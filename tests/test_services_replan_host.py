"""The re-order host and the journey keeper in 3.0's window (W3.5 row 7, R7a): `app/services/replan_host.py`.

What a wrong answer would cost a learner:
  * Anki's order written behind their back with Surasura's automation off (D29) — or a Generate started for it;
  * two re-orders after one Generate, or a correction lost (E2.2's overlap tests: two new plans in flight, a move
    during a correction — its RUNBOOK's done condition for this step);
  * a write to the deck of the language they just left;
  * an update that waits on (or ends) a helper writing to Anki, or a write cut in half at quit.

The host is a stand-in recording each call (`_Opener`), or `replan_preview.Host` itself in this process with its job
replaced by one the test holds (`_HeldJobs`, the overlap tests), or — for the `_force` path — the real job on a real
generated Japanese library and Junban's fake Anki, as `tests/test_replan_preview.py` runs it. The keeper is Haya's real
`JourneyKeeper` on the real controller and registry; its Generate is a launcher that records each run.
`replan_preview.automation_on` (worker K's 3.0 predicate) is replaced by its rule's shape where a test is about the
wiring, not the predicate (`_gate`).
"""
import os
import threading
import time

import pytest

from app import replan_preview
from app.services import journey as J
from app.services import replan_host as R
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from app.services.library_reader import LibraryReader
from tests import services_helpers as h
from tests.fixtures import window_seed


# --- stand-ins --------------------------------------------------------------------------------------------------- #
class _Settings:
    """The settings service's shape: `get`, `automation` (D29's `logic.automation`, default on)."""

    def __init__(self, **values):
        self.values = {"target_language": "ja", "journey_settle_s": 0, "enable_junban": True,
                       "junban_deck": "Mining", "junban_replan_language": "ja", "junban_replan_deck": "Mining"}
        self.values.update(values)

    def get(self):
        return dict(self.values)

    def automation(self):
        return (self.values.get("logic") or {}).get("automation", True) is not False


@pytest.fixture
def gate(monkeypatch):
    """`automation_on`'s shape (D29 on, Junban on and installed, the (language, deck) pair recorded and holding) and the update's lock
    (`staged["now"]`). The real predicate is worker K's, tested with replan_preview."""
    staged = {"now": False}

    def automation_on(settings, language):
        return ((settings.get("logic") or {}).get("automation", True) is not False
                and settings.get("enable_junban") is True
                and settings.get("junban_replan_language") == language
                and bool(settings.get("junban_replan_deck"))
                and settings.get("junban_replan_deck") == settings.get("junban_deck"))
    monkeypatch.setattr(replan_preview, "automation_on", automation_on, raising=False)
    monkeypatch.setattr(replan_preview, "_update_staged", lambda: staged["now"])
    # Junban installed, whatever this checkout holds (GitHub's has no `modules/`): the bar's stand-aside line needs it
    monkeypatch.setattr(replan_preview, "junban_present", lambda: True)
    return staged


class _Host:
    """A host recording every call; `busy_for(n)` keeps it busy for its next n looks (`busy()` answering True, each
    one recorded as "busy" among the calls) — never a wall clock; its window's callbacks kept."""

    def __init__(self, language, say, working, generate):
        self.language, self.say, self.working, self.generate = language, say, working, generate
        self.calls = []
        self.looks = 0

    def poke(self): self.calls.append("poke")
    def catch_up(self): self.calls.append("catch_up")
    def after_generate(self): self.calls.append("after_generate")
    def close(self): self.calls.append("close")
    def stop(self): self.calls.append("stop")

    def busy(self):
        if self.looks <= 0:
            return False
        self.looks -= 1
        self.calls.append("busy")
        return True

    def busy_for(self, looks):
        self.looks = looks


class _Opener:
    def __init__(self):
        self.hosts = []

    def __call__(self, language, say=None, working=None, generate=None):
        host = _Host(language, say, working, generate)
        self.hosts.append(host)
        return host


class _HeldJobs:
    """`replan_preview.Host` in this process, its job replaced: each job records its kind, writes (the host's own
    `working` — the registry's `replan` job) and waits until the test lets it go (`gate`)."""

    def __init__(self):
        self.kinds = []
        self.hosts = []
        self.gate = threading.Event()
        self.running = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, language, say=None, working=None, generate=None):
        host = replan_preview.Host(language, say=say, working=working, generate=generate)

        def job(kind):
            with self.lock:
                self.kinds.append(kind)
            host._working(True)
            self.running.set()
            try:
                self.gate.wait(10)
            finally:
                host._working(False)
        host._job = job
        host._sync_step = lambda force=False: None      # S3 is the host's own: nothing to sync here
        host._refresh_web = lambda: None
        self.hosts.append(host)
        return host

    def count(self):
        with self.lock:
            return len(self.kinds)


class _Child:
    returncode = None

    def poll(self):
        return self.returncode


class _Launches:
    """The controller's launcher: records each run; the test ends it."""

    def __init__(self):
        self.runs = []
        self.lock = threading.Lock()

    def __call__(self, run):
        run.cancel_file = os.path.join(h.root(), f"replan-cancel-{len(self.runs)}.flag")
        with self.lock:
            self.runs.append(run)
        run.started(_Child())

    def count(self):
        with self.lock:
            return len(self.runs)


class _Plan:
    """A loaded plan's stand-in: what the keeper reads of one (its header)."""

    def __init__(self, signature, language="ja"):
        self.header = {"run_signature": signature, "language": language, "order_free_signature": "f"}


