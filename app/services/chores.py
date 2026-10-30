"""The window's chores (W3.5 row 6), Qt-free: what the Tk dashboard does at start, on focus and at close besides the
sync and Generate — Koe's speech helper (`apply_koe_state`), the indexer (`_maybe_launch_indexer`, `_index_needed`),
the library store's helper (`_maybe_maintain`, `_schedule_maintain`, `maintain_at_close`), the Rarity tables' warm-up
(`_prepare_preview`), the install note (`_write_install_note`, K100), surasura.json (`_refresh_tools_entry`,
09-hato-layer §3) and Connect's notices (`_arrivals_notice`, `notice.at_close`).

- **The triggers are the window's calls** and return at once: `started()`, `activated()`, `language_changed(lang)`,
  `koe_changed()` (the switch moved), `index(force)` (the automation service's, when Anki brought words and no
  Generate started). Every file, store or module read runs on the service's one worker, in the order asked.
- **Each one as the Tk dashboard runs it**, the same switches turning it off: the indexer never under
  `SURASURA_NO_AUTOINDEX`, at most every 2 s unless forced, never two (a `indexer` job: never beside Generate, which
  writes the same store); its start 1.5 s on, the store's helper 1.5 s on and 2 s after the last focus or language
  switch, Connect's notice at 2.5 s and the warm-up at 3 s — none of them under `SURASURA_NO_UI_TIMERS` (testing.md §5.4).
- **Child processes** start with `subprocess` and `build_subprocess_env` (never QProcess) and are jobs: the indexer a
  gated `indexer` job (stopped when the window quits), the store's helper a recorded `library-maintain` job (detached:
  it outlives the window, Library_Store_Spec §6.7). Koe's helper is in-process and never ends: a server this service
  owns (not a job), started and stopped on the worker, stopped at `close()`.
- `state()` / `subscribe`: Connect's line (*N arrived while Surasura was closed*) and Koe's port, delivered when they
  change. `on_indexed(cb)`: `cb(language)` after each indexer run (the Rarity numbers' refresh).

`close()` is the window's close, after the window is gone (it waits: a worker's call or the process's last one): Koe
stopped, Connect's `at_close`, and the store's close trigger for each language (`close_store`, which the window's
quit runs apart: `close(store=False)` first, the trigger once the single-instance claim is let go).
"""
import importlib
import os
import subprocess
import sys
import threading
import time
from collections import namedtuple

from app.services import jobs as jobs_module
from app.services.automation import Worker, start_timer

INDEX_EVERY = 2.0           # _maybe_launch_indexer: FocusIn fires for every widget
START_INDEX = 1.5           # root.after(1500, lambda: self._maybe_launch_indexer(force=True))
START_MAINTAIN = 1.5        # root.after(1500, self._maybe_maintain)
MAINTAIN_SETTLE = 2.0       # _schedule_maintain: 2 s after the last trigger
ARRIVALS_AT = 2.5           # root.after(2500, self._arrivals_notice)
FROM_FOLDERS_EVERY = 60.0   # W3.2 P0: a fresh language's store built from its folders at most this often
# The Rarity tables' warm-up (`_prepare_preview`): the Tk window starts it as it opens; here once the start's own work
# is done (the duties made and started, the indexer's and the helper's checks at 1.5 s, Connect's notice at 2.5 s). At
# once it ran beside that work and the first paint of the duties' controls: ~0.25 s of a worker's CPU on Python's one
# lock made the window's thread wait 45 + 130 ms on the desktop (the start-light fix, 2026-10-14).
WARM_AT = 3.0
INDEX_LABEL = "Indexing"
MAINTAIN_LABEL = "Tidying your library"
LOG_NAME = "indexer-window.log"

State = namedtuple("State", "notice koe_port seq")


def index_needed(language, script):
    """Would the indexer have anything to do for `language` (the Tk `_index_needed`)? Stat-only, no tokenizer; False
    when it can't tell. A worker's call."""
    try:
        from app import token_index
        from app.indexer import _content_files, token_store_lists
        from app.path_utils import get_data_path, get_user_files_path
        data_dir = get_data_path(language)
        files, more = token_store_lists(language, data_dir, _content_files(data_dir, language))
        if files is None:
            return False                # the library's lists can't be read now: the next check tells
        store = token_index.open_store(language)
        try:
            known_file = os.path.join(get_user_files_path(language), "KnownWord.json")
            # needs_reconcile is stat-only, so a tokenizer change (the Chinese script) alone would never re-index:
            # the identity the store was built with is compared too.
            return bool(store.needs_reconcile(files, **more)
                        or store.get_meta("build_sig") != token_index.build_signature(language, script=script)
                        or store.get_cached_known(token_index.known_signature(known_file, script)) is None)
        finally:
            store.close()
    except Exception:
        return False


