"""The update service (W3.5 row 1; the window's spec 03 — the update mark — and 04 §4.2): the in-app update, Qt-free.

The Tk dashboard's update flow (`app/main.py`: `check_updates_thread` … `_apply_and_restart`, `reconcile_update_result`)
moved out of the window, its rules called where they live (`update_checker`, `updater`: S3.1's, never copied here):

- `check()` asks GitHub on a worker (`update_checker.get_update_info` → `classify_update` → `updater.effective_class`
  with the inputs the Tk check passes: the skip, `auto_update_enabled`, `can_auto_apply`, the failed version). Off under
  `SURASURA_NO_UPDATE_CHECK`, as the Tk dashboard's; offline, or nothing new, it changes nothing and says nothing (E18).
- States: `none` · `available` (version, class, the dialog's words, the notes' page; `open_now` once for a critical
  release: the Tk indicator's rule) · `downloading` (done, total, and what already runs) · `waiting` (the programs it
  waits for) · `ready` (handing over: the app quits next) · `failed` (message, the report's path — never a dialog).
- *Skip this version* / *Offer skipped version again* write `skipped_version` alone, through the settings service.
- `start()` (*Update now*) on a worker: the manual fallbacks of `_do_auto_update` / `_do_installer_update`, then
  `take_update_lock` → `hold_children` → `prepare_update` / `prepare_installer` with its progress, while the programs it
  waits for are listed every 300 ms (the Tk poll): `busy()` (the window's own Anki writing: the sync, Junban's
  automatic reorder), the Anki writer lock held in this process, the registry's running jobs (*Stop it* cancels one) and
  `updater.running_children(active())`. An entry whose `stop` is None is waited for, never stopped (the window's own
  work; Connect's row after the P3.1 take-in). While it holds the children, the registry starts no job but
  `FREE_KINDS` (its gate: the Tk `defer_child` / `children_held()` checks); a cancel starts what was held.
  Downloaded and nothing left → the last check (`can_update_now`) → `hold_library_locks` → the install note →
  `arm_and_launch` → `on_quit()`. `stop(key)` is *Stop it* (`stop()`: *Stop all and update now*); `cancel()` (Cancel,
  Esc, closing the sheet) releases what `_cancel_update` / `_end_update` release (the update lock — at once when
  downloaded, else when the download ends, which then discards it — the held children, the staged download); refused
  mid-swap. The update is a job in the registry (`update`: one at a time).
- `reconcile()` at start (`consume_result`): `ok` → the telemetry update event; `failed` → `record_failed_version`,
  `write_report`, a `failed` state and a *Needs you* entry (seen stops counting, stays listed: P1.2-1); `failure()` is
  the newest unseen one as a `StatusService` provider reads a line.

Nothing here waits on the caller's thread: every network call, listing, lock take and download runs on the service's
workers. Subscribers (`subscribe`) hear each new state on those workers, one at a time and in order; a window posts
them to its own queue.
"""
import os
import threading
import time
import webbrowser
from collections import namedtuple

from app import __version__
from app import path_utils
from app import update_checker
from app import updater
from app.services import jobs as jobs_module

NONE, AVAILABLE, DOWNLOADING, WAITING, READY, FAILED = "none", "available", "downloading", "waiting", "ready", "failed"
POLL = 0.3                                  # the Tk `_update_poll`'s period (seconds)
JUNBAN_AUTO = "Junban's automatic reorder"  # a `busy()` name the Anki writer lock's own entry stands in for
RELEASES_PAGE = "https://github.com/SonicSandbox/surasura/releases/latest"
NEEDS_YOU_KEPT = 20
# What still starts while an update waits: the update itself. Every other job — a child process (the arrivals worker
# too: it runs this install's program, IK-19), an Anki write, a sync — waits, as the Tk dashboard's `hold_children` /
# `defer_child` and its `children_held()` checks held them, and starts when the update is cancelled.
FREE_KINDS = ("update",)
HELD_REASON = "waits for the update"
_MB = 1 << 20

Program = namedtuple("Program", "key name can_stop")
Failure = namedtuple("Failure", "text at seen version report")
State = namedtuple("State", "state version cls body notes_url critical open_now done total programs message report "
                            "needs_you updated seq")


