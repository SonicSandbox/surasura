"""Report a problem in the window (`app/qt/report.py`; the scope `tracks/ship/work/report/scope.md`).

What a wrong answer would cost: the bug not where Sonic asked (the header's top right), or a picture of the screen —
another program, the tester's desktop — instead of Surasura's own window; a picture taken after the report window
already covers what went wrong; a tester's notes lost or the list emptied by a zip that wasn't made; a control with no
tip or no name; the window's thread waiting on the disk; the zip's folder not opened.
"""
import os
import threading
import zipfile

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton, QWidget

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
    """Send report pressed: wait for What goes filled in (it opens at the press, gathering: try a9.1), and for the send
    state read after it."""
    w.send_button.click()
    assert wait_until(lambda: w.pages.currentIndex() == w.GOES and w.outbox is not None, 15)
    _read(w)


def _read(w):
    """Wait until the window has shown its newest read of the send state (waiting zip, code, name)."""
    assert wait_until(lambda: getattr(w, "send_read", None) == w._reads, 15)


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
    assert w.done_line.text() == strings.REPORT_SENT_WHERE_ONE.format(id="K3Q7PM")   # try a9 #6: where it went


def _sent_open(w, rid):
    """The *Open* of `rid`'s row under Sent reports."""
    for i in range(w.sent_rows.count()):
        row = w.sent_rows.itemAt(i).widget()
        if row is not None and any(f"#{rid}" in x.text() for x in row.findChildren(QLabel)):
            return [b for b in row.findChildren(QPushButton) if b.text() == strings.REPORT_SENT_OPEN][0]
    raise AssertionError(f"no row for #{rid}")


def test_after_send_the_done_line_says_where_the_reports_went_and_sent_reports_sits_right_under_it(main, receiver):
    """try a9 #6 (Sonic: "I don't see anything and now I can't see the 5 nor the zip"): the done line counts the reports
    the send took off the list and names Sent reports, which follows it at once (no other row between)."""
    w = _press(main)
    w.include_results.setChecked(False)
    _save(w, JA_WHAT)
    _save(w, ZH_WHAT, "风景 shows once")
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: w.sent_id == "K3Q7PM" and w.sent_rows.count() == 1, 15)
    assert w.done_line.text() == strings.REPORT_SENT_WHERE_MANY.format(id="K3Q7PM", n=2)
    assert "Sent reports" in w.done_line.text() and not w.done_line.isHidden()
    box = w.done_line.parentWidget().layout()
    order = []

    def walk(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is not None:
                order.append(item.widget())
            elif item.layout() is not None:
                walk(item.layout())
    walk(box)
    shown = [x for x in order if x.isVisibleTo(w)]
    at = shown.index(w.done_line)
    assert shown[at + 1:at + 3] == [w.copy_button, w.invite_button] and shown[at + 3] is w.sent_box
    assert w.sent_heading.isVisibleTo(w) and w.sent_heading.y() == 0       # its heading first in it


def test_opening_a_sent_report_shows_the_reports_it_held_words_and_pictures(main, receiver, sent):
    """try a9 #6: a sent #ID opens the reports it held, from the zip kept on this PC — not only the zip."""
    from app import scrub
    scrub.identity()                                                   # (a scrubbed picture goes with it)
    w = _press(main)
    w.include_results.setChecked(False)
    _save(w, JA_WHAT, "Currentに残る")
    _save(w, ZH_WHAT)
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: w.sent_rows.count() == 1, 15)
    _sent_open(w, "K3Q7PM").click()
    assert wait_until(lambda: w.pages.currentIndex() == w.SENT, 15)
    assert w.sent_opened_heading.text().startswith("#K3Q7PM, sent ")
    items = [w.sent_lines.itemAt(i).widget() for i in range(w.sent_lines.count())]
    words = [x.text() for x in items if isinstance(x, QLabel) and x.pixmap().isNull()]
    pictures = [x for x in items if isinstance(x, QLabel) and not x.pixmap().isNull()]
    assert len(words) == 2 and JA_WHAT in words[0] and "Currentに残る" in words[0] and ZH_WHAT in words[1]
    assert len(pictures) >= 1                                          # the picture that went, as it went
    w.sent_zip.click()
    assert wait_until(lambda: [k for k, _p in sent] == ["show"])
    assert sent[0][1].endswith("K3Q7PM.zip")
    w.sent_back.click()
    assert w.pages.currentIndex() == w.FORM and w.sent_opened is None


def test_sent_contents_reads_only_the_reports_in_order_and_scales_wide_pictures(tmp_path):
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtCore import QBuffer, QIODevice

    def png(width):
        img = QImage(width, 40, QImage.Format.Format_RGB32)
        img.fill(QColor("#2d2d2d"))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())
    path = tmp_path / "K3Q7PM.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("reports/20261102-100529-1/report.txt", "What happened:\n" + ZH_WHAT + "\n")
        z.writestr("reports/20261102-093757-2/report.txt", "What happened:\n" + JA_WHAT + "\n")
        z.writestr("reports/20261102-093757-2/picture-10.png", png(80))
        z.writestr("reports/20261102-093757-2/picture-2.png", png(1200))
        z.writestr("reports/20261102-093757-2/report.json", "{}")
        z.writestr("logs/app_debug_log.txt", "not a report")
        z.writestr("MANIFEST.txt", "")
    got = report_ui.sent_contents(str(path), 600)
    assert [rid for rid, _t, _p in got] == ["20261102-093757-2", "20261102-100529-1"]     # oldest first
    assert JA_WHAT in got[0][1] and ZH_WHAT in got[1][1] and got[1][2] == []
    assert [img.width() for img in got[0][2]] == [600, 80]             # picture-2 before picture-10; scaled to fit


