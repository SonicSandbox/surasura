"""The update service (`app/services/updates.py`) — W3.5 row 1: the Tk dashboard's update flow, Qt-free.

What a wrong answer would cost:
  * an install half-replaced — the helper armed while a Content Manager, a command line or an Anki write still runs, or
    after the user pressed Cancel; or a staged download left behind for the next *Update now* to trip on;
  * a stuck app — the update lock or the held children never released after a cancel or a failure, so no Generate and
    no second update ever start again;
  * a loop — a version whose in-app update failed offered in place again on every start;
  * the user's settings rewritten — *Skip this version* saving the whole file instead of its one key;
  * a freeze or a box — a network call or a lock take on the window's thread, a dialog instead of the bar's state;
  * a test going online — the release check stays off under the test switch, and every test here feeds fakes.

Each test's docstring names the Tk method (`app/main.py`) whose rule it carries over. The updater's own functions
(S3.1's) are replaced only where they would download, launch or list the machine's processes.
"""
import os
import subprocess
import sys
import threading
import time

import pytest

from app import __version__
from app import anki_connect
from app import locks
from app import path_utils
from app import update_checker
from app import updater
from app.services import jobs as J
from app.services import updates as U
from app.services.jobs import JobRegistry
from app.services.settings import SettingsService, freeze
from app.update_checker import UpdateInfo
from tests import services_helpers as h

NEWER = "99.0"          # newer than this build, whatever __version__ says
NOTES = "https://github.com/SonicSandbox/surasura/releases/tag/v99.0"
FAST = 0.02             # the wait list's period in these tests (the app's is U.POLL)


def _app_release(version=NEWER, critical=False):
    return UpdateInfo(version=version, update_type="app", runtime_baseline="0.0", critical=critical,
                      sha256="a" * 64, app_package_url="https://example.invalid/app_package.zip", notes_url=NOTES)


def _installer_release():
    return UpdateInfo(version=NEWER, update_type="installer", sha256="b" * 64, notes_url=NOTES,
                      installer={"asset": "Surasura-setup.exe", "sha256": "c" * 64, "args": ["/SILENT"]},
                      installer_url="https://example.invalid/Surasura-setup.exe")


class FakeSettings:
    """The settings service's two calls the update uses: `get()` (frozen) and `set(changes)` (recorded)."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.calls = []

    def get(self):
        return freeze(self.values)

    def set(self, changes):
        self.calls.append(dict(changes))
        self.values.update(changes)


class Stage:
    """`prepare_update` / `prepare_installer` without the network: reports progress, waits for `gate`, then returns
    the staged marker (or raises `error`)."""

    def __init__(self, gate=True, error=None, marker=None):
        self.gate = threading.Event()
        if gate:
            self.gate.set()
        self.error = error
        self.marker = marker or {"target_version": NEWER, "targets": [], "from_version": __version__}
        self.calls = []
        self.finished = threading.Event()

    def __call__(self, info, progress_cb=None):
        self.calls.append(info.version)
        try:
            for done in (0, 4 * U._MB, 8 * U._MB):
                progress_cb(done, 16 * U._MB)
            assert self.gate.wait(20), "the test never opened the download's gate"
            progress_cb(16 * U._MB, 16 * U._MB)
            if self.error is not None:
                raise self.error
            return self.marker
        finally:
            self.finished.set()


class World:
    """Every updater / checker seam a test may steer, recorded in one call log."""

    def __init__(self, monkeypatch):
        self.log = []
        self.release = _app_release()
        self.children = []                       # what `running_children` lists now
        self.can_update = []                     # answers `can_update_now` gives first (then: nothing runs)
        self.library = []                        # answers `hold_library_locks` gives first (then: [])
        self.arm_error = None
        self.on_arm = None
        self.opened = []
        self.stage = Stage()
        self.installer = Stage(marker={"kind": "installer", "path": "setup.exe", "args": [],
                                       "target_version": NEWER, "from_version": __version__})
        self.quits = []
        self.sent = []
        m = monkeypatch
        m.setattr(update_checker, "get_update_info", lambda *a, **k: self._get())
        m.setattr(updater, "can_auto_apply", lambda info=None: True)
        m.setattr(updater, "prepare_update", lambda info, progress_cb=None: self.stage(info, progress_cb))
        m.setattr(updater, "prepare_installer", lambda info, progress_cb=None: self.installer(info, progress_cb))
        m.setattr(updater, "running_children", lambda active=(), images=None: self._children(active))
        m.setattr(updater, "can_update_now", lambda active=(), images=None: self._can_update(active))
        m.setattr(updater, "hold_library_locks", lambda languages=("ja", "zh"): self._hold())
        m.setattr(updater, "release_library_locks", lambda held: self.log.append(("release library", held)))
        m.setattr(updater, "arm_and_launch", self._arm)
        real_discard = updater.discard_staged
        m.setattr(updater, "discard_staged", lambda: (self.log.append("discard"), real_discard()))
        m.setattr(path_utils, "write_install_note", lambda frozen=None: self.log.append("install note"))
        from app import telemetry
        m.setattr(telemetry, "send_update_event", lambda from_version: self.sent.append(from_version))
        m.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
        self.services = []
        self.locks = []
        real_take = updater.take_update_lock
        m.setattr(updater, "take_update_lock", lambda *a, **k: self._took(real_take(*a, **k)))

    def _took(self, held):
        if held is not None:
            self.locks.append(held)
        return held

    def _get(self):
        self.log.append("check")
        if isinstance(self.release, Exception):
            raise self.release
        return self.release

    def _children(self, active):
        return [dict(c) for c in self.children] + [{"pid": p.pid, "name": p.surasura_desc, "stop": None}
                                                    for p in active]

    def _can_update(self, active):
        return self.can_update.pop(0) if self.can_update else not self._children(active)

    def _hold(self):
        self.log.append("hold library")
        return self.library.pop(0) if self.library else []

    def _arm(self, staged):
        self.log.append(("arm", staged.get("target_version"), staged.get("kind")))
        if self.on_arm is not None:
            self.on_arm()
        if self.arm_error is not None:
            raise self.arm_error

    def service(self, settings=None, busy=None, active=None, registry=None):
        svc = U.UpdateService(settings if settings is not None else FakeSettings(), registry or JobRegistry(),
                              on_quit=lambda: (self.log.append("quit"), self.quits.append(1)), busy=busy,
                              active=active, open_url=self.opened.append, poll=FAST)
        self.services.append(svc)
        return svc

    def offered(self, svc):
        """A service with the release on offer (its check run on this thread)."""
        assert svc.check(now=True)
        assert svc.state().state == U.AVAILABLE, svc.state()
        return svc


@pytest.fixture
def world(monkeypatch):
    w = World(monkeypatch)
    yield w
    for svc in w.services:                       # nothing of a test's update outlives its fakes
        svc.quit()
    w.stage.gate.set()
    w.installer.gate.set()
    assert h.until(lambda: all(svc._update is None or svc._update.handing for svc in w.services), seconds=20)
    for held in w.locks:                         # a test that handed over leaves its lock held, as the app exits
        if not held.closed:
            updater.drop_update_lock(held)
    updater.release_children(start=False)


def _lock_is_free():
    held = updater.take_update_lock()
    if held is None:
        return False
    updater.drop_update_lock(held)
    return True


def _states(svc):
    seen = []
    svc.subscribe(lambda s: seen.append(s))
    return seen


# --- the check ------------------------------------------------------------------------------------------------ #
def test_a_newer_in_app_release_is_offered_with_its_words(world):
    """check_updates_thread → _show_update_indicator: the release, its class and the dialog's words (_update_body)."""
    svc = world.offered(world.service())
    s = svc.state()
    assert (s.version, s.cls, s.notes_url, s.critical, s.open_now) == (NEWER, "APP", NOTES, False, False)
    assert s.body == U.body("APP", world.release) and "briefly close and reopen" in s.body


