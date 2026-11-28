"""PHRASE-REFIND (3.0.21): the set phrases searched for again after new phrase data or a new matcher.

The first index after such an update searches every file's phrases again (`Store._update_phrases`: each file's tally and
its kept matches), and it decoded and searched every sentence of every file — 6.9 M on a 20,000-file library, about
55 s of the first Generate after the update. A match is its phrase's whole lemma run in a row (`PhraseSet.find` walks
its trie lemma by lemma), so a sentence holding no phrase's run holds none: a re-find of many files now reads only the
sentences that hold one, judged on the store's type ids (`_PhraseGate`), and those a name span stands in (a join makes
their words anew). What it keeps is byte for byte what reading every sentence kept.
"""

import json
import os
import shutil
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from app import analyzer, phrase_data, phrases, token_index as ti

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
# Real subtitles, transcripts and captions: set phrases (気を付ける, あっという間, ありがとうございます …), names, songs
FILES = ["phrases_sample.srt", "placed_episode.srt", "readings_sample.srt", "utterances_sample.srt",
         "verses_sample.srt", "pauses_sample.srt", "repeated_lines.ja.srt", "library_episode.ass", "tv_captions.ass",
         "context_test.txt", "sentence_words.txt", "runaway_transcript.txt"]


def _phrases_on(root):
    (root / "settings.json").write_text(json.dumps({"logic": {"phrase_rows": True}}), encoding="utf-8")
    analyzer.LOGIC["phrase_rows"] = True


