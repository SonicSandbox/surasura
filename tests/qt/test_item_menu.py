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
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QAction, QColor, QContextMenuEvent, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import path_utils
from app.qt import drag, item_menu, rows, strings, style
from app.services import view_rows
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

    def join(self, piece_ids, label=None, ahead=False, how="parts"):
        return self._put("join", [], label, piece_ids=list(piece_ids), ahead=ahead,
                         **({"how": how} if how != "parts" else {}))

    def add_to_group(self, piece_id, piece_ids=(), item_ids=(), label=None):
        return self._put("add_to_group", [], label, piece_id=piece_id, piece_ids=list(piece_ids),
                         item_ids=list(item_ids))

    def ungroup(self, piece_id, label=None):
        return self._put("ungroup", [], label, piece_id=piece_id)

    def rename_piece(self, piece_id, title, label=None):
        return self._put("rename_piece", [], label, piece_id=piece_id, title=title)

    def set_media_type(self, work_ids, media_type, label=None):
        return self._put("set_media_type", [], label, work_ids=list(work_ids), media_type=media_type)

    def remove(self, ids, label=None):
        return self._put("remove", ids, label)

    def group(self, piece_ids=(), item_ids=(), label=None):
        return self._put("group", [], label, piece_ids=list(piece_ids), item_ids=list(item_ids))

    def merge_works(self, keep_id, other_ids, label=None):
        return self._put("merge_works", [], label, keep_id=keep_id, other_ids=list(other_ids))


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
    assert names(win.items.entries(row)) == ["pin", "type", "split", "join", "same-show", "cover", "folder",
                                                 "remove"]                       # W3.2 L3; LM11b G3: same-show
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


# --- LM11b G2: a show dropped on another show (Sonic's answers: a rest on its middle makes a group, no question) ---- #
def two_shows(win):
    """Two Current rows of different shows, neither Up next, neither a show in two parts: (dragged place, dropped-on
    place) — the dropped-on one above, with 2+ episodes (an opened group of it has an episode before its last)."""
    rs = rows_of(win)
    split = {r.work_id for r in rs if sum(1 for o in rs if o.work_id == r.work_id) > 1}
    ok = [i for i, r in enumerate(rs) if i > 0 and item_menu.joinable(r) and r.work_id not in split]
    a = next(i for i in ok if len(rs[i].episodes) >= 2)
    b = next(i for i in ok if i > a + 1 and rs[i].work_id != rs[a].work_id)
    return b, a


def rest():
    QTest.qWait(item_menu.JOIN_REST_MS + 150)


def theme_swallow():
    from app import theme
    return theme.MOTION["click-swallow-after-drag"] + 30


def as_group(win, i, other_work=987654):
    """Row `i` shown as a group of its show and another (G1's `group` / `works`), the rest of the view as it was."""
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    rs[i] = rs[i]._replace(group=True, works=(rs[i].work_id, other_work))
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()
    assert rows_of(win)[i].group
    return rows_of(win)[i]


