"""The status service (W1.3; the window's spec 04 §4.2): one snapshot for the bottom bar and *Needs you*.

What it holds, refreshed off the window's thread:
- the running jobs' lines, in the user's words (G1.5-2, "subtle but there": *Updating known words from Anki* ·
  *Generating* · *Re-ordering Anki* · *Mining 12 words*), each with its step when the job reports one;
- the newest command-line failure (P0.3 02 §4, ✅ G0.3-1: shown in the bar, never a box), read from the events file
  through `cli.events.Reader` — `changed()` is a stat, the read happens on a worker — in plain words (`plain`);
- *Needs you*'s entries from the same failures (Sonic's 3.0 addition: a failure once looked at no longer counts, but
  stays listed; the logs folder is one more row);
- the AnkiWeb mark (G1.5-7) and Connect's line, from providers the window registers once their specs exist (the
  window's spec 04 §4.4 gaps 10 and 9): `None` until then. A provider that fails leaves the rest of the snapshot.

`poll()` is safe on a window's thread (a stat, nothing read); it starts a refresh on a worker when the file changed.
`subscribe(cb)` hears every new snapshot, on the thread that made it (a worker, or the registry's).
"""
import threading
import time
from collections import namedtuple

from app.services import jobs as jobs_module

Entry = namedtuple("Entry", "text at seen")
Snapshot = namedtuple("Snapshot", "lines failure needs_you ankiweb connect logs taken_at")
NEEDS_YOU_KEPT = 50


def job_line(view):
    """A running job's line: its label, and its step when it reports one ("Generating · Reading your files 3 / 12")."""
    if view.state == jobs_module.CANCELLING:
        return f"{view.label} · stopping"
    if view.state == jobs_module.WAITING and view.reason:
        return f"{view.label} · {view.reason}"
    progress = view.progress
    if progress is None or not progress.step:
        return view.label
    if progress.total:
        return f"{view.label} · {progress.step} {progress.done or 0} / {progress.total}"
    return f"{view.label} · {progress.step}"


class StatusService:
    """`registry`: the window's job registry; `reader`: a `cli.events.Reader` (made on first use when None);
    `providers`: {"ankiweb": fn, "connect": fn} -> a line or None, called on the worker."""

    def __init__(self, registry, reader=None, providers=None, logs_folder=None):
        self.registry = registry
        self._reader = reader
        self.providers = dict(providers or {})
        self._logs_folder = logs_folder
        self._lock = threading.Lock()
        self._deliver = threading.RLock()
        self._lines = ()
        self._failure = None
        self._needs = []                 # Entry, newest first
        self._extra = {"ankiweb": None, "connect": None}
        self._refreshing = False
        self._subscribers = []
        self._logs_path = self._logs()
        self._snapshot = self._make()
        registry.subscribe(self._jobs_changed)
        self._jobs_changed(registry.snapshot())

    # --- reading ------------------------------------------------------------------------------------------------ #
    def snapshot(self):
        with self._lock:
            return self._snapshot

    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

    def poll(self):
        """A window's timer: a stat of the events file; a refresh on a worker when it changed. -> the snapshot now."""
        reader = self._reader
        if reader is None or reader.changed():
            self.refresh_soon()
        return self.snapshot()

    def refresh_soon(self):
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self.refresh, name="status-refresh", daemon=True).start()

    def mark_seen(self):
        """The user looked at *Needs you*: its entries stop counting, and stay listed."""
        with self._lock:
            self._needs = [e._replace(seen=True) for e in self._needs]
        self._publish()

    # --- the worker's side -------------------------------------------------------------------------------------- #
    def refresh(self):
        """Read new command-line failures and ask the providers (files and calls: a worker's)."""
        try:
            if self._reader is None:
                from app.cli import events
                self._reader = events.Reader()
            from app.cli import events
            newest = self._reader.newest_to_show()
            extra = {}
            for name in ("ankiweb", "connect"):
                provider = self.providers.get(name)
                try:
                    extra[name] = provider() if provider is not None else None
                except Exception as e:                  # one provider's fault never empties the bar
                    print(f"Status: the {name} line failed: {e}")
                    extra[name] = None
            with self._lock:
                if newest is not None:
                    self._failure = events.plain(newest)
                    self._needs.insert(0, Entry(self._failure, newest.get("time"), False))
                    del self._needs[NEEDS_YOU_KEPT:]
                self._extra = extra
        finally:
            with self._lock:
                self._refreshing = False
        self._publish()

    def _jobs_changed(self, views):
        lines = tuple(job_line(v) for v in views if v.state in (jobs_module.RUNNING, jobs_module.CANCELLING,
                                                                 jobs_module.WAITING))
        with self._lock:
            if lines == self._lines:
                return
            self._lines = lines
        self._publish()

    def _logs(self):
        if self._logs_folder is not None:
            return self._logs_folder
        try:
            from app.cli import contract
            return contract.log_folder()
        except Exception:
            return None

    def _make(self):
        return Snapshot(self._lines, self._failure, tuple(self._needs), self._extra.get("ankiweb"),
                        self._extra.get("connect"), self._logs_path, time.time())

    def _publish(self):
        """A new snapshot, delivered one at a time and only while it is the newest (never an older one last)."""
        with self._lock:
            self._snapshot = self._make()
            snap = self._snapshot
        with self._deliver:
            with self._lock:
                if snap is not self._snapshot:
                    return
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception as e:
                    print(f"Status: a listener failed: {e}")
