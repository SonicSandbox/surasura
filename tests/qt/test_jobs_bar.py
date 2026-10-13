"""The dashboard's duties in the window (W3.5 rows 2, 4, 5 and the wiring; the window's spec 05 §5.2, 03, 06 E10).

What a wrong answer would cost:
  * a Generate that can't be stopped, or one stopped half-way through writing the list (the CSVs aren't atomic: a
    click after *Writing your list* must do nothing);
  * a failed Generate or update shown nowhere — or as a box (E10, ✅ G0.3-1: the bar and Needs you);
  * an update installed after the user pressed Esc or Cancel (IK-2), or *Skip this version* rewriting his settings;
  * a critical release's sheet opening again and again;
  * the bar repainting every mark on every state (S19), or a status change holding the window over 4 ms;
  * the window's close cutting the duties in the wrong order (the update's held jobs started as it quits).

Behaviour only (the looks are Sonic's to re-skin): what a click asks the services, what each state shows, what repaints.
The services are stand-ins that record what the window asks; their own rules are their suites' (tests/test_services_*).
"""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QPushButton

from app.qt import shell, strings
from app.services import automation as A
from app.services import chores as C
from app.services import generate as G
from app.services import updates as U
from app.services.jobs import JobRegistry
from app.services.status import StatusService
from tests import services_helpers as h
from tests.qt.conftest import wait_until


# --- stand-ins ------------------------------------------------------------------------------------------------------- #
class _Duty:
    """Records every call; `push(state)` tells the subscribers from another thread, as a service does."""

    def __init__(self, state, log):
        self._state = state
        self.subscribers = []
        self.calls = []
        self.log = log
        self.threads = {}

    def state(self):
        return self._state

    def subscribe(self, cb):
        self.subscribers.append(cb)

    def push(self, **changes):
        self._state = self._state._replace(seq=self._state.seq + 1, **changes)
        t = threading.Thread(target=lambda: [cb(self._state) for cb in list(self.subscribers)])
        t.start()
        t.join()
        return self._state

    def _record(self, name, *args):
        self.calls.append((name,) + args)
        self.log.append(name)
        self.threads[name] = threading.current_thread()

    def called(self, name):
        return [c for c in self.calls if c[0] == name]


class FakeUpdates(_Duty):
    def __init__(self, log):
        super().__init__(U.State(U.NONE, "", "NONE", "", "", False, False, None, None, (), None, None, (), None, 0),
                         log)

    def failure(self):
        return next((f.text for f in self._state.needs_you if not f.seen), None)

    def begin(self): self._record("updates.begin")
    def start(self): self._record("updates.start"); return True
    def skip(self, version=None): self._record("updates.skip", version); return True
    def stop(self, key=None): self._record("updates.stop", key); return True
    def cancel(self, start_held=True): self._record("updates.cancel"); return True
    def open_download(self): self._record("updates.open_download")
    def mark_seen(self): self._record("updates.mark_seen")
    def quit(self): self._record("updates.quit")


class FakeController(_Duty):
    def __init__(self, log):
        super().__init__(G.State(G.IDLE, None, None, None, None, None, None, 0), log)

    def check(self, settings, language, then=None): self._record("controller.check", language)
    def request(self, language, **kw): self._record("controller.request", language, kw.get("quiet", False))
    def cancel(self): self._record("controller.cancel")
    def on_end(self, cb): pass
    def unsubscribe(self, cb): pass


class FakeAutomation(_Duty):
    def __init__(self, log):
        super().__init__(A.State(A.IDLE, "ja", 0, None, None, None, 0), log)

    def started(self): self._record("automation.started")
    def activated(self): self._record("automation.activated")
    def language_changed(self, language): self._record("automation.language_changed", language)
    def recheck(self): self._record("automation.recheck")
    def before_generate(self): self._record("automation.before_generate")
    def update_cancelled(self): self._record("automation.update_cancelled")
    def close(self): self._record("automation.close")


class FakeChores(_Duty):
    def __init__(self, log):
        super().__init__(C.State(None, None, 0), log)

    def on_indexed(self, cb): self.indexed = cb
    def started(self): self._record("chores.started")
    def activated(self): self._record("chores.activated")
    def language_changed(self, language): self._record("chores.language_changed", language)
    def koe_changed(self): self._record("chores.koe_changed")
    def close(self, store=True):            # as the real one: the store's close trigger too, unless store=False
        self._record("chores.close", store)
        if store:
            self.close_store()

    def close_store(self): self._record("chores.close_store")
    def halt(self): self._record("chores.halt")


class QuietReader:
    """No command-line events file: only the duties' failures reach the bar."""

    def changed(self):
        return False

    def newest_to_show(self):
        return None


class World:
    def __init__(self, qapp, logs_folder=None, automation=None):
        self.log = []
        self.updates = FakeUpdates(self.log)
        self.controller = FakeController(self.log)
        self.automation = automation or FakeAutomation(self.log)
        self.chores = FakeChores(self.log)
        self.registry = JobRegistry()
        self.status = StatusService(self.registry, reader=QuietReader(), logs_folder=logs_folder)
        self.services = shell.Services(registry=self.registry, status=self.status, controller=self.controller,
                                       updates=self.updates, automation=self.automation, chores=self.chores)
        self.win = shell.open_window(qapp, self.services)
        self.win.show()
        QApplication.processEvents()
        self.d = self.win.duties

    def start(self):
        self.win.start_duties()
        assert wait_until(lambda: self.services.started and "chores.started" in self.log)

    def close(self):
        self.win.close()
        self.services.shutdown(0.5)


@pytest.fixture
def world(qapp, tmp_path):
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    yield w
    w.close()


# --- the header: Generate --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("changes, text, look, enabled, bar, log", [
    (dict(state=G.IDLE), strings.GENERATE, "idle", True, False, False),
    (dict(state=G.CURRENT), strings.GENERATE_CURRENT, "current", True, False, False),
    (dict(state=G.STALE), strings.GENERATE, "stale", True, False, False),
    (dict(state=G.QUEUED, message="Waiting for another Generate to finish"), strings.GENERATE_QUEUED, "busy", True,
     False, False),
    (dict(state=G.RUNNING, step="Counting words", done=1, total=2), "Generating… 30 %", "busy", True, True, False),
    (dict(state=G.RUNNING, step="Writing your list"), "Generating… 60 %", "busy", False, True, False),
    (dict(state=G.CANCELLING, message="Stopping before your list is written"), strings.GENERATE_STOPPING, "busy",
     False, False, False),
    (dict(state=G.FAILED, message="Generate stopped (exit code 1).", log_path="gen.log"), strings.GENERATE_FAILED,
     "failed", True, False, True),
])
def test_header_generate_shows_each_state(world, changes, text, look, enabled, bar, log):
    world.controller.push(**changes)
    g = world.d.generate
    assert wait_until(lambda: g.button.text() == text)
    assert g.button.property("look") == look
    assert g.button.isEnabled() == enabled
    assert g.bar.isVisibleTo(world.win) == bar
    assert g.log_button.isVisibleTo(world.win) == log
    assert g.button.toolTip()


