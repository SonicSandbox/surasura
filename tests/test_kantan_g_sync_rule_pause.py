"""Kantan-G (Sonic 2026-11-19: "a pause stops all a circle runs by itself"): Anki's circle paused holds the pending
AnkiWeb sync a re-order left (S3) — the re-order host's and a window's close alike: it stays pending, looked at again
later, and goes once the circle is resumed (or Anki's own close carries it, S2). The sync before a write (S1) is the
write's own and is never held: a position written over a review made on the phone would lose that review.

What a wrong answer would cost: the learner pauses Anki to keep AnkiWeb quiet and Surasura syncs it anyway; or the
pending sync is dropped, so the phone never gets the new order until Anki is closed.

Anki is a stand-in: `anki_connect.probe` / `sync` record their calls.
"""
import time

from app import anki_connect, anki_sync_rule


def _pending(monkeypatch):
    calls = []
    monkeypatch.setattr(anki_sync_rule, "due_at", lambda settings, state=None: time.time() - 1)
    monkeypatch.setattr(anki_connect, "probe", lambda url, timeout=3: calls.append("probe") or {"ok": False})
    return calls


def test_anki_paused_keeps_a_due_sync_pending_and_asks_anki_nothing(monkeypatch):
    calls = _pending(monkeypatch)
    answer, again = anki_sync_rule.sync_if_due("http://127.0.0.1:8765", {"paused": ["anki"]})
    assert answer is None and again is not None and again > time.time(), "looked at again later"
    assert calls == []


def test_anki_paused_at_a_windows_close_sends_nothing_either(monkeypatch):
    calls = _pending(monkeypatch)
    assert anki_sync_rule.sync_if_due("http://127.0.0.1:8765", {"paused": ["anki"]}, force=True) == (None, None)
    assert calls == []


def test_another_circles_pause_or_none_lets_the_due_sync_go(monkeypatch):
    calls = _pending(monkeypatch)
    monkeypatch.setattr(anki_sync_rule, "closed_seen", lambda now=None: None)
    monkeypatch.setattr(anki_sync_rule, "_update", lambda **values: None)
    for settings in ({"paused": ["junban", "miner"]}, {}, {"paused": "anki"}):     # (a hand-edited text: nothing)
        assert anki_sync_rule.sync_if_due("http://127.0.0.1:8765", settings)[0] == "anki-closed"
    assert calls == ["probe"] * 3
