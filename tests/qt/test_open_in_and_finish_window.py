"""Settings › Content's *Videos open in* / *Books open in* / *When you finish something* in the window (Sonic
2026-11-05): each its name on one line and its choices under it; the program picked through the system's file dialog
(both keys in one change, nothing on a cancel, *Change…* once kept); ▶ handing the file to the program chosen, or to
the system's opener, and saying so when the program is gone. The finish toast's three ways are in test_drag.py and
test_arrivals.py (their worlds). The rules: tests/test_open_in_and_finish_settings.py."""
import os
import subprocess

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import press as qpress
from app.qt import screens, strings
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
# (never the page tests' `_no_direct_save`: here the window's own settings service writes, as in use)
from tests.qt.test_settings_page import _full_motion, _no_real_file_dialog, make_page, sp  # noqa: F401
from tests.qt.test_current import seeded  # noqa: F401  (the window over a seeded library)

MPV = "C:\\Program Files\\mpv\\mpv.exe"


def _patch_dialog(monkeypatch, answer):
    asked = []

    def dialog(parent, title, start, filters):
        asked.append((title, start, filters))
        return answer, filters
    monkeypatch.setattr(sp.QFileDialog, "getOpenFileName", dialog)
    return asked


def _choice(page, row_id):
    return page.rows[row_id].controls[0]


# --- the page ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("row_id", ["open_video", "open_book", "finish_cards"])
def test_each_row_stands_its_name_above_its_choices_at_every_width(qapp, row_id):
    """Sonic: "2 lines. One for the term and then a row or 2 for the buttons" — stacked wide and narrow alike."""
    page, _store = make_page()
    view = page.rows[row_id]
    for width in (1400, 700):
        page.resize(width, 700)
        QApplication.processEvents()
        view.arrange()
        assert view.stacked is True
        assert view.slot.geometry().top() >= view.label.geometry().bottom(), (row_id, width)
    assert view.label.text() == view.row.label and view.mark is not None           # the description behind its ?


def test_choosing_a_program_with_none_kept_asks_for_one_and_writes_both_keys_once(qapp, monkeypatch):
    page, store = make_page()
    asked = _patch_dialog(monkeypatch, "C:/Program Files/mpv/mpv.exe")
    control = _choice(page, "open_video")
    assert control.values() == ["default", "program"] and control.value() == "default"
    assert not page.rows["open_video"].change.isVisibleTo(page)                       # nothing to change yet
    store.calls.clear()
    control._choose(1)
    assert len(asked) == 1 and asked[0][0] == S.PROGRAM_PICK_TITLE["open_video"]
    assert store.calls == [({"open_video": "program", "open_video_program": os.path.normpath(
        "C:/Program Files/mpv/mpv.exe")}, None)]
    assert control.value() == "program" and control._options[1][1] == "mpv"         # named at once
    store.land()
    assert page.rows["open_video"].change.isVisibleTo(page)


def test_a_cancelled_pick_writes_nothing_and_the_choice_goes_back(qapp, monkeypatch):
    page, store = make_page()
    _patch_dialog(monkeypatch, "")
    control = _choice(page, "open_book")
    store.calls.clear()
    control._choose(1)
    assert store.calls == [] and control.value() == "default"
    assert control._options[1][1] == S.PROGRAM_PICK


def test_with_a_program_kept_the_choice_flips_alone_and_change_picks_again(qapp, monkeypatch):
    page, store = make_page({"open_video": "default", "open_video_program": MPV})
    asked = _patch_dialog(monkeypatch, "D:/Tools/vlc/vlc.exe")
    control = _choice(page, "open_video")
    assert control._options[1][1] == "mpv"
    store.calls.clear()
    control._choose(1)
    assert asked == [] and store.calls == [({"open_video": "program"}, None)]      # the kept one: no picker
    store.land()
    view = page.rows["open_video"]
    assert view.change.isVisibleTo(page) and view.change.toolTip() == S.PROGRAM_CHANGE_TIP
    view.change.click()
    assert asked[0][1] == os.path.dirname(MPV)                                       # starts where the last one is
    assert store.calls[-1] == ({"open_video_program": os.path.normpath("D:/Tools/vlc/vlc.exe")}, None)
    assert control._options[1][1] == "vlc"
    control._choose(0)
    assert store.calls[-1] == ({"open_video": "default"}, None)                       # the program stays kept


def test_the_finish_choice_writes_its_one_key(qapp):
    page, store = make_page()
    control = _choice(page, "finish_cards")
    assert [label for _v, label, _t in control._options] == ["Ask each time", "Keep its cards", "Leave them out"]
    assert all(tip for _v, _l, tip in control._options) and control.toolTip()
    store.calls.clear()
    control._choose(2)
    assert store.calls == [({"finish_cards": "out"}, None)]


