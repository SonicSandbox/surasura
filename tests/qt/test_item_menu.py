"""The rest of Current's ⋯, the ✂ seam and drop-to-join (W3.2 Q8, `app/qt/item_menu.py`; RUNBOOK §5a IK-4; the window's
spec 05 §5.4, A2 G3, A3 `split`, 06 E4, E22) — on the window's seed (Japanese titles, its show split in two parts:
Ep 1–4 third in Current, Ep 5–8 seventh) through a recording writer, and where the store's own answers matter (a split
and its Undo, a join across sections in episode order and its one Undo, the type, the pin, a remove and its Undo) on a
real migrated store with the real writer.

What a wrong answer would cost a learner:
  * a split or a join that can't be undone, or a join that leaves the episodes out of order (Ep 5–8 before Ep 1–4);
  * a part from Finished joined into Finished instead of where he asked for it (E22);
  * a drag over the other part opening a gap (the rows must hold still) or dropping it beside it instead of joining;
  * *Remove…* writing without his yes, or Esc removing it anyway;
  * a write offered on a library that can't be saved (E4), or ⋯ showing the opposite of the pin the store holds;
  * an entry with no tooltip, or a seam that never shows where the hand is.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QAction, QColor, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import path_utils
from app.qt import drag, item_menu, rows, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import (FakeWriter, lift, move, move_global, open_window, part_rect, press, real,  # noqa: F401
                                release, release_global, row_point, settle)
from tests.qt.test_wiring import _connected


# --- a recording writer with the menu's commands -------------------------------------------------------------------- #
class ItemWriter(FakeWriter):
    def pin(self, ids, on=True, label=None):
        return self._put("pin", ids, label, on=on)

    def split(self, piece_id, at_item_id, label=None):
        return self._put("split", [at_item_id], label, piece_id=piece_id)

    def join(self, piece_ids, label=None, ahead=False):
        return self._put("join", [], label, piece_ids=list(piece_ids), ahead=ahead)

    def set_media_type(self, work_ids, media_type, label=None):
        return self._put("set_media_type", [], label, work_ids=list(work_ids), media_type=media_type)

    def remove(self, ids, label=None):
        return self._put("remove", ids, label)


@pytest.fixture
def world(qapp):
    made = []

    def make(writable=True):
        from tests.fixtures import window_seed
        seed = window_seed.build()
        writer = ItemWriter(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
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


def calls(writer, op=None):
    return [c for c in writer.calls if op is None or c[0] == op]


def split_parts(win):
    """The seed's show in two parts: (its Ep 1–4 row's place, its Ep 5–8 row's place)."""
    rs = rows_of(win)
    works = {}
    for i, r in enumerate(rs):
        if r.work_id is not None and r.piece_id is not None:
            works.setdefault(r.work_id, []).append(i)
    a, b = next(v for v in works.values() if len(v) == 2)
    assert [e.number for e in rs[a].episodes] == [1, 2, 3, 4] and [e.number for e in rs[b].episodes] == [5, 6, 7, 8]
    return a, b


def names(entries):
    return [e.name for e in entries]


def open_row(win, i):
    lst = lst_of(win)
    lst.toggle(lst.model().index(i, 0))
    settle()
    assert lst.model().open_key == rows_of(win)[i].key


def seams(lst, i):
    entry = lst.model().entries[i]
    return [p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))) if p[0] == "seam"]


def hover(lst, pos):
    move(lst, pos, buttons=Qt.MouseButton.NoButton)
    settle(20)


def middle_point(win, i):
    """The global point over the middle of row `i` (where a part joins; its edges are a move)."""
    lst = lst_of(win)
    return lst.viewport().mapToGlobal(lst.visualRect(lst.model().index(i, 0)).center())


def lit(lst, rect, colour, tolerance=40):
    """Pixels inside `rect` (the viewport's) close to `colour`."""
    img = lst.viewport().grab(rect).toImage()
    want = QColor(colour)
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixelColor(x, y)
            if abs(px.red() - want.red()) + abs(px.green() - want.green()) + abs(px.blue() - want.blue()) < tolerance:
                n += 1
    return n


