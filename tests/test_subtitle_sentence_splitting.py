"""Subtitle sentences must end where the subtitle says they end.

Three faults compounded and produced 409-character "sentences" on a real episode:

1. Anime subs terminate with the HALFWIDTH ideographic full stop `｡` (U+FF61), which wasn't in the
   boundary set — so the subtitles' own sentence endings were invisible.
2. The boundary test compared the WHOLE token, but the tokenizer glues a terminator to an adjacent
   symbol (`➡。`, `｡。` arrive as single tokens), so even the terminator the analyzer itself added
   was swallowed.
3. `➡` marks "this line continues into the next cue", but was treated as ordinary text — so a `。`
   was appended after it, cementing a fragment instead of joining the two cues.

And the reason a fix to DEFAULT_SETTINGS alone wasn't enough: a saved settings.json overrides the
defaults wholesale, so anyone who had ever opened the app kept the broken boundary set forever.
"""

from unittest.mock import patch

import pytest

from app import analyzer
from app.settings_manager import DEFAULT_SETTINGS, load_settings


@pytest.fixture(autouse=True)
def _ja():
    analyzer.SANITIZE_JA = True


def _sentences(text):
    return [s for s, _t in analyzer.JapaneseTokenizer().tokenize_sentences(text)]


# --- boundaries ----------------------------------------------------------------------------------- #
def test_halfwidth_full_stop_is_a_boundary():
    """Anime subs use ｡ throughout (alongside halfwidth katakana). Without it nothing ever ends."""
    assert "｡" in DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["ja"]
    assert "｡" in DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["zh"]


def test_a_saved_settings_file_cannot_drop_a_required_boundary(tmp_path):
    """THE trap: an existing settings.json replaces the defaults, so shipping a new default alone
    would have fixed nothing for anyone who had already run the app."""
    stale = tmp_path / "settings.json"
    stale.write_text(
        '{"logic": {"sentence_boundaries": {"ja": "\\u3002\\uff01\\uff1f!?\\n"}}}',
        encoding="utf-8")
    with patch("app.settings_manager.get_user_file", return_value=str(stale)):
        merged = load_settings()
    assert "｡" in merged["logic"]["sentence_boundaries"]["ja"]


def test_the_full_width_full_stop_reaches_a_saved_settings_file(tmp_path):
    """．(U+FF0E) is the full stop of horizontal technical and official Japanese. Like ｡, it joins
    every saved set through the union, so no one has to edit settings.json; Chinese stays without it
    (an open question: Taiwan writes the name interpunct as ．, 瑪麗．居禮)."""
    assert "．" in DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["ja"]
    assert "．" not in DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["zh"]
    stale = tmp_path / "settings.json"
    stale.write_text(
        '{"logic": {"sentence_boundaries": {"ja": "\\u3002\\uff01\\uff1f!?\\n\\uff61"}}}',
        encoding="utf-8")
    with patch("app.settings_manager.get_user_file", return_value=str(stale)):
        merged = load_settings()
    assert "．" in merged["logic"]["sentence_boundaries"]["ja"]


def test_a_custom_boundary_is_preserved(tmp_path):
    """The union adds what's required; it must not throw away a user's own additions."""
    custom = tmp_path / "settings.json"
    custom.write_text('{"logic": {"sentence_boundaries": {"ja": "\\u3002\\u2026"}}}',
                      encoding="utf-8")
    with patch("app.settings_manager.get_user_file", return_value=str(custom)):
        merged = load_settings()
    ja = merged["logic"]["sentence_boundaries"]["ja"]
    assert "…" in ja, "the user's own boundary survives"
    assert "｡" in ja and "。" in ja, "the essentials are added"


def test_a_terminator_glued_to_a_symbol_still_splits():
    """Fugashi returns '➡。' as ONE token; comparing the whole surface let every cue end slip past."""
    out = _sentences("我々の最終目的は➡。藍染との決戦だ｡力を発揮できる者がいるなら➡。")
    assert len(out) >= 3, out
    assert all(len(s) < 30 for s in out), out


# --- cue assembly --------------------------------------------------------------------------------- #
def test_a_cue_already_ending_in_halfwidth_is_not_double_terminated():
    """'｡。' pairs were the analyzer appending a terminator to a cue that already had one."""
    assert analyzer.close_cue("お前に話がある｡") == "お前に話がある｡"
    assert analyzer.close_cue("反応です！") == "反応です！"
    assert analyzer.close_cue("限定解除は") == "限定解除は。", "a genuinely open cue is still closed"