class _Arrivals:
    def __init__(self, language="ja"):
        self.language = language
        self.reloads = 0

    def reload(self, callback=None):
        self.reloads += 1


@pytest.fixture
def fired(monkeypatch):
    """Each keeper's timer that fired and ended (not re-armed): `fired.done(keeper)` — its newest arming has fired, so
    its `asked` counter is final for now. A test asserts on the counter after that, never after a sleep."""
    done = []
    real = J.JourneyKeeper._fire

    def fire(keeper, armed):
        try:
            real(keeper, armed)
        finally:
            done.append((keeper, armed))

    class Fired:
        @staticmethod
        def done(keeper, seconds=10):
            return h.until(lambda: (keeper, keeper._armed) in done, seconds=seconds)
    monkeypatch.setattr(J.JourneyKeeper, "_fire", fire)
    return Fired


@pytest.fixture
def landed(monkeypatch):
    """Each finished Generate's plan read by the keeper, handed on or not (`_landed` ended, on its own thread):
    `landed.count()`. A test waits until the count says its runs were looked at, never on a sleep."""
    done = []
    real = J.JourneyKeeper._landed

    def land(keeper, previous):
        try:
            real(keeper, previous)
        finally:
            done.append(keeper)

    class Landed:
        @staticmethod
        def count():
            return len(done)
    monkeypatch.setattr(J.JourneyKeeper, "_landed", land)
    return Landed


def _replan(settings=None, opener=None, language="ja", pending=lambda language: False, journey=lambda: True):
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    launches = _Launches()
    opener = opener if opener is not None else _Opener()
    replan = R.Replan(registry, controller, settings or _Settings(), language, opener=opener, pending=pending,
                      keeper_options={"launcher": launches, "pending": journey, "battery": lambda: False,
                                      "plan_path": os.path.join(h.root(), "no-plan.json.gz")})
    return replan, registry, controller, launches, opener


def _quiet(replan, seconds=5):
    assert replan.host.worker.idle(seconds)


def _replans(registry):
    return [v for v in registry.snapshot() if v.kind == "replan"]


@pytest.fixture
def plans(monkeypatch):
    """The plan each finished Generate leaves (the keeper reads it): `plans.now = "run-2"` before the run ends."""
    class Plans:
        now = "run-1"
    monkeypatch.setattr(J, "_load_plan", lambda path: _Plan(Plans.now))
    monkeypatch.setattr(J, "_lists", lambda: {})
    monkeypatch.setattr(J, "shadow", lambda previous, plan, lists, stamp=False: "")
    return Plans


def _users_generate(controller, launches, signature, plans):
    """A Generate the user pressed, finished with a plan of `signature`."""
    n = launches.count()
    plans.now = signature
    controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == n + 1, seconds=5)
    launches.runs[n].ended(0)


# --- D29 off: nothing --------------------------------------------------------------------------------------------- #
def test_automation_off_makes_no_host_asks_no_generate_and_writes_nothing_but_still_rebaselines(gate, plans, fired):
    """D29 off (Haya G2c): no host is opened by the start, focus, a store change or a Generate's end; the keeper asks
    for no Generate; nothing is recorded as writing — and the keeper still re-baselines New arrivals after the user's
    own Generate."""
    settings = _Settings(logic={"automation": False})
    replan, registry, controller, launches, opener = _replan(settings, pending=lambda language: True)
    arrivals = replan.arrivals = _Arrivals()
    replan.start()
    replan.activated()
    replan.store_moved("ja", {"order_version": 9})
    _quiet(replan)
    assert fired.done(replan.keeper)                      # the keeper's look after the moves ran to its end
    assert replan.keeper.asked == 0 and launches.count() == 0, "a background Generate with automation off"
    _users_generate(controller, launches, "run-1", plans)
    assert h.until(lambda: arrivals.reloads == 1, seconds=5)
    _quiet(replan)
    assert opener.hosts == [] and replan.host.opened == 0
    assert _replans(registry) == []
    replan.finish(time.monotonic() + 1)


def test_the_switch_is_read_every_time_and_turning_it_off_lets_the_host_go(gate):
    """Never cached: on, a host opens; switched off (D29) the next call lets it go and opens nothing; on again, a new
    one opens."""
    settings = _Settings()
    replan, _registry, _c, _l, opener = _replan(settings)
    replan.activated()
    _quiet(replan)
    assert len(opener.hosts) == 1 and opener.hosts[0].calls == ["catch_up"]
    settings.values["logic"] = {"automation": False}
    replan.activated()
    _quiet(replan)
    assert opener.hosts[0].calls == ["catch_up", "stop"] and len(opener.hosts) == 1
    settings.values["logic"] = {"automation": True}
    replan.activated()
    _quiet(replan)
    assert len(opener.hosts) == 2 and opener.hosts[1].calls == ["catch_up"]
    replan.finish(time.monotonic() + 1)


