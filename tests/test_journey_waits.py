"""A plain move waits for a reader (Sonic 2026-11-06, "into 3.0"; the generate-speed study's A + A2):
`app/services/journey.py` (`only_moved`, the keeper's catch-up), `plan_engine.only_order`, the controller's check.

What a wrong answer would cost a learner:
  * a Generate after every burst of moves (13 s at 2,000 files, 107 s at 20,000 here; ×2.2 on a laptop) that only
    refreshes the journey — the engine already made the numbers, *Up next*, Anki's order and Connect current;
  * the other way: a journey that never catches up, or a known word, a word list, a setting, a finish, a removed file
    or a new file that changes the list waiting minutes for its Generate (a word crossing the list's cut-off left out);
  * *Journey ↗* waiting a minute for a background run (A2), or a reader's wish lost;
  * the Generate button saying "out of date" after a move the list already follows (its ● says the journey catches up).

The keeper's timing runs on a scripted child (a launcher that records each run, as tests/test_services_journey.py);
the rule runs on a real library (RP-2's, tests/plan_file_cases.py), its real Generate, its store and its plan file.
"""
import json
import os
import threading
import time

import pytest

from app import analyzer, library_store as ls, plan_engine
from app.services import generate as G
from app.services import journey as J
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse: the child's store, in-process)
from tests.test_services_journey import _Launches, _generates

SETTLE = {"journey_settle_s": 0.3, "journey_settle_battery_s": 0.3}


def _keeper(only_moved=lambda: True, catch_up=30.0, pending=lambda: True, **kw):
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    launches = _Launches()
    keeper = J.JourneyKeeper(controller, "ja", settings=lambda: dict(SETTLE), pending=pending,
                             battery=lambda: False, launcher=launches, only_moved=only_moved, catch_up=catch_up,
                             plan_path=os.path.join(h.root(), "no-plan.json.gz"), **kw)
    return keeper, controller, registry, launches


def _quiet(keeper):
    """The keeper's settle time and its first look are over: what it decided is final until its next timer."""
    time.sleep(SETTLE["journey_settle_s"] + 0.6)


# --- the keeper: moves wait, everything else Generates ------------------------------------------------------------- #
def test_a_burst_of_moves_starts_no_generate_and_the_journey_is_catching_up():
    # the work count of the move press: twenty moves, the quiet time over — zero Generates asked, none in the registry
    keeper, _controller, registry, launches = _keeper()
    for _ in range(20):
        keeper.changed("store")
        time.sleep(0.01)
    assert h.until(keeper.catching_up, seconds=5)
    _quiet(keeper)
    assert launches.count() == 0 and keeper.asked == 0 and _generates(registry) == []
    keeper.close()
    assert not keeper.catching_up()


def test_anything_but_moves_still_generates_after_the_quiet_time():
    # a known word, a word list, a setting, a finish, a new file: the rule says no — the run comes as before
    keeper, controller, _registry, launches = _keeper(only_moved=lambda: False)
    keeper.changed("store")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert not keeper.catching_up() and keeper.asked == 1
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    keeper.close()


@pytest.mark.parametrize("reason", ["store", "replan: moves", "start", "level", "replan: replan-now: known"])
def test_the_rule_decides_whatever_the_reason_is(reason):
    # every path into the keeper (a store change, the host's asks, the start's and a focus's look, the level) meets the
    # one rule at the quiet time: moves only waits, anything else runs
    for moves_only, runs in ((True, 0), (False, 1)):
        keeper, _controller, _registry, launches = _keeper(only_moved=lambda m=moves_only: m)
        keeper.changed(reason)
        if runs:
            assert h.until(lambda: launches.count() == 1, seconds=5)
        else:
            assert h.until(keeper.catching_up, seconds=5)
        _quiet(keeper)
        assert launches.count() == runs, (reason, moves_only)
        keeper.close()


