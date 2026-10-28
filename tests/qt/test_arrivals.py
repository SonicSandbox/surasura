"""New arrivals in the window (W3.2 Q1, `app/qt/arrivals.py`; A2 #22–32, #89–97, #100, #118; IK-5, IK-10, IK-11): the
header's inset, the tray under it, its actions through the writer, a drag from it, and the arrivals' numbers — on the
window's seed (Japanese and Chinese titles; its arrivals: a hato show in two evenings, a YouTube channel's video, a
hato show already watched) through the stand-in store, and on a real migrated store for the writes.

What a wrong answer would cost a learner:
  * an arrival placed somewhere other than where its icon, its ⋯ or the hand said, or finished without D14's choice
    (its new cards taken out, or kept, without being asked — IK-11);
  * *Remove…* sending a show to the trash without asking, or with no Undo;
  * a tray that closes after each placement (A2 #27), or that can't be closed by Esc / Back / a click away;
  * an inset that says something arrived when nothing did (A2 #32), or counts shows instead of files (R4b-12);
  * the new-words number asked again and again of the worker (every view), shown stale after Generate (IK-10), or an
    error shown where a dash belongs;
  * the inset and the tray repainted on every refresh (S19), or moving when nothing arrived.
"""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import settings_manager, theme
from app.qt import arrivals, freeze, motion, shell, strings
from app.services import library_reader, view_rows
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import (FakeWriter, LEFT, NONE, calls, mouse, move_global, release_global, row_point, settle,
                                well_point)
from tests.qt.test_wiring import problems


# --- the writer and the worker the window talks to ------------------------------------------------------------------ #
class ArrivalsWriter(FakeWriter):
    """test_drag's recording writer, with S2's commands the tray gives (written into the stand-in library as the store
    would: a place moves the items, Finished dates them, Remove takes them out)."""

    def place(self, ids, where, label=None):
        return self._put("place", ids, label, where=where)

    def remove(self, ids, label=None):
        return self._put("remove", ids, label)

    def add_to_group(self, piece_id, piece_ids=(), item_ids=(), label=None):
        return self._put("add_to_group", [], label, piece_id=piece_id, piece_ids=list(piece_ids),
                         item_ids=list(item_ids))

    def _write(self, change):
        lib = self.library
        if change.op == "place":
            where = change.kw["where"]
            if where == "finished":
                lib.commit(items=[{"id": i, "tier": "graduated", "graduated_at": "2026-10-15T10:00:00Z"}
                                  for i in change.ids], order=True)
            else:
                tier = {"top": "now", "after-show": "now", "soon": "soon", "goal": "goal"}[where]
                lib.commit(items=[{"id": i, "tier": tier, "ord": -1000.0 + k} for k, i in enumerate(change.ids)],
                           order=True)
        elif change.op == "remove":
            lib.commit(gone=[("item", i) for i in change.ids], order=True)
        else:
            super()._write(change)


class FakeWorker:
    """The warm worker's client (`ArrivalsWorker.estimate`): each request recorded and answered on a thread of its own,
    as the real one answers, from `table` ({file name: (n_new_top, n_new_after_show)}) or with `error`."""

    def __init__(self, plan="sig-1", error=None, table=None, n=12):
        self.plan, self.error, self.table, self.n = plan, error, table or {}, n
        self.asked = []
        self.lock = threading.Lock()

    def estimate(self, path, placed=(), callback=None, piece=None):
        placed = list(piece[:placed]) if isinstance(placed, int) else list(placed)   # A4: the index form
        with self.lock:
            self.asked.append((path, placed))
            rid = len(self.asked)
        if self.error:
            answer = {"id": rid, "op": "estimate", "error": self.error}
        else:
            top, after = self.table.get(os.path.basename(path), (self.n, self.n // 3 if placed else None))
            answer = {"id": rid, "op": "estimate", "path": path, "n_new_top": top, "n_new_after_show": after,
                      "plan": self.plan, "exact": True}
        threading.Thread(target=callback, args=(answer,), daemon=True).start()
        return rid


def open_window(qapp, seed, writer, worker=None, size=(1280, 900), coalesce=False):
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02, coalesce=coalesce)
    settings_manager.save_keys({"target_language": seed.language})    # the window's language is its library's (P0)
    services = shell.Services(library=reader, writer=writer)
    services.arrivals = worker
    win = shell.open_window(qapp, services)
    win.resize(*size)
    win.move(40, 30)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading
                      and win.arrivals_tray.groups, 10)
    for _ in range(30):
        QApplication.processEvents()
    return win, services


@pytest.fixture
def world(qapp):
    made = []

    def make(language="ja", worker=None, size=(1280, 900), coalesce=False):
        seed = window_seed.build(language=language)
        writer = ArrivalsWriter(seed.library)
        win, services = open_window(qapp, seed, writer, worker, size, coalesce)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def tray_of(win):
    return win.arrivals_tray


def open_tray(win):
    win.arrivals_inset.click()
    assert wait_until(lambda: tray_of(win).isVisible(), 3)
    return tray_of(win)


class TrayRowAt:
    """A row of the tray's list as the tests press it (A4: the rows are painted by a list, not widgets of their own):
    its key, the arrival it shows, its parts' places on the list's viewport, its repaints asked, its tips."""

    def __init__(self, tray, key):
        self.tray, self.key = tray, key
        self.arrival = tray.model.objs[tray.view.row_of(key)]         # what it showed when it was taken

    @property
    def paints(self):
        return self.tray.model.paints.get(self.key, 0)

    @property
    def icon_kind(self):
        return arrivals.icon_of(self.arrival)

    def rect(self, part="row"):
        return self.tray.part_rect(self.key, part)

    def point(self, part="row"):
        return QPointF(self.rect(part).center())

    def tip(self, part):
        return self.tray.tip(self.key, part)

    def click(self, part="icon", modifiers=Qt.KeyboardModifier.NoModifier):
        vp = self.tray.view.viewport()
        at = self.point(part)
        mouse(vp, QEvent.Type.MouseButtonPress, at, LEFT, LEFT, modifiers)
        mouse(vp, QEvent.Type.MouseButtonRelease, at, LEFT, NONE, modifiers)


def tray_rows(win):
    """The tray's rows as laid out, top to bottom."""
    tray = tray_of(win)
    return [TrayRowAt(tray, k) for k in tray.keys()]


def tray_arrivals(win):
    """The arrivals the tray holds (shown, or waiting for it to open: a closed tray does no row work)."""
    return [a for g in tray_of(win).groups for a in g.rows]


def arrival_titles(seed):
    """The seed's arrivals by kind: the hato show, the YouTube channel's video, the watched hato show."""
    works = {w["id"]: w for w in seed.works}
    items = [r for r in seed.items if r["tier"] == "arrivals"]
    out = {}
    for r in items:
        w = works[r["work_id"]]
        kind = "youtube" if w.get("media_type") == "youtube" else ("watched" if w.get("anilist_id") == 303 else "hato")
        out.setdefault(kind, (w["title"], []))[1].append(r["id"])
    return out


def esc(widget):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


# --- the inset ---------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A2_22_the_inset_counts_files_and_shows_the_three_newest_covers_in_the_header_before_the_level(world,
                                                                                                      language):
    # R4b-12: the count is files (episodes) — 6 + 1 + 3 — never shows; the covers newest first by `added_at`
    seed, win, _w = world(language)
    inset = win.arrivals_inset
    by = arrival_titles(seed)
    assert inset.isVisible() and inset.count == 10
    assert inset.titles == (by["youtube"][0], by["hato"][0], by["watched"][0])
    assert inset.accessibleName() == strings.ARRIVALS_NAME.format(n=10)
    assert inset.toolTip().startswith("New arrivals")
    lay = win.header.layout()
    assert lay.indexOf(inset) == lay.indexOf(win.add_stone) - 1       # after the stretch: the level ▾, + Add and ? follow it


def test_A2_32_with_nothing_arrived_the_inset_is_absent_and_placing_the_last_closes_the_tray(world):
    seed, win, writer = world()
    tray = open_tray(win)
    ids = [r["id"] for r in seed.items if r["tier"] == "arrivals"]
    seed.library.commit(items=[{"id": i, "tier": "goal", "ord": 99000.0 + k} for k, i in enumerate(ids)], order=True)
    assert wait_until(lambda: not win.arrivals_inset.isVisible(), 5)
    assert not tray.isVisible() and tray_rows(win) == []


# --- the tray ----------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A2_23_the_tray_holds_new_then_already_watched_each_newest_first(world, language):
    seed, win, _w = world(language)
    open_tray(win)
    by = arrival_titles(seed)
    rs = [r.arrival for r in tray_rows(win)]
    assert rs[0].chip == "YouTube" and rs[0].channel == by["youtube"][0]     # the video, titled by itself (#97)
    assert [a.title for a in rs[1:]] == [by["hato"][0], by["watched"][0]]
    kinds = [g.kind for g in tray_of(win).groups]
    assert kinds == ["new", "watched"]
    head, label, button = tray_of(win).heads["watched"]
    assert label.text() == view_rows.STRINGS["arr_watched"].upper()
    assert button is not None and button.text() == strings.TRAY_ALL_FINISHED
    assert tray_of(win).heads["new"][2] is None                       # only *Already watched* offers it


