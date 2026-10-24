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
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import library_store as ls
from app.qt import press as qpress
from app.qt import settings_sources, strings, windows
from app.qt import settings_strings as S
from app.qt import wizard_strings as W
from app.services import source_looks
from tests.qt.conftest import wait_until
from tests.qt.test_drag import _stones_sheet, calls  # noqa: F401  (the stones' sheet fixture)
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
        self.refusals, self.skip_asks = {}, []            # Q7: the store's rule for *Skip a folder…*, by path

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

    def skip_refused(self, path, then, language=None):
        self.skip_asks.append((path, language))
        then(self.refusals.get(path))
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
    want = [folders.lines[5].stop, folders.lines[1].stop, folders.skipped[7].read, folders.skip, folders.look,
            folders.add]
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
        for button in (row.add, folders.add, folders.look, folders.skip):
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
    for button in (row.add, folders.add, folders.lines[1].stop, folders.skipped[7].read, folders.skip):
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


# --- Q7: *Skip a folder…* under the skipped folders ----------------------------------------------------------------- #
def _skipping(win, looks):
    """The window's recording writer taught `skip_folder` as the store lands it: the folder joins the looks' skipped
    list (the store's), its change carrying the store's `folder`; Undo takes it off again. -> the writer."""
    writer = win.services.writer
    folders = iter(range(100, 200))

    def write(change):
        if change.op == "skip_folder":
            change.folder = next(folders)
            looks.skipped_folders.append(_skip(change.folder, 1, change.kw["path"]))
    writer.apply, writer._write = True, write
    writer.skip_folder = lambda path, label=None: writer._put("skip_folder", [], label, path=path)
    undo = writer.undo

    def undone(change=None, label=None):
        if change is None and writer.saved:              # Ctrl+Z: the newest saved change, as the real writer's
            change = next((c for c in reversed(writer.saved) if c not in writer.undone), None)
        looks.skipped_folders = [f for f in looks.skipped_folders if f["id"] != getattr(change, "folder", None)]
        return undo(change, label)
    writer.undo = undone
    return writer


def _picks(folders, path):
    """The folder dialog stood in for: it answers `path` -> the (title, start) it was opened with."""
    asked = []
    folders.pick_dialog = lambda title, start: (asked.append((title, start)), path)[1]
    return asked


def test_skip_a_folder_shows_under_the_folders_even_with_none_skipped_and_is_tipped(window):
    # The only way to skip a folder after setup from here: it must be there before anything is skipped.
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    assert folders.skip_box.isHidden() and folders.skipped == {}
    assert folders.skip.isVisible() and folders.skip.isEnabled()
    assert folders.skip.text() == S.SOURCES_SKIP and folders.skip.toolTip() == S.SOURCES_SKIP_TIP


def test_skip_a_folder_starts_in_a_folder_being_read_and_a_refusal_says_why_in_the_windows_line(window):
    # A folder Surasura reads itself is *Stop reading*'s: the store's words, in the window he is looking at; nothing
    # is written.
    looks = ActingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: len(folders.lines) == 2, 10)
    writer = _skipping(win, looks)
    looks.refusals[os.path.normpath(DRAMA)] = ls.SKIP_IS_SOURCE
    asked = _picks(folders, DRAMA)
    folders.skip.click()
    assert asked == [(W.SKIP_TITLE, ANIME)]                             # the first folder being read
    assert looks.skip_asks == [(os.path.normpath(DRAMA), "ja")]
    assert wait_until(lambda: folders.status.text() == W.FOLDER_REFUSED.format(folder=os.path.normpath(DRAMA),
                                                                              why=ls.SKIP_IS_SOURCE), 5)
    assert calls(writer, "skip_folder") == [] and not win.presses.any_live()
    assert qpress.arc(folders.skip) is None and folders.skip.isEnabled()
    _picks(folders, "")                                                 # the dialog cancelled: nothing asked
    folders.skip.click()
    assert len(looks.skip_asks) == 1


def test_skip_a_folder_paints_its_arc_before_the_looks_are_asked(window):
    from tests.qt.press_handover import Paints, arc_turning
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines and folders.skip.isVisible(), 10)
    _skipping(win, looks)
    _picks(folders, OLD)
    paints, seen, ask = Paints(folders.skip), [], looks.skip_refused

    def asked(path, then, language=None):
        seen.append((arc_turning(folders.skip), paints.n))
        return ask(path, then, language)
    looks.skip_refused = asked
    folders.skip.click()
    assert seen and seen[0][0] and seen[0][1] >= 1
    assert wait_until(lambda: not win.presses.any_live() and qpress.arc(folders.skip) is None, 5)


