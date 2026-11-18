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
        if change is None and self.saved:                # Ctrl+Z: the newest saved change, as the real writer's
            change = next((c for c in reversed(self.saved) if c not in self.undone), None)
        rows = self.taken.pop(getattr(change, "folder", None), None)
        if rows:
            self.library.commit(items=rows, order=True)
        return super().undo(change, label)


class FakeLooks:
    """`SourceLooks.skippable` as ⋯ asks it (`choices`, answered on a thread of its own, as the looks' worker does);
    `listing` counted (Settings' skipped folders read again)."""

    def __init__(self, choices):
        self.choices, self.asks, self.listings = choices, [], 0
        self.under_ids, self.unders = {}, []

    def skippable(self, ids, then):
        self.asks.append(list(ids))
        threading.Thread(target=then, args=(list(self.choices),), daemon=True).start()
        return True

    def under(self, path, then):
        """Kura-NA: the items a skip of `path` takes, as the store reads them (`under_ids`), on a thread of its own."""
        self.unders.append(path)
        threading.Thread(target=then, args=(self.under_ids.get(path),), daemon=True).start()
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


def test_an_answer_after_the_tray_menu_closed_adds_nothing(world):
    # The tray's menu is kept and emptied once hidden (N4, R5 since 2026-11-06): a late answer must neither put its
    # entry into the closed menu (the next row's open would show it) nor raise.
    _seed, win, _writer, row = world()
    m = tray_of(win).menu(row)
    m.close()
    assert wait_until(lambda: not m.isVisible(), 3)
    settle(100)
    assert win.looks.asks == [list(row.arrival.item_ids)]
    assert m.actions() == [] and _skip_menu(m) is None


def test_a_late_answer_for_a_closed_menu_never_lands_in_the_picks_menu_opened_next(world):
    # The tray's one kept menu (R5) is the picks' menu at the next open: the folder answer row A's ⋯ asked for, coming
    # after it closed, must not add *Never read this folder* (for row A) to the picks' menu (Mado-WF review B1).
    import threading
    _seed, win, _writer, row = world()
    held = []
    looks = win.looks
    real = looks.skippable

    def hold(ids, then):
        looks.asks.append(list(ids))
        held.append(then)
        return True
    looks.skippable = hold
    tray = tray_of(win)
    m = tray.menu(row)
    assert held
    m.close()
    rs = tray_rows(win)
    tray.pick(rs[0].key)
    tray.pick(rs[1].key)
    picks = tray.menu(rs[0].key)
    assert picks is m and picks.isVisible()
    for then in held:                                 # the late answer, from the looks' worker
        threading.Thread(target=then, args=(list(looks.choices),), daemon=True).start()
    settle(300)
    try:
        assert _skip_menu(picks) is None
    finally:
        picks.close()
        looks.skippable = real


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


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_skips_rows_leave_at_its_press_while_the_store_is_busy_and_come_back_with_its_undo(world, language):
    # Kura-NA (a Send report: "when i selected the folder to skip i expected to immediately remove it from new arrivals
    # but its still there"): the store busy (the skip waits to be saved), the row it was asked from leaves at the press,
    # and every other row the store says lies under the folder leaves once that read answers — before anything is
    # saved. Undone before it lands, they come back; nothing else moved.
    _seed, win, writer, row = world(language)
    tray = tray_of(win)
    rows = tray_rows(win)
    other = next(r for r in rows if r.key != row.key)
    stays = [r.key for r in rows if r.key not in (row.key, other.key)]
    extras = win.looks.choices[1]
    win.looks.under_ids[extras] = list(row.arrival.item_ids) + list(other.arrival.item_ids)
    writer.under[extras] = win.looks.under_ids[extras]
    writer.stuck = True
    tray.skip_folder(row.arrival, extras)
    assert row.key not in tray.keys()                                 # the press itself, nothing saved yet
    assert wait_until(lambda: other.key not in tray.keys(), 5)        # the store's read: its other row too
    assert writer.pending() == 1 and all(k in tray.keys() for k in stays)
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: row.key in tray.keys() and other.key in tray.keys(), 5)
    assert tray.leaving == frozenset()
    writer.free()


def test_a_row_only_partly_under_the_folder_stays_until_the_store_says(world):
    # The store's read is the truth: a row of a title whose episodes lie in two folders keeps showing (only the files
    # under the folder leave, in the store's own view), though the press hid it at first.
    _seed, win, writer, _row = world()
    tray = tray_of(win)
    row = max(tray_rows(win), key=lambda r: len(r.arrival.item_ids))     # a title of several episodes
    extras = win.looks.choices[1]
    ids = list(row.arrival.item_ids)
    assert len(ids) > 1, "why: a row of one file can't be partly under the folder"
    win.looks.under_ids[extras] = ids[:-1]
    writer.stuck = True
    tray.skip_folder(row.arrival, extras)
    assert row.key not in tray.keys()
    assert wait_until(lambda: row.key in tray.keys(), 5)
    writer.free()