def test_effective_class_gets_the_same_inputs_as_the_tk_check(world, monkeypatch):
    """check_updates_thread: the skip, `auto_update_enabled`, `can_auto_apply(info)` and the failed version, all
    passed to `updater.effective_class` (one rule, never copied)."""
    seen = []
    real = updater.effective_class

    def spy(cls, info, **kwargs):
        seen.append((cls, info, kwargs))
        return real(cls, info, **kwargs)
    monkeypatch.setattr(updater, "effective_class", spy)
    monkeypatch.setattr(updater, "can_auto_apply", lambda info=None: info is world.release and "can-apply")
    monkeypatch.setattr(updater, "failed_version", lambda settings=None: "97.0")
    svc = world.service(FakeSettings({"skipped_version": "98.0", "auto_update_enabled": False}))
    svc.check(now=True)
    assert seen == [("APP", world.release, {"skipped_version": "98.0", "auto_enabled": False,
                                            "can_apply": "can-apply", "failed_version": "97.0"})]
    assert svc.state().cls == "FULL"                     # auto updates off: a manual download, still offered


def test_auto_update_off_offers_a_download_and_update_now_does_nothing(world):
    """check_updates_thread with `auto_update_enabled` False (the Tk default True when missing): FULL, the Download
    button's browser, and no in-app start."""
    svc = world.offered(world.service(FakeSettings({"auto_update_enabled": False})))
    assert svc.state().cls == "FULL" and "downloaded manually" in svc.state().body
    assert svc.start() is False
    svc.open_download()
    assert h.until(lambda: world.opened == [NOTES], seconds=5)
    default = world.offered(world.service(FakeSettings({})))
    assert default.state().cls == "APP"


@pytest.mark.parametrize("answer", [None, OSError("getaddrinfo failed")])
def test_offline_or_no_release_is_silent(world, answer):
    """check_updates_thread: offline, a timeout, no release — no state, no listener call, no failure entry (E18); the
    next check still runs."""
    world.release = answer
    svc = world.service()
    seen = _states(svc)
    assert svc.check(now=True)
    assert svc.state().state == U.NONE and seen == [] and svc.state().needs_you == ()
    world.release = _app_release()
    assert svc.check(now=True) and svc.state().state == U.AVAILABLE


