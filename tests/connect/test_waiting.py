"""Waiting and its reasons (P2.4 row 2.4.4; P1.5 02-data-model §2, §2a; 06-edges E1–E3, E8, E15, E16, E32): a job
waits with one reason at a time. A reason that can end while Connect runs (Anki closed, you reviewing, another
profile, on battery, Anki Miner open, the library busy) keeps it running, looking again every 2 minutes, and the job
goes on from the step it waited at once the reason clears; one that can't (no video, not timed) waits for the next
start, so Connect exits. With nothing to do it exits at once.

What a wrong answer would cost: Connect writing Anki while you review (K88) or into another profile (E3); a process
spinning on a laptop's battery; Connect alive all night for a video that isn't there; a not-timed episode named in
*Needs you* every time Connect starts; a job that waited at mining picking its words again (a second Generate's list).

Against `FakeSteps` (real words); the 2-minute look is the injected `sleep`. Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=5, clear=None):
    """Run with `plan`; each 2-minute look's sleep is recorded and, when `clear` names plan keys, clears them."""
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        for key in clear or ():
            steps.plan.pop(key, None)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep, looks=looks)
    return steps, summary, slept


@pytest.mark.parametrize("key, value, reason", [
    ("blocked", runner.ANKI_CLOSED, runner.ANKI_CLOSED),
    ("blocked", runner.REVIEWING, runner.REVIEWING),
    ("blocked", 'Waiting for Anki\'s profile "日本語": "DevTest" is open.',
     'Waiting for Anki\'s profile "日本語": "DevTest" is open.'),
    ("blocked", runner.ON_BATTERY, runner.ON_BATTERY),
    ("miner_busy", True, runner.ANKI_MINER_OPEN),
    ("library_busy", True, runner.LIBRARY_BUSY),
])
def test_a_reason_that_can_end_keeps_connect_looking_every_two_minutes(tmp_path, ledger, key, value, reason):
    # first look: it waits with that one reason
    steps, summary, slept = _run(tmp_path, ledger, {key: value}, looks=1)
    assert summary["languages"]["ja"]["waiting"] == {1: reason}
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("waiting", reason)
    # the reason clears while it sleeps: the next look (2 minutes on) finishes the job, then Connect exits
    steps, summary, slept = _run(tmp_path, ledger, {key: value}, looks=5, clear=[key])
    assert slept == [runner.LOOK_EVERY_S], "one 2-minute look, then done"
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert summary["looks"] == 2


def test_a_wait_before_any_batch_reached_anki_miner_picks_again(tmp_path, ledger):
    # Anki Miner refused the batch (its window open): nothing reached Anki, so the job keeps no step to resume at —
    # it picks again from the list as it is then, can still be dropped, and never holds the level raise
    # (adversary P2.4-A #1)
    steps, _summary, _slept = _run(tmp_path, ledger, {"miner_busy": True}, looks=1)
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["resume"]) == ("waiting", None)
    assert not ledger.in_flight("ja")
    steps, _summary, _slept = _run(tmp_path, ledger, {"miner_busy": True}, clear=["miner_busy"])
    assert [e[0] for e in steps.log if e[0] in ("pick", "mine")] == ["pick", "mine", "pick", "mine"]
    assert ledger.jobs("ja")[0]["state"] == "done"


def test_no_video_waits_for_the_next_start_and_connect_exits(tmp_path, ledger):
    steps, summary, slept = _run(tmp_path, ledger, {"videos": {"1": None}})
    assert summary["languages"]["ja"]["waiting"] == {1: runner.NO_VIDEO}
    assert slept == [] and summary["looks"] == 1, "nothing to look for every 2 minutes: it exits"
    assert not any(e[0] == "mine" for e in steps.log)


def test_tsubasa_with_no_answer_waits_and_is_asked_again_at_the_next_look(tmp_path, ledger):
    # why: a RETRY verdict is tsubasa not answering this time, not a video that is not timed; it must never become a
    # Needs you "not-timed" (the user would be told a fine episode is wrong) and Connect must keep looking
    steps, summary, slept = _run(tmp_path, ledger, {"verdict": "retry"}, looks=1)
    assert 1 in summary["languages"]["ja"]["waiting"], "the episode waits"
    assert ledger.jobs("ja")[0]["state"] == "waiting"
    assert ledger.needs("ja") == [], "no not-timed need is recorded"
    assert not any(e[0] == "mine" for e in steps.log)
    # the next look (2 minutes on) gets the answer: the job goes on and is done
    steps, summary, slept = _run(tmp_path, ledger, {"verdict": "retry"}, looks=5, clear=["verdict"])
    assert slept == [runner.LOOK_EVERY_S], "asked again after one 2-minute look"
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert ledger.needs("ja") == [], "still no need after the answer came"


