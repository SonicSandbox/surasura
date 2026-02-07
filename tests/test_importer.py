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
        # Create a temp srt file
        test_file = "test_sample.srt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nこんにちは (Hello)\n\n2\n00:00:05,000 --> 00:00:08,000\nテスト (Test)")
        
        text, error = self.app.extract_text_from_srt(test_file)
        self.assertIsNone(error)
        self.assertEqual(text.strip(), "こんにちは (Hello)\nテスト (Test)")
        
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
        # Create a temp srt file with mixed English/Japanese
        test_file = "test_mixed.srt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:04,000\nHello (JP: こんにちは)\n\n2\n00:00:05,000 --> 00:00:08,000\nOnly English Line")
        
        text, error = self.app.extract_text_from_srt(test_file)
        self.assertIsNone(error)
        # Should only contain the line with Japanese
        self.assertEqual(text.strip(), "Hello (JP: こんにちは)")
        
        os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
