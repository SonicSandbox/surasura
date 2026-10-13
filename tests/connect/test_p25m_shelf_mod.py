"""Shelving records each card's NOTE's mod, read just before the shelf's write (`shelf.shelve` -> `shelf._mods`).

The mod is what lets a later *Undo this batch* tell whether the learner has edited a note since Connect shelved it:
a note edited since must be kept. A wrong answer here would store the mod of the wrong thing (a card id instead of
its note id), so the stored mod would never match Anki's and an edit would be read as no edit.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The mods come from the
fake's `note_mods`, keyed by note id, and the card ids are chosen so they never collide with a note id.
"""
import contextlib

import pytest

from app.connect import shelf
from app.connect.ledger import Ledger


class FakeAnki:
    """The Anki methods the shelf calls, and only those. `note_of`: {card id: note id}; `mods`: {note id: mod}."""

    def __init__(self, note_of, mods):
        self.note_of = dict(note_of)
        self.mods = dict(mods)
        self.suspended = set()
        self.tags = {n: set() for n in self.note_of.values()}
        self.busy = False
        self.in_writer = False
        self.read_in_writer = []

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

    def note_mods(self, ids):
        # Why: the shelf must read the mods under its writer, so a mod read outside the write could be stale by the
        # time the write lands. Record whether the read happened inside the writer.
        self.read_in_writer.append(self.in_writer)
        return {n: self.mods[n] for n in ids if n in self.mods}

    def reviewing(self):
        return self.busy

    @contextlib.contextmanager
    def writer(self, verb):
        self.in_writer = True
        try:
            yield
        finally:
            self.in_writer = False

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


def test_shelve_records_each_cards_note_mod_looked_up_by_note_id(ledger):
    # Why: the mod belongs to the note, and the shelf looks it up by note id. Cards 11 and 12 are not keys of the
    # mod table, so a lookup by card id would store nothing and an edit to the note would go unseen.
    anki = FakeAnki({11: 1, 12: 2}, {1: 1760000001, 2: 1760000002})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "溜め息", 7)]

    shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")

    rows = ledger.conn.execute("SELECT card_id, mod_shelved FROM shelf ORDER BY card_id").fetchall()
    assert {card_id: mod for card_id, mod in rows} == {11: 1760000001, 12: 1760000002}
    # Why: the rule is "under its writer" - the mods are read once, inside the shelf's write, not outside it.
    assert anki.read_in_writer == [True]
