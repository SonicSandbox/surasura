"""Settings' *Sort again or start over…* sheet (Fresh library 3.0.1, WP4; the spec §3.1, §3.3–3.4, §8; replaces K7's one
confirm, `app/qt/settings_sources.py` FreshRow / StartOverRow / FreshSheet / `act`): its two doors, its two choices,
its Backups list (on a worker), and what each press hands on — the work itself is the looks' (test_resort.py) and the
start gate's (test_start_gate_move.py).

What a wrong answer would cost a learner:
  * a library set aside by a click he meant as Close (Esc, a click outside, Back);
  * a Start over that restarts with nothing written, or writes the request and never restarts (asked next start);
  * a Backups list that names the wrong backup, hides one a crash stopped, or never says a 3.0 backup's known words
    stay as they are now (P9);
  * a sheet that waits on a slow folder before it opens (the listing is a worker's).

The window over its seed (test_window_sources' `window`), recorded looks; backups made as files in the test's own root
(their records as the stores write them).
"""
import json
import os
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QLabel as QLabel_, QPushButton as QPushButton_

from app import library_store as ls
from app import path_utils, profile_reset
from app.qt import confirm, first_run, settings_sources
from app.qt import shell as shell_module
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_drag import _stones_sheet  # noqa: F401  (the stones' sheet fixture)
from tests.qt.test_window_sources import RecordingLooks, _fresh_run, window  # noqa: F401


class SheetLooks(RecordingLooks):
    """The looks as the sheet asks them: its counts (`fresh_counts`), `fresh` and `put_back` recorded and answered as
    told."""

    def __init__(self, counts=None, answer=None, put_back_answer=None):
        super().__init__()
        self.counts = counts
        self.answer = answer or {"done": True, "known": "kept", "backup": "B"}
        self.put_back_answer = put_back_answer
        self.fresh_calls, self.put_backs = [], []

    def fresh_counts(self, then):
        then(dict(self.counts) if self.counts is not None else None)
        return True

    def fresh(self, then=None, folders=None, progress=None, stop=None, scanned=None):
        self.fresh_calls.append(folders)
        then(dict(self.answer))
        return True

    def put_back(self, folder, then=None):
        self.put_backs.append(folder)
        then(dict(self.put_back_answer or {"done": True, "backup": folder + "-over", "put_back": folder}))
        return True


def _rows(win):
    page = win.mount_settings()
    assert wait_until(lambda: page.findChildren(settings_sources.SourcesRow), 10)
    row = page.findChildren(settings_sources.SourcesRow)[0]
    return page, row.fresh, row.start_over


def _sheet(card):
    assert wait_until(lambda: card.sheet.backups is not None, 10)        # the worker's list landed
    return card.sheet


