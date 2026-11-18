"""Mado-PZ (2026-11-18, a tester's ask: Connect's mining taxes the PC): Anki Miner's circle paused at the bar stops
Connect too — its loop at the next step boundary (`Steps.paused`, read again at every look and before each job, as
D29's switch is), `kick` starts nothing, and the `connect` verb answers `skipped`. Resumed, Connect runs as before. The
jobs it had are kept in the ledger: the next start mines them (nothing is lost).

What a wrong answer would cost: Connect going on making cards — the PC working hard — after the learner paused it to
use the PC for something else; or Connect never coming back after the click that resumes it.

The test's own root and settings.json; no Anki, no Anki Miner; `kick`'s process start replaced.
"""
import subprocess

import pytest

from app.connect import kick, runner
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@pytest.mark.parametrize("paused, stop", [
    (["miner"], runner.PAUSED),
    (["junban", "arrivals"], None),               # another circle's pause: Connect goes on
    ([], None),
    ("miner", None),                              # a hand-edited value that isn't a list: nothing paused
])
def test_connects_loop_stops_at_its_next_boundary_only_while_anki_miner_is_paused(paused, stop):
    h.write_settings(connect_enabled=True, paused=paused)
    steps = runner.Steps({"connect_enabled": True})
    assert runner._stop(steps) == stop


def test_a_pause_pressed_mid_run_stops_it_at_the_next_look_and_a_resume_lets_the_next_start_run():
    h.write_settings(connect_enabled=True)
    steps = runner.Steps({"connect_enabled": True})
    assert runner._stop(steps) is None
    h.write_settings(connect_enabled=True, paused=["miner"])
    assert runner._stop(steps) == runner.PAUSED, "read again at each boundary, never kept from the run's start"
    h.write_settings(connect_enabled=True, paused=[])
    assert runner._stop(steps) is None


def test_a_stand_in_steps_without_the_pause_look_goes_on():
    class Steps:
        def update_staged(self):
            return False

        def enabled(self):
            return True
    assert runner._stop(Steps()) is None


@pytest.fixture
def starts(monkeypatch):
    """`kick` allowed to start under the test root, its process start recorded instead."""
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a) or "a process")
    monkeypatch.setattr(kick, "running", lambda: False)
    return started


def test_with_anki_miner_paused_kick_starts_nothing_and_resumed_it_starts(starts):
    assert kick.kick({"connect_enabled": True, "paused": ["miner"]}) is None
    assert starts == []
    assert kick.kick({"connect_enabled": True, "paused": ("surasura",)}) == "a process", "another circle's pause"
    assert kick.kick({"connect_enabled": True, "paused": []}) == "a process" and len(starts) == 2


def test_with_anki_miner_paused_a_running_connect_is_not_woken(monkeypatch):
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    monkeypatch.setattr(kick, "running", lambda: True)
    woken = []
    monkeypatch.setattr(kick, "wake", lambda videos=False: woken.append(videos))
    assert kick.kick({"connect_enabled": True, "paused": ["miner"]}) is None and woken == []
    kick.kick({"connect_enabled": True})
    assert woken == [False]


def test_the_connect_verb_answers_skipped_while_anki_miner_is_paused():
    h.write_settings(connect_enabled=True, paused=["miner"])
    code, line = h.call("connect")
    assert code == 0 and line["skipped"] == "paused", line
    h.write_settings(connect_enabled=True, paused=["miner"], logic={"automation": False})
    code, line = h.call("connect")
    assert line["skipped"] == "automation off", "the master switch is said first"