def test_G2_another_show_is_outlined_drop_to_group_only_after_the_hand_rests_and_it_clears_on_leave_and_esc(world):
    # a passing hand reorders as before (a gap under it); resting over the middle outlines the other show with *Drop to
    # group* (the rows hold still); off it, or Esc, the outline goes — and a new drag starts its rest again
    _seed, win, writer = world()
    b, a = two_shows(win)
    lst = lst_of(win)
    rs = rows_of(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    settle()
    assert win.moves.running.target[0] == "list" and lst.join_key is None, "no rest yet: a move, a gap opens"
    rest()
    d = win.moves.running
    assert d.target == ("join", rs[a].key) and lst.join_key == rs[a].key
    assert lst.join_label == strings.JOIN_GROUP_LABEL
    assert d.parting.slot == d.parting.src                           # the rows hold still under the outline
    move_global(win, middle_point(win, 4 if 4 not in (a, b) else 5))   # off it
    settle()
    assert lst.join_key is None and win.moves.running.target[0] == "list"
    move_global(win, to)                                             # back on it: its rest starts again
    settle()
    assert lst.join_key is None
    rest()
    assert lst.join_key == rs[a].key
    QTest.keyClick(win, Qt.Key.Key_Escape)
    settle()
    assert win.moves.running is None and lst.join_key is None
    QTest.qWait(theme_swallow())
    lift(win, b)                                                     # a new drag: never groups at once
    move_global(win, to)
    settle()
    assert lst.join_key is None and win.moves.running.target[0] == "list"
    win.moves.cancel()
    assert writer.calls == []


def test_G2_the_same_shows_other_part_still_joins_at_once_with_drop_to_join(world):
    _seed, win, writer = world()
    a, b = split_parts(win)
    lst = lst_of(win)
    lift(win, b)
    move_global(win, middle_point(win, a))
    settle()
    assert win.moves.running.target == ("join", rows_of(win)[a].key) and lst.join_label == strings.JOIN_LABEL
    win.moves.cancel()
    assert writer.calls == []


def test_G2_a_passing_drop_on_another_show_reorders_and_never_groups(world):
    _seed, win, writer = world()
    b, a = two_shows(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    release_global(win, to)                                          # let go at once: no rest
    rest()                                                           # (the rest's timer, if any, finds no drag)
    assert [c[0] for c in writer.calls] == ["move"]
    assert win.moves.running is None and lst_of(win).join_key is None


def test_G2_a_rested_drop_on_another_show_is_one_group_join_target_first_opened_and_toasted_with_undo(world):
    _seed, win, writer = world()
    b, a = two_shows(win)
    rs = rows_of(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    rest()
    release_global(win, to)
    assert calls(writer) == [("join", [], {"piece_ids": [rs[a].piece_id, rs[b].piece_id], "ahead": False,
                                           "how": "group"})]
    assert lst_of(win).model().open_key == rs[a].key
    text = strings.ITEM_GROUPED_WITH.format(other=rs[b].title, title=rs[a].title)
    assert wait_until(lambda: win.toasts.card.message == text, 5)
    assert win.toasts.card.buttons, "its Undo"


def test_G2_a_part_dropped_on_a_group_led_by_its_own_show_waits_for_the_rest_and_makes_a_group_join(world):
    # either side a group: never a join of one show's parts at once, though the group's first show is the dragged one's
    _seed, win, writer = world()
    a, b = split_parts(win)
    group = as_group(win, a)
    lst = lst_of(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    settle()
    assert win.moves.running.target[0] == "list" and lst.join_key is None
    rest()
    assert lst.join_key == group.key and lst.join_label == strings.JOIN_GROUP_LABEL
    release_global(win, to)
    assert calls(writer) == [("join", [], {"piece_ids": [group.piece_id, rows_of(win)[b].piece_id], "ahead": False,
                                           "how": "group"})]


def _opened_group_episode(win, k):
    """A short row (2–4 episodes) shown as a group and opened, and another show's row above it still in view (an
    opened row pushes the rows under it down): (dragged place, the group, its `k`-th episode (-1: its last), the global
    point on that episode's stone)."""
    rs = rows_of(win)
    ok = [i for i, r in enumerate(rs) if i > 0 and item_menu.joinable(r)]
    a = next(i for i in ok if 2 <= len(rs[i].episodes) <= 4 and any(j < i and rs[j].work_id != rs[i].work_id
                                                                      for j in ok))
    group = as_group(win, a)
    lst = lst_of(win)
    open_row(win, a)
    r, ep = stone_of(lst, a, k if k >= 0 else len(group.episodes) - 1)
    view = lst.viewport().rect()
    b = next(j for j in reversed(ok) if j < a and rs[j].work_id != rs[a].work_id and
             view.contains(title_point(lst, j)))
    return b, group, ep, lst.viewport().mapToGlobal(r.center())


def test_G2_IK2_a_rested_drop_on_an_opened_groups_episode_lands_after_it_in_one_move_toasted_with_undo(world):
    # Sonic's LM11-Q1: a drop into a group joins it where dropped — a move after that episode, in its tier (the store's
    # GI1 takes it into the group there)
    _seed, win, writer = world()
    b, group, ep, at = _opened_group_episode(win, 0)
    dragged = rows_of(win)[b]
    lift(win, b)
    move_global(win, at)
    settle()
    assert win.moves.running.target[0] == "list"                     # passing: a move, as before
    rest()
    assert win.moves.running.target == ("join", group.key)
    release_global(win, at)
    assert calls(writer) == [("move", list(drag.ids_of(dragged)), {"tier": group.tier, "before_id": None,
                                                                   "after_id": ep.id, "near": [], "end": False})]
    text = strings.ITEM_GROUPED_WITH.format(other=dragged.title, title=group.title)
    assert wait_until(lambda: win.toasts.card.message == text, 5)
    assert win.toasts.card.buttons, "its Undo"


def test_G2_IK2_a_rested_drop_on_an_opened_groups_last_episode_is_the_group_join_at_its_end(world):
    _seed, win, writer = world()
    b, group, _ep, at = _opened_group_episode(win, -1)
    dragged = rows_of(win)[b]
    lift(win, b)
    move_global(win, at)
    rest()
    release_global(win, at)
    assert calls(writer) == [("join", [], {"piece_ids": [group.piece_id, dragged.piece_id], "ahead": False,
                                           "how": "group"})]


def test_G2_IK2_an_episode_after_the_soon_line_lands_in_soon():
    eps = [SimpleNamespace(id=n) for n in (11, 12, 13)]
    row = SimpleNamespace(tier="now", soon_from=2, episodes=eps)
    assert [item_menu.ep_tier(row, e) for e in eps] == ["now", "now", "soon"]
    assert item_menu.ep_tier(SimpleNamespace(tier="now", soon_from=None, episodes=eps), eps[2]) == "now"


def test_G2_IK1_a_show_the_soon_line_runs_through_passes_both_its_pieces_to_the_group_join(world, monkeypatch):
    _seed, win, writer = world()
    b, a = two_shows(win)
    rs = rows_of(win)
    target = rs[a]._replace(soon_from=1, soon_piece=876543)
    dragged = rs[b]._replace(soon_from=1, soon_piece=765432)
    assert win.items.group_join(target, dragged) == target.key
    assert calls(writer) == [("join", [], {"piece_ids": [target.piece_id, 876543, dragged.piece_id, 765432],
                                           "ahead": False, "how": "group"})]


def test_G2_a_read_only_store_groups_nothing(world):
    _seed, win, writer = world(writable=False)
    b, a = two_shows(win)
    rs = rows_of(win)
    assert win.items.group_join(rs[a], rs[b]) is None
    assert win.items.add_to_group(rs[a], [e.id for e in rs[b].episodes], rs[b].title) is None
    assert writer.calls == []


# --- LM11b G3: ⋯ on a group (IK-5), *Rename…*, *Ungroup*, *Same show as…* (IK-6) ---------------------------------- #
def test_G3_IK5_a_groups_menu_is_the_moves_study_split_rename_ungroup_then_remove_and_nothing_of_one_show(world,
                                                                                                            monkeypatch):
    # a group is several shows: what it is, its cover, its folder, a skipped folder or another part of "its" title
    # would each be one show's, so none of them is offered
    _seed, win, _w = world()
    _b, a = two_shows(win)
    group = as_group(win, a)
    skips = []
    monkeypatch.setattr(win.items, "_offer_skip", lambda row, m: skips.append(row.key))
    entries = win.items.entries(group)
    assert names(entries) == ["pin", "split", "rename", "ungroup", "remove"]
    m = win.items.menu(group, win.mapToGlobal(QPoint(300, 300)))
    acts = m.actions()
    moves = [label for _n, label, _t, _ok in win.moves.menu_entries(group)]
    assert [x.text() for x in acts] == moves + [e.label for e in entries[:-1]] + ["", strings.ITEM_MENU["remove"][0]]
    assert acts[-2].isSeparator() and skips == []
    for act in acts:                                                 # every entry tipped and wired
        if not act.isSeparator():
            for x in [act] + (act.menu().actions() if act.menu() is not None else []):
                assert x.toolTip().strip() and _connected(x), x.text()
    m.close()


def test_G3_ungroup_is_one_writer_call_toasted_with_undo(world):
    _seed, win, writer = world()
    _b, a = two_shows(win)
    group = as_group(win, a)
    win.items.menu_pick(group, "ungroup")
    assert calls(writer) == [("ungroup", [], {"piece_id": group.piece_id})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_UNGROUPED.format(title=group.title), 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: len(writer.undone) == 1, 5)


def _rename_card(win, group):
    win.items.menu_pick(group, "rename")
    card = win.items.question
    assert card is not None and card.isVisible() and card.field is not None
    assert card.title.text() == strings.ITEM_RENAME_ASK and card.yes.text() == strings.ITEM_RENAME_YES
    assert card.no.text() == strings.CONFIRM_NO and card.field.text() == group.title    # the name shown
    return card


def test_G3_rename_writes_the_new_name_once_toasted_with_undo(world):
    _seed, win, writer = world()
    _b, a = two_shows(win)
    group = as_group(win, a)
    card = _rename_card(win, group)
    card.field.setText("  雲の上の郵便屋さんと仲間たち ")
    card.yes.click()
    assert calls(writer) == [("rename_piece", [], {"piece_id": group.piece_id, "title": "雲の上の郵便屋さんと仲間たち"})]
    text = strings.ITEM_RENAMED.format(title=group.title, name="雲の上の郵便屋さんと仲間たち")
    assert wait_until(lambda: win.toasts.card.message == text, 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: len(writer.undone) == 1, 5)


def test_G3_rename_to_nothing_names_it_after_its_shows_again_and_the_same_name_or_esc_writes_nothing(world):
    _seed, win, writer = world()
    _b, a = two_shows(win)
    group = as_group(win, a)
    card = _rename_card(win, group)
    assert wait_until(lambda: QApplication.focusWidget() is card.field, 3)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)  # Esc (the shell's router): No
    assert writer.calls == [] and win.items.question is None
    card = _rename_card(win, group)
    card.yes.click()                                                 # the name it had: nothing to write
    assert writer.calls == []
    card = _rename_card(win, group)
    card.field.setText("   ")
    card.yes.click()
    assert calls(writer) == [("rename_piece", [], {"piece_id": group.piece_id, "title": None})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_RENAME_CLEARED.format(title=group.title), 5)


def test_G3_a_read_only_store_renames_and_ungroups_nothing(world):
    _seed, win, writer = world(writable=False)
    _b, a = two_shows(win)
    group = as_group(win, a)
    assert all(not e.ok for e in win.items.entries(group) if e.name in ("rename", "ungroup"))
    assert win.items.ungroup(group) is None and win.items.rename(group, "山の音") is None
    win.items.menu_pick(group, "rename")
    assert win.items.question is None and writer.calls == []


def _same_show(win, row):
    return next((e for e in win.items.entries(row) if e.name == "same-show"), None)


def test_G3_IK6_same_show_as_lists_each_other_show_once_from_current_goal_finished_and_new_arrivals(world,
                                                                                                    monkeypatch):
    _seed, win, _w = world()
    view = win.page_widgets["current"].view_model
    b, a = two_shows(win)
    row = view.rows[b]
    entry = _same_show(win, row)
    assert entry is not None and entry.tip == strings.ITEM_MENU["same-show"][1] and entry.ok
    shows = [c.payload for c in entry.children]
    assert len({s.key for s in shows}) == len(shows)
    assert all(c.tip and c.ok and c.label == strings.ITEM_SAME_SHOW_PICK.format(title=c.payload.title,
                                                                               where=c.payload.where)
               for c in entry.children)
    works = [s.work_id for s in shows]
    assert row.work_id not in works and len(set(works)) == len(works)          # one entry per show, never its own
    current = [s for s in shows if s.where.endswith(("in Current", "in Current (Soon)"))]
    first = next(r for r in view.rows if item_menu.joinable(r) and not r.group and r.work_id != row.work_id)
    assert current[0].key == first.key and current[0].work_id == first.work_id
    # Goal's tiles as `view_rows.build` makes them (the window's own view, never a hand-made tile): Goal's shows not in
    # Current come next, each once, by its title (the merge names no piece), at most 20 of them (the cap
    # is each section's, never Current's first)
    in_current = {r.work_id for r in view.rows} | {row.work_id}
    tiles = [t for t in view.goal.works if not t.group and t.work_id not in in_current]
    assert tiles, "the seed's Goal holds shows Current doesn't"
    goal = [s for s in shows if s.where == strings.ITEM_JOIN_WHERE["goal"]]
    want = list(dict.fromkeys(t.work_id for t in tiles))[:item_menu.SAME_SHOW_MAX]
    assert [s.work_id for s in goal] == want
    assert len(current) <= item_menu.SAME_SHOW_MAX
    # Finished's and New arrivals' come after Goal's (seen here with Goal's emptied: the seed's Goal fills the list)
    with monkeypatch.context() as patched:
        patched.setattr(win.items, "_view", lambda: view._replace(goal=view.goal._replace(works=())))
        wheres = {c.payload.where for c in _same_show(win, row).children}
    assert strings.ITEM_JOIN_WHERE["goal"] not in wheres
    assert strings.ITEM_JOIN_WHERE["graduated"] in wheres or not any(m.rows for m in view.finished or ())
    assert strings.ITEM_JOIN_WHERE["arrivals"] in wheres or not view.arrivals
    # a group is no show of its own
    group = as_group(win, a)
    assert group.key not in [c.payload.key for c in _same_show(win, rows_of(win)[b]).children]
    assert _same_show(win, group) is None


def test_G3_same_show_as_asks_first_cancel_is_the_default_and_writes_nothing_yes_is_one_titles_merge(world):
    _seed, win, writer = world()
    b, _a = two_shows(win)
    row = rows_of(win)[b]
    show = _same_show(win, row).children[0].payload
    win.items.menu_pick(row, "same-show", show)
    card = win.items.question
    assert card.title.text() == strings.ITEM_SAME_SHOW_ASK.format(b=row.title, a=show.title)
    assert card.body.text() == strings.ITEM_SAME_SHOW_BODY.format(b=row.title, a=show.title)
    assert card.yes.text() == strings.ITEM_SAME_SHOW_YES and card.no.text() == strings.CONFIRM_NO
    assert card.default is card.no
    card.no.click()
    assert writer.calls == []
    win.items.menu_pick(row, "same-show", show)
    win.items.question.yes.click()
    # the titles alone — the picked show (A) keeps its name, nothing moves, no piece named
    assert calls(writer) == [("merge_works", [], {"keep_id": show.work_id, "other_ids": [row.work_id]})]
    text = strings.ITEM_SAME_SHOW_DONE.format(b=row.title, a=show.title)
    assert wait_until(lambda: win.toasts.card.message == text, 5)
    assert win.toasts.card.buttons, "its Undo"


def _pages(menu):
    """A submenu's chain of pages: [QMenu] — each page's *More…* opens the next."""
    out = [menu]
    while True:
        more = [a for a in out[-1].actions() if a.menu() is not None and a.text() == strings.MENU_MORE[0]]
        if not more:
            return out
        out.append(more[0].menu())


@pytest.mark.parametrize("size", ["M", "L"])
def test_same_show_as_with_many_shows_pages_with_more_so_each_page_fits_the_window(world, monkeypatch, qapp, size):
    """The follow-up (shots 6a): 20+ shows in *Same show as…* ran past an 800 px window, and at 150 % (a screen of
    fewer logical pixels) Qt split the menu into two columns past the window's top. A submenu holds `MENU_PAGE` entries
    and a *More…* opening the rest, page by page: each page fits the window (logical pixels: Windows' scaling leaves
    them as they are) and every show is reachable, in order, each still asking first."""
    theme_name, old_size, language = style.current()
    style.apply(qapp, theme_name, size, language)
    try:
        _seed, win, writer = world()
        win.resize(1280, 800)
        settle()
        b, _a = two_shows(win)
        row = rows_of(win)[b]
        many = [item_menu.Show(f"k{n}", 5000 + n, f"テスト作品{n}", strings.ITEM_JOIN_WHERE["goal"]) for n in range(30)]
        monkeypatch.setattr(win.items, "same_shows", lambda r: many)
        m = win.items.menu(row, win.mapToGlobal(QPoint(300, 100)))
        sub = next(a.menu() for a in m.actions() if a.text() == strings.ITEM_MENU["same-show"][0])
        pages = _pages(sub)
        assert len(pages) == 3                                   # 12, 12, 6
        reached = []
        for page in pages:
            assert page.sizeHint().height() <= win.height(), (page.sizeHint().height(), win.height())
            places = [page.actionGeometry(a) for a in page.actions()]
            assert len({r.x() for r in places}) == 1, "one column: Qt splits a menu taller than the screen"
            assert max(r.bottom() for r in places) <= win.height()
            shows = [a for a in page.actions() if a.menu() is None]
            assert len(shows) <= item_menu.MENU_PAGE + 1           # (one left over never gets a page alone)
            for a in shows:
                assert a.toolTip().strip() and _connected(a), a.text()
                reached.append(a.text())
            for a in page.actions():
                if a.menu() is not None:
                    assert a.toolTip() == strings.MENU_MORE[1] and a.isEnabled()
        assert reached == [strings.ITEM_SAME_SHOW_PICK.format(title=s.title, where=s.where) for s in many]
        last = [a for a in pages[-1].actions() if a.menu() is None][-1]
        last.trigger()
        assert win.items.question is not None and writer.calls == [], "the last show still asks first"
        win.items.question.no.click()
        m.close()
    finally:
        style.apply(qapp, theme_name, old_size, language)


def test_a_short_submenu_has_no_more(world):
    """*What is it?* (12 entries) and a short *Split here…* list stay one page."""
    _seed, win, _w = world()
    a, _b = split_parts(win)
    m = win.items.menu(rows_of(win)[a], win.mapToGlobal(QPoint(300, 300)))
    short = [act for act in m.actions() if act.menu() is not None
             and act.text() in (strings.ITEM_MENU["type"][0], strings.ITEM_MENU["split"][0])]
    assert len(short) == 2
    for act in short:
        assert len(_pages(act.menu())) == 1, act.text()
    m.close()


# --- row 28: an episode's own ⋯ -------------------------------------------------------------------------------------
def _long_row_scrolled(win):
    """The row with the most episodes (never Up Next), opened and scrolled so its head is off the top of the list:
    (its place, the row, [(QRect, Episode)] — its episode lines fully on screen)."""
    win.resize(1280, 640)                                              # a short window: the list has room to scroll
    settle()
    lst, rs = lst_of(win), rows_of(win)
    i = max(range(1, len(rs)), key=lambda k: len(rs[k].episodes))
    assert len(rs[i].episodes) >= 4, "the seed holds a row with several episodes"
    open_row(win, i)
    idx = lst.model().index(i, 0)
    bar = lst.verticalScrollBar()
    head = lst.delegate.slab_of(lst.visualRect(idx))
    bar.setValue(bar.value() + head.bottom() + 1 + 4)                  # the head just past the top
    settle()
    vp = lst.viewport().rect()
    assert lst.delegate.slab_of(lst.visualRect(idx)).bottom() < 0, "its head is off-screen"
    on = [(r, ep) for r, ep in lst.delegate.episode_lines(lst.model().entries[i], lst.visualRect(idx))
          if vp.contains(r)]
    assert len(on) >= 2
    return i, rs[i], on


def _ep_more(lst, i):
    return [pt for pt in part(lst, i) if pt[0] == "more-ep"]


def _entries_of(m):
    """A menu's entries, its separators left out."""
    return [a for a in m.actions() if not a.isSeparator()]


def part(lst, i):
    entry = lst.model().entries[i]
    return lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0)))