# --- the start --------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("pending", [True, False])
def test_the_start_catches_up_once_and_asks_for_the_journey_only_when_the_store_says_it_is_pending(gate, pending,
                                                                                                    fired):
    """The map's fix 5: `catch_up` always (the host checks the versions and new cards itself), and `changed("start")`
    only when the store's `journey_pending()` — so one start is one catch-up and at most one background Generate."""
    looked = []
    replan, _registry, _c, launches, opener = _replan(
        pending=lambda language: looked.append(language) or pending)
    replan.start()
    _quiet(replan)
    assert looked == ["ja"]
    assert len(opener.hosts) == 1 and opener.hosts[0].calls == ["catch_up"]
    if pending:
        assert h.until(lambda: launches.count() == 1, seconds=5)
        assert fired.done(replan.keeper)
    assert replan.keeper.asked == (1 if pending else 0)
    assert launches.count() == (1 if pending else 0)
    assert all(run.quiet for run in launches.runs)
    replan.finish(time.monotonic() + 1)


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
def test_the_starts_journey_look_waits_for_a_generate_that_runs_or_waits(gate, monkeypatch, state):
    """The start and a language switch look at the journey (`changed("start")` when the store says it is pending). While
    a Generate runs or waits its turn the keeper hears it but asks for nothing and withdraws nothing (a7): its look
    comes once that run has ended (one change, never two Generates)."""
    from types import SimpleNamespace
    from app.services import generate as G
    replan, _registry, controller, launches, opener = _replan(pending=lambda language: True)
    monkeypatch.setattr(controller, "state", lambda: SimpleNamespace(state=getattr(G, state)))
    replan.start()
    _quiet(replan)
    assert opener.hosts[0].calls == ["catch_up"]
    assert replan.keeper.reasons == ["start"] and replan.keeper._again == "start" and launches.count() == 0
    replan.language_changed("zh")
    _quiet(replan)
    assert replan.keeper.reasons == ["start"] and replan.keeper._again == "start" and launches.count() == 0
    replan.finish(time.monotonic() + 1)


def test_the_store_look_at_start_reads_the_real_store(monkeypatch):
    """`journey_pending` with no library store (a fresh profile) is False, never an error."""
    assert R.journey_pending("ja") is False


# --- a store change ------------------------------------------------------------------------------------------------ #
def test_one_store_change_through_the_reader_is_one_poke_and_one_keeper_change(gate):
    """The map's fix 4, end to end: another program moves the order (a hato drop) → the reader → one poke and one
    `changed("store")`; the reader's next look with nothing new adds nothing; another language's reader is ignored."""
    seed = window_seed.build()
    reader = LibraryReader(seed.opener, language="ja", numbers=seed.numbers, mining=seed.mining, poll=0.02)
    replan, _registry, _c, _launches, opener = _replan()
    changes = []
    real = replan.keeper.changed
    replan.keeper.changed = lambda reason="move": changes.append(reason) or real(reason)
    reader.subscribe_moves(replan.store_moved)
    reader._look()
    seed.library.commit(order=True)
    reader._look()
    reader._look()
    _quiet(replan)
    assert opener.hosts[0].calls == ["poke"] and changes == ["store"]
    replan.store_moved("zh", {"order_version": 3})        # a Chinese reader's move: not this window's language
    _quiet(replan)
    assert opener.hosts[0].calls == ["poke"] and changes == ["store"]
    replan.finish(time.monotonic() + 1)


# --- the host asks for a Generate ------------------------------------------------------------------------------------ #
def test_the_hosts_generate_ask_is_one_background_request(gate, fired):
    """The map's fix 1: one automatic Generate path — the host's ask goes to the keeper (`changed("replan: …")`), which
    settles and asks the controller once, quietly."""
    replan, _registry, _c, launches, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.generate("generate-first: files")
    host.generate("generate-first: files")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert fired.done(replan.keeper)
    assert replan.keeper.asked == 1 and launches.count() == 1 and launches.runs[0].quiet
    # G7 (worker B's stand-in): the keeper's run reads *Journey: updating sentences…* in the bar
    from app.services import generate as G
    assert [v.label for v in _registry.snapshot() if v.kind == "generate"] == [G.JOURNEY_LABEL]
    replan.finish(time.monotonic() + 1)


def test_the_reorder_after_a_generate_comes_from_the_keeper_once_per_new_plan(gate, plans, landed):
    """The map's fix 2: `after_generate` only from the keeper's `on_done` — once per new plan (a run that left the same
    plan re-orders nothing) — and New arrivals' worker of this language re-baselined each time."""
    replan, _registry, controller, launches, opener = _replan()
    arrivals = replan.arrivals = _Arrivals()
    _users_generate(controller, launches, "run-1", plans)
    assert h.until(lambda: arrivals.reloads == 1, seconds=5)
    _users_generate(controller, launches, "run-1", plans)      # the same plan again: nothing handed on
    assert h.until(lambda: landed.count() == 2, seconds=5), "the keeper never read the second run's plan"
    _quiet(replan)
    assert opener.hosts[0].calls == ["after_generate"] and arrivals.reloads == 1
    replan.finish(time.monotonic() + 1)


# --- E2.2's overlap tests -------------------------------------------------------------------------------------------- #
def test_two_new_plans_in_flight_make_one_reorder_and_one_after_it(gate, plans, landed):
    """E2.2 RUNBOOK :58 (two corrections in flight): plan 1 lands → its re-order starts; plans 2 and 3 land while it
    writes → exactly one more re-order after it (the newest plan), never two at once, never a third."""
    held = _HeldJobs()
    replan, registry, controller, launches, _opener = _replan(opener=held)
    seen_live = []
    registry.subscribe(lambda snap: seen_live.append(sum(1 for v in snap if v.kind == "replan"
                                                         and v.state in ("running", "cancelling"))))
    _users_generate(controller, launches, "run-1", plans)
    assert held.running.wait(5)
    _users_generate(controller, launches, "run-2", plans)
    _users_generate(controller, launches, "run-3", plans)
    assert h.until(lambda: landed.count() == 3, seconds=5)   # both plans handed on while the first write runs …
    _quiet(replan)                                          # … and on to the host
    assert held.kinds == ["generate"]
    held.gate.set()
    assert h.until(lambda: held.count() == 2 and not replan.host.busy(), seconds=5)
    _quiet(replan)                                          # nothing pending anywhere: no third job can start
    assert not replan.host.busy()
    assert held.kinds == ["generate", "generate"]
    assert max(seen_live) == 1, "two re-orders ran at once"
    assert [v.state for v in _replans(registry)] == ["done", "done"]
    replan.finish(time.monotonic() + 1)


