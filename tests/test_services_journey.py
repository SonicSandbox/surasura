"""The journey kept current in the background (`app/services/journey.py`) — E3.2, research/17 §2.7 (the debounce).

What a wrong answer would cost:
  * a Generate per move — a burst of twenty drags twenty full runs, the laptop's fan on for minutes;
  * a run that never comes — the report and the sentences stay behind the plan until the user presses Generate;
  * two runs at once, or the user's own Generate cancelled by an automatic one;
  * a run nobody needed — a burst that came back to the analysed order still costs a Generate (S19);
  * the battery drained — on a laptop's battery the quiet time is 30 s (Sonic, E3.2-1), not 3 s;
  * a window that waits — `changed` is called on the window's thread after every move.

A scripted child (a launcher feeding the analyzer's real protocol lines) where the claim is about timing; real Generates
of RP-2's library (Japanese and Chinese) where the claim is that the report then agrees with the plan.
"""
import json
import os
import threading
import time

import pytest

from app.services import generate as G
from app.services import journey as J
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse: the child's store, in-process)

FAST = {"journey_settle_s": 0.2, "journey_settle_battery_s": 0.8}
CANCELLED = json.dumps({"type": "error", "contract": 1, "ok": False, "code": "cancelled", "message": "x"}) + "\n"


def _line(step):
    return json.dumps({"type": "progress", "step": step, "done": None, "total": None}) + "\n"


class _Child:
    returncode = None

    def poll(self):
        return self.returncode


class _Launches:
    """The controller's launcher: records each run (its start time) and lets the test end it."""

    def __init__(self):
        self.runs, self.times = [], []
        self.lock = threading.Lock()

    def __call__(self, run):
        run.cancel_file = os.path.join(h.root(), f"journey-cancel-{len(self.runs)}.flag")
        with self.lock:
            self.runs.append(run)
            self.times.append(time.monotonic())
        run.started(_Child())

    def count(self):
        with self.lock:
            return len(self.runs)


def _keeper(settings=None, pending=lambda: True, battery=lambda: False, **kw):
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    launches = _Launches()
    keeper = J.JourneyKeeper(controller, "ja", settings=lambda: dict(FAST, **(settings or {})), pending=pending,
                             battery=battery, launcher=launches, plan_path=os.path.join(h.root(), "no-plan.json.gz"),
                             **kw)
    return keeper, controller, registry, launches


class _Plan:
    """A loaded plan's stand-in: what the keeper reads of one (its header)."""

    def __init__(self, signature="run-1", language="ja"):
        self.header = {"run_signature": signature, "language": language, "order_free_signature": "f"}


def _generates(registry):
    return [v for v in registry.snapshot() if v.kind == "generate"]


def test_a_burst_of_twenty_moves_makes_one_run_after_the_last():
    """Twenty moves 20 ms apart: nothing runs during the burst, one quiet run starts the quiet time after the last."""
    keeper, controller, registry, launches = _keeper()
    for _ in range(20):
        keeper.changed("move")
        time.sleep(0.02)
    last = time.monotonic()
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert launches.times[0] - last >= FAST["journey_settle_s"] - 0.02, "it waited the quiet time after the last move"
    time.sleep(0.5)
    assert launches.count() == 1 and keeper.asked == 1
    view = _generates(registry)[0]
    assert view.automatic and view.label == "Generating (automatic)"
    assert launches.runs[0].quiet and "--no-open" in launches.runs[0].argv
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)


def test_changed_returns_at_once_and_reads_nothing():
    """`changed` runs on the window's thread: no settings file, no battery, no journey check there."""
    calls = []
    keeper, _controller, _registry, _launches = _keeper(
        pending=lambda: calls.append("pending") or True)
    keeper._settings = lambda: calls.append("settings") or dict(FAST)
    keeper._battery = lambda: calls.append("battery") or False
    started = time.perf_counter()
    for _ in range(50):
        keeper.changed("move")
    ms = (time.perf_counter() - started) * 1000 / 50
    assert calls == [] and ms <= 4, (calls, ms)
    keeper.close()


