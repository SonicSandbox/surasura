"""Idioms and set phrases on the list (Settings -> Language & Parsing, logic.phrase_rows) — what a Generate lists.

The tokenizer never joins a phrase; with the switch on (the default) the analyzer finds the dictionary's set phrases in
the words it already has (app/phrases.py) and gives each one met as often as the cut-off asks of a word a row of its
own: its Word the lemmas joined (気が付く), its Orth the commonest spelling (気がつく). It is additive — every word keeps
its row and uses, coverage and the cut-off stay the tokens' — except that a word living only inside its phrase (手っ取り
in 手っ取り早い) gives the phrase its uses there. A phrase is ready once every other real word in it is known: one whose
real words are all known sits lower (half score), one waiting for a new word sorts after it. Off, every output is what
a run without the phrases writes, and the phrase modules are never used.

A sandboxed library (SURASURA_TEST_ROOT) holding tests/Test Resources/ja/phrases_sample.srt — made-up cues with the
phrases in several forms, one of them across a comma — and the shipped phrase data. Floors are raw counts (--min-freq).
"""

import json
import os
import shutil
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import app
from app import analyzer

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja", "phrases_sample.srt")
OUTPUTS = ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json", "library_frequency.json",
           "file_words.json", "analyzed_files.json", "file_statistics.json", "file_statistics.txt",
           "reading_words.csv", "sources.json")
# The phrases the fixture meets twice or more, by their rows' Word — and the words that live only inside them.
PHRASE_ROWS = {"気が付く", "気を付ける", "手っ取り早い", "若しか為るた", "本題に入る", "眉根を寄せる", "首を傾げる"}
BOUND = {"手っ取り", "眉根", "傾げる"}


@pytest.fixture
def library():
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    shutil.copy(FIXTURE, high / "phrases_sample.srt")
    (root / "User Files" / "ja").mkdir(parents=True)
    _lists(root)
    (root / "results").mkdir(exist_ok=True)
    return root


