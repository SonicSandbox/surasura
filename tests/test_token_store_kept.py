"""The token store's counted / kept flag and the kept text (E2.2 rows 2.2.1–2.2.2; L2.2 05 §5.10, 9a / 9b).

Why these matter: 3.0 keeps the sentences of Finished, removed and newly arrived files — for 例文, the journey and the
sentence library — but the list, the cut-off, the name tables and the Rarity slider count only what Generate analyses.
A kept file must never reach a count; a kept file's text must outlive the token store, which is a cache (a new
tokenizer identity empties it, a damaged file deletes itself); a moved file keeps its tokens; a file the user forgot,
or that left both lists, goes with its text; and an unchanged library costs nothing (S19). Real Japanese and Chinese
text (testing.md): the samples and the test resources, in a data folder under the test root.
"""

import os
import shutil
import sys
from unittest.mock import patch

import pytest

from app import indexer, library_store as ls, token_index as ti, word_selection as ws
from tests.test_library_store_support import LANGUAGES, entry, roots, write_manifest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = {
    "ja": ["samples/ja/HighPriority/H_priority_sample_1.txt", "samples/ja/HighPriority/H_priority_sample_2.srt",
           "samples/ja/LowPriority/L_priority_sample_1.txt", "samples/ja/LowPriority/L_priority_sample_2.txt",
           "tests/Test Resources/ja/library_episode.ass", "tests/Test Resources/ja/phrases_sample.srt"],
    "zh": ["samples/zh/HighPriority/H_priority_sample_1.txt", "samples/zh/HighPriority/H_priority_sample_2.txt",
           "samples/zh/LowPriority/L_priority_sample_1.txt", "samples/zh/LowPriority/L_priority_sample_2.txt",
           "tests/Test Resources/zh/chinese_text_1.txt", "tests/Test Resources/zh/night_market.srt"],
}


def _files(language, folders=("HighPriority/作品", "HighPriority/作品", "LowPriority/番組", "LowPriority/番組",
                              "GoalContent/物語", "GoalContent/物語")):
    """The language's six real files, copied into the test root's data folder (nested show folders): their paths."""
    data_dir, _u = roots(language)
    out = []
    for source, folder in zip(SOURCES[language], folders):
        path = os.path.join(data_dir, *folder.split("/"), os.path.basename(source))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy2(os.path.join(REPO, *source.split("/")), path)
        out.append(path)
    return out


def _counting(language):
    """The real tokenizer, every read counted: ("file", key) for a whole file, ("text", None) for text read in by hand
    (a kept file, or one read back from its kept text)."""
    inner = ti.make_tokenizer(language)
    calls = []

    def tokenize(path):
        calls.append(("file", ti._norm(path)))
        return inner(path)

    def tokenize_text(text, facts=None):
        calls.append(("text", None))
        return inner.tokenize_text(text, facts)

    tokenize.read_text, tokenize.tokenize_text, tokenize.calls = inner.read_text, tokenize_text, calls
    return tokenize


def _cut_off(store, language):
    """The Rarity slider's numbers and the cut-off automatic rarity takes from them: (freqs, band, floor)."""
    freqs = ti.preview_frequencies(store, language, roots(language)[1])
    band = ws.auto_band(ws.band_previews(freqs)) or ws.BANDS_ORDER[0]
    return freqs, band, ws.band_floor_count(band, freqs["total_tokens"])


def _everything_counted(store, language):
    return {"words": store.word_counts(), "bound": store.bound_counts(), "total": store.total_tokens(),
            "files": store.file_count(), "names": store.names_tables(), "phrases": store.phrase_table(),
            "has": store.has_tokens(), "cut_off": _cut_off(store, language)}


def _kept_text(store):
    return store._kept_text()


def _lemmas(store, path):
    return {token[0] for _s, tokens in store.file_tokens(path) for token in tokens}


