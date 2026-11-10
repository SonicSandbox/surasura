"""`Ledger.mark_seen` on a need the window has already shown (the P2.5 mutant M9).

The rule: marking a need seen returns 1 the first time and 0 the second, and the seen time keeps its first value,
so the badge counts a need once and "when you saw it" never moves forward on a repeat.

What a wrong answer would cost: every reopen of the window would rewrite when each need was seen, so a need you saw
yesterday would look fresh today and the record of what you were shown would be wrong.
"""

import app.connect.ledger
import pytest

from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_marking_a_need_seen_twice_changes_nothing_the_second_time(ledger, monkeypatch):
    # Why: `AND seen_at IS NULL` is what keeps the first seen time; without it a second mark rewrites it.
    assert ledger.need("ja", "not-timed", "上層部は時間が決まっていません") is True
    row_id = ledger.needs("ja")[0]["id"]

    assert ledger.mark_seen([row_id]) == 1
    first_seen = ledger.needs("ja")[0]["seen_at"]
    assert first_seen is not None

    # Move the clock on, so a rewritten seen time would be visibly different.
    monkeypatch.setattr(app.connect.ledger, "_now", lambda: "2030-01-01T00:00:00Z")

    assert ledger.mark_seen([row_id]) == 0
    assert ledger.needs("ja")[0]["seen_at"] == first_seen