def test_a_move_during_a_correction_makes_exactly_one_more_job(gate, plans, monkeypatch):
    """E2.2 RUNBOOK :123 (a move during the correction): while the re-order after a Generate writes, the store moves —
    the reader's poke (and a second move in the same settle) → exactly one more job after it, a move."""
    monkeypatch.setattr(replan_preview, "SETTLE_S", 0.1)
    held = _HeldJobs()
    replan, _registry, controller, launches, _opener = _replan(opener=held)
    _users_generate(controller, launches, "run-1", plans)
    assert held.running.wait(5)
    replan.store_moved("ja", {"order_version": 7})
    replan.store_moved("ja", {"order_version": 8})
    _quiet(replan)                                          # both pokes reached the host while its first job writes
    held.gate.set()
    assert h.until(lambda: held.count() == 2 and not replan.host.busy(), seconds=5)
    _quiet(replan)                                          # nothing pending anywhere: no third job can start
    assert not replan.host.busy()
    assert held.kinds == ["generate", "move"]
    replan.finish(time.monotonic() + 1)


def test_the_force_path_a_move_landing_mid_write_runs_exactly_one_more_job(gate, monkeypatch, tmp_path):
    """E2.2 RUNBOOK :123 on the real job (the `_force` path, rp's `_replan`): the re-order after a Generate writes Anki
    while the user moves a file (the store's order moves under the write, and the reader pokes) — after the write the
    host sees the newer order and runs exactly one more job, owed or not; the second job leaves Anki in the store's
    order and records it."""
    pytest.importorskip("modules.junban")
    from modules.junban import reposition
    from modules.junban.tests.test_reposition import _patched
    from tests import test_replan_preview as rp_tests
    root = str(tmp_path / "lib")
    env = rp_tests.cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    rp_tests.cases.build(root, rp_tests.CASE)
    rp_tests._settings_file(root, junban_replan_language="ja", junban_replan_deck=rp_tests.DECK, enable_junban=True)
    from app.path_utils import ensure_data_setup, get_data_path, get_user_files_path
    ensure_data_setup("ja")
    rp_tests._generate(root)
    from app import library_store
    store = library_store.open_store("ja", get_data_path("ja"), get_user_files_path("ja"))
    monkeypatch.setattr(replan_preview, "SETTLE_S", 0.05)
    fake = rp_tests._deck(root)
    kinds = []
    from app.services import settings as settings_service
    registry = JobRegistry()
    replan = R.Replan(registry, GenerateController(registry, settle=0), settings_service.SettingsService(), "ja",
                      keeper_options={"launcher": _Launches(), "pending": lambda: False})   # open_host: in process
    try:
        with _patched(fake):        # held until the host's thread has ended: its loop asks Anki on its own (`_unplaced`)
            try:
                replan.host.catch_up()                          # the ladder laid once (every card), the plan recorded
                assert h.until(lambda: replan.host.opened == 1 and not replan.host.busy(), seconds=30)
                host = replan.host._host
                real_job, real_run = host._job, reposition.run
                monkeypatch.setattr(host, "_job", lambda kind: kinds.append(kind) or real_job(kind))
                moved = []

                def run_with_a_move(settings, **kw):            # the user moves a file while the write is in Anki
                    report = real_run(settings, **kw)
                    if not moved:                               # (a handle of this thread's own: sqlite's rule)
                        other = library_store.open_store("ja", get_data_path("ja"), get_user_files_path("ja"))
                        try:
                            moved.append(rp_tests._move_later_to_top(other))
                            replan.store_moved("ja", other.versions())
                        finally:
                            other.close()
                    return report
                monkeypatch.setattr(reposition, "run", run_with_a_move)
                replan.host.after_generate()                    # the correction after a Generate
                ok = h.until(lambda: len(kinds) >= 2 and not replan.host.busy(), seconds=15)
                assert ok, kinds
                _quiet(replan)
                # Nothing pending, no retry armed: no third job can start.
                assert not replan.host.busy() and host._retry_at is None, (kinds, host._retry_kind)
                assert kinds == ["generate", "move"], kinds
                assert host._force is False and "move" not in host._want
                versions = store.versions()
                assert versions["planned_order_version"] == versions["order_version"]
            finally:
                live = replan.host._host
                replan.finish(time.monotonic() + 5)
                if live is not None and live._thread is not None:
                    live._thread.join(10)
                    assert not live._thread.is_alive(), "the host's thread outlived its finish (and the stand-in)"
    finally:
        store.close()


