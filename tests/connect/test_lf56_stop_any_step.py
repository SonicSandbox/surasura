"""Row 56 (laptop round 9 #56): *Stop* reaches every step of a mining job within about a second.

Sonic: "it got to checking the timing, 4% and i clicked it and it just sits there". The runner asked for a press only
between its steps, and every program it waited on — tsubasa's check (up to 120 s), Anki Miner's look-ups — was waited
for whole. One rule now (`app/connect/stopping.py`): every program Connect waits on during a job is waited for in slices
of a second, asking the job's Stop each slice; a look-up is ended at a press and the job stops before that step, while
Anki Miner's run still goes through its cancel file (cards made so far kept whole).

What a wrong answer costs: a press that does nothing for minutes (the app looks frozen), a tsubasa left reading a video
after its job stopped, a card half-written by a killed Anki Miner run, or a Stop counted as Anki Miner failing (two of
those fail the job).

Real child processes (a tsubasa stand-in, the fake Anki Miner as `--api` documents it), `FakeSteps` with real Japanese
words and a real ledger. Never a live Anki, never a real tsubasa or Anki Miner.
"""
import importlib
import json
import logging
import subprocess
import sys
import threading
import time

import pytest

from app.connect import anki_miner, feed, fit_check, runner, status
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)
from tests.connect_helpers import tsubasa_answer

VIDEO = "C:/Video/上層部の話 01.mkv"
SUBTITLE = "C:/Subs/上層部の話 01.srt"
LOOK_UPS = ("version", "profiles", "check", "settings-export")
QUICK = 2.0                 # seconds: a press is acted on within a slice (1 s) plus the process tree's end


def _stopping():
    # imported per test, so each one reports on its own before the module exists
    return importlib.import_module("app.connect.stopping")


def _press_after(seconds):
    began = time.monotonic()
    return lambda: time.monotonic() - began > seconds


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _queue(ledger, item_id):
    with ledger.transaction():
        return ledger.queue("ja", item_id, "user", None, store_id="store-1")


def _ask(ledger, item_id, at):
    with ledger.transaction():
        return ledger.ask("ja", item_id, at, store_id="store-1")


def _run(steps, ledger):
    return runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)


# --- tsubasa: a real child process -------------------------------------------------------------------------------- #
def _tsubasa(tmp_path, seconds, answer=None):
    """A tsubasa stand-in: a program (a .cmd starting this Python on Windows, a shell script elsewhere) that beats into
    a file every 0.05 s for `seconds`, then prints `answer` as tsubasa's `--json` line -> (its path, the beat file)."""
    beat = tmp_path / "beat.txt"
    script = tmp_path / "tsubasa_standin.py"
    script.write_text(
        "import sys, time\n"
        f"end = time.monotonic() + {float(seconds)!r}\n"
        "while time.monotonic() < end:\n"
        f"    with open({str(beat)!r}, 'a') as f:\n"
        "        f.write('.')\n"
        "    time.sleep(0.05)\n"
        f"sys.stdout.write({json.dumps(json.dumps(answer or {}))} + '\\n')\n", encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "tsubasa.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        exe = tmp_path / "tsubasa"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    return str(exe), beat


def _beats_stopped(beat):
    """The stand-in has stopped beating (its process ended, not left reading the video)."""
    before = beat.stat().st_size if beat.exists() else 0
    time.sleep(0.4)
    return (beat.stat().st_size if beat.exists() else 0) == before


def test_tsubasas_check_ends_at_a_press_within_a_second_and_leaves_no_process(tmp_path):
    # #56 itself: tsubasa reading a whole video (here 30 s) — the press ends it, never waits it out
    stopping = _stopping()
    exe, beat = _tsubasa(tmp_path, 30, tsubasa_answer())
    began = time.monotonic()
    with stopping.watching(_press_after(0.3)):
        with pytest.raises(stopping.Stopped):
            fit_check.fit(None, VIDEO, SUBTITLE, tsubasa=exe)
    took = time.monotonic() - began
    assert took < QUICK, f"the press reached tsubasa after {took:.2f} s"
    assert _beats_stopped(beat), "tsubasa was ended with its job, never left running"


def test_tsubasa_past_its_timeout_is_ended_and_asked_again(tmp_path):
    # no press: a check past its timeout is RETRY as before, and the program is ended, not left behind
    exe, beat = _tsubasa(tmp_path, 30, tsubasa_answer())
    verdict, who, why, _offset = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa=exe, timeout=1.2)
    assert (verdict, who) == (fit_check.RETRY, "tsubasa") and "took longer than" in why     # LF56-1: plain words
    assert _beats_stopped(beat)


