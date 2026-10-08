"""The library watched, not checked (L3.2; the user's answer L3.1-4, 2026-10-07: "let windows handle it but with the
fallback").

Why this exists
---------------
The Content Manager looked at the library twice a second while it was open — a `stat` of every folder that holds an
item — whether the window was in front, behind or minimized: ~1 % of a core at 2,000 files, ~10 % at 20,000, ~46 % at
200,000, and two wake-ups a second all day. Windows can report changes itself: one handle on the library folder (the
whole tree), one thread blocked inside Windows, nothing at all while nothing happens, and a file noticed ~1–2 ms after
it lands (the watch study, measured on synthetic libraries of 2k / 20k / 200k files).

What this module gives a window
-------------------------------
- `TreeWatch(root)`: the folders (relative to `root`, '/'-separated) that changed, each once it has been quiet for
  `SETTLE_S` (Windows reports a file when it is created; there is no "file closed" report), and `full` when Windows lost
  track (its buffer overflowed: one full look of the tree). A watch that can't start (a network share or a drive that
  can't report, not Windows) or that ends (the share went away, the folder was deleted) says so through `state`; the
  window then falls back to a slow look and retries.

Rules that bite
---------------
- **Standard library only** (`ctypes`); nothing else in the app touches Windows' change reports.
- **It only reads.** The watch never opens a file, never moves one; the store's sync decides what a change means.
- **Headless:** no Tk or Qt here; a window's worker thread waits on `wait()` / reads `take()`.
- A report is a hint: whatever arrives (or doesn't), the store's disk sync is the truth.
"""

import hashlib
import os
import sys
import threading
import time

SETTLE_S = 0.3            # a folder is synced once it has had no report for this long (a copy still running waits)
BUFFER = 65536            # bytes: the most Windows allows over a network share
RETRY_S = 300.0           # a watch that failed is tried again this often while the window is open (and on focus)
SLOW_S = 10.0             # the slow look (no watch: not Windows, a drive that can't report): this often, in front only
ROUND_S = 3600.0          # the safety round: once an hour while a window is open, none within an hour of a full look
ROUND_GAP_S = 2.0         # one batch of the round (`library_store.Round.step`) every this often

# The names a change report can carry that never mean a library change: the trash, the store's own files, the
# manifest copy, and the temp names downloads and editors write first.
_SKIP_PARTS = (".trash",)
_SKIP_NAMES = ("master_manifest.json", "_order.json", "desktop.ini")
_TEMP_SUFFIXES = (".part", ".ytdl", ".tmp", ".crdownload", ".partial", "-journal", "-wal", "-shm")
_TEMP_PREFIXES = ("~$", ".~")

BELL_SLOTS = 8            # windows that can listen to one store's bell at once (a ninth falls back to the slow look)

FILE_ACTION_MODIFIED = 3
ERROR_ALREADY_EXISTS = 183
ERROR_OPERATION_ABORTED = 995        # our own close()
ERROR_NOTIFY_ENUM_DIR = 1022         # Windows lost track: enumerate the tree


_KERNEL32 = []


def _k32():
    """kernel32 with the calls this module makes declared (loaded once, on first use; Windows only)."""
    if _KERNEL32:
        return _KERNEL32[0]
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.ReadDirectoryChangesW.restype = wt.BOOL
    k32.ReadDirectoryChangesW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, wt.BOOL, wt.DWORD,
                                          ctypes.POINTER(wt.DWORD), ctypes.c_void_p, ctypes.c_void_p]
    k32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.c_void_p]
    k32.CancelIoEx.restype = wt.BOOL
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.CloseHandle.restype = wt.BOOL
    k32.CreateEventW.restype = wt.HANDLE
    k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    k32.OpenEventW.restype = wt.HANDLE
    k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    k32.SetEvent.argtypes = [wt.HANDLE]
    k32.SetEvent.restype = wt.BOOL
    k32.WaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL, wt.DWORD]
    k32.WaitForMultipleObjects.restype = wt.DWORD
    k32.ResetEvent.argtypes = [wt.HANDLE]
    k32.ResetEvent.restype = wt.BOOL
    k32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(wt.DWORD), wt.BOOL]
    k32.GetOverlappedResult.restype = wt.BOOL
    _KERNEL32.append(k32)
    return k32


def watchable():
    """Can this system report a folder tree's changes? (Windows only, for now: macOS and Linux keep the slow look.)"""
    return sys.platform == "win32"