def _sorted_again(language, stamp, stopped=False, **record):
    """A Sorted-again backup as `start_fresh` leaves it (`reset.json`, a store copy); `stopped`: one a kill left
    "started" after its first move (that move's `to` there)."""
    folder = os.path.join(path_utils.get_user_files_path(language), ".trash", ls.RESET_PREFIX + stamp)
    os.makedirs(folder, exist_ok=True)
    if stopped:
        os.makedirs(os.path.join(folder, "Library"), exist_ok=True)
        record.update(status="started", moves=[{"step": "data", "rel": "Library", "from": "Library",
                                                "to": os.path.join(folder, "Library")}])
    with open(os.path.join(folder, "library.db"), "wb") as f:
        f.write(b"x" * 2048)
    rec = {"status": "done", "language": language, "started_at": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T"
           f"{stamp[9:11]}:{stamp[11:13]}:00", "moves": [], "store_copy": "library.db", "known": "kept"}
    rec.update(record)
    with open(os.path.join(folder, ls.RESET_RECORD), "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return folder


def test_two_doors_open_one_sheet_each_with_its_own_choice_first_and_close_does_nothing(window):
    looks = SheetLooks()
    seed, win = window(looks)
    page, fresh, over = _rows(win)
    assert fresh.button.text() == S.FRESH_OPEN and fresh.button.toolTip() == S.FRESH_TIP
    assert over.button.text() == S.START_OVER_OPEN and over.button.toolTip() == S.START_OVER_TIP
    t = time.perf_counter()
    card = fresh.ask()
    opened_ms = (time.perf_counter() - t) * 1000
    sheet = card.sheet
    assert card.title.text() == S.FRESH_SHEET and card.yes is None and card.default is card.no
    lay = card.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]
    assert order.index(sheet.sort_part) < order.index(sheet.over_part)   # Content's door: Sort again first
    assert sheet.looking.text() == S.FRESH_LOOKING                        # until the worker's list lands
    assert opened_ms < 250, f"the sheet opens at once (the listing is a worker's): {opened_ms:.1f} ms"
    for b in (sheet.btn_sort, sheet.btn_folders, sheet.btn_over, card.no):
        assert b.toolTip() and b.text()
    _sheet(card)
    assert not sheet.backups_part.isVisibleTo(card)                      # none: the part is hidden
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)       # Esc: nothing happens
    assert card.answer is False and looks.fresh_calls == [] and fresh.card is None
    card = over.ask()
    lay = card.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]
    assert order.index(card.sheet.over_part) < order.index(card.sheet.sort_part)   # App's door: Start over first
    card.no.click()
    assert looks.fresh_calls == []


def test_the_counts_say_what_never_comes_back_and_the_cards_left_suspended_on_their_sides(window):
    looks = SheetLooks(counts={"added": 3, "youtube": 1, "other": 0, "suspended": 4})
    seed, win = window(looks)
    _page, fresh, _over = _rows(win)
    card = fresh.ask()
    sheet = _sheet(card)
    assert sheet.counts_line.text() == S.FRESH_GONE.format(parts=", ".join((S.FRESH_GONE_ADDED.format(n=3, s="s"),
                                                                            S.FRESH_GONE_YOUTUBE.format(n=1, s=""))))
    assert sheet.suspended_line.text() == S.FRESH_SUSPENDED_OVER.format(n=4, s="s")
    card.no.click()
    looks.counts = {"added": 0, "youtube": 0, "other": 0, "suspended": 0}
    card = fresh.ask()
    sheet = _sheet(card)
    assert sheet.counts_line.isHidden() and sheet.suspended_line.isHidden()
    card.no.click()


def test_connect_on_says_the_top_twenty_get_cards_off_says_nothing(window):
    # FL-1: re-sorting behaves like sorting by hand — and says so on the Sort again side
    looks = SheetLooks()
    seed, win = window(looks)
    _page, fresh, _over = _rows(win)
    win.services.settings.set({"connect_enabled": True})
    card = fresh.ask()
    assert card.sheet.cards_line.text() == S.FRESH_SORT_CARDS and not card.sheet.cards_line.isHidden()
    card.no.click()
    win.services.settings.set({"connect_enabled": False})
    card = fresh.ask()
    assert card.sheet.cards_line.isHidden()
    card.no.click()


def test_sort_again_closes_the_sheet_and_starts_the_load_over_the_window(window):
    looks = SheetLooks()
    seed, win = window(looks)
    _page, fresh, _over = _rows(win)
    card = fresh.ask()
    card.sheet.btn_sort.click()
    assert card.answer is True and looks.fresh_calls == [None]
    assert settings_sources.running(win) == S.FRESH_RUNNING_TIP
    assert fresh.why_not() == S.FRESH_RUNNING_TIP and not fresh.button.isEnabled() or fresh.running
    assert fresh.ask() is None, "one at a time"


