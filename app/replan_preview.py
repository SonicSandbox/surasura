"""The fast re-plan's preview (E1.1 04, RP-7; 2.6, opt-in): a move in the Content Manager re-orders Anki's new cards
about a second later — tomorrow's cards first, then the rest — without a full Generate.

    replan_preview.is_on(settings, language)    # 順's option "Re-order Anki as I move content (preview)", for the
                                                # language it was switched on in, Junban on and present
    replan_preview.unavailable(settings)        # why the option can't be used now (D7), or None
    host = replan_preview.Host(language, say=…, working=…, generate=…)   # one per window process
    host.poke()                                 # a store change: the 0.8 s settle restarts; one job when it ends
    host.catch_up()                             # the dashboard's start / focus, the CM's open: the job, only if owed
    host.after_generate()                       # a full Generate finished: the re-order from its plan, shadow mode
    host.close()                                # the window closes: a pending settle and a pending sync run at once

**The job** (04 §2.3), on the host's one worker, never two at once (a poke during a job queues one more): the store's
versions and order (one read), the guards (Junban's window, an update, Anki closed, a review), the plan file checked
against the library as it stands (`plan_engine.check`, the signature's parts read here), `Engine.replan`, Junban's
spaced delta with the engine's rows (`reposition.run(job=spaced.Job(automatic=True, …))`, under the Anki-write lock,
positions only, one deck), then `record_planned` with the versions read with the order. When the plan can't serve the
move the line says so, and the dashboard's host asks its window for an automatic Generate (04 §3–4; `generate`).

**Off** (the default), another language, or Junban removed: `is_on` is False, no window makes a host, and nothing
here imports Junban, the engine or the analyzer — 2.5, byte for byte (rule 1).

Light by rule: no Tk. `say(line)`, `working(bool)` and `generate(reason)` are the window's, called from the worker:
each must only post to that window's own queue. Everything heavy (the store, the engine, the analyzer's signature,
Junban) is imported on the worker; the AnkiWeb indicator's words are worked out there too (`web`).
"""

import importlib.util
import os
import threading
import time

SWITCH = "junban_replan_preview"
LANGUAGE = "junban_replan_language"     # the language 順's switch was turned on in (its deck's): "" reads as "ja"
SETTLE_S = 0.8                  # 04 §2.2: the moves' settle
RETRY_S = 20.0                  # Anki in a review, 順's window open, cards left by the re-check: look again
DONE_S = 5.0                    # "tomorrow's cards placed" gives way to "up to date" after this
CHECK_ANKI_S = 60.0             # the catch-up's look for new cards in Anki, at most this often
CLOSE_WAIT_S = 15.0             # "finishing…" waits at most this long (inside an update's 20 s grace: updater.STOP_GRACE)
SHADOW_LOG = "replan_shadow.log"
VERB = "re-ordering as you move"    # the Anki-write lock's holder line ("… is writing to Anki")
TIERS = ("now", "soon", "goal")
KINDS = ("warm", "generate", "move", "catch-up")

# The bar's lines (04 §2.4, §4).
CLOSED = "Anki is closed — your new order goes to Anki the next time Surasura sees it open"
REVIEWING = "Anki is in a review — re-ordering after it"
BUSY = "順 is busy — re-ordering when it's done"
UPDATE = "An update is waiting — re-ordering after it"
UP_TO_DATE = "Anki's order is up to date"
NEW_CONTENT = "New content: Generate puts its words in Anki's order (press it when you've placed it)"
GENERATE_FIRST = "New content or settings: Generate runs first, then Anki is re-ordered"
GENERATE_FIRST_CM = "New content or settings: Generate runs first (when you close the Content Manager), then Anki is re-ordered"
REPLAN_THEN_GENERATE = "Anki re-ordered · refreshing your list (Generate)…"
REPLAN_THEN_GENERATE_CM = "Anki re-ordered · your list refreshes (Generate) when you close the Content Manager"
STAND_ASIDE = {
    "shared-phrase": "This list holds a row two set phrases share — Generate re-orders Anki this time",
    "weights": "Your tier weights aren't whole numbers — Generate re-orders Anki",
}


