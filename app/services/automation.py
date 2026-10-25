"""Automatic Anki sync, automatic Generate and 順's automatic reorder (W3.5 row 3), Qt-free: the Tk dashboard's
`_maybe_anki_sync`, `_on_anki_sync_result`, `_maybe_backlog_sync`, `_maybe_auto_generate` (+ `_auto_generate_alarm`)
and `_maybe_junban_auto`, as one service a window builds once.

- **The triggers are the window's calls** — `started()` (the sync 2 s after the window opens, forced), `activated()`
  (the window came back into focus: the sync, 順 and a waiting Generate, each asked again), `language_changed(lang)`
  (the sync forced: known words and decks are per language), `recheck()` (the Generate button's journey check, 0.6 s
  after a burst: focus, an indexer's end, new known words), `sync_now()` (a click on the bar's known-words count: the
  same sync, forced, with the automatic sync off too) — and they only queue: every gate (`anki_sync.may_sync`,
  the settings, the throttles, a file or a store read) is asked on the service's one worker, in the order asked, so
  the window's thread never waits.
- **Never twice.** Each duty is a job in the window's registry (`app/services/jobs.py`): the sync an `anki-sync` job,
  順 a `junban` job, Generate through `GenerateController.request(quiet=True)` (the `generate` job: a user's request
  takes an automatic one's place; an automatic one never runs beside a user's). On top: the Tk throttles, moved here —
  the sync and 順 at most every 5 minutes unless forced, counted from "never" (`-inf`: on Windows `time.monotonic`
  counts from the computer's start), the automatic Generate at most every 10 minutes with one alarm for the moment the
  limit is up — and a duty already live in the registry is not asked again.
- **The gates are the modules' own** (`anki_sync.may_sync`: the test switch, decks chosen, the first sync the user's;
  `modules/junban/auto.py`'s `enabled` / `blocked` / `window_open`); `update_staged()` (default
  `updater.children_held`) holds everything while an update waits. The automatic Generate runs only for the language
  its words came for, never while a Generate or another child process is live, never on an empty library.
- **The state for the bar** (`state()`, `subscribe`): the last sync (`idle` · `syncing` · `synced` · `anki-closed` ·
  `failed`), how many words it added, the known-words count (read on the worker: at the start, on a language switch and
  after each sync) and 順's last line. Delivered only when it changed, on the worker's thread; a window posts it on.

`close()` leaves nothing: no timer, no listener acting, the worker stopped. 順 already running finishes its batch
(`on_quit="wait"`: an Anki write is never cut in half, and the window stays until it ends, E20). The sync and the
backlog read only read Anki and write their files atomically under the known-words lock, so closing never waits for
them (`on_quit="detach"`, as the Tk `on_closing`); neither can be cancelled (no Stop on the update's wait list).
"""
import importlib
import math
import os
import queue
import threading
import time
from collections import namedtuple

from app.services import generate as generate_module
from app.services import jobs as jobs_module

SYNC_EVERY = 300.0          # _maybe_anki_sync: FocusIn fires for every widget, so 5 minutes, not a debounce
GENERATE_EVERY = 600.0      # _maybe_auto_generate: at most every 10 minutes
JUNBAN_EVERY = 300.0        # _maybe_junban_auto: like the sync
START_DELAY = 2.0           # the Tk `root.after(2000, lambda: self._maybe_anki_sync(force=True))`
CHECK_SETTLE = 0.6          # _schedule_journey_state: one journey check for a burst of triggers
# The child processes the automatic Generate waits for: the Tk window's, and the 3.0 importers' (a known-words import,
# Extract: the Tk tooltip's "never while … an import … is running")
CHILD_KINDS = ("generate", "indexer", "sentence-corpus", "child", "known-import", "extract")

IDLE, SYNCING, SYNCED, CLOSED, FAILED = "idle", "syncing", "synced", "anki-closed", "failed"
SYNC_LABEL = "Updating known words from Anki"
BACKLOG_LABEL = "Reading Anki's new cards"
JUNBAN_LABEL = "Re-ordering Anki (automatic)"

State = namedtuple("State", "sync language added known message junban seq")
# What `level` reads (IK-28): only a write of one of these reads the token store again for the bar's level chip.
LEVEL_KEYS = ("logic.selection", "logic.names_recurring", "logic.names_kanji", "logic.names_work_terms", "zh_script")


