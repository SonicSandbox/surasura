"""The frame-time HUD (W2.1; the window's spec 07 §7.1 *Budgets*): how long the GUI thread is busy, and how long a frame
takes, measured in the running window.

- **Steps:** every stretch the GUI thread spends between waking and going back to wait (the event dispatcher's *awake*
  → *aboutToBlock*): one stretch holds every event it handled, so "no stretch over 4 ms" is "no step over 4 ms".
- **Frames:** each update of a window (its update request or expose, painted and flushed) — **every window's (M4.1):**
  the main window's, the lift's (`motion._Lift`), the drag ghost's and every top-level popup's, each frame tagged with
  its window's kind (`main` · `lift` · `ghost` · `popup` · `window`). Seen through one application-wide event filter
  (about 1.5 µs an event on this desktop while the HUD is on); a frame ends where the next event that can never come
  inside a paint begins (a timer, a queued call, input, another frame), or where the loop goes back to wait. **A frame
  over `SLOW_MS` is given a cause** (`frame_cause`): Python's collector, or the late tick over it explained by
  `classify` (another thread, the machine, the timer, unexplained), else its own paint / flush (`paint`) or the clock's
  work in it (`step`).
- **Spans:** anything a view wraps in `hud.span(name)` (W2.2's painters), by name.
- **Late ticks:** a precise 2 ms timer, and how late each tick came. A step's own clock starts only once the GUI thread
  holds Python's lock again, so a wait *for* the lock (a busy worker thread) never shows as a long step; a tick that
  comes over 4 ms late does show it (W2.1 review A3). **M2.1 (row D):** each tick over 4 ms late is explained — what
  Python's collector, the GUI thread, the other threads and the machine did in that gap — and given a cause (`classify`).
- **Animation frames (M2.1):** the motion clock's frames — how late each came and its work — and, added to the paint
  that follows it, each animation frame's whole cost; a measuring script can tag them (`tag`) to read one motion apart.
  M4.1: the work lands in the frame that paints it, in whichever window — the first frame to begin before the clock's
  next one, or the one painted inside it (a `repaint()`: its paint is in the work); a clock frame that paints in no
  widget (the lift and a top-level popup move and fade in Windows' compositor,
  the ghost glides as a window) is a frame of its own, of the window that moved.
- **Start-up phases (M2.1 row D):** with the probe on, `mark(name)` records where the first frame's time goes (each
  phase's wall time, the process's CPU, page faults, bytes read, the machine's idle share).

Off (the default) it installs nothing and costs nothing. On with `SURASURA_HUD=1` or `--hud`: a small overlay in the
window's top-right corner shows p95 / max per kind and how many steps went over 4 ms; `report()` hands the same to
`tests/qt/measure_shell.py`. `SURASURA_SHELL_PROBE=<file>` makes the window write its first frame and idle memory to
that file and quit (the measuring script's way in).
"""
import gc
import json
import os
import sys
import threading
import time
from contextlib import contextmanager

from PyQt6 import sip
from PyQt6.QtCore import QAbstractEventDispatcher, QAbstractNativeEventFilter, QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QWindow
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from app import theme
from app.qt import strings, style

STEP_BUDGET_MS = 4.0
TICK_MS = 2
LONG_MS = 20.0                                   # a stretch this long is explained (row D)
SLOW_MS = 6.4                                    # M4.1's bar on this desktop: the laptop's 16 ms ÷ 2.5 — a frame over it
                                                 # is given a cause
KEEP = 20000                                     # frames and steps kept with their times (a bench may keep more)
_E = QEvent.Type
_FRAME_EVENTS = (_E.UpdateRequest, _E.Expose)
# events that never come inside a paint: one beginning ends the frame being painted (its paint and flush are done)
_ENDS = frozenset((_E.UpdateRequest, _E.Expose, _E.Timer, _E.MetaCall, _E.MouseMove, _E.MouseButtonPress,
                   _E.MouseButtonRelease, _E.MouseButtonDblClick, _E.Wheel, _E.KeyPress, _E.KeyRelease,
                   _E.DeferredDelete))
_POPUPS = (Qt.WindowType.Popup, Qt.WindowType.ToolTip, Qt.WindowType.Tool, Qt.WindowType.SplashScreen)


