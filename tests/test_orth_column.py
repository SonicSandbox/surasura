"""D4 — the `Orth` column: the spelling a word is actually WRITTEN in.

UniDic's `lemma` is a lexeme id, not a name. It deliberately merges every spelling of a word into
one canonical headword, which is what makes it correct for counting (いう + 言う + 言える are one
verb) and wrong as a label: the headword is frequently a form nobody writes (有る for ある), and
proper nouns get a *katakana* lemma (スドウ for 須藤, トットリ for 鳥取).

So the tokenizer now carries `orthBase` alongside, and the analyzer emits the commonest one per
word as `Orth`. `Word` remains the identity — nothing is keyed on `Orth`.

Measured on the live library when this was written: 23.7% of listed words that appear in the user's
own content were being named with a spelling that content never uses.
"""
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analyzer


# --------------------------------------------------------------------------- #
# The tokenizer contract
# --------------------------------------------------------------------------- #

def test_japanese_tokens_carry_four_values():
    """Every consumer unpacks this tuple positionally, so its width is a contract. A 3-wide blob
    left in the SQLite cache by an older build would raise here rather than silently mis-bind —
    which is why SCHEMA_VERSION was bumped alongside."""
    tok = analyzer.JapaneseTokenizer()
    tokens = [t for _s, toks in tok.tokenize_sentences("猫が魚を食べた。") for t in toks]
    assert tokens, "real Japanese should produce tokens"
    for t in tokens:
        assert len(t) == 4, f"expected (lemma, reading, surface, orth), got {t!r}"


def test_the_orth_is_the_spelling_the_text_used_not_the_canonical_lemma():
    """The case that started this: the card says 引きずる, the report said 引き摺る, and the two
    never matched. Both values are now present and distinct."""
    tok = analyzer.JapaneseTokenizer()
    found = {}
    for _s, toks in tok.tokenize_sentences("初めてなんか引きずってしまった恋だった。"):
        for lemma, _reading, _surface, orth in toks:
            found[lemma] = orth
    assert found["引き摺る"] == "引きずる"
    assert found["仕舞う"] == "しまう"


def test_proper_nouns_keep_their_kanji_instead_of_a_katakana_lemma():
    """UniDic lemmatizes proper nouns to their READING, so a report ordered by lemma tells the user
    to learn スドウ while their show writes 須藤. This is the most visible form of the bug."""
    tok = analyzer.JapaneseTokenizer()
    found = {}
    for _s, toks in tok.tokenize_sentences("須藤は鳥取へ行く。"):
        for lemma, _reading, _surface, orth in toks:
            found[lemma] = orth
    assert found["スドウ"] == "須藤"
    assert found["トットリ"] == "鳥取"


def test_chinese_tokens_are_the_same_width():
    """Jieba has no lemma/orth distinction — the surface IS the dictionary form — but the tuple
    shape has to match or every shared consumer needs a per-language branch."""
    tok = analyzer.ChineseTokenizer()
    tokens = [t for _s, toks in tok.tokenize_sentences("我喜欢学习中文。") for t in toks]
    assert tokens
    for lemma, reading, surface, orth in tokens:
        assert (lemma, reading, orth) == (surface, "", surface)


# --------------------------------------------------------------------------- #
# Choosing which spelling to show
# --------------------------------------------------------------------------- #

def test_the_commonest_spelling_wins():
    """Counted, not last-wins: one stray spelling in one file must not rename the word. Real
    distribution measured over 60 files of the live library."""
    assert analyzer._display_orth("言う", Counter({"いう": 3019, "言う": 1010, "言える": 38})) == "いう"


def test_a_word_with_no_recorded_spelling_falls_back_to_the_lemma():
    """Nothing may return blank — an empty `Orth` would render as a nameless row."""
    assert analyzer._display_orth("有る", Counter()) == "有る"
    assert analyzer._display_orth("有る", None) == "有る"


