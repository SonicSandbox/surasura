"""P4.1 row 4.1.9 (G1.3-6, 06-edges E16): *Mine anyway* on an episode Connect found not timed to its video —
`actions.mine_anyway(language, need_id)`, the window's third short ledger write: the *Needs you* entry fixed, the job
queued again with `picked.forced`, and `runner._fit` passing it untimed (no shift, tsubasa not asked, logged). The
choice holds for the pairing it was made on: one re-timed meanwhile is picked and checked again.

What a wrong answer would cost: *Mine anyway* pressed and nothing happening (the user's only way to cards for an
untimed episode); or the opposite — an episode hato re-timed (or paired with another subtitle) since the click mined
untimed on the strength of an old answer, its cards cut at the wrong moments; a stale entry the window still shows
making some other job mine untimed.

Connect's loop against `FakeSteps` (real Japanese words; synthetic titles); a real ledger in the test's folder.
"""
import logging

import pytest

from app.connect import actions, feed, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps

PAIRING = {"verdict": "untimed", "untimed_tier": "same", "content_key": "4f1c", "n": 1}


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "ledger.sqlite")


def _plan(**more):
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1]}, "pairings": {"1": dict(PAIRING)},
            "verdict": "not timed", "offset": 2.75}
    plan.update(more)
    return plan


def _run(tmp_path, path, plan):
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(path) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    return steps, summary


def _open_need(path, kind="not-timed"):
    with Ledger(path) as ledger:
        return [n for n in ledger.needs("ja") if n["kind"] == kind]


def test_not_timed_is_a_need_and_no_cards_then_mine_anyway_mines_it_untimed(tmp_path, path, caplog):
    plan = _plan()
    steps, _summary = _run(tmp_path, path, plan)
    needs = _open_need(path)
    assert len(needs) == 1 and needs[0]["item_id"] == 1 and steps.anki.words() == [], "no cards: *Needs you*"
    assert actions.mine_anyway("ja", needs[0]["id"], path=path) is True
    assert _open_need(path) == [], "the entry off the list"
    caplog.set_level(logging.INFO, logger="surasura-cli")
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.job("ja", 1)
        picked = ledger.picked(job["id"])
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1]), "its words made"
    assert job["state"] == "done" and picked["forced"] is True and picked["offset"] == 0.0, \
        "untimed: no shift (never the plan's 2.75 s a fit check would answer)"
    assert not any(e[0] == "fit" for e in steps.log), "tsubasa isn't asked again: you chose"
    assert "mined anyway: not timed" in caplog.text
    assert _open_need(path) == []


def test_a_pairing_retimed_meanwhile_is_picked_again_and_gated_again(tmp_path, path):
    plan = _plan()
    _run(tmp_path, path, plan)
    assert actions.mine_anyway("ja", _open_need(path)[0]["id"], path=path) is True
    plan["pairings"]["1"] = dict(PAIRING, n=2)          # hato re-timed it (or paired another subtitle) since the click
    steps, _summary = _run(tmp_path, path, plan)
    with Ledger(path) as ledger:
        job = ledger.job("ja", 1)
        picked = ledger.picked(job["id"])
    assert steps.anki.words() == [] and any(e[0] == "fit" for e in steps.log), "checked again: still not timed"
    assert not picked.get("forced"), "the re-pick cleared it"
    assert len(_open_need(path)) == 1, "a new entry: *Mine anyway* asked again for the new pairing"


def test_the_new_pairing_timed_mines_with_its_offset(tmp_path, path):
    plan = _plan()
    _run(tmp_path, path, plan)
    actions.mine_anyway("ja", _open_need(path)[0]["id"], path=path)
    plan["pairings"]["1"] = dict(PAIRING, verdict="timed", n=2)
    plan["verdict"] = "timed"
    steps, _summary = _run(tmp_path, path, plan)
    with Ledger(path) as ledger:
        picked = ledger.picked(ledger.job("ja", 1)["id"])
    assert picked["offset"] == 2.75 and not picked.get("forced") and len(steps.anki.words()) == 3


def test_no_ledger_is_false_and_nothing_is_made(path):
    import os
    assert actions.mine_anyway("ja", 1, path=path) is False
    assert not os.path.exists(path), "the window never makes a ledger"


def test_only_an_open_not_timed_entry_of_its_language_forces_anything(tmp_path, path):
    _run(tmp_path, path, _plan())
    need = _open_need(path)[0]
    with Ledger(path) as ledger:
        job_id = ledger.job("ja", 1)["id"]
        # another kind of entry on the same item and job (Connect stopped on an error there)
        assert ledger.need("ja", "error", "Connect stopped on an error (OSError).", item_id=1, job_id=job_id)
        other_id = [n for n in ledger.needs("ja") if n["kind"] == "error"][0]["id"]
        before = ledger.picked(job_id)
    assert actions.mine_anyway("zh", need["id"], path=path) is False, "another language's"
    assert actions.mine_anyway("ja", other_id, path=path) is False, "another kind of entry"
    assert actions.mine_anyway("ja", 9999, path=path) is False, "no such entry"
    with Ledger(path) as ledger:
        assert ledger.picked(ledger.job("ja", 1)["id"]) == before and "forced" not in before
    assert len(_open_need(path)) == 1 and len(_open_need(path, "error")) == 1, "nothing written"
    assert actions.mine_anyway("ja", need["id"], path=path) is True
    assert actions.mine_anyway("ja", need["id"], path=path) is False, "fixed already: a second click does nothing"


def test_an_entry_whose_job_ended_meanwhile_forces_nothing(tmp_path, path):
    _run(tmp_path, path, _plan())
    need = _open_need(path)[0]
    with Ledger(path) as ledger:
        ledger.set_state(ledger.job("ja", 1)["id"], "dropped", reason="left the top 20")
    assert actions.mine_anyway("ja", need["id"], path=path) is False
    assert len(_open_need(path)) == 1, "left for its own fix (a dropped job's entry is the runner's to close)"


def test_hatos_name_only_pairing_carries_its_warning():
    # 09-hato-layer v2 §1.2: *Mine anyway* on `untimed` carries a warning (hato's wrong-episode finding)
    assert feed.WORDS["untimed"] == feed.UNTIMED_WARNING and "episode" in feed.UNTIMED_WARNING
