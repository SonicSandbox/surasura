"""P-text with the real shell (W2.1 row 9; the window's spec 07 §7.5, 08 G1.2-21): how long a live theme switch and a
live text-size switch take with the shell's widgets alive, to the window painted again.

    python tests/qt/probe_text.py [--offscreen] [--runs 5]

The window is built on Windows' own platform (real fonts) but never put on the screen (`WA_DontShowOnScreen`): it lays
out and paints into its backing store as a shown one does, and nothing opens on the desktop. Each switch is timed from
the call to the window rendered again (`grab()`, every widget painted). Prints one JSON line. Under ~300 ms each, the
shell switches live (`shell.LIVE_LOOK`); over it, *Restart to apply*. A temp `SURASURA_TEST_ROOT` is set (and
checked) first: never the real settings or local data.
"""
import argparse
import json
import os
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    os.environ["SURASURA_TEST_ROOT"] = tempfile.mkdtemp(prefix="w21-ptext-")
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    else:
        os.environ.pop("QT_QPA_PLATFORM", None)
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QWidget
    from app import path_utils
    assert path_utils.get_local_data_path().startswith(os.environ["SURASURA_TEST_ROOT"])
    from app.qt import shell

    app = QApplication(["probe-text"])
    services = shell.Services()
    win = shell.open_window(app, services)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1280, 800)
    win.show()
    app.processEvents()
    win.grab()
    widgets = len(win.findChildren(QWidget))

    def timed(theme_name, size):
        t0 = time.perf_counter()
        win.set_look(theme_name, size)
        app.processEvents()
        win.grab()
        return (time.perf_counter() - t0) * 1000

    themes = ["sky", "sapphire", "hb"] * args.runs
    sizes = ["L", "S", "M"] * args.runs
    theme_ms = [timed(t, "M") for t in themes]
    size_ms = [timed("hb", s) for s in sizes]
    out = {"platform": app.platformName(), "widgets": widgets, "runs": len(themes),
           "theme_median_ms": round(statistics.median(theme_ms), 1), "theme_max_ms": round(max(theme_ms), 1),
           "size_median_ms": round(statistics.median(size_ms), 1), "size_max_ms": round(max(size_ms), 1),
           "live": max(theme_ms + size_ms) < 300}
    print(json.dumps(out))
    win.close()
    services.shutdown(1.0)


if __name__ == "__main__":
    main()
