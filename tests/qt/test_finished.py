"""Finished's actions (W3.2 Q4, `app/qt/finished.py`; RUNBOOK §1 *Finished* and *What if I added it back?*, §5 leans 1
and 8, §5a IK-1, IK-5, N3; 06 E4, E23): the hover's *Put back* and ⋯, the *What if I added it back?* card, the importer
and Explorer's files on the Finished tab — on the window's seed (Japanese titles) through a recording writer, and where
the store's own answers matter (one Undo for a put back with its cards, the pin kept through finishing, the cards' flag,
the import's copies and its Undo, a drop on the tab, a past Graduate) on a real migrated store with the real writer.

What a wrong answer would cost a learner:
  * a show put back without its cards (or its cards without the show), or an Undo that takes back only half (IK-1);
  * a pin lost when it was finished, or ⋯ showing the opposite of what the store holds (E23);
  * *What if…* moving something, counting a word once per episode, or showing an error where it can't count;
  * an import that can't be stopped or undone, or files dropped on Finished landing at the top of Current;
  * the keyboard not reaching what the hand reaches (hover and focus showing different things);
  * every Finished row repainted for a view that changed nothing (N9).
"""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from app import library_store as ls
from app.qt import drag, finished, rows, strings
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, open_window, press, real, release, settle  # noqa: F401 (real: a fixture)
from tests.qt.test_wiring import problems
from tests.test_library_store_support import names, roots, touch


# --- a recording writer with Finished's commands -------------------------------------------------------------------- #
class FinWriter(FakeWriter):
    def put_back(self, ids, label=None):
        return self._put("put_back", ids, label)

    def pin(self, ids, on=True, label=None):
        return self._put("pin", ids, label, on=on)

    def keep_cards(self, ids, on, label=None):
        return self._put("keep_cards", ids, label, on=on)

    def import_finished(self, paths, copied=(), label=None):
        return self._put("import_finished", [], label, paths=list(paths), copied=list(copied))


class FakeEstimator:
    """The arrivals worker's `estimate` as Finished asks it: every request recorded; `answer(k, …)` answers request `k`
    on a thread of its own, as the worker's reader thread does."""

    def __init__(self):
        self.asked = []

    def __call__(self, path, placed, callback):
        self.asked.append((path, placed, callback))
        return len(self.asked)

    def answer(self, k, value):
        threading.Thread(target=self.asked[k][2], args=(value,), daemon=True).start()


@pytest.fixture
def fin(qapp):
    made = []

    def make(writable=True):
        from tests.fixtures import window_seed
        seed = window_seed.build()
        writer = FinWriter(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
        estimator = FakeEstimator()
        win.finished.estimator = estimator
        win.show_tab("finished")
        page = win.page_widgets["finished"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.finished, 10)
        settle()
        made.append((win, services))
        return seed, win, writer, estimator
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def lst_of(win):
    return win.page_widgets["finished"].list


def finished_rows(win):
    return [(i, e[1]) for i, e in enumerate(lst_of(win).model().entries) if e[0] == rows.FINISHED]


def part(lst, i, name):
    entry = lst.model().entries[i]
    return next(p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))) if p[0] == name)


def click(lst, pos):
    press(lst, pos)
    release(lst, pos)


def calls(writer, op=None):
    return [c for c in writer.calls if op is None or c[0] == op]


