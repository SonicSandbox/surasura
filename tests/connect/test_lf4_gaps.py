"""LF-build4 mutant gaps (laptop round 8 #47 Stop, #49 level raise, #45 presses at once): the cases the change's own
tests left open, each named for what a wrong answer costs. Against `FakeSteps` (real Japanese words) and a real
ledger; never a live Anki.
"""
import sqlite3
import threading

import pytest

from types import SimpleNamespace

from app import anki_sync
from app.cli import verbs
from app.connect import anki_miner, feed, known_signal, runner
from tests import cli_helpers as h
from tests.connect.test_lf4_stop import _ask, _queue, _run, ledger  # noqa: F401  (fixture)
from tests.connect.fake_steps import FakeSteps, Killed
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)
from tests.connect.test_fix_b_offer_rechecked import SETTINGS, URL, anki, known_file  # noqa: F401  (fixtures)


def test_an_asked_episode_stopped_mid_batch_stays_stopped_at_the_next_start(tmp_path, ledger):  # noqa: F811
    # *Mine now*, then *Stop* while Anki Miner works: the ask the job carried is used up with the stop. Were it
    # forgotten, the next start would read that same ask as a new one and mine the episode again by itself.
    job_id = _queue(ledger, 1)
    _ask(ledger, 1, "2026-10-22T23:40:00.000000Z")

    def press(n, _job):
        if n == 1:
            ledger.ask_stop(job_id)
    plan = {"line": {"ja": [1]}, "on_word": press}
    _run(tmp_path, ledger, plan)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU
    plan.pop("on_word")
    steps, _summary = _run(tmp_path, ledger, plan)
    assert not any(e[0] in ("pick", "mine") for e in steps.log), "the stopped episode never starts again by itself"
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU


def test_an_asked_episode_stopped_at_its_pick_stays_stopped_at_the_next_start(tmp_path, ledger):  # noqa: F811
    # the same at a step's edge (`_stop_here`): the press lands while the job is picking
    job_id = _queue(ledger, 1)
    _ask(ledger, 1, "2026-10-22T23:40:00.000000Z")
    plan = {"line": {"ja": [1]}}
    steps = FakeSteps(str(tmp_path), plan)
    real_pick = steps.pick

    def pick_then_press(lang, job, video):
        got = real_pick(lang, job, video)
        ledger.ask_stop(job_id)
        return got
    steps.pick = pick_then_press
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU
    steps, _summary = _run(tmp_path, ledger, plan)
    assert not any(e[0] in ("pick", "fit", "mine") for e in steps.log), "the stopped episode never starts again"


def test_the_cards_a_stop_kept_are_recorded_under_the_jobs_tag(tmp_path, ledger):  # noqa: F811
    # the store's made-words row names the job that made the card (its `batch`). The resumed job re-records them all,
    # but a word whose note ids are recorded already is never written again: a stop that records them without the
    # tag leaves them nameless for good.
    job_id = _queue(ledger, 1)

    def press(n, _job):
        if n == 1:
            ledger.ask_stop(job_id)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "on_word": press})
    batches = []
    real_record = steps.record

    def record(lang, job, made, mined_at, batch):
        batches.append(batch)
        return real_record(lang, job, made, mined_at, batch)
    steps.record = record
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU
    assert batches == [runner._tag(ledger.job_by_id(job_id))]
    # and their media get the episode's names now: a stopped episode may never be asked for again
    assert [e for e in steps.log if e[0] == "name_media"] == [("name_media", 1, 1)]


def test_stop_wakes_a_running_connect(tmp_path, ledger, monkeypatch):  # noqa: F811
    # the press is acted on within a second or two, not at Connect's next look (minutes): the window wakes it
    from app.connect import actions, kick
    woken = []
    monkeypatch.setattr(kick, "wake", lambda *a, **k: woken.append(1))
    job_id = _queue(ledger, 1)
    ledger.set_state(job_id, "mining")
    assert actions.stop("ja", job_id, path=str(tmp_path / "ledger.sqlite")) is True
    assert woken == [1]
    assert actions.stop("zh", job_id, path=str(tmp_path / "ledger.sqlite")) is False
    assert woken == [1], "a press not recorded wakes nothing"


