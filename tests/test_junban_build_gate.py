"""The two build gates that decide whether Junban ships, checked against the real files.

Both failure directions are silent. Ship the module into a build nobody asked for and the 順 button
appears next to an AnkiConnect integration the user never enabled; leave it out of a build whose
settings enable it and the button appears and does nothing. Neither shows up until someone runs the
packaged app.

`packaging/Surasura.spec` is a PyInstaller script, not an importable module, so its conditionality
block is sliced out between its own section banners and executed in a controlled namespace. That
tests the logic that actually ships rather than a paraphrase of it — if the banners or the variable
names move, this fails rather than quietly passing.
"""

import json
import os
import unittest

import package_app

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = os.path.join(_ROOT, "packaging", "Surasura.spec")

_BLOCK_START = "BUILD SETTINGS (Conditionality)"
_BLOCK_END = "PYINSTALLER CONFIG"


def _conditionality_block():
    """The spec's build-configuration section, as executable source.

    Both markers sit inside comments, so the slice starts at the line *after* the opening banner —
    beginning mid-comment would leave bare text as line 1 and fail to compile.
    """
    with open(_SPEC, "r", encoding="utf-8") as handle:
        source = handle.read()
    start = source.index("\n", source.index(_BLOCK_START)) + 1
    end = source.index(_BLOCK_END)
    return source[start:end]


def _run_spec_config(tmp_root):
    """Execute that block with `project_root` pointed at a throwaway folder.

    Returns the namespace, so a test can inspect `excluded_modules` exactly as PyInstaller would
    see it.
    """
    namespace = {"os": os, "project_root": tmp_root}
    exec(compile(_conditionality_block(), _SPEC, "exec"), namespace)
    return namespace


def _write_settings(tmp_root, settings):
    with open(os.path.join(tmp_root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump(settings, handle)


class TestSpecExclusion(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp()
        # Koe is gated on the folder existing rather than on a toggle, so the fixture has to carry
        # it for the "other modules are unaffected" assertion below to mean anything.
        os.makedirs(os.path.join(self.root, "modules", "koe"), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_block_can_still_be_found(self):
        """A guard on the guard: if the section banners are renamed, every test below would exec an
        empty string and pass while checking nothing."""
        block = _conditionality_block()
        self.assertIn("enable_junban", block)
        self.assertIn("excluded_modules", block)

    def test_junban_is_excluded_when_the_toggle_is_off(self):
        _write_settings(self.root, {"enable_junban": False})
        self.assertIn("modules.junban", _run_spec_config(self.root)["excluded_modules"])

    def test_junban_is_bundled_when_the_toggle_is_on(self):
        _write_settings(self.root, {"enable_junban": True})
        self.assertNotIn("modules.junban", _run_spec_config(self.root)["excluded_modules"])

    def test_junban_is_excluded_when_the_key_is_absent(self):
        """Opt-in: a settings file that has never heard of Junban must not ship it."""
        _write_settings(self.root, {"theme": "Dark Flow"})
        self.assertIn("modules.junban", _run_spec_config(self.root)["excluded_modules"])

    def test_a_missing_settings_file_excludes_rather_than_crashing(self):
        """The pre-initialised default is what stops a NameError here — the trap the spec's own
        comment calls out for `enable_preview`."""
        self.assertIn("modules.junban", _run_spec_config(self.root)["excluded_modules"])

    def test_a_corrupt_settings_file_fails_closed(self):
        with open(os.path.join(self.root, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertIn("modules.junban", _run_spec_config(self.root)["excluded_modules"])

    def test_the_other_modules_are_unaffected_by_the_junban_toggle(self):
        """The gates are independent; turning Junban on must not drag anything else in or out."""
        _write_settings(self.root, {"enable_junban": True})
        excluded = _run_spec_config(self.root)["excluded_modules"]
        self.assertIn("modules.youtube_downloader", excluded)   # its own toggles are off
        self.assertIn("modules.reels", excluded)                # parked, and its toggle is off here
        self.assertNotIn("modules.koe", excluded)               # folder exists in the fixture

    def test_junban_is_never_named_as_a_hiddenimport(self):
        """A hiddenimport naming a module that is also excluded is a contradiction PyInstaller
        resolves by warning and dropping it — a silent no-op. Junban needs none: everything it uses
        is reached by ordinary imports from `modules.junban`, so the exclusion is the whole gate."""
        with open(_SPEC, "r", encoding="utf-8") as handle:
            spec = handle.read()
        hiddenimports_region = spec[spec.index("hiddenimports = ["):spec.index("a = Analysis(")]
        self.assertNotIn("junban", hiddenimports_region)


class TestPreBuildTestGate(unittest.TestCase):
    """`package_app` runs a bundled module's own suite before building. A module that ships without
    its tests having run is a module nobody checked."""

    def test_the_junban_suite_runs_when_the_module_will_be_bundled(self):
        dirs = package_app._included_module_test_dirs({"enable_junban": True})
        expected = os.path.join("modules", "junban", "tests")
        if os.path.isdir(os.path.join(_ROOT, expected)):
            self.assertIn(expected, dirs)

    def test_the_junban_suite_is_skipped_when_it_will_not_be_bundled(self):
        dirs = package_app._included_module_test_dirs({"enable_junban": False})
        self.assertNotIn(os.path.join("modules", "junban", "tests"), dirs)

    def test_the_junban_suite_is_skipped_when_the_key_is_absent(self):
        """Same opt-in default as the spec: no key means no module, so no suite."""
        dirs = package_app._included_module_test_dirs({})
        self.assertNotIn(os.path.join("modules", "junban", "tests"), dirs)

    def test_an_absent_module_is_not_asked_for_its_tests(self):
        """An open-source checkout enables nothing it does not have."""
        original = os.path.isdir

        def missing_junban(path):
            return False if "junban" in str(path) else original(path)

        os.path.isdir = missing_junban
        try:
            dirs = package_app._included_module_test_dirs({"enable_junban": True})
        finally:
            os.path.isdir = original
        self.assertNotIn(os.path.join("modules", "junban", "tests"), dirs)

    def test_the_gate_mirrors_the_spec(self):
        """The two gates read the same key. If they ever disagreed, a module could ship without its
        suite having run, or a suite could run for a module that was excluded."""
        block = _conditionality_block()
        self.assertIn('settings.get("enable_junban"', block)
        import inspect
        source = inspect.getsource(package_app._included_module_test_dirs)
        self.assertIn('settings.get("enable_junban"', source)


if __name__ == "__main__":
    unittest.main()