@pytest.mark.parametrize("size", ["S", "L"])
def test_row28_a_hovered_episode_shows_its_own_more_inside_the_list_and_opens_its_menu(world, qapp, size):
    """Row 28 (Sonic: "I cannot see the options … when i hover over each episode"): the ⋯ lived on the head alone,
    scrolled away under Current's heading while he was on Ep 13. An episode under the hand shows its own ⋯ in its line
    (text at 100 % and 130 %; logical pixels, so Windows' scaling moves nothing); its menu holds *Mark watched*, *Play*,
    *Split here…* and a hook's entry, whose callback runs."""
    theme_name, old_size, language = style.current()
    style.apply(qapp, theme_name, size, language)
    try:
        _seed, win, writer = world()
        ran = []
        win.items.episode_hooks.append(lambda row, ep: [item_menu.Entry(
            "mine-one", "Mine this one now", "Mine its cards now", True, payload=lambda: ran.append(ep.id))])
        lst = lst_of(win)
        i, row, on = _long_row_scrolled(win)
        assert _ep_more(lst, i) == [], "nothing hovered: no episode's ⋯"
        r, ep = on[1]
        hover(lst, r.center())
        more = _ep_more(lst, i)
        assert [(pt[3].id, pt[2]) for pt in more] == [(ep.id, strings.ROWS_EP_MORE_TIP)]
        assert lst.viewport().rect().contains(more[0][1]) and r.contains(more[0][1])
        assert lst.hot_eps(row.key) == {ep.id}
        # the row's own ⋯ (on its head) is unchanged
        assert [pt[3] for pt in part(lst, i) if pt[0] == "more"] == [None]
        press(lst, more[0][1].center())
        release(lst, more[0][1].center())
        settle()
        m = win.items.last_menu
        want = win.items.episode_entries(row, ep)
        assert [a.text() for a in _entries_of(m)] == [e.label for e in want]
        assert [e.name for e in want][:1] == ["ep-unwatched" if ep.watched else "ep-watched"]
        assert "split" in [e.name for e in want] and want[-1].name == "mine-one"
        assert ("ep-play" in [e.name for e in want]) == ep.can_play
        for a in _entries_of(m):
            assert a.toolTip().strip() and _connected(a), a.text()
        m.actions()[-1].trigger()
        assert ran == [ep.id], "the hook's callback ran"
        win.items.episode_pick(row, ep, want[0].name)
        assert [c[1] for c in calls(writer, "set_watched")] == [[ep.id]], "the stone's own path"
        m.close()
        # the hand gone: no ⋯
        move(lst, QPoint(-5, -5), buttons=Qt.MouseButton.NoButton)
        lst.leaveEvent(QEvent(QEvent.Type.Leave))
        assert _ep_more(lst, i) == []
    finally:
        style.apply(qapp, theme_name, old_size, language)