def indexer_command(language):
    """The indexer's process command: the frozen app's `index` verb, or the script (`run_command_async`'s map)."""
    from app.path_utils import is_frozen
    if is_frozen():
        return [sys.executable, "index", "--language", language]
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [sys.executable, os.path.join(app_dir, "indexer.py"), "--language", language]


class Chores:
    """One per window. `registry`: the window's job registry; `settings`: the settings service (`get()`, `set(changes)`,
    `flush(timeout)`); `language`: the one open. `update_staged()`: an update waits (default `updater.children_held`):
    no indexer starts. `clock`, `timer(delay, call)`, `popen`, `needed(language, script)`: a test's stand-ins (defaults
    `time.monotonic`, `automation.start_timer`, `subprocess.Popen`, `index_needed`)."""

    def __init__(self, registry, settings, language, update_staged=None, clock=None, timer=None, popen=None,
                 needed=None, log_folder=None):
        self.registry = registry
        self._settings = settings
        self.language = language or "ja"
        self._clock = clock or time.monotonic
        self._timer = timer if timer is not None else start_timer
        self._popen = popen if popen is not None else subprocess.Popen
        self._needed = needed or index_needed
        if update_staged is None:
            from app import updater
            update_staged = updater.children_held
        self._update_staged = update_staged
        if log_folder is None:
            try:
                from app.path_utils import get_local_data_path
                log_folder = os.path.join(get_local_data_path(), "logs")
            except Exception:
                log_folder = None
        self._log_folder = log_folder
        self._lock = threading.RLock()
        self._deliver = threading.RLock()
        self.worker = Worker("chores")
        self._closed = False
        self._timers = []
        self._maintain_timer = None
        self._last_index = float("-inf")
        self._indexing = False          # from the check until the indexer's end: never two
        self._again = False             # a forced ask came while it ran: one more run at its end, never lost
        self._proc = None
        self._handed = {}               # the store copy's stat last handed to a helper, per language
        self._from_folders = {}         # when a fresh language's build from its folders was last asked, per language
        self._state = State(None, None, 0)
        self._subscribers = []
        self._indexed = []

    # --- reading ------------------------------------------------------------------------------------------------ #
    def index_log(self):
        """The indexer's log of its newest run (setup's load screen reads its count there), or None (no log kept)."""
        return os.path.join(self._log_folder, LOG_NAME) if self._log_folder else None

    def indexing(self):
        """Whether an index ask is under way — its check, its run, or a forced ask waiting for the next (setup's load
        screen: idle, its words step is over, whatever the reason no run came)."""
        with self._lock:
            return self._indexing or self._again

    def state(self):
        with self._lock:
            return self._state

    def subscribe(self, callback):
        """`callback(State)` when Connect's line or Koe's port changed, on the worker's thread."""
        with self._lock:
            self._subscribers.append(callback)

    def on_indexed(self, callback):
        """`callback(language)` after each indexer run, on its thread."""
        with self._lock:
            self._indexed.append(callback)

    # --- the window's triggers (each returns at once) ------------------------------------------------------------ #
    def started(self):
        """The window opened: the install note, surasura.json, Koe as the settings say, and — unless timers are off —
        the indexer and the store's helper 1.5 s on, Connect's notice 2.5 s on, the Rarity tables' warm-up 3 s on."""
        self.worker.put(self._install_note)
        self.worker.put(self._tools_entry)
        self.worker.put(self._koe)
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        self._later(START_INDEX, lambda: self.index(force=True))
        self._later(START_MAINTAIN, lambda: self.worker.put(self._maintain))
        self._later(ARRIVALS_AT, lambda: self.worker.put(self._arrivals))
        self._later(WARM_AT, lambda: self.worker.put(self._prepare_preview))

    def activated(self):
        """The window came back into focus: the indexer (2 s throttle), the store's helper (2 s after the last)."""
        self.index()
        self._schedule_maintain()

    def language_changed(self, language):
        """A switch points at another store: re-index that language, and its store's helper."""
        with self._lock:
            self.language = language or "ja"
        self.index(force=True)
        self._schedule_maintain()

    def koe_changed(self):
        """The speech switch moved (or its settings): start or stop the helper to match."""
        self.worker.put(self._koe)

    def index(self, force=False):
        """Keep the token store fresh (`_maybe_launch_indexer`): a stat-only check on the worker, then the indexer as
        an `indexer` job when there is work. None when asked, else why not. A forced ask while one runs (from its
        check to its end) is *busy* but remembered: the check runs once more when that one ends, however many came."""
        if os.environ.get("SURASURA_NO_AUTOINDEX"):
            return "off"
        with self._lock:
            if self._closed or self._indexing:
                if force and not self._closed:
                    self._again = True
                return "busy"
            now = self._clock()
            if not force and now - self._last_index < INDEX_EVERY:
                return "throttled"
            self._last_index = now
            self._indexing = True
            language = self.language
        if not self.worker.put(self._index_check, language):
            with self._lock:
                self._indexing = False
            return "closed"
        return None

    def halt(self):
        """The quit began (the window may stay up a while for a write to end): the start-up timers taken back and
        nothing more started from here — no store helper, no Connect notice, no indexer. `close()` still runs the rest
        at the end."""
        with self._lock:
            self._closed = True
            timers, self._timers = self._timers, []
            maintain, self._maintain_timer = self._maintain_timer, None
        for timer in timers + ([maintain] if maintain is not None else []):
            timer.cancel()

    def close(self, store=True):
        """The window closed (after it is gone: this waits). No timer left, Koe stopped, Connect's `at_close`, then —
        unless `store=False` (the window's quit runs it apart, after the single-instance claim is let go) — the store's
        close trigger (`close_store`)."""
        with self._lock:
            self._closed = True
            timers, self._timers = self._timers, []
            maintain, self._maintain_timer = self._maintain_timer, None
        for timer in timers + ([maintain] if maintain is not None else []):
            timer.cancel()
        self.worker.close()
        self._koe_stop()
        try:
            settings = self._settings.get()
            if settings.get("connect_enabled"):
                from app.connect import notice
                notice.at_close(self.language)
        except Exception as e:
            print(f"Arrivals notice at close: {e}")
        if store:
            self.close_store()

    def close_store(self):
        """The store's close trigger for each language (`maintain_at_close`: in-process, never waits for a helper; an
        export of the copy takes seconds at 100k items: Library_Store_Spec's L3.1 figures, 6.7–14.5 s)."""
        try:
            from app import library_store
            for language in ("ja", "zh"):
                try:
                    library_store.maintain_at_close(language)
                except Exception as e:
                    print(f"Library store ({language}) at close: {e}")
        except Exception:
            pass

    # --- inside: timers ----------------------------------------------------------------------------------------- #
    def _later(self, delay, call):
        with self._lock:
            if self._closed:
                return
            self._timers.append(self._timer(delay, call))

    def _schedule_maintain(self):
        """The store's helper 2 s after the last trigger: one check for a burst (Library_Store_Spec §6.7)."""
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        with self._lock:
            if self._closed:
                return
            if self._maintain_timer is not None:
                self._maintain_timer.cancel()
            self._maintain_timer = self._timer(MAINTAIN_SETTLE, lambda: self.worker.put(self._maintain))

    # --- inside: the indexer ------------------------------------------------------------------------------------ #
    def _index_check(self, language):
        """(The worker.) The stat-only check, then the job. Whatever fails before the job is made (the script, the
        settings, the update's flag) leaves nothing busy: the next trigger asks again (HR-11)."""
        submitted = False
        try:
            from app.zh_script import effective
            script = effective(language, self._settings.get().get("zh_script", "asis"))
            try:
                need = self._needed(language, script)
            except Exception:
                need = False
            if need and not self._update_staged() and not self._closed:
                self.registry.submit("indexer", INDEX_LABEL, automatic=True, on_quit="cancel",
                                     start=lambda job: threading.Thread(target=self._run_indexer, args=(job, language),
                                                                        name="chores-indexer", daemon=True).start(),
                                     cancel=self._cancel_indexer)
                submitted = True
        finally:
            if not submitted and self._not_busy():
                self.index(force=True)

    def _run_indexer(self, job, language):
        """(The job's thread.) The indexer as a child process, to its end."""
        returncode, message, log = None, None, None
        try:
            from app.path_utils import build_subprocess_env, is_frozen
            env = build_subprocess_env(is_frozen())
            if self._log_folder:
                os.makedirs(self._log_folder, exist_ok=True)
                log = open(os.path.join(self._log_folder, LOG_NAME), "w", encoding="utf-8")
            flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
            from app.connect.power import popen_below_normal            # a7: below the window, its pools too
            proc = popen_below_normal(indexer_command(language), popen=self._popen, stdin=subprocess.DEVNULL,
                                      stdout=log if log is not None else subprocess.DEVNULL,
                                      stderr=subprocess.STDOUT, env=env, creationflags=flags)
            with self._lock:
                self._proc = proc
                stop = job.cancelled
            job.started_process(getattr(proc, "pid", None))     # the update's wait list: this job's row alone
            if stop:
                proc.terminate()
            returncode = proc.wait()
        except Exception as e:
            message = f"The indexer couldn't be started: {e}"
            print(message)
        finally:
            if log is not None:
                log.close()
            with self._lock:
                self._proc = None
            again = self._not_busy()
            if returncode not in (0, None) and message is None:
                message = f"Indexing ended (exit code {returncode})"
            job.finish(ok=returncode == 0, message=message, cancelled=job.cancelled)
        if returncode is not None:
            with self._lock:
                listeners = list(self._indexed)
            for callback in listeners:
                try:
                    callback(language)
                except Exception as e:
                    print(f"Chores: an indexer listener failed: {e}")
        if again:
            self.index(force=True)

    def _not_busy(self):
        """The check found nothing, or the indexer ended: nothing busy. -> whether a forced ask came meanwhile (taken:
        the caller asks once more)."""
        with self._lock:
            self._indexing = False
            again, self._again = self._again and not self._closed, False
        return again

    def _cancel_indexer(self, job):
        """The registry's cancel (a quit, or a cancel before it started): the child stopped; nothing left busy, and no
        follow-up run (a forced ask remembered before the cancel goes with it)."""
        with self._lock:
            proc = self._proc
            self._again = False
            if job.state == jobs_module.DONE:
                self._indexing = False      # ended before it started: its thread never runs
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception as e:
                print(f"Chores: the indexer couldn't be stopped: {e}")

    # --- inside: the other chores (the worker) ------------------------------------------------------------------- #
    def _install_note(self):
        try:
            from app import path_utils
            path_utils.write_install_note()
        except Exception as e:
            print(f"Install note: {e}")

    def _tools_entry(self):
        """surasura.json in the shared tools folder (09-hato-layer §3): how hato finds Surasura, Connect on or off. A
        failure is only printed (a source checkout writes it only with SURASURA_TOOLS_CLI)."""
        try:
            from app import tools_entry
            tools_entry.refresh()
        except Exception as e:
            print(f"surasura.json: {e}")

    def _prepare_preview(self):
        try:
            from app import token_index
            from app.path_utils import get_user_files_path
            token_index.prepare_preview(self.language, get_user_files_path(self.language))
        except Exception:
            pass

    def _maintain(self):
        """The store's helper when it has something to do (`_maybe_maintain`): no store yet but a manifest to build
        from, a change since the last export, or a copy someone else rewrote (once per new stat)."""
        language = self.language
        if self._closed:
            return                              # a timer that rang as the quit began: no helper for a closing window
        try:
            from app import library_store
            from app.path_utils import get_data_path, get_user_files_path
            data_dir, user_files_dir = get_data_path(language), get_user_files_path(language)
            mode, _reason = library_store.check_mode(language, data_dir, busy_wait=0.0)
            if mode == "json":
                proc = library_store.spawn_build_if_waiting(language, data_dir, user_files_dir)
                if proc is None and self._fresh(library_store, language, data_dir, user_files_dir):
                    proc = library_store.spawn_maintain(language, "--from-folders")
                self._watch(proc)
                return
            if mode != "store":
                return
            store = library_store.open_store(language, data_dir, user_files_dir, role="window", busy_wait=0.0)
            if store is None:
                return
            with store:
                due, seen = library_store.maintain_due(store, self._handed.get(language, ""))
            if due:
                proc = library_store.spawn_maintain(language)
                if proc is not None:              # None while an update is staged: not handed on, asked again (HR-24)
                    self._handed[language] = seen
                self._watch(proc)
        except Exception as e:
            print(f"Library store helper check: {e}")

    def _fresh(self, library_store, language, data_dir, user_files_dir):
        """(W3.2 P0, IK0-2) A language with no store and no manifest at all — a fresh install, or a language never
        opened: the helper builds its store from the tiers' folders (`--from-folders`, as the Content Manager's open
        does), so the window reaches its empty state and takes a drop. Never over a manifest (that one is built from,
        `spawn_build_if_waiting`) nor a store file (being migrated, or failed: its own path); at most once a minute
        per language (the build trigger's rule)."""
        if os.path.exists(library_store.manifest_path(user_files_dir)) or \
                os.path.exists(library_store.library_db_path(language, data_dir)):
            return False
        now = self._clock()
        if now - self._from_folders.get(language, -FROM_FOLDERS_EVERY) < FROM_FOLDERS_EVERY:
            return False
        self._from_folders[language] = now
        return True

    def _watch(self, proc):
        """A detached helper (`spawn_maintain`'s Popen) listed as a job until it ends; quitting leaves it running —
        unless the close's *Stop and quit* cancels it (row 35, `jobs.STOPPABLE_AT_QUIT`): ended through this Popen,
        whose open handle keeps its pid from being reused, and alone (`maintain` starts no child; a kill mid-way
        rolls its transaction back)."""
        if proc is None:
            return
        lock = threading.Lock()

        def stop(_job):
            with lock:
                if proc.poll() is None:
                    proc.kill()
        job = self.registry.record("library-maintain", MAINTAIN_LABEL, cancel=stop, on_quit="detach")
        job.started_process(getattr(proc, "pid", None))     # the update's wait list: this job's row alone

        def wait():
            try:
                returncode = proc.wait()
            except Exception:
                returncode = None
            job.finish(ok=True, message=None if returncode == 0 else f"exit code {returncode}")
        threading.Thread(target=wait, name="chores-maintain", daemon=True).start()

    def _arrivals(self):
        """With Connect's preview on: what another program registered while Surasura was closed, named once."""
        if self._closed or not self._settings.get().get("connect_enabled"):
            return
        try:
            from app.connect import notice
            line = notice.at_open(self.language)
        except Exception as e:
            print(f"Arrivals notice: {e}")
            return
        if line:
            self._publish(notice=line)

    def _koe(self):
        """(The worker: `stop` may wait 2 s.) Koe's helper to match the switch (`apply_koe_state`): started when
        revealed and on, stopped when off; the module absent: nothing. A server this service owns, never a job (it
        never ends: the bar's line would never stop), and nothing written to settings.json (the Tk load's promotion of
        `source_display` is not ported: nothing automatic writes settings)."""
        try:
            koe = importlib.import_module("modules.koe")
        except Exception:
            return
        try:
            on = bool(koe.is_revealed()) and bool(self._settings.get().get("enable_koe"))
        except Exception:
            on = False
        if not on or self._closed:
            self._koe_stop(koe)
            return
        try:
            self._settings.flush(10.0)        # the helper reads settings.json itself
        except Exception:
            pass
        try:
            port = koe.start_server(None)     # idempotent: a running helper answers its port
        except Exception as e:
            print(f"Warning: could not change the speech helper state: {e}")
            port = None
        self._publish(koe_port=port)

    def _koe_stop(self, koe=None):
        """The helper stopped, its port let go (idempotent; a worker's call or the close's)."""
        if koe is None:
            try:
                koe = importlib.import_module("modules.koe")
            except Exception:
                return
        try:
            koe.stop_server()
        except Exception as e:
            print(f"Koe: the helper couldn't be stopped: {e}")
        self._publish(koe_port=None)

    def _publish(self, **changes):
        with self._lock:
            fresh = self._state._replace(**changes)
            if fresh._replace(seq=self._state.seq) == self._state:
                return
            self._state = fresh._replace(seq=self._state.seq + 1)
            snap = self._state
        with self._deliver:
            with self._lock:
                if snap is not self._state:
                    return
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception as e:
                    print(f"Chores: a listener failed: {e}")