# --- ⋯: what it lists, in order -------------------------------------------------------------------------------------- #
def test_the_menu_lists_the_moves_then_study_type_split_join_folder_and_remove_last_after_a_separator(world):
    _seed, win, _w = world()
    a, _b = split_parts(win)
    row = rows_of(win)[a]
    assert names(win.items.entries(row)) == ["pin", "type", "split", "join", "cover", "folder", "remove"]   # W3.2 L3
    m = win.items.menu(row, win.mapToGlobal(QPoint(300, 300)))
    acts = m.actions()
    texts = [x.text() for x in acts]
    moves = [label for _n, label, _t, _ok in win.moves.menu_entries(row)]
    assert texts[:len(moves)] == moves                               # the moves first, as W3.1a built them
    assert acts[-2].isSeparator() and texts[-1] == strings.ITEM_MENU["remove"][0]      # Remove… last, apart
    m.close()


def test_every_entry_and_every_submenu_entry_has_a_tooltip_and_is_wired(world):
    # D17: every control tipped; the wiring check's rule (a submenu's own action counts as wired by its menu)
    _seed, win, _w = world()
    a, _b = split_parts(win)
    m = win.items.menu(rows_of(win)[a], win.mapToGlobal(QPoint(300, 300)))
    walked = 0
    for act in m.actions():
        if act.isSeparator():
            continue
        subs = act.menu().actions() if act.menu() is not None else []
        for x in [act] + subs:
            walked += 1
            assert x.toolTip().strip(), x.text()
            assert _connected(x), x.text()
    assert walked > 20                                               # the 12 types and the split list included
    m.close()


def test_a_menu_closed_is_gone_so_the_windows_wiring_walk_never_meets_its_separator(world):
    _seed, win, _w = world()
    m = win.items.menu(rows_of(win)[1], win.mapToGlobal(QPoint(300, 300)))
    m.close()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not [x for x in win.findChildren(QAction) if x.isSeparator()]


def test_C4_two_opens_make_one_native_window_its_actions_the_entries_and_a_pick_through_it_still_lands(world):
    """C4 (M4.1 row 4): every ⋯ made a new menu — a new native window, its first show most of the 15–30 ms an open
    took. The list keeps one, emptied as it hides. What it could break: an open showing the last one's entries, or a
    pick lost because its action went with the hide."""
    _seed, win, writer = world()
    rs = rows_of(win)
    at = win.mapToGlobal(QPoint(300, 300))
    first = win.items.menu(rs[5], at)
    native = int(first.winId())
    first.close()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    m = win.items.menu(rs[4], at)
    assert m is first and int(m.winId()) == native                    # one native window, opened again
    want = [label for _n, label, _t, _ok in win.moves.menu_entries(rs[4])] +         [e.label for e in win.items.entries(rs[4])]
    assert [a.text() for a in m.actions() if not a.isSeparator()] == want
    assert wait_until(m.isVisible, 2)
    pin = next(a for a in m.actions() if a.text() == strings.ITEM_MENU["pin"][0])
    m.setActiveAction(pin)
    QTest.keyClick(m, Qt.Key.Key_Return)                              # the menu hides, then its action triggers
    assert wait_until(lambda: calls(writer, "pin"), 5)
    assert calls(writer, "pin")[-1][1] == drag.ids_of(rs[4])
    assert not m.isVisible() and m.actions() == []                    # closed, it holds nothing
    assert win.moves.menu(rs[4], at) is m                             # the moves' own ⋯ is the same list's one
    m.close()


def test_IKB10_esc_closes_the_kept_menu_and_it_opens_again_with_the_next_rows_entries(world):
    """IKB-10 (C4's kept menu): it only hides on a close, so Esc must still close it (every window closes on Esc), it
    must hold nothing once closed, and the next ⋯ must open the same menu with that row's entries, not the last
    row's."""
    _seed, win, writer = world()
    rs = rows_of(win)
    at = win.mapToGlobal(QPoint(300, 300))
    m = win.items.menu(rs[5], at)
    native = int(m.winId())
    assert wait_until(m.isVisible, 2)
    QTest.keyClick(m, Qt.Key.Key_Escape)
    assert wait_until(lambda: not m.isVisible(), 2)                   # Esc closed it
    assert m.actions() == []                                          # and nothing of rs[5]'s open is left in it
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    again = win.items.menu(rs[4], at)
    assert again is m and int(again.winId()) == native               # the same kept menu, its native window kept
    want = [label for _n, label, _t, _ok in win.moves.menu_entries(rs[4])] + [e.label for e in win.items.entries(rs[4])]
    assert [a.text() for a in again.actions() if not a.isSeparator()] == want     # fresh: rs[4]'s entries
    assert wait_until(again.isVisible, 2)
    QTest.keyClick(again, Qt.Key.Key_Escape)                          # and Esc closes it again, writing nothing
    assert wait_until(lambda: not again.isVisible(), 2)
    assert again.actions() == [] and calls(writer) == []


