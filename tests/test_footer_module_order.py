"""The dashboard footer's button order: [flag] 悟 🎬 順 ⚙.

Settings (⚙) is always the right-most button, and the optional module buttons sit to its left in one
fixed order however many are switched on and in whatever order they were switched on. Before, ⚙ was
packed first and each module appended after it, so the order depended on when a toggle happened.

The placement is decided by MasterDashboardApp._module_slot (which widget to pack a module button
BEFORE). It is exercised on real widgets here — packing order is a Tk fact, not something a mock can
show — using one Tk root for the file (testing.md §5.4).
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    from tkinter import ttk
    _ROOT = tk.Tk()
    _ROOT.withdraw()
except Exception:   # no display
    _ROOT = None


@unittest.skipIf(_ROOT is None, "no display")
class TestFooterModuleOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.main import MasterDashboardApp
        cls.Dash = MasterDashboardApp

    def setUp(self):
        self.box = ttk.Frame(_ROOT)
        flag = ttk.Label(self.box, text="JP")
        flag.pack(side=tk.LEFT)
        self.app = SimpleNamespace(_MODULE_BUTTONS=self.Dash._MODULE_BUTTONS)
        self.app.btn_settings = ttk.Button(self.box, text="⚙")
        self.app.btn_settings.pack(side=tk.LEFT)
        self.app.btn_satori = ttk.Button(self.box, text="悟")
        self.app.btn_reels = ttk.Button(self.box, text="🎬")
        self.app.btn_junban = ttk.Button(self.box, text="順")
        self.flag = flag

    def tearDown(self):
        self.box.destroy()

    def _show(self, name):
        btn = getattr(self.app, name)
        btn.pack(side=tk.LEFT, before=self.Dash._module_slot(self.app, btn))

    def _order(self):
        return [w.cget("text") for w in self.box.pack_slaves()]

    def test_settings_stays_rightmost_with_junban_directly_left_of_it(self):
        self._show("btn_satori")
        self._show("btn_junban")
        self.assertEqual(self._order(), ["JP", "悟", "順", "⚙"])

    def test_the_order_is_fixed_whatever_order_modules_are_switched_on(self):
        """Switching Junban on before Reels must not put 順 left of 🎬."""
        self._show("btn_junban")
        self._show("btn_reels")
        self._show("btn_satori")
        self.assertEqual(self._order(), ["JP", "悟", "🎬", "順", "⚙"])

    def test_hiding_a_module_and_showing_it_again_returns_it_to_its_place(self):
        for name in ("btn_satori", "btn_reels", "btn_junban"):
            self._show(name)
        self.app.btn_reels.pack_forget()
        self.assertEqual(self._order(), ["JP", "悟", "順", "⚙"])
        self._show("btn_reels")
        self.assertEqual(self._order(), ["JP", "悟", "🎬", "順", "⚙"])

    def test_no_modules_leaves_settings_alone_on_the_right(self):
        self.assertEqual(self._order(), ["JP", "⚙"])


if __name__ == "__main__":
    unittest.main()
