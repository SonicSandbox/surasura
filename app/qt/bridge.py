"""The bridge (W2.1; the window's spec 04 §4.1): the only place a service's callback becomes a Qt signal.

The services (`app/services/`) are Qt-free and run their callbacks on their own threads (the settings writer's worker,
the job registry's caller, the status service's refresher). The window may touch a widget only on its own thread, so
each callback is re-emitted here as a signal of an object that lives on the GUI thread: Qt queues it there, in the
order the service called it, one at a time. No widget ever hears a service directly.

`run_in_worker(fn, then=…, failed=…)` is the other direction: work the GUI thread must not wait for (a file, SQLite,
a lock) runs on `QThreadPool` with a frozen input, and its answer comes back to the GUI thread the same way. The
function never touches a widget.

`Gate(obj)` is the one road from a service's thread into a Qt object (the bridge's, a `Relay`'s, the drag's and
Finished's relays, the search's answer): a thread emitting on a QObject at the moment the GUI thread deletes it crashes
the process — an access violation, no Python error to catch (round 8's crash: the writer's late landing on a relay the
window's deletion took). The gate's emit and the object's deletion never overlap, and once it is closed nothing more is
emitted.
"""
import functools
import sys
import threading
import traceback

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal


class Gate:
    """(Any thread.) `obj`'s signals as a service's callbacks. `emit(name, *args)` emits `obj.<name>` unless the gate
    is closed, looking the signal up afresh each time (a bound signal kept past its object's deletion calls freed
    memory: round 8's crash); `caller(name)` is that emit as one callback (the same object each call: a service can let
    it go by identity). `close()` — the object's deletion (its `destroyed`, on the deleting thread) or a window letting
    go — waits for an emit under way on another thread, and from its return nothing more is emitted. On the object's
    own thread no deletion can overlap the emit, so it takes no lock there (its direct slots never run under it). Make
    it on the GUI thread, for an object with a parent (a parentless one would wait for the cycle collector)."""

    def __init__(self, obj):
        self._lock = threading.Lock()
        self._home = threading.get_ident()        # the object's own thread (the GUI thread)
        self._obj = obj
        self._callers = {}
        obj.destroyed.connect(self.close, Qt.ConnectionType.DirectConnection)

    def close(self, *_):
        with self._lock:                          # (a service's emit under way holds it: waited for)
            self._obj = None

    @property
    def open(self):
        return self._obj is not None

    def emit(self, name, *args):
        if threading.get_ident() == self._home:
            self._emit(name, args)
            return
        with self._lock:
            self._emit(name, args)

    def _emit(self, name, args):
        obj = self._obj
        if obj is None:                           # a service calling back after the window let go: dropped, never
            return                                # raised into the service (it would log a fault)
        try:
            getattr(obj, name).emit(*args)
        except RuntimeError:                      # the C++ object went without its `destroyed` reaching the gate
            self._obj = None

    def caller(self, name):
        if name not in self._callers:
            self._callers[name] = functools.partial(self.emit, name)
        return self._callers[name]


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
        self._gate = Gate(self)
        if settings is not None:
            settings.subscribe(lambda keys: self._emit("settings_written", tuple(keys)))
        if registry is not None:
            registry.subscribe(lambda views: self._emit("jobs_changed", tuple(views)))
        if status is not None:
            status.subscribe(lambda snap: self._emit("status_changed", snap))
        if library is not None:
            library.subscribe(lambda view: self._emit("library_changed", view))

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
        self._gate.close()

    def _emit(self, signal, value):
        # A service may call back after the window closed (its thread outlives the bridge): dropped (`Gate`).
        self._gate.emit(signal, value)


class Relay(QObject):
    """(W3.4) One service callback as a signal, for a window that hands a Qt-free runner a callback (a tool's lines and
    its end, `app/services/tools.py`): `relay.call` is the callback (any thread), `said` arrives on the GUI thread, in
    order. Made on the GUI thread with a parent: once the parent is gone, a call is dropped."""
    said = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gate = Gate(self)

    def call(self, value=None):
        self._gate.emit("said", value)


class _Relay(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)


class _Job(QRunnable):
    def __init__(self, fn, args, gate):
        super().__init__()
        self.fn, self.args, self.gate = fn, args, gate
        self.setAutoDelete(True)

    def run(self):
        try:
            value = self.fn(*self.args)
        except BaseException as e:                 # the answer is the failure; the worker thread never dies of it
            self.gate.emit("failed", (e, traceback.format_exc()))
            return
        self.gate.emit("done", value)


_pending = set()                                   # relays waiting for their answer (kept alive until it arrives)


def run_in_worker(fn, *args, then=None, failed=None, pool=None):
    """Run `fn(*args)` on the thread pool; `then(value)` or `failed((exception, traceback))` runs on the GUI thread
    afterwards. Call it on the GUI thread. A failure with no `failed` handler is printed (never raised in the pool)."""
    relay = _Relay()                               # made here, so it lives on the caller's (the GUI) thread
    gate = Gate(relay)                             # (the pool's emit and the relay's deletion never overlap)

    def finish(_):
        _pending.discard(relay)
        gate.close()
        relay.deleteLater()

    relay.dropped = False                          # `drop_answers`: an answer already queued is dropped as it lands

    def unless_dropped(callback):
        return lambda value: None if relay.dropped else callback(value)

    if then is not None:
        relay.done.connect(unless_dropped(then))
    if failed is not None:
        relay.failed.connect(unless_dropped(failed))
    else:
        relay.failed.connect(lambda info: print(f"A background task failed: {info[1]}", file=sys.stderr))
    relay.done.connect(finish)
    relay.failed.connect(finish)
    _pending.add(relay)
    (pool or QThreadPool.globalInstance()).start(_Job(fn, args, gate))
    return relay


def drop_answers():
    """The window closed (its `closeEvent`, row 55's follow-up): every answer still to come is dropped where it comes
    back — never handed to a callback writing into a widget deleted by the time it lands (round 8: the journey's
    answer said into a bar already gone; a callback into a deleted widget raises at best, and can crash natively).
    One guard for every `run_in_worker` caller, never a check in each callback."""
    for relay in list(_pending):                    # (kept in `_pending`: a parentless relay let go here would be
        relay.dropped = True                        # deleted by whichever thread drops it last — the pool's; and an
        try:                                        # answer already on the window's queue is past blockSignals)
            relay.blockSignals(True)
        except RuntimeError:
            pass


def wait_for_workers(timeout_ms):
    """At the app's quit (W3.4; row 6's find): every answer still to come is dropped (the window is going), then the
    global pool is waited for, up to `timeout_ms` — a worker still running Python as the process ends can crash it.
    Called after the window closed, never while it shows. -> True when every worker ended in time."""
    drop_answers()
    return QThreadPool.globalInstance().waitForDone(int(timeout_ms))
