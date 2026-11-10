"""A run whose preparation went through a fix of the language's own needs (P2.5 N2): the first run's Anki sync
asks for a known-sync Needs ("Sync once from Surasura's Anki window first"), so the language waits and the Needs
stays open; the next run on the same ledger prepares cleanly and the runner fixes that Needs by itself (its
`fixed_at` is set and it is no longer listed as a need).

What a wrong answer would cost: the learner is told to sync Anki forever, although the sync went through on the
next run, and the status window keeps saying "Needs you" for a problem that is gone.

Against `FakeSteps` with real words and a real ledger; never a live Anki, no sleeps.
"""
import sqlite3

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("気配", "けはい")]


def test_a_later_run_whose_preparation_went_through_fixes_the_known_sync_need(tmp_path):
    ledger_path = str(tmp_path / "ledger.sqlite")

    # first run: the sync asks for a fix from the learner, so the language waits with the Needs open
    first = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "prepare_error": "needs"}
    with Ledger(ledger_path) as ledger:
        runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), first), ledger=ledger,
                   sleep=lambda s: None, looks=1)
        # why: the need must be open before the second run, or fixing it proves nothing
        open_kinds = [n["kind"] for n in ledger.needs("ja")]
        assert "known-sync" in open_kinds, "the first run's failed sync leaves a known-sync need open"

    # second run on the same ledger, preparation now clean: the need is fixed by the runner itself
    second = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}}
    with Ledger(ledger_path) as ledger:
        runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), second), ledger=ledger,
                   sleep=lambda s: None, looks=1)
        still_listed = [n["kind"] for n in ledger.needs("ja", listed=False)]

    assert "known-sync" not in still_listed, "a clean preparation fixes the known-sync need of the language"
    # the row itself keeps its history: fixed_at is set, so the fix is recorded rather than the row deleted
    conn = sqlite3.connect(ledger_path)
    try:
        rows = conn.execute("SELECT fixed_at FROM needs WHERE kind = 'known-sync'").fetchall()
    finally:
        conn.close()
    assert rows, "the known-sync row is kept, not deleted"
    assert all(row[0] is not None for row in rows), "its fixed_at is set once the sync went through"