@pytest.fixture
def library():
    """A Japanese library of real files, half of them two folders down, plus an empty file and one with CRLF lines."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    nested = high / "作品" / "第1期"
    nested.mkdir(parents=True)
    for n, name in enumerate(FILES):
        shutil.copy(os.path.join(RESOURCES, "ja", name), (nested if n % 2 else high) / name)
    (high / "empty.txt").write_text("", encoding="utf-8")
    (high / "crlf.txt").write_bytes("車に気をつけて。\r\nどうもありがとうございました！\r\n何があっても、ずっと一緒だよ。\r\n"
                                    .encode("utf-8"))
    (root / "User Files" / "ja").mkdir(parents=True)
    (root / "User Files" / "ja" / "KnownWord.json").write_text('{"words": []}', encoding="utf-8")
    _phrases_on(root)
    analyzer.SANITIZE_JA = True
    return root


def _paths(root):
    return sorted(str(p) for p in (root / "data" / "ja").rglob("*") if p.is_file())


def _index(root):
    store = ti.open_store("ja")
    store.reconcile(_paths(root), ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja"))
    return store


def _kept(store):
    """What a phrase search keeps, without the state it is keyed on: each counted file's tally, each file's matches
    (with its sentence count), the phrase table — as stored text."""
    out = [json.dumps(json.loads(store.get_meta(key))["files"], ensure_ascii=False, sort_keys=True)
           for key in ("phrase_files", "phrase_matches")]
    return out + [store.get_meta("phrases")]


def _refind(store, monkeypatch, tag, gate_from):
    """Search every file's phrases again from a fresh process's state (no vocabulary read yet), as new phrase data does
    (its revision moved), the gate used from `gate_from` files on -> the sentences `phrases.tally` was given, a list
    a file."""
    monkeypatch.setattr(phrase_data, "REVISION", f"{phrase_data.REVISION}-{tag}")
    monkeypatch.setattr(ti, "_PHRASE_GATE_FILES", gate_from, raising=False)
    store._types.clear()
    given, real = [], phrases.tally
    # (the words given, each token as a list: the gate hands the vocabulary's own tuples, file_tokens new lists)
    monkeypatch.setattr(phrases, "tally", lambda sentences, found, matches=None, places=None:
                        given.append([[text, [list(token) for token in tokens]] for text, tokens in sentences])
                        or real(sentences, found, matches, places))
    store._update_phrases(True)
    monkeypatch.setattr(phrases, "tally", real)
    return given


def _can_hold(store):
    """{path: (its sentences as `file_tokens` reads them, the numbers of those that can hold a set phrase)}, in the
    store's order: a phrase's whole lemma run in a row in its words, or a name span in it — worked out word by word."""
    keys = {entry.key for entry in phrases.load().entries}
    longest = max(len(key) for key in keys)
    out = {}
    for path, names in store.conn.execute(f"SELECT path, names FROM files WHERE {ti._EVIDENCE}").fetchall():
        sentences = store.file_tokens(path)
        spans = {span[0] for span in store._name_spans(names)[0]}
        out[path] = sentences, [number for number, (_text, tokens) in enumerate(sentences)
                                if number in spans or any(tuple([t[0] for t in tokens[i:i + n]]) in keys
                                                          for i in range(len(tokens)) for n in range(1, longest + 1))]
    return out


def _expected(held):
    """The sentences a gated re-find gives `phrases.tally`, a list a file: those that can hold a phrase."""
    return [[sentences[k] for k in numbers] for sentences, numbers in held.values()]


def test_a_big_refind_decodes_only_the_sentences_that_can_hold_a_phrase_and_keeps_the_same(library, monkeypatch):
    # why: the first Generate after a matcher change spent ~55 s decoding and searching every sentence of every file;
    # only the sentences holding a phrase's whole lemma run (or a name span) can hold a match, and what the re-find
    # keeps — the tallies the Rarity slider counts, the matches Generate reads — must not move by a byte
    store = _index(library)
    try:
        whole = _refind(store, monkeypatch, "whole", 10 ** 9)
        before = _kept(store)
        gated = _refind(store, monkeypatch, "gated", 1)
        held = _can_hold(store)
        assert whole == [sentences for sentences, _numbers in held.values()], "read whole: every sentence"
        total, can = sum(len(s) for s, _n in held.values()), sum(len(n) for _s, n in held.values())
        assert 0 < can < total, "the files hold phrases, and sentences that can't hold one"
        assert gated == _expected(held), "gated: only the sentences that can hold a phrase, read as file_tokens reads"
        assert len(gated) == store.conn.execute("SELECT count(*) FROM files").fetchone()[0]
        assert _kept(store) == before, "the tallies, the matches and the table byte for byte"
        rows = json.loads(store.get_meta("phrases"))["rows"]
        assert rows["気を付ける|キヲツケル"][0] >= 2
        assert [row[0] for row in rows.values() if "何があっても" in row[1]] == [1], "a run of five words"
    finally:
        store.close()


def test_a_sentence_a_name_join_changes_is_searched_in_its_joined_words(library, monkeypatch):
    # why: a name table makes one word of a span's pieces, so the store's ids aren't that sentence's words: every
    # sentence a span stands in is read and joined before it is searched, and the kept matches still match a whole read
    store = _index(library)
    try:
        spans = [span for (names,) in store.conn.execute(f"SELECT names FROM files WHERE {ti._EVIDENCE}")
                 if names for span in ti._decode_counts(names).get("s", [])]
        assert spans, "the files record name candidates"
        tables = {"k": {}, "j": {}, "w": {}, "stamp": "refind"}
        for span in spans:                              # every candidate the tables can hold, made a name
            if span[5] in tables:
                tables[span[5]][span[6]] = [1.0, span[6], "", span[6]]
        store.set_meta("names_tables", json.dumps(tables, ensure_ascii=False))
        store._names = None
        joined = set()
        for path, names, texts, ids in store.conn.execute(
                f"SELECT path, names, texts, ids FROM files WHERE {ti._EVIDENCE}").fetchall():
            store._named(store._stored(texts, ids), names, joined)
        assert joined, "the tables join some sentence's pieces"
        _refind(store, monkeypatch, "whole", 10 ** 9)
        before = _kept(store)
        gated = _refind(store, monkeypatch, "gated", 1)
        assert gated == _expected(_can_hold(store)), "each sentence a span stands in given in its joined words"
        assert _kept(store) == before
    finally:
        store.close()


def _texts(store, path, sentences):
    """Make `path`'s kept texts those of `sentences` (a damaged row: they no longer count its sentences)."""
    store.conn.execute("UPDATE files SET texts=? WHERE path=?", (ti._encode_texts(sentences), path))
    store.conn.commit()


def test_rows_the_gate_cant_read_are_read_whole_as_before(library, monkeypatch):
    # why: a damaged row (its texts one sentence more or less than its words, a vocabulary row gone) must give what a
    # whole read gives it — `file_tokens` reads such a file as no sentence — never a match the whole read wouldn't keep
    store = _index(library)
    try:
        held = _can_hold(store)
        more = next(path for path in held if path.endswith("phrases_sample.srt"))
        fewer = next(path for path, (sentences, numbers) in held.items()   # its last sentence holds no phrase
                     if len(sentences) > 2 and numbers and numbers[-1] < len(sentences) - 1)
        _texts(store, more, held[more][0] + [["もう一行。", []]])
        _texts(store, fewer, held[fewer][0][:-1])
        _refind(store, monkeypatch, "whole", 10 ** 9)
        before = _kept(store)
        kept = json.loads(store.get_meta("phrase_matches"))["files"]
        assert kept[more][2:4] == kept[fewer][2:4] == [0, []], "read as no sentence"
        _refind(store, monkeypatch, "gated", 1)
        assert _kept(store) == before, "the damaged files read whole, the rest gated"
        used = ti._read_ids(store.conn.execute("SELECT ids FROM files WHERE path=?", (more,)).fetchone()[0])[1][0]
        store.conn.execute("DELETE FROM types WHERE id=?", (used,))     # a gap in the vocabulary: no gate at all
        store.conn.commit()
        built = []
        real = ti._PhraseGate
        monkeypatch.setattr(ti, "_PhraseGate", lambda *a: built.append(1) or real(*a))
        _refind(store, monkeypatch, "gap-whole", 10 ** 9)
        before = _kept(store)
        _refind(store, monkeypatch, "gap", 1)
        assert built == [] and _kept(store) == before
    finally:
        store.close()

