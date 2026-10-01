"""The set phrases in the token store and the Rarity slider (Settings -> "Idioms and set phrases on your list").

The slider and automatic rarity count the list Generate writes, so with the switch on they count its phrase rows too:
after a reconcile the store counts each file's phrases in its cached tokens (the name tables applied, as a run reads
them) — one tally per file, re-read only for the files that changed — and the preview adds the phrases the learner
neither knows nor ignores, taking a bound word's uses inside its phrase off the word. Off, the store counts none and
the known-words cache keeps its old key. The GUI process never needs the tokenizer for any of it.
"""

import json
import os
import shutil
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, phrases, settings_manager, token_index, word_selection

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja", "phrases_sample.srt")
BANDS_PPM = {"core": 60000, "common": 30000, "occasional": 20000, "uncommon": 12000, "rare": 7000,
             "very_rare": 4000, "native": 1}


@pytest.fixture
def library():
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    shutil.copy(FIXTURE, high / "phrases_sample.srt")
    uf = root / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text('{"words": []}', encoding="utf-8")
    (root / "results").mkdir(exist_ok=True)
    return root


def _switch(root, on, **logic):
    (root / "settings.json").write_text(json.dumps({"logic": dict(logic, phrase_rows=on)}), encoding="utf-8")
    analyzer.LOGIC["phrase_rows"] = on


def _files(root):
    return [str(p) for p in (root / "data" / "ja" / "HighPriority").iterdir()]


def _reconcile(root):
    analyzer.SANITIZE_JA = True
    store = token_index.open_store("ja")
    store.reconcile(_files(root), token_index.make_tokenizer("ja"), build_signature=token_index.build_signature("ja"))
    return store


def _generate(root):
    """One Generate (no skip) at a raw floor of 2 -> the priority list's text."""
    results = root / "results"
    for name in ("priority_learning_list.csv", "run_signature.txt"):
        if (results / name).exists():
            (results / name).unlink()
    with patch("app.analyzer.RESULTS_DIR", str(results)), \
            patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
            patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
            patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
            patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "2"]):
        analyzer.main()
    return (results / "priority_learning_list.csv").read_text(encoding="utf-8-sig")


def test_the_store_counts_each_phrase_as_generate_lists_it(library):
    """After an index: 気を付ける met 3 times (気をつけて folds into it), 気が付く twice (never across the comma), and
    the uses 手っ取り and 眉根 give their phrases."""
    _switch(library, True)
    store = _reconcile(library)
    try:
        table = store.phrase_table()
    finally:
        store.close()
    rows = table["rows"]
    assert rows["気を付ける|キヲツケル"][0] == 3 and rows["気が付く|キガツク"][0] == 2
    assert {"気がつく", "気がつい", "気が付い"} <= set(rows["気が付く|キガツク"][1])
    assert table["taken"]["手っ取り|テットリ"] == 2 and table["taken"]["眉根|マユネ"] == 2


def test_off_the_store_counts_no_phrase_and_the_known_cache_keeps_its_key(library, monkeypatch):
    """Off: no phrase table, the phrase modules untouched, and the known-words cache's key as it was — so a user who
    switches it off reads nothing again."""
    _switch(library, False)
    monkeypatch.setattr(phrases, "load", lambda: pytest.fail("the phrases were read with the switch off"))
    store = _reconcile(library)
    try:
        assert store.phrase_table() is None and store.get_meta("phrases") is None
        assert "phrase_rows" not in store._known_key('[true, 1, 2]')
    finally:
        store.close()
    _switch(library, True)
    store = token_index.open_store("ja")
    try:
        from app import phrase_data
        assert store._known_key('[true, 1, 2]').endswith(f"|phrase_rows={phrase_data.REVISION}"), \
            "on: a known phrase reads differently, by the phrases this data holds"
    finally:
        store.close()


def test_a_changed_file_is_counted_again_and_new_data_counts_every_file_again(library, monkeypatch):
    """One tally per file: an unchanged library reads no file again; a new file is read alone; new phrase data (its
    revision) reads every file again."""
    _switch(library, True)
    store = _reconcile(library)
    store.close()
    read = []
    real = phrases.tally
    monkeypatch.setattr(phrases, "tally", lambda sentences, found, matches=None:
                        read.append(1) or real(sentences, found, matches))
    store = _reconcile(library)
    store.close()
    assert read == [], "nothing changed: no file read again"
    (library / "data" / "ja" / "HighPriority" / "more.txt").write_text("車に気をつけて。\n", encoding="utf-8")
    store = _reconcile(library)
    try:
        assert len(read) == 1 and store.phrase_table()["rows"]["気を付ける|キヲツケル"][0] == 4
    finally:
        store.close()
    from app import phrase_data
    monkeypatch.setattr(phrase_data, "REVISION", phrase_data.REVISION + "-next")
    read.clear()
    store = _reconcile(library)
    store.close()
    assert len(read) == 2, "new data: every file again"


