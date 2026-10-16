"""Search your library in the window (W3.2 Q3, `app/qt/search.py`; A2 #79–86, the RUNBOOK §1 *Search*, §5a N7): the
header's cut, its results overlay and what a hit does — on the window's seed (invented Japanese titles) through the
stand-in store, the search itself S4's on a **real store** written from the same seed (its ids are the window's), asked
on the searcher's own thread.

What a wrong answer would cost a learner:
  * `/` or Ctrl+K not reaching the box (or `/` stolen from Settings' own search), the cursor leaving the box while they
    type (A2 #79, #81);
  * a show they typed not found by its romaji, a split show listed once so ⤒ moves the wrong part (A2 #80, #86);
  * ⤒ moving the wrong thing — the whole of a Goal title instead of its next part, an arrival left in New arrivals, a
    Finished show back in Current with its cards still out of the order (A2 #82, #83, IK-1);
  * a click that doesn't show the row (A2 #84), results that jump in again on every keystroke (A2 #85);
  * results that won't close on Esc, Back or a click away (N7), or a store that can't be saved taking a move (E4).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app.qt import search as search_ui
from app.qt import strings
from app.services import search as S
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, _stones_sheet, open_window  # noqa: F401  (the stones' sheet fixture)
from tests.test_library_store_support import roots
from tests.test_services_search import real_store

ARRIVAL_ROMAJI = "Kumo no Ue no Yuubinya-san"           # an arrival's other title, as hato's record would bring it


class Writer(FakeWriter):
    """The test_drag writer with W3.2's commands (`moves.Writer`'s names), each recorded."""

    def place(self, ids, where, label=None):
        return self._put("place", ids, label, where=where)

    def put_back(self, ids, label=None):
        return self._put("put_back", ids, label)


class Opener:
    """`library_store.StoreOpener` on the seed's real store (its handle is the searcher thread's own)."""

    def __init__(self, language):
        data_dir, user_files_dir = roots(language)
        self.real = ls.StoreOpener(language, data_dir, user_files_dir, role="window")
        self.mode = "store"

    def check(self):
        return self.real.check()

    def handle(self):
        return self.real.handle()

    def close(self):
        close = getattr(self.real, "close", None)
        if close is not None:
            close()


@pytest.fixture
def world(qapp):
    made = []

    def make(writable=True):
        seed = window_seed.build()
        arrival_work = next(r["work_id"] for r in seed.items if r["tier"] == "arrivals")
        store = real_store(seed, titles={arrival_work: [ARRIVAL_ROMAJI]})
        store.close()
        writer = Writer(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
        page = win.page_widgets["current"]
        win.search.searcher = S.Searcher(Opener(seed.language), lambda: page.view_model)
        made.append((win, services))
        win.activateWindow()
        QApplication.processEvents()
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def ask(win, text):
    """Type `text` into the search (focused, as a learner's hand puts it there) and wait for its results."""
    cut = win.search
    cut.edit.setFocus(Qt.FocusReason.OtherFocusReason)
    before = cut.results.fills if cut.results is not None else 0
    cut.edit.setText(text)
    assert wait_until(lambda: cut.results is not None and cut.results.fills > before and cut.results.isVisible()
                      and cut.results.query == text)
    return cut.results


def hits_of(results, group=None):
    return [r.hit for r in results.hits if group is None or r.hit.group == group]


def rows_of(win):
    return win.page_widgets["current"].view_model.rows


def calls(writer, op):
    return [c for c in writer.calls if c[0] == op]


# --- the keys ------------------------------------------------------------------------------------------------------ #
def test_A2_79_slash_and_ctrl_k_jump_to_the_search_and_on_settings_slash_is_its_own(world, monkeypatch):
    seed, win, _writer = world()
    win._rest.setFocus()
    QTest.keyClick(win._rest, Qt.Key.Key_Slash)
    assert QApplication.focusWidget() is win.search.edit and win.search.edit.text() == ""     # no "/" typed in
    win._rest.setFocus()
    QTest.keyClick(win._rest, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.focusWidget() is win.search.edit
    asked = []
    monkeypatch.setattr(win.page_widgets["settings"], "focus_search", lambda: asked.append(True), raising=False)
    win.show_tab("settings")
    win._rest.setFocus()
    QTest.keyClick(win._rest, Qt.Key.Key_Slash)
    assert asked == [True] and QApplication.focusWidget() is not win.search.edit


def test_the_cut_sinks_while_focused_and_rests_unlit(world):
    seed, win, _writer = world()
    cut = win.search
    assert cut.sink == 0.0                                          # unlit at rest
    cut.edit.setFocus(Qt.FocusReason.OtherFocusReason)
    assert wait_until(lambda: cut.sink == 1.0)
    win._rest.setFocus()
    assert wait_until(lambda: cut.sink == 0.0)


def test_typing_asks_once_after_the_last_keystroke(world):
    # 120 ms after the last keystroke (A2 #85's hold): "kumo" typed letter by letter is one search, not four.
    seed, win, _writer = world()
    cut = win.search
    cut.edit.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClicks(cut.edit, "kumo")
    assert wait_until(lambda: cut.results is not None and cut.results.isVisible())
    assert cut.asked == 1


# --- what it finds ----------------------------------------------------------------------------------------------- #
def test_A2_80_a_new_arrival_is_found_by_its_romaji_and_A2_81_the_cursor_stays_in_the_box(world):
    seed, win, _writer = world()
    results = ask(win, "yuubinya")
    arrivals = hits_of(results, "arrivals")
    assert arrivals and arrivals[0].where.startswith("New arrivals")
    assert QApplication.focusWidget() is win.search.edit           # the results never take the keyboard
    assert all(not b.focusPolicy() & Qt.FocusPolicy.TabFocus
               for r in results.hits for b in (r.play_button, r.top_button) if b is not None)


def test_A2_86_a_show_in_two_pieces_shows_up_twice_each_with_its_episodes(world):
    seed, win, _writer = world()
    split = [r for r in rows_of(win) if r.title == rows_of(win)[2].title]
    assert len(split) == 2
    results = ask(win, split[0].title)
    current = hits_of(results, "current")
    assert [h.key for h in current] == [r.key for r in split]
    assert [h.where for h in current] == [f"Ep 1–4 · #{split[0].index} in Current",
                                          f"Ep 5–8 · #{split[1].index} in Current"]


def test_the_matched_text_is_lit_where_it_falls_in_the_title():
    assert search_ui.split_lit("星降る街の小さな工房", ((5, 8),)) == [("星降る街の", False), ("小さな", True),
                                                                     ("工房", False)]
    assert search_ui.split_lit("星降る街の小…", ((5, 8),)) == [("星降る街の", False), ("小…", True)]   # cut short
    assert search_ui.split_lit("がらす", ()) == [("がらす", False)]


def test_nothing_found_says_so_in_the_overlay(world):
    seed, win, _writer = world()
    results = ask(win, "存在しない題名")
    assert results.hits == []
    labels = [w.text() for w in results.body.findChildren(search_ui.QLabel)]
    assert strings.SEARCH_NONE.format(query="存在しない題名") in labels


def test_A2_85_the_results_animate_in_once_then_hold_while_typing(world):
    seed, win, _writer = world()
    results = ask(win, "星")
    assert results.opens == 1
    results = ask(win, "星降")
    assert results.opens == 1 and results.fills >= 2                # refilled in place, never opened again


# --- what a hit does --------------------------------------------------------------------------------------------- #
def test_A2_84_a_click_on_a_current_result_shows_it_in_place_scrolled_and_washed(world):
    seed, win, _writer = world()
    target = rows_of(win)[-1]
    results = ask(win, target.title)
    row = next(r for r in results.hits if r.hit.key == target.key)
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=QPoint(row.width() // 3, row.height() // 2))
    assert not results.isVisible()
    assert win.current_tab() == "current"
    lst = win.page_widgets["current"].list
    assert wait_until(lambda: win.search.washes == 1)
    at = next(i for i, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == target.key)
    rect = lst.visualRect(lst.model().index(at, 0))
    assert lst.viewport().rect().intersects(rect)                   # scrolled to it
    assert win.search.washed_at == rect                              # the wash over that row


def test_a_finished_result_opens_finished_at_it(world):
    seed, win, _writer = world()
    results = ask(win, "がらす")
    hit = hits_of(results, "finished")[0]
    win.search.reveal(hit)
    assert win.current_tab() == "finished"
    assert wait_until(lambda: win.search.washes == 1)


def test_a_goal_result_shows_currents_goal_dock_until_goals_sheet_lands_then_opens_the_sheet(world):
    seed, win, _writer = world()
    goal_work = next(r["work_id"] for r in seed.items if r["tier"] == "goal")
    title = next(w["title"] for w in seed.works if w["id"] == goal_work)
    results = ask(win, title)
    hit = hits_of(results, "goal")[0]
    win.show_tab("finished")
    win.search.reveal(hit)
    assert win.current_tab() == "current" and win.search.washes == 1
    opened = []
    win.show_goal = opened.append                                    # Q2's sheet, once it is there
    win.search.reveal(hit)
    assert opened == [goal_work]


def test_play_on_a_current_hit_opens_its_next_episode_as_the_rows_play_does(world, monkeypatch):
    seed, win, _writer = world()
    hero = rows_of(win)[0]
    played = []
    monkeypatch.setattr(win.page_widgets["current"], "_play", played.append)
    results = ask(win, hero.title)
    row = next(r for r in results.hits if r.hit.key == hero.key)
    assert row.top_button is None                                    # Current's first row: no ⤒
    QTest.mouseClick(row.play_button, Qt.MouseButton.LeftButton)
    assert played == [hero.episodes[hero.next_index]]


def test_top_on_a_current_hit_makes_it_up_next(world):
    seed, win, writer = world()
    target = rows_of(win)[4]
    hero = rows_of(win)[0]
    results = ask(win, target.title)
    row = next(r for r in results.hits if r.hit.key == target.key)
    QTest.mouseClick(row.top_button, Qt.MouseButton.LeftButton)
    op, ids, kw = calls(writer, "move")[-1]
    assert ids == [e.id for e in target.episodes] and kw["tier"] == hero.tier
    assert kw["before_id"] == hero.episodes[0].id


def test_A2_82_top_puts_the_arrival_up_next_out_of_new_arrivals(world):
    seed, win, writer = world()
    results = ask(win, "yuubinya")
    hit = hits_of(results, "arrivals")[0]
    row = next(r for r in results.hits if r.hit is hit)
    QTest.mouseClick(row.top_button, Qt.MouseButton.LeftButton)
    assert calls(writer, "place") == [("place", list(hit.item_ids), {"where": "top"})]


def test_A2_83_top_on_a_goal_title_brings_its_next_part_up_and_the_rest_stays(world):
    seed, win, writer = world()
    goal_work = next(r["work_id"] for r in seed.items if r["tier"] == "goal")
    title = next(w["title"] for w in seed.works if w["id"] == goal_work)
    hit = hits_of(ask(win, title), "goal")[0]
    assert hit.top_ids and set(hit.top_ids) < set(hit.item_ids) or hit.top_ids == hit.item_ids
    win.search.top(hit)
    op, ids, kw = calls(writer, "move")[-1]
    assert ids == list(hit.top_ids) and kw["tier"] == "now" and kw["before_id"] is None and kw["after_id"] is None


def test_top_on_a_finished_hit_puts_it_back_with_its_cards(world):
    seed, win, writer = world()
    hit = hits_of(ask(win, "がらす"), "finished")[0]
    win.search.top(hit)
    assert calls(writer, "put_back") == [("put_back", list(hit.item_ids), {})]


def test_E4_a_store_that_cant_be_saved_refuses_top_and_says_why(world):
    seed, win, writer = world(writable=False)
    hit = hits_of(ask(win, "がらす"), "finished")[0]
    win.search.top(hit)
    assert writer.calls == []
    assert win.bar_line.full().startswith(strings.DRAG_REFUSED.split("{")[0])


# --- closing (N7) ------------------------------------------------------------------------------------------------ #
def test_esc_clears_then_closes(world):
    seed, win, _writer = world()
    results = ask(win, "星")
    QTest.keyClick(win.search.edit, Qt.Key.Key_Escape)
    assert not results.isVisible() and win.search.edit.text() == ""
    assert QApplication.focusWidget() is win.search.edit             # cleared: still in the box
    QTest.keyClick(win.search.edit, Qt.Key.Key_Escape)
    assert QApplication.focusWidget() is not win.search.edit          # then closed
    assert win.isVisible()                                           # never the main window


def test_esc_before_any_result_clears_the_box(world):
    seed, win, _writer = world()
    win.search.edit.setFocus(Qt.FocusReason.OtherFocusReason)
    win.search.edit.setText("星")
    QTest.keyClick(win.search.edit, Qt.Key.Key_Escape)
    assert win.search.edit.text() == "" and not win.search.timer.isActive()


def test_the_mouses_back_button_closes_the_results(world):
    seed, win, _writer = world()
    results = ask(win, "星")
    at = QPointF(results.rect().center())
    press = QMouseEvent(QEvent.Type.MouseButtonPress, at, results.mapToGlobal(at), Qt.MouseButton.BackButton,
                        Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(results, press)
    assert not results.isVisible()


def test_a_click_away_closes_the_results_keeps_the_words_and_a_late_answer_stays_closed(world):
    seed, win, _writer = world()
    results = ask(win, "星")
    lst = win.page_widgets["current"].list
    QTest.mousePress(lst.viewport(), Qt.MouseButton.LeftButton, pos=lst.viewport().rect().center())
    QTest.mouseRelease(lst.viewport(), Qt.MouseButton.LeftButton, pos=lst.viewport().rect().center())
    assert not results.isVisible() and win.search.edit.text() == "星"
    win.search._answered("星", (), 1.0)                              # an answer still on its way
    assert not results.isVisible()


def test_a_click_in_the_box_keeps_the_results_open(world):
    seed, win, _writer = world()
    results = ask(win, "星")
    QTest.mouseClick(win.search.edit, Qt.MouseButton.LeftButton)
    assert results.isVisible()


def test_arrows_pick_a_result_and_enter_shows_it(world):
    seed, win, _writer = world()
    results = ask(win, "がらす")
    QTest.keyClick(win.search.edit, Qt.Key.Key_Down)
    assert results.picked == 0 and results.hits[0].current
    QTest.keyClick(win.search.edit, Qt.Key.Key_Return)
    assert not results.isVisible() and win.current_tab() == "finished"


def test_a_view_published_while_the_results_show_asks_again(world):
    # the where-lines follow a move made meanwhile (⤒ itself, or a drag)
    seed, win, _writer = world()
    ask(win, "星")
    before = win.search.asked
    win.search.library_moved(None)
    assert wait_until(lambda: win.search.asked == before + 1)


def test_every_control_in_the_results_is_wired_tipped_and_named(world):
    from tests.qt.test_wiring import problems
    seed, win, _writer = world()
    ask(win, "星")
    found, _walked = problems(win)
    assert found == []


def test_without_a_library_the_search_isnt_offered(qapp):
    from app.qt import shell
    services = shell.Services()
    win = shell.open_window(qapp, services)
    try:
        win.show()
        assert win.search.isHidden()
        QTest.keyClick(win._rest, Qt.Key.Key_Slash)
        assert QApplication.focusWidget() is not win.search.edit
    finally:
        win.close()
        services.shutdown(0.5)
