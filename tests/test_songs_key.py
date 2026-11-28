"""A warm Generate checks no song file again when every work's songs were kept (WARM-BACK, 3.0.21).

`Store.keep_song_counts` takes the songs a run leaves out off the token store's counts (RARITY-SONGS). With nothing
changed it still read every song file's row, its names and its tag to find that out: 11,440 files and ~0.6 s at a
20k library, every Generate. `analyzer.song_sentences` already proves each work's answer by a digest of its files'
stamps, so when every work's answer came under its digest it gives one fingerprint of the songs (`fingerprint=`), and
a count under the fingerprint, state and name tables the last count kept its shares for reads nothing.

Real data: the made-up shows of tests/Test Resources/<lang>/songs_* (星祭り's four episodes, 星星节's three), as
tests/test_rarity_songs.py reads them.
"""
import json
import os
import shutil
from collections import Counter
from unittest.mock import patch

import pytest

from app import analyzer
from app import token_index as ti

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
SHOWS = {"ja": os.path.join(RES, "ja", "songs_show"), "zh": os.path.join(RES, "zh", "songs_show")}


@pytest.fixture(autouse=True)
def _a_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _library(tmp_path, language):
    """The show's episodes in a work folder, indexed into a store of their own -> (store, data dir, paths)."""
    data_dir = tmp_path / "data" / language
    work = data_dir / "HighPriority" / os.path.basename(SHOWS[language])
    shutil.copytree(SHOWS[language], work)
    paths = sorted(str(work / name) for name in os.listdir(work))
    db = str(tmp_path / "store.db")
    ti.reconcile_language(language, paths, path=db)
    return ti.open_store(language, db), str(data_dir), paths


def _found(paths, kind="subtitle"):
    return [(p, "high", 10, kind) for p in paths]


def _songs(store, data_dir, paths, language):
    """What a Generate does before its floor: the songs found and their fingerprint."""
    key = []
    songs = analyzer.song_sentences(_found(paths), data_dir, store, None, language, fingerprint=key)
    return songs, key[0]


def _list_counts(store, paths, songs, language):
    """The list's own count of the library, its song lines given no words — what word_counts must equal."""
    counts, total = Counter(), 0
    for path in paths:
        for _text, tokens in analyzer.blank_songs(store.file_tokens(path), songs.get(path)):
            for lemma, reading, surface, *_rest in tokens:
                if analyzer.has_target_language(lemma, language) or analyzer.has_target_language(surface, language):
                    counts[(lemma, reading)] += 1
                    total += 1
    return {key: n for key, n in counts.items() if n > 0}, total