def start_timer(delay, call):
    """A daemon `threading.Timer` started now (the services' timer; a test hands in its own)."""
    timer = threading.Timer(max(0.0, delay), call)
    timer.daemon = True
    timer.start()
    return timer


class Worker:
    """One thread that runs a service's calls in the order asked: `put` returns at once."""

    def __init__(self, name):
        self.name = name
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = None
        self._closed = False

    def put(self, call, *args):
        """Queue `call(*args)`. False once closed."""
        with self._lock:
            if self._closed:
                return False
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
                self._thread.start()
            self._queue.put((call, args))
        return True

    def idle(self, timeout=None):
        """Wait until everything queued has run (a test's, or a worker's call). True when it has."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._queue.all_tasks_done.wait(left)
        return True

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._thread is not None:
                self._queue.put(None)

    def _loop(self):
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                call, args = item
                try:
                    call(*args)
                except Exception as e:                # one duty's fault never stops the others
                    print(f"{self.name}: {e}")
            finally:
                self._queue.task_done()


def _thaw(settings):
    from app.services.settings import thaw
    return thaw(settings or {})


def _set_up(language):
    """The language's folders and word lists, and the 30-day .trash clean-up, before a Generate (the Tk `run_analyzer`'s
    `ensure_data_setup`, IK-21). A worker's call."""
    try:
        from app import path_utils
        path_utils.ensure_data_setup(language)
    except Exception as e:
        print(f"Generate: the folders couldn't be set up: {e}")


def library_has_content(language):
    """Whether `language`'s library has a file Generate would read (the Tk `_library_has_content` /
    `_folders_have_content`): the store's answer when it is ready, else the tier folders walked. A worker's call."""
    from app.path_utils import get_data_path, get_user_files_path, is_content_file
    data_dir = get_data_path(language)
    try:
        from app import library_store
        store = library_store.open_store(language, data_dir, get_user_files_path(language), role="window",
                                         busy_wait=0.0)
        if store is not None:
            with store:
                return bool(store.has_content())
    except Exception:
        pass
    for tier in ("HighPriority", "LowPriority", "GoalContent"):
        folder = os.path.join(data_dir, tier)
        if os.path.isdir(folder):
            for _root, _dirs, files in os.walk(folder):
                if any(is_content_file(f) for f in files):
                    return True
    return False


def journey_current(settings, language):
    """The Generate button's own question (`analyzer.journey_is_current`), asked on a worker."""
    from app import analyzer, run_args
    return analyzer.journey_is_current(run_args.analyzer_args(settings, language), language)


def moves_level(keys):
    """Whether a write of `keys` (the settings service's: dotted under `logic`) can move the level chip: the whole
    `logic` block, or a key `level` reads (`LEVEL_KEYS`)."""
    return any(key == "logic" or any(key == k or key.startswith(k + ".") for k in LEVEL_KEYS) for key in keys)


def level(settings, language):
    """The bar's level chip (W3.5 row 5): (band, automatic) — `logic.selection.band`, or with Automatic rarity on the
    band `word_selection.auto_band` picks over the Rarity slider's numbers (the Tk `_compute_band_previews` +
    `_auto_band_choice`: the rule Generate applies, I3), band None while there are none yet. Reads the token store: a
    worker's call."""
    from app import word_selection
    from app.settings_manager import DEFAULT_SETTINGS
    settings = settings or {}
    sel = ((settings.get("logic") or {}).get("selection") or {})
    if not sel.get("auto"):
        return sel.get("band") or DEFAULT_SETTINGS["logic"]["selection"]["band"], False
    try:
        from app import analyzer, library_store, token_index
        from app.path_utils import get_data_path, get_user_files_path
        from app.zh_script import effective
        for key in ("names_recurring", "names_kanji", "names_work_terms"):     # as the Tk refresh sets them
            analyzer.LOGIC[key] = bool((settings.get("logic") or {}).get(key, True))
        script = effective(language, settings.get("zh_script", "asis"))
        try:
            remembered = library_store.read_auto_band(language, get_data_path(language))
        except Exception:
            remembered = None
        store = token_index.open_store(language)
        try:
            freqs = token_index.preview_frequencies(store, language, get_user_files_path(language), script)
            if freqs is None:
                return None, True
            previews = word_selection.band_previews(
                freqs, sel.get("bands_ppm"), sel.get("min_count", word_selection.DEFAULT_MIN_COUNT),
                freqs["total_tokens"] / (store.file_count() or 1),
                sel.get("minutes_per_file", word_selection.MINUTES_PER_FILE))
        finally:
            store.close()
        try:
            return word_selection.auto_band(previews, sel.get("auto_max_words", word_selection.DEFAULT_AUTO_MAX_WORDS),
                                            remembered=remembered), True
        except (TypeError, ValueError):
            # A line the rule can't compare with ("850" in quotes, hand-edited into settings.json) makes the analyzer
            # keep your own band: so that is the band shown (the Tk `_auto_band_choice`).
            return sel.get("band") or DEFAULT_SETTINGS["logic"]["selection"]["band"], True
    except Exception as e:
        print(f"Automation: the level couldn't be read: {e}")
        return None, True


