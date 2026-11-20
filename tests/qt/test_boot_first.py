"""Booted first, on every PC (Haya-LD, 3.0.18; Sonic 2026-11-20: "I would like it to first boot up / launch before
doing the rest. that would be consistent across the board").

The window is *booted* when Current's list, filled from what is on disk (a view that isn't the cached first screen),
has been drawn and its event loop has gone idle once after it — or `gentle.BOOT_MAX_S` after its first frame. Until
then `Services.start` — the Anki look and Connect's kick, the known-words sync, the journey check, the update check,
the chores (the indexer, the store's helper) — waits; then it starts once, and the scheduler hears it (`booted`).

What a wrong answer would cost: on the laptop (report #8158GX) Current stayed blank 79 s while six background jobs
started beside it; held the other way, a window whose list never draws (a store that can't be read) would never sync,
mine or index at all. The duties are the bar's test's stand-ins (`tests/qt/test_jobs_bar.py`), the view a real
`view_rows` view; `boot_gate` is turned on here (the suites run with it off: SURASURA_NO_UI_TIMERS).
"""
import pytest
from PyQt6.QtWidgets import QApplication

from app.qt import applog
from app.services import gentle as gentle_module
from app.services import view_rows
from tests.qt.conftest import wait_until as _processed_until
from tests.qt.test_jobs_bar import World

STARTED = ("updates.begin", "automation.started", "chores.started")


class _Reader:
    """A library reader's shape for the boot: its newest view, nothing published by itself."""

    language = "ja"

    def __init__(self, view):
        self._view = view

    def view(self):
        return self._view

    def subscribe(self, cb):
        pass

    def subscribe_moves(self, cb):
        pass


def _view(loading):
    return view_rows.build({}, {}, {}, language="ja", mode="store", loading=loading)


@pytest.fixture
def lines(monkeypatch):
    said = []
    monkeypatch.setattr(applog, "log", lambda area, msg: said.append((area, msg)))
    return said


@pytest.fixture
def gated(qapp, tmp_path):
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    w.win.boot_gate = True
    yield w
    w.close()


def wait_until(predicate, timeout=5.0):
    """Run a real event loop (it blocks between events, so the dispatcher's `aboutToBlock` comes — the boot's idle;
    `processEvents` alone never blocks) until `predicate()` is true or the time is up."""
    import time
    from PyQt6.QtCore import QEventLoop, QTimer
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return _processed_until(predicate, 0)


def _started(world):
    return [name for name in world.log if name in STARTED]


def _settle(ms=300):
    wait_until(lambda: False, ms / 1000)


def test_nothing_in_the_background_starts_before_the_list_from_disk_is_drawn(gated, lines):
    gated.services.library = _Reader(_view(loading=True))       # only the cached first screen so far
    gated.win.start_duties()
    _settle()
    assert _started(gated) == [] and not gated.services.boot.is_set()
    gated.win.show_library(_view(loading=True))
    _settle()
    assert _started(gated) == [], "the cached first screen is no boot: its list isn't from disk yet"
    gated.win.show_library(_view(loading=False))
    assert wait_until(lambda: set(_started(gated)) == set(STARTED))
    assert gated.services.boot.is_set()
    assert any(area == "shell" and msg.startswith("booted") and "after the process began" in msg
               for area, msg in lines), lines


def test_the_duties_start_once_however_many_views_come(gated, lines):
    gated.services.library = _Reader(_view(loading=True))
    gated.win.start_duties()
    for _ in range(3):
        gated.win.show_library(_view(loading=False))
        QApplication.processEvents()
    assert wait_until(lambda: "chores.started" in gated.log)
    _settle()
    assert [name for name in gated.log if name == "chores.started"] == ["chores.started"]
    assert len([m for a, m in lines if m.startswith("booted")]) == 1


def test_with_no_library_to_draw_it_boots_at_the_first_idle(gated, lines):
    gated.services.library = None                               # the library couldn't be opened (AD0-12)
    gated.win.start_duties()
    assert wait_until(lambda: "chores.started" in gated.log)


def test_a_list_that_never_draws_still_boots_at_its_limit(gated, lines, monkeypatch):
    monkeypatch.setattr(gentle_module, "BOOT_MAX_S", 0.3)
    gated.services.library = _Reader(_view(loading=True))
    gated.win.start_duties()
    assert wait_until(lambda: "chores.started" in gated.log)
    assert any("its limit passed" in msg for _a, msg in lines)


def test_the_scheduler_hears_the_boot_and_lets_background_work_go(gated, lines):
    from app.services import jobs
    g = gentle_module.Gentle(gated.registry, machine=lambda: (False, None), log=lambda line: None,
                             reviewing=lambda: False).attach(watch=False)
    gated.services.gentle = g
    try:
        job = gated.registry.submit("arrivals-ja", "Counting new arrivals", start=lambda j: None, automatic=True)
        assert job.reason == gentle_module.WINDOW_FIRST, "booted first on a strong PC too"
        gated.services.library = _Reader(_view(loading=False))
        gated.win.show_library(_view(loading=False))          # a list from disk drawn before the first frame's call
        assert job.state == jobs.WAITING
        gated.win.start_duties()
        assert wait_until(lambda: job.state == jobs.RUNNING)
    finally:
        g.close()


def test_under_the_suites_switch_the_duties_start_as_before(qapp, tmp_path):
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    try:
        assert w.win.boot_gate is False
        w.start()
        assert wait_until(lambda: "chores.started" in w.log)
    finally:
        w.close()