def test_no_press_tsubasa_answers_as_before_and_a_failing_check_is_no_press(tmp_path, caplog):
    # a check that raises is logged and read as no press: tsubasa's answer (across a slice) decides as always
    stopping = _stopping()
    exe, _beat = _tsubasa(tmp_path, 1.3, tsubasa_answer(segments=((None, -2.4),)))

    def broken():
        raise OSError("the ledger is locked")
    with caplog.at_level(logging.WARNING, logger="surasura-cli"), stopping.watching(broken):
        got = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa=exe)
    assert got == (fit_check.TIMED, "tsubasa", None, -2.4)
    assert any("Stop" in r.getMessage() for r in caplog.records)
    with stopping.watching(lambda: False):
        assert fit_check.fit(None, VIDEO, SUBTITLE, tsubasa=exe) == got
    assert fit_check.fit(None, VIDEO, SUBTITLE, tsubasa=exe) == got, "no job's check installed: as before"


# --- Anki Miner: the look-ups end at a press, the run and any writing verb never ------------------------------------ #
@pytest.mark.parametrize("verb", LOOK_UPS)
def test_anki_miners_look_ups_end_at_a_press(fake_miner, tmp_path, verb):
    stopping = _stopping()
    assert set(anki_miner.LOOK_UPS) == set(LOOK_UPS), "only the read-only verbs; never mine"
    fake_miner.plan(slow={verb: 30})
    args = {"check": ["check", "--language", "ja"],
            "settings-export": ["settings-export", "--language", "ja", "--out", str(tmp_path / "export.json")]}
    began = time.monotonic()
    with stopping.watching(_press_after(0.3)):
        with pytest.raises(stopping.Stopped):
            anki_miner.api(fake_miner.path, args.get(verb, [verb]))
    assert time.monotonic() - began < QUICK


@pytest.mark.parametrize("verb", ["mine", "fetch"])
def test_a_verb_that_may_write_is_never_ended_by_a_press(fake_miner, tmp_path, verb):
    # Anki Miner's run (and any verb not known read-only) finishes: a killed writer could leave a card half-made
    stopping = _stopping()
    assert verb not in anki_miner.LOOK_UPS
    fake_miner.plan(slow={verb: 1.5})
    began = time.monotonic()
    with stopping.watching(lambda: True):
        verdict = anki_miner.api(fake_miner.path, [verb, str(tmp_path / "run-1.json")])
    assert time.monotonic() - began >= 1.5 and verdict["schema"] == 1, "it answered: never ended"


def test_no_press_a_look_up_answers_as_before(fake_miner):
    stopping = _stopping()
    fake_miner.plan(slow={"version": 1.2}, app="3.7.0")
    with stopping.watching(lambda: False):
        assert anki_miner.version(fake_miner.path)["app"] == "3.7.0"
    assert anki_miner.version(fake_miner.path)["app"] == "3.7.0"


def test_a_stop_during_mining_s_look_ups_leaves_the_kept_set_empty(fake_miner, tmp_path):
    # row 25's kept set: a stopped look-up never leaves it half-filled (read again whole when the job goes on)
    stopping = _stopping()
    from app.cli import verbs
    fake_miner.plan(slow={"profiles": 30})
    held = {"set": ("old",), "at": 0.0, "stamp": "old"}
    with stopping.watching(_press_after(0.3)):
        with pytest.raises(stopping.Stopped):
            verbs._anki_miner_setup({"connect_anki_miner_path": fake_miner.path}, "ja", str(tmp_path / "run"),
                                    held=held)
    assert held == {}
    assert "settings-export" not in fake_miner.commands()