def test_a_sent_report_read_late_never_takes_the_page_back_after_back(main, monkeypatch, tmp_path):
    """Open on a sent #ID, then Back (or another report opened) before its zip was read: the late answer shows nothing."""
    import threading
    gate = threading.Event()
    real = report_ui.sent_contents
    monkeypatch.setattr(report_ui, "sent_contents", lambda *a: (gate.wait(10), real(*a))[1])
    path = tmp_path / "K3Q7PM.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("reports/20261102-093757-2/report.txt", "What happened:\n" + JA_WHAT + "\n")
    w = _press(main)
    w.open_sent("K3Q7PM", "2026-11-02 02:05", str(path))
    w.back()
    gate.set()
    assert wait_until(lambda: not report_ui.qpress.live(w, "report:sent:K3Q7PM"))
    QTest.qWait(50)
    assert w.pages.currentIndex() == w.FORM and w.sent_lines.count() == 0


def test_a_sent_report_read_late_never_takes_the_page_from_show_me(main, monkeypatch, tmp_path):
    import threading
    gate = threading.Event()
    real = report_ui.sent_contents
    monkeypatch.setattr(report_ui, "sent_contents", lambda *a: (gate.wait(10), real(*a))[1])
    path = tmp_path / "K3Q7PM.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("reports/20261102-093757-2/report.txt", "What happened:\n" + JA_WHAT + "\n")
    w = _press(main)
    _save(w, ZH_WHAT)
    w.open_sent("K3Q7PM", "2026-11-02 02:05", str(path))
    w.show_button.click()
    assert wait_until(lambda: w.pages.currentIndex() == w.CONTENTS)
    gate.set()
    assert wait_until(lambda: not report_ui.qpress.live(w, "report:sent:K3Q7PM"))
    QTest.qWait(50)
    assert w.pages.currentIndex() == w.CONTENTS


def test_sent_reports_wait_while_what_goes_is_up(main, receiver):
    """The adversary's S1: a sent #ID opened from What goes would leave its zip and the held row behind."""
    w = _press(main)
    w.include_results.setChecked(False)
    _save(w, JA_WHAT)
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: w.sent_rows.count() == 1, 15)
    _save(w, ZH_WHAT)
    _look(w)
    assert not w.sent_box.isEnabled() and not _sent_open(w, "K3Q7PM").isEnabled()
    w.goes_back.click()
    assert w.sent_box.isEnabled() and _sent_open(w, "K3Q7PM").isEnabled()


def test_a_sent_zip_with_no_reports_says_so_instead_of_a_blank_page(main, tmp_path):
    path = tmp_path / "K3Q7PM.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("logs/app_debug_log.txt", "a log")
    w = _press(main)
    w.open_sent("K3Q7PM", "2026-11-02 02:05", str(path))
    assert wait_until(lambda: w.status.text() == strings.REPORT_SENT_EMPTY.format(id="K3Q7PM"))
    assert w.pages.currentIndex() == w.FORM and w.sent_opened is None


def test_a_sent_zip_that_cant_be_read_says_so_and_stays_on_the_form(main, receiver, tmp_path):
    w = _press(main)
    w.open_sent("K3Q7PM", "2026-11-02 02:05", str(tmp_path / "gone.zip"))
    assert wait_until(lambda: w.status.text().startswith("#K3Q7PM couldn't be read: "))
    assert w.pages.currentIndex() == w.FORM and w.sent_opened is None


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


def test_send_now_refused_again_says_so_anew_and_keeps_the_report_waiting(main, receiver):
    # Mattias, 3.0.0 (2026-11-11): production's /report answered 404, and "Send now ... did nothing" — the refusal's
    # line was word for word the one already showing (the status line repaints only on new words), and the press's arc
    # lasts only as long as a 404's round trip. Each try that fails says so in words of its own; the zip stays.
    receiver.answer = (404, b"Not found")
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    nonce = w.outbox.nonce
    first = strings.REPORT_SEND_REFUSED.format(status=404)
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == first, 15)
    assert wait_until(lambda: not w.waiting_line.isHidden())
    lines = [first]
    for tries in (2, 3):
        w.send_now_button.click()
        said = strings.REPORT_SEND_TRIED.format(n=tries, words=first)
        assert wait_until(lambda: w.status.text() == said, 15)        # a line it hadn't shown: the press answered
        lines.append(said)
        assert wait_until(lambda: not w.waiting_line.isHidden() and w.send_now_button.isEnabled())
    assert len(set(lines)) == 3 and len(receiver.got) == 3
    assert {k.lower(): v for k, v in receiver.got[2]["headers"].items()}["x-report-nonce"] == nonce
    assert len(core.listed()) == 1 and _send_state()[0].nonce == nonce     # the report and its zip both kept
    receiver.answer = (201, {"id": "K3Q7PM"})
    w.send_now_button.click()                                          # the receiver back: the same zip goes, once
    assert wait_until(lambda: w.status.text() == "Sent. Your report is #K3Q7PM", 15)
    assert wait_until(lambda: w.reports == [] and w.waiting_line.isHidden())