def ignored(rel):
    """A reported path ('/'-separated, relative to the root) that can't be a library change."""
    parts = rel.split("/")
    if any(p in _SKIP_PARTS for p in parts):
        return True
    name = parts[-1].lower()
    return name in _SKIP_NAMES or name.endswith(_TEMP_SUFFIXES) or name.startswith(_TEMP_PREFIXES)


def folders_of(root, rel, action=1):
    """The folder a report on `rel` asks to sync: `rel` itself when it is a folder now (a folder copied, moved or
    renamed in arrives as one report; its scoped sync takes what is under it), else its parent (a file added, changed,
    removed or renamed there; a sub-folder gone). A folder's own "modified" report asks for nothing: Windows sends it
    whenever something inside changes, and that change has its own report (syncing the folder would widen a drop
    into a show's folder to the whole tier)."""
    if os.path.isdir(os.path.join(root, *rel.split("/"))):
        return [] if action == FILE_ACTION_MODIFIED else [rel]
    return [rel.rsplit("/", 1)[0] if "/" in rel else ""]


class TreeWatch:
    """One handle on `root` and one thread blocked in ReadDirectoryChangesW over the whole tree.

    `state`: "watching" · "fallback" (it couldn't start: not Windows, a drive or share that can't report, the folder
    missing) · "ended" (it stopped: the share went away, the folder was deleted; `error` holds Windows' code) ·
    "closed". A window reads `take()` after `wait()` returns; on "fallback" / "ended" it runs the slow look and calls
    `start()` again on focus and every `RETRY_S`."""

    def __init__(self, root, buffer=BUFFER, settle=SETTLE_S, under=None, wake=None):
        self.root = root
        self.buffer = buffer
        self.settle = settle
        self.under = tuple(under) if under else None          # only reports under these top-level folders count
        self.subtree = True                                   # the whole tree
        self.notify = 0x1 | 0x2 | 0x8 | 0x10                  # names, folders, size, last write
        self.state = "closed"
        self.error = None
        self.reports = 0                                      # wake-ups of the watch thread (an idle watch has none)
        self._pending = {}                                    # folder -> monotonic time of its last report
        self._full = False
        self._lock = threading.Lock()
        self._changed = wake or threading.Event()             # a window's worker may share its own wake event
        self._handle = self._io = self._stop = None
        self._thread = None

    # --- life ------------------------------------------------------------------------------------------ #

    def start(self):
        """Open the watch (again). Returns True when it is watching."""
        if self.state == "watching":
            return True
        self.close()
        self.error = None
        if not watchable() or not os.path.isdir(self.root):
            self.state = "fallback"
            return False
        try:
            k32 = _k32()
            # list the folder; share all; open existing; a folder (backup semantics) + overlapped: a read blocked on
            # a network share must end when asked (a synchronous one ignored CancelIoEx there: CloseHandle hung).
            handle = k32.CreateFileW(self.root, 0x0001, 0x7, None, 3, 0x02000000 | 0x40000000, None)
            if handle in (None, -1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF):
                raise OSError(_last_error(), "the folder can't be watched")
        except OSError as exc:
            self.state, self.error = "fallback", getattr(exc, "errno", None)
            return False
        self._k32, self._handle = k32, handle
        self._io = k32.CreateEventW(None, True, False, None)            # the read's completion (manual reset)
        self._stop = k32.CreateEventW(None, True, False, None)          # close() asks the thread to end
        self.state = "watching"
        self._thread = threading.Thread(target=self._run, name="library-watch", daemon=True)
        self._thread.start()
        return True

    def close(self):
        """Stop watching: the thread cancels its read and ends; then the handles close."""
        handle = self._handle
        if handle is None:
            return
        if self.state == "watching":
            self.state = "closed"
        self._k32.SetEvent(self._stop)
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)
        self._handle = None
        for h in (handle, self._io, self._stop):
            try:
                self._k32.CloseHandle(h)
            except Exception:
                pass
        self._io = self._stop = None
        self._changed.set()

    @property
    def alive(self):
        return self.state == "watching" and self._thread is not None and self._thread.is_alive()

    # --- the window's side ----------------------------------------------------------------------------- #

    def wait(self, timeout=None):
        """Block until a report may be ready (or `timeout`): the next settle time when folders are pending."""
        due = self.due()
        if due is not None:
            timeout = due if timeout is None else min(timeout, due)
        got = self._changed.wait(timeout)
        self._changed.clear()
        return got

    def due(self, now=None):
        """Seconds until the earliest pending folder settles, or None when none is pending."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._full:
                return 0.0
            if not self._pending:
                return None
            return max(0.0, min(self._pending.values()) + self.settle - now)

    def take(self, now=None):
        """-> (folders settled since the last take, full): `full` means one full look of the tree instead."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._full:
                self._full = False
                self._pending.clear()
                return [], True
            ready = sorted(f for f, t in self._pending.items() if now - t >= self.settle)
            for f in ready:
                del self._pending[f]
        return _outermost(ready), False

    # --- the watch thread ------------------------------------------------------------------------------ #

    def _read(self, buf, got):
        """One ReadDirectoryChangesW (names, folders, size, last write; the whole tree), waited for alongside the stop
        event. -> True (`got` bytes in `buf`), False (failed: `_last_error()`), None (close() asked). Tests replace it."""
        import ctypes
        import ctypes.wintypes as wt
        k32 = self._k32
        ov = _Overlapped()
        ov.hEvent = self._io
        k32.ResetEvent(self._io)
        if not k32.ReadDirectoryChangesW(self._handle, buf, len(buf), self.subtree, self.notify, None,
                                         ctypes.byref(ov), None):
            return False
        handles = (wt.HANDLE * 2)(self._io, self._stop)
        if k32.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF) != 0:
            k32.CancelIoEx(self._handle, ctypes.byref(ov))
            k32.GetOverlappedResult(self._handle, ctypes.byref(ov), ctypes.byref(got), True)   # ov outlives the read
            return None
        return bool(k32.GetOverlappedResult(self._handle, ctypes.byref(ov), ctypes.byref(got), False))

    def _run(self):
        import ctypes
        import ctypes.wintypes as wt
        buf = ctypes.create_string_buffer(self.buffer)
        got = wt.DWORD()
        while True:
            ok = self._read(buf, got)
            if ok is None:
                return
            self.reports += 1
            if not ok:
                err = _last_error()
                if err == ERROR_NOTIFY_ENUM_DIR:
                    self._overflow()
                    continue
                if self._handle is not None and err != ERROR_OPERATION_ABORTED:
                    self.state, self.error = "ended", err
                self._changed.set()
                return
            if got.value == 0:
                self._overflow()
                continue
            self._note(_parse(buf.raw[:got.value], actions=True))

    def _overflow(self):
        with self._lock:
            self._full = True
        self._changed.set()

    def _note(self, reports):
        now = time.monotonic()
        added = False
        with self._lock:
            for action, name in reports:
                rel = name.replace("\\", "/")
                if ignored(rel) or (self.under and rel.split("/", 1)[0] not in self.under):
                    continue
                for folder in folders_of(self.root, rel, action):
                    if not folder:
                        continue                              # the root itself: only its tier folders matter
                    self._pending[folder] = now
                    added = True
        if added:
            self._changed.set()