def p95(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


class Hud(QObject):
    def __init__(self, window, overlay=True, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.steps = []
        self.frames = []
        self.spans = {}
        self.over = []                              # (ms, when) of each step over the budget
        self.late = []                              # how late each tick of the 2 ms timer came, ms
        self._tick_at = None
        self._discard = False
        self._awake_at = None
        self.started = False
        self.label = None
        self._overlay = overlay
        self.ignore_before = 0.0                   # perf_counter: steps before it don't count (the first paint)
        self.counters = None                       # M2.1 row D: the late ticks explained (Windows; None elsewhere)
        self.gcwatch = None
        self.explained = []                        # one record per tick over 4 ms late
        self._tick_sample = None
        self.anim_ticks = []                       # (late, work) of each motion-clock frame, ms
        self.anim_frames = []                      # each animation frame's whole cost: the clock's work + its paint
        self.tag = None                            # a measuring script's label for the frames now (e.g. "pop")
        self.tagged = {}
        self.long = []                             # row D: each stretch over LONG_MS — its messages and sampled stacks
        self.sampler = None
        # M4.1: every window's frames, with their times — {"window", "name", "t0", "t1", "paint_ms", "work_ms", "ms",
        # "tag", "cause"} (t0 the clock frame's start when it carried one; "cause" set for a slow frame by
        # `explain_frames`) — and each counted step's (start, ms); a bench reads them by time
        self.frame_log = []
        self.step_log = []
        self.keep = KEEP
        self.late_spans = []                       # (before, now, record) of each explained late tick
        self._open = None                          # the frame being painted now
        self._pending = None                       # a clock frame not yet painted: (work, late, tag, start, end)
        self._sync = None                          # a window painted inside the clock's frame (a `repaint()`)
        self._clock = None
        self._app = None

    # --- on / off ----------------------------------------------------------------------------------------------- #
    def start(self):
        dispatcher = QAbstractEventDispatcher.instance()
        dispatcher.awake.connect(self._awake)
        dispatcher.aboutToBlock.connect(self._block)
        self._app = QApplication.instance()
        self._app.installEventFilter(self)         # every window's frames (M4.1), not the main window's alone
        self._ticker = QTimer(self)
        self._ticker.setTimerType(Qt.TimerType.PreciseTimer)
        self._ticker.setInterval(TICK_MS)
        self._ticker.timeout.connect(self._tick)
        self.counters = Counters()
        self.gcwatch = GcWatch().install()
        self.messages = MessageLog().install()
        if os.environ.get("SURASURA_HUD_SAMPLE") == "1":
            self.sampler = StallSampler(self).start()
        from app.qt import motion
        self._clock = motion.clock()
        self._clock.on_frame_done = self._clock_frame
        self._ticker.start()
        if self._overlay:
            self.label = QLabel(self.window)
            self.label.setObjectName("hud")
            self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            c = style.colours()
            self.label.setStyleSheet(f"QLabel#hud {{ background: {style.qss_colour(c['bg'])}; color: "
                                     f"{style.qss_colour(c['ink-dim'])}; border: 1px solid {style.qss_colour(c['line'])};"
                                     f" padding: 3px 6px; font-family: \"{theme.MONO[0]}\"; }}")
            self._refresh = QTimer(self)
            self._refresh.timeout.connect(self._show)
            self._refresh.start(500)
        self.started = True
        return self

    def stop(self):
        if not self.started:
            return
        dispatcher = QAbstractEventDispatcher.instance()
        try:
            dispatcher.awake.disconnect(self._awake)
            dispatcher.aboutToBlock.disconnect(self._block)
        except (TypeError, RuntimeError):
            pass
        if self._app is not None:
            self._app.removeEventFilter(self)
            self._app = None
        self._ticker.stop()
        if self.gcwatch is not None:
            self.gcwatch.remove()
        if getattr(self, "messages", None) is not None:
            self.messages.remove()
        if self.sampler is not None:
            self.sampler.stop()
        from app.qt import motion
        if motion.clock().on_frame_done == self._clock_frame:
            motion.clock().on_frame_done = None
        self.started = False

    def _tick(self):
        now = time.perf_counter()
        sample = self.counters.sample() if self.counters is not None else None
        if self._tick_at is not None and now >= self.ignore_before:
            late = max(0.0, (now - self._tick_at) * 1000 - TICK_MS)
            self.late.append(late)
            del self.late[:-20000]
            if late > STEP_BUDGET_MS:
                self._explain(late, self._tick_at, now, self._tick_sample, sample)
        self._tick_at = now
        self._tick_sample = sample

    def _explain(self, late, before, now, s0, s1):
        """What happened in the gap before a late tick (row D), and its cause."""
        rec = {"late_ms": round(late, 2), "at_ms": round((now - self.ignore_before) * 1000)}
        rec.update(self.counters.between(s0, s1) if self.counters is not None else {})
        gc_ms, gen, elsewhere = self.gcwatch.within(before, now) if self.gcwatch is not None else (0.0, None, False)
        rec.update(gc_ms=gc_ms, gc_gen=gen, gc_elsewhere=elsewhere)
        due = before + TICK_MS / 1000.0
        awake = self._awake_at
        rec["in_stretch_ms"] = round(max(0.0, (now - max(awake, due)) * 1000), 2) if awake is not None else None
        rec["threads"] = threading.active_count()
        if getattr(self, "messages", None) is not None:
            rec["messages"] = self.messages.within(before, now)
        rec["cause"] = classify(rec)
        self.explained.append(rec)
        del self.explained[:-500]
        self.late_spans.append((before, now, rec))      # M4.1: a slow frame under it reads its counters
        del self.late_spans[:-self.keep]

    def _clock_frame(self, late, work):
        self.anim_ticks.append((late, work))
        del self.anim_ticks[:-5000]
        now = time.perf_counter()
        if self._pending is not None:              # the clock's last frame painted nowhere before this one came
            self._paintless()
        if self._sync is not None:                 # it painted inside itself (`repaint()`): that window's frame, now —
            kind, name, p0 = self._sync            # its paint and flush are inside the work
            self._sync = None
            paint = min(work, (now - p0) * 1000)
            self._record(kind, name, now - work / 1000.0, now, paint, work - paint, self.tag)
            return
        self._pending = (work, late, self.tag, now - work / 1000.0, now)

    # --- measuring ---------------------------------------------------------------------------------------------- #
    def _awake(self):
        # The dispatcher says *awake* more than once in a stretch (measured: three times around one timer's slot):
        # the stretch starts at the first.
        if self._awake_at is None:
            self._awake_at = time.perf_counter()

    def _block(self):
        now = time.perf_counter()
        if self._open is not None:                 # the loop goes back to wait: the frame painted is done
            self._close(now)
        if self._pending is not None and self._moving() is not None:
            self._paintless()                      # the lift, the ghost or a popup moved in Windows: nothing to paint
        if self._awake_at is None:
            return
        started = self._awake_at
        ms = (now - started) * 1000
        self._awake_at = None
        if self._discard:                          # the measuring script's own work (scheduling its burst)
            self._discard = False
            return
        if started >= self.ignore_before:          # stretches that began after the first paint (start-up excluded)
            self.steps.append(ms)
            if ms > STEP_BUDGET_MS:
                self.over.append((round(ms, 2), now))
            del self.steps[:-5000]
            self.step_log.append((started, ms))
            del self.step_log[:-self.keep]
            if ms > LONG_MS and len(self.long) < 60:
                rec = {"at_ms": round((started - self.ignore_before) * 1000), "ms": round(ms, 1)}
                if getattr(self, "messages", None) is not None:
                    rec["messages"] = self.messages.within(started, now)
                if self.sampler is not None:
                    rec["stacks"] = self.sampler.take(started)
                self.long.append(rec)

    # --- every window's frames (M4.1) -------------------------------------------------------------------------- #
    def eventFilter(self, obj, event):
        t = event.type()
        if t in _ENDS:                             # (one test a call: this filter sees every event of the app)
            now = time.perf_counter()
            if self._open is not None:
                self._close(now)
            if t in _FRAME_EVENTS:
                kind = self._kind(obj, t)
                if kind is not None:
                    self._begin(kind, obj, now)
        return False

    def _kind(self, obj, t):
        """The kind of window a frame event paints, or None (not a window's frame)."""
        if obj is self.window:
            return "main"
        if isinstance(obj, QWidget):
            return self.window_kind(obj) if t == _E.UpdateRequest and obj.isWindow() else None
        if isinstance(obj, QWindow):
            if obj.objectName() == "motionLift":
                return "lift"
            if t == _E.Expose and obj.isExposed():     # a widget window's first paint (its show) comes as an expose
                w = _widget_of(obj)
                return self.window_kind(w) if w is not None else "window"
        return None

    def window_kind(self, w):
        """main · ghost (the drag's lifted row) · popup (menus, tooltips, any popup or tool window) · window."""
        if w is self.window or _same(w, self.window):
            return "main"
        if w.objectName() == "dragghost":
            return "ghost"
        return "popup" if w.windowType() in _POPUPS else "window"

    def _begin(self, kind, obj, now):
        if self._clock is not None and self._clock._frame_now is not None:
            if self._sync is None:                 # inside the clock's frame: part of its work (closed with it)
                self._sync = (kind, _name(obj), now)
            return
        work = None
        t0, tag = now, self.tag
        if self._pending is not None:              # the clock's frame lands in the frame that paints it, any window's
            work, _late, tag, t0, _end = self._pending
            self._pending = None
        self._open = (kind, _name(obj), now, t0, work, tag)
        QTimer.singleShot(0, self._frame_done)     # (a loop that never waits: its next turn ends it)

    def _frame_done(self):
        if self._open is not None:
            self._close(time.perf_counter())

    def _close(self, now):
        kind, name, p0, t0, work, tag = self._open
        self._open = None
        self._record(kind, name, t0, now, (now - p0) * 1000, work, tag)

    def _paintless(self):
        """The pending clock frame as a frame of its own: what it moved was a window (Windows composes it)."""
        work, _late, tag, t0, t1 = self._pending
        self._pending = None
        self._record(self._moving() or "none", "", t0, t1, 0.0, work, tag)

    def _moving(self):
        """The kind of window a paintless clock frame moved — a lift, the drag ghost or a popup shown — else None."""
        found = None
        for w in QGuiApplication.topLevelWindows():
            if not w.isVisible():
                continue
            name = w.objectName()
            if name == "motionLift":
                return "lift"
            if name == "dragghostWindow":
                found = "ghost"
            elif found is None and w.type() in _POPUPS:
                found = "popup"
        return found

    def _record(self, kind, name, t0, t1, paint, work, tag):
        total = paint + (work or 0.0)
        self.frame_log.append({"window": kind, "name": name, "t0": t0, "t1": t1, "paint_ms": round(paint, 3),
                               "work_ms": None if work is None else round(work, 3), "ms": round(total, 3), "tag": tag,
                               "cause": None})
        del self.frame_log[:-self.keep]
        if t0 < self.ignore_before:
            return
        self.frames.append(total)
        del self.frames[:-5000]
        if work is not None:                       # a motion-clock frame: its whole cost
            self.anim_frames.append(total)
            del self.anim_frames[:-5000]
            if tag:
                self.tagged.setdefault(tag, []).append(total)

    def frame_cause(self, rec):
        """Why a frame over SLOW_MS took its time (M4.1's bar): `gc` when Python's collector ran for half of it; else the
        late tick over it as `classify` reads its counters — `other-thread`, `machine`, `timer` or `unexplained` (the
        tick's wait behind this very frame set aside: that wait is the frame itself); else the frame's own — `paint` (its
        paint and flush) or `step` (the clock's work in it). None for a frame within the bar."""
        ms = rec["ms"]
        if ms <= SLOW_MS:
            return None
        t0, t1 = rec["t0"], rec["t1"]
        if self.gcwatch is not None and self.gcwatch.within(t0, t1)[0] >= 0.5 * ms:
            return "gc"
        best, overlap = None, 0.0
        for before, now, tick in reversed(self.late_spans):
            if now < t0:
                break
            o = min(now, t1) - max(before, t0)
            if o > overlap:
                best, overlap = tick, o
        if best is not None:
            cause = classify(dict(best, in_stretch_ms=0.0, gc_ms=0.0))
            if cause in ("other-thread", "machine", "timer", "unexplained"):
                return cause
        return "paint" if rec["paint_ms"] >= (rec["work_ms"] or 0.0) else "step"

    def explain_frames(self):
        """Each slow frame given its cause (once the late tick after it has come: a bench calls it before it reads).
        -> the frame log."""
        if self._open is not None:
            self._close(time.perf_counter())
        if self._pending is not None:
            self._paintless()
        for rec in self.frame_log:
            if rec["cause"] is None and rec["ms"] > SLOW_MS:
                rec["cause"] = self.frame_cause(rec)
        return self.frame_log

    def discard_current(self):
        """Leave the stretch running now out of the count (the measuring script calls it around its own set-up)."""
        self._discard = True
        self._tick_at = None

    @contextmanager
    def span(self, name):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.spans.setdefault(name, []).append((time.perf_counter() - t0) * 1000)

    def report(self):
        out = {"steps": {"n": len(self.steps), "p95_ms": round(p95(self.steps), 2),
                         "max_ms": round(max(self.steps, default=0.0), 2), "over_4ms": len(self.over)},
               "frames": {"n": len(self.frames), "p95_ms": round(p95(self.frames), 2),
                          "max_ms": round(max(self.frames, default=0.0), 2)}}
        out["spans"] = {k: {"n": len(v), "p95_ms": round(p95(v), 2), "max_ms": round(max(v), 2)}
                        for k, v in self.spans.items()}
        out["over"] = [ms for ms, _ in self.over[-20:]]
        out["over_at_ms"] = [round((at - self.ignore_before) * 1000) for _, at in self.over[-20:]]   # after the first paint
        out["late"] = {"n": len(self.late), "p95_ms": round(p95(self.late), 2),
                       "max_ms": round(max(self.late, default=0.0), 2),
                       "over_4ms": sum(1 for v in self.late if v > STEP_BUDGET_MS)}
        causes = {}
        for rec in self.explained:
            causes[rec["cause"]] = causes.get(rec["cause"], 0) + 1
        out["late"]["causes"] = causes
        out["late"]["explained"] = self.explained[-40:]
        late_t = [lt for lt, _w in self.anim_ticks]
        work_t = [w for _lt, w in self.anim_ticks]
        out["anim"] = {"ticks": len(self.anim_ticks), "tick_late_p95_ms": round(p95(late_t), 2),
                       "tick_late_max_ms": round(max(late_t, default=0.0), 2),
                       "work_p95_ms": round(p95(work_t), 2), "work_max_ms": round(max(work_t, default=0.0), 2),
                       "frames": len(self.anim_frames), "frame_p95_ms": round(p95(self.anim_frames), 2),
                       "frame_max_ms": round(max(self.anim_frames, default=0.0), 2)}
        out["tagged"] = {k: {"n": len(v), "p95_ms": round(p95(v), 2), "max_ms": round(max(v), 2)}
                         for k, v in self.tagged.items()}
        out["long"] = self.long[-30:]
        frames = [f for f in self.explain_frames() if f["t0"] >= self.ignore_before]
        windows = {}
        for f in frames:
            windows.setdefault(f["window"], []).append(f["ms"])
        out["windows"] = {k: {"n": len(v), "p95_ms": round(p95(v), 2), "max_ms": round(max(v), 2)}
                          for k, v in windows.items()}
        slow = sorted((f for f in frames if f["ms"] > SLOW_MS), key=lambda f: -f["ms"])
        by_cause = {}
        for f in slow:
            by_cause[f["cause"]] = by_cause.get(f["cause"], 0) + 1
        out["slow_frames"] = {"over_ms": SLOW_MS, "n": len(slow), "causes": by_cause,
                              "worst": [slow_line(f, self.ignore_before) for f in slow[:20]]}
        return out

    def _show(self):
        if self.label is None:
            return
        r = self.report()
        self.label.setText(strings.HUD_LINE.format(sp=r["steps"]["p95_ms"], sm=r["steps"]["max_ms"],
                                                   so=r["steps"]["over_4ms"], fp=r["frames"]["p95_ms"],
                                                   fm=r["frames"]["max_ms"]))
        self.label.adjustSize()
        self.label.move(self.window.width() - self.label.width() - 8, 8)
        self.label.raise_()
        self.label.show()


def slow_line(f, since=0.0):
    """One slow frame for a report: its time, window, cause, what moved (the tag) and where its time went."""
    return {"ms": round(f["ms"], 2), "window": f["window"], "name": f["name"], "cause": f["cause"], "tag": f["tag"],
            "paint_ms": round(f["paint_ms"], 2), "work_ms": None if f["work_ms"] is None else round(f["work_ms"], 2),
            "at_ms": round((f["t0"] - since) * 1000)}


def _name(obj):
    try:
        return obj.objectName()
    except RuntimeError:
        return ""


def _same(a, b):
    """The same Qt object (a wrapper made afresh for an object Qt made is another Python object)."""
    try:
        return a is b or (a is not None and b is not None and sip.unwrapinstance(a) == sip.unwrapinstance(b))
    except (TypeError, RuntimeError):
        return False


def _widget_of(window):
    """The top-level widget a widget window (`QWidgetWindow`) shows, or None."""
    for w in QApplication.topLevelWidgets():
        handle = w.windowHandle()
        if handle is not None and _same(handle, window):
            return w
    return None


def wanted(argv=None):
    return os.environ.get("SURASURA_HUD") == "1" or "--hud" in (argv or [])


# --- the late-tick diagnosis (M2.1 row D) ---------------------------------------------------------------------------- #
# For every tick of the 2 ms timer that comes over 4 ms late, what the process and the machine did in that gap: Python's
# collector (any thread), the GUI thread's and the other threads' CPU, the machine's idle share, the timer resolution;
# `classify` names a cause from those counters alone (a pure function: tests feed it made-up records).
CAUSES = ("gc", "step", "gui-busy", "other-thread", "machine", "timer", "unexplained", "unknown")


def classify(rec):
    """The cause of one late tick, from its counters (ms; None = not measured on this system).
    - gc: Python's collector ran for at least half the lateness (in any thread: it holds the lock).
    - step: the tick waited behind other work in the same stretch (a long step, already counted as one).
    - gui-busy: the GUI thread itself ran for at least half the lateness outside a counted stretch (Windows calling
      into the window while it waits: sent messages, hooks, accessibility).
    - other-thread: another thread of this process ran for at least half of it (Python's lock is then likely, not
      proven: a thread in Qt's own code holds no Python lock).
    - machine: nothing here ran and the machine's processors were mostly busy (another program had them).
    - timer: nothing ran and Windows' timer is coarse enough to explain it (its resolution ≥ half the lateness).
    - unexplained: nothing here ran, the machine was idle and the timer was fine."""
    late = rec.get("late_ms") or 0.0
    half = 0.5 * late
    if (rec.get("gc_ms") or 0.0) >= half:
        return "gc"
    if (rec.get("in_stretch_ms") or 0.0) >= half:
        return "step"
    gui, other, idle = rec.get("gui_ms"), rec.get("other_ms"), rec.get("idle_share")
    if gui is None or other is None:
        return "unknown"
    if gui >= half:
        return "gui-busy"
    if other >= half:
        return "other-thread"
    if idle is not None and idle < 0.25:
        return "machine"
    res = rec.get("res_ms")
    if res is not None and res >= half:
        return "timer"
    return "unexplained"


class Counters:
    """Windows' counters, read on the GUI thread: its own CPU cycles, the process's, the processors' idle cycles, the
    timer resolution. Off Windows (or if a call fails) every reading is None — never an error (05 §5.11)."""

    def __init__(self, calibrate=True):
        self.ok = False
        self.mhz = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32")
            self._k = k
            self._u64 = ctypes.c_uint64
            self._byref = ctypes.byref
            k.GetCurrentThread.restype = wintypes.HANDLE
            k.GetCurrentProcess.restype = wintypes.HANDLE
            k.QueryThreadCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_uint64)]
            k.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_uint64)]
            k.QueryIdleProcessorCycleTime.argtypes = [ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(ctypes.c_uint64)]
            self._thread = k.GetCurrentThread()
            self._process = k.GetCurrentProcess()
            self.cpus = os.cpu_count() or 1
            self._idle_buf = (ctypes.c_uint64 * self.cpus)()
            self._idle_len = wintypes.ULONG(ctypes.sizeof(self._idle_buf))
            nt = ctypes.WinDLL("ntdll")
            nt.NtQueryTimerResolution.argtypes = [ctypes.POINTER(wintypes.ULONG)] * 3
            self._nt = nt
            self._res = [wintypes.ULONG() for _ in range(3)]
            self._c = ctypes.c_uint64()
            # cycles per µs, measured (never a nominal MHz); a probe's marks measure it after the first frame instead
            self.mhz = self._calibrate() if calibrate else None
            self.ok = True
        except Exception:
            self.ok = False

    def _calibrate(self, ms=4.0):
        """The GUI thread's cycle counter against the clock over a short busy spin (the HUD's start only)."""
        try:
            k, c = self._k, self._c
            k.QueryThreadCycleTime(self._thread, self._byref(c))
            c0, t0 = c.value, time.perf_counter()
            while (time.perf_counter() - t0) * 1000 < ms:
                pass
            k.QueryThreadCycleTime(self._thread, self._byref(c))
            return (c.value - c0) / ((time.perf_counter() - t0) * 1e6) or None
        except Exception:
            return None

    def sample(self):
        """(perf_counter s, GUI-thread cycles, process cycles, idle cycles of all processors, timer resolution ms) or
        None off Windows."""
        if not self.ok:
            return None
        try:
            k, c = self._k, self._c
            k.QueryThreadCycleTime(self._thread, self._byref(c))
            gui = c.value
            k.QueryProcessCycleTime(self._process, self._byref(c))
            proc = c.value
            length = type(self._idle_len)(self._idle_len.value)
            k.QueryIdleProcessorCycleTime(self._byref(length), self._idle_buf)
            idle = sum(self._idle_buf)
            lo, hi, cur = self._res
            self._nt.NtQueryTimerResolution(self._byref(lo), self._byref(hi), self._byref(cur))
            return (time.perf_counter(), gui, proc, idle, cur.value / 10000.0)
        except Exception:
            return None

    def ms(self, cycles):
        return None if not self.mhz else cycles / (self.mhz * 1000.0)

    def between(self, a, b):
        """The counters' story between two samples: GUI thread ms, other threads ms, the machine's idle share."""
        if a is None or b is None or not self.mhz:
            return {"gui_ms": None, "other_ms": None, "idle_share": None, "res_ms": None}
        wall_ms = (b[0] - a[0]) * 1000.0
        gui = self.ms(b[1] - a[1])
        proc = self.ms(b[2] - a[2])
        idle = self.ms(b[3] - a[3])
        return {"gui_ms": round(gui, 2), "other_ms": round(max(0.0, proc - gui), 2),
                "idle_share": round(min(1.0, idle / (self.cpus * wall_ms)), 2) if wall_ms > 0 else None,
                "res_ms": round(b[4], 3)}


