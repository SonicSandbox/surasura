"""The book's question in the window after AUDIO-FILL (Sonic § 106 decision 10): Kura-AB2's *Do you have 「…」's
audiobook?* offers **Pick its audiobook… · Mine without audio** whether the AI voice is on or not — Iro-AA's *Make AI
audio (beta)* between them is retired into Card sound (*Add sound*: the AI voice reads a book's cards as they come
due, whatever the answer).

What a wrong answer would cost a learner: a third answer that leads nowhere (its writer is gone), or the voice's state
read on the window's thread again (a freeze: it looks at files).
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
def ask(world, monkeypatch):  # noqa: F811
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
    seed, win, writer, ny = world(connect=connect, connect_calls={"book_audiobook": rec("book_audiobook"),
                                                                  "kick": rec("kick", None)})
    return ny, got, main


def _entry(ny):
    return next(e for e in ny.entries if e.kind == runner.BOOK_AUDIO_NEED)


@pytest.mark.parametrize("voice_on", [False, True])
def test_the_books_card_keeps_its_two_answers_with_the_voice_on_or_off(ask, monkeypatch, voice_on):
    ny, _got, _main = ask
    from app.connect import card_sound
    monkeypatch.setattr(card_sound, "_voice_on", lambda s, l: voice_on)
    settle(ny)
    assert {b.property("action") for b in ny.cards.buttons(_entry(ny).key)} == \
        {"pick_audiobook", "no_audiobook", "dismiss"}
    assert "ai_audio" not in strings.NEEDS_ACTIONS


def test_mine_without_audio_answers_connect_on_a_worker_then_kicks_it(ask):
    ny, got, _main = ask
    button(ny, _entry(ny).key, "no_audiobook").click()
    assert wait_until(lambda: [g[0] for g in got] == ["book_audiobook", "kick"], 5)
    assert got[0][1] == ("ja", 21) and all(g[2] for g in got)