def test_tries_count_per_zip_so_a_new_zips_first_refusal_says_the_plain_words(main, receiver):
    # The count is the zip's (its nonce): a new zip after *Don't send* starts again, never "Tried 3 times".
    receiver.answer = (404, b"Not found")
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    first = strings.REPORT_SEND_REFUSED.format(status=404)
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == first, 15)
    assert wait_until(lambda: not w.waiting_line.isHidden() and w.send_now_button.isEnabled())
    w.send_now_button.click()
    assert wait_until(lambda: w.status.text() == strings.REPORT_SEND_TRIED.format(n=2, words=first), 15)
    assert wait_until(lambda: not w.waiting_line.isHidden() and w.dont_send_button.isEnabled())
    w.dont_send_button.click()
    assert wait_until(lambda: w.waiting_line.isHidden() and w.status.text() == strings.REPORT_DISCARDED)
    _save(w, ZH_WHAT)                                                  # another report: another zip, another nonce
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: len(receiver.got) == 3, 15)
    assert wait_until(lambda: w.status.text() == first, 15)


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


def test_the_window_says_what_a_report_holds_and_github_is_the_quieter_way(main, sent, tmp_path):
    """try a9 #6: Sonic thought Send went to GitHub — GitHub is named only on Make a zip instead's path, once a zip is
    made, never beside Send."""
    from app.qt import settings_strings
    w = _press(main)
    for said in ("logs", "settings", "titles in your library", "Windows name"):
        assert said in w.hint.text()
    assert w.send_where.isHidden() and w.issues_button.isHidden()
    shown = [x for x in w.findChildren(QWidget) if x.isVisibleTo(w) and hasattr(x, "text")]
    assert not any("GitHub" in x.text() for x in shown)
    assert "GitHub" not in strings.REPORT_SEND_TIP and "GitHub" not in strings.REPORT_PROMISE
    _save(w, JA_WHAT)
    w.dest = str(tmp_path)
    w.include_results.setChecked(False)
    w.zip_button.click()
    assert wait_until(lambda: w.reports == [] and not w.issues_button.isHidden())
    assert w.send_where.text() == strings.REPORT_SEND_WHERE and "Make a zip instead" in strings.REPORT_SEND_WHERE
    assert w.issues_button.toolTip() == strings.REPORT_ISSUES_TIP
    w.issues_button.click()                                            # the quieter way: GitHub Issues, in the browser
    assert wait_until(lambda: ("url", settings_strings.ISSUES_URL) in sent)


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
    made = []

    def slow(*a, **k):
        gate.wait(10)
        made.append(real(*a, **k))
        return made[-1]
    monkeypatch.setattr(send_report, "build", slow)
    w = _press(main)
    _save(w, JA_WHAT)
    w.send_button.click()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert wait_until(lambda: windows.opened(main, report_ui.NAME) is None)
    gate.set()
    assert wait_until(lambda: made, 15)                                # the zip was made after the close
    # its delete waited on, not a count of loop turns: the pool's answer that starts it can come later (GitHub,
    # Flake-P2, tests/FLAKES.md)
    assert wait_until(_outbox_empty, 10), "the zip made after the close is deleted"
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


def test_who_you_are_is_worked_out_after_the_start_or_as_the_hand_reaches_the_bug(main):
    # GitHub's shard 3 (2026-11-01): worked out at every first frame, the read ran beside the start's own work and the
    # drag suite's timed checks. Now: a moment after the first frame, or at once when the hand reaches the bug.
    import threading
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    from app import scrub
    timer = main.report_button.prepare_timer
    assert timer.isSingleShot() and timer.interval() == report_ui.PREPARE_AFTER_MS == 3000
    for t in threading.enumerate():
        if t.name == "scrub-identity":
            t.join(10)
    scrub.reset()
    p = QPointF(4, 4)
    QApplication.sendEvent(main.report_button, QEnterEvent(p, p, p))
    QApplication.sendEvent(main.report_button, QEnterEvent(p, p, p))          # (a second pass: one worker only)
    assert sum(t.name == "scrub-identity" for t in threading.enumerate()) <= 1
    assert wait_until(scrub.ready, 10)


# --- a9.1: the window kept built after its first close (Sonic: "It lags when I open up the debug screen") ---------- #
def _close(w):
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert wait_until(lambda: w.gone)


def test_the_second_press_shows_the_same_window_again_built_once(main, monkeypatch):
    made = []
    real = report_ui.ReportWindow.__init__

    def counted(self, *a, **k):
        made.append(1)
        real(self, *a, **k)
    monkeypatch.setattr(report_ui.ReportWindow, "__init__", counted)
    w = _press(main)
    _close(w)
    assert windows.opened(main, report_ui.NAME) is None                # closed: no window, no icon
    assert getattr(main, report_ui.KEPT) is w and not w.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    again = _press(main)
    assert again is w and made == [1] and w.isVisible() and not w.gone
    assert getattr(main, report_ui.KEPT) is None                       # in use, not kept twice
    receivers = w.receivers(w.closed)
    for _ in range(3):                                                 # closed and opened again: connected once
        _close(w)
        assert _press(main) is w
    assert w.receivers(w.closed) == receivers
    _close(w)
    assert windows.opened(main, report_ui.NAME) is None


