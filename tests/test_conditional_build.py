import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib

class TestConditionalSatori(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Safely setup mocks for app.main import.
        We snapshot sys.modules to ensure we can unload EVERYTHING loaded during this test class.
        """
        cls._original_modules = set(sys.modules.keys())
        
        cls.sys_modules_patcher = patch.dict(sys.modules, {
            'tkinter': MagicMock(),
            'tkinter.ttk': MagicMock(),
            'tkinter.messagebox': MagicMock(),
            'app.path_utils': MagicMock(),
            'app.update_checker': MagicMock(),
            'app.onboarding_gui': MagicMock(),
        })
        cls.sys_modules_patcher.start()
        
        # Now import app.main. It will use the mocks.
        try:
            import app.main
            importlib.reload(app.main) # Force reload with OUR mocks
            cls.app_module = app.main
            cls.MasterDashboardApp = app.main.MasterDashboardApp
        except ImportError as e:
            print(f"DEBUG: Failed to import app.main in setUpClass: {e}")
            cls.app_module = None
            cls.MasterDashboardApp = None

    @classmethod
    def tearDownClass(cls):
        """
        Clean up mocks and force unload of ANY module loaded during this test class.
        This prevents 'poisoned' modules (initialized with mocks) from persisting to other tests.
        """
        cls.sys_modules_patcher.stop()
        
        # Aggressively unload any module that wasn't present before setUpClass
        current_modules = set(sys.modules.keys())
        new_modules = current_modules - cls._original_modules
        
        for mod in new_modules:
            if mod in sys.modules:
                del sys.modules[mod]
        
        # Explicitly ensure app.main is gone just in case
        if 'app.main' in sys.modules:
            del sys.modules['app.main']

    def setUp(self):
        if self.MasterDashboardApp is None:
            self.skipTest("app.main could not be imported")

        # Create a mock instance
        self.app = MagicMock(spec=self.MasterDashboardApp)
        self.app.btn_satori = MagicMock()
        self.app.var_hide_satoru = MagicMock()
        self.app.btn_satori.winfo_ismapped.return_value = False
        
    def test_satori_hidden_by_user_setting(self):
        """Test that button is hidden if user setting is True"""
        self.app.var_hide_satoru.get.return_value = True
        
        self.MasterDashboardApp.update_satori_visibility(self.app)
        
        self.app.btn_satori.pack_forget.assert_called()
        self.app.btn_satori.pack.assert_not_called()

    def test_satori_shown_if_module_present(self):
        """Test that button is shown if setting is False and module imports"""
        self.app.var_hide_satoru.get.return_value = False

        # The PARENT package has to be faked too. `import modules.immersion_architect` binds the
        # top-level name, so __import__ looks up sys.modules['modules'] as well — faking only the
        # submodule raised ModuleNotFoundError whenever modules/ was genuinely absent, which is
        # exactly the configuration this file exists to prove works (an open-source checkout, or
        # the SOP's delete-test). Faking both keeps the coverage instead of skipping it.
        with patch.dict(sys.modules, {'modules': MagicMock(),
                                      'modules.immersion_architect': MagicMock()}):
            self.MasterDashboardApp.update_satori_visibility(self.app)
            self.app.btn_satori.pack.assert_called()

    def test_satori_hidden_if_module_missing(self):
        """Test that button is hidden if module raises ImportError"""
        self.app.var_hide_satoru.get.return_value = False
        
        # Ensure module is NOT in sys.modules
        with patch.dict(sys.modules):
            if 'modules.immersion_architect' in sys.modules:
                del sys.modules['modules.immersion_architect']
            
            # Use 'modules.immersion_architect' = None to trigger ImportError on import attempt
            # (Standard Python 3 behavior for "module not found" in sys.modules overrides)
            # Actually, setting it to None explicitly might work best here.
            sys.modules['modules.immersion_architect'] = None
            
            try:
                self.MasterDashboardApp.update_satori_visibility(self.app)
            except (ImportError, AttributeError):
                 # function might catch it, or not since we are simulating import failure
                 pass
            
            self.app.btn_satori.pack_forget.assert_called()

if __name__ == '__main__':
    unittest.main()


# --- S1.1 A5: the Immersion Architect is out of every build --------------------------------------
# The spec is executed for real (PyInstaller's build steps stubbed to record what they are given), in
# a scratch project folder whose settings.json would have bundled the module under 2.4.0's gate.

import json
import os
import shutil
import types

import pytest

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_spec(tmp_path, settings):
    root = tmp_path / "project"
    (root / "app").mkdir(parents=True)
    shutil.copy(os.path.join(_PROJECT, "app", "__init__.py"), root / "app" / "__init__.py")
    arch = root / "modules" / "immersion_architect"
    arch.mkdir(parents=True)
    (arch / "architect_settings.json").write_text('{"words_per_day": 12}', encoding="utf-8")
    (root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    seen = {}

    class _Analysis:
        def __init__(self, scripts, **kw):
            seen.update(kw)
            self.pure, self.scripts, self.binaries, self.datas = [], [], [], kw["datas"]

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda name: ([], [], [])
    fakes = {"PyInstaller": types.ModuleType("PyInstaller"),
             "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
             "PyInstaller.utils.hooks": hooks}
    with open(os.path.join(_PROJECT, "packaging", "Surasura.spec"), encoding="utf-8") as f:
        code = compile(f.read(), "Surasura.spec", "exec")
    here = os.getcwd()
    os.chdir(root)
    try:
        with patch.dict(sys.modules, fakes):
            exec(code, {"Analysis": _Analysis, "PYZ": lambda *a, **k: None,
                        "EXE": lambda *a, **k: None, "COLLECT": lambda *a, **k: None,
                        "__name__": "__main__"})
    finally:
        os.chdir(here)
    return seen


@pytest.mark.parametrize("settings", [{}, {"hide_satoru": False}, {"hide_satoru": True}])
def test_every_build_excludes_the_immersion_architect(tmp_path, settings):
    """2.4.0 bundled it unless hide_satoru was set; from 2.5 nothing a settings.json says brings it in."""
    seen = _run_spec(tmp_path, settings)
    assert "modules.immersion_architect" in seen["excludes"]


def test_no_build_ships_architect_settings(tmp_path):
    seen = _run_spec(tmp_path, {"hide_satoru": False})
    assert not [d for d in seen["datas"] if "architect_settings" in str(d[0])]
    assert not [d for d in seen["datas"] if "immersion_architect" in str(d[1])]


def test_the_prebuild_gate_never_runs_the_architect_suite():
    """package_app runs a module's suite before a build only when the module ships; it never does."""
    import package_app
    for settings in ({}, {"hide_satoru": False}):
        dirs = package_app._included_module_test_dirs(settings)
        assert not [d for d in dirs if "immersion_architect" in d]
