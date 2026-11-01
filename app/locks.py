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
`update.lock`). A name in `SHARED` lives per user: one Windows user has one Anki, so two installs (a 2.x and
a 3.0 side by side, an installed copy and a source checkout) must not write it together. It is taken in
BOTH per-user roots, always in the same order — the Houseki root (`path_utils.local_data_root()/locks/`),
then 2.x's SonicSandbox root (`path_utils.legacy_local_root()/locks/`) — so a 2.x, which knows only the
second, and a 3.0 never write Anki at once (S3.1 D14). Each look is non-blocking and a take that gets the
first but not the second lets the first go, so two takers never wait on each other. Sharedness belongs to
the name, never the call.

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


def folders(name):
    """The folders `name`'s lock lives in, in the order it is taken: a shared name's two per-user roots (Houseki,
    then SonicSandbox), else the per-install folder alone."""
    _check(name)
    if name in SHARED:
        return [os.path.join(path_utils.local_data_root(), "locks"),
                os.path.join(path_utils.legacy_local_root(), "locks")]
    return [os.path.join(path_utils.get_local_data_path(), "locks")]


def folder(name):
    """The folder `name`'s lock lives in first: per user (Houseki) for a shared name, else per install."""
    return folders(name)[0]


def _all_paths(name):
    """(lock file, holder record) in each of `folders(name)`, in taking order."""
    return [(os.path.join(where, name + ".lock"), os.path.join(where, name + ".holder.json"))
            for where in folders(name)]


def _paths(name):
    return _all_paths(name)[0]


def _program():
    """The running program's name: `Surasura.exe` / `surasura-cli.exe` when frozen, else `python`."""
    return os.path.basename(sys.executable) if getattr(sys, "frozen", False) else "python"


def unopenable(name):
    """The path of `name`'s lock file when this process can't open it (a PermissionError: its folder's permissions),
    else None. `take` reads such a file as held by a program it can't name (`Busy(None)`), failing closed; a caller
    asks this to say so in plain words instead of "busy" (P1.2, E1.4's review #11). Never raises."""
    try:
        for path, _record in _all_paths(name):
            try:
                with open(path, "a+b"):
                    pass
            except PermissionError:
                return path
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def in_use(name, looks=6, gap=0.02):
    """Is `name` held — by any thread of this process, or another program? A reader's look (P1.2): it never takes the
    lock for a holder, writes no record and joins no registry. The OS lock is tried and let go at once, `looks` times
    `gap` seconds apart: another reader's look holds it well under a millisecond, a holder holds it all along, so
    only a lock held at every look is in use. A missing lock file is free. Never raises."""
    if held_in_process(name):
        return True
    try:
        return any(_held_at(path, looks, gap) for path, _record in _all_paths(name))
    except (OSError, ValueError, RuntimeError):
        return False


def _held_at(path, looks, gap):
    """Is the OS lock on `path` held at every one of `looks` looks? A missing lock file is free."""
    if not os.path.exists(path):
        return False
    for look in range(looks):
        handle = path_utils.try_lock(path)
        if handle is not None:
            path_utils.release_lock(handle)
            return False
        if look < looks - 1:
            time.sleep(gap)
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
    """The holder record of `name` — a shared name's first record found, Houseki's then SonicSandbox's (a 2.x
    holder writes only the second) — or None when there is none or it can't be read. Never raises."""
    try:
        records = [record for _lock, record in _all_paths(name)]
    except (OSError, ValueError, RuntimeError):
        return None
    for path in records:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            return record
    return None


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

    def __init__(self, name, verb, handles, record_paths, waited):
        self.name = name
        self.verb = verb
        self.waited = waited
        self._handle = handles              # the OS locks, in taking order (two for a shared name)
        self._record_paths = record_paths
        self._lock = threading.Lock()

    def release(self):
        with self._lock:
            handles, self._handle = self._handle, None
        if handles is None:
            return
        for record_path in self._record_paths:
            try:
                _retried(lambda: os.remove(record_path))    # before the unlock: the next holder's record survives
            except OSError:
                pass
        with _registry_lock:
            _release_all(handles)
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


