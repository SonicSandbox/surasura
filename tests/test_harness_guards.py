"""The harness's own guards (tests/harness_guards.py; tests/conftest.py and each module suite's conftest import them)
against the three flakes that forced full re-runs (2026-10-14):

* a worker thread that outlived its test reached a per-user path in the gap pytest leaves between two tests (no
  PYTEST_CURRENT_TEST, no test root) and made the real, empty %APPDATA%\\Houseki\\Surasura — every test running then,
  in every shard, failed the real-root guard;
* a Tk interpreter freed on a worker thread (a collection there, or the thread holding it last) aborted the whole
  process (Windows fatal 0x80000003 / 0xC0000005);
* a test's child process (`slow.py`) kept running for an hour after its pytest had gone.

And the AnkiConnect port (2026-10-20): six green tests had sent a request to it, where an Anki left open
on this machine would have answered.
"""
import gc
import json
import os
import subprocess
import sys
import textwrap
import threading

import pytest

from tests import harness_guards

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = "SURASURA_HARNESS_PROBE"        # set only for the nested run below: its two helper tests run there alone


def _held(interp_id):
    return any(id(t) == interp_id for t in harness_guards._TK_INTERPS)


def _tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as e:                                            # no display
        pytest.skip(f"no Tk: {e}")
    root.withdraw()
    return root


def _running(pid):
    import _winapi
    try:
        handle = _winapi.OpenProcess(0x00100000, False, pid)           # SYNCHRONIZE
    except OSError:
        return False
    try:
        return _winapi.WaitForSingleObject(handle, 5000) != _winapi.WAIT_OBJECT_0
    finally:
        _winapi.CloseHandle(handle)


# --- the gap between two tests, and the end of the run ------------------------------------------------------------ #

def test_the_gap_after_a_tests_teardown_still_names_no_test(monkeypatch):
    # The order inside the teardown wrapper: pytest clears PYTEST_CURRENT_TEST at the end of a test's teardown; the
    # wrapper runs after that and names the gap.
    monkeypatch.setenv("PYTEST_CURRENT_TEST", os.environ.get("PYTEST_CURRENT_TEST", "x (call)"))  # put back after
    wrapper = harness_guards.pytest_runtest_teardown(None, None)
    next(wrapper)
    os.environ.pop("PYTEST_CURRENT_TEST")                       # what pytest's own teardown does last
    with pytest.raises(StopIteration):
        next(wrapper)
    assert os.environ["PYTEST_CURRENT_TEST"] == harness_guards.BETWEEN_TESTS


@pytest.mark.skipif(sys.platform != "win32", reason="the child watch is Windows-only")
def test_a_real_run_names_the_gap_and_fails_on_a_child_left_running(tmp_path):
    # A real pytest run of the two helper tests below, with a plugin that records PYTEST_CURRENT_TEST where a worker
    # outliving its test would meet it: after the first test's teardown (the gap) and at the session's end. The first
    # helper leaves a child running (as slow.py did): the run must end it, name it and fail.
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    record = tmp_path / "record.jsonl"
    (plugins / "gap_recorder.py").write_text(textwrap.dedent(f"""
        import json, os
        def _note(when):
            with open({str(record)!r}, "a", encoding="utf-8") as f:
                f.write(json.dumps({{"when": when, "current": os.environ.get("PYTEST_CURRENT_TEST")}}) + "\\n")
        def pytest_runtest_logfinish(nodeid, location):
            _note("after " + nodeid.rsplit("::", 1)[-1])
        def pytest_sessionfinish(session, exitstatus):
            _note("session end")
    """), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(plugins), PROJECT]), PYTHONIOENCODING="utf-8",
               SURASURA_TEST_CHILD_GRACE_MS="300")
    env[PROBE] = str(record)
    env.pop("PYTEST_CURRENT_TEST", None)                        # the nested run starts as any run does
    env.pop("PYTEST_ADDOPTS", None)                             # why: a `-p <plugin>` there is not on this PYTHONPATH
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "gap_recorder", "-p", "no:cacheprovider", "-q",
         "tests/test_harness_guards.py::test_helper_leaves_a_child_running",
         "tests/test_harness_guards.py::test_helper_runs_second"],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert record.exists(), text                                # the nested run died before its helper ran: say why
    notes = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    child = next(n["child"] for n in notes if "child" in n)
    try:
        assert out.returncode == 1, text
        assert "LEAKED CHILD PROCESS" in text and "test_helper_leaves_a_child_running" in text, text
        # why: two checks, not one string: a warning in the nested run would sit between them ("1 warning, …")
        assert "2 passed" in text and "1 leaked child" in text, text
        gap = [n["current"] for n in notes if n.get("when") in ("after test_helper_leaves_a_child_running",
                                                                 "session end")]
        assert gap == [harness_guards.BETWEEN_TESTS, harness_guards.BETWEEN_TESTS], notes
        assert not _running(child), "the leaked child was ended"
    finally:
        if _running(child):
            subprocess.run(["taskkill", "/F", "/PID", str(child)], capture_output=True)


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_leaves_a_child_running():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ[PROBE], "a", encoding="utf-8") as f:
        f.write(json.dumps({"child": child.pid}) + "\n")


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_runs_second():
    pass