class MessageLog(QAbstractNativeEventFilter):
    """Windows' messages to the app's windows, by time (Windows only; nothing elsewhere): which ones came in a late tick's
    gap — a message Windows *sends* (another program asking the window something) runs inside the wait, outside any
    counted stretch."""

    def __init__(self):
        super().__init__()
        self.seen = []                           # (perf_counter, message id)
        self.app = None
        self._msg = None

    def install(self):
        if sys.platform == "win32":
            from PyQt6.QtWidgets import QApplication
            self.app = QApplication.instance()
            self.app.installNativeEventFilter(self)
        return self

    def remove(self):
        if self.app is not None:
            self.app.removeNativeEventFilter(self)
            self.app = None

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG":
                if self._msg is None:
                    from ctypes import wintypes
                    self._msg = wintypes.MSG
                self.seen.append((time.perf_counter(), self._msg.from_address(int(message)).message))
                if len(self.seen) > 20000:
                    del self.seen[:-10000]
        except Exception:
            pass
        return False, 0

    def within(self, t0, t1):
        """{message id (hex): count} seen in [t0, t1]."""
        out = {}
        for t, m in reversed(self.seen):
            if t < t0:
                break
            if t <= t1:
                key = hex(m)
                out[key] = out.get(key, 0) + 1
        return out


