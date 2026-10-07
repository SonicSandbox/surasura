"""Toasts (M2.1 row 5; the window's spec 05 §5.4, A4 *Motion*, A2's toast list).

What a wrong answer would cost:
  * an Undo that runs twice, or a toast that never goes;
  * a toast that rises again each time its message changes (the mock's STEADY rule), or covers the buckets during a
    drag (05 §5.4: hidden while dragging);
  * a toast that takes the keyboard from the field the user is typing in;
  * a toast that keeps the animation clock awake for its 6.5 s;
  * a long title spilling past the window (it is elided, the whole message in its tooltip).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget

from app import theme
from app.qt import freeze, motion, strings, toast

JA = "進撃の巨人 → Soon · #26、最初の25ファイルの後"
ZH = "鬼灭之刃 第三季 已移到目标 · 它的卡片保持原位"


@pytest.fixture
def clock(qapp):
    c = motion.clock()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    before = c.mode.setting
    c.mode.set_setting("full")
    yield c
    for a in c.active:
        a.stop()
    c.use_real_time()
    c.mode.set_setting(before)
    freeze.set_frozen(None)


@pytest.fixture
def stage(qapp):
    w = QWidget()
    w.resize(1000, 640)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


def _up(host, clock):
    clock.advance(theme.MOTION["toast-rise"])
    QApplication.processEvents()


def test_a_toast_rises_into_place_48_px_above_the_bottom_and_shows_its_message_whole(clock, stage):
    host = toast.ToastHost(stage)
    host.show(JA)
    opening = motion.opening_of(host.card)
    assert opening is not None and opening.ghost.offset.y() == theme.MOTION["toast-rise-px"]   # from 12 px below
    _up(host, clock)
    card = host.card
    assert card.isVisible() and card.text.text() == JA
    assert stage.height() - card.geometry().bottom() - 1 == theme.MOTION["toast-bottom"]
    assert abs(card.geometry().center().x() - stage.width() // 2) <= 1
    stage.resize(1200, 700)
    QApplication.processEvents()
    assert stage.height() - card.geometry().bottom() - 1 == theme.MOTION["toast-bottom"]   # stays put on resize


def test_a_long_message_is_elided_within_92_percent_and_kept_whole_in_its_tooltip(clock, stage):
    host = toast.ToastHost(stage)
    long_zh = ZH * 8
    host.show(long_zh)
    _up(host, clock)
    card = host.card
    assert card.width() <= int(stage.width() * toast.WIDTH_SHARE)
    assert card.text.text() != long_zh and card.text.text().endswith("…")
    assert card.text.toolTip() == long_zh and card.accessibleName() == long_zh


def test_undo_calls_back_once_and_closes(clock, stage):
    host = toast.ToastHost(stage)
    undone = []
    host.show(JA, undo=lambda: undone.append(1))
    _up(host, clock)
    b = host.card.buttons[0]
    assert b.isVisible() and b.text() == strings.TOAST_UNDO and b.toolTip()
    b.click()
    assert undone == [1] and not host.card.isVisible() and not host.alive
    b.click()                                              # hidden: a second click can't reach it
    assert undone == [1] or not b.isVisible()


def test_extra_buttons_run_and_close_and_every_button_has_a_tooltip(clock, stage):
    host = toast.ToastHost(stage)
    ran = []
    host.show("X finished · its cards stay put", undo=lambda: ran.append("undo"),
              buttons=[("Mine it too", "Make its cards now", lambda: ran.append("mine")),
                       ("Remove unstudied cards", "Suspend and tag them", lambda: ran.append("remove"))])
    _up(host, clock)
    shown = [b for b in host.card.buttons if b.isVisible()]
    assert [b.text() for b in shown] == ["Undo", "Mine it too", "Remove unstudied cards"]
    assert all(b.toolTip() for b in shown)
    shown[1].click()
    assert ran == ["mine"] and not host.card.isVisible()


def test_its_time_is_6_5_s_or_12_s_on_a_timer_of_its_own_and_ends_it(clock, stage):
    host = toast.ToastHost(stage)
    host.show(JA)
    assert host.life.isActive() and host.life.interval() == 6500
    host.show(JA, long=True)                               # the Anki offer
    assert host.life.interval() == 12000
    _up(host, clock)
    clock.use_real_time()
    assert not clock.running                               # resting: the toast wakes no clock
    host.life.timeout.emit()
    assert not host.card.isVisible() and not host.alive


def test_a_new_toast_replaces_the_shown_one_without_rising_again(clock, stage):
    host = toast.ToastHost(stage)
    host.show(JA)
    _up(host, clock)
    host.show(ZH)
    assert motion.opening_of(host.card) is None            # no second rise (the mock's STEADY)
    assert host.card.isVisible() and host.card.message == ZH


def test_hidden_while_dragging_its_time_still_running_and_back_unanimated(clock, stage):
    host = toast.ToastHost(stage)
    host.show(JA)
    _up(host, clock)
    host.set_dragging(True)
    assert not host.card.isVisible() and host.life.isActive()
    assert host.shadow.isHidden()                          # nothing of it over the buckets
    host.set_dragging(False)
    assert host.card.isVisible() and motion.opening_of(host.card) is None
    # a drag that outlives the toast: it stays closed after the drop
    host.set_dragging(True)
    host.life.timeout.emit()
    host.set_dragging(False)
    assert not host.card.isVisible()


def test_a_toast_shown_during_a_drag_waits_for_the_drop(clock, stage):
    host = toast.ToastHost(stage)
    host.set_dragging(True)
    host.show(JA)
    assert not host.card.isVisible() and motion.opening_of(host.card) is None
    host.set_dragging(False)
    assert host.card.isVisible()


def test_a_toast_never_takes_the_keyboard(clock, stage):
    field = QLineEdit(stage)
    field.setGeometry(10, 10, 200, 30)
    field.show()
    stage.activateWindow()
    field.setFocus()
    QApplication.processEvents()
    before = QApplication.focusWidget()
    host = toast.ToastHost(stage)
    host.show(JA, undo=lambda: None)
    _up(host, clock)
    assert QApplication.focusWidget() is before
    assert host.card.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_its_fill_and_border_are_the_tokens(clock, stage):
    freeze.set_frozen(True)
    host = toast.ToastHost(stage)
    host.show("短い")
    img = host.card.grab().toImage()
    fill = img.pixelColor(img.width() - 6, img.height() // 2)
    want = theme.parse(theme.FIXED["toast"])
    assert abs(fill.red() - want[0]) <= 3 and abs(fill.green() - want[1]) <= 3 and abs(fill.blue() - want[2]) <= 3
    edge = img.pixelColor(img.width() // 2, 0)
    line = theme.parse(theme.colours("hb")["line-hi"])
    assert abs(edge.red() - line[0]) <= 12 and abs(edge.green() - line[1]) <= 12
