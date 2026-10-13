"""Known from Anki, undo of a word marked from a flagged card (P2.4 Part B, item J12).

A word marked from a flagged card that is also suspended must be removed from KnownWord.json by undo, but its card
must not be un-suspended: the suspension was not made by the signal, so Anki's card keeps it. Only a signal that
includes `suspended` in its terms may un-suspend the card on undo. A wrong answer would either leave a card the user
suspended on purpose un-suspended (flag-only signal), or leave a suspended card of a `suspended` signal stuck.

Anki is never reached: `anki_connect` functions are replaced by a fake that records every action it is asked for.
"""
import contextlib

import pytest

from app import anki_connect, anki_sync
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
FLAG_SETTINGS = {"connect_enabled": True, "known_from_anki": ["flag:1"]}
SUSPENDED_SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class SuspendedFlaggedAnki:
    """One flagged card per note; `queue` -1 means Anki says the card is suspended. Every action sent is recorded in
    `calls`, so a test can tell whether undo tried to un-suspend anything."""

    def __init__(self):
        self.found = []
        self.card_note = {}
        self.note_word = {}
        self.queue = {}
        self.calls = []

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
        self.calls.append((action, kwargs))
        if action == "getActiveProfile":
            return "DevTest"
        if action == "guiReviewActive":          # the user is not reviewing; undo may write
            return False
        if action == "unsuspend":
            for c in kwargs["cards"]:            # the card goes live again, as Anki would do it
                self.queue[c] = 0
            return None
        raise AssertionError(f"undo sent Anki an action this test did not expect: {action}")

    def unsuspend_calls(self):
        return [kw["cards"] for action, kw in self.calls if action == "unsuspend"]


@pytest.fixture
def anki(monkeypatch):
    """Route every Anki call of known_signal through the fake; no network, no writer lock."""
    fake = SuspendedFlaggedAnki()
    monkeypatch.setattr(anki_connect, "find_cards", fake.find_cards)
    monkeypatch.setattr(anki_connect, "cards_info", fake.cards_info)
    monkeypatch.setattr(anki_connect, "notes_info", fake.notes_info)
    monkeypatch.setattr(anki_connect, "invoke", fake.invoke)
    monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())
    return fake


def _mark_from_suspended_card(fake, settings, card, word):
    """The first read records the offer (nothing marked); the next read marks the card's word as known."""
    fake.add(card, card + 1000, word, -1)     # queue -1: suspended
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], settings)
    fake.found = [card]
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], settings)
    assert out["marked"] == [word]


def _known_words():
    """The dictForm and knownBy of every KnownWord.json entry, as the file holds them now."""
    data, words = anki_sync._read_known_file("ja")
    return [(w.get("dictForm"), w.get("knownBy")) for w in (words or [])]


def test_undo_of_flag_signal_removes_word_but_leaves_suspended_card_alone(anki):
    """Undoing 上層部, marked from a suspended card under flag:1, removes the word and sends Anki no unsuspend, so
    the card stays suspended. Why: the user's own suspension is not the signal's to undo; a flag-only signal must
    not touch suspension."""
    _mark_from_suspended_card(anki, FLAG_SETTINGS, 201, "上層部")

    out = known_signal.undo("ja", "上層部", URL)

    assert out["removed"] is True
    assert out["unsuspended"] == []
    assert anki.unsuspend_calls() == [], "a flag-only signal must never un-suspend a card"
    assert anki.queue[201] == -1, "the card stays suspended in Anki"
    assert _known_words() == [], "the word leaves the known list"


def test_undo_of_suspended_signal_unsuspends_its_card(anki):
    """Undoing 一生懸命, marked from a suspended card under `suspended`, un-suspends that card and removes the word.
    Why: this is the other half of the rule; with `suspended` in the signal the card's suspension is the signal's
    own, so undo must give it back."""
    _mark_from_suspended_card(anki, SUSPENDED_SETTINGS, 301, "一生懸命")

    out = known_signal.undo("ja", "一生懸命", URL)

    assert out["removed"] is True
    assert out["unsuspended"] == [301]
    assert anki.unsuspend_calls() == [[301]]
    assert anki.queue[301] == 0
    assert _known_words() == []