class _Checks:
    """Counts the per-file checks `_count_songs` makes (`_tag_numbers`: one a held song file) and the files it reads."""

    def __init__(self):
        self.tags, self.read = 0, []

    def __enter__(self):
        # the song lines' reader, by the name it has (`some_tokens`; `_song_shares` since RARITY-SONGS 2): `asked` first
        reader = "some_tokens" if hasattr(ti.Store, "some_tokens") else "_song_shares"
        real_tag, real_some = ti._tag_numbers, getattr(ti.Store, reader)

        def tag(value):
            self.tags += 1
            return real_tag(value)

        def some(store, asked, *args, **kwargs):
            self.read.extend(ti._norm(p) for p in asked)
            return real_some(store, asked, *args, **kwargs)
        self._patches = [patch.object(ti, "_tag_numbers", tag), patch.object(ti.Store, reader, some)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


def _generate(root, language):
    """One real run (Generate) over `root`'s library (made on the first call) -> its results/ files' bytes."""
    uf = root / "User Files" / language
    work = root / "data" / language / "HighPriority" / os.path.basename(SHOWS[language])
    if not work.exists():
        uf.mkdir(parents=True)
        (uf / ("KnownWord.json" if language == "ja" else "KnownWords.json")).write_text(json.dumps({"words": []}),
                                                                                           encoding="utf-8")
        shutil.copytree(SHOWS[language], work)
    results = root / "results"
    shutil.rmtree(results, ignore_errors=True)
    results.mkdir()
    patches = [patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)),
               patch("app.analyzer.get_data_path",
                     side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")),
               patch("app.analyzer.get_user_files_path",
                     side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")),
               patch("app.analyzer.RESULTS_DIR", str(results)),
               patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")),
               patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")),
               patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")),
               patch("sys.argv", ["analyzer.py", "--language", language])]
    for p in patches:
        p.start()
    try:
        analyzer.main()
    finally:
        for p in reversed(patches):
            p.stop()
    return {name: (results / name).read_bytes() for name in ("priority_learning_list.csv",
                                                             "progressive_learning_list.csv")}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_second_generate_with_nothing_changed_checks_no_song_file_and_writes_the_same_list(tmp_path, language):
    """Generate twice, nothing changed between: the first counts the songs' shares (and checks each held file), the
    second takes them as kept — no song file's row or tag looked at — and its list is the first's, byte for byte."""
    first = _generate(tmp_path, language)
    with _Checks() as checks:
        second = _generate(tmp_path, language)
    assert checks.tags == 0 and checks.read == [], "a song file checked again with nothing changed"
    assert second == first


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_same_fingerprint_reads_nothing_and_the_counts_stay_the_lists(tmp_path, language):
    """The fingerprint is the same while nothing changed; the second count reads no file and checks none, and the
    store's counts are still the list's."""
    store, data_dir, paths = _library(tmp_path, language)
    try:
        songs, key = _songs(store, data_dir, paths, language)
        assert key is not None and songs and all(songs.values())
        store.keep_song_counts(songs, key=key)
        assert store.get_meta("songs_key") is not None and not store.conn.in_transaction, "the mark committed"
        store.close()
        store = ti.open_store(language, str(tmp_path / "store.db"))    # the next Generate's own connection
        again, key2 = _songs(store, data_dir, paths, language)
        assert (again, key2) == (songs, key)
        with _Checks() as checks:
            store.keep_song_counts(again, key=key2)
        assert checks.tags == 0 and checks.read == []
        assert store._songs_state_now == store._songs_state(), "the state the shares stand under, for the read"
        store.songs_out = True
        assert store.word_counts() == _list_counts(store, paths, songs, language)
    finally:
        store.close()


def test_an_episode_changed_moves_the_fingerprint_and_only_it_is_read_again(tmp_path):
    """An episode's stamp moved: the work is read again, its fingerprint is another, and the count reads that episode
    alone — the counts are the list's again."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        store.keep_song_counts(songs, key=key)
        changed = paths[2]
        store.conn.execute("UPDATE files SET mtime = mtime + 5 WHERE path = ?", (ti._norm(changed),))
        store.conn.commit()
        songs2, key2 = _songs(store, data_dir, paths, "ja")
        assert key2 is not None and key2 != key
        with _Checks() as checks:
            store.keep_song_counts(songs2, key=key2)
        assert checks.read == [ti._norm(changed)], "only the changed episode is read again"
        store.songs_out = True
        assert store.word_counts() == _list_counts(store, paths, songs2, "ja")
        with _Checks() as checks:                   # and kept: the next Generate checks nothing
            store.keep_song_counts(songs2, key=key2)
        assert checks.tags == 0 and checks.read == []
    finally:
        store.close()


def test_a_count_without_the_fingerprint_takes_the_mark_away(tmp_path):
    """A count with no fingerprint (a caller that has none) may write other shares: the mark goes first, so the old
    fingerprint never finds shares it didn't see — the next count with it checks every file and puts them right."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        store.keep_song_counts(songs, key=key)
        assert store.get_meta("songs_key") is not None
        fewer = {p: n for p, n in songs.items() if p != paths[0]}
        store.keep_song_counts(fewer)
        assert store.get_meta("songs_key") is None
        with _Checks() as checks:
            store.keep_song_counts(songs, key=key)
        assert checks.tags > 0, "the old fingerprint is no answer once another count wrote"
        store.songs_out = True
        assert store.word_counts() == _list_counts(store, paths, songs, "ja")
    finally:
        store.close()


@pytest.mark.parametrize("moved", ["state", "names"])
def test_the_mark_is_no_answer_under_another_state_or_other_name_tables(tmp_path, moved):
    """The same fingerprint under another state (a new tokenizer, phrase data, a switch) or other name tables is a
    count of its own: every file checked, as before."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        store.keep_song_counts(songs, key=key)
        if moved == "state":
            real = ti.Store._songs_state
            other = patch.object(ti.Store, "_songs_state", lambda self, settings=None: real(self, settings) + ["x"])
        else:
            other = patch.object(ti, "_names_reads", lambda tables: {"ア": ["イ"]})
        counted = []
        real_count = ti.Store._count_songs
        with other, patch.object(ti.Store, "_count_songs",
                                 lambda self, *a, **k: counted.append(1) or real_count(self, *a, **k)):
            store.keep_song_counts(songs, key=key)
        assert counted == [1], "counted again, as before"
    finally:
        store.close()


def test_no_spoken_file_no_store_or_a_work_not_kept_gives_no_fingerprint(tmp_path):
    """A library with no subtitle (no work), a run without the store, or a work whose lines the store doesn't hold:
    no fingerprint — the count checks every file, as before."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        for found, with_store in ((_found(paths, "ebook"), store), (_found(paths), None),
                                  (_found(paths + [os.path.join(data_dir, "HighPriority", "x", "gone.srt")]), store)):
            key, stats = [], {}
            analyzer.song_sentences(found, data_dir, with_store, analyzer.JapaneseTokenizer(), "ja", stats, key)
            assert key == [None]
            assert set(stats) == {"read", "kept"}, "the stats as they were"
    finally:
        store.close()


