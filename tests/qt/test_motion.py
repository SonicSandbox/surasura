"""The motion (M2.1 rows 1–3 and 6; the window's spec 05 §5.3–5.5, §5.10, §5.11, A4 *Motion*).

What a wrong answer would cost:
  * a curve that isn't the mock's (every slide and rise feels off: the mock is "VERY close", G1.6);
  * a clock that keeps waking with nothing moving (a laptop's battery, and a step taken 60 times a second for nothing);
  * an overlay that animates again on every refresh (the search results flashed on every keystroke: R4b-5);
  * a close during an opening that the overlay ignores (it pops back after Esc), or a press during it lost to the list
    beneath;
  * reduced motion that still slides (Sonic's G1.2-3: Reduced = no slides, short fades kept);
  * a spinner that keeps the clock running on a hidden page or a minimised window (G1.5-2: it stops when hidden).

Every test drives the clock's own test time: none waits on real time for a motion.
"""
import ctypes
import os
import re

import pytest

pytest.importorskip("PyQt6")
from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, Qt
from PyQt6.QtGui import QExposeEvent, QRegion
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app import theme
from app.qt import freeze, motion, shell

JA = "今日は新しいエピソードを見た"


@pytest.fixture
def clock(qapp):
    """The clock on test time, motion unfrozen and Full; put back afterwards."""
    c = motion.clock()
    for a in c.active:
        a.stop()
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
    """A shown parent window to hold overlays (offscreen)."""
    w = QWidget()
    w.resize(900, 640)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()
    w.deleteLater()


def css_cubic_bezier(x1, y1, x2, y2, x):
    """CSS's cubic-bezier: the y at which the curve's x is `x` (solved by bisection, to 1e-7)."""
    def bez(t, a, b):
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if bez(mid, x1, x2) < x:
            lo = mid
        else:
            hi = mid
    return bez((lo + hi) / 2, y1, y2)


# --- row 1: the curve and the clock ---------------------------------------------------------------------------------- #
def test_the_curve_is_the_mocks_cubic_bezier_to_within_two_thousandths():
    assert theme.EASE == (0.2, 0.7, 0.3, 1.0)
    for i in range(101):
        t = i / 100
        assert abs(motion.ease(t) - css_cubic_bezier(*theme.EASE, t)) < 0.002, t
    assert motion.ease(0.0) == pytest.approx(0.0, abs=1e-9) and motion.ease(1.0) == pytest.approx(1.0, abs=1e-9)
    # the pulse's ease-in-out is CSS's keyword too
    for i in range(0, 101, 10):
        assert abs(motion.ease(i / 100, theme.EASE_IN_OUT) - css_cubic_bezier(*theme.EASE_IN_OUT, i / 100)) < 0.002


def test_durations_come_from_the_tokens():
    assert motion.duration("fast") == 120 and motion.duration("slow") == 260
    assert motion.duration("toast-rise") == 260 and motion.duration("overlay-pop") == theme.MOTION["overlay-pop"]


def test_the_clock_runs_only_while_something_moves(clock):
    clock.use_real_time()
    assert not clock.running
    a = clock.animate(120, lambda v: None)
    assert clock.running                          # one thing moving: the timer runs
    a.stop()
    assert not clock.running                      # nothing moving: no wake-ups
    b = clock.animate(120, lambda v: None)
    b.finish()
    assert not clock.running


def test_two_animations_started_together_read_the_same_frame_time(clock):
    seen_a, seen_b = [], []
    clock.animate(190, seen_a.append)
    clock.animate(190, seen_b.append)
    clock.advance(190)
    assert seen_a == seen_b and len(seen_a) >= 10


def test_an_animation_ends_on_its_last_value_then_once_done(clock):
    values, done = [], []
    clock.animate(120, values.append, lambda: done.append(1))
    clock.advance(119)
    assert not done and 0.9 < values[-1] < 1.0
    clock.advance(1)
    assert values[-1] == 1.0 and done == [1]
    assert values == sorted(values)               # the curve only rises
    clock.advance(100)
    assert done == [1] and values.count(1.0) == 1


def test_an_owner_hidden_midway_ends_its_animation_without_a_last_call(clock, stage):
    owner = QWidget(stage)
    owner.show()
    values, done = [], []
    clock.animate(260, values.append, lambda: done.append(1), owner=owner)
    clock.advance(64)
    n = len(values)
    owner.hide()
    clock.advance(300)
    assert len(values) == n and not done and not clock.active


def test_an_owner_deleted_midway_ends_it(clock, stage):
    owner = QWidget(stage)
    owner.show()
    values = []
    clock.animate(260, values.append, owner=owner)
    clock.advance(32)
    sip.delete(owner)
    clock.advance(300)
    assert not clock.active and values[-1] < 1.0


def test_frozen_every_animation_is_at_its_end_at_once_and_no_timer_starts(qapp):
    c = motion.clock()
    freeze.set_frozen(True)
    try:
        c.use_real_time()
        values, done = [], []
        c.animate(260, values.append, lambda: done.append(1))
        assert values == [1.0] and done == [1] and not c.running and not c.active
    finally:
        freeze.set_frozen(None)


def test_a_broken_animation_stops_reports_and_leaves_the_others_moving(clock, qt_errors):
    good = []

    def bad(_v):
        raise ValueError("a painter's bug")
    clock.animate(120, bad)
    clock.animate(120, good.append)
    clock.advance(120)
    assert good[-1] == 1.0
    assert qt_errors and qt_errors[0][0] is ValueError
    qt_errors.clear()


def test_a_loop_turns_through_its_phase_until_stopped(clock):
    phases = []
    a = clock.animate(1200, phases.append, kind="loop", repeat=True, points="linear")
    clock.advance(1800)
    assert any(p > 0.9 for p in phases) and phases[-1] == pytest.approx(0.5, abs=0.02)
    a.stop()
    assert not clock.active


def test_no_other_animation_engine_and_no_motion_literals_under_app_qt():
    # One clock (row 1): Qt's own animation classes and graphics effects stay out of the window (05 §5.3).
    folder = os.path.join(os.path.dirname(motion.__file__))
    banned = re.compile(r"QPropertyAnimation|QVariantAnimation|QTimeLine|QGraphics\w*Effect|setGraphicsEffect")
    literal = re.compile(r"animate\(\s*\d")
    for name in os.listdir(folder):
        if name.endswith(".py"):
            text = open(os.path.join(folder, name), encoding="utf-8").read()
            code = re.sub(r'"""[\s\S]*?"""', "", text)           # docstrings may name what's banned
            code = re.sub(r"#.*", "", code)
            assert not banned.search(code), name
            assert not literal.search(code), name


# --- row 2: reduced motion ------------------------------------------------------------------------------------------ #
def test_follow_reads_windows_and_full_or_reduced_ignore_it(qapp):
    windows = {"on": False}
    mode = motion.Mode(reader=lambda: windows["on"])
    assert mode.setting == "follow" and mode.reduced            # Windows' animations off -> reduced
    windows["on"] = True
    mode.system_changed()
    assert not mode.reduced
    mode.set_setting("reduced")
    assert mode.reduced
    mode.set_setting("full")
    windows["on"] = False
    mode.system_changed()
    assert not mode.reduced
    mode.set_setting("sideways")                                 # unknown: follow
    assert mode.setting == "follow" and mode.reduced


