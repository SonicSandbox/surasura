import sys
import os
import unittest
import tkinter as tk
from tkinter import ttk

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestFlagUI(unittest.TestCase):
    def setUp(self):
        from app.main import MasterDashboardApp
        self.root = tk.Tk()
        self.root.withdraw() # Hide window
        self.app = MasterDashboardApp(self.root)
        
    def tearDown(self):
        self.root.destroy()

    def test_flag_updates(self):
        # Initial state (should be ja -> 🇯🇵)
        # Note: MasterDashboardApp.__init__ calls update_ui_for_language.
        
        # We need to ensure settings window is created for widget tests
        self.app.var_language.set("ja")
        self.app.create_settings_window()
        
        # Check initial (default ja)
        self.assertEqual(self.app.var_language.get(), "ja")
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇯🇵")
        
        # In 'ja', chk_reinforce_widget should be hidden (it is a Chinese-only option).
        # winfo_manager() returns 'pack' if managed by pack, '' if not.
        self.assertEqual(self.app.chk_reinforce_widget.winfo_manager(), "")
        
        # Switch to Chinese
        self.app.var_language.set("zh")
        # Trace handles update_ui_for_language()
        
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇨🇳")
        self.assertEqual(self.app.chk_reinforce_widget.winfo_manager(), "pack")

        # Verify container nesting
        self.assertEqual(self.app.chk_reinforce_widget.master, self.app.lang_options_frame)
        
        # Switch back to Japanese
        self.app.var_language.set("ja")
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇯🇵")
        self.assertEqual(self.app.chk_reinforce_widget.winfo_manager(), "")

    def test_zen_slider_shown_only_for_zen_theme(self):
        """The Zen Limit slider appears only when the Zen Mode theme is selected. Real-root test so
        it exercises the actual <<ComboboxSelected>> binding — guards the regression where the
        theme-SAVE binding replaced the zen-visibility binding (a second bind() without add='+')."""
        def slider_shown():
            return self.app.zen_limit_frame.winfo_manager() == "pack"

        def select(theme):
            self.app.combo_theme.set(theme)
            self.app.combo_theme.event_generate("<<ComboboxSelected>>")
            self.root.update()

        select("Dark Flow")
        self.assertFalse(slider_shown(), "slider must be hidden for a non-Zen theme")
        select("Zen Mode")
        self.assertTrue(slider_shown(), "slider must appear when Zen Mode is selected")
        select("Modern Light")
        self.assertFalse(slider_shown(), "slider must hide again when leaving Zen Mode")

    def test_very_rare_band_hidden_when_identical_to_native(self):
        """The rarity slider drops a redundant band from the collapsed rare tail, keeping the RAREST
        (Native) rather than Very Rare: on a library where Very Rare selects identically to Native,
        Very Rare is hidden (no dead stop) and a Very Rare selection folds into Native. When they
        differ, all six bands are shown."""
        def mk(wc, cov):
            return {"band": "", "word_count": wc, "coverage_percent": cov, "hours_between": 2.0}
        # Very Rare == Native -> hide Very Rare, keep Native.
        self.app._band_previews = {"core": mk(100, 50), "common": mk(200, 75),
                                   "occasional": mk(400, 90), "uncommon": mk(550, 93),
                                   "rare": mk(650, 95), "very_rare": mk(800, 98.7),
                                   "native": mk(800, 98.7)}
        self.app.var_band.set("very_rare")
        self.app._effective_bands = self.app._compute_effective_bands()
        self.app._apply_effective_bands()
        self.assertNotIn("very_rare", self.app._effective_bands)
        self.assertIn("native", self.app._effective_bands)              # Native stays visible
        self.assertEqual(float(self.app.band_slider.cget("to")), 5.0)   # 6 stops (7 bands - hidden Very Rare)
        self.assertEqual(self.app.var_band.get(), "native")            # Very Rare folded into Native

        # Distinct -> all seven shown again.
        self.app._band_previews["very_rare"] = mk(700, 96.7)
        self.assertEqual(len(self.app._compute_effective_bands()), 7)

    def test_preview_line_shows_coverage_words_and_encounter_rate(self):
        """The visible preview line carries all three: coverage %, word count, and the compact
        'every X' encounter rate — while the full sentence stays in the tooltip."""
        self.app._band_previews = {"occasional": {"band": "", "word_count": 400,
                                                  "coverage_percent": 90.0, "hours_between": 2.5}}
        self.app._update_band_preview_labels("occasional")
        line = self.app.var_band_coverage.get()
        self.assertIn("90.0% coverage", line)
        self.assertIn("400 words", line)
        self.assertIn("every ~2.5 hours", line)
        self.assertIn("every ~2.5 hours of immersion", self.app._band_hours_text)  # tooltip intact

    def test_selecting_by_commonness_is_non_blocking(self):
        """The heavy preview compute (store + known words) runs off-thread, so the toggle is
        instant: _refresh_band_preview returns immediately with a 'Calculating…' placeholder; the
        real numbers land later via the GUI queue."""
        self.app.var_band_coverage.set("")
        self.app._refresh_band_preview()
        self.assertEqual(self.app.var_band_coverage.get(), "Calculating…")

    def test_stale_async_preview_result_is_ignored(self):
        """A superseded async refresh (older generation) must not clobber a newer one."""
        self.app._band_previews = "SENTINEL"
        self.app._preview_gen = 5
        self.app._apply_preview_result(3, {"core": {}})     # stale gen 3 < 5 -> ignored
        self.assertEqual(self.app._band_previews, "SENTINEL")
        self.app._apply_preview_result(5, None)             # current gen -> applied
        self.assertIsNone(self.app._band_previews)

    def test_generate_disabled_with_hint_when_library_empty(self):
        """Generate Journey is disabled and shows a short 'add content first' hint when the library
        has no content; enabled with the hint hidden once content exists."""
        from unittest.mock import patch
        with patch.object(self.app, "_library_has_content", return_value=False):
            self.app._update_generate_state()
        self.assertEqual(str(self.app.btn_journey.cget("state")), "disabled")
        self.assertEqual(self.app.lbl_generate_hint.winfo_manager(), "pack", "empty -> hint shown")

        with patch.object(self.app, "_library_has_content", return_value=True):
            self.app._update_generate_state()
        self.assertEqual(str(self.app.btn_journey.cget("state")), "normal")
        self.assertEqual(self.app.lbl_generate_hint.winfo_manager(), "", "content -> hint hidden")

    def test_library_content_collapses_to_one_button(self):
        """Phase 1 of the Content Manager redesign: the main GUI's Library Content shows a single
        'Import Content' button; the YouTube DOWNLOADER moved into the Content Manager
        (btn_youtube is None) while the ▷ Preview button stays on the main page."""
        def walk(widget, out):
            for c in widget.winfo_children():
                out.append(c); walk(c, out)
        allw = []
        walk(self.root, allw)
        libframe = next((w for w in allw if isinstance(w, ttk.LabelFrame)
                         and "Library Content" in w.cget("text")), None)
        self.assertIsNotNone(libframe, "Library Content frame should exist")
        buttons = [w.cget("text") for w in libframe.winfo_children() if isinstance(w, ttk.Button)]
        self.assertEqual(buttons, ["Import Content"], "exactly one content button on the main GUI")
        self.assertIsNone(self.app.btn_youtube, "the YouTube downloader button is no longer on main")
        self.assertIsNotNone(self.app.btn_preview, "the Preview button stays on the main GUI")

if __name__ == '__main__':
    unittest.main()
