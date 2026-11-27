"""The window's half of a book's line-up line (Kura-AB3 A2, cut down by AUDIO-FILL: the write is Card sound's;
PROVISIONAL): a book paired with its audiobook after some of its cards were made says so on *Needs you* — *Line it up*
runs Connect's `add_audio` on a worker: not lined up yet, its first part's *Mine now* through the window's own path;
lined up already, Card sound's *Add sound* answer, a toast with its *Undo* (`card_sound.press_undo`, on a worker too);
a "couldn't" says why and leaves the line. On the window's seed.

What a wrong answer would cost a learner: Anki written from the window's thread (a freeze for a whole book's clips), a
press with no Undo, an Undo that takes back another press's sound, or a line gone though nothing was done.
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
    answers = {"add_audio": {"ok": True, "id": "17-ab", "real": 5, "not_cut": 0, "say": None, "sound": True,
                             "title": STAR},
               "add_sound_undo": {"ok": True, "emptied": 5, "kept": 0, "say": None}}

    def rec(name):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return answers[name]
        return call
    say = runner.ADD_AUDIO_WAIT.format(title=STAR)
    connect = {"jobs": [], "needs": [{"id": 31, "kind": runner.ADD_AUDIO_NEED, "say": say, "item": 9, "seen_at": None,
                                      "at": "2026-11-10T05:00:00Z"}]}
    _seed, win, _writer, ny = world(connect=connect, connect_calls={"add_audio": rec("add_audio"),
                                                                    "add_sound_undo": rec("add_sound_undo")})
    entry = next(e for e in ny.entries if e.kind == runner.ADD_AUDIO_NEED)
    return win, ny, entry, got, answers


def test_the_books_line_offers_its_line_up_with_a_tooltip(offer):
    """The line's one answer reads *Line it up* (never the retired *Add the narrator's voice*), with its tooltip."""
    _win, ny, entry, _got, _answers = offer
    assert entry.title == runner.ADD_AUDIO_WAIT.format(title=STAR)
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"add_audio", "dismiss"}
    b = button(ny, entry.key, "add_audio")
    assert b.text() == strings.NEEDS_ACTIONS["add_audio"][0] == "Line it up" and b.toolTip()


def test_a_press_on_a_book_lined_up_shows_card_sounds_toast_whose_undo_runs_on_a_worker(offer):
    """Lined up already: Connect's answer is Card sound's *Add sound* (`sound`) — its toast, and its Undo is Card
    sound's own (`add_sound_undo`), on a worker, for that record."""
    win, ny, entry, got, _answers = offer
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: any(g[0] == "add_audio" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "add_audio"]
    assert on_worker and args[:2] == ("ja", 31)
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 5)
    assert win.toasts.text == strings.NEEDS_SOUND_ADDED.format(n=5)
    undo = next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO)
    undo.click()
    assert wait_until(lambda: any(g[0] == "add_sound_undo" for g in got), 5)
    [(_name, args, on_worker)] = [g for g in got if g[0] == "add_sound_undo"]
    assert on_worker and args[:2] == ("ja", "17-ab")


def test_a_press_that_couldnt_says_why_and_leaves_no_undo(offer):
    """Connect off (or the library busy): its words in the bar, no toast."""
    win, ny, entry, got, answers = offer
    answers["add_audio"] = {"ok": False, "say": "connect preview off"}
    said = []
    win.say = said.append
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: said, 5)
    assert said == ["connect preview off"]
    assert not (win.toasts.alive and win.toasts.text == strings.NEEDS_SOUND_ADDED.format(n=5))


def test_a_press_that_couldnt_can_be_pressed_again(offer):
    """Mutant Q1: a "couldn't" leaves the line — pressed again at once, it asks Connect again."""
    win, ny, entry, got, answers = offer
    answers["add_audio"] = {"ok": False, "say": "connect preview off"}
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: len([g for g in got if g[0] == "add_audio"]) == 1, 5)
    assert wait_until(lambda: button(ny, entry.key, "add_audio") is not None and
                      button(ny, entry.key, "add_audio").isEnabled(), 5)
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: len([g for g in got if g[0] == "add_audio"]) == 2, 5)


def test_a_press_on_a_book_not_lined_up_asks_mine_now_on_its_first_part_through_the_windows_path(offer):
    """r4: Connect answers "line it up first" — the window asks *Mine now* for that part (its own path: its row turns,
    its job lines the book up, seen and stoppable there); no toast, nothing undone."""
    win, ny, entry, got, answers = offer
    asked = []
    win.mine = type("Mine", (), {"ask_items": lambda self, text, ids: asked.append((text, ids))})()
    answers["add_audio"] = {"ok": False, "line_up": 42, "title": STAR, "say": "「x」 is lined up with its audiobook first"}
    button(ny, entry.key, "add_audio").click()
    assert wait_until(lambda: asked, 5)
    assert asked == [("「x」 is lined up with its audiobook first", [42])]
    assert not [g for g in got if g[0] == "add_sound_undo"]


def test_the_line_has_no_answer_without_card_sounds_undo(world):  # noqa: F811
    """The press can write (Card sound's *Add sound*): without its Undo call, the line offers no *Line it up*."""
    connect = {"jobs": [], "needs": [{"id": 31, "kind": runner.ADD_AUDIO_NEED, "say": runner.ADD_AUDIO_WAIT.format(
        title=STAR), "item": 9, "seen_at": None, "at": "2026-11-10T05:00:00Z"}]}
    _seed, _win, _writer, ny = world(connect=connect, connect_calls={"add_audio": lambda *a: {"ok": False},
                                                                     "add_sound_undo": None})
    entry = next(e for e in ny.entries if e.kind == runner.ADD_AUDIO_NEED)
    assert "add_audio" not in {b.property("action") for b in ny.cards.buttons(entry.key)}