def test_a_second_burst_cancels_the_run_and_one_more_runs_after_it():
    """A burst while the background run reads files: that run is asked to stop (its cancel file), answers cancelled,
    and one more run starts the quiet time after the second burst — never two at once."""
    keeper, controller, registry, launches = _keeper()
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    first = launches.runs[0]
    first.feed(_line("Counting words"))
    for _ in range(5):
        keeper.changed("move")
        time.sleep(0.02)
    assert os.path.exists(first.cancel_file), "the run in flight was asked to stop"
    assert controller.state().state == G.CANCELLING
    first.feed(CANCELLED)
    first.ended(76)                                 # it stops in the middle of the burst ...
    keeper.changed("move")                          # ... which goes on: the next run waits for its end, not for this one
    last = time.monotonic()
    time.sleep(0.05)
    assert launches.count() == 1, "never re-queued the moment the cancelled run ended"
    assert h.until(lambda: launches.count() == 2, seconds=5)
    assert launches.times[1] - last >= FAST["journey_settle_s"] - 0.02
    assert [v.cancelled for v in _generates(registry)][:1] == [True]
    launches.runs[1].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    assert launches.count() == 2


def test_a_run_past_writing_your_list_finishes_and_the_next_burst_runs_after():
    """The second burst came once the run writes the list: it finishes (current), then the burst's own run comes."""
    keeper, controller, _registry, launches = _keeper()
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].feed(_line("Writing your list"))
    keeper.changed("move")
    launches.runs[0].ended(0)
    assert h.until(lambda: launches.count() == 2, seconds=5)
    launches.runs[1].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)


def test_a_burst_back_to_the_analysed_order_asks_for_nothing():
    """S19: the moves came back to the order the last Generate read — the journey is current, no run."""
    keeper, _controller, registry, launches = _keeper(pending=lambda: False)
    for _ in range(4):
        keeper.changed("move")
    time.sleep(FAST["journey_settle_s"] + 0.4)
    assert launches.count() == 0 and _generates(registry) == [] and keeper.asked == 0


def test_a_failed_check_generates_to_be_sure():
    """The journey check raised (a store busy, a disk error): a Generate, which reads the truth itself."""
    def broken():
        raise OSError("the store is busy")
    keeper, _controller, _registry, launches = _keeper(pending=broken)
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].ended(0)


def test_the_users_generate_is_never_cancelled_and_the_automatic_one_waits_for_it():
    """The user pressed Generate: a burst never withdraws the user's run; the automatic run waits behind it."""
    keeper, controller, registry, launches = _keeper()
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].feed(_line("Counting words"))
    keeper.changed("move")
    time.sleep(FAST["journey_settle_s"] + 0.3)
    assert not os.path.exists(launches.runs[0].cancel_file), "the user's run is not the keeper's to cancel"
    assert launches.count() == 1, "never two at once"
    keeper.changed("move")                          # a burst while the automatic one waits: it withdraws its own
    assert controller._pending is None, "the waiting automatic request was taken back"
    user.ended(0)
    assert h.until(lambda: launches.count() == 2, seconds=5), "the automatic run after the user's"
    assert launches.runs[1].quiet and not launches.runs[0].quiet
    launches.runs[1].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    assert [v.cancelled for v in _generates(registry)] == [False, False]


def test_an_automatic_run_waiting_its_turn_gives_way_to_the_users():
    """The automatic run is still waiting for `results` (another program's Generate): the user's press takes its place
    — one run, the user's."""
    h.seed_library("ja")
    keeper, controller, registry, launches = _keeper()
    with h.Holder("results", "Generate"):
        keeper.changed("move")
        assert h.until(lambda: controller.state().message == "Waiting for Generate to finish", seconds=10)
        controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == 1, seconds=10)
    assert not launches.runs[0].quiet, "the user's run"
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    assert launches.count() == 1


def test_a_level_change_runs_one_generate():
    """The level or the band moved (the order-free signature: the plan is stale): one background run."""
    keeper, _controller, _registry, launches = _keeper()
    keeper.changed("level")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert keeper.asked == 1
    launches.runs[0].ended(0)