def test_the_test_switch_keeps_the_check_off(world, monkeypatch):
    """__init__ / _offer_skipped_again: no check under SURASURA_NO_UPDATE_CHECK (a test must never go online)."""
    monkeypatch.setenv("SURASURA_NO_UPDATE_CHECK", "1")
    svc = world.service()
    assert svc.check() is False and svc.check(now=True) is False
    svc.offer_again()
    assert "check" not in world.log and svc.state().state == U.NONE


def test_begin_reconciles_then_checks_and_reads_both_switches(world, monkeypatch):
    """__init__'s `after(800, reconcile_update_result)` (off under SURASURA_NO_UI_TIMERS) and the start-up check (off
    under SURASURA_NO_UPDATE_CHECK): reconcile first, so a version that just failed is never offered in place."""
    order = []
    monkeypatch.setattr(updater, "consume_result", lambda: order.append("reconcile"))
    monkeypatch.setattr(update_checker, "get_update_info", lambda *a, **k: order.append("check") or world.release)
    monkeypatch.setenv("SURASURA_NO_UPDATE_CHECK", "1")       # conftest's SURASURA_NO_UI_TIMERS is on too
    svc = world.service()
    svc.begin()
    time.sleep(0.2)
    assert order == []
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK")
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    svc.begin()
    assert h.until(lambda: svc.state().state == U.AVAILABLE, seconds=10)
    assert order == ["reconcile", "check"]


def test_a_critical_release_opens_once(world):
    """_show_update_indicator: a critical release escalates once to the opened dialog; the user still chooses."""
    world.release = _app_release(critical=True)
    svc = world.service()
    svc.check(now=True)
    assert svc.state().critical and svc.state().open_now
    svc.check(now=True)
    assert svc.state().critical and not svc.state().open_now


def test_the_check_and_its_listeners_run_off_the_callers_thread(world, monkeypatch):
    """check_updates_thread is a worker: `check()` returns at once even when GitHub is slow, and the listener hears the
    state on the worker."""
    gate = threading.Event()
    monkeypatch.setattr(update_checker, "get_update_info", lambda *a, **k: gate.wait(10) and world.release)
    svc = world.service()
    threads = []
    svc.subscribe(lambda s: threads.append(threading.current_thread()))
    ok, ms = h.timed(svc.check)
    assert ok and ms <= 4, ms
    assert svc.check() is False                              # one check at a time
    gate.set()
    assert h.until(lambda: threads, seconds=10)
    assert threads[0] is not threading.main_thread()


# --- skip / offer again ----------------------------------------------------------------------------------------- #
def test_skip_writes_only_its_key_and_the_version_is_never_offered_again(world):
    """_skip_update: `skipped_version` alone, through the settings service (never the whole file); the offer goes, a
    check finds nothing; Settings' row names it while it is newer (_sync_skipped_row)."""
    h.write_settings({"target_language": "ja", "theme": "dark", "anki_connect_url": "http://127.0.0.1:9"})
    settings = SettingsService(delay=0.01)
    svc = world.offered(world.service(settings))
    assert svc.skip() is True
    assert svc.state().state == U.NONE
    assert settings.flush(10)
    assert h.read_settings() == {"target_language": "ja", "theme": "dark", "anki_connect_url": "http://127.0.0.1:9",
                                 "skipped_version": NEWER}
    svc.check(now=True)
    assert svc.state().state == U.NONE
    assert svc.skipped() == NEWER


def test_offer_again_forgets_the_skip_and_checks_again(world):
    """_offer_skipped_again: `skipped_version` written as '' alone, then checked: offered again in one click."""
    settings = FakeSettings({"skipped_version": NEWER, "theme": "dark"})
    svc = world.service(settings)
    svc.check(now=True)
    assert svc.state().state == U.NONE
    svc.offer_again()
    assert h.until(lambda: svc.state().state == U.AVAILABLE, seconds=10)
    assert settings.calls == [{"skipped_version": ""}] and svc.state().cls == "APP"


@pytest.mark.parametrize("skipped,shown", [(NEWER, NEWER), ("0.0.1", ""), ("", ""), (__version__, "")])
def test_the_skipped_row_shows_only_a_version_newer_than_this_one(world, skipped, shown):
    """_sync_skipped_row: after a manual update to it, or past it, there is nothing to bring back."""
    assert world.service(FakeSettings({"skipped_version": skipped})).skipped() == shown


def test_skip_from_a_failure_entry_and_never_during_an_update(world):
    """_skip_update, and the failure card's *Skip this version*: the version it names; refused while an update runs."""
    world.stage = Stage(gate=False)
    settings = FakeSettings()
    svc = world.offered(world.service(settings))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.DOWNLOADING, seconds=10)
    assert svc.skip() is False and settings.calls == []
    svc.cancel()
    world.stage.gate.set()
    assert svc.skip("98.5") is True
    assert settings.calls == [{"skipped_version": "98.5"}]
    assert svc.state().state == U.AVAILABLE                  # another version skipped: this offer stands