GAP_PROBE = "SURASURA_HARNESS_GAP_PROBE"     # set only for the nested run below: its helpers run there alone
GAP_SEEN = []
GAP_STOP = threading.Event()


def test_pytests_own_end_of_teardown_never_leaves_the_variable_unset(monkeypatch):
    # pytest's last step of a teardown (`_update_current_test_var(item, None)`) popped PYTEST_CURRENT_TEST, and the
    # wrapper above named the gap only after it: a worker reading a path in between met neither variable. Now that
    # step writes BETWEEN_TESTS itself, in one assignment (Mado's Needs-you flake, 2026-10-21).
    import _pytest.runner
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x (teardown)")
    _pytest.runner._update_current_test_var(None, None)
    assert os.environ["PYTEST_CURRENT_TEST"] == harness_guards.BETWEEN_TESTS


def test_a_worker_that_outlives_its_test_never_meets_a_moment_without_a_guard(tmp_path):
    # A real pytest run: its first helper starts a worker that outlives it (as the Needs-you gather did) and watches,
    # through 200 later tests' ends and starts, for a moment with neither the test root nor PYTEST_CURRENT_TEST set —
    # where path_utils would hand out a per-user path. Thread switches every microsecond, so a gap is met if one is
    # there (before the fix: thousands of moments in every run). The last helper fails the run if the worker saw one.
    env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    env[GAP_PROBE] = "1"
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("SURASURA_TEST_ROOT", None)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "tests/test_harness_guards.py",
         "-k", "test_gap_helper"],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 0 and "202 passed" in text, text


def _watch_for_a_gap():
    while not GAP_STOP.is_set():
        if "PYTEST_CURRENT_TEST" not in os.environ and "SURASURA_TEST_ROOT" not in os.environ:
            GAP_SEEN.append(os.environ.get("PYTEST_CURRENT_TEST"))


@pytest.mark.skipif(not os.environ.get(GAP_PROBE), reason="a helper of the nested run above")
def test_gap_helper_0_starts_a_worker_that_outlives_it():
    sys.setswitchinterval(1e-6)
    threading.Thread(target=_watch_for_a_gap, daemon=True, name="outlives its test").start()


@pytest.mark.skipif(not os.environ.get(GAP_PROBE), reason="a helper of the nested run above")
@pytest.mark.parametrize("n", range(200))
def test_gap_helper_1_one_of_many(monkeypatch, n):
    monkeypatch.setenv("SURASURA_TEST_ROOT", os.path.join(PROJECT, "never-made", str(n)))   # gone at its teardown


@pytest.mark.skipif(not os.environ.get(GAP_PROBE), reason="a helper of the nested run above")
def test_gap_helper_2_the_worker_met_no_gap():
    GAP_STOP.set()
    sys.setswitchinterval(0.005)
    assert GAP_SEEN == [], f"{len(GAP_SEEN)} moments with neither PYTEST_CURRENT_TEST nor a test root"


# --- no test opens a browser or a file viewer (2026-10-21) --------------------------------------------------------- #
# Each target below opens nothing even unguarded (a BROWSER that does nothing, paths that don't exist, a browser that
# isn't installed there), so the red run before the guard opened nothing on this desktop either.

def _no_browser_at_all(monkeypatch):
    import webbrowser
    monkeypatch.setenv("BROWSER", f'"{sys.executable.replace(os.sep, "/")}" -c pass %s')
    monkeypatch.setattr(webbrowser, "_tryorder", None, raising=False)       # read BROWSER again at the next open


def _claimed(routes):
    lines = harness_guards._claim_opens()
    return [r for r in routes if not any(line.startswith(r) for line in lines)], lines


def test_every_way_this_process_opens_a_page_or_a_folder_is_refused_and_named(monkeypatch, tmp_path):
    import webbrowser
    _no_browser_at_all(monkeypatch)
    page = (tmp_path / "無い" / "reading_list_static.html").as_uri()
    assert webbrowser.open(page) is True and webbrowser.open_new(page) is True and webbrowser.open_new_tab(page)
    os.startfile(str(tmp_path / "無い"))                                         # Explorer at a folder, or a file
    missing, lines = _claimed(["webbrowser.open ", "webbrowser.open_new ", "webbrowser.open_new_tab ",
                               "os.startfile "])
    assert missing == [], lines
    assert all("test_every_way_this_process_opens" in line for line in lines), lines


