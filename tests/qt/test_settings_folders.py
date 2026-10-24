"""Settings › Content › *Library folders* as a summary and its own window (laptop row 32; `app/qt/settings_sources.py`
`SourcesRow`, `FoldersWindow`): the page says *4 folders · 1 not reachable now · 2 skipped* with *Add a folder…* and
*Manage folders…* beside it; the folders, the skipped ones, *Stop reading*, *Read again* and *Look again* are in the
window.

What a wrong answer would cost a learner:
  * a summary that counts a stopped folder (or a skip under one), misses one that can't be reached, or says *No folders
    yet* while his folders are being listed (he thinks his library lost them);
  * *Add a folder…* gone from the page, or a door that opens nothing;
  * a stop or a read-again in the window that leaves the page's count stale, or repaints every line (S19);
  * a press on a library that can't be written that fails with no word why; a folder stopped twice;
  * a window that doesn't grow to show his folders, a scroll area or a Tab order that skips about; Esc not closing it.

Made-up folder names (Japanese, as his drives hold them); the looks recorded (no store), except Add, which reads a real
folder of real Japanese subtitles into a real store in the test's own root.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import library_store as ls
from app.qt import press as qpress
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


def _skip(id_, root, path):
    return {"id": id_, "root": root, "key": path.lower(), "path": path}


class ActingLooks(RecordingLooks):
    """The looks with *Stop reading* and *Read again* answered at once (or held, `hold`), then the summary published as
    the real looks publish it (`on_result`, the shell's `_sources_looked`)."""

    def __init__(self, sources, skipped=(), hold=False):
        super().__init__()
        self.sources, self.skipped_folders = [dict(s) for s in sources], [dict(f) for f in skipped]
        self.stops, self.reads, self.held = [], [], []
        self.hold = hold
        self.language = "ja"

    def publish(self):
        self.on_result({"language": self.language, "sources": [dict(s) for s in self.sources],
                        "skipped": [dict(f) for f in self.skipped_folders]})

    def listing(self):
        if self.on_result is not None:
            self.publish()
        return True

    def busy(self):
        return False

    def stop(self, root_id, then=None, language=None):
        self.stops.append((root_id, language))

        def land():
            self.sources = [s for s in self.sources if s["id"] != root_id]
            then({"stopped": True})
            self.publish()
        self.held.append(land) if self.hold else land()
        return True

    def read_again(self, folder_id, then=None, language=None):
        self.reads.append((folder_id, language))
        self.skipped_folders = [f for f in self.skipped_folders if f["id"] != folder_id]
        then({"read": True})
        self.publish()
        return True


def _open(window, looks):
    seed, win = window(looks)
    looks.on_result = win._sources_looked                 # as `_open_looks` wires the real looks (a relay to it)
    page, row, folders = _folders_window(win)
    return win, page, row, folders


# --- the page's summary ----------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("sources, skipped, words", [
    ([], (), S.SOURCES_NONE),
    ([_src(1, ANIME, 412)], (), "1 folder"),
    ([_src(1, ANIME, 412), _src(2, DRAMA, 30), _src(3, OLD, 5), _src(4, r"F:\映画", 1)], (), "4 folders"),
    ([_src(1, ANIME, 412), _src(2, DRAMA, 30, reachable=False)], (), "2 folders · 1 not reachable now"),
    ([_src(1, ANIME, 412), _src(2, DRAMA, 30, on=False)],                  # a stopped folder never counts, nor its skip
     (_skip(7, 1, ANIME + r"\予告"), _skip(8, 1, ANIME + r"\特典"), _skip(9, 2, DRAMA + r"\SP")), "1 folder · 2 skipped"),
    ([_src(2, DRAMA, 30, on=False)], (_skip(9, 2, DRAMA + r"\SP"),), S.SOURCES_NONE),       # the sentence alone
    ([_src(i, f"D:\\番組{i}", i) for i in range(1, 1201)], (), "1,200 folders"),
])
def test_the_summary_counts_the_folders_being_read_the_unreachable_and_the_skipped_under_them(sources, skipped, words):
    assert settings_sources.summary_words(sources, skipped) == words