def test_on_the_battery_it_waits_the_battery_time():
    """Sonic's E3.2-1: 3 s after the last move, 30 s on a laptop's battery (the settings' own values here)."""
    keeper, _controller, _registry, launches = _keeper(battery=lambda: True)
    keeper.changed("move")
    last = time.monotonic()
    time.sleep(FAST["journey_settle_s"] + 0.2)
    assert launches.count() == 0, "not at the plugged-in time"
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert launches.times[0] - last >= FAST["journey_settle_battery_s"] - 0.03
    launches.runs[0].ended(0)


def test_a_longer_quiet_time_set_in_advanced_settings_is_waited():
    keeper, _controller, _registry, launches = _keeper(settings={"journey_settle_s": 0.7})
    keeper.changed("move")
    last = time.monotonic()
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert launches.times[0] - last >= 0.67
    launches.runs[0].ended(0)


@pytest.mark.parametrize("settings, battery, expected", [
    ({}, False, J.SETTLE_S), ({}, True, J.SETTLE_BATTERY_S),
    ({"journey_settle_s": 5}, False, 5.0), ({"journey_settle_battery_s": 45}, True, 45.0),
    ({"journey_settle_s": "soon"}, False, J.SETTLE_S), ({"journey_settle_s": -1}, False, J.SETTLE_S),
    ({"journey_settle_battery_s": None}, True, J.SETTLE_BATTERY_S), (None, False, J.SETTLE_S),
])
def test_settle_seconds_reads_the_settings_and_falls_back(settings, battery, expected):
    """A hand-edited settings.json with a word or a negative number: the default, never an error."""
    assert J.settle_seconds(settings, battery) == expected


def test_the_defaults_are_sonics():
    from app import settings_manager
    defaults = settings_manager.load_settings()
    assert defaults["journey_settle_s"] == 3 and defaults["journey_settle_battery_s"] == 30
    assert J.SETTLE_S == 3.0 and J.SETTLE_BATTERY_S == 30.0


def test_on_battery_answers_without_raising():
    """Whatever the machine (a desktop: plugged in, no battery), a bool, never an exception."""
    assert J.on_battery() in (True, False)


def test_the_window_closing_leaves_nothing():
    """`close` while the quiet time runs: no run is ever asked for, no timer left."""
    keeper, _controller, registry, launches = _keeper()
    keeper.changed("move")
    keeper.close()
    keeper.changed("move")
    time.sleep(FAST["journey_settle_s"] + 0.3)
    assert launches.count() == 0 and _generates(registry) == [] and keeper._timer is None


def test_withdraw_drops_only_its_own_request():
    """The controller's `withdraw(run)`: a run another request replaced, or one already over, is left alone."""
    controller = GenerateController(JobRegistry(), settle=5)
    launches = _Launches()
    mine = controller.request("ja", argv=["analyzer.py", "--progress-json"], quiet=True, launcher=launches)
    theirs = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    controller.withdraw(mine)                       # replaced while settling: nothing to take back
    assert controller._pending is theirs
    controller.withdraw(theirs)
    assert controller._pending is None and controller._timer is None
    assert controller.state().state == G.IDLE


