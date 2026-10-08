"""A job skipped because Anki Miner wasn't installed comes back once it is (P2.4 R19; the Q4-2 answer and intent keeper
P2.4-A #11): run 1 with Anki Miner absent leaves the job `skipped` and mines nothing; run 2, with Anki Miner installed
and the same item still in the line, reopens that job and mines it to `done` with its cards.

What a wrong answer would cost: a word the user queued and Connect skipped staying skipped for good, with no cards
ever made after the install; or the reopen running for a job that was never skipped for want of Anki Miner.
Real Japanese words, temp folders only; never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    return steps, summary


def test_a_job_skipped_for_a_missing_anki_miner_is_mined_once_it_is_installed(tmp_path, ledger):
    # run 1: Anki Miner absent -> the job is skipped with its reason, and nothing is written to Anki
    _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}, "absent": ["anki-miner"]})
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("skipped", "Anki Miner isn't installed")

    # run 2: installed, item 1 still in the line. Its inbox event was read in run 1, so the inbox queues nothing again
    # (an empty "queue"): only the reopen can bring the skipped job back. A fresh FakeSteps has no record of the first.
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": []}})
    jobs = ledger.jobs("ja")
    assert len(jobs) == 1, "the skipped job is reopened, not joined by a second job for the same item"
    assert (jobs[0]["state"], jobs[0]["reason"]) == ("done", None), "the job is mined to done once installed"
    assert sorted(steps.anki.words()) == sorted(w for w, _ in WORDS[1]), "its cards are made in run 2"
    assert summary["languages"]["ja"]["done"] == [1]