def test_opened_again_it_is_as_new_no_page_line_row_or_picture_of_before(main):
    w = _press(main)
    first = list(w.pictures)
    _save(w, JA_WHAT, "Finishedに残ると思った")
    _save(w, ZH_WHAT)
    w.remove(w.reports[0].id)
    assert wait_until(lambda: len(w.reports) == 1 and w.undo_button.isVisible())
    w.open(w.reports[0].id)
    w.note.setPlainText("还没写完")
    assert w.pages.currentIndex() == w.OPENED and w.status.text()     # "Removed…" said
    w.name_field.setText("ゆき#0429")                                  # typed, never sent
    w.include_results.setChecked(False)
    w._done_row("Made it", invite=strings.REPORT_INVITE_ZIP)
    for x in w.dest_row:
        x.setVisible(True)
    w.dest = os.path.expanduser("~")
    _close(w)
    w = _press(main)
    assert w.pages.currentIndex() == w.FORM and w.opened_id is None and w.sent_opened is None and w.outbox is None
    assert w.opened_text.toPlainText() == "" and w.note.toPlainText() == "" and w.opened_pictures.count() == 0
    assert w.status.text() in ("", strings.REPORT_EMPTY)               # nothing said of before
    assert not w.undo_button.isVisible() and w.last_removed is None
    assert w.done_line.isHidden() and w.invite_button.isHidden() and all(x.isHidden() for x in w.dest_row)
    assert w.dest == report_ui.downloads() and w.include_results.isChecked()
    assert w.name_field.text() == "" and not w.name_goes.isVisibleTo(w)    # the typed name not kept (as a new window)
    assert len(w.pictures) == 1 and w.pictures[0] is not first[0]       # this press's picture, its thumbnail anew
    assert len(w._thumbs) == 1 and not w._thumbs[0].pixmap().isNull()
    assert w.what.toPlainText() == "" and not w.save_button.isEnabled()


def test_a_sent_reports_page_is_never_shown_again_on_the_next_press(main, receiver, sent):
    w = _press(main)
    w.include_results.setChecked(False)
    _save(w, JA_WHAT)
    _look(w)
    w.goes_send.click()
    assert wait_until(lambda: w.sent_rows.count() == 1, 15)
    assert w.done_line.isVisibleTo(w) and w.copy_button.isVisibleTo(w)
    _sent_open(w, "K3Q7PM").click()
    assert wait_until(lambda: w.pages.currentIndex() == w.SENT, 15)
    _close(w)
    w = _press(main)
    _read(w)
    assert w.pages.currentIndex() == w.FORM and w.sent_lines.count() == 0 and w.sent_opened_heading.text() == ""
    assert w.done_line.isHidden() and w.copy_button.isHidden() and w.sent_id is None
    assert w.sent_rows.count() == 1                                    # Sent reports still lists it (read again)


def test_what_goes_closed_unsent_is_never_shown_again(main, receiver):
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    _close(w)
    assert wait_until(_outbox_empty)
    w = _press(main)
    _read(w)
    assert w.pages.currentIndex() == w.FORM and w.outbox is None and w.goes_pictures.count() == 0
    assert w.send_button.isEnabled() and w.name_field.isEnabled() and w.list.isVisibleTo(w)   # nothing held


def test_an_answer_to_an_earlier_opening_never_lands_in_the_next(main):
    w = _press(main)
    landed = []
    late = w.alive(lambda *a: landed.append(a))                        # a worker's answer, asked before the close
    _close(w)
    assert late("closed") is None
    _press(main)
    late("opened again")
    assert landed == []
    w.alive(lambda *a: landed.append(a))("now")                        # this opening's own answers land
    assert landed == [("now",)]


def test_the_draft_and_the_remembered_name_come_back_as_in_a_new_window(main):
    from app import send_report
    w = _press(main)
    w.what.setPlainText(JA_WHAT)
    w.leave_out.setChecked(True)
    w.name_field.setText("typed, not kept")
    _close(w)
    send_report.remember_name("ゆき#0429")
    w = _press(main)
    assert w.what.toPlainText() == JA_WHAT and w.leave_out.isChecked() and w.save_button.isEnabled()
    assert wait_until(lambda: w.name_field.text() == "ゆき#0429")      # the remembered one, filled in again


def test_a_window_closed_while_its_work_goes_on_is_not_kept(main, receiver, monkeypatch):
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
    _close(w)
    assert getattr(main, report_ui.KEPT, None) is None and w.gone
    gate.set()
    again = _press(main)
    assert again is not w                                              # (that one finishes, and goes)


def test_a_new_look_makes_a_new_window(main):
    w = _press(main)
    _close(w)
    w.made_in = ("day",) + tuple(w.made_in[1:])                        # as if the look changed while it was kept
    again = _press(main)
    assert again is not w and getattr(main, report_ui.KEPT, None) is None
    _close(again)
    assert _press(main) is again


