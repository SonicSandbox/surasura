"""The pairing is checked again before every batch (P2.4 review fix, Connect's loop; E17): hato can re-time an episode
while Anki Miner is still to be asked for its cards. A job whose pairing changed between the fit check and a batch is
picked again (its words and its pairing version read afresh) before anything is mined with the old timing.

What a wrong answer would cost: cards mined from lines that no longer match the episode's timing, so the example
sentences and the audio land on the wrong moment in the video. Real Japanese words, temp folders only, never a live
Anki; the fake steps stand in for every outside call.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class _RetimedDuringFit(FakeSteps):
    """hato re-times the episode the first time the fit check runs: the pairing version changes after the job was picked."""

    def __init__(self, folder, plan):
        super().__init__(folder, plan)
        self.retimed = False

    def fit(self, lang, job, pairing, video, subtitle):
        if not self.retimed:
            self.retimed = True
            self.plan["pairings"]["1"] = {"verdict": "timed", "n": 2}
        return super().fit(lang, job, pairing, video, subtitle)


def test_a_pairing_retimed_before_a_batch_picks_the_job_again_and_mines_it_once(tmp_path, ledger):
    # the first batch must never run on the old timing: the job is picked a second time, then mined once with the new one
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "pairings": {"1": {"verdict": "timed", "n": 1}}}
    steps = _RetimedDuringFit(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)

    picks = [e for e in steps.log if e[0] == "pick"]
    mines = [e for e in steps.log if e[0] == "mine"]
    assert len(picks) == 2, "the re-timed job is picked again before its batch"
    assert len(mines) == 1, "it is mined once, after the pairing settled"
    assert summary["languages"]["ja"]["done"] == [1]