def test_change_folders_opens_the_folders_page_alone_and_back_opens_the_sheet_again(window, monkeypatch):
    looks = SheetLooks()
    seed, win = window(looks)
    _page, fresh, _over = _rows(win)
    opened = []

    class Wiz:
        def __init__(self):
            from PyQt6.QtCore import QObject, pyqtSignal

            class Sig(QObject):
                finished = pyqtSignal(str)
            self.sig = Sig()
            self.finished = self.sig.finished
    wiz = Wiz()
    monkeypatch.setattr(first_run, "open_again", lambda shell, resort=None: opened.append(resort) or wiz)
    card = fresh.ask()
    card.sheet.btn_folders.click()
    assert len(opened) == 1 and looks.fresh_calls == []                 # nothing changed until its Next
    wiz.finished.emit("later")                                         # Back: the sheet again
    again = [c for c in confirm._OPEN if getattr(c, "sheet", None) is not None]
    assert again and again[-1] is not card
    again[-1].no.click()
    opened[0]({"add": ["D:/Dramas"], "stop": [3], "skip": []})          # its Next: Sort again with the changes
    assert looks.fresh_calls == [{"add": ["D:/Dramas"], "stop": [3], "skip": []}]


def test_without_a_library_sort_again_is_greyed_with_why_and_start_over_still_opens(window):
    seed, win = window(None)
    _page, fresh, over = _rows(win)
    assert not fresh.button.isEnabled() and fresh.button.toolTip() == S.STORE_NO_LIBRARY_TIP
    assert fresh.ask() is None
    card = over.ask()
    assert card is not None and not card.sheet.btn_sort.isEnabled() and card.sheet.btn_over.isEnabled()
    assert card.sheet.btn_sort.toolTip() == S.STORE_NO_LIBRARY_TIP
    card.no.click()


def test_start_over_asks_once_more_then_writes_the_request_and_restarts(window, monkeypatch):
    looks = SheetLooks()
    seed, win = window(looks)
    _page, _fresh, over = _rows(win)
    restarts = []
    monkeypatch.setattr(type(win), "restart", lambda self, move=False: restarts.append(move))
    monkeypatch.setattr(shell_module, "relaunch_refused", lambda argv=None: None)
    card = over.ask()
    card.sheet.btn_over.click()
    step = confirm._OPEN[-1]
    assert step.title.text() == S.FRESH_OVER_ASK and step.default is step.no and step.no.text() == S.FRESH_BACK
    step.no.click()                                                      # Back: nothing written
    assert profile_reset.pending() is None and restarts == []
    over.ask().sheet.btn_over.click()
    confirm._OPEN[-1].yes.click()
    journal = profile_reset.pending()
    assert journal["action"] == profile_reset.START_OVER and journal["status"] == profile_reset.ASKED
    assert restarts == [True]
    profile_reset.cancel_request()


def test_start_over_that_cant_restart_or_is_refused_says_so_and_writes_nothing(window, monkeypatch):
    looks = SheetLooks()
    seed, win = window(looks)
    restarts = []
    monkeypatch.setattr(type(win), "restart", lambda self, move=False: restarts.append(move))
    monkeypatch.setattr(shell_module, "relaunch_refused", lambda argv=None: "Surasura.exe isn't there")
    assert settings_sources.start_over(win) is False
    assert win.bar_line.full() == S.FRESH_RESTART_FAILED.format(why="Surasura.exe isn't there")
    assert profile_reset.pending() is None and restarts == []
    monkeypatch.setattr(shell_module, "relaunch_refused", lambda argv=None: None)
    monkeypatch.setattr(ls, "update_staged", lambda: True)
    assert settings_sources.start_over(win) is False
    assert win.bar_line.full() == profile_reset.REFUSED_UPDATE and restarts == []
    assert profile_reset.pending() is None


