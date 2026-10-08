"""A duplicate after a batch in doubt (P2.4 Part A review fix, runner `_mine` ~483–487): when Anki Miner's first batch
crashed and its second answers a word `duplicate`, the note found under this job's own tag is the card Connect made
before the crash, so the word is recorded as made with that note id — never left as a duplicate.

What a wrong answer would cost: a word Connect made, with its card in Anki, shown as turned down by Anki Miner; the
job's made count and its Undo list (the note ids) missing a card that is really there.

Against `FakeSteps` (a real word, a fake Anki); never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import TAG, FakeSteps

WORD = ("上層部", "ジョウソウブ")


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class DoubtThenDuplicate(FakeSteps):
    """The first batch crashes (every word in doubt); before the second batch, the card Connect made before the crash
    is in Anki under the job's tag, and the second batch answers the word `duplicate`."""

    def __init__(self, folder, plan):
        super().__init__(folder, plan)
        self.calls = 0
        self.added_note = None

    def mine(self, lang, job, picked, words, attempt):
        self.calls += 1
        if self.calls == 1:
            return super().mine(lang, job, picked, words, attempt)     # the crash: nothing reached Anki for the word
        self.added_note = self.anki.add(WORD[0], TAG + job["tag"])     # the card that reached Anki before the crash
        return {"outcomes": [{"word": WORD[0], "reading": WORD[1], "outcome": "duplicate", "note_id": None,
                              "line_start": 10.0}],
                "app": "3.7.0", "doubt": False, "tag_pending": []}


def test_a_duplicate_that_is_this_jobs_own_card_is_recorded_as_made_after_a_batch_in_doubt(tmp_path, ledger):
    # the plan: one item, one word; its first batch crashes at the first word (crash_mid_batch: 0)
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": [WORD]}, "crash_mid_batch": 0}
    steps = DoubtThenDuplicate(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)

    assert steps.calls == 2                                  # tried once more after the batch in doubt, no third try
    jid = ledger.jobs("ja")[0]["id"]
    rows = [o for o in ledger.outcomes(jid) if o["word"] == WORD[0]]
    assert len(rows) == 1
    assert rows[0]["outcome"] == "made"                      # not "duplicate": this job's own card is recorded
    assert rows[0]["note_id"] == steps.added_note            # and it is that card's note id, the one Undo would remove
