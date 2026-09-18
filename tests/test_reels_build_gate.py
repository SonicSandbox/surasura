"""The two build gates that decide whether Reels ships, checked against the real files.

Both failure directions are silent and expensive. Ship the module into a build nobody asked for and
a vendored copy of SubsMatcher goes out with it; leave it out of a build that enables it and the
button appears and does nothing. Neither shows up until someone runs the packaged app.

`packaging/Surasura.spec` is a PyInstaller script, not an importable module, so its conditionality
block is sliced out between its own section banners and executed in a controlled namespace. That
tests the logic that actually ships rather than a paraphrase of it — if the banners or the variable
names move, this fails rather than quietly passing.
"""

import json
import os
import unittest

import package_app
from app import settings_manager

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
        os.makedirs(os.path.join(self.root, "modules", "koe"), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_block_can_still_be_found(self):
        """A guard on the guard: if the section banners are renamed, every test below would exec an
        empty string and pass while checking nothing."""
        block = _conditionality_block()
        self.assertIn("enable_reels", block)
        self.assertIn("excluded_modules", block)

    def test_reels_is_excluded_when_the_toggle_is_off(self):
        _write_settings(self.root, {"enable_reels": False})
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_reels_is_bundled_when_the_toggle_is_on(self):
        _write_settings(self.root, {"enable_reels": True})
        self.assertNotIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_reels_is_excluded_when_the_key_is_absent(self):
        """Opt-in: a settings file that has never heard of Reels must not ship it."""
        _write_settings(self.root, {"theme": "Dark Flow"})
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_a_missing_settings_file_excludes_rather_than_crashing(self):
        """The pre-initialised default is what stops a NameError here — the trap the spec's own
        comment calls out for `enable_preview`."""
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_a_corrupt_settings_file_fails_closed(self):
        with open(os.path.join(self.root, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_the_other_modules_are_unaffected_by_the_reels_toggle(self):
        """The gates are independent; turning Reels on must not drag anything else in or out."""
        _write_settings(self.root, {"enable_reels": True})
        excluded = _run_spec_config(self.root)["excluded_modules"]
        self.assertIn("modules.youtube_downloader", excluded)   # its own toggles are off
        self.assertNotIn("modules.koe", excluded)               # folder exists in the fixture


class TestPreBuildTestGate(unittest.TestCase):
    """`package_app` runs a bundled module's own suite before building. A module that ships without
    its tests having run is a module nobody checked."""

    def test_the_reels_suite_runs_when_the_module_will_be_bundled(self):
        dirs = package_app._included_module_test_dirs({"enable_reels": True})
        expected = os.path.join("modules", "reels", "tests")
        if os.path.isdir(os.path.join(_ROOT, expected)):
            self.assertIn(expected, dirs)

    def test_the_reels_suite_is_skipped_when_it_will_not_be_bundled(self):
        dirs = package_app._included_module_test_dirs({"enable_reels": False})
        self.assertNotIn(os.path.join("modules", "reels", "tests"), dirs)

    def test_an_absent_module_is_not_asked_for_its_tests(self):
        """An open-source checkout enables nothing it does not have."""
        original = os.path.isdir

        def missing_reels(path):
            return False if "reels" in str(path) else original(path)

        os.path.isdir = missing_reels
        try:
            dirs = package_app._included_module_test_dirs({"enable_reels": True})
        finally:
            os.path.isdir = original
        self.assertNotIn(os.path.join("modules", "reels", "tests"), dirs)

    def test_the_gate_mirrors_the_spec(self):
        """The two gates read the same key. If they ever disagreed, a module could ship without its
        suite having run, or a suite could run for a module that was excluded."""
        block = _conditionality_block()
        self.assertIn('settings.get("enable_reels"', block)
        import inspect
        source = inspect.getsource(package_app._included_module_test_dirs)
        self.assertIn('settings.get("enable_reels"', source)


class TestFrozenSubsyncIsReachable(unittest.TestCase):
    """The sync stage shells out to the vendored SubsMatcher, and a frozen build changes both
    halves of how that works: there is no interpreter to run a script with, and the script is not
    a file on disk. Three things have to line up, and all three are invisible from source."""

    def test_the_vendored_script_is_an_importable_module(self):
        """PyInstaller bundles what the import graph reaches. The script is only ever executed, so
        without this package marker it is left out of the build and the dispatch imports nothing."""
        self.assertTrue(os.path.isfile(
            os.path.join(_ROOT, "modules", "reels", "vendor", "__init__.py")))

    def test_the_spec_bundles_the_vendored_script_only_when_reels_ships(self):
        """A hiddenimport naming a module that is also excluded is a contradiction PyInstaller
        resolves by dropping it — so the entry has to sit inside the same gate."""
        with open(_SPEC, "r", encoding="utf-8") as handle:
            spec = handle.read()
        self.assertIn("modules.reels.vendor.subsync", spec)
        guarded = spec.index("if enable_reels:") < spec.index("modules.reels.vendor.subsync")
        self.assertTrue(guarded, "the hiddenimport must be inside the `if enable_reels:` gate")


class TestArchitectSettingsAreBundled(unittest.TestCase):
    def test_the_spec_ships_architect_settings_when_the_module_is_included(self):
        """It is read AND written through `get_resource`, so it has to exist under the bundle root.
        Without it every read silently falls back to defaults and the budget slider discards
        changes — which looks like it worked."""
        with open(_SPEC, "r", encoding="utf-8") as handle:
            spec = handle.read()
        self.assertIn("architect_settings.json", spec)
        self.assertIn("if not hide_satoru:", spec)


class TestShippedSettings(unittest.TestCase):
    def test_the_settings_written_into_a_build_carry_no_reels_keys(self):
        """`package_app` regenerates settings.json from the core defaults, so a release never ships
        one user's module tunables to everyone."""
        defaults = settings_manager.get_default_settings()
        self.assertEqual([k for k in defaults if "reels" in k.lower()], [])


if __name__ == "__main__":
    unittest.main()
