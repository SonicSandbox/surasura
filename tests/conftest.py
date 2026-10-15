
import csv
import importlib
import json
import os
import shutil
import sys
import threading
import time
import pytest
from unittest.mock import patch

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.quiet_windows import quiet_windows
from tests.tk_on_github import skip_tk_tests
from tests.network_guard import around_a_test

quiet_windows()                             # test windows open on a desktop of their own: never seen, never typed into


def pytest_collection_modifyitems(items):
    skip_tk_tests(items)                    # GitHub's runner only: the Tk window tests run in the local --all


@pytest.fixture(autouse=True)
def network_guard():
    """Every test stays on this machine (the window's spec 07 §7.3; tests/network_guard.py): a connection or a name
    lookup past loopback is refused as the app meets it offline, and the test fails at its end naming the address.
    The fixture's value is the guard: a test that provokes a refusal on purpose reads `attempts`, then `forgive()`s."""
    yield from around_a_test()

@pytest.fixture
def test_resources_dir():
    """Returns the path to the 'tests/Test Resources' directory."""
    return os.path.join(os.path.dirname(__file__), "Test Resources")

@pytest.fixture
def ja_resources_dir(test_resources_dir):
    return os.path.join(test_resources_dir, "ja")

@pytest.fixture
def zh_resources_dir(test_resources_dir):
    return os.path.join(test_resources_dir, "zh")

@pytest.fixture(scope="session", autouse=True)
def mock_messagebox():
    """Globally mock tkinter.messagebox for all tests to prevent blocking dialogs."""
    with patch("tkinter.messagebox.showinfo"), \
         patch("tkinter.messagebox.showwarning"), \
         patch("tkinter.messagebox.showerror"), \
         patch("tkinter.messagebox.askyesno", return_value=True), \
         patch("tkinter.messagebox.askokcancel", return_value=True):
        yield


@pytest.fixture(scope="session", autouse=True)
def no_browser_launch():
    """Never open a real browser during a test run.

    generate_static_html() ends by opening the report — correct in the app, but several tests call it
    just to inspect the generated HTML, so a full run used to spawn a browser tab per test. Same
    rationale as mock_messagebox above: suppress the side effect, not the behaviour under test.
    Tests that assert on OPENING patch static_html_generator.open_report, which is untouched here.
    """
    with patch("webbrowser.open"), \
         patch("app.static_html_generator.open_as_app"):
        yield

@pytest.fixture
def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _no_gui_autoindex(monkeypatch):
    """Stop the dashboard from spawning a real background-indexer subprocess during tests.

    Constructing MasterDashboardApp runs update_ui_for_language(), which calls
    _maybe_launch_indexer(); that guard-checks this env var and no-ops. The indexer's own logic
    is covered directly by test_indexer.py (it calls indexer.main()), not via the GUI auto-launch."""
    monkeypatch.setenv("SURASURA_NO_AUTOINDEX", "1")


@pytest.fixture(autouse=True)
def _no_gui_anki_sync(monkeypatch):
    """Stop the dashboard's background Anki known-words sync from reaching a live Anki (and the
    developer's real collection) during tests. The sync itself is covered by test_anki_sync.py."""
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")


@pytest.fixture(autouse=True)
def _no_gui_update_check(monkeypatch):
    """Stop the dashboard's startup update check from calling the real GitHub API during tests.

    Constructing MasterDashboardApp starts check_updates_thread, which asks api.github.com for the
    latest release. Nothing failed because of it (a daemon thread that gives up silently offline),
    so it went unnoticed: every test that built the window made a live request, spending the
    developer's anonymous GitHub quota (60/hour) that the real app's own check also needs. The
    update logic is covered directly by test_update_checker.py with the HTTP layer patched."""
    monkeypatch.setenv("SURASURA_NO_UPDATE_CHECK", "1")


@pytest.fixture(autouse=True)
def _replan_in_process(monkeypatch):
    """The fast re-plan preview's host in the test's own process (`replan_preview.open_host`), never a helper process:
    the suites' fake AnkiConnect is a patch of this process's `urlopen`, which a helper would never see. The helper
    itself is tested on its own (tests/test_replan_helper.py, against a fake Anki served on a loopback port)."""
    monkeypatch.setenv("SURASURA_REPLAN_IN_PROCESS", "1")


