"""The settings service (W1.3; the window's spec 04 §4.2): what a window reads and changes in settings.json.

`get()` is a frozen copy of the settings as `settings_manager.load_settings()` reads them (the defaults filled in, a
saved value always winning), with the changes not yet written laid over it, so a window reading right after `set` sees
its own change. `set(changes)` writes only the keys it is given, onto the file as it is (`save_keys`' rule, CLAUDE.md §6):
the whole file is never rebuilt, so a key another program or window saved meanwhile is never reverted or dropped — and
a first save (no file yet) writes those keys alone, never every default.

Every change joins one pending dict, and the writer (`settings_manager.SettingsWriter`: off the caller's thread, under
the `settings` lock, atomic, retried while the lock is held, never dropped) gets a build that applies every pending
change to the file as it is when written — so a change 0.1 s after another is never lost, though the writer keeps only
its newest build. A key leaves the pending dict once a write carried it (a key set again meanwhile stays). Nothing here
waits on the caller's thread: `set` and `get` are safe on a window's (≤ 4 ms, measured in the tests); `reload` and
`flush` wait, so a window calls them from a worker.

Keys are top-level names (`theme`) or dotted paths into the `logic` block (`logic.selection.band`); a value replaces
what is at its key. `kind(key, language)` says whether a change is `analysis` (the journey goes stale), `report` (a
re-render) or `neither` (`app/settings_placement.py`).
"""
import copy
import json
import os
import shutil
import threading
import time
from types import MappingProxyType

from app import settings_manager
from app import settings_placement


def freeze(value):
    """A read-only deep copy: dicts become mappings nobody can change, lists tuples."""
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    """A plain, changeable deep copy of a frozen value (for code that takes a dict)."""
    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


def _copy(value):
    """A copy of a settings value: JSON's containers copied all the way down, anything else as it is."""
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy(v) for v in value]
    return value


def put(settings, key, value):
    """Set `key` (top-level, or a dotted `logic.…` path) in a settings dict, making the dicts on the way."""
    parts = key.split(".") if key.startswith("logic.") else [key]
    node = settings
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = _copy(value)


def file_as_is():
    """settings.json as the file holds it — never the defaults: no file yet is `{}` (a first save writes only the keys
    it is given, never every default and every module's), and a file that can't be read as an object is kept beside
    it (`settings.json.unreadable`) before the save starts it again from `{}`, as the 2.x dashboard's save did."""
    from app.path_utils import get_user_file, read_text
    path = get_user_file("settings.json")
    if not os.path.exists(path):
        return {}
    try:
        settings = json.loads(read_text(path))
        if isinstance(settings, dict):
            return settings
    except (OSError, ValueError):
        pass
    try:
        shutil.copy2(path, path + ".unreadable")
    except OSError:
        pass
    return {}


