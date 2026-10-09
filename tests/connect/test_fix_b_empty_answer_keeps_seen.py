"""Known from Anki: an empty answer from Anki never empties what was seen (P2.4 Part B, adversary B #1c).

What the rule protects: Anki's bad reply to a search reads as "no cards". If the reader took that as the truth, the
record's list of seen cards would go empty, and the next good reply would look like every card was new again. Those
cards would then be marked known in KnownWord.json although the user had already been offered them and said nothing.
A wrong answer here would mark a word known that the user never accepted.

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
SIGNAL = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class FakeAnki:
    """Cards and notes held in memory; the cards listed in `found` are what Anki answers to the signal's query."""

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


def test_empty_answer_keeps_seen_cards_so_they_are_not_marked_later(anki, known_file):
    """After a first read offers 201 and 202, an empty answer from Anki must leave both in the record's seen list,
    so that when Anki answers them again they are still not new and mark nothing. Why: an empty reply is Anki's
    failure, not the user's deletion of those cards; treating it as none would mark them known unseen."""
    anki.add(201, 1, "気配")
    anki.add(202, 2, "勇気")
    anki.found = [201, 202]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SIGNAL)      # the first read: records the offer

    anki.found = []                                                        # Anki's bad reply: no cards
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SIGNAL)
    assert known_signal.load("ja").get("seen") == [201, 202]               # the empty answer kept what was seen

    anki.found = [201, 202]                                                # Anki answers properly again
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], SIGNAL)

    assert out["marked"] == []                                             # they were seen: nothing marked
    with open(known_file, encoding="utf-8") as f:                          # KnownWord.json: 気配 never marked known
        assert "気配" not in [w["dictForm"] for w in json.load(f)["words"]]
