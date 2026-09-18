"""
Tests for the (git-tracked) Junban toggle wiring in app.main + settings_manager.

The optional module itself is NOT tracked, so these tests must pass with or without it present. We
assert the Junban settings are module-owned (absent from the core defaults, merged in only when the
module is present) and that update_junban_visibility shows/hides the 順 button purely from the
setting and module availability — mirroring tests/test_reels_toggle.py.

What Junban does NOT have is the one extra condition Reels carries: there is no language gate.
Reordering an Anki backlog by rank works for ja and zh alike, so a test here pins that a Chinese
library still gets the button — a language check quietly grown in the core would be a regression,
not a feature.
"""

import unittest
from unittest.mock import MagicMock, patch
import importlib
import os
import sys
import tempfile

from app import settings_manager


class TestJunbanSettingsDefaults(unittest.TestCase):
    def test_settings_are_module_owned_not_core(self):
        """Junban settings belong to the optional module, so they must NOT be in core defaults."""
        defaults = settings_manager.get_default_settings()
        self.assertNotIn("enable_junban", defaults)
        for key in ("junban_scope", "junban_deck", "junban_url", "junban_word_fields",
                    "junban_chunk_size", "junban_unmatched"):
            self.assertNotIn(key, defaults)

    def test_no_junban_key_leaks_into_the_core_defaults_at_all(self):
        """A build without the module must never see or persist any of them."""
        leaked = [k for k in settings_manager.get_default_settings() if "junban" in k.lower()]
        self.assertEqual(leaked, [])

    def test_no_junban_key_reaches_settings_when_the_module_is_absent(self):
        """The Prime Invariant, at the settings layer: with modules.junban unimportable, a full
        load must produce a settings dict with no trace of the feature — nothing for save_settings
        to then write back into a user's settings.json.

        The on-disk settings file is deliberately routed to a path that does not exist, so this
        measures the merge mechanism rather than whatever this developer's own settings.json
        happens to contain today.
        """
        missing = os.path.join(tempfile.gettempdir(), "surasura-no-such-settings.json")
        with patch.dict(sys.modules), \
             patch("app.settings_manager.get_user_file", return_value=missing):
            sys.modules['modules.junban'] = None    # forces ImportError on import
            loaded = settings_manager.load_settings()
        leaked = [k for k in loaded if "junban" in k.lower()]
        self.assertEqual(leaked, [])

    def test_the_module_contributes_its_keys_when_it_is_present(self):
        """The mirror image — proof the test above measures absence, not a typo. A stand-in package
        contributing one known key must reach the loaded settings."""
        missing = os.path.join(tempfile.gettempdir(), "surasura-no-such-settings.json")
        stand_in = MagicMock()
        stand_in.SETTINGS_DEFAULTS = {"enable_junban": False}
        parent = MagicMock()
        parent.junban = stand_in
        with patch.dict(sys.modules, {'modules': parent, 'modules.junban': stand_in}), \
             patch("app.settings_manager.get_user_file", return_value=missing):
            loaded = settings_manager.load_settings()
        self.assertIn("enable_junban", loaded)
        self.assertFalse(loaded["enable_junban"])


class TestJunbanVisibility(unittest.TestCase):
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
        self.app.btn_junban = MagicMock()
        self.app.var_enable_junban = MagicMock()
        self.app.var_language = MagicMock()
        self.app.var_language.get.return_value = "ja"
        self.app.btn_junban.winfo_ismapped.return_value = False

    @staticmethod
    def _fake_package(module):
        """`{'modules': parent, 'modules.junban': module}` with the PARENT wired to the child.

        `import modules.junban` binds the top-level name via `getattr(modules, 'junban')` and only
        falls back to `sys.modules['modules.junban']`. Patching the submodule alone therefore leaves
        the caller holding an auto-created attribute of the parent mock, and nothing on the real
        stand-in is ever called — the test passes while measuring nothing.
        """
        parent = MagicMock()
        parent.junban = module
        return {'modules': parent, 'modules.junban': module}

    def test_hidden_when_setting_off(self):
        self.app.var_enable_junban.get.return_value = False
        self.MasterDashboardApp.update_junban_visibility(self.app)
        self.app.btn_junban.pack_forget.assert_called()
        self.app.btn_junban.pack.assert_not_called()

    def test_hidden_when_on_but_module_missing(self):
        """The module-absent case — the one that must hold in an open-source checkout and in a
        build that excluded it."""
        self.app.var_enable_junban.get.return_value = True
        with patch.dict(sys.modules):
            sys.modules['modules.junban'] = None  # forces ImportError on import
            self.MasterDashboardApp.update_junban_visibility(self.app)
            self.app.btn_junban.pack_forget.assert_called()
            self.app.btn_junban.pack.assert_not_called()

    def test_shown_when_on_and_module_present(self):
        """Fake the PARENT package too — `import modules.junban` binds the top-level name, so
        sys.modules['modules'] is consulted and faking only the submodule raises
        ModuleNotFoundError whenever modules/ is genuinely absent."""
        self.app.var_enable_junban.get.return_value = True
        with patch.dict(sys.modules, self._fake_package(MagicMock())):
            self.MasterDashboardApp.update_junban_visibility(self.app)
            self.app.btn_junban.pack.assert_called()

    def test_shown_for_chinese_too_there_is_no_language_gate(self):
        """Unlike Reels, reordering a backlog by rank is language-agnostic: the orthBase match key
        is the only Japanese-specific part and zh degrades to the lemma key harmlessly. A language
        condition grown in the core would hide a feature that works."""
        self.app.var_enable_junban.get.return_value = True
        self.app.var_language.get.return_value = "zh"
        with patch.dict(sys.modules, self._fake_package(MagicMock())):
            self.MasterDashboardApp.update_junban_visibility(self.app)
            self.app.btn_junban.pack.assert_called()
            self.app.btn_junban.pack_forget.assert_not_called()

    def test_no_button_yet_is_not_an_error(self):
        """`update_junban_visibility` runs during load_settings, which can precede setup_ui."""
        self.app.btn_junban = None
        self.app.var_enable_junban.get.return_value = True
        self.MasterDashboardApp.update_junban_visibility(self.app)  # must simply return

    def test_an_already_shown_button_is_not_repacked(self):
        """Re-packing on every settings save would reorder the footer."""
        self.app.var_enable_junban.get.return_value = True
        self.app.btn_junban.winfo_ismapped.return_value = True
        with patch.dict(sys.modules, self._fake_package(MagicMock())):
            self.MasterDashboardApp.update_junban_visibility(self.app)
            self.app.btn_junban.pack.assert_not_called()

    def test_open_junban_is_a_silent_no_op_without_the_module(self):
        """The button cannot be visible without the module, but a stale callback or a hand-edited
        settings file must not produce a traceback."""
        with patch.dict(sys.modules):
            sys.modules['modules.junban'] = None
            self.MasterDashboardApp.open_junban(self.app)   # must not raise

    def test_open_junban_delegates_everything_to_the_module(self):
        """The core owns a thin entry point and nothing else — no AnkiConnect, no planner, no
        snapshot logic leaks in here."""
        module = MagicMock()
        with patch.dict(sys.modules, self._fake_package(module)):
            self.MasterDashboardApp.open_junban(self.app)
        module.open_junban.assert_called_once_with(self.app)


if __name__ == '__main__':
    unittest.main()
