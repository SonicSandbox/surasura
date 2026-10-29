"""The window's half of a5-2 (Hon): *Find its book…* and *It has no book* on an audiobook's card after a *No*, and the
🎧 before a title with its words in its hover (`app/qt/needs.py`, `app/qt/rows.py`, `app/qt/arrivals.py`,
`app/qt/importers.py`). On the window's seed with a writer that records.

What a wrong answer would cost a learner: a pick that pairs another book than the one chosen, a store read on the
window's thread (a freeze), an EPUB from disk that never joins (or joins a book it wasn't), a press that does nothing,
or a 🎧 whose words never show.
"""
import os
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QRect

from app.qt import arrivals, rows, strings
from app.services import needs as service
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import NeedsWriter, button, world  # noqa: F401 (the fixture)

NEKO, BOCCHAN = "吾輩は猫である", "坊っちゃん"


def _with_audiobook_writer():
    def pick_audiobook(self, item_id, epub, label=None):
        return self._put("audiobook_pick", [item_id], label, path=epub)

    def audiobook_no_book(self, item_id, label=None):
        return self._put("audiobook_no_book", [item_id], label)
    NeedsWriter.pick_audiobook = pick_audiobook
    NeedsWriter.audiobook_no_book = audiobook_no_book


@pytest.fixture
def find(world):  # noqa: F811
    _with_audiobook_writer()
    ask = {"kind": service.AUDIOBOOK_FIND, "item_id": 901, "title": NEKO, "said_no": BOCCHAN,
           "files": ["D:/Audio/01.mp3", "D:/Audio/12.mp3"], "seconds": 33120}
    seed, win, writer, ny = world(asks=[ask])
    main, asked = threading.main_thread(), []

    def read_books(item_id):
        asked.append((item_id, threading.current_thread() is not main))
        return [{"epub": "D:/Books/neko.epub", "title": NEKO, "parts": 7, "sha256": "a", "work_id": 1},
                {"epub": "D:/Books/bocchan.epub", "title": BOCCHAN, "parts": 5, "sha256": "b", "work_id": 2}]
    ny.read_books = read_books
    return win, writer, ny, ny.entries[[e.kind for e in ny.entries].index(service.AUDIOBOOK_FIND)], asked


def test_the_find_card_shows_its_two_answers(find):
    _win, _writer, ny, entry, _asked = find
    assert entry.title == f"Which book does the audiobook 「{NEKO}」 read?"
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} >= {"find_book", "no_book"}
    assert button(ny, entry.key, "find_book").text() == strings.NEEDS_ACTIONS["find_book"][0]


