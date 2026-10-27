"""K6 (alpha 4, Mattias's note 1): the picks move as ONE store command — the writer's `place` / `move` / `remove`
handed every picked item at once.

What a wrong answer would cost a learner: 50 picked episodes moved to Goal as 50 commands — 50 toasts, 50 Undos (one
Ctrl+Z puts back one episode of the 50), a crash half way leaving half of them moved, and at 20,000 files 50 times the
slow Goal move (D1); or the block landing in the order the picks were CLICKED rather than the list's own, so a season
lands shuffled. These tests hold the writer to one journal entry, one change, one Undo, the list's order kept, and
name the one trap the window must avoid (*Up next* with Up Next itself among the picks).

A real migrated library (`tests/test_services_moves.Library`: three shows of four episodes and a loose file in NOW,
Soon and 6+ Months, Japanese and Chinese names), the writer on its own thread.
"""
import time

from app.services import moves as M
from tests import services_helpers as h
from tests.test_services_moves import (Heard, LockHolder, journalled, lib, make_writer,  # noqa: F401 (fixtures)
                                       short_lock_wait)


def _picks(lib):
    """Five picks across Current, clicked out of the list's order (the last first)."""
    current = lib.current()
    picked = [current[1], current[3], current[4], current[7], current[9]]
    return picked, list(reversed(picked))


def test_picks_to_goal_are_one_command_one_change_one_undo_and_keep_the_lists_order(lib, make_writer):
    w, heard = make_writer()
    in_order, clicked = _picks(lib)
    w.move(clicked, "goal", end=True, label="5 to Goal")
    assert h.until(lambda: heard.saved)
    time.sleep(0.1)                                     # nothing else lands after it
    assert len(heard.saved) == 1                        # one change: one toast, one Undo
    goal = lib.ids("goal")
    assert goal[-5:] == in_order                        # Goal's end, in the list's order (never the clicks')
    assert not set(in_order) & set(lib.current())
    w.undo(label="undo")
    assert h.until(lambda: heard.undone)
    assert len(heard.undone) == 1
    assert [i for i in lib.current() if i in in_order] == in_order     # every pick back, one Undo
    assert not set(in_order) & set(lib.ids("goal"))


def test_picks_up_next_with_up_next_itself_picked_go_to_the_top_through_place(lib, make_writer):
    """*Up next* for picks that include the first row: `move` before that row is a no-op (its anchor is in the block),
    so the window uses `place(ids, "top")` — the top of Current, the block in the list's order."""
    w, heard = make_writer()
    current = lib.current()
    picked = [current[0], current[5], current[8]]
    assert w.move(list(reversed(picked)), "now", before_id=current[0], label="no-op") is not None
    assert h.until(lambda: heard.rereads == 1)          # nothing to change: re-read, never a toast
    assert heard.saved == []
    w.place(list(reversed(picked)), "top", label="3 up next")
    assert h.until(lambda: heard.saved)
    assert lib.current()[:3] == picked
    assert len(heard.saved) == 1


def test_picks_to_soon_land_together_below_the_line_as_one_change(lib, make_writer):
    w, heard = make_writer()
    in_order, clicked = _picks(lib)
    w.place(clicked, "soon", label="5 to Soon")
    assert h.until(lambda: heard.saved)
    soon = lib.ids("soon")
    assert soon[:5] == in_order and len(heard.saved) == 1


def test_picks_removed_are_one_command_and_one_undo_puts_every_one_back(lib, make_writer):
    w, heard = make_writer()
    in_order, clicked = _picks(lib)
    w.remove(clicked, label="5 removed")
    assert h.until(lambda: heard.saved)
    assert len(heard.saved) == 1 and not set(in_order) & set(lib.current())
    w.undo(label="undo")
    assert h.until(lambda: heard.undone)
    assert [i for i in lib.current() if i in in_order] == in_order


def test_picks_given_while_the_store_is_busy_are_one_journal_entry_and_land_once(lib, make_writer, short_lock_wait):
    """A busy store: the picks wait as ONE journalled command (a crash replays them together or not at all), never
    one entry per pick."""
    w, heard = make_writer()
    in_order, clicked = _picks(lib)
    holder = LockHolder(lib.db)
    try:
        w.move(clicked, "goal", end=True, label="5 to Goal")
        assert h.until(lambda: journalled(lib.language))
        assert journalled(lib.language) == [("move", clicked)]
    finally:
        holder.release()
    assert h.until(lambda: heard.saved)
    assert len(heard.saved) == 1 and lib.ids("goal")[-5:] == in_order
    assert h.until(lambda: not journalled(lib.language))


def test_the_writer_keeps_one_command_for_any_number_of_ids():
    """The commands the picks use carry every id in one entry (the journal's shape): nothing splits them per item."""
    for op in ("move", "place", "remove", "finish", "set_tier"):
        assert op in M.JOURNALLED
