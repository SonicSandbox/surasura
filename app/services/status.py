"""The status service (W1.3; the window's spec 04 §4.2): one snapshot for the bottom bar and *Needs you*.

What it holds, refreshed off the window's thread:
- the running jobs' lines, in the user's words (G1.5-2, "subtle but there": *Updating known words from Anki* ·
  *Generating* · *Re-ordering Anki* · *Mining 12 words*), each with its step when the job reports one;
- the newest command-line failure (P0.3 02 §4, ✅ G0.3-1: shown in the bar, never a box), read from the events file
  through `cli.events.Reader` — `changed()` is a stat, the read happens on a worker — in plain words (`plain`);
- *Needs you*'s entries from the same failures (Sonic's 3.0 addition: a failure once looked at no longer counts, but
  stays listed; the logs folder is one more row);
- the AnkiWeb mark (G1.5-7) and Connect's line, from providers the window registers once their specs exist (the
  window's spec 04 §4.4 gaps 10 and 9): `None` until then. A provider that fails leaves the rest of the snapshot;
- the failures of the window's own duties (W3.5, E10, IK-7), from providers too — `update` (the update service's
  newest failure not looked at yet) and `generate` (Generate's, while it reads `failed`): each new one is the bar's
  failure line, as a command-line one is, and (but the update's: Needs you lists those itself, with their actions)
  a *Needs you* entry. Their service says when to look again (`refresh_soon`). A duty's line is the bar's while its
  provider gives it (Generate failed until it runs cleanly again, the update's failure until looked at), then it goes
  — still listed (HR-23); a command line's stays the bar's until a newer one.

- the re-order host's passing line (`replan`: *Anki: placing tomorrow's 20 cards…* → *Anki's order is up to date*,
  *Generate first*) and the journey dot (`journey`, G10: True while the store's `journey_pending()` says the sentences
  are owed), from providers the window registers (W3.5 row 7): `None` without one. The host says when its line moved
  (`refresh_soon("replan")`); the dot is asked again with every refresh of everything.
- the new cards waiting in Anki (`backlog`, W31A-2: the footer's *Anki · N waiting*), counted from the Anki sync's
  saved backlog by a provider the window registers (`anki_backlog`), ticking every 3 s with a stat: `None` without
  one, or while no backlog has been saved.

`poll()` is safe on a window's thread (a stat and a clock compare, nothing read); it starts a refresh on a worker when
the file changed, and a look at the ticking providers when their period is up (G5): Connect's line every 3 s (the Tk
`status_row.StatusRow`'s EVERY_MS) while Connect is on, the AnkiWeb mark every second while it counts down, else every
3 s (S19: a look that can't change anything isn't taken every second). `refresh_soon(*names)` asks the providers
named (none: everything). `subscribe(cb)` hears a snapshot only when something in it changed (S19: a tick that changes
nothing delivers nothing), on the thread that made it (a worker, or the registry's).

The window's providers for Connect, AnkiWeb and the dot are the plain functions at the end (`connect_line`,
`ankiweb_line`, `journey_pending`): they call the Tk-free rules (`connect.status`, `anki_sync_rule.status`,
`library_store`), never copy them, and live here so the window registers them from the module it already imports.
"""
import os
import threading
import time
import weakref
from collections import namedtuple

from app.services import jobs as jobs_module

Entry = namedtuple("Entry", "text at seen")
Snapshot = namedtuple("Snapshot", "lines failure needs_you ankiweb connect logs taken_at replan journey backlog",
                      defaults=(None, None, None))
NEEDS_YOU_KEPT = 50
LINE_PROVIDERS = ("ankiweb", "connect", "replan", "journey", "backlog")   # `journey`: True / False; `backlog`: a count
TICKS = {"connect": 3.0, "ankiweb": 1.0, "backlog": 3.0}  # seconds between a ticking provider's looks (`poll`); a
                                          # provider with an `every()` says its own now (None: not ticking now)
FAILURE_PROVIDERS = ("update", "generate")
LISTED_BY_THE_WINDOW = ("update",)       # failures Needs you shows from their own service, with their actions


def job_line(view):
    """A running job's line: its label, and its step when it reports one ("Generating · Reading your files 3 / 12")."""
    if view.state == jobs_module.CANCELLING:
        return f"{view.label} · stopping"
    if view.state == jobs_module.WAITING and view.reason:
        return f"{view.label} · {view.reason}"
    progress = view.progress
    if progress is None or not (progress.step or progress.total):
        return view.label
    if progress.total:                                  # (a count with no step: *Making cards · 3 / 12*, row 40)
        step = f"{progress.step} " if progress.step else ""
        return f"{view.label} · {step}{progress.done or 0} / {progress.total}"
    return f"{view.label} · {progress.step}"