def test_not_timed_is_named_once_in_needs_you_and_never_mined(tmp_path, ledger):
    for _start in range(2):
        steps, summary, slept = _run(tmp_path, ledger, {"verdict": "not timed"})
        assert slept == [] and not any(e[0] == "mine" for e in steps.log)
    job = ledger.jobs("ja")[0]
    assert job["state"] == "waiting" and "Not timed" in job["reason"]
    assert [n["kind"] for n in ledger.needs("ja")] == ["not-timed"], "named once, however many starts"


def test_a_not_timed_wait_before_mining_keeps_no_pick_so_it_holds_no_level_raise_look(tmp_path, ledger):
    # why: it waits at fit-check, before any mining, so it has no step to resume at; a stored resume would make
    # `in_flight` true and hold the level raise's look for a job that can't mine anyway
    steps, summary, slept = _run(tmp_path, ledger, {"verdict": "not timed"})
    assert ("fit", 1) in steps.log, "it reached the fit check (the wait is the fit's, not an earlier one)"
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["resume"]) == ("waiting", None)
    assert ledger.in_flight("ja") is False


def test_a_failed_known_sync_or_generate_is_needs_you_and_nothing_is_picked(tmp_path, ledger):
    steps, summary, slept = _run(tmp_path, ledger, {"prepare_error": "needs"})
    assert not any(e[0] == "pick" for e in steps.log)
    assert [n["kind"] for n in ledger.needs("ja")] == ["known-sync"]
    assert slept == [], "it waits for you, not for a look"


def test_anki_busy_at_the_runs_start_is_looked_at_again(tmp_path, ledger):
    steps, summary, slept = _run(tmp_path, ledger, {"prepare_error": "Another program is writing to Anki."},
                                 clear=["prepare_error"])
    assert slept == [runner.LOOK_EVERY_S]
    assert [e for e in steps.log if e[0] == "prepare"] == [("prepare", "ja")] * 2, "prepared again after the wait"
    assert ledger.jobs("ja")[0]["state"] == "done"


def test_nothing_to_do_exits_at_once(tmp_path, ledger):
    steps, summary, slept = _run(tmp_path, ledger, {"queue": {"ja": []}})
    assert (summary["looks"], slept) == (1, [])
    assert not any(e[0] in ("prepare", "blocked") for e in steps.log), "no job: Anki isn't even asked"
    assert ("settle",) in steps.log


def test_a_cancel_ends_the_wait_at_once(tmp_path, ledger):
    import threading
    cancel = threading.Event()
    cancel.set()
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "blocked": runner.ANKI_CLOSED})
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, cancel=cancel)
    assert summary["stopped"] == "cancelled" and summary["looks"] == 1


def test_a_busy_library_at_the_look_is_a_wait_never_an_empty_top_20(tmp_path, ledger):
    # the store can't be read: the job waits to look again, it is never mined against an empty top 20 and dropped
    steps, summary, slept = _run(tmp_path, ledger, {"store_busy": True}, looks=1)
    assert summary["languages"]["ja"]["waiting"] == {1: runner.LIBRARY_BUSY}
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("waiting", runner.LIBRARY_BUSY), "waits, not dropped"
    assert not any(e[0] == "mine" for e in steps.log), "no mining against an empty top 20"


def test_each_episodes_backfill_need_names_its_own_item(tmp_path, ledger):
    # Why: a need is named once per (kind, item); without the item id, the second episode's ask would be
    # swallowed as the first one's and you'd see one need for two episodes.
    steps, summary, slept = _run(tmp_path, ledger, {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]},
                                                    "fill_needs": True})
    assert {n["item_id"] for n in ledger.needs("ja")} == {1, 2}
    # a Backfill failure is tried again at the next start, once (adversary P2.4-A #13); then the job finishes
    assert [(j["state"], j["resume"]) for j in ledger.jobs("ja")] == [("waiting", "filling")] * 2
    steps, summary, slept = _run(tmp_path, ledger, {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]},
                                                    "fill_needs": True})
    assert [e[0] for e in steps.log].count("fill") == 2
    assert [j["state"] for j in ledger.jobs("ja")] == ["done", "done"]
