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
    """`automation_on`'s shape (D29 on, Junban on, the (language, deck) pair recorded and holding) and the update's lock
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
    return staged


class _Host:
    """A host recording every call; `busy_for(s)` keeps it busy that long; its window's callbacks kept."""

    def __init__(self, language, say, working, generate):
        self.language, self.say, self.working, self.generate = language, say, working, generate
        self.calls = []
        self.busy_until = 0.0
        self.stopped_at = None

    def poke(self): self.calls.append("poke")
    def catch_up(self): self.calls.append("catch_up")
    def after_generate(self): self.calls.append("after_generate")
    def close(self): self.calls.append("close")

    def stop(self):
        self.calls.append("stop")
        self.stopped_at = time.monotonic()

    def busy(self):
        return time.monotonic() < self.busy_until

    def busy_for(self, seconds):
        self.busy_until = time.monotonic() + seconds


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
def test_automation_off_makes_no_host_asks_no_generate_and_writes_nothing_but_still_rebaselines(gate, plans):
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
    time.sleep(0.8)                                       # past the keeper's first look (0.5 s)
    assert launches.count() == 0, "a background Generate with automation off"
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
def test_the_start_catches_up_once_and_asks_for_the_journey_only_when_the_store_says_it_is_pending(gate, pending):
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
    time.sleep(0.8)
    assert launches.count() == (1 if pending else 0)
    assert all(run.quiet for run in launches.runs)
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
def test_the_hosts_generate_ask_is_one_background_request(gate):
    """The map's fix 1: one automatic Generate path — the host's ask goes to the keeper (`changed("replan: …")`), which
    settles and asks the controller once, quietly."""
    replan, _registry, _c, launches, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.generate("generate-first: files")
    host.generate("generate-first: files")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    time.sleep(0.8)
    assert launches.count() == 1 and launches.runs[0].quiet
    # G7 (worker B's stand-in): the keeper's run reads *Journey: updating sentences…* in the bar
    from app.services import generate as G
    assert [v.label for v in _registry.snapshot() if v.kind == "generate"] == [G.JOURNEY_LABEL]
    replan.finish(time.monotonic() + 1)


def test_the_reorder_after_a_generate_comes_from_the_keeper_once_per_new_plan(gate, plans):
    """The map's fix 2: `after_generate` only from the keeper's `on_done` — once per new plan (a run that left the same
    plan re-orders nothing) — and New arrivals' worker of this language re-baselined each time."""
    replan, _registry, controller, launches, opener = _replan()
    arrivals = replan.arrivals = _Arrivals()
    _users_generate(controller, launches, "run-1", plans)
    assert h.until(lambda: arrivals.reloads == 1, seconds=5)
    _users_generate(controller, launches, "run-1", plans)      # the same plan again: nothing handed on
    time.sleep(0.3)
    _quiet(replan)
    assert opener.hosts[0].calls == ["after_generate"] and arrivals.reloads == 1
    replan.finish(time.monotonic() + 1)


# --- E2.2's overlap tests -------------------------------------------------------------------------------------------- #
def test_two_new_plans_in_flight_make_one_reorder_and_one_after_it(gate, plans):
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
    time.sleep(0.4)                                         # both plans handed on while the first write runs
    assert held.kinds == ["generate"]
    held.gate.set()
    assert h.until(lambda: held.count() == 2 and not replan.host.busy(), seconds=5)
    time.sleep(0.4)
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
    time.sleep(0.3)
    held.gate.set()
    assert h.until(lambda: held.count() == 2 and not replan.host.busy(), seconds=5)
    time.sleep(0.4)
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
        with _patched(fake):
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
            time.sleep(0.5)
        assert kinds == ["generate", "move"], kinds
        assert host._force is False and "move" not in host._want
        versions = store.versions()
        assert versions["planned_order_version"] == versions["order_version"]
    finally:
        replan.finish(time.monotonic() + 5)
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
    time.sleep(0.6)                                      # past the old settle
    replan.store_moved("ja", {"order_version": 5})
    replan.activated()
    _quiet(replan)
    time.sleep(0.2)
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
def test_a_language_switch_runs_the_starts_journey_check_whatever_the_new_hosts_gate_says(gate, automation):
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
    time.sleep(0.8)                                      # past the keeper's first look
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
    assert heard == [deck, one_deck, None, deck, None]
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
    `busy()` waited for, then `stop()` — after the write ended, well inside the deadline."""
    replan, _registry, _c, launches, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.busy_for(0.4)
    t0 = time.monotonic()
    assert replan.finish(t0 + 3.0) is True
    assert host.calls == ["catch_up", "close", "stop"]
    assert host.stopped_at - t0 >= 0.35 and host.stopped_at - t0 < 1.5
    assert replan.keeper._closed
    replan.store_moved("ja", {"order_version": 9})        # after the quit: nothing
    replan.activated()
    time.sleep(0.6)
    assert host.calls == ["catch_up", "close", "stop"] and launches.count() == 0


def test_quit_never_waits_past_its_deadline_for_a_host_that_stays_busy(gate):
    replan, _registry, _c, _l, opener = _replan()
    replan.activated()
    _quiet(replan)
    host = opener.hosts[0]
    host.busy_for(60)
    t0 = time.monotonic()
    assert replan.finish(t0 + 0.3) is False
    assert host.calls[-1] == "stop" and time.monotonic() - t0 < 1.0


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
    settings or the store on the caller's thread."""
    replan, _registry, _c, _l, _opener = _replan()
    me = threading.get_ident()
    readers = []
    real = replan.host._settings
    replan.host._settings = lambda: readers.append(threading.get_ident()) or real()
    t0 = time.perf_counter()
    for _ in range(20):
        replan.activated()
        replan.store_moved("ja", {"order_version": 2})
    assert time.perf_counter() - t0 < 0.05
    _quiet(replan)
    assert readers and me not in readers
    replan.finish(time.monotonic() + 1)