def test_header_holds_generate_the_journey_and_help_and_no_level_menu(world):
    # Sonic's W3.5-1: the Level menu (Generate's ▾) is not built. ? holds *Online guide* only until the tours (IK-15).
    header = world.win.header
    texts = [b.text() for b in header.findChildren(QAbstractButton)]
    assert strings.GENERATE in texts and strings.JOURNEY in texts and strings.HELP in texts
    assert not any("▾" in t for t in texts)


def test_header_help_opens_the_online_guide_the_tk_dashboard_opens_too(world, monkeypatch):
    """IK-24 (RUNBOOK row 4: ? with *Online guide*, the browser's link): one constant, `path_utils.GUIDE_URL`, read
    by both windows — the Tk dashboard's Help › Tutorial and this ?; the browser opens on a worker."""
    import webbrowser
    from app import path_utils
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append((url, threading.current_thread())))
    help_button = world.d.help
    actions = help_button.menu().actions()
    assert [a.text() for a in actions] == [strings.HELP_GUIDE]
    assert help_button.toolTip()
    actions[0].trigger()
    assert wait_until(lambda: opened)
    assert opened[0][0] == path_utils.GUIDE_URL and opened[0][1] is not threading.main_thread()
    from app import main as tk_dashboard
    tk_dashboard.MasterDashboardApp.open_tutorial(None)
    assert opened[-1][0] == path_utils.GUIDE_URL


def test_header_click_during_an_automatic_generate_is_the_users_own_run(world):
    """IK-20 (the Tk `run_analyzer`: a press while a quiet run goes is the user's Generate, never a cancel of it): the
    click asks the controller for the user's run, which takes the automatic one's place — even once it writes."""
    button = world.d.generate.button
    world.controller.push(state=G.RUNNING, step="Picking sentences", done=3, total=10, quiet=True)
    assert wait_until(lambda: button.text().startswith("Generating…"))
    assert button.isEnabled()
    button.click()
    assert wait_until(lambda: world.controller.called("controller.request"))
    assert world.controller.called("controller.request")[0][1:] == ("ja", False)
    world.controller.push(state=G.RUNNING, step="Writing your list", done=None, total=None, quiet=True)
    assert wait_until(lambda: button.text() == "Generating… 60 %")
    assert button.isEnabled()
    button.click()
    assert wait_until(lambda: len(world.controller.called("controller.request")) == 2)
    assert not world.controller.called("controller.cancel")


def test_header_generate_sets_up_the_language_folders_first(world, monkeypatch):
    """IK-21 (`run_analyzer`: `ensure_data_setup(language)` before every Generate — the tier folders, the word lists,
    the 30-day .trash clean-up): on the worker, before the controller's run."""
    from app import path_utils
    monkeypatch.setattr(path_utils, "ensure_data_setup", lambda language=None: (
        world.log.append(("ensure_data_setup", language, threading.current_thread() is threading.main_thread()))))
    world.d.generate.button.click()
    assert wait_until(lambda: world.controller.called("controller.request"))
    assert ("ensure_data_setup", "ja", False) in world.log
    assert world.log.index(("ensure_data_setup", "ja", False)) < world.log.index("controller.request")


def test_header_generate_click_runs_through_the_controller(world):
    world.controller.push(state=G.STALE)
    assert wait_until(lambda: world.d.generate.button.property("look") == "stale")
    world.d.generate.button.click()
    assert wait_until(lambda: world.controller.called("controller.request"))
    assert world.controller.called("controller.request")[0][1:] == ("ja", False)      # the user's: not quiet
    assert world.log.index("automation.before_generate") < world.log.index("controller.request")   # the backlog read
    assert world.controller.threads["controller.request"] is not threading.main_thread()


def test_header_click_while_running_cancels_but_never_once_writing(world):
    world.controller.push(state=G.RUNNING, step="Picking sentences", done=3, total=10)
    button = world.d.generate.button
    assert wait_until(lambda: button.text().startswith("Generating…"))
    button.click()
    assert wait_until(lambda: world.controller.called("controller.cancel"))
    assert not world.controller.called("controller.request")
    world.controller.push(state=G.RUNNING, step="Writing your list", done=None, total=None)
    assert wait_until(lambda: not button.isEnabled())
    button.click()                                       # disabled: nothing asked
    QTest.qWait(50)
    assert len(world.controller.called("controller.cancel")) == 1
    world.controller.push(state=G.QUEUED)                # still waiting its turn: a click drops it
    assert wait_until(lambda: button.isEnabled() and button.text() == strings.GENERATE_QUEUED)
    button.click()
    assert wait_until(lambda: len(world.controller.called("controller.cancel")) == 2)


def test_header_a_failed_generate_reaches_the_bar_and_needs_you_and_opens_its_log(world, monkeypatch):
    # E10, IK-7: `failed` on the button with *Open the log*, the bar's failure line, a Needs you entry — never a box.
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append((path, threading.current_thread())),
                        raising=False)
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).", log_path="C:/logs/gen.log")
    assert wait_until(lambda: world.win.bar_failure.isVisibleTo(world.win))
    assert "Generate stopped (exit code 1)." in world.win.bar_failure.full()
    assert wait_until(lambda: not world.win.tab_buttons["needs"].isHidden())
    assert world.win.tab_buttons["needs"].count == 1
    world.d.generate.log_button.click()
    if os.name == "nt":
        assert wait_until(lambda: opened)
        assert opened[0][0] == "C:/logs/gen.log" and opened[0][1] is not threading.main_thread()


