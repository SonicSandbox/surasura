"""Speaker labels must be removed WHOLE — a nested one used to leave its closing bracket behind.

Netflix wraps a speaker's name in fullwidth parens, and when that name carries furigana the label
nests: `（風太郎(ふうたろう)）`. The old cleaner was a non-greedy `[\\(（].*?[\\)）]`, which stops at
the INNER `)`. It removed `（風太郎(ふうたろう)` and left an orphan `）` glued to the front of the
line — so the learner saw `）くっ…` in example sentences, and the same orphan went into every
export. A regex cannot count bracket depth; `_strip_bracketed` does.

The shapes below are taken from the repo's own sample subtitle
(`samples/ja/HighPriority/H_priority_sample_2.srt`, 五等分の花嫁), which carries six of these labels
— they are what the bug actually looked like in practice, not invented strings.

The one thing this fix must NOT do is get greedier. An unmatched OPENER keeps the text after it:
deleting to end-of-line would silently swallow real dialogue, and losing subtitle text is a far
worse failure than leaving one stray bracket.
"""

from app import analyzer


def _clean(text, language='ja'):
    return analyzer.clean_subtitle_text(text, language)


# --- the reported bug ----------------------------------------------------------------------------- #
def test_a_nested_speaker_label_leaves_nothing_behind():
    """THE bug: the lazy match stopped at the inner `)` and stranded the outer `）`."""
    assert _clean("（風太郎(ふうたろう)）くっ…") == "くっ…"
    assert _clean("（三玖(みく)）１人で何やってるの？") == "１人で何やってるの？"


def test_every_nested_label_in_the_real_sample_is_removed_cleanly():
    """All six shapes from the sample subtitle, each of which used to leave a `）`."""
    cases = [
        ("（風太郎(ふうたろう)）くっ…", "くっ…"),
        ("（三玖(みく)）１人で何やってるの？", "１人で何やってるの？"),
        ("（五月(いつき)）やっぱり来ましたか", "やっぱり来ましたか"),
        ("（四葉(よつば)）いらっしゃ～い", "いらっしゃ～い"),
        ("（二乃(にの)）んん…", "んん…"),
        ("（一花(いちか)）えっと―", "えっと―"),
    ]
    for raw, expected in cases:
        assert _clean(raw) == expected, raw


def test_no_closing_bracket_survives_any_nested_label():
    """The specific residue, asserted directly — this is what reached the learner."""
    for raw in ("（風太郎(ふうたろう)）くっ…", "（一花(いちか)）えっと―", "（二乃(にの)）んん…"):
        cleaned = _clean(raw)
        assert "）" not in cleaned and ")" not in cleaned, f"{raw!r} -> {cleaned!r}"


# --- nesting depth and bracket mixing ------------------------------------------------------------- #
def test_a_plain_unnested_label_still_goes():
    """The common case the old regex handled correctly must keep working."""
    assert _clean("（上杉）そうだね") == "そうだね"
    assert _clean("(上杉)そうだね") == "そうだね"


def test_three_levels_of_nesting():
    """Depth is counted, not guessed — one extra level used to strand two brackets."""
    assert analyzer._strip_bracketed("（あ（い（う）え）お）text") == "text"


def test_bracket_kinds_may_be_mixed():
    """Real subtitles mix fullwidth and ASCII freely; depth doesn't care which is which."""
    assert analyzer._strip_bracketed("（あ(い)う）残り") == "残り"
    assert analyzer._strip_bracketed("(あ（い）う)残り") == "残り"


def test_adjacent_and_trailing_groups():
    assert _clean("（一花）（二乃）そうだね") == "そうだね"
    assert _clean("そうだね（心の声）") == "そうだね"


# --- orphan closers (the residue) ----------------------------------------------------------------- #
def test_an_orphan_closing_bracket_is_dropped_wherever_it_sits():
    """A lone `）` is never content — it is the artifact this fix exists to prevent."""
    assert _clean("）くっ…") == "くっ…"
    assert analyzer._strip_bracketed("そう）だね") == "そうだね"
    assert analyzer._strip_bracketed("））））そうだね") == "そうだね"