class FileWatch(TreeWatch):
    """One folder (not its tree), and only the files named in `names`: the library's copy (`master_manifest.json`),
    which every writer saves by a rename (`os.replace`, reported at once). `take()` -> ([], True) once one of them
    changed (or Windows lost track): look at it."""

    def __init__(self, folder, names, wake=None):
        super().__init__(folder, buffer=4096, settle=0.0, wake=wake)
        self.names = {n.lower() for n in names}
        self.subtree = False
        self.notify = 0x1 | 0x10                              # names (a save by rename), last write (one in place)

    def _note(self, reports):
        if any(name.replace("\\", "/").lower() in self.names for _action, name in reports):
            self._overflow()


def _identity(path):
    """The folder at `path` now — (device, file index), "" when there is none — to tell a root renamed away (a watch
    follows its folder, and Windows sends no report for the watched folder's own rename) from the one watched."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return (st.st_dev, st.st_ino) if st.st_ino else None


class Lookout:
    """A library window's eyes on its store and folders (L3.2), headless — the Content Manager's worker today, the
    new window's tomorrow: the tree watch on the language's data folder, a watch on the copy, the store's bell, and
    the timers of the slow look, the watch's retry and the hourly round. The window's worker loops:

        lookout.wait()                    # blocks until something is due: idle and watched, the round (an hour)
        jobs = lookout.jobs()             # what is due now (`Jobs`)
        ...                               # the syncs; `looked()` after every full look

    The window sets `front` (focused and not minimized: the slow look runs only then) and calls `focus()` before the
    full look a focus return or Refresh makes (the watch's health: restarted when it ended or its root moved)."""

    def __init__(self, data_dir, under=None, db_path=None, copy=None, wake=None, make_round=None,
                 clock=time.monotonic):
        self.wake = wake or threading.Event()
        self.clock = clock
        self.tree = TreeWatch(data_dir, under=under, wake=self.wake)
        self.copy = FileWatch(os.path.dirname(copy), [os.path.basename(copy)], wake=self.wake) if copy else None
        self.db_path = db_path
        self.bell = None
        self.make_round = make_round                          # () -> a `library_store.Round`
        self.round = None
        self.front = True
        self.wakes = 0                                        # the worker's wake-ups (an idle watched window: none)
        self.slow_looks = 0
        self._root = None
        now = clock()
        self._last_full = now                                 # the open's full look follows `open()` at once
        self._last_slow = None
        self._last_try = now
        self._round_next = None

    def open(self):
        self._start_tree()
        if self.copy is not None:
            self.copy.start()
        if self.db_path:
            self.bell = Bell(self.db_path, self.wake.set)
        return self

    def close(self):
        self.tree.close()
        if self.copy is not None:
            self.copy.close()
        if self.bell is not None:
            self.bell.close()

    def _start_tree(self):
        self.tree.close()
        started = self.tree.start()
        self._root = _identity(self.tree.root) if started else None
        return started

    @property
    def slow(self):
        """No watch (or no bell to hear other processes by): the slow look stands in, in front only."""
        return not self.tree.alive or (self.db_path is not None and (self.bell is None or self.bell.slot is None))

    def set_front(self, front):
        """The window's thread: in front or not. Coming to the front in fallback wakes the worker for its look."""
        was, self.front = self.front, bool(front)
        if self.front and not was and self.slow:
            self.wake.set()

    def focus(self, now=None):
        """Before a focus return's (or Refresh's) full look: restart the watch if it ended, failed or its root moved;
        give the copy's watch and the bell another try. -> True when the tree watch was restarted."""
        now = self.clock() if now is None else now
        self._last_try = now
        restarted = False
        if watchable():
            if not self.tree.alive or _identity(self.tree.root) != self._root:
                restarted = self._start_tree()
            if self.copy is not None and not self.copy.alive:
                self.copy.start()
            if self.db_path and (self.bell is None or self.bell.slot is None):
                if self.bell is not None:
                    self.bell.close()
                self.bell = Bell(self.db_path, self.wake.set)
        return restarted

    def looked(self, now=None):
        """A full look just ran: the round restarts its hour, and one under way is dropped (the look covered it)."""
        self._last_full = self.clock() if now is None else now
        self.round = self._round_next = None

    def timeout(self, now=None):
        """Seconds until something is due (the worker's wait), never None: an idle watched window waits for the
        round."""
        now = self.clock() if now is None else now
        due = [self._last_full + ROUND_S if self._round_next is None else self._round_next]
        if self.tree.state == "watching":
            settle = self.tree.due(now)
            if settle is not None:
                due.append(now + settle)
        elif watchable():
            due.append(self._last_try + RETRY_S)
        if self.slow and self.front:
            due.append(now if self._last_slow is None else self._last_slow + SLOW_S)
        return max(0.0, min(due) - now)

    def wait(self, now=None):
        got = self.wake.wait(self.timeout(now))
        self.wake.clear()
        self.wakes += 1
        return got

    def jobs(self, now=None):
        """What is due now -> `Jobs(folders, full, copy, slow, round)`: the settled folders to sync; a full look
        (Windows lost track, or a watch that came back missed what happened meanwhile); the copy changed; the slow
        look's turn (`DiskPoll`); a round batch to run (`round.step()`)."""
        now = self.clock() if now is None else now
        folders, full = self.tree.take(now)
        copy = bool(self.copy is not None and self.copy.take(now)[1])
        if self.tree.state != "watching" and watchable() and now - self._last_try >= RETRY_S:
            self._last_try = now
            full = self._start_tree() or full
        slow = self.slow and self.front and (self._last_slow is None or now - self._last_slow >= SLOW_S)
        if slow:
            self._last_slow = now
            self.slow_looks += 1
        step = None
        if self._round_next is None and now - self._last_full >= ROUND_S and self.make_round is not None:
            self.round, self._round_next = self.make_round(), now
        if self._round_next is not None and now >= self._round_next:
            step = self.round
            self._round_next = now + ROUND_GAP_S
        return Jobs(folders, full, copy, slow, step)

    def round_done(self, now=None):
        """The round's last batch ran: the next one in an hour."""
        self._last_full = self.clock() if now is None else now
        self.round = self._round_next = None


class Jobs:
    __slots__ = ("folders", "full", "copy", "slow", "round")

    def __init__(self, folders, full, copy, slow, round):
        self.folders, self.full, self.copy, self.slow, self.round = folders, full, copy, slow, round


def _overlapped_type():
    import ctypes
    import ctypes.wintypes as wt

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", wt.DWORD),
                    ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]
    return OVERLAPPED


