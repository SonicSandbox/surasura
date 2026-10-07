"""The Generate controller (W1.3; the window's spec 04 §4.2): whether the journey is current, and running Generate.

States (the consult's): `idle` (nothing known yet) · `current` · `stale` · `queued` (asked for; waiting for the
requests to settle, for a job it can't run beside, or for another program's Generate) · `running` (with its progress)
· `cancelling` · `failed` (with a message and the log's path — never a dialog).

- `check(settings, language)` asks `analyzer.journey_is_current` on a worker (it syncs the library first and stats
  every file: never a window's thread) and moves `idle` / `current` / `stale`.
- `request(...)` builds the analyzer's argv with `run_args.analyzer_args` (one builder: the command line's run
  signature) plus `--progress-json`, and coalesces: one run once the requests stop for `settle` seconds; a request
  during a run runs once after it, or cancels it and runs after when the caller says so (`restart`, E3.2's burst rule).
  A user's request while an automatic run still waits takes its place. The run is a `generate` job in the registry
  (`app/services/jobs.py`: never beside the indexer, never two).
- The run waits on a worker until `results` is free (`locks.take("results", …, wait=None, cancel=…)`): a cancel, or
  the window closing, while it waits drops the request with nothing started (P1.2 left this cancel to W1.3). It lets go
  and starts the analyzer, which takes `results` itself (`SURASURA_RESULTS_WAIT=forever`: in the moment between, another
  program's Generate may take it, and the analyzer waits its turn).
- **Cancel during a run** is the run's own decision: the controller makes the run's cancel file
  (`SURASURA_CANCEL_FILE`), and the analyzer
  stops at its next step if it hasn't reached *Writing your list* (the CSV writes aren't atomic: P1.2 deferred that),
  else finishes. Only the run knows which step it is in — the reader always trails it — so the controller never ends
  the child itself. A run started without `--progress-json` (the Tk dashboard's) can't be asked: a cancel waits for its
  end. A cancelled run leaves the last journey's files as they were; the analyzer dropped its stamp as it started, so
  the journey reads `stale` and the next Generate runs it again.
- Children are started with `subprocess` and read on a reader thread (§4.1: no QProcess, headless in tests), with the
  environment from `path_utils.build_subprocess_env`. A window that starts the child its own way (the Tk dashboard:
  its log, spinner and update wait) hands `request` a `launcher` and reports the end through the run (`Run.ended`).

Nothing here waits on the caller's thread. Listeners (`subscribe`, a request's `on_wait`) run on the controller's
workers or the reader's thread, one at a time and in order (an older state is never delivered after a newer one); a
window posts them to its own queue.
"""
import os
import subprocess
import sys
import threading
import time
from collections import namedtuple

from app import locks
from app.services import jobs as jobs_module
from app.services import progress as progress_module

IDLE, CURRENT, STALE, QUEUED, RUNNING, CANCELLING, FAILED = (
    "idle", "current", "stale", "queued", "running", "cancelling", "failed")
STEPS = ("Reading your files", "Counting words", "Picking sentences", "Writing your list", "Writing the journey")
LOG_NAME = "generate-window.log"
PROGRESS_FLAG = "--progress-json"

State = namedtuple("State", "state step done total message log_path job_id seq")


class _Either:
    """Two cancel events as one, for `locks.take(cancel=…)`: set when either is."""

    def __init__(self, first, second):
        self.first, self.second = first, second

    def is_set(self):
        return self.first.is_set() or (self.second is not None and self.second.is_set())

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                return False
            self.first.wait(0.05 if left is None else min(0.05, left))
        return True


