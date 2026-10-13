"""Connect parks a Chinese job until the next start (P2.4 mutant D04; P1.5 06-edges E24).

Rule: while Anki Miner cannot make Chinese cards yet, a Chinese job is parked in the ledger as waiting for Chinese
(`runner.CHINESE`) and the run does not look again every 2 minutes for it: `run` looks once and returns.

Mutant P2.4-D04 flips the `False` passed to `_waiting_all` for Chinese into `True`, so the run reports "outside
Connect, look again" and loops until its look budget runs out.

What a wrong answer would cost: the loop wakes every 2 minutes all night, reads Anki and the library for a language
that cannot mine yet, and burns the laptop's battery and the Anki session for nothing.

Runs against `FakeSteps` with a real ledger; never a live Anki.
"""
from app.connect import runner
from tests.connect.test_runner import _run, ledger  # noqa: F401  (fixture)


def test_chinese_job_is_parked_and_run_looks_only_once_even_with_looks_budget(tmp_path, ledger):
    # Why looks=3: the budget allows three looks; a parked Chinese job must not spend more than the first one.
    steps, summary = _run(tmp_path, ledger, {"line": {"zh": [1]}, "queue": {"zh": [1]}}, looks=3, languages=("zh",))
    job = ledger.jobs("zh")[0]
    assert (job["state"], job["reason"]) == ("waiting", runner.CHINESE), "parked until the next start"
    assert not any(e[0] in ("prepare", "pick", "mine") for e in steps.log), "nothing of Chinese is mined"
    assert summary["looks"] == 1, "Chinese is parked: the run does not look again every 2 minutes for it"