def test_header_the_journey_waits_for_a_journey_and_opens_on_a_worker(world, monkeypatch, tmp_path):
    from app import static_html_generator
    report = tmp_path / "reading_list_static.html"
    monkeypatch.setattr(static_html_generator, "OUTPUT_FILE", str(report))
    opened = []
    monkeypatch.setattr(static_html_generator, "open_report",
                        lambda app_mode=False: opened.append((app_mode, threading.current_thread())) or True)
    world.start()
    journey = world.d.journey
    QTest.qWait(50)
    assert not journey.isEnabled() and journey.toolTip() == strings.JOURNEY_NONE_TIP
    report.write_text("<html></html>", encoding="utf-8")
    world.controller.push(state=G.RUNNING, step="Writing the journey")
    world.controller.push(state=G.CURRENT)               # a run ended: the journey is looked for again
    assert wait_until(lambda: journey.isEnabled())
    assert journey.toolTip() == strings.JOURNEY_TIP
    journey.click()
    assert wait_until(lambda: opened)
    assert opened[0][0] is False and opened[0][1] is not threading.main_thread()


def test_header_start_asks_the_journey_and_starts_every_duty_once(world):
    world.start()
    world.win.start_duties()                             # a second first frame: nothing twice
    QTest.qWait(50)
    for name in ("controller.check", "updates.begin", "automation.started", "chores.started"):
        assert world.log.count(name) == 1, name


# --- the update ---------------------------------------------------------------------------------------------------- #
def _offer(world, **more):
    offer = dict(state=U.AVAILABLE, version="99.0", cls="APP", body="A quick in-app update.",
                 notes_url="https://example.invalid/notes")
    offer.update(more)
    return world.updates.push(**offer)


def test_update_mark_says_ready_and_a_click_opens_the_sheet(world):
    mark = world.d.update_mark
    assert mark.isHidden()
    _offer(world)
    assert wait_until(lambda: mark.text() == strings.UPDATE_READY)
    assert "99.0" in mark.toolTip()
    sheet = world.d.sheet
    assert not sheet.isVisible()
    mark.click()
    assert wait_until(lambda: sheet.isVisible())
    assert "99.0" in sheet.title.text() and sheet.body.text() == "A quick in-app update."
    assert sheet.buttons["start"].isVisibleTo(sheet) and not sheet.buttons["download"].isVisibleTo(sheet)
    world.updates.push(state=U.WAITING, programs=(U.Program(1, "Content Manager", True),))
    assert wait_until(lambda: mark.text() == strings.UPDATE_RESTART)


def test_update_sheet_buttons_call_the_service(world):
    _offer(world)
    assert wait_until(lambda: not world.d.update_mark.isHidden())
    sheet = world.d.sheet
    world.win.open_update_sheet()
    sheet.buttons["notes"].click()
    sheet.buttons["start"].click()
    assert wait_until(lambda: world.updates.called("updates.start") and world.updates.called("updates.open_download"))
    sheet.buttons["later"].click()                       # Later: closed, nothing cancelled
    assert wait_until(lambda: not sheet.isVisible())
    assert not world.updates.called("updates.cancel")
    world.win.open_update_sheet()
    sheet.buttons["skip"].click()
    assert wait_until(lambda: world.updates.called("updates.skip"))
    assert world.updates.called("updates.skip")[0] == ("updates.skip", None) and not sheet.isVisible()
    _offer(world, cls="FULL")                            # a manual release: Download, not Update now
    assert wait_until(lambda: sheet.buttons["download"].isVisibleTo(sheet))
    assert not sheet.buttons["start"].isVisibleTo(sheet)


def test_update_skip_writes_only_skipped_version(qapp, monkeypatch):
    """With the real update service: the sheet's *Skip this version* sends `skipped_version` alone to the settings
    service (the Tk `_skip_update`), never the whole file."""
    from app import update_checker, updater
    from app.update_checker import UpdateInfo
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update_checker, "get_update_info", lambda *a, **k: UpdateInfo(
        version="99.0", update_type="app", runtime_baseline="0.0", sha256="a" * 64,
        app_package_url="https://example.invalid/app.zip", notes_url="https://example.invalid/notes"))
    monkeypatch.setattr(updater, "can_auto_apply", lambda info=None: True)
    log = []
    registry = JobRegistry()
    services = shell.Services(registry=registry, status=StatusService(registry, reader=QuietReader()),
                              controller=FakeController(log), automation=FakeAutomation(log), chores=FakeChores(log))
    services.updates = U.UpdateService(services.settings, registry, on_quit=lambda: None)
    services._provide()
    written = []
    real_set = services.settings.set
    monkeypatch.setattr(services.settings, "set", lambda changes, **kw: (written.append(dict(changes)),
                                                                         real_set(changes, **kw)))
    win = shell.open_window(qapp, services)
    win.show()
    try:
        assert services.updates.check(now=True)
        assert wait_until(lambda: win.duties.update_mark.text() == strings.UPDATE_READY)
        win.open_update_sheet()
        win.duties.sheet.buttons["skip"].click()
        assert wait_until(lambda: written)
        assert written == [{"skipped_version": "99.0"}]
        assert wait_until(lambda: win.duties.update_mark.isHidden())
    finally:
        win.close()
        services.shutdown(0.5)


def test_update_esc_while_waiting_cancels_and_the_wait_list_repaints_only_when_it_changes(world):
    programs = (U.Program(41, "Content Manager", True), U.Program("Anki sync", "Anki sync", False))
    _offer(world)
    world.updates.push(state=U.WAITING, programs=programs)
    sheet = world.d.sheet
    assert wait_until(lambda: world.d.update_mark.text() == strings.UPDATE_RESTART)
    world.win.open_update_sheet()
    assert wait_until(lambda: sheet.isVisible())
    stops = [b for b in sheet.findChildren(QPushButton) if b.text() == strings.UPDATE_STOP and b.isVisibleTo(sheet)]
    assert len(stops) == 1                               # the sync is waited for, never stopped
    assert sheet.buttons["stop-all"].isVisibleTo(sheet) and sheet.buttons["cancel"].isVisibleTo(sheet)
    rows, paints = list(sheet.program_rows), sheet.paints
    world.updates.push(state=U.WAITING, programs=programs)       # the same list again (a poll): nothing repainted
    QTest.qWait(30)
    assert sheet.paints == paints and sheet.program_rows == rows
    stops[0].click()
    assert wait_until(lambda: world.updates.called("updates.stop"))
    assert world.updates.called("updates.stop")[0] == ("updates.stop", 41)
    sheet.buttons["stop-all"].click()
    assert wait_until(lambda: ("updates.stop", None) in world.updates.calls)
    QTest.keyClick(world.win, Qt.Key.Key_Escape)                 # Esc while it waits: the update is cancelled (IK-2)
    assert wait_until(lambda: world.updates.called("updates.cancel"))
    assert not sheet.isVisible()
    assert wait_until(lambda: world.automation.called("automation.update_cancelled"))   # a held Generate asks again


