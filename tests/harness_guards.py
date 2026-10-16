"""The guards every test suite runs under — the core suite (tests/conftest.py) and each module suite's own conftest
(modules/*/tests/conftest.py), which import them: a module suite is its own pytest process (`run_tests.py --all`, or
`python -m pytest modules/<name>/tests`) and never loads tests/conftest.py.

* the real Houseki roots are out of reach: the per-user bases (%LOCALAPPDATA%, %APPDATA%, XDG_DATA_HOME) point at a
  folder of the run's own from the moment a conftest imports this, for the whole process and every child it starts,
  removed at its exit (`_redirect_user_bases`) — in any pytest run, wrapped or plain;
* the data roots a run would reach without a test root: a test that writes this checkout's local data folder, or makes
  or writes the Houseki roots, fails (`_guard_real_local_data`);
* no moment of the run without a test's guard: PYTEST_CURRENT_TEST names the gap between two tests and the end of the
  run, so a worker thread that outlived its test is refused a real per-user path there too;
* Tk interpreters are freed on the main thread, never by a worker's collection (Windows fatal 0x80000003);
* a test's child process never outlives the run: one still running at the end is ended, named, and fails the run.

A conftest takes them by importing these names at its top level and never binding them again (pytest registers a
conftest's hooks and fixtures by name): `EVERY_SUITE` below, plus `pytest_sessionfinish` — a module suite's conftest
imports that hook itself (tests/test_harness_guards.py checks every one); tests/conftest.py, whose session-finish hook
does more, calls `session_finish_guards()` from its own. Their own tests: tests/test_harness_guards.py.
"""
import atexit
import os
import shutil
import sys
import tempfile
import threading
import time

import pytest

EVERY_SUITE = ("_guard_real_local_data", "pytest_collection", "pytest_runtest_teardown", "pytest_runtestloop")


# --- The real per-user roots are out of reach --------------------------------------------------------------------- #
# path_utils refuses the real per-user folders while PYTEST_CURRENT_TEST is set, and every test runs under a test root
# — but code that reaches them where neither holds (a module imported before the run starts, a window's worker past the
# end of the run, a route that builds the path itself) made the real, empty %LOCALAPPDATA%\Houseki\Surasura\<key> from
# a plain `python -m pytest tests/qt/test_drag.py`, and only the other runs' guards saw it. So every pytest run moves
# the per-user bases themselves: nothing in it, or started by it, can reach the real Houseki roots.
ROOTS_PREFIX = "surasura-test-bases-"


def _redirect_user_bases():
    """Point %LOCALAPPDATA%, %APPDATA% and XDG_DATA_HOME at a new folder in TEMP (removed when this process exits);
    PYTHONUSERBASE keeps naming this user's packages (Python looks for them under %APPDATA%), for the children too."""
    import site
    os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())
    bases = tempfile.mkdtemp(prefix=ROOTS_PREFIX)
    atexit.register(shutil.rmtree, bases, True)   # before any test's exit hook, so it runs after them
    for name, sub in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming"), ("XDG_DATA_HOME", "Local")):
        os.makedirs(os.path.join(bases, sub), exist_ok=True)
        os.environ[name] = os.path.join(bases, sub)


_redirect_user_bases()


def _real_local_data_folder():
    """This checkout's per-install local data folder as the run reaches it without a test root (under its own bases:
    path_utils.get_local_data_path()), computed once, here, before any test can mock path_utils."""
    from app import path_utils
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(path_utils._local_data_root(), path_utils._install_key(project_root))


_REAL_LOCAL_DATA = _real_local_data_folder()


def _real_houseki_roots():
    """The Houseki roots a source run uses (under the run's own bases) — path_utils.local_data_root() and get_persistent_user_data_path() with
    no test root: %LOCALAPPDATA%\\Houseki\\Surasura and %APPDATA%\\Houseki\\Surasura — computed once, here, before any
    test can point the environment or path_utils elsewhere."""
    from app import path_utils
    return tuple(os.path.join(base, path_utils.VENDOR, path_utils.DATA_NAME)
                 for base in (path_utils._local_base(), path_utils._roaming_base()))


_REAL_HOUSEKI_ROOTS = _real_houseki_roots()


def _root_state(root):
    """Whether `root` exists, and the names at its top. Not deeper: other sessions' own source runs write inside it
    (their token stores, their per-install folders); a test reaching it makes it, or a name at its top."""
    try:
        return True, sorted(os.listdir(root))
    except OSError:
        return os.path.isdir(root), []