# --- ▶ ------------------------------------------------------------------------------------------------------------- #
def _set(win, changes):
    """Settings changed as the page changes them, and written before the test ends (never after its root is gone)."""
    win.services.settings.set(changes)
    assert win.services.settings.flush(5)


def _play(win, monkeypatch, path, media="anime", row=0):
    """Row 0's first episode played, its lookup answering `path`; -> (programs, system) the opens asked."""
    page = win.page_widgets["current"]
    ep = page.view_model.rows[row].episodes[0]               # (a row a press: one ▶ at a time each)
    monkeypatch.setattr(screens, "media_to_open", lambda *_a: (path, None))
    monkeypatch.setattr(page, "_media_of", lambda _ep: media)
    programs, system, said = [], [], []
    monkeypatch.setattr(screens, "open_with_program", lambda program, p: programs.append((program, p)))
    monkeypatch.setattr(qpress, "open_now", system.append)
    page.message.connect(said.append)
    page._play(ep)
    assert wait_until(lambda: programs or system or said, 5)
    return programs, system, said


def test_play_hands_a_video_to_the_chosen_program_and_an_epub_to_its_own(seeded, monkeypatch):
    _seed, win = seeded()
    _set(win, {"open_video": "program", "open_video_program": MPV})
    video = "D:\\アニメ\\ぼっち・ざ・ろっく！ 第05話.mkv"
    assert _play(win, monkeypatch, video)[:2] == ([(MPV, video)], [])
    book = "D:\\本\\本好きの下剋上 第一部 1.epub"
    assert _play(win, monkeypatch, book, media="lightnovel", row=1)[:2] == ([], [book])     # *Books open in*: default


def test_play_by_default_is_the_systems_opener_and_a_link_always_is(seeded, monkeypatch):
    _seed, win = seeded()
    video = "D:\\アニメ\\ぼっち・ざ・ろっく！ 第06話.mkv"
    assert _play(win, monkeypatch, video)[:2] == ([], [video])
    _set(win, {"open_video": "program", "open_video_program": MPV})
    link = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert _play(win, monkeypatch, link, media="youtube", row=1)[:2] == ([], [link])


def test_a_program_gone_from_disk_is_said_in_the_bar_and_nothing_else_opens(seeded, monkeypatch, tmp_path):
    _seed, win = seeded()
    gone = str(tmp_path / "mpv.exe")
    _set(win, {"open_video": "program", "open_video_program": gone})
    page = win.page_widgets["current"]
    monkeypatch.setattr(screens, "media_to_open", lambda *_a: ("D:\\アニメ\\第07話.mkv", None))
    system, said = [], []
    monkeypatch.setattr(qpress, "open_now", system.append)
    page.message.connect(said.append)
    page._play(page.view_model.rows[0].episodes[0])
    assert wait_until(lambda: said, 5)
    assert system == [] and said == [strings.PLAY_FAILED.format(
        name="第07話.mkv", why=strings.PLAY_NO_PROGRAM.format(program="mpv.exe"))]


@pytest.mark.skipif(os.name != "nt", reason="Windows' rule: .exe / .com only")
@pytest.mark.parametrize("name", ["play.bat", "play.cmd", "mpv.lnk"])
def test_a_batch_file_or_shortcut_is_never_started_with_a_files_name(monkeypatch, tmp_path, name):
    """(The adversary's R2) cmd runs a .bat's line: `&` in a file's name would be a command. Hand-edited into
    settings.json, it is refused in the bar's words; typed past the picker's filter, it is never kept."""
    program = tmp_path / name
    program.write_bytes(b"@echo off")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append(args))
    with pytest.raises(OSError, match=strings.PLAY_NOT_A_PROGRAM.format(program=name).split(" isn")[0]):
        screens.open_with_program(str(program), "D:\\アニメ\\x&calc 第09話.mkv")
    assert started == []


@pytest.mark.skipif(os.name != "nt", reason="Windows' rule: .exe / .com only")
def test_a_non_program_typed_into_the_picker_writes_nothing(qapp, monkeypatch):
    page, store = make_page()
    _patch_dialog(monkeypatch, "C:/Tools/play.bat")
    store.calls.clear()
    _choice(page, "open_video")._choose(1)
    assert store.calls == [] and _choice(page, "open_video").value() == "default"


def test_the_program_gets_the_file_as_its_one_argument_and_no_shell(monkeypatch, tmp_path):
    program = tmp_path / "mpv.exe"
    program.write_bytes(b"MZ")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append((args, kw)))
    path = "D:\\アニメ\\ぼっち & ろっく\" 第08話.mkv"                                 # quotes and & reach it as written
    screens.open_with_program(str(program), path)
    (args, kw), = started
    assert args == [str(program), path] and not kw.get("shell")