# --- the report then agrees with the plan (real Generates, RP-2's library) ----------------------------------------- #
@pytest.mark.parametrize("case", ["rp2-ja", "rp2-zh"])
def test_after_moves_the_background_run_agrees_with_the_plan(case):
    """Moves in the library store → one background Generate through the controller → its lists equal the engine's for
    that order (shadow mode finds no difference, writes no line), the window is handed the new plan, and the journey
    is no longer pending."""
    import subprocess
    import sys
    from app import analyzer, library_store as ls, plan_engine
    from app.path_utils import get_local_data_path
    from tests import plan_file_cases as cases

    root = h.root()
    language = cases.ALL_CASES[case][0]
    cases.build(root, case)
    settings = dict(FAST, target_language=language, anki_connect_url="http://127.0.0.1:9")
    h.write_settings(settings)
    controller = GenerateController(JobRegistry(), settle=0)
    controller.request(language, settings=settings, quiet=True)
    assert h.until(lambda: controller.state().state in (G.CURRENT, G.FAILED) and controller._run is None, 300)
    assert controller.state().state == G.CURRENT
    subprocess.run([sys.executable, os.path.join(h.PROJECT_ROOT, "app", "library_store.py"), "maintain",
                    "--language", language], cwd=h.PROJECT_ROOT, capture_output=True)
    plan_path = os.path.join(root, "results", analyzer.PLAN_FILE)
    previous = plan_engine.load(plan_path)

    data_dir, user_files = os.path.join(root, "data", language), os.path.join(root, "User Files", language)
    # A move and its reverse: the journey is current again (the real check), so nothing is asked (S19).
    store = ls.open_store(language, data_dir, user_files)
    try:
        soon = store.ids("soon")
        assert store.move([soon[0]], "now") is not None
        assert store.move([soon[0]], "soon", before_id=soon[1]) is not None
    finally:
        store.close()
    back = J.JourneyKeeper(controller, language, settings=lambda: settings)
    back.changed("move")
    back.changed("move")
    time.sleep(FAST["journey_settle_s"] + 1.5)
    assert back.asked == 0, "a burst back to the analysed order asks for nothing"
    back.close()

    store = ls.open_store(language, data_dir, user_files)
    try:
        soon, goal = store.ids("soon"), store.ids("goal")
        assert soon and goal
        assert store.move([soon[0]], "now") is not None                    # Soon -> NOW's front
        assert store.move([goal[-1]], "soon", before_id=soon[-1]) is not None
        assert store.journey_pending()
    finally:
        store.close()

    landed = []
    compared = []
    real_shadow = J.shadow

    def spy(previous, plan, lists, stamp=False):
        compared.append((previous is not None, bool(lists.get("priority"))))
        return real_shadow(previous, plan, lists, stamp)
    keeper = J.JourneyKeeper(controller, language, settings=lambda: settings, on_done=landed.append)
    J.shadow = spy
    try:
        keeper.changed("move")
        keeper.changed("move")
        assert h.until(lambda: landed, seconds=300), controller.state()
    finally:
        J.shadow = real_shadow
    assert compared == [(True, True)], "the keeper compared the new lists against a previous plan"
    assert plan_engine.stands_aside(previous) is None
    assert landed == [plan_path] and keeper.asked == 1
    new = plan_engine.load(plan_path)
    assert new.header["run_signature"] != previous.header["run_signature"]
    assert new.header["order_free_signature"] == previous.header["order_free_signature"]
    assert J.shadow(previous, new, J._lists()) == "", "the report agrees with the plan"
    assert not os.path.exists(os.path.join(get_local_data_path(), "logs", J.SHADOW_LOG))
    store = ls.open_store(language, data_dir, user_files)
    try:
        assert not store.journey_pending()
    finally:
        store.close()
    keeper.close()


def test_shadow_names_the_first_difference():
    """Shadow mode's comparison is a referee, not a formality: a list that differs from the engine's in one value is
    named, row and column."""
    class _Result:
        priority = [{"Word": "猫", "Reading": "ネコ", "Score": 2.0, "Occurrences": 3}]
        progressive = []
    lists = {"priority": [{"Word": "猫", "Reading": "ネコ", "Score": "2.0", "Occurrences": "4"}], "progressive": []}
    assert "Occurrences" in J._differs(_Result, lists) and "row 1" in J._differs(_Result, lists)
    lists["priority"][0]["Occurrences"] = "3"
    assert J._differs(_Result, lists) == ""
    assert J.shadow(None, object(), lists) == ""


def test_a_timer_already_firing_when_a_move_comes_asks_for_nothing():
    """`Timer.cancel` can't stop a timer whose `_fire` has begun: that stale fire must see a newer move armed another
    timer and ask for nothing, so the burst still makes one run."""
    keeper, _controller, registry, launches = _keeper()
    keeper.changed("move")
    stale = keeper._armed
    keeper.changed("move")                          # the move that cancelled it
    keeper._fire(stale)                             # ... whose fire had already begun
    assert launches.count() == 0 and keeper.asked == 0
    assert h.until(lambda: launches.count() == 1, seconds=5)
    time.sleep(0.4)
    assert launches.count() == 1 and len(_generates(registry)) == 1
    launches.runs[0].ended(0)


