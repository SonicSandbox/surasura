"""The swap-in (P2.4 Part B, item S1): `shelf.bring_back` takes shelved cards back out of Anki. Every card given is
un-suspended and has the shelf tag taken off; only a card from a finished item gets a `rewrites` row, aimed at the
journey item that holds its word now; a learner who started reviewing gets `Reviewing` and nothing is written.

What a wrong answer would cost: a rewrite row for a card whose line still comes from the journey (its note rewritten
for a show nobody finished); a card left suspended after the learner asked for it back; a swap-in that writes into
Anki while the learner is reviewing.

Fake Anki only: no network, no sleeps, the ledger is a temp SQLite file that the fixture closes.
"""
import contextlib

import pytest

from app.connect import shelf
from app.connect.ledger import Ledger

# Real Japanese words for the cards' spellings (the swap-in never reads them as meaning, but they are real data).
WORD_A, WORD_B = "上層部", "一生懸命"


class FakeAnki:
    """Records every write the swap-in makes; `reviewing` says whether the learner has started a review."""

    def __init__(self, reviewing=False):
        self._reviewing = reviewing
        self.unsuspended = []
        self.tag_removals = []

    def writer(self, verb):
        return contextlib.nullcontext()

    def reviewing(self):
        return self._reviewing

    def unsuspend(self, ids):
        self.unsuspended.extend(ids)

    def remove_tag(self, note_ids, tag):
        self.tag_removals.append((list(note_ids), tag))

    def find_cards(self, query):
        """No other card of these notes is left on the shelf (the sibling rule's read; its own test is elsewhere)."""
        return []

    def cards_info(self, ids):
        return []


@pytest.fixture
def ledger(tmp_path):
    # Why: a temp file per test keeps rewrites rows from one test leaking into another; closed even if a test fails.
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    # Why: the tables are made on the first write, which a reviewing refusal never reaches; make them up front so
    # "no rewrite row" is checked against an empty table, not a missing one.
    shelf.ensure(led)
    yield led
    led.close()


def _rewrites(ledger):
    return ledger.conn.execute("SELECT note_id, to_item FROM rewrites ORDER BY note_id").fetchall()


def test_every_card_given_is_unsuspended_and_loses_the_shelf_tag(ledger):
    # Why: the learner asked for these cards back, whatever item they came from: all of them come out of suspension
    # and the shelf tag goes from every note, so a card from an unfinished show is not left shelved in Anki.
    anki = FakeAnki()
    back = [shelf.Card(card_id=11, note_id=21, word=WORD_A, item_id=5),
            shelf.Card(card_id=12, note_id=22, word=WORD_B, item_id=7)]

    result = shelf.bring_back(anki, ledger, "ja", back, finished_items={5}, journey_item_of=lambda w: 9)

    assert sorted(anki.unsuspended) == [11, 12]
    assert anki.tag_removals == [([21, 22], shelf.SHELF_TAG)]
    assert result["back"] == 2


def test_only_a_card_from_a_finished_item_gets_a_rewrite_row_to_the_journey_item(ledger):
    # Why: item 5 is finished, so its note is marked for the rewrite to item 9; item 7's card still reads from the
    # journey, so it must get no row. A mutant that marks every card (`if True:`) writes a row for note 22 and fails.
    anki = FakeAnki()
    back = [shelf.Card(card_id=11, note_id=21, word=WORD_A, item_id=5),
            shelf.Card(card_id=12, note_id=22, word=WORD_B, item_id=7)]

    result = shelf.bring_back(anki, ledger, "ja", back, finished_items={5}, journey_item_of=lambda w: 9)

    assert _rewrites(ledger) == [(21, 9)]
    assert result["rewrite"] == [21]


def test_reviewing_raises_and_writes_nothing(ledger):
    # Why: a swap-in during a review must not touch Anki or the ledger; the learner is told to stop and try again.
    anki = FakeAnki(reviewing=True)
    back = [shelf.Card(card_id=11, note_id=21, word=WORD_A, item_id=5)]

    with pytest.raises(shelf.Reviewing):
        shelf.bring_back(anki, ledger, "ja", back, finished_items={5}, journey_item_of=lambda w: 9)

    assert anki.unsuspended == []
    assert anki.tag_removals == []
    assert _rewrites(ledger) == []
