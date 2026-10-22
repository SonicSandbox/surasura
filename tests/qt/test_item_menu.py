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
from PyQt6.QtGui import QAction, QColor, QContextMenuEvent, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import path_utils
from app.qt import drag, item_menu, rows, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import (FakeWriter, lift, mouse, move, move_global, open_window, part_rect, press,  # noqa: F401
                                real, release, release_global, row_point, settle, title_point)
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

    def group(self, piece_ids=(), item_ids=(), label=None):
        return self._put("group", [], label, piece_ids=list(piece_ids), item_ids=list(item_ids))


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


# ================================================================================================================== #
# LM11b G4: select, then right-click *Group…* (RUNBOOK §1 G4, §2)
# ================================================================================================================== #
# What a wrong answer would cost a learner: a Ctrl+click that marks an episode watched (a stone is a Done on a plain
# click); a selection he can't see, or one that lingers after he moved on and groups the wrong shows; *Group…* writing
# two commands (two Undos) or the shows in the order he clicked them instead of the list's; a write on a library that
# can't be saved; a right-click that does nothing.
CTRL = Qt.KeyboardModifier.ControlModifier


def ctrl_click(lst, pos):
    mouse(lst.viewport(), QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
          CTRL)
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
          CTRL)
    settle(20)


def groupable(win, n=2):
    """`n` places of Current rows (never Up Next) that are shows' own parts, each of another show."""
    out, works = [], set()
    for i, r in enumerate(rows_of(win)):
        if i and r.piece_id is not None and r.source != "hato" and len(r.episodes) >= 3 and r.work_id not in works:
            out.append(i)
            works.add(r.work_id)
    assert len(out) >= n
    return out[:n]


def stone_of(lst, i, k):
    """Row `i`'s (opened) `k`-th episode's stone: (its rect, the episode) — read once the row is the current one (a
    press makes it current, and an opened row taller than the list scrolls into view then)."""
    if lst.currentIndex().row() != i:
        lst.setCurrentIndex(lst.model().index(i, 0))
        settle()
    entry = lst.model().entries[i]
    ep = entry[1].episodes[k]
    part = next(p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0)))
                if p[0] == "stone" and p[3] is ep)
    return part[1], ep


def slab_rect(lst, i):
    return lst.delegate.slab_of(lst.visualRect(lst.model().index(i, 0)))


def test_G4_ctrl_click_picks_and_unpicks_a_row_and_an_episode_and_never_marks_it_watched(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b = groupable(win)
    key = rows_of(win)[a].key
    ctrl_click(lst, title_point(lst, a))
    assert lst.picked_rows == {key} and lst.model().open_key != key       # picked, never opened
    ctrl_click(lst, title_point(lst, a))
    assert lst.picked_rows == set()                                       # a second Ctrl+click lets it go
    open_row(win, b)
    r, ep = stone_of(lst, b, 1)
    ctrl_click(lst, r.center())
    assert lst.picked_eps == {(rows_of(win)[b].key, ep.id)}
    ctrl_click(lst, r.center())
    assert lst.picked_eps == set()
    settle()
    assert writer.calls == [] and not ep.watched                          # nothing marked watched, nothing written


def test_G4_ctrl_space_picks_the_keyboards_row(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    a, _b = groupable(win)
    lst.setCurrentIndex(lst.model().index(a, 0))
    QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, CTRL))
    assert lst.picked_rows == {rows_of(win)[a].key} and lst.model().open_key != rows_of(win)[a].key
    QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, CTRL))
    assert lst.picked_rows == set()


