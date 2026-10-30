"""The re-order host and the journey keeper in 3.0's window (W3.5 row 7, R7a; the map's §3 "smallest fix"): the Tk
dashboard's preview switch (`app/main.py` `_replan_start` … `_replan_finishing`) moved out of the window, Qt-free.

- **`ReplanHost`** wraps `replan_preview.open_host` (the helper process; `Host` in this process under
  `SURASURA_REPLAN_IN_PROCESS=1`). Its calls — `poke`, `catch_up`, `after_generate` — only queue: on its own worker it
  reads the settings now and asks `replan_preview.automation_on(settings, language)` every time (D29, Junban, one deck,
  the (language, deck) pair recorded: Haya's G2 / G3; never cached), opens the host lazily when it says yes, and lets an
  open host go when it says no. The host's Generate ask goes to the keeper (`generate`: one automatic Generate path);
  its writes are a `replan` job in the window's registry (`working(True/False)`: recorded — the registry sees the write
  and waits for it at quit, `on_quit="wait"`, and never holds the host's own machine-locked write back); its last line
  is `line()` (None before any, and once the host is let go), each new one told through `on_line`. While it stands
  aside for a reason the user can fix — D7's one deck, the (language, deck) pair not recorded — `line()` is
  `stands_aside`'s line, worked out beside the gate and told only when it changes; D29 off, Junban off or
  absent are the user's choices: no line. `hold()` (an update waits: its helper is a Surasura process the update would
  wait for) lets the host go until `release()`; nothing opens while an update holds its lock (the helper would see it
  and leave the jobs to the window's process): the next call opens it. `close()` + `finish(deadline)` is the quit: a
  pending settle and the S3 sync run at once, `busy()` is waited for until the deadline, then `stop()` (the helper
  finishes a write in hand by itself); from the moment `close()` is called nothing opens a host (a catch-up queued
  before it never spawns a helper during the quit). `settling()` (no lock, any thread): a move was told less than a
  settle ago — the window's close then waits for `busy()` with the window up (E20). The settings are read from the file
  on the worker (`settings()`: the settings service's `fresh`), so 順's own deck pick is seen at the next call. With no
  host to send it — none may run in any language — and Connect off, a pending AnkiWeb sync is let go there (the Tk
  `_replan_start`'s rule: Anki's own sync on close carries the order).
- **`Replan`** is one per window: the keeper and the host of the language open, made again on a language switch (the
  old host stopped — a settle still pending is dropped, so nothing more is written to the old deck; its next start
  catches up through the store's versions — and the old keeper closed); the new language gets the start's catch-up
  and journey look — and so does a focus (`activated`: another program may have placed an item while no reader
  watched). The keeper (`journey.JourneyKeeper`) is always made, D29 off too: its `on_done`
  re-baselines New arrivals' worker after a manual Generate (Haya G2c). `on_done` is the only re-order after a Generate
  (`after_generate`: the keeper hands each new plan once), never the controller's end. A store change (`store_moved`,
  from the library reader: any writer) → one poke + one `changed("store")`. A stone that moved nothing that counts
  (`stone_marked`, JS-1) → `marked("stone")`: never a poke, never a withdrawn run (the keeper looks once after the run
  in flight). The host's own Generate asks and the
  journey look (the store's `journey_pending()` or the report not current: `journey_pending`) go to the keeper only
  while no Generate runs or waits (`_asker`): a move withdraws the keeper's run in flight, and the run going already
  serves the ask (its `on_done` re-orders after it).

Nothing here waits on the caller's thread but `finish` (the quit's worker): the rest queues on the host's worker, arms
the keeper's timer, or lets a host go (`stop` never waits).
"""
import threading
import time

from app.services.automation import Worker

LABEL = "Re-ordering Anki's new cards"     # the `replan` job's words (the bar, the update's list: `updater.REPLAN_ROW`)
HOLDING = ("downloading", "waiting", "ready")  # the update service's states while it holds the children
BUSY_LOOK = 0.05                           # at quit, how often the host is asked whether it still works


