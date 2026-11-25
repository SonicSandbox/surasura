"""Integration test for the example-sentence length cap (logic.context.max_chars, default 150).

A sentence longer than the cap must be excluded from a word's *secondary* example candidates,
but still kept as that word's own/original fallback when it's the only sentence it appears in.
"""
import os
import sys
import shutil
import tempfile

import pytest
import pandas as pd

from app import analyzer


# A single, long (>150 char) sentence containing BOTH target words. One '。' only, so it stays one
# sentence; padded with 、 clauses to comfortably exceed the 150-char cap.
LONG_SENTENCE = (
    "電車と飛行機はどちらも人々を遠くまで運ぶとても大切な乗り物であり、"
    "朝早くから夜遅くまでたくさんの乗客を乗せて街と街を結び、"
    "国と国をつなぎ、時には広い海を越え高い山を越えて、"
    "私たちの毎日の生活や仕事や旅行や通勤や通学を長い間ずっと支え続けている、"
    "とても便利で決して欠かせない、現代の社会になくてはならない、"
    "多くの人が日々利用している大切な交通手段の一つなのである。"
)
SHORT_SENTENCE = "電車に乗る。"


@pytest.fixture
def ja_env(monkeypatch):
    temp = tempfile.mkdtemp()
    data_dir = os.path.join(temp, "data", "ja")
    for bucket in ("HighPriority", "LowPriority", "GoalContent"):
        os.makedirs(os.path.join(data_dir, bucket))
    uf = os.path.join(temp, "User Files", "ja")
    os.makedirs(uf)
    with open(os.path.join(uf, "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        open(os.path.join(uf, name), "w", encoding="utf-8").close()
    results = os.path.join(temp, "results")
    os.makedirs(results)

    analyzer.get_data_path = lambda lang=None: data_dir
    # why: the list's sentences (level 2: analyzer.ListSentences) read the lines from the data folder path_utils names
    monkeypatch.setattr("app.path_utils.get_data_path",
                        lambda lang=None: os.path.join(temp, "data", lang) if lang else os.path.join(temp, "data"))
    analyzer.get_user_files_path = lambda lang=None: uf
    analyzer.RESULTS_DIR = results
    analyzer.OUTPUT_CSV = os.path.join(results, "priority_learning_list.csv")
    analyzer.OUTPUT_STATS = os.path.join(results, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results, "progressive_learning_list.csv")
    yield {"data": data_dir, "results": results}
    shutil.rmtree(temp, ignore_errors=True)


@pytest.mark.usefixtures("level_0")
def test_long_sentence_dropped_as_secondary_but_kept_as_fallback(ja_env):
    # why: proves the old path's fall-back (a word's own sentence kept over the cap); at level 2 a line over *Never
    # longer than* is never shown (the test below) and E-RETIRE removes both this path and this test
    assert len(LONG_SENTENCE) > 150, "test sentence must exceed the 150-char cap"

    # 電車 appears in the SHORT sentence first, then the long one. 乗客 appears ONLY in the long one.
    with open(os.path.join(ja_env["data"], "HighPriority", "t.txt"), "w", encoding="utf-8") as f:
        f.write(SHORT_SENTENCE + "\n" + LONG_SENTENCE + "\n")

    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    df = pd.read_csv(os.path.join(ja_env["results"], "priority_learning_list.csv"))
    ctx_cols = [c for c in df.columns if c.startswith("Context ")]

    def contexts_for(word):
        row = df[df["Word"] == word]
        assert not row.empty, f"{word} should be in the priority list"
        return [str(row.iloc[0].get(c) or "") for c in ctx_cols]

    # "交通手段" appears only in the long (>150) sentence — a reliable marker for it.
    # 電車 has a short alternative, so the long sentence is NOT used as one of its examples.
    train_ctx = contexts_for("電車")
    assert any("電車に乗る" in c for c in train_ctx), "the short original should be an example for 電車"
    assert not any("交通手段" in c for c in train_ctx), "the >150-char sentence must be dropped for 電車"

    # 乗客 appears ONLY in the long sentence -> it's kept as the fallback (its example).
    fallback_ctx = contexts_for("乗客")
    assert any("交通手段" in c for c in fallback_ctx), "the long sentence must be kept as 乗客's only/fallback example"


def test_a_sentence_over_the_cap_is_never_an_example_even_a_words_only_one(ja_env):
    """The sentence choice (SPEC § 4.2 item 4, § 4.3): *Never longer than* is the wall. 電車 shows its short sentence;
    the >150-character one is no word's example, 乗客's (its only sentence) neither."""
    with open(os.path.join(ja_env["data"], "HighPriority", "t.txt"), "w", encoding="utf-8") as f:
        f.write(SHORT_SENTENCE + "\n" + LONG_SENTENCE + "\n")
    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    df = pd.read_csv(os.path.join(ja_env["results"], "priority_learning_list.csv"))
    ctx_cols = [c for c in df.columns if c.startswith("Context ")]
    shown = {str(v) for c in ctx_cols for v in df[c].dropna()}
    train = df[df["Word"] == "電車"]
    assert not train.empty and any("電車に乗る" in str(train.iloc[0].get(c) or "") for c in ctx_cols)
    assert "乗客" in set(df["Word"]), "a word whose only sentence is over the cap is still listed"
    assert not any("交通手段" in s for s in shown), "the >150-char sentence is never an example"
