"""Template-wiring regressions in the generated report (themes, CSS, reading obfuscation).

Self-contained: renders a two-word fixture library into a temp results dir. It used to render
whatever was in the developer's real `results/` — found via os.getcwd(), which no fixture reaches —
and hold every rendered theme in a class-level cache for the whole session. On a real library that
is tens of megabytes per cached report, retained until the process exits, and the cost scaled with
whoever happened to be running it. The cache is kept (these are wiring assertions, so re-rendering
per test is waste) but it now holds small documents.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from bs4 import BeautifulSoup

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestHTMLRegression(unittest.TestCase):

    _CACHE = {}

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="surasura_html_regression_")
        cls.results_dir = os.path.join(cls._tmp, "results")
        os.makedirs(cls.results_dir)

        # Real Japanese, per docs/agent instructions/testing.md — a reading is needed for the
        # obfuscation assertions, and two words exercise the per-word render loop.
        pd.DataFrame([
            {"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 30,
             "Occurrences": 3, "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0,
             "Sources": "a_novel.txt", "Context 1": "彼は毎日冒険に出かけます。"},
            {"Word": "図書館", "Reading": "トショカン", "Tier": "Outside", "Score": 12,
             "Occurrences": 2, "Count (High)": 2, "Count (Low)": 0, "Count (Goal)": 0,
             "Sources": "a_novel.txt", "Context 1": "図書館で勉強しました。"},
        ]).to_csv(os.path.join(cls.results_dir, "priority_learning_list.csv"),
                  index=False, encoding="utf-8-sig")

        # PROGRESSIVE_CSV is pointed at a path that doesn't exist; the generator guards on
        # os.path.exists, and none of the assertions here need the per-file view's data.
        cls._patches = [
            patch("app.static_html_generator.RESULTS_DIR", cls.results_dir),
            patch("app.static_html_generator.PRIORITY_CSV",
                  os.path.join(cls.results_dir, "priority_learning_list.csv")),
            patch("app.static_html_generator.PROGRESSIVE_CSV",
                  os.path.join(cls.results_dir, "progressive_learning_list.csv")),
            patch("app.static_html_generator.OUTPUT_FILE",
                  os.path.join(cls.results_dir, "reading_list_static.html")),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        cls._CACHE.clear()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _verify_html(self, theme, zen_limit=None):
        """Helper to generate and parse HTML.

        Cached per (theme, zen_limit): these are template-wiring assertions, and they don't vary
        with the data."""
        # Imported here so the patched module constants are picked up.
        from app.static_html_generator import generate_static_html, OUTPUT_FILE
        key = (theme, zen_limit)
        if key in self._CACHE:
            content = self._CACHE[key]
        else:
            generate_static_html(theme=theme, zen_limit=zen_limit)
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            self._CACHE[key] = content

        # Runtime validation: Ensure theme token injected into JS has no spaces (DOMTokenList requirement)
        import re
        match = re.search(r"let globalTheme\s*=\s*'([^']+)';", content)
        if match:
            injected_theme = match.group(1)
            self.assertFalse(' ' in injected_theme,
                             f"Theme token '{injected_theme}' contains spaces, which breaks classList.add in the browser.")

        return BeautifulSoup(content, "html.parser")

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
