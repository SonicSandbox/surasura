"""The cap (P2.4 Part B): before a job's first batch, Connect's own waiting cards are counted against the learner's cap.
Under the cap a job mines; at or over it the job waits with a reason that names the count ("Your 300 cards are
waiting ...") and Connect keeps looking every 2 minutes. Since Kyou-SH (Sonic 2026-11-20: Connect never suspends by
itself) the shelf is never asked at the cap: the job waits until you study. No cap (None or 0) always mines. The waiting count only counts Connect's own new, unsuspended cards.

What a wrong answer would cost: Connect piling cards past the learner's cap (a backlog nobody asked for), a job that
waits forever at 299 cards, a job that mines at exactly 300 and grows the pile, or cards suspended at the cap by
Connect (a tester's 236).

Against `FakeSteps` (real words, item 1 = 3 words); the 2-minute look is the injected `sleep`. Never a live Anki.
"""
import pytest

from app.connect import runner, shelf
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=5, clear=None):
    """Run with `plan`; each look's sleep is recorded and, when `clear` names plan keys, clears them (Anki freed up)."""
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan))
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        for key in clear or ():
            steps.plan.pop(key, None)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep, looks=looks)
    return steps, summary, slept


def test_the_waiting_query_counts_only_connects_own_new_unsuspended_cards():
    # why: a suspended card or the learner's own note must never count against the cap, or the cap fills with cards
    # Connect didn't make and the job waits for nothing
    assert shelf.WAITING_QUERY == '"tag:surasura::connect::*" is:new -is:suspended'


@pytest.mark.parametrize("waiting", [0, 299])
def test_under_the_cap_the_job_mines_and_an_episode_that_crosses_it_finishes(tmp_path, ledger, waiting):
    # why: the cap is checked before the first batch only, so an episode of 3 words taking 299 to 302 is not cut short
    steps, summary, slept = _run(tmp_path, ledger, {"cap": 300, "waiting": waiting}, looks=1)
    assert not any(e[0] == "shelve" for e in steps.log), "under the cap the shelf isn't asked"
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert slept == [], "it mined; no look was needed"


@pytest.mark.parametrize("waiting", [300, 450])
def test_at_or_over_the_cap_the_job_waits_with_its_count_and_keeps_looking(tmp_path, ledger, waiting):
    # why: exactly at the cap is a full pile; a wait that didn't name the count would hide why nothing is mined
    steps, summary, slept = _run(tmp_path, ledger, {"cap": 300, "waiting": waiting}, looks=3)
    reason = summary["languages"]["ja"]["waiting"][1]
    assert reason.startswith(f"Your {waiting} cards are waiting"), reason
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("waiting", reason)
    assert not any(e[0] == "mine" for e in steps.log), "nothing is mined over the cap"
    assert slept and set(slept) == {runner.LOOK_EVERY_S}, "Connect looks again every 2 minutes"


@pytest.mark.parametrize("frees", [0, 1, 40])
def test_at_the_cap_the_shelf_is_never_asked_and_the_job_waits(tmp_path, ledger, frees):
    # why (Kyou-SH): Connect suspended a tester's 236 cards at the cap; now nothing is shelved, however much the shelf
    # could free, and nothing is mined past the cap
    steps, summary, slept = _run(tmp_path, ledger, {"cap": 300, "waiting": 300, "shelf_frees": frees}, looks=1)
    assert not any(e[0] == "shelve" for e in steps.log), "the shelf never asked"
    assert not any(e[0] == "mine" for e in steps.log)
    assert ledger.jobs("ja")[0]["state"] == "waiting"


@pytest.mark.parametrize("cap", [None, 0])
def test_no_cap_always_mines_however_many_cards_wait(tmp_path, ledger, cap):
    # why: a learner with no cap set (or 0) has no limit; 450 waiting must not stop the job
    steps, summary, slept = _run(tmp_path, ledger, {"cap": cap, "waiting": 450}, looks=1)
    assert not any(e[0] == "shelve" for e in steps.log), "no cap, no shelf"
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert slept == []


def test_a_wait_at_the_cap_goes_on_once_anki_frees_room(tmp_path, ledger):
    # why: the look after the pile drops under the cap is the one that mines; the job is not dropped
    steps, summary, slept = _run(tmp_path, ledger, {"cap": 300, "waiting": 300}, looks=5, clear=["waiting"])
    assert slept == [runner.LOOK_EVERY_S], "one 2-minute look, then the job mines"
    assert ledger.jobs("ja")[0]["state"] == "done"