def test_the_journey_is_generated_after_the_quiet_minutes_and_each_move_starts_them_again():
    # the quiet timer: moves at 0, 0.4 and 0.8 s with a 1 s catch-up -> one run, no sooner than 1 s after the last
    keeper, controller, _registry, launches = _keeper(catch_up=1.0)
    for _ in range(3):
        keeper.changed("store")
        last = time.monotonic()
        time.sleep(0.4)
    assert launches.count() == 0, "never during the burst"
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert launches.times[0] - last >= 1.0 - 0.05, "the quiet minutes counted from the last move"
    assert not keeper.catching_up() and keeper.asked == 1
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    time.sleep(1.5)
    assert launches.count() == 1, "one run for the burst"
    keeper.close()


def test_a_focus_or_a_start_look_never_puts_the_catch_up_off():
    # looks are not changes: a focus every 0.3 s must not keep the journey behind for ever
    keeper, _controller, _registry, launches = _keeper(catch_up=1.0)
    keeper.changed("store")
    moved = time.monotonic()
    while time.monotonic() - moved < 2.5 and launches.count() == 0:
        keeper.changed("start")
        keeper.changed("replan: moves")
        time.sleep(0.5)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    took = launches.times[0] - moved
    assert took < 1.0 + SETTLE["journey_settle_s"] + 0.6, f"counted from the move, not the looks ({took:.2f} s)"
    keeper.close()


def test_a_reader_gets_the_run_at_once_with_no_quiet_time_and_no_rest():
    # Journey ↗ (or an export): want -> asked now, not after the settle, nor the rest after the last run
    keeper, _controller, _registry, launches = _keeper()
    keeper.changed("store")
    assert h.until(keeper.catching_up, seconds=5)
    keeper._rest_until = time.monotonic() + 60       # a run just ended that took a minute
    keeper._settle = 30.0
    asked = time.monotonic()
    assert keeper.want("journey") is True
    assert h.until(lambda: launches.count() == 1, seconds=2)
    assert launches.times[0] - asked < 1.0
    assert not keeper.catching_up()
    assert keeper.want("journey") is False, "nothing owed any more: a second press asks nothing"
    time.sleep(0.4)
    assert launches.count() == 1
    keeper.close()


def test_want_asks_nothing_when_nothing_is_owed():
    keeper, _controller, _registry, launches = _keeper()
    assert keeper.want("journey") is False
    time.sleep(0.3)
    assert launches.count() == 0
    keeper.close()


def test_a_reader_never_starts_a_run_beside_the_users_own():
    # a user's Generate in flight: the reader's wish waits for it; the look after it finds the journey current
    current = {"now": False}
    keeper, controller, registry, launches = _keeper(pending=lambda: not current["now"])
    keeper.changed("store")
    assert h.until(keeper.catching_up, seconds=5)
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert keeper.want("journey") is False, "the user's run brings it: the reader waits for that one"
    time.sleep(0.5)
    assert launches.count() == 1 and not launches.runs[0].quiet, "never two at once"
    current["now"] = True
    user.ended(0)
    _quiet(keeper)
    assert launches.count() == 1 and keeper.asked == 0, "the user's run brought it in"
    assert not keeper.catching_up()
    assert len(_generates(registry)) == 1
    keeper.close()


def test_with_the_background_generate_off_nothing_runs_by_itself():
    # D29 off: no run after the quiet time, none after the minutes; a reader's wish asks nothing either
    keeper, _controller, _registry, launches = _keeper(catch_up=0.5, enabled=lambda: False)
    keeper.changed("store")
    time.sleep(1.5)
    assert launches.count() == 0 and not keeper.catching_up()
    assert keeper.want("journey") is False
    keeper.close()


def test_an_update_staged_holds_the_catch_up(monkeypatch):
    # the registry's hold while an update waits: the reader's run is queued, never started, until the hold ends
    keeper, controller, registry, launches = _keeper()
    held = {"now": True}
    registry.gate(lambda kind: "an update is waiting" if held["now"] and kind == "generate" else None)
    keeper.changed("store")
    assert h.until(keeper.catching_up, seconds=5)
    assert keeper.want("journey")
    assert h.until(lambda: keeper.asked == 1, seconds=5)
    time.sleep(0.5)
    assert launches.count() == 0, "held while the update waits"
    held["now"] = False
    registry.reschedule()
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert launches.runs[0].quiet and "--no-open" in launches.runs[0].argv
    keeper.close()


