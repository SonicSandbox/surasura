"""Gentle on the machine (Haya-LD, 3.0.18): `power.gentle` (which PCs run their background work one job at a time),
`power.CpuLoad`, and the window's one scheduler (`services.gentle.Gentle`) — the registry's gate for automatic jobs,
and `hold` / `wait_turn` for the steps outside the registry (New arrivals' estimates, 順's re-order catch-up, covers).

What a wrong answer would cost: on a laptop (a 3.0.16 problem report) six jobs started inside two minutes of a cold start
and Anki crawled; a scheduler that holds too much costs the opposite — a press that waits behind background work (the
rule: a press always goes first), a strong desktop slowed for nothing, a busy PC whose estimates never come, or a job
held forever because the window's list was never seen. Every reading (the machine, the CPU, your review in Anki, the
clock) is a stand-in here: no real CPU, Anki or timer; the watcher's thread is never started (`attach(watch=False)`,
the test calls `tick`).
"""
import os
import sys
import threading
import time

import pytest

from app.connect import power
from app.services import gentle as G
from app.services import jobs

JA = os.path.join(os.path.dirname(__file__), "Test Resources", "ja", "context_test.txt")
ZH = os.path.join(os.path.dirname(__file__), "Test Resources", "zh", "chinese_text_1.txt")


# --- which machines -------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("cpus, total_mb, battery, expect", [
    (8, 32 * 1024, False, (True, "8 logical CPUs")),          # a laptop's class: few cores
    (24, 8 * 1024, False, (True, "8 GB of memory")),          # many cores, little memory
    (24, 32 * 1024, True, (True, "on battery")),              # this desktop unplugged (a UPS, a laptop)
    (24, 32 * 1024, False, (False, None)),                    # this desktop: side by side as before
    (12, 16 * 1024 - 200, False, (False, None)),              # a "16 GB" 12-thread PC reads ~15.8 GB: strong
    (24, None, False, (False, None)),                         # memory unreadable: the CPUs decide
])
def test_which_machines_run_their_background_work_one_job_at_a_time(cpus, total_mb, battery, expect):
    assert power.gentle(cpus=cpus, total_mb=total_mb, battery=battery) == expect


def test_the_cpu_load_is_the_busy_share_between_two_samples_and_none_where_it_cant_be_read():
    readings = iter([(1000, 2000), (1030, 2100), (1030, 2100), None, (1100, 2300)])

    def read():
        got = next(readings)
        if got is None:
            raise OSError("GetSystemTimes failed")
        return got
    load = power.CpuLoad(read=read)
    assert load.sample() is None, "the first sample has nothing to compare with"
    assert load.sample() == pytest.approx(0.70), "30 idle ticks of 100: 70 % busy"
    assert load.sample() is None, "no time passed: no share, never a division by zero"
    assert load.sample() is None, "a reading that fails is no share"
    assert load.sample() is None, "after a failed reading the next one starts again"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own counters")
def test_the_real_counters_read_and_the_real_machine_answers():
    load = power.CpuLoad()
    load.sample()
    time.sleep(0.05)
    share = load.sample()
    assert share is None or 0.0 <= share <= 1.0
    gentle, why = power.gentle()
    assert isinstance(gentle, bool) and (why is None) == (not gentle)


# --- the scheduler ---------------------------------------------------------------------------------------------- #
class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Load:
    def __init__(self):
        self.share = 0.1

    def sample(self):
        return self.share


class _World:
    """One window's registry and scheduler, every reading a stand-in."""

    def __init__(self, gentle=True, reviewing=False):
        self.registry = jobs.JobRegistry()
        self.clock = _Clock()
        self.load = _Load()
        self.machine = (gentle, "8 logical CPUs" if gentle else None)
        self.review = reviewing
        self.review_asks = 0
        self.lines = []
        self.g = G.Gentle(self.registry, machine=lambda: self.machine, load=self.load, reviewing=self._reviewing,
                          clock=self.clock, log=self.lines.append).attach(watch=False)

    def _reviewing(self):
        self.review_asks += 1
        return self.review

    def later(self, seconds):
        self.clock.now += seconds
        self.g.tick()

    def submit(self, kind, automatic=True, label=None):
        started = []
        job = self.registry.submit(kind, label or kind.title(), start=lambda j: started.append(j),
                                   automatic=automatic)
        return job, started


