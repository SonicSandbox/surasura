"""Laptop round 8 #47 (LF4-5 ⭐ A, PROVISIONAL): *Stop* the episode Connect is making cards for.

Sonic: "WHILE MINING, might be a good thing to give the option to stop the current mining job." The press is recorded
at once (`actions.stop` → `Ledger.ask_stop`, Connect woken); Connect stops the job at its next safe point — before its
next step, or Anki Miner's batch cancelled through its cancel file (polled every 0.2 s) — every card it made kept,
whole and recorded, none made twice; the episode waits until a newer *Mine now*; Connect goes on with the next.

What a wrong answer costs: half-written cards, the same card made twice when the episode goes on, a stopped episode
that starts again by itself at the next look, or a Stop counted as Anki Miner failing (two of those fail the job).

Against `FakeSteps` (real Japanese words), the fake Anki Miner (`--api` as API.md documents it) and a real ledger.
Never a live Anki.
"""
import os

import pytest

from app.connect import actions, anki_miner, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    return steps, summary


def _queue(ledger, item_id):
    with ledger.transaction():
        return ledger.queue("ja", item_id, "user", None, store_id="store-1")


def _ask(ledger, item_id, at):
    with ledger.transaction():
        return ledger.ask("ja", item_id, at, store_id="store-1")


def test_a_stop_pressed_before_the_job_starts_holds_it_until_a_newer_ask(tmp_path, ledger):
    job_id = _queue(ledger, 1)
    assert ledger.ask_stop(job_id) is True
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU),         "a job not under way is stopped at the press, Connect running or not (its stone says so at once)"
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}})
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
    assert not any(e[0] in ("pick", "mine") for e in steps.log), "nothing of a stopped job runs"
    # the next start: still held — a stop never undoes itself
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert not any(e[0] == "pick" for e in steps.log)
    # *Mine now*: a newer ask lets it go on
    _ask(ledger, 1, "2026-10-22T23:50:00.000000Z")
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert ledger.job_by_id(job_id)["state"] == "done", "the old press never stops it again"
    assert summary["languages"]["ja"]["done"] == [1]
    assert not ledger.stop_asked(job_id) and not ledger.held_by_stop(ledger.job_by_id(job_id))


def test_a_press_while_the_runner_takes_the_job_up_stops_it_at_its_next_step(tmp_path, ledger):
    # the window's press lands just as the runner moved the job to picking: the job is stopped before its fit check
    job_id = _queue(ledger, 1)
    plan = {"line": {"ja": [1]}}
    steps = FakeSteps(str(tmp_path), plan)
    real_pick = steps.pick

    def pick_then_press(lang, job, video):
        got = real_pick(lang, job, video)
        ledger.ask_stop(job_id)                     # the job is `picking` now: the press alone is recorded
        return got
    steps.pick = pick_then_press
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
    assert not any(e[0] in ("fit", "mine") for e in steps.log)


def test_an_ask_older_than_the_stop_never_lets_it_go_on(tmp_path, ledger):
    # *Mine now*, then *Stop*: the ask it carried when it stopped is used up with it
    job_id = _queue(ledger, 1)
    _ask(ledger, 1, "2026-10-22T23:40:00.000000Z")
    ledger.ask_stop(job_id)
    _run(tmp_path, ledger, {"line": {"ja": [1]}})
    _ask(ledger, 1, "2026-10-22T23:40:00.000000Z")         # the same ask read again: no new press
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert not any(e[0] == "pick" for e in steps.log)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU


def test_a_stop_mid_batch_keeps_the_cards_made_and_the_rest_are_made_once_on_mine_now(tmp_path, ledger):
    job_id = _queue(ledger, 1)

    def press(n, _job):
        if n == 1:
            ledger.ask_stop(job_id)
    plan = {"line": {"ja": [1]}, "on_word": press}
    steps, summary = _run(tmp_path, ledger, plan)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.STOPPED_BY_YOU, "mining")
    first = WORDS[1][0][0]
    outcomes = {o["word"]: o["outcome"] for o in ledger.outcomes(job_id)}
    assert outcomes[first] == "made" and steps.anki.words() == [first]
    assert ("by_tag", 1) in steps.log, "a stopped batch is read back by the job's tag"
    assert (job["failures"] or 0) == 0, "your Stop is no failure of Anki Miner's"
    assert steps.records == [(1, {first: [o["note_id"] for o in ledger.outcomes(job_id) if o["word"] == first]},
                              False)], "its cards recorded, no receipt: the episode isn't mined yet"
    assert not any(e[0] in ("fill", "order") for e in steps.log)
    # *Mine now*: only the words still unmade are sent; every word has one card
    _ask(ledger, 1, "2026-10-22T23:55:00.000000Z")
    plan.pop("on_word")
    steps2 = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps2, ledger=ledger, sleep=lambda s: None, looks=1)
    assert [e[3] for e in steps2.log if e[0] == "mine"] == [[w for w, _r in WORDS[1][1:]]]
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert sorted(steps2.anki.words()) == sorted(w for w, _r in WORDS[1])