def test_A2_89_from_another_tab_the_inset_opens_current_with_the_tray(world):
    seed, win, _w = world()
    win.show_tab("finished")
    open_tray(win)
    assert win.current_tab() == "current"
    tray = tray_of(win)
    inset = win.arrivals_inset
    assert tray.geometry().top() > inset.mapTo(win.centralWidget(), QPoint(0, inset.height())).y() - 1
    assert tray.width() == min(round(theme.size("tray", "M")), win.centralWidget().width() - 16)


def test_A2_95_118_each_row_has_one_icon_square_named_first_and_every_control_is_wired_and_tipped(world):
    seed, win, _w = world()
    open_tray(win)
    rs = tray_rows(win)
    sizes = {(r.rect("icon").width(), r.rect("icon").height()) for r in rs}
    assert len(sizes) == 1                                            # one size on every row
    assert [r.icon_kind for r in rs] == ["top", "top", "finished"]
    for r in rs:                                                      # always there (n10: no hover-to-reveal)
        assert r.rect("icon").width() > 0 and r.rect("more").width() > 0
        name = strings.TRAY_ICON[r.icon_kind][0]
        assert r.tip("icon").startswith(name + " · ")
        assert r.tip("more").startswith(strings.TRAY_MORE_NAME)
    assert rs[0].tip("icon").startswith("Top · Add to the top of Current")
    tray_of(win).menu(rs[1].key)                                      # the ⋯ menu's actions join the walk
    found, _n = problems(win)
    assert found == []
    tray_of(win).last_menu.close()


def test_A2_90_to_94_96_97_the_rows_line_number_and_text_column(world):
    seed, win, _w = world()
    open_tray(win)
    rs = tray_rows(win)
    yt, hato, watched = (r.arrival for r in rs)
    assert yt.line == yt.channel and yt.chip == "YouTube"             # #97: the channel below its title
    assert hato.line == "Ep 1–6" and hato.chip == "hato"               # #94: the line gives only the range
    assert hato.parts[0] == ("Ep 1–6", "dim")
    assert [t for t, tone in watched.parts if tone == "warn"]         # #26: no video, in amber
    xs = {r.rect("number").x() for r in rs}
    assert len(xs) == 1                                               # #92: one column whatever the row
    fz = theme.text_factor("M")
    tray = tray_of(win)
    for r in rs:
        assert r.rect("number").width() == round(56 * fz)
        parts = arrivals.row_parts(tray.view.visualRect(tray.model.index(tray.view.row_of(r.key), 0)))
        assert parts["text_right"] <= r.rect("number").x() - round(28 * fz)   # #96: the title stops 28 px short
        assert "≈" not in r.tip("number") and "~" not in r.tip("number")      # #90
        assert "estimate until analysed" in r.tip("number")
    assert arrivals.number_text(rs[1].arrival)[0] == strings.TRAY_NUMBER_NONE  # a dash until it's counted
    assert "6 episodes" in rs[1].tip("number")


def test_A2_93_the_estimates_fill_the_number_per_episode_and_only_their_rows_repaint(world):
    seed, win, _w = world()
    open_tray(win)
    rs = tray_rows(win)
    by = arrival_titles(seed)
    hato_ids = by["hato"][1]
    paints = {r.arrival.key: r.paints for r in rs}
    est = {i: n for i, n in zip(hato_ids, (30, 5, 5, 5, 5, 5))}       # 55 for six files → 9 / ep, rounded
    win.services.library.set_estimates(est)
    assert wait_until(lambda: tray_rows(win)[1].arrival.per_ep is not None, 5)
    row = tray_rows(win)[1]
    assert arrivals.number_text(row.arrival) == ("9", "new / ep")
    assert row.tip("number").startswith("About 9 new words an episode")
    assert row.paints == paints[row.arrival.key] + 1
    others = [r for r in tray_rows(win) if r.key != row.key]
    assert all(r.paints == paints[r.arrival.key] for r in others)     # S19: only the row whose number came


