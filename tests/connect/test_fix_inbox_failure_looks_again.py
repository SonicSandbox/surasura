"""An inbox that can't be read is looked at again, never the end of the run (P2.4 Part A review fix; runner
`_consume`, its except branch returns True so `run` looks again).

What a wrong answer would cost: a read that fails once (a busy or read-only store, a ledger error) ends Connect's
run with a job still waiting, so the job waits for the next start instead of going on in this run; or the error
escapes `run` and Connect exits with a traceback over one unreadable inbox.

Against `FakeSteps` (real words); the injected `sleep` is a no-op. Never a live Anki.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


class InboxFailsOnce(FakeSteps):
    """The first read of the inbox raises; every later read works (and queues item 1, as the real inbox does)."""

    def __init__(self, folder, plan=None):
        super().__init__(folder, plan)
        self.reads = 0

    def consume(self, lang, ledger):
        self.reads += 1
        if self.reads == 1:
            raise RuntimeError("the inbox is locked by another writer")
        return super().consume(lang, ledger)


def test_an_unreadable_inbox_is_looked_at_again_and_the_run_goes_on(tmp_path):
    # Why the job is queued before the run: the runner only looks again while a job is open (`run` breaks when a look
    # has no work and no failed read), so a first read that fails with nothing queued would end the run at once.
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}}
    steps = InboxFailsOnce(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            ledger.queue("ja", 1, "user", None, store_id="store-1")
        # No exception may escape: the RuntimeError is caught inside the runner's inbox step.
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
        assert summary["looks"] >= 2, "the failed read is looked at again on a second look"
        assert steps.reads >= 2, "the inbox was read again after the failure"
        assert ledger.jobs("ja")[0]["state"] == "done", "the job still went on in this run"
