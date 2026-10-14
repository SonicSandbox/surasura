"""The window's services and the re-order host / journey keeper (W3.5 row 7, R7a: `Services` in app/qt/shell.py).

`Services` only routes — the rules are `app/services/replan_host.py`'s (tests/test_services_replan_host.py). What a
wrong route would cost: a host never made (Anki never follows the moves), made twice, left running across an update
or a language switch, or a quit that cuts a write (or waits past its caps). A `Replan` stand-in records each call; the
other duties are the bar suite's stand-ins.
"""
import threading
import time

from app.qt import shell, strings
from app.services import generate as G
from app.services import replan_host as R
from app.services import updates as U
from app.services.jobs import JobRegistry
from app.services.status import StatusService
from tests.qt.conftest import wait_until
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


def test_a_language_switch_asks_the_bar_for_the_new_languages_line_and_dot_at_once(qapp):
    """After a switch the bar shows the new language's re-order line and journey dot straight away — the two
    slots asked by name once their providers are the new language's (never left until the next full refresh)."""
    replan = _Replan()
    services, _log = _services(replan)
    providers = services.status.providers
    old = providers["journey"]
    asked = []
    services.status.refresh_soon = lambda *names: asked.append((set(names), providers["journey"]))
    services.language_changed("zh")
    assert asked, "nothing asked of the bar after the switch"
    names, journey = asked[-1]
    assert names == {"journey", "replan"} and journey is not old
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
        def failure(self, language=None):
            return "Generate stopped (exit code 1)."
    services, _log = _services(controller=Failing(log))
    assert services.controller.state().state != G.FAILED
    assert services.status.providers["generate"]() == "Generate stopped (exit code 1)."
    services.shutdown(0.05)


# --- the last review round -------------------------------------------------------------------------------------- #
def test_a_focus_asks_the_bar_for_the_journey_dot(qapp):
    """A focus runs the start's journey look (another program may have placed an item: the dot may be owed now), so
    the bar asks for the dot too — not only at the next full refresh."""
    replan = _Replan()
    services, _log = _services(replan)
    asked = []
    services.status.refresh_soon = lambda *names: asked.append(names)
    services.start()
    asked.clear()
    services.activated()
    assert replan.calls[-1] == "activated" and ("journey",) in asked
    services.shutdown(0.05)


def test_a_language_switch_forgets_the_last_languages_generate_failure(qapp):
    """A Japanese Generate failed; the window switches to Chinese: the bar's Generate line is asked for the language
    open (a Japanese failure is never the Chinese bar's), and the switch forgets it."""
    log = []

    class Failing(FakeController):
        kept = ("Generate stopped (exit code 1).", "ja")

        def failure(self, language=None):
            kept = self.kept
            return kept[0] if kept and language in (None, kept[1]) else None

        def forget_failure(self):
            self.kept = None
    services, _log = _services(_Replan(), controller=Failing(log))
    provider = services.status.providers["generate"]
    assert provider() == "Generate stopped (exit code 1)."
    services.language_changed("zh")
    assert provider() is None and services.controller.kept is None
    services.controller.kept = ("Generate stopped (exit code 1).", "ja")     # a Japanese run's failure landing late
    assert provider() is None, "the Chinese bar read a Japanese failure"
    services.shutdown(0.05)


class _Settling(_Replan):
    """A move's settle pending as the window closes: `settling()` says so (no lock); `busy()` is True for `looks`
    more looks (the settle running at the host's close), then False."""

    def __init__(self, settling=True, looks=3):
        super().__init__()
        self._settling, self.looks = settling, looks

    def settling(self):
        return self._settling

    def busy(self):
        self.looks -= 1
        return self.looks >= 0


def test_closing_with_a_move_settling_keeps_the_window_with_one_line_until_the_settle_ran(qapp):
    """A move under 0.8 s old as the user closes: no write job yet, so the window hid at once while the settle and the
    AnkiWeb sync ran windowless for seconds (the claim held). E20's wait now covers it: the window stays with its one
    line, the host's close is sent (the settle runs at once), and the window closes itself once the host is idle."""
    replan = _Settling()
    services, _log = _services(replan)
    win = shell.open_window(qapp, services)
    win.show()
    try:
        win.show_status(services.status.snapshot())
        win.close()
        assert win.isVisible() and win._quit == "waiting"
        assert win.bar_line.full() == strings.QUIT_FINISHING
        assert wait_until(lambda: not win.isVisible())
        assert "closing" in replan.calls and replan.looks < 0
    finally:
        services.shutdown(0.05)


def test_the_quits_wait_for_the_reorder_host_ends_at_its_deadline(qapp, monkeypatch):
    """A host still busy long after the quit began (Anki slow to answer its last write): the wait for it ends at what
    is left of `QUIT_FINISH_WAIT` and says it didn't end, so the quit is never held past its cap."""
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 0.3)
    replan = _Settling(looks=200)                        # 200 looks of 50 ms: 10 s busy, far past the 0.3 s cap
    services, _log = _services(replan)
    try:
        started = time.monotonic()
        assert services.replan_wait() is False
        assert time.monotonic() - started < 5 and replan.looks > 0
    finally:
        services.shutdown(0.05)


def test_closing_with_no_settle_pending_closes_at_once(qapp):
    replan = _Settling(settling=False)
    services, _log = _services(replan)
    win = shell.open_window(qapp, services)
    win.show()
    try:
        win.close()
        assert not win.isVisible() and win._quit is None
    finally:
        services.shutdown(0.05)
