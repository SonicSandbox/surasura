"""The job registry (`app/services/jobs.py`) — W1.3, the window's spec 04 §4.2.

What a wrong answer would cost:
  * two writers at once — Generate and the indexer both writing the token store, or two programs writing Anki;
  * an automatic job taking the turn of one the user asked for (the user waits on something they didn't ask for);
  * a stuck bar — a job whose start failed left "running" forever, or a listener's fault stopping every update;
  * a bar that changes under the window's hands — a snapshot that moves after it was taken;
  * closing that hangs or leaves work half-done — quitting must cancel, wait for or leave each job as it says.
"""
import threading

import pytest

from app.services import jobs as J
from app.services.jobs import JobRegistry


def _starter(started):
    def start(job):
        started.append(job.label)
    return start


@pytest.mark.parametrize("a,b,together", [
    ("generate", "indexer", False),        # both write the token store
    ("indexer", "generate", False),
    ("junban", "backfill", False),         # one Anki writer at a time (E1.4's anki-writer)
    ("mine", "replan", False),
    ("generate", "generate", False),       # never two of a kind
    ("child", "child", False),
    ("generate", "junban", True),
    ("anki-sync", "indexer", True),
    ("generate", "child", True),
])
def test_the_exclusion_table_row_by_row(a, b, together):
    registry, started = JobRegistry(), []
    first = registry.submit(a, "first", _starter(started))
    second = registry.submit(b, "second", _starter(started))
    assert first.state == J.RUNNING
    if together:
        assert second.state == J.RUNNING and started == ["first", "second"]
    else:
        assert second.state == J.WAITING and second.reason == "waits for first" and started == ["first"]
        first.finish()
        assert second.state == J.RUNNING and started == ["first", "second"]


def test_an_automatic_job_yields_to_a_users_job_queued_before_it_could_start():
    """An automatic Generate asked for while the user's waits behind the indexer never takes the user's turn."""
    registry, started = JobRegistry(), []
    indexer = registry.submit("indexer", "Indexing", _starter(started))
    users = registry.submit("generate", "Generating", _starter(started))
    sync = registry.submit("anki-sync", "Updating known words from Anki", _starter(started), automatic=True)
    auto_index = registry.submit("sentence-corpus", "Sentence dictionary", _starter(started), automatic=True)
    assert users.state == J.WAITING and sync.state == J.RUNNING      # no conflict: runs
    assert auto_index.state == J.WAITING
    indexer.finish()
    assert users.state == J.RUNNING and auto_index.state == J.WAITING
    assert auto_index.reason == "waits for Generating"
    users.finish()
    assert auto_index.state == J.RUNNING


def test_an_automatic_job_never_starts_while_a_users_conflicting_job_waits():
    registry, started = JobRegistry(), []
    first = registry.submit("junban", "Re-ordering Anki", _starter(started))
    users = registry.submit("backfill", "Filling cards", _starter(started))
    auto = registry.submit("mine", "Mining 12 words", _starter(started), automatic=True)
    first.finish()
    assert users.state == J.RUNNING and auto.state == J.WAITING and auto.reason == "waits for Filling cards"


def test_an_automatic_job_asked_for_first_still_yields_and_neither_waits_on_the_other():
    """Connect's automatic mining waits behind 順; then the user asks for Backfill (another Anki writer). When 順 ends,
    the user's Backfill runs first and the mining after it — never both waiting on each other."""
    registry, started = JobRegistry(), []
    junban = registry.submit("junban", "Re-ordering Anki", _starter(started))
    auto = registry.submit("mine", "Mining 12 words", _starter(started), automatic=True)
    users = registry.submit("backfill", "Filling cards", _starter(started))
    junban.finish()
    assert users.state == J.RUNNING and auto.state == J.WAITING and auto.reason == "waits for Filling cards"
    users.finish()
    assert auto.state == J.RUNNING and started == ["Re-ordering Anki", "Filling cards", "Mining 12 words"]


def test_a_users_request_absorbs_a_queued_automatic_one_of_its_kind():
    """The automatic Generate after a sync was waiting; the user presses Generate: one run, the user's."""
    registry, started = JobRegistry(), []
    running = registry.submit("indexer", "Indexing", _starter(started))
    auto = registry.submit("generate", "Generating (automatic)", _starter(started), automatic=True)
    users = registry.submit("generate", "Generating", _starter(started))
    assert auto.state == J.DONE and auto.cancelled and auto.reason == "joined your request"
    running.finish()
    assert started == ["Indexing", "Generating"] and users.state == J.RUNNING


