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
        real = ti.Store._song_shares

        def counting(self, asked, *args):
            read.extend(asked)
            return real(self, asked, *args)
        with patch.object(ti.Store, "_song_shares", counting), \
                patch.object(ti.Store, "file_tokens", side_effect=AssertionError("a whole file read")):
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


def _share_read_whole(store, path, numbers, found):
    """A file's share as the first count made it before it was streamed (RARITY-SONGS): `file_tokens`' sentences of
    `numbers`, every token asked, the phrases searched for — the answer `Store._song_shares` must give to the byte."""
    from app import phrases
    sentences = store.file_tokens(path)
    sung = [sentences[n] for n in numbers if n < len(sentences)]
    counts, total, pieces = Counter(), 0, Counter()
    for text, tokens in sung:
        for lemma, reading, surface, *_rest in tokens:
            if analyzer.has_target_language(lemma, store.language) or analyzer.has_target_language(surface,
                                                                                                    store.language):
                counts[(lemma, reading)] += 1
                total += 1
        if store.language == "ja":
            for i in analyzer.bound_uses(text, tokens):
                pieces[(tokens[i][0], tokens[i][1])] += 1
    uses, taken = phrases.tally(sung, found) if found is not None else ({}, {})
    return ([[l, r, n] for (l, r), n in counts.items()], total, [[l, r, n] for (l, r), n in pieces.items()],
            [{str(k): v[0] for k, v in uses.items()}, taken])


def test_each_files_share_is_the_one_its_whole_sentences_give_the_names_joined_and_the_phrases_kept_or_searched(
        tmp_path):
    """The first count reads only the song lines (their texts and type ids sliced out, their name spans alone
    applied), counts a line the names leave be by its type ids and takes the phrases the last index found — so each
    file's share must be, list for list and in the same order, the one its whole cached sentences give: a name the
    tables join (メロンベンチ, 焔魄陣) joined, the phrases the same kept or searched for; a number past the end, a
    file not held, nothing asked: none."""
    from app import phrases
    from tests.test_names import HOMURA, JIN, PARK, SHOP, STATION, _library as names_library
    store, paths = names_library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK,
                                                    "a.txt": HOMURA, "b.txt": JIN})
    show, _data_dir, show_paths = _library(tmp_path / "show", "ja", JA_SHOW)
    try:
        found = phrases.load()
        assert store.names_tables(), "the made-up library has name tables"
        joined = set()
        for p in paths:
            truth = set()
            store._named(store._stored(*store.conn.execute("SELECT texts, ids FROM files WHERE path=?",
                                                          (ti._norm(p),)).fetchone()),
                         store.conn.execute("SELECT names FROM files WHERE path=?", (ti._norm(p),)).fetchone()[0], truth)
            joined |= {(p, n) for n in truth}
        assert joined, "some sentence is joined"
        for lib, files, asked in (
                # every other sentence, the joined ones among them, and one past the end
                (store, paths, {p: sorted({n for n in range(len(store.file_tokens(p))) if n % 2}
                                          | {n for q, n in joined if q == p} | {len(store.file_tokens(p)) + 3})
                                for p in paths}),
                (store, paths, {p: [1] for p in paths}),       # a sentence asked alone: its own spans, never 0's
                (show, show_paths, {p: list(range(len(show.file_tokens(p)))) for p in show_paths})):
            met = lib.phrase_matches([ti._norm(p) for p in files])
            assert len(met) == len(files), "the index kept every file's phrases"
            for kept in (met, {}):                      # the index's phrases, or none kept: searched for
                got = lib._song_shares(dict(asked, **{str(tmp_path / "no such file.txt"): [0]}), found,
                                       {ti._norm(p): m for p, m in kept.items()}, {}, set())
                assert set(got) == set(files)
                for p in files:
                    assert got[p] == _share_read_whole(lib, p, asked[p], found), p
            assert lib._song_shares(asked, None, met, {}, set())[files[0]][3] == [{}, {}], "phrases off: none"
        uses = [show._song_shares({p: list(range(30))}, found, {}, {}, set())[p][3][0] for p in show_paths]
        assert any(uses), "the show's songs hold set phrases"
        assert store._song_shares({paths[0]: []}, found, {}, {}, set())[paths[0]] == ([], 0, [], [{}, {}])
        assert store._song_shares({}, found, {}, {}, set()) == {}
    finally:
        store.close()
        show.close()


