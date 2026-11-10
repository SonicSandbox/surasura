"""A Backfill that answers `skipped` (a reason string) makes the loop's fill step raise Skip with that reason, so the
job names the step it could not do (runner `Steps.fill`).

Mutant P2.4-E25 turns the `skipped` check into `if False:`, so a skipped answer is ignored and the job looks filled.

What a wrong answer would cost: a Backfill that is absent or switched off would count as done, the notes would stay
without 例文 and パターン, and nobody would see why in the job's status.

Backfill is replaced by a stub at its own boundary (the real `Steps.fill` runs), so no Anki is reached.
"""
import pytest

from app.cli import verbs
from app.connect import runner


def test_backfill_skipped_reason_raises_skip_naming_the_reason(monkeypatch):
    # the answer is a string reason, not an error: the step is skipped and the reason is kept on the Skip
    monkeypatch.setattr(verbs, "backfill", lambda ns: {"skipped": "backfill absent"})
    with pytest.raises(runner.Skip) as info:
        runner.Steps({}).fill("ja", {"id": 7, "item_id": 3, "tag": "ab12cd34-7"}, [101])
    assert info.value.why == "backfill absent", "the job names the reason the step was skipped"
