"""A Chinese job a 3.0.x Connect parked (P2.4 mutant D04; P1.5 06-edges E24) is mined at the next start (Zh-C).

Rule before Zh-C: while Anki Miner could not make Chinese cards, a Chinese job was parked in the ledger as waiting for
Chinese (`runner.CHINESE`). Since Zh-C (Anki Miner 3.12's Chinese) Connect makes Chinese cards
(`runner.CARD_LANGUAGES`): a job a 3.0.x ledger still holds with that reason is an open job like any waiting one.

What a wrong answer would cost: a Chinese learner who placed episodes under 3.0.x never gets their cards, the row
saying *Chinese cards come later* for ever.

Runs against `FakeSteps` with a real ledger; never a live Anki.
"""
from app.connect import runner
from tests.connect.test_runner import _run, ledger  # noqa: F401  (fixture)


def test_a_chinese_job_parked_by_3_0_x_is_mined_at_the_next_start(tmp_path, ledger):
    job = ledger.queue("zh", 1, "user", None, store_id="store-1")      # FakeSteps' store
    ledger.set_state(job, "waiting", reason=runner.CHINESE)          # as a 3.0.x Connect left it
    words = {"1": [("夜市", "")]}
    steps, summary = _run(tmp_path, ledger, {"line": {"zh": [1]}, "queue": {"zh": []}, "words": words},
                          languages=("zh",))
    job = ledger.jobs("zh")[0]
    assert job["state"] == "done" and job["reason"] != runner.CHINESE
    assert any(e[0] == "mine" for e in steps.log), "the parked job reaches Anki Miner"
    assert summary["languages"]["zh"]["done"] == [1]
