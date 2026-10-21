"""Start a fresh library (K7, laptop fixes; FEEDBACK row 8's trap): `library_store.start_fresh` — Surasura's own
library state for a language set aside into one dated backup, the store emptied in one write, the folders it reads
kept (and read again from scratch by the caller), known words kept unless asked.

What a wrong answer would cost a learner:
  * the old library coming back by itself — the JSON copy (`master_manifest.json`) left beside an emptied store is
    rebuilt from (item 8: every item back, pointing at copies that are gone, never copied again), and a 2.x tier
    folder left in `data/<lang>` is walked back in;
  * a library lost: a backup that isn't whole, or a crash between the steps that leaves neither the old library in
    place nor a backup to put back by hand;
  * his own folders written to (they are only ever read), his known words forgotten when he didn't ask;
  * a reset that runs over a Generate, Connect or the helper writing the same store.

Real Japanese / Chinese subtitles and texts from tests/Test Resources/ (the scan tests' helpers), made-up show names;
every source folder sits beside the data folder under SURASURA_TEST_ROOT ("elsewhere"), and every look goes through
`_look`, which proves nothing under it changed.
"""
import json
import os
import shutil
import sqlite3
import threading

import pytest

from app import library_store as ls
from app import locks, sources
from tests.test_library_store_support import LANGUAGES, library, names, touch, write_manifest
from tests.test_sources_scan import _SHOWS, _drive, _look, _text, _tree, _write


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Each test starts as a new run of the app: no look made yet this run, no scan running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


class _Killed(BaseException):
    """A process killed between two steps: no `except Exception` sees it, so nothing is put back for it."""


# --- the world ----------------------------------------------------------------------------------------------------- #

def _world(language):
    """A library as a laptop holds one after an upgrade: a 2.x upgrade's copied tier folders (now, soon), a source folder read in
    (two shows, copies under Library/), one episode removed (an exclusion; its copy in data/.trash), hato's drop
    (HighPriority/Hato), an order moved by hand, a log reader, the folder-time cache and KnownWord.json."""
    data_dir, user_files_dir, doc = library(language, shows=1, episodes=2, loose=1, tiers=("now", "soon"))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    store.register_reader("connect")                                   # the placement log is written
    a, b = _SHOWS[language]
    src = _drive("driveA")
    for n in (1, 2, 3):
        _write(os.path.join(src, a, f"{a} - {n:02d}.srt"), _text(language, n))
    _write(os.path.join(src, b, f"{b} - 01.srt"), _text(language, 4))
    root = store.add_source(src)
    ids = _look(store, language, root, first=True)["ids"]
    assert len(ids) == 4
    gone = ids[2]                                                      # Remove, as the window does it
    trashed = ls.trash_file(data_dir, store.item(gone)["rel_path"])
    store.remove([gone], trashed_paths={gone: trashed})
    hato = touch(data_dir, ls.HATO_FOLDER + "/" + names(language)[71] + ".srt", _text(language, 5))
    store.insert([hato], "now")
    now = store.ids("now")
    store.move([now[-1]], "now", before_id=now[0])                     # an order of his own
    store.set_library_options(mine_line=7)                              # his own mine line (an option, it stays)
    assert store.conn.execute("SELECT COUNT(*) FROM exclusions").fetchone()[0] == 1
    assert os.path.exists(sources.cache_path(language))                # the look kept its folder times
    assert ls.export_copy(store)                                       # the JSON copy is up to date, as after a close
    known = os.path.join(user_files_dir, "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        json.dump({"exportDate": "2026-10-20T08:00:00", "source": "anki", "statistics": {},
                   "words": [{"dictForm": w} for w in names(language)[:5]]}, f, ensure_ascii=False, indent=2)
    return store, data_dir, user_files_dir, src, root


def _rows(store):
    """The library's own rows: every item (path, tier, place), and the counts of every table it keeps."""
    items = [tuple(r) for r in store.conn.execute("SELECT id, rel_path, tier, ord FROM items ORDER BY tier, ord, id")]
    counts = {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("items", "pairings", "exclusions", "trash", "works", "pieces", "placement_log")}
    return items, counts


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _state(store, data_dir, user_files_dir):
    """Everything the reset may touch, to prove it untouched (a refusal) or put back (a failure)."""
    return (_rows(store), _tree(data_dir), _bytes(ls.manifest_path(user_files_dir)),
            _bytes(os.path.join(user_files_dir, "KnownWord.json")))