# --------------------------------------------------------------------------- #
# 2.2.1: the flag, counted-only sums
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_finished_and_removed_text_never_reaches_the_counts(language, tmp_path):
    """A Finished file (kept, on the disk) and a removed one (kept, its file in the trash) are tokenized and cached, but
    the word counts, the bound table, the totals, the name tables, the phrase table, the Rarity slider's numbers and the
    cut-off are exactly those of a store that holds the counted files alone."""
    a, b, finished, removed, _e, _f = _files(language)
    data_dir, _u = roots(language)
    trashed = os.path.join(data_dir, ".trash", "removed_20261008120000" + os.path.splitext(removed)[1])
    os.makedirs(os.path.dirname(trashed))
    os.replace(removed, trashed)                                       # the Content Manager's Remove (§6.6)

    store = ti.open_store(language)
    store.reconcile([a, b], ti.make_tokenizer(language), kept=[finished, removed], elsewhere={removed: trashed})
    alone = ti.open_store(language, path=str(tmp_path / "counted_alone.db"))
    alone.reconcile([a, b], ti.make_tokenizer(language))

    assert _everything_counted(store, language) == _everything_counted(alone, language)
    assert set(store.kept_files()) == {ti._norm(finished), ti._norm(removed)}
    assert set(store.counted_files()) == {ti._norm(a), ti._norm(b)}
    # Not vacuous: the kept files hold words the counted ones don't, and those words are cached, never counted.
    only_kept = (_lemmas(store, finished) | _lemmas(store, removed)) - _lemmas(store, a) - _lemmas(store, b)
    assert only_kept and not only_kept & {lemma for lemma, _r in store.word_counts()[0]}
    # Their text is kept: the finished file's from the disk, the removed one's from the trash.
    held = _kept_text(store).held()
    assert held == {ti._norm(finished): False, ti._norm(removed): False}
    store.close()
    alone.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_kept_and_counted_flips_move_counts_without_tokenizing(language, tmp_path):
    """Finish, Put back, a removed file restored: a file moving between the lists moves its counts in or out of the
    aggregate and `bound`, and is never tokenized again."""
    a, b, c, _d, _e, _f = _files(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, b], tok, kept=[c])
    tok.calls.clear()

    store.reconcile([a, c], tok, kept=[b])                             # c put back, b finished
    assert tok.calls == [], "a flip re-tokenizes nothing"
    reference = ti.open_store(language, path=str(tmp_path / "ref.db"))
    reference.reconcile([a, c], ti.make_tokenizer(language))
    assert _everything_counted(store, language) == _everything_counted(reference, language)

    store.reconcile([a, b, c], tok, kept=[])                           # everything counted again
    assert tok.calls == []
    reference.reconcile([a, b, c], ti.make_tokenizer(language))
    assert store.word_counts() == reference.word_counts() and store.bound_counts() == reference.bound_counts()
    assert _kept_text(store).held() == {ti._norm(c): False}, "kept text goes only when the user forgets a file"
    store.close()
    reference.close()


