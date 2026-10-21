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
* a test's child process never outlives the run: one still running at the end is ended, named, and fails the run;
* no test reaches a real Anki: a connection to the AnkiConnect port is refused for the whole run, between tests and
  from a thread that outlived its test included, and fails the test (or the run) naming it (`_guard_anki_port`);
* no test opens a browser or a file viewer, in this process or a Python child it starts (tests/open_guard_site/): the
  open is refused and fails the test (or the run) naming it (`_guard_anki_port` claims them too).

A conftest takes them by importing these names at its top level and never binding them again (pytest registers a
conftest's hooks and fixtures by name): `EVERY_SUITE` below, plus `pytest_sessionfinish` and `pytest_configure` — a
module suite's conftest imports those hooks itself (tests/test_harness_guards.py checks every one); tests/conftest.py,
whose own hooks do more, calls `session_finish_guards()` and `configure_guards()` from them. Their own tests:
tests/test_harness_guards.py.
"""
import atexit
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback

import pytest

EVERY_SUITE = ("_guard_real_local_data", "_guard_anki_port", "pytest_collection", "pytest_runtest_protocol",
               "pytest_runtest_teardown", "pytest_runtestloop")


# --- The real per-user roots are out of reach --------------------------------------------------------------------- #
# path_utils refuses the real per-user folders while PYTEST_CURRENT_TEST is set, and every test runs under a test root
# — but code that reaches them where neither holds (a module imported before the run starts, a window's worker past the
# end of the run, a route that builds the path itself) made the real, empty %LOCALAPPDATA%\Houseki\Surasura\<key> from
# a plain `python -m pytest tests/qt/test_drag.py`, and only the other runs' guards saw it. So every pytest run moves
# the per-user bases themselves: nothing in it, or started by it, reaches the real Houseki roots through them. (A route
# past the variables — `expanduser` with one unset, the known-folder API, a path written out — still could: the guard
# below watches the true roots too.)
ROOTS_PREFIX = "surasura-test-bases-"
BASE_NAMES = ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME")
ORIGINAL_BASES = {name: os.environ.get(name) for name in BASE_NAMES}     # as the run was started: None = unset


def _redirect_user_bases():
    """Point %LOCALAPPDATA%, %APPDATA% and XDG_DATA_HOME at a new folder in TEMP (removed when this process exits);
    PYTHONUSERBASE keeps naming this user's packages (Python looks for them under %APPDATA%), for the children too."""
    import site
    os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())
    _forget_stale_bases()
    bases = tempfile.mkdtemp(prefix=ROOTS_PREFIX)
    atexit.register(shutil.rmtree, bases, True)   # before any test's exit hook, so it runs after them
    for name, sub in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming"), ("XDG_DATA_HOME", "Local")):
        os.makedirs(os.path.join(bases, sub), exist_ok=True)
        os.environ[name] = os.path.join(bases, sub)


def _forget_stale_bases(older_than=86400):
    """Remove the bases a run killed before its exit left in TEMP (a day old or more)."""
    temp = tempfile.gettempdir()
    try:
        names = [n for n in os.listdir(temp) if n.startswith(ROOTS_PREFIX)]
    except OSError:
        return
    for name in names:
        path = os.path.join(temp, name)
        try:
            if time.time() - os.path.getmtime(path) > older_than:
                shutil.rmtree(path, True)
        except OSError:
            pass


def _real_local_data_folder():
    """This checkout's per-install local data folder as the run reaches it without a test root (under its own bases:
    path_utils.get_local_data_path()), computed once, here, before any test can mock path_utils."""
    from app import path_utils
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(path_utils._local_data_root(), path_utils._install_key(project_root))


def _real_houseki_roots():
    """The Houseki roots a source run uses: path_utils.local_data_root() and get_persistent_user_data_path() with no
    test root (%LOCALAPPDATA%\\Houseki\\Surasura and %APPDATA%\\Houseki\\Surasura), for the bases as they are now."""
    from app import path_utils
    return tuple(os.path.join(base, path_utils.VENDOR, path_utils.DATA_NAME)
                 for base in (path_utils._local_base(), path_utils._roaming_base()))


