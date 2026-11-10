"""Connect switched off mid-run (runner `_stop` at each job boundary; P2.4 Part A review, Connect's loop): a switch
read as off after one job's mine step ends the run before the next job is picked. The job left behind stays open
(queued, neither done nor dropped), so the next run that Connect is on picks it up.

What a wrong answer would cost: Connect keeps making cards after you switched it off (it writes Anki while you have
turned it off), and an item the switch stopped is lost instead of waiting for the next run.

Against `FakeSteps` (real words); never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_switch_off_after_a_mine_step_stops_the_run_before_the_next_job(tmp_path, ledger):
    # why: the switch is read again after each job, so the second job is never picked once it's off
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "switch_off_after": "mine"})
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=5)

    assert summary["stopped"] == runner.SWITCHED_OFF
    assert [e[1] for e in steps.log if e[0] == "pick"] == [1], "only item 1 was picked"
    by_item = {j["item_id"]: j for j in ledger.jobs("ja")}
    assert by_item[1]["state"] == "done"
    assert by_item[2]["state"] not in ("done", "dropped"), "item 2 stays open for the next run"
