"""A run's fix by kind touches only the language's own needs (no item).

The rule: `Ledger.fix("ja", kinds=["known-sync"])` fixes the language's own known-sync need (the one with no item)
and leaves a known-sync need that belongs to item 3 open. A run that finished its known-sync step clears the
language's own trouble; it must never clear trouble of an episode the run did not fix.

What a wrong answer would cost: the run would mark item 3's *Needs you* entry as fixed, and the learner would lose
the warning that item 3's known-word sync still needs attention, with no sign that anything went wrong.

The ledger is real SQLite in a temp folder; no Anki is involved.
"""
import pytest

from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    """A fresh ledger per test, closed even when the test fails."""
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield led
    finally:
        led.close()


def test_fix_by_kind_without_item_leaves_an_item_known_sync_need_open(ledger):
    # Two known-sync needs in the same language: one the language owns (no item), one owned by item 3.
    ledger.need("ja", "known-sync", "同期が止まりました")
    ledger.need("ja", "known-sync", "別の同期の問題", item_id=3)

    fixed = ledger.fix("ja", kinds=["known-sync"])

    # Only the language's own need is fixed; item 3's need stays open in the list.
    assert len(fixed) == 1
    assert fixed[0]["item_id"] is None
    open_rows = ledger.needs("ja")
    assert [(r["item_id"], r["kind"]) for r in open_rows] == [(3, "known-sync")]
