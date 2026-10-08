"""The 2.x window's session start for Connect (P2.3 row 2.3.6; ✅ Q4-4, Q4-16): `MasterDashboardApp._connect_session`
looks at Anki on a worker at the window's start and on focus (at most once a minute), hands the decision to
`anki_session.at_window` (3.0's window calls the same), and says in the bottom bar only what the user needs to know.
Only the window's first look may open Anki (*Open Anki for me*); off, nothing of Connect's is imported.

The window is a stand-in (its queue, bar and timers recorded); `at_window` is a stand-in too — its own rules are
tests/connect/test_anki_session.py's.
"""
import sys
import types

import pytest

from app import main


class Window(types.SimpleNamespace):
    """What `_connect_session` touches on the dashboard."""

    def __init__(self, **settings):
        super().__init__(_current_settings=dict({"connect_enabled": True}, **settings), _connect_looked=float("-inf"),
                         _connect_looking=False, _connect_opened=False, lines=[], synced_known=[],
                         CONNECT_LOOK_EVERY=main.MasterDashboardApp.CONNECT_LOOK_EVERY)
        self.gui_queue = types.SimpleNamespace(put=lambda job: job())
        self.status_var = types.SimpleNamespace(set=self.lines.append)
        self._maybe_anki_sync = lambda force=False: self.synced_known.append(force)

    def look(self, opening=False):
        main.MasterDashboardApp._connect_session(self, opening=opening)


class Now:
    """A worker that runs at once, so the test sees its end."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def looks(monkeypatch):
    """`at_window`'s calls, and what it answers next."""
    from app.connect import anki_session, kick
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(main.threading, "Thread", Now)
    monkeypatch.setattr(main.settings_manager, "load_settings", lambda: None)
    record = types.SimpleNamespace(calls=[], answer={"anki": "open", "opened": False, "sync": None}, kicks=[])

    def at_window(settings, opening=False, say=None):
        record.calls.append(opening)
        if record.answer.get("opened") and say:
            say("Opening Anki for you (Open Anki for me)…")
        return record.answer
    monkeypatch.setattr(anki_session, "at_window", at_window)
    monkeypatch.setattr(kick, "kick", lambda settings: record.kicks.append(settings.get("connect_enabled")))
    return record


def test_with_connect_off_nothing_of_it_is_imported(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    Window(connect_enabled=False).look(opening=True)
    assert not [m for m in sys.modules if m.startswith("app.connect")]


def test_with_anki_switched_off_for_the_run_nothing_looks(looks, monkeypatch):
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    Window().look(opening=True)
    assert looks.calls == []


def test_a_focus_before_the_windows_first_look_never_takes_its_place(looks):
    window = Window(connect_open_anki=True)
    window.look()                                   # FocusIn fires as the window appears
    assert looks.calls == []
    window.look(opening=True)
    assert looks.calls == [True], "the first look is the one that may open Anki"


def test_focus_looks_come_at_most_once_a_minute_and_never_open_anki(looks, monkeypatch):
    window = Window(connect_open_anki=True)
    window.look(opening=True)
    window._connect_looked -= window.CONNECT_LOOK_EVERY + 1
    window.look()
    window.look()
    assert looks.calls == [True, False]


def test_a_session_synced_reads_your_known_words_and_kicks_connect(looks):
    looks.answer = {"anki": "open", "opened": False, "sync": "synced"}
    window = Window()
    window.look(opening=True)
    assert window.synced_known == [True] and looks.kicks == [True] and window.lines == []


def test_anki_opened_for_you_is_said_then_its_sync(looks):
    looks.answer = {"anki": "open", "opened": True, "sync": "synced"}
    window = Window(connect_open_anki=True)
    window.look(opening=True)
    assert window.lines == ["Opening Anki for you (Open Anki for me)…",
                            "Anki is open and synced: your phone's reviews are in."]


@pytest.mark.parametrize("answer, line", [
    ({"anki": "open", "opened": False, "sync": "not-signed-in"}, "Anki isn't signed in to AnkiWeb"),
    ({"anki": "open", "opened": False, "sync": "full-sync"}, "AnkiWeb wants a full sync"),
    ({"anki": "open", "opened": False, "sync": "failed: AnkiWeb could not be reached"}, "couldn't sync"),
    ({"anki": "closed", "opened": True, "sync": None}, "Anki didn't open within two minutes"),
])
def test_what_needs_saying_is_said_once_in_the_bar(looks, answer, line):
    looks.answer = answer
    window = Window(connect_open_anki=True)
    window.look(opening=True)
    assert any(line in said for said in window.lines), window.lines
    assert window.synced_known == [] and looks.kicks == []


def test_nothing_to_say_says_nothing(looks):
    for answer in ({"anki": "open", "opened": False, "sync": None}, {"anki": "closed", "opened": False, "sync": None},
                   {"anki": "busy", "opened": False, "sync": None}):
        looks.answer = answer
        window = Window()
        window.look(opening=True)
        assert window.lines == [] and window.synced_known == []


def test_a_look_that_fails_never_takes_the_window_down_and_the_next_one_runs(looks, monkeypatch):
    from app.connect import anki_session

    def broken(settings, opening=False, say=None):
        raise RuntimeError("Anki answered in a shape nobody expected")
    monkeypatch.setattr(anki_session, "at_window", broken)
    window = Window()
    window.look(opening=True)
    assert window._connect_looking is False and window.lines == []
