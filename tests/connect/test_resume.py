"""Resume after a kill (P2.4 row 2.4.3; P1.5 06-edges E25, E11, E14; 02 §2: "mines nothing twice"): Connect killed at
any step boundary, or in the middle of an Anki Miner batch, picks up from its last saved step on the next start; a
batch left in doubt is checked by the job's tag before anything is tried again, so every word gets one card; a batch
that fails twice is *Needs you*, never a third try.

What a wrong answer would cost: the same word carded twice in the user's deck after a shutdown mid-batch (two cards
of one word, one of them never wanted); a job stuck half-way that never fills or orders its cards; Anki Miner tried
again and again on an episode that crashes it.

The loop runs as a child process (`python -m tests.connect.fake_steps PLAN`) that kills itself (`os._exit`) where the
plan says; Anki is `FakeAnki`'s JSON file, which outlives the child as a real Anki's notes would. Real words; never a
live Anki.
"""
import collections
import json
import os
import subprocess
import sys

import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.cli_helpers import PROJECT_ROOT
from tests.connect.fake_steps import WORDS, FakeAnki, FakeSteps

KILLS = ["pick", "fit", "mine", "mid-batch:1", "mid-batch:2", "after-mine", "fill", "order"]


def _child(folder, **plan):
    plan = dict({"folder": str(folder), "line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan)
    path = os.path.join(str(folder), "plan.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False)
    done = subprocess.run([sys.executable, "-m", "tests.connect.fake_steps", path], cwd=PROJECT_ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    return done.returncode, done.stderr.decode("utf-8", errors="replace")


def _clean_run(folder, **plan):
    plan = dict({"line": {"ja": [1]}, "queue": {"ja": [1]}}, **plan)
    steps = FakeSteps(str(folder), plan)
    with Ledger(os.path.join(str(folder), "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        jobs = ledger.jobs("ja")
        needs = ledger.needs("ja")
    return steps, summary, jobs, needs


@pytest.mark.parametrize("kill", KILLS)
def test_a_kill_at_any_step_resumes_and_every_word_is_made_once(tmp_path, kill):
    code, err = _child(tmp_path, kill=kill)
    assert code == 9, f"the child should have been killed at {kill}: {err[-2000:]}"
    steps, _summary, jobs, _needs = _clean_run(tmp_path)
    assert [(j["item_id"], j["state"]) for j in jobs] == [(1, "done")], jobs
    counts = collections.Counter(FakeAnki(str(tmp_path / "anki.json")).words())
    assert counts == collections.Counter(w for w, _r in WORDS[1]), f"one card a word after a kill at {kill}"
    if kill in ("mid-batch:1", "mid-batch:2", "after-mine"):
        assert any(e[0] == "by_tag" for e in steps.log), "a batch in doubt is checked by its tag first"
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        outcomes = ledger.outcomes(jobs[0]["id"])
    assert sorted(o["word"] for o in outcomes if o["outcome"] == "made") == sorted(w for w, _r in WORDS[1])


def test_a_kill_after_filling_fills_again_but_never_mines_again(tmp_path):
    code, _err = _child(tmp_path, kill="order")
    assert code == 9
    steps, _summary, _jobs, _needs = _clean_run(tmp_path)
    assert not any(e[0] in ("pick", "mine") for e in steps.log), "resumed at ordering: nothing picked or mined"
    assert [e[0] for e in steps.log if e[0] in ("fill", "order")] == ["order"]


def test_a_batch_that_fails_twice_is_needs_you_and_never_tried_a_third_time(tmp_path):
    steps, summary, jobs, needs = _clean_run(tmp_path, crash_mid_batch=1, crash_always=True)
    assert [j["state"] for j in jobs] == ["failed"]
    assert [e[2] for e in steps.log if e[0] == "mine"] == [1, 2], "one try, one retry"
    assert [n["kind"] for n in needs] == ["mine-failed"]
    assert summary["languages"]["ja"]["failed"] == [1]
    assert collections.Counter(steps.anki.words()) == collections.Counter([WORDS[1][0][0], WORDS[1][1][0]]), \
        "the words made before each crash are kept, once each"


def test_one_crash_is_tried_again_once_and_only_the_words_in_doubt_are_sent(tmp_path):
    steps, _summary, jobs, _needs = _clean_run(tmp_path, crash_mid_batch=1)
    assert [j["state"] for j in jobs] == ["done"]
    mines = [e for e in steps.log if e[0] == "mine"]
    assert len(mines) == 2 and mines[1][3] == [w for w, _r in WORDS[1][1:]], "the made one is found by tag, not resent"
    assert collections.Counter(steps.anki.words()) == collections.Counter(w for w, _r in WORDS[1])


def test_a_lost_ledger_mines_nothing_twice(tmp_path):
    _clean_run(tmp_path)
    os.remove(str(tmp_path / "ledger.sqlite"))
    for side in ("-wal", "-shm"):
        if os.path.exists(str(tmp_path / "ledger.sqlite") + side):
            os.remove(str(tmp_path / "ledger.sqlite") + side)
    steps, _summary, jobs, _needs = _clean_run(tmp_path)
    # the job comes again (a fresh ledger), but every word has its card in Anki: nothing is sent
    assert not any(e[0] == "mine" for e in steps.log)
    assert [j["reason"] for j in jobs] == [runner.NO_WORDS]
    assert collections.Counter(steps.anki.words()) == collections.Counter(w for w, _r in WORDS[1])