def test_update_a_critical_release_opens_the_sheet_once(world):
    _offer(world, critical=True, open_now=True)
    sheet = world.d.sheet
    assert wait_until(lambda: sheet.isVisible())
    assert "important" in sheet.title.text()
    sheet.close()                                        # Later / Esc: an offer is only closed
    assert not world.updates.called("updates.cancel")
    _offer(world, critical=True, open_now=False)         # asked again later: the service says it surfaced already
    QTest.qWait(50)
    assert not sheet.isVisible()


def test_update_needs_you_cards_and_their_actions(world, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path), raising=False)
    (tmp_path / "logs").mkdir()
    world.status.refresh()                               # the logs folder known to the bar
    _offer(world)
    cards = world.d.cards
    assert wait_until(lambda: len(cards.cards) == 1)
    assert not world.win.tab_buttons["needs"].isHidden()
    assert world.win.tab_buttons["needs"].count == 0     # an offer is listed, never counted (the mark says it)
    buttons = {b.text(): b for b in cards.findChildren(QPushButton)}
    buttons[strings.UPDATE_NOW].click()
    assert wait_until(lambda: world.updates.called("updates.start"))
    failure = U.Failure("The automatic update didn't finish (exit code 3).", 0.0, False, "99.0", "report.txt")
    world.updates.push(state=U.FAILED, message=failure.text, version="99.0", needs_you=(failure,))
    assert wait_until(lambda: len(cards.cards) == 1
                      and cards.cards[0].findChildren(QPushButton)[0].text() == strings.UPDATE_SKIP)
    assert not cards.isHidden()
    assert wait_until(lambda: world.win.tab_buttons["needs"].count == 1)
    assert wait_until(lambda: "didn't finish" in world.win.bar_failure.full())     # the bar's failure line too
    buttons = {b.text(): b for b in cards.cards[0].findChildren(QPushButton)}
    buttons[strings.UPDATE_SKIP].click()
    assert wait_until(lambda: ("updates.skip", "99.0") in world.updates.calls)
    buttons[strings.BAR_LOGS].click()
    if os.name == "nt":
        assert wait_until(lambda: opened == [str(tmp_path / "logs")])
    world.win.show_tab("needs")                          # looked at: it stops counting (P1.2-1)
    assert wait_until(lambda: world.updates.called("updates.mark_seen"))


# --- the bottom bar's marks ---------------------------------------------------------------------------------------- #
def test_bar_marks_show_the_automation_state_and_repaint_only_on_change(world):
    d = world.d
    assert wait_until(lambda: d.anki.text() == strings.BAR_ANKI["off"])            # anki_sync_auto off by default
    world.services.settings.set({"anki_sync_auto": True}, now=True)
    assert wait_until(lambda: d.anki.isHidden())                                  # on, nothing synced yet
    world.automation.push(sync=A.SYNCING)
    assert wait_until(lambda: d.anki.text() == strings.BAR_ANKI["syncing"])
    world.automation.push(sync=A.SYNCED, added=3, known=12345)
    assert wait_until(lambda: d.known.text() == "12,345 known" and d.anki.text() == strings.BAR_ANKI["synced"])
    assert "3" in d.anki.toolTip()
    painted = (d.paints[d.known], d.paints[d.anki])
    world.automation.push(junban="順: placed 20 cards")                         # nothing the marks show changed
    QTest.qWait(30)
    assert (d.paints[d.known], d.paints[d.anki]) == painted
    world.automation.push(sync=A.CLOSED, message="Anki is closed")
    assert wait_until(lambda: d.anki.text() == "Anki closed — work waits")
    assert d.paints[d.known] == painted[0]                                        # the count didn't move: not repainted


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_bar_known_count_from_a_real_known_words_file(qapp, lang):
    """The count the real automation service reads from the test root's KnownWord.json (Japanese and Chinese)."""
    from app import anki_sync
    h.seed_library(lang)
    log = []
    controller = FakeController(log)
    registry = JobRegistry()
    services = shell.Services(registry=registry, status=StatusService(registry, reader=QuietReader()))
    automation = A.Automation(registry, controller, services.settings, lang)
    world = None
    try:
        services.controller, services.updates, services.chores = controller, FakeUpdates(log), FakeChores(log)
        services.automation = automation
        win = shell.open_window(qapp, services)
        win.show()
        world = win
        expected = anki_sync.count_known(lang)
        assert expected > 0
        win.start_duties()
        assert wait_until(lambda: win.duties.known.text() == strings.BAR_KNOWN.format(n=expected))
    finally:
        if world is not None:
            world.close()
        services.shutdown(0.5)


def test_bar_level_chip_reads_the_band_and_automatic(world):
    world.services.settings.set({"logic.selection.band": "rare"}, now=True)
    world.start()
    level = world.d.level
    assert wait_until(lambda: level.text() == "Rare")
    world.services.settings.set({"logic.selection.auto": True}, now=True)
    assert wait_until(lambda: level.text().startswith("Auto"))      # no store yet: "Auto" until a Generate
    assert level.toolTip()


def test_bar_a_status_change_takes_under_4_ms_on_the_window_thread(world):
    # 07 §7.1: no GUI-thread step over 4 ms — painting a new state is a few label sets, never a read.
    win = world.win
    _offer(world)
    assert wait_until(lambda: not world.d.update_mark.isHidden())
    states = []
    for n in range(20):
        states.append(("auto", A.State(A.SYNCED, "ja", n, 1000 + n, None, None, n)))
        states.append(("gen", G.State(G.RUNNING, "Counting words", n, 20, None, None, 1, n)))
        states.append(("upd", world.updates.state()._replace(state=U.DOWNLOADING, done=n, total=20, seq=100 + n)))
    took = []
    for kind, state in states:
        t0 = time.perf_counter()
        {"auto": win._show_automation, "gen": win._show_generate, "upd": win._show_update}[kind](state)
        took.append((time.perf_counter() - t0) * 1000)
    took.sort()
    assert took[int(len(took) * 0.9)] < 4.0, took[-5:]


