"""A book's whole Remove, its own *Rename…*, and New arrivals' *Replace 「…」* (Kura-AB5; 11-20 report;
Sonic's yes to all three, words PROVISIONAL).

The learner removed the old version of his book: its parts sat in three rows, so it took three Removes. He wanted the
new version called by the book's name — a book's row had no *Rename…*. And the new version should have replaced the
old one, keeping its name and its audiobook, asked once in New arrivals.

- ⋯ › *Remove…* on any row of a book reads the whole book on a worker (`Store.book_items`) and asks about all of it:
  *Remove the whole book* (one change, one Undo) — or only this row's parts (the card's box);
- ⋯ › *Rename…* on a book's row: its own name (`Writer.rename_work`), its toast's Undo;
- New arrivals' ⋯ on a new version gets *Replace 「…」* first (`Store.new_version_of`, read on a worker as ⋯ opens):
  one writer change (`Writer.replace_book`) with its toast's Undo.

What a wrong answer would cost a learner: a book half removed (its other rows' parts left, their cards still counted),
a removal the window can't undo in one; a rename that a look renames back, or one written on a library that can't be
saved; a replacement that drops the old version without its audiobook, or one offered for a book that isn't one.

On the window's seed (its Japanese and Chinese titles from tests/Test Resources/) through a recording writer; the
store's own answers and writes are tests/test_audiobook_book_gone.py's.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.qt import arrivals, drag, strings
from tests.qt.conftest import wait_until
from tests.qt.test_item_menu import ItemWriter, calls, rows_of


class BookWriter(ItemWriter):
    def rename_work(self, work_id, title, label=None):
        return self._put("rename_work", [], label, work_id=work_id, title=title)


@pytest.fixture
def world(qapp, monkeypatch):
    made = []

    def make(book=None, writable=True):
        from tests.fixtures import window_seed
        from tests.qt.test_drag import open_window
        seed = window_seed.build()
        writer = BookWriter(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
        made.append((win, services))
        row = rows_of(win)[4]
        from app.qt import item_menu
        monkeypatch.setattr(item_menu, "book_row", lambda r: r is row)   # (the seed's rows are videos: this, a book's)
        main, asked = threading.main_thread(), []

        def read(item_id):
            asked.append((item_id, threading.current_thread() is not main))
            return book(row) if callable(book) else book
        win.items.read_book = read
        return seed, win, writer, row, asked
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _card(items):
    q = items.question
    return q if q is not None and q.isVisible() else None


def _whole(row, more=(9001, 9002)):
    return {"epub": "D:/Drop/吾輩は猫である.epub", "title": "吾輩は猫である", "ids": list(drag.ids_of(row)) + list(more)}


# --- B3 2: the whole book's Remove ---------------------------------------------------------------------------------- #
def test_a_books_remove_reads_the_whole_book_on_a_worker_and_removes_every_part_at_once(world):
    _seed, win, writer, row, asked = world(_whole)
    win.items.menu_pick(row, "remove")
    assert wait_until(lambda: _card(win.items) is not None, 5)
    assert asked == [(drag.ids_of(row)[0], True)], "asked once, on a worker, by the row's first part"
    q = _card(win.items)
    n = len(drag.ids_of(row)) + 2
    assert q.title.text() == strings.ITEM_REMOVE_BOOK_ASK.format(title="吾輩は猫である")
    assert q.yes.text() == strings.ITEM_REMOVE_BOOK_YES and q.default is q.no      # Cancel stays the default
    assert strings.ITEM_REMOVE_BOOK_BODY.format(n=n) in q.body.text()
    q.yes.click()
    assert calls(writer, "remove") == [("remove", list(drag.ids_of(row)) + [9001, 9002], {})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_REMOVED.format(title="吾輩は猫である"), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert [c.op for c in writer.undone] == ["remove"], "one Undo for the whole book"


def test_the_cards_box_removes_only_this_rows_parts(world):
    _seed, win, writer, row, _asked = world(_whole)
    win.items.menu_pick(row, "remove")
    assert wait_until(lambda: _card(win.items) is not None, 5)
    q = _card(win.items)
    assert q.check is not None and not q.check.isChecked()
    assert q.check.text() == strings.ITEM_REMOVE_BOOK_ONLY.format(k=len(drag.ids_of(row)))
    q.check.setChecked(True)
    q.yes.click()
    assert calls(writer, "remove") == [("remove", drag.ids_of(row), {})]


@pytest.mark.parametrize("book", [None, "row only"])
def test_a_book_wholly_in_this_row_or_none_found_is_asked_as_any_row(world, book):
    """Every part already in the row (or the store found no book): today's card, its files counted."""
    _seed, win, writer, row, _asked = world((lambda r: {"epub": "x.epub", "title": r.title,
                                                         "ids": list(drag.ids_of(r))}) if book else None)
    win.items.menu_pick(row, "remove")
    assert wait_until(lambda: _card(win.items) is not None, 5)
    q = _card(win.items)
    assert q.title.text() == strings.ITEM_REMOVE_ASK.format(title=row.title) and q.check is None
    q.yes.click()
    assert calls(writer, "remove") == [("remove", drag.ids_of(row), {})]


def test_a_video_rows_remove_asks_the_store_nothing(world):
    _seed, win, _writer, row, asked = world(_whole)
    other = next(r for r in rows_of(win) if r is not row)
    win.items.menu_pick(other, "remove")
    assert wait_until(lambda: _card(win.items) is not None, 5)
    assert asked == [] and _card(win.items).title.text() == strings.ITEM_REMOVE_ASK.format(title=other.title)


