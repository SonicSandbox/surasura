"""The fast re-plan's preview (E1.1 04, RP-7; 2.6, opt-in): a move in the Content Manager re-orders Anki's new cards
about a second later — tomorrow's cards first, then the rest — without a full Generate.

    replan_preview.is_on(settings)          # 順's option "Re-order Anki as I move content (preview)", Junban present
    replan_preview.unavailable(settings)    # why the option can't be used now (D7), or None
    host = replan_preview.Host(language, say=…, working=…, generate=…)   # one per window process
    host.poke()                             # a store change: the 0.8 s settle restarts; one job when it ends
    host.catch_up()                         # the dashboard's start / focus, the CM's open: the job, only if owed
    host.after_generate()                   # a full Generate finished: the automatic step on its list, shadow mode
    host.close()                            # the window closes: a pending settle and a pending sync run at once

**The job** (04 §2.3), on the host's one worker, never two at once (a poke during a job queues one more): the store's
versions → the plan file checked against the library as it stands (`plan_engine.check`, the signature's parts read
here) → the order from the store → `Engine.replan` → Junban's spaced delta with the engine's rows
(`reposition.run(job=spaced.Job(automatic=True, …))`, under the Anki-write lock, positions only, one deck) →
`record_planned` with the versions read before the order. When the plan can't serve the move the line says so and the
dashboard's host asks its window for an automatic Generate (04 §3–4; `generate`).

**Off** (the default), or Junban removed: `is_on` is False, no window makes a host, and nothing here imports Junban,
the engine or the analyzer — 2.5, byte for byte (rule 1).

Light by rule: no Tk. `say(line)`, `working(bool)` and `generate(reason)` are the window's, called from the worker:
each must only post to that window's own queue. Everything heavy (the store, the engine, the analyzer's signature,
Junban) is imported on the worker.
"""

import importlib.util
import os
import threading
import time

SWITCH = "junban_replan_preview"
SETTLE_S = 0.8                  # 04 §2.2: the moves' settle
RETRY_S = 20.0                  # Anki in a review, 順's window open, cards left by the re-check: look again
DONE_S = 5.0                    # "tomorrow's cards placed" gives way to "up to date" after this
CHECK_ANKI_S = 60.0             # the catch-up's look for new cards in Anki, at most this often
CLOSE_WAIT_S = 20.0             # the window's "finishing…" waits at most this long
SHADOW_LOG = "replan_shadow.log"
VERB = "re-ordering as you move"    # the Anki-write lock's holder line ("… is writing to Anki")
TIERS = ("now", "soon", "goal")

# The bar's lines (04 §2.4, §4).
CLOSED = "Anki is closed — your new order goes to Anki the next time Surasura sees it open"
REVIEWING = "Anki is in a review — re-ordering after it"
BUSY = "順 is busy — re-ordering when it's done"
UPDATE = "An update is waiting — re-ordering after it"
UP_TO_DATE = "Anki's order is up to date"
GENERATE_FIRST = "New content or settings: Generate runs first, then Anki is re-ordered"
NEW_CONTENT = "New content: Generate puts its words in Anki's order (press it when you've placed it)"
GENERATE_FIRST_CM = "New content or settings: Generate runs first (when you close the Content Manager), then Anki is re-ordered"
REPLAN_THEN_GENERATE = "Anki re-ordered · refreshing your list (Generate)…"
REPLAN_THEN_GENERATE_CM = "Anki re-ordered · your list refreshes (Generate) when you close the Content Manager"
GENERATING = "Refreshing your list (Generate)… · Anki is re-ordered when it's done"
STAND_ASIDE = {
    "coverage": "Re-ordering as you move is off with Coverage selection — Generate re-orders Anki",
    "i+1": "Re-ordering as you move is off with 'Only i+1' — Generate re-orders Anki",
    "shared-phrase": "This list holds a row two set phrases share — Generate re-orders Anki this time",
    "weights": "Your tier weights aren't whole numbers — Generate re-orders Anki",
}


def junban_present():
    """Is Junban installed? Asked without importing it (core never imports `modules/` at load: Backlog spec I2)."""
    try:
        return importlib.util.find_spec("modules.junban") is not None
    except (ImportError, ValueError):
        return False


