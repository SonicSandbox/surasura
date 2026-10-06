"""The services stay Qt-free, Tk-free and pandas-free (W1.3; the window's spec 04 §4.1, 01 §1.6).

What a wrong answer would cost: a service that pulls in tkinter or Qt can't run headless (the command line, Connect, the
tests), and one that pulls in pandas costs every window and every check its ~0.35 s import; Qt imported outside the
window's own folders would put the GPL-only stack into the command line and Connect, which ship without it.

Each module is imported alone, in a fresh interpreter, and what it brought in is read from `sys.modules`.
"""
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN = ("tkinter", "_tkinter", "PyQt6", "PySide6", "PyQt5", "PySide2", "pandas")


def _services_modules():
    folder = os.path.join(ROOT, "app", "services")
    names = sorted(f[:-3] for f in os.listdir(folder) if f.endswith(".py") and f != "__init__.py")
    return ["app.services"] + [f"app.services.{n}" for n in names] + ["app.theme", "app.settings_placement"]


def test_the_list_holds_every_service():
    assert set(_services_modules()) >= {"app.services.settings", "app.services.jobs", "app.services.generate",
                                        "app.services.progress", "app.services.status", "app.theme",
                                        "app.settings_placement"}


@pytest.mark.parametrize("module", _services_modules())
def test_importing_a_service_brings_in_no_qt_tk_or_pandas(module):
    probe = (f"import sys, json; import {module}; "
             f"print(json.dumps([m for m in {list(FORBIDDEN)!r} if m in sys.modules]))")
    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [], module


_QT = re.compile(r"^\s*(?:from|import)\s+(PyQt6|PySide6|PyQt5|PySide2)\b", re.M)


def test_no_file_outside_the_windows_folders_imports_qt():
    """Qt lives under app/qt/ and modules/*/qt_*.py only (01 §1.6); none of it exists before W2.1."""
    found = []
    for top in ("app", "modules"):
        for where, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests", "vendor")]
            rel = os.path.relpath(where, ROOT).replace("\\", "/")
            if rel == "app/qt" or rel.startswith("app/qt/"):
                continue
            for name in files:
                if not name.endswith(".py") or (top == "modules" and name.startswith("qt_")):
                    continue
                with open(os.path.join(where, name), encoding="utf-8", errors="replace") as f:
                    if _QT.search(f.read()):
                        found.append(f"{rel}/{name}")
    assert found == []