def body(cls, info, failed_version=""):
    """What the update sheet says (the Tk `_update_body`). A version whose in-app update already failed is a manual
    download for that reason — it isn't "a larger update"."""
    if cls == "INSTALLER":
        return ("This version installs with its own installer: Surasura closes, the installer starts, "
                "and it brings your library, words and settings with it.")
    if cls == "APP":
        return ("This is a quick in-app update — it refreshes only the program code and "
                "report templates (about 15–20 MB). Your words, data, settings, and file "
                "order are never touched. Surasura will briefly close and reopen.")
    version = getattr(info, "version", "")
    if failed_version and version == failed_version:
        return (f"The in-app update to v{version} didn't finish last time, so this one is a "
                "manual download. Your personal data stays where it is.")
    return ("This is a larger update and should be downloaded manually (it changes more "
            "than the app code). Your personal data stays where it is.")


def percent(state):
    """The download's share, 0–100, or None while its size isn't known (the update mark and sheet, W3.5 row 2)."""
    if not state.total:
        return None
    return min(100, int((state.done or 0) * 100 / state.total))


def report_note(report):
    """The lines naming a saved update report ('' when none could be written): the Tk `_update_report_note`."""
    if not report:
        return ""
    return (" A report was saved to " + report + ". If this keeps happening, please attach it to an issue at "
            "github.com/SonicSandbox/surasura/issues.")


class _Update:
    """One *Update now*, from the click until the hand-over or a cancel (the Tk `job` dict)."""

    def __init__(self, info, cls):
        self.info = info
        self.cls = cls
        self.lock = None                # the update lock, once taken
        self.staged = None
        self.error = None
        self.done = False               # the download ended (well or not)
        self.ended = False              # cancelled, failed or closed: nothing more happens
        self.handing = False            # the hand-over is under way: no cancel now
        self.start_held = True          # what the cancel said: start the children held meanwhile
        self.children = None            # the last listing: [{"pid", "name", "stop"}]
        self.progress = (0, 0)
        self.shown = None               # the progress last reported (percent, or MB when the size is unknown)
        self.message = None
        self.job = None                 # its record in the job registry
        self.downloading = None         # the download's thread, once started (it drops the lock at its end)
        self.wake = threading.Event()   # list again now (a Stop, the download's end, a cancel)


