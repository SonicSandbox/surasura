"""The drag in the window, the wells, Undo, Done and the finish toast (W3.1a §2, `app/qt/drag.py`; A2 #9–#21, 06 E4–E6,
E21; the intent keeper's B1, S3, L4, L5, L7; the adversary's AD-5, AD-7, AD-14), on the window's seed (Japanese titles)
through the stand-in store — and, where the store's own answers matter (a busy store, an Undo after an outside change,
the numbers at the drop, the Finished toast's choice, files from Explorer, the quit), on a real migrated store with the
real writer and numbers.

What a wrong answer would cost a learner:
  * a drag begun on a stone marking that episode watched, or one begun on a row opening it (B1);
  * a row dropped somewhere else than where the hand left it, or flashing back to its old place before the store
    catches up (04 §4.5's optimistic move);
  * a drop on Finished that can't be undone, a Finished choice greyed out, a split's first part or hato's mix finished
    by accident (the well must stay unlit);
  * a drag on a library that can't be saved accepted, then lost (E4), a move lost while the store is busy (E5), a row
    jumping under the hand because a sync landed (E6), an Undo that erases work done since (E21);
  * the numbers on the moved rows lagging the drop (RP-6: 50 ms);
  * every row repainted on a drop or a hover (S19).
"""
import os
import threading
import time
from collections import namedtuple

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QMimeData, QObject, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent, QRegion
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import drag, frame, freeze, motion, rows, shell, stones, strings
from app.services import library_reader
from app.services import moves as moves_module
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until

LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton


# --- a writer that records (the seed's stand-in store takes no writes) --------------------------------------------- #
class Change:
    def __init__(self, op, ids, **kw):
        self.op, self.ids, self.kw = op, list(ids), kw
        self.kind = op


class FakeWriter:
    """The writer's API as the window calls it (`moves.Writer`): every command recorded, saved at once (its callbacks on
    a thread of their own, as the real one's) — and, with `apply`, written into the stand-in library, so the reader's
    next view holds it."""

    def __init__(self, library=None, apply=True):
        self.library, self.apply = library, apply
        self.calls = []
        self.writable = True
        self.why = "busy"
        self.words = strings.MOVE_WORDS
        self.numbers = None
        self.held = 0
        self.undone = []
        self.saved = []
        self.stuck = False                            # a busy store: commands wait (pending) until `free()`
        self.nothing = set()                          # ops that land as nothing to change (the store's None)
        self._waiting = []
        self.on_saved = self.on_saving = self.on_reread = self.on_note = self.on_undone = None
        self.started = self.replayed = 0
        self.finished = []

    # the window's side
    def start(self):
        self.started += 1
        return self

    def replay(self):
        self.replayed += 1
        return self.writable

    def can_write(self):
        return self.writable

    def reason(self):
        return None if self.writable else self.why

    def hold(self):
        self.held += 1

    def release(self):
        self.held -= 1

    def pending(self):
        return len(self._waiting)

    def can_undo(self):
        return bool(self.saved)

    def finish(self, deadline):
        self.finished.append(deadline)
        return True

    def _put(self, op, ids, label, **kw):
        if not self.writable:
            return None
        self.calls.append((op, list(ids), kw))
        change = Change(op, ids, **kw)
        if self.stuck:
            self._waiting.append((change, label))
        else:
            self._land(change, label)
        return len(self.calls)

    def free(self):
        self.stuck = False
        waiting, self._waiting = self._waiting, []
        for change, label in waiting:
            self._land(change, label)

    def _land(self, change, label):
        if change.op in self.nothing:
            threading.Thread(target=self.on_reread, daemon=True).start()
            return
        if self.apply and self.library is not None:
            self._write(change)
        self.saved.append(change)
        threading.Thread(target=self.on_saved, args=(change, label), daemon=True).start()

    def move(self, ids, tier, before_id=None, after_id=None, near=(), label=None, end=False):
        return self._put("move", ids, label, tier=tier, before_id=before_id, after_id=after_id, near=list(near),
                         end=end)

    def nudge(self, ids, direction, label=None):
        return self._put("nudge", ids, label, direction=direction)

    def set_tier(self, ids, tier, label=None):
        return self._put("set_tier", ids, label, tier=tier)

    def set_finished(self, ids, keep_cards=True, label=None, **kw):
        return self._put("finish", ids, label, keep_cards=keep_cards, **kw)

    def set_watched(self, ids, on=True, label=None):
        return self._put("set_watched", ids, label, on=on)

    def insert_at(self, paths, tier, before_id=None, after_id=None, near=(), label=None):
        return self._put("insert_at", [], label, files=list(paths), tier=tier, before_id=before_id, after_id=after_id,
                         near=list(near))

    def undo(self, change=None, label=None):
        self.calls.append(("undo", [], {"change": change}))
        self.undone.append(change)
        threading.Thread(target=self.on_undone, args=(change, label), daemon=True).start()
        return len(self.calls)

    # the stand-in library, written as the store would
    def _write(self, change):
        lib, kw = self.library, change.kw
        items = {r["id"]: r for r in lib.items()}
        if change.op == "move":
            tier = kw["tier"]
            rest = sorted((r for r in items.values() if r["tier"] == tier and r["id"] not in change.ids),
                          key=lambda r: (r["ord"], r["id"]))
            anchor = kw["after_id"] if kw.get("end") is False or kw.get("end") is None else None
            if kw.get("end"):
                lo, hi = (rest[-1]["ord"] if rest else 0.0), (rest[-1]["ord"] if rest else 0.0) + 1024
            elif kw["before_id"] is not None:
                a = next(i for i, r in enumerate(rest) if r["id"] == kw["before_id"])
                hi = rest[a]["ord"]
                lo = rest[a - 1]["ord"] if a > 0 else hi - 1024
            elif anchor is not None:
                a = next(i for i, r in enumerate(rest) if r["id"] == anchor)
                lo = rest[a]["ord"]
                hi = rest[a + 1]["ord"] if a + 1 < len(rest) else lo + 1024
            else:
                hi = rest[0]["ord"] if rest else 1024.0
                lo = hi - 1024
            step = (hi - lo) / (len(change.ids) + 1)
            lib.commit(items=[{"id": i, "tier": tier, "ord": lo + step * (k + 1)} for k, i in enumerate(change.ids)],
                       order=True)
        elif change.op == "set_tier":
            lib.commit(items=[{"id": i, "tier": kw["tier"], "graduated_at": "2026-10-15T10:00:00Z"}
                              for i in change.ids], order=True)
        elif change.op == "set_watched":
            lib.commit(items=[{"id": i, "watched": 1 if kw["on"] else 0} for i in change.ids])


def open_window(qapp, seed, writer, size=(1280, 900)):
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    services = shell.Services(library=reader, writer=writer)
    win = shell.open_window(qapp, services)
    win.resize(*size)
    win.move(40, 30)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading, 10)
    for _ in range(50):
        QApplication.processEvents()
    return win, services


@pytest.fixture(autouse=True)
def _stones_sheet(qapp):
    """The stones' sheet drawn before the window opens (as test_current's): stones are hit-tested only once it is
    there (L4)."""
    key = stones._key(1.0, "M")
    if key not in stones._SHEETS:
        stones._landed(key, stones.build(*key))


@pytest.fixture
def world(qapp):
    made = []

    def make(files=window_seed.SMALL, apply=True, size=(1280, 900), **kw):
        seed = window_seed.build(files=files, **kw)
        writer = FakeWriter(seed.library, apply=apply)
        win, services = open_window(qapp, seed, writer, size)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def lst_of(win):
    return win.page_widgets["current"].list


def rows_of(win):
    return win.page_widgets["current"].view_model.rows


def index_of(lst, key):
    return next(i for i, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == key)


def title_point(lst, i):
    """A point on row `i`'s title (a part that opens the row on a click, and lifts it on a drag)."""
    entry = lst.model().entries[i]
    rect = lst.visualRect(lst.model().index(i, 0))
    if entry[0] == rows.HERO:
        g = lst.delegate._hero_geometry(entry[1], rect, entry[2])
        return g["title"].center()
    g = lst.delegate.line_geometry(entry[1], lst.delegate.slab_of(rect))
    return QPoint(g["main"].left() + 20, g["main"].center().y())


def part_rect(lst, i, name):
    entry = lst.model().entries[i]
    return next(p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))) if p[0] == name)


def mouse(widget, kind, pos, button=LEFT, buttons=LEFT, modifiers=Qt.KeyboardModifier.NoModifier):
    pos = QPointF(pos)
    QApplication.sendEvent(widget, QMouseEvent(kind, pos, QPointF(widget.mapToGlobal(pos)), button, buttons,
                                               modifiers))


def press(lst, pos):
    mouse(lst.viewport(), QEvent.Type.MouseButtonPress, pos, LEFT, LEFT)


def move(lst, pos, buttons=LEFT):
    mouse(lst.viewport(), QEvent.Type.MouseMove, pos, NONE, buttons)


def release(lst, pos):
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, pos, LEFT, NONE)


def move_global(win, gpos, buttons=LEFT):
    w = win.centralWidget()
    mouse(w, QEvent.Type.MouseMove, w.mapFromGlobal(gpos), NONE, buttons)


def release_global(win, gpos):
    w = win.centralWidget()
    mouse(w, QEvent.Type.MouseButtonRelease, w.mapFromGlobal(gpos), LEFT, NONE)


def lift(win, i):
    """Press on row `i`'s title and travel 6 px: the drag has it."""
    lst = lst_of(win)
    at = title_point(lst, i)
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is not None
    return at


def row_point(win, i, lower=False):
    """The global point over row `i`'s upper (or lower) half."""
    lst = lst_of(win)
    rect = lst.visualRect(lst.model().index(i, 0))
    y = rect.top() + rect.height() // 4 if not lower else rect.bottom() - rect.height() // 4
    return lst.viewport().mapToGlobal(QPoint(rect.center().x(), y))


def well_point(win, name):
    dock = win.dock
    r = dock.well_rects()[name]
    return dock.mapToGlobal(r.center().toPoint())


def settle(ms=60):
    QTest.qWait(ms)
    QApplication.processEvents()


def calls(writer, op=None):
    return [c for c in writer.calls if op is None or c[0] == op]


# --- B1: a press acts on its release, a drag never clicks --------------------------------------------------------- #
def test_B1_a_click_on_a_stone_is_a_done_on_release_and_a_drag_from_it_never_marks_it_watched(world):
    seed, win, writer = world()
    lst = lst_of(win)
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and part_rect(lst, n, "stone"))
    stone = part_rect(lst, i, "stone")
    press(lst, stone[1].center())
    assert calls(writer, "set_watched") == []                        # a press alone acts on nothing
    release(lst, stone[1].center())
    assert calls(writer, "set_watched") and calls(writer, "set_watched")[0][1] == [stone[3].id]
    settle()
    writer.calls.clear()
    stone = part_rect(lst, i, "stone")
    press(lst, stone[1].center())
    move(lst, stone[1].center() + QPoint(theme.MOTION["drag-start-px"], 0))
    assert win.moves.running is not None                              # the press is the drag's now
    win.moves.cancel()
    release(lst, stone[1].center())
    assert calls(writer, "set_watched") == []                         # never marked watched


def test_B1_a_click_on_a_row_opens_it_on_release_and_a_drag_from_it_never_opens_it(world):
    seed, win, writer = world()
    lst = lst_of(win)
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    at = title_point(lst, i)
    press(lst, at)
    assert lst.model().open_key is None
    release(lst, at)
    assert lst.model().open_key == lst.model().entries[i][1].key
    lst.toggle(lst.model().index(i, 0))
    assert lst.model().open_key is None
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"] - 1))       # under the threshold: still a click
    assert win.moves.running is None
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is not None
    win.moves.cancel()
    release(lst, at)
    assert lst.model().open_key is None and calls(writer) == []


def test_a_release_over_another_part_does_nothing(world):
    seed, win, writer = world()
    lst = lst_of(win)
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and part_rect(lst, n, "stone"))
    press(lst, part_rect(lst, i, "stone")[1].center())
    release(lst, title_point(lst, i))
    assert calls(writer) == [] and lst.model().open_key is None


# --- the lift: ghost, slot, parting, wells, toasts hidden, the holds --------------------------------------------- #
def test_a_lift_shows_the_ghost_raises_the_wells_hides_the_toasts_and_holds_the_writer_and_reader(world):
    seed, win, writer = world()
    lst = lst_of(win)
    win.toasts.show("…")
    reader = win.services.library
    lift(win, 4)
    g = win.moves.ghost
    assert g.isVisible() and g.isWindow() and g.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert g.pix is not None and not g.pix.isNull() and g.alpha == theme.DRAG["ghost-alpha"]
    assert win.dock.wells == ("soon", "goal", "finished")
    assert win.toasts.dragging and not win.toasts.card.isVisible()
    assert writer.held == 1 and reader._hold.is_set()
    assert lst.parting is not None and lst.parting.src == 4 and lst.parting.slot == 4
    win.moves.cancel()
    assert writer.held == 0 and not reader._hold.is_set() and not win.toasts.dragging
    assert lst.parting is None and not g.isVisible()


def test_the_rows_between_part_by_the_slots_height_and_the_slot_travels(world):
    seed, win, writer = world()
    lst = lst_of(win)
    lift(win, 6)
    move_global(win, row_point(win, 3))                               # over row 3's upper half: before it
    p = lst.parting
    assert p.slot == 3
    h = p.h
    assert [p.offset(r) for r in range(2, 8)] == [0, h, h, h, 0, 0]   # 3, 4, 5 make room; 6 left its place
    move_global(win, row_point(win, 8, lower=True))                   # past its place: below row 8
    assert p.slot == 8
    assert [p.offset(r) for r in range(5, 10)] == [0, 0, -h, -h, 0]
    assert p.slot_y is not None
    win.moves.cancel()


def test_over_a_well_the_ghost_fades_and_the_well_lights(world):
    seed, win, writer = world()
    lift(win, 4)
    move_global(win, well_point(win, "goal"))
    assert win.dock.lit == "goal" and win.moves.ghost.alpha == theme.DRAG["ghost-alpha-well"]
    move_global(win, row_point(win, 2))
    assert win.dock.lit is None and win.moves.ghost.alpha == theme.DRAG["ghost-alpha"]
    win.moves.cancel()