def journey_pending(language):
    """The start's and a focus's look: the store's `journey_pending()` (the order moved since the last Generate), or the
    report isn't current (`analyzer.report_is_current`, the keeper's own report half: a stone with *Keep studying* on
    moves no `order_version`, so one marked just before a quit, or before the window's services were made, still shows
    at the next start, JSW-A2) — False with no store. A worker's (the report half reads the settings and the marks)."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    store = library_store.open_store(language, get_data_path(language), get_user_files_path(language), role="window",
                                     busy_wait=0.0)
    if store is None:
        return False
    with store:
        if store.journey_pending():
            return True
    from app import analyzer, run_args, settings_manager
    args = run_args.analyzer_args(settings_manager.load_settings(strict=True), language)
    return not analyzer.report_is_current(args, language)


def _automation_on(settings, language):
    try:
        from app import replan_preview
        return bool(replan_preview.automation_on(settings, language))
    except Exception as e:                  # an answer that can't be had is no: never a write on a guess
        print(f"Re-order: its switch couldn't be read: {e}")
        return False


def _aside_line(settings, language):
    """Why the host stands aside, for the bar: `stands_aside`'s line where the user can fix it — D7's one
    deck, the (language, deck) pair not recorded — else None: D29 off, Junban off or absent are the user's own choices.
    Asked on the host's worker, beside the gate."""
    try:
        from app import replan_preview
        why = replan_preview.stands_aside(settings, language)
        return None if why is None else (replan_preview.ends_with(why) or None)   # (a line that gives up: the bar's)
    except Exception as e:
        print(f"Re-order: why it stands aside couldn't be read: {e}")
        return None


def sync_sent(settings):
    """Whether anything will send a pending AnkiWeb sync (S3): Connect while it is on, else the re-order host of a
    language whose gate holds (only a host sends it, `Host._sync_step`; another window's may be another language's).
    A worker's call."""
    if (settings or {}).get("connect_enabled"):
        return True
    from app import replan_preview
    return any(_automation_on(settings, language) for language in replan_preview.LANGUAGE_NAMES)


def replan_preview_off():
    from app import replan_preview
    return replan_preview.OFF


def _drop_pending():
    try:
        from app import anki_sync_rule
        anki_sync_rule.drop_pending()
    except Exception as e:
        print(f"Re-order: the pending AnkiWeb sync couldn't be let go: {e}")


def _update_staged():
    from app import replan_preview
    return replan_preview._update_staged()


