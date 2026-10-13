"""Connect's loop with a tool missing (P2.4 row 2.4.8; the Q4-2 answer): with Backfill absent the job's `skipped` column
names the step `filling` and the job still ends `done`; with Junban absent it names `ordering` and still ends `done`;
with Anki Miner absent the job ends `skipped` (reason "Anki Miner isn't installed") and nothing is mined. The loop goes
on to the next job in every case.

What a wrong answer would cost: a job reported `done` with its backfill silently left out (the user never learns why
the example sentences and patterns are missing); a skipped step with no name, so Connect can't say what to fix; a
missing Anki Miner that still writes cards, or that stops the queue for the jobs behind it. Real Japanese words, synthetic
titles, temp folders only; never a live Anki.
"""
import json

import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    return steps, summary


def test_missing_backfill_names_filling_and_the_job_still_ends_done(tmp_path, ledger):
    # Backfill absent: its step is skipped and named; Junban still runs (the 'order' step is in the log) and the job is done
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}, "absent": ["backfill"]})
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("done", None), "the job is done, not skipped or failed"
    assert set(json.loads(job["skipped"])) == {"filling"}, "the skipped step is named: filling"
    assert ("order", 1) in steps.log, "Junban's step still runs after a missing Backfill"
    assert summary["languages"]["ja"]["done"] == [1]


def test_missing_junban_names_ordering_and_the_job_still_ends_done(tmp_path, ledger):
    # Junban absent: the ordering step is skipped and named; the words were made and filled before it, so the job is done
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}, "absent": ["junban"]})
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("done", None)
    assert set(json.loads(job["skipped"])) == {"ordering"}, "the skipped step is named: ordering"
    kinds = [e[0] for e in steps.log]
    assert kinds.index("fill") < kinds.index("order"), "Backfill ran before Junban was found missing"
    assert summary["languages"]["ja"]["done"] == [1]


def test_missing_anki_miner_skips_the_job_and_the_loop_goes_on(tmp_path, ledger):
    # Anki Miner absent: nothing is mined into Anki, the job is skipped with its reason, and job 2 is still reached
    steps, summary = _run(tmp_path, ledger,
                          {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "absent": ["anki-miner"]})
    by_item = {j["item_id"]: j for j in ledger.jobs("ja")}
    assert set(by_item) == {1, 2}, "the job behind the skipped one is still picked up"
    for item in (1, 2):
        assert (by_item[item]["state"], by_item[item]["reason"]) == ("skipped", "Anki Miner isn't installed")
    assert steps.anki.words() == [], "nothing is mined into Anki"
    assert summary["languages"]["ja"]["skipped"] == [1, 2]
