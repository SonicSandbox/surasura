"""Known from Anki: a read that finds nothing new writes nothing (P2.4 Part B, charter S19).

What the rule protects: the signal is read on every sync, and most reads find nothing new. If each one rewrote the
record, every idle sync would touch the user's files for no reason (and a rewrite can clash with a file the user has
open). The opposite wrong answer, a read that skips a real change, would leave a card unrecorded. So a read whose
cards are the same as the last read's leaves the record's bytes and modification time, and KnownWord.json's bytes,
exactly as they were, while a read whose cards changed does rewrite the record.

Anki is faked at the app.anki_connect functions the reader calls (as test_known_from_anki_read.py does); the record and
KnownWord.json live in the per-test temp root (conftest's SURASURA_TEST_ROOT), so nothing touches a real library.
"""
import json
import os

import pytest

from app import anki_connect
from app.connect import known_signal
from app.path_utils import get_user_files_path

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True}  # known_from_anki defaults to ["suspended"]

# Real Japanese words, one note each; the card ids are the signal's cards.
UPPER = (101, 1, "上層部")
KEHAI = (102, 2, "気配")

# A fixed past modification time: a write moves it to now, so a write is seen even when the bytes come out the same.
PAST_NS = 1_000_000_000 * 10 ** 9


class FakeAnki:
    """The signal's cards: a card is signalled while it sits in `suspended`."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.suspended = set()
        monkeypatch.setattr(anki_connect, "find_cards", self._find_cards)
        monkeypatch.setattr(anki_connect, "cards_info", self._cards_info)
        monkeypatch.setattr(anki_connect, "notes_info", self._notes_info)

    def add(self, card, note, word, suspended=True):
        self.cards[card] = note
        self.words[note] = word
        if suspended:
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
    fake.add(*UPPER)                    # suspended: the first read records it as the offer
    fake.add(*KEHAI, suspended=False)   # signalled later in the tests
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


def _read():
    return known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)


def _stamp(path):
    """The file's bytes and its modification time, the two things a write changes."""
    with open(path, "rb") as f:
        data = f.read()
    return data, os.stat(path).st_mtime_ns


def _set_past_mtime(path):
    os.utime(path, ns=(PAST_NS, PAST_NS))


def test_a_read_that_finds_nothing_new_writes_neither_the_record_nor_known_word_json(anki, known_file):
    """After a first read and a read that marked 気配, a third read whose cards are the same finds nothing new. It
    must leave the record and KnownWord.json untouched: same bytes, same modification time. A rewrite here is the
    idle-sync write this rule forbids, and the record's `read` stamp would move too."""
    _read()                                  # first read: the offer is recorded
    anki.suspended.add(KEHAI[0])
    _read()                                  # a later read marks 気配 and saves the cards it has seen
    assert "気配" in [m["word"] for m in known_signal.load("ja")["marked"]]

    record = known_signal.record_path("ja")
    _set_past_mtime(record)
    _set_past_mtime(known_file)
    before = (_stamp(record), _stamp(known_file))

    result = _read()                         # same cards, nothing new

    assert (result["marked"], result["offered"], result["skipped"]) == ([], 0, None)
    assert (_stamp(record), _stamp(known_file)) == before


def test_a_read_whose_cards_changed_rewrites_the_record(anki, known_file):
    """The control for the test above: when a card is un-suspended, the card list changes, so the read saves it and the
    record keeps the cards as they are now. Without this, a reader that never saves would pass the test above."""
    _read()                                  # first read: the offer is recorded
    anki.suspended.add(KEHAI[0])
    _read()                                  # 気配 marked; seen is now 上層部 and 気配

    record = known_signal.record_path("ja")
    _set_past_mtime(record)
    anki.suspended.discard(KEHAI[0])         # the card list shrinks to 上層部 alone
    _read()

    assert os.stat(record).st_mtime_ns != PAST_NS
    assert known_signal.load("ja")["seen"] == [UPPER[0]]
