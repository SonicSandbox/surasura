"""Work counts on the sort screen (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: each choice laying the screen out again and again while he sorts a library.

The screen: test_sort_screen's `world` fixture and `open_sort` (one window a test).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_sort_screen import keys_shown, open_sort, press, world, KEY_OF   # noqa: F401
from tests.qt.test_drag import _stones_sheet   # noqa: F401  (autouse: the stones drawn before the window opens)


def _layout_asks_of_one_pass(screen, win):
    """The LayoutRequest events one forced pass of the screen's own layouts asks: the unit the press's asks are compared
    with (a press that invalidates every layout in the app asks far more than the screen's own pass)."""
    layouts = [screen.layout()] if screen.layout() is not None else []
    layouts += [l for l in screen.findChildren(wc.QLayout) if l not in layouts]
    with wc.measure(win) as u:
        for layout in layouts:
            layout.invalidate()
        if layouts:
            layouts[0].activate()
    return sum(u.layout_requests.values())


# --- R1: a choice by its key lays the sort screen out once -------------------------------------------------------- #
def test_a_choice_by_its_key_soon_lays_the_sort_screen_out_once_and_the_next_title_comes_up(world):
    """Soon (the S key) on the sort screen: the top title leaves the screen and the next one comes up; the screen is
    laid out at most one pass as the press ends (never once per row or per shown title)."""
    _seed, win, _writer = world()
    screen = open_sort(win)
    top = screen.visible_rows()[0][1]
    second = screen.visible_rows()[1][1].key
    unit = wc.one_pass(screen, win)
    unit_asks = _layout_asks_of_one_pass(screen, win)
    b0 = win.services.library.builds
    with wc.measure(win, readers=[win.services.library]) as w:
        press(screen, Qt.Key.Key_S)
        landed = wait_until(lambda: win.services.library.builds > b0 and win.moves.tickets == [], 3)
        wc.rest(150)
    assert landed and w.builds == 1, w.report()                          # the choice's work landed inside the count
    assert top.key not in keys_shown(screen), w.report()
    assert keys_shown(screen)[0] == second, w.report()
    assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()
    assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
    assert sum(w.layout_requests.values()) <= max(unit_asks, 1) * wc.PASS_SLACK, (unit_asks, w.report())


def test_a_choice_now_lays_the_screen_out_once_and_the_next_title_comes_up_in_one_pass(world):
    """Now (the right arrow) on the sort screen: the top title is placed through New arrivals and the next one comes up
    on top; the press lays the screen out as one pass does (no row moved twice; its at-once feedback and the view's
    landing may come a turn apart), the view is built once, and nothing the screen covers is painted — the placement
    lays Current's list out again under it, and the screen's ground is opaque (found-B B4: Current's list and the
    whole screen over it were painted at every choice; 89 paints, 6.2 × the window. Its 78 hints also held the
    screen's own opening, measured straight after it opened)."""
    _seed, win, writer = world()
    screen = open_sort(win)
    unit = wc.one_pass(screen, win)                              # (the opening laid out and painted: unmeasured)
    wc.rest(150)
    b0 = win.services.library.builds
    with wc.measure(win, readers=[win.services.library]) as w:
        press(screen, KEY_OF["now"])
        landed = wait_until(lambda: win.services.library.builds > b0 and win.moves.tickets == [], 3)
        wc.rest(150)
    if not (landed and w.painted and w.builds == 1):             # setup, not the rule: never an AssertionError here
        pytest.fail(f"the choice's work didn't land once inside the count: {w.report()}")
    assert w.painted_in(win.page_widgets["current"]) == 0, w.report()
    assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
    assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()


def test_put_the_rest_in_menu_opened_again_makes_no_widget(world):
    """*Put the rest in…* opened, closed and opened again: the second open makes no widget (R5)."""
    _seed, win, _writer = world()
    screen = open_sort(win)
    QTest.mouseClick(screen.btn_rest, Qt.MouseButton.LeftButton)
    screen.last_menu.close()
    wc.rest(150)
    try:
        with wc.measure(win, readers=[win.services.library]) as w:
            QTest.mouseClick(screen.btn_rest, Qt.MouseButton.LeftButton)
            wc.rest(150)
    finally:
        try:
            screen.last_menu.close()
        except RuntimeError:
            pass
    assert w.created == 0, w.report()
