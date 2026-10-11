"""The status line counts only the cards made today (status.py `_made_today`, the "N cards made today" figure).

What this holds still: a batch that made its card two days ago is not today's work. If the day filter were dropped,
the idle line would count every card Connect ever made, and the learner would read a number that says nothing about
today. Two jobs are made here; the one-card batch is moved two days back, so the count must be the other job's
two cards alone.

The ledger is a real SQLite file in a temp folder (`tmp_path`); Connect's running check is faked. No network, no sleeps.
"""
import datetime

import pytest

from app.connect import status
from app.connect.ledger import Ledger


@pytest.fixture
def ledger_path(tmp_path):
    """A real ledger file, closed before the test reads it (status.read opens its own read-only connection)."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path):
        pass
    return path


def test_made_today_counts_only_batches_that_ended_today(ledger_path, monkeypatch):
    """Three jobs. The old batch made one card and is moved to 48 hours ago; the yesterday batch made one card and is
    moved to yesterday at local noon; today's batch made two cards. The count must be 2: the two cards made today.
    Counting every made card would say 4; counting only the old batch would say 1. The yesterday batch is what separates
    'today' from 'recent': it sits inside a rolling 24-hour window for part of the day, so a rolling window fails too.
    The unequal numbers make an inverted day filter fail as well."""
    monkeypatch.setattr(status, "running", lambda: False)
    with Ledger(ledger_path) as ledger:
        old_job = ledger.queue("ja", 301, "test", "ev-old")
        ledger.start_batch(old_job, 1, "run-old")
        ledger.end_batch(old_job, 1, "done", outcomes=[
            {"word": "上層部", "reading": "じょうそうぶ", "outcome": "made", "note_id": 9101},
        ])
        ledger.set_state(old_job, "done")

        new_job = ledger.queue("ja", 302, "test", "ev-new")
        ledger.start_batch(new_job, 1, "run-new")
        ledger.end_batch(new_job, 1, "done", outcomes=[
            {"word": "気配", "reading": "けはい", "outcome": "made", "note_id": 9102},
            {"word": "場面", "reading": "ばめん", "outcome": "made", "note_id": 9103},
        ])
        ledger.set_state(new_job, "done")

        yesterday_job = ledger.queue("ja", 303, "test", "ev-yesterday")
        ledger.start_batch(yesterday_job, 1, "run-yesterday")
        ledger.end_batch(yesterday_job, 1, "done", outcomes=[
            {"word": "場所", "reading": "ばしょ", "outcome": "made", "note_id": 9104},
        ])
        ledger.set_state(yesterday_job, "done")

        # Stored as UTC text, the way end_batch writes it. 48 hours back is never today in any time zone; yesterday at
        # local noon is never today either, and sits inside a rolling 24-hour window for part of the day.
        two_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        yesterday_noon = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - datetime.timedelta(
            days=1)
        yesterday_utc = yesterday_noon.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with ledger.transaction():
            ledger.conn.execute("UPDATE batches SET ended_at = ? WHERE job_id = ?", (two_days_ago, old_job))
            ledger.conn.execute("UPDATE batches SET ended_at = ? WHERE job_id = ?", (yesterday_utc, yesterday_job))

    ja = status.read(["ja"], path=ledger_path)["languages"]["ja"]

    assert ja["made_today"] == 2