NAMES = {"k": {"ローゼマイン": [0.9, "ローゼマイン", "", "ローゼマイン"]}, "j": {"帆波": [3, "帆波", "", "帆波"]},
         "w": {"卍解": [1.0, "卍解", "", "卍解"]}, "stamp": "a1"}


def _spans(*spans):
    """A file's recorded name candidates as the store keeps them — only each span's kind and spelling matter here."""
    return token_index._encode_counts({"s": [[0, 0, 2, [], [], kind, spelling] for kind, spelling in spans]})


def test_what_the_name_tables_make_of_a_files_names_moves_only_with_its_words():
    """A file's words read differently only when a table starts or stops holding one of its names (a term inside a run
    of one-kanji words included) or names it otherwise — never as the tables' evidence grows (stickiness, the kanji
    evidence bits), and never for a name the file doesn't hold. A switched-off table holds nothing."""
    blob = _spans(("k", "ローゼマイン"), ("w", "卍解放"), ("j", "坂柳"))
    on = (True, True, True)
    reads = token_index._names_reads(NAMES)
    held = token_index._names_read_in(blob, reads, on)
    assert held and token_index._names_read_in(None, reads, on) == "" and token_index._names_read_in(blob, {}, on) == ""
    grown = dict(NAMES, k={"ローゼマイン": [0.95, "ローゼマイン", "", "ローゼマイン"]}, j={"帆波": [1, "帆波", "", "帆波"]},
                 stamp="b2")
    assert token_index._names_reads(grown) == reads, "evidence moved, no word did"
    other = dict(NAMES, k={**NAMES["k"], "ダームエル": [1.0, "ダームエル", "", "ダームエル"]})
    assert token_index._digest(token_index._names_reads(other)) != token_index._digest(reads)
    assert token_index._names_read_in(blob, token_index._names_reads(other), on) == held, "not a name it holds"
    joined = dict(NAMES, j={**NAMES["j"], "坂柳": [1, "坂柳", "", "坂柳"]})
    assert token_index._names_read_in(blob, token_index._names_reads(joined), on) != held
    no_term = dict(NAMES, w={})
    assert token_index._names_read_in(blob, token_index._names_reads(no_term), on) != held
    assert token_index._names_read_in(blob, reads, (False, True, True)) != held


def test_a_name_table_that_moves_rereads_only_the_files_whose_words_it_changes(library, monkeypatch):
    """After an index the name tables' evidence moves with nearly every new file: no file is read again for it, nor
    for a name the library's files don't hold; Generate still trusts the kept matches."""
    _switch(library, True)
    store = _reconcile(library)
    try:
        store.set_meta("names_tables", json.dumps(NAMES, ensure_ascii=False))
        store._update_phrases(True)
        read = []
        real = phrases.tally
        monkeypatch.setattr(phrases, "tally", lambda sentences, found, matches=None:
                            read.append(1) or real(sentences, found, matches))
        grown = dict(NAMES, k={"ローゼマイン": [0.95, "ローゼマイン", "", "ローゼマイン"],
                               "ダームエル": [1.0, "ダームエル", "", "ダームエル"]}, stamp="b2")
        store.set_meta("names_tables", json.dumps(grown, ensure_ascii=False))
        store._names = None
        store._update_phrases(True)
        assert read == [], "no file holds a name that moved"
        assert set(store.phrase_matches(_files(library))) == set(_files(library))
    finally:
        store.close()


def test_a_file_whose_names_read_otherwise_is_counted_again_alone(library, monkeypatch):
    """When what the tables join changes, each file's names are looked at again, and only a file whose words now
    read otherwise is counted again."""
    _switch(library, True)
    (library / "data" / "ja" / "HighPriority" / "more.txt").write_text("車に気をつけて。\n", encoding="utf-8")
    store = _reconcile(library)
    try:
        (moved,) = store.conn.execute("SELECT names FROM files WHERE path LIKE '%more.txt'").fetchone()
        monkeypatch.setattr(token_index, "_names_reads", lambda tables: {"k": {"ダームエル": ["ダームエル", "", "ダームエル"]}})
        monkeypatch.setattr(token_index, "_names_read_in", lambda blob, reads, switches: "x" if blob == moved else "")
        read = []
        real = phrases.tally
        monkeypatch.setattr(phrases, "tally", lambda sentences, found, matches=None:
                            read.append(sentences[0][0]) or real(sentences, found, matches))
        store._update_phrases(True)
        assert read == ["車に気をつけて。"]
        assert store.phrase_table()["rows"]["気を付ける|キヲツケル"][0] == 4
    finally:
        store.close()


