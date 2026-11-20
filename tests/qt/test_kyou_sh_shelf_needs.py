"""The window's half of Kyou-SH (PROVISIONAL words): the cards Connect set aside on its shelf are one *Needs you* card —
*Put back* runs Connect's own put-back (`switch.put_back`, every restore point still holding cards) on a worker and
says it in the bar; one that couldn't says why and leaves the card; *Leave them* answers it. On the window's seed.

What a wrong answer would cost a learner: Anki written from the window's thread, a *Put back* that puts back another
restore point than the card named, or the card gone though nothing came back.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import switch
from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

CONNECT = {"shelf": {"on_shelf": 236, "swap_ins": 0, "runs": [
    {"run": "shelf-20261120-171012", "cards": 236, "back": 0, "why": "the cap", "at": "2026-11-20T17:10:12Z",
     "words": ["撒く", "血塗れ"]},
    {"run": "shelf-20261118-090000", "cards": 12, "back": 12, "why": "the cap", "at": "2026-11-18T09:00:00Z",
     "words": ["眼鏡"]}]}, "needs": [], "gaps": []}


@pytest.fixture
def card(world, monkeypatch):  # noqa: F811
    main, got, answer = threading.main_thread(), [], {"failed": []}

    def put_back(shelved, *rest):
        got.append((shelved, threading.current_thread() is not main))
        return list(answer["failed"])
    monkeypatch.setattr(switch, "put_back", put_back)
    _seed, win, _writer, ny = world(connect=CONNECT)
    entry = next(e for e in ny.entries if e.kind == service.SHELVED)
    return win, ny, entry, got, answer


def test_the_card_says_how_many_are_set_aside_and_offers_put_back_and_leave_them(card):
    _win, ny, entry, _got, _answer = card
    assert entry.title == "236 cards made for you are set aside."
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"put_back_shelf", "leave_shelf"}
    assert button(ny, entry.key, "put_back_shelf").toolTip() and button(ny, entry.key, "leave_shelf").toolTip()


def test_put_back_runs_on_a_worker_with_the_restore_points_still_holding_cards(card):
    win, ny, entry, got, _answer = card
    said = []
    win.say = said.append
    button(ny, entry.key, "put_back_shelf").click()
    assert wait_until(lambda: got and said, 5)
    [(shelved, on_worker)] = got
    assert on_worker, "Anki is never written from the window's thread"
    assert shelved == {"ja": (236, ["shelf-20261120-171012"])}, "never the restore point already back"
    assert said == [strings.NEEDS_SHELF_BACK]


def test_a_put_back_that_couldnt_says_why(card):
    win, ny, entry, _got, answer = card
    answer["failed"] = ["You're reviewing in Anki. Undo once you've finished."]
    said = []
    win.say = said.append
    button(ny, entry.key, "put_back_shelf").click()
    assert wait_until(lambda: said, 5)
    assert said == [strings.NEEDS_SHELF_NOT_BACK.format(why="You're reviewing in Anki. Undo once you've finished.")]


def test_leave_them_answers_the_card(card):
    _win, ny, entry, _got, _answer = card
    button(ny, entry.key, "leave_shelf").click()
    assert wait_until(lambda: entry.key in service.read_answered("ja"), 5)
    assert wait_until(lambda: not any(e.kind == service.SHELVED for e in ny.entries), 5)