def test_the_hovered_ellipsis_of_a_current_row_opens_this_menu(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    i = 4
    lst.setCurrentIndex(lst.model().index(i, 0))
    more = part_rect(lst, i, "more")[1].center()
    press(lst, more)
    release(lst, more)
    m = win.items.last_menu
    assert m is not None and m.isVisible()
    assert strings.ITEM_MENU["remove"][0] in [x.text() for x in m.actions()]
    m.close()


# --- Study its cards first ↔ Done with its cards ----------------------------------------------------------------------- #
def test_study_first_pins_and_done_unpins_each_with_its_toast_and_undo(world):
    _seed, win, writer = world()
    row = rows_of(win)[4]
    assert not row.studying and "pin" in names(win.items.entries(row))
    win.items.menu_pick(row, "pin")
    assert calls(writer, "pin") == [("pin", drag.ids_of(row), {"on": True})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_PINNED.format(title=row.title), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()                               # Undo: that change
    assert writer.undone and writer.undone[-1].op == "pin"
    studying = row._replace(studying=True)
    assert "unpin" in names(win.items.entries(studying))
    win.items.menu_pick(studying, "unpin")
    assert calls(writer, "pin")[-1][2] == {"on": False}


# --- What is it? -------------------------------------------------------------------------------------------------------- #
def test_N3_the_menu_writes_through_the_windows_writer_as_it_stands_never_the_one_it_was_made_with(world):
    seed, win, writer = world()
    row = rows_of(win)[1]
    other = ItemWriter(seed.library, apply=False)
    win.services.writer = other                                      # (a language switch: another library's)
    win.language = "zh"
    win.items.pin(row, True)
    assert calls(writer, "pin") == [] and calls(other, "pin") == [("pin", drag.ids_of(row), {"on": True})]
    assert win.items.language == "zh"


def test_what_is_it_offers_every_store_type_the_rows_own_checked_and_sets_it_for_its_title(world):
    _seed, win, writer = world()
    a, _b = split_parts(win)
    row = rows_of(win)[a]
    kinds = next(e for e in win.items.entries(row) if e.name == "type").children
    assert [k.payload for k in kinds] == list(ls.MEDIA_TYPES) + [None]
    assert [k.payload for k in kinds if k.checked] == [row.media] == ["anime"]
    win.items.menu_pick(row, "type-to", "drama")
    assert calls(writer, "set_media_type") == [("set_media_type", [], {"work_ids": [row.work_id],
                                                                      "media_type": "drama"})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_TYPE_DONE.format(
        title=row.title, kind=strings.ITEM_TYPES["drama"]), 5)
    win.items.menu_pick(row, "type-to", None)                        # back to Surasura's guess
    assert calls(writer, "set_media_type")[-1][2]["media_type"] is None


# --- ✂ Split here: the seam and ⋯ -------------------------------------------------------------------------------------- #
def test_an_opened_part_has_a_seam_between_each_two_episodes_and_a_closed_one_none(world):
    _seed, win, _w = world()
    a, _b = split_parts(win)
    lst = lst_of(win)
    assert seams(lst, a) == []
    open_row(win, a)
    s = seams(lst, a)
    row = rows_of(win)[a]
    assert [p[3].id for p in s] == [e.id for e in row.episodes[1:]]
    assert all(p[2] for p in s)                                      # each with its tip


def test_the_seam_lights_under_the_hand_and_a_click_on_it_splits_there(world):
    _seed, win, writer = world()
    a, _b = split_parts(win)
    lst = lst_of(win)
    open_row(win, a)
    row = rows_of(win)[a]
    seam = seams(lst, a)[1]                                          # between Ep 2 and Ep 3
    before = lit(lst, seam[1], rows.c("accent").name())
    hover(lst, seam[1].center())
    assert lst.seam == (row.key, row.episodes[2].id)
    settle()
    assert lit(lst, seam[1], rows.c("accent").name()) > before + 10  # painted: the dashed line and its chip
    press(lst, seam[1].center())
    release(lst, seam[1].center())
    assert calls(writer, "split") == [("split", [row.episodes[2].id], {"piece_id": row.piece_id})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SPLIT_DONE.format(
        title=row.title, rest="Ep 3–4"), 5)
    assert lst.seam is None and calls(writer, "move") == []          # nothing moves


def test_split_here_from_the_menu_splits_after_the_episode_the_hand_was_on(world):
    _seed, win, writer = world()
    a, _b = split_parts(win)
    lst = lst_of(win)
    open_row(win, a)
    row = rows_of(win)[a]
    stone = next(p for p in lst.delegate.parts(lst.model().entries[a], lst.visualRect(lst.model().index(a, 0)))
                 if p[0] == "stone" and p[3].id == row.episodes[0].id)
    hover(lst, stone[1].center())                                    # the hand on Ep 1
    entry = next(e for e in win.items.entries(row) if e.name == "split")
    assert entry.children is None and entry.payload.id == row.episodes[1].id
    win.items.menu_pick(row, "split", entry.payload)
    assert calls(writer, "split")[-1] == ("split", [row.episodes[1].id], {"piece_id": row.piece_id})


def test_split_here_on_a_closed_row_asks_after_which_episode(world):
    _seed, win, writer = world()
    a, _b = split_parts(win)
    row = rows_of(win)[a]
    entry = next(e for e in win.items.entries(row) if e.name == "split")
    assert [c.label for c in entry.children] == [strings.ITEM_SPLIT_AFTER.format(ep=e.label) for e in row.episodes[:-1]]
    win.items.menu_pick(row, "split", entry.children[2].payload)     # after Ep 3
    assert calls(writer, "split")[-1][1] == [row.episodes[3].id]


def test_B2_2_a_show_the_soon_line_runs_through_splits_each_episode_by_its_own_piece(world):
    """The row of a show the Soon line cuts holds two pieces (P-LF-16: NOW's up to `soon_from`, then Soon's own). ✂ on
    a Soon episode splits Soon's piece — never NOW's, where the store finds no such item and does nothing — and the seam
    the line already makes is never offered: no menu entry, no seam, and asked anyway no toast and no Undo."""
    _seed, win, writer = world()
    a, _b = split_parts(win)
    open_row(win, a)
    row = rows_of(win)[a]._replace(soon_from=2, soon_piece=987654)    # Ep 1–2 NOW's piece, Ep 3… Soon's
    assert len(row.episodes) >= 4
    entry = next(e for e in win.items.entries(row) if e.name == "split")
    offered = [c.payload.id for c in entry.children]
    assert row.episodes[2].id not in offered and row.episodes[1].id in offered and row.episodes[3].id in offered
    lst = lst_of(win)
    seams = [p[3].id for p in lst.delegate._seam_parts(row, lst.visualRect(lst.model().index(a, 0)))]
    assert row.episodes[2].id not in seams and row.episodes[3].id in seams
    toast = win.toasts.card.message if win.toasts.card is not None else None
    assert win.items.split(row, row.episodes[2]) is None and calls(writer, "split") == []
    settle()
    assert (win.toasts.card.message if win.toasts.card is not None else None) == toast     # no toast, no Undo
    win.items.split(row, row.episodes[3])
    assert calls(writer, "split")[-1] == ("split", [row.episodes[3].id], {"piece_id": 987654})
    win.items.split(row, row.episodes[1])
    assert calls(writer, "split")[-1] == ("split", [row.episodes[1].id], {"piece_id": row.piece_id})


def test_a_single_file_and_hatos_mix_offer_no_split_and_no_seam(world):
    _seed, win, _w = world()
    rs = rows_of(win)
    single = next(r for r in rs if len(r.episodes) == 1)
    assert "split" not in names(win.items.entries(single))
    hero = rs[0]
    assert drag.is_mix(hero) and "split" not in names(win.items.entries(hero))
    open_row(win, 0)
    assert seams(lst_of(win), 0) == []


# --- Join with… (E22) and drop-to-join (G3) -------------------------------------------------------------------------- #
def test_join_with_lists_the_other_part_not_next_to_it_with_its_episodes_and_place(world):
    _seed, win, _w = world()
    a, b = split_parts(win)
    rs = rows_of(win)
    join = next(e for e in win.items.entries(rs[a]) if e.name == "join")
    assert [c.label for c in join.children] == [strings.ITEM_JOIN_PART.format(
        range="Ep 5–8", where=strings.ITEM_JOIN_WHERE["now"].format(n=b + 1))]
    assert "join" not in names(win.items.entries(rs[4]))             # a title in one part: nothing to join


def test_joining_the_later_part_onto_the_earlier_is_one_join_with_the_target_first(world):
    _seed, win, writer = world()
    a, b = split_parts(win)
    rs = rows_of(win)
    payload = next(e for e in win.items.entries(rs[a]) if e.name == "join").children[0].payload
    win.items.menu_pick(rs[a], "join", payload)
    assert calls(writer) == [("join", [], {"piece_ids": [rs[a].piece_id, rs[b].piece_id], "ahead": False})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_JOINED.format(range="Ep 1–8"), 5)
    assert lst_of(win).model().open_key == rs[a].key                # the result opened
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert [c.op for c in writer.undone] == ["join"]


def test_joining_the_earlier_part_onto_the_later_is_one_join_ahead_and_one_undo(world):
    # E22: the target keeps its place; episode order kept: Ep 1–4 just before Ep 5 — the store's one command (S5)
    _seed, win, writer = world()
    a, b = split_parts(win)
    rs = rows_of(win)
    payload = next(e for e in win.items.entries(rs[b]) if e.name == "join").children[0].payload
    win.items.menu_pick(rs[b], "join", payload)
    assert calls(writer) == [("join", [], {"piece_ids": [rs[b].piece_id, rs[a].piece_id], "ahead": True})]
    assert lst_of(win).model().open_key == rs[b].key
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_JOINED.format(range="Ep 1–8"), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert [c.op for c in writer.undone] == ["join"]


def test_S5_a_command_that_landed_as_nothing_settles_its_ticket_so_ctrl_z_takes_the_one_still_waiting(world):
    # a busy store: a no-op lands while the join still waits; Ctrl+Z must reach the join, not the no-op
    _seed, win, writer = world()
    a, b = split_parts(win)
    rs = rows_of(win)
    empty = []

    def landed_empty():
        out = list(empty)
        empty.clear()
        return out
    writer.landed_empty = landed_empty
    writer.stuck = True
    step = drag.Ticket("step", (rs[a].key,), drag.ids_of(rs[a]))
    join = drag.Ticket("join", (rs[a].key,), drag.ids_of(rs[a]) + drag.ids_of(rs[b]))
    win.moves._give(step, lambda t: writer.move(drag.ids_of(rs[a]), "now", label=t), toast=False)
    win.moves._give(join, lambda t: writer.join([rs[a].piece_id, rs[b].piece_id], label=t), toast=False)
    writer._waiting.pop(0)                                           # the move lands as nothing; the join waits
    empty.append(step)
    win.moves._reread()
    assert step not in win.moves.tickets and join in win.moves.tickets
    win.moves.undo_last()
    assert join.undo_asked and not step.undo_asked
    writer.stuck = False
    writer.free()


def test_a_part_dragged_over_the_other_part_holds_the_rows_still_and_outlines_it(world):
    _seed, win, writer = world()
    a, b = split_parts(win)
    lst = lst_of(win)
    rs = rows_of(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    settle()
    d = win.moves.running
    assert d.target == ("join", rs[a].key)
    parting = d.parting
    assert parting.slot == parting.src and all(parting.target(r) == 0 for r in range(len(rs)))   # no gap opens
    assert lst.join_key == rs[a].key
    slot = lst.delegate.slot_rect(rows.ROW, lst.visualRect(lst.model().index(a, 0)), ())
    shown = lit(lst, slot, rows.c("ok").name())
    lst.set_join(None)
    settle()
    assert shown > lit(lst, slot, rows.c("ok").name()) + 30          # the green dashed outline and its words
    win.moves._follow(to)                                            # (the hand still there: back again)
    assert lst.join_key == rs[a].key
    move_global(win, middle_point(win, 4))                           # off it: the outline goes, a gap opens again
    settle()
    assert lst.join_key is None and win.moves.running.target[0] == "list"
    win.moves.cancel()
    assert writer.calls == []


def test_the_drop_on_the_other_part_joins_them_opens_the_result_and_toasts_with_undo(world):
    _seed, win, writer = world()
    a, b = split_parts(win)
    rs = rows_of(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    release_global(win, to)
    assert calls(writer) == [("join", [], {"piece_ids": [rs[a].piece_id, rs[b].piece_id], "ahead": False})]
    assert lst_of(win).join_key is None and win.moves.running is None
    assert lst_of(win).model().open_key == rs[a].key
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_JOINED.format(range="Ep 1–8"), 5)


def test_a_drag_over_another_title_is_a_move_never_a_join(world):
    _seed, win, writer = world()
    a, _b = split_parts(win)
    lift(win, a)
    move_global(win, middle_point(win, 4))
    assert win.moves.running.target[0] == "list"
    win.moves.cancel()


def test_a_parts_top_and_bottom_edges_place_it_beside_the_other_part_never_join(world):
    # its edges stay a move: a part can still be put right next to its other part
    _seed, win, writer = world()
    a, b = split_parts(win)
    lift(win, b)
    move_global(win, row_point(win, a))                              # its upper quarter
    assert win.moves.running.target[0] == "list" and lst_of(win).join_key is None
    move_global(win, row_point(win, a, lower=True))
    assert win.moves.running.target[0] == "list"
    win.moves.cancel()
    assert writer.calls == []


# --- Remove… ---------------------------------------------------------------------------------------------------------- #
def _card_open(items):
    q = items.question
    return q is not None and q.isVisible()


def test_remove_asks_first_naming_its_files_and_esc_cancels_with_nothing_written(world):
    _seed, win, writer = world()
    row = rows_of(win)[4]
    win.items.menu_pick(row, "remove")
    assert wait_until(lambda: _card_open(win.items), 5)
    q = win.items.question
    assert q.title.text() == strings.ITEM_REMOVE_ASK.format(title=row.title)
    assert q.yes.text() == strings.ITEM_REMOVE_YES.format(n=len(row.episodes))
    assert q.default is q.no                                         # Cancel is the default: Enter never removes
    QTest.keyClick(QApplication.focusWidget() or q, Qt.Key.Key_Escape)
    assert wait_until(lambda: win.items.question is None, 5)
    settle()
    assert writer.calls == []


def test_remove_yes_sends_its_files_to_the_trash_with_a_toast_and_undo(world):
    _seed, win, writer = world()
    row = rows_of(win)[4]
    win.items.menu_pick(row, "remove")
    assert wait_until(lambda: _card_open(win.items), 5)
    win.items.question.yes.click()
    assert calls(writer, "remove") == [("remove", drag.ids_of(row), {})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_REMOVED.format(title=row.title), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert [c.op for c in writer.undone] == ["remove"]


# --- E4: read-only ------------------------------------------------------------------------------------------------- #
def test_E4_a_read_only_store_greys_every_write_with_its_reason_and_picks_write_nothing(world):
    _seed, win, writer = world(writable=False)
    a, _b = split_parts(win)
    row = rows_of(win)[a]
    entries = win.items.entries(row)
    flat = {e.name: e for e in entries}
    for name in ("pin", "remove"):
        assert not flat[name].ok and flat[name].tip.startswith(strings.MENU_REFUSED_TIP.format(reason="")[:20])
    assert flat["folder"].ok                                         # nothing to save: stays
    for name in ("type", "split", "join"):                           # the submenus greyed with the reason too
        assert not flat[name].ok and flat[name].tip == flat["pin"].tip
        assert not any(c.ok for c in flat[name].children)
    for name, payload in (("pin", None), ("type-to", "drama"), ("split", row.episodes[1]), ("remove", None),
                          ("join", flat["join"].children[0].payload)):
        win.items.menu_pick(row, name, payload)
    win.items.split(row, row.episodes[1])
    settle()
    assert writer.calls == [] and win.items.question is None


def test_E4_a_drag_never_starts_so_nothing_can_be_joined(world):
    _seed, win, writer = world(writable=False)
    assert win.items.target(type("D", (), {"row": None, "external": True, "key": None})(), QPoint(0, 0)) is None
    assert writer.calls == []


# --- Change cover… (Q6's hook) and Open its folder ----------------------------------------------------------------- #
def test_change_cover_shows_once_covers_offer_their_entries(world):
    _seed, win, _w = world()
    row = rows_of(win)[4]
    # --- W3.2 L3: Q6's entries through the hook (Download covers off: no online ones), in the hook's shape
    cover = next(e for e in win.items.entries(row) if e.name == "cover")
    assert [c.label for c in cover.children] == [strings.COVER_MENU["choose"][0], strings.COVER_MENU["generated"][0]]
    assert all(c.tip and callable(c.payload) for c in cover.children)
    picked = []
    win.items.cover_entries = lambda r: [("Choose an image…", "Pick a picture of your own", True,
                                          lambda: picked.append(r.key))]
    cover = next(e for e in win.items.entries(row) if e.name == "cover")
    assert [c.label for c in cover.children] == ["Choose an image…"]
    win.items.menu_pick(row, "cover-to", cover.children[0].payload)
    assert picked == [row.key]


def test_open_its_folder_opens_it_or_says_its_gone(world, monkeypatch):
    seed, win, _w = world()
    opened, said = [], []
    monkeypatch.setattr(item_menu.windows, "open_url", lambda url: opened.append(url))
    monkeypatch.setattr(win.moves, "say", lambda text: said.append(text))
    row = rows_of(win)[4]
    win.items.menu_pick(row, "folder")
    assert wait_until(lambda: opened or said, 5)
    folder = item_menu.finished.folder_of(seed.language, row)
    assert (opened == [folder]) if os.path.isdir(folder) else said == [strings.FIN_NO_FOLDER.format(title=row.title)]


# --- Alt+↑ / Alt+↓ ------------------------------------------------------------------------------------------------- #
def test_alt_up_and_down_nudge_the_focused_row(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    lst.setCurrentIndex(lst.model().index(4, 0))
    row = rows_of(win)[4]
    QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier))
    assert calls(writer, "nudge")[-1] == ("nudge", drag.ids_of(row), {"direction": "up"})
    win.moves._let_go()
    win.show_library(win.services.library.view())
    lst.setCurrentIndex(lst.model().index(4, 0))
    row = rows_of(win)[4]
    QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier))
    assert calls(writer, "nudge")[-1] == ("nudge", drag.ids_of(row), {"direction": "down"})


# ================================================================================================================== #
# The real store: the writer and the reader on one opener
# ================================================================================================================== #
def _row_of(win, ids):
    view = win.page_widgets["current"].view_model
    return next((r for r in view.rows if [e.id for e in r.episodes] == list(ids)), None)


def _split_outside(store, win, n_first=2):
    """The first four-file show split after its `n_first`th file from outside (another program); -> (ids, piece)."""
    row = next(r for r in win.page_widgets["current"].view_model.rows if len(r.episodes) == 4 and r.piece_id)
    ids = drag.ids_of(row)
    piece = store.item(ids[0])["piece_id"]
    store.split(piece, ids[n_first])
    assert wait_until(lambda: _row_of(win, ids[:n_first]) is not None, 10)
    return ids, piece


def test_real_store_the_seam_splits_the_part_and_its_undo_joins_it_back(real):
    store, win, _writer = real()
    lst = lst_of(win)
    rs = rows_of(win)
    i, row = next((n, r) for n, r in enumerate(rs) if len(r.episodes) == 4 and r.piece_id)
    ids = drag.ids_of(row)
    open_row(win, i)
    seam = seams(lst, i)[1]
    press(lst, seam[1].center())
    release(lst, seam[1].center())
    assert wait_until(lambda: store.item(ids[2])["piece_id"] != row.piece_id, 5)
    assert store.item(ids[3])["piece_id"] == store.item(ids[2])["piece_id"]
    assert [store.item(x)["piece_id"] for x in ids[:2]] == [row.piece_id] * 2
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: {store.item(x)["piece_id"] for x in ids} == {row.piece_id}, 5)


