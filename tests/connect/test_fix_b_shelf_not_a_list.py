"""Review fix B #11: the shelf never reads a bad answer from AnkiConnect as "none" (P2.4 Part B review).

When AnkiConnect answers something other than a list to a search (a protocol slip, or a half-up Anki), the shelf's
`AnkiConnectAnki` must raise `AnkiError` rather than return an empty result. An empty result read as "none" would
make `shelf.gone_notes` call every note gone, so the store would mark the learner's whole library as removed from
Anki. What a wrong answer would cost here is that loss of the library's record, so each test pins the raise and the
list that still comes back as ints.

Why the monkeypatch: `invoke` is the one place a real AnkiConnect call happens; patching it keeps the test off the
network while the code under test (`AnkiConnectAnki._ids`) runs unchanged.
"""
import pytest

from app import anki_connect
from app.connect import shelf


def test_find_notes_raises_when_anki_answers_none_not_a_list(monkeypatch):
    # Why: `None` is what a failed or half-answered call can look like; reading it as "no notes" would call every
    # note gone. The shelf must see an error, so it marks nothing.
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: None)
    adapter = shelf.AnkiConnectAnki("http://127.0.0.1:8765")

    with pytest.raises(anki_connect.AnkiError):
        adapter.find_notes("note:Lapis")


def test_gone_notes_marks_nothing_when_anki_answers_a_non_list(monkeypatch):
    # Why: the end-to-end rule. Notes 1 and 2 are still in Anki; a non-list answer must raise, not report both gone.
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: {"error": "busy"})
    adapter = shelf.AnkiConnectAnki("http://127.0.0.1:8765")

    with pytest.raises(anki_connect.AnkiError):
        shelf.gone_notes(adapter, [1, 2])


def test_find_notes_returns_ints_when_anki_answers_a_list(monkeypatch):
    # Why: the guard must not reject a good answer. Anki may send ids as strings; the shelf compares them as ints.
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: [3, "4"])
    adapter = shelf.AnkiConnectAnki("http://127.0.0.1:8765")

    assert adapter.find_notes("nid:3,4") == [3, 4]