def test_row28_the_keyboard_steps_into_an_opened_rows_episodes_and_opens_one_episodes_menu(world):
    """↓ on an opened row steps into its episodes (that one shows its ⋯, as on hover), ↑ back out to its head; Enter,
    or the menu key, opens that episode's menu."""
    _seed, win, _w = world()
    lst = lst_of(win)
    i, row, _on = _long_row_scrolled(win)
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    QTest.keyClick(lst, Qt.Key.Key_Down)
    QTest.keyClick(lst, Qt.Key.Key_Down)
    settle()
    assert lst.currentIndex().row() == i and lst.ep_key == (row.key, row.episodes[1].id)
    assert [pt[3].id for pt in _ep_more(lst, i)] == [row.episodes[1].id]
    QTest.keyClick(lst, Qt.Key.Key_Return)
    settle()
    assert win.items.last_menu.isVisible()
    assert win.items.last_menu.accessibleName() == strings.ITEM_EP_MENU_NAME.format(ep=row.episodes[1].label)
    win.items.last_menu.close()
    QTest.keyClick(lst, Qt.Key.Key_Up)
    QTest.keyClick(lst, Qt.Key.Key_Up)
    assert lst.ep_key is None and lst.currentIndex().row() == i, "back on its head"
    assert _ep_more(lst, i) == []


def test_row28_an_episode_menu_offers_no_split_after_the_last_and_greys_its_writes_when_read_only(world):
    _seed, win, _w = world(writable=False)
    i, row, _on = _long_row_scrolled(win)
    entries = win.items.episode_entries(row, row.episodes[-1])
    assert "split" not in [e.name for e in entries]
    watched = entries[0]
    assert not watched.ok and watched.tip == win.items._refused_tip()
    play = [e for e in entries if e.name == "ep-play"]
    assert all(e.ok for e in play), "Play writes nothing"


def test_row28_a_failing_hook_leaves_the_rest_of_the_menu(world):
    _seed, win, _w = world()
    i, row, _on = _long_row_scrolled(win)
    win.items.episode_hooks.append(lambda row, ep: 1 / 0)
    assert win.items.episode_entries(row, row.episodes[0])[0].name in ("ep-watched", "ep-unwatched")


def test_row28_the_episode_menus_words_are_the_stones_and_plays_own(world):
    """IK-2, IK-10: one source each. *Mark watched* / *Mark not watched* say the stone's own click
    (`ROWS_STONE_ACTION`, as the stone's tip does); *Play* is ▶'s own verb and tip, by the episode's media — never a
    second wording ("in your video player" on a podcast)."""
    from app.services import view_rows as vr
    _seed, win, _w = world()
    i, row, _on = _long_row_scrolled(win)
    first = row.episodes[0]
    for ep in (first._replace(watched=False), first._replace(watched=True)):
        mark = win.items.episode_entries(row, ep)[0]
        action = strings.ROWS_STONE_ACTION[ep.watched]
        assert mark.label == strings.ITEM_EP_MARK[0].format(action=action)
        assert mark.tip.startswith(f"Mark {ep.label} {action}\n")
        stone = strings.ROWS_STONE_TIP.format(label=ep.label, state="", action=action)
        assert stone.endswith(action) and mark.label.endswith(action)
    for word in ("video", "audio", "EPUB"):
        tip = vr.STRINGS["play"].format(verb=vr.VERB[word], name=first.label, player=vr.STRINGS["player"][word],
                                        word=word)
        ep = first._replace(media_word=word, can_play=True, play_tip=tip)
        play = [e for e in win.items.episode_entries(row, ep) if e.name == "ep-play"]
        assert [(e.label, e.tip, e.ok) for e in play] == [(vr.VERB[word], tip, True)], word


def _on_screen(lst, i):
    """Row `i`'s episode lines fully in the list's view, as laid out now: [(QRect, Episode)]."""
    vp = lst.viewport().rect()
    return [(r, ep) for r, ep in lst.delegate.episode_lines(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0)))
            if vp.contains(r)]


def _click_ep_more(win, lst, i, line):
    """The hand on episode line `line` = (QRect, Episode) of row `i`, then a click (press, release) on its ⋯ -> the
    menu it opened. The press scrolls nothing: the ⋯ stays under the hand (the bug: Qt's autoScroll pulled a tall opened
    row's head back in, so the release met its title and nothing opened)."""
    r, ep = line
    win.items.last_menu = None
    hover(lst, r.center())
    more = [pt for pt in _ep_more(lst, i) if pt[3].id == ep.id]
    assert len(more) == 1, "the hovered episode, and it alone, shows its ⋯"
    bar = lst.verticalScrollBar().value()
    press(lst, more[0][1].center())
    assert lst.verticalScrollBar().value() == bar, "the press moves nothing under the hand"
    release(lst, more[0][1].center())
    settle()
    assert win.items.last_menu is not None, "the click opened the episode's menu"
    return win.items.last_menu


