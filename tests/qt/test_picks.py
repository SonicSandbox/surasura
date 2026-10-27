"""The picks in every list (A4, D1 list half; Mattias #1, #2 — `rows.RowsView` picks, `item_menu.fill_picks_menu`,
`drag.DragController.send_picks`, Goal's sheet's tiles): Ctrl / Shift+click and Ctrl+A in Current, Soon, Goal and
Finished; ⋯ or a right-click on a picked row offers *Up next* · *Soon* · *Goal* · *Finished* · *Remove…* for all of
them, each ONE store command, one toast naming the count, one Undo; a drag from a picked row carries them all. On the
window's seed (invented Japanese and Chinese titles) through a recording writer, and on a real migrated store where the
store's own answer matters (the rows after, one Undo putting every one back).

Sonic: "I have the Control-click-to-select-multiple but … I don't have any way to interact with those."
What a wrong answer would cost a learner:
  * picks he can make but never use (no menu, no drag), or a menu offering to send Soon's picks to Soon;
  * twelve titles sent as twelve commands — twelve toasts, twelve Undos, and a half-done block if one is refused;
  * *Remove…* on many titles without asking first;
  * a store that can't be written taking the picks' command anyway (E4);
  * picks in two lists at once, sent from the one he isn't looking at;
  * a pick that repaints the whole list (S19), or Ctrl+A that freezes the window at 20,000 files.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt                                  # noqa: E402
from PyQt6.QtTest import QTest                                               # noqa: E402

from app import theme                                                        # noqa: E402
from app.qt import confirm, drag, rows, strings                               # noqa: E402
from tests.fixtures import window_seed                                       # noqa: E402
from tests.qt.conftest import wait_until                                     # noqa: E402
from tests.qt.test_drag import (mouse, move, move_global, open_window, press, real, release_global,  # noqa: E402,F401
                                settle, title_point, well_point)
from tests.qt.test_item_menu import ItemWriter, click_with, ctrl_click        # noqa: E402

CTRL = Qt.KeyboardModifier.ControlModifier
LEFT = Qt.MouseButton.LeftButton


class PicksWriter(ItemWriter):
    """The recording writer with the picks' commands (`moves.Writer.place` / `put_back`)."""

    def place(self, ids, where, label=None):
        return self._put("place", ids, label, where=where)

    def put_back(self, ids, label=None):
        return self._put("put_back", ids, label)


@pytest.fixture
def world(qapp):
    made = []

    def make(language="ja", writable=True, files=window_seed.SMALL):
        from app import settings_manager
        settings_manager.save_keys({"target_language": language})      # the window's language is its library's
        seed = window_seed.build(files=files, language=language)
        writer = PicksWriter(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)
    from app.qt import style
    style.apply(qapp, "night", "M", "ja")         # the harness puts back theme and size, not the language


def lst_of(win, name="current"):
    return win.page_widgets[name].list


def rows_of(win):
    return win.page_widgets["current"].view_model.rows


def calls(writer, op=None):
    return [c for c in writer.calls if op is None or c[0] == op]


def current_rows(win, tier):
    """Places of Current's list rows of `tier` that can be picked and finished (never Up Next, hato's mix or a split's
    first part)."""
    lst = lst_of(win)
    shown = rows_of(win)
    return [i for i, e in enumerate(lst.model().entries) if i and e[0] == rows.ROW and e[1].tier == tier and
            getattr(e[1], "soon_from", None) is None and lst.pickable(e[1]) and not drag.split_first(shown, e[1])]


def show_finished(win):
    win.show_tab("finished")
    page = win.page_widgets["finished"]
    assert wait_until(lambda: page.view_model is not None and page.view_model.finished and
                      any(e[0] == rows.FINISHED for e in page.list.model().entries), 10)
    settle()
    return page.list


def finished_rows(win):
    return [(i, e[1]) for i, e in enumerate(lst_of(win, "finished").model().entries) if e[0] == rows.FINISHED]


