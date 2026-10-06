"""The Immersion Architect (悟) is out of 2.5: no build bundles it (S1.1 A5), and the dashboard has no button for it
(L2.1 A5)."""
import os
import sys
from unittest.mock import patch


def test_the_dashboard_has_no_satori_button_and_never_imports_the_architect():
    """L2.1 A5: the dashboard holds no 悟 button and never imports the module, so a leftover
    modules/immersion_architect folder (modules/ has no __init__.py, so its import would succeed) brings nothing
    back."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "main.py")
    source = open(path, encoding="utf-8").read()
    for name in ("immersion_architect", "btn_satori", "update_satori_visibility", "hide_satoru", "悟"):
        assert name not in source, name


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