@pytest.fixture(autouse=True)
def _detached():
    yield
    G._current[0] = None


def test_on_a_gentle_pc_background_work_waits_for_the_windows_list_then_its_settle():
    w = _World(gentle=True)
    job, started = w.submit("indexer")
    assert (job.state, job.reason) == (jobs.WAITING, G.WINDOW_FIRST) and not started
    w.g.ready()
    w.later(G.SETTLE_S - 0.5)
    assert job.state == jobs.WAITING, "the window's first paints get their few seconds"
    w.later(1.0)
    assert job.state == jobs.RUNNING and started, "the watcher's look starts what waited"
    assert any("booted" in line for line in w.lines)


def test_a_list_never_seen_holds_nothing_past_its_limit():
    # why: a reader that never publishes (a store that can't be read) must never hold New arrivals forever
    w = _World(gentle=True)
    job, _ = w.submit("arrivals-ja")
    w.later(G.START_HOLD_MAX_S + 1)
    assert job.state == jobs.WAITING, "the settle still follows the limit"
    w.later(G.SETTLE_S + 1)
    assert job.state == jobs.RUNNING
    assert any("boot wasn't told" in line for line in w.lines)


@pytest.mark.parametrize("arrivals", ["arrivals-ja", "arrivals-zh"])
def test_on_a_gentle_pc_one_heavy_job_at_a_time_new_arrivals_last(arrivals):
    w = _World(gentle=True)
    w.g.ready()
    w.later(G.SETTLE_S + 1)
    indexer, _ = w.submit("indexer", label="Indexing")
    assert indexer.state == jobs.RUNNING
    estimates, started = w.submit(arrivals, label="Counting new arrivals")
    assert (estimates.state, estimates.reason) == (jobs.WAITING, G.TURN.format(label="Indexing"))
    indexer.finish()
    assert estimates.state == jobs.RUNNING and started, "the heavier job's end starts the next at once"


def test_on_a_gentle_pc_the_rest_waits_while_connect_makes_cards_or_a_reorder_writes():
    w = _World(gentle=True)
    w.g.ready()
    w.later(G.SETTLE_S + 1)
    mining = w.registry.record(jobs.CONNECT_KIND, "Making cards", automatic=True, on_quit="detach")
    covers_turn = G.hold("covers")
    assert covers_turn == G.TURN.format(label="Making cards")
    mining.finish()
    replan = w.registry.record("replan", "Re-ordering Anki's new cards", automatic=True, on_quit="wait")
    assert G.hold("arrivals-ja") == G.TURN.format(label="Re-ordering Anki's new cards")
    replan.finish()
    assert G.hold("arrivals-ja") is None and G.hold("covers") is None


def test_a_press_always_goes_first_whatever_the_scheduler_holds():
    w = _World(gentle=True, reviewing=True)
    w.load.share = 0.99
    w.later(G.TICK_S)
    asked, started = w.submit("indexer", automatic=False)
    assert asked.state == jobs.RUNNING and started, "a job you asked for never waits for the window, a review or load"
    generate, _ = w.submit("generate", automatic=False)
    assert generate.state != jobs.WAITING or generate.reason != G.WINDOW_FIRST


@pytest.mark.parametrize("gentle", [True, False])
def test_on_every_pc_nothing_automatic_starts_before_the_window_booted(gentle):
    # why (2026-11-20): the window opens fully before anything else, the same on every machine
    w = _World(gentle=gentle)
    generate, _ = w.submit("generate", label="Generating (automatic)")
    estimates, _ = w.submit("arrivals-ja")
    assert (generate.reason, estimates.reason) == (G.WINDOW_FIRST, G.WINDOW_FIRST)
    assert G.hold("covers") == G.WINDOW_FIRST
    w.g.ready()
    assert generate.state == jobs.RUNNING, "the boot reschedules at once: a Generate needs no settle"
    if not gentle:
        assert estimates.state == jobs.RUNNING, "a strong PC: no settle, side by side"