def test_a_no_definition_answer_counts_under_the_version_of_its_own_batch_only(tmp_path, ledger):  # noqa: F811
    # each episode's first batch by Anki Miner 3.7.0 found no definition; its second batch (other words) ran on
    # 3.11.0. The word is uncardable for 3.7.0 only: 3.11.0's dictionary was never asked about it.
    for item_id in (21, 22):
        job_id = _queue(ledger, item_id)
        ledger.start_batch(job_id, 1, str(tmp_path))
        ledger.end_batch(job_id, 1, "done", [{"word": "ルーデウス", "reading": "ルーデウス", "outcome": "no_definition"}],
                         anki_miner="3.7.0")
        ledger.start_batch(job_id, 2, str(tmp_path))
        ledger.end_batch(job_id, 2, "done", [{"word": "杖", "reading": "ツエ", "outcome": "made", "note_id": item_id}],
                         anki_miner="3.11.0")
    assert ledger.uncardable("ja", "3.7.0") == {("ルーデウス", "ルーデウス")}
    assert ledger.uncardable("ja", "3.11.0") == set()


def test_a_press_that_outlived_mining_never_stops_a_job_waiting_to_fill_its_cards(tmp_path, ledger):  # noqa: F811
    # *Stop* pressed during the last batch, which Anki Miner finished before it looked for the cancel file; then the
    # fill waited for Anki. Its cards are made: the job fills and orders them when it goes on, never held unfilled
    # until you press *Mine now*.
    job_id = _queue(ledger, 1)
    ledger.set_state(job_id, "mining")
    assert ledger.ask_stop(job_id)
    ledger.set_state(job_id, "waiting", reason=runner.ANKI_CLOSED, resume="filling")
    _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert not ledger.stop_asked(job_id) and not ledger.is_stopped(job_id)


class _Store:
    """The store's handle as `Steps.watched` reads it: a context manager with `item`."""

    def __init__(self, items):
        self.items = items

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def item(self, item_id):
        return self.items.get(item_id)


def test_the_runner_reads_watched_from_the_store_and_a_busy_store_is_not_watched(monkeypatch):
    # the real `Steps.watched` (the runner tests use FakeSteps' own): a watched episode's level job is dropped, so a
    # wrong answer either mines an episode you've seen or drops the new words of one you haven't
    store = _Store({5: {"watched": 1}, 6: {"watched": 0}})
    monkeypatch.setattr(runner.Steps, "_open", lambda self, lang: store)
    steps = runner.Steps({})
    assert steps.watched("ja", {"id": 1, "item_id": 5}) is True
    assert steps.watched("ja", {"id": 2, "item_id": 6}) is False
    assert steps.watched("ja", {"id": 3, "item_id": 7}) is False, "an item the store no longer holds"

    def busy(self, lang):
        raise runner.Wait(runner.LIBRARY_BUSY)
    monkeypatch.setattr(runner.Steps, "_open", busy)
    assert steps.watched("ja", {"id": 1, "item_id": 5}) is False, "a busy store: the job goes on as before"


def test_a_press_between_a_crashed_batch_and_its_retry_starts_no_second_batch(tmp_path, ledger):  # noqa: F811
    # Anki Miner crashed mid-batch; while Connect read back what reached Anki (by the job's tag) you pressed Stop.
    # The retry is never started (no Anki Miner launched only to be cancelled): the job waits at mining.
    job_id = _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "crash_mid_batch": 1})
    real_by_tag = steps.by_tag

    def by_tag_then_press(*a):
        got = real_by_tag(*a)
        ledger.ask_stop(job_id)
        return got
    steps.by_tag = by_tag_then_press
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.STOPPED_BY_YOU, "mining")
    assert len([e for e in steps.log if e[0] == "mine"]) == 1, "no second batch after the press"


