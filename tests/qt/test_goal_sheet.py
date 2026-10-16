"""Goal's sheet (W3.2 Q2, `app/qt/goal_sheet.py`; the RUNBOOK §1 *Goal's sheet*; A2 #35–36, #117, G1, G2; n9, n11;
IK-11) and its tiles in the reader's view (`view_rows.goal_tiles`), on the window's seed (Japanese titles: a show in
Goal in two parts — Ep 1–12, then Ep 13–24 — a light novel and a book) through the stand-in store, and where the store's
own answers matter (a move landing, Remove and its Undo) on a real migrated store with the real writer.

What a wrong answer would cost a learner:
  * Goal's bar that opens nothing, or a sheet that stays over the list when they click elsewhere (n9), or that closes
    while they pick from its own ⋯ menu or answer its Remove question (G1);
  * *Move to the top* bringing up all 24 episodes of a show they meant to start, or none, or leaving them hunting the
    list for where it went (G2: the first piece only, the rest stays in Goal, the list scrolls to it);
  * a Goal title finished with no choice about its cards (IK-11), a Remove that can't be undone or that never said how
    many files it takes;
  * a sheet that re-animates or rebuilds its tiles on every view (N9, S19), or moves under Reduced motion.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import freeze, goal_sheet, motion, strings, windows
from app.services import view_rows as vr
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, mouse, move_global, open_window, release_global, row_point, rows_of
from tests.qt.test_wiring import problems

LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton


class Writer(FakeWriter):
    """The recording writer, with the trash's command the sheet gives (`moves.Writer.remove`)."""

    def remove(self, ids, label=None):
        return self._put("remove", ids, label)


@pytest.fixture
def world(qapp):
    made = []

    def make(language="ja", size=(1280, 900)):
        seed = window_seed.build(language=language)
        writer = Writer(seed.library)
        win, services = open_window(qapp, seed, writer, size)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def bar_point(win):
    return win.dock.bar_rect().center().toPoint()


def open_sheet(win):
    QTest.mouseClick(win.dock, LEFT, pos=bar_point(win))
    sheet = win.goal_sheet
    assert wait_until(sheet.isVisible, 2)
    return sheet


def calls(writer, op=None):
    return [c for c in writer.calls if op is None or c[0] == op]


def tile_of(sheet, title):
    return next(t for t in sheet.order if t.work.title == title)


def goal_view(win):
    return win.page_widgets["current"].view_model.goal


def two_part(win):
    """The seed's Goal show in two parts (Ep 1–12, Ep 13–24)."""
    return next(w for w in goal_view(win).works if len(w.pieces) == 2)


def settle(ms=40):
    QTest.qWait(ms)
    QApplication.processEvents()


# --- the tiles in the reader's view (pure) ------------------------------------------------------------------------ #
def _goal_items(seed):
    items = {r["id"]: r for r in seed.items}
    return items, {w["id"]: w for w in seed.works}


def test_goals_tiles_are_one_per_title_in_goals_order_and_a_title_in_two_parts_keeps_both_parts_in_order():
    """A title split in Goal is one tile (the mock: tiles grouped by work), its count over all its files, its pieces
    in Goal's order — the first is what *Move to the top* brings up."""
    seed = window_seed.build()
    items, works = _goal_items(seed)
    goal = vr.build(items, works, {}).goal
    titles = [w.title for w in goal.works]
    assert len(titles) == 3 == goal.titles
    show = goal.works[0]
    assert [p.line for p in show.pieces] == ["Ep 1–12", "Ep 13–24"]
    assert show.line == "24 episodes" and show.n_files == 24 and len(show.item_ids) == 24
    assert [w.line for w in goal.works[1:]] == ["4 parts", "6 parts"]
    goal_ids = [r["id"] for r in sorted((r for r in seed.items if r["tier"] == "goal"), key=lambda r: r["ord"])]
    assert show.pieces[0].item_ids == tuple(goal_ids[:12])           # Goal's first twelve: the show's first part
    assert show.folder.startswith("GoalContent/") and show.source == "disk"