def test_qt_s_open_url_is_refused_and_named(tmp_path):
    QtGui = pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtCore import QUrl
    assert QtGui.QDesktopServices.openUrl(QUrl.fromLocalFile(str(tmp_path / "無い.html"))) is True
    missing, lines = _claimed(["QDesktopServices.openUrl "])
    assert missing == [], lines


@pytest.mark.parametrize("command", [
    [r"C:\無い\Google\Chrome\Application\chrome.exe", "--app=file:///C:/無い/reading_list_static.html"],
    r'"C:\無い\Microsoft\Edge\Application\msedge.exe" file:///C:/無い/x.html',
    ["explorer", r"C:\無い"],
    ["cmd", "/c", "exit", "0", "start"],
])
def test_a_browser_or_a_viewer_started_as_a_child_is_refused_and_named(command):
    done = subprocess.run(command, capture_output=True)
    assert done.returncode == 0, "started as a Python that does nothing in its place"
    missing, lines = _claimed(["a browser or viewer started as a child "])
    assert missing == [], lines


def test_a_python_child_opening_a_page_its_way_is_refused_and_named_for_the_test_that_started_it(monkeypatch,
                                                                                                tmp_path):
    # The analyzer as a child opened the report through webbrowser, os.startfile or Chrome in app mode: out of any
    # monkeypatch's reach. The child carries the guard (its PYTHONPATH), even with an environment of its own.
    _no_browser_at_all(monkeypatch)
    code = ("import app, os, subprocess, webbrowser; webbrowser.open('file:///C:/無い/x.html'); "
            "os.startfile(r'C:\\無い\\x.html'); "
            "subprocess.run([r'C:\\無い\\Google\\Chrome\\Application\\chrome.exe', '--app=file:///C:/無い/x.html'])")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=120, cwd=PROJECT)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    missing, lines = _claimed(["webbrowser.open ", "os.startfile ", "a browser or viewer started as a child "])
    assert missing == [], lines
    assert all(f"pid {os.getpid()}" not in line and "test_a_python_child_opening" in line for line in lines), lines


OPEN_PROBE = "SURASURA_HARNESS_OPEN_PROBE"     # set only for the nested run below: its helper runs there alone


def test_a_test_that_opens_a_page_fails_naming_it(tmp_path):
    # A real pytest run of the helper below: its open is refused, and the per-test guard fails it, naming the test.
    env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    env[OPEN_PROBE] = "1"
    env["BROWSER"] = f'"{sys.executable.replace(os.sep, "/")}" -c pass %s'      # nothing opens, guard or none
    for name in ("PYTEST_CURRENT_TEST", "PYTEST_ADDOPTS", "SURASURA_TEST_ROOT"):
        env.pop(name, None)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "tests/test_harness_guards.py::test_open_helper_opens_the_report"],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 1 and "a browser or a file viewer was opened" in text, text
    assert "webbrowser.open " in text and "test_open_helper_opens_the_report" in text, text


@pytest.mark.skipif(not os.environ.get(OPEN_PROBE), reason="a helper of the nested run above")
def test_open_helper_opens_the_report(tmp_path):
    import webbrowser
    webbrowser.open((tmp_path / "reading_list_static.html").as_uri())


# --- a test's own monkeypatch.undo() keeps the test root (2026-10-21) ---------------------------------------------- #
# `monkeypatch.undo()` in a test undid the conftest's SURASURA_TEST_ROOT too: the rest of the test resolved its paths
# with no root (the project's own data folder; a per-user one by a route past path_utils' refusal) — the likely maker,
# with the teardown gap, of the empty real %APPDATA%\Houseki\Surasura in Kura's runs.

def test_an_undo_in_the_test_keeps_its_test_root_and_names_the_test(monkeypatch):
    from app import path_utils
    root = os.environ["SURASURA_TEST_ROOT"]
    monkeypatch.setenv("SURASURA_HARNESS_UNDO_PROBE", "patched")
    monkeypatch.undo()
    assert "SURASURA_HARNESS_UNDO_PROBE" not in os.environ          # the test's own patch is undone, as it asked
    assert os.environ.get("SURASURA_TEST_ROOT") == root             # the sandbox's root is not
    assert path_utils.get_user_data_path() == root
    assert path_utils.get_persistent_user_data_path().startswith(root)
    undone = harness_guards._claim_undone()                        # claimed here, so this test itself passes
    assert len(undone) == 1 and "test_an_undo_in_the_test_keeps_its_test_root_and_names_the_test" in undone[0]


def test_a_scoped_patch_and_a_monkeypatch_of_its_own_are_never_flagged(monkeypatch):
    root = os.environ["SURASURA_TEST_ROOT"]
    with monkeypatch.context() as patched:
        patched.setenv("SURASURA_HARNESS_UNDO_PROBE", "patched")
    own = pytest.MonkeyPatch()
    own.setenv("SURASURA_HARNESS_UNDO_PROBE", "patched")
    own.undo()
    assert os.environ.get("SURASURA_TEST_ROOT") == root and harness_guards._claim_undone() == []


