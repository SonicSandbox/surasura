"""Settings › Content › *Start a fresh library…* (K7; `app/qt/settings_sources.py` FreshRow, `SourceLooks.fresh`,
the store's `start_fresh`): the sheet, what a click does, where the work runs, what the bar says.

What a wrong answer would cost a learner: a library emptied by a click he meant as No (Esc, Cancel); his known words
forgotten when he didn't tick the box; the window frozen while the reset copies his library aside; a reset that leaves
the library empty and never reads his folders again; a button that acts with no library open, or twice at once.

Real Japanese subtitles from tests/Test Resources/ (the window tests' helpers), made-up show names; a real store in
the test's own root; the source folder sits beside the data folder ("elsewhere"), never inside it.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app.qt import press as qpress
from app.qt import settings_sources
from app.qt import settings_strings as S
from app.services import source_looks
from tests.qt.conftest import wait_until
from tests.qt.test_drag import _stones_sheet  # noqa: F401  (the stones' sheet fixture)
from tests.qt.test_window_sources import (RecordingLooks, _added, _fresh_run, _library, _read_store,  # noqa: F401
                                          _source, window)


def _fresh_row(win):
    page = win.mount_settings()
    assert wait_until(lambda: page.findChildren(settings_sources.SourcesRow), 10)
    return page, page.findChildren(settings_sources.SourcesRow)[0].fresh


def _items(data_dir, user_files_dir):
    store = _read_store(data_dir, user_files_dir)
    try:
        return store.conn.execute("SELECT tier, rel_path FROM items").fetchall()
    finally:
        store.close()


class FreshLooks(RecordingLooks):
    """The looks with `fresh` recorded (the box's state, the calling thread) and answered as told."""

    def __init__(self, answer=None):
        super().__init__()
        self.fresh_calls = []
        self.answer = answer or {"done": True, "known": "kept"}

    def fresh(self, forget_known=False, then=None):
        self.fresh_calls.append((forget_known, threading.current_thread()))
        then(dict(self.answer))
        return True


def test_yes_sets_the_library_aside_reads_the_folders_again_and_says_so(window):
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    folder = _source()
    _added(looks, folder)
    before = sorted(r for _t, r in _items(data_dir, user_files_dir))
    assert len(before) == 2
    page, row = _fresh_row(win)
    assert row.button.isEnabled() and row.button.toolTip() == S.FRESH_TIP
    assert row.ask() is None                                                # the counts first, on the worker
    assert wait_until(lambda: row.card is not None, 10)
    card = row.card
    assert "master_manifest.json" in card.body.text() and not card.check.isChecked()
    assert card.default is card.no                                          # Enter is Cancel: it empties a library
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)          # Esc is No: nothing happens
    assert row.card is None and not row.running
    assert sorted(r for _t, r in _items(data_dir, user_files_dir)) == before
    trash = os.path.join(user_files_dir, ".trash")
    assert not os.path.isdir(trash) or not [n for n in os.listdir(trash) if n.startswith(ls.RESET_PREFIX)]
    row.ask()
    assert wait_until(lambda: row.card is not None, 10)
    row.card.yes.click()
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_DONE, 30)
    assert wait_until(lambda: looks.idle(1) and len(_items(data_dir, user_files_dir)) == 2, 30)
    after = _items(data_dir, user_files_dir)
    assert {t for t, _r in after} <= set(ls.CURRENT)                        # read again into Current (SRC-1)
    assert sorted(r for _t, r in after) == before                           # the same episodes, once each
    assert [n for n in os.listdir(trash) if n.startswith(ls.RESET_PREFIX)]   # the old library, in its backup
    assert row.button.isEnabled()


def test_the_box_ticked_asks_the_reset_to_forget_known_words_never_on_the_windows_thread(window):
    looks = FreshLooks()
    seed, win = window(looks)
    page, row = _fresh_row(win)
    card = row.ask()
    card.check.setChecked(True)
    card.yes.click()
    assert [k for k, _t in looks.fresh_calls] == [True]
    card = row.ask()
    card.yes.click()                                                        # not ticked: known words kept
    assert [k for k, _t in looks.fresh_calls] == [True, False]
    card = row.ask()
    card.check.setChecked(True)
    card.no.click()                                                         # No: nothing asked, ticked or not
    assert len(looks.fresh_calls) == 2


def test_a_refused_reset_says_why_and_that_nothing_changed(window):
    looks = FreshLooks({"done": False, "refused": ls.RESET_GENERATE})
    seed, win = window(looks)
    page, row = _fresh_row(win)
    row.ask().yes.click()
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_REFUSED.format(reason=ls.RESET_GENERATE), 10)
    assert row.button.isEnabled() and not row.running


@pytest.mark.parametrize("refused, why", [
    ("busy", "Your library is busy for a moment — try again."),
    ("io: disk I/O error", "Surasura can't read the library's file — check its drive is there, then restart Surasura."),
], ids=["busy", "disk-error"])
def test_P1_a_reset_refused_by_a_busy_store_says_so_in_the_stores_words(window, refused, why):
    # why (P-1): a store busy past its wait answers "busy", never "no-library" (your library isn't open); said as a
    # sentence, as a disk error is (the bar's words for one, never "io: …"), nothing changed
    looks = FreshLooks({"done": False, "refused": refused})
    seed, win = window(looks)
    page, row = _fresh_row(win)
    row.ask().yes.click()
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_REFUSED.format(reason=why), 10), win.bar_line.full()
    assert row.button.isEnabled() and not row.running


