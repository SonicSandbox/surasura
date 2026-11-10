"""Setup's page 3, *Skip a folder…* (K6, `app/qt/wizard.py`, `app/services/setup_wizard.py`): a folder inside one picked
that is never read — checked by the store's own rule on a worker (refused in the page's refusal line), listed with
*Read it after all*, and skipped on *Next* before the folder's first look, so nothing of it is ever copied in.

What a wrong answer would cost a learner:
  * a backup's or a game's files flooding Current on the very first look, though he said to skip them;
  * a skip outside every folder picked accepted and silently doing nothing — or refused with no word why;
  * the check or the skip run on the window's thread.

Real Japanese subtitles from tests/Test Resources/ in temp folders beside the test's data folder, made-up names.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QPushButton

from app import library_store as ls
from app.qt import wizard_strings as S
from app.services import setup_wizard
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import go_to, make  # noqa: F401
from tests.qt.test_wizard_sources import (SHOWS, SourcesApi, _folder, _fresh_look_state, _items, _pick,  # noqa: F401
                                          _store, empty_library)
from tests.test_sources_scan import _drive, _text, _write

CARD = os.path.join("Old Backups", "Console Card")


class SkipApi(SourcesApi):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.skip_threads = []

    def skip_refused(self, language, path, chosen=()):
        self.skip_threads.append(threading.current_thread())
        return setup_wizard.skip_refused(language, path, chosen)

    def read_folders(self, language, paths, progress=None, stop=None, skips=(), **kw):
        self.read_threads.append(threading.current_thread())
        return setup_wizard.read_folders(language, paths, progress, stop, skips=skips, **kw)


def _skip(wiz, path):
    page = wiz.pages[2]
    wiz.pick_dialog = lambda _title, _start, p=path: p
    before = (list(page.skips), page.refused_line.text())
    QTest.mouseClick(page.btn_skip, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: (list(page.skips), page.refused_line.text()) != before)


def _with_card(root):
    for n in (1, 2):
        _write(os.path.join(root, CARD, "loader", "skins", f"skin {n}.srt"), _text("ja", 50 + n))
    return os.path.join(root, CARD)


def test_skip_a_folder_shows_once_a_folder_is_picked_and_refuses_one_outside_with_the_stores_words(make,
                                                                                                    empty_library):
    first = _folder("anime", SHOWS)
    elsewhere = _drive("not-picked")
    wiz, *_ = make(api=SkipApi())
    go_to(wiz, "shows")
    page = wiz.page
    assert page.btn_skip.isHidden()                                # nothing picked: nothing to skip inside
    _pick(wiz, first)
    assert not page.btn_skip.isHidden() and page.btn_skip.toolTip()
    _skip(wiz, elsewhere)
    assert page.skips == [] and page.refused_line.text() == S.FOLDER_REFUSED.format(
        folder=os.path.normpath(elsewhere), why=ls.SKIP_OUTSIDE)
    _skip(wiz, first)                                              # the folder itself: that's leaving it out
    assert page.refused_line.text() == S.FOLDER_REFUSED.format(folder=os.path.normpath(first), why=ls.SKIP_IS_SOURCE)
    card = _with_card(first)
    _skip(wiz, card)
    assert page.skips == [os.path.normpath(card)] and page.refused_line.isHidden()
    assert wiz.api.skip_threads and all(t is not threading.main_thread() for t in wiz.api.skip_threads)
    for b in page.folders_part.findChildren(QPushButton):           # every control says what it does
        assert b.toolTip()
    undo = next(b for b in page.folders_part.findChildren(QPushButton)
                if b.accessibleName() == S.SKIP_REMOVE_NAME.format(folder=os.path.normpath(card)))
    QTest.mouseClick(undo, Qt.MouseButton.LeftButton)
    assert page.skips == []
    store = _store()
    try:
        assert store.skipped_folders() == [] and store.sources(all=True) == []          # picking writes nothing
    finally:
        store.close()


def test_next_skips_the_folder_before_the_first_look_so_nothing_of_it_comes_in(make, empty_library):
    first = _folder("anime", SHOWS)
    card = _with_card(first)
    api = SkipApi()
    wiz, *_ = make(api=api)
    go_to(wiz, "shows")
    page = wiz.page
    _pick(wiz, first)
    _skip(wiz, card)
    wiz.next()
    assert wait_until(lambda: wiz.reading is None, 30)
    assert api.read_threads and api.read_threads[0] is not threading.main_thread()
    items = _items()
    assert len(items) == sum(SHOWS.values()) and not any("Console Card" in rel for *_x, rel in items)
    assert page.skips == [] and page.folders == [] and page.refused_line.isHidden()
    store = _store()
    try:
        assert [f["path"] for f in store.skipped_folders()] == [ls.folder_path(card)]
    finally:
        store.close()


def test_read_folders_reports_a_skip_no_folder_holds_and_reads_the_rest(empty_library):
    first = _folder("anime", SHOWS)
    stray = os.path.join(_drive("not-picked"), "inside")
    got = setup_wizard.read_folders("ja", [first], skips=[stray])
    assert got["added"] == sum(SHOWS.values())
    assert got["refused"] == [(stray, ls.SKIP_OUTSIDE)]


def test_a_second_choose_or_skip_while_the_first_is_checked_opens_no_dialog(make, empty_library):
    """P5-A1: *Choose a folder…* / *Skip a folder…* stay enabled while the folder picked is checked, so a second press
    opened the folder dialog again — and the folder picked there was dropped with no word. A press while one is live
    does nothing: no dialog."""
    first = _folder("anime", SHOWS)
    card = _with_card(first)
    gate = threading.Event()

    class Held(SkipApi):
        def folder_refused(self, language, path):
            gate.wait(5)
            return super().folder_refused(language, path)

        def skip_refused(self, language, path, chosen=()):
            gate.wait(5)
            return super().skip_refused(language, path, chosen)
    wiz, *_ = make(api=Held())
    go_to(wiz, "shows")
    page = wiz.pages[2]
    dialogs = []
    for button, path in ((page.btn_pick, first), (page.btn_skip, card)):
        gate.clear()
        wiz.pick_dialog = lambda _title, _start, p=path: dialogs.append(p) or p
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)       # the first folder still being checked
        assert dialogs.count(path) == 1
        gate.set()
        assert wait_until(lambda: os.path.normpath(path) in (page.folders + list(page.skips)))