# --- the actions -------------------------------------------------------------------------------------------------- #
def test_A2_27_the_top_icon_places_the_arrival_through_the_writer_and_the_tray_stays_open(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[1]
    ids = list(row.arrival.item_ids)
    title = row.arrival.title
    row.click("icon")
    assert calls(writer, "place") == [("place", ids, {"where": "top"})]
    assert win.toasts.card.base == strings.TRAY_PLACED["top"].format(title=title)
    assert wait_until(lambda: len(tray_rows(win)) == 2, 5)
    settle()
    assert tray_of(win).isVisible()                                   # open for the next one
    assert win.arrivals_inset.count == 4


@pytest.mark.parametrize("name", ["top", "after-show", "soon", "goal"])
def test_each_menu_place_calls_the_writer_with_its_place(world, name, monkeypatch):
    monkeypatch.setattr(arrivals.ArrivalsTray, "_has_show", lambda _self, _a: True)    # (its show in Current)
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[0]
    menu = tray_of(win).menu(row.key)
    act = next(a for a in menu.actions() if a.text() == strings.TRAY_MENU[name][0])
    assert act.toolTip() and act.isEnabled()
    act.trigger()
    assert calls(writer, "place") == [("place", list(row.arrival.item_ids), {"where": name})]
    menu.close()


def test_the_menu_lists_its_entries_in_order_and_disables_the_moves_on_a_read_only_store(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[0]
    menu = tray_of(win).menu(row.key)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    # --- W3.2 L3: *Change cover…* (a submenu) after the moves, before *Open its folder*
    want = [strings.TRAY_MENU[n][0] for n in arrivals.MENU]
    assert labels == want[:5] + [strings.ITEM_MENU["cover"][0]] + want[5:]
    menu.close()
    writer.writable = False
    menu = tray_of(win).menu(row.key)
    enabled = {a.text(): a.isEnabled() for a in menu.actions() if not a.isSeparator()}
    assert enabled[strings.TRAY_MENU["folder"][0]] and not enabled[strings.TRAY_MENU["top"][0]]
    menu.close()
    row.click("icon")                                                 # E4: refused at the press, said in the bar
    assert calls(writer, "place") == []


def test_IK_11_finished_on_a_watched_arrival_offers_D14s_choice_and_take_out_follows_it(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[2]
    ids = list(row.arrival.item_ids)
    title = row.arrival.title
    assert row.icon_kind == "finished"
    row.click("icon")
    assert calls(writer, "place") == [("place", ids, {"where": "finished"})]
    card = win.toasts.card
    assert card.base == strings.DRAG_FINISHED.format(title=title)
    labels = [b.text() for b in card.buttons if b.isVisible()]
    assert strings.DRAG_KEEP in labels and strings.DRAG_TAKE_OUT in labels
    settle()
    take = next(b for b in card.buttons if b.text() == strings.DRAG_TAKE_OUT)
    take.click()
    assert wait_until(lambda: calls(writer, "finish"), 5)
    op, got, kw = calls(writer, "finish")[0]
    assert got == ids and kw["keep_cards"] is False and kw["follows"] is not None


def test_IK_11_the_menus_finished_offers_the_same_choice(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[0]
    menu = tray_of(win).menu(row.key)
    next(a for a in menu.actions() if a.text() == strings.TRAY_MENU["finished"][0]).trigger()
    assert calls(writer, "place")[0][2] == {"where": "finished"}
    assert strings.DRAG_TAKE_OUT in [b.text() for b in win.toasts.card.buttons if b.isVisible()]


def test_A2_100_all_to_finished_records_every_watched_arrival_in_one_command_with_the_choice(world):
    seed, win, writer = world()
    open_tray(win)
    by = arrival_titles(seed)
    tray_of(win).heads["watched"][2].click()
    assert calls(writer, "place") == [("place", by["watched"][1], {"where": "finished"})]
    assert calls(writer, "set_watched") == []                        # nothing else written (nothing mined)
    assert strings.DRAG_KEEP in [b.text() for b in win.toasts.card.buttons if b.isVisible()]


def test_A2_101_mine_them_too_stays_hidden_until_P41_sets_its_callable(world):
    seed, win, writer = world()
    open_tray(win)
    tray = tray_of(win)
    head = tray.heads["watched"][0]
    assert not head.mine.isHidden()                                   # P4.1 4.1.11: the window's routing sets it
    tray.mine_too = None
    tray.set_groups(tuple(list(tray.groups)))
    assert head.mine.isHidden()                                       # unset: hidden
    got = []
    tray.mine_too = got.append
    tray.set_groups(tuple(list(tray.groups)))                         # the next view
    assert not head.mine.isHidden()
    head.mine.click()
    assert got == [arrival_titles(seed)["watched"][1]] and calls(writer) == []


def test_open_its_folder_opens_the_arrivals_own_folder(world, monkeypatch):
    from app import path_utils
    from app.qt import screens
    opened = []
    monkeypatch.setattr(screens, "open_with_system", opened.append)    # (a folder: the system's opener, on a worker)
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[1]
    rel = row.arrival.rel_paths[0]
    want = os.path.dirname(os.path.join(path_utils.get_data_path("ja"), *rel.split("/")))
    tray_of(win).act(row.arrival, "folder")                           # N4: gone: looked for on a worker, then said
    assert wait_until(lambda: win.bar_line.full() == strings.TRAY_NO_FOLDER.format(path=want), 5)
    assert opened == []
    os.makedirs(want, exist_ok=True)
    menu = tray_of(win).menu(row.key)
    next(a for a in menu.actions() if a.text() == strings.TRAY_MENU["folder"][0]).trigger()
    assert wait_until(lambda: opened == [want], 5) and calls(writer) == []


def test_N1_after_its_show_is_greyed_while_none_of_its_show_is_in_current_and_N4_the_menu_goes_once_hidden(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[0]                                           # a YouTube video: no part of it in Current
    menu = tray_of(win).menu(row.key)
    act = next(a for a in menu.actions() if a.text() == strings.TRAY_MENU["after-show"][0])
    assert not act.isEnabled() and act.toolTip() == strings.TRAY_NO_SHOW
    assert menu.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    menu.close()
    assert wait_until(lambda: sip.isdeleted(menu), 3)


def test_remove_asks_first_naming_the_count_esc_is_no_and_yes_removes_with_undo(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[1]
    ids = list(row.arrival.item_ids)
    arrival = row.arrival
    tray = tray_of(win)
    tray.act(arrival, "remove")
    q = tray.question
    assert q is not None and q.yes.text() == strings.TRAY_REMOVE_YES.format(n=6)
    assert q.default is q.no                                          # Enter at first is Cancel
    esc(q)
    assert wait_until(lambda: sip.isdeleted(q) or not q.isVisible(), 3)
    assert calls(writer, "remove") == []
    tray.open() if not tray.isVisible() else None
    tray.act(arrival, "remove")
    tray.question.yes.click()
    assert calls(writer, "remove") == [("remove", ids, {})]
    card = win.toasts.card
    assert card.base == strings.TRAY_REMOVED.format(title=arrival.title)
    undo = next(b for b in card.buttons if b.text() == strings.TOAST_UNDO)
    assert wait_until(lambda: writer.saved, 3)
    settle()
    undo.click()
    assert wait_until(lambda: calls(writer, "undo"), 3)


def test_enter_on_a_focused_row_is_its_icon_and_tab_walks_the_rows(world):
    seed, win, writer = world()
    open_tray(win)
    rs = tray_rows(win)
    view = tray_of(win).view
    assert view.focusPolicy() & Qt.FocusPolicy.TabFocus
    view.setFocus(Qt.FocusReason.TabFocusReason)                      # Tab into the list: its first row
    QApplication.processEvents()
    assert view.currentIndex().row() == view.row_of(rs[0].key)
    QTest.keyClick(view, Qt.Key.Key_Tab)                              # Tab: the next row (a head is passed by)
    assert view.currentIndex().row() == view.row_of(rs[1].key)
    QTest.keyClick(view, Qt.Key.Key_Backtab)
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert calls(writer, "place") == [("place", list(rs[0].arrival.item_ids), {"where": "top"})]


# --- closing ------------------------------------------------------------------------------------------------------ #
def test_esc_back_the_close_button_and_a_click_outside_close_the_tray_a_click_inside_does_not(world):
    seed, win, _w = world()
    tray = open_tray(win)
    esc(tray)
    assert not tray.isVisible()
    tray = open_tray(win)
    QApplication.sendEvent(tray, QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5),
                                             QPointF(tray.mapToGlobal(QPoint(5, 5))), Qt.MouseButton.BackButton,
                                             Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier))
    assert not tray.isVisible()
    tray = open_tray(win)
    tray.close_button.click()
    assert not tray.isVisible()
    tray = open_tray(win)
    tray_rows(win)[0].click("row")
    assert tray.isVisible()                                           # inside: stays
    lst = win.page_widgets["current"].list
    mouse(lst.viewport(), QEvent.Type.MouseButtonPress, QPointF(20, 20))
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, QPointF(20, 20), LEFT, NONE)
    assert not tray.isVisible()                                       # a click away
    tray = open_tray(win)
    win.arrivals_inset.click()                                        # the inset again
    assert not tray.isVisible()


# --- the drag ----------------------------------------------------------------------------------------------------- #
def lift_row(win, k, modifiers=Qt.KeyboardModifier.NoModifier):
    row = tray_rows(win)[k]
    vp = tray_of(win).view.viewport()
    at = row.point("row")
    mouse(vp, QEvent.Type.MouseButtonPress, at, LEFT, LEFT, modifiers)
    mouse(vp, QEvent.Type.MouseMove, at + QPointF(0, theme.MOTION["drag-start-px"]), NONE, LEFT)
    assert win.moves.running is not None
    return row


def test_A2_24_a_drag_from_the_tray_lands_where_the_gap_was_and_the_tray_fades_then_comes_back(world):
    seed, win, writer = world()
    tray = open_tray(win)
    ids = list(tray_rows(win)[1].arrival.item_ids)
    lift_row(win, 1)
    assert win.moves.running.source == "arrivals" and win.moves.running.ids == ids
    assert not tray.isVisible() and tray.fade is not None              # faded (frozen motion: at once)
    rows_ = win.page_widgets["current"].view_model.rows
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    got = calls(writer, "move")
    assert got and got[0][1] == ids
    assert got[0][2]["tier"] == rows_[1].tier and got[0][2]["after_id"] == rows_[1].episodes[-1].id
    assert wait_until(lambda: tray.isVisible(), 3)                     # back, still open (A2 #27)


def test_A2_28_an_arrival_dragged_onto_the_finished_well_is_recorded_finished(world):
    seed, win, writer = world()
    open_tray(win)
    ids = list(tray_rows(win)[1].arrival.item_ids)
    lift_row(win, 1)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    assert calls(writer, "set_tier") == [("set_tier", ids, {"tier": "graduated"})]
    assert strings.DRAG_TAKE_OUT in [b.text() for b in win.toasts.card.buttons if b.isVisible()]


# --- LM11b G2 (IK-3): a tray file rested on a group joins it ------------------------------------------------------ #
def _current_group(win, i, other_work=987654):
    """Current's row `i` shown as a group of its show and another (G1's `group` / `works`)."""
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    rs[i] = rs[i]._replace(group=True, works=(rs[i].work_id, other_work))
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()
    return win.page_widgets["current"].view_model.rows[i]


def _middle(win, i):
    lst = win.page_widgets["current"].list
    return lst.viewport().mapToGlobal(lst.visualRect(lst.model().index(i, 0)).center())


def _rest():
    from app.qt import item_menu
    QTest.qWait(item_menu.JOIN_REST_MS + 150)


def test_G2_IK3_a_tray_file_rested_on_a_group_joins_it_with_one_add_to_group_toasted_with_undo(world):
    seed, win, writer = world()
    rows_ = win.page_widgets["current"].view_model.rows
    i = next(k for k, r in enumerate(rows_) if k > 1 and r.piece_id is not None and r.source != "hato")
    group = _current_group(win, i)
    open_tray(win)
    arrival = tray_rows(win)[1].arrival
    ids = list(arrival.item_ids)
    lift_row(win, 1)
    to = _middle(win, i)
    move_global(win, to)
    settle()
    assert win.moves.running.target[0] == "list"                      # passing: a place in the list, as before
    _rest()
    assert win.moves.running.target == ("join", group.key)
    assert win.page_widgets["current"].list.join_label == strings.JOIN_GROUP_LABEL
    release_global(win, to)
    assert calls(writer) == [("add_to_group", [], {"piece_id": group.piece_id, "piece_ids": [], "item_ids": ids})]
    text = strings.ITEM_GROUPED_WITH.format(other=arrival.title, title=group.title)
    assert wait_until(lambda: win.toasts.card.base == text, 5)
    assert win.toasts.card.buttons, "its Undo"


def test_G2_IK3_a_tray_file_rested_on_a_run_is_placed_there_as_before(world):
    seed, win, writer = world()
    rows_ = win.page_widgets["current"].view_model.rows
    i = next(k for k, r in enumerate(rows_) if k > 1 and r.piece_id is not None and r.source != "hato")
    open_tray(win)
    ids = list(tray_rows(win)[1].arrival.item_ids)
    lift_row(win, 1)
    to = _middle(win, i)
    move_global(win, to)
    _rest()
    assert win.moves.running.target[0] == "list"
    release_global(win, to)
    assert [c[0] for c in calls(writer)] == ["move"] and calls(writer)[0][1] == ids


def test_G2_IK3_after_its_show_finds_a_show_that_sits_inside_a_group(world, monkeypatch):
    # the group's row names every show in it (Row.works): an arrival of its second show has a show in Current
    seed, win, _w = world()
    tray = open_tray(win)
    view = win.page_widgets["current"].view_model
    a = next(r.arrival for r in tray_rows(win) if r.arrival.work_id is not None)
    others = [r for r in view.rows if r.work_id != a.work_id]
    page = win.page_widgets["current"]
    monkeypatch.setattr(page, "view_model", view._replace(rows=type(view.rows)(others)))
    assert not tray._has_show(a)
    grouped = others[2]._replace(group=True, works=(others[2].work_id, a.work_id))
    rows_ = list(others)
    rows_[2] = grouped
    monkeypatch.setattr(page, "view_model", view._replace(rows=type(view.rows)(rows_)))
    assert tray._has_show(a)


# --- S19 and motion ----------------------------------------------------------------------------------------------- #
def test_S19_a_refresh_with_nothing_new_in_arrivals_repaints_neither_the_inset_nor_the_tray(world):
    seed, win, _w = world()
    open_tray(win)
    inset, tray = win.arrivals_inset, tray_of(win)
    before = (inset.paints, tray.paints, [r.paints for r in tray_rows(win)])
    goal = next(r for r in seed.items if r["tier"] == "goal")
    builds = win.services.library.builds
    seed.library.commit(items=[{"id": goal["id"], "watched": 1}])     # a change elsewhere: a new view
    assert wait_until(lambda: win.services.library.builds > builds, 5)
    settle(100)
    assert (inset.paints, tray.paints, [r.paints for r in tray_rows(win)]) == before


@pytest.fixture
def test_clock(qapp):
    freeze.set_frozen(False)
    c = motion.clock()
    c.mode.set_setting("full")
    c.use_test_time()
    yield c
    c.use_real_time()
    c.mode.set_setting("follow")


def _arrive(seed, title="ぼっち・ざ・ろっく！", added="2026-10-15T23:00:00Z"):
    """A new hato arrival into the stand-in store (one file), as hato's register leaves it."""
    item_id = max(r["id"] for r in seed.library.items()) + 1
    work_id = item_id + 5000
    seed.library.commit(works=[{"id": work_id, "title": title, "media_type": "anime"}],
                        items=[{"id": item_id, "tier": "arrivals", "ord": 1.0, "work_id": work_id,
                                "rel_path": f"HighPriority/Hato/{title}/{title} - 01.srt", "added_at": added,
                                "parent_folder": f"Hato/{title}", "piece_id": None}], order=True)
    return item_id


def test_an_arrival_parts_the_covers_drops_the_new_one_in_and_reduced_motion_jumps_it(world, test_clock):
    seed, win, _w = world()
    test_clock.mode.set_setting("full")        # the window set its own (Follow Windows: GitHub's runner shows none)
    inset = win.arrivals_inset
    played = inset.arrivals_played
    _arrive(seed)
    assert wait_until(lambda: inset.count == 11, 5)
    assert inset.arrivals_played == played + 1 and inset.fresh == 1
    assert inset.titles[0] == "ぼっち・ざ・ろっく！"
    test_clock.advance(16)
    assert 0.0 < inset.arrive < 1.0                                   # moving
    test_clock.advance(800)
    assert inset.arrive == 1.0                                        # at rest
    test_clock.mode.set_setting("reduced")
    _arrive(seed, title="葬送のフリーレン", added="2026-10-16T08:00:00Z")
    assert wait_until(lambda: inset.count == 12, 5)
    assert inset.arrive == 1.0                                        # Reduced motion: jumped
    test_clock.mode.set_setting("full")


def test_the_inset_sinks_pressed_and_lifts_released_on_its_springs(world, test_clock):
    seed, win, _w = world()
    test_clock.mode.set_setting("full")        # the window set its own (Follow Windows: GitHub's runner shows none)
    inset = win.arrivals_inset
    c = QPointF(inset.width() / 2, inset.height() / 2)
    mouse(inset, QEvent.Type.MouseButtonPress, c)
    test_clock.advance(400)
    assert inset.press == pytest.approx(1.0)
    mouse(inset, QEvent.Type.MouseButtonRelease, c, LEFT, NONE)
    test_clock.advance(16)
    assert 0.0 < inset.press < 1.0
    test_clock.advance(600)
    assert inset.press == 0.0


# --- the numbers -------------------------------------------------------------------------------------------------- #
def _sync(fn):
    fn()


def _numbers(worker, tmp_path, plan=lambda: 1, every=0.0):
    got = []
    known = tmp_path / "KnownWord.json"
    known.write_text('{"words": ["猫"]}', encoding="utf-8")
    nums = arrivals.ArrivalNumbers(worker, "ja", on_change=got.append, data_path=str(tmp_path / "data"),
                                   known_file=str(known), plan_token=plan, run=_sync, every=every)
    return nums, got, known


def _all_in(got, view):
    """The numbers last handed on hold every arrival's file."""
    return bool(got) and set(got[-1]) == {i for a in view.arrivals for i in a.item_ids}


def _view(seed):
    items = {r["id"]: r for r in seed.items}
    works = {w["id"]: w for w in seed.works}
    return view_rows.build(items, works, {"arrivals_on": 1}, language=seed.language)


def test_IK_5_each_file_is_asked_once_with_the_pieces_earlier_files_placed_before_it(tmp_path):
    seed = window_seed.build()
    view = _view(seed)
    worker = FakeWorker()
    nums, got, _k = _numbers(worker, tmp_path)
    nums.want(view.arrivals)
    assert wait_until(lambda: _all_in(got, view), 3)
    assert len(worker.asked) == 10                                    # every file once
    nums.want(view.arrivals)
    nums.want(view.arrivals)
    assert len(worker.asked) == 10                                    # never again for a view it has seen
    hato = next(a for a in view.arrivals if a.chip == "hato" and a.group == "new")
    asked = {os.path.basename(p): placed for p, placed in worker.asked}
    names = [r.split("/")[-1] for r in hato.rel_paths]
    for k, name in enumerate(names):
        assert [os.path.basename(x) for x in asked[name]] == names[:k]  # its earlier files placed before it
    est = nums.estimates()
    assert est[hato.item_ids[0]] == 12 and est[hato.item_ids[1]] == 4  # the first at the top, the rest after them


class HeldWorker(FakeWorker):
    """Answers only when told (`release`): an answer still out when the window switched language."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.held = []

    def estimate(self, path, placed=(), callback=None, piece=None):
        placed = list(piece[:placed]) if isinstance(placed, int) else list(placed)
        with self.lock:
            self.asked.append((path, placed))
            rid = len(self.asked)
        self.held.append(lambda: callback({"id": rid, "op": "estimate", "path": path, "n_new_top": self.n,
                                           "n_new_after_show": None, "plan": self.plan, "exact": True}))
        return rid

    def release(self):
        held, self.held = self.held, []
        for answer in held:
            answer()


def test_W32_H_an_answer_asked_before_a_language_switch_never_reaches_the_new_librarys_numbers(tmp_path):
    # The window's numbers now go to the reader open as they come (a switch let the first reader go). A ja file's
    # answer landing after the switch to zh would hand ja item ids to the zh library, where an id can name another file.
    seed = window_seed.build()
    view = _view(seed)
    worker = HeldWorker()
    language = ["ja"]
    got = []
    known = tmp_path / "KnownWord.json"
    known.write_text('{"words": ["猫"]}', encoding="utf-8")
    nums = arrivals.ArrivalNumbers(worker, lambda: language[0], on_change=got.append, data_path=str(tmp_path / "d"),
                                   known_file=str(known), plan_token=lambda: 1, run=_sync, every=0.0)
    nums.want(view.arrivals)
    assert len(worker.asked) == 10 and got == []
    language[0] = "zh"                                                # the switch, the answers still out
    worker.release()
    assert got == [] and nums.estimates() == {}
    language[0] = "ja"                                                # (and the same answers, asked in ja, land)
    nums.want(view.arrivals, force=True)
    worker.release()
    assert got and set(got[-1]) == {i for a in view.arrivals for i in a.item_ids}


def test_IK_10_answers_are_kept_by_item_plan_and_known_words_and_a_change_asks_again(tmp_path):
    seed = window_seed.build()
    view = _view(seed)
    worker = FakeWorker(plan="sig-1")
    plan = [1]
    nums, got, known = _numbers(worker, tmp_path, plan=lambda: plan[0])
    nums.want(view.arrivals)
    assert wait_until(lambda: _all_in(got, view), 3)
    known_sig = nums._token[1]
    first = view.arrivals[0].item_ids[0]
    assert (first, "sig-1", known_sig) in nums.kept
    nums.recheck()                                                    # nothing moved: nothing asked
    assert len(worker.asked) == 10
    plan[0] = 2                                                       # a Generate: a new plan
    worker.plan = "sig-2"
    nums.recheck()
    assert wait_until(lambda: len(worker.asked) == 20 and nums.answers == 20, 3)
    assert (first, "sig-2", known_sig) in nums.kept
    assert set(nums.estimates()) == {i for a in view.arrivals for i in a.item_ids}
    time.sleep(0.02)
    known.write_text('{"words": ["猫", "犬", "鳥"]}', encoding="utf-8")   # the known words moved
    nums.recheck()
    assert wait_until(lambda: len(worker.asked) == 30, 3)
    assert nums._token[1] != known_sig


def test_a_failed_estimate_shows_nothing_and_isnt_asked_again(tmp_path):
    seed = window_seed.build()
    view = _view(seed)
    worker = FakeWorker(error="the arrivals worker was stopped")
    nums, got, _k = _numbers(worker, tmp_path)
    nums.want(view.arrivals)
    time.sleep(0.2)
    assert got == [] and nums.estimates() == {}
    nums.want(view.arrivals)
    assert len(worker.asked) == 10
    assert arrivals.answer_number({"n_new_top": None, "reason": "no-plan"}, False) is None
    assert arrivals.answer_number({"n_new_top": True}, False) is None


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_window_asks_each_new_files_estimate_once_and_shows_it_within_300_ms(world, language):
    # fix round (IK-2): with the window's own reader (`coalesce`, as `shell.library_for` makes it) — the number used to
    # wait out the burst rule behind the arrival's own view (~500 ms), and the reader without it never showed that
    worker = FakeWorker(n=8)
    seed, win, _w = world(language=language, worker=worker, coalesce=True)
    assert wait_until(lambda: all(a.per_ep is not None for a in tray_arrivals(win)), 5)
    assert len(worker.asked) == 10
    t0 = time.perf_counter()
    item_id = _arrive(seed, "山河令" if language == "zh" else "ぼっち・ざ・ろっく！")
    shown = lambda: any(item_id in a.item_ids and a.per_ep == 8 for a in tray_arrivals(win))  # noqa: E731
    assert wait_until(shown, 5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"an arrival -> its number in the tray: {ms:.0f} ms")
    assert ms <= 300                                                  # functional (a shared machine)
    settle(100)
    assert len(worker.asked) == 11                                    # only the new file


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_file_arriving_at_rest_shows_its_number_with_its_next_paint_not_a_bursts_wait_later(world, language):
    """IK-2: with the window's reader, a lone file arriving while nothing else is going on built its view at once, but
    its *N new* (handed on a moment later) waited out the burst rule behind that view: a quarter second of a dash for
    every file hato drops. No burst under way, the number shows at once."""
    worker = FakeWorker(n=6)
    seed, win, _w = world(language=language, worker=worker, coalesce=True)
    assert wait_until(lambda: all(a.per_ep is not None for a in tray_arrivals(win)), 5)
    settle(int((arrivals.HAND_EVERY + library_reader.COALESCE_S) * 1000) + 50)     # the window at rest
    t0 = time.perf_counter()
    item_id = _arrive(seed, "长安十二时辰" if language == "zh" else "葬送のフリーレン")
    assert wait_until(lambda: any(item_id in a.item_ids for a in tray_arrivals(win)), 5)
    assert wait_until(lambda: any(item_id in a.item_ids and a.per_ep == 6 for a in tray_arrivals(win)), 5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"an arrival at rest -> its number in the tray: {ms:.0f} ms")
    assert ms < library_reader.COALESCE_S * 1000 / 2, ms             # one look and a paint, never the burst's wait


def test_S2_the_same_answers_again_hand_nothing_on_so_the_reader_builds_nothing(tmp_path):
    seed = window_seed.build()
    view = _view(seed)
    worker = FakeWorker()
    nums, got, _k = _numbers(worker, tmp_path)
    nums.want(view.arrivals)
    assert wait_until(lambda: _all_in(got, view) and nums.answers == 10, 3)
    handed = len(got)
    nums.want(view.arrivals, force=True)                              # every file asked again, every answer the same
    assert wait_until(lambda: len(worker.asked) == 20 and nums.answers == 20, 3)
    time.sleep(0.1)
    nums.flush()
    assert len(got) == handed


def test_S2_a_drag_then_the_tray_opened_asks_no_number_again_and_a_generate_asks_them_all(world, monkeypatch):
    # the token is the plan file's key, never the numbers' version (which moves with every drop)
    key = [(1, 100)]
    monkeypatch.setattr(window_seed._Numbers, "plan_key", lambda self: key[0], raising=False)
    worker = FakeWorker(n=8)
    seed, win, _w = world(worker=worker)
    assert wait_until(lambda: all(a.per_ep is not None for a in tray_arrivals(win)), 5)
    assert len(worker.asked) == 10
    reader = win.services.library
    item = next(iter(seed.numbers.table))
    seed.numbers.set(item, seed.numbers.table[item])                  # a drop: the numbers' version moves
    reader.refresh()
    settle(100)
    open_tray(win)
    settle(200)
    assert len(worker.asked) == 10, "a drag then the tray opened: zero new requests"
    reader.set_estimates(dict(reader._estimates))                     # the same numbers: nothing to build
    assert not reader._estimates_new
    key[0] = (2, 120)                                                 # a Generate: a new plan file
    win.arrival_numbers.recheck()
    assert wait_until(lambda: len(worker.asked) == 20, 3)


def test_IK_L2_2_new_arrivals_and_finisheds_what_if_share_one_warm_worker_for_the_language(world):
    seed, win, _w = world(worker=FakeWorker())
    win.services.arrivals = None                                      # (the world's stub off: the real slot)
    one = win.arrivals_worker()
    try:
        assert one is win.arrivals_worker() and one is win.services.arrivals_worker and one.language == "ja"
        assert win.arrival_numbers.client is one
    finally:
        one.stop()


def test_without_a_library_the_window_has_neither_the_inset_nor_the_tray(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    try:
        assert win.arrivals_tray is None and win.arrivals_inset is None
        win.open_arrivals()                                           # does nothing
        assert problems(win)[0] == []
    finally:
        win.close()
        services.shutdown(0.5)


# --- A4: New arrivals at 20,000 (speed, the stale row, one title in several folders) ---------------------------------- #
SERIES = {"ja": ("ハリー・ポッター", ("1 賢者の石", "2 秘密の部屋", "3 アズカバンの囚人"), "別の物語"),
          "zh": ("哈利·波特", ("1 魔法石", "2 密室", "3 阿兹卡班的囚徒"), "另一个故事")}


def _series_items(language, base, split=False, work=777000):
    """A series in New arrivals, one folder per book (two files each) — `split`: all three one piece, another title's
    file between its runs (as hato's drops leave a show that came in two evenings with something else between)."""
    title, parts, other = SERIES[language]
    items, works = [], [{"id": work, "title": title, "media_type": "book"}]
    k = 0
    for p, part in enumerate(parts):
        for e in (1, 2):
            items.append({"id": base + k, "tier": "arrivals", "ord": -9000.0 + 10 * k, "work_id": work,
                          "rel_path": f"HighPriority/{title}/{part}/第{e:02d}章.txt", "source_type": "text",
                          "added_at": f"2026-10-2{p}T10:00:00Z", "parent_folder": f"{title}/{part}",
                          "piece_id": 880000 if split else 880000 + p})
            k += 1
        if split:
            items.append({"id": base + k, "tier": "arrivals", "ord": -9000.0 + 10 * k, "work_id": work + 1 + p,
                          "rel_path": f"HighPriority/{other}{p}/01.txt", "added_at": f"2026-10-2{p}T09:00:00Z",
                          "parent_folder": f"{other}{p}", "piece_id": None, "source_type": "text"})
            works.append({"id": work + 1 + p, "title": f"{other}{p}", "media_type": "book"})
            k += 1
    return items, works


def _shown_and_viewed(win):
    tray = tray_of(win)
    shown = [(r.key, r.arrival.title, r.arrival.item_ids) for r in tray_rows(win)]
    viewed = [(a.key, a.title, a.item_ids) for g in tray.groups for a in g.rows]
    return shown, viewed


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A4_mattias_7_a_piece_in_two_runs_is_two_rows_and_placing_one_to_goal_leaves_the_tray_as_the_view_says(
        world, language):
    # Mattias #7: "After a move to Goal the next row showed 'Harry Potter' again and again until a restart." A piece
    # whose files another title split in New arrivals gave two rows one key: one row stood for both, and the next row
    # after a placement kept showing the series. Each run is a row of its own; the tray shows exactly the view.
    seed, win, writer = world(language)
    base = max(r["id"] for r in seed.library.items()) + 1
    items, works = _series_items(language, base, split=True)
    seed.library.commit(works=works, items=items, order=True)
    assert wait_until(lambda: sum(len(g.rows) for g in tray_of(win).groups) == 9, 5)
    tray = open_tray(win)
    settle()
    shown, viewed = _shown_and_viewed(win)
    assert shown == viewed and len({k for k, _t, _i in shown}) == len(shown)
    series = SERIES[language][0]
    for _ in range(3):                                                # the series' rows to Goal, one after another
        row = next(r for r in tray_rows(win) if r.arrival.title == series)
        placed = set(row.arrival.item_ids)
        tray.act(row.arrival, "goal")
        assert wait_until(lambda: not any(placed & set(a.item_ids) for g in tray.groups for a in g.rows), 5)
        settle()
        shown, viewed = _shown_and_viewed(win)
        assert shown == viewed                                        # never a row the view no longer holds
        assert not any(placed & set(ids) for _k, _t, ids in shown)
        assert win.arrivals_inset.count == sum(len(ids) for _k, _t, ids in viewed)
    assert not any(t == series for _k, t, _i in shown)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A4_one_piece_split_by_another_title_gives_each_run_its_own_key(language):
    items, works = _series_items(language, 1, split=True)
    view = view_rows.build({r["id"]: dict(r) for r in items}, {w["id"]: w for w in works}, {"arrivals_on": 1},
                           language=language)
    keys = [a.key for a in view.arrivals]
    assert len(keys) == 6 and len(set(keys)) == 6
    series = [a for a in view.arrivals if a.title == SERIES[language][0]]
    assert sorted(i for a in series for i in a.item_ids) == sorted(r["id"] for r in items
                                                                   if r["work_id"] == 777000)


class DetailLooks:
    """K7: the looks as the shell asks for the arrivals' folders (`folders(ids, then, detail=True)`), answered on a
    thread of their own from where each item's ORIGINAL sits under its source folder (`rel`), never its copy's path."""

    def __init__(self, root, rel_of):
        self.root, self.rel_of, self.calls = root, rel_of, []

    def folders(self, ids, then, detail=False):
        self.calls.append((list(ids), detail))
        found = {}
        for i in ids:
            rel = self.rel_of(i)
            found[i] = None if rel is None else (
                {"root": self.root, "folder": os.path.join(self.root, *rel.split("/")), "rel": rel} if detail
                else self.root)
        threading.Thread(target=then, args=(found,), daemon=True).start()
        return True

    def listing(self):
        return True

    def asked(self, **_kw):
        return False

    def close(self):
        pass

    def set_shown(self, _shown):
        pass


def _with_detail_looks(win, items, root):
    """The window's looks replaced by `DetailLooks` over `items` (each original under `root`/<its book's folder>), and
    the reader told to ask them (A4B-8: it asks and names on its own thread)."""
    rel = {it["id"]: it["parent_folder"] for it in items}
    looks = DetailLooks(root, rel.get)
    win.looks = looks
    win._follow_folders(looks)                                         # (asked of these looks afresh)
    return looks


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_K7_one_title_in_several_folders_names_each_rows_folder_from_where_its_original_sits(world, language):
    # Mattias #7 / K7: a box set in several folders showed identical rows. Each row names the folder its ORIGINAL is in
    # under the source (the store's answer) — never the library copy's path (HighPriority/…), which is Surasura's.
    seed, win, _w = world(language)
    title, parts, _other = SERIES[language]
    items, works = _series_items(language, max(r["id"] for r in seed.library.items()) + 1)
    seed.library.commit(works=works, items=items, order=True)
    assert wait_until(lambda: sum(1 for a in tray_arrivals(win) if a.title == title) == 3, 5)
    looks = _with_detail_looks(win, items, os.path.join("D:", os.sep, "本棚"))
    assert wait_until(lambda: all(a.folder for a in tray_arrivals(win) if a.title == title), 5)
    assert all(detail for _ids, detail in looks.calls)                  # the store's place, asked with its detail
    by_folder = {a.folder: a for a in tray_arrivals(win) if a.title == title}
    assert set(by_folder) == {f"{title} › {p}" for p in parts}        # its folder's last two parts
    for folder, a in by_folder.items():
        assert a.parts[0] == (folder, "dim") and folder in a.accessible and a.chip == "本棚"
    alone = [a for a in tray_arrivals(win) if a.title != title]
    assert alone and all(a.folder is None for a in alone)              # a lone title: no folder on its line


@pytest.mark.parametrize("where, words", [
    ({"root": r"D:\本棚", "folder": r"D:\本棚\ハリー・ポッター\2 秘密の部屋", "rel": "ハリー・ポッター/2 秘密の部屋"},
     "ハリー・ポッター › 2 秘密の部屋"),
    ({"root": r"D:\本棚", "folder": r"D:\本棚\全集\哈利·波特\2 密室", "rel": "全集/哈利·波特/2 密室"}, "哈利·波特 › 2 密室"),
    ({"root": r"D:\本棚", "folder": r"D:\本棚", "rel": ""}, "本棚"),       # at the source's top: the source's name
    (None, None),                                                           # no answer (a file from no folder read)
])
def test_K7_the_folder_words_come_from_the_originals_place_under_its_source(where, words):
    assert view_rows.arrival_folder(where) == words


def test_K7_the_view_itself_names_no_folder_the_library_copys_path_is_never_read_as_one():
    items, works = _series_items("ja", 1)
    view = view_rows.build({r["id"]: dict(r) for r in items}, {w["id"]: w for w in works}, {"arrivals_on": 1},
                           language="ja")
    assert all(a.folder is None for a in view.arrivals)


def test_A4_a_view_built_again_keeps_each_folder_named_row_the_same_object(world):
    seed, win, _w = world()
    items, works = _series_items("ja", max(r["id"] for r in seed.library.items()) + 1)
    seed.library.commit(works=works, items=items, order=True)
    assert wait_until(lambda: len(tray_arrivals(win)) > 3, 5)
    _with_detail_looks(win, items, os.path.join("D:", os.sep, "本棚"))
    assert wait_until(lambda: any(a.folder for a in tray_arrivals(win)), 5)
    tray = open_tray(win)
    settle()
    named = {r.key: r.arrival for r in tray_rows(win) if r.arrival.folder}
    paints = {k: tray.model.paints[k] for k in named}
    builds = win.services.library.builds
    goal = next(r for r in seed.items if r["tier"] == "goal")
    seed.library.commit(items=[{"id": goal["id"], "watched": 1}])     # a change elsewhere: a new view
    assert wait_until(lambda: win.services.library.builds > builds, 5)
    settle(100)
    assert all(tray.arrival(k) is a for k, a in named.items())          # S19: the same rows, nothing repainted
    assert {k: tray.model.paints[k] for k in named} == paints


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A4B8_the_reader_names_the_arrivals_on_its_own_thread_asks_each_once_and_same_answers_build_nothing(
        world, language, monkeypatch):
    # A4B-8: the naming was the window's (~15 ms a new view at 20,000 arrivals, every arrival more). Now the reader asks
    # the looks and names the rows as it builds: the window's thread names none; each first file is asked once (a new
    # view elsewhere asks nothing); the same answers handed again build nothing (S19).
    seed, win, _w = world(language)
    title = SERIES[language][0]
    items, works = _series_items(language, max(r["id"] for r in seed.library.items()) + 1)
    seed.library.commit(works=works, items=items, order=True)
    assert wait_until(lambda: sum(1 for a in tray_arrivals(win) if a.title == title) == 3, 5)
    on_window = []
    real_name = view_rows._name_arrivals
    monkeypatch.setattr(view_rows, "_name_arrivals", lambda *a: on_window.append(
        threading.current_thread() is threading.main_thread()) or real_name(*a))
    looks = _with_detail_looks(win, items, os.path.join("D:", os.sep, "本棚"))
    assert wait_until(lambda: all(a.folder for a in tray_arrivals(win) if a.title == title), 5)
    assert on_window and not any(on_window)                             # every naming on the reader's thread
    asked = [i for ids, _d in looks.calls for i in ids]
    assert len(asked) == len(set(asked)) == len(tray_arrivals(win))     # each first file asked once
    reader = win.services.library
    goal = next(r for r in seed.items if r["tier"] == "goal")
    builds = reader.builds
    seed.library.commit(items=[{"id": goal["id"], "watched": 1}])     # a change elsewhere: a new view
    assert wait_until(lambda: reader.builds > builds, 5)
    settle(100)
    assert [i for ids, _d in looks.calls for i in ids] == asked         # nothing asked again
    builds = reader.builds
    with reader._lock:
        again = dict(reader._folders)
    reader.set_folders(again)                                           # the same answers: no view built
    time.sleep(0.2)
    assert reader.builds == builds


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_K7_mattias_7_two_same_title_arrivals_place_one_and_the_other_row_is_right_with_no_stale_folder(world,
                                                                                                         language):
    # Kura's suspects for the stale row: the shell's caches kept per a row's key and per its first item. Two rows of
    # one title name their folders; one goes to Goal; the other stays exactly as the view has it — and, its title no
    # longer shared, without a folder on its line.
    seed, win, _w = world(language)
    title = SERIES[language][0]
    items, works = _series_items(language, max(r["id"] for r in seed.library.items()) + 1)
    items = [it for it in items if not it["parent_folder"].endswith(SERIES[language][1][2])]     # two books
    seed.library.commit(works=works, items=items, order=True)
    assert wait_until(lambda: sum(1 for a in tray_arrivals(win) if a.title == title) == 2, 5)
    _with_detail_looks(win, items, os.path.join("D:", os.sep, "本棚"))
    assert wait_until(lambda: all(a.folder for a in tray_arrivals(win) if a.title == title), 5)
    tray = open_tray(win)
    settle()
    first, second = [r for r in tray_rows(win) if r.arrival.title == title]
    placed, kept = set(first.arrival.item_ids), second.arrival
    tray.act(first.arrival, "goal")
    assert wait_until(lambda: not any(placed & set(a.item_ids) for a in tray_arrivals(win)), 5)
    settle()
    shown, viewed = _shown_and_viewed(win)
    assert shown == viewed                                             # never a row the view no longer holds
    left = [r.arrival for r in tray_rows(win) if r.arrival.title == title]
    assert [a.item_ids for a in left] == [kept.item_ids]
    assert left[0].folder is None and left[0].parts[0] != (kept.folder, "dim")     # alone now: no folder
    assert left[0].chip == "本棚"                                       # its source's name stays on its chip


def test_A4_S19_a_closed_tray_does_no_row_work_and_opening_brings_its_rows_up_to_date(world):
    seed, win, _w = world()
    tray = tray_of(win)
    open_tray(win)
    tray.close()
    settle()
    keys, paints, model_paints = tray.keys(), dict(tray.model.paints), tray.paints
    item_id = _arrive(seed)
    assert wait_until(lambda: any(item_id in a.item_ids for a in tray_arrivals(win)), 5)
    settle(100)
    assert tray.keys() == keys and tray.model.paints == paints and tray.paints == model_paints
    open_tray(win)
    assert any(item_id in r.arrival.item_ids for r in tray_rows(win))
    assert [r.key for r in tray_rows(win)][1:] == keys                  # one row inserted: the others as they were
    assert all(tray.model.paints[k] == paints[k] for k in keys)


def test_A4_the_inset_given_the_same_rows_looks_at_nothing_and_its_covers_are_the_newest_in_order():
    seed = window_seed.build()
    view = _view(seed)
    inset = arrivals.ArrivalsInset()
    assert inset.set_arrivals(view.arrivals, 10)
    paints = inset.paints
    assert not inset.set_arrivals(view.arrivals, 10) and inset.paints == paints
    same = [a._replace(added_at="2026-10-01T00:00:00Z") for a in view.arrivals]      # every stamp equal: the
    assert arrivals.inset_titles(same) == tuple(a.cover_title or a.title for a in same[:3])   # tray's order kept
    many = _many_arrivals(2000)                                       # New then Already watched, each newest first:
    watched = tuple(a._replace(group="watched", added_at=f"2026-10-{1 + k % 28:02d}T09:00:00Z")
                    for k, a in enumerate(many[:900]))
    news = tuple(a._replace(added_at=f"2026-10-{1 + k % 28:02d}T10:00:00Z") for k, a in enumerate(many[900:]))
    tray_order = tuple(sorted(news, key=lambda a: a.added_at, reverse=True)) +         tuple(sorted(watched, key=lambda a: a.added_at, reverse=True))
    want = sorted(tray_order, key=lambda a: a.added_at or "", reverse=True)[:3]
    assert arrivals.newest(tray_order) == want                        # each group's head is enough


class _Later:
    """A test's timer: what waits is held until `run`."""

    def __init__(self):
        self.waiting = []

    def __call__(self, seconds, fn):
        self.waiting.append((seconds, fn))

    def run(self):
        held, self.waiting = self.waiting, []
        for _s, fn in held:
            fn()


class _AtOnce(FakeWorker):
    def estimate(self, path, placed=(), callback=None, piece=None):
        self.asked.append((path, placed, piece))
        callback({"n_new_top": 7, "n_new_after_show": 3 if placed else None, "plan": "p"})


def _many_arrivals(n):
    items = {k: {"id": k, "tier": "arrivals", "ord": float(k), "work_id": 10_000 + k // 4, "piece_id": None,
                 "rel_path": f"HighPriority/作品{k // 4}/第{k % 4 + 1:02d}話.srt", "parent_folder": f"作品{k // 4}",
                 "added_at": "2026-10-20T10:00:00Z"} for k in range(1, n + 1)}
    works = {10_000 + j: {"id": 10_000 + j, "title": f"作品{j}", "media_type": "anime"} for j in range(n // 4 + 1)}
    return view_rows.build(items, works, {"arrivals_on": 1}).arrivals


def test_A4_a_burst_of_answers_is_handed_on_at_most_four_times_a_second_and_the_last_is_never_lost(tmp_path):
    arrivals_ = _many_arrivals(400)
    worker, later, now = _AtOnce(), _Later(), [100.0]
    known = tmp_path / "KnownWord.json"
    known.write_text('{"words": ["猫"]}', encoding="utf-8")
    got = []
    nums = arrivals.ArrivalNumbers(worker, "ja", on_change=got.append, data_path=str(tmp_path / "d"),
                                   known_file=str(known), plan_token=lambda: 1, run=_sync, later=later,
                                   clock=lambda: now[0])
    nums.want(arrivals_)
    assert nums.answers == 400
    assert len(got) == 1 and len(got[0]) == 1                         # the first at once, the rest wait their turn
    assert [s for s, _fn in later.waiting] == [pytest.approx(0.25)]   # one hand-on waiting, never one per answer
    now[0] += 0.25
    later.run()
    assert len(got) == 2 and len(got[-1]) == 400                      # the last answer never lost
    nums.flush()
    assert len(got) == 2                                              # nothing moved: nothing handed (S19)


def test_A4_each_file_is_asked_by_its_place_in_its_piece_and_the_worker_writes_the_list_it_always_read(tmp_path):
    from app.services import arrivals as service
    a = _many_arrivals(8)[0]
    worker = _AtOnce()
    nums, _got, _k = _numbers(worker, tmp_path)
    nums.want([a])
    asked = worker.asked
    assert [placed for _p, placed, _piece in asked] == list(range(len(a.item_ids)))
    assert len({id(piece) for _p, _placed, piece in asked}) == 1      # one tuple the piece's asks share
    piece = asked[0][2]
    request = {"id": 3, "op": "estimate", "path": piece[2], "placed": 2, "piece": piece}
    assert service._written(request) == {"id": 3, "op": "estimate", "path": piece[2], "placed": list(piece[:2])}
    listed = {"id": 4, "op": "estimate", "path": piece[1], "placed": [piece[0]]}
    assert service._written(listed) is listed                         # the list form as before


# --- A4 Part 2: the tray's picks and its groups' All to Soon / All to Goal --------------------------------------------- #
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def _picked_keys(win):
    return [r.key for r in tray_rows(win) if r.key in tray_of(win).picks]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A4_ctrl_and_shift_click_pick_rows_ctrl_a_picks_all_and_esc_or_a_plain_click_lets_them_go(world, language):
    seed, win, writer = world(language)
    tray = open_tray(win)
    rs = tray_rows(win)
    rs[0].click("row", CTRL)
    rs[2].click("icon", CTRL)                                         # a Ctrl+click picks, never acts
    assert _picked_keys(win) == [rs[0].key, rs[2].key] and calls(writer) == []
    assert tray.view.picked(rs[0].key) and not tray.view.picked(rs[1].key)     # drawn as Current's picked rows
    rs[0].click("row", CTRL)                                          # again: let go
    assert _picked_keys(win) == [rs[2].key]
    rs[2].click("row", SHIFT)                                         # Shift: from the row Ctrl clicked last to this one
    assert _picked_keys(win) == [r.key for r in rs]
    rs[1].click("row")                                                # a plain click lets them go
    assert tray.picks == set() and calls(writer) == []
    tray.view.setFocus()
    QTest.keyClick(tray.view, Qt.Key.Key_A, CTRL)                     # Ctrl+A while the tray has the keys
    assert _picked_keys(win) == [r.key for r in rs]
    esc(tray.view)                                                    # Esc: the picks go, the tray stays
    assert tray.picks == set() and tray.isVisible()
    esc(tray.view)                                                    # again: it closes
    assert not tray.isVisible()


def test_A4_more_on_a_picked_row_moves_every_pick_in_one_command_one_toast_one_undo(world):
    seed, win, writer = world()
    tray = open_tray(win)
    rs = tray_rows(win)
    rs[0].click("row", CTRL)
    rs[1].click("row", CTRL)
    ids = list(rs[0].arrival.item_ids) + list(rs[1].arrival.item_ids)    # the tray's order
    rs[1].click("more")                                               # ⋯ keeps the picks: the picks' menu
    menu = tray.last_menu
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == [v[0] for v in strings.TRAY_PICKS_MENU.values()]
    assert menu.accessibleName() == strings.TRAY_PICKS_MENU_NAME.format(n=2)
    assert all(a.toolTip() and "2" in a.toolTip() for a in menu.actions() if not a.isSeparator())
    next(a for a in menu.actions() if a.text() == "Soon").trigger()
    assert calls(writer, "place") == [("place", ids, {"where": "soon"})]       # ONE command
    assert win.toasts.card.base == strings.TRAY_PLACED["soon"].format(title=strings.TRAY_TITLES.format(n=2))
    assert tray.picks == set()
    assert wait_until(lambda: writer.saved, 3)
    settle()
    undo = [b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO]
    assert len(undo) == 1
    undo[0].click()
    assert wait_until(lambda: calls(writer, "undo"), 3)


def test_A4_a_right_click_on_a_picked_row_offers_the_picks_and_finished_keeps_D14s_choice(world):
    seed, win, writer = world()
    tray = open_tray(win)
    rs = tray_rows(win)
    rs[1].click("row", CTRL)
    rs[2].click("row", CTRL)
    ids = list(rs[1].arrival.item_ids) + list(rs[2].arrival.item_ids)
    vp = tray.view.viewport()
    at = rs[2].rect("row").center()
    QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, at, vp.mapToGlobal(at)))
    menu = tray.last_menu
    assert menu.accessibleName() == strings.TRAY_PICKS_MENU_NAME.format(n=2)
    next(a for a in menu.actions() if a.text() == strings.TRAY_PICKS_MENU["finished"][0]).trigger()
    assert calls(writer, "place") == [("place", ids, {"where": "finished"})]
    assert strings.DRAG_TAKE_OUT in [b.text() for b in win.toasts.card.buttons if b.isVisible()]
    rs = tray_rows(win)
    tray.menu(rs[0].key).close()                                       # an unpicked row's ⋯: its own menu, as before
    assert tray.last_menu.accessibleName() == strings.TRAY_MENU_NAME.format(title=rs[0].arrival.title)


def test_A4_remove_on_the_picks_asks_once_naming_every_file_and_removes_them_in_one_command(world):
    seed, win, writer = world()
    tray = open_tray(win)
    rs = tray_rows(win)
    rs[0].click("row", CTRL)
    rs[1].click("row", CTRL)
    ids = list(rs[0].arrival.item_ids) + list(rs[1].arrival.item_ids)
    tray.act_many(tray.picked(), "remove")
    q = tray.question
    assert q.yes.text() == strings.TRAY_REMOVE_YES.format(n=len(ids)) and q.default is q.no
    q.yes.click()
    assert calls(writer, "remove") == [("remove", ids, {})]


def test_A4_a_drag_from_a_picked_row_carries_every_pick(world):
    seed, win, writer = world()
    tray = open_tray(win)
    rs = tray_rows(win)
    rs[0].click("row", CTRL)
    rs[1].click("row", CTRL)
    ids = list(rs[0].arrival.item_ids) + list(rs[1].arrival.item_ids)
    lift_row(win, 1)                                                  # a plain press on a picked row keeps them
    assert win.moves.running.ids == ids and win.moves.running.title == strings.TRAY_TITLES.format(n=2)
    at = well_point(win, "goal")
    move_global(win, at)
    release_global(win, at)
    assert [c[1] for c in calls(writer)] == [ids]                     # one command for both


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_A4_each_group_head_offers_all_to_soon_and_all_to_goal_in_one_command(world, language):
    seed, win, writer = world(language)
    tray = open_tray(win)
    for kind in ("new", "watched"):
        head = tray.heads[kind][0]
        for where in ("soon", "goal"):
            b = getattr(head, where)
            assert b.isVisible() and b.toolTip() and b.accessibleName() == b.text()
    assert tray.heads["new"][2] is None and tray.heads["watched"][2].text() == strings.TRAY_ALL_FINISHED
    rows_ = next(g.rows for g in tray.groups if g.kind == "new")
    ids = [i for a in rows_ for i in a.item_ids]
    tray.heads["new"][0].goal.click()
    assert calls(writer, "place") == [("place", ids, {"where": "goal"})]
    assert win.toasts.card.base == strings.TRAY_PLACED["goal"].format(title=strings.TRAY_TITLES.format(n=len(rows_)))
    found, _n = problems(win)
    assert found == []


# --- the real store ----------------------------------------------------------------------------------------------- #
from tests.qt.test_drag import real  # noqa: E402,F401


def _real_arrivals(store, n_items=3):
    """A real store with a show's last files back in New arrivals (as hato's register leaves a 3.0 store's drops)."""
    ids = store.ids("soon")[-n_items:]
    store.set_tier(ids, "arrivals")
    return ids


def test_real_store_the_icon_places_it_at_the_top_and_undo_puts_it_back(real):
    store, win, writer = real()
    ids = _real_arrivals(store)
    assert wait_until(lambda: win.arrivals_tray.groups, 10)
    open_tray(win)
    row = next(r for r in tray_rows(win) if ids[0] in r.arrival.item_ids)
    row.click("icon")
    assert wait_until(lambda: store.place_of(ids[0])[0] == "now", 5)
    assert store.place_of(ids[0])[1] == 1
    assert wait_until(lambda: writer.can_undo() and not win.moves.tickets, 5)
    settle()
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: store.place_of(ids[0])[0] == "arrivals", 5)


def test_real_store_finished_with_its_new_cards_taken_out(real):
    store, win, writer = real()
    ids = _real_arrivals(store, 2)
    assert wait_until(lambda: win.arrivals_tray.groups, 10)
    tray = open_tray(win)
    row = next(r for r in tray_rows(win) if ids[0] in r.arrival.item_ids)
    assert all(store.item(i)["watched"] != 1 for i in row.arrival.item_ids)
    tray.act(row.arrival, "finished")
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in row.arrival.item_ids), 5)
    assert all(store.item(i)["watched"] == 1 for i in row.arrival.item_ids)     # A2 #28 (IK-L2-3): watched
    settle()
    next(b for b in win.toasts.card.buttons if b.text() == strings.DRAG_TAKE_OUT).click()
    assert wait_until(lambda: all(store.item(i)["in_learning_order"] == 0 for i in row.arrival.item_ids), 5)
    assert all(store.item(i)["watched"] == 1 for i in row.arrival.item_ids)


def test_real_store_IK_L2_3_the_check_and_all_to_finished_land_watched_and_after_its_show_is_offered(real):
    store, win, writer = real()
    ids = _real_arrivals(store, 2)                                    # its show's earlier files stay in Current
    assert wait_until(lambda: win.arrivals_tray.groups, 10)
    tray = open_tray(win)
    row = next(r for r in tray_rows(win) if ids[0] in r.arrival.item_ids)
    menu = tray.menu(row)                                             # N1: its show is in Current: offered
    assert next(a for a in menu.actions() if a.text() == strings.TRAY_MENU["after-show"][0]).isEnabled()
    menu.close()
    store.set_watched(ids)                                            # watched elsewhere: ✓ and All to Finished
    assert wait_until(lambda: tray.watched(), 10)
    tray.heads["watched"][2].click()
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in ids), 5)
    assert all(store.item(i)["watched"] == 1 for i in ids)