class AutoSync:
    """The background known-words sync from a running Anki (`_maybe_anki_sync`), its result
    (`_on_anki_sync_result`) and Generate's read of the Anki backlog (`_maybe_backlog_sync`)."""

    def __init__(self, owner):
        self._owner = owner
        self._last = float("-inf")

    def maybe(self, force=False, asked=False):
        """(The worker.) Start a sync when every gate allows: None, or why not (a short word, for tests and logs).
        `asked`: the user's own (`Automation.sync_now`) — the same job, run with the automatic sync switched off too,
        and a user's job in the registry."""
        o = self._owner
        settings = o.settings_now()
        if not (asked or settings.get("anki_sync_auto")) or os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return "off"
        now = o.clock()
        if not force and now - self._last < SYNC_EVERY:
            return "throttled"
        language = o.language
        from app import anki_sync
        why = anki_sync.may_sync(language, settings, throttle=False)
        if why is not None:
            return why[0]
        if o.update_staged():
            return "update-staged"              # an update waits (K75): no Anki read or write may begin
        if o.registry.live("anki-sync"):
            return "running"                    # a sync is running (this one, or the Anki window's)
        self._last = now
        decks = list((settings.get("anki_sync_decks") or {}).get(language) or [])
        fields = list((settings.get("anki_sync_fields") or {}).get(language) or [])
        suspended = bool(settings.get("anki_sync_include_suspended", False))
        o.registry.submit("anki-sync", SYNC_LABEL, automatic=not asked, on_quit="detach",
                          start=lambda job: o.thread(self._work, job, language, settings, decks, fields, suspended))
        return None

    def _work(self, job, language, settings, decks, fields, suspended):
        """(The job's own thread.) The Tk `work()`'s order: the sync, then the same decks' new cards."""
        o = self._owner
        o.publish(sync=SYNCING, language=language, message=None)
        result, closed, problem = None, False, None
        try:
            from app import anki_connect, anki_sync
            url = anki_connect.address(settings)
            if anki_connect.probe(url).get("ok"):
                # the one sync order: the studied words, the new cards (the report's backlog marks), then Known from
                # Anki — your suspended / marked cards (laptop round 7 #43: the window's sync never read it)
                result, _signal = anki_sync.sync_all(language, url, decks, fields, settings,
                                                     include_suspended=suspended)
            else:
                closed = True
        except Exception as e:
            problem = str(e)
            print(f"Anki sync skipped: {e}")
        failed = (result is None and not closed) or (result is not None and bool(result.error))
        job.finish(ok=not failed, message=problem or (result.error if result is not None else None))
        self.ended(result, language, closed, problem)

    def ended(self, result, language, closed=False, problem=None):
        """(The sync's own thread.) Every sync's end, automatic or by hand (`Automation.anki_synced`: the Anki window's
        *Sync now*, the setup wizard's first sync): the bar told, the 5-minute wait counted from now, and the result's
        work (`result`) queued for the worker."""
        o = self._owner
        if result is not None or closed:
            self._last = o.clock()
        if closed:
            o.publish(sync=CLOSED, message="Anki is closed")
        elif result is None:
            o.publish(sync=FAILED, message=problem)
        elif result.error:
            o.publish(sync=FAILED, message=result.error)
        elif language == o.language:
            o.publish(sync=SYNCED, added=result.added, known=result.total_known, message=None)
            if language != o.language:          # switched as it was said: the open language's count, read after it
                o.worker.put(o._read_known)
        else:
            o.publish(sync=SYNCED, added=result.added, message=None)     # its count is another language's (D31)
        if result is not None:
            o.worker.put(self.result, result, language)

    def result(self, result, language):
        """(The worker.) After a sync (`_on_anki_sync_result`): when it changed the known words, the automatic
        Generate for the language it read — or, when none starts, the indexer — and the journey asked again."""
        o = self._owner
        if result.error:
            print(f"Anki sync: {result.error}")
            return
        if result.added > 0 or result.mode in ("replace", "restore"):
            if not o.generate.known_words_changed(language) and o.index is not None:
                o.index()
            o.recheck()

    def backlog(self):
        """(The worker.) Generate's own read of the Anki backlog (`_maybe_backlog_sync`), never waited for."""
        o = self._owner
        settings = o.settings_now()
        if not settings.get("anki_backlog_on_generate", True) or os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return "off"
        language = o.language
        decks = list((settings.get("anki_sync_decks") or {}).get(language) or [])
        if not decks:
            return "no-decks"
        if o.registry.live("anki-backlog"):
            return "running"
        fields = list((settings.get("anki_sync_fields") or {}).get(language) or [])

        def work(job):
            try:
                from app import anki_connect, anki_sync
                url = anki_connect.address(settings)
                if anki_connect.probe(url).get("ok"):
                    anki_sync.sync_backlog(language, url, decks, fields)
            except Exception as e:
                print(f"Anki backlog skipped: {e}")
            job.finish(ok=True)
        o.registry.submit("anki-backlog", BACKLOG_LABEL, automatic=True, on_quit="detach",
                          start=lambda job: o.thread(work, job))
        return None