def _folder_state(folder):
    """Every file under `folder` with its size and mtime; (False, []) when the folder doesn't exist."""
    files = []
    for dirpath, _dirs, names in os.walk(folder):
        for name in names:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            files.append((os.path.relpath(full, folder), st.st_size, st.st_mtime_ns))
    return os.path.isdir(folder), sorted(files)


@pytest.fixture(autouse=True)
def _guard_real_local_data():
    """Fail any test that writes the real local data folder (the command line's logs, locks and events, P0.3
    02-contract §6). get_local_data_path() already refuses under pytest without SURASURA_TEST_ROOT; this catches a
    path built some other way, and a subprocess started without the test root. (Running this checkout's own app or
    `python -m app.cli` by hand during a test run writes that folder too, and fails whichever test is running.)
    The real Houseki local and roaming roots too (S3.1): a test that makes either, or a name at its top, fails — a
    read of the roaming root once made the real %APPDATA%\\Houseki\\Surasura."""
    before = _folder_state(_REAL_LOCAL_DATA)
    roots = [_root_state(root) for root in _REAL_HOUSEKI_ROOTS]
    yield
    assert _folder_state(_REAL_LOCAL_DATA) == before, \
        f"a test wrote the real local data folder {_REAL_LOCAL_DATA}: use the test root"
    for root, was in zip(_REAL_HOUSEKI_ROOTS, roots):
        assert _root_state(root) == was, f"a test made or wrote the real Houseki root {root}: use the test root"


def _clear_destroyed_default_root():
    try:
        import tkinter
    except ImportError:
        return
    root = getattr(tkinter, "_default_root", None)
    if root is not None:
        try:
            root.tk.call("winfo", "exists", ".")
        except tkinter.TclError:
            tkinter._default_root = None


# --- Tk interpreters are freed on the main thread ----------------------------------------------------------------- #
# A Tk root's interpreter must be deleted by the thread that made it: freed on another, Tcl aborts the whole process
# (Windows fatal 0x80000003, "Garbage-collecting" on a worker in the dump). The app keeps one root for its whole life;
# the tests make hundreds, and a destroyed one left in a reference cycle, or held last by a window's worker thread, was
# freed wherever the next collection or that thread's end happened — a worker of the next test (test_connect_window,
# then test_am_release_ui_gaps, test_connect_window_hato_gaps, test_library_store_switch: one file fixed at a time).
# Only the interpreter object (`root.tk`) deletes the interpreter when it is freed, and it points at nothing in Python:
# so the harness holds the interpreter of every root the main thread makes — the root, its widgets and their cycles
# are freed wherever they are, as before — and lets it go only on the main thread, after a test's teardown, once
# nothing else holds it: the last reference dropped there deletes the interpreter there.

_TK_INTERPS = []    # the interpreter of every Tk root the main thread made that something may still hold


def _refs_held_only_here():
    """What `sys.getrefcount` reads for an object a list alone holds (its own argument included), measured here, so a
    Python that counts references differently changes this number, never the meaning of the check."""
    held = [object()]
    return sys.getrefcount(held[0])


_ONLY_HERE = _refs_held_only_here()


def _hold_tk_interpreters():
    try:
        import tkinter
    except ImportError:
        return
    if getattr(tkinter.Tk.__init__, "_held_by_conftest", False):
        return
    made = tkinter.Tk.__init__

    def __init__(self, *args, **kwargs):
        made(self, *args, **kwargs)
        if threading.current_thread() is threading.main_thread():     # (one made on a worker is that thread's own)
            _TK_INTERPS.append(self.tk)
    __init__._held_by_conftest = True
    tkinter.Tk.__init__ = __init__


_hold_tk_interpreters()


def _free_tk_interpreters():
    """On the main thread: let go of every held interpreter nothing else holds (no root, widget, variable or font), so
    it is deleted here. One still held — by a root in a cycle not yet collected, or a thread still running — stays
    held, for a later call."""
    if not _TK_INTERPS or threading.current_thread() is not threading.main_thread():
        return
    _clear_destroyed_default_root()
    i = 0
    while i < len(_TK_INTERPS):
        if sys.getrefcount(_TK_INTERPS[i]) <= _ONLY_HERE:
            del _TK_INTERPS[i]                  # the last reference: the interpreter is deleted here
        else:
            i += 1


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    yield
    _between_tests()
    _free_tk_interpreters()
    _forget_ended_children(_CHILDREN)


