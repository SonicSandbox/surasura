"""No process Surasura starts opens a console window (TERM-POPUPS, 3.0.21; the suite's own: run_tests.py, 3.0.18).

On Windows, a console program started by a process that has no console of its own gets a NEW console, with a window
that takes the focus. CREATE_NO_WINDOW gives a child a console with no window, and whatever that child starts in turn
shares it: no window anywhere below, flags or not (a worker pool's processes are started with no flags at all, by
Python's multiprocessing). DETACHED_PROCESS gives a child no console at all, so each console program IT starts
without flags of its own opens a window: Connect (surasura-cli.exe, a console program), the store's helper and the
window's *Restart now* from source were started that way, and their worker pools opened a window per worker.

The rule, read here from the source (AST, never imported): every process start in the app and the public modules
names `creationflags` with CREATE_NO_WINDOW, or runs only off Windows, or starts another program's own window
(`ALLOWED`, each with its reason); DETACHED_PROCESS only for another program (`DETACHED_ALLOWED`: Anki, hato, the
installer, the updater). run_tests.py starts every child through its two wrappers (`_run`, `_popen`). Then the three
starts that were DETACHED are started for real, from the app's own code, with a probe that starts a worker pool.
"""
import ast
import os
import re
import subprocess
import sys

import pytest

from tests.flake_lints import _parse, _text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The app and the public modules (a private module's own tests hold it to the same rule; tests/ is the harness's).
SCANNED = ("app", os.path.join("modules", "junban"), os.path.join("modules", "youtube_downloader"), "app_entry.py")
STARTS = {"Popen", "run", "call", "check_call", "check_output"}       # subprocess's
WRAPPERS = {"popen_below_normal", "popen_idle", "_popen"}            # power's two, Anki Miner's: Popen's own keywords
NO_WINDOW = re.compile(r"NO_WINDOW|no_window|\b0x0*8000000\b|\b134217728\b")
DETACHED = re.compile(r"DETACHED_PROCESS|\b8 \| 512\b|\b0x0*8 \| ")
_ON_WINDOWS = {"sys.platform == 'win32'", "os.name == 'nt'", "sys.platform.startswith('win')"}
_OFF_WINDOWS = {"sys.platform != 'win32'", "os.name != 'nt'", "sys.platform == 'darwin'", "sys.platform == 'linux'",
                "sys.platform.startswith('linux')", "not sys.platform.startswith('win')"}

# "file:function" (the function whose body starts it) -> why it needs no flag.
ALLOWED = {
    "app/qt/screens.py:open_with_program": "the learner's own player for ▶ (`play.program_allowed`): a program whose "
                                           "window is what the press asks for",
    "app/qt/screens.py:show_in_folder": "Explorer at the file: a windowed program, never a console",
    "app/static_html_generator.py:open_as_app": "the 2.x report in a browser's app window: a windowed program",
    "modules/youtube_downloader/gui.py:open_output": "off Windows only: os.startfile is Windows', its AttributeError "
                                                      "every other system's (open / xdg-open)",
}
# "file:function" -> the program it starts DETACHED: another program's own window, never a console Python of ours.
DETACHED_ALLOWED = {
    "app/connect/open_anki.py:start": "Anki, a windowed program (Connect opening it at a Windows session's start)",
    "app/services/tools_found.py:start_hato": "hato's window, started as Anki is",
    "app/updater.py:launch_installer": "the installer (frozen only): a windowed program that outlives us",
    "app/updater.py:_launch_swapper": "updater.exe (frozen only): a windowed program (updater.spec console=False)",
    "app/updater.py:launch_helper": "updater.exe (frozen only): a windowed program (updater.spec console=False)",
}


_MAY_START = re.compile(r"subprocess|popen_")     # a file without either starts nothing: it is never parsed
_SCAN = {}


def _files():
    """The scanned .py files that may start a process, as paths from the top (read once a run: flake_lints' `_text`)."""
    for top in SCANNED:
        if os.path.isfile(os.path.join(ROOT, top)):
            names = [top]
        else:
            names = []
            for folder, dirs, files in os.walk(os.path.join(ROOT, top)):
                dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
                names += [os.path.relpath(os.path.join(folder, n), ROOT) for n in sorted(files) if n.endswith(".py")]
        yield from (n for n in names if _MAY_START.search(_text(ROOT, n)))


