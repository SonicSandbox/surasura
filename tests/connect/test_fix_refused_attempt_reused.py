"""Attempt numbers (P2.4 review fixes, R16; runner 455–460): a call Anki Miner refused never ran, so the next look
reuses its attempt number instead of spending a new one. The batch history keeps one row per call that really ran,
and a retry that succeeds is attempt 1 too.

What a wrong answer would cost: a refused call that spends a number leaves a gap and extra rows in the batch history
(the ledger is what Connect shows as "what ran"), so a reader would count calls that never reached Anki Miner.

Against `FakeSteps` (real words); the 2-minute look is the injected `sleep`. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=5, clear=None):
    """Run with `plan`; each 2-minute look's sleep is recorded and, when `clear` names plan keys, clears them."""
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))

    def sleep(seconds):
        for key in clear or ():
            steps.plan.pop(key, None)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep, looks=looks)
    return steps


def test_a_refused_call_reuses_its_attempt_number_on_every_look(tmp_path, ledger):
    # Anki Miner stays open for all three looks: each look's call is refused before it runs
    words = {"words": {1: [("上層部", "じょうそうぶ")]}}
    steps = _run(tmp_path, ledger, dict({"miner_busy": True}, **words), looks=3)
    job = ledger.jobs("ja")[0]
    assert [(b["attempt"], b["state"]) for b in ledger.batches(job["id"])] == [(1, "refused")]
    attempts = [e[2] for e in steps.log if e[0] == "mine"]
    assert len(attempts) >= 2 and set(attempts) == {1}, "every look asked with number 1: none was spent"

    # Anki Miner closes while the job sleeps: the next call runs as attempt 1, the refused row stays the only earlier one
    _run(tmp_path, ledger, dict({"miner_busy": True}, **words), clear=["miner_busy"])
    batches = ledger.batches(job["id"])
    assert [b["attempt"] for b in batches] == [1], "a retry after a refusal keeps number 1, never 2"
    assert batches[0]["state"] != "refused"
