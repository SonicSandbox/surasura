"""A subtitle line shown again is one line (analyzer.shown_again, ENGINE_REVISION 40; SPEC card-lines rule 5).

Streaming subtitles show a line through another speaker's by writing it again: the same text as two or three cues
back to back, each starting as the one before ends, the other speaker's line beside them at the same time. An .ass
file draws a line twice (a glow layer under it: one timing). A Generate read such a line two or three times; it reads
it once now, and the cue reader keeps every copy — the cue count and order stay the file's, as Anki Miner indexes
them — with the copies not `counted` and `repeats` naming the first.

The lines are written for these tests (natural Japanese and Chinese), never taken from a show.
"""
import pytest

from app import analyzer, cues


@pytest.fixture(autouse=True)
def _sanitized():
    # A Japanese run reads sanitized lemmas (analyzer.main sets it; conftest restores the global).
    analyzer.SANITIZE_JA = True


def _write(tmp_path, name, text, encoding="utf-8", newline="\n"):
    path = tmp_path / name
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)
    return str(path)


def _srt(*blocks):
    """An .srt from (start, end, text) blocks, times as SubRip writes them."""
    return "\n".join(f"{n}\n{start} --> {end}\n{text}\n" for n, (start, end, text) in enumerate(blocks, 1))


# One speaker's line shown through another's: three copies, each starting as the one before ends; the other speaker's
# short line on screen beside the second copy (the same timing), then the next line 83 ms later.
STREAMING = _srt(("00:00:20,051", "00:00:20,969", "（ハル）この道 聞いてたのと違うな"),
                 ("00:00:20,969", "00:00:22,136", "（ハル）この道 聞いてたのと違うな"),
                 ("00:00:20,969", "00:00:22,136", "（ミナ）えっ…"),
                 ("00:00:22,136", "00:00:23,012", "（ハル）この道 聞いてたのと違うな"),
                 ("00:00:23,095", "00:00:25,000", "地図を見せてくれる？"))

# The same words said twice, as two lines: streaming subtitles leave 83 ms (two frames) between two lines.
SAID_TWICE = _srt(("00:00:30,000", "00:00:31,000", "もう行こう"),
                  ("00:00:31,083", "00:00:32,000", "もう行こう"))


def _store_words(tmp_path, path, language):
    """The words the token store holds for `path`, indexed as the indexer and Generate index it (test_cues' helper)."""
    from app import names, token_index as ti
    store = ti.open_store(language, path=str(tmp_path / f"store_{language}.db"))
    try:
        store.reconcile([path], ti.make_tokenizer(language), build_signature=ti.build_signature(language))
        names.use_library_tables(store.names_tables())
        return [(t[0], t[1]) for _s, tokens in store.file_tokens(path) for t in tokens]
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("second, again", [
    ((1000, 2000), 0),         # starts as the copy ends: the line shown again
    ((1010, 2000), 0),         # 10 ms after (one centisecond, an .ass file's step): still touching
    ((1011, 2000), None),      # 11 ms after: two lines
    ((1083, 2000), None),      # 83 ms: a streaming subtitle's gap between two lines — the words said twice
    ((1100, 2000), None),      # 100 ms: two lines
    ((700, 1500), 0),          # overlapping it (a fade drawn twice)
    ((0, 1000), 0),            # the same timing (a layer)
    ((5000, 6000), None),      # seconds later: said again
    ((-2000, -11), None),      # written later but said before it, 11 ms apart: two lines
    ((-2000, -10), 0),         # … 10 ms before it: one
])
def test_a_copy_is_the_line_shown_again_only_when_their_times_touch(second, again):
    first = (0, 1000, "もう行こう")
    assert analyzer.shown_again([first, (second[0], second[1], "もう行こう")]) == [None, again]


def test_a_third_copy_and_a_line_between_still_show_the_first_again():
    lines = [(20051, 20969, "この道 聞いてたのと違うな"), (20969, 22136, "この道 聞いてたのと違うな"),
             (20969, 22136, "えっ…"), (22136, 23012, "この道 聞いてたのと違うな"), (23095, 25000, "地図を見せてくれる？")]
    assert analyzer.shown_again(lines) == [None, 0, None, 0, None]


def test_a_layer_listed_first_is_found_whenever_the_line_comes_back():
    # An .ass file's glow layer for the whole episode first, then the lines themselves: うん said twice, minutes apart,
    # each drawn twice — two lines, each read once (the adversary's S1: only the text's last time was looked at)
    lines = [(10000, 12000, "うん"), (300000, 302000, "うん"), (10000, 12000, "うん"), (300000, 302000, "うん")]
    assert analyzer.shown_again(lines) == [None, None, 0, 1]


def test_spaces_aside_the_text_is_the_line_and_a_different_text_never_is():
    # the subtitler broke the copy's line elsewhere: the same line; one word more is another line
    assert analyzer.shown_again([(0, 1000, "この道 聞いてたのと違うな"), (1000, 2000, "この道聞いてたのと 違うな"),
                                 (2000, 3000, "この道聞いてたのと違うなあ")]) == [None, 0, None]


