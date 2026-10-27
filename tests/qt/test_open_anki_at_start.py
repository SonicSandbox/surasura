"""A session's start in 3.0 (✅ Q4-4: "sync once when a session starts (when Anki opens, or when Surasura starts with
Anki open)"; P2.3 row 2.3.6) and *Open Anki for me* (✅ Q4-16, K102; P2.3-1 a: "opens Anki only when the window opens";
BRIEF: "Anki is never opened for you after mining"). With Connect on, the window's start looks at Anki through
`anki_session.at_window` — the one path that may open it: Anki open, the session's sync; Anki closed, recorded, and
with *Open Anki for me* on started once, the session's sync asked once it answers. Then the one start known-words sync,
after the session's sync (IK-2), and, synced, Connect kicked on the settings as they are then (IK-5). A focus looks
again at most once a minute and never opens Anki. Never a second start's, a language switch's, or with Connect off.
Alpha 3's finding: 3.0 never called the window's look, so the setting did nothing.

What a wrong answer would cost a learner: the morning case broken (Surasura opens without your phone's reviews, so it
orders cards you already studied), or Anki popping up on its own after a focus or after mining — the moment Sonic asked
never to have it opened for him.

Anki is a stand-in: `anki_session.look` answers from its state, `open_anki.start` records its call and starts nothing,
`anki_session.begin` answers as AnkiWeb would; nothing launches Anki or talks to a port.
"""
import time

import pytest

from app.connect import anki_session, kick, open_anki
from app.qt import shell, strings
from app.services.jobs import JobRegistry
from app.services.status import StatusService
from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader

URL = "http://127.0.0.1:8765"
ON = {"connect_enabled": True, "connect_open_anki": True, "anki_connect_url": URL, "target_language": "ja"}
OFF = dict(ON, connect_open_anki=False)
OPENING = "Opening Anki for you (Open Anki for me)…"
BEGAN = "automation.session_began"


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
        self.on_look = None

    def look(self, url):
        self.looks += 1
        if self.on_look is not None:
            self.on_look()
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


def _until(test, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.01)
    return False


def _settled(services):
    """The start's look ended, and any focus's look after it."""
    thread = services.anki_session_thread
    if thread is not None:
        thread.join(10)
        assert not thread.is_alive(), "the session's look never ended"
    assert _until(lambda: not services._session_running), "a focus's look never ended"


def _began(services):
    return services.automation.called(BEGAN)


# --- *Open Anki for me* at the window's start -------------------------------------------------------------------- #
def test_open_anki_for_me_opens_a_closed_anki_at_the_windows_start_then_syncs_and_reads_your_progress(qapp, anki):
    """The morning case: Anki closed, the window opens — Anki is started for you, the session's sync goes once it
    answers, then the one start known-words sync (after it) and Connect kicked."""
    services, said, _log = _services(ON)
    assert services.start()
    _settled(services)
    assert len(anki.starts) == 1, "Anki is started once"
    assert anki.begins == [URL], "the session's sync once Anki answers"
    assert services.automation.called("automation.started") == [("automation.started", True)], \
        "the start's own sync waits for the session's look (IK-2)"
    assert _began(services) == [(BEGAN, True)], "then exactly one known-words sync, forced"
    assert len(anki.kicks) == 1, "Connect kicked to see what waits"
    assert said[0] == OPENING and said[-1] == "Anki is open and synced: your phone's reviews are in."
    services.shutdown(0.05)


def test_a_restart_now_start_never_opens_the_anki_you_closed_but_still_syncs_one_open(qapp, anki):
    """Alpha 4 M6: the window *Restart now* started (`relaunch`'s mark, `Services.restarted`) looks at Anki as any
    start does but never opens it — *Open Anki for me* is for a start you made; you may have closed Anki — and its
    setting is left as it is. An Anki already open still gets the session's sync."""
    services, said, _log = _services(ON)
    services.restarted = True
    services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [], "Anki closed: left closed"
    assert services.settings.get()["connect_open_anki"] is True, "the setting untouched"
    services.shutdown(0.05)
    anki.state = "open"
    services, said, _log = _services(ON)
    services.restarted = True
    services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [URL], "Anki open: its session's sync"
    services.shutdown(0.05)


