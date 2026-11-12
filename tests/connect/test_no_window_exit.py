"""Haya-CL (Mattias on 3.0.2: "I had a bunch of surasura-cli.exe running after having closed Surasura … Maybe they
never shut down?"): Connect's 2-minute looks (02 §2a) go on only while a Surasura window is open. When everything left
only waits — on the learner's study, on Anki — and no window is open (closed, crashed, killed), Connect ends instead of
pausing, the ledger keeping every wait; a pause ends within UPDATE_LOOK_S of the last window closing. Work it can do now
is still done. A Connect whose program folder now holds another build stops at the step boundary and starts the
folder's own Connect (never an old version's Connect beside a new one: Mattias's #7J3960).

What a wrong answer would cost: a surasura-cli.exe looking every 2 minutes for hours after the window closed (the
field report; it also holds Setup's AppMutex, so Setup says Surasura is running with no window open), or the other
way, an exit that drops work: a job's wait lost, a hato drop never mined with the window closed, a Connect started
again and again with no window to wait for.

Against `FakeSteps` (real words); the window's presence is a real running mark (`locks.hold_running("window")`) held
by a child process, killed as a crash would end it. Never a live Anki.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest

from app.cli import connect_verbs
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPLACED = getattr(runner, "REPLACED", "(no REPLACED before Haya-CL)")     # red-first collects
WAITING = {"cap": 300, "waiting": 300}     # the learner's cap reached: "Your 300 cards are waiting" (an outside wait)


class Steps(FakeSteps):
    """FakeSteps with the window's look and the build's look as the plan says (`window`: a bool or a list of
    answers in turn, the last repeated; `replaced`)."""

    def window_open(self):
        answers = self.plan.get("window", True)
        if isinstance(answers, list):
            self.log.append(("window",))
            looked = sum(1 for e in self.log if e[0] == "window")
            return answers[min(looked, len(answers)) - 1]
        return answers

    def replaced(self):
        return bool(self.plan.get("replaced"))


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=4, **kw):
    steps = Steps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))
    slept = []
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=slept.append, looks=looks, **kw)
    return steps, summary, slept


def test_with_no_window_open_a_connect_that_only_waits_ends_and_the_ledger_keeps_the_wait(tmp_path, ledger):
    # why: the field report — a Connect waiting on the learner's study looked every 2 minutes for hours after the
    # window closed; it must end at once, and the job's wait must stay for the next start to read
    _steps, summary, slept = _run(tmp_path, ledger, dict(WAITING, window=False))
    assert slept == [], "no 2-minute pause with no window open"
    assert summary["looks"] == 1 and summary.get("no_window") is True
    assert "stopped" not in summary, "not a stop: nothing for the window to show as one"
    job = ledger.jobs("ja")[0]
    assert job["state"] == "waiting" and job["reason"].startswith("Your 300 cards are waiting"), job


def test_with_a_window_open_it_still_looks_every_2_minutes(tmp_path, ledger):
    # why: while the window is open nothing changes: the looks are what lets cards come as you study
    _steps, summary, slept = _run(tmp_path, ledger, dict(WAITING, window=True), looks=3)
    assert slept == [runner.LOOK_EVERY_S] * 2 and "no_window" not in summary


def test_the_window_closing_during_the_waits_ends_connect_at_its_next_look(tmp_path, ledger):
    # why: the window open at the first look and closed during the pause: the next look is the last one
    _steps, summary, slept = _run(tmp_path, ledger, dict(WAITING, window=[True, False]), looks=5)
    assert slept == [runner.LOOK_EVERY_S] and summary["looks"] == 2 and summary.get("no_window") is True


def test_work_it_can_do_now_is_done_with_no_window_open(tmp_path, ledger):
    # why: a hato drop with the window closed, or a batch the window's close came in the middle of, is still mined:
    # only waiting needs a window
    steps, summary, slept = _run(tmp_path, ledger, {"window": False})
    assert ledger.jobs("ja")[0]["state"] == "done" and any(e[0] == "mine" for e in steps.log)
    assert slept == [] and "no_window" not in summary, "it ended because nothing was left, as before"


def test_a_stand_in_without_the_look_or_a_look_that_fails_waits_as_before(tmp_path, ledger):
    # why: an exit on a failed look would leave the work for nobody; waiting is the old, safe answer
    class Failing(Steps):
        def window_open(self):
            raise OSError("the running marks can't be listed")
    steps = Failing(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **WAITING))
    slept = []
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=slept.append, looks=2)
    assert slept == [runner.LOOK_EVERY_S] and "no_window" not in summary
    assert runner._window_open(object()) is True and runner._replaced(object()) is False


def test_the_pause_ends_within_a_step_once_the_last_window_closes(tmp_path, ledger, monkeypatch):
    # why: Connect must not sit out the rest of a 2-minute pause after the window closed: the pause asks every
    # UPDATE_LOOK_S, as it does for an update staged
    monkeypatch.setattr(runner, "UPDATE_LOOK_S", 0.05)
    monkeypatch.setattr(runner, "LOOK_EVERY_S", 30)
    steps = Steps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, window=[True, True, False],
                                      **WAITING))
    started = time.monotonic()
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, looks=5)
    assert time.monotonic() - started < 10, "the 30 s pause was cut short"
    assert summary["looks"] == 2 and summary.get("no_window") is True


def test_an_inbox_it_couldnt_read_is_named_so_the_next_connect_isnt_started_for_it(tmp_path, ledger):
    # why: `_loop` starts no Connect again for a pending inbox only when the run says it couldn't read it; without the
    # mark a busy store with no window open becomes a start every half second
    class Unreadable(Steps):
        def consume(self, lang, ledger):
            raise OSError("the library store is busy")
    steps = Unreadable(str(tmp_path), {"line": {"ja": [1]}, "window": False})
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert summary.get("no_window") is True and summary.get("inbox_unread") is True
    _steps, read, _slept = _run(tmp_path, ledger, dict(WAITING, window=False))
    assert read.get("no_window") is True and "inbox_unread" not in read, "an inbox read: only no_window"


def test_a_newer_build_under_a_running_connect_stops_it_at_the_step_boundary(tmp_path, ledger):
    # why: #7J3960 — never an old version's Connect working on beside the new version: the folder's own takes over
    steps, summary, slept = _run(tmp_path, ledger, {"replaced": True})
    assert summary.get("stopped") == REPLACED
    assert not any(e[0] == "mine" for e in steps.log), "nothing mined by the old build"
    assert not any(j["state"] == "done" for j in ledger.jobs("ja")), "the inbox and its job wait for the new Connect"


@pytest.mark.parametrize("summary, pending, woken, kicked", [
    ({"no_window": True, "inbox_unread": True}, True, False, False),    # an inbox it couldn't read: never a loop
    ({"no_window": True, "inbox_unread": True}, True, True, True),      # but a kick since its last look still goes
    ({"no_window": True}, True, False, True),       # a drop that landed after its last read (hato): read by the next
    ({"no_window": True}, False, True, True),       # a kick since its last look (hato's drop): read by the next one
    ({"no_window": True}, False, False, False),     # nothing waits for it: it stays ended
    ({}, True, False, True),                        # with a window: as before, a pending inbox starts the next
    ({"stopped": REPLACED}, False, False, True),     # the new build's Connect takes over
    ({"stopped": runner.SWITCHED_OFF}, True, True, False),  # a stop is a stop
])
def test_after_the_run_the_next_connect_is_started_only_when_someone_waits_for_it(monkeypatch, summary, pending,
                                                                                   woken, kicked):
    # why: the exit with no window must not become a loop of starts (each 0.5 s, for ever, while the inbox is
    # unreadable), and must not lose a hato drop that came during its last look
    kicks = []
    monkeypatch.setattr(runner, "run", lambda loaded, languages, looks=None: dict(summary))
    monkeypatch.setattr(connect_verbs, "_pending", lambda lang: pending)
    monkeypatch.setattr(connect_verbs, "_woken_since", lambda s: woken)
    monkeypatch.setattr(connect_verbs, "_kick", lambda loaded: kicks.append(loaded))
    connect_verbs._loop({}, ["ja"])
    assert bool(kicks) is kicked


# --- The real look: another program's running mark, its process killed as a crash ends it ------------------------ #
_HOLDER = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, sys.argv[1])
    from app import locks
    assert locks.hold_running(sys.argv[2])
    if sys.argv[3] == "no-record":          # a window just starting: its mark taken, its record not written yet
        for name in os.listdir(os.path.join(os.environ["SURASURA_TEST_ROOT"], "local", "locks", "running")):
            if name.startswith(f"{os.getpid()}-") and name.endswith(".json"):
                os.remove(os.path.join(os.environ["SURASURA_TEST_ROOT"], "local", "locks", "running", name))
    print("held", flush=True)
    time.sleep(120)
""")