def test_a_line_no_generate_reads_is_never_a_copy_nor_copied():
    # None: a line in another script, karaoke, a time that can't be read — it neither repeats nor is repeated
    assert analyzer.shown_again([(0, 1000, "はい"), None, (1000, 2000, "はい")]) == [None, None, 0]
    assert analyzer.shown_again([None, (0, 1000, "はい")]) == [None, None]
    assert analyzer.shown_again([]) == []


def test_ass_times_read_in_milliseconds():
    assert analyzer.ass_ms("0:00:20.97") == 20970 and analyzer.ass_ms(" 1:02:03.4 ") == 3723400
    assert analyzer.ass_ms("0:00:05") == 5000
    assert analyzer.ass_ms("soon") is None and analyzer.ass_ms("") is None and analyzer.ass_ms(None) is None


# --------------------------------------------------------------------------- #
# A Generate reads the line once
# --------------------------------------------------------------------------- #
def test_a_generate_reads_a_streaming_line_shown_through_another_speakers_once(tmp_path):
    text = analyzer.extract_text(_write(tmp_path, "ep01.ja.srt", STREAMING), "ja")
    assert text == "この道 聞いてたのと違うな。えっ…\n地図を見せてくれる？"
    words = [t[0] for _s, tokens in analyzer.JapaneseTokenizer().tokenize_sentences(text) for t in tokens]
    assert words.count("違う") == 1 and words.count("道") == 1


def test_the_same_words_said_twice_as_two_lines_are_read_twice(tmp_path):
    text = analyzer.extract_text(_write(tmp_path, "ep02.ja.srt", SAID_TWICE), "ja")
    assert text == "もう行こう。もう行こう。"


def test_an_ass_line_drawn_twice_and_shown_again_is_read_once(tmp_path):
    # A glow layer under the line (one timing, its own style and colour), then a line written again as it ends;
    # a karaoke OP line is still never read, and a line said again a second later is two.
    path = _write(tmp_path, "ep03.ja.ass", "﻿[Script Info]\r\nScriptType: v4.00+\r\n\r\n[V4+ Styles]\r\n"
                  "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold\r\n"
                  "Style: Default,MS Gothic,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0\r\n"
                  "Style: Glow,MS Gothic,64,&H00FFAA00,&H000000FF,&H00000000,&H80000000,0\r\n"
                  "Style: OP_JP,MS Gothic,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0\r\n\r\n[Events]\r\n"
                  "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
                  "Dialogue: 0,0:00:01.00,0:00:04.00,OP_JP,,0,0,0,,{\\k40}夜{\\k35}空{\\k60}に{\\k45}歌う\r\n"
                  "Dialogue: 0,0:00:05.00,0:00:07.50,Glow,,0,0,0,,{\\blur3}明日は雨が降るらしい\r\n"
                  "Dialogue: 1,0:00:05.00,0:00:07.50,Default,,0,0,0,,明日は雨が降るらしい\r\n"
                  "Dialogue: 0,0:00:07.60,0:00:09.00,Default,,0,0,0,,傘を持っていこうかな\r\n"
                  "Dialogue: 0,0:00:09.00,0:00:10.20,Default,,0,0,0,,傘を持っていこうかな\r\n"
                  "Dialogue: 0,0:00:11.20,0:00:12.00,Default,,0,0,0,,うん\r\n"
                  "Dialogue: 0,0:00:13.00,0:00:14.00,Default,,0,0,0,,うん\r\n", newline="")
    assert analyzer.extract_text(path, "ja") == "明日は雨が降るらしい。 傘を持っていこうかな。 うん。 うん。"
    read = cues.read(path, "ja")
    assert len(read) == 7 and [c.index for c in read] == list(range(7))       # every event still a cue, in order
    assert [c.repeats for c in read] == [None, None, 1, None, 3, None, None]
    assert [c.counted for c in read] == [False, True, False, True, False, True, True]
    assert cues._text(read, "ja")[0] == analyzer.extract_text(path, "ja")


def test_chinese_lines_shown_again_are_read_once(tmp_path):
    path = _write(tmp_path, "ep01.zh.srt", _srt(("00:00:01,000", "00:00:02,500", "我们明天去看电影吧"),
                                                ("00:00:02,500", "00:00:03,200", "我们明天去看电影吧"),
                                                ("00:00:02,500", "00:00:03,200", "（小美）好啊"),
                                                ("00:00:04,000", "00:00:05,000", "好啊")))
    assert analyzer.extract_text(path, "zh") == "我们明天去看电影吧。好啊。好啊。"
    read = cues.read(path, "zh")
    assert [c.repeats for c in read] == [None, 0, None, None]
    found = cues.tokens(read, "zh")
    assert [t.lemma for t in found].count("电影") == 1 and {t.cue for t in found} == {0, 2, 3}