def test_a_continuation_arrow_joins_the_next_cue():
    """'➡' means the sentence runs on. Dropping it and leaving the cue open lets the two halves
    become one grammatical sentence instead of a dangling fragment."""
    assert analyzer.close_cue("我々の最終目的は➡") == "我々の最終目的は"
    assert analyzer.close_cue("残された わずかな時間で ➡") == "残された わずかな時間で"


def test_a_netflix_dash_joins_the_next_cue():
    """Netflix's continuation marker is a dash, not an arrow. Measured on 4,200 real cues: 3.4% end
    in one, and every one of them was being closed with '。' mid-clause — cementing exactly the
    fragment the arrow handling exists to prevent. Both bars are in use: ― U+2015 and — U+2014."""
    assert analyzer.close_cue("あんたみたいな男を招き入れるなんて―") == "あんたみたいな男を招き入れるなんて"
    assert analyzer.close_cue("水の分量は—") == "水の分量は"
    assert analyzer.close_cue("入れてくれたら ―") == "入れてくれたら", "trailing space before the dash"


def test_the_dash_fragment_that_used_to_be_cemented():
    """The exact old output: '―' wasn't a terminator either, so a '。' was appended AFTER it."""
    assert analyzer.close_cue("招き入れるなんて―") != "招き入れるなんて―。"
    assert "―" not in analyzer.close_cue("招き入れるなんて―")


def test_repeated_trailing_dashes_are_all_stripped():
    """Netflix repeats a line across a shot change; both copies can carry the marker."""
    assert analyzer.close_cue("もらったのに――") == "もらったのに"
    assert analyzer.close_cue("もらったのに―➡") == "もらったのに", "mixed markers"


def test_a_cue_that_is_only_a_dash_produces_nothing():
    """Stripping the marker can empty the cue; an empty cue must be dropped, not become '。'."""
    assert analyzer.close_cue("―") == ""
    assert analyzer.close_cue(" — ") == ""


def test_a_leading_dash_is_not_a_continuation():
    """Only the END of a cue is consulted. A leading speech dash (—そうだね) is ordinary text, and
    the cue is closed normally — behaviour here is unchanged."""
    assert analyzer.close_cue("―そうだね") == "―そうだね。"
    assert analyzer.close_cue("そう―だね") == "そう―だね。", "a mid-line dash is untouched"


def test_a_nested_label_and_a_dash_on_the_same_cue():
    """The two fixes meet on one real line from the sample: `（一花(いちか)）えっと―`. The label must
    go whole and the dash must open the cue for joining."""
    cleaned = analyzer.clean_subtitle_text("（一花(いちか)）えっと―", "ja")
    assert cleaned == "えっと―"
    assert analyzer.close_cue(cleaned) == "えっと"


def test_close_cue_handles_empty_input():
    for junk in ("", "   ", None):
        assert analyzer.close_cue(junk) == ""


def test_the_broadcast_captions_arrow_joins_the_next_cue():
    """➨ is the broadcast captions' continuation arrow; unknown, it was kept and the cue
    closed mid-clause (…のは➨。 — 35 sentences of one episode)."""
    assert analyzer.close_cue("山の向こうで育ったのは➨") == "山の向こうで育ったのは"


def test_a_cue_ending_in_an_ellipsis_ends_without_gaining_a_full_stop():
    """A trailing … is the subtitle's own mark of speech trailing off: the cue has ended, on its timing,
    but … is no terminator in running text. Its end becomes a line break, so the sentence
    reads くっ… as the file does — it read くっ…。 (12,530 cues of the user's library)."""
    assert analyzer.close_cue("くっ…") == "くっ…\n"
    assert analyzer.close_cue("えっと‥") == "えっと‥\n"
    assert analyzer.close_cue("「そうか…」") == "「そうか…」\n", "looked for past the closing bracket"
    assert analyzer.close_cue("そうか…。") == "そうか…。", "a cue that already ends in 。 is untouched"


def test_a_cue_ending_in_a_comma_runs_on_into_the_next():
    """A comma is a pause inside a sentence (UAX #29 SContinue): the cue stays open, comma kept — it read
    今日は、。 and 我觉得，。"""
    assert analyzer.close_cue("今日は、") == "今日は、"
    assert analyzer.close_cue("我觉得，") == "我觉得，"