def _old_schema(db):
    """The store as a 3.0 build before E2.2 wrote it: the same SCHEMA_VERSION, no `counted` column."""
    import sqlite3
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE files_old (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, total INTEGER, counts BLOB, "
        "tokens BLOB, names BLOB, bound BLOB);"
        "INSERT INTO files_old SELECT path, mtime, size, total, counts, tokens, names, bound FROM files ORDER BY rowid;"
        "DROP TABLE files; ALTER TABLE files_old RENAME TO files;")
    conn.commit()
    assert "counted" not in [r[1] for r in conn.execute("PRAGMA table_info(files)")]
    conn.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_old_store_opens_with_every_row_counted_and_no_rebuild(language, tmp_path):
    """D2: a store without the flag gets it by ALTER TABLE — every row counted, nothing wiped, nothing re-tokenized,
    every number as it was (no SCHEMA_VERSION bump)."""
    files = _files(language)[:4]
    db = str(tmp_path / "old.db")
    store = ti.open_store(language, path=db)
    store.reconcile(files, ti.make_tokenizer(language), build_signature=ti.build_signature(language))
    before = _everything_counted(store, language)
    store.close()
    _old_schema(db)

    tok = _counting(language)
    store = ti.open_store(language, path=db)
    assert set(store.counted_files()) == {ti._norm(p) for p in files} and store.kept_files() == []
    assert _everything_counted(store, language) == before
    store.reconcile(files, tok, build_signature=ti.build_signature(language))
    assert tok.calls == [], "no rebuild"
    assert _everything_counted(store, language) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reconcile_with_nothing_changed_tokenizes_and_writes_nothing(language):
    """S19: counted, kept, a removed file in the trash and a missing counted one — a second reconcile with nothing
    changed tokenizes nothing and writes nothing, to the store or to the kept text."""
    a, b, finished, removed, missing, _f = _files(language)
    data_dir, _u = roots(language)
    trashed = os.path.join(data_dir, ".trash", os.path.basename(removed))
    os.makedirs(os.path.dirname(trashed))
    os.replace(removed, trashed)
    sig = ti.build_signature(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, b, missing], tok, sig, kept=[finished, removed], elsewhere={removed: trashed})
    os.remove(missing)
    store.reconcile([a, b, missing], tok, sig, kept=[finished, removed], elsewhere={removed: trashed})
    tok.calls.clear()
    kept_db = _kept_text(store).path
    on_disk = [(os.stat(kept_db + s).st_mtime_ns, os.stat(kept_db + s).st_size) for s in ("", "-wal")
               if os.path.exists(kept_db + s)]
    changes = store.conn.total_changes

    store.reconcile([a, b, missing], tok, sig, kept=[finished, removed], elsewhere={removed: trashed})
    assert tok.calls == []
    assert store.conn.total_changes == changes, "no row of the store written"
    assert [(os.stat(kept_db + s).st_mtime_ns, os.stat(kept_db + s).st_size) for s in ("", "-wal")
            if os.path.exists(kept_db + s)] == on_disk, "the kept text untouched"
    assert store.needs_reconcile([a, b, missing], [finished, removed], {removed: trashed}) is False
    store.close()


# --------------------------------------------------------------------------- #
# 2.2.2: the kept text, the re-key, the indexer's two lists
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_tokenize_text_equals_tokenize_file(language):
    """A kept file read back in from its kept text gives exactly what its file gave — every real file, both
    languages (an .ass caption file and subtitles included)."""
    tokenize = ti.make_tokenizer(language)
    for path in _files(language):
        assert tokenize.tokenize_text(*tokenize.read_text(path)) == tokenize(path), path