def test_a_few_files_to_search_again_are_read_whole_without_the_gate(library, monkeypatch):
    # why: the gate's numpy and its read of the vocabulary cost more than they save on a few files (a new episode,
    # the watch's small updates): below `_PHRASE_GATE_FILES` files the re-find reads them as before
    store = _index(library)
    try:
        built = []
        real = ti._phrase_gate
        monkeypatch.setattr(ti, "_phrase_gate", lambda *a: built.append(1) or real(*a))
        whole = _refind(store, monkeypatch, "few", ti._PHRASE_GATE_FILES)
        assert built == [] and whole == [sentences for sentences, _numbers in _can_hold(store).values()]
        _refind(store, monkeypatch, "many", len(whole))
        assert built == [1], "as many files as the threshold: the gate"
    finally:
        store.close()


def test_a_chinese_store_searches_no_phrase_and_builds_no_gate(monkeypatch):
    # why: set phrases are Japanese only; a Chinese index must never pay for the gate or a search
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "zh" / "HighPriority"
    high.mkdir(parents=True)
    for name in ("night_market.srt", "chinese_text_1.txt", "mixed_script_transcript.txt"):
        shutil.copy(os.path.join(RESOURCES, "zh", name), high / name)
    (root / "settings.json").write_text(json.dumps({"logic": {"phrase_rows": True}}), encoding="utf-8")
    monkeypatch.setattr(ti, "_PHRASE_GATE_FILES", 1, raising=False)
    called = []
    monkeypatch.setattr(ti, "_phrase_gate", lambda *a: called.append("gate"), raising=False)
    monkeypatch.setattr(phrases, "tally", lambda *a: called.append("tally"))
    store = ti.open_store("zh")
    try:
        store.reconcile([str(p) for p in high.iterdir()], ti.make_tokenizer("zh"),
                        build_signature=ti.build_signature("zh"))
        store._update_phrases(True)
        assert called == [] and store.get_meta("phrase_matches") is None
        assert store.conn.execute("SELECT count(*) FROM files").fetchone()[0] == 3
    finally:
        store.close()


def test_find_passes_over_a_place_no_phrase_goes_on_from_and_still_meets_a_phrase_at_the_end(monkeypatch):
    # why: find now skips a first word whose next word no phrase continues without walking the trie; a phrase of one
    # word, or one whose first word ends the sentence, must still be met as the walk meets it
    analyzer.SANITIZE_JA = True
    tokenizer = analyzer.JapaneseTokenizer(library=False)
    found_in = phrases.PhraseSet([["気|を|付ける", "キ|ヲ|ツケル", "cgc", "気をつける", "キヲツケル"],
                                  ["本当", "ホントウ", "c", "本当", "ホントウ"]])

    def found(text):
        return [(found_in.entry(i).word, "".join(t[2] for t in tokens[a:b]))
                for sentence, tokens in tokenizer.tokenize_sentences(text)
                for a, b, i in found_in.find(tokens, sentence)]

    assert found("気が重い。でも車に気をつけて。") == [("気を付ける", "気をつけ")]
    assert found("それは本当") == [("本当", "本当")], "a one-word phrase, the sentence's last word"
    assert found("元気") == [] and found("気") == [], "a first word at the end, no phrase of it alone"


# -- PHRASE-REFIND b: the songs' phrases after a matcher change, each file's names decoded once, find at the runs ---- #
SONGS_SHOW = os.path.join(RESOURCES, "ja", "songs_show")


