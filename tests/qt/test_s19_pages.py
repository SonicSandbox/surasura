"""Charter S19 on every page (Sonic, 2026-10-08: "update only what changed"; alpha 4, A4): a view the reader builds
afresh that changes nothing on screen — every row a new object with the same face, the numbers' new version holding the
same numbers — paints nothing on the page the learner is on: Current (its Soon rows and the Goal dock under them),
Finished, Needs you, Settings, New arrivals' tray open over Current, and the header above them all.

What a wrong answer would cost a learner: a window that flickers or redraws a whole page on every background tick
(a Generate's numbers, Connect's looks, an import's batches) — on the laptop each needless whole-page paint is a frame
he sees stutter while he reads or drags.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from tests.qt.conftest import logos_in, needs_in, wait_until
from tests.qt.test_current import _settings, open_on, seeded, _stones_sheet      # noqa: F401
from app.qt import style


class Paints(QObject):
    def __init__(self):
        super().__init__()
        self.painted = []

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Paint:
            self.painted.append((type(obj).__name__, obj.objectName()))
        return False


def _at_rest(win):
    """Everything the window does after a view done: the strip's logos, Needs you's answer, the lists' paint-ahead."""
    assert logos_in(win.phase) and needs_in(win)
    lists = [p.list for p in win.page_widgets.values() if hasattr(p, "list")]
    assert wait_until(lambda: not any(lst._warm.isActive() for lst in lists), 10)
    QTest.qWait(300)
    QApplication.processEvents()


def _same_again(seed, win):
    """A view built afresh that changes nothing on screen: the numbers' new version with the very same numbers (every
    row rebuilt — the seed's numbers can't say which changed — each with the same face). -> once the window took it."""
    page = win.page_widgets["current"]
    before = page.view_model
    seed.numbers.version += 1
    win.services.library.refresh()
    assert wait_until(lambda: page.view_model is not before and page.view_model.rows[0] is not before.rows[0], 5)
    return before, page.view_model


def _watch(qapp, seed, win):
    spy = Paints()
    qapp.installEventFilter(spy)
    try:
        before, after = _same_again(seed, win)
        QTest.qWait(500)                                     # nothing happens for a while: any repaint would show here
    finally:
        qapp.removeEventFilter(spy)
    return spy.painted, before, after


@pytest.mark.parametrize("tab", ["current", "finished", "needs", "settings"])
def test_a_view_that_changes_nothing_paints_nothing_on_the_page_shown(qapp, seeded, tab):
    seed, win = seeded()
    if tab == "settings":
        win.mount_settings()
    win.show_tab(tab)
    _at_rest(win)
    painted, before, after = _watch(qapp, seed, win)
    assert after.rows[1] is not before.rows[1]               # the rows really are new objects (not a no-op)
    assert painted == [], painted


def test_a_view_that_changes_nothing_paints_nothing_under_the_open_arrivals_tray(qapp, seeded):
    """New arrivals' tray open over Current (the inset's click): the same arrivals in a new view repaint neither the
    tray's rows nor the inset nor the list under them."""
    seed, win = seeded()
    _at_rest(win)
    win.open_arrivals()
    tray = win.arrivals_tray
    assert wait_until(tray.isVisible, 5)
    QTest.qWait(600)                                          # its rise done
    _at_rest(win)
    painted, _before, _after = _watch(qapp, seed, win)
    assert painted == [], painted


def test_a_view_that_changes_nothing_paints_nothing_on_the_open_goal_sheet(qapp, seeded):
    """Goal's sheet risen over Current (the dock's bar, as its click asks): the same Goal in a new view repaints no tile,
    no dock and nothing under it."""
    seed, win = seeded()
    _at_rest(win)
    sheet = win.goal_sheet
    win.dock.sheet_requested.emit()
    assert wait_until(sheet.isVisible, 5)
    QTest.qWait(700)                                          # its rise done
    _at_rest(win)
    painted, before, after = _watch(qapp, seed, win)
    assert after.goal is not None
    assert painted == [], painted


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_header_and_the_tabs_paint_nothing_for_a_view_that_changes_nothing(qapp, seeded, language):
    """The header (the subline's counts, the tabs' counts, the phase strip) reads every view: the same counts in a new
    view repaint none of it, in either language."""
    if language == "zh":
        _settings(target_language="zh", zh_script="s")
    try:
        seed, win = seeded(language=language)
        _at_rest(win)
        painted, _before, _after = _watch(qapp, seed, win)
        assert painted == [], painted
    finally:
        style.apply(qapp, "night", "M", "ja")
