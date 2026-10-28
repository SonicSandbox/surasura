"""K5 C2 (alpha 4, the large-library copy): a look's new books are hashed and split by worker processes a few ahead of
it, and their parts written and flushed by a thread pool, while the look alone checks and takes each in. The proof:
the library a look makes with the pools is the one it makes without them — the same items, copies, bytes and records
— and every way the work done ahead can go wrong (the file changed after its worker read it, a worker that failed, a
part that can't be written, a Stop) ends exactly as the look alone ends. *Use every core* (C4) sizes the pools."""
import os
import shutil

import pytest

from app import library_store as ls
from app import sources, token_index
from tests.test_library_store_support import LANGUAGES, roots
from tests.test_sources_k5_tables import _chapters
from tests.test_sources_scan import _drive, _empty, _epub, _fresh_module_state, _look  # noqa: F401

_NAMES = ("星の歌", "月の庭", "風の便り", "海の声", "空の色")


def _shelf(language, src):
    for n, name in enumerate(_NAMES):
        _epub(os.path.join(src, "Shelf" if n % 2 else "Shelf/Author", f"{name}.epub"), _chapters(language, n))


def _library(store, data_dir):
    """Everything a look leaves: each item's copy (its path and bytes) and its origin record, by the origin."""
    items = {r[0]: r[1:] for r in store.conn.execute("SELECT id, rel_path, size, availability, tier FROM items")}
    out = {}
    for key, o in store.origins().items():
        rel = items[o.item_id][0]
        with open(os.path.join(data_dir, *rel.split("/")), "rb") as f:
            body = f.read()
        out[key] = (rel, items[o.item_id][1:], o.sha256, o.chapter, o.version, body)
    return out


def _pooled(monkeypatch, size=2):
    """The pools on for any number of books (the app's own threshold is POOL_MIN_FILES), at `size` workers."""
    monkeypatch.setattr(token_index, "pool_workers", lambda n, *a, **k: size)


def _start_over(language):
    """The test's library gone whole (its store, its folders, this run's looks), so a second first look in one test
    starts where the first did — the store is keyed by the data folder's path, the same folder each time. The books
    stay as they are (an EPUB written again is other bytes: its zip's times)."""
    data_dir, user_files_dir = roots(language)
    db = ls.library_db_path(language, data_dir)
    for path in (db, db + "-wal", db + "-shm"):
        if os.path.exists(path):
            os.remove(path)
    for folder in (data_dir, user_files_dir):
        shutil.rmtree(folder, ignore_errors=True)
    sources._LOOKED.clear()


def _first_look(language, monkeypatch=None, pooled=False):
    store, data_dir = _empty(language)
    src = _drive("books")
    if not os.listdir(src):
        _shelf(language, src)
    if pooled:
        _pooled(monkeypatch)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        return result, _library(store, data_dir), store, data_dir, src, root


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_first_look_with_the_pools_makes_the_library_a_look_alone_makes(language, monkeypatch):
    """Why: the workers only do ahead what the look would do itself; a book split by a worker must be the book the
    look splits (its parts, their names, chapters and bytes, their records), or two Surasuras would disagree."""
    taken = []
    real = sources._Look._prepared

    def prepared(self, path, st):
        got = real(self, path, st)
        taken.append(got is not None)
        return got
    monkeypatch.setattr(sources._Look, "_prepared", prepared)
    alone, want, *_ = _first_look(language)
    taken.clear()
    _start_over(language)
    pooled, got, *_ = _first_look(language, monkeypatch, pooled=True)
    assert taken and all(taken), "every book's work came from a worker"
    assert {k: v for k, v in alone.items() if k != "ids"} == {k: v for k, v in pooled.items() if k != "ids"}
    assert [(v[0], v[2:]) for _k, v in sorted(got.items())] == [(v[0], v[2:]) for _k, v in sorted(want.items())]