class StatusService:
    """`registry`: the window's job registry; `reader`: a `cli.events.Reader` (made on first use when None);
    `providers`: {"ankiweb": fn, "connect": fn, "replan": fn, "journey": fn, "update": fn, "generate": fn} -> a line
    (or the dot) or None, called on the worker (`FAILURE_PROVIDERS`' lines are failures). A window may add providers
    later (`providers` is the dict asked). `clock`: the ticks' (`time.monotonic`; a test's stand-in)."""

    def __init__(self, registry, reader=None, providers=None, logs_folder=None, clock=None):
        self.registry = registry
        self._reader = reader
        self.providers = dict(providers or {})
        self._clock = clock or time.monotonic
        self._ticked = {}                # each ticking provider's last look (the clock's), started by `poll`
        self._logs_folder = logs_folder
        self._lock = threading.Lock()
        self._deliver = threading.RLock()
        self._lines = ()
        self._failure = None
        self._failure_from = None        # the failure provider whose line the bar's failure is (None: a command line's)
        self._needs = []                 # Entry, newest first
        self._extra = dict.fromkeys(LINE_PROVIDERS)
        self._provided = {}              # each failure provider's last line (a new one counts once)
        self._refreshing = False
        self._wanted = set()             # asked for while a refresh ran (it runs once more): the providers named,
        self._wanted_all = False         # ... or everything
        self._subscribers = []
        self._logs_path = self._logs()
        # The events file's path, settled now (on the window's start): a refresh later never works one out again.
        self._events_path = None
        if reader is None:
            try:
                from app.cli import events
                self._events_path = events.path()
            except Exception:
                self._events_path = None
        self._snapshot = self._make()
        self._heard = _content(self._snapshot)     # what the subscribers last heard (S19: the same again is not news)
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
        """A window's timer: a stat of the events file, a refresh on a worker when it changed; else the ticking
        providers whose period is up, asked on a worker (G5). A clock compare, nothing read. With no events file to
        watch (its path couldn't be worked out), the ticks alone (never a full refresh every poll). -> the
        snapshot now."""
        reader = self._reader
        if (reader is None and self._events_path) or (reader is not None and reader.changed()):
            self.refresh_soon()
        else:
            due = self._due()
            if due:
                self.refresh_soon(*due)
        return self.snapshot()

    def refresh_soon(self, *names):
        """A refresh on a worker: of the providers `names`, or (none named) the events file and every provider. Asked
        for while one runs (which may have asked its providers already), it runs once more after it — a request is
        never dropped."""
        with self._lock:
            if names:
                self._wanted.update(names)
            else:
                self._wanted_all = True
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh_while_asked, name="status-refresh", daemon=True).start()

    def mark_seen(self):
        """The user looked at *Needs you*: its entries stop counting, and stay listed. Nothing unseen: no new snapshot
        (S19)."""
        with self._lock:
            if all(e.seen for e in self._needs):
                return
            self._needs = [e._replace(seen=True) for e in self._needs]
        self._publish()

    def _refresh_while_asked(self):
        while True:
            with self._lock:
                names = None if self._wanted_all else tuple(self._wanted)
                self._wanted_all, self._wanted = False, set()
            try:
                self.refresh(names)
            except Exception as e:                      # a fault of this refresh never drops the next one asked for
                print(f"Status: the refresh failed: {e}")
            with self._lock:                            # the loop owns the flag: no second refresh starts between two
                if not (self._wanted_all or self._wanted):
                    self._refreshing = False
                    return

    def _due(self):
        """The registered ticking providers whose period is up, each counted as looked at now."""
        now = self._clock()
        due = []
        with self._lock:
            for name, every in TICKS.items():
                provider = self.providers.get(name)
                if provider is None:
                    continue
                period = getattr(provider, "every", None)
                if period is not None:
                    every = period()                    # the provider's own, from its last look (no read)
                    if every is None:
                        continue                        # not ticking now (Connect off): asked by name when it moves
                last = self._ticked.get(name)
                if last is None or now - last >= every:
                    self._ticked[name] = now
                    due.append(name)
        return due

    # --- the worker's side -------------------------------------------------------------------------------------- #
    def refresh(self, names=None):
        """Read new command-line failures and ask the providers (files and calls: a worker's). `names`: those providers
        alone (a tick, the host's new line), the others' answers kept; None: the events file and every provider."""
        try:
            from app.cli import events
            newest = None
            if names is None:
                if self._reader is None and self._events_path:
                    self._reader = events.Reader(events_path=self._events_path)
                newest = self._reader.newest_to_show() if self._reader is not None else None
            extra = {}
            for name in LINE_PROVIDERS + FAILURE_PROVIDERS:
                if names is not None and name not in names:
                    continue
                provider = self.providers.get(name)
                try:
                    extra[name] = provider() if provider is not None else None
                except Exception as e:                  # one provider's fault never empties the bar
                    print(f"Status: the {name} line failed: {e}")
                    extra[name] = None
            with self._lock:
                if newest is not None:
                    self._failure, self._failure_from = events.plain(newest), None
                    self._needs.insert(0, Entry(self._failure, newest.get("time"), False))
                for name in FAILURE_PROVIDERS:
                    if name not in extra:
                        continue                                            # not asked this time
                    line = extra.pop(name)
                    if line and line != self._provided.get(name):
                        self._failure, self._failure_from = line, name      # the newest failure is the bar's
                        if name not in LISTED_BY_THE_WINDOW:
                            self._needs.insert(0, Entry(line, time.strftime("%Y-%m-%dT%H:%M:%S"), False))
                    elif not line and self._failure_from == name:
                        self._failure, self._failure_from = None, None      # over, or looked at: off the bar
                    self._provided[name] = line
                del self._needs[NEEDS_YOU_KEPT:]
                self._extra.update(extra)
        finally:
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
                        self._extra.get("connect"), self._logs_path, time.time(), self._extra.get("replan"),
                        self._extra.get("journey"), self._extra.get("backlog"))

    def _publish(self):
        """A new snapshot, delivered one at a time and only while it is the newest (never an older one last), and only
        when something in it changed since the subscribers last heard one (S19)."""
        with self._lock:
            self._snapshot = self._make()
            snap = self._snapshot
        with self._deliver:
            with self._lock:
                if snap is not self._snapshot or _content(snap) == self._heard:
                    return
                self._heard = _content(snap)
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception as e:
                    print(f"Status: a listener failed: {e}")