def test_real_store_E22_join_with_a_part_in_finished_brings_it_to_current_in_episode_order_one_undo(real):
    # IK-L2-1: finished with its cards taken out, it comes back with them in the order; Undo takes them out again
    store, win, _writer = real()
    ids, piece = _split_outside(store, win)
    store.finish(list(ids[2:]), keep_cards=False)                    # Ep 3–4 in Finished, Ep 1–2 in Current
    assert wait_until(lambda: _row_of(win, ids[2:]) is None and _row_of(win, ids[:2]) is not None, 10)
    row = _row_of(win, ids[:2])
    join = next(e for e in win.items.entries(row) if e.name == "join")
    child = next(c for c in join.children if c.payload.ids == tuple(ids[2:]))
    assert child.label.endswith(strings.ITEM_JOIN_WHERE["graduated"])
    win.items.menu_pick(row, "join", child.payload)
    assert wait_until(lambda: all(store.item(x)["tier"] == "now" for x in ids), 5)
    now = store.ids("now")
    assert now[now.index(ids[0]):now.index(ids[0]) + 4] == list(ids)          # where the target is, in order
    assert {store.item(x)["piece_id"] for x in ids} == {piece}
    assert [store.item(x)["in_learning_order"] for x in ids[2:]] == [1, 1]
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: all(store.item(x)["tier"] == "graduated" for x in ids[2:]), 5)
    assert store.item(ids[2])["piece_id"] != piece
    assert [store.item(x)["in_learning_order"] for x in ids[2:]] == [0, 0]


