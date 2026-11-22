"""The build gates that keep Reels out of every build, checked against the real files.

Reels is shelved (3.0.18): its folder is no longer in the tree, and the tests of it shipping went with it. What
stays is the closed direction: whatever the build config says or lacks, a build excludes it, and a checkout without
it is never asked for its suite.

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


def _write_config(tmp_root, modules):
    """The build's one configuration (S3.1 D15): packaging/build_config.json's `modules` block, never settings.json."""
    os.makedirs(os.path.join(tmp_root, "packaging"), exist_ok=True)
    with open(os.path.join(tmp_root, "packaging", "build_config.json"), "w", encoding="utf-8") as handle:
        json.dump({"modules": modules}, handle)


class TestSpecExclusion(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp()

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
        _write_config(self.root, {"reels": False})
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_reels_is_excluded_when_the_key_is_absent(self):
        """Opt-in: a build config that has never heard of Reels must not ship it."""
        _write_config(self.root, {"koe": True})
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_a_missing_build_config_excludes_rather_than_crashing(self):
        """No build config bundles no optional module (package_app refuses to build without one first)."""
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])

    def test_a_corrupt_build_config_fails_closed(self):
        os.makedirs(os.path.join(self.root, "packaging"), exist_ok=True)
        with open(os.path.join(self.root, "packaging", "build_config.json"), "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertIn("modules.reels", _run_spec_config(self.root)["excluded_modules"])


class TestPreBuildTestGate(unittest.TestCase):
    """`package_app` runs a bundled module's own suite before building. A module that ships without
    its tests having run is a module nobody checked."""

    def test_the_reels_suite_is_skipped_when_it_will_not_be_bundled(self):
        dirs = package_app._included_module_test_dirs({"reels": False})
        self.assertNotIn(os.path.join("modules", "reels", "tests"), dirs)

    def test_an_absent_module_is_not_asked_for_its_tests(self):
        """An open-source checkout enables nothing it does not have."""
        original = os.path.isdir

        def missing_reels(path):
            return False if "reels" in str(path) else original(path)

        os.path.isdir = missing_reels
        try:
            dirs = package_app._included_module_test_dirs({"reels": True})
        finally:
            os.path.isdir = original
        self.assertNotIn(os.path.join("modules", "reels", "tests"), dirs)


class TestShippedSettings(unittest.TestCase):
    def test_the_settings_written_into_a_build_carry_no_reels_keys(self):
        """`package_app` regenerates settings.json from the core defaults, so a release never ships
        one user's module tunables to everyone."""
        defaults = settings_manager.get_default_settings()
        self.assertEqual([k for k in defaults if "reels" in k.lower()], [])


if __name__ == "__main__":
    unittest.main()
