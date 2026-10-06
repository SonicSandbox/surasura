"""The status service (`app/services/status.py`) — W1.3, the window's spec 04 §4.2.

What a wrong answer would cost:
  * a silent window — Sonic asked to see, subtly, that Surasura is updating known words, generating, re-ordering Anki
    (G1.5-2); a running job with no line is invisible work;
  * a command-line failure that freezes or hides — it must reach the bar in plain words, once, never as a box (G0.3-1),
    and stay listed in *Needs you* after it was looked at;
  * an empty bar because one part failed — a provider's fault must leave the rest;
  * a stutter — the window's poll must be a stat, never a read.
"""
import os

from app.cli import contract
from app.services import jobs as J
from app.services.jobs import JobRegistry
from app.services.status import StatusService, job_line
from tests import services_helpers as h


def _failure(verb="status", message="Surasura's settings (settings.json) can't be read."):
    contract._record_event({"type": "error", "contract": 1, "ok": False, "code": "bad-data", "message": message,
                            "verb": verb, "exit": 1, "time": "2026-10-06T01:00:00"})


def test_running_jobs_show_in_the_users_words_with_their_step():
    registry = JobRegistry()
    status = StatusService(registry)
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, automatic=True)
    gen = registry.submit("generate", "Generating", lambda j: None)
    gen.progress("Reading your files", 3, 12)
    assert status.snapshot().lines == ("Updating known words from Anki", "Generating · Reading your files 3 / 12")
    registry.submit("generate", "Generating (automatic)", lambda j: None, automatic=True)
    assert status.snapshot().lines[-1] == "Generating (automatic) · waits for Generating"
    sync.finish()
    gen.cancel()
    assert status.snapshot().lines[0] == "Generating · stopping"


def test_job_line_for_a_step_without_counts():
    view = J.JobView(1, "mine", "Mining 12 words", J.RUNNING, None, None, J.Progress("Asking Anki Miner", None, None),
                     0, None, True, "cancel", False, True)
    assert job_line(view) == "Mining 12 words · Asking Anki Miner"


def test_a_command_line_failure_reaches_the_bar_once_in_plain_words_and_stays_in_needs_you():
    status = StatusService(JobRegistry())
    status.refresh()                                       # the reader starts at the file's end: history isn't news
    _failure()
    assert status.poll() is not None
    assert h.until(lambda: status.snapshot().failure is not None, seconds=10)
    snap = status.snapshot()
    assert snap.failure.startswith("Command line (status): Surasura's settings (settings.json) can't be read")
    assert [e.seen for e in snap.needs_you] == [False]
    status.mark_seen()
    status.refresh()                                       # nothing new: no second entry
    assert [e.seen for e in status.snapshot().needs_you] == [True]
    assert status.snapshot().logs == contract.log_folder()


def test_poll_is_a_stat_within_4_ms():
    status = StatusService(JobRegistry())
    status.refresh()
    for _ in range(20):
        _, ms = h.timed(status.poll)
        assert ms <= 4, ms


def test_a_provider_that_fails_leaves_the_rest_of_the_snapshot():
    registry = JobRegistry()

    def broken():
        raise OSError("the sync state can't be read")
    status = StatusService(registry, providers={"ankiweb": broken, "connect": lambda: "Connect: 3 words to mine"})
    registry.submit("generate", "Generating", lambda j: None)
    status.refresh()
    snap = status.snapshot()
    assert snap.ankiweb is None and snap.connect == "Connect: 3 words to mine" and snap.lines == ("Generating",)


def test_subscribers_hear_each_new_snapshot_and_a_failing_one_is_harmless():
    registry = JobRegistry()
    status = StatusService(registry)
    heard = []

    def broken(_snap):
        raise RuntimeError("a listener's own fault")
    status.subscribe(broken)
    status.subscribe(heard.append)
    registry.submit("junban", "Re-ordering Anki", lambda j: None)
    assert heard and heard[-1].lines == ("Re-ordering Anki",)


def test_without_an_events_file_the_bar_is_quiet():
    """A first run: no logs folder yet. Nothing fails, nothing shows."""
    status = StatusService(JobRegistry())
    status.refresh()
    assert status.snapshot().failure is None and not os.path.exists(os.path.join(contract.log_folder(),
                                                                                 "cli-events.jsonl"))


def test_poll_never_reads_the_events_file_on_the_callers_thread():
    """The read (`new()`) is a worker's, even when the file changed: only the stat runs where the window calls."""
    import threading
    status = StatusService(JobRegistry())
    status.refresh()
    reads, real_new = [], status._reader.new

    def recording_new():
        reads.append(threading.current_thread())
        return real_new()
    status._reader.new = recording_new
    _failure()
    caller = threading.current_thread()
    status.poll()
    assert h.until(lambda: reads, seconds=10)
    assert caller not in reads