def test_an_automatic_request_never_takes_a_waiting_users_place():
    """The user pressed Generate a moment ago (still settling): the keeper's quiet request leaves it in place — the
    user's run runs, opens as the user's, and the keeper holds no run of the user's to withdraw."""
    controller = GenerateController(JobRegistry(), settle=2.5)    # the user's request settles longer than the keeper
    launches = _Launches()
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    keeper = J.JourneyKeeper(controller, "ja", settings=lambda: dict(FAST), pending=lambda: True,
                             battery=lambda: False, launcher=launches,
                             plan_path=os.path.join(h.root(), "no-plan.json.gz"))
    keeper.changed("move")
    assert h.until(lambda: keeper.asked == 1, seconds=5)
    assert controller._pending is user and keeper._run is None
    keeper.changed("move")                          # a burst never withdraws the user's request
    assert h.until(lambda: launches.count() >= 1, seconds=10)
    assert launches.runs[0] is user and not user.quiet
    user.ended(0)
    keeper.close()


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 1e9])
def test_an_endless_quiet_time_is_held_to_an_hour_or_the_default(value):
    """A hand-edited infinity, NaN or a huge number: a Timer can't wait for it (OverflowError on its thread)."""
    assert J.settle_seconds({"journey_settle_s": value}, False) in (J.SETTLE_S, J.SETTLE_MAX_S)


def test_a_shorter_quiet_time_is_honoured_on_the_first_burst():
    """The keeper starts with 3 s in mind; a 0.1 s setting is still waited, not the 3 s."""
    keeper, _controller, _registry, launches = _keeper(settings={"journey_settle_s": 0.1})
    keeper.changed("move")
    last = time.monotonic()
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert launches.times[0] - last < 1.5
    launches.runs[0].ended(0)


def test_a_list_that_cant_be_read_is_logged_and_the_window_still_rebaselines(monkeypatch, tmp_path):
    """Shadow mode's read of the lists fails (a damaged CSV): one log line, and `on_done` still hands the plan over."""
    landed, logged = [], []
    keeper, _controller, _registry, _launches = _keeper(on_done=landed.append)
    plan = tmp_path / "plan.json.gz"
    plan.write_bytes(b"")
    keeper._plan_path = str(plan)
    monkeypatch.setattr(J, "_load_plan", lambda path: _Plan())
    monkeypatch.setattr(J, "_lists", lambda: (_ for _ in ()).throw(UnicodeDecodeError("utf-8", b"", 0, 1, "x")))
    monkeypatch.setattr(J, "shadow", lambda previous, plan, lists, stamp=False: "")
    monkeypatch.setattr(J, "_log_shadow", logged.append)
    keeper._landed(object())
    assert landed == [str(plan)] and logged and "comparison failed" in logged[0]


def test_a_generate_the_keeper_didnt_ask_for_is_still_shadowed(monkeypatch):
    """05 §3: every full Generate is compared — the user's own too — against the plan the last Generate wrote."""
    seen = []
    keeper, _controller, _registry, _launches = _keeper(on_done=lambda path: None)
    earlier, newer = _Plan("run-0"), _Plan("run-1")
    keeper._last_plan = earlier
    monkeypatch.setattr(J, "_load_plan", lambda path: newer)
    monkeypatch.setattr(J, "_lists", lambda: {})
    monkeypatch.setattr(J, "shadow", lambda previous, plan, lists, stamp=False: seen.append((previous, plan)) or "")
    keeper._ended(object(), "current")              # the user's own run, told by the run itself
    assert h.until(lambda: seen, seconds=5)
    assert seen == [(earlier, newer)] and keeper._last_plan is newer



