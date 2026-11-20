"""Kantan-G (Sonic 2026-11-19: "a pause stops all a circle runs by itself"): Anki's circle paused — kept across a
restart — holds the window's own look at Anki: at the window's start no Anki opened (*Open Anki for me*) and no
AnkiWeb session sync, none at a focus either; Connect is still kicked at the start (its own Anki steps read the pause).
The resume runs the start's look it held, once — Anki opened for you then, the session's sync, the start's one
known-words sync after it. Also the circles' hover words and Connect's waits say the one shared line.

What a wrong answer would cost: the learner pauses Anki's circle to keep Anki closed (or AnkiWeb quiet) and the next
start opens Anki and syncs anyway; or, resumed, the morning sync never comes.

Anki is a stand-in (`test_open_anki_at_start`'s): nothing launches Anki or talks to a port.
"""
import pytest

from app.connect import runner
from app.qt import strings
from app.services import phase as P
from tests.qt.test_open_anki_at_start import BEGAN, ON, URL, _services, _settled, _until, anki  # noqa: F401


class _Saved:
    """The settings service, as `resumed` uses it: its write landed at once."""

    def __init__(self, values):
        self.values = dict(values)

    def get(self):
        return self.values

    def set(self, changes):
        self.values.update(changes)

    def flush(self, _timeout=None):
        return True


def _paused_services(values):
    services, said, log = _services(values)
    services.settings = _Saved(values)
    return services, said, log


def test_anki_paused_at_the_start_opens_no_anki_and_syncs_nothing_but_still_kicks_connect(qapp, anki):
    services, _said, _log = _paused_services(dict(ON, paused=["anki"]))
    assert services.start()
    assert _until(lambda: len(anki.kicks) == 1), "Connect kicked at the start all the same (Haya-CL)"
    assert services.anki_session_thread is None, "no look at Anki"
    assert anki.starts == [] and anki.begins == [] and anki.looks == 0
    assert _began(services) == [], "the start's known-words sync waits for the look"


def test_anki_paused_a_focus_never_looks_at_anki(qapp, anki):
    services, _said, _log = _paused_services(dict(ON, paused=["anki"]))
    assert services.start()
    _until(lambda: len(anki.kicks) == 1)
    services._session_looked = float("-inf")
    services.activated()
    assert _until(lambda: not services._session_running)
    assert anki.looks == 0 and anki.begins == []


def test_the_resume_runs_the_start_look_it_held_once_then_the_known_words_sync(qapp, anki):
    services, _said, _log = _paused_services(dict(ON, paused=["anki"]))
    assert services.start()
    _until(lambda: len(anki.kicks) == 1)
    services.set_paused(frozenset())
    services.resumed(frozenset({P.ANKI}))
    _settled(services)
    assert len(anki.starts) == 1, "Open Anki for me: the look the pause held, now"
    assert anki.begins == [URL]
    assert _began(services) == [(BEGAN, True)], "the start's one forced known-words sync, after the session's"
    services.resumed(frozenset({P.ANKI}))
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [URL], "once: a second resume is a focus's look at most"


def test_another_circles_pause_leaves_the_start_look(qapp, anki):
    services, _said, _log = _paused_services(dict(ON, paused=["junban", "surasura"]))
    assert services.start()
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [URL]


@pytest.mark.parametrize("circle", [P.MINER, P.SURASURA, P.JUNBAN, P.ANKI])
def test_a_resume_of_a_circle_that_holds_a_step_of_connects_kicks_connect(qapp, anki, circle):
    services, _said, _log = _paused_services(dict(ON, paused=[circle]))
    services.started = True
    services.paused = frozenset()
    services.resumed(frozenset({circle}))
    _settled(services)
    assert len(anki.kicks) >= 1, "its waiting episodes go on from their step"


def test_a_resume_of_new_arrivals_alone_never_kicks_connect_by_itself(qapp, anki, monkeypatch):
    from app.connect import rules
    placed = []
    monkeypatch.setattr(rules, "place_held", lambda settings: placed.append(settings) or {})
    services, _said, _log = _paused_services(dict(ON, paused=["arrivals"]))
    services.started = True
    services.paused = frozenset()
    services.resumed(frozenset({P.ARRIVALS}))
    _settled(services)
    assert len(placed) == 1, "hato's waiting drops placed by their rule"
    assert anki.kicks == [], "(place_held kicks Connect itself when its placements gave it work)"


def _began(services):
    return services.automation.called(BEGAN)


# --- the words ---------------------------------------------------------------------------------------------------- #
def test_connects_waits_say_the_windows_one_shared_line_with_the_circles_mark():
    assert runner.PAUSED_WAITS == strings.PAUSED_WAITS
    assert runner.GENERATE_PAUSED.endswith(strings.PAUSED_WAITS.format(what="", circle=strings.PAUSED_CIRCLE[P.SURASURA])
                                           .lstrip())
    assert runner.JUNBAN_PAUSED.endswith(strings.PAUSED_WAITS.format(what="", circle=strings.PAUSED_CIRCLE[P.JUNBAN])
                                         .lstrip())


def test_each_hover_names_connects_steps_its_pause_now_holds():
    assert "Connect" in strings.PHASE_HOLDS[P.SURASURA] and "Generate" in strings.PHASE_HOLDS[P.SURASURA]
    assert "Connect" in strings.PHASE_HOLDS[P.JUNBAN] and "Backfill" in strings.PHASE_HOLDS[P.JUNBAN]
    anki_words = strings.PHASE_HOLDS[P.ANKI]
    assert "AnkiWeb" in anki_words and "Open Anki for me" in anki_words and "Connect" in anki_words
    assert "hato's new files" in strings.PHASE_HOLDS[P.ARRIVALS]


def test_a_resume_while_another_look_is_under_way_keeps_the_held_look_for_the_next_focus(qapp, anki):
    """Review (Haiku state, confirmed): the held look was dropped when a look was still running at the resume."""
    services, _said, _log = _paused_services(dict(ON, paused=["anki"]))
    assert services.start()
    _until(lambda: len(anki.kicks) == 1)
    services._session_running = True                # a focus's look from before the pause, still under way
    services.set_paused(frozenset())
    services.resumed(frozenset({P.ANKI}))
    assert anki.starts == [] and services._look_after_pause, "kept"
    services._session_running = False
    services.activated()
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [URL]
    assert _began(services) == [(BEGAN, True)]


def test_anki_paused_while_the_setup_wizard_closes_holds_its_look_for_the_resume(qapp, anki):
    services, _said, _log = _paused_services(dict(ON, paused=["anki"]))
    services.setup_open.set()
    assert services.start()
    services.setup_ended()
    assert _until(lambda: len(anki.kicks) == 1)
    assert anki.starts == [] and anki.begins == [] and services._look_after_pause
    services.set_paused(frozenset())
    services.resumed(frozenset({P.ANKI}))
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [URL]
