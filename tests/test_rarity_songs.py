"""The songs a Generate leaves out are out of the Rarity readout too (RARITY-SONGS; ENGINE_REVISION 54).

While *Count song lyrics (OP / ED)* is off (the default), a run leaves a show's opening and ending songs out of the
list's counts (tests/test_song_lines.py). The Rarity readout (`token_index.preview_frequencies`), Automatic rarity and
Generate's floor are one recipe over the token store's counts (`Store.word_counts` / `bound_counts` / `phrase_table`),
and those still held the songs: a library with songs showed more words a band than its list could hold, and the floor
was cut on tokens the list never counts. Now each counted file's share of the songs is kept beside them
(`Store.keep_song_counts`, the store's `songs` table) and taken off while the file is counted at that stamp.

Real data: the made-up shows of tests/Test Resources/<lang>/songs_* (星祭り's four episodes: an opening in ♪ and an
ending with no mark; 星星节's three Chinese episodes), Generated for real.
"""
import os
import re
import shutil
from collections import Counter
from unittest.mock import patch

import pytest

from app import analyzer
from app import token_index as ti

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
JA_SHOW = os.path.join(RES, "ja", "songs_show")
ZH_SHOW = os.path.join(RES, "zh", "songs_show")


@pytest.fixture(autouse=True)
def _a_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _library(tmp_path, language, show):
    """`show`'s episodes in a work folder of a library, indexed into a store of their own -> (store, data dir, paths)."""
    data_dir = tmp_path / "data" / language
    work = data_dir / "HighPriority" / os.path.basename(show)
    shutil.copytree(show, work)
    paths = sorted(str(work / name) for name in os.listdir(work))
    db = str(tmp_path / "store.db")
    ti.reconcile_language(language, paths, path=db)
    return ti.open_store(language, db), str(data_dir), paths


def _found(paths):
    return [(p, "high", 10, "subtitle") for p in paths]


def _list_counts(store, paths, songs, language):
    """({(lemma, reading): uses}, tokens, {(lemma, reading): one-kanji pieces}) as the list counts them: each file's
    cached sentences with its song lines given no words (`blank_songs`), the aggregate's own filter."""
    counts, total, pieces = Counter(), 0, Counter()
    for path in paths:
        for text, tokens in analyzer.blank_songs(store.file_tokens(path), songs.get(path)):
            for lemma, reading, surface, *_rest in tokens:
                if analyzer.has_target_language(lemma, language) or analyzer.has_target_language(surface, language):
                    counts[(lemma, reading)] += 1
                    total += 1
            if language == "ja":
                for i in analyzer.bound_uses(text, tokens):
                    pieces[(tokens[i][0], tokens[i][1])] += 1
    return counts, total, pieces


def _kept(store, data_dir, paths, language):
    """What a Generate does before its floor: the songs found, their share kept, the run's answer said."""
    songs = analyzer.song_sentences(_found(paths), data_dir, store, None, language)
    store.keep_song_counts(songs)
    return songs


@pytest.mark.parametrize("language, show, sung", [
    ("ja", JA_SHOW, ("背中", "約束", "涙")),
    ("zh", ZH_SHOW, ("清晨", "眼泪", "约定")),
])
def test_the_store_counts_the_library_as_the_list_counts_it_once_the_songs_are_kept(tmp_path, language, show, sung):
    """Off (the default), the readout's words, tokens and one-kanji pieces are the list's to the word: the words only
    the songs sing have no uses left, 地図 / 地图 (sung every episode, said once) keeps its one."""
    store, data_dir, paths = _library(tmp_path, language, show)
    try:
        songs = _kept(store, data_dir, paths, language)
        assert songs and all(songs.values())
        want, total, pieces = _list_counts(store, paths, songs, language)
        for songs_out in (None, True):              # Settings read (the window) or the run's own answer
            store.songs_out = songs_out
            counts, n = store.word_counts()
            assert counts == {key: c for key, c in want.items() if c > 0}
            assert n == total
            if language == "ja":
                assert store.bound_counts() == {key: c for key, c in pieces.items() if c > 0}
            assert not any(lemma in sung for lemma, _reading in counts), "a word only the songs sing has no uses"
            said = "地図" if language == "ja" else "地图"
            assert sum(c for (lemma, _r), c in counts.items() if lemma == said) == 1
        freqs = ti.preview_frequencies(store, language, str(tmp_path / "User Files" / language))
        assert freqs["total_tokens"] == total, "the Rarity readout's library is the list's"
    finally:
        store.close()


