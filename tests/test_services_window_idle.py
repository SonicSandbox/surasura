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