def _backups(user_files_dir):
    trash = os.path.join(user_files_dir, ".trash")
    if not os.path.isdir(trash):
        return []
    return sorted(os.path.join(trash, n) for n in os.listdir(trash) if n.startswith(ls.RESET_PREFIX))


def _record(folder):
    with open(os.path.join(folder, ls.RESET_RECORD), encoding="utf-8") as f:
        return json.load(f)


def _restore_by_hand(record, db_path):
    """What a user is told to do with the app closed, from reset.json alone: every move undone (what got as far
    as the backup goes back to where it came from) and, when the store was written, its copy put back over it."""
    for move in reversed(record["moves"]):
        if not os.path.exists(move["to"]):
            continue                                                    # never got that far: still in its place
        os.makedirs(os.path.dirname(move["from"]), exist_ok=True)
        if os.path.isdir(move["to"]):
            shutil.copytree(move["to"], move["from"], dirs_exist_ok=True)
            shutil.rmtree(move["to"])
        else:
            os.replace(move["to"], move["from"])                       # over the fresh copy an export wrote
    if record["status"] in ("written", "done"):
        for suffix in ("-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.remove(db_path + suffix)
        shutil.copyfile(record["db_copy"], db_path)


def _sources_read_again(store, language):
    """What the window's looks do right after (`SourceLooks.fresh`): each folder being read, a first look in full."""
    for row in store.sources():
        _look(store, language, row["id"], first=True)


# --- a reset ------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_fresh_library_keeps_the_folders_reads_them_again_and_backs_up_everything_it_set_aside(language):
    store, data_dir, user_files_dir, src, root = _world(language)
    (old_items, old_counts), _t, manifest, known = _state(store, data_dir, user_files_dir)
    old_sources = store.sources()
    old_meta = store.meta()
    cache = _bytes(sources.cache_path(language))
    source_before = _tree(src)
    with store:
        answer = ls.start_fresh(store)
        # the store holds nothing of the old library; the folders are kept, as they were
        items, counts = _rows(store)
        assert items == [] and set(counts.values()) == {0}
        assert [(s["id"], s["path"], s["on"]) for s in store.sources()] == \
               [(s["id"], s["path"], s["on"]) for s in old_sources]
        meta = store.meta()
        assert meta["store_id"] != old_meta["store_id"]                 # a new library (Connect's old jobs drop)
        assert meta["epoch"] == old_meta["epoch"] + 1                   # every window and the folder cache reload
        assert meta["state_version"] > old_meta["state_version"]
        assert meta["order_version"] > old_meta["order_version"]
        assert meta["mine_line"] == old_meta["mine_line"] and meta["arrivals_on"] == old_meta["arrivals_on"]
        assert meta["mine_line"] == 7 and meta["reader:connect"] == old_meta["reader:connect"]   # Connect reads on
        assert meta["log_seq"] == old_meta["log_seq"]
        assert not os.path.exists(sources.cache_path(language))         # the folder times set aside
        # nothing of the old library is left where Surasura would walk it back in
        assert [p for p in _tree(data_dir) if p[1] is not None] == []
        # the folders read again from scratch: every episode back once, in Current (setup's first scan)
        _sources_read_again(store, language)
        items, counts = _rows(store)
        rels = [r[1] for r in items]
        assert len(rels) == 4 and len(set(rels)) == 4
        assert {r[2] for r in items} <= set(ls.CURRENT)
        assert all(r.startswith(ls.CONTENT_FOLDER + "/") for r in rels)
        assert ids_not_reused(old_items, items)
    assert _tree(src) == source_before                                  # his folder only ever read
    # one backup folder, holding all of it
    (folder,) = _backups(user_files_dir)
    assert answer["backup"] == folder
    record = _record(folder)
    assert record["status"] == "done" and record["language"] == language
    copy = sqlite3.connect(record["db_copy"])
    try:
        held = [tuple(r) for r in copy.execute("SELECT id, rel_path, tier, ord FROM items ORDER BY tier, ord, id")]
        assert held == old_items                                        # the store's copy: openable, the same rows
        assert copy.execute("SELECT COUNT(*) FROM exclusions").fetchone()[0] == old_counts["exclusions"]
    finally:
        copy.close()
    assert _bytes(os.path.join(folder, ls.MANIFEST_NAME)) == manifest
    assert _bytes(os.path.join(folder, os.path.basename(sources.cache_path(language)))) == cache
    moved = os.path.join(folder, "data")
    for rel in ("HighPriority", "LowPriority", ls.CONTENT_FOLDER, ".trash", ls.HATO_FOLDER):
        assert os.path.isdir(os.path.join(moved, *rel.split("/"))), rel
    assert os.listdir(os.path.join(moved, ".trash"))                    # the removed episode's copy
    froms = {os.path.normcase(m["from"]) for m in record["moves"]}
    assert os.path.normcase(ls.manifest_path(user_files_dir)) in froms
    assert _bytes(os.path.join(user_files_dir, "KnownWord.json")) == known   # known words kept (not ticked)
    assert answer["known"] == "kept"


def ids_not_reused(old_items, new_items):
    """K30: an item id is never issued twice — Connect's ledger and the cards name items by id."""
    return not ({r[0] for r in old_items} & {r[0] for r in new_items})


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_old_library_never_comes_back_when_the_store_reopens_or_its_database_is_lost(language):
    # Item 8's trap: a store whose database is gone rebuilds itself from master_manifest.json
    store, data_dir, user_files_dir, src, root = _world(language)
    with store:
        ls.start_fresh(store)
        _sources_read_again(store, language)
        fresh = sorted(r[1] for r in _rows(store)[0])
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        assert sorted(r[1] for r in _rows(store)[0]) == fresh
    # The database deleted by hand, the JSON copy left beside it
    db = ls.library_db_path(language, data_dir)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        assert sorted(r[1] for r in _rows(store)[0]) == fresh            # the fresh library, never the old one
        assert [s["path"] for s in store.sources()] == [ls.folder_path(src)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_forget_my_known_words_backs_the_file_up_and_leaves_an_empty_one(language):
    store, data_dir, user_files_dir, src, root = _world(language)
    known = os.path.join(user_files_dir, "KnownWord.json")
    before = _bytes(known)
    with store:
        answer = ls.start_fresh(store, forget_known=True)
    assert answer["known"] == "forgotten"
    with open(known, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["words"] == [] and "exportDate" in doc                  # the file's own format, empty
    dated = [n for n in os.listdir(os.path.join(user_files_dir, ".trash"))
             if n.startswith("KnownWord.") and n.endswith(".json")]
    assert len(dated) == 1 and _bytes(os.path.join(user_files_dir, ".trash", dated[0])) == before
    (folder,) = _backups(user_files_dir)
    assert _bytes(os.path.join(folder, "KnownWord.json")) == before


# --- refusals: nothing changed ------------------------------------------------------------------------------------- #

def _hold_elsewhere(path):
    """Another process's OS lock on byte 0 of `path` (a second handle: Windows and fcntl both refuse a second taker)."""
    lock = ls._FileLock(path, byte_range=path.endswith(".wlock"))
    assert lock.try_acquire()
    return lock


@pytest.mark.parametrize("held", ["write", "helper", "generate", "connect", "update", "known"])
def test_a_reset_is_refused_with_a_reason_while_another_program_writes_and_nothing_changes(held, monkeypatch):
    store, data_dir, user_files_dir, src, root = _world("ja")
    before = _state(store, data_dir, user_files_dir)
    cache = _bytes(sources.cache_path("ja"))
    undo = None
    if held == "write":
        monkeypatch.setattr(ls, "RESET_WAIT", 0.2)
        undo = _hold_elsewhere(store.db_path + ".wlock")
    elif held == "helper":
        undo = _hold_elsewhere(store.db_path + ".lock")
    elif held in ("generate", "connect", "known"):
        name = {"generate": "results", "connect": "connect", "known": "known-words-ja"}[held]
        took = []
        ready, done = threading.Event(), threading.Event()

        def hold():                                                     # another program's hold
            with locks.take(name, f"a test's {held}"):
                ready.set()
                done.wait(10)
        t = threading.Thread(target=hold)
        t.start()
        assert ready.wait(5)
        undo = (t, done)
    else:
        monkeypatch.setattr(ls, "update_staged", lambda *a, **k: True)
    try:
        with pytest.raises(ls.ResetRefused) as refused:
            ls.start_fresh(store, forget_known=(held == "known"))
        assert refused.value.reason
        assert _state(store, data_dir, user_files_dir) == before         # nothing changed
        assert _bytes(sources.cache_path("ja")) == cache
        assert _backups(user_files_dir) == []
    finally:
        if isinstance(undo, tuple):
            undo[1].set()
            undo[0].join(5)
        elif undo is not None:
            undo.close()
        store.close()


def test_a_backup_copy_that_isnt_whole_stops_the_reset_before_anything_moves(monkeypatch):
    store, data_dir, user_files_dir, src, root = _world("zh")
    before = _state(store, data_dir, user_files_dir)
    real = ls._copy_db

    def short(conn, dest):                                              # a copy missing a row
        real(conn, dest)
        c = sqlite3.connect(dest)
        c.execute("DELETE FROM items WHERE id = (SELECT MAX(id) FROM items)")
        c.commit()
        c.close()
    monkeypatch.setattr(ls, "_copy_db", short)
    with store:
        with pytest.raises(ls.StoreError):
            ls.start_fresh(store)
        assert _state(store, data_dir, user_files_dir) == before


# --- crash safety: the old library is in place, or restorable from the backup -------------------------------------- #

STEPS = ("folder", "backup", "manifest", "cache", "data", "wipe", "write", "export", "known")


@pytest.mark.parametrize("step", STEPS)
def test_a_kill_between_any_two_steps_leaves_the_old_library_in_place_or_restorable_by_hand(step):
    store, data_dir, user_files_dir, src, root = _world("ja")
    db = store.db_path
    (old_items, _c), old_tree, manifest, known = _state(store, data_dir, user_files_dir)

    def kill(name):
        if name == step:
            raise _Killed(name)
    with pytest.raises(_Killed):
        ls.start_fresh(store, forget_known=True, _step=kill)
    store.close()
    folders = _backups(user_files_dir)
    if folders:                                                         # what the record says is enough to undo it
        _restore_by_hand(_record(folders[0]), db)
    store = ls.open_store("ja", data_dir, user_files_dir)
    with store:
        assert _rows(store)[0] == old_items
    assert [p[:3] for p in _tree(data_dir)] == [p[:3] for p in old_tree]   # every file back, the same bytes
    assert _bytes(ls.manifest_path(user_files_dir)) == manifest
    if step != "known" or not folders:                                 # killed before the words were forgotten
        assert _bytes(os.path.join(user_files_dir, "KnownWord.json")) == known


@pytest.mark.parametrize("step", ("folder", "backup", "manifest", "cache", "data", "wipe"))
def test_a_failure_before_the_write_puts_everything_back_itself(step):
    store, data_dir, user_files_dir, src, root = _world("zh")
    before = _state(store, data_dir, user_files_dir)
    cache = _bytes(sources.cache_path("zh"))

    def fail(name):
        if name == step:
            raise OSError(f"disk full at {name}")
    with store:
        with pytest.raises(OSError):
            ls.start_fresh(store, _step=fail)
        rows, tree, manifest, known = _state(store, data_dir, user_files_dir)
        assert rows == before[0] and manifest == before[2] and known == before[3]
        assert [p[:3] for p in tree] == [p[:3] for p in before[1]]       # every file back, the same bytes
    assert _bytes(sources.cache_path("zh")) == cache
    for folder in _backups(user_files_dir):
        assert _record(folder)["status"] == "undone"


def test_a_folder_that_cant_be_renamed_is_copied_verified_then_removed(monkeypatch):
    # data/<lang> beside the program and User Files are one volume in practice; a rename refused (another volume, a
    # folder held open by a watch) falls back to copy, check every byte, remove
    store, data_dir, user_files_dir, src, root = _world("ja")
    old_tree = _tree(data_dir)
    real = os.rename

    def no_rename(a, b, *args, **kw):
        if os.path.normcase(os.path.abspath(a)).startswith(os.path.normcase(os.path.abspath(data_dir))):
            raise OSError(18, "Invalid cross-device link")
        return real(a, b, *args, **kw)
    monkeypatch.setattr(ls.os, "rename", no_rename)
    with store:
        answer = ls.start_fresh(store)
    assert [p for p in _tree(data_dir) if p[1] is not None] == []
    moved = os.path.join(answer["backup"], "data")
    held = {(p[0], p[1]) for p in _tree(moved) if p[1] is not None}
    assert held == {(p[0], p[1]) for p in old_tree if p[1] is not None}


def test_a_fallback_copy_that_doesnt_match_keeps_the_original_and_puts_everything_back(monkeypatch):
    # a copy that lost bytes must never be the only copy left: the original stays, the reset is undone
    store, data_dir, user_files_dir, src, root = _world("zh")
    before = _state(store, data_dir, user_files_dir)
    real_rename, real_copytree = os.rename, shutil.copytree

    def no_rename(a, b, *args, **kw):
        if os.path.normcase(os.path.abspath(a)).startswith(os.path.normcase(os.path.abspath(data_dir))):
            raise OSError(18, "Invalid cross-device link")
        return real_rename(a, b, *args, **kw)

    def short_copy(a, b, *args, **kw):
        out = real_copytree(a, b, *args, **kw)
        for where, _d, files in os.walk(b):
            for name in files:
                with open(os.path.join(where, name), "r+b") as f:
                    f.truncate(1)                                        # the copy lost bytes
                return out
        return out
    monkeypatch.setattr(ls.os, "rename", no_rename)
    monkeypatch.setattr(shutil, "copytree", short_copy)
    with store:
        with pytest.raises(OSError):
            ls.start_fresh(store)
        rows, tree, manifest, known = _state(store, data_dir, user_files_dir)
        assert rows == before[0] and manifest == before[2]
        assert [p[:3] for p in tree] == [p[:3] for p in before[1]]


def test_a_folder_he_said_never_to_read_stays_with_the_folders(monkeypatch):
    # an exclusion that isn't Remove's is about how his folders are read, not the library: it stays
    store, data_dir, user_files_dir, src, root = _world("ja")
    with store:
        with store._writing():
            store.conn.execute("INSERT INTO exclusions (root_id, pattern, kind, created_at, note) VALUES "
                               "(?, ?, 'never-read', ?, NULL)", (root, ls.path_key(os.path.join(src, "extras")),
                                                                 ls._now()))
        ls.start_fresh(store)
        kinds = [r[0] for r in store.conn.execute("SELECT kind FROM exclusions")]
    assert kinds == ["never-read"]


# --- the review fix round (LF register: H1/LF-6, LF-4, H2, I-R1/LF-5, I-R4, I-R5/LF-8, I-R8/LF-11) ------------------ #

def _no_rename_in(data_dir):
    real = os.rename

    def no_rename(a, b, *args, **kw):
        if os.path.normcase(os.path.abspath(a)).startswith(os.path.normcase(os.path.abspath(data_dir))):
            raise PermissionError(13, "held open by a watch")
        return real(a, b, *args, **kw)
    return no_rename


def test_a_removal_that_stops_part_way_puts_every_copy_back_and_never_over_an_original(monkeypatch):
    # H1 / LF-6: Library can't be renamed (a watch holds it), so it is copied, checked, then removed — and the 2nd
    # removal fails. The move must count as begun: every copy already removed comes back from the backup, the ones
    # never removed are left exactly as they were (never written over), and the record says "undone"
    store, data_dir, user_files_dir, src, root = _world("ja")
    before = _state(store, data_dir, user_files_dir)
    lib = os.path.normcase(os.path.join(data_dir, ls.CONTENT_FOLDER)) + os.sep
    real_remove, count = os.remove, [0]

    def remove(p, *args, **kw):
        if os.path.normcase(os.path.abspath(p)).startswith(lib):
            count[0] += 1
            if count[0] == 2:
                raise PermissionError(13, "held open by a player")
        return real_remove(p, *args, **kw)
    real_rename = os.rename
    monkeypatch.setattr(ls.os, "rename", _no_rename_in(data_dir))
    monkeypatch.setattr(ls.os, "remove", remove)
    with store:
        with pytest.raises(OSError):
            ls.start_fresh(store)
        monkeypatch.setattr(ls.os, "rename", real_rename)              # (never `undo`: it drops the test root too)
        monkeypatch.setattr(ls.os, "remove", real_remove)
        rows, tree, manifest, known = _state(store, data_dir, user_files_dir)
        assert rows == before[0] and manifest == before[2]
        assert [p[:3] for p in tree] == [p[:3] for p in before[1]]       # every copy back, the same bytes
    (folder,) = _backups(user_files_dir)
    assert _record(folder)["status"] == "undone" and "not_put_back" not in _record(folder)


def test_a_put_back_never_writes_over_the_file_left_in_place(tmp_path):
    # H1: a move whose byte check failed leaves the original in place and bad bytes in the backup; the put-back
    # copies back only what is missing at the source, never over it
    src, dst = tmp_path / "data" / "Library", tmp_path / "backup" / "Library"
    for where in (src, dst):
        (where / "Show").mkdir(parents=True)
    (src / "Show" / "01.srt").write_text(_text("ja", 1), encoding="utf-8")          # still in place
    (dst / "Show" / "01.srt").write_bytes(b"\x00")                                  # the bad copy
    (dst / "Show" / "02.srt").write_text(_text("ja", 2), encoding="utf-8")          # removed from the source
    ls._put_back(str(dst), str(src))
    assert (src / "Show" / "01.srt").read_text(encoding="utf-8") == _text("ja", 1)
    assert (src / "Show" / "02.srt").read_text(encoding="utf-8") == _text("ja", 2)


def test_each_move_is_put_back_on_its_own_and_one_that_cant_be_is_named(monkeypatch):
    # H1: one put-back failing never keeps the others away; the record names it, and the answer is never "nothing
    # was changed" (ResetNotAllBack names the backup folder)
    store, data_dir, user_files_dir, src, root = _world("zh")
    before = _state(store, data_dir, user_files_dir)
    real = ls._put_back

    def put_back(dst, src_path):
        if os.path.basename(src_path) == ls.MANIFEST_NAME:
            raise PermissionError(13, "the JSON copy is held open")
        return real(dst, src_path)
    monkeypatch.setattr(ls, "_put_back", put_back)

    def fail(name):
        if name == "wipe":
            raise OSError("disk full at the write")
    with store:
        with pytest.raises(ls.ResetNotAllBack) as e:
            ls.start_fresh(store, _step=fail)
        assert _rows(store) == before[0]
        assert [p[:3] for p in _tree(data_dir)] == [p[:3] for p in before[1]]   # data/ came back all the same
    (folder,) = _backups(user_files_dir)
    assert e.value.folder == folder
    record = _record(folder)
    assert record["status"] == "undone"
    assert [m["from"] for m in record["not_put_back"]] == [ls.manifest_path(user_files_dir)]
    assert os.path.exists(os.path.join(folder, ls.MANIFEST_NAME))      # the JSON copy is safe in the backup


@pytest.mark.skipif(os.name != "nt", reason="a junction is Windows' own")
def test_a_junction_in_the_data_folder_refuses_the_reset_before_anything_is_copied_or_removed(monkeypatch):
    # LF-4: a 2.x user linked his own show folder into a tier folder. Python 3.11 walks a junction as a plain folder,
    # so the fallback's removal would delete HIS file in HIS folder; it is refused, everything put back, his folder
    # untouched, and the reason says a linked folder is in the way
    import _winapi
    store, data_dir, user_files_dir, src, root = _world("ja")
    his = os.path.join(os.path.dirname(data_dir), "elsewhere", "his own", "Linked Show")
    mine = _write(os.path.join(his, "Linked Show - 01.srt"), _text("ja", 6))
    his_before = _tree(his)
    tier = next(n for n in sorted(os.listdir(data_dir)) if os.path.isdir(os.path.join(data_dir, n)) and
                n != ls.CONTENT_FOLDER and not n.startswith("."))
    link = os.path.join(data_dir, tier, "Linked", "Linked Show")              # a folder down: found walking in
    os.makedirs(os.path.dirname(link))
    _winapi.CreateJunction(his, link)
    rows, manifest = _rows(store), _bytes(ls.manifest_path(user_files_dir))
    real_rename = os.rename
    monkeypatch.setattr(ls.os, "rename", _no_rename_in(data_dir))
    try:
        with store:
            with pytest.raises(ls.ResetRefused) as refused:
                ls.start_fresh(store)
            monkeypatch.setattr(ls.os, "rename", real_rename)
            assert refused.value.reason == ls.RESET_LINKED.format(path=link)
            assert _rows(store) == rows and _bytes(ls.manifest_path(user_files_dir)) == manifest
        assert _tree(his) == his_before and os.path.exists(mine)            # his own file, never touched
        assert os.path.isdir(link)                                           # the link still there, as he made it
        (folder,) = _backups(user_files_dir)
        assert _record(folder)["status"] == "undone"
    finally:
        os.rmdir(link)                                                      # the link only, never his folder
        os.rmdir(os.path.dirname(link))


def test_connects_never_again_words_and_lines_stay_through_a_reset():
    # I-R1 / LF-5: `made_words` / `made_lines` are Connect's "never made again" (G1.3-4): a card he deleted must not
    # be made again in his Anki after a fresh library
    from app.connect import library
    store, data_dir, user_files_dir, src, root = _world("ja")
    with store:
        item = store.ids("now")[0]
        word = names("ja")[3]
        library.record_batch(store, item, {word: [111]}, ls._now())
        assert store.record_lines(item, [(222, 1000, 2000, names("ja")[4])]) == [222]
        lines = store.conn.execute("SELECT * FROM made_lines").fetchall()
        ls.start_fresh(store)
        assert word in library.made_words_all(store)
        assert store.conn.execute("SELECT * FROM made_lines").fetchall() == lines
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0     # the library itself is fresh


def test_after_the_commit_no_failure_is_the_resets_and_its_record_says_written(monkeypatch):
    # H2: once the one write is committed the library IS fresh: the JSON copy, the known words (a non-OSError) and
    # the last record write failing are logged, never raised — so the window never says "Nothing was changed"
    from app import anki_sync
    store, data_dir, user_files_dir, src, root = _world("ja")
    known = _bytes(os.path.join(user_files_dir, "KnownWord.json"))
    monkeypatch.setattr(ls, "export_copy", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("export broke")))
    monkeypatch.setattr(anki_sync, "_atomic_write_json",
                        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("an odd entry")))
    real = ls._write_record

    def write_record(folder, record):
        if record["status"] == "done":
            raise RuntimeError("the record's last write broke")
        return real(folder, record)
    monkeypatch.setattr(ls, "_write_record", write_record)
    with store:
        answer = ls.start_fresh(store, forget_known=True)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    assert answer["known"].startswith("kept") and answer["sources"] == [root]
    assert _record(answer["backup"])["status"] == "written"             # the commit's own record
    assert _bytes(os.path.join(user_files_dir, "KnownWord.json")) == known


def test_known_words_that_couldnt_be_forgotten_are_never_recorded_as_forgotten(monkeypatch):
    # H2: the record named a known-words backup as if the words were forgotten when the write failed
    from app import anki_sync
    store, data_dir, user_files_dir, src, root = _world("zh")
    monkeypatch.setattr(anki_sync, "_atomic_write_json",
                        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError(13, "held by another program")))
    with store:
        answer = ls.start_fresh(store, forget_known=True)
    assert answer["known"].startswith("kept: ")
    assert _record(answer["backup"])["known"] == answer["known"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_forgetting_known_words_keeps_the_words_he_dismissed(language):
    # I-R4: every replacing import keeps the IGNORED entries (anki_sync.kept_ignored); a fresh library's "forget my
    # known words" is one more, so a dismissed word never comes back as a new one
    store, data_dir, user_files_dir, src, root = _world(language)
    path = os.path.join(user_files_dir, "KnownWord.json")
    words = names(language)
    dismissed = [{"dictForm": words[6], "knownStatus": "IGNORED"}, {"dictForm": words[7], "knownStatus": "IGNORED"}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"exportDate": "2026-10-20T08:00:00", "source": "anki", "statistics": {},
                   "words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in words[:4]] + dismissed}, f,
                  ensure_ascii=False)
    with store:
        answer = ls.start_fresh(store, forget_known=True)
    assert answer["known"] == "forgotten"
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["words"] == dismissed
    known = _record(answer["backup"])["known"]                          # the record names where the words went
    assert known["ignored_kept"] == 2 and _bytes(known["copy"]) == _bytes(known["dated"])


def test_the_sheets_counts_are_what_a_fresh_library_never_brings_back():
    # I-R5 / LF-8 / I-R1: the sheet names, from the store, the items no folder being read brings back (+ Add files
    # from outside the folders, YouTube transcripts, the rest: pasted, hato's, 2.x) and the cards left suspended —
    # and exactly that many items are gone after the reset and the folders' first look
    store, data_dir, user_files_dir, src, root = _world("ja")
    with store:
        outside = _write(os.path.join(os.path.dirname(data_dir), "elsewhere", "downloads", "Added Show - 01.srt"),
                         _text("ja", 7))
        copy = os.path.join(data_dir, ls.CONTENT_FOLDER, "Added Show", "Added Show - 01.srt")
        os.makedirs(os.path.dirname(copy))
        shutil.copyfile(outside, copy)
        st = os.stat(outside)
        added = store.insert([copy], "now", origins={copy: {
            "origin": os.path.abspath(outside), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": ls.sha256_of(copy), "show": "Added Show"}}).added[0]
        tube = next(i for i in store.ids("now") if i != added and not store.conn.execute(
            f"SELECT 1 FROM pairings p WHERE p.item_id = ? AND {ls._ORIGIN_ROW}", (i,)).fetchone())
        with store._writing():
            store.conn.execute("UPDATE items SET source_type = 'youtube' WHERE id = ?", (tube,))
        out = {"queue": -1, "suspended": [9001, 9002], "tag": "Surasura::out", "tagged": [501]}
        store.record_anki_changes([(added, "cards_out", [501], {"queue": 0, "tagged": []}, out),
                                   (tube, "cards_out", [502], {"queue": 0, "tagged": []},
                                    dict(out, suspended=[9002, 9003]))])
        total = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        removed = store.conn.execute("SELECT COUNT(*) FROM exclusions WHERE kind = 'removed'").fetchone()[0]
        counts = ls.fresh_counts(store)
        assert (counts["added"], counts["youtube"], counts["suspended"]) == (1, 1, 3)
        assert counts["other"] >= 2                                     # the 2.x tier files and hato's drop
        ls.start_fresh(store)
        _look(store, "ja", root, first=True)
        back = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert removed == 1                                                 # and the episode he removed comes back
    assert back == total - (counts["added"] + counts["youtube"] + counts["other"]) + removed


def test_a_reset_a_kill_left_started_is_found_at_the_next_start_and_a_finished_one_never():
    # I-R8 / LF-11: a kill mid-move leaves reset.json "started" and the old library in the backup; the next start
    # names that folder (the looks' first summary); a reset put back by hand, or one that finished, is never named
    store, data_dir, user_files_dir, src, root = _world("ja")

    def kill(name):
        if name == "data":
            raise _Killed(name)
    with pytest.raises(_Killed):
        ls.start_fresh(store, _step=kill)
    store.close()
    (folder,) = _backups(user_files_dir)
    assert ls.unfinished_reset(user_files_dir) == folder
    _restore_by_hand(_record(folder), store.db_path)
    record = _record(folder)
    record["status"] = "undone"                                         # put back by hand, as reset.json says
    with open(os.path.join(folder, ls.RESET_RECORD), "w", encoding="utf-8") as f:
        json.dump(record, f)
    assert ls.unfinished_reset(user_files_dir) is None
    store = ls.open_store("ja", data_dir, user_files_dir)
    with store:
        ls.start_fresh(store)
    assert ls.unfinished_reset(user_files_dir) is None


def test_the_looks_first_summary_names_an_unfinished_reset_once_a_run():
    # LF-11: the window's bar line comes from the looks' first summary; later looks never repeat it
    from app.services import source_looks
    store, data_dir, user_files_dir, src, root = _world("zh")

    def kill(name):
        if name == "cache":
            raise _Killed(name)
    with pytest.raises(_Killed):
        ls.start_fresh(store, _step=kill)
    store.close()
    (folder,) = _backups(user_files_dir)

    opener = ls.StoreOpener("zh", data_dir, user_files_dir)
    assert opener.check() == "store"
    seen = []
    looks = source_looks.SourceLooks(opener, "zh", on_result=seen.append, kind=lambda _p: "network")
    try:
        assert looks.asked(refreshed=True) and looks.idle(30)
        assert looks.asked(refreshed=True) and looks.idle(30)
    finally:
        looks.close()
        looks.idle(5)
    assert [s.get("unfinished_reset") for s in seen] == [folder, None]
