"""The one in-window confirmation (W3.4 row 1; `app/qt/confirm.py`; the RUNBOOK's *Safety confirmations*, IK-10).

What a wrong answer would cost: a list, a known-words file or Anki's order replaced or removed by a key press the user
meant as "no" (Esc, Back, Enter on a remove, ✕, a click beside the box); a click landing on the window behind the box
(a second Remove under the dimmed room); an answer arriving after its window closed (a write for a window that's gone);
a modal loop that freezes the main window.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from app.qt import confirm, shell, strings
from app.qt.windows import SecondaryWindow
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1100, 700)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def second(main):
    w = SecondaryWindow(main, "Frequency lists")
    behind = QPushButton("Remove…", w)
    behind.setToolTip("behind the box")
    w.clicks = []
    behind.clicked.connect(lambda: w.clicks.append("behind"))
    w.behind = behind
    field = QLineEdit(w)
    w.field = field
    w.body.addWidget(behind)
    w.body.addWidget(field)
    w.body.addStretch(1)                                  # the two at the top, clear of the box in the middle
    w.resize(640, 420)
    w.show()
    QApplication.processEvents()
    return w


def _ask(window, default_no=True, **kw):
    answers = []
    card = confirm.ask(window, "Remove 2 frequency lists?", "They move to the trash folder, never deleted.",
                       "Remove", "Move the lists to the trash folder", default_no=default_no,
                       on_answer=answers.append, **kw)
    QApplication.processEvents()
    return card, answers


def _gone(card):
    try:
        return not card.isVisible()
    except RuntimeError:                                  # deleted: gone
        return True


def _click_window_at(window, widget, point=None):
    """A real click through the window (hit-tested as a mouse would be), at `widget`'s centre or `point`."""
    pos = point if point is not None else widget.mapTo(window, widget.rect().center())
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QApplication.processEvents()


# --- every way of saying no is No -------------------------------------------------------------------------------- #
def test_esc_is_no_and_leaves_the_window_open(second):
    card, answers = _ask(second)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert answers == [False] and _gone(card)
    assert second.isVisible()                             # Esc closed the box, not the window under it
    assert not any(w.isVisible() for w in second.findChildren(confirm.Scrim))


def test_the_mouse_back_button_is_no(second):
    card, answers = _ask(second)
    QTest.mouseClick(card.body, Qt.MouseButton.BackButton)
    assert answers == [False] and _gone(card) and second.isVisible()


def test_a_click_outside_the_box_is_no_and_reaches_nothing_behind(second):
    card, answers = _ask(second)
    pos = second.behind.mapTo(second, second.behind.rect().center())
    assert not card.geometry().contains(pos)              # beside the box, under the dimmed room
    _click_window_at(second, second.behind)
    assert answers == [False] and _gone(card)
    assert second.clicks == []
    _click_window_at(second, second.behind)               # the witness: with no box, that click reaches it
    assert second.clicks == ["behind"]


def test_a_click_inside_the_box_off_its_buttons_answers_nothing(second):
    card, answers = _ask(second)
    _click_window_at(second, card.title)
    assert answers == [] and card.isVisible()
    card.no.click()
    assert answers == [False]


def test_closing_the_window_with_a_question_open_answers_nothing(second):
    # ✕ is No, and a callback never fires once its window closed: nothing happens at all.
    card, answers = _ask(second)
    second.close()
    QApplication.processEvents()
    assert answers == []


def test_a_question_dropped_with_its_window_never_answers_later(second):
    card, answers = _ask(second)
    second.hide()                                         # hidden (not through ✕): an answer now would be too late
    card.yes.click()
    assert answers == []


# --- Enter and the default button ------------------------------------------------------------------------------- #
def test_enter_is_cancel_on_a_remove(second):
    card, answers = _ask(second, default_no=True)
    assert QApplication.focusWidget() is card.no
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    assert answers == [False] and _gone(card)


def test_enter_is_the_action_on_a_write_the_preview_already_showed(second):
    card, answers = _ask(second, default_no=False)
    assert QApplication.focusWidget() is card.yes
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Enter)
    assert answers == [True]


def test_tab_goes_round_the_two_buttons_and_enter_presses_the_one_in_focus(second):
    card, answers = _ask(second, default_no=True)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is card.yes
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is card.no        # never out to the field behind the dimmed room
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Backtab)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    assert answers == [True]


def test_the_keyboard_cant_reach_the_window_behind(second):
    card, answers = _ask(second)
    second.field.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is card.no
    QTest.keyClicks(QApplication.focusWidget(), "x")
    assert second.field.text() == "" and answers == []


# --- what it shows, and how it is shown ------------------------------------------------------------------------- #
def test_the_box_names_the_action_and_its_numbers_and_every_button_is_wired_and_tipped(second):
    card, _answers = _ask(second, danger=True)
    assert card.title.text() == "Remove 2 frequency lists?"
    assert card.yes.text() == "Remove" and card.yes.property("kind") == "danger"
    assert card.no.text() == strings.CONFIRM_NO
    found, walked = problems(second)
    assert walked >= 3 and found == []


def test_it_is_never_modal_and_ask_returns_at_once(second, main):
    card, answers = _ask(second)
    assert QApplication.activeModalWidget() is None
    assert answers == []                                  # nothing waited for an answer
    assert main.isEnabled() and second.isEnabled()


def test_the_box_is_centred_in_the_window_that_asked_over_a_dimmed_room(second):
    card, _answers = _ask(second)
    scrim = card.scrim
    assert scrim.geometry() == second.rect() and scrim.isVisible()
    assert abs(card.geometry().center().x() - second.rect().center().x()) <= 1
    second.resize(800, 500)
    QApplication.processEvents()
    assert scrim.geometry() == second.rect()
    assert abs(card.geometry().center().x() - second.rect().center().x()) <= 1


def test_it_works_in_the_main_window_too(main):
    card, answers = _ask(main)
    assert card.isVisible() and card.window() is main
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert answers == [False] and main.isVisible()


def test_answered_once_whatever_comes_after(second):
    card, answers = _ask(second)
    card.yes.click()
    try:
        card.no.click()
        card.close()
    except RuntimeError:
        pass
    QApplication.processEvents()
    assert answers == [True]


def test_focus_goes_back_where_it_was(second):
    second.field.setFocus()
    QApplication.processEvents()
    card, answers = _ask(second)
    card.no.click()
    assert wait_until(lambda: QApplication.focusWidget() is second.field)
