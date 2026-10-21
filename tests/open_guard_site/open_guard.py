"""No test opens a browser or a file viewer (2026-10-21: tests opened Journey / report pages, one under a test root, in
Sonic's own Chrome and left them there). Installed by tests/harness_guards.py in every pytest process, and in every
Python child a test starts: this folder rides first on the child's PYTHONPATH (the harness's Popen watch puts it
there), so its `sitecustomize.py` installs the same guard before the child's own code runs — the analyzer's report
opening through `webbrowser`, `os.startfile` or Chrome in app mode included.

Each route is refused, never carried out, and recorded as one JSON line in the file SURASURA_TEST_OPEN_LOG names,
with the test running then (PYTEST_CURRENT_TEST, inherited by a child) and the code that asked; the harness reads the
file at each test's end and fails that test naming each line:
* `webbrowser.open` / `open_new` / `open_new_tab` (answer: True, as an opened page);
* `os.startfile` (a page, a file or a folder in its program);
* PyQt6's `QDesktopServices.openUrl` (answer: True), when PyQt6 is installed;
* a child that is a browser or a viewer — chrome / msedge / firefox / brave / iexplore / explorer, `cmd /c start`,
  `xdg-open`, `open` — started in its place as a Python that does nothing.
Nothing here imports the app."""
import json
import os
import re
import subprocess
import sys
import threading
import traceback

LOG = "SURASURA_TEST_OPEN_LOG"
BY = "SURASURA_TEST_OPEN_BY"            # a child's: the test that started it (never PYTEST_CURRENT_TEST: path rules read it)
HERE = os.path.dirname(os.path.abspath(__file__))
VIEWERS = {"chrome", "msedge", "firefox", "brave", "iexplore", "explorer", "xdg-open", "open", "opera", "vivaldi"}
_PROJECT = os.path.dirname(os.path.dirname(HERE))
_LOCK = threading.Lock()


def _where():
    """The project's own frames nearest the call, innermost first (never this file or the harness)."""
    frames = [f for f in traceback.extract_stack()[:-3] if f.filename.startswith(_PROJECT)
              and os.path.basename(f.filename) not in ("open_guard.py", "harness_guards.py", "sitecustomize.py")]
    return " <- ".join(f"{os.path.relpath(f.filename, _PROJECT)}:{f.lineno} {f.name}" for f in reversed(frames[-4:]))


def record(route, target):
    """One refused open, appended to the log (a child's line too: the file is shared by the run)."""
    line = {"route": route, "target": str(target),
            "test": os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get(BY) or "between tests",
            "thread": threading.current_thread().name, "pid": os.getpid(), "where": _where()}
    path = os.environ.get(LOG)
    if not path:
        sys.stderr.write(f"OPEN REFUSED (no {LOG}): {line}\n")
        return
    with _LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _words(command):
    """A child's command -> (its program, the rest), lower-cased words; a string is split as Windows quotes it."""
    if isinstance(command, (list, tuple)):
        parts = [os.fsdecode(p) if isinstance(p, (bytes, os.PathLike)) else str(p) for p in command]
    elif isinstance(command, (str, bytes, os.PathLike)):
        text = os.fsdecode(command).strip()
        if text.startswith('"') and '"' in text[1:]:
            end = text.index('"', 1)
            parts = [text[1:end]] + text[end + 1:].split()
        else:
            parts = text.split()
    else:
        return "", []
    return (parts[0] if parts else ""), [p.lower() for p in parts[1:]]


def viewer(command):
    """Whether a child's command starts a browser or a viewer (its program's name), or `cmd /c start …`."""
    program, rest = _words(command)
    name = os.path.splitext(os.path.basename(program))[0].lower()
    return name in VIEWERS or (name == "cmd" and "start" in rest)


# Surasura's own code in a child's command (the harness's Anki check reads the same rule).
SURASURA_CODE = re.compile(r"app_entry|\b(?:app|modules)[./\\]|\b(?:from|import) (?:app|modules)\b")


def python_child(command):
    """Whether a child is a Python running Surasura's code (its program named python*, or this one; app_entry, -m app…,
    an `import app` in its -c). Any other Python child — a stand-in for Anki started with a clean environment — keeps
    its environment as given."""
    program, rest = _words(command)
    if not program or not (os.path.basename(program).lower().startswith("python")
                           or os.path.normcase(program) == os.path.normcase(sys.executable)):
        return False
    words = command if isinstance(command, (list, tuple)) else [command]
    return bool(SURASURA_CODE.search(" ".join(os.fsdecode(w) if isinstance(w, (bytes, os.PathLike)) else str(w)
                                              for w in words)))


def child_env(env):
    """A Python child's environment with this guard first on its PYTHONPATH and the run's log named (a copy)."""
    env = dict(os.environ if env is None else env)
    paths = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if not paths or os.path.normcase(paths[0]) != os.path.normcase(HERE):
        env["PYTHONPATH"] = os.pathsep.join([HERE] + [p for p in paths if os.path.normcase(p) != os.path.normcase(HERE)])
    if os.environ.get(LOG):
        env.setdefault(LOG, os.environ[LOG])
    env[BY] = os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get(BY) or "between tests"
    return env


def guard_popen(args, kwargs):
    """subprocess.Popen's arguments as the guard lets them through -> (args, kwargs): a viewer becomes a Python that
    does nothing (recorded); a Python child carries the guard."""
    command = kwargs.get("args", args[0] if args else None)
    if command is None:
        return args, kwargs
    if viewer(command):
        record("a browser or viewer started as a child", command)
        harmless = [sys.executable, "-c", "pass"]
        if "args" in kwargs:
            kwargs = dict(kwargs, args=harmless)
        else:
            args = (harmless,) + tuple(args[1:])
        kwargs = dict(kwargs, shell=False)
    elif python_child(command):
        kwargs = dict(kwargs, env=child_env(kwargs.get("env")))
    return args, kwargs


def install(qt=True):
    """Every route refused and recorded, in this process. Safe to call twice. `qt`: PyQt6's route too (the pytest
    process; a child imports no Qt for it — a Qt window run as a test's child is out of its reach)."""
    import webbrowser
    if getattr(webbrowser.open, "_open_guard", False):
        return

    def refuse(name):
        def opened(url, *a, **k):
            record(f"webbrowser.{name}", url)
            return True
        opened._open_guard = True
        return opened
    for name in ("open", "open_new", "open_new_tab"):
        setattr(webbrowser, name, refuse(name))

    if hasattr(os, "startfile"):
        def startfile(path, *a, **k):
            record("os.startfile", path)
        startfile._open_guard = True
        os.startfile = startfile

    started = subprocess.Popen.__init__
    if not getattr(started, "_open_guard", False):
        def __init__(self, *args, **kwargs):
            args, kwargs = guard_popen(args, kwargs)
            started(self, *args, **kwargs)
        __init__._open_guard = True
        subprocess.Popen.__init__ = __init__

    if not qt:
        return
    try:
        from PyQt6.QtGui import QDesktopServices
    except Exception:
        return

    def open_url(url, *a, **k):
        record("QDesktopServices.openUrl", url.toString() if hasattr(url, "toString") else url)
        return True
    open_url._open_guard = True
    QDesktopServices.openUrl = staticmethod(open_url)