@pytest.mark.parametrize("fz,dpr", [(1.0, 1.0), (1.0, 1.5), (1.5, 1.0), (1.5, 1.5)])
def test_row28_a_click_on_an_episodes_more_opens_that_episodes_menu_at_every_text_size_and_screen_ratio(
        world, qapp, monkeypatch, fz, dpr):
    """Row 28's bug: a click on an episode's ⋯ opened nothing — the press made its row current and Qt scrolled the row's
    head back into view, the ⋯ slid away before the release. Text at 100 % and 150 %, a 150 % screen (the rows' scroll
    step snaps to it): the menu opens, its entries that episode's."""
    from app import theme
    monkeypatch.setitem(theme.TEXT_SIZES, "row28", fz)                 # a text size of its own: 150 %
    theme_name, old_size, language = style.current()
    style.apply(qapp, theme_name, "row28", language)
    try:
        assert rows.fz() == fz
        _seed, win, _w = world()
        lst = lst_of(win)
        monkeypatch.setattr(lst.viewport(), "devicePixelRatioF", lambda: dpr)
        assert lst.viewport().devicePixelRatioF() == dpr
        i, row, on = _long_row_scrolled(win)
        for line in (on[0], on[-1]):
            m = _click_ep_more(win, lst, i, line)
            assert [a.text() for a in _entries_of(m)] == [e.label for e in win.items.episode_entries(row, line[1])]
            assert m.accessibleName() == strings.ITEM_EP_MENU_NAME.format(ep=line[1].label)
            m.close()
    finally:
        style.apply(qapp, theme_name, old_size, language)


def test_row28_up_nexts_opened_episode_lines_show_their_own_more_and_a_click_opens_its_menu(world):
    """Up Next's card opens as a row does: its episode under the hand shows its ⋯ (none while no hand is there), and a
    click on it opens that episode's menu."""
    _seed, win, _w = world()
    lst = lst_of(win)
    assert lst.model().entries[0][0] == rows.HERO
    open_row(win, 0)
    hero = lst.model().entries[0][1]
    on = _on_screen(lst, 0)
    assert on and _ep_more(lst, 0) == []
    m = _click_ep_more(win, lst, 0, on[-1])
    want = win.items.episode_entries(hero, on[-1][1])
    assert [a.text() for a in _entries_of(m)] == [e.label for e in want]
    assert m.accessibleName() == strings.ITEM_EP_MENU_NAME.format(ep=on[-1][1].label)
    m.close()


def test_row28_in_a_group_an_episodes_menu_names_its_own_show(world):
    """LM11b: a group holds several shows, each with its Ep 1 — an episode's menu names its own show ("<show> · Ep N",
    as the group's row labels it), never another's."""
    _seed, win, _w = world()
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    i = next(k for k in range(1, len(rs)) if len(rs[k].episodes) >= 2 and item_menu.joinable(rs[k]))
    shows = ("星降る街の小さな工房", "白銀の書庫番")
    eps = tuple(e._replace(show=shows[n % 2]) for n, e in enumerate(rs[i].episodes))
    rs[i] = rs[i]._replace(group=True, works=(rs[i].work_id, 987654), episodes=eps)
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()
    open_row(win, i)
    lst = lst_of(win)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    settle()
    group = lst.model().entries[i][1]
    assert group.group
    for line in _on_screen(lst, i)[:2]:
        ep = line[1]
        named = view_rows.STRINGS["group_ep"].format(show=ep.show, label=ep.label)
        m = _click_ep_more(win, lst, i, line)
        assert m.accessibleName() == strings.ITEM_EP_MENU_NAME.format(ep=named)
        watched = win.items.episode_entries(group, ep)[0]
        assert named in watched.tip and shows[1 - shows.index(ep.show)] not in watched.tip
        m.close()


def test_row28_mark_watched_is_the_pages_one_done_path_with_its_undo(world, monkeypatch):
    """S12: *Mark watched* in an episode's menu is the page's one Done (`page.done`, as a stone's click) — the writer's
    `set_watched` for that file, its toast with Undo."""
    _seed, win, writer = world()
    lst = lst_of(win)
    i, row, on = _long_row_scrolled(win)
    line = next(ln for ln in on if not ln[1].watched)
    seen, real_done = [], win.items.page.done
    monkeypatch.setattr(win.items.page, "done", lambda r, e: (seen.append((r.key, e.id)), real_done(r, e)))
    m = _click_ep_more(win, lst, i, line)
    act = next(a for a in m.actions() if a.text() == strings.ITEM_EP_MARK[0].format(
        action=strings.ROWS_STONE_ACTION[False]))
    act.trigger()
    m.close()
    assert seen == [(row.key, line[1].id)]
    assert [c[1] for c in calls(writer, "set_watched")] == [[line[1].id]]
    assert wait_until(lambda: win.toasts.card is not None and win.toasts.card.buttons, 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()                               # Undo: that Done
    assert writer.undone and writer.undone[-1].op == "set_watched"


def test_row28_enter_on_the_keyboards_episode_opens_the_same_menu_the_click_does(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    i, row, _on = _long_row_scrolled(win)
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    QTest.keyClick(lst, Qt.Key.Key_Down)
    settle()
    ep = row.episodes[0]
    assert lst.ep_key == (row.key, ep.id)
    win.items.last_menu = None
    QTest.keyClick(lst, Qt.Key.Key_Enter)
    settle()
    m = win.items.last_menu
    assert m is not None and m.isVisible()
    assert [a.text() for a in _entries_of(m)] == [e.label for e in win.items.episode_entries(row, ep)]
    m.close()


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


# --- LM11b G2 on the real store ------------------------------------------------------------------------------------- #
def _state(store):
    items = store.conn.execute("SELECT id, tier, piece_id, work_id FROM items ORDER BY id").fetchall()
    pieces = store.conn.execute("SELECT id, kind, title FROM pieces ORDER BY id").fetchall()
    return {t: store.ids(t) for t in ls.TIERS}, items, pieces


def _rest_and_drop(win, b, a):
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    rest()
    assert win.moves.running.target[0] == "join"
    release_global(win, to)


@pytest.mark.parametrize("language", ("ja", "zh"))
def test_real_store_G2_two_shows_rested_and_dropped_are_one_group_row_and_undo_and_ctrl_z_make_them_two(real, language):
    # the dropped-on show keeps its place and its row's key; the group is one row holding both shows' files; the
    # toast's Undo, and Ctrl+Z after a second drop, put every row and piece back exactly — Japanese and Chinese
    store, win, _writer = real(language)
    b, a = two_shows(win)
    rs = rows_of(win)
    kept, dragged = rs[a], rs[b]
    ids = list(drag.ids_of(kept)) + list(drag.ids_of(dragged))
    before = _state(store)
    keys = [r.key for r in rs]
    _rest_and_drop(win, b, a)
    assert wait_until(lambda: {store.item(i)["piece_id"] for i in ids} == {kept.piece_id}, 5)
    assert store.conn.execute("SELECT kind FROM pieces WHERE id = ?", (kept.piece_id,)).fetchone()[0] == "group"
    assert {store.item(i)["work_id"] for i in ids} == {kept.work_id, dragged.work_id}       # each keeps its own show

    def one_row():
        now = rows_of(win)
        holding = [r for r in now if set(drag.ids_of(r)) & set(ids)]
        return len(holding) == 1 and holding[0].group and holding[0].key == kept.key and \
            list(drag.ids_of(holding[0])) == ids
    assert wait_until(one_row, 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    assert win.toasts.card.message == strings.ITEM_GROUPED_WITH.format(other=dragged.title, title=kept.title)
    win.toasts.card.buttons[0].click()                               # the toast's Undo
    assert wait_until(lambda: _state(store) == before, 5)
    assert wait_until(lambda: [r.key for r in rows_of(win)] == keys, 5)
    QTest.qWait(theme_swallow())
    b, a = two_shows(win)
    _rest_and_drop(win, b, a)
    assert wait_until(lambda: len({store.item(i)["piece_id"] for i in ids}) == 1, 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: _state(store) == before, 5)
    assert wait_until(lambda: [r.key for r in rows_of(win)] == keys, 5)


# --- LM11b G3 on the real store ------------------------------------------------------------------------------------- #
def _grouped_outside(store, win):
    """Two shows of Current grouped by another program: (the group's row, its items' ids, the state before)."""
    b, a = two_shows(win)
    rs = rows_of(win)
    ids = list(drag.ids_of(rs[a])) + list(drag.ids_of(rs[b]))
    before = _state(store)
    store.join([rs[a].piece_id, rs[b].piece_id], how="group")
    assert wait_until(lambda: any(r.group and list(drag.ids_of(r)) == ids for r in rows_of(win)), 10)
    return next(r for r in rows_of(win) if r.group), ids, before


def test_real_store_G3_ungroup_makes_two_rows_and_its_undo_one_again(real):
    store, win, _writer = real()
    group, ids, before = _grouped_outside(store, win)
    grouped = _state(store)
    win.items.menu_pick(group, "ungroup")
    assert wait_until(lambda: len({store.item(i)["piece_id"] for i in ids}) == 2, 5)
    assert wait_until(lambda: sum(1 for r in rows_of(win) if set(drag.ids_of(r)) & set(ids)) == 2, 5)
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_UNGROUPED.format(title=group.title), 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: _state(store) == grouped, 5)


def test_real_store_G4_a_group_picked_alone_offers_no_group_and_a_pick_writes_nothing(real):
    # one group's row picked alone spans two shows, yet is one pick: the store makes no group of it (it returned
    # nothing and the picks went, silently), so *Group…* isn't offered and the pick stays. Wrong: offered, then nothing
    store, win, _writer = real()
    group, _ids, _before = _grouped_outside(store, win)
    lst = lst_of(win)
    at = next(i for i, r in enumerate(rows_of(win)) if r.key == group.key)
    ctrl_click(lst, title_point(lst, at))
    assert lst.picked_rows == {group.key} and win.items.group_entry() is None
    m = win.items.menu(group, win.mapToGlobal(QPoint(300, 300)))
    assert strings.ITEM_MENU["group"][0] not in [x.text() for x in m.actions()]
    m.close()
    grouped = _state(store)
    win.items.menu_pick(group, "group")
    settle()
    assert _state(store) == grouped and lst.picked_rows == {group.key}


def test_real_store_G3_rename_names_the_group_and_undo_gives_back_its_shows_name(real):
    store, win, _writer = real()
    group, _ids, _before = _grouped_outside(store, win)
    win.items.menu_pick(group, "rename")
    card = win.items.question
    card.field.setText("雨の日の喫茶店めぐり")
    card.yes.click()
    assert wait_until(lambda: any(r.key == group.key and r.title == "雨の日の喫茶店めぐり" for r in rows_of(win)), 5)
    assert store.conn.execute("SELECT title FROM pieces WHERE id = ?", (group.piece_id,)).fetchone()[0] == \
        "雨の日の喫茶店めぐり"
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: any(r.key == group.key and r.title == group.title for r in rows_of(win)), 5)


def test_real_store_G3_same_show_as_makes_one_title_and_one_undo_makes_two(real):
    store, win, _writer = real()
    b, _a = two_shows(win)
    row = rows_of(win)[b]
    show = next(c.payload for c in _same_show(win, row).children if c.payload.key in [r.key for r in rows_of(win)])
    before = _state(store)
    win.items.menu_pick(row, "same-show", show)
    win.items.question.yes.click()
    assert wait_until(lambda: {store.item(i)["work_id"] for i in drag.ids_of(row)} == {show.work_id}, 5)
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SAME_SHOW_DONE.format(b=row.title,
                                                                                           a=show.title), 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: _state(store) == before, 5)


