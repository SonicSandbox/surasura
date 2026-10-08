"""The motion (M2.1; the window's spec 05 §5.3–5.5, §5.10, §5.11, A4 *Motion*): one clock, the mock's curve and
tokens, the overlay animator, the spinner, and reduced motion.

- **One clock** (`clock()`): everything that moves in the window moves on it — no `QPropertyAnimation`, no
  `QVariantAnimation`, no `QTimeLine`, no view timer driving a look (a test reads `app/qt/`). Its one precise timer runs
  only while something moves: with nothing moving there are no wake-ups. Every animation in a frame reads the same frame
  time. The clock records each frame's lateness and work (`clock().stats`), which the HUD reports.
- **The curve and the tokens** come from `app/theme.py` only: `EASE` (cubic-bezier(.2, .7, .3, 1), built here as Qt's
  `BezierSpline`), `FAST` 120 ms, `SLOW` 260 ms and the named durations in `MOTION`.
- **Overlays animate when they open, never on a refresh** (R4b-5, the mock's `.steady`): `open_overlay(widget, how)`
  moves a snapshot of the overlay with painted opacity (no scale, no `QGraphicsEffect`: 05 §5.3), then shows the overlay.
- **The spinner** (`Spinner`) is on the clock only while it runs, is shown and its window isn't minimised.
- **The freeze switch** (`app/qt/freeze.py`, tests and captures) jumps every animation to its end and leaves spinners
  still. **Reduced motion** (`app_motion`: Follow Windows · Full · Reduced, the user's; 05 §5.10) is separate: a move
  jumps, a fade is kept but no longer than `FAST`, a spinner is a static mark. *Follow* reads Windows' *Show animations*
  (`SPI_GETCLIENTAREAANIMATION`) at start and again when Windows says it changed (`WM_SETTINGCHANGE`): Qt 6.11 can't see
  it (05 §5.11); off Windows it answers "animations on".
- **Tests drive time** (`clock().use_test_time()`, `advance(ms)`): no test waits on real time for a motion.
"""
import sys
import time
from collections import deque

