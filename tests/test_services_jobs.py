"""The job registry (`app/services/jobs.py`) — W1.3, the window's spec 04 §4.2.

What a wrong answer would cost:
  * two writers at once — Generate and the indexer both writing the token store, or two programs writing Anki;
  * an automatic job taking the turn of one the user asked for (the user waits on something they didn't ask for);
  * a stuck bar — a job whose start failed left "running" forever, or a listener's fault stopping every update;
  * a bar that changes under the window's hands — a snapshot that moves after it was taken;
  * closing that hangs or leaves work half-done — quitting must cancel, wait for or leave each job as it says.
"""
import threading
import time

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


def test_a_job_asked_to_stop_too_late_that_completes_is_recorded_done_not_cancelled():
    """W3.5 row 7 (E3.2's A13): a Generate asked to stop once it writes your list can't stop there and finishes. Its
    owner says so (`completed=True`), and the registry takes back the flag the ask set: the bar never calls a run
    that wrote everything a cancel. A plain finish after the ask keeps the flag (the ask is still what ended it)."""
    registry, asked = JobRegistry(), []
    late = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: asked.append(j.id))
    assert late.cancel() and late.state == J.CANCELLING and late.cancelled
    late.finish(ok=True, completed=True)
    view = registry.snapshot()[-1]
    assert (view.state, view.cancelled) == (J.DONE, False)
    assert late.ended.is_set() and asked == [late.id]
    stopped = registry.submit("generate", "Generating again", lambda j: None, cancel=lambda j: None)
    stopped.cancel()
    stopped.finish(ok=True)
    assert (stopped.state, stopped.cancelled) == (J.DONE, True)
    stopped.finish(ok=True, completed=True)              # ended already: a second finish changes nothing
    assert stopped.cancelled


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


def test_quit_lets_an_anki_write_finish_its_batch_and_drops_one_that_never_started():
    """IK-22 / HR-22 (E20: "an Anki write finishes its batch first"): a running `wait` job is waited for up to its own
    `wait_timeout`, past the window's short `timeout` for the rest; a `wait` job that never started (held back by the
    update, or behind another writer) has nothing to finish — it is dropped, never waited for, never started."""
    registry = JobRegistry()
    registry.gate(lambda kind: "waits for the update" if kind == "anki-sync" else None)
    held = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, automatic=True,
                           on_quit="wait")
    writing = registry.submit("junban", "Re-ordering Anki", lambda j: threading.Timer(0.4, j.finish).start(),
                              on_quit="wait")
    behind = registry.submit("backfill", "Filling Anki fields", lambda j: j.finish(), automatic=True, on_quit="wait")
    t0 = time.monotonic()
    still = registry.quit(timeout=0.05, wait_timeout=5)
    assert writing.state == J.DONE and not writing.cancelled          # its batch finished
    assert held.state == J.DONE and held.cancelled                    # held back: dropped, not waited for
    assert behind.state == J.DONE and behind.cancelled                # behind the writer: never started at quit
    assert still == () and time.monotonic() - t0 < 4


def test_quit_gives_a_job_it_cancels_only_the_short_timeout_never_an_anki_writes():
    """IK-22 / HR-22: `wait_timeout` is a running Anki write's alone. A `cancel` job still ending after its cancel
    (Generate past *Writing your list* can't stop part-way) is waited for the short `timeout` only and left running:
    the quit never waits an Anki write's cap (AnkiConnect's 30 s) for it."""
    registry = JobRegistry()
    writing_list = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: None, on_quit="cancel")
    t0 = time.monotonic()
    still = registry.quit(timeout=0.05, wait_timeout=5)
    assert time.monotonic() - t0 < 2
    assert [v.id for v in still] == [writing_list.id] and writing_list.state == J.CANCELLING
    writing_list.finish(cancelled=True)


def test_what_closing_the_window_waits_for_is_an_anki_write_under_way_only():
    """E20 (W3.5: the window stays up while an Anki write finishes its batch): only a `wait` job under way keeps it —
    one not started yet has nothing to finish (`quit` drops it), Generate (`cancel`) is stopped and Connect (`detach`)
    goes on without the window. One rule for the window and `quit` (`waits_at_quit`)."""
    registry = JobRegistry()
    writing = registry.submit("junban", "Re-ordering Anki", lambda j: None, on_quit="wait")
    behind = registry.submit("backfill", "Filling Anki fields", lambda j: None, on_quit="wait")    # behind the writer
    registry.submit("generate", "Generating", lambda j: None, on_quit="cancel")
    registry.submit("arrivals-ja", "New arrivals", lambda j: None, on_quit="detach")
    assert [v.id for v in J.waits_at_quit(registry.snapshot())] == [writing.id]
    writing.finish()                                                  # the one behind it starts
    assert [v.id for v in J.waits_at_quit(registry.snapshot())] == [behind.id]
    registry.cancel(behind.id)                                        # asked to stop: still under way until it ends
    assert [v.id for v in J.waits_at_quit(registry.snapshot())] == [behind.id]
    behind.finish(cancelled=True)
    assert J.waits_at_quit(registry.snapshot()) == ()