def test_snapshots_never_change_after_they_are_taken():
    registry = JobRegistry()
    job = registry.submit("generate", "Generating", lambda j: None)
    snap = registry.snapshot()
    job.progress("Reading your files", 3, 12)
    job.finish()
    assert snap[0].state == J.RUNNING and snap[0].progress is None
    assert registry.snapshot()[0].state == J.DONE
    with pytest.raises(AttributeError):
        snap[0].state = "x"


def test_progress_and_failure_reach_the_record():
    registry = JobRegistry()
    job = registry.submit("generate", "Generating", lambda j: None)
    job.progress("Counting words", None, None)
    assert registry.snapshot()[0].progress == J.Progress("Counting words", None, None)
    job.finish(ok=False, message="The analyzer stopped: see generate.log")
    view = registry.snapshot()[0]
    assert view.state == J.FAILED and view.message == "The analyzer stopped: see generate.log"


def test_a_start_that_raises_is_a_failed_job_and_the_next_one_runs():
    registry, started = JobRegistry(), []

    def broken(_job):
        raise OSError("no such program")
    bad = registry.submit("generate", "Generating", broken)
    nxt = registry.submit("generate", "Generating again", _starter(started))
    assert bad.state == J.FAILED and "no such program" in bad.message
    assert nxt.state == J.RUNNING


def test_a_listener_that_raises_never_stops_the_registry():
    registry, heard = JobRegistry(), []

    def broken(_snap):
        raise RuntimeError("a listener's own fault")
    registry.subscribe(broken)
    registry.subscribe(heard.append)
    job = registry.submit("generate", "Generating", lambda j: None)
    job.finish()
    assert heard and heard[-1][0].state == J.DONE


def test_cancel_before_start_ends_it_and_while_running_asks_its_owner():
    registry, asked = JobRegistry(), []
    first = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: asked.append(j.id))
    second = registry.submit("generate", "Generating again", lambda j: None)
    assert second.cancel() and second.state == J.DONE and second.cancelled
    assert first.cancel() and first.state == J.CANCELLING and asked == [first.id]
    first.finish()
    assert first.state == J.DONE and first.cancelled
    assert not first.cancel(), "nothing left to cancel"


def test_recorded_jobs_are_listed_but_never_hold_a_gated_job_back():
    """The Tk dashboard's children: recorded for the bar, started by their owner; they hold nothing back (today's
    behaviour: a pressed Generate starts while the indexer child runs)."""
    registry, started = JobRegistry(), []
    child = registry.record("indexer", "Indexer")
    gen = registry.submit("generate", "Generating", _starter(started))
    assert child.state == J.RUNNING and gen.state == J.RUNNING and not child.gated
    child.finish()
    assert [v.state for v in registry.snapshot()] == [J.DONE, J.RUNNING]


def test_quit_cancels_waits_for_and_leaves_each_job_as_it_says():
    registry = JobRegistry()
    stop = threading.Event()
    cancelled = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: j.finish(),
                                on_quit="cancel")
    waited = registry.submit("junban", "Re-ordering Anki", lambda j: threading.Timer(0.2, j.finish).start(),
                             on_quit="wait")
    left = registry.submit("mine", "Mining", lambda j: None, on_quit="detach")    # waits behind junban
    left_running = registry.submit("anki-sync", "Updating known words from Anki", lambda j: stop.wait(0),
                                   on_quit="detach")
    still = registry.quit(timeout=5)
    assert cancelled.state == J.DONE and cancelled.cancelled
    assert waited.state == J.DONE and not waited.cancelled
    assert {v.label for v in still} == {"Mining", "Updating known words from Anki"}
    assert left.state in (J.RUNNING, J.WAITING) and left_running.state == J.RUNNING


def test_ended_jobs_are_kept_only_to_a_limit():
    registry = JobRegistry(keep_ended=3)
    for n in range(6):
        registry.submit("child", f"job {n}", lambda j: None).finish()
    assert [v.label for v in registry.snapshot()] == ["job 3", "job 4", "job 5"]


def test_an_unknown_quit_choice_is_refused():
    with pytest.raises(ValueError):
        JobRegistry().submit("generate", "Generating", lambda j: None, on_quit="never")
