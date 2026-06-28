import os
import sys
import unittest

from bs4 import BeautifulSoup

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.static_html_generator import generate_static_html, OUTPUT_FILE


class TestSortFilterFeature(unittest.TestCase):
    """
    Regression tests for the browser-side "Show" priority filter on the Progressive
    Learning page (templates/web_app.html).

    Like the other HTML regression tests, the feature is pure template JS/CSS, so we
    verify the generated report carries the required markers/wiring rather than executing
    the JS (the suite has no browser engine).
    """

    def _generate_and_read(self, theme="default"):
        generate_static_html(theme=theme)
        self.assertTrue(os.path.exists(OUTPUT_FILE), "Static report was not generated")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
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