# --- Update now: the happy path --------------------------------------------------------------------------------- #
def test_update_now_downloads_waits_and_hands_over(world):
    """_do_auto_update → _start_update → _update_downloaded → _update_poll → _apply_and_restart: the lock, the held
    children, the download's progress, the wait for a running program, then library locks → install note → arm →
    quit, in that order; the registry lists it as `update`."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    seen = _states(svc)
    assert svc.start() is True
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    assert updater.children_held() and not _lock_is_free()
    assert svc.state().programs == (U.Program(4242, "Content Manager", True),)
    assert [j.kind for j in registry.live()] == ["update"]
    assert "Waiting for Content Manager" in registry.live()[0].progress.step
    progress = [(s.done, s.total) for s in seen if s.state == U.DOWNLOADING]
    assert progress[0] == (0, 0) and progress == sorted(progress)
    assert {(4 * U._MB, 16 * U._MB), (8 * U._MB, 16 * U._MB), (16 * U._MB, 16 * U._MB)} <= set(progress)
    assert world.quits == []
    world.children = []
    assert h.until(lambda: world.quits, seconds=10)
    tail = world.log[world.log.index("hold library"):]
    assert tail == ["hold library", "install note", ("arm", NEWER, None), "quit"]
    assert seen[-1].state == U.READY
    assert registry.snapshot()[-1].state == J.DONE and "discard" not in world.log


def test_the_installer_release_stages_its_installer(world, monkeypatch):
    """_do_installer_update: a frozen build stages the installer (`prepare_installer`) and hands it to `arm_and_launch`;
    a source checkout opens the release page instead."""
    world.release = _installer_release()
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    svc = world.offered(world.service())
    assert svc.state().cls == "INSTALLER" and "its own installer" in svc.state().body
    assert svc.start()
    assert h.until(lambda: world.opened == [NOTES], seconds=10)
    assert h.until(lambda: svc._update is None, seconds=10)
    assert world.installer.calls == [] and _lock_is_free() and not updater.children_held()
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    assert svc.start()
    assert h.until(lambda: world.quits, seconds=10)
    assert world.installer.calls == [NEWER] and world.stage.calls == []
    assert ("arm", NEWER, "installer") in world.log


def test_no_updater_exe_falls_back_to_the_release_page(world, monkeypatch):
    """_do_auto_update: `can_auto_apply` False at the click (no bundled updater.exe) → the browser; no lock, no hold."""
    svc = world.offered(world.service())
    monkeypatch.setattr(updater, "can_auto_apply", lambda info=None: False)
    taken = []
    monkeypatch.setattr(updater, "take_update_lock", lambda *a, **k: taken.append(1))
    assert svc.start()
    assert h.until(lambda: world.opened == [NOTES], seconds=10)
    assert h.until(lambda: svc._update is None, seconds=10)
    assert taken == [] and world.stage.calls == [] and svc.state().state == U.AVAILABLE


def test_start_returns_at_once_and_never_twice(world, monkeypatch):
    """_start_update: the lock take, the download and the listing on workers (the click returns within 4 ms); a second
    *Update now* while one runs does nothing; one registry job."""
    real = updater.take_update_lock
    monkeypatch.setattr(updater, "take_update_lock", lambda *a, **k: (time.sleep(0.3), real())[1])
    world.stage = Stage(gate=False)
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    ok, ms = h.timed(svc.start)
    assert ok and ms <= 4, ms
    assert svc.start() is False
    assert h.until(lambda: svc.state().state == U.DOWNLOADING, seconds=10)
    assert svc.start() is False
    assert len(registry.live("update")) == 1 and world.stage.calls == [NEWER]


def test_another_update_holding_the_lock_is_said_in_the_state(world):
    """_start_update: `take_update_lock` None (another install's update) → said, nothing held, offered again."""
    other = updater.take_update_lock()
    try:
        registry = JobRegistry()
        svc = world.offered(world.service(registry=registry))
        assert svc.start()
        assert h.until(lambda: svc.state().message == "Another Surasura update is already in progress.", seconds=10)
        assert svc.state().state == U.AVAILABLE and not updater.children_held() and world.stage.calls == []
        assert h.until(lambda: registry.live("update") == (), seconds=5)
    finally:
        updater.drop_update_lock(other)


# --- the wait ----------------------------------------------------------------------------------------------------- #
def test_the_anki_writer_lock_and_the_windows_own_work_keep_it_waiting(world):
    """_busy_threads: the window's sync and Junban's automatic reorder (from `busy()`), and the Anki writer lock held
    in this process — one entry for the automatic step, never listed twice; none of them can be stopped."""
    busy = ["Anki sync", U.JUNBAN_AUTO]
    token = object()
    held = locks.take(anki_connect.WRITER_LOCK, anki_connect.AUTOMATIC_STEP, owner=token)
    try:
        svc = world.offered(world.service(busy=lambda: list(busy)))
        assert svc.start()
        assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
        assert svc.state().programs == (U.Program("Anki sync", "Anki sync", False),
                                        U.Program(f"Writing to Anki ({anki_connect.AUTOMATIC_STEP})",
                                                  f"Writing to Anki ({anki_connect.AUTOMATIC_STEP})", False))
        assert svc.stop() is False                           # nothing here can be stopped
        busy.clear()
        assert h.until(lambda: len(svc.state().programs) == 1, seconds=10)
        time.sleep(0.15)
        assert world.quits == []                             # the writer lock alone still holds it
    finally:
        held.release()
    assert h.until(lambda: world.quits, seconds=10)


def test_junban_is_listed_when_the_writer_lock_is_someone_elses(world):
    """_busy_threads: Junban's own entry stands unless the lock is held for the automatic step."""
    held = locks.take(anki_connect.WRITER_LOCK, "Backfill", owner=object())
    try:
        svc = world.offered(world.service(busy=lambda: [U.JUNBAN_AUTO]))
        assert svc.start()
        assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
        assert [p.name for p in svc.state().programs] == [U.JUNBAN_AUTO, "Writing to Anki (Backfill)"]
        svc.cancel()
    finally:
        held.release()


def test_stop_it_stops_one_child_and_a_wait_only_row_is_only_waited_for(world):
    """_show_update_wait / _stop_update_children: *Stop it* calls that child's stop; an entry whose stop is None (the
    window's own work; Connect's row after the P3.1 take-in) is waited for, never stopped."""
    stopped = []
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: stopped.append(4242)},
                      {"pid": None, "name": "Connect: mining 12 words", "stop": None}]
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING and len(svc.state().programs) == 2, seconds=10)
    assert [p.can_stop for p in svc.state().programs] == [True, False]
    assert svc.stop("Connect: mining 12 words") is False
    assert svc.stop(4242) is True
    assert h.until(lambda: stopped == [4242], seconds=5)
    world.children = [world.children[1]]
    assert h.until(lambda: [p.name for p in svc.state().programs] == ["Connect: mining 12 words"], seconds=10)
    assert svc.stop() is False                               # Stop all: nothing left that can be stopped
    time.sleep(0.15)
    assert world.quits == []
    world.children = []
    assert h.until(lambda: world.quits, seconds=10)


