"""A frozen pool worker whose parent goes while it starts ends at once (POOL-ORPHAN, 3.0.21).

Surasura.exe is a windowed program: an exception that leaves app_entry reaches PyInstaller's bootloader, which shows
*Unhandled exception in script* and waits on that box. A pool worker (`--multiprocessing-fork`: the indexer's pool, a
Generate's `sentence_table.Cores`) whose parent was stopped while it started — the window's quit stops the indexer —
raised in multiprocessing's `spawn_main` (the parent's pipe can no longer be copied, WinError 5, or read) and stayed
there, the box on the desktop, holding the program folder: the next update found the install in use (3 of 7 built
lib20k update starts; the built program, killed at 8 points of its pool's start, left one such worker every time).

Each case runs app_entry.run() in a fresh process as the frozen program runs it (`sys.frozen`, the fork form of the
command line) and stands in for the bootloader: an exception that escapes run() waits, as the box does. The parent is
stopped before the worker's start reads its pipe (forced: no sleep decides it), and the worker must be gone within 1 s.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE_WITHIN_S = 1.0

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the windowed bootloader's box: Windows only")

# The frozen worker as Surasura.exe runs it, the bootloader's box stood in for: "ready" once imported (the worker's
# start begins), then app_entry.run() with the fork command line; an exception that escapes it waits for ever.
_WORKER = textwrap.dedent("""
    import sys, threading
    sys.frozen = True                                   # multiprocessing.freeze_support acts only in a frozen program
    import app_entry
    from app import path_utils                          # the exit's log line: imported before the clock starts
    sys.argv = ["Surasura.exe", "--multiprocessing-fork"] + sys.argv[1:]
    print("ready", flush=True)
    try:
        app_entry.run()
    except SystemExit:
        raise
    except BaseException as e:
        print("escaped " + type(e).__name__ + ": " + str(e), flush=True)
        threading.Event().wait()                        # the bootloader's box: a press that never comes
""")

# A pool's parent as far as the worker sees it: its process and the reading end of a pipe it never writes.
_PARENT = textwrap.dedent("""
    import _winapi, threading
    rhandle, whandle = _winapi.CreatePipe(None, 0)
    print(rhandle, flush=True)
    threading.Event().wait()
