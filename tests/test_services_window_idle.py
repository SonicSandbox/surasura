"""The window's idle for the window process's background threads (`app/services/window_idle.py`, Up next 2).

What a wrong answer would cost a learner: a worker that never waits takes turns at Python's lock with the window's
thread while it paints a press (Alt+↑ at 20,000 files: 7 ms of the window's work stretched to 26 ms); one that waits for
good — a window that never rests — stops the library's views and the saves for ever.
"""
import threading
import time

import pytest

from app.services import window_idle


def test_without_a_window_nothing_waits():
    t0 = time.perf_counter()
    assert window_idle.idle() and window_idle.wait() is True
    assert time.perf_counter() - t0 < 0.01


def test_a_step_waits_while_the_window_is_busy_and_starts_as_it_rests():
    started = []
    window_idle.busy()
    try:
        worker = threading.Thread(target=lambda: started.append(window_idle.wait(5)))
        worker.start()
        time.sleep(0.05)
        assert started == []                                   # (the window is awake: the step holds)
        window_idle.rest()
        worker.join(5)
        assert started == [True]
    finally:
        window_idle.rest()


def test_a_window_that_never_rests_holds_a_step_back_cap_s_at_most(monkeypatch):
    monkeypatch.setattr(window_idle, "CAP_S", 0.05)
    window_idle.busy()
    try:
        t0 = time.perf_counter()
        assert window_idle.wait() is False
        assert 0.04 <= time.perf_counter() - t0 < 1.0
    finally:
        window_idle.rest()


MINE = "window-idle-test"     # the name of each thread this file starts for a piece (`_SeenIdle` counts only these)


def _in_a_worker(fn):
    out = []
    t = threading.Thread(target=lambda: out.append(fn()), name=MINE)
    t.start()
    t.join(5)
    return out[0]


def test_a_pause_on_the_windows_own_thread_never_waits():
    window_idle.busy()
    try:
        t0 = time.perf_counter()
        window_idle.pause()
        assert time.perf_counter() - t0 < 0.005
    finally:
        window_idle.rest()


class _Clock:
    """The clock window_idle reads (`time.perf_counter`), moved by the test: a stretch is young or old by the test's
    word, never by how fast a loaded machine starts a thread."""
    def __init__(self, t=100.0):
        self.t = t

    def perf_counter(self):
        return self.t


class _SeenIdle(threading.Event):
    """window_idle's idle event, keeping each wait's timeout and saying when a wait has begun — the waits of this
    file's own pieces (threads named MINE) only: a worker another test file left running (a move's write, a look,
    a bridge job: `window_idle.wait()`, CAP_S) waits on the same event and isn't the piece (train 29's GitHub core
    1/4: `[0.015, 0.05]`)."""
    def __init__(self):
        super().__init__()
        self.set()
        self.timeouts, self.waiting = [], threading.Event()

    def wait(self, timeout=None):
        if threading.current_thread().name == MINE:
            self.timeouts.append(timeout)
            self.waiting.set()
        return super().wait(timeout)


def test_a_pause_inside_a_step_waits_out_a_young_window_stretch_and_never_an_old_one(monkeypatch):
    """(Up next 3) Between two pieces of a long step: the window just woke → the piece waits (till it rests, `SPAN_S`
    after it woke at most); a window awake longer than that → no wait at all, so a window that never rests never makes
    a 300-piece build wait 300 times; at rest → no wait.
    The clock is the test's and the idle event a seen one (Tool-T, 2026-11-12): the real-clock form measured a wait
    against SPAN_S with no slack and went red at 0.0200591 s on a loaded runner (tests/FLAKES.md)."""
    clock, seen = _Clock(), _SeenIdle()
    monkeypatch.setattr(window_idle, "time", clock)
    monkeypatch.setattr(window_idle, "_idle", seen)
    window_idle.pause()                                        # (at rest: one look, no wait)
    window_idle.busy()                                         # (woke at 100.000)
    try:
        clock.t = 100.005
        _in_a_worker(window_idle.pause)                        # (young: waits out the rest of SPAN_S)
        assert seen.timeouts == [pytest.approx(window_idle.SPAN_S - 0.005)]
        clock.t = 100.0 + window_idle.SPAN_S + 0.001          # (old now: no wait, for a hundred pieces either)
        _in_a_worker(lambda: [window_idle.pause() for _ in range(100)])
        window_idle.busy()                                     # (still awake: the stretch's start is kept)
        _in_a_worker(window_idle.pause)
        assert len(seen.timeouts) == 1, seen.timeouts
    finally:
        window_idle.rest()
    monkeypatch.setattr(window_idle, "SPAN_S", 60.0)           # woke anew after a rest: young again, and resting ends it
    window_idle.busy()                                         # (a minute's stretch: only the rest can end the wait)
    try:
        seen.waiting.clear()
        worker = threading.Thread(target=window_idle.pause, name=MINE)
        worker.start()
        assert seen.waiting.wait(5)                            # (the piece waits...)
        assert seen.timeouts[-1] == pytest.approx(60.0)
        window_idle.rest()                                     # (...till the window rests)
        worker.join(5)
        assert not worker.is_alive()
    finally:
        window_idle.rest()


def test_while_the_window_is_awake_pythons_lock_comes_back_to_it_at_once_and_at_rest_as_before():
    # Mado-SP: under 1 ms Windows' Python asks for the lock at once (and two busy workers spin, 3.5x as slow), so the
    # fine hand-over holds only from the window's waking to its rest; once a stretch, not at each `awake`
    import sys
    was = sys.getswitchinterval()
    try:
        window_idle.set_switch(0.00025, 0.001)
        sys.setswitchinterval(0.001)
        window_idle.busy()
        assert sys.getswitchinterval() == pytest.approx(0.00025)
        sys.setswitchinterval(0.002)                    # (someone's own setting inside the stretch: a second awake
        window_idle.busy()                              # of the same stretch leaves it)
        assert sys.getswitchinterval() == pytest.approx(0.002)
        window_idle.rest()
        assert sys.getswitchinterval() == pytest.approx(0.001)
        sys.setswitchinterval(0.003)
        window_idle.rest()                              # already at rest: nothing set again
        assert sys.getswitchinterval() == pytest.approx(0.003)
        window_idle.set_switch(None, None)              # without a window: never changed
        window_idle.busy()
        window_idle.rest()
        assert sys.getswitchinterval() == pytest.approx(0.003)
    finally:
        window_idle.set_switch(None, None)
        window_idle.rest()
        sys.setswitchinterval(was)
