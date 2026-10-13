"""Known from Anki, the summary's unshown list (P2.4 Part B review fix B #15, item H14).

The summary says "You suspended N cards since ..." from `known_signal.unshown`. Words the user got by accepting the
one-time offer were answered by the user in the offer, not by a suspension, so they must stay out of that summary;
a word a later read marks is a suspension the summary must name. A wrong answer here would tell the user they
suspended cards they only accepted in one click, or hide a word a real suspension marked.

Anki is never reached: find_cards / cards_info / notes_info / invoke / writer are replaced by a small fake.
"""
import contextlib

import pytest

from app import anki_connect
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


def test_summary_leaves_out_the_offer_words_but_names_a_later_suspension(fake_anki):
    """Accepting the offer makes 上層部 and 一生懸命 known, but the summary's unshown list stays empty; a card
    suspended after that (溜め息) is the one word it names. Why: an offer answer is not a suspension the summary
    should report as one."""
    # The first read records the offer for the two suspended cards already there; nothing is marked yet.
    fake_anki.add(101, 1, "上層部", -1)
    fake_anki.add(102, 2, "一生懸命", -1)
    fake_anki.found = [101, 102]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)

    # The user accepts the offer: both words are marked by the offer, not by a suspension.
    added = known_signal.accept_offer("ja", URL)
    assert sorted(added) == ["一生懸命", "上層部"]
    assert known_signal.unshown("ja") == []

    # A later suspension is read and marked by the signal: that one, and only that one, is summarised.
    fake_anki.add(103, 3, "溜め息", -1)
    fake_anki.found = [101, 102, 103]
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    assert out["marked"] == ["溜め息"]
    assert [m["word"] for m in known_signal.unshown("ja")] == ["溜め息"]
