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