def test_the_summary_waits_for_the_first_listing():
    assert settings_sources.summary_words([], (), known=False) == S.SOURCES_LISTING


def test_the_unreachable_count_is_the_offline_lines_own_rule():
    sources = [_src(1, ANIME, 412, reachable=False), _src(2, DRAMA, 30, reachable=False, on=False),
               _src(3, OLD, 5, reachable=None)]                            # stopped, or not looked at yet: not counted
    assert len(source_looks.offline(sources)) == 1
    assert settings_sources.summary_words(sources) == "2 folders · 1 not reachable now"


def test_the_page_shows_the_summary_and_add_and_the_door_never_the_lines(window):
    looks = ActingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30, reachable=False)],
                        skipped=[_skip(7, 1, ANIME + r"\予告")])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: row.summary.text() == "2 folders · 1 not reachable now · 1 skipped", 10)
    assert set(folders.lines) == {1, 2} and set(folders.skipped) == {7}       # the window built them…
    view = page.row(settings_sources.ROW_ID)
    assert not view.findChildren(settings_sources.SourceLine)          # …and the page holds none
    assert not view.findChildren(settings_sources.SkippedLine)
    assert row.add.isVisibleTo(page) and row.add.toolTip() == S.SOURCES_ADD_TIP
    assert view.doors[settings_sources.WINDOW].isVisibleTo(page)


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
    assert len(win.findChildren(settings_sources.FoldersWindow)) == 1               # never a second one made
    assert folders.look.toolTip() and folders.add.toolTip()
    assert all(line.stop.toolTip() for line in folders.lines.values())
    assert folders.scroll.focusPolicy() == Qt.FocusPolicy.NoFocus                   # never a Tab stop of its own
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
    assert all(line.stop.isEnabled() for line in folders.lines.values())


def test_a_stop_answered_after_the_window_closed_is_told_in_the_bar_and_never_pressed_twice(window):
    looks = ActingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30)], hold=True)
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: len(folders.lines) == 2, 10)
    folders.lines[2].stop.click()
    # round 8 row 45: never greyed — its arc turns until the stop answers, and a press meanwhile stops nothing more
    assert folders.lines[2].stop.isEnabled() and qpress.arc(folders.lines[2].stop) is not None
    folders.lines[2].stop.click()
    folders.close()
    QApplication.processEvents()
    again = settings_sources.open_window(win)                          # opened again before the stop answered
    assert again is not folders and qpress.arc(again.lines[2].stop) is not None     # its arc taken by the new line
    assert qpress.arc(again.lines[1].stop) is None and again.lines[1].stop.isEnabled()
    again.lines[2].stop.click()
    assert looks.stops == [(2, "ja")]                                  # one stop, never two
    again.close()
    QApplication.processEvents()
    looks.held.pop()()                                                 # the stop lands with no window open
    assert win.bar_line.full() == S.SOURCES_STOPPED.format(path=DRAMA, n=30)
    assert row.summary.text() == "1 folder"
    third = settings_sources.open_window(win)
    try:
        assert set(third.lines) == {1} and third.lines[1].stop.isEnabled() and qpress.arc(third.lines[1].stop) is None
        assert not win.presses.any_live()
    finally:
        third.close()


def test_a_read_again_in_the_window_takes_its_line_and_the_page_counts_it(window):
    looks = ActingLooks([_src(1, ANIME, 412)], skipped=[_skip(7, 1, OLD), _skip(8, 1, r"D:\アニメ\予告")])
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
    # round 8 row 45 (P5-A2): the Refresh key's press, on this button — its arc from the press, the bar's arc never
    # turning beside it (one mark, one end rule: P3's), until the look's summary; a press meanwhile asks nothing
    assert qpress.arc(folders.look) is not None and folders.look.isEnabled() and not win.bar_arc.isVisible()
    assert win.presses.find("sources:refresh").live()
    folders.look.click()
    assert len(looks.asks) == 1
    looks.publish()                                        # the look's summary
    assert qpress.arc(folders.look) is None and not win.presses.find("sources:refresh").live()