def _content(snap):
    """What a snapshot says, its time aside: two that say the same are one to a subscriber."""
    return snap._replace(taken_at=None)


# --- the window's providers (W3.5 row 7): plain functions, each made once per window and language ---------------- #
CONNECT_JOB_KIND = "mine"                 # Connect's mining as the window's registry lists it (laptop row 40)
CONNECT_JOB_LABEL = "Making cards"
CONNECT_JOB_MISSED = 2                    # looks without mining before its job ends (a gap between two batches)
_mirrored = weakref.WeakKeyDictionary()   # registry -> [its Connect job or None, its step, looks missed]


def mirror_connect(registry, got):
    """Laptop row 40 ("I can't tell what my actions trigger"): Connect mines in its own process, so its work was a quiet
    mark the bottom-left line never named. While the feed says an item is being mined, the window's one job registry
    lists it as a recorded job (`record`: never holding a job back; `detach` at quit: Connect goes on) — the line reads
    *Making cards · <its step> 40%* — told only when its step moved (S19), and ended after `CONNECT_JOB_MISSED` looks
    with none (no blink between two batches), or at once when the feed is gone (`got` None: another language's, the
    window's provider replaced). `connect_line(registry=)` calls it each look. A worker's call (the status service's
    refresh, one at a time)."""
    if registry is None:
        return
    held = _mirrored.setdefault(registry, [None, None, 0])
    item = next((it for it in (got.items.values() if got is not None and got.on else ())
                 if it.kind == "mining"), None)
    if item is None:
        held[2] += 1
        if held[0] is not None and (got is None or held[2] >= CONNECT_JOB_MISSED):
            held[0].finish()
            held[:] = [None, None, 0]
        return
    held[2] = 0
    if held[0] is None or held[0].state not in jobs_module.LIVE:
        held[:] = [registry.record(CONNECT_JOB_KIND, CONNECT_JOB_LABEL, automatic=True, on_quit="detach"), None, 0]
    if item.progress is not None:
        step = (f"{item.doing} {item.progress}%" if item.doing else f"{item.progress}%", None, None)
    else:
        step = (item.doing, item.made, item.total) if item.total else (item.doing, None, None)
    if step != held[1] and any(x is not None for x in step):
        held[1] = step
        held[0].progress(*step)


