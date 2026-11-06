"""A dropped row moves once (alpha 9.1 try, report 1, Sonic 2026-11-02: *"I'll move it (BOM), it will then move back,
wait a second, and then visually go back to where i had moved it. Weird"* — expected: *"I move it and it's moved."*).

The window paints a drop at once and keeps its own order until the store has the move. It let that order go once the
writer had been idle for `settle-ms` (300 ms) — but a view the reader began before the write (the drop's own release
starts one, a Generate's numbers start more) could still be on its way: on a busy machine a build takes longer than
the settle, so that view landed after the order went and put the row back where it was, and the reader's next build
put it forward again a second later. Reproduced on the window with a 336-part group during a Generate (builds of
~0.85 s): the row showed at 3, then 6, then 3. Now the order goes only with the store's own view read after every
write landed — the reader's answer to the window's ask (`LibraryReader.republish` / `answered`); a reader that never
answers lets it go after `answer-ms`, as before.

What a wrong answer would cost a learner: a row that jumps back after the drop (they move it again, and it lands twice),
or an order that never lets go (the store's own placing never shown). Headless on the window's seed (Japanese titles).
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtTest import QTest                                          # noqa: E402

from app.qt import drag                                                 # noqa: E402
from tests.qt.conftest import wait_until                                # noqa: E402
from tests.qt.test_drag import (_stones_sheet, lift, move_global, release_global, row_point,  # noqa: E402,F401
                                rows_of, world)


def _keys(win):
    return [r.key for r in rows_of(win)]


def _dropped(win, src=6, slot=1):
    """Row `src` dropped onto row `slot` and its write landed (the writer idle, its word taken in) -> (the view shown
    before the drop, the order the drop painted)."""
    old = win.page_widgets["current"].view_model
    before = [r.key for r in old.rows]
    moved = before[src]
    lift(win, src)
    target = row_point(win, slot)
    move_global(win, target)
    release_global(win, target)
    painted = drag.order_after(before, moved, slot)
    assert _keys(win) == painted
    assert wait_until(lambda: not win.moves.tickets and not win.moves.writer.pending(), 3)
    return old, painted


def test_a_view_begun_before_the_drops_write_never_puts_the_row_back_once_the_writer_is_idle(world):
    """The report's sequence, step by step: the write lands, the writer idles (the settle), and only then the view a
    busy reader began before the write arrives. The row stays where it was dropped; the reader's answer — the store's
    own view, read after — stands. Wrong (before), the settle let the order go and that view put the row back."""
    _seed, win, _writer = world()
    moves, reader = win.moves, win.services.library
    old, painted = _dropped(win)
    reader.hold()                                                     # a busy reader: nothing of its comes yet
    moves._settle.stop()
    moves._settled()                                                  # every write landed: the store's view asked
    win.show_library(old)                                             # the view begun before the write, arriving now
    assert _keys(win) == painted                                      # the row stays where it was dropped
    assert moves.expect is not None and moves._asked is not None
    reader.release()                                                  # the reader answers: read after the write
    assert wait_until(lambda: moves.expect is None, 5)
    assert reader.answered()[0] >= 1 and win.page_widgets["current"].view_model is reader.answered()[1]
    assert _keys(win) == painted                                      # the store's own view: the row is there


def test_a_drop_on_a_slow_reader_shows_one_place_on_every_view_after_it(world, monkeypatch):
    """End to end, nothing held by hand, as in the report: the reader as slow as a laptop's during a Generate (each
    build longer than `settle-ms`), and a change that came in under the hand (a sync, a Generate's numbers) — so the
    drop's release starts a build from the store as it was before the write. Every view the page takes after the drop
    shows the row at its new place. Wrong (before), that build came after the settle and showed the row back at its old
    place, and the next one forward again."""
    from app.services import library_reader
    real_build = library_reader.view_rows.build

    def slow(*args, **kw):
        time.sleep(0.45)
        return real_build(*args, **kw)
    seed, win, _writer = world()
    reader = win.services.library
    monkeypatch.setattr(library_reader.view_rows, "build", slow)
    page = win.page_widgets["current"]
    before = _keys(win)
    far = rows_of(win)[-1].episodes[0]
    shown = []
    real = page.set_view

    def set_view(view):
        shown.append([r.key for r in view.rows])
        return real(view)
    page.set_view = set_view
    try:
        moved = before[6]
        lift(win, 6)
        target = row_point(win, 1)
        move_global(win, target)
        seed.library.commit(items=[{"id": far.id, "watched": 0 if far.watched else 1}])     # in under the hand
        assert wait_until(lambda: reader._held_dirty, 3)
        release_global(win, target)
        assert _keys(win) == drag.order_after(before, moved, 1)
        assert wait_until(lambda: win.moves.expect is None, 8)
        assert wait_until(lambda: len(shown) >= 2, 3)                 # the drop's, then the store's own
        QTest.qWait(1200)                                             # and nothing late after it, either
        assert all(keys.index(moved) == 1 for keys in shown), [keys.index(moved) for keys in shown]
    finally:
        page.set_view = real


def test_a_reader_that_never_answers_lets_the_order_go_after_the_wait(world):
    """A store that can't be read for long (the reader never answers the ask): the window's order goes after
    `answer-ms` all the same, and the newest view stands — never an order held for ever."""
    _seed, win, _writer = world()
    moves, reader = win.moves, win.services.library
    try:
        old, _painted = _dropped(win)
        reader.hold()
        QTest.qWait(250)                                              # whatever it had begun has come
        moves._unanswered.setInterval(80)
        moves._settle.stop()
        moves._settled()
        moves._unanswered.start()
        assert moves.expect is not None and moves._asked is not None
        moves.held = old                                              # the newest view the window holds
        assert wait_until(lambda: moves.expect is None, 3)
        assert moves._asked is None and _keys(win) == [r.key for r in old.rows]
    finally:
        reader.release()


def test_the_stores_answer_arriving_under_the_next_drag_stands_when_that_drag_is_let_go(world):
    """The answer can come while the next drag runs: held under the hand (E6), and a cancel shows it as the store's own
    view — the order let go, never left waiting for an answer that already came."""
    _seed, win, _writer = world()
    moves, reader = win.moves, win.services.library
    _old, painted = _dropped(win)
    reader.hold()
    moves._settle.stop()
    moves._settled()
    asked = moves._asked
    QTest.qWait(80)                                                   # (a press right after a drop is swallowed)
    lift(win, 4)
    reader.release()                                                  # (the drag's own hold, let go by hand here)
    assert wait_until(lambda: moves.held is not None and reader.answered()[0] >= asked, 5)
    assert _keys(win) == painted                                      # nothing changes under the hand
    moves.cancel()
    assert moves.expect is None and moves._asked is None
    assert win.page_widgets["current"].view_model is reader.answered()[1] and _keys(win) == painted


def test_a_later_view_held_after_the_answer_under_the_next_drag_lets_the_order_go_at_its_cancel(world):
    """The adversary's S: the answer came under the hand, then a later view (read after it too) took its place in the
    hold. The cancel shows that later view as the store's own and lets the order go — never left waiting `answer-ms`
    for an answer that already went by (meanwhile a view with other rows would be held back, not shown)."""
    _seed, win, _writer = world()
    moves, reader = win.moves, win.services.library
    _old, painted = _dropped(win)
    reader.hold()
    moves._settle.stop()
    moves._settled()
    QTest.qWait(80)
    lift(win, 4)
    reader.release()
    assert wait_until(lambda: moves._answer_passed, 5)                # the answer, held under the hand
    answer = reader.answered()[1]
    later = answer._replace(subline=answer.subline)                   # a later look's view (another object)
    win.show_library(later)
    assert moves.held is later
    moves.cancel()
    assert moves.expect is None and moves._asked is None and not moves._answer_passed
    assert win.page_widgets["current"].view_model is later and _keys(win) == painted


def test_an_answer_held_under_a_drag_that_ends_without_a_view_lets_the_order_go_at_the_next_view(world):
    """The adversary's second S: a drag can end with no view of its own (a join drop, an item from the tray or the Goal
    sheet: `_end` alone). The answer held under it counts for every view after it: the next one the reader sends
    lets the order go — never `answer-ms` of other-row views held back."""
    seed, win, _writer = world()
    moves, reader = win.moves, win.services.library
    _old, painted = _dropped(win)
    reader.hold()
    moves._settle.stop()
    moves._settled()
    QTest.qWait(80)
    lift(win, 4)
    reader.release()
    assert wait_until(lambda: moves._answer_passed, 5)
    moves._end(moves.running)                                         # the drag ends as a join or tray drop does
    assert moves.expect is not None
    far = rows_of(win)[-1].episodes[0]
    seed.library.commit(items=[{"id": far.id, "watched": 0 if far.watched else 1}])     # the reader's next view
    assert wait_until(lambda: moves.expect is None, 3) and _keys(win) == painted


def test_a_view_published_before_the_answer_never_lets_the_order_go_though_it_arrives_after(world):
    """Views reach the window in the order the reader published them, but the reader may have answered by the time an
    older one is taken in: only the answering view itself lets the order go — never one published before it, which
    can still predate the write."""
    _seed, win, _writer = world()
    moves, reader = win.moves, win.services.library
    old, painted = _dropped(win)
    reader.hold()
    moves._settle.stop()
    moves._settled()
    asked = moves._asked
    reader.release()
    end = time.monotonic() + 5
    while reader.answered()[0] < asked and time.monotonic() < end:    # answered, nothing taken in by the window yet
        time.sleep(0.01)
    assert reader.answered()[0] >= asked
    win.show_library(old)                                             # published before the answer, taken in after it
    assert moves.expect is not None and _keys(win) == painted
    assert wait_until(lambda: moves.expect is None, 5) and _keys(win) == painted


def test_a_let_go_while_the_writer_still_waits_asks_only_once_it_landed(world):
    """An Undo or a reread lets the order go while a write still waits (a busy store): the ask waits for the writer —
    a view read now would predate that write and put the row back."""
    _seed, win, writer = world()
    moves = win.moves
    before = _keys(win)
    writer.stuck = True
    moves.menu_pick(rows_of(win)[5], "up-next")                       # ⋯ Up next: a move, its write waiting
    painted = _keys(win)
    assert painted != before and writer.pending()
    moves._let_go()
    assert moves._asked is None and moves.expect is not None
    QTest.qWait(400)
    assert _keys(win) == painted                                      # nothing read before the write is shown
    writer.free()
    assert wait_until(lambda: moves.expect is None, 5) and _keys(win) == painted


def test_a_new_drop_while_the_last_ask_waits_is_never_let_go_by_that_older_answer(world):
    """The next move painted while the last move's ask is out: that ask was taken before the new write, so its answer
    lets nothing go — the new order stands till its own write lands and the store's view after it comes."""
    _seed, win, writer = world()
    moves, reader = win.moves, win.services.library
    _dropped(win)
    reader.hold()
    moves._settle.stop()
    moves._settled()
    assert moves._asked is not None
    writer.stuck = True
    moves.menu_pick(rows_of(win)[5], "up-next")                       # the next move, its write waiting
    painted = _keys(win)
    assert moves._asked is None
    reader.release()                                                  # the older ask answered: no write of the new move
    QTest.qWait(400)
    assert moves.expect is not None and _keys(win) == painted
    writer.free()
    assert wait_until(lambda: moves.expect is None, 5) and _keys(win) == painted


def test_a_refused_command_lets_the_order_go_at_once(world):
    """A command the writer refuses wrote nothing: the store's view stands at once (no ask to wait for)."""
    _seed, win, writer = world()
    moves = win.moves
    before = _keys(win)
    writer.writable = False                                           # the writer takes nothing (the press passed)
    writer.can_write = lambda: True
    moves.nudge(rows_of(win)[4], -1)                                  # painted ahead, then refused
    assert moves.expect is None and moves._asked is None and _keys(win) == before
