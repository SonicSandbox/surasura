"""Work counts on the secondary windows (the report window, the Anki window, the frequency lists, the confirmation card, the toast) (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a window that repaints whole on each keystroke or tick.

Each test opens its window with its neighbour's own fixtures (imported at the top: one `main` for the main window's tests; the frequency lists' as `lists_main`).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from app.qt import shadow, toast
from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_anki_window import _choose, _gates_closed, _open, anki   # noqa: F401  (the Anki window's)
from tests.qt.test_confirm import _ask, _gone, second   # noqa: F401  (the confirmation card's)
from tests.qt.test_frequency_lists_window import _open as _open_lists, ja_list   # noqa: F401  (the lists window's)
from tests.qt.test_frequency_lists_window import main as lists_main   # noqa: F401  (its own window, by its own name)
from tests.qt.test_report_window import _press, main   # noqa: F401  (the window: the same one the Anki and confirm
#                                                         tests open; one `main` here, so no import shadows another)
from tests.qt.test_toast import JA, _up, clock, stage   # noqa: F401  (the toast's own fixtures)


def test_leaving_the_pictures_out_hides_them_making_no_widget(main):
    """The tick on *Leave the pictures out* hides the report form's thumbnails: the window makes no widget (the
    thumbnails the press made are kept and only hidden, never made again)."""
    w = _press(main)
    wc.rest()                                  # the window's own deferred build (its other pages) lands before the count
    thumbs = list(w._thumbs)
    assert thumbs and not any(t.isHidden() for t in thumbs)
    try:
        with wc.measure(w) as m:
            w.leave_out.click()
        assert all(t.isHidden() for t in thumbs), m.report()
        assert m.created == 0, m.report()
    finally:
        w.leave_out.setChecked(False)


def test_a_switch_toggled_in_the_anki_window_repaints_only_its_own_row(main, anki):
    """A switch in the Anki window pressed (auto-sync): its own row alone repaints, nothing above or below it and
    nothing outside the window's page, no widget made. Layout hints are bounded by one forced pass times PASS_SLACK
    (the R1-style bound), not required to be zero."""
    _choose(main)
    w = _open(main)
    chk = w.chk_auto
    try:
        with wc.measure(w) as m:
            QTest.mouseClick(chk, Qt.MouseButton.LeftButton)
            wc.rest(150)
        rect = wc.rect_in_window(chk)
        assert m.painted > 0, m.report()                                 # (the switch did show its new value)
        assert m.paints_outside(chk) == [], m.report()
        assert m.union <= rect.width() * rect.height(), m.report()
        assert m.hints <= wc.one_pass(chk.parentWidget(), w) * wc.PASS_SLACK, m.report()
        assert m.created == 0, m.report()
    finally:
        QTest.mouseClick(chk, Qt.MouseButton.LeftButton)                 # put back, unmeasured
        wc.rest(150)


def test_an_undo_pressed_on_a_toast_repaints_the_toast_and_the_thing_it_undoes_alone(clock, stage):
    """An Undo pressed on a toast: the toast's card (with the shadow's reach, `shadow.margins('toast')`) and the one
    row the Undo puts back repaint, nothing else in the window; the put-back row is painted and the toast closes."""
    host = toast.ToastHost(stage)
    row = QLabel("未読", stage)
    row.setGeometry(20, 20, 220, 40)
    row.show()
    host.show(JA, undo=lambda: row.setText("既読"))
    _up(host, clock)
    QApplication.processEvents()
    left, top, right, bottom = shadow.margins("toast")
    card = wc.rect_in_window(host.card).adjusted(-left, -top, right, bottom)
    undone = wc.rect_in_window(row)
    b = host.card.buttons[0]
    with wc.measure(stage) as w:
        b.click()
        QApplication.processEvents()
    assert not host.card.isVisible() and not host.alive, w.report()
    assert row.text() == "既読", w.report()
    assert w.union_in(undone) > 0, w.report()
    assert w.union_in(card) > 0, w.report()
    assert w.paints_outside_rect(card, undone) == [], w.report()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="WC found-B B7: each confirmation makes its card and its scrim again")
def test_confirm_asked_again_after_no_is_built_once_and_no_widget_is_made(second):
    """The confirmation card asked in a window, answered No (Esc), and asked again in that window: the second open
    reuses the card that was built, making no widget."""
    card, answers = _ask(second)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    if not (answers == [False] and _gone(card)):                  # setup: never the xfail's AssertionError
        pytest.fail(f"Esc didn't answer No and close the card: {answers}")
    with wc.measure(second) as w:
        card2, answers2 = _ask(second)
    try:
        assert w.created == 0, w.report()
    finally:
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)     # put back, unmeasured
        wc.settle()


def test_typing_in_what_happened_repaints_only_the_box_and_the_buttons_that_change(main):
    """Typing in the report's *What happened* box: the first letter into an empty box repaints the box and the
    Save and Send buttons it enables, nothing else of the form; the next letter changes no button, so only the box
    repaints."""
    w = _press(main)
    assert QTest.qWaitForWindowExposed(w)
    wc.settle()
    w.what.setPlainText("")
    w.what.setFocus()
    wc.settle()
    assert not w.save_button.isEnabled()
    try:
        with wc.measure(w) as m:
            QTest.keyClicks(w.what, "x")
            wc.settle()
        assert w.what.toPlainText() == "x", w.what.toPlainText()
        assert w.save_button.isEnabled(), m.report()
        assert m.painted > 0, m.report()
        assert m.painted_in(w.save_button) > 0, m.report()           # (the part that changed did repaint)
        assert w.send_button.isEnabled(), m.report()
        # where: every px painted lies on the box or the two buttons (by area, not bounding rects: the form's ground
        # repaints the region under them, whose bounding rect spans the form)
        parts = [wc.rect_in_window(b) for b in (w.what, w.save_button, w.send_button)]
        assert m.union <= sum(m.union_in(r) for r in parts), m.report()
        with wc.measure(w) as m2:
            QTest.keyClicks(w.what, "y")
            wc.settle()
        assert w.what.toPlainText() == "xy", w.what.toPlainText()
        assert m2.painted > 0, m2.report()
        box = wc.rect_in_window(w.what)
        assert m2.union_in(box) > 0, m2.report()                            # the box did show the letter
        assert m2.union <= m2.union_in(box), m2.report()                    # every px painted lies on the box
    finally:
        w.what.setPlainText("")                                       # put back, unmeasured
        wc.settle()


def test_a_list_row_selected_in_the_frequency_lists_window_repaints_that_row_and_the_remove_button_alone(lists_main, ja_list):
    """A list row clicked in the frequency lists window: the row itself repaints, and with it the Remove button that
    turns on, nothing else in the window, no widget made."""
    from app import frequency_lists
    frequency_lists.add(ja_list, "ja")
    w = _open_lists(lists_main)
    wc.settle()                                                          # the window's own first-show paints land before the count
    assert w.list.count() > 0
    item = w.list.item(0)
    viewport = w.list.viewport()
    row = viewport.rect().intersected(w.list.visualItemRect(item)).translated(wc.rect_in_window(viewport).topLeft())
    button = wc.rect_in_window(w.remove_button)
    try:
        with wc.measure(w) as m:
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=w.list.visualItemRect(item).center())
        assert w.remove_button.isEnabled(), m.report()
        assert m.union_in(row) > 0, m.report()                           # (the selected row did show it)
        assert m.union_in(button) > 0, m.report()                        # (the Remove button did turn on)
        assert m.paints_outside_rect(row, button) == [], m.report()
        assert m.created == 0, m.report()
    finally:
        w.list.clearSelection()                                          # put back, unmeasured
        wc.rest(150)