def test_the_windows_own_children_are_listed_through_running_children(world):
    """_list_update_children: `running_children(active_processes)` gets the window's live children (`active()`)."""
    class Child:
        pid, surasura_desc = 5150, "Importing from Migaku"
    active = [Child()]
    svc = world.offered(world.service(active=lambda: list(active)))
    assert svc.start()
    assert h.until(lambda: svc.state().programs == (U.Program(5150, "Importing from Migaku", False),), seconds=10)
    active.clear()
    assert h.until(lambda: world.quits, seconds=10)


def test_something_started_at_the_last_moment_keeps_it_waiting(world):
    """_apply_and_restart: the last check (`can_update_now`) finds a program → nothing armed, the wait goes on."""
    world.can_update = [False, False]
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: world.quits, seconds=10)
    assert world.can_update == [] and world.log.count(("arm", NEWER, None)) == 1


def test_the_library_helper_holding_its_lock_keeps_it_waiting(world):
    """_apply_and_restart: `hold_library_locks` None (the store's helper runs) → said, nothing armed, tried again."""
    world.library = [None]
    svc = world.offered(world.service())
    seen = _states(svc)
    assert svc.start()
    assert h.until(lambda: world.quits, seconds=10)
    assert any(s.message == "Waiting for the library's upkeep to finish" for s in seen)
    assert world.log.count("hold library") == 2 and world.log.count(("arm", NEWER, None)) == 1


def test_the_wait_polls_at_the_tk_period():
    """_update_poll: `after(300, …)`."""
    assert U.POLL == 0.3


# --- cancel -------------------------------------------------------------------------------------------------------- #
def test_cancel_mid_download_frees_the_children_now_and_the_lock_when_the_download_ends(world):
    """_cancel_update / _end_update / _update_downloaded(ended): children free at once; the lock kept until the download
    ends (a new *Update now* never stages into the folder it still writes), then dropped and the staging discarded;
    nothing armed; the registry's job stopping until then."""
    world.stage = Stage(gate=False)
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.DOWNLOADING and updater.children_held(), seconds=10)
    assert svc.cancel() is True
    assert not updater.children_held()
    assert svc.state().state == U.AVAILABLE and svc.state().message == "Update cancelled."
    assert registry.live("update")[0].state == J.CANCELLING
    assert not _lock_is_free() and svc.start() is False and "discard" not in world.log
    world.stage.gate.set()
    assert h.until(lambda: "discard" in world.log and _lock_is_free(), seconds=10)
    assert h.until(lambda: registry.live("update") == (), seconds=5)
    assert registry.snapshot()[-1].cancelled and world.quits == [] and ("arm", NEWER, None) not in world.log
    assert svc.cancel() is False
    assert svc._update is None and svc.state().state == U.AVAILABLE    # offered again: it may start again


