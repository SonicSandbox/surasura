"""Regression tests for the progressive pass reusing cached tokens instead of re-tokenizing
(analyzer-01). They lock the two invariants that make the optimization output-identical:

  1. A file's `Total Count` equals the FULL tokenize() stream length — including non-target
     tokens (e.g. embedded English), which the coverage denominator must still count.
  2. Each word's per-file `Occurrences (File)` equals its count in that stream, keyed by the
     exact (lemma, reading) pair — guarding against a lemma-only cache that would conflate
     Japanese homographs.

Both are computed independently from the tokenizer, so they can't drift with it.
"""
import sys
from collections import Counter

import pytest
import pandas as pd

from app import analyzer
from app.analyzer import JapaneseTokenizer, ChineseTokenizer


def _setup_env(tmp_path, language):
    data_dir = tmp_path / "data" / language
    for bucket in ("HighPriority", "LowPriority", "GoalContent"):
        (data_dir / bucket).mkdir(parents=True)
    uf = tmp_path / "User Files" / language
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text("{}", encoding="utf-8")
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        (uf / name).write_text("", encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()

    analyzer.get_data_path = lambda lang=None: str(data_dir)
    analyzer.get_user_files_path = lambda lang=None: str(uf)
    analyzer.RESULTS_DIR = str(results)
    analyzer.OUTPUT_CSV = str(results / "priority_learning_list.csv")
    analyzer.OUTPUT_STATS = str(results / "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = str(results / "progressive_learning_list.csv")
    return data_dir, results


def _assert_invariants(results, src_path, tokenizer, filename):
    prog = pd.read_csv(results / "progressive_learning_list.csv")
    rows = prog[prog["Source File"] == filename]
    assert not rows.empty, "expected progressive rows for the test file"

    tokens = tokenizer.tokenize(analyzer.extract_text(str(src_path), tokenizer_lang(tokenizer)))
    expected_total = len(tokens)
    expected_counts = Counter((lemma, reading) for (lemma, reading, _surface) in tokens)

    # Invariant 1: the coverage denominator counts the full token stream (non-target included).
    assert int(rows.iloc[0]["Total Count"]) == expected_total

    # Invariant 2: per-word file occurrences match the (lemma, reading)-keyed stream counts.
    for _, r in rows.iterrows():
        reading = r["Reading"] if pd.notna(r["Reading"]) else ""
        assert int(r["Occurrences (File)"]) == expected_counts[(r["Word"], reading)]


def tokenizer_lang(tokenizer):
    return "zh" if isinstance(tokenizer, ChineseTokenizer) else "ja"


def test_progressive_cache_matches_stream_japanese(tmp_path):
    data_dir, results = _setup_env(tmp_path, "ja")
    # Embedded English (non-target) + single-char + repeated multi-char words.
    text = "私はiPhoneを買った。猫が好き。OKです。本を読む。猫は可愛い。本が多い。"
    src = data_dir / "HighPriority" / "mixed.txt"
    src.write_text(text, encoding="utf-8")

    sys.argv = ["analyzer.py", "--language", "ja", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    _assert_invariants(results, src, JapaneseTokenizer(), "mixed.txt")


def test_progressive_cache_matches_stream_chinese(tmp_path):
    data_dir, results = _setup_env(tmp_path, "zh")
    text = "我有一只猫。猫很可爱。我喜欢这只猫。猫在睡觉。你好。他是谁。时间过得很快。"
    src = data_dir / "HighPriority" / "cat.txt"
    src.write_text(text, encoding="utf-8")

    sys.argv = ["analyzer.py", "--language", "zh", "--min-freq", "1",
                "--context-min", "0", "--target-coverage", "100"]
    analyzer.main()

    _assert_invariants(results, src, ChineseTokenizer(), "cat.txt")
