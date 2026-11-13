"""Michi-RM3: *Needs you*'s line for a part whose cards Anki refused for some words (`mine-refused`) offers *Skip this
word* first, then *Try again*. Pressed, *Skip this word* asks Connect's `actions.skip_refused` on a worker, kicks
Connect so the part's other cards are filled now, and says so in the bar; nothing left to skip (its job went on
meanwhile): the bar says that, and the card stays to be answered again. Every press reacts at once (its arc turns).

What a wrong answer would cost: a button that does nothing, a skip that leaves the part waiting for Connect's next
start, or a skip pressed on the wrong language's line.

On the window's seed through a recording writer (`test_p41_actions`'s); Connect's calls replaced by recorders.
"""
import pytest

pytest.importorskip("PyQt6")

from app.connect import runner
from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_p41_actions import act, asks  # noqa: F401  (act: a fixture)

SAY = runner.MINE_REFUSED_SAY.format(title="カラフル Part 32", words="塗れ",
                                     why="AnkiConnect error in 'addNotes': ['cannot create note for unknown reason']",
                                     hint=runner.CLOZE_HINT)


def _entry(need_id=21):
    rec = {"needs": [{"id": need_id, "kind": runner.MINE_REFUSED, "say": SAY, "item": 32, "title": None,
                      "at": "2026-11-10T05:00:00Z", "seen_at": None}]}
    return next(e for e in service.entries(None, connect=rec) if e.kind == runner.MINE_REFUSED)


def test_the_refused_line_offers_skip_this_word_and_never_try_again():
    # Kantan-B2 (AUDIT B5, Sonic's yes 2026-11-12): Anki refuses the word for good (Anki Miner's MINING_FAILED, not
    # transient: #ZHFKV0's 24 identical failures) — *Try again* would fail the same way, so the line offers only *Skip
    # this word*, says why, and never tells him to try again
    entry = _entry()
    assert entry.actions[0] == "skip_words" and "try_again" not in entry.actions
    assert "{{c1::" in entry.title and "塗れ" in entry.title
    assert "Try again" not in entry.title and "Try again" not in runner.MINE_REFUSED_SAY
    assert strings.NEEDS_ACTIONS["skip_words"][0] == "Skip this word"


def test_skip_this_word_asks_connect_then_kicks_it_and_says_so(act, monkeypatch):
    from app.services import press as press_service
    monkeypatch.setattr(press_service, "LINGER_S", 0.0)
    _seed, win, _writer = act()
    ny = win.needs_you
    assert ny.available("skip_words")
    held = ny.connect_calls["skip_words"]
    ny.connect_calls["skip_words"] = None             # Connect's actions can't be loaded: no button that does nothing
    assert not ny.available("skip_words")
    ny.connect_calls["skip_words"] = held
    calls, answer = [], ["on"]
    ny.connect_calls["skip_words"] = lambda lang, need_id: calls.append(("skip", lang, need_id)) or answer[0]
    ny.connect_calls["kick"] = lambda settings: calls.append(("kick",)) or object()
    ny.act("skip_words", _entry(), None)
    assert wait_until(lambda: len(calls) == 2, 5), calls
    assert calls == [("skip", ny.language, 21), ("kick",)]
    assert wait_until(lambda: win.bar_line.full() == strings.NEEDS_SKIPPED, 5)
    del calls[:]
    answer[0] = "owes"                                  # skipped, its other words still owed: said so, never "made next"
    ny.act("skip_words", _entry(23), None)
    assert wait_until(lambda: win.bar_line.full() == strings.NEEDS_SKIPPED_OWES, 5)
    del calls[:]
    answer[0] = False                                   # nothing to skip any more: no kick, said
    ny.act("skip_words", _entry(22), None)
    assert wait_until(lambda: win.bar_line.full() == strings.NEEDS_SKIPPED_NOT, 5)
    assert calls == [("skip", ny.language, 22)]