# --- the duties' wiring: activation, settings, quit --------------------------------------------------------------- #
def test_chores_koe_switch_and_activation_reach_the_duties(world, monkeypatch):
    world.start()
    world.services.settings.set({"enable_koe": True}, now=True)
    assert wait_until(lambda: world.chores.called("chores.koe_changed"))
    monkeypatch.setattr(world.win, "isActiveWindow", lambda: True)
    world.win.changeEvent(QEvent(QEvent.Type.ActivationChange))
    assert wait_until(lambda: world.automation.called("automation.activated") and world.chores.called(
        "chores.activated"))
    assert world.automation.threads["automation.activated"] is not threading.main_thread()


def test_chores_settings_that_stale_the_journey_ask_it_again(world):
    world.start()
    world.services.settings.set({"exclude_single": False}, now=True)
    assert wait_until(lambda: world.automation.called("automation.recheck"))


def test_quit_cancels_the_update_before_the_jobs_and_closes_the_duties_off_the_window_thread(qapp, monkeypatch):
    w = World(qapp)
    w.start()
    real_quit = w.registry.quit
    monkeypatch.setattr(w.registry, "quit", lambda timeout=2.0, **kw: (w.log.append("registry.quit"),
                                                                        real_quit(timeout, **kw)))
    w.win.close()
    w.services.shutdown(0.5)
    assert w.log.index("updates.quit") < w.log.index("registry.quit")
    assert "automation.close" in w.log and "chores.close" in w.log and "chores.close_store" in w.log
    assert w.automation.threads["automation.close"] is not threading.main_thread()
    assert w.chores.threads["chores.close"] is not threading.main_thread()
    assert w.chores.threads["chores.close_store"] is not threading.main_thread()


def test_quit_lets_an_anki_write_finish_and_runs_the_close_chores_to_the_end(qapp, monkeypatch):
    """IK-22 / HR-22 (E20: "an Anki write finishes its batch first"; the Tk `on_closing` ran Koe's stop, Connect's
    `at_close` and the store's close trigger to their end): the window's short quit timeout never cuts them — nor
    does the quit when the window didn't wait for the write itself (the update's hand-over closes at once)."""
    w = World(qapp)
    w.start()
    finished = []
    job = w.registry.submit("junban", "Re-ordering Anki (automatic)",
                            lambda j: threading.Timer(0.6, j.finish).start(), automatic=True, on_quit="wait")
    monkeypatch.setattr(w.chores, "close_store", lambda: (time.sleep(0.6), finished.append("chores.close_store")))
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
    assert wait_until(lambda: A.JUNBAN_LABEL in w.win.bar_line.full())
    w.win._quit_for_update()                                    # the update hands over: the window goes at once
    assert not w.win.isVisible()
    w.services.shutdown(0.1)
    assert job.state == "done" and not job.cancelled
    assert finished == ["chores.close_store"]


# --- W3.5: quitting while an Anki write runs (E20), and no unbounded wait at exit ------------------------------- #
def _anki_write(registry):
    """順's automatic reorder under way (`wait` at quit: an Anki write finishes its batch), ended when the test says."""
    return registry.submit("junban", A.JUNBAN_LABEL, lambda j: None, automatic=True, on_quit="wait")


def _bar_shows(world, text):
    return wait_until(lambda: text in world.win.bar_line.full())


def test_closing_while_an_anki_write_runs_keeps_the_window_with_one_line_until_it_ends(world):
    """E20 (W1.2 06: "an Anki write finishes its batch first (≤ a few seconds, a line says so)"; the Tk
    `_replan_finishing`, which kept the window with *Finishing the re-order in Anki…*): the close leaves the window up
    with one line in the bar; Generate is cancelled at once and Connect's job goes on (`detach`); a second close and
    Esc change nothing; the window closes by itself when the write ends — the registry's own signal, no poll."""
    world.start()
    gen = world.registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: j.finish(cancelled=True),
                                on_quit="cancel")
    connect = world.registry.submit("arrivals-ja", "New arrivals", lambda j: None, on_quit="detach")
    write = _anki_write(world.registry)
    assert _bar_shows(world, A.JUNBAN_LABEL)
    world.win.close()
    assert world.win.isVisible()
    assert world.win.bar_line.full() == strings.QUIT_FINISHING                  # one line, the jobs' lines behind it
    assert wait_until(lambda: gen.state == "done" and gen.cancelled)            # Generate: cancelled at once
    assert connect.state == "running" and write.state == "running"
    world.win.close()                                                           # a second close: nothing changes
    QTest.keyClick(world.win, Qt.Key.Key_Escape)                                # nor Esc
    QTest.qWait(60)
    assert world.win.isVisible() and world.log.count("updates.quit") == 1
    assert world.win.bar_line.full() == strings.QUIT_FINISHING
    write.finish()
    assert wait_until(lambda: not world.win.isVisible())


def test_nothing_new_starts_while_the_window_waits_for_an_anki_write(world, monkeypatch):
    """E20: while the window waits for the write, the header's Generate, the window's activation (the sync, 順, the
    indexer, the store's helper) and any duty's job start nothing — a job asked for is held, with its reason."""
    world.start()
    monkeypatch.setattr(world.win, "isActiveWindow", lambda: True)
    write = _anki_write(world.registry)
    assert _bar_shows(world, A.JUNBAN_LABEL)
    activated = len(world.automation.called("automation.activated")), len(world.chores.called("chores.activated"))
    world.win.close()
    assert wait_until(lambda: world.services.closing.is_set())
    world.d.generate.button.click()
    world.win.changeEvent(QEvent(QEvent.Type.ActivationChange))
    started = []
    held = world.registry.submit("indexer", C.INDEX_LABEL, lambda j: started.append(j), automatic=True)
    QTest.qWait(100)
    assert not world.controller.called("controller.request")
    assert (len(world.automation.called("automation.activated")),
            len(world.chores.called("chores.activated"))) == activated
    assert held.state == "waiting" and held.reason == strings.QUIT_HELD and started == []
    write.finish()
    assert wait_until(lambda: not world.win.isVisible())
    assert started == []


def test_closing_with_an_anki_write_that_never_started_closes_at_once(world):
    """E20: a `wait` job still waiting for its turn (behind Connect's miner on Anki's writer) has nothing to finish —
    the window closes at once, and the quit drops it."""
    world.start()
    world.registry.submit("mine", "Mining", lambda j: None, on_quit="detach")
    queued = _anki_write(world.registry)
    assert _bar_shows(world, "Mining") and queued.state == "waiting"
    world.win.close()
    assert not world.win.isVisible()