# --- the conservative half: unmatched openers ----------------------------------------------------- #
def test_an_unmatched_opener_keeps_the_dialogue_after_it():
    """Deliberately NOT greedy. A truncated cue like `（風太郎 何やってるの` must keep its dialogue —
    deleting to end-of-line would silently lose real subtitle text, which is a worse failure than
    leaving one stray bracket. The old regex also left this alone, so behaviour is unchanged here."""
    assert analyzer._strip_bracketed("（風太郎 何やってるの") == "（風太郎 何やってるの"
    assert analyzer._strip_bracketed("そうだね（続く") == "そうだね（続く"


def test_an_inner_group_still_closes_under_an_unmatched_opener():
    """Depth tracking must not be defeated by an outer bracket that never closes."""
    assert analyzer._strip_bracketed("（風太郎 (ふうたろう) 何やってるの") == "（風太郎  何やってるの"


# --- empty states --------------------------------------------------------------------------------- #
def test_empty_and_bracket_only_inputs():
    assert analyzer._strip_bracketed("") == ""
    assert analyzer._strip_bracketed("（）") == ""
    assert analyzer._strip_bracketed("）") == ""
    assert _clean("（風太郎(ふうたろう)）") == "", "a label-only cue collapses to nothing"
    assert _clean("   ") == ""


def test_a_label_only_cue_is_not_emitted_end_to_end(tmp_path):
    """A cue that is nothing but a speaker label must vanish, not become an empty sentence."""
    path = tmp_path / "labels.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n（風太郎(ふうたろう)）\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\n（三玖(みく)）本当にそう思うの。\n",
        encoding="utf-8")
    text = analyzer.extract_text(str(path), "ja")
    assert "）" not in text and "(" not in text, text
    assert "本当にそう思うの" in text


# --- interaction with the other cleaners ---------------------------------------------------------- #
def test_ass_override_tags_are_removed_before_bracket_counting():
    """`{\\pos(10,20)}` contains parens. The brace strip runs first, so those never reach the depth
    counter — if it ever stopped running, an unbalanced count would eat the line."""
    assert _clean("{\\pos(10,20)}（三玖(みく)）そうだね") == "そうだね"


def test_prose_without_brackets_is_untouched():
    """The fix must not disturb books or transcripts, which have no speaker labels at all."""
    line = "少年は静かに扉を開けた。廊下には誰もいなかった。"
    assert _clean(line) == line


def test_chinese_cues_get_the_same_treatment():
    """Language isolation is about the ASCII/noise rules, not bracket structure — a Chinese subtitle
    carries the same labels and must not keep an orphan either."""
    assert _clean("（李明(lǐ míng)）你在做什么？", "zh") == "你在做什么？"


# --- end to end ------------------------------------------------------------------------------------ #
def test_nested_labels_never_reach_a_sentence(tmp_path):
    """The learner-facing guarantee: no bracket residue survives into an example sentence."""
    path = tmp_path / "netflix.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n（風太郎(ふうたろう)）くっ…\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\n（四葉(よつば)）いらっしゃ～い上杉さん！\n\n"
        "3\n00:00:05,000 --> 00:00:07,000\n（五月(いつき)）やっぱり来ましたか。\n",
        encoding="utf-8")
    sentences = [s for s, _t in
                 analyzer.JapaneseTokenizer().tokenize_sentences(analyzer.extract_text(str(path), "ja"))]
    assert sentences, "the cues must still produce sentences"
    assert not any("）" in s or ")" in s for s in sentences), sentences
    assert not any("（" in s or "(" in s for s in sentences), sentences
    assert any("いらっしゃ" in s for s in sentences), sentences


def test_crlf_and_bom_subtitles_are_handled(tmp_path):
    """Windows-authored subs arrive CRLF, sometimes with a BOM; bracket stripping is per-line and
    must not be defeated by either."""
    path = tmp_path / "crlf.srt"
    path.write_bytes(
        "﻿1\r\n00:00:01,000 --> 00:00:03,000\r\n（三玖(みく)）本当にそう思うの。\r\n"
        .encode("utf-8"))
    text = analyzer.extract_text(str(path), "ja")
    assert "）" not in text, repr(text)
    assert "本当にそう思うの" in text
