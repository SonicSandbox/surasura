"""The re-order host's guards against its own races (`app/services/replan_host.py`): each test plants the moment two
threads cross — an opener still starting the helper while the window lets it go, a write being recorded while the host
goes, a late word from a host already let go, a language switch with a call still queued, the quit and a switch at
once.

What a wrong answer would cost a learner: a helper process left running (an update then waits on it), a write to the
deck of the language they just left, a `replan` job that never ends (the bar says *Re-ordering* forever and the quit
waits for it), or a quit that stops the write it was meant to wait for. The host is a stand-in recording each call.
"""
import os
import threading
import time

import pytest

from app import replan_preview
from app.services import replan_host as R
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h

SETTINGS = {"target_language": "ja", "journey_settle_s": 0, "enable_junban": True, "junban_deck": "日本語::Mining",
            "junban_replan_language": "ja", "junban_replan_deck": "日本語::Mining"}


@pytest.fixture
def gate(monkeypatch):
    """The gate says yes (the predicate itself is replan_preview's, tested there); no update holds its lock."""
    monkeypatch.setattr(replan_preview, "automation_on", lambda settings, language: True)
    monkeypatch.setattr(replan_preview, "_update_staged", lambda: False)


class _Host:
    def __init__(self, language, say, working, generate):
        self.language, self.say, self.working, self.generate = language, say, working, generate
        self.calls = []

    def poke(self): self.calls.append("poke")
    def catch_up(self): self.calls.append("catch_up")
    def after_generate(self): self.calls.append("after_generate")
    def close(self): self.calls.append("close")
    def stop(self): self.calls.append("stop")
    def busy(self): return False


class _Opener:
    """`open_host`'s shape; with `blocking`, each call waits for `go` after saying `opening` (the helper starting)."""

    def __init__(self, blocking=False):
        self.hosts = []
        self.blocking = blocking
        self.opening = threading.Event()
        self.go = threading.Event()

    def __call__(self, language, say=None, working=None, generate=None):
        host = _Host(language, say, working, generate)
        self.hosts.append(host)
        if self.blocking:
            self.opening.set()
            assert self.go.wait(5)
        return host


class _SlowRegistry(JobRegistry):
    """The registry, its `record` held until `go` (the window's listeners are told inside it): the moment a write is
    being recorded."""

    def __init__(self):
        super().__init__()
        self.recording = threading.Event()
        self.go = threading.Event()

    def record(self, *args, **kwargs):
        self.recording.set()
        assert self.go.wait(5)
        return super().record(*args, **kwargs)


def _host(opener, registry=None):
    return R.ReplanHost(registry or JobRegistry(), lambda: dict(SETTINGS), "ja", generate=lambda reason: None,
                        opener=opener)


def _quiet(host):
    assert host.worker.idle(5)


def test_a_switch_that_cannot_be_read_opens_no_host(monkeypatch):
    """An answer that can't be had is no: a gate that fails never opens the helper (never a write on a guess)."""
    def broken(settings, language):
        raise OSError("settings.json is being written")
    monkeypatch.setattr(replan_preview, "automation_on", broken)
    monkeypatch.setattr(replan_preview, "_update_staged", lambda: False)
    opener = _Opener()
    host = _host(opener)
    host.poke()
    host.catch_up()
    _quiet(host)
    assert opener.hosts == [] and host.opened == 0
    host.stop()


def test_nothing_reaches_the_host_once_the_quit_began(gate):
    """After `close()` (the quit), a poke or a catch-up still arriving neither reaches the open host (its close is the
    last it hears before `stop`) nor, with none open, starts a helper at the quit."""
    opener = _Opener()
    host = _host(opener)
    host.catch_up()
    _quiet(host)
    host.close()
    host.poke()
    host.after_generate()
    _quiet(host)
    assert opener.hosts[0].calls == ["catch_up", "close"]
    host.stop()

    none_open = _Opener()
    quitting = _host(none_open)
    quitting.close()
    quitting.poke()
    _quiet(quitting)
    assert none_open.hosts == [], "a helper started while the window was quitting"
    quitting.stop()


def test_a_helper_still_starting_when_the_update_holds_is_stopped_as_it_arrives(gate):
    """The update holds the children (*Update now*) while the helper is still starting: it is stopped the moment it is
    there — never kept, never left running for the update to wait on — and the hold's end opens a fresh one."""
    opener = _Opener(blocking=True)
    host = _host(opener)
    host.catch_up()
    assert opener.opening.wait(5)
    host.hold()
    opener.go.set()
    _quiet(host)
    assert opener.hosts[0].calls == ["stop"], "the helper that arrived during the hold was left running"
    assert host.opened == 0
    host.release()
    _quiet(host)
    assert len(opener.hosts) == 2 and opener.hosts[1].calls == ["catch_up"]
    host.stop()


