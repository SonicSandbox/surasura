"""The update waits for Connect (P3.1 row 3.1.8 (a), K99; 🧭 it waits, never kills): a running Connect stops at a
boundary of its own — between two Anki Miner batches of a job, and within UPDATE_LOOK_S of its 2-minute pause — with
every outcome saved, and the next run goes on from there.

What a wrong answer would cost:
  * a batch run after the update was staged: the update window waits another 18–24 s a batch, or (worse, before this
    row) the learner presses *Stop* and Anki Miner is orphaned mid-batch;
  * a resumed job that sends a word again: the same card made twice in the learner's Anki;
  * a Connect asleep in its pause for up to 2 minutes while the update waits for it.

Runs against `FakeSteps` (real Japanese words, synthetic titles) and a fake clock; never a live Anki.
"""
import types

import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _mines(steps):
    return [e for e in steps.log if e[0] == "mine"]


def test_an_update_staged_mid_job_stops_after_the_batch_and_the_next_run_makes_each_word_once(tmp_path, ledger):
    # Item 1's first batch makes 上層部, then Anki Miner stops (the rest in doubt): a second batch would follow. The
    # update is staged meanwhile, so the run stops before that second batch, with the first one's outcomes saved
    first = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "crash_mid_batch": 1, "staged_after_pick": True}
    steps = FakeSteps(str(tmp_path), first)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert summary["stopped"] == runner.STOPPED_FOR_UPDATE
    assert len(_mines(steps)) == 1, "no second batch once the update was staged"
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.STOPPED_FOR_UPDATE, "mining")
    assert steps.anki.words() == ["上層部"]

    # The next run (after the update): it resumes at mining and sends only the words still unsettled
    again = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})
    runner.run({}, ["ja"], steps=again, ledger=ledger, sleep=lambda s: None, looks=1)
    assert [m[3] for m in _mines(again)] == [["一生懸命", "走り出す"]], "only the words the first batch didn't make"
    assert sorted(again.anki.words()) == sorted(w for w, _r in WORDS[1]), "each word made once"
    assert ledger.jobs("ja")[0]["state"] == "done"


class Clock:
    """A fake clock for the pause: `sleep` moves it on; the update is staged once it passes `staged_at`."""

    def __init__(self, steps, staged_at):
        self.now, self.steps, self.staged_at, self.slept = 0.0, steps, staged_at, []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if self.now >= self.staged_at:
            self.steps.plan["staged"] = True
        return None

    def wait(self, seconds):                # a cancel Event's wait that is never set
        self.sleep(seconds)
        return False


def test_an_update_staged_during_the_pause_ends_it_within_five_seconds(tmp_path, ledger, monkeypatch):
    # Anki is closed: Connect pauses 2 minutes between looks. Staged 7 s in, it notices at the next 5-s look
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "blocked": runner.ANKI_CLOSED})
    clock = Clock(steps, staged_at=7)
    monkeypatch.setattr(runner, "time", types.SimpleNamespace(sleep=clock.sleep))
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger)
    assert summary["stopped"] == runner.STOPPED_FOR_UPDATE
    assert clock.now - clock.staged_at <= runner.UPDATE_LOOK_S, f"the pause went on {clock.now - 7} s after"
    assert set(clock.slept) == {runner.UPDATE_LOOK_S}, "the pause looks every 5 s"
    assert summary["looks"] == 2, "the next look named the update and stopped"


def test_the_pause_with_a_cancel_event_looks_for_the_update_too(tmp_path, ledger):
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "blocked": runner.ANKI_CLOSED})
    clock = Clock(steps, staged_at=12)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, cancel=types.SimpleNamespace(wait=clock.wait))
    assert summary["stopped"] == runner.STOPPED_FOR_UPDATE
    assert clock.now == 15, "three 5-s looks: staged at 12 s, seen at 15 s"


def test_with_nothing_staged_the_pause_is_the_whole_two_minutes(tmp_path, ledger, monkeypatch):
    # The 5-s looks change nothing else: unstaged, the pause lasts its 2 minutes, then Connect looks again
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "blocked": runner.ANKI_CLOSED})
    clock = Clock(steps, staged_at=10 ** 9)
    monkeypatch.setattr(runner, "time", types.SimpleNamespace(sleep=clock.sleep))
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, looks=2)
    assert clock.now == runner.LOOK_EVERY_S and summary["looks"] == 2 and "stopped" not in summary