def _release_all(handles):
    """Let go of OS locks taken in order, newest first."""
    for handle in reversed(handles):
        path_utils.release_lock(handle)


def _try(name, verb, lock_paths, me):
    """One attempt: every OS lock in `lock_paths`, in order, registered to this thread -> the open files, or None
    when any is held (those already taken let go at once)."""
    with _registry_lock:
        owner = (_registry.get(name) or (None,))[0]
        if owner == me:
            raise RuntimeError(f"'{name}' is already held by this owner: a nested take is a programming error.")
        if owner is not None:
            return None
        handles = []
        for lock_path in lock_paths:
            handle = path_utils.try_lock(lock_path)
            if handle is None:
                _release_all(handles)
                return None
            handles.append(handle)
        _registry[name] = (me, verb)
        return handles


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
    paths = _all_paths(name)
    lock_paths, record_paths = [lock for lock, _ in paths], [record for _, record in paths]
    me = threading.get_ident() if owner is None else owner
    deadline = None if wait is None else time.monotonic() + max(0.0, float(wait))
    waited = False
    while True:
        handles = _try(name, verb, lock_paths, me)
        if handles is not None:
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
        for record_path in record_paths:       # each root's: a 2.x waiting on its own root can say who holds it
            _write_holder(record_path, record)
        return Held(name, verb, handles, record_paths, waited)
    except BaseException:
        # Taken but not handed over (an interrupt, say): let go, or the name stays held until restart.
        with _registry_lock:
            _release_all(handles)
            _registry.pop(name, None)
        raise


# --- Running marks and the profile-move lock (Fresh library, 3.0.1; spec §4.1, §5, P13) -------------------------- #
# Every Surasura program (the window, the command line and Piyo's MCP server, Connect, the window's children) holds a
# RUNNING MARK for its life: an OS lock on its own `<install folder>/locks/running/<pid>-<n>.lock`, with a holder
# record beside it (`.json`: program, pid, kind, started). The OS lets go when the program dies, so a mark held means a
# program alive — on every OS, which is what *Start over completely* asks before it renames a thing (Windows' refused
# rename is only a second check). The mover takes PROFILE_MOVE first and then looks at the marks; a program takes its
# mark first and then looks at PROFILE_MOVE: whichever order the two meet in, one of them sees the other.
PROFILE_MOVE = "profile-move"
RUNNING_DIR = "running"
MOVE_WAIT = 60.0        # s: a program starting while a move runs waits this long for it, then stops with MOVE_RUNNING
MOVE_RUNNING = "Surasura is setting your old Surasura aside: try again in a moment."

_mark = {}              # this process's mark: {"handle", "path", "count"}; guarded by `_registry_lock`


class MoveRunning(Busy):
    """A Start over or Put back is running (PROFILE_MOVE held): a program starting now waits, then stops with
    MOVE_RUNNING. Its mark is let go first."""


def _running_folders():
    """The running marks' folders of every install of this data name: this one's (`get_local_data_path`) and each
    install folder in the local root — they share the roaming root, so another install's programs count too."""
    mine = os.path.join(path_utils.get_local_data_path(), "locks", RUNNING_DIR)
    out = [mine]
    root = path_utils.local_data_root()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for name in names:
        where = os.path.join(root, name, "locks", RUNNING_DIR)
        if path_utils._INSTALL_DIR.match(name) and os.path.normcase(where) != os.path.normcase(mine) \
                and os.path.isdir(where):
            out.append(where)
    return out


