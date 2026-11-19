"""The window's half of One deck (Michi-DK; PROVISIONAL): cards Connect made in another deck than the one Surasura shows
are one *Needs you* card — *Move them to "<deck>"* runs `connect/decks.move` on a worker (the arc turns meanwhile),
then a toast with its *Undo* (`decks.move_back`, on a worker too); a "couldn't" (you're reviewing, another writer)
says why and leaves the card; *Leave them* answers it. On the window's seed.

What a wrong answer would cost a learner: Anki written from the window's thread, a move with no Undo, an Undo that
names another move, or the card gone though nothing moved.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import decks
from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

JA_DECK = "Japanese::Mining Deck"
MINER_DECK = "Japanese::Anki Miner"
RECORD = {"deck": JA_DECK, "from": {MINER_DECK: 12}, "cards": 12}


@pytest.fixture
def offer(world, monkeypatch):  # noqa: F811
    main, got = threading.main_thread(), []
    answers = {"move": {"ok": True, "say": decks.MOVED.format(n=12, deck=JA_DECK), "moved": 12, "deck": JA_DECK,
                        "id": "20261118-120000-7"},
               "move_back": {"ok": True, "say": decks.UNDONE.format(n=12), "back": 12}}

    def rec(name):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return answers[name]
        return call
    monkeypatch.setattr(service, "deck_strays", lambda lang, settings=None: RECORD)
    monkeypatch.setattr(decks, "move", rec("move"))
    monkeypatch.setattr(decks, "move_back", rec("move_back"))
    _seed, win, _writer, ny = world()
    entry = next(e for e in ny.entries if e.kind == service.DECK_STRAYS)
    return win, ny, entry, got, answers


def test_the_card_offers_the_move_by_the_decks_name_and_leave_them_with_tooltips(offer):
    _win, ny, entry, _got, _answers = offer
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"move_cards", "leave_cards"}
    move = button(ny, entry.key, "move_cards")
    assert move.text() == f"Move them to “{JA_DECK}”" and move.toolTip()
    assert button(ny, entry.key, "leave_cards").toolTip()


def test_the_move_runs_on_a_worker_then_its_toast_undoes_that_move_on_a_worker(offer):
    win, ny, entry, got, _answers = offer
    button(ny, entry.key, "move_cards").click()
    assert wait_until(lambda: any(g[0] == "move" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "move"]
    assert on_worker and args[1:] == ("ja", JA_DECK), "the deck the button named"
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == decks.MOVED.format(n=12, deck=JA_DECK)
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: any(g[0] == "move_back" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "move_back"]
    assert on_worker and args[1] == "20261118-120000-7"


def test_a_move_that_couldnt_says_why_and_offers_no_undo(offer):
    win, ny, entry, _got, answers = offer
    answers["move"] = {"ok": False, "say": "You're reviewing in Anki. Press again when you're done."}
    said = []
    win.say = said.append
    button(ny, entry.key, "move_cards").click()
    assert wait_until(lambda: said, 5)
    assert said == ["You're reviewing in Anki. Press again when you're done."]
    assert not (win.toasts.alive and win.toasts.text == decks.MOVED.format(n=12, deck=JA_DECK))


def test_a_move_anki_stopped_answering_in_still_offers_its_undo(offer):
    win, ny, entry, got, answers = offer
    answers["move"] = {"ok": False, "say": "Anki stopped answering while the cards went to …: look in Anki.",
                       "moved": None, "deck": JA_DECK, "id": "20261118-120001-7"}
    button(ny, entry.key, "move_cards").click()
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == answers["move"]["say"]
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: any(g[0] == "move_back" for g in got), 5)
    assert [g[1][1] for g in got if g[0] == "move_back"] == ["20261118-120001-7"]


def test_leave_them_answers_the_card(offer):
    _win, ny, entry, _got, _answers = offer
    button(ny, entry.key, "leave_cards").click()
    assert wait_until(lambda: service.strays_key(RECORD) in service.read_answered("ja"), 5)
    assert wait_until(lambda: not any(e.kind == service.DECK_STRAYS for e in ny.entries), 5)
