"""Named locks between Surasura's programs — one primitive for every lock name (E1.4; P0.3 04 §2).

`take("anki-writer", "順 reorder")` holds a lock that every other thread, process and install asking for
the same name sees: it answers `Busy` at once, or waits for it (`wait=` seconds, or `None` until it is
free or `cancel` is set). Built on S1.1's `path_utils.try_lock` / `release_lock`: byte 0 of
`<name>.lock`, nothing written into the locked byte, so **the OS releases the lock when the process
dies** and a crash never leaves a stale one.

Beside the lock, `<name>.holder.json` says who holds it (`{program, pid, started, verb}`), written after
the take and deleted before the release. It is informative only: a write that fails never fails the
take, and a record a dead holder left is read only after a failed take.

Inside one process a registry of held names stands beside the OS lock: a second thread waits or is
told `Busy` like another process; the same thread asking again is a programming error (`RuntimeError`),
never a wait on itself.

Where: per install, `<local data>/locks/` (`path_utils.get_local_data_path()`, beside S1.1's
`update.lock`). A name in `SHARED` lives per user, `path_utils.local_data_root()/locks/`: one Windows user
has one Anki, so two installs (a 2.x and a 3.0 side by side, an installed copy and a source checkout)
must not write it together. Sharedness belongs to the name, never the call.

Standard library only, no Tk: `on_wait` and the wait itself run on the waiting worker, so a window
passes a callback that only posts to its own queue.
"""

import datetime
import json
import os
import re
import sys
import threading
import time

from app import path_utils

# The names one Windows user shares across installs (see the module docstring).
SHARED = frozenset({"anki-writer"})

# How often a wait looks again (P0.3 04 §2: `--wait` polls every 250 ms).
POLL = 0.25

_NAME = re.compile(r"[a-z0-9-]+\Z")

# name -> (its owner in this process — the taking thread's ident, or the `owner` a hold that outlives its thread
# named — and its verb). Guarded by `_registry_lock`, which is
# held only while asking the OS for the lock (never while waiting).
_registry = {}
_registry_lock = threading.Lock()


class Busy(Exception):
    """The lock is held elsewhere. `holder` is its record (`{program, pid, started, verb}`), or None
    when none could be read."""

    def __init__(self, name, holder=None):
        self.name = name
        self.holder = holder
        verb = (holder or {}).get("verb") or "another program"
        super().__init__(f"'{name}' is held by {verb}.")


class Cancelled(Busy):
    """A wait stopped by its `cancel` event before the lock came free."""


def _check(name):
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError(f"A lock name is lowercase letters, digits and '-': {name!r}")


def folder(name):
    """The folder `name`'s lock lives in: per user for a shared name, else per install."""
    _check(name)
    root = path_utils.local_data_root() if name in SHARED else path_utils.get_local_data_path()
    return os.path.join(root, "locks")


def _paths(name):
    where = folder(name)
    return os.path.join(where, name + ".lock"), os.path.join(where, name + ".holder.json")


def _program():
    """The running program's name: `Surasura.exe` / `surasura-cli.exe` when frozen, else `python`."""
    return os.path.basename(sys.executable) if getattr(sys, "frozen", False) else "python"


def unopenable(name):
    """The path of `name`'s lock file when this process can't open it (a PermissionError: its folder's permissions),
    else None. `take` reads such a file as held by a program it can't name (`Busy(None)`), failing closed; a caller
    asks this to say so in plain words instead of "busy" (P1.2, E1.4's review #11). Never raises."""
    try:
        path = _paths(name)[0]
        with open(path, "a+b"):
            return None
    except PermissionError:
        return path
    except (OSError, ValueError, RuntimeError):
        return None


def in_use(name, looks=6, gap=0.02):
    """Is `name` held — by any thread of this process, or another program? A reader's look (P1.2): it never takes the
    lock for a holder, writes no record and joins no registry. The OS lock is tried and let go at once, `looks` times
    `gap` seconds apart: another reader's look holds it well under a millisecond, a holder holds it all along, so
    only a lock held at every look is in use. A missing lock file is free. Never raises."""
    if held_in_process(name):
        return True
    try:
        path = _paths(name)[0]
        if not os.path.exists(path):
            return False
        for look in range(looks):
            handle = path_utils.try_lock(path)
            if handle is not None:
                path_utils.release_lock(handle)
                return False
            if look < looks - 1:
                time.sleep(gap)
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def holder_alive(holder):
    """The holder record if its process still runs, else None: a record a killed holder left names nobody. Never
    raises."""
    try:
        pid = int((holder or {}).get("pid"))
    except (TypeError, ValueError):
        return None
    if pid == os.getpid():
        return holder
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            code = ctypes.c_ulong()
            alive = kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259    # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
        return holder if alive else None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except OSError:
        pass
    return holder