def test_on_a_strong_pc_the_rest_runs_beside_a_generate_as_before():
    w = _World(gentle=False)
    w.g.ready()
    generate, _ = w.submit("generate", label="Generating (automatic)")
    assert generate.state == jobs.RUNNING, "no window-first hold on a strong PC"
    estimates, _ = w.submit("arrivals-ja")
    assert estimates.state == jobs.RUNNING, "side by side: never held behind the Generate"
    assert G.hold("covers") is None


@pytest.mark.parametrize("gentle", [True, False])
def test_on_every_pc_the_rest_waits_while_you_review_in_anki_and_goes_when_you_stop(gentle):
    w = _World(gentle=gentle, reviewing=True)
    w.g.ready()
    w.later(G.SETTLE_S + 1)                            # the boot's first look asks Anki (the start's work comes now)
    assert w.review_asks == 1
    job, _ = w.submit("arrivals-zh")
    assert (job.state, job.reason) == (jobs.WAITING, G.REVIEWING)
    w.review = False
    w.later(G.REVIEW_LOOK_S)
    assert job.state == jobs.RUNNING
    assert any("reviewing" in line for line in w.lines) and any("review ended" in line for line in w.lines)


def test_anki_is_never_asked_while_no_background_work_waits():
    # why: the point is a lighter Anki — a request every few seconds for nothing would be the opposite
    w = _World(gentle=True)
    w.submit("indexer")
    w.later(G.REVIEW_LOOK_S)
    assert w.review_asks == 0, "never asked while the window opens"
    w.g.ready()
    w.later(G.TICK_S)
    assert w.review_asks == 1, "the boot's own look: the start's work comes now"
    for job in w.registry.live():
        w.registry.cancel(job.id)
    w.review_asks = 0
    w.clock.now += G.WANTED_FOR_S
    for _ in range(5):
        w.later(G.REVIEW_LOOK_S)
    assert w.review_asks == 0
    w.submit("indexer")
    w.later(G.REVIEW_LOOK_S)
    assert w.review_asks == 1


@pytest.mark.parametrize("gentle", [True, False])
def test_a_busy_cpu_holds_the_rest_until_it_is_quiet_with_no_flapping_at_the_line(gentle):
    w = _World(gentle=gentle)
    w.g.ready()
    w.load.share = 0.85
    for _ in range(int(G.LOAD_WINDOW_S) + 1):
        w.later(G.TICK_S)
    job, _ = w.submit("covers")
    assert (job.state, job.reason) == (jobs.WAITING, G.BUSY_NOW)
    w.load.share = 0.60                                # under BUSY, over QUIET: still busy
    for _ in range(int(G.LOAD_WINDOW_S) + 1):
        w.later(G.TICK_S)
    assert job.state == jobs.WAITING
    w.load.share = 0.30
    for _ in range(int(G.LOAD_WINDOW_S) + 1):
        w.later(G.TICK_S)
    assert job.state == jobs.RUNNING


def test_a_pc_that_stays_busy_still_gets_its_background_work_after_the_limit():
    w = _World(gentle=False)
    w.g.ready()
    w.load.share = 0.95
    w.later(G.TICK_S)
    job, _ = w.submit("arrivals-ja")
    assert job.reason == G.BUSY_NOW
    w.later(G.HOLD_MAX_S - 1)
    assert job.state == jobs.WAITING
    w.later(2)
    assert job.state == jobs.RUNNING, "load alone holds a kind at most HOLD_MAX_S"
    told = [line for line in w.lines if "goes on" in line]
    w.later(G.TICK_S)
    assert [line for line in w.lines if "goes on" in line] == told, "said once"