# --- the second pass's findings (Opus adversary, intent keeper) ------------------------------------------------------ #
def test_a_run_that_ends_while_another_waits_still_lands(monkeypatch):
    """The keeper's run finishes past *Writing your list* while the next burst's run already waits: the controller's
    state then reads `queued`, never `current` — the run's own end still hands the window the new plan."""
    landed = []
    monkeypatch.setattr(J, "_load_plan", lambda path: _Plan("run-1"))
    monkeypatch.setattr(J, "_lists", lambda: {})
    keeper, controller, _registry, launches = _keeper(on_done=landed.append)
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].feed(_line("Writing your list"))
    controller.request("ja", argv=["analyzer.py", "--progress-json"], quiet=True, launcher=launches)   # waits behind
    launches.runs[0].ended(0)
    assert h.until(lambda: landed, seconds=5), "landed though the state read queued"
    assert h.until(lambda: launches.count() == 2, seconds=5)
    launches.runs[1].ended(0)
    keeper.close()


def test_close_withdraws_its_own_run_and_tells_the_window_nothing_more(monkeypatch):
    """Closing (or switching language) while the keeper's run is in flight: the run is asked to stop, and a landing
    after `close` hands nothing to the closed window; no listener is left on the controller."""
    landed = []
    monkeypatch.setattr(J, "_load_plan", lambda path: _Plan("run-1"))
    keeper, controller, _registry, launches = _keeper(on_done=landed.append)
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].feed(_line("Counting words"))
    keeper.close()
    assert os.path.exists(launches.runs[0].cancel_file), "its own run was withdrawn"
    assert keeper._ended not in controller._end_listeners
    launches.runs[0].feed(CANCELLED)
    launches.runs[0].ended(76)
    keeper._ended(object(), "current")              # told late, all the same
    time.sleep(0.2)
    assert landed == []


def test_another_languages_plan_is_never_handed_to_the_window(monkeypatch):
    landed = []
    monkeypatch.setattr(J, "_load_plan", lambda path: _Plan("run-zh", language="zh"))
    keeper, _controller, _registry, _launches = _keeper(on_done=landed.append)
    keeper._landed(None)
    assert landed == [] and keeper._last_plan is None


def test_the_same_plan_is_handed_over_once(monkeypatch):
    """S19: a Generate the analyzer skipped (nothing changed) writes the same plan: the window isn't re-baselined again."""
    landed = []
    plans = iter([_Plan("run-1"), _Plan("run-1"), _Plan("run-2")])
    monkeypatch.setattr(J, "_load_plan", lambda path: next(plans))
    monkeypatch.setattr(J, "_lists", lambda: {})
    keeper, _controller, _registry, _launches = _keeper(on_done=landed.append)
    for _ in range(3):
        keeper._landed(None)
    assert len(landed) == 2


def test_the_users_press_stops_a_running_automatic_generate():
    """The automatic run has started; the user presses Generate: the automatic one is asked to stop (before *Writing
    your list*), and the user's runs next — one wait, not two full runs."""
    keeper, controller, registry, launches = _keeper()
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    automatic = launches.runs[0]
    automatic.feed(_line("Counting words"))
    controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert os.path.exists(automatic.cancel_file), "the automatic run was asked to stop"
    automatic.feed(CANCELLED)
    automatic.ended(76)
    assert h.until(lambda: launches.count() == 2, seconds=5)
    assert not launches.runs[1].quiet
    launches.runs[1].ended(0)
    assert [v.cancelled for v in _generates(registry)] == [True, False]


def test_a_run_that_ended_as_it_was_withdrawn_never_reads_stopping():
    """The withdraw's cancel lands just after the run ended: the controller doesn't go back to `cancelling` for good."""
    controller = GenerateController(JobRegistry(), settle=0)
    launches = _Launches()
    run = controller.request("ja", argv=["analyzer.py", "--progress-json"], quiet=True, launcher=launches)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    run.ended(0)
    controller._cancel_run(run)                     # the registry's cancel, arriving late
    assert controller.state().state == G.CURRENT


