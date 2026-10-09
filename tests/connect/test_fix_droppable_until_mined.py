"""A refused batch leaves the job droppable (P2.4 review fix R1; runner `_wait`, 300–312; `_started`, 294–297).

When Anki Miner refuses a batch (its window is open), nothing reached Anki: the job waits with no step to resume at
(`resume` None), so the next run picks it again from the list as it is then. If the item has left the top 20 by then,
the job is `dropped`, and Anki Miner is never asked for it.

What a wrong answer would cost: a job Anki Miner refused, and that has since left the top 20, being mined anyway, so
a card lands for a word the list no longer wants; or the job resuming at mining, which skips the top-20 check.

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


def _run(tmp_path, ledger, plan, looks=5):
    """Run with `plan` over the fake steps; the injected sleep records each 2-minute look and does nothing else."""
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))
    slept = []

    def sleep(seconds):
        slept.append(seconds)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep, looks=looks)
    return steps, summary, slept


def test_a_refused_batch_leaves_the_job_droppable_until_it_is_mined(tmp_path, ledger):
    # first run: Anki Miner's window is open, so its batch is refused and the job waits with no step to resume at
    # (nothing reached Anki, so it is still droppable)
    _run(tmp_path, ledger, {"miner_busy": True}, looks=1)
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["resume"]) == ("waiting", None), "a refused batch keeps no resume step"

    # the item leaves the top 20 while the job waits, and Anki Miner is free again: the job is dropped at the
    # top-20 check and never mined (no "mine" step is logged)
    steps, summary, _slept = _run(tmp_path, ledger, {"line": {"ja": [2]}, "queue": {"ja": []}}, looks=1)
    assert summary["languages"]["ja"]["dropped"] == [1]
    assert ledger.jobs("ja")[0]["state"] == "dropped"
    assert not any(e[0] == "mine" for e in steps.log), "Anki Miner is never asked for a dropped item"
