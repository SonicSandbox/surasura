# SPDX-License-Identifier: GPL-3.0-or-later
"""
Caption-resolution priority + multi-language coverage.

Order under test: manual subtitles -> native auto -> auto-translation (preferring
the video's original source language), else nothing.
"""
import unittest

from modules.youtube_downloader import downloader as core

JA = core.LANGS["Japanese"]
ZH = core.LANGS["Chinese"]
EN = core.LANGS["English"]


def vtt(): return [{"ext": "vtt"}]


class TestResolveCaption(unittest.TestCase):
    def test_manual_beats_everything(self):
        info = {"subtitles": {"ja": vtt()},
                "automatic_captions": {"ja": vtt(), "ja-en": vtt()}}
        self.assertEqual(core.resolve_caption(info, JA), ("ja", "manual"))

    def test_native_auto_when_no_manual(self):
        info = {"subtitles": {}, "automatic_captions": {"ja": vtt()}}
        self.assertEqual(core.resolve_caption(info, JA), ("ja", "native auto"))

    def test_secondary_native_code_used(self):
        # 'ja' absent but 'ja-orig' present as manual
        info = {"subtitles": {"ja-orig": vtt()}, "automatic_captions": {}}
        self.assertEqual(core.resolve_caption(info, JA), ("ja-orig", "manual"))

    def test_auto_translation_prefers_source_language(self):
        # Original language Korean -> prefer the ja-ko translation over ja-en
        info = {"subtitles": {}, "language": "ko",
                "automatic_captions": {"ja-en": vtt(), "ja-ko": vtt()}}
        self.assertEqual(core.resolve_caption(info, JA), ("ja-ko", "auto-translated"))

    def test_auto_translation_fallback_sorted(self):
        # No source-language match -> first sorted ja-* translation
        info = {"subtitles": {}, "language": "ru",
                "automatic_captions": {"ja-fr": vtt(), "ja-en": vtt()}}
        code, kind = core.resolve_caption(info, JA)
        self.assertEqual(kind, "auto-translated")
        self.assertEqual(code, "ja-en")  # 'ja-en' < 'ja-fr'

    def test_translation_without_known_source_language(self):
        info = {"subtitles": {}, "automatic_captions": {"ja-en": vtt()}}
        self.assertEqual(core.resolve_caption(info, JA), ("ja-en", "auto-translated"))

    def test_nothing_available(self):
        info = {"subtitles": {}, "automatic_captions": {"ko": vtt(), "fr": vtt()}}
        self.assertEqual(core.resolve_caption(info, JA), (None, None))

    def test_missing_dicts_are_safe(self):
        self.assertEqual(core.resolve_caption({}, JA), (None, None))
        self.assertEqual(core.resolve_caption({"subtitles": None, "automatic_captions": None}, JA), (None, None))


class TestResolveCaptionChinese(unittest.TestCase):
    def test_zh_hans_manual(self):
        info = {"subtitles": {"zh-Hans": vtt()}, "automatic_captions": {}}
        self.assertEqual(core.resolve_caption(info, ZH), ("zh-Hans", "manual"))

    def test_zh_hant_when_hans_absent(self):
        info = {"subtitles": {"zh-Hant": vtt()}, "automatic_captions": {}}
        self.assertEqual(core.resolve_caption(info, ZH), ("zh-Hant", "manual"))

    def test_zh_auto_translation_prefix(self):
        info = {"subtitles": {}, "language": "en",
                "automatic_captions": {"zh-Hans-en": vtt()}}
        code, kind = core.resolve_caption(info, ZH)
        self.assertEqual(kind, "auto-translated")
        self.assertTrue(code.startswith("zh-Hans"))


class TestResolveCaptionEnglish(unittest.TestCase):
    def test_en_variants(self):
        info = {"subtitles": {"en-GB": vtt()}, "automatic_captions": {}}
        self.assertEqual(core.resolve_caption(info, EN), ("en-GB", "manual"))

    def test_en_native_auto(self):
        info = {"subtitles": {}, "automatic_captions": {"en": vtt()}}
        self.assertEqual(core.resolve_caption(info, EN), ("en", "native auto"))


if __name__ == "__main__":
    unittest.main()