class ReplanHost:
    """One per window and language. `registry`: the window's job registry; `settings()`: the settings now (a dict);
    `generate(reason)`: the host asks for an automatic Generate; `on_line(line)`: its newest line (or None); `opener`:
    `open_host`'s shape (a test's stand-in); `held`: made while an update holds the children."""

    def __init__(self, registry, settings, language, generate=None, on_line=None, opener=None, held=False):
        self.registry = registry
        self._settings = settings
        self.language = language
        self._generate = generate
        self._on_line = on_line
        self._opener = opener
        self._lock = threading.Lock()
        self._host = None
        self._gen = 0                       # which host the callbacks are from: a host let go is never heard again
        self._job = None                    # the `replan` job of the write in hand
        self._line = None
        self._aside = None                  # the stand-aside line `line()` gives while no host is open
        self._off = False                   # finish-pending: `OFF` told since the gate last said yes (told once)
        self._held = bool(held)
        self._closing = False               # the quit: the host's close is sent (once)
        self._quitting = False              # the quit was asked (`close()`, at the call): nothing opens from here
        self._closed = False
        self._settle_until = 0.0            # monotonic: a move told until then may still be settling (`settling`)
        self.worker = Worker("replan-host")
        self.opened = 0                     # hosts opened (tests)

    # --- the window's calls (any thread; each returns at once) ----------------------------------------------------- #
    def poke(self):
        from app import replan_preview
        self._settle_until = time.monotonic() + replan_preview.SETTLE_S     # a plain float: read with no lock
        self.worker.put(self._forward, "poke")

    def catch_up(self):
        self.worker.put(self._forward, "catch_up")

    def after_generate(self):
        self.worker.put(self._forward, "after_generate")

    def started(self, changed, pending=None):
        """The window's start: the catch-up, then `changed("start")` when the store says the journey is pending (the
        order moved since the last Generate; read on the worker)."""
        self.catch_up()
        self.worker.put(self._journey, changed, pending or journey_pending)

    def line(self):
        return self._line

    def settling(self):
        """A move was told less than a settle ago: its re-order may still be pending. No lock, no wait (the window's
        close asks it on its own thread)."""
        return time.monotonic() < self._settle_until

    def busy(self):
        with self._lock:
            host = self._host
        return host is not None and bool(host.busy())

    def hold(self):
        """An update holds the children (*Update now*): the host goes (a write in hand finishes in its helper), nothing
        opens until `release`."""
        with self._lock:
            self._held = True
        self._let_go()

    def release(self):
        """The update's hold ended (cancelled, failed): a catch-up, which opens the host again."""
        with self._lock:
            if self._closed or not self._held:
                return
            self._held = False
        self.catch_up()

    def close(self):
        """The quit begins: after what is queued, the host's own close (a pending settle and the S3 sync run at once);
        nothing opens from here on — refused from this call, so a catch-up queued before it opens nothing."""
        with self._lock:
            self._quitting = True
        self.worker.put(self._close_host)

    def finish(self, deadline):
        """(The quit's worker.) After `close`: the host waited for while `busy()`, until `deadline` (monotonic), then
        `stop()`. -> True when it ended before the deadline."""
        self.close()
        self.worker.idle(max(0.0, deadline - time.monotonic()))
        while self.busy() and time.monotonic() < deadline:
            time.sleep(BUSY_LOOK)
        done = not self.busy()
        self.stop()
        return done

    def stop(self):
        """Gone (a language switch, the quit): the host let go — never waits — and nothing more from here."""
        with self._lock:
            self._closed = True
        self._let_go()
        self.worker.close()

    # --- the worker ---------------------------------------------------------------------------------------------- #
    def _forward(self, call):
        with self._lock:
            if self._closed or self._closing or self._held:
                return
            host = self._host
            if host is None and self._quitting:
                return                      # the quit was asked: no helper is spawned now
        settings = self._settings()
        if not _automation_on(settings, self.language):
            # switched off (D29, Junban, the deck): the helper goes; the bar says why where the user can fix it —
            # the user's own choices with no line, told once as `OFF` (finish-pending: a press waiting ends quietly)
            self._let_go(_aside_line(settings, self.language), off=True)
            if not sync_sent(settings):
                _drop_pending()             # nothing will send a pending AnkiWeb sync (the Tk `_replan_start`)
            return
        self._unsay_aside()
        if host is None:
            if _update_staged():
                return                      # an update holds its lock: the next call opens the host
            host = self._open()
            if host is None:
                return
        getattr(host, call)()

    def _open(self):
        opener = self._opener
        if opener is None:
            from app import replan_preview
            opener = replan_preview.open_host
        with self._lock:
            gen = self._gen + 1
        host = opener(self.language, say=lambda line: self._said(gen, line),
                      working=lambda on: self._working(gen, on),
                      generate=(lambda reason: self._asked(gen, reason)) if self._generate is not None else None)
        with self._lock:
            late = self._closed or self._closing or self._quitting or self._held or self._gen + 1 != gen
            if not late:
                self._gen, self._host = gen, host
                self.opened += 1
        if late:
            host.stop()
            return None
        return host

    def _journey(self, changed, pending):
        with self._lock:
            if self._closed or self._closing:
                return
        try:
            if pending(self.language):
                changed("start")
        except Exception as e:
            print(f"Journey: the store couldn't be read at start: {e}")

    def _close_host(self):
        with self._lock:
            if self._closing:
                return                      # once: a second close would ask the S3 sync again
            self._closing = True
            host = self._host
        if host is not None:
            host.close()

    def _let_go(self, aside=None, off=False):
        """The host goes (if open); `line()` is `aside` from here (None: no line), told only when it changed (S19).
        `off` (the gate said no): with no line, `replan_preview.OFF` is told instead, once until the gate says yes."""
        with self._lock:
            host, self._host = self._host, None
            job, self._job = self._job, None
            self._gen += 1
            told = aside if self._line != aside else False
            if off and aside is None and not self._off:
                told = replan_preview_off()
            self._off = off and aside is None
            self._line = self._aside = aside
        if host is not None:
            try:
                host.stop()
            except Exception as e:
                print(f"Re-order: its host couldn't be stopped: {e}")
        if job is not None and job is not True:
            job.finish(ok=True)             # the helper's own row stands for a write it still finishes (the update)
        if told is not False:
            self._tell(told)

    def _unsay_aside(self):
        """The host may run again: the stand-aside line goes (its own lines follow)."""
        with self._lock:
            self._off = False
            aside, self._aside = self._aside, None
            said = aside is not None and self._line == aside
            if said:
                self._line = None
        if said:
            self._tell(None)

    # --- the host's callbacks (its worker, or the pipe's reader) --------------------------------------------------- #
    def _said(self, gen, line):
        with self._lock:
            if gen != self._gen:
                return
            self._line = line or None
        self._tell(line or None)

    def _tell(self, line):
        if self._on_line is not None:
            try:
                self._on_line(line)
            except Exception as e:
                print(f"Re-order: a listener failed: {e}")

    def _working(self, gen, on):
        """The host writes to Anki (True) or ended its write (False): one `replan` job for it, recorded outside the
        lock (the registry tells its listeners from inside `record`); `True` holds its place meanwhile."""
        with self._lock:
            if gen != self._gen:
                return
            if on:
                if self._job is not None:
                    return
                self._job = True
            else:
                ended, self._job = self._job, None
        if not on:
            if ended is not None and ended is not True:
                ended.finish(ok=True)
            return
        job = self.registry.record("replan", LABEL, automatic=True, on_quit="wait")
        with self._lock:
            mine = self._job is True and gen == self._gen
            if mine:
                self._job = job
        if not mine:
            job.finish(ok=True)             # it ended (or its host went) while it was being recorded

    def _asked(self, gen, reason):
        with self._lock:
            if gen != self._gen:
                return
        self._generate(reason)


