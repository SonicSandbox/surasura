"""A job that has reached Anki Miner finishes even when it is back at `picking` and its item left the top 20 (P2.4 gap
D06; runner `_job`, `droppable`; E18).

Once a batch has reached Anki Miner, its item's notes may already be in Anki. A job killed during a re-pick, set back to
`picking`, must still finish: its item leaving the top 20 is no reason to drop it, because the drop rule is for jobs
that have not started mining yet.

What a wrong answer would cost: a job whose batch already went to Anki Miner is dropped as "left the top 20", so its
words are never finished and the cards already made stay half-finished in the ledger.

Mutant P2.4-D06: `droppable` ignores `_started`. Against `FakeSteps` (real words); never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps, Killed


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_a_started_job_set_back_to_picking_finishes_even_after_its_item_leaves_the_top_20(tmp_path, ledger):
    # first run: Connect is killed in the middle of the job's one batch, so the batch has reached Anki Miner
    killed = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "kill": "mid-batch:1"})
    with pytest.raises(Killed):
        runner.run({}, ["ja"], steps=killed, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.jobs("ja")[0]
    last = ledger.batches(job["id"])[-1]
    # precondition: the batch really reached Anki Miner, or the test proves nothing
    assert last["state"] == "running", "the kill must leave the batch running (a job that has started mining)"

    # the job is back at `picking` (killed during a re-pick), so the pre-mining drop rule applies to its step
    ledger.set_state(job["id"], "picking")

    # the next run: item 1 has left the top 20 (only item 2 is in the line) — a started job still finishes
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [2]}})
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job["id"])["state"] == "done", "a job that has started mining must finish"
    # why: the drop is reported in the run's summary too, so both places must agree the job was not dropped
    assert 1 not in summary["languages"]["ja"]["dropped"], summary
