"""A job that fails twice still renames the media of the cards it made (P2.4 Part B review fix; runner `_fail_mining`,
which calls `_name_media_at_end` before it marks the job `failed`): the first try makes a card, the batch crashes, the
retry crashes too. The clip and picture of that card must still be renamed by the line, so the learner's media files
match the cards Anki is left holding. Only the rename is at stake here, not the job: a rename that fails is logged and
the job still ends `failed` (see `_name_media_at_end`).

What a wrong answer would cost: a failed job leaves its made cards with media named by nothing, so the next look at
the deck finds files it cannot match to a line.

Against `FakeSteps` with real words; never a live Anki, no sleeps.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("気配", "けはい")]


def test_a_job_that_fails_twice_still_renames_the_media_of_the_cards_it_made(tmp_path):
    # the first word is made, then the batch crashes; the retry crashes too (crash_always), so the job fails
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS},
            "crash_mid_batch": 1, "crash_always": True}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        jobs = ledger.jobs("ja")
        outcomes = ledger.outcomes(jobs[0]["id"])

    assert [j["state"] for j in jobs] == ["failed"], "the job is failed after its second crash"
    # why: the rename has to have something to name, or the assertion below proves nothing
    made = [o for o in outcomes if o["outcome"] == "made" and o["note_id"] is not None]
    assert made, "the first word must be made before the crash, or this test proves nothing"
    # the rename is logged with the item and the number of lines it renamed (at least the one made card)
    renames = [e for e in steps.log if e[0] == "name_media"]
    assert renames, f"a failed job still renames its made cards' media: {steps.log}"
    assert renames[0][1] == 1, "the rename is for the item that failed"
    assert renames[0][2] >= 1, "the rename covers the card the job made before it crashed"