def test_on_a_gentle_pc_an_automatic_generate_waits_for_the_window_then_for_connects_batch():
    w = _World(gentle=True)
    generate, started = w.submit("generate", label="Generating (automatic)")
    assert generate.reason == G.WINDOW_FIRST
    mining = w.registry.record(jobs.CONNECT_KIND, "Making cards", automatic=True, on_quit="detach")
    w.g.ready()
    w.later(G.TICK_S)
    assert (generate.state, generate.reason) == (jobs.WAITING, G.TURN.format(label="Making cards"))
    mining.finish()
    assert generate.state == jobs.RUNNING and started, "it goes in at Connect's step boundary"


def test_the_generate_is_never_held_by_a_review_or_load():
    # why: the fresh list is the learner's own: only the rest waits for a quiet machine
    w = _World(gentle=True, reviewing=True)
    w.g.ready()
    w.load.share = 0.99
    w.later(G.REVIEW_LOOK_S)
    w.submit("indexer")
    w.later(G.REVIEW_LOOK_S)
    generate, _ = w.submit("generate")
    assert generate.state == jobs.RUNNING, "the indexer the review holds, asked first, never holds it back"


def test_unplugging_a_laptop_makes_it_gentle_at_the_next_battery_look():
    w = _World(gentle=False)
    w.g.ready()
    w.machine = (True, "on battery")
    w.later(G.BATTERY_EVERY_S)
    assert w.g.gentle and any("one job at a time (on battery)" in line for line in w.lines)
    w.registry.record("indexer", "Indexing", automatic=True)
    job, _ = w.submit("arrivals-ja")
    assert job.reason == G.TURN.format(label="Indexing"), "one heavy job at a time from the next look"


def test_with_no_scheduler_attached_nothing_waits_and_after_its_close_nothing_does():
    assert G.hold("arrivals-ja") is None
    assert G.wait_turn("covers", lambda: False) is False
    w = _World(gentle=True)
    assert G.hold("covers") == G.WINDOW_FIRST
    w.g.close()
    assert G.hold("covers") is None, "the closed window's scheduler holds nothing"


def test_wait_turn_waits_while_held_and_ends_at_its_stop():
    w = _World(gentle=True)
    naps = []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 2:
            w.g.ready()
            w.later(G.SETTLE_S + 1)
    assert G.wait_turn("covers", lambda: False, nap) is True and len(naps) == 2
    stop = threading.Event()
    w.registry.record("indexer", "Indexing", automatic=True)
    stop.set()
    assert G.wait_turn("covers", stop.is_set, nap) is False, "a stop asked ends the wait at once"


def test_a_reading_that_fails_never_holds_and_never_stops_the_watcher():
    registry = jobs.JobRegistry()

    def broken():
        raise OSError("no reading")
    g = G.Gentle(registry, machine=broken, load=_Load(), reviewing=broken, clock=_Clock(),
                 log=lambda line: None).attach(watch=False)
    registry.record("indexer", "Indexing", automatic=True)
    g.ready()
    g.tick()
    assert not g.gentle and not g.reviewing
    job = registry.submit("arrivals-ja", "Counting new arrivals", start=lambda j: None, automatic=True)
    assert job.state == jobs.RUNNING


# --- the steps outside the registry ------------------------------------------------------------------------------ #
_ECHO = r"""
import json, sys
for line in sys.stdin.buffer:
    request = json.loads(line)
    sys.stdout.buffer.write((json.dumps({"id": request["id"], "op": request["op"]}) + "\n").encode())
    sys.stdout.buffer.flush()
"""