_TRUE_HOUSEKI_ROOTS = _real_houseki_roots()     # the user's own, before the move
_redirect_user_bases()
_REAL_LOCAL_DATA = _real_local_data_folder()    # the run's own, after it: computed once, here, before any test can
_REAL_HOUSEKI_ROOTS = _real_houseki_roots()     # mock path_utils or point the environment elsewhere


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
    read of the roaming root once made the real %APPDATA%\\Houseki\\Surasura. Since the run's bases moved, these are
    the run's own roots, and the user's true ones beside them (a route past the variables)."""
    watched = tuple(dict.fromkeys(_REAL_HOUSEKI_ROOTS + _TRUE_HOUSEKI_ROOTS))
    before = _folder_state(_REAL_LOCAL_DATA)
    roots = [_root_state(root) for root in watched]
    yield
    assert _folder_state(_REAL_LOCAL_DATA) == before, \
        f"a test wrote the local data folder {_REAL_LOCAL_DATA} (reached without the test root): use the test root"
    for root, was in zip(watched, roots):
        assert _root_state(root) == was, \
            f"a test made or wrote the Houseki root {root} (reached without the test root): use the test root"


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


# pytest's own end of a teardown pops the variable (`_pytest.runner._update_current_test_var(item, None)`) after the
# test's monkeypatch has removed its root, and only then does `pytest_runtest_teardown` below set BETWEEN_TESTS: a
# worker that outlived its test and read a path in those few statements met neither variable and got a per-user path
# (Mado's Needs-you flake, 2026-10-21: tracks/window/work/laptop-fixes/needs/FLAKE.md). So pytest's one function is
# replaced: the same value at set-up, call and teardown, and BETWEEN_TESTS written in the pop's place — one assignment,
# so the variable is never absent. A pytest that renamed the function stops the run here, never silently reopens it.
import _pytest.runner as _pytest_runner     # noqa: E402

if not callable(getattr(_pytest_runner, "_update_current_test_var", None)):
    raise RuntimeError("pytest no longer has _pytest.runner._update_current_test_var: tests/harness_guards.py's "
                       "PYTEST_CURRENT_TEST gap guard needs its new name")


def _update_current_test_var(item, when):
    """pytest's own (`_pytest/runner.py`), with BETWEEN_TESTS where it popped the variable."""
    if when:
        os.environ["PYTEST_CURRENT_TEST"] = f"{item.nodeid} ({when})".replace("\x00", "(null)")
    else:
        os.environ["PYTEST_CURRENT_TEST"] = BETWEEN_TESTS