def _hold(kind, record="record"):
    """A child holding a running mark of `kind` (the test root is the parent's) -> the process, once held."""
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, REPO, kind, record], stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def _end(proc):
    proc.kill()
    proc.wait(10)


@pytest.mark.parametrize("kind, record, open_", [("window", "record", True), ("dashboard", "record", True),
                                                 ("--hud", "record", True), ("cli", "record", False),
                                                 ("mcp", "record", False), ("analyzer", "record", False),
                                                 ("cli", "no-record", True)])
def test_the_real_look_sees_a_window_by_its_running_mark_and_nothing_else(kind, record, open_):
    # why: only a window keeps Connect waiting — another command line (Piyo's server, a hato call) never does — and
    # a mark whose record isn't written yet counts as a window (one just starting), never as none
    assert runner.Steps.window_open(None) is False, "no other program: no window"
    proc = _hold(kind, record)
    try:
        assert runner.Steps.window_open(None) is open_
    finally:
        _end(proc)
    assert runner.Steps.window_open(None) is False, "a killed window's mark is let go by the OS"


def test_from_source_the_build_look_never_says_replaced():
    # why: a source run has no build stamp: it must never stop itself as replaced
    assert runner.Steps.replaced(None) is False


_CONNECT = textwrap.dedent("""
    import json, os, sys
    sys.path.insert(0, sys.argv[1])
    from app.connect import runner
    from app.connect.ledger import Ledger
    from tests.connect.test_no_window_exit import Steps
    runner.UPDATE_LOOK_S, runner.LOOK_EVERY_S = 0.2, 600
    plan = json.loads(sys.argv[2])
    steps = Steps(plan["folder"], plan)
    said = []
    def window_open():                                              # the real look, at the real running marks
        if not said:
            said.append(True)
            print("looked", flush=True)                             # its first look done: the test may go on
        return runner.Steps.window_open(steps)
    steps.window_open = window_open
    with Ledger(os.path.join(plan["folder"], "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, looks=50)
        print(json.dumps({"summary": summary, "jobs": ledger.jobs("ja")}, default=str),
              flush=True)
""")


