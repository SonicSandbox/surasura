"""Known from Anki: a switch turned off, then on again, offers again (P2.4 Part B review).

What the rule protects: when the signal is switched off (known_from_anki: []) the record forgets its terms, so the
next time it is switched on, its first read is a first read again: the newly signalled card is recorded as a pending
offer and nothing is marked. A wrong answer here would rewrite the user's KnownWord.json on the first read after
switching back on, taking a word the user never accepted.

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
ON = {"connect_enabled": True}                              # known_from_anki defaults to ["suspended"]
OFF = {"connect_enabled": True, "known_from_anki": []}      # the switch turned off

# Real Japanese words, one note each.
UPPER = (201, 11, "上層部")
KEHAI = (202, 12, "気配")


class FakeAnki:
    """A card is signalled while it sits in `suspended`."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.suspended = set()
        monkeypatch.setattr(anki_connect, "find_cards", lambda url, query: sorted(self.suspended))
        monkeypatch.setattr(anki_connect, "cards_info",
                            lambda url, ids: [{"cardId": c, "note": self.cards[c]} for c in ids])
        monkeypatch.setattr(anki_connect, "notes_info",
                            lambda url, ids: [{"noteId": n, "modelName": "Lapis",
                                               "fields": {"Expression": {"value": self.words[n], "order": 0}}}
                                              for n in ids])

    def add(self, card, note, word, suspended=True):
        self.cards[card] = note
        self.words[note] = word
        if suspended:
            self.suspended.add(card)


@pytest.fixture
def anki(monkeypatch):
    fake = FakeAnki(monkeypatch)
    fake.add(*UPPER)
    fake.add(*KEHAI, suspended=False)   # signalled only after the switch goes off and on again
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


def test_signal_off_then_on_offers_the_new_card_again_and_marks_nothing(anki, known_file):
    """Switching the signal off forgets its terms, so the next read with it on is a first read: the newly signalled
    card becomes the pending offer, and KnownWord.json keeps its exact bytes. Without the forgetting, that read
    would see the same terms as before and mark the card at once."""
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], ON)     # first read: offer 上層部
    assert known_signal.read("ja", URL, ["DevTest"], ["Expression"], OFF)["skipped"] == "off"

    anki.suspended.add(KEHAI[0])                                       # a new card, after the switch is back on
    with open(known_file, "rb") as f:
        before = f.read()

    result = known_signal.read("ja", URL, ["DevTest"], ["Expression"], ON)

    assert result["marked"] == [], "a read after the switch came back on marks nothing"
    assert result["offered"] == 1
    offer = known_signal.load("ja")["offer"]
    assert offer["state"] == "pending"
    assert [c["word"] for c in offer["cards"]] == ["気配"]
    with open(known_file, "rb") as f:
        assert f.read() == before
