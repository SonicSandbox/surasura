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

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import drag, freeze, motion, rows, shell, stones, strings
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
from tests.test_library_store_support import migrated                               # noqa: E402
from tests.test_services_moves import LockHolder, short_lock_wait, write_plan       # noqa: E402,F401


@pytest.fixture
def real(qapp):
    made = []

    def make(language="ja", plan=False):
        store = migrated(language)                                     # the outside writer's handle (another program)
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
