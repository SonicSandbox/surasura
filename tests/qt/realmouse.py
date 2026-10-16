"""The drag under the real mouse (W3.1a §2; not collected by pytest — run it by hand, the window must be on screen):

    python tests/qt/realmouse.py

It moves the real cursor (Windows' SendInput through `user32`), so it can't run hidden: keep your hands off the mouse
for the ten seconds it runs. It opens the window on the seed (the stand-in store, nothing written anywhere — the
recording writer of `test_drag.py`) and checks, as a learner's hand would do it:
  1. a row grabbed by its cover and dragged up two rows lands there (one move given; the cover never starts a drag of
     its own image);
  2. a click on a stone marks that episode watched — on the release (B1);
  3. a drag begun on a stone never marks it watched (B1), and Esc mid-drag puts the row back (nothing given);
  4. a row dropped on the Soon well goes to Soon.
Prints one line per check and exits 1 on the first that fails.
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt6.QtCore import QPoint, Qt                                             # noqa: E402
from PyQt6.QtWidgets import QApplication                                        # noqa: E402

user32 = ctypes.windll.user32
DOWN, UP = 0x0002, 0x0004                                                       # MOUSEEVENTF_LEFTDOWN / LEFTUP
KEY_UP, ESC = 0x0002, 0x1B


def pump(ms=30):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def to_screen(win, gpos):
    """A Qt global point (logical) as the screen's pixels."""
    ratio = win.windowHandle().screen().devicePixelRatio() if win.windowHandle() else 1.0
    return int(round(gpos.x() * ratio)), int(round(gpos.y() * ratio))


def cursor_to(win, gpos):
    user32.SetCursorPos(*to_screen(win, gpos))
    pump(25)


def glide(win, start, end, steps=12):
    """The cursor travels from `start` to `end` in `steps`, as a hand does."""
    for k in range(1, steps + 1):
        cursor_to(win, start + (end - start) * k / steps)


def button(flag):
    user32.mouse_event(flag, 0, 0, 0, 0)
    pump(40)


def key(code):
    user32.keybd_event(code, 0, 0, 0)
    user32.keybd_event(code, 0, KEY_UP, 0)
    pump(40)


def check(ok, what):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        raise SystemExit(1)


def main():
    from app.qt import rows, stones
    from tests.fixtures import window_seed
    from tests.qt import test_drag as t
    from app.qt import style

    app = QApplication.instance() or QApplication(["surasura-realmouse"])
    style.apply(app, "night", "M", "ja")
    key_ = stones._key(1.0, "M")
    if key_ not in stones._SHEETS:
        stones._landed(key_, stones.build(*key_))
    seed = window_seed.build()
    writer = t.FakeWriter(seed.library, apply=True)
    win, services = t.open_window(app, seed, writer)
    win.setWindowState(Qt.WindowState.WindowActive)
    win.raise_()
    win.activateWindow()
    pump(400)
    lst = t.lst_of(win)
    vp = lst.viewport()
    try:
        # 1. by the cover, up two rows
        i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and n >= 4)
        key_row = lst.model().entries[i][1].key
        rect = lst.visualRect(lst.model().index(i, 0))
        cover = vp.mapToGlobal(QPoint(rect.left() + 12, rect.center().y()))
        cursor_to(win, cover)
        button(DOWN)
        glide(win, cover, t.row_point(win, i - 2))
        dragging = win.moves.running is not None
        button(UP)
        pump(500)
        moved = t.calls(writer, "move")
        check(dragging and len(moved) == 1 and t.index_of(lst, key_row) == i - 2,
              "a row grabbed by its cover lands two rows up (one move)")
        writer.calls.clear()

        # 2. a click on a stone: watched on the release
        n = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and t.part_rect(lst, n, "stone"))
        stone = t.part_rect(lst, n, "stone")
        at = vp.mapToGlobal(stone[1].center())
        cursor_to(win, at)
        button(DOWN)
        pressed_only = t.calls(writer, "set_watched") == []
        button(UP)
        pump(300)
        check(pressed_only and [c[1] for c in t.calls(writer, "set_watched")] == [[stone[3].id]],
              "a click on a stone marks it watched on the release")
        writer.calls.clear()
        win.toasts.close()

        # 3. a drag from a stone never marks it; Esc puts the row back
        stone = t.part_rect(lst, n, "stone")
        at = vp.mapToGlobal(stone[1].center())
        order = [getattr(e[1], "key", None) for e in lst.model().entries]
        cursor_to(win, at)
        button(DOWN)
        glide(win, at, at + QPoint(0, 40), steps=6)
        began = win.moves.running is not None
        key(ESC)
        button(UP)
        pump(400)
        check(began and not t.calls(writer) and [getattr(e[1], "key", None) for e in lst.model().entries] == order,
              "a drag from a stone never marks it watched; Esc puts the row back")

        # 4. onto the Soon well
        i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and e[1].tier == "now")
        start = vp.mapToGlobal(t.title_point(lst, i))
        cursor_to(win, start)
        button(DOWN)
        glide(win, start, start + QPoint(0, 12), steps=3)
        pump(200)                                                       # the wells rise
        glide(win, start + QPoint(0, 12), t.well_point(win, "soon"))
        button(UP)
        pump(500)
        moved = t.calls(writer, "move")
        check(len(moved) == 1 and moved[0][2]["tier"] == "soon", "a row dropped on the Soon well goes to Soon")
    finally:
        user32.mouse_event(UP, 0, 0, 0, 0)                               # never leave the button held
        win.close()
        services.shutdown(0.5)
    print("all checks passed")


if __name__ == "__main__":
    main()
