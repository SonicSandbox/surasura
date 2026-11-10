"""Who took a card off the shelf (P2.5-2; `app/connect/shelf.py` 75–78, 253–335, and the shelf block of
`app/connect/status.py` 210–230).

What each test holds still:

  * a card you put back (`shelf.restore`) and a shelved card you un-suspended in Anki (`shelf.tidy`) are in
    `shelf.kept(ledger)`: Connect never shelves them again. A wrong answer would shelve a card you chose to keep;
  * a card the swap-in brought back (`shelf.bring_back`) is NOT in `kept`: its word is relevant again, so it may be
    shelved again. A wrong answer would lock a card out of the shelf for good;
  * the status record's shelf block lists each restore point with its cards and how many came back, counts the cards
    still shelved (`on_shelf`), and counts the swap-ins of today (`swap_ins`). A wrong answer would show the learner
    a shelf that does not match what is in Anki.

Why the fake Anki: the real writer is AnkiConnect over loopback, and no test may reach Anki. The ledger is a real
SQLite file in a temp folder; the status record is read from that same file. No network, no sleeps.
"""
import contextlib

import pytest

from app.connect import shelf, status
from app.connect.ledger import Ledger


class FakeAnki:
    """The Anki methods the shelf calls, and only those. `note_of`: {card id: note id}."""

    def __init__(self, note_of):
        self.note_of = dict(note_of)
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
def ledger_path(tmp_path):
    return str(tmp_path / "ledger.sqlite")


def _two_shelved(path):
    """Two of Connect's cards (real words), shelved under one run: cards 11-12 in notes 1-2."""
    anki = FakeAnki({11: 1, 12: 2})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "溜め息", 7)]
    with Ledger(path) as ledger:
        shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a")
    return anki


def test_a_card_you_put_back_is_kept_and_the_record_lists_the_restore_point(tmp_path, ledger_path):
    # Why: a card you put back is yours; Connect must never shelve it again, and the record must show the run.
    anki = _two_shelved(ledger_path)
    with Ledger(ledger_path) as ledger:
        assert shelf.restore(anki, ledger, "run-a") == 2
        assert shelf.kept(ledger) == {11, 12}

    block = status.read(["ja"], path=ledger_path)["languages"]["ja"]["shelf"]
    assert [(r["run"], r["cards"], r["back"]) for r in block["runs"]] == [("run-a", 2, 2)]
    assert block["on_shelf"] == 0
    assert block["swap_ins"] == 0


def test_a_shelved_card_you_un_suspended_in_anki_is_kept_after_tidy(tmp_path, ledger_path):
    # Why: un-suspending in Anki is also you taking the card back; tidy must record it as yours, not as Surasura's.
    anki = _two_shelved(ledger_path)
    anki.suspended.discard(11)                  # the learner releases 上層部 in Anki herself
    with Ledger(ledger_path) as ledger:
        assert shelf.tidy(anki, ledger) == 1
        assert shelf.kept(ledger) == {11}       # 溜め息 is still on the shelf, so it is not yours yet


def test_a_card_the_swap_in_brought_back_is_not_kept_and_the_record_counts_it(tmp_path, ledger_path):
    # Why: the swap-in's card may be shelved again later; the record counts it as today's swap-in, not as yours.
    anki = _two_shelved(ledger_path)
    with Ledger(ledger_path) as ledger:
        back = shelf.bring_back(anki, ledger, "ja", [shelf.Card(12, 2, "溜め息", 7)])
        assert back == {"back": 1, "rewrite": []}
        assert shelf.kept(ledger) == set()

    block = status.read(["ja"], path=ledger_path)["languages"]["ja"]["shelf"]
    assert [(r["run"], r["cards"], r["back"]) for r in block["runs"]] == [("run-a", 2, 1)]
    assert block["on_shelf"] == 1               # 上層部 is still suspended by the shelf
    assert block["swap_ins"] == 1               # one swap-in today
