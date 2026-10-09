"""Known from Anki: a new offer keeps the pending offer's cards (P2.4 Part B, adversary B #17).

What the rule protects: the first read offers card 201 (上層部). The user then widens the signal, and the next read finds
card 202 (一生懸命) as a new card. The offer on screen must hold BOTH cards, still pending, so the user can answer for
the first one as well. A wrong answer here would drop 201 from the offer silently: the user's pending question vanishes
and the word is never shown to them.

Anki is faked at the app.anki_connect functions the reader calls; KnownWord.json and the record live in the per-test
temp root (conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
"""
import contextlib

import pytest

from app import anki_connect
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
NARROW = {"connect_enabled": True, "known_from_anki": ["suspended"]}
WIDE = {"connect_enabled": True, "known_from_anki": ["suspended", "flag:1"]}


class FakeAnki:
    """Cards and notes held in memory; the signal's query is ignored, the cards listed are what Anki answers."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.found = []
        monkeypatch.setattr(anki_connect, "find_cards", lambda url, query: list(self.found))
        monkeypatch.setattr(anki_connect, "cards_info",
                            lambda url, ids: [{"cardId": c, "note": self.cards[c]} for c in ids])
        monkeypatch.setattr(anki_connect, "notes_info",
                            lambda url, ids: [{"noteId": n, "modelName": "Lapis",
                                               "fields": {"Expression": {"value": self.words[n], "order": 0}}}
                                              for n in ids])
        monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: None)
        monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())

    def add(self, card, note, word):
        self.cards[card] = note
        self.words[note] = word


@pytest.fixture
def anki(monkeypatch):
    return FakeAnki(monkeypatch)


def test_new_offer_keeps_the_pending_offers_cards(anki):
    """After a signal change, the pending offer holds the first read's card AND the new one, in that order.
    Why: a new card joins the question on screen; it never replaces the question the user has not answered yet."""
    anki.add(201, 1, "上層部")
    anki.found = [201]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], NARROW)      # the first read: offers 201

    anki.add(202, 2, "一生懸命")                                              # a card the wider signal now catches
    anki.found = [201, 202]
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], WIDE)

    assert out["marked"] == []                                              # an offer, never a mark
    offer = known_signal.load("ja").get("offer") or {}
    assert offer.get("state") == "pending"
    # 201 was pending from the first read and must survive the second; 202 joins it (adversary B #17)
    assert [c["card"] for c in offer.get("cards", [])] == [201, 202]