def test_a_host_let_go_while_its_write_is_being_recorded_leaves_no_job_running(gate):
    """The host says it writes (`working(True)`) and, while the registry records that job, the update holds the
    children: the hold returns cleanly, and the job recorded for the host already gone is ended at once — never a
    `replan` job left running (the bar would say *Re-ordering* forever and the quit would wait for it)."""
    registry = _SlowRegistry()
    opener = _Opener()
    host = _host(opener, registry)
    host.catch_up()
    _quiet(host)
    said = threading.Thread(target=opener.hosts[0].working, args=(True,), name="host-says-working")
    said.start()
    assert registry.recording.wait(5)
    host.hold()                                          # raises nothing while the record is in hand
    registry.go.set()
    said.join(5)
    assert not said.is_alive()
    assert registry.live("replan") == ()
    assert [v.state for v in registry.snapshot() if v.kind == "replan"] == ["done"]
    host.stop()


def test_a_late_word_from_a_host_let_go_never_ends_the_new_hosts_write(gate):
    """Host A is let go (an update's hold that ended) and host B opens and writes; A's late *my write ended* must not
    end B's job — the quit waits for B's write, and the bar keeps saying it."""
    registry = JobRegistry()
    opener = _Opener()
    host = _host(opener, registry)
    host.catch_up()
    _quiet(host)
    a = opener.hosts[0]
    host.hold()
    host.release()
    _quiet(host)
    b = opener.hosts[1]
    b.working(True)
    a.working(True)
    a.working(False)
    live = registry.live("replan")
    assert len(live) == 1, "the old host's word ended the new host's write"
    assert [v.kind for v in registry.snapshot()] == ["replan"], "the old host's word recorded a job"
    b.working(False)
    assert registry.live("replan") == ()
    host.stop()


def test_a_call_still_queued_when_the_host_stops_opens_nothing(gate):
    """A language switch stops the old host while a poke for it is still queued behind a helper starting: the queued
    poke opens no new helper for the language just left (nothing more is written to its deck), and the stopped host's
    worker takes no more calls and ends its thread."""
    opener = _Opener(blocking=True)
    host = _host(opener)
    host.catch_up()
    assert opener.opening.wait(5)
    host.poke()                                          # queued behind the helper starting
    host.stop()
    opener.go.set()
    assert h.until(lambda: not host.worker._thread.is_alive(), seconds=5), "the stopped host's worker never ended"
    assert len(opener.hosts) == 1 and opener.hosts[0].calls == ["stop"]
    assert host.worker.put(host.poke) is False
    assert len(opener.hosts) == 1


def test_a_language_switch_after_the_quit_began_changes_nothing(gate, monkeypatch):
    """The quit began (`closing`), then a language switch arrives: the host whose write the quit waits for is not
    stopped early and no new language's host or keeper is made."""
    opener = _Opener()
    registry = JobRegistry()
    made = []
    real = R.ReplanHost

    class Counting(real):
        def __init__(self, *args, **kwargs):
            made.append(args[2])
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(R, "ReplanHost", Counting)

    class _Settings:
        def get(self):
            return dict(SETTINGS)

        def automation(self):
            return True
    replan = R.Replan(registry, GenerateController(registry, settle=0), _Settings(), "ja", opener=opener,
                      pending=lambda language: False,
                      keeper_options={"pending": lambda: False, "battery": lambda: False,
                                      "plan_path": os.path.join(h.root(), "no-plan.json.gz")})
    replan.activated()
    _quiet(replan.host)
    replan.closing()
    replan.language_changed("zh")
    _quiet(replan.host)
    assert replan.language == "ja" and made == ["ja"]
    assert opener.hosts[0].calls == ["catch_up", "close"], "the switch stopped the host the quit waits for"
    replan.finish(time.monotonic() + 1)
    assert opener.hosts[0].calls[-1] == "stop"


def test_the_quit_landing_while_a_switch_makes_the_new_host_keeps_it_from_ever_opening(gate):
    """A language switch is making the new language's keeper and host when the quit begins: the new pair is closed at
    once — no helper is started for the new language during the quit, and the quit finishes the pair it closed."""
    opener = _Opener()
    registry = JobRegistry()

    class _Settings:
        def get(self):
            return dict(SETTINGS)

        def automation(self):
            return True
    replan = R.Replan(registry, GenerateController(registry, settle=0), _Settings(), "ja", opener=opener,
                      pending=lambda language: False,
                      keeper_options={"pending": lambda: False, "battery": lambda: False,
                                      "plan_path": os.path.join(h.root(), "no-plan.json.gz")})
    first = replan.host
    make = replan._make

    def make_while_the_quit_lands(language):
        pair = make(language)
        replan.closing()                                 # the quit, between the switch's two looks
        return pair
    replan._make = make_while_the_quit_lands
    replan.language_changed("zh")
    assert replan.host is first
    time.sleep(0.3)                                      # the new host's worker would have opened it by now
    assert opener.hosts == [], "a helper started for the new language while the window quits"
    replan.finish(time.monotonic() + 1)
    assert opener.hosts == []
