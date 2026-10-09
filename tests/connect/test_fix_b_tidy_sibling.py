"""Review B fix (H7): `shelf.tidy` takes the shelf tag off a note only when none of its cards is still on the shelf.

The tag belongs to the note, not the card. A note can hold two of Connect's cards: if you un-suspend one of them in
Anki while its sibling stays suspended on the shelf, the note must keep `surasura::shelf` (the sibling is still
shelved). A note whose only shelved card you un-suspended loses the tag, as before.

What a wrong answer would cost: with the tag removed early, the next `tidy` or a Generate reads the sibling as a
card the learner released, and the shelf's own book of what is still held drifts from Anki.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The fake answers
`find_cards` by query (`-is:suspended` vs `is:suspended`) and records tags per note, so the assertions read what
`tidy` asked Anki to do. The ledger is a real SQLite file in a temp folder; no network, no sleeps.
"""
import contextlib

import pytest

from app.connect import shelf
from app.connect.ledger import Ledger


class FakeAnki:
    """The Anki methods the shelf calls, and only those. `note_of`: {card id: note id}."""

    def __init__(self, note_of):
        self.note_of = dict(note_of)
        self.suspended = set()
        self.tags = {n: set() for n in self.note_of.values()}

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

    def suspend(self, ids):
        self.suspended.update(ids)

    def unsuspend(self, ids):
        self.suspended.difference_update(ids)

    def add_tag(self, note_ids, tag):
        for n in note_ids:
            self.tags[n].add(tag)

    def remove_tag(self, note_ids, tag):
        for n in note_ids:
            self.tags[n].discard(tag)


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def test_tidy_keeps_the_tag_of_a_note_whose_sibling_card_is_still_shelved(ledger):
    # Why: cards 11 and 12 are two cards of note 1 (上層部, shelved together); 13 is note 2's own card (一生懸命).
    # You release 11 and 13 in Anki and keep 12 shelved. Note 1 still holds a shelved card, so its tag stays;
    # note 2 has no shelved card left, so its tag goes.
    anki = FakeAnki({11: 1, 12: 1, 13: 2})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 1, "気配", 7), shelf.Card(13, 2, "一生懸命", 7)]
    shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")
    anki.suspended.discard(11)
    anki.suspended.discard(13)

    tidied = shelf.tidy(anki, ledger)

    assert tidied == 1
    assert anki.tags[1] == {shelf.SHELF_TAG}
    assert anki.tags[2] == set()
    assert anki.suspended == {12}
