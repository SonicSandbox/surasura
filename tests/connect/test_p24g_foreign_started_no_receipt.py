"""A job that started mining in a library set up again finishes, but writes no receipt into the new library (P2.4 gap
D07, runner `_record_made` / `record = not foreign`; mutant P2.4-D07).

A job remembers the store it was queued for. Once mining has started, the job is no longer droppable, so it finishes.
But its receipt (the cards it made, the mined time) belongs to the old library: the store set up again must not get it.
So the run writes nothing into the new store, and the job is not dropped either.

What a wrong answer would cost: the old library's receipt lands in the new library, so the new library's records claim
cards it never made, and a later Undo or a Connect look at the library would act on the wrong cards.

Against `FakeSteps` (real words); the first run is killed mid-batch, as in the kill tests. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps, Killed


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_a_started_job_of_a_store_set_up_again_finishes_and_writes_no_receipt(tmp_path, ledger):
    # first run: queued for store "old", killed mid-batch, so the job has started mining (no longer droppable)
    killed = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "queued_store": "old",
                                       "store_id": "old", "kill": "mid-batch:1"})
    with pytest.raises(Killed):
        runner.run({}, ["ja"], steps=killed, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.jobs("ja")[0]
    # precondition: the job really started mining, or the test proves nothing
    assert ledger.batches(job["id"])[-1]["state"] == "running", "the kill must leave the job mid-mining"

    # second run: the library is set up again (store "new"); the job is still on the line
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "store_id": "new"})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)

    # the job finishes (E18: once started, it is not dropped) ...
    assert ledger.job_by_id(job["id"])["state"] == "done", "a started job finishes even though its library changed"
    # ... but its receipt is the old library's: the new library gets no record from it
    assert steps.records == [], "a job from a store set up again must write no receipt into the new store"
