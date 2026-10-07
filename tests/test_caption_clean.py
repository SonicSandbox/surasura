"""The TV-caption cleaner (app/caption_clean.py, P1.3 row 1.3.2; ✅ G1.3-11): a broadcast .ass's reading rows dropped,
the rows of one caption joined, the arrows taken off — and the copy a job reads written where the job reads it, so the
pick and Anki Miner see the same lines.

`ja/tv_captions.ass` is broadcast-style: a reading row in small type by override (もんばん) and by style (ちょうろう), a
caption cut into two rows (《門番は城への侵入者を / 厳しく取り調べた》), two speakers at one time in two colours, an
arrow, a small-type row that isn't a reading (ＮＨＫ), and small type that is no half-size row (\\fs40).
"""
import os

import pytest

from app import analyzer, caption_clean, cues

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja")
TV = os.path.join(RESOURCES, "tv_captions.ass")


@pytest.fixture
def copy(tmp_path):
    return caption_clean.copy_for(TV, str(tmp_path / "runs" / "job-1"))


def _texts(path):
    return [c.text for c in cues.read(path, "ja")]


def test_reading_rows_go_by_override_and_by_style(copy):
    texts = _texts(copy)
    assert not any(t in ("もんばん", "ちょうろう") for t in texts)
    assert "もんばん" not in _texts(TV)                  # the original reads the same: cleaned as a Generate reads it
    assert "もんばん" in open(TV, encoding="utf-8").read()      # and is never changed on disk


def test_the_rows_of_one_caption_are_one_line_and_two_speakers_stay_two(copy):
    read = cues.read(copy, "ja")
    texts = [c.text for c in read]
    assert "《門番は城への侵入者を 厳しく取り調べた》" in texts
    assert "え…養父様を？" in texts and "うむ。" in texts       # one time, two colours: two people
    joined = next(c for c in read if c.text.startswith("《門番"))
    assert (joined.start, joined.end) == (5100, 8400)


def test_an_arrow_is_taken_off_and_the_line_still_runs_on(copy):
    texts = _texts(copy)
    assert "長老の話によれば" in texts and not any("➡" in t for t in texts)
    assert "長老の話によれば➡" in _texts(TV)          # read as a Generate reads it: the arrow says it runs on
    # the sentence still runs into the next line (an unfinished line), so the card holds both
    from app.connect import pick
    read = cues.read(copy, "ja")
    at = next(c.index for c in read if c.text == "長老の話によれば")
    assert pick.line_expansion(read, at) == [0, 1]


def test_what_isnt_a_reading_row_stays(copy):
    texts = _texts(copy)
    assert "いってきます！" in texts                            # \fs40 is a font size, not a half-size row
    raw = open(copy, encoding="utf-8").read()
    assert "ＮＨＫ" in raw                                      # small, but no kana: no reading


def test_the_copy_is_utf8_without_a_bom_and_keeps_everything_else(copy):
    raw = open(copy, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    original = open(TV, encoding="utf-8").read().replace("\r\n", "\n")
    for line in original.split("\n"):
        if not line.startswith("Dialogue:"):
            assert line in text                                 # headers, styles, the format line: as they were


def test_a_generate_reads_tv_captions_through_the_cleaner_so_the_list_and_the_pick_agree(copy):
    # ENGINE_REVISION 31 / SCHEMA_VERSION 20 (P1.3-1 a): the reading rows are no words in the list either; an arrow
    # still says its row runs on, so that row is never closed as a sentence of its own
    read = analyzer.parse_ass(TV, "ja")
    assert "もんばん" not in read and "ちょうろう" not in read
    assert "門番は城への侵入者を 厳しく取り調べた" in read
    assert "長老の話によれば この村には" in read and "によれば。" not in read
    # the lines and times the pick reads (the original) are the lines and times Anki Miner reads (the copy)
    assert [(c.start, c.end) for c in cues.read(TV, "ja")] == [(c.start, c.end) for c in cues.read(copy, "ja")]


def test_an_srt_is_read_where_it_is(tmp_path):
    srt = os.path.join(RESOURCES, "phrases_sample.srt")
    assert caption_clean.copy_for(srt, str(tmp_path)) == srt
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("content", ["", "[Script Info]\nTitle: x\n", "[Events]\nDialogue: broken"])
def test_a_file_with_no_events_comes_back_as_it_was(content):
    assert caption_clean.clean(content) == content


def test_a_copy_never_overwrites_its_own_subtitle(tmp_path):
    path = tmp_path / "ep.ass"
    path.write_text(open(TV, encoding="utf-8").read(), encoding="utf-8")
    with pytest.raises(ValueError):
        caption_clean.copy_for(str(path), str(tmp_path))