def test_a_terminator_behind_a_closing_bracket_is_found():
    """「行くぞ。」 has ended (UAX #29 SB9) and gained a second 。 (「行くぞ。」。); a bracket with no
    terminator behind it is closed as before."""
    assert analyzer.close_cue("「行くぞ。」") == "「行くぞ。」"
    assert analyzer.close_cue("《罰を与えられた》") == "《罰を与えられた》。"
    assert analyzer.close_cue("」") == "」。", "a bracket alone: debris, dropped by the tokenizer"


def test_punctuation_only_fragments_are_not_emitted():
    """'!?' splits into '!' and a lone '?'; a fragment with no Japanese is never a usable example."""
    assert all("限定解除" in s or "許可" in s for s in _sentences("限定解除は!? 許可済みです！")), \
        _sentences("限定解除は!? 許可済みです！")


# --- end to end ------------------------------------------------------------------------------------ #
# Real shape: halfwidth terminators, internal spacing, continuation arrows, a wrapped cue.
SRT = (
    "1\n00:01:37,856 --> 00:01:42,427\n"
    "残された わずかな時間で\n少しでも 己の力をあげるために➡\n\n"
    "2\n00:01:42,427 --> 00:01:45,263\n"
    "過酷な修行に 挑んでいた｡\n\n"
    "3\n00:19:50,000 --> 00:19:53,000\n"
    "そうだ 女｡ お前に話がある｡\n"
)


def test_a_real_subtitle_splits_into_readable_sentences(tmp_path):
    path = tmp_path / "ep01.srt"
    path.write_text(SRT, encoding="utf-8")
    out = _sentences(analyzer.extract_text(str(path), "ja"))

    assert len(out) >= 3, out
    assert max(len(s) for s in out) < 60, f"no runaway sentences: {out}"
    assert not any("➡" in s for s in out), "continuation arrows must not reach the learner"
    assert not any("｡。" in s for s in out), "no doubled terminators"

    # The arrowed cue joined with the one after it into a complete sentence.
    joined = [s for s in out if "己の力" in s]
    assert joined and "挑んでいた" in joined[0], joined


def test_the_reported_runaway_sentence_is_gone(tmp_path):
    """The shape the user reported: many cues concatenated into one unreadable block."""
    path = tmp_path / "long.srt"
    cues = []
    for i in range(12):
        cues.append(f"{i+1}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\n"
                    f"これは{i}番目の台詞です｡続きがあります➡\n")
    path.write_text("\n".join(cues), encoding="utf-8")

    out = _sentences(analyzer.extract_text(str(path), "ja"))
    assert len(out) >= 12, "each cue's own sentence must survive as its own sentence"
    assert max(len(s) for s in out) < 80, f"longest was {max(len(s) for s in out)}: {out}"


def test_ass_subtitles_get_the_same_treatment(tmp_path):
    path = tmp_path / "signs.ass"
    path.write_text(
        "[Events]\nFormat: Layer, Start, End, Style, Name, Text\n"
        "Dialogue: 0,0:00:12.30,0:00:15.00,Default,,そうだ 女｡ お前に話がある｡\n"
        "Dialogue: 0,0:00:16.00,0:00:18.00,Default,,我々の最終目的は➡\n"
        "Dialogue: 0,0:00:18.00,0:00:20.00,Default,,藍染との決戦だ｡\n",
        encoding="utf-8")
    out = _sentences(analyzer.extract_text(str(path), "ja"))
    assert not any("➡" in s for s in out), out
    assert max(len(s) for s in out) < 60, out


def test_a_netflix_shaped_subtitle_joins_across_dashes(tmp_path):
    """The Netflix dialect end to end: fullwidth speaker labels with furigana, and dashes carrying
    a clause across cue boundaries. Both halves must land as one sentence with no residue."""
    path = tmp_path / "netflix.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n"
        "（二乃(にの)）あんたみたいなえたいの知れない男を―\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\n"
        "招き入れるなんてどうかしてるわ。\n\n"
        "3\n00:00:05,000 --> 00:00:07,000\n"
        "（四葉(よつば)）水の分量は―\n\n"
        "4\n00:00:07,000 --> 00:00:09,000\n"
        "フィーリング！\n",
        encoding="utf-8")
    out = _sentences(analyzer.extract_text(str(path), "ja"))

    assert not any("―" in s for s in out), f"continuation dashes must not reach the learner: {out}"
    assert not any("）" in s or "（" in s for s in out), f"no label residue: {out}"

    joined = [s for s in out if "招き入れる" in s]
    assert joined and "えたいの知れない男" in joined[0], \
        f"the dashed cue must join the one after it: {out}"
    assert any("水の分量" in s and "フィーリング" in s for s in out), out


