"""The window's half of *Add audio to these cards* (Kura-AB3 A2; PROVISIONAL): a book lined up with its audiobook after
some of its cards were made says so on *Needs you* — *Add the narrator's voice* runs Connect's `add_audio` on a worker
(the arc turns meanwhile), then a toast with its *Undo* (Connect's `add_audio_undo`, on a worker too); a "couldn't"
(you're reviewing, Anki closed) says why and leaves the line. On the window's seed.

What a wrong answer would cost a learner: Anki written from the window's thread (a freeze for a whole book's clips), a
press with no Undo, an Undo that takes back another press's audio, or a line gone though nothing was added.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import runner
from app.qt import strings
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

STAR = "星屑の剣士になりたくて！"


@pytest.fixture
def offer(world):  # noqa: F811
    main, got = threading.main_thread(), []
    answers = {"add_audio": {"ok": True, "filled": 5, "id": "17-ab", "title": STAR, "not_cut": 0, "why": None,
                             "say": None},
               "add_audio_undo": {"ok": True, "emptied": 5, "kept": 0, "say": None}}

    def rec(name):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return answers[name]
        return call
    say = runner.ADD_AUDIO_ASK.format(title=STAR, n=8)
    connect = {"jobs": [], "needs": [{"id": 31, "kind": runner.ADD_AUDIO_NEED, "say": say, "item": 9, "seen_at": None,
                                      "at": "2026-11-12T05:00:00Z"}]}
    _seed, win, _writer, ny = world(connect=connect, connect_calls={"add_audio": rec("add_audio"),
                                                                    "add_audio_undo": rec("add_audio_undo")})
    entry = next(e for e in ny.entries if e.kind == runner.ADD_AUDIO_NEED)
    return win, ny, entry, got, answers


def test_the_books_line_offers_the_narrators_voice_with_a_tooltip(offer):
    _win, ny, entry, _got, _answers = offer
    assert entry.title == runner.ADD_AUDIO_ASK.format(title=STAR, n=8)
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"add_audio", "dismiss"}
    b = button(ny, entry.key, "add_audio")
    assert b.text() == strings.NEEDS_ACTIONS["add_audio"][0] and b.toolTip()


def test_the_press_runs_on_a_worker_then_its_toast_undoes_that_record_on_a_worker(offer):
    win, ny, entry, got, _answers = offer
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: any(g[0] == "add_audio" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "add_audio"]
    assert on_worker and args[:2] == ("ja", 31)
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == strings.NEEDS_AUDIO_ADDED.format(n=5, title=STAR)
    undo = next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO)
    undo.click()
    assert wait_until(lambda: any(g[0] == "add_audio_undo" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "add_audio_undo"]
    assert on_worker and args[:2] == ("ja", "17-ab")


def test_a_press_that_couldnt_says_why_and_leaves_no_undo(offer):
    win, ny, entry, got, answers = offer
    answers["add_audio"] = {"ok": False, "say": "You're reviewing in Anki. Add audio again when you're done."}
    said = []
    win.say = said.append
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: said, 5)
    assert said == ["You're reviewing in Anki. Add audio again when you're done."]
    assert not (win.toasts.alive and win.toasts.text == strings.NEEDS_AUDIO_ADDED.format(n=5, title=STAR))


def test_some_cards_not_cut_are_named_in_the_toast(offer):
    win, ny, entry, _got, answers = offer
    answers["add_audio"] = dict(answers["add_audio"], filled=3, not_cut=2, why="Anki Miner took too long.")
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == strings.NEEDS_AUDIO_SOME.format(n=3, title=STAR, m=2, why="Anki Miner took too long.")
