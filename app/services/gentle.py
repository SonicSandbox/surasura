"""Gentle on the machine (Haya-LD, 3.0.18; Sonic 2026-11-20: "anki on my laptop can get really slow when everything is
running … new arrivals is probably something that could wait" · "yes go to more gently … is there a way to tell which
machines need more gently vs not?"). Qt-free. One per window (`Gentle`), the one scheduler the window's background work
asks for a turn — never one per feature.

**Booted first, on every PC** (Sonic, 2026-11-20: "I would like it to first boot up / launch before doing the rest.
that would be consistent across the board"): the window is *booted* when Current's list, filled from what is on disk
(the library reader's first view that isn't the cached first screen), has been drawn and the window's event loop has
gone idle once after it (`ShellWindow._boot_after_idle`: the dispatcher's `aboutToBlock`) — or BOOT_MAX_S after its
first frame, whichever comes first. Until then nothing in the background starts: the window holds `Services.start`
itself (the Anki look and Connect's kick, the known-words sync, the journey's Generate, the update check, the chores:
the indexer, the store's helper, Koe; 順's catch-up) and this scheduler holds every automatic job and step
(WINDOW_FIRST: an automatic Generate, New arrivals, covers…), from the moment the window's services are made
(`shell.open_services`). `ready()` is the window's word that it booted. The adaptive part below applies only after.

**The order.** The window first → Generate (only when it's needed) → Connect's mining → the rest last, and only while
the machine is quiet. *The rest* (`BACKGROUND`) is New arrivals' estimates, the indexer's catch-up, 順's re-order
catch-up (and the one after a Generate), covers from online, the library store's helper (`library-maintain`: the
window's start and focus checks; one at a time in every program, `library_store.spawn_maintain`). A press always goes first: every rule here is asked of
automatic work only (the registry's `gate(…, automatic=True)`; a re-order a move asked for — `poke` — is never held),
and nothing already running is stopped: a held kind waits **between its steps** (a job's start, the next estimate the
arrivals worker is sent, the next round of covers, the next re-order catch-up).

**Which machines** (`power.gentle`: logical CPUs, total memory, on battery — measured at the start, the battery read
again every BATTERY_EVERY_S): on a **gentle** PC (a laptop, a small or unplugged one) —
- every background kind waits SETTLE_S more after the boot (its first paints' follow-ups);
- and while another heavy job runs (`HEAVY`: a Generate, Connect making cards, the indexer, a re-order writing to
  Anki, the sentence dictionary) — one heavy job at a time;
- an automatic Generate waits while Connect makes cards (`mine`: one batch's
  episode) — Connect's next step in turn waits while a Generate runs (`runner.Steps.blocked`, GENERATE_FIRST), so
  the Generate goes in at Connect's next step boundary.
On **every** PC (a strong desktop runs the rest side by side as before):
- the rest waits while you review in Anki (`guiReviewActive`, asked every REVIEW_LOOK_S while background work
  waits or runs: never a request while nothing does);
- and while the system's CPU is busy (`power.CpuLoad` over LOAD_WINDOW_S at or over `power.BUSY`, until it is under
  `power.QUIET`) — a hold for load alone lasts at most HOLD_MAX_S a kind (a PC always busy still gets its estimates).

**Words** (the bar's *waiting* line, a job's `reason`; PROVISIONAL): WINDOW_FIRST, REVIEWING, BUSY_NOW, TURN. Every
change of the machine's state is logged (`write_app_log`, *gentle: …*), so a Send report says what waited and why.

`hold(kind)` (module level) is what a step outside the registry asks: None (go on) when no window's scheduler is
attached — a test, the 2.x window, a command-line run — so nothing changes there.
"""
import collections
import os
import threading
import time

from app.services import jobs as jobs_module

BACKGROUND = frozenset({"indexer", "replan", "arrivals-ja", "arrivals-zh", "covers", "library-maintain"})
HEAVY = frozenset({"generate", "mine", "indexer", "replan", "sentence-corpus", "library-maintain"})
GENERATE = "generate"
MINE = jobs_module.CONNECT_KIND

TICK_S = 1.0                    # the watcher's look: the CPU sampled, the holds asked again
LOAD_WINDOW_S = 5.0             # the CPU's busy share is the mean of this many seconds' samples
REVIEW_LOOK_S = 10.0            # `guiReviewActive` asked at most this often, only while background work wants a turn
BATTERY_EVERY_S = 30.0          # plugged in or not, read again (a laptop unplugged becomes gentle)
SETTLE_S = 3.0                  # on a gentle PC, after the boot the rest waits this much more (its first paints)
START_HOLD_MAX_S = 60.0         # the boot never told (a window that never drew its list): the rest goes this long after
#                                 the services were made all the same (the window's own limit, BOOT_MAX_S, comes first)
HOLD_MAX_S = 300.0              # a kind held for load alone goes after this long (still below normal priority)
WANTED_FOR_S = 30.0             # a `hold` asked within this long counts as background work wanting a turn
STEP_LOOK_S = 1.0               # how often a step held outside the registry asks again (`wait_turn`)