def test_ellipsis_cues_end_at_the_cue_and_read_as_written(tmp_path):
    """The file's own boundary (the cue's timing) ends the sentence; the text gains no 。."""
    path = tmp_path / "ep05.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nウウ…\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\n（健太）ハッ…\n\n"
        "3\n00:00:04,500 --> 00:00:06,000\n行くぞ\n",
        encoding="utf-8")
    assert _sentences(analyzer.extract_text(str(path), "ja")) == ["ウウ…", "ハッ…", "行くぞ。"]


# The two lines of one broadcast caption, written as two events with one start and end, then a caption of its
# own.
_ONE_CAPTION_ASS = (
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:01:10.00,0:01:13.50,Default,,0000,0000,0000,,今は様子を見るしかありませんから。\n"
    "Dialogue: 0,0:01:13.50,0:01:17.00,Default,,0000,0000,0000,,{\\pos(212,437)}《門番は城への侵入者を\n"
    "Dialogue: 0,0:01:13.50,0:01:17.00,Default,,0000,0000,0000,,{\\pos(252,497)}厳しく取り調べた》\n"
    "Dialogue: 0,0:01:17.00,0:01:19.50,Default,,0000,0000,0000,,次の話だ\n")


def test_ass_events_with_one_timing_are_one_caption(tmp_path):
    """Events on screen together are one caption, read like an .srt cue's two lines — each used to be
    closed with 。 mid-clause (…侵入者を。)."""
    path = tmp_path / "caption.ja.ass"
    path.write_text(_ONE_CAPTION_ASS, encoding="utf-8")
    assert _sentences(analyzer.extract_text(str(path), "ja")) == [
        "今は様子を見るしかありませんから。", "《門番は城への侵入者を厳しく取り調べた》。", "次の話だ。"]


def test_ass_events_in_another_format_order_still_group_by_timing(tmp_path):
    """The Format line names where Start and End are; an SSA file (Marked, …) reads the same way."""
    path = tmp_path / "old.ssa"
    path.write_text(
        "[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.50,Default,,0000,0000,0000,,限られたこの夏の間に\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.50,Default,,0000,0000,0000,,泳ぎを上達させる\n"
        "Dialogue: Marked=0,0:00:05.00,0:00:06.50,Default,,0000,0000,0000,,本当にそう思うの。\n",
        encoding="utf-8")
    assert _sentences(analyzer.extract_text(str(path), "ja")) == [
        "限られたこの夏の間に泳ぎを上達させる。", "本当にそう思うの。"]


def test_srt_cues_with_one_timing_stay_two_captions(tmp_path):
    """An .srt cue is its own caption: two cues with one timing are two captions shown at once — the
    repo's own sample writes two speakers talking together so. Read as one caption, 二乃's laugh would
    join 風太郎's line into one sentence."""
    path = tmp_path / "gotoubun.srt"
    path.write_text(
        "62\n00:04:20,343 --> 00:04:21,844 \n（風太郎）あれは てめえが薬を…\n\n"
        "63\n00:04:20,343 --> 00:04:21,844 \n（二乃）フフフフ…\n",
        encoding="utf-8")
    assert _sentences(analyzer.extract_text(str(path), "ja")) == ["あれはてめえが薬を…", "フフフフ…"]


def test_plain_prose_is_unaffected(tmp_path):
    """The fix must not disturb books or transcripts, which already split correctly."""
    path = tmp_path / "book.txt"
    path.write_text("少年は静かに扉を開けた。廊下には誰もいなかった。秘密の部屋が待っていた。",
                    encoding="utf-8")
    out = _sentences(analyzer.extract_text(str(path), "ja"))
    assert out == ["少年は静かに扉を開けた。", "廊下には誰もいなかった。", "秘密の部屋が待っていた。"]


