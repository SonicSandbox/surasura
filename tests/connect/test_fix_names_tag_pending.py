"""Fix rule (P2.4 Part A review fixes, Connect's loop, runner `_mine` 475–477 and `_fill` 598–612): when Anki
refuses the names' tag on a batch, the batch comes back with `tag_pending`; before Backfill fills the made notes,
the runner adds that tag to them, clears the job's `tag_pending`, and only then fills and finishes the job.

What a wrong answer would cost: notes made from a names list that Anki never tagged get filled and the job is
recorded done while the tag is still owed, so the names are never found again by the tag, and a re-run has
nothing left to repair them with.

Against `FakeSteps` (real words); `sleep` is a no-op, the ledger is a temp SQLite file. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_refused_names_tag_is_added_before_filling_and_cleared(tmp_path, ledger):
    """A batch Anki answers with `tag_pending` (the names' tag refused) must have its made notes tagged before
    `fill` runs, and the job must end done with `tag_pending` empty. Without the tagging step the fill would run
    on untagged notes and the owed tag would stay on the job."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "names_tag_refused": True}
    steps = FakeSteps(str(tmp_path), plan)

    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)

    kinds = [entry[0] for entry in steps.log]
    assert "tag_names" in kinds, "the refused names' tag is added to the made notes"
    assert "fill" in kinds, "the job still reaches filling after the tag is added"
    tagged = steps.log[kinds.index("tag_names")][1]
    filled = steps.log[kinds.index("fill")][2]
    assert tagged, "the tagged notes are the made notes (a non-empty list)"
    assert set(tagged) == set(filled), "every made note is tagged and then filled"
    assert kinds.index("tag_names") < kinds.index("fill"), "tagging happens before fill touches the notes"

    job = ledger.jobs("ja")[0]
    assert job["state"] == "done", "the job finishes once the tag is in place"
    assert not job["tag_pending"], "the owed tag is cleared from the job, not left for a re-run"