class StallSampler:
    """`SURASURA_HUD_SAMPLE=1` (row D, diagnosis only): a watching thread that, while a GUI-thread stretch has run over
    LONG_MS, reads the GUI thread's Python stack every few ms. A stack ending in `app.exec()` means Qt's own C++ held
    the time (painting, layout, fonts), not a Python callback. It takes Python's lock to look, so it is never on by
    default."""

    def __init__(self, hud, every_ms=4):
        self.hud = hud
        self.every = every_ms / 1000.0
        self.ident = threading.get_ident()
        self.samples = {}                        # stretch start -> [stack]
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name="hud-stall-sampler", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        import traceback
        while not self._stop.wait(self.every):
            start = self.hud._awake_at
            if start is None or (time.perf_counter() - start) * 1000 < LONG_MS:
                continue
            frame = sys._current_frames().get(self.ident)
            if frame is None:
                continue
            lines = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
                     for f in traceback.extract_stack(frame, limit=12)]
            got = self.samples.setdefault(start, [])
            if len(got) < 6 and (not got or got[-1] != lines):
                got.append(lines)
            if len(self.samples) > 200:
                for k in sorted(self.samples)[:100]:
                    self.samples.pop(k, None)

    def take(self, start):
        return self.samples.pop(start, [])


class GcWatch:
    """Python's collector: each collection's start, end, generation and thread (gc.callbacks)."""

    def __init__(self):
        self.events = []                      # (start s, end s, generation, on the GUI thread)
        self._open = {}
        self._gui = threading.get_ident()

    def __call__(self, phase, info):
        now = time.perf_counter()
        ident = threading.get_ident()
        if phase == "start":
            self._open[ident] = now
        else:
            start = self._open.pop(ident, now)
            self.events.append((start, now, info.get("generation"), ident == self._gui))
            del self.events[:-2000]

    def install(self):
        if self not in gc.callbacks:
            gc.callbacks.append(self)
        return self

    def remove(self):
        if self in gc.callbacks:
            gc.callbacks.remove(self)

    def within(self, t0, t1):
        """Milliseconds of collection overlapping [t0, t1], the highest generation, and whether any ran elsewhere."""
        total, gen, elsewhere = 0.0, None, False
        for start, end, g, on_gui in reversed(self.events):
            if end < t0:
                break
            overlap = min(end, t1) - max(start, t0)
            if overlap > 0:
                total += overlap
                gen = g if gen is None else max(gen, g)
                elsewhere = elsewhere or not on_gui
        return round(total * 1000.0, 2), gen, elsewhere