def test_a_job_that_passes_the_point_it_can_stop_at_while_the_quit_waits_is_waited_for_as_an_anki_write():
    """E20: Generate cancelled at quit may already be writing your list (the window reads its step a moment late). Once
    its owner says it is past its cancel point (`finishes_at_quit`) — while the quit waits its short `timeout` for it —
    the quit gives it an Anki write's `wait_timeout` instead: the process's exit never cuts a list half-written."""
    registry = JobRegistry()
    run = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: None, on_quit="cancel")

    def child():
        time.sleep(0.2)
        run.finishes_at_quit()                                        # the step read late: it is writing
        time.sleep(0.6)                                               # past the short timeout: still writing
        run.finish()
    threading.Thread(target=child, daemon=True).start()
    t0 = time.monotonic()
    still = registry.quit(timeout=0.5, wait_timeout=5)
    assert still == () and run.state == J.DONE and time.monotonic() - t0 < 4
    assert registry.snapshot()[0].on_quit == "wait"



def test_a_job_that_passes_its_stop_point_during_the_quit_is_held_only_to_the_shorter_finish_cap():
    """The other way round: the window already spent most of its finish cap, so what is left (`wait_timeout`) is
    shorter than the quit's `timeout`. A job that turns `wait` meanwhile is held to that shorter cap from the moment it
    turns, never to the longer one it started under: the exit stays within the window's promise."""
    registry = JobRegistry()
    run = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: None, on_quit="cancel")
    done = threading.Event()

    def child():
        time.sleep(0.1)
        run.finishes_at_quit()                                        # writing now, and it never ends in time
        done.wait(10)
        run.finish()
    threading.Thread(target=child, daemon=True).start()
    t0 = time.monotonic()
    still = registry.quit(timeout=3.0, wait_timeout=0.4)
    took = time.monotonic() - t0
    done.set()
    assert [v.kind for v in still] == ["generate"]
    assert took < 1.5

def test_the_pids_of_a_jobs_child_and_whether_it_can_be_cancelled_are_on_its_record():
    """The update's wait list reads them: a job's own child process is listed as the job alone, and a job with no
    cancel (the sync, the backlog read) has no *Stop it* whatever it does at quit."""
    registry = JobRegistry()
    gen = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: None)
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, on_quit="detach")
    gen.started_process(4242)
    views = {v.kind: v for v in registry.snapshot()}
    assert (views["generate"].pid, views["generate"].can_cancel) == (4242, True)
    assert (views["anki-sync"].pid, views["anki-sync"].can_cancel) == (None, False)


def test_ended_jobs_are_kept_only_to_a_limit():
    registry = JobRegistry(keep_ended=3)
    for n in range(6):
        registry.submit("child", f"job {n}", lambda j: None).finish()
    assert [v.label for v in registry.snapshot()] == ["job 3", "job 4", "job 5"]


def test_an_unknown_quit_choice_is_refused():
    with pytest.raises(ValueError):
        JobRegistry().submit("generate", "Generating", lambda j: None, on_quit="never")


def test_a_gate_holds_gated_jobs_until_it_opens_and_cancel_by_id():
    """W3.5 row 1: the update's gate — a job its check names a reason for waits with that reason (a recorded child is
    never held: its owner started it); `reschedule()` after the gate opens starts it; `cancel(job_id)` is *Stop it*."""
    registry, started, closed = JobRegistry(), [], [True]
    registry.gate(lambda kind: "waits for the update" if closed[0] and kind == "generate" else None)
    gen = registry.submit("generate", "Generating", _starter(started))
    idx = registry.submit("junban", "Re-ordering Anki", _starter(started))
    child = registry.record("child", "Content Manager")
    assert (gen.state, gen.reason) == (J.WAITING, "waits for the update")
    assert idx.state == J.RUNNING and child.state == J.RUNNING and started == ["Re-ordering Anki"]
    closed[0] = False
    registry.reschedule()
    assert gen.state == J.RUNNING and started == ["Re-ordering Anki", "Generating"]
    assert registry.cancel(gen.id) is True and gen.state == J.CANCELLING
    assert registry.cancel(10_000) is False


# --- W3.5 worker K: the Haiku mutant list's survivors ------------------------------------------------------------ #
def test_cancelling_a_waiting_users_job_lets_the_automatic_one_behind_it_start():
    """`_cancel_job` schedules again: a user's Generate held back (here by a gate) is cancelled before it started, and
    the automatic indexer that yielded to it starts at once — never a stuck *waits for Generating* behind a job that no
    longer exists."""
    registry, started = JobRegistry(), []
    registry.gate(lambda kind: "waits for the update" if kind == "generate" else None)
    users = registry.submit("generate", "Generating", _starter(started))
    auto = registry.submit("indexer", "Indexing", _starter(started), automatic=True)
    assert users.state == J.WAITING and (auto.state, auto.reason) == (J.WAITING, "waits for Generating")
    assert users.cancel() and users.state == J.DONE and users.cancelled
    assert auto.state == J.RUNNING and auto.reason is None and started == ["Indexing"]


