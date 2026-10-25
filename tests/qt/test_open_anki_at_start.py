"""*Open Anki for me* in 3.0 (✅ Q4-16, K102; P2.3-1 a: "opens Anki only when the window opens"; BRIEF: "Anki is never
opened for you after mining"): the window's start is a session's start. With the setting on and Connect on, a closed
Anki is started once — through `anki_session.at_window`, the one path that may open it — and the session's sync asked
once it answers; then the known-words sync (forced once your phone's reviews are in) and Connect kicked. Never at a
focus, a language switch, a second start, or with the setting or Connect off. Alpha 3's finding: 3.0 never called
the window-start look, so the setting did nothing.

What a wrong answer would cost a learner: the morning case broken (Surasura opens without your phone's reviews, so it
orders cards you already studied), or Anki popping up on its own after every focus or after mining — the moment Sonic
asked never to have it opened for him.

Anki is a stand-in: `anki_session.look` answers from its state, `open_anki.start` records its call and starts nothing,
`anki_session.begin` answers as AnkiWeb would; nothing launches Anki or talks to a port.
"""
import pytest

from app.connect import anki_session, kick, open_anki
from app.qt import shell
from app.services.jobs import JobRegistry
from app.services.status import StatusService
from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader

URL = "http://127.0.0.1:8765"
ON = {"connect_enabled": True, "connect_open_anki": True, "anki_connect_url": URL, "target_language": "ja"}


class _Settings:
    def __init__(self, values):
        self.values = dict(values)

    def get(self):
        return self.values


class _Anki:
    """Anki as the session sees it: closed until something starts it, then open after one look."""

    def __init__(self, state="closed", answers=True):
        self.state, self.answers = state, answers
        self.starts, self.looks, self.begins, self.kicks = [], 0, [], []

    def look(self, url):
        self.looks += 1
        return self.state

    def start(self, profile=None):
        self.starts.append(profile)
        if self.answers:
            self.state = "open"
        return "a process"


@pytest.fixture
def anki(monkeypatch):
    """The stand-in Anki, with Anki allowed for this test (the suites switch it off) and the session's two-minute wait
    run without sleeping."""
    a = _Anki()
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_session, "look", a.look)
    monkeypatch.setattr(anki_session, "OPENING_EVERY_S", 0)
    monkeypatch.setattr(anki_session, "begin", lambda url, settings, wait=None: a.begins.append(url) or "synced")
    monkeypatch.setattr(open_anki, "start", a.start)
    monkeypatch.setattr(open_anki, "running", lambda: a.state == "open")
    monkeypatch.setattr(kick, "kick", lambda settings, videos=False: a.kicks.append(dict(settings)))
    return a


def _services(settings, log=None):
    log = log if log is not None else []
    registry = JobRegistry()
    services = shell.Services(settings=_Settings(settings), registry=registry,
                              status=StatusService(registry, reader=QuietReader()), controller=FakeController(log),
                              updates=FakeUpdates(log), automation=FakeAutomation(log), chores=FakeChores(log))
    said = []
    services.say = said.append
    return services, said, log


def _settled(services):
    thread = services.anki_session_thread
    if thread is not None:
        thread.join(10)
        assert not thread.is_alive(), "the session's look never ended"


def test_open_anki_for_me_opens_a_closed_anki_at_the_windows_start_then_syncs_and_reads_your_progress(qapp, anki):
    """The morning case: Anki closed, the window opens — Anki is started for you, the session's sync goes once it
    answers, then the known-words sync is asked (forced: your phone's reviews are in) and Connect kicked."""
    services, said, log = _services(ON)
    assert services.start()
    _settled(services)
    assert len(anki.starts) == 1, "Anki is started once"
    assert anki.begins == [URL], "the session's sync once Anki answers"
    began = services.automation.called("automation.session_began")
    assert began == [("automation.session_began", True)], "the known-words sync forced: your phone's reviews are in"
    assert len(anki.kicks) == 1, "Connect kicked to see what waits"
    assert said[0] == "Opening Anki for you (Open Anki for me)…"
    assert said[-1] == "Anki is open and synced: your phone's reviews are in."
    services.shutdown(0.05)


def test_open_anki_for_me_never_opens_anki_twice_in_a_session(qapp, anki):
    """One window, one session: a second start, every focus and a language switch never start Anki again — even with
    Anki closed again since (you closed it: that is your choice until the next window)."""
    services, _said, _log = _services(ON)
    services.start()
    _settled(services)
    anki.state = "closed"
    assert services.start() is False
    for _ in range(3):
        services.activated()
    services.language_changed("zh")
    _settled(services)
    assert len(anki.starts) == 1
    services.shutdown(0.05)


@pytest.mark.parametrize("settings", [dict(ON, connect_open_anki=False), {k: v for k, v in ON.items()
                                                                           if k != "connect_open_anki"}],
                         ids=["off", "never-set"])
def test_with_open_anki_for_me_off_anki_is_never_opened_nor_looked_at(qapp, anki, settings):
    """Off (its default): the window's start opens nothing and asks Anki nothing for it."""
    services, said, log = _services(settings)
    services.start()
    _settled(services)
    services.activated()
    assert anki.starts == [] and anki.looks == 0 and anki.begins == [] and anki.kicks == []
    assert said == [] and "automation.session_began" not in log
    services.shutdown(0.05)


@pytest.mark.parametrize("settings", [dict(ON, connect_enabled=False), dict(ON, logic={"automation": False})],
                         ids=["connect-off", "automation-off"])
def test_with_connect_off_open_anki_for_me_opens_nothing(qapp, anki, settings):
    """The setting is Connect's: with Connect's switch or D29's automation off, nothing needs Anki, so nothing opens."""
    services, said, _log = _services(settings)
    services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [] and anki.kicks == [] and said == []
    services.shutdown(0.05)


def test_an_anki_already_open_is_never_started_again_and_its_session_syncs(qapp, anki):
    """Anki already open at the window's start: nothing started, the session's sync asked (your phone's reviews), no
    "Opening Anki" line."""
    anki.state = "open"
    services, said, log = _services(ON)
    services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [URL]
    assert services.automation.called("automation.session_began") == [("automation.session_began", True)]
    assert "Opening Anki for you (Open Anki for me)…" not in said
    services.shutdown(0.05)


def test_an_anki_that_never_answers_is_left_and_the_bar_says_so(qapp, anki, monkeypatch):
    """Started, but no answer within the session's wait: no sync, no kick, and the bar says to open it yourself."""
    anki.answers = False
    monkeypatch.setattr(anki_session, "OPENING_WAIT_S", 0.05)
    services, said, log = _services(ON)
    services.start()
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [] and anki.kicks == []
    assert "automation.session_began" not in log
    assert said[-1] == "Anki didn't open within two minutes. Open it yourself when you're ready."
    services.shutdown(0.05)


def test_a_quit_under_way_starts_no_session(qapp, anki):
    """The window closing before its duties started: no look at Anki, nothing opened."""
    services, _said, _log = _services(ON)
    services.closing.set()
    assert services.start() is False                # a quit already under way starts no duty, no session
    assert services.anki_session_thread is None and anki.starts == []


def test_a_quit_begun_before_the_looks_thread_runs_opens_nothing(qapp, anki):
    """The duties started, then the window closed before the look's own thread ran: it looks at nothing and opens
    nothing for a window that's gone."""
    services, said, _log = _services(ON)
    services.closing.set()
    services._session(dict(ON))
    assert anki.looks == 0 and anki.starts == [] and said == []
