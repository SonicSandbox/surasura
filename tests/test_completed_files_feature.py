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

    _CACHE = {}

    def _generate_and_read(self, theme="default"):
        """Generate the static report and return (raw_html, soup).

        Cached per theme: every assertion here is on template WIRING, which doesn't vary with the
        data, and rendering a real-sized library costs seconds each time."""
        if theme not in self._CACHE:
            generate_static_html(theme=theme)
            self.assertTrue(os.path.exists(OUTPUT_FILE), "Static report was not generated")
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                self._CACHE[theme] = f.read()
        content = self._CACHE[theme]
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

    # --- Collapsible "Completed" sidebar section ------------------------------------------------ #
    def test_completed_section_wiring_present(self):
        """Files you've marked complete collapse into their own section instead of staying in the
        middle of the sidebar — the whole point is to stop scrolling past finished episodes."""
        content, _ = self._generate_and_read(theme="default")

        for marker in ("buildCompletedSection", "applyCompletedSectionState",
                       "toggleCompletedSection", "moveTabToCompletedSection", "isItemCompleted"):
            self.assertIn(marker, content, f"Completed-section helper '{marker}' missing")

        self.assertIn("completed-section-header", content, "Section header class/id missing")
        self.assertIn("completed-section-body", content, "Section body id missing")
        self.assertIn("surasura_completed_collapsed_", content,
                      "Per-language collapsed-state storage key missing")

    def test_completed_section_defaults_to_collapsed(self):
        """Collapsed by default — an expanded default would defeat the feature."""
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("let completedCollapsed = true;", content,
                      "The Completed section must start collapsed")

    def test_completed_section_is_built_at_the_top_of_the_sidebar(self):
        """The section renders BEFORE the active list, so finished files sit above rather than
        below. Two things have to follow from that and are asserted here."""
        content, _ = self._generate_and_read(theme="default")

        build_at = content.index("buildCompletedSection(tabsContainer, doneList);")
        render_at = content.index("setupInfiniteScroll(tabsContainer, activeList")
        self.assertLess(build_at, render_at,
                        "the Completed section must be built before the active list is rendered")

        # 1. Opening the report must not land on a completed (and collapsed) file.
        self.assertIn("!t.closest('#completed-section')", content,
                      "initial tab selection must skip the Completed section")
        # 2. Un-marking appends to the END of the active list (the section is the FIRST child now).
        self.assertIn("tabsContainer.insertBefore(tab, after || null);", content,
                      "un-marking must fall back to appending, not inserting before the section")

    def test_sidebar_partitions_completed_out_of_the_active_list(self):
        """The split happens on the DATA (activeList/doneList) before rendering, not by hiding DOM
        nodes afterwards — otherwise the >500-file infinite scroll interleaves the two sections."""
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("const doneList = fileList.filter(isItemCompleted);", content,
                      "Completed files must be partitioned out of the data before rendering")
        self.assertIn("setupInfiniteScroll(tabsContainer, activeList", content,
                      "Infinite scroll must page the ACTIVE list, not the full file list")

    def test_unmarking_restores_original_sidebar_position(self):
        """Un-marking must put a file back where it was, not at the top or bottom."""
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("tab.dataset.order = item._order", content,
                      "Sidebar tabs must record their natural position for restore-on-unmark")

    def test_target_met_section_is_untouched(self):
        """The analysis-derived 'Target Met' list is a DIFFERENT concept from manual completion and
        must keep its own divider."""
        content, _ = self._generate_and_read(theme="default")
        self.assertIn("Target Met", content, "Analysis-derived 'Target Met' divider was removed")
        self.assertIn("target-met-inline", content, "'Target met ✓' tab label was removed")


if __name__ == "__main__":
    unittest.main()