def test_the_window_grows_to_show_folders_that_arrive_then_scrolls(window):
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    QApplication.processEvents()
    before = folders.height()
    looks.sources += [_src(i, f"D:\\アニメ\\番組{i}", i * 12) for i in range(2, 8)]
    looks.publish()
    QApplication.processEvents()
    assert len(folders.lines) == 7 and folders.height() > before
    assert folders.scroll.viewport().height() >= folders.box.sizeHint().height() - 2     # all 7 in view
    room = folders.screen().availableGeometry().bottom() - folders.frameGeometry().bottom()
    looks.sources += [_src(i, f"D:\\アニメ\\番組{i}", i) for i in range(8, 400)]
    looks.publish()
    QApplication.processEvents()
    assert folders.frameGeometry().bottom() <= folders.screen().availableGeometry().bottom()   # never off the screen
    assert room >= 0 and folders.scroll.verticalScrollBar().maximum() > 0                       # the rest scroll


def test_tab_follows_the_window_folders_then_skipped_then_look_again_and_add(window):
    looks = ActingLooks([_src(1, ANIME, 412)], skipped=[_skip(7, 1, OLD)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 7 in folders.skipped, 10)
    looks.sources.insert(0, _src(5, DRAMA, 30))                       # a folder arriving above the first one, alone
    looks.publish()
    want = [folders.lines[5].stop, folders.lines[1].stop, folders.skipped[7].read, folders.look, folders.add]
    seen, w = [], want[0]
    for _ in range(200):
        if w in want and w not in seen:
            seen.append(w)
        w = w.nextInFocusChain()
        if w is want[0]:
            break
    assert seen == want


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


def test_a_library_that_cant_be_written_greys_stop_read_again_and_add_with_the_reason(window):
    looks = ActingLooks([_src(1, ANIME, 412)], skipped=[_skip(7, 1, OLD)])
    win, page, row, folders = _open(window, looks)
    writer = win.services.writer
    writer.writable, writer.why = False, "another Surasura is writing it"
    looks.publish()                                                      # re-checked on the next summary
    why = S.FRESH_NOT_WRITABLE.format(reason="another Surasura is writing it")
    for button in (row.add, folders.add, folders.lines[1].stop, folders.skipped[7].read):
        assert not button.isEnabled() and button.toolTip() == why
    assert folders.look.isEnabled()                                      # looking still works
    assert settings_sources.add_folder(win, folders, DRAMA) is False
    writer.writable = True
    looks.publish()
    assert folders.lines[1].stop.isEnabled() and folders.lines[1].stop.toolTip() == folders.lines[1].tip
    assert row.add.toolTip() == S.SOURCES_ADD_TIP


# --- round 8 row 45: every press reacts at once ------------------------------------------------------------------- #
def test_stop_reading_paints_its_arc_before_the_looks_are_asked(window):
    # *Stop reading* greyed with no words: its arc now turns, painted before the looks' worker is asked to stop.
    from tests.qt.press_handover import Paints, arc_turning
    looks = ActingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30)], hold=True)
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: len(folders.lines) == 2 and folders.lines[2].stop.isVisible(), 10)
    button = folders.lines[2].stop
    paints, seen, stop = Paints(button), [], looks.stop

    def asked(root_id, then=None, language=None):
        seen.append((arc_turning(button), paints.n))
        return stop(root_id, then, language)
    looks.stop = asked
    button.click()
    assert seen and seen[0][0] and seen[0][1] >= 1
    looks.held.pop()()
    assert wait_until(lambda: 2 not in folders.lines and not win.presses.any_live(), 5)
