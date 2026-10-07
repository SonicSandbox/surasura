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
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QPainter
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
        before = self.reduced
        self.setting = value if value in SETTINGS else "follow"
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
    `on_done()` once. `finish()` jumps it to its end; `stop()` ends it where it is (no more callbacks)."""
    __slots__ = ("clock", "start", "duration", "on_frame", "on_done", "curve", "repeat", "owner", "kind", "alive")

    def __init__(self, clock, duration_ms, on_frame, on_done, curve_, repeat, owner, kind):
        self.clock, self.duration, self.on_frame, self.on_done = clock, max(1.0, float(duration_ms)), on_frame, on_done
        self.curve, self.repeat, self.owner, self.kind = curve_, repeat, owner, kind
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
    def animate(self, duration_ms, on_frame, on_done=None, kind="move", points=None, owner=None, repeat=False):
        """Start one animation. `kind`: "move" (slides, rises, rows: reduced motion jumps it), "fade" (kept when
        reduced, at most FAST), "loop" (with `repeat`: a spinner; never started when reduced or frozen). `points`: the
        bezier (default the mock's EASE; "linear"). `owner`: a widget whose deletion or hiding ends it. -> Animation."""
        anim = Animation(self, duration_ms, on_frame, on_done, curve(points), repeat, owner, kind)
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
        if owner is not None:
            try:
                owner.destroyed.connect(lambda *_a, a=anim: self._end(a, finish=False))
            except (TypeError, RuntimeError):
                pass
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
        self._prune()

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
    """Listen for Windows' animation switch (Follow Windows). -> the filter (kept by the app)."""
    app = app or QApplication.instance()
    existing = getattr(app, "_surasura_motion_filter", None)
    if existing is not None:
        return existing
    f = SettingChangeFilter()
    app.installNativeEventFilter(f)
    app._surasura_motion_filter = f
    return f


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


class _Ghost(QWidget):
    """The opening overlay's stand-in: its snapshot (and shadow), moved, with painted opacity. It takes the mouse, so a
    press during the opening reaches what the user saw under the pointer (`OverlayOpening.forward`)."""

    def __init__(self, opening, parent):
        super().__init__(parent)
        self.opening = opening
        self.setObjectName("motionGhost")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.offset = QPoint(0, 0)
        self.opacity = 0.0

    def content_rect(self):
        o = self.opening
        return QRect(o.target_in_ghost.topLeft() + self.offset, o.target_in_ghost.size())

    def paintEvent(self, _event):
        o = self.opening
        p = QPainter(self)
        p.setOpacity(self.opacity)
        r = self.content_rect()
        if o.shadow_name:
            from app.qt import shadow
            shadow.paint(p, QRectF(r), o.shadow_name)
        p.drawPixmap(r.topLeft(), o.pixmap)
        p.end()

    def mousePressEvent(self, event):
        self.opening.forward(self, event)

    def mouseReleaseEvent(self, event):
        self.opening.forward(self, event)


class OverlayOpening:
    """One overlay opening (made by `open_overlay`): the snapshot moved and faded in on the clock, then the overlay."""

    def __init__(self, widget, how, shadow_name=None, on_done=None, focus=False):
        self.widget, self.how, self.shadow_name, self.on_done, self.focus = widget, how, shadow_name, on_done, focus
        self.ghost = None
        self.anim = None
        self.pixmap = None
        self.target_in_ghost = QRect()
        self._finisher = None
        self._pressed = None                       # the child a forwarded press went to (its release follows it)
        self.ended = False

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
            self.anim = clock().animate(duration(dur_name), self._frame_window, self._done, kind=kind, owner=w)
            return self
        w.ensurePolished()
        if w.layout() is not None:
            w.layout().activate()
        self.pixmap = w.grab()                     # once: the overlay as it will look, at the device-pixel ratio
        final = w.geometry()
        m = _shadow_margins(self.shadow_name)
        area = final.adjusted(-m[0], -m[1], m[2], m[3])
        area = area.united(area.translated(self.delta))
        self.ghost = _Ghost(self, w.parentWidget())
        self.ghost.setGeometry(area)
        self.target_in_ghost = QRect(final.topLeft() - area.topLeft(), final.size())
        self.ghost.offset = QPoint(self.delta)
        self.ghost.opacity = 0.0
        self._last = self._painted(self.ghost.content_rect())
        self.ghost.show()
        self.ghost.raise_()
        self._finisher = _InputFinisher(self)
        QApplication.instance().installEventFilter(self._finisher)
        self.anim = clock().animate(duration(dur_name), self._frame, self._done, kind=kind, owner=self.ghost)
        return self

    def _offset(self, v, _widget=None):
        """Where the snapshot is at value `v`: whole logical pixels, drawn with no smooth transform, so Qt places it on
        the nearest device pixel and never resamples it (crisp at 125 / 150 / 175 %)."""
        return QPoint(round(self.delta.x() * (1.0 - v)), round(self.delta.y() * (1.0 - v)))

    def _painted(self, content):
        """The ghost's painted rect for a content rect: the snapshot and its shadow."""
        m = _shadow_margins(self.shadow_name)
        return content.adjusted(-m[0], -m[1], m[2], m[3])

    # --- frames ------------------------------------------------------------------------------------------------ #
    def _frame(self, v):
        g = self.ghost
        if g is None or sip.isdeleted(g):
            return
        g.opacity = v
        g.offset = self._offset(v, g)
        now = self._painted(g.content_rect())
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

    def finish(self):
        """Jump to the end now (a key or a press came during the opening)."""
        if self.anim is not None and self.anim.alive:
            self.anim.finish()

    def cancel(self):
        """The overlay was closed during its opening: no ghost, nothing shown."""
        if self.anim is not None:
            self.anim.stop()
        self._teardown(show=False)

    def _widget_gone(self, *_args):
        self.cancel()

    def _teardown(self, show):
        if self.ended:
            return
        self.ended = True
        if self._finisher is not None:
            QApplication.instance().removeEventFilter(self._finisher)
            self._finisher = None
        if self.ghost is not None and not sip.isdeleted(self.ghost):
            self.ghost.hide()
            self.ghost.deleteLater()
        w = self.widget
        _OPENINGS.pop(id(w), None)
        if not show or sip.isdeleted(w):
            return
        if w.isWindow():
            w.setWindowOpacity(1.0)
            w.move(self._final_pos)
            return
        w.show()
        w.raise_()
        if self.focus:                             # only when the opener asks (a menu, the tray): never a toast
            w.setFocus(Qt.FocusReason.PopupFocusReason)

    def forward(self, ghost, event):
        """A press (or its release) on the ghost: finish the opening, then hand it to what the user saw under the
        pointer, in the overlay at its place (the press is never lost to the window beneath)."""
        w = self.widget
        if event.type() == QEvent.Type.MouseButtonPress:
            local = event.position().toPoint() - ghost.content_rect().topLeft()
            self.finish()
            if sip.isdeleted(w) or not w.isVisible() or not w.rect().contains(local):
                return
            target = w.childAt(local) or w
            self._pressed = target
            pos = target.mapFrom(w, local) if target is not w else local
        else:
            target = self._pressed
            self._pressed = None
            if target is None or sip.isdeleted(target):
                return
            pos = target.mapFromGlobal(event.globalPosition().toPoint())
        QApplication.sendEvent(target, QMouseEvent(event.type(), QPointF(pos), QPointF(target.mapToGlobal(pos)),
                                                   event.button(), event.buttons(), event.modifiers()))


class _InputFinisher(QObject):
    """During an opening: a key or a press anywhere finishes it first. A key goes on to whatever has the focus after
    it (the overlay, usually); a press goes on as Qt routed it (a press on the ghost is the ghost's to forward)."""

    def __init__(self, opening):
        super().__init__()
        self.opening = opening

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.KeyPress:
            self.opening.finish()
            target = QApplication.focusWidget()
            if target is not None and target is not obj:
                QApplication.postEvent(target, QKeyEvent(et, event.key(), event.modifiers(), event.text(),
                                                         event.isAutoRepeat(), event.count()))
                return True
        elif et == QEvent.Type.MouseButtonPress and obj is not self.opening.ghost:
            self.opening.finish()
        return False


_OPENINGS = {}


def _shadow_margins(name):
    if not name:
        return (0, 0, 0, 0)
    from app.qt import shadow
    return shadow.margins(name)


def open_overlay(widget, how="pop", shadow_name=None, on_done=None, focus=False):
    """Show `widget` — an in-window overlay laid out at its place, or a top-level popup — with its opening motion,
    **only if it isn't shown already**: an overlay on screen never animates again (a refresh holds still, R4b-5). `how`:
    a key of HOW. `shadow_name`: its shadow (`theme.SHADOWS`), drawn under the snapshot. `focus`: it takes the keyboard
    when it shows (a menu, the tray; never a toast or search results). Close it with `hide()` /
    `close()` on an `Overlay` (or `cancel_opening`): a close during the opening drops it. -> the opening, or None when
    nothing animates (frozen, already shown)."""
    if widget.isVisible() or id(widget) in _OPENINGS:
        return None
    if freeze.frozen():
        widget.show()
        if on_done is not None:
            on_done()
        return None
    opening = OverlayOpening(widget, how, shadow_name, on_done, focus)
    _OPENINGS[id(widget)] = opening
    opening.start()
    if opening.anim is None or not opening.anim.alive:
        _OPENINGS.pop(id(widget), None)
        return None
    return opening


def opening_of(widget):
    """The opening under way for `widget`, or None."""
    o = _OPENINGS.get(id(widget))
    return o if o is not None and o.widget is widget else None


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
        side = size or (self.DOT + 2 * 6 if kind == "pulse" else 14)
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