def test_a_stop_pressed_while_its_cards_are_filled_lets_the_job_finish(tmp_path, ledger):
    job_id = _queue(ledger, 1)
    ledger.set_state(job_id, "filling")
    ledger.ask_stop(job_id)                  # a press that slipped in (the window offers none past mining)
    _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert not ledger.stop_asked(job_id) and not ledger.held_by_stop(ledger.job_by_id(job_id))


def test_the_window_action_records_a_press_only_on_a_job_it_can_stop(tmp_path, ledger):
    path = str(tmp_path / "ledger.sqlite")
    job_id = _queue(ledger, 1)
    assert actions.stop("zh", job_id, path=path) is False, "another language's job"
    assert actions.stop("ja", 999, path=path) is False, "no such job"
    ledger.set_state(job_id, "filling")
    assert actions.stop("ja", job_id, path=path) is False, "its cards are made: it finishes"
    ledger.set_state(job_id, "mining")
    assert actions.stop("ja", job_id, path=path) is True
    assert ledger.stop_asked(job_id)
    ledger.set_state(job_id, "done")
    assert ledger.ask_stop(job_id) is False, "an ended job takes no press"
    assert actions.stop("ja", job_id, path=str(tmp_path / "none.sqlite")) is False, "no ledger: nothing written"
    assert not os.path.exists(str(tmp_path / "none.sqlite"))


# --- the Anki Miner call: the cancel file -------------------------------------------------------------------------- #
def test_a_stop_during_the_call_holds_the_cancel_file_and_keeps_what_was_made(batch, fake_miner, words,  # noqa: F811
                                                                                     monkeypatch):
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(cancel_at=2)
    asked = []

    def should_stop():
        asked.append(1)
        return True
    done = batch(should_stop=should_stop)
    assert done["stopped"] is True
    outcomes = [o["outcome"] for o in done["outcomes"]]
    assert outcomes[:2] == ["made", "made"]
    assert all(o in runner.UNSETTLED for o in outcomes[2:]), "the rest are never counted as turned down"
    run_dir = os.path.dirname(done["run_file"])
    assert not os.path.exists(os.path.join(run_dir, "job-1-1", "cancel")), "the call over: no cancel file left behind"


@pytest.mark.parametrize("cancel_at", [0, 2], ids=["before-anything-reached-anki", "mid-call"])
def test_a_stop_in_the_first_second_of_the_call_still_stops_it_when_anki_miner_clears_leftovers(
        batch, fake_miner, words, monkeypatch, cancel_at):  # noqa: F811
    # why (Anki Miner 3.10.1): a call clears an unconsumed cancel file once, before its setup, a
    # second or two after it starts — a Stop pressed just as the call began wrote its cancel file before that, and
    # Anki Miner deleted it as a leftover: the episode mined to its end. The file stands while the Stop does, and goes
    # once the call is over (no stray file for the next call)
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(cancel_at=cancel_at, clear_leftovers=0.3)
    if cancel_at == 0:
        with pytest.raises(anki_miner.AnkiMinerError) as raised:
            batch(should_stop=lambda: True)
        assert raised.value.kind == "cancelled" and raised.value.stopped is True
        run_dir = None
    else:
        done = batch(should_stop=lambda: True)
        assert done["stopped"] is True
        outcomes = [o["outcome"] for o in done["outcomes"]]
        assert outcomes[:2] == ["made", "made"] and all(o in runner.UNSETTLED for o in outcomes[2:])
        run_dir = os.path.dirname(done["run_file"])
    assert fake_miner.calls() and any("cleared" in c for c in fake_miner.calls()), "3.10's clearing ran"
    if run_dir:
        assert not os.path.exists(os.path.join(run_dir, "job-1-1", "cancel"))


