"""Haya-LD (3.0.18): on a PC that runs one heavy job at a time (`power.gentle`), Connect's next step that touches
Anki waits while a Generate runs (its `results` lock) — GENERATE_FIRST — so the Generate goes in at Connect's next
step boundary; a strong PC mines beside it as before, and an episode you asked for (*Mine now*) goes on (a press is
the yes, as on battery).

What a wrong answer would cost: on a laptop (a 3.0.16 problem report) Connect's Anki Miner and ffmpeg ran beside a Generate
and Anki crawled; held the other way, a *Mine now* that does nothing while a Generate runs, or a desktop slowed for
nothing. Against `FakeSteps` (real words) and the real ledger in a temp folder; the machine, the lock and Anki are
stand-ins. Never a live Anki.
"""
import pytest

from app import locks
from app.connect import anki_session, feed, power, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


@pytest.fixture
def anki_open(monkeypatch):
    """Anki reachable and idle (the session's own look answers nothing), mains power: only the rule under test speaks."""
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    monkeypatch.setattr(anki_session, "waiting", lambda url, loaded: None)


@pytest.mark.parametrize("gentle, generating, expect", [
    ((True, "8 logical CPUs"), True, runner.GENERATE_FIRST),
    ((True, "8 logical CPUs"), False, None),            # no Generate: nothing to wait for
    ((False, None), True, None),                        # a strong PC mines beside a Generate, as before
])
def test_the_next_step_waits_for_a_running_generate_only_on_a_gentle_pc(monkeypatch, anki_open, gentle, generating,
                                                                         expect):
    monkeypatch.setattr(power, "gentle", lambda *a, **k: gentle)
    monkeypatch.setattr(locks, "in_use", lambda name, *a, **k: generating and name == "results")
    monkeypatch.setattr(locks, "read_holder", lambda name: {"verb": "Generate", "pid": 1})
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:8765"})
    assert steps.blocked("ja") == expect


def test_battery_still_comes_first_and_a_failing_reading_never_holds(monkeypatch, anki_open):
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: True)
    monkeypatch.setattr(power, "gentle", lambda *a, **k: (True, "on battery"))
    monkeypatch.setattr(locks, "in_use", lambda name, *a, **k: True)
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:8765"})
    assert steps.blocked("ja") == runner.ON_BATTERY

    def broken(*a, **k):
        raise OSError("no reading")
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    monkeypatch.setattr(power, "gentle", broken)
    assert steps.blocked("ja") is None


def _steps(tmp_path, **plan):
    return FakeSteps(str(tmp_path), dict({"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}, **plan))


def test_every_episode_waits_in_its_place_and_its_row_is_a_plain_wait(tmp_path, ledger):
    steps = _steps(tmp_path, blocked=runner.GENERATE_FIRST)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
    assert not [e for e in steps.log if e[0] == "mine"]
    assert summary["languages"]["ja"]["waiting"] == {1: runner.GENERATE_FIRST, 2: runner.GENERATE_FIRST}
    assert runner.holds_every(runner.GENERATE_FIRST), "the pass ends there: the list's order is kept"
    assert not runner.anki_needs_you(runner.GENERATE_FIRST), "never amber: it clears by itself"
    rec = {"languages": {"ja": {"jobs": [{"item": 1, "job": 1, "state": "waiting", "reason": runner.GENERATE_FIRST}]}}}
    item = feed.build(rec, "ja").items[1]
    assert (item.kind, item.tip) == (feed.WAITING, runner.GENERATE_FIRST)


def test_an_episode_you_asked_for_goes_on_while_the_rest_wait_for_the_generate(tmp_path, ledger):
    steps = _steps(tmp_path, blocked=runner.GENERATE_FIRST)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
    with ledger.transaction():
        ledger.ask("ja", 1, "2026-11-20T21:45:00.000000Z")          # *Mine now* on episode 1
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
    states = {j["item_id"]: (j["state"], j.get("reason")) for j in ledger.jobs("ja")}
    assert states[1][0] == "done", states
    assert states[2] == ("waiting", runner.GENERATE_FIRST), states
    assert all(e[1] == 1 for e in steps.log if e[0] == "mine")


def test_the_run_says_how_this_pc_runs_its_heavy_jobs(tmp_path, ledger, monkeypatch, caplog):
    monkeypatch.setattr(power, "gentle", lambda *a, **k: (True, "8 logical CPUs"))
    with caplog.at_level("INFO", logger="surasura-cli"):
        runner.run({}, ["ja"], steps=_steps(tmp_path), ledger=ledger, sleep=lambda _s: None, looks=1)
    text = caplog.text
    assert "a run begins (ja): one heavy job at a time on this computer (8 logical CPUs)" in text
    assert "the run ends after" in text
    assert "Connect: job" in text and "batch" in text and "made" in text


@pytest.mark.parametrize("verb, expect", [("Generate", runner.GENERATE_FIRST), ("Generate (waiting)", runner.GENERATE_FIRST),
                                          ("Sorting your library again", None), ("Putting your library back", None),
                                          (None, None)])
def test_only_a_generates_hold_of_results_makes_connect_wait(monkeypatch, anki_open, verb, expect):
    # why (review): a sort or a put-back holds `results` too, briefly — "Waiting for Generate" would be untrue
    monkeypatch.setattr(power, "gentle", lambda *a, **k: (True, "8 logical CPUs"))
    monkeypatch.setattr(locks, "in_use", lambda name, *a, **k: name == "results")
    monkeypatch.setattr(locks, "read_holder", lambda name: {"verb": verb, "pid": 1} if verb else None)
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:8765"})
    assert steps.blocked("ja") == expect