# --- the drop in the list (A2 #9) -------------------------------------------------------------------------------- #
def test_A2_9_a_row_dropped_onto_row_2_is_second_at_once_and_the_writer_places_it_after_the_row_before(world):
    seed, win, writer = world()
    lst = lst_of(win)
    before = [r.key for r in rows_of(win)]
    moved = rows_of(win)[6]
    lift(win, 6)
    target = row_point(win, 1)                                        # row 2's upper half: between Up Next and it
    move_global(win, target)
    release_global(win, target)
    shown = [e[1].key for e in lst.model().entries]
    assert shown[1] == moved.key and shown == drag.order_after(before, moved.key, 1)   # at once, before any save
    hero = rows_of(win)[0]
    op = calls(writer, "move")[0]
    assert op[1] == drag.ids_of(moved) and op[2]["tier"] == hero.tier
    assert op[2]["after_id"] == hero.episodes[-1].id and op[2]["before_id"] is None
    assert op[2]["near"] and op[2]["near"][0][1] == "before"
    assert win.toasts.card.message == strings.DRAG_PLACED_MINES.format(title=moved.title, n=2)
    assert writer.held == 0
    assert wait_until(lambda: win.moves.expect is None, 3)            # the store caught up: its view stands
    assert [r.key for r in rows_of(win)][1] == moved.key


def test_a_drop_above_up_next_makes_it_up_next(world):
    seed, win, writer = world()
    moved = rows_of(win)[3]
    hero = rows_of(win)[0]
    lift(win, 3)
    target = row_point(win, 0)
    move_global(win, target)
    release_global(win, target)
    op = calls(writer, "move")[0]
    assert op[2]["before_id"] == hero.episodes[0].id and op[2]["after_id"] is None
    assert rows_of(win)[0].key == moved.key
    assert win.toasts.card.message == strings.DRAG_UP_NEXT.format(title=moved.title)


def test_a_drop_back_on_its_own_place_writes_nothing(world):
    seed, win, writer = world()
    lift(win, 5)
    target = row_point(win, 5)
    move_global(win, target)
    release_global(win, target)
    assert calls(writer) == [] and win.moves.running is None


def test_placement_maps_every_drop_in_the_list(world):
    """The drop → writer mapping (pure): after the row before (its tier), the very top before the first row, near =
    the painted neighbours in that tier, nearest first, never the anchor itself."""
    seed, win, writer = world()
    rs = rows_of(win)
    tier, before, after, near = drag.placement(rs, 6, 0)
    assert (tier, before, after) == (rs[0].tier, rs[0].episodes[0].id, None)
    assert near[0] == (rs[1].episodes[0].id, "before")
    tier, before, after, near = drag.placement(rs, 6, 3)              # without row 6: after rs[2]
    assert (tier, before, after) == (rs[2].tier, None, rs[2].episodes[-1].id)
    assert near[:2] == [(rs[3].episodes[0].id, "before"), (rs[1].episodes[-1].id, "after")]
    first_soon = next(i for i, r in enumerate(rs) if r.tier == "soon")
    tier, before, after, _near = drag.placement(rs, 2, first_soon - 1)   # just after NOW's last row (2 left above)
    assert tier == "now" and after == rs[first_soon - 1].episodes[-1].id
    tier, before, after, _near = drag.placement(rs, 2, first_soon)      # after Soon's first row
    assert tier == "soon" and after == rs[first_soon].episodes[-1].id
    tier, before, after, near = drag.placement(rs, None, len(rs))     # from outside, at the end
    assert after == rs[-1].episodes[-1].id and all(n[0] != after for n in near)


# --- the wells and the Finished tab (A2 #15–#21) --------------------------------------------------------------------- #
def test_A2_20_a_drop_on_soon_moves_it_to_the_top_of_soon(world):
    seed, win, writer = world()
    moved = rows_of(win)[4]
    lift(win, 4)
    at = well_point(win, "soon")
    move_global(win, at)
    release_global(win, at)
    op = calls(writer, "move")[0]
    assert op[2]["tier"] == "soon" and op[2]["before_id"] is None and op[2]["after_id"] is None and not op[2]["end"]
    rs = rows_of(win)
    place = next(i for i, r in enumerate(rs) if r.key == moved.key)
    assert rs[place].tier == "soon" and all(r.tier == "now" for r in rs[:place])
    files = sum(r.n_files for r in rs[:place])
    assert win.toasts.card.message == strings.DRAG_SOON.format(title=moved.title, n=place + 1, files=files)
    assert win.dock.wells == () or wait_until(lambda: win.dock.wells == (), 2)        # A2 #18: they fold back


def test_A2_19_a_drop_on_goal_sends_it_to_goals_end_and_leaves_current_at_once(world):
    seed, win, writer = world()
    moved = rows_of(win)[5]
    goal_files = win.page_widgets["current"].view_model.goal.files
    lift(win, 5)
    at = well_point(win, "goal")
    move_global(win, at)
    release_global(win, at)
    op = calls(writer, "move")[0]
    assert op[2]["tier"] == "goal" and op[2]["end"] is True and op[2]["after_id"] is None
    view = win.page_widgets["current"].view_model
    assert moved.key not in [r.key for r in view.rows]
    assert view.goal.files == goal_files + moved.n_files
    assert win.toasts.card.message == strings.DRAG_GOAL.format(title=moved.title)


def test_A2_17_a_drop_on_finished_finishes_it_with_keep_and_take_out_live(world):
    seed, win, writer = world()
    moved = rows_of(win)[5]
    fin = win.page_widgets["current"].view_model.counts.finished
    lift(win, 5)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    op = calls(writer, "set_tier")[0]
    assert op[1] == drag.ids_of(moved) and op[2]["tier"] == "graduated"
    view = win.page_widgets["current"].view_model
    assert moved.key not in [r.key for r in view.rows] and view.counts.finished == fin + 1
    card = win.toasts.card
    assert card.message == strings.DRAG_FINISHED.format(title=moved.title)
    labels = [b.text() for b in card.buttons if not b.isHidden()]
    assert labels == [strings.TOAST_UNDO, strings.DRAG_KEEP, strings.DRAG_TAKE_OUT]
    assert all(b.isEnabled() for b in card.buttons if not b.isHidden())          # live, never greyed
    settle()
    card.buttons[2].click()                                                         # Take its new cards out
    op = calls(writer, "finish")[0]
    assert op[1] == drag.ids_of(moved) and op[2]["keep_cards"] is False
    assert op[2]["follows"] is writer.saved[0] and writer.saved[0].op == "set_tier"     # the drop's Undo takes both


def test_a_choice_made_while_the_drop_waits_for_a_busy_store_follows_it_once_it_lands(world):
    """(AD-6) *Take its new cards out* pressed before the drop is saved: never given unlinked (its Undo would leave the
    cards out) — it waits for the drop's change and is linked to it."""
    seed, win, writer = world()
    writer.stuck = True
    lift(win, 5)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    settle()
    win.toasts.card.buttons[2].click()
    assert calls(writer, "finish") == []                              # waits for the drop's change
    writer.free()
    assert wait_until(lambda: calls(writer, "finish"), 3)
    op = calls(writer, "finish")[0]
    assert op[2]["keep_cards"] is False and op[2]["follows"] is calls_change(writer, "set_tier")


def test_a_drop_undone_before_it_lands_takes_its_waiting_choice_with_it(world):
    seed, win, writer = world()
    writer.stuck = True
    lift(win, 5)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    settle()
    drop = win.moves.toasted
    win.toasts.card.buttons[2].click()                                # the choice waits for the drop …
    win.moves.undo(drop)                                              # … and the drop is taken back first
    writer.free()
    assert wait_until(lambda: writer.undone, 3)
    settle(150)
    assert calls(writer, "finish") == [] and writer.undone[0].op == "set_tier"
    assert not win.moves.tickets or all(t.change is not None for t in win.moves.tickets)


def test_a_choice_waiting_for_a_drop_that_lands_as_nothing_is_given_on_its_own(world):
    """The drop had nothing to change (the item was in Finished already, an outside program moved it): the cards'
    choice the learner made still lands, unlinked."""
    seed, win, writer = world()
    writer.stuck = True
    lift(win, 5)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    settle()
    win.toasts.card.buttons[2].click()
    writer.nothing = {"set_tier"}
    writer.free()
    assert wait_until(lambda: calls(writer, "finish"), 3)
    op = calls(writer, "finish")[0]
    assert op[2]["keep_cards"] is False and op[2]["follows"] is None


def calls_change(writer, op):
    return next(c for c in writer.saved if c.op == op)


def test_the_finished_toasts_keep_writes_the_choice_to_keep(world):
    seed, win, writer = world()
    lift(win, 5)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    settle()
    win.toasts.card.buttons[1].click()
    assert calls(writer, "finish")[0][2]["keep_cards"] is True


def test_A2_21_the_finished_tab_takes_a_drop_too(world):
    seed, win, writer = world()
    moved = rows_of(win)[5]
    lift(win, 5)
    tab = win.tab_buttons["finished"]
    at = tab.mapToGlobal(tab.rect().center())
    move_global(win, at)
    assert win.moves.running.target == ("tab", "finished")
    release_global(win, at)
    assert calls(writer, "set_tier")[0][1] == drag.ids_of(moved)


def tab_point(win):
    tab = win.tab_buttons["finished"]
    return tab.mapToGlobal(tab.rect().center())


def test_G3_2_the_finished_tab_lights_under_a_drag_and_its_drop_lands_in_finished(world):
    """A running drag swallows hover, so the tab's own hover look never showed: he had no sign the tab takes a drop.
    It lights while the drop would land on it (reduced motion too: the light is a state, not an animation), goes out
    when the hand leaves and when the drop lands, and the drop finishes the item through the writer."""
    seed, win, writer = world()
    tab = win.tab_buttons["finished"]
    moved = rows_of(win)[5]
    fin = win.page_widgets["current"].view_model.counts.finished
    lift(win, 5)
    assert not tab.drop_lit
    move_global(win, tab_point(win))
    assert tab.drop_lit
    move_global(win, row_point(win, 2))
    assert not tab.drop_lit                                           # the hand left: out
    move_global(win, tab_point(win))
    assert tab.drop_lit
    release_global(win, tab_point(win))
    assert not tab.drop_lit                                           # the drop landed: out
    op = calls(writer, "set_tier")[0]
    assert op[1] == drag.ids_of(moved) and op[2]["tier"] == "graduated"
    view = win.page_widgets["current"].view_model
    assert moved.key not in [r.key for r in view.rows] and view.counts.finished == fin + 1


def test_G3_2_the_finished_tab_goes_out_on_esc_and_never_lights_for_hatos_mix(world):
    """Esc puts everything back, the tab's light too; hato's mix never finishes, so the tab stays dark as the well does
    (a light would promise a drop that goes back)."""
    seed, win, writer = world()
    tab = win.tab_buttons["finished"]
    lift(win, 5)
    move_global(win, tab_point(win))
    assert tab.drop_lit
    QApplication.sendEvent(lst_of(win), QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                                  Qt.KeyboardModifier.NoModifier))
    assert win.moves.running is None and not tab.drop_lit and calls(writer) == []
    QTest.qWait(theme.MOTION["click-swallow-after-drag"] + 30)
    assert drag.is_mix(rows_of(win)[0])
    lift(win, 0)
    move_global(win, tab_point(win))
    assert win.moves.running.target == ("tab", "finished") and not tab.drop_lit
    win.moves.cancel()


def test_a_splits_first_part_leaves_the_finished_well_unlit_and_its_drop_goes_back(world):
    seed, win, writer = world()
    rs = rows_of(win)
    i = next(n for n, r in enumerate(rs) if drag.split_first(rs, r))
    lift(win, i)
    assert win.dock.unlit_tip("finished") == strings.WELL_UNLIT_SPLIT
    at = well_point(win, "finished")
    move_global(win, at)
    assert win.dock.lit is None                                       # it never lights
    release_global(win, at)
    assert calls(writer) == [] and [r.key for r in rows_of(win)] == [r.key for r in rs]
    assert win.bar_line.full() == strings.WELL_UNLIT_SPLIT


def test_hatos_mix_leaves_the_finished_well_unlit(world):
    seed, win, writer = world()
    rs = rows_of(win)
    assert drag.is_mix(rs[0])                                         # the seed's Up Next comes from hato
    lift(win, 0)
    assert win.dock.unlit_tip("finished") == strings.WELL_UNLIT_MIX
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    assert calls(writer) == []


# --- cancel: Esc, a pointer lost, the window let go; the click after ------------------------------------------- #
@pytest.mark.parametrize("how", ["esc", "lost", "deactivate"])
def test_a_cancelled_drag_puts_everything_back_and_writes_nothing(world, how):
    seed, win, writer = world()
    lst = lst_of(win)
    before = [e[1].key for e in lst.model().entries]
    lift(win, 6)
    move_global(win, row_point(win, 2))
    if how == "esc":
        QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    elif how == "lost":
        move_global(win, row_point(win, 2), buttons=NONE)            # the button came up outside the window
    else:
        QApplication.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))
    assert win.moves.running is None and lst.parting is None
    assert [e[1].key for e in lst.model().entries] == before
    assert calls(writer) == [] and writer.held == 0 and win.dock.wells in ((), ("soon", "goal", "finished"))
    assert not win.moves.ghost.isVisible()


def test_the_click_right_after_a_drag_is_swallowed(world):
    seed, win, writer = world()
    lst = lst_of(win)
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    i = 3
    at = title_point(lst, i)
    press(lst, at)                                                    # within click-swallow-after-drag
    release(lst, at)
    assert lst.model().open_key is None
    QTest.qWait(theme.MOTION["click-swallow-after-drag"] + 30)
    press(lst, at)
    release(lst, at)
    assert lst.model().open_key == lst.model().entries[i][1].key


# --- E4: a store that can't be written refuses at the press ------------------------------------------------------ #
def test_E4_a_read_only_store_refuses_the_drag_and_says_why(world):
    seed, win, writer = world()
    writer.writable, writer.why = False, "damaged"
    lst = lst_of(win)
    at = title_point(lst, 4)
    press(lst, at)
    move(lst, at + QPoint(0, 10))
    assert win.moves.running is None and writer.held == 0
    assert win.bar_line.full() == strings.DRAG_REFUSED.format(reason=strings.READ_ONLY_REASONS["damaged"])
    release(lst, at)
    assert lst.model().open_key is None                               # the attempt was no click either
    win.moves.done(rows_of(win)[2], rows_of(win)[2].episodes[0])      # a Done refused too
    assert calls(writer) == []
    entries = win.moves.menu_entries(rows_of(win)[4])
    assert [e[3] for e in entries if e[0] != "journey"] == [False] * (len(entries) - 1)
    assert all(e[2] == strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS["damaged"])
               for e in entries if e[0] != "journey")


# --- E6: an outside change during a drag waits for the drop ------------------------------------------------------- #
def test_E6_an_outside_change_during_a_drag_waits_for_the_drop(world):
    seed, win, writer = world()
    lst = lst_of(win)
    row = rows_of(win)[3]
    lift(win, 6)
    seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1}])        # a sync lands mid-drag
    QTest.qWait(200)
    assert not rows_of(win)[3].episodes[0].watched                                 # never under the hand
    win.moves.cancel()
    assert wait_until(lambda: rows_of(win)[3].episodes[0].watched, 3)              # applied at the drop


