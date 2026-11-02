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


@pytest.fixture
def sent(monkeypatch):
    """Explorer's `/select,` and the browser stood in for: [("show", zip path) | ("url", link)], in the order asked."""
    asked = []
    monkeypatch.setattr(screens, "show_in_folder", lambda path: asked.append(("show", path)))
    monkeypatch.setattr(windows, "open_url", lambda url: asked.append(("url", url)) or True)
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


def test_make_a_zip_instead_writes_it_where_asked_shows_it_selected_offers_the_invite_and_empties_the_list(
        main, sent, tmp_path):
    w = _press(main)
    _save(w, JA_WHAT)
    _save(w, ZH_WHAT)
    assert w.dest_line.isHidden()                                      # the zip's folder: shown once one is made
    w.dest = str(tmp_path / "picked")
    w.include_results.setChecked(False)
    w.zip_button.click()
    assert wait_until(lambda: w.reports == [])
    made = [n for n in os.listdir(tmp_path / "picked") if n.endswith(".zip")]
    assert len(made) == 1
    assert wait_until(lambda: sent == [("show", str(tmp_path / "picked" / made[0]))])   # selected (on a worker)
    assert not w.dest_line.isHidden() and not w.invite_button.isHidden() and w.copy_button.isHidden()
    assert w.invite_button.text() == strings.REPORT_INVITE_ZIP          # offered, never opened by itself
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


def test_a_zip_finished_after_the_window_closed_is_said_in_the_main_bar(main, sent, tmp_path, monkeypatch):
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
    assert wait_until(lambda: [k for k, _v in sent] == ["show"]) and core.listed() == []
    assert wait_until(lambda: main.report_button.count == 0)


# --- 3.0: Send report (alpha 10; SPEC §3: press → look → Send), against a fake receiver on loopback ---------------- #
@pytest.fixture
def receiver(monkeypatch):
    """The fake receiver of `tests/test_send_report.py` (127.0.0.1, records each request); Send report pointed at it."""
    from app import telemetry
    from tests.test_send_report import Receiver
    r = Receiver()
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": r.url)
    yield r
    r.close()


def _send_state():
    from app import send_report
    return send_report.waiting(), send_report.sent_reports()


def _outbox_empty():
    """Nothing waiting, looked at without opening a file (a read racing a delete is refused on Windows)."""
    from app import path_utils, send_report
    folder = os.path.join(path_utils.persistent_root(), send_report.OUTBOX_DIR)
    return not os.path.exists(os.path.join(folder, send_report.OUTBOX_META))


def _look(w):
    """Send report pressed: wait for What goes."""
    w.send_button.click()
    assert wait_until(lambda: w.pages.currentIndex() == w.GOES, 15)


def test_send_report_is_the_main_button_and_says_the_promise_always(main):
    w = _press(main)
    assert w.send_button.property("kind") == "primary" and w.zip_button.property("kind") != "primary"
    assert w.send_button.text() == "Send report" and w.zip_button.text() == "Make a zip instead"
    assert not w.send_button.isEnabled() and w.send_button.toolTip() == strings.REPORT_SEND_NONE_TIP
    assert w.promise.text() == "No personal data or identification is included" and not w.promise.isHidden()
    w.what.setPlainText(JA_WHAT)                                       # words typed: ready (they're saved first)
    assert w.send_button.isEnabled() and w.send_button.toolTip() == strings.REPORT_SEND_TIP
    w.what.setPlainText("")
    assert not w.send_button.isEnabled()
    _save(w, ZH_WHAT)                                                  # a saved report: ready with the form empty
    assert w.send_button.isEnabled() and not w.promise.isHidden()
    assert not hasattr(w, "discord_button")                            # SR-Q1: Send report takes its place


def test_a_typed_discord_name_is_said_to_go_and_is_at_most_32_characters(main):
    w = _press(main)
    assert w.name_goes.isHidden()
    w.name_field.setText("風景_0429")
    assert not w.name_goes.isHidden() and w.name_goes.text() == strings.REPORT_NAME_GOES
    w.name_field.setText("   ")
    assert w.name_goes.isHidden()                                      # spaces only: nothing goes
    w.name_field.setText("x" * 40)
    assert len(w.name_field.text()) == 32