UNDO_PROBE = "SURASURA_HARNESS_UNDO_RUN"       # set only for the nested run below: its helper runs there alone


def test_a_test_that_undoes_its_monkeypatch_fails_naming_it():
    # A real pytest run of the helper below: its paths stay under its root, and the per-test guard fails it by name.
    env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    env[UNDO_PROBE] = "1"
    for name in ("PYTEST_CURRENT_TEST", "PYTEST_ADDOPTS", "SURASURA_TEST_ROOT"):
        env.pop(name, None)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "tests/test_harness_guards.py::test_undo_helper_undoes_and_reads_a_path"],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 1 and "1 passed, 1 error" in text, text           # the call passed; the guard failed it
    assert "monkeypatch.undo()" in text and "test_undo_helper_undoes_and_reads_a_path" in text, text


@pytest.mark.skipif(not os.environ.get(UNDO_PROBE), reason="a helper of the nested run above")
def test_undo_helper_undoes_and_reads_a_path(monkeypatch):
    from app import path_utils
    root = os.environ["SURASURA_TEST_ROOT"]
    monkeypatch.undo()
    assert path_utils.get_persistent_user_data_path().startswith(root)


# --- no pytest run reaches the real Houseki roots ------------------------------------------------------------------ #

def test_a_plain_run_never_reaches_the_real_houseki_roots_even_outside_its_tests(tmp_path):
    # A plain `python -m pytest <file>` (no wrapper, no SURASURA_TEST_ROOT) whose code reaches the per-user roots where
    # no test's guard looks — here at the process's exit, by a route without path_utils' refusal (as a window's worker
    # outliving the run once made the real, empty %LOCALAPPDATA%\Houseki\Surasura\<key>, seen only by other runs'
    # guards). The harness points the per-user bases at a folder of the run's own, so the real roots (stood in for
    # here by `real`) stay untouched, and that folder is gone when the process ends.
    import site
    real, temp = tmp_path / "real", tmp_path / "temp"
    (real / "Local").mkdir(parents=True)
    (real / "Roaming").mkdir()
    temp.mkdir()
    record = tmp_path / "record.json"
    env = dict(os.environ, LOCALAPPDATA=str(real / "Local"), APPDATA=str(real / "Roaming"),
               XDG_DATA_HOME=str(real / "Local"), TEMP=str(temp), TMP=str(temp), PYTHONIOENCODING="utf-8",
               PYTHONUSERBASE=os.environ.get("PYTHONUSERBASE") or site.getuserbase())  # this user's packages
    env[PROBE] = str(record)
    for name in ("PYTEST_CURRENT_TEST", "PYTEST_ADDOPTS", "SURASURA_TEST_ROOT"):
        env.pop(name, None)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "tests/test_harness_guards.py::test_helper_reaches_the_roots_at_exit"],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 0 and "1 passed" in text, text
    reached = json.loads(record.read_text(encoding="utf-8"))
    assert reached["local"] and reached["roaming"], reached         # the helper's exit hook did run
    assert not (real / "Local" / "Houseki").exists() and not (real / "Roaming" / "Houseki").exists(), reached
    assert not os.path.exists(reached["local"]) and not os.path.exists(reached["roaming"]), reached
    assert not [n for n in os.listdir(temp) if n.startswith(harness_guards.ROOTS_PREFIX)], os.listdir(temp)


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_reaches_the_roots_at_exit():
    import atexit
    from app import path_utils

    def reach():
        roots = {"local": path_utils._local_data_root(),
                 "roaming": os.path.join(path_utils._roaming_base(), path_utils.VENDOR, path_utils.DATA_NAME)}
        for root in roots.values():
            os.makedirs(os.path.join(root, "made-at-exit"), exist_ok=True)
        with open(os.environ[PROBE], "w", encoding="utf-8") as f:
            json.dump(roots, f)
    atexit.register(reach)


# --- a probe run by hand on the shared test data never reaches the real profile ------------------------------------ #

_SEED_PROBE = """
import sys
sys.path.insert(0, sys.argv[1])
from tests.fixtures import window_seed
from app.services import view_rows
seed = window_seed.build(root=sys.argv[2])
opener = seed.opener
opener.check()
feed = opener.handle().read_feed()
items = {r["id"]: r for r in feed["items"]}
works = {w["id"]: w for w in feed["works"]}
view = view_rows.build(items, works, {}, numbers=(1, dict(seed.numbers.table)), cache=view_rows.RowCache())
print("rows", len(view.rows))
"""