def test_a_mark_that_cant_be_written_raises_nothing_and_the_next_count_checks_again(tmp_path):
    """The shares are written; only the mark failed (a store locked a moment): no error reaches the run (its songs
    stay out), and the next Generate checks every file, as before."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        real = ti.Store._mark_songs

        def locked(self, mark):
            if mark is not None:
                raise ti.sqlite3.OperationalError("database is locked")
            return real(self, mark)
        with patch.object(ti.Store, "_mark_songs", locked):
            store.keep_song_counts(songs, key=key)
        assert store.get_meta("songs_key") is None
        assert not store.conn.in_transaction
        with _Checks() as checks:
            store.keep_song_counts(songs, key=key)
        assert checks.tags > 0
        assert store.get_meta("songs_key") is not None
    finally:
        store.close()


class _CommitLocked:
    """The store's connection, but its commit fails while the songs mark is pending (another program holds the lock
    at that moment): what `_mark_songs` must roll back."""

    def __init__(self, conn):
        self._conn, self._pending = conn, False

    def execute(self, sql, *args):
        self._pending = self._pending or "songs_key" in sql
        return self._conn.execute(sql, *args)

    def commit(self):
        if self._pending:
            self._pending = False
            raise ti.sqlite3.OperationalError("database is locked")
        return self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.mark.parametrize("at", ["the mark", "taking it away"])
def test_a_mark_whose_commit_fails_is_rolled_back_never_left_open(tmp_path, at):
    """The commit of the mark (or of its removal) fails: rolled back, no transaction left open on the run's
    connection. A mark that failed is no mark (the next count checks every file); a removal that failed raises, so
    the run counts its songs as before (the old mark is never trusted for the shares this count would write)."""
    store, data_dir, paths = _library(tmp_path, "ja")
    real = store.conn
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        if at == "the mark":
            store.conn = _CommitLocked(real)
            store.keep_song_counts(songs, key=key)
            store.conn = real
            assert not real.in_transaction
            assert store.get_meta("songs_key") is None
        else:
            store.keep_song_counts(songs, key=key)
            fewer = {p: n for p, n in songs.items() if p != paths[0]}
            store.conn = _CommitLocked(real)
            with pytest.raises(ti.sqlite3.OperationalError):
                store.keep_song_counts(fewer)
            store.conn = real
            assert not real.in_transaction
            assert store.get_meta("songs_key") is not None, "rolled back: the shares it named untouched too"
            store.songs_out = True
            assert store.word_counts() == _list_counts(store, paths, songs, "ja")
    finally:
        store.conn = real
        store.close()


def test_an_episode_brought_back_from_aside_gets_its_share_with_the_same_fingerprint(tmp_path):
    """An episode set aside (watched) is still its work's, so the fingerprint doesn't move when it is counted again
    at the same stamp; it holds no share, so the count reads it and takes its songs off, as the full check did."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        back = paths[1]
        store.reconcile([p for p in paths if p != back], ti.make_tokenizer("ja", False, "asis"),
                        build_signature=ti.build_signature("ja", False, "asis"), aside=[back])   # as a run lists it
        assert store.conn.execute("SELECT counted, aside FROM files WHERE path = ?", (ti._norm(back),)).fetchone()             == (0, 1)
        songs, key = _songs(store, data_dir, paths, "ja")       # the run's songs: counted and aside alike
        store.keep_song_counts(songs, key=key)
        assert ti._norm(back) not in {p for (p,) in store.conn.execute("SELECT path FROM songs")}
        ti.reconcile_language("ja", paths, path=store.path)
        songs2, key2 = _songs(store, data_dir, paths, "ja")
        assert key2 == key, "the same stamps: the same fingerprint"
        with _Checks() as checks:
            store.keep_song_counts(songs2, key=key2)
        assert checks.read == [ti._norm(back)]
        store.songs_out = True
        assert store.word_counts() == _list_counts(store, paths, songs2, "ja")
    finally:
        store.close()