def test_the_window_closes_by_itself_at_the_cap_and_the_quit_waits_no_longer(world, monkeypatch):
    """E20's bound (`QUIT_FINISH_WAIT`: a hung Anki): the window closes by itself at the
    cap, and the quit after it doesn't wait the cap a second time."""
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 1.0)
    world.start()
    write = _anki_write(world.registry)                                       # never ends by itself
    assert _bar_shows(world, A.JUNBAN_LABEL)
    t0 = time.monotonic()
    world.win.close()
    assert world.win.isVisible()
    assert wait_until(lambda: not world.win.isVisible(), 5)
    assert time.monotonic() - t0 >= 0.9
    t1 = time.monotonic()
    world.services.shutdown(0.1)
    assert time.monotonic() - t1 < 0.6 and write.state == "running"         # its time was spent with the window up
    assert world.log.count("updates.quit") == 1                               # the quit began once, at the close
    write.finish()


def _services_only(log):
    """The window's services with stand-in duties, started, and no window: what `main` runs once the window's loop
    ended."""
    registry = JobRegistry()
    services = shell.Services(registry=registry, status=StatusService(registry, reader=QuietReader()),
                              controller=FakeController(log), updates=FakeUpdates(log),
                              automation=FakeAutomation(log), chores=FakeChores(log))
    assert services.start()
    return services


def test_the_quit_waits_for_an_anki_write_past_its_short_timeout(qapp):
    """IK-22 / HR-22 (E20): with no wait of the window's before it (the update's hand-over closes at once), `shutdown`
    still lets a running Anki write finish its batch — up to `QUIT_FINISH_WAIT`, past the short `timeout` it gives the
    rest — before the process goes on to end."""
    log = []
    services = _services_only(log)
    write = services.registry.submit("junban", A.JUNBAN_LABEL, lambda j: threading.Timer(0.5, j.finish).start(),
                                     automatic=True, on_quit="wait")
    services.shutdown(0.05)
    assert write.state == "done" and not write.cancelled


def test_quit_never_waits_on_a_close_chore_that_never_returns(qapp, monkeypatch):
    """F.md (`shutdown` joined the duties' close with no bound): a chore of the close that hangs (Koe's stop, Connect's
    `at_close`) would keep a windowless process — and the single-instance claim — for ever. The quit goes on at
    `QUIT_CLOSE_WAIT`, and the claim still goes."""
    monkeypatch.setattr(shell, "QUIT_CLOSE_WAIT", 0.3)
    log, never, released = [], threading.Event(), []
    services = _services_only(log)
    monkeypatch.setattr(services.chores, "close", lambda *a, **k: never.wait())
    quitting = threading.Thread(target=services.shutdown, args=(0.1,), kwargs={"release": lambda: released.append(1)},
                                daemon=True)
    quitting.start()
    quitting.join(3.0)
    hung = quitting.is_alive()
    never.set()
    assert not hung and released == [1]


def test_the_close_chores_cap_counts_from_the_quits_start(qapp, monkeypatch):
    """The quit's close cap (`QUIT_CLOSE_WAIT` from the quit's start): the duties' close runs beside the wait for an Anki write, so a hung
    close chore and a write finishing its batch keep the claim for the longer of the two — never their sum."""
    monkeypatch.setattr(shell, "QUIT_CLOSE_WAIT", 1.0)
    log, never, released = [], threading.Event(), []
    services = _services_only(log)
    monkeypatch.setattr(services.chores, "close", lambda *a, **k: never.wait())
    write = services.registry.submit("junban", A.JUNBAN_LABEL, lambda j: threading.Timer(1.0, j.finish).start(),
                                     automatic=True, on_quit="wait")
    t0 = time.monotonic()
    try:
        services.shutdown(0.05, release=lambda: released.append(time.monotonic() - t0))
    finally:
        never.set()
    assert write.state == "done" and len(released) == 1 and released[0] < 1.6, released


def test_quit_lets_the_claim_go_before_the_stores_close_and_never_waits_on_a_hung_one(qapp, monkeypatch):
    """F.md: the store's close trigger (`maintain_at_close`, as the Tk `on_closing` runs it: an export took 6.7–14.5 s
    at 100k items) ran with the single-instance claim held, so a start meanwhile waited for it and gave up after 10 s
    with no window. The claim goes once the settings are written, before that trigger; a trigger that never returns
    keeps the process `QUIT_STORE_WAIT` at most."""
    from app import path_utils
    from app.qt import single
    monkeypatch.setattr(shell, "QUIT_STORE_WAIT", 0.5)
    log, free, never = [], [], threading.Event()
    services = _services_only(log)
    first = single.SingleInstance()
    assert first.claim([])

    def hung_store_close():
        log.append("store close")
        lock = path_utils.try_lock(first.lock_file)                     # what a new start takes to become the first
        free.append(lock is not None)
        path_utils.release_lock(lock)
        never.wait()

    monkeypatch.setattr(services.chores, "close_store", hung_store_close)
    monkeypatch.setattr(services.settings, "flush", lambda timeout=None: log.append("settings") or True)
    t0 = time.monotonic()
    try:
        services.shutdown(0.1, release=lambda: (log.append("release"), first.release()))
        took = time.monotonic() - t0
    finally:
        never.set()
        first.release()
    assert free == [True]
    assert log.index("settings") < log.index("release") < log.index("store close")
    assert took < 3.0


def test_main_hands_its_claim_to_the_quit_before_the_stores_close_trigger(qapp, monkeypatch):
    """Main's order: `main` gives its single-instance claim to `shutdown`, which lets it go once the settings are
    written and before the store's close trigger (seconds at 100k items) — so a start meanwhile opens its window
    instead of giving up after `WAIT_FOR_FIRST_S` with none."""
    import sys
    from app import path_utils
    from app.qt import single
    made, free = [], []

    class Claim(single.SingleInstance):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    class QuittingServices:
        def shutdown(self, timeout=2.0, release=None):
            if release is not None:
                release()                                   # the settings written: the claim goes here
            lock = path_utils.try_lock(made[0].lock_file)   # the store's close trigger: what a new start takes
            free.append(lock is not None)
            path_utils.release_lock(lock)

    class Window:
        class first_frame:
            @staticmethod
            def connect(_slot): pass

        def start_duties(self): pass
        def show_first(self): pass

    monkeypatch.setattr(single, "SingleInstance", Claim)
    monkeypatch.setattr(shell, "Services", QuittingServices)
    monkeypatch.setattr(shell, "open_window", lambda app, services: Window())
    monkeypatch.setattr(shell, "connect_instance", lambda window, instance: None)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.delenv("SURASURA_SHELL_PROBE", raising=False)
    monkeypatch.delenv("SURASURA_HUD", raising=False)
    hook, interval = sys.excepthook, sys.getswitchinterval()
    try:
        assert shell.main(["claim-test"]) == 0
    finally:
        sys.excepthook, _ = hook, sys.setswitchinterval(interval)
        for claim in made:
            claim.release()
    assert len(made) == 1 and free == [True]