@pytest.mark.parametrize("language, path", [("ja", JA), ("zh", ZH)])
def test_an_estimate_waits_for_its_turn_between_two_requests_and_the_workers_end_is_logged(monkeypatch, language,
                                                                                          path):
    import queue
    from app import path_utils
    from app.services.arrivals import ArrivalsWorker
    logged = []
    monkeypatch.setattr(path_utils, "write_app_log", logged.append)
    held = {"now": None}
    monkeypatch.setattr(G, "hold", lambda kind: held["now"])
    monkeypatch.setattr(G, "STEP_LOOK_S", 0.05)
    registry = jobs.JobRegistry()
    client = ArrivalsWorker(registry, language, command=[sys.executable, "-c", _ECHO])
    got = queue.Queue()
    try:
        client.stats(callback=got.put)
        assert got.get(timeout=30)["op"] == "stats"
        held["now"] = G.REVIEWING
        client.estimate(path, callback=got.put)
        with pytest.raises(queue.Empty):
            got.get(timeout=0.5)                   # held: never sent while you review
        held["now"] = None
        assert got.get(timeout=15)["op"] == "estimate", "sent once its turn came"
    finally:
        client.stop()
        registry.quit(timeout=30)
    deadline = time.monotonic() + 10
    while not any("arrivals worker" in line for line in logged) and time.monotonic() < deadline:
        time.sleep(0.05)
    end = [line for line in logged if line.startswith(f"arrivals worker ({language}")]
    assert end and "2 answered" in end[0] and "the window ended it" in end[0], end


class _Opener:
    def __init__(self):
        self.hosts = []

    def __call__(self, language, say=None, working=None, generate=None):
        host = _Host()
        self.hosts.append(host)
        return host


class _Host:
    def __init__(self):
        self.calls = []

    def poke(self): self.calls.append("poke")
    def catch_up(self): self.calls.append("catch_up")
    def after_generate(self): self.calls.append("after_generate")
    def close(self): self.calls.append("close")
    def stop(self): self.calls.append("stop")
    def busy(self): return False


def test_the_reorder_catch_up_waits_for_its_turn_and_a_move_never_does(monkeypatch):
    from app import replan_preview
    from app.services import replan_host as R
    monkeypatch.setattr(R, "_automation_on", lambda settings, language: True)
    monkeypatch.setattr(R, "_update_staged", lambda: False)
    monkeypatch.setattr(replan_preview, "SETTLE_S", 0.0)
    held = {"now": G.REVIEWING}
    monkeypatch.setattr(G, "hold", lambda kind: held["now"] if kind == "replan" else None)
    timers = []
    opener = _Opener()
    host = R.ReplanHost(jobs.JobRegistry(), lambda: {}, "ja", opener=opener)
    host._timer = lambda delay, call: timers.append((delay, call))
    try:
        host.catch_up()
        host.catch_up()                             # the same ask while one waits: one timer
        host.after_generate()
        host.worker.idle(5)
        assert not opener.hosts, "no helper spawned for a held catch-up"
        assert [d for d, _c in timers] == [R.TURN_LOOK_S, R.TURN_LOOK_S]
        host.poke()                                 # a move: a press goes first
        host.worker.idle(5)
        assert opener.hosts and opener.hosts[0].calls == ["poke"]
        held["now"] = None
        for _d, call in timers:
            call()
        host.worker.idle(5)
        assert opener.hosts[0].calls == ["poke", "catch_up", "after_generate"]
    finally:
        host.stop()


def test_a_covers_round_waits_for_its_turn(monkeypatch):
    from app.services import covers_online
    held = {"looks": 0}

    def hold(kind):
        assert kind == "covers"
        held["looks"] += 1
        return G.BUSY_NOW if held["looks"] < 3 else None
    monkeypatch.setattr(G, "hold", hold)
    monkeypatch.setattr(G, "STEP_LOOK_S", 0.01)
    rounds = []

    class _Writer:
        def can_write(self):
            return True
    fetcher = covers_online.Fetcher("ja", _Writer(), settings=lambda: {"covers_download": False})
    monkeypatch.setattr(fetcher, "run_once", lambda: rounds.append(held["looks"]) or 0)
    fetcher.want([])
    with fetcher._cond:
        fetcher._queue["w"] = object()
        fetcher._cond.notify_all()
    fetcher._start()
    deadline = time.monotonic() + 10
    while not rounds and time.monotonic() < deadline:
        time.sleep(0.01)
    fetcher.stop()
    assert rounds and rounds[0] == 3, "the round ran only once its turn came"