def test_real_store_G3_same_show_as_refused_by_anilist_says_why_in_the_bar_and_changes_nothing(real, monkeypatch):
    store, win, _writer = real()
    b, _a = two_shows(win)
    row = rows_of(win)[b]
    show = next(c.payload for c in _same_show(win, row).children if c.payload.key in [r.key for r in rows_of(win)])
    with store._writing():                                       # as each title's AniList record would set them
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (101, show.work_id))
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (202, row.work_id))
    before = _state(store)
    said = []
    say = win.say
    monkeypatch.setattr(win, "say", lambda text: (said.append(text), say(text)))
    win.items.menu_pick(row, "same-show", show)
    win.items.question.yes.click()
    assert wait_until(lambda: any(ls.TITLES_APART["anilist_id"] in t for t in said), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    assert _state(store) == before
    done = strings.ITEM_SAME_SHOW_DONE.format(b=row.title, a=show.title)
    assert win.toasts.card is None or win.toasts.card.message != done          # no toast for what never happened


# --- LM11b fix round A ---------------------------------------------------------------------------------------------- #
def test_same_show_as_offers_twenty_from_each_section_never_twenty_in_all(world):
    # a library with more than 20 shows in Current: Goal's are still offered (20 per section), and a show past
    # Current's 20 is never listed again under Goal (where it first stands only)
    _seed, win, _w = world()
    view = win.page_widgets["current"].view_model
    b, _a = two_shows(win)
    row = view.rows[b]
    many = list(view.rows) + [r._replace(key=f"x{n}", work_id=900000 + n)
                              for n, r in enumerate([view.rows[b]] * (item_menu.SAME_SHOW_MAX + 5))]
    big = view._replace(rows=type(view.rows)(many))
    win.items._view = lambda: big
    shows = win.items.same_shows(row)
    current = [s for s in shows if s.where not in (strings.ITEM_JOIN_WHERE["goal"], strings.ITEM_JOIN_WHERE["graduated"],
                                                   strings.ITEM_JOIN_WHERE["arrivals"])]
    goal = [s for s in shows if s.where == strings.ITEM_JOIN_WHERE["goal"]]
    assert len(current) == item_menu.SAME_SHOW_MAX
    assert goal, "Goal's shows offered with Current full"
    in_current = {r.work_id for r in many}
    assert all(s.work_id not in in_current for s in goal)


def _shown(win, view, rs):
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()


def _two_show_group(win, title=None):
    """A Current row (2+ episodes) shown as a group of two of the seed's shows: its episodes its own show's, its last
    another's (each episode's `work_id` / `show`, as `view_rows` makes a group's), named `title` (None: as the store
    names an unnamed group, "<first> + 1 more"). -> (the group row, the other show's row)."""
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    b, a = two_shows(win)
    g, o = rs[a], rs[b]
    eps = [e._replace(work_id=g.work_id, show=g.title) for e in g.episodes]
    eps[-1] = eps[-1]._replace(work_id=o.work_id, show=o.title)
    name = title if title is not None else view_rows.STRINGS["group_name"].format(first=g.title, n=1)
    rs[a] = g._replace(group=True, works=(g.work_id, o.work_id), episodes=tuple(eps), title=name)
    _shown(win, view, rs)
    return rows_of(win)[a], o


def test_G3_an_unnamed_groups_rename_cleared_or_to_its_starting_name_writes_nothing(world):
    # its stored name is None: clearing the field, or Rename with the name it was shown, is no change — no journal
    # entry, no toast
    _seed, win, writer = world()
    group, _o = _two_show_group(win)
    assert item_menu.unnamed(group)
    assert win.items.rename(group, "") is None and win.items.rename(group, "   ") is None
    assert win.items.rename(group, f" {group.title} ") is None
    assert writer.calls == []
    assert win.items.rename(group, "雲の上の郵便屋さんと仲間たち") is not None
    assert calls(writer) == [("rename_piece", [], {"piece_id": group.piece_id, "title": "雲の上の郵便屋さんと仲間たち"})]


def test_G3_a_named_groups_rename_cleared_names_it_after_its_shows_again(world):
    _seed, win, writer = world()
    group, _o = _two_show_group(win, title="雲の上の郵便屋さんと仲間たち")
    assert not item_menu.unnamed(group)
    assert win.items.rename(group, group.title) is None and writer.calls == []
    assert win.items.rename(group, "") is not None
    assert calls(writer) == [("rename_piece", [], {"piece_id": group.piece_id, "title": None})]


def test_split_in_a_group_names_each_episode_with_its_show(world):
    # two shows' Ep 1 must never read alike: "<show> · Ep N", as the group's row labels them
    _seed, win, _w = world()
    group, other = _two_show_group(win)
    split = next(e for e in win.items.entries(group) if e.name == "split")
    eps = group.episodes
    cuts = [k for k in range(1, len(eps)) if view_rows.split_piece(group, k) is not None]
    assert cuts
    labels = [c.label for c in split.children]
    assert labels == [strings.ITEM_SPLIT_AFTER.format(ep=f"{eps[k - 1].show} · {eps[k - 1].label}") for k in cuts]
    assert all(f"{eps[k - 1].show} · {eps[k - 1].label}" in c.tip for k, c in zip(cuts, split.children))
    # a show's own row keeps its plain labels
    row = next(r for r in rows_of(win) if not r.group and len(r.episodes) >= 2 and item_menu.joinable(r))
    assert item_menu.ep_name(row, row.episodes[0]) == row.episodes[0].label


def test_G4_group_counts_a_groups_second_show_by_its_episodes_own_title(world):
    # a group's SECOND show's episode, and a part of its first show, are two shows — Group… is offered
    _seed, win, _w = world()
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    ok = [i for i, r in enumerate(rs) if i > 0 and item_menu.joinable(r) and len(r.episodes) >= 2]
    a = ok[0]
    b = next(i for i in ok if rs[i].work_id != rs[a].work_id)
    other_work, g = rs[b].work_id, rs[a]
    eps = list(g.episodes)
    eps[-1] = eps[-1]._replace(work_id=other_work, show=rs[b].title)
    rs[a] = g._replace(group=True, works=(g.work_id, other_work), episodes=tuple(eps))
    rs[b] = rs[b]._replace(work_id=g.work_id, works=(g.work_id,))     # a run of the group's FIRST show elsewhere
    _shown(win, view, rs)
    lst = lst_of(win)
    lst.picked_eps = {(rs[a].key, eps[-1].id)}
    lst.picked_rows = {rs[b].key}
    assert win.items._to_group() is not None, "picks of two shows offer Group…"
    # and a whole group alone is its every show: with a part of one of them, still two shows
    lst.picked_eps, lst.picked_rows = set(), {rs[a].key, rs[b].key}
    assert len(win.items._shows([rows_of(win)[a], rows_of(win)[b]], [])) == 2
    # one show's two parts are still one show (no group of them)
    lst.picked_rows = {rs[b].key}
    lst.picked_eps = {(rs[a].key, eps[0].id)}
    assert win.items._to_group() is None


GROUP_WRITES = {
    "group": lambda win, g, o: (setattr(lst_of(win), "picked_rows", {g.key, o.key}), win.items.group(g))[1],
    "group_join": lambda win, g, o: win.items.group_join(g, o),
    "into_group_at": lambda win, g, o: win.items.into_group_at(g, g.episodes[0], drag.ids_of(o), o.title, (o.key,)),
    "add_to_group": lambda win, g, o: win.items.add_to_group(g, drag.ids_of(o), o.title),
    "same_show": lambda win, g, o: win.items.same_show(o, item_menu.Show(g.key, g.work_id, g.title, "")),
}
GROUP_TEXT = {
    "group": lambda g, o: strings.ITEM_GROUPED.format(n=2),
    "same_show": lambda g, o: strings.ITEM_SAME_SHOW_DONE.format(b=o.title, a=g.title),
}


@pytest.mark.parametrize("name", list(GROUP_WRITES))
def test_every_group_write_toasts_only_once_saved_and_never_for_nothing_landed(world, name):
    # a busy store: no toast (and no Undo) until the store saved it; one that lands as nothing toasts nothing
    _seed, win, writer = world()
    b, a = two_shows(win)
    rs = rows_of(win)
    g, o = (as_group(win, a), rs[b]) if name in ("into_group_at", "add_to_group") else (rs[a], rs[b])
    text = GROUP_TEXT.get(name, lambda g, o: strings.ITEM_GROUPED_WITH.format(other=o.title, title=g.title))(g, o)
    shown = lambda: win.toasts.card is not None and win.toasts.card.message == text     # noqa: E731
    writer.stuck = True
    assert GROUP_WRITES[name](win, g, o) is not None
    settle(200)
    assert not shown(), "toasted before the store saved it"
    writer.free()
    assert wait_until(shown, 5) and win.toasts.card.buttons, "its toast and Undo once saved"
    win.toasts.close()
    settle()
    op = calls(writer)[-1][0]
    writer.nothing = {op}
    writer.calls.clear()
    lst_of(win).clear_picks()
    win.moves.toasted = None
    assert GROUP_WRITES[name](win, g, o) is not None and calls(writer)
    assert wait_until(lambda: not win.moves.tickets, 5)
    settle(200)
    assert win.moves.toasted is None, "toasted for what never happened"


def test_a_target_in_finished_or_new_arrivals_is_never_a_groups(world):
    # the store refuses a group there (`NO_GROUP_TIERS`): the window never offers or writes it
    _seed, win, writer = world()
    b, a = two_shows(win)
    rs = rows_of(win)
    for tier in ls.NO_GROUP_TIERS:
        target = as_group(win, a)._replace(tier=tier)
        assert not item_menu.groups_there(target)
        assert win.items.group_join(rs[a]._replace(tier=tier), rs[b]) is None
        assert win.items.into_group_at(target, target.episodes[0], drag.ids_of(rs[b]), rs[b].title) is None
        assert win.items.add_to_group(target, drag.ids_of(rs[b]), rs[b].title) is None
    assert writer.calls == []
    assert item_menu.groups_there(rs[a]) and item_menu.groups_there(rs[a]._replace(tier="soon"))


# --- real store: the review's cases, red on the code before this round ---------------------------- #
def _tiers(store, ids):
    return [store.item(i)["tier"] for i in ids]


def _same_show_to(win, row, where):
    entry = _same_show(win, row)
    assert entry is not None, "no Same show as… on the row"
    return next((c.payload for c in entry.children if c.payload.where == where), None)


def _said(win, monkeypatch):
    said = []
    say = win.say
    monkeypatch.setattr(win, "say", lambda text: (said.append(text), say(text)))
    return said


@pytest.mark.parametrize("where", ["arrivals", "goal", "graduated"])
def test_real_store_same_show_as_a_show_elsewhere_makes_one_title_and_moves_no_file(real, where, monkeypatch):
    # "Make B part of A" — never "send B's Current files to New arrivals / Goal", and a show in Finished merges too
    # (every join into Finished was refused before)
    store, win, _w = real()
    b, a = two_shows(win)
    rs = rows_of(win)
    row, other = rs[b], rs[a]
    mine = list(drag.ids_of(row))
    if where == "graduated":
        store.finish(list(drag.ids_of(other)))
    else:
        store.set_tier(list(drag.ids_of(other)), where)
    assert wait_until(lambda: all(r.work_id != other.work_id for r in rows_of(win)), 10)
    row = next(r for r in rows_of(win) if list(drag.ids_of(r)) == mine)
    before = {i: (store.item(i)["tier"], store.item(i)["ord"], store.item(i)["piece_id"]) for i in mine}
    name = store._work_row(other.work_id)["title"]
    show = _same_show_to(win, row, strings.ITEM_JOIN_WHERE[where])
    assert show is not None, f"{where}'s show offered"
    said = _said(win, monkeypatch)
    win.items.menu_pick(row, "same-show", show)
    win.items.question.yes.click()
    assert wait_until(lambda: {store.item(i)["work_id"] for i in mine} == {other.work_id}, 5), "made one show"
    assert {i: (store.item(i)["tier"], store.item(i)["ord"], store.item(i)["piece_id"]) for i in mine} == before
    assert store._work_row(other.work_id)["title"] == name, "A keeps its name"
    assert not said, said
    text = strings.ITEM_SAME_SHOW_DONE.format(b=row.title, a=show.title)
    assert wait_until(lambda: win.toasts.card is not None and win.toasts.card.message == text, 5)


def test_real_store_same_show_in_current_is_one_call_nothing_moves_and_undo_makes_two_shows_again(real):
    store, win, w = real()
    b, a = two_shows(win)
    rs = rows_of(win)
    row, other = rs[b], rs[a]
    mine, theirs = list(drag.ids_of(row)), list(drag.ids_of(other))
    order = {t: store.ids(t) for t in ("now", "soon", "goal")}
    pieces = {i: store.item(i)["piece_id"] for i in mine + theirs}
    show = next(c.payload for c in _same_show(win, row).children if c.payload.work_id == other.work_id)
    given = []
    real_merge = w.merge_works
    w.merge_works = lambda *a, **k: (given.append((a, k)), real_merge(*a, **k))[1]
    win.items.menu_pick(row, "same-show", show)
    win.items.question.yes.click()
    assert wait_until(lambda: {store.item(i)["work_id"] for i in mine} == {other.work_id}, 5)
    assert [g[0] for g in given] == [(other.work_id, [row.work_id])], "one call, A kept"
    assert {t: store.ids(t) for t in ("now", "soon", "goal")} == order
    assert {i: store.item(i)["piece_id"] for i in mine + theirs} == pieces
    text = strings.ITEM_SAME_SHOW_DONE.format(b=row.title, a=other.title)
    assert wait_until(lambda: win.toasts.card is not None and win.toasts.card.message == text, 5)
    win.toasts.card.buttons[0].click()                                # its Undo: two shows again
    assert wait_until(lambda: {store.item(i)["work_id"] for i in mine} == {row.work_id}, 5)
    assert {t: store.ids(t) for t in ("now", "soon", "goal")} == order


def test_real_store_same_show_the_ids_refuse_says_why_in_the_bar_and_toasts_nothing(real, monkeypatch):
    store, win, _w = real()
    b, a = two_shows(win)
    rs = rows_of(win)
    row, other = rs[b], rs[a]
    mine = list(drag.ids_of(row))
    with store._writing():
        store.conn.execute("UPDATE works SET anilist_id = 7 WHERE id = ?", (other.work_id,))
        store.conn.execute("UPDATE works SET anilist_id = 8 WHERE id = ?", (row.work_id,))
    show = next(c.payload for c in _same_show(win, row).children if c.payload.work_id == other.work_id)
    said = _said(win, monkeypatch)
    win.items.menu_pick(row, "same-show", show)
    win.items.question.yes.click()
    assert wait_until(lambda: any(ls.TITLES_APART["anilist_id"] in t for t in said), 5), said
    assert wait_until(lambda: not win.moves.tickets, 5)
    settle(200)
    assert {store.item(i)["work_id"] for i in mine} == {row.work_id}
    text = strings.ITEM_SAME_SHOW_DONE.format(b=row.title, a=other.title)
    assert win.toasts.card is None or win.toasts.card.message != text


def test_real_store_a_group_dropped_on_an_opened_groups_episode_joins_it_whole_never_cuts_it(real):
    store, win, _w = real()
    rs = rows_of(win)
    ok = [i for i, r in enumerate(rs) if i > 0 and item_menu.joinable(r) and len(r.episodes) >= 2]
    works, pick = set(), []
    for i in ok:
        if rs[i].work_id not in works:
            works.add(rs[i].work_id)
            pick.append(i)
    assert len(pick) >= 4, "four shows in Current"
    a1, a2, c1, c2 = (rs[i] for i in pick[:4])
    store.join([a1.piece_id, a2.piece_id], how="group")
    store.join([c1.piece_id, c2.piece_id], how="group")
    g1_ids = list(drag.ids_of(a1)) + list(drag.ids_of(a2))
    g2_ids = list(drag.ids_of(c1)) + list(drag.ids_of(c2))
    assert wait_until(lambda: sum(1 for r in rows_of(win) if r.group) == 2, 10)
    g1 = next(r for r in rows_of(win) if r.group and set(drag.ids_of(r)) == set(g1_ids))
    g2 = next(r for r in rows_of(win) if r.group and set(drag.ids_of(r)) == set(g2_ids))
    win.items._ep_at = (g1.key, g1.episodes[0])         # as `target()` leaves it with the hand on that episode
    d = SimpleNamespace(external=False, row=g2, ids=list(drag.ids_of(g2)), title=g2.title)
    assert win.items.drop(d, g1.key) == g1.key
    assert wait_until(lambda: not win.moves.tickets, 5)
    settle(200)
    text = strings.ITEM_GROUPED_WITH.format(other=g2.title, title=g1.title)
    assert win.toasts.card is not None and win.toasts.card.message == text
    assert len({store.item(i)["piece_id"] for i in g1_ids + g2_ids}) == 1, \
        {i: store.item(i)["piece_id"] for i in g1_ids + g2_ids}


def test_real_store_a_group_join_the_store_refuses_is_never_toasted_as_grouped(real, monkeypatch):
    # the target's piece gone (another program grouped it meanwhile): the bar says why, no Grouped toast, no Undo
    store, win, _w = real()
    b, a = two_shows(win)
    rs = rows_of(win)
    target, dragged = rs[a], rs[b]
    c = next(r for r in rs[1:] if item_menu.joinable(r) and r.work_id not in (target.work_id, dragged.work_id))
    store.join([c.piece_id, target.piece_id], how="group")
    said = _said(win, monkeypatch)
    win.items.group_join(target, dragged)               # the drop, from the row the window still shows
    assert wait_until(lambda: not win.moves.tickets, 5)
    settle(200)
    assert any("gone" in t for t in said), said
    grouped = strings.ITEM_GROUPED_WITH.format(other=dragged.title, title=target.title)
    assert win.toasts.card is None or win.toasts.card.message != grouped


# --- LM11b mutant pass: the gaps it found ----------------------------------------------------------------------- #
def test_G3_same_show_as_from_a_group_row_merges_no_title(world):
    # a group is no show (its work id is its first show's): asked from a group's row — a menu made before it became
    # one — the merge writes nothing, never folding that first show into another
    _seed, win, writer = world()
    b, a = two_shows(win)
    show = _same_show(win, rows_of(win)[b]).children[0].payload
    group = as_group(win, a)
    assert win.items.same_show(group, show) is None
    assert writer.calls == []


def test_G3_same_show_as_never_offers_a_group_tile_in_goal(world, monkeypatch):
    # a group sitting in Goal is one tile of several shows, no show of its own: never offered as the show to merge into
    _seed, win, _w = world()
    view = win.page_widgets["current"].view_model
    b, _a = two_shows(win)
    row = view.rows[b]
    elsewhere = {r.work_id for r in view.rows} | {r.work_id for m in view.finished or () for r in m.rows} | \
        {a.work_id for a in view.arrivals or ()}
    tile = next(t for t in view.goal.works if not t.group and t.work_id not in elsewhere)
    goal = strings.ITEM_JOIN_WHERE["goal"]
    assert tile.work_id in [c.payload.work_id for c in _same_show(win, row).children if c.payload.where == goal]
    works = tuple(t._replace(group=True) if t is tile else t for t in view.goal.works)
    monkeypatch.setattr(win.items, "_view", lambda: view._replace(goal=view.goal._replace(works=works)))
    assert tile.work_id not in [c.payload.work_id for c in _same_show(win, row).children]


def test_G2_a_drop_on_a_groups_episode_past_the_soon_line_moves_it_into_soon(world):
    # a group the Soon line runs through: a drop after one of its Soon episodes lands in Soon, beside it (`ep_tier`)
    _seed, win, writer = world()
    b, a = two_shows(win)
    rs = rows_of(win)
    group = as_group(win, a)._replace(tier="now", soon_from=1)
    ep = group.episodes[1]
    ids = drag.ids_of(rs[b])
    assert win.items.into_group_at(group, ep, ids, rs[b].title) == group.key
    assert calls(writer) == [("move", list(ids), {"tier": "soon", "before_id": None, "after_id": ep.id, "near": [],
                                                  "end": False})]


def test_G2_a_rest_on_a_stale_finished_row_is_never_a_group_target(world):
    # a row still drawn in Current though it is in Finished now (a stale view): no group lives there, so a resting hand
    # never outlines it with *Drop to group* — the drop is a move, as any
    _seed, win, writer = world()
    b, a = two_shows(win)
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    rs[a] = rs[a]._replace(tier="graduated")
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    rest()
    assert win.moves.running.target[0] == "list" and lst_of(win).join_key is None
    win.moves.cancel()
    assert writer.calls == []