class AutoGenerate:
    """The quiet Generate when the sync brought in known words (`_maybe_auto_generate`, `_auto_generate_alarm`)."""

    def __init__(self, owner):
        self._owner = owner
        self._last = float("-inf")
        self._alarm = None
        self.pending = False        # False, or the language Anki brought words in for, not generated since
        self.pending_at = None      # when they came (the clock the registry stamps a job's start with)
        self._children = 0

    def known_words_changed(self, language):
        """(The worker.) Words came in for `language`: pending with *Generate when Anki adds known words* on."""
        if self._owner.settings_now().get("anki_auto_generate"):
            self.pending, self.pending_at = language, time.time()
        return self.maybe()

    def maybe(self):
        """(The worker.) The quiet Generate, if nothing holds it back. True when it was asked for."""
        o = self._owner
        pending = self.pending
        settings = o.settings_now()
        if not pending or not settings.get("anki_auto_generate"):
            return False
        if o.held is not None and o.held():
            return False                # the setup wizard is up (W3.5 part 3): its close asks again
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return False
        if pending != o.language:
            return False                # for the other language: it runs once that one is open again
        if o.controller.state().state in (generate_module.QUEUED, generate_module.RUNNING,
                                          generate_module.CANCELLING):
            return False                # a Generate is asked for or running: its end asks again
        if o.update_staged():
            return False                # an update waits (K75): asked again if it is cancelled
        if any(view.kind in CHILD_KINDS for view in o.registry.live()):
            return False                # a child process is running: its end asks again
        if not o.has_content(o.language):
            return False
        now = o.clock()
        wait = GENERATE_EVERY - (now - self._last)
        if wait > 0:
            self._arm(wait)             # only the limit is in the way: one alarm, replaced, never stacked
            return False
        self._last = now
        self.pending = False            # this run includes them (run_analyzer clears it as it starts)
        print("Anki brought in words you know now — generating in the background; the report is not opened.")
        _set_up(o.language)
        o.sync.backlog()
        o.controller.request(o.language, settings=_thaw(settings), quiet=True, settle=0, launcher=o.launcher)
        return True

    def _arm(self, wait):
        o = self._owner
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return                      # never scheduled under test (testing.md §5.4)
        with o.lock:
            if o.closed:
                return
            if self._alarm is not None:
                self._alarm.cancel()
            self._alarm = o.timer(math.ceil(wait * 1000) / 1000.0, lambda: o.worker.put(self._ring))

    def _ring(self):
        """The 10-minute limit is up: asked again (everything, as the Tk alarm does)."""
        with self._owner.lock:
            self._alarm = None
        self.maybe()

    def cancel_alarm(self):
        with self._owner.lock:
            alarm, self._alarm = self._alarm, None
        if alarm is not None:
            alarm.cancel()

    def ended(self, language, outcome, started_at=None):
        """(The worker, after the controller's end.) A Generate of the pending language that ran includes its words
        when they came before it started (`started_at`, its job's start: the Tk `run_analyzer` cleared them as any
        Generate of it started) — words that came while it ran are not in it and wait for the next (HR-1); else the
        waiting one asks again."""
        if (outcome != "dropped" and self.pending and (language or self._owner.language) == self.pending
                and started_at is not None and self.pending_at is not None and self.pending_at <= started_at):
            self.pending = False
        if self.pending:
            self.maybe()

    def jobs_changed(self, views):
        """(The registry's thread.) When the last child process ends, a waiting Generate gets its chance. A Generate's
        own end is the controller's to tell (`ended`, after its words are counted in): its job ending first would ask
        before they are."""
        children = sum(1 for v in views if v.kind in CHILD_KINDS and v.kind != "generate"
                       and v.state in jobs_module.LIVE)
        before, self._children = self._children, children
        if before and not children and self.pending:
            self._owner.worker.put(self.maybe)