def test_reduced_jumps_a_move_and_keeps_a_fade_at_most_fast(clock):
    clock.mode.set_setting("reduced")
    moved, done = [], []
    clock.animate(260, moved.append, lambda: done.append("move"))
    assert moved == [1.0] and done == ["move"]                   # no slide: at its place at once
    faded = []
    clock.animate(260, faded.append, lambda: done.append("fade"), kind="fade")
    clock.advance(theme.FAST - 1)
    assert "fade" not in done
    clock.advance(1)
    assert done[-1] == "fade" and faded[-1] == 1.0


@pytest.mark.skipif(os.name != "nt", reason="Windows' message")
def test_a_settingchange_for_animations_rereads_and_another_doesnt(qapp):
    from ctypes import wintypes
    reads = []
    mode = motion.Mode(reader=lambda: reads.append(1) or True)
    f = motion.SettingChangeFilter(mode)
    msg = wintypes.MSG()
    msg.message = motion.WM_SETTINGCHANGE
    msg.wParam = 0x0057                                          # SPI_SETWORKAREA: not ours
    f.nativeEventFilter(QByteArray(b"windows_generic_MSG"), sip.voidptr(ctypes.addressof(msg)))
    QApplication.processEvents()
    assert len(reads) == 1 and f.heard == 0
    msg.wParam = motion.SPI_SETCLIENTAREAANIMATION
    handled = f.nativeEventFilter(QByteArray(b"windows_generic_MSG"), sip.voidptr(ctypes.addressof(msg)))
    assert handled == (False, 0)                                 # never swallows Windows' message
    QApplication.processEvents()
    assert len(reads) == 2 and f.heard == 1


def test_off_windows_animations_read_as_on(monkeypatch):
    monkeypatch.setattr(motion.sys, "platform", "linux")
    assert motion.windows_animations() is True


def test_the_window_follows_app_motion_from_settings(qapp):
    services = shell.Services()
    try:
        services.settings.set({"app_motion": "reduced"}, now=True)
        win = shell.open_window(qapp, services)
        assert motion.clock().mode.setting == "reduced" and motion.clock().mode.reduced
        services.settings.set({"app_motion": "full"}, now=True)
        assert _wait(lambda: motion.clock().mode.setting == "full")
        win.close()
    finally:
        services.settings.set({"app_motion": "follow"}, now=True)
        motion.clock().mode.set_setting("follow")
        services.shutdown(0.5)


def _wait(predicate, timeout=5.0):
    from tests.qt.conftest import wait_until
    return wait_until(predicate, timeout)


# --- row 3: the overlay animator ------------------------------------------------------------------------------------ #
class Card(motion.Overlay):
    """A stand-in overlay: a label of ja text and a button."""

    def __init__(self, parent, how="pop"):
        super().__init__(parent)
        self.how = how
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        self.label = QLabel(JA, self)
        self.button = QPushButton("開く", self)
        self.button.setToolTip("Open it")
        lay.addWidget(self.label)
        lay.addWidget(self.button)
        self.clicks = []
        self.button.clicked.connect(lambda: self.clicks.append(1))
        self.setGeometry(200, 120, 320, 140)


