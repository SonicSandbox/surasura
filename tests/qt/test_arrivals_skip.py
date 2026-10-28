"""New arrivals' ⋯ › *Never read this folder* (Q7, `app/qt/arrivals.py` through `app/qt/item_menu.py`'s one rule —
`offer_skip`, `skip_menu`, `give_skip`): a list row's own entry on a tray row — the arrival's folder and each one above
it inside its source folder, asked on the looks' worker and added before *Open its folder* while the menu is open; a
pick is one writer change with its toast and one Undo. On the window's seed (Japanese and Chinese titles, from
tests/Test Resources/) through a recording writer that lands the skip as the store does (the files under the folder
leave, the change carrying its `folder`; Undo puts them back) — the store's own answer and write are
tests/test_sources_skip.py's (row 57).

What a wrong answer would cost a learner:
  * a featurette waiting in New arrivals he can't keep out (no entry), or an entry on an arrival from no folder;
  * a pick that skips another folder, writes on a library that can't be saved (E4), or can't be undone;
  * the arrival still in the tray after the skip, or not back after its Undo; Settings' skipped list left stale.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")

from app.qt import strings
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import ArrivalsWriter, open_tray, open_window, tray_of, tray_rows
from tests.qt.test_drag import calls, settle

ROOT = os.path.join(os.sep, "Media")                       # made-up folders, never read: the looks are a stand-in


class SkipWriter(ArrivalsWriter):
    """The arrivals' recording writer with `skip_folder` landed as the store lands it: the files `under` the folder
    ({folder: ids}) leave the stand-in library in one change carrying its `folder`; Undo puts them back."""

    def __init__(self, library):
        super().__init__(library)
        self.under = {}
        self.taken = {}

    def skip_folder(self, path, label=None):
        return self._put("skip_folder", self.under.get(path, []), label, path=path)

    def _write(self, change):
        if change.op != "skip_folder":
            return super()._write(change)
        rows = [r for r in self.library.items() if r["id"] in change.ids]
        change.folder = len(self.taken) + 1
        self.taken[change.folder] = rows
        self.library.commit(gone=[("item", r["id"]) for r in rows], order=True)

    def undo(self, change=None, label=None):
        rows = self.taken.pop(getattr(change, "folder", None), None)
        if rows:
            self.library.commit(items=rows, order=True)
        return super().undo(change, label)


class FakeLooks:
    """`SourceLooks.skippable` as ⋯ asks it (`choices`, answered on a thread of its own, as the looks' worker does);
    `listing` counted (Settings' skipped folders read again)."""

    def __init__(self, choices):
        self.choices, self.asks, self.listings = choices, [], 0

    def skippable(self, ids, then):
        self.asks.append(list(ids))
        threading.Thread(target=then, args=(list(self.choices),), daemon=True).start()
        return True

    def folders(self, ids, then, detail=False):                       # (the rows' folder names: none here)
        then(dict.fromkeys(ids))
        return True

    def listing(self):
        self.listings += 1
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

    def make(language="ja", folders=None, writable=True):
        seed = window_seed.build(language=language)
        writer = SkipWriter(seed.library)
        win, services = open_window(qapp, seed, writer)
        writer.writable = writable
        open_tray(win)
        row = tray_rows(win)[0]
        show = os.path.join(ROOT, row.arrival.title)                   # the arrival's own show, by its own name
        if folders is None:
            folders = [os.path.join(show, "Extras", "Commentary"), os.path.join(show, "Extras"), show]
        win.looks = FakeLooks(folders)
        made.append((win, services))
        return seed, win, writer, row
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _skip_menu(m):
    return next((a.menu() for a in m.actions() if a.text() == strings.ITEM_SKIP[0]), None)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_tray_menu_offers_the_arrivals_folder_and_each_above_it_deepest_first_before_open_its_folder(world,
                                                                                                         language):
    _seed, win, _writer, row = world(language)
    m = tray_of(win).menu(row)
    assert wait_until(lambda: _skip_menu(m) is not None, 5)
    assert win.looks.asks == [list(row.arrival.item_ids)]
    texts = [a.text() for a in m.actions()]
    assert texts.index(strings.ITEM_SKIP[0]) + 1 == texts.index(strings.TRAY_MENU["folder"][0])
    sub = _skip_menu(m)
    assert [a.text() for a in sub.actions()] == ["Commentary", "Extras", row.arrival.title]
    assert sub.menuAction().toolTip() == strings.ITEM_SKIP[1]
    assert all(f in a.toolTip() for f, a in zip(win.looks.choices, sub.actions()))    # each tipped with its path
    m.close()


def test_an_arrival_from_no_folder_being_read_gets_no_entry(world):
    _seed, win, _writer, row = world(folders=[])
    m = tray_of(win).menu(row)
    assert wait_until(lambda: win.looks.asks, 5)
    settle(100)
    assert _skip_menu(m) is None
    m.close()


def test_an_answer_after_the_tray_menu_closed_and_went_adds_nothing(world):
    # The tray's menu is deleted once hidden (N4): a late answer must neither paint into it nor raise.
    from PyQt6 import sip
    _seed, win, _writer, row = world()
    m = tray_of(win).menu(row)
    m.close()
    assert wait_until(lambda: sip.isdeleted(m), 3)
    settle(100)
    assert win.looks.asks == [list(row.arrival.item_ids)]


def test_E4_a_library_that_cant_be_written_greys_the_entry_with_the_writers_reason_and_writes_nothing(world):
    _seed, win, writer, row = world(writable=False)
    m = tray_of(win).menu(row)
    assert wait_until(lambda: _skip_menu(m) is not None, 5)
    sub = _skip_menu(m)
    assert not sub.menuAction().isEnabled() and not any(a.isEnabled() for a in sub.actions())
    why = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get("busy") or "busy")
    assert sub.menuAction().toolTip() == why and all(a.toolTip() == why for a in sub.actions())
    m.close()
    tray_of(win).skip_folder(row.arrival, win.looks.choices[1])
    settle()
    assert calls(writer, "skip_folder") == []


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_skip_takes_the_arrivals_rows_out_in_one_change_and_one_undo_brings_them_back(world, language):
    # Q7's scenario: a show's Extras waiting in New arrivals skipped from the tray — its rows go, the toast says so,
    # Settings' skipped list is read again; one Undo brings the rows back and reads the list again.
    _seed, win, writer, row = world(language)
    win.mount_settings()                                              # (the Settings row shows the skipped count)
    ids, key, extras = list(row.arrival.item_ids), row.arrival.key, win.looks.choices[1]
    writer.under[extras] = ids
    tray = tray_of(win)
    m = tray.menu(row)
    assert wait_until(lambda: _skip_menu(m) is not None, 5)
    listed = win.looks.listings
    _skip_menu(m).actions()[1].trigger()                              # "Extras"
    m.close()
    assert calls(writer, "skip_folder") == [("skip_folder", ids, {"path": extras})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SKIPPED.format(name="Extras"), 5)
    assert wait_until(lambda: key not in tray.keys(), 5)
    assert wait_until(lambda: win.looks.listings > listed, 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    settle()
    listed = win.looks.listings
    tray.open() if not tray.isVisible() else None
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: key in tray.keys() and list(tray.arrival(key).item_ids) == ids, 5)
    assert wait_until(lambda: win.looks.listings > listed, 5)
    assert [c[0] for c in writer.calls] == ["skip_folder", "undo"]