# --- the row: hover and keyboard focus ------------------------------------------------------------------------------ #
def _paint(lst, i, state, focused=False):
    idx = lst.model().index(i, 0)
    rect = lst.visualRect(idx)
    img = QImage(rect.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.translate(-rect.topLeft())
    opt = QStyleOptionViewItem()
    opt.rect = rect
    opt.state = state
    lst.focus_visible = focused
    lst.delegate.paint(p, opt, idx)
    p.end()
    return img, rect


def test_hover_and_keyboard_focus_show_the_same_put_back_and_more(fin, monkeypatch):
    # S7: the keyboard reaches what the hand reaches — the focused row paints the hover's Put back and ⋯
    _seed, win, _w, _e = fin()
    lst = lst_of(win)
    i, _row = finished_rows(win)[0]
    monkeypatch.setattr(lst, "hasFocus", lambda: True)
    rest, rect = _paint(lst, i, QStyle.StateFlag.State_Enabled)
    hover, _r = _paint(lst, i, QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver)
    focus, _r = _paint(lst, i, QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_HasFocus, focused=True)
    back = part(lst, i, "put-back")[1].translated(-rect.topLeft()).adjusted(3, 3, -3, -3)
    more = part(lst, i, "more")[1].translated(-rect.topLeft()).adjusted(3, 3, -3, -3)
    for r in (back, more):
        hov, foc, at_rest = hover.copy(r), focus.copy(r), rest.copy(r)
        assert hov == foc                                               # the same button, by hand or by key
        assert hov != at_rest                                           # and not there at rest
    assert win.page_widgets["finished"].list.delegate.renders > 0


def test_every_part_of_a_finished_row_has_a_tooltip_and_the_window_stays_wired(fin):
    _seed, win, _w, _e = fin()
    lst = lst_of(win)
    i, _row = finished_rows(win)[0]
    entry = lst.model().entries[i]
    tips = {p[0]: p[2] for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0)))}
    assert tips["put-back"] == strings.FIN_PUT_BACK_TIP and tips["more"] == strings.FIN_MORE_TIP
    assert strings.FIN_PUT_BACK_TIP.startswith(strings.FIN_PUT_BACK)    # the button names itself first (A2 #118)
    page = win.page_widgets["finished"]
    assert page.importer.isVisible() and page.importer.toolTip() == strings.FIN_IMPORT_TIP
    win.finished.what_if(finished_rows(win)[0][1])                     # the card's controls join the walk
    found, _n = problems(win)
    assert found == []


def test_put_back_on_hover_puts_its_files_back_with_one_toast_and_its_undo(fin):
    _seed, win, writer, _e = fin()
    lst = lst_of(win)
    i, row = finished_rows(win)[0]
    click(lst, part(lst, i, "put-back")[1].center())
    assert calls(writer, "put_back") == [("put_back", drag.ids_of(row), {})]
    assert wait_until(lambda: win.toasts.card.message == strings.FIN_PUT_BACK_DONE.format(title=row.title), 3)
    change = writer.saved[-1]
    win.toasts.card.buttons[0].click()                                  # Undo
    assert wait_until(lambda: writer.undone == [change], 3)


def test_the_more_button_and_the_keyboard_open_the_same_menu(fin):
    _seed, win, _w, _e = fin()
    lst = lst_of(win)
    i, row = finished_rows(win)[0]
    click(lst, part(lst, i, "more")[1].center())
    by_hand = [a.text() for a in win.finished.last_menu.actions()]
    win.finished.last_menu.close()
    win.finished.last_menu = None
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    QTest.keyClick(lst, Qt.Key.Key_Return)
    assert win.finished.last_menu is not None
    assert [a.text() for a in win.finished.last_menu.actions()] == by_hand
    assert by_hand[:2] == [strings.FIN_MENU["what-if"][0], strings.FIN_MENU["put-back"][0]]
    win.finished.last_menu.close()


def test_the_menu_shows_the_state_the_store_holds_pin_and_cards(fin):
    # E23: a finished row pinned shows *Done with its cards*; one without shows *Study its cards first*; the cards'
    # entry names the count and offers the opposite of the row's flag
    _seed, win, writer, _e = fin()
    fa = win.finished
    rs = [r for _i, r in finished_rows(win)]
    pinned = next(r for r in rs if r.studying)
    plain = next(r for r in rs if not r.studying and sum(e.cards for e in r.episodes))
    names_of = lambda r: [e[0] for e in fa.menu_entries(r)]           # noqa: E731
    assert "unpin" in names_of(pinned) and "pin" not in names_of(pinned)
    assert "pin" in names_of(plain)
    cards = next(e for e in fa.menu_entries(plain) if e[0] == "cards")
    n = sum(e.cards for e in plain.episodes)
    assert cards[1] == strings.FIN_MENU["cards"][0].format(n=f"{n:,}")
    assert [c[0] for c in cards[4]] == ["cards-out"]
    assert [c[0] for c in next(e for e in fa.menu_entries(plain._replace(cards_out=True))
                               if e[0] == "cards")[4]] == ["cards-in"]
    assert "mine" not in names_of(plain) and "mine-too" not in names_of(plain)      # P4.1's, hidden until wired
    fa.on_mine_too = lambda r: None
    assert "mine-too" in names_of(plain)