def test_blank_orths_are_never_chosen():
    """An empty orthBase is a tokenizer artifact, not a spelling. Preferring it would blank a name
    that has a perfectly good alternative."""
    assert analyzer._display_orth("食べる", Counter({"": 99, "食べる": 2})) == "食べる"


def test_the_lemma_still_merges_spellings_that_orth_would_split():
    """The reason `Word` is NOT switched to orthBase. Keying on the spelling would split this one
    verb into three entries holding a third of the frequency each, and a word sitting just above a
    density band's floor would drop out of the list entirely."""
    tok = analyzer.JapaneseTokenizer()
    lemmas = set()
    for text in ("そう言う人もいる。", "そういう人もいる。"):
        for _s, toks in tok.tokenize_sentences(text):
            for lemma, _r, _s2, orth in toks:
                if orth in ("言う", "いう"):
                    lemmas.add(lemma)
    assert lemmas == {"言う"}, "both spellings must collapse to one lemma for counting"


# --------------------------------------------------------------------------- #
# The column, end to end
# --------------------------------------------------------------------------- #

def test_orth_column_is_present_and_never_blank(tmp_path, ja_resources_dir, monkeypatch):
    """The golden-master snapshot proves the other 16 columns are untouched; this proves the new
    one is populated for every row, since a blank would reach the report as a nameless word."""
    import pandas as pd
    expected = os.path.join(ja_resources_dir, "expected_output.csv")
    df = pd.read_csv(expected)
    assert "Orth" in df.columns
    assert df["Orth"].notna().all(), "every row needs a spelling"
    assert (df["Orth"].astype(str).str.strip() != "").all()


def test_orth_is_not_named_like_an_example_sentence():
    """Both report templates collect example sentences with startsWith('Context '). A column named
    'Context ...' that is not a sentence renders as a bogus example — the trap that named `Src N`
    and `Modality` what they are."""
    assert not "Orth".startswith("Context ")


def test_engine_revision_was_bumped_for_this_change():
    """Adding a column changes what a run OUTPUTS for unchanged inputs. Without a bump the stored
    run-signature still matches and the analyzer serves the OLD report, with no Orth column at all."""
    assert analyzer.ENGINE_REVISION >= 8


def test_both_output_lists_name_a_word_the_same_way(tmp_path):
    """The priority list and the progressive list are read by the same consumers — the exporters,
    and junban's two ordering modes. A word named 須藤 in one and スドウ in the other would match in
    one place and silently fail in the other, which is the hardest kind of bug to see.
    """
    import csv
    import sys
    from unittest.mock import patch

    root = tmp_path
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (root / "User Files" / "ja").mkdir(parents=True)
    results = root / "results"
    results.mkdir()
    # Real text whose lemma and orthBase disagree: 引きずって -> lemma 引き摺る, orthBase 引きずる.
    (high / "a.txt").write_text(
        "初めてなんか引きずってしまった恋だった。\n"
        "彼はまた引きずっている。\n"
        "須藤は鳥取へ行く。\n"
        "須藤がまた来た。\n", encoding="utf-8")

    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch.object(sys, "argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()

    def by_word(path):
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return {r["Word"]: r.get("Orth", "") for r in csv.DictReader(handle)}

    priority = by_word(results / "priority_learning_list.csv")
    progressive = by_word(results / "progressive_learning_list.csv")
    assert priority, "the sample should produce a priority list"
    assert progressive, "the sample should produce a progressive list"

    shared = set(priority) & set(progressive)
    assert shared, "the two lists should overlap"
    for word in shared:
        assert priority[word] == progressive[word], (
            f"{word} is named {priority[word]!r} in the priority list but "
            f"{progressive[word]!r} in the progressive list")
    # And the column is doing real work here, not just present-and-equal.
    assert any(priority[w] != w for w in shared), "this fixture must contain a lemma/orth mismatch"
