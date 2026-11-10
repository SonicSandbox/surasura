"""The status row's gap the P3.1 mutant pass found (2026-10-11): after `refresh()` the next look reads the record
again, even though the stamp did not move (P3.1 row 3.1.4).

What a wrong answer would cost: the window marks the list seen or dismisses a card, and the row keeps showing the
old line and the old badge until the ledger's stamp happens to move, so the user sees a stale "Needs you" after
acting on it. The rule is the user-visible one: the same stamp, a refresh, and a changed record is drawn. Without a
refresh the same stamp still reads nothing (S19), which this test checks first so the read is caused by refresh
and not by the poll. The row is built on a hidden root; Connect's stamp and record are stood in for.
"""
import pytest

from tests.connect_tk_helpers import tk_root
from tests.test_connect_status_row import NEED, Connect, _look, _record, _row


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


def test_refresh_reads_again_at_the_same_stamp_and_draws_the_changed_record(root):
    """Why: the window's own actions change the record without moving the stamp; refresh must make the row look
    again."""
    connect = Connect(_record(line="Up to date · 26 cards made today"))
    row, pump, _tips = _row(root, connect)
    _look(row, pump, root)
    assert connect.count("read") == 1 and row.redraws == 1

    _look(row, pump, root)                       # no refresh, same stamp: nothing is read (S19 contract)
    assert connect.count("read") == 1, "a look at the same stamp without refresh must not read"

    connect.record = _record(line="Up to date · 27 cards made today 上層部", needs=[NEED], unseen=1)
    row.refresh()                                # the window marked the list seen / dismissed a card
    assert pump.run(root, lambda: not row._looking and not pump.jobs)

    assert connect.stamp_value == [1, 2, False, "2026-10-11"], "the stamp did not move"
    assert connect.count("read") == 2, "refresh makes the next look read the record again"
    assert row.redraws == 2 and row.line.cget("text") == "Connect: Up to date · 27 cards made today 上層部"


def test_a_look_still_running_starts_no_second_one(root):
    # A refresh or a tick while a worker still looks (a ledger held by Anki Miner) starts no second worker: one look
    # at a time, never a pile of threads behind a busy ledger
    import threading
    gate = threading.Event()
    connect = Connect(_record())
    real_stamp = connect.stamp

    def slow_stamp(languages=None):
        gate.wait(5)
        return real_stamp(languages)
    row, pump, _tips = _row(root, connect)
    row._stamp = slow_stamp
    row.look_now()
    row.look_now()
    row.refresh()
    gate.set()
    assert pump.run(root, lambda: not row._looking and not pump.jobs)
    assert connect.count("stamp") == 1, "one look while the first was still running"