def test_cancel_mid_wait_releases_the_lock_discards_and_starts_what_was_held(world):
    """_cancel_update / _end_update: downloaded and waiting → the lock dropped now, the download discarded, the
    children asked for meanwhile started (`release_children(start=True)`)."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    started = []
    assert updater.defer_child(lambda: started.append("Generate")) is True
    assert svc.cancel() is True
    assert _lock_is_free() and world.log.count("discard") == 1
    assert started == ["Generate"] and not updater.children_held()
    world.children = []
    time.sleep(0.15)
    assert world.quits == [] and ("arm", NEWER, None) not in world.log


def test_closing_mid_wait_cancels_without_starting_what_was_held(world):
    """on_closing → _cancel_update(start_held=False): the children asked for meanwhile are dropped (they would outlive
    the window); nothing armed."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    started = []
    updater.defer_child(lambda: started.append("Generate"))
    svc.quit()
    assert started == [] and _lock_is_free() and not updater.children_held() and "discard" in world.log
    assert svc.start() is False                              # closing: nothing new starts


def test_a_cancel_from_the_registry_cancels_the_update(world):
    """The bar's job cancel reaches `cancel()` (the registry's cancel callback), children started as after Cancel."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    svc._update.job.cancel()
    assert h.until(_lock_is_free, seconds=5) and svc.state().state == U.AVAILABLE


def test_no_cancel_mid_swap(world):
    """_apply_and_restart runs as one step on the Tk thread: here a cancel during the hand-over is refused."""
    answers = []
    svc = world.offered(world.service())
    world.on_arm = lambda: answers.append(svc.cancel())
    assert svc.start()
    assert h.until(lambda: world.quits, seconds=10)
    assert answers == [False] and "discard" not in world.log


# --- failures ------------------------------------------------------------------------------------------------------ #
def test_a_failed_download_is_a_failed_state_and_a_report_never_a_dialog(world):
    """_update_downloaded(error): the update ended (lock, children), the report written (`write_report("download")`),
    the bar's `failed` state and a *Needs you* entry; nothing armed."""
    world.stage = Stage(error=updater.UpdateError("checksum mismatch — download corrupted or tampered"))
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.FAILED, seconds=10)
    s = svc.state()
    assert s.message.startswith("Couldn't download the update: checksum mismatch")
    assert s.report == updater.report_path() and "Stage: download" in open(s.report, encoding="utf-8").read()
    assert [(f.version, f.seen) for f in s.needs_you] == [(NEWER, False)]
    assert _lock_is_free() and not updater.children_held()
    assert registry.snapshot()[-1].state == J.FAILED and world.quits == [] and ("arm", NEWER, None) not in world.log
    assert svc.cancel() is False


def test_the_updater_failing_to_start_is_reported_and_releases_everything(world):
    """_apply_and_restart(arm_and_launch raises): the library locks released, the update ended, the report
    (`write_report("start updater")`), `failed` — the app stays open."""
    world.library = [["ja-lock"]]
    world.arm_error = OSError("updater.exe is missing")
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.FAILED, seconds=10)
    assert svc.state().message.startswith("Couldn't start the updater: updater.exe is missing")
    assert "Stage: start updater" in open(svc.state().report, encoding="utf-8").read()
    assert ("release library", ["ja-lock"]) in world.log
    assert world.quits == [] and _lock_is_free() and not updater.children_held()


# --- reconcile ----------------------------------------------------------------------------------------------------- #
def test_reconcile_with_nothing_pending_says_nothing(world, monkeypatch):
    """reconcile_update_result: no result → nothing (an unreadable one is the updater's to read)."""
    svc = world.service()
    monkeypatch.setattr(updater, "consume_result", lambda: None)
    assert svc.reconcile() == "none"

    def broken():
        raise OSError("the install folder is read-only")
    monkeypatch.setattr(updater, "consume_result", broken)
    assert svc.reconcile() == "none"
    assert svc.state().state == U.NONE and world.sent == []


def test_reconcile_after_an_update_sends_the_update_event(world, monkeypatch):
    """reconcile_update_result(success): the from→to telemetry event, and the state names the version it updated to."""
    monkeypatch.setattr(updater, "consume_result", lambda: {"status": "success", "from": "2.3.1", "to": __version__})
    svc = world.service()
    assert svc.reconcile() == "ok"
    assert world.sent == ["2.3.1"] and svc.state().updated == __version__ and svc.state().needs_you == ()


def test_reconcile_after_a_failed_update_records_it_and_is_never_tried_in_place_again(world, monkeypatch):
    """reconcile_update_result(failed): `record_failed_version` (update_state.json, never settings.json), the report
    (`write_report("install")`), `failed` and a *Needs you* entry that stays listed once seen; the next check offers
    that version as a download, saying why (_update_body)."""
    monkeypatch.setattr(updater, "consume_result",
                        lambda: {"status": "failed", "from": __version__, "to": NEWER, "reason": "update did not complete"})
    settings = FakeSettings()
    svc = world.service(settings)
    assert svc.reconcile() == "failed"
    assert updater.failed_version() == NEWER and settings.calls == []
    s = svc.state()
    assert s.state == U.FAILED and s.message.startswith("The automatic update didn't finish (update did not complete).")
    assert "Stage: install" in open(s.report, encoding="utf-8").read()
    svc.mark_seen()
    assert [(f.version, f.seen) for f in svc.state().needs_you] == [(NEWER, True)]
    svc.check(now=True)
    assert svc.state().cls == "FULL" and "didn't finish last time" in svc.state().body
    assert len(svc.state().needs_you) == 1 and world.sent == []


