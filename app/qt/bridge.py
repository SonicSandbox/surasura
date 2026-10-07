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

    def __init__(self, settings=None, registry=None, status=None, parent=None):
        super().__init__(parent)
        self._alive = True
        if settings is not None:
            settings.subscribe(lambda keys: self._emit("settings_written", tuple(keys)))
        if registry is not None:
            registry.subscribe(lambda views: self._emit("jobs_changed", tuple(views)))
        if status is not None:
            status.subscribe(lambda snap: self._emit("status_changed", snap))
        self.destroyed.connect(self._gone)

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