def test_junbans_line_and_the_update_that_landed_are_said_once(world, monkeypatch):
    """IK-23 (the Tk `_on_junban_auto`: never the same line twice running; `reconcile_update_result`: *Updated to
    v… ✓*): one toast each, never repeated by a state that didn't change them."""
    said = []
    monkeypatch.setattr(world.win.toasts, "show", lambda message, **kw: said.append(message))
    world.automation.push(junban="順 (automatic): 12 cards moved")
    assert wait_until(lambda: said == ["順 (automatic): 12 cards moved"])
    world.automation.push(sync=A.SYNCED, known=40)                 # the same line in a newer state: not again
    world.updates.push(updated="99.0")
    assert wait_until(lambda: len(said) == 2)
    assert said[1] == strings.UPDATED.format(version="99.0")
    world.updates.push(state=U.NONE)
    world.automation.push(junban="順 (automatic): choose one deck")
    assert wait_until(lambda: len(said) == 3)
    QTest.qWait(30)
    assert said[2] == "順 (automatic): choose one deck" and len(said) == 3


def test_the_level_is_read_again_only_after_what_it_reads(world, monkeypatch):
    """IK-28 (S19): a `logic` write the level doesn't read (the names switch, phrase rows) never reads the token store
    again; the selection does."""
    reads = []
    monkeypatch.setattr(world.services, "level", lambda: reads.append(1) or ("rare", False))
    world.start()
    assert wait_until(lambda: reads)
    before = len(reads)
    world.services.settings.set({"logic.ignore_names": True}, now=True)
    QTest.qWait(80)
    assert len(reads) == before
    world.services.settings.set({"logic.selection.band": "rare"}, now=True)
    assert wait_until(lambda: len(reads) == before + 1)


def test_a_duty_failure_leaves_the_bar_once_it_is_over(world):
    """HR-23 (E10: `failed` in the bar while it is): a Generate that runs cleanly again, and an update failure looked
    at in Needs you, take their line off the bar (both stay listed)."""
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).", log_path="gen.log")
    assert wait_until(lambda: world.win.bar_failure.isVisibleTo(world.win))
    world.controller.push(state=G.RUNNING, step="Reading your files")
    world.controller.push(state=G.CURRENT)
    assert wait_until(lambda: not world.win.bar_failure.isVisibleTo(world.win))
    failure = U.Failure("The automatic update didn't finish.", 0.0, False, "99.0", "")
    world.updates.push(state=U.FAILED, message=failure.text, version="99.0", needs_you=(failure,))
    assert wait_until(lambda: "didn't finish" in world.win.bar_failure.full())
    world.updates.push(needs_you=(failure._replace(seen=True),))      # looked at (`mark_seen`)
    assert wait_until(lambda: not world.win.bar_failure.isVisibleTo(world.win))


def test_the_update_hands_over_and_the_window_closes(world, monkeypatch):
    quits = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append(True)))
    threading.Thread(target=world.services._ask_quit).start()      # the service's on_quit, on its worker
    assert wait_until(lambda: quits and not world.win.isVisible())


# --- the final review's fixes: the quit, Needs you, the bridge ---------------------------------------------------- #
class _Analyzer:
    """A scripted analyzer child for a real Generate controller: the test feeds its lines and ends it."""
    returncode = None

    def poll(self):
        return self.returncode


def _line(record):
    import json
    return json.dumps(record) + "\n"


def _writing_generate(registry):
    """A real Generate controller on `registry` whose run has told it *Writing your list* (past its cancel point)."""
    controller = G.GenerateController(registry, settle=0)
    holder = {}

    def launcher(run):
        holder["run"] = run
        run.started(_Analyzer())
    controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launcher)
    assert wait_until(lambda: "run" in holder)
    holder["run"].feed(_line({"type": "progress", "step": "Writing your list", "done": None, "total": None}))
    return holder["run"]


def test_closing_while_generate_writes_your_list_keeps_the_window_until_it_ends(world):
    """E20 ("Generate is cancelled cleanly (the last good journey kept)"): a Generate past its cancel point can't stop,
    and the process's exit would cut it between the list and the journey (its output pipe closes). The window stays
    with one line, as for an Anki write, and closes by itself when the run ends."""
    world.start()
    run = _writing_generate(world.registry)
    assert _bar_shows(world, "Writing your list")
    world.win.close()
    assert world.win.isVisible()
    assert world.win.bar_line.full() == strings.QUIT_FINISHING_LIST
    QTest.qWait(60)
    assert not run.job.cancelled and run.job.state == "running"
    run.feed(_line({"type": "result", "contract": 1, "ok": True, "ran": True}))
    run.ended(0)
    assert wait_until(lambda: not world.win.isVisible())


def test_while_the_window_waits_at_quit_generate_and_the_update_sheet_are_off(world):
    """No control that does nothing: while the window waits for a write to end, Generate's click and *Update now*
    are refused (nothing new starts) — so the header's Generate and the update sheet's actions are disabled."""
    world.start()
    _offer(world)
    assert wait_until(lambda: not world.d.update_mark.isHidden())
    world.win.open_update_sheet()
    assert wait_until(lambda: world.d.sheet.isVisible())
    write = _anki_write(world.registry)
    assert _bar_shows(world, A.JUNBAN_LABEL)
    assert world.d.generate.button.isEnabled() and world.d.sheet.buttons["start"].isEnabled()
    card_starts = [b for b in world.d.cards.findChildren(QPushButton) if b.property("action") == "start"]
    assert card_starts and all(b.isEnabled() for b in card_starts)      # Needs you's *Install the update*
    world.win.close()
    assert world.win.isVisible()
    assert not world.d.generate.button.isEnabled()
    assert not world.d.sheet.buttons["start"].isEnabled() and not world.d.sheet.buttons["skip"].isEnabled()
    assert not any(b.isEnabled() for b in card_starts)
    world.controller.push(state=G.STALE)                             # a new state never turns it back on
    QTest.qWait(30)
    assert not world.d.generate.button.isEnabled()
    write.finish()
    assert wait_until(lambda: not world.win.isVisible())


