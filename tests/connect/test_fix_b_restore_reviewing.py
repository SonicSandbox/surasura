"""Restore point while you are reviewing (P2.4-H item H6; `restore` in `app/connect/shelf.py`).

What it holds still: `shelf.restore` raises `Reviewing` when Anki says you are reviewing, and un-suspends nothing.
The shelf's rows stay open in the ledger, so a later restore (once you stop reviewing) still finds every card.

What a wrong answer would cost: a restore that writes during a review would pull cards back into your queue under
your own hands, mid-session, and the ledger would then record them as returned.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The fake keeps its own
suspended set and tag map, so the assertions read what the shelf asked Anki to do. The ledger is a real SQLite file
in a temp folder; no network, no sleeps.
"""
import contextlib

import pytest

from app.connect import shelf
from app.connect.ledger import Ledger


class FakeAnki:
    """The Anki methods the shelf calls, and only those. `note_of`: {card id: note id}; `busy`: you are reviewing."""

    def __init__(self, note_of):
        self.note_of = dict(note_of)
        self.suspended = set()
        self.tags = {n: set() for n in self.note_of.values()}
        self.busy = False
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
        return self.busy

    def writer(self, verb):
        return contextlib.nullcontext()

    def suspend(self, ids):
        self.suspended.update(ids)

    def unsuspend(self, ids):
        self.unsuspend_calls.append(sorted(ids))
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


def _three_shelved(ledger):
    """Three of Connect's cards (real words), shelved under one run: cards 11-13 in notes 1-3."""
    anki = FakeAnki({11: 1, 12: 2, 13: 3})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "一生懸命", 7), shelf.Card(13, 3, "気配", 7)]
    shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")
    return anki


def test_restore_while_reviewing_raises_and_unsuspends_nothing(ledger):
    # Why: a restore during your review would change your queue under you; it must refuse before any unsuspend.
    anki = _three_shelved(ledger)
    anki.busy = True

    with pytest.raises(shelf.Reviewing):
        shelf.restore(anki, ledger, "run-a")

    assert anki.unsuspend_calls == []
    assert anki.suspended == {11, 12, 13}
    assert all(shelf.SHELF_TAG in anki.tags[n] for n in (1, 2, 3))


def test_restore_refused_while_reviewing_leaves_the_run_open_for_later(ledger):
    # Why: a refused restore must not mark the run done; once you stop reviewing, the same run still puts every card back.
    anki = _three_shelved(ledger)
    anki.busy = True
    with pytest.raises(shelf.Reviewing):
        shelf.restore(anki, ledger, "run-a")

    rows = ledger.conn.execute("SELECT back_at FROM shelf WHERE run = ?", ("run-a",)).fetchall()
    assert rows and all(back_at is None for (back_at,) in rows)

    anki.busy = False
    assert shelf.restore(anki, ledger, "run-a") == 3
    assert anki.suspended == set()