def test_chinese_goal_tiles_read_the_same_way():
    seed = window_seed.build(language="zh")
    items, works = _goal_items(seed)
    goal = vr.build(items, works, {}, language="zh").goal
    assert [len(w.pieces) for w in goal.works] == [2, 1, 1]
    assert all(any("一" <= ch <= "鿿" for ch in w.title) for w in goal.works)


def test_an_empty_goal_has_no_tiles():
    seed = window_seed.build()
    items, works = _goal_items(seed)
    items = {k: v for k, v in items.items() if v["tier"] != "goal"}
    goal = vr.build(items, works, {}).goal
    assert goal.works == () and goal.line == "Goal is empty"


def test_an_unchanged_goal_gives_back_the_same_tiles_and_a_renamed_title_only_its_own():
    """S19: the reader's cache hands back the same Goal (nothing repaints); a title renamed rebuilds its own tile and
    hands back the others as the same objects — equal to a build with no cache."""
    seed = window_seed.build()
    items, works = _goal_items(seed)
    tiers = vr._by_tier(items)
    cache = vr.RowCache()

    def view(changed_works=()):
        return vr.build(items, works, {}, numbers=(1, {}), cards={1: 0}, cache=cache, tiers=tiers, changed=[],
                        changed_works=list(changed_works))
    view()
    first = view()
    assert view().goal is first.goal
    renamed = first.goal.works[1]
    works[renamed.work_id] = dict(works[renamed.work_id], title="微睡みの魔導書と最後の弟子 新装版")
    again = view(changed_works=[renamed.work_id])
    assert again.goal is not first.goal
    assert again.goal.works[1].title == "微睡みの魔導書と最後の弟子 新装版"
    assert again.goal.works[0] is first.goal.works[0] and again.goal.works[2] is first.goal.works[2]
    assert again.goal == vr.build(items, works, {}, numbers=(1, {}), cards={1: 0}, tiers=tiers).goal


def test_the_first_screens_cache_keeps_the_strip_but_never_the_tiles():
    seed = window_seed.build()
    items, works = _goal_items(seed)
    view = vr.build(items, works, {})
    cached = vr.from_cache(vr.to_cache(view))
    assert cached.goal.works == () and len(vr.to_cache(view)["goal"]) == 5
    strip = (cached.goal.titles, cached.goal.files, tuple(cached.goal.covers), cached.goal.line)
    assert strip == (view.goal.titles, view.goal.files, view.goal.covers, view.goal.line)


def test_menu_entries_leave_finished_out_for_hatos_mix_and_disable_the_moves_on_a_store_that_cant_be_saved():
    """Current's ⋯ rules (W3.1a): hato's mix never finishes; E4: the moves greyed with the reason, the folder kept."""
    piece = vr.GoalPiece((1, 2), "Ep 1–2")
    work = vr.GoalWork("w1", 1, "星降る街の小さな工房", "星降る街の小さな工房", "anime", "hato", 2, "2 episodes",
                       (piece,), (1, 2), "HighPriority/Hato/星降る街の小さな工房", "", "")
    names = [e[0] for e in goal_sheet.menu_entries(work, True)]
    assert names == ["top", "soon", "folder", "remove"]
    shut = goal_sheet.menu_entries(work._replace(source="disk"), False, "why")
    assert [(n, ok) for n, _l, _t, ok in shut] == [("top", False), ("soon", False), ("finished", False),
                                                    ("folder", True), ("remove", False)]
    assert all(t == "why" for n, _l, t, ok in shut if not ok)