def test_the_first_press_builds_the_form_and_the_other_pages_after_its_first_frame(main):
    w = report_ui.ReportWindow(main)
    assert w.pages.count() == 1                                        # the form alone at the press
    w.show()
    assert wait_until(lambda: w.pages.count() == 5)                    # after its first frame
    assert w.pages.indexOf(w.opened_text.parentWidget()) == w.OPENED
    assert w.pages.indexOf(w.contents.parentWidget()) == w.CONTENTS
    w.close()


@pytest.mark.parametrize("ask", ["open", "hold", "goes", "contents", "gather"])
def test_whatever_needs_a_page_before_the_first_frame_builds_it_first(main, ask):
    from app import send_report
    w = _press(main)
    _save(w, ZH_WHAT)
    _close(w)
    setattr(main, report_ui.KEPT, None)
    w = report_ui.ReportWindow(main)                                   # never shown: no frame yet
    assert wait_until(lambda: w.reports)
    assert w.pages.count() == 1
    if ask == "open":
        w.open(w.reports[0].id)
        assert w.pages.currentIndex() == w.OPENED and ZH_WHAT in w.opened_text.toPlainText()
    elif ask == "hold":
        w._hold(True)
        assert not w.note_button.isEnabled()
        w._hold(False)
    elif ask == "goes":
        ob = send_report.build(w.language, include_results=False)
        w._show_goes(ob, [])
        assert w.pages.currentIndex() == w.GOES and w.goes_files.text()
        w.back()
    elif ask == "gather":                                              # (#279: What goes opens at the press)
        w._gather()
        assert w.pages.currentIndex() == w.GOES and w.goes_gathering.isVisibleTo(w)
        w.back()
    else:
        w.show_contents()
        assert wait_until(lambda: w.pages.currentIndex() == w.CONTENTS)
    assert w.pages.count() == 5
    w.close()


def test_kept_hidden_it_holds_no_picture_and_opens_again_at_a_fresh_ones_size(main, receiver):
    # The adversary's S1 / S2: a hidden window held the screenshots and What goes' full-width pictures until the next
    # press (which may never come), and a page left full could size the next opening bigger than a fresh one.
    from app import scrub
    scrub.identity()
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    assert w.goes_pictures.count() >= 1                                # the press's picture, at the page's width
    _close(w)
    assert w.pictures == [] and w._thumbs is None and w.picture_row.count() == 0
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert w.goes_pictures.count() == 0 and w.opened_pictures.count() == 0 and w.contents.toPlainText() == ""
    assert _press(main) is w
    _read(w)
    after_goes = w.size()
    assert len(w.pictures) == 1
    _close(w)                                                          # (closed from the form this time)
    assert _press(main) is w
    _read(w)
    assert w.size() == after_goes                                      # nothing a page showed sizes the next one


def test_opened_again_it_is_where_it_was_left_never_in_its_icon(main):
    # The adversary's N2 (lean, lead): a kept window comes back where the learner left it, at its size — but never
    # minimised (closed from its icon), as `windows.bring_back` shows one.
    w = _press(main)
    w.move(w.pos() + QPoint(40, 30))
    at, size = w.pos(), w.size()
    w.setWindowState(Qt.WindowState.WindowMinimized)                   # (closed as it goes into its icon)
    _close(w)
    assert _press(main) is w
    for _ in range(5):
        QApplication.processEvents()                                   # (the platform's late state reports)
    assert not w.isMinimized() and w.isVisible() and w.pos() == at and w.size() == size


# --- try a9.1 (Sonic: "it lagged when i hit the button, just hung there until it got to the screen of exactly what goes.
# need something to indicate that it's thinking"): What goes opens at the press, gathering, and counts the files in ----- #
def _gated_build(monkeypatch, steps=()):
    """`send_report.build` held until the gate opens, telling `steps` ((done, total) …) first, as `report._write` does:
    what the window shows meanwhile is the press's own frame, not the zip's end."""
    import threading
    from app import send_report
    gate, real, made = threading.Event(), send_report.build, []

    def slow(*a, step=None, **k):
        for done, total in steps:
            step(done, total)
        gate.wait(10)
        made.append(real(*a, step=step, **k))
        return made[-1]
    monkeypatch.setattr(send_report, "build", slow)
    return gate, made


def test_send_report_opens_what_goes_in_the_press_frame_saying_it_is_gathering(main, receiver, monkeypatch):
    import time
    gate, _made = _gated_build(monkeypatch)
    w = _press(main)
    w.what.setPlainText(JA_WHAT)
    t0 = time.perf_counter()
    w.send_button.click()                                              # (the frame: no worker has answered yet)
    took = time.perf_counter() - t0
    assert took < 0.1                                                  # press -> its page: well inside 100 ms
    assert w.pages.currentIndex() == w.GOES and w.gathering
    assert not w.goes_gathering.isHidden() and w.goes_gathering.text() == strings.REPORT_GATHERING
    assert all(x.isHidden() for x in (w.goes_placeholders, w.goes_name, w.goes_kept, w.goes_files))
    assert not w.goes_send.isEnabled() and not w.goes_open.isEnabled()  # nothing to send or open until it's made
    assert wait_until(lambda: w.reports is not None and len(w.reports) == 1)   # saved meanwhile: still no second press
    assert not w.send_button.isEnabled()                               # ... nor Show me / Make a zip beside it
    assert not w.show_button.isEnabled() and not w.zip_button.isEnabled()
    assert w.goes_back.isEnabled() and receiver.got == []
    gate.set()
    assert wait_until(lambda: w.outbox is not None, 15)                # made: the page fills in, the same page
    assert w.pages.currentIndex() == w.GOES and not w.gathering and w.goes_gathering.isHidden()
    assert not w.goes_files.isHidden() and "MANIFEST.txt" in w.goes_files.text()
    assert w.goes_send.isEnabled() and w.goes_open.isEnabled() and receiver.got == []