_pytest_runner._update_current_test_var = _update_current_test_var


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
        command = kwargs.get("args", args[0] if args else None)
        _check_python_child(command, kwargs.get("env"))
        started(self, *args, **kwargs)
        _watch_child(_CHILDREN, self.pid, command)
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
    10 s) is ended and named, and fails the run — counted in the closing line too ("1 leaked child"). A try at the
    AnkiConnect port no test's end claimed (after the last test's) fails the run the same way ("1 anki port")."""
    result = yield
    leaked = _end_leaked_children(_CHILDREN, int(os.environ.get("SURASURA_TEST_CHILD_GRACE_MS", "10000")))
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    session.testsfailed += _report_late_anki_tries(reporter)       # (defined below, with the Anki-port guard)
    if leaked:
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


# --- No test reaches a real Anki ---------------------------------------------------------------------------------- #
# Every suite's AnkiConnect is a stand-in (a patched `urlopen`, Junban's helpers patched, an adapter's methods faked),
# so nothing listens on the AnkiConnect port while the tests run — unless Anki is open on this machine, with the user's
# own profile. A test whose patch closed before its thread's last request, or that faked all but one call, sent that
# request to a real Anki and stayed green (refused, it reads as "Anki is closed"): six such tries, 2026-10-20. So for
# the whole process a connection to the port is refused before it leaves — any host, through socket.connect /
# connect_ex (urllib, http.client, requests, a raw socket) and asyncio's Windows proactor — and remembered with the
# test running then, the thread and the test that started it, and where in the code. At each test's end every try
# not yet claimed fails that test (an error at its teardown naming each); one after the last test fails the run. The
# ports: AnkiConnect's own and the stand-in addresses the suites give it (nothing listens there: a try there is a patch
# that didn't hold). A test that must reach a real Anki (the live drills, DevTest only) carries the mark ANKI_PORT_MARK;
# the port is open only while that test runs, to its own code and the threads it started, never to a thread it leaves
# behind. A child process is its own interpreter, out of the guard's reach: every child starts with
# SURASURA_NO_ANKI_SYNC=1 (set for the run below; the app's Anki callers stay off under it), and a Python child of
# Surasura's code an unmarked test starts without it, whose settings give Anki's own port, is flagged as a try
# (Windows: the child watch's Popen wrapper; a test meeting "Anki closed" points its child at port 9). NO_PROXY=* for
# the run: a loopback proxy would carry a request to the port past the check. Not covered: code calling the C socket
# type's methods directly, and a child (not Python, or not caught by the check above) that reaches Anki anyway.
ANKI_PORT_MARK = "anki_port"
ANKI_PORTS = frozenset({8765,                        # AnkiConnect's (app/anki_connect.DEFAULT_URL)
                        8766, 8770, 18765, 28765})   # the suites' stand-in anki_connect_url / junban_url addresses
_CONNREFUSED = 10061 if sys.platform == "win32" else 111            # what connect_ex answers for a closed port
_ANKI_TRIES = []          # [address, the test running then, thread, the test that started it, where, claimed]
_ANKI_OPEN = [None]       # the node id of the test carrying ANKI_PORT_MARK while it runs, else None
_STARTED_IN = "_surasura_started_in"                                # a thread's attribute: the test that started it
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AnkiPortRefused(ConnectionRefusedError):
    """A test tried the AnkiConnect port (refused by the test harness: a real Anki may be listening there)."""


def _test_now():
    return os.environ.get("PYTEST_CURRENT_TEST") or BETWEEN_TESTS


def _opted_in_now():
    """Whether a marked test is running and this is its own code: the main thread, or a thread it started."""
    node = _ANKI_OPEN[0]
    if node is None or _test_now().rsplit(" (", 1)[0] != node:
        return False
    thread = threading.current_thread()
    started_in = getattr(thread, _STARTED_IN, None)
    return thread is threading.main_thread() or (started_in is not None and started_in.rsplit(" (", 1)[0] == node)


def _anki_port_refuses(family, address):
    """Whether a connection to `address` goes to the AnkiConnect port, from anything but an opted-in test's own code."""
    if family not in (socket.AF_INET, socket.AF_INET6) or not isinstance(address, tuple) or len(address) < 2:
        return False
    return address[1] in ANKI_PORTS and not _opted_in_now()


_SURASURA_CODE = re.compile(r"app_entry|\b(?:app|modules)[./\\]|\b(?:from|import) (?:app|modules)\b")