def test_E6_the_dragged_item_removed_lets_the_drag_go(world):
    seed, win, writer = world()
    row = rows_of(win)[6]
    lift(win, 6)
    seed.library.commit(gone=[("item", e.id) for e in row.episodes])
    assert wait_until(lambda: win.moves.running is None, 3)
    assert win.bar_line.full() == strings.DRAG_GONE and calls(writer) == []


# --- the expectation: no flash back ------------------------------------------------------------------------------- #
def test_a_view_of_the_old_order_after_a_drop_is_shown_in_the_drops_order(world):
    seed, win, writer = world(apply=False)                            # the store never moves: only the window did
    lst = lst_of(win)
    old = win.page_widgets["current"].view_model
    moved = old.rows[6]
    lift(win, 6)
    target = row_point(win, 1)
    move_global(win, target)
    release_global(win, target)
    win.show_library(old)                                             # the reader's view, before the write landed
    assert [r.key for r in rows_of(win)][1] == moved.key              # no flash back
    numbers = old._replace(rows=tuple(r._replace(n_new=777) if r.key == moved.key else r for r in old.rows))
    win.show_library(numbers)                                         # fresh numbers flow in, in the drop's order
    assert rows_of(win)[1].n_new == 777
    assert wait_until(lambda: win.moves.expect is None, 3)            # settled: the reader's view stands
    win.show_library(old)
    assert [r.key for r in rows_of(win)] == [r.key for r in old.rows]


# --- Undo (A2 #12): the toast's, Ctrl+Z, depth on the writer -------------------------------------------------------- #
def test_the_toasts_undo_undoes_its_own_change(world):
    seed, win, writer = world()
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    assert wait_until(lambda: writer.saved and win.moves.tickets == [], 3)
    change = writer.saved[0]
    win.toasts.card.buttons[0].click()
    assert writer.undone == [change]


def test_an_undo_asked_before_the_save_runs_when_it_lands(world):
    seed, win, writer = world()
    writer.stuck = True
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    win.toasts.card.buttons[0].click()
    assert writer.undone == []
    writer.free()
    assert wait_until(lambda: writer.undone == [writer.saved[0]], 3)


def test_ctrl_z_undoes_the_newest_change(world):
    seed, win, writer = world()
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    assert wait_until(lambda: writer.saved, 3)
    settle(80)
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert writer.undone == [None]                                    # None: the newest, as the writer reaches it


# --- Reduced motion -------------------------------------------------------------------------------------------------- #
def test_reduced_motion_jumps_the_parting_and_the_ghost_never_glides(world):
    seed, win, writer = world()
    freeze.set_frozen(False)
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("reduced")
    try:
        lst = lst_of(win)
        lift(win, 6)
        move_global(win, row_point(win, 3))
        p = lst.parting
        assert p.springs == {} and p.offset(4) == p.h                 # at rest at once
        target = row_point(win, 3)
        release_global(win, target)
        assert not win.moves.ghost.isVisible() and lst.landing is None
    finally:
        mode.set_setting(was)


def _full_motion():
    """Motion on whatever Windows says (GitHub's runners turn Windows' animations off: *Follow* reads as reduced)."""
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("full")
    return lambda: mode.set_setting(was)


def test_with_motion_the_ghost_glides_onto_the_rows_place_and_its_slot_shows_meanwhile(world):
    seed, win, writer = world()
    freeze.set_frozen(False)
    restore = _full_motion()
    clock = motion.clock()
    try:
        lst = lst_of(win)
        moved = rows_of(win)[6]
        lift(win, 6)
        target = row_point(win, 2)
        move_global(win, target)
        clock.use_test_time()                     # the glide moves only when the test says so (a slow runner's
        release_global(win, target)               # event waits can outlast its 160 ms)
        assert lst.landing == moved.key and win.moves.ghost.isVisible()
        clock.advance(theme.MOTION["ghost-glide"] + 50)
        assert lst.landing is None and not win.moves.ghost.isVisible()
    finally:
        clock.use_real_time()
        restore()


def test_a_lift_during_the_last_drops_glide_keeps_its_ghost_shown_for_the_whole_drag(world):
    """Round 2 (the Haiku time lens): the last drop's glide (or a well's fade) ends by hiding the ghost — a row lifted
    before it ended must not lose its ghost mid-drag."""
    seed, win, writer = world()
    freeze.set_frozen(False)
    restore = _full_motion()
    clock = motion.clock()
    try:
        lift(win, 6)
        target = row_point(win, 2)
        move_global(win, target)
        clock.use_test_time()                                         # the glide moves only when the test says so
        release_global(win, target)
        QTest.qWait(theme.MOTION["click-swallow-after-drag"] + 20)   # past the click swallowed after a drag,
        assert win.moves.ghost.isVisible()                            # still inside the glide
        lift(win, 4)
        clock.advance(theme.MOTION["ghost-glide"] + 100)              # the old glide's end has passed
        assert win.moves.running is not None and win.moves.ghost.isVisible()
        win.moves.cancel()
    finally:
        clock.use_real_time()
        restore()


# --- speed: a drop repaints the rows it moved; S3 at 2,000 files -------------------------------------------------- #
def _paint_spy(lst, monkeypatch):
    painted = []
    real = lst.delegate.paint

    def spy(p, option, index):
        painted.append(index.row())
        return real(p, option, index)
    monkeypatch.setattr(lst.delegate, "paint", spy)
    return painted


def _under_toast(win, lst):
    """The rows the drop's toast (and its shadow) rises over: a translucent card repaints what lies beneath it — the
    toast's cost, not the drop's."""
    host = win.toasts
    under = set()
    for w in (host.card, host.shadow):
        if not w.isVisible():
            continue
        box = w.geometry()
        box.moveTopLeft(lst.viewport().mapFrom(w.parentWidget(), box.topLeft()))
        model = lst.model()
        under |= {i for i in range(model.rowCount()) if lst.visualRect(model.index(i, 0)).intersects(box)}
    return under


def test_a_drop_repaints_only_the_rows_it_moved(world, monkeypatch):
    seed, win, writer = world(apply=False, size=(1280, 1200))
    lst = lst_of(win)
    lift(win, 8)
    target = row_point(win, 6)
    move_global(win, target)
    QApplication.processEvents()
    lst.viewport().repaint()
    resets = []
    lst.model().modelReset.connect(lambda: resets.append(1))
    painted = _paint_spy(lst, monkeypatch)
    release_global(win, target)
    QApplication.processEvents()
    QApplication.processEvents()
    assert resets == []                                               # the "moved" path: no reset, no relayout
    assert painted and set(painted) - _under_toast(win, lst) <= {6, 7, 8}, sorted(set(painted))


def test_S3_a_drop_at_2000_files_moves_the_rows_in_place(world, monkeypatch):
    seed, win, writer = world(files=2000, current_share=0.6, apply=False, size=(1280, 1200))
    lst = lst_of(win)
    rs = rows_of(win)
    first_soon = next(i for i, r in enumerate(rs) if r.tier == "soon")
    src = first_soon + 6                                              # inside Soon, crossing no line
    to = first_soon + 2
    lst.scrollTo(lst.model().index(src, 0), lst.ScrollHint.PositionAtCenter)
    QApplication.processEvents()
    lift(win, src)
    target = row_point(win, to)
    move_global(win, target)
    QApplication.processEvents()
    lst.viewport().repaint()
    layouts = []
    lst.model().modelReset.connect(lambda: layouts.append("reset"))
    lst.model().layoutChanged.connect(lambda: layouts.append("layout"))
    painted = _paint_spy(lst, monkeypatch)
    t0 = time.perf_counter()
    release_global(win, target)
    took = (time.perf_counter() - t0) * 1000
    QApplication.processEvents()
    assert layouts == [] and set(painted) - _under_toast(win, lst) <= set(range(to, src + 1)), sorted(set(painted))
    print(f"a drop at {len(rs)} Current rows took {took:.1f} ms on the window's thread")


# --- Gap 2 (M4.1 P3): a frame repaints only what moved; the numbers at the drop, never after ------------------- #
class _PaintRects(QObject):
    """The rects of the paint events a widget gets (Qt hands one paint the union of every update asked since the
    last)."""

    def __init__(self, widget):
        super().__init__()
        self.seen = []
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.seen.append(event.rect())
        return False


def _on_test_time():
    """Motion unfrozen and Full, the clock on test time (a frame moves only when the test says): -> its undo."""
    freeze.set_frozen(False)
    restore = _full_motion()
    clock = motion.clock()
    clock.use_test_time()

    def undo():
        clock.use_real_time()
        restore()
    return clock, undo


def _flushed(lst):
    """Every paint owed so far painted (the hand's own move asks for some): what is painted next is the frame's."""
    QApplication.processEvents()
    lst.viewport().repaint()


