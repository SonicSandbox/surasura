"""A transcript's groups in parentheses are no speech, as a subtitle's are (SUB-PARENS, widened 3.0.17).

A Netflix or Disney+ episode reaches the library as a transcript — the YouTube downloader's header, then a cue a line
(the browser extension's items) — and Netflix's Japanese subtitles name the speaker at the start of about half their lines,
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
    text = _read(tmp_path, _transcript(NETFLIX_BODY))
    words = _surfaces(text)
    assert not [w for w in words if "女子" in w or "生徒" in w or "足音" in w or "チャイム" in w or "遠野" in w], words
    assert text.count("佐倉") == 1, "the one 佐倉 left is the one said (佐倉さん), never the labels'"
    assert any("転校" in w for w in words) and any("早" in w for w in words)


def test_timestamps_kept_crlf_and_a_bracket_left_open_on_its_line(tmp_path):
    """The 'keep timestamps' format and Windows line ends read the same; a group never runs across a line break —
    an opener left open on one line keeps the lines after it, up to a closer two cues later."""
    body = "\r\n".join(("[00:01:02] （平野）おはよう", "[00:01:05] （遠藤）おはよう 平野さん", "[00:01:09] えっと（ 何だっけ",
                        "[00:01:12] 宿題 やった？", "[00:01:15] まだ）やってない"))
    path = tmp_path / "雲の上の郵便屋さん S01E04 [netflix-81234568].txt"
    path.write_bytes(_transcript(body).replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))   # CRLF once
    text = analyzer.extract_text(str(path), "ja")
    assert "[00:" not in text and "平野）" not in text and "遠藤" not in text
    for said in ("おはよう 平野さん", "何だっけ", "宿題 やった？", "やってない"):
        assert said in text, said


def test_a_group_is_short_or_it_is_text(tmp_path):
    """At most 40 pieces inside (each a character, or a nested reading of at most 40): Netflix's longest group in a
    season was 15 characters. A 41-character stretch between brackets is speech as written."""
    inside_40, inside_41 = "あ" * 40, "い" * 41
    text = _read(tmp_path, _transcript(f"（{inside_40}）一\n（{inside_41}）二\n（({'う' * 41})）三"))
    assert inside_40 not in text and f"（{inside_41}）二" in text and "う" * 41 in text


def test_the_source_link_finds_a_sentence_whose_group_sat_inside_it(tmp_path):
    """A transcript without a sidecar is linked by the report's source anchor: the sentence lost its （笑）, the
    file didn't — the anchor steps over the group and hands back the file's own wording, found once."""
    path = tmp_path / "天気の話 [abcdefghijk].txt"
    path.write_text(_transcript("今日は（笑）いい天気ですね。 明日は雨（雷鳴）らしいです。", title="天気の話",
                                channel="天気チャンネル | 2026-01-01 | 1:00", site="youtube"), encoding="utf-8")
    text = analyzer.extract_text(str(path), "ja")
    sentences = [s for s, _tokens in analyzer.JapaneseTokenizer().tokenize_sentences(text)]
    assert sentences == ["今日はいい天気ですね。", "明日は雨らしいです。"]
    finder = AnchorFinder(language="ja")
    assert finder.anchor(str(path), sentences[0]) == "今日は（笑）いい天気ですね"
    assert finder.anchor(str(path), sentences[1]) == "明日は雨（雷鳴）らしいです"


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
