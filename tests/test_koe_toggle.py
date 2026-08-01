"""Core-side wiring for the optional Koe (speech) module.

The module itself is NOT tracked by git, so everything here must pass with or without it present.
These tests cover only what lives in the core: that the speech settings are module-owned, that the
report generator embeds nothing when the module is absent or off, and that the toggle drives the
helper's lifecycle. The module's own behaviour is covered by `modules/koe/tests`.

Mirrors tests/test_youtube_toggle.py.
"""

import importlib
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

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
        """The shipped templates must read `globalKoe = null` as 'no speech', so a report rendered
        without the module keeps the badge's original copy-path behaviour."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("web_app.html", "zen_app.html"):
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
        for name in ("web_app.html", "zen_app.html"):
            with open(os.path.join(root, "templates", name), "r", encoding="utf-8") as f:
                markup = f.read()
            self.assertNotIn("generativelanguage.googleapis.com", markup)
            self.assertNotIn("x-goog-api-key", markup)
            self.assertIn("127.0.0.1", markup)


class TestHiddenInstallLeavesNoTrace(unittest.TestCase):
    """A user who never asks for speech must end up with a settings.json that looks exactly as it
    did before the module shipped — no toggle, and no koe_* keys written by a routine save."""

    def _saved_settings(self, revealed):
        """Run the dashboard's save path with the module present and `is_revealed` forced."""
        app = MagicMock()
        app._current_settings = {"koe_voice": "Sadaltager", "koe_model": "m", "koe_style": "",
                                 "koe_temperature": 1.15, "koe_port": 8787, "koe_daily_cap": 300}
        app.var_enable_koe.get.return_value = True

        settings = {}
        fake_koe = MagicMock()
        fake_koe.is_revealed.return_value = revealed
        with patch.dict(sys.modules, {'modules': MagicMock(koe=fake_koe),
                                      'modules.koe': fake_koe}):
            # Mirrors the block in MasterDashboardApp.save_settings.
            try:
                import modules.koe as _koe
                if _koe.is_revealed():
                    settings["enable_koe"] = app.var_enable_koe.get()
                    for key in ("koe_voice", "koe_model", "koe_style",
                                "koe_temperature", "koe_port", "koe_daily_cap"):
                        if key in app._current_settings:
                            settings[key] = app._current_settings[key]
            except (ImportError, ModuleNotFoundError):
                pass
        return settings

    def test_nothing_is_written_while_hidden(self):
        self.assertEqual(self._saved_settings(revealed=False), {})

    def test_settings_are_written_once_revealed(self):
        saved = self._saved_settings(revealed=True)
        self.assertIn("enable_koe", saved)
        self.assertIn("koe_voice", saved)

    def test_the_real_save_path_consults_is_revealed(self):
        """Guards the wiring itself: if the `is_revealed()` check were ever dropped from
        save_settings, the keys would leak to every user and this file would still pass."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app", "main.py"), "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("_koe.is_revealed()", source,
                      "save_settings/settings UI must gate on the reveal check")


class TestSpeechIsPartOfThePresentationFingerprint(unittest.TestCase):
    """Speech state is INJECTED into the report, so toggling it has to force a re-render.

    Without this the badge could be left mute: with the source badge already visible, turning
    speech on changed nothing the render signature looked at, so Generate reused the existing
    report and its badges carried `globalKoe = null`.
    """

    def _signature(self, enable_koe):
        from app import analyzer
        args = analyzer.parse_analysis_args(["--theme=default"])
        settings = {"source_display": "icon", "words_per_day": 5,
                    "show_words_per_day": True, "enable_koe": enable_koe}
        with patch("app.settings_manager.load_settings", return_value=settings):
            return analyzer.compute_render_signature(args)

    def test_toggling_speech_changes_the_render_signature(self):
        self.assertNotEqual(self._signature(True), self._signature(False))

    def test_signature_is_stable_when_speech_state_is_unchanged(self):
        """It must only force a re-render on a real change — this runs on every Generate."""
        self.assertEqual(self._signature(True), self._signature(True))

    def test_absent_module_reads_as_speech_off(self):
        """Without the module the key simply isn't in settings; that must not raise or churn."""
        from app import analyzer
        args = analyzer.parse_analysis_args(["--theme=default"])
        with patch("app.settings_manager.load_settings", return_value={"source_display": "icon"}):
            without_key = analyzer.compute_render_signature(args)
        self.assertEqual(without_key, self._signature(False))


class TestKoeToggleDrivesTheHelper(unittest.TestCase):
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

    def test_enabling_speech_starts_the_helper(self):
        self.app.var_enable_koe.get.return_value = True
        self.app.var_source_display.get.return_value = "icon"
        fake_koe = MagicMock()
        # The PARENT package is faked too: `from modules import koe` binds the top-level name, so
        # sys.modules['modules'] is consulted and faking only the submodule would raise whenever
        # modules/ is genuinely absent — the very case this file promises to cover.
        with patch.dict(sys.modules, {'modules': MagicMock(koe=fake_koe),
                                      'modules.koe': fake_koe}):
            self.MasterDashboardApp.apply_koe_state(self.app)
        fake_koe.start_server.assert_called_once()
        fake_koe.stop_server.assert_not_called()

    def test_disabling_speech_stops_the_helper(self):
        self.app.var_enable_koe.get.return_value = False
        self.app.var_source_display.get.return_value = "icon"
        fake_koe = MagicMock()
        with patch.dict(sys.modules, {'modules': MagicMock(koe=fake_koe),
                                      'modules.koe': fake_koe}):
            self.MasterDashboardApp.apply_koe_state(self.app)
        fake_koe.stop_server.assert_called_once()
        fake_koe.start_server.assert_not_called()

    def test_enabling_speech_promotes_a_hidden_source_badge(self):
        """The report's speech control IS the source badge, so with the badge off there would be
        no button to click. Turning speech on must make it visible."""
        self.app.var_enable_koe.get.return_value = True
        self.app.var_source_display.get.return_value = "off"
        fake_koe = MagicMock()
        with patch.dict(sys.modules, {'modules': MagicMock(koe=fake_koe),
                                      'modules.koe': fake_koe}):
            self.MasterDashboardApp.apply_koe_state(self.app)
        self.app.var_source_display.set.assert_called_once_with("icon")

    def test_an_existing_badge_choice_is_left_alone(self):
        """Only 'off' is overridden — someone who chose 'File name' keeps it."""
        self.app.var_enable_koe.get.return_value = True
        self.app.var_source_display.get.return_value = "filename"
        fake_koe = MagicMock()
        with patch.dict(sys.modules, {'modules': MagicMock(koe=fake_koe),
                                      'modules.koe': fake_koe}):
            self.MasterDashboardApp.apply_koe_state(self.app)
        self.app.var_source_display.set.assert_not_called()

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