def test_a_word_whose_lemma_is_latin_counts_by_its_kana_surface_as_the_list_counts_it(tmp_path):
    """Unidic writes some loanwords' lemma in Latin letters (エイズ -> ＡＩＤＳ, ユニセフ -> ＵＮＩＣＥＦ): the aggregate
    counts such a token by its surface. The first count asks each type's language once (`lang`), and must ask its
    surface too — else a song's エイズ stays in the store's counts while the list leaves it out. CRLF lines, and an
    empty file beside them, as a learner's folder has."""
    from app import phrases
    work = tmp_path / "data" / "ja" / "HighPriority" / "Kokuren"
    work.mkdir(parents=True)
    song = work / "song.txt"
    song.write_bytes("エイズのない世界へ。\r\nユニセフの歌を歌おう。\r\nユネスコの空に届け。\r\n".encode("utf-8"))
    (work / "empty.txt").write_bytes(b"")
    db = str(tmp_path / "store.db")
    ti.reconcile_language("ja", [str(song), str(work / "empty.txt")], path=db)
    store = ti.open_store("ja", db)
    try:
        lemmas = {t[0] for _text, tokens in store.file_tokens(str(song)) for t in tokens}
        assert {"ＡＩＤＳ", "ＵＮＩＣＥＦ"} <= lemmas, "the tokenizer's lemmas are Latin for these"
        found = phrases.load()
        asked = {str(song): [0, 1, 2]}
        for met in ({}, store.phrase_matches([ti._norm(str(song))])):
            got = store._song_shares(asked, found, {ti._norm(k): v for k, v in met.items()}, {}, set())
            assert got[str(song)] == _share_read_whole(store, str(song), [0, 1, 2], found)
            counted = {lemma for lemma, _reading, _n in got[str(song)][0]}
            assert {"ＡＩＤＳ", "ＵＮＩＣＥＦ"} <= counted, "counted by its kana surface"
    finally:
        store.close()


def test_a_sung_line_whose_only_one_character_word_is_a_kanji_piece_still_counts_the_piece(tmp_path):
    """The first count runs `bound_uses` only on a line holding a word written as one kanji (`ones`: one character at
    or past U+3400, bound_uses' own first test). A line of numbers and pieces alone — ３年, 十年 — has no kana of one
    character beside them, so only that test lets its 年 be counted as the piece the whole read counts."""
    from app import phrases
    work = tmp_path / "data" / "ja" / "HighPriority" / "Nikki"
    work.mkdir(parents=True)
    song = work / "song.txt"
    song.write_text("３年\n十年\n", encoding="utf-8")
    db = str(tmp_path / "store.db")
    ti.reconcile_language("ja", [str(song)], path=db)
    store = ti.open_store("ja", db)
    try:
        found = phrases.load()
        whole = _share_read_whole(store, str(song), [0, 1], found)
        assert ["年", "ネン", 2] in whole[2], "the whole read counts 年 twice as a piece"
        assert store._song_shares({str(song): [0, 1]}, found, {}, {}, set())[str(song)] == whole
    finally:
        store.close()