# --- the write is a job ------------------------------------------------------------------------------------------- #
def test_the_hosts_write_is_one_replan_job_the_registry_sees_and_waits_for_at_quit(gate):
    """`working(True/False)` → one recorded `replan` job (automatic, `on_quit="wait"`: the quit's E20 wait sees it),
    never two for one write, never holding a gated job back; a write said by a host already let go records nothing."""
    replan, registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.working(True)
    host.working(True)
    live = registry.live("replan")
    assert len(live) == 1 and live[0].automatic and live[0].on_quit == "wait" and not live[0].gated
    other = registry.submit("junban", "順", start=lambda job: job.finish(), automatic=True)
    assert other.state == "done", "the recorded write held a gated Anki writer back"
    host.working(False)
    assert registry.live("replan") == () and [v.state for v in _replans(registry)] == ["done"]
    replan.update_state("downloading")                    # the host let go …
    host.working(True)                                    # … its late word records nothing
    assert registry.live("replan") == ()
    replan.finish(time.monotonic() + 1)


def test_a_write_in_hand_when_the_host_goes_leaves_no_job_running(gate):
    replan, registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    opener.hosts[0].working(True)
    replan.language_changed("zh")
    assert registry.live("replan") == ()
    replan.finish(time.monotonic() + 1)


def test_the_last_line_is_kept_and_cleared_when_the_host_goes(gate):
    """`line()` and `on_line` for the bar (worker B's slot): the host's newest line; a passing line is replaced by the
    host's next (it turns *placed* into *up to date* itself); none once the host is let go, and a late line from it is
    never heard."""
    heard = []
    registry = JobRegistry()
    opener = _Opener()
    replan = R.Replan(registry, GenerateController(registry, settle=0), _Settings(), "ja", opener=opener,
                      on_line=heard.append, keeper_options={"launcher": _Launches(), "pending": lambda: False})
    assert replan.line() is None
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.say("Anki: placing tomorrow's 20 cards…")
    host.say(replan_preview.UP_TO_DATE)
    assert replan.line() == replan_preview.UP_TO_DATE
    replan.update_state("downloading")
    host.say("Anki: tomorrow's 20 cards placed · 3 more moved")
    assert replan.line() is None
    assert heard == ["Anki: placing tomorrow's 20 cards…", replan_preview.UP_TO_DATE, None]
    replan.finish(time.monotonic() + 1)


# --- a language switch --------------------------------------------------------------------------------------------- #
def test_a_language_switch_leaves_no_write_to_the_old_deck(gate, monkeypatch):
    """D31: the Japanese host, a settle pending (a move just made), is stopped at the switch — its settle never runs,
    so nothing more reaches the Japanese deck; the old keeper is closed; the Chinese window opens no host while the
    deck is recorded for Japanese (G3); a Japanese reader's late move is ignored."""
    monkeypatch.setattr(replan_preview, "SETTLE_S", 0.3)
    held = _HeldJobs()
    held.gate.set()
    replan, registry, controller, _launches, _opener = _replan(opener=held)
    replan.store_moved("ja", {"order_version": 4})
    _quiet(replan)
    old_keeper, old_host = replan.keeper, held.hosts[0]
    replan.language_changed("zh")
    old_host._thread.join(5)                             # the old host's worker ended: its settle can never run now
    assert not old_host._thread.is_alive()
    replan.store_moved("ja", {"order_version": 5})
    replan.activated()
    _quiet(replan)
    assert held.kinds == [], "a write reached the old deck after the switch"
    assert old_host._stop.is_set() and old_keeper._closed
    assert replan.keeper.language == "zh" and replan.host.language == "zh" and len(held.hosts) == 1
    assert _replans(registry) == []
    replan.finish(time.monotonic() + 1)


def test_a_switch_to_a_language_with_its_deck_recorded_opens_that_languages_host(gate):
    replan, _registry, _c, _l, opener = _replan(_Settings(junban_replan_language="zh"))
    replan.activated()
    _quiet(replan)
    assert opener.hosts == []                            # the deck is recorded for Chinese: the Japanese window stands aside
    replan.language_changed("zh")
    _quiet(replan)
    assert [host.language for host in opener.hosts] == ["zh"] and opener.hosts[0].calls == ["catch_up"]
    replan.finish(time.monotonic() + 1)


@pytest.mark.parametrize("automation", [True, False])
def test_a_language_switch_runs_the_starts_journey_check_whatever_the_new_hosts_gate_says(gate, automation, fired):
    """The new language's store owes its sentences (`journey_pending`) and no deck is recorded for it (its host
    stands aside): the switch still looks, on the worker, as the start does — `changed("start")`; D29 alone decides
    whether that is a Generate (the keeper's `enabled`)."""
    looked = []
    settings = _Settings() if automation else _Settings(logic={"automation": False})
    replan, _registry, _c, launches, opener = _replan(
        settings, pending=lambda language: looked.append(language) or language == "zh")
    replan.language_changed("zh")
    _quiet(replan)
    assert looked == ["zh"], "the switch never looked at the new language's journey"
    assert opener.hosts == []                            # the deck is recorded for Japanese: no Chinese host
    if automation:
        assert h.until(lambda: launches.count() == 1, seconds=5)
        assert launches.runs[0].language == "zh" and launches.runs[0].quiet
    assert fired.done(replan.keeper)                     # the new keeper's look ran to its end
    assert replan.keeper.asked == (1 if automation else 0)
    assert launches.count() == (1 if automation else 0)
    replan.finish(time.monotonic() + 1)


