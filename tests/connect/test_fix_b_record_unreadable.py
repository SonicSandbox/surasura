"""Known from Anki's record: an unreadable record is never written over (P2.4 Part B, review B #17).

The record (`known-signal-ja.json`) holds what the signal has read so far: the offer, the cards seen, the terms.
If that file exists but can't be parsed, `known_signal.load` must raise `Unreadable` rather than act as though
there were no record, and `read` must stop before it saves, so the file's bytes stay exactly as the user left
them. A wrong answer here would throw away the offer and the seen-card list, and the next read would offer and
mark the same cards again. A missing record is the first read and loads as {}.

Anki is always a fake (the `fake_anki` fixture of the undo test pattern): no network, no writer lock.
"""
import contextlib
import os

import pytest

from app import anki_connect
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}
BROKEN = b"{not json"


class FakeAnki:
    """Nothing in Anki matches: a read that reaches the save would still write, which is what the test catches."""

    def find_cards(self, url, query):
        return []

    def cards_info(self, url, ids):
        return []

    def notes_info(self, url, ids):
        return []

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


@pytest.fixture
def record_file():
    """The Japanese record at its real path (inside the test root), removed again after the test."""
    path = known_signal.record_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_unreadable_record_raises_unreadable_on_load(record_file):
    """A record that is not JSON raises `Unreadable` from `load`: it is not silently taken as an empty record."""
    with open(record_file, "wb") as f:
        f.write(BROKEN)
    with pytest.raises(known_signal.Unreadable):
        known_signal.load("ja")


def test_read_over_unreadable_record_raises_and_leaves_bytes_as_they_were(fake_anki, record_file):
    """A read whose record can't be parsed raises `Unreadable` and writes nothing: the file's bytes are unchanged.
    Why: with the record taken as {}, the read would save its own state over the user's file."""
    with open(record_file, "wb") as f:
        f.write(BROKEN)
    with pytest.raises(known_signal.Unreadable):
        known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    with open(record_file, "rb") as f:
        assert f.read() == BROKEN


def test_missing_record_loads_as_empty_so_the_first_read_can_start(record_file):
    """No record yet is the first read, not a fault: `load` returns {} and does not raise."""
    if os.path.exists(record_file):
        os.remove(record_file)
    assert known_signal.load("ja") == {}
