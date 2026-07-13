"""Tests for _update_zen_visibility in app.main: the Zen Limit slider is only shown when the Zen
Mode theme is selected (it has no effect on any other theme).

Mirrors the headless visibility-test pattern in test_youtube_toggle.py — tkinter is mocked and the
method is invoked unbound against a spec'd MagicMock, so we assert the pack / pack_forget logic
without a real Tk display.
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib


class TestZenSliderVisibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_modules = set(sys.modules.keys())
        cls.patcher = patch.dict(sys.modules, {
            'tkinter': MagicMock(),
            'tkinter.ttk': MagicMock(),
            'tkinter.messagebox': MagicMock(),
            'app.path_utils': MagicMock(),
            'app.update_checker': MagicMock(),
            'app.onboarding_gui': MagicMock(),
        })
        cls.patcher.start()
        try:
            import app.main
            importlib.reload(app.main)
            cls.MasterDashboardApp = app.main.MasterDashboardApp
        except ImportError:
            cls.MasterDashboardApp = None

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        for mod in set(sys.modules.keys()) - cls._original_modules:
            sys.modules.pop(mod, None)
        sys.modules.pop('app.main', None)

    def setUp(self):
        if self.MasterDashboardApp is None:
            self.skipTest("app.main could not be imported")
        self.app = MagicMock(spec=self.MasterDashboardApp)
        self.app.zen_limit_frame = MagicMock()
        self.app.journey_row = MagicMock()
        self.app.combo_theme = MagicMock()
        self.app.zen_limit_frame.winfo_ismapped.return_value = False

    def test_shown_when_zen_mode_selected(self):
        self.app.combo_theme.get.return_value = "Zen Mode"
        self.MasterDashboardApp._update_zen_visibility(self.app)
        self.app.zen_limit_frame.pack.assert_called()          # slider revealed
        self.app.zen_limit_frame.pack_forget.assert_not_called()

    def test_hidden_for_a_non_zen_theme(self):
        self.app.combo_theme.get.return_value = "Dark Flow"
        self.MasterDashboardApp._update_zen_visibility(self.app)
        self.app.zen_limit_frame.pack_forget.assert_called()   # slider hidden
        self.app.zen_limit_frame.pack.assert_not_called()

    def test_not_repacked_when_already_visible(self):
        """Idempotent: if it's already showing for Zen Mode, don't pack it again."""
        self.app.combo_theme.get.return_value = "Zen Mode"
        self.app.zen_limit_frame.winfo_ismapped.return_value = True
        self.MasterDashboardApp._update_zen_visibility(self.app)
        self.app.zen_limit_frame.pack.assert_not_called()


if __name__ == '__main__':
    unittest.main()
