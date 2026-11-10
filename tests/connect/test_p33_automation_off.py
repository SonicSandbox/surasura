"""P3.3 row 3.3.6 (C1): D29's switch (`logic.automation`) off stops Connect too — its loop at the next step boundary
(`Steps.enabled`, read again at every look and before each job), `kick` starts nothing, and the `connect` verb
answers `skipped` with a plain line. With the automation on, Connect's own switch (`connect_enabled`) decides as
before: off, nothing; on, Connect runs.

What a wrong answer would cost: Connect making cards and re-ordering Anki after you switched the automation off — the
one switch that says "nothing automatic" (D29).

The test's own root and settings.json; no Anki, no Anki Miner; `kick`'s process start replaced.
"""
import subprocess

import pytest

from app.connect import kick, runner
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@pytest.mark.parametrize("connect,logic,on", [
    (True, {"automation": False}, False),
    (True, {"automation": True}, True),
    (True, {}, True),                             # absent: on (the default)
    (False, {"automation": True}, False),         # Connect's own switch off: as today
])
def test_connects_loop_runs_only_with_its_switch_and_the_automation_on(connect, logic, on):
    h.write_settings(connect_enabled=connect, logic=logic)
    steps = runner.Steps({"connect_enabled": True})
    assert steps.enabled() is on
    assert runner._stop(steps) == (None if on else runner.SWITCHED_OFF), "the run stops at the next boundary"


def test_the_automation_switched_off_mid_run_stops_it_at_the_next_look(monkeypatch):
    h.write_settings(connect_enabled=True)
    steps = runner.Steps({"connect_enabled": True})
    assert runner._stop(steps) is None
    h.write_settings(connect_enabled=True, logic={"automation": False})
    assert runner._stop(steps) == runner.SWITCHED_OFF, "read again, never kept from the run's start"


@pytest.fixture
def starts(monkeypatch):
    """`kick` allowed to start under the test root, its process start recorded instead."""
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a) or "a process")
    monkeypatch.setattr(kick, "running", lambda: False)
    return started


def test_with_the_automation_off_kick_starts_nothing(starts):
    assert kick.kick({"connect_enabled": True, "logic": {"automation": False}}) is None
    assert starts == []
    assert kick.kick({"connect_enabled": True}) == "a process" and len(starts) == 1, "on: as today"
    assert kick.kick({"connect_enabled": False}) is None and len(starts) == 1


def test_the_connect_verb_answers_skipped_with_the_automation_off():
    h.write_settings(connect_enabled=True, logic={"automation": False})
    code, line = h.call("connect")
    assert code == 0 and line["skipped"] == "automation off", line
    h.write_settings(connect_enabled=False, logic={"automation": False})
    code, line = h.call("connect")
    assert code == 0 and line["skipped"] == "connect preview off", "Connect's own switch is named first"
