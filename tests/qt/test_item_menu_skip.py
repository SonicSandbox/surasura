"""Current's ⋯ › *Never read this folder* (K6, `app/qt/item_menu.py`): the item's folder and each one above it inside
its source folder, asked on the looks' worker and added before *Open its folder*; a pick writes through the window's writer
with a toast and Undo. On the window's seed through a recording writer, the folders a stand-in looks answer (the store's
own answer is `Store.skip_choices`, tested in tests/test_sources_skip.py).

What a wrong answer would cost a learner:
  * the entry on a row that came from no folder (nothing to skip), or missing on one that did;
  * a pick that skips another folder than the one named, writes on the window's thread, or can't be undone;
  * a write offered on a library that can't be saved (E4); an entry with no tooltip.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint

from app.qt import drag, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import open_window, settle  # noqa: F401
from tests.qt.test_item_menu import ItemWriter, calls, rows_of

ROOT = os.path.join(os.sep, "Media")                       # made-up folders, never read: the looks are a stand-in
FOLDERS = [os.path.join(ROOT, "Old Backups", "Console Card", "loader", "skins", "blue"),
           os.path.join(ROOT, "Old Backups", "Console Card", "loader", "skins"),
           os.path.join(ROOT, "Old Backups", "Console Card", "loader"),
           os.path.join(ROOT, "Old Backups", "Console Card"),
           os.path.join(ROOT, "Old Backups")]


class SkipWriter(ItemWriter):
    def skip_folder(self, path, label=None):
        return self._put("skip_folder", [], label, path=path)


class FakeLooks:
    """`SourceLooks.skippable` as ⋯ asks it: answers on a thread of its own (as the looks' worker does)."""

    def __init__(self, folders):
        self.folders, self.asks = folders, []

    def skippable(self, ids, then):
        self.asks.append(list(ids))
        threading.Thread(target=then, args=(list(self.folders),), daemon=True).start()
        return True

    def close(self):
        pass

    def set_shown(self, _shown):
        pass

    def asked(self, **_kw):
        return False


@pytest.fixture
def world(qapp):
    made = []

    def make(folders=FOLDERS, writable=True):
        from tests.fixtures import window_seed
        seed = window_seed.build()
        writer = SkipWriter(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
        win.looks = FakeLooks(folders)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _skip_menu(m):
    return next((a.menu() for a in m.actions() if a.text() == strings.ITEM_SKIP[0]), None)


def test_the_entry_lists_the_items_folder_and_each_above_it_deepest_first_before_open_its_folder(world):
    _seed, win, writer = world()
    row = rows_of(win)[4]
    m = win.items.menu(row, win.mapToGlobal(QPoint(300, 300)))
    assert wait_until(lambda: _skip_menu(m) is not None, 5)
    texts = [a.text() for a in m.actions()]
    assert texts.index(strings.ITEM_SKIP[0]) + 1 == texts.index(strings.ITEM_MENU["folder"][0])
    sub = _skip_menu(m)
    assert [a.text() for a in sub.actions()] == ["blue", "skins", "loader", "Console Card", "Old Backups"]
    assert win.looks.asks == [drag.ids_of(row)]
    assert m.actions()[texts.index(strings.ITEM_SKIP[0])].toolTip()
    assert all(FOLDERS[i] in a.toolTip() for i, a in enumerate(sub.actions()))   # every entry tipped, its whole path
    m.hide()


def test_picking_a_folder_skips_that_folder_on_the_writer_with_a_toast_and_undo(world):
    _seed, win, writer = world()
    row = rows_of(win)[4]
    m = win.items.menu(row, win.mapToGlobal(QPoint(300, 300)))
    assert wait_until(lambda: _skip_menu(m) is not None, 5)
    _skip_menu(m).actions()[3].trigger()                              # "Console Card", picked from the "blue" item
    m.hide()
    assert calls(writer, "skip_folder") == [("skip_folder", [], {"path": FOLDERS[3]})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SKIPPED.format(name="Console Card"), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert [c.op for c in writer.undone] == ["skip_folder"]


def test_a_row_from_no_source_folder_gets_no_entry(world):
    _seed, win, _w = world(folders=[])
    row = rows_of(win)[4]
    m = win.items.menu(row, win.mapToGlobal(QPoint(300, 300)))
    assert wait_until(lambda: win.looks.asks, 5)
    settle(100)
    assert _skip_menu(m) is None
    m.hide()


def test_an_answer_after_the_menu_closed_adds_nothing(world):
    _seed, win, _w = world()
    row = rows_of(win)[4]
    m = win.items.menu(row, win.mapToGlobal(QPoint(300, 300)))
    m.hide()
    settle(100)
    assert _skip_menu(m) is None


def test_E4_a_read_only_store_greys_the_entry_with_its_reason_and_a_pick_writes_nothing(world):
    _seed, win, writer = world(writable=False)
    row = rows_of(win)[4]
    m = win.items.menu(row, win.mapToGlobal(QPoint(300, 300)))
    assert wait_until(lambda: _skip_menu(m) is not None, 5)
    sub = _skip_menu(m)
    assert not sub.menuAction().isEnabled() and not any(a.isEnabled() for a in sub.actions())
    assert sub.menuAction().toolTip().startswith(strings.MENU_REFUSED_TIP.format(reason="")[:20])
    m.hide()
    win.items.skip_folder(row, FOLDERS[0])
    settle()
    assert writer.calls == []
