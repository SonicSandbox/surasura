"""Report a problem in the window (`app/qt/report.py`; the scope `tracks/ship/work/report/scope.md`).

What a wrong answer would cost: the bug not where Sonic asked (the header's top right), or a picture of the screen —
another program, the tester's desktop — instead of Surasura's own window; a picture taken after the report window
already covers what went wrong; a tester's notes lost or the list emptied by a zip that wasn't made; a control with no
tip or no name; the window's thread waiting on the disk; the zip's folder not opened.
"""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget

from app import report as core
from app.qt import report as report_ui
from app.qt import screens, shell, strings, windows
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems

JA_WHAT = "Finishedに入れた「葬送のフリーレン」がCurrentに戻ってしまった"
ZH_WHAT = "生词本里的“风景”显示了两次"


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def opened(monkeypatch):
    """The system's own opener stood in for (no Explorer window in a test): what it was asked to open."""
    asked = []
    monkeypatch.setattr(screens, "open_with_system", lambda path: asked.append(path))
    return asked


def _press(main):
    main.report_button.click()
    w = windows.opened(main, report_ui.NAME)
    assert w is not None
    assert wait_until(lambda: w.reports is not None)
    return w


def _save(w, what, expected=""):
    w.what.setPlainText(what)
    w.expected.setPlainText(expected)
    n = len(w.reports or [])
    w.save_button.click()
    assert wait_until(lambda: w.reports is not None and len(w.reports) == n + 1)


# --- the bug ---------------------------------------------------------------------------------------------------- #
def test_the_bug_is_the_headers_rightmost_control_after_help(main):
    row = main.header.layout()
    widgets = [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget() is not None]
    assert widgets[-1] is main.report_button                           # Sonic: "top right"
    if getattr(main, "duties", None) is not None and getattr(main.duties, "help", None) is not None:
        assert widgets[-2] is main.duties.help                         # ? keeps its place, just left of the bug


def test_the_bug_is_painted_named_and_tipped_with_its_count(main):
    b = main.report_button
    assert b.text() == "" and b.icon().isNull()                        # painted, never a picture
    assert b.accessibleName() == strings.REPORT_NAME
    assert b.toolTip().startswith(strings.REPORT_NAME)                 # an icon-only control's tip names it first
    side = b.sizeHint()
    assert b.set_count(3) is True and b.set_count(3) is False          # repainted only when the count changed
    assert "3 saved" in b.toolTip() and b.sizeHint().width() > side.width()
    b.set_count(0)
    assert b.toolTip() == strings.REPORT_TIP and b.sizeHint() == side


def test_the_bug_draws_inside_its_box_at_every_scale(main):
    for side in (32, 48, 64):                                          # 100 %, 150 %, 200 %
        body, paths = report_ui.bug_path(side / 2, side / 2, side)
        box = body
        for p in paths:
            box = box.united(p.boundingRect())
        assert 0 < box.left() and box.right() < side and 0 < box.top() and box.bottom() < side
        assert abs((box.left() + box.right()) / 2 - side / 2) < 0.01  # centred: both sides drawn the same


# --- the picture ------------------------------------------------------------------------------------------------ #
def test_the_picture_is_taken_before_the_window_opens_and_is_only_surasuras_window(main, monkeypatch):
    grabbed = []
    real = QWidget.grab

    def watch(self, *a):
        grabbed.append((self, windows.opened(main, report_ui.NAME)))  # the report window open yet?
        return real(self, *a)
    monkeypatch.setattr(QWidget, "grab", watch)
    w = _press(main)
    assert grabbed and grabbed[0] == (main, None)                     # the main window's own picture, first, before
    assert len(w.pictures) == 1
    img, own = w.pictures[0], real(main).toImage()
    assert img.size() == own.size()                                    # exactly the window: never the screen around it


def test_another_open_surasura_window_is_pictured_too_but_not_menus_or_the_report_window(main):
    other = windows.SecondaryWindow(main, "Anki")
    other.show()
    try:
        got = report_ui.surasura_windows(main)
        assert got[0] is main and other in got
        w = _press(main)
        assert len(w.pictures) == 2
        assert all(not isinstance(x, report_ui.ReportWindow) for x in report_ui.surasura_windows(main))
    finally:
        other.close()


