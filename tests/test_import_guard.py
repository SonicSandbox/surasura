"""The services stay Qt-free, Tk-free and pandas-free (W1.3; the window's spec 04 §4.1, 01 §1.6).

What a wrong answer would cost: a service that pulls in tkinter or Qt can't run headless (the command line, Connect, the
tests), and one that pulls in pandas costs every window and every check its ~0.35 s import; Qt imported outside the
window's own folders would put the GPL-only stack into the command line and Connect, which ship without it.

Each module is imported alone, in a fresh interpreter, and what it brought in is read from `sys.modules`.

From W2.1 (the shell) the window exists, and the guard also holds its edges: the window imports only the Qt modules the
stack names (01 §1.1: QtCore, QtGui, QtWidgets, QtNetwork, QtSvg — a GPL-only or WebEngine module would be a new
dependency), and the command line and `app_entry.py` reach the window only from the default start, never on import.
"""
import ast
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
    """Qt lives under app/qt/ and modules/*/qt_*.py only (01 §1.6)."""
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


# --- The window's own imports (W2.1) ------------------------------------------------------------------------------- #
ALLOWED_QT = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg", "sip"}
_QT_NAMES = re.compile(r"^\s*(?:from\s+PyQt6\.(\w+)\s+import|from\s+PyQt6\s+import\s+([\w ,]+)|import\s+PyQt6\.(\w+))",
                       re.M)


def qt_modules_named(source):
    """The PyQt6 modules a source imports: `from PyQt6.QtX import …`, `from PyQt6 import QtX, …`, `import PyQt6.QtX`."""
    names = set()
    for dotted, listed, imported in _QT_NAMES.findall(source):
        if listed:
            names.update(n.strip() for n in listed.split(",") if n.strip())
        names.update(n for n in (dotted, imported) if n)
    return names


def _window_files():
    files = []
    for where, dirs, names in os.walk(os.path.join(ROOT, "app", "qt")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        files += [os.path.join(where, n) for n in names if n.endswith(".py")]
    for where, dirs, names in os.walk(os.path.join(ROOT, "modules")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        files += [os.path.join(where, n) for n in names if n.startswith("qt_") and n.endswith(".py")]
    return files


def test_the_reader_of_qt_imports_sees_every_spelling():
    # The check's own witness: each way of naming a module is read, so a QtQml or a WebEngine import can't slip by.
    source = "\n".join(["from PyQt6.QtQml import QQmlEngine", "from PyQt6 import QtWebEngineWidgets, QtCore",
                        "import PyQt6.QtMultimedia", "    from PyQt6.QtWidgets import QWidget"])
    assert qt_modules_named(source) == {"QtQml", "QtWebEngineWidgets", "QtCore", "QtMultimedia", "QtWidgets"}


def test_the_window_imports_only_the_qt_modules_the_stack_names():
    """01 §1.1: QtCore, QtGui, QtWidgets, QtNetwork (single instance: a local pipe), QtSvg. QtTest is the tests' own."""
    files = _window_files()
    assert files, "app/qt/ holds the window from W2.1 on"
    stray = {}
    for path in files:
        with open(path, encoding="utf-8") as f:
            extra = qt_modules_named(f.read()) - ALLOWED_QT
        if extra:
            stray[os.path.relpath(path, ROOT)] = sorted(extra)
    assert stray == {}


def test_the_command_line_and_the_entry_never_reach_the_window_on_import():
    """The command line and Connect ship without Qt (01 §1.1); `app_entry.py` imports the window only to open it."""
    modules = ["app.cli.__main__", "app.cli.verbs", "app.cli.events", "app.cli.contract", "app_entry"]
    probe = "; ".join(["import sys, json", f"[__import__(m) for m in {modules!r}]",
                       "print(json.dumps(sorted(m for m in sys.modules if m == 'PyQt6' or "
                       "m.startswith(('PyQt6.', 'app.qt')))))"])
    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


def test_app_entry_imports_the_window_only_inside_a_function():
    # A module-level `import app.qt…` in app_entry.py would load Qt for every headless verb (the analyzer, the indexer,
    # the store's helper) before the dispatch even looks at argv.
    with open(os.path.join(ROOT, "app_entry.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    top = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            top.append(node.module or "")
    assert not [m for m in top if m == "PyQt6" or m.startswith(("PyQt6.", "app.qt"))]
