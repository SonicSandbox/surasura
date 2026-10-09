"""P-motion (M2.1 row 0; the window's spec 07 §7.5, 05 §5.11): can reduced motion follow Windows on Qt 6.11?

    python tests/qt/probe_motion.py

On Windows' own platform (not offscreen), a small window shown without activating:
1. reads Windows' *Show animations* (`SPI_GETCLIENTAREAANIMATION`) and prints it;
2. sends that window `WM_SETTINGCHANGE` with `SPI_SETCLIENTAREAANIMATION` (to it alone: **Windows' own value is never
   changed on this desktop**) and checks the app's native filter heard it and the mode read Windows again, within one
   turn of the event loop; a message with another code must not;
3. notes which Qt events the window got for it (whether Qt 6.11 turns it into a ThemeChange by itself);
4. times the filter: the GUI thread's cost per native message it sees (it sees every one).
Prints one JSON line. Exit 0 when (2) holds.
"""
import ctypes
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("SURASURA_TEST_ROOT", tempfile.mkdtemp(prefix="m21-pmotion-"))
os.environ.pop("QT_QPA_PLATFORM", None)


def main():
    if sys.platform != "win32":
        print(json.dumps({"skipped": "Windows only"}))
        return 0
    from PyQt6.QtCore import QEvent, QObject, Qt
    from PyQt6.QtWidgets import QApplication, QWidget
    from app.qt import motion

    app = QApplication(["probe-motion"])
    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    w.setGeometry(40, 40, 160, 60)
    w.show()
    app.processEvents()

    events = []

    class Spy(QObject):
        def eventFilter(self, obj, event):
            if obj is w:
                events.append(event.type().name if hasattr(event.type(), "name") else int(event.type()))
            return False
    spy = Spy()
    w.installEventFilter(spy)

    reads = []
    real = motion.windows_animations
    mode = motion.Mode(reader=lambda: reads.append(1) or real())
    f = motion.SettingChangeFilter(mode)
    app.installNativeEventFilter(f)
    value = real()
    hwnd = int(w.winId())
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.SendMessageW.restype = ctypes.c_ssize_t

    events.clear()
    base = len(reads)
    user32.SendMessageW(hwnd, motion.WM_SETTINGCHANGE, 0x0057, 0)            # SPI_SETWORKAREA: not ours
    app.processEvents()
    other_heard, other_reads = f.heard, len(reads)
    user32.SendMessageW(hwnd, motion.WM_SETTINGCHANGE, motion.SPI_SETCLIENTAREAANIMATION, 0)
    t0 = time.perf_counter()
    app.processEvents()
    turn_ms = (time.perf_counter() - t0) * 1000
    heard, read_again = f.heard, len(reads) > other_reads
    qt_events = sorted(set(str(e) for e in events))

    # the filter's cost: 2,000 harmless messages through the window's queue, with and without it
    def flood():
        for _ in range(2000):
            user32.PostMessageW(hwnd, 0x0400 + 7, 0, 0)                       # WM_USER + 7: nobody's
        t = time.perf_counter()
        app.processEvents()
        return (time.perf_counter() - t) * 1000
    with_filter = min(flood() for _ in range(3))
    app.removeNativeEventFilter(f)
    without = min(flood() for _ in range(3))
    w.close()
    out = {"show_animations": value, "other_code_heard": other_heard, "other_code_reread": other_reads > base,
           "heard": heard, "reread": read_again, "turn_ms": round(turn_ms, 2), "qt_events_seen": qt_events,
           "filter_cost_us_per_message": round((with_filter - without) * 1000 / 2000, 2)}
    print(json.dumps(out))
    ok = heard == 1 and read_again and other_heard == 0 and not out["other_code_reread"]
    print("P-MOTION " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