def test_a_probe_built_on_the_window_seed_by_hand_never_reaches_the_real_profile(tmp_path):
    # 2026-10-31 15:43: a review agent's plain `python probe.py` (no pytest, no harness, no test root) built the window
    # seed and its rows; a row asks whether Connect's setup record exists (view_rows -> anki_miner.mines_now ->
    # ledger.folder -> get_local_data_path), which made the real, empty %LOCALAPPDATA%\\Houseki\\Surasura\\<install key>
    # — and failed the lanes' runs then live. The shared test data moves the bases itself when they name the real
    # profile (stood in for by `home`), and its folder is gone when the probe ends.
    import site
    home, temp, lib = tmp_path / "home", tmp_path / "temp", tmp_path / "lib"
    for d in (home / "AppData" / "Local", home / "AppData" / "Roaming", temp, lib):
        d.mkdir(parents=True)
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), LOCALAPPDATA=str(home / "AppData" / "Local"),
               APPDATA=str(home / "AppData" / "Roaming"), XDG_DATA_HOME=str(home / ".local" / "share"),
               TEMP=str(temp), TMP=str(temp), PYTHONIOENCODING="utf-8",
               PYTHONUSERBASE=os.environ.get("PYTHONUSERBASE") or site.getuserbase())     # this user's packages
    for name in ("PYTEST_CURRENT_TEST", "PYTEST_ADDOPTS", "SURASURA_TEST_ROOT"):
        env.pop(name, None)
    out = subprocess.run([sys.executable, "-c", _SEED_PROBE, PROJECT, str(lib)], cwd=str(tmp_path), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 0 and "rows " in text, text
    made = [os.path.join(d, n) for d, ds, fs in os.walk(home) for n in ds + fs if "Houseki" in os.path.join(d, n)]
    assert made == [], made
    assert not [n for n in os.listdir(temp) if n.startswith(harness_guards.ROOTS_PREFIX)], os.listdir(temp)


def test_the_shared_test_data_moves_only_bases_that_name_the_real_profile(tmp_path, monkeypatch):
    # A bench's child (tests/qt/bench_moments.py) and an env.sh name bases of their own: kept. Unset or the user's own
    # folders: moved. (Asked, never moved here: this process's bases are the harness's.)
    from tests import user_bases
    home = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "bench" / "localappdata"))
        assert user_bases.names_the_real_profile()                     # one of the two is the user's own
        monkeypatch.setenv("APPDATA", str(tmp_path / "bench" / "appdata"))
        assert not user_bases.names_the_real_profile()
        monkeypatch.delenv("LOCALAPPDATA")
        assert user_bases.names_the_real_profile()                     # unset: path_utils falls back to the profile
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
        assert user_bases.names_the_real_profile()
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "bench" / "share"))
        assert not user_bases.names_the_real_profile()


def test_the_root_guard_excuses_only_an_empty_folder_removed(tmp_path):
    # 2026-10-31: the lead removing two empty leaked folders by hand failed every run then live. An empty folder gone
    # is no loss; a populated one gone, or the root with one, still fails — as does anything made.
    root = tmp_path / "Houseki" / "Surasura"
    (root / "33b0ab4f8a769fe8").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "store").mkdir()
    (root / "store" / "library.db").write_bytes(b"x")
    before = harness_guards._root_state(str(root))
    assert before[2] == ["33b0ab4f8a769fe8", "bin"]
    (root / "33b0ab4f8a769fe8").rmdir()
    (root / "bin").rmdir()
    assert harness_guards._changed(before, harness_guards._root_state(str(root))) == ([], [])
    (root / "store" / "library.db").unlink()
    (root / "store").rmdir()
    assert harness_guards._changed(before, harness_guards._root_state(str(root))) == ([], ["store"])
    root.rmdir()
    assert harness_guards._changed(before, harness_guards._root_state(str(root))) == ([], ["store"])
    assert harness_guards._changed((True, ["a"], []), (True, ["a", "bin"], ["bin"])) == (["bin"], [])
    assert harness_guards._changed((False, [], []), (True, [], [])) == (["(the root itself)"], [])


def test_the_root_guard_names_another_copys_install_folder_only_in_the_true_local_root():
    true_local = harness_guards._TRUE_HOUSEKI_ROOTS[0]
    own = os.path.basename(harness_guards._REAL_LOCAL_DATA)
    other = "0" * 16 if own != "0" * 16 else "1" * 16
    if true_local not in harness_guards._REAL_HOUSEKI_ROOTS:
        assert "another copy" in harness_guards._whose(true_local, [other])
    assert harness_guards._whose(true_local, [own]) == "" and harness_guards._whose(true_local, ["bin"]) == ""
    assert harness_guards._whose(harness_guards._REAL_HOUSEKI_ROOTS[0], [other]) == ""   # the run's own: its doing


