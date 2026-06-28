import os
import sys
import unittest

from bs4 import BeautifulSoup

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.static_html_generator import generate_static_html, OUTPUT_FILE


class TestCompletedFilesFeature(unittest.TestCase):
    """
    Regression tests for the browser-side "Mark Complete" feature on the
    Progressive Learning page (templates/web_app.html).

    The feature is implemented entirely in the static template's JS/CSS, so —
    like the other HTML regression tests — we verify the generated report
    contains the required markers rather than executing the JS. This guards
    against the template losing the wiring or the build pipeline accidentally
    stripping/colliding with it.
    """

    def _generate_and_read(self, theme="default"):
        """Generate the static report and return (raw_html, soup)."""
        generate_static_html(theme=theme)
        self.assertTrue(os.path.exists(OUTPUT_FILE), "Static report was not generated")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return content, BeautifulSoup(content, "html.parser")

    def test_completed_feature_markers_present(self):
        """All the wiring for the browser-side Completed feature must survive generation."""
        content, soup = self._generate_and_read(theme="default")

        # Per-language localStorage key (mirrors the ignored-words pattern)
        self.assertIn("surasura_completed_files_", content,
                      "Per-language completed-files storage key missing")
        self.assertIn("saveCompletedFiles", content, "Completed-files save helper missing")

        # Header button (placed right of the show/hide-all toggle), progressive-only
        self.assertIn("btn-mark-complete", content, "Mark Complete button id missing")
        self.assertIn("toggleCurrentFileComplete", content, "Toggle handler missing")

        # Core behaviors: sidebar marker, auto-advance, in-place target line swap
        self.assertIn("applyCompletedStyle", content, "Sidebar completed-marker helper missing")
        self.assertIn("goToNextIncompleteFile", content, "Auto-advance helper missing")
        self.assertIn("updateTargetDaysForCurrent", content, "Target-days swap helper missing")

        # Visual markers
        self.assertIn("completed-check", content, "Green sidebar check CSS class missing")
        self.assertIn("target-days-box completed", content,
                      "Completed target-days variant class missing")
        self.assertIn("Completed", content, "'Completed' label text missing")

    def test_completed_marker_uses_extension_avoidance(self):
        """
        The green 'X words Completed' line must keep the same anti-extension trick
        (hidden-content + migaku_ignore) the original Target Days line uses, so dictionary
        extensions don't try to parse it.
        """
        content, _ = self._generate_and_read(theme="default")

        # Locate the completed branch and confirm it renders via the hidden-content pattern.
        self.assertIn('data-content="${count} words"', content,
                      "Completed line should render the count via the hidden-content data-content trick")
        self.assertIn('data-content=" Completed"', content,
                      "Completed label should render via the hidden-content data-content trick")

    def test_data_injection_still_intact(self):
        """
        Sanity guard: the new markup must not have broken the generator's data injection
        (it replaces `let globalData = null;` and injects globalLanguage, which the storage
        key depends on). Empty results are fine — we only assert the injection happened.
        """
        content, _ = self._generate_and_read(theme="default")

        self.assertNotIn("let globalData = null;", content,
                         "globalData placeholder was not replaced — injection broke")
        self.assertIn("let globalLanguage =", content,
                      "globalLanguage injection missing — completed storage key would mis-key")

    def test_complete_hotkey_wired(self):
        """The 'c' hotkey must be wired into the keydown handler and listed in the on-page hint."""
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("isComplete", content, "'c' hotkey flag missing from keydown handler")
        self.assertIn("toggleCurrentFileComplete", content, "'c' hotkey action missing")
        self.assertIn("Mark File Complete", content, "'c' hotkey missing from the on-page hint")

    def test_feature_present_across_themes(self):
        """The feature lives in the shared web_app template, so it must appear for non-Zen themes."""
        for theme in ("default", "world-class", "modern-light"):
            with self.subTest(theme=theme):
                content, _ = self._generate_and_read(theme=theme)
                self.assertIn("btn-mark-complete", content,
                              f"Mark Complete button missing for theme '{theme}'")


if __name__ == "__main__":
    unittest.main()