def test_each_menu_entry_reaches_the_writer_with_its_op(fin):
    _seed, win, writer, _e = fin()
    fa = win.finished
    row = finished_rows(win)[0][1]
    ids = drag.ids_of(row)
    for name in ("put-back", "pin", "unpin", "cards-out", "cards-in"):
        fa.menu_pick(row, name)
    assert [(c[0], c[2].get("on")) for c in writer.calls] == [("put_back", None), ("pin", True), ("pin", False),
                                                              ("keep_cards", False), ("keep_cards", True)]
    assert all(c[1] == ids for c in writer.calls)


def test_E4_a_read_only_store_greys_the_writes_with_its_reason_and_writes_nothing(fin):
    _seed, win, writer, _e = fin(writable=False)
    fa = win.finished
    row = finished_rows(win)[0][1]
    entries = {e[0]: e for e in fa.menu_entries(row)}
    assert not entries["put-back"][3] and not entries["pin"][3]
    assert entries["what-if"][3] and entries["folder"][3]              # reading and looking still work
    assert entries["put-back"][2].startswith(strings.FIN_REFUSED_TIP.split("{")[0])
    fa.put_back(row)
    fa.pin(row, True)
    assert writer.calls == []


def test_open_its_folder_opens_the_folder_its_files_are_in(fin, monkeypatch):
    _seed, win, _w, _e = fin()
    row = finished_rows(win)[0][1]
    opened = []
    monkeypatch.setattr(finished.windows, "open_url", opened.append)
    folder = finished.folder_of("ja", row)
    os.makedirs(folder, exist_ok=True)
    win.finished.menu_pick(row, "folder")
    assert wait_until(lambda: opened == [folder], 3)
    assert folder.endswith(os.path.dirname(row.episodes[0].rel_path).replace("/", os.sep))


def test_open_its_folder_says_so_when_the_folder_is_gone(fin, monkeypatch):
    _seed, win, _w, _e = fin()
    row = finished_rows(win)[1][1]
    opened = []
    monkeypatch.setattr(finished.windows, "open_url", opened.append)
    win.finished.menu_pick(row, "folder")
    assert wait_until(lambda: win.bar_line.full() == strings.FIN_NO_FOLDER.format(title=row.title), 3)
    assert opened == []


# --- What if I added it back? --------------------------------------------------------------------------------------- #
def _answer(words, known, counted, n_top=5):
    return {"words": [list(w) for w in words], "n_new_top": n_top, "known": known, "counted": counted,
            "known_pct": round(known / counted * 100, 2)}


