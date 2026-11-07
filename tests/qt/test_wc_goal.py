"""Work counts on Goal's dock and sheet (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a sheet that builds itself again on every open, picks that repaint every tile.

The screen: test_goal_sheet's `world` fixture (one window a test).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_goal_sheet import bar_point, calls, goal_view, open_sheet, tile_of, world   # noqa: F401
from tests.qt.test_drag import _stones_sheet   # noqa: F401  (autouse: the stones drawn before the window opens)


# --- R3: a range pick repaints the tiles that changed -------------------------------------------------------------- #
def test_r3_a_shift_click_after_a_pick_repaints_only_the_tiles_of_the_range(world):
    """Goal's sheet: a Shift+click takes the tiles from the picked anchor to this one; only the tiles whose pick changed
    repaint, and nothing else in the sheet or the window does."""
    _seed, win, _w = world()
    sheet = open_sheet(win)
    wc.rest(150)
    pk = [t for t in sheet.order if sheet.pickable(t.work)]
    assert len(pk) >= 3, [t.work.title for t in sheet.order]
    QTest.mouseClick(pk[0], Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     QPoint(pk[0].width() // 2, pk[0].height() // 3))          # the anchor: Ctrl+click
    wc.rest(150)
    changed = pk[1:3]                                                       # the range is pk[0]..pk[2]
    rects = [wc.rect_in_window(t).adjusted(-wc.STRIP_SLACK_PX, -wc.STRIP_SLACK_PX,
                                           wc.STRIP_SLACK_PX, wc.STRIP_SLACK_PX) for t in changed]
    with wc.measure(win, readers=[win.services.library]) as w:
        QTest.mouseClick(pk[2], Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                         QPoint(pk[2].width() // 2, pk[2].height() // 3))
        wc.rest(150)
    assert sheet.picks == {t.work.key for t in pk[:3]}, w.report()
    assert all(w.painted_in(t) > 0 for t in changed), w.report()
    assert w.paints_outside_rect(*rects) == [], w.report()


def test_ctrl_a_on_the_goal_sheet_picks_every_tile_and_repaints_the_tiles_and_nothing_outside_the_sheet(world):
    """Ctrl+A on Goal's sheet: every tile the picks can take is picked; the tiles repaint and nothing outside the sheet
    is painted (no window repainted whole, the dock and the page untouched)."""
    _seed, win, _writer = world()
    sheet = open_sheet(win)
    wc.rest(150)
    sheet.setFocus()
    wc.rest(50)
    try:
        with wc.measure(win, readers=[win.services.library]) as w:
            QTest.keyClick(sheet, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            wc.rest(150)
        assert sheet.picks and sheet.picks == {t.work.key for t in sheet.order if sheet.pickable(t.work)}, w.report()
        changed = [t for t in sheet.order if sheet.pickable(t.work)]
        assert changed and all(w.painted_in(t) > 0 for t in changed), w.report()
        assert w.paints_outside(sheet) == [], w.report()
    finally:
        sheet.clear_picks()
        wc.rest(50)
