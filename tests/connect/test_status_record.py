"""The status record's badge, seen and dismissed rules (P2.5 S2).

Rule: with no ledger file the record is "Up to date", idle, with no unseen needs, and reading it (or marking
something seen) never creates the file; with two open needs the badge counts only the unseen ones, both stay
listed newest first after one is seen, and a dismissed one leaves the list; the stamp is the same for the same
ledger and changes after a write. What a wrong answer costs: a badge that counts seen needs keeps the learner
looking at a "1 new" that is not new, and a read that creates a ledger makes a file Connect never asked for.
"""
import os
import time

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


def test_stamp_differs_after_a_need_written_in_the_same_clock_tick(tmp_path, quiet_running):
    # Why: a file's time moves only once a clock tick (15.6 ms on Windows' default clock, 2 s on FAT), so a second
    # write of the same size inside the first one's tick leaves size and time as they were. A look between the two
    # writes then keeps the stamp, and the window never shows the second need (flakes-2026-11-05 #1). The tick is
    # made here by putting the first write's time back on the file.
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        ledger.need("ja", "mine-failed", "上層部: Anki Miner stopped twice", item_id=3)
    first = os.stat(path)
    before = status.stamp(path, ["ja"])

    with Ledger(path) as ledger:
        ledger.need("ja", "known-sync", "気配 is not in the known words yet")
    os.utime(path, ns=(first.st_atime_ns, first.st_mtime_ns))
    assert os.stat(path).st_size == first.st_size              # the probe's premise: size and time as before

    assert status.stamp(path, ["ja"]) != before
    assert status.stamp(path, ["ja"]) == status.stamp(path, ["ja"])


def test_a_settled_ledger_is_stamped_without_reading_it(tmp_path, quiet_running, monkeypatch):
    # Why: the stamp is taken every 3 s; a ledger last written long ago is two stats, never its bytes read again.
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        ledger.need("ja", "mine-failed", "上層部: Anki Miner stopped twice", item_id=3)
    hour_ago = os.stat(path).st_mtime_ns - 3600 * 10 ** 9
    os.utime(path, ns=(hour_ago, hour_ago))
    monkeypatch.setattr(status, "_digest", lambda p: pytest.fail("a settled ledger was read"))

    assert status.stamp(path, ["ja"])[0] == [os.stat(path).st_size, hour_ago]


def _files(tmp_path, shm=b"\x00" * 48):
    """A ledger, its WAL and its wal-index as plain files, each dated an hour ago (settled)."""
    path = str(tmp_path / "ledger.sqlite")
    hour_ago = time.time_ns() - 3600 * 10 ** 9
    for name, data in ((path, b"SQLite format 3\x00" + b"\x00" * 4080), (path + "-wal", b"\x37\x7f\x06\x82" * 8),
                       (path + "-shm", shm)):
        with open(name, "wb") as f:
            f.write(data)
        os.utime(name, ns=(hour_ago, hour_ago))
    return path, hour_ago


def test_a_commit_moves_the_stamp_once_the_wal_index_has_it(tmp_path, quiet_running):
    # Why: a reader sees a commit only once SQLite writes the wal-index, after the WAL's bytes are final; a stamp taken
    # in between (its read still the old record) must not equal every later look's, or the commit never shows
    # (adversary A1, flakes-2026-11-05). Here only the wal-index header moves: same sizes, same times.
    path, hour_ago = _files(tmp_path)
    before = status.stamp(path, ["ja"])
    with open(path + "-shm", "r+b") as f:
        f.write(b"\x01")                                                    # its change counter's first byte
    os.utime(path + "-shm", ns=(hour_ago, hour_ago))

    assert status.stamp(path, ["ja"]) != before
    assert status.stamp(path, ["ja"]) == status.stamp(path, ["ja"])


def test_a_ledger_a_connection_holds_is_never_read_whole(tmp_path, quiet_running, monkeypatch):
    # Why: while the wal-index is there every commit moves its header, so a ledger just checkpointed (fresh) is never
    # read whole for its crc each look — tens of MB on a long-used ledger.
    path, _ = _files(tmp_path)
    now = time.time_ns()
    os.utime(path, ns=(now, now))
    monkeypatch.setattr(status, "_digest", lambda p: pytest.fail(f"{p} was read whole"))

    assert len(status.stamp(path, ["ja"])[0]) == 2


def test_a_refusal_dismissed_then_fixed_is_not_counted_as_skipped(tmp_path, quiet_running):
    # Why: a dismissed refusal is "skipped" only while its need stays open; once the fix closes it, the item must
    # leave the skipped list, or the window keeps showing a refusal the learner already dealt with.
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        assert ledger.need("ja", "not-timed", "上層部: no timing in the video yet", item_id=3) is True
        need_id = ledger.needs("ja")[0]["id"]

    assert status.dismiss(need_id, path=path) is True
    assert status.read(["ja"], path=path)["languages"]["ja"]["skipped"] == [3]

    with Ledger(path) as ledger:
        ledger.fix("ja", item_id=3)

    assert status.read(["ja"], path=path)["languages"]["ja"]["skipped"] == []