def test_a_stopped_batch_whose_tag_check_waits_for_anki_is_no_failure(tmp_path, ledger):  # noqa: F811
    # you stopped Anki Miner before it wrote its result (so the batch is in doubt), then Anki closed before the tag
    # check: a wait, never a crash counted against Anki Miner (two of those would fail the episode)
    job_id = _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})

    def stopped_in_doubt(lang, job, picked, words, attempt):
        return {"outcomes": [{"word": w["word"], "reading": w["reading"], "outcome": "uncertain", "note_id": None}
                             for w in words], "app": None, "doubt": True, "stopped": True}

    def anki_closed(*a):
        raise runner.Wait(runner.ANKI_CLOSED)
    steps.mine, steps.by_tag = stopped_in_doubt, anki_closed
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "waiting"
    assert (ledger.job_by_id(job_id)["failures"] or 0) == 0, "your Stop is no failure of Anki Miner's"


def test_an_item_with_no_job_offers_no_stop():
    # a record entry Connect lists without its job id (nothing for *Stop* to name): no Stop button that does nothing
    got = feed.build({"running": True, "languages": {"ja": {"jobs": [{"item": 9, "state": "queued", "reason": None}],
                                                            "line": "Making cards", "state": "busy"}}}, "ja")
    assert got.items[9].stoppable is None


def test_a_wait_notice_that_fails_never_stops_mark_them_known(anki, known_file):  # noqa: F811
    # the window's notice is only a word on the screen: when it fails, the known words are still written
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    taken, release = threading.Event(), threading.Event()

    def sync():
        held, _refused = anki_sync.hold_known_words("ja", "Anki known-words sync")
        taken.set()
        release.wait(10)
        held.release()
    holder = threading.Thread(target=sync)
    holder.start()
    assert taken.wait(10)

    def on_wait(_who):
        release.set()
        raise RuntimeError("the window has closed")
    added = known_signal.accept_offer("ja", URL, on_wait=on_wait)
    holder.join(10)
    assert sorted(added) == ["一生懸命", "上層部"]


def test_a_stopped_batch_in_doubt_read_back_by_tag_is_no_failure(tmp_path, ledger):  # noqa: F811
    # stopped before Anki Miner wrote its result (in doubt), read back by the job's tag as it should be: no crash
    # counted (two would fail the episode)
    job_id = _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})

    def stopped_in_doubt(lang, job, picked, words, attempt):
        return {"outcomes": [{"word": w["word"], "reading": w["reading"], "outcome": "uncertain", "note_id": None}
                             for w in words], "app": None, "doubt": True, "stopped": True}
    steps.mine = stopped_in_doubt
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
    assert (job["failures"] or 0) == 0, "your Stop is no failure of Anki Miner's"


class _Unreadable:
    def stop_asked(self, job_id):
        raise sqlite3.OperationalError("database is locked")


def test_a_look_for_stop_that_fails_is_no_press():
    # Anki Miner's poll asks the ledger every 0.2 s: a read that fails must never cancel a batch you didn't stop
    assert runner._stop_pressed(_Unreadable(), 1) is False


def test_a_level_job_already_mining_goes_on_when_its_episode_is_watched_since(tmp_path, ledger):  # noqa: F811
    # the watched rule drops a level job only before its mining starts: one Connect was stopped in the middle of
    # (its first card made) finishes, so the card already in Anki is recorded and filled
    level = [("ja", 15, [("好く", "スク"), ("存在感", "ソンザイカン")])]
    plan = {"line": {"ja": [15]}, "level": level, "kill": "mid-batch:1"}
    with pytest.raises(Killed):
        _run(tmp_path, ledger, plan)
    _run(tmp_path, ledger, {"line": {"ja": [15]}, "watched": [15]})
    assert ledger.jobs("ja")[0]["state"] == "done", "never dropped once its cards are being made"


