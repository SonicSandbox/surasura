"""P2.4 gap B20: `Ledger.undo_record` lists only the notes a job made that have an id (mutant P2.4-B20).

The rule: *Undo this batch* asks for the note ids a job made. A word marked `made` without a note id has
nothing to delete in Anki, so it must not appear in the list at all. A wrong answer (a `None` in the list)
would hand Anki's delete call an empty id and make the undo look as if it had removed a note it never found.
Real Japanese words (上層部, 気配) and the ledger are real; Anki is never touched.
"""
import pytest

from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    L = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield L
    finally:
        L.close()


def o(word, outcome, note=None):
    """One outcome row, the shape `record_outcomes` takes (as in the B19 neighbour)."""
    return {"word": word, "reading": "", "outcome": outcome, "note_id": note}


def test_undo_record_lists_only_made_notes_that_have_an_id(ledger):
    # 気配 is `made` but has no note id: it has nothing for Undo to delete, so it stays out of the list.
    # 溜め息 has a note id but is not `made` (it was not found): Undo must not ask Anki to delete it either.
    j = ledger.queue("ja", 4, "user", None)
    with ledger.transaction():
        ledger.record_outcomes(j, 1, [o("上層部", "made", 1700000000001), o("気配", "made", None),
                                      o("溜め息", "not_found", 1700000000002)])
    assert ledger.undo_record(j) == [1700000000001]