def test_ik6_the_windows_start_look_is_a_job_while_it_runs_and_a_focus_look_is_none(qapp, anki, monkeypatch):
    """IK-6: the start look (it may open Anki and wait up to two minutes) is listed in the registry while it runs —
    the Anki circle and the bar show it — and ends with it; no Cancel, the quit never waits for it. A focus's quick
    look lists nothing (it would flicker each minute)."""
    monkeypatch.setattr(shell.Services, "SESSION_LOOK_EVERY", 0.0)
    services, _said, _log = _services(ON)
    live = []
    real = anki.state

    def look(settings, opening=False, **kw):
        live.append([(j.kind, j.label, j.on_quit) for j in services.registry.live(shell.SESSION_JOB)])
        return {"anki": real, "sync": None}
    services.anki_look = look
    services.start()
    _settled(services)
    assert live == [[(shell.SESSION_JOB, strings.SESSION_JOB_LABEL, "detach")]]
    assert services.registry.live(shell.SESSION_JOB) == ()
    ended = [j for j in services.registry.snapshot() if j.kind == shell.SESSION_JOB]
    assert len(ended) == 1 and ended[0].state == "done" and not ended[0].can_cancel
    services.activated()
    _settled(services)
    assert live[1:] == [[]], "a focus's look: no job"
    services.shutdown(0.05)


def test_b10_the_starts_look_waits_for_the_setup_wizard_then_runs_once(qapp, anki):
    """B-10 (AD-8): an upgrader whose 2.x had Connect and *Open Anki for me* on, the setup wizard up at the window's
    start: Anki is neither opened nor synced, nor Connect kicked, before the wizard closes — then the start's look runs
    exactly once (Anki opened, its sync, the one forced known-words sync)."""
    services, _said, _log = _services(ON)
    services.setup_open.set()
    assert services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [] and anki.kicks == [] and _began(services) == []
    services.setup_ended()
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [URL] and _began(services) == [(BEGAN, True)]
    services.setup_ended()                  # a second close (the wizard opened again): no second start look
    _settled(services)
    assert len(anki.starts) == 1
    services.shutdown(0.05)


def test_b10_connect_switched_off_in_the_wizard_looks_at_nothing_and_the_start_sync_still_goes(qapp, anki):
    settings = dict(ON)
    services, _said, _log = _services(settings)
    services.setup_open.set()
    services.start()
    services.settings.get()["connect_enabled"] = False
    services.setup_ended()
    _settled(services)
    assert anki.starts == [] and anki.begins == [] and _began(services) == [(BEGAN, True)]
    services.shutdown(0.05)


def test_open_anki_for_me_never_opens_anki_twice_in_a_session(qapp, anki, monkeypatch):
    """One window, one session: a second start, every focus (even one a minute on) and a language switch never start
    Anki again — even with Anki closed again since (you closed it: that is your choice until the next window)."""
    monkeypatch.setattr(shell.Services, "SESSION_LOOK_EVERY", 0.0)
    services, _said, _log = _services(ON)
    services.start()
    _settled(services)
    anki.state = "closed"
    assert services.start() is False
    for _ in range(3):
        services.activated()
        _settled(services)
    services.language_changed("zh")
    _settled(services)
    assert len(anki.starts) == 1 and anki.looks >= 3, "the focuses looked, and opened nothing"
    services.shutdown(0.05)


@pytest.mark.parametrize("settings", [OFF, {k: v for k, v in ON.items() if k != "connect_open_anki"}],
                         ids=["off", "never-set"])
def test_with_open_anki_for_me_off_a_closed_anki_is_never_opened(qapp, anki, settings):
    """Off (its default): the window's start looks (Connect on), finds Anki closed, and opens nothing; the start's
    known-words sync still goes once, and nothing is kicked."""
    services, said, _log = _services(settings)
    services.start()
    _settled(services)
    services.activated()
    _settled(services)
    assert anki.starts == [] and anki.begins == [] and anki.kicks == [] and said == []
    assert _began(services) == [(BEGAN, True)]
    services.shutdown(0.05)


def test_with_open_anki_for_me_off_an_anki_already_open_still_gets_the_sessions_sync(qapp, anki):
    """IK-1 (Q4-4 ✅: "or when Surasura starts with Anki open"): the session's sync isn't *Open Anki for me*'s — with it
    off and Anki open, the window's start still asks for it, then reads the known words and kicks Connect."""
    anki.state = "open"
    services, said, _log = _services(OFF)
    services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [URL] and len(anki.kicks) == 1
    assert _began(services) == [(BEGAN, True)] and OPENING not in said
    services.shutdown(0.05)