# --- Tk interpreters are freed on the main thread ----------------------------------------------------------------- #

def test_an_interpreter_dropped_last_by_a_worker_thread_is_deleted_on_the_main_thread():
    root = _tk_root()
    interp = id(root.tk)
    # Checked before the worker drops it: were the interpreter not held, it would be deleted on the worker and Tcl
    # would abort this whole run — the very crash this guards.
    assert _held(interp), "conftest holds the interpreter of every Tk root the main thread makes"
    root.destroy()
    box = [root]
    del root
    t = threading.Thread(target=box.clear)                              # the worker drops the last outside reference
    t.start()
    t.join(30)
    assert _held(interp), "the interpreter outlived the worker's drop: still held for the main thread"
    harness_guards._free_tk_interpreters()
    assert not _held(interp), "deleted by the main thread once nothing else held it"


def test_a_root_in_a_cycle_collected_on_a_worker_leaves_its_interpreter_to_the_main_thread():
    # The dashboard's case, the dump's: the window object and its root in a reference cycle, collected later by a
    # worker thread's collection. The cycle goes there; the interpreter waits for the main thread.
    root = _tk_root()
    interp = id(root.tk)

    class Window:
        pass
    window = Window()
    window.root, window.again, root.window = root, window, window      # a cycle through the root itself, too
    root.destroy()
    was = gc.isenabled()
    gc.disable()                                                        # no automatic collection in between
    try:
        del root, window
        harness_guards._free_tk_interpreters()
        assert _held(interp), "the cycle still holds it"
        t = threading.Thread(target=gc.collect)
        t.start()
        t.join(60)
    finally:
        if was:
            gc.enable()
    assert _held(interp), "collected on the worker, the interpreter still held"
    harness_guards._free_tk_interpreters()
    assert not _held(interp)


def test_a_destroyed_root_still_held_keeps_its_interpreter_until_let_go():
    root = _tk_root()
    interp = id(root.tk)
    root.destroy()
    harness_guards._free_tk_interpreters()
    assert _held(interp), "a test still holds the root: its interpreter stays"
    del root
    harness_guards._free_tk_interpreters()
    assert not _held(interp)


# --- a test's child process never outlives the run --------------------------------------------------------------- #

@pytest.mark.skipif(sys.platform != "win32", reason="the child watch is Windows-only")
def test_a_child_still_running_at_the_end_is_ended_and_named():
    slow = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])   # stands in for slow.py
    try:
        assert any(c[0] == slow.pid for c in harness_guards._CHILDREN), "every Popen of this process is watched"
        children = []
        harness_guards._watch_child(children, slow.pid, "slow.py")
        leaked = harness_guards._end_leaked_children(children, grace_ms=200)
        assert [(pid, command) for pid, command, _test in leaked] == [(slow.pid, "slow.py")]
        assert "test_a_child_still_running_at_the_end_is_ended_and_named" in leaked[0][2]
        assert slow.wait(30) is not None and children == []
    finally:
        if slow.poll() is None:
            slow.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="the child watch is Windows-only")
def test_a_child_that_ended_is_forgotten():
    quick = subprocess.Popen([sys.executable, "-c", "print('done')"], stdout=subprocess.DEVNULL)
    quick.wait(60)
    children = []
    harness_guards._watch_child(children, quick.pid, "quick.py")
    assert harness_guards._end_leaked_children(children, grace_ms=2000) == []
    harness_guards._forget_ended_children(harness_guards._CHILDREN)
    assert not any(c[0] == quick.pid for c in harness_guards._CHILDREN)

# --- no test reaches a real Anki -------------------------------------------------------------------------------- #
# Every try below is refused by the harness before a socket leaves (the first assert proves the guard is on): nothing
# here reaches an Anki left open on this machine. Each test claims its own tries (`_claim_anki_tries`), which is what
# keeps the guard's fixture from failing it.

def _on(port, tries):
    return [line for line in tries if f", {port})" in line or f", {port}," in line]


