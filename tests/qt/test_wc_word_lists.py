"""Work counts on the word lists window (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a filter or a removal that lays the whole list out again.

The screen: test_word_lists_window's `main` fixture (the window a test opens).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_word_lists_window import _fresh_session, _open, _put, _rows, calls, main   # noqa: F401


BLACKLIST = ["毎日", "勉強", "友達", "学校", "電話", "旅行"]


def test_the_blacklist_button_shows_its_words_in_one_layout_pass(main):
    """Ignore list → Blacklist button: one click lays the word lists window out at most once, and no row is laid out
    again for each row the blacklist shows. A click on the list already shown changes nothing, so it asks for no
    layout at all."""
    _put("冒険\n", "ignore")
    _put("# ja Blacklist\n" + "".join(f"{word}\n" for word in BLACKLIST), "blacklist")
    win = _open(main)
    assert win.kind == "ignore"
    unit = wc.one_pass(win, main)
    with wc.measure(main) as w:                       # the list already shown: a press that changes nothing
        win.kind_buttons["ignore"].click()
    assert sum(w.layout_requests.values()) == 0, w.report()
    with wc.measure(main) as w:
        win.kind_buttons["blacklist"].click()
        assert wait_until(lambda: sorted(_rows(win)) == sorted(BLACKLIST), 3)
        wc.rest(150)
    assert w.hints <= unit * wc.PASS_SLACK, w.report()
    assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()


# --- R1: one press, one layout pass at most ---------------------------------------------------------------------- #
def test_enter_adding_typed_words_grows_the_list_and_lays_it_out_once(main):
    """Enter in the add field with two new words typed: the list grows by them, in order, and the press asks at most
    one layout pass of the window (the list is not laid out again row by row)."""
    _put("冒険\n")
    win = _open(main)
    assert wait_until(lambda: _rows(win) == ["冒険"], 3)
    win.add_field.setText("毎日 ストレート")
    wc.rest(150)
    unit = wc.one_pass(win, win)
    with wc.measure(win) as w:
        QTest.keyClick(win.add_field, Qt.Key.Key_Return)
        landed = wait_until(lambda: _rows(win) == ["冒険", "毎日", "ストレート"], 3)
        wc.rest(150)
    assert landed, w.report()
    assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
    assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()
    # The press lays out this window and nothing else: no other top-level window's layouts are invalidated (a press
    # that invalidates every layout of the app asks its whole page again, whatever this window's own count says).
    elsewhere = [type(x).__name__ for x in w._layout_widgets.values() if x.window() is not win]
    assert not elsewhere, (elsewhere, w.report())


def test_a_keystroke_in_the_search_filters_the_list_and_lays_it_out_once(main):
    """A keystroke in the search: the list shows the matching words, and the press asks at most one layout pass of the
    window (the filter does not invalidate every layout), moving no widget more than a pass would, and laying no widget
    out more than once."""
    _put("冒険\n冒険家\n毎日\n勉強\n")
    win = _open(main)
    assert wait_until(lambda: _rows(win) == ["冒険", "冒険家", "毎日", "勉強"], 3)
    wc.settle()
    wc.rest(150)
    unit = wc.one_pass(win, main)
    try:
        win.search.setFocus()
        wc.settle()
        with wc.measure(main) as w:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(win.search, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, "冒"))
            landed = wait_until(lambda: _rows(win) == ["冒険", "冒険家"], 3)
            wc.rest(150)
        assert landed, w.report()
        assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
        assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()
        assert w.most_layouts()[0] <= 1, w.report()
    finally:
        win.search.clear()