@pytest.mark.parametrize("settings", [dict(ON, connect_enabled=False), dict(ON, logic={"automation": False})],
                         ids=["connect-off", "automation-off"])
def test_with_connect_off_nothing_looks_at_anki_or_opens_it(qapp, anki, settings, monkeypatch):
    """The look and the setting are Connect's: with Connect's switch or D29's automation off, nothing looks at Anki at
    the start or a focus, nothing opens, and the start's known-words sync keeps its own 2 s timer."""
    monkeypatch.setattr(shell.Services, "SESSION_LOOK_EVERY", 0.0)
    services, said, _log = _services(settings)
    services.start()
    services.activated()
    _settled(services)
    assert anki.looks == 0 and anki.starts == [] and anki.begins == [] and anki.kicks == [] and said == []
    assert services.automation.called("automation.started") == [("automation.started",)] and _began(services) == []
    services.shutdown(0.05)


def test_an_anki_already_open_is_never_started_again_and_its_session_syncs(qapp, anki):
    """Anki already open at the window's start: nothing started, the session's sync asked (your phone's reviews), no
    "Opening Anki" line."""
    anki.state = "open"
    services, said, _log = _services(ON)
    services.start()
    _settled(services)
    assert anki.starts == [] and anki.begins == [URL]
    assert _began(services) == [(BEGAN, True)]
    assert OPENING not in said
    services.shutdown(0.05)


def test_an_anki_that_never_answers_is_left_and_the_bar_says_so(qapp, anki, monkeypatch):
    """Started, but no answer within the session's wait: no sync, no kick, the bar says to open it yourself — and the
    start's known-words sync still goes, once."""
    anki.answers = False
    monkeypatch.setattr(anki_session, "OPENING_WAIT_S", 0.05)
    services, said, _log = _services(ON)
    services.start()
    _settled(services)
    assert len(anki.starts) == 1 and anki.begins == [] and anki.kicks == []
    assert _began(services) == [(BEGAN, True)]
    assert said[-1] == "Anki didn't open within two minutes. Open it yourself when you're ready."
    services.shutdown(0.05)


def test_connect_switched_off_during_the_look_is_never_kicked(qapp, anki):
    """IK-5: the look may wait up to two minutes; Connect switched off meanwhile is read again before the kick, so a
    synced session kicks nothing."""
    services, _said, _log = _services(ON)

    def switched_off():
        if anki.starts:
            services.settings.values["connect_enabled"] = False
    anki.on_look = switched_off
    services.start()
    _settled(services)
    assert anki.begins == [URL] and anki.kicks == []
    services.shutdown(0.05)


# --- a focus: the session's look again, never Anki opened ------------------------------------------------------- #
def test_a_focus_looks_again_at_most_once_a_minute_and_never_opens_anki(qapp, anki, monkeypatch):
    """P2.3 row 2.3.6: a focus is a session's start seen again (Anki opened by you since: its sync), at most once every
    SESSION_LOOK_EVERY; it never opens Anki, setting on or not. Its known-words sync is forced only when the session's
    sync brought your phone's reviews in."""
    services, _said, _log = _services(ON)
    anki.answers = False
    monkeypatch.setattr(anki_session, "OPENING_WAIT_S", 0.05)
    services.start()
    _settled(services)
    looks = anki.looks
    services.activated()                                  # within the minute: no look
    _settled(services)
    assert anki.looks == looks
    monkeypatch.setattr(shell.Services, "SESSION_LOOK_EVERY", 0.0)
    anki.state = "open"                                   # you opened Anki yourself
    services.activated()
    _settled(services)
    assert len(anki.starts) == 1, "the start's one, never a focus's"
    assert anki.begins == [URL] and _began(services)[-1] == (BEGAN, True)
    anki.state = "closed"
    services.activated()
    _settled(services)
    assert len(anki.starts) == 1, "a closed Anki at a focus stays closed"
    services.shutdown(0.05)


# --- the quit ---------------------------------------------------------------------------------------------------- #
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
    services._session(dict(ON), True)
    assert anki.looks == 0 and anki.starts == [] and said == []