@pytest.mark.parametrize("language, show", [("ja", JA_SHOW), ("zh", ZH_SHOW)])
def test_with_count_song_lyrics_on_or_none_kept_the_store_counts_the_songs(tmp_path, language, show):
    """On (Settings, or a run that counts them), or before any Generate kept them, the store's counts are the whole
    library's, songs and all — as the list then counts them."""
    store, data_dir, paths = _library(tmp_path, language, show)
    try:
        whole = store.word_counts()
        _kept(store, data_dir, paths, language)
        with patch("app.token_index.songs_counted", return_value=True):
            assert store.word_counts() == whole
        store.songs_out = False
        assert store.word_counts() == whole
        store.songs_out = True
        assert store.word_counts()[1] < whole[1]
    finally:
        store.close()


def test_an_episode_changed_or_set_aside_counts_its_songs_again_until_the_next_generate_keeps_it(tmp_path):
    """Only a file still counted at its share's stamp is taken off; the next Generate reads only that file again."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = _kept(store, data_dir, paths, "ja")
        store.songs_out = True
        out = store.word_counts()
        changed = paths[1]
        store.conn.execute("UPDATE files SET mtime = mtime + 5 WHERE path = ?", (ti._norm(changed),))
        store.conn.commit()
        want, total, _pieces = _list_counts(store, paths, {p: n for p, n in songs.items() if p != changed}, "ja")
        assert store.word_counts() == ({k: c for k, c in want.items() if c > 0}, total)
        read = []
        real = ti.Store.file_tokens

        def counting(self, path):
            read.append(path)
            return real(self, path)
        with patch.object(ti.Store, "file_tokens", counting):
            store.keep_song_counts(songs)
        assert [ti._norm(p) for p in read] == [ti._norm(changed)], "only the changed episode is read again"
        assert store.word_counts() == out
        aside = [p for p in paths if p != changed]
        ti.reconcile_language("ja", aside, path=store.path)          # the episode no longer counted
        want, total, _pieces = _list_counts(store, aside, songs, "ja")
        assert store.word_counts() == ({k: c for k, c in want.items() if c > 0}, total), "gone: none of it counts"
    finally:
        store.close()


def test_a_generate_after_nothing_changed_reads_no_file_and_writes_nothing(tmp_path):
    """The share is kept: the next Generate compares the stamps and numbers alone."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = _kept(store, data_dir, paths, "ja")
        before = store.get_meta("songs_counted")
        with patch.object(ti.Store, "file_tokens", side_effect=AssertionError("read again")), \
             patch.object(ti.Store, "set_meta", side_effect=AssertionError("written")):
            store.keep_song_counts(songs)
        assert store.get_meta("songs_counted") == before
    finally:
        store.close()


