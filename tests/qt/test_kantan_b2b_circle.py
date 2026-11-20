"""Kantan-B2b: setup's *Make cards for your first 20 episodes?* stays reachable until the yes (Sonic, 2026-11-19:
nothing mines until the yes; Not now is no yes) — while it stands on *Needs you*, asked or after its *Not now*, the
鉱 circle is amber and its press opens that card (a7: amber only for a decision, and a press goes to it). Gone with
the card. What a wrong answer would cost: a learner who said *Not now* and can't find the question again — or an
amber 鉱 that stays after the yes, a decision that isn't there.
"""
from types import SimpleNamespace

from app.qt import shell, strings
from app.services import needs as service
from app.services import phase


class _Strip:
    def __init__(self):
        self.parts = {}
        self.calls = []

    def set_extra(self, circle, key, state=None, words=None, go=None):
        self.calls.append((circle, key, state))
        if state is None:
            self.parts.pop((circle, key), None)
        else:
            self.parts[(circle, key)] = (state, words, go)


def _window(entries):
    return SimpleNamespace(needs_you=SimpleNamespace(shown_entries=lambda: tuple(entries)), phase=_Strip())


def _first(actions=("first_cards", "not_now")):
    return service.Entry(key=service.FIRST_CARDS, kind=service.FIRST_CARDS, title="Make cards for your first 20 "
                         "episodes?", lines=(), actions=actions, unseen=False)


def test_the_miner_circle_is_amber_while_the_first_cards_line_stands_and_its_press_opens_it():
    win = _window([_first()])
    shell.ShellWindow._first_cards_circle(win)
    state, words, go = win.phase.parts[(phase.MINER, "first-cards")]
    assert (state, words) == ("needs", strings.PHASE_FIRST_CARDS) and go == shell.FIRST_CARDS_GO
    got = phase.read((), extra={phase.MINER: [(state, words, go)]})[phase.MINER]
    assert got.go == go and got.go.at == (service.FIRST_CARDS,), "a press opens Needs you at that card"


def test_after_not_now_the_circle_stays_amber_and_after_the_yes_it_goes():
    win = _window([_first(actions=("first_cards",))])          # *Not now* pressed: *Make cards* alone
    shell.ShellWindow._first_cards_circle(win)
    assert (phase.MINER, "first-cards") in win.phase.parts
    win.needs_you.shown_entries = lambda: ()                   # the yes: the card goes
    shell.ShellWindow._first_cards_circle(win)
    assert (phase.MINER, "first-cards") not in win.phase.parts


def test_no_first_cards_line_lights_nothing():
    # why: a page with other cards (a gone folder) never makes 鉱 amber for this
    other = service.Entry(key="folder:x", kind="folder-gone", title="x", lines=(), actions=(), unseen=False)
    win = _window([other])
    shell.ShellWindow._first_cards_circle(win)
    assert win.phase.parts == {}