WINDOW_FIRST = "Waits for the window to finish opening"
BOOT_MAX_S = 30.0               # the window's limit after its first frame: booted all the same (`ShellWindow`)
REVIEWING = "Waits while you review in Anki"
BUSY_NOW = "Waits for a quieter moment: this computer is busy"
TURN = "Waits its turn: {label} first"

_current = [None]               # the window's scheduler (one window a process: `single.py`)


def hold(kind):
    """Why a step of `kind` outside the registry waits now (plain words), or None — None too with no scheduler
    attached. Never raises."""
    gentle = _current[0]
    if gentle is None:
        return None
    try:
        return gentle.hold(kind)
    except Exception:
        return None


def press(kind, on):
    """A press asks for work of `kind` (Finished's *What if* through the arrivals worker): while `on`, nothing holds
    that kind — its job starts at once. Off when the press's last answer came. Nothing with no scheduler attached."""
    gentle = _current[0]
    if gentle is not None:
        gentle.pressed(kind, on)


def wait_turn(kind, stopped, sleep=None):
    """Wait while `hold(kind)` names a reason and `stopped()` says no; `sleep(s)`: the caller's own (ended at its stop),
    default `time.sleep`. -> True when it waited."""
    sleep = sleep or time.sleep
    waited = False
    while not stopped() and hold(kind):
        waited = True
        sleep(STEP_LOOK_S)
    return waited


def _log(line):
    try:
        from app.path_utils import write_app_log
        write_app_log(f"gentle: {line}")
    except Exception:
        pass


def _reviewing_now(settings):
    """Is the learner reviewing in Anki now? False when Anki doesn't answer (closed, busy) or isn't set up."""
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return False
    from app import anki_connect
    return bool(anki_connect.reviewing(anki_connect.address(settings())))


