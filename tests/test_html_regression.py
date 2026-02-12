import os
import sys
import unittest
import pytest
from bs4 import BeautifulSoup

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.static_html_generator import generate_static_html

class TestHTMLRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We'll generate the reports once for performance, or as needed.
        # But for parameterized-like behavior in unittest, we'll do it in methods.
        cls.results_dir = os.path.join(os.getcwd(), "results")
        if not os.path.exists(cls.results_dir):
            os.makedirs(cls.results_dir)

    def _verify_html(self, theme, zen_limit=None):
        """Helper to generate and parse HTML"""
        generate_static_html(theme=theme, zen_limit=zen_limit)
        report_path = os.path.join(self.results_dir, "reading_list_static.html")
        with open(report_path, "r", encoding="utf-8") as f:
            return BeautifulSoup(f.read(), "html.parser")

    def test_zen_mode_regression(self):
        """Verify Zen Mode specific requirements"""
        soup = self._verify_html(theme="Zen Mode", zen_limit=50)
        content = str(soup)

        # 1. Header and Layout
        self.assertIn('zen-header', content, "Zen Header missing")
        self.assertIn('comprehension-stats', content, "Comprehension Stats missing in Zen Mode")
        self.assertIn('file-section-wrapper', content, "Per-file wrapper missing")
        
        # 2. CSS Properties
        # Checking for the presence of specific styles (Session 12/14)
        style_text = soup.find('style').string
        self.assertIn('position: sticky', style_text)
        self.assertIn('top: 0', style_text)
        self.assertIn('background: #000', style_text) # Solid black header
        self.assertIn('content-visibility: auto', style_text)
        self.assertIn('cursor: default', style_text)
        self.assertIn('user-select: none', style_text)
        self.assertIn('caret-color: transparent', style_text)

        # 3. Reading Obfuscation (Session 8/9/12)
        # Check that readings use the attribute trick
        self.assertIn('unicode-bidi: bidi-override', style_text)
        self.assertIn('content: attr(data-content)', style_text)
        
        # Ensure 'data-reading' attribute is NOT on the span itself (Session 8 fix)
        # Note: We check for the raw attribute name in the string to be thorough
        reading_spans = soup.find_all('span', class_='reading')
        for span in reading_spans:
            self.assertFalse(span.has_attr('data-reading'), "data-reading attribute should not leak on span")
            self.assertTrue(span.has_attr('data-content'), "data-content attribute should exist for CSS display")
            self.assertIn('migaku_ignore', span.attrs, "migaku_ignore missing")

    def test_world_class_theme_regression(self):
        """Verify World Class (Dark Flow) theme requirements"""
        soup = self._verify_html(theme="world-class")
        content = str(soup)

        # 1. Theme Class
        self.assertIn('theme-world-class', content, "theme-world-class class missing")
        
        # 2. Selection behavior (Should NOT have user-select: none on everything like Zen)
        # But should have caret-color transparent (Session 14)
        style_text = soup.find('style').string
        self.assertIn('caret-color: transparent', style_text)
        
        # Verify Zen-specific classes are NOT present
        self.assertNotIn('zen-header', content)

    def test_default_dark_theme_regression(self):
        """Verify Default (Dark) theme requirements"""
        soup = self._verify_html(theme="default")
        content = str(soup)

        # Verify dark mode root variables exist in CSS
        style_text = soup.find('style').string
        self.assertIn('--background: #121212', style_text)
        self.assertIn('--surface: #1e1e1e', style_text)
        self.assertIn('caret-color: transparent', style_text)

    def test_html_cleanliness(self):
        """Verify the HTML doesn't contain malformed comments or garbage"""
        # Testing across the default theme
        soup = self._verify_html(theme="default")
        content = str(soup)
        
        self.assertNotIn('< !--', content, "Malformed HTML comments found")
        self.assertNotIn('obfReading', content, "Undefined obfReading variable leak")

if __name__ == '__main__':
    unittest.main()
