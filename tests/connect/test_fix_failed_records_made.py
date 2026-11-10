"""A job that fails twice still records the cards it made (P2.4 Part A review fix R4; runner `_fail_mining`, which
calls `_record_made` before it marks the job `failed`): the first try makes a card, the batch crashes, the retry
crashes too. The store write (`steps.record`, which G1.3-4 read) must hold the word made before the crash, with its
note id, and the ledger must owe a re-sort for the language, so the made card is ordered on the next pass.

What a wrong answer would cost: a card sitting in the user's Anki deck that the library never hears of (it is not
counted as learned, and a later Generate picks the same word again); a made card that is never ordered.

Against `FakeSteps` with real words; never a live Anki, no sleeps.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("気配", "けはい")]


def test_a_job_that_fails_twice_still_records_the_cards_it_made(tmp_path):
    # the first word is made, then the batch crashes; the retry crashes too (crash_always), so the job fails
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS},
            "crash_mid_batch": 1, "crash_always": True}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        jobs = ledger.jobs("ja")
        job = ledger.job_by_id(jobs[0]["id"])
        outcomes = ledger.outcomes(jobs[0]["id"])
        owed = ledger.resort_owed("ja")

    assert [j["state"] for j in jobs] == ["failed"], "the job is failed after its second crash"
    # the made cards, as the ledger holds them: word -> its note ids (the shape `_made` builds for the store)
    made = {}
    for o in outcomes:
        if o["outcome"] == "made":
            made.setdefault(o["word"], []).append(o["note_id"])
    assert made.get(WORDS[0][0]), "why: the first word must be made before the crash, or this test proves nothing"
    # the store write holds exactly those words with their note ids: a record that dropped them would show here
    assert len(steps.records) == 1, f"the failed job's made cards are written once: {steps.records}"
    recorded_item, recorded_made, _mined = steps.records[0]
    assert recorded_item == 1
    assert recorded_made == made, "every card made before the crash is in the store write, with its note id"
    assert owed is not None, "a made card owes its language a re-sort, so it is ordered on the next pass"
    assert job["state"] == "failed"
