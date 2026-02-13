import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from app.analyzer import load_known_words, JapaneseTokenizer

class TestUnicodeSafety(unittest.TestCase):
    def setUp(self):
        self.tokenizer = JapaneseTokenizer()

    def test_load_known_words_unicode_path(self):
        """Verify that load_known_words handles non-ASCII characters in its print path."""
        # Use a path with the problematic character '悟'
        unicode_path = os.path.join("temp_dir_悟", "KnownWord.json")
        
        # Mock os.path.exists to avoid actual file IO
        with patch("os.path.exists", return_value=False):
            # This should not raise UnicodeEncodeError even if the console encoding is limited
            # (though in the test environment it usually won't be, the try-except defends it)
            load_known_words(unicode_path, self.tokenizer)

    def test_print_safety_in_load_known_words(self):
        """Verify the try-except block specifically handles UnicodeEncodeError in print."""
        unicode_path = "path/with/悟.json"
        
        # Record if the fallback print was called
        captured_output = []
        def mock_print(msg):
            captured_output.append(msg)
            if "悟" in str(msg):
                raise UnicodeEncodeError('charmap', msg, 0, 1, 'character maps to <undefined>')

        with patch("os.path.exists", return_value=False), \
             patch("builtins.print", side_effect=mock_print):
            
            # This call should succeed because the try-except in load_known_words catches the error
            load_known_words(unicode_path, self.tokenizer)
            
            # Verify the fallback message was printed
            self.assertIn("Loading known words (path contains non-ASCII characters)...", captured_output)

    def test_print_safety_pattern_standalone(self):
        """Verify the try-except pattern works as expected standalone."""
        def safe_print(msg):
            try:
                print(msg)
            except UnicodeEncodeError:
                print("Fallback message")

        captured_output = []
        def mock_print(msg):
            if "悟" in str(msg):
                raise UnicodeEncodeError('charmap', str(msg), 0, 1, 'error')
            captured_output.append(msg)

        with patch("builtins.print", side_effect=mock_print):
            safe_print("Safe message")
            safe_print("Message with 悟")
            
        self.assertIn("Safe message", captured_output)
        self.assertIn("Fallback message", captured_output)

if __name__ == "__main__":
    unittest.main()
