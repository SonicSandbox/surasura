"""The window's services and the re-order host / journey keeper (W3.5 row 7, R7a: `Services` in app/qt/shell.py).

`Services` only routes — the rules are `app/services/replan_host.py`'s (tests/test_services_replan_host.py). What a
wrong route would cost: a host never made (Anki never follows the moves), made twice, left running across an update
or a language switch, or a quit that cuts a write (or waits past its caps). A `Replan` stand-in records each call; the
other duties are the bar suite's stand-ins.
"""
import threading
import time

from app.qt import shell
from app.services import generate as G
from app.services import replan_host as R
from app.services import updates as U
from app.services.jobs import JobRegistry
from app.services.status import StatusService
from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader


class _Replan:
    def __init__(self):
        self.calls = []
        self.deadline = None

    def start(self): self.calls.append("start")
    def activated(self): self.calls.append("activated")
    def store_moved(self, language, versions=None): self.calls.append(("store_moved", language))
    def language_changed(self, language): self.calls.append(("language_changed", language))
    def update_state(self, state): self.calls.append(("update_state", state))
    def closing(self): self.calls.append("closing")
    def line(self): return "Anki: placing tomorrow's 20 cards…"

    def finish(self, deadline):
        self.calls.append("finish")
        self.deadline = deadline
        return True


class _Library:
    def __init__(self):
        self.moves = []

    def subscribe_moves(self, cb):
        self.moves.append(cb)

    def stop(self, timeout=None):
        pass


def _services(replan=None, library=None, controller=None):
    log = []
    registry = JobRegistry()
    status = StatusService(registry, reader=QuietReader())
    services = shell.Services(registry=registry, status=status, controller=controller or FakeController(log),
                              updates=FakeUpdates(log), automation=FakeAutomation(log), chores=FakeChores(log),
                              library=library, replan=replan)
    return services, log


def test_the_window_routes_start_focus_switch_and_store_moves_to_the_replan(qapp):
    """Start → one `start` (the catch-up once); focus → `activated`; a language switch → the new language; the
    reader's version move → `store_moved` and the journey dot asked again; nothing once the quit began."""
    replan, library = _Replan(), _Library()
    services, _log = _services(replan, library)
    asked = []
    services.status.refresh_soon = lambda *names: asked.append(names)
    assert services.start() and not services.start()
    services.activated()
    library.moves[0]("ja", {"order_version": 4})
    services.language_changed("zh")
    assert replan.calls == ["start", "activated", ("store_moved", "ja"), ("language_changed", "zh")]
    assert ("journey",) in asked
    services.begin_quit()
    library.moves[0]("zh", {"order_version": 5})
    services.activated()
    assert replan.calls[-1] == "closing" and ("store_moved", "zh") not in replan.calls
    services.shutdown(0.05)


def test_the_bar_providers_are_registered_and_again_for_a_new_language(qapp):
    """Worker B's providers (`replan`, `connect`, `ankiweb`, `journey`), registered with the replan and again on a
    switch (Connect's line and the dot are per language); the host's new line asks the bar for `replan` alone."""
    replan = _Replan()
    services, _log = _services(replan)
    providers = services.status.providers
    assert {"replan", "connect", "ankiweb", "journey"} <= set(providers)
    assert providers["replan"]() == "Anki: placing tomorrow's 20 cards…"
    journey, connect = providers["journey"], providers["connect"]
    asked = []
    services.status.refresh_soon = lambda *names: asked.append(names)
    services._replan_line("Anki's order is up to date")
    assert asked == [("replan",)]
    services.language_changed("zh")
    assert providers["journey"] is not journey and providers["connect"] is not connect
    services.shutdown(0.05)


def test_the_updates_hold_and_its_end_reach_the_replan(qapp):
    replan = _Replan()
    services, _log = _services(replan)
    services.updates.push(state=U.DOWNLOADING)
    services.updates.push(state=U.AVAILABLE)
    assert replan.calls == [("update_state", "downloading"), ("update_state", "available")]
    services.shutdown(0.05)


def test_quit_closes_the_replan_at_its_start_and_finishes_it_inside_the_close_cap(qapp):
    """The quit's order (part 1's caps): the keeper and the host's close at the quit's start (`_stop_starting`: a
    pending settle runs while the window may still wait for a write, E20), then — on the duties' close thread —
    `finish` with a deadline inside `QUIT_CLOSE_WAIT`, so the host is stopped before the close is given up on."""
    replan = _Replan()
    services, _log = _services(replan)
    services.start()
    t0 = time.monotonic()
    services.shutdown(0.05)
    assert replan.calls.index("closing") < replan.calls.index("finish")
    assert t0 < replan.deadline <= t0 + shell.QUIT_CLOSE_WAIT


def test_a_replan_whose_finish_hangs_never_holds_the_quit_past_its_cap(qapp, monkeypatch):
    monkeypatch.setattr(shell, "QUIT_CLOSE_WAIT", 0.3)
    replan, never = _Replan(), threading.Event()
    replan.finish = lambda deadline: never.wait()
    services, _log = _services(replan)
    released = []
    t0 = time.monotonic()
    try:
        services.shutdown(0.05, release=lambda: released.append(time.monotonic() - t0))
    finally:
        never.set()
    assert released and released[0] < 1.5


def test_make_duties_makes_one_replan_with_a_labelled_keeper(qapp):
    """The duties made after the first paint make the window's replan too (one keeper and one host for the language
    open); its keeper's runs carry *Journey: updating sentences…* (G7)."""
    registry = JobRegistry()
    controller = G.GenerateController(registry, settle=0)
    log = []
    services = shell.Services(registry=registry, status=StatusService(registry, reader=QuietReader()),
                              controller=controller, updates=FakeUpdates(log), automation=FakeAutomation(log),
                              chores=FakeChores(log))
    assert services.replan is None
    services.make_duties()
    assert isinstance(services.replan, R.Replan) and services.replan.language == services.language
    keeper = services.replan.keeper
    assert isinstance(keeper.controller, G.Labelled) and keeper.controller._label == G.JOURNEY_LABEL
    assert "replan" in services.status.providers
    services.shutdown(0.05)


def test_the_generate_failure_provider_reads_the_controllers_kept_failure(qapp):
    """A12 (worker B's ask): a failure stays the bar's while another run already started — read from
    `controller.failure()`, never the state (which reads `queued` then)."""
    log = []

    class Failing(FakeController):
        def failure(self):
            return "Generate stopped (exit code 1)."
    services, _log = _services(controller=Failing(log))
    assert services.controller.state().state != G.FAILED
    assert services.status.providers["generate"]() == "Generate stopped (exit code 1)."
    services.shutdown(0.05)
