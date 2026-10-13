"""Connect's ordering step pays the owed re-sort (P2.4 row 2.4.x; P1.5 02-data-model): when a job's ordering step runs
and finishes, the re-sort that was owed for its language (the list moved) is paid, so it is no longer owed.

Mutant P2.4-D17: the `ledger.resort_paid(lang)` call after the ordering step is replaced by `pass`. The ordering step
still runs, but the re-sort debt is never cleared, so the next job re-sorts Anki's queue for nothing and the
"re-sort owed" mark stays on forever.

What a wrong answer would cost: a list that moved is re-sorted on every run after it was already re-sorted (Anki's
queue reshuffled again and again), or the owed mark never clears and the app keeps showing a re-sort as pending.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=1, languages=("ja",)):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, list(languages), steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)
    return steps, summary


def test_ordering_step_pays_the_owed_resort_for_its_language(tmp_path, ledger):
    # Why: the list moved before this run, so a re-sort is owed for ja. The ordering step is the one that pays it.
    with ledger.transaction():
        ledger.owe_resort("ja")
    assert ledger.resort_owed("ja") is not None, "setup: the re-sort is owed before the run"
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    assert ("order", 1) in steps.log, "setup: the job reached its ordering step"
    assert ledger.resort_owed("ja") is None, "the ordering step paid the owed re-sort"
