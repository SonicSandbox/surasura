"""The Connect ledger's state columns (mutants P2.4-B16, B17; app/connect/ledger.py `set_state`).

What this holds still: a job's `resume` step belongs to its `waiting` state. Entering `waiting` keeps the resume
step it is given (the runner needs it to pick the job up again), and leaving `waiting` for any other state clears
it unless the caller gives a new one, so a job that is mining never says it will resume a fit check that is done.
A wrong answer would either lose the resume step a waiting job needs, or leave a stale one on a running job that
the runner later reads as a reason to stop. Likewise a job's `reason` belongs to a finished state: moving back to an
open state clears it (a queued job never shows the old reason), and finishing keeps the reason it had (a failed job
still says why).

The ledger is a real SQLite file in `tmp_path`; no network, no sleeps.
"""
from app.connect.ledger import Ledger


def test_leaving_waiting_clears_the_resume_step_and_entering_waiting_keeps_it(tmp_path):
    """The resume step is kept while a job waits and cleared the moment it leaves `waiting` for mining.

    Why both halves: the first assertion pins that `waiting` keeps the step it is given; the second pins that
    leaving `waiting` for another state clears it when no new step is given, and the last pair pins that a new
    step given on the way out is kept. A mutant that inverts the test on `waiting` keeps the stale step on the
    mining job and fails the second assertion; one that ignores the given step fails the last.
    """
    with Ledger(str(tmp_path / "ledger.sqlite")) as L:
        j = L.queue("ja", 4, "user", None)

        L.set_state(j, "waiting", resume="fit-check")
        assert L.job_by_id(j)["resume"] == "fit-check"

        L.set_state(j, "mining")
        assert L.job_by_id(j)["resume"] is None

        L.set_state(j, "waiting", resume="fit-check")
        L.set_state(j, "mining", resume="filling")
        assert L.job_by_id(j)["resume"] == "filling"


def test_an_open_state_clears_the_reason_and_a_finished_state_keeps_it(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as L:
        j = L.queue("ja", 4, "user", None)
        L.set_state(j, "skipped", reason="Anki Miner isn't installed")
        L.set_state(j, "queued")
        assert L.job_by_id(j)["reason"] is None, "a job queued again shows no old reason"
        k = L.queue("ja", 5, "user", None)
        L.set_state(k, "waiting", reason="On battery")
        L.set_state(k, "failed")
        assert L.job_by_id(k)["reason"] == "On battery", "a failed job keeps the reason it had"