def test_pressing_the_bug_again_retakes_the_picture_in_the_open_window(main):
    w = _press(main)
    w.pictures = []
    main.report_button.click()
    assert windows.opened(main, report_ui.NAME) is w and len(w.pictures) == 1


# --- the window ------------------------------------------------------------------------------------------------- #
def test_every_control_is_wired_tipped_and_named_and_esc_closes_it(main):
    w = _press(main)
    found, walked = problems(w)
    assert walked >= 8 and found == []
    assert w.windowTitle() == "Report a problem — Surasura"
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert wait_until(lambda: windows.opened(main, report_ui.NAME) is None)
    assert main.isVisible()                                            # Esc never closes the main window


def test_save_needs_words_then_lists_it_counts_it_on_the_bug_and_clears_the_form(main):
    w = _press(main)
    assert not w.save_button.isEnabled() and not w.zip_button.isEnabled()
    _save(w, JA_WHAT, "Finishedに残ると思った")
    assert w.what.toPlainText() == "" and w.expected.toPlainText() == ""
    assert main.report_button.count == 1 and w.zip_button.isEnabled()
    r = core.listed()[0]
    assert r.what == JA_WHAT and r.pictures == ["picture-1.png"] and r.where.startswith("the ")
    assert w.list_heading.text() == strings.REPORT_LIST_HEADING.format(n=1)


def test_leave_the_picture_out_saves_no_picture(main):
    w = _press(main)
    w.leave_out.setChecked(True)
    _save(w, ZH_WHAT)
    assert core.listed()[0].pictures == []


def test_the_list_survives_closing_the_window_and_the_count_is_read_back(main):
    w = _press(main)
    _save(w, JA_WHAT)
    _save(w, ZH_WHAT)
    w.close()
    main.report_button.set_count(0)
    main.report_button.refresh()                                       # as after a restart's first frame
    assert wait_until(lambda: main.report_button.count == 2)
    w = _press(main)
    assert [r.what for r in w.reports] == [JA_WHAT, ZH_WHAT]


def test_open_shows_a_report_and_a_note_is_added_to_it(main):
    w = _press(main)
    _save(w, ZH_WHAT, "应该只显示一次")
    w.open(w.reports[0].id)
    assert w.pages.currentIndex() == w.OPENED
    assert ZH_WHAT in w.opened_text.toPlainText() and "应该只显示一次" in w.opened_text.toPlainText()
    w.note.setPlainText("换成繁体以后也一样")
    w.note_button.click()
    assert wait_until(lambda: w.reports and len(w.reports[0].notes) == 1)
    assert core.listed()[0].notes[0]["text"] == "换成繁体以后也一样"


def test_remove_then_undo(main):
    w = _press(main)
    _save(w, JA_WHAT)
    w.remove(w.reports[0].id)
    assert wait_until(lambda: w.reports == [])
    assert main.report_button.count == 0 and w.undo_button.isVisible()
    w.undo_button.click()
    assert wait_until(lambda: w.reports and len(w.reports) == 1)
    assert not w.undo_button.isVisible()


def test_show_me_lists_every_file_before_the_zip(main):
    w = _press(main)
    _save(w, JA_WHAT)
    w.show_button.click()
    assert wait_until(lambda: w.pages.currentIndex() == w.CONTENTS)
    text = w.contents.toPlainText()
    assert f"reports/{w.reports[0].id}/report.txt" in text and "library/summary.json" in text and "Left out:" in text


def test_make_the_zip_writes_it_where_asked_opens_that_folder_and_empties_the_list(main, opened, tmp_path):
    w = _press(main)
    _save(w, JA_WHAT)
    _save(w, ZH_WHAT)
    w.dest = str(tmp_path / "picked")
    w.include_results.setChecked(False)
    w.zip_button.click()
    assert wait_until(lambda: w.reports == [])
    made = [n for n in os.listdir(tmp_path / "picked") if n.endswith(".zip")]
    assert len(made) == 1
    assert wait_until(lambda: opened == [str(tmp_path / "picked")])    # the folder opened (on a worker)
    with zipfile.ZipFile(tmp_path / "picked" / made[0]) as z:
        names = z.namelist()
    assert sum(n.endswith("/report.txt") for n in names) == 2 and not any(n.startswith("results/") for n in names)
    assert main.report_button.count == 0
    assert strings.REPORT_ZIPPED.format(name=made[0], folder=str(tmp_path / "picked")) == w.status.text()


