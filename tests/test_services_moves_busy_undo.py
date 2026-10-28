"""P-2-F (the store-busy register's row F, alpha 4): a move given while an Undo at the head of the queue waits on a busy
store is journalled at once — never only at the next retry.

What a wrong answer would cost a learner: an Undo is never journalled (it needs its Change), so while it waited on a
busy store the journal held nothing, and a drag he gave meanwhile was written to the journal only when the Undo was
tried again; a crash in that moment lost the drag (charter G1: a move can't be lost). Here the retry is 5 s, so only
the fix journals it in time.

A real migrated library (`tests/test_services_moves.Library`), the store's write lock held by another window's save.
"""
import time

from tests import services_helpers as h
from tests.test_services_moves import (LockHolder, journal, journalled, lib, make_writer,  # noqa: F401 (fixtures)
                                       short_lock_wait)


def test_a_move_given_while_an_undo_waits_on_a_busy_store_is_journalled_at_once(lib, make_writer, short_lock_wait):
    w, heard = make_writer(retry=5.0)
    goal = lib.ids("goal")
    w.move([goal[5]], "goal", before_id=goal[0], label="first")
    assert h.until(lambda: heard.saved)
    holder = LockHolder(lib.db)
    try:
        w.undo(label="undo")                                 # the head: an Undo, never journalled
        assert h.until(lambda: w.attempts >= 2, seconds=5)   # the Undo's attempt began …
        time.sleep(0.5)                                      # … met the busy store (0.2 s) and went back to wait:
        assert journalled(lib.language) == []                # nothing wakes the writer again for 5 s
        started = time.monotonic()
        w.move([goal[8]], "goal", before_id=goal[1], label="second")
        assert h.until(lambda: journalled(lib.language) == [("move", [goal[8]])], seconds=2)
        assert time.monotonic() - started < 2.0              # long before the 5 s retry
    finally:
        holder.release()
    assert h.until(lambda: heard.undone and len(heard.saved) == 2, seconds=15)
    assert h.until(lambda: journal(lib.language) is None)


def test_once_the_head_lands_a_quiet_queue_journals_nothing(lib, make_writer):
    """The flag ends with its head: on a quiet store a move lands with no journal written."""
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.move([goal[5]], "goal", before_id=goal[0], label="first")
    assert h.until(lambda: heard.saved)
    assert journal(lib.language) is None and not w._head_waits