def test_a_report_only_re_render_is_never_put_off(monkeypatch):
    # the analysis current, the report behind (a stone, a Journey setting): seconds of work — it runs at the quiet
    # time even though nothing but the order moved
    from app import run_args
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **_k: ["analyzer.py"])
    monkeypatch.setattr(analyzer, "journey_is_current", lambda _a, _l: True)
    monkeypatch.setattr(analyzer, "report_is_current", lambda _a, _l: False)
    keeper, _controller, _registry, launches = _keeper(pending=None)
    keeper.changed("store")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert not keeper.catching_up()
    keeper.close()


def test_background_run_is_true_for_a_quiet_run_and_false_for_the_keepers_re_render(monkeypatch):
    # A2's question: a quiet full run in flight brings the journey (Journey ↗ opens at once); the keeper's re-render
    # of a report whose analysis is current takes seconds (Journey ↗ waits for it, as a6 #5 does)
    keeper, controller, _registry, launches = _keeper(only_moved=lambda: False)
    assert keeper.background_run() is False, "nothing in flight"
    keeper.changed("store")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert keeper.background_run() is True
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == 2, seconds=5)
    assert keeper.background_run() is False, "a user's run is no background run"
    user.ended(0)
    keeper.close()
    from app import run_args
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **_k: ["analyzer.py"])
    monkeypatch.setattr(analyzer, "journey_is_current", lambda _a, _l: True)
    monkeypatch.setattr(analyzer, "report_is_current", lambda _a, _l: False)
    keeper, _controller, _registry, launches = _keeper(pending=None)
    keeper.changed("settings")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert keeper.background_run() is False, "the keeper's re-render"
    keeper.close()


# --- the controller's check: the Generate button's mark ------------------------------------------------------------ #
@pytest.mark.parametrize("current, moves_only, state", [
    (True, False, G.CURRENT), (False, True, G.CURRENT), (False, False, G.STALE), (None, True, G.IDLE)])
def test_the_generate_buttons_check_reads_moves_as_current(monkeypatch, current, moves_only, state):
    # after a move the list is the engine's: the button stays ✓ and the ● says the journey catches up; anything else
    # that moved is "out of date" as before; a check that can't tell stays idle
    from app import run_args
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **_k: ["analyzer.py"])
    monkeypatch.setattr(analyzer, "journey_is_current", lambda _a, _l: current)
    asked = []
    monkeypatch.setattr(J, "only_moved", lambda settings, language: asked.append(language) or moves_only)
    controller = GenerateController(JobRegistry(), settle=0)
    answers = []
    controller.check({}, "ja", then=answers.append)
    assert h.until(lambda: answers, seconds=5)
    assert answers == [current], "its caller hears the analyzer's own answer"
    assert controller.state().state == state
    assert asked == (["ja"] if current is False else []), "the rule is asked only of a journey that isn't current"


# --- the rule on a real library: each trigger, both ways ----------------------------------------------------------- #
def _baseline(language="ja", monkeypatch=None):
    """RP-2's library, one real Generate through the controller -> (store, settings, root, controller)."""
    from tests import plan_file_cases as cases
    root = h.root()
    case = "rp2-" + language
    cases.build(root, case)
    settings = dict(SETTLE, target_language=language, anki_connect_url="http://127.0.0.1:9")
    h.write_settings(settings)
    controller = GenerateController(JobRegistry(), settle=0)
    controller.request(language, settings=settings, quiet=True)
    assert h.until(lambda: controller.state().state in (G.CURRENT, G.FAILED) and controller._run is None, 300)
    assert controller.state().state == G.CURRENT
    store = ls.open_store(language, os.path.join(root, "data", language), os.path.join(root, "User Files", language))
    assert store is not None
    assert not J.only_moved(settings, language), "current: nothing moved at all — no move to wait for"
    return store, settings, root, controller


def _not_current(settings, language):
    from app import run_args
    return analyzer.journey_is_current(run_args.analyzer_args(settings, language), language) is not True