def test_find_its_book_reads_the_books_on_a_worker_and_a_pick_pairs_that_book(find):
    _win, writer, ny, entry, asked = find
    button(ny, entry.key, "find_book").click()
    assert wait_until(lambda: ny.last_menu is not None and ny.last_menu.actions(), 5)
    assert asked == [(901, True)]                                    # never on the window's thread
    labels = [a.text() for a in ny.last_menu.actions() if not a.isSeparator()]
    assert labels == [f"{NEKO} · 7 parts", f"{BOCCHAN} · 5 parts", strings.NEEDS_FIND_FILE]
    next(a for a in ny.last_menu.actions() if a.text().startswith(NEKO)).trigger()
    assert wait_until(lambda: any(c[0] == "audiobook_pick" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "audiobook_pick"] == [("audiobook_pick", [901],
                                                                      {"path": "D:/Books/neko.epub"})]


def test_it_has_no_book_is_one_write(find):
    _win, writer, ny, entry, _asked = find
    button(ny, entry.key, "no_book").click()
    assert wait_until(lambda: any(c[0] == "audiobook_no_book" for c in writer.calls), 5)
    assert [c[:2] for c in writer.calls if c[0] == "audiobook_no_book"] == [("audiobook_no_book", [901])]


def test_an_epub_from_disk_opens_extract_with_it_and_joins_once_it_is_added(find, tmp_path):
    _win, writer, ny, entry, _asked = find
    said = []
    ny._say = said.append
    ny.pick_file = lambda _title, _folder: str(tmp_path / "notes.txt")
    ny._book_from_disk(entry)
    assert said == [strings.NEEDS_FIND_NOT_EPUB] and not any(c[0] == "audiobook_pick" for c in writer.calls)
    opened = []

    class Extract:
        path = SimpleNamespace(setText=lambda text: opened.append(("text", text)))

        def choose(self, path):
            opened.append(("choose", path))
    extract = Extract()
    ny.open_extract = lambda _win: extract
    book = tmp_path / "新しい本.epub"
    book.write_bytes(b"PK new book")
    book = str(book)
    ny.pick_file = lambda _title, _folder: book
    ny._book_from_disk(entry)
    assert wait_until(lambda: opened, 5)                             # looked up on a worker first: not held
    assert opened == [("text", book), ("choose", book)]
    assert not any(c[0] == "audiobook_pick" for c in writer.calls)  # nothing until Extract has added it
    assert extract.on_added[0] == os.path.abspath(book)             # waiting for THAT file only
    extract.on_added[1](os.path.abspath(book))
    assert wait_until(lambda: any(c[0] == "audiobook_pick" for c in writer.calls), 5)
    assert [c[2] for c in writer.calls if c[0] == "audiobook_pick"] == [{"path": os.path.abspath(book)}]


def test_an_epub_the_library_holds_is_picked_at_once_by_its_path_or_its_bytes(find, tmp_path):
    """R3-6: the book already in (its own file, or its bytes under another name) never goes through Extract (which
    would answer *already* and pair nothing): picked as from the menu."""
    _win, writer, ny, entry, _asked = find
    copy = tmp_path / "neko copy.epub"
    copy.write_bytes(b"PK neko's bytes")
    from app.library_store import sha256_of
    ny.read_books = lambda _i: [{"epub": "D:/Books/neko.epub", "title": NEKO, "parts": 7,
                                 "sha256": sha256_of(str(copy)), "work_id": 1}]
    ny.open_extract = lambda _win: pytest.fail("Extract opened for a book the library holds")
    ny.pick_file = lambda _title, _folder: str(copy)
    ny._book_from_disk(entry)
    assert wait_until(lambda: any(c[0] == "audiobook_pick" for c in writer.calls), 5)
    assert [c[2] for c in writer.calls if c[0] == "audiobook_pick"] == [{"path": "D:/Books/neko.epub"}]


@pytest.mark.parametrize("key, started, joins", [("done", "D:/Books/本.epub", True),
                                                  ("taken", "D:/Books/本.epub", False),
                                                  ("failed", "D:/Books/本.epub", False),
                                                  ("done", "D:/Books/別の本.epub", False)])
def test_extract_tells_the_audiobook_only_when_its_book_was_added(monkeypatch, key, started, joins):
    from app.qt import importers
    from app import importers_view
    monkeypatch.setattr(importers_view, "extract_outcome",
                        lambda code, result, why: (key, {"parts": 3, "section": "now", "name": "本", "why": "x",
                                                         "title": "本"}))
    told = []
    fake = SimpleNamespace(_result=None, _why=lambda: None, say=lambda _l: None, end_write=lambda _l=None: None,
                           _failed_line=lambda why: why, on_added=(os.path.abspath("D:/Books/本.epub"), told.append),
                           _started=started)
    importers.ExtractWindow._done(fake, 0)
    assert told == ([os.path.abspath("D:/Books/本.epub")] if joins else [])
    assert (fake.on_added is None) == joins          # a failed run (or another book's job) keeps waiting for its file


# --- the 🎧 before a title ----------------------------------------------------------------------------------------- #
def _row(audio):
    return view_rows.Row(*([None] * len(view_rows.Row._fields)))._replace(title=NEKO, audio=audio, episodes=())


def test_the_headphones_go_before_the_title_and_carry_the_words():
    tip = f"🎧 With its audiobook 「{NEKO}」\n12 files (01.mp3 … 12.mp3) · 9 h 12 min"
    assert rows.heard_title(_row(tip)) == f"🎧 {NEKO}" and rows.heard_title(_row("")) == NEKO
    assert rows.heard_title(_row(None)) == NEKO                     # a first-screen cache from before: plain
    [(name, rect, said, _p)] = rows._audio_part(_row(tip), QRect(100, 10, 300, 40), "row-title")
    assert name == "audio" and said == tip and rect.left() == 100 and 0 < rect.width() < 300
    assert rows._audio_part(_row(""), QRect(100, 10, 300, 40), "row-title") == []


def test_a_new_arrivals_row_says_its_audiobook_on_hover():
    a = SimpleNamespace(audio="🎧 Audio only 「銀河鉄道の夜」", tip="3 parts")
    assert arrivals.part_tip(a, "row") == a.audio and arrivals.part_tip(a, "number") == "3 parts"
    assert arrivals.part_tip(SimpleNamespace(audio="", tip=""), "row") is None
