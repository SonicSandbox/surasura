"""WP-Z3: a whole Chinese analysis read in one script — content, known words, lists, frequency lists.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md (§5.6, §7). The library here is the
realistic mixed case the setting exists for: the same sentences once in Simplified (a YouTube
transcript, say) and once in Traditional, with the learner's known words and ignore list written in
Traditional. As-is, every shared word is counted twice under two spellings and the Traditional known
word never matches the Simplified content. Under `s` or `t` each word is ONE row with the combined
count, and known/ignored words drop out whichever script the content used.

Also pinned: nothing on disk is rewritten (I1), a frequency list merges two spellings onto the
commoner rank, and the run signature moves when the script does (or Generate would reopen the
report from the other script).
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, zh_script

SIMPLIFIED = ("我们每天都在学习新的东西。\n"
              "这个问题和经济发展的关系很重要。\n"
              "学习的时候要保持耐心。\n")
TRADITIONAL = ("我們每天都在學習新的東西。\n"
               "這個問題和經濟發展的關係很重要。\n"
               "學習的時候要保持耐心。\n")


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "zh"
    uf.mkdir(parents=True)
    high = tmp_path / "data" / "zh" / "HighPriority"
    high.mkdir(parents=True)
    results = tmp_path / "results"
    results.mkdir()
    (high / "transcript_simplified.txt").write_text(SIMPLIFIED, encoding="utf-8")
    (high / "novel_traditional.txt").write_text(TRADITIONAL, encoding="utf-8")
    # Written in Traditional, as a Traditional learner's Anki deck would be.
    (uf / "KnownWord.json").write_text(json.dumps(
        {"words": [{"dictForm": "問題", "knownStatus": "KNOWN"}]}, ensure_ascii=False), encoding="utf-8")
    (uf / "IgnoreList.txt").write_text("# my ignores\n東西\n", encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "uf": uf, "high": high, "results": results,
            "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env, *extra):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "zh", "--min-freq", "1", *extra]):
        analyzer.main()
    df = pd.read_csv(csv)
    return dict(zip(df["Word"], df["Occurrences"]))


def test_as_is_counts_each_spelling_separately(env):
    """The problem, pinned so the fix below means something: two rows for one word, and the
    Traditional known word leaves its Simplified twin on the list."""
    counts = _run(env)
    assert counts.get("学习") == 2 and counts.get("學習") == 2
    assert "问题" in counts and "問題" not in counts


@pytest.mark.parametrize("script, learn, known, ignored", [
    ("s", "学习", "问题", "东西"),
    ("t", "學習", "問題", "東西"),
])
def test_one_script_merges_the_counts_and_applies_known_and_ignored_words(env, script, learn,
                                                                          known, ignored):
    counts = _run(env, f"--zh-script={script}")
    assert counts.get(learn) == 4, "both files' occurrences must land on one row"
    assert known not in counts, "a Traditional known word must match content in either script"
    assert ignored not in counts, "a Traditional ignore-list entry must match too"
    for word in counts:
        assert zh_script.convert(word, script) == word, f"{word!r} is not in the chosen script"


def test_nothing_on_disk_is_rewritten(env):
    """I1: conversion happens on read. Content, known words and lists stay byte-identical."""
    files = [env["high"] / "transcript_simplified.txt", env["high"] / "novel_traditional.txt",
             env["uf"] / "KnownWord.json", env["uf"] / "IgnoreList.txt"]
    before = {p: p.read_bytes() for p in files}
    _run(env, "--zh-script=t")
    _run(env, "--zh-script=s")
    assert {p: p.read_bytes() for p in files} == before


def test_the_run_signature_moves_with_the_script(env):
    """Generate compares this to decide whether to reopen the last report. Without the script in it,
    switching to Traditional would reopen the Simplified report."""
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]):
        sigs = {s: analyzer.compute_run_signature(
                    "zh", [], analyzer.parse_analysis_args(["--language=zh", f"--zh-script={s}"]))
                for s in ("asis", "s", "t")}
        # Japanese ignores the setting entirely: its signature must not move.
        ja = {s: analyzer.compute_run_signature(
                  "ja", [], analyzer.parse_analysis_args(["--language=ja", f"--zh-script={s}"]))
              for s in ("asis", "t")}
    assert len(set(sigs.values())) == 3 and None not in sigs.values()
    assert ja["asis"] == ja["t"]


# ---- the loaders, directly -------------------------------------------------------------------- #

def test_simple_list_reads_entries_in_the_chosen_script(tmp_path):
    path = tmp_path / "Blacklist.txt"
    path.write_text("# comment\n東西\n头发\n\n", encoding="utf-8")
    assert analyzer.load_simple_list(str(path)) == {"東西", "头发"}          # as-is: unchanged
    assert analyzer.load_simple_list(str(path), "s") == {"东西", "头发"}
    assert analyzer.load_simple_list(str(path), "t") == {"東西", "頭髮"}


def test_frequency_list_keys_convert_and_merged_spellings_keep_the_commoner_rank(tmp_path):
    """乾 (dry) and 幹 (do) are both 干 in Simplified. One word now, as common as its commonest
    spelling: rank 5, not the rank of whichever row happened to come last."""
    path = tmp_path / "frequency_list_zh_News.csv"
    path.write_text("Word,Rank\n學習,1\n幹,5\n乾,10\n", encoding="utf-8")
    assert analyzer.load_yomitan_frequency_list(str(path)) == {"學習": 1, "幹": 5, "乾": 10}
    assert analyzer.load_yomitan_frequency_list(str(path), "s") == {"学习": 1, "干": 5}


def test_known_words_follow_the_tokenizer_script(tmp_path):
    """load_known_words takes the script from the tokenizer, so every caller that builds a
    script-aware tokenizer (analyzer, indexer, YouTube preview) converts without another argument."""
    path = tmp_path / "KnownWord.json"
    path.write_text(json.dumps({"words": [{"dictForm": "學習", "knownStatus": "KNOWN"},
                                          {"dictForm": "头发", "hasCard": 1}]},
                               ensure_ascii=False), encoding="utf-8")
    _tuples, lemmas = analyzer.load_known_words(str(path), analyzer.ChineseTokenizer(script="s"))
    assert {"学习", "头发"} <= lemmas and "學習" not in lemmas
    _tuples, lemmas = analyzer.load_known_words(str(path), analyzer.ChineseTokenizer(script="t"))
    assert {"學習", "頭髮"} <= lemmas and "头发" not in lemmas
    _tuples, lemmas = analyzer.load_known_words(str(path), analyzer.ChineseTokenizer())
    assert {"學習", "头发"} <= lemmas                                            # as-is
