"""Laptop round 5 #23: the row moves while an episode mines. Anki Miner writes its run's `progress.json` as it goes
(stage / stages, done / total); Connect reads it while the mine call runs, saves it in the job only when it moves
(S19), and the status record, the feed and the row carry it (*Mining · 40%*, the step on hover).

What a wrong answer would cost: *Mining · 0/57* for the whole episode (Sonic: "it should at least show some
interaction about the progress"), a ledger written four times a second, or a mine call that dies with its progress.
Against the fake Anki Miner and `FakeSteps`; never a live Anki.
"""
import json
import subprocess
import sys

import pytest

from app.connect import anki_miner, feed, runner, status
from app.connect.ledger import Ledger
from app.services import view_rows
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


# --- the mine call reads its progress --------------------------------------------------------------------------- #
def test_a_mine_call_hands_over_its_progress_as_it_goes(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # why: before, the call waited on Anki Miner's verdict alone; now each progress.json it writes is handed on
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(progress=[[1, 5, 0, 0], [3, 5, 2, 6], [3, 5, 6, 6], [5, 5, 3, 6]], progress_every=0.3)
    seen = []
    done = batch(on_progress=seen.append)
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)
    stages = [p["stage"] for p in seen]
    assert stages == sorted(stages) and {1, 3, 5} <= set(stages)
    assert {"stage": 3, "stages": 5, "done": 2, "total": 6} in seen


def test_a_poll_that_fails_never_stops_the_call(monkeypatch):
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.4); print('verdict')"],
                            stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    calls = []

    def poll():
        calls.append(1)
        raise OSError("progress.json held open")
    assert anki_miner._communicate(proc, 30, poll).strip() == b"verdict"
    assert len(calls) >= 2


def test_the_calls_timeout_still_holds_while_it_polls(monkeypatch):
    # why: a hung Anki Miner is still stopped at its timeout (the caller kills it), polls or not
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            anki_miner._communicate(proc, 0.5, lambda: None)
    finally:
        proc.kill()
        proc.communicate()


@pytest.mark.parametrize("text, expected", [
    (None, None), ("not json", None), ('{"stage": 3, "stages": 5, "done": 2}', None),
    ('{"stage": 3, "stages": 5, "done": -1, "total": 6}', None), ('{"stage": true, "stages": 5, "done": 2, "total": 6}',
                                                                  None),
    ('{"schema": 1, "run_id": "j-1", "stage": 3, "stages": 5, "done": 2, "total": 6}',
     {"stage": 3, "stages": 5, "done": 2, "total": 6}),
])
def test_read_progress_takes_only_a_whole_answer(tmp_path, text, expected):
    if text is not None:
        (tmp_path / "j-1").mkdir()
        (tmp_path / "j-1" / "progress.json").write_text(text, encoding="utf-8")
    assert anki_miner.read_progress(str(tmp_path), "j-1") == expected


def test_percent_adds_the_finished_stages_and_the_part_done(monkeypatch):
    monkeypatch.setattr(anki_miner, "STAGE_SHARES", (0.1, 0.1, 0.5, 0.1, 0.2))
    p = lambda stage, done=0, total=0, stages=5: anki_miner.percent(  # noqa: E731
        {"stage": stage, "stages": stages, "done": done, "total": total})
    assert p(0) == 0 and p(1) == 0
    assert p(3, 0, 10) == 20 and p(3, 5, 10) == 45 and p(4) == 70
    assert p(5, 6, 6) == 99, "100 is the run's end, never its progress"
    assert p(3, 12, 10) == 70, "done past total counts as the stage done"
    assert p(2, stages=4) == 25, "another number of stages: equal shares"


# --- saved only when it moves ------------------------------------------------------------------------------------ #
def test_progress_is_saved_only_when_its_stage_or_its_percent_step_moves(ledger, monkeypatch):
    monkeypatch.setattr(anki_miner, "STAGE_SHARES", (0.2, 0.2, 0.2, 0.2, 0.2))
    with ledger.transaction():
        ledger.queue("ja", 7, "user", None, store_id="s")
    jid = ledger.jobs("ja")[0]["id"]
    ledger.set_state(jid, "mining")
    writes = []
    real = ledger.set_state
    monkeypatch.setattr(ledger, "set_state", lambda *a, **k: (writes.append(k.get("progress")), real(*a, **k)))
    save = runner._Progress(ledger, jid)
    for done in (0, 1, 1, 2, 3, 4, 5, 6):            # stage 3 of 5, 6 clips: 40 43 43 46 50 53 56 60 %
        save({"stage": 3, "stages": 5, "done": done, "total": 6})
    assert [w["done"] for w in writes] == [0, 2, 3, 5, 6], "one write per 5 % step entered, never per poll"
    save({"stage": 4, "stages": 5, "done": 0, "total": 0})
    assert writes[-1]["stage"] == 4
    assert json.loads(ledger.job_by_id(jid)["progress"])["stage"] == 4