# --- the measuring script's way in (tests/qt/measure_shell.py) ------------------------------------------------------ #
MARKS = []                                       # (phase, perf_counter, process age ms, counters, faults + bytes read)
_mark_counters = []


def mark(name):
    """The end of one phase of the start (row D): recorded only while the probe is on (`SURASURA_SHELL_PROBE`)."""
    if not os.environ.get("SURASURA_SHELL_PROBE"):
        return
    if not _mark_counters:
        _mark_counters.append(Counters(calibrate=False))   # no spin inside the start it measures
    MARKS.append((name, time.perf_counter(), _process_age_ms(), _mark_counters[0].sample(), _faults_and_reads()))


def _faults_and_reads():
    """(page faults, bytes read) of this process so far, or None off Windows."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                       "OtherOperationCount", "ReadTransferCount",
                                                       "WriteTransferCount", "OtherTransferCount")]
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = wintypes.HANDLE
        io = IO()
        if not k.GetProcessIoCounters(k.GetCurrentProcess(), ctypes.byref(io)):
            return None
        mem = _memory_counts()
        return (mem, io.ReadTransferCount)
    except Exception:
        return None


def phases(marks=None, first_frame_ms=None):
    """The start's phases from the marks: each one's wall time, the process's CPU in it, its page faults and bytes read,
    and the machine's idle share — the first phase (process creation → `app.qt` imported) from the package's own
    timestamp. -> [dict]."""
    marks = MARKS if marks is None else marks
    if not marks:
        return []
    out = []
    try:
        import app.qt as qt_package
        name0, perf0, age0 = marks[0][0], marks[0][1], marks[0][2]
        if age0 is not None:
            q_age = age0 - (perf0 - qt_package.IMPORTED_AT) * 1000.0
            out.append({"phase": "python+app_entry", "ms": round(q_age, 1)})
            out.append({"phase": f"imports-to-{name0}", "ms": round(age0 - q_age, 1)})
    except Exception:
        pass
    counters = _mark_counters[0] if _mark_counters else None
    if counters is not None and counters.ok and not counters.mhz:
        counters.mhz = counters._calibrate()   # now, after the start
    for (_n0, _p0, a0, c0, f0), (n1, _p1, a1, c1, f1) in zip(marks, marks[1:]):
        row = {"phase": n1, "ms": round(a1 - a0, 1) if a0 is not None and a1 is not None else None}
        if counters is not None and c0 is not None and c1 is not None:
            between = counters.between(c0, c1)
            row["cpu_ms"] = round(counters.ms(c1[2] - c0[2]), 1)
            row["idle_share"] = between["idle_share"]
        if f0 is not None and f1 is not None:
            row["faults"] = f1[0] - f0[0] if f0[0] is not None and f1[0] is not None else None
            row["read_kb"] = round((f1[1] - f0[1]) / 1024)
        out.append(row)
    return out


def _memory_counts():
    """Page faults so far (Windows), or None."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if not psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return None
        return pmc.PageFaultCount
    except Exception:
        return None