# --- the bar's line when the host stands aside ------------------------------------------------------------ #
def test_a_host_standing_aside_says_why_in_the_bar_and_the_users_own_choices_say_nothing(gate, monkeypatch):
    """A 2.x upgrader who never ticked the preview's box has no (language, deck) pair recorded: with D29 on
    and Junban on and present, the host stands aside — and the bar says why, in `stands_aside`'s words (the deck, or
    D7's one deck), told once per new line (S19). D29 off, Junban off or absent are the user's own choices: no line.
    Once the pair holds, the host opens and the reason goes."""
    heard = []
    registry = JobRegistry()
    opener = _Opener()
    settings = _Settings(junban_replan_language="", junban_replan_deck="")
    replan = R.Replan(registry, GenerateController(registry, settle=0), settings, "ja", opener=opener,
                      on_line=heard.append, pending=lambda language: False,
                      keeper_options={"launcher": _Launches(), "pending": lambda: False})

    def look():
        replan.activated()
        _quiet(replan)
        return replan.line()
    replan.start()
    _quiet(replan)
    deck = "順's deck Mining isn't recorded for Japanese — pick it in 順's window in Japanese"
    assert replan.line() == deck and opener.hosts == []
    assert look() == deck and heard == [deck]            # asked again: the same line, never told again
    settings.values["junban_scope"] = "all"
    one_deck = look()
    assert one_deck == replan_preview.unavailable({"junban_scope": "all"}) and heard == [deck, one_deck]
    settings.values["junban_scope"] = "deck"
    settings.values["enable_junban"] = False
    assert look() is None                                # 順 off: the user's choice
    settings.values["enable_junban"] = True
    settings.values["logic"] = {"automation": False}
    assert look() is None                                # D29 off: the user's choice
    settings.values["logic"] = {"automation": True}
    present = replan_preview.junban_present
    monkeypatch.setattr(replan_preview, "junban_present", lambda: False)
    assert look() is None                                # 順 not installed
    monkeypatch.setattr(replan_preview, "junban_present", present)
    assert look() == deck
    settings.values.update(junban_replan_language="ja", junban_replan_deck="Mining")     # picked in 順: it holds
    assert look() is None and len(opener.hosts) == 1 and opener.hosts[0].calls == ["catch_up"]
    # finish-pending: the user's own choices say no words but are told once, as `OFF` (a press waiting ends quietly);
    # the lines the user can fix are told as lines that give up
    assert heard == [deck, one_deck, replan_preview.OFF, deck, None]
    assert all(isinstance(line, replan_preview.GivesUp) for line in heard[:4])
    replan.finish(time.monotonic() + 1)


# --- the update ---------------------------------------------------------------------------------------------------- #
def test_the_updates_hold_stops_the_host_and_its_end_makes_it_again(gate):
    """*Update now* (the map's G6): the hold lets the host go (its helper would be a Surasura process the update waits
    for); nothing opens while it holds; when the hold ends (cancel, a failed download) a catch-up opens it again — but
    never while the update's lock is still held (the helper would leave the jobs to the window): the next call then."""
    replan, _registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    replan.update_state("downloading")
    assert opener.hosts[0].calls == ["catch_up", "stop"]
    replan.update_state("waiting")                       # still held: nothing new
    replan.store_moved("ja", {"order_version": 3})
    replan.activated()
    _quiet(replan)
    assert len(opener.hosts) == 1
    gate["now"] = True                                   # cancelled mid-download: the lock goes when the download ends
    replan.update_state("available")
    _quiet(replan)
    assert len(opener.hosts) == 1
    gate["now"] = False
    replan.activated()
    _quiet(replan)
    assert len(opener.hosts) == 2 and opener.hosts[1].calls == ["catch_up"]
    replan.update_state("downloading")
    replan.update_state("failed")                        # a download that failed: the hold ends too
    _quiet(replan)
    assert len(opener.hosts) == 3
    replan.finish(time.monotonic() + 1)


def test_a_switch_while_the_update_holds_makes_the_new_host_held(gate):
    replan, _registry, _c, _l, opener = _replan(_Settings(junban_replan_language="zh"))
    replan.update_state("downloading")
    replan.language_changed("zh")
    replan.activated()
    _quiet(replan)
    assert opener.hosts == []
    replan.update_state("available")
    _quiet(replan)
    assert [host.language for host in opener.hosts] == ["zh"]
    replan.finish(time.monotonic() + 1)


# --- quit ---------------------------------------------------------------------------------------------------------- #
def test_quit_mid_run_closes_waits_while_busy_then_stops(gate):
    """The quit (the map's §4): the keeper closed, the host's `close()` (a pending settle and the S3 sync run at once),
    `busy()` waited for, then `stop()` — only once the host said it was no longer busy, inside the deadline."""
    replan, _registry, _c, launches, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.busy_for(3)
    assert replan.finish(time.monotonic() + 30) is True
    assert host.calls == ["catch_up", "close", "busy", "busy", "busy", "stop"]
    assert replan.keeper._closed and replan.host.worker._closed
    replan.store_moved("ja", {"order_version": 9})        # after the quit: nothing — refused where it is asked
    replan.activated()
    assert replan.host.worker.idle(5)
    assert host.calls[-1] == "stop" and host.calls.count("catch_up") == 1
    assert replan.keeper.reasons == [] and replan.keeper._timer is None and launches.count() == 0


def test_quit_never_waits_past_its_deadline_for_a_host_that_stays_busy(gate):
    replan, _registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.busy_for(10 ** 9)                                # busy for good: only the deadline ends the wait
    assert replan.finish(time.monotonic() + 0.3) is False
    assert host.calls[-1] == "stop" and host.looks > 0


def test_the_windows_close_sees_the_host_still_writing(gate):
    """`Replan.busy()` is what the window's close waits on (the shell's `replan_wait`, E20): it answers for the open
    host — True while the host still works, False once it ended."""
    replan, _registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    assert replan.busy() is False
    host.busy_for(2)
    assert replan.busy() is True and replan.busy() is True
    assert replan.busy() is False
    replan.finish(time.monotonic() + 1)