class Replan:
    """One per window: the keeper and the host of the language open. `registry`, `controller`: the window's;
    `settings`: the settings service (`get`, `automation`); `opener`: `open_host`'s shape; `keeper_options`: the keeper's
    stand-ins (a test's: `launcher`, `pending`, `battery`, `plan_path`); `pending(language)`: the start's journey look
    (default `journey_pending`). `arrivals`: New arrivals' worker when the window holds one (W3.2), re-baselined after a
    Generate of its language. `on_line(line)`: the host's newest line."""

    def __init__(self, registry, controller, settings, language, opener=None, keeper_options=None, pending=None,
                 on_line=None):
        self.registry = registry
        self.controller = controller
        self._settings = settings
        self._opener = opener
        self._keeper_options = dict(keeper_options or {})
        self._pending = pending
        self._on_line = on_line
        self.arrivals = None
        self.held = None                # the window's: `held()` True while the setup wizard is up (the keeper waits)
        self._lock = threading.Lock()
        self._held = False
        self._closing = False
        self.language = language or "ja"
        self.keeper, self.host = self._make(self.language)

    # --- the window's calls (each returns at once) ------------------------------------------------------------------ #
    def start(self):
        keeper, host = self._pair()
        host.started(self._asker(keeper), self._pending)

    def activated(self):
        """A focus: the catch-up and the start's journey look (another program may have placed an item while no
        library reader watched: the store says the journey is pending)."""
        keeper, host = self._pair()
        host.started(self._asker(keeper), self._pending)

    def store_moved(self, language, _versions=None):
        """The library reader saw the order or the pins move (any writer): one poke, one `changed`."""
        with self._lock:
            if self._closing or language != self.language:
                return
            keeper, host = self.keeper, self.host
        host.poke()
        keeper.changed("store")

    def stone_marked(self, language):
        """A watched mark, or its undo, that moved nothing that counts (Keep studying on, JS-1): the report still shows
        the stone, so the keeper looks again (`marked("stone")`: its check asks the report half too, and a Generate in
        flight is never withdrawn for it — the look waits for it to end). No poke: the order and the pins stand, so the
        re-order host has nothing new."""
        with self._lock:
            if self._closing or language != self.language:
                return
            keeper = self.keeper
        keeper.marked("stone")

    def language_changed(self, language):
        language = language or "ja"
        with self._lock:
            if self._closing or language == self.language:
                return
            old = (self.keeper, self.host)
            self.language = language
        old[0].close()
        old[1].stop()
        keeper, host = self._make(language)
        with self._lock:
            stale = self._closing or self.language != language
            if not stale:
                self.keeper, self.host = keeper, host
        if stale:
            keeper.close()
            host.stop()
            return
        host.started(self._asker(keeper), self._pending)    # the start's catch-up and journey look, whatever
                                                        # the new host's gate says: D29 decides through the keeper

    def level_changed(self):
        """A level key written (Settings, the wizard; W3.3's S3): the keeper's quiet time starts again."""
        keeper, _host = self._pair()
        keeper.changed("level")

    def report_changed(self):
        """A setting only the report reads written (Settings' Journey rows: the theme, a switch; a6 #5): the keeper
        looks as for a stone (`marked`: a Generate in flight is never withdrawn), so its quiet run re-renders the
        journey and re-analyses nothing — unless a Generate was already due (an analysis setting changed and not yet
        generated): then that whole run comes now, as it would at the next focus. No poke: the order and the pins
        stand."""
        keeper, _host = self._pair()
        keeper.marked("settings")

    def update_state(self, state):
        """The update service's state: while it holds the children the host is let go; when the hold ends, back."""
        holding = state in HOLDING
        with self._lock:
            if holding == self._held:
                return
            self._held = holding
            host = self.host
        if holding:
            host.hold()
        elif not self._closing:
            host.release()

    def line(self):
        return self._pair()[1].line()

    def settling(self):
        """A move's settle may still be pending (no lock: the window's close asks on its own thread)."""
        return self.host.settling()

    def busy(self):
        """The host works or has work pending (a worker's look: the window's close waits on it, E20)."""
        return self._pair()[1].busy()

    def closing(self):
        """The quit begins: the keeper closed (nothing asked from here), the host's close sent. Returns at once."""
        with self._lock:
            if self._closing:
                return
            self._closing = True
            keeper, host = self.keeper, self.host
        keeper.close()
        host.close()

    def finish(self, deadline):
        """(The quit's worker.) The host's write in hand and its pending work waited for until `deadline`, then it
        goes. -> True when it ended in time."""
        self.closing()
        return self._pair()[1].finish(deadline)

    # --- inside ------------------------------------------------------------------------------------------------------ #
    def _pair(self):
        with self._lock:
            return self.keeper, self.host

    def _settings_now(self):
        from app.services.settings import thaw
        return thaw(self._settings.get())

    def _settings_fresh(self):
        """The host's gate reads the file now (the settings service's `fresh`, on the host's worker): 順 records its
        deck with its own save, behind the window's copy. A stand-in without `fresh`: its `get`."""
        fresh = getattr(self._settings, "fresh", None)
        return fresh() if fresh is not None else self._settings_now()

    def _asker(self, keeper):
        """`keeper.changed` for the host's Generate asks and the journey look. A Generate running or waiting is never
        withdrawn for it (a7): the keeper looks once after it ends, whose check asks nothing when that run read it all —
        a language switch's start look included, while the old language's run is being stopped."""
        def ask(reason):
            keeper.changed(reason)
        return ask

    def _automation(self):
        held = self.held
        if held is not None and held():
            return False                # the setup wizard is up: its close asks again (`Services.setup_ended`)
        automation = getattr(self._settings, "automation", None)
        if automation is not None:
            return bool(automation())
        from app import settings_manager
        return bool(settings_manager.automation(self._settings.get()))

    def _make(self, language):
        from app.services import journey as journey_module
        keepers = []

        def generate(reason):
            for keeper in keepers:
                self._asker(keeper)("replan: " + reason)
        host = ReplanHost(self.registry, self._settings_fresh, language, generate=generate, on_line=self._on_line,
                          opener=self._opener, held=self._held)

        def on_done(_plan_path):
            host.after_generate()           # the only re-order after a Generate: once per new plan (the keeper's rule)
            arrivals = self.arrivals
            if arrivals is not None and getattr(arrivals, "language", language) == language:
                try:
                    arrivals.reload()
                except Exception as e:
                    print(f"New arrivals: couldn't re-read the plan: {e}")
        controller = self.controller
        labelled = getattr(controller, "labelled", None)
        if labelled is not None:                # its run reads *Journey: updating sentences…* in the bar (G7)
            from app.services import generate as generate_module
            controller = labelled(generate_module.JOURNEY_LABEL)
        keeper = journey_module.JourneyKeeper(controller, language, settings=self._settings_now,
                                              enabled=self._automation, on_done=on_done, **self._keeper_options)
        keepers.append(keeper)
        return keeper, host