def test_every_route_to_the_anki_port_is_refused_and_named():
    # Why: the six leaks went through app.anki_connect (urllib); requests, a raw socket and connect_ex are the other
    # doors a test's code could use. A wrong answer: a real Anki answering a test.
    import socket
    import urllib.error
    import urllib.request
    import requests
    from app import anki_connect
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:   # first, and sending nothing: the guard is on
        with pytest.raises(harness_guards.AnkiPortRefused):
            s.connect(("127.0.0.1", 8765))
        assert s.connect_ex(("127.0.0.1", 8765)) != 0
    with pytest.raises(anki_connect.AnkiError) as offline:
        anki_connect.invoke("version", "http://127.0.0.1:8765")
    assert offline.value.kind == "offline"                          # the app meets it as Anki closed
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen("http://localhost:8765", timeout=5)
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get("http://127.0.0.1:8765", timeout=5)
    if socket.has_ipv6:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            with pytest.raises(harness_guards.AnkiPortRefused):
                s.connect(("::1", 8765, 0, 0))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:   # a suite's stand-in address: a patch that slipped
        with pytest.raises(harness_guards.AnkiPortRefused):
            s.connect(("127.0.0.1", 18765))

    async def through_asyncio():                                    # Windows' loop connects through its proactor
        await asyncio.open_connection("127.0.0.1", 8765)
    import asyncio
    with pytest.raises(OSError):
        asyncio.run(through_asyncio())
    claimed = harness_guards._claim_anki_tries()
    tries = _on(8765, claimed)
    assert len(tries) >= 6, tries                                   # (urllib may try both localhost addresses)
    assert all("test_every_route_to_the_anki_port_is_refused_and_named" in t for t in tries), tries
    assert any("app" + os.sep + "anki_connect.py" in t for t in tries), "a try names the code that sent it"
    assert len(_on(18765, claimed)) == 1, claimed
    assert os.environ.get("NO_PROXY") == "*", "a loopback proxy would carry a request to the port past the check"


@pytest.mark.skipif(sys.platform != "win32", reason="the child watch is Windows-only")
def test_a_child_of_surasuras_code_that_would_reach_anki_unguarded_is_flagged(monkeypatch, tmp_path):
    # Why: a child is its own interpreter, out of the guard's reach; SURASURA_NO_ANKI_SYNC (set for the run) keeps its
    # Anki callers off, and a test that turns it off points the child at a closed port. A wrong answer: a child of
    # Surasura's code reaching a real Anki unseen — or every child of an "Anki closed" test flagged for nothing.
    assert os.environ.get("SURASURA_NO_ANKI_SYNC") == "1", "the run sets it for itself and every child"
    surasura = [sys.executable, "-c", "pass  # from app import cli"]             # stands in for a CLI child
    default_root, closed_root = tmp_path / "default", tmp_path / "closed"
    default_root.mkdir()
    closed_root.mkdir()
    (closed_root / "settings.json").write_text('{"anki_connect_url": "http://127.0.0.1:9"}', encoding="utf-8")
    subprocess.run(surasura, env=dict(os.environ, SURASURA_TEST_ROOT=str(default_root)), check=True)   # switch on
    assert harness_guards._claim_anki_tries() == []
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC")
    subprocess.run(surasura, env=dict(os.environ, SURASURA_TEST_ROOT=str(closed_root)), check=True)    # port 9
    subprocess.run([sys.executable, "-c", "pass"], env=dict(os.environ, SURASURA_TEST_ROOT=str(default_root)),
                   check=True)                                                    # not Surasura's code
    subprocess.run(["cmd", "/c", "exit 0"], check=True)                           # not Python
    assert harness_guards._claim_anki_tries() == []
    subprocess.run(surasura, env=dict(os.environ, SURASURA_TEST_ROOT=str(default_root)), check=True)   # 8765
    flagged = harness_guards._claim_anki_tries()
    assert len(flagged) == 1 and "Anki's own port and no SURASURA_NO_ANKI_SYNC" in flagged[0], flagged


def test_other_loopback_ports_stay_open():
    # Why: the suites' own servers (port 0) and "Anki is closed" (port 9) are loopback connections the guard leaves
    # alone. A wrong answer: refusals no leak caused.
    import socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        with socket.create_connection(server.getsockname(), timeout=5):
            pass
    finally:
        server.close()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect_ex(("127.0.0.1", 9))
    assert harness_guards._claim_anki_tries() == []


@pytest.mark.anki_port
def test_a_marked_test_may_reach_the_port():
    # Why: the live drills (DevTest only) must reach Anki. Proven on a stand-in port of the guarded set where this test
    # listens itself, never on Anki's own: a wrong answer would refuse the drills.
    import socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", 28765))
    except OSError:
        server.close()
        pytest.skip("port 28765 is taken on this machine")
    server.listen(1)
    try:
        with socket.create_connection(("127.0.0.1", 28765), timeout=5):
            pass
    finally:
        server.close()
    assert harness_guards._claim_anki_tries() == []


