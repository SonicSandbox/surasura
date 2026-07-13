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

if __name__ == '__main__':
    unittest.main()