def test_a_first_count_takes_the_phrases_the_index_found_and_asks_each_types_language_once(tmp_path):
    """A first count (every song line of a library: the first Generate after an update) searches no song line for
    its phrases — the index found them (`phrase_matches`) — and asks a word's language once a type, never once a
    token; the share the same as when each line is searched and each token asked."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = analyzer.song_sentences(_found(paths), data_dir, store, None, "ja")
        tokens = sum(len(store.file_tokens(p)[n][1]) for p in paths for n in songs[p])
        asked = []
        real = analyzer.has_target_language

        def counting(text, language="ja"):
            asked.append(text)
            return real(text, language)
        with patch("app.phrases.PhraseSet.find", side_effect=AssertionError("a song line searched again")), \
                patch.object(analyzer, "has_target_language", counting):
            store.keep_song_counts(songs)
        assert asked and len(asked) < tokens, "each type's language asked once, not each token's"
        mine = store.get_meta("songs_counted")
        store.conn.execute("DELETE FROM songs")
        store.conn.execute("DELETE FROM meta WHERE key = 'songs_counted'")
        store.conn.commit()
        with patch.object(ti.Store, "phrase_matches", return_value={}):
            store.keep_song_counts(songs)               # none kept: every song line searched
        assert store.get_meta("songs_counted") == mine
    finally:
        store.close()


def test_a_first_count_holds_one_batch_of_files_song_lines_at_a_time(tmp_path):
    """The first count reads and counts a batch of files at a time and lets it go (a 20k library's song lines held at
    once were ~2 GB): with a batch of one file, each read asks one file — the shares and their sum as one batch's."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = analyzer.song_sentences(_found(paths), data_dir, store, None, "ja")
        store.keep_song_counts(songs)
        whole = (store.get_meta("songs_counted"), store.conn.execute("SELECT * FROM songs ORDER BY path").fetchall())
        store.conn.execute("DELETE FROM songs")
        store.conn.execute("DELETE FROM meta WHERE key = 'songs_counted'")
        store.conn.commit()
        calls = []
        real = ti.Store._song_shares

        def counting(self, asked, *args):
            calls.append(len(asked))
            return real(self, asked, *args)
        with patch.object(ti, "_SONG_BATCH", 1), patch.object(ti.Store, "_song_shares", counting):
            store.keep_song_counts(songs)
        assert calls == [1] * len(paths)
        assert (store.get_meta("songs_counted"),
                store.conn.execute("SELECT * FROM songs ORDER BY path").fetchall()) == whole
    finally:
        store.close()


def test_a_file_whose_row_cant_be_read_keeps_no_share_and_its_songs_count(tmp_path):
    """A counted file whose cached sentences can't be read gives no share (never a share of nothing, which would stand
    until the file's stamp moved): the others are kept, its songs still count, and nothing raises."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = analyzer.song_sentences(_found(paths), data_dir, store, None, "ja")
        broken = paths[2]
        store.conn.execute("UPDATE files SET texts = x'00' WHERE path = ?", (ti._norm(broken),))
        store.conn.commit()
        store.keep_song_counts(songs)
        kept = {p for (p,) in store.conn.execute("SELECT path FROM songs")}
        assert ti._norm(broken) not in kept
        assert kept == {ti._norm(p) for p in paths if p != broken and songs.get(p)}
    finally:
        store.close()


@pytest.mark.parametrize("damage", ["tag", "sum"])
def test_an_unreadable_tag_or_sum_is_counted_again_never_raised(tmp_path, damage):
    """A row's tag or the kept sum this code can't read (a hand-edited or damaged store) is no answer: that share (or
    all of them) is counted again at the next Generate — the counts then the list's — instead of failing every run."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = _kept(store, data_dir, paths, "ja")
        store.songs_out = True
        out = store.word_counts()
        if damage == "tag":
            store.conn.execute("UPDATE songs SET tag = 'not json' WHERE path = ?", (ti._norm(paths[1]),))
        else:
            store.conn.execute("UPDATE meta SET value = '[1]' WHERE key = 'songs_counted'")
        store.conn.commit()
        store.keep_song_counts(songs)
        assert store.word_counts() == out
        assert ti._tag_numbers(store.conn.execute("SELECT tag FROM songs WHERE path = ?",
                                                  (ti._norm(paths[1]),)).fetchone()[0]) == sorted(songs[paths[1]])
    finally:
        store.close()


