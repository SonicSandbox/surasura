"""Japanese term sanitization is now always on (the toggle was removed). This locks in the
two things that buys: Unidic gloss suffixes (e.g. テスト-test) are stripped so words display
clean, AND a suffixed lemma matches its clean frequency-list entry — the fix for what was
analyzer-02 (tier lookup silently returning "Outside" when sanitization was off)."""
import os
import sys
import shutil
import tempfile

import pytest
import pandas as pd

from app import analyzer


@pytest.fixture
def ja_env():
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
    # Frequency list keyed by the CLEAN dictionary form.
    with open(os.path.join(uf, "frequency_list_ja_test.csv"), "w", encoding="utf-8") as f:
        f.write("Word,Rank\nテスト,1\n")
    results = os.path.join(temp, "results")
    os.makedirs(results)

    analyzer.get_data_path = lambda lang=None: data_dir
    analyzer.get_user_files_path = lambda lang=None: uf
    analyzer.RESULTS_DIR = results
    analyzer.OUTPUT_CSV = os.path.join(results, "priority_learning_list.csv")
    analyzer.OUTPUT_STATS = os.path.join(results, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results, "progressive_learning_list.csv")
    yield {"data": data_dir, "results": results}
    shutil.rmtree(temp, ignore_errors=True)


def test_suffixed_lemma_is_sanitized_and_matches_its_tier(ja_env):
    # テスト lemmatizes to 'テスト-test' in Unidic-lite; sanitization strips it back to テスト.
    text = "これはテストです。テストをする。テストが好き。"
    with open(os.path.join(ja_env["data"], "HighPriority", "t.txt"), "w", encoding="utf-8") as f:
        f.write(text)

    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    df = pd.read_csv(os.path.join(ja_env["results"], "priority_learning_list.csv"))
    words = set(df["Word"].astype(str))

    # (a) Displayed clean — not the raw Unidic lemma.
    assert "テスト" in words
    assert "テスト-test" not in words

    # (b) The (formerly suffixed) lemma now matches the frequency list => a real tier, not "Outside".
    row = df[df["Word"] == "テスト"].iloc[0]
    assert str(row["Tier"]) != "Outside"
