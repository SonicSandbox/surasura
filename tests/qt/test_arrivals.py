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
from PyQt6.QtGui import QKeyEvent, QMouseEvent
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

    def estimate(self, path, placed=(), callback=None):
        with self.lock:
            self.asked.append((path, list(placed)))
            rid = len(self.asked)
        if self.error:
            answer = {"id": rid, "op": "estimate", "error": self.error}
        else:
            top, after = self.table.get(os.path.basename(path), (self.n, self.n // 3 if placed else None))
            answer = {"id": rid, "op": "estimate", "path": path, "n_new_top": top, "n_new_after_show": after,
                      "plan": self.plan, "exact": True}
        threading.Thread(target=callback, args=(answer,), daemon=True).start()
        return rid


def open_window(qapp, seed, writer, worker=None, size=(1280, 900)):
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
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

    def make(language="ja", worker=None, size=(1280, 900)):
        seed = window_seed.build(language=language)
        writer = ArrivalsWriter(seed.library)
        win, services = open_window(qapp, seed, writer, worker, size)
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


def tray_rows(win):
    """The tray's rows as laid out, top to bottom."""
    tray = tray_of(win)
    out = []
    for i in range(tray.list.count()):
        w = tray.list.itemAt(i).widget()
        if isinstance(w, arrivals.TrayRow):
            out.append(w)
    return out


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
    sizes = {(r.icon.width(), r.icon.height()) for r in rs}
    assert len(sizes) == 1                                            # one size on every row
    assert [r.icon.kind for r in rs] == ["top", "top", "finished"]
    for r in rs:
        assert r.icon.isVisible() and r.more.isVisible()              # always shown (n10: no hover-to-reveal)
        assert r.icon.toolTip().startswith(r.icon.accessibleName() + " · ")
        assert r.more.toolTip().startswith(r.more.accessibleName())
    assert rs[0].icon.toolTip().startswith("Top · Add to the top of Current")
    tray_of(win).menu(rs[1])                                          # the ⋯ menu's actions join the walk
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
    xs = {r.number.mapTo(tray_of(win), QPoint(0, 0)).x() for r in rs}
    assert len(xs) == 1                                               # #92: one column whatever the row
    fz = theme.text_factor("M")
    for r in rs:
        assert r.number.width() == round(56 * fz)
        assert r.text_right() <= r.number.x() - round(28 * fz)        # #96: the title stops 28 px short
        assert "≈" not in r.number.toolTip() and "~" not in r.number.toolTip()    # #90
        assert "estimate until analysed" in r.number.toolTip()
    assert rs[1].number.text[0] == strings.TRAY_NUMBER_NONE           # a dash until it's counted
    assert "6 episodes" in rs[1].number.toolTip()


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
    assert row.number.text == ("9", "new / ep")
    assert row.number.toolTip().startswith("About 9 new words an episode")
    assert row.paints == paints[row.arrival.key] + 1
    others = [r for r in tray_rows(win) if r is not row]
    assert all(r.paints == paints[r.arrival.key] for r in others)     # S19: only the row whose number came


# --- the actions -------------------------------------------------------------------------------------------------- #
def test_A2_27_the_top_icon_places_the_arrival_through_the_writer_and_the_tray_stays_open(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[1]
    ids = list(row.arrival.item_ids)
    row.icon.click()
    assert calls(writer, "place") == [("place", ids, {"where": "top"})]
    assert win.toasts.card.message == strings.TRAY_PLACED["top"].format(title=row.arrival.title)
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
    menu = tray_of(win).menu(row)
    act = next(a for a in menu.actions() if a.text() == strings.TRAY_MENU[name][0])
    assert act.toolTip() and act.isEnabled()
    act.trigger()
    assert calls(writer, "place") == [("place", list(row.arrival.item_ids), {"where": name})]
    menu.close()


def test_the_menu_lists_its_entries_in_order_and_disables_the_moves_on_a_read_only_store(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[0]
    menu = tray_of(win).menu(row)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    # --- W3.2 L3: *Change cover…* (a submenu) after the moves, before *Open its folder*
    want = [strings.TRAY_MENU[n][0] for n in arrivals.MENU]
    assert labels == want[:5] + [strings.ITEM_MENU["cover"][0]] + want[5:]
    menu.close()
    writer.writable = False
    menu = tray_of(win).menu(row)
    enabled = {a.text(): a.isEnabled() for a in menu.actions() if not a.isSeparator()}
    assert enabled[strings.TRAY_MENU["folder"][0]] and not enabled[strings.TRAY_MENU["top"][0]]
    menu.close()
    row.icon.click()                                                  # E4: refused at the press, said in the bar
    assert calls(writer, "place") == []


def test_IK_11_finished_on_a_watched_arrival_offers_D14s_choice_and_take_out_follows_it(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[2]
    ids = list(row.arrival.item_ids)
    assert row.icon.kind == "finished"
    row.icon.click()
    assert calls(writer, "place") == [("place", ids, {"where": "finished"})]
    card = win.toasts.card
    assert card.message == strings.DRAG_FINISHED.format(title=row.arrival.title)
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
    menu = tray_of(win).menu(row)
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
    from app.qt import windows
    opened = []
    monkeypatch.setattr(windows, "open_url", lambda url: opened.append(url) or True)
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[1]
    rel = row.arrival.rel_paths[0]
    want = os.path.dirname(os.path.join(path_utils.get_data_path("ja"), *rel.split("/")))
    tray_of(win).act(row.arrival, "folder")                           # N4: gone: looked for on a worker, then said
    assert wait_until(lambda: win.bar_line.full() == strings.TRAY_NO_FOLDER.format(path=want), 5)
    assert opened == []
    os.makedirs(want, exist_ok=True)
    menu = tray_of(win).menu(row)
    next(a for a in menu.actions() if a.text() == strings.TRAY_MENU["folder"][0]).trigger()
    assert wait_until(lambda: opened == [want], 5) and calls(writer) == []


def test_N1_after_its_show_is_greyed_while_none_of_its_show_is_in_current_and_N4_the_menu_goes_once_hidden(world):
    seed, win, writer = world()
    open_tray(win)
    row = tray_rows(win)[0]                                           # a YouTube video: no part of it in Current
    menu = tray_of(win).menu(row)
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
    tray = tray_of(win)
    tray.act(row.arrival, "remove")
    q = tray.question
    assert q is not None and q.yes.text() == strings.TRAY_REMOVE_YES.format(n=6)
    assert q.default is q.no                                          # Enter at first is Cancel
    esc(q)
    assert wait_until(lambda: sip.isdeleted(q) or not q.isVisible(), 3)
    assert calls(writer, "remove") == []
    tray.open() if not tray.isVisible() else None
    tray.act(row.arrival, "remove")
    tray.question.yes.click()
    assert calls(writer, "remove") == [("remove", ids, {})]
    card = win.toasts.card
    assert card.message == strings.TRAY_REMOVED.format(title=row.arrival.title)
    undo = next(b for b in card.buttons if b.text() == strings.TOAST_UNDO)
    assert wait_until(lambda: writer.saved, 3)
    settle()
    undo.click()
    assert wait_until(lambda: calls(writer, "undo"), 3)


def test_enter_on_a_focused_row_is_its_icon_and_tab_walks_the_rows(world):
    seed, win, writer = world()
    open_tray(win)
    rs = tray_rows(win)
    rs[0].setFocus()
    QApplication.processEvents()
    assert rs[0].focusPolicy() & Qt.FocusPolicy.TabFocus
    QTest.keyClick(rs[0], Qt.Key.Key_Return)
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
    row = tray_rows(win)[0]
    mouse(row, QEvent.Type.MouseButtonPress, QPointF(row.width() / 2, row.height() / 2))
    mouse(row, QEvent.Type.MouseButtonRelease, QPointF(row.width() / 2, row.height() / 2), LEFT, NONE)
    assert tray.isVisible()                                           # inside: stays
    lst = win.page_widgets["current"].list
    mouse(lst.viewport(), QEvent.Type.MouseButtonPress, QPointF(20, 20))
    mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, QPointF(20, 20), LEFT, NONE)
    assert not tray.isVisible()                                       # a click away
    tray = open_tray(win)
    win.arrivals_inset.click()                                        # the inset again
    assert not tray.isVisible()


# --- the drag ----------------------------------------------------------------------------------------------------- #
def lift_row(win, k):
    row = tray_rows(win)[k]
    at = QPointF(row.width() / 2, row.height() / 2)
    mouse(row, QEvent.Type.MouseButtonPress, at)
    mouse(row, QEvent.Type.MouseMove, at + QPointF(0, theme.MOTION["drag-start-px"]), NONE, LEFT)
    assert win.moves.running is not None
    return row


def test_A2_24_a_drag_from_the_tray_lands_where_the_gap_was_and_the_tray_fades_then_comes_back(world):
    seed, win, writer = world()
    tray = open_tray(win)
    row = lift_row(win, 1)
    ids = list(row.arrival.item_ids)
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
    row = lift_row(win, 1)
    ids = list(row.arrival.item_ids)
    at = well_point(win, "finished")
    move_global(win, at)
    release_global(win, at)
    assert calls(writer, "set_tier") == [("set_tier", ids, {"tier": "graduated"})]
    assert strings.DRAG_TAKE_OUT in [b.text() for b in win.toasts.card.buttons if b.isVisible()]


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


def _numbers(worker, tmp_path, plan=lambda: 1):
    got = []
    known = tmp_path / "KnownWord.json"
    known.write_text('{"words": ["猫"]}', encoding="utf-8")
    nums = arrivals.ArrivalNumbers(worker, "ja", on_change=got.append, data_path=str(tmp_path / "data"),
                                   known_file=str(known), plan_token=plan, run=_sync)
    return nums, got, known


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
    assert wait_until(lambda: len(got) == 10, 3)
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

    def estimate(self, path, placed=(), callback=None):
        with self.lock:
            self.asked.append((path, list(placed)))
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
                                   known_file=str(known), plan_token=lambda: 1, run=_sync)
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
    assert wait_until(lambda: len(got) == 10, 3)
    known_sig = nums._token[1]
    first = view.arrivals[0].item_ids[0]
    assert (first, "sig-1", known_sig) in nums.kept
    nums.recheck()                                                    # nothing moved: nothing asked
    assert len(worker.asked) == 10
    plan[0] = 2                                                       # a Generate: a new plan
    worker.plan = "sig-2"
    nums.recheck()
    assert wait_until(lambda: len(got) == 20, 3)
    assert len(worker.asked) == 20 and (first, "sig-2", known_sig) in nums.kept
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


def test_the_window_asks_each_new_files_estimate_once_and_shows_it_within_300_ms(world):
    worker = FakeWorker(n=8)
    seed, win, _w = world(worker=worker)
    assert wait_until(lambda: all(r.arrival.per_ep is not None for r in tray_rows(win)), 5)
    assert len(worker.asked) == 10
    t0 = time.perf_counter()
    item_id = _arrive(seed)
    shown = lambda: any(item_id in r.arrival.item_ids and r.arrival.per_ep == 8 for r in tray_rows(win))  # noqa: E731
    assert wait_until(shown, 5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"an arrival -> its number in the tray: {ms:.0f} ms")
    assert ms <= 300                                                  # functional (a shared machine)
    settle(100)
    assert len(worker.asked) == 11                                    # only the new file


def test_S2_the_same_answers_again_hand_nothing_on_so_the_reader_builds_nothing(tmp_path):
    seed = window_seed.build()
    view = _view(seed)
    worker = FakeWorker()
    nums, got, _k = _numbers(worker, tmp_path)
    nums.want(view.arrivals)
    assert wait_until(lambda: len(got) == 10, 3)
    nums.want(view.arrivals, force=True)                              # every file asked again, every answer the same
    assert wait_until(lambda: len(worker.asked) == 20, 3)
    time.sleep(0.1)
    assert len(got) == 10


def test_S2_a_drag_then_the_tray_opened_asks_no_number_again_and_a_generate_asks_them_all(world, monkeypatch):
    # the token is the plan file's key, never the numbers' version (which moves with every drop)
    key = [(1, 100)]
    monkeypatch.setattr(window_seed._Numbers, "plan_key", lambda self: key[0], raising=False)
    worker = FakeWorker(n=8)
    seed, win, _w = world(worker=worker)
    assert wait_until(lambda: all(r.arrival.per_ep is not None for r in tray_rows(win)), 5)
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
    row.icon.click()
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
