"""The window's half of Kura-AB2 (Mattias's 3.0.0 field report, issue 3; PROVISIONAL): a book about to be mined with
no audiobook paired asks *Do you have 「…」's audiobook?* on *Needs you* — *Pick its audiobook…* (the library's
audiobooks with no book, read on a worker; a pick pairs them through the writer, its toast's Undo, and Connect is
kicked once it saved) · *Mine without audio* (Connect's answer, on a worker, then a kick). On the window's seed with a
writer that records.

What a wrong answer would cost a learner: a pick that pairs another audiobook than the one chosen (wrong clips on
every card), a store read on the window's thread (a freeze), a press that does nothing while the book waits, or an
answer that never reaches Connect (the book waits for good).
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import runner
from app.qt import strings
from tests.qt.conftest import wait_until
from tests.qt.test_audiobook_find_window import _with_audiobook_writer
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

NEKO = "吾輩は猫である"


@pytest.fixture
def ask(world):  # noqa: F811
    _with_audiobook_writer()
    main, got = threading.main_thread(), []

    def rec(name, value=True):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return value
        return call
    say = runner.BOOK_AUDIO_ASK.format(title=NEKO)
    connect = {"jobs": [{"item": 7, "state": "waiting", "reason": say}],
               "needs": [{"id": 21, "kind": runner.BOOK_AUDIO_NEED, "say": say, "item": 7, "seen_at": None,
                          "at": "2026-11-01T05:00:00Z"}]}
    seed, win, writer, ny = world(connect=connect, connect_calls={"book_audiobook": rec("book_audiobook"),
                                                                  "kick": rec("kick", None)})
    read = []

    def read_audiobooks(item_id):
        read.append((item_id, threading.current_thread() is not main))
        return {"epub": "D:/Books/吾輩は猫である.epub", "title": NEKO,
                "audiobooks": [{"item_id": 901, "title": "I Am a Cat", "n": 12, "seconds": 33120},
                               {"item_id": 902, "title": "坊っちゃん", "n": 6, "seconds": 18000}]}
    ny.read_audiobooks = read_audiobooks
    entry = next(e for e in ny.entries if e.kind == runner.BOOK_AUDIO_NEED)
    return win, writer, ny, entry, got, read


def test_the_books_card_asks_with_its_two_answers(ask):
    _win, _writer, ny, entry, _got, _read = ask
    assert entry.title == runner.BOOK_AUDIO_ASK.format(title=NEKO)
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"pick_audiobook", "no_audiobook", "dismiss"}
    assert button(ny, entry.key, "pick_audiobook").text() == strings.NEEDS_ACTIONS["pick_audiobook"][0]
    assert button(ny, entry.key, "no_audiobook").text() == strings.NEEDS_ACTIONS["no_audiobook"][0]


def test_pick_its_audiobook_reads_on_a_worker_and_a_pick_pairs_that_audiobook_with_the_book(ask):
    _win, writer, ny, entry, got, read = ask
    button(ny, entry.key, "pick_audiobook").click()
    assert wait_until(lambda: ny.last_menu is not None and ny.last_menu.actions(), 5)
    assert read == [(7, True)]                                       # never on the window's thread
    labels = [a.text() for a in ny.last_menu.actions() if not a.isSeparator()]
    assert labels == ["I Am a Cat · 12 files", "坊っちゃん · 6 files", strings.NEEDS_AUDIOBOOK_FOLDER]
    next(a for a in ny.last_menu.actions() if a.text().startswith("I Am a Cat")).trigger()
    assert wait_until(lambda: any(c[0] == "audiobook_pick" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "audiobook_pick"] == [("audiobook_pick", [901],
                                                                      {"path": "D:/Books/吾輩は猫である.epub"})]


def test_a_folder_on_your_computer_becomes_a_library_folder(ask):
    win, _writer, ny, entry, _got, _read = ask
    folders, starts = [], []
    win.adder.read_folder = lambda folder, first=False, book=None: folders.append((folder, book)) or True
    ny.pick_folder = lambda _title, start: starts.append(start) or "D:/Audio/I Am a Cat"
    menu = ny._audiobooks_menu(entry, {"epub": "D:/Books/b.epub", "title": NEKO, "audiobooks": []})
    [only] = [a for a in menu.actions() if not a.isSeparator()]
    assert only.text() == strings.NEEDS_AUDIOBOOK_FOLDER
    only.trigger()
    assert folders == [("D:/Audio/I Am a Cat", {"epub": "D:/Books/b.epub", "title": NEKO})]   # Kura-AB4: the book told
    from app.qt import windows
    assert starts == [windows.content_folder()]          # Fresh-U row 11: never the program's own folder ("")


def test_mine_without_audio_answers_connect_on_a_worker_then_kicks_it(ask):
    _win, _writer, ny, entry, got, _read = ask
    button(ny, entry.key, "no_audiobook").click()
    assert wait_until(lambda: [g[0] for g in got] == ["book_audiobook", "kick"], 5)
    assert got[0][1] == ("ja", 21) and got[0][2] and got[1][2]
