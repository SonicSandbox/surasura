"""The Generate controller (`app/services/generate.py`) — W1.3, the window's spec 04 §4.2.

What a wrong answer would cost:
  * a frozen window — a request that waits on `results` (another program's Generate) on the window's thread;
  * a request nobody can take back — P1.2 left the cancel for a Generate waiting its turn to W1.3;
  * a half-written list — a cancel that ends the analyzer while it writes the CSVs (not atomic yet): from *Writing your
    list* a cancel must wait for the end;
  * a burst of runs — every settings change a full Generate, where one run after the changes settle is enough;
  * a failure that hides — a crash must say `failed`, with where the log is, never a box.

Real Japanese files and the real analyzer as a child (under the test's own root) where the claim is about the run; a
scripted child (a launcher feeding real protocol lines) where the claim is about timing that must not depend on luck.
"""
import hashlib
import json
import os
import threading
import time

import pytest

from app.services import generate as G
from app.services import jobs as J
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse: the child's store, in-process)


_REAL_ANALYZER_ARGS = __import__("app.run_args", fromlist=["x"]).analyzer_args   # before any stand-in


@pytest.fixture(autouse=True)
def _real_runs_write_the_journey_but_never_open_it(monkeypatch):
    """A user's Generate opens the Journey in the browser when it ends (the app's, by design); these tests ask for that
    run and only read its state and files, so its child gets --no-open (run_args' headless argv): no page opens on
    this desktop (tests/harness_guards.py fails a test that opens one)."""
    from app import run_args
    real = run_args.analyzer_args
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, headless=False, opens=True:
                        real(settings, language, headless=True, opens=opens))


def _settings(lang="ja"):
    return {"target_language": lang, "anki_connect_url": "http://127.0.0.1:9"}


def _record(controller):
    seen = []
    controller.subscribe(seen.append)
    return seen


def _outputs(skip=()):
    folder = os.path.join(h.root(), "results")
    return {name: hashlib.sha256(open(os.path.join(folder, name), "rb").read()).hexdigest()
            for name in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, name)) and name not in skip}


def _settled(controller, seconds=300):
    return h.until(lambda: controller.state().state in (G.CURRENT, G.STALE, G.FAILED, G.IDLE)
                   and controller._run is None, seconds=seconds)


# --- real runs -------------------------------------------------------------------------------------------------- #
def test_a_real_generate_goes_queued_running_current_with_its_steps(monkeypatch):
    h.seed_library("ja")
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    seen = _record(controller)
    lines = []
    controller.on_text(lines.append)
    controller.request("ja", settings=_settings())
    assert _settled(controller)
    states = [s.state for s in seen]
    assert states[0] == G.QUEUED and G.RUNNING in states and states[-1] == G.CURRENT, states
    steps = [s.step for s in seen if s.step]
    assert steps and steps[0] == "Reading your files" and "Writing the journey" in steps
    assert any("Saved priority list" in line for line in lines), "the analyzer's own lines reach the log"
    job = registry.snapshot()[-1]
    assert job.kind == "generate" and job.state == J.DONE and not job.cancelled
    assert os.path.exists(os.path.join(h.root(), "results", "run_signature.txt"))

    seen.clear()
    done = threading.Event()
    controller.check(_settings(), "ja", then=lambda answer: done.set())
    assert done.wait(60) and controller.state().state == G.CURRENT


def test_a_request_while_another_program_holds_results_returns_at_once_waits_and_can_be_cancelled():
    h.seed_library("ja")
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    waits = []
    with h.Holder("results", "Generate"):
        run, ms = h.timed(lambda: controller.request("ja", settings=_settings(), on_wait=waits.append))
        assert ms <= h.AT_ONCE_MS, ms
        assert h.until(lambda: controller.state().message == "Waiting for Generate to finish", seconds=10)
        assert controller.state().state == G.QUEUED and waits and waits[0]["verb"] == "Generate"
        _, cancel_ms = h.timed(controller.cancel)
        assert cancel_ms <= h.AT_ONCE_MS, cancel_ms
        assert _settled(controller, 10)
        assert run.proc is None, "nothing started"
        assert registry.snapshot()[-1].cancelled
    controller.request("ja", settings=_settings())         # free now: it runs
    assert _settled(controller) and controller.state().state == G.CURRENT


