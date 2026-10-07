"""The frame-time HUD (W2.1; the window's spec 07 §7.1 *Budgets*): how long the GUI thread is busy, and how long a frame
takes, measured in the running window.

- **Steps:** every stretch the GUI thread spends between waking and going back to wait (the event dispatcher's *awake*
  → *aboutToBlock*): one stretch holds every event it handled, so "no stretch over 4 ms" is "no step over 4 ms".
- **Frames:** each update of the window (its update request, painted and flushed).
- **Spans:** anything a view wraps in `hud.span(name)` (W2.2's painters), by name.
- **Late ticks:** a precise 2 ms timer, and how late each tick came. A step's own clock starts only once the GUI thread
  holds Python's lock again, so a wait *for* the lock (a busy worker thread) never shows as a long step; a tick that
  comes over 4 ms late does show it (W2.1 review A3).

Off (the default) it installs nothing and costs nothing. On with `SURASURA_HUD=1` or `--hud`: a small overlay in the
window's top-right corner shows p95 / max per kind and how many steps went over 4 ms; `report()` hands the same to
`tests/qt/measure_shell.py`. `SURASURA_SHELL_PROBE=<file>` makes the window write its first frame and idle memory to
that file and quit (the measuring script's way in).
"""
import json
import os
import sys
import time
from contextlib import contextmanager

from PyQt6.QtCore import QAbstractEventDispatcher, QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel

from app import theme
from app.qt import strings, style

STEP_BUDGET_MS = 4.0
TICK_MS = 2


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
        self._frame_at = None
        self.started = False
        self.label = None
        self._overlay = overlay
        self.ignore_before = 0.0                   # perf_counter: steps before it don't count (the first paint)

    # --- on / off ----------------------------------------------------------------------------------------------- #
    def start(self):
        dispatcher = QAbstractEventDispatcher.instance()
        dispatcher.awake.connect(self._awake)
        dispatcher.aboutToBlock.connect(self._block)
        self.window.installEventFilter(self)
        self._ticker = QTimer(self)
        self._ticker.setTimerType(Qt.TimerType.PreciseTimer)
        self._ticker.setInterval(TICK_MS)
        self._ticker.timeout.connect(self._tick)
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
        self.window.removeEventFilter(self)
        self._ticker.stop()
        self.started = False

    def _tick(self):
        now = time.perf_counter()
        if self._tick_at is not None and now >= self.ignore_before:
            self.late.append(max(0.0, (now - self._tick_at) * 1000 - TICK_MS))
            del self.late[:-20000]
        self._tick_at = now

    # --- measuring ---------------------------------------------------------------------------------------------- #
    def _awake(self):
        # The dispatcher says *awake* more than once in a stretch (measured: three times around one timer's slot):
        # the stretch starts at the first.
        if self._awake_at is None:
            self._awake_at = time.perf_counter()

    def _block(self):
        if self._awake_at is None:
            return
        now = time.perf_counter()
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

    def eventFilter(self, obj, event):
        if obj is self.window and event.type() == QEvent.Type.UpdateRequest:
            self._frame_at = time.perf_counter()
            QTimer.singleShot(0, self._frame_done)
        return False

    def _frame_done(self):
        if self._frame_at is not None:
            self.frames.append((time.perf_counter() - self._frame_at) * 1000)
            self._frame_at = None
            del self.frames[:-5000]

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


def wanted(argv=None):
    return os.environ.get("SURASURA_HUD") == "1" or "--hud" in (argv or [])


# --- the measuring script's way in (tests/qt/measure_shell.py) ------------------------------------------------------ #
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
        window.first_frame.connect(self._first_frame)

    def _first_frame(self):
        self.result["first_frame_ms"] = _process_age_ms()
        self.result["first_frame_wall"] = time.perf_counter()
        if self.hud is not None:
            self.hud.ignore_before = time.perf_counter()
        QTimer.singleShot(int(self.idle * 1000), self._finish)
        if os.environ.get("SURASURA_SHELL_PROBE_EXERCISE") == "1":
            QTimer.singleShot(500, self._exercise)

    def _exercise(self):
        """Row 8's run: ten tab switches, then 500 bar updates in a burst (one a millisecond), each from the event loop
        and each timed on its own (`tab-switch`, `bar-update` spans: a step is one of them). The loop's stretches and the
        late ticks are reported beside them: a burst of due timers is handled in one stretch, so a stretch can be many
        steps. `SURASURA_SHELL_PROBE_BUSY=1` adds a Python worker busy in 20 ms runs — CPU work in a thread, which the
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
        for i in range(500):
            QTimer.singleShot(600 + i, lambda i=i: timed("bar-update", lambda: self.window.show_status(
                snap._replace(lines=(f"{i} / 500",)))))

    def _finish(self):
        self.result["memory"] = _memory_mb()
        if self.hud is not None:
            self.result["hud"] = self.hud.report()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.result, f)
        finally:
            QApplication.instance().quit()