@pytest.mark.parametrize("why", ["changed", "failed", "raised"])
def test_work_done_ahead_that_doesnt_fit_the_file_is_done_again_by_the_look(why, monkeypatch):
    """Why: a worker reads the EPUB a moment before the look takes it; a file changed meanwhile (its size or time
    differ from the listing's), a worker that failed or a pool that broke must never hand the look someone else's
    parts — the look reads the book itself, and the library is the same."""
    language = "ja"
    alone, want, *_ = _first_look(language)
    _start_over(language)
    real = sources._Splitter.take

    def take(self, path):
        got = real(self, path)
        if why == "changed":
            return (got[0] + 1,) + got[1:] if got else got
        return None                                          # a worker that failed: `take`'s own answer

    def fill(self, at):                                      # every worker raises: `take` answers None itself
        while self.next < len(self.paths) and self.next < at + self.ahead:
            self.futures[self.paths[self.next]] = self.pool.submit(int, "not a number")
            self.next += 1
    if why == "raised":
        monkeypatch.setattr(sources._Splitter, "_fill", fill)
    else:
        monkeypatch.setattr(sources._Splitter, "take", take)
    _pooled(monkeypatch)
    got_result, got, *_ = _first_look(language)
    assert [(v[0], v[2:]) for _k, v in sorted(got.items())] == [(v[0], v[2:]) for _k, v in sorted(want.items())]
    assert got_result["added"] == alone["added"]


def test_a_part_that_cant_be_written_leaves_no_part_file_and_the_book_waits(monkeypatch):
    """Why: the writing threads flush a book's parts side by side; one that fails must still leave nothing behind
    (no `.part`, no copy of that book) and the book waits for the next look — as the look alone does — while the other
    books come in; the next look then takes it in."""
    language = "ja"
    _pooled(monkeypatch)
    real = sources._write_part
    failed = []

    def write(part, data):
        if "月の庭" in part and not failed:
            failed.append(part)
            raise OSError("the disk said no")
        return real(part, data)
    monkeypatch.setattr(sources, "_write_part", write)
    result, got, store, data_dir, src, root = _first_look(language, monkeypatch, pooled=True)
    assert failed
    left = [os.path.join(w, f) for w, _d, fs in os.walk(os.path.join(data_dir, ls.CONTENT_FOLDER)) for f in fs
            if f.endswith(".part") or "月の庭" in f]
    assert left == []
    assert {v[0].split("/")[1] for v in got.values()} == set(_NAMES) - {"月の庭"}
    with ls.open_store(language, data_dir, roots(language)[1]) as store:
        sources._LOOKED.clear()
        again = _look(store, language, root, full=True)
        books = {r[0].split("/")[1] for r in store.conn.execute("SELECT rel_path FROM items")}
    assert again["added"] > 0 and books == set(_NAMES)


def test_a_stop_ends_the_take_and_closes_the_pools(monkeypatch):
    """Why: Stop on setup's page 3 must end a long copy at once — the books already taken in kept, nothing split
    ahead taken in after it, and no worker left running."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("books")
    _shelf(language, src)
    _pooled(monkeypatch)
    books = []
    real = sources._Look._book

    def book(self, *c):
        books.append(c[1])
        return real(self, *c)
    monkeypatch.setattr(sources._Look, "_book", book)
    seen = {}
    waits = []
    real_close = sources._Splitter.close
    monkeypatch.setattr(sources._Splitter, "close", lambda self, wait=True: (waits.append(wait), real_close(self, wait)))
    real_pools = sources._Look._pools

    def pools(self, epubs):
        real_pools(self, epubs)
        seen.setdefault("open" if epubs else "closed", (self.splitter, self.writers))
    monkeypatch.setattr(sources._Look, "_pools", pools)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True, stop=lambda: len(books) >= 2)
        n = store.conn.execute("SELECT COUNT(DISTINCT work_id) FROM items").fetchone()[0]
    assert result["stopped"] and len(books) == 2 and n == 2
    splitter, writers = seen["open"]
    assert splitter is not None and writers is not None
    assert seen["closed"] == (None, None)
    assert splitter.pool._shutdown_thread and writers._shutdown
    assert waits == [False]                                  # Stop: the splits under way are not waited for


def test_use_every_core_sizes_the_pools_at_every_core_and_reads_off_when_unset(monkeypatch):
    """Why (C4): *Use every core* is the learner's choice to read a big library sooner; off (the default, or settings
    that can't be read) the indexer and a look keep half the cores, so the computer stays quick to use."""
    assert token_index.pool_workers(1000, cpus=24, free_mb=64000) == 12
    assert token_index.pool_workers(1000, cpus=24, free_mb=64000, every=True) == 24
    assert token_index.pool_workers(1000, cpus=24, free_mb=1000, every=True) == 5        # half the free memory
    assert token_index.pool_workers(10, cpus=24, free_mb=64000, every=True) == 1         # under POOL_MIN_FILES
    from app import settings_manager
    monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: {"use_every_core": True})
    assert token_index.every_core() is True
    monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: {})
    assert token_index.every_core() is False

    def broken(*a, **k):
        raise OSError("settings.json held")
    monkeypatch.setattr(settings_manager, "load_settings", broken)
    assert token_index.every_core() is False


