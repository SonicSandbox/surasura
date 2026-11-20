"""A transcript's groups in parentheses are no speech, as a subtitle's are (SUB-PARENS, widened 3.0.17).

A Netflix or Disney+ episode reaches the library as a transcript — the YouTube downloader's header, then a cue a line
(app/online_receiver.py) — and Netflix's Japanese subtitles name the speaker at the start of about half their lines,
（平野）, write a reading after a name, （風早(かぜはや)）, and describe sounds, （足音）. A subtitle file drops every such
group (analyzer.clean_subtitle_text); a transcript kept them all, so the speaker's name counted once for every line
they say and 女子生徒, 足音, 笑い声 became words of the list. Measured on a 25-episode Netflix season: 88 rows of
labels and sound notes (830 uses) and about 3,000 uses of the speakers' names, gone once the groups go.

A YouTube transcript is written as ONE line (its cues joined with spaces), so a group here is short and one level deep
at most (`analyzer._TRANSCRIPT_GROUP_RE`): a stray bracket never takes the text up to some later one. The line player
looks a sentence up in the transcript without the groups too (cues._transcript_removed), so a line whose label sat
in the middle still plays from its second.

The lines below are written for these tests in the shape Netflix's subtitles take (no show's own text).
"""
import json

import pytest

from app import analyzer
from app.path_utils import SIDECAR_SUFFIX
from app.static_html_generator import AnchorFinder


@pytest.fixture(autouse=True)
def _sanitized():
    analyzer.SANITIZE_JA = True         # as every Japanese run sets it (conftest restores the global)


def _transcript(body, title="第3話 放課後", channel="雲の上の郵便屋さん |  | ", site="netflix"):
    return (f"{title}\n{channel}\nCaptions: ja (manual)\nhttps://www.{site}.com/watch/81234567\n\n" + "-" * 60
            + "\n" + body)


NETFLIX_BODY = "\n".join((
    "♪～",
    "（女子生徒）ねえ 聞いた？",
    "（女子生徒）転校生が来るんだって",
    "（佐倉(さくら)）おはよう",
    "（チャイム）",
    "（遠野）あっ 佐倉さん（佐倉）えっ",
    "（足音）（戸が開く音）",
    "（佐倉）今日は 早いね",
    "誰も 来ないと思ってた",
))