# --------------------------------------------------------------------------- #
# The cue reader keeps every copy
# --------------------------------------------------------------------------- #
def test_the_cue_reader_keeps_each_copy_uncounted_and_the_cues_in_the_files_order(tmp_path):
    read = cues.read(_write(tmp_path, "ep01.ja.srt", STREAMING), "ja")
    # Anki Miner indexes the file's own cues: five here, in the file's order, with the file's times
    assert len(read) == 5 and [c.index for c in read] == list(range(5))
    assert [(c.start, c.end) for c in read] == [(20051, 20969), (20969, 22136), (20969, 22136), (22136, 23012),
                                                (23095, 25000)]
    assert [c.counted for c in read] == [True, False, True, False, True]
    assert [c.repeats for c in read] == [None, 0, None, 0, None]
    assert read[1].text == read[3].text == read[0].text == "この道 聞いてたのと違うな"


def test_a_line_said_twice_stays_two_counted_cues(tmp_path):
    read = cues.read(_write(tmp_path, "ep02.ja.srt", SAID_TWICE), "ja")
    assert [c.counted for c in read] == [True, True] and [c.repeats for c in read] == [None, None]
    assert [t.cue for t in cues.tokens(read, "ja") if t.lemma == "行く"] == [0, 1]


def test_the_words_are_in_the_first_copy_only(tmp_path):
    read = cues.read(_write(tmp_path, "ep01.ja.srt", STREAMING), "ja")
    found = cues.tokens(read, "ja")
    assert [t.cue for t in found if t.lemma == "違う"] == [0]
    assert {t.cue for t in found} == {0, 2, 4}


def test_a_sung_line_shown_again_is_never_read_on_its_own(tmp_path):
    # A ♪ line is sung (no card is cut from it) but a Generate counts it; its copy is neither
    read = cues.read(_write(tmp_path, "ep04.ja.srt", _srt(("00:01:00,000", "00:01:02,000", "♪ 風の中で歌おう"),
                                                          ("00:01:02,000", "00:01:03,500", "♪ 風の中で歌おう"))), "ja")
    assert [(c.sung, c.counted, c.repeats) for c in read] == [(True, True, None), (True, False, 0)]
    found = cues.tokens(read, "ja")
    assert found and {t.cue for t in found} == {0}
    assert [t.lemma for t in found].count("風") == 1


@pytest.mark.parametrize("name, text", [("ep01.ja.srt", STREAMING), ("ep02.ja.srt", SAID_TWICE)])
def test_the_cue_readers_words_are_the_token_stores_for_a_file_with_copies(tmp_path, name, text):
    # Intent review #12: the pick reads exactly the words the list counted — a copy's words neither, a line said
    # twice both.
    path = _write(tmp_path, name, text)
    read = cues.read(path, "ja")
    assert [(t.lemma, t.reading) for t in cues.tokens(read, "ja") if read[t.cue].counted] \
        == _store_words(tmp_path, path, "ja")


def test_the_cue_readers_text_is_a_generates_with_crlf_and_a_bom(tmp_path):
    path = _write(tmp_path, "ep05.ja.srt", "﻿" + STREAMING, newline="\r\n")
    assert cues._text(cues.read(path, "ja"), "ja")[0] == analyzer.extract_text(path, "ja")


# --------------------------------------------------------------------------- #
# The line's time
# --------------------------------------------------------------------------- #
def test_a_line_shown_again_is_said_until_its_last_copy_ends(tmp_path):
    # SPEC rule 5: the clip runs to the end of the speech — the journey's line times as the card's
    line = cues.timeline(_write(tmp_path, "ep01.ja.srt", STREAMING), "ja").line
    assert line("この道聞いてたのと違うな。") == (20051, 23012)
    assert line("えっ…") == (20969, 22136)
    assert line("地図を見せてくれる？") == (23095, 25000)


def test_a_line_said_twice_keeps_each_lines_own_time(tmp_path):
    line = cues.timeline(_write(tmp_path, "ep02.ja.srt", SAID_TWICE), "ja").line
    assert line("もう行こう。") == (30000, 31000)      # its first time, as before


def test_a_copy_written_later_but_shown_first_moves_the_lines_start(tmp_path):
    # file order is not time order: the copy is said first, and the line runs from its start
    path = _write(tmp_path, "ep06.ja.srt", _srt(("00:00:05,000", "00:00:06,000", "そろそろ帰ろうか"),
                                                ("00:00:04,000", "00:00:05,000", "そろそろ帰ろうか")))
    assert [c.repeats for c in cues.read(path, "ja")] == [None, 0]
    assert cues.timeline(path, "ja").line("そろそろ帰ろうか。") == (4000, 6000)


def test_files_with_no_lines_have_no_copies(tmp_path):
    for name, text in (("empty.ja.srt", ""), ("empty.ja.ass", "[Events]\n")):
        path = _write(tmp_path, name, text)
        assert list(cues.read(path, "ja")) == [] and analyzer.extract_text(path, "ja") == ""