def test_a_zip_that_fails_keeps_the_list_and_says_why(main, monkeypatch, tmp_path):
    w = _press(main)
    _save(w, JA_WHAT)

    def unplugged(*a, **k):
        raise OSError("the drive was unplugged")
    monkeypatch.setattr(core, "make_zip", unplugged)
    w.zip_button.click()
    assert wait_until(lambda: "unplugged" in w.status.text())
    assert len(core.listed()) == 1 and main.report_button.count == 1


def test_change_picks_the_zips_folder(main, monkeypatch, tmp_path):
    w = _press(main)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    w.change_button.click()
    assert w.dest == os.path.normpath(str(tmp_path)) and str(tmp_path) in w.dest_line.text()


def test_the_zip_goes_to_downloads_by_default():
    assert os.path.isdir(report_ui.downloads())


def test_the_library_summary_holds_counts_and_folders_never_titles(main):
    got = report_ui.library_summary(main)
    assert got["language"] in ("ja", "zh")
    assert set(got) <= {"language", "counts", "state", "mode", "library", "sources"}


# --- the review round's finds ------------------------------------------------------------------------------------ #
def test_a_shown_key_is_never_drawn_in_the_picture(main, monkeypatch):
    # The adversary's A2: Jiten's window with its key shown (*Show*): the picture is taken with the field as dots, and
    # the field is shown again afterwards.
    from PyQt6.QtWidgets import QLineEdit
    other = windows.SecondaryWindow(main, "Jiten")
    key = QLineEdit(other)
    key.setAccessibleName(strings.JITEN_KEY_NAME)
    key.setText("jiten-sk-1234567890")
    key.setEchoMode(QLineEdit.EchoMode.Normal)
    other.body.addWidget(key)
    other.show()
    seen = []
    real = QWidget.grab

    def watch(self, *a):
        if self is other:
            seen.append(key.echoMode())
        return real(self, *a)
    monkeypatch.setattr(QWidget, "grab", watch)
    try:
        report_ui.take_pictures(main)
        assert seen == [QLineEdit.EchoMode.Password]
        assert key.echoMode() == QLineEdit.EchoMode.Normal and key.text() == "jiten-sk-1234567890"
    finally:
        other.close()


def test_esc_keeps_what_was_typed_for_the_next_press(main):
    w = _press(main)
    w.what.setPlainText(JA_WHAT)
    w.expected.setPlainText("戻らないと思った")
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert wait_until(lambda: windows.opened(main, report_ui.NAME) is None)
    w = _press(main)
    assert w.what.toPlainText() == JA_WHAT and w.expected.toPlainText() == "戻らないと思った"
    _save(w, w.what.toPlainText())
    w.close()
    w = _press(main)
    assert w.what.toPlainText() == ""                                  # saved: the draft is gone


def test_the_tick_hides_the_pictures_without_rebuilding_them(main):
    w = _press(main)
    thumbs = list(w._thumbs)
    w.leave_out.setChecked(True)
    assert all(t.isHidden() for t in thumbs) and w.picture_note.text() == strings.REPORT_NO_PICTURE
    w.leave_out.setChecked(False)
    assert w._thumbs == thumbs and not any(t.isHidden() for t in thumbs) and w.picture_note.isHidden()


