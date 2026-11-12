# SPDX-License-Identifier: GPL-3.0-or-later
"""
Edge-case coverage for clean_vtt — the WebVTT → clean-text converter.

Uses real Japanese / Chinese caption text (per the Surasura testing standard) so
encoding, inline tags, and the auto-caption roll-up dedupe are exercised on actual
language data, not ASCII placeholders.
"""
import unittest

from modules.youtube_downloader import downloader as core


# Auto-generated Japanese captions: rolled-up duplicate cues + inline tags + entities.
VTT_JA = """WEBVTT
Kind: captions
Language: ja

00:00:01.000 --> 00:00:03.000
今日はいい天気ですね

00:00:03.000 --> 00:00:05.000
今日はいい天気ですね

00:00:05.500 --> 00:00:08.000
公園で<c>散歩</c>しましょう&nbsp;ね
"""

# Chinese manual captions across cues.
VTT_ZH = """WEBVTT

00:00:00.000 --> 00:00:02.000
你好世界

00:00:02.000 --> 00:00:04.000
今天我们学习中文
"""


class TestCleanVttHappyPath(unittest.TestCase):
    def test_japanese_dedupe_and_tag_strip(self):
        # Adjacent duplicate cue collapses; <c> tags removed; &nbsp; -> a regular (kept) space.
        lines = core.clean_vtt(VTT_JA, keep_timestamps=False)
        self.assertEqual(lines, ["今日はいい天気ですね", "公園で散歩しましょう ね"])

    def test_japanese_exact_lines(self):
        # &nbsp; becomes a regular space; the <c> tag is removed.
        lines = core.clean_vtt(VTT_JA)
        self.assertEqual(lines[0], "今日はいい天気ですね")
        self.assertIn("公園で散歩しましょう", lines[1])
        self.assertNotIn("<c>", lines[1])
        self.assertNotIn("&nbsp;", lines[1])

    def test_keep_timestamps_prefixes_first_cue(self):
        lines = core.clean_vtt(VTT_JA, keep_timestamps=True)
        self.assertTrue(lines[0].startswith("[00:00:01] "))
        # Fractional seconds are dropped from the [HH:MM:SS] stamp
        self.assertNotIn(".000", lines[0])

    def test_chinese_lines(self):
        lines = core.clean_vtt(VTT_ZH)
        self.assertEqual(lines, ["你好世界", "今天我们学习中文"])


class TestCleanVttEdgeCases(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(core.clean_vtt(""), [])

    def test_only_header(self):
        self.assertEqual(core.clean_vtt("WEBVTT\n\n"), [])

    def test_metadata_lines_dropped(self):
        raw = "WEBVTT\nKind: captions\nLanguage: ja\nNOTE this is a note\n\n" \
              "00:00:01.000 --> 00:00:02.000\nやあ\n"
        self.assertEqual(core.clean_vtt(raw), ["やあ"])

    def test_numeric_cue_numbers_dropped(self):
        raw = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nこんにちは\n\n2\n00:00:02.000 --> 00:00:03.000\nさようなら\n"
        self.assertEqual(core.clean_vtt(raw), ["こんにちは", "さようなら"])

    def test_crlf_line_endings(self):
        raw = "WEBVTT\r\n\r\n00:00:01.000 --> 00:00:02.000\r\nテスト\r\n"
        self.assertEqual(core.clean_vtt(raw), ["テスト"])

    def test_only_consecutive_duplicates_collapse(self):
        # Non-adjacent repeats are preserved; only adjacent roll-up duplicates collapse.
        raw = ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nはい\n\n"
               "00:00:02.000 --> 00:00:03.000\nはい\n\n"
               "00:00:03.000 --> 00:00:04.000\nいいえ\n\n"
               "00:00:04.000 --> 00:00:05.000\nはい\n")
        self.assertEqual(core.clean_vtt(raw), ["はい", "いいえ", "はい"])

    def test_inline_position_tags_removed(self):
        raw = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000 align:start position:0%\n<00:00:01.500>もう<c>すぐ</c>\n"
        out = core.clean_vtt(raw)
        self.assertEqual(out, ["もうすぐ"])

    def test_blank_and_whitespace_lines_ignored(self):
        raw = "WEBVTT\n\n   \n00:00:01.000 --> 00:00:02.000\n  間  \n"
        self.assertEqual(core.clean_vtt(raw), ["間"])


if __name__ == "__main__":
    unittest.main()