from PyQt6 import sip
from PyQt6.QtCore import (QAbstractNativeEventFilter, QEasingCurve, QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from app import theme
from app.qt import freeze, style

# The clock's frame: ~60 a second (a screen's usual refresh). The clock's own pace, not a motion's duration.
FRAME_MS = 16
KEPT = 2000                                      # frames kept in the stats


# --- the curve ------------------------------------------------------------------------------------------------------ #
def bezier_curve(points):
    """A CSS cubic-bezier(x1, y1, x2, y2) as Qt's BezierSpline (Qt solves x for the parameter, as CSS does)."""
    x1, y1, x2, y2 = points
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


_CURVES = {}


def curve(points=None):
    """The mock's curve (`theme.EASE`) unless other bezier points are named; `"linear"` for none. Built once each."""
    points = theme.EASE if points is None else points
    if points == "linear":
        return None
    key = tuple(points)
    if key not in _CURVES:
        _CURVES[key] = bezier_curve(key)
    return _CURVES[key]


def ease(t, points=None):
    """The eased value of progress `t` (0..1) on the mock's curve (or the named one)."""
    c = curve(points)
    t = min(1.0, max(0.0, t))
    return t if c is None else c.valueForProgress(t)


def duration(name):
    """A named duration (ms) from the motion tokens (`theme.MOTION`), or `fast` / `slow`."""
    if name == "fast":
        return theme.FAST
    if name == "slow":
        return theme.SLOW
    return theme.MOTION[name]


# --- reduced motion ------------------------------------------------------------------------------------------------ #
SPI_GETCLIENTAREAANIMATION = 0x1042
SPI_SETCLIENTAREAANIMATION = 0x1043
WM_SETTINGCHANGE = 0x001A
SETTINGS = ("follow", "full", "reduced")        # `app_motion` (05 §5.7, §5.10); anything else reads as follow


def windows_animations():
    """Windows' *Show animations* (Settings › Ease of Access › Display): True when on — and off Windows, where Qt 6.12
    will say (05 §5.11). A failed read answers True: motion is the default."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        value = wintypes.BOOL(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0)
        return bool(value.value) if ok else True
    except Exception:
        return True


class Mode(QObject):
    """Whether motion is reduced: the user's `app_motion` and, for *Follow*, Windows' own switch."""
    changed = pyqtSignal(bool)                  # reduced, after a change
    setting_changed = pyqtSignal()

    def __init__(self, reader=windows_animations, parent=None):
        super().__init__(parent)
        self._reader = reader
        self.setting = "follow"
        self.system = bool(reader())

    @property
    def reduced(self):
        if self.setting == "reduced":
            return True
        if self.setting == "full":
            return False
        return not self.system

    def set_setting(self, value):
        before, was = self.reduced, self.setting
        self.setting = value if value in SETTINGS else "follow"
        if self.setting != was:
            self.setting_changed.emit()
        if self.reduced != before:
            self.changed.emit(self.reduced)

    def system_changed(self):
        """Windows said its animation switch may have changed: read it again."""
        before = self.reduced
        self.system = bool(self._reader())
        if self.reduced != before:
            self.changed.emit(self.reduced)


class SettingChangeFilter(QAbstractNativeEventFilter):
    """Hears Windows' `WM_SETTINGCHANGE` for the animation switch (any window of the app) and tells the mode, on the
    next turn of the loop (never inside the native call). Without a mode of its own it tells the clock's."""

    def __init__(self, mode=None):
        super().__init__()
        self._mode = mode
        self.heard = 0
        self._msg = None
        if sys.platform == "win32":
            from ctypes import wintypes
            self._msg = wintypes.MSG

    @property
    def mode(self):
        return self._mode if self._mode is not None else clock().mode

    def nativeEventFilter(self, event_type, message):
        if self._msg is not None and event_type == b"windows_generic_MSG":
            try:
                msg = self._msg.from_address(int(message))
                if msg.message == WM_SETTINGCHANGE and msg.wParam == SPI_SETCLIENTAREAANIMATION:
                    self.heard += 1
                    QTimer.singleShot(0, lambda: self.mode.system_changed())
            except Exception:
                pass
        return False, 0


# --- the clock ------------------------------------------------------------------------------------------------------ #
class Animation:
    """One thing moving on the clock: `on_frame(value)` each frame (value 0..1, eased; a loop's raw phase), then
    `on_done()` once. `finish()` jumps it to its end; `stop()` ends it where it is (no more frames). **Every** end that
    isn't a finish — `stop()`, its owner hidden or deleted, an error in a frame — calls `on_end()` once, so whoever
    started it can always tidy up (M2.1 review A1)."""
    __slots__ = ("clock", "start", "duration", "on_frame", "on_done", "on_end", "curve", "repeat", "owner", "kind",
                 "alive")

    def __init__(self, clock, duration_ms, on_frame, on_done, curve_, repeat, owner, kind, on_end=None):
        self.clock, self.duration, self.on_frame, self.on_done = clock, max(1.0, float(duration_ms)), on_frame, on_done
        self.curve, self.repeat, self.owner, self.kind, self.on_end = curve_, repeat, owner, kind, on_end
        self.start = 0.0
        self.alive = True

    def finish(self):
        self.clock._end(self, finish=True)

    def stop(self):
        self.clock._end(self, finish=False)


class Stats:
    """Each frame's lateness (how long after it was due it came) and work (the clock's own callbacks), ms."""

    def __init__(self):
        self.late = deque(maxlen=KEPT)
        self.work = deque(maxlen=KEPT)
        self.frames = 0
        self.wakes = 0                           # timer wake-ups (0 while nothing moves)

    def reset(self):
        self.late.clear()
        self.work.clear()
        self.frames = 0
        self.wakes = 0


class Clock(QObject):
    """The window's one animation clock. Make it through `clock()`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anims = []
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._test_now = None
        self._due = None
        self._frame_now = None
        self.stats = Stats()
        self.mode = Mode(parent=self)
        self.on_frame_done = None                # the HUD's hook: called with (late_ms, work_ms) after each frame

    # --- time -------------------------------------------------------------------------------------------------- #
    def now(self):
        """The clock's time, ms (a test's own time while `use_test_time` is on)."""
        if self._frame_now is not None:
            return self._frame_now
        return self._test_now if self._test_now is not None else time.perf_counter() * 1000.0

    def use_test_time(self, start=0.0):
        """Tests: time moves only with `advance()`; the timer never runs."""
        self._test_now = float(start)
        self._timer.stop()

    def use_real_time(self):
        self._test_now = None
        if self._anims:
            self._start_timer()

    @property
    def test_time(self):
        return self._test_now is not None

    def advance(self, ms, step=FRAME_MS):
        """Tests: move the test time on by `ms`, a frame every `step` ms (the last frame lands on the end)."""
        assert self._test_now is not None, "use_test_time() first"
        end = self._test_now + ms
        while self._test_now < end - 1e-9:
            self._test_now = min(end, self._test_now + step)
            self._frame(self._test_now, late=0.0)

    @property
    def running(self):
        """True while the timer runs (something moves, on real time)."""
        return self._timer.isActive()

    @property
    def active(self):
        return [a for a in self._anims if a.alive]

    # --- animating ------------------------------------------------------------------------------------------ #
    def animate(self, duration_ms, on_frame, on_done=None, kind="move", points=None, owner=None, repeat=False,
                on_end=None):
        """Start one animation. `kind`: "move" (slides, rises, rows: reduced motion jumps it), "fade" (kept when
        reduced, at most FAST), "loop" (with `repeat`: a spinner; never started when reduced or frozen). `points`: the
        bezier (default the mock's EASE; "linear"). `owner`: a widget whose deletion or hiding ends it (checked each
        frame). `on_end`: called once on any end but a finish. -> Animation."""
        anim = Animation(self, duration_ms, on_frame, on_done, curve(points), repeat, owner, kind, on_end)
        reduced = self.mode.reduced
        if freeze.frozen() or (reduced and kind != "fade"):
            anim.alive = False
            if not repeat:
                self._call(anim, on_frame, 1.0)
                if on_done is not None:
                    self._call(anim, on_done)
            return anim
        if reduced:
            anim.duration = min(anim.duration, float(theme.FAST))
        anim.start = self.now()
        self._anims.append(anim)
        if self._test_now is None:
            self._start_timer()
        return anim

    def _start_timer(self):
        if not self._timer.isActive():
            self._due = time.perf_counter() * 1000.0 + FRAME_MS
            self._timer.start()

    def _end(self, anim, finish):
        if not anim.alive:
            return
        anim.alive = False
        if finish and not anim.repeat:
            self._call(anim, anim.on_frame, 1.0)
            if anim.on_done is not None:
                self._call(anim, anim.on_done)
        else:
            self._ended(anim)
        self._prune()

    def _ended(self, anim):
        """An end that isn't a finish: tell its starter once (never twice, never from inside its own error)."""
        fn, anim.on_end = anim.on_end, None
        if fn is not None:
            try:
                fn()
            except Exception:
                sys.excepthook(*sys.exc_info())

    def _prune(self):
        self._anims = [a for a in self._anims if a.alive]
        if not self._anims:
            self._timer.stop()

    def _call(self, anim, fn, *args):
        try:
            fn(*args)
        except Exception:
            anim.alive = False                     # a broken animation stops; the others go on; the error is reported
            sys.excepthook(*sys.exc_info())
            self._ended(anim)

    @staticmethod
    def _gone(owner):
        if owner is None:
            return False
        try:
            return sip.isdeleted(owner) or not owner.isVisible()
        except RuntimeError:
            return True

    def _tick(self):
        now = time.perf_counter() * 1000.0
        late = 0.0 if self._due is None else max(0.0, now - self._due)
        self._due = now + FRAME_MS
        self.stats.wakes += 1
        self._frame(now, late)

    def _frame(self, now, late):
        t0 = time.perf_counter()
        self._frame_now = now
        try:
            for anim in list(self._anims):
                if not anim.alive:
                    continue
                if self._gone(anim.owner):
                    anim.alive = False
                    self._ended(anim)
                    continue
                p = (now - anim.start) / anim.duration
                if anim.repeat:
                    self._call(anim, anim.on_frame, p % 1.0)
                elif p >= 1.0:
                    anim.alive = False
                    self._call(anim, anim.on_frame, 1.0)
                    if anim.on_done is not None:
                        self._call(anim, anim.on_done)
                else:
                    self._call(anim, anim.on_frame, anim.curve.valueForProgress(p) if anim.curve is not None else p)
        finally:
            self._frame_now = None
        self._prune()
        work = (time.perf_counter() - t0) * 1000.0
        self.stats.frames += 1
        self.stats.late.append(late)
        self.stats.work.append(work)
        if self.on_frame_done is not None:
            self.on_frame_done(late, work)


