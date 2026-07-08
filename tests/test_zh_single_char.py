import os
import sys
import shutil
import tempfile

import pytest
import pandas as pd

from app import analyzer


@pytest.fixture
def zh_env():
    """A temporary Chinese analysis environment, mirroring the analyzer-mock pattern used by
    test_dynamic_contexts but for zh. The analyzer module globals are pointed at temp paths."""
    temp_dir = tempfile.mkdtemp()

    data_dir = os.path.join(temp_dir, "data", "zh")
    for bucket in ("HighPriority", "LowPriority", "GoalContent"):
        os.makedirs(os.path.join(data_dir, bucket))

    user_files_dir = os.path.join(temp_dir, "User Files", "zh")
    os.makedirs(user_files_dir)
    # Empty known/ignore/blacklist so every word is "unknown" and eligible for the list.
    with open(os.path.join(user_files_dir, "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        with open(os.path.join(user_files_dir, name), "w", encoding="utf-8") as f:
            f.write("")

    results_dir = os.path.join(temp_dir, "results")
    os.makedirs(results_dir)

    analyzer.get_data_path = lambda lang=None: data_dir
    analyzer.get_user_files_path = lambda lang=None: user_files_dir
    analyzer.RESULTS_DIR = results_dir
    analyzer.OUTPUT_CSV = os.path.join(results_dir, "Priority_Words.csv")
    analyzer.OUTPUT_STATS = os.path.join(results_dir, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results_dir, "Progressive_Coverage.csv")

    yield {"data_dir": data_dir, "results_dir": results_dir}

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_chinese_single_char_words_are_retained(zh_env):
    """Most high-frequency Chinese words are single characters. With exclude_single left at its
    default (skip ON), the engine used to drop them for zh too, gutting the vocab list
    (finding analyzer-04). It must now keep single-char tokens for Chinese."""
    data_dir = zh_env["data_dir"]
    results_dir = zh_env["results_dir"]

    # Real Chinese sentences repeating the single-character word 猫 (cat).
    text = "我有一只猫。猫很可爱。我喜欢这只猫。猫在睡觉。"
    with open(os.path.join(data_dir, "HighPriority", "cat.txt"), "w", encoding="utf-8") as f:
        f.write(text)

    # No --include-single-chars flag => default skip is ON; this is the exact bug scenario.
    sys.argv = ["analyzer.py", "--language", "zh", "--context-min", "0", "--min-freq", "1"]
    analyzer.main()

    csv_path = os.path.join(results_dir, "Priority_Words.csv")
    assert os.path.exists(csv_path)
    df = pd.read_csv(csv_path)

    words = set(df["Word"].astype(str))
    assert "猫" in words, "single-character Chinese word 猫 must be retained, not skipped"