def test_G4_a_picked_row_and_a_picked_episode_are_painted(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    a, b = groupable(win)
    accent = rows.c("accent")
    slab = slab_rect(lst, a)
    before = lit(lst, slab, accent, tolerance=12)
    ctrl_click(lst, title_point(lst, a))
    settle()
    assert lit(lst, slab, accent, tolerance=12) >= before + slab.width()  # its slab outlined in the accent
    open_row(win, b)
    r, _ep = stone_of(lst, b, 2)
    line = r.adjusted(0, -4, lst.viewport().width(), 4)
    before = lit(lst, line, accent, tolerance=12)
    ctrl_click(lst, r.center())
    settle()
    assert lit(lst, line, accent, tolerance=12) >= before + r.width()     # the episode's line too


def test_G4_esc_a_plain_click_and_a_drag_each_clear_the_picks(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b = groupable(win)
    ctrl_click(lst, title_point(lst, a))
    ctrl_click(lst, title_point(lst, b))
    assert len(lst.picked_rows) == 2
    QTest.keyClick(lst, Qt.Key.Key_Escape)                                # the router's Esc
    assert lst.picked_rows == set()
    ctrl_click(lst, title_point(lst, a))
    at = title_point(lst, b)
    press(lst, at)
    release(lst, at)                                                      # a plain click: it opens b, the picks go
    assert lst.picked_rows == set()
    settle()
    ctrl_click(lst, title_point(lst, a))
    assert lst.picked_rows
    lift(win, a)                                                          # a drag starting
    assert lst.picked_rows == set()
    win.moves.cancel()
    assert calls(writer, "group") == []


def test_G4_a_new_view_without_a_picked_row_or_episode_lets_it_go(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    a, _b = groupable(win)
    key = rows_of(win)[a].key
    lst.picked_rows |= {key, "gone"}
    lst.picked_eps |= {(key, -1), ("gone", 7)}
    lst.set_entries(list(lst.model().entries))
    assert lst.picked_rows == {key} and lst.picked_eps == set()


def test_G4_a_right_click_on_a_row_opens_its_menu_at_the_hand(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    a, _b = groupable(win)
    asked = []
    lst.menu_requested.connect(lambda row, at: asked.append((row.key, at)))
    pos = title_point(lst, a)
    gpos = lst.viewport().mapToGlobal(pos)
    QApplication.sendEvent(lst.viewport(), QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, gpos))
    settle()
    assert asked == [(rows_of(win)[a].key, gpos)]
    m = win.items.last_menu
    assert m is not None and m.isVisible()
    assert strings.ITEM_MENU["remove"][0] in [x.text() for x in m.actions()]
    m.close()


def test_G4_group_is_offered_first_only_with_two_rows_and_is_tipped_and_wired(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    a, b = groupable(win)
    row = rows_of(win)[a]
    at = win.mapToGlobal(QPoint(300, 300))
    assert win.items.group_entry() is None                                # nothing picked
    ctrl_click(lst, title_point(lst, a))
    assert win.items.group_entry() is None                                # one row: nothing to group
    lst.clear_picks()
    open_row(win, b)
    for k in (0, 1):
        ctrl_click(lst, stone_of(lst, b, k)[0].center())
    assert win.items.group_entry() is None                                # two episodes of one show: no group either
    ctrl_click(lst, title_point(lst, a))                                  # ... with another show's row: three
    e = win.items.group_entry()
    assert e is not None and e.ok and e.label == strings.ITEM_MENU["group"][0]
    assert e.tip == strings.ITEM_MENU["group"][1].format(n=3)
    m = win.items.menu(row, at)
    first = m.actions()[0]
    assert first.text() == strings.ITEM_MENU["group"][0] and first.toolTip() == e.tip and _connected(first)
    m.close()


def test_G4_group_is_one_command_the_rows_pieces_in_list_order_then_the_episodes_with_a_toast_and_undo(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b, c3 = groupable(win, 3)
    rs = rows_of(win)
    ctrl_click(lst, title_point(lst, c3))                                 # picked last-first: the list's order wins
    ctrl_click(lst, title_point(lst, a))
    open_row(win, b)
    r, ep = stone_of(lst, b, 1)
    ctrl_click(lst, r.center())
    win.items.menu_pick(rs[a], "group")
    assert calls(writer) == [("group", [], {"piece_ids": [rs[a].piece_id, rs[c3].piece_id], "item_ids": [ep.id]})]
    assert lst.picked_rows == set() and lst.picked_eps == set()           # the picks go with it
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_GROUPED.format(n=3), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()                                    # Undo: the one command
    assert writer.undone and writer.undone[-1].op == "group"


def test_G4_a_read_only_store_greys_group_with_its_reason_and_a_pick_writes_nothing(world):
    _seed, win, writer = world(writable=False)
    lst = lst_of(win)
    a, b = groupable(win)
    ctrl_click(lst, title_point(lst, a))
    ctrl_click(lst, title_point(lst, b))
    e = win.items.group_entry()
    assert e is not None and not e.ok
    assert e.tip.startswith(strings.MENU_REFUSED_TIP.format(reason="")[:20])
    win.items.menu_pick(rows_of(win)[a], "group")
    settle()
    assert writer.calls == []


def test_G4_IK4_picks_all_from_one_show_offer_no_group(world):
    # one show's two parts (or its episodes) picked: the store would make no group of them (a quiet split, a wrong
    # toast), so *Group…* isn't offered
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b = split_parts(win)
    ctrl_click(lst, title_point(lst, a))
    ctrl_click(lst, title_point(lst, b))
    assert len(lst.picked_rows) == 2 and win.items.group_entry() is None
    m = win.items.menu(rows_of(win)[a], win.mapToGlobal(QPoint(300, 300)))
    assert strings.ITEM_MENU["group"][0] not in [x.text() for x in m.actions()]
    m.close()
    win.items.menu_pick(rows_of(win)[a], "group")
    assert calls(writer, "group") == []


def test_G4_IK1_a_picked_row_the_soon_line_runs_through_groups_both_its_pieces(world, monkeypatch):
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b = groupable(win)
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    rs[a] = rs[a]._replace(soon_from=1, soon_piece=987654)            # Ep 1 NOW's piece, Ep 2… Soon's
    monkeypatch.setattr(win.items, "_view", lambda: view._replace(rows=rs))
    assert item_menu.pieces_of(rs[a]) == [rs[a].piece_id, 987654]
    assert item_menu.pieces_of(rs[a]._replace(soon_piece=rs[a].piece_id)) == [rs[a].piece_id]
    lst.picked_rows |= {rs[a].key, rs[b].key}
    win.items.menu_pick(rs[a], "group")
    assert calls(writer, "group") == [("group", [], {"piece_ids": [rs[a].piece_id, 987654, rs[b].piece_id],
                                                     "item_ids": []})]


def test_G4_IK9_ctrl_click_never_plays_opens_the_menu_or_marks_a_stone_watched(world):
    from app.qt import stones, style
    key = stones._key(1.0, style.current()[1])
    if key not in stones._SHEETS:                                       # the stones drawn (a closed row's are then hit)
        stones._landed(key, stones.build(*key))
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b = groupable(win)
    asked = []
    for sig in (lst.play_requested, lst.menu_requested, lst.done_requested, lst.nudge_requested):
        sig.connect(lambda *x, s=sig: asked.append(s))
    lst.setCurrentIndex(lst.model().index(a, 0))
    settle()
    for name in ("play", "more", "up"):                                 # buttons: nothing, not even a pick
        ctrl_click(lst, part_rect(lst, a, name)[1].center())
    hero = rows.HERO
    assert lst.model().entries[0][0] == hero
    for name in ("play", "done"):
        ctrl_click(lst, part_rect(lst, 0, name)[1].center())
    assert asked == [] and lst.picked_rows == set()
    stone = next(p for p in lst.delegate.parts(lst.model().entries[b], lst.visualRect(lst.model().index(b, 0)))
                 if p[0] == "stone")                                    # a closed row's stone: picks the row
    ctrl_click(lst, stone[1].center())
    assert lst.picked_rows == {rows_of(win)[b].key}
    open_row(win, a)
    r, ep = stone_of(lst, a, 0)                                         # an opened row's: picks the episode
    ctrl_click(lst, r.center())
    assert (rows_of(win)[a].key, ep.id) in lst.picked_eps
    settle()
    assert asked == [] and writer.calls == []


def test_G4_IK10_shift_click_picks_the_rows_from_the_last_picked_to_this_one(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    a, _b = groupable(win)
    to = a + 3
    ctrl_click(lst, title_point(lst, a))
    mouse(lst.viewport(), QEvent.Type.MouseButtonPress, title_point(lst, to), Qt.MouseButton.LeftButton,
          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, title_point(lst, to), Qt.MouseButton.LeftButton,
          Qt.MouseButton.NoButton, Qt.KeyboardModifier.ShiftModifier)
    settle(20)
    want = {r.key for r in rows_of(win)[a:to + 1] if lst.pickable(r)}
    assert len(want) >= 3 and lst.picked_rows == want
    assert lst.model().open_key not in want and writer.calls == []      # nothing opened, nothing written


def click_with(lst, pos, modifiers):
    mouse(lst.viewport(), QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
          modifiers)
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
          modifiers)
    settle(20)


def test_G4_shift_click_replaces_the_picks_with_the_range_and_ctrl_shift_adds_it(world):
    # as Explorer: Shift+click — the rows from the one Ctrl picked last to this one, and nothing else; Ctrl+Shift+click
    # adds that range to what is picked; the anchor stays on the Ctrl-picked row
    _seed, win, writer = world()
    lst = lst_of(win)
    rs = rows_of(win)
    seen = lst.viewport().rect()
    p = [i for i in range(1, len(rs)) if lst.pickable(rs[i]) and
         seen.contains(lst.visualRect(lst.model().index(i, 0)))][:4]     # four rows on screen that can be picked
    assert len(p) == 4

    def span(i, j):
        return {r.key for r in rs[i:j + 1] if lst.pickable(r)}
    ctrl_click(lst, title_point(lst, p[0]))
    ctrl_click(lst, title_point(lst, p[3]))                               # the anchor: the row Ctrl picked last
    click_with(lst, title_point(lst, p[2]), Qt.KeyboardModifier.ShiftModifier)
    assert lst.picked_rows == span(p[2], p[3]) and rs[p[0]].key not in lst.picked_rows   # replaced: p0 let go
    ctrl_click(lst, title_point(lst, p[0]))                               # p0 again: now the anchor
    click_with(lst, title_point(lst, p[1]), Qt.KeyboardModifier.ShiftModifier | CTRL)
    assert lst.picked_rows == span(p[0], p[1]) | span(p[2], p[3])        # added: the rest kept
    click_with(lst, title_point(lst, p[2]), Qt.KeyboardModifier.ShiftModifier)
    assert lst.picked_rows == span(p[0], p[2])                            # Shift alone: the range from p0, alone
    assert writer.calls == [] and lst.model().open_key not in lst.picked_rows


def test_G4_a_rows_menu_offers_group_only_when_that_row_is_picked(world):
    # ⋯ or a right-click on a row that isn't picked is that row's own menu: no *Group…*, and the picks stay
    _seed, win, writer = world()
    lst = lst_of(win)
    a, b, other = groupable(win, 3)
    rs = rows_of(win)
    ctrl_click(lst, title_point(lst, a))
    ctrl_click(lst, title_point(lst, b))
    picks = set(lst.picked_rows)
    at = win.mapToGlobal(QPoint(300, 300))
    assert win.items.group_entry(rs[other]) is None and win.items.group_entry(rs[b]) is not None
    m = win.items.menu(rs[other], at)
    assert strings.ITEM_MENU["group"][0] not in [x.text() for x in m.actions()]
    m.close()
    win.items.menu_pick(rs[other], "group")
    assert calls(writer, "group") == [] and lst.picked_rows == picks
    m = win.items.menu(rs[b], at)
    assert m.actions()[0].text() == strings.ITEM_MENU["group"][0]
    m.close()


def test_G4_IK11_a_pick_repaints_only_the_rows_whose_state_changed(world, monkeypatch):
    _seed, win, _w = world()
    lst = lst_of(win)
    a, b = groupable(win)
    asked = []
    monkeypatch.setattr(lst, "update", lambda index: asked.append(index.row()))
    rs = rows_of(win)
    lst.pick_row(rs[a])
    assert asked == [a]
    lst.pick_row(rs[b])
    assert asked == [a, b]
    del asked[:]
    lst.pick_row(rs[a])                                                 # let go: that row alone
    assert asked == [a]
    del asked[:]
    lst.clear_picks()
    assert asked == [b]
    lst.clear_picks()                                                   # nothing picked: nothing repainted
    assert asked == [b]


def test_G4_finisheds_list_picks_nothing(world):
    # Current's list only: Finished's rows never join a selection (a group never lives in Finished)
    _seed, win, _w = world()
    assert win.page_widgets["finished"].list.pickable is None
    assert lst_of(win).pickable is not None


def test_real_store_G4_two_shows_ctrl_clicked_and_grouped_are_one_row_and_undo_makes_them_two(real):
    store, win, _writer = real()
    lst = lst_of(win)
    a, b = groupable(win)
    rs = rows_of(win)
    ids = drag.ids_of(rs[a]) + drag.ids_of(rs[b])
    ctrl_click(lst, title_point(lst, a))
    ctrl_click(lst, title_point(lst, b))
    win.items.menu_pick(rs[a], "group")
    assert wait_until(lambda: len({store.item(x)["piece_id"] for x in ids}) == 1, 5)
    assert wait_until(lambda: sum(1 for r in rows_of(win) if set(drag.ids_of(r)) & set(ids)) == 1, 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: len({store.item(x)["piece_id"] for x in ids}) == 2, 5)
    assert wait_until(lambda: sum(1 for r in rows_of(win) if set(drag.ids_of(r)) & set(ids)) == 2, 5)