def test_a_file_whose_row_couldnt_be_read_is_tried_again_at_every_count(tmp_path):
    """A counted file whose row couldn't be read holds no share (its songs count); the next count with the same
    fingerprint tries it again, as the full check did — never left out for good by the mark."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        broken = paths[2]
        store.conn.execute("UPDATE files SET texts = x'00' WHERE path = ?", (ti._norm(broken),))
        store.conn.commit()
        store.keep_song_counts(songs, key=key)
        with _Checks() as checks:
            store.keep_song_counts(songs, key=key)
        assert checks.read == [ti._norm(broken)]
    finally:
        store.close()


def test_an_episode_set_aside_after_the_mark_has_its_share_taken_away(tmp_path):
    """Set aside at the same stamp (watched), the fingerprint stays; the count sees a song file with a share that no
    longer counts and takes the share away, as the full check did — the songs table holds the counted files' alone."""
    store, data_dir, paths = _library(tmp_path, "ja")
    try:
        songs, key = _songs(store, data_dir, paths, "ja")
        store.keep_song_counts(songs, key=key)
        gone = paths[3]
        store.reconcile([p for p in paths if p != gone], ti.make_tokenizer("ja", False, "asis"),
                        build_signature=ti.build_signature("ja", False, "asis"), aside=[gone])
        songs2, key2 = _songs(store, data_dir, paths, "ja")
        assert key2 == key
        store.keep_song_counts(songs2, key=key2)
        held = {p for (p,) in store.conn.execute("SELECT path FROM songs")}
        assert held == {ti._norm(p) for p in paths if p != gone and songs.get(p)}
        store.songs_out = True
        assert store.word_counts() == _list_counts(store, [p for p in paths if p != gone], songs2, "ja")
    finally:
        store.close()