@pytest.mark.skipif(sys.platform != "win32", reason="the late case waits on the child watch (Windows-only)")
def test_a_real_run_fails_the_test_a_left_thread_tries_the_port_in_and_the_run_for_one_after_the_last(tmp_path):
    # A real pytest run of the three helpers below: the first leaves a thread that tries the port during the second
    # (as the re-plan host's loop did after its patch closed); the third leaves one that tries after the last test,
    # while the run waits on its child. The second test fails naming the first; the run fails for the late try.
    env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8", SURASURA_TEST_CHILD_GRACE_MS="90000")
    env[PROBE] = str(tmp_path / "probe")
    env.pop("PYTEST_CURRENT_TEST", None)                        # the nested run starts as any run does
    env.pop("PYTEST_ADDOPTS", None)                             # why: a `-p <plugin>` there is not on this PYTHONPATH
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "tests/test_harness_guards.py::test_helper_leaves_a_thread_that_tries_the_port",
         "tests/test_harness_guards.py::test_helper_is_running_when_the_thread_tries",
         "tests/test_harness_guards.py::test_helper_leaves_a_thread_that_tries_after_the_last_test"],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 1, text
    assert "ERROR at teardown of test_helper_is_running_when_the_thread_tries" in text, text
    assert "started in tests/test_harness_guards.py::test_helper_leaves_a_thread_that_tries_the_port" in text, text
    assert "ANKI PORT TRIED after its test had ended" in text, text
    # why: separate checks: a warning in the nested run would sit between them ("1 warning, …")
    assert "3 passed" in text and "1 error" in text and "1 anki port" in text, text


def _wait_for(condition, seconds=20):
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def _left_thread_tries_the_port_once(ready, then=None):
    import socket

    def run():
        ready()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect(("127.0.0.1", 8765))
            except OSError:
                pass
        if then:
            open(then, "w").close()
    threading.Thread(target=run, name="left-behind", daemon=True).start()


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_leaves_a_thread_that_tries_the_port():
    second = os.environ[PROBE] + ".second"
    _left_thread_tries_the_port_once(lambda: _wait_for(lambda: os.path.exists(second)))


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_is_running_when_the_thread_tries():
    open(os.environ[PROBE] + ".second", "w").close()
    assert _wait_for(lambda: any(not attempt[5] for attempt in harness_guards._ANKI_TRIES))


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_leaves_a_thread_that_tries_after_the_last_test():
    tried = os.environ[PROBE] + ".tried"
    # The run waits on this child after the tests, and the child waits until the thread has tried (at most 60 s).
    wait = f"import os, time; [time.sleep(0.05) for _ in range(1200) if not os.path.exists({tried!r})]"
    subprocess.Popen([sys.executable, "-c", wait])
    _left_thread_tries_the_port_once(lambda: _wait_for(
        lambda: os.environ.get("PYTEST_CURRENT_TEST") == harness_guards.BETWEEN_TESTS), then=tried)

# --- every module suite takes the guards ------------------------------------------------------------------------- #

def _names_bound(node):
    """The names a module-level statement binds: its own (a def, a class, an import, an assignment's, a del's, a for's,
    a with's or an except's target), and those of the statements in its bodies (if, try, with, for, while), never
    inside a def or a class."""
    import ast
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(alias.asname or alias.name).split(".")[0] for alias in node.names}
    targets = list(getattr(node, "targets", None) or [])                    # Assign, Delete
    targets += [t for t in (getattr(node, "target", None),) if t is not None]  # AnnAssign, AugAssign, For
    targets += [item.optional_vars for item in getattr(node, "items", []) if item.optional_vars is not None]  # With
    names = {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, ast.ExceptHandler) and node.name:
        names.add(node.name)
    for field in ("body", "orelse", "finalbody", "handlers"):
        for child in getattr(node, field, None) or []:
            names |= _names_bound(child)
    return names


def test_every_module_suite_on_disk_takes_the_harness_guards():
    # A module suite is a pytest process of its own (`run_tests.py --all`, or `python -m pytest modules/<name>/tests`)
    # and never loads tests/conftest.py: its own conftest imports the guards, or its threads and children go unguarded
    # (an empty real %LOCALAPPDATA%\Houseki\Surasura\<key> made by a module suite failed whole --all runs).
    import ast
    import glob
    suites = sorted(glob.glob(os.path.join(PROJECT, "modules", "*", "tests")))
    if not suites:
        pytest.skip("no module suites in this checkout (the private parts are absent)")
    wanted = set(harness_guards.EVERY_SUITE) | {"pytest_sessionfinish", "pytest_configure"}
    for suite in suites:
        path = os.path.join(suite, "conftest.py")
        assert os.path.isfile(path), f"{suite} has no conftest.py: it runs without the harness guards"
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        # Only the file's top level counts (an import under `if` or in a function may never run), and a name the
        # conftest binds again after importing it (its own `def pytest_runtest_teardown`, say) replaces the guard.
        taken = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "tests.harness_guards":
                as_is = {alias.name for alias in node.names if alias.asname in (None, alias.name)}
                bound = {alias.asname for alias in node.names if alias.asname not in (None, alias.name)}
            else:
                as_is, bound = set(), _names_bound(node)
            rebound = bound & wanted & taken
            assert not rebound, f"{path} binds {sorted(rebound)} again after importing it from tests.harness_guards"
            taken |= as_is
        assert wanted <= taken, f"{path} does not import {sorted(wanted - taken)} from tests.harness_guards"