_clock = None


def clock():
    """The application's one clock (made on first use, parented to the QApplication)."""
    global _clock
    if _clock is None or sip.isdeleted(_clock):
        _clock = Clock(QApplication.instance())
    return _clock


def install_mode_filter(app=None):
    """Follow Windows' animation switch: Windows' `WM_SETTINGCHANGE` for it (a native filter, on Windows and only while
    the setting is *Follow*: it sees every message, ~8 µs each — P-motion), and a fresh read whenever the app comes back
    to the front (the switch lives in Windows' Settings, so the app is in the back when it changes). Idempotent."""
    app = app or QApplication.instance()
    state = getattr(app, "_surasura_motion", None)
    if state is None:
        state = {"filter": SettingChangeFilter(), "installed": False}
        app._surasura_motion = state
        app.applicationStateChanged.connect(
            lambda st: clock().mode.system_changed() if st == Qt.ApplicationState.ApplicationActive else None)
        clock().mode.changed.connect(lambda _r: _sync_mode_filter(app))
        clock().mode.setting_changed.connect(lambda: _sync_mode_filter(app))
    _sync_mode_filter(app)
    return state["filter"]


def _sync_mode_filter(app):
    state = getattr(app, "_surasura_motion", None)
    if state is None:
        return
    want = sys.platform == "win32" and clock().mode.setting == "follow"
    if want and not state["installed"]:
        app.installNativeEventFilter(state["filter"])
    elif not want and state["installed"]:
        app.removeNativeEventFilter(state["filter"])
    state["installed"] = want


# --- the overlay animator ------------------------------------------------------------------------------------------- #
# how -> (the duration's token, the distance's token or 0, the axis and the sign: where it comes from)
HOW = {
    "pop": ("overlay-pop", "pop-shift", "y", -1),       # search results, menus, popovers: from 4 px above
    "tray": ("tray-pop", "pop-shift", "y", -1),         # the New arrivals tray
    "rise": ("toast-rise", "toast-rise-px", "y", 1),    # a toast: from 12 px below
    "up": ("sheet", "buckets-rise", "y", 1),            # the Goal sheet, the buckets: from 40 px below
    "slide": ("side-panel", "side-panel-shift", "x", 1),  # the side panel: from 24 px right
    "dialog": ("dialog-card", "dialog-rise", "y", 1),   # a dialog's card: from 10 px below
    "fade": ("dialog-scrim", None, "y", 0),             # a scrim: a fade alone
}


