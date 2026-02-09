
import unittest
import sys
import os

# Ensure package root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analyzer import JapaneseTokenizer, has_target_language

class TestJapaneseRegression(unittest.TestCase):
    def test_kanji_detection(self):
        text = "これはテストです。"
        self.assertTrue(has_target_language(text, 'ja'))
        self.assertFalse(has_target_language("Hello World", 'ja'))
        # Chinese characters should also trigger JA detection currently as they share Kanji
        # But purely specific checks might differentiate if needed.
        # Current implementation: has_target_language('ja') checks for Kana OR Kanji.
        self.assertTrue(has_target_language("你好", 'ja')) 

    def test_tokenization(self):
        tokenizer = JapaneseTokenizer()
        text = "学校に行きます。"
        tokens = tokenizer.tokenize(text)
        # Expected: 学校, に, 行き, ます, 。
        # Lemmas: 学校, に, 行く, ます, 。
        lemmas = [t[0] for t in tokens]
        self.assertIn("学校", lemmas)
        self.assertIn("行く", lemmas)

if __name__ == '__main__':
    unittest.main()