def test_gap2_a_gap_slide_frame_repaints_only_the_rows_that_moved_never_the_whole_list(world, monkeypatch):
    """R3-S5: each frame of the slide repainted the whole list (every row on screen, ~20 at this size) for the two
    rows making room. Now a frame repaints the band those rows were and are painted in, and the slot's."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        lift(win, 8)
        move_global(win, row_point(win, 6))                           # before row 6: rows 6 and 7 make room
        p = lst.parting
        assert set(p.springs) == {6, 7}
        _flushed(lst)
        painted = _paint_spy(lst, monkeypatch)
        rects = _PaintRects(lst.viewport())
        clock.advance(motion.FRAME_MS)                                # one frame of the slide
        QApplication.processEvents()
        assert 0 < p.offset(6) < p.h                                  # mid-slide
        assert painted and set(painted) <= {5, 6, 7, 8, 9}, sorted(set(painted))
        assert rects.seen and all(r.height() < lst.viewport().height() // 2 for r in rects.seen), rects.seen
        clock.advance(1000)                                           # at rest: the rows made room, as before
        assert p.springs == {} and [p.offset(r) for r in range(5, 10)] == [0, p.h, p.h, 0, 0]
        win.moves.cancel()
    finally:
        undo()


def _on_screen_vs_whole(win, lst):
    """The list as the screen shows it (the window's painted pixels: what the partial repaints left) and as one whole
    repaint draws it, the ghost's box blanked in both (it floats over the list). -> (shown, whole) RGB arrays."""
    from tests.qt.pixels import rgb_array
    vp = lst.viewport()
    at = vp.mapTo(win, QPoint(0, 0))
    shown = rgb_array(win.screen().grabWindow(win.winId(), at.x(), at.y(), vp.width(), vp.height()))
    whole = rgb_array(vp.grab())
    ghost = win.moves.ghost
    if ghost is not None and ghost.isVisible():
        box = ghost.geometry()
        box.moveTopLeft(vp.mapFrom(win, box.topLeft()))
        r = box.adjusted(-2, -2, 2, 2).intersected(vp.rect())
        for arr in (shown, whole):
            arr[max(0, r.top()):r.bottom() + 1, max(0, r.left()):r.right() + 1] = 0
    return shown, whole


def test_gap2_the_slides_partial_repaints_leave_the_list_as_a_whole_repaint_draws_it(world):
    """What the partial repaints could break: a row left half-drawn where it was, or a slot's ghost of itself. Frame
    by frame through a slide, a slide turned back mid-way and a slide past the row's own place, the screen's pixels
    over the list are a whole repaint's."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)

        def same(where):
            shown, whole = _on_screen_vs_whole(win, lst)
            bad = (abs(shown.astype(int) - whole.astype(int)) > 2).any(axis=2)
            assert not bad.any(), (where, int(bad.sum()), [int(v) for v in bad.nonzero()[0][[0, -1]]])
        _flushed(lst)
        lift(win, 8)                                                  # the lift: the row leaves its place for the slot
        QApplication.processEvents()
        same("lift")
        for to, lower, frames in ((5, False, 6), (7, True, 40), (11, True, 40)):
            move_global(win, row_point(win, to, lower))
            for i in range(frames):
                clock.advance(motion.FRAME_MS)
                QApplication.processEvents()
                same((to, i))
        win.moves.cancel()
    finally:
        undo()


def test_gap2_a_slot_glide_frame_repaints_only_the_slots_old_and_new_place(world, monkeypatch):
    """The slot's glide repainted the whole list each frame too. Now a frame of it repaints where the slot was and
    is — nothing else (the rows at rest here)."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        lift(win, 8)
        move_global(win, row_point(win, 6))
        clock.advance(1000)                                           # the rows and the slot at rest
        p = lst.parting
        assert p.springs == {} and not p._slot_spring.alive
        _flushed(lst)
        rects = _PaintRects(lst.viewport())
        was = p._slot_box()
        p._slot_spring.retarget(p.slot_y + 30, **motion.preset("drag-part"))   # the slot alone glides, its own spring
        clock.advance(motion.FRAME_MS)
        QApplication.processEvents()
        now = p._slot_box()
        assert now.top() > was.top()
        band = was.united(now).adjusted(0, -2, 0, 2)
        assert rects.seen and all(band.contains(r) for r in rects.seen), (band, rects.seen)
        win.moves.cancel()
    finally:
        undo()


def test_gap2_an_auto_scroll_tick_repaints_what_scrolled_in_never_the_whole_list_and_runs_under_reduced(
        world, monkeypatch):
    """Each auto-scroll tick asked the whole list to repaint on top of the scroll (Qt moves what was painted and asks
    only for what scrolled in). The hand's, not motion (IK-4): it keeps running under Reduced motion."""
    seed, win, writer = world(apply=False)
    freeze.set_frozen(False)
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("reduced")
    try:
        lst = lst_of(win)
        bar = lst.verticalScrollBar()
        assert bar.maximum() > 400
        bar.setValue(bar.maximum() // 2)
        QApplication.processEvents()
        vp = lst.viewport()
        first = lst.indexAt(QPoint(4, vp.height() // 2)).row()
        lift(win, first)
        move_global(win, vp.mapToGlobal(QPoint(vp.width() // 2, 10)))     # the hand at the list's top edge
        _flushed(lst)
        win.moves._scroll.stop()                                      # the test steps the ticks itself
        painted = _paint_spy(lst, monkeypatch)
        rects = _PaintRects(vp)
        before = bar.value()
        for _ in range(3):
            win.moves._auto_scroll()
            QApplication.processEvents()
        assert bar.value() < before                                   # it scrolled, under Reduced motion
        model = lst.model()
        assert painted and all(lst.visualRect(model.index(r, 0)).top() < vp.height() // 3 for r in set(painted)),             sorted(set(painted))
        assert rects.seen and all(r.height() < vp.height() // 2 for r in rects.seen), rects.seen
        win.moves.cancel()
    finally:
        mode.set_setting(was)


def test_gap2_auto_scroll_through_a_parted_list_leaves_it_as_a_whole_repaint_draws_it(world):
    """What a scroll's partial repaint could break: Qt paints only the strip that scrolled in, and only the rows whose
    places lie in it — a parted row standing in that strip from a place outside it was left unpainted. Tick by tick,
    the slide still moving, both ways, the screen's pixels over the list are a whole repaint's."""
    seed, win, writer = world(apply=False)
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        vp = lst.viewport()
        bar = lst.verticalScrollBar()
        assert bar.maximum() > 400
        bar.setValue(bar.maximum() // 2)
        QApplication.processEvents()

        def same(where):
            shown, whole = _on_screen_vs_whole(win, lst)
            bad = (abs(shown.astype(int) - whole.astype(int)) > 2).any(axis=2)
            assert not bad.any(), (where, int(bad.sum()), [int(v) for v in bad.nonzero()[0][[0, -1]]])
        first = lst.indexAt(QPoint(4, vp.height() // 2)).row()
        lift(win, first)
        win.moves._scroll.stop()                                      # the test steps the ticks itself
        for edge, name in ((10, "up"), (vp.height() - 10, "down")):
            move_global(win, vp.mapToGlobal(QPoint(vp.width() // 2, edge)))
            win.moves._scroll.stop()
            _flushed(lst)
            before = bar.value()
            for i in range(8):
                win.moves._auto_scroll()
                clock.advance(motion.FRAME_MS)                        # the rows still sliding as the list scrolls
                QApplication.processEvents()
                same((name, i))
            assert bar.value() != before, name
        win.moves.cancel()
    finally:
        undo()


def test_gap2_auto_scroll_while_rows_spring_back_into_the_strip_leaves_no_row_unpainted(world):
    """The hand from below to the top edge: rows just under the strip that scrolls in still spring back up into it
    from places outside it — Qt alone would paint only the rows whose places lie in the strip."""
    seed, win, writer = world(apply=False)
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        vp = lst.viewport()
        bar = lst.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        QApplication.processEvents()

        def same(where):
            shown, whole = _on_screen_vs_whole(win, lst)
            bad = (abs(shown.astype(int) - whole.astype(int)) > 2).any(axis=2)
            assert not bad.any(), (where, int(bad.sum()), [int(v) for v in bad.nonzero()[0][[0, -1]]])
        top = lst.indexAt(QPoint(4, vp.height() // 6)).row()
        lift(win, top)
        win.moves._scroll.stop()
        move_global(win, row_point(win, top + 4))
        clock.advance(1000)                                           # the rows under it parted up, at rest
        move_global(win, vp.mapToGlobal(QPoint(vp.width() // 2, 10)))
        win.moves._scroll.stop()
        _flushed(lst)
        for i in range(8):
            win.moves._auto_scroll()
            clock.advance(motion.FRAME_MS)
            QApplication.processEvents()
            same(("jump", i))
        win.moves.cancel()
    finally:
        undo()


def _strip_shown_as_whole(win, lst, where):
    shown, whole = _on_screen_vs_whole(win, lst)
    bad = (abs(shown.astype(int) - whole.astype(int)) > 2).any(axis=2)
    assert not bad.any(), (where, int(bad.sum()), [int(v) for v in bad.nonzero()[0][[0, -1]]])


def _edge_row(win, lst, band, upper):
    """A scroll place and a point in the edge band (`band`: its viewport rows, tried in order — its inner end scrolls
    1 px a tick, so the slot stays put for a few ticks) on a row's upper (or lower) half, the row's place clear of the
    viewport's edge by more than a few pixels: -> (scroll value, y), the list scrolled there."""
    bar, h = lst.verticalScrollBar(), lst.viewport().height()
    for v in range(bar.maximum() // 2, bar.maximum() // 2 + 200):
        bar.setValue(v)
        QApplication.processEvents()
        for y in band:
            idx = lst.indexAt(QPoint(4, y))
            if not idx.isValid():
                continue
            r = lst.visualRect(idx)
            if upper and y < r.center().y() and r.bottom() < h - 6:
                return v, y
            if not upper and y >= r.center().y() + 4 and r.top() > 2:     # (the list comes down under the hand)
                return v, y
    raise AssertionError("no such geometry in the seed")


def test_S1_auto_scroll_down_paints_the_strip_under_rows_parted_down_from_places_outside_it(world):
    """M4.1 adversary S1: a drag from outside the list (the Goal sheet, the tray) pushes every row past the slot down.
    The hand in the bottom band on a row's upper half leaves the slot's box short of the edge, so the strip each tick
    scrolls in shows the slot's row, pushed down into it from a place outside it — Qt alone paints only the rows whose
    places lie in the strip, and a background band grew a pixel row a tick. The scroll asks for that strip, widened
    to the parted rows whose pictures reach into it."""
    seed, win, writer = world(apply=False)
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        vp = lst.viewport()
        bar = lst.verticalScrollBar()
        h, edge = vp.height(), theme.MOTION["auto-scroll-edge"]
        v, y = _edge_row(win, lst, range(h - edge + 1, h - 1), upper=True)
        goal_ids = [r["id"] for r in seed.items if r["tier"] == "goal"][:3]
        first = lst.indexAt(QPoint(4, h // 2)).row()
        assert win.moves.begin_by_id(goal_ids, "goal", "海辺の図書室", row_point(win, first))
        win.moves._scroll.stop()                                      # the test steps the ticks itself
        move_global(win, vp.mapToGlobal(QPoint(vp.width() // 2, y)))
        win.moves._scroll.stop()
        clock.advance(1000)                                           # parted, at rest
        _flushed(lst)
        _strip_shown_as_whole(win, lst, "at rest")
        for i in range(6):
            win.moves._auto_scroll()
            clock.advance(motion.FRAME_MS)
            QApplication.processEvents()
            _strip_shown_as_whole(win, lst, ("down", i, bar.value(), lst.parting.slot))
        assert bar.value() > v
        win.moves.cancel()
    finally:
        undo()


def test_S1_auto_scroll_up_paints_the_strip_under_rows_parted_up_from_places_outside_it(world):
    """S1's mirror: a row lifted from above the screen pulls the rows up to its slot; the hand in the top band on a
    row's lower half leaves the slot's box short of the top edge, so the slot's row, pulled up, stands in the strip
    each tick scrolls in from a place below it. (A shorter window: the lifted row a screen above the scroll place.)"""
    seed, win, writer = world(apply=False, size=(1280, 560))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        vp = lst.viewport()
        bar = lst.verticalScrollBar()
        h, edge = vp.height(), theme.MOTION["auto-scroll-edge"]
        v, y = _edge_row(win, lst, range(edge - 1, 0, -1), upper=False)     # the band's inner end: 1 px a tick
        assert v >= h
        bar.setValue(v - h)                                           # the row to lift: half a screen above v's top
        QApplication.processEvents()
        lift(win, lst.indexAt(QPoint(4, h // 2)).row())
        win.moves._scroll.stop()
        bar.setValue(v)
        QApplication.processEvents()
        move_global(win, vp.mapToGlobal(QPoint(vp.width() // 2, y)))
        win.moves._scroll.stop()
        clock.advance(1000)                                           # parted up, at rest
        p = lst.parting
        assert p.slot > p.src and p._slot_box().top() > 2             # the slot's box short of the top edge
        _flushed(lst)
        _strip_shown_as_whole(win, lst, "at rest")
        for i in range(6):
            win.moves._auto_scroll()
            clock.advance(motion.FRAME_MS)
            QApplication.processEvents()
            _strip_shown_as_whole(win, lst, ("up", i, bar.value(), p.slot))
        assert bar.value() < v
        win.moves.cancel()
    finally:
        undo()


def test_gap2_a_drop_on_goal_shows_goals_new_count_and_its_name_at_the_drop_while_the_wells_fall(world):
    """The bar's new count (and the dock's accessible name) waited for the wells' 260 ms fall; now they come at the
    drop, the bar shown under the wells falling away from it."""
    seed, win, writer = world()
    clock, undo = _on_test_time()
    try:
        lift(win, 5)
        clock.advance(theme.MOTION["buckets"] + 16)                   # the wells have risen
        at = well_point(win, "goal")
        move_global(win, at)
        release_global(win, at)
        dock = win.dock
        goal = win.page_widgets["current"].view_model.goal
        assert dock.wells                                             # the clock hasn't moved: the fall not begun
        assert dock.accessibleName() == strings.GOAL_ACCESSIBLE.format(name=strings.GOAL_NAME, line=goal.line)
        clock.advance(theme.MOTION["buckets"] / 2)
        dock.repaint()
        assert dock.wells and dock._key is not None and dock._key[0] == frame._bar_of(goal)   # drawn mid-fall
        clock.advance(theme.MOTION["buckets"])
        assert dock.wells == ()
    finally:
        undo()


# --- M4.1 row 4, package C: the window's own work at a move and a pickup ---------------------------------------- #
def test_C2_a_moves_next_view_of_the_same_rows_walks_nothing_in_the_dock(world):
    """C2: each of a move's views walked every Current and Finished row in the dock for the wells' cover records
    (3–5 ms a view at 20,000 files). A view holding the same rows, Finished and Goal walks nothing; new rows walk
    once, their records the same."""
    seed, win, writer = world(apply=True)
    dock = win.dock
    rs = rows_of(win)
    win.moves.menu_pick(rs[4], "up-next")                             # a reorder: the window's view, the store's
    assert wait_until(lambda: win.moves.expect is None and not win.moves.tickets
                      and win.services.library.view().rows[0].key == rs[4].key, 10)
    view = win.services.library.view()
    win.show_library(view)
    walks, refs = dock.walks, dict(dock._refs)
    for _ in range(3):                                                # the move's next views: the same rows
        win.show_library(view._replace(subline=view.subline + " "))
    assert dock.walks == walks and dock._refs == refs
    keys = [r.key for r in view.rows]
    keys[1], keys[2] = keys[2], keys[1]
    win.show_library(drag.reordered(view, keys))                      # other rows: walked once, the same titles
    assert dock.walks == walks + 1 and dock._refs == refs


def test_C2_a_moves_settle_view_its_rows_the_same_objects_in_a_new_tuple_walks_nothing_again(world):
    """C2's shell half, as measured (C2.md): none of a move's views is the view shown before or holds its rows' tuple,
    so a skip on those in `show_library` would never fire. The view that walked unchanged data again is the last: the
    same rows (and Finished) in a new tuple, which the dock walked once more. Now it walks nothing; a row changed (a new
    object: its numbers) walks once."""
    seed, win, writer = world(apply=True)
    dock = win.dock
    rs = rows_of(win)
    win.moves.menu_pick(rs[4], "up-next")                             # a reorder: the window's view, the store's
    assert wait_until(lambda: win.moves.expect is None and not win.moves.tickets
                      and win.services.library.view().rows[0].key == rs[4].key, 10)
    view = win.services.library.view()
    win.show_library(view)
    walks, refs = dock.walks, dict(dock._refs)
    win.show_library(view._replace(rows=tuple(list(view.rows)), finished=tuple(list(view.finished))))
    assert dock.walks == walks and dock._refs == refs
    other = list(view.rows)
    other[2] = other[2]._replace(n_new=other[2].n_new + 1)
    win.show_library(view._replace(rows=tuple(other)))
    assert dock.walks == walks + 1 and dock._refs == refs


def test_C5_a_lift_right_after_the_pointer_rested_on_a_row_bakes_no_ghost_and_shows_that_rows_picture(world):
    """C5: the pickup baked the ghost (its shadow, ring, turn: 9 pictures drawn) and showed its window for the first
    time on the press's frame. The pointer resting on the row bakes it ahead; the lift only shows it. What it could
    break: a stale ghost — the row's picture changed since is baked again."""
    seed, win, writer = world(apply=False)
    lst, moves = lst_of(win), win.moves
    assert moves.ghost is not None and not moves.ghost.isVisible()     # made once, at the window's open, hidden
    i = 4
    at = title_point(lst, i)
    baked = moves.ghost_bakes
    move(lst, at, buttons=NONE)                                       # the pointer comes to rest on row 4
    assert wait_until(lambda: moves.ghost_bakes == baked + 1, 3)
    lift(win, i)
    assert moves.ghost_bakes == baked + 1, "the lift baked its ghost again"
    kind, row, lines = lst.model().entries[i]
    rect = lst.visualRect(lst.model().index(i, 0))
    slot = lst.delegate.slot_rect(kind, rect, lines)
    dpr = lst.viewport().devicePixelRatioF() or 1.0
    fresh = drag.ghost_picture(moves._row_picture(kind, row, lines, rect, slot), slot.width(), slot.height(), dpr)[0]
    assert moves.ghost.isVisible() and moves.ghost.pix.toImage() == fresh.toImage()     # the row's own picture
    moves.cancel()
    assert wait_until(lambda: time.monotonic() >= moves._swallow_until, 3)      # (a press right after is swallowed)
    k = next(iter(moves._ghosts))
    moves._ghosts[k] = (-1,) + moves._ghosts[k][1:]                   # as if the row were painted anew since
    lift(win, i)
    assert moves.ghost_bakes == baked + 2
    moves.cancel()


def test_C6_a_slide_frame_asks_one_repaint_its_rows_rects_worked_out_once(world, monkeypatch):
    """C6: each moving row's spring frame worked the screen out again (two `indexAt`) and walked the parted rows'
    `visualRect`s while its band widened — ~220 calls a frame with six rows moving. Now a frame's bands are asked
    for once, at its end, every rect worked out once (the gap2 tests above hold what repaints)."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        lift(win, 8)
        move_global(win, row_point(win, 2))                           # rows 2–7 make room: six springs
        p = lst.parting
        assert len(p.springs) == 6
        _flushed(lst)
        lo, hi = p._screen()
        rects, updates = [0], [0]
        real_rect, real_update = lst.visualRect, lst.viewport().update

        def visual_rect(index):
            rects[0] += 1
            return real_rect(index)

        def update(*args):
            updates[0] += 1
            return real_update(*args)
        monkeypatch.setattr(lst, "visualRect", visual_rect)
        monkeypatch.setattr(lst.viewport(), "update", update)
        painted = _paint_spy(lst, monkeypatch)
        clock.advance(motion.FRAME_MS)                                # one frame of the slide
        assert 0 < p.offset(2) < p.h
        assert updates[0] == 1, updates[0]
        assert rects[0] <= hi - lo + 1, (rects[0], hi - lo + 1)
        QApplication.processEvents()
        assert painted and set(painted) <= set(range(1, 10)), sorted(set(painted))
        clock.advance(1000)
        assert p.springs == {}
        win.moves.cancel()
    finally:
        undo()


def test_gap2_a_hover_letting_go_during_a_drag_repaints_its_rows_never_the_whole_list(world, monkeypatch):
    """Gap 2 item 4: the row under the hand lets its hover look go as it is lifted (it and its neighbours on their
    springs), and each of those frames repainted the whole list while the rows parted. Now a frame repaints the rows
    the hover moved, each where the parting paints it."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        move(lst, title_point(lst, 8), buttons=NONE)                  # the hand rests on row 8: it lifts
        clock.advance(1000)
        key = lst.model().entries[8][1].key
        assert lst._touch[key].lift == theme.SPRINGS["lift-px"]
        lift(win, 8)                                                  # its hover look lets go, on its springs
        move_global(win, row_point(win, 6))                           # rows 6 and 7 make room
        p = lst.parting
        assert lst._touch[key].s_lift.alive and set(p.springs) == {6, 7}
        _flushed(lst)
        painted = _paint_spy(lst, monkeypatch)
        rects = _PaintRects(lst.viewport())
        clock.advance(motion.FRAME_MS)
        QApplication.processEvents()
        assert key in lst._touch and 0 < p.offset(6) < p.h            # both mid-way
        assert painted and set(painted) <= set(range(5, 11)), sorted(set(painted))
        assert rects.seen and all(r.height() < lst.viewport().height() // 2 for r in rects.seen), rects.seen
        win.moves.cancel()
    finally:
        undo()


def test_gap2_a_hover_spring_on_a_parted_row_repaints_where_it_is_painted_now(world, monkeypatch):
    """What item 4's partial repaint could break: a parted row's hover moving where the parting paints it (its place
    moved by the slot's height) while only its own place repaints — its old picture left on the screen. Frame by
    frame, the screen's pixels over the list are a whole repaint's."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        lift(win, 8)
        move_global(win, row_point(win, 6))
        clock.advance(1000)                                           # rows 6 and 7 at rest, a slot's height down
        p = lst.parting
        assert p.springs == {} and p.offset(7) == p.h
        _flushed(lst)
        asked = []
        vp = lst.viewport()
        with monkeypatch.context() as m:
            m.setattr(vp, "update", lambda *a, real=vp.update: asked.append(a[0]) or real(*a))
            p.repaint_rows([7])                                       # (outside a frame: asked at once)
        place = lst.visualRect(lst.model().index(7, 0))
        painted_at = QRegion(place.translated(0, round(p.h)))           # where row 7 is painted now (its place moved)
        assert asked and painted_at.subtracted(QRegion(asked[0])).isEmpty(), asked
        key = lst.model().entries[7][1].key
        for on in (True, False):                                      # its hover look lifts, then lets go
            lst._touch_to(key, on)
            for i in range(30):
                clock.advance(motion.FRAME_MS)
                QApplication.processEvents()
                shown, whole = _on_screen_vs_whole(win, lst)
                bad = (abs(shown.astype(int) - whole.astype(int)) > 2).any(axis=2)
                assert not bad.any(), (on, i, int(bad.sum()))
        win.moves.cancel()
    finally:
        undo()


@pytest.mark.parametrize("line", ["top", "soon"])
def test_C3_a_drop_across_a_line_relays_the_rows_out_never_resets_and_keeps_the_keyboards_row(world, line):
    """C3 (R3-S6): a drop across the top-20 or the Soon line moves that line to another place, so places change height
    and the list was reset — Qt's whole relayout, the keyboard's row and the hand's let go, the scroll put back from
    its anchor. Now the same rows in their new places are relaid out: no reset, the keyboard's row (the press made it
    the dragged row's) still on its title, every row painted from its kept picture."""
    seed, win, writer = world(apply=False, size=(1280, 1200))
    lst = lst_of(win)
    model = lst.model()

    def line_at():
        return next(i for i, e in enumerate(model.entries) if any(ln.kind == line for ln in e[2]))
    at = line_at()
    view = win.page_widgets["current"].view_model
    keys = [r.key for r in view.rows]
    by = {r.key: r for r in view.rows}

    def after(order):
        return next(ln.after for ln in drag.lines_for(view, [by[k] for k in order]) if ln.kind == line)
    to = at - 1                                                       # from under the line to above it: the line moves
    src = next(s for s in range(at + 1, at + 6) if after(drag.order_after(keys, keys[s], to)) != at)
    lst.scrollTo(model.index(src, 0), lst.ScrollHint.PositionAtCenter)
    moved_key = model.entries[src][1].key
    QApplication.processEvents()
    lst.viewport().repaint()
    hows, real = [], model.set_entries
    model.set_entries = lambda entries: hows.append(real(entries)) or hows[-1]
    resets = []
    model.modelReset.connect(lambda: resets.append(1))
    lift(win, src)
    target = row_point(win, to)
    move_global(win, target)
    QApplication.processEvents()
    renders = lst.delegate.renders                                    # (the lift draws the ghost's picture)
    release_global(win, target)
    QApplication.processEvents()
    assert model.entries[to][1].key == moved_key and line_at() != at  # the drop crossed the line: it moved
    assert "relayout" in hows and "reset" not in hows and resets == [], hows
    assert lst.currentIndex().row() == to                             # the keyboard's row (the press's) on its title
    lst.viewport().repaint()
    QApplication.processEvents()
    drawn = lst.delegate.renders - renders
    assert drawn == (1 if line == "soon" else 0), drawn               # none drawn afresh but the row now in NOW
    assert calls(writer, "move")


def test_IKB8_a_drop_across_a_line_above_the_screen_moves_no_row_on_screen(world):
    """IKB-8: a drop across the Soon line relays the rows out (C3) and keeps the scroll value, where a reset put the top
    row back from its anchor. With the line's old place above the screen, no row on screen may shift by the line's
    height at the drop: each sits where the parting painted it just before. (An anchor kept by the top row's key, as
    the reset's, would be wrong here: that row moved up a place with the drop, so the list would jump by a row.)"""
    seed, win, writer = world(files=2000, apply=False, size=(1280, 900))
    clock, undo = _on_test_time()
    try:
        lst = lst_of(win)
        model = lst.model()
        bar = lst.verticalScrollBar()

        def line_at():
            return next(i for i, e in enumerate(model.entries) if any(ln.kind == "soon" for ln in e[2]))
        at = line_at()
        src = 2
        assert model.entries[src][1].tier == "now" and src < at
        moved_key = model.entries[src][1].key
        hows, real = [], model.set_entries
        model.set_entries = lambda entries: hows.append(real(entries)) or hows[-1]
        lift(win, src)                                                # a NOW row above both lines
        top = at + 3
        bar.setValue(lst.visualRect(model.index(top, 0)).top() + bar.value() + 20)   # scrolled past the Soon line
        QApplication.processEvents()
        to = top + 4
        target = row_point(win, to)
        move_global(win, target)
        clock.advance(1000)                                           # the rows have parted and rest
        QApplication.processEvents()
        p = lst.parting
        assert lst.visualRect(model.index(at, 0)).bottom() < 0        # the line's old place is above the screen
        vh = lst.viewport().height()
        before = {}
        for i in range(model.rowCount()):
            r = lst.visualRect(model.index(i, 0))
            if i != p.src and r.bottom() >= 0 and r.top() < vh:
                before[model.entries[i][1].key] = r.top() + int(round(p.offset(i)))
        assert len(before) >= 6
        release_global(win, target)
        clock.advance(1000)                                           # the ghost home, the rows at rest
        QApplication.processEvents()
        assert "relayout" in hows and "reset" not in hows, hows       # C3's branch, not the reset
        assert line_at() == at - 1                                    # the drop crossed the Soon line: it moved
        after = {model.entries[i][1].key: lst.visualRect(model.index(i, 0)).top() for i in range(model.rowCount())}
        moved = {k: (y, after[k]) for k, y in before.items() if k != moved_key and after[k] != y}
        assert moved == {}, moved                                     # no row on screen shifted at the drop
    finally:
        undo()


def test_C6_no_row_is_painted_ahead_while_a_drag_parts_the_rows_and_it_resumes_after(world, monkeypatch):
    """C6: the list's painting ahead (`_warm_one`, a row a turn) ran under a drag, 51 rows in one 15 ms chain during
    auto-scroll. While the rows part it waits — the shown list and a hidden one laid out like it — and starts again
    once the drag is over."""
    seed, win, writer = world(apply=False)
    lst = lst_of(win)
    fin = win.page_widgets["finished"].list
    warmed = []
    for view in (lst, fin):
        real = view.delegate.warm
        monkeypatch.setattr(view.delegate, "warm", lambda *a, real=real, v=view, **k: warmed.append(v) or real(*a, **k))
    lift(win, 4)
    lst._warm.stop()
    lst._moved = 0.0                                                  # the shown list at rest: only the drag holds
    fin.warm_like = lst
    fin._warm_one()                                                   # a hidden list laid out like the dragged one
    lst._warm_one()
    assert warmed == [] and lst._warm.isActive() and fin._warm.isActive()     # each asked again once it rests
    QTest.qWait(rows.WARM_IDLE_MS + 150)
    assert warmed == []
    win.moves.cancel()
    assert wait_until(lambda: lst in warmed, 3)


# --- hover springs rest when what they draw stops changing (L5) -------------------------------------------------- #
def test_L5_a_hover_spring_rests_once_its_drawn_value_stops_changing(world):
    seed, win, writer = world()
    freeze.set_frozen(False)
    lst = lst_of(win)
    clock = motion.clock()
    clock.use_test_time()
    try:
        key = lst.model().entries[3][1].key
        lst._hover = 3
        lst._retouch()
        t = lst._touch[key]
        took = 0
        while t.s_lift.alive and took < 1000:
            clock.advance(motion.FRAME_MS)
            took += motion.FRAME_MS
        assert not t.s_lift.alive and t.lift == theme.SPRINGS["lift-px"]
        # 2 px, critically damped at ω 13.5: within 0.05 px by ≈ 0.43 s; rest-x alone (0.005 px) would run ≈ 0.62 s
        assert took < 500, took
    finally:
        clock.use_real_time()


# --- AD-5: a reorder keeps the keyboard on its row --------------------------------------------------------------- #
def test_AD5_after_a_nudge_the_focus_stays_on_the_same_title(world):
    seed, win, writer = world(apply=False)
    lst = lst_of(win)
    lst.setFocus(Qt.FocusReason.TabFocusReason)
    lst.setCurrentIndex(lst.model().index(5, 0))
    row = rows_of(win)[5]
    QTest.keyClick(lst, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)        # L7: Alt+↓
    assert lst.model().entries[6][1].key == row.key
    assert lst.currentIndex().row() == 6
    assert calls(writer, "nudge")[0][1] == drag.ids_of(row) and calls(writer, "nudge")[0][2]["direction"] == "down"


def test_AD5_the_hovered_place_follows_its_row_too(world):
    seed, win, writer = world(apply=False)
    lst = lst_of(win)
    lst._hover = 5
    row = rows_of(win)[5]
    win.moves.nudge(rows_of(win)[4], 1)                              # row 4 swaps with the hovered row 5
    assert lst.model().entries[4][1].key == row.key and lst._hover == 4


# --- ↑ ↓ across the NOW / Soon edge; ⋯ ---------------------------------------------------------------------------- #
def test_a_nudge_across_the_now_soon_edge_moves_it_beside_the_neighbour(world):
    seed, win, writer = world(apply=False)
    rs = rows_of(win)
    first_soon = next(i for i, r in enumerate(rs) if r.tier == "soon")
    win.moves.nudge(rs[first_soon], -1)
    op = calls(writer, "move")[0]
    assert op[2]["tier"] == "now" and op[2]["before_id"] == rs[first_soon - 1].episodes[0].id
    win.moves._let_go()
    win.show_library(win.services.library.view() or win.page_widgets["current"].view_model)
    writer.calls.clear()
    rs = rows_of(win)
    last_now = first_soon - 1
    win.moves.nudge(rs[last_now], 1)
    op = calls(writer)[-1]
    assert op[0] == "move" and op[2]["tier"] == "soon" and op[2]["after_id"] == rs[last_now + 1].episodes[-1].id


def _soon_line_through_a_show(world, apply=True):
    """The seed with the store's Soon line inside NOW's last show (P-LF-16): the podcast (#1–4, 6) keeps #1–4 in NOW and
    its #6 is Soon's first file, as the store's line, a count of files, leaves a show it falls inside. -> (seed, win,
    writer, the podcast's place)."""
    seed, win, writer = world(apply=apply)
    rs = rows_of(win)
    at = next(i for i, r in enumerate(rs) if r.tier == "soon") - 1
    show = rs[at]
    top_of_soon = min(r["ord"] for r in seed.library.items() if r["tier"] == "soon")
    seed.library.commit(items=[{"id": show.episodes[-1].id, "tier": "soon", "ord": top_of_soon - 1024}], order=True)
    assert wait_until(lambda: rows_of(win)[at].soon_from is not None, 5)
    for _ in range(20):
        QApplication.processEvents()
    return seed, win, writer, at


def test_P_LF_16_a_show_the_soon_line_runs_through_is_one_row_and_a_drag_moves_all_its_files(world):
    """The show stays one row above the line (its tiers per file unchanged), the line drawn after it; a drag of that
    row moves every file of it — both sides of the line — as one, and a drop after it lands after its last file, in
    Soon (Sonic, 2026-10-21: "a soon show should be added after that series")."""
    seed, win, writer, at = _soon_line_through_a_show(world)
    rs = rows_of(win)
    show = rs[at]
    assert show.tier == "now" and show.n_files == 5 and show.soon_from == 4
    assert [r.key for r in rs].count(show.key) == 1 and rs[at + 1].work_id != show.work_id
    view = win.page_widgets["current"].view_model
    assert [ln.after for ln in view.lines if ln.kind == "soon"] == [at]
    tier, before, after, _near = drag.placement(rs, 2, at)             # without row 2: just after the show
    assert tier == "soon" and after == show.episodes[-1].id
    lst = lst_of(win)
    lst.scrollTo(lst.model().index(at, 0))
    settle()
    lift(win, at)
    lst.scrollToTop()
    settle()
    target = row_point(win, 1)
    move_global(win, target)
    release_global(win, target)
    op = calls(writer, "move")[0]
    assert op[1] == [e.id for e in show.episodes] and len(op[1]) == 5 and op[2]["tier"] == rs[0].tier
    assert rows_of(win)[1].key == show.key and rows_of(win)[1].soon_from is None     # at once, whole in one tier
    assert wait_until(lambda: win.moves.expect is None, 3)


def test_P_LF_16_nudges_around_a_show_the_soon_line_runs_through_move_beside_it_never_a_one_tier_nudge(world):
    """The store's nudge stays in one tier, and this show's files are in both: ↑ on it is a move before the row above,
    and ↓ on the row above it a move after its last file (in Soon) — never a nudge that moves half of it."""
    seed, win, writer, at = _soon_line_through_a_show(world, apply=False)
    rs = rows_of(win)
    show = rs[at]
    win.moves.nudge(show, -1)
    op = calls(writer)[-1]
    assert op[0] == "move" and op[1] == drag.ids_of(show) and len(op[1]) == 5
    assert op[2]["tier"] == "now" and op[2]["before_id"] == rs[at - 1].episodes[0].id
    win.moves._let_go()
    win.show_library(win.services.library.view() or win.page_widgets["current"].view_model)
    writer.calls.clear()
    rs = rows_of(win)
    win.moves.nudge(rs[at - 1], 1)
    op = calls(writer)[-1]
    assert op[0] == "move" and op[2]["tier"] == "soon" and op[2]["after_id"] == show.episodes[-1].id


def _sent_to_soon_lands_after_the_show(win, writer, show, moved):
    """B2-1: what is sent to Soon with the line inside a show lands after that show's last file — never at Soon's very
    top, between its NOW and Soon files (the show split again) — and the toast counts only NOW's files above it."""
    op = calls(writer, "move")[-1]
    assert op[1] == drag.ids_of(moved) and op[2]["tier"] == "soon"
    assert op[2]["before_id"] is None and op[2]["after_id"] == show.episodes[-1].id
    rs = rows_of(win)
    place = next(i for i, r in enumerate(rs) if r.key == moved.key)
    assert rs[place - 1].key == show.key                              # just below the show the line runs through
    now_files = sum(r.n_files for r in rs[:place]) - (show.n_files - show.soon_from)      # its Soon file isn't NOW's
    assert win.toasts.card.message == strings.DRAG_SOON.format(title=moved.title, n=place + 1, files=now_files)
    assert wait_until(lambda: win.moves.expect is None, 3)
    rs = rows_of(win)                                                 # the store's view, once the move landed
    show_now = next(r for r in rs if r.key == show.key)
    assert [r.key for r in rs].count(show.key) == 1 and show_now.soon_from == 4      # still one row, never split
    assert rs[rs.index(show_now) + 1].key == moved.key


def test_B2_1_a_drop_on_the_soon_well_lands_after_a_show_the_soon_line_runs_through(world):
    seed, win, writer, at = _soon_line_through_a_show(world)
    rs = rows_of(win)
    show, moved = rs[at], rs[1]
    lift(win, 1)
    point = well_point(win, "soon")
    move_global(win, point)
    release_global(win, point)
    _sent_to_soon_lands_after_the_show(win, writer, show, moved)


def test_B2_1_the_menus_soon_lands_after_a_show_the_soon_line_runs_through(world):
    seed, win, writer, at = _soon_line_through_a_show(world)
    rs = rows_of(win)
    show, moved = rs[at], rs[1]
    win.moves.menu_pick(moved, "soon")
    _sent_to_soon_lands_after_the_show(win, writer, show, moved)


def test_B2_1_soon_slot_is_the_one_rule_and_counts_only_now_files():
    """The pure rule the three callers share: with no show cut by the line, Soon's top (no anchor) and every file above
    it; with one, after its last file and its Soon files left out of the count."""
    Ep = namedtuple("Ep", "id")
    R = namedtuple("R", "key tier n_files episodes soon_from")

    def row(key, tier, ids, cut=None):
        return R(key, tier, len(ids), tuple(Ep(i) for i in ids), cut)
    plain = [row("a", "now", [1, 2]), row("b", "now", [3]), row("c", "soon", [4, 5])]
    assert drag.soon_slot(plain, 0) == (1, 1, None)
    cut = [row("a", "now", [1, 2]), row("b", "now", [3, 4, 5], cut=1), row("c", "soon", [6])]
    assert drag.soon_slot(cut, 0) == (1, 1, 5)                        # after the show's #5; its two Soon files out
    assert drag.soon_slot(cut, None) == (2, 3, 5)
    whole = cut[:2]                                                   # the show holds the whole of Soon
    assert drag.soon_slot(whole, 0) == (1, 1, 5)
    assert drag.soon_slot(cut, 1) == (1, 2, None)                     # the show itself sent: Soon's top, whole


def test_the_menu_leaves_out_up_next_for_up_next_and_finished_for_splits_and_hatos_mix(world):
    seed, win, writer = world()
    rs = rows_of(win)
    names = [e[0] for e in win.moves.menu_entries(rs[4])]
    assert names == ["up-next", "soon", "goal", "finished", "journey"]
    assert [e[0] for e in win.moves.menu_entries(rs[0])] == ["soon", "goal", "journey"]       # Up Next, hato's mix
    split = next(r for r in rs if drag.split_first(rs, r))
    assert "finished" not in [e[0] for e in win.moves.menu_entries(split)]
    m = win.moves.menu(rs[4], win.mapToGlobal(QPoint(300, 300)))
    assert m.toolTipsVisible() and all(a.toolTip() for a in m.actions())
    assert [a.text() for a in m.actions()][-1] == strings.MENU_ITEMS["journey"][0]
    m.close()


def test_the_menus_moves_reach_the_writer(world):
    seed, win, writer = world(apply=False)
    rs = rows_of(win)
    win.moves.menu_pick(rs[5], "up-next")
    op = calls(writer, "move")[-1]
    assert op[2]["before_id"] == rs[0].episodes[0].id and rows_of(win)[0].key == rs[5].key
    win.moves._let_go()
    win.show_library(win.services.library.view())
    rs = rows_of(win)
    win.moves.menu_pick(rs[4], "goal")
    assert calls(writer, "move")[-1][2]["end"] is True
    win.moves._let_go()
    win.show_library(win.services.library.view())
    rs = rows_of(win)
    win.moves.menu_pick(rs[4], "soon")
    assert calls(writer, "move")[-1][2]["tier"] == "soon"
    win.moves._let_go()
    win.show_library(win.services.library.view())
    rs = rows_of(win)
    win.moves.menu_pick(rs[4], "finished")
    assert calls(writer, "set_tier")[-1][1] == drag.ids_of(rs[4])


# --- a Done and the finish toast (A2 #1, #2) ------------------------------------------------------------------------- #
def test_a_done_marks_it_watched_and_names_the_next(world):
    seed, win, writer = world()
    rs = rows_of(win)
    row = rs[4]
    ep = row.episodes[0]
    win.moves.done(row, ep)
    assert calls(writer, "set_watched")[0] == ("set_watched", [ep.id], {"on": True})
    assert win.toasts.card.message == strings.DONE_NEXT.format(title=row.title, ep=ep.label,
                                                                next=row.episodes[1].label)


def test_a_watched_stone_turns_back(world):
    seed, win, writer = world()
    row = rows_of(win)[0]
    ep = next(e for e in row.episodes if e.watched)
    win.moves.done(row, ep)
    assert calls(writer, "set_watched")[0][2] == {"on": False}


def _all_but_one(seed, win, i):
    row = rows_of(win)[i]
    seed.library.commit(items=[{"id": e.id, "watched": 1} for e in row.episodes[:-1]])
    assert wait_until(lambda: sum(e.watched for e in rows_of(win)[i].episodes) == len(row.episodes) - 1, 3)
    return rows_of(win)[i]


def test_the_last_files_done_offers_the_finish_and_its_move_to_finished_acts(world):
    seed, win, writer = world()
    row = _all_but_one(seed, win, 4)
    win.moves.done(row, row.episodes[-1])
    card = win.toasts.card
    assert card.message == strings.DONE_ALL.format(n=len(row.episodes))
    assert [b.text() for b in card.buttons if not b.isHidden()] == [strings.TOAST_UNDO, strings.DONE_MOVE_FINISHED]
    settle()
    card.buttons[1].click()
    assert calls(writer, "set_tier")[0][1] == drag.ids_of(row)
    assert row.key not in [r.key for r in rows_of(win)]
    assert win.toasts.card.message == strings.DRAG_FINISHED.format(title=row.title)


def test_the_finish_toast_is_skipped_for_a_splits_first_part_and_hatos_mix(world):
    seed, win, writer = world()
    rs = rows_of(win)
    i = next(n for n, r in enumerate(rs) if drag.split_first(rs, r))
    row = _all_but_one(seed, win, i)
    win.moves.done(row, row.episodes[-1])
    assert win.toasts.card.message == strings.DONE_ONE.format(title=row.title, ep=row.episodes[-1].label)
    row = _all_but_one(seed, win, 0)
    win.moves.done(row, row.episodes[-1])
    assert win.toasts.card.message == strings.DONE_ONE.format(title=row.title, ep=row.episodes[-1].label)


def click_hero_done(win):
    lst = lst_of(win)
    done = part_rect(lst, 0, "done")
    press(lst, done[1].center())
    release(lst, done[1].center())
    return done


def test_G3_2_up_next_done_with_every_file_watched_offers_move_to_finished_and_undo_takes_it_back(world):
    """Up Next's ✓ Done did nothing once every file was watched (the click was swallowed). Now it offers the finish,
    as the last file's Done does: nothing is marked (every file is watched already), *Move to Finished* finishes it
    through the writer, and the Finished toast's Undo takes it back."""
    seed, win, writer = world()
    moved = rows_of(win)[3]
    assert not drag.is_mix(moved) and not drag.split_first(rows_of(win), moved)
    lift(win, 3)
    move_global(win, row_point(win, 0))
    release_global(win, row_point(win, 0))                            # it is Up Next now
    assert rows_of(win)[0].key == moved.key
    seed.library.commit(items=[{"id": e.id, "watched": 1} for e in moved.episodes])
    assert wait_until(lambda: all(e.watched for e in rows_of(win)[0].episodes), 3)
    QTest.qWait(theme.MOTION["click-swallow-after-drag"] + 30)
    writer.calls.clear()
    done = click_hero_done(win)
    assert done[2] == strings.ROWS_DONE_ALL_TIP
    assert calls(writer) == []                                        # nothing marked: an offer
    card = win.toasts.card
    assert card.message == strings.DONE_ALL.format(n=len(moved.episodes))
    assert [b.text() for b in card.buttons if not b.isHidden()] == [strings.DONE_MOVE_FINISHED]
    settle()
    next(b for b in card.buttons if b.text() == strings.DONE_MOVE_FINISHED).click()
    op = calls(writer, "set_tier")[0]
    assert op[1] == drag.ids_of(moved) and op[2]["tier"] == "graduated"
    assert moved.key not in [r.key for r in rows_of(win)]
    assert win.toasts.card.message == strings.DRAG_FINISHED.format(title=moved.title)
    assert wait_until(lambda: any(c.op == "set_tier" for c in writer.saved) and win.moves.tickets == [], 3)
    change = next(c for c in writer.saved if c.op == "set_tier")
    win.toasts.card.buttons[0].click()                                # the Finished toast's Undo
    assert writer.undone == [change]


def test_G3_2_up_next_done_with_a_file_left_still_marks_it_watched_and_hatos_mix_all_watched_says_why(world):
    """The fix touches only the all-watched Done: with a file left, Done marks Up Next's next file watched as before.
    hato's mix never finishes, so its all-watched Done offers nothing and the bar says why."""
    seed, win, writer = world()
    hero = rows_of(win)[0]
    nxt = hero.episodes[hero.next_index]
    assert not nxt.watched
    click_hero_done(win)
    assert calls(writer, "set_watched")[0] == ("set_watched", [nxt.id], {"on": True})
    settle()
    seed.library.commit(items=[{"id": e.id, "watched": 1} for e in hero.episodes])
    assert wait_until(lambda: all(e.watched for e in rows_of(win)[0].episodes), 3)
    writer.calls.clear()
    done = click_hero_done(win)
    assert done[2] == strings.ROWS_DONE_ALL_MIX_TIP                   # its tip never promises Finished
    assert calls(writer) == []
    assert win.bar_line.full() == strings.WELL_UNLIT_MIX


def test_G3_2_up_next_done_on_a_splits_first_part_all_watched_says_why_and_offers_no_finish(world):
    """A split's first part never finishes while a later part is in Current (its parts stay together): with every
    file watched, Up Next's Done writes nothing, shows no finish toast, and the bar says why."""
    seed, win, writer = world()
    rs = rows_of(win)
    i = next(n for n, r in enumerate(rs) if drag.split_first(rs, r))
    moved = rs[i]
    lift(win, i)
    move_global(win, row_point(win, 0))
    release_global(win, row_point(win, 0))                            # the first part is Up Next now
    assert rows_of(win)[0].key == moved.key and drag.split_first(rows_of(win), rows_of(win)[0])
    seed.library.commit(items=[{"id": e.id, "watched": 1} for e in moved.episodes])
    assert wait_until(lambda: all(e.watched for e in rows_of(win)[0].episodes), 3)
    QTest.qWait(theme.MOTION["click-swallow-after-drag"] + 30)
    settle()
    writer.calls.clear()
    click_hero_done(win)
    assert calls(writer) == []
    assert win.bar_line.full() == strings.WELL_UNLIT_SPLIT
    shown = win.toasts.card.message if win.toasts.card is not None else None
    assert shown != strings.DONE_ALL.format(n=len(moved.episodes))   # no finish offered


def test_split_first_is_a_part_with_a_later_part_in_current(world):
    seed, win, writer = world()
    rs = rows_of(win)
    parts = [r for r in rs if sum(1 for o in rs if o.work_id == r.work_id) > 1]
    first, second = parts[0], parts[1]
    assert drag.split_first(rs, first) and not drag.split_first(rs, second)


# --- files from Explorer and drags by item id ---------------------------------------------------------------------- #
_MIMES = []                                                            # (a drop event doesn't own its data)


def _drop_files(lst, paths, pos):
    """Files from Explorer, as Qt hands them: enter, move, then the drop."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    _MIMES.append(mime)
    copy, mods = Qt.DropAction.CopyAction, Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(lst.viewport(), QDragEnterEvent(pos, copy, mime, LEFT, mods))
    QApplication.sendEvent(lst.viewport(), QDragMoveEvent(pos, copy, mime, LEFT, mods))
    event = QDropEvent(QPointF(pos), copy, mime, LEFT, mods)
    QApplication.sendEvent(lst.viewport(), event)
    return event


def test_files_dropped_from_explorer_go_beside_the_row_under_the_hand(world, tmp_path):
    seed, win, writer = world(apply=False)
    lst = lst_of(win)
    path = tmp_path / "海辺の図書室 - 01.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
    rs = rows_of(win)
    rect = lst.visualRect(lst.model().index(3, 0))
    _drop_files(lst, [str(path)], QPoint(rect.center().x(), rect.top() + 3))      # over row 3's upper half
    op = calls(writer, "insert_at")[0]
    assert op[2]["files"] == [str(path)] and op[2]["tier"] == rs[2].tier
    assert op[2]["after_id"] == rs[2].episodes[-1].id and op[2]["near"]
    assert win.toasts.card.message == strings.DRAG_ADDED.format(name=path.name, n=4)
    writer.writable = False
    _drop_files(lst, [str(path)], QPoint(rect.center().x(), rect.top() + 3))
    assert len(calls(writer, "insert_at")) == 1                        # E4: refused


def test_a_drag_by_item_id_from_goal_leaves_the_goal_well_out_and_lands_where_dropped(world):
    seed, win, writer = world(apply=False)
    goal_ids = [r["id"] for r in seed.items if r["tier"] == "goal"][:3]
    rs = rows_of(win)
    assert win.moves.begin_by_id(goal_ids, "goal", "海辺の図書室", row_point(win, 2))
    assert win.dock.wells == ("soon", "finished")
    assert win.moves.lst.parting.src is None
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    op = calls(writer, "move")[0]
    assert op[1] == goal_ids and op[2]["after_id"] == rs[1].episodes[-1].id


# --- AD-7 and AD-14: the footer's slot and the quiet marks -------------------------------------------------------- #
def test_AD7_a_line_said_takes_the_slot_over_the_failure_line_then_gives_it_back(world):
    seed, win, writer = world()
    win.bar_failure.set_full(strings.BAR_FAILURE_PREFIX + "analyzer: exit 2")
    win._paint_slot()
    assert win.bar_line.isHidden() and not win.bar_failure.isHidden()
    win.say(strings.JOURNEY_NONE_TIP)
    assert not win.bar_line.isHidden() and win.bar_failure.isHidden()
    assert win.bar_line.full() == strings.JOURNEY_NONE_TIP
    win._message_until = time.monotonic() - 1                          # its time is up
    win._paint_slot()
    assert win.bar_line.isHidden() and not win.bar_failure.isHidden()


def test_AD14_a_quiet_marks_hover_never_reads_a_providers_line_as_markup(world):
    seed, win, writer = world()
    line = "Connect: <b>error</b> page"
    win._status_mark(win.bar_connect, line, strings.FOOT_CONNECT_TIP.format(line=line))
    tip = win.bar_connect.toolTip()
    assert "<b>" not in tip and "&lt;b&gt;" in tip


# --- L4: no stone hit before the sheet ---------------------------------------------------------------------------- #
def test_L4_without_the_stones_sheet_a_click_on_the_string_opens_the_row(world, monkeypatch):
    seed, win, writer = world()
    lst = lst_of(win)
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and part_rect(lst, n, "stone"))
    at = part_rect(lst, i, "stone")[1].center()
    monkeypatch.setattr(stones, "get", lambda *a, **k: None)
    assert not [p for p in lst.delegate.parts(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0)))
                if p[0] == "stone"]
    press(lst, at)
    release(lst, at)
    assert calls(writer) == [] and lst.model().open_key == lst.model().entries[i][1].key


# ================================================================================================================== #
# The real store: the writer, the numbers and the reader on one opener
# ================================================================================================================== #
from app import library_store as ls                                                  # noqa: E402
from app import settings_manager                                                     # noqa: E402
from tests.test_library_store_support import migrated                               # noqa: E402
from tests.test_services_moves import LockHolder, short_lock_wait, write_plan       # noqa: E402,F401


@pytest.fixture
def real(qapp):
    made = []

    def make(language="ja", plan=False):
        store = migrated(language)                                     # the outside writer's handle (another program)
        settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
        opener = moves_module.store_opener(language)
        plan_file = None
        if plan:
            plan_file = os.path.join(os.environ["SURASURA_TEST_ROOT"], "plan.json.gz")
            rels = [store.item(i)["rel_path"] for t in ("now", "soon", "goal") for i in store.ids(t)]
            tiers = [t for t in ("now", "soon", "goal") for _i in store.ids(t)]
            write_plan(plan_file, rels, tiers, language=language, n_words=400)
        held = []
        numbers = moves_module.Numbers(opener, language, plan_file=plan_file,
                                       on_change=lambda: held and held[0].refresh())
        reader = library_reader.LibraryReader(opener, language, numbers=numbers, poll=0.02)
        held.append(reader)
        reader.subscribe_moves(lambda _l, _v: numbers.resync())
        writer = moves_module.Writer(opener, language, journal_file=moves_module.journal_path(language),
                                     numbers=numbers, words=strings.MOVE_WORDS, retry=0.05)
        numbers.load()
        if plan:
            assert numbers.idle(60) and numbers.why() is None, numbers.why()
        services = shell.Services(library=reader, writer=writer)
        win = shell.open_window(qapp, services)
        win.resize(1280, 900)
        win.show()
        page = win.page_widgets["current"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 15)
        made.append((win, services, store))
        return store, win, writer
    yield make
    for win, services, store in made:
        win.close()
        services.shutdown(2.0)
        store.close()


def _drop_in_list(win, src, to):
    lift(win, src)
    target = row_point(win, to)
    move_global(win, target)
    release_global(win, target)


def test_real_store_a_drop_lands_in_the_store_and_its_numbers_come_at_the_drop(real):
    store, win, writer = real(plan=True)
    rs = rows_of(win)
    moved = rs[3]
    numbers = writer.numbers
    v = numbers.version
    times = []
    t0 = time.perf_counter()
    _drop_in_list(win, 3, 1)
    assert wait_until(lambda: numbers.version > v, 5)
    table = numbers()[1]
    want = sum(table[e.id][2] for e in moved.episodes)

    def shown():
        row = next(r for r in rows_of(win) if r.key == moved.key)
        return row.n_new == want
    assert wait_until(shown, 5)
    times.append((time.perf_counter() - t0) * 1000)
    print(f"drop → its numbers on screen: {times[0]:.1f} ms")
    assert times[0] <= 250, times                                     # functional (a shared machine); RP-6 is 50 ms
    assert wait_until(lambda: writer.pending() == 0, 5)
    ids_now = store.ids(moved.tier)
    first = ids_now.index(moved.episodes[0].id)
    assert ids_now[first - 1] == rs[0].episodes[-1].id                # after Up Next's last file, as dropped


def test_real_store_E5_a_busy_store_queues_the_drop_says_saving_and_lands_it_when_freed(real, short_lock_wait):
    store, win, writer = real()
    rs = rows_of(win)
    moved = rs[3]
    holder = LockHolder(store.db_path)
    try:
        _drop_in_list(win, 3, 1)
        assert rows_of(win)[1].key == moved.key                       # kept where the hand left it
        assert wait_until(lambda: moved.key in lst_of(win).saving, 5)   # *saving…* after 300 ms
        assert writer.pending() == 1
        # journalled: a crash keeps it (the *saving* mark is told just before the journal is written)
        assert wait_until(lambda: os.path.exists(moves_module.journal_path("ja")), 5)
        assert rows_of(win)[1].key == moved.key
    finally:
        holder.release()
    assert wait_until(lambda: writer.pending() == 0 and not lst_of(win).saving, 10)
    ids_now = store.ids(moved.tier)
    assert ids_now[ids_now.index(moved.episodes[0].id) - 1] == rs[0].episodes[-1].id
    assert wait_until(lambda: win.moves.expect is None and rows_of(win)[1].key == moved.key, 5)


def test_real_store_E21_undo_after_an_outside_change_says_cant_undo(real):
    store, win, writer = real()
    rs = rows_of(win)
    moved = rs[3]
    _drop_in_list(win, 3, 1)
    assert wait_until(lambda: writer.can_undo() and not win.moves.tickets, 5)
    store.move(drag.ids_of(moved), "goal")                            # another program moves the same item since
    win.toasts.card.buttons[0].click()                                # the drop's Undo
    assert wait_until(lambda: win.toasts.card.message == strings.MOVE_WORDS["cant_undo"], 5)
    assert store.item(moved.episodes[0].id)["tier"] == "goal"         # nothing written over the change


def test_real_store_ctrl_z_puts_the_order_back(real):
    store, win, writer = real()
    rs = rows_of(win)
    before = store.ids(rs[3].tier)
    _drop_in_list(win, 3, 1)
    assert wait_until(lambda: writer.can_undo() and not win.moves.tickets, 5)
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: store.ids(rs[3].tier) == before, 5)
    assert wait_until(lambda: [r.key for r in rows_of(win)] == [r.key for r in rs], 5)


def test_real_store_finished_with_its_new_cards_taken_out(real):
    store, win, writer = real()
    moved = rows_of(win)[2]
    lift(win, 2)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in drag.ids_of(moved)), 5)
    settle()
    win.toasts.card.buttons[2].click()                                # Take its new cards out
    assert wait_until(lambda: all(store.item(i)["in_learning_order"] == 0 for i in drag.ids_of(moved)), 5)


def test_real_store_files_dropped_from_explorer_are_copied_and_placed(real, tmp_path):
    store, win, writer = real()
    lst = lst_of(win)
    src = tmp_path / "海辺の図書室 第01話.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\n海辺で本を読む\n", encoding="utf-8")
    rs = rows_of(win)
    rect = lst.visualRect(lst.model().index(2, 0))
    _drop_files(lst, [str(src)], QPoint(rect.center().x(), rect.top() + 3))
    copy = os.path.join(store.data_dir, ls.CONTENT_FOLDER, ls.show_of_name(src.name), src.name)   # (SRC K3)
    assert wait_until(lambda: os.path.exists(copy) and writer.pending() == 0, 10)
    ids_now = store.ids(rs[1].tier)
    after = ids_now[ids_now.index(rs[1].episodes[-1].id) + 1]
    assert store.item(after)["rel_path"].endswith(src.name)
    assert os.path.exists(src)                                         # the user's own file stays where it was


def test_real_store_the_quit_waits_for_a_queued_move(real, short_lock_wait):
    store, win, writer = real()
    rs = rows_of(win)
    moved = rs[3]
    holder = LockHolder(store.db_path)
    _drop_in_list(win, 3, 1)
    assert writer.pending() == 1
    win.close()                                                        # the window stays while the move waits
    assert win.isVisible() and win._quit == "waiting"
    assert win.bar_line.full() == strings.MOVE_WORDS["saving"]
    holder.release()
    assert wait_until(lambda: not win.isVisible(), 10)
    ids_now = store.ids(moved.tier)
    assert ids_now[ids_now.index(moved.episodes[0].id) - 1] == rs[0].episodes[-1].id


# --- round 2 (the adversary, the intent keeper, the mutants) ------------------------------------------------------- #
def test_AD2_1_letting_go_outside_the_window_gives_the_drag_up_and_writes_nothing(world):
    seed, win, writer = world()
    lst = lst_of(win)
    before = [e[1].key for e in lst.model().entries]
    lift(win, 3)
    move_global(win, row_point(win, 6))
    below = win.mapToGlobal(QPoint(win.width() // 2, win.height() + 120))       # off the window's bottom edge
    move_global(win, below)
    release_global(win, below)
    assert win.moves.running is None and calls(writer) == [] and writer.held == 0
    assert [e[1].key for e in lst.model().entries] == before


def test_AD2_2_a_view_landing_between_the_press_and_the_lift_lifts_nothing(world):
    seed, win, writer = world()
    lst = lst_of(win)
    at = title_point(lst, 4)
    press(lst, at)
    view = win.page_widgets["current"].view_model
    keys = [r.key for r in view.rows]
    keys[3], keys[4] = keys[4], keys[3]                                         # another row now stands there
    win.moves._show(drag.reordered(view, keys))
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is None and writer.held == 0
    release(lst, at)
    assert calls(writer) == []


@pytest.mark.parametrize("which", ["split", "mix"])
def test_the_finished_tab_never_finishes_a_splits_first_part_or_hatos_mix(world, which):
    """(Mutants D09 / D10) The tab keeps the well's rule: a split's first part and hato's mix go back, with its tip."""
    seed, win, writer = world()
    rs = rows_of(win)
    i = next(n for n, r in enumerate(rs) if drag.split_first(rs, r)) if which == "split" else 0
    if which == "mix":
        assert drag.is_mix(rs[0])
    lift(win, i)
    tab = win.tab_buttons["finished"]
    at = tab.mapToGlobal(tab.rect().center())
    move_global(win, at)
    release_global(win, at)
    assert calls(writer) == [] and [r.key for r in rows_of(win)] == [r.key for r in rs]
    assert win.bar_line.full() == (strings.WELL_UNLIT_SPLIT if which == "split" else strings.WELL_UNLIT_MIX)


def test_a_release_on_another_rows_stone_marks_nothing(world):
    """(Mutant B02) A press on one stone let go on another row's stone: no click at all."""
    seed, win, writer = world()
    lst = lst_of(win)
    with_stone = [n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and part_rect(lst, n, "stone")]
    i, j = with_stone[0], with_stone[1]
    press(lst, part_rect(lst, i, "stone")[1].center())
    release(lst, part_rect(lst, j, "stone")[1].center())
    assert calls(writer) == []


def test_a_press_on_a_button_never_starts_a_drag(world):
    """(Mutant B03) ✓ Done on Up Next pressed and moved 6 px: no lift, and no Done on a release elsewhere."""
    seed, win, writer = world()
    lst = lst_of(win)
    at = part_rect(lst, 0, "done")[1].center()
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"] + 4))
    assert win.moves.running is None and writer.held == 0
    release(lst, at + QPoint(0, 200))
    assert calls(writer) == []


def test_E4_files_dropped_on_a_read_only_store_are_refused_with_the_reason(world, tmp_path):
    """(Mutant E02) The window refuses before the writer is asked, and says why."""
    seed, win, writer = world(apply=False)
    writer.writable, writer.why = False, "damaged"
    lst = lst_of(win)
    path = tmp_path / "海辺の図書室 - 01.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
    rect = lst.visualRect(lst.model().index(3, 0))
    _drop_files(lst, [str(path)], QPoint(rect.center().x(), rect.top() + 3))
    assert calls(writer) == []
    assert win.bar_line.full() == strings.DRAG_REFUSED.format(reason=strings.READ_ONLY_REASONS["damaged"])


def test_AD2_5_ctrl_z_while_a_finished_choice_waits_takes_the_choice_back_never_given(world):
    seed, win, writer = world()
    writer.stuck = True
    lift(win, 5)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    settle()
    win.toasts.card.buttons[2].click()                                # *Take its new cards out*, waiting on the drop
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    writer.free()
    settle(150)
    assert calls(writer, "finish") == []                              # the newest — the choice — never given
    assert calls(writer, "set_tier") and None not in writer.undone    # the drop stands; nothing older undone


def test_AD2_6_ctrl_z_while_a_drop_waits_undoes_that_drop_as_it_lands_never_the_one_before(world):
    seed, win, writer = world()
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    assert wait_until(lambda: writer.saved, 3)
    settle(80)
    writer.stuck = True                                               # a busy store (or an Explorer copy running)
    lift(win, 5)
    target = row_point(win, 1)
    move_global(win, target)
    release_global(win, target)
    settle(80)
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert writer.undone == []                                        # asked: undone as it lands
    writer.free()
    assert wait_until(lambda: writer.undone, 3)
    assert writer.undone == [writer.saved[-1]] and writer.undone[0] is not writer.saved[0]


def test_R3_S2_a_lift_that_fails_lets_the_drag_go_and_holds_nothing(world, monkeypatch):
    seed, win, writer = world()
    lst = lst_of(win)

    def broken(*_a, **_k):
        raise RuntimeError("no picture")
    monkeypatch.setattr(drag.Ghost, "set_picture", broken)
    at = title_point(lst, 4)
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is None and writer.held == 0 and lst.parting is None
    seed.library.commit(items=[{"id": rows_of(win)[3].episodes[0].id, "watched": 1}])   # views still come in
    assert wait_until(lambda: rows_of(win)[3].episodes[0].watched, 3)


# ================================================================================================================== #
# LM11b G5: one show inside a group, all watched (GW-2 ⭐ A: the toast offers *Move {show} to Finished*)
# ================================================================================================================== #
from app.services import view_rows as vr                                            # noqa: E402
from tests import test_view_rows as tvr                                             # noqa: E402

SHOW_A, SHOW_B = "星降る街の小さな工房", "雲の上の郵便屋さん"


def _group_view(a_watched=2, b_watched=0, source=None):
    """A group (piece 10): SHOW_A Ep 1–3 (its first `a_watched` watched), SHOW_B Ep 7–8 (its first `b_watched`
    watched); under it 白銀の書庫番 Part 1 as a run of its own. `source` "hato": the group's first show under hato's
    folder (hato's mix)."""
    tvr.WORKS.clear()
    tvr.work(1, SHOW_A)
    tvr.work(2, SHOW_B)
    tvr.work(3, "白銀の書庫番", media="lightnovel")
    folder = "HighPriority/Hato/" if source == "hato" else "HighPriority/"
    a = {k: {"watched": int(k < a_watched), "rel_path": folder + n} for k, n in enumerate(tvr.eps(SHOW_A, 1, 3))}
    b = {k: {"watched": 1} for k in range(b_watched)}
    items = tvr.items_of([("now", 1, 10, tvr.eps(SHOW_A, 1, 3), a), ("now", 2, 10, tvr.eps(SHOW_B, 7, 8), b),
                          ("now", 3, 11, ["白銀の書庫番 01 章.epub"], {0: {"source_type": "epub"}})])
    pieces = {10: {"id": 10, "title": None, "kind": "group"}, 11: {"id": 11, "title": None, "kind": "run"}}
    return vr.build(items, dict(tvr.WORKS), {"mine_line": 20}, pieces=pieces)


def _show_group(win, **kw):
    """The group's view shown in the window (the fake writer writes nothing back: no reader view replaces it)."""
    win.moves._show(_group_view(**kw))
    for _ in range(5):
        QApplication.processEvents()
    return rows_of(win)[0]


def _shown_buttons(card):
    return [b.text() for b in card.buttons if not b.isHidden()]


def test_LM11b_G5_the_whole_group_watched_offers_the_rows_own_finish(world):
    """Every show of the group watched by this Done: the row's own toast (*All 5 watched*), its *Move to Finished*
    taking the whole row — never the one show's offer."""
    seed, win, writer = world(apply=False)
    row = _show_group(win, a_watched=3, b_watched=1)
    win.moves.done(row, row.episodes[-1])
    card = win.toasts.card
    assert card.message == strings.DONE_ALL.format(n=5)
    assert _shown_buttons(card) == [strings.TOAST_UNDO, strings.DONE_MOVE_FINISHED]
    settle()
    card.buttons[1].click()
    assert calls(writer, "set_tier")[0][1] == drag.ids_of(row)
    assert row.key not in [r.key for r in rows_of(win)]


def test_LM11b_G5_a_show_with_a_file_left_hatos_mix_a_run_and_a_cache_from_before_offer_no_show_finish():
    """`drag.show_finished` (pure): offered only for a group's show whose every other episode is watched while another
    show still waits; never for hato's mix (it never finishes), a run (the store makes a group of one show a run: its
    last Done is the row's own finish), or episodes from a cache from before (no show to name)."""
    row = _group_view(a_watched=2).rows[0]
    a = [e for e in row.episodes if e.work_id == 1]
    assert drag.show_finished(row, a[-1]) == (SHOW_A, [e.id for e in a])
    assert drag.show_finished(_group_view(a_watched=1).rows[0], a[-1]) is None           # SHOW_A's Ep 2 still waits
    mix = _group_view(a_watched=2, source="hato").rows[0]
    assert mix.source == "hato" and drag.show_finished(mix, mix.episodes[2]) is None
    assert drag.show_finished(row._replace(group=False), a[-1]) is None
    old = row._replace(episodes=tuple(e._replace(work_id=None, show=None) for e in row.episodes))
    assert drag.show_finished(old, old.episodes[2]) is None
    every = _group_view(a_watched=3, b_watched=1).rows[0]
    assert drag.show_finished(every, every.episodes[-1]) is None                         # all of it: the row's own


def _real_group(real):
    """The real store: Current's first two shows grouped into one row, the first's Ep 1–3 watched; its Ep 4 marked
    (the Done). -> (store, win, writer, the first show's row, the second's, the group row before the Done)."""
    store, win, writer = real()
    rs = rows_of(win)
    first, second = rs[0], rs[1]
    store.group(piece_ids=[first.piece_id, second.piece_id])
    assert wait_until(lambda: rows_of(win)[0].group, 5)
    store.set_watched(drag.ids_of(first)[:-1])
    assert wait_until(lambda: rows_of(win)[0].n_watched == 3, 5)
    row = rows_of(win)[0]
    last = next(e for e in row.episodes if e.id == drag.ids_of(first)[-1])
    win.moves.done(row, last)
    return store, win, writer, first, second, row


def _holding(win, ids):
    return next((r for r in rows_of(win) if [e.id for e in r.episodes] == ids), None)


def test_real_store_LM11b_G5_a_show_finished_inside_a_group_lands_in_finished_under_its_own_name(real, monkeypatch):
    """GW-2 ⭐ A on the real store: the first show's last episode marked while the second's wait — its watched written
    as any Done and the toast offers *Move <show> to Finished*. Pressed: only its four ids go, in one call, with the
    Finished toast's Keep / Leave its new cards out (D14); they land in Finished as a run of their own show, and
    Current's row holds the second show's four, built by the view's own rule (its cover and work the second show's).
    Wrong, a finished show would sit in Current until the whole group is done — or the press would finish the second
    show unwatched too."""
    store, win, writer, first, second, row = _real_group(real)
    a, b = drag.ids_of(first), drag.ids_of(second)
    show = row.episodes[3].show
    card = win.toasts.card
    assert card.message == strings.DONE_SHOW_IN_GROUP.format(show=show, n=4)
    assert _shown_buttons(card) == [strings.TOAST_UNDO, strings.DONE_MOVE_SHOW_FINISHED.format(show=show)]
    assert card.buttons[1].toolTip() == strings.DONE_MOVE_SHOW_FINISHED_TIP.format(show=show, n=4)
    assert wait_until(lambda: store.item(a[-1])["watched"] == 1, 5)
    tiers = []
    monkeypatch.setattr(writer, "set_tier", lambda ids, tier, label=None, real=writer.set_tier:
                        tiers.append((list(ids), tier)) or real(ids, tier, label=label))
    settle()
    card.buttons[1].click()
    assert tiers == [(a, drag.FINISHED)]
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in a), 5)
    assert {store.item(i)["work_id"] for i in a} == {first.work_id}
    assert len({store.item(i)["piece_id"] for i in a}) == 1                  # one run, its own show's
    assert all(store.item(i)["tier"] == "now" for i in b)
    assert wait_until(lambda: win.moves.expect is None and _holding(win, b) is not None, 5)
    kept = _holding(win, b)
    assert (kept.work_id, kept.cover.work_id, kept.group) == (second.work_id, second.work_id, False)
    assert not any(set(a) & {e.id for e in r.episodes} for r in rows_of(win))
    assert win.toasts.card.message == strings.DRAG_FINISHED.format(title=show)
    win.toasts.card.buttons[2].click()                                # Leave its new cards out
    assert wait_until(lambda: all(store.item(i)["in_learning_order"] == 0 for i in a), 5)
    assert all(store.item(i)["in_learning_order"] == 1 for i in b)


def test_real_store_LM11b_G5_while_the_store_is_busy_the_row_is_the_readers_own_and_a_stale_view_is_held(
        real, short_lock_wait):
    """The press while another program holds the store: the finish waits in the writer's queue (*saving…*), but the
    row on screen is already the second show's alone — built by the reader by the view's own rule (`expect`): its
    work, cover and status the second show's, never the group's old ones for as long as the store stays busy. A view
    still holding the first show's episodes is held. Released: the finish lands and the same row stands."""
    store, win, writer, first, second, row = _real_group(real)
    a, b = drag.ids_of(first), drag.ids_of(second)
    assert wait_until(lambda: store.item(a[-1])["watched"] == 1 and writer.pending() == 0, 5)
    settle()
    before = win.page_widgets["current"].view_model
    holder = LockHolder(store.db_path)
    try:
        win.toasts.card.buttons[1].click()
        assert win.moves.view_in(before) is None                       # still holding the first show: held
        assert wait_until(lambda: _holding(win, b) is not None, 5)
        kept = _holding(win, b)
        assert (kept.work_id, kept.cover.work_id, kept.title) == (second.work_id, second.work_id, second.title)
        assert kept.status == second.status
        settle(400)
        assert writer.pending() == 1 and all(store.item(i)["tier"] == "now" for i in a)
        assert _holding(win, b) is not None                            # past the settle: still the reader's own row
    finally:
        holder.release()
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in a), 10)
    assert wait_until(lambda: win.moves.expect is None and not win.moves.reader._expected, 5)
    assert _holding(win, b) is not None and not any(set(a) & {e.id for e in r.episodes} for r in rows_of(win))


# --- LM11b review fix round (package B): the settle and the reader's build of a show taken off ------------------- #
def _finish_show_stuck(world, monkeypatch):
    """A group shown, the store busy (the fake writer's commands wait), *Move SHOW_A to Finished* given -> (win, writer,
    the reader's `expect` calls)."""
    _seed, win, writer = world(apply=False)
    row = _show_group(win, a_watched=2)
    told = []
    monkeypatch.setattr(win.moves.reader, "expect", lambda tiers: told.append(tiers))
    writer.stuck = True
    a = [e.id for e in row.episodes if e.work_id == 1]
    win.moves.finish_show(row, SHOW_A, a)
    assert writer.pending() == 1 and told == [{i: drag.FINISHED for i in a}]
    return win, writer, told


def test_LM11b_H_T1_a_writer_stopped_with_moves_left_ends_the_settle_and_lets_the_readers_build_go(world, monkeypatch):
    """H-T1: the settle waits while the writer has moves pending — unbounded by design (a busy store's moves are queued,
    never dropped) — but a writer stopped (a language switch, the quit) lands nothing more here: the settle ends, the
    window's order is let go and the reader's build of the show taken off goes with it. Wrong, the timer ticked for
    good and the reader kept building the show in Finished."""
    win, writer, told = _finish_show_stuck(world, monkeypatch)
    moves = win.moves
    settle(drag.D["settle-ms"] * 2)
    assert moves._settle.isActive() and told[-1] is not None          # waiting on the busy store, as designed
    writer.stopped = lambda: True                                    # let go: its move stays in its journal
    settle(drag.D["settle-ms"] * 3)
    assert not moves._settle.isActive() and moves.expect is None and told[-1] is None


def test_LM11b_H_T1_a_closed_controller_stops_its_settle_and_a_late_tick_shows_nothing(world, monkeypatch):
    """H-T1: the window lets its controller go (its close, a language switch): the settle stops at once, and a tick
    already queued past it shows nothing of that controller's."""
    win, writer, told = _finish_show_stuck(world, monkeypatch)
    moves = win.moves
    shown = []
    monkeypatch.setattr(moves, "_show", lambda view: shown.append(view))
    moves.close()
    assert not moves._settle.isActive()
    moves._settled()
    assert shown == [] and not moves._settle.isActive()


def test_LM11b_H_C3_another_command_landing_as_nothing_never_lets_the_readers_build_go_before_its_own_lands(
        world, monkeypatch):
    """H-C3: a command that landed as nothing (`on_reread`) while the show's finish still waits for the busy store lets
    the window's order go, never the reader's build of the show in Finished: the show stays off the group row until its
    own command lands — then it goes. Wrong, the show came back into the group before its finish landed."""
    win, writer, told = _finish_show_stuck(world, monkeypatch)
    moves = win.moves
    moves._reread()                                                   # the other command's answer: nothing to change
    assert writer.pending() == 1 and told[-1] is not None
    writer.free()                                                     # the finish lands
    assert wait_until(lambda: told[-1] is None and not moves.tickets, 3)


def test_LM11b_H_C3_the_finish_landing_as_nothing_lets_the_readers_build_go_though_another_command_still_waits(
        world, monkeypatch):
    """H-C3, the other side: the show's own finish lands as nothing (the store had nothing to change) while another
    command still waits for the busy store — the reader's build of the show in Finished goes now, never only once the
    queue is empty. Wrong, the show stayed off its group row for as long as the other command waited."""
    win, writer, told = _finish_show_stuck(world, monkeypatch)
    moves = win.moves
    writer.move([987001], "goal")                                     # another command, waiting behind it
    change, ticket = writer._waiting.pop(0)                           # the finish's own answer: nothing to change
    writer.nothing.add(change.op)
    monkeypatch.setattr(writer, "landed_empty", lambda: [ticket], raising=False)
    writer._land(change, ticket)
    assert wait_until(lambda: told[-1] is None, 3)
    assert writer.pending() == 1 and ticket not in moves.tickets


def test_LM11b_a_landed_show_finish_leaves_nothing_behind_for_the_next_move(world, monkeypatch):
    """The show taken off its row is the window's order while its finish waits, and goes with it: once it landed, the
    next move the window makes ahead of the store shows a view that holds that show's episodes again (an Undo of the
    finish), never holding it back for a show it no longer takes off. Wrong, every view was held until that move
    settled."""
    win, writer, told = _finish_show_stuck(world, monkeypatch)
    moves = win.moves
    writer.free()
    assert wait_until(lambda: told[-1] is None and moves.expect is None and not moves.tickets, 3)
    view = _group_view(a_watched=2)                                   # the group holding SHOW_A's episodes again
    moves._ahead(view)                                                # the next move, ahead of the store
    assert moves.view_in(view) is not None


def test_LM11b_a_settle_reached_while_a_drag_runs_keeps_the_held_view_under_the_hand(world):
    """E6: the settle of an earlier move can come while the next drag runs — the reader's view it held stays held (the
    rows under the hand never change), shown at the drop. Wrong, the held view was shown mid-drag."""
    _seed, win, _writer = world()
    lift(win, 3)
    moves = win.moves
    shown = win.page_widgets["current"].view_model
    view = shown._replace(rows=shown.rows[::-1])
    moves.held = view
    moves._let_go()
    assert moves.held is view and win.page_widgets["current"].view_model is shown
    moves.cancel()


def test_LM11b_every_write_landed_asks_the_reader_for_the_stores_own_view_again(world, monkeypatch):
    """AD2-4: once every write landed the settle asks the reader to publish the store's view again — changed or not —
    so a row the store placed otherwise than the window drew it comes back to where it is. Wrong, the window kept its
    own drawing."""
    _seed, win, writer = world()
    asked = []
    monkeypatch.setattr(win.moves.reader, "republish", lambda: asked.append(1))
    rs = rows_of(win)
    win.moves.nudge(rs[3], 1)
    assert calls(writer)
    assert wait_until(lambda: asked and win.moves.expect is None, 5)