# How an in-window overlay's opening is drawn (row 7, measured 2026-10-07): **lifted** — the composed picture in a
# top-level, see-through, input-transparent window that Windows' compositor fades and moves (≈ 0.3 ms of this thread a
# frame at 150 and 200 %) — or **painted** — a ghost child painting it with painted opacity (5–56 ms a frame for the
# Goal sheet, a side panel or a dialog). Lifted on Windows' own platform; painted elsewhere (offscreen tests, other
# systems until 3.1 checks them). None = choose; True / False = force (tests).
LIFT = None


def _lifted():
    if LIFT is not None:
        return bool(LIFT)
    return QGuiApplication.platformName() == "windows"


# How an in-window overlay's opening is prepared (M2.1-1, Sonic 2026-10-08: "Split it as you said"): in pieces — the
# overlay drawn (its snapshot); for the ghost, its shadow added (the picture); the picture shown and the motion started
# (a lift paints the shadow and the snapshot itself, in its own paint: no picture composed) — each in a pass of the GUI
# thread's loop of its own, the thread waiting PIECE_GAP_MS between them (input and paints come in between), instead of
# one step of 4-10 ms on this desktop (perhaps 10-25 ms on the laptop). The motion starts 2-3 ms later. None = split on
# real time, one step on a test's time (a test reads the opening at once); True / False = force.
SPLIT = None
PIECE_GAP_MS = 1


def _split():
    if SPLIT is not None:
        return bool(SPLIT)
    return not clock().test_time