def test_a_book_the_look_passed_by_is_let_go_and_the_workers_stay_ahead_of_the_look():
    """Why: a book split ahead that the look then passes by (its path kept out, its file changed) must not hold its
    parts until the look ends — 25,000 books' worth would be gigabytes; the workers keep SPLIT_AHEAD per worker in
    hand ahead of the book the look takes."""
    src = _drive("books")
    _shelf("ja", src)
    paths = sorted(os.path.join(w, f) for w, _d, fs in os.walk(src) for f in fs if f.endswith(".epub"))
    splitter = sources._Splitter(paths, "ja", 1, ())
    try:
        assert set(splitter.futures) == set(paths[:sources.SPLIT_AHEAD])
        got = splitter.take(paths[1])                                # the look passed paths[0] by
        assert got is not None and got[2] == ls.sha256_of(paths[1]) and got[5] is True
        assert set(splitter.futures) == set(paths[2:2 + sources.SPLIT_AHEAD])
        assert splitter.take(paths[0]) is None                       # let go of: the look would read it itself
    finally:
        splitter.close()


def test_after_books_the_look_skipped_the_workers_never_split_one_it_has_passed():
    """Why (review): books the look passes by without asking (a file still being copied, a path kept out) left the
    window behind; the next book's take then queued every passed book again ahead of the ones it needs — wasted
    splits the look waited behind."""
    src = _drive("books")
    _shelf("ja", src)
    paths = sorted(os.path.join(w, f) for w, _d, fs in os.walk(src) for f in fs if f.endswith(".epub"))
    splitter = sources._Splitter(paths, "ja", 1, ())
    try:
        splitter.take(paths[2])                                      # paths[0] and [1] passed by unasked
        assert set(splitter.futures) == set(paths[3:3 + sources.SPLIT_AHEAD])
    finally:
        splitter.close()


def test_the_look_sizes_its_pools_as_the_indexer_does_with_index_pool_workers(monkeypatch):
    """Why (review): settings.json's `index_pool_workers` (a learner's own cap, 1 = one process) is how many processes
    the indexer takes; the look's pools take the same answer, never more."""
    from app import settings_manager
    asked = []
    monkeypatch.setattr(settings_manager, "load_settings",
                        lambda *a, **k: {"index_pool_workers": 1, "use_every_core": True})
    monkeypatch.setattr(token_index, "pool_workers", lambda n, setting=None, *a, **k: (asked.append((setting, k)), 1)[1])
    result, got, *_ = _first_look("ja")
    assert asked == [(1, {"every": True})]
    assert result["added"] > 0 and got


def test_a_write_that_fails_cancels_the_parts_not_started_and_a_shut_pool_writes_here(tmp_path, monkeypatch):
    """Why (review): after one part fails the whole book waits, so the parts not started yet are never written (the
    look alone stopped at the first failure); a pool shut meanwhile (the app closing) never leaves parts unwritten
    or half the book behind — this thread writes the rest."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(str(tmp_path / f"{n}.part"), "第{}章".format(n).encode("utf-8")) for n in range(6)]
    real = sources._write_part

    def write(part, data):
        if part.endswith("0.part"):
            raise OSError("the disk said no")
        return real(part, data)
    monkeypatch.setattr(sources, "_write_part", write)
    with ThreadPoolExecutor(1) as pool:
        with pytest.raises(OSError, match="the disk said no"):
            sources._write_parts_at_once(pool, jobs)
    assert sorted(os.listdir(tmp_path)) == []                        # one thread: 0 failed, 1-5 never started
    monkeypatch.setattr(sources, "_write_part", real)
    pool = ThreadPoolExecutor(2)
    pool.shutdown()
    sources._write_parts_at_once(pool, jobs)
    assert sorted(os.listdir(tmp_path)) == sorted(os.path.basename(p) for p, _d in jobs)
