"""Work counts on Finished (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a Finished page that repaints whole on a put back or a scroll.

The screen: test_finished's `fin` fixture (one window a test: it needs its estimator and Finished shown).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_finished import FakeEstimator, calls, click, fin, finished_rows, lst_of, part   # noqa: F401
from tests.qt.test_drag import _stones_sheet   # noqa: F401  (autouse: the stones drawn before the window opens)


def test_finished_wheel_notch_paints_only_the_strip_that_came_into_view(fin):
    """A wheel notch on the Finished list: Qt moves what is drawn and the list paints only the strip that came into
    view (plus the scroll bar), and no widget is made or view built. What a wrong answer would cost a learner: every
    notch repainting the whole Finished page while scrolling back through what was finished."""
    seed, win, writer, estimator = fin()
    win.resize(win.width(), 300)          # the seed's ~7 finished rows fit a tall window: a short one lets the list scroll
    wc.rest(200)
    lst = lst_of(win)
    vp = lst.viewport()
    bar = lst.verticalScrollBar()
    assert bar.maximum() > 0
    view = wc.rect_in_window(vp)
    toast = wc.rect_in_window(win.toasts.card).adjusted(-48, -48, 48, 48)
    bottom = QRect(0, wc.rect_in_window(win.dock).top() - 24, win.width(), win.height())
    progress = win.findChild(QWidget, "progress")
    allowed = [toast, bottom] + ([wc.rect_in_window(progress)] if progress is not None else [])
    for _ in range(3):
        v0 = bar.value()
        with wc.measure(win) as w:
            pos = QPointF(vp.width() / 2, vp.height() / 2)
            QApplication.sendEvent(vp, QWheelEvent(pos, QPointF(vp.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                                   QPoint(0, -120), Qt.MouseButton.NoButton,
                                                   Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                                                   False))
        moved = wc.exposed(v0, bar.value())
        assert moved > 0
        assert w.union_in(view) <= (moved + wc.STRIP_SLACK_PX) * vp.width(), (moved, w.report())
        assert w.paints_outside_rect(wc.rect_in_window(lst), *allowed) == [], w.report()
        assert w.created == 0 and w.builds == 0, w.report()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="WC found-B B3: a Finished row's ⋯ menu is made at each open (L1 N7: deleted on close)")
def test_the_more_menu_opened_again_is_built_once_and_makes_no_widget(fin):
    """Press: a Finished row's ⋯ opened, closed, opened again. The rule: an overlay opened again is built once, so the
    second open makes no widget."""
    _seed, win, _w, _e = fin()
    lst = lst_of(win)
    i, _row = finished_rows(win)[0]
    click(lst, part(lst, i, "more")[1].center())
    win.finished.last_menu.close()
    wc.rest(150)
    with wc.measure(win) as w:
        click(lst, part(lst, i, "more")[1].center())
    try:
        assert w.created == 0, w.report()
    finally:
        win.finished.last_menu.close()