def test_press_look_then_send_saves_whats_typed_shows_what_goes_and_sends_only_on_send(main, receiver):
    w = _press(main)
    w.include_results.setChecked(False)
    w.what.setPlainText(JA_WHAT)                                       # typed, not saved: saved first
    _look(w)
    assert receiver.got == []                                          # nothing has left the PC
    rid = core.listed()[0].id
    assert f"reports/{rid}/report.txt" in w.goes_files.text() and "MANIFEST.txt" in w.goes_files.text()
    assert "<you>" in w.goes_placeholders.text() and w.goes_name.text() == strings.REPORT_GOES_NO_NAME
    assert w.goes_kept.text() == "Kept privately for 90 days, seen only by Surasura's developer, then deleted."
    assert wait_until(lambda: w.goes_sender.text().startswith("Your reports are grouped as "))
    assert w.waiting_line.isHidden()                                   # (that zip is the page's, not "waiting")
    nonce = w.outbox.nonce
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == "Sent. Your report is #K3Q7PM", 15)
    assert len(receiver.got) == 1 and receiver.got[0]["path"] == "/report"
    headers = {k.lower(): v for k, v in receiver.got[0]["headers"].items()}
    assert headers["x-report-nonce"] == nonce and "x-discord-name" not in headers
    assert wait_until(lambda: w.reports == [] and main.report_button.count == 0)
    assert w.pages.currentIndex() == w.FORM and w.what.toPlainText() == ""
    assert not w.copy_button.isHidden() and not w.invite_button.isHidden()
    assert w.invite_button.text() == strings.REPORT_INVITE
    waiting, sent = _send_state()
    assert waiting is None and [s[0] for s in sent] == ["K3Q7PM"]
    assert wait_until(lambda: not w.sent_heading.isHidden() and w.sent_rows.count() == 1)


def test_copy_puts_the_id_on_the_clipboard_and_the_invite_opens_the_one_link(main, receiver, sent):
    from app.qt import settings_strings
    w = _press(main)
    _save(w, ZH_WHAT)
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: w.sent_id == "K3Q7PM", 15)
    w.copy_button.click()
    assert QApplication.clipboard().text() == "#K3Q7PM" and w.status.text() == "Copied #K3Q7PM"
    w.invite_button.click()
    assert wait_until(lambda: sent == [("url", settings_strings.DISCORD_URL)])


def test_back_from_what_goes_sends_nothing_and_leaves_nothing_waiting(main, receiver):
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    w.goes_back.click()
    assert w.pages.currentIndex() == w.FORM
    assert wait_until(_outbox_empty)
    assert receiver.got == [] and len(core.listed()) == 1 and w.waiting_line.isHidden()


def test_the_discord_name_goes_only_when_typed_shows_on_what_goes_and_is_remembered(main, receiver):
    import base64
    w = _press(main)
    _save(w, JA_WHAT)
    w.name_field.setText("ゆき#0429")
    _look(w)
    assert w.goes_name.text() == "Discord name: ゆき#0429"
    w.goes_send.click()
    assert wait_until(lambda: len(receiver.got) == 1, 15)
    sent_name = {k.lower(): v for k, v in receiver.got[0]["headers"].items()}["x-discord-name"]
    assert base64.urlsafe_b64decode(sent_name + "=" * (-len(sent_name) % 4)).decode("utf-8") == "ゆき#0429"
    assert wait_until(lambda: w.reports == [])
    w.close()
    w = _press(main)
    assert wait_until(lambda: w.name_field.text() == "ゆき#0429")      # remembered on this PC