@pytest.mark.parametrize("source, folder", [(ANIME, ANIME + r"\特典映像"), (r"D:\动画\2026秋", r"D:\动画\2026秋\花絮")])
def test_a_skip_from_the_window_is_one_change_its_line_and_count_show_and_one_undo_takes_them_back(window, source,
                                                                                                    folder):
    # Japanese and Chinese folder names: one writer change with ⋯'s toast; the skipped line and the page's count
    # follow its landing, and its Undo, with no Refresh.
    looks = ActingLooks([_src(1, source, 24)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    _picks(folders, folder)
    folders.skip.click()
    assert wait_until(lambda: calls(writer, "skip_folder"), 5)
    assert calls(writer, "skip_folder") == [("skip_folder", [], {"path": os.path.normpath(folder)})]
    name = os.path.basename(os.path.normpath(folder))
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SKIPPED.format(name=name), 5)
    assert wait_until(lambda: len(folders.skipped) == 1 and not folders.skip_box.isHidden(), 5)
    assert next(iter(folders.skipped.values())).folder["path"] == os.path.normpath(folder)
    assert row.summary.text() == " · ".join([S.SOURCES_FOLDERS_ONE, S.SOURCES_SKIPPED_N.format(n=1)])
    assert wait_until(lambda: not win.moves.tickets and not win.presses.any_live(), 5)
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: not folders.skipped and folders.skip_box.isHidden(), 5)
    assert wait_until(lambda: row.summary.text() == S.SOURCES_FOLDERS_ONE, 5)
    assert [c[0] for c in writer.calls] == ["skip_folder", "undo"]


# --- Sonic's lean B (2026-10-24, PROVISIONAL): it turns until saved; its line and Undo in this window --------------- #
def _held_check(looks):
    """The looks' pre-check held (a look under way): -> the answers waiting, call one with the store's reason."""
    waiting = []

    def ask(path, then, language=None):
        looks.skip_asks.append((path, language))
        waiting.append(then)
        return True
    looks.skip_refused = ask
    return waiting


def test_skip_a_folder_turns_until_the_skip_is_saved_then_its_line_says_so_with_the_toasts_one_undo(window):
    # A busy store: handed to the writer is not saved. The arc keeps turning (never "done" before it is), and the
    # window's own line says so once saved, with an Undo that is the toast's one Undo (no second change).
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    writer.stuck = True
    _picks(folders, OLD)
    folders.skip.click()
    assert wait_until(lambda: calls(writer, "skip_folder"), 5)
    QApplication.processEvents()
    assert win.presses.any_live() and qpress.arc(folders.skip) is not None
    assert folders.skip_said.isHidden() and folders.skip_undo.isHidden()
    folders.skip.click()                                                # a press meanwhile does nothing
    assert len(calls(writer, "skip_folder")) == 1
    writer.free()
    words = strings.ITEM_SKIPPED.format(name=os.path.basename(OLD))
    assert wait_until(lambda: not win.presses.any_live() and folders.skip_said.isVisible(), 5)
    assert folders.skip_said.text() == words and folders.skip_undo.isVisible()
    assert folders.skip_undo.text() == strings.TOAST_UNDO and folders.skip_undo.toolTip() == S.SOURCES_SKIP_UNDO_TIP
    assert wait_until(lambda: len(folders.skipped) == 1, 5)
    folders.skip_undo.click()
    assert folders.skip_said.isHidden() and folders.skip_undo.isHidden()        # at the click
    assert wait_until(lambda: not folders.skipped, 5)
    undos = [c for c in writer.calls if c[0] == "undo"]
    assert len(undos) == 1 and undos[0][2]["change"] is writer.saved[0]         # that change, once


@pytest.mark.parametrize("how", ["toast", "ctrl-z"])
def test_the_toasts_undo_or_ctrl_z_takes_the_windows_skip_line_away_too(window, how):
    # One Undo, three places to press it: whichever is pressed, the window never keeps offering an Undo of a skip
    # already taken back.
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    _picks(folders, OLD)
    folders.skip.click()
    assert wait_until(lambda: folders.skip_said.isVisible() and not win.moves.tickets, 5)
    if how == "toast":
        next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    else:
        win.moves.undo_last()
    assert wait_until(lambda: folders.skip_said.isHidden() and folders.skip_undo.isHidden(), 5)
    assert wait_until(lambda: not folders.skipped, 5)
    assert len([c for c in writer.calls if c[0] == "undo"]) == 1


