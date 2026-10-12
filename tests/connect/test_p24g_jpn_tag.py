"""A three-letter language tag on a subtitle (.jpn) is stripped when looking for its video.

Rule: `runner.beside` looks for the video under the subtitle's name without its language
tag, so `Example Show - 05.jpn.srt` finds `Example Show - 05.mkv` on disk. The tag is
allowed to be up to four characters with the dot (.jpn is four), so a three-letter tag
is never mistaken for part of the name.
Mutant: P2.4-E24 (`1 < len(tag) <= 4` becomes `<= 3`, so .jpn is no tag and the video is
missed). What a wrong answer would cost: a finished Connect job would report "no video"
for a three-letter-tagged subtitle and the card would never be made.
"""
from app.connect import runner


def test_a_three_letter_language_tag_is_stripped_to_find_the_video_beside_the_subtitle(tmp_path):
    folder = tmp_path / "Example Show"
    folder.mkdir()
    subtitle = folder / "Example Show - 05.jpn.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\n気配\n", encoding="utf-8")
    video = folder / "Example Show - 05.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    # why: .jpn is four characters with its dot, the longest tag the rule accepts
    assert runner.beside(str(subtitle)) == str(video), "the language tag (.jpn) is no part of the video's name"
