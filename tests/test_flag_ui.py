import sys
import os
import unittest
import tkinter as tk
from tkinter import ttk

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import MasterDashboardApp

class TestFlagUI(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw() # Hide window
        self.app = MasterDashboardApp(self.root)
        
    def tearDown(self):
        self.root.destroy()

    def test_flag_updates(self):
        # Initial state (should be ja -> 🇯🇵)
        # Note: MasterDashboardApp.__init__ calls update_ui_for_language.
        
        # We need to ensure settings window is created for widget tests
        self.app.create_settings_window()
        
        # Check initial (default ja)
        self.assertEqual(self.app.var_language.get(), "ja")
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇯🇵")
        
        # In 'ja', chk_sanitize_ja should be visible, chk_reinforce_widget should be hidden
        # We check winfo_manager() - it returns 'pack' if managed by pack, '' if not.
        self.assertEqual(self.app.chk_sanitize_ja.winfo_manager(), "pack")
        self.assertEqual(self.app.chk_reinforce_widget.winfo_manager(), "")
        
        # Switch to Chinese
        self.app.var_language.set("zh")
        # Trace handles update_ui_for_language()
        
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇨🇳")
        self.assertEqual(self.app.chk_reinforce_widget.winfo_manager(), "pack")
        self.assertEqual(self.app.chk_sanitize_ja.winfo_manager(), "")
        
        # Verify container nesting
        self.assertEqual(self.app.chk_reinforce_widget.master, self.app.lang_options_frame)
        self.assertEqual(self.app.lang_options_frame.master, self.app.chk_reinforce_widget.winfo_toplevel().children['!labelframe']) # ' Advanced Settings' frame
        
        # Switch back to Japanese
        self.app.var_language.set("ja")
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇯🇵")
        self.assertEqual(self.app.chk_sanitize_ja.winfo_manager(), "pack")
        self.assertEqual(self.app.chk_reinforce_widget.winfo_manager(), "")

if __name__ == '__main__':
    unittest.main()