def test_a_store_that_cant_be_written_at_a_stop_is_no_needs_you(tmp_path, ledger):  # noqa: F811
    # review A7: the store refusing the stopped batch's cards now is no matter (the resumed job records them all):
    # the episode says Stopped, *Needs you* stays empty, and the media are still named
    job_id = _queue(ledger, 1)

    def press(n, _job):
        if n == 1:
            ledger.ask_stop(job_id)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "on_word": press})

    def read_only(*a):
        raise runner.Needs("no-store", "Surasura's library can't be written just now.")
    steps.record = read_only
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU
    assert summary["languages"]["ja"]["needs"] == []
    assert any(e[0] == "name_media" for e in steps.log)


# --- the real Steps.mine: the stop handed to Anki Miner and its answer handed back --------------------------------- #
MAPPING = SimpleNamespace(word="Word")
WORDS2 = [{"word": "気配", "reading": "ケハイ", "line_start": 3.0}, {"word": "見る", "reading": "ミル", "line_start": 7.5}]


def _real_steps(monkeypatch, mine_batch):
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir, held=None: ({}, "p1", MAPPING))
    monkeypatch.setattr(anki_miner, "mine_batch", mine_batch)
    return runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})


def _mine(steps):
    return steps.mine("ja", {"id": 3, "item_id": 1}, {"video": "v", "subtitle": "s", "profile": "p1"}, WORDS2, 1)


def test_steps_mine_hands_the_stop_to_anki_miner_and_its_stopped_answer_back(monkeypatch):
    # the runner's `should_stop` reaches mine_batch, and a run Anki Miner ended at the cancel comes back `stopped`
    # (else the runner reads it as whole: its cards never recorded at the stop, a later episode free to card them)
    seen = []

    def stopped_run(*a, should_stop=None, **k):
        seen.append(should_stop)
        return {"outcomes": [dict(w, outcome="made", note_id=1) for w in WORDS2[:1]], "app": "3.7.0",
                "error": None, "run": {"ok": False}, "stopped": True}
    steps = _real_steps(monkeypatch, stopped_run)
    steps.should_stop = press = (lambda: True)
    got = _mine(steps)
    assert seen == [press]
    assert got["stopped"] is True


def test_steps_mine_reads_a_cancel_before_any_result_as_a_stopped_batch_in_doubt(monkeypatch):
    # cancelled before Anki Miner wrote its result: what reached Anki is found by the job's tag (every word in
    # doubt), never Anki Miner refusing the episode
    def cancelled(*a, **k):
        e = anki_miner.AnkiMinerError("cancelled", "Cancelled.")
        e.stopped = True
        raise e
    got = _mine(_real_steps(monkeypatch, cancelled))
    assert got["stopped"] is True and got["doubt"] is True
    assert [o["outcome"] for o in got["outcomes"]] == ["uncertain", "uncertain"]


def test_a_stopped_run_that_crashed_after_writing_its_result_is_still_stopped(batch, fake_miner, monkeypatch):  # noqa: F811
    # the cancel took, then Anki Miner crashed at teardown after its result was written: the cards it made are read
    # from the result, and the answer still says you stopped it
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(cancel_at=2, mine="crash-after-result")
    done = batch(should_stop=lambda: True)
    assert done["stopped"] is True
    assert [o["outcome"] for o in done["outcomes"]][:2] == ["made", "made"]


def test_the_cancel_is_held_and_the_ledger_asked_no_more_after_it(batch, fake_miner, monkeypatch):  # noqa: F811
    # one press: after it the poll never asks the ledger again (a read every 0.2 s for nothing); the cancel file is
    # held at each poll (Anki Miner 3.10 clears an unconsumed one as a call starts) — a file touch, never a ledger read
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(cancel_at=2, progress=[[1, 5, 0, 0], [3, 5, 2, 6], [3, 5, 4, 6]], progress_every=0.2)
    real_cancel, cancels, asked = anki_miner.cancel, [], []
    monkeypatch.setattr(anki_miner, "cancel", lambda *a: cancels.append(1) or real_cancel(*a))

    def should_stop():
        asked.append(1)
        return True
    done = batch(should_stop=should_stop)
    assert done["stopped"] is True
    assert len(cancels) >= 1 and asked == [1]
