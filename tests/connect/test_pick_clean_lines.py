"""A word said on several lines is cut from the one whose audio the subtitle gives no reason to doubt
(app/connect/pick.py `Around`: the subtitle alone, before anything is cut).

A card's audio is whatever plays while its lines are on screen. Three things the subtitle itself shows make that
audio more than the sentence: another speaker's line on screen at the same time, a song line on screen at the same
time, and a line shown far faster or slower than it can be said (its timing is off, or it is not speech all the way).
Each is a preference among a word's own lines, after "no other new word" and before the 8 s cap: a word whose only
line has one is still sent.

The lines above the real-file section are written for these tests (natural Japanese and Chinese, no show's lines);
the real-file section reads tests/Test Resources. Times are seconds.
"""
import os

import pytest

from app import analyzer, cues
from app.connect import pick


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _srt(tmp_path, lines, name="episode.ja.srt"):
    """An .srt of `lines` [(start s, end s, text)]."""
    def stamp(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    body = "\n".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(lines, 1))
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _picked(tmp_path, lines, word, language="ja", unknown=None, name="episode.ja.srt"):
    """The line start (s) the card of `word` is cut from, `word` (and `unknown`) the only words not known."""
    read = cues.read(_srt(tmp_path, lines, name), language)
    tokens = cues.tokens(read, language)
    new = {word} | set(unknown or ())
    chosen = pick.pick(read, tokens, language, lambda key: key[0] not in new, mode="unknown")
    return {w["word"]: w["line_start"] for w in chosen["words"]}[word]


def _doubts(tmp_path, lines, at, language="ja", name="episode.ja.srt"):
    read = cues.read(_srt(tmp_path, lines, name), language)
    held = [at]
    return pick.Around(read).doubts(at, held, language)


# --------------------------------------------------------------------------- #
# Another speaker's line on screen with the card
def test_a_line_another_speaker_talks_over_gives_way_to_a_line_said_alone(tmp_path):
    lines = [(10.0, 12.5, "この小説は面白いよ"), (10.4, 12.2, "ちょっと待ってよ"),     # two lines at once
             (40.0, 42.5, "あの小説を読んだの")]
    assert _picked(tmp_path, lines, "小説") == 40.0


def test_a_line_that_only_touches_its_neighbour_is_said_alone(tmp_path):
    # streaming lines 83 ms apart, and even a 200 ms overlap of two cues, are one speaker after another
    lines = [(10.0, 12.5, "この小説は面白いよ"), (12.3, 14.5, "ちょっと待ってよ"), (40.0, 42.5, "あの小説を読んだの")]
    assert _doubts(tmp_path, lines, 0) == 0
    assert _picked(tmp_path, lines, "小説") == 10.0


def test_a_line_shown_again_is_not_another_speaker(tmp_path):
    # the same text at the same time (a caption shown twice, an .ass layer): the card's own line
    lines = [(10.0, 12.5, "この小説は面白いよ"), (10.0, 12.5, "この小説は面白いよ")]
    assert _doubts(tmp_path, lines, 0) == 0


def test_a_sign_in_another_script_on_screen_is_not_a_speaker(tmp_path):
    lines = [(10.0, 12.5, "この小説は面白いよ"), (10.0, 12.5, "BOOK STORE")]
    assert _doubts(tmp_path, lines, 0) == 0


# --------------------------------------------------------------------------- #
# A song line on screen with the card
def test_a_line_said_under_a_song_gives_way_to_a_line_with_none(tmp_path):
    lines = [(10.0, 12.5, "この小説は面白いよ"), (9.0, 14.0, "♪ 遠い空の向こうへ"), (40.0, 42.5, "あの小説を読んだの")]
    assert _picked(tmp_path, lines, "小説") == 40.0


def test_a_song_mark_alone_on_screen_counts_as_a_song(tmp_path):
    # ♪～ holds none of the language's script (Anki Miner drops the line), and still says what is playing
    lines = [(10.0, 12.5, "この小説は面白いよ"), (9.0, 14.0, "♪～"), (40.0, 42.5, "あの小説を読んだの")]
    assert _doubts(tmp_path, lines, 0) == 1
    assert _picked(tmp_path, lines, "小説") == 40.0


# --------------------------------------------------------------------------- #
# A line shown far faster or slower than it is said
@pytest.mark.parametrize("start, end, text, ok", [
    (10.0, 12.5, "この小説は面白いよ", True),             # 9 characters in 2.5 s
    (10.0, 10.4, "この小説は本当に面白いよね", False),     # 13 characters in 0.4 s: no one says that
    (10.0, 19.0, "この小説は面白いよ", False),             # 9 characters in 9 s: not speech all the way
    (10.0, 14.0, "はい", True),                           # too short a line to judge
])
def test_a_line_is_paced_when_it_is_shown_about_as_long_as_it_takes_to_say(tmp_path, start, end, text, ok):
    read = cues.read(_srt(tmp_path, [(start, end, text)]), "ja")
    assert pick.paced(read[0], "ja") is ok