@pytest.fixture(autouse=True)
def _no_ui_timers(monkeypatch):
    """Stop GUI windows from leaving Tk `after` timers behind when a test destroys them.

    ContentImporterApp defers _initial_load by 100 ms and re-arms a 4 s _poll_word_stats. A test
    builds and destroys the window far inside that window, so the callbacks are still pending at
    destroy(): Tk drops the Tcl command with the interpreter, the timer fires anyway, and every
    construction leaves an "invalid command name ..._initial_load" firing into a dead interpreter
    for the rest of the session. Enough of them and the run dies mid-suite.

    A guard inside the callback cannot fix this — the callback is never invoked — so the window
    skips SCHEDULING them under this flag. Tests that want the deferred load call refresh_file_list()
    directly, which is what _initial_load does anyway."""
    monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")


from app import library_store as _library_store_module
_REAL_SPAWN_MAINTAIN = _library_store_module.spawn_maintain


@pytest.fixture(autouse=True)
def _isolate_user_data_root(tmp_path_factory, monkeypatch):
    """Point every test at a throwaway data root.

    With SURASURA_TEST_ROOT unset, get_user_data_path() falls back to the PROJECT ROOT — so building
    a GUI in a test runs against the developer's REAL library: _sync_disk_to_manifest walks every
    content file, refresh_file_list inserts a Treeview row per file, and the real
    master_manifest.json is writable. On a large library that is a full disk walk plus thousands of
    row insertions per test, and it leaves real user data one bug away from being rewritten by a
    test run — which CLAUDE.md §4 forbids outright.

    8 of the 10 GUI test files never set this themselves. Setting it here makes that impossible
    instead of relying on each file remembering, for the same reason _isolate_token_store exists.
    Files that set it in their own setUp still win for the duration of the test; monkeypatch
    restores the original (unset) value afterwards either way.

    NOTE the env var is overloaded: it redirects bundled RESOURCES (get_base_path) as well as user
    data (get_user_data_path). So the sandbox has to carry the resources the app legitimately reads:
    without templates/ every report render fails with "Template file ... not found", and without
    samples/ seed_samples() copies nothing. Both are small (~270 KB total); anything larger should
    be symlinked or faulted in rather than copied per test."""
    root = tmp_path_factory.mktemp("user_root")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for resource in ("templates", "samples"):
        src = os.path.join(project_root, resource)
        if os.path.isdir(src):
            shutil.copytree(src, str(root / resource))
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))


def _real_local_data_folder():
    """This checkout's REAL per-install local data folder (path_utils.get_local_data_path() with no test root),
    computed once, here, before any test can mock path_utils."""
    from app import path_utils
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(path_utils._local_data_root(), path_utils._install_key(project_root))


_REAL_LOCAL_DATA = _real_local_data_folder()


