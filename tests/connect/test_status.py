"""The status line Connect shows while it works (status.py `_line`, U1's line and its state).

What each test holds still:

  * with Connect running and a batch under way, the line counts the run's jobs: the jobs finished since the run began
    plus the open ones, and names the step of the job in flight. A wrong count tells the learner the wrong progress,
    so "Making cards 2 of 3" must mean one finished and two to go, never one fewer;
  * with Connect not running, a waiting job's own reason is the line (a learner who sees "Waiting for Anki" knows
    what to do; a generic "working" line would hide it), and the state is `waiting`;
  * with nothing open, a line reports the cards made today, and the state is `idle`.

The ledger is a real SQLite file in a temp folder (`tmp_path`); Connect's running check is faked. No network, no sleeps.
"""
import pytest

from app.connect import status
from app.connect import ledger as ledger_module
from app.connect.ledger import Ledger


@pytest.fixture
def ledger_path(tmp_path):
    """A real ledger file, closed before the test reads it (status.read opens its own read-only connection)."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path):
        pass
    return path


def _ja_status(path):
    return status.read(["ja"], path=path)["languages"]["ja"]


def test_working_line_counts_finished_jobs_of_this_run_and_names_the_step(ledger_path, monkeypatch):
    """Three jobs: one finished in this run, one in the `mining` step, one still queued. The line says the job in
    flight is the second of three, because the finished one counts as done in this run and the queued one as to do."""
    monkeypatch.setattr(status, "running", lambda: True)
    with Ledger(ledger_path) as ledger:
        first = ledger.queue("ja", 101, "test", "ev-1")
        second = ledger.queue("ja", 102, "test", "ev-1")
        ledger.queue("ja", 103, "test", "ev-1")
        earlier = ledger.queue("ja", 104, "test", "ev-1")
        # Timestamps have one-second resolution, so the earlier job is stamped well before the run starts; a same-second
        # stamp would count it, and the start filter would go untested.
        real_now = ledger_module._now
        monkeypatch.setattr(ledger_module, "_now", lambda: "2000-01-01T00:00:00Z")
        ledger.set_state(earlier, "done")           # finished before this run began: must not count toward it
        monkeypatch.setattr(ledger_module, "_now", real_now)
        ledger.mark_run("ja")                       # the run starts; jobs finished from now on count toward it
        ledger.set_state(first, "done")
        ledger.set_state(second, "mining")

    ja = _ja_status(ledger_path)

    assert ja["line"] == "Making cards 2 of 3 — an episode (Anki Miner)"
    assert ja["state"] == "working"


def test_waiting_job_shows_its_reason_when_connect_is_not_running(ledger_path, monkeypatch):
    """Connect is closed and one job waits for Anki: the line is that job's own reason, and the state is `waiting`."""
    monkeypatch.setattr(status, "running", lambda: False)
    with Ledger(ledger_path) as ledger:
        job = ledger.queue("ja", 201, "test", "ev-2")
        ledger.set_state(job, "waiting", reason="Waiting for Anki: it isn't open.")

    ja = _ja_status(ledger_path)

    assert ja["line"] == "Waiting for Anki: it isn't open."
    assert ja["state"] == "waiting"


def test_idle_line_counts_cards_made_today_when_nothing_is_open(ledger_path, monkeypatch):
    """No open job, and a batch that made two cards and ended today: the line says so, and the state is `idle`.
    The count is the cards made, not the jobs finished, so two made words read as 2 cards."""
    monkeypatch.setattr(status, "running", lambda: False)
    with Ledger(ledger_path) as ledger:
        job = ledger.queue("ja", 301, "test", "ev-3")
        ledger.start_batch(job, 1, "run-dir")
        ledger.end_batch(job, 1, "done", outcomes=[
            {"word": "上層部", "reading": "じょうそうぶ", "outcome": "made", "note_id": 9001},
            {"word": "気配", "reading": "けはい", "outcome": "made", "note_id": 9002},
        ])
        ledger.set_state(job, "done")

    ja = _ja_status(ledger_path)

    assert ja["line"] == "Up to date · 2 cards made today"
    assert ja["state"] == "idle"