def _read(tmp_path, text, name="雲の上の郵便屋さん S01E03 放課後 [netflix-81234567].txt", language="ja"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return analyzer.extract_text(str(path), language)


def _surfaces(text):
    """Every counted word of `text` as written (the tokenizer's (lemma, reading, surface, orth) tuples)."""
    return [str(token[2]) for _sentence, tokens in analyzer.JapaneseTokenizer().tokenize_sentences(text) for token in tokens]


# --- the reader ------------------------------------------------------------------------------------------------ #
def test_a_netflix_transcript_keeps_its_speech_and_drops_labels_readings_and_sounds(tmp_path):
    """Every group goes — a label at a line's start, a label with its reading nested inside, a label in the middle
    of a line (two people talking), a sound alone on its line and two side by side — and every word said stays."""
    text = _read(tmp_path, _transcript(NETFLIX_BODY))
    for gone in ("女子生徒", "佐倉(さくら)", "さくら", "チャイム", "遠野", "足音", "戸が開く音", "（", "）", "(", ")"):
        assert gone not in text, gone
    for said in ("ねえ 聞いた？", "転校生が来るんだって", "おはよう", "あっ 佐倉さんえっ", "今日は 早いね", "誰も 来ないと思ってた"):
        assert said in text, said
    assert "佐倉さん" in text, "a name SAID in a line is speech: only the label goes"


def test_the_label_and_sound_words_no_longer_count(tmp_path):
    """What the change is for: 女子生徒, 足音 and the speaker's name in the label were counted once per line."""
    words = _surfaces(_read(tmp_path, _transcript(NETFLIX_BODY)))
    assert not [w for w in words if "女子" in w or "生徒" in w or "足音" in w or "チャイム" in w or "遠野" in w], words
    assert sum("佐倉" in w for w in words) == 1, "the one 佐倉 left is the one said (佐倉さん), never the labels'"
    assert any("転校" in w for w in words) and "早い" in words


def test_a_chinese_transcript_drops_its_groups_too(tmp_path):
    """The rule is the subtitle's, for every language: a Chinese caption's speaker （小明） and sound （笑声） go."""
    body = "（小明）你今天怎么这么早？\n（笑声）\n（小红）因为我想先复习一下(翻书声)\n明天就考试了"
    text = _read(tmp_path, _transcript(body, title="第五集", channel="校园日记 |  | "), name="校园日记 [netflix-81234999].txt",
                 language="zh")
    for gone in ("小明", "小红", "笑声", "翻书声", "（", "("):
        assert gone not in text, gone
    for said in ("你今天怎么这么早？", "因为我想先复习一下", "明天就考试了"):
        assert said in text, said


def test_a_youtube_transcript_on_one_line_never_loses_text_to_a_stray_bracket(tmp_path):
    """The downloader joins a video's cues with spaces: the transcript is one line. A group closes within a short
    reach, or it is text — an opener left open by one cue never takes the speech up to a closer many cues later; a
    label with its reading inside (one level) still goes whole; a short aside closed in the same breath goes."""
    said = " ".join(["今日は市場を歩きます", "（笑）", "このお店は 三代目なんです（店主の田中(たなか)さん）",
                     "えっと（ 何て言うんだっけ"] + ["ここの魚は毎朝とれたものです"] * 6 + ["それでは）また来週"])
    text = _read(tmp_path, _transcript(said, title="市場さんぽ", channel="さんぽチャンネル | 2026-03-01 | 12:04",
                                       site="youtube"), name="市場さんぽ [abcdefghijk].txt")
    assert "笑" not in text and "店主" not in text and "たなか" not in text
    assert text.count("ここの魚は毎朝とれたものです") == 6, "nothing between a stray （ and a far ） is lost"
    assert "何て言うんだっけ" in text and "また来週" in text


def test_a_book_keeps_its_groups_as_before(tmp_path):
    """Only a transcript is captions: a book's aside in parentheses stays text, its reading follows paren_readings."""
    text = _read(tmp_path, "自分（モロナイ）は言った。東京(とうきょう)に着いた。\n", name="book.txt")
    assert text == "自分（モロナイ）は言った。東京に着いた。\n"


# --- the line player ------------------------------------------------------------------------------------------- #
def test_a_line_whose_label_sat_in_the_middle_still_plays_from_its_second(tmp_path):
    """The transcript's sidecar lines hold the labels; the sentence a Generate keeps doesn't. The line player looks the
    sentence up without the groups (as it does without a sound cue), so it still finds the line it was said in."""
    lines = [["（女子生徒）ねえ 聞いた？", 3], ["（遠野）あっ 佐倉さん（佐倉）えっ 何？", 11], ["（佐倉）今日は 早いね", 17]]
    txt = tmp_path / "雲の上の郵便屋さん S01E03 [netflix-81234567].txt"
    txt.write_text(_transcript("\n".join(line for line, _sec in lines)), encoding="utf-8")
    (tmp_path / ("雲の上の郵便屋さん S01E03 [netflix-81234567]" + SIDECAR_SUFFIX)).write_text(
        json.dumps({"video_id": "81234567", "cues": lines}, ensure_ascii=False), encoding="utf-8")
    text = analyzer.extract_text(str(txt), "ja")
    sentences = [s for s, _tokens in analyzer.JapaneseTokenizer().tokenize_sentences(text)]
    sentence = next(s for s in sentences if "佐倉さん" in s)
    assert "遠野" not in sentence and "えっ" in sentence, "the label in the middle is out of the sentence"
    finder = AnchorFinder()
    assert finder.line(str(txt), sentence)[0] == 11
    assert finder.line(str(txt), next(s for s in sentences if "早い" in s))[0] == 17