def is_on(settings):
    """The preview's switch: on, Junban switched on, and present. Everything the preview does asks this first."""
    settings = settings or {}
    return settings.get(SWITCH) is True and settings.get("enable_junban") is True and junban_present()


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
        self._sync_at = None                      # wall time: S3's
        self._running = False
        self._closing = False
        self._anki_looked = -CHECK_ANKI_S
        self._done_at = None
        self._asked = None                        # the last automatic Generate asked for: (reason, the run stamp)
        self._seen = None                         # the catch-up's last look with nothing owed (store, plan, run)
        self._store = None
        self._plan = self._plan_key = self._engine = self._ids = None
        self._cards = None
        self.last = ""                            # the last line said (tests; the window's line)

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
            waits.append(self._sync_at - wall)
        if self._done_at is not None:
            waits.append(self._done_at - now)
        return max(0.0, min(waits))

    def _loop(self):
        while not self._stop.is_set():
            self._wake.wait(self._next_wait())
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.run_pending()
            except Exception as e:                  # a background job must never take the window down
                self._tell(f"Re-ordering as you move stopped: {e}")
            with self._lock:
                if self._closing and not self._want and self._due is None:
                    self._running = False
                    break

    def run_pending(self):
        """Whatever is due now, in order — the worker's step (a test calls it directly)."""
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
            if "warm" in run:
                self._warm()
            for kind in ("generate", "move", "catch-up"):
                if kind in run:
                    self._job(kind)
            self._sync_step(force="sync-now" in run)
            if self._done_at is not None and time.monotonic() >= self._done_at:
                self._done_at = None
                self._tell(UP_TO_DATE)
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

    def _store_handle(self):
        if self._store is None:
            from app import library_store
            from app.path_utils import get_data_path, get_user_files_path
            self._store = library_store.open_store(self.language, get_data_path(self.language),
                                                   get_user_files_path(self.language), role="window")
        return self._store

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
        """04 §2.1: the plan and the engine; Junban warms on the first job (its tables build while Anki answers)."""
        settings = self._settings()
        if not is_on(settings):
            return
        store = self._store_handle()
        if store is None:
            return
        plan, _why = self._load_plan()
        if plan is not None:
            self._engine_for(store)

    def _job(self, kind):
        """One job (04 §2.3): "move" (the CM's settle), "catch-up" (start, focus, the CM's open) or "generate"
        (after a full Generate)."""
        settings = self._settings()
        if not is_on(settings) or unavailable(settings):
            return
        store = self._store_handle()
        if store is None:
            return                                   # no library store (JSON mode): nothing to re-plan from
        versions = store.versions()
        owed = (versions["order_version"] > versions["planned_order_version"]
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
            if plan is None:
                return
            self._shadow(previous, plan)
            owed = True
        parts = self._parts(settings, store) if plan is not None else None
        verdict = self._verdict(plan, parts, store) if plan is not None else ("generate-first", why)
        if owed:
            self._replan(settings, store, versions, verdict, kind)
        if kind == "catch-up" and self._generate is not None:
            self._journey(plan, parts, verdict, store)

    def _replan(self, settings, store, versions, verdict, kind="move"):
        if verdict is not None and verdict[0] == "stand-aside":
            self._tell(STAND_ASIDE.get(verdict[1], "Generate re-orders Anki this time"))
            return
        if verdict is not None and verdict[0] == "generate-first":
            if self._plan is not None and not self._moved(store):
                # Only new (or changed) content, nothing the plan holds moved: new episodes are the user's to place
                # first (2.4's rule for the automatic Generate) — said, never run on its own.
                self._tell(NEW_CONTENT)
                return
            self._tell(GENERATE_FIRST if self._generate is not None else GENERATE_FIRST_CM)
            self._ask_generate(f"generate-first: {verdict[1]}")
            return
        engine, ids = self._engine_for(store)
        held = set(i for i in ids if i is not None)
        order = [(item_id, tier) for tier in TIERS for item_id in store.ids(tier) if item_id in held]
        result = engine.replan(order)
        mode = str(settings.get("junban_order") or "content").strip().lower()
        rows = result.rows(mode if mode in ("content", "priority") else "content")
        from modules.junban import spaced
        job = spaced.Job(automatic=True, rows=rows, cards=self._card_map(), places=places(self._plan, ids, result))
        report = self._write(settings, job, kind)
        if report is not None and report.get("ok") and not report.get("left") and not report.get("failures"):
            store.record_planned(versions["order_version"], versions["pins_version"])
        if verdict is not None and verdict[0] == "replan-now" and report is not None and report.get("ok"):
            self._tell(REPLAN_THEN_GENERATE if self._generate is not None else REPLAN_THEN_GENERATE_CM)
            self._done_at = None
            self._ask_generate("replan-now: " + ",".join(verdict[1]))

    def _moved(self, store):
        """Did anything the plan holds move — its files' order or tiers in the store now, against the run's own?"""
        ids = [store.item_id(entry[0]) for entry in self._plan.files]
        held = set(i for i in ids if i is not None)
        then = [(item_id, entry[1]) for item_id, entry in zip(ids, self._plan.files) if item_id is not None]
        now = [(item_id, tier) for tier in TIERS for item_id in store.ids(tier) if item_id in held]
        return now != then

    def _card_map(self):
        if self._cards is None:
            from modules.junban import reposition
            self._cards = reposition.CardMap()
        return self._cards

    def _write(self, settings, job, kind):
        """Junban's run for `job`, with the preview's guards (04 §4) and its bar lines -> the report, or None when
        nothing ran (the line said why; `kind` runs again later when it's worth it)."""
        from app import anki_connect, anki_sync_rule
        from modules.junban import auto, reposition
        blocked = auto.blocked(settings)
        if blocked:
            if blocked == "the 順 window is open":
                self._tell(BUSY)
                self._retry(kind)
            elif blocked == "an update is waiting":
                self._tell(UPDATE)
            return None
        url = anki_connect.address(settings)
        if not anki_connect.probe(url, timeout=3).get("ok"):
            anki_sync_rule.closed_seen()
            self._tell(CLOSED)
            return None
        if anki_connect.reviewing(url):
            self._tell(REVIEWING)
            self._retry(kind)
            return None
        settings.update(auto._POSITIONS_ONLY)
        self._working(True)
        try:
            report = reposition.run(settings, progress=self._progress(job), refresh=False, wait=None,
                                    cancel=self._cancel, on_wait=lambda holder: self._tell(BUSY),
                                    verb=VERB, job=job)
        finally:
            self._working(False)
        if report.get("busy"):
            if not self._cancel.is_set():
                self._tell(BUSY)
                self._retry(kind)
            return None
        if not report.get("ok"):
            problems = report.get("problems") or ["it could not finish"]
            self._tell(f"Anki not re-ordered: {problems[0]}")
            return report
        self._said_done(report, job)
        if report.get("left"):
            self._retry("move")
        self._sync_at = anki_sync_rule.due_at(settings)
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
        written = set(report.get("written") or [])
        n = job.front_size or 0
        front = len(written & set(job.front_ids))
        rest = len(written) - front
        if not written:
            line = UP_TO_DATE
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
        every CHECK_ANKI_S. Never raises."""
        now = time.monotonic()
        if now - self._anki_looked < CHECK_ANKI_S:
            return False
        self._anki_looked = now
        try:
            from app import anki_connect
            from modules.junban import undo
            deck = str(settings.get("junban_deck") or "").strip()
            url = anki_connect.address(settings)
            if not anki_connect.probe(url, timeout=3).get("ok"):
                return False
            ids = anki_connect.find_cards(url, f'deck:"{anki_connect.escape_query(deck)}" is:new')
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

    def _sync_step(self, force=False):
        """S3 (04 §3): the pending sync when it is due — at once when the window closes."""
        try:
            if self._sync_at is None and not force:
                return
            if not force and time.time() < self._sync_at:
                return
            from app import anki_connect, anki_sync_rule
            settings = self._settings()
            if not is_on(settings):
                self._sync_at = None
                return
            _answer, self._sync_at = anki_sync_rule.sync_if_due(anki_connect.address(settings), settings,
                                                                 force=force, cancel=None if force else self._cancel)
        except Exception:
            self._sync_at = None

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
