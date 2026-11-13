"""⋯ → *Its audiobook…* on any book (Kura-TX; the smoother-UX audit's ask 2, Sonic's yes 2026-11-12; PROVISIONAL words):
a book's row names its audiobook up front — today's picker (`Store.book_audiobooks`: the library's audiobooks with no
book, likeliest first, then *A folder on your computer…*) and today's pairing (*Needs you*'s `pick_audiobook`, its
toast's Undo, Connect kicked) — an EPUB's or a `.txt` book's alike, never only once its first part is mined.

What a wrong answer would cost a learner (Mattias ×3: "I didn't get to tell it I have an audiobook… just creating a
bunch of text-only cards"): no door until mining starts; a second audiobook paired over the first; the store read on
the window's thread at every ⋯ (20,000 rows); a late answer landing in another row's menu.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.qt import strings
from tests.qt.conftest import wait_until

TITLE = "蜘蛛の糸"
JOINED = "C:/Users/me/AppData/Local/Houseki/Surasura/connect/books/txt-ja-0123456789abcdef.txt"


@pytest.fixture
def book_menu(qapp, monkeypatch):
    from PyQt6.QtCore import QPoint
    from tests.fixtures import window_seed
    from tests.qt.test_drag import open_window
    from tests.qt.test_item_menu import ItemWriter, rows_of
    seed = window_seed.build()
    win, services = open_window(qapp, seed, ItemWriter(seed.library, apply=False))
    main, got, picked = threading.main_thread(), [], []
    answer = {"book": {"epub": JOINED, "title": TITLE, "paired": False,
                       "audiobooks": [{"item_id": 77, "title": "The Spider's Thread", "n": 3, "seconds": 1800.0}]}}

    def read(item_id):
        got.append((item_id, threading.current_thread() is not main))
        return answer["book"]
    win.items.read_audiobook = read
    monkeypatch.setattr(win.needs_you, "_pick_audiobook", lambda entry, audio, epub, title: picked.append(
        ("pick", entry, audio, epub, title)))
    monkeypatch.setattr(win.needs_you, "_audiobook_folder", lambda title: picked.append(("folder", title)))
    row = rows_of(win)[4]
    from app.qt import item_menu
    monkeypatch.setattr(item_menu, "book_row", lambda r: r is row)      # (the seed's rows are videos: this, a book's)
    yield win, row, got, answer, picked, (lambda: win.items.menu(row, win.mapToGlobal(QPoint(300, 300))))
    win.close()
    services.shutdown(0.5)


def _entry(m):
    return next((a for a in m.actions() if a.text() == strings.ITEM_MENU["audiobook"][0]), None)


def test_a_books_row_offers_its_audiobook_before_open_its_folder_once_the_store_answers_on_a_worker(book_menu):
    from app.qt import drag
    win, row, got, _answer, _picked, open_menu = book_menu
    m = open_menu()
    assert wait_until(lambda: _entry(m) is not None, 5)
    texts = [a.text() for a in m.actions()]
    assert texts.index(strings.ITEM_MENU["audiobook"][0]) < texts.index(strings.ITEM_MENU["folder"][0])
    assert _entry(m).toolTip() == strings.ITEM_MENU["audiobook"][1]
    assert got == [(drag.ids_of(row)[0], True)], "asked once, on a worker, by the row's first part"
    m.hide()


@pytest.mark.parametrize("book", [None, "paired"])
def test_no_book_or_a_book_already_paired_has_no_entry(book_menu, book):
    """A row the store finds no book for, or a book that has its audiobook already (never a second one over it)."""
    win, _row, got, answer, _picked, open_menu = book_menu
    answer["book"] = None if book is None else dict(answer["book"], paired=True)
    m = open_menu()
    assert wait_until(lambda: got, 5)
    wait_until(lambda: False, 0.3)                      # (its answer had its turn on the window's thread)
    assert _entry(m) is None
    m.hide()


def test_its_press_lists_todays_picker_and_a_pick_pairs_through_needs_yous_own_pairing(book_menu):
    """The press opens today's list: each audiobook with no book, then *A folder on your computer…*; a pick is *Needs
    you*'s own `_pick_audiobook` (its toast's Undo, Connect kicked) with the book's path — a joined `.txt` too."""
    win, _row, _got, _answer, picked, open_menu = book_menu
    m = open_menu()
    assert wait_until(lambda: _entry(m) is not None, 5)
    _entry(m).trigger()
    assert wait_until(lambda: getattr(win.items, "audiobook_list", None) is not None and
                      win.items.audiobook_list.actions(), 5)
    lst = win.items.audiobook_list
    texts = [a.text() for a in lst.actions() if not a.isSeparator()]
    assert texts == [strings.NEEDS_AUDIOBOOK_LINE.format(title="The Spider's Thread", n=3),
                     strings.NEEDS_AUDIOBOOK_FOLDER]
    next(a for a in lst.actions() if a.text() == texts[0]).trigger()
    assert picked == [("pick", None, 77, JOINED, TITLE)]
    lst.hide()


def test_a_folder_on_your_computer_is_needs_yous_own_door(book_menu):
    win, _row, _got, _answer, picked, open_menu = book_menu
    m = open_menu()
    assert wait_until(lambda: _entry(m) is not None, 5)
    _entry(m).trigger()
    assert wait_until(lambda: getattr(win.items, "audiobook_list", None) is not None and
                      win.items.audiobook_list.actions(), 5)
    next(a for a in win.items.audiobook_list.actions() if a.text() == strings.NEEDS_AUDIOBOOK_FOLDER).trigger()
    assert picked == [("folder", TITLE)]
    win.items.audiobook_list.hide()


def test_a_row_of_no_book_asks_the_store_nothing(book_menu):
    """Up next at 20,000 files: ⋯ on a video's row starts no worker (an open makes nothing)."""
    from PyQt6.QtCore import QPoint
    from tests.qt.test_item_menu import rows_of
    win, row, got, _answer, _picked, _open_menu = book_menu
    other = next(r for r in rows_of(win) if r is not row)
    m = win.items.menu(other, win.mapToGlobal(QPoint(300, 300)))
    wait_until(lambda: False, 0.3)
    assert not got and _entry(m) is None
    m.hide()


def test_an_earlier_menus_late_answer_never_lands_in_a_newer_menu(book_menu):
    win, _row, got, answer, _picked, open_menu = book_menu
    hold = threading.Event()
    first = answer["book"]

    def slow(item_id):
        got.append((item_id, True))
        if len(got) == 1:
            hold.wait(5)
            return first
        return None
    win.items.read_audiobook = slow
    open_menu()
    assert wait_until(lambda: got, 5)
    m = open_menu()                                     # a newer open: its own answer is "no book"
    assert wait_until(lambda: len(got) == 2, 5)
    hold.set()
    wait_until(lambda: False, 0.4)
    assert _entry(m) is None
    m.hide()
