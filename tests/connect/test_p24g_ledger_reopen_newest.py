"""Connect ledger: `reopen_skipped` requeues only the newest skipped job of an item (P2.4-B23).

The rule: an item can carry two skipped jobs for the same reason (say, Anki Miner wasn't installed on two runs).
When Anki Miner is installed later, `reopen_skipped` queues again the newest of them only, so the item is mined once
and the older skip stays on record as history. The mutant (P2.4-B23) takes the oldest job instead, so the newest
skip stays skipped and the history is rewritten.

What a wrong answer would cost: the wrong job is requeued, the one the user last saw skipped stays skipped, and the
queue shows a job the user already dealt with while the current one is never mined.
"""
import pytest

from app.connect.ledger import Ledger

# The reason Connect writes when Anki Miner isn't installed (the one `reopen_skipped` looks for).
REASON = "Anki Miner isn't installed"


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def test_reopen_skipped_requeues_only_the_newest_skipped_job_of_an_item(ledger):
    """Two skipped jobs for one item: only the newer one is queued again; the older one stays skipped."""
    older = ledger.queue("ja", 4, "user", None)
    ledger.set_state(older, "skipped", reason=REASON)
    # The first job is skipped, so the item has no open work and a second job can be queued for it.
    newer = ledger.queue("ja", 4, "user", None)
    ledger.set_state(newer, "skipped", reason=REASON)
    assert older != newer
    assert newer is not None

    with ledger.transaction():
        requeued = ledger.reopen_skipped("ja", [4], REASON)

    assert requeued == 1
    assert ledger.job_by_id(newer)["state"] == "queued"
    assert ledger.job_by_id(older)["state"] == "skipped"
