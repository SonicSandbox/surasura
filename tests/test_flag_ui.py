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
        # Note: setup_ui sets initial state.
        # But wait, MasterDashboardApp.__init__ calls setup_ui then update_ui_for_language.
        
        # Check initial (default ja)
        self.assertEqual(self.app.var_language.get(), "ja")
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇯🇵")
        
        # Switch to Chinese
        self.app.var_language.set("zh")
        # update_ui_for_language is traced? 
        # In __init__: self.var_language.trace_add("write", lambda *args: self.update_ui_for_language())
        # So setting the var should trigger the update.
        # However, trace callbacks might be async or require mainloop step in some environments, 
        # but usually in simple scripts it happens immediately on set().
        # Let's verify if we need to manually call it or if trace works.
        # To be safe and test the logic specifically, we can also call it manually if trace fails in test env.
        self.app.update_ui_for_language() 
        
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇨🇳")
        
        # Switch back to Japanese
        self.app.var_language.set("ja")
        self.app.update_ui_for_language()
        self.assertEqual(self.app.lbl_flag.cget("text"), "🇯🇵")

if __name__ == '__main__':
    unittest.main()
