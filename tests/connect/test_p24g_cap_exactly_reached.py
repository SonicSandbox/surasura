"""The cap, at the edge (mutant P2.4-D14): a shelf that frees cards only down to exactly the cap still leaves the job
waiting. The cap is a full pile, so 300 waiting against a cap of 300 is over it; only a count strictly under the cap
lets a batch through. The mutant (`count <= cap` in the shelf's re-check) lets the batch mine at exactly 300.

What a wrong answer would cost: a batch mined at exactly the cap, so the pile grows past the learner's limit, the
very backlog the cap exists to stop.

Against `FakeSteps` (real words, item 1 = 3 words); the 2-minute look is the injected `sleep`. Never a live Anki.
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
    """Run with `plan`; each look's sleep is recorded and, when `clear` names plan keys, clears them (Anki freed up)."""
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        for key in clear or ():
            steps.plan.pop(key, None)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep, looks=looks)
    return steps, summary, slept


def test_a_shelf_freeing_down_to_exactly_the_cap_still_leaves_the_job_waiting(tmp_path, ledger):
    # why: 301 waiting is over the cap of 300; the shelf frees one, which lands on exactly 300 - a full pile, not
    # room. Only a count strictly under the cap may let the batch mine, so the job must keep waiting
    steps, _summary, _slept = _run(tmp_path, ledger, {"cap": 300, "waiting": 301, "shelf_frees": 1}, looks=1)
    assert [e for e in steps.log if e[0] == "shelve"], "the shelf was asked"
    assert not any(e[0] == "mine" for e in steps.log), "at exactly the cap nothing is mined"
    assert ledger.jobs("ja")[0]["state"] == "waiting"
