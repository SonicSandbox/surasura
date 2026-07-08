"""
Tests for the (git-tracked) YouTube toggle wiring in app.main + settings_manager.

The optional module itself is NOT tracked, so these tests must pass with or without
it present. We assert the YouTube settings are module-owned (absent from the core
defaults, merged in only when the module is present) and that update_youtube_visibility
shows/hides the button purely from the setting + module availability (mocked), exactly
mirroring the Immersion Architect (Satori) conditional-visibility tests.
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib

from app import settings_manager


class TestYoutubeSettingsDefaults(unittest.TestCase):
    def test_settings_are_module_owned_not_core(self):
        """YouTube settings belong to the optional module, so they must NOT be in core defaults."""
        defaults = settings_manager.get_default_settings()
        self.assertNotIn("enable_youtube_transcripts", defaults)
        self.assertNotIn("enable_youtube_preview", defaults)
        self.assertNotIn("youtube_risk_acknowledged", defaults)


class TestYoutubeVisibility(unittest.TestCase):
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
        self.app.btn_youtube = MagicMock()
        self.app.var_enable_youtube = MagicMock()
        self.app.btn_youtube.winfo_ismapped.return_value = False

    def test_hidden_when_setting_off(self):
        self.app.var_enable_youtube.get.return_value = False
        self.MasterDashboardApp.update_youtube_visibility(self.app)
        self.app.btn_youtube.pack_forget.assert_called()
        self.app.btn_youtube.pack.assert_not_called()

    def test_shown_when_on_and_module_present(self):
        self.app.var_enable_youtube.get.return_value = True
        with patch.dict(sys.modules, {'modules.youtube_downloader': MagicMock()}):
            self.MasterDashboardApp.update_youtube_visibility(self.app)
            self.app.btn_youtube.pack.assert_called()

    def test_hidden_when_on_but_module_missing(self):
        self.app.var_enable_youtube.get.return_value = True
        with patch.dict(sys.modules):
            sys.modules['modules.youtube_downloader'] = None  # forces ImportError on import
            self.MasterDashboardApp.update_youtube_visibility(self.app)
            self.app.btn_youtube.pack_forget.assert_called()


if __name__ == '__main__':
    unittest.main()