def _songs_library(tmp_path):
    """songs_show's episodes (the same opening and ending sung in each) in a work folder, indexed into a store of
    their own and their songs kept, as a Generate keeps them -> (store, the songs: {path: sentence numbers})."""
    analyzer.SANITIZE_JA = True
    data_dir = tmp_path / "data" / "ja"
    work = data_dir / "HighPriority" / "songs_show"
    shutil.copytree(SONGS_SHOW, work)
    paths = sorted(str(work / name) for name in os.listdir(work))
    db = str(tmp_path / "store.db")
    ti.reconcile_language("ja", paths, path=db)
    store = ti.open_store("ja", db)
    songs = analyzer.song_sentences([(p, "high", 10, "subtitle") for p in paths], str(data_dir), store, None, "ja")
    store.keep_song_counts(songs)
    return store, songs


def _songs_kept(store):
    """The songs table, every column of every row, and the sum (meta songs_counted), as stored."""
    return ([tuple(row) for row in store.conn.execute(
        "SELECT path, mtime, size, tag, total, counts, bound, phrases FROM songs ORDER BY path")],
        store.get_meta("songs_counted"))


def _sum_counts(value):
    """meta songs_counted, its words and pieces as sets of rows (a share taken off and put back may move their order;
    never their counts)."""
    held = json.loads(value)
    return {key: (sorted(map(tuple, rows)) if key in ("counts", "bound") else rows) for key, rows in held.items()}


def _copy(store, tmp_path, name):
    """Another store over a copy of `store`'s database as it is now."""
    import sqlite3
    path = str(tmp_path / name)
    other = sqlite3.connect(path)
    store.conn.backup(other)
    other.close()
    return ti.open_store("ja", path)


def _counted_again(store, songs, whole=False):
    """`keep_song_counts` after the change -> what it asked `_song_shares` for: [(path, sentence numbers, phrases
    only?)] — `whole`: every share counted again whole, as before (the vocabulary taken for a damaged one)."""
    asked, real = [], ti.Store._song_shares

    def spy(self, wanted, *args, **kw):
        asked.extend((ti._norm(p), list(n), kw.get("phrases_only", False)) for p, n in wanted.items())
        return real(self, wanted, *args, **kw)
    with patch.object(ti.Store, "_song_shares", spy):
        if whole:
            with patch.object(ti, "_types_whole", lambda _store: None):
                store.keep_song_counts(songs)
        else:
            store.keep_song_counts(songs)
    return asked


def test_after_a_matcher_change_the_songs_count_again_only_their_lines_holding_a_match_and_keep_the_same(
        tmp_path, monkeypatch):
    # why: a new matcher made the first Generate count every song line again (~27 s on a 20,000-file library) though
    # it moves only the songs' set phrases — their words, tokens and one-kanji pieces stand — and a line holding none
    # of the re-find's matches gives a phrase nothing; the songs table and its sum must be what counting all gives
    store, songs = _songs_library(tmp_path)
    try:
        monkeypatch.setattr(phrases, "MATCHER_VERSION", phrases.MATCHER_VERSION + 1)
        store._update_phrases(True)                     # the index's re-find under the new matcher
        other = _copy(store, tmp_path, "whole.db")
        try:
            _counted_again(other, songs, whole=True)
            want = _songs_kept(other)
        finally:
            other.close()
        met = store.phrase_matches(list(songs))
        holding = {ti._norm(p): sorted(set(n) & set(met[p][1][::4])) for p, n in songs.items() if n}
        assert 0 < sum(map(len, holding.values())) < sum(len(n) for n in songs.values()), \
            "the songs hold set phrases, and lines that hold none"
        with patch.object(ti.Store, "file_tokens", side_effect=AssertionError("a whole file read")):
            asked = _counted_again(store, songs)
        assert {p: n for p, n, _only in asked} == holding, "only the song lines holding a kept match"
        assert all(only for _p, _n, only in asked), "their phrases alone"
        assert _songs_kept(store) == want, "the songs table and the sum byte for byte"
        assert json.loads(want[1])["uses"], "the songs' phrases are counted"
    finally:
        store.close()


