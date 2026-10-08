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
from PyQt6.QtCore import QByteArray, QPoint, QRect, Qt
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
def lifted():
    motion.LIFT = True
    yield
    motion.LIFT = None
    motion._LIFTS.clear()                                        # the kept lifts belong to this test's window


def test_a_lifted_opening_is_a_see_through_window_moved_and_faded_then_the_overlay(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    card = Card(stage, "up")
    opening = card.open()
    lift = opening.lift
    assert lift is not None and opening.ghost is None and lift.isWindow()
    assert lift.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert bool(lift.windowFlags() & Qt.WindowType.WindowTransparentForInput)
    final = opening._lift_at
    assert lift.pos() == final + QPoint(0, theme.MOTION["buckets-rise"]) and lift.windowOpacity() == 0.0
    clock.advance(130)
    assert 0.0 < lift.windowOpacity() < 1.0 and final.y() < lift.pos().y() < final.y() + 40
    clock.advance(200)
    assert card.isVisible() and motion.opening_of(card) is None
    assert wait_until(lambda: sip.isdeleted(lift) or not lift.isVisible(), 2)       # gone a frame after the overlay


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


def test_a_lifted_opening_hands_its_window_to_the_next_opening(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    # why: making a top-level window each time costs a native window's birth; a kept one is only shown again
    card1 = Card(stage, "up")
    o1 = card1.open()
    lift = o1.lift
    clock.advance(400)                                           # the opening ends; its lift is given back a frame on
    assert wait_until(lambda: not lift.isVisible(), 2)
    assert lift.opening is None and lift in motion._LIFTS[id(lift.parentWidget())]
    card1.hide()
    card2 = Card(stage, "up")
    o2 = card2.open()
    assert o2.lift is lift and lift.opening is o2 and lift.isVisible()
    clock.advance(400)
    assert card2.isVisible()


def test_no_more_than_the_kept_number_of_lifts_stay(clock, stage, lifted):
    from tests.qt.conftest import wait_until
    # why: the pool is bounded: a window that once opened many overlays at once keeps at most LIFTS_KEPT hidden ones
    cards = [Card(stage, how) for how in ("up", "pop", "slide")]
    assert len(cards) == motion.LIFTS_KEPT + 1
    openings = [card.open() for card in cards]
    lifts = [o.lift for o in openings]
    assert len({id(w) for w in lifts}) == len(cards)             # each opening has a lift of its own
    top = lifts[0].parentWidget()                                # taken before the advance: the window they belong to
    clock.advance(400)
    assert wait_until(lambda: all(sip.isdeleted(w) or not w.isVisible() for w in lifts), 2)
    free = [w for w in motion._LIFTS.get(id(top), []) if not sip.isdeleted(w)]
    assert len(free) <= motion.LIFTS_KEPT