# --- B3 4: a book's *Rename…* --------------------------------------------------------------------------------------- #
def test_a_books_row_offers_rename_and_a_new_name_is_one_writer_change_with_undo(world):
    _seed, win, writer, row, _asked = world()
    names = [e.name for e in win.items.entries(row)]
    assert "rename-book" in names and names.index("rename-book") < names.index("folder")
    other = next(r for r in rows_of(win) if r is not row and not getattr(r, "group", False))
    assert "rename-book" not in [e.name for e in win.items.entries(other)], "a video's row: no book's Rename"
    win.items.menu_pick(row, "rename-book")
    assert wait_until(lambda: _card(win.items) is not None, 5)
    q = _card(win.items)
    assert q.title.text() == strings.ITEM_RENAME_BOOK_ASK and q.field.text() == row.title
    q.field.setText("  吾輩は猫である ")
    q.yes.click()
    assert calls(writer, "rename_work") == [("rename_work", [], {"work_id": row.work_id, "title": "吾輩は猫である"})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_RENAMED.format(title=row.title,
                                                                                      name="吾輩は猫である"), 5)


@pytest.mark.parametrize("text", ["", "   ", None])
def test_an_empty_name_or_the_same_one_writes_nothing(world, text):
    _seed, win, writer, row, _asked = world()
    assert win.items.rename_book(row, row.title if text is None else text) is None
    assert calls(writer, "rename_work") == []


def test_E4_a_library_that_cant_be_written_greys_rename(world):
    _seed, win, writer, row, _asked = world(writable=False)
    entry = next(e for e in win.items.entries(row) if e.name == "rename-book")
    assert not entry.ok
    assert win.items.ask_rename_book(row) is None and calls(writer) == []


# --- B3 3: New arrivals' *Replace 「…」* ----------------------------------------------------------------------------- #
@pytest.fixture
def tray(qapp):
    made = []

    def make(offer):
        from tests.fixtures import window_seed
        from tests.qt.test_arrivals import ArrivalsWriter, open_tray, open_window, tray_rows

        class ReplaceWriter(ArrivalsWriter):
            def replace_book(self, old_ids, new_epub, old_epub, label=None):
                return self._put("replace_book", list(old_ids), label, new_epub=new_epub, old_epub=old_epub)
        seed = window_seed.build()
        writer = ReplaceWriter(seed.library)
        win, services = open_window(qapp, seed, writer)
        open_tray(win)
        row = tray_rows(win)[0]
        main, asked = threading.main_thread(), []

        def read(item_id):
            asked.append((item_id, threading.current_thread() is not main))
            return offer
        win.needs_you.read_new_version = read
        made.append((win, services))
        return win, writer, row, asked
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


OFFER = {"old": {"epub": "D:/Drop/吾輩は猫である.epub", "title": "吾輩は猫である", "ids": [501, 502, 503],
                 "replaced": [502, 503], "kept": [501]},              # Kura-AB6: part 1 read (Finished)
         "new": {"epub": "D:/Drop/吾輩は猫である-章分割-注なし.epub", "title": "吾輩は猫である-章分割-注なし", "ids": [601, 602]}}


def _replace(m):
    words = strings.TRAY_REPLACE[0].format(old="吾輩は猫である")
    return next((a for a in m.actions() if a.text() == words), None)


def test_a_new_version_gets_replace_first_in_its_menu_and_a_press_is_one_change_with_undo(tray):
    from tests.qt.test_arrivals import tray_of
    win, writer, row, asked = tray(OFFER)
    m = tray_of(win).menu(row)
    assert wait_until(lambda: _replace(m) is not None, 5)
    assert asked == [(row.arrival.item_ids[0], True)]
    act = _replace(m)
    assert m.actions()[0] is act, "first"
    assert act.toolTip() == arrivals.replace_tip(OFFER)
    assert "2 unread parts" in act.toolTip() and "part you've read" in act.toolTip()
    act.trigger()
    got = [c for c in writer.calls if c[0] == "replace_book"]
    assert got == [("replace_book", [502, 503], {"new_epub": OFFER["new"]["epub"],
                                                       "old_epub": OFFER["old"]["epub"]})]
    assert wait_until(lambda: win.toasts.card.message == strings.TRAY_REPLACED.format(old="吾輩は猫である"), 5)
    m.close()


def test_replaces_tip_counts_the_unread_parts_that_go_and_the_read_ones_that_stay():
    """Kura-AB6: the tip says how many of the old book's parts go to Removed (the unread ones) and how many stay (the
    read ones) — one or many, and no *stay* line when none was read."""
    def offer(replaced, kept):
        return {"old": dict(OFFER["old"], replaced=replaced, kept=kept), "new": OFFER["new"]}
    tip = arrivals.replace_tip(offer([502], [501, 503]))
    assert strings.TRAY_REPLACE_GONE[1] in tip and strings.TRAY_REPLACE_KEPT[0].format(n=2) in tip
    tip = arrivals.replace_tip(offer([501, 502, 503], []))
    assert strings.TRAY_REPLACE_GONE[0].format(n=3) in tip and "you've read" not in tip
    assert tip.startswith(strings.TRAY_REPLACE[1].split("{")[0].strip()) and tip.endswith("Undo puts it all back")
    assert "吾輩は猫である" in tip and "{" not in tip


def test_an_arrival_that_is_no_new_version_gets_no_replace(tray):
    from tests.qt.test_arrivals import tray_of
    win, _writer, row, asked = tray(None)
    m = tray_of(win).menu(row)
    assert wait_until(lambda: asked, 5)
    wait_until(lambda: False, 0.3)                      # (its answer had its turn on the window's thread)
    assert _replace(m) is None
    m.close()
