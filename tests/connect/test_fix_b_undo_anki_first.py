"""Known from Anki, undo with Anki gone (P2.4 Part B review fix, #13 / #25; item H12).

When Anki is closed at the moment the user presses undo, `undo` must raise and change nothing: the word stays in
KnownWord.json with its anki-signal mark, no backup is written, and its record entry is not marked undone, so a later
undo can try again. A wrong answer would drop a word from the user's known list while its suspended cards stay
suspended, and the record would say the undo happened when it did not.

Anki is never reached: the calls known_signal makes are replaced by a fake that can be switched to "closed".
"""
import contextlib
import glob
import os

import pytest

from app import anki_connect, anki_sync
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class ClosableAnki:
    """Cards held in memory; `queue` -1 means Anki says the card is suspended. Once `closed` is set, every
    cards_info call fails the way a closed Anki does (AnkiError kind 'offline')."""

    def __init__(self):
        self.found = []
        self.card_note = {}
        self.note_word = {}
        self.queue = {}
        self.closed = False

    def add(self, card, note, word, queue):
        self.card_note[card] = note
        self.note_word[note] = word
        self.queue[card] = queue

    def find_cards(self, url, query):
        return list(self.found)

    def cards_info(self, url, ids):
        if self.closed:
            raise anki_connect.AnkiError("closed", kind="offline")
        return [{"cardId": c, "note": self.card_note[c], "queue": self.queue[c]} for c in ids]

    def notes_info(self, url, ids):
        return [{"noteId": n, "modelName": "Lapis",
                 "fields": {"Expression": {"value": self.note_word[n], "order": 0}}} for n in ids]

    def invoke(self, action, url, **kwargs):
        if action == "getActiveProfile":        # the reads before undo record their Anki profile (adversary B #1)
            return "DevTest"
        raise AssertionError(f"undo must not reach Anki's {action} once Anki is closed")


@pytest.fixture
def closable_anki(monkeypatch):
    """Route every Anki call of known_signal through the fake; no network, no writer lock."""
    fake = ClosableAnki()
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


def test_undo_with_anki_closed_raises_and_changes_nothing(closable_anki):
    """Undoing 上層部 while Anki is closed raises; KnownWord.json still holds both signal entries, no backup is
    written to .trash, and the record keeps 上層部 without an undone mark, so the undo can be tried again.
    Why: a word must not leave the known list when its cards were never un-suspended."""
    _signal_two_words(closable_anki)
    closable_anki.closed = True

    with pytest.raises(anki_connect.AnkiError):
        known_signal.undo("ja", "上層部", URL)

    assert _known_words() == [("上層部", "anki-signal"), ("一生懸命", "anki-signal")]
    trash = os.path.join(os.path.dirname(anki_sync._known_path("ja")), ".trash")
    assert not glob.glob(os.path.join(trash, "KnownWord*")), "a failed undo must not back up or rewrite the file"
    marked = [m for m in known_signal.load("ja").get("marked") or () if m.get("word") == "上層部"]
    assert marked and all(not m.get("undone") for m in marked)