def _child_reaches_anki(env):
    """Whether a child's settings (its test root's settings.json, else this checkout's) give Anki's own port."""
    from urllib.parse import urlsplit
    path = os.path.join(env.get("SURASURA_TEST_ROOT") or _PROJECT, "settings.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    try:
        from app import anki_connect
        return urlsplit(anki_connect.address(settings if isinstance(settings, dict) else {})).port == 8765
    except Exception:
        return True


def _check_python_child(command, env):
    """A Python child running Surasura's code, started by anything but an opted-in test without SURASURA_NO_ANKI_SYNC,
    whose settings point at Anki's own port: recorded as a try (the guard can't follow it into its process). A child
    of a test that turned the switch off on purpose to meet "Anki closed" reads a closed or stand-in port: not one."""
    parts = list(command) if isinstance(command, (list, tuple)) else [command]
    if not parts or not all(isinstance(x, (str, bytes, os.PathLike)) for x in parts):
        return
    parts = [os.fsdecode(x) for x in parts]
    first = parts[0] if len(parts) > 1 else (parts[0].split() or [""])[0]
    name = os.path.basename(first.strip('"')).lower()
    if not name.startswith("python") and os.path.normcase(first) != os.path.normcase(sys.executable):
        return
    env = env if env is not None else os.environ
    if env.get(NO_ANKI) or _opted_in_now() or not _SURASURA_CODE.search(" ".join(parts)):
        return
    if not _child_reaches_anki(env):
        return
    thread = threading.current_thread()
    _ANKI_TRIES.append([f"a child of Surasura's code with Anki's own port and no {NO_ANKI} (out of the guard's "
                        f"reach): {command!r}", _test_now(), thread.name, getattr(thread, _STARTED_IN, None),
                        _where(), False])


def _where():
    """The project's own frames nearest the try (innermost first): which code sent it."""
    frames = [f for f in traceback.extract_stack()[:-3]
              if f.filename.startswith(_PROJECT)
              and os.path.basename(f.filename) not in ("harness_guards.py", "network_guard.py")]
    return " <- ".join(f"{os.path.relpath(f.filename, _PROJECT)}:{f.lineno} {f.name}" for f in reversed(frames[-4:]))


def _anki_refused(address):
    thread = threading.current_thread()
    _ANKI_TRIES.append([address, _test_now(), thread.name, getattr(thread, _STARTED_IN, None), _where(), False])
    return AnkiPortRefused(f"the test harness refused a connection to the AnkiConnect port {address!r}: a test never "
                           f"reaches a real Anki (tests/harness_guards.py; mark {ANKI_PORT_MARK} if it must)")


def _guard_the_anki_port():
    if getattr(socket.socket.__dict__.get("connect"), "_anki_port_guard", False):
        return
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def connect(sock, address):
        if _anki_port_refuses(sock.family, address):
            raise _anki_refused(address)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        if _anki_port_refuses(sock.family, address):
            _anki_refused(address)
            return _CONNREFUSED
        return real_connect_ex(sock, address)

    connect._anki_port_guard = connect_ex._anki_port_guard = True
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    try:
        from asyncio.windows_events import IocpProactor        # asyncio's Windows loop connects past socket.connect
    except ImportError:
        return
    real_proactor_connect = IocpProactor.connect

    def proactor_connect(self, conn, address):
        if _anki_port_refuses(conn.family, address):
            raise _anki_refused(address)
        return real_proactor_connect(self, conn, address)
    IocpProactor.connect = proactor_connect


def _tag_threads():
    """Every thread remembers the test that started it, for the message when it tries the port after that test."""
    if getattr(threading.Thread.start, "_tagged_by_conftest", False):
        return
    start = threading.Thread.start

    def started(self):
        starter = threading.current_thread()
        inherited = None if starter is threading.main_thread() else getattr(starter, _STARTED_IN, None)
        try:
            setattr(self, _STARTED_IN, inherited or _test_now())
        except AttributeError:
            pass
        return start(self)
    started._tagged_by_conftest = True
    threading.Thread.start = started


NO_ANKI = "SURASURA_NO_ANKI_SYNC"
os.environ.setdefault(NO_ANKI, "1")      # the app's Anki callers stay off, in this process and every child it starts
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"       # no proxy carries a request to the port past the check
_guard_the_anki_port()
_tag_threads()


def _claim_anki_tries():
    """Every try not yet claimed, marked claimed -> one line each."""
    lines = []
    for attempt in list(_ANKI_TRIES):
        if attempt[5]:
            continue
        attempt[5] = True
        address, during, thread, started_in, where = attempt[:5]
        line = f"{address!r} during {during}, thread {thread!r}"
        if started_in and started_in.rsplit(" (", 1)[0] != during.rsplit(" (", 1)[0]:
            line += f" started in {started_in}"
        lines.append(line + (f", from {where}" if where else ""))
    return lines


@pytest.fixture(autouse=True)
def _guard_anki_port():
    """Fail a test during which anything tried the AnkiConnect port (refused: a real Anki may be listening there) —
    its own code, a thread left by an earlier test, or a try in the gap before it — naming each try. And one during
    which anything opened a browser or a viewer (refused), a child of it included."""
    yield
    tries = _claim_anki_tries()
    assert not tries, ("the AnkiConnect port was tried, or a child that could was started unguarded (refused or "
                       "flagged; a real Anki could have answered): " + "; ".join(tries))
    opened = _claim_opens()
    assert not opened, ("a browser or a file viewer was opened (refused: a test never opens one on this desktop; "
                        "pass --no-open, or hand the code its own opener): " + "; ".join(opened))


# --- No test opens a browser or a file viewer (2026-10-21) ---------------------------------------------------------- #
# Tests opened Journey and report pages — one under a test root — in Sonic's own Chrome and left them open. The guard
# (tests/open_guard_site/open_guard.py) refuses webbrowser's opens, os.startfile, QDesktopServices.openUrl and a browser
# or viewer started as a child, here and, through the Popen watch, in every Python child a test starts; each refused
# open is a line in the run's own log, read at each test's end. Only the log is shared: one rule, in one file.
def _load_open_guard():
    import importlib.util
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "open_guard_site")
    spec = importlib.util.spec_from_file_location("open_guard", os.path.join(folder, "open_guard.py"))
    module = sys.modules.get("open_guard")
    if module is None or getattr(module, "HERE", None) != folder:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules["open_guard"] = module
    return module