def _append(path, text):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _trigger(name, store, settings, root, language):
    """One of the learner's changes -> the settings to ask with."""
    user_files = os.path.join(root, "User Files", language)
    soon, goal = store.ids("soon"), store.ids("goal")
    if name == "move":
        assert store.move([soon[0]], "now") is not None
    elif name == "move-between-tiers":
        assert store.move([goal[-1]], "soon", before_id=soon[0]) is not None
    elif name == "pin":
        assert store.pin([goal[0]]) is not None
    elif name == "finish":
        assert store.finish([soon[0]]) is not None
    elif name == "remove":
        # as the window's Remove: the row to the store's trash, its file out of the tier folder (else the next look
        # finds it there again and takes it back in)
        entry = store.schedule()[ls.TIERS["goal"][0]][-1]
        rel = str(entry["physical_path"]).lstrip("./")
        trash = os.path.join(root, "data", language, ".trash")
        os.makedirs(trash, exist_ok=True)
        os.replace(os.path.join(root, "data", language, rel), os.path.join(trash, os.path.basename(rel)))
        assert store.remove([goal[-1]], trashed_paths={goal[-1]: ".trash/" + os.path.basename(rel)}) is not None
    elif name == "known":
        path = os.path.join(user_files, "KnownWord.json")
        with open(path, encoding="utf-8") as f:
            known = json.load(f)
        known["words"].append(dict(known["words"][0], dictForm="灯台", secondary="とうだい"))   # a word learned
        with open(path, "w", encoding="utf-8") as f:
            json.dump(known, f, ensure_ascii=False)
    elif name == "ignore":
        _append(os.path.join(user_files, "IgnoreList.txt"), "\n灯台\n")
    elif name == "setting":
        settings = dict(settings, exclude_single=False)
        h.write_settings(settings)
    elif name == "level":
        settings = dict(settings, logic={"selection": {"band": "rare"}})
        h.write_settings(settings)
    elif name == "new-file":
        folder = os.path.join(root, "data", language, "HighPriority")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "added_now.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("新しい話が届いた。灯台の光が海を照らしている。\n" if language == "ja" else "新的故事到了。灯塔照亮了大海。\n")
        assert store.insert([path], "now", placement="top") is not None
    else:
        raise AssertionError(name)
    return settings


@pytest.mark.parametrize("name, waits", [
    ("move", True), ("move-between-tiers", True),                           # only the order
    ("finish", False), ("remove", False),                                   # the cut-off may move: never guessed
    ("known", False), ("ignore", False), ("setting", False), ("level", False),   # the list's edge moves
    ("new-file", False),                                                    # a new file the engine never added
])
def test_each_trigger_on_a_real_library_waits_only_when_nothing_but_the_order_moved(name, waits):
    store, settings, root, _controller = _baseline("ja")
    try:
        settings = _trigger(name, store, settings, root, "ja")
    finally:
        store.close()
    assert _not_current(settings, "ja"), "the journey is owed something"
    assert J.only_moved(settings, "ja") is waits, name
    # and the Generate button's check says the same: ✓ with the ● after a move, "out of date" after the rest
    controller = GenerateController(JobRegistry(), settle=0)
    answers = []
    controller.check(settings, "ja", then=answers.append)
    assert h.until(lambda: answers, seconds=30)
    assert controller.state().state == (G.CURRENT if waits else G.STALE)


def test_a_pin_asks_nothing_at_all():
    # a pin moves no list (*Study its cards first* groups Anki's order): the journey stays current, nothing is owed
    store, settings, root, _controller = _baseline("ja")
    try:
        assert store.pin([store.ids("goal")[0]]) is not None
    finally:
        store.close()
    assert not _not_current(settings, "ja"), "nothing owed"


def test_a_move_on_a_chinese_library_waits_too():
    store, settings, root, _controller = _baseline("zh")
    try:
        settings = _trigger("move-between-tiers", store, settings, root, "zh")
    finally:
        store.close()
    assert _not_current(settings, "zh") and J.only_moved(settings, "zh")


