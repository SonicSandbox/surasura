"""Known from Anki: the first read offers, later reads mark (P2.4 Part B).

What the rule protects: a card suspended in Anki means "I know this". The first read of a library must not
silently mark every card the user ever suspended (an offer is asked once, and only accepting it marks the words),
and a later read must mark exactly the cards signalled since the last read. A wrong answer here would either
rewrite the user's KnownWord.json without asking (the first read) or drop a word the user just marked known
(a later read that misses it), and a word already known must never gain a second entry.

Anki is faked at the app.anki_connect functions the reader calls; KnownWord.json and the record live in the
per-test temp root (conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
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
ISSHO = (103, 3, "一生懸命")


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
    fake.add(*UPPER)
    fake.add(*KEHAI, suspended=False)  # signalled later in the tests, so the first read sees only 上層部
    fake.add(*ISSHO, suspended=False)  # never signalled: never offered, never marked
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


def _read(decks=("DevTest",)):
    return known_signal.read("ja", URL, list(decks), ["Expression"], SETTINGS)


def _words(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["words"]


def test_first_read_marks_nothing_and_only_records_an_offer(anki, known_file):
    """The first read of a library must not rewrite KnownWord.json: the signalled card is kept as a pending offer,
    and the file's bytes stay exactly as they were. Marking at once would take words the user never accepted."""
    with open(known_file, "rb") as f:
        before = f.read()

    result = _read()

    assert result["marked"] == []
    assert result["offered"] == 1
    assert known_signal.load("ja")["offer"]["state"] == "pending"
    with open(known_file, "rb") as f:
        assert f.read() == before


def test_later_read_marks_the_newly_signalled_card_and_not_the_offer(anki, known_file):
    """After the offer is recorded, one more suspension is marked known on the next read, with its knownBy tag. The
    card still waiting in the offer is not marked by that read: only accepting the offer marks it."""
    _read()
    anki.suspended.add(KEHAI[0])

    result = _read()

    assert result["marked"] == ["気配"]
    entries = {w["dictForm"]: w for w in _words(known_file)}
    assert entries["気配"]["knownBy"] == "anki-signal"
    assert "上層部" not in entries


def test_a_word_already_known_is_recorded_but_not_appended_twice(anki, known_file):
    """A signalled word the user already knows adds no second entry and is not reported as newly marked. Appending
    it again would duplicate a row in the user's file. The read still records it, so undo knows it was not the
    signal's own word (added False)."""
    with open(known_file, encoding="utf-8") as f:
        data = json.load(f)
    data["words"].append({"dictForm": "気配", "knownStatus": "KNOWN", "hasCard": 1, "knownBy": "user"})
    with open(known_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    _read()
    anki.suspended.add(KEHAI[0])

    result = _read()

    assert result["marked"] == []
    kehai = [w for w in _words(known_file) if w["dictForm"] == "気配"]
    assert len(kehai) == 1
    assert kehai[0]["knownBy"] == "user"  # the signal left the user's own entry as it was
    recorded = [m for m in known_signal.load("ja")["marked"] if m["word"] == "気配"]
    assert len(recorded) == 1 and recorded[0]["added"] is False


def test_accepting_the_offer_marks_the_offered_words(anki, known_file):
    """Accepting the one-time offer marks the words of the cards signalled at the first read, tagged as the signal's,
    and closes the offer so it is not asked again."""
    _read()

    added = known_signal.accept_offer("ja")

    assert added == ["上層部"]
    entries = {w["dictForm"]: w for w in _words(known_file)}
    assert entries["上層部"]["knownBy"] == "anki-signal"
    assert known_signal.load("ja")["offer"]["state"] == "accepted"
    assert known_signal.accept_offer("ja") == []
