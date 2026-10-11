"""Steps.settle sends the session's pending sync when a session is on, and does nothing when none is (P2.4-E06).

Rule: with Connect's Anki session on, `Steps.settle` hands the session the run's URL and loaded settings so it can
send the pending sync; with no session (Connect's preview off, or the test suites' SURASURA_NO_ANKI_SYNC), it does
nothing and raises nothing. Mutant P2.4-E06 inverts the test on `session is not None`: a live session is never told,
and with no session it calls `None.settle` and crashes the job.

What a wrong answer would cost: the studied-card sync is never sent, so Connect reads stale Anki state and works from
cards it already changed; or, with Connect off, every Steps call crashes with AttributeError.
"""
from app.cli import verbs
from app.connect import runner


class _RecordingSession:
    """A stand-in for `app/connect/anki_session`: records what `settle` was called with."""

    def __init__(self):
        self.calls = []

    def settle(self, url, loaded):
        self.calls.append((url, loaded))


def test_settle_sends_the_sync_to_a_live_session_with_the_run_url_and_settings(monkeypatch):
    # With Connect on there is a session, so the run's pending sync must reach it with this run's own URL and settings.
    fake = _RecordingSession()
    monkeypatch.setattr(verbs, "_session", lambda loaded: fake)
    s = runner.Steps({"connect_enabled": True})
    s.settle()
    assert fake.calls == [(s.url, s.loaded)]


def test_settle_does_nothing_and_raises_nothing_when_there_is_no_session(monkeypatch):
    # With Connect off there is no session to settle; the step must return quietly rather than call None.settle.
    monkeypatch.setattr(verbs, "_session", lambda loaded: None)
    s = runner.Steps({"connect_enabled": True})
    assert s.settle() is None
