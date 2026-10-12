"""Fix B (P2.4 Part B final review, item J4): a job that is already waiting for the same reason, resuming at the same
step, is not written again. The runner looks every 2 minutes while Connect's cap holds a job, so an unchanged wait
written each time would cost a database write per look and churn the job's updated time for nothing. A wait with a
different reason is still written, so the job's shown reason never goes stale.

What a wrong answer would cost: a write on every look (a busy ledger for a job that is just waiting), or a changed
reason that never reaches the ledger (the learner sees the old "Your 300 cards are waiting" after the count moved).

Against a real Ledger in a temp folder; the ledger's `set_state` is wrapped only to count writes (the ledger is not
the code under test). Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_the_same_wait_again_writes_nothing_and_a_different_reason_is_written(ledger, monkeypatch):
    # why: a look every 2 minutes must not rewrite an unchanged wait, but a new count in the reason must reach the ledger
    job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
    job = ledger.job_by_id(job_id)
    writes = []
    real_set_state = ledger.set_state

    def counting_set_state(*args, **kwargs):
        writes.append(args)
        return real_set_state(*args, **kwargs)
    monkeypatch.setattr(ledger, "set_state", counting_set_state)

    out = {"waiting": {}}
    first = runner.Wait("Your 300 cards are waiting in Anki", look=True, resume=None)
    runner._wait(ledger, job, first, out)
    assert len(writes) == 1, "the first wait is written once (the sanity check that the write path runs)"

    runner._wait(ledger, job, first, out)
    assert len(writes) == 1, "the same reason at the same step writes nothing on the next look"
    assert ledger.job_by_id(job_id)["state"] == "waiting"

    changed = runner.Wait("Your 301 cards are waiting in Anki", look=True, resume=None)
    runner._wait(ledger, job, changed, out)
    assert len(writes) == 2, "a different reason is written, so the shown count never goes stale"
    stored = ledger.job_by_id(job_id)
    assert (stored["state"], stored["reason"]) == ("waiting", "Your 301 cards are waiting in Anki")