def command_line(argv):
    """The analyzer's process command for `argv` (`['analyzer.py', …]`): the frozen app's own verb, or the script."""
    from app.path_utils import is_frozen
    if is_frozen():
        return [sys.executable, "analyzer"] + list(argv[1:])
    return [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analyzer.py")] \
        + list(argv[1:])


class Run:
    """One Generate on its way: its argv, its job, and what its launcher reports (`started`, `feed`, `ended`)."""

    def __init__(self, controller, argv, language, quiet, on_wait, cancel_event, launcher, inline):
        self.controller = controller
        self.argv = argv
        self.language = language
        self.quiet = quiet
        self.on_wait = on_wait
        self.cancel_event = threading.Event()
        self.external_cancel = cancel_event
        self.launcher = launcher
        self.inline = inline
        self.job = None
        self.proc = None
        self.step = None                   # the newest step the child printed (as read: it trails the child)
        self.begun = False                 # the registry let it start
        self.launched = False              # the child was asked to start
        self.cancel_asked = False
        self.cancel_sent = False
        self.cancel_file = None            # the file that asks the child to stop (`_spawn` names it)
        self.done = False
        self.dropped = False
        self.final = None
        self.lock = threading.Lock()
        self.coalescer = progress_module.Coalescer(self._update, on_final=self._final, on_text=self._text)

    @property
    def can_be_asked(self):
        """Whether the child takes a cancel (it was started with the progress flag)."""
        return PROGRESS_FLAG in self.argv

    # --- what a launcher reports -------------------------------------------------------------------------------- #
    def started(self, proc):
        """The child is running (its Popen)."""
        with self.lock:
            self.proc = proc
            if self.cancel_asked:
                self._ask_to_stop()

    def feed(self, line):
        """One line of the child's stdout."""
        kind, value = progress_module.parse(line)
        if kind == "progress":
            with self.lock:
                self.step = value.step
        self.coalescer.feed(line)

    def ended(self, returncode):
        """The child ended (`returncode`; None when it never started). Only the first report counts."""
        with self.lock:
            if self.done:
                return
            self.done = True
        self.coalescer.end()
        self.controller._ended(self, returncode)

    # --- inside ------------------------------------------------------------------------------------------------- #
    def _ask_to_stop(self):
        """Make the child's cancel file (inside `self.lock`): it stops if it can, before writing anything."""
        if self.cancel_sent or self.proc is None or not self.can_be_asked or not self.cancel_file:
            return
        try:
            with open(self.cancel_file, "w", encoding="utf-8") as f:
                f.write("cancel\n")
            self.cancel_sent = True
        except OSError:
            pass                            # the folder is gone: the run finishes, its own end says how

    def _update(self, update):
        self.controller._progress(self, update)

    def _final(self, kind, record):
        self.final = (kind, record)

    def _text(self, line):
        self.controller._text(self, line)


class GenerateController:
    """One per window. `registry`: the window's job registry; `closing`: an Event set when the window closes (a run still
    waiting for `results` then starts nothing); `settle`: the burst rule's quiet time (seconds)."""

    def __init__(self, registry=None, closing=None, settle=0.4, log_folder=None):
        self.registry = registry if registry is not None else jobs_module.JobRegistry()
        self.closing = closing
        self.settle = settle
        # Where its log goes, settled now (on the window's start): a run that ends later never works out a path again.
        if log_folder is None:
            try:
                from app.path_utils import get_local_data_path
                log_folder = os.path.join(get_local_data_path(), "logs")
            except Exception:
                log_folder = None
        self._log_folder = log_folder
        self._lock = threading.RLock()
        self._deliver = threading.RLock()  # one delivery at a time (a listener may ask for a run from inside one)
        self._state = State(IDLE, None, None, None, None, None, None, 0)
        self._settled = IDLE            # what a check (or the last run) found: the state to fall back to
        self._run = None                # the run in flight (waiting, or its child running)
        self._pending = None            # the request that runs next
        self._timer = None
        self._subscribers = []
        self._text_listeners = []

    # --- reading ------------------------------------------------------------------------------------------------ #
    def state(self):
        with self._lock:
            return self._state

    def subscribe(self, callback):
        """`callback(State)` after every change, in order."""
        with self._lock:
            self._subscribers.append(callback)

    def on_text(self, callback):
        """`callback(line)` for every text line the child prints (a window's log)."""
        with self._lock:
            self._text_listeners.append(callback)

    def log_path(self):
        """The window's Generate log (`<local data>/logs/generate-window.log`; None when it has no folder)."""
        return os.path.join(self._log_folder, LOG_NAME) if self._log_folder else None

    # --- the journey check -------------------------------------------------------------------------------------- #
    def check(self, settings, language, then=None):
        """Is the journey current? Asked on a worker; the state moves to `current` / `stale` (or `idle` when it
        can't tell) unless a run is in flight. `then(answer)` after, on that worker."""
        def work():
            from app import analyzer, run_args
            try:
                answer = analyzer.journey_is_current(run_args.analyzer_args(settings, language), language)
            except Exception as e:
                print(f"Generate: the journey check failed: {e}")
                answer = None
            with self._lock:
                self._settled = {True: CURRENT, False: STALE}.get(answer, IDLE)
                if self._run is None and self._pending is None:
                    snap = self._assign(self._settled)
                else:
                    snap = None
            self._send(snap)
            if then is not None:
                then(answer)
        threading.Thread(target=work, name="generate-check", daemon=True).start()

    # --- asking for a run --------------------------------------------------------------------------------------- #
    def request(self, language, settings=None, argv=None, quiet=False, restart=False, settle=None, launcher=None,
                on_wait=None, cancel_event=None, inline=False):
        """Ask for a Generate. `argv` (`['analyzer.py', …]`) or `settings` (settings.json's shape) say what to run;
        `quiet`: automatic, written not opened. `launcher(run)`: start the child another way (else this controller
        spawns and reads it). `on_wait(holder)`: once, if another program's Generate holds `results`.
        `cancel_event`: another Event that also drops the run while it waits (the window's closing). `inline`: take a
        free `results` lock and launch on this thread (a test harness with no queue to drain). Returns at once."""
        if argv is None:
            from app import run_args
            argv = run_args.analyzer_args(settings or {}, language)
            argv = argv + [PROGRESS_FLAG] + (["--no-open"] if quiet else [])
        if not isinstance(cancel_event, threading.Event):
            cancel_event = self.closing if isinstance(self.closing, threading.Event) else None
        run = Run(self, list(argv), language, quiet, on_wait, cancel_event, launcher, inline)
        snap = None
        with self._lock:
            self._pending = run
            in_flight = self._run
            if in_flight is not None and not quiet and in_flight.quiet and not in_flight.launched:
                restart = True              # an automatic run still waiting: the user's takes its place
            if in_flight is None:
                snap = self._assign(QUEUED)
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._send(snap)
        if in_flight is not None:
            if restart:
                self._cancel(in_flight)
            return run
        delay = self.settle if settle is None else settle
        if delay <= 0:
            self._launch_pending()
        else:
            with self._lock:
                self._timer = threading.Timer(delay, self._launch_pending)
                self._timer.daemon = True
                self._timer.start()
        return run

    def cancel(self):
        """Cancel what is asked for: a request still settling is dropped; the run in flight is cancelled (dropped
        while it waits; asked to stop before *Writing your list*; else it finishes)."""
        snap = None
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            dropped, self._pending = self._pending, None
            run = self._run
            if run is None and dropped is not None:
                snap = self._assign(self._settled)
        self._send(snap)
        if run is not None:
            self._cancel(run)

    # --- inside: starting --------------------------------------------------------------------------------------- #
    def _cancel(self, run):
        """Cancel `run` whatever its stage: through its job once it has one (the registry tells `_cancel_run`)."""
        run.cancel_event.set()
        job = run.job
        if job is not None:
            job.cancel()
        # else: the job is being made (`_launch_pending`): it sees the event as it starts

    def _launch_pending(self):
        with self._lock:
            self._timer = None
            if self._run is not None or self._pending is None:
                return
            run, self._pending = self._pending, None
            self._run = run
        label = "Generating (automatic)" if run.quiet else "Generating"

        def begin(job):
            run.job = job                   # the registry may start it inside submit(): the run knows its job first
            run.begun = True
            if run.cancel_event.is_set():
                self._dropped(run)          # cancelled before it could start: nothing runs
                return
            self._begin(run)
        job = self.registry.submit("generate", label, start=begin, cancel=lambda job: self._cancel_run(run),
                                   automatic=run.quiet, on_quit="cancel")
        run.job = job
        if run.cancel_event.is_set() and job.state in (jobs_module.QUEUED, jobs_module.WAITING):
            job.cancel()                    # cancelled while the job was being made
        elif job.state == jobs_module.WAITING:
            self._set(QUEUED, message=job.reason)

    def _begin(self, run):
        """The registry let it start: wait for `results` (a worker), then launch."""
        if run.inline:
            try:
                with locks.take("results", "Generate (waiting)"):
                    pass
            except locks.Busy:
                threading.Thread(target=self._wait_then_launch, args=(run,), daemon=True).start()
                return
            except Exception:
                pass                        # the lock can't be read here: the analyzer decides
            self._launch(run)
            return
        threading.Thread(target=self._wait_then_launch, args=(run,), name="generate-wait", daemon=True).start()

    def _wait_then_launch(self, run):
        try:
            if locks.read_holder("results") is None and locks.unopenable("results"):
                pass                        # no program to wait for: the analyzer's own take says why (its log)
            else:
                with locks.take("results", "Generate (waiting)", wait=None,
                                cancel=_Either(run.cancel_event, run.external_cancel),
                                on_wait=lambda holder: self._waiting(run, holder)):
                    pass
        except locks.Cancelled:
            self._dropped(run)
            return
        except Exception:
            pass                            # the lock can't be read here: the analyzer decides
        self._launch(run)

    def _waiting(self, run, holder):
        verb = (holder or {}).get("verb") or "another Generate"
        self._set(QUEUED, message=f"Waiting for {verb} to finish")
        if run.on_wait is not None:
            run.on_wait(holder)

    def _launch(self, run):
        with run.lock:
            stop = run.cancel_event.is_set() or (run.external_cancel is not None and run.external_cancel.is_set())
            if not stop:
                run.launched = True
        if stop:
            self._dropped(run)
            return
        self._set(RUNNING, job_id=run.job.id)
        try:
            (run.launcher or self._spawn)(run)
        except Exception as e:
            print(f"Generate: the analyzer couldn't be started: {e}")
            run.ended(None)

    def _spawn(self, run):
        """Start the analyzer and read it on a reader thread (the headless / Qt path)."""
        from app.path_utils import build_subprocess_env, is_frozen
        env = build_subprocess_env(is_frozen())
        env["SURASURA_RESULTS_WAIT"] = "forever"
        import tempfile
        folder = self._log_folder or tempfile.gettempdir()
        os.makedirs(folder, exist_ok=True)
        run.cancel_file = os.path.join(folder, f"generate-cancel-{os.getpid()}-{id(run)}.flag")
        env["SURASURA_CANCEL_FILE"] = run.cancel_file
        flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
        proc = subprocess.Popen(command_line(run.argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                env=env, creationflags=flags)
        run.started(proc)

        def read():
            log = None
            try:
                log = open(self.log_path() or os.devnull, "w", encoding="utf-8")
            except OSError:
                log = None
            try:
                for line in proc.stdout:
                    if log is not None:
                        log.write(line)
                    run.feed(line)
            finally:
                if log is not None:
                    log.close()
                proc.wait()
                try:
                    os.remove(run.cancel_file)
                except OSError:
                    pass
                run.ended(proc.returncode)
        threading.Thread(target=read, name="generate-reader", daemon=True).start()

    # --- inside: cancelling and ending -------------------------------------------------------------------------- #
    def _cancel_run(self, run):
        """The registry's cancel for the run's job (a cancel, the window quitting, or another request taking its
        turn): dropped while it hasn't launched; asked to stop once it has."""
        run.cancel_event.set()
        with run.lock:
            run.cancel_asked = True
            launched = run.launched
            if launched:
                run._ask_to_stop()
            asked = run.cancel_sent or (run.proc is None and run.can_be_asked)
        if not launched:
            if not run.begun or run.job is None or run.job.state != jobs_module.CANCELLING:
                self._dropped(run)          # never started, or waiting for the registry: nothing to wait for
            return                          # waiting for `results`: its wait sees the cancel and drops it
        self._set(CANCELLING, job_id=run.job.id,
                  message="Stopping before your list is written" if asked
                  else "Finishing: Generate can't stop part-way here")

    def _dropped(self, run):
        """Cancelled (or the window closed) before the child started: nothing ran."""
        with run.lock:
            if run.dropped:
                return
            run.dropped = True
        if run.job is not None:
            run.job.finish(ok=True, cancelled=True)
        self._after(run, None)

    def _ended(self, run, returncode):
        final = run.final
        if final is not None and final[0] == "error" and final[1].get("code") == "cancelled":
            run.job.finish(ok=True, message="cancelled", cancelled=True)
            self._after(run, STALE)
        elif returncode == 0:
            run.job.finish(ok=True)
            self._after(run, CURRENT)
        else:
            what = "couldn't start" if returncode is None else f"stopped (exit code {returncode})"
            message = f"Generate {what}." + (f" The details are in {self.log_path()}" if self.log_path() else "")
            run.job.finish(ok=False, message=message)
            self._after(run, FAILED, message=message, log_path=self.log_path())

    def _after(self, run, state, message=None, log_path=None):
        """`run` is over (`state`; None: back to what the last check found)."""
        with self._lock:
            if self._run is run:
                self._run = None
            if state in (CURRENT, STALE):
                self._settled = state
            nxt = self._pending
            if nxt is not None:
                snap = self._assign(QUEUED)
            else:
                snap = self._assign(self._settled if state is None else state, message=message, log_path=log_path)
        self._send(snap)
        if nxt is not None:
            self._launch_pending()

    def _progress(self, run, update):
        run.job.progress(update.step, update.done, update.total)
        with self._lock:
            if self._run is not run or self._state.state != RUNNING:
                return                      # over, or cancelling: an update read late never moves the state back
            snap = self._assign(RUNNING, step=update.step, done=update.done, total=update.total, job_id=run.job.id)
        self._send(snap)

    def _text(self, run, line):
        with self._lock:
            listeners = list(self._text_listeners)
        for callback in listeners:
            try:
                callback(line)
            except Exception as e:
                print(f"Generate: a log listener failed: {e}")

    def _set(self, state, step=None, done=None, total=None, message=None, log_path=None, job_id=None):
        with self._lock:
            snap = self._assign(state, step, done, total, message, log_path, job_id)
        self._send(snap)

    def _assign(self, state, step=None, done=None, total=None, message=None, log_path=None, job_id=None):
        """The new state (inside `self._lock`), numbered."""
        self._state = State(state, step, done, total, message, log_path, job_id, self._state.seq + 1)
        return self._state

    def _send(self, snap):
        """Deliver `snap` to the listeners, one delivery at a time, and only while it is still the newest."""
        if snap is None:
            return
        with self._deliver:
            with self._lock:
                if snap.seq != self._state.seq:
                    return
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception as e:                # a listener's fault never stops a Generate
                    print(f"Generate: a listener failed: {e}")