def test_opening_needs_you_marks_a_generate_failure_seen_and_keeps_it_listed(world):
    """P1.2-1 (E10): a failure looked at stops counting. Opening Needs you marks the bar's failures seen — Generate's
    and the command line's, not only the update's — so the badge goes to 0 while the entry stays listed."""
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).", log_path="gen.log")
    needs = world.win.tab_buttons["needs"]
    assert wait_until(lambda: needs.count == 1)
    world.win.show_tab("needs")
    assert wait_until(lambda: needs.count == 0)
    assert not needs.isHidden()
    assert [e.text for e in world.status.snapshot().needs_you] == ["Generate stopped (exit code 1)."]


def test_an_update_failures_logs_button_opens_the_folder_its_report_is_in(world, monkeypatch, tmp_path):
    """The update's report is written beside the install (`updater.report_path`), not in the logs folder: *Open the
    logs folder* on its Needs you card, and the bar's while the failure is the bar's, open the report's folder."""
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path), raising=False)
    (tmp_path / "logs").mkdir()
    world.status.refresh()
    report = tmp_path / "debug" / "update_report.txt"
    failure = U.Failure("The automatic update didn't finish (exit code 3).", 0.0, False, "99.0", str(report))
    world.updates.push(state=U.FAILED, message=failure.text, version="99.0", needs_you=(failure,))
    cards = world.d.cards
    assert wait_until(lambda: len(cards.cards) == 1 and "didn't finish" in world.win.bar_failure.full())
    buttons = {b.text(): b for b in cards.cards[0].findChildren(QPushButton)}
    buttons[strings.BAR_LOGS].click()
    assert wait_until(lambda: world.win.logs_button.isVisibleTo(world.win))
    world.win.logs_button.click()
    if os.name == "nt":
        assert wait_until(lambda: len(opened) == 2)
        assert opened == [str(tmp_path / "debug")] * 2


def test_after_the_window_closed_a_duty_change_reaches_none_of_its_slots(world, monkeypatch):
    """At quit `shutdown` runs on the window's thread after its loop ended, so a service's callback then reaches the
    window's slots directly: a Generate dropped at quit would start a journey look and a token-store read as the
    process exits. Once the window is closed, nothing a service says reaches it."""
    reads = []
    monkeypatch.setattr(world.services, "journey_exists", lambda: reads.append("journey") or False)
    monkeypatch.setattr(world.services, "level", lambda: reads.append("level") or ("rare", False))
    world.win.close()
    assert not world.win.isVisible()
    for state in (G.State(G.RUNNING, "Counting words", 1, 2, None, None, 1, 50),
                  G.State(G.STALE, None, None, None, None, None, None, 51)):
        for callback in list(world.controller.subscribers):
            callback(state)                                         # on this (the window's) thread, as at quit
    QTest.qWait(80)
    assert reads == []


def test_the_quit_wait_ends_before_a_new_start_stops_waiting_for_the_claim():
    """A start while the window waits at quit finds the claim free in time: the wait's cap is under the next start's
    `WAIT_FOR_FIRST_S`, and within E20's "a few seconds"."""
    from app.qt import single
    assert shell.QUIT_FINISH_WAIT <= 8.0 and shell.QUIT_FINISH_WAIT < single.WAIT_FOR_FIRST_S


def test_a_start_after_the_quit_began_starts_no_duty(qapp):
    """A close in the moment the duties are being made: the window's `ready` asks `start()` after the quit began —
    nothing starts (the update's last outcome isn't consumed, no chore's timer is armed)."""
    log = []
    registry = JobRegistry()
    services = shell.Services(registry=registry, status=StatusService(registry, reader=QuietReader()),
                              controller=FakeController(log), updates=FakeUpdates(log),
                              automation=FakeAutomation(log), chores=FakeChores(log))
    assert services.begin_quit()
    assert services.start() is False
    assert not [n for n in log if n in ("updates.begin", "automation.started", "chores.started", "controller.check")]
    services.shutdown(0.1)
    assert "chores.close" not in log


class _Timer:
    def __init__(self, delay, call):
        self.delay, self.call, self.cancelled = delay, call, False

    def cancel(self):
        self.cancelled = True


def test_a_close_in_the_first_seconds_spawns_nothing(qapp, monkeypatch, tmp_path):
    """The chores' start-up timers (the store's helper at 1.5 s, Connect's notice at 2.5 s) are taken back as the quit
    begins — the window may stay up a while for a write — and one already ringing does nothing: no helper is spawned
    for a window that is closing."""
    import sys
    from app import library_store, path_utils, token_index
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    monkeypatch.setattr(path_utils, "write_install_note", lambda *a, **k: None)
    monkeypatch.setattr(token_index, "prepare_preview", lambda *a, **k: None)
    looked = []
    monkeypatch.setattr(library_store, "check_mode", lambda *a, **k: looked.append(1) or ("none", ""))
    monkeypatch.setattr(library_store, "maintain_at_close", lambda language: None)
    timers, log = [], []
    registry = JobRegistry()
    services = shell.Services(registry=registry, status=StatusService(registry, reader=QuietReader()),
                              controller=FakeController(log), updates=FakeUpdates(log),
                              automation=FakeAutomation(log))
    services.chores = C.Chores(registry, services.settings, "ja", update_staged=lambda: False,
                               timer=lambda delay, call: timers.append(_Timer(delay, call)) or timers[-1],
                               log_folder=str(tmp_path / "logs"))
    assert services.start()
    armed = list(timers)
    assert C.START_MAINTAIN in [t.delay for t in armed]
    services.begin_quit()
    assert all(t.cancelled for t in armed)
    for t in armed:
        t.call()                                                    # one that rang just as the quit began
    assert services.chores.worker.idle(5)
    assert looked == []
    services.shutdown(0.1)


def test_a_language_switch_after_the_quit_began_reaches_no_duty(qapp):
    """E20: once the quit began (the window may still be up), a language switch asks no duty for anything."""
    log = []
    services = _services_only(log)
    services.begin_quit()
    services.language_changed("zh")
    assert "automation.language_changed" not in log and "chores.language_changed" not in log
    services.shutdown(0.1)
