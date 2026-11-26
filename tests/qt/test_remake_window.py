"""The window's half of REMAKE (3.0.19; PROVISIONAL words): Settings › Anki & mining's *Make my new cards again…*
under *Tidy waiting cards*. The press reacts at once (its arc) and counts on a worker (`tidy.act_remake_plan`:
nothing deleted); the sheet then shows the counts (made by Surasura · kept, by why), the sync line and that edits go
with the cards and stay in the copy; No is the default and the action is painted as a danger; *from before* is a tick,
off; Yes runs `tidy.act_remake` on a worker with the tick as given and says the count (and the words of any card
studied meanwhile, kept). A count that can't run says why and opens no sheet. ja + zh. (Esc, Back and a click outside are No for every sheet
through the shell's router: `tests/qt/test_confirm.py`.)

What a wrong answer would cost a learner: cards deleted from the window's thread, the cards from before deleted
though the tick was off, a sheet that opens with Yes ready under Enter, or a press that says nothing.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import tidy
from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until

WORDS = {"ja": ["雰囲気", "溜め息"], "zh": ["气氛", "叹气"]}
PLAN = {"made": [101, 102, 103], "before": [201, 202], "kept": {"you've studied it": 4, "you flagged it": 1},
        "decks": ["日本語::Mining"], "models": ["Lapis"]}


def test_the_row_sits_under_tidy_and_is_filled_by_the_live_page():
    rows = [r.id for r in catalog.ROWS]
    assert rows.index("connect_remake") == rows.index("connect_tidy") + 1
    row = catalog.ROW["connect_remake"]
    assert row.kind == "action" and row.sub and catalog.FILLED_BY["connect_remake"] == "app.qt.settings_live"
    assert row.label and row.tip


def _page(monkeypatch, language):
    from tests.qt.test_settings_live import Fakes, make
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes, data={"connect_enabled": True})
    page.language = language
    return page, store, shell_


def _sheet(page):
    assert wait_until(lambda: getattr(page.live, "remake_card", None) is not None
                      and page.live.remake_card.isVisible(), 5), "the sheet opens"
    return page.live.remake_card


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_count_then_the_sheet_then_the_yes_with_the_tick_off(qapp, monkeypatch, lang):
    # why: the count never deletes; the sheet says what goes and what stays; the tick from before is off unless
    # ticked; Anki is written only after the yes, off the window's thread
    main, counted, went = threading.main_thread(), [], []

    def act_remake_plan(settings, language, anki=None):
        counted.append((language, threading.current_thread() is not main))
        return dict(PLAN)

    def act_remake(settings, language, before=False, steps=None, anki=None):
        went.append((language, before, threading.current_thread() is not main))
        return {"cards": 3, "id": 7, "kept": 5, "queued": 3, "ahead": 0, "studied": []}
    monkeypatch.setattr(tidy, "act_remake_plan", act_remake_plan)
    monkeypatch.setattr(tidy, "act_remake", act_remake)
    page, store, shell_ = _page(monkeypatch, lang)
    door = page.live.parts["connect_remake"]["remake"]
    assert door.text() == S.REMAKE_NOW and door.toolTip()
    door.click()
    card = _sheet(page)
    assert counted == [(lang, True)], "counted on a worker"
    assert card.title.text() == S.REMAKE_ASK.format(n=3)
    body = card.body.text()
    assert S.REMAKE_COUNTS.format(made=3) in body and S.REMAKE_SYNC in body and S.REMAKE_EDITS in body
    assert "you've studied it 4" in body and "you flagged it 1" in body
    assert card.check is not None and card.check.text() == S.REMAKE_BEFORE.format(n=2) and card.check.toolTip()
    assert not card.check.isChecked(), "from before: off by default"
    assert card.yes.property("kind") == "danger" and card.yes.toolTip() and card.no.toolTip()
    assert qapp.focusWidget() is not card.yes, "No by default: Enter never deletes"
    assert went == [], "nothing deleted before the yes"
    card.yes.click()
    assert wait_until(lambda: went, 5)
    assert went == [(lang, False, True)], "the tick off: the cards from before stay; on a worker"
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [S.REMAKE_DONE.format(n=3, q=3)], 5)
    assert store.calls == [], "the press writes no setting"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_tick_on_takes_the_cards_from_before_and_a_card_studied_meanwhile_is_named(qapp, monkeypatch, lang):
    went = []
    monkeypatch.setattr(tidy, "act_remake_plan", lambda s, language, anki=None: {"made": [], "before": [201],
                                                                                  "kept": {}, "decks": [], "models": []})

    def act_remake(settings, language, before=False, steps=None, anki=None):
        went.append(before)
        return {"cards": 1, "id": 8, "kept": 2, "queued": 1, "ahead": 0, "studied": WORDS[lang]}
    monkeypatch.setattr(tidy, "act_remake", act_remake)
    page, _store, shell_ = _page(monkeypatch, lang)
    page.live.parts["connect_remake"]["remake"].click()
    card = _sheet(page)
    assert card.title.text() == S.REMAKE_ASK_ONE and card.check.text() == S.REMAKE_BEFORE_ONE
    card.check.setChecked(True)
    card.yes.click()
    assert wait_until(lambda: went, 5) and went == [True]
    line = S.REMAKE_DONE.format(n=1, q=1) + S.REMAKE_STUDIED.format(words="、".join(WORDS[lang]))
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [line], 5)


def test_no_deletes_nothing_and_a_count_that_cant_run_opens_no_sheet(qapp, monkeypatch):
    from app.cli.contract import CliError
    went, answers = [], [{"made": [101], "before": [], "kept": {}, "decks": [], "models": []}]

    def act_remake_plan(settings, language, anki=None):
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    monkeypatch.setattr(tidy, "act_remake_plan", act_remake_plan)
    monkeypatch.setattr(tidy, "act_remake", lambda *a, **k: went.append(1) or {"cards": 1})
    page, _store, shell_ = _page(monkeypatch, "ja")
    door = page.live.parts["connect_remake"]["remake"]
    door.click()
    card = _sheet(page)
    assert card.check is None, "no card from before: no tick"
    card.no.click()
    assert wait_until(lambda: not card.isVisible(), 5) and went == []
    page.live.remake_card = None
    answers.append(CliError("busy", tidy.REMAKE_MINING))         # Connect mining (SORT-BAR's lock)
    door.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [S.REMAKE_CANT.format(why=tidy.REMAKE_MINING)], 5)
    assert page.live.remake_card is None and went == []
    answers.append({"cards": 0, "say": tidy.NOTHING_NEW})
    door.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [S.REMAKE_NONE.format(why=tidy.NOTHING_NEW)], 5)
    assert page.live.remake_card is None