# --- the module itself --------------------------------------------------------------------------------------------- #
def test_the_service_imports_no_qt_tk_or_pandas():
    """The services' rule (app/services/__init__.py): headless under either window."""
    code = ("import sys; import app.services.updates; "
            "print([m for m in ('PyQt6', 'tkinter', 'pandas') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], cwd=h.PROJECT_ROOT, capture_output=True, text=True,
                         env=dict(os.environ, PYTHONPATH=h.PROJECT_ROOT), timeout=60)
    assert out.stdout.strip() == "[]", out.stderr


# --- the hold on new work (the Tk `hold_children` / `defer_child`) -------------------------------------------------- #
def test_no_new_job_starts_while_the_update_waits_and_it_starts_after_a_cancel(world):
    """_start_update's `hold_children` + run_command_async's `defer_child` + `_maybe_auto_generate` / `_maybe_anki_sync`'s
    `children_held()`: a Generate or a sync asked for while the update waits waits too (an arrivals reader, which only
    reads, still starts); Cancel starts what was held (`release_children(start=True)`)."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    started = []
    generate = registry.submit("generate", "Generating", lambda job: started.append("generate"))
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda job: started.append("sync"),
                           automatic=True)
    registry.submit("arrivals-ja", "New arrivals", lambda job: started.append("arrivals"))
    assert started == ["arrivals"]
    assert (generate.state, generate.reason) == (J.WAITING, U.HELD_REASON) and sync.state == J.WAITING
    assert svc.cancel()
    assert started == ["arrivals", "generate", "sync"]


def test_closing_mid_wait_starts_none_of_the_held_jobs(world):
    """on_closing → _cancel_update(start_held=False): a job held by the update never starts as the window closes."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    started = []
    generate = registry.submit("generate", "Generating", lambda job: started.append("generate"))
    svc.quit()
    registry.quit(timeout=1)
    assert started == [] and generate.state == J.DONE and generate.cancelled


def test_a_running_job_is_waited_for_and_stop_it_cancels_it(world):
    """_list_update_children / _stop_update_children for the registry's jobs: a running reorder (any kind) is in the
    wait list; *Stop it* cancels it as its own Cancel does; listed until it ends; then the update hands over."""
    registry = JobRegistry()
    cancelled = []
    junban = registry.submit("junban", "Re-ordering Anki", lambda job: None, cancel=lambda job: cancelled.append(job.id))
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().programs == (U.Program("Re-ordering Anki", "Re-ordering Anki", True),),
                   seconds=10)
    assert svc.stop("Re-ordering Anki") is True
    assert h.until(lambda: cancelled == [junban.id], seconds=5)
    time.sleep(0.15)
    assert world.quits == [] and svc.state().state == U.WAITING      # cancelling: still waited for
    junban.finish(ok=True, cancelled=True)
    assert h.until(lambda: world.quits, seconds=10)


def test_a_job_held_during_the_download_starts_at_the_cancel(world):
    """_cancel_update mid-download: `release_children(start=True)` at once — what was held starts now, never only when
    the download ends."""
    world.stage = Stage(gate=False)
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.DOWNLOADING and updater.children_held(), seconds=10)
    started = []
    registry.submit("generate", "Generating", lambda job: started.append("generate"))
    assert started == []
    assert svc.cancel()
    assert started == ["generate"] and not world.stage.finished.is_set()


def test_failures_are_a_status_provider_line_until_seen(world):
    """The bar / Needs you: `failure()` is the newest unseen failure (a StatusService provider's shape); `failures()`
    keeps every one listed after it was seen (P1.2-1)."""
    world.stage = Stage(error=updater.UpdateError("release has no app package or checksum"))
    svc = world.offered(world.service())
    assert svc.failure() is None
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.FAILED, seconds=10)
    assert svc.failure().startswith("Couldn't download the update: release has no app package")
    svc.mark_seen()
    assert svc.failure() is None and [f.seen for f in svc.failures()] == [True]


# --- W3.5 worker K: the Haiku mutant list's survivors ------------------------------------------------------------ #
def _lock_take_held(monkeypatch):
    """`take_update_lock` held until the test opens `gate` (`entered` once it is asked), and a child asked for in the
    instant the update holds the children (between `hold_children` and the release: `started` hears it if it starts)."""
    entered, gate, started = threading.Event(), threading.Event(), []
    real_take, real_hold = updater.take_update_lock, updater.hold_children

    def take(*a, **k):
        entered.set()
        gate.wait(20)
        return real_take(*a, **k)

    def hold():
        real_hold()
        updater.defer_child(lambda: started.append("Content Manager"))
    monkeypatch.setattr(updater, "take_update_lock", take)
    monkeypatch.setattr(updater, "hold_children", hold)
    return entered, gate, started