def test_real_store_joining_the_earlier_part_from_finished_onto_the_later_keeps_episode_order_one_undo(real):
    store, win, _writer = real()
    ids, piece = _split_outside(store, win)
    store.finish(list(ids[:2]), keep_cards=False)                    # Ep 1–2 in Finished, Ep 3–4 in Current
    assert wait_until(lambda: _row_of(win, ids[:2]) is None and _row_of(win, ids[2:]) is not None, 10)
    row = _row_of(win, ids[2:])
    later = row.piece_id
    child = next(c for c in next(e for e in win.items.entries(row) if e.name == "join").children
                 if c.payload.ids == tuple(ids[:2]))
    win.items.menu_pick(row, "join", child.payload)
    assert wait_until(lambda: len({store.item(x)["piece_id"] for x in ids}) == 1 and
                      all(store.item(x)["tier"] == "now" for x in ids), 5)
    now = store.ids("now")
    assert now[now.index(ids[0]):now.index(ids[0]) + 4] == list(ids)          # Ep 1–4, before where Ep 3 stood
    assert [store.item(x)["in_learning_order"] for x in ids[:2]] == [1, 1]
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()                               # one Undo: the one join
    assert wait_until(lambda: all(store.item(x)["tier"] == "graduated" for x in ids[:2]), 5)
    assert all(store.item(x)["piece_id"] == later for x in ids[2:]) and store.item(ids[0])["piece_id"] != later
    assert [store.item(x)["in_learning_order"] for x in ids[:2]] == [0, 0]