def test_anki_miners_run_still_goes_through_its_cancel_file(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # #47 unchanged under the new rule: a press while it mines cancels the run; the cards made so far are kept
    stopping = _stopping()
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(cancel_at=2)
    with stopping.watching(lambda: "mine" in fake_miner.commands()):        # pressed once the run is under way
        done = batch(should_stop=stopping.pressed)
    assert done["stopped"] is True
    assert [o["outcome"] for o in done["outcomes"]][:2] == ["made", "made"]


# --- the runner: the job stops at the step it was in -------------------------------------------------------------- #
def _press_inside(steps, ledger, job_id, name):
    """`steps.<name>` replaced by a program that runs until the job's Stop reaches it (as `stopping.wait` does): the
    press is made from inside the step, then it waits for `pressed()`."""
    stopping = _stopping()

    def until_pressed(lang, job, *a):
        steps.log.append((name + "-started", job["item_id"]))
        ledger.ask_stop(job_id)
        for _ in range(50):
            if stopping.pressed():
                raise stopping.Stopped()
        raise AssertionError(f"the press never reached the {name} step")
    setattr(steps, name, until_pressed)


@pytest.mark.parametrize("step", ["pick", "fit", "mine"])
def test_a_press_during_a_steps_program_stops_the_job_there_and_mine_now_goes_on(tmp_path, ledger, step):
    job_id = _queue(ledger, 1)
    plan = {"line": {"ja": [1]}}
    steps = FakeSteps(str(tmp_path), plan)
    _press_inside(steps, ledger, job_id, step)
    _run(steps, ledger)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
    assert ledger.held_by_stop(job) and not ledger.stop_asked(job_id), "the press used up; it waits for your ask"
    assert job["resume"] is None, "stopped before its first batch: picked again when it goes on (adversary P2.4-A #1)"
    assert steps.anki.words() == [] and not any(e[0] == "mine" for e in steps.log), "nothing mined"
    assert (job["failures"] or 0) == 0, "your Stop is no failure of Anki Miner's"
    if step == "mine":
        assert [b["state"] for b in ledger.batches(job_id)] == ["refused"], "a look-up stopped: the batch never ran"
    # the next look: still held
    again = FakeSteps(str(tmp_path), plan)
    _run(again, ledger)
    assert not any(e[0] == "pick" for e in again.log)
    # *Mine now*: it goes on, every word made once
    _ask(ledger, 1, "2026-10-23T09:00:00.000000Z")
    after = FakeSteps(str(tmp_path), plan)
    _run(after, ledger)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert sorted(after.anki.words()) == sorted(w for w, _r in WORDS[1])
    assert [e[2] for e in after.log if e[0] == "mine"] == [1], "a refused attempt's number is reused"
    assert (ledger.job_by_id(job_id)["failures"] or 0) == 0


def test_the_jobs_check_is_installed_only_around_its_pick_fit_and_mining(tmp_path, ledger):
    stopping = _stopping()
    _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})
    seen = {}
    for name in ("pick", "fit", "mine", "fill", "order"):
        real = getattr(steps, name)

        def spy(*a, _name=name, _real=real):
            seen[_name] = getattr(stopping._here, "check", None) is not None
            return _real(*a)
        setattr(steps, name, spy)
    _run(steps, ledger)
    assert seen == {"pick": True, "fit": True, "mine": True, "fill": False, "order": False}
    assert getattr(stopping._here, "check", None) is None, "taken off when the job leaves it"


# --- the window's hook: the status record and the feed ------------------------------------------------------------- #
@pytest.fixture
def ledger_path(tmp_path):
    path = str(tmp_path / "status-ledger.sqlite")
    with Ledger(path):
        pass
    return path


def _ja(path):
    record = status.read(["ja"], path=path)
    return record, {j["item"]: j for j in record["languages"]["ja"]["jobs"]}


