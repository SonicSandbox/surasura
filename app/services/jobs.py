"""The job registry (W1.3; the window's spec 04 §4.2): every job the window starts, one record each, and one table of
which jobs may run together.

A job is anything that runs while the window stays usable: Generate, the indexer, an Anki sync, 順's reorder, Connect's
mining, a child process. Its record — `id`, `kind`, `label` (the user's words: *Generating*), `state`, `progress`,
`started_at`, whether it was automatic, and what quitting does to it (`wait` · `cancel` · `detach`) — is what the bottom
bar shows (`snapshot()`), and a window hears every change (`subscribe`).

States: `queued` (asked for, not started) · `waiting` (held back, with its reason in plain words) · `running` ·
`cancelling` (asked to stop; still ending) · `done` · `failed` (with its message). A job cancelled before it started is
`done` with `cancelled` set.

The exclusion rules, in one table (`RESOURCES`): two jobs that use the same resource never run together — Generate and
the indexer both write the token store, and one Anki writer at a time (`anki-writer`, E1.4) — and never two of a kind.
An automatic job yields to one the user started: it never starts while a user's job it conflicts with is queued,
waiting or running; and a user's request absorbs a queued automatic job of its kind (one run, the user's). Jobs wait in
the order they were asked for.

A job is either **gated** (started by the registry when the table allows: `submit(…, start=…)`) or **recorded**
(`record(…)`: already started by its owner — the Tk dashboard's children — listed for the bar and never held back, nor
holding a gated job back). Nothing here waits on the caller's thread: `submit`, `record`, `snapshot` and a job's
`progress` / `finish` / `cancel` return at once; `start` and `cancel` callbacks must too (they start a thread or a
process). Callbacks to subscribers run on whichever thread changed the job; a window posts them to its own queue.
"""
import itertools
import threading
import time
from collections import namedtuple

QUEUED, WAITING, RUNNING, CANCELLING, DONE, FAILED = "queued", "waiting", "running", "cancelling", "done", "failed"
LIVE = (QUEUED, WAITING, RUNNING, CANCELLING)
QUIT_CHOICES = ("wait", "cancel", "detach")

# What each kind of job uses. Two jobs sharing a resource never run together; a kind always conflicts with itself.
RESOURCES = {
    "generate": {"token-store", "results"},
    "indexer": {"token-store"},
    "sentence-corpus": {"token-store"},
    "anki-sync": {"known-words"},
    "junban": {"anki-writer"},
    "backfill": {"anki-writer"},
    "mine": {"anki-writer"},
    "replan": {"anki-writer"},
}

Progress = namedtuple("Progress", "step done total")
JobView = namedtuple("JobView", "id kind label state reason message progress started_at ended_at automatic on_quit "
                                "cancelled gated")


def conflicts(kind_a, kind_b):
    """Whether two kinds of job may never run together (the one table)."""
    if kind_a == kind_b:
        return True
    return bool(RESOURCES.get(kind_a, set()) & RESOURCES.get(kind_b, set()))


class Job:
    """One job. Its owner reports `progress(...)` and `finish(...)`; anyone may `cancel()`."""

    def __init__(self, registry, job_id, kind, label, automatic, on_quit, start, cancel, gated):
        self._registry = registry
        self.id = job_id
        self.kind = kind
        self.label = label
        self.automatic = automatic
        self.on_quit = on_quit
        self._start = start
        self._cancel = cancel
        self.gated = gated
        self.state = QUEUED
        self.reason = None
        self.message = None
        self.progress_now = None
        self.started_at = None
        self.ended_at = None
        self.cancelled = False
        self.ended = threading.Event()

    def view(self):
        return JobView(self.id, self.kind, self.label, self.state, self.reason, self.message, self.progress_now,
                       self.started_at, self.ended_at, self.automatic, self.on_quit, self.cancelled, self.gated)

    def progress(self, step, done=None, total=None):
        """Where the running job is: a step in the user's words, and how far through it."""
        self._registry._change(self, progress=Progress(step, done, total))

    def finish(self, ok=True, message=None, cancelled=False):
        """The job ended: `done`, or `failed` with its message (plain words; a log's path where there is one);
        `cancelled` when it stopped because it was asked to."""
        self._registry._end(self, DONE if ok else FAILED, message, cancelled)

    def cancel(self):
        """Stop it: a job not started yet ends now (`done`, cancelled — its owner's cancel callback is told); a running
        one is asked to stop (`cancelling`) through that callback and ends when its owner says so. True when there was
        something to cancel."""
        return self._registry._cancel_job(self)

    def wait(self, timeout=None):
        """Wait until the job ended (a worker's call, never a window's thread). True when it has."""
        return self.ended.wait(timeout)