def read_holder(name):
    """The holder record of `name`, or None when there is none or it can't be read. Never raises."""
    try:
        with open(_paths(name)[1], "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _retried(step):
    """`step()`, tried again for up to ~0.2 s: on Windows a waiter reading the record (every 250 ms) makes a
    replace or delete fail with a sharing violation for that moment. Raises the last error."""
    for attempt in range(10):
        try:
            return step()
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02)


def _write_holder(path, record):
    """Atomically (temp + `os.replace`). Informative only: any failure is swallowed."""
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        _retried(lambda: os.replace(temp, path))
    except Exception:
        try:
            os.remove(temp)
        except OSError:
            pass


class Held:
    """A held lock. A context manager; `release()` is safe to call twice. `waited` is True when the
    take had to wait for another holder first (a writer checks again after a wait)."""

    def __init__(self, name, verb, handle, record_path, waited):
        self.name = name
        self.verb = verb
        self.waited = waited
        self._handle = handle
        self._record_path = record_path
        self._lock = threading.Lock()

    def release(self):
        with self._lock:
            handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _retried(lambda: os.remove(self._record_path))  # before the unlock: the next holder's record survives
        except OSError:
            pass
        with _registry_lock:
            path_utils.release_lock(handle)
            _registry.pop(self.name, None)

    @property
    def held(self):
        return self._handle is not None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def held_here(name, owner=None):
    """Does the calling thread (or `owner`, when given) hold `name`?"""
    owner = threading.get_ident() if owner is None else owner
    with _registry_lock:
        return (_registry.get(name) or (None,))[0] == owner


def held_in_process(name):
    """The verb `name` is held for by any thread of this process, or None."""
    with _registry_lock:
        return (_registry.get(name) or (None, None))[1]


def _try(name, verb, lock_path, me):
    """One attempt: the OS lock, registered to this thread -> the open file, or None when held."""
    with _registry_lock:
        owner = (_registry.get(name) or (None,))[0]
        if owner == me:
            raise RuntimeError(f"'{name}' is already held by this owner: a nested take is a programming error.")
        if owner is not None:
            return None
        handle = path_utils.try_lock(lock_path)
        if handle is not None:
            _registry[name] = (me, verb)
        return handle


def take(name, verb, wait=0.0, cancel=None, on_wait=None, owner=None):
    """Take `name` for `verb` (a short user-facing phrase: "順 reorder", "Backfill") -> `Held`.

    `wait=0` answers at once; `wait=s` looks again every 250 ms for up to `s` seconds; `wait=None` waits
    until the lock is free or `cancel` (a `threading.Event`) is set. Held elsewhere when the wait runs
    out -> `Busy(holder)`; cancelled -> `Cancelled(holder)`. `on_wait(holder)` is called once, when
    waiting starts. Both run on the calling thread — never the GUI's.

    A hold never outlives its thread unless it names an `owner` (any object: the 順 window passes its own token, takes
    the lock on a worker that ends, and lets go through its `Held`): the registry keeps the owner, and the nested-take
    check and `held_here` compare owners, so a later thread that reuses the ident is never mistaken for the holder.
    """
    lock_path, record_path = _paths(name)
    me = threading.get_ident() if owner is None else owner
    deadline = None if wait is None else time.monotonic() + max(0.0, float(wait))
    waited = False
    while True:
        handle = _try(name, verb, lock_path, me)
        if handle is not None:
            break
        holder = read_holder(name)
        if cancel is not None and cancel.is_set():
            raise Cancelled(name, holder)
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise Busy(name, holder)
        if not waited:
            waited = True
            if on_wait is not None:
                on_wait(holder)
        pause = POLL if remaining is None else min(POLL, remaining)
        if cancel is not None:
            if cancel.wait(pause):
                raise Cancelled(name, read_holder(name))
        else:
            time.sleep(pause)
    try:
        record = {"program": _program(), "pid": os.getpid(),
                  "started": datetime.datetime.now().isoformat(timespec="seconds"), "verb": verb}
        _write_holder(record_path, record)
        return Held(name, verb, handle, record_path, waited)
    except BaseException:
        # Taken but not handed over (an interrupt, say): let go, or the name stays held until restart.
        with _registry_lock:
            path_utils.release_lock(handle)
            _registry.pop(name, None)
        raise
