"""The status line never says "Making cards" when Connect isn't running (status.py `_line`).

Rule: a job left in an in-flight step (here `mining`, after a run began) is not work in progress when Connect is
closed. The line must not start with "Making cards" and the state must not be `working`; the job waits, because a
closed Connect can't finish it. A wrong answer would tell the learner that cards are being made while nothing is
running, so the progress line would stay on "working" for a job that will never move.
"""
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


def _ja_status(path):
    return status.read(["ja"], path=path)["languages"]["ja"]


def test_job_left_mid_step_is_not_making_cards_when_connect_is_closed(ledger_path, monkeypatch):
    """Connect is closed while a job sits in the `mining` step of a run: the line is not "Making cards" and the state
    is not `working`. The job is still open, so the line reports it as waiting rather than as work in progress."""
    monkeypatch.setattr(status, "running", lambda: False)
    with Ledger(ledger_path) as ledger:
        job = ledger.queue("ja", 401, "test", "ev-4")
        ledger.mark_run("ja")                       # the run began, as it would before the job was left mid-step
        ledger.set_state(job, "mining")

    ja = _ja_status(ledger_path)

    assert not ja["line"].startswith("Making cards")
    assert ja["state"] != "working"
    assert ja["state"] == "waiting"