def reorders(settings, language):
    """Whether 順's automatic step may re-order Anki here (W3.5 row 7): never with automation off (D29: every
    automatic Anki write), never while the re-order host runs for this language (`replan_preview.automation_on`: one
    re-order per Generate, the host's — as the Tk `_maybe_junban_auto`), and only to the deck recorded for this language
    (`recorded_deck`, Haya G3). An answer that can't be had is no. A worker's call."""
    try:
        from app import replan_preview, settings_manager
        return (settings_manager.automation(settings) and not replan_preview.automation_on(settings, language)
                and replan_preview.recorded_deck(settings, language) is not None)
    except Exception as e:
        print(f"順 (automatic): its re-order's switch couldn't be read: {e}")
        return False


class AutoJunban:
    """順's automatic reorder (`_maybe_junban_auto`; a test option, `junban_auto_reorder` in settings.json) and its
    Backfill step. The reorder only where `reorders` says (W3.5 row 7); the Backfill always as switched on."""

    def __init__(self, owner):
        self._owner = owner
        self._last = float("-inf")

    def maybe(self, force=False):
        """(The worker.) None when the reorder was asked for, else why not."""
        o = self._owner
        now = o.clock()
        if not force and now - self._last < JUNBAN_EVERY:
            return "throttled"
        try:
            auto = importlib.import_module("modules.junban.auto")
        except Exception:
            return "absent"             # the module isn't installed: the window runs without it
        settings = _thaw(o.settings_fresh())    # the file now: 順's deck pick (its own save) is seen at once
        settings["target_language"] = o.language
        if not reorders(settings, o.language):
            settings["junban_auto_reorder"] = False     # the re-order host's, or none: the Backfill step stays
        if not auto.enabled(settings) or auto.blocked(settings, window=False):
            return "off"
        if o.update_staged():
            return "update-staged"
        if o.registry.live("junban"):
            return "running"
        self._last = now
        language = o.language

        def work(job):
            message = ""
            try:
                if not auto.window_open():          # a lock look: on this thread, never the window's
                    o.flush()
                    message = auto.run_quietly(settings, list_current=o.journey_current(settings, language))
            except Exception as e:
                message = f"順 (automatic) skipped: {e}"
            finally:
                job.finish(ok=True, message=message or None)
            if message:
                o.publish(junban=message)
        o.registry.submit("junban", JUNBAN_LABEL, automatic=True, on_quit="wait",
                          start=lambda job: o.thread(work, job))
        return None