def test_a_second_busy_spell_holds_from_its_own_start():
    # why (review): the first spell's clock, kept, let the next spell hold nothing — it read as 300 s overdue at once
    w = _World(gentle=False)
    w.g.ready()
    w.load.share = 0.95
    w.later(G.TICK_S)
    job, _ = w.submit("covers")
    assert job.reason == G.BUSY_NOW
    w.load.share = 0.1
    for _ in range(int(G.LOAD_WINDOW_S) + 1):
        w.later(G.TICK_S)
    job.finish()
    w.clock.now += G.HOLD_MAX_S * 3
    w.load.share = 0.95
    for _ in range(int(G.LOAD_WINDOW_S) + 1):
        w.later(G.TICK_S)
    again, _ = w.submit("covers")
    assert again.reason == G.BUSY_NOW


def test_a_press_lets_its_kind_through_every_hold_and_the_hold_comes_back_after():
    w = _World(gentle=True, reviewing=True)
    job, started = w.submit("arrivals-ja")
    assert job.reason == G.WINDOW_FIRST
    G.press("arrivals-ja", True)
    assert job.state == jobs.RUNNING and started, "Finished's *What if*: its worker starts at once"
    assert G.hold("arrivals-ja") is None and G.hold("arrivals-zh") == G.WINDOW_FIRST, "that kind alone"
    G.press("arrivals-ja", False)
    assert G.hold("arrivals-ja") == G.WINDOW_FIRST


def test_a_pressed_estimate_goes_before_the_held_ones_and_a_long_hold_kills_no_healthy_worker(monkeypatch):
    import queue
    from app import path_utils
    from app.services import arrivals as A
    logged = []
    monkeypatch.setattr(path_utils, "write_app_log", logged.append)
    monkeypatch.setattr(A, "STUCK", 0.4)                  # a hold longer than this is no time the worker took
    monkeypatch.setattr(G, "STEP_LOOK_S", 0.05)
    w = _World(gentle=False)
    w.g.ready()
    client = A.ArrivalsWorker(w.registry, "ja", command=[sys.executable, "-c", _ECHO])
    got = queue.Queue()
    try:
        client.stats(callback=got.put)
        assert got.get(timeout=30)["op"] == "stats"
        w.review = True
        w.g._asked_at = w.clock.now
        w.later(G.REVIEW_LOOK_S)
        assert w.g.reviewing
        held = client.estimate(JA, callback=got.put)
        time.sleep(0.8)                                   # held past STUCK
        pressed = client.estimate(ZH, callback=got.put, pressed=True)
        first = got.get(timeout=15)
        assert first["id"] == pressed, "your press goes before the estimate waiting for its turn"
        w.review = False
        w.later(G.REVIEW_LOOK_S)
        assert got.get(timeout=15)["id"] == held
    finally:
        client.stop()
        w.registry.quit(timeout=30)
    deadline = time.monotonic() + 10
    while not any(line.startswith("arrivals worker") for line in logged) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any("stuck" in line for line in logged), logged


# --- the library store's helper: one at a time (a 3.0.16 problem report: five within 50 s of a start) ------------ #
class _Running:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_no_second_helper_starts_while_one_this_program_started_runs(monkeypatch, tmp_path, language,
                                                                    real_store_helper):
    from app import library_store as LS
    from app.connect import power as P
    started = []
    monkeypatch.setattr(LS, "update_staged", lambda: False)
    monkeypatch.setattr(LS, "_spawned", {})
    monkeypatch.setattr(LS, "_owed", set())
    monkeypatch.setattr(P, "popen_below_normal", lambda args, **k: started.append(args) or _Running())
    first = LS.spawn_maintain(language)
    assert first is not None and len(started) == 1
    assert LS.spawn_maintain(language) is None and LS.spawn_maintain(language) is None, "a burst starts one"
    assert len(started) == 1 and LS.take_owed(language) and not LS.take_owed(language), "the ask remembered once"
    other = "zh" if language == "ja" else "ja"
    assert LS.spawn_maintain(other) is not None, "another language's helper is its own"
    first.code = 0
    assert LS.spawn_maintain(language) is not None and len(started) == 3, "after its end, the next one starts"


