"""The frame-time HUD (W2.1 row 8; the window's spec 07 §7.1 *Budgets*: no GUI-thread step over 4 ms).

What a wrong answer would cost: a budget nobody can see broken (a 6 ms step that never shows), or an instrument that
itself costs the window time when it's off.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QAbstractEventDispatcher, QEventLoop, QTimer

from app.qt import hud, shell
from tests.qt.conftest import wait_until


@pytest.fixture
def window(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


def _run_loop(ms):
    # A real event loop (it blocks when idle, as app.exec() does): the dispatcher's awake / aboutToBlock fire only then.
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_a_slot_that_takes_6_ms_is_counted_over_the_budget(qapp, window):
    meter = hud.Hud(window, overlay=False).start()
    try:
        _run_loop(100)
        quiet = len(meter.over)
        assert meter.steps                               # it measures steps at all
        QTimer.singleShot(20, lambda: time.sleep(0.006))
        _run_loop(150)
        # the 6 ms slot is one stretch over the budget (a loaded machine may add others: never fewer than it)
        new = [ms for ms, _ in meter.over[quiet:]]
        assert any(ms >= 6 for ms in new), new
        assert meter.report()["steps"]["over_4ms"] == len(meter.over)
    finally:
        meter.stop()


def test_a_frame_of_the_window_is_measured(qapp, window):
    meter = hud.Hud(window, overlay=False).start()
    try:
        window.update()
        assert wait_until(lambda: meter.frames, 3)
        assert meter.report()["frames"]["n"] >= 1
    finally:
        meter.stop()


def test_a_named_span_is_reported(qapp, window):
    meter = hud.Hud(window, overlay=False)
    with meter.span("current-rows"):
        time.sleep(0.002)
    r = meter.report()["spans"]["current-rows"]
    assert r["n"] == 1 and r["max_ms"] >= 2


def test_the_overlay_shows_its_numbers(qapp, window):
    meter = hud.Hud(window, overlay=True).start()
    try:
        meter._show()
        assert meter.label.isVisible() and "step p95" in meter.label.text()
    finally:
        meter.stop()


def test_off_the_hud_installs_nothing(qapp, window, monkeypatch):
    monkeypatch.delenv("SURASURA_HUD", raising=False)
    assert not hud.wanted([])
    assert hud.wanted(["app", "--hud"])
    dispatcher = QAbstractEventDispatcher.instance()
    before = dispatcher.receivers(dispatcher.awake)
    hud.Hud(window, overlay=False)                     # made but not started
    assert dispatcher.receivers(dispatcher.awake) == before


def test_p95_reads_the_right_rank():
    assert hud.p95([]) == 0.0
    assert hud.p95(list(range(1, 101))) == 95


def test_a_late_tick_shows_a_wait_the_steps_cannot_see(qapp, window):
    # Review A3: a step's clock starts only once the GUI thread holds Python's lock again, so a wait for the lock is
    # invisible to it; the 2 ms precise timer comes late instead. An 8 ms block of the loop must read as a late tick.
    meter = hud.Hud(window, overlay=False).start()
    try:
        _run_loop(100)
        QTimer.singleShot(20, lambda: time.sleep(0.008))
        _run_loop(150)
        r = meter.report()["late"]
        assert r["n"] > 20 and r["over_4ms"] >= 1 and r["max_ms"] >= 5
    finally:
        meter.stop()


# --- M2.1 row D: the late ticks explained, the start's phases -------------------------------------------------------- #
# What a wrong answer would cost: a cause told to Sonic that the counters don't support (the stack pack's HOT: prove a
# cause A/B), or an instrument that breaks the window off Windows.
def _rec(**kw):
    base = {"late_ms": 10.0, "gc_ms": 0.0, "in_stretch_ms": 0.0, "gui_ms": 0.5, "other_ms": 0.5, "idle_share": 0.8}
    base.update(kw)
    return base


def test_classify_names_each_cause_from_its_counters():
    assert hud.classify(_rec(gc_ms=7.0)) == "gc"                       # the collector held the lock for most of it
    assert hud.classify(_rec(in_stretch_ms=9.0)) == "step"             # it waited behind work in the same stretch
    assert hud.classify(_rec(gui_ms=8.0)) == "gui-busy"                # the GUI thread ran outside a counted stretch
    assert hud.classify(_rec(other_ms=9.0)) == "other-thread"          # another thread of ours ran (not proven: GIL)
    assert hud.classify(_rec(idle_share=0.1)) == "machine"             # nothing here ran; the processors were busy
    assert hud.classify(_rec(res_ms=15.6)) == "timer"                  # Windows' timer coarse enough to explain it
    assert hud.classify(_rec(res_ms=1.0)) == "unexplained"             # nothing ran, idle machine, a fine timer
    assert hud.classify(_rec(gui_ms=None, other_ms=None)) == "unknown"  # no counters on this system
    assert set(hud.CAUSES) >= {"gc", "step", "gui-busy", "other-thread", "machine", "timer", "unexplained"}


def test_off_windows_the_counters_answer_none_never_an_error(monkeypatch):
    monkeypatch.setattr(hud.sys, "platform", "linux")
    c = hud.Counters()
    assert not c.ok and c.sample() is None
    assert c.between(None, None) == {"gui_ms": None, "other_ms": None, "idle_share": None, "res_ms": None}
    assert hud._faults_and_reads() is None


@pytest.mark.skipif(hud.sys.platform != "win32", reason="Windows' counters")
def test_on_windows_the_counters_read_and_a_busy_spin_shows_as_gui_cpu():
    c = hud.Counters()
    assert c.ok and c.mhz and c.mhz > 100
    a = c.sample()
    end = time.perf_counter() + 0.03
    while time.perf_counter() < end:
        pass
    b = c.sample()
    between = c.between(a, b)
    assert between["gui_ms"] > 10 and 0.0 <= between["idle_share"] <= 1.0 and between["res_ms"] > 0


def test_the_collector_watch_finds_a_collection_in_a_gap():
    w = hud.GcWatch()
    w.events = [(1.000, 1.008, 2, True), (2.000, 2.001, 0, False)]
    assert w.within(0.995, 1.010) == (8.0, 2, False)
    total, gen, elsewhere = w.within(1.5, 2.5)
    assert total == 1.0 and gen == 0 and elsewhere
    assert w.within(3.0, 4.0) == (0.0, None, False)


def test_a_real_collection_during_the_hud_is_seen(qapp, window):
    import gc
    meter = hud.Hud(window, overlay=False).start()
    try:
        t0 = time.perf_counter()
        gc.collect()
        t1 = time.perf_counter()
        total, gen, _elsewhere = meter.gcwatch.within(t0, t1)
        assert gen == 2 and total > 0
    finally:
        meter.stop()
    assert meter.gcwatch not in __import__("gc").callbacks          # stopped: the watch is gone


def test_the_phases_are_consecutive_and_sum_to_the_last_mark(monkeypatch):
    marks = [("main", 10.0, 300.0, None, (100, 1000)), ("qapp", 10.02, 320.0, None, (150, 5000)),
             ("window", 10.10, 400.0, None, (300, 9000)), ("flushed", 10.15, 450.0, None, (310, 9100))]
    rows = hud.phases(marks)
    named = [r for r in rows if r["phase"] in ("qapp", "window", "flushed")]
    assert [r["ms"] for r in named] == [20.0, 80.0, 50.0] and named[0]["faults"] == 50
    first = [r for r in rows if r["phase"] in ("python+app_entry", "imports-to-main")]
    assert len(first) == 2 and round(sum(r["ms"] for r in first), 1) == 300.0
    assert round(sum(r["ms"] for r in rows), 1) == 450.0               # they add up to the first frame


def test_marks_are_nothing_without_the_probe(monkeypatch):
    monkeypatch.delenv("SURASURA_SHELL_PROBE", raising=False)
    before = len(hud.MARKS)
    hud.mark("anything")
    assert len(hud.MARKS) == before


def test_a_motion_frame_is_counted_with_the_paint_that_follows_it(qapp, window):
    meter = hud.Hud(window, overlay=False).start()
    try:
        meter.tag = "pop"
        meter._clock_frame(0.5, 0.3)
        window.update()
        assert wait_until(lambda: meter.anim_frames, 3)
        r = meter.report()
        assert r["anim"]["frames"] >= 1 and r["anim"]["ticks"] == 1 and r["tagged"]["pop"]["n"] >= 1
    finally:
        meter.stop()


def test_the_probe_start_runs_main_and_writes_every_phase(qapp, monkeypatch, tmp_path):
    # M2.1 row D: shell.main() with the probe on — the measuring scripts' way in — marks each phase of the start and
    # writes them (a name clash in main() once crashed every measured start before its first frame).
    import json
    import sys
    probe = tmp_path / "probe.json"
    monkeypatch.setenv("SURASURA_SHELL_PROBE", str(probe))
    monkeypatch.setenv("SURASURA_SHELL_PROBE_IDLE", "0.3")
    monkeypatch.delenv("SURASURA_HUD", raising=False)
    hook, interval = sys.excepthook, sys.getswitchinterval()
    hud.MARKS.clear()
    try:
        code = shell.main(["probe-test"])
    finally:
        sys.excepthook, _ = hook, sys.setswitchinterval(interval)
        hud.MARKS.clear()
    data = json.loads(probe.read_text(encoding="utf-8"))
    names = [p["phase"] for p in data["phases"]]
    assert code == 0 and data["first_frame_ms"] is not None
    assert {"qapp", "claimed", "services", "look", "window", "shown", "painted", "flushed"} <= set(names)
