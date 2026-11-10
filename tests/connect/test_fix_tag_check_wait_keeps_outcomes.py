"""P2.4-R review fix R13: a tag check that can't run keeps Anki Miner's own outcomes (runner `_mine`, the Wait
handler after the tag check).

A batch comes back with one word Anki Miner made and one word it answers with a status Connect doesn't know, so the
batch is in doubt and the runner asks Anki by the job's tag. If Anki closes before that check can run, the made word
must keep its note id and the batch must end "uncertain", not stay "running".

What a wrong answer would cost: the made word's note id is lost, so the job mines it again and Anki gets a second
card for one word; or the batch stays "running", and the next start reads it as Connect's own stop and checks the
tag then, when the answer was already known.

Against FakeSteps (real words); never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class _AnkiClosesBeforeTagCheck(FakeSteps):
    """Anki is shut when the tag check asks it: by_tag waits, as it does with Anki closed."""

    def by_tag(self, lang, job, picked, words):
        raise runner.Wait(runner.ANKI_CLOSED)


def test_a_tag_check_that_cannot_run_keeps_anki_miners_made_outcomes(tmp_path, ledger):
    # 気配 gets a status Connect doesn't know, so the tag check runs and fails; 上層部, which Anki Miner made, keeps
    # its note id, and the batch is "uncertain" (in doubt), not left "running" for the next start to guess at
    steps = _AnkiClosesBeforeTagCheck(str(tmp_path), {
        "line": {"ja": [1]}, "queue": {"ja": [1]},
        "words": {"1": [("上層部", "じょうそうぶ"), ("気配", "けはい")]},
        "unknown_status": ["気配"],
    })
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)

    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("waiting", runner.ANKI_CLOSED)
    assert ledger.batches(job["id"])[-1]["state"] == "uncertain", "in doubt, not left running"
    outcomes = {o["word"]: o for o in ledger.outcomes(job["id"])}
    assert outcomes["上層部"]["outcome"] == "made"
    assert outcomes["上層部"]["note_id"] in steps.anki.notes(), "the note Anki Miner made is the one recorded"
    assert outcomes["気配"]["outcome"] == "uncertain"