def junban_present():
    """Is Junban installed? Asked without importing it (core never imports `modules/` at load: Backlog spec I2)."""
    try:
        return importlib.util.find_spec("modules.junban") is not None
    except (ImportError, ValueError):
        return False


def preview_language(settings):
    """The language the preview runs for: the one 順's switch was turned on in (its deck's), "ja" when unsaid."""
    return str((settings or {}).get(LANGUAGE) or "ja").strip().lower() or "ja"


def is_on(settings, language=None):
    """The preview's switch: on, Junban switched on and present — and, given a `language`, that language's (a
    Chinese Generate never re-orders the Japanese deck: `junban_deck` is one key for both). Everything the preview
    does asks this first."""
    settings = settings or {}
    if settings.get(SWITCH) is not True or settings.get("enable_junban") is not True:
        return False
    if language is not None and preview_language(settings) != str(language).strip().lower():
        return False
    return junban_present()


def unavailable(settings):
    """Why the preview can't run with these settings (D7; 01 §7), or None: one deck (never All decks), not
    Coverage selection, not "Only i+1" — there the list's words themselves depend on the order."""
    settings = settings or {}
    scope = str(settings.get("junban_scope") or "deck").strip().lower()
    if scope != "deck" or not str(settings.get("junban_deck") or "").strip():
        return "It needs one deck: choose it in 順's deck list (never All decks)."
    if settings.get("strategy") == "coverage":
        return "Not with Coverage selection: there the list's words depend on the order, so only Generate can tell."
    if settings.get("only_i_plus_one"):
        return "Not with 'Only i+1': there the list's words depend on the order, so only Generate can tell."
    return None


def plan_path():
    from app import analyzer
    from app.path_utils import get_user_file
    return os.path.join(get_user_file("results"), analyzer.PLAN_FILE)


def places(plan, ids, result):
    """RP-10: {the plan's file number (1-based, the run's order): its number in `result`'s order} — what
    `library_frequency.json` and the phrase places still carry, read through the new order. A file the order left
    (it left the counted tiers) goes after every other."""
    after = len(result.sequence) + 1
    return {number: result.sequence.get(item_id, after) if item_id is not None else after
            for number, item_id in enumerate(ids, 1)}


def _snapshot(store):
    """The store's versions and its analysed tiers' order, read in one transaction: {path_key: (rank, place, tier)},
    rank the tier's place in NOW, Soon, 6+ Months — sorting the values gives the study order."""
    from app import library_store
    schedule, versions = store.schedule(with_versions=True)
    order = {}
    for rank, tier in enumerate(TIERS):
        phase = library_store.TIERS[tier][0]
        for place, entry in enumerate(schedule.get(phase) or []):
            order[library_store.path_key(entry["physical_path"])] = (rank, place, tier)
    return versions, order


