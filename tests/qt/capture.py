"""Captures of the shell at 100–200 %, read by their pixels (W2.1 row 11; the window's spec 07 §7.1 *Visual QA*, §5.11
DPI; the stack pack's harness layer: a capture's units are the first suspect).

    python tests/qt/capture.py --scales 100,125,150,175,200 [--out DIR]
    python tests/qt/capture.py --screen [--out DIR]
    python tests/qt/capture.py --integrated --scales 100,125,150,175,200 [--out DIR]

**Scales:** each scale runs in its own process on Windows' own platform (real fonts), the window laid out and painted
but never put on the screen (`WA_DontShowOnScreen`); Windows' scaling is stood in for by `QT_SCALE_FACTOR` over this
desktop's own (so 150 % on a 150 % desktop is factor 1). Each theme is grabbed at the window's device-pixel ratio, and
the picture is checked: its size is the window's × the scale (a crop is the classic false defect); the frame band, the
page and the footer hold their tokens (at least N pixels each, none of another theme's); the frame's two edges (W3.1a:
the baked strips under the tabs and above the footer, where the 1 px separators were) stand where they should, at their
height × the scale, darkest at the band and fading to the page's ground, the same at the window's side as in its middle
(no side edge), the bottom one meeting the footer. Large text at 1024 × 720 and 200 % (E16) keeps the bar and the tabs
inside the window.

**Integrated** (W3.1a: `--integrated --scales …`): the window as it runs — the synthetic seed's library and the duties
attached (stand-ins from `tests/qt/test_jobs_bar.py`: no Anki, no update check, no Generate) — in Medium at 1280 × 800,
each scale in its own process: the header's level ▾ with Generate's stale mark, the footer (the status line, the
emerald lit with *Anki · N waiting* from a backlog file under the test root, the known corner), Current's Goal dock;
then the level's pop open, then the dock's wells as a drag shows them. Checked: the size, the level ▾ inside the header,
the footer's corner and the dock shown and inside the window, the stones' sheet landed before the shot.

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
        cases.append(("night", "L", (1024, 720)))                      # E16: Large text, the narrow window, 200 %
    for theme_name, size, (w, h) in cases:
        win.set_look(size)
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
        from app.qt import frame

        def rows_of(widget):                          # (first device row, last device row + 1) of a widget in the grab
            y = widget.mapTo(win, QPoint(0, 0)).y()
            return round(y * dpr), round((y + widget.height()) * dpr)
        top = win.edge_top                            # W3.1a: the baked edges where the separators were
        bottom = next(s for s in win.pages.currentWidget().findChildren(frame.EdgeStrip) if s.side == "bottom")
        (t0, t1), (b0, b1), (f0, _f1) = rows_of(top), rows_of(bottom), rows_of(win.footer)
        regions = {"frame": arr[: t0 - 1], "page": arr[t1 + 1: b0 - 1], "footer": arr[f0 + 1:]}
        tokens = {"frame": (c["frame"],), "page": (c["bg"],), "footer": (c["frame"],)}
        problems = []
        if (arr.shape[1], arr.shape[0]) != (round(w * scale / 100), round(h * scale / 100)):
            problems.append(f"size {arr.shape[1]}x{arr.shape[0]} is not {w}x{h} at {scale} %")
        for region, wanted in tokens.items():
            part = regions[region]
            n = sum(count(part, colour, TOL) for colour in wanted)
            if n < 0.3 * part.shape[0] * part.shape[1]:
                problems.append(f"{region}: {n} pixels of its tokens")
            for o in others:
                key = "bg" if region == "page" else "frame"
                # (a stray antialiased glyph pixel may land on any colour: a theme left behind fills far more)
                stray = count(part, o[key], 1) > 0.005 * part.shape[0] * part.shape[1]
                if o[key] not in [c[k] for k in ("surface", "bg", "frame", "raised")] and stray:
                    problems.append(f"{region}: another theme's {key}")
        ground = sum(theme.parse(c["bg"])[:3])
        edges = {}
        for where, (y0, y1), band_first in (("under the tabs", (t0, t1), True), ("above the footer", (b0, b1), False)):
            want = theme.FRAME["edge-strip"] * scale / 100
            if abs((y1 - y0) - want) > 1.5:
                problems.append(f"the edge {where} is {y1 - y0} rows, not {want:.0f} at {scale} %")
            strip = arr[y0:y1].astype(int)
            if strip.shape[0] < 2:
                problems.append(f"the edge {where} is missing")
                continue
            mid = strip.shape[1] // 2
            near, far = (strip[0, mid].sum(), strip[-1, mid].sum()) if band_first else (strip[-1, mid].sum(),
                                                                                         strip[0, mid].sum())
            if not near < far <= ground + 6:                  # a shadow: darkest at the band, fading to the ground
                problems.append(f"the edge {where} is no shadow falling from its band ({near} → {far}, ground {ground})")
            if (abs(strip[:, 1] - strip[:, mid]) > 3).any():   # the same at the side as in the middle: no side edge
                problems.append(f"the edge {where} has a side edge")
            edges[where] = [y0, y1]
        if abs(b1 - f0) > 1:
            problems.append(f"the bottom edge ends at row {b1}, the footer starts at {f0}: a gap or an overlap")
        if win.footer.geometry().bottom() > win.centralWidget().height() or win.footer.height() <= 0:
            problems.append("the bar is outside the window")
        results.append({"scale": scale, "theme": theme_name, "text_size": size, "window": [w, h], "dpr": dpr,
                        "file": name, "edges": edges, "problems": problems})
    win.close()
    services.shutdown(1.0)
    return results


# --- W2.2: the first screens on the synthetic seed ---------------------------------------------------------------- #
PLAY_FAILED_LINE = "Couldn't open Ep 1: no video beside it on disk"


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
    soon = next(i for i, e in enumerate(lst.model().entries) if any(ln.kind == "soon" for ln in e[2]))
    from PyQt6.QtCore import QEvent
    for theme_name in theme.THEMES:
        win.set_look("M")
        c = theme.colours(theme_name)
        others = [theme.colours(t)["bg"] for t in theme.THEMES if t != theme_name]
        for screen in ("current", "current-open", "current-soon", "finished", "needs"):
            if lst.model().open_key is not None:
                lst.model().open_key = None
                lst.relayout()
            win.bar_line.set_full(PLAY_FAILED_LINE if screen == "needs" else "")    # the bar's line by its dot (G2.3 N2)
            win.show_tab("current" if screen.startswith("current") else screen)
            settle(10)
            if screen == "current-open":
                lst.toggle(lst.model().index(amber, 0))
                settle(10)
                lst.scrollTo(lst.model().index(amber, 0), lst.ScrollHint.PositionAtTop)
            elif screen == "current-soon":
                lst.scrollTo(lst.model().index(soon, 0), lst.ScrollHint.PositionAtCenter)
            elif screen == "current":
                lst.scrollToTop()
            settle()
            for lv in (lst, win.page_widgets[screen if screen in win.page_widgets else "current"].list):
                QApplication.sendEvent(lv.viewport(), QEvent(QEvent.Type.Leave))   # wherever the real pointer is,
            settle(5)                                                              # no row is hovered in a picture
            page = win.pages.currentWidget()
            pix = win.grab()
            name = f"w22-{screen}-{theme_name}-{scale}.png"
            pix.save(os.path.join(out_dir, name))
            if screen == "current-open":             # an episode's No video tooltip: its action on its own line (T1)
                ep = next(e for e in lst.model().entries[amber][1].episodes if e.missing)
                parts = [pt for pt in lst.delegate.parts(lst.model().entries[amber], lst.visualRect(
                    lst.model().index(amber, 0))) if pt[0] in ("status", "no-media") and ep.status.tip in (pt[2] or "")]
                rect, tip = parts[-1][1], parts[-1][2]      # by its tip: not every episode has a status (H-1)
                win.tooltips.request(lst.viewport(), rect, tip)
                settle(5)
                win.tooltips.bubble.grab().save(os.path.join(out_dir, f"w22-tooltip-{theme_name}-{scale}.png"))
                win.tooltips.hide()
            sub = rgb_array(page.grab())
            problems = []
            area = sub.shape[0] * sub.shape[1]
            if count(sub, c["bg"], TOL) + count(sub, c["surface"], TOL) < 0.3 * area:
                problems.append(f"{screen}: the page's ground (bg, an open row's surface) is under 30 %")
            if count(sub, "#000000", 0) > 0.01 * area:
                problems.append(f"{screen}: black (unpainted) areas")
            for o in others:
                if o != c["bg"] and count(sub, o, 1) > 0.005 * area:
                    problems.append(f"{screen}: another theme's ground")
            if screen == "current":
                if count(sub, theme.STATUS["ok"], 40) < 5:
                    problems.append("current: no learned green (in Anki)")
                if count(sub, c["top20-line"], 12) < 40:
                    problems.append("current: no top-20 line")
            if screen == "current-open":
                # only the open row's episodes (the closed row's own amber mark mustn't answer for them)
                from PyQt6.QtCore import QRect
                r = lst.visualRect(lst.model().index(amber, 0))
                row_h = round(theme.SIZES["row"] * rows.fz())
                eps = rgb_array(lst.viewport().grab(QRect(r.left(), r.top() + row_h, r.width(), r.height() - row_h)))
                if count(eps, theme.STATUS["warn"], 40) < 5:
                    problems.append("current-open: no heads-up amber on its episodes (no video in the top 20)")
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
        win.set_look("M")
        settle()
        pix = win.grab()
        name = f"w22-{label}-night-{scale}.png"
        pix.save(os.path.join(out_dir, name))
        page = win.page_widgets["current"]
        problems = []
        sub = rgb_array(page.grab())
        if count(sub, theme.colours()["bg"], TOL) < 0.3 * sub.shape[0] * sub.shape[1]:
            problems.append(f"{label}: the page's ground is under 30 %")
        if count(sub, "#000000", 0) > 0.01 * sub.shape[0] * sub.shape[1]:
            problems.append(f"{label}: black (unpainted) areas")
        if label == "read-only" and not (page.state_bar.isVisible() and page.state_bar.text()):
            problems.append("read-only: no bar saying why")
        if label == "empty" and page.list.model().entries[0][0] != rows.EMPTY:
            problems.append("empty: no empty line")
        results.append({"scale": scale, "theme": "night", "screen": label, "file": name, "problems": problems})
        win.close()
        services.shutdown(1.0)
    return results
# --- end W2.2 ----------------------------------------------------------------------------------------------------------- #


# --- W3.1a: the integrated window — the library and the duties attached --------------------------------------------- #
def run_integrated(scale, out_dir):
    """One process: the window with the seed's library and the duties (stand-ins) at `scale` %, Medium, 1280 × 800 —
    as it rests, with the level's pop open, and with the dock's wells as a drag shows them. -> result dicts."""
    _isolate()
    os.environ.pop("QT_QPA_PLATFORM", None)
    import time
    from PyQt6.QtCore import QEvent, QPoint, Qt
    from PyQt6.QtWidgets import QApplication
    from app import path_utils
    from app.qt import shell, stones, style
    from app.services import automation as A
    from app.services import generate as G
    from app.services import library_reader
    from app.services import status as status_service
    from app.services.jobs import JobRegistry
    from tests.fixtures import window_seed

    root = os.environ["SURASURA_TEST_ROOT"]
    with open(path_utils.get_user_file("settings.json"), "w", encoding="utf-8") as f:
        json.dump({"text_size": "M", "anki_sync_auto": True}, f)
    seed = window_seed.build(root=root)
    from app import anki_sync                                     # a backlog as the sync saves it: Anki · 3 waiting
    backlog = anki_sync._backlog_path(seed.language)
    os.makedirs(os.path.dirname(backlog), exist_ok=True)
    with open(backlog, "w", encoding="utf-8") as f:
        json.dump({"version": anki_sync.BACKLOG_VERSION, "synced_at": "2026-10-14T21:05:00", "decks": ["日本語::Mining"],
                   "fields": ["Word"], "notes": {str(1700000000001 + i): {"word": w, "keys": [w], "source": "日本語::Mining",
                                                                          "freqsort": 1000 + i}
                                                 for i, w in enumerate(("撒く", "上層部", "一生懸命"))}}, f,
                  ensure_ascii=False)

    app = QApplication(["capture-integrated"])
    # the duties' stand-ins, imported once the app is made on Windows' own platform: their test module's conftest asks
    # for the offscreen one (no real fonts, no real scale) as it loads
    from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader
    log = []
    registry = JobRegistry()
    status = status_service.StatusService(registry, reader=QuietReader(), providers={   # (the quiet marks: W31A-1)
        "backlog": status_service.anki_backlog(seed.language), "replan": lambda: "Anki: placing tomorrow's 20 cards…",
        "connect": lambda: "Up to date · 12 cards made today"})
    reader = library_reader.LibraryReader(seed.opener, numbers=seed.numbers, mining=seed.mining, poll=0.02)
    controller, automation = FakeController(log), FakeAutomation(log)
    services = shell.Services(library=reader, registry=registry, status=status, controller=controller,
                              updates=FakeUpdates(log), automation=automation, chores=FakeChores(log))
    win = shell.open_window(app, services)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1280, 800)
    win.show()

    def settle(n=30):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.005)

    def until(test, seconds=10):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if test():
                return True
            time.sleep(0.01)
        return False

    page = win.page_widgets["current"]
    until(lambda: page.view_model is not None and not page.view_model.loading)
    status.refresh_soon()
    controller.push(state=G.STALE)                                # the ▾'s mark
    automation.push(sync=A.SYNCED, added=3, known=12345)          # the emerald lit, the known corner
    win._show_level(("rare", False))
    dpr = win.devicePixelRatioF()
    sheet = until(lambda: stones.get(dpr, style.current()[1]) is not None, 20)
    until(lambda: win.anki_mark.waiting == 3)
    lst = page.list
    QApplication.sendEvent(lst.viewport(), QEvent(QEvent.Type.Leave))     # no row hovered, wherever the pointer is
    settle(40)
    d = win.duties
    results = []

    def shot(label, extra=()):
        settle(20)
        pix = win.grab()
        name = f"w31a-integrated-{label}-{scale}.png"
        pix.save(os.path.join(out_dir, name))
        problems = list(extra)
        if (pix.width(), pix.height()) != (round(1280 * scale / 100), round(800 * scale / 100)):
            problems.append(f"size {pix.width()}x{pix.height()} is not 1280x800 at {scale} %")
        if not sheet:
            problems.append("the stones' sheet never landed")
        level = d.level.geometry()
        if d.level.isHidden() or not win.header.rect().contains(level):
            problems.append("the level ▾ is hidden or outside the header")
        for part, what in ((win.anki_mark, "the emerald"), (win.known, "the known corner")):
            at = part.mapTo(win, QPoint(0, 0))
            if part.isHidden() or at.x() + part.width() > win.width() or at.y() + part.height() > win.height():
                problems.append(f"{what} is hidden or outside the window")
        if win.anki_mark.text() != "Anki · 3 waiting":
            problems.append(f"the emerald says {win.anki_mark.text()!r}, not 'Anki · 3 waiting'")
        if win.dock is None or not win.dock.isVisibleTo(win):
            problems.append("the Goal dock is not shown")
        results.append({"scale": scale, "integrated": label, "dpr": dpr, "file": name, "level": d.level.text(),
                        "level_mark": d.level.mark, "problems": problems})

    shot("rest", () if d.level.mark == "stale" else [f"the ▾'s mark is {d.level.mark!r}, not 'stale'"])
    d.pop.open()
    settle(30)
    shot("pop", () if d.pop.isVisible() else ["the level's pop did not open"])
    d.pop.hide()
    win.dock.begin_drag("current")
    settle(30)
    win.dock.hover("goal")
    shot("wells", () if win.dock.wells else ["the wells did not rise"])
    win.dock.hover(None)
    win.dock.end_drag()
    win.close()
    services.shutdown(1.0)
    return results


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
    ap.add_argument("--integrated", action="store_true",
                    help="W3.1a: the window with the seed's library and the duties attached, per scale")
    args = ap.parse_args()
    out_dir = args.out or tempfile.mkdtemp(prefix="w21-captures-")
    os.makedirs(out_dir, exist_ok=True)
    if args.one:
        run = run_integrated if args.integrated else run_screens if args.screens else run_scale
        for r in run(args.one, out_dir):
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
                              (["--screens"] if args.screens else []) + (["--integrated"] if args.integrated else []),
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
