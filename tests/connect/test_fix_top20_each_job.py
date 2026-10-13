"""The top 20 is read again before each job (P2.4 review fix R2; runner `run` loop, 238–262): the line is the list as it
stands when each job is taken, so a word that leaves the top 20 while an earlier job runs is dropped in the same run,
never picked and never mined.

What a wrong answer would cost: a job for a word the user has moved off the top 20 still mined into Anki (a card the
user didn't ask for today), and a Generate's list held from the start of the run for the whole run.

Against `FakeSteps` (real words); never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class LineLosesItemTwoAfterItemOneMines(FakeSteps):
    """Item 2 leaves the top 20 while item 1 is being mined (the list is read again at the next job)."""

    def mine(self, lang, job, picked, words, attempt):
        result = super().mine(lang, job, picked, words, attempt)
        if job["item_id"] == 1:
            self.plan["line"][lang].remove(2)
        return result


def test_a_job_whose_word_leaves_the_top_20_mid_run_is_dropped_and_never_picked(tmp_path, ledger):
    # item 1's mine takes item 2 out of the line; the second job is checked against the line as it is now (2 gone), so
    # it is dropped before any pick — not against the line read at the run's start
    steps = LineLosesItemTwoAfterItemOneMines(str(tmp_path), {
        "line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=5)
    jobs = {j["item_id"]: j for j in ledger.jobs("ja")}
    assert jobs[1]["state"] == "done", "item 1 is still in the line, so it is mined"
    assert jobs[2]["state"] == "dropped", "item 2 left the top 20 during the run: dropped in the same run"
    assert ("pick", 2) not in steps.log, "a dropped job is never picked"
    assert not any(e[0] == "mine" and e[1] == 2 for e in steps.log), "and never mined"