def test_a_failed_reset_says_nothing_changed(window):
    looks = FreshLooks({"done": False, "failed": "disk full"})
    seed, win = window(looks)
    page, row = _fresh_row(win)
    row.ask().yes.click()
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_FAILED.format(reason="disk full"), 10)


def test_known_words_that_couldnt_be_forgotten_are_named_in_the_line(window):
    looks = FreshLooks({"done": True, "known": "kept: the file is open in another program"})
    seed, win = window(looks)
    page, row = _fresh_row(win)
    card = row.ask()
    card.check.setChecked(True)
    card.yes.click()
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_DONE_KNOWN_KEPT.format(
        why="the file is open in another program"), 10)


def test_without_a_library_the_button_is_greyed_and_says_why(window):
    seed, win = window(None)
    page, row = _fresh_row(win)
    assert not row.button.isEnabled() and row.button.toolTip() == S.STORE_NO_LIBRARY_TIP
    assert row.ask() is None


def test_one_reset_at_a_time_its_arc_turning_while_it_runs(window):
    class Held(FreshLooks):
        def fresh(self, forget_known=False, then=None):
            self.fresh_calls.append((forget_known, threading.current_thread()))
            self.then = then                                               # answered later
            return True
    looks = Held()
    seed, win = window(looks)
    page, row = _fresh_row(win)
    row.ask().yes.click()
    # round 8 row 45: never greyed while it runs — its arc turns, *Starting a fresh library…* held in the bar
    assert row.running and row.button.isEnabled() and row.button.toolTip() == S.FRESH_RUNNING_TIP
    assert qpress.arc(row.button) is not None                          # the arc now; the words once live 300 ms (IK-1)
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_RUNNING_TIP, 3)
    assert row.ask() is None and row.start() is False
    looks.then({"done": True, "known": "kept"})
    assert wait_until(lambda: not row.running and qpress.arc(row.button) is None, 10)
    assert row.button.isEnabled() and row.button.toolTip() == S.FRESH_TIP
    assert len(looks.fresh_calls) == 1


# --- the review fix round (LF register: I-R1/I-R5/LF-8, H13, H1, LF-11) ---------------------------------------------- #

class CountingLooks(FreshLooks):
    """FreshLooks with the store's counts (`fresh_counts`), answered as told."""

    def __init__(self, counts, answer=None):
        super().__init__(answer)
        self.counts = counts

    def fresh_counts(self, then):
        then(dict(self.counts) if self.counts is not None else None)
        return True


def test_the_sheet_names_what_never_comes_back_and_the_cards_left_suspended(window):
    # I-R5 / LF-8 / I-R1: a learner whose library is mostly + Add, YouTube or pasted texts must read, before Yes, that
    # those never come back — and how many cards stay suspended in Anki
    looks = CountingLooks({"added": 3, "youtube": 1, "other": 2, "suspended": 4})
    seed, win = window(looks)
    page, row = _fresh_row(win)
    row.ask()
    assert wait_until(lambda: row.card is not None, 10)
    body = row.card.body.text()
    assert S.FRESH_GONE.format(parts=", ".join((S.FRESH_GONE_ADDED.format(n=3, s="s"),
                                                 S.FRESH_GONE_YOUTUBE.format(n=1, s=""),
                                                 S.FRESH_GONE_OTHER.format(n=2, s="s")))) in body
    assert S.FRESH_SUSPENDED.format(n=4, s="s") in body
    assert "episodes you removed too" in body and "book's text comes back only" in body
    row.card.no.click()


def test_with_nothing_lost_or_no_counts_the_sheet_says_only_what_always_holds(window):
    for counts in ({"added": 0, "youtube": 0, "other": 0, "suspended": 0}, None):
        looks = CountingLooks(counts)
        seed, win = window(looks)
        page, row = _fresh_row(win)
        row.ask()
        assert wait_until(lambda: row.card is not None, 10)
        assert row.card.body.text() == S.FRESH_BODY
        row.card.no.click()


def test_a_sheet_dropped_with_its_window_never_leaves_the_button_dead(window):
    # H13: confirm's drop (the window hidden) answers nothing back on purpose; the row then held the card for good
    # and every later click did nothing
    looks = FreshLooks()
    seed, win = window(looks)
    page, row = _fresh_row(win)
    card = row.ask()
    card.drop()
    assert row.card is card and card.answer is not None
    again = row.ask()
    assert again is not None and again is not card
    again.no.click()


def test_a_reset_that_couldnt_put_everything_back_never_says_nothing_changed(window):
    looks = FreshLooks({"done": False, "failed": "disk full", "aside": "C:/backup/library-reset-x"})
    seed, win = window(looks)
    page, row = _fresh_row(win)
    row.ask().yes.click()
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_NOT_ALL_BACK.format(folder="C:/backup/library-reset-x"),
                      10)


def test_a_fresh_library_a_kill_left_unfinished_is_named_in_the_bar(window):
    # LF-11: the looks' first summary carries the backup folder of a reset still "started"
    looks = FreshLooks()
    seed, win = window(looks)
    win._sources_looked({"language": win.language, "sources": [], "unfinished_reset": "C:/backup/library-reset-y"})
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_UNFINISHED.format(folder="C:/backup/library-reset-y"),
                      10)