_OPEN_GUARD = _load_open_guard()
os.environ[_OPEN_GUARD.LOG] = os.path.join(os.path.dirname(os.environ["LOCALAPPDATA"]), "opened.jsonl")
_OPEN_GUARD.install(qt=True)
_OPENS_READ = [0]           # how far the log has been read


def _claim_opens():
    """The log's lines since the last claim -> one line each, naming the test, the route, what and where."""
    try:
        with open(os.environ[_OPEN_GUARD.LOG], "rb") as f:
            f.seek(_OPENS_READ[0])
            data = f.read()
    except OSError:
        return []
    complete = data[:data.rfind(b"\n") + 1]
    _OPENS_READ[0] += len(complete)
    out = []
    for raw in complete.decode("utf-8", "replace").splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            out.append(raw)
            continue
        out.append(f"{line.get('route')} {line.get('target')!r} during {line.get('test')} (pid {line.get('pid')}, "
                   f"thread {line.get('thread')!r}{', at ' + line['where'] if line.get('where') else ''})")
    return out


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """The port open to a test carrying ANKI_PORT_MARK, from its set-up to its teardown (decided on the item itself, so
    a suite whose conftest loads mid-collection — `pytest modules` — reads it too)."""
    _ANKI_OPEN[0] = item.nodeid if item.get_closest_marker(ANKI_PORT_MARK) else None
    try:
        return (yield)
    finally:
        _ANKI_OPEN[0] = None


def pytest_configure(config):
    """Registers the opt-in mark (a historic hook: a conftest that loads late gets it too). tests/conftest.py, which
    has its own, calls configure_guards()."""
    configure_guards(config)


def configure_guards(config):
    config.addinivalue_line("markers", f"{ANKI_PORT_MARK}: the test may reach the AnkiConnect port (a real Anki: the "
                            "live drills only); refused, and the test failed, for every other test")


def _report_late_anki_tries(reporter):
    """The tries no test's end claimed, each named -> how many."""
    late = _claim_anki_tries()
    for line in late:
        line = f"ANKI PORT TRIED after its test had ended (refused): {line}"
        if reporter:
            reporter.write_sep("!", line, red=True)
            reporter.stats.setdefault("anki port", []).append(line)
        else:
            print(line)
    return len(late)


def _say_tries_at_exit():
    """A try after the session's end (a daemon thread at interpreter exit): refused, and said on stderr."""
    for line in _claim_anki_tries():
        sys.stderr.write(f"ANKI PORT TRIED at interpreter exit (refused): {line}\n")


atexit.register(_say_tries_at_exit)


def _report_late_opens(reporter):
    """The opens no test's end claimed (after the last test, or by a child still running then) -> how many."""
    late = _claim_opens()
    for line in late:
        line = f"A BROWSER OR VIEWER OPENED after its test had ended (refused): {line}"
        if reporter:
            reporter.write_sep("!", line, red=True)
            reporter.stats.setdefault("opened", []).append(line)
        else:
            print(line)
    return len(late)


def session_finish_guards(session=None):
    _free_tk_interpreters()     # what a still-running thread holds stays held, deleted at exit on this thread
    _end_leaked_children(_CHILDREN, grace_ms=0)     # an interrupted run's children: ended, nothing waited for
    reporter = session.config.pluginmanager.get_plugin("terminalreporter") if session is not None else None
    late = _report_late_anki_tries(reporter) + _report_late_opens(reporter)
    if late and session is not None and session.exitstatus == 0:
        session.exitstatus = 1  # a try or an open after the test loop (an interrupted run's, or at the session's end)


def pytest_sessionfinish(session, exitstatus):
    session_finish_guards(session)
