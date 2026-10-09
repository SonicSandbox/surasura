"""Known from Anki: a changed signal offers again, it never marks (P2.4 Part B, review fix H15).

What the rule protects: when the user widens the signal (Settings: ["suspended"] becomes ["suspended", "flag:1"]),
the cards the wider signal now catches are a new question, not a new answer. A wrong answer here would mark a
word known that the user never accepted, straight into KnownWord.json, just because a setting changed.

Anki is faked at the app.anki_connect functions the reader calls; KnownWord.json and the record live in the
per-test temp root (conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
"""
import contextlib
import json
import os

import pytest

from app import anki_connect
from app.connect import known_signal
from app.path_utils import get_user_files_path

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


def test_changed_signal_offers_again_and_marks_nothing(anki, known_file):
    """Widening the signal after a first read must not mark the newly caught card: it is recorded as a pending
    offer, and KnownWord.json keeps its exact bytes. Why: a setting change is not the user accepting a word."""
    anki.add(101, 1, "上層部")
    anki.found = [101]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], NARROW)      # the first read: records the offer

    anki.add(102, 2, "一生懸命")                                              # a card the wider signal now catches
    anki.found = [101, 102]
    before = _bytes(known_file)
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], WIDE)

    assert out["marked"] == []                                              # nothing marked
    assert out["offered"] == 1                                              # the new card is offered
    assert _bytes(known_file) == before                                     # KnownWord.json unchanged
    offer = known_signal.load("ja").get("offer") or {}
    assert offer.get("state") == "pending"
    # the new card joins the offer still pending from the first read; nothing is marked (adversary B #17)
    assert [c["word"] for c in offer.get("cards", [])][-1:] == ["一生懸命"]