def _real_houseki_roots():
    """The REAL Houseki roots a source run uses — path_utils.local_data_root() and get_persistent_user_data_path() with
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


@pytest.fixture(autouse=True)
def _no_tools_entry_from_the_shell(monkeypatch):
    """surasura.json (app/tools_entry.py) is written by a source checkout only when SURASURA_TOOLS_CLI is set, into
    HOUSEKI_TOOLS_DIR when that is set: a developer's shell carrying either would have every window and CLI test write
    it, possibly into the real shared tools folder. A test that wants them sets them itself; with SURASURA_TEST_ROOT
    the entry lands in <test root>/houseki-tools, and with neither tools_dir() raises under pytest."""
    monkeypatch.delenv("SURASURA_TOOLS_CLI", raising=False)
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)


@pytest.fixture(autouse=True)
def _isolate_token_store(tmp_path_factory, monkeypatch):
    """Point the SQLite token store at a fresh temp dir per test, so analyzer runs never write to
    the real %APPDATA% store (and tests never couple through a shared DB)."""
    d = tmp_path_factory.mktemp("token_store")
    monkeypatch.setattr(
        "app.token_index.store_path_for",
        lambda language: str(d / f"token_store_{language}.db"),
        raising=False,
    )


@pytest.fixture(autouse=True)
def _no_destroyed_default_root():
    """A test that makes its root tkinter's default with `monkeypatch.setattr(tk, "_default_root", root)` right after
    `tk.Tk()` has it put back at teardown as `root` itself (Tk() had just made it the default), destroyed by then —
    nine files do. A later file's Font() or Variable() with no master then fails "application has been destroyed",
    but only when no other Tk was made in between: the core suite in shards met it (test_undo_logic after
    test_ignore_names). Before each test, a destroyed default root is cleared (before, not after: monkeypatch's own
    teardown, which puts it back, can run after any other fixture's)."""
    _clear_destroyed_default_root()


@pytest.fixture(autouse=True, scope="class")
def _no_destroyed_default_root_for_a_class():
    """The same before a test class's own set-up: a class that makes its root in `setUpClass` / `setup_class` (the
    Content Manager's layer-A tests) builds before any test's fixtures run, so a destroyed default root left by the
    file before it (test_connect_switch_gaps, in shards) failed all 23 of its tests "application has been destroyed"."""
    _clear_destroyed_default_root()


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


@pytest.fixture(autouse=True)
def store_helper_spawns(monkeypatch):
    """The library store's helper (`library_store.spawn_maintain`) is a DETACHED process: started by a test's
    Generate, Content Manager or dashboard, it would outlive the test and write into a test root being torn
    down. Each spawn is recorded here instead (the list is this fixture's value); a test that wants the real
    helper asks for `real_store_helper`."""
    from app import library_store
    calls = []
    monkeypatch.setattr(library_store, "spawn_maintain", lambda language, *extra: calls.append((language,) + extra))
    return calls


@pytest.fixture
def real_store_helper(store_helper_spawns, monkeypatch):
    """Undo `store_helper_spawns` for one test: `spawn_maintain` starts the real helper."""
    from app import library_store
    monkeypatch.setattr(library_store, "spawn_maintain", _REAL_SPAWN_MAINTAIN)


@pytest.fixture(scope="session", autouse=True)
def _guards_for_shared_windows():
    """The guards above — no UI timers, indexer, Anki sync or update check, no store helper (nor the store's idle
    trigger after Connect's or the command line's writes, in this process or one a test starts) — held for the whole
    session as well: a window a test class builds once (setUpClass) or a module fixture builds is made before any
    function fixture runs, so it had none of them. The Content Manager of test_content_manager_layer_a.py started
    the real store helper and its own worker thread: the helper built a store mid-test (sooner on a loaded machine),
    and from then on the samples flow's sync went to the worker while the test read NOW at once — it failed one run
    in two beside other test runs."""
    mp = pytest.MonkeyPatch()
    for name in ("SURASURA_NO_UI_TIMERS", "SURASURA_NO_AUTOINDEX", "SURASURA_NO_ANKI_SYNC",
                 "SURASURA_NO_UPDATE_CHECK", "SURASURA_REPLAN_IN_PROCESS", "SURASURA_NO_IDLE_EXPORT"):
        mp.setenv(name, "1")
    from app import library_store
    mp.setattr(library_store, "spawn_maintain", lambda language, *extra: None)
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _forget_names_tables():
    """The library's name tables a process applies (app/names.py) are read from the token store once and kept for a
    while — and every test has a store of its own (above). Forget them around every test, so one test's library never
    names another's words."""
    try:
        from app import names
    except Exception:
        yield
        return
    names.forget_library_tables()
    try:
        yield
    finally:
        names.forget_library_tables()


# Analyzer module state that a test (or analyzer.main()) can reassign, and which therefore has to
# be restored afterwards. Kept as a module constant so the guard test can assert it stays complete.
ANALYZER_MUTABLE_GLOBALS = (
    # rebound by tests that redirect the analyzer at a temp library
    "get_data_path", "get_user_files_path", "get_user_file",
    "RESULTS_DIR", "OUTPUT_CSV", "OUTPUT_STATS", "OUTPUT_PROGRESSIVE",
    # assigned by analyzer.main() from CLI flags
    "SANITIZE_JA", "SKIP_SINGLE_CHARS", "MIN_FREQ", "ONLY_I_PLUS_ONE", "ENSURE_AUDIO_EXAMPLE",
)


@pytest.fixture(scope="session", autouse=True)
def _real_analyzer_imported_first():
    """Import the REAL analyzer, anki_sync and token_index once, before any test class can mock
    `app.path_utils`.

    The dashboard-wiring tests patch `sys.modules['app.path_utils']` with a MagicMock for a whole
    class. If `_isolate_analyzer_module_state` below then imported the analyzer for the FIRST time
    under that mock, the analyzer's module-level `os.makedirs(get_user_file("results"))` ran on a
    MagicMock and created a real "MagicMock/" folder in the repo root. Invisible in a full run (the
    analyzer is already cached), it happened whenever such a file was run on its own. A session
    fixture runs before every class-level setUp, so the analyzer is always cached first.

    The same for the modules the wiring harness imports under that mock. The patch drops them from
    sys.modules when the class ends, but the `app` package keeps each as an attribute, and every
    later `from app import …` gets that one:
      * `app.anki_sync` binds `get_user_files_path` at import. The report's backlog labels then read
        nothing, and a backlog read (`sync_backlog`) wrote "MagicMock/…/anki_backlog.json" into the
        working folder — test_anki_sync_wiring.py, then test_anki_backlog_label.py.
      * `app.token_index`: `_isolate_token_store` patches the attribute, so a leftover one took the
        patch while a fresh import (`from app.token_index import …`) kept the real `store_path_for`.
    """
    for name in ("app.analyzer", "app.anki_sync", "app.token_index"):
        try:
            importlib.import_module(name)
        except Exception:
            pass
    yield


@pytest.fixture(autouse=True)
def _isolate_analyzer_module_state():
    """Keep the analyzer's module-level state from leaking between tests.

    Many analyzer tests reassign module attributes (get_data_path, RESULTS_DIR, OUTPUT_CSV, ...)
    and analyzer.main() mutates config globals (LOGIC via --context-min/max, SANITIZE_JA,
    SKIP_SINGLE_CHARS, MIN_FREQ, ONLY_I_PLUS_ONE, ENSURE_AUDIO_EXAMPLE) without restoring them.
    Snapshot and restore all of that around every test so the suite is order-independent.

    ADD ANY NEW `global` THAT main() ASSIGNS TO THE LIST BELOW. A missing one doesn't fail
    locally — it leaks into every later test in the session, which shows up as unrelated tests
    failing and the run getting slower and heavier the longer it goes.
    `test_analyzer_globals_are_isolated` guards this so the next one can't be forgotten.
    """
    import copy
    try:
        from app import analyzer
    except Exception:
        yield
        return

    attrs = list(ANALYZER_MUTABLE_GLOBALS)
    saved = {a: getattr(analyzer, a) for a in attrs if hasattr(analyzer, a)}
    saved_logic = copy.deepcopy(analyzer.LOGIC) if hasattr(analyzer, "LOGIC") else None
    try:
        yield
    finally:
        for a, v in saved.items():
            setattr(analyzer, a, v)
        if saved_logic is not None:
            analyzer.LOGIC.clear()
            analyzer.LOGIC.update(saved_logic)


# ==============================================================================================
# Diagnostic profiler — per-test cost, opt-in via SURASURA_TEST_PROFILE=<csv path>.
#
# Records duration, resident memory, thread count and OS handle count for EVERY test, and both
# flushes AND fsyncs each row before the next test starts. That matters: when the process dies of
# MemoryError, pytest dies while FORMATTING the failure, so its own output never names the test it
# reached. This file does.
#
# SURASURA_TEST_MEM_CEILING_MB (default 2048) ends the session cleanly once resident memory crosses
# the ceiling, so the diagnostic cannot itself reach the point of exhausting the machine.
#
# Reading the result: a genuine LEAK shows rss_mb climbing monotonically and never recovering,
# roughly independent of which tests run. A few heavy files show spikes that fall back afterwards.
# threads/handles climbing without bound points at GUI or subprocess objects being retained rather
# than at allocation size.
# ==============================================================================================

_PROF = {"file": None, "writer": None, "t0": None, "prev_rss": 0.0, "n": 0, "outcome": {}}

# Each test file's time (setup + call + teardown), written at the end of the session to SURASURA_TEST_TIMES when
# `run_tests.py --all` runs the core suite in shards: it packs the next run's shards by them.
_TIMES = {"path": os.environ.get("SURASURA_TEST_TIMES"), "files": {}}


def pytest_sessionfinish(session, exitstatus):
    _free_tk_interpreters()     # what a still-running thread holds stays held, deleted at exit on this thread
    _end_leaked_children(_CHILDREN, grace_ms=0)     # an interrupted run's children: ended, nothing waited for
    if not _TIMES["path"]:
        return
    try:
        with open(_TIMES["path"], "w", encoding="utf-8") as f:
            json.dump(_TIMES["files"], f)
    except OSError:
        pass


def _init_proc_stats():
    """Bind the psapi/kernel32 calls once. Returns a callable, or None where unavailable.

    argtypes/restype are declared explicitly and NOT optional: with ctypes' defaults
    GetCurrentProcess returns c_int, which truncates the 64-bit pseudo-handle, and
    GetProcessMemoryInfo then fails and reports 0 MB for everything — a silently blind
    instrument, which is worse than none."""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetProcessHandleCount.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        handle = kernel32.GetCurrentProcess()

        def _stats():
            pmc = _PMC()
            pmc.cb = ctypes.sizeof(_PMC)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return (0.0, 0.0, 0)
            count = wintypes.DWORD(0)
            kernel32.GetProcessHandleCount(handle, ctypes.byref(count))
            return (pmc.WorkingSetSize / 1048576.0,
                    pmc.PeakWorkingSetSize / 1048576.0,
                    count.value)

        # Prove it works now rather than emitting a column of zeros for the whole run.
        if _stats()[0] <= 0:
            return None
        return _stats
    except Exception:
        return None


_PROC_STATS = _init_proc_stats()


def _proc_stats():
    """(rss_mb, peak_rss_mb, handle_count); zeros where the platform call isn't available.

    Deliberately NOT psutil — that would be a new dependency (CLAUDE.md §4)."""
    return _PROC_STATS() if _PROC_STATS else (0.0, 0.0, 0)


def pytest_configure(config):
    path = os.environ.get("SURASURA_TEST_PROFILE")
    if not path:
        return
    f = open(path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["n", "nodeid", "outcome", "secs", "rss_mb", "delta_mb", "peak_mb",
                "threads", "handles"])
    f.flush()
    _PROF["file"], _PROF["writer"] = f, w


def pytest_unconfigure(config):
    if _PROF["file"]:
        try:
            _PROF["file"].close()
        finally:
            _PROF["file"] = _PROF["writer"] = None


def pytest_runtest_logstart(nodeid, location):
    _PROF["t0"] = time.perf_counter()


def pytest_runtest_logreport(report):
    if _TIMES["path"]:
        path = report.nodeid.split("::")[0]
        _TIMES["files"][path] = _TIMES["files"].get(path, 0.0) + report.duration
    # Worst outcome across setup/call/teardown wins.
    if report.failed:
        _PROF["outcome"][report.nodeid] = "FAILED"
    elif report.skipped:
        _PROF["outcome"].setdefault(report.nodeid, "skipped")


def pytest_runtest_logfinish(nodeid, location):
    writer = _PROF["writer"]
    if not writer:
        return
    secs = time.perf_counter() - (_PROF["t0"] or time.perf_counter())
    rss, peak, handles = _proc_stats()
    _PROF["n"] += 1
    writer.writerow([
        _PROF["n"], nodeid, _PROF["outcome"].pop(nodeid, "passed"),
        f"{secs:.3f}", f"{rss:.1f}", f"{rss - _PROF['prev_rss']:+.1f}", f"{peak:.1f}",
        threading.active_count(), handles,
    ])
    _PROF["file"].flush()
    try:
        # fsync, not just flush: a hard crash must not lose the row that names where we stopped.
        os.fsync(_PROF["file"].fileno())
    except OSError:
        pass
    _PROF["prev_rss"] = rss

    ceiling = float(os.environ.get("SURASURA_TEST_MEM_CEILING_MB", "2048"))
    if ceiling and rss > ceiling:
        pytest.exit(f"Memory ceiling reached: {rss:.0f} MB > {ceiling:.0f} MB "
                    f"(last test: {nodeid})", returncode=1)