def test_no_connection_keeps_the_report_waiting_and_send_now_sends_the_same_one(main, receiver, monkeypatch):
    from app import telemetry
    from tests.test_send_report import Receiver
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    nonce = w.outbox.nonce
    dead = Receiver()
    dead.close()                                                       # nothing listens there any more
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": dead.url)
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == strings.REPORT_SEND_OFFLINE, 20)
    assert len(core.listed()) == 1 and w.pages.currentIndex() == w.FORM
    assert wait_until(lambda: not w.waiting_line.isHidden() and w.waiting_line.text() == "1 report waiting to send")
    assert receiver.got == []
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": receiver.url)
    w.send_now_button.click()                                          # online again: a press, never by itself
    assert wait_until(lambda: w.status.text() == "Sent. Your report is #K3Q7PM", 15)
    headers = {k.lower(): v for k, v in receiver.got[0]["headers"].items()}
    assert headers["x-report-nonce"] == nonce                          # the same report: the same #ID
    assert wait_until(lambda: w.reports == [] and w.waiting_line.isHidden())


def test_a_window_opened_with_a_report_waiting_sends_nothing_by_itself(main, receiver):
    from app import send_report
    w = _press(main)
    _save(w, JA_WHAT)
    w.close()
    send_report.build(windows.language_of(main), include_results=False)
    w = _press(main)
    assert wait_until(lambda: not w.waiting_line.isHidden())
    for _ in range(20):
        QApplication.processEvents()
    assert receiver.got == []                                          # Q4: never sent again by itself


def test_dont_send_deletes_the_waiting_zip_and_keeps_the_list(main, receiver):
    from app import send_report
    w = _press(main)
    _save(w, JA_WHAT)
    w.close()
    send_report.build(windows.language_of(main), include_results=False)
    w = _press(main)
    assert wait_until(lambda: not w.waiting_line.isHidden())
    w.dont_send_button.click()
    assert wait_until(lambda: w.waiting_line.isHidden() and w.status.text() == strings.REPORT_DISCARDED)
    assert send_report.waiting() is None and len(core.listed()) == 1 and receiver.got == []


@pytest.mark.parametrize("status, words", [
    (429, strings.REPORT_SEND_BUSY),
    (503, strings.REPORT_SEND_PAUSED),
    (413, strings.REPORT_SEND_TOO_BIG),
    (400, strings.REPORT_SEND_REFUSED.format(status=400)),
])
def test_each_refusal_is_said_in_plain_words_and_the_report_is_kept(main, receiver, status, words):
    receiver.answer = (status, {"error": "x"})
    w = _press(main)
    _save(w, ZH_WHAT)
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == words, 15)
    assert len(core.listed()) == 1 and _send_state()[0] is not None


def test_the_sixth_send_of_a_day_is_refused_before_anything_is_made(main, receiver):
    import datetime
    import json
    from app import path_utils, send_report
    with open(os.path.join(path_utils.get_persistent_user_data_path(), send_report.STATE_FILE), "w",
              encoding="utf-8") as f:
        json.dump({"day": datetime.datetime.now().astimezone().date().isoformat(), "sent": 5}, f)
    w = _press(main)
    _save(w, JA_WHAT)
    w.send_button.click()
    assert wait_until(lambda: w.status.text() == "You've sent 5 today. Send it tomorrow, or make a zip instead")
    assert w.pages.currentIndex() == w.FORM and send_report.waiting() is None and receiver.got == []


@pytest.mark.parametrize("raised, words", [("unsafe", strings.REPORT_SEND_UNSAFE),
                                           ("too big", strings.REPORT_SEND_TOO_BIG)])
def test_a_report_the_check_refuses_or_too_big_is_never_offered(main, receiver, monkeypatch, raised, words):
    from app import send_report

    def refuse(*a, **k):
        raise core.Unsafe(["logs/app_debug_log.txt"]) if raised == "unsafe" else send_report.TooBig("12 MB")
    monkeypatch.setattr(send_report, "build", refuse)
    w = _press(main)
    _save(w, JA_WHAT)
    w.send_button.click()
    assert wait_until(lambda: w.status.text() == words)
    assert w.pages.currentIndex() == w.FORM and receiver.got == [] and len(core.listed()) == 1


