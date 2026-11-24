"""The window's half of Kyou-SH2 (PROVISIONAL words): a tidy is one *Needs you* card — *Undo* runs Tidy's Undo
(`tidy.act_undo`, that tidy's id) on a worker and says it in the bar; one that couldn't says why and leaves the card;
*OK* answers it. Settings › Anki & mining's *Tidy waiting cards* row under the cap: *Tidy now* runs `tidy.act` on a
worker and says what it did. On the window's seed.

What a wrong answer would cost a learner: Anki written from the window's thread, an Undo of another tidy than the card
named, the card gone though nothing came back, or a press that says nothing.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import tidy
from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

CONNECT = {"tidied": {"id": 4, "cards": 37, "at": "2026-11-21T06:00:00Z", "why": "auto"}, "needs": [], "gaps": []}


@pytest.fixture
def card(world, monkeypatch):  # noqa: F811
    main, got, answer = threading.main_thread(), [], {"back": 37, "missing": []}

    def act_undo(settings, lang, tidy_id):
        got.append((lang, tidy_id, threading.current_thread() is not main))
        return dict(answer)
    monkeypatch.setattr(tidy, "act_undo", act_undo)
    _seed, win, _writer, ny = world(connect=CONNECT)
    entry = next(e for e in ny.entries if e.kind == service.TIDIED)
    return win, ny, entry, got, answer


def test_the_card_says_how_many_were_tidied_and_offers_undo_and_ok(card):
    _win, ny, entry, _got, _answer = card
    assert entry.title == "37 unstudied cards deleted, a copy kept."       # Kyou-SH3: never "set aside"
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"undo_tidy", "leave_tidy"}
    assert button(ny, entry.key, "undo_tidy").toolTip() and button(ny, entry.key, "leave_tidy").toolTip()


def test_undo_runs_that_tidys_undo_on_a_worker_and_says_it(card):
    win, ny, entry, got, _answer = card
    said = []
    win.say = said.append
    button(ny, entry.key, "undo_tidy").click()
    assert wait_until(lambda: got and said, 5)
    assert got == [("ja", 4, True)], "that tidy, never from the window's thread"
    assert said == [strings.NEEDS_TIDY_BACK.format(n=37)]


def test_an_undo_that_couldnt_says_why(card):
    win, ny, entry, _got, answer = card
    answer.clear()
    answer["why"] = "You're reviewing in Anki. Undo once you've finished."
    said = []
    win.say = said.append
    button(ny, entry.key, "undo_tidy").click()
    assert wait_until(lambda: said, 5)
    assert said == [strings.NEEDS_TIDY_NOT_BACK.format(why="You're reviewing in Anki. Undo once you've finished.")]


def test_ok_answers_the_card(card):
    _win, ny, entry, _got, _answer = card
    button(ny, entry.key, "leave_tidy").click()
    assert wait_until(lambda: entry.key in service.read_answered("ja"), 5)
    assert wait_until(lambda: not any(e.kind == service.TIDIED for e in ny.entries), 5)


def test_tidy_now_sits_under_the_cap_and_is_filled_by_the_live_page():
    rows = [r.id for r in catalog.ROWS]
    assert rows.index("connect_tidy") == rows.index("connect_backlog_cap") + 1
    row = catalog.ROW["connect_tidy"]
    assert row.kind == "action" and row.sub and catalog.FILLED_BY["connect_tidy"] == "app.qt.settings_live"
    assert S.TIDY_NOW == "Tidy now" and row.label and row.tip


def test_tidy_now_runs_on_a_worker_and_says_what_it_did(qapp, monkeypatch):
    # why: the press reacts at once (its arc), Anki is written off the window's thread, and the bar says the count —
    # or why nothing was tidied
    from tests.qt.test_settings_live import Fakes, make
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes, data={"connect_enabled": True})
    main, got, answer = threading.main_thread(), [], {"cards": 12, "id": 3}

    def act(settings, lang, steps=None):
        got.append((lang, threading.current_thread() is not main))
        return dict(answer)
    monkeypatch.setattr(tidy, "act", act)
    button = page.live.parts["connect_tidy"]["tidy"]
    assert button.toolTip() and button.text() == S.TIDY_NOW
    button.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [S.TIDY_DONE.format(n=12)], 5)
    assert got == [("ja", True)] and store.calls == [], "on a worker; the press writes no setting"
    answer.clear()
    answer.update(cards=0, say=tidy.NOTHING)
    button.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [S.TIDY_NONE.format(why=tidy.NOTHING)], 5)