def test_what_if_shows_a_dash_at_once_then_its_numbers_and_first_new_words_and_moves_nothing(fin):
    _seed, win, writer, est = fin()
    fa = win.finished
    row = next(r for _i, r in finished_rows(win) if len(r.episodes) >= 3)
    fa.menu_pick(row, "what-if")
    card = fa.card
    assert card.isVisible()
    assert card.line.text() == strings.WHATIF_LINE.format(n="—", pct="—")      # at once, a dash while it counts
    assert len(est.asked) == len(row.episodes)
    # IK-5: each file asked with the earlier ones placed, the first at the top of NOW, each after the one before it
    files = finished.file_paths("ja", row)
    assert [a[0] for a in est.asked] == [f[0] for f in files]
    assert est.asked[0][1] == []
    assert est.asked[2][1] == [{"path": files[0][0], "tier": "now", "before": None, "after": None},
                               {"path": files[1][0], "tier": "now", "before": None, "after": files[0][1]}]
    words = [("海辺", "うみべ"), ("図書室", "としょしつ"), ("灯台", "とうだい")]
    est.answer(0, _answer(words[:2], 80, 100))
    settle()
    assert card.line.text() == strings.WHATIF_LINE.format(n="—", pct="—")      # not until every file answered
    est.answer(1, _answer(words[1:], 90, 100))                                   # 図書室 again: one new word
    for k in range(2, len(row.episodes)):
        est.answer(k, _answer([], 100, 100))
    total = 100 * len(row.episodes)
    known = 80 + 90 + 100 * (len(row.episodes) - 2)
    assert wait_until(lambda: card.line.text() == strings.WHATIF_LINE.format(
        n="3", pct=strings.WHATIF_PCT.format(pct=round(known / total * 100))), 3)
    assert card.words.text() == strings.WHATIF_WORDS.format(words="海辺（うみべ） · 図書室（としょしつ） · 灯台（とうだい）")
    assert writer.calls == []                                                  # nothing moves


def test_what_if_cards_numbers_from_answers_count_a_word_once_and_show_twenty(fin):
    many = [(f"言葉{n}", f"ことば{n}") for n in range(30)]
    out = finished.what_if_numbers([_answer(many[:15], 1, 2), _answer(many[10:], 1, 2)])
    assert out["n"] == 30 and out["pct"] == 50 and out["state"] == "ok"
    assert out["words"] == [list(w) for w in many[:20]]                       # the first 20, in the order met
    assert finished.what_if_numbers([None, {"error": "stopped"}]) == {"n": None, "pct": None, "words": [],
                                                                       "state": "none"}
    no_plan = finished.what_if_numbers([{"words": [], "n_new_top": None, "known": 3, "counted": 4,
                                         "reason": "no-plan"}])
    assert no_plan == {"n": None, "pct": 75, "words": [], "state": "no-plan"}
    assert finished.what_if_numbers([_answer([], 5, 5)])["state"] == "ok"
    assert finished.word_text("灯台", "とうだい") == "灯台（とうだい）" and finished.word_text("ガラス", "ガラス") == "ガラス"


def test_what_if_says_it_cant_count_when_the_worker_fails_never_an_error(fin):
    _seed, win, _w, est = fin()
    row = finished_rows(win)[0][1]
    win.finished.what_if(row)
    for k in range(len(est.asked)):
        est.answer(k, {"error": "the arrivals worker was stopped"})
    assert wait_until(lambda: win.finished.card.words.text() == strings.WHATIF_NONE, 3)
    assert win.finished.card.line.text() == strings.WHATIF_LINE.format(n="—", pct="—")


def test_what_if_an_older_cards_late_answer_is_dropped(fin):
    _seed, win, _w, est = fin()
    a, b = finished_rows(win)[0][1], finished_rows(win)[1][1]
    win.finished.what_if(a)
    first = len(est.asked)
    win.finished.what_if(b)
    for k in range(first):                                                     # a's answers land after b was asked
        est.answer(k, _answer([("海辺", "うみべ")], 1, 1))
    settle(120)
    assert win.finished.card.row.key == b.key
    assert win.finished.card.line.text() == strings.WHATIF_LINE.format(n="—", pct="—")


def test_what_ifs_put_back_and_journey_buttons_act_and_close_it(fin, monkeypatch):
    _seed, win, writer, _e = fin()
    row = finished_rows(win)[0][1]
    fa = win.finished
    fa.what_if(row)
    fa.card.put_back.click()
    assert not fa.card.isVisible()
    assert calls(writer, "put_back") == [("put_back", drag.ids_of(row), {})]
    asked = []
    monkeypatch.setattr(win, "_open_journey", lambda *a, **kw: asked.append(kw))
    fa.what_if(row)
    fa.card.journey.click()
    assert asked == [{"asked": True}] and not fa.card.isVisible()