def test_generate_reads_each_files_phrases_from_the_index_and_searches_a_file_they_dont_fit(library, monkeypatch):
    """An index keeps each file's matches — the uses the table counts — so Generate never searches a sentence for
    the phrases again. Matches that don't fit the file's words (it changed since) are not trusted: that file is
    searched, and the list is the same either way. Counted with other phrase data, none are kept."""
    _switch(library, True)
    store = _reconcile(library)
    try:
        path = _files(library)[0]
        sentences, flat = store.phrase_matches([path])[path]
        assert sentences == len(store.file_tokens(path)) and len(flat) % 4 == 0
        met = Counter(phrases.load().entry(index).word for index in flat[3::4])
        assert met["気を付ける"] == 3 and met["気が付く"] == 2, "the uses the table counts"
    finally:
        store.close()
    searched = []
    real_find = phrases.PhraseSet.find
    monkeypatch.setattr(phrases.PhraseSet, "find",
                        lambda self, tokens, text: searched.append(text) or real_find(self, tokens, text))
    listed = _generate(library)
    assert searched == [] and "気がつく" in listed, "every sentence's phrases came from the index"
    store = token_index.open_store("ja")
    try:
        kept = json.loads(store.get_meta("phrase_matches"))
        for entry in kept["files"].values():
            entry[3] = [n + 1 if k % 4 == 1 else n for k, n in enumerate(entry[3])]     # each one a word later
        store.set_meta("phrase_matches", json.dumps(kept))
    finally:
        store.close()
    assert _generate(library) == listed and searched, "matches that don't fit: the file searched, the same list"
    from app import phrase_data
    monkeypatch.setattr(phrase_data, "REVISION", phrase_data.REVISION + "-next")
    store = token_index.open_store("ja")
    try:
        assert store.phrase_matches([path]) == {}
    finally:
        store.close()


def test_the_preview_counts_phrase_rows_and_takes_a_bound_words_uses_off_it(library):
    """The preview's unknowns hold the phrase rows by their own keys, without the ones known or ignored as a whole
    (by a spelling, by the row's Word) or whose lemmas joined are a word; a bound word counts without its uses inside
    its phrase. Coverage stays the tokens'."""
    _switch(library, True)
    store = _reconcile(library)
    try:
        counts, total = store.word_counts()
        table = store.phrase_table()
    finally:
        store.close()
    plain = dict(token_index.unknown_distribution(counts, total, language="ja")["unknown"])
    freqs = token_index.unknown_distribution(counts, total, set(), {"もしかしたら"}, {"本題に入る"}, True, "ja", table)
    unknown = dict(freqs["unknown"])
    assert unknown["気を付ける|キヲツケル"] == 3 and unknown["手っ取り早い|テットリバヤイ"] == 2
    assert "若しか為るた|モシカシタラ" not in unknown and "本題に入る|ホンダイニハイル" not in unknown
    assert unknown["手っ取り|テットリ"] == plain["手っ取り|テットリ"] - 2 == 0
    assert freqs["all_counts"] == sorted(counts.values()), "coverage stays the tokens'"
    clash = dict(table, rows=dict(table["rows"], **{"付く|ツク": [5, []]}))
    assert "付く|ツク" in dict(token_index.unknown_distribution(counts, total, language="ja", phrases=clash)["unknown"])
    assert all(n != 5 or name != "付く|ツク" for name, n in token_index.unknown_distribution(
        counts, total, language="ja", phrases=clash)["unknown"]), "a word's own row wins over a phrase spelled so"


def test_the_band_preview_counts_the_list_generate_writes_phrases_included(library):
    """The slider's "N words" for each band is the length of the list Generate writes at that band — phrase rows in,
    bound words' uses inside their phrases out, on both sides."""
    root = library
    counted = {}
    for band in word_selection.BANDS_ORDER:
        _switch(root, True, selection={"band": band, "bands_ppm": BANDS_PPM, "min_count": 2})
        analyzer.LOGIC["selection"] = settings_manager.load_settings()["logic"]["selection"]
        results = root / "results"
        for name in ("priority_learning_list.csv", "run_signature.txt"):
            if (results / name).exists():
                (results / name).unlink()
        with patch("app.analyzer.RESULTS_DIR", str(results)), \
                patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
                patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
                patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
                patch("sys.argv", ["analyzer.py", "--language", "ja"]):
            analyzer.main()
        listed = results / "priority_learning_list.csv"
        counted[band] = len(pd.read_csv(listed)) if listed.exists() else 0
    store = token_index.open_store("ja")
    try:
        freqs = token_index.preview_frequencies(store, "ja", str(root / "User Files" / "ja"))
    finally:
        store.close()
    previews = word_selection.band_previews(freqs, BANDS_PPM, 2)
    assert {band: p["word_count"] for band, p in previews.items()} == counted
    assert any(n for n in counted.values()) and len(set(counted.values())) >= 2, counted
