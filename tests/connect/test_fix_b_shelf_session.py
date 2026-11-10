"""The swap-in brings back only the shelved word a top-20 file holds (P2.4-J item J17; `Steps.shelf_session`).

A shelved card's word that a top-20 file holds (勇気, held by ep1.srt in the line) comes back: un-suspended and its
shelf tag taken off. A shelved word no file holds (溜め息) stays on the shelf, suspended and tagged.

What a wrong answer would cost: a word the top 20 needs stays shelved, so the learner's next words stall; or a word
nobody needs is put back, so the list fills with cards the cap meant to hold off.

Against a Steps instance whose Anki, store and list readers are fakes (no live Anki, no network, no sleeps); the
ledger is a real SQLite file in a temp folder.
"""
import contextlib

import pytest

from app.cli import connect_verbs
from app.connect import library, runner, shelf
from app.connect.ledger import Ledger

# two shelved cards, one note each: 勇気's note came from item 1 (ep1.srt, on the top 20); 溜め息's from item 2
# (a show the top 20 doesn't hold)
NOTE_YUUKI, NOTE_TAMEIKI = 201, 202
CARD_YUUKI, CARD_TAMEIKI = 101, 102


class FakeAnki:
    """The Anki methods the swap-in calls, and only those. Both cards start suspended and tagged as shelved."""

    def __init__(self):
        self.note_of = {CARD_YUUKI: NOTE_YUUKI, CARD_TAMEIKI: NOTE_TAMEIKI}
        self.suspended = {CARD_YUUKI, CARD_TAMEIKI}
        self.tags = {NOTE_YUUKI: {shelf.SHELF_TAG}, NOTE_TAMEIKI: {shelf.SHELF_TAG}}
        self.unsuspend_calls = []

    def find_cards(self, query):
        ids = sorted(c for c, n in self.note_of.items()
                     if shelf.SHELF_TAG in self.tags[n] or "surasura::shelf" not in query)
        if "-is:suspended" in query:
            return [c for c in ids if c not in self.suspended]
        if "is:suspended" in query:
            return [c for c in ids if c in self.suspended]
        return ids

    def cards_info(self, ids):
        return [{"cardId": c, "note": self.note_of[c]} for c in ids]

    def reviewing(self):
        return False

    def writer(self, verb):
        return contextlib.nullcontext()

    def unsuspend(self, ids):
        self.unsuspend_calls.append(sorted(ids))
        self.suspended.difference_update(ids)

    def remove_tag(self, note_ids, tag):
        for n in note_ids:
            self.tags[n].discard(tag)


class FakeStore:
    """The one store read the swap-in makes outside the readers patched below: an item's row."""

    def item(self, item_id):
        return {"rel_path": "show/ep1.srt"} if item_id == 1 else {"rel_path": "show/ep2.srt"}


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


@pytest.fixture
def swap_in(monkeypatch, ledger):
    """A Steps whose Anki and store are fakes, and whose made-note and list readers are patched to the case above.
    Returns (steps, anki, ledger)."""
    made = {NOTE_YUUKI: (1, "勇気"), NOTE_TAMEIKI: (2, "溜め息")}
    monkeypatch.setattr(shelf, "made_notes", lambda store: made)
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    # the top 20's line is item 1 alone; its file holds 勇気 and no other shelved word
    monkeypatch.setattr(library, "mine_line", lambda store: [1])
    monkeypatch.setattr(connect_verbs, "_read_list", lambda lang: (None, None, {"ep1.srt": ["勇気"]}))

    anki = FakeAnki()
    steps = runner.Steps({"connect_enabled": True})
    steps._anki = lambda: anki

    @contextlib.contextmanager
    def _open(lang):
        yield FakeStore()

    steps._open = _open
    return steps, anki, ledger


def test_swap_in_brings_back_the_word_a_top_20_file_holds_and_leaves_the_rest_shelved(swap_in):
    # why: the top 20 needs 勇気 again, so its card comes back; 溜め息 is held by no file, so it stays on the shelf
    steps, anki, ledger = swap_in

    steps.shelf_session("ja", ledger)

    assert anki.unsuspend_calls == [[CARD_YUUKI]], "only the card of the word a top-20 file holds is un-suspended"
    assert CARD_TAMEIKI in anki.suspended, "a shelved word no top-20 file holds stays suspended"
    assert shelf.SHELF_TAG not in anki.tags[NOTE_YUUKI], "the returned card's note loses its shelf tag"
    assert shelf.SHELF_TAG in anki.tags[NOTE_TAMEIKI], "the note that stays on the shelf keeps its tag"
    assert any("1 shelved cards came back" in line for line in steps.said["ja"]), "the run says one card came back"