def connect_line(language, settings, stamp=None, read=None, feed=None, registry=None):
    """Connect's line for `language` (gap 9; the Tk `status_row.StatusRow`'s look) -> a provider. `settings()`: the
    settings now (the settings service's `get`). P4.1 L2 (row 4.1.13, W-A5): it is the window's Connect feed's
    (`app/connect/feed.Provider`, `feed`: the one the library reader's stones are built from, else one made here) —
    one stamp a tick for the line and the stones: each look takes Connect's `stamp` (two stats and a look at its lock)
    and reads the record only when it moved, so an unchanged Connect reads nothing (S19), and a new Feed wakes the
    reader (`Provider.on_change`). None while Connect isn't set up (`connect_enabled` off: no mark, as before); with
    it set up but D29's automation off (`settings_manager.connect_on`, F-7) the feed's line says why nothing runs (IK
    N4). `stamp` / `read`: Connect's `status.stamp` / `status.read` (a test's stand-ins). A worker's call, one at a
    time (the service's refresh). `provider.every()`: its tick, 3 s — none once a look found Connect off (the window
    asks for it by name when the switch lands; any full refresh asks it too)."""
    from app.connect import feed as connect_feed
    if feed is None:
        feed = connect_feed.Provider(language, settings, stamp=stamp, read=read)
    mirror_connect(registry, None)                      # the language before's job, if any, ends

    def provider():
        got = feed.feed()
        mirror_connect(registry, got)
        if not got.on and got.line == connect_feed.OFF_CONNECT:
            return None                                 # not set up (`connect_enabled` off): no Connect mark at all
        return got.line
    provider.every = lambda: TICKS["connect"] if feed.every() else None
    return provider


def ankiweb_line(settings, now=None):
    """The AnkiWeb mark (gap 10, G1.5-7) -> a provider: `anki_sync_rule.status` (*AnkiWeb: syncing in 45 s*, *synced
    18:42*, …), None before any. `settings()`: the settings now; `now()`: the wall clock (a test's stand-in). Asked
    every second: its state file is read again only when its stamp (mtime, size) moved, else the last read is worked
    out again for the time now — the countdown ticks, the disk is only stat'd. A worker's call, one at a
    time (the service's refresh). A sync is counted down only while something will send it (`replan_host.sync_sent`:
    Connect on, or the re-order host of a language whose gate holds); else the mark says what it would without it —
    never *syncing in 0 s* for an hour. `provider.every()`: 1 s while it counts down, else Connect's 3 s."""
    last = {"stamp": object(), "state": None, "due": True}      # never a stamp: the first look reads

    def provider():
        from app import anki_sync_rule
        stamp = _stamp(anki_sync_rule._path())
        if stamp is None or stamp != last["stamp"]:
            last["state"] = anki_sync_rule.read_state()
            last["stamp"] = stamp
        values, state = settings() or {}, last["state"] or {}
        if state.get("front_pending"):
            from app.services import replan_host
            if not replan_host.sync_sent(values):
                state = dict(state, front_pending=False)        # nothing will send it: no countdown
        last["due"] = anki_sync_rule.due_at(values, state) is not None
        return anki_sync_rule.status(values, now=None if now is None else now(), state=state) or None
    provider.every = lambda: TICKS["ankiweb"] if last["due"] else TICKS["connect"]
    return provider


def anki_backlog(language):
    """*Anki · N waiting* (W31A-2) -> a provider: the new cards waiting in Anki — the Anki sync's saved backlog
    (`User Files/<lang>/anki_backlog.json`), its notes counted as `anki_sync.count_backlog` counts them — never a call
    to Anki. None while no backlog file exists (someone who never synced sees *Anki*, never *0 waiting*), and for one
    that can't be read or holds no notes table (not a count: *Anki*, not a false 0); a read file with no notes is 0.
    Ticking every 3 s, it stats the file and reads it again only when its stamp (mtime, size) moved: the count is
    kept. A read that fails (the file held a moment by a scanner, just after the sync replaced it) keeps the last count
    and is tried again at the next tick (AD-8). A worker's call, one at a time (the service's refresh)."""
    last = {"stamp": None, "n": None}

    def provider():
        from app import anki_sync
        stamp = _stamp(anki_sync._backlog_path(language))
        if stamp is None:
            last["stamp"] = last["n"] = None            # gone (or never written): *Anki*
            return None
        if stamp != last["stamp"]:
            data = anki_sync.load_backlog(language)
            if not data:                                # couldn't be read (`load_backlog`'s {}): asked again next tick
                return last["n"]
            notes = data.get("notes")
            last["n"] = len(notes) if isinstance(notes, dict) else None
            last["stamp"] = stamp
        return last["n"]
    provider.every = lambda: TICKS["backlog"]
    return provider


def _stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None                                     # none yet (or unreadable): read, as before
    return st.st_mtime_ns, st.st_size


def journey_pending(language):
    """The journey dot (G10) -> a provider: the store's `journey_pending()` for `language` (the sentences owed a
    Generate), through a handle opened and closed on the worker (never kept: it would hold Repair's rename back); None
    while no store is ready."""
    def provider():
        from app import library_store
        from app.path_utils import get_data_path, get_user_files_path
        store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                         role="window", busy_wait=0.0)
        if store is None:
            return None
        with store:
            return bool(store.journey_pending())
    return provider
