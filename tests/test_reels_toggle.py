"""
Tests for the (git-tracked) Reels toggle wiring in app.main + settings_manager.

The optional module itself is NOT tracked, so these tests must pass with or without it present. We
assert the Reels settings are module-owned (absent from the core defaults, merged in only when the
module is present) and that update_reels_visibility shows/hides the button purely from the setting,
module availability and the language — exactly mirroring tests/test_youtube_toggle.py.

The language condition is the one thing this button has that the others do not: Reels' cue merger
reads UniDic inflection features, so a Chinese library cannot be served. The core does not know that
— it asks the module — so the test patches `supports_language` explicitly rather than relying on a
MagicMock's truthiness (see docs/agent instructions/testing.md §5.3).
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

    @staticmethod
    def _module(supports=True):
        """A stand-in for modules.reels whose language answer is stated, not inferred.

        A bare MagicMock would answer every call truthily, so the 'shown' case would pass even if
        the core asked the wrong question entirely.
        """
        module = MagicMock()
        module.supports_language.return_value = supports
        return module

    @staticmethod
    def _fake_package(module):
        """`{'modules': parent, 'modules.reels': module}` with the PARENT wired to the child.

        `import modules.reels as reels` binds via `getattr(modules, 'reels')` and only falls back to
        `sys.modules['modules.reels']`. Patching the submodule alone therefore leaves the caller
        holding an auto-created attribute of the parent mock, and nothing on the real stand-in is
        ever called — the test passes while measuring nothing.
        """
        parent = MagicMock()
        parent.reels = module
        return {'modules': parent, 'modules.reels': module}

    def test_hidden_when_setting_off(self):
        self.app.var_enable_reels.get.return_value = False
        self.MasterDashboardApp.update_reels_visibility(self.app)
        self.app.btn_reels.pack_forget.assert_called()
        self.app.btn_reels.pack.assert_not_called()

    def test_shown_when_on_and_module_present(self):
        """Fake the PARENT package too — `import modules.reels` binds the top-level name, so
        sys.modules['modules'] is consulted and faking only the submodule raises
        ModuleNotFoundError whenever modules/ is genuinely absent."""
        self.app.var_enable_reels.get.return_value = True
        with patch.dict(sys.modules, self._fake_package(self._module(supports=True))):
            self.MasterDashboardApp.update_reels_visibility(self.app)
            self.app.btn_reels.pack.assert_called()

    def test_hidden_when_on_but_module_missing(self):
        self.app.var_enable_reels.get.return_value = True
        with patch.dict(sys.modules):
            sys.modules['modules.reels'] = None  # forces ImportError on import
            self.MasterDashboardApp.update_reels_visibility(self.app)
            self.app.btn_reels.pack_forget.assert_called()

    def test_hidden_for_a_language_the_module_cannot_serve(self):
        """A Chinese library gets no button rather than one that builds subtly broken reels."""
        self.app.var_enable_reels.get.return_value = True
        self.app.var_language.get.return_value = "zh"
        with patch.dict(sys.modules, self._fake_package(self._module(supports=False))):
            self.MasterDashboardApp.update_reels_visibility(self.app)
            self.app.btn_reels.pack_forget.assert_called()
            self.app.btn_reels.pack.assert_not_called()

    def test_the_language_is_asked_of_the_module_not_decided_here(self):
        """The core must not carry the rule. If it grew its own hardcoded 'ja', this would pass
        without the module ever being consulted."""
        self.app.var_enable_reels.get.return_value = True
        module = self._module(supports=True)
        with patch.dict(sys.modules, self._fake_package(module)):
            self.MasterDashboardApp.update_reels_visibility(self.app)
        module.supports_language.assert_called_once_with("ja")

    def test_no_button_yet_is_not_an_error(self):
        """`update_reels_visibility` runs during load_settings, which can precede setup_ui."""
        self.app.btn_reels = None
        self.app.var_enable_reels.get.return_value = True
        self.MasterDashboardApp.update_reels_visibility(self.app)  # must simply return

    def test_an_already_shown_button_is_not_repacked(self):
        """Re-packing on every language change or settings save would reorder the footer."""
        self.app.var_enable_reels.get.return_value = True
        self.app.btn_reels.winfo_ismapped.return_value = True
        with patch.dict(sys.modules, self._fake_package(self._module(supports=True))):
            self.MasterDashboardApp.update_reels_visibility(self.app)
            self.app.btn_reels.pack.assert_not_called()

    def test_open_reels_is_a_silent_no_op_without_the_module(self):
        """The button cannot be visible without the module, but a stale callback or a hand-edited
        settings file must not produce a traceback."""
        with patch.dict(sys.modules):
            sys.modules['modules.reels'] = None
            self.MasterDashboardApp.open_reels(self.app)   # must not raise

    def test_open_reels_delegates_everything_to_the_module(self):
        """The core owns a thin entry point and nothing else — no orchestration leaks in here."""
        module = self._module()
        with patch.dict(sys.modules, self._fake_package(module)):
            self.MasterDashboardApp.open_reels(self.app)
        module.open_reels.assert_called_once_with(self.app)


if __name__ == '__main__':
    unittest.main()