def test_a_share_kept_under_another_engine_or_switch_is_never_taken_off(tmp_path):
    """Counted under another engine (a build since), the share is no answer: the songs count until a Generate keeps
    them again under this one."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        whole = store.word_counts()
        _kept(store, data_dir, paths, "ja")
        with patch.object(analyzer, "ENGINE_REVISION", analyzer.ENGINE_REVISION + 1):
            assert store.word_counts() == whole
        with patch.dict(analyzer.LOGIC, {"names_recurring": not analyzer.LOGIC.get("names_recurring", True)}):
            store.songs_out = False
            flipped = store.word_counts()               # the library as the other switch counts it, songs and all
            store.songs_out = None
            assert store.word_counts() == flipped
    finally:
        store.close()


def _generate(tmp_path, language, show, capsys, store=True):
    """One real run (Generate) over a library holding `show`, its band's floor from the library's size -> the tokens
    the floor was cut on (the run's own line)."""
    import json
    uf = tmp_path / "User Files" / language
    uf.mkdir(parents=True)
    (uf / ("KnownWord.json" if language == "ja" else "KnownWords.json")).write_text(json.dumps({"words": []}),
                                                                                       encoding="utf-8")
    work = tmp_path / "data" / language / "HighPriority" / os.path.basename(show)
    shutil.copytree(show, work)
    results = tmp_path / "results"
    results.mkdir()
    patches = [patch("app.analyzer.get_user_file", side_effect=lambda p: str(tmp_path / p)),
               patch("app.analyzer.get_data_path",
                     side_effect=lambda l=None: str(tmp_path / "data" / l) if l else str(tmp_path / "data")),
               patch("app.analyzer.get_user_files_path",
                     side_effect=lambda l=None: str(tmp_path / "User Files" / l) if l else str(tmp_path / "User Files")),
               patch("app.analyzer.RESULTS_DIR", str(results)),
               patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")),
               patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")),
               patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")),
               patch("sys.argv", ["analyzer.py", "--language", language])]
    if not store:
        patches.append(patch("app.token_index.open_store", side_effect=OSError("no store")))
    capsys.readouterr()
    for p in patches:
        p.start()
    try:
        analyzer.main()
    finally:
        for p in reversed(patches):
            p.stop()
    line = re.search(r"keep count >= ([\d.]+) \(of (\d+) library tokens\)", capsys.readouterr().out)
    assert line, "the run says its floor"
    return int(line.group(2)), [str(work / name) for name in sorted(os.listdir(work))]


def test_generates_floor_is_cut_on_the_lists_tokens_with_the_store_and_without_it(tmp_path, capsys):
    """The floor's library (its tokens) is the list's: the same number whether the run reads the token store or
    counts the library itself first (the store-less first pass, KO-3), and no song token in it."""
    with_store, paths = _generate(tmp_path / "a", "ja", JA_SHOW, capsys)
    without, _paths = _generate(tmp_path / "b", "ja", JA_SHOW, capsys, store=False)
    store = ti.open_store("ja")
    try:
        songs = analyzer.song_sentences(_found(paths), str(tmp_path / "a" / "data" / "ja"), store, None, "ja")
        _want, total, _pieces = _list_counts(store, paths, songs, "ja")
        whole = store.total_tokens()
    finally:
        store.close()
    assert whole > total, "the show sings"
    assert with_store == total
    assert without == total


def test_a_store_made_before_the_songs_table_gains_it_at_open_with_no_file_read_again_or_version_moved(tmp_path):
    """The songs' table is a share kept beside the counts, not cached tokenization (engine map § Rules: SCHEMA_VERSION
    moves only when that changes): a store at this version made before it is given the table at its next open, every file's
    tokens kept as they were and `user_version` unchanged — no re-index on top of the one ENGINE_REVISION's run causes."""
    import sqlite3
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    db = str(tmp_path / "store.db")
    before = {p: store.file_tokens(p) for p in paths}
    store.close()
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE songs")                    # the store as 3.0-dev before RARITY-SONGS made it
    conn.execute("INSERT INTO meta(key, value) VALUES('pin', 'the same store')")    # gone if it were built again
    conn.commit()
    conn.close()
    store = ti.open_store("ja", db)
    try:
        conn = sqlite3.connect(db)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='songs'").fetchone()
        finally:
            conn.close()
        assert store.get_meta("pin") == "the same store"
        assert {p: store.file_tokens(p) for p in paths} == before
        _kept(store, data_dir, paths, "ja")             # and the table takes a Generate's share
        assert store.get_meta("songs_counted")
    finally:
        store.close()