def test_no_plan_file_or_a_damaged_one_never_waits():
    # can't be told -> a Generate, as before (never a guess)
    store, settings, root, _controller = _baseline("ja")
    try:
        _trigger("move", store, settings, root, "ja")
    finally:
        store.close()
    plan = os.path.join(root, "results", analyzer.PLAN_FILE)
    assert J.only_moved(settings, "ja")
    with open(plan, "rb") as f:
        data = f.read()
    with open(plan, "wb") as f:
        f.write(data[:-12])                         # cut off: the gzip end and its CRC gone
    assert not J.only_moved(settings, "ja")
    os.remove(plan)
    assert not J.only_moved(settings, "ja")


def test_only_order_answers_check_s_none_from_the_header_alone():
    # the header-only plan gives check's None exactly when the whole plan does (the property `only_order` rests on)
    store, settings, root, _controller = _baseline("ja")
    try:
        from app.services import moves
        path = os.path.join(root, "results", analyzer.PLAN_FILE)
        whole, header = plan_engine.load(path), plan_engine.read_header(path)
        for name in ("move", "known", "setting"):
            settings = _trigger(name, store, settings, root, "ja")
            inputs = moves.plan_inputs("ja", settings, store)
            assert plan_engine.only_order(header, "ja", *inputs) is (plan_engine.check(whole, "ja", *inputs) is None)
    finally:
        store.close()
    assert plan_engine.only_order(None, "ja", "e", "s", {}) is False



# --- the adversarial review's cases (tracks/engine/reviews/journey-waits-register.md) ------------------------------ #
def test_a_readers_wish_in_the_quiet_time_after_a_move_is_never_lost():
    # R2: Journey ↗ a moment after a move (before the keeper's first look): the look asks the run at once, and a
    # reader waiting on `catching_up` waits for it instead of reading the old lists
    keeper, _controller, _registry, launches = _keeper()
    keeper._settings = lambda: dict(SETTLE, journey_settle_s=5.0)
    keeper.changed("store")
    assert keeper.want("journey") is False, "not told yet: the reader goes on as before"
    assert keeper.catching_up(), "but a reader waiting on it waits"
    assert h.until(lambda: launches.count() == 1, seconds=2), "asked at once, not after the 5 s quiet time"
    assert not keeper.catching_up()
    keeper.close()


def test_a_readers_wish_with_the_background_generate_switched_off_waits_on_nothing():
    # R3: deferred, then D29 off: the reader's wish meets the switch — nothing runs, nothing is left owed
    on = {"now": True}
    keeper, _controller, _registry, launches = _keeper(enabled=lambda: on["now"])
    keeper.changed("store")
    assert h.until(keeper.catching_up, seconds=5)
    on["now"] = False
    assert keeper.want("journey") is True
    assert h.until(lambda: not keeper.catching_up(), seconds=3), "no reader waits on a run that never comes"
    assert launches.count() == 0
    keeper.close()


def test_a_users_generate_in_flight_takes_the_readers_wish_never_the_keeper():
    # R1: deferred, then the user's Generate: Journey ↗ waits for that run as before (want says no)
    keeper, controller, _registry, launches = _keeper()
    keeper.changed("store")
    assert h.until(keeper.catching_up, seconds=5)
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert keeper.want("journey") is False and keeper.background_run() is False
    user.ended(0)
    keeper.close()


def test_a_quiet_run_being_stopped_for_the_users_press_is_no_background_run():
    # R8: the user's press replaces the keeper's run: while it stops, Journey ↗ waits for the user's run
    keeper, controller, _registry, launches = _keeper(only_moved=lambda: False)
    keeper.changed("store")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert keeper.background_run() is True
    controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)   # the user's
    assert h.until(lambda: controller.state().state == G.CANCELLING, seconds=5)
    assert keeper.background_run() is False
    launches.runs[0].ended(1)
    keeper.close()


def test_a_list_file_gone_with_nothing_moved_is_no_move():
    # R7: the journey isn't current because a list file is missing, not because the order moved: a Generate, and
    # the Generate button says "out of date", never ✓
    store, settings, root, _controller = _baseline("ja")
    store.close()
    os.remove(os.path.join(root, "results", "priority_learning_list.csv"))
    assert _not_current(settings, "ja")
    assert J.only_moved(settings, "ja") is False
