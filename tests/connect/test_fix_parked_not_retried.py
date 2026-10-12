"""A job waiting for the next start is parked for this run (P2.4 review fix R9; runner `_wait`, adversary P2.4-A #11).

Two jobs: item 1 has no video on this computer (waits for the next start, `look=False`), item 2's Anki Miner is open
(waits and looks again, `look=True`). Over three looks, item 2's video is asked on every look, item 1's only once.

What a wrong answer would cost: a job with no video asked again every 2 minutes all night (a process that never
exits, a battery drain); the parked job's pick re-run each look, so a second Generate's list is read again.

Against `FakeSteps` (real words); the 2-minute look is the injected `sleep`, so no real time passes. Never a live Anki.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


class VideoCountingSteps(FakeSteps):
    """Records which item's video is asked for, once per call, so the test can count each job's looks."""

    def __init__(self, folder, plan=None):
        super().__init__(folder, plan)
        self.video_asked = []

    def video(self, lang, job):
        self.video_asked.append(job["item_id"])
        return super().video(lang, job)


def test_a_job_waiting_for_the_next_start_is_not_tried_again_this_run(tmp_path):
    # item 1 (no video) parks at its first look and is never asked again; item 2 (Anki Miner open) is asked again at
    # every one of the three looks (adversary P2.4-A #11)
    plan = {
        "queue": {"ja": [1, 2]},
        "line": {"ja": [1, 2]},
        "videos": {"1": None},
        "miner_busy": True,
    }
    steps = VideoCountingSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert steps.video_asked.count(1) == 1, "a parked job's video is asked once, never at each look"
    assert steps.video_asked.count(2) == 3, "a job waiting for Anki Miner is asked at every look"
    assert summary["languages"]["ja"]["waiting"][1] == runner.NO_VIDEO