def test_real_store_S5_an_adjacent_earlier_part_dropped_to_join_is_undone_by_one_ctrl_z(real):
    # Ep 1–2 right above Ep 3–4: no move to make, the join alone; the first Ctrl+Z takes it back
    store, win, _writer = real()
    ids, piece = _split_outside(store, win)
    row = _row_of(win, ids[2:])
    later = row.piece_id
    first = _row_of(win, ids[:2])
    win.items.join(item_menu.part_of(row), item_menu.part_of(first))
    assert wait_until(lambda: {store.item(x)["piece_id"] for x in ids} == {later}, 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.moves.undo_last()
    assert wait_until(lambda: store.item(ids[0])["piece_id"] != later, 5)
    assert all(store.item(x)["piece_id"] == later for x in ids[2:])


def test_real_store_what_is_it_and_study_first_land_in_the_store(real):
    store, win, _writer = real()
    row = next(r for r in rows_of(win) if r.work_id is not None)
    ids = drag.ids_of(row)
    win.items.menu_pick(row, "type-to", "drama")
    assert wait_until(lambda: store.media_type(row.work_id) == ("drama", "user"), 5)
    win.items.menu_pick(row, "pin")
    assert wait_until(lambda: all(store.item(x)["pinned"] is not None for x in ids), 5)
    assert wait_until(lambda: next(r for r in rows_of(win) if r.key == row.key).studying, 5)
    assert "unpin" in names(win.items.entries(next(r for r in rows_of(win) if r.key == row.key)))


def test_real_store_remove_sends_the_files_to_the_trash_and_undo_brings_them_back(real):
    store, win, _writer = real()
    row = rows_of(win)[1]
    ids = drag.ids_of(row)
    rels = [store.item(x)["rel_path"] for x in ids]
    win.items.menu_pick(row, "remove")
    assert wait_until(lambda: _card_open(win.items), 5)
    win.items.question.yes.click()
    assert wait_until(lambda: all(store.item(x) is None for x in ids), 5)
    data = path_utils.get_data_path("ja")
    assert not any(os.path.exists(os.path.join(data, *r.split("/"))) for r in rels)      # in the trash
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: sorted(store.item(x)["rel_path"] for x in store.ids("now")
                                     if store.item(x)["rel_path"] in rels) == sorted(rels), 5)
