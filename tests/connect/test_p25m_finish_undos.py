"""The runner finishes a half-done *Undo this batch* only when one is actually pending.

Rule: `runner._finish_undos(steps, ledger, lang)` calls `steps.finish_undos(lang, ledger)` only when the ledger holds
an unfinished undo for that language; with none pending, Anki is never reached. What a wrong answer costs: every
run would open Anki for nothing, and a run with no undo to finish could call into Anki's delete path by mistake.
"""

import pytest

from app.connect import runner
from app.connect.ledger import Ledger


class FakeSteps:
    """The runner's steps object: only `finish_undos`, recording each call."""

    def __init__(self):
        self.calls = []

    def finish_undos(self, lang, ledger):
        self.calls.append(lang)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as book:
        yield book


def test_no_pending_undo_means_finish_is_never_called(ledger):
    # An empty ledger has nothing a kill left half-way, so Anki must not be asked to finish anything.
    steps = FakeSteps()
    runner._finish_undos(steps, ledger, "ja")
    assert steps.calls == [], "with no pending undo, finish_undos is not called"


def test_pending_undo_of_the_language_is_finished_once(ledger):
    # A job's undo that was started and never finished is pending; the runner finishes it once, for its language.
    job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
    ledger.start_undo(job_id, "ja", [101], [])
    steps = FakeSteps()
    runner._finish_undos(steps, ledger, "ja")
    assert steps.calls == ["ja"], "a pending Japanese undo is finished exactly once, with its language"
