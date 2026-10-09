"""Known from Anki: the window's news comes from the record, not from the read that happened to run (P2.4 Part B, J6).

What the rule protects: a Connect run with no window can mark a word first. Its read leaves the record saying the
window has something to show. If the window's next read finds nothing new and answered "no news", the user never sees
the word: the dashboard only learns of it from the record. So a read with nothing new still reports news while a
marked word is unshown, and only `mark_shown` (the window listing it) turns the news off.

Anki is faked at the app.anki_connect functions the reader calls, and its active profile is pinned to DevTest so no
loopback call is made. The record and KnownWord.json live in the per-test temp root (conftest's SURASURA_TEST_ROOT).
"""
import json
import os

import pytest

from app import anki_connect
from app.connect import known_signal
from app.path_utils import get_user_files_path

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True}  # known_from_anki defaults to ["suspended"]

# A real Japanese word on one note; its card is the signal's card once suspended.
UPPER = (101, 1, "上層部")


class FakeAnki:
    """The signal's cards: a card is signalled while it sits in `suspended`."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.suspended = set()
        monkeypatch.setattr(anki_connect, "find_cards", self._find_cards)
        monkeypatch.setattr(anki_connect, "cards_info", self._cards_info)
        monkeypatch.setattr(anki_connect, "notes_info", self._notes_info)
        # The read's scope asks the active profile; pinned, so no request leaves the test.
        monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kw: "DevTest")

    def add(self, card, note, word):
        self.cards[card] = note
        self.words[note] = word

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
    return fake


@pytest.fixture
def known_file():
    """A KnownWord.json with one unrelated known word, in the user's folder for the test."""
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    data = {"words": [{"dictForm": "溜め息", "knownStatus": "KNOWN", "hasCard": 1, "knownBy": "user"}]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def _read():
    return known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)


def test_news_from_a_marked_word_survives_a_read_with_nothing_new_until_the_window_shows_it(anki, known_file):
    """A run with no window marks 上層部. The next read, with nothing new, must still say news: the word was never
    shown. Only after mark_shown (the window listing it) does a read say no news. A reader that answers from its own
    read alone would say False on that next read, and the user would never see the word."""
    anki.suspended.discard(UPPER[0])     # nothing signalled yet: the first read records no offer
    first = _read()
    assert first["news"] is False        # control: no marked word, no offer, so no news

    anki.suspended.add(UPPER[0])         # the next read marks 上層部, as a Connect run with no window would
    marked = _read()
    assert "上層部" in marked["marked"]
    assert marked["news"] is True

    nothing_new = _read()                # same cards: this read finds nothing new
    assert (nothing_new["marked"], nothing_new["offered"]) == ([], 0)
    assert nothing_new["news"] is True   # the record's news, not this read's

    known_signal.mark_shown("ja")        # the window lists the word
    assert _read()["news"] is False
