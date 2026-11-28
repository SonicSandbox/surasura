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
from pathlib import Path

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
    (high / "crlf.txt").write_bytes("車に気をつけて。\r\nどうもありがとうございました！\r\n".encode("utf-8"))
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
    """Search every file's phrases again, as new phrase data does (its revision moved), the gate used from
    `gate_from` files on -> the sentence count of each file `phrases.tally` was given."""
    monkeypatch.setattr(phrase_data, "REVISION", f"{phrase_data.REVISION}-{tag}")
    monkeypatch.setattr(ti, "_PHRASE_GATE_FILES", gate_from, raising=False)
    given, real = [], phrases.tally
    monkeypatch.setattr(phrases, "tally", lambda sentences, found, matches=None:
                        given.append(len(sentences)) or real(sentences, found, matches))
    store._update_phrases(True)
    monkeypatch.setattr(phrases, "tally", real)
    return given


def _can_hold(store):
    """(every sentence of the store's files, those that can hold a set phrase): a phrase's whole lemma run in a row
    in its words as `file_tokens` reads them, or a name span in it — worked out here word by word."""
    found = phrases.load()
    keys = {entry.key for entry in found.entries}
    longest = max(len(key) for key in keys)
    total = held = 0
    for path, names in store.conn.execute(f"SELECT path, names FROM files WHERE {ti._EVIDENCE}").fetchall():
        sentences = store.file_tokens(path)
        spans = {span[0] for span in store._name_spans(names)[0]}
        total += len(sentences)
        for number, (_text, tokens) in enumerate(sentences):
            lemmas = [token[0] for token in tokens]
            held += number in spans or any(tuple(lemmas[i:i + n]) in keys for i in range(len(lemmas))
                                           for n in range(1, longest + 1))
    return total, held


def test_a_big_refind_decodes_only_the_sentences_that_can_hold_a_phrase_and_keeps_the_same(library, monkeypatch):
    # why: the first Generate after a matcher change spent ~55 s decoding and searching every sentence of every file;
    # only the sentences holding a phrase's whole lemma run (or a name span) can hold a match, and what the re-find
    # keeps — the tallies the Rarity slider counts, the matches Generate reads — must not move by a byte
    store = _index(library)
    try:
        whole = _refind(store, monkeypatch, "whole", 10 ** 9)
        before = _kept(store)
        gated = _refind(store, monkeypatch, "gated", 1)
        total, held = _can_hold(store)
        assert sum(whole) == total, "read whole: every sentence"
        assert 0 < held < total, "the files hold phrases, and sentences that can't hold one"
        assert sum(gated) == held, "gated: only the sentences that can hold a phrase are decoded and searched"
        assert len(gated) == len(whole) == store.conn.execute("SELECT count(*) FROM files").fetchone()[0]
        assert _kept(store) == before, "the tallies, the matches and the table byte for byte"
        assert json.loads(store.get_meta("phrases"))["rows"]["気を付ける|キヲツケル"][0] >= 2
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
        total, held = _can_hold(store)
        assert sum(gated) == held < total
        assert _kept(store) == before
    finally:
        store.close()


def test_rows_the_gate_cant_read_are_read_whole_as_before(library, monkeypatch):
    # why: a damaged row (its texts not counting its sentences, a vocabulary row gone) must give what a whole read gives
    # it — `file_tokens` reads such a file as no sentence — never a match the whole read wouldn't keep
    store = _index(library)
    try:
        one, ids = store.conn.execute("SELECT path, ids FROM files WHERE path LIKE '%phrases_sample.srt'").fetchone()
        (other_texts,) = store.conn.execute("SELECT texts FROM files WHERE path LIKE '%placed_episode.srt'").fetchone()
        store.conn.execute("UPDATE files SET texts=? WHERE path=?", (other_texts, one))
        store.conn.commit()
        _refind(store, monkeypatch, "whole", 10 ** 9)
        before = _kept(store)
        assert json.loads(store.get_meta("phrase_matches"))["files"][one][2:4] == [0, []], "read as no sentence"
        _refind(store, monkeypatch, "gated", 1)
        assert _kept(store) == before, "the damaged file read whole, the rest gated"
        used = ti._read_ids(ids)[1][0]
        store.conn.execute("DELETE FROM types WHERE id=?", (used,))     # a gap in the vocabulary: no gate at all
        store.conn.commit()
        store._types.clear()
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
        assert built == [] and sum(whole) == _can_hold(store)[0]
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