def test_no_helper_starts_while_another_program_holds_the_maintenance_lock(monkeypatch, tmp_path, real_store_helper):
    from app import library_store as LS
    from app import path_utils
    from app.connect import power as P
    monkeypatch.setattr(path_utils, "get_data_path", lambda language: str(tmp_path / "data" / language))
    monkeypatch.setattr(LS, "update_staged", lambda: False)
    monkeypatch.setattr(LS, "_spawned", {})
    monkeypatch.setattr(LS, "_owed", set())
    started = []
    monkeypatch.setattr(P, "popen_below_normal", lambda args, **k: started.append(args) or _Running())
    assert not LS.maintain_running("ja")
    assert not os.path.exists(LS.library_db_path("ja", str(tmp_path / "data" / "ja")) + ".lock"), \
        "a look creates nothing"
    db = LS.library_db_path("ja", str(tmp_path / "data" / "ja"))
    holder = LS.MaintenanceLock(db)
    assert holder.try_acquire()                         # an analyzer's in-process steps, the Content Manager's helper
    try:
        assert LS.maintain_running("ja") and LS.spawn_maintain("ja") is None and not started
    finally:
        holder.close()
    assert LS.spawn_maintain("ja") is not None and len(started) == 1


def test_the_windows_helper_check_waits_for_the_boot_and_asks_again(monkeypatch):
    from app import library_store as LS
    from app.services import chores as C
    held = {"now": G.WINDOW_FIRST}
    monkeypatch.setattr(G, "hold", lambda kind: held["now"] if kind == "library-maintain" else None)
    monkeypatch.setattr(LS, "check_mode", lambda language, data_dir, busy_wait=None: ("store", ""))
    opened = []
    monkeypatch.setattr(LS, "open_store", lambda *a, **k: opened.append(1))
    timers = []
    chores = C.Chores(jobs.JobRegistry(), _NoSettings(), "ja", update_staged=lambda: False,
                      timer=lambda delay, call: timers.append((delay, call)) or _Timer(), needed=lambda *a: False,
                      log_folder=None)
    try:
        chores.worker.put(chores._maintain)
        chores.worker.put(chores._maintain)
        chores.worker.idle(5)
        assert not opened, "nothing read, nothing started before the boot"
        assert [d for d, _c in timers] == [C.MAINTAIN_AGAIN], "one check waits, however many asked"
        held["now"] = None
        timers[0][1]()
        chores.worker.idle(5)
        assert opened, "asked again once its turn came"
    finally:
        chores.close(store=False)


class _NoSettings:
    def get(self):
        return {}

    def set(self, changes):
        pass

    def flush(self, timeout=None):
        return True


class _Timer:
    def cancel(self):
        pass


def test_a_helper_asked_for_while_the_windows_own_ran_is_looked_at_again_when_it_ends(monkeypatch):
    from app import library_store as LS
    from app.services import chores as C
    monkeypatch.setattr(LS, "_owed", {"ja"})            # a trigger came while this helper ran
    asked = []
    chores = C.Chores(jobs.JobRegistry(), _NoSettings(), "ja", update_staged=lambda: False,
                      timer=lambda delay, call: _Timer(), needed=lambda *a: False, log_folder=None)
    monkeypatch.setattr(chores, "_maintain", lambda: asked.append("check"))

    class _Ended:
        pid = 4242

        def wait(self):
            return 0

        def poll(self):
            return 0
    try:
        chores._watch(_Ended(), "ja")
        assert _wait_for(lambda: asked == ["check"]), "its end asks the check once more"
        assert not LS.take_owed("ja"), "the ask is taken, never asked twice"
    finally:
        chores.close(store=False)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()
