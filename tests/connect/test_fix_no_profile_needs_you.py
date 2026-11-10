"""Connect's Anki gate with no recorded Anki profile (runner `Steps.blocked`, adversary P2.4-A #9; laptop round 5 #22):
the gate never stops for it itself — the session's check (`anki_session.waiting`) is the one rule: the first profile
Anki names while Connect is on is recorded as Connect's, and with none named nothing is written (a wait, never *Needs
you*: tests/connect/test_lf_mining.py). With a profile recorded, the gate goes on to the session's own check too.

What a wrong answer would cost: Connect never mining after setup (setup's page records no profile, round 5 #22), or
making cards in whichever profile happens to be open when Anki doesn't say which.
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


def test_no_recorded_profile_goes_to_the_sessions_check_which_holds_the_rule(monkeypatch):
    # why: the profile rule lives in the session's check alone (it records the open profile, or waits): the gate
    # neither raises *Needs you* nor skips that check
    calls = _gate(monkeypatch, None)
    steps = runner.Steps({"connect_enabled": True})
    assert steps.blocked("ja") is None
    assert len(calls) == 1


def test_a_recorded_profile_lets_the_gate_pass_to_the_session_check(monkeypatch):
    # why: the same setup with a profile recorded is the normal path: the session says go (None), no Needs
    calls = _gate(monkeypatch, "日本語")
    steps = runner.Steps({"connect_enabled": True})
    assert steps.blocked("ja") is None
    assert len(calls) == 1