def test_esc_while_it_sends_lets_it_finish_and_the_main_bar_says_so(main, receiver):
    receiver.sleep = 0.6
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    w.goes_send.click()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert wait_until(lambda: windows.opened(main, report_ui.NAME) is None)
    assert wait_until(lambda: main.bar_line.full() == "Sent. Your report is #K3Q7PM", 15)
    assert core.listed() == [] and wait_until(lambda: main.report_button.count == 0)


def test_closing_what_goes_unsent_deletes_its_zip(main, receiver):
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    w.close()
    assert wait_until(_outbox_empty)
    assert receiver.got == [] and len(core.listed()) == 1


def test_the_sender_code_shows_and_new_code_makes_another(main):
    from app import send_report
    w = _press(main)
    assert wait_until(lambda: w.sender_line.text().startswith("Your reports are grouped as "))
    old = w.sender_line.text().rsplit(" ", 1)[1]
    assert old == send_report.sender_code() and w.new_code_button.isEnabled()
    w.new_code_button.click()
    assert wait_until(lambda: w.sender_line.text().rsplit(" ", 1)[1] != old)
    assert w.sender_line.text().rsplit(" ", 1)[1] == send_report.sender_code()


def test_send_while_a_zip_is_being_made_saves_nothing_and_says_so(main, sent, tmp_path, monkeypatch):
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
    w.send_button.click()
    assert w.status.text() == strings.REPORT_ZIP_BUSY and w.what.toPlainText() == JA_WHAT   # kept, never saved
    assert not w.list.isEnabled()                                      # the first zip still holds the list
    gate.set()
    assert wait_until(lambda: w.reports == [] and w.list.isEnabled())
    assert len(core.listed()) == 0 and wait_until(lambda: [k for k, _v in sent] == ["show"])


def test_the_window_says_what_a_report_holds_and_github_is_the_quieter_way(main, sent):
    from app.qt import settings_strings
    w = _press(main)
    for said in ("logs", "settings", "titles in your library", "Windows name"):
        assert said in w.hint.text()
    assert w.send_where.text() == strings.REPORT_SEND_WHERE and "Make a zip instead" in strings.REPORT_SEND_WHERE
    assert w.issues_button.toolTip() == strings.REPORT_ISSUES_TIP
    w.issues_button.click()                                            # the quieter way: GitHub Issues, in the browser
    assert wait_until(lambda: sent == [("url", settings_strings.ISSUES_URL)])


def test_a_picture_taken_once_the_scrub_is_ready_is_saved_marked_and_one_before_is_not(main):
    from app import scrub
    scrub.identity()                                                   # ready (the first frame's worker)
    w = _press(main)
    assert w.scrubbed
    _save(w, JA_WHAT)
    assert core.listed()[0].scrubbed
    w.close()
    import threading
    for t in threading.enumerate():                                    # (a first frame's worker, finished first)
        if t.name == "scrub-identity":
            t.join(10)
    scrub.reset()                                                      # not ready yet: the picture isn't marked
    w = _press(main)
    assert not w.scrubbed
    _save(w, ZH_WHAT)
    assert [r.scrubbed for r in core.listed()] == [True, False]


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


# --- the review's round (tracks/window/reviews/send-report-adversary.md) ------------------------------------------- #
def test_esc_while_the_report_is_made_keeps_nothing_waiting_and_sends_nothing(main, receiver, monkeypatch):
    # The adversary's 1: closed before What goes, the zip it made is deleted — never offered as "waiting" to Send now.
    import threading
    from app import send_report
    gate = threading.Event()
    real = send_report.build

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(send_report, "build", slow)
    w = _press(main)
    _save(w, JA_WHAT)
    w.send_button.click()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert wait_until(lambda: windows.opened(main, report_ui.NAME) is None)
    gate.set()
    assert wait_until(lambda: not any(t.name == "report-discard" for t in threading.enumerate()) and _outbox_empty())
    w = _press(main)
    assert wait_until(lambda: w.sender_line.text() != "")
    assert w.waiting_line.isHidden() and receiver.got == [] and len(core.listed()) == 1


