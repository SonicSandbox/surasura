"""Known from Anki, the summary's unshown list only loses the words the window actually listed (P2.4 Part B final
adversary, item J11, over known_signal.mark_shown / unshown).

The window lists its unshown words, then calls `mark_shown` with just those. A word it did not list (one past its
first 30) must stay unshown and come up next time. Words the user accepted from the offer are listed under their own
heading, so they must never leak into the signal's unshown list. A wrong answer here would drop a real suspension
from the summary the first time the window showed a few of them, or name an offer answer as a suspension.

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


def test_mark_shown_of_one_word_leaves_the_other_listed_words_unshown(fake_anki):
    """Three suspensions are marked by the signal; the window lists only 上層部 and calls mark_shown with it. The
    unshown list must still name 一生懸命 and 溜め息. Why: the window pages its list, and a word it did not show
    must come up again next time, not vanish after one page."""
    # The first read only records an offer for the card already suspended; nothing is marked yet.
    fake_anki.add(101, 1, "気配", -1)
    fake_anki.found = [101]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)

    # Three later suspensions are read and marked by the signal.
    fake_anki.add(102, 2, "上層部", -1)
    fake_anki.add(103, 3, "一生懸命", -1)
    fake_anki.add(104, 4, "溜め息", -1)
    fake_anki.found = [101, 102, 103, 104]
    out = known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    assert sorted(out["marked"]) == ["一生懸命", "上層部", "溜め息"]
    assert sorted(m["word"] for m in known_signal.unshown("ja")) == ["一生懸命", "上層部", "溜め息"]

    # The window shows only 上層部 and marks just that one shown.
    known_signal.mark_shown("ja", {"上層部"})
    assert sorted(m["word"] for m in known_signal.unshown("ja")) == ["一生懸命", "溜め息"]


def test_offer_words_list_under_offer_and_never_under_the_signal(fake_anki):
    """Two cards suspended before the first read are accepted from the offer. They appear in unshown("ja", "offer")
    and never in unshown("ja"). Why: the summary says "you suspended N cards", and an offer answer is not one."""
    fake_anki.add(201, 5, "上層部", -1)
    fake_anki.add(202, 6, "一生懸命", -1)
    fake_anki.found = [201, 202]
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)

    known_signal.accept_offer("ja", URL)
    assert sorted(m["word"] for m in known_signal.unshown("ja", "offer")) == ["一生懸命", "上層部"]
    assert known_signal.unshown("ja") == []