def test_a_note_that_fails_keeps_what_was_typed(main, monkeypatch):
    w = _press(main)
    _save(w, ZH_WHAT)
    w.open(w.reports[0].id)

    def full(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(core, "add_note", full)
    w.note.setPlainText("这条备注不能丢")
    w.note_button.click()
    assert wait_until(lambda: "disk full" in w.status.text())
    assert w.note.toPlainText() == "这条备注不能丢"


def test_undo_says_so_when_the_report_couldnt_come_back(main, monkeypatch):
    w = _press(main)
    _save(w, JA_WHAT)
    w.remove(w.reports[0].id)
    assert wait_until(lambda: w.reports == [])
    monkeypatch.setattr(core, "restore", lambda rid: False)
    w.undo_button.click()
    assert wait_until(lambda: w.status.text() == strings.REPORT_NOT_RESTORED)


def test_a_zip_finished_after_the_window_closed_is_said_in_the_main_bar(main, opened, tmp_path, monkeypatch):
    import threading
    w = _press(main)
    _save(w, JA_WHAT)
    w.dest = str(tmp_path)
    gate = threading.Event()
    real = core.make_zip

    def slow(*a, **k):
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(core, "make_zip", slow)
    w.zip_button.click()
    assert not w.list.isEnabled()                                      # the list waits while the zip is made
    w.close()
    gate.set()
    assert wait_until(lambda: main.bar_line.full().startswith("Made Surasura-problems-"))
    assert wait_until(lambda: opened == [str(tmp_path)]) and core.listed() == []
    assert wait_until(lambda: main.report_button.count == 0)


# --- 3.0: where it goes — Surasura's Discord, or GitHub Issues ----------------------------------------------------- #
@pytest.fixture
def sent(monkeypatch):
    """Explorer's `/select,` and the browser stood in for: [("show", zip path) | ("url", link)], in the order asked."""
    asked = []
    monkeypatch.setattr(screens, "show_in_folder", lambda path: asked.append(("show", path)))
    monkeypatch.setattr(windows, "open_url", lambda url: asked.append(("url", url)) or True)
    return asked


def test_send_on_discord_waits_for_words_then_is_tipped_as_what_it_does(main):
    w = _press(main)
    assert not w.discord_button.isEnabled() and w.discord_button.toolTip() == strings.REPORT_DISCORD_NONE_TIP
    w.what.setPlainText(JA_WHAT)                                       # words typed: ready (they're saved first)
    assert w.discord_button.isEnabled() and w.discord_button.toolTip() == strings.REPORT_DISCORD_TIP
    w.what.setPlainText("")
    assert not w.discord_button.isEnabled()
    _save(w, ZH_WHAT)                                                  # a saved report: ready with the form empty
    assert w.discord_button.isEnabled() and w.discord_button.property("kind") == "primary"


def test_send_on_discord_saves_whats_typed_makes_the_zip_shows_it_selected_then_opens_the_invite(main, sent, tmp_path):
    from app.qt import settings_strings
    w = _press(main)
    _save(w, ZH_WHAT)
    w.what.setPlainText(JA_WHAT)                                       # typed, not saved: it goes in the zip too
    w.dest = str(tmp_path)
    w.include_results.setChecked(False)
    w.discord_button.click()
    assert wait_until(lambda: len(sent) == 2)
    made = [n for n in os.listdir(tmp_path) if n.endswith(".zip")]
    assert len(made) == 1
    assert sent == [("show", str(tmp_path / made[0])), ("url", settings_strings.DISCORD_URL)]   # the folder, then on top
    with zipfile.ZipFile(tmp_path / made[0]) as z:
        assert sum(n.endswith("/report.txt") for n in z.namelist()) == 2
    assert wait_until(lambda: w.reports == [] and w.status.text() == strings.REPORT_SENT.format(name=made[0]))
    assert w.what.toPlainText() == "" and main.report_button.count == 0


def test_a_folder_that_cant_be_shown_still_opens_the_invite(main, monkeypatch, tmp_path):
    from app.qt import settings_strings
    opened = []

    def no_explorer(path):
        raise OSError("explorer.exe is missing")
    monkeypatch.setattr(screens, "show_in_folder", no_explorer)
    monkeypatch.setattr(windows, "open_url", lambda url: opened.append(url) or True)
    w = _press(main)
    _save(w, JA_WHAT)
    w.dest = str(tmp_path)
    w.discord_button.click()
    assert wait_until(lambda: opened == [settings_strings.DISCORD_URL])


def test_a_discord_zip_finished_after_the_window_closed_still_shows_it_and_opens_the_invite(main, sent, tmp_path,
                                                                                           monkeypatch):
    import threading
    from app.qt import settings_strings
    w = _press(main)
    _save(w, JA_WHAT)
    w.dest = str(tmp_path)
    gate = threading.Event()
    real = core.make_zip

    def slow(*a, **k):
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(core, "make_zip", slow)
    w.discord_button.click()
    w.close()
    gate.set()
    assert wait_until(lambda: main.bar_line.full().startswith("Made Surasura-problems-"))
    assert wait_until(lambda: [k for k, _v in sent] == ["show", "url"]) and sent[1][1] == settings_strings.DISCORD_URL


def test_the_window_says_where_to_send_it_and_what_the_zip_holds(main, sent):
    from app.qt import settings_strings
    w = _press(main)
    assert w.send_where.text() == strings.REPORT_SEND_WHERE and "bug-report channel" in strings.REPORT_SEND_WHERE
    for said in ("logs", "settings", "titles in your library"):
        assert said in w.hint.text()
    assert "Sonic" not in strings.REPORT_ZIPPED and "Discord" in strings.REPORT_ZIPPED
    assert w.issues_button.toolTip() == strings.REPORT_ISSUES_TIP
    w.issues_button.click()                                            # the quieter way: GitHub Issues, in the browser
    assert wait_until(lambda: sent == [("url", settings_strings.ISSUES_URL)])


def test_show_in_folder_asks_explorer_to_select_the_zip(monkeypatch, tmp_path):
    """Explorer's `/select,` with the path quoted (a folder with spaces); off Windows the folder itself."""
    import subprocess
    import sys
    asked = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **k: asked.append(cmd))
    path = str(tmp_path / "My Downloads" / "Surasura-problems-2026-10-30-120000.zip")
    monkeypatch.setattr(sys, "platform", "win32")
    screens.show_in_folder(path)
    assert asked == [f'explorer /select,"{os.path.normpath(path)}"']