def test_a_pending_press_shows_as_stopping_with_no_second_stop(ledger_path, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    with Ledger(ledger_path) as led:
        pressed_job = led.queue("ja", 101, "test", "ev-1")
        other = led.queue("ja", 102, "test", "ev-1")
        led.set_state(pressed_job, "fit-check")
        led.set_state(other, "mining")
        assert led.ask_stop(pressed_job)
    record, jobs = _ja(ledger_path)
    assert jobs[101]["stopping"] is True and jobs[102]["stopping"] is False
    items = feed.build(record, "ja").items
    assert (items[101].stopping, items[101].stoppable) == (True, None), "Stopping…: no second Stop offered"
    assert (items[102].stopping, items[102].stoppable) == (None, True)
    # the runner stops it: Stopped, with Mine now — never *Stopping…* any more
    with Ledger(ledger_path) as led:
        led.mark_stopped(pressed_job, None)
        led.set_state(pressed_job, "waiting", reason=runner.STOPPED_BY_YOU)
    record, jobs = _ja(ledger_path)
    assert jobs[101]["stopping"] is False
    item = feed.build(record, "ja").items[101]
    assert (item.tip, item.stopping, item.stoppable) == (runner.STOPPED_BY_YOU, None, None)


def test_every_other_open_job_reads_waiting_its_turn_behind_the_one_in_flight(ledger_path, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    with Ledger(ledger_path) as led:
        working = led.queue("ja", 201, "test", "ev-1")
        queued = led.queue("ja", 202, "test", "ev-1")
        held = led.queue("ja", 203, "test", "ev-1")
        led.set_state(working, "mining")
        led.set_state(held, "waiting", reason=runner.ANKI_CLOSED)
    record, jobs = _ja(ledger_path)
    assert (jobs[202]["reason"], jobs[202]["behind"]) == (runner.TURN, 201)
    assert jobs[203]["reason"] == runner.ANKI_CLOSED and "behind" not in jobs[203], "a reason of its own stands"
    assert jobs[201]["reason"] is None and "behind" not in jobs[201]
    item = feed.build(record, "ja").items[202]
    assert (item.kind, item.tip) == (feed.WAITING, runner.TURN)
    with Ledger(ledger_path) as led:
        assert led.job_by_id(queued)["reason"] is None, "computed for the record, never written"
    # Connect not running: nothing is anyone's turn
    monkeypatch.setattr(status, "running", lambda: False)
    _record, jobs = _ja(ledger_path)
    assert jobs[202]["reason"] is None and "behind" not in jobs[202]
    # nothing in flight: unchanged
    monkeypatch.setattr(status, "running", lambda: True)
    with Ledger(ledger_path) as led:
        led.set_state(working, "done")
    _record, jobs = _ja(ledger_path)
    assert jobs[202]["reason"] is None and "behind" not in jobs[202]


# --- after review: every stop at mining keeps what the earlier batches made --------------------------------------- #
def _press_after_by_tag(steps, ledger, job_id):
    """A press as the first batch (in doubt: two words made, then a crash) is read back by the job's tag."""
    real = steps.by_tag

    def by_tag_then_press(*a):
        got = real(*a)
        ledger.ask_stop(job_id)
        return got
    steps.by_tag = by_tag_then_press


def _kept(steps, ledger, job_id):
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.STOPPED_BY_YOU, "mining")
    assert [(item, sorted(made), mined) for item, made, mined in steps.records] == [
        (1, ["一生懸命", "上層部"], False)], "the first batch's cards recorded (no receipt: not mined yet)"
    assert ("name_media", 1, 2) in steps.log, "and their clips named before Anki's next sync"


def test_a_press_between_two_batches_records_and_names_the_first_batchs_cards(tmp_path, ledger):
    # the review: a stop before the second batch left the first batch's cards unrecorded and unnamed until Mine now
    # (an Anki sync meanwhile syncs unnamed files)
    job_id = _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "crash_mid_batch": 2})
    _press_after_by_tag(steps, ledger, job_id)
    _run(steps, ledger)
    _kept(steps, ledger, job_id)
    assert [e[2] for e in steps.log if e[0] == "mine"] == [1], "no second batch"