def test_the_window_closing_drops_a_run_still_waiting():
    h.seed_library("ja")
    closing = threading.Event()
    controller = GenerateController(JobRegistry(), closing=closing, settle=0)
    with h.Holder("results", "Generate"):
        run = controller.request("ja", settings=_settings(), cancel_event=closing)
        assert h.until(lambda: controller.state().state == G.QUEUED and controller.state().message, seconds=10)
        closing.set()
        assert _settled(controller, 10)
    assert run.proc is None


def test_three_requests_in_a_fifth_of_a_second_make_one_run():
    h.seed_library("ja")
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0.4)
    for _ in range(3):
        controller.request("ja", settings=_settings())
        threading.Event().wait(0.06)
    assert _settled(controller)
    assert len([v for v in registry.snapshot() if v.kind == "generate"]) == 1


def test_a_request_during_a_run_runs_exactly_once_after_it(monkeypatch):
    h.seed_library("ja", copies=30)
    monkeypatch.setenv("SURASURA_FORCE_RUN", "1")
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    controller.request("ja", settings=_settings())
    assert h.until(lambda: controller.state().state == G.RUNNING, seconds=60)
    controller.request("ja", settings=_settings())
    controller.request("ja", settings=_settings())
    assert h.until(lambda: len([v for v in registry.snapshot() if v.kind == "generate"]) == 2, seconds=300)
    assert _settled(controller)
    gens = [v for v in registry.snapshot() if v.kind == "generate"]
    assert len(gens) == 2 and all(v.state == J.DONE and not v.cancelled for v in gens)


def test_a_cancel_while_reading_files_stops_the_run_itself_and_leaves_the_last_journeys_files(monkeypatch):
    """The run stops itself at its next file (the cancel file): the other 12 outputs byte for byte as they were; the stamp
    the analyzer dropped as it started stays gone, so the journey is stale and the next Generate runs it again."""
    h.seed_library("ja", copies=40)
    controller = GenerateController(JobRegistry(), settle=0)
    controller.request("ja", settings=_settings())
    assert _settled(controller) and controller.state().state == G.CURRENT
    before = _outputs(skip=("run_signature.txt",))
    assert len(before) == 12

    monkeypatch.setenv("SURASURA_FORCE_RUN", "1")
    run = controller.request("ja", settings=_settings())
    assert h.until(lambda: run.step == "Reading your files", seconds=120)
    controller.cancel()
    assert _settled(controller, 60)
    assert controller.state().state == G.STALE and run.cancel_sent
    assert run.proc.returncode == 76 and run.final[1]["code"] == "cancelled"
    assert _outputs(skip=("run_signature.txt",)) == before
    assert not os.path.exists(os.path.join(h.root(), "results", "run_signature.txt"))
    assert not os.path.exists(run.cancel_file), "the cancel file goes with its run"


# --- a scripted child: the cancel rule, failure and the races, step by step --------------------------------------- #
class _Child:
    """Stands in for the analyzer's Popen; the test feeds its lines and ends it."""

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


def _scripted(controller, cancel_folder=None):
    holder = {"launches": 0}

    def launcher(run):
        holder["launches"] += 1
        holder["run"] = run
        holder["child"] = _Child()
        if cancel_folder is not None:
            run.cancel_file = os.path.join(cancel_folder, f"cancel-{holder['launches']}.flag")
        run.started(holder["child"])
    return holder, launcher


def _line(step, done=None, total=None):
    return json.dumps({"type": "progress", "step": step, "done": done, "total": total}) + "\n"


CANCELLED = json.dumps({"type": "error", "contract": 1, "ok": False, "code": "cancelled", "message": "x"}) + "\n"
RESULT = json.dumps({"type": "result", "contract": 1, "ok": True, "ran": True}) + "\n"
FLAGGED = ["analyzer.py", "--progress-json"]