# --- No moment of the run without a test's guard ------------------------------------------------------------------ #
# path_utils, the library store, the tools folder and the updater's RunOnce key refuse the real per-user folders while
# PYTEST_CURRENT_TEST is set — but pytest clears it after each test's teardown, and the test root (SURASURA_TEST_ROOT)
# is gone by then too. A window's worker thread that outlived its test (the re-plan host's loop, Connect's known-word
# mark) and reached a path in that gap, or after the last test, met neither: `store_path_for` made the real, empty
# %APPDATA%\Houseki\Surasura, and every test running then, in every shard, failed the real-root guard. So the variable
# names the gap itself: set from the start of the run, after every test's teardown, to the end of the process (pytest
# sets its own over it at each test's set-up).
BETWEEN_TESTS = "between tests (conftest: no test is running)"


def _between_tests():
    os.environ.setdefault("PYTEST_CURRENT_TEST", BETWEEN_TESTS)


def pytest_collection(session):
    _between_tests()


# --- A test's child process never outlives the run ---------------------------------------------------------------- #
# A child a test starts (subprocess.Popen, directly or through the app's code) and never ends kept running after the
# run: `slow.py` of test_a_second_tool_of_its_kind ran for an hour after its pytest had gone. Windows: every child this
# process starts is watched through a handle of its own (never the Popen's pipes: holding those would change how the
# child ends); one still running when the session ends gets a few seconds, then is ended and named, and the run fails.

_CHILDREN = []      # [pid, handle, command, the test that started it] for every child still running
_CHILD_ACCESS = 0x00100000 | 0x1000 | 0x0001        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | TERMINATE


def _watch_children():
    if sys.platform != "win32":
        return
    import subprocess
    if getattr(subprocess.Popen.__init__, "_watched_by_conftest", False):
        return
    started = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        started(self, *args, **kwargs)
        _watch_child(_CHILDREN, self.pid, kwargs.get("args", args[0] if args else None))
    __init__._watched_by_conftest = True
    subprocess.Popen.__init__ = __init__


def _watch_child(children, pid, command):
    import _winapi
    try:
        handle = _winapi.OpenProcess(_CHILD_ACCESS, False, pid)
    except OSError:                         # already gone
        return
    test = os.environ.get("PYTEST_CURRENT_TEST", "between tests").rsplit(" (", 1)[0]
    children.append([pid, handle, command, test])


def _forget_ended_children(children, wait_ms=0):
    """Drop (and close the handle of) every child that has ended, waiting up to `wait_ms` in all."""
    if not children:
        return
    import _winapi
    deadline = time.monotonic() + wait_ms / 1000
    for child in list(children):
        left = max(0, int((deadline - time.monotonic()) * 1000))
        if _winapi.WaitForSingleObject(child[1], left) == _winapi.WAIT_OBJECT_0:
            _winapi.CloseHandle(child[1])
            children.remove(child)


def _end_leaked_children(children, grace_ms=10000):
    """The children still running after `grace_ms`, each ended -> [(pid, command, the test that started it)]."""
    if not children:
        return []
    import _winapi
    _forget_ended_children(children, grace_ms)
    leaked = []
    for child in list(children):
        pid, handle, command, test = child
        try:
            _winapi.TerminateProcess(handle, 1)
        except OSError:
            pass
        _winapi.CloseHandle(handle)
        children.remove(child)
        leaked.append((pid, command, test))
    return leaked


@pytest.hookimpl(wrapper=True)
def pytest_runtestloop(session):
    """Once every test has run (not on Ctrl-C): a child still running after the grace (SURASURA_TEST_CHILD_GRACE_MS,
    10 s) is ended and named, and fails the run — counted in the closing line too ("1 leaked child")."""
    result = yield
    leaked = _end_leaked_children(_CHILDREN, int(os.environ.get("SURASURA_TEST_CHILD_GRACE_MS", "10000")))
    if leaked:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        for pid, command, test in leaked:
            line = (f"LEAKED CHILD PROCESS {pid}, still running after every test had ended (ended now): {command!r} "
                    f"from {test}")
            if reporter:
                reporter.write_sep("!", line, red=True)
                reporter.stats.setdefault("leaked child", []).append(line)
            else:
                print(line)
        session.testsfailed += len(leaked)
    return result


_watch_children()


def session_finish_guards():
    _free_tk_interpreters()     # what a still-running thread holds stays held, deleted at exit on this thread
    _end_leaked_children(_CHILDREN, grace_ms=0)     # an interrupted run's children: ended, nothing waited for


def pytest_sessionfinish(session, exitstatus):
    session_finish_guards()