def test_what_if_closes_on_esc_and_on_a_click_outside(fin):
    _seed, win, writer, _e = fin()
    fa = win.finished
    row = finished_rows(win)[0][1]
    fa.what_if(row)
    assert fa.card.isVisible()
    QTest.keyClick(fa.card, Qt.Key.Key_Escape)
    assert not fa.card.isVisible()
    fa.what_if(row)
    assert fa.card.isVisible()
    header = win.header
    QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert not fa.card.isVisible()
    assert writer.calls == []


# --- N9: nothing repaints on an unchanged view ---------------------------------------------------------------------- #
def test_N9_an_unchanged_view_repaints_no_finished_row(fin):
    _seed, win, _w, _e = fin()
    page = win.page_widgets["finished"]
    lst = page.list
    lst.viewport().repaint()
    renders = lst.delegate.renders
    view = page.view_model
    assert page.set_view(view._replace(finished=tuple(m for m in view.finished))) == "same"
    lst.viewport().repaint()
    assert lst.delegate.renders == renders


def test_N9_a_row_whose_cards_flag_alone_changed_keeps_its_picture(fin):
    _seed, win, _w, _e = fin()
    lst = lst_of(win)
    i, row = finished_rows(win)[0]
    assert rows._same_face(row, row._replace(cards_out=not row.cards_out), rows.FINISHED)


# --- the importer and Explorer's files -------------------------------------------------------------------------------- #
_MIMES = []                                          # Qt's drag events hold their data by pointer: kept alive here


def _drop_event(target, paths, pos, kind):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    _MIMES.append(mime)
    if kind == "enter":
        return QDragEnterEvent(pos, Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
                               Qt.KeyboardModifier.NoModifier)
    return QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier)


def _drop_on(target, paths):
    pos = target.rect().center()
    enter = _drop_event(target, paths, pos, "enter")
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted()
    drop = _drop_event(target, paths, pos, "drop")
    QApplication.sendEvent(target, drop)
    return drop


def test_files_dropped_on_the_finished_tab_and_list_go_through_the_importer(fin, monkeypatch, tmp_path):
    # lean 8: Explorer's files on Finished are what you finished before — never the top of Current
    _seed, win, writer, _e = fin()
    src = tmp_path / "海辺の図書室 第01話.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\n海辺で本を読む\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(win.finished, "import_paths", lambda paths: seen.append(paths) or object())
    _drop_on(win.tab_buttons["finished"], [str(src)])
    _drop_on(lst_of(win).viewport(), [str(src)])
    assert seen == [[os.path.normpath(str(src))]] * 2
    assert calls(writer, "insert_at") == []


