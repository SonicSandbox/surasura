"""The window's half of Iro-AA's book answer (PROVISIONAL): with the AI voice's beta on and installed, the book's
question (Kura-AB2's *Do you have 「…」's audiobook?*) offers **Pick its audiobook… · Make AI audio (beta) · Mine
without audio**; with it off — or the module absent — the card is Kura-AB2's two answers, unchanged.

What a wrong answer would cost a learner: AI audio offered while nothing can make it (the beta off or not installed),
the beta's state read on the window's thread (a freeze: it looks at files), or an answer that never reaches Connect.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import runner
from app.qt import strings
from tests.qt.conftest import wait_until
from tests.qt.test_audiobook_find_window import _with_audiobook_writer
from tests.qt.test_needs_you import button, settle, world  # noqa: F401 (the fixture)

NEKO = "吾輩は猫である"


@pytest.fixture
def ask(world):  # noqa: F811
    _with_audiobook_writer()
    main, got = threading.main_thread(), []

    def rec(name, value=True):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return value
        return call
    say = runner.BOOK_AUDIO_ASK.format(title=NEKO)
    connect = {"jobs": [{"item": 7, "state": "waiting", "reason": say}],
               "needs": [{"id": 21, "kind": runner.BOOK_AUDIO_NEED, "say": say, "item": 7, "seen_at": None,
                          "at": "2026-11-01T05:00:00Z"}]}
    seed, win, writer, ny = world(connect=connect, connect_calls={
        "book_audiobook": rec("book_audiobook"), "book_ai_audio": rec("book_ai_audio"), "kick": rec("kick", None)})
    return ny, got, main


def _on(ny, main, on=True):
    looked = []

    def ai_audio_on(settings):
        looked.append(threading.current_thread() is not main)
        return on
    ny.ai_audio_on = ai_audio_on
    ny.refresh()
    settle(ny)
    return looked


def _entry(ny):
    return next(e for e in ny.entries if e.kind == runner.BOOK_AUDIO_NEED)


def test_with_the_beta_off_the_card_keeps_its_two_answers(ask):
    ny, _got, _main = ask
    assert {b.property("action") for b in ny.cards.buttons(_entry(ny).key)} == \
        {"pick_audiobook", "no_audiobook", "dismiss"}


def test_with_the_beta_on_make_ai_audio_sits_between_the_two_read_on_a_worker(ask):
    ny, _got, main = ask
    looked = _on(ny, main)
    assert looked and all(looked)                                   # the beta's look: never the window's thread
    entry = _entry(ny)
    shown = [b.property("action") for b in ny.cards.buttons(entry.key)]
    assert shown.index("pick_audiobook") < shown.index("ai_audio") < shown.index("no_audiobook")
    assert button(ny, entry.key, "ai_audio").text() == strings.NEEDS_ACTIONS["ai_audio"][0] == "Make AI audio (beta)"


def test_make_ai_audio_answers_connect_on_a_worker_then_kicks_it(ask):
    ny, got, main = ask
    _on(ny, main)
    button(ny, _entry(ny).key, "ai_audio").click()
    assert wait_until(lambda: [g[0] for g in got] == ["book_ai_audio", "kick"], 5)
    assert got[0][1] == ("ja", 21) and all(g[2] for g in got)


def test_the_beta_turned_off_takes_the_answer_away_again(ask):
    ny, _got, main = ask
    _on(ny, main)
    _on(ny, main, on=False)
    assert "ai_audio" not in {b.property("action") for b in ny.cards.buttons(_entry(ny).key)}
