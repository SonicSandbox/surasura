"""Connect's runner opens no store span around a job's steps (L3.3 wiring; runner `_held()` is only for store reads back to
back). While one job runs end to end, `pick`, `mine`, `record`, `blocked`, `fill` and `order` must each see no span
open on this thread (`library_store._span() is None`): a span held across Anki, Anki Miner or a lock's wait would keep
one store handle open for minutes, so a store marked damaged meanwhile could not be set aside by Repair.

What a wrong answer would cost: Repair blocked for the length of a Mining batch, or a store handle kept open across
Anki Miner's minutes. The Steps methods are the real calls the runner makes; only the stand-ins for Anki are fakes.

Against `FakeSteps` with real words; never a live Anki, no sleeps.
"""
from app import library_store
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("眼鏡", "めがね")]


class SpanRecordingSteps(FakeSteps):
    """Each step records whether a store span was open when it was called, then answers as `FakeSteps` does."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_span = []   # (step name, True when a span was open)

    def _note(self, name):
        self.in_span.append((name, library_store._span() is not None))

    def pick(self, lang, job, video):
        self._note("pick")
        return super().pick(lang, job, video)

    def mine(self, lang, job, picked, words, attempt):
        self._note("mine")
        return super().mine(lang, job, picked, words, attempt)

    def record(self, lang, job, made, mined_at, batch):
        self._note("record")
        return super().record(lang, job, made, mined_at, batch)

    def blocked(self, lang):
        self._note("blocked")
        return super().blocked(lang)

    def fill(self, lang, job, note_ids):
        self._note("fill")
        return super().fill(lang, job, note_ids)

    def order(self, lang, job):
        self._note("order")
        return super().order(lang, job)


def test_a_job_runs_its_steps_with_no_store_span_open(tmp_path):
    # one episode, three real words: the job goes pick -> mine -> record -> fill -> order in one run
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}}
    steps = SpanRecordingSteps(str(tmp_path), plan)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        states = [j["state"] for j in ledger.jobs("ja")]

    assert states == ["done"], "the job runs to done, so every step is reached"
    seen = {name for name, _ in steps.in_span}
    # why: a step never reached would make the check below pass for no reason
    assert {"pick", "mine", "record"} <= seen, f"the steps reached: {sorted(seen)}"
    spanned = [name for name, open_ in steps.in_span if open_]
    assert spanned == [], "no step runs inside a store span: a span across Anki Miner would hold the store open"
