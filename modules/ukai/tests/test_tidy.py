# SPDX-License-Identifier: GPL-3.0-or-later
"""A streaming site's subtitle made what a subtitle file is, before anything reads it (`modules/ukai/subtitles`
`tidy_cues`, `unruby`; ported from #474's `tests/test_online_receiver_tidy.py`, by mattias): the text an item is
analysed from, its sidecar, the lines Connect picks, the clips the extension records and the sentences Anki Miner
writes all come from what is kept here.

What a wrong answer would cost a learner (Mattias, 2026-11-19, a Netflix season mined in one evening): a card whose
sentence says one line two or three times while its sound holds part of it; another speaker's line inside the card;
a reading written into the sentence (黒沼くろぬま) and a card made for a word that is only that reading (ぬま).

Every line here is written for these tests (no show's lines). Times are seconds.
"""

import pytest

from modules.ukai import subtitles as rx


# --------------------------------------------------------------------------- #
# One line, one cue
def test_a_line_split_around_another_speakers_is_one_cue_again():
    # the player shows A, then A again while B is on screen, then A once more: A is one line, B overlaps it
    cues = [[10.0, 11.3, "今日は駅まで歩いて帰るよ"], [11.3, 13.8, "今日は駅まで歩いて帰るよ"],
            [11.3, 13.8, "（友達）雨が降りそうだけど"], [13.8, 14.5, "今日は駅まで歩いて帰るよ"],
            [15.0, 16.0, "気をつけてね"]]
    assert rx.tidy_cues(cues, "ja") == [[10.0, 14.5, "今日は駅まで歩いて帰るよ"],
                                        [11.3, 13.8, "（友達）雨が降りそうだけど"], [15.0, 16.0, "気をつけてね"]]


def test_a_line_said_again_later_is_two_lines():
    cues = [[10.0, 11.0, "おはよう"], [30.0, 31.0, "おはよう"]]
    assert rx.tidy_cues(cues, "ja") == cues


def test_copies_are_the_same_line_spaces_aside_and_come_in_time_order():
    cues = [[13.8, 14.5, "今日は 駅まで"], [10.0, 13.8, "今日は駅まで"]]
    assert rx.tidy_cues(cues, "ja") == [[10.0, 14.5, "今日は駅まで"]]


def test_chinese_copies_are_joined_too():
    cues = [[5.0, 6.0, "我们明天见"], [6.0, 7.5, "我们明天见"], [6.0, 7.5, "好的"]]
    assert rx.tidy_cues(cues, "zh") == [[5.0, 7.5, "我们明天见"], [6.0, 7.5, "好的"]]


# --------------------------------------------------------------------------- #
# No reading written into the line
@pytest.mark.parametrize("flat, kept", [
    ("黒沼くろぬまさん おはよう", "黒沼さん おはよう"),          # a name
    ("矢野やのと吉田よしだは？", "矢野と吉田は？"),              # its reading read as particles is still its reading
    ("武田信玄たけだしんげんだもんね", "武田信玄だもんね"),       # a name of two words
    ("それは復讐ふくしゅう？", "それは復讐？"),                  # a hard word
    ("読売よみうり新聞の記者です", "読売新聞の記者です"),
    ("善ぜんはどうしたんだ？", "善はどうしたんだ？"),
])
def test_a_reading_after_its_kanji_is_taken_out(flat, kept):
    assert rx.unruby(flat) == kept


@pytest.mark.parametrize("text", [
    "何なんだよ それ",           # 何 + なんだ: the sentence's own grammar
    "ホンマ 負けず嫌いやな",     # 嫌い + や: one word
    "日にちを決めよう",          # one word
    "殺し屋やマフィアとは違う",  # 屋 + や (and)
    "葉はたくさんある",          # 葉 + は (topic)
    "今日は晴れ",
    "食べる",
    "ジョーです",
])
def test_kana_that_are_the_sentence_stay(text):
    assert rx.unruby(text) == text


def test_readings_are_taken_out_before_copies_are_compared():
    cues = [[1.0, 2.0, "黒沼くろぬま"], [2.0, 3.0, "黒沼"]]
    assert rx.tidy_cues(cues, "ja") == [[1.0, 3.0, "黒沼"]]


def test_chinese_text_is_never_read_for_readings():
    assert rx.tidy_cues([[1.0, 2.0, "你好吗"]], "zh") == [[1.0, 2.0, "你好吗"]]


def test_no_tagger_keeps_the_text_as_sent(monkeypatch):
    monkeypatch.setattr(rx, "_TAGGER", [None])
    assert rx.unruby("黒沼くろぬま") == "黒沼くろぬま"


# --------------------------------------------------------------------------- #
# The subtitle a post becomes
def test_a_posted_subtitle_is_tidied_before_it_is_kept():
    body = {"schema": 1, "site": "netflix", "video_id": "81000001", "url": "https://www.netflix.com/watch/81000001",
            "language": "ja", "title": "第一話", "show": {"title": "駅前の物語", "season": 1, "episode": 1},
            "cues": [[10.0, 11.3, "黒沼くろぬまさん おはよう"], [11.3, 12.0, "黒沼くろぬまさん おはよう"],
                     [11.3, 12.0, "（友達）早いね"]]}
    sub = rx.subtitle(body)                             # (the door hands the route its parsed body)
    assert sub["cues"] == [[10.0, 12.0, "黒沼さん おはよう"], [11.3, 12.0, "（友達）早いね"]]
    assert "くろぬま" not in rx.text(sub)
