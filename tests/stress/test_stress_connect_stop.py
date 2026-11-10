"""Stress (opt-in: `python run_tests.py --stress`): Connect's *Stop* pressed from another thread — the window's own
connection to the ledger — at a random moment while a mining job runs (each step a little slow, as programs are), then
*Mine now* until the job is done. What must hold wherever the press lands — before the pick, inside a step, between a
batch and its record, after the job ended: every word of the item is made in Anki exactly once (nothing lost, nothing
twice), the job ends done, and a Stop never counts as Anki Miner failing. No timing is asserted.

`FakeSteps` with real Japanese words and a real ledger (tests/connect/fake_steps.py); never a live Anki."""
import random
import threading
import time

import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps

ROUNDS = 25


def _slowed(steps, rnd):
    """Each step of `steps` a few milliseconds slow, at random (a program's start and its work)."""
    for name in ("pick", "fit", "mine", "by_tag"):
        real = getattr(steps, name)

        def slow(*a, _real=real, **k):
            time.sleep(rnd.uniform(0, 0.004))           # (a stand-in's pace, not a wait: nothing is waited for here)
            return _real(*a, **k)
        setattr(steps, name, slow)
    return steps


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_a_stop_pressed_anywhere_then_mine_now_makes_every_word_exactly_once(tmp_path, round_):
    seed = random.randrange(1 << 30)
    rnd, pace = random.Random(seed), random.Random(seed + 1)    # one per thread: the seed replays the same draws
    path = str(tmp_path / "ledger.sqlite")
    plan = {"line": {"ja": [1]}}
    with Ledger(path) as ledger:
        with ledger.transaction():
            job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
        pressed = threading.Event()

        def press():
            time.sleep(pace.uniform(0, 0.03))           # (when it lands is the point: anywhere in the run)
            with Ledger(path) as window:
                window.ask_stop(job_id)
            pressed.set()
        presser = threading.Thread(target=press, name="stop-press")
        presser.start()
        runner.run({}, ["ja"], steps=_slowed(FakeSteps(str(tmp_path), plan), rnd), ledger=ledger,
                   sleep=lambda s: None, looks=1)
        presser.join()
        assert pressed.is_set()
        for n in range(5):                              # *Mine now* until it's done (a press used up each time)
            job = ledger.job_by_id(job_id)
            if job["state"] == "done":
                break
            with ledger.transaction():
                ledger.ask("ja", 1, f"2026-10-23T09:00:0{n}.000000Z", store_id="store-1")
            runner.run({}, ["ja"], steps=_slowed(FakeSteps(str(tmp_path), plan), rnd), ledger=ledger,
                       sleep=lambda s: None, looks=1)
        job = ledger.job_by_id(job_id)
        assert job["state"] == "done", f"seed {seed}: {job['state']} {job['reason']}"
        made = FakeSteps(str(tmp_path), plan).anki.words()
        assert sorted(made) == sorted(w for w, _r in WORDS[1]), f"seed {seed}: a word lost or made twice: {made}"
        assert (job["failures"] or 0) == 0, f"seed {seed}: a Stop counted as Anki Miner failing"
