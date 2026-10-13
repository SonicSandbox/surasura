"""The swap-in records the note's mod before it writes (shelf.bring_back, app/connect/shelf.py).

Rule: when a shelved card is brought back, the shelf reads its NOTE's mod (Anki's note modification time) under the
writer, before the un-suspend and the untag, and stores it in `mod_back` with `back_by = 'surasura'`. The undo uses
that mod to tell whether the learner edited the note after Connect's swap-in; a wrong or missing mod would let
*Undo this batch* delete a note the learner had edited.

What a wrong answer would cost: a mod recorded after the write, or none at all, makes the note look untouched.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The mods are read from
the fake's own table, so the test sees the value the shelf actually recorded.
"""
import contextlib

import pytest

from app.connect import shelf
from app.connect.ledger import Ledger

# The mod Anki gives a note once a write touches it (the un-suspend, the untag). Distinct from every seeded mod.
WRITTEN_MOD = 1760000999


class FakeAnki:
    """The Anki methods the shelf calls, and only those, plus `note_mods`. `note_of`: {card id: note id}."""

    def __init__(self, note_of, mods):
        self.note_of = dict(note_of)
        self.mods = dict(mods)
        self.suspended = set()
        self.tags = {n: set() for n in self.note_of.values()}
        self.busy = False

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
        return self.busy

    def writer(self, verb):
        return contextlib.nullcontext()

    def note_mods(self, note_ids):
        return {n: self.mods[n] for n in note_ids if n in self.mods}

    def suspend(self, ids):
        self.suspended.update(ids)

    # Anki bumps a note's mod when a write touches it: the un-suspend and the untag below move the mod on, so a
    # swap-in that read the mod after these writes would record the bumped value, not the learner's.
    def unsuspend(self, ids):
        self.suspended.difference_update(ids)
        for c in ids:
            if self.note_of[c] in self.mods:
                self.mods[self.note_of[c]] = WRITTEN_MOD

    def add_tag(self, note_ids, tag):
        for n in note_ids:
            self.tags[n].add(tag)

    def remove_tag(self, note_ids, tag):
        for n in note_ids:
            self.tags[n].discard(tag)
            if n in self.mods:
                self.mods[n] = WRITTEN_MOD


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def test_bring_back_records_the_notes_mod_and_surasura_as_the_one_who_brought_it_back(ledger):
    # Why: the undo reads mod_back to see whether the learner edited the note after the swap-in; the mod must be the
    # note's (not the card's) and must be the value Anki holds just before Connect's un-suspend.
    anki = FakeAnki({11: 1, 12: 2}, {1: 1760000001, 2: 1760000002})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "溜め息", 7)]
    shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")

    # The learners' notes change in Anki after the shelving; the swap-in must read each note's own newer mod.
    # Why both cards in one call: a swap-in that records only the first card's mod, or swaps mods between notes,
    # must fail here.
    anki.mods[1] = 1760000101
    anki.mods[2] = 1760000202

    shelf.bring_back(anki, ledger, "ja", [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "溜め息", 7)])

    rows = ledger.conn.execute("SELECT card_id, mod_back, back_by FROM shelf ORDER BY card_id").fetchall()
    assert rows == [(11, 1760000101, "surasura"), (12, 1760000202, "surasura")]