def test_when_the_name_tables_moved_only_a_file_they_read_otherwise_is_read_again(tmp_path):
    """The name tables moved since the last Generate (a new index): a file whose names they read as before keeps its
    share unread; one they read otherwise is read again, alone, and the sum moves by it — the counts as before."""
    import json
    from tests.test_names import HOMURA, JIN, PARK, SHOP, STATION, _library as names_library
    store, paths = names_library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK,
                                                    "a.txt": HOMURA, "b.txt": JIN})
    try:
        songs = {p: [1] for p in paths}                 # each file's second line, as a song
        store.keep_song_counts(songs)
        store.songs_out = True
        out = store.word_counts()
        held = json.loads(store.get_meta("songs_counted"))
        names = held["names"]
        held["names"] = "the tables before"
        store.set_meta("songs_counted", json.dumps(held, ensure_ascii=False, separators=(",", ":")))
        target = ti._norm(paths[0])
        tag = json.loads(store.conn.execute("SELECT tag FROM songs WHERE path=?", (target,)).fetchone()[0])
        real = tag[1]
        tag[1] = "read before"
        store.conn.execute("UPDATE songs SET tag=? WHERE path=?", (json.dumps(tag), target))
        store.conn.commit()
        read = []
        some = ti.Store._song_shares

        def counting(self, asked, *args):
            read.extend(asked)
            return some(self, asked, *args)
        with patch.object(ti.Store, "_song_shares", counting):
            store.keep_song_counts(songs)
        assert read == [target], "only the file the tables read otherwise"
        assert json.loads(store.conn.execute("SELECT tag FROM songs WHERE path=?", (target,)).fetchone()[0])[1] == real
        assert json.loads(store.get_meta("songs_counted"))["names"] == names
        assert store.word_counts() == out
    finally:
        store.close()


def test_a_piece_only_the_songs_use_is_gone_from_the_pieces(tmp_path):
    """A one-kanji word whose every use as a piece is in the songs has none left (gone from `bound_counts`, never a
    0 kept): the list reads its uses on its own as its whole count. test_one_kanji_words' diary (年 in 三年 and
    10年), every line sung."""
    from tests.test_one_kanji_words import DIARY
    show = tmp_path / "diary"
    show.mkdir()
    (show / "diary.txt").write_text(DIARY, encoding="utf-8")
    store, _data_dir, paths = _library(tmp_path, "ja", str(show))
    try:
        before = store.bound_counts()
        assert before.get(("年", "ネン")), "the diary uses 年 as a piece"
        store.keep_song_counts({p: list(range(len(store.file_tokens(p)))) for p in paths})
        store.songs_out = True
        assert not store.bound_counts()
    finally:
        store.close()


def test_the_readout_reads_the_share_once_a_store_state_and_sees_another_programs_write(tmp_path):
    """The Rarity readout asks for the share three times (word_counts, bound_counts, phrase_table): it is read and
    summed once while the store stands still, and read again once another connection writes (a Generate, the
    indexer) — here an episode restamped, so its songs count again."""
    store, data_dir, paths = _library(tmp_path, "ja", JA_SHOW)
    try:
        songs = _kept(store, data_dir, paths, "ja")
        store.songs_out = True
        with patch.object(ti, "_SongSum", wraps=ti._SongSum) as made:
            first = store.word_counts()
            store.bound_counts()
            store.phrase_table()
            store.phrase_sums()
            assert made.call_count == 1
            assert store.word_counts() == first and made.call_count == 1
            other = ti.open_store("ja", store.path)
            try:
                other.conn.execute("UPDATE files SET mtime = mtime + 5 WHERE path = ?", (ti._norm(paths[1]),))
                other.conn.commit()
            finally:
                other.close()
            want, total, _pieces = _list_counts(store, paths, {p: n for p, n in songs.items() if p != paths[1]}, "ja")
            assert store.word_counts() == ({k: c for k, c in want.items() if c > 0}, total)
            assert made.call_count == 2
    finally:
        store.close()