def test_the_backups_list_five_then_show_all_a_stopped_one_first_with_put_it_back(window):
    looks = SheetLooks()
    seed, win = window(looks)
    lang = win.language
    for day in range(1, 8):
        _sorted_again(lang, f"202610{day:02d}-120000")
    stopped = _sorted_again(lang, "20260920-090000", stopped=True)
    _page, fresh, _over = _rows(win)
    card = fresh.ask()
    sheet = _sheet(card)
    assert len(sheet.backups) == 8 and len(sheet.row_widgets) == 5
    first = sheet.row_widgets[0].findChildren(QLabel_)[0].text()
    assert S.FRESH_STOPPED in first and sheet.backups[0]["folder"] == stopped
    labels = [b.text() for b in sheet.row_widgets[0].findChildren(QPushButton_)]
    assert labels == [S.FRESH_PUT_IT_BACK, S.FRESH_SHOW]
    assert [b.text() for b in sheet.row_widgets[1].findChildren(QPushButton_)] == [S.FRESH_PUT_BACK, S.FRESH_SHOW]
    assert sheet.btn_all.isVisibleTo(card) and sheet.btn_all.text() == S.FRESH_SHOW_ALL.format(n=8)
    assert wait_until(lambda: S.FRESH_SIZE_WAIT not in sheet.row_widgets[1].findChildren(QLabel_)[0].text(), 10)
    assert "MB" in sheet.row_widgets[1].findChildren(QLabel_)[0].text()   # its size, from the worker
    sheet.btn_all.click()
    assert len(sheet.row_widgets) == 8 and not sheet.btn_all.isVisibleTo(card)
    card.no.click()


def test_put_back_confirms_with_its_date_then_the_looks_put_it_back_and_the_toast_offers_undo(window):
    looks = SheetLooks()
    seed, win = window(looks)
    folder = _sorted_again(win.language, "20261030-154000")
    _page, fresh, _over = _rows(win)
    card = fresh.ask()
    sheet = _sheet(card)
    sheet.row_widgets[0].findChildren(QPushButton_)[0].click()
    ask = confirm._OPEN[-1]
    assert ask.title.text() == S.FRESH_PB_ASK.format(date="30 Oct 2026, 15:40")
    assert S.FRESH_PB_KNOWN not in ask.body.text() and ask.default is ask.no
    ask.yes.click()
    assert looks.put_backs == [folder]
    assert wait_until(lambda: win.toasts.text == S.FRESH_PB_DONE.format(date="30 Oct 2026, 15:40"), 5)
    assert win.current_tab() == "current" and settings_sources.running(win) is None


def test_a_3_0_backup_made_with_forget_says_known_words_stay_as_they_are_now(window):
    # P9: a 3.0 backup made with *Also forget my known words* puts back the library only
    looks = SheetLooks()
    seed, win = window(looks)
    _sorted_again(win.language, "20261029-101500",                # as `start_fresh(forget_known=True)` records it
                  known={"from": "KnownWord.json", "dated": "KnownWord.x.json", "copy": "KnownWord.json"})
    _page, fresh, _over = _rows(win)
    sheet = _sheet(fresh.ask())
    sheet.row_widgets[0].findChildren(QPushButton_)[0].click()
    ask = confirm._OPEN[-1]
    assert ask.body.text().endswith(S.FRESH_PB_KNOWN)
    ask.no.click()
    assert looks.put_backs == []


def test_a_refused_put_back_says_why_and_nothing_changed(window):
    looks = SheetLooks(put_back_answer={"done": False, "refused": ls.RESET_NEWER.format(version="3.2.0")})
    seed, win = window(looks)
    assert settings_sources.put_back(win, {"folder": "F", "scope": "library", "date": None})
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_PB_REFUSED.format(
        reason=ls.RESET_NEWER.format(version="3.2.0")), 5)
    assert settings_sources.running(win) is None


def test_a_started_over_backup_puts_back_by_a_restart_never_in_the_window(window, monkeypatch):
    looks = SheetLooks()
    seed, win = window(looks)
    restarts = []
    monkeypatch.setattr(type(win), "restart", lambda self, move=False: restarts.append(move))
    monkeypatch.setattr(shell_module, "relaunch_refused", lambda argv=None: None)
    entry = {"kind": profile_reset.STARTED_OVER, "scope": "profile", "stamp": "20261030-154000",
             "date": "2026-10-30T15:40:00", "folder": "F"}
    ask = settings_sources.act(win, ("put-back", entry))
    assert ask.title.text() == S.FRESH_PB_OVER_ASK.format(date="30 Oct 2026, 15:40")
    ask.yes.click()
    assert profile_reset.pending()["action"] == profile_reset.PUT_BACK and restarts == [True]
    assert looks.put_backs == []
    profile_reset.cancel_request()


