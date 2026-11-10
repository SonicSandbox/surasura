# SPDX-License-Identifier: GPL-3.0-or-later
"""
Filename slugging, text-header building, date/duration formatting, channel
resolution, and yt-dlp sub-lang pattern generation.
"""
import unittest

from modules.youtube_downloader import downloader as core


class TestSlug(unittest.TestCase):
    def test_strips_ascii_filesystem_invalid(self):
        self.assertEqual(core.slug('A/B:C*?"<>|D'), "ABCD")

    def test_strips_control_chars(self):
        self.assertEqual(core.slug("a\x00b\x1fc"), "abc")

    def test_keeps_unicode_and_fullwidth_punctuation(self):
        self.assertEqual(core.slug("第一話：始まり"), "第一話：始まり")
        self.assertEqual(core.slug("学习中文！"), "学习中文！")

    def test_ascii_colon_stripped_whitespace_collapsed(self):
        self.assertEqual(core.slug("第一話:  始まり"), "第一話 始まり")

    def test_trailing_dots_and_spaces_trimmed(self):
        self.assertEqual(core.slug("  Title...  "), "Title")

    def test_empty_and_only_invalid_become_untitled(self):
        self.assertEqual(core.slug(""), "untitled")
        self.assertEqual(core.slug(None), "untitled")
        self.assertEqual(core.slug('/\\:*?"<>|'), "untitled")

    def test_length_limit(self):
        self.assertEqual(len(core.slug("あ" * 500)), 150)
        self.assertEqual(core.slug("abcdef", limit=3), "abc")


class TestDateAndDuration(unittest.TestCase):
    def test_fmt_date(self):
        self.assertEqual(core._fmt_date("20260101"), "2026-01-01")
        self.assertEqual(core._fmt_date(""), "")
        self.assertEqual(core._fmt_date("2026"), "2026")        # wrong length -> as-is
        self.assertEqual(core._fmt_date("abcdefgh"), "abcdefgh")  # non-digit -> as-is

    def test_duration_prefers_string(self):
        self.assertEqual(core._duration({"duration_string": "1:02:03"}), "1:02:03")

    def test_duration_from_seconds_with_hours(self):
        self.assertEqual(core._duration({"duration": 3723}), "1:02:03")

    def test_duration_from_seconds_minutes_only(self):
        self.assertEqual(core._duration({"duration": 65}), "1:05")

    def test_duration_missing(self):
        self.assertEqual(core._duration({}), "")


class TestChannelOf(unittest.TestCase):
    def test_channel_present(self):
        self.assertEqual(core.channel_of({"channel": "NHK", "uploader": "x"}), "NHK")

    def test_falls_back_to_uploader(self):
        self.assertEqual(core.channel_of({"uploader": "SomeUploader"}), "SomeUploader")

    def test_unknown_when_missing(self):
        self.assertEqual(core.channel_of({}), "Unknown")


class TestBuildText(unittest.TestCase):
    def test_full_header_and_body(self):
        info = {"title": "テスト動画", "channel": "テストCh",
                "webpage_url": "https://youtu.be/abc", "upload_date": "20260101", "duration": 65}
        text = core.build_text(info, "本文です", "Japanese", "manual")
        self.assertIn("テスト動画", text)
        self.assertIn("テストCh | 2026-01-01 | 1:05", text)
        self.assertIn("Captions: Japanese (manual)", text)
        self.assertIn("https://youtu.be/abc", text)
        self.assertTrue(text.rstrip().endswith("本文です"))

    def test_missing_fields_default(self):
        text = core.build_text({}, "body", "English", "native auto")
        self.assertIn("Untitled", text)
        self.assertIn("Unknown", text)

    def test_the_analyzer_reads_back_only_the_cues(self):
        # The header is this module's label, not the video's speech: whatever
        # build_text and clean_vtt_cues write — header, '[00:01:02] ' timestamps, the captions' [音楽] — the
        # analyzer's reader (analyzer.transcript_body / extract_text) must give back the spoken cues alone.
        from app import analyzer
        info = {"title": "『駅前の喫茶店』をゆっくり語っていく", "channel": "ゆっくり雑談ラジオ",
                "webpage_url": "https://www.youtube.com/watch?v=commentary1", "upload_date": "20220222",
                "duration": 807}
        vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n[音楽]\n\n"
               "00:01:02.500 --> 00:01:05.000\n今日は原作の話をしようと思います\n")
        for keep_ts in (False, True):
            lines = [line for line, _sec in core.clean_vtt_cues(vtt, keep_ts)]
            body = "\n".join(lines) if keep_ts else " ".join(lines)
            text = core.build_text(info, body, "Japanese", "native auto")
            spoken = analyzer.strip_text_conventions(text, "ja")
            self.assertEqual(spoken.split(), ["今日は原作の話をしようと思います"], (keep_ts, spoken))


class TestSubLangPatterns(unittest.TestCase):
    def test_japanese(self):
        pats = core.sublang_patterns(core.LANGS["Japanese"]).split(",")
        self.assertIn("ja", pats)
        self.assertIn("ja-orig", pats)
        self.assertIn("ja.*", pats)

    def test_chinese_includes_variants_and_wildcard(self):
        pats = core.sublang_patterns(core.LANGS["Chinese"]).split(",")
        self.assertIn("zh-Hans", pats)
        self.assertIn("zh-Hant", pats)
        self.assertIn("zh-Hans.*", pats)

    def test_lang_by_code_map(self):
        self.assertEqual(core.LANG_BY_CODE["ja"], "Japanese")
        self.assertEqual(core.LANG_BY_CODE["zh"], "Chinese")
        self.assertEqual(core.LANG_BY_CODE["en"], "English")


if __name__ == "__main__":
    unittest.main()