def test_the_switch_off_asks_for_nothing():
    """D29: with the background Generate switched off, moves never start one."""
    keeper, _controller, registry, launches = _keeper(enabled=lambda: False)
    keeper.changed("move")
    time.sleep(FAST["journey_settle_s"] + 0.7)
    assert launches.count() == 0 and _generates(registry) == []


def test_reasons_are_cleared_when_nothing_is_asked():
    keeper, _controller, _registry, _launches = _keeper(pending=lambda: False)
    for _ in range(3):
        keeper.changed("pin")
    assert h.until(lambda: keeper.reasons == [], seconds=5)


def test_a_move_while_the_request_is_made_takes_it_back():
    """A move lands between the keeper's last check and its request: the request it just made is withdrawn at once."""
    class _Controller:
        def __init__(self):
            self.withdrawn = []

        def on_end(self, callback):
            pass

        def unsubscribe(self, callback):
            pass

        def request(self, *a, **k):
            keeper.changed("move")              # the move, on the window's thread, as the request is made
            run = type("R", (), {"quiet": True, "done": False})()
            self.made = run
            return run

        def withdraw(self, run):
            self.withdrawn.append(run)
    controller = _Controller()
    keeper = J.JourneyKeeper(controller, "ja", settings=lambda: dict(FAST), pending=lambda: True,
                             battery=lambda: False, plan_path=os.path.join(h.root(), "no-plan.json.gz"))
    keeper._ask(keeper._armed)
    assert controller.withdrawn == [controller.made] and keeper._run is None
    keeper.close()


def test_the_comparison_skips_lists_another_run_is_writing(monkeypatch):
    """Shadow mode compares the plan with `results/`'s lists only while the run stamp still names that plan's run."""
    monkeypatch.setattr(J, "_stamped", lambda signature: False)

    class _Engine:
        def __init__(self, *a):
            pass

        def replan(self, order):
            return type("R", (), {"priority": [{"Word": "x"}], "progressive": []})()
    from app import plan_engine
    monkeypatch.setattr(plan_engine, "Engine", _Engine)
    monkeypatch.setattr(plan_engine, "stands_aside", lambda plan: None)
    previous, plan = _Plan("run-0"), _Plan("run-1")
    previous.files = plan.files = []
    assert J.shadow(previous, plan, {"priority": [], "progressive": []}, stamp=True) == ""
    assert J.shadow(previous, plan, {"priority": [], "progressive": []}) != "", "without the stamp check: compared"


def test_settings_that_cant_be_read_ask_for_nothing():
    """settings.json unreadable as the timer fires (being replaced): no Generate on guessed settings, no dead thread —
    the next move asks again."""
    def broken():
        raise OSError("settings.json is being replaced")
    keeper, _controller, registry, launches = _keeper()
    keeper._settings = broken
    keeper.changed("move")
    time.sleep(FAST["journey_settle_s"] + 0.7)
    assert launches.count() == 0 and _generates(registry) == []
    keeper._settings = lambda: dict(FAST)
    keeper.changed("move")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].ended(0)


@pytest.mark.parametrize("outcome", ["stale", "failed", "dropped"])
def test_a_run_that_didnt_finish_hands_nothing_over(monkeypatch, outcome):
    """Only a finished run wrote a new plan: a cancelled, failed or never-started one leaves the window's engine as it
    is (the plan file on disk is still the last finished run's)."""
    landed = []
    monkeypatch.setattr(J, "_load_plan", lambda path: _Plan("run-new"))
    monkeypatch.setattr(J, "_lists", lambda: {})
    keeper, _controller, _registry, _launches = _keeper(on_done=landed.append)
    keeper._ended(object(), outcome)
    time.sleep(0.2)
    assert landed == []


def test_shadow_names_a_row_count_that_differs():
    """A list one row shorter than the engine's is a difference, said with both counts."""
    class _Result:
        priority = [{"Word": "猫", "Reading": "ネコ"}, {"Word": "犬", "Reading": "イヌ"}]
        progressive = []
    lists = {"priority": [{"Word": "猫", "Reading": "ネコ"}], "progressive": []}
    assert J._differs(_Result, lists) == "priority: 2 rows, the Generate wrote 1"
