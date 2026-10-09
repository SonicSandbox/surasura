"""The run's summary names what the shelf did (P2.4 Part B, intent keeper P2.4-B #1, S16: an automation is seen).

When the shelf suspends waiting cards, the run's summary for that language carries a "shelf" list with the words the
shelf said it did; a run where the shelf said nothing has no "shelf" key at all, so the dashboard shows nothing it
didn't do.

What a wrong answer would cost: a learner whose cards were suspended by an automation with no line anywhere saying so
(an automation nobody sees), or a "shelf" key that appears on every run and tells the learner the shelf did something
when it did not.

Against `FakeSteps` (real words, item 1 = 3 words, the cap at 300 with 300 waiting so the shelf is asked); the look's
sleep is a no-op. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


class ShelfSayingSteps(FakeSteps):
    """The real shelf's answer, plus what it says it did: the shelve call is asked as the base class asks it, and the
    subclass adds the one line the shelf reports for this run."""

    def shelve(self, lang, ledger, todo, count, cap):
        frees = super().shelve(lang, ledger, todo, count, cap)
        self.said = {"ja": ["3 of Connect's waiting cards went to the shelf"]}
        return frees


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, steps_class):
    """One run of item 1 at the cap, with 300 waiting: the shelf is asked and frees nothing, so the job waits."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "cap": 300, "waiting": 300}
    steps = steps_class(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda seconds: None, looks=1)
    return steps, summary


def test_the_run_summary_names_what_the_shelf_did(tmp_path, ledger):
    # why: the shelf suspends cards on its own; the summary is the only place the learner is told so, and it must
    # carry the shelf's words for this language exactly as the shelf said them
    steps, summary = _run(tmp_path, ledger, ShelfSayingSteps)
    assert any(e[0] == "shelve" for e in steps.log), "the shelf was asked, so there is something to name"
    assert summary["languages"]["ja"]["shelf"] == ["3 of Connect's waiting cards went to the shelf"]


def test_a_run_whose_steps_say_nothing_has_no_shelf_key(tmp_path, ledger):
    # why: a "shelf" key on a run where the shelf said nothing would claim an action that never happened
    steps, summary = _run(tmp_path, ledger, FakeSteps)
    assert any(e[0] == "shelve" for e in steps.log), "the shelf was asked and said nothing"
    assert "shelf" not in summary["languages"]["ja"]
