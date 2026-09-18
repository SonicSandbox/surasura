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


def test_plain_prose_is_unaffected(tmp_path):
    """The fix must not disturb books or transcripts, which already split correctly."""
    path = tmp_path / "book.txt"
    path.write_text("少年は静かに扉を開けた。廊下には誰もいなかった。秘密の部屋が待っていた。",
                    encoding="utf-8")
    out = _sentences(analyzer.extract_text(str(path), "ja"))
    assert out == ["少年は静かに扉を開けた。", "廊下には誰もいなかった。", "秘密の部屋が待っていた。"]
