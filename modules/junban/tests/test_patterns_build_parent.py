"""A library build's worker ends with the build (POOL-ORPHAN, 3.0.21).

The パターン build counts in a spawned ProcessPoolExecutor (`patterns_build.build`, `_init_worker`). A build stopped
from outside (Task Manager, a crash) left its workers waiting on the executor's queue, which each worker holds open
itself: each one now watches the build's process from its start, as the indexer's workers do
(`tests/test_pool_worker_start.py`).
"""
import os
import subprocess
import sys
import textwrap
import threading

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GONE_WITHIN_S = 5.0                                     # ends in ~0.3 s here; room for a loaded machine
LINE_WITHIN_S = 60.0

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the worker's handle is waited on: Windows only")


def _ends_with_the_build(script, root):
    """Start `script` (the build's pool, printing its worker's pid), stop it -> whether the worker ended within
    GONE_WITHIN_S after. A worker still running then is stopped here (this test's own grandchild)."""
    import _winapi
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root), PYTHONIOENCODING="utf-8")
    parent = subprocess.Popen([sys.executable, "-c", script], cwd=PROJECT_ROOT, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, text=True)
    got = []
    try:
        reader = threading.Thread(target=lambda: got.append(parent.stdout.readline()), daemon=True)
        reader.start()
        reader.join(LINE_WITHIN_S)                      # a stalled build fails the test instead of hanging it
        assert got and got[0].strip(), f"no worker pid from the build in {LINE_WITHIN_S} s"
        worker = _winapi.OpenProcess(_winapi.SYNCHRONIZE | 0x0001, False, int(got[0]))     # | PROCESS_TERMINATE
    finally:
        parent.kill()
        parent.wait()
    try:
        return _winapi.WaitForSingleObject(worker, int(GONE_WITHIN_S * 1000)) == _winapi.WAIT_OBJECT_0
    finally:
        try:
            _winapi.TerminateProcess(worker, 1)
        except OSError:                                 # ended already
            pass
        _winapi.CloseHandle(worker)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_library_build_worker_ends_with_the_build(tmp_path, language):
    # The pool as `build` makes it (its initializer and its arguments); one call run, so the worker's start is done.
    script = textwrap.dedent(f"""
        import multiprocessing, os, threading
        from concurrent.futures import ProcessPoolExecutor
        from modules.junban import patterns_build
        pool = ProcessPoolExecutor(1, multiprocessing.get_context("spawn"), patterns_build._init_worker,
                                   ({language!r}, False, "library"))
        print(pool.submit(os.getpid).result(), flush=True)
        threading.Event().wait()
    """)
    assert _ends_with_the_build(script, tmp_path)