def test_a_refused_press_never_deletes_a_report_already_waiting(main, receiver, monkeypatch):
    # The adversary's 6a: the 6th send of a day makes nothing; a zip already waiting from a failed send stays.
    import datetime
    import json
    from app import path_utils, send_report
    w = _press(main)
    _save(w, JA_WHAT)
    w.close()
    ob = send_report.build(windows.language_of(main), include_results=False)
    with open(os.path.join(path_utils.get_persistent_user_data_path(), send_report.STATE_FILE), "w",
              encoding="utf-8") as f:
        json.dump({"day": datetime.datetime.now().astimezone().date().isoformat(), "sent": 5}, f)
    w = _press(main)
    w.send_button.click()
    QTest.keyClick(w, Qt.Key.Key_Escape)                               # closed before the answer, too
    assert wait_until(lambda: windows.opened(main, report_ui.NAME) is None)
    for _ in range(30):
        QApplication.processEvents()
    assert send_report.waiting() is not None and send_report.waiting().sha256 == ob.sha256


def test_a_cleared_discord_name_stays_cleared_and_what_goes_says_what_goes(main, receiver):
    # The adversary's 2: the remembered name filled once, never again over the tester's edit; while What goes is up
    # the name can't change, so the page's "No Discord name" is what is sent.
    from app import send_report
    send_report.remember_name("yuki0429")
    w = _press(main)
    assert wait_until(lambda: w.name_field.text() == "yuki0429")
    w.name_field.setFocus()
    w.name_field.selectAll()
    QTest.keyClick(w.name_field, Qt.Key.Key_Backspace)                 # the tester clears it
    _save(w, ZH_WHAT)
    _look(w)
    assert w.goes_name.text() == strings.REPORT_GOES_NO_NAME
    assert not w.name_field.isEnabled() and not w.send_button.isEnabled() and not w.zip_button.isEnabled()
    for _ in range(30):
        QApplication.processEvents()
    assert w.name_field.text() == ""                                   # no read filled it back
    w.goes_send.click()
    assert wait_until(lambda: len(receiver.got) == 1, 15)
    assert "x-discord-name" not in {k.lower() for k in receiver.got[0]["headers"]}
    assert wait_until(lambda: w.pages.currentIndex() == w.FORM and w.name_field.isEnabled())


def test_back_puts_the_row_back_and_the_code_on_the_page_is_the_one_sent(main, receiver):
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    shown = w.goes_sender.text().rsplit(" ", 1)[1]
    assert not w.new_code_button.isEnabled()                           # the code that goes can't change under it
    w.goes_send.click()
    assert wait_until(lambda: len(receiver.got) == 1, 15)
    assert {k.lower(): v for k, v in receiver.got[0]["headers"].items()}["x-report-sender"] == shown
    assert wait_until(lambda: w.new_code_button.isEnabled() and w.send_button.isEnabled() is False)   # (list empty)


def test_what_goes_shows_the_pictures_at_the_pages_width(main, receiver):
    # The adversary's 4: at full width, the tester's eyes being the only check on a picture.
    from app import scrub
    scrub.identity()
    w = _press(main)
    _save(w, JA_WHAT)
    w.resize(760, 900)
    _look(w)
    shown = [w.goes_pictures.itemAt(i).widget() for i in range(w.goes_pictures.count())]
    assert shown, "a scrubbed picture goes and is shown"
    room = w.goes_scroll.viewport().width()
    for label in shown:
        pm = label.pixmap()
        assert pm.width() / pm.devicePixelRatio() >= min(room - 30, main.width() - 2), (pm.width(), room)


def test_another_windows_newer_report_is_never_deleted_by_a_late_close(main, receiver):
    # The adversary's 6b: a delete only of the zip this window showed.
    from app import send_report
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    shown = w.outbox.sha256
    _save(w, ZH_WHAT)                                                  # (another report: the next build differs)
    newer = send_report.build(windows.language_of(main), include_results=False)
    assert newer.sha256 != shown
    w.close()
    for _ in range(30):
        QApplication.processEvents()
    import threading
    for t in threading.enumerate():
        if t.name == "report-discard":
            t.join(5)
    assert send_report.waiting() is not None and send_report.waiting().sha256 == newer.sha256
