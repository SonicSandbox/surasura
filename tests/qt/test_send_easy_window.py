"""SEND-EASY in the window (`app/qt/report.py`; the lead's card, Sonic 2026-11-25): *Send report* is one easy "help us
improve" button — lit by anything there is to send (a saved report, flagged sentences, swaps, the cards the learner
didn't want), with nothing written; grey, with its tip, when there is nothing. What goes shows the cards beside the
swaps, a tick each; any one ticked is something to send. The form says what it's for: its heading, with its one line
behind a ?, and the bug's tip.

What a wrong answer costs: a learner with swaps waiting told to write something first (Sonic: "an easy button option
not confusing"), an unticked card sent, or the form's words still framing it as a bug report only. Real lines from
tests/Test Resources (ja/library_episode.ass, zh/night_market.srt and its traditional lines).
"""
import io
import json
import zipfile

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QWidget

from app import report as core
from app import send_report
from app.connect import deleted
from app.qt import report as report_ui
from app.qt import strings, windows
from app.qt.tooltip import AboutMark
from tests.qt.conftest import wait_until
from tests.qt.test_report_window import _look, _press, main, receiver  # noqa: F401
from tests.test_send_easy import GONE, _gone
from tests.test_swaps_report import CASES, _ask


def test_nothing_to_send_keeps_send_report_grey_with_its_tip(main):
    w = _press(main)
    assert not w.send_button.isEnabled() and w.send_button.toolTip() == strings.REPORT_SEND_NONE_TIP
    assert w.flags_line.isHidden() and w.status.text() == strings.REPORT_EMPTY


def test_swaps_alone_light_send_report_and_the_form_says_what_waits(main, receiver):
    lang = windows.language_of(main)
    entry, _ = _ask(lang, 9200, old=CASES[lang][1])
    w = _press(main)
    assert wait_until(lambda: w.send_button.isEnabled())
    assert w.send_button.toolTip() == strings.REPORT_SEND_TIP
    assert not w.flags_line.isHidden() and w.flags_line.text() == report_ui.waiting_words(0, 1, 0)
    assert w.status.text() != strings.REPORT_EMPTY                           # never "nothing to send" beside them
    _look(w)
    assert w.goes_swaps.keep() == [f"q:{entry['id']}"] and w.goes_send.isEnabled()
    w.goes_swaps.toggle(0)                                                   # the one swap off: nothing to send
    assert not w.goes_send.isEnabled() and w.goes_send.toolTip() == strings.REPORT_FLAGS_NONE_TIP
    w.goes_swaps.toggle(0)
    assert w.goes_send.isEnabled()
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == "Sent. Your report is #K3Q7PM", 15)
    with zipfile.ZipFile(io.BytesIO(receiver.got[0]["body"])) as z:
        assert [x["word"] for x in json.loads(z.read(core.SWAPS))["swaps"]] == [CASES[lang][0]]
    assert wait_until(lambda: not w.send_button.isEnabled())                 # sent: nothing waits now


def test_the_cards_not_wanted_alone_light_it_and_what_goes_ticks_each(main, receiver):
    lang = windows.language_of(main)
    a, b = _gone(lang, [deleted.IGNORE, deleted.KNOWN])
    w = _press(main)
    assert wait_until(lambda: w.send_button.isEnabled())
    assert w.flags_line.text() == report_ui.waiting_words(0, 0, 2)
    _look(w)
    cards = w.goes_cards
    assert not cards.isHidden() and not w.goes_cards_line.isHidden()
    assert w.goes_cards_line.text() == strings.REPORT_CARDS_HEADING and cards.toolTip() == strings.REPORT_CARDS_TIP
    assert sorted(cards.keep()) == sorted([f"d:{a}", f"d:{b}"]) and cards.findChildren(QWidget) == []
    assert core.NOT_WANTED in w.goes_files.text()
    known = [i for i, line in enumerate(cards.lines) if line["id"] == f"d:{b}"][0]
    cards.toggle(known)
    assert cards.keep() == [f"d:{a}"] and w.goes_send.isEnabled()
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == "Sent. Your report is #K3Q7PM", 15)
    with zipfile.ZipFile(io.BytesIO(receiver.got[0]["body"])) as z:
        (gone,) = json.loads(z.read(core.NOT_WANTED))["cards"]
    assert (gone["word"], gone["sentence"], gone["why"]) == (GONE[lang][0][0], GONE[lang][0][2], "ignore")
    assert send_report.not_wanted_sent(lang) == {f"d:{a}": "ignore"}
    assert wait_until(lambda: w.flags_line.text() == report_ui.waiting_words(0, 0, 1))   # the unticked one waits


def test_the_form_says_it_is_for_improving_with_its_line_behind_a_question_mark(main):
    w = _press(main)
    assert main.report_button.toolTip() == strings.REPORT_TIP
    assert strings.REPORT_TIP.startswith(strings.REPORT_NAME)                 # an icon names itself first
    assert w.what_heading.text() == strings.REPORT_WHAT
    mark = w.what_about
    assert isinstance(mark, AboutMark) and mark.toolTip() == strings.REPORT_WHAT_ABOUT and not mark.isHidden()
    assert "\n" not in strings.REPORT_WHAT_ABOUT                              # one succinct line
    assert w.what.placeholderText() == strings.REPORT_WHAT_HINT


def test_waiting_words_name_each_kind_once_and_nothing_for_none():
    assert report_ui.waiting_words(0, 0, 0) == ""
    assert report_ui.waiting_words(1, 0, 0) == strings.REPORT_NEXT.format(what=strings.REPORT_NEXT_FLAGS[0])
    assert report_ui.waiting_words(2, 1, 3) == strings.REPORT_NEXT.format(what=" · ".join((
        strings.REPORT_NEXT_FLAGS[1].format(n=2), strings.REPORT_NEXT_SWAPS[0],
        strings.REPORT_NEXT_CARDS[1].format(n=3))))


def test_card_texts_say_the_sentence_then_the_word_why_and_how():
    word, _r, line = GONE["ja"][0]
    assert report_ui.card_texts({"word": word, "sentence": line, "why": "ignore", "by": "deleted",
                                 "at": "2026-11-24T09:01:00"}) == [
        (line, False), (f"{word} · {strings.REPORT_CARD_WHY['ignore']} · "
                        f"{strings.REPORT_CARD_BY['deleted'].format(when='2026-11-24')}", True)]
    word, _r, _line = GONE["zh"][1]
    assert report_ui.card_texts({"word": word, "sentence": None, "why": "known", "by": "flag", "at": None}) == [
        (strings.REPORT_CARD_NO_SENTENCE, False),
        (f"{word} · {strings.REPORT_CARD_WHY['known']} · {strings.REPORT_CARD_BY['flag'].format(when='').strip()}",
         True)]