def test_a_look_up_ended_in_the_second_batch_records_and_names_the_first_batchs_cards(tmp_path, ledger):
    stopping = _stopping()
    job_id = _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "crash_mid_batch": 2})
    real, calls = steps.mine, []

    def mine(lang, job, picked, todo, attempt):
        calls.append(attempt)
        if len(calls) == 1:
            return real(lang, job, picked, todo, attempt)
        ledger.ask_stop(job_id)                 # pressed while the second batch's look-ups run: ended there
        raise stopping.Stopped()
    steps.mine = mine
    _run(steps, ledger)
    _kept(steps, ledger, job_id)
    assert [b["state"] for b in ledger.batches(job_id)][-1] == "refused"


# --- after review: *Stopping…* from the press until the job has stopped, never past the stop point ---------------- #
def _entry(ledger_file, item):
    record = status.read(["ja"], path=ledger_file)
    entry = next(j for j in record["languages"]["ja"]["jobs"] if j["item"] == item)
    return entry, feed.build(record, "ja").items[item]


def test_the_tidy_up_after_a_stopped_batch_reads_stopping_with_no_second_stop(tmp_path, ledger, monkeypatch):
    # the batch Anki Miner ended at the press: its cards are read back, recorded and named — all of it *Stopping…*,
    # never *Mining* with Stop offered again
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _queue(ledger, 1)
    ledger_file = str(tmp_path / "ledger.sqlite")

    def press(n, job):
        if n == 1:
            ledger.ask_stop(job_id)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "on_word": press})
    seen = []
    for name in ("by_tag", "record", "name_media"):
        real = getattr(steps, name)

        def look(*a, _name=name, _real=real):
            entry, item = _entry(ledger_file, 1)
            seen.append((_name, entry["stopping"], item.stopping, item.stoppable))
            return _real(*a)
        setattr(steps, name, look)
    _run(steps, ledger)
    assert [s[0] for s in seen] == ["by_tag", "record", "name_media"]
    assert all(s[1:] == (True, True, None) for s in seen), seen
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
    entry, item = _entry(ledger_file, 1)
    assert (entry["stopping"], item.stopping, item.stoppable) == (False, None, None), "stopped: Mine now, no Stop"


def test_naming_the_clips_is_past_the_stop_point(tmp_path, ledger, monkeypatch):
    # the review: a press during naming (a third of an episode) was taken and never acted on — *Stopping…*
    # through naming, filling and ordering, then done. Naming is past the stop point: a pending press is forgotten as
    # it begins, a press then is refused, and no Stop is offered
    stopping = _stopping()
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _queue(ledger, 1)
    ledger_file = str(tmp_path / "ledger.sqlite")
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})
    real_after, real_name = steps.after_write, steps.name_media

    def after_write(lang):                      # pressed as Anki Miner's run ends, before naming
        real_after(lang)
        assert ledger.ask_stop(job_id)
    seen = []

    def name_media(lang, job, picked, lines):
        entry, item = _entry(ledger_file, 1)
        seen.append((ledger.stop_asked(job_id), entry["stopping"], item.stoppable, ledger.ask_stop(job_id),
                     stopping.pressed()))
        return real_name(lang, job, picked, lines)
    steps.after_write, steps.name_media = after_write, name_media
    _run(steps, ledger)
    assert seen == [(False, False, None, False, False)]
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1])
    from app.connect import actions
    assert actions.stoppable("mining", None, {"step": "naming"}) is False
    assert actions.stoppable("mining", None, json.dumps({"step": "naming"})) is False
    assert actions.stoppable("mining", None, json.dumps({"stage": 3, "stages": 5, "done": 2, "total": 6})) is True