def hold_running(kind, wait=MOVE_WAIT, cancel=None):
    """This process's running mark, for `kind` ("window", "cli", "mcp", a command's name), held until it ends or
    `release_running` -> True. Once a process: a second call only counts (the command line called in-process again).
    PROFILE_MOVE held by another program: the mark is let go, the move waited for up to `wait` s, the mark taken again;
    still held -> `MoveRunning`. A mark that can't be written (a read-only folder) is no mark: False, logged by the
    caller — never a refusal to start."""
    with _registry_lock:
        if _mark:
            _mark["count"] += 1
            return True
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        handle, path = _take_mark(kind)
        if handle is None:
            return False
        if not _moving():
            with _registry_lock:
                _mark.update(handle=handle, path=path, count=1)
            return True
        _drop_mark(handle, path)
        if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
            raise MoveRunning(PROFILE_MOVE, read_holder(PROFILE_MOVE))
        time.sleep(POLL)


def _moving():
    """Is PROFILE_MOVE held by another program? (This process's own move never stops its own programs.)"""
    if held_in_process(PROFILE_MOVE):
        return False
    try:
        return any(_held_at(path, 2, 0.01) for path, _record in _all_paths(PROFILE_MOVE))
    except (OSError, ValueError, RuntimeError):
        return False


def _take_mark(kind):
    """A new mark file, locked, with its record -> (handle, path), or (None, None)."""
    try:
        folder = os.path.join(path_utils.get_local_data_path(), "locks", RUNNING_DIR)
        os.makedirs(folder, exist_ok=True)
        for n in range(100):
            path = os.path.join(folder, f"{os.getpid()}-{time.time_ns()}-{n}.lock")
            if os.path.exists(path):
                continue
            handle = path_utils.try_lock(path)
            if handle is None:
                continue
            try:                                    # cleared by another's tidy-up between our open and our lock (POSIX)
                if os.path.samestat(os.fstat(handle.fileno()), os.stat(path)):
                    record = {"program": _program(), "pid": os.getpid(), "kind": kind,
                              "started": datetime.datetime.now().isoformat(timespec="seconds")}
                    _write_holder(path[:-len(".lock")] + ".json", record)
                    return handle, path
            except OSError:
                pass
            path_utils.release_lock(handle)
    except OSError:
        pass
    return None, None


def _drop_mark(handle, path):
    for doomed in (path[:-len(".lock")] + ".json",):
        try:
            os.remove(doomed)
        except OSError:
            pass
    path_utils.release_lock(handle)
    try:
        os.remove(path)
    except OSError:
        pass


def release_running():
    """Let go of this process's mark (the last of its in-process holds). Never raises."""
    with _registry_lock:
        if not _mark:
            return
        _mark["count"] -= 1
        if _mark["count"] > 0:
            return
        handle, path = _mark.pop("handle"), _mark.pop("path")
        _mark.clear()
    _drop_mark(handle, path)


def running_others():
    """The holder records of every running mark held by another program, oldest first; a mark whose program has died
    is tidied away (its OS lock was free). Never raises."""
    found = []
    try:
        folders = _running_folders()
    except (OSError, RuntimeError):
        return found
    own = _mark.get("path")
    for where in folders:
        try:
            names = sorted(n for n in os.listdir(where) if n.endswith(".lock"))
        except OSError:
            continue
        for name in names:
            path = os.path.join(where, name)
            if own and os.path.normcase(path) == os.path.normcase(own):
                continue
            handle = path_utils.try_lock(path)
            if handle is not None:                  # nobody holds it: a program that died
                _drop_mark(handle, path)
                continue
            record = None
            try:
                with open(path[:-len(".lock")] + ".json", "r", encoding="utf-8") as f:
                    record = json.load(f)
            except (OSError, ValueError):
                pass
            if not isinstance(record, dict):
                record = {"program": None, "pid": None, "kind": None, "started": None}
            if record.get("pid") == os.getpid():
                continue                            # this process's own (taken under another name)
            found.append(dict(record, mark=path))
    found.sort(key=lambda r: str(r.get("started") or ""))
    return found