# --- opening and closing ------------------------------------------------------------------------------------------ #
def test_a_click_on_goals_bar_opens_the_sheet_over_the_bottom_62_percent_of_the_column_with_its_tiles(world):
    seed, win, writer = world()
    sheet = win.goal_sheet
    assert not sheet.isVisible() and sheet.order == []                  # nothing made before the hand asks
    open_sheet(win)
    lst = win.page_widgets["current"].list
    g = sheet.geometry()
    assert g.bottom() + 1 == win.dock.geometry().top()
    assert abs(g.height() - 0.62 * (win.dock.geometry().top() - lst.geometry().top())) <= 1
    assert g.left() == lst.geometry().left() and g.width() == lst.geometry().width()
    assert [t.work.title for t in sheet.order] == [w.title for w in goal_view(win).works]
    assert all(t.isVisible() and t.toolTip() for t in sheet.order)
    assert sheet.opens == 1 and calls(writer) == []


def test_the_bar_clicked_again_closes_it_and_a_press_dragged_off_the_bar_opens_nothing(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    QTest.mouseClick(win.dock, LEFT, pos=bar_point(win))
    assert not sheet.isVisible()
    at = bar_point(win)
    mouse(win.dock, QEvent.Type.MouseButtonPress, at)
    mouse(win.dock, QEvent.Type.MouseButtonRelease, at + QPoint(30, 0), LEFT, NONE)
    assert not sheet.isVisible()


def test_G1_a_click_outside_closes_it_but_the_sheet_its_menu_and_the_remove_question_dont(world, monkeypatch):
    seed, win, writer = world()
    sheet = open_sheet(win)
    QTest.mouseClick(sheet, LEFT, pos=QPoint(sheet.width() - 80, sheet.height() - 10))      # the sheet itself
    assert sheet.isVisible()
    opened = []
    monkeypatch.setattr(windows, "open_url", lambda path: opened.append(path) or True)
    tile = sheet.order[0]
    menu = sheet.menu(tile)
    assert wait_until(menu.isVisible, 2)
    act = next(a for a in menu.actions() if a.text() == strings.GOAL_MENU_ITEMS["folder"][0])
    QTest.mouseClick(menu, LEFT, pos=menu.actionGeometry(act).center())                      # its ⋯ menu
    assert opened and sheet.isVisible()
    card = sheet.ask_remove(tile.work)
    QTest.mouseClick(card.scrim, LEFT, pos=QPoint(5, 5))                                       # the question's room: No
    assert card.answer is False and sheet.isVisible() and calls(writer, "remove") == []
    QTest.mouseClick(win.header, LEFT, pos=QPoint(win.header.width() // 2, 10))               # elsewhere: closed
    assert not sheet.isVisible()


@pytest.mark.parametrize("how", ["esc", "back", "close", "tab"])
def test_esc_back_its_close_button_and_leaving_current_close_it(world, how):
    seed, win, writer = world()
    sheet = open_sheet(win)
    if how == "esc":
        QTest.keyClick(sheet, Qt.Key.Key_Escape)
    elif how == "back":
        QTest.mouseClick(sheet, Qt.MouseButton.BackButton, pos=QPoint(20, 20))
    elif how == "close":
        sheet.close_button.click()
    else:
        win.show_tab("finished")
        win.show_tab("current")                                       # back on Current: it stays closed
    assert not sheet.isVisible()
    assert win.isVisible()                                            # the main window is never closed


def test_every_control_on_the_sheet_and_its_menu_is_wired_tipped_and_named(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    sheet.menu(sheet.order[0]).close()
    found, n = problems(win)
    assert found == [] and n > 0
    for t in sheet.order:
        assert t.more.toolTip().startswith(t.more.accessibleName())


def test_tab_goes_round_the_tiles_and_close_and_enter_opens_a_tiles_menu(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    seen = []
    for _ in range(len(sheet.order) + 1):
        sheet.focusNextPrevChild(True)
        seen.append(QApplication.focusWidget())
    assert seen == list(sheet.order) + [sheet.close_button]
    sheet.focusNextPrevChild(True)
    assert QApplication.focusWidget() is sheet.order[0]                # round, never out of the sheet
    QTest.keyClick(sheet.order[0], Qt.Key.Key_Return)
    assert sheet.last_menu is not None and wait_until(sheet.last_menu.isVisible, 2)
    assert [a.text() for a in sheet.last_menu.actions() if a.text()] == \
        [strings.GOAL_MENU_ITEMS[k][0] for k in ("top", "soon", "finished", "folder", "remove")]
    sheet.last_menu.close()


# --- G2: the first piece up, the rest stays ----------------------------------------------------------------------- #
@pytest.mark.parametrize("where", ["top", "soon"])
def test_G2_move_up_closes_the_sheet_moves_the_first_piece_keeps_the_rest_in_goal_and_scrolls_to_it(world, where):
    seed, win, writer = world()
    sheet = open_sheet(win)
    show = two_part(win)
    hero = rows_of(win)[0]
    sheet.pick(show, where)
    assert not sheet.isVisible()
    op = calls(writer, "move")[0]
    assert op[1] == list(show.pieces[0].item_ids)                     # Ep 1–12 only
    if where == "top":
        assert op[2]["tier"] == hero.tier and op[2]["before_id"] == hero.episodes[0].id
        assert win.toasts.card.message == strings.GOAL_UP.format(title=show.title, first="Ep 1–12", n=1)
    else:
        assert op[2]["tier"] == "soon" and op[2]["before_id"] is None and op[2]["after_id"] is None
        assert "→ Soon" in win.toasts.card.message and "the rest stays in Goal" in win.toasts.card.message
    first = show.pieces[0].item_ids[0]
    assert wait_until(lambda: sheet.washed is not None, 5)
    row = next(r for r in rows_of(win) if any(e.id == first for e in r.episodes))
    assert sheet.washed == row.key and row.tier == ("now" if where == "top" else "soon")
    if where == "top":
        assert rows_of(win)[0].key == row.key
    lst = win.page_widgets["current"].list
    at = next(i for i, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == row.key)
    assert lst.viewport().rect().intersects(lst.visualRect(lst.model().index(at, 0)))     # scrolled into view
    rest = next(w for w in goal_view(win).works if w.key == show.key)
    assert [p.line for p in rest.pieces] == ["Ep 13–24"]              # the rest stays in Goal


def test_a_one_part_title_moves_whole_and_its_toast_says_so(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    novel = goal_view(win).works[1]
    sheet.pick(novel, "top")
    assert calls(writer, "move")[0][1] == list(novel.item_ids)
    assert win.toasts.card.message == strings.GOAL_UP_ALL.format(title=novel.title, n=1)


def test_IK11_move_to_finished_takes_the_whole_title_and_offers_the_cards_choice(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    show = two_part(win)
    sheet.pick(show, "finished")
    op = calls(writer, "set_tier")[0]
    assert op[1] == list(show.item_ids) and op[2]["tier"] == "graduated"
    settle()
    labels = [b.text() for b in win.toasts.card.buttons if b.isVisible()]
    assert strings.DRAG_KEEP in labels and strings.DRAG_TAKE_OUT in labels
    next(b for b in win.toasts.card.buttons if b.text() == strings.DRAG_TAKE_OUT).click()
    assert wait_until(lambda: calls(writer, "finish"), 5)
    assert calls(writer, "finish")[0][2]["keep_cards"] is False


def test_open_its_folder_opens_the_titles_folder_in_the_data_folder(world, monkeypatch):
    seed, win, writer = world()
    sheet = open_sheet(win)
    opened = []
    monkeypatch.setattr(windows, "open_url", lambda path: opened.append(path) or True)
    show = two_part(win)
    sheet.pick(show, "folder")
    assert opened and opened[0].endswith(os.path.join("GoalContent", show.title))
    monkeypatch.setattr(windows, "open_url", lambda path: False)
    sheet.pick(show, "folder")
    assert win.bar_line.full() == strings.GOAL_FOLDER_FAILED.format(title=show.title)
    assert calls(writer) == []


def test_remove_asks_naming_the_count_then_trashes_every_file_and_its_toast_undoes_it(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    book = goal_view(win).works[2]
    card = sheet.ask_remove(book)
    assert card.yes.text() == strings.GOAL_REMOVE_YES.format(n=6) and "6 files" in card.body.text()
    assert card.default is card.no                                     # removing: Cancel is the default
    card.yes.click()
    op = calls(writer, "remove")[0]
    assert op[1] == list(book.item_ids)
    assert win.toasts.card.message == strings.GOAL_REMOVED.format(title=book.title, n=6)
    assert wait_until(lambda: writer.saved, 5)
    settle()
    win.toasts.card.buttons[0].click()                                 # Undo
    assert wait_until(lambda: calls(writer, "undo"), 5)
    assert calls(writer, "undo")[0][2]["change"].op == "remove"


def test_a_store_that_cant_be_saved_refuses_every_move_and_says_why(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    writer.writable = False
    show = two_part(win)
    menu = sheet.menu(sheet.order[0])
    assert [a.isEnabled() for a in menu.actions() if a.text()] == [False, False, False, True, False]
    menu.close()
    for name in ("top", "soon", "finished", "remove"):
        sheet.pick(show, name)
    assert calls(writer) == [] and win.bar_line.full().startswith(strings.DRAG_REFUSED.split("{")[0])


# --- A2 #35–36, #117: a tile dragged into Current ----------------------------------------------------------------- #
def test_a_tile_dragged_up_lifts_its_first_piece_closes_the_sheet_and_lands_where_dropped(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    show = two_part(win)
    tile = tile_of(sheet, show.title)
    at = QPoint(30, 30)
    mouse(tile, QEvent.Type.MouseButtonPress, at)
    mouse(tile, QEvent.Type.MouseMove, at + QPoint(0, theme.MOTION["drag-start-px"]), NONE, LEFT)
    assert not sheet.isVisible()
    assert win.moves.running is not None and win.moves.running.ids == list(show.pieces[0].item_ids)
    assert win.dock.wells == ("soon", "finished")                     # from Goal: no Goal well
    rs = rows_of(win)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    op = calls(writer, "move")[0]
    assert op[1] == list(show.pieces[0].item_ids) and op[2]["after_id"] == rs[1].episodes[-1].id


def test_a_press_that_travels_less_than_6_px_lifts_nothing(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    tile = sheet.order[0]
    mouse(tile, QEvent.Type.MouseButtonPress, QPoint(30, 30))
    mouse(tile, QEvent.Type.MouseMove, QPoint(32, 32), NONE, LEFT)
    mouse(tile, QEvent.Type.MouseButtonRelease, QPoint(32, 32), LEFT, NONE)
    assert sheet.isVisible() and win.moves.running is None and calls(writer) == []


# --- N9 / S19 and the motion ------------------------------------------------------------------------------------ #
def test_N9_a_view_with_goal_unchanged_changes_no_tile_and_never_reanimates_the_sheet(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    goal = sheet.goal
    builds, sets = sheet.builds, [t.sets for t in sheet.order]
    hero = rows_of(win)[0]
    page = win.page_widgets["current"]
    before = page.view_model
    seed.library.commit(items=[{"id": hero.episodes[-1].id, "watched": 1}])           # an outside change in Current
    assert wait_until(lambda: page.view_model is not before, 5)
    settle()
    assert sheet.goal is goal and sheet.builds == builds and [t.sets for t in sheet.order] == sets
    assert sheet.opens == 1 and not sheet.rising() and sheet.isVisible()
    assert sheet.set_goal(page.view_model.goal) is False


def test_a_goal_change_while_open_updates_its_tiles_in_place_without_rising_again(world):
    seed, win, writer = world()
    sheet = open_sheet(win)
    keep = sheet.order[0]
    book = goal_view(win).works[2]
    seed.library.commit(items=[{"id": i, "tier": "graduated", "graduated_at": "2026-10-15T10:00:00Z"}
                               for i in book.item_ids], order=True)
    assert wait_until(lambda: len(sheet.order) == 2, 5)
    assert sheet.order[0] is keep and sheet.opens == 1 and sheet.offset == 0


def test_reduced_motion_puts_the_sheet_in_place_at_once(world):
    seed, win, writer = world()
    freeze.set_frozen(False)
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("reduced")
    try:
        sheet = open_sheet(win)
        assert sheet.offset == 0 and not sheet.rising() and sheet.geometry() == sheet.rest_rect()
    finally:
        mode.set_setting(was)


def test_with_motion_it_rises_on_its_spring_from_below_and_never_past_its_place(world):
    seed, win, writer = world()
    freeze.set_frozen(False)
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("full")
    clock = motion.clock()
    clock.use_test_time()
    try:
        sheet = win.goal_sheet
        sheet.open()
        assert sheet.isVisible() and sheet.offset == theme.MOTION["buckets-rise"]
        seen = []
        for _ in range(40):
            clock.advance(16)
            seen.append(sheet.offset)
        assert seen[0] < theme.MOTION["buckets-rise"] and min(seen) >= 0 and seen[-1] == 0
        assert sheet.geometry() == sheet.rest_rect()
        sheet.set_goal(goal_view(win)._replace(line="3 titles · 34 files"))            # a refresh: never again
        assert not sheet.rising() and sheet.opens == 1
    finally:
        clock.use_real_time()
        mode.set_setting(was)


# ================================================================================================================== #
# The real store: the writer and the reader on one opener
# ================================================================================================================== #
from tests.qt.test_drag import real  # noqa: E402,F401,F811  (the fixture)


def _open_real(win):
    assert wait_until(lambda: goal_view(win) is not None and goal_view(win).works, 10)
    return open_sheet(win)


def test_real_store_move_to_the_top_lands_its_first_piece_at_the_top_and_leaves_the_rest_in_goal(real):
    store, win, writer = real()
    sheet = _open_real(win)
    tile = goal_view(win).works[0]
    others = [i for w in goal_view(win).works[1:] for i in w.item_ids]
    sheet.pick(tile, "top")
    ids = list(tile.pieces[0].item_ids)
    assert wait_until(lambda: writer.pending() == 0 and all(store.item(i)["tier"] == "now" for i in ids), 10)
    assert store.ids("now")[:len(ids)] == ids
    assert all(store.item(i)["tier"] == "goal" for i in others)
    assert wait_until(lambda: sheet.washed is not None, 5)


def test_real_store_remove_sends_the_files_to_the_trash_and_undo_brings_them_back(real):
    store, win, writer = real()
    sheet = _open_real(win)
    tile = goal_view(win).works[-1]
    ids = list(tile.item_ids)
    paths = [os.path.join(store.data_dir, *store.item(i)["rel_path"].split("/")) for i in ids]
    assert all(os.path.exists(p) for p in paths)
    sheet.ask_remove(tile).yes.click()
    assert wait_until(lambda: writer.pending() == 0 and not any(os.path.exists(p) for p in paths), 10)
    assert not [i for i in store.ids("goal") if i in ids]
    assert wait_until(lambda: writer.can_undo() and not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()                                  # Undo
    assert wait_until(lambda: all(os.path.exists(p) for p in paths), 10)
    rels = {store_rel(store, p) for p in paths}
    assert wait_until(lambda: len([i for i in store.ids("goal") if store.item(i)["rel_path"] in rels]) == len(ids), 10)


def store_rel(store, path):
    return os.path.relpath(path, store.data_dir).replace(os.sep, "/")
