"""A job's store reads run inside one open store span, and Anki Miner's call never does (P2.4 L3.3 wiring; runner
`_held` around the pick's reads, the batch's reads before Anki Miner's call, and the names' reads with the record).

The span keeps one store handle open for the reads and the write of a job, so a job touches the store through one
handle. Anki Miner's call takes minutes; if a span were open across it, a store marked damaged meanwhile could not be
set aside by Repair while the handle stays open. What a wrong answer would cost: a job that holds the store open for
minutes (Repair blocked, the library frozen), or a pick or record that runs without the one handle and opens the
store again per read.

Against `FakeSteps` with real words, one job run to the end; no sleeps, no live Anki.
"""
from app import library_store
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("眼鏡", "めがね")]


class _SpanRecordingSteps(FakeSteps):
    """FakeSteps that notes, at each of the three calls, whether a store span is open on this thread."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spans = []  # (step name, True if a span was open when the step ran)

    def pick(self, *args, **kwargs):
        self.spans.append(("pick", library_store._span() is not None))
        return super().pick(*args, **kwargs)

    def mine(self, *args, **kwargs):
        self.spans.append(("mine", library_store._span() is not None))
        return super().mine(*args, **kwargs)

    def record(self, *args, **kwargs):
        self.spans.append(("record", library_store._span() is not None))
        return super().record(*args, **kwargs)


def test_a_jobs_store_reads_and_record_share_one_span_and_mining_never_holds_one(tmp_path):
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}}
    steps = _SpanRecordingSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        jobs = ledger.jobs("ja")

    # why: the job must reach its end, or the span checks prove nothing about the pick, the mine and the record
    assert [j["state"] for j in jobs] == ["done"], "the job runs to done, so every step below is reached"

    names = {name for name, _ in steps.spans}
    assert names == {"pick", "mine", "record"}, f"each step ran at least once: {steps.spans}"

    for name, span_open in steps.spans:
        if name == "mine":
            assert span_open is False, "Anki Miner's call (minutes) never runs inside a store span"
        else:
            assert span_open is True, f"{name}'s store reads and write run inside the job's one span"
    # the span is closed again once the job is over: nothing holds the store after the run
    assert library_store._span() is None
