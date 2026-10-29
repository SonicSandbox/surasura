"""Laptop round 7 #43 (build 3): cards suspended and marked in Anki (一緒に, やがる) never counted as known.

Rules pinned, in plain words:
- every known-words sync runs one order (`anki_sync.sync_all`): the studied words, the decks' new and young cards,
  then Known from Anki (your suspended / marked cards) — the 3.0 window's sync included, which before stopped after the
  new cards, so the signal was read only behind Connect's throttled known-sync and never ran on the laptop;
- the words the signal marks are words this sync made known: they count in its `added` and its known total, so the
  window's own rule (a sync that added words → the automatic Generate) runs for them too;
- the cards already signalled at the first read are a one-time question (*Mark their words known?*): 3.0's Needs you
  shows it (⭐ B3-1 A), *Mark them known* accepts it and asks the journey again, *Leave them* declines it.

What a wrong answer would cost: the laptop's state — the setting says "a card in every state you pick marks its word
known", yet no card ever did, and the journey counts the words as unknown.

Pure: the Anki calls are stand-ins; the known-signal record in a temp local-data folder. Never a live Anki.
"""
import json
import os

import pytest

from app import anki_sync
from app.services import needs


class Result:
    def __init__(self, added=0, total=10, error=None):
        self.added, self.total_known, self.error = added, total, error


def test_every_sync_reads_the_signal_last_and_counts_its_words(monkeypatch):
    # why: before, the window's sync stopped after the new cards; the signal must come after both, in one order
    calls = []
    monkeypatch.setattr(anki_sync, "sync", lambda *a, **k: (calls.append("sync"), Result(added=2, total=10))[1])
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: calls.append("backlog"))
    monkeypatch.setattr(anki_sync, "sync_young", lambda *a, **k: calls.append("young"))
    monkeypatch.setattr(anki_sync, "read_known_signal",
                        lambda *a, **k: (calls.append("signal"), {"marked": ["一緒に", "やがる"], "offered": 0})[1])
    result, signal = anki_sync.sync_all("ja", "http://127.0.0.1:8765", ["Deck"], [], {"connect_enabled": True})
    assert calls == ["sync", "backlog", "young", "signal"]
    assert signal["marked"] == ["一緒に", "やがる"]
    assert (result.added, result.total_known) == (4, 12), "the signal's words are this sync's new known words"


def test_a_sync_with_no_signal_keeps_its_own_counts(monkeypatch):
    # why: Connect off (None) or an offer only: nothing marked, so the sync's counts are its own
    monkeypatch.setattr(anki_sync, "sync", lambda *a, **k: Result(added=1, total=5))
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: None)
    monkeypatch.setattr(anki_sync, "sync_young", lambda *a, **k: None)
    for signal in (None, {"marked": [], "offered": 40}):
        monkeypatch.setattr(anki_sync, "read_known_signal", lambda *a, _s=signal, **k: _s)
        result, _ = anki_sync.sync_all("ja", None, ["Deck"], [], {})
        assert (result.added, result.total_known) == (1, 5)


def test_a_failed_sync_reads_no_signal(monkeypatch):
    # why: a sync that couldn't read KnownWord.json or Anki must not go on writing the same file from the signal
    monkeypatch.setattr(anki_sync, "sync", lambda *a, **k: Result(error="KnownWord.json can't be read"))
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: None)
    monkeypatch.setattr(anki_sync, "read_known_signal", lambda *a, **k: pytest.fail("read after a failed sync"))
    result, signal = anki_sync.sync_all("ja", None, ["Deck"], [], {})
    assert result.error and signal is None


def test_the_window_sync_goes_through_the_one_order():
    # why: the 3.0 window's sync is the one Sonic's clicks run; it must call `sync_all`, never `sync` alone
    import inspect
    from app.services import automation
    src = inspect.getsource(automation.AutoSync._work)
    assert "anki_sync.sync_all(" in src and "anki_sync.sync(" not in src