class _Reports(FakeSteps):
    """Anki Miner's run reports a stage while it mines; the job's saved progress is read back mid-call."""

    def mine(self, lang, job, picked, words, attempt):
        self.on_progress({"stage": 3, "stages": 5, "done": 2, "total": 6})
        self.mid = json.loads(self.ledger.job_by_id(job["id"])["progress"])
        return super().mine(lang, job, picked, words, attempt)


def test_the_runner_saves_the_batchs_progress_in_its_job_while_it_mines(tmp_path, ledger):
    steps = _Reports(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    steps.ledger = ledger
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=2)
    assert steps.mid == {"stage": 3, "stages": 5, "done": 2, "total": 6}
    assert steps.on_progress is None, "the callback lives only as long as its call (no reference kept)"
    assert ledger.jobs("ja")[0]["state"] == "done"


def test_a_new_batch_starts_with_no_progress(tmp_path, ledger):
    # why: a retried batch never shows the last one's 90 % before its own first word
    steps = _Reports(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "crash_mid_batch": 0})
    steps.ledger = ledger
    starts = []
    real = ledger.start_batch
    ledger.start_batch = lambda jid, *a: (starts.append(ledger.job_by_id(jid)["progress"]), real(jid, *a))
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=2)
    assert len(starts) >= 2 and all(s is None for s in starts)


# --- status, feed, row ------------------------------------------------------------------------------------------- #
def test_one_percent_runs_through_the_whole_episode(monkeypatch):
    # why (Sonic 2026-10-22, M-2 A): one number from choosing words to ordering, the step on hover — never stuck
    # at a count while words are chosen, the clips named or the fields filled
    monkeypatch.setattr(anki_miner, "STAGE_SHARES", (0.2, 0.2, 0.2, 0.2, 0.2))
    seq = [status._progress({"state": "picking"}), status._progress({"state": "fit-check"}),
           status._progress({"state": "mining", "progress": None}),
           status._progress({"state": "mining", "progress": json.dumps({"stage": 3, "stages": 5, "done": 3,
                                                                        "total": 6})}),
           status._progress({"state": "mining", "progress": json.dumps({"step": "naming"})}),
           status._progress({"state": "filling"}), status._progress({"state": "ordering"})]
    percents = [p["percent"] for p in seq]
    assert percents == sorted(percents) and len(set(percents)) == len(percents), percents
    assert [p["doing"] for p in seq] == ["Choosing words", "Checking the timing", "Starting Anki Miner",
                                         "Cutting clips (3 of 6)", "Naming the clips", "Filling fields",
                                         "Ordering your cards"]
    assert seq[3]["percent"] == status.MINE_FROM + (status.MINE_TO - status.MINE_FROM) // 2
    assert status._progress({"state": "mining", "progress": "{broken"})["doing"] == "Starting Anki Miner"


def test_the_row_shows_the_percent_and_the_step_on_hover():
    rec = {"running": True, "languages": {"ja": {"jobs": [
        {"item": 4, "job": 9, "state": "mining", "words": 57, "made": 0,
         "progress": {"stage": 3, "stages": 5, "done": 12, "total": 57, "percent": 41,
                      "doing": "Cutting clips (12 of 57)"}}]}}}
    item = feed.build(rec, "ja").items[4]
    assert (item.kind, item.progress, item.doing) == (feed.MINING, 41, "Cutting clips (12 of 57)")
    plain = view_rows.Status("waiting", "Waiting", "In your top 20", "dim")
    st = view_rows._connected(plain, item, "video")
    assert (st.kind, st.label) == ("mining", "Mining · 41%")
    assert "Cutting clips (12 of 57)" in st.tip


def test_the_runner_marks_the_clips_naming_before_it(tmp_path, ledger):
    # why: the rename after Anki Miner's run is a third of an episode's time: the row says so
    steps = _Reports(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    steps.ledger = ledger
    seen = []
    real = steps.name_media
    steps.name_media = lambda lang, job, picked, lines: (seen.append(json.loads(
        ledger.job_by_id(job["id"])["progress"])), real(lang, job, picked, lines))
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=2)
    assert seen and seen[0] == {"step": "naming"}


def test_a_job_waiting_carries_no_progress():
    rec = {"running": True, "languages": {"ja": {"jobs": [
        {"item": 4, "job": 9, "state": "waiting", "reason": runner.ON_BATTERY, "progress": None}]}}}
    item = feed.build(rec, "ja").items[4]
    assert item.kind == feed.BATTERY and item.progress is None and item.doing is None