def test_a_skip_the_writer_refuses_takes_no_row_away(world):
    _seed, win, writer, row = world(writable=False)
    tray = tray_of(win)
    tray.skip_folder(row.arrival, win.looks.choices[1])
    settle()
    assert row.key in tray.keys() and tray.leaving == frozenset() and calls(writer, "skip_folder") == []


def test_settings_skip_a_folder_takes_the_trays_rows_of_that_folder_at_its_press(world):
    # Settings' *Skip a folder…* (no row asked it): every row the store says lies under the folder leaves New arrivals
    # once that read answers — before the busy store saves the skip.
    from app.qt import item_menu
    _seed, win, writer, row = world()
    tray = tray_of(win)
    folder = win.looks.choices[2]
    win.looks.under_ids[folder] = list(row.arrival.item_ids)
    writer.stuck = True
    assert item_menu.give_skip(win.moves, folder) is not None
    assert wait_until(lambda: row.key not in tray.keys(), 5) and writer.pending() == 1
    writer.free()


def test_two_skips_at_once_one_undone_keeps_the_others_rows_out(world):
    # Two skips under way (the store busy), their rows overlapping: undoing one brings back only what the other doesn't
    # take.
    _seed, win, writer, row = world()
    tray = tray_of(win)
    other = next(r for r in tray_rows(win) if r.key != row.key)
    a, b = win.looks.choices[0], win.looks.choices[1]
    win.looks.under_ids[a] = list(row.arrival.item_ids)
    win.looks.under_ids[b] = list(row.arrival.item_ids) + list(other.arrival.item_ids)
    writer.stuck = True
    tray.skip_folder(row.arrival, a)
    tray.skip_folder(other.arrival, b)
    assert wait_until(lambda: row.key not in tray.keys() and other.key not in tray.keys(), 5)
    first = next(t for t in win.moves.tickets if t.text == strings.ITEM_SKIPPED.format(name=os.path.basename(a)))
    win.moves.undo(first)
    settle(200)
    assert row.key not in tray.keys() and other.key not in tray.keys()      # skip b still takes both
    writer.free()


def test_a_saved_skips_items_put_back_later_show_again(world):
    # Saved, the store's view keeps them out; brought back later under their old ids (the Removed list's *Put back*),
    # they show — the press's hiding never outlives the store's own view.
    _seed, win, writer, row = world()
    tray = tray_of(win)
    extras = win.looks.choices[1]
    win.looks.under_ids[extras] = writer.under[extras] = list(row.arrival.item_ids)
    tray.skip_folder(row.arrival, extras)
    assert wait_until(lambda: not win.moves.tickets and row.key not in tray.keys(), 5)
    settle(200)
    assert tray.leaving == frozenset()
    rows = writer.taken.pop(1)
    writer.library.commit(items=rows, order=True)                             # Put back, outside the skip's Undo
    assert wait_until(lambda: row.key in tray.keys(), 5)


def test_a_skip_whose_hand_over_breaks_brings_its_rows_back(world, monkeypatch):
    # The writer raising as the skip is handed over (H8): nothing was skipped, so nothing stays hidden.
    _seed, win, writer, row = world()
    tray = tray_of(win)

    def broke(path, label=None):
        raise OSError("the writer's journal can't be written")
    monkeypatch.setattr(writer, "skip_folder", broke)
    with pytest.raises(OSError):
        tray.skip_folder(row.arrival, win.looks.choices[1])
    settle(200)
    assert row.key in tray.keys() and tray.leaving == frozenset()


def test_ctrl_z_of_a_saved_skip_before_the_next_view_shows_its_rows_again(world):
    # Saved, then undone by Ctrl+Z before the store's next view landed: Ctrl+Z labels its undo with a ticket of its own,
    # so the skip's ticket hears no "undone" and the view still holds the rows — the drag controller's skip hook
    # (`_skips_moved(undone=True)`) tells the tray, and the rows are the store's to show again.
    from types import SimpleNamespace
    from app.qt import drag
    _seed, win, _writer, row = world()
    tray = tray_of(win)
    win.looks.under_ids = {}
    told = tray.skip_leaves(win.looks.choices[1], list(row.arrival.item_ids))
    assert row.key not in tray.keys()
    told("saved")                                                             # (no new view yet: the rows are in it)
    assert row.key not in tray.keys()
    drag._skips_moved(win, SimpleNamespace(folder=1), undone=True)            # Ctrl+Z's undo of it landed
    assert row.key in tray.keys() and tray.leaving == frozenset()