def test_a_line_shown_too_briefly_gives_way_to_one_at_a_speaking_pace(tmp_path):
    lines = [(10.0, 10.4, "この小説は本当に面白いよね"), (40.0, 42.5, "あの小説を読んだの")]
    assert _picked(tmp_path, lines, "小説") == 40.0


def test_chinese_lines_are_judged_at_a_chinese_pace(tmp_path):
    lines = [(10.0, 10.3, "这本小说真的非常好看"), (40.0, 42.5, "我昨天看了那本小说")]
    read = cues.read(_srt(tmp_path, lines, "episode.zh.srt"), "zh")
    assert [pick.paced(cue, "zh") for cue in read] == [False, True]
    assert pick.Around(read).doubts(0, [0], "zh") == 1 and pick.Around(read).doubts(1, [1], "zh") == 0


@pytest.mark.parametrize("start, end, zh, ja", [
    (10.0, 10.85, False, True),     # 10 characters in 0.85 s (~11.8 a second): fast for Chinese, not for Japanese
    (10.0, 18.0, True, False),      # 10 characters in 8 s (1.25 a second): slow for Japanese, not for Chinese
])
def test_the_chinese_pace_is_its_own(tmp_path, start, end, zh, ja):
    read = cues.read(_srt(tmp_path, [(start, end, "这本小说真的非常好看")], "episode.zh.srt"), "zh")
    assert pick.paced(read[0], "zh") is zh and pick.paced(read[0], "ja") is ja


# --------------------------------------------------------------------------- #
# What is on screen: short lines, copies, long lines
@pytest.mark.parametrize("language, short, over, name", [
    ("ja", "はい", "ちょっと待ってよ", "episode.ja.srt"),
    ("zh", "好", "你等我一下好吗", "episode.zh.srt"),
])
def test_another_line_over_all_of_a_short_line_is_another_speaker(tmp_path, language, short, over, name):
    # a reply shown 250 ms, wholly under another line of the card: shorter than OVER_MS, still said at the same time
    read = cues.read(_srt(tmp_path, [(10.0, 10.25, short), (9.5, 11.5, over)], name), language)
    assert pick.Around(read).doubts(0, [0, 1], language) == 1


def test_a_short_line_that_only_touches_another_is_said_alone(tmp_path):
    # はい ends as the next line starts (50 ms shared): one speaker after another, however short the line
    read = cues.read(_srt(tmp_path, [(10.0, 10.25, "はい"), (10.2, 12.5, "ちょっと待ってよ")]), "ja")
    assert pick.Around(read).doubts(0, [0], "ja") == 0


@pytest.mark.parametrize("language, one, two, name", [
    ("ja", "この小説は 面白いよ", "この小説は面白いよ", "episode.ja.srt"),
    ("zh", "这本小说 真的很好看", "这本小说真的很好看", "episode.zh.srt"),
])
def test_a_copy_shown_on_two_lines_is_still_the_same_line(tmp_path, language, one, two, name):
    # the same caption, once on one line and once broken in two: one speaker, spaces aside (as shown_again)
    read = cues.read(_srt(tmp_path, [(10.0, 12.5, one), (10.0, 12.5, two)], name), language)
    around = pick.Around(read)
    assert around.doubts(0, [0], language) == 0 and around.doubts(1, [1], language) == 0


def test_a_song_on_screen_for_minutes_is_still_on_screen(tmp_path):
    # a karaoke line held for a whole minute is kept apart in the look-up and still found
    lines = [(0.0, 60.0, "♪ 遠い空の向こうへ"), (30.0, 32.5, "この小説は面白いよ"), (90.0, 92.5, "あの小説を読んだの")]
    read = cues.read(_srt(tmp_path, lines), "ja")
    around = pick.Around(read)
    assert around.long == [0] and around.longest == 2500     # the look-up reaches back 2.5 s, not a minute
    assert around.doubts(1, [1], "ja") == 1 and around.doubts(2, [2], "ja") == 0
    assert _picked(tmp_path, lines, "小説") == 90.0


def test_a_sign_on_screen_for_minutes_is_not_another_speaker(tmp_path):
    # an episode's title held for 45 s is no one saying it: the line under it is said alone (a song still counts)
    lines = [(0.0, 45.0, "第一話 星屑の駅"), (10.0, 12.5, "この小説は面白いよ"), (90.0, 92.5, "あの小説を読んだの")]
    read = cues.read(_srt(tmp_path, lines), "ja")
    assert read[0].counted and not read[0].sung
    assert pick.Around(read).doubts(1, [1], "ja") == 0
    assert _picked(tmp_path, lines, "小説") == 10.0


