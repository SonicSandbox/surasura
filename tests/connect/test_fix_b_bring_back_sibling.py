"""Final-adversary fix (J13): the swap-in (`shelf.bring_back`) takes the shelf tag off a note only when none of its cards
is still on the shelf, the same rule `tidy` keeps (`test_fix_b_tidy_sibling.py`).

A note can hold two of Connect's cards. Here note 1 holds 11 and 12 (上層部, shelved together) and note 2 holds 13
(一生懸命). The swap-in brings back 11 and 13. Note 1 keeps `surasura::shelf` because 12 is still shelved; note 2's
only card came back, so its tag goes.

What a wrong answer would cost: with the tag removed from note 1 too, the next `tidy` or Generate reads card 12 as one
the learner released, and the shelf's book of what is still held drifts from Anki.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The fake is the one
`test_fix_b_tidy_sibling.py` uses; it answers `find_cards` by query and records tags per note. The ledger is a real
SQLite file in a temp folder; no network, no sleeps.
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


def test_swap_in_keeps_the_tag_of_a_note_with_a_card_still_shelved_and_drops_the_tag_of_a_note_fully_back(ledger):
    # Why: 11 and 12 are note 1's two cards; 13 is note 2's only card. The swap-in brings back 11 and 13 and leaves
    # 12 shelved, so note 1 keeps its tag and note 2 loses it.
    anki = FakeAnki({11: 1, 12: 1, 13: 2})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 1, "気配", 7), shelf.Card(13, 2, "一生懸命", 7)]
    shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")
    back = [shelf.Card(11, 1, "上層部", 7), shelf.Card(13, 2, "一生懸命", 7)]

    result = shelf.bring_back(anki, ledger, "ja", back)

    assert result == {"back": 2, "rewrite": []}
    assert anki.tags[1] == {shelf.SHELF_TAG}
    assert anki.tags[2] == set()
    assert anki.suspended == {12}
