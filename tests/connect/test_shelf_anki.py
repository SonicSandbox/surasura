"""Connect's shelf through Anki, and its restore point (P2.4 card B3; the shelf's Anki writes in `app/connect/shelf.py`).

What each test holds still:

  * `shelve` suspends the chosen cards, tags their notes `surasura::shelf`, and records the run in the ledger under
    the id it returns. A wrong answer would leave cards suspended that no restore point knows about, so they could
    never be brought back;
  * while you are reviewing, `shelve` raises `Reviewing` and writes nothing: no suspend, no tag, no ledger row. A
    wrong answer would change your queue under your own hands;
  * `restore` un-suspends and untags only the run's cards that are still suspended by the shelf. A card you already
    released in Anki is left alone: restoring it again would un-suspend a card you chose to keep, and call it back
    from a run it no longer belongs to. The count it returns is the number of cards it actually put back;
  * a second `restore` of the same run finds nothing to do and returns 0;
  * `cards` ignores a card whose note Connect did not make (the learner's own): the shelf never touches it.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The fake keeps its own
suspended set and tag map, so the assertions read what the shelf asked Anki to do, not what the shelf says it did.
The ledger is a real SQLite file in a temp folder; no network, no sleeps.
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


def test_shelve_suspends_tags_and_records_the_run_in_the_ledger(ledger):
    # Why: the restore point is the only way back; a card suspended without a ledger row is lost to the shelf.
    anki = FakeAnki({11: 1, 12: 2})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "溜め息", 7)]

    run = shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")

    assert run == "run-a"
    assert anki.suspended == {11, 12}
    assert anki.tags[1] == {shelf.SHELF_TAG} and anki.tags[2] == {shelf.SHELF_TAG}
    assert shelf.runs(ledger, "ja")[0]["cards"] == 2


def test_shelve_while_reviewing_raises_and_writes_nothing(ledger):
    # Why: Connect never changes the queue while you review (the reviewing check comes before every write).
    anki = FakeAnki({11: 1})
    anki.busy = True

    with pytest.raises(shelf.Reviewing):
        shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "勇気", 7)], "a quarter of the cap", run="run-a")

    assert anki.suspended == set()
    assert anki.tags[1] == set()
    assert shelf.runs(ledger) == []


def test_restore_leaves_a_card_the_learner_already_released_alone(ledger):
    # Why: card 12 was un-suspended by you in Anki; restore must not un-suspend it again or count it as put back.
    anki = _three_shelved(ledger)
    anki.suspended.discard(12)

    back = shelf.restore(anki, ledger, "run-a")

    assert back == 2
    assert anki.unsuspend_calls == [[11, 13]]
    assert 12 not in anki.suspended
    assert anki.tags[2] == {shelf.SHELF_TAG}


def test_restore_puts_back_every_card_the_run_still_holds_then_is_done(ledger):
    # Why: a restore of a run whose cards are all still suspended returns them all; a second restore is a no-op.
    anki = _three_shelved(ledger)

    assert shelf.restore(anki, ledger, "run-a") == 3
    assert anki.suspended == set()
    assert all(shelf.SHELF_TAG not in tags for tags in anki.tags.values())
    assert shelf.runs(ledger, "ja")[0]["back"] == 3

    assert shelf.restore(anki, ledger, "run-a") == 0


def test_cards_ignores_a_note_connect_did_not_make(ledger):
    # Why: the learner's own card, suspended by hand, must never reach the shelf's choice.
    anki = FakeAnki({11: 1, 12: 9})
    anki.suspended.update({11, 12})
    made = {1: (7, "上層部")}

    found = shelf.cards(anki, "is:suspended", made)

    assert [(c.card_id, c.word) for c in found] == [(11, "上層部")]
