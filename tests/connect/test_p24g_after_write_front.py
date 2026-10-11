"""Connect's Steps.after_write tells the session's sync clock that a write changed tomorrow's cards (front=True):
new cards made for a 上層部 or 気配 card are a change Anki's sync is owed for (S3). Mutant P2.4-E13 passes False
instead, so the clock never starts for a batch that made cards.

What a wrong answer would cost: Connect makes new cards and Anki's next sync is never scheduled, so the new cards
stay on this computer and the phone never gets them; the mutant does this silently, with no error.
"""
from app.connect import runner


def test_new_cards_made_mark_tomorrows_cards_changed_for_the_sync_clock(monkeypatch):
    from app.connect import anki_session

    calls = []
    # Recorded instead of starting the clock: the clock itself is tested elsewhere.
    monkeypatch.setattr(anki_session, "after_write", lambda settings, front: calls.append((settings, front)))

    s = runner.Steps({"connect_enabled": True})
    s.after_write("ja")

    # The front flag is True for any batch that wrote new cards, whatever the language.
    assert calls == [(s.loaded, True)]
