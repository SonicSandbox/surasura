"""Settings › Content › *Library folders* as a summary and its own window (laptop row 32; `app/qt/settings_sources.py`
`SourcesRow`, `FoldersWindow`): the page says *4 folders · 1 not reachable now · 2 skipped* with *Add a folder…* and
*Manage folders…* beside it; the folders, the skipped ones, *Stop reading*, *Read again* and *Look again* are in the
window.

What a wrong answer would cost a learner:
  * a summary that counts a stopped folder, or misses one that can't be reached (he thinks his drive is read);
  * *Add a folder…* gone from the page, or a door that opens nothing;
  * a stop or a read-again in the window that leaves the page's count stale, or repaints every line (S19);
  * a window Esc doesn't close.

Made-up folder names (Japanese, as his drives hold them); the looks recorded (no store), except Add, which reads a real
folder of real Japanese subtitles into a real store in the test's own root.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import library_store as ls
from app.qt import settings_sources, windows
from app.qt import settings_strings as S
from app.services import source_looks
from tests.qt.conftest import wait_until
from tests.qt.test_drag import _stones_sheet  # noqa: F401  (the stones' sheet fixture)
from tests.qt.test_window_sources import (RecordingLooks, _folders_window, _fresh_run, _library,  # noqa: F401
                                          _read_store, _source, _sources_row, window)

ANIME = r"D:\アニメ\2026秋"
DRAMA = r"E:\ドラマ"
OLD = r"D:\アニメ\昔の録画"


def _src(id_, path, items, reachable=True, on=True):
    return {"id": id_, "path": path, "on": on, "items": items, "reachable": reachable}


class ActingLooks(RecordingLooks):
    """The looks with *Stop reading* and *Read again* answered at once, then the summary published as the real looks
    publish it (`on_result`, the shell's `_sources_looked`)."""

    def __init__(self, sources, skipped=()):
        super().__init__()
        self.sources, self.skipped_folders = [dict(s) for s in sources], [dict(f) for f in skipped]
        self.stops, self.reads = [], []
        self.language = "ja"

    def _publish(self):
        self.on_result({"language": self.language, "sources": [dict(s) for s in self.sources],
                        "skipped": [dict(f) for f in self.skipped_folders]})

    def listing(self):
        if self.on_result is not None:
            self._publish()
        return True

    def stop(self, root_id, then=None, language=None):
        self.stops.append((root_id, language))
        self.sources = [s for s in self.sources if s["id"] != root_id]
        then({"stopped": True})
        self._publish()
        return True

    def read_again(self, folder_id, then=None, language=None):
        self.reads.append((folder_id, language))
        self.skipped_folders = [f for f in self.skipped_folders if f["id"] != folder_id]
        then({"read": True})
        self._publish()
        return True


def _open(window, looks):
    seed, win = window(looks)
    looks.on_result = win._sources_looked                 # as `_open_looks` wires the real looks (a relay to it)
    page, row, folders = _folders_window(win)
    return win, page, row, folders


# --- the page's summary ----------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("sources, skipped, words", [
    ([], 0, S.SOURCES_NONE),
    ([_src(1, ANIME, 412)], 0, "1 folder"),
    ([_src(1, ANIME, 412), _src(2, DRAMA, 30), _src(3, OLD, 5), _src(4, r"F:\映画", 1)], 0, "4 folders"),
    ([_src(1, ANIME, 412), _src(2, DRAMA, 30, reachable=False)], 0, "2 folders · 1 not reachable now"),
    ([_src(1, ANIME, 412), _src(2, DRAMA, 30, on=False)], 2, "1 folder · 2 skipped"),     # a stopped one never counts
    ([_src(2, DRAMA, 30, on=False)], 1, S.SOURCES_NONE + " · 1 skipped"),
    ([_src(i, f"D:\\番組{i}", i) for i in range(1, 1201)], 0, "1,200 folders"),
])
def test_the_summary_counts_the_folders_being_read_the_unreachable_and_the_skipped(sources, skipped, words):
    assert settings_sources.summary_words(sources, skipped) == words


def test_the_summary_waits_for_the_first_listing():
    assert settings_sources.summary_words([], 0, known=False) == S.SOURCES_LISTING


