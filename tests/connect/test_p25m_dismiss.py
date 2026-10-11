"""Dismissing a *Needs you* entry twice changes nothing (`Ledger.dismiss`).

The rule: the first Dismiss takes the entry off the list and returns True; a second Dismiss of the same entry
returns False and writes nothing, so the time the entry was dismissed stays the first time.

What a wrong answer would cost: a second click (or a repeated Dismiss from another window) would count as a
change, and the dismissed time would be rewritten to the later moment, so the record of when you stopped seeing
the wait would be wrong.
"""

import app.connect.ledger as ledger_module
import pytest

from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_dismissing_twice_returns_false_and_keeps_the_first_dismissed_time(ledger, monkeypatch):
    # Why: a repeated Dismiss must not look like a new change or move the time the user first dismissed it
    assert ledger.need("ja", "not-timed", "約束は時間が決まっていません") is True
    need_id = ledger.needs("ja")[0]["id"]

    assert ledger.dismiss(need_id) is True
    first_time = ledger.needs("ja", listed=False)[0]["dismissed_at"]
    assert first_time is not None

    # A later clock: a rewritten time would show up as the later value
    later = "2030-01-01T00:00:00Z"
    monkeypatch.setattr(ledger_module, "_now", lambda: later)

    assert ledger.dismiss(need_id) is False
    assert ledger.needs("ja", listed=False)[0]["dismissed_at"] == first_time
    assert first_time != later