@pytest.mark.parametrize("how", sorted(motion.HOW))
def test_each_kind_starts_at_its_offset_transparent_and_ends_in_place(clock, stage, how):
    card = Card(stage, how)
    opening = card.open()
    assert opening is not None and not card.isVisible()
    ghost = opening.ghost
    dur, dist_name, axis, sign = motion.HOW[how]
    dist = theme.MOTION[dist_name] * sign if dist_name else 0
    want = QPoint(dist, 0) if axis == "x" else QPoint(0, dist)
    assert ghost.offset - opening._origin == want and ghost.opacity == 0.0
    assert card.graphicsEffect() is None
    clock.advance(theme.MOTION[dur] // 2)
    assert 0.0 < ghost.opacity < 1.0 and card.graphicsEffect() is None
    clock.advance(theme.MOTION[dur])
    assert card.isVisible() and card.geometry() == QRect(200, 120, 320, 140) and motion.opening_of(card) is None
    assert ghost.isHidden()                                  # gone (deleted on the next turn)


def test_the_ghost_at_its_place_is_the_overlay_pixel_for_pixel(clock, stage):
    card = Card(stage)
    opening = card.open()
    ghost = opening.ghost
    ghost.opacity, ghost.offset = 1.0, opening._offset(1.0)
    seen = ghost.grab(ghost.content_rect()).toImage()
    want = opening.pixmap.toImage()
    assert seen.size() == want.size()
    assert seen.convertToFormat(want.format()) == want      # never resampled: crisp


def test_an_overlay_already_shown_or_opening_never_animates_again(clock, stage):
    card = Card(stage)
    assert card.open() is not None
    assert card.open() is None                                # opening: a second open starts nothing
    clock.advance(200)
    assert card.isVisible()
    assert card.open() is None                                # shown: a refresh holds still (R4b-5)
    card.hide()
    assert card.open() is not None                            # closed and opened again: it animates again


def test_hide_or_close_during_the_opening_drops_it_and_it_stays_hidden(clock, stage):
    for close in (lambda c: c.hide(), lambda c: c.close()):
        card = Card(stage)
        opening = card.open()
        clock.advance(48)
        close(card)
        assert motion.opening_of(card) is None and opening.ghost is None
        clock.advance(400)
        assert not card.isVisible()


def test_esc_during_the_opening_finishes_it_then_the_router_closes_it(clock, qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    QApplication.processEvents()
    try:
        card = Card(win.centralWidget())
        win.register_overlay(card)
        card.open()
        clock.advance(32)
        QTest.keyClick(win.centralWidget(), Qt.Key.Key_Escape)
        QApplication.processEvents()
        assert not card.isVisible() and motion.opening_of(card) is None and win.isVisible()
    finally:
        win.close()
        services.shutdown(0.5)


def test_esc_closes_an_overlay_still_opening_when_its_finisher_is_gone(clock, qapp):
    # M2.1 review A3: the router must not depend on the opening's own filter finishing it first; with that filter
    # removed, an Esc during the opening still closes the overlay and drops the opening
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    QApplication.processEvents()
    try:
        card = Card(win.centralWidget())
        win.register_overlay(card)
        opening = card.open()
        clock.advance(32)
        opening._finisher.remove()                              # the opening's filter does not finish it before the router
        assert motion.opening_of(card) is opening and not card.isVisible()
        QTest.keyClick(win.centralWidget(), Qt.Key.Key_Escape)
        QApplication.processEvents()
        assert motion.opening_of(card) is None and not card.isVisible() and win.isVisible()
        clock.advance(400)
        assert not card.isVisible()                             # and it stays closed when its time is up
    finally:
        win.close()
        services.shutdown(0.5)


def test_a_press_on_the_opening_overlay_reaches_the_button_the_user_saw(clock, stage):
    # routed as Qt routes it: the press lands on the window at the point; the ghost takes no mouse itself
    card = Card(stage)
    opening = card.open()
    clock.advance(48)
    ghost = opening.ghost
    at = ghost.mapTo(stage, ghost.content_rect().topLeft() + card.button.geometry().center())
    win = stage.windowHandle()                                 # through the window: Qt picks the widget at the point
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert card.isVisible() and motion.opening_of(card) is None    # finished first
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert card.clicks == [1]
    assert not _filters_left(opening)


def test_a_press_beside_the_opening_overlay_reaches_what_is_there(clock, stage):
    # review A2: the shadow's margin and the travel are no wall — a row under a rising toast takes its click
    below = QPushButton("下の行", stage)
    below.setGeometry(200, 270, 320, 30)                       # under the card's bottom edge, in its shadow's reach
    below.show()
    hits = []
    below.clicked.connect(lambda: hits.append(1))
    card = Card(stage, "up")
    opening = card.open()
    clock.advance(32)
    at = below.geometry().center()
    assert not opening.ghost.content_rect().contains(opening.ghost.mapFrom(stage, at))
    QTest.mouseClick(stage.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert hits == [1] and card.isVisible()                    # the opening finished, the click went where it fell


def test_the_ghost_is_transparent_so_a_press_on_its_travel_strip_reaches_the_button_under_it(clock, stage):
    # why: the app-wide finisher would end the opening on any press first, hiding the ghost, so the finisher is
    # taken off here and the press meets the ghost alone: a transparent ghost lets it reach the button beneath
    below = QPushButton("下の行", stage)
    below.setGeometry(200, 270, 320, 30)                       # inside the ghost's travel, under the card's bottom edge
    below.show()
    hits = []
    below.clicked.connect(lambda: hits.append(1))
    card = Card(stage, "up")
    opening = card.open()
    clock.advance(32)
    ghost = opening.ghost
    at = below.geometry().center()
    assert ghost.rect().contains(ghost.mapFrom(stage, at))     # the press really lands on the ghost's own area
    assert not ghost.content_rect().contains(ghost.mapFrom(stage, at))
    opening._finisher.remove()
    QTest.mouseClick(stage.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert hits == [1]


def _filters_left(opening):
    f = opening._finisher
    return f is not None and f.installed


def test_every_end_tears_the_opening_down_a_hidden_page_an_error_a_stop(clock, stage, qt_errors):
    # review A1: an opening cut short leaves no filter, no ghost, and the overlay can open again
    page = QWidget(stage)
    page.setGeometry(0, 0, 900, 640)
    page.show()
    card = Card(page, "slide")
    opening = card.open()
    clock.advance(32)
    page.hide()                                                 # a tab switch while the side panel opens
    clock.advance(32)
    assert motion.opening_of(card) is None and opening.ghost is None and not _filters_left(opening)
    assert not card.isHidden()                                  # it was asked open: open, without the motion
    page.show()
    assert card.isVisible()
    card.hide()
    assert card.open() is not None                              # and it opens again
    clock.advance(400)
    card.hide()
    # an error in a frame
    opening = card.open()
    opening._frame = lambda v: (_ for _ in ()).throw(ValueError("a painter's bug"))
    opening.anim.on_frame = opening._frame
    clock.advance(32)
    assert motion.opening_of(card) is None and not _filters_left(opening) and card.isVisible()
    assert qt_errors and qt_errors[0][0] is ValueError
    qt_errors.clear()
    card.hide()
    # stopped from outside
    opening = card.open()
    opening.anim.stop()
    assert motion.opening_of(card) is None and not _filters_left(opening)


def test_a_piece_that_raises_on_a_tests_time_is_reported_the_overlay_shown_and_the_opening_over(clock, stage, qt_errors,
                                                                                            monkeypatch):
    # why: on a test's time the pieces run inside open(); a piece's error must not escape open(), must reach the
    # error hook, and must leave no opening and no app-wide filter behind, and the overlay must open again later
    seen = []

    def snapshot_that_raises(self):
        seen.append(self)                                       # the opening, to check its filter afterwards
        raise ValueError("a piece's bug")
    monkeypatch.setattr(motion.OverlayOpening, "_snapshot", snapshot_that_raises)
    card = Card(stage, "slide")
    card.open()
    opening = seen[0]
    assert qt_errors and qt_errors[0][0] is ValueError
    qt_errors.clear()
    assert opening.ended and not opening.live                   # the opening is over
    assert motion.opening_of(card) is None and not _filters_left(opening)
    assert card.isVisible()                                     # shown at once, without the motion
    monkeypatch.undo()
    card.hide()
    assert card.open() is not None                              # and it opens again
    clock.advance(400)
    assert motion.opening_of(card) is None and card.isVisible()
    assert not qt_errors


def test_a_finisher_whose_opening_is_over_removes_itself_and_lets_the_key_through(clock, stage, qapp):
    # why: a finisher left on the app after its opening ended would sit on every key and press of the whole app
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    card = Card(stage)
    opening = card.open()
    opening.anim.stop()                                         # the opening is over: its animation has stopped
    assert not opening.live and opening._pressed is None
    finisher = motion._InputFinisher(opening)                   # a finisher still built for that finished opening
    qapp.installEventFilter(finisher)
    try:
        key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
        assert finisher.eventFilter(stage, key) is False        # the key goes on to whatever has it
        assert not finisher.installed                           # and the filter has taken itself off the app
    finally:
        qapp.removeEventFilter(finisher)


def test_back_during_the_opening_closes_it(clock, qapp):
    # review A3: the mouse's Back button over an opening overlay closes it, as Esc does
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    QApplication.processEvents()
    try:
        card = Card(win.centralWidget())
        win.register_overlay(card)
        opening = card.open()
        clock.advance(32)
        at = opening.ghost.mapTo(win.centralWidget(), opening.ghost.content_rect().center())
        QTest.mouseClick(win.centralWidget(), Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier, at)
        QApplication.processEvents()
        assert not card.isVisible() and motion.opening_of(card) is None and win.isVisible()
    finally:
        win.close()
        services.shutdown(0.5)


def test_a_key_during_an_opening_without_focus_stays_with_the_field(clock, stage):
    field = QLineEdit(stage)
    field.setGeometry(10, 10, 200, 30)
    field.show()
    stage.activateWindow()
    field.setFocus()
    QApplication.processEvents()
    card = Card(stage, "rise")
    card.open()                                               # focus=False: a toast, search results
    clock.advance(32)
    QTest.keyClick(field, Qt.Key.Key_A)
    QApplication.processEvents()
    assert card.isVisible()                                   # the key finished the opening
    assert field.text() == "a" and stage.focusWidget() is field   # the window's own focus, never the overlay


def test_an_opener_that_asks_gives_the_overlay_the_focus(clock, stage):
    card = Card(stage)
    card.focus = True
    card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    stage.activateWindow()
    card.open()
    clock.advance(400)
    assert card.isVisible() and stage.focusWidget() is card


def test_each_frame_repaints_only_where_the_ghost_was_and_is(clock, stage):
    card = Card(stage, "up")
    opening = card.open()
    ghost = opening.ghost
    rects = []
    original = ghost.update
    ghost.update = lambda *a: (rects.append(a[0]) if a else None, original(*a))
    painted = opening._painted()
    full_travel = ghost.rect()
    clock.advance(200)
    assert rects
    for r in rects:
        assert full_travel.contains(r)
        assert r.height() <= painted.height() + abs(opening.delta.y())


def test_reduced_an_overlay_fades_in_place_within_fast(clock, stage):
    clock.mode.set_setting("reduced")
    card = Card(stage, "up")
    opening = card.open()
    assert opening.ghost.offset == QPoint(0, 0)
    clock.advance(theme.FAST)
    assert card.isVisible()


def test_frozen_an_overlay_shows_at_once_on_top_and_focused_as_users_see_it(qapp, stage):
    # review A5: the frozen path ends as an opening does (tests run frozen: they must see what users see)
    freeze.set_frozen(True)
    try:
        other = QLabel("上", stage)
        other.setGeometry(150, 100, 400, 200)
        other.show()
        card = Card(stage)
        card.focus = True
        card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        assert card.open() is None and card.isVisible()
        assert stage.childAt(card.geometry().center()) in (card, card.label, card.button)   # raised over the label
        assert stage.focusWidget() is card
    finally:
        freeze.set_frozen(None)


def test_a_top_level_popup_moves_and_fades_on_its_own_window(clock, qapp):
    pop = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    pop.setGeometry(300, 300, 200, 100)
    opening = motion.open_overlay(pop, "pop")
    assert pop.isVisible() and pop.pos() == QPoint(300, 300 - theme.MOTION["pop-shift"])
    clock.advance(theme.MOTION["overlay-pop"])
    assert pop.pos() == QPoint(300, 300) and motion.opening_of(pop) is None and opening is not None
    pop.hide()
    # review A7: a popup closed mid-opening keeps no half-faded state for its next open
    opening = motion.open_overlay(pop, "pop")
    clock.advance(40)
    motion.cancel_opening(pop)
    assert pop.windowOpacity() == 1.0 and pop.pos() == QPoint(300, 300) and not pop.isVisible()
    pop.close()


# --- row 6: the spinner --------------------------------------------------------------------------------------------- #
def test_a_running_spinner_is_on_the_clock_only_while_shown(clock, stage):
    clock.use_real_time()
    spin = motion.Spinner("pulse", stage)
    spin.show()
    assert not spin.on_clock and not clock.running              # not running: nothing moves
    spin.set_running(True)
    assert spin.on_clock and len(clock.active) == 1 and clock.running
    spin.hide()
    assert not spin.on_clock and not clock.running             # hidden: off the clock, which stops
    spin.show()
    assert spin.on_clock
    spin.set_running(False)
    assert not spin.on_clock and not clock.running


def test_a_minimised_window_stops_its_spinner(clock, qapp):
    clock.use_real_time()
    top = QWidget()
    top.resize(200, 100)
    spin = motion.Spinner("spin", top)
    top.show()
    spin.set_running(True)
    assert spin.on_clock
    top.setWindowState(Qt.WindowState.WindowMinimized)
    assert _wait(lambda: not spin.on_clock, 2)
    top.setWindowState(Qt.WindowState.WindowNoState)
    assert _wait(lambda: spin.on_clock, 2)
    top.close()


def test_reduced_or_frozen_a_spinner_is_a_still_mark(clock, stage):
    spin = motion.Spinner("pulse", stage)
    spin.show()
    clock.mode.set_setting("reduced")
    spin.set_running(True)
    assert not spin.on_clock and spin.pulse_opacity() == 1.0
    clock.mode.set_setting("full")
    assert spin.on_clock                                        # the mode changed back: it moves again
    spin.set_running(False)


def test_the_pulse_dims_to_a_third_at_its_half(clock, stage):
    spin = motion.Spinner("pulse", stage)
    spin.show()
    spin.set_running(True)
    clock.advance(1)
    assert spin.pulse_opacity() == pytest.approx(1.0, abs=0.01)
    clock.advance(theme.MOTION["footer-pulse"] / 4 - 1)               # a quarter: halfway down, on ease-in-out
    assert spin.pulse_opacity() == pytest.approx(1.0 - 0.65 * 0.5, abs=0.02)
    clock.advance(theme.MOTION["footer-pulse"] / 4)
    assert spin.pulse_opacity() == pytest.approx(0.35, abs=0.01)
    c = _alone(spin).pixelColor(spin.width() // 2, spin.height() // 2)
    # the dot at .35 over its glow at .35: about two fifths covered, never the full dot
    assert 70 <= c.alpha() <= 130
    spin.set_running(False)
    still = _alone(spin).pixelColor(spin.width() // 2, spin.height() // 2)
    assert still.alpha() == 255 and still.name() == theme.colours("hb")["ink-faint"]


def _alone(widget):
    """The widget painted on a transparent image, without the window's background (grab() would draw it)."""
    from PyQt6.QtGui import QImage, QRegion
    img = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    widget.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img


def test_the_bars_dot_runs_while_a_job_runs(clock, qapp):
    from app.services import status as status_service
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    QApplication.processEvents()
    try:
        snap = status_service.Snapshot((), None, (), None, None, None, 0.0)
        win.show_status(snap._replace(lines=("Generating · Reading your files 3 / 12",)))
        assert win.bar_dot.running and win.bar_dot.property("busy") == "true"
        win.show_status(snap)
        assert not win.bar_dot.running and not win.bar_dot.on_clock
    finally:
        win.close()
        services.shutdown(0.5)


# --- row 7: the lifted opening (Windows' compositor fades and moves it; measured ≈ 0.3 ms a frame) ------------------- #
@pytest.fixture
def lifted(monkeypatch):
    motion.LIFT = True
    monkeypatch.setattr(motion, "_in_front", lambda top: True)   # (offscreen hands activation around unlike Windows)
    yield
    motion.LIFT = None
    motion._LIFTS.clear()                                        # the kept lifts belong to this test's window


def test_a_lifted_opening_is_a_see_through_window_moved_and_faded_then_the_overlay(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    card = Card(stage, "up")
    opening = card.open()
    lift = opening.lift
    assert lift is not None and opening.ghost is None and lift.isTopLevel()
    assert lift.transientParent() is stage.windowHandle()        # owned by its window: shown above it
    assert bool(lift.flags() & Qt.WindowType.WindowTransparentForInput)
    assert bool(lift.flags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert lift.format().alphaBufferSize() == 8                  # see-through
    final = opening._lift_at
    assert lift.position() == final + QPoint(0, theme.MOTION["buckets-rise"]) and lift.opacity() == 0.0
    clock.advance(130)
    assert 0.0 < lift.opacity() < 1.0 and final.y() < lift.position().y() < final.y() + 40
    clock.advance(200)
    assert card.isVisible() and motion.opening_of(card) is None
    assert wait_until(lambda: sip.isdeleted(lift) or not lift.isVisible(), 2)       # gone a frame after the overlay


def test_the_snapshot_is_drawn_over_the_shadow_and_never_clears_it(clock, stage, lifted):
    from PyQt6.QtGui import QImage
    from tests.qt.conftest import wait_until
    # why (M2.1-3): a lifted opening paints in two pieces: "under" clears the store and draws the shadow, "over" draws
    # the snapshot onto what is there and clears nothing. An over piece that clears would wipe the shadow away, and
    # the card would sit on a bare see-through window with no edge. Checked after the pieces ran, while still open.
    card = Card(stage, "up")
    card.shadow_name = "dialog"
    opening = card.open()
    assert wait_until(lambda: opening._pieces is None, 2)
    assert opening.lift is not None and not opening.ended
    picture = sip.cast(opening.lift.store.paintDevice(), QImage)
    dpr = picture.devicePixelRatio()
    top = opening.target_in_picture.y()
    centre_x = opening.target_in_picture.x() + card.width() // 2
    below = top + card.height() + 6                              # a few pixels under the card, in the shadow's margin
    shadow_alpha = picture.pixelColor(round(centre_x * dpr), round(below * dpr)).alpha()
    snapshot_alpha = picture.pixelColor(round(centre_x * dpr), round((top + card.height() // 2) * dpr)).alpha()
    assert shadow_alpha > 0                                      # the shadow survived the snapshot's piece
    assert snapshot_alpha == 255                                 # and the snapshot is drawn on top of it


class _PaintCount(QObject):
    """Counts the Paint events a widget gets (an event filter that never takes one)."""

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.count = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False

    def stop(self):
        self.widget.removeEventFilter(self)


def test_each_lifted_frame_repaints_nothing_not_the_window_nor_what_is_under_it(clock, stage, lifted, monkeypatch):
    # S19: a frame moves and fades the lift window alone (the compositor blends it), so no paint of the window, of a
    # widget under the overlay, or of the lift's own paint and flush
    sibling = QWidget(stage)
    sibling.setGeometry(180, 100, 360, 180)            # under the card that opens over it
    sibling.show()
    QApplication.processEvents()
    card = Card(stage, "up")
    opening = card.open()
    lift = opening.lift
    assert lift is not None
    QTest.qWait(60)                                    # the show's own expose pass is over: count from here
    calls = []

    def counted(name, real):
        def wrapper(self, *a):
            calls.append(name)
            return real(self, *a)
        return wrapper

    monkeypatch.setattr(motion._Lift, "paint", counted("paint", motion._Lift.paint))
    monkeypatch.setattr(motion._Lift, "flush", counted("flush", motion._Lift.flush))
    win_paints, sib_paints = _PaintCount(stage), _PaintCount(sibling)
    try:
        clock.advance(150)
        QTest.qWait(60)                                # any posted paint is delivered
        assert 0.0 < lift.opacity() < 1.0              # mid-motion: the frames really ran
        assert win_paints.count == 0 and sib_paints.count == 0
        assert calls == []
        sibling.update()                               # contrast: the counter does see a real repaint
        QTest.qWait(60)
        assert sib_paints.count > 0
    finally:
        win_paints.stop()
        sib_paints.stop()


def test_a_press_on_a_lifted_opening_reaches_its_button(clock, stage, lifted):
    card = Card(stage)
    opening = card.open()
    clock.advance(48)
    at = stage.mapFromGlobal(opening.content_global().topLeft() + card.button.geometry().center())
    win = stage.windowHandle()
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert card.clicks == [1] and card.isVisible()


def test_a_lifted_opening_ends_when_its_page_goes_or_its_window_moves(clock, stage, lifted):
    page = QWidget(stage)
    page.setGeometry(0, 0, 900, 640)
    page.show()
    card = Card(page, "slide")
    opening = card.open()
    clock.advance(32)
    page.hide()
    clock.advance(32)
    assert motion.opening_of(card) is None and opening.lift is None and not _filters_left(opening)
    page.show()
    card.hide()
    opening = card.open()
    clock.advance(32)
    stage.move(stage.pos() + QPoint(30, 0))                      # the window moved: the opening lands at once
    QApplication.processEvents()
    assert motion.opening_of(card) is None and card.isVisible()


def test_a_minimised_window_opens_its_overlay_at_once_with_no_lift_and_no_ghost(clock, stage, lifted, monkeypatch):
    # why (M2.1-A1): a minimised window has nothing on screen to lift or to ghost over; the overlay is shown as asked
    # and the opening is over, at once, as its last piece runs
    started = []                                                 # records the opening (it has ended by open()'s return)
    real_start = motion.OverlayOpening.start

    def recording_start(self):
        started.append(self)
        return real_start(self)

    monkeypatch.setattr(motion.OverlayOpening, "start", recording_start)
    stage.showMinimized()
    QApplication.processEvents()
    if not stage.isMinimized():
        stage.setWindowState(Qt.WindowState.WindowMinimized)
    assert stage.isMinimized()
    card = Card(stage, "up")
    card.open()
    assert len(started) == 1
    opening = started[0]
    assert opening.ended and motion.opening_of(card) is None
    assert opening.lift is None and opening.ghost is None
    assert not card.isHidden()


def test_a_minimised_window_takes_no_lift_so_take_lift_is_never_called(clock, stage, lifted, monkeypatch):
    # why (M2.1-A1): a lift is a window kept or made for the opening; a minimised window has none to be placed on, so
    # the lift is not taken at all (not taken and given back) and the overlay is shown as asked at once
    taken = []                                                   # records every lift the opening asks for
    real_take = motion._take_lift

    def recording_take(opening, top):
        taken.append(top)
        return real_take(opening, top)

    monkeypatch.setattr(motion, "_take_lift", recording_take)
    stage.showMinimized()
    QApplication.processEvents()
    if not stage.isMinimized():
        stage.setWindowState(Qt.WindowState.WindowMinimized)
    assert stage.isMinimized()
    card = Card(stage, "up")
    card.open()                                                  # (ended by the time it returns: no opening to hold)
    assert taken == []
    assert motion.opening_of(card) is None
    assert not card.isHidden()


def test_a_window_not_in_front_opens_with_the_painted_ghost_not_a_lift(clock, stage, lifted, monkeypatch):
    # why (M2.1-A2): a lift is a window of its own and would show over another program's window, so a window behind
    # another program's is opened with the painted stand-in even though lifting is chosen; it still ends with the overlay
    monkeypatch.setattr(motion, "_in_front", lambda top: False)
    card = Card(stage, "up")
    opening = card.open()
    clock.advance(32)
    assert motion.opening_of(card) is opening
    assert opening.ghost is not None and opening.lift is None
    clock.advance(400)
    assert card.isVisible() and motion.opening_of(card) is None


def test_a_page_back_on_screen_before_the_show_opens_painted_when_no_lift_was_placed(clock, stage, lifted, monkeypatch):
    # why (M2.1-3, review L1): the page was hidden when the lift would have been placed (none taken), and shown again
    # before the show piece: the opening uses the painted ghost — never a show of a lift that was never placed (an
    # error the harness would report) — and ends with the overlay shown
    page = QWidget(stage)
    page.setGeometry(0, 0, 900, 640)
    page.show()
    place = motion.OverlayOpening._lift_place

    def hidden_while_placed(self):
        page.hide()
        place(self)
        page.show()
    monkeypatch.setattr(motion.OverlayOpening, "_lift_place", hidden_while_placed)
    card = Card(page, "up")
    opening = card.open()
    assert opening is not None and opening.lift is None and opening.ghost is not None
    clock.advance(400)
    assert card.isVisible() and motion.opening_of(card) is None


def test_a_page_moved_while_its_lift_is_prepared_shows_the_lift_at_its_new_place(clock, stage, lifted, monkeypatch):
    # why (M2.1-3, review L6): the lift's place is read when it is placed, three passes before its show; a page moved
    # in the window meanwhile would show it at the old place. The show reads the place again.
    page = QWidget(stage)
    page.setGeometry(0, 0, 900, 640)
    page.show()
    paint = motion.OverlayOpening._lift_paint

    def moved_while_painted(self):
        page.move(page.pos() + QPoint(30, 20))
        paint(self)
    monkeypatch.setattr(motion.OverlayOpening, "_lift_paint", moved_while_painted)
    card = Card(page, "up")
    opening = card.open()
    lift = opening.lift
    now = page.mapToGlobal(opening._area.topLeft())
    assert opening._lift_at == now and lift.position() == now + opening.delta


def test_a_window_that_goes_behind_while_its_lift_is_prepared_opens_with_the_painted_ghost(clock, stage, lifted,
                                                                                           monkeypatch):
    # why (M2.1-A2b): the lift is placed while the window is in front, then the window goes behind another program's
    # before the show; the lift is given back and the opening uses the painted ghost with its picture composed there
    answers = [True, False]                                      # the place piece asks first, `_go` second
    monkeypatch.setattr(motion, "_in_front", lambda top: answers.pop(0) if answers else False)
    given = []                                                   # records the lift given back (wrapping, not replacing)
    real_give_back = motion._give_back
    monkeypatch.setattr(motion, "_give_back", lambda lift: (given.append(lift), real_give_back(lift))[1])
    card = Card(stage, "up")
    opening = card.open()
    assert len(given) == 1                                       # the placed lift went back to the pool
    assert opening.ghost is not None and opening.lift is None
    assert opening.picture is not None                           # the ghost's picture composed behind the other program
    clock.advance(400)
    assert card.isVisible() and motion.opening_of(card) is None


def test_a_lift_taken_for_a_window_that_went_behind_is_given_back_hidden_at_once(clock, stage, split, lifted, monkeypatch):
    # why (M2.1-A3): the lift is placed while the window is in front and the window goes behind another program's before
    # its show; the lift must not be left on the opening or shown over that program, but given back to the window's pool
    # at once, so the next opening can take it (the ghost shows instead, and the overlay still ends shown)
    answers = [True, False]                                      # the place piece asks first, `_go` second
    monkeypatch.setattr(motion, "_in_front", lambda top: answers.pop(0) if answers else False)
    taken = []
    real_take = motion._take_lift

    def recording_take(opening, top):
        lift = real_take(opening, top)
        taken.append(lift)
        return lift

    monkeypatch.setattr(motion, "_take_lift", recording_take)
    card = Card(stage, "slide")
    opening = card.open()
    _passes(opening)
    assert len(taken) == 1
    lift = taken[0]
    assert opening.ghost is not None and opening.lift is None
    assert not lift.isVisible() and lift.opening is None
    assert lift in motion._LIFTS[id(stage)]
    clock.advance(400)
    assert card.isVisible() and motion.opening_of(card) is None


def test_a_window_not_in_front_composes_the_ghosts_picture_before_it_shows(clock, stage, lifted, monkeypatch):
    # why (M2.1-A2): the stand-in is painted from its picture (shadow + snapshot), so that picture must be composed
    # before the ghost shows — otherwise the first frames paint nothing over the window
    monkeypatch.setattr(motion, "_in_front", lambda top: False)
    card = Card(stage, "up")
    opening = card.open()
    assert opening.lift is None and opening.ghost is not None
    assert opening.picture is not None
    dpr = opening.picture.devicePixelRatio()
    assert opening.picture.width() >= opening.widget_size.width() * dpr
    assert opening.picture.height() >= opening.widget_size.height() * dpr
    clock.advance(32)
    assert motion.opening_of(card) is opening                    # still opening: the ghost is what is on screen
    ghost = opening.ghost
    ghost.opacity, ghost.offset = 1.0, opening._offset(1.0)      # (the neighbour's way: the overlay at its place)
    img = ghost.grab().toImage()
    centre = ghost.content_rect().center()
    px = QPoint(round(centre.x() * img.devicePixelRatio()), round(centre.y() * img.devicePixelRatio()))
    assert img.pixelColor(px).alpha() == 255                     # the picture is painted: an opaque pixel at the centre


def test_a_painted_opening_survives_a_window_move_and_a_resize_lands_it(clock, stage):
    # why: a painted opening's ghost is a child of the window, so a move carries it along and the picture still fits:
    # only a resize (the picture no longer fits) lands it. The lifted move lands at once (the test above).
    card = Card(stage, "slide")
    opening = card.open()
    clock.advance(32)
    assert opening.ghost is not None and opening.lift is None    # painted: the default when nothing is lifted
    stage.move(stage.pos() + QPoint(30, 0))                      # the window moved under the ghost: still opening
    QApplication.processEvents()
    assert motion.opening_of(card) is opening and opening.live
    stage.resize(stage.width() + 40, stage.height())             # the picture no longer fits: it lands at once
    QApplication.processEvents()
    assert motion.opening_of(card) is None and card.isVisible()


def test_a_window_moved_under_a_lift_gives_the_lift_back_at_once(clock, stage, lifted):
    # why (M2.1-H9): the lift is a window left at the old place; a move from under it lands the opening, so the lift is
    # hidden now, not a frame later (that frame is only the no-flash wait of a normal end, checked next)
    card = Card(stage, "up")
    opening = card.open()
    clock.advance(32)
    lift = opening.lift
    assert lift is not None and lift.isVisible()                 # so the hidden check below can't pass on a lift never shown
    stage.move(stage.pos() + QPoint(30, 0))
    QApplication.processEvents()
    assert not lift.isVisible() and lift.opening is None


def test_a_normal_end_keeps_the_lift_one_frame_after_the_overlay(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    # why (M2.1-H9): the overlay must paint before its lift goes, so a normal end keeps the lift visible until the next frame
    card = Card(stage, "up")
    opening = card.open()
    clock.advance(32)
    lift = opening.lift                                          # read before the end: the opening drops its lift at once
    assert lift is not None
    clock.advance(400)
    assert card.isVisible() and lift.isVisible()
    assert wait_until(lambda: not lift.isVisible(), 2)


def test_an_overlay_hidden_in_the_lifts_last_frame_gives_the_lift_back_at_once(clock, stage, lifted):
    # why (M2.1-A3): a normal end keeps the lift one frame; if the overlay is hidden in that frame (Esc closing it), the
    # lift is given back right then, not a frame later. Checked with no clock advance and no wait: nothing may pass time.
    card = Card(stage, "up")
    opening = card.open()
    clock.advance(32)
    lift = opening.lift                                          # read before the end: the opening drops its lift at once
    assert lift is not None
    clock.advance(400)
    assert card.isVisible() and lift.isVisible()                 # the lift is still up in its one frame (the contrast)
    card.hide()
    assert not lift.isVisible() and lift.opening is None         # given back in the same call, no frame to wait for


def test_a_lifted_opening_hands_its_window_to_the_next_opening(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    # why: making a top-level window each time costs a native window's birth; a kept one is only shown again
    card1 = Card(stage, "up")
    o1 = card1.open()
    lift = o1.lift
    clock.advance(400)                                           # the opening ends; its lift is given back a frame on
    assert wait_until(lambda: not lift.isVisible(), 2)
    assert lift.opening is None and lift in motion._LIFTS[id(lift.owner)]
    card1.hide()
    card2 = Card(stage, "up")
    o2 = card2.open()
    assert o2.lift is lift and lift.opening is o2 and lift.isVisible()
    clock.advance(400)
    assert card2.isVisible()


def test_a_lift_whose_opening_has_ended_paints_nothing_until_it_is_given_back(clock, stage, lifted, monkeypatch):
    # why (M2.1-H4): once the opening ends its overlay is shown under the lift and may already be gone, so a repaint of
    # the lift in its last frame (an expose) must draw nothing; during the opening the same repaint draws the picture
    # (the contrast keeps this honest)
    card = Card(stage, "up")
    opening = card.open()
    lift = opening.lift
    drawn = []
    draw = motion.OverlayOpening._draw
    monkeypatch.setattr(motion.OverlayOpening, "_draw", lambda self, p, **k: (drawn.append(self), draw(self, p, **k))[1])
    clock.advance(120)                                           # mid-opening: a repaint draws its picture
    lift.paint()
    assert drawn == [opening]
    clock.advance(280)                                           # the opening ends; the lift is not given back yet
    assert card.isVisible() and motion.opening_of(card) is None
    assert lift.isVisible() and lift.opening is opening
    lift.paint()
    assert drawn == [opening]                                    # nothing drawn: the store is left clear


def test_a_lift_is_painted_and_flushed_while_hidden_so_its_show_is_only_a_show(clock, stage, lifted, split, monkeypatch):
    from PyQt6.QtTest import QTest
    from tests.qt.conftest import wait_until
    # why (M2.1-3): a widget's show painted it and flushed the whole see-through window in that one pass (8 ms at 150 %,
    # a scrim); the lift paints into its backing store and hands the picture over while hidden, each a pass of its own,
    # and its show's expose flushes nothing again. A later expose that changes nothing redraws nothing (S19); one with
    # a new size (a screen change) repaints and flushes.
    calls = []
    for name in ("paint", "flush"):
        real = getattr(motion._Lift, name)
        monkeypatch.setattr(motion._Lift, name,
                            lambda self, *a, real=real, name=name: (calls.append((name, self.isVisible())), real(self, *a))[1])
    card1 = Card(stage, "up")
    o1 = card1.open()
    assert wait_until(lambda: o1._pieces is None, 2)
    lift = o1.lift
    QTest.qWait(60)                                              # the show's expose, and anything it would ask for
    assert lift.isVisible() and calls == [("paint", False), ("paint", False), ("flush", False)]   # under, over
    lift.exposeEvent(QExposeEvent(QRegion(QRect(QPoint(), lift.size()))))   # exposed again, nothing changed
    assert calls == [("paint", False), ("paint", False), ("flush", False)]
    calls.clear()
    lift.resize(lift.width() + 8, lift.height())                 # a screen change gave it a new size
    lift.exposeEvent(QExposeEvent(QRegion(QRect(QPoint(), lift.size()))))
    assert calls == [("paint", True), ("flush", True)]
    clock.advance(400)
    assert wait_until(lambda: not lift.isVisible(), 2)
    card1.hide()
    calls.clear()
    card2 = Card(stage, "pop")
    card2.setGeometry(150, 100, 420, 220)
    o2 = card2.open()                                            # the kept lift shown again, at another size
    assert wait_until(lambda: o2._pieces is None, 2)
    assert o2.lift is lift and lift.isVisible()
    QTest.qWait(60)
    assert calls == [("paint", False), ("paint", False), ("flush", False)]
    assert lift.store.size() == lift.size() == o2._size          # its store painted at the new size


def test_a_hidden_lift_paints_and_flushes_nothing(clock, stage, lifted, monkeypatch):
    from PyQt6.QtTest import QTest
    from tests.qt.conftest import wait_until
    # why (M2.1-3): a hidden lift has no screen to repaint; its hide (an expose that leaves it not exposed) and any
    # expose while hidden leave its store and Windows' picture alone. While shown, an expose with a new size repaints
    # (the contrast).
    card = Card(stage, "up")
    lift = card.open().lift
    QTest.qWait(60)                                              # the show's expose, past
    calls = []
    for name in ("paint", "flush"):
        real = getattr(motion._Lift, name)
        monkeypatch.setattr(motion._Lift, name,
                            lambda self, *a, real=real, name=name: (calls.append((name, self.isVisible())), real(self, *a))[1])
    lift.resize(lift.width() + 8, lift.height())
    lift.exposeEvent(QExposeEvent(QRegion(QRect(QPoint(), lift.size()))))   # shown, a new size: repaints
    assert calls == [("paint", True), ("flush", True)]
    clock.advance(400)                                           # the opening ends; its lift is given back, hidden
    assert wait_until(lambda: not lift.isVisible(), 2)
    QTest.qWait(60)                                              # the hide's own expose
    assert lift.opening is None and not lift.isExposed()
    lift.exposeEvent(QExposeEvent(QRegion()))                    # and one more while hidden
    assert [c for c in calls if not c[1]] == []                  # nothing painted or flushed while hidden


def test_no_more_than_the_kept_number_of_lifts_stay(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    # why: the pool is bounded: a window that once opened many overlays at once keeps at most LIFTS_KEPT hidden ones
    cards = [Card(stage, how) for how in ("up", "pop", "slide")]
    assert len(cards) == motion.LIFTS_KEPT + 1
    openings = [card.open() for card in cards]
    lifts = [o.lift for o in openings]
    assert len({id(w) for w in lifts}) == len(cards)             # each opening has a lift of its own
    top = lifts[0].owner                                         # taken before the advance: the window they belong to
    clock.advance(400)
    assert wait_until(lambda: all(sip.isdeleted(w) or not w.isVisible() for w in lifts), 2)
    free = [w for w in motion._LIFTS.get(id(top), []) if not sip.isdeleted(w)]
    assert len(free) <= motion.LIFTS_KEPT


# --- row 7: the opening prepared in pieces (M2.1-1, lean (b)): never one GUI-thread step of 4–10 ms per click -------- #
@pytest.fixture
def split():
    motion.SPLIT = True
    yield
    motion.SPLIT = None


def _passes(opening):
    """Run the loop until the opening is ready (moving or ended); -> the loop pass each piece ran in, by name."""
    from tests.qt.conftest import wait_until
    seen, n = {}, [0]
    for name in ("_snapshot", "_picture", "_lift_place", "_lift_paint", "_lift_paint_over", "_lift_flush", "_go"):
        fn = getattr(opening, name)
        setattr(opening, name, lambda fn=fn, name=name: (seen.__setitem__(name, n[0]), fn())[1])
    opening._pieces = type(opening._pieces)(getattr(opening, f.__name__) for f in opening._pieces)

    def ready():
        n[0] += 1
        return opening._pieces is None
    assert wait_until(ready, 2)
    return seen


def test_a_split_opening_is_prepared_in_three_passes_of_the_loop_then_moves(clock, stage, split):
    # why: the snapshot, the picture with its shadow and the shown picture each cost 1-6 ms here (2-3x on the laptop);
    # in one step they made the click's step 4-10 ms. Each in a pass of its own, input and paints come in between.
    card = Card(stage, "up")
    opening = card.open()
    assert opening is not None and motion.opening_of(card) is opening
    assert opening.pixmap is None and opening.ghost is None and opening.anim is None    # nothing done in the click
    assert card.open() is None                                   # being prepared: a second open starts nothing
    seen = _passes(opening)
    assert list(seen) == ["_snapshot", "_picture", "_go"]
    assert seen["_snapshot"] < seen["_picture"] < seen["_go"]    # never two pieces in one pass
    assert opening.picture is not None and opening.ghost is not None and opening.anim.alive
    assert opening.ghost.opacity == 0.0 and not card.isVisible()
    clock.advance(400)
    assert card.isVisible() and motion.opening_of(card) is None and not _filters_left(opening)


def test_a_split_lifted_opening_is_six_pieces_and_shows_its_window_only_in_the_last(clock, stage, split, lifted):
    # why (M2.1-3): the lift's paint, its flush and its show each cost up to 3-4 ms at 150 % (a scrim: the whole window);
    # in one pass they made 8 ms, and its paint alone 3.5-4.5. Each in a pass of its own — the paint as two: the store
    # cleared with the shadow, then the snapshot over it; nothing composed (the lift paints the two itself).
    card = Card(stage, "slide")
    opening = card.open()
    assert opening.lift is None
    seen = _passes(opening)
    assert list(seen) == ["_snapshot", "_lift_place", "_lift_paint", "_lift_paint_over", "_lift_flush", "_go"]
    assert (seen["_snapshot"] < seen["_lift_place"] < seen["_lift_paint"] < seen["_lift_paint_over"]
            < seen["_lift_flush"] < seen["_go"])
    assert opening.picture is None
    assert opening.lift is not None and opening.lift.isVisible() and opening.lift.opacity() == 0.0
    clock.advance(400)
    assert card.isVisible()


def test_each_paint_piece_of_a_lifted_opening_draws_only_its_own_part(clock, stage, lifted, monkeypatch):
    from tests.qt.conftest import wait_until
    # why (M2.1-3): the snapshot is the costlier drawing (a scrim's whole window), so it is drawn once, by the "over"
    # piece; the "under" piece draws the shadow alone. Each call to the opening's _draw is recorded with its flags, and
    # the real _draw still does the drawing.
    calls = []
    real = motion.OverlayOpening._draw

    def record(self, p, shadow=True, snapshot=True):
        calls.append((shadow, snapshot))
        return real(self, p, shadow=shadow, snapshot=snapshot)

    monkeypatch.setattr(motion.OverlayOpening, "_draw", record)
    card = Card(stage, "up")
    card.shadow_name = "dialog"                                  # a shadow in the margins, so "under" has one to draw
    opening = card.open()
    assert wait_until(lambda: opening._pieces is None, 2)
    assert calls == [(True, False), (False, True)]               # under, over


def test_split_pieces_wait_the_gap_between_their_passes(clock, stage, split, monkeypatch):
    import time
    # why: a piece run straight after the last one (a 0 ms gap) leaves no input or paint between the pieces, which is
    # the point of splitting. The gap is raised to 60 ms so the check has room: half of it must pass between pieces.
    monkeypatch.setattr(motion, "PIECE_GAP_MS", 60)
    card = Card(stage, "up")
    opening = card.open()
    stamps = {}
    for name in ("_snapshot", "_picture", "_lift_place", "_lift_paint", "_lift_paint_over", "_lift_flush", "_go"):
        fn = getattr(opening, name)
        setattr(opening, name, lambda fn=fn, name=name: (stamps.__setitem__(name, time.perf_counter()), fn())[1])
    opening._pieces = type(opening._pieces)(getattr(opening, f.__name__) for f in opening._pieces)
    from tests.qt.conftest import wait_until
    assert wait_until(lambda: opening._pieces is None, 2)
    assert list(stamps) == ["_snapshot", "_picture", "_go"]
    assert stamps["_picture"] - stamps["_snapshot"] >= 0.030
    assert stamps["_go"] - stamps["_picture"] >= 0.030
    clock.advance(400)
    assert card.isVisible()


def test_a_close_while_the_opening_is_prepared_drops_it(clock, stage, split):
    from tests.qt.conftest import wait_until
    for close in (lambda c: c.hide(), lambda c: c.close()):
        card = Card(stage)
        opening = card.open()
        close(card)
        assert motion.opening_of(card) is None and opening.ended and not _filters_left(opening)
        wait_until(lambda: False, 0.05)                          # the pieces that were due run, and do nothing
        assert opening.ghost is None and opening.picture is None and not card.isVisible()


def test_a_key_while_the_opening_is_prepared_shows_it_at_once_and_goes_to_the_field(clock, stage, split):
    field = QLineEdit(stage)
    field.setGeometry(10, 10, 200, 30)
    field.show()
    stage.activateWindow()
    field.setFocus()
    QApplication.processEvents()
    card = Card(stage, "rise")
    opening = card.open()
    QTest.keyClick(field, Qt.Key.Key_A)
    assert card.isVisible() and opening.ended and opening.ghost is None and not _filters_left(opening)
    assert field.text() == "a"
    from tests.qt.conftest import wait_until
    wait_until(lambda: False, 0.05)
    assert opening.ghost is None and card.isVisible()          # no motion after it showed


def test_a_press_while_the_opening_is_prepared_shows_it_and_goes_to_what_the_user_saw(clock, stage, split):
    # intent keeper K6: in the 2-3 ms it is prepared nothing of the overlay is on screen yet: the press is the row's
    # under it (what the user saw), and the overlay shows at once, its opening done
    below = QPushButton("下の行", stage)
    below.setGeometry(200, 120, 320, 30)                       # where the card will be
    below.show()
    hits = []
    below.clicked.connect(lambda: hits.append(1))
    card = Card(stage)
    opening = card.open()
    at = below.geometry().center()
    win = stage.windowHandle()
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    from tests.qt.conftest import wait_until
    assert wait_until(lambda: opening.ended, 2) and card.isVisible() and opening.ghost is None
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert hits == [1] and card.clicks == [] and not _filters_left(opening)


def test_a_page_hidden_while_the_opening_is_prepared_shows_it_as_asked_without_the_motion(clock, stage, split):
    page = QWidget(stage)
    page.setGeometry(0, 0, 900, 640)
    page.show()
    card = Card(page, "slide")
    opening = card.open()
    page.hide()                                                  # a tab switch in the 2-3 ms it is prepared
    from tests.qt.conftest import wait_until
    assert wait_until(lambda: opening.ended, 2)
    assert opening.ghost is None and not card.isHidden() and not _filters_left(opening)
    page.show()
    assert card.isVisible()


def test_an_error_in_a_piece_is_reported_and_the_overlay_shown_without_the_motion(clock, stage, split, qt_errors):
    card = Card(stage)
    opening = card.open()

    def broken():
        raise ValueError("a painter's bug")
    opening._pieces[1] = broken                                  # the picture
    from tests.qt.conftest import wait_until
    assert wait_until(lambda: opening.ended, 2)
    assert card.isVisible() and opening.ghost is None and not _filters_left(opening)
    assert qt_errors and qt_errors[0][0] is ValueError
    qt_errors.clear()


def test_openings_are_split_on_real_time_and_whole_on_a_tests_time(clock):
    assert motion.SPLIT is None
    assert not motion._split()                                   # the clock fixture: test time, read at once
    clock.use_real_time()
    assert motion._split()
    clock.use_test_time(0.0)