def test_the_importers_button_offers_files_or_a_folder_and_the_choice_starts_the_job(fin, monkeypatch, tmp_path):
    _seed, win, _w, _e = fin()
    fa = win.finished
    seen = []
    monkeypatch.setattr(fa, "import_paths", seen.append)
    win.page_widgets["finished"].importer.click()
    m = fa.last_menu
    assert [a.text() for a in m.actions()] == [strings.FIN_IMPORT_FILES[0], strings.FIN_IMPORT_FOLDER[0]]
    assert all(a.toolTip() for a in m.actions())
    m.close()
    monkeypatch.setattr(finished.QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    monkeypatch.setattr(finished.QFileDialog, "getOpenFileNames", lambda *a: ([str(tmp_path / "a.srt")], ""))
    fa._choose("folder")
    fa._choose("files")
    assert seen == [[str(tmp_path)], [str(tmp_path / "a.srt")]]


# ================================================================================================================== #
# The real store: the writer, the reader and the importer on one store
# ================================================================================================================== #
def _fin_rows(win):
    page = win.page_widgets["finished"]
    return [r for m in (page.view_model.finished if page.view_model else ()) for r in m.rows]


def _fin_row(win, ids):
    return next((r for r in _fin_rows(win) if drag.ids_of(r) == list(ids)), None)


def _finish_outside(store, win, row, keep_cards=False, pin=False):
    """Finish a Current row from outside (another program), then wait for its Finished row."""
    ids = drag.ids_of(row)
    if pin:
        store.pin(ids)
    store.finish(ids, keep_cards=keep_cards)
    assert wait_until(lambda: _fin_row(win, ids) is not None, 10)
    return ids


def test_real_store_put_back_brings_it_and_its_cards_back_and_one_undo_takes_both_back(real):
    store, win, writer = real()
    row = win.page_widgets["current"].view_model.rows[2]
    ids = _finish_outside(store, win, row, keep_cards=False)
    assert all(store.item(i)["in_learning_order"] == 0 for i in ids)
    win.finished.put_back(_fin_row(win, ids))
    assert wait_until(lambda: store.ids("now")[:len(ids)] == ids, 5)        # at the top of Current
    assert all(store.item(i)["in_learning_order"] == 1 for i in ids)       # and its cards back in the order
    assert wait_until(lambda: win.toasts.card.message == strings.FIN_PUT_BACK_DONE.format(title=row.title), 5)
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.toasts.card.buttons[0].click()                                      # one Undo
    assert wait_until(lambda: all(store.item(i)["tier"] == "graduated" for i in ids), 5)
    assert all(store.item(i)["in_learning_order"] == 0 for i in ids)


def test_real_store_E23_a_pin_kept_through_finishing_shows_done_with_its_cards_and_ends_from_there(real):
    store, win, writer = real()
    row = win.page_widgets["current"].view_model.rows[1]
    ids = _finish_outside(store, win, row, keep_cards=True, pin=True)
    fin_row = _fin_row(win, ids)
    assert fin_row.studying                                                 # E23: finishing kept the pin
    assert "unpin" in [e[0] for e in win.finished.menu_entries(fin_row)]
    win.finished.menu_pick(fin_row, "unpin")
    assert wait_until(lambda: all(store.item(i)["pinned"] is None for i in ids), 5)
    assert wait_until(lambda: not _fin_row(win, ids).studying, 5)
    win.finished.menu_pick(_fin_row(win, ids), "pin")
    assert wait_until(lambda: all(store.item(i)["pinned"] is not None for i in ids), 5)


def test_real_store_leave_its_new_cards_out_then_put_them_back_shows_the_state_it_holds(real):
    store, win, writer = real()
    row = win.page_widgets["current"].view_model.rows[3]
    ids = _finish_outside(store, win, row, keep_cards=True)
    fin_row = _fin_row(win, ids)
    assert not fin_row.cards_out
    win.finished.menu_pick(fin_row, "cards-out")
    assert wait_until(lambda: all(store.item(i)["in_learning_order"] == 0 for i in ids), 5)
    assert wait_until(lambda: _fin_row(win, ids).cards_out, 5)
    sub = next(e for e in win.finished.menu_entries(_fin_row(win, ids)) if e[0] == "cards")[4]
    assert [c[0] for c in sub] == ["cards-in"]
    win.finished.menu_pick(_fin_row(win, ids), "cards-in")
    assert wait_until(lambda: all(store.item(i)["in_learning_order"] == 1 for i in ids), 5)


def _a_show_folder(tmp_path, n=3):
    show = names("ja")[40]
    folder = tmp_path / show
    folder.mkdir()
    for e in range(1, n + 1):
        (folder / f"[Group] {show} - {e:02d} (1080p).ja.srt").write_text(
            f"1\n00:00:01,000 --> 00:00:02,000\n{show}の{e}話\n", encoding="utf-8")
    return folder


def test_real_store_the_importer_adds_a_folder_to_finished_toasts_and_its_undo_trashes_only_its_copies(real, tmp_path):
    store, win, writer = real()
    folder = _a_show_folder(tmp_path)
    before = len(store.ids("graduated"))
    job = win.finished.import_paths([str(folder)])
    assert job is not None
    assert win.page_widgets["finished"].importer.text() == strings.FIN_IMPORT_STOP
    assert wait_until(lambda: win.finished.import_job is None, 15)
    assert win.page_widgets["finished"].importer.text() == strings.FIN_IMPORT
    assert wait_until(lambda: len(store.ids("graduated")) == before + 3, 10)
    assert wait_until(lambda: win.toasts.card.message == strings.FIN_IMPORTED.format(n="3"), 5)
    copies = [os.path.join(store.data_dir, *store.item(i)["rel_path"].split("/"))
              for i in store.ids("graduated")[-3:]]
    assert all(os.path.exists(p) for p in copies)
    assert all(store.item(i)["graduated_at"] is None for i in store.ids("graduated")[-3:])   # dated Earlier
    assert wait_until(lambda: not win.moves.tickets and writer.pending() == 0, 5)
    win.toasts.card.buttons[0].click()                                      # Undo
    assert wait_until(lambda: len(store.ids("graduated")) == before, 10)
    assert not any(os.path.exists(p) for p in copies)                      # the copies to the trash
    assert all((folder / n).exists() for n in os.listdir(folder))          # the user's own files untouched


def test_real_store_the_same_folder_imported_again_says_nothing_new_never_added(real, tmp_path):
    store, win, writer = real()
    folder = _a_show_folder(tmp_path)
    win.finished.import_paths([str(folder)])
    assert wait_until(lambda: win.toasts.card.message == strings.FIN_IMPORTED.format(n="3"), 15)
    after = len(store.ids("graduated"))
    win.toasts.close()
    assert wait_until(lambda: win.finished.import_job is None and writer.pending() == 0, 10)
    win.finished.import_paths([str(folder)])
    assert wait_until(lambda: win.bar_line.full() == strings.FIN_IMPORT_NOTHING, 15)
    assert len(store.ids("graduated")) == after
    assert not win.toasts.shown                                             # no *Added 3* for what it already held


def test_real_store_the_importer_stops_when_asked_and_adds_nothing(real, tmp_path, monkeypatch):
    store, win, writer = real()
    folder = _a_show_folder(tmp_path)
    before = len(store.ids("graduated"))
    started = threading.Event()

    def slow_copy(data_dir, sources, progress=None, cancel=None):
        started.set()
        deadline = time.monotonic() + 10
        while not cancel() and time.monotonic() < deadline:
            time.sleep(0.01)
        return []
    monkeypatch.setattr(ls, "copy_into_finished", slow_copy)
    assert win.finished.import_paths([str(folder)]) is not None
    assert started.wait(5)
    win.page_widgets["finished"].importer.click()                           # *Stop adding*
    assert wait_until(lambda: win.finished.import_job is None, 10)
    assert wait_until(lambda: win.bar_line.full() == strings.FIN_IMPORT_STOPPED, 5)
    assert len(store.ids("graduated")) == before


def test_real_store_files_dropped_on_the_finished_tab_land_in_finished_not_current(real, tmp_path):
    store, win, writer = real()
    folder = _a_show_folder(tmp_path, n=1)
    src = str(next(folder.iterdir()))
    now = list(store.ids("now"))
    _drop_on(win.tab_buttons["finished"], [src])
    assert wait_until(lambda: any(store.item(i)["rel_path"].endswith(os.path.basename(src))
                                  for i in store.ids("graduated")), 15)
    assert store.ids("now") == now


def test_real_store_a_past_graduate_from_2x_is_a_row_like_any_and_puts_back_the_same(real):
    # 2.x's graduated items (its Graduated folder, dated Earlier by the migration) are Finished rows like any
    data_dir, _u = roots("ja")
    show = names("ja")[50]
    rels = [f"Graduated/{show}/{show}_第{e:02d}話.srt" for e in (1, 2)]
    for rel in rels:
        touch(data_dir, rel, f"{show}\n")
    store, win, writer = real()
    page = win.page_widgets["finished"]
    assert wait_until(lambda: any(r.title == show for r in _fin_rows(win)), 10)
    row = next(r for r in _fin_rows(win) if r.title == show)
    last = page.view_model.finished[-1]
    assert last.label == view_rows.STRINGS["earlier"] and row in last.rows  # *Earlier*, last
    ids = drag.ids_of(row)
    win.finished.put_back(row)
    assert wait_until(lambda: store.ids("now")[:len(ids)] == ids, 5)
