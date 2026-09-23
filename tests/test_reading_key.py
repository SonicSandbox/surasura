"""A Japanese word is ONE row, however it is conjugated (Bugfix_Batch_2026-09-22_Spec.md, Fix C).

Words are keyed by (lemma, reading). The reading used to be the kana of the conjugated SURFACE, so a
verb split into one row per conjugation: on the live list 辿り着く sat on four rows (タドリツイ 102,
タドリツク 40, タドリツケ 32, タドリツキ 18) and ranked far below its true 192, and 立ち入る (31 uses)
never appeared because no single form cleared the floor. The reading is now the lemma's (UniDic
lForm) — one value per word, which still tells real homographs (上手: ジョウズ / カミテ) apart.

End-to-end through analyzer.main(), the harness of tests/test_selection_integration.py, on real
Japanese sentences verified against the project's fugashi + unidic-lite.
"""

import json

import pandas as pd
import pytest
from unittest.mock import patch

from app import analyzer

# One verb, three conjugations: 辿り着い(た) / 辿り着く / 辿り着け(ば).
JOURNEY = ("長い旅の末に、ついに城へ辿り着いた。\n"
           "この道を行けば、必ず海に辿り着く。\n"
           "明日の朝までに辿り着けば間に合う。\n")

# Three uses of 立ち入る, each in a different form — alone, no form reaches a floor of 2.
NO_ENTRY = ("関係者以外はこの部屋に立ち入らないでください。\n"
            "彼は許可なく研究所に立ち入った。\n"
            "ここから先は誰も立ち入ることができない。\n")

# 上手 is two words: ジョウズ (skilful) twice, カミテ (stage left) once.
STAGE = ("彼女は日本語を上手に話せる。\n"
         "役者が舞台の上手から入ってきた。\n"
         "兄は料理がとても上手だ。\n")


@pytest.fixture
def env(tmp_path):
    def build(text, language="ja", known=()):
        uf = tmp_path / "User Files" / language
        uf.mkdir(parents=True, exist_ok=True)
        high = tmp_path / "data" / language / "HighPriority"
        high.mkdir(parents=True, exist_ok=True)
        (tmp_path / "results").mkdir(exist_ok=True)
        words = [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]
        (uf / "KnownWord.json").write_text(json.dumps({"words": words}, ensure_ascii=False),
                                           encoding="utf-8")
        (high / "content.txt").write_text(text, encoding="utf-8")
        return tmp_path
    return build


def _run(root, *args, language="ja"):
    """Run a real analysis against `root` only (patch app.analyzer.*, never app.path_utils.* —
    testing.md §5.2). Returns (priority rows, progressive rows) as DataFrames."""
    results = root / "results"
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", language] + list(args)):
        analyzer.main()

    def read(name):
        path = results / name
        if not path.exists():
            return pd.DataFrame(columns=["Word", "Reading"])
        return pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    return read("priority_learning_list.csv"), read("progressive_learning_list.csv")


def test_a_verb_is_one_row_however_it_is_conjugated(env):
    """辿り着いた / 辿り着く / 辿り着けば: one row, all three uses counted, under the dictionary
    form's reading — in the priority list and the per-file progressive list alike."""
    priority, progressive = _run(env(JOURNEY), "--min-freq", "1")

    rows = priority[priority["Word"] == "辿り着く"]
    assert len(rows) == 1, f"split across rows: {rows[['Reading', 'Occurrences']].values.tolist()}"
    assert rows.iloc[0]["Reading"] == "タドリツク"
    assert int(rows.iloc[0]["Occurrences"]) == 3
    assert len(progressive[progressive["Word"] == "辿り着く"]) == 1


def test_a_word_whose_forms_only_clear_the_floor_together_is_listed(env):
    """Three uses in three different forms, one each, under a floor of 2: split by conjugation none
    of them qualified and the word vanished; counted as one word it has 3 and is listed."""
    priority, _ = _run(env(NO_ENTRY), "--min-freq", "2")

    rows = priority[priority["Word"] == "立ち入る"]
    assert len(rows) == 1, "a word used three times was dropped: each form was judged on its own"
    assert rows.iloc[0]["Reading"] == "タチイル"
    assert int(rows.iloc[0]["Occurrences"]) == 3


def test_a_known_word_counts_as_known_in_every_conjugation(env):
    """Guard (passes before and after the fix): a known 辿り着く covers 辿り着いた and 辿り着けば
    too — known words are matched by lemma, so the reading change must not reopen any form."""
    priority, _ = _run(env(JOURNEY, known=["辿り着く"]), "--min-freq", "1")

    assert "辿り着く" not in set(priority["Word"])


def test_words_with_different_lemma_readings_stay_apart(env):
    """Guard (passes before and after the fix): one lemma string, two words. The lemma's reading must
    still tell them apart — 上手 (ジョウズ, skilful) is not 上手 (カミテ, stage left)."""
    priority, _ = _run(env(STAGE), "--min-freq", "1")

    rows = priority[priority["Word"] == "上手"]
    assert sorted(zip(rows["Reading"], rows["Occurrences"].astype(int))) == [("カミテ", 1), ("ジョウズ", 2)]


def test_chinese_rows_are_unchanged(env, zh_resources_dir):
    """Guard (passes before and after the fix): Jieba has no readings — every Chinese row keeps an
    empty Reading, so the key is the word alone, exactly as before."""
    with open(f"{zh_resources_dir}/chinese_text_1.txt", encoding="utf-8") as f:
        text = f.read()
    priority, _ = _run(env(text, language="zh"), "--min-freq", "1", language="zh")

    assert len(priority) > 0
    assert set(priority["Reading"]) == {""}
    assert not priority["Word"].duplicated().any()
