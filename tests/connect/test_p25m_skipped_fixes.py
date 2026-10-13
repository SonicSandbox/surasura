"""A job that ends `skipped` (Anki Miner absent) fixes its item's earlier needs, except the step it skipped. The
skipped job's cards were never made, but its item's older troubles are settled by the job's end, the same way a
`done` job's are (only the step the job ended without keeps its need open: here, the mining step's own need stays).

What a wrong answer would cost: a skipped job leaves its item's stale failure open forever on an item the learner
has already been told is handled, so the list keeps asking about a problem the run no longer has.

Against `FakeSteps` with real words; never a live Anki, no sleeps.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("気配", "けはい")]
OLD_ERROR = "上層部: Connect stopped on an error while making an episode's cards (ValueError): old fault"


def test_a_skipped_job_fixes_its_item_older_error_as_a_done_job_does(tmp_path):
    # Anki Miner absent: the pick step ends the job skipped, with its cards never made
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "absent": ["anki-miner"]}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        # an older error of the same item, raised before the run: the skipped job's end must fix it
        assert ledger.need("ja", "error", OLD_ERROR, item_id=1), "the old error must be recorded before the run"
        # the step the job skips keeps its own need open (the one exception to the fix)
        assert ledger.need("ja", "mining", runner.MINER_ABSENT, item_id=1)
        before = [n["say"] for n in ledger.needs("ja", listed=False)]
        assert OLD_ERROR in before, "setup check: the old error is open before the run, or the test proves nothing"
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        jobs = ledger.jobs("ja")
        job = ledger.job_by_id(jobs[0]["id"])
        open_says = [n["say"] for n in ledger.needs("ja", listed=False)]

    # why: the rule only means something if the job really ended skipped, not done
    assert job["state"] == "skipped", "the job must end skipped (Anki Miner absent) or this proves nothing"
    assert OLD_ERROR not in open_says, "a skipped job's end fixes its item's older error"
    assert runner.MINER_ABSENT in open_says, "the step the job skipped keeps its need open"