def _connect(tmp_path):
    plan = dict({"folder": str(tmp_path), "line": {"ja": [1]}, "queue": {"ja": [1]}}, **WAITING)
    return subprocess.Popen([sys.executable, "-c", _CONNECT, REPO, json.dumps(plan)], stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8")


def _answer(proc, within):
    try:
        out, _ = proc.communicate(timeout=within)
    except subprocess.TimeoutExpired:
        proc.kill()                 # still waiting: the failure this file guards against; never a leaked child
        proc.communicate(timeout=10)
        raise AssertionError(f"Connect still running {within} s on") from None
    assert proc.returncode == 0, out
    return json.loads(out.strip().splitlines()[-1])


def test_a_waiting_connect_process_ends_within_seconds_of_its_window_being_killed(tmp_path):
    # why: the field report end to end — a Connect child waiting on the learner, the window a separate process that is
    # killed (a crash, Task Manager's End task): no surasura-cli left looking; the wait kept for the next start
    window = _hold("window")
    connect = _connect(tmp_path)
    try:
        assert connect.stdout.readline().strip() == "looked", "its first look"
        time.sleep(0.6)                 # three of its 0.2 s pause steps with the window open
        assert connect.poll() is None, "with the window open Connect waits on"
        _end(window)
        killed = time.monotonic()
        answer = _answer(connect, within=30)
        assert time.monotonic() - killed < 10, "it ended within seconds, not at its 10-minute look"
    finally:
        _end(window)
        if connect.poll() is None:
            connect.kill()
            connect.wait(10)
    assert answer["summary"].get("no_window") is True and answer["summary"]["looks"] >= 2
    assert [j["state"] for j in answer["jobs"]] == ["waiting"]


def test_a_waiting_connect_process_started_with_no_window_ends_at_its_first_look(tmp_path):
    # why: hato's hand-over with the window closed while Anki's cards wait: one look, then nothing left running
    started = time.monotonic()
    answer = _answer(_connect(tmp_path), within=30)
    assert answer["summary"]["looks"] == 1 and answer["summary"].get("no_window") is True
    assert time.monotonic() - started < 20