def test_a_gate_that_raises_holds_nothing_back():
    """`_held`: a gate whose check fails lets the job start (a failed start is a failed job, never a stuck one — and a
    broken check never holds every job back for good)."""
    registry, started = JobRegistry(), []

    def broken(kind):
        raise RuntimeError("the update's flag couldn't be read")
    registry.gate(broken)
    job = registry.submit("generate", "Generating", _starter(started))
    assert job.state == J.RUNNING and job.reason is None and started == ["Generating"]


def test_a_users_job_held_by_a_gate_keeps_its_turn_before_a_later_conflicting_one():
    """The order asked for (`_blocker`'s `earlier`): the user's Generate, held by the update's gate, still holds back the
    indexer the user asked for after it (both write the token store); when the gate opens the Generate runs first."""
    registry, started, hold = JobRegistry(), [], [True]
    registry.gate(lambda kind: "waits for the update" if hold[0] and kind == "generate" else None)
    gen = registry.submit("generate", "Generating", _starter(started))
    idx = registry.submit("indexer", "Indexing", _starter(started))
    assert (gen.state, gen.reason) == (J.WAITING, "waits for the update")
    assert (idx.state, idx.reason) == (J.WAITING, "waits for Generating") and started == []
    hold[0] = False
    registry.reschedule()
    assert gen.state == J.RUNNING and idx.state == J.WAITING and started == ["Generating"]
    gen.finish()
    assert idx.state == J.RUNNING and started == ["Generating", "Indexing"]


# --- row 35: what goes on after the window closes, and *Stop and quit* ------------------------------------------- #
# What a wrong answer would cost: a sheet at every close (or none while Surasura's helpers hold its folder), and —
# worst — *Stop and quit* ending something it must not: a Content Manager mid-import, Connect mid-batch (Anki's), or a
# process the window never started.
def test_what_outlives_the_window_is_the_upkeep_or_connect_and_nothing_else():
    """`detached_at_quit`, by kind: the library's upkeep (`STOPPABLE_AT_QUIT`) and Connect making cards
    (`CONNECT_KIND`) go on without the window; a sync on the window's own thread, a Content Manager child (`detach`,
    with a pid), the update, Generate (`cancel`) and an Anki write (`wait`) are never named."""
    registry = JobRegistry()
    upkeep = registry.record("library-maintain", "Tidying your library", on_quit="detach")
    upkeep.started_process(4321)
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, on_quit="detach")
    manager = registry.record("child", "Content Manager", on_quit="detach")
    manager.started_process(5555)                             # a pid is no reason: it may be mid-import
    registry.submit("generate", "Generating", lambda j: None, on_quit="cancel")
    registry.submit("junban", "Re-ordering Anki", lambda j: None, on_quit="wait")
    mine = registry.record(J.CONNECT_KIND, "Making cards", on_quit="detach")
    update = registry.submit("update", "Downloading the update", lambda j: None, on_quit="detach")
    update.started_process(6666)
    assert sync.state == J.RUNNING and update.state == J.RUNNING
    assert [v.id for v in J.detached_at_quit(registry.snapshot())] == [upkeep.id, mine.id]
    upkeep.finish()
    mine.finish()
    assert J.detached_at_quit(registry.snapshot()) == ()
    assert J.detached_at_quit(()) == ()
    assert J.CONNECT_KIND == "mine" and J.STOPPABLE_AT_QUIT == ("library-maintain",)


def test_the_rule_reads_jobs_as_well_as_views():
    registry = JobRegistry()
    upkeep = registry.record("library-maintain", "Tidying your library", on_quit="detach")
    assert J.detached_at_quit([upkeep]) == (upkeep,)


def test_stop_and_quit_cancels_the_upkeep_alone_through_its_owner_never_connect_nor_another_child():
    """`stop_at_quit` reads the registry now and asks the owner (its cancel callback, which holds the Popen) — only for
    a `STOPPABLE_AT_QUIT` kind: never Connect (even one with a pid and a cancel), never a Content Manager child, never
    a sync, never a job already ended."""
    registry, asked = JobRegistry(), []
    upkeep = registry.record("library-maintain", "Tidying your library", cancel=lambda j: asked.append(j.kind),
                             on_quit="detach")
    registry.record(J.CONNECT_KIND, "Making cards", cancel=lambda j: asked.append(j.kind), on_quit="detach")
    registry.record("child", "Content Manager", cancel=lambda j: asked.append(j.kind), on_quit="detach")
    registry.submit("anki-sync", "Updating known words from Anki", lambda j: None,
                    cancel=lambda j: asked.append(j.kind), on_quit="detach")
    ended = registry.record("library-maintain", "Tidying your library", cancel=lambda j: asked.append("ended"),
                            on_quit="detach")
    ended.finish()
    assert J.stop_at_quit(registry) == (upkeep.id,)
    assert asked == ["library-maintain"] and upkeep.state == J.CANCELLING
    assert J.stop_at_quit(registry) == ()                     # asked once: a second answer asks nothing again
    assert J.stop_at_quit(JobRegistry()) == ()
