"""Known from Anki: another Anki profile or deck is a first read, never a marking read (P2.4 Part B final review, J1).

What the rule protects: a Connect user with two Anki profiles, or with the signal's decks changed, reads a different
set of cards. After a first read (an offer) and a second read that would mark, a read whose scope changed must mark
nothing: the cards it finds are a new question, offered again. A wrong answer here would write a word into
KnownWord.json as known just because the user switched profile or deck, which the user never accepted.

Anki is faked at the app.anki_connect functions the reader calls; KnownWord.json and the record live in the per-test
temp root (conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
"""
import contextlib
import json
import os

import pytest

from app import anki_connect
from app.connect import known_signal
from app.path_utils import get_user_files_path

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class FakeAnki:
    """Cards and notes held in memory. The search is ignored: the cards listed in `found` are what Anki answers.
    `profile` is what getActiveProfile answers, so a test can switch the Anki profile between two reads."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.found = []
        self.profile = "User 1"
        monkeypatch.setattr(anki_connect, "find_cards", lambda url, query: list(self.found))
        monkeypatch.setattr(anki_connect, "cards_info",
                            lambda url, ids: [{"cardId": c, "note": self.cards[c]} for c in ids])
        monkeypatch.setattr(anki_connect, "notes_info",
                            lambda url, ids: [{"noteId": n, "modelName": "Lapis",
                                               "fields": {"Expression": {"value": self.words[n], "order": 0}}}
                                              for n in ids])
        monkeypatch.setattr(anki_connect, "invoke",
                            lambda action, url, **kwargs: self.profile if action == "getActiveProfile" else None)
        monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())

    def add(self, card, note, word):
        self.cards[card] = note
        self.words[note] = word


@pytest.fixture
def anki(monkeypatch):
    return FakeAnki(monkeypatch)


@pytest.fixture
def known_file():
    """A KnownWord.json with one unrelated known word, written in the user's folder for the test."""
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    data = {"words": [{"dictForm": "溜め息", "knownStatus": "KNOWN", "hasCard": 1, "knownBy": "user"}]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _first_read_then_second(anki, known_file, second_profile, second_decks):
    """A first read offers card 101 (上層部) in DevTest under User 1; then a second read under `second_profile` and
    `second_decks` finds card 102 (一生懸命) as a new card. The same signal and terms, so only the scope may differ."""
    anki.add(101, 1, "上層部")
    anki.found = [101]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)      # the first read: records the offer

    anki.add(102, 2, "一生懸命")
    anki.found = [101, 102]
    anki.profile = second_profile
    before = _bytes(known_file)
    return known_signal.read("ja", URL, second_decks, ["Expression"], SETTINGS), before


def _assert_offer_not_mark(out, before, known_file):
    assert out["marked"] == []                                              # nothing marked
    assert out["offered"] == 1                                              # the new card is offered, not marked
    assert _bytes(known_file) == before                                     # KnownWord.json keeps its exact bytes
    offer = known_signal.load("ja").get("offer") or {}
    assert offer.get("state") == "pending"                                  # a pending offer, shown to the user
    assert [c["word"] for c in offer.get("cards", [])][-1:] == ["一生懸命"]


def test_another_anki_profile_after_a_first_read_offers_and_marks_nothing(anki, known_file):
    """Switching Anki profile between two reads is a first read: the card found under the new profile is offered,
    never marked. Why: the profile the user reads is part of what they agreed to; a new profile is a new question."""
    out, before = _first_read_then_second(anki, known_file, "User 2", ["DevTest"])
    _assert_offer_not_mark(out, before, known_file)


def test_changed_decks_after_a_first_read_offers_and_marks_nothing(anki, known_file):
    """Reading other decks after a first read is a first read: the new deck's card is offered, never marked.
    Why: the decks are the scope the user accepted; a different deck is a different set of cards to ask about."""
    out, before = _first_read_then_second(anki, known_file, "User 1", ["Other deck"])
    _assert_offer_not_mark(out, before, known_file)