def test_the_backup_line_words(window):
    entry = {"kind": "put-back-over", "date": "2026-10-30T15:40:12", "stopped": False}
    assert settings_sources.backup_line(entry, 182 * 1024 * 1024) == "Put back over · 30 Oct 2026, 15:40 · 182 MB"
    assert settings_sources.backup_line(dict(entry, stopped=True), None).endswith(
        S.FRESH_SIZE_WAIT + " · " + S.FRESH_STOPPED)



def test_a_sort_again_a_kill_left_unfinished_is_named_in_the_bar_with_where_to_put_it_back(window):
    # LF-11: the looks' first summary carries the backup folder of a reset still "started" (its *Put it back* is in
    # the sheet's Backups now)
    seed, win = window(SheetLooks())
    win._sources_looked({"language": win.language, "sources": [], "unfinished_reset": "C:/backup/library-reset-y"})
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_UNFINISHED.format(folder="C:/backup/library-reset-y"),
                      10)


def test_another_languages_sorted_again_backups_are_never_listed_here(window):
    # its Put back would act on this language's store (`put_back_library` refuses another's): never offered
    seed, win = window(SheetLooks())
    other = "zh" if win.language == "ja" else "ja"
    _sorted_again(other, "20261030-154000")
    mine = _sorted_again(win.language, "20261029-154000")
    _page, fresh, _over = _rows(win)
    sheet = _sheet(fresh.ask())
    assert [b["folder"] for b in sheet.backups] == [mine]


# --- the review's round (F4, F8, F9, F10, gap 1) ------------------------------------------------------------------ #
def test_the_bar_words_never_say_nothing_changed_when_part_stayed_in_the_backup(window):
    # (ported from the one-confirm tests) a reset that couldn't put everything back names where the rest is
    aside = {"done": False, "failed": "disk full", "aside": "C:/backup/library-reset-x"}
    assert settings_sources.fresh_said(aside) == S.FRESH_NOT_ALL_BACK.format(folder="C:/backup/library-reset-x")
    assert settings_sources.put_back_said(aside) == S.FRESH_NOT_ALL_BACK.format(folder="C:/backup/library-reset-x")
    assert settings_sources.fresh_said({"failed": "disk full"}) == S.FRESH_FAILED.format(reason="disk full")
    assert settings_sources.put_back_said({"failed": "disk full"}) == S.FRESH_PB_FAILED.format(reason="disk full")


@pytest.mark.parametrize("refused, why", [
    ("busy", "Your library is busy for a moment — try again."),
    ("io: disk I/O error", "Surasura can't read the library's file — check its drive is there, then restart Surasura."),
])
def test_a_store_refusal_is_said_in_the_stores_own_words(window, refused, why):
    # P-1 (ported): the store's busy / read-only reasons, as a sentence
    assert settings_sources.fresh_said({"refused": refused}) == S.FRESH_REFUSED.format(reason=why)
    assert settings_sources.put_back_said({"refused": refused}) == S.FRESH_PB_REFUSED.format(reason=why)


def test_a_sheet_dropped_with_its_window_never_leaves_the_button_dead(window):
    # H13 (ported): confirm's drop answers nothing back on purpose; the row must not hold the card for good
    seed, win = window(SheetLooks())
    _page, fresh, _over = _rows(win)
    card = fresh.ask()
    card.drop()
    again = fresh.ask()
    assert again is not None and again is not card
    again.no.click()


