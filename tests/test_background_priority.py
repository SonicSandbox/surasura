"""a7: the window's background work runs below normal priority (`power.popen_below_normal`).

Alpha 6's try: Generate ran nearly all session (43 runs in 70 minutes) at the window's own priority, beside a first index,
and the window lagged. Every child the window starts for itself — each Generate, the indexer, New arrivals' worker and
the store's helper — now starts below normal, and what it starts in turn inherits that (the indexer's and a look's
pools, the analyzer's own store helper). *Use every core* is untouched: it says how many cores, never the priority.

What a wrong answer would cost: the window drawing late while a run takes every core at its own priority (the lag Sonic
saw), or a background child that never starts because its priority couldn't be set.
"""
import subprocess
import sys
import threading

import pytest

from app.connect import power
from app.services import chores as C
from app.services import generate as G
from app.services.jobs import JobRegistry
from tests import services_helpers as h

BELOW_NORMAL = 0x4000
NO_WINDOW = 0x08000000


class _Popen:
    """`subprocess.Popen`'s stand-in: records each start's keywords and ends at once."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        proc = type("P", (), {})()
        proc.pid, proc.returncode, proc.stdout = 4242, 0, iter(())
        proc.wait = lambda timeout=None: 0
        proc.poll = lambda: 0
        proc.terminate = lambda: None
        return proc


def test_on_windows_the_child_gets_the_below_normal_class_beside_its_own_flags():
    popen = _Popen()
    power.popen_below_normal(["x"], popen=popen, platform="win32", creationflags=NO_WINDOW, stdin=None)
    assert popen.calls == [(["x"], {"creationflags": NO_WINDOW | BELOW_NORMAL, "stdin": None})]
    power.popen_below_normal(["y"], popen=popen, platform="win32")
    assert popen.calls[1][1] == {"creationflags": BELOW_NORMAL}, "no flags of its own: the class alone"


def test_off_windows_the_child_is_niced_after_it_starts_and_a_refusal_still_starts_it(monkeypatch):
    popen = _Popen()
    asked = []
    monkeypatch.setattr(power.os, "PRIO_PROCESS", 0, raising=False)
    monkeypatch.setattr(power.os, "getpriority", lambda which, pid: 0, raising=False)
    monkeypatch.setattr(power.os, "setpriority", lambda which, pid, value: asked.append((pid, value)), raising=False)
    proc = power.popen_below_normal(["x"], popen=popen, platform="linux", creationflags=0)
    assert asked == [(4242, power.NICE)] and popen.calls[0][1] == {"creationflags": 0}

    def refuse(*_a):
        raise PermissionError("not allowed")
    monkeypatch.setattr(power.os, "setpriority", refuse, raising=False)
    assert power.popen_below_normal(["x"], popen=popen, platform="linux") is not None, "started at normal, never lost"
    assert proc.pid == 4242


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' priority classes")
def test_a_real_child_and_the_child_it_starts_both_run_below_normal():
    # the analyzer's own children (its store helper, the indexer's pool) inherit the class: a grandchild proves it
    said = ("import ctypes; from ctypes import wintypes; k = ctypes.windll.kernel32; "
            "k.GetCurrentProcess.restype = wintypes.HANDLE; k.GetPriorityClass.argtypes = [wintypes.HANDLE]; "
            "print(k.GetPriorityClass(k.GetCurrentProcess()))")
    parent = said + f"; import subprocess, sys; subprocess.run([sys.executable, '-c', {said!r}])"
    proc = power.popen_below_normal([sys.executable, "-c", parent], stdout=subprocess.PIPE, text=True,
                                    creationflags=NO_WINDOW)
    out, _ = proc.communicate(timeout=60)
    assert out.split() == [str(BELOW_NORMAL), str(BELOW_NORMAL)], out


def _recording(monkeypatch):
    """`power.popen_below_normal` recorded, then failing as a child that can't start: each caller's own fallback."""
    seen = []

    def record(args, popen=None, platform=None, **kwargs):
        seen.append(args)
        raise OSError("recorded, not started")
    monkeypatch.setattr(power, "popen_below_normal", record)
    return seen


def test_every_generate_the_window_starts_goes_below_normal(monkeypatch):
    seen = _recording(monkeypatch)
    controller = G.GenerateController(JobRegistry(), settle=0, log_folder=h.root())
    ended = threading.Event()
    controller.on_end(lambda run, outcome: ended.set())
    controller.request("ja", argv=["analyzer.py", "--progress-json"], quiet=True)
    assert ended.wait(10)
    assert len(seen) == 1 and seen[0][-1] == "--progress-json"


def test_the_indexer_goes_below_normal():
    popen = _Popen()
    chores = C.Chores(JobRegistry(), None, "ja", update_staged=lambda: False, popen=popen, needed=lambda *a: True)
    job = type("J", (), {"cancelled": False, "started_process": lambda self, pid: None,
                         "finish": lambda self, *a, **k: None})()
    chores._run_indexer(job, "ja")
    assert len(popen.calls) == 1 and popen.calls[0][0] == C.indexer_command("ja")
    if sys.platform == "win32":
        assert popen.calls[0][1]["creationflags"] == NO_WINDOW | BELOW_NORMAL


def test_new_arrivals_worker_goes_below_normal(monkeypatch):
    seen = _recording(monkeypatch)
    from app.services.arrivals import ArrivalsWorker
    worker = ArrivalsWorker(JobRegistry(), "ja", command=["arrivals-worker", "ja"])
    answered = threading.Event()
    worker.estimate(h.root(), callback=lambda answer: answered.set())
    assert answered.wait(10), "the request is answered (an error) when the worker can't start"
    assert seen == [["arrivals-worker", "ja"]]
    worker.stop()


def test_the_stores_helper_goes_below_normal(monkeypatch, real_store_helper):
    seen = _recording(monkeypatch)
    from app import library_store
    monkeypatch.setattr(library_store, "update_staged", lambda: False)
    with pytest.raises(OSError):
        library_store.spawn_maintain("ja")
    assert len(seen) == 1 and "maintain" in seen[0]
