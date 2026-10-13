"""The status record's badge, seen and dismissed rules (P2.5 S2).

Rule: with no ledger file the record is "Up to date", idle, with no unseen needs, and reading it (or marking
something seen) never creates the file; with two open needs the badge counts only the unseen ones, both stay
listed newest first after one is seen, and a dismissed one leaves the list; the stamp is the same for the same
ledger and changes after a write. What a wrong answer costs: a badge that counts seen needs keeps the learner
looking at a "1 new" that is not new, and a read that creates a ledger makes a file Connect never asked for.
"""
import os

import pytest

from app.connect import status
from app.connect.ledger import Ledger


@pytest.fixture
def quiet_running(monkeypatch):
    # The stamp reads whether Connect runs; pin it so two stamps compare only the ledger's own state.
    monkeypatch.setattr(status, "running", lambda: False)


def test_no_ledger_reads_as_up_to_date_and_creates_no_file(tmp_path, quiet_running):
    # Why: the window opens before Connect was ever used; a read must not make a ledger as a side effect.
    path = str(tmp_path / "ledger.sqlite")

    rec = status.read(["ja"], path=path)["languages"]["ja"]

    assert rec["line"] == "Up to date"
    assert rec["state"] == "idle"
    assert rec["unseen"] == 0
    assert not os.path.exists(path)


def test_marking_seen_with_no_ledger_returns_zero_and_creates_no_file(tmp_path):
    # Why: the window never makes a ledger, so "seen" on a missing file is a no-op that reports nothing changed.
    path = str(tmp_path / "ledger.sqlite")

    assert status.mark_seen([1], path=path) == 0
    assert not os.path.exists(path)


def test_badge_counts_only_unseen_needs_and_dismissed_needs_leave_the_list(tmp_path, quiet_running):
    # Why: seeing a need clears the badge but keeps it listed; only Dismiss takes it off the list.
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        assert ledger.need("ja", "mine-failed", "上層部: Anki Miner stopped twice", item_id=3) is True
        assert ledger.need("ja", "known-sync", "気配 is not in the known words yet") is True
        first, second = [row["id"] for row in ledger.needs("ja")]

    rec = status.read(["ja"], path=path)["languages"]["ja"]
    assert rec["unseen"] == 2
    assert [n["kind"] for n in rec["needs"]] == ["known-sync", "mine-failed"]  # newest first

    assert status.mark_seen([first], path=path) == 1
    rec = status.read(["ja"], path=path)["languages"]["ja"]
    assert rec["unseen"] == 1
    assert [n["kind"] for n in rec["needs"]] == ["known-sync", "mine-failed"]

    assert status.dismiss(second, path=path) is True
    rec = status.read(["ja"], path=path)["languages"]["ja"]
    assert [n["kind"] for n in rec["needs"]] == ["mine-failed"]


def test_stamp_is_equal_when_nothing_changed_and_differs_after_a_need(tmp_path, quiet_running):
    # Why: the window redraws only when the stamp moves (S19); a stamp that never moves hides new needs.
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        ledger.need("ja", "mine-failed", "上層部: Anki Miner stopped twice", item_id=3)

    before = status.stamp(path, ["ja"])
    assert status.stamp(path, ["ja"]) == before

    with Ledger(path) as ledger:
        ledger.need("ja", "known-sync", "気配 is not in the known words yet")

    assert status.stamp(path, ["ja"]) != before