def _every_start():
    """{file: its starts} for every scanned file, worked out once for the four guards below."""
    if not _SCAN:
        _SCAN.update({rel.replace(os.sep, "/"): _starts(rel) for rel in _files()})
    return _SCAN


def _starts(rel):
    """Each process start in `rel` -> (line, its function's name, the call, the function's node, off Windows)."""
    tree = _parse(ROOT, rel)
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "subprocess"
                for a in n.names if a.name in STARTS}
    found = []

    def visit(node, func, off):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node
        if isinstance(node, ast.If):
            test = ast.unparse(node.test)
            visit(node.test, func, off)
            for child in node.body:
                visit(child, func, off or test in _OFF_WINDOWS)
            for child in node.orelse:
                visit(child, func, off or test in _ON_WINDOWS)
            return
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            subprocess_call = (isinstance(f, ast.Attribute) and name in STARTS and isinstance(f.value, ast.Name)
                               and f.value.id == "subprocess") or (isinstance(f, ast.Name) and name in imported)
            if subprocess_call or name in WRAPPERS:
                found.append((node.lineno, func.name if func else "<module>", node, func, off))
        for child in ast.iter_child_nodes(node):
            visit(child, func, off)
    visit(tree, None, False)
    return found


def _said(node, func):
    """The text of `node` and of every assignment in `func` that a name in it comes from (three steps back)."""
    texts, names = [ast.unparse(node)], {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    for _ in range(3):
        more = set()
        for n in ast.walk(func) if func else ():
            targets, value = (), None
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets, value = (n.targets if isinstance(n, ast.Assign) else [n.target]), n.value
            elif isinstance(n, ast.For):
                targets, value = [n.target], n.iter
            bound = {m.id for target in targets for m in ast.walk(target) if isinstance(m, ast.Name)}
            if value is not None and bound & names:
                texts.append(ast.unparse(value))
                more |= {m.id for m in ast.walk(value) if isinstance(m, ast.Name)}
        names = more - names
    return " ".join(texts)


def _flags(call, func):
    """What the start's creationflags say -> (named at all, its text): the keyword, or a `**` dict that holds it."""
    for k in call.keywords:
        if k.arg == "creationflags":
            return True, _said(k.value, func)
    for k in call.keywords:
        if k.arg is None:
            text = _said(k.value, func)
            if "creationflags" in text:
                return True, text
    return False, ""


def _pass_through(call, func):
    """A wrapper handing its own **kwargs on (power.popen_below_normal / popen_idle, anki_miner._popen): its callers
    are read here, each naming its flags."""
    if func is None or func.name not in WRAPPERS or func.args.kwarg is None:
        return False
    return any(k.arg is None and isinstance(k.value, ast.Name) and k.value.id == func.args.kwarg.arg
               for k in call.keywords)


def _where(rel, line, name):
    return f"{rel}:{line} {name}"


def test_every_process_the_app_starts_opens_no_console_window():
    """A start that names no CREATE_NO_WINDOW opens a console window for a learner whenever the program doing the
    starting has no console (a windowed Surasura.exe, a Connect started on its own console): ffmpeg for ▶, Anki Miner,
    tsubasa, git, uv, yt-dlp — each a console program."""
    missing = []
    for rel, starts in _every_start().items():
        for line, name, call, func, off in starts:
            key = f"{rel}:{name}"
            if off or key in ALLOWED or key in DETACHED_ALLOWED or _pass_through(call, func):
                continue
            named, text = _flags(call, func)
            if not (named and NO_WINDOW.search(text)):
                missing.append(_where(rel, line, name))
    assert missing == [], ("each start names creationflags with CREATE_NO_WINDOW (0x08000000), or says why not in "
                           "ALLOWED: " + "; ".join(missing))


def test_only_another_programs_window_is_started_detached():
    """DETACHED_PROCESS leaves a child no console at all: a Python of ours started so opened a console window for each
    worker of a pool it started (Connect, the store's helper, *Restart now*). Only another program's window may be."""
    detached = []
    for rel, starts in _every_start().items():
        for line, name, call, func, off in starts:
            if not off and DETACHED.search(_flags(call, func)[1]) and f"{rel}:{name}" not in DETACHED_ALLOWED:
                detached.append(_where(rel, line, name))
    assert detached == [], "started DETACHED: " + "; ".join(detached)


def test_every_allowed_entry_still_names_a_start_and_says_why():
    """An entry whose function no longer starts anything would let the next start there go unread."""
    starts = {f"{rel}:{name}" for rel, found in _every_start().items() for _line, name, _call, _func, _off in found}
    for table in (ALLOWED, DETACHED_ALLOWED):
        for key, why in table.items():
            assert key in starts, f"{key} starts no process any more: take its entry out"
            assert len(why) > 20, key


def test_run_tests_starts_every_child_through_its_two_wrappers():
    """run_tests.py's children have no console window when it has none (`_quiet`): only through `_run` / `_popen`."""
    direct = [_where("run_tests.py", line, name) for line, name, call, _func, _off in _starts("run_tests.py")
              if getattr(call.func, "attr", None) in STARTS and name not in ("_run", "_popen")]
    assert direct == []


# --- The three starts that were DETACHED, for real (Windows) ------------------------------------------------------- #
# The probe: has it a console, has that console a window, and has the worker of a spawn pool it starts (no flags: as
# the walk's cores, the indexer's and the look's pools are started) a window? Started DETACHED it wrote
# "False 0 <a window>"; started with CREATE_NO_WINDOW, "True 0 0".
PROBE = """import ctypes, multiprocessing, sys
from concurrent.futures import ProcessPoolExecutor

def window(_):
    import ctypes
    return ctypes.windll.kernel32.GetConsoleWindow() or 0

if __name__ == "__main__":
    k = ctypes.windll.kernel32
    with ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn")) as pool:
        worker = pool.submit(window, 0).result(timeout=90)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(f"{bool(k.GetConsoleCP())} {k.GetConsoleWindow() or 0} {worker}")
"""


def _probe(tmp_path):
    probe, out = tmp_path / "probe.py", tmp_path / "said.txt"
    probe.write_text(PROBE, encoding="utf-8")
    return str(probe), str(out)


def _said_by(proc, out):
    proc.wait(timeout=120)
    with open(out, encoding="utf-8") as f:
        return f.read().split()


@pytest.mark.skipif(sys.platform != "win32", reason="a console window is Windows'")
def test_connects_kick_starts_it_on_a_console_with_no_window(tmp_path, monkeypatch):
    from app import library_store, settings_manager
    from app.connect import kick
    probe, out = _probe(tmp_path)
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    monkeypatch.setattr(settings_manager, "connect_on", lambda settings: True)
    monkeypatch.setattr(settings_manager, "paused", lambda settings, what: False)
    monkeypatch.setattr(library_store, "update_staged", lambda **kw: False)
    monkeypatch.setattr(kick, "running", lambda: False)
    monkeypatch.setattr(kick, "command", lambda: [sys.executable, probe, out])
    assert _said_by(kick.kick({}), out) == ["True", "0", "0"]


@pytest.mark.skipif(sys.platform != "win32", reason="a console window is Windows'")
def test_the_store_helper_starts_on_a_console_with_no_window(tmp_path, monkeypatch, real_store_helper):
    from app import library_store
    probe, out = _probe(tmp_path)
    monkeypatch.setattr(library_store, "update_staged", lambda *a, **kw: False)
    monkeypatch.setattr(library_store, "maintain_running", lambda *a, **kw: False)
    monkeypatch.setattr(library_store, "_helper_args", lambda *a: [sys.executable, probe, out])
    monkeypatch.setattr(library_store, "_spawned", {})
    assert _said_by(library_store.spawn_maintain("ja"), out) == ["True", "0", "0"]


@pytest.mark.skipif(sys.platform != "win32", reason="a console window is Windows'")
def test_restart_now_from_source_starts_on_a_console_with_no_window(tmp_path):
    from app.qt import shell
    probe, out = _probe(tmp_path)
    assert _said_by(shell.relaunch([probe, out]), out) == ["True", "0", "0"]
