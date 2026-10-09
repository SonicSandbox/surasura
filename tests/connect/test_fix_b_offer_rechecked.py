"""Known from Anki: an accepted offer marks only the cards still signalled (P2.4 Part B review fix, H13).

What the rule protects: the one-time offer lists the words of every card signalled at the first read. If the user
un-suspends one of those cards before answering, accepting the offer must not mark that card's word known anyway: the
user took the signal back, and KnownWord.json would then hold a word the user never meant to learn as known. A wrong
answer here would silently widen the user's known list.

Anki is faked at the app.anki_connect functions the reader calls; KnownWord.json and the record live in the per-test
temp root (conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
"""
import json
import os

import pytest

from app import anki_connect
from app.connect import known_signal
from app.path_utils import get_user_files_path

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True}  # known_from_anki defaults to ["suspended"]

# Real Japanese words, one note each; both cards are suspended when the first read records the offer.
UPPER = (201, 11, "上層部")
ISSHO = (202, 12, "一生懸命")


class FakeAnki:
    """The signal's cards: a card is signalled while it sits in `suspended`."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.suspended = set()
        monkeypatch.setattr(anki_connect, "find_cards", self._find_cards)
        monkeypatch.setattr(anki_connect, "invoke",                     # the scope's Anki profile: never a real Anki
                            lambda action, url, **kw: "User 1" if action == "getActiveProfile" else None)
        monkeypatch.setattr(anki_connect, "cards_info", self._cards_info)
        monkeypatch.setattr(anki_connect, "notes_info", self._notes_info)

    def add(self, card, note, word):
        self.cards[card] = note
        self.words[note] = word
        self.suspended.add(card)

    def _find_cards(self, url, query):
        return sorted(self.suspended)

    def _cards_info(self, url, ids):
        return [{"cardId": c, "note": self.cards[c]} for c in ids]

    def _notes_info(self, url, ids):
        return [{"noteId": n, "modelName": "Lapis",
                 "fields": {"Expression": {"value": self.words[n], "order": 0}}} for n in ids]


@pytest.fixture
def anki(monkeypatch):
    fake = FakeAnki(monkeypatch)
    fake.add(*UPPER)
    fake.add(*ISSHO)
    return fake


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


def _words(path):
    with open(path, encoding="utf-8") as f:
        return {w["dictForm"]: w for w in json.load(f)["words"]}


def test_accepting_the_offer_skips_a_card_unsuspended_before_the_answer(anki, known_file):
    """The first read offers both signalled words. The user then un-suspends 上層部's card, so accepting the offer
    marks only 一生懸命. The word whose card is no longer signalled must not reach KnownWord.json, and the offer
    still closes as accepted."""
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    anki.suspended.discard(UPPER[0])  # the user un-suspends 上層部 before answering the offer

    added = known_signal.accept_offer("ja", URL)

    assert added == ["一生懸命"]
    entries = _words(known_file)
    assert "一生懸命" in entries and entries["一生懸命"]["knownBy"] == "anki-signal"
    assert "上層部" not in entries
    assert known_signal.load("ja")["offer"]["state"] == "accepted"