# --- broadcast captions: a speaker by colour; a caption's lines -------------------------------------------------- #
# Japanese TV captions (字幕放送) tell speakers apart by colour: two colours on screen at once are two people speaking.
_BROADCAST_HEAD = (
    "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
    "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding\n"
    "Style: Default,Yu Gothic,46,&H00FFFFFF,&H000000FF,&H00000000,&H7F000000,1,0,0,0,100,100,4,0,1,2,2,1,0,0,0,1\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def _broadcast(tmp_path, *texts, language="ja"):
    """An .ass file whose events all share one timing, as a broadcast caption's lines do."""
    path = tmp_path / "broadcast.ja.ass"
    path.write_text(_BROADCAST_HEAD + "".join(
        f"Dialogue: 0,0:00:05.00,0:00:07.00,Default,,0000,0000,0000,,{text}\n" for text in texts), encoding="utf-8")
    return analyzer.extract_text(str(path), language)


def test_two_colours_on_screen_at_once_are_two_speakers(tmp_path):
    text = _broadcast(tmp_path, "{\\pos(332,437)\\c&H0000FFFF}え…お父様を？", "{\\pos(432,497)}うむ。")
    assert _sentences(text) == ["え…お父様を？", "うむ。"]


def test_one_speakers_lines_around_anothers_are_read_in_order(tmp_path):
    # White speaks two lines (right), yellow one (left) between them in the file: white's lines are one sentence.
    text = _broadcast(tmp_path, "{\\pos(500,436)}駅前で待っている", "{\\pos(140,496)\\c&H0000FFFF}早く行こう。",
                      "{\\pos(520,496)}友達がいるんだ。")
    assert _sentences(text) == ["駅前で待っている友達がいるんだ。", "早く行こう。"]


def test_a_captions_colour_is_its_first_visible_characters(tmp_path):
    # A converter colours a narrowed space now and then; one speaker, one sentence.
    text = _broadcast(tmp_path, "{\\pos(172,437)}その後{\\c&H0000FFFF\\fscx50}　{\\c&H00FFFFFF\\fscx100}会議を",
                      "{\\pos(172,497)}開きます。")
    assert _sentences(text) == ["その後　会議を開きます。"]


def test_an_ssa_style_colour_in_decimal_is_the_same_colour(tmp_path):
    # SSA writes a style's colour as a decimal number: 16777215 is white, as &H00FFFFFF is in an .ass override.
    path = tmp_path / "old.ssa"
    path.write_text(
        "[V4 Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour\n"
        "Style: Default,MS Gothic,28,16777215,65535,65535,0\n\n"
        "[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.50,Default,,0000,0000,0000,,放課後の市民プールで\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.50,Default,,0000,0000,0000,,{\\c&HFFFFFF&}泳ぎを覚えた。\n",
        encoding="utf-8")
    assert _sentences(analyzer.extract_text(str(path), "ja")) == ["放課後の市民プールで泳ぎを覚えた。"]


def test_a_japanese_cues_lines_keep_the_boundary_the_line_break_made(tmp_path):
    # The space between a cue's lines is a word boundary to the tagger; the sentence shown drops it.
    path = tmp_path / "two_lines.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,500\n行くぞ\nうん\n", encoding="utf-8")
    tokens = [t for _s, ts in analyzer.JapaneseTokenizer().tokenize_sentences(analyzer.extract_text(str(path), "ja"))
              for t in ts]
    assert _sentences(analyzer.extract_text(str(path), "ja")) == ["行くぞうん。"]
    assert "うん" in [lemma for lemma, _r, _s, _o in tokens]


@pytest.mark.parametrize("cue, sentence", [
    ("我明天\n要去北京", "我明天要去北京。"),       # between two Han characters a line break is nothing (CSS Text 3)
    ("我买了一件\nT恤", "我买了一件 T恤。"),        # beside a Latin letter it stays a space
])
def test_a_chinese_captions_lines_join_as_running_text(tmp_path, cue, sentence):
    path = tmp_path / "zh.srt"
    path.write_text(f"1\n00:00:01,000 --> 00:00:02,500\n{cue}\n", encoding="utf-8")
    text = analyzer.extract_text(str(path), "zh")
    assert [s for s, _t in analyzer.ChineseTokenizer().tokenize_sentences(text)] == [sentence]


def test_a_chinese_ass_line_break_joins_the_same_way(tmp_path):
    text = _broadcast(tmp_path, "我觉得\\N他不会来", language="zh")
    assert [s for s, _t in analyzer.ChineseTokenizer().tokenize_sentences(text)] == ["我觉得他不会来。"]