def test_a_skip_that_lands_as_nothing_stops_turning_and_shows_no_line(window):
    # The store had nothing to change (skipped already, by another window): the press ends, never turning for ever.
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    writer.nothing.add("skip_folder")
    _picks(folders, OLD)
    folders.skip.click()
    assert wait_until(lambda: calls(writer, "skip_folder") and not win.presses.any_live(), 5)
    assert qpress.arc(folders.skip) is None and folders.skip_said.isHidden()
    _picks(folders, ANIME + r"\特典映像")
    writer.nothing.clear()
    folders.skip.click()                                                # it can be pressed again
    assert wait_until(lambda: len(calls(writer, "skip_folder")) == 2, 5)


def test_a_skip_behind_a_look_under_way_says_it_waits_in_the_windows_line(window):
    # H1: the pre-check waits for the look on the looks' one worker. The window says so (never silent) until it is
    # answered; the waiting words go once the skip is saved.
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    looks.busy = lambda: True
    waiting = _held_check(looks)
    _picks(folders, OLD)
    folders.skip.click()
    words = S.SOURCES_SKIP_QUEUED.format(name=os.path.basename(OLD))
    assert folders.status.text() == words and folders.status.isVisible()
    assert win.presses.any_live() and calls(writer, "skip_folder") == []
    waiting[0](None)
    assert wait_until(lambda: not win.presses.any_live() and folders.skip_said.isVisible(), 5)
    assert folders.status.text() == "" and folders.status.isHidden()


def test_a_skip_whose_library_changed_language_meanwhile_says_nothing_was_skipped(window):
    # H2: the pre-check answered after a switch to the Chinese library: nothing is written, and the press says why.
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    waiting = _held_check(looks)
    _picks(folders, OLD)
    folders.skip.click()
    win.language = "zh"
    try:
        waiting[0](None)
        assert wait_until(lambda: not win.presses.any_live(), 5)
        assert folders.status.text() == S.SOURCES_SKIP_SWITCHED
        assert calls(writer, "skip_folder") == []
    finally:
        win.language = "ja"


def test_a_skip_that_breaks_as_it_is_handed_over_never_leaves_the_press_turning(window, monkeypatch):
    # H8: an error while handing the skip to the writer ends the press (failed), so *Skip a folder…* works again.
    from app.qt import item_menu
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    _skipping(win, looks)
    looks.skip_refused = None                                           # no pre-check: handed over at once

    def broke(*_a, **_k):
        raise OSError("the writer's journal can't be written")
    monkeypatch.setattr(item_menu, "give_skip", broke)
    with pytest.raises(OSError):
        folders.skip_folder(path=OLD)
    assert not win.presses.any_live() and qpress.arc(folders.skip) is None


def test_only_a_skips_change_with_a_window_showing_it_asks_the_folders_again(window):
    # S19 (IK finding 4): every saved or undone change passes the drag controller's hook — only a skip's change (the
    # store's `folder` on it) asks the looks, and only while the folders window or the Settings page shows its lines.
    from app.qt import drag
    from tests.qt.test_drag import Change
    looks = ActingLooks([_src(1, ANIME, 412)])
    seed, win = window(looks)
    looks.on_result = win._sources_looked
    asked = []
    looks.listing = lambda: (asked.append(1), True)[1]
    skip = Change("skip_folder", [], path=OLD)
    skip.folder = 101
    assert getattr(win, "settings_page", None) is None and windows.opened(win, settings_sources.WINDOW) is None
    drag._skips_moved(win, skip)
    drag._skips_moved(win, skip, undone=True)
    assert asked == []                                                  # neither shows: nothing read
    page, row, folders = _folders_window(win)
    asked.clear()
    drag._skips_moved(win, Change("move", [3], tier="soon"))            # no skip: nothing read
    drag._skips_moved(win, None)                                        # (an undo that undid nothing)
    assert asked == []
    drag._skips_moved(win, skip)
    assert asked == [1]


def test_a_library_that_turned_read_only_while_the_skip_was_checked_says_so_in_the_window_too(window):
    # H5: the store stopped taking writes between the press and the pre-check's answer — the reason in the window he
    # pressed in (and the bar, as every refused write), nothing written, the press ended.
    looks = ActingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: 1 in folders.lines, 10)
    writer = _skipping(win, looks)
    waiting = _held_check(looks)
    _picks(folders, OLD)
    folders.skip.click()
    writer.writable = False
    waiting[0](None)
    assert wait_until(lambda: not win.presses.any_live(), 5)
    assert folders.status.text().startswith(strings.DRAG_REFUSED.split("{")[0]) and folders.status.isVisible()
    assert calls(writer, "skip_folder") == [] and folders.skip_said.isHidden()