class SettingsService:
    """One per process (a window makes one at start). `on_error(e)` runs on the writer's worker when a write meets a
    held lock or a refused file (it is retried); `delay` is the writer's debounce. `writer`: a window's own
    `SettingsWriter` to write through (its `on_saved` still runs, after the service's). `load`: read the file now (a
    window that makes the service on its own thread passes False and calls `reload()` from a worker)."""

    def __init__(self, delay=0.25, on_error=None, wait=settings_manager.LOCK_WAIT, load=True, writer=None):
        self._lock = threading.Lock()
        self._landed_cond = threading.Condition(self._lock)
        self._pending = {}              # key -> (value, seq): the changes not yet written
        self._updates = []              # (seq, update(settings)) not yet written
        self._seq = 0
        self._landed_upto = 0           # every change up to this seq is written and read back
        self._carried = {}              # id(the dict a build returned) -> ({key: seq}, upto): what that write carries
        self._base = None               # load_settings() as of the last load or landed write
        self._frozen = None             # get()'s answer, rebuilt after a change
        self._subscribers = []
        if writer is None:
            writer = settings_manager.SettingsWriter(delay=delay, on_saved=self._landed, on_error=on_error, wait=wait)
        else:
            theirs = writer.on_saved

            def landed(written):
                self._landed(written)
                if theirs is not None:
                    theirs(written)
            writer.on_saved = landed
        self.writer = writer
        if load:
            self._base = settings_manager.load_settings()

    # --- reading ------------------------------------------------------------------------------------------------ #
    def get(self):
        """The settings now (frozen): the file as last read, with every change not yet written laid over it. A copy in
        memory once the file was read (at construction, or by `reload()` on a worker)."""
        with self._lock:
            if self._frozen is None:
                base = copy.deepcopy(self._base) if self._base is not None else settings_manager.load_settings()
                for key, (value, _seq) in self._pending.items():
                    put(base, key, value)
                self._frozen = freeze(base)
            return self._frozen

    def reload(self):
        """Read settings.json again (at start, or after another program changed it). Reads the file: a worker's."""
        base = settings_manager.load_settings()
        with self._lock:
            self._base = base
            self._frozen = None
        return self.get()

    @staticmethod
    def kind(key, language):
        """`analysis` · `report` · `neither` for a change of `key` in `language` (app/settings_placement.py)."""
        return settings_placement.kind(key, language)

    def stales(self, keys, language):
        """True when changing any of `keys` makes `language`'s journey stale (an analysis or report setting)."""
        return any(self.kind(k, language) != "neither" for k in keys)

    # --- changing ----------------------------------------------------------------------------------------------- #
    def set(self, changes, update=None, now=False):
        """Queue `changes` ({key: value}) for settings.json and return at once. `update(settings)`, when given, changes
        the file's dict in place after them, inside the lock — kept for the dashboard's migrations of 2.x keys (the Anki
        address; the update's old failure mark). Safe on a window's thread. `now`: write them (and every change still
        pending) on this thread instead, holding the `settings` lock for the read and the write — a caller with no
        window (a test harness, a headless tool), never a window's thread."""
        if not changes and update is None:
            return
        for key in changes:
            if not isinstance(key, str) or not key or (("." in key) and not key.startswith("logic.")):
                raise ValueError(f"not a settings key: {key!r}")
        with self._lock:
            self._seq += 1
            for key, value in changes.items():
                self._pending[key] = (_copy(value), self._seq)
            if update is not None:
                self._updates.append((self._seq, update))
            self._frozen = None
        if now:
            held = settings_manager._settings_lock(settings_manager.LOCK_WAIT)
            try:
                settings = self._build()
                if settings_manager.save_settings(settings) is not False:
                    self._landed(settings)
            finally:
                if held is not None:
                    held.release()
            return
        self.writer.submit(self._build)

    def flush(self, timeout=None):
        """Wait until every change so far is written and read back (a worker's call, never a window's thread). True
        when it is."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            target = self._seq
        if not self.writer.flush(timeout):
            return False
        with self._landed_cond:
            while self._landed_upto < target:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._landed_cond.wait(left)
        return True

    def pending(self):
        with self._lock:
            return sorted(self._pending)

    def subscribe(self, callback):
        """`callback(keys)` after each write lands, with the keys it wrote — on the writer's worker."""
        with self._lock:
            self._subscribers.append(callback)

    # --- the writer's side (its worker, inside the `settings` lock) --------------------------------------------- #
    def _build(self):
        with self._lock:
            entries = {key: (_copy(value), seq) for key, (value, seq) in self._pending.items()}
            updates = list(self._updates)
            upto = self._seq
        settings = file_as_is()
        for key, (value, _seq) in entries.items():
            put(settings, key, value)
        for _seq, update in updates:
            update(settings)
        with self._lock:
            self._carried[id(settings)] = ({key: seq for key, (_v, seq) in entries.items()}, upto)
        return settings

    def _landed(self, written):
        base = settings_manager.load_settings()                   # the file as written, the defaults filled in
        with self._lock:
            carried, upto = self._carried.pop(id(written), ({}, None))
            for key, seq in carried.items():
                if key in self._pending and self._pending[key][1] == seq:
                    del self._pending[key]
            if upto is not None:
                self._updates = [(seq, u) for seq, u in self._updates if seq > upto]
                self._landed_upto = max(self._landed_upto, upto)
                # Builds never written (a write retried builds again) carry nothing newer: let them go.
                self._carried = {k: v for k, v in self._carried.items() if v[1] > self._landed_upto}
            self._base = base
            self._frozen = None
            self._landed_cond.notify_all()
            subscribers = list(self._subscribers)
        keys = sorted(carried)
        for callback in subscribers:
            try:
                callback(keys)
            except Exception as e:                                # a subscriber's fault never stops the writer
                print(f"Settings: a listener failed: {e}")