def test_a_cancel_asks_the_run_and_its_cancelled_answer_leaves_the_journey_stale():
    """The controller never ends the child: it makes the run's cancel file, and the run answers."""
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller, h.root())
    controller.request("ja", argv=FLAGGED, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    run = holder["run"]
    run.feed(_line("Counting words"))
    controller.cancel()
    assert os.path.exists(run.cancel_file)
    assert controller.state().state == G.CANCELLING and controller.state().message.startswith("Stopping")
    run.feed(CANCELLED)
    holder["child"].returncode = 76
    run.ended(76)
    assert controller.state().state == G.STALE and registry.snapshot()[-1].cancelled


def test_a_run_past_writing_your_list_finishes_and_the_journey_is_current():
    """The run had reached *Writing your list* when the cancel came: it finishes (its answer is the result line)."""
    controller = GenerateController(JobRegistry(), settle=0)
    holder, launcher = _scripted(controller, h.root())
    controller.request("ja", argv=FLAGGED, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder["run"].feed(_line("Picking sentences"))       # as read: the child may be further on
    controller.cancel()
    holder["run"].feed(_line("Writing your list"))
    holder["run"].feed(RESULT)
    holder["run"].ended(0)
    assert controller.state().state == G.CURRENT


def test_a_run_past_its_cancel_point_is_waited_for_when_the_window_closes():
    """E20 ("Generate is cancelled cleanly (the last good journey kept)"): before *Writing your list* closing the window
    cancels the run; from there it can't stop, so its job quits with `wait`, as an Anki write — said as soon as the
    line is read (never held back with the coalesced progress) and before the bar hears the step."""
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller, h.root())
    controller.request("ja", argv=FLAGGED, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    run = holder["run"]
    run.feed(_line("Picking sentences"))
    assert run.job.on_quit == "cancel" and J.waits_at_quit(registry.snapshot()) == ()
    heard = []
    registry.subscribe(lambda views: heard.append([(v.on_quit, v.progress) for v in views if v.kind == "generate"]))
    run.feed(_line("Writing your list"))
    assert [v.id for v in J.waits_at_quit(registry.snapshot())] == [run.job.id]
    assert all(on_quit == "wait" for seen in heard for on_quit, progress in seen
               if progress is not None and progress.step == "Writing your list")
    run.feed(RESULT)
    run.ended(0)
    assert controller.state().state == G.CURRENT


def test_a_run_started_without_the_flag_is_never_asked_and_a_cancel_waits_for_its_end():
    """The Tk dashboard's runs (their argv is pinned): no cancel file, no kill; the bar says it finishes."""
    controller = GenerateController(JobRegistry(), settle=0)
    holder, launcher = _scripted(controller, h.root())
    controller.request("ja", argv=["analyzer.py", "--static"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    controller.cancel()
    assert not os.path.exists(holder["run"].cancel_file)
    assert controller.state().message == "Finishing: Generate can't stop part-way here"
    holder["run"].ended(0)
    assert controller.state().state == G.CURRENT


def test_a_cancel_before_the_child_starts_is_honoured_when_it_starts():
    controller = GenerateController(JobRegistry(), settle=0)
    holder = {}

    def launcher(run):
        controller.cancel()                         # the cancel lands as the child is being started
        holder["run"] = run
        run.cancel_file = os.path.join(h.root(), "early.flag")
        run.started(_Child())
    controller.request("ja", argv=FLAGGED, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    assert os.path.exists(holder["run"].cancel_file), "asked as soon as it started"
    holder["run"].ended(76)


def test_a_crash_is_failed_with_the_logs_path_never_a_box():
    controller = GenerateController(JobRegistry(), settle=0, log_folder=os.path.join(h.root(), "logs"))
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder["run"].ended(3221225477)                          # 0xC0000005: a native fault
    state = controller.state()
    assert state.state == G.FAILED and state.log_path == controller.log_path()
    assert controller.log_path() in state.message


def test_a_launcher_that_raises_is_failed_and_the_next_request_runs():
    controller = GenerateController(JobRegistry(), settle=0)

    def broken(run):
        raise OSError("the analyzer is missing")
    controller.request("ja", argv=["analyzer.py"], launcher=broken)
    assert h.until(lambda: controller.state().state == G.FAILED, seconds=10)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder["run"].ended(0)
    assert controller.state().state == G.CURRENT


def test_neither_the_users_generate_nor_an_automatic_one_opens_the_journey():
    """Laptop fixes (Sonic: "the journey should never automatically pop up anymore. It pops up after the first one on
    load"): the window's runs — the setup wizard's first Generate and the button's, as well as the automatic ones —
    write the journey with `--no-open`; it opens only from the header's *Journey ↗* (or a link the learner clicks)."""
    controller = GenerateController(JobRegistry(), settle=0)
    seen = []

    def launcher(run):
        seen.append((run.quiet, list(run.argv)))
        raise OSError("stand-in: the argv is all this test reads")
    for quiet in (False, True):
        controller.request("ja", settings=_settings(), quiet=quiet, launcher=launcher)
        assert h.until(lambda: len(seen) == (2 if quiet else 1) and controller.state().state == G.FAILED, seconds=10)
    assert [q for q, _argv in seen] == [False, True]
    for _quiet, argv in seen:
        assert "--no-open" in argv and argv[0] == "analyzer.py" and G.PROGRESS_FLAG in argv


def test_IK2_4_a_run_that_opens_nothing_is_one_rule_in_run_args():
    """IK2-4: `--no-open` comes from `run_args` (`opens=False`), never added by hand beside it: the window's argv is
    the builder's own plus the progress flag; a run that opens nothing never passes `--app-mode` either (the
    command line's `headless` is the same rule). The run signature never reads either, so nothing re-runs."""
    real = _REAL_ANALYZER_ARGS                      # the builder itself: this file's autouse stand-in makes every run headless
    settings = dict(_settings(), open_app_mode=True)
    opens = real(settings, "ja")
    assert "--app-mode" in opens and "--no-open" not in opens                 # the Tk dashboard's Generate, as before
    quiet = real(settings, "ja", opens=False)
    assert "--no-open" in quiet and "--app-mode" not in quiet
    assert quiet == real(settings, "ja", headless=True)
    controller = GenerateController(JobRegistry(), settle=0)
    seen = []

    def launcher(run):
        seen.append(list(run.argv))
        raise OSError("stand-in: the argv is all this test reads")
    controller.request("ja", settings=settings, launcher=launcher)
    assert h.until(lambda: seen and controller.state().state == G.FAILED, seconds=10)
    assert seen[0] == quiet + [G.PROGRESS_FLAG] and seen[0].count("--no-open") == 1


def test_a_restart_request_asks_the_run_to_stop_and_runs_after():
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller, h.root())
    controller.request("ja", argv=FLAGGED, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    first = holder.pop("run")
    first.feed(_line("Counting words"))
    controller.request("ja", argv=FLAGGED, launcher=launcher, restart=True)
    assert os.path.exists(first.cancel_file)
    first.feed(CANCELLED)
    first.ended(76)
    assert h.until(lambda: "run" in holder, seconds=10), "the new request ran after"
    holder["run"].ended(0)
    assert controller.state().state == G.CURRENT
    assert [v.cancelled for v in registry.snapshot() if v.kind == "generate"] == [True, False]


def test_the_generate_job_waits_for_a_running_indexer():
    """Generate ⟂ the indexer (both write the token store): a gated indexer job holds the run back."""
    registry = JobRegistry()
    indexer = registry.submit("indexer", "Indexing", lambda j: None)
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert controller.state().state == G.QUEUED and controller.state().message == "waits for Indexing"
    assert "run" not in holder
    indexer.finish()
    assert h.until(lambda: "run" in holder, seconds=10)
    holder["run"].ended(0)


# --- the review's races (tracks/window/reviews/W1.3-adversary.md #3, #4, #5) ----------------------------------- #
class _SlowRegistry(JobRegistry):
    """submit() takes a moment: the gap between the controller taking a run and knowing its job."""

    def submit(self, *a, **k):
        time.sleep(0.3)
        return super().submit(*a, **k)


@pytest.mark.parametrize("how", ["cancel", "restart"])
def test_a_cancel_or_restart_while_the_job_is_being_made_is_honoured(how):
    controller = GenerateController(_SlowRegistry(), settle=0)
    holder, launcher = _scripted(controller)
    threading.Thread(target=lambda: controller.request("ja", argv=["analyzer.py"], launcher=launcher)).start()
    time.sleep(0.1)
    if how == "cancel":
        controller.cancel()
        assert h.until(lambda: controller._run is None, seconds=5)
        assert holder["launches"] == 0, "nothing started"
    else:
        controller.request("ja", argv=["analyzer.py"], launcher=launcher, restart=True)   # never raises
        assert h.until(lambda: holder["launches"] == 1, seconds=5)
        holder["run"].ended(0)
        assert controller.state().state == G.CURRENT


def test_an_older_state_is_never_delivered_after_a_newer_one():
    """A listener held on a progress update while the run ends: it hears CURRENT last."""
    controller = GenerateController(JobRegistry(), settle=0)
    seen, gate = [], threading.Event()

    def listener(state):
        if state.step == "Counting words":
            gate.set()
            time.sleep(0.4)                     # the window's queue, slow this once
        seen.append(state.state)
    controller.subscribe(listener)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=FLAGGED, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    feeder = threading.Thread(target=lambda: holder["run"].feed(_line("Counting words")))
    feeder.start()
    assert gate.wait(5)
    holder["run"].ended(0)
    feeder.join()
    assert seen[-1] == G.CURRENT, seen


def test_a_users_request_takes_the_place_of_a_waiting_automatic_run():
    registry = JobRegistry()
    indexer = registry.submit("indexer", "Indexing", lambda j: None)
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py", "--no-open"], quiet=True, launcher=launcher)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    indexer.finish()
    assert h.until(lambda: "run" in holder, seconds=10)
    assert holder["launches"] == 1 and not holder["run"].quiet, "the user's run, once; the automatic one dropped"
    holder["run"].ended(0)


def test_a_job_absorbed_by_another_submitter_tells_the_controller():
    """Another part of the window asks the registry for a Generate while the controller's automatic one waits: the
    controller hears its job ended and takes the next request."""
    registry = JobRegistry()
    indexer = registry.submit("indexer", "Indexing", lambda j: None)
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], quiet=True, launcher=launcher)
    other = registry.submit("generate", "Generating", lambda j: None)
    assert h.until(lambda: controller._run is None, seconds=5), "not wedged"
    indexer.finish()
    other.finish()
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder["run"].ended(0)


# --- W3.5 row 7: the journey's label (G7) and the controller's two points from E3.2's review (G8: A12, A13) ------ #
def test_a_generate_the_journey_keeper_starts_reads_journey_updating_sentences_in_the_bar():
    """G7 (W1.2 02-state-model: *Plan current, sentences catching up*): the keeper's background Generate is the bar's
    *Journey: updating sentences…*, not *Generating (automatic)*. The window hands the keeper the controller as
    `labelled(JOURNEY_LABEL)` (journey.py untouched); every other quiet request (AutoGenerate's) keeps its label, and
    the keeper's close (its withdraw) reaches the controller through it."""
    from app.services.journey import JourneyKeeper
    from app.services.status import StatusService
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    status = StatusService(registry)
    holder, launcher = _scripted(controller, h.root())
    keeper = JourneyKeeper(controller.labelled(G.JOURNEY_LABEL), "ja", settings=lambda: {"journey_settle_s": 0},
                           pending=lambda: True, battery=lambda: False, launcher=launcher,
                           plan_path=os.path.join(h.root(), "no-plan.bin"))
    try:
        keeper.changed("move")
        assert h.until(lambda: "run" in holder, seconds=10)
        view = registry.snapshot()[-1]
        assert view.kind == "generate" and view.automatic and view.label == "Journey: updating sentences…"
        assert status.snapshot().lines == ("Journey: updating sentences…",)
        keeper.changed("move")                          # a second burst: never withdrawn (a7), one look after it
        assert not os.path.exists(holder["run"].cancel_file)
        holder["run"].ended(0)
        assert h.until(lambda: holder["launches"] == 2, seconds=10)
        assert registry.snapshot()[-1].label == "Journey: updating sentences…"
    finally:
        keeper.close()                                  # its own run withdrawn through the labelled controller
    assert os.path.exists(holder["run"].cancel_file)
    holder["run"].feed(CANCELLED)
    holder["run"].ended(76)
    assert keeper._ended not in controller._end_listeners, "close unsubscribed through the labelled controller"
    holder2, launcher2 = _scripted(controller)
    controller.request("ja", argv=["analyzer.py", "--no-open"], quiet=True, launcher=launcher2)
    assert h.until(lambda: "run" in holder2, seconds=10)
    assert registry.snapshot()[-1].label == "Generating (automatic)"
    holder2["run"].ended(0)


def test_a_run_that_fails_while_another_waits_reads_failed_and_its_failure_stays_for_the_bar():
    """A12: the user's run fails while the keeper's quiet run waits behind it. The state said `queued` at once, so the
    failure's message and log never reached the window. Now it reads `failed` first; and `failure()` — what the bar's
    Generate line reads — keeps it while the next run runs, until a run finishes cleanly (HR-23)."""
    controller = GenerateController(JobRegistry(), settle=0, log_folder=os.path.join(h.root(), "logs"))
    seen = _record(controller)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    first = holder.pop("run")
    controller.request("ja", argv=["analyzer.py", "--no-open"], quiet=True, launcher=launcher)
    seen.clear()
    first.ended(1)
    assert h.until(lambda: "run" in holder, seconds=10)
    assert seen[0].state == G.FAILED and seen[0].message.startswith("Generate stopped (exit code 1).")
    assert seen[0].log_path == controller.log_path()
    assert controller.state().state == G.RUNNING
    assert controller.failure().startswith("Generate stopped (exit code 1).")
    holder["run"].ended(0)
    assert controller.state().state == G.CURRENT and controller.failure() is None


def test_a_run_dropped_after_a_failure_never_falls_back_to_an_older_current():
    """A12's second half: a clean run (current), then one that fails while the keeper's waits; the keeper's is dropped
    before it starts (withdrawn while another program holds `results`). The state goes back to the failure, never to
    the `current` from before it — the window would take that for a landing."""
    controller = GenerateController(JobRegistry(), settle=0)
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder.pop("run").ended(0)
    assert controller.state().state == G.CURRENT
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    failing = holder.pop("run")
    with h.Holder("results", "Generate"):
        keepers = controller.request("ja", argv=["analyzer.py", "--no-open"], quiet=True, launcher=launcher)
        failing.ended(1)
        assert h.until(lambda: controller.state().message == "Waiting for Generate to finish", seconds=10)
        controller.withdraw(keepers)
        assert _settled(controller, 10)
    assert "run" not in holder, "the keeper's run never started"
    state = controller.state()
    assert state.state == G.FAILED and state.message.startswith("Generate stopped (exit code 1).")


def test_a_withdrawn_run_that_finishes_anyway_is_recorded_done_not_cancelled():
    """A13: the keeper withdraws its run once it is writing your list; the run can't stop there and finishes, writing
    the lists and the plan. It is a finished Generate — the journey `current`, its end told as "current" — and the
    registry records it done, not cancelled (it was: `_cancel_job` set the flag at running → cancelling and the end
    kept it), so the bar never calls a Generate that wrote everything a cancel."""
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    ends = []
    controller.on_end(lambda run, outcome: ends.append(outcome))
    holder, launcher = _scripted(controller, h.root())
    run = controller.request("ja", argv=FLAGGED + ["--no-open"], quiet=True, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder["run"].feed(_line("Writing your list"))
    controller.withdraw(run)
    assert registry.snapshot()[-1].state == J.CANCELLING
    holder["run"].feed(RESULT)
    holder["run"].ended(0)
    view = registry.snapshot()[-1]
    assert (view.state, view.cancelled) == (J.DONE, False)
    assert controller.state().state == G.CURRENT and ends == ["current"]


def test_a_japanese_failure_never_reads_in_the_chinese_bar_and_goes_on_a_switch_or_a_current_check(monkeypatch):
    """The bar's Generate line (`failure()`) is kept per controller, so a Japanese run that failed stayed on the bar
    after a switch to Chinese — a failure the Chinese journey never had. Asked for a language, `failure(language)`
    gives only that language's run's failure; a language switch forgets it (`forget_failure`); and a journey check that
    finds the journey current (another program generated cleanly) clears it too."""
    controller = GenerateController(JobRegistry(), settle=0, log_folder=os.path.join(h.root(), "logs"))
    holder, launcher = _scripted(controller)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder.pop("run").ended(1)
    assert controller.failure("ja").startswith("Generate stopped (exit code 1).")
    assert controller.failure("zh") is None, "the Chinese bar read the Japanese failure"
    controller.forget_failure()                                  # the window switched to Chinese
    assert controller.failure() is None and controller.failure("ja") is None
    # a failure again; then another program's clean Generate makes the check say current
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    holder.pop("run").ended(1)
    assert controller.failure("ja")
    from app import analyzer
    monkeypatch.setattr(analyzer, "journey_is_current", lambda args, language: True)
    other = threading.Event()
    controller.check(_settings("zh"), "zh", then=lambda answer: other.set())
    assert other.wait(10)
    assert controller.failure("ja"), "the Chinese journey being current cleared the Japanese failure"
    checked = threading.Event()
    controller.check(_settings(), "ja", then=lambda answer: checked.set())
    assert checked.wait(10)
    assert controller.failure("ja") is None and controller.state().state == G.CURRENT


# --- the Tk dashboard on the controller ------------------------------------------------------------------------- #
def test_the_dashboards_generate_is_the_controllers_job_and_its_end_reaches_it():
    """The dashboard (2.x's window until W3.5) starts the child itself, through the controller: its run is the
    registry's `generate` job, and its end — told by `_on_generate_exit` — ends the job."""
    import queue
    from unittest.mock import MagicMock
    from app.main import MasterDashboardApp
    app = MagicMock()
    app.gui_queue, app._closing_event = queue.Queue(), threading.Event()
    MasterDashboardApp._start_analyzer(app, ["analyzer.py", "--static", "--language=ja"], quiet=True)
    assert app.run_command_async.call_count == 1                     # a free lock: started at once (under test)
    jobs = app.job_registry.snapshot()
    assert [(v.kind, v.label, v.state, v.automatic) for v in jobs] == [
        ("generate", "Generating (automatic)", J.RUNNING, True)]
    MasterDashboardApp._on_generate_exit(app)
    assert app.job_registry.snapshot()[0].state in (J.DONE, J.FAILED)
    assert app.generate_controller._run is None


def test_every_child_the_dashboard_starts_is_recorded_while_it_runs(monkeypatch):
    """K75's list as jobs: an importer's child is in the registry while it runs and ends with it."""
    import queue
    import subprocess as sp
    from unittest.mock import MagicMock
    from app.main import MasterDashboardApp

    class _Proc:
        returncode = 0
        stdout = None

        def wait(self):
            return 0
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr("app.main.threading.Thread", lambda target=None, **k: MagicMock(start=target))
    app = MagicMock()
    app.gui_queue = queue.Queue()
    MasterDashboardApp.run_command_async(app, ["indexer.py", "--language", "ja"], "Indexer")
    views = app.job_registry.snapshot()
    assert [(v.kind, v.label, v.state, v.gated) for v in views] == [("indexer", "Indexer", J.DONE, False)]


def test_a_run_its_asker_withdrew_is_told_apart_from_one_the_user_stopped():
    """finish-pending FP-A3: the window's press waiting for Anki ends when the learner stops the Generate it waits
    for, never when the journey keeper withdraws its run to ask again after the moves settle — both end cancelled, so
    the controller says which (`withdrawn(job_id)`)."""
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    holder, launcher = _scripted(controller)
    keepers = controller.request("ja", argv=["analyzer.py", "--no-open"], quiet=True, launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    controller.withdraw(keepers)
    holder.pop("run").ended(1)
    taken_back = registry.snapshot()[-1]
    assert taken_back.cancelled and controller.withdrawn(taken_back.id)
    controller.request("ja", argv=["analyzer.py"], launcher=launcher)
    assert h.until(lambda: "run" in holder, seconds=10)
    controller.cancel()
    holder.pop("run").ended(1)
    stopped = registry.snapshot()[-1]
    assert stopped.id != taken_back.id and stopped.cancelled and not controller.withdrawn(stopped.id)