# --------------------------------------------------------------------------- #
# A preference only
def test_a_word_whose_only_line_is_talked_over_is_still_sent(tmp_path):
    lines = [(10.0, 12.5, "この小説は面白いよ"), (10.4, 12.2, "ちょっと待ってよ")]
    assert _picked(tmp_path, lines, "小説") == 10.0


def test_no_other_new_word_still_comes_before_a_clean_line(tmp_path):
    # i+1 outranks it: the clean line holds another new word, so the talked-over one is taken
    lines = [(10.0, 12.5, "この小説は面白いよ"), (10.4, 12.2, "ちょっと待ってよ"),
             (40.0, 42.5, "あの小説は図書館で借りた")]
    assert _picked(tmp_path, lines, "小説", unknown=("図書館",)) == 10.0


def test_a_clean_line_comes_before_one_the_cap_does_not_cut(tmp_path):
    # the clean line's sentence runs past the 8 s cap; the short one is said under a song
    long = [(40.0, 43.9, "昨日 駅前の本屋で"), (43.983, 47.883, "ずっと探していた小説を"),
            (47.966, 51.866, "やっと見つけて"), (51.949, 55.849, "買ってきた")]
    lines = [(10.0, 12.5, "この小説は面白いよ"), (9.0, 14.0, "♪ 遠い空の向こうへ")] + long
    assert _picked(tmp_path, lines, "小説") == 43.983


def test_a_books_sentences_have_no_audio_to_doubt(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("この小説は面白い。あの小説を読んだ。", encoding="utf-8")
    read, tokens = cues.reading(str(path), "ja")
    chosen = pick.pick(read, tokens, "ja", lambda key: key[0] != "小説", mode="unknown")
    assert [w["word"] for w in chosen["words"]] == ["小説"]


# --------------------------------------------------------------------------- #
# The real subtitle files: a doubt only where the clip really holds more than its sentence (the false alarms kept down)
REAL = os.path.join(os.path.dirname(__file__), os.pardir, "Test Resources")


@pytest.mark.parametrize("name, language, doubted", [
    # two lines on screen at once (two speakers): both doubted; a line shown again is never another speaker
    ("ja/repeated_lines.ja.srt", "ja", {3, 4}),
    # a two-speaker caption; the station mark on screen (not counted) doubts nothing
    ("ja/tv_captions.ass", "ja", {1, 2}),
    # two lines at once in the episode; the opening song's lines end long before the dialogue starts
    ("ja/library_episode.ass", "ja", {8, 9}),
    ("ja/placed_episode.srt", "ja", set()),
    ("ja/phrases_sample.srt", "ja", set()),
    ("zh/night_market.srt", "zh", set()),
    ("zh/repeated_lines.zh.srt", "zh", set()),
])
def test_on_the_real_files_only_a_clip_holding_another_voice_or_a_song_is_doubted(name, language, doubted):
    """Every line said alone in the test resources' real episodes gets no doubt: each good line wrongly doubted is one
    fewer good sentence to choose from. The doubted ones share their screen time with another speaker's line."""
    read = cues.read(os.path.join(REAL, *name.split("/")), language)
    around = pick.Around(read)
    got = {i for i, cue in enumerate(read) if cue.counted and not cue.sung and around.doubts(i, [i], language)}
    assert got == doubted


@pytest.mark.parametrize("name, language", [("ja/library_episode.ass", "ja"), ("ja/tv_captions.ass", "ja"),
                                            ("ja/repeated_lines.ja.srt", "ja"), ("zh/night_market.srt", "zh")])
def test_on_the_real_files_the_doubts_only_reorder_never_drop_a_word(name, language, monkeypatch):
    """A preference only: with every word unknown, the words sent with the doubts are the words sent without them."""
    read = cues.read(os.path.join(REAL, *name.split("/")), language)
    tokens = cues.tokens(read, language)
    sent = lambda: sorted(w["word"] for w in pick.pick(read, tokens, language, lambda key: False,
                                                       mode="unknown")["words"])
    with_doubts = sent()
    monkeypatch.setattr(pick.Around, "doubts", lambda self, at, held, language: 0)
    assert with_doubts == sent() and with_doubts


def test_the_same_line_listed_twice_is_not_another_speaker(tmp_path):
    """A subtitle that lists one line twice at the same time (a common slip in a hand-made file) holds one voice: the
    copy is the card's own sentence, so the line keeps no doubt and is still preferred over a later one."""
    lines = [(10.0, 12.5, "この小説は面白いよ"), (10.0, 12.5, "この小説は面白いよ"),
             (20.0, 22.5, "小説を読むのが好き"), (20.3, 22.2, "ちょっと待ってよ")]
    assert _picked(tmp_path, lines, "小説", unknown={"待つ"}) == 10.0
