"""A job that ends `done` fixes its item's open needs, except the one that names a step the job ended without (its
`skipped` column). Backfill failing for one episode is the case: the job's cards are made and ordered, but the filling
step was skipped, so the Backfill need stays open for the learner to answer, while an older Anki Miner failure on the
same item is fixed by the job's end. (No Backfill deck at all is the language's need, not the episode's:
`test_alpha6_needs_once.py`.)

What a wrong answer would cost: the learner's open "needs you" line for a Backfill step that never ran disappears
on its own, so the skipped fill is never done and nothing says so; or a stale failure stays open forever on an item
that is already made.

Against `FakeSteps` with real words; never a live Anki, no sleeps.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FILL_FAILED, FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("気配", "けはい")]
MINE_FAILED = "上層部: Anki Miner stopped twice"


def test_a_done_job_fixes_its_older_failure_but_keeps_the_backfill_need_it_skipped(tmp_path):
    # `fill_needs` makes the filling step fail for this episode every time it runs (fake_steps.fill)
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "fill_needs": True}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        # an older failure of the same item, raised before the run: the job's end must fix it
        ledger.need("ja", "mine-failed", MINE_FAILED, item_id=1)
        # Backfill's first try waits for the next start; the second start tries once more and ends the step skipped
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        jobs = ledger.jobs("ja")
        job = ledger.job_by_id(jobs[0]["id"])
        open_says = [n["say"] for n in ledger.needs("ja", listed=False)]

    # why: the rule only means something if the job really ended done with its filling step skipped
    assert job["state"] == "done", "the job must end done (its cards made, the fill skipped) or this proves nothing"
    assert job["skipped"] and "filling" in job["skipped"], "the filling step is recorded as ended without"
    assert MINE_FAILED not in open_says, "the job's end fixes its item's older failure"
    assert FILL_FAILED in open_says, \
        "the need of the step the job ended without stays open for the learner"
