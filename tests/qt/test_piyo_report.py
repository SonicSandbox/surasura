"""Piyo's *Send report* reaching the window (app/instance_name.ask_window → the window's one-instance pipe →
`MainWindow.bring_to_front` → `report.open_from_piyo`): the learner's AI hands over a report's words; Report a problem
opens with them in its form, for the learner to read, change and send there.

What a wrong answer would cost: a report saved or sent without the learner's press; Piyo told "asked" when no window
heard it; a draft the learner was writing replaced; a second start's ordinary arguments opening Report a problem; or a
report Sonic can't tell came from the AI. A real listening window (its own pipe name per test), real Japanese words.
"""
import gc
import os
import threading

import pytest

pytest.importorskip("PyQt6")

from app import instance_name, practice, report as core, send_report
from app.qt import report as report_ui
from app.qt import shell, single, strings, windows
from tests.qt.conftest import wait_until

WHAT = "第3話のカードが作られなかった。Connectの行には「Anki Miner stopped」と出ている。"
EXPECTED = "三枚のカードがAnkiに入ること"


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


def _ask(args, result):
    """Piyo's server, as it runs: another process's thread, no Qt (`ask_window` speaks the pipe's line itself)."""
    t = threading.Thread(target=lambda: result.append(instance_name.ask_window(args)), daemon=True)
    t.start()
    return t


def test_the_open_window_hears_piyos_words_over_its_own_pipe_without_qt(qapp):
    first = single.SingleInstance()
    try:
        assert first.claim([]) is True
        heard = []
        first.activated.connect(heard.append)
        long_what = "あ" * 4000                                       # the most the server hands over: one line still
        result = []
        t = _ask([practice.REPORT_ARG, long_what, EXPECTED], result)
        assert wait_until(lambda: (gc.collect(), not t.is_alive())[1], 10)
        assert result == [True] and heard == [[practice.REPORT_ARG, long_what, EXPECTED]]
    finally:
        first.release()


def test_no_window_listening_is_said_at_once(qapp, monkeypatch):
    monkeypatch.setenv("SURASURA_INSTANCE_NAME", "surasura-test-nobody-listens-here")
    assert instance_name.ask_window([practice.REPORT_ARG, WHAT]) is None


def test_the_window_opens_report_a_problem_with_the_words_and_saves_and_sends_nothing(main, monkeypatch):
    monkeypatch.setattr(send_report, "send", lambda *a, **k: pytest.fail("never sent without the learner's press"))
    main.bring_to_front([practice.REPORT_ARG, WHAT, EXPECTED])
    w = windows.opened(main, report_ui.NAME)
    assert w is not None and w.isVisible()
    assert wait_until(lambda: w.reports is not None)
    assert w.what.toPlainText() == WHAT and w.expected.toPlainText() == EXPECTED
    assert w.pages.currentIndex() == w.FORM and w.status.text() == strings.REPORT_FROM_PIYO
    assert core.listed(core.folder()) == [] and send_report.waiting() is None      # nothing saved, nothing to send
    assert w.send_button.isEnabled()                               # the learner's press: Send report → What goes


def test_a_draft_the_learner_was_writing_is_kept_and_piyos_words_come_after_it(main):
    main.report_button.click()
    w = windows.opened(main, report_ui.NAME)
    w.what.setPlainText("Ankiのカードの順番がおかしい")
    main.bring_to_front([practice.REPORT_ARG, WHAT])
    assert w.what.toPlainText() == f"Ankiのカードの順番がおかしい\n\n{WHAT}"
    assert w.expected.toPlainText() == ""


def test_saved_it_says_it_was_written_with_piyo_and_the_next_one_doesnt(main):
    main.bring_to_front([practice.REPORT_ARG, WHAT, EXPECTED])
    w = windows.opened(main, report_ui.NAME)
    assert wait_until(lambda: w.reports is not None)
    w.save_button.click()
    assert wait_until(lambda: w.reports is not None and len(w.reports) == 1)
    assert w.reports[0].where.endswith(", written with Piyo") and w.reports[0].what == WHAT
    w.what.setPlainText("Journeyのページが開かない")
    w.save_button.click()
    assert wait_until(lambda: len(w.reports) == 2)
    assert "Piyo" not in w.reports[1].where                          # the learner's own report: theirs alone


def test_a_second_starts_own_arguments_never_open_report_a_problem(main):
    for args in ([], ["--headless"], [practice.REPORT_ARG], ["--from", practice.REPORT_ARG, WHAT]):
        main.bring_to_front(args)
        assert windows.opened(main, report_ui.NAME) is None, args


def test_a_report_heard_before_the_window_was_made_reaches_it_once_it_is(qapp):
    # setup or the start gate showing: the pipe answers, and the words wait for the window (never dropped)
    first = single.SingleInstance()
    try:
        assert first.claim([]) is True
        result = []
        t = _ask([practice.REPORT_ARG, WHAT], result)
        assert wait_until(lambda: (gc.collect(), not t.is_alive())[1], 10)
        assert result == [True] and first.pending == [[practice.REPORT_ARG, WHAT]]
        t = _ask([], result)                                          # an ordinary start after it: both kept
        assert wait_until(lambda: (gc.collect(), not t.is_alive())[1], 10)
        heard = []
        first.activated.connect(heard.append)
        assert first.replay() == 2 and heard == [[practice.REPORT_ARG, WHAT], []] and first.pending == []
        assert first.replay() == 0                                    # once
    finally:
        first.release()


def test_the_words_have_the_focus_never_a_button_a_key_could_press(main):
    main.bring_to_front([practice.REPORT_ARG, WHAT])
    w = windows.opened(main, report_ui.NAME)
    assert w.focusWidget() is w.what


def test_the_window_takes_the_starts_it_missed_once_its_first_frame_is_drawn(main):
    # the real start's order: the pipe listens from the claim, the window connects after setup and the gate
    first = single.SingleInstance()
    try:
        first.pending = [[practice.REPORT_ARG, WHAT]]                 # heard while the gate showed
        shell.connect_instance(main, first)
        assert windows.opened(main, report_ui.NAME) is None            # not before the window is drawn
        main.first_frame.emit()
        w = windows.opened(main, report_ui.NAME)
        assert w is not None and w.what.toPlainText() == WHAT and first.pending == []
    finally:
        first.release()


def test_what_goes_up_piyos_words_bring_the_form_back_with_the_focus_on_them(main):
    main.report_button.click()
    w = windows.opened(main, report_ui.NAME)
    w._whole()
    w.pages.setCurrentIndex(w.GOES)                                   # the learner was looking at What goes
    main.bring_to_front([practice.REPORT_ARG, WHAT])
    assert w.pages.currentIndex() == w.FORM and w.focusWidget() is w.what      # never Send, a key away
    assert w.what.toPlainText() == WHAT