def test_the_page_shows_the_summary_and_add_and_the_door_never_the_lines(window):
    looks = ActingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30, reachable=False)], skipped=[{"id": 7, "path": OLD}])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: row.summary.text() == "2 folders · 1 not reachable now · 1 skipped", 10)
    view = page.row(settings_sources.ROW_ID)
    assert not view.findChildren(settings_sources.SourceLine)          # the lines live in the window only
    assert not view.findChildren(settings_sources.SkippedLine)
    assert row.add.isVisibleTo(page) and row.add.toolTip() == S.SOURCES_ADD_TIP
    assert view.doors[settings_sources.WINDOW].isVisibleTo(page)
    assert set(folders.lines) == {1, 2} and set(folders.skipped) == {7}


# --- Add a folder… on the page ---------------------------------------------------------------------------------- #
def test_add_a_folder_on_the_page_reads_it_where_it_is_and_the_summary_counts_it(window, monkeypatch):
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    page, row = _sources_row(win)
    assert wait_until(lambda: row.summary.text() == S.SOURCES_NONE, 10)
    folder = _source()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: folder)
    row.add.click()
    assert wait_until(lambda: row.summary.text() == S.SOURCES_FOLDERS_ONE, 30)
    store = _read_store(data_dir, user_files_dir)
    try:
        assert [s["path"] for s in store.sources()] == [ls.folder_path(folder)]
    finally:
        store.close()


def test_a_cancelled_picker_adds_nothing(window, monkeypatch):
    looks = ActingLooks([])
    win, page, row, folders = _open(window, looks)
    asked = []
    monkeypatch.setattr(win.adder, "read_folder", asked.append)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")
    row.add.click()
    folders.add.click()
    assert asked == []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: DRAMA)
    folders.add.click()                                    # the window's Add is the page's one
    assert asked == [DRAMA]


# --- the window ------------------------------------------------------------------------------------------------- #
def test_the_door_opens_one_library_folders_window_titled_and_esc_closes_it(window):
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert folders.windowTitle() == "Library folders — Surasura" and folders.parentWidget() is win
    page.row(settings_sources.ROW_ID).doors[settings_sources.WINDOW].click()
    assert windows.opened(win, settings_sources.WINDOW) is folders                  # one of its kind, raised
    assert folders.look.toolTip() and folders.add.toolTip()
    assert all(line.stop.toolTip() for line in folders.lines.values())
    QTest.keyClick(folders, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert windows.opened(win, settings_sources.WINDOW) is None and win.isVisible()


def test_a_stop_in_the_window_takes_only_its_line_and_the_page_counts_one_fewer(window):
    looks = ActingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30), _src(3, OLD, 1)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: row.summary.text() == "3 folders" and len(folders.lines) == 3, 10)
    kept = {i: folders.lines[i] for i in (1, 3)}
    reads, paints = folders.reads, row.paints
    folders.lines[2].stop.click()
    assert looks.stops == [(2, "ja")]                      # its language named: never another store's id
    assert set(folders.lines) == {1, 3} and all(folders.lines[i] is kept[i] for i in kept)   # the others untouched
    assert folders.reads == reads + 1 and row.paints == paints + 1
    assert row.summary.text() == "2 folders"
    assert win.bar_line.full() == S.SOURCES_STOPPED.format(path=DRAMA, n=30)


def test_a_read_again_in_the_window_takes_its_line_and_the_page_counts_it(window):
    looks = ActingLooks([_src(1, ANIME, 412)], skipped=[{"id": 7, "path": OLD}, {"id": 8, "path": r"D:\アニメ\予告"}])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: row.summary.text() == "1 folder · 2 skipped" and len(folders.skipped) == 2, 10)
    other = folders.skipped[8]
    folders.skipped[7].read.click()
    assert looks.reads == [(7, "ja")]
    assert set(folders.skipped) == {8} and folders.skipped[8] is other and not folders.skip_box.isHidden()
    assert row.summary.text() == "1 folder · 1 skipped"
    assert win.bar_line.full() == S.SOURCES_READ_AGAIN_DONE.format(path=OLD)
    other.read.click()
    assert folders.skipped == {} and folders.skip_box.isHidden()          # none left: no heading
    assert row.summary.text() == "1 folder"


def test_look_again_in_the_window_is_a_full_look(window):
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    looks.asks.clear()
    folders.look.click()
    assert looks.asks and looks.asks[-1][1] is True        # refreshed: every folder, in full


def test_without_a_library_the_buttons_are_greyed_and_say_why(window):
    seed, win = window(RecordingLooks())
    win.looks = None
    page, row = _sources_row(win)
    folders = settings_sources.open_window(win)
    try:
        for button in (row.add, folders.add, folders.look):
            assert not button.isEnabled() and button.toolTip() == S.STORE_NO_LIBRARY_TIP
    finally:
        folders.close()