def test_closing_twice_sends_the_hosts_close_once(gate):
    """A second close would ask the S3 sync again (`Host.close` adds it each time)."""
    replan, _registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    replan.closing()
    replan.closing()
    replan.finish(time.monotonic() + 1)
    assert opener.hosts[0].calls.count("close") == 1


def test_the_calls_return_at_once_and_read_nothing_on_the_callers_thread(gate, monkeypatch):
    """The GUI thread may call `poke` / `catch_up` / `after_generate` / `changed`: each queues, never reads the
    settings or the store on the caller's thread. Proved with the host's worker held: every call returns while it
    can't run anything (a call that waited for it would never return), and nothing was read meanwhile."""
    replan, _registry, _c, _l, _opener = _replan()
    me = threading.get_ident()
    readers = []
    real = replan.host._settings
    replan.host._settings = lambda: readers.append(threading.get_ident()) or real()
    held, holding = threading.Event(), threading.Event()
    replan.host.worker.put(lambda: holding.set() or held.wait(30))
    assert holding.wait(5)
    for _ in range(20):
        replan.activated()
        replan.store_moved("ja", {"order_version": 2})
    assert readers == [], "the settings were read on the caller's thread"
    held.set()
    _quiet(replan)
    assert readers and me not in readers
    replan.finish(time.monotonic() + 1)


# --- the last review round ------------------------------------------------------------------------------------------- #
def test_a_deck_picked_in_juns_own_window_reaches_the_gate_at_the_next_catch_up(gate):
    """順 records the (language, deck) pair with its own `save_keys` — straight to settings.json, behind the window's
    settings service, whose copy is read again only after the window's own writes. The gate reads the file on the
    host's worker every time, so the next catch-up (a focus) opens the host and the bar's stand-aside line goes."""
    from app.services import settings as settings_service
    h.write_settings({"target_language": "ja", "journey_settle_s": 0, "enable_junban": True, "junban_deck": "Mining"})
    service = settings_service.SettingsService()
    heard = []
    registry = JobRegistry()
    opener = _Opener()
    replan = R.Replan(registry, GenerateController(registry, settle=0), service, "ja", opener=opener,
                      on_line=heard.append, pending=lambda language: False,
                      keeper_options={"launcher": _Launches(), "pending": lambda: False})
    replan.activated()
    _quiet(replan)
    deck = "順's deck Mining isn't recorded for Japanese — pick it in 順's window in Japanese"
    assert replan.line() == deck and opener.hosts == []
    h.write_settings(dict(h.read_settings(), junban_replan_language="ja", junban_replan_deck="Mining"))  # 順's save
    assert not service.get().get("junban_replan_deck")   # the window's own copy hasn't seen it
    replan.activated()
    _quiet(replan)
    assert len(opener.hosts) == 1 and opener.hosts[0].calls == ["catch_up"]
    assert replan.line() is None and heard == [deck, None]
    replan.finish(time.monotonic() + 1)


@pytest.mark.parametrize("case, values, dropped", [
    ("automation off", {"logic": {"automation": False}}, True),
    ("no deck recorded", {"junban_replan_language": "", "junban_replan_deck": ""}, True),
    ("automation off, Connect on (Connect sends it)", {"logic": {"automation": False}, "connect_enabled": True}, False),
    ("the deck recorded for Chinese (a Chinese host may send it)", {"junban_replan_language": "zh"}, False),
])
def test_with_no_host_to_send_it_and_connect_off_a_pending_anki_sync_is_let_go(gate, case, values, dropped):
    """A spaced 順 run arms the AnkiWeb sync (S3); only the re-order host — its gate holding, in any language — or
    Connect sends it. With neither, the Tk dashboard's rule (`_replan_start`): the pending sync is let go (Anki's own
    sync on close carries the order), on the host's worker, as the host stands aside."""
    from app import anki_sync_rule
    anki_sync_rule.wrote(True)
    assert anki_sync_rule.read_state().get("front_pending") is True
    replan, _registry, _c, _l, opener = _replan(_Settings(**values))
    replan.activated()
    _quiet(replan)
    assert opener.hosts == []
    assert (anki_sync_rule.read_state().get("front_pending") is not True) is dropped, case
    replan.finish(time.monotonic() + 1)


def test_the_hosts_generate_ask_never_withdraws_a_keeper_run_in_flight(gate, fired):
    """A store move → the keeper's background Generate starts; a focus's catch-up then asks for a Generate for the same
    moves (`_journey`'s "moves", or a generate-first ask landing late): routed to the keeper as a move, it withdrew the
    run in flight and started one from scratch — one change, two Generates. With a Generate running or queued the ask
    is left to it (the keeper's `on_done` re-orders after it)."""
    replan, _registry, _c, launches, opener = _replan()
    replan.activated()
    _quiet(replan)
    replan.store_moved("ja", {"order_version": 3})
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert fired.done(replan.keeper)
    run, armed = launches.runs[0], replan.keeper._armed
    opener.hosts[0].generate("moves")
    opener.hosts[0].generate("generate-first: files")
    assert not run.cancel_event.is_set(), "the keeper's run in flight was withdrawn"
    assert replan.keeper._armed == armed and replan.keeper._timer is None      # no second settle armed
    assert replan.keeper.asked == 1 and launches.count() == 1
    run.ended(0)
    replan.finish(time.monotonic() + 1)


