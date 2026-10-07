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
# Read as Python reads them (the syntax tree), not as text: a parenthesised list, two modules on one `import`, `;`,
# a continued line, an import inside a function and `importlib.import_module("…")` all count (W2.1 review A7).
ALLOWED_QT = {"PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtNetwork", "PyQt6.QtSvg",
              "PyQt6.sip"}
_DYNAMIC = {"import_module", "__import__"}


def imports_of(source, module):
    """Every module `source` (the file of `module`, dotted) imports, anywhere in it, as absolute dotted names."""
    package = module.rsplit(".", 1)[0] if "." in module else ""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join(p for p in parts + ([base] if base else []) if p)
            names.add(base)
            names.update(f"{base}.{a.name}" for a in node.names if a.name != "*")
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if called in _DYNAMIC:
                names.add(node.args[0].value)
    return names


def _qt_names(names):
    """The PyQt6 modules among `names` (`PyQt6.QtCore.QObject`, a name taken from a module, counts as its module)."""
    return {".".join(n.split(".")[:2]) for n in names if n == "PyQt6" or n.startswith("PyQt6.")}


def _module_of(path):
    rel = os.path.relpath(path, ROOT)[:-3].replace(os.sep, ".")
    return rel[:-9] if rel.endswith(".__init__") else rel


def _window_files():
    files = []
    for where, dirs, names in os.walk(os.path.join(ROOT, "app", "qt")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        files += [os.path.join(where, n) for n in names if n.endswith(".py")]
    for where, dirs, names in os.walk(os.path.join(ROOT, "modules")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        files += [os.path.join(where, n) for n in names if n.startswith("qt_") and n.endswith(".py")]
    return files


def _headless_files():
    """Every file that must never reach Qt: the app outside app/qt/, the modules outside their qt_*.py, the entry."""
    files = [os.path.join(ROOT, "app_entry.py")]
    for top in ("app", "modules"):
        for where, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests", "vendor")]
            rel = os.path.relpath(where, ROOT).replace("\\", "/")
            if rel == "app/qt" or rel.startswith("app/qt/"):
                continue
            files += [os.path.join(where, n) for n in names
                      if n.endswith(".py") and not (top == "modules" and n.startswith("qt_"))]
    return files


def test_the_reader_of_imports_sees_every_spelling():
    # The check's own witness: each way of naming a module is read, so a QtQml or a WebEngine import can't slip by.
    source = "\n".join([
        "from PyQt6 import (QtCore,", "    QtQml)",
        "import PyQt6.QtGui, PyQt6.QtWebEngineWidgets",
        "import os; import PyQt6.QtMultimedia",
        "from PyQt6.QtWidgets import \\", "    QWidget",
        "def later():", "    from app.qt import shell", "    importlib.import_module('PyQt6.QtQuick')",
        "    __import__('PyQt6.Qt3DCore')",
        "from .qt import style",
    ])
    names = imports_of(source, "app.cli.verbs")
    assert {"PyQt6.QtQml", "PyQt6.QtWebEngineWidgets", "PyQt6.QtMultimedia", "PyQt6.QtWidgets", "PyQt6.QtQuick",
            "PyQt6.Qt3DCore", "app.qt", "app.qt.shell", "app.cli.qt", "app.cli.qt.style"} <= names


def test_the_window_imports_only_the_qt_modules_the_stack_names():
    """01 §1.1: QtCore, QtGui, QtWidgets, QtNetwork (single instance: a local pipe), QtSvg. QtTest is the tests' own."""
    files = _window_files()
    assert files, "app/qt/ holds the window from W2.1 on"
    stray = {}
    for path in files:
        with open(path, encoding="utf-8") as f:
            extra = _qt_names(imports_of(f.read(), _module_of(path))) - ALLOWED_QT
        if extra:
            stray[os.path.relpath(path, ROOT)] = sorted(extra)
    assert stray == {}


def test_nothing_outside_the_window_reaches_qt_or_the_window_but_the_entrys_one_door():
    """Nowhere outside app/qt/ (and modules' qt_*.py) imports PyQt6 or app.qt — inside a function, through importlib,
    relatively — except app_entry.py's `_qt_window`, the default start's one door (01 §1.6)."""
    found = {}
    for path in _headless_files():
        module = _module_of(path)
        with open(path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        if module == "app_entry":
            door = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_qt_window"]
            outside = [n for n in tree.body if n not in door]
            source = "\n".join(ast.unparse(n) for n in outside)
            assert door and imports_of(ast.unparse(door[0]), module) >= {"app.qt.shell"}
        bad = {n for n in imports_of(source, module) if n == "PyQt6" or n.startswith(("PyQt6.", "app.qt"))}
        if bad:
            found[os.path.relpath(path, ROOT)] = sorted(bad)
    assert found == {}


def test_the_window_loads_only_the_allowed_qt_modules():
    """Imported, not just named: every module of app/qt/ in a fresh interpreter, and the PyQt6 modules it pulled in."""
    modules = sorted(_module_of(p) for p in _window_files() if os.sep + "app" + os.sep + "qt" + os.sep in p)
    probe = "; ".join(["import sys, json", f"[__import__(m) for m in {modules!r}]",
                       "print(json.dumps(sorted(m for m in sys.modules if m == 'PyQt6' or m.startswith('PyQt6.'))))"])
    env = dict(os.environ, PYTHONPATH=ROOT, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    loaded = set(json.loads(proc.stdout.strip().splitlines()[-1]))
    assert loaded and loaded <= ALLOWED_QT, sorted(loaded - ALLOWED_QT)


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