def test_the_gathering_page_counts_the_files_in_and_says_the_last_check(main, receiver, monkeypatch):
    gate, _made = _gated_build(monkeypatch, steps=((0, 12), (4, 12)))
    w = _press(main)
    _save(w, ZH_WHAT)                                                  # a saved report, the form empty
    w.send_button.click()
    assert wait_until(lambda: w.goes_gathering.text() == strings.REPORT_GATHERING_N.format(done=5, total=12))
    w._gathered((12, 12))                                              # every file in: the guard's read-back
    assert w.goes_gathering.text() == strings.REPORT_GATHERING_CHECK
    gate.set()
    assert wait_until(lambda: w.outbox is not None, 15)
    w._gathered((3, 12))                                               # a late count, the page made: never said
    assert w.goes_gathering.isHidden() and w.goes_gathering.text() == strings.REPORT_GATHERING_CHECK


def test_back_while_gathering_returns_to_the_form_and_the_zip_made_after_is_deleted(main, receiver, monkeypatch):
    gate, made = _gated_build(monkeypatch)
    w = _press(main)
    _save(w, JA_WHAT)
    w.send_button.click()
    assert w.pages.currentIndex() == w.GOES and w.gathering
    w.goes_back.click()                                                # changed their mind before it was made
    assert w.pages.currentIndex() == w.FORM and not w.gathering
    gate.set()
    assert wait_until(lambda: made, 15)
    assert wait_until(_outbox_empty, 15)                               # made after Back: never kept, never shown
    assert w.pages.currentIndex() == w.FORM and w.outbox is None and receiver.got == []
    assert wait_until(lambda: w.send_button.isEnabled() and w.list.isEnabled())
    assert len(core.listed()) == 1                                     # the report itself stays on the list


def test_a_save_that_fails_takes_the_gathering_page_back_to_the_form(main, receiver, monkeypatch):
    def refuse(*a, **k):
        raise OSError("the disk is full")
    monkeypatch.setattr(core, "save", refuse)
    w = _press(main)
    w.what.setPlainText(JA_WHAT)
    w.send_button.click()
    assert w.pages.currentIndex() == w.GOES                            # it reacted at once …
    assert wait_until(lambda: w.pages.currentIndex() == w.FORM)        # … and came back with the reason
    assert wait_until(lambda: "the disk is full" in w.status.text())
    assert w.what.toPlainText() == JA_WHAT and not w.gathering and receiver.got == []


def test_prepare_send_scales_wide_pictures_on_the_worker(main, receiver, monkeypatch):
    """The What goes pictures come scaled to the page's width from the worker: the window's thread only shows them."""
    from PyQt6.QtGui import QColor, QImage
    w = _press(main)
    img = QImage(3000, 400, QImage.Format.Format_RGB32)
    img.fill(QColor("#1e1e1e"))
    core.save(JA_WHAT, "", [report_ui.png_bytes(img)], where="Current", scrubbed=True)
    kind, _outbox, pictures, *_code = report_ui.prepare_send("ja", False, {"language": "ja"}, {}, None, 600)
    assert kind == "built" and [p.width() for p in pictures] == [600]
    kind, _outbox, pictures, *_code = report_ui.prepare_send("ja", False, {"language": "ja"}, {})
    assert kind == "built" and [p.width() for p in pictures] == [3000]  # no width: as it went
    assert w is not None


def test_back_while_gathering_reads_what_waits_again_and_never_shows_the_replaced_zip(main, receiver, monkeypatch):
    """A zip left waiting (a send that didn't go) is replaced by the press's: its *Send now* row goes at the press and,
    after Back deleted the new one, stays gone (nothing waits any more) — never a row for a zip that's gone."""
    from app import send_report
    w = _press(main)
    _save(w, JA_WHAT)
    send_report.build("ja")                                            # one waiting, as after a send that didn't go
    w.read_send()
    assert wait_until(lambda: not w.waiting_row[0].isHidden())
    gate, made = _gated_build(monkeypatch)
    w.send_button.click()
    assert all(x.isHidden() for x in w.waiting_row)                     # never beside the gathering page
    w.goes_back.click()
    gate.set()
    assert wait_until(lambda: made, 15) and wait_until(_outbox_empty, 15)
    assert wait_until(lambda: w.waiting is None and all(x.isHidden() for x in w.waiting_row), 15)


