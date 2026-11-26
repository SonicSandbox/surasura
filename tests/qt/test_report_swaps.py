"""SWAPS-REPORT on What goes (`app/qt/report.py`; Sonic's yes, OPEN-FOR-SONIC § 92): the learner's swaps beside the
flagged sentences — one painted list, a tick each, all ticked; an unticked swap stays out of the zip that goes and
comes again in the next report; swaps alone light *Send report* since SEND-EASY
(`tests/qt/test_send_easy_window.py`).

What a wrong answer costs: an unticked swap sent; the list a widget per line (a slow page with many swaps); a swap's
line with no old sentence said as nothing at all. Real lines from tests/Test Resources (ja/library_episode.ass,
zh/night_market.srt).
"""
import io
import json
import zipfile

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from app import report as core
from app import send_report
from app.connect import swap, swap_queue
from app.qt import report as report_ui
from app.qt import strings, windows
from tests.qt.conftest import wait_until
from tests.qt.test_report_window import JA_WHAT, _look, _press, _save, main, receiver  # noqa: F401
from tests.test_swaps_report import CASES, _ask


def test_what_goes_shows_each_swap_ticked_and_an_unticked_one_stays_for_the_next_report(main, receiver):
    lang = windows.language_of(main)
    word, old, new = CASES[lang]
    a, _ = _ask(lang, 9000, line=new, old=old)
    swap_queue.made(lang, a["id"], 9100)
    b, _ = _ask(lang, 9010, old=old)
    w = _press(main)
    _save(w, JA_WHAT)
    _look(w)
    sw = w.goes_swaps
    assert not sw.isHidden() and not w.goes_swaps_line.isHidden()
    assert w.goes_swaps_line.text() == strings.REPORT_SWAPS_HEADING and sw.toolTip() == strings.REPORT_SWAPS_TIP
    assert sorted(sw.keep()) == sorted([f"q:{a['id']}", f"q:{b['id']}"])  # every swap ticked
    assert sw.findChildren(QWidget) == [] and core.SWAPS in w.goes_files.text()
    made_row = [i for i, line in enumerate(sw.lines) if line["id"] == f"q:{a['id']}"][0]
    top = 1 + sum(sw._row_height(x) for x in sw.lines[:made_row])
    QTest.mouseClick(sw, Qt.MouseButton.LeftButton, pos=QPoint(20, top + 6))   # the made swap's tick: off
    assert sw.keep() == [f"q:{b['id']}"] and w.goes_send.isEnabled()
    w.goes_send.click()
    assert wait_until(lambda: w.status.text() == "Sent. Your report is #K3Q7PM", 15)
    with zipfile.ZipFile(io.BytesIO(receiver.got[0]["body"])) as z:
        (gone,) = json.loads(z.read(core.SWAPS))["swaps"]
    assert (gone["word"], gone["old"], gone["state"]) == (word, old, "waiting")
    assert send_report.swaps_sent(lang) == {f"q:{b['id']}": "waiting"}
    assert [x[0] for x in swap.for_report(lang, sent=send_report.swaps_sent(lang))] == [f"q:{a['id']}"]   # (next)


def test_a_swap_ticked_beside_every_flag_unticked_and_no_report_still_sends(main, receiver):
    from app.services import flags
    lang = windows.language_of(main)
    _ask(lang, 9300, old=CASES[lang][1])
    flags.add(lang, CASES[lang][1], CASES[lang][0], "journey", key="e3:1.0", reasons=["too_long"])
    w = _press(main)
    assert wait_until(lambda: w.flag_count == 1)
    _look(w)
    assert len(w.goes_swaps.keep()) == 1
    w.goes_flags.toggle(0)                                                    # the flag off, the swap still ticked
    assert w.goes_send.isEnabled() and w.goes_send.toolTip() == strings.REPORT_GOES_SEND_TIP   # (SEND-EASY)
    w.goes_swaps.toggle(0)                                                    # the swap off too: nothing to send
    assert not w.goes_send.isEnabled() and w.goes_send.toolTip() == strings.REPORT_FLAGS_NONE_TIP
    w.back()


def test_swap_texts_say_the_old_sentence_the_new_one_the_word_when_and_what_came_of_it():
    word, old, new = CASES["ja"]
    assert report_ui.swap_texts({"word": word, "old": old, "new": new, "asked": "2026-11-24T09:01:00",
                                 "state": "made", "why": None}) == [
        (old, False), (f"→ {new}", False), (f"{word} · asked 2026-11-24 · made", True)]
    word, old, _new = CASES["zh"]
    assert report_ui.swap_texts({"word": word, "old": None, "new": None, "asked": None, "state": "dropped",
                                 "why": "known"}) == [
        (strings.REPORT_SWAP_NO_OLD, False), (strings.REPORT_SWAP_NO_NEW, False),
        (f"{word} · dropped (the word is Known now)", True)]
