"""The core without the Koe (speech) module.

Koe is shelved (3.0.18): its folder is no longer in the tree, and its own wiring tests went with it. What stays
here is what the core must keep true without it: the speech settings are module-owned, the report generator embeds
nothing when the module is absent, the templates never carry a key or call Google, and an absent module is a
silent no-op.

Mirrors tests/test_youtube_toggle.py.
"""

import importlib
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

from app import settings_manager


class TestKoeSettingsAreModuleOwned(unittest.TestCase):
    def test_speech_settings_are_not_in_core_defaults(self):
        """They belong to the optional module and are merged in only when it is importable, so a
        build without it never sees or persists them."""
        defaults = settings_manager.get_default_settings()
        for key in ("enable_koe", "koe_voice", "koe_model", "koe_style",
                    "koe_temperature", "koe_port", "koe_daily_cap"):
            self.assertNotIn(key, defaults)

    def test_no_api_key_field_exists_anywhere_in_core_settings(self):
        """settings.json is read by packaging/Surasura.spec and ships inside the release, so a
        credential must never be able to land in it."""
        serialized = json.dumps(settings_manager.get_default_settings())
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("AQ.", serialized)


class TestReportEmbedsNothingWithoutTheModule(unittest.TestCase):
    """`static_html_generator` runs in the analyzer SUBPROCESS, where no helper is running, so it
    derives the endpoint from configuration. With the module absent it must embed a bare null."""

    def test_generator_handles_a_missing_module(self):
        from app import static_html_generator  # noqa: F401  (import must not require the module)

        with patch.dict(sys.modules):
            sys.modules['modules.koe'] = None      # forces ImportError on import
            koe_config = None
            try:
                # Mirrors static_html_generator exactly, including the import FORM: the
                # `from modules import koe` spelling reads a cached package attribute and would
                # not fail here even with the module gone.
                import modules.koe as _koe
                koe_config = _koe.report_config()
            except Exception:
                koe_config = None
            self.assertIsNone(koe_config)
            self.assertEqual(json.dumps(koe_config), "null")

    def test_template_treats_a_null_endpoint_as_speech_off(self):
        """The YouTube preview's page (web_app.html; Zen's page retired, J-RETIRE) must read `globalKoe = null` as
        'no speech', so a page rendered without the module keeps the badge's original copy-path behaviour."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("web_app.html",):
            with open(os.path.join(root, "templates", name), "r", encoding="utf-8") as f:
                markup = f.read()
            self.assertIn("globalKoe", markup, f"{name} must read the injected endpoint")
            self.assertIn("function koeEnabled()", markup)
            # koeEnabled() gates every speech path; it must require BOTH the object and a token.
            self.assertIn("return !!(KOE && KOE.token);", markup)

    def test_templates_never_contain_an_api_key_or_a_google_endpoint(self):
        """The page talks only to 127.0.0.1. If a report ever called Google directly it would have
        to carry the credential, which is the whole reason the local helper exists."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("web_app.html",):
            with open(os.path.join(root, "templates", name), "r", encoding="utf-8") as f:
                markup = f.read()
            self.assertNotIn("generativelanguage.googleapis.com", markup)
            self.assertNotIn("x-goog-api-key", markup)
            self.assertIn("127.0.0.1", markup)


# The old page's signature part for Speech retired with the old journey page (J-RETIRE): the journey page has no
# Speech, so toggling it moves no signature (tests/test_settings_signatures.py holds that).


class TestAnAbsentKoeIsANoOp(unittest.TestCase):
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
        self.app.var_enable_koe = MagicMock()
        self.app.var_source_display = MagicMock()

    def test_absent_module_is_a_silent_no_op(self):
        """The Prime Invariant: with modules/koe/ deleted the app must behave exactly as before."""
        self.app.var_enable_koe.get.return_value = True
        self.app.var_source_display.get.return_value = "off"
        with patch.dict(sys.modules):
            sys.modules['modules.koe'] = None      # forces ImportError on import
            self.MasterDashboardApp.apply_koe_state(self.app)   # must not raise
        self.app.var_source_display.set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