def test_a_stop_before_anything_reached_anki_is_a_cancelled_refusal_marked_stopped(batch, fake_miner, monkeypatch):  # noqa: F811
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(cancel_at=0)
    with pytest.raises(anki_miner.AnkiMinerError) as raised:
        batch(should_stop=lambda: True)
    assert raised.value.kind == "cancelled" and raised.value.stopped is True


def test_no_stop_asked_is_the_call_as_before(batch, fake_miner, words):  # noqa: F811
    done = batch(should_stop=lambda: False)
    assert done["stopped"] is False
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)


# --- the review's walks (reviews/LF-build4-adversary.md) ----------------------------------------------------------- #
def test_a_job_waiting_to_fill_its_made_cards_is_never_stopped(tmp_path, ledger):
    # A3: its cards are made; it finishes once Anki answers (a stop would leave them unfilled, unordered)
    job_id = _queue(ledger, 1)
    ledger.set_state(job_id, "waiting", reason=runner.ANKI_CLOSED, resume="filling")
    assert not actions.stoppable("waiting", "filling") and actions.stoppable("waiting", None)
    assert ledger.ask_stop(job_id) is False
    assert actions.stop("ja", job_id, path=str(tmp_path / "ledger.sqlite")) is False


def test_a_stop_that_lands_after_every_word_was_made_lets_the_job_finish(tmp_path, ledger):
    # A3: the cancel came too late to stop anything: the episode is finished, never held at mining with nothing left
    job_id = _queue(ledger, 1)

    def press(n, _job):
        if n == len(WORDS[1]) - 1:
            ledger.ask_stop(job_id)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "on_word": press})
    real = steps.mine

    def mine_all_then_report_stopped(*a):
        got = real(*a)
        if got.get("stopped"):                      # Anki Miner had made every word before it read the cancel file
            return got
        return dict(got, stopped=True)
    steps.mine = mine_all_then_report_stopped
    steps.plan["on_word"] = None
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1])


def test_mine_now_pressed_after_stop_before_connect_reached_it_wins(tmp_path, ledger):
    # A4: Stop, then Mine now, both before the runner's next step: your later press decides — it goes on
    job_id = _queue(ledger, 1)
    ledger.set_state(job_id, "picking")
    ledger.ask_stop(job_id)
    _ask(ledger, 1, "2026-10-22T23:58:00.000000Z")
    assert not ledger.stop_asked(job_id)
    _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert ledger.job_by_id(job_id)["state"] == "done"


def test_an_ask_undone_never_lets_a_stopped_job_go_on(tmp_path, ledger):
    # A5: Mine now, Stop, then the ask undone (its asked_at cleared): still held — only a newer ask lets it go
    job_id = _queue(ledger, 1)
    _ask(ledger, 1, "2026-10-22T23:40:00.000000Z")
    ledger.ask_stop(job_id)
    with ledger.transaction():
        assert ledger.unask(job_id) == "cleared"
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1]}})
    assert not any(e[0] == "pick" for e in steps.log)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU


def test_an_ended_job_keeps_no_stop_record(tmp_path, ledger):
    # A9: skipped, dropped or failed — a job queued again later is never held by an old stop
    job_id = _queue(ledger, 1)
    ledger.ask_stop(job_id)
    ledger.set_state(job_id, "skipped", reason=runner.MINER_ABSENT)
    assert not ledger.stop_asked(job_id) and not ledger.is_stopped(job_id)


def test_a_stopped_jobs_own_wait_keeps_saying_stopped(tmp_path, ledger):
    # A10: the window stopped a waiting job the runner held; the runner's wait (Anki closed) never hides the stop
    job_id = _queue(ledger, 1)
    ledger.ask_stop(job_id)
    out = {"waiting": {}}
    runner._wait(ledger, ledger.job_by_id(job_id), runner.Wait(runner.ANKI_CLOSED), out)
    assert ledger.job_by_id(job_id)["reason"] == runner.STOPPED_BY_YOU


def test_a_cancel_file_left_by_a_stopped_call_never_cancels_the_next(batch, fake_miner, words, tmp_path):  # noqa: F811
    # A2: a refused attempt's number is reused; the stopped call's cancel file must not end the new one at once
    folder = tmp_path / "runs" / "job-1" / "job-1-1"
    folder.mkdir(parents=True)
    (folder / "cancel").write_text("")
    fake_miner.plan(cancel_at=0)                    # it would cancel at its first word if the file were there
    done = batch(should_stop=lambda: False)
    assert [o["outcome"] for o in done["outcomes"]] == ["made"] * len(words)