def test_back_during_the_save_makes_no_zip_and_a_second_press_meanwhile_says_why(main, receiver, monkeypatch):
    import threading
    from app import send_report
    gate, real_save, built = threading.Event(), core.save, []
    monkeypatch.setattr(core, "save", lambda *a, **k: (gate.wait(10), real_save(*a, **k))[1])
    monkeypatch.setattr(send_report, "build", lambda *a, **k: built.append(a))
    w = _press(main)
    w.what.setPlainText(JA_WHAT)
    w.send_button.click()                                              # saving first
    w.goes_back.click()
    w.what.setPlainText(JA_WHAT + "。")
    w.send_button.click()                                              # pressed again while the first save runs
    assert w.status.text() == strings.REPORT_ZIP_BUSY and w.pages.currentIndex() == w.FORM
    gate.set()
    assert wait_until(lambda: w.reports is not None and len(w.reports) == 1, 15)
    for _ in range(30):
        QApplication.processEvents()
    assert built == [] and w.pages.currentIndex() == w.FORM          # Back before the zip: none made for nothing
    assert wait_until(lambda: w.send_button.isEnabled())


# --- Mado-SO (a9.1's kept window at 250 %: three whole paints an opening): opened again as it was left ------------- #
def _held_list(monkeypatch):
    """The saved reports' read held until the gate opens (a slow disk): what the window shows before it lands."""
    import threading
    gate = threading.Event()
    real = core.listed
    monkeypatch.setattr(core, "listed", lambda: (gate.wait(5), real())[1])
    return gate


def test_kept_it_opens_at_the_size_it_was_left_at_never_shrunk_then_grown_back(main, monkeypatch):
    # `windows.show` sized a kept window to its hint again; its lines landing grew it back, twice (Windows' own
    # second step): each a whole repaint at 250 %. Opened again it is the size it was left at — a learner's own too
    from PyQt6.QtCore import QObject, QSize
    w = _press(main)
    for _ in range(10):
        QApplication.processEvents()
    w.resize(w.size() + QSize(30, 50))
    for _ in range(10):
        QApplication.processEvents()
    size = w.size()
    _close(w)
    resized = []

    class Sizes(QObject):
        def eventFilter(self, obj, event):
            if obj is w and event.type() == QEvent.Type.Resize and event.oldSize().isValid():
                resized.append((event.oldSize(), event.size()))
            return False
    sizes = Sizes()
    w.installEventFilter(sizes)
    gate = _held_list(monkeypatch)
    landed = []
    real_show = w._show
    monkeypatch.setattr(w, "_show", lambda got, line=None: (real_show(got, line), landed.append(len(got))))
    main.report_button.click()
    assert windows.opened(main, report_ui.NAME) is w and w.size() == size
    gate.set()
    assert wait_until(lambda: landed == [0])
    for _ in range(10):
        QApplication.processEvents()
    assert w.size() == size and resized == []
    w.removeEventFilter(sizes)
    _close(w)


def test_kept_with_nothing_saved_its_line_is_there_at_the_press_and_the_read_changes_nothing(main, monkeypatch):
    w = _press(main)
    assert wait_until(lambda: w.status.text() == strings.REPORT_EMPTY) and w.reports == []
    _close(w)
    gate = _held_list(monkeypatch)
    landed = []
    real_show = w._show
    monkeypatch.setattr(w, "_show", lambda got, line=None: (real_show(got, line), landed.append(len(got))))
    main.report_button.click()
    assert windows.opened(main, report_ui.NAME) is w
    assert w.status.text() == strings.REPORT_EMPTY and w.status.isVisibleTo(w)   # at the press, before the read
    paints = w.status_paints
    gate.set()
    assert wait_until(lambda: landed == [0])
    assert w.status.text() == strings.REPORT_EMPTY and w.status_paints == paints   # nothing it shows changed (S19)
    _close(w)


def test_kept_with_nothing_saved_a_report_saved_since_takes_the_empty_line_away(main, monkeypatch):
    # the line is the list's own: put back at the press from the last read, it goes when the read finds a report
    w = _press(main)
    assert wait_until(lambda: w.status.text() == strings.REPORT_EMPTY)
    _close(w)
    core.save(JA_WHAT, "", [])                                         # (saved meanwhile: the next read finds it)
    gate = _held_list(monkeypatch)
    main.report_button.click()
    assert w.status.text() == strings.REPORT_EMPTY
    gate.set()
    assert wait_until(lambda: w.reports is not None and len(w.reports) == 1)
    assert w.status.text() == "" and w.status.isHidden()
    _close(w)


# --- Fresh-U row 3 (2026-11-10): no grey button without its reason; never past the screen ------------------------------ #
def test_fresh_u_show_me_works_straight_after_typing_saving_the_draft_first(main):
    # A new user typed what happened and pressed *Show me what's in it*: it waited, grey, for *Save to my list* (only a
    # hover said so). Now it lights up with the words, says in its tip that they are saved first, and shows the plan
    # with the typed report in it
    w = _press(main)
    assert not w.show_button.isEnabled() and w.show_button.toolTip() == strings.REPORT_SHOW_NONE_TIP
    w.what.setPlainText(JA_WHAT)
    assert w.show_button.isEnabled() and w.zip_button.isEnabled() and w.send_button.isEnabled()
    assert w.show_button.toolTip() == strings.REPORT_SHOW_SAVES_TIP
    assert w.zip_button.toolTip() == strings.REPORT_ZIP_SAVES_TIP
    w.show_button.click()
    assert wait_until(lambda: w.pages.currentIndex() == w.CONTENTS)
    assert wait_until(lambda: w.reports and len(w.reports) == 1)
    assert core.listed()[0].what == JA_WHAT and w.what.toPlainText() == ""
    assert f"reports/{core.listed()[0].id}/report.txt" in w.contents.toPlainText()
    assert w.show_button.toolTip() == strings.REPORT_SHOW_TIP          # saved: the plain tip again


