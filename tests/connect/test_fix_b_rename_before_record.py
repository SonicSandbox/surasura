"""The store write comes after the media rename (P2.4 Part B final-adversary fix J9; runner `_mine`, the end of it).

When the media rename waits because the learner is reviewing in Anki, the job must wait at mining without writing
the store: the made cards are recorded only once the rename is done, and then exactly once. A write before the
rename would be repeated at every look that waits, and the store would hold a receipt for a rename nobody finished.
What a wrong answer would cost: the library counts a card as learned in a rename that never ran, or writes the same
record again on every look while the learner reviews.

Against `FakeSteps` with real words: the rename's first call raises Wait (the learner is reviewing), the second call
goes through. Never a live Anki, no sleeps.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


class ReviewWaitsOnce(FakeSteps):
    """The first rename finds Anki under review: it waits, and the store's records seen at that moment are kept."""

    def __init__(self, folder, plan=None):
        super().__init__(folder, plan)
        self.waited_once = False
        self.records_at_wait = None
        self.renames = 0

    def name_media(self, lang, job, picked, lines):
        self.renames += 1
        if not self.waited_once:
            self.waited_once = True
            self.records_at_wait = len(self.records)   # why: a write before the rename shows up here
            raise runner.Wait(runner.REVIEWING, resume="mining")
        super().name_media(lang, job, picked, lines)


def test_the_store_write_waits_for_the_media_rename_then_happens_once(tmp_path):
    # one line, two real words made; the rename waits on the first look and is done on the second
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}}
    steps = ReviewWaitsOnce(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=2)
        job = ledger.jobs("ja")[0]

    assert steps.waited_once, "why: the rename must have been asked and have waited, or this test proves nothing"
    assert steps.records_at_wait == 0, "the store is not written while the rename waits for the learner"
    assert steps.renames == 2, "the rename is asked again on the next look, and goes through"
    assert len(steps.records) == 1, f"the made cards are written once, after the rename: {steps.records}"
    assert steps.records[0][0] == 1
    assert steps.records[0][1], "the write holds the cards made, with their note ids"
    assert job["state"] != "failed"
