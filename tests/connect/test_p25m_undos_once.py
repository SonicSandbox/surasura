"""P2.5's planted-bug pass: a half-done undo is looked at once a run, however many looks the run takes.

The rule: in one `runner.run`, `steps.finish_undos` is called once per language, not once per look. A job that
waits for Anki makes the run look again; each look that re-finished an undo would re-run Anki's deletes and
re-write the undo's record. A wrong answer would cost a second pass over Anki's notes for every look, and
a run that waits on Anki for an hour would spend that hour re-reading the same half-done undo.

Real Japanese words, a real SQLite ledger in a temp folder, a fake Anki; no network, no sleeps.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_undo import _batch


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield led
    finally:
        led.close()


def test_a_half_done_undo_is_finished_once_however_many_looks_the_run_takes(ledger, tmp_path):
    # The job waits for Anki ("blocked"), so the run looks again; the undo stays pending because the spy does
    # not finish it. Before this rule, every look called finish_undos again for the same language.
    job_id, _tag = _batch(ledger)
    ledger.start_undo(job_id, "ja", [101], [])
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]},
                                      "words": {"1": [["上層部", "じょうそうぶ"]]},
                                      "blocked": "Waiting for Anki: it isn't open."})
    calls = []

    def finish(lang, led):
        calls.append(lang)
    steps.finish_undos = finish

    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)

    assert summary["looks"] >= 2, "the run looked again while the job waited, so the once-only rule is what's tested"
    assert calls == ["ja"], "the half-done undo is finished once per run, not once per look"


def test_each_language_with_a_half_done_undo_is_finished_once_not_one_flag_for_the_run(ledger, tmp_path):
    # The rule is per language: a single run-wide flag would finish ja's undo and then skip zh's, so zh's
    # half-done undo would never be finished. Two languages, one pending undo each, the job waits on ja.
    job_id, _tag = _batch(ledger)
    ledger.start_undo(job_id, "ja", [101], [])
    ledger.start_undo(job_id, "zh", [202], [])
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]},
                                      "words": {"1": [["上層部", "じょうそうぶ"]]},
                                      "blocked": "Waiting for Anki: it isn't open."})
    calls = []

    def finish(lang, led):
        calls.append(lang)
    steps.finish_undos = finish

    summary = runner.run({}, ["ja", "zh"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)

    assert summary["looks"] >= 2, "the run looked again while the job waited, so the once-per-language rule is tested"
    assert sorted(calls) == ["ja", "zh"], "each language's half-done undo is finished exactly once, never dropped"