def row_title_point(lst, i):
    """A point on row `i`'s title — a Current row's, or a Finished row's line."""
    entry = lst.model().entries[i]
    if entry[0] == rows.FINISHED:
        rect = lst.visualRect(lst.model().index(i, 0))
        return QPoint(rect.left() + 60, rect.top() + round(theme.SIZES["row"] * rows.fz()) // 2)
    return title_point(lst, i)


def open_sheet(win):
    QTest.mouseClick(win.dock, LEFT, pos=win.dock.bar_rect().center().toPoint())
    sheet = win.goal_sheet
    assert wait_until(sheet.isVisible, 2)
    settle()
    return sheet


def tile_click(tile, mods=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(tile, LEFT, mods, QPoint(tile.width() // 2, tile.height() // 3))
    settle(20)


def menu_texts(m):
    return [a.text() for a in m.actions() if not a.isSeparator()]


def picks_menu_of(win, lst, i):
    """The ⋯ of picked row `i` (`menu_requested`, as ⋯ and a right-click ask)."""
    row = lst.model().entries[i][1]
    lst.menu_requested.emit(row, win.mapToGlobal(QPoint(300, 300)))
    owner = win.items if lst is lst_of(win) else win.finished
    return owner.last_menu


def pick_entry(m, name):
    label = strings.PICKS_MENU[name][0]
    act = next(a for a in m.actions() if a.text() == label)
    m.close()
    act.trigger()
    settle()
    return act


# --- picking in every list ----------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ("ja", "zh"))
def test_A4_ctrl_click_picks_in_soon_finished_and_goal_and_each_shows_it_picked(world, language):
    """Current's picks were all there was: now Soon's rows (below the Soon line), Finished's rows and Goal's tiles take
    Ctrl+click too, and a picked one paints as picked."""
    _seed, win, writer = world(language)
    lst = lst_of(win)
    soon = current_rows(win, "soon")
    assert len(soon) >= 2
    ctrl_click(lst, title_point(lst, soon[0]))
    ctrl_click(lst, title_point(lst, soon[1]))
    assert lst.picked_rows == {lst.model().entries[i][1].key for i in soon[:2]}
    fin = show_finished(win)
    (i, a), (j, b) = finished_rows(win)[:2]
    ctrl_click(fin, row_title_point(fin, i))
    click_with(fin, row_title_point(fin, j), Qt.KeyboardModifier.ShiftModifier | CTRL)
    assert {a.key, b.key} <= fin.picked_rows
    assert not lst.picked_rows                                           # picks live in one list at a time
    win.show_tab("current")
    settle()
    sheet = open_sheet(win)
    tiles = sheet.order[:2]
    tile_click(tiles[0], CTRL)
    tile_click(tiles[1], CTRL)
    assert sheet.picks == {t.work.key for t in tiles}
    assert not fin.picked_rows
    assert writer.calls == []                                            # a pick writes nothing


@pytest.mark.parametrize("language", ("ja", "zh"))
def test_A4_ctrl_a_picks_every_row_of_the_list_in_focus(world, language):
    """Ctrl+A: every row this list can pick — Current's (hato's mix left out, as Ctrl+click leaves it), Finished's,
    Goal's tiles; a plain click lets them go."""
    _seed, win, _w = world(language)
    lst = lst_of(win)
    lst.setFocus()
    QTest.keyClick(lst, Qt.Key.Key_A, CTRL)
    want = {e[1].key for e in lst.model().entries if e[0] in (rows.HERO, rows.ROW) and lst.pickable(e[1])}
    assert lst.picked_rows == want and len(want) > 5
    assert all(e[1].key not in lst.picked_rows for e in lst.model().entries if e[0] == rows.ROW and drag.is_mix(e[1]))
    press(lst, title_point(lst, current_rows(win, "now")[0]))           # a plain click on a picked row: kept for
    assert lst.picked_rows == want                                      # its drag until the release …
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, title_point(lst, current_rows(win, "now")[0]), LEFT,
          Qt.MouseButton.NoButton)
    settle()
    assert not lst.picked_rows                                          # … which lets them go
    fin = show_finished(win)
    fin.setFocus()
    QTest.keyClick(fin, Qt.Key.Key_A, CTRL)
    assert fin.picked_rows == {r.key for _i, r in finished_rows(win)}
    win.show_tab("current")
    settle()
    sheet = open_sheet(win)
    sheet.order[0].setFocus()
    QTest.keyClick(sheet.order[0], Qt.Key.Key_A, CTRL)
    assert sheet.picks == {t.work.key for t in sheet.order if sheet.pickable(t.work)}
    assert not fin.picked_rows
    tile_click(sheet.order[0])                                          # a plain click lets them go
    assert not sheet.picks


def test_A4_esc_lets_the_picks_go_in_finished_as_in_current(world):
    _seed, win, _w = world()
    fin = show_finished(win)
    (i, _a), (j, _b) = finished_rows(win)[:2]
    ctrl_click(fin, row_title_point(fin, i))
    ctrl_click(fin, row_title_point(fin, j))
    assert len(fin.picked_rows) == 2
    QTest.keyClick(fin, Qt.Key.Key_Escape)
    settle()
    assert not fin.picked_rows


def test_A4_S19_picking_and_ctrl_a_repaint_only_the_rows_whose_pick_changed(world, monkeypatch):
    """S19: a pick repaints its row; Ctrl+A repaints only the rows on screen whose pick changed, and a second Ctrl+A
    (nothing changed) repaints nothing."""
    _seed, win, _w = world()
    lst = lst_of(win)
    asked = []
    monkeypatch.setattr(lst, "update", lambda index: asked.append(index.row()))
    soon = current_rows(win, "soon")
    lst.pick_row(lst.model().entries[soon[0]][1])
    assert asked == [soon[0]]
    del asked[:]
    before = set(lst.picked_rows)
    lst.pick_all()
    changed = {i for i, e in enumerate(lst.model().entries)
               if getattr(e[1], "key", None) in before ^ lst.picked_rows}
    assert asked and soon[0] not in asked and set(asked) <= changed
    del asked[:]
    lst.pick_all()
    assert asked == []


# --- the picks' ⋯ -------------------------------------------------------------------------------------------------- #
def test_A4_the_picks_menu_leaves_out_their_own_list_in_soon_goal_and_finished(world):
    _seed, win, _w = world()
    lst = lst_of(win)
    now = current_rows(win, "now")
    for i in now[:2]:
        lst.pick_row(lst.model().entries[i][1])
    m = picks_menu_of(win, lst, now[0])
    assert menu_texts(m)[0] == strings.ITEM_MENU["group"][0]              # two shows picked: *Group…* first
    assert menu_texts(m)[1:] == [strings.PICKS_MENU[n][0] for n in ("top", "soon", "goal", "finished", "remove")]
    assert m.accessibleName() == strings.PICKS_MENU_NAME.format(n=2)
    assert all(a.toolTip() for a in m.actions() if not a.isSeparator())
    m.close()
    lst.clear_picks()
    soon = current_rows(win, "soon")
    for i in soon[:2]:
        lst.pick_row(lst.model().entries[i][1])
    m = picks_menu_of(win, lst, soon[0])
    assert strings.PICKS_MENU["soon"][0] not in menu_texts(m) and strings.PICKS_MENU["top"][0] in menu_texts(m)
    m.close()
    fin = show_finished(win)
    for _i, r in finished_rows(win)[:2]:
        fin.pick_row(r)
    m = picks_menu_of(win, fin, finished_rows(win)[0][0])
    assert menu_texts(m) == [strings.PICKS_MENU[n][0] for n in ("top", "soon", "goal", "remove")]
    m.close()
    win.show_tab("current")
    settle()
    sheet = open_sheet(win)
    sheet.pick_all()
    m = sheet.menu(sheet.order[0])
    assert menu_texts(m) == [strings.PICKS_MENU[n][0] for n in ("top", "soon", "finished", "remove")]
    m.close()
    tile = sheet.order[-1]
    sheet.pick_tile(tile)                                                    # one let go: still 2+, still the picks' menu
    sheet.clear_picks()
    sheet.pick_tile(sheet.order[0])
    m = sheet.menu(sheet.order[0])                                      # one pick alone: the tile's own ⋯
    assert strings.GOAL_MENU_ITEMS["top"][0] in menu_texts(m)
    m.close()


def test_A4_a_right_click_on_a_picked_row_opens_the_picks_menu_and_on_another_row_its_own(world):
    from PyQt6.QtGui import QContextMenuEvent
    _seed, win, _w = world()
    lst = lst_of(win)
    now = current_rows(win, "now")
    for i in now[:2]:
        lst.pick_row(lst.model().entries[i][1])
    at = title_point(lst, now[0])
    from PyQt6.QtWidgets import QApplication
    QApplication.sendEvent(lst.viewport(), QContextMenuEvent(QContextMenuEvent.Reason.Mouse, at,
                                                             lst.viewport().mapToGlobal(at)))
    settle()
    assert win.items.last_menu.accessibleName() == strings.PICKS_MENU_NAME.format(n=2)
    win.items.last_menu.close()


@pytest.mark.parametrize("language", ("ja", "zh"))
@pytest.mark.parametrize("name", ("top", "soon", "goal", "finished"))
def test_A4_each_entry_on_currents_picks_is_one_command_one_toast_naming_the_count(world, language, name):
    """*Up next* `place(…, "top")`; *Soon* a `move` after the Soon line; *Goal* a `move` to Goal's end; *Finished*
    `set_tier` with D14's Keep / Leave out — each ONE command with every picked row's files in the list's order, one
    toast naming the count; the rows move (or go) at once, and the picks go."""
    _seed, win, writer = world(language)
    lst = lst_of(win)
    now = current_rows(win, "now")[:3]
    picked = [lst.model().entries[i][1] for i in now]
    for r in picked:
        lst.pick_row(r)
    ids = [i for r in picked for i in drag.ids_of(r)]
    pick_entry(picks_menu_of(win, lst, now[0]), name)
    title = strings.PICKS_TITLES.format(n=3)
    if name == "top":
        assert writer.calls == [("place", ids, {"where": "top"})]
        assert [r.key for r in rows_of(win)[:3]] == [r.key for r in picked]          # shown at the top at once
        assert win.toasts.card.base == strings.PICKS_DONE["top"].format(title=title)
    elif name == "soon":
        (op, got, kw), = writer.calls
        assert (op, got, kw["tier"]) == ("move", ids, "soon")
        assert kw["after_id"] not in ids
        assert all(r.tier == "soon" for r in rows_of(win) if r.key in {p.key for p in picked})
        assert win.toasts.card.base == strings.PICKS_DONE["soon"].format(title=title)
    elif name == "goal":
        (op, got, kw), = writer.calls
        assert (op, got, kw["tier"], kw["end"]) == ("move", ids, "goal", True)
        assert not {p.key for p in picked} & {r.key for r in rows_of(win)}             # gone from Current at once
        assert win.toasts.card.base == strings.PICKS_DONE["goal"].format(title=title)
    else:
        assert writer.calls == [("set_tier", ids, {"tier": "graduated"})]
        card = win.toasts.card
        assert card.base == strings.PICKS_FINISHED.format(title=title)
        assert [b.text() for b in card.buttons if not b.isHidden()] == [strings.TOAST_UNDO, strings.DRAG_KEEP,
                                                                        strings.DRAG_TAKE_OUT]
    assert not lst.picked_rows


def test_A4_one_undo_takes_the_whole_block_back(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    now = current_rows(win, "now")[:4]
    for i in now:
        lst.pick_row(lst.model().entries[i][1])
    pick_entry(picks_menu_of(win, lst, now[0]), "goal")
    assert wait_until(lambda: not win.moves.tickets or win.moves.tickets[-1].change is not None, 5)
    win.toasts.card.buttons[0].click()                                  # its Undo
    settle()
    assert [c[0] for c in writer.calls] == ["move", "undo"] and len(writer.undone) == 1


def test_A4_remove_on_the_picks_asks_first_naming_the_files_and_no_writes_nothing(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    now = current_rows(win, "now")[:2]
    picked = [lst.model().entries[i][1] for i in now]
    for r in picked:
        lst.pick_row(r)
    ids = [i for r in picked for i in drag.ids_of(r)]
    pick_entry(picks_menu_of(win, lst, now[0]), "remove")
    card = win.items.question
    assert isinstance(card, confirm.Confirm) and card.isVisible()
    assert card.yes.text() == strings.PICKS_REMOVE_YES.format(n=len(ids))
    card.no.click()
    settle()
    assert writer.calls == [] and lst.picked_rows == {r.key for r in picked}
    pick_entry(picks_menu_of(win, lst, now[0]), "remove")
    win.items.question.yes.click()
    settle()
    assert writer.calls == [("remove", ids, {})]
    assert win.toasts.card.base == strings.PICKS_REMOVED.format(title=strings.PICKS_TITLES.format(n=2))
    assert not lst.picked_rows


def test_A4_finisheds_picks_up_next_is_put_back_and_soon_goal_are_one_move(world):
    _seed, win, writer = world()
    fin = show_finished(win)
    picked = [r for _i, r in finished_rows(win)[:3]]
    ids = [i for r in picked for i in drag.ids_of(r)]
    for name, want in (("top", ("put_back", ids, {})), ("goal", None), ("soon", None)):
        writer.calls.clear()
        for r in picked:
            fin.pick_row(r)
        pick_entry(picks_menu_of(win, fin, finished_rows(win)[0][0]), name)
        if want is not None:
            assert writer.calls == [want]
        else:
            (op, got, kw), = writer.calls
            assert (op, got, kw["tier"]) == ("move", ids, name)
        assert not fin.picked_rows


def test_A4_goals_picks_bring_up_each_titles_first_part_and_finish_all_of_each(world):
    """Goal's *Up next* / *Soon* bring each picked title's first part (as its single ⋯ does: the rest stays in Goal);
    *Finished* takes all of each — one command each."""
    _seed, win, writer = world()
    sheet = open_sheet(win)
    works = [t.work for t in sheet.order]
    sheet.pick_all()
    m = sheet.menu(sheet.order[0])
    pick_entry(m, "top")
    first = [i for w in works for i in w.pieces[0].item_ids]
    assert writer.calls == [("place", first, {"where": "top"})]
    assert sheet.isVisible() and not sheet.picks
    writer.calls.clear()
    sheet.pick_all()
    pick_entry(sheet.menu(sheet.order[0]), "finished")
    assert writer.calls == [("set_tier", [i for w in works for i in w.item_ids], {"tier": "graduated"})]


@pytest.mark.parametrize("where", ("current", "finished", "goal"))
def test_A4_E4_a_read_only_store_greys_the_picks_entries_with_its_reason_and_writes_nothing(world, where):
    _seed, win, writer = world(writable=False)
    if where == "goal":
        sheet = open_sheet(win)
        sheet.pick_all()
        m = sheet.menu(sheet.order[0])
        owner = sheet
    else:
        lst = lst_of(win) if where == "current" else show_finished(win)
        found = current_rows(win, "now")[:2] if where == "current" else [i for i, _r in finished_rows(win)[:2]]
        for i in found:
            lst.pick_row(lst.model().entries[i][1])
        m = picks_menu_of(win, lst, found[0])
        owner = win.items if where == "current" else win.finished
    acts = [a for a in m.actions() if not a.isSeparator() and a.text() in
            {v[0] for v in strings.PICKS_MENU.values()}]
    assert acts and not any(a.isEnabled() for a in acts)
    assert all(a.toolTip().startswith(strings.MENU_REFUSED_TIP.format(reason="")[:20]) for a in acts)
    m.close()
    for name in strings.PICKS_MENU:
        owner.send_picks(name)
    settle()
    assert writer.calls == []


# --- a drag carries every pick ------------------------------------------------------------------------------------- #
def test_A4_a_drag_from_a_picked_row_carries_every_pick_into_goal_in_one_move(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    now = current_rows(win, "now")[:5]
    picked = [lst.model().entries[i][1] for i in now]
    for r in picked:
        lst.pick_row(r)
    at = title_point(lst, now[2])
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    d = win.moves.running
    assert d is not None and d.many == 5 and d.title == strings.PICKS_TITLES.format(n=5)
    assert not lst.picked_rows                                          # the drag has them now
    target = well_point(win, "goal")
    move_global(win, target)
    release_global(win, target)
    settle()
    ids = [i for r in picked for i in drag.ids_of(r)]
    (op, got, kw), = writer.calls
    assert (op, got, kw["tier"], kw["end"]) == ("move", ids, "goal", True)
    assert not {p.key for p in picked} & {r.key for r in rows_of(win)}


def test_A4_a_drag_of_the_picks_dropped_in_a_gap_is_one_move_beside_a_row_that_isnt_picked(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    now = current_rows(win, "now")
    picked = [lst.model().entries[i][1] for i in now[1:3]]
    for r in picked:
        lst.pick_row(r)
    at = title_point(lst, now[1])
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is not None and win.moves.running.many == 2
    target = lst.viewport().mapToGlobal(title_point(lst, now[5]))
    move_global(win, target)
    release_global(win, target)
    settle()
    ids = [i for r in picked for i in drag.ids_of(r)]
    (op, got, kw), = writer.calls
    assert op == "move" and got == ids
    assert kw["before_id"] not in ids and kw["after_id"] not in ids


def test_A4_a_drag_of_an_unpicked_row_lets_the_picks_go_and_moves_that_row_alone(world):
    _seed, win, writer = world()
    lst = lst_of(win)
    now = current_rows(win, "now")
    for i in now[:2]:
        lst.pick_row(lst.model().entries[i][1])
    at = title_point(lst, now[3])
    press(lst, at)
    assert not lst.picked_rows                                          # a press on another row: let go at once
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is not None and win.moves.running.many == 0
    win.moves.cancel()


def test_A4_goals_picked_tiles_drag_as_one_card(world):
    _seed, win, _w = world()
    sheet = open_sheet(win)
    sheet.pick_all()
    n = len(sheet.picks)
    tile = sheet.order[0]
    assert sheet.drag(tile, tile.mapToGlobal(QPoint(10, 10)))
    d = win.moves.running
    assert d is not None and d.many == n and d.source == "goal"
    assert d.ids == [i for t in sheet.order for i in t.work.pieces[0].item_ids]
    win.moves.cancel()


# --- the store's own answer ---------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language,name", (("ja", "goal"), ("zh", "goal"), ("ja", "top"), ("ja", "soon"),
                                           ("zh", "finished"), ("ja", "remove")))
def test_real_store_A4_picks_land_together_in_the_store_and_one_undo_puts_every_one_back(real, language, name):
    """The store's own answer: every picked row's files where the entry says (Up next: the top of Current in the list's
    order; Soon; Goal; Finished; Remove: gone from the library), from ONE command — and its one Undo puts every file
    back in its tier."""
    store, win, _writer = real(language)
    lst = lst_of(win)
    rs = rows_of(win)
    picked = [r for r in rs[2:] if lst.pickable(r) and not drag.split_first(rs, r)][-3:]
    ids = [i for r in picked for i in drag.ids_of(r)]
    before = {i: store.item(i)["tier"] for i in ids}
    for r in picked:
        assert lst.pick_row(r)
    if name == "remove":
        win.items.send_picks("remove")
        win.items.question.yes.click()
    else:
        win.items.send_picks(name)
    want = {"top": "now", "soon": "soon", "goal": "goal", "finished": "graduated"}.get(name)
    if want is None:
        assert wait_until(lambda: all(store.item(i) is None or store.item(i).get("tier") is None for i in ids), 10)
    else:
        assert wait_until(lambda: all(store.item(i)["tier"] == want for i in ids), 10)
    if name == "top":
        assert wait_until(lambda: [r.key for r in rows_of(win)[:3]] == [r.key for r in picked], 10)
    assert wait_until(lambda: win.moves.toasted is not None and win.moves.toasted.change is not None, 10)
    assert len([t for t in (win.moves.toasted,) if t.ids == tuple(ids)]) == 1      # one command for them all
    win.toasts.card.buttons[0].click()                                  # one Undo
    assert wait_until(lambda: all(store.item(i) is not None and store.item(i)["tier"] == before[i] for i in ids), 10)


def test_A4_picks_holding_a_splits_first_part_offer_no_finished_and_its_drag_leaves_the_well_dark(world):
    """A split's first part never finishes alone (A2): with one among the picks, their ⋯ leaves *Finished* out (as the
    single ⋯ does) and their drag keeps the Finished well dark, its tip saying why — a drop there writes nothing."""
    _seed, win, writer = world()
    lst = lst_of(win)
    shown = rows_of(win)
    first = next(i for i, e in enumerate(lst.model().entries) if i and e[0] == rows.ROW and
                 drag.split_first(shown, e[1]))
    other = current_rows(win, "now")[0]
    for i in (first, other):
        lst.pick_row(lst.model().entries[i][1])
    m = picks_menu_of(win, lst, first)
    assert strings.PICKS_MENU["finished"][0] not in menu_texts(m)
    m.close()
    at = title_point(lst, other)
    press(lst, at)
    move(lst, at + QPoint(0, theme.MOTION["drag-start-px"]))
    assert win.moves.running is not None and win.moves.running.many == 2
    assert win.dock.unlit_tip("finished") == strings.WELL_UNLIT_SPLIT
    target = well_point(win, "finished")
    move_global(win, target)
    release_global(win, target)
    settle()
    assert writer.calls == []


def test_A4_picks_live_in_one_list_the_trays_and_currents_let_each_other_go(world):
    """New arrivals' tray picks as the lists do (its own Ctrl / Shift+click, Ctrl+A): picking in Current lets the
    tray's picks go, and picking in the tray lets Current's go — never two blocks picked at once."""
    from tests.qt.test_arrivals import open_tray, tray_of
    _seed, win, _w = world()
    tray = open_tray(win)
    keys = tray.keys()[:2]
    for k in keys:
        tray.pick(k)
    assert tray.picks == set(keys)
    lst = lst_of(win)
    lst.pick_row(lst.model().entries[current_rows(win, "now")[0]][1])
    assert not tray_of(win).picks
    tray.pick(keys[0])
    assert tray.picks == {keys[0]} and not lst.picked_rows


def test_A4_S19_a_tiles_pick_repaints_that_tile_alone(world, monkeypatch):
    _seed, win, _w = world()
    sheet = open_sheet(win)
    painted = []
    for t in sheet.order:
        monkeypatch.setattr(t, "update", lambda t=t: painted.append(t.work.key))
    sheet.pick_tile(sheet.order[1])
    assert painted == [sheet.order[1].work.key]
    del painted[:]
    sheet.pick_all()
    assert sorted(painted) == sorted(t.work.key for t in sheet.order if t is not sheet.order[1] and
                                     sheet.pickable(t.work))
    del painted[:]
    sheet.pick_all()                                                    # nothing changed: nothing repainted
    assert painted == []