def _Overlapped():
    if not _OVERLAPPED:
        _OVERLAPPED.append(_overlapped_type())
    return _OVERLAPPED[0]()


_OVERLAPPED = []


def _parse(raw, actions=False):
    """FILE_NOTIFY_INFORMATION records -> the names they carry (relative to the watched folder, '\\'-separated), or
    (action, name) pairs with `actions`."""
    out, off = [], 0
    while off + 12 <= len(raw):
        nxt = int.from_bytes(raw[off:off + 4], "little")
        action = int.from_bytes(raw[off + 4:off + 8], "little")
        ln = int.from_bytes(raw[off + 8:off + 12], "little")
        name = raw[off + 12:off + 12 + ln].decode("utf-16-le", "replace")
        out.append((action, name) if actions else name)
        if not nxt:
            break
        off += nxt
    return out


def _outermost(folders):
    """Drop a folder whose ancestor is in the list: a scoped sync takes what is under each folder it's given."""
    out = []
    for f in sorted(folders):
        if not any(f == o or f.startswith(o + "/") for o in out):
            out.append(f)
    return out


def _last_error():
    import ctypes
    return ctypes.get_last_error()


# --- the writers' bell --------------------------------------------------------------------------------------- #
#
# Every write to the store, from any process (the command line, Connect, hato's hand-off, the store's helper, the
# dashboard, a second window), commits in one place, `Store._writing`, and rings the store's bell just after. A window
# listening wakes at once (~0.05 ms) and reads `data_version` / the feed as before: the bell is only a hint, the store's
# versions stay the truth. One named Windows event per listening window ("slots"), so every window is woken and none
# can take another's ring; a window that crashes frees its slot with its process. (Watching the store's own file
# instead would be late by seconds whenever a save isn't flushed to disk at once: the watch study, §2.2.)