class Gentle:
    """`registry`: the window's job registry; `settings()`: the settings now (for Anki's address). Stand-ins (tests):
    `machine()` -> `power.gentle`'s (gentle, why); `load` -> a `power.CpuLoad`; `reviewing()` -> bool; `clock`
    (monotonic); `log(line)`."""

    def __init__(self, registry, settings=None, machine=None, load=None, reviewing=None, clock=None, log=None):
        from app.connect import power
        self.registry = registry
        self._settings = settings or (lambda: {})
        self._machine = machine or power.gentle
        self._load = load if load is not None else power.CpuLoad()
        self._reviewing = reviewing or (lambda: _reviewing_now(self._settings))
        self._clock = clock or time.monotonic
        self._log = log or _log
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.gentle, self.why = False, None
        self._samples = collections.deque()
        self.busy = False               # the CPU over power.BUSY (until under power.QUIET)
        self.busy_share = None
        self.reviewing = False
        self._started_at = None
        self._ready_at = None           # when the window's list was up (or START_HOLD_MAX_S passed)
        self._held_since = {}           # kind -> when load alone began holding it
        self._overdue = set()           # the kinds past HOLD_MAX_S already let go (told once)
        self._asked_at = None           # the last `hold` asked (background work wanting a turn)
        self._review_looked = float("-inf")
        self._battery_looked = float("-inf")
        self._open = None               # the last state the rules read (a change reschedules)
        self._late = False              # the boot never told by START_HOLD_MAX_S (the watcher says so once)
        self._pressing = set()          # kinds a press waits on now (`press`): never held

    # --- the window's calls ---------------------------------------------------------------------------------------- #
    def attach(self, watch=True):
        """The registry's gate, the machine read and (`watch`) the watcher's thread; this window's from here on
        (`hold`). -> self."""
        self._started_at = self._clock()
        self._read_machine(first=True)
        self.registry.gate(self.check, automatic=True)
        _current[0] = self
        if watch:
            self._thread = threading.Thread(target=self._watch, name="gentle", daemon=True)
            self._thread.start()
        return self

    def ready(self):
        """The window booted (its list from disk drawn, its loop idle once): the rest may go — on a gentle PC after
        SETTLE_S. Once."""
        with self._lock:
            if self._ready_at is not None:
                return
            self._ready_at = self._clock()
            self._asked_at = self._ready_at     # the start's background work comes now: the next look asks Anki
            began = self._started_at
        if began is not None:
            self._log(f"the window booted {self._ready_at - began:.1f} s after its services were made")
        self._reconsider()

    def pressed(self, kind, on):
        """`press`'s: `kind` let through while a press waits on it (the registry asked again at once)."""
        with self._lock:
            (self._pressing.add if on else self._pressing.discard)(kind)
        if on:
            self.registry.reschedule()

    def close(self):
        self._stop.set()
        if _current[0] is self:
            _current[0] = None

    # --- the rules ---------------------------------------------------------------------------------------------- #
    def check(self, kind):
        """The registry's gate for automatic jobs (under its lock: flags and the live jobs read, nothing slower)."""
        return self._reason(kind, self.registry.live())

    def hold(self, kind):
        """`check` for a step outside the registry (it counts as background work wanting a turn)."""
        with self._lock:
            self._asked_at = self._clock()
        return self._reason(kind, self.registry.live())

    def _reason(self, kind, live):
        now = self._clock()
        with self._lock:
            if kind in self._pressing:
                return None                             # a press goes first
            if kind == GENERATE:
                if not self._window_up(now, settle=False):
                    return WINDOW_FIRST                 # booted first, on every PC
                return self._turn(kind, live, (MINE,)) if self.gentle else None
            if kind not in BACKGROUND:
                return None
            if not self._window_up(now, settle=False):
                return WINDOW_FIRST                     # booted first, on every PC
            if self.reviewing:
                return REVIEWING
            if self.busy:
                since = self._held_since.setdefault(kind, now)
                if now - since < HOLD_MAX_S:
                    return BUSY_NOW
            else:
                self._held_since.pop(kind, None)
            if not self.gentle:
                return None
            if not self._window_up(now, settle=True):
                return WINDOW_FIRST                     # its settle (a gentle PC's)
            return self._turn(kind, live, HEAVY)

    @staticmethod
    def _turn(kind, live, heavy):
        for job in live:
            if job.kind != kind and job.kind in heavy and job.state in (jobs_module.RUNNING, jobs_module.CANCELLING):
                return TURN.format(label=job.label)
        return None

    def _window_up(self, now, settle):
        if self._ready_at is None:
            if self._started_at is None or now - self._started_at < START_HOLD_MAX_S:
                return False
            self._ready_at = self._asked_at = now   # never told: the rest goes all the same (said by the watcher:
            self._late = True                       # never a file written under the registry's lock)
        return not settle or now - self._ready_at >= SETTLE_S

    # --- the watcher ---------------------------------------------------------------------------------------------- #
    def _watch(self):
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception as e:          # the watcher never dies of a reading
                self._log(f"a look failed: {e!r}")

    def tick(self):
        """One look (the watcher's, every TICK_S; a test calls it): the CPU sampled, the battery and your review asked
        when due, and the registry rescheduled when the rest may go now where it couldn't."""
        now = self._clock()
        share = self._load.sample()
        with self._lock:
            if share is not None:
                self._samples.append((now, share))
            while self._samples and now - self._samples[0][0] > LOAD_WINDOW_S:
                self._samples.popleft()
            mean = (sum(s for _t, s in self._samples) / len(self._samples)) if self._samples else None
            self.busy_share = mean
        if mean is not None:
            from app.connect import power
            busy = mean >= power.BUSY or (self.busy and mean >= power.QUIET)
            if busy != self.busy:
                self.busy = busy
                if not busy:
                    with self._lock:
                        self._held_since.clear()        # the next busy spell holds from its own start
                self._log(f"this computer is busy ({mean:.0%} CPU): background work waits" if busy
                          else f"quiet again ({mean:.0%} CPU)")
        if self._late:
            self._late = False
            self._log(f"the window's boot wasn't told in {START_HOLD_MAX_S:.0f} s: background work goes on")
        if now - self._battery_looked >= BATTERY_EVERY_S:
            self._read_machine()
        if self._wanted(now) and now - self._review_looked >= REVIEW_LOOK_S:
            self._review_looked = now
            try:
                reviewing = bool(self._reviewing())
            except Exception:
                reviewing = False
            if reviewing != self.reviewing:
                self.reviewing = reviewing
                self._log("you're reviewing in Anki: background work waits" if reviewing else "your review ended")
        elif not self._wanted(now) and self.reviewing:
            self.reviewing = False          # nothing waits: no request, and no stale hold for the next one
        self._reconsider()

    def _wanted(self, now):
        """Is background work waiting or running — a live automatic job of a background kind, or a `hold` lately?
        Never before the boot (no request to Anki while the window opens: everything waits for the boot anyway)."""
        if self._ready_at is None:
            return False
        if self._asked_at is not None and now - self._asked_at < WANTED_FOR_S:
            return True
        return any(j.kind in BACKGROUND and j.automatic for j in self.registry.live())

    def _read_machine(self, first=False):
        self._battery_looked = self._clock()
        try:
            gentle, why = self._machine()
        except Exception:
            gentle, why = False, None
        if first or gentle != self.gentle:
            self.gentle, self.why = gentle, why
            self._log(f"this computer runs its background work one job at a time ({why})" if gentle
                      else "this computer runs its background work side by side")

    def _reconsider(self):
        """The scheduler's state now against the last: any change (the window up, a review, the load, the machine) →
        the registry asked again — what may go starts, and what still waits shows its reason now, never an old one."""
        now = self._clock()
        with self._lock:
            state = (self.reviewing, self.busy, self.gentle, self._window_up(now, settle=False),
                     not self.gentle or self._window_up(now, settle=True))
            changed, self._open = state != self._open, state
            # a kind held for load alone past HOLD_MAX_S goes now (told once, until the CPU is quiet again)
            overdue = [k for k, since in self._held_since.items()
                       if now - since >= HOLD_MAX_S and k not in self._overdue]
            self._overdue.update(overdue)
            if not self.busy:
                self._overdue.clear()
        if overdue and not self.reviewing:
            self._log(f"held {HOLD_MAX_S:.0f} s by a busy computer, goes on: {', '.join(sorted(overdue))}")
        if changed or (overdue and not self.reviewing):
            self.registry.reschedule()
