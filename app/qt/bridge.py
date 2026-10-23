"""The bridge (W2.1; the window's spec 04 §4.1): the only place a service's callback becomes a Qt signal.

The services (`app/services/`) are Qt-free and run their callbacks on their own threads (the settings writer's worker,
the job registry's caller, the status service's refresher). The window may touch a widget only on its own thread, so
each callback is re-emitted here as a signal of an object that lives on the GUI thread: Qt queues it there, in the
order the service called it, one at a time. No widget ever hears a service directly.

`run_in_worker(fn, then=…, failed=…)` is the other direction: work the GUI thread must not wait for (a file, SQLite,
a lock) runs on `QThreadPool` with a frozen input, and its answer comes back to the GUI thread the same way. The
function never touches a widget.
"""
import sys
import traceback

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class Bridge(QObject):
    """Make one per window, on the GUI thread, with the window's services. Connect widgets to its signals."""

    settings_written = pyqtSignal(object)        # tuple of the keys a landed write carried
    jobs_changed = pyqtSignal(object)            # tuple of job views (the registry's snapshot)
    status_changed = pyqtSignal(object)          # the status service's Snapshot
    library_changed = pyqtSignal(object)         # the library reader's View (W2.2)
    # --- W3.5: the dashboard's duties
    update_changed = pyqtSignal(object)          # the update service's State
    generate_changed = pyqtSignal(object)        # the Generate controller's State
    automation_changed = pyqtSignal(object)      # automatic sync / Generate / 順's State
    chores_changed = pyqtSignal(object)          # the chores' State (Connect's line, Koe's port)
    indexed = pyqtSignal(object)                 # the indexer ran (its language)
    quit_asked = pyqtSignal(object)              # the update hands over: the window closes

    def __init__(self, settings=None, registry=None, status=None, library=None, parent=None):
        super().__init__(parent)
        self._alive = True
        if settings is not None:
            settings.subscribe(lambda keys: self._emit("settings_written", tuple(keys)))
        if registry is not None:
            registry.subscribe(lambda views: self._emit("jobs_changed", tuple(views)))
        if status is not None:
            status.subscribe(lambda snap: self._emit("status_changed", snap))
        if library is not None:
            library.subscribe(lambda view: self._emit("library_changed", view))
        self.destroyed.connect(self._gone)

    def attach(self, updates=None, controller=None, automation=None, chores=None):
        """W3.5: the duties' callbacks as signals (each service calls back on its own workers)."""
        if updates is not None:
            updates.subscribe(lambda state: self._emit("update_changed", state))
        if controller is not None:
            controller.subscribe(lambda state: self._emit("generate_changed", state))
        if automation is not None:
            automation.subscribe(lambda state: self._emit("automation_changed", state))
        if chores is not None:
            chores.subscribe(lambda state: self._emit("chores_changed", state))
            chores.on_indexed(lambda language: self._emit("indexed", language))

    def ask_quit(self):
        """(Any thread.) The update service's `on_quit`: the window closes on its own thread."""
        self._emit("quit_asked", None)

    def stop(self):
        """The window closed: no service's callback reaches a slot from here on. The quit runs on the window's thread
        after its loop ended, where a signal would reach its slot at once (a Generate dropped at quit would start a
        journey look and a token-store read as the process exits)."""
        self._alive = False

    def _gone(self, *_):
        self._alive = False

    def _emit(self, signal, value):
        # A service may call back after the window closed (its thread outlives the bridge): dropped, never raised
        # into the service (a raising listener would be logged there as a fault).
        if not self._alive:
            return
        try:
            getattr(self, signal).emit(value)
        except RuntimeError:                      # the C++ object is gone
            self._alive = False


class Relay(QObject):
    """(W3.4) One service callback as a signal, for a window that hands a Qt-free runner a callback (a tool's lines and
    its end, `app/services/tools.py`): `relay.call` is the callback (any thread), `said` arrives on the GUI thread, in
    order. Made on the GUI thread with a parent: once the parent is gone, a call is dropped."""
    said = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alive = True
        self.destroyed.connect(self._gone)

    def call(self, value=None):
        if not self._alive:
            return
        try:
            self.said.emit(value)
        except RuntimeError:                      # the C++ object is gone
            self._alive = False

    def _gone(self, *_):
        self._alive = False


class _Relay(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)


class _Job(QRunnable):
    def __init__(self, fn, args, relay):
        super().__init__()
        self.fn, self.args, self.relay = fn, args, relay
        self.setAutoDelete(True)

    def run(self):
        try:
            value = self.fn(*self.args)
        except BaseException as e:                 # the answer is the failure; the worker thread never dies of it
            self.relay.failed.emit((e, traceback.format_exc()))
            return
        self.relay.done.emit(value)


_pending = set()                                   # relays waiting for their answer (kept alive until it arrives)


def run_in_worker(fn, *args, then=None, failed=None, pool=None):
    """Run `fn(*args)` on the thread pool; `then(value)` or `failed((exception, traceback))` runs on the GUI thread
    afterwards. Call it on the GUI thread. A failure with no `failed` handler is printed (never raised in the pool)."""
    relay = _Relay()                               # made here, so it lives on the caller's (the GUI) thread

    def finish(_):
        _pending.discard(relay)
        relay.deleteLater()

    if then is not None:
        relay.done.connect(then)
    if failed is not None:
        relay.failed.connect(failed)
    else:
        relay.failed.connect(lambda info: print(f"A background task failed: {info[1]}", file=sys.stderr))
    relay.done.connect(finish)
    relay.failed.connect(finish)
    _pending.add(relay)
    (pool or QThreadPool.globalInstance()).start(_Job(fn, args, relay))
    return relay


def drop_answers():
    """The window closed (its `closeEvent`, row 55's follow-up): every answer still to come is dropped where it comes
    back — never handed to a callback writing into a widget deleted by the time it lands (round 8: the journey's
    answer said into a bar already gone; a callback into a deleted widget raises at best, and can crash natively).
    One guard for every `run_in_worker` caller, never a check in each callback."""
    for relay in list(_pending):
        try:
            relay.blockSignals(True)
        except RuntimeError:
            pass


def wait_for_workers(timeout_ms):
    """At the app's quit (W3.4; row 6's find): every answer still to come is dropped (the window is going), then the
    global pool is waited for, up to `timeout_ms` — a worker still running Python as the process ends can crash it.
    Called after the window closed, never while it shows. -> True when every worker ended in time."""
    drop_answers()
    return QThreadPool.globalInstance().waitForDone(int(timeout_ms))