@pytest.fixture
def record(tmp_path, monkeypatch):
    """Known from Anki's record in a temp local-data folder -> a function writing it."""
    from app import path_utils
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: str(tmp_path))

    def write(data):
        os.makedirs(tmp_path / "connect", exist_ok=True)
        with open(tmp_path / "connect" / "known-signal-ja.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return write


def _offer(n, state="pending"):
    return {"read": "2026-10-22T17:20:00", "terms": ["suspended", "marked"],
            "offer": {"state": state, "query": "q",
                      "cards": [{"word": w, "card": i, "note": 100 + i}
                                for i, w in enumerate(["一緒に", "やがる", "勇気", "約束"][:n], 1)]}}


def test_a_pending_offer_is_read_with_connects_record(record):
    record(_offer(2))
    got = needs.known_offer("ja")
    assert (got["cards"], got["terms"]) == (2, ["suspended", "marked"]) and got["id"]


@pytest.mark.parametrize("data", [None, _offer(2, "accepted"), _offer(2, "declined"), _offer(0)])
def test_no_offer_when_there_is_none_to_answer(record, data):
    # why: no record, an answered offer or an empty one is no question
    if data is not None:
        record(data)
    assert needs.known_offer("ja") is None


def test_the_offer_is_one_needs_you_entry_with_its_count_and_two_answers():
    connect = {"known_offer": {"cards": 40, "terms": ["suspended", "marked"]}}
    found = [e for e in needs.entries(None, connect=connect) if e.kind == needs.KNOWN_OFFER]
    assert len(found) == 1
    entry = found[0]
    assert "40" in entry.title and "suspended and marked" in entry.title
    assert entry.actions == ("mark_known", "leave_known") and entry.unseen
    assert not [e for e in needs.entries(None, connect={}) if e.kind == needs.KNOWN_OFFER]
    assert not [e for e in needs.entries(None, connect=None) if e.kind == needs.KNOWN_OFFER], "Connect off: none"


def test_the_offers_states_read_as_words():
    # why: the title names the states you picked, a flag by its colour
    assert needs.signal_words(["suspended"]) == "suspended"
    assert needs.signal_words(["suspended", "flag:1"]) == "suspended and flagged red"


def test_a_syncs_end_asks_needs_you_again_once():
    # why: the question appears after a sync made it; the page must look again when a sync ends, once per sync
    pytest.importorskip("PyQt6")
    from types import SimpleNamespace
    from app.qt import shell
    asked = []
    fake = SimpleNamespace(needs_you=SimpleNamespace(synced=lambda: asked.append(1)),
                           duties=SimpleNamespace(auto_state=SimpleNamespace(sync="syncing")))
    state = SimpleNamespace(sync="synced")
    try:
        shell.ShellWindow._show_automation(fake, state)
    except AttributeError:
        pass                                    # the rest of the handler paints a window this fake doesn't have
    assert asked == [1]
    fake.duties.auto_state = state
    try:
        shell.ShellWindow._show_automation(fake, SimpleNamespace(sync="synced"))
    except AttributeError:
        pass
    assert asked == [1], "the same sync's state again: no second look"


def test_the_windows_frozen_settings_still_read_the_signal():
    # why (review r2 #1): the 3.0 window hands its settings frozen (lists become tuples), and the signal read them as
    # "off", then wrote the record's terms empty at every sync
    from app.connect import known_signal
    from app.services.settings import freeze
    settings = freeze({"connect_enabled": True, "known_from_anki": ["suspended", "marked"]})
    assert known_signal.signal(settings) == ["suspended", "marked"]


def test_the_anki_windows_sync_now_goes_through_the_one_order(monkeypatch):
    # why (review r2 #5): *Sync now* in the Anki window and the wizard's first sync read the signal too
    from app import anki_window, settings_manager
    calls = []
    monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: {"connect_enabled": True})
    monkeypatch.setattr(anki_sync, "sync_all", lambda *a, **k: (calls.append((a, k)), (Result(added=1), None))[1])
    result = anki_window.run_sync("ja", "http://127.0.0.1:8765", ["Deck"], [], False, full=True)
    assert result.added == 1
    (args, kw), = calls
    assert args[4] == {"connect_enabled": True} and kw == {"include_suspended": False, "full": True}