def _lists(root, known=(), ignore=()):
    uf = root / "User Files" / "ja"
    (uf / "KnownWord.json").write_text(json.dumps(
        {"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, ensure_ascii=False), encoding="utf-8")
    (uf / "IgnoreList.txt").write_text("\n".join(ignore), encoding="utf-8")


def _switch(root, on):
    """The switch as the dashboard saves it (settings.json, read fresh by the token store) and as a run reads it
    (the analyzer's logic block, read when a run's process starts)."""
    (root / "settings.json").write_text(json.dumps({"logic": {"phrase_rows": on}}), encoding="utf-8")
    analyzer.LOGIC["phrase_rows"] = on


def _run(root, *extra):
    """One Generate -> {Word: row} of the priority list; every output file is replaced (no skip)."""
    results = root / "results"
    for name in OUTPUTS + ("run_signature.txt",):
        if (results / name).exists():
            (results / name).unlink()
    with patch("app.analyzer.RESULTS_DIR", str(results)), \
            patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
            patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
            patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
            patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "2", *extra]):
        analyzer.main()
    listed = results / "priority_learning_list.csv"
    rows = pd.read_csv(listed, keep_default_na=False).to_dict("records") if listed.exists() else []
    return {row["Word"]: row for row in rows}


def _outputs(root):
    return {name: (root / "results" / name).read_bytes() for name in OUTPUTS if (root / "results" / name).exists()}


WORD_COLUMNS = ("Word", "Orth", "Forms", "Reading", "Tier", "Score", "Occurrences", "Count (High)", "Count (Low)",
                "Count (Goal)", "Modality", "Sources")


def test_off_every_output_is_a_run_without_the_phrases(library, monkeypatch):
    """Off: a run writes byte for byte what it writes when the phrase modules can't even be used — they are never
    touched (a stand-in records any use), and the known-words cache and the store count no phrase."""
    _switch(library, False)
    _run(library)
    plain = _outputs(library)
    used = []
    stand_in = types.ModuleType("stand_in")
    stand_in.__getattr__ = lambda name: used.append(name) or (_ for _ in ()).throw(AttributeError(name))
    for name in ("phrases", "phrase_data"):
        monkeypatch.setitem(sys.modules, f"app.{name}", stand_in)
        monkeypatch.setattr(app, name, stand_in, raising=False)
    _run(library)
    assert _outputs(library) == plain and len(plain) >= 9
    assert used == [], "no phrase module was used"
    rows = pd.read_csv(library / "results" / "priority_learning_list.csv", keep_default_na=False)
    assert not PHRASE_ROWS & set(rows["Word"]) and BOUND <= set(rows["Word"])


def test_on_adds_the_phrase_rows_and_every_word_row_stays_but_the_bound_ones(library):
    """On: the phrase rows are added and every word row is what it was off — its spellings, counts, score, tiers and
    sources — except a word that lives only inside its phrase: here all its uses were inside it, so it leaves the list
    (手っ取り from 手っ取り早い, 眉根, 傾げる)."""
    _switch(library, False)
    off = _run(library)
    _switch(library, True)
    on = _run(library)
    assert set(on) - set(off) == PHRASE_ROWS
    assert set(off) - set(on) == BOUND
    for word, row in off.items():
        if word not in BOUND:
            assert {c: on[word][c] for c in WORD_COLUMNS} == {c: row[c] for c in WORD_COLUMNS}, word


def test_a_phrase_row_counts_every_form_but_never_across_a_comma(library):
    """気がついた and 気が付いて are two uses of 気が付く — named 気がつく, its commonest spelling, its reading the
    dictionary's; 気が、ついたら is none (the comma between its words), and ふと気がつくと is its own phrase (気が付くと,
    met once). 気をつけて is 気をつける + て: three uses of 気を付ける with 気をつける itself. Coverage is the tokens': a
    phrase row learned in the progressive list makes no more of the file known."""
    _switch(library, True)
    rows = _run(library)
    notice = rows["気が付く"]
    assert (notice["Orth"], notice["Reading"], notice["Occurrences"]) == ("気がつく", "キガツク", 2)
    assert set(notice["Forms"].split("|")) == {"気がつい", "気が付い"}
    assert rows["気を付ける"]["Occurrences"] == 3 and rows["気を付ける"]["Orth"] == "気をつける"
    assert rows["若しか為るた"]["Orth"] == "もしかしたら" and rows["若しか為るた"]["Reading"] == "モシカシタラ"
    assert rows["付く"]["Occurrences"] == 4, "the words keep every use (気が、ついたら included)"
    prog = pd.read_csv(library / "results" / "progressive_learning_list.csv", keep_default_na=False)
    for _, row in prog[prog["Word"].isin(PHRASE_ROWS)].iterrows():
        assert row["Current %"] == row["New %"], row["Word"]


def test_a_phrase_of_known_words_sits_lower_and_one_waiting_for_a_word_sorts_after_it(library):
    """本題に入る waits for 本題 while 本題 is new: full score, listed after 本題 (the two tie). Once 本題 and 入る are
    known it is ready, every real word known: half score. 眉根を寄せる is ready with 眉根 new — 眉根 lives only
    inside it — but not every real word is known, so it keeps its full score."""
    _switch(library, True)
    rows = _run(library)
    order = list(rows)
    assert rows["本題に入る"]["Score"] == rows["本題"]["Score"] == 20
    assert order.index("本題") < order.index("本題に入る")
    _lists(library, known=["本題", "入る", "寄せる"])
    rows = _run(library)
    assert rows["本題に入る"]["Score"] == 10, "every real word known: half"
    assert rows["眉根を寄せる"]["Score"] == 20, "its bound word is still new: full"


def test_a_waiting_phrases_own_new_word_counts_in_its_sentences(library, monkeypatch):
    """A phrase row's example sentences count the words outside it — and the words it waits for (本題 in 本題に入る,
    付く and 気 in 気が付く with nothing known): never an i+1 sentence for a phrase whose own word is still new. A
    one-kanji dictionary word is waited for like any word (気 is on the list where it stands on its own)."""
    monkeypatch.setenv("SURASURA_DEBUG_WORD_STATS", "1")
    _switch(library, True)
    _run(library)
    stats = json.loads((library / "results" / "word_stats.json").read_text(encoding="utf-8"))
    subject = stats["本題に入る|ホンダイニハイル"]
    for context in subject["candidate_contexts"]:
        assert ["本題", "ホンダイ"] in context[3], context
    notice = stats["気が付く|キガツク"]
    assert all(["気", "キ"] in context[3] and ["付く", "ツク"] in context[3]
               for context in notice["candidate_contexts"]), "it waits for 付く and for 気 (a one-kanji list word)"


def test_known_or_ignored_as_a_whole_is_no_row(library):
    """A KnownWord.json 気がつく (an Anki card) makes the phrase known however the text spells it; an ignore-list line
    ignores a phrase by its spelling (もしかしたら) or by its row's Word (本題に入る)."""
    _switch(library, True)
    _lists(library, known=["気がつく"], ignore=["もしかしたら", "本題に入る"])
    rows = _run(library)
    assert not {"気が付く", "若しか為るた", "本題に入る"} & set(rows)
    assert {"気を付ける", "手っ取り早い"} <= set(rows)


def test_the_cut_off_is_a_words(library):
    """A phrase is a row by exactly a word's test: 気を付ける (3 uses) at a floor of 3, 気が付く (2) not."""
    _switch(library, True)
    rows = _run(library, "--min-freq", "3")
    assert "気を付ける" in rows and "気が付く" not in rows


def test_without_the_token_store_the_phrase_rows_are_the_same(library):
    """The store can be locked or damaged: the run then finds the phrases in its own first pass over the library and
    reads them from there — the same rows, counts and example sentences as with the store's index."""
    import sqlite3
    _switch(library, True)
    _run(library)
    with_store = {name: (library / "results" / name).read_bytes()
                  for name in ("priority_learning_list.csv", "progressive_learning_list.csv")}
    with patch("app.token_index.open_store", side_effect=sqlite3.OperationalError("database is locked")):
        rows = _run(library)
    assert PHRASE_ROWS <= set(rows)
    assert {name: (library / "results" / name).read_bytes() for name in with_store} == with_store


def test_a_phrase_whose_words_joined_are_a_word_is_no_row(library, monkeypatch):
    """A phrase whose lemmas joined are a word the library holds keeps no row of its own — the word keeps its row:
    今日 + は is the greeting こんにちは's lemma (今日は)."""
    from app import phrases
    (library / "data" / "ja" / "HighPriority" / "greeting.txt").write_text(
        "こんにちは。\n今日は雨です。\n今日は晴れです。\n", encoding="utf-8")
    fake = phrases.PhraseSet([["今日|は", "キョウ|ハ", "cg", "今日は", "キョウハ"],
                              ["気|が|付く", "キ|ガ|ツク", "cgc", "気がつく", "キガツク"]])
    monkeypatch.setattr(phrases, "load", lambda: fake)
    _switch(library, True)
    rows = _run(library)
    assert "今日は" not in rows or rows["今日は"]["Reading"] == "コンニチハ", "the greeting's row, never the phrase"
    assert "気が付く" in rows


def test_a_new_phrase_puts_a_sentence_after_cleaner_ones_among_a_words_examples():
    """やっと's example sentences, every other word in them known: its first sentence leads, as always; of the other
    two, やっと気がついた holds the phrase 気が付く — a row further down the list (its words known: half score), so
    still new at やっと's place — and やっと雨が止んだ holds none. On, the cleaner one comes first; off, file order. No
    sentence is taken away: an i+1 sentence stays i+1 (the phrase is no unknown of its own)."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (high / "yatto.txt").write_text("\n".join(["やっと晴れた。", "やっと気がついた。", "やっと雨が止んだ。", "気がついた。"]),
                                    encoding="utf-8")
    (root / "User Files" / "ja").mkdir(parents=True)
    _lists(root, known=["晴れる", "気", "が", "付く", "た", "雨", "止む", "だ"])
    (root / "results").mkdir(exist_ok=True)
    _switch(root, True)
    rows = _run(root)
    assert rows["気が付く"]["Score"] < rows["漸と"]["Score"], "the phrase is further down the list"
    on = [rows["漸と"][f"Context {n}"] for n in (1, 2, 3)]
    _switch(root, False)
    off = [_run(root)["漸と"][f"Context {n}"] for n in (1, 2, 3)]
    assert off == ["やっと晴れた。", "やっと気がついた。", "やっと雨が止んだ。"]
    assert on == ["やっと晴れた。", "やっと雨が止んだ。", "やっと気がついた。"]


def test_chinese_is_never_read_for_phrases(monkeypatch):
    """A Chinese run with the switch on writes what it writes off, and never asks for the phrases."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "zh" / "HighPriority"
    high.mkdir(parents=True)
    (high / "news.txt").write_text("我们今天去学校。\n我们明天去学校。\n他们今天在家。\n", encoding="utf-8")
    (root / "User Files" / "zh").mkdir(parents=True)
    (root / "User Files" / "zh" / "KnownWord.json").write_text('{"words": []}', encoding="utf-8")
    (root / "results").mkdir(exist_ok=True)
    results = root / "results"

    def run():
        for name in OUTPUTS + ("run_signature.txt",):
            if (results / name).exists():
                (results / name).unlink()
        with patch("app.analyzer.RESULTS_DIR", str(results)), \
                patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
                patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
                patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
                patch("sys.argv", ["analyzer.py", "--language", "zh", "--min-freq", "2"]):
            analyzer.main()
        return {name: (results / name).read_bytes() for name in OUTPUTS if (results / name).exists()}
    _switch(root, False)
    off = run()
    used = []
    from app import phrases
    monkeypatch.setattr(phrases, "load", lambda: used.append(1))
    _switch(root, True)
    assert run() == off and used == []
