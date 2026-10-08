"""Known from Anki, preview off (P2.4 row 2.4.15): with Connect's preview off, `read_known_signal` asks nothing.

What a wrong answer would cost: with the preview off the 2.5 path must stay byte-identical, so a read that reaches
Anki (or writes a record) for a user who never turned Connect on would be a silent network call and an unasked-for
change to their words. The ON case is here too, so the OFF case cannot pass just because the function always
returns None: the same settings with the preview on must return a dict, and must reach Anki.
"""
import contextlib

import pytest

from app import anki_connect, anki_sync


URL = "http://127.0.0.1:8765"
WORD_NOTE = {"noteId": 1700000001, "modelName": "Lapis",
             "fields": {"Expression": {"value": "上層部", "order": 0}}}


@pytest.fixture
def anki_calls(monkeypatch):
    """Fake the AnkiConnect functions the known-signal read calls; every call is recorded so a test can prove
    that none ran. Nothing reaches Anki: the fakes replace the functions, not the module under test."""
    calls = []

    def find_cards(url, query):
        calls.append(("find_cards", query))
        return [4001]

    def cards_info(url, card_ids):
        calls.append(("cards_info", list(card_ids)))
        return [{"cardId": 4001, "note": WORD_NOTE["noteId"]}]

    def notes_info(url, note_ids):
        calls.append(("notes_info", list(note_ids)))
        return [WORD_NOTE]

    def invoke(*args, **kwargs):
        calls.append(("invoke", args))
        return None

    monkeypatch.setattr(anki_connect, "find_cards", find_cards)
    monkeypatch.setattr(anki_connect, "cards_info", cards_info)
    monkeypatch.setattr(anki_connect, "notes_info", notes_info)
    monkeypatch.setattr(anki_connect, "invoke", invoke)
    monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())
    return calls


@pytest.mark.parametrize("settings", [
    {"known_from_anki": ["suspended"]},                      # preview key missing
    {"connect_enabled": False, "known_from_anki": ["suspended"]},  # preview explicitly off
], ids=["key-missing", "key-false"])
def test_known_signal_off_asks_nothing_and_calls_no_anki_function(settings, anki_calls):
    # Why: the 2.5 path must not reach AnkiConnect at all when the preview is off, even with the signal set.
    result = anki_sync.read_known_signal("ja", URL, ["DevTest"], ["Expression"], settings)

    assert result is None
    assert anki_calls == []


def test_known_signal_on_with_fakes_returns_a_result_and_reads_anki(anki_calls):
    # Why: the same call with the preview on does read Anki, so the OFF test above is not passing trivially.
    settings = {"connect_enabled": True, "known_from_anki": ["suspended"]}

    result = anki_sync.read_known_signal("ja", URL, ["DevTest"], ["Expression"], settings)

    assert isinstance(result, dict)
    assert result["offered"] == 1  # first read only records the one-time offer for 上層部
    assert any(name == "find_cards" for name, _ in anki_calls)
