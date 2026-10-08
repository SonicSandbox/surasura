"""Captures of the shell at 100–200 %, read by their pixels (W2.1 row 11; the window's spec 07 §7.1 *Visual QA*, §5.11
DPI; the stack pack's harness layer: a capture's units are the first suspect).

    python tests/qt/capture.py --scales 100,125,150,175,200 [--out DIR]
    python tests/qt/capture.py --screen [--out DIR]

**Scales:** each scale runs in its own process on Windows' own platform (real fonts), the window laid out and painted
but never put on the screen (`WA_DontShowOnScreen`); Windows' scaling is stood in for by `QT_SCALE_FACTOR` over this
desktop's own (so 150 % on a 150 % desktop is factor 1). Each theme is grabbed at the window's device-pixel ratio, and
the picture is checked: its size is the window's × the scale (a crop is the classic false defect); the header, the
tab bar, the page and the bottom bar hold their tokens (at least N pixels each, none of another theme's); the 1 px
lines under the header, the tabs and above the bar are whole rows of the `line` colour, neither missing nor doubled.
Large text at 1024 × 720 and 200 % (E16) keeps the bar and the tabs inside the window.

**Screen:** the window shown for a moment without taking focus, captured with `PrintWindow` into a bitmap sized by
`GetDpiForWindow / 96` (never `GetWindowRect`'s logical size): the title bar's pixels must be dark on Windows 10.

**Screens** (W2.2 row 6: `--screens --scales …`): the first screens on the synthetic seed (the stand-in store, invented
titles), each scale in its own process as above, each theme: Current (the hero and the top-20 line; then a row open with
its missing episodes), Finished and Needs you; at Blue also the read-only state and an empty library. Checked: the page
holds its ground (`bg`), Current shows the learned green (✓ in Anki), the open row the heads-up amber (no video in the top
20) and the top-20 line's colour, and no other theme's ground.

Motion is frozen; a temp `SURASURA_TEST_ROOT` is set and checked first (never the real settings or local data).
Pictures go to `--out` (default: a new temp folder); every one is dark, on no one's library. Prints JSON lines and
ends with `ALL CAPTURES PASS` or exits 1.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

TOL = 2


def _system_scale():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def _isolate():
    os.environ["SURASURA_TEST_ROOT"] = tempfile.mkdtemp(prefix="w21-capture-")
    import shutil                                    # the test root is also where bundled resources are read: the mark
    shutil.copytree(os.path.join(ROOT, "app", "assets"), os.path.join(os.environ["SURASURA_TEST_ROOT"], "app", "assets"))
    os.environ["SURASURA_FREEZE_MOTION"] = "1"
    from app import path_utils
    assert path_utils.get_local_data_path().startswith(os.environ["SURASURA_TEST_ROOT"])
    assert path_utils.get_user_file("settings.json").startswith(os.environ["SURASURA_TEST_ROOT"])


def _seam_rows(arr, y_from, y_to, colour):
    """Rows in [y_from, y_to) that are (≥ 95 %) the line colour."""
    from tests.qt.pixels import count
    rows = []
    for y in range(max(0, y_from), min(arr.shape[0], y_to)):
        row = arr[y:y + 1, :, :]
        if count(row, colour, TOL + 1) >= 0.95 * row.shape[1]:
            rows.append(y)
    return rows


def run_scale(scale, out_dir):
    """One process: every theme at `scale` %, checked. -> a list of result dicts."""
    _isolate()
    os.environ.pop("QT_QPA_PLATFORM", None)
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from app import theme
    from app.qt import shell
    from tests.qt.pixels import count, rgb_array

    app = QApplication(["capture"])
    services = shell.Services()
    win = shell.open_window(app, services)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    results = []
    cases = [(t, "M", (1280, 800)) for t in theme.THEMES]
    if scale == 200:
        cases.append(("hb", "L", (1024, 720)))                      # E16: Large text, the narrow window, 200 %
    for theme_name, size, (w, h) in cases:
        win.set_look(theme_name, size)
        win.resize(w, h)
        win.show()
        app.processEvents()
        pix = win.grab()
        dpr = pix.devicePixelRatio()
        arr = rgb_array(pix)
        name = f"w21-shell-{theme_name}-{size}-{w}x{h}-{scale}.png"
        pix.save(os.path.join(out_dir, name))
        c = theme.colours(theme_name)
        others = [theme.colours(t) for t in theme.THEMES if t != theme_name]
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QFrame
        seps = sorted(win.centralWidget().findChildren(QFrame, "separator"), key=lambda f: f.mapTo(win, QPoint(0, 0)).y())
        lines = [f.mapTo(win, QPoint(0, 0)).y() * dpr for f in seps]       # device rows where each 1 px line starts

        y1, y2, y3 = (int(v) for v in lines[:3])
        regions = {"header": arr[: y1 - 1], "tabs": arr[y1 + 3: y2 - 1], "page": arr[y2 + 3: y3 - 1],
                   "footer": arr[y3 + 3:]}
        tokens = {"header": (c["header-top-opaque"], c["surface"]), "tabs": (c["tab-bar"],), "page": (c["bg"],),
                  "footer": (c["surface"],)}
        problems = []
        if (arr.shape[1], arr.shape[0]) != (round(w * scale / 100), round(h * scale / 100)):
            problems.append(f"size {arr.shape[1]}x{arr.shape[0]} is not {w}x{h} at {scale} %")
        for region, wanted in tokens.items():
            part = regions[region]
            n = sum(count(part, colour, TOL) for colour in wanted)
            if n < 0.3 * part.shape[0] * part.shape[1]:
                problems.append(f"{region}: {n} pixels of its tokens")
            for o in others:
                key = "surface" if region in ("footer", "header") else ("bg" if region == "page" else "tab-bar")
                # (a stray antialiased glyph pixel may land on any colour: a theme left behind fills far more)
                stray = count(part, o[key], 1) > 0.005 * part.shape[0] * part.shape[1]
                if o[key] not in [c[k] for k in ("surface", "bg", "tab-bar", "raised")] and stray:
                    problems.append(f"{region}: another theme's {key}")
        seams = {where: _seam_rows(arr, y - 2, y + 4, c["line"])
                 for where, y in zip(("under the header", "under the tabs", "above the bar"), (y1, y2, y3))}
        for where, rows in seams.items():
            if not rows:
                problems.append(f"the line {where} is missing")
            elif len(rows) > math.ceil(scale / 100):          # 1 px is one row at 100 %, at most two up to 200 %
                problems.append(f"the line {where} is {len(rows)} rows at {scale} %")
        if win.footer.geometry().bottom() > win.centralWidget().height() or win.footer.height() <= 0:
            problems.append("the bar is outside the window")
        results.append({"scale": scale, "theme": theme_name, "text_size": size, "window": [w, h], "dpr": dpr,
                        "file": name, "seams": {k: len(v) for k, v in seams.items()}, "problems": problems})
    win.close()
    services.shutdown(1.0)
    return results


# --- W2.2: the first screens on the synthetic seed ---------------------------------------------------------------- #
def run_screens(scale, out_dir):
    """One process: Current, Finished and Needs you for every theme at `scale` %, on the seed. -> result dicts."""
    _isolate()
    os.environ.pop("QT_QPA_PLATFORM", None)
    import time
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from app import theme
    from app.qt import rows, shell
    from app.services import library_reader
    from tests.fixtures import standin_store, window_seed
    from tests.qt.pixels import count, rgb_array

    app = QApplication(["capture"])
    results = []

    def settle(n=30):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.005)

    def open_seeded(seed):
        reader = library_reader.LibraryReader(seed.opener, numbers=seed.numbers, mining=seed.mining, poll=0.02)
        services = shell.Services(library=reader)
        win = shell.open_window(app, services)
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.resize(1280, 800)
        win.show()
        page = win.page_widgets["current"]
        for _ in range(400):
            app.processEvents()
            if page.view_model is not None and not page.view_model.loading:
                break
            time.sleep(0.01)
        settle()
        return win, services

    seed = window_seed.build(root=os.environ["SURASURA_TEST_ROOT"])
    win, services = open_seeded(seed)
    lst = win.page_widgets["current"].list
    amber = next(i for i, e in enumerate(lst.model().entries)
                 if e[0] == rows.ROW and sum(ep.missing for ep in e[1].episodes) == 3)
    for theme_name in theme.THEMES:
        win.set_look(theme_name, "M")
        c = theme.colours(theme_name)
        others = [theme.colours(t)["bg"] for t in theme.THEMES if t != theme_name]
        for screen in ("current", "current-open", "finished", "needs"):
            if lst.model().open_key is not None:
                lst.model().open_key = None
                lst.relayout()
            win.show_tab("current" if screen.startswith("current") else screen)
            settle(10)
            if screen == "current-open":
                lst.toggle(lst.model().index(amber, 0))
                settle(10)
                lst.scrollTo(lst.model().index(amber, 0), lst.ScrollHint.PositionAtTop)
            elif screen == "current":
                lst.scrollToTop()
            settle()
            page = win.pages.currentWidget()
            pix = win.grab()
            name = f"w22-{screen}-{theme_name}-{scale}.png"
            pix.save(os.path.join(out_dir, name))
            sub = rgb_array(page.grab())
            problems = []
            area = sub.shape[0] * sub.shape[1]
            if count(sub, c["bg"], TOL) < 0.3 * area:
                problems.append(f"{screen}: the page's ground is under 30 %")
            for o in others:
                if o != c["bg"] and count(sub, o, 1) > 0.005 * area:
                    problems.append(f"{screen}: another theme's ground")
            if screen == "current":
                if count(sub, theme.STATUS["ok"], 40) < 5:
                    problems.append("current: no learned green (in Anki)")
                if count(sub, c["top20-line"], 12) < 40:
                    problems.append("current: no top-20 line")
            if screen == "current-open" and count(sub, theme.STATUS["warn"], 40) < 5:
                problems.append("current-open: no heads-up amber (no video in the top 20)")
            results.append({"scale": scale, "theme": theme_name, "screen": screen, "file": name,
                            "problems": problems})
    win.close()
    services.shutdown(1.0)
    for mode, reason, label in (("read-only", "damaged", "read-only"), ("store", None, "empty")):
        if label == "empty":
            lib = standin_store.StandinLibrary([], [])
            seed2 = window_seed.Seed(library=lib, opener=standin_store.StandinOpener(lib), numbers=lambda: (0, {}),
                                     mining=lambda: (), root=None, language="ja", files=0, vocabulary=set(), items=[],
                                     works=[], hero_work=None)
        else:
            seed2 = window_seed.build(root=os.environ["SURASURA_TEST_ROOT"], mode=mode, reason=reason)
        win, services = open_seeded(seed2)
        win.set_look("hb", "M")
        settle()
        pix = win.grab()
        name = f"w22-{label}-hb-{scale}.png"
        pix.save(os.path.join(out_dir, name))
        results.append({"scale": scale, "theme": "hb", "screen": label, "file": name, "problems": []})
        win.close()
        services.shutdown(1.0)
    return results
# --- end W2.2 ----------------------------------------------------------------------------------------------------------- #


def run_screen(out_dir):
    """The window on screen for a moment (no focus taken), captured by PrintWindow at GetDpiForWindow / 96."""
    _isolate()
    os.environ.pop("QT_QPA_PLATFORM", None)
    import ctypes
    from ctypes import wintypes
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QApplication
    from app.qt import shell
    from tests.qt.pixels import rgb_array

    app = QApplication(["capture-screen"])
    services = shell.Services()
    win = shell.open_window(app, services)
    win.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    win.resize(1000, 640)
    win.move(40, 40)
    out = {}

    def shoot():
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        hwnd = int(win.winId())
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        dpi = user32.GetDpiForWindow(hwnd)
        logical = (win.frameGeometry().width(), win.frameGeometry().height())
        # The window's own size in device pixels: this process is DPI-aware (Qt makes it so), so GetWindowRect answers
        # device pixels, borders included; a DPI-unaware one would answer logical ones and the bitmap would crop.
        w, h = rect.right - rect.left, rect.bottom - rect.top
        need = (round(logical[0] * dpi / 96), round(logical[1] * dpi / 96))
        hdc = user32.GetDC(hwnd)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(mem, bmp)
        ok = user32.PrintWindow(hwnd, mem, 2)                      # PW_RENDERFULLCONTENT
        img = QImage(w, h, QImage.Format.Format_RGB32)
        bits = img.bits()
        bits.setsize(img.sizeInBytes())

        class BMI(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = (ctypes.c_ubyte * img.sizeInBytes()).from_buffer(bits)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
        name = "w21-shell-screen.png"
        img.save(os.path.join(out_dir, name))
        arr = rgb_array(img)
        top = max(1, round(8 * dpi / 96))
        caption = arr[top: top + round(14 * dpi / 96), round(60 * dpi / 96): round(300 * dpi / 96)]
        luma = 0.2126 * caption[:, :, 0] + 0.7152 * caption[:, :, 1] + 0.0722 * caption[:, :, 2]
        lum = luma.mean()
        text = int((luma > 110).sum())                              # the title's letters: a real caption, not a blank
        problems = []
        if not ok:
            problems.append("PrintWindow failed")
        if lum > 80:
            problems.append(f"the title bar is light (mean {lum:.0f} / 255)")
        if text < 20:
            problems.append(f"no title text in the caption ({text} light pixels): a blank or black capture")
        if w < need[0] - 1 or h < need[1] - 1:
            problems.append(f"the capture {w}x{h} is smaller than the window at {dpi} dpi ({need[0]}x{need[1]}): a crop")
        out.update({"screen": True, "dpi": dpi, "size": [w, h], "logical_x_dpi": list(need),
                    "caption_luma": round(float(lum), 1), "file": name, "problems": problems})
        app.quit()

    win.show()
    QTimer.singleShot(1200, shoot)
    app.exec()
    win.close()
    services.shutdown(1.0)
    return [out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", default="")
    ap.add_argument("--screen", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--one", type=int, default=0, help=argparse.SUPPRESS)       # a child: one scale
    ap.add_argument("--screens", action="store_true", help="W2.2: the first screens on the seed, per scale")
    args = ap.parse_args()
    out_dir = args.out or tempfile.mkdtemp(prefix="w21-captures-")
    os.makedirs(out_dir, exist_ok=True)
    if args.one:
        for r in (run_screens if args.screens else run_scale)(args.one, out_dir):
            print(json.dumps(r), flush=True)
        return 0
    results = []
    if args.screen:
        results += run_screen(out_dir)
    system = _system_scale()
    for s in [int(x) for x in args.scales.split(",") if x.strip()]:
        env = dict(os.environ, QT_SCALE_FACTOR=f"{s / 100 / system:.6f}", QT_ENABLE_HIGHDPI_SCALING="1")
        env.pop("QT_QPA_PLATFORM", None)
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--one", str(s), "--out", out_dir] +
                              (["--screens"] if args.screens else []),
                              env=env, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            results.append({"scale": s, "problems": [f"the capture process failed: {proc.stderr[-1500:]}"]})
            continue
        results += [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    bad = 0
    for r in results:
        print(json.dumps(r))
        bad += bool(r.get("problems"))
    print(f"pictures in {out_dir}")
    print("ALL CAPTURES PASS" if not bad else f"{bad} CAPTURES WITH PROBLEMS")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