def test_fresh_u_make_a_zip_straight_after_typing_saves_it_and_zips_it_with_the_ones_saved_before(main, sent, tmp_path):
    w = _press(main)
    _save(w, ZH_WHAT)
    w.what.setPlainText(JA_WHAT)
    w.expected.setPlainText("Finishedに残ると思った")
    w.dest = str(tmp_path / "zips")
    w.zip_button.click()
    assert wait_until(lambda: w.reports == [] and sent)
    made = [n for n in os.listdir(tmp_path / "zips") if n.endswith(".zip")]
    with zipfile.ZipFile(tmp_path / "zips" / made[0]) as z:
        texts = [z.read(n).decode("utf-8") for n in z.namelist() if n.endswith("/report.txt")]
    assert len(texts) == 2 and any(JA_WHAT in t for t in texts) and any(ZH_WHAT in t for t in texts)


def test_fresh_u_words_typed_during_shows_save_stay_on_the_form_and_are_never_saved_twice(main, monkeypatch):
    # The adversary's S7: typed while *Show me*'s save ran, the form kept the new words (as Send's save does) — the
    # plan must follow without saving again (it saved them as a second report holding the first one's words too)
    w = _press(main)
    real_save = core.save
    gate = threading.Event()

    def slow(*a, **k):
        gate.wait(5)
        return real_save(*a, **k)
    monkeypatch.setattr(core, "save", slow)
    w.what.setPlainText(JA_WHAT)
    w.show_button.click()
    w.what.setPlainText(JA_WHAT + "\nもう一つ：Soonに戻った")              # typed meanwhile
    w.make_zip()                                                       # a second press meanwhile: says why, does nothing
    assert w.status.text() == strings.REPORT_ZIP_BUSY
    gate.set()
    assert wait_until(lambda: w.pages.currentIndex() == w.CONTENTS)
    assert wait_until(lambda: w.reports is not None and len(w.reports) == 1)
    assert [r.what for r in core.listed()] == [JA_WHAT]
    assert w.what.toPlainText().endswith("Soonに戻った")                 # kept for the learner, not saved


def test_fresh_u_with_nothing_typed_or_saved_the_grey_buttons_reason_is_in_plain_sight(main):
    # Every button of the row grey, and the window's own line (never only a hover) says what lights them
    w = _press(main)
    assert wait_until(lambda: w.status.text() == strings.REPORT_EMPTY) and w.status.isVisibleTo(w)
    assert "write what happened" in strings.REPORT_EMPTY
    assert not any(b.isEnabled() for b in (w.save_button, w.show_button, w.zip_button, w.send_button))
    w.what.setPlainText("   ")                                         # blanks are not words
    assert not w.show_button.isEnabled() and not w.zip_button.isEnabled()


def test_fresh_u_a_short_screen_gets_a_window_that_fits_and_scrolls_to_the_privacy_line(main, monkeypatch):
    # 1,224 px on a 1080p screen put the privacy line and *New code* below the screen's edge: the window now asks for
    # no more than the screen's available height (less its frame) and its body scrolls; the line is reachable
    from PyQt6.QtCore import QRect
    monkeypatch.setattr(windows, "screen_area", lambda win: QRect(0, 0, 1280, 420))
    w = _press(main)
    assert w.body_scroll is not None and w.promise.parent() is not w
    assert w.sizeHint().height() <= 420 and w.height() <= 420
    assert w.body_scroll.verticalScrollBar().maximum() > 0             # taller than the room: it scrolls inside
    w.body_scroll.ensureWidgetVisible(w.promise)
    QApplication.processEvents()
    top = w.promise.mapTo(w.body_scroll.viewport(), QPoint(0, 0)).y()
    assert 0 <= top and top + w.promise.height() <= w.body_scroll.viewport().height()


def test_fresh_u_a_window_crossing_the_screens_bottom_is_moved_up_onto_it(main, monkeypatch):
    from PyQt6.QtCore import QRect
    # A stand-in screen taller than the window can be (its height, title bar included, is the real screen's room at
    # most): 700 rows let a window that tall cross the bottom from y=10 once Windows reported its frame — a race the
    # 3.0.0 cut's --all met. Only the move to y=1500 crosses it here.
    monkeypatch.setattr(windows, "screen_area", lambda win: QRect(0, 0, 1280, 1600))
    w = _press(main)
    w.move(40, 1500)
    windows.onto_screen(w)
    assert w.frameGeometry().bottom() <= 1599 and w.x() == 40 and w.y() < 1500
    w.move(40, 10)
    windows.onto_screen(w)                                             # on the screen already: never moved
    assert w.pos() == QPoint(40, 10)