class UpdateService:
    """One per window. `settings`: the settings service; `registry`: the window's job registry; `on_quit()`: close the
    app for the helper (called on a worker). `busy()` -> the window's own Anki writing now (names: "Anki sync",
    `JUNBAN_AUTO`); `active()` -> the window's child processes (Popen objects, `surasura_desc` naming them);
    `open_url(url)`: the browser (a worker's call). `poll`: the wait list's period."""

    def __init__(self, settings, registry, on_quit, busy=None, active=None, open_url=None, poll=POLL):
        self.settings = settings
        self.registry = registry
        self.on_quit = on_quit
        self._busy = busy or (lambda: ())
        self._active = active or (lambda: ())
        self._open_url = open_url or webbrowser.open
        self._poll = poll
        self._lock = threading.RLock()
        self._deliver = threading.RLock()
        self._info = None               # the release on offer
        self._cls = "NONE"
        self._failed_version = ""
        self._surfaced = set()          # critical versions already opened once
        self._needs = []                # Failure, newest first
        self._update = None             # the update in flight (or ending)
        self._checking = False
        self._quitting = False
        self._held_at_quit = False      # closed while an update waited: the jobs it held stay held
        self._updated = None
        self._subscribers = []
        self._state = State(NONE, "", "NONE", "", "", False, False, None, None, (), None, None, (), None, 0)
        registry.gate(self._holds)

    def _holds(self, kind):
        """The registry's gate: while an update holds the children (`updater.children_held`, the Tk `_HOLD`), no job
        but `FREE_KINDS` starts — nor once the window closed mid-update (`quit`: what it held is dropped, never started
        as the window goes, as the Tk `release_children(start=False)`)."""
        if kind in FREE_KINDS:
            return None
        return HELD_REASON if updater.children_held() or self._held_at_quit else None

    # --- reading ------------------------------------------------------------------------------------------------ #
    def state(self):
        with self._lock:
            return self._state

    def subscribe(self, callback):
        """`callback(State)` after every change, in order, on the service's workers."""
        with self._lock:
            self._subscribers.append(callback)

    def skipped(self):
        """Settings' *vX skipped — Offer again*: the skipped version while it is still newer than this one, else ''
        (the Tk `_sync_skipped_row`)."""
        version = str(self.settings.get().get("skipped_version", "") or "")
        try:
            if version and update_checker.parse_version(version) > update_checker.parse_version(__version__):
                return version
        except Exception:
            pass
        return ""

    # --- at start ----------------------------------------------------------------------------------------------- #
    def begin(self):
        """The window opened: on a worker, the last update's outcome (`reconcile`, after the Tk dashboard's timers:
        off under `SURASURA_NO_UI_TIMERS`), then the check (off under `SURASURA_NO_UPDATE_CHECK`) — in that order, so a
        version that just failed is never offered in place again."""
        def work():
            if not os.environ.get("SURASURA_NO_UI_TIMERS"):
                self.reconcile()
            self.check(now=True)
        threading.Thread(target=work, name="update-begin", daemon=True).start()

    def reconcile(self):
        """The outcome of an update applied since the last run (the Tk `reconcile_update_result`): reads and clears its
        files, so a worker's call. -> "none" · "ok" · "failed"."""
        try:
            res = updater.consume_result()
        except Exception:
            res = None
        if not res:
            return "none"
        if res.get("status") == "success":
            try:
                from app import telemetry
                telemetry.send_update_event(res.get("from") or res.get("to") or "")
            except Exception:
                pass
            with self._lock:
                self._updated = __version__
                snap = self._assign(self._state.state, keep=True)
            self._send(snap)
            return "ok"
        # Failed or interrupted: never tried in place again (its own mark, not a skip: still offered, as a download).
        version = res.get("to") or ""
        if version:
            with self._lock:
                self._failed_version = version
            updater.record_failed_version(version)
        reason = res.get("reason", "")
        report = updater.write_report("install", reason, to_version=version, from_version=res.get("from") or "")
        detail = f" ({reason})" if reason else ""
        self._fail(None, f"The automatic update didn't finish{detail}." + report_note(report), report, version)
        return "failed"

    # --- the check ---------------------------------------------------------------------------------------------- #
    def check(self, now=False):
        """Ask whether a newer release is on offer: on a worker (`now`: on this thread — a worker's). False when the
        test switch is on, *Check for updates* is off (no request at all) or a check is already running."""
        if os.environ.get("SURASURA_NO_UPDATE_CHECK"):
            return False
        from app import settings_manager
        from app.services.settings import thaw
        if not settings_manager.update_check_on(thaw(self.settings.get())):
            return False
        with self._lock:
            if self._checking:
                return False
            self._checking = True
        if now:
            self._check()
        else:
            threading.Thread(target=self._check, name="update-check", daemon=True).start()
        return True

    def _check(self):
        try:
            info = update_checker.get_update_info()
            cls = update_checker.classify_update(__version__, info)
            from app.services.settings import thaw
            current = thaw(self.settings.get())
            failed = updater.failed_version(current)
            cls = updater.effective_class(
                cls, info,
                skipped_version=current.get("skipped_version", ""),
                auto_enabled=current.get("auto_update_enabled", True),
                can_apply=updater.can_auto_apply(info),
                failed_version=failed,
            )
        except Exception as e:                        # offline, a bad answer: nothing to say (E18)
            print(f"Update check failed: {e}")
            info, cls, failed = None, "NONE", None
        snap = None
        with self._lock:
            self._checking = False
            if failed is not None:
                self._failed_version = failed
            if cls != "NONE" and info is not None and self._update is None:
                self._info, self._cls = info, cls
                critical = bool(getattr(info, "critical", False))
                open_now = critical and info.version not in self._surfaced
                if critical:
                    self._surfaced.add(info.version)
                snap = self._assign(AVAILABLE, open_now=open_now)
        self._send(snap)

    # --- the user's choices ------------------------------------------------------------------------------------- #
    def skip(self, version=None):
        """*Skip this version* (the Tk `_skip_update`): `skipped_version` written alone; the offer goes. `version`: the
        one a *Needs you* failure names (else the one on offer). False when there is nothing to skip or an update is
        under way."""
        with self._lock:
            if self._update is not None and not self._update.ended:
                return False
            version = version or getattr(self._info, "version", "")
            if not version:
                return False
            snap = None
            if getattr(self._info, "version", "") == version or self._state.version == version:
                self._info, self._cls = None, "NONE"
                snap = self._assign(NONE)
        self.settings.set({"skipped_version": version})
        self._send(snap)
        return True

    def offer_again(self):
        """*Offer skipped version again* (the Tk `_offer_skipped_again`): the skip forgotten, then checked again."""
        self.settings.set({"skipped_version": ""})
        self.check()

    def open_download(self):
        """*Download* (a manual release) / *Open the download page*: the browser, on a worker."""
        url = getattr(self._info, "notes_url", "") or RELEASES_PAGE
        threading.Thread(target=self._open, args=(url,), name="update-browser", daemon=True).start()

    def _open(self, url):
        try:
            self._open_url(url)
        except Exception as e:
            print(f"Update: the browser couldn't open {url}: {e}")

    def failures(self):
        """*Needs you*'s update entries (Failure: text, at, seen, version, report), newest first."""
        with self._lock:
            return tuple(self._needs)

    def failure(self):
        """The newest failure not looked at yet, in plain words, or None: a `StatusService` provider's shape."""
        with self._lock:
            return next((f.text for f in self._needs if not f.seen), None)

    def mark_seen(self):
        """The user looked at *Needs you*: the update's failures stop counting, and stay listed. Nothing unseen: no new
        state (HR-8, S19)."""
        with self._lock:
            if all(f.seen for f in self._needs):
                return
            self._needs = [f._replace(seen=True) for f in self._needs]
            snap = self._assign(self._state.state, keep=True)
        self._send(snap)

    # --- Update now --------------------------------------------------------------------------------------------- #
    def start(self):
        """*Update now* (the Tk `_do_auto_update` / `_do_installer_update` → `_start_update`). Returns at once: True when
        it began; False when nothing in-app is on offer, an update is already under way (or still ending), or the
        window is closing."""
        with self._lock:
            if self._update is not None or self._info is None or self._quitting or self._cls not in ("APP", "INSTALLER"):
                return False
            update = self._update = _Update(self._info, self._cls)
        # `detach`: closing never waits for a download — `quit()` cancels it, as the Tk `on_closing` did.
        job = self.registry.submit(
            "update", "Updating Surasura", start=lambda job: self._begin(update, job),
            cancel=lambda job: self.cancel(start_held=not self._quitting), on_quit="detach")
        update.job = job
        return True

    def _begin(self, update, job):
        update.job = job                              # the registry may start it inside submit(): known first
        threading.Thread(target=self._run, args=(update,), name="update-run", daemon=True).start()

    def _run(self, update):
        try:
            self._steps(update)
        except Exception as e:                        # a fault nobody foresaw never leaves it stuck (HR-14)
            self._broke(update, e)

    def _broke(self, update, error):
        """An unexpected fault in *Update now*'s run: everything it holds let go — the update lock (here, when no
        download was started to drop it), the held children, its job — and the failure said, as a failed download's."""
        print(f"Update: {error}")
        with self._lock:
            started = update.downloading is not None
            if not started:
                update.done = True                    # no download to end: this run drops the lock (`_end`)
        if not self._end(update, start_held=True, discard=started):
            return                                    # cancelled meanwhile: the cancel said so
        report = updater.write_report("update", error, to_version=getattr(update.info, "version", ""))
        self._fail(update, f"The update stopped: {error}." + report_note(report), report)

    def _steps(self, update):
        info = update.info
        if update.cls == "APP":
            manual = not updater.can_auto_apply(info)  # no updater.exe (a source checkout), or a list it may not write
            stage = updater.prepare_update
        else:
            manual = not path_utils.is_frozen()
            stage = updater.prepare_installer
        if manual:
            self._open(info.notes_url or RELEASES_PAGE)
            self._over(update, None)
            return
        lock = updater.take_update_lock()
        if lock is None:                              # another install's update, or a command line's
            self._over(update, "Another Surasura update is already in progress.")
            return
        updater.hold_children()
        with self._lock:
            update.lock = lock
            ended = update.ended
            if not ended:
                snap = self._assign(DOWNLOADING, done=0, total=0)
        if ended:                                     # cancelled while the lock was taken
            updater.drop_update_lock(lock)
            updater.release_children(start=update.start_held)
            if update.start_held:
                self.registry.reschedule()
            self._close_job(update, cancelled=True)
            return
        self._send(snap)
        update.downloading = threading.Thread(target=self._download, args=(update, stage), name="update-download",
                                              daemon=True)
        update.downloading.start()
        self._wait(update)

    def _download(self, update, stage):
        try:
            staged, error = stage(update.info, progress_cb=lambda done, total: self._progress(update, done, total)), None
        except Exception as e:
            staged, error = None, e
        with self._lock:
            update.staged, update.error, update.done = staged, error, True
            ended = update.ended
        if ended:
            # Cancelled (or closed) while it downloaded: its staging goes and the lock is freed only now, so a new
            # *Update now* never stages into the folder this download was still writing (the Tk `_update_downloaded`).
            updater.discard_staged()
            updater.drop_update_lock(update.lock)
            self._close_job(update, cancelled=True)
            return
        if error is not None:
            if not self._end(update, start_held=True):
                return                                # cancelled at the same moment: the cancel said so
            report = updater.write_report("download", error, to_version=getattr(update.info, "version", ""))
            self._fail(update, f"Couldn't download the update: {error}. You can try again later, or update manually "
                               "from the releases page." + report_note(report), report)
            return
        update.wake.set()

    def _progress(self, update, done, total):
        shown = int(done * 100 / total) if total else done // _MB
        with self._lock:
            update.progress = (done, total)
            if shown == update.shown or update.ended or update.done:
                return
            update.shown = shown
            snap = self._assign(DOWNLOADING, done=done, total=total, programs=self._programs(update),
                                message=update.message)
        update.job.progress(f"Downloading the update {shown} %" if total else f"Downloading the update {shown} MB")
        self._send(snap)

    # --- the wait ----------------------------------------------------------------------------------------------- #
    def _wait(self, update):
        """Every `poll` seconds until it hands over or ends (the Tk `_update_poll`): list what still runs, say it, and
        hand over once the download is done and nothing is left."""
        while True:
            update.wake.clear()
            children = self._listing()
            with self._lock:
                if update.ended:
                    return
                if children is None:                  # the look failed: the last list stands until the next (HR-16)
                    children = update.children or []
                update.children = children
                if children:
                    update.message = None
                done, error = update.done, update.error
            if done and error is None and not children:
                if self._hand_over(update):
                    return
            elif not (done and error is not None):
                self._say(update)
            update.wake.wait(self._poll)

    def _busy_entries(self):
        """The window's own work that writes to Anki (the Tk `_busy_threads`): waited for, no Stop. A thread here holding
        the Anki writer lock is one entry naming what it writes; when that is the automatic step, in place of Junban's
        own entry — never listed twice."""
        from app import anki_connect, locks
        writing = locks.held_in_process(anki_connect.WRITER_LOCK)
        busy = []
        for name in self._busy() or ():
            if name == JUNBAN_AUTO and writing == anki_connect.AUTOMATIC_STEP:
                continue
            busy.append({"pid": None, "name": name, "stop": None})
        if writing is not None:
            busy.append({"pid": None, "name": f"Writing to Anki ({writing or 'Surasura'})", "stop": None})
        # The registry's running jobs (the Qt window's Generate, indexer, sync, 順 …), each keyed by its job (two may
        # share a label: HR-4): *Stop it* cancels the job as its own Cancel does — but a job with no cancel (the sync,
        # the backlog read, 順) or one that quits with `wait` (an Anki write, Generate writing your list: it can't
        # stop) is only waited for, as Tk; 順's own row goes while the writer lock's row names its automatic step
        # (IK-18). A job's child process (its `pid`) is listed as the job alone (`_listing`). A recorded job is a child
        # the window passes in `active()`: listed there, never twice.
        for view in self.registry.live():
            if not view.gated or view.kind == "update" or view.state not in (jobs_module.RUNNING,
                                                                              jobs_module.CANCELLING):
                continue
            if view.kind == "junban" and writing == anki_connect.AUTOMATIC_STEP:
                continue
            stop = (None if view.on_quit == "wait" or not view.can_cancel
                    else (lambda job_id=view.id: self.registry.cancel(job_id)))
            busy.append({"pid": view.pid, "key": ("job", view.id), "name": view.label, "stop": stop})
        return busy

    def _listing(self):
        """What still runs (the Tk `_list_update_children`), or None when it couldn't be read. The window's own
        children (Generate's analyzer, the indexer: `Surasura.exe …` in a frozen build, so the scan finds them too)
        are their jobs' rows alone — never also *Another Surasura window*, whose Stop would end one at once."""
        try:
            busy = self._busy_entries()
            own = {entry["pid"] for entry in busy if entry.get("pid")}
            return busy + [child for child in updater.running_children(list(self._active() or ()))
                           if child.get("pid") not in own]
        except Exception as e:
            print(f"Update: {e}")
            return None

    @staticmethod
    def _key(child):
        return child.get("key") or child.get("pid") or child.get("name")

    @classmethod
    def _programs(cls, update):
        return tuple(Program(cls._key(c), c.get("name"), c.get("stop") is not None) for c in update.children or ())

    def _say(self, update):
        """The state while it waits, sent only when it changed."""
        with self._lock:
            if update.ended or update.handing:
                return
            programs = self._programs(update)
            state = WAITING if update.done else DOWNLOADING
            done, total = update.progress
            now = self._state
            if (now.state, now.programs, now.message) == (state, programs, update.message):
                return                                # the download's progress is `_progress`'s to say
            snap = self._assign(state, done=done, total=total, programs=programs, message=update.message)
        if programs:
            update.job.progress("Waiting for " + ", ".join(p.name for p in programs))
        self._send(snap)

    def stop(self, key=None):
        """*Stop it* for one program (`key`: its Program's key), or every one that can be stopped (None). Wait-only
        entries are never stopped. On a worker; the list is read again at once. False when there was nothing to stop."""
        with self._lock:
            update = self._update
            if update is None or update.ended:
                return False
            targets = [c for c in update.children or ()
                       if c.get("stop") is not None and (key is None or self._key(c) == key)]
        if not targets:
            return False

        def work():
            for child in targets:
                try:
                    child["stop"]()
                except Exception:
                    pass
            update.wake.set()
        threading.Thread(target=work, name="update-stop", daemon=True).start()
        return True

    def _hand_over(self, update):
        """The final step (the Tk `_apply_and_restart`): the last check, the library's locks, the install note (K100),
        the marker and the helper's launch, then `on_quit`. -> True when it handed over or gave up; False when
        something started meanwhile (the wait goes on)."""
        try:
            if self._busy_entries() or not updater.can_update_now(list(self._active() or ())):
                return False
        except Exception as e:
            print(f"Update: {e}")
            return False
        with self._lock:
            if update.ended:
                return True
            update.handing = True
        # The library store's helper (a detached process, not a child): its maintenance lock, every language, held
        # from here until this process exits — the swap comes after (Library_Store_Spec §7).
        held = updater.hold_library_locks()
        if held is None:
            with self._lock:
                update.handing = False
                update.message = "Waiting for the library's upkeep to finish"
            self._say(update)
            return False
        try:
            path_utils.write_install_note()
        except Exception as e:
            print(f"Install note: {e}")
        with self._lock:
            snap = self._assign(READY)
        self._send(snap)
        try:
            updater.arm_and_launch(update.staged)
        except Exception as e:
            updater.release_library_locks(held)
            with self._lock:
                update.handing = False
            self._end(update, start_held=True)
            report = updater.write_report("start updater", e, to_version=getattr(update.info, "version", ""))
            self._fail(update, f"Couldn't start the updater: {e}." + report_note(report), report)
            return True
        self._close_job(update)
        try:
            self.on_quit()                            # updater.exe waits on this process; the OS frees the locks
        except Exception as e:
            print(f"Update: closing for the updater failed: {e}")
        return True

    # --- cancelling and ending ---------------------------------------------------------------------------------- #
    def cancel(self, start_held=True):
        """*Cancel* / Esc / closing the sheet (the Tk `_cancel_update`): nothing armed, the update lock released (at once
        when downloaded; else when the download ends, which discards it), the held children free to start (those asked
        for meanwhile start now — not when the window is closing: `start_held=False`); offered again. False when there
        is nothing to cancel, or mid-swap."""
        with self._lock:
            update = self._update
            if update is None or update.ended or update.handing:
                return False
        if not self._end(update, start_held, discard=True):
            return False
        with self._lock:
            done = update.done
            snap = self._assign(AVAILABLE, message="Update cancelled.") if self._info is not None else self._assign(NONE)
        if done:
            self._close_job(update, cancelled=True)
        elif update.job is not None:
            update.job.cancel()                       # listed as stopping until the download ends
        self._send(snap)
        return True

    def quit(self):
        """The window closes (the Tk `on_closing`): an update still waiting is cancelled and nothing held starts. Call it
        before the registry's `quit`."""
        with self._lock:
            self._quitting = True
            update = self._update
            self._held_at_quit = update is not None and not update.ended
        self.cancel(start_held=False)

    def _end(self, update, start_held=True, discard=False):
        """The Tk `_end_update`: ended once; the update lock dropped when the download is over (else by it); children
        released. -> False when it had ended already."""
        with self._lock:
            if update.ended:
                return False
            update.ended, update.start_held = True, start_held
            done = update.done
        update.wake.set()
        if done:
            if discard:
                updater.discard_staged()
            updater.drop_update_lock(update.lock)
        if update.lock is not None:
            updater.release_children(start=start_held)
            if start_held:                            # the jobs held meanwhile start — not when the window closes:
                self.registry.reschedule()            # the registry's `quit` cancels them, as Tk dropped its children
        return True

    def _close_job(self, update, cancelled=False, message=None, ok=True):
        if update.job is not None:
            update.job.finish(ok=ok, message=message, cancelled=cancelled)
        with self._lock:
            if self._update is update:
                self._update = None

    def _over(self, update, message):
        """It never began (a manual download, or another update holds the lock): offered again, as before."""
        with self._lock:
            update.ended = True
            snap = self._assign(AVAILABLE, message=message) if self._info is not None else None
        self._close_job(update)
        self._send(snap)

    def _fail(self, update, message, report, version=None):
        """A failure: the bar's `failed` state and a *Needs you* entry — never a dialog."""
        with self._lock:
            version = version if version is not None else getattr(getattr(update, "info", None), "version", "")
            self._needs.insert(0, Failure(message, time.time(), False, version, report))
            del self._needs[NEEDS_YOU_KEPT:]
            snap = self._assign(FAILED, message=message, report=report, version=version)
        if update is not None:
            self._close_job(update, ok=False, message=message)
        self._send(snap)

    # --- states ------------------------------------------------------------------------------------------------- #
    def _assign(self, state, done=None, total=None, programs=(), message=None, report=None, open_now=False,
                version=None, keep=False):
        """The new state (inside `self._lock`), numbered. `keep`: the same state with the failures / outcome renewed."""
        now = self._state
        if keep:
            self._state = now._replace(needs_you=tuple(self._needs), updated=self._updated, open_now=False,
                                       seq=now.seq + 1)
            return self._state
        info = self._info
        cls = self._cls if info is not None else "NONE"
        self._state = State(
            state, version if version is not None else getattr(info, "version", ""), cls,
            body(cls, info, self._failed_version) if info is not None else "", getattr(info, "notes_url", "") or "",
            bool(getattr(info, "critical", False)), open_now, done, total, tuple(programs), message, report,
            tuple(self._needs), self._updated, now.seq + 1)
        return self._state

    def _send(self, snap):
        """Deliver `snap`, one delivery at a time, and only while it is still the newest."""
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
                except Exception as e:                # a listener's fault never stops an update
                    print(f"Update: a listener failed: {e}")
