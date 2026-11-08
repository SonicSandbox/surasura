"""The window's idle for the window process's background threads (`app/services/window_idle.py`, Up next 2).

What a wrong answer would cost a learner: a worker that never waits takes turns at Python's lock with the window's
thread while it paints a press (Alt+↑ at 20,000 files: 7 ms of the window's work stretched to 26 ms); one that waits for
good — a window that never rests — stops the library's views and the saves for ever.
"""
import threading
import time

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


def _timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def _in_a_worker(fn):
    out = []
    t = threading.Thread(target=lambda: out.append(fn()))
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


def test_a_pause_inside_a_step_waits_out_a_young_window_stretch_and_never_an_old_one():
    """(Up next 3) Between two pieces of a long step: the window just woke → the piece waits (till it rests, `SPAN_S`
    after it woke at most); a window awake longer than that → no wait at all, so a window that never rests never makes
    a 300-piece build wait 300 times; at rest → no wait."""
    t0 = time.perf_counter()
    window_idle.pause()
    assert time.perf_counter() - t0 < 0.005
    window_idle.busy()
    try:
        waited = _in_a_worker(lambda: _timed(window_idle.pause))    # (young: waits out the rest of SPAN_S)
        assert 0.01 <= waited <= window_idle.SPAN_S + 0.05, waited
        assert _in_a_worker(lambda: _timed(lambda: [window_idle.pause() for _ in range(100)])) < 0.01   # (old now)
        window_idle.busy()                                     # (still awake: the stretch's start is kept)
        assert _in_a_worker(lambda: _timed(window_idle.pause)) < 0.01
    finally:
        window_idle.rest()
    window_idle.busy()                                         # woke anew after a rest: young again, and resting ends it
    try:
        threading.Timer(0.005, window_idle.rest).start()
        assert _in_a_worker(lambda: _timed(window_idle.pause)) < window_idle.SPAN_S
    finally:
        window_idle.rest()