def test_with_connect_not_running_a_pending_press_never_reads_stopping(ledger_path, monkeypatch):
    # the review: a job left in flight by a Connect that isn't running read *Stopping…* until it ran again
    monkeypatch.setattr(status, "running", lambda: False)
    with Ledger(ledger_path) as led:
        job_id = led.queue("ja", 301, "test", "ev-1")
        led.set_state(job_id, "fit-check")
        assert led.ask_stop(job_id)
    _record, jobs = _ja(ledger_path)
    assert jobs[301]["stopping"] is False
    monkeypatch.setattr(status, "running", lambda: True)
    _record, jobs = _ja(ledger_path)
    assert jobs[301]["stopping"] is True


# --- after review: the one program-ender and the one wait --------------------------------------------------------- #
def test_ending_a_program_whose_child_holds_its_pipe_returns_within_its_bound(monkeypatch):
    # the review: taskkill failed (or timed out) and a child the program started survives, holding its output pipe:
    # the final wait for its output had no limit, so the runner never reached its stop
    stopping = _stopping()
    monkeypatch.setattr(stopping, "END_WAIT_S", 1.0, raising=False)

    def taskkill_refused(*a, **k):
        raise OSError("taskkill refused")
    monkeypatch.setattr(subprocess, "run", taskkill_refused)
    code = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)']); "
            "time.sleep(30)")
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    time.sleep(1.0)                             # the program started its own child
    ended = threading.Event()

    def end():
        stopping.end(proc)
        ended.set()
    threading.Thread(target=end, daemon=True).start()
    assert ended.wait(5.0), "the end waited on a pipe a surviving child holds"
    assert proc.returncode is not None, "the program itself was ended"


def test_a_progress_read_that_keeps_failing_is_logged_once_a_wait(caplog):
    # a poll that always failed froze the bar unseen
    stopping = _stopping()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5); print('verdict')"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    calls = []

    def poll():
        calls.append(1)
        raise OSError("progress.json held open")
    with caplog.at_level(logging.WARNING, logger="surasura-cli"):
        out, _err = stopping.wait(proc, 30, on_poll=poll, every=0.05)
    assert out.strip() == b"verdict" and len(calls) >= 3
    logged = [r for r in caplog.records if r.exc_info and "progress.json held open" in str(r.exc_info[1])]
    assert len(logged) == 1, "once a wait: never every slice, never not at all"


def test_hatos_stop_is_connects_one_program_ender(monkeypatch):
    # a second copy of the ender (taskkill /T, kill, a bounded wait) lived in hato.py
    stopping = _stopping()
    from app.connect import hato
    seen = []
    monkeypatch.setattr(stopping, "end", lambda proc, **kw: seen.append((proc, kw)))
    proc = object()
    hato._stop(proc)
    assert seen == [(proc, {"collect": False})], "hato's own thread reads its output: never collected by the ender"


# --- after review: Anki Miner's look-ups -------------------------------------------------------------------------- #
def test_an_export_ended_mid_write_leaves_the_last_whole_export(fake_miner, tmp_path):
    # the review: a press ended `settings-export` while it wrote --out; the run folder's export (the mapping a run
    # after a kill reads) was left cut in half and read as {}
    stopping = _stopping()
    out = tmp_path / "run" / "settings-export.json"
    out.parent.mkdir()
    out.write_text(json.dumps({"anki_miner_settings": 1, "settings": {"anki_deck_name": "前の設定"}},
                              ensure_ascii=False), encoding="utf-8")
    before = out.read_bytes()
    fake_miner.plan(export_cut=True)
    with stopping.watching(_press_after(0.5)):
        with pytest.raises(stopping.Stopped):
            anki_miner.settings_export(fake_miner.path, "ja", str(out))
    assert out.read_bytes() == before, "the last whole export stands"
    assert sorted(p.name for p in out.parent.iterdir()) == ["settings-export.json"], "no part left behind"
    fake_miner.plan()
    assert anki_miner.settings_export(fake_miner.path, "ja", str(out))["settings"]["anki_deck_name"] == "DevTest"
    assert json.loads(out.read_text(encoding="utf-8"))["settings"]["anki_deck_name"] == "DevTest"
    assert sorted(p.name for p in out.parent.iterdir()) == ["settings-export.json"]