def test_real_store_remove_sends_it_to_the_trash_and_undo_brings_it_back(real):
    store, win, writer = real()
    ids = _real_arrivals(store, 2)
    assert wait_until(lambda: win.arrivals_tray.groups, 10)
    tray = open_tray(win)
    row = next(r for r in tray_rows(win) if ids[0] in r.arrival.item_ids)
    item_ids = list(row.arrival.item_ids)
    tray.act(row.arrival, "remove")
    tray.question.yes.click()
    assert wait_until(lambda: all(store.item(i) is None for i in item_ids), 5)
    assert wait_until(lambda: writer.can_undo() and not win.moves.tickets, 5)
    settle()
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: all(store.item(i) is not None and store.item(i)["tier"] == "arrivals"
                                  for i in item_ids), 5)


def test_real_store_a_drag_from_the_tray_onto_the_finished_well_lands_in_finished(real):
    store, win, writer = real()
    ids = _real_arrivals(store, 2)
    assert wait_until(lambda: win.arrivals_tray.groups, 10)
    open_tray(win)
    k = next(n for n, r in enumerate(tray_rows(win)) if ids[0] in r.arrival.item_ids)
    item_ids = list(tray_rows(win)[k].arrival.item_ids)
    lift_row(win, k)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in item_ids), 5)
    assert all(store.item(i)["watched"] == 1 for i in item_ids)       # A2 #28 (IK-L2-3): the well records it watched


def test_real_store_A4_two_picked_arrivals_to_goal_in_one_command_and_one_undo_brings_both_back(real):
    store, win, writer = real()
    first, second = store.ids("soon")[-2:], store.ids("goal")[-2:]    # two shows' files, as two arrivals
    store.set_tier(first, "arrivals")
    store.set_tier(second, "arrivals")
    assert wait_until(lambda: sum(len(g.rows) for g in win.arrivals_tray.groups) >= 2, 10)
    tray = open_tray(win)
    settle()
    rs = [r for r in tray_rows(win) if set(r.arrival.item_ids) & set(first + second)]
    assert len(rs) >= 2                                               # (each folder its own run)
    for r in rs:
        r.click("row", CTRL)
    ids = [i for r in rs for i in r.arrival.item_ids]
    tray.act_many(tray.picked(), "goal")
    assert wait_until(lambda: all(store.item(i)["tier"] == "goal" for i in ids), 5)
    assert wait_until(lambda: writer.can_undo() and not win.moves.tickets, 5)
    settle()
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: all(store.item(i)["tier"] == "arrivals" for i in ids), 5)