def test_a_cancel_while_the_lock_is_taken_frees_the_lock_and_starts_what_was_held(world, monkeypatch):
    """_start_update's worker, `if job["ended"]` once the lock is taken (cancelled meanwhile): the update lock dropped
    (else no *Update now* ever works again), the children released as the cancel said (`start=True`: one asked for
    meanwhile starts), nothing downloaded, the job cancelled."""
    entered, gate, started = _lock_take_held(monkeypatch)
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert entered.wait(10)
    assert svc.cancel() is True
    gate.set()
    assert h.until(lambda: svc._update is None, seconds=10)
    assert _lock_is_free(), "the update lock taken after the cancel is dropped"
    assert not updater.children_held() and started == ["Content Manager"]
    assert world.stage.calls == [] and registry.snapshot()[-1].cancelled


def test_closing_while_the_lock_is_taken_drops_what_was_held(world, monkeypatch):
    """on_closing → _cancel_update(start_held=False) while the lock is being taken: once it is, the children are
    released with the close's `start=False` — a child asked for meanwhile is dropped (it would outlive the window)."""
    entered, gate, started = _lock_take_held(monkeypatch)
    svc = world.offered(world.service())
    assert svc.start()
    assert entered.wait(10)
    svc.quit()
    gate.set()
    assert h.until(lambda: svc._update is None, seconds=10)
    assert started == [] and not updater.children_held() and _lock_is_free()


def test_a_cancel_ends_the_wait_list_while_programs_still_run(world, monkeypatch):
    """_update_poll's `if job["ended"]: return`: after Cancel the wait list stops being read — no poller left listing
    the machine's programs (and the window's `active()`) for the rest of the session."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    pollers = set()
    real = updater.running_children
    monkeypatch.setattr(updater, "running_children", lambda active=(), images=None: (
        pollers.add(threading.current_thread()), real(active))[1])
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    assert svc.cancel() is True
    (poller,) = pollers
    poller.join(10)
    assert not poller.is_alive(), "the wait loop ended with the update"


def test_stop_it_reads_the_list_again_at_once(world):
    """_stop_update_children then `_update_poll()` at once: after *Stop it* the list is read again without waiting out
    the poll's period — a minute here, so only that wake can hand over in time."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: world.children.clear()}]
    svc = U.UpdateService(FakeSettings(), JobRegistry(), on_quit=lambda: world.quits.append(1),
                          open_url=world.opened.append, poll=60)
    world.services.append(svc)
    world.offered(svc)
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING and svc.state().programs, seconds=10)
    assert svc.stop(4242) is True
    assert h.until(lambda: world.quits, seconds=10), "handed over at once, not a poll period later"


def test_closing_after_a_cancel_holds_back_nothing(world):
    """quit() after Cancel, the cancelled download still ending: the update is over, so the close holds no job back
    (the hold is for an update still waiting) — an Anki write queued behind another (`wait` at quit) still runs."""
    world.stage = Stage(gate=False)
    registry = JobRegistry()
    svc = world.offered(world.service(registry=registry))
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.DOWNLOADING and updater.children_held(), seconds=10)
    assert svc.cancel() is True and svc._update is not None          # its download still ending
    started = []
    junban = registry.submit("junban", "Re-ordering Anki", lambda job: started.append("junban"), on_quit="wait")
    backfill = registry.submit("backfill", "Filling cards", lambda job: started.append("backfill"), on_quit="wait")
    assert started == ["junban"] and backfill.state == J.WAITING
    svc.quit()
    junban.finish()
    assert started == ["junban", "backfill"] and backfill.state == J.RUNNING


def test_needs_you_keeps_the_newest_twenty_update_failures(world, monkeypatch):
    """`NEEDS_YOU_KEPT`: *Needs you* lists the update's newest 20 failures, newest first; an older one goes."""
    svc = world.service()
    for n in range(U.NEEDS_YOU_KEPT + 1):
        monkeypatch.setattr(updater, "consume_result", lambda n=n: {
            "status": "failed", "from": __version__, "to": f"99.{n}", "reason": "update did not complete"})
        assert svc.reconcile() == "failed"
    kept = svc.failures()
    assert len(kept) == U.NEEDS_YOU_KEPT == 20 and len(svc.state().needs_you) == 20
    assert kept[0].version == "99.20" and kept[-1].version == "99.1"


def test_a_late_turn_of_the_wait_never_overwrites_the_cancel(world):
    """_update_poll after `_cancel_update`: a turn of the wait already past its ended check when Cancel lands (called
    here after the cancel, as that race would) says nothing — the bar keeps *Update cancelled.*, never a stale
    *Waiting for Content Manager*."""
    world.children = [{"pid": 4242, "name": "Content Manager", "stop": lambda: None}]
    svc = world.offered(world.service())
    assert svc.start()
    assert h.until(lambda: svc.state().state == U.WAITING, seconds=10)
    update = svc._update
    assert svc.cancel() is True
    seen = _states(svc)
    svc._say(update)
    assert (svc.state().state, svc.state().message) == (U.AVAILABLE, "Update cancelled.") and seen == []