def test_a_quit_during_the_first_look_starts_no_anki(qapp, anki):
    """B-3: the window closed while its first look waited for Anki's answer: Anki is not started after it."""
    services, _said, _log = _services(ON)
    anki.on_look = services.closing.set
    services._session(dict(ON), True)
    assert anki.starts == [] and anki.begins == []


def test_a_quit_during_the_wait_for_anki_ends_the_wait_at_once(qapp, anki):
    """Anki started for you but not answering, and the window closes: the look stops waiting (no two minutes of a
    thread outliving its window), and nothing is synced, read or kicked after."""
    anki.answers = False
    services, _said, log = _services(ON)
    services.start()
    assert _until(lambda: anki.starts and anki.looks >= 2)
    services.closing.set()
    services.anki_session_thread.join(5)
    assert not services.anki_session_thread.is_alive(), "the wait outlived the window"
    assert anki.begins == [] and anki.kicks == [] and BEGAN not in log
    services.shutdown(0.05)


# why: one session look at a time; a second one asked while the first still waits on Anki starts no thread and asks
# Anki nothing more, even at the window's start, so one window never runs two looks at once.
def test_a_second_session_look_while_one_is_under_way_starts_nothing(qapp, anki):
    import threading
    release = threading.Event()
    anki.state = "open"
    anki.on_look = lambda: release.wait(5)
    services, _said, _log = _services(ON)
    first = services._look_at_anki(dict(ON), True)
    try:
        assert first is not None and _until(lambda: anki.looks == 1), "the first look never began"
        assert services._look_at_anki(dict(ON), True) is None, "a second look started while the first was under way"
        assert anki.looks == 1, "a second look asked Anki while the first was under way"
    finally:
        release.set()
        if first is not None:
            first.join(10)
        services.shutdown(0.05)
    assert not first.is_alive(), "the first look never ended"


def test_a_quit_ends_the_looks_wait_at_once_and_a_wait_without_one_still_waits(qapp, anki, monkeypatch):
    """The look waits on the window's closing event: with the window open a wait lasts its full length, and a quit ends
    it at once, well before the wait's own length, so the window's thread never outlives a closed window."""
    import threading
    from app.connect import anki_session
    waited = []

    def look_for(length):
        def look(settings, opening, say, sleep, clock, cancel):
            started = time.time()
            sleep(length)
            waited.append(time.time() - started)
        return look

    # why: a quit during a 5 s wait must end it well before its 5 s, after the 0.2 s quit: under 4 s leaves a loaded
    # machine room and still tells an ended wait from one that ran its length
    services, _said, _log = _services(ON)
    services.anki_look = look_for(5)
    threading.Timer(0.2, services.closing.set).start()
    services._session(dict(ON), True)
    assert waited and 0.1 <= waited[0] < 4.0, waited

    # why: with the window open nothing ends the wait early, so a 0.4 s wait takes at least about 0.4 s
    waited.clear()
    open_services, _said, _log = _services(ON)
    open_services.anki_look = look_for(0.4)
    open_services._session(dict(ON), True)
    assert waited and waited[0] >= 0.3, waited

    # why: the real look (`anki_session.at_window`) is the one the window runs, so the wiring is pinned on it: the
    # sleep it is handed is the window's closing event's wait, which is what makes a quit end its wait
    handed = []

    def spy_at_window(settings, opening, say, sleep, clock, cancel):
        handed.append(sleep)
        return None

    monkeypatch.setattr(anki_session, "at_window", spy_at_window)
    real_services, _said, _log = _services(ON)
    real_services._session(dict(ON), True)
    assert handed and handed[0] == real_services.closing.wait, handed


def test_a_focus_look_never_starts_while_the_window_starts_session_look_runs(qapp, anki):
    """A focus look is refused while the window start's session look still runs, even once the focus's own
    minute has passed (the time gate is switched off here, so only the running look can hold the focus back)."""
    gate = {"open": False}
    anki.on_look = lambda: _until(lambda: gate["open"], 60.0)   # the start's look waits on Anki's answer, held for the whole test (the finally releases it)
    services, _said, _log = _services(ON)
    services.SESSION_LOOK_EVERY = 0
    try:
        assert services.start()
        assert _until(lambda: anki.looks >= 1), "the window start's look never began"
        assert services._look_at_anki(dict(ON), False) is None
    finally:
        gate["open"] = True
        _settled(services)
        services.shutdown(0.05)
