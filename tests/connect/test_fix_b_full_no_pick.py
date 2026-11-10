"""J3 (P2.4 final adversary): a job waiting at the cap is not picked again at every look.

Once this run's shelf has had its try for the language, a job that finds Connect's waiting cards at the cap waits with
its count ("Your 5 cards are waiting ...") on every look, and the look never picks: no pick, no write, no batch. The
gate is the cap itself, so a job under the cap still mines after the shelf's try.

What a wrong answer would cost: every 2-minute look re-picking the same words from the top 20 (a pick reads the
library and writes to Anki's notes each time), or a job under the cap being held back by a stale shelf try.

Against `FakeSteps` (real words, item 1 = 3 words); the look's sleep is injected. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class TriedShelfSteps(FakeSteps):
    """The shelf has already had its one try this run, for every language (the state `_full` reads)."""

    def shelf_tried(self, lang):
        return True


def _run(tmp_path, ledger, plan, looks):
    """Run one job with `plan`; each look's sleep is recorded so a test can count the looks."""
    steps = TriedShelfSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))
    slept = []
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=slept.append, looks=looks)
    return steps, summary, slept


def test_a_job_waiting_at_the_cap_after_the_shelf_try_is_not_picked_on_any_look(tmp_path, ledger):
    # why: the cap is the gate; a pick at a look over the cap would write notes past the learner's cap
    steps, summary, slept = _run(tmp_path, ledger, {"cap": 5, "waiting": 5}, looks=3)
    assert not any(e[0] == "pick" for e in steps.log), "over the cap nothing is picked, on any look"
    job = ledger.jobs("ja")[0]
    assert job["state"] == "waiting", "the job waits; it is not dropped or done"
    assert job["reason"].startswith("Your 5 cards are waiting"), job["reason"]
    assert slept and set(slept) == {runner.LOOK_EVERY_S}, "Connect keeps looking every 2 minutes"


def test_a_job_under_the_cap_still_picks_after_the_shelf_try(tmp_path, ledger):
    # why: the shelf's try alone must not hold a job back; one card under the cap lets the batch go
    steps, summary, slept = _run(tmp_path, ledger, {"cap": 5, "waiting": 4}, looks=1)
    assert any(e[0] == "pick" for e in steps.log), "under the cap the job is picked"
    assert ledger.jobs("ja")[0]["state"] == "done"
