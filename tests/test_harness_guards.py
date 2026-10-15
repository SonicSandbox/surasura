"""The harness's own guards (tests/harness_guards.py; tests/conftest.py and each module suite's conftest import them)
against the three flakes that forced full re-runs (2026-10-14):

* a worker thread that outlived its test reached a per-user path in the gap pytest leaves between two tests (no
  PYTEST_CURRENT_TEST, no test root) and made the real, empty %APPDATA%\\Houseki\\Surasura — every test running then,
  in every shard, failed the real-root guard;
* a Tk interpreter freed on a worker thread (a collection there, or the thread holding it last) aborted the whole
  process (Windows fatal 0x80000003 / 0xC0000005);
* a test's child process (`slow.py`) kept running for an hour after its pytest had gone.
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

# --- every module suite takes the guards ------------------------------------------------------------------------- #

def test_every_module_suite_on_disk_takes_the_harness_guards():
    # A module suite is a pytest process of its own (`run_tests.py --all`, or `python -m pytest modules/<name>/tests`)
    # and never loads tests/conftest.py: its own conftest imports the guards, or its threads and children go unguarded
    # (an empty real %LOCALAPPDATA%\Houseki\Surasura\<key> made by a module suite failed whole --all runs).
    import ast
    import glob
    suites = sorted(glob.glob(os.path.join(PROJECT, "modules", "*", "tests")))
    if not suites:
        pytest.skip("no module suites in this checkout (the private parts are absent)")
    wanted = set(harness_guards.EVERY_SUITE) | {"pytest_sessionfinish"}
    for suite in suites:
        path = os.path.join(suite, "conftest.py")
        assert os.path.isfile(path), f"{suite} has no conftest.py: it runs without the harness guards"
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        taken = {alias.asname or alias.name for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module == "tests.harness_guards" for alias in node.names}
        assert wanted <= taken, f"{path} does not import {sorted(wanted - taken)} from tests.harness_guards"
