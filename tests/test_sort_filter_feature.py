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


class TestSortFilterFeature(unittest.TestCase):
    """
    Regression tests for the browser-side "Show" priority filter on the Progressive
    Learning page (templates/web_app.html).

    Like the other HTML regression tests, the feature is pure template JS/CSS, so we
    verify the generated report carries the required markers/wiring rather than executing
    the JS (the suite has no browser engine).
    """

    _CACHE = {}

    @classmethod
    def setUpClass(cls):
        """Render a one-word fixture library, not the developer's real one.

        The generator's RESULTS_DIR/OUTPUT_FILE are module constants resolved at IMPORT time, so no
        environment fixture reaches them — they have to be patched. Left alone, these assertions
        rendered the real library and held every theme in _CACHE for the whole session."""
        cls._tmp = tempfile.mkdtemp(prefix="surasura_sort_filter_")
        results = os.path.join(cls._tmp, "results")
        os.makedirs(results)

        pd.DataFrame([
            {"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 30,
             "Occurrences": 3, "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0,
             "Sources": "a_novel.txt", "Context 1": "彼は毎日冒険に出かけます。"},
        ]).to_csv(os.path.join(results, "priority_learning_list.csv"),
                  index=False, encoding="utf-8-sig")

        cls._patches = [
            patch("app.static_html_generator.RESULTS_DIR", results),
            patch("app.static_html_generator.PRIORITY_CSV",
                  os.path.join(results, "priority_learning_list.csv")),
            patch("app.static_html_generator.PROGRESSIVE_CSV",
                  os.path.join(results, "progressive_learning_list.csv")),
            patch("app.static_html_generator.OUTPUT_FILE",
                  os.path.join(results, "reading_list_static.html")),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        cls._CACHE.clear()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _generate_and_read(self, theme="default"):
        """Cached per theme: these assertions are on template WIRING, which doesn't vary with the
        data."""
        # Imported here so the patched module constants are picked up.
        from app.static_html_generator import generate_static_html, OUTPUT_FILE
        if theme in self._CACHE:
            return self._CACHE[theme], BeautifulSoup(self._CACHE[theme], "html.parser")
        generate_static_html(theme=theme)
        self.assertTrue(os.path.exists(OUTPUT_FILE), "Static report was not generated")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        self._CACHE[theme] = content
        return content, BeautifulSoup(content, "html.parser")

    def test_filter_markers_present(self):
        """All wiring for the Show/priority filter must survive generation."""
        content, _ = self._generate_and_read(theme="default")

        # Toolbar button + menu
        self.assertIn("btn-sort-filter", content, "Sort/filter button id missing")
        self.assertIn("toggleSortMenu", content, "Sort menu toggle handler missing")
        self.assertIn("sort-menu", content, "Sort menu container/class missing")
        self.assertIn("Show:", content, "Menu 'Show:' header missing")

        # Three options
        self.assertIn('data-filter="all"', content, "'All' filter option missing")
        self.assertIn('data-filter="priority"', content, "'Priority' filter option missing")
        self.assertIn('data-filter="non-priority"', content, "'Non-priority' filter option missing")

        # State + application logic
        self.assertIn("globalPriorityFilter", content, "Filter state variable missing")
        self.assertIn("setPriorityFilter", content, "Filter setter missing")
        self.assertIn("applyPriorityFilter", content, "Filter application helper missing")

        # CSS hooks that actually hide cards
        self.assertIn("filter-priority", content, "filter-priority CSS hook missing")
        self.assertIn("filter-non-priority", content, "filter-non-priority CSS hook missing")
        self.assertIn("is-priority", content, "is-priority card class missing")

    def test_star_uses_existing_priority_marker(self):
        """
        The menu's star must reuse the same ✦ 'marker-priority' element shown on cards, so
        the menu icon and the card classification stay visually and logically consistent.
        """
        content, _ = self._generate_and_read(theme="default")
        # Menu options render the gold star via the existing marker-priority span
        self.assertIn('class="priority-marker marker-priority"', content,
                      "Menu star should reuse the marker-priority element")

    def test_priority_classification_intact_after_refactor(self):
        """
        The ✦/⚖ marker logic was hoisted out of the card template to also drive the filter.
        Both markers and their tooltips must still be emitted by the card builder.
        """
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("marker-lopsided", content, "Lopsided (⚖) marker logic missing")
        self.assertIn("marker-priority", content, "Priority (✦) marker logic missing")
        self.assertIn("High Leverage", content, "Priority tooltip text missing")
        self.assertIn("Lopsided", content, "Lopsided tooltip text missing")

    def test_sort_hotkey_wired(self):
        """The 's' hotkey must cycle the filter (via the keydown handler) and appear in the hint."""
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("isSort", content, "'s' hotkey flag missing from keydown handler")
        self.assertIn("cyclePriorityFilter", content, "'s' hotkey cycle helper missing")
        self.assertIn("Cycle Show Filter", content, "'s' hotkey missing from the on-page hint")

    def test_filter_present_across_themes(self):
        """The filter lives in the shared web_app template — present for non-Zen themes."""
        for theme in ("default", "world-class", "modern-light"):
            with self.subTest(theme=theme):
                content, _ = self._generate_and_read(theme=theme)
                self.assertIn("btn-sort-filter", content,
                              f"Sort/filter button missing for theme '{theme}'")


if __name__ == "__main__":
    unittest.main()