class JobRegistry:
    def __init__(self, keep_ended=20):
        self._lock = threading.RLock()
        self._jobs = []                     # every live job, in the order asked for, then the newest ended ones
        self._ids = itertools.count(1)
        self._subscribers = []
        self._keep_ended = keep_ended
        self._version = 0                   # each change's number: a listener never hears an older one after a newer
        self._deliver = threading.RLock()

    # --- asking ------------------------------------------------------------------------------------------------- #
    def submit(self, kind, label, start, cancel=None, automatic=False, on_quit="cancel"):
        """A gated job: `start(job)` is called (at once, or when the table allows) to begin the work; `cancel(job)`
        to ask a running one to stop. -> the Job (a user's request that absorbed a queued automatic one is still a new
        Job; the automatic one ends, cancelled)."""
        if on_quit not in QUIT_CHOICES:
            raise ValueError(f"on_quit must be one of {QUIT_CHOICES}")
        absorbed = []
        with self._lock:
            job = Job(self, next(self._ids), kind, label, automatic, on_quit, start, cancel, gated=True)
            if not automatic:
                for other in self._jobs:
                    if other.gated and other.automatic and other.kind == kind and other.state in (QUEUED, WAITING):
                        other.state, other.cancelled, other.reason = DONE, True, "joined your request"
                        other.ended_at = time.time()
                        absorbed.append(other)
            self._jobs.append(job)
        for other in absorbed:
            other.ended.set()
            self._tell_owner(other)
        self._schedule()
        return job

    def record(self, kind, label, cancel=None, automatic=False, on_quit="cancel"):
        """A job its owner started already (a child process): listed as running, never held back nor holding a gated
        job back."""
        with self._lock:
            job = Job(self, next(self._ids), kind, label, automatic, on_quit, None, cancel, gated=False)
            job.state, job.started_at = RUNNING, time.time()
            self._jobs.append(job)
        self._notify()
        return job

    # --- reading ------------------------------------------------------------------------------------------------ #
    def snapshot(self):
        """Every live job and the newest ended ones, as immutable records, oldest first."""
        with self._lock:
            return tuple(job.view() for job in self._jobs)

    def live(self, kind=None):
        with self._lock:
            return tuple(j.view() for j in self._jobs if j.state in LIVE and (kind is None or j.kind == kind))

    def subscribe(self, callback):
        """`callback(snapshot)` after every change, on the thread that made it."""
        with self._lock:
            self._subscribers.append(callback)

    # --- quitting ----------------------------------------------------------------------------------------------- #
    def quit(self, timeout=10.0):
        """What closing the window does to each live job: `cancel` ones are cancelled, `wait` ones waited for (up to
        `timeout` in all), `detach` ones left running. A worker's call. -> the jobs still running after it."""
        with self._lock:
            live = [j for j in self._jobs if j.state in LIVE]
        for job in live:
            if job.on_quit == "cancel":
                job.cancel()
        deadline = time.monotonic() + timeout
        for job in live:
            if job.on_quit in ("wait", "cancel"):
                job.wait(max(0.0, deadline - time.monotonic()))
        with self._lock:
            return tuple(j.view() for j in self._jobs if j.state in LIVE)

    # --- inside ------------------------------------------------------------------------------------------------- #
    def _blocker(self, job, earlier):
        """The job that holds `job` back, or None. Running jobs hold back what conflicts with them; a user's job asked
        for earlier holds back a later conflicting one (the order asked for), and any user's job an automatic one."""
        for other in self._jobs:
            if other is job or not other.gated or not conflicts(job.kind, other.kind):
                continue
            if other.state in (RUNNING, CANCELLING):
                return other
            if other.state in (QUEUED, WAITING):
                if job.automatic and not other.automatic:
                    return other                  # an automatic job yields to any user's job it conflicts with
                if other in earlier and not (other.automatic and not job.automatic):
                    return other                  # the order asked for — but a user's job never waits on an automatic one
        return None

    def _schedule(self):
        to_start = []
        with self._lock:
            earlier = []
            for job in [j for j in self._jobs if j.gated and j.state in (QUEUED, WAITING)]:
                blocker = self._blocker(job, earlier)
                if blocker is None:
                    job.state, job.reason, job.started_at = RUNNING, None, time.time()
                    to_start.append(job)
                else:
                    job.state = WAITING
                    job.reason = f"waits for {blocker.label}"
                earlier.append(job)
        self._notify()
        for job in to_start:
            try:
                job._start(job)
            except Exception as e:                    # a start that fails is a failed job, never a stuck one
                self._end(job, FAILED, f"couldn't start: {e}")

    def _change(self, job, progress=None):
        with self._lock:
            if job.state not in (RUNNING, CANCELLING):
                return
            job.progress_now = progress
        self._notify()

    def _end(self, job, state, message, cancelled=False):
        with self._lock:
            if job.state in (DONE, FAILED):
                return
            job.state, job.message, job.ended_at = state, message, time.time()
            job.cancelled = job.cancelled or cancelled
            self._trim()
        job.ended.set()
        self._schedule()

    def _cancel_job(self, job):
        call = None
        with self._lock:
            if job.state in (QUEUED, WAITING):
                job.state, job.cancelled, job.ended_at = DONE, True, time.time()
                job.reason = None
                ended = True
            elif job.state == RUNNING:
                job.state, job.cancelled = CANCELLING, True
                call, ended = job._cancel, False
            else:
                return False
        if ended:
            job.ended.set()
            self._tell_owner(job)
            self._schedule()
            return True
        self._notify()
        if call is not None:
            try:
                call(job)
            except Exception as e:
                print(f"Jobs: cancelling {job.label} failed: {e}")
        return True

    @staticmethod
    def _tell_owner(job):
        """A job that ended before it started: its owner hears through its cancel callback (it may be waiting on it)."""
        if job._cancel is None:
            return
        try:
            job._cancel(job)
        except Exception as e:
            print(f"Jobs: telling {job.label}'s owner failed: {e}")

    def _trim(self):
        ended = [j for j in self._jobs if j.state not in LIVE]
        for old in ended[:-self._keep_ended] if len(ended) > self._keep_ended else []:
            self._jobs.remove(old)

    def _notify(self):
        with self._lock:
            self._version += 1
            version = self._version
        with self._deliver:                           # one delivery at a time, and only the newest
            with self._lock:
                if version != self._version:
                    return
                snap = tuple(job.view() for job in self._jobs)
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception as e:                # a listener's fault never stops the registry
                    print(f"Jobs: a listener failed: {e}")