""")


def _env(root):
    return dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root), PYTHONIOENCODING="utf-8")


def _start_worker(root, parent_pid, pipe_handle):
    return subprocess.Popen([sys.executable, "-c", _WORKER, f"parent_pid={parent_pid}", f"pipe_handle={pipe_handle}"],
                            cwd=str(root), env=_env(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")


def _ends_within(worker, seconds):
    """-> (exit code or None while it still runs, what it printed after `ready`). A worker still running is stopped
    here (by its own Popen: this test's process)."""
    try:
        code = worker.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait()
        code = None
    return code, worker.stdout.read()


def _log(root):
    path = os.path.join(str(root), "local", "logs", "app_debug_log.txt")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_a_worker_whose_parent_is_already_gone_ends_instead_of_waiting_on_the_box(tmp_path):
    # The window's quit stopped the indexer before this worker copied its pipe: the indexer's process is ended but
    # still known (a handle to it held, as the window's Popen holds one), so the copy is refused (WinError 5).
    parent = subprocess.Popen([sys.executable, "-c", _PARENT], stdout=subprocess.PIPE, text=True)
    pipe_handle = int(parent.stdout.readline())
    parent.kill()
    parent.wait()                                       # gone before the worker starts: forced, no sleep
    worker = _start_worker(tmp_path, parent.pid, pipe_handle)
    try:
        assert worker.stdout.readline().strip() == "ready"
        code, said = _ends_within(worker, GONE_WITHIN_S)
    finally:
        if worker.poll() is None:
            worker.kill()
    assert "escaped" not in said, said                  # nothing left for the bootloader's box
    assert code == 1, (code, said)
    assert "A pool worker's start failed" in _log(tmp_path)


def test_a_worker_whose_parent_is_stopped_as_it_starts_ends_too(tmp_path):
    # The parent alive when the worker starts, stopped at once after: whether the worker's copy of the pipe is refused
    # or its read finds the pipe broken, its start fails and it ends.
    parent = subprocess.Popen([sys.executable, "-c", _PARENT], stdout=subprocess.PIPE, text=True)
    try:
        pipe_handle = int(parent.stdout.readline())
        worker = _start_worker(tmp_path, parent.pid, pipe_handle)
        assert worker.stdout.readline().strip() == "ready"
    finally:
        parent.kill()
        parent.wait()
    try:
        code, said = _ends_within(worker, GONE_WITHIN_S)
    finally:
        if worker.poll() is None:
            worker.kill()
    assert "escaped" not in said, said
    assert code == 1, (code, said)


def _run_fork_path(root, outcome):
    """app_entry.run() on the fork command line with `main` (the worker's start: freeze_support) ending in `outcome`:
    "exit-0" (a worker that ran and returned), "exit-3", "raise". -> (exit code, what escaped)."""
    script = textwrap.dedent(f"""
        import json, sys
        import app_entry
        def fake_main():
            if {outcome!r} == "raise":
                raise EOFError("the parent's pipe ended")
            sys.exit(int({outcome!r}.split("-")[1]))
        app_entry.main = fake_main
        sys.argv = ["Surasura.exe", "--multiprocessing-fork", "parent_pid=1", "pipe_handle=2"]
        escaped = None
        try:
            app_entry.run()
            code = 0
        except SystemExit as e:
            code = e.code
        except BaseException as e:
            code, escaped = None, type(e).__name__
        print(json.dumps([code, escaped]))
    """)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=_env(root), capture_output=True,
                          text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_worker_that_starts_keeps_its_own_exit_code(tmp_path):
    # A worker's normal end is multiprocessing's own sys.exit(code): passed through as it is, never turned into 1,
    # and nothing logged as a failed start.
    assert _run_fork_path(tmp_path, "exit-0") == [0, None]
    assert _run_fork_path(tmp_path, "exit-3") == [3, None]
    assert "A pool worker's start failed" not in _log(tmp_path)


def test_any_failure_of_the_start_is_logged_and_exits_1(tmp_path):
    # Whatever the start raises (a broken pipe reads as EOFError) leaves as exit 1 with its line in the app's log.
    assert _run_fork_path(tmp_path, "raise") == [1, None]
    assert "A pool worker's start failed (EOFError" in _log(tmp_path)


# A pool's parent as the indexer starts it (its initializer, its initargs): one task run, so the worker's start has
# finished, its pid printed, then it waits.
_INDEXER_PARENT = textwrap.dedent("""
    import multiprocessing, os, threading
    from app import analyzer, token_index
    context = multiprocessing.get_context("spawn")
    pool = context.Pool(1, initializer=token_index._pool_start, initargs=("ja", False, "asis", dict(analyzer.LOGIC)))
    print(pool.apply(os.getpid), flush=True)
    threading.Event().wait()
""")


def ends_with_its_parent(script, root, seconds):
    """Start `script` (a pool's parent that prints its worker's pid), stop it, -> whether the worker ended within
    `seconds` after. A worker still running then is stopped here (its pid is this test's own grandchild)."""
    import _winapi
    parent = subprocess.Popen([sys.executable, "-c", script], cwd=PROJECT_ROOT, env=_env(root),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    try:
        pid = int(parent.stdout.readline())
        worker = _winapi.OpenProcess(_winapi.SYNCHRONIZE | 0x0001, False, pid)      # | PROCESS_TERMINATE
    finally:
        parent.kill()
        parent.wait()
    try:
        ended = _winapi.WaitForSingleObject(worker, int(seconds * 1000)) == _winapi.WAIT_OBJECT_0
        if not ended:
            _winapi.TerminateProcess(worker, 1)
        return ended
    finally:
        _winapi.CloseHandle(worker)


def test_an_indexer_worker_that_has_started_ends_with_its_parent(tmp_path):
    # After its start the worker's own watch ends it (`token_index._pool_start`): the indexer stopped, the pool's pipe
    # still open in the worker, it would otherwise wait on it for ever.
    assert ends_with_its_parent(_INDEXER_PARENT, tmp_path, GONE_WITHIN_S)
