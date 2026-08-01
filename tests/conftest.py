
import csv
import os
import shutil
import sys
import threading
import time
import pytest
from unittest.mock import patch

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# Analyzer module state that a test (or analyzer.main()) can reassign, and which therefore has to
# be restored afterwards. Kept as a module constant so the guard test can assert it stays complete.
ANALYZER_MUTABLE_GLOBALS = (
    # rebound by tests that redirect the analyzer at a temp library
    "get_data_path", "get_user_files_path", "get_user_file",
    "RESULTS_DIR", "OUTPUT_CSV", "OUTPUT_STATS", "OUTPUT_PROGRESSIVE",
    # assigned by analyzer.main() from CLI flags
    "SANITIZE_JA", "SKIP_SINGLE_CHARS", "MIN_FREQ", "ONLY_I_PLUS_ONE", "ENSURE_AUDIO_EXAMPLE",
)


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