def test_a_focus_after_an_outside_placement_asks_for_one_generate(gate, fired):
    """An item placed by another program (the Tk Content Manager, the command line) while this window is open, with no
    library reader to tell it: the store's order moved, nothing else did. A focus runs the start's journey look too:
    the store says the journey is pending → one background Generate; a second focus while it runs asks nothing more."""
    looked = []
    replan, _registry, _c, launches, _opener = _replan(pending=lambda language: looked.append(language) or True)
    replan.activated()
    _quiet(replan)
    assert looked == ["ja"]
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert fired.done(replan.keeper)
    replan.activated()                                   # focus again while that Generate runs
    _quiet(replan)
    assert looked == ["ja", "ja"] and not launches.runs[0].cancel_event.is_set()
    assert replan.keeper.asked == 1 and replan.keeper._timer is None
    replan.finish(time.monotonic() + 1)


def test_a_catch_up_queued_before_the_quit_never_opens_a_helper_during_it(gate):
    """The quit's close is queued behind what the host's worker holds: a focus's catch-up queued just before it opened
    (spawned) a helper during the quit. The close refuses every later open as it is called, not when its turn comes."""
    replan, _registry, _c, _l, opener = _replan()
    held, holding = threading.Event(), threading.Event()
    replan.host.worker.put(lambda: holding.set() or held.wait(30))
    assert holding.wait(5)
    replan.activated()                                   # queued behind the held call
    replan.closing()                                     # the quit begins
    held.set()
    _quiet(replan)
    assert opener.hosts == [] and replan.host.opened == 0
    replan.finish(time.monotonic() + 1)


@pytest.mark.parametrize("settle, settling", [(0.8, True), (0.0, False)])
def test_a_move_just_told_marks_a_settle_maybe_pending_read_with_no_lock(gate, monkeypatch, settle, settling):
    """The window's close asks on its own thread whether a move's settle may still be pending (E20 then keeps the
    window up while it runs): a mark set as the move is told — read with no lock and no wait — for the settle's time."""
    monkeypatch.setattr(replan_preview, "SETTLE_S", settle)
    replan, _registry, _c, _l, _opener = _replan()
    assert replan.settling() is False
    replan.store_moved("ja", {"order_version": 3})
    assert replan.settling() is settling
    replan.finish(time.monotonic() + 1)


# --- W3.5 part 3 (AD-8): the setup wizard holds the keeper ---------------------------------------------------------- #
def test_while_the_setup_wizard_is_up_the_keeper_asks_no_generate_and_its_close_asks_again(gate, fired):
    """An upgrader's library has no journey yet: no quiet Generate before the wizard's last page sets the level. Held,
    a focus after an outside placement asks nothing; released, the next focus (the wizard's close) asks once."""
    up = [True]
    replan, _registry, _c, launches, _opener = _replan(pending=lambda language: True)
    replan.held = lambda: up[0]
    replan.activated()
    _quiet(replan)
    assert fired.done(replan.keeper)
    assert replan.keeper.asked == 0 and launches.count() == 0
    up[0] = False
    replan.activated()
    _quiet(replan)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].ended(0)
    replan.finish(time.monotonic() + 1)


def test_a_level_key_written_starts_the_keepers_quiet_time_again(gate):
    """W3.3's S3: Settings' level rows (and the wizard's level page) reach the journey keeper as a level change."""
    replan, _registry, _c, _launches, _opener = _replan()
    replan.level_changed()
    assert replan.keeper.reasons[-1] == "level"
    replan.finish(time.monotonic() + 1)


# --- finish-pending's fix round (FP-A4): switched off while the window waits for a re-order ------------------------- #
def test_switched_off_with_a_host_open_tells_off_once_with_no_words_and_the_update_hold_tells_no_off(gate):
    """The window's press waiting for a re-order heard nothing when the learner turned automation or 順 off: the host
    was let go with no line. Now `OFF` is told once (no words in the bar: `line()` stays None), not again at the next
    look while it stays off, and again after it was on. An update's hold lets the host go too, but it resumes after:
    no `OFF`."""
    heard = []
    registry = JobRegistry()
    opener = _Opener()
    settings = _Settings()
    replan = R.Replan(registry, GenerateController(registry, settle=0), settings, "ja", opener=opener,
                      on_line=heard.append, pending=lambda language: False,
                      keeper_options={"launcher": _Launches(), "pending": lambda: False})

    def look():
        replan.activated()
        _quiet(replan)
    look()
    assert len(opener.hosts) == 1 and heard == []
    replan.update_state("downloading")
    replan.update_state("idle")
    look()
    assert replan_preview.OFF not in heard
    settings.values["enable_junban"] = False
    look()
    look()
    assert heard.count(replan_preview.OFF) == 1 and replan.line() is None
    settings.values["enable_junban"] = True
    look()
    settings.values["logic"] = {"automation": False}
    look()
    assert heard.count(replan_preview.OFF) == 2
    replan.finish(time.monotonic() + 1)


def test_the_hosts_ask_reaches_the_keeper_even_while_a_generate_runs():
    """a7 (review S1): the keeper never withdraws a run for a change and looks once after it, so the host's asks go to
    it whatever runs — a language switch's start look while the old language's run is being stopped is not lost."""
    from app.services.replan_host import Replan
    asked = []
    keeper = type("K", (), {"generating": lambda self: True, "changed": lambda self, reason: asked.append(reason)})()
    Replan._asker(None, keeper)("start")
    assert asked == ["start"]
