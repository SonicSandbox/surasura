"""The ledger keeps a later attempt's outcome for each word, except a word already `made` (P2.4 gap, mutant P2.4-B19).

Rule: when a job's next attempt records an outcome for a word, that outcome replaces the earlier attempt's row,
unless the earlier row says `made` (the note was written, and nothing may undo that). A non-made row for a word
that has an earlier row must still go in. Mutant P2.4-B19 makes any earlier row block every non-made row, so a word
the first attempt left `not_attempted` keeps that stale answer after the second attempt found it. A wrong answer
would show the user a word as never tried when it was tried and not found, and the job would never retry it.

The ledger is a real SQLite file in `tmp_path`; no network, no sleeps.
"""
from app.connect.ledger import Ledger


def _o(word, outcome, note=None):
    """One outcome row as `record_outcomes` takes it (the reading is empty: these are kanji-only words here)."""
    return {"word": word, "reading": "", "outcome": outcome, "note_id": note}


def test_a_later_outcome_replaces_an_earlier_one_but_never_a_made_word(tmp_path):
    """Attempt 2 corrects attempt 1's `not_attempted` for 上層部, and cannot undo 気配's `made` from attempt 1."""
    with Ledger(str(tmp_path / "ledger.sqlite")) as L:
        j = L.queue("ja", 4, "user", None)
        with L.transaction():
            L.record_outcomes(j, 1, [_o("上層部", "not_attempted"), _o("気配", "made", 1700000000001)])
        with L.transaction():
            L.record_outcomes(j, 2, [_o("上層部", "not_found"), _o("気配", "not_found")])
        by = {r["word"]: r["outcome"] for r in L.outcomes(j)}
    # 上層部 takes the later answer; 気配 keeps `made` because the note exists.
    assert by == {"上層部": "not_found", "気配": "made"}
