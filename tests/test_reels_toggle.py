"""
The 2.x dashboard's Reels wiring (app.main + settings_manager) without the Reels module.

Reels is shelved (3.0.18): its folder is no longer in the tree, and the tests that faked it went with it. What
stays is what the core must keep true without it: the Reels settings are module-owned (absent from the core
defaults), the button stays hidden, and opening it is a silent no-op.
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib

from app import settings_manager


class TestReelsSettingsDefaults(unittest.TestCase):
    def test_settings_are_module_owned_not_core(self):
        """Reels settings belong to the optional module, so they must NOT be in core defaults."""
        defaults = settings_manager.get_default_settings()
        self.assertNotIn("enable_reels", defaults)
        for key in ("reels_context_cues", "reels_max_folder_gb", "reels_words_per_part",
                    "reels_port", "reels_output_dir"):
            self.assertNotIn(key, defaults)

    def test_no_reels_key_leaks_into_the_core_defaults_at_all(self):
        """A build without the module must never see or persist any of them."""
        leaked = [k for k in settings_manager.get_default_settings() if "reels" in k.lower()]
        self.assertEqual(leaked, [])


class TestReelsVisibility(unittest.TestCase):
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
        self.app.btn_reels = MagicMock()
        self.app.var_enable_reels = MagicMock()
        self.app.var_language = MagicMock()
        self.app.var_language.get.return_value = "ja"
        self.app.btn_reels.winfo_ismapped.return_value = False

    def test_hidden_when_setting_off(self):
        self.app.var_enable_reels.get.return_value = False
        self.MasterDashboardApp.update_reels_visibility(self.app)
        self.app.btn_reels.pack_forget.assert_called()
        self.app.btn_reels.pack.assert_not_called()

    def test_hidden_when_on_but_module_missing(self):
        self.app.var_enable_reels.get.return_value = True
        with patch.dict(sys.modules):
            sys.modules['modules.reels'] = None  # forces ImportError on import
            self.MasterDashboardApp.update_reels_visibility(self.app)
            self.app.btn_reels.pack_forget.assert_called()

    def test_no_button_yet_is_not_an_error(self):
        """`update_reels_visibility` runs during load_settings, which can precede setup_ui."""
        self.app.btn_reels = None
        self.app.var_enable_reels.get.return_value = True
        self.MasterDashboardApp.update_reels_visibility(self.app)  # must simply return

    def test_open_reels_is_a_silent_no_op_without_the_module(self):
        """The button cannot be visible without the module, but a stale callback or a hand-edited
        settings file must not produce a traceback."""
        with patch.dict(sys.modules):
            sys.modules['modules.reels'] = None
            self.MasterDashboardApp.open_reels(self.app)   # must not raise


if __name__ == '__main__':
    unittest.main()
