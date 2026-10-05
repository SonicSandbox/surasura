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

# name -> the thread ident holding it in this process. Guarded by `_registry_lock`, which is held only
# while asking the OS for the lock (never while waiting).
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


def read_holder(name):
    """The holder record of `name`, or None when there is none or it can't be read. Never raises."""
    try:
        with open(_paths(name)[1], "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _write_holder(path, record):
    """Atomically (temp + `os.replace`). Informative only: a failure is swallowed."""
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        os.replace(temp, path)
    except OSError:
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
            os.remove(self._record_path)        # before the unlock, so the next holder's record survives
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


def held_here(name):
    """Does the calling thread hold `name`?"""
    with _registry_lock:
        return _registry.get(name) == threading.get_ident()


def _try(name, lock_path, me):
    """One attempt: the OS lock, registered to this thread -> the open file, or None when held."""
    with _registry_lock:
        owner = _registry.get(name)
        if owner == me:
            raise RuntimeError(f"This thread already holds '{name}': a nested take is a programming error.")
        if owner is not None:
            return None
        handle = path_utils.try_lock(lock_path)
        if handle is not None:
            _registry[name] = me
        return handle


def take(name, verb, wait=0.0, cancel=None, on_wait=None):
    """Take `name` for `verb` (a short user-facing phrase: "順 reorder", "Backfill") -> `Held`.

    `wait=0` answers at once; `wait=s` looks again every 250 ms for up to `s` seconds; `wait=None` waits
    until the lock is free or `cancel` (a `threading.Event`) is set. Held elsewhere when the wait runs
    out -> `Busy(holder)`; cancelled -> `Cancelled(holder)`. `on_wait(holder)` is called once, when
    waiting starts. Both run on the calling thread — never the GUI's.
    """
    lock_path, record_path = _paths(name)
    me = threading.get_ident()
    deadline = None if wait is None else time.monotonic() + max(0.0, float(wait))
    waited = False
    while True:
        handle = _try(name, lock_path, me)
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
    record = {"program": _program(), "pid": os.getpid(),
              "started": datetime.datetime.now().isoformat(timespec="seconds"), "verb": verb}
    _write_holder(record_path, record)
    return Held(name, verb, handle, record_path, waited)