def bell_name(db_path, slot):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(db_path)).encode("utf-8")).hexdigest()[:16]
    return f"Local\\Surasura-bell-{key}-{slot}"


def ring(db_path):
    """Wake every window listening to this store. Never raises (the commit it follows has already succeeded).
    Returns how many listeners were rung."""
    if not watchable():
        return 0
    rung = 0
    try:
        k32 = _k32()
        for slot in range(BELL_SLOTS):
            handle = k32.OpenEventW(0x0002, False, bell_name(db_path, slot))          # EVENT_MODIFY_STATE
            if handle:
                k32.SetEvent(handle)
                k32.CloseHandle(handle)
                rung += 1
    except Exception:
        pass
    return rung


class Bell:
    """A window's ear on one store: `on_ring()` is called (on the bell's own thread) after another process commits.
    `slot` is None when it can't listen (not Windows, every slot taken): the window keeps its slow look."""

    def __init__(self, db_path, on_ring):
        self.db_path = db_path
        self.on_ring = on_ring
        self.slot = None
        self.rings = 0
        self._event = self._stop = None
        self._thread = None
        if not watchable():
            return
        try:
            k32 = _k32()
            for slot in range(BELL_SLOTS):
                handle = k32.CreateEventW(None, False, False, bell_name(db_path, slot))    # auto-reset, not set
                if not handle:
                    continue
                if _last_error() == ERROR_ALREADY_EXISTS:                               # another window's slot
                    k32.CloseHandle(handle)
                    continue
                self._k32, self._event, self.slot = k32, handle, slot
                break
            if self._event is None:
                return
            self._stop = k32.CreateEventW(None, True, False, None)
            self._thread = threading.Thread(target=self._run, name="library-bell", daemon=True)
            self._thread.start()
        except Exception:
            self.close()

    def _run(self):
        import ctypes.wintypes as wt
        handles = (wt.HANDLE * 2)(self._event, self._stop)
        while True:
            got = self._k32.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF)
            if got != 0:                                   # the stop event, or the wait failed: end
                return
            self.rings += 1
            try:
                self.on_ring()
            except Exception:
                pass

    def close(self):
        if self._stop:
            self._k32.SetEvent(self._stop)
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)
        for h in (self._event, self._stop):
            if h:
                try:
                    self._k32.CloseHandle(h)
                except Exception:
                    pass
        self._event = self._stop = None
        self.slot = None
