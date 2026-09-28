import os
import sys
import unittest
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.epub_importer import FileImporterApp

class TestFileImporter(unittest.TestCase):
    def setUp(self):
        self.root = MagicMock()
        self.app = FileImporterApp(self.root)

    def test_extract_text_from_generic(self):
        # Create a temp text file
        test_file = "test_sample.txt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Hello World\nLine 2")
        
        text, error = self.app.extract_text_from_generic(test_file)
        self.assertIsNone(error)
        self.assertEqual(text, "Hello World\nLine 2")
        
        os.remove(test_file)

    def test_extract_text_from_srt(self):
        # Extract reads a subtitle exactly as the library does (analyzer.extract_text): the speaker label and
        # its reading go, the ➡ joins its cue to the next, each cue ends with its own mark or 。 — so the .txt it
        # writes says what the .srt says in a tier (it used to keep the label and break at every cue line).
        test_file = "test_sample.srt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\n（三玖(みく)）本当にそう思うの。\n\n"
                    "2\n00:00:05,000 --> 00:00:08,000\n限られた この夏の間に\n少しでも 泳ぎを上達させるために➡\n\n"
                    "3\n00:00:08,000 --> 00:00:10,000\n毎朝 海へ通っていた｡\n")

        text, error = self.app.extract_text_from_file(test_file)
        self.assertIsNone(error)
        self.assertEqual(text, "本当にそう思うの。限られた この夏の間に 少しでも 泳ぎを上達させるために"
                               "毎朝 海へ通っていた｡")

        os.remove(test_file)

    def test_extract_text_from_ass(self):
        # An .ass event's override tags and \N go as the library reads them.
        test_file = "test_sample.ass"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an8}そうだ\\Nお前に話がある\n")

        text, error = self.app.extract_text_from_file(test_file)
        self.assertIsNone(error)
        self.assertEqual(text, "そうだ お前に話がある。")

        os.remove(test_file)

    def test_split_by_length(self):
        # Case 1: Split at boundary within limit
        # limit=10, boundary at 15
        test_text = "0123456789Boundary. Rest of the text."
        chunks = self.app.split_by_length(test_text, 10)
        # It should find the '.' at index 18 (0-indexed)
        # "0123456789Boundary." is 19 chars.
        self.assertEqual(chunks[0], "0123456789Boundary.")
        
        # Case 2: Split at boundary with closing mark
        test_text = "0123456789Boundary!」 Rest of the text."
        chunks = self.app.split_by_length(test_text, 10)
        self.assertEqual(chunks[0], "0123456789Boundary!」")

        # Case 3: No boundary found, force split at limit + 150
        test_text = "A" * 500
        chunks = self.app.split_by_length(test_text, 100)
        self.assertEqual(len(chunks[0]), 250) # 100 + 150

    def test_extract_text_from_file_dispatch(self):
        # Test dispatch for .txt
        test_file = "test_sample.txt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Text Content")
        
        text, error = self.app.extract_text_from_file(test_file)
        self.assertIsNone(error)
        self.assertEqual(text, "Text Content")
        os.remove(test_file)

    def test_extract_text_from_srt_japanese_filter(self):
        # A bilingual cue keeps its Japanese line only, and an English-only cue gives nothing — as in the library.
        test_file = "test_mixed.srt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nこんにちは\nHello\n\n2\n00:00:05,000 --> 00:00:08,000\nOnly English Line")

        text, error = self.app.extract_text_from_file(test_file)
        self.assertIsNone(error)
        self.assertEqual(text, "こんにちは。")

        os.remove(test_file)

    def test_a_subtitle_line_in_cjk_extension_a_or_b_is_kept(self):
        # Extract keeps a subtitle line only when it holds Japanese or Chinese text, by Unicode's own ranges
        # (app/unicode_ranges.py) — the old test stopped at U+9FFF. 㗎 and 𨋢 are Cantonese (Extension A / B), 〇〇 a
        # Japanese placeholder, ㇰ Ainu katakana; a Latin line is still dropped. Extract reads a subtitle as the
        # library does (analyzer.extract_text), so this is the library's line filter too.
        test_file = "test_ranges.srt"
        cues = ("㗎", "𨋢", "〇〇", "ㇰ", "Only English Line")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join(f"{n}\n00:00:0{n},000 --> 00:00:0{n},500\n{cue}" for n, cue in enumerate(cues, 1)))

        text, error = self.app.extract_text_from_file(test_file)
        self.assertIsNone(error)
        for cue in cues[:4]:
            self.assertIn(cue, text)
        self.assertNotIn("English", text)

        os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