def test_the_invite_and_issues_links_are_the_ones_checked():
    from app.qt import settings_strings
    assert settings_strings.DISCORD_URL == "https://surasura.dev/app/discord"     # 3.0.0: redirects to the invite
    assert settings_strings.WEBSITE_URL == "https://surasura.dev"
    assert settings_strings.LINK_URLS["discord"] == settings_strings.DISCORD_URL
    assert settings_strings.LINK_URLS["website"] == settings_strings.WEBSITE_URL
    assert settings_strings.ISSUES_URL == "https://github.com/SonicSandbox/surasura/issues"


def test_a_first_report_typed_then_sent_keeps_the_button_working_through_its_save_and_zip(main, sent, tmp_path,
                                                                                          monkeypatch):
    """Nothing saved yet, words typed, *Send on Discord*: the form clears as it saves, yet the button stays enabled
    with its arc on until the zip is made (an arc never turns on a greyed button)."""
    import threading
    from app.qt import settings_strings
    w = _press(main)
    w.dest = str(tmp_path)
    gate = threading.Event()
    real = core.make_zip

    def slow(*a, **k):
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(core, "make_zip", slow)
    w.what.setPlainText(JA_WHAT)
    w.discord_button.click()
    assert wait_until(lambda: w.what.toPlainText() == "")                # saved: the form cleared
    assert w.sending and w.discord_button.isEnabled()
    gate.set()
    assert wait_until(lambda: [k for k, _v in sent] == ["show", "url"]) and sent[1][1] == settings_strings.DISCORD_URL
    assert wait_until(lambda: w.reports == [] and not w.discord_button.isEnabled() and not w.sending)


def test_send_while_a_zip_is_being_made_saves_nothing_and_says_so(main, sent, opened, tmp_path, monkeypatch):
    import threading
    w = _press(main)
    _save(w, ZH_WHAT)
    w.dest = str(tmp_path)
    gate = threading.Event()
    real = core.make_zip

    def slow(*a, **k):
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(core, "make_zip", slow)
    w.zip_button.click()
    w.what.setPlainText(JA_WHAT)
    w.discord_button.click()
    assert w.status.text() == strings.REPORT_ZIP_BUSY and w.what.toPlainText() == JA_WHAT   # kept, never saved
    assert not w.list.isEnabled()                                      # the first zip still holds the list
    gate.set()
    assert wait_until(lambda: w.reports == [] and w.list.isEnabled())
    assert sent == [] and len(core.listed()) == 0 and wait_until(lambda: opened == [str(tmp_path)])
