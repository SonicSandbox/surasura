"""Connect starts the session's sync clock after a batch that makes cards, whether or not Junban is installed
(P2.4 review fix R10; runner `_mine`, the `after_write` call after the batch's outcomes are recorded).

What a wrong answer would cost: with Junban absent, the new cards of a Connect run never start the sync clock, so
Anki's next sync is late or never happens (S3); and a batch that made no card starting the clock would sync an
Anki nobody wrote to.

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


def test_new_cards_start_the_sync_clock_even_when_junban_is_not_installed(tmp_path, ledger):
    # Junban absent: the mine still makes cards, and the clock starts after that batch is recorded, before any order step
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "absent": ["junban"]})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    names = [e[0] for e in steps.log]
    assert ("after_write", "ja") in steps.log
    assert names.index("after_write") > names.index("mine")


def test_a_batch_that_makes_no_card_does_not_start_the_sync_clock(tmp_path, ledger):
    # every word of episode 1 is already in Anki before the run, so the pick has nothing to make: no card, no clock
    seed = FakeSteps(str(tmp_path))
    for word in ("上層部", "一生懸命", "走り出す"):
        seed.anki.add(word, "other")
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "absent": ["junban"]})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert not any(e[0] == "after_write" for e in steps.log)