def test_while_a_put_back_runs_nothing_on_the_sheet_acts_and_start_over_refuses(window, monkeypatch):
    # F9: the Needs-you door and setup's link open the sheet while a Put back runs: none of its presses may act
    looks = SheetLooks()
    seed, win = window(looks)
    _sorted_again(win.language, "20261030-154000")
    settings_sources._set_running(win, S.FRESH_PB_RUNNING)
    restarts = []
    monkeypatch.setattr(type(win), "restart", lambda self, move=False: restarts.append(move))
    card = settings_sources.open_fresh(win, win)
    sheet = _sheet(card)
    assert not sheet.btn_sort.isEnabled() and not sheet.btn_over.isEnabled()
    assert sheet.btn_over.toolTip() == S.FRESH_PB_RUNNING
    assert not any(b.isEnabled() for w in sheet.row_widgets for b in w.findChildren(QPushButton_)
                   if b.text() == S.FRESH_PUT_BACK)
    card.no.click()
    assert settings_sources.start_over(win) is False and restarts == []
    assert win.bar_line.full() == S.FRESH_PB_RUNNING and profile_reset.pending() is None
    settings_sources._set_running(win, None)


def test_a_generate_or_an_update_staged_greys_every_choice_with_why(window, monkeypatch):
    # §3.1: greyed with the reason, never a cover that lifts with a refusal
    seed, win = window(SheetLooks())
    monkeypatch.setattr(type(win), "generating", lambda self: True)
    card = settings_sources.open_fresh(win, win)
    assert not card.sheet.btn_sort.isEnabled() and card.sheet.btn_sort.toolTip() == S.FRESH_GENERATING
    assert not card.sheet.btn_over.isEnabled()
    card.no.click()
    monkeypatch.setattr(type(win), "generating", lambda self: False)
    monkeypatch.setattr(ls, "update_staged", lambda: True)
    card = settings_sources.open_fresh(win, win)
    assert card.sheet.btn_over.toolTip() == S.FRESH_UPDATING and not card.sheet.btn_folders.isEnabled()
    card.no.click()


def test_a_started_over_backup_stopped_part_way_offers_only_its_folder(window, monkeypatch):
    # F8: its Put back is refused at the gate every time: never offered; its line says it is put back by hand
    seed, win = window(SheetLooks())
    entry = {"kind": profile_reset.STARTED_OVER, "scope": "profile", "stamp": "20261030-154000", "stopped": True,
             "date": "2026-10-30T15:40:00", "folder": "F", "language": None}
    monkeypatch.setattr(settings_sources, "list_backups", lambda language: [entry])
    card = settings_sources.open_fresh(win, win)
    sheet = _sheet(card)
    row = sheet.row_widgets[0]
    assert [b.text() for b in row.findChildren(QPushButton_)] == [S.FRESH_SHOW]
    assert row.findChildren(QLabel_)[0].toolTip() == S.FRESH_OVER_STOPPED_TIP
    card.no.click()


def test_sizes_land_in_place_and_the_rest_are_worked_out_only_on_show_all(window, monkeypatch):
    # F12 / F13: a row's buttons keep the keyboard as its size lands; the backups past five are walked on Show all
    seed, win = window(SheetLooks())
    for d in range(1, 8):
        _sorted_again(win.language, f"202610{d:02d}-120000")
    walked = []
    real = settings_sources.backup_sizes
    monkeypatch.setattr(settings_sources, "backup_sizes", lambda entries: walked.append(len(entries)) or real(entries))
    card = settings_sources.open_fresh(win, win)
    sheet = _sheet(card)
    first = sheet.row_widgets[0]
    assert wait_until(lambda: len(sheet.sizes) == 5, 10)
    assert sheet.row_widgets[0] is first and walked == [5]
    sheet.show_all()
    assert wait_until(lambda: len(sheet.sizes) == 7, 10) and walked == [5, 2]
    card.no.click()


def test_a_second_press_on_the_sheet_changes_nothing_so_sort_and_start_over_never_both_run(window):
    # the first press decides: a double press (another button, or the same one again) must not replace it
    looks = SheetLooks()
    seed, win = window(looks)
    _page, fresh, _over = _rows(win)
    card = fresh.ask()
    sheet = _sheet(card)
    sheet.choose(("sort",))
    assert card.answer is True and sheet.choice == ("sort",)
    sheet.choose(("over",))
    assert sheet.choice == ("sort",) and card.answer is True
    # the same button pressed again is a second press too: it changes nothing either
    sheet.choose(("sort",))
    assert sheet.choice == ("sort",) and card.answer is True
