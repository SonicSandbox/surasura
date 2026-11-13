"""The window's half of a book's audiobook picked by its folder (Kura-AB4; Mattias's 3.0.6 report, words PROVISIONAL).

- The book's *A folder on your computer…* names the book to the read (`Adder.read_folder(book=)` → the looks'
  `add(book=)`), so its look pairs the audiobook there with that book (the store's half:
  `tests/test_audiobook_folder_pick.py`).
- What the read did is said: *The audiobook joins 「…」* when it joined; one already in the library and still without a
  book is picked for it (*Needs you*'s own `_pick_audiobook`, its toast's Undo); several, or none, said in the bar.
- + Add's own *A folder…*, an audiobook in it H-8 asks about: a toast *「…」's audiobook?* · *Pair it* — the question's
  *Yes* through the writer (`answer_audiobook`), never a silent pairing.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QPushButton

from app.qt import strings
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, open_window
from tests.qt.test_window_sources import RecordingLooks

EPUB = os.path.join("D:" + os.sep, "Books", "吾輩は猫である.epub")
TITLE = "吾輩は猫である"


class AudioWriter(FakeWriter):
    def answer_audiobook(self, item_id, yes, key=None, label=None):
        return self._put("audiobook_answer", [item_id], label, yes=bool(yes), key=key)

    def audiobook_separate(self, item_id, key, label=None):
        return self._put("audiobook_separate", [item_id], label, key=key)


class AnsweringLooks(RecordingLooks):
    """The looks' `add`, recorded with the book it was told, answering `said` as the read's audiobooks."""

    def __init__(self, said=None):
        super().__init__()
        self.added, self.said = [], said or {"joined": [], "alone": [], "asks": []}

    def add(self, path, then, first=False, book=None):
        self.added.append((path, book))
        then(dict({"path": path, "root": 9, "refused": None, "result": {"added": 1}, "arrivals": 0, "language": "ja",
                   "audiobooks": self.said}, **self.more))
        return True

    more = {}


@pytest.fixture
def window(qapp):
    made = []

    def make(looks):
        seed = window_seed.build()
        writer = AudioWriter(seed.library, apply=False)
        win, services = open_window(qapp, seed, writer)
        services.source_looks = looks
        win._open_looks(None)
        made.append((win, services))
        return win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _folder():
    return os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "audiobook")


def test_the_books_folder_pick_tells_the_read_which_book_and_says_it_joined(window, monkeypatch):
    """*A folder on your computer…* from the book's question: the read is told the book (its EPUB and title); its look
    joined the audiobook → the toast *The audiobook joins 「…」*, its Undo the way back (*Separate them*, journalled)."""
    looks = AnsweringLooks({"joined": [{"item_id": 41, "key": "k-41"}], "alone": [], "asks": []})
    win, _writer = window(looks)
    monkeypatch.setattr(win.needs_you, "pick_folder", lambda title, start: _folder())
    win.needs_you._audiobook_folder(TITLE, EPUB)
    assert wait_until(lambda: looks.added, 5)
    assert looks.added == [(os.path.normpath(_folder()), {"epub": EPUB, "title": TITLE})]
    assert wait_until(lambda: win.toasts.alive and win.toasts.text == strings.NEEDS_PICKED.format(book=TITLE), 5), \
        win.toasts.text
    undo = _button(win, strings.TOAST_UNDO)
    assert undo is not None
    undo.click()
    assert wait_until(lambda: [c for c in _writer.calls if c[0] == "audiobook_separate"], 5)
    assert [c for c in _writer.calls if c[0] == "audiobook_separate"] == [("audiobook_separate", [41],
                                                                           {"key": "k-41"})]


@pytest.mark.parametrize("more", [{"later": True}, {"result": {"added": 0, "reachable": False}}],
                         ids=["deferred", "unreachable"])
def test_a_read_that_didnt_run_says_nothing_about_audiobooks(window, more):
    """A look deferred (the store busy) or a folder not reachable: no audiobook was looked for — nothing is said about
    one (the read's own line stands), nothing picked."""
    looks = AnsweringLooks({"joined": [], "alone": [], "asks": []})
    looks.more = more
    win, writer = window(looks)
    assert win.adder.read_folder(_folder(), book={"epub": EPUB, "title": TITLE})
    assert wait_until(lambda: looks.added, 5)
    wait_until(lambda: False, 0.3)
    assert win.bar_line.full() != strings.NEEDS_AUDIOBOOK_NONE_IN.format(name="audiobook", book=TITLE)
    assert not [c for c in writer.calls if c[0].startswith("audiobook")]


def test_setups_first_scan_never_leads_into_a_pairing(window):
    looks = AnsweringLooks({"joined": [], "alone": [], "asks": [{"item_id": 61, "key": "k-61", "book": TITLE,
                                                                  "epub": EPUB}]})
    win, _writer = window(looks)
    assert win.adder.read_folder(_folder(), first=True)
    assert wait_until(lambda: looks.added, 5)
    wait_until(lambda: False, 0.3)
    assert _button(win, strings.ADD_AUDIOBOOK_PAIR_IT[0]) is None


def test_one_already_in_alone_is_picked_for_the_book_with_its_undo(window, monkeypatch):
    """The folder read before (its audiobook alone in New arrivals — Mattias's stray): picked now for the book, it is
    paired by *Needs you*'s own pick (`_pick_audiobook`: the store's pick, its toast's Undo)."""
    looks = AnsweringLooks({"joined": [], "alone": [52], "asks": []})
    win, _writer = window(looks)
    picked = []
    monkeypatch.setattr(win.needs_you, "_pick_audiobook", lambda entry, audio, epub, title: picked.append(
        (entry, audio, epub, title)))
    assert win.adder.read_folder(_folder(), book={"epub": EPUB, "title": TITLE})
    assert wait_until(lambda: picked, 5)
    assert picked == [(None, 52, EPUB, TITLE)]


def test_one_with_a_copy_of_this_title_is_taken_from_it_with_its_undo(window, monkeypatch):
    """Kura-AB4, based on the diagnosis in #419 by Mattias: the folder's audiobook was paired by a look with a copy of
    this very book (the EPUB beside it); picked again for the book that asked, it is taken from the copy — the pick
    with `replace`, its Undo pairing it back."""
    looks = AnsweringLooks({"joined": [], "alone": [], "asks": [], "elsewhere": [{"item_id": 53, "book": TITLE}]})
    win, _writer = window(looks)
    picked = []
    monkeypatch.setattr(win.needs_you, "_pick_audiobook", lambda entry, audio, epub, title, replace=False:
                        picked.append((entry, audio, epub, title, replace)))
    assert win.adder.read_folder(_folder(), book={"epub": EPUB, "title": TITLE})
    assert wait_until(lambda: picked, 5)
    assert picked == [(None, 53, EPUB, TITLE, True)]


def test_the_pick_menus_line_says_which_book_it_is_with_now():
    from app.qt import needs as qneeds
    assert qneeds.audiobook_line({"title": "カラフル", "n": 1}) == strings.NEEDS_AUDIOBOOK_LINE.format(title="カラフル", n=1)
    assert qneeds.audiobook_line({"title": "カラフル", "n": 1, "elsewhere": "カラフル"}) ==         strings.NEEDS_AUDIOBOOK_LINE.format(title="カラフル", n=1) + strings.NEEDS_AUDIOBOOK_ELSEWHERE.format(book="カラフル")
    assert qneeds.taken({"elsewhere": "カラフル"}) == {"replace": True} and qneeds.taken({}) == {}   # (its pick takes it)


@pytest.mark.parametrize("said, line", [
    ({"joined": [], "alone": [], "asks": []}, strings.NEEDS_AUDIOBOOK_NONE_IN.format(name="audiobook", book=TITLE)),
    ({"joined": [], "alone": [3, 4], "asks": []},
     strings.NEEDS_AUDIOBOOK_SEVERAL_IN.format(n=2, name="audiobook", book=TITLE)),
], ids=["none", "several"])
def test_none_or_several_in_the_folder_is_said_and_nothing_is_paired(window, monkeypatch, said, line):
    looks = AnsweringLooks(said)
    win, writer = window(looks)
    picked = []
    monkeypatch.setattr(win.needs_you, "_pick_audiobook", lambda *a: picked.append(a))
    assert win.adder.read_folder(_folder(), book={"epub": EPUB, "title": TITLE})
    assert wait_until(lambda: win.bar_line.full() == line, 5), win.bar_line.full()
    assert picked == [] and not [c for c in writer.calls if c[0].startswith("audiobook")]


def _button(win, label):
    return next((b for b in win.toasts.card.findChildren(QPushButton) if b.text() == label and b.isVisible()), None)


def test_add_a_folder_whose_audiobook_is_asked_about_leads_into_the_pairing(window):
    """+ Add's own *A folder…* (no book named): its audiobook's names are like a book's (H-8's question open) — the
    toast *「…」's audiobook?* with *Pair it*; its press is the question's *Yes* through the writer."""
    looks = AnsweringLooks({"joined": [], "alone": [], "asks": [{"item_id": 61, "key": "k-61", "book": TITLE,
                                                                  "epub": EPUB}]})
    win, writer = window(looks)
    assert win.adder.read_folder(_folder())
    assert wait_until(lambda: win.toasts.alive and win.toasts.text == strings.ADD_AUDIOBOOK_PAIR.format(book=TITLE),
                      5), win.toasts.text
    assert looks.added == [(os.path.normpath(_folder()), None)]
    assert not [c for c in writer.calls if c[0] == "audiobook_answer"]       # nothing paired until the press
    button = _button(win, strings.ADD_AUDIOBOOK_PAIR_IT[0])
    assert button is not None
    button.click()
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "audiobook_answer"], 5)
    assert [c for c in writer.calls if c[0] == "audiobook_answer"] == [("audiobook_answer", [61],
                                                                        {"yes": True, "key": "k-61"})]


def test_add_a_folder_with_nothing_asked_offers_nothing(window):
    looks = AnsweringLooks({"joined": [], "alone": [8], "asks": []})
    win, writer = window(looks)
    assert win.adder.read_folder(_folder())
    assert wait_until(lambda: looks.added, 5)
    wait_until(lambda: False, 0.3)
    assert _button(win, strings.ADD_AUDIOBOOK_PAIR_IT[0]) is None
    assert not [c for c in writer.calls if c[0].startswith("audiobook")]
