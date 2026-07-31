"""Scroll-to-text deep links must land on the sentence, or not be offered at all.

The sentence in the report is NOT the sentence in the file. The tokenizer drops every space when it
rebuilds a sentence, so an anime subtitle line written as

    そうだ 女｡ お前に話がある｡

is stored as `そうだ女｡お前に話がある。`. The analyzer also appends `。` to cues without sentence
punctuation and strips Latin characters. Any anchor guessed from the stored text therefore spans
gaps the file doesn't have — and a short guess can land on the WRONG line.

So the generator verifies candidate snippets against the real file and only emits one that occurs
exactly once. These tests use real subtitle/prose text and drive the REAL analyzer, so they cover
the whole chain rather than the helper in isolation.
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer
from app.static_html_generator import AnchorFinder

# Spacing and halfwidth '｡' copied from a real anime subtitle — this is the reported failing shape.
SRT = (
    "1\n00:19:50,000 --> 00:19:53,000\n"
    "そうだ 女｡ お前に話がある｡\n\n"
    "2\n00:20:00,724 --> 00:20:05,930\n"
    "逃げて 逃げてください！\nし しかし｡\n\n"
    "3\n00:20:05,930 --> 00:20:07,965\n"
    "そのために\n拘流と拘突が存在したんだ\n"
)
# Prose has no internal spacing, which is why plain .txt worked from the start.
TXT = "少年は静かに扉を開けた。廊下には誰もいなかった。秘密の部屋が待っていた。"


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "ja" / "HighPriority"; high.mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (high / "ep01.srt").write_text(SRT, encoding="utf-8")
    (high / "book.txt").write_text(TXT, encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "results": results, "high": high, "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(csv)


def _sentence_containing(df, needle):
    for ctx in df["Context 1"].dropna():
        if needle in str(ctx):
            return str(ctx)
    raise AssertionError(f"no example sentence containing {needle!r} was produced")


# --- the loss that makes guessing impossible ---------------------------------------------------- #
def test_spaces_inside_a_subtitle_line_do_not_survive(env):
    """Root cause. The file separates words with spaces; the stored sentence has none, and nothing
    records where they were."""
    df = _run(env)
    sentence = _sentence_containing(df, "お前に話")
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")

    assert "そうだ 女｡ お前に話がある｡" in raw, "the file keeps its spacing"
    assert " " not in sentence, f"no whitespace survives: {sentence!r}"
    assert sentence not in raw, "so the stored sentence is not in the file"


def test_a_guessed_anchor_would_miss(env):
    """Proves verification is necessary, not decorative: a plausible guess from the stored text is
    absent from the file, because it spans a gap."""
    df = _run(env)
    sentence = _sentence_containing(df, "お前に話")
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")

    guess = sentence.rstrip("。")[:10]
    assert guess not in raw, f"{guess!r} unexpectedly matched — the guessing bug is back"


# --- verified anchors ---------------------------------------------------------------------------- #
def test_verified_anchor_is_found_for_a_spaced_subtitle_line(env):
    """The reported case now produces a real anchor — a run that survives inside one line."""
    df = _run(env)
    sentence = _sentence_containing(df, "お前に話")
    path = str(env["high"] / "ep01.srt")
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")

    anchor = AnchorFinder().anchor(path, sentence)
    assert anchor, f"no anchor found for {sentence!r}"
    assert anchor in raw, "the anchor must exist verbatim in the file"
    # The anchor may carry the file's spacing, which the sentence lost — compare without it.
    assert "".join(anchor.split()) in "".join(sentence.split()), \
        "the anchor must be a genuine piece of this sentence, not some other line"


def test_a_sentence_spanning_many_cues_still_anchors(env):
    """The analyzer appends '。' at every cue boundary, so one 'sentence' can cover a dozen spaced
    cues. Splitting on '。' recovers the per-cue chunks, and the longest usable one becomes the
    anchor."""
    df = _run(env)
    path = str(env["high"] / "ep01.srt")
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")

    multi = [s for s in df["Context 1"].dropna().astype(str)
             if s.count("。") >= 2 and "ep01" in str(df.loc[df["Context 1"] == s, "Src 1"].iloc[0])]
    if not multi:
        pytest.skip("this fixture produced no multi-cue sentence")
    anchor = AnchorFinder().anchor(path, multi[0])
    assert anchor and raw.count(anchor) == 1


def test_anchor_is_unique_so_it_cannot_scroll_to_the_wrong_line(env):
    """A snippet occurring twice would send Chrome to the first one. Only unique anchors ship."""
    df = _run(env)
    finder = AnchorFinder()
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")
    path = str(env["high"] / "ep01.srt")

    checked = 0
    for _, row in df.iterrows():
        if str(row.get("Src 1", "")).endswith("ep01.srt") and pd.notna(row.get("Context 1")):
            anchor = finder.anchor(path, row["Context 1"])
            if anchor:
                assert raw.count(anchor) == 1, f"{anchor!r} is ambiguous"
                checked += 1
    assert checked, "no subtitle anchors were produced at all"


def test_plain_prose_still_anchors(env):
    """The case that already worked must keep working."""
    df = _run(env)
    path = str(env["high"] / "book.txt")
    raw = (env["high"] / "book.txt").read_text(encoding="utf-8")

    checked = 0
    for _, row in df.iterrows():
        if str(row.get("Src 1", "")).endswith("book.txt") and pd.notna(row.get("Context 1")):
            anchor = finder_anchor = AnchorFinder().anchor(path, row["Context 1"])
            assert anchor, f"prose should always anchor: {row['Context 1']!r}"
            assert finder_anchor in raw
            checked += 1
    assert checked, "no prose sentences were checked"


# --- AnchorFinder in isolation -------------------------------------------------------------------- #
def test_no_anchor_rather_than_a_wrong_one(tmp_path):
    """A sentence that simply isn't in the file yields nothing — the badge then offers no link
    instead of one that misses."""
    f = tmp_path / "a.txt"
    f.write_text("まったく関係のない文章がここにあります。", encoding="utf-8")
    assert AnchorFinder().anchor(str(f), "存在しない別の文です。") == ""


def test_ambiguous_text_is_rejected(tmp_path):
    """A repeated line can't produce a trustworthy anchor."""
    f = tmp_path / "b.txt"
    f.write_text("同じ文が続きます。\n" * 5, encoding="utf-8")
    assert AnchorFinder().anchor(str(f), "同じ文が続きます。") == ""


def test_missing_file_and_junk_input_are_safe(tmp_path):
    finder = AnchorFinder()
    assert finder.anchor(str(tmp_path / "gone.txt"), "何かの文です") == ""
    f = tmp_path / "c.txt"
    f.write_text("少年は静かに扉を開けた。", encoding="utf-8")
    for junk in ("", "   ", None, "短い"):
        assert finder.anchor(str(f), junk) == "", f"{junk!r} should yield no anchor"


def test_files_are_read_once(tmp_path):
    """The pass runs over every sentence, so re-reading per sentence would be the whole cost."""
    f = tmp_path / "d.txt"
    f.write_text("少年は静かに扉を開けた。廊下には誰もいなかった。", encoding="utf-8")
    finder = AnchorFinder()

    real_open = open
    calls = {"n": 0}

    def counting_open(*a, **kw):
        calls["n"] += 1
        return real_open(*a, **kw)

    with patch("builtins.open", counting_open):
        for _ in range(5):
            finder.anchor(str(f), "少年は静かに扉を開けた。")
    assert calls["n"] == 1, f"file was read {calls['n']} times"