class Host:
    """The preview in one window's process (the Content Manager's, the dashboard's): one worker, one engine, one
    warm card map, one bar line. See the module docstring."""

    def __init__(self, language, say=None, working=None, generate=None):
        self.language = language
        self._say = say or (lambda line: None)
        self._working = working or (lambda on: None)
        self._generate = generate                 # the dashboard's: start an automatic Generate (it applies its rules)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel = threading.Event()          # a lock wait ends when the window closes
        self._lock = threading.Lock()
        self._thread = None
        self._due = None                          # monotonic: the settle's end
        self._want = set()                        # "move", "catch-up", "generate", "warm", "sync-now"
        self._retry_at = None                     # monotonic, and the kind to run again then
        self._retry_kind = None
        self._force = False                       # the next job runs owed or not (a newer order planned meanwhile)
        self._sync_at = None                      # wall time: S3's
        self._running = False
        self._closing = False
        self._anki_looked = -CHECK_ANKI_S
        self._done_at = None
        self._asked = None                        # the last automatic Generate asked for: (reason, the run stamp)
        self._seen = None                         # the catch-up's last look with nothing owed (store, plan, run)
        self._plan = self._plan_key = self._engine = self._ids = None
        self._cards = None
        self.last = ""                            # the last line said (tests; the window's line)
        self.web = ""                             # the AnkiWeb indicator's words, worked out on the worker

    # --- the window's calls (any thread; never block) --------------------------------------------------------- #

    def poke(self):
        """A store change in this window (a move, Undo, another program's change, a disk sync): the settle restarts."""
        with self._lock:
            if self._closing:
                return
            self._due = time.monotonic() + SETTLE_S
            self._want.add("move")
        self._start()

    def catch_up(self):
        self._ask("catch-up")

    def after_generate(self):
        self._ask("generate")

    def warm(self):
        """Load the plan and the engine now (the CM's open, 04 §2.1), so the first move pays nothing for them."""
        self._ask("warm")

    def _ask(self, kind):
        with self._lock:
            if self._closing:
                return
            self._want.add(kind)
        self._start()

    def busy(self):
        with self._lock:
            return self._running or bool(self._want) or self._due is not None

    def close(self):
        """The window closes (04 §2.5): a pending settle runs at once, a pending S3 sync runs at once; nothing new.
        Returns at once — the window waits on `busy()` (at most CLOSE_WAIT_S) before it goes."""
        with self._lock:
            self._closing = True
            self._retry_at = None
            self._want -= {"catch-up", "warm"}
            if self._due is not None:
                self._due = time.monotonic()
            self._want.add("sync-now")
        self._start()

    def stop(self):
        """The window is gone: the worker ends (a lock wait is let go)."""
        self._stop.set()
        self._cancel.set()
        self._wake.set()

    # --- the worker ------------------------------------------------------------------------------------------ #

    def _start(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="replan-preview", daemon=True)
                self._thread.start()
        self._wake.set()

    def _next_wait(self):
        now, wall = time.monotonic(), time.time()
        waits = [3600.0]
        with self._lock:
            if self._want - {"move"}:
                return 0.0
            if self._due is not None:
                waits.append(self._due - now)
            if self._retry_at is not None:
                waits.append(self._retry_at - now)
        if self._sync_at is not None:
            waits.append(min(1.0, self._sync_at - wall))      # the indicator's countdown, once a second
        if self._done_at is not None:
            waits.append(self._done_at - now)
        return max(0.0, min(waits))

    def _loop(self):
        while not self._stop.is_set():
            self._wake.wait(self._next_wait())
            self._wake.clear()
            if self._stop.is_set():
                break
            self.run_pending()
            with self._lock:
                if self._closing and not self._want and self._due is None:
                    self._running = False
                    break

    def run_pending(self):
        """Whatever is due now, in order — the worker's step (a test calls it directly). Each kind on its own: one
        that fails says so and never drops the others."""
        with self._lock:
            now = time.monotonic()
            if self._retry_at is not None and now >= self._retry_at:
                kind, self._retry_at = self._retry_kind or "move", None
                self._want.add(kind)
                if kind == "move":
                    self._due = now
            run = {kind for kind in ("warm", "generate", "catch-up", "sync-now") if kind in self._want}
            if "move" in self._want and self._due is not None and now >= self._due:
                run.add("move")
                self._due = None
            self._want -= run
            self._running = True
        try:
            for kind in KINDS:
                if kind in run:
                    try:
                        self._warm() if kind == "warm" else self._job(kind)
                    except Exception as e:          # a background job must never take the window down
                        self._tell(f"Re-ordering as you move stopped: {e}")
            self._sync_step(force="sync-now" in run)
            if self._done_at is not None and time.monotonic() >= self._done_at:
                self._done_at = None
                self._tell(UP_TO_DATE)
            self._refresh_web()
        finally:
            with self._lock:
                self._running = False

    # --- pieces ---------------------------------------------------------------------------------------------- #

    def _tell(self, line):
        self.last = line
        try:
            self._say(line)
        except Exception:
            pass

    def _settings(self):
        from app import settings_manager
        settings = dict(settings_manager.load_settings() or {})
        settings["target_language"] = self.language
        return settings

    def _open_store(self):
        """A store handle for this job (closed after it: a long-lived handle would hold Repair's rename back)."""
        from app import library_store
        from app.path_utils import get_data_path, get_user_files_path
        return library_store.open_store(self.language, get_data_path(self.language),
                                        get_user_files_path(self.language), role="window")

    def _load_plan(self):
        """The plan file, loaded once per version of the file -> (plan, None) or (None, why)."""
        from app import plan_engine
        path = plan_path()
        try:
            st = os.stat(path)
        except OSError:
            self._plan = self._plan_key = self._engine = self._ids = None
            return None, "no-plan"
        key = (st.st_mtime_ns, st.st_size)
        if key != self._plan_key or self._plan is None:
            try:
                plan = plan_engine.load(path)
            except plan_engine.PlanError as e:
                self._plan = self._plan_key = self._engine = self._ids = None
                return None, f"plan: {e}"
            self._plan, self._plan_key, self._engine, self._ids = plan, key, None, None
        return self._plan, None

    def _engine_for(self, store):
        from app import plan_engine
        ids = [store.item_id(entry[0]) for entry in self._plan.files]
        if self._engine is None or ids != self._ids:
            self._engine, self._ids = plan_engine.Engine(self._plan, ids), ids
        return self._engine, ids

    def _parts(self, settings, store):
        """The run signature's parts for the library as it stands (stats every file: on this worker only)."""
        from app import analyzer, run_args
        found = analyzer.resolve_found_files(self.language, verbose=False, schedule=store.schedule())
        args = analyzer.parse_analysis_args(run_args.analyzer_args(settings, self.language)[1:])
        return analyzer.run_signature_parts(self.language, found, args)

    def _verdict(self, plan, parts, store):
        from app import analyzer, plan_engine
        from app.path_utils import get_user_file
        return plan_engine.check(plan, self.language, analyzer.engine_id(),
                                 analyzer.read_run_stamp(get_user_file("results")), parts,
                                 store.versions().get("epoch"))

    def _warm(self):
        """04 §2.1: the plan and the engine (never for a plan the engine stands aside from); Junban warms on the
        first job (its tables build while Anki answers)."""
        settings = self._settings()
        if not is_on(settings, self.language) or unavailable(settings):
            return
        self._sync_at = self._due_sync(settings)
        plan, _why = self._load_plan()
        if plan is None:
            return
        from app import plan_engine
        if plan_engine.stands_aside(plan):
            return
        store = self._open_store()
        if store is None:
            return
        try:
            self._engine_for(store)
        finally:
            store.close()

    def _job(self, kind):
        """One job (04 §2.3): "move" (the CM's settle), "catch-up" (start, focus, the CM's open) or "generate"
        (after a full Generate)."""
        settings = self._settings()
        if not is_on(settings, self.language) or unavailable(settings):
            return
        self._sync_at = self._due_sync(settings)      # a write elsewhere (順's own run, a closed window) armed one
        store = self._open_store()
        if store is None:
            return                                   # no library store (JSON mode): nothing to re-plan from
        try:
            self._run_job(kind, settings, store)
        finally:
            store.close()

    def _run_job(self, kind, settings, store):
        versions, order = _snapshot(store)
        force, self._force = self._force, False
        owed = (force or versions["order_version"] > versions["planned_order_version"]
                or versions["pins_version"] > versions["planned_pins_version"])
        if kind == "move" and not owed:
            return                                   # nothing moved since the last re-order: nothing read, nothing stat'd
        if kind == "catch-up" and not owed:
            owed = self._unplaced(settings)
            if not owed and self._generate is None:
                return
        previous = self._plan
        plan, why = self._load_plan()
        if kind == "catch-up" and not owed:
            # Focus comes often: with nothing owed, the library's files are stat'd again only when the store, the plan
            # or the run moved since the last look.
            from app import analyzer
            from app.path_utils import get_user_file
            seen = (tuple(sorted(versions.items())), self._plan_key, analyzer.read_run_stamp(get_user_file("results")))
            if seen == self._seen:
                return
            self._seen = seen
        if kind == "generate":
            # After a full Generate (04 §3): shadow mode against the plan it replaced (05 §3), then the re-order from
            # its plan in the store's order now — its own order, or a move made while it ran — whatever was recorded.
            if plan is not None:
                self._shadow(previous, plan)
            owed = True
        if owed and not self._may_write(settings, kind):
            return                                   # 順's window, an update, Anki closed or a review: said, retried
        parts = self._parts(settings, store) if plan is not None else None
        verdict = self._verdict(plan, parts, store) if plan is not None else ("generate-first", why)
        if owed:
            self._replan(settings, store, versions, order, verdict, kind)
        if kind == "catch-up" and self._generate is not None:
            self._journey(plan, parts, verdict, store)

    def _may_write(self, settings, kind):
        """The guards a write needs (04 §4), asked before the library is read: 順's window open (waited for), an
        update waiting, Anki closed (the next sight of it catches up), a review (waited for)."""
        from app import anki_connect, anki_sync_rule
        from modules.junban import auto
        blocked = auto.blocked(settings)
        if blocked:
            if blocked == "the 順 window is open":
                self._tell(BUSY)
                self._retry(kind)
            elif blocked == "an update is waiting":
                self._tell(UPDATE)
            return False
        url = anki_connect.address(settings)
        if not anki_connect.probe(url, timeout=3).get("ok"):
            anki_sync_rule.closed_seen()
            self._tell(CLOSED)
            return False
        if anki_connect.reviewing(url):
            self._tell(REVIEWING)
            self._retry(kind)
            return False
        return True

    def _replan(self, settings, store, versions, order, verdict, kind="move"):
        from modules.junban import spaced
        if verdict is not None and verdict[0] in ("stand-aside", "generate-first") and kind == "generate":
            # After a Generate the list itself is current: when the engine can't replay this plan (or none was
            # written), the automatic step runs from the list, as 2.5's did (04 §1(b)).
            self._write(settings, spaced.Job(automatic=True, cards=self._card_map()), kind)
            return
        if verdict is not None and verdict[0] == "stand-aside":
            self._tell(STAND_ASIDE.get(verdict[1], "Generate re-orders Anki this time"))
            return
        if verdict is not None and verdict[0] == "generate-first":
            if self._plan is not None and not self._moved(store, order):
                # Only new (or changed) content, nothing the plan holds moved: new episodes are the user's to place
                # first (2.4's rule for the automatic Generate) — said, never run on its own.
                self._tell(NEW_CONTENT)
                return
            self._tell(GENERATE_FIRST if self._generate is not None else GENERATE_FIRST_CM)
            self._ask_generate(f"generate-first: {verdict[1]}")
            return
        engine, ids = self._engine_for(store)
        ranked = sorted((order[key] + (item_id,) for key, item_id in self._plan_keys(ids) if key in order))
        result = engine.replan([(item_id, tier) for _rank, _place, tier, item_id in ranked])
        mode = str(settings.get("junban_order") or "content").strip().lower()
        rows = result.rows(mode if mode in ("content", "priority") else "content")
        job = spaced.Job(automatic=True, rows=rows, cards=self._card_map(), places=places(self._plan, ids, result))
        report = self._write(settings, job, kind)
        if report is not None and report.get("ok") and not report.get("left") and not report.get("failures"):
            store.record_planned(versions["order_version"], versions["pins_version"])
            after = store.versions()
            if after["planned_order_version"] > versions["order_version"] or \
                    after["order_version"] > versions["order_version"]:
                # Another window planned (or the user moved) a newer order while this one was being written: this
                # write may have landed over it. One more job, owed or not.
                with self._lock:
                    self._force = True
                    if not self._closing:
                        self._want.add("move")
                        self._due = time.monotonic()
                self._wake.set()
        if verdict is not None and verdict[0] == "replan-now" and report is not None and report.get("ok"):
            self._tell(REPLAN_THEN_GENERATE if self._generate is not None else REPLAN_THEN_GENERATE_CM)
            self._done_at = None
            self._ask_generate("replan-now: " + ",".join(verdict[1]))

    def _plan_keys(self, ids):
        from app import library_store
        return [(library_store.path_key(entry[0]), item_id)
                for entry, item_id in zip(self._plan.files, ids) if item_id is not None]

    def _moved(self, store, order):
        """Did anything the plan holds move — its files' order or tiers in the store now, against the run's own?"""
        from app import library_store
        then, now = [], []
        for entry in self._plan.files:
            key = library_store.path_key(entry[0])
            then.append((key, entry[1]))
            if key in order:
                now.append(order[key] + (key,))
        now = [(key, tier) for _rank, _place, tier, key in sorted(now)]
        return now != [pair for pair in then if pair[0] in order]

    def _card_map(self):
        if self._cards is None:
            from modules.junban import reposition
            self._cards = reposition.CardMap()
        return self._cards

    def _write(self, settings, job, kind):
        """Junban's run for `job` and its bar lines -> the report, or None when nothing ran (the line said why;
        `kind` runs again later when it's worth it)."""
        from app import anki_connect
        from modules.junban import auto, reposition
        settings.update(auto._POSITIONS_ONLY)
        self._working(True)
        try:
            report = reposition.run(settings, progress=self._progress(job), refresh=False, wait=None,
                                    cancel=self._cancel, on_wait=lambda holder: self._tell(BUSY),
                                    verb=VERB, job=job)
        finally:
            self._working(False)
        self._sync_at = self._due_sync(settings)
        if report.get("busy"):
            if not self._cancel.is_set():
                problem = (report.get("problems") or [""])[0]
                self._tell(REVIEWING if problem == anki_connect.REVIEWING else BUSY)
                self._retry(kind)
            return None
        if report.get("reviewing"):
            self._tell(REVIEWING)
            self._retry(kind)
            return report
        if not report.get("ok"):
            written = len(report.get("written") or [])
            problems = report.get("problems") or ["it could not finish"]
            self._tell(f"Anki re-ordered {written:,} cards, then stopped: {problems[0]} — the rest at the next re-order"
                       if written else f"Anki not re-ordered: {problems[0]}")
            self._retry(kind)
            return report
        self._said_done(report, job)
        if report.get("left"):
            self._retry("move")
        return report

    def _progress(self, job):
        def progress(done, total):
            from modules.junban import spaced
            n = job.front_size or 0
            if job.kind == spaced.FULL and total > 200:
                self._tell(f"Anki: spacing your new cards out once so later moves are quick — {done:,} of {total:,}…")
            elif done < len(job.front_ids):
                self._tell(f"Anki: placing tomorrow's {n} cards…")
            elif done < total:
                self._tell(f"Anki: tomorrow's {n} cards placed · moving {total - done:,} more…")
        return progress

    def _said_done(self, report, job):
        from modules.junban import spaced
        written = set(report.get("written") or [])
        n = job.front_size or 0
        front = len(written & set(job.front_ids))
        rest = len(written) - front
        if not written:
            line = UP_TO_DATE
        elif job.kind == spaced.FULL:
            line = f"Anki: your {len(written):,} new cards are spaced out (once) — tomorrow's {n} first"
        elif front:
            line = f"Anki: tomorrow's {n} cards placed · {rest:,} more moved"
        else:
            line = f"Anki: {rest:,} cards moved · tomorrow's {n} already in place"
        if report.get("left"):
            line += f" · {len(report['left'])} changed in Anki meanwhile, placed next"
        self._tell(line)
        if written:
            self._done_at = time.monotonic() + DONE_S

    def _retry(self, kind):
        with self._lock:
            if not self._closing:
                self._retry_at, self._retry_kind = time.monotonic() + RETRY_S, kind

    def _ask_generate(self, reason):
        """Ask the window for an automatic Generate — once per run (`results/`' stamp): the window keeps a request
        it can't start yet, and a Generate that ran and still left a reason (it couldn't write the plan) is not
        asked for again until another run."""
        if self._generate is None:
            return
        from app import analyzer
        from app.path_utils import get_user_file
        asked = ("asked", analyzer.read_run_stamp(get_user_file("results")))
        if asked == self._asked:
            return
        self._asked = asked
        try:
            self._generate(reason)
        except Exception:
            pass

    def _unplaced(self, settings):
        """New cards in the deck the last spaced run didn't place (03 §6: newly mined) — one `findCards`, at most
        every CHECK_ANKI_S, asking for exactly the cards a run places (not suspended, buried or in a filtered deck).
        Never raises."""
        now = time.monotonic()
        if now - self._anki_looked < CHECK_ANKI_S:
            return False
        self._anki_looked = now
        try:
            from app import anki_connect, anki_sync_rule
            from modules.junban import undo
            deck = str(settings.get("junban_deck") or "").strip()
            url = anki_connect.address(settings)
            if not anki_connect.probe(url, timeout=3).get("ok"):
                anki_sync_rule.closed_seen()
                return False
            ids = anki_connect.find_cards(url, f'deck:"{anki_connect.escape_query(deck)}" is:new -is:suspended '
                                               "-is:buried -deck:filtered")
            seen = undo.ladder(self.language, [deck]).get("seen")
            return bool(ids) and (seen is None or max(ids) > seen)
        except Exception:
            return False

    def _journey(self, plan, parts, verdict, store):
        """The dashboard's automatic Generate beyond a re-order the plan can't serve (04 §3, ✅ G1.5-2 / G1.5-5): no
        plan at all (switched on, or lost), or the journey pending because of moves — moved since the last Generate
        (`journey_pending`) and the run no longer this library's — with nothing else changed, or only the known
        words or the lists (re-ordered from the plan already). New files alone start nothing (2.5's button)."""
        if plan is None:
            self._ask_generate("no-plan")
            return
        if verdict is not None and verdict[0] != "replan-now":
            return                                  # generate-first asks from the re-order itself; stand-aside: never
        from app import analyzer, plan_rules
        from app.path_utils import get_user_file
        try:
            full = plan_rules.signature_digest(parts)
            moved = store.journey_pending()
        except Exception:
            return
        if moved and full and full != analyzer.read_run_stamp(get_user_file("results")):
            self._ask_generate("moves")

    # --- S3 and the indicator --------------------------------------------------------------------------------- #

    @staticmethod
    def _due_sync(settings):
        try:
            from app import anki_sync_rule
            return anki_sync_rule.due_at(settings)
        except Exception:
            return None

    def _sync_step(self, force=False):
        """S3 (04 §3): the pending sync when it is due — at once when the window closes."""
        try:
            if self._sync_at is None and not force:
                return
            if not force and time.time() < self._sync_at:
                return
            from app import anki_connect, anki_sync_rule
            settings = self._settings()
            if not is_on(settings, self.language):
                self._sync_at = None
                return
            _answer, self._sync_at = anki_sync_rule.sync_if_due(anki_connect.address(settings), settings,
                                                                 force=force, cancel=None if force else self._cancel)
        except Exception:
            self._sync_at = None

    def _refresh_web(self):
        """The indicator's words, read here (a small file) so the window's thread never reads it."""
        try:
            from app import anki_sync_rule, settings_manager
            self.web = anki_sync_rule.status(settings_manager.load_settings())
        except Exception:
            self.web = ""

    # --- shadow mode (05 §3) --------------------------------------------------------------------------------- #

    def _shadow(self, previous, plan):
        """Shadow mode (05 §3): the engine built from the previous plan, re-planned to this run's order, against
        this run's own lists. A difference writes one line to the log; the host goes on from the new plan."""
        if previous is None or previous is plan:
            return
        h0, h1 = previous.header, plan.header
        if h0.get("order_free_signature") != h1.get("order_free_signature") or \
                h0.get("run_signature") == h1.get("run_signature") or h0.get("language") != h1.get("language"):
            return
        try:
            from app import plan_engine
            if plan_engine.stands_aside(previous):
                return
            engine = plan_engine.Engine(previous, [entry[0] for entry in previous.files])
            result = engine.replan([(entry[0], entry[1]) for entry in plan.files])
            difference = _differs(result, _lists())
        except Exception as e:
            difference = f"the comparison failed: {e}"
        if difference:
            _log_shadow(f"{self.language} · {difference}")


