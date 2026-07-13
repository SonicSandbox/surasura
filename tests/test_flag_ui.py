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

    def test_native_band_hidden_when_identical_to_very_rare(self):
        """The rarity slider drops a redundant trailing band: on a library where Native selects
        identically to Very Rare, Native is hidden (no dead stop), and a Native selection folds
        into Very Rare. When they differ, all six bands are shown."""
        def mk(wc, cov):
            return {"band": "", "word_count": wc, "coverage_percent": cov, "hours_between": 2.0}
        # Native == Very Rare -> hidden.
        self.app._band_previews = {"core": mk(100, 50), "common": mk(200, 75),
                                   "occasional": mk(400, 90), "rare": mk(600, 94),
                                   "very_rare": mk(800, 98.7), "native": mk(800, 98.7)}
        self.app.var_band.set("native")
        self.app._effective_bands = self.app._compute_effective_bands()
        self.app._apply_effective_bands()
        self.assertNotIn("native", self.app._effective_bands)
        self.assertEqual(float(self.app.band_slider.cget("to")), 4.0)   # 5 stops, not 6
        self.assertEqual(self.app.var_band.get(), "very_rare")          # Native folded in

        # Distinct -> all six shown again.
        self.app._band_previews["very_rare"] = mk(700, 96.7)
        self.assertEqual(len(self.app._compute_effective_bands()), 6)

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

if __name__ == '__main__':
    unittest.main()
