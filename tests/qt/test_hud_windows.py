"""The HUD sees every window's frames (M4.1 row 2; the RUNBOOK's bar: a moment's frames p95 and every slow frame with
its cause, on every moment a user feels).

What a wrong answer would cost: a moment judged on frames it never saw (the lift's opening, the drag's ghost and a
popup menu paint in windows of their own: W3.1a timed-1 found bench_motion's tags empty at 125–200 % for that), a
clock frame's cost put on the wrong window's next paint (a slow main-window frame that was the lift's work), or a slow
frame brought to Sonic with no cause, or the wrong one.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QLabel

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
    loop = QEventLoop()                            # a real loop: it waits when idle, so the dispatcher's signals fire
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class _Popup(QLabel):
    """A top-level popup of its own (the kind of the row's ⋯ menu or a tooltip), with real text; `spin_ms` makes its
    paint take that long on the GUI thread's own processor."""

    def __init__(self, parent, spin_ms=0.0):
        super().__init__("進撃の巨人 → Soon · #26", parent, Qt.WindowType.ToolTip)
        self.setObjectName("rowmenu")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.spin_ms = spin_ms
        self.resize(220, 40)

    def paintEvent(self, event):
        end = time.perf_counter() + self.spin_ms / 1000.0
        while time.perf_counter() < end:
            pass
        super().paintEvent(event)


def _frames(meter, kind):
    return [f for f in meter.explain_frames() if f["window"] == kind]


def test_a_frame_in_a_second_window_is_counted_and_tagged_with_its_window(qapp, window):
    meter = hud.Hud(window, overlay=False).start()
    pop = _Popup(window)
    try:
        pop.show()
        _run_loop(30)
        n = len(_frames(meter, "popup"))
        meter.tag = "menu"
        pop.update()
        assert wait_until(lambda: len(_frames(meter, "popup")) > n, 3)
        f = _frames(meter, "popup")[-1]
        assert f["name"] == "rowmenu" and f["work_ms"] is None and f["paint_ms"] >= 0.0
        assert meter.report()["windows"]["popup"]["n"] >= 1
        # the main window's own frames are still counted, as its own
        window.update()
        assert wait_until(lambda: _frames(meter, "main"), 3)
    finally:
        meter.stop()
        pop.close()


def test_a_lift_window_frame_and_a_paintless_clock_frame_count_as_the_lift(qapp, window):
    # The lift (motion._Lift) is a QWindow, not a widget: its own update is a frame of the lift's; and a clock frame
    # that moves only it (its opacity and place, in Windows' compositor) paints nothing — still a frame, the lift's.
    meter = hud.Hud(window, overlay=False).start()
    lift = QWindow()
    lift.setObjectName("motionLift")
    lift.setFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
    lift.resize(60, 40)
    try:
        lift.show()
        _run_loop(30)
        lift.requestUpdate()
        assert wait_until(lambda: _frames(meter, "lift"), 3)
        before = len(_frames(meter, "lift"))
        meter.tag = "tray"
        meter._clock_frame(0.4, 1.5)               # the clock moved the lift; no widget repaints
        _run_loop(40)
        moved = [f for f in _frames(meter, "lift")[before:] if f["work_ms"] is not None]
        assert len(moved) == 1 and moved[0]["work_ms"] == pytest.approx(1.5) and moved[0]["paint_ms"] == 0.0
        assert meter.report()["tagged"]["tray"]["n"] >= 1          # bench_motion's per-kind tags read these
    finally:
        meter.stop()
        lift.destroy()


def test_a_clock_frames_work_lands_in_the_frame_that_paints_it_not_the_main_windows_next(qapp, window):
    # Before M4.1 the work waited for the main window's next frame: a popup's opening frame piled onto whatever the
    # main window painted next (or vanished). It belongs to the window that painted it, once.
    meter = hud.Hud(window, overlay=False).start()
    pop = _Popup(window)
    try:
        pop.show()
        _run_loop(30)
        n_pop, n_main = len(_frames(meter, "popup")), len(_frames(meter, "main"))
        meter._clock_frame(0.2, 3.0)
        pop.update()
        assert wait_until(lambda: len(_frames(meter, "popup")) > n_pop, 3)
        painted = _frames(meter, "popup")[n_pop:]
        assert painted[0]["work_ms"] == pytest.approx(3.0) and painted[0]["ms"] >= 3.0
        window.update()
        assert wait_until(lambda: len(_frames(meter, "main")) > n_main, 3)
        assert all(f["work_ms"] is None for f in _frames(meter, "main")[n_main:])
        assert sum(1 for f in meter.explain_frames() if f["work_ms"] is not None) == 1     # counted once
    finally:
        meter.stop()
        pop.close()


def test_a_window_painted_inside_the_clocks_frame_is_that_one_frame_not_two(qapp, window):
    # A look that repaints at once from its frame (`repaint()`, as Settings' choice vein does) paints inside the clock's
    # work: one frame of that window, its paint inside the work — never a second frame, nor the work handed on to
    # whatever paints next.
    from app.qt import freeze, motion
    meter = hud.Hud(window, overlay=False).start()
    pop = _Popup(window)
    clock = motion.clock()
    try:
        pop.show()
        _run_loop(30)
        freeze.set_frozen(False)
        clock.use_test_time(0.0)
        n = len(meter.explain_frames())
        clock.animate(48, lambda v: pop.repaint(), kind="fade")
        clock.advance(48)
        new = meter.explain_frames()[n:]
        assert len(new) == 3 and meter._pending is None, new
        assert all(f["window"] == "popup" and f["paint_ms"] > 0.0 and f["work_ms"] is not None for f in new)
        assert all(f["ms"] >= f["paint_ms"] for f in new)
    finally:
        clock.use_real_time()
        meter.stop()
        pop.close()


def test_a_slow_frame_names_a_cause(qapp, window):
    # A popup whose paint keeps the GUI thread's processor 9 ms: over the 6.4 ms bar, its cause its own paint.
    meter = hud.Hud(window, overlay=False).start()
    pop = _Popup(window, spin_ms=9.0)
    try:
        pop.show()
        _run_loop(60)
        pop.update()
        _run_loop(80)
        slow = [f for f in _frames(meter, "popup") if f["ms"] > hud.SLOW_MS]
        assert slow, [f["ms"] for f in _frames(meter, "popup")]
        assert all(f["cause"] in hud.CAUSES + ("paint",) for f in slow)
        assert slow[-1]["cause"] == "paint"
        r = meter.report()["slow_frames"]
        assert r["n"] >= 1 and r["causes"].get("paint", 0) >= 1 and r["worst"][0]["window"] == "popup"
    finally:
        meter.stop()
        pop.close()


def test_frame_cause_reads_the_collector_the_late_tick_and_the_frames_own_split(qapp, window):
    # The causes from their counters (made-up records, as test_hud's classify test): Python's collector over the frame;
    # another thread or the machine under the late tick over it; else the frame's own paint or the clock's work in it.
    meter = hud.Hud(window, overlay=False)
    meter.gcwatch = hud.GcWatch()
    frame = {"ms": 9.0, "t0": 10.000, "t1": 10.009, "paint_ms": 7.0, "work_ms": 2.0}
    assert meter.frame_cause(dict(frame, ms=5.0)) is None                  # within the bar: no cause asked
    assert meter.frame_cause(frame) == "paint"                             # nothing else ran: its own paint
    assert meter.frame_cause(dict(frame, paint_ms=1.0, work_ms=8.0)) == "step"      # the clock's work in it
    tick = {"late_ms": 9.0, "gc_ms": 0.0, "in_stretch_ms": 9.0, "gui_ms": 0.3, "other_ms": 8.0, "idle_share": 0.8}
    meter.late_spans = [(9.999, 10.010, tick)]
    assert meter.frame_cause(frame) == "other-thread"                      # (its wait behind the frame set aside)
    meter.late_spans = [(9.999, 10.010, dict(tick, other_ms=0.2, idle_share=0.1))]
    assert meter.frame_cause(frame) == "machine"
    meter.late_spans = [(9.999, 10.010, dict(tick, other_ms=0.2, gui_ms=8.5))]
    assert meter.frame_cause(frame) == "paint"                             # the GUI thread busy: the frame itself
    meter.gcwatch.events = [(10.001, 10.008, 2, True)]
    assert meter.frame_cause(frame) == "gc"