def _process_age_ms():
    """Milliseconds since this process was created (Windows: GetProcessTimes), or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.GetProcessTimes.restype = wintypes.BOOL
        k.GetSystemTimePreciseAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(k.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(exited),
                                 ctypes.byref(kernel), ctypes.byref(user)):
            return None
        now = wintypes.FILETIME()
        k.GetSystemTimePreciseAsFileTime(ctypes.byref(now))

        def ticks(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return (ticks(now) - ticks(created)) / 10000.0
    except Exception:
        return None


def _memory_mb():
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t)]
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if not psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return None
        return {"private_mb": round(pmc.PrivateUsage / 1048576, 1), "working_set_mb": round(pmc.WorkingSetSize / 1048576, 1)}
    except Exception:
        return None


class Probe(QObject):
    """With `SURASURA_SHELL_PROBE=<file>`: the first frame's age, then (after `idle` seconds, and `actions`) the idle
    memory and the HUD's report, written to the file; then the window quits."""

    def __init__(self, window, path, hud=None, idle=None, parent=None):
        super().__init__(parent or window)
        self.window, self.path, self.hud = window, path, hud
        self.idle = float(os.environ.get("SURASURA_SHELL_PROBE_IDLE", "10")) if idle is None else idle
        self.result = {"first_frame_ms": None}
        if hud is not None:
            # nothing counts until the first paint (row D: the window's first show is start-up, and its ~80 ms stretch
            # had read as a late tick after it — W2.1's and the kit's "late max")
            hud.ignore_before = float("inf")
        window.first_frame.connect(self._first_frame)

    def _first_frame(self):
        mark("flushed")
        self.result["first_frame_ms"] = _process_age_ms()
        if os.environ.get("SURASURA_GC_FREEZE") == "1":  # row D's A/B (measure_shell.py --gc-freeze): measuring only
            gc.freeze()
        self.result["first_frame_wall"] = time.perf_counter()
        if self.hud is not None:
            self.hud.ignore_before = time.perf_counter()
        QTimer.singleShot(int(self.idle * 1000), self._finish)
        if os.environ.get("SURASURA_SHELL_PROBE_EXERCISE") == "1":
            QTimer.singleShot(500, self._exercise)

    def _exercise(self):
        """Row 8's run: ten tab switches, then 500 bar updates in a burst (one a millisecond, each set off as the last
        ends: M2.1 row D), each from the event loop and each timed on its own (`tab-switch`, `bar-update` spans: a step
        is one of them). The loop's stretches and the late ticks are reported beside them. `SURASURA_SHELL_PROBE_PILED=1`
        schedules the 500 at once (W2.1's way: on a busy machine due timers pile into one stretch). `SURASURA_SHELL_PROBE_BUSY=1` adds a Python worker busy in 20 ms runs — CPU work in a thread, which the
        threading rule forbids (04 §4.1: processes do CPU work) — to show what it would cost (review A3)."""
        if os.environ.get("SURASURA_SHELL_PROBE_BUSY") == "1":
            import threading

            def busy():
                end = time.perf_counter() + 2.0
                while time.perf_counter() < end:
                    t = time.perf_counter()
                    while time.perf_counter() - t < 0.02:
                        sum(range(200))
                    time.sleep(0.005)
            threading.Thread(target=busy, name="hud-busy", daemon=True).start()
        hud = self.hud

        def timed(name, fn):
            if hud is None:
                fn()
                return
            with hud.span(name):
                fn()
        if hud is not None:
            hud.discard_current()                  # scheduling 510 timers is the script's own work, not the window's
        names = list(self.window.tab_buttons)
        for i in range(10):
            QTimer.singleShot(40 * i, lambda n=names[i % len(names)]: timed("tab-switch", lambda: self.window.show_tab(n)))
        snap = self.window.services.status.snapshot()
        if os.environ.get("SURASURA_SHELL_PROBE_PILED") == "1":
            # W2.1's burst (row D's A/B): 500 timers due 1 ms apart, all set at once — on a late or busy machine several
            # come due together and one stretch handles them all, so a stretch reads as many steps
            for i in range(500):
                QTimer.singleShot(600 + i, lambda i=i: timed("bar-update", lambda: self.window.show_status(
                    snap._replace(lines=(f"{i} / 500",)))))
            return

        def update(i=0):
            # M2.1 row D: each update sets the next one off 1 ms after it ends, as a real bar's are (the status service
            # sends a few a second, never a queue of 500)
            if i == 0:
                self.result["burst"] = [time.perf_counter(), None]
            timed("bar-update", lambda: self.window.show_status(snap._replace(lines=(f"{i} / 500",))))
            if i + 1 < 500:
                QTimer.singleShot(1, lambda: update(i + 1))
            else:
                self.result["burst"][1] = time.perf_counter()
                self.window.show_status(snap)              # the bar idle again: its spinner stops
        QTimer.singleShot(600, update)

    def _finish(self):
        self.result["memory"] = _memory_mb()
        self.result["phases"] = phases()
        if self.hud is not None:
            self.result["hud"] = self.hud.report()
            burst = self.result.pop("burst", None)
            if burst and burst[1]:
                outside = [ms for ms, end in self.hud.over if not (burst[0] <= end - ms / 1000.0 <= burst[1])]
                self.result["hud"]["steps"]["over_4ms_outside_burst"] = len(outside)
                self.result["hud"]["steps"]["max_ms_outside_burst"] = round(max(outside, default=0.0), 2)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.result, f)
        finally:
            QApplication.instance().quit()