class Automation:
    """One per window. `registry`: the window's job registry; `controller`: its `GenerateController`; `settings`: the
    settings service (`get()`, `flush(timeout)`); `language`: the one open. `update_staged()`: an update waits
    (default `updater.children_held`). `index()`: the indexer asked for (the chores service's `index`, forced) when
    words came in and no Generate started. `launcher`: how the controller starts the child (`request`'s; default its
    own). `clock`, `timer(delay, call)`, `has_content(language)`, `journey_current_fn(settings, language)`: a test's
    stand-ins (defaults `time.monotonic`, `start_timer`, `library_has_content`, `journey_current`)."""

    def __init__(self, registry, controller, settings, language, update_staged=None, index=None, launcher=None,
                 clock=None, timer=None, has_content=None, journey_current_fn=None):
        self.registry = registry
        self.controller = controller
        self._settings = settings
        self.language = language or "ja"
        self.index = index
        self.launcher = launcher
        self.clock = clock or time.monotonic
        self.timer = timer if timer is not None else start_timer
        self.has_content = has_content or library_has_content
        self.journey_current = journey_current_fn or journey_current
        if update_staged is None:
            from app import updater
            update_staged = updater.children_held
        self.update_staged = update_staged
        self.lock = threading.RLock()
        self.closed = False
        self.held = None                # the window's: `held()` True while the setup wizard is up (no quiet Generate)
        self.worker = Worker("automation")
        self._state = State(IDLE, self.language, 0, None, None, None, 0)
        self._subscribers = []
        self._deliver = threading.RLock()
        self._start_timer = None
        self._check_timer = None
        self.sync = AutoSync(self)
        self.generate = AutoGenerate(self)
        self.junban = AutoJunban(self)
        controller.on_end(self._ended)
        registry.subscribe(self._jobs_changed)

    # --- reading ------------------------------------------------------------------------------------------------ #
    def state(self):
        with self.lock:
            return self._state

    def subscribe(self, callback):
        """`callback(State)` after every change, on the thread that made it (the worker, or a job's)."""
        with self.lock:
            self._subscribers.append(callback)

    # --- the window's triggers (each returns at once) ------------------------------------------------------------ #
    def started(self):
        """The window opened: the known-words count read, and the sync forced 2 s on (skipped under test, as the Tk
        start timers are)."""
        self.worker.put(self._read_known)
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        with self.lock:
            if self.closed or self._start_timer is not None:
                return
            self._start_timer = self.timer(START_DELAY, lambda: self.worker.put(self.sync.maybe, True))

    def activated(self):
        """The window came back into focus (the Tk `<FocusIn>`): the journey asked again (`recheck`), the sync, 順 and
        a waiting Generate."""
        self.recheck()
        self.worker.put(self.sync.maybe)
        self.worker.put(self.junban.maybe)
        self.worker.put(self.generate.maybe)

    def language_changed(self, language):
        """Known words and decks are per language: the count read again, the sync forced, and Generate's waiting
        words for the language now open may go."""
        with self.lock:
            self.language = language or "ja"
        self.worker.put(self._read_known)
        self.worker.put(self.sync.maybe, True)
        self.worker.put(self.generate.maybe)

    def known_changed(self):
        """A known-words import ended having written (W3.4 row 2: the deck, Migaku, Jiten): the bar's count read again
        and the journey asked again. Any thread; returns at once. Nothing once closed."""
        if self.closed:
            return
        self.worker.put(self._read_known)
        self.recheck()

    def anki_synced(self, result, language):
        """A sync by hand ended (the Anki window's *Sync now*, Replace, Restore; the setup wizard's first sync): it ends
        as the automatic one does (`AutoSync.ended`). The job's own thread; returns at once. Nothing once closed."""
        if self.closed:
            return
        self.sync.ended(result, language or self.language)

    def session_began(self, fresh):
        """The window's session look found Anki open (Q4-16: `Services._session`, after *Open Anki for me*): the
        known-words sync asked again — forced when the session's sync brought your phone's reviews in (`fresh`), else
        at its own pace (the Tk `_maybe_anki_sync(force=fresh)`). Any thread; returns at once. Nothing once closed."""
        if not self.closed:
            self.worker.put(self.sync.maybe, bool(fresh))

    def sync_now(self, then=None):
        """A sync the user asked for (a click on the bar's known-words count, Q30): the automatic sync's own job,
        forced, run with `anki_sync_auto` off too (the user asked), ending as every sync does (`AutoSync.ended`: the
        5-minute wait counted from it). One at a time: a click while a sync runs adds nothing ("running"). `then(why)`
        on the worker: None when it started, else why not — "no-decks" and "never-synced" are the Anki window's to
        set right (the first sync is always made there). Any thread; returns at once. Every ask is answered (round 8,
        A-2: a press waits on it): "failed" when the sync couldn't be asked for, "closed" once closed."""
        def ask():
            try:
                why = self.sync.maybe(force=True, asked=True)
            except Exception as e:
                print(f"{self.worker.name}: the sync asked for failed: {e}")
                why = "failed"
            if then is not None:
                then(why)
        if self.closed or not self.worker.put(ask):
            if then is not None:
                then("closed")

    def recheck(self):
        """Is the journey still current? (`_schedule_journey_state`) — the Generate button's mark: one
        `GenerateController.check` 0.6 s after the last of a burst of triggers (focus, an indexer's end — the chores'
        `on_indexed` —, new known words). Never under `SURASURA_NO_UI_TIMERS`, as the Tk timer."""
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        with self.lock:
            if self.closed:
                return
            if self._check_timer is not None:
                self._check_timer.cancel()

            def ring():
                self.worker.put(self.check, timer)
            timer = self._check_timer = self.timer(CHECK_SETTLE, ring)

    def update_cancelled(self):
        """An update that held everything was cancelled: a Generate it held back asks again."""
        self.worker.put(self.generate.maybe)

    def before_generate(self):
        """A Generate is about to run (the user's too): Anki's backlog read beside it, never waited for."""
        self.worker.put(self.sync.backlog)

    def close(self):
        """No timer, no trigger acting from here on, the worker stopped (a running sync or 順 finishes)."""
        with self.lock:
            self.closed = True
            timers = [self._start_timer, self._check_timer]
            self._start_timer = self._check_timer = None
        for timer in timers:
            if timer is not None:
                timer.cancel()
        self.generate.cancel_alarm()
        self.controller.unsubscribe(self._ended)
        self.worker.close()

    # --- shared inside ------------------------------------------------------------------------------------------ #
    def settings_now(self):
        return self._settings.get()

    def settings_fresh(self):
        """The settings read from the file now, the window's changes not yet written laid over them (the settings
        service's `fresh`; a stand-in without it: `get`). A worker's call."""
        fresh = getattr(self._settings, "fresh", None)
        return fresh() if fresh is not None else self._settings.get()

    def flush(self):
        try:
            self._settings.flush(10.0)          # every reader of settings.json: the newest choice first
        except Exception as e:
            print(f"Automation: the settings couldn't be written first: {e}")

    def check(self, timer=None):
        """(The worker.) The journey asked again (the Generate button's mark), on the controller's worker. `timer`: the
        one that rang — forgotten only if no newer burst armed another meanwhile (HR-21: `close` takes that one back)."""
        with self.lock:
            if timer is None or timer is self._check_timer:
                self._check_timer = None
            if self.closed:
                return
        try:
            self.controller.check(_thaw(self.settings_now()), self.language)
        except Exception as e:
            print(f"Automation: the journey check couldn't start: {e}")

    def thread(self, call, *args):
        """A job's own thread (started by the registry's `start`, which must return at once)."""
        threading.Thread(target=call, args=args, name="automation-job", daemon=True).start()

    def publish(self, **changes):
        """A new state when something in it changed (S19), delivered one at a time and only while it is the newest."""
        with self.lock:
            fresh = self._state._replace(**changes)
            if fresh._replace(seq=self._state.seq) == self._state:
                return
            self._state = fresh._replace(seq=self._state.seq + 1)
            snap = self._state
        with self._deliver:
            with self.lock:
                if snap is not self._state:
                    return
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception as e:
                    print(f"Automation: a listener failed: {e}")

    def _read_known(self):
        language = self.language
        try:
            from app import anki_sync
            known = anki_sync.count_known(language)
        except Exception as e:
            print(f"Automation: the known words couldn't be counted: {e}")
            return
        self.publish(language=language, known=known)

    def _ended(self, run, outcome):
        """A Generate ended (the controller's `on_end`): 順 forced after one that wrote the list (the Tk Generate's
        `on_complete`), and a waiting automatic Generate asked again."""
        if self.closed:
            return
        if outcome == "current":
            self.worker.put(self.junban.maybe, True)
        self.worker.put(self.generate.ended, run.language, outcome, getattr(run.job, "started_at", None))

    def _jobs_changed(self, views):
        if not self.closed:
            self.generate.jobs_changed(views)