def test_a_call_with_no_verb_starts_nothing_it_cant_end(fake_miner, monkeypatch):
    # the verb was read after the program started: no verb raised IndexError and left the program running
    started = []
    real = subprocess.Popen

    def popen(*a, **k):
        started.append(a[0])
        return real(*a, **k)
    monkeypatch.setattr(subprocess, "Popen", popen)
    verdict = anki_miner.api(fake_miner.path, [])
    assert verdict["ok"] is False and len(started) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses a replace onto a file held open")
def test_the_fake_logs_each_progress_step_it_skips_as_anki_miner_warns(batch, fake_miner, tmp_path,  # noqa: F811
                                                                      monkeypatch):
    # Anki Miner's progress file write catches OSError, logs a warning and goes on: the fake does the same and says so
    # in its call log, so a test sees a collision rather than have it absorbed
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(progress=[[1, 5, 0, 0], [2, 5, 0, 0], [3, 5, 2, 6], [3, 5, 4, 6], [5, 5, 3, 6]],
                    progress_every=0.25)
    held = []

    def hold(progress):
        if held:
            return
        path = next((tmp_path / "runs").rglob("progress.json"))
        with open(path, "rb"):
            held.append(path)
            time.sleep(0.9)                     # Connect's read held open across the fake's next replaces
    done = batch(on_progress=hold)
    assert held and [o["outcome"] for o in done["outcomes"]] == ["made"] * len(done["outcomes"])
    assert any("progress_skipped" in c for c in fake_miner.calls()), "each skipped step in the call log"


def test_a_job_waiting_to_fill_or_order_is_never_offered_a_stop(ledger_path, monkeypatch):
    # the record carried no `resume`: a job waiting to fill its made cards (Anki closed) was offered a Stop that the
    # ledger refuses — a press that does nothing
    monkeypatch.setattr(status, "running", lambda: True)
    with Ledger(ledger_path) as led:
        filling = led.queue("ja", 401, "test", "ev-1")
        picking = led.queue("ja", 402, "test", "ev-1")
        led.set_state(filling, "waiting", reason=runner.ANKI_CLOSED, resume="filling")
        led.set_state(picking, "waiting", reason=runner.ANKI_CLOSED, resume=None)
        assert not led.ask_stop(filling)
    record, jobs = _ja(ledger_path)
    assert (jobs[401]["resume"], jobs[402]["resume"]) == ("filling", None)
    items = feed.build(record, "ja").items
    assert (items[401].stoppable, items[402].stoppable) == (None, True)


# --- after review round 2 ------------------------------------------------------------------------------------------ #
def test_a_job_whose_naming_waits_is_past_the_stop_point_too(tmp_path, ledger, monkeypatch):
    # round 2: the rename waited (Anki busy: you reviewing), the job went `waiting` at `mining` with its naming step
    # kept — Stop was offered, and a press held the job with its made cards unrecorded and its clips unnamed
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _queue(ledger, 1)
    ledger_file = str(tmp_path / "ledger.sqlite")
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})
    real_name = steps.name_media
    calls = []

    def name_media(lang, job, picked, lines):
        calls.append(job["id"])
        if len(calls) == 1:
            raise runner.Wait(runner.ANKI_CLOSED, True)
        return real_name(lang, job, picked, lines)
    steps.name_media = name_media
    _run(steps, ledger)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["resume"]) == ("waiting", "mining")
    entry, item = _entry(ledger_file, 1)
    assert entry["progress"] == {"step": "naming"} and item.stoppable is None, "no Stop offered at naming"
    assert not ledger.ask_stop(job_id) and not ledger.stop_asked(job_id), "a press is refused, nothing written"
    from app.connect import actions
    assert actions.stop("ja", job_id, path=ledger_file) is False
    _run(steps, ledger)                             # Anki free again: named, recorded, done
    assert ledger.job_by_id(job_id)["state"] == "done" and len(calls) == 2
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1])
    assert actions.stoppable("waiting", "mining", {"step": "naming"}) is False
    assert actions.stoppable("waiting", "mining", None) is True, "waiting to mine, not named yet: still stoppable"