# --- shadow mode's comparison ------------------------------------------------------------------------------------- #

PRIORITY_COLUMNS = ("Word", "Reading", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)", "Orth",
                    "Forms", "Tier")
PROGRESSIVE_COLUMNS = ("Sequence", "Source File", "Word", "Reading", "Score", "Occurrences (Global)",
                       "Occurrences (File)", "Count (High)", "Count (Low)", "Count (Goal)", "Known Count",
                       "Total Count", "Baseline %", "Current %", "New %", "Orth", "Forms", "Tier")


def _lists():
    import csv
    from app.path_utils import get_user_file
    out = {}
    for name, key in (("priority_learning_list.csv", "priority"), ("progressive_learning_list.csv", "progressive")):
        try:
            with open(os.path.join(get_user_file("results"), name), encoding="utf-8-sig", newline="") as f:
                out[key] = list(csv.DictReader(f))
        except OSError:
            out[key] = []
    return out


def _same_value(want, got):
    if isinstance(got, bool) or isinstance(got, str) or got is None:
        return (want or "") == (got or "")
    if isinstance(got, int):
        try:
            return int(want) == got
        except (TypeError, ValueError):
            return False
    if isinstance(got, float):
        try:
            return abs(float(want) - got) <= 1e-9
        except (TypeError, ValueError):
            return False
    return (want or "") == (got or "")


def _differs(result, lists):
    """The first difference between the engine's columns and a Generate's lists (05 §1's plan columns), or ""."""
    for name, rows, columns in (("priority", result.priority, PRIORITY_COLUMNS),
                                ("progressive", result.progressive, PROGRESSIVE_COLUMNS)):
        want = lists.get(name) or []
        if len(want) != len(rows):
            return f"{name}: {len(rows)} rows, the Generate wrote {len(want)}"
        for i, (w, r) in enumerate(zip(want, rows)):
            for column in columns:
                if not _same_value(w.get(column), r.get(column)):
                    return (f"{name} row {i + 1} ({w.get('Word')}): {column} {r.get(column)!r}, "
                            f"the Generate wrote {w.get(column)!r}")
    return ""


def _log_shadow(line):
    """One line to `replan_shadow.log` in the local data folder's logs (beside the command line's). Never raises."""
    try:
        from app.path_utils import get_local_data_path
        folder = os.path.join(get_local_data_path(), "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, SHADOW_LOG), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " · " + line + "\n")
    except Exception:
        pass