class _Lift(QWidget):
    """The opening overlay lifted: its shadow and snapshot in a window of its own, above the main window and owned by it,
    see-through, never taking input or focus. Painted once, in its own paint (no picture composed first: M2.1-1); each
    frame only its opacity and place change."""

    def __init__(self, opening, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.NoDropShadowWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.opening = opening
        self.setObjectName("motionLift")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._painted = False                      # painted since it was last shown

    def showEvent(self, event):
        self._painted = False
        super().showEvent(event)

    def event(self, event):
        # Painted once a show (M2.1-2, measured 2026-10-08). Qt paints a shown window twice: Windows sends a see-through
        # (layered) window no WM_PAINT, so Qt's Windows plugin exposes it itself as it shows (qwindowswindow.cpp,
        # setVisible -> fireFullExpose) and that paint is the one put on screen; QWidgetPrivate::show_sys also posts every
        # shown widget an UpdateLater of its whole rect (qwidget.cpp: the paint a child, which gets no expose, needs).
        # Here it repaints the same picture (~1 ms at 150 %, 4+ at 250 %). Dropped once the expose has painted it; one
        # that comes first (no paint yet) goes through, and the expose then finds nothing to paint. (PyQt6 gives the
        # event no region; a lift's picture never changes while it is shown, so the one after a paint is that repaint.)
        if event.type() == QEvent.Type.UpdateLater and self._painted:
            self._painted = False                  # (only the one: a later UpdateLater paints as usual)
            return True
        return super().event(event)

    def paintEvent(self, _event):
        o = self.opening
        if o is None or o.pixmap is None or o.ended:   # (resting in the pool; or its overlay is shown under it, which
                                                       # may be gone: nothing of it is drawn — review H4)
            return
        p = QPainter(self)                         # (a see-through window's backing store starts clear)
        o._draw(p)
        p.end()
        self._painted = True


# The lifts kept for the next opening in the same window (row 7): making a top-level window is a native window's birth
# each time; a kept one, hidden, is only shown again. id(top window) -> the free lifts (children of it: they go with it).
_LIFTS = {}
LIFTS_KEPT = 2


def _take_lift(opening, top):
    free = _LIFTS.get(id(top))
    while free:
        lift = free.pop()
        if not sip.isdeleted(lift) and lift.parentWidget() is top:
            lift.opening = opening
            return lift
    return _Lift(opening, top)


def _give_back(lift):
    """A lift whose opening ended: hidden and kept for the window's next opening (at most LIFTS_KEPT), else deleted."""
    if sip.isdeleted(lift):
        return
    lift.hide()
    lift.opening = None
    top = lift.parentWidget()
    free = _LIFTS.setdefault(id(top), []) if top is not None else None
    if free is None or len(free) >= LIFTS_KEPT:
        lift.deleteLater()
        return
    free.append(lift)


class _Ghost(QWidget):
    """The opening overlay's stand-in: one picture — its shadow and its snapshot, composed once — moved, with painted
    opacity (CSS's opacity: the shadow never shows through the card as it fades). Transparent to the mouse: a press
    goes where Qt sends it, and the opening's input filter takes those that land on the overlay (`OverlayOpening`)."""

    def __init__(self, opening, parent):
        super().__init__(parent)
        self.opening = opening
        self.setObjectName("motionGhost")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.offset = QPoint(0, 0)
        self.opacity = 0.0

    def content_rect(self):
        """Where the overlay itself is inside the picture now (the ghost's coordinates)."""
        o = self.opening
        return QRect(self.offset + o.target_in_picture, o.widget_size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setOpacity(self.opacity)
        p.drawPixmap(self.offset, self.opening.picture)   # self.offset: the picture's top-left now
        p.end()


class OverlayOpening:
    """One overlay opening (made by `open_overlay`): the composed picture moved and faded in on the clock, then the
    overlay itself. **Every end tears it down** — finished, cancelled (a close), or cut short (its ghost hidden with a
    page, an error in a frame): nothing of it stays installed, and the overlay can open again."""

    def __init__(self, widget, how, shadow_name=None, on_done=None, focus=False):
        self.widget, self.how, self.shadow_name, self.on_done, self.focus = widget, how, shadow_name, on_done, focus
        self.ghost = None
        self.lift = None
        self.anim = None
        self.pixmap = None
        self.picture = None
        self.target_in_picture = QPoint()
        self.widget_size = None
        self._finisher = None
        self._pressed = None                       # the child a forwarded press went to (its release follows it)
        self._pieces = None                        # the preparation's pieces still to run (None: none left)
        self._landed_by_window = False             # ended by its window moving or resizing (its lift left behind at once)
        self.ended = False
        self.cancelled = False

    def start(self):
        w = self.widget
        dur_name, dist_name, axis, sign = HOW[self.how]
        dist = theme.MOTION[dist_name] * sign if dist_name else 0
        kind = "move" if dist else "fade"
        if clock().mode.reduced:
            dist, kind = 0, "fade"                 # reduced: no move; the fade kept, at most FAST
        self.delta = QPoint(dist, 0) if axis == "x" else QPoint(0, dist)
        w.destroyed.connect(self._widget_gone)
        if w.isWindow():                           # a top-level popup: the window's own opacity and place
            self._final_pos = w.pos()
            w.setWindowOpacity(0.0)
            w.move(self._final_pos + self.delta)
            w.show()
            self.anim = clock().animate(duration(dur_name), self._frame_window, self._done, kind=kind, owner=w,
                                        on_end=self._cut_short)
            return self
        self._dur_name, self._kind = dur_name, kind
        self._top = w.window()
        self._finisher = _InputFinisher(self)      # a key or a press while it is prepared shows it at once
        QApplication.instance().installEventFilter(self._finisher)
        self._lifts = _lifted()
        self._pieces = deque((self._snapshot, self._go) if self._lifts else (self._snapshot, self._picture, self._go))
        if _split():
            self._next_piece()
        else:
            while self._step():                    # a test's time: the pieces in this one step
                pass
        return self

    @property
    def live(self):
        """Being prepared or moving."""
        return self._pieces is not None or (self.anim is not None and self.anim.alive)

    def _next_piece(self):
        QTimer.singleShot(PIECE_GAP_MS, Qt.TimerType.PreciseTimer, self._run_piece)

    def _run_piece(self):
        """One piece of the preparation, in its own pass of the loop."""
        if self._step():
            self._next_piece()

    def _step(self):
        """Run the next piece; a piece's error is reported and the overlay shown without the motion. -> True when
        pieces remain."""
        if self.ended or not self._pieces:
            return False
        piece = self._pieces.popleft()
        try:
            piece()
        except Exception:
            self._pieces = None
            sys.excepthook(*sys.exc_info())
            self._cut_short()
            return False
        if self.ended:
            return False
        if self._pieces:
            return True
        self._pieces = None
        return False

    def _snapshot(self):
        """The first piece: the overlay drawn once, as it will look, at the device-pixel ratio."""
        w = self.widget
        w.ensurePolished()
        if w.layout() is not None:
            w.layout().activate()
        self.pixmap = w.grab()
        final = w.geometry()
        m = _shadow_margins(self.shadow_name)
        self._area = final.adjusted(-m[0], -m[1], m[2], m[3])    # the picture: the overlay and its shadow
        self.target_in_picture = final.topLeft() - self._area.topLeft()
        self.widget_size = final.size()
        self._size = self._area.size()

    def _picture(self):
        """The second, for the painted ghost only (it repaints each frame): its shadow added under it, in one picture.
        A lift paints the two itself, in its own paint."""
        self.picture = self._compose(self._size)

    def _go(self):
        """The last: the picture shown where the motion starts, and the motion started — unless its page went while it
        was prepared (then it is shown as asked, without the motion)."""
        w, area = self.widget, self._area
        parent = w.parentWidget()
        if parent is None or not parent.isVisible():
            self._cut_short()
            return
        if self._lifts:
            self._lift_at = parent.mapToGlobal(area.topLeft())   # the picture's place at the end, global
            self._origin = QPoint(0, 0)
            self.lift = _take_lift(self, self._top)
            self.lift.setGeometry(QRect(self._lift_at + self.delta, self._size))
            self.lift.setWindowOpacity(0.0)
            self.lift.show()
            owner = self.lift
        else:
            travel = area.united(area.translated(self.delta))    # the ghost: everywhere the picture goes
            self.ghost = _Ghost(self, parent)
            self.ghost.setGeometry(travel)
            self._origin = area.topLeft() - travel.topLeft()     # the picture's place at the end
            self.ghost.offset = self._offset(0.0)
            self.ghost.opacity = 0.0
            self._last = self._painted()
            self.ghost.show()
            self.ghost.raise_()
            owner = self.ghost
        self.anim = clock().animate(duration(self._dur_name), self._frame, self._done, kind=self._kind, owner=owner,
                                    on_end=self._cut_short)

    def content_global(self):
        """Where the overlay itself is on the screen now, while it opens."""
        if self.lift is not None and not sip.isdeleted(self.lift):
            return QRect(self.lift.pos() + self.target_in_picture, self.widget_size)
        g = self.ghost
        if g is not None and not sip.isdeleted(g):
            r = g.content_rect()
            return QRect(g.mapToGlobal(r.topLeft()), r.size())
        return QRect()

    def _compose(self, size):
        """The shadow and the snapshot in one picture, at the snapshot's device-pixel ratio."""
        dpr = self.pixmap.devicePixelRatio() or 1.0
        pic = QPixmap(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
        pic.setDevicePixelRatio(dpr)
        pic.fill(Qt.GlobalColor.transparent)
        p = QPainter(pic)
        self._draw(p)
        p.end()
        return pic

    def _draw(self, p):
        """The shadow and the snapshot at their place in the picture (into the ghost's picture, or the lift's window)."""
        r = QRect(self.target_in_picture, self.widget_size)
        if self.shadow_name:
            from app.qt import shadow
            shadow.paint(p, QRectF(r), self.shadow_name, covered=self._opaque(r))
        p.drawPixmap(r.topLeft(), self.pixmap)

    def _opaque(self, r):
        """The part of the snapshot that is surely opaque (a slice of the shadow wholly under it is never seen): the
        overlay's rect inside its corners' radius, when the overlay paints its whole background."""
        w = self.widget
        if not (w.autoFillBackground() or w.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)):
            return None
        inset = max(v for v in theme.RADII.values() if v < theme.RADII["pill"])   # the roundest card corner
        return QRectF(r).adjusted(inset, inset, -inset, -inset)

    def _painted(self):
        """The ghost's rect where the picture is now (its own coordinates)."""
        return QRect(self.ghost.offset, self._size)

    # --- frames ------------------------------------------------------------------------------------------------ #
    def _offset(self, v, _widget=None):
        """Where the picture is at value `v`: whole logical pixels, drawn with no smooth transform, so Qt places it on
        the nearest device pixel and never resamples it."""
        return self._origin + QPoint(round(self.delta.x() * (1.0 - v)), round(self.delta.y() * (1.0 - v)))

    def _frame(self, v):
        lift = self.lift
        if lift is not None:
            parent = self.widget.parentWidget() if not sip.isdeleted(self.widget) else None
            if parent is None or not parent.isVisible():
                if self.anim is not None and self.anim.alive:
                    self.anim.stop()               # its page went (a tab switch): cut short, as a ghost would be
                return
            if not sip.isdeleted(lift):
                lift.setWindowOpacity(v)           # the compositor blends it: nothing here repaints
                lift.move(self._lift_at + self._offset(v))
            return
        g = self.ghost
        if g is None or sip.isdeleted(g):
            return
        g.opacity = v
        g.offset = self._offset(v)
        now = self._painted()
        g.update(now.united(self._last))           # only what this frame changes: the last and the next place
        self._last = now

    def _frame_window(self, v):
        w = self.widget
        if sip.isdeleted(w):
            return
        w.setWindowOpacity(v)
        w.move(self._final_pos + QPoint(round(self.delta.x() * (1.0 - v)), round(self.delta.y() * (1.0 - v))))

    def _done(self):
        self._teardown(show=True)
        if self.on_done is not None:
            self.on_done()

    def _cut_short(self):
        """Ended without finishing (its ghost hidden with its page, stopped, an error in a frame): the overlay is shown
        as asked, without the motion — unless it was cancelled (closed)."""
        self._teardown(show=not self.cancelled)

    def finish(self):
        """Jump to the end now (a key or a press came during the opening): shown at once while it is prepared."""
        if self._pieces is not None:
            self._pieces = None
            self._done()
        elif self.anim is not None and self.anim.alive:
            self.anim.finish()

    def cancel(self):
        """The overlay was closed during its opening: no ghost, nothing shown."""
        self.cancelled = True
        if self.anim is not None and self.anim.alive:
            self.anim.stop()                       # -> _cut_short -> torn down, not shown
        self._teardown(show=False)

    def _widget_gone(self, *_args):
        self.cancel()

    def _teardown(self, show):
        if self.ended:
            return
        self.ended = True
        self._pieces = None
        if self._finisher is not None and self._pressed is None:
            self._finisher.remove()                # (kept while a forwarded press waits for its release)
        if self.ghost is not None and not sip.isdeleted(self.ghost):
            self.ghost.hide()
            self.ghost.deleteLater()
        self.ghost = None
        lift, self.lift = self.lift, None
        if lift is not None and not sip.isdeleted(lift):
            if show and not self._landed_by_window:   # the overlay paints first; the lift goes a frame later (no flash)
                QTimer.singleShot(FRAME_MS, lambda: _give_back(lift))
            else:
                _give_back(lift)
        w = self.widget
        if _OPENINGS.get(id(w)) is self:
            _OPENINGS.pop(id(w), None)
        if sip.isdeleted(w):
            return
        try:
            w.destroyed.disconnect(self._widget_gone)
        except (TypeError, RuntimeError):
            pass
        if w.isWindow():
            w.setWindowOpacity(1.0)                # cancelled or not, the window keeps no half-faded state
            w.move(self._final_pos)
            if not show:
                w.hide()
            return
        if not show:
            return
        _show(w, self.focus)

    def press(self, event):
        """A press (left, right, middle) on the opening overlay: finish it, then give the press to what the user saw
        under the pointer, at its place now. -> True when it was taken."""
        if self._pieces is not None:               # nothing of it on screen yet: the press is what's there; it shows after
            QTimer.singleShot(0, self.finish)
            return False
        content = self.content_global()
        at = event.globalPosition().toPoint()
        if content.isNull() or not content.contains(at):
            self.finish()                          # a press elsewhere: the opening ends, the press goes on as routed
            return False
        local = at - content.topLeft()
        self._pressed = w_pending = self.widget    # (set before the finish: the filter stays for the release)
        self.finish()
        w = self.widget
        if sip.isdeleted(w) or not w.isVisible():
            self._pressed = None
            if self._finisher is not None:
                self._finisher.remove()
            return True
        target = w.childAt(local) or w_pending
        self._pressed = target
        pos = target.mapFrom(w, local) if target is not w else local
        QApplication.sendEvent(target, QMouseEvent(event.type(), QPointF(pos), QPointF(target.mapToGlobal(pos)),
                                                   event.button(), event.buttons(), event.modifiers()))
        return True

    def release(self, event):
        """The release that follows a forwarded press goes to the same control. -> True when it was taken."""
        target, self._pressed = self._pressed, None
        if self._finisher is not None:
            self._finisher.remove()
        if target is None or sip.isdeleted(target):
            return False
        pos = target.mapFromGlobal(event.globalPosition().toPoint())
        QApplication.sendEvent(target, QMouseEvent(event.type(), QPointF(pos), QPointF(target.mapToGlobal(pos)),
                                                   event.button(), event.buttons(), event.modifiers()))
        return True


_FORWARDED = (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton)


class _InputFinisher(QObject):
    """App-wide, only while an overlay opens (and until a press it forwarded is released): a key finishes the opening
    and goes on to whatever has the focus after it; a press on the opening overlay is the overlay's (it finishes, then
    reaches the control under the pointer); any other press (the mouse's Back button too) finishes it and goes on as
    Qt routed it, so Esc's router sees the overlay open."""

    def __init__(self, opening):
        super().__init__()
        self.opening = opening
        self.installed = True

    def remove(self):
        if self.installed:
            self.installed = False
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            if self.opening._finisher is self:
                self.opening._finisher = None

    def eventFilter(self, obj, event):
        et = event.type()
        o = self.opening
        live = o.live
        if et == QEvent.Type.MouseButtonRelease and o._pressed is not None:
            return o.release(event)
        if not live:
            if o._pressed is None:
                self.remove()                      # nothing left to do: never a filter left behind
            return False
        if obj is getattr(o, "_top", None) and (et in (QEvent.Type.Resize, QEvent.Type.WindowStateChange)
                                                or (et == QEvent.Type.Move and o.lift is not None)):
            o._landed_by_window = True             # resized (the picture no longer fits) or moved from under a lift
            o.finish()                             # (a lift is a window of its own: it stays where it was) — land it now
            return False
        if et == QEvent.Type.KeyPress:
            o.finish()
            target = QApplication.focusWidget()
            if target is not None and target is not obj:
                QApplication.postEvent(target, QKeyEvent(et, event.key(), event.modifiers(), event.text(),
                                                         event.isAutoRepeat(), event.count()))
                return True
        elif et == QEvent.Type.MouseButtonPress:
            if event.button() in _FORWARDED:
                return o.press(event)
            o.finish()
        return False


_OPENINGS = {}


def _shadow_margins(name):
    if not name:
        return (0, 0, 0, 0)
    from app.qt import shadow
    return shadow.margins(name)


def _show(widget, focus):
    """An overlay at its place: shown, on top, and given the keyboard only when its opener asked."""
    widget.show()
    widget.raise_()
    if focus:                                      # only when the opener asks (a menu, the tray): never a toast
        widget.setFocus(Qt.FocusReason.PopupFocusReason)


def open_overlay(widget, how="pop", shadow_name=None, on_done=None, focus=False):
    """Show `widget` — an in-window overlay laid out at its place, or a top-level popup — with its opening motion,
    **only if it isn't shown already**: an overlay on screen never animates again (a refresh holds still, R4b-5). `how`:
    a key of HOW. `shadow_name`: its shadow (`theme.SHADOWS`), drawn under the snapshot. `focus`: it takes the keyboard
    when it shows (a menu, the tray; never a toast or search results). Close it with `hide()` / `close()` on an
    `Overlay` (or `cancel_opening`): a close during the opening drops it. -> the opening, or None when nothing animates
    (frozen, already shown)."""
    if widget.isVisible() or opening_of(widget) is not None:
        return None
    if freeze.frozen():
        _show(widget, focus)                       # as at an opening's end: the same stacking and focus
        if on_done is not None:
            on_done()
        return None
    opening = OverlayOpening(widget, how, shadow_name, on_done, focus)
    _OPENINGS[id(widget)] = opening
    opening.start()
    if opening.ended or not opening.live:
        _OPENINGS.pop(id(widget), None)
        return None
    return opening


def opening_of(widget):
    """The opening under way for `widget`, or None."""
    o = _OPENINGS.get(id(widget))
    return o if o is not None and o.widget is widget and not o.ended else None


def cancel_opening(widget):
    o = opening_of(widget)
    if o is not None:
        o.cancel()


class Overlay(QWidget):
    """An in-window overlay (the tray, the Goal sheet, the side panel, a popover, a toast's card): `open()` shows it
    with its motion, once; hiding or closing it during the opening drops the opening (Esc's router, a drag starting)."""
    how = "pop"
    shadow_name = None

    focus = False

    def open(self):
        return open_overlay(self, self.how, self.shadow_name, focus=self.focus)

    def setVisible(self, visible):
        if not visible:
            cancel_opening(self)
        super().setVisible(visible)

    def closeEvent(self, event):
        cancel_opening(self)                       # close() on an overlay still opening (hidden) never calls hide()
        super().closeEvent(event)


# --- the spinner ---------------------------------------------------------------------------------------------------- #
GLOW = 10                                       # px the pulse's glow reaches (theme.SHADOWS["bar-dot"]: blur 10)


class Spinner(QWidget):
    """A painted busy mark. `pulse`: the bottom bar's dot (7 px, the accent with its glow; its opacity 1 → .35 → 1 in
    1.4 s, ease-in-out: the mock's `.foot .dot.busy`); `spin`: an arc turning once in 1.2 s, linear (the mining mark).
    `set_running(True)` starts it; it is on the clock only while running, shown and its window not minimised; reduced
    motion and the freeze switch show it still. Not running: a faint dot (pulse) or nothing (spin)."""

    DOT = 7

    def __init__(self, kind="pulse", parent=None, size=None):
        super().__init__(parent)
        self.kind = kind
        self.running = False
        self.phase = 0.0
        self._anim = None
        self._watched = None
        side = size or (self.DOT + 2 * GLOW if kind == "pulse" else 14)   # room for the glow (2σ: its last 2 %)
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        clock().mode.changed.connect(self._sync)

    def set_running(self, on):
        on = bool(on)
        if on == self.running:
            return
        self.running = on
        self._sync()
        self.update()

    @property
    def on_clock(self):
        return self._anim is not None and self._anim.alive

    def _wanted(self):
        if not self.running or freeze.frozen() or clock().mode.reduced or not self.isVisible():
            return False
        top = self.window()
        return not (top is not None and top.isMinimized())

    def _sync(self, *_args):
        if sip.isdeleted(self):
            return
        if self._wanted():
            if not self.on_clock:
                period = duration("footer-pulse" if self.kind == "pulse" else "mining-spin")
                self._anim = clock().animate(period, self._on_frame, kind="loop", repeat=True, owner=self)
        elif self._anim is not None:
            self._anim.stop()
            self._anim = None
            self.phase = 0.0
            self.update()

    def _on_frame(self, phase):
        self.phase = phase
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        top = self.window()
        if top is not self._watched and top is not None:
            if self._watched is not None and not sip.isdeleted(self._watched):
                self._watched.removeEventFilter(self)
            top.installEventFilter(self)
            self._watched = top
        self._sync()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync()

    def eventFilter(self, obj, event):
        if obj is self._watched and event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.Hide,
                                                    QEvent.Type.Show):
            QTimer.singleShot(0, self._sync)
        return False

    def pulse_opacity(self):
        """The dot's opacity at this phase: 1 → .35 at the half → 1, each half on CSS's ease-in-out."""
        if not self.on_clock:
            return 1.0
        half = self.phase * 2.0
        if half < 1.0:
            return 1.0 - 0.65 * ease(half, theme.EASE_IN_OUT)
        return 0.35 + 0.65 * ease(half - 1.0, theme.EASE_IN_OUT)

    def paintEvent(self, _event):
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        if self.kind == "pulse":
            dot = QRectF(0, 0, self.DOT, self.DOT)
            dot.moveCenter(r.center())
            if self.running:
                p.setOpacity(self.pulse_opacity())
                from app.qt import shadow
                shadow.paint(p, dot, "bar-dot")
                p.setBrush(style.qcolor(c["accent"]))
            else:
                p.setBrush(style.qcolor(c["ink-faint"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(dot)
        elif self.running:
            from PyQt6.QtGui import QPen
            pen = QPen(style.qcolor(c["accent"]), max(1.5, r.width() / 8))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            inset = pen.widthF()
            arc = r.adjusted(inset, inset, -inset, -inset)
            start = -int(self.phase * 360 * 16) if self.on_clock else 90 * 16
            p.drawArc(arc, start, 270 * 16)
        p.end()
