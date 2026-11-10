"""Known from Anki, undo (P2.4 Part B row 2.4.15; Sonic, 2026-10-08 P2.4-6 ✅: undo un-suspends).

Undoing one signal-marked word takes that word out of KnownWord.json only when the signal itself added it (after a
dated backup in .trash), and un-suspends its card only while Anki still reports it suspended. A wrong answer here
would either drop a word the user knew another way, or un-suspend a card the user had already put back to active.

Anki is never reached: find_cards / cards_info / notes_info / invoke / writer are replaced by a small fake.
"""
import contextlib
import glob
import json
import os

import pytest

from app import anki_connect, anki_sync
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class FakeAnki:
    """Cards and notes held in memory; `queue` -1 means Anki says the card is suspended."""

    def __init__(self):
        self.found = []
        self.card_note = {}
        self.note_word = {}
        self.queue = {}
        self.unsuspended = []

    def add(self, card, note, word, queue):
        self.card_note[card] = note
        self.note_word[note] = word
        self.queue[card] = queue

    def find_cards(self, url, query):
        return list(self.found)

    def cards_info(self, url, ids):
        return [{"cardId": c, "note": self.card_note[c], "queue": self.queue[c]} for c in ids]

    def notes_info(self, url, ids):
        return [{"noteId": n, "modelName": "Lapis",
                 "fields": {"Expression": {"value": self.note_word[n], "order": 0}}} for n in ids]

    def invoke(self, action, url, **kwargs):
        if action == "unsuspend":
            self.unsuspended.extend(kwargs["cards"])
        return None


@pytest.fixture
def fake_anki(monkeypatch):
    """Route every Anki call of known_signal through the fake; no network, no writer lock."""
    fake = FakeAnki()
    monkeypatch.setattr(anki_connect, "find_cards", fake.find_cards)
    monkeypatch.setattr(anki_connect, "cards_info", fake.cards_info)
    monkeypatch.setattr(anki_connect, "notes_info", fake.notes_info)
    monkeypatch.setattr(anki_connect, "invoke", fake.invoke)
    monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())
    return fake


def _known_words():
    """The dictForm and knownBy of every KnownWord.json entry, as the file holds them now."""
    data, words = anki_sync._read_known_file("ja")
    return [(w.get("dictForm"), w.get("knownBy")) for w in (words or [])]


def _signal_two_words(fake):
    """The first read records the offer; a later read marks two newly signalled cards (上層部, 一生懸命)."""
    fake.add(101, 1, "上層部", -1)
    fake.add(102, 2, "一生懸命", -1)
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)   # the one-time read: nothing marked
    fake.found = [101, 102]
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    assert sorted(out["marked"]) == ["一生懸命", "上層部"]


def test_undo_removes_only_its_own_word_and_unsuspends_its_still_suspended_card(fake_anki):
    """Undoing 上層部 takes only that signal entry out and un-suspends only its card (queue -1); 一生懸命 stays
    known and its card stays suspended. A backup of KnownWord.json is kept in .trash before the change."""
    _signal_two_words(fake_anki)

    result = known_signal.undo("ja", "上層部", URL)

    assert result == {"removed": True, "unsuspended": [101]}
    assert fake_anki.unsuspended == [101]
    assert _known_words() == [("一生懸命", "anki-signal")]
    trash = os.path.join(os.path.dirname(anki_sync._known_path("ja")), ".trash")
    assert glob.glob(os.path.join(trash, "KnownWord*")), "undo must back KnownWord.json up first"


def test_undo_leaves_a_card_already_back_to_active_alone(fake_anki):
    """A card the user has since un-suspended (queue 0) is not un-suspended again; the word is still taken out,
    because the signal added it. Why: un-suspending an active card would be a write Anki never asked for."""
    _signal_two_words(fake_anki)
    fake_anki.queue[101] = 0

    result = known_signal.undo("ja", "上層部", URL)

    assert result["removed"] is True
    assert result["unsuspended"] == []
    assert fake_anki.unsuspended == []


def test_undo_keeps_a_word_that_was_known_before_the_signal(fake_anki):
    """A word the user already knew another way (its KnownWord entry has no knownBy) is not taken out by undo,
    even though its card is marked here. Why: a signal undo must never erase knowledge the signal did not add."""
    data_path = anki_sync._known_path("ja")
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": "上層部", "knownStatus": "KNOWN"}]}, f, ensure_ascii=False)
    fake_anki.add(101, 1, "上層部", -1)
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)   # the one-time read
    fake_anki.found = [101]
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    assert out["marked"] == []   # already known, so nothing new was appended

    result = known_signal.undo("ja", "上層部", URL)

    assert result["removed"] is False
    assert _known_words() == [("上層部", None)]
