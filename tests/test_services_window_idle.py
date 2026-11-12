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


def test_a_save_gets_pythons_lock_at_once_till_the_last_one_ends_then_the_hand_over_before_comes_back():
    """F13's leftover: while a store save holds the write lock (`save_began` … `save_ended`, `Store._writing`), the
    lock comes back to it at once; saves on two threads overlap, so only the last one's end puts back what was set
    before — the first one's would leave the other's SQLite steps waiting a whole interval each again. A finer
    hand-over already set (the harness's 1 µs probe) is never coarsened, and is left as it was."""
    import sys
    was = sys.getswitchinterval()
    try:
        sys.setswitchinterval(0.005)
        window_idle.save_began()
        assert sys.getswitchinterval() == window_idle.SAVE_SWITCH_S
        window_idle.save_began()                        # (a second thread's save, inside the first)
        window_idle.save_ended()
        assert sys.getswitchinterval() == window_idle.SAVE_SWITCH_S     # (one still under way)
        window_idle.save_ended()
        assert sys.getswitchinterval() == pytest.approx(0.005)
        window_idle.save_ended()                        # (an end with none under way: nothing)
        assert sys.getswitchinterval() == pytest.approx(0.005)
        sys.setswitchinterval(0.000001)
        window_idle.save_began()
        assert sys.getswitchinterval() == pytest.approx(0.000001)
        window_idle.save_ended()
        assert sys.getswitchinterval() == pytest.approx(0.000001)
        sys.setswitchinterval(0.005)
        window_idle.save_began()
        sys.setswitchinterval(0.002)                    # (someone's own setting inside the save: it stays)
        window_idle.save_ended()
        assert sys.getswitchinterval() == pytest.approx(0.002)
    finally:
        while window_idle._saves["n"]:
            window_idle.save_ended()
        sys.setswitchinterval(was)


def test_a_save_under_way_keeps_the_fine_hand_over_through_the_windows_rest_and_its_end_puts_back_the_windows():
    """In the window's process the window sets its own hand-over at each wake and rest (`set_switch`): a rest in the
    middle of a save would put back 1 ms under it, so it waits for the save's end; that end puts back the window's
    own — 1 ms at rest, its finer one while it is awake — never the value from before the save."""
    import sys
    was = sys.getswitchinterval()
    try:
        window_idle.set_switch(0.0002, 0.001)
        sys.setswitchinterval(0.001)
        window_idle.save_began()
        assert sys.getswitchinterval() == window_idle.SAVE_SWITCH_S
        window_idle.busy()                              # (the window woke while the save went on: its finer one)
        assert sys.getswitchinterval() == pytest.approx(0.0002)
        window_idle.rest()                              # (and rested: held back till the save's end)
        assert sys.getswitchinterval() == pytest.approx(0.0002)
        window_idle.save_ended()
        assert sys.getswitchinterval() == pytest.approx(0.001)          # (at rest: the window's at-rest one)
        window_idle.save_began()
        window_idle.busy()                              # (awake when the save ends: the window's awake one)
        window_idle.save_ended()
        assert sys.getswitchinterval() == pytest.approx(0.0002)
        window_idle.rest()
        assert sys.getswitchinterval() == pytest.approx(0.001)
        window_idle.busy()                              # (a save begun while the window is awake lowers nothing —
        window_idle.save_began()                        # finer already — but the rest it held back is still put
        window_idle.rest()                              # back at its end)
        assert sys.getswitchinterval() == pytest.approx(0.0002)
        window_idle.save_ended()
        assert sys.getswitchinterval() == pytest.approx(0.001)
    finally:
        window_idle.set_switch(None, None)
        window_idle.rest()
        while window_idle._saves["n"]:
            window_idle.save_ended()
        sys.setswitchinterval(was)