@pytest.mark.parametrize("damage", ["matches", "vocabulary", "changed"])
def test_after_a_matcher_change_a_file_the_phrases_only_count_cant_take_is_counted_whole(tmp_path, monkeypatch,
                                                                                        damage):
    # why: a file whose kept matches don't fit its words (damaged), a vocabulary with a gap, or an episode changed
    # since its songs were kept must be counted as before — every line — and the sum still be what counting all gives
    store, songs = _songs_library(tmp_path)
    try:
        monkeypatch.setattr(phrases, "MATCHER_VERSION", phrases.MATCHER_VERSION + 1)
        store._update_phrases(True)
        sung = sorted(ti._norm(p) for p, n in songs.items() if n)
        one = sung[1]
        if damage == "matches":                         # its kept matches count one sentence more than it holds
            kept = json.loads(store.get_meta("phrase_matches"))
            kept["files"][one][2] += 1
            store.set_meta("phrase_matches", json.dumps(kept, ensure_ascii=False))
        elif damage == "vocabulary":                    # a row past the last but one: the ids no longer run unbroken
            top = store.conn.execute("SELECT max(id) FROM types").fetchone()[0]
            store.conn.execute("INSERT INTO types(id, lemma, reading, surface, orth) VALUES(?, ?, ?, ?, ?)",
                               (top + 2, "欠", "ケツ", "欠", "欠"))
        else:                                           # the episode changed since its songs were kept: its stamp
            store.conn.execute("UPDATE files SET mtime = mtime + 5 WHERE path = ?", (one,))
        store.conn.commit()
        other = _copy(store, tmp_path, "whole.db")
        try:
            _counted_again(other, songs, whole=True)
            want = _songs_kept(other)
        finally:
            other.close()
        asked = _counted_again(store, songs)
        whole = {p: n for p, n, only in asked if not only}
        numbers = {ti._norm(p): sorted(n) for p, n in songs.items() if n}
        if damage == "vocabulary":
            assert whole == numbers, "every file, every line"
        else:
            assert whole == {one: numbers[one]}, "that file alone, every song line"
            assert sorted(p for p, _n, only in asked if only and p != one) == [p for p in sung if p != one],                 "the rest: their phrases alone"
        got = _songs_kept(store)
        assert got[0] == want[0], "the songs table byte for byte"
        assert _sum_counts(got[1]) == _sum_counts(want[1]), "the sum: the same counts"
    finally:
        store.close()


def test_a_refind_and_a_first_song_count_decode_each_files_names_once(library, monkeypatch, tmp_path):
    # why: the re-find decoded a re-read file's recorded names twice (to search it, and to say what the tables make of
    # them), the first song count twice too (its tag, its lines' joins) — one decode gives both
    real, decoded = ti._decode_counts, []

    def counting(blob):
        if blob:
            decoded.append(bytes(blob))
        return real(blob)
    monkeypatch.setattr(ti, "_decode_counts", counting)
    store = _index(library)
    try:
        held = [bytes(b) for (b,) in store.conn.execute(f"SELECT names FROM files WHERE {ti._EVIDENCE}") if b]
        assert held, "the files record name candidates"
        decoded.clear()
        _refind(store, monkeypatch, "gated", 1)
        assert Counter(b for b in decoded if b in set(held)) == Counter(held), "each file's names once"
    finally:
        store.close()
    store, songs = _songs_library(tmp_path)
    try:
        store.conn.execute("DELETE FROM songs")
        store.conn.commit()
        store.set_meta("songs_counted", "{}")
        names = {p: bytes(b) for p, b in store.conn.execute("SELECT path, names FROM files") if b}
        sung = [names[ti._norm(p)] for p, n in songs.items() if n and ti._norm(p) in names]
        assert sung, "the song files record name candidates"
        decoded.clear()
        store.keep_song_counts(songs)
        assert Counter(b for b in decoded if b in set(sung)) == Counter(sung), "each song file's names once"
    finally:
        store.close()


def test_a_gated_refind_tries_a_phrase_only_where_a_whole_run_of_its_words_starts(library, monkeypatch):
    # why: find tried every place a phrase's first word stands (に, と … open many), walking on wherever a second word
    # went on; the gate already knows where a phrase's whole lemma run starts, and a match starts nowhere else — the
    # kept tallies and matches stay byte for byte
    for switch in ("names_recurring", "names_kanji", "names_work_terms"):
        monkeypatch.setitem(analyzer.LOGIC, switch, False)  # (no join: each sentence's words are its ids')
    store = _index(library)
    try:
        _refind(store, monkeypatch, "whole", 10 ** 9)
        before = _kept(store)
        keys = {entry.key for entry in phrases.load().entries}
        longest = max(map(len, keys))
        tried, real = [], phrases.PhraseSet._longest

        def spy(self, node, tokens, lemmas, i, limit, text, n, among=None):
            if among is None:
                tried.append(any(tuple(lemmas[i:i + k]) in keys for k in range(1, longest + 1)))
            return real(self, node, tokens, lemmas, i, limit, text, n, among)
        monkeypatch.setattr(phrases.PhraseSet, "_longest", spy)
        _refind(store, monkeypatch, "gated", 1)
        assert tried and all(tried), "each place tried starts a phrase's whole run"
        assert _kept(store) == before
    finally:
        store.close()
