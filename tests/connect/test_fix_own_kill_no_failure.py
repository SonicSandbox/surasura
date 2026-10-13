"""Connect's own kill mid-batch is no Anki Miner failure (P2.4 review fix R14; runner `_mine`, the batch left `running`).

A batch left `running` after Connect was stopped mid-batch is a batch in doubt: its notes are found by the job's tag and
the batch is ended as `uncertain`. Connect's own stop is not Anki Miner failing, so the job's `failures` count stays 0
and the next run finishes the job normally.

What a wrong answer would cost: every kill of Connect counted as a failure, so after two kills an episode is *Needs you*
and never mined again, though Anki Miner never crashed.

Against `FakeSteps` (real words); the injected `sleep` is a no-op. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeAnki, FakeSteps, Killed


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_a_kill_mid_batch_leaves_no_failure_and_the_next_run_finishes_the_job(tmp_path, ledger):
    # first run: Connect is killed in the middle of the job's one batch, so the batch is left `running`
    killed = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "kill": "mid-batch:1"})
    with pytest.raises(Killed):
        runner.run({}, ["ja"], steps=killed, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.jobs("ja")[0]
    last = ledger.batches(job["id"])[-1]
    # precondition: the batch really is in doubt, or the test proves nothing
    assert last["state"] == "running", "the kill must leave the batch running (a batch in doubt)"

    # the next run, with no kill: the job finishes and Connect's own kill counted no failure
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job["id"])
    assert job["state"] == "done", job
    assert job["failures"] == 0, "Connect's own kill mid-batch must not count as an Anki Miner failure"
    # why: the same job's notes are still one a word (the tag check ran, nothing mined twice)
    counts = {w: FakeAnki(str(tmp_path / "anki.json")).words().count(w) for w, _r in WORDS[1]}
    assert all(n == 1 for n in counts.values()), counts
