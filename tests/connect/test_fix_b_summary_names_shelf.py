"""The run's summary names what the shelf did (P2.4 Part B, intent keeper P2.4-B #1, S16: an automation is seen).

When the shelf does something (since Kyou-SH only the swap-in at a run's first look: it no longer shelves at the
cap), the run's summary for that language carries a "shelf" list with the words the
shelf said it did; a run where the shelf said nothing has no "shelf" key at all, so the dashboard shows nothing it
didn't do.

What a wrong answer would cost: a learner whose cards were suspended by an automation with no line anywhere saying so
(an automation nobody sees), or a "shelf" key that appears on every run and tells the learner the shelf did something
when it did not.

Against `FakeSteps` (real words, item 1 = 3 words, the cap at 300 with 300 waiting); the shelf's line is said in the
run's first look (`prepare`, where the real swap-in speaks); the look's sleep is a no-op. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


class ShelfSayingSteps(FakeSteps):
    """The base class's look, plus the one line the shelf reports for this run (the swap-in's, said in `prepare`)."""

    def prepare(self, lang, ledger):
        out = super().prepare(lang, ledger)
        self.said = {"ja": ["3 of Connect's waiting cards went to the shelf"]}
        return out


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, steps_class):
    """One run of item 1 at the cap, with 300 waiting: the job waits."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "cap": 300, "waiting": 300}
    steps = steps_class(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda seconds: None, looks=1)
    return steps, summary


def test_the_run_summary_names_what_the_shelf_did(tmp_path, ledger):
    # why: the shelf suspends cards on its own; the summary is the only place the learner is told so, and it must
    # carry the shelf's words for this language exactly as the shelf said them
    steps, summary = _run(tmp_path, ledger, ShelfSayingSteps)
    assert summary["languages"]["ja"]["shelf"] == ["3 of Connect's waiting cards went to the shelf"]


def test_a_run_whose_steps_say_nothing_has_no_shelf_key(tmp_path, ledger):
    # why: a "shelf" key on a run where the shelf said nothing would claim an action that never happened
    steps, summary = _run(tmp_path, ledger, FakeSteps)
    assert not any(e[0] == "shelve" for e in steps.log), "the shelf is never asked at the cap (Kyou-SH)"
    assert "shelf" not in summary["languages"]["ja"]
