"""Connect's Anki gate with no recorded Anki profile (runner `Steps.blocked`, adversary P2.4-A #9): with Anki open
and no profile set up, the session's "another profile open" guard can't hold, so the job is *Needs you* (kind
"no-profile") and nothing is written. With a profile recorded, the gate goes on to the session's own check.

What a wrong answer would cost: Connect making cards in whichever profile happens to be open, behind the user's back,
when it doesn't know which profile is theirs.
"""
from app.connect import anki_session, power, runner, setup


def _gate(monkeypatch, profile):
    """Connect on, off battery, Anki open (the session's check is recorded, never reached for real)."""
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    monkeypatch.setattr(setup, "anki_profile", lambda: profile)
    calls = []

    def waiting(url, settings):
        calls.append(url)
        return None
    monkeypatch.setattr(anki_session, "waiting", waiting)
    return calls


def test_no_recorded_profile_with_anki_open_is_needs_you_and_nothing_is_written(monkeypatch):
    # why: without a profile the "another profile open" guard can't hold, so the session's check must not run
    calls = _gate(monkeypatch, None)
    steps = runner.Steps({"connect_enabled": True})
    try:
        steps.blocked("ja")
    except runner.Needs as needs:
        assert needs.kind == "no-profile"
    else:
        raise AssertionError("no recorded profile must raise Needs, not let Connect write")
    assert calls == [], "the session's check (and so any write) is never reached without a profile"


def test_a_recorded_profile_lets_the_gate_pass_to_the_session_check(monkeypatch):
    # why: the same setup with a profile recorded is the normal path: the session says go (None), no Needs
    calls = _gate(monkeypatch, "日本語")
    steps = runner.Steps({"connect_enabled": True})
    assert steps.blocked("ja") is None
    assert len(calls) == 1