def _wipe(store, language, kind):
    """One of the three ways the token store loses every row: a new tokenizer identity (reconcile's own wipe), a
    SCHEMA_VERSION it doesn't match (_ensure_schema drops its tables) or a damaged file (open_store deletes it). The
    store to reconcile next, and the build signature to reconcile with."""
    if kind == "identity":
        return store, "identity 2"
    path = store.path
    store.close()
    if kind == "schema":
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute(f"PRAGMA user_version = {ti.SCHEMA_VERSION - 1}")
        conn.commit()
        conn.close()
    else:
        for suffix in ("-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        with open(path, "wb") as f:
            f.write(b"not a database" * 100)
    store = ti.open_store(language)
    assert store.file_count() == 0 and store.kept_files() == [], "the store is empty"
    return store, "identity 1"


@pytest.mark.parametrize("kind", ("identity", "schema", "damaged"))
@pytest.mark.parametrize("language", LANGUAGES)
def test_kept_text_survives_a_wipe(language, kind):
    """A kept file gone from the disk, a removed file whose trash copy was purged and a missing counted file: each of
    the three wipes empties the store, and each file comes back from its kept text — the kept ones exactly as they read
    before, the missing one as its cached sentences read — in the list it was in, with the counts it had."""
    a, finished, removed, missing, _e, _f = _files(language)
    data_dir, _u = roots(language)
    trashed = os.path.join(data_dir, ".trash", os.path.basename(removed))
    os.makedirs(os.path.dirname(trashed))
    os.replace(removed, trashed)
    store = ti.open_store(language)
    lists = dict(kept=[finished, removed], elsewhere={removed: trashed})
    store.reconcile([a, missing], ti.make_tokenizer(language), "identity 1", **lists)
    before = {p: store.file_tokens(p) for p in (finished, removed, missing)}
    counted = (store.word_counts(), store.bound_counts())
    os.remove(missing)
    store.reconcile([a, missing], ti.make_tokenizer(language), "identity 1", **lists)   # its text kept, rebuilt
    os.remove(finished)
    os.remove(trashed)                                                 # the trash's 30 days are over
    kept_db = _kept_text(store).path

    store, signature = _wipe(store, language, kind)
    assert os.path.exists(kept_db), "the kept text is not the cache's to delete"
    tok = _counting(language)
    store.reconcile([a, missing], tok, signature, **lists)
    assert sorted(tok.calls) == [("file", ti._norm(a))] + [("text", None)] * 3
    assert store.file_tokens(finished) == before[finished] and store.file_tokens(removed) == before[removed]
    assert store.file_tokens(missing) == before[missing]
    assert set(store.kept_files()) == {ti._norm(finished), ti._norm(removed)}
    assert set(store.counted_files()) == {ti._norm(a), ti._norm(missing)}
    assert (store.word_counts(), store.bound_counts()) == counted, "the missing file still counts, as it did"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_damaged_kept_text_file_is_set_aside_once_never_fatal(language, capsys):
    """A kept-text file that is no database any more is renamed aside with a printed line and a new one started; the
    reconcile goes on and keeps the text anew."""
    a, finished, *_rest = _files(language)
    store = ti.open_store(language)
    kept_db = _kept_text(store).path
    with open(kept_db, "wb") as f:
        f.write(b"\x00garbage" * 512)
    store.reconcile([a], ti.make_tokenizer(language), kept=[finished])
    out = capsys.readouterr().out
    assert "Some kept sentences couldn't be read" in out and out.count("set aside") == 1
    assert [n for n in os.listdir(os.path.dirname(kept_db)) if ".damaged-" in n and not n.endswith(("-wal", "-shm"))]
    assert _kept_text(store).held() == {ti._norm(finished): False}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_token_store_follows_the_move(language):
    """9a: a counted file moved to another show's folder, and a kept one moved too — same name, size and modified
    time — keep their rows (re-keyed, nothing re-tokenized); the kept one's text follows it."""
    a, b, c, *_rest = _files(language)
    data_dir, _u = roots(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, b], tok, kept=[c])
    before = (store.word_counts(), store.file_tokens(a), store.file_tokens(c))
    moved_a = os.path.join(data_dir, "LowPriority", "別の作品", os.path.basename(a))
    moved_c = os.path.join(data_dir, "GoalContent", "別の物語", os.path.basename(c))
    for old, new in ((a, moved_a), (c, moved_c)):
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.replace(old, new)                                           # a move keeps the modified time
    tok.calls.clear()

    store.reconcile([moved_a, b], tok, kept=[moved_c])
    assert tok.calls == [], "the moved files take their rows"
    assert (store.word_counts(), store.file_tokens(moved_a), store.file_tokens(moved_c)) == before
    assert store.file_tokens(a) == [] and set(store.kept_files()) == {ti._norm(moved_c)}
    assert set(_kept_text(store).held()) == {ti._norm(moved_c)}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_missing_items_text_is_kept_and_counted(language, tmp_path):
    """9b (✅ G2.2-3): a counted file gone from the disk stays — counted, its cached sentences served — and its text
    is kept (rebuilt from those sentences), so it outlives a wipe."""
    a, missing, *_rest = _files(language)
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile([a, missing], tok)
    before = (store.word_counts(), store.file_tokens(missing))
    os.remove(missing)
    tok.calls.clear()

    store.reconcile([a, missing], tok, kept=[])
    assert tok.calls == []
    assert (store.word_counts(), store.file_tokens(missing)) == before
    assert set(store.counted_files()) == {ti._norm(a), ti._norm(missing)}
    assert _kept_text(store).held() == {ti._norm(missing): True}
    assert store.needs_reconcile([a, missing], []) is False, "a missing file is no work for the indexer"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_forget_text_drops_it(language):
    """G2.2-3 (*This file is junk — forget its sentences too*): a forgotten file loses its row and its kept text; a
    kept file the list leaves out but nobody forgot keeps both; a forgotten path a list names again (a new file there)
    is that file's."""
    a, junk, kept, unnamed, *_rest = _files(language)
    store = ti.open_store(language)
    store.reconcile([a], ti.make_tokenizer(language), kept=[junk, kept, unnamed])
    assert set(_kept_text(store).held()) == {ti._norm(junk), ti._norm(kept), ti._norm(unnamed)}
    store.reconcile([a], ti.make_tokenizer(language), kept=[kept], forgotten=[junk])
    assert store.file_tokens(junk) == [] and set(store.kept_files()) == {ti._norm(kept), ti._norm(unnamed)}
    assert set(_kept_text(store).held()) == {ti._norm(kept), ti._norm(unnamed)}
    store.reconcile([a, kept], ti.make_tokenizer(language), kept=[], forgotten=[kept])
    assert set(store.counted_files()) == {ti._norm(a), ti._norm(kept)}, "listed: never forgotten"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def _kept_state(language):
    """The kept rows, every column, and the kept text file's rows: what no caller with one list may touch."""
    import sqlite3
    with ti.open_store(language) as store:
        rows = store.conn.execute("SELECT * FROM files WHERE counted = 0 ORDER BY path").fetchall()
        path = _kept_text(store).path
    conn = sqlite3.connect(path)
    try:
        return rows, conn.execute("SELECT * FROM kept ORDER BY rel").fetchall()
    finally:
        conn.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_caller_with_one_list_leaves_the_kept_rows_alone(language):
    """Callers that know only the run's list — a Generate-style reconcile, the sentence dictionary's
    (`reconcile_language`), and the indexer with the library store busy or not ready — drop a counted file the list
    left out, as ever, and leave every kept row and all kept text byte for byte."""
    a, b, c, d, *_rest = _files(language)
    with ti.open_store(language) as store:
        store.reconcile([a, b], ti.make_tokenizer(language), kept=[c, d])
    before = _kept_state(language)
    assert len(before[0]) == 2 and len(before[1]) == 2

    with ti.open_store(language) as store:                            # Generate: its found files
        store.reconcile([a, b], ti.make_tokenizer(language), build_signature=ti.build_signature(language))
    assert _kept_state(language) == before
    ti.reconcile_language(language, [a])                              # the sentence dictionary's call
    assert _kept_state(language) == before
    with ti.open_store(language) as store:
        assert store.counted_files() == [ti._norm(a)], "a counted file no list names goes, as ever"
    with patch("app.library_store.check_mode", return_value=("read-only", "busy")):
        _run_indexer(language)                                        # the library store can't be read now
    assert _kept_state(language) == before
    _run_indexer(language)                                            # no library store at all (JSON mode)
    assert _kept_state(language) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_first_opens_of_an_old_store_both_succeed(language, tmp_path):
    """D2 under a race: two processes open a store without the flag at once (the indexer and a Generate) — both add
    or find the column, neither takes the other's "duplicate column" for damage, and every row survives."""
    import threading
    files = _files(language)[:2]
    db = str(tmp_path / "old.db")
    with ti.open_store(language, path=db) as store:
        store.reconcile(files, ti.make_tokenizer(language))
        total = store.total_tokens()
    for _round in range(5):
        _old_schema(db)
        results, start = [], threading.Barrier(2)

        def first_open():
            start.wait()
            try:
                with ti.open_store(language, path=db) as store:
                    results.append((store.total_tokens(), len(store.counted_files())))
            except Exception as e:                                    # the failure being tested
                results.append(e)
        threads = [threading.Thread(target=first_open) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [(total, 2), (total, 2)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_twins_are_read_again_never_guessed(language):
    """9a's re-key is one to one: two leaving rows and two new paths with the same name, size and modified time are
    each read again — a row is never handed to a file it may not be."""
    data_dir, _u = roots(language)
    source = _files(language)[0]
    stamp = os.stat(source).st_mtime
    olds = [os.path.join(data_dir, "HighPriority", show, "第01話.txt") for show in ("甲", "乙")]
    for path in olds:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(source, path)
        os.utime(path, (stamp, stamp))
    tok = _counting(language)
    store = ti.open_store(language)
    store.reconcile(olds, tok)
    news = [os.path.join(data_dir, "LowPriority", show, "第01話.txt") for show in ("丙", "丁")]
    for old, new in zip(olds, news):
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.replace(old, new)
    tok.calls.clear()
    store.reconcile(news, tok)
    assert sorted(tok.calls) == sorted(("file", ti._norm(p)) for p in news)
    assert set(store.counted_files()) == {ti._norm(p) for p in news}
    store.close()


# --------------------------------------------------------------------------- #
# D5: the indexer's two lists, end to end through a real library store
# --------------------------------------------------------------------------- #
def _library(language):
    """A library store over the six real files, two per tier (show folders): (store, data_dir, {path: item id})."""
    data_dir, user_files_dir = roots(language)
    files = _files(language)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for path in files:
        rel = os.path.relpath(path, data_dir).replace("\\", "/")
        doc["schedule"][ls.TIERS[ls.TIER_OF_FOLDER[rel.split("/")[0]]][0]].append(entry(rel))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    ids = {path: store.item_id(os.path.relpath(path, data_dir).replace("\\", "/")) for path in files}
    return store, data_dir, ids


def _remove(store, data_dir, item_id, path):
    """The Content Manager's Remove in store mode: the file to data/<lang>/.trash, then the store's remove."""
    trashed = os.path.join(data_dir, ".trash", "removed_" + os.path.basename(path))
    os.makedirs(os.path.dirname(trashed), exist_ok=True)
    os.replace(path, trashed)
    return store.remove([item_id], {item_id: os.path.relpath(trashed, data_dir).replace("\\", "/")})


def _run_indexer(language):
    with patch.object(sys, "argv", ["indexer.py", "--language", language]):
        indexer.main()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_indexer_takes_both_lists_from_the_library_store(language, tmp_path):
    """D5: the indexer hands the token store the library store's two lists — Finished and a removed file kept (its
    text read from the trash), a forgotten one dropped, a missing one still counted — and the counts are exactly those
    of the counted files alone."""
    store, data_dir, ids = _library(language)
    now1, now2, soon1, soon2, goal1, goal2 = list(ids)
    # The reference: the same history with no kept list — every file counted, then the three that stay counted (the
    # name tables keep a name through a flip guard: they remember the last tables, so both must have the same past).
    reference = ti.open_store(language, path=str(tmp_path / "ref.db"))
    reference.reconcile(list(ids), ti.make_tokenizer(language))
    reference.reconcile([now1, now2, soon2], ti.make_tokenizer(language))
    _run_indexer(language)
    with ti.open_store(language) as tokens:
        assert len(tokens.counted_files()) == 6 and tokens.kept_files() == []

    assert store.finish([ids[soon1]]) is not None
    removed = _remove(store, data_dir, ids[goal1], goal1)
    junk = _remove(store, data_dir, ids[goal2], goal2)
    assert store.forget_text([ids[goal2]]) == 1
    os.remove(now2)                                                    # gone from the disk: a missing item
    store.sync_disk()
    counted, more = indexer.token_store_lists(language, data_dir, [now1, soon2])
    assert {ti._norm(p) for p in counted} == {ti._norm(p) for p in (now1, now2, soon2)}
    assert {ti._norm(p) for p in more["kept"]} == {ti._norm(soon1), ti._norm(goal1)}
    assert {ti._norm(p) for p in more["elsewhere"]} == {ti._norm(goal1)}
    assert {ti._norm(p) for p in more["forgotten"]} == {ti._norm(goal2)}
    store.close()
    assert removed is not None and junk is not None

    _run_indexer(language)
    tokens = ti.open_store(language)
    assert set(tokens.counted_files()) == {ti._norm(p) for p in (now1, now2, soon2)}
    assert set(tokens.kept_files()) == {ti._norm(soon1), ti._norm(goal1)}
    assert tokens.file_tokens(goal2) == [], "forgotten: its row goes"
    assert tokens.word_counts() == reference.word_counts() and tokens.total_tokens() == reference.total_tokens()
    assert tokens.names_tables() == reference.names_tables()
    assert _kept_text(tokens).held() == {ti._norm(soon1): False, ti._norm(goal1): False, ti._norm(now2): True}
    assert tokens.needs_reconcile(counted, **more) is False, "the dashboard's check: nothing left to do"
    tokens.close()
    reference.close()


def test_without_a_library_store_the_indexer_leaves_kept_rows(tmp_path):
    """JSON mode (no library store): the run's list only, `kept` None — nothing kept is ever dropped by a caller that
    can't see the kept list."""
    files = _files("ja")[:2]
    assert indexer.token_store_lists("ja", roots("ja")[0], files) == (files, {})
