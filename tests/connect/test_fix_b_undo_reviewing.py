"""Known from Anki, undo while you review in Anki (P2.4 Part B final-adversary fix; item J10).

While Anki's reviewer is open, `undo` must raise and change nothing: the cards stay suspended (no `unsuspend` call
reaches Anki), the word stays in KnownWord.json with its anki-signal mark, and its record entry is not marked undone,
so the undo can be tried again after the review. A wrong answer would un-suspend cards under the user's review and
drop the word from the known list while the record said nothing happened.

Anki is never reached: the calls known_signal makes are replaced by a fake, and `reviewing` is switched on by the test.
"""
import contextlib

import pytest

from app import anki_connect, anki_sync
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class SuspendedAnki:
    """Cards held in memory; queue -1 means Anki says the card is suspended. Every invoke is recorded, so a test can
    see whether undo tried to un-suspend anything."""

    def __init__(self):
        self.found = []
        self.card_note = {}
        self.note_word = {}
        self.queue = {}
        self.calls = []
        self.reviewing_now = False

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
        if action == "getActiveProfile":        # the reads before undo record their Anki profile
            return "DevTest"
        if action == "unsuspend":
            return None
        raise AssertionError(f"unexpected Anki action {action} in an undo test")

    def reviewing(self, url):
        return self.reviewing_now


@pytest.fixture
def anki(monkeypatch):
    """Route every Anki call of known_signal through the fake; no network, no writer lock. Cleanup is monkeypatch's."""
    fake = SuspendedAnki()
    monkeypatch.setattr(anki_connect, "find_cards", fake.find_cards)
    monkeypatch.setattr(anki_connect, "cards_info", fake.cards_info)
    monkeypatch.setattr(anki_connect, "notes_info", fake.notes_info)
    monkeypatch.setattr(anki_connect, "invoke", fake.invoke)
    monkeypatch.setattr(anki_connect, "reviewing", fake.reviewing)
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


def test_undo_while_reviewing_raises_and_unsuspends_nothing(anki):
    """Undoing 上層部 while Anki's reviewer is open raises; no unsuspend reaches Anki, the card stays suspended,
    KnownWord.json still holds both signal entries, and the record keeps 上層部 without an undone mark.
    Why: a word must not leave the known list, and its card must not wake up, under the user's review."""
    _signal_two_words(anki)
    anki.reviewing_now = True

    with pytest.raises(RuntimeError, match="reviewing"):
        known_signal.undo("ja", "上層部", URL)

    assert not [c for c in anki.calls if c[0] == "unsuspend"], "undo must not un-suspend while you review"
    assert anki.queue[101] == -1, "the card stays suspended"
    assert _known_words() == [("上層部", "anki-signal"), ("一生懸命", "anki-signal")]
    marked = [m for m in known_signal.load("ja").get("marked") or () if m.get("word") == "上層部"]
    assert marked and all(not m.get("undone") for m in marked)
