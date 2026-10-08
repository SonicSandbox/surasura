"""Fix review R15 (P2.4-A #19): a word Anki Miner turned down for an item is never sent to mine again for that item.
The ledger's `declined` set (outcomes not_found, no_definition, ... of any job of the item) is filtered out of the
pick, so a later level job naming it sends only its other words.

What a wrong answer would cost: Anki Miner asked again for a word it already said it can't find, every later level
job for the episode (a slower batch, a second turn-down recorded as a new outcome).

Against `FakeSteps` (real Japanese words); never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_a_word_anki_miner_turned_down_is_not_sent_again_by_a_later_level_job(tmp_path, ledger):
    # Item 1 was mined once already: Anki Miner said 気配 is not found there (a done job, its outcome in the ledger).
    first = ledger.queue("ja", 1, "user", None, store_id="store-1")
    ledger.set_state(first, "done", reason=None)
    ledger.end_batch(first, 1, "done", [{"word": "気配", "reading": "ケハイ", "outcome": "not_found"}])

    # A level job for item 1 names 気配 again and 上層部: only 上層部 may reach mine.
    plan = {"line": {"ja": [1]}, "level": [("ja", 1, [("気配", "ケハイ"), ("上層部", "ジョウソウブ")])]}
    steps = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)

    sent = [e[3] for e in steps.log if e[0] == "mine"]
    assert sent == [["上層部"]], "the declined 気配 is left out of the level job's batch"
    level = [j for j in ledger.jobs("ja") if j["kind"] == "level"]
    assert len(level) == 1, "the level job ran (so the filter, not a missing job, kept 気配 out)"
