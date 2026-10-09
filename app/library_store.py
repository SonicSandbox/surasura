"""The library store: the library's order, tiers and state in one small SQLite database per install and
language (`docs/redesign/Library_Store_Spec.md`, L1.1, signed at G1.1 on 2026-10-04).

Why this exists
---------------
`User Files/<lang>/master_manifest.json` held the library's order, and every change rewrote the whole
file: a drag at 2,000 items rewrote 1.3 MB, a crash mid-save could cost the order, and Undo put back a
whole-manifest snapshot that erased every later drag. Here every change is one short transaction that
touches only the rows it changed: a move is saved for good in about 1 ms at any library size, two
writers take turns instead of overwriting each other, and a crash leaves the old order or the new one.

`master_manifest.json` stays, as a copy this module writes (`maintain`, in its own process): the same
shape, so older versions and every reader keep working, plus a `surasura_library` key that carries the
store's extra state and names the store that wrote it.

Phase 1 (L1.2) built it as new files only, with `STORE_LIVE` False. Phase 2 (L2.1, 2.5) switches the app
over: `STORE_LIVE` is True. Under pytest every open still refuses unless `SURASURA_TEST_ROOT` is set, so a
test can't migrate the real library.

Rules that bite (spec §6.2, §8)
-------------------------------
- **Every write goes through `Store._writing()`**, under the cross-process write lock (`<db>.wlock`):
  SQLite 3.39.4, which 2.5 ships, carries the WAL-reset bug (two connections writing or checkpointing at
  the same instant can corrupt the database silently). `query_only` is on outside the helper, so a bare
  write anywhere else fails. No `wal_checkpoint` outside `Store.checkpoint` (a test scans for it).
- **One connection per thread** (never `check_same_thread=False`); a worker opens its own `Store`.
- **A command that changes nothing commits nothing**: no version bump, no write, no mtime change.
- **The store never moves a file** (I3). File work stays with the caller, outside transactions.
- **Never `DROP TABLE`, never delete the database** (I2). Damage is set aside, never deleted.
- **Headless:** no Tk, Qt or pandas here (I9).
"""

import hashlib
import json
import ntpath
import os
import random
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import uuid
from collections import namedtuple
from contextlib import contextmanager

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import library_watch
from app.path_utils import (CONTENT_EXTENSIONS, backup_to_trash, infer_source_type, read_source_marker,
                            restart_trash_clock)

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None
    import fcntl


# The switch (WP-L8, 2.5): the app keeps its library order in the store. False turns every open into a refusal
# (the app then runs as 2.4 did, in JSON mode).
STORE_LIVE = True

STORE_SCHEMA = 2                 # PRAGMA user_version this code writes (2: 3.0's works, feed and line, L3.1)
COPY_FORMAT = 1                  # surasura_library.format
MANIFEST_NAME = "master_manifest.json"
PHASES = ("PHASE_1_NOW", "PHASE_2_SOON", "PHASE_3_LATER")

# name: (phase_key, tier folder, analysed, read order) — the store's one map (spec §6.3). The items.tier
# CHECK lists the same five names; a test holds them equal. 3.0's Finished is 'graduated' relabelled.
TIERS = {
    "now":       ("PHASE_1_NOW",   "HighPriority", True,  1),
    "soon":      ("PHASE_2_SOON",  "LowPriority",  True,  2),
    "goal":      ("PHASE_3_LATER", "GoalContent",  True,  3),
    "graduated": (None,            None,           False, 9),
    "arrivals":  (None,            None,           False, 0),
}
ANALYSED = tuple(t for t, v in TIERS.items() if v[2])                    # now, soon, goal
TIER_OF_PHASE = {v[0]: t for t, v in TIERS.items() if v[0]}
TIER_OF_FOLDER = {v[1]: t for t, v in TIERS.items() if v[1]}
FOLDER_OF_TIER = {t: v[1] for t, v in TIERS.items() if v[1]}
TIER_LABELS = {"now": "NOW", "soon": "Soon", "goal": "6+ Months", "graduated": "Graduated",
               "arrivals": "New arrivals"}
CURRENT = ("now", "soon")        # Current = NOW then Soon; the Soon line is their boundary
HATO_FOLDER = "HighPriority/Hato"  # hato's drop folder: its files land at the top of NOW through 2.x
GRADUATED_FOLDER = "Graduated"
MINE_LINE_DEFAULT = 20           # a lean owned by Connect's spec and the window (settled at G2.2)
SOON_LINE_NEW = 25               # a library 3.0 builds new: the Soon line after 25 rows of Current (Q2-4)
SEARCH_FOLD_VERSION = 1          # meta.search_fold: the version of `search_fold` the stored keys were made with
FEED_KEEP = 24 * 3600            # s: the feed's tombstones (`gone`) are kept a day (L2.2 04 §4.1)
LOG_KEEP_DAYS = 30               # the placement log keeps at most the trash clock's length

# Per title (L2.2 05 §5.4): the window's 11 types, and where a work's cover came from (05 §5.5)
MEDIA_TYPES = ("anime", "drama", "movie", "youtube", "podcast", "audiobook", "book", "lightnovel", "manga",
               "game", "text")
COVER_SOURCES = ("anilist", "tmdb", "youtube", "file", "user", "generated")
SKIP_NAMES = ("master_manifest.json", "_order.json", "desktop.ini")

# maintain's exit codes (spec §6.7); register_headless adds 6: the path can't be registered (not in the library)
EXIT_DONE, EXIT_FAILED, EXIT_USAGE, EXIT_NOTHING, EXIT_NEEDS_YOU, EXIT_BUSY = 0, 1, 2, 3, 4, 5
EXIT_BAD_DATA = 6

LOCK_TIMEOUT = 5.0               # the write lock and SQLite's busy wait
LOCK_RETRY = 0.0005              # 0.5 ms between tries of the OS write lock
BUSY_AT_OPEN = 1.0               # "database is locked" at open is retried this long (§6.2)
MAINT_WAIT = 10.0                # a helper waits this long for the maintenance lock, then exits 5
BAK_KEEP = 10                    # the store's own .bak files kept (R-5)

# Integer meta keys, and what a fresh store holds (spec §6.3, §6.8 step 3)
INT_META = ("epoch", "state_version", "order_version", "availability_version", "pins_version",
            "analysed_order_version", "planned_order_version", "planned_pins_version",
            "last_export_version", "copy_dirty", "log_seq", "mine_line", "arrivals_on", "soon_line",
            "feed_floor", "search_fold")


class StoreError(Exception):
    """Base for every store failure a caller may want to show (never a modal: the caller decides)."""


class StoreRefused(StoreError):
    """The store refuses to open: Phase 1 without a test root, or a test without isolation (I7)."""


class StoreReadOnly(StoreError):
    """The store can't be written: damage found, a newer schema, or an I/O error at open (§6.9)."""


class StoreBusy(StoreError):
    """A write couldn't get the write lock in 5 s; nothing was written (§6.9)."""


class StoreConflict(StoreError):
    """The commit's re-check found one of the command's own items or keys changed since its check
    (§6.6, "file work and commands"): nothing was written; the caller undoes its file work."""


class UndoRefused(StoreError):
    """An undo record from another epoch (a rebuild or Repair happened since, §6.6)."""


class NotInLibrary(StoreError):
    """`register` was handed a path outside the library's data folder: refused before anything is written."""


# ------------------------------------------------------------------------------------------------ #
# Paths and keys (spec §6.1, §6.4)
# ------------------------------------------------------------------------------------------------ #

def path_key(path, platform=sys.platform):
    """The one comparison key for two paths, as the platform's file system compares them. NTFS ignores
    case, but NFC and NFD are different names there (both exist side by side); APFS / HFS+ ignore case
    and normalization; Linux is exact. `ntpath`, not `os.path`, so a test can check every platform."""
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if platform == "win32":
        return ntpath.normcase(p).replace("\\", "/")   # normcase also turns "/" into "\\"; keys keep "/"
    if platform == "darwin":
        return unicodedata.normalize("NFC", p).casefold()
    return p


_KATAKANA_FOLD = {c: c - 0x60 for c in range(0x30A1, 0x30F7)}     # ァ…ヶ → ぁ…ゖ
_SPACES = re.compile(r"\s+")


def search_fold(text, language=None):
    """The one key for a title and a query alike (L2.2 05 §5.3, 06 §6.8): NFKC, case-folded, katakana as hiragana,
    whitespace runs as one space; Chinese also reads Traditional as Simplified (`app/zh_script`'s tables, loaded on
    the first Chinese fold). Pure: the stored keys are made with it, `meta.search_fold` says which version."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", str(text)).casefold().translate(_KATAKANA_FOLD)
    if language == "zh":
        from app.zh_script import to_simplified
        folded = to_simplified(folded)
    return _SPACES.sub(" ", folded).strip()


def _below_tier(rel):
    """The folder a file sits in, below its tier folder ('HighPriority/Frieren/Season 1/x.srt' → 'Frieren/Season 1'),
    as written; '' for a loose file (directly in a tier folder, or in hato's drop folder)."""
    folder = _rel_dir(_strip(rel))
    if not folder or path_key(folder) == path_key(HATO_FOLDER):
        return ""
    parts = folder.split("/")
    if parts[0] in TIER_OF_FOLDER or parts[0] == GRADUATED_FOLDER:
        parts = parts[1:]
    return "/".join(parts)


def _in_hato(rel):
    """A file in hato's drop folder or a folder below it (as `_destination` and read-only mode read it)."""
    dkey, hato = path_key(_rel_dir(_strip(rel))), path_key(HATO_FOLDER)
    return dkey == hato or dkey.startswith(hato + "/")


def folder_key_of(rel):
    """A work's folder key (L2.2 02 §2.6): `path_key` of the file's folder below its tier folder, so `Frieren/Season 1`
    in NOW and in 6+ Months is one title while `A/Season 1` and `B/Season 1` stay apart; None for a loose file."""
    below = _below_tier(rel)
    return path_key(below) if below else None


def _test_root():
    return os.environ.get("SURASURA_TEST_ROOT") or None


def _guard():
    """I7 / K5: tests never touch the real library or the per-user folders, enforced here."""
    root = _test_root()
    if root:
        return root
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise StoreRefused("a test opened the library store without SURASURA_TEST_ROOT (I7)")
    if not STORE_LIVE:
        raise StoreRefused("the library store is not switched on yet (STORE_LIVE = False)")
    return None


def _local_root():
    """The per-user LOCAL data folder (spec §6.1): never %APPDATA%, which roams and can be redirected
    to a network share where WAL doesn't work (K22): `path_utils`' one local root (S1.1 K100)."""
    root = _guard()
    if root:
        return os.path.join(root, "local")
    from app.path_utils import _local_data_root
    return _local_data_root()


def library_db_path(language, data_dir):
    """`library_<lang>_<key>.db`, one per install and language: the key comes from the data folder's
    real path, so a checkout and an installed copy never share a library, and a moved folder gets a
    new (empty) database that rebuilds from the JSON copy (§6.8)."""
    key = hashlib.sha256(path_key(os.path.realpath(data_dir)).encode("utf-8")).hexdigest()[:16]
    name = f"library_{language}_{key}.db"
    root = _guard()
    if root:
        return os.path.join(root, "index", name)
    return os.path.join(_local_root(), "libraries", name)


def update_staged_path():
    """The updater's own marker, `pending_update.json` beside the app (S1.1): written at the hand-over,
    deleted by its helper once the files are swapped. The store adds no second marker."""
    from app.path_utils import get_user_data_path
    return os.path.join(get_user_data_path(), "pending_update.json")


def update_lock_path():
    """S1.1's update lock, held from "Update now" until the hand-over (`updater.update_lock_path`)."""
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "locks", "update.lock")


# A probe of the update lock (below) holds it for well under a millisecond; an update holds it from "Update now"
# until the hand-over. Held at every look over this window = an update (P1.2: two command-line calls probing at once
# must never read each other's probe as one).
PROBE_LOOKS = 6
PROBE_GAP = 0.02


def update_staged(max_age=3600.0, looks=1):
    """True while an update is staged (§6.7): the update lock is held (Update now, until the hand-over —
    by this process too: a lock taken on another handle is refused), or the updater's marker exists
    while its helper swaps the files. A marker older than an hour (a crashed update) is ignored.

    A look takes the lock for a moment, so another caller's look can find it held: the command line looks
    `PROBE_LOOKS` times (~0.1 s) and only a lock held at every look is an update; a window's thread looks once
    (`looks=1`, never waiting). An update lock file this process can't open is no update (logged): read as one,
    every command would answer `update-staged` for good."""
    try:
        age = time.time() - os.path.getmtime(update_staged_path())
        if age < max_age:
            return True
    except OSError:
        pass
    try:
        from app.path_utils import release_lock, try_lock
        path = update_lock_path()
        for look in range(max(1, looks)):
            if not os.path.exists(path):
                return False
            held = try_lock(path)
            if held is not None:
                release_lock(held)
                return False
            if look < looks - 1:
                time.sleep(PROBE_GAP)
        try:
            with open(path, "a+b"):
                pass
        except PermissionError:
            print(f"Warning: the update lock can't be opened ({path}); read as no update.")
            return False
    except Exception:
        return False
    return True


def manifest_path(user_files_dir):
    return os.path.join(user_files_dir, MANIFEST_NAME)


def _now():
    """A sortable UTC time stamp with microseconds (`added_at`, `removed_at`, the log's `at`)."""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%06dZ" % int((t % 1) * 1e6)


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


# ------------------------------------------------------------------------------------------------ #
# OS locks (spec §6.2, K27): byte 0 of a file of its own, never written into
# ------------------------------------------------------------------------------------------------ #

class _FileLock:
    """An exclusive lock on byte 0 of `path`. Windows: `msvcrt.locking` after a seek to 0 (it locks
    from the current position, so two handles at different offsets would both "succeed"); POSIX:
    `flock` for the maintenance lock, an `fcntl` byte-range lock for the write lock. Waiting loops on
    the non-blocking call with a short sleep, never LK_LOCK (ten one-second tries, then it gives up)."""

    def __init__(self, path, byte_range=False):
        self.path = path
        self.byte_range = byte_range
        self.fd = None
        self.held = False

    def _open(self):
        if self.fd is None:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)

    def try_acquire(self):
        self._open()
        try:
            if msvcrt:
                os.lseek(self.fd, 0, 0)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            elif self.byte_range:
                fcntl.lockf(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.held = True
        return True

    def acquire(self, timeout, retry):
        deadline = time.perf_counter() + timeout
        while not self.try_acquire():
            if time.perf_counter() >= deadline:
                return False
            time.sleep(retry)
        return True

    def release(self):
        if not self.held:
            return
        self.held = False
        if msvcrt:
            os.lseek(self.fd, 0, 0)
            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        elif self.byte_range:
            fcntl.lockf(self.fd, fcntl.LOCK_UN, 1, 0)
        else:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def close(self):
        self.release()
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class MaintenanceLock(_FileLock):
    """`<db>.lock`: held by whoever builds, checks, re-imports, exports or repairs (§6.2). A second
    handle in the same process is refused like another process's, so a holder passes its own lock on
    (Repair exports through the lock it already holds). Every holder unlocks in a `finally`."""

    def __init__(self, db_path):
        super().__init__(db_path + ".lock")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _WriteLock:
    """`<db>.wlock`, one per database per process (§6.2): an RLock for this process's threads (two
    threads' connections race too), then the OS lock on a descriptor the process opens once and keeps
    for its life (on POSIX, closing ANY descriptor of the file drops the process's fcntl locks)."""

    def __init__(self, db_path):
        self.rlock = threading.RLock()
        self.file = _FileLock(db_path + ".wlock", byte_range=True)
        self.depth = 0

    def acquire(self, timeout=LOCK_TIMEOUT):
        deadline = time.perf_counter() + timeout
        if not self.rlock.acquire(timeout=timeout):
            raise StoreBusy("the library is busy (another window's save); try again")
        try:
            if self.depth == 0:
                if not self.file.acquire(max(0.0, deadline - time.perf_counter()), LOCK_RETRY):
                    raise StoreBusy("the library is busy (another program's save); try again")
            self.depth += 1
        except BaseException:
            self.rlock.release()
            raise

    def release(self):
        self.depth -= 1
        try:
            if self.depth == 0:
                self.file.release()
        finally:
            self.rlock.release()


_WRITE_LOCKS = {}
_WRITE_LOCKS_GUARD = threading.Lock()
_OWN_BUMPS = {}                  # db path -> this process's own bumps {"order": n, "availability": n}


def _write_lock_for(db_path):
    key = os.path.normcase(os.path.abspath(db_path))
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = _WRITE_LOCKS[key] = _WriteLock(db_path)
            _OWN_BUMPS[key] = {"order": 0, "availability": 0}
        return lock


def _own_bumps(db_path):
    _write_lock_for(db_path)
    return _OWN_BUMPS[os.path.normcase(os.path.abspath(db_path))]


# ------------------------------------------------------------------------------------------------ #
# Connections and schema (spec §6.2, §6.3)
# ------------------------------------------------------------------------------------------------ #

ROLES = ("window", "helper", "analyzer", "register", "reader", "connect")

SCHEMA_SQL = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE roots (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL,
      path TEXT,
      placement TEXT,
      catalogue_only INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL)""",
    "CREATE TABLE pieces (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, created_at TEXT NOT NULL)",
    """CREATE TABLE items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      root_id  INTEGER NOT NULL REFERENCES roots(id),
      rel_path TEXT NOT NULL,
      rel_key  TEXT NOT NULL,
      tier     TEXT NOT NULL CHECK (tier IN ('now', 'soon', 'goal', 'graduated', 'arrivals')),
      ord      REAL NOT NULL,
      entry    TEXT NOT NULL,
      title TEXT, parent_folder TEXT, source_type TEXT,
      availability TEXT NOT NULL DEFAULT 'available',
      size INTEGER, mtime_ns INTEGER,
      changed_in INTEGER NOT NULL,
      added_at TEXT NOT NULL, graduated_at TEXT,
      piece_id INTEGER REFERENCES pieces(id),
      watched INTEGER NOT NULL DEFAULT 0,
      mined_at TEXT,
      pinned TEXT,
      in_learning_order INTEGER NOT NULL DEFAULT 1,
      UNIQUE (root_id, rel_key))""",
    "CREATE INDEX items_order ON items (tier, ord, id)",
    "CREATE INDEX items_folder ON items (tier, parent_folder, ord, id)",   # placement by folder (§12)
    "CREATE INDEX items_key ON items (rel_key)",                            # "is this file an item?" (§12)
    """CREATE TABLE trash (
      id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, root_id INTEGER NOT NULL, rel_path TEXT NOT NULL,
      tier TEXT NOT NULL, prev_id INTEGER, next_id INTEGER,
      entry TEXT NOT NULL, item_state TEXT NOT NULL,
      trashed_path TEXT,
      removed_at TEXT NOT NULL, restored_at TEXT)""",
    """CREATE TABLE exclusions (
      id INTEGER PRIMARY KEY, root_id INTEGER, pattern TEXT NOT NULL, kind TEXT NOT NULL,
      created_at TEXT NOT NULL, note TEXT)""",
    """CREATE TABLE anki_links (
      item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
      note_id INTEGER NOT NULL, source TEXT, linked_at TEXT NOT NULL,
      PRIMARY KEY (item_id, note_id))""",
    """CREATE TABLE anki_changes (
      id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, action TEXT NOT NULL,
      notes TEXT NOT NULL, before TEXT, after TEXT, at TEXT NOT NULL, reverted_at TEXT)""",
    """CREATE TABLE pairings (
      content_key TEXT PRIMARY KEY,
      item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
      pairing TEXT NOT NULL,
      paired_at TEXT NOT NULL)""",
    """CREATE TABLE placement_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id INTEGER NOT NULL,
      kind TEXT NOT NULL,
      by TEXT NOT NULL,
      explicit INTEGER NOT NULL,
      state_version INTEGER NOT NULL,
      at TEXT NOT NULL)""",
)

# Tables added without a schema change (L2.2 §2.2): an older Surasura ignores a table it doesn't know, so each is
# made IF NOT EXISTS wherever tables are written, and goes out in the copy only where it exists.
ADDED_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS made_words (
      item_id  INTEGER NOT NULL,
      word     TEXT NOT NULL,
      note_ids TEXT NOT NULL,
      made_at  TEXT NOT NULL,
      batch    TEXT,
      PRIMARY KEY (item_id, word))""",
    # Each card's line (✅ D1, 2026-10-07): the note Connect made from a line of an item, the line's start and end (ms,
    # as Connect's line reader gives them) and a short fingerprint of its text — no sentence, no media; 3.1's journey
    # plays a card's line, found again by its fingerprint after a re-sync shifts the timings. Empty until Connect fills it.
    """CREATE TABLE IF NOT EXISTS made_lines (
      note_id  INTEGER PRIMARY KEY,
      item_id  INTEGER NOT NULL,
      start_ms INTEGER,
      end_ms   INTEGER,
      line_fp  TEXT,
      made_at  TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS made_lines_item ON made_lines (item_id)",
)

# Schema 2 (L3.1, the L2.2 pack 02 §2.3–2.4): works (a title: a season, a film, a book, a channel), the feed's
# tombstones, and the items' work, search key, feed version and *Mine it too*. A fresh store runs SCHEMA_SQL and then
# these, so a new store and an upgraded one have one shape. `items_piece` is L3.1's (§12.8): every command keeps the
# pieces it touches whole, which reads a piece's members.
SCHEMA_2_SQL = (
    """CREATE TABLE works (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title         TEXT NOT NULL,
      title_by_user INTEGER NOT NULL DEFAULT 0,
      titles        TEXT NOT NULL DEFAULT '[]',
      search_key    TEXT NOT NULL,
      folder_key    TEXT,
      anilist_id    INTEGER,
      tmdb_id       TEXT,
      youtube_channel TEXT,
      media_type    TEXT,
      media_type_by TEXT,
      cover_source  TEXT CHECK (cover_source IN ('anilist', 'tmdb', 'youtube', 'file', 'user', 'generated')),
      cover_ref     TEXT,
      cover_path    TEXT,
      cover_fetched_at TEXT,
      cover_locked  INTEGER NOT NULL DEFAULT 0,
      feed_in       INTEGER NOT NULL DEFAULT 0,
      created_at    TEXT NOT NULL)""",
    "CREATE INDEX works_folder ON works (folder_key)",
    "CREATE UNIQUE INDEX works_anilist ON works (anilist_id) WHERE anilist_id IS NOT NULL",
    "CREATE UNIQUE INDEX works_tmdb ON works (tmdb_id) WHERE tmdb_id IS NOT NULL",
    "CREATE INDEX works_feed ON works (feed_in)",
    """CREATE TABLE gone (
      kind TEXT NOT NULL CHECK (kind IN ('item', 'work')),
      id INTEGER NOT NULL, feed_in INTEGER NOT NULL, at TEXT NOT NULL,
      PRIMARY KEY (kind, id))""",
    "ALTER TABLE items ADD COLUMN work_id INTEGER REFERENCES works(id)",
    "ALTER TABLE items ADD COLUMN search_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE items ADD COLUMN feed_in INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE items ADD COLUMN mine_asked TEXT",
    "ALTER TABLE trash ADD COLUMN text_forgotten INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX items_work ON items (work_id)",
    "CREATE INDEX items_feed ON items (feed_in)",
    "CREATE INDEX items_piece ON items (piece_id)",
    "CREATE INDEX items_search ON items (search_key)",     # the search scans these keys, never the wide rows (§12.8)
)

# The change feed (L2.2 04 §4.1): what a window reads of each changed row
FEED_POLL = 0.1                  # s: a window looks at `PRAGMA data_version` this often (its store worker)
FEED_ITEM_FIELDS = ("id", "tier", "ord", "rel_path", "title", "parent_folder", "source_type", "availability",
                    "work_id", "piece_id", "watched", "mined_at", "pinned", "mine_asked", "graduated_at",
                    "in_learning_order", "added_at", "feed_in")
FEED_WORK_FIELDS = ("id", "title", "title_by_user", "titles", "folder_key", "anilist_id", "tmdb_id", "youtube_channel",
                    "media_type", "media_type_by", "cover_source", "cover_ref", "cover_path", "cover_fetched_at",
                    "cover_locked", "feed_in")

# Every table but meta and items goes out in the copy generically (fields + rows, §6.7); `works` without its derived
# columns (WORK_NOT_COPIED: a rebuild re-derives them)
COPY_TABLES = ("roots", "pieces", "trash", "exclusions", "anki_links", "anki_changes", "pairings",
               "placement_log", "made_words", "made_lines", "works")
WORK_NOT_COPIED = ("search_key", "feed_in")
# Meta keys the copy carries when the store holds them (beside epoch, log_seq, mine_line, arrivals_on and the readers)
COPY_META_KEYS = ("soon_line", "auto_band", "rename_asks", "kept_apart")
ITEM_FIELDS = ("id", "root_id", "rel_path", "tier", "availability", "size", "mtime_ns", "added_at",
               "graduated_at", "piece_id", "watched", "mined_at", "pinned", "in_learning_order", "work_id",
               "mine_asked")

# Forward-only upgrades: {from_version: function(store)}, each run inside one transaction after a .bak; filled
# below, where the functions are (`_upgrade_1_to_2`)
_UPGRADES = {}


def _connect(path, role, busy_ms=5000):
    """A connection by the spec's rules (§6.2): Python opens no transaction of its own (every BEGIN is
    ours), WAL + synchronous=FULL, foreign keys on, `query_only` until the write helper lifts it, and no
    auto-checkpoint except in the helper, which checkpoints under the write lock."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    if sys.version_info >= (3, 12):
        conn = sqlite3.connect(path, timeout=LOCK_TIMEOUT, autocommit=True)
    else:
        conn = sqlite3.connect(path, timeout=LOCK_TIMEOUT, isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_size_limit=4194304")
        conn.execute(f"PRAGMA wal_autocheckpoint={1000 if role == 'helper' else 0}")
        conn.execute("PRAGMA query_only=1")
    except BaseException:
        conn.close()
        raise
    return conn


def _is_malformed(exc):
    text = str(exc).lower()
    return "malformed" in text or "not a database" in text


def damaged_marker(db_path):
    return db_path + ".damaged"


def mark_damaged(db_path, detail):
    """Record damage in `<db>.damaged` (time and detail): every process sees it at its next open or
    command and goes read-only until Repair (§6.9). Best effort: the store is already unusable."""
    try:
        with open(damaged_marker(db_path), "w", encoding="utf-8") as f:
            f.write(f"{_now()}\n{detail}\n")
    except OSError:
        pass
    library_watch.ring(db_path)          # a window sleeping on its watch looks again and turns read-only (L3.2)


def quick_check(conn, db_path):
    """`PRAGMA quick_check` (§6.2): 'ok', or 'damaged' (the marker written), or 'error' when the check
    itself raised (an antivirus lock, an I/O error: read-only for this session, not damage)."""
    try:
        rows = [r[0] for r in conn.execute("PRAGMA quick_check").fetchall()]
    except sqlite3.DatabaseError as exc:
        if _is_malformed(exc):
            mark_damaged(db_path, f"quick_check: {exc}")
            return "damaged"
        return "error"
    if rows == ["ok"]:
        return "ok"
    mark_damaged(db_path, "quick_check:\n" + "\n".join(map(str, rows[:50])))
    return "damaged"


def _backup_db(conn, db_path):
    """A `.bak` through SQLite's backup API (a plain copy of the .db alone lost committed rows, K6);
    keep the newest BAK_KEEP (R-5). Written under a `.part` name and renamed once whole, so a process killed
    mid-copy leaves no `.bak` that looks complete; the next backup (always the helper's, under the maintenance lock)
    clears such a leftover, and a `.bak` still holding its `-journal` (an older version's killed copy)."""
    folder, base = os.path.split(db_path)
    names = os.listdir(folder)
    for name in names:
        if not name.startswith(base + ".bak."):
            continue
        whole = name[:-len("-journal")] if name.endswith("-journal") else name
        if whole.endswith(".part") or (whole != name or whole + "-journal" in names):
            for leftover in (whole, whole + "-journal"):
                try:
                    os.remove(os.path.join(folder, leftover))
                except OSError:
                    pass
    dest = f"{db_path}.bak.{_stamp()}"
    n = 1
    while os.path.exists(dest):
        dest = f"{db_path}.bak.{_stamp()}-{n}"
        n += 1
    target = sqlite3.connect(dest + ".part")
    try:
        conn.backup(target)
    finally:
        target.close()
    os.replace(dest + ".part", dest)
    baks = sorted((f for f in os.listdir(folder) if f.startswith(base + ".bak.") and
                   not f.endswith((".part", "-journal"))),
                  key=lambda f: os.path.getmtime(os.path.join(folder, f)))
    for old in baks[:-BAK_KEEP]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass
    return dest


# ------------------------------------------------------------------------------------------------ #
# Modes (spec §6.9): 'store', 'read-only' or 'json', checked, never fixed
# ------------------------------------------------------------------------------------------------ #

def _probe(db_path, busy_wait):
    """(mode, reason) for the database at `db_path`, retrying a busy database for `busy_wait` s."""
    if not os.path.exists(db_path):
        return "json", "no store"
    if os.path.exists(damaged_marker(db_path)):
        return "read-only", "damaged"
    deadline = time.perf_counter() + busy_wait
    while True:
        conn = None
        try:
            conn = _connect(db_path, "reader", busy_ms=50 if busy_wait else 0)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > STORE_SCHEMA:
                return "read-only", "made by a newer Surasura"
            if version < STORE_SCHEMA:
                return "json", "not ready"
            row = conn.execute("SELECT value FROM meta WHERE key = 'migrated_at'").fetchone()
            if row is None:
                if conn.execute("SELECT 1 FROM meta WHERE key = 'newer_copy'").fetchone():
                    return "read-only", NEWER_COPY                  # the helper met a newer store's copy (G2.2-7)
                failed = conn.execute("SELECT value FROM meta WHERE key = 'migration_failed'").fetchone()
                return "json", ("migration failed" if failed else "not ready")
            return "store", None
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                if time.perf_counter() < deadline:
                    time.sleep(0.02)
                    continue
                return "read-only", "busy"
            if _is_malformed(exc):
                mark_damaged(db_path, f"open: {exc}")
                return "read-only", "damaged"
            return "read-only", f"io: {exc}"
        except sqlite3.DatabaseError as exc:
            if _is_malformed(exc):
                mark_damaged(db_path, f"open: {exc}")
                return "read-only", "damaged"
            return "read-only", f"io: {exc}"
        finally:
            if conn is not None:
                conn.close()


def check_mode(language, data_dir, busy_wait=BUSY_AT_OPEN):
    """('store' | 'read-only' | 'json', reason). Cheap: no scans, no parsing (I10)."""
    return _probe(library_db_path(language, data_dir), busy_wait)


def open_store(language, data_dir, user_files_dir, role="window", busy_wait=BUSY_AT_OPEN):
    """A `Store` handle for this thread, or None when no store is ready (not built, JSON mode,
    read-only). Cheap: it checks the version, the damage marker and readiness, nothing more (§6.2)."""
    db_path = library_db_path(language, data_dir)
    mode, _reason = _probe(db_path, busy_wait)
    if mode != "store":
        return None
    try:
        # Schema 2: the Soon line is canonical and the tiers follow it (L2.2 05 §5.1); an open no longer re-counts it
        return Store(db_path, language, data_dir, user_files_dir, role)
    except sqlite3.DatabaseError:
        return None
    except StoreError:
        return None


class StoreOpener:
    """A window's view of its store (§6.2): `check()` never waits on the window's thread. A busy
    database is retried on a worker, and the window uses the mode it cached at its last check until the
    worker settles. The handle itself belongs to the thread that calls `handle()` (K31)."""

    def __init__(self, language, data_dir, user_files_dir, role="window"):
        self.language, self.data_dir, self.user_files_dir, self.role = language, data_dir, user_files_dir, role
        self.mode, self.reason = "json", "not checked"
        self._worker = None
        self._local = threading.local()
        self._guard = threading.Lock()

    def check(self):
        with self._guard:
            if self._worker is not None and self._worker.is_alive():
                return self.mode
        mode, reason = check_mode(self.language, self.data_dir, busy_wait=0.0)
        if reason == "busy":
            with self._guard:
                if self._worker is None or not self._worker.is_alive():
                    self._worker = threading.Thread(target=self._settle, daemon=True)
                    self._worker.start()
            return self.mode
        self.mode, self.reason = mode, reason
        return mode

    def _settle(self):
        mode, reason = check_mode(self.language, self.data_dir, busy_wait=BUSY_AT_OPEN)
        self.mode, self.reason = mode, reason

    def handle(self):
        """This thread's long-lived handle, opened on first use, or None outside store mode."""
        if self.mode != "store":
            return None
        store = getattr(self._local, "store", None)
        if store is None:
            store = open_store(self.language, self.data_dir, self.user_files_dir, self.role, busy_wait=0.0)
            self._local.store = store
        return store

    def wait(self, timeout=5.0):
        """For tests and headless callers: let a running worker settle."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)
        return self.mode


# ------------------------------------------------------------------------------------------------ #
# Entries: the placement helpers' own copies (spec §7: the tkinter module keeps its copies until
# Phase 2 points them here)
# ------------------------------------------------------------------------------------------------ #

def place_new_entries(existing, new_entries):
    """One tab's order with `new_entries` placed in it — a copy of the Content Manager's rule
    (New_Content_Placement_Spec.md): a file whose folder already has files in this tab goes right after
    that folder's LAST item; everything else goes to the TOP, all together, in the order given. The
    existing entries are never reordered."""
    last_of = {}
    for index, entry in enumerate(existing):
        folder = _entry_folder(entry)
        if folder:
            last_of[folder] = index
    placed, after = [], {}
    for entry in new_entries:
        folder = _entry_folder(entry)
        if folder in last_of:
            after.setdefault(last_of[folder], []).append(entry)
        else:
            placed.append(entry)
    for index, entry in enumerate(existing):
        placed.append(entry)
        placed.extend(after.get(index, ()))
    return placed


def _entry_folder(entry):
    """The folder a manifest entry belongs to — its `parent_folder`, the grouping the library draws —
    or "" for a file loose in the tab (never an anchor: a loose file goes to the top)."""
    if not isinstance(entry, dict):
        return ""
    folder = entry.get("parent_folder")
    if isinstance(folder, str):
        return folder
    parts = str(entry.get("physical_path") or "").split("/")
    return "/".join(parts[1:-1]) if len(parts) > 2 else ""


def _detect_source_type(fpath, marker_cache=None):
    """Classify a file for the report's source badge (the Content Manager's rule): the extension, then
    the folder's producer marker (read once per directory with `marker_cache`), then the file name."""
    folder = os.path.dirname(fpath)
    if marker_cache is None:
        marker_type = read_source_marker(folder).get("source_type")
    else:
        if folder not in marker_cache:
            marker_cache[folder] = read_source_marker(folder).get("source_type")
        marker_type = marker_cache[folder]
    return infer_source_type(fpath, marker_type=marker_type)


def parent_folder_of(rel):
    """`parent_folder` as the three builders compute it: the middle path parts, dropping a second
    level named like a tier."""
    parts = rel.split("/")
    hierarchy = parts[1:-1] if len(parts) > 2 else []
    if hierarchy and hierarchy[0] in TIER_OF_FOLDER:
        hierarchy = hierarchy[1:]
    return "/".join(hierarchy)


def make_entry(rel, origin, source_type=None, with_source_type=True):
    """A manifest entry in the builders' field order: title, physical_path, parent_folder,
    origin_source, [source_type], type, status."""
    entry = {"title": rel.rsplit("/", 1)[-1], "physical_path": rel, "parent_folder": parent_folder_of(rel),
             "origin_source": origin}
    if with_source_type:
        entry["source_type"] = source_type
    entry["type"] = "File"
    entry["status"] = "New"
    return entry


def is_content_name(name):
    return name.lower().endswith(CONTENT_EXTENSIONS)


def _columns(entry):
    """The entry's column copies (title, parent_folder, source_type), so reads needn't parse JSON. The
    folder column is `_entry_folder` (the placement key); a non-string title or source_type is stored
    as NULL — `infer_source_type` reads a non-string declared type exactly as it reads None."""
    title = entry.get("title")
    source_type = entry.get("source_type")
    return (title if isinstance(title, str) else None, _entry_folder(entry),
            source_type if isinstance(source_type, str) else None)


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


_PRODUCER = re.compile(r"[a-z0-9_-]{1,32}")
_NOT_PRODUCERS = ("user", "undo", "sync")       # the names a person, an undo and a disk sync are logged under


def _producer(pairing):
    """Who registered (the record's `producer`), as the placement log records it: a short name (lowercase letters,
    digits, - or _, up to 32) that isn't a person's, an undo's, a sync's or a rule's, else "hato" — it lands in the
    copy and the log."""
    name = pairing.get("producer") if isinstance(pairing, dict) else None
    if isinstance(name, str) and _PRODUCER.fullmatch(name) and name not in _NOT_PRODUCERS \
            and not name.startswith("rule"):
        return name
    return "hato"


def library_rel(data_dir, path):
    """`path` (absolute, or relative to the data folder) as the data folder's normalised relative path ('/'), or None
    when it isn't under it: another drive, a drive-relative path (D:foo.srt), `..`, the folder itself. 3.0's Sources
    (roots) widen this."""
    if not os.path.isabs(path) and os.path.splitdrive(path)[0]:
        return None
    try:
        rel = os.path.relpath(path, data_dir) if os.path.isabs(path) else path
    except ValueError:              # os.path.relpath across drives (Windows)
        return None
    rel = os.path.normpath(rel).replace("\\", "/")
    if rel in (".", "..") or rel.startswith("../") or os.path.isabs(rel) or os.path.splitdrive(rel)[0]:
        return None
    return rel


def _same_record(text, pairing):
    """A stored pairing row and a record: equal by value, whatever order the row's keys were written in."""
    try:
        return json.loads(text) == pairing
    except ValueError:
        return False


def _rel_dir(rel):
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ------------------------------------------------------------------------------------------------ #
# Order keys (spec §6.5)
# ------------------------------------------------------------------------------------------------ #

STEP = 1024.0
RESPACE_WINDOW = 16


def _keys_between(lo, hi, k):
    if lo is None and hi is None:
        return [STEP * i for i in range(1, k + 1)]
    if lo is None:
        return [hi - STEP * (k + 1 - i) for i in range(1, k + 1)]
    if hi is None:
        return [lo + STEP * i for i in range(1, k + 1)]
    return [lo + (hi - lo) * i / (k + 1) for i in range(1, k + 1)]


def _valid(keys, lo, hi):
    """Strictly increasing and strictly inside (lo, hi), in floating point."""
    prev = lo
    for key in keys:
        if prev is not None and not key > prev:
            return False
        prev = key
    return hi is None or prev is None or prev < hi


def _spread_ok(lo, hi, n):
    """A re-space window is usable when its span gives at least 1.0 per slot (§6.5 step 2)."""
    if lo is None or hi is None:
        return True
    return (hi - lo) / (n + 1) >= 1.0


def _plan_ords(seq, ords, placed):
    """New keys for one tier's final order `seq` (ids), where every id in `placed` needs a key and the
    rest keep theirs (`ords`). A run that doesn't fit its gap re-spaces locally — 16 keys each side,
    then 32, 64, … — and only a window reaching both ends renumbers the whole tier. Returns {id: ord}
    for every key that changes."""
    cur = {i: ords[i] for i in seq if i not in placed}
    new = {}
    n = len(seq)
    i = 0
    while i < n:
        if seq[i] in cur:
            i += 1
            continue
        j = i
        while j < n and seq[j] not in cur:
            j += 1
        lo = cur[seq[i - 1]] if i > 0 else None
        hi = cur[seq[j]] if j < n else None
        keys = _keys_between(lo, hi, j - i)
        if _valid(keys, lo, hi):
            for item, key in zip(seq[i:j], keys):
                cur[item] = new[item] = key
            i = j
            continue
        width = RESPACE_WINDOW
        while True:
            a = max(0, i - width)
            b = min(n, j + width)
            while b < n and seq[b] not in cur:
                b += 1
            lo = cur[seq[a - 1]] if a > 0 else None
            hi = cur[seq[b]] if b < n else None
            if a == 0 and b == n:
                keys = _keys_between(None, None, n)
            else:
                keys = _keys_between(lo, hi, b - a)
                if not (_spread_ok(lo, hi, b - a) and _valid(keys, lo, hi)):
                    width *= 2
                    continue
            for item, key in zip(seq[a:b], keys):
                if ords.get(item) != key or item in placed:
                    new[item] = key
                cur[item] = key
            i = b
            break
    return new


# ------------------------------------------------------------------------------------------------ #
# Changes (spec §6.11): what a command returns, for undo
# ------------------------------------------------------------------------------------------------ #

class Change:
    """One committed command, as undo needs it: per item, in the previous order, where it stood
    (tier, the neighbours just before the change — items of the change's own set included) and the
    `changed_in` the change replaced; for a status write, the values it replaced. Kept in memory by the
    window that made it (B8); `epoch` and `version` say what it committed at."""

    def __init__(self, kind, epoch, version):
        self.kind = kind
        self.epoch = epoch
        self.version = version
        self.items = []       # [{"id", "tier", "prev", "next", "changed_in", "explicit", ...}]
        self.status = []      # [(id, column, old, new)] for set_watched / pin / unpin
        self.added = []       # ids an Add created (or took over)
        self.trash_ids = []   # trash rows a remove wrote
        self.restored = []    # trash ids a restore put back
        self.pieces = None    # split / join: what undo restores
        self.existing = []    # insert: [(path, item_id, tier)] already in the library, left where they are
        self.notes = []
        self.repieced = []    # (item_id, old piece, new piece) the settling step wrote (schema 2)
        self.options = []     # set_soon_line / set_library_options: [(key, old, new)]
        self.works = None     # works' commands: {"rows": [work rows before], "items": [(id, old, new)],
                              #                   "fields": [(work_id, column, old, new)], "created": [ids]}

    def __repr__(self):
        return f"<Change {self.kind} v{self.version} e{self.epoch} items={len(self.items)}>"


class _Command:
    """The outermost command's bookkeeping, shared with any command nested inside it (§6.2: `register`
    → its pairing, `undo` → what it replays join the outer transaction): one version for the whole
    transaction, bumps decided at the end, placement-log events written in the same transaction."""

    def __init__(self, store, kind, by, meta):
        self.store = store
        self.kind = kind
        self.by = by
        self.meta = meta
        self.version = meta["state_version"] + 1
        self.epoch = meta["epoch"]
        self.changed = False
        self.bump_order = False
        self.bump_avail = False
        self.bump_pins = False
        self.logging = any(k.startswith("reader:") for k in meta)
        self.mine_n = meta.get("mine_line", MINE_LINE_DEFAULT)
        self.mine_before = store._mine_ids(self.mine_n) if self.logging else None
        self.events = []      # (item_id, kind, explicit)
        self.explicit = {}    # item_id -> explicit, for its crossing events
        self.quiet = set()    # items that log no event at all (a back-fill registration, P2.1)
        self.event_by = {}    # item_id -> who placed it last in this command, when not the command's `by`
        # Schema 2 (L3.1): what the command's settling step reads (`Store._settle`)
        self.tiers = set()    # tiers whose rows moved, came or went: Current's among them → the Soon line
        self.moved = set()    # items placed (moved, added, re-tiered, put back): their pieces are re-checked
        self.reworked = set() # items whose work changed: their pieces are re-checked too
        self.hints = {}       # item_id -> the piece an undo puts it back in
        self.fed = set()      # items whose `feed_in` takes this version (L2.2 04 §4.1)
        self.fed_inline = set()  # … already written with their placement
        self.fed_works = set()
        self.gone = []        # (kind, id) leaving items / works: the feed's tombstones
        self.back = set()     # items put back: their tombstones go
        self.pieces_left = set()  # pieces items left: deleted when emptied (05 §5.2 rule 7)
        self.repieced = []    # (item_id, old piece, new piece) the settling step wrote, for undo
        self.line_set = False  # set_soon_line: the line moved

    def touch(self, tiers=(), order=False, availability=False, pins=False):
        """Record a change: any tier in `tiers` that is analysed bumps `order_version`."""
        self.changed = True
        self.tiers.update(t for t in tiers if t in TIERS)
        if order or any(TIERS[t][2] for t in tiers if t in TIERS):
            self.bump_order = True
        if availability:
            self.bump_avail = True
        if pins:
            self.bump_pins = True

    def feed(self, ids=(), works=()):
        """These rows change what a view draws: their `feed_in` takes this command's version."""
        self.fed.update(ids)
        self.fed_works.update(works)

    def event(self, item_id, kind, explicit, by=None):
        """Log an event for `item_id`, as `by`'s (default: the command's). An explicit event makes the item's later
        crossings of the mine line explicit too (a rule the user set is the user's own placement, D30)."""
        self.events.append((item_id, kind, int(explicit), by))
        if explicit:
            self.explicit[item_id] = 1
        else:
            self.explicit.setdefault(item_id, 0)

    def finish(self):
        """Settle (the Soon line, the pieces, the feed: `Store._settle`), then write the versions and the log,
        inside the transaction. Returns the own-bump deltas."""
        if not self.changed:
            return None
        store = self.store
        store._settle(self)
        if self.logging:
            after = store._mine_ids(self.mine_n)
            before = set(self.mine_before)
            now = set(after)
            for item_id in after:
                if item_id not in before:
                    self.events.append((item_id, "entered_mine_line", self.explicit.get(item_id, 0),
                                        self.event_by.get(item_id)))
            for item_id in self.mine_before:
                if item_id not in now:
                    self.events.append((item_id, "left_mine_line", self.explicit.get(item_id, 0),
                                        self.event_by.get(item_id)))
            events = [e for e in self.events if e[0] not in self.quiet]
            if events:
                at = _now()
                store.conn.executemany(
                    "INSERT INTO placement_log (item_id, kind, by, explicit, state_version, at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(i, k, b or self.by, e, self.version, at) for i, k, e, b in events])
        updates = [("state_version", self.version)]
        if self.bump_order:
            updates.append(("order_version", self.meta["order_version"] + 1))
        if self.bump_avail:
            updates.append(("availability_version", self.meta["availability_version"] + 1))
        if self.bump_pins:
            updates.append(("pins_version", self.meta["pins_version"] + 1))
        store.conn.executemany("UPDATE meta SET value = ? WHERE key = ?", [(str(v), k) for k, v in updates])
        return {"order": int(self.bump_order), "availability": int(self.bump_avail)}



# ------------------------------------------------------------------------------------------------ #
# The store handle: one per thread (K31)
# ------------------------------------------------------------------------------------------------ #

class Check:
    """What a command will touch, read before its file work (§6.6 "file work and commands", step 1):
    each item's `changed_in` and each key's holder. The commit re-checks only these."""

    def __init__(self, items, keys, started_at):
        self.items = items            # {item_id: changed_in or None (gone)}
        self.keys = keys              # {rel_key: item_id or None}
        self.started_at = started_at


class _Seq:
    """One tier's order as a doubly linked list, for the bulk commands (undo, restore, sync, Reset,
    re-import) that re-place many items: O(1) per removal or insertion."""

    def __init__(self, ids):
        self.nxt, self.prv = {}, {}
        self.head = self.tail = None
        for item in ids:
            self.append(item)

    def __contains__(self, item):
        return item in self.nxt

    def append(self, item):
        self.insert_after(item, self.tail)

    def remove(self, item):
        p, n = self.prv.pop(item), self.nxt.pop(item)
        if p is None:
            self.head = n
        else:
            self.nxt[p] = n
        if n is None:
            self.tail = p
        else:
            self.prv[n] = p

    def insert_after(self, item, anchor):
        """`anchor` None = at the top."""
        n = self.head if anchor is None else self.nxt[anchor]
        self.prv[item], self.nxt[item] = anchor, n
        if anchor is None:
            self.head = item
        else:
            self.nxt[anchor] = item
        if n is None:
            self.tail = item
        else:
            self.prv[n] = item

    def insert_before(self, item, anchor):
        self.insert_after(item, self.prv[anchor])

    def ids(self):
        out, item = [], self.head
        while item is not None:
            out.append(item)
            item = self.nxt[item]
        return out


_ROW = "id, tier, ord, changed_in, parent_folder, rel_path, availability, rel_key, graduated_at, entry, piece_id"


class Store:
    """A handle on one language's store, for the thread that opened it. Every write goes through
    `_writing()`; every command is one `BEGIN IMMEDIATE` transaction returning the `Change` it made."""

    def __init__(self, db_path, language, data_dir, user_files_dir, role="window"):
        self.db_path = db_path
        self.language = language
        self.data_dir = data_dir
        self.user_files_dir = user_files_dir
        self.role = role
        self.conn = _connect(db_path, role)
        self._wlock = _write_lock_for(db_path)
        self._own = _own_bumps(db_path)
        self._depth = 0
        self._cmd = None
        self._repairing = False          # Repair writes past the damage marker it is about to clear

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- the one write helper (§6.2, K32) ------------------------------------------------------- #

    @contextmanager
    def _writing(self, begin=True):
        """Every write and every explicit checkpoint, under the write lock. Re-entrant: a command
        called inside another joins the outer transaction; only the outermost call takes the OS lock,
        begins and commits. `query_only` is lifted here and nowhere else."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        if not self._repairing and os.path.exists(damaged_marker(self.db_path)):
            raise StoreReadOnly("the library store is damaged and needs Repair")
        self._wlock.acquire()
        committed = False
        try:
            self.conn.execute("PRAGMA query_only=0")
            if begin:
                try:
                    self.conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                        raise StoreBusy("the library is busy; try again") from exc
                    raise
            self._depth = 1
            try:
                yield
            except BaseException:
                self._depth = 0
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
            self._depth = 0
            if begin:
                try:
                    self.conn.execute("COMMIT")
                except BaseException:
                    if self.conn.in_transaction:
                        self.conn.execute("ROLLBACK")
                    raise
                committed = True
        except sqlite3.DatabaseError as exc:
            if _is_malformed(exc):
                mark_damaged(self.db_path, f"{self.role}: {exc}")
            raise
        finally:
            self._depth = 0
            try:
                self.conn.execute("PRAGMA query_only=1")
            finally:
                self._wlock.release()
                if committed:
                    library_watch.ring(self.db_path)  # every writer's commit wakes the windows listening (L3.2)

    def checkpoint(self):
        """A PASSIVE checkpoint (never TRUNCATE: K18), under the write lock like every write."""
        with self._writing(begin=False):
            return self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()

    @contextmanager
    def _reading(self):
        """Reads that must agree run in one short read transaction (K10); inside a write, as they are."""
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN")
        try:
            yield
        finally:
            if self.conn.in_transaction:
                try:
                    self.conn.execute("COMMIT")
                except BaseException:
                    if self.conn.in_transaction:
                        self.conn.execute("ROLLBACK")
                    raise

    @contextmanager
    def _command(self, kind, by="user"):
        if self._cmd is not None:
            yield self._cmd
            return
        deltas = None
        with self._writing():
            cmd = self._cmd = _Command(self, kind, by, self._meta())
            try:
                yield cmd
                deltas = cmd.finish()
            finally:
                self._cmd = None
        if deltas:
            self._own["order"] += deltas["order"]
            self._own["availability"] += deltas["availability"]

    def _change(self, cmd, kind):
        change = Change(kind, cmd.epoch, cmd.version)
        change.repieced = cmd.repieced                     # filled by the settling step, read by undo
        return change

    # --- meta ---------------------------------------------------------------------------------- #

    def _meta(self):
        out = {}
        for key, value in self.conn.execute("SELECT key, value FROM meta"):
            if key in INT_META or key.startswith("reader"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    pass
            out[key] = value
        return out

    def meta(self):
        """Every meta value (versions as integers), read at once."""
        return self._meta()

    def _set_meta(self, values):
        self.conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                              [(k, str(v)) for k, v in values.items()])

    def bookkeeping(self, values, copy_carries=False):
        """Bookkeeping writes (§6.6): no version moves. What the copy carries sets `copy_dirty`."""
        with self._writing():
            if copy_carries:
                values = dict(values, copy_dirty=self._meta().get("copy_dirty", 0) + 1)
            self._set_meta(values)

    # --- reading -------------------------------------------------------------------------------- #

    def _rows(self, ids):
        """{id: row} for the ids that exist, row = (id, tier, ord, changed_in, folder, rel_path,
        availability, rel_key, graduated_at, entry, piece_id)."""
        out = {}
        ids = list(ids)
        for chunk in _chunks(ids, 500):
            marks = ",".join("?" * len(chunk))
            for row in self.conn.execute(f"SELECT {_ROW} FROM items WHERE id IN ({marks})", chunk):
                out[row[0]] = row
        return out

    def _tier_keys(self, tier):
        """[(id, ord)] of a tier, in order."""
        return self.conn.execute("SELECT id, ord FROM items WHERE tier = ? ORDER BY ord, id", (tier,)).fetchall()

    def _neighbours(self, rows):
        """{id: (prev_id, next_id)} in each row's tier, just before a change (one query per 300)."""
        out = {}
        for chunk in _chunks(rows, 300):
            values = ",".join("(?, ?, ?)" for _ in chunk)
            params = [v for r in chunk for v in (r[0], r[1], r[2])]
            sql = (f"WITH m(id, tier, ord) AS (VALUES {values}) SELECT m.id, "
                   "(SELECT i.id FROM items i WHERE i.tier = m.tier AND (i.ord, i.id) < (m.ord, m.id) "
                   " ORDER BY i.ord DESC, i.id DESC LIMIT 1), "
                   "(SELECT i.id FROM items i WHERE i.tier = m.tier AND (i.ord, i.id) > (m.ord, m.id) "
                   " ORDER BY i.ord, i.id LIMIT 1) FROM m")
            for item_id, prev_id, next_id in self.conn.execute(sql, params):
                out[item_id] = (prev_id, next_id)
        return out

    def _before(self, change, rows, explicit=1):
        """Record each row's place just before the change, in the previous order (§6.11)."""
        rows = sorted(rows, key=lambda r: (TIERS[r[1]][3], r[2], r[0]))
        near = self._neighbours(rows)
        for r in rows:
            prev_id, next_id = near.get(r[0], (None, None))
            change.items.append({"id": r[0], "tier": r[1], "prev": prev_id, "next": next_id,
                                 "changed_in": r[3], "explicit": explicit, "graduated_at": r[8],
                                 "piece": r[10] if len(r) > 10 else None})
        return rows

    def _mine_ids(self, n):
        """The mine line: the top N of Current's AVAILABLE items (a missing item never counts)."""
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM items WHERE tier = 'now' AND availability = 'available' ORDER BY ord, id LIMIT ?",
            (n,))]
        if len(ids) < n:
            ids += [r[0] for r in self.conn.execute(
                "SELECT id FROM items WHERE tier = 'soon' AND availability = 'available' ORDER BY ord, id "
                "LIMIT ?", (n - len(ids),))]
        return ids

    def _root_id(self):
        row = self.conn.execute("SELECT id FROM roots WHERE kind = 'library' ORDER BY id LIMIT 1").fetchone()
        return row[0]

    def schedule(self, with_versions=False):
        """{phase_key: [entries]} for the analysed tiers in (ord, id) order — what `resolve_found_files`
        loads — each entry {physical_path, source_type, title, parent_folder} straight from the columns.
        With `with_versions`, also the versions, read in the same transaction."""
        out = {}
        with self._reading():
            for tier in ANALYSED:
                out[TIERS[tier][0]] = [
                    {"physical_path": p, "source_type": s, "title": t, "parent_folder": f}
                    for p, s, t, f in self.conn.execute(
                        "SELECT rel_path, source_type, title, parent_folder FROM items WHERE tier = ? "
                        "ORDER BY ord, id", (tier,))]
            versions = self._versions() if with_versions else None
        return (out, versions) if with_versions else out

    def _versions(self):
        meta = self._meta()
        return {k: meta.get(k, 0) for k in ("epoch", "state_version", "order_version", "availability_version",
                                            "pins_version", "analysed_order_version", "planned_order_version",
                                            "planned_pins_version")}

    def versions(self):
        with self._reading():
            return self._versions()

    def ordered(self, tier):
        """[(item_id, entry, availability)] of a tier in order, for a view."""
        return [(i, json.loads(e), a) for i, e, a in self.conn.execute(
            "SELECT id, entry, availability FROM items WHERE tier = ? ORDER BY ord, id", (tier,))]

    def ids(self, tier):
        return [r[0] for r in self.conn.execute("SELECT id FROM items WHERE tier = ? ORDER BY ord, id", (tier,))]

    def item(self, item_id):
        """One item's columns as a dict (the entry parsed), or None."""
        cur = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is None:
            return None
        out = dict(zip([d[0] for d in cur.description], row))
        out["entry"] = json.loads(out["entry"])
        return out

    # --- the change feed (L2.2 04 §4.1): a window's store worker reads it, never the GUI thread -------- #

    def data_version(self):
        """SQLite's `PRAGMA data_version` on this connection: it moves when another connection commits (the
        window's poll, every `FEED_POLL` s: ~5 µs when nothing changed)."""
        return self.conn.execute("PRAGMA data_version").fetchone()[0]

    def read_feed(self, seen=None, epoch=None):
        """What changed since the window last read (04 §4.1 #4), in one read transaction: a dict with `full`
        (True: every item and work — the first read, a new epoch, or `seen` older than the tombstones kept,
        `feed_floor`), `epoch`, `version` (the window's next `seen`), `items` and `works` (rows of FEED_ITEM_FIELDS /
        FEED_WORK_FIELDS as dicts: every row when full, else those whose `feed_in` > `seen`), `gone` ([(kind, id)] left
        since) and `options` (the Soon line, the mine line, New arrivals). Applying it by id is idempotent: a window's
        own commits come back through it too."""
        item_cols = ", ".join(FEED_ITEM_FIELDS)
        work_cols = ", ".join(FEED_WORK_FIELDS)
        with self._reading():
            meta = self._meta()
            version, now_epoch = meta["state_version"], meta["epoch"]
            full = seen is None or epoch != now_epoch or seen < int(meta.get("feed_floor") or 0)
            if full:
                items = self.conn.execute(f"SELECT {item_cols} FROM items").fetchall()
                works = self.conn.execute(f"SELECT {work_cols} FROM works").fetchall()
                gone = []
            else:
                items = self.conn.execute(f"SELECT {item_cols} FROM items WHERE feed_in > ?", (seen,)).fetchall()
                works = self.conn.execute(f"SELECT {work_cols} FROM works WHERE feed_in > ?", (seen,)).fetchall()
                gone = [tuple(r) for r in self.conn.execute("SELECT kind, id FROM gone WHERE feed_in > ? ORDER BY feed_in",
                                                            (seen,))]
        return {"full": full, "epoch": now_epoch, "version": version,
                "items": [dict(zip(FEED_ITEM_FIELDS, r)) for r in items],
                "works": [dict(zip(FEED_WORK_FIELDS, r)) for r in works], "gone": gone,
                "options": {"soon_line": meta.get("soon_line"), "mine_line": meta.get("mine_line", MINE_LINE_DEFAULT),
                            "arrivals_on": meta.get("arrivals_on", 0)}}

    def prune_gone(self, now=None):
        """In the helper's run (04 §4.1 #3): tombstones older than a day go, and `feed_floor` rises to the newest
        version they held — a window that hasn't read since then re-reads in full. Bookkeeping: no version moves.
        Returns how many went."""
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime((now or time.time()) - FEED_KEEP))
        with self._writing():
            newest = self.conn.execute("SELECT MAX(feed_in) FROM gone WHERE at < ?", (cutoff,)).fetchone()[0]
            if newest is None:
                return 0
            floor = max(int(self._meta().get("feed_floor") or 0), int(newest))
            n = self.conn.execute("DELETE FROM gone WHERE at < ?", (cutoff,)).rowcount
            self._set_meta({"feed_floor": floor})
            return n

    def tidy_works(self):
        """In the helper's run (06 §6.5): a work with no item and no trash row of one (Put back would find it) goes,
        a tombstone in its place. One command (the window reads the tombstone). Returns the ids that went."""
        empty = [r[0] for r in self.conn.execute("SELECT id FROM works WHERE id NOT IN "
                                                 "(SELECT work_id FROM items WHERE work_id IS NOT NULL)")]
        if not empty:
            return []
        held = set()
        for (state,) in self.conn.execute("SELECT item_state FROM trash WHERE restored_at IS NULL"):
            try:
                work = json.loads(state)["columns"].get("work_id")
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if work is not None:
                held.add(work)
        empty = [w for w in empty if w not in held]
        if not empty:
            return []
        with self._command("tidy_works", "sync") as cmd:
            gone = [w for w in empty if not self.conn.execute("SELECT 1 FROM items WHERE work_id = ?", (w,)).fetchone()]
            if not gone:
                return []
            self.conn.executemany("DELETE FROM works WHERE id = ?", [(w,) for w in gone])
            cmd.gone += [("work", w) for w in gone]
            cmd.touch()
            return gone

    def place_of(self, item_id):
        """(tier, 1-based position in it) of an item, read at once; (None, None) when it's gone."""
        with self._reading():
            row = self.conn.execute("SELECT tier, ord FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return None, None
            above = self.conn.execute("SELECT COUNT(*) FROM items WHERE tier = ? AND (ord < ? OR (ord = ? AND id < ?))",
                                      (row[0], row[1], row[1], item_id)).fetchone()[0]
        return row[0], above + 1

    def item_id(self, rel_path):
        row = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (path_key(rel_path),)).fetchone()
        return row[0] if row else None

    # --- change tokens (§6.6) -------------------------------------------------------------------- #

    def token(self):
        """(epoch, order_version, availability_version) and this process's own bumps at that moment."""
        with self._reading():
            meta = self._meta()
        return (meta["epoch"], meta["order_version"], meta["availability_version"],
                self._own["order"], self._own["availability"])

    def changed_since(self, token):
        """Did anyone ELSE change what a view draws since `token`? A version that moved further than this
        process's own bumps did; a new epoch always did. A receipt, a pin or a watched mark never does."""
        epoch, order, avail, own_order, own_avail = token
        with self._reading():
            meta = self._meta()
        if meta["epoch"] != epoch:
            return True
        if meta["order_version"] - order > self._own["order"] - own_order:
            return True
        return meta["availability_version"] - avail > self._own["availability"] - own_avail

    # --- the commit's re-check (§6.6) ------------------------------------------------------------ #

    def check(self, ids=(), paths=()):
        """Step 1 of a command with file work: what it will touch, so its commit can re-check only that."""
        with self._reading():
            rows = self._rows(ids)
            keys = {}
            for p in paths:
                key = path_key(self._rel(p))
                row = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (key,)).fetchone()
                keys[key] = row[0] if row else None
        return Check({i: (rows[i][3] if i in rows else None) for i in ids}, keys, _now())

    def _recheck(self, check, takeover_ok=None):
        if check is None:
            return
        rows = self._rows(check.items)
        for item_id, changed_in in check.items.items():
            now = rows[item_id][3] if item_id in rows else None
            if now != changed_in:
                raise StoreConflict("an item this change touches was changed meanwhile")
        for key, holder in check.keys.items():
            row = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (key,)).fetchone()
            now = row[0] if row else None
            if now != holder and not (takeover_ok and now is not None and takeover_ok(now)):
                raise StoreConflict("a file this change adds was added meanwhile")

    def _rel(self, path):
        """A path under the data folder as the manifest writes it (relative, '/'); a relative path as is."""
        if os.path.isabs(path):
            path = os.path.relpath(path, self.data_dir)
        return path.replace("\\", "/")

    def _in_library(self, path):
        """Does `path` lie under the data folder? (`library_rel`)"""
        return library_rel(self.data_dir, path) is not None

    # --- order primitives (§6.5) ----------------------------------------------------------------- #

    def _beyond(self, tier, at, excl, direction, count):
        """Up to `count` rows (id, ord) of `tier` strictly beyond `at` (id, ord), nearest first, skipping
        `excl`; `at` None = from the tier's edge (the top going down, the end going up)."""
        limit = count + len(excl)
        if at is None:
            order = "ord, id" if direction > 0 else "ord DESC, id DESC"
            rows = self.conn.execute(f"SELECT id, ord FROM items WHERE tier = ? ORDER BY {order} LIMIT ?",
                                     (tier, limit))
        elif direction > 0:
            rows = self.conn.execute("SELECT id, ord FROM items WHERE tier = ? AND (ord, id) > (?, ?) "
                                     "ORDER BY ord, id LIMIT ?", (tier, at[1], at[0], limit))
        else:
            rows = self.conn.execute("SELECT id, ord FROM items WHERE tier = ? AND (ord, id) < (?, ?) "
                                     "ORDER BY ord DESC, id DESC LIMIT ?", (tier, at[1], at[0], limit))
        return [r for r in rows if r[0] not in excl][:count]

    def _key(self, item_id):
        return self.conn.execute("SELECT id, ord FROM items WHERE id = ?", (item_id,)).fetchone()

    def _put(self, tier, ids, where, changed_in):
        """Place `ids` (in order) contiguously in `tier` at `where` — ('after', id), ('before', id),
        ('top',) or ('end',) — touching only the rows that change: the placed items (tier, ord,
        `changed_in`) and, when the gap is spent, a local window re-spaced (ord only, §6.5)."""
        excl = set(ids)
        kind = where[0]
        if kind == "after":
            lo = self._key(where[1])
            nxt = self._beyond(tier, lo, excl, 1, 1)
            hi = nxt[0] if nxt else None
        elif kind == "before":
            hi = self._key(where[1])
            prv = self._beyond(tier, hi, excl, -1, 1)
            lo = prv[0] if prv else None
        elif kind == "top":
            lo = None
            first = self._beyond(tier, None, excl, 1, 1)
            hi = first[0] if first else None
        else:
            hi = None
            last = self._beyond(tier, None, excl, -1, 1)
            lo = last[0] if last else None
        keys = _keys_between(lo[1] if lo else None, hi[1] if hi else None, len(ids))
        others = []
        if not _valid(keys, lo[1] if lo else None, hi[1] if hi else None):
            keys, others = self._respace(tier, ids, lo, hi, excl)
        cmd = self._cmd
        self.conn.executemany("UPDATE items SET tier = ?, ord = ?, changed_in = ?, feed_in = ? WHERE id = ?",
                              [(tier, k, changed_in, cmd.version, i) for i, k in zip(ids, keys)])
        cmd.moved.update(ids)
        cmd.fed_inline.update(ids)
        cmd.tiers.add(tier)
        if others:          # a re-space: each row carries its new key to the windows (§12.8)
            self.conn.executemany("UPDATE items SET ord = ?, feed_in = ? WHERE id = ?",
                                  [(k, cmd.version, i) for i, k in others])

    def _respace(self, tier, ids, lo, hi, excl):
        """Local re-space (§6.5): up to 16 rows each side of the gap, renumbered with the placed items
        evenly across the keys just outside the window; doubled until the span gives 1.0 per slot; the
        whole tier renumbered only when the window reaches both ends. Returns (keys, [(id, ord)])."""
        width = RESPACE_WINDOW
        while True:
            before = self._beyond(tier, lo, excl, -1, width) if lo else []
            after = self._beyond(tier, hi, excl, 1, width) if hi else []
            members_lo = ([lo] if lo else []) + before[:width - 1]
            members_hi = ([hi] if hi else []) + after[:width - 1]
            bound_lo = before[width - 1][1] if len(before) >= width else None
            bound_hi = after[width - 1][1] if len(after) >= width else None
            if bound_lo is None and bound_hi is None:
                seq = [r[0] for r in self._tier_keys(tier) if r[0] not in excl]
                at = seq.index(lo[0]) + 1 if lo else 0
                seq[at:at] = ids
                keys = _keys_between(None, None, len(seq))
                mine = set(ids)
                placed = [k for i, k in zip(seq, keys) if i in mine]
                return placed, [(i, k) for i, k in zip(seq, keys) if i not in mine]
            window = [r[0] for r in reversed(members_lo)] + list(ids) + [r[0] for r in members_hi]
            keys = _keys_between(bound_lo, bound_hi, len(window))
            if _spread_ok(bound_lo, bound_hi, len(window)) and _valid(keys, bound_lo, bound_hi):
                mine = set(ids)
                placed = [k for i, k in zip(window, keys) if i in mine]
                return placed, [(i, k) for i, k in zip(window, keys) if i not in mine]
            width *= 2

    def _write_seqs(self, seqs, ords, placed, changed_in_of):
        """Write the final orders the bulk commands built: every `placed` item's tier, key and
        `changed_in`, and the keys a local re-space moved (ord only)."""
        moves, others = [], []
        for tier, seq in seqs.items():
            ids = seq.ids()
            here = {i for i in ids if i in placed}
            if not here:
                continue
            plan = _plan_ords(ids, ords, here)
            for item_id, key in plan.items():
                if item_id in here:
                    moves.append((tier, key, changed_in_of(item_id), self._cmd.version, item_id))
                else:
                    others.append((key, item_id))
            self._cmd.tiers.add(tier)
        self.conn.executemany("UPDATE items SET tier = ?, ord = ?, changed_in = ?, feed_in = ? WHERE id = ?", moves)
        placed_ids = [m[-1] for m in moves]
        self._cmd.moved.update(placed_ids)
        self._cmd.fed_inline.update(placed_ids)
        if others:                                             # re-spaced keys reach the windows too (§12.8)
            self.conn.executemany("UPDATE items SET ord = ?, feed_in = ? WHERE id = ?",
                                  [(k, self._cmd.version, i) for k, i in others])

    def _seqs(self, tiers):
        """({tier: _Seq}, {id: ord}) for the given tiers, as they stand."""
        seqs, ords = {}, {}
        for t in tiers:
            rows = self._tier_keys(t)
            ords.update(rows)
            seqs[t] = _Seq([r[0] for r in rows])
        return seqs, ords

    # --- commands (§6.6) ------------------------------------------------------------------------- #

    def move(self, ids, tier, before_id=None, after_id=None, check=None, by="user", explicit=None):
        """Drag: the block keeps its current relative order and lands contiguous before or after the
        anchor (neither = the top of `tier`). A tier change is Demote / Promote without moving files.
        A no-op — an anchor inside `ids`, or every item already in `tier` in the same sequence —
        commits nothing and returns None. `by`: who placed it, as the placement log records it (a
        program's name from the command line's `place --source`, ✅ G1.3-5); explicit when "user", or as
        `explicit` says (a placing rule the user turned on is the user's own action, D30)."""
        ids = list(dict.fromkeys(ids))
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}")
        anchor = before_id if before_id is not None else after_id
        if anchor is not None and anchor in ids:
            return None
        with self._command("move", by) as cmd:
            self._recheck(check)
            rows = self._rows(ids)
            if not rows:
                return None
            if anchor is not None:
                a = self._rows([anchor]).get(anchor)
                if a is None or a[1] != tier:
                    raise ValueError("the anchor is not in that tier")
            ordered = sorted(rows.values(), key=lambda r: (TIERS[r[1]][3], r[2], r[0]))
            block = [r[0] for r in ordered]
            where = ("before", before_id) if before_id is not None else \
                ("after", after_id) if after_id is not None else self._tier_top(tier, set(block))
            if self._in_place(tier, ordered, where[1] if where[0] == "before" else None,
                              where[1] if where[0] == "after" else None, end=where[0] == "end"):
                return None
            change = self._change(cmd, "move")
            self._before(change, ordered)
            self._put(tier, block, where, cmd.version)
            cmd.touch({r[1] for r in ordered} | {tier})
            for item_id in block:
                cmd.event(item_id, "placed", int(by == "user" if explicit is None else explicit),
                          by if by != cmd.by else None)
                if by != cmd.by:
                    cmd.event_by[item_id] = by
            return change

    def _in_place(self, tier, ordered, before_id, after_id, end=False):
        """True when the move would leave every item in `tier` and the tier's sequence unchanged (`end`: the block
        is to go to the tier's end)."""
        if any(r[1] != tier for r in ordered):
            return False
        first, last = ordered[0], ordered[-1]
        count = self.conn.execute(          # bounded: a scattered block never counts a whole tier
            "SELECT COUNT(*) FROM (SELECT 1 FROM items WHERE tier = ? AND (ord, id) >= (?, ?) AND (ord, id) <= (?, ?) "
            "LIMIT ?)", (tier, first[2], first[0], last[2], last[0], len(ordered) + 1)).fetchone()[0]
        if count != len(ordered):
            return False
        if before_id is not None:
            nxt = self._beyond(tier, (last[0], last[2]), set(), 1, 1)
            return bool(nxt) and nxt[0][0] == before_id
        if end:
            return not self._beyond(tier, (last[0], last[2]), set(), 1, 1)
        prv = self._beyond(tier, (first[0], first[2]), set(), -1, 1)
        if after_id is not None:
            return bool(prv) and prv[0][0] == after_id
        return not prv

    NUDGE_BATCH = 64

    def nudge(self, ids, direction):
        """▲▼ with today's group-jump rules (`move_items_in_manifest`) over the tier's order. "Visible"
        = in this tier and not missing, as the tree draws it. A non-contiguous selection becomes one
        block. Returns the move's change, or None when nothing moves. Reads only the rows between the selection
        and the row it jumps past (L3.1, §12.4 #11: a ▲ read the whole tier, 20 ms at 20k)."""
        rows = self._rows(ids)
        if not rows:
            return None
        tier = min(rows.values(), key=lambda r: (r[2], r[0]))[1]
        block = sorted((r for r in rows.values() if r[1] == tier), key=lambda r: (r[2], r[0]))
        info = {r[0]: (r[4], r[6]) for r in block}            # id -> (parent_folder, availability)
        up = direction == "up"
        edge = block[0] if up else block[-1]
        moving_parent = edge[4]
        target = None
        group = None
        at = (edge[0], edge[2])
        while True:
            batch = self.conn.execute(
                "SELECT id, ord, parent_folder, availability FROM items WHERE tier = ? AND (ord, id) {} (?, ?) "
                "ORDER BY ord {d}, id {d} LIMIT ?".format("<" if up else ">", d="DESC" if up else "ASC"),
                (tier, at[1], at[0], self.NUDGE_BATCH)).fetchall()
            if not batch:
                break
            for item_id, ord_, parent, availability in batch:
                at = (item_id, ord_)
                if item_id in info:
                    continue
                if target is None:
                    if availability == "missing":
                        continue
                    target = item_id
                    if not parent or parent == moving_parent:
                        group = None
                        break
                    group = parent
                    continue
                # extending the target's group: the same parent, visible, next to it
                if parent == group and availability != "missing":
                    target = item_id
                    continue
                group = None
                break
            else:
                continue
            if group is None:
                break
        if target is None:
            return None
        moving = [r[0] for r in block]
        if up:
            return self.move(moving, tier, before_id=target)
        return self.move(moving, tier, after_id=target)

    def _tier_top(self, tier, excl):
        """Where "the top of `tier`" is. Soon's top is the first slot below the Soon line (L2.2 05 §5.1), counted
        without the rows being placed: rows leaving NOW let the line take Soon's first rows up, so the slot is after
        Current's `soon_line`-th row once they're gone; with fewer rows than the line nothing can sit below it (the
        end of Soon, which the line then takes up). Any other tier: its top."""
        n = self._soon_line() if tier == "soon" else None
        if not n:
            return ("top",)
        now = self.conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'now'").fetchone()[0]
        leaving = 0
        for chunk in _chunks(list(excl), 500):
            leaving += self.conn.execute(f"SELECT COUNT(*) FROM items WHERE tier = 'now' AND id IN "
                                         f"({','.join('?' * len(chunk))})", chunk).fetchone()[0]
        need = n - (now - leaving)
        if need <= 0:
            return ("top",)
        rows = [r[0] for r in self.conn.execute("SELECT id FROM items WHERE tier = 'soon' ORDER BY ord, id LIMIT ?",
                                                (need + len(excl),)) if r[0] not in excl]
        return ("after", rows[need - 1]) if len(rows) >= need else ("end",)

    def _folder_last(self, tier, folder, excl):
        """The last row of `folder` (the placement key) in `tier`, skipping `excl`: (id, ord) or None."""
        for row in self.conn.execute("SELECT id, ord FROM items WHERE tier = ? AND parent_folder = ? "
                                     "ORDER BY ord DESC, id DESC LIMIT ?", (tier, folder, len(excl) + 1)):
            if row[0] not in excl:
                return row
        return None

    def set_tier(self, ids, tier, check=None, by="user", explicit=None):
        """Graduate (→ graduated, `graduated_at` set), Demote, Promote — no file moves (L5). Each item
        lands after its folder's last row in the new tier, else at the top, in the order given. `by` as
        `move`'s (the command line's `finish --source`)."""
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}")
        ids = list(dict.fromkeys(ids))
        with self._command("set_tier", by) as cmd:
            self._recheck(check)
            rows = self._rows(ids)
            moving = [i for i in ids if i in rows and rows[i][1] != tier]
            if not moving:
                return None
            change = self._change(cmd, "set_tier")
            self._before(change, [rows[i] for i in moving])
            excl = set(moving)
            groups = {}
            for item_id in moving:
                folder = rows[item_id][4]
                last = self._folder_last(tier, folder, excl) if folder else None
                where = ("after", last[0]) if last else self._tier_top(tier, excl)
                groups.setdefault(where, []).append(item_id)
            for where, group in groups.items():
                self._put(tier, group, where, cmd.version)
            if tier == "graduated":
                self.conn.executemany("UPDATE items SET graduated_at = ? WHERE id = ?",
                                      [(_now(), i) for i in moving])
            cmd.touch({rows[i][1] for i in moving} | {tier})
            for item_id in moving:
                cmd.event(item_id, "finished" if tier == "graduated" else "placed",
                          int(by == "user" if explicit is None else explicit), by if by != cmd.by else None)
                if by != cmd.by:
                    cmd.event_by[item_id] = by
            return change

    # --- adding files -------------------------------------------------------------------------- #

    def _prepare(self, files, entries, origin):
        """Outside any transaction (§6.6): each file's rel path, key, entry and fingerprint."""
        marker_cache = {}
        out = []
        for n, path in enumerate(files):
            rel = self._rel(path)
            full = os.path.join(self.data_dir, rel)
            entry = entries[n] if entries else make_entry(rel, origin, _detect_source_type(full, marker_cache))
            try:
                st = os.stat(full)
                fp = (st.st_size, st.st_mtime_ns, "available")
            except OSError:
                fp = (None, None, "missing")
            out.append((path, rel, path_key(rel), entry, fp))
        return out

    def _dir_rows(self, rel_dir_path, excl):
        """The items whose file sits directly in `rel_dir_path` (the show = the file's real directory)."""
        base = path_key(rel_dir_path) + "/"
        rows = self.conn.execute("SELECT id, tier, ord, rel_key FROM items WHERE root_id = ? AND rel_key > ? "
                                 "AND rel_key < ?", (self._root_id(), base, base[:-1] + "0")).fetchall()
        return [r for r in rows if r[0] not in excl and "/" not in r[3][len(base):]]

    def _destination(self, rel, entry, fallback_tier, excl):
        """Where a new file lands (§6.10 rule 3, Q4-9, Q4-11): hato's drop folder → the top of NOW; a
        tier folder's loose file → the top of its tier; a show (the file's real directory) with a row in
        NOW or Soon → right after its last row there (reading NOW → Soon); a show with rows but none
        there → the top of NOW; a directory with no item yet → today's rule in `fallback_tier` (after the
        folder's last row, else the top)."""
        folder_dir = _rel_dir(rel)
        dkey = path_key(folder_dir)
        hato = path_key(HATO_FOLDER)
        if dkey == hato or dkey.startswith(hato + "/"):
            return ("top", "now")
        if folder_dir in TIER_OF_FOLDER:
            return ("top", TIER_OF_FOLDER[folder_dir])
        rows = self._dir_rows(folder_dir, excl) if folder_dir else []
        if rows:
            for tier in ("soon", "now"):
                here = [r for r in rows if r[1] == tier]
                if here:
                    last = max(here, key=lambda r: (r[2], r[0]))
                    return ("after", last[0], tier)
            return ("top", "now")
        folder = _entry_folder(entry)
        last = self._folder_last(fallback_tier, folder, excl) if folder else None
        return ("after", last[0], fallback_tier) if last else ("top", fallback_tier)

    def _add_rows(self, prepared, version):
        """Insert new item rows (ids issued past every id ever used, K30), placed later by `_put`."""
        root = self._root_id()
        seq = self.conn.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'items'), 0), "
                                "COALESCE((SELECT MAX(id) FROM items), 0)").fetchone()
        next_id = max(seq) + 1
        now = _now()
        rows, ids = [], []
        for path, rel, key, entry, (size, mtime_ns, availability), tier in prepared:
            title, folder, source_type = _columns(entry)
            rows.append((next_id, root, rel, key, tier, 0.0, _dumps(entry), title, folder, source_type,
                         availability, size, mtime_ns, version, now, search_fold(title, self.language)))
            ids.append(next_id)
            next_id += 1
        self.conn.executemany(
            "INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, "
            "source_type, availability, size, mtime_ns, changed_in, added_at, search_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return ids

    def _takeover(self, key, started_at):
        """A row a sync created after `started_at` (the command's own file, caught mid-copy)."""
        row = self.conn.execute("SELECT id, entry, added_at FROM items WHERE rel_key = ?", (key,)).fetchone()
        if row is None or started_at is None or row[2] < started_at:
            return None
        entry = json.loads(row[1])
        return row[0] if entry.get("origin_source") == "Disk Sync" else None

    def insert(self, files, tier, placement="show", started_at=None, entries=None, check=None):
        """Add the files the command itself copied (Add Files, Add Folder, the preview), as one command:
        a, b, c lands a, b, c (L-Q6). `placement` "show" follows §6.10 rule 3 with `tier` (the tab
        chosen) for a directory that holds no item yet; "top" puts them at the top of `tier` (the
        preview). A file already an item is left where it is and reported in `change.existing`."""
        prepared = self._prepare(files, entries, "Manual Import")
        return self._add(prepared, tier, placement, None, started_at, check, "insert")

    def insert_at(self, files, anchor_id, before=True, started_at=None, entries=None, check=None):
        """`insert` at an anchor item: the files land contiguous, in the order given, before or after it,
        in its tier (the user chose the place, so Q4-9 doesn't apply)."""
        prepared = self._prepare(files, entries, "Manual Import")
        return self._add(prepared, None, "anchor", (anchor_id, before), started_at, check, "insert_at")

    def _add(self, prepared, tier, placement, anchor, started_at, check, kind, by="user", explicit=1):
        with self._command(kind, by) as cmd:
            self._recheck(check, takeover_ok=lambda i: self._takeover_id(i, started_at))
            change = self._change(cmd, kind)
            new, taken, seen = [], [], set()
            for item in prepared:
                path, rel, key, entry, fp = item
                if key in seen:
                    continue
                seen.add(key)
                row = self.conn.execute("SELECT id, tier FROM items WHERE rel_key = ?", (key,)).fetchone()
                if row is None:
                    new.append(item)
                elif self._takeover(key, started_at) is not None:
                    taken.append((row[0], item))
                else:
                    change.existing.append((path, row[0], row[1]))
            if not new and not taken:
                return change if change.existing else None
            excl = {i for i, _ in taken}
            if placement == "anchor":
                a = self._rows([anchor[0]]).get(anchor[0])
                if a is None:
                    raise StoreConflict("the anchor item is gone")
                dests = [("before" if anchor[1] else "after", a[0], a[1])] * (len(new) + len(taken))
            elif placement in ("top", "end"):
                dests = [(placement, tier)] * (len(new) + len(taken))
            else:
                dests = [self._destination(it[1], it[3], tier or "now", excl)
                         for it in [t[1] for t in taken] + new]
            dest_tier = [d[2] if d[0] in ("after", "before") else d[1] for d in dests]
            ids = [i for i, _ in taken]
            if taken:
                self._before(change, list(self._rows(ids).values()))
                self.conn.executemany(
                    "UPDATE items SET entry = ?, title = ?, parent_folder = ?, source_type = ?, search_key = ? "
                    "WHERE id = ?",
                    [(_dumps(it[3]),) + _columns(it[3]) + (search_fold(_columns(it[3])[0], self.language), i)
                     for i, it in taken])
            ids += self._add_rows([it + (t,) for it, t in zip(new, dest_tier[len(taken):])], cmd.version)
            groups = {}
            for item_id, dest, t in zip(ids, dests, dest_tier):
                where = (dest[0], dest[1]) if dest[0] in ("after", "before") else (dest[0],)
                groups.setdefault((t, where), []).append(item_id)
            for (t, where), group in groups.items():
                self._put(t, group, where, cmd.version)
            change.added = ids
            cmd.touch(set(dest_tier), availability=any(it[4][2] == "missing" for it in new))
            for item_id in ids:
                cmd.event(item_id, "placed", explicit)
            return change

    def _takeover_id(self, item_id, started_at):
        row = self.conn.execute("SELECT rel_key FROM items WHERE id = ?", (item_id,)).fetchone()
        return row is not None and self._takeover(row[0], started_at) == item_id

    def register(self, path, pairing, backfill=False, rules=None):
        """hato's command (headless): find the item for `path` (a sync may have made it) or add it — in
        `arrivals` when `meta.arrivals_on`; else a file in hato's drop folder at the top of NOW (Q4-11,
        through 2.x); else by §6.10 rule 3 (Q4-9) — and write its pairing (`pairing["content_key"]`, the
        record verbatim). An added item undoes as an Add; a pairing alone leaves `changed_in`.

        The record is written with its keys sorted and compared by its parsed value, so the same record in
        another key order (or a row written before keys were sorted) is the same: nothing written. A path not
        under the data folder raises `NotInLibrary` before anything is written (3.0's Sources widen this).
        `backfill` (P3.2: pairings hato made before Connect was on) attaches and places as above but logs no
        placement event for the item, so nothing is ever mined because of it (✅ G1.1-2's watermark). The events
        are logged as the record's `producer`'s (`_producer`: "hato" when it names none), never explicit.

        3.0 (L3.1): the record names its title first (`_work_by_record`: its ids, then its show), and an item that
        waits in New arrivals is placed by the user's rule for its source in the same command (`placing_rules`,
        05 §5.12: logged as the source's, explicit — D30); `rules` = {source: target} as the caller read them from
        settings.json (`placing_rules`; None or empty: it waits); a back-fill places by no rule."""
        content_key = pairing["content_key"]
        rel = library_rel(self.data_dir, path)
        if rel is None:
            raise NotInLibrary(f"not in the library: {path}")
        prepared = self._prepare([rel], None, "hato")     # normalised: one key per file (a/../b.srt is b.srt)
        by = _producer(pairing)
        with self._command("register", by) as cmd:
            meta = cmd.meta
            _p, rel, key, entry, fp = prepared[0]
            row = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (key,)).fetchone()
            change = None
            if row is None:
                if meta.get("arrivals_on"):
                    change = self._add(prepared, "arrivals", "end", None, None, None, "register", by, 0)
                else:
                    first = rel.split("/", 1)[0]
                    change = self._add(prepared, TIER_OF_FOLDER.get(first, "now"), "show", None, None, None,
                                       "register", by, 0)
                item_id = change.added[0]
                work = self._work_by_record(pairing)            # the record names its title first (K81)
                if work is None and _show_title(pairing) and folder_key_of(rel) is None:
                    work = self._new_work(_show_title(pairing), None, cmd)     # a loose drop: titled by its show
                if work is not None:
                    self.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (work, item_id))
                else:
                    self._settle_works(cmd)
            else:
                item_id = row[0]
                self._title_scanned_drop(cmd, item_id, rel, pairing)
            work = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]
            if work is not None:
                holder = change if change is not None else self._change(cmd, "register")
                self._fill_work(cmd, holder, work, pairing)
                if change is None and holder.works is not None:
                    change = holder
            if backfill:
                cmd.quiet.add(item_id)
            elif rules and self.conn.execute("SELECT tier FROM items WHERE id = ?", (item_id,)).fetchone()[0] == \
                    "arrivals":
                placed = self._apply_rule(item_id, pairing, rules)
                if placed and change is None:
                    change = self._change(cmd, "register")
                if placed:
                    change.rule = placed
            old = self.conn.execute("SELECT item_id, pairing, paired_at FROM pairings WHERE content_key = ?",
                                    (content_key,)).fetchone()
            record = json.dumps(pairing, sort_keys=True, ensure_ascii=False)
            if old is not None and old[0] == item_id and _same_record(old[1], pairing):
                return change
            self.conn.execute("INSERT OR REPLACE INTO pairings (content_key, item_id, pairing, paired_at) "
                              "VALUES (?, ?, ?, ?)", (content_key, item_id, record, _now()))
            cmd.touch()
            if change is None:
                change = self._change(cmd, "register")
            change.pairing_before = (content_key, old)
            change.pairing_item = item_id
            return change

    # --- remove and put back ------------------------------------------------------------------- #

    def remove(self, ids, trashed_paths=None, check=None, by="user", kind="remove"):
        """Rows → the trash table, each with its neighbours just before the removal (removed ones
        included), its entry, its state, its pairings and Anki links, and where its file went
        (`trashed_paths`: {id: path relative to data/<lang>}, the caller's file work). The trash rows are
        written first, then the item rows deleted; their pairings and links follow by ON DELETE CASCADE."""
        trashed_paths = trashed_paths or {}
        with self._command(kind, by) as cmd:
            self._recheck(check)
            rows = self._rows(ids)
            if not rows:
                return None
            change = self._change(cmd, kind)
            ordered = self._before(change, list(rows.values()))
            near = {it["id"]: (it["prev"], it["next"]) for it in change.items}
            full = {}
            cur = self.conn.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(rows))})", list(rows))
            names = [d[0] for d in cur.description]
            for r in cur.fetchall():
                full[r[0]] = dict(zip(names, r))
            marks = ",".join("?" * len(rows))
            pairs, links = {}, {}
            for p in self.conn.execute(f"SELECT content_key, item_id, pairing, paired_at FROM pairings "
                                       f"WHERE item_id IN ({marks})", list(rows)):
                pairs.setdefault(p[1], []).append([p[0], p[2], p[3]])
            for a in self.conn.execute(f"SELECT item_id, note_id, source, linked_at FROM anki_links "
                                       f"WHERE item_id IN ({marks})", list(rows)):
                links.setdefault(a[0], []).append([a[1], a[2], a[3]])
            now = _now()
            trash_rows = []
            for r in ordered:
                item = full[r[0]]
                state = {k: v for k, v in item.items() if k not in ("entry", "rel_path", "tier", "ord")}
                state = {"columns": state, "pairings": pairs.get(r[0], []), "anki_links": links.get(r[0], [])}
                trash_rows.append((r[0], item["root_id"], item["rel_path"], item["tier"], near[r[0]][0],
                                   near[r[0]][1], item["entry"], _dumps(state), trashed_paths.get(r[0]), now))
            first = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM trash").fetchone()[0] + 1
            self.conn.executemany(
                "INSERT INTO trash (item_id, root_id, rel_path, tier, prev_id, next_id, entry, item_state, "
                "trashed_path, removed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", trash_rows)
            change.trash_ids = list(range(first, first + len(trash_rows)))
            self.conn.execute(f"DELETE FROM items WHERE id IN ({marks})", list(rows))
            cmd.gone += [("item", i) for i in rows]
            cmd.pieces_left.update(full[i]["piece_id"] for i in rows if full[i]["piece_id"] is not None)
            cmd.touch({r[1] for r in ordered}, availability=any(r[6] == "missing" for r in ordered))
            for r in ordered:
                cmd.event(r[0], "removed", 1)
            return change

    def trash_rows(self, trash_ids=None):
        """The trash table's rows as dicts (newest last), for Put back."""
        sql = "SELECT * FROM trash"
        params = []
        if trash_ids is not None:
            sql += f" WHERE id IN ({','.join('?' * len(trash_ids))})"
            params = list(trash_ids)
        cur = self.conn.execute(sql + " ORDER BY id", params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def restore(self, trash_ids, rel_paths=None, by="user", kind="restore", explicit_of=None):
        """Put back (§6.6): each row after its recorded predecessor if that item is in the tier (never
        removed, or put back already), else after that one's own recorded predecessor, along the trash
        rows; else before its successor, by the same chain; else at the top. Pairings and Anki links come
        back (a key paired again since keeps the newer). `rel_paths` {trash_id: rel} carries a new name
        the file got when it was put back. A row already restored is refused."""
        rel_paths = rel_paths or {}
        with self._command(kind, by) as cmd:
            rows = self.trash_rows(trash_ids)
            if len(rows) != len(set(trash_ids)):
                raise StoreConflict("a trash row is gone")
            if any(r["restored_at"] for r in rows):
                raise StoreConflict("already put back")
            change = self._change(cmd, kind)
            now = _now()
            for r in sorted(rows, key=lambda r: list(trash_ids).index(r["id"])):
                rel = rel_paths.get(r["id"], r["rel_path"])
                key = path_key(rel)
                if self.conn.execute("SELECT 1 FROM items WHERE rel_key = ?", (key,)).fetchone():
                    raise StoreConflict(f"{rel} is in the library again")
                entry = json.loads(r["entry"])
                if rel != r["rel_path"]:
                    entry["physical_path"] = rel
                    entry["title"] = rel.rsplit("/", 1)[-1]
                state = json.loads(r["item_state"])
                cols = state["columns"]
                full = os.path.join(self.data_dir, rel)
                try:
                    st = os.stat(full)
                    size, mtime_ns, availability = st.st_size, st.st_mtime_ns, "available"
                except OSError:
                    size, mtime_ns, availability = cols.get("size"), cols.get("mtime_ns"), "missing"
                title, folder, source_type = _columns(entry)
                # an undo restores the `changed_in` the removal replaced (§6.11), so a second undo in a row
                # still finds its own version; Put back is a new change
                changed_in = (cols.get("changed_in") or cmd.version) if kind == "undo" else cmd.version
                work = cols.get("work_id")
                if work is not None and not self.conn.execute("SELECT 1 FROM works WHERE id = ?", (work,)).fetchone():
                    work = None                                    # merged away meanwhile: its folder finds one (6.5)
                self.conn.execute(
                    "INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, "
                    "source_type, availability, size, mtime_ns, changed_in, added_at, graduated_at, piece_id, "
                    "watched, mined_at, pinned, in_learning_order, work_id, search_key, mine_asked) "
                    "VALUES (?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["item_id"], r["root_id"], rel, key, r["tier"], _dumps(entry), title, folder, source_type,
                     availability, size, mtime_ns, changed_in, cols.get("added_at") or now,
                     cols.get("graduated_at"), self._piece_or_none(cols.get("piece_id")), cols.get("watched", 0),
                     cols.get("mined_at"), cols.get("pinned"), cols.get("in_learning_order", 1), work,
                     search_fold(title, self.language), cols.get("mine_asked")))
                cmd.back.add(r["item_id"])
                self._put(r["tier"], [r["item_id"]], self._restore_where(r), changed_in)
                self.conn.executemany("INSERT OR IGNORE INTO pairings (content_key, item_id, pairing, paired_at) "
                                      "VALUES (?, ?, ?, ?)", [(k, r["item_id"], p, at) for k, p, at in state["pairings"]])
                self.conn.executemany("INSERT OR IGNORE INTO anki_links (item_id, note_id, source, linked_at) "
                                      "VALUES (?, ?, ?, ?)", [(r["item_id"], n, s, at) for n, s, at in state["anki_links"]])
                self.conn.execute("UPDATE trash SET restored_at = ? WHERE id = ?", (now, r["id"]))
                change.restored.append(r["id"])
                change.added.append(r["item_id"])
                cmd.touch({r["tier"]}, availability=availability == "missing")
                cmd.event(r["item_id"], "restored", explicit_of(r["item_id"]) if explicit_of else 1)
            return change

    def _piece_or_none(self, piece_id):
        if piece_id is None:
            return None
        row = self.conn.execute("SELECT 1 FROM pieces WHERE id = ?", (piece_id,)).fetchone()
        return piece_id if row else None

    def _restore_where(self, r):
        tier = r["tier"]

        def in_tier(item_id):
            row = self.conn.execute("SELECT tier FROM items WHERE id = ?", (item_id,)).fetchone()
            return row is not None and row[0] == tier

        def recorded(item_id, column):
            row = self.conn.execute(f"SELECT {column} FROM trash WHERE item_id = ? ORDER BY id DESC LIMIT 1",
                                    (item_id,)).fetchone()
            return (True, row[0]) if row else (False, None)

        for column, side in (("prev_id", "after"), ("next_id", "before")):
            seen = set()
            item = r[column]
            while item is not None and item not in seen:
                seen.add(item)
                if in_tier(item):
                    return (side, item)
                found, item = recorded(item, column)
                if not found:
                    break
        return ("top",)

    # --- settling (schema 2, L3.1): every command ends here, inside its transaction ---------------- #

    def _settle(self, cmd):
        """What every command leaves true (the L2.2 pack): each new item has a work (05 §5.3); Current's first
        `soon_line` rows are NOW and the rest Soon (05 §5.1); every piece the command touched is one run of one work in
        one tier (05 §5.2); each row it changed carries its version in `feed_in`, each row it took out a tombstone
        (04 §4.1). Called by `_Command.finish` before the versions and the log, so the log sees the settled order."""
        self._settle_works(cmd)
        if (cmd.meta.get("rename_asks") or "[]") != "[]":
            self._tidy_asks()
        if cmd.line_set or cmd.tiers & set(CURRENT):
            self._keep_line(cmd)
        self._fix_pieces(cmd)
        self._write_feed(cmd)

    def _new_work(self, title, fk, cmd, titles=()):
        titles = [t for t in titles if t and t != title]
        cur = self.conn.execute(
            "INSERT INTO works (title, titles, search_key, folder_key, feed_in, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (title, _dumps(titles), _work_search_key(title, titles, self.language), fk, cmd.version, _now()))
        cmd.fed_works.add(cur.lastrowid)
        return cur.lastrowid

    def _folder_work(self, rel, title, cmd, cache=None):
        """A new file's work by its folder (05 §5.3 (3)–(4)): the work holding its folder key; else the work of the
        files beside it (a folder whose work was merged into another keeps going there); else a new work, titled by
        its folder below the tier folder, or by its own title when it is loose."""
        fk = folder_key_of(rel)
        if cache is not None and fk is not None and fk in cache:
            return cache[fk]
        wid = None
        if fk is not None:
            row = self.conn.execute("SELECT id FROM works WHERE folder_key = ? ORDER BY id LIMIT 1", (fk,)).fetchone()
            wid = row[0] if row else None
            if wid is None:
                folder = _rel_dir(_strip(rel))
                base = path_key(folder) + "/"
                row = self.conn.execute(
                    "SELECT work_id FROM items WHERE rel_key > ? AND rel_key < ? AND work_id IS NOT NULL "
                    "AND instr(substr(rel_key, ?), '/') = 0 ORDER BY ord DESC LIMIT 1",
                    (base, base[:-1] + "0", len(base) + 1)).fetchone()
                wid = row[0] if row else None
        if wid is None:
            wid = self._new_work(_below_tier(rel) if fk is not None else (title or rel.rsplit("/", 1)[-1]), fk, cmd)
        if cache is not None and fk is not None:
            cache[fk] = wid
        return wid

    def _work_by_record(self, record):
        """A record's work (05 §5.3 (1)–(2), `register`'s only): the work holding its AniList / TMDB id (or YouTube
        channel), else one whose folded title or other title is its show's title; None."""
        ids = _work_ids_of(record)
        for col in ("anilist_id", "tmdb_id", "youtube_channel"):
            if ids[col] is not None:
                row = self.conn.execute(f"SELECT id FROM works WHERE {col} = ? ORDER BY id LIMIT 1",
                                        (ids[col],)).fetchone()
                if row:
                    return row[0]
        title = _show_title(record)
        if title:
            key = search_fold(title, self.language)
            mine = _episode(record)
            season = mine[0] if mine else (record.get("show") or {}).get("season") or 1
            for (work,) in self.conn.execute("SELECT id FROM works WHERE instr(char(10) || search_key || char(10), ?) "
                                             "> 0 ORDER BY id", ("\n" + key + "\n",)).fetchall():
                seasons = set()
                for (text,) in self.conn.execute("SELECT pairing FROM pairings WHERE item_id IN "
                                                 "(SELECT id FROM items WHERE work_id = ?)", (work,)):
                    try:
                        ep = _episode(json.loads(text))
                    except ValueError:
                        continue
                    if ep is not None:
                        seasons.add(ep[0])
                if not seasons or season in seasons:            # another season is another title
                    return work
        return None

    def _title_scanned_drop(self, cmd, item_id, rel, record):
        """A loose drop the folder scan found before hato's hand-off (✅ L3.1 call b; the intent review #2) sits in a
        title of its own, named by its file: on the first hand-off the record's title takes it, as `register` places a
        new drop (`_work_by_record`, else a new title named by its show). Only that title: alone, never paired, no id,
        nothing of the user's in it. The emptied title goes in the helper's run (`tidy_works`)."""
        if folder_key_of(rel) is not None or \
                self.conn.execute("SELECT 1 FROM pairings WHERE item_id = ?", (item_id,)).fetchone():
            return
        cur, title = self.conn.execute("SELECT work_id, title FROM items WHERE id = ?", (item_id,)).fetchone()
        w = self._work_row(cur) if cur is not None else None
        if w is None or w["title"] != title or w["title_by_user"] or w["media_type_by"] == "user" or \
                w["cover_locked"] or w["cover_source"] == "user" or \
                any(w[c] is not None for c in ("anilist_id", "tmdb_id", "youtube_channel")) or \
                self.conn.execute("SELECT COUNT(*) FROM items WHERE work_id = ?", (cur,)).fetchone()[0] != 1:
            return
        target = self._work_by_record(record)
        if target is None and _show_title(record):
            target = self._new_work(_show_title(record), None, cmd)
        if target is None or target == cur:
            return
        self.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (target, item_id))
        cmd.reworked.add(item_id)
        cmd.feed([item_id])
        cmd.fed_works.update((cur, target))
        cmd.touch()

    def _fill_work(self, cmd, change, work_id, record, by="hato"):
        """What a record says of its work, never over the user's (03 §3.3): its ids where the work has none — an id
        another work holds makes the two one title (the lower id kept, G2.2-6); its show's title among the other titles;
        its media type unless the user chose one. Returns the work the record's item now belongs to."""
        ids = _work_ids_of(record)
        for col in ("anilist_id", "tmdb_id", "youtube_channel"):
            if ids[col] is None:
                continue
            current = self.conn.execute(f"SELECT {col} FROM works WHERE id = ?", (work_id,)).fetchone()[0]
            if current is not None:
                continue                                        # the work's own id stays (a record never re-points it)
            other = self.conn.execute(f"SELECT id FROM works WHERE {col} = ? AND id != ?", (ids[col], work_id)).fetchone()
            if other is not None:
                keep, drop = sorted((other[0], work_id))
                self._merge_into(cmd, change, keep, [drop], users_first=True)
                work_id = keep
            else:
                self._set_work_fields(cmd, change, work_id, {col: ids[col]})
        title = _show_title(record)
        row = self.conn.execute("SELECT title, titles, media_type_by FROM works WHERE id = ?", (work_id,)).fetchone()
        titles = json.loads(row[1] or "[]")
        if title and title != row[0] and title not in titles:
            self._set_work_fields(cmd, change, work_id, {"titles": _dumps(titles + [title])})
        kind = record.get("media_type") if isinstance(record, dict) else None
        if kind in MEDIA_TYPES and row[2] != "user":
            self._set_work_fields(cmd, change, work_id, {"media_type": kind, "media_type_by": by})
        return work_id

    def _set_work_fields(self, cmd, change, work_id, fields):
        """Write a work's columns, keeping each old value for undo (the value check) and its search key in step."""
        cols = list(fields)
        row = self.conn.execute(f"SELECT {', '.join(cols)} FROM works WHERE id = ?", (work_id,)).fetchone()
        if row is None:
            return False
        changed = {c: v for c, old, v in zip(cols, row, [fields[c] for c in cols]) if old != v}
        if not changed:
            return False
        if change.works is None:
            change.works = {"rows": [], "items": [], "fields": [], "created": []}
        change.works["fields"] += [(work_id, c, old, fields[c]) for c, old in zip(cols, row) if c in changed]
        self.conn.execute(f"UPDATE works SET {', '.join(c + ' = ?' for c in changed)} WHERE id = ?",
                          list(changed.values()) + [work_id])
        if {"title", "titles"} & set(changed):
            self._rekey_work(work_id)
        cmd.fed_works.add(work_id)
        cmd.touch()
        return True

    def _rekey_work(self, work_id):
        title, titles = self.conn.execute("SELECT title, titles FROM works WHERE id = ?", (work_id,)).fetchone()
        self.conn.execute("UPDATE works SET search_key = ? WHERE id = ?",
                          (_work_search_key(title, json.loads(titles or "[]"), self.language), work_id))

    def _work_row(self, work_id):
        cur = self.conn.execute("SELECT * FROM works WHERE id = ?", (work_id,))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    def _merge_into(self, cmd, change, keep_id, other_ids, users_first=False):
        """`merge_works`' body, inside a command: the others' items, ids, folder key, titles and — where the kept work
        has none of its own — media type and cover move to `keep_id`; the others go (a tombstone each). The kept
        cover stays unless it is generated and another's isn't (05 §5.5). `users_first` (a merge no one asked for: a
        record's id another title holds, G2.2-6): the user's own name, type and cover on a merged-away title win over
        the kept title's that aren't the user's (G4: nothing automatic changes them; L3.1's intent review #1)."""
        keep = self._work_row(keep_id)
        others = [w for w in (self._work_row(o) for o in other_ids if o != keep_id) if w]
        if keep is None or not others:
            return False
        if change.works is None:
            change.works = {"rows": [], "items": [], "fields": [], "created": []}
        change.works["rows"] += [dict(o) for o in others]          # the kept work's own changes go in "fields"
        moved = []
        for o in others:
            moved += [(r[0], o["id"]) for r in self.conn.execute("SELECT id FROM items WHERE work_id = ?", (o["id"],))]
        fields = {}
        titles = json.loads(keep["titles"] or "[]")
        users_cover = lambda w: bool(w.get("cover_locked")) or w.get("cover_source") == "user"
        for o in others:
            for t in [o["title"]] + json.loads(o["titles"] or "[]"):
                if t and t != keep["title"] and t not in titles:
                    titles.append(t)
            for col in ("anilist_id", "tmdb_id", "youtube_channel", "folder_key"):
                if keep[col] is None and fields.get(col) is None and o[col] is not None:
                    fields[col] = o[col]
            users_type = users_first and o["media_type_by"] == "user" and \
                "user" not in (keep["media_type_by"], fields.get("media_type_by"))
            if o["media_type"] is not None and (users_type or (keep["media_type"] is None and "media_type" not in fields)):
                fields["media_type"], fields["media_type_by"] = o["media_type"], o["media_type_by"]
            users_art = users_first and users_cover(o) and not users_cover(keep) and not users_cover(fields)
            if users_art or (keep["cover_source"] in (None, "generated") and "cover_source" not in fields and
                             o["cover_source"] not in (None, "generated")):
                for col in ("cover_source", "cover_ref", "cover_path", "cover_fetched_at", "cover_locked"):
                    fields[col] = o[col]
            if users_first and o["title_by_user"] and not keep["title_by_user"] and "title" not in fields:
                fields["title"], fields["title_by_user"] = o["title"], 1          # the user's name shows
        if fields.get("title", keep["title"]) != keep["title"]:
            titles = [t for t in titles if t != fields["title"]] + [keep["title"]]   # the kept name stays findable
        fields["titles"] = _dumps(titles)
        self.conn.executemany("UPDATE items SET work_id = ? WHERE id = ?", [(keep_id, i) for i, _o in moved])
        change.works["items"] += [(i, o, keep_id) for i, o in moved]
        cmd.feed(i for i, _o in moved)
        self.conn.executemany("UPDATE works SET anilist_id = NULL, tmdb_id = NULL, youtube_channel = NULL WHERE id = ?",
                              [(o["id"],) for o in others])           # the unique ids free before the kept takes them
        self._set_work_fields(cmd, change, keep_id, fields)
        self.conn.executemany("DELETE FROM works WHERE id = ?", [(o["id"],) for o in others])
        cmd.gone += [("work", o["id"]) for o in others]
        cmd.fed_works.add(keep_id)
        cmd.touch()
        return True

    def rename_work(self, work_id, title):
        """The user's name for a title (03 §3.3 #2): `title_by_user` set, so no record, match or sync renames it; the
        old name stays among the other titles (search still finds it). Undo by the value check."""
        title = (title or "").strip()
        if not title:
            raise ValueError("a title needs a name")
        with self._command("rename_work") as cmd:
            row = self._work_row(work_id)
            if row is None or (row["title"] == title and row["title_by_user"]):
                return None
            change = self._change(cmd, "rename_work")
            titles = json.loads(row["titles"] or "[]")
            if row["title"] != title and row["title"] not in titles:
                titles.append(row["title"])
            titles = [t for t in titles if t != title]
            self._set_work_fields(cmd, change, work_id, {"title": title, "title_by_user": 1, "titles": _dumps(titles)})
            return change

    def merge_works(self, keep_id, other_ids):
        """*Same title as …* (04 §4.2): the others' items and ids move to `keep_id` and the others go. Pieces stay as
        they are (each is still one title's). Undo restores the works and each item's work."""
        with self._command("merge_works") as cmd:
            change = self._change(cmd, "merge_works")
            if not self._merge_into(cmd, change, keep_id, list(dict.fromkeys(other_ids))):
                return None
            self._drop_apart(keep_id, other_ids)
            return change

    def split_work(self, item_ids, title):
        """*Not part of this title* (04 §4.2): a new title for these items (no folder key: new files in their folder
        keep joining the title they were in); the pieces they leave split where the title changes. Undo merges back."""
        title = (title or "").strip()
        if not title:
            raise ValueError("a title needs a name")
        with self._command("split_work") as cmd:
            rows = self.conn.execute(f"SELECT id, work_id FROM items WHERE id IN ({','.join('?' * len(item_ids))})",
                                     list(item_ids)).fetchall() if item_ids else []
            if not rows:
                return None
            change = self._change(cmd, "split_work")
            change.works = {"rows": [], "items": [], "fields": [], "created": []}
            new = self._new_work(title, None, cmd)
            self.conn.execute("UPDATE works SET title_by_user = 1 WHERE id = ?", (new,))
            change.works["created"].append(new)
            self.conn.executemany("UPDATE items SET work_id = ? WHERE id = ?", [(new, i) for i, _w in rows])
            change.works["items"] += [(i, w, new) for i, w in rows]
            cmd.reworked.update(i for i, _w in rows)
            cmd.feed(i for i, _w in rows)
            cmd.touch()
            return change

    def _undo_works(self, cmd, change):
        """Undo a works' command by the value check (§6.11): each field back where it still holds what the command
        wrote (the kept work's ids first, so the merged works can take theirs back); the works a merge took out back as
        they were; items back where they still sit in the work it gave them; a work it made goes once empty."""
        out = self._change(cmd, "undo")
        works = change.works
        skipped = []
        for work_id, col, old, new in reversed(works["fields"]):
            row = self.conn.execute(f"SELECT {col} FROM works WHERE id = ?", (work_id,)).fetchone()
            if row is not None and row[0] == new:
                self.conn.execute(f"UPDATE works SET {col} = ? WHERE id = ?", (old, work_id))
                self._rekey_work(work_id)
                cmd.fed_works.add(work_id)
        for row in works["rows"]:
            if self.conn.execute("SELECT 1 FROM works WHERE id = ?", (row["id"],)).fetchone():
                continue
            ids = {c: row[c] for c in ("anilist_id", "tmdb_id", "youtube_channel") if row[c] is not None}
            held = [c for c, v in ids.items()
                    if self.conn.execute(f"SELECT 1 FROM works WHERE {c} = ?", (v,)).fetchone()]
            row = dict(row, **{c: None for c in held})         # an id taken again since stays with its holder
            self.conn.execute(f"INSERT INTO works ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                              list(row.values()))
            self.conn.execute("DELETE FROM gone WHERE kind = 'work' AND id = ?", (row["id"],))
            cmd.fed_works.add(row["id"])
        back = []
        for item_id, old, new in works["items"]:
            now = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()
            if now is not None and now[0] == new and \
                    self.conn.execute("SELECT 1 FROM works WHERE id = ?", (old,)).fetchone():
                back.append((old, item_id))
            else:
                skipped.append(item_id)
        if back:
            self.conn.executemany("UPDATE items SET work_id = ? WHERE id = ?", back)
            cmd.reworked.update(i for _o, i in back)
            cmd.feed(i for _o, i in back)
        for work_id in works["created"]:
            if not self.conn.execute("SELECT 1 FROM items WHERE work_id = ?", (work_id,)).fetchone():
                self.conn.execute("DELETE FROM works WHERE id = ?", (work_id,))
                cmd.gone.append(("work", work_id))
        cmd.touch()
        return out, skipped

    def keep_apart(self, work_ids):
        """*Keep apart* (05 §5.3): the user's answer that titles sharing a name are different titles — *Same title?*
        stops asking about them. Bookkeeping the copy carries (`meta.kept_apart`)."""
        ids = sorted({int(w) for w in work_ids})
        if len(ids) < 2:
            return False
        with self._writing():
            pairs = json.loads(self._meta().get("kept_apart") or "[]")
            new = [[a, b] for n, a in enumerate(ids) for b in ids[n + 1:] if [a, b] not in pairs]
            if not new:
                return False
            self._set_meta({"kept_apart": _dumps(pairs + new), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})
        return True

    def _drop_apart(self, keep_id, other_ids):
        pairs = json.loads(self._meta().get("kept_apart") or "[]")
        gone = set(other_ids)
        kept = [p for p in pairs if not gone & set(p)]
        if kept != pairs:
            self._set_meta({"kept_apart": _dumps(kept)})

    def same_titles(self):
        """*Same title?* (05 §5.3, G2.2-6): groups of works whose folded titles are equal and whose ids don't already
        say they're different, never joined automatically; minus the pairs the user kept apart. Derived on read."""
        apart = {tuple(p) for p in json.loads(self._meta().get("kept_apart") or "[]")}
        groups = {}
        for work_id, key, anilist, tmdb in self.conn.execute("SELECT id, search_key, anilist_id, tmdb_id FROM works "
                                                             "ORDER BY id"):
            title = key.split("\n", 1)[0]
            if title:
                groups.setdefault(title, []).append((work_id, anilist, tmdb))
        out = []
        for members in groups.values():
            if len(members) < 2:
                continue
            ids = [m[0] for m in members]
            distinct = len({m[1] for m in members if m[1] is not None}) > 1 or \
                len({m[2] for m in members if m[2] is not None}) > 1
            if distinct:
                continue
            if all((a, b) in apart for n, a in enumerate(ids) for b in ids[n + 1:]):
                continue
            out.append(ids)
        return out

    def search(self, query, tiers=("now", "soon", "goal", "arrivals", "graduated")):
        """The window's search (05 §5.3), on its reader worker: (work ids, item ids) whose folded key holds the folded
        query, the works first — over Current, 6+ Months, New arrivals and Finished. Romaji finds a title only through a
        romaji title among its other titles (G2.2-4: no converter)."""
        key = search_fold(query, self.language)
        if not key:
            return [], []
        tiers = [t for t in tiers if t in TIERS]
        if not tiers:
            return [], []
        marks = ",".join("?" * len(tiers))
        with self._reading():      # the keys alone are scanned (`items_search`); a hit's tier read only for a subset
            works = [r[0] for r in self.conn.execute(
                f"SELECT id FROM works w WHERE instr(search_key, ?) > 0 AND EXISTS "
                f"(SELECT 1 FROM items i WHERE i.work_id = w.id AND i.tier IN ({marks})) ORDER BY id", [key] + tiers)]
            try:
                items = [r[0] for r in self.conn.execute(
                    "SELECT id FROM items INDEXED BY items_search WHERE instr(search_key, ?) > 0", (key,))]
            except sqlite3.OperationalError:                   # a store built before the index (development only)
                items = [r[0] for r in self.conn.execute("SELECT id FROM items WHERE instr(search_key, ?) > 0", (key,))]
            if set(tiers) != set(TIERS):
                wanted = set(tiers)
                items = [i for c in _chunks(items, 500) for i, t in self.conn.execute(
                    f"SELECT id, tier FROM items WHERE id IN ({','.join('?' * len(c))})", c) if t in wanted]
        return works, sorted(items)

    def _settle_works(self, cmd):
        """Items the command added (or put back from a work merged away) get their work by their folder."""
        if not cmd.moved:
            return
        cache, sets = {}, []
        for chunk in _chunks(list(cmd.moved), 500):
            for item_id, rel, title in self.conn.execute(
                    f"SELECT id, rel_path, title FROM items WHERE work_id IS NULL AND id IN ({','.join('?' * len(chunk))})",
                    chunk).fetchall():
                sets.append((self._folder_work(rel, title, cmd, cache), item_id))
        if sets:
            self.conn.executemany("UPDATE items SET work_id = ? WHERE id = ?", sets)
            cmd.fed.update(i for _w, i in sets)

    def _soon_line(self):
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'soon_line'").fetchone()
        try:
            return int(row[0]) if row else None
        except (TypeError, ValueError):
            return None

    def _keep_line(self, cmd):
        """The tiers follow the line (05 §5.1, G2.2-1): Current is NOW then Soon in one order; its first `soon_line`
        rows, available or missing, are NOW. A row crossing takes the command's version (a tier change, as any)."""
        n = self._soon_line()
        if n is None:
            return
        now = self.conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'now'").fetchone()[0]
        if now > n:
            down = [r[0] for r in self.conn.execute("SELECT id FROM items WHERE tier = 'now' ORDER BY ord DESC, id DESC "
                                                    "LIMIT ?", (now - n,))][::-1]
            self._put("soon", down, ("top",), cmd.version)
            cmd.touch(CURRENT)
        elif now < n:
            up = [r[0] for r in self.conn.execute("SELECT id FROM items WHERE tier = 'soon' ORDER BY ord, id LIMIT ?",
                                                  (n - now,))]
            if up:
                self._put("now", up, ("end",), cmd.version)
                cmd.touch(CURRENT)

    BIG_SETTLE = 200      # items: from here the settling step reads each touched tier's order once

    def _order_view(self, tiers):
        """{tier: ({id: (index, piece_id, work_id)}, [ids])} — a tier's whole order read once, for a command that
        touched many rows (a whole-tier move: one read instead of a query per row)."""
        view = {}
        for tier in tiers:
            rows = self.conn.execute("SELECT id, piece_id, work_id FROM items WHERE tier = ? ORDER BY ord, id",
                                     (tier,)).fetchall()
            view[tier] = ({r[0]: (n, r[1], r[2]) for n, r in enumerate(rows)}, [r[0] for r in rows])
        return view

    def _near(self, ids, view=None):
        """{id: ((prev_id, prev_piece, prev_work), (next_id, next_piece, next_work))} for `ids` ({id: tier}), in each
        item's tier as the rows stand now; (None, None, None) at a tier's edge. With `view`, read from it for the tiers
        it holds."""
        out, rest = {}, []
        none = (None, None, None)
        for item_id, tier in ids.items():
            if view is not None and tier in view:
                index, order = view[tier]
                n = index[item_id][0]
                prev = order[n - 1] if n > 0 else None
                nxt = order[n + 1] if n + 1 < len(order) else None
                out[item_id] = ((prev,) + index[prev][1:] if prev is not None else none,
                                (nxt,) + index[nxt][1:] if nxt is not None else none)
            else:
                rest.append(item_id)
        for chunk in _chunks(rest, 300):
            sql = ("WITH m(id) AS (VALUES %s) SELECT x.id, "
                   "(SELECT i.id FROM items i WHERE i.tier = x.tier AND (i.ord, i.id) < (x.ord, x.id) "
                   " ORDER BY i.ord DESC, i.id DESC LIMIT 1), "
                   "(SELECT i.id FROM items i WHERE i.tier = x.tier AND (i.ord, i.id) > (x.ord, x.id) "
                   " ORDER BY i.ord, i.id LIMIT 1) FROM m JOIN items x ON x.id = m.id" % ",".join("(?)" for _ in chunk))
            pairs = self.conn.execute(sql, chunk).fetchall()
            others = {v for _i, p, n in pairs for v in (p, n) if v is not None}
            info = {}
            for sub in _chunks(list(others), 500):
                for r in self.conn.execute(f"SELECT id, piece_id, work_id FROM items WHERE id IN "
                                           f"({','.join('?' * len(sub))})", sub):
                    info[r[0]] = r
            for item_id, p, n in pairs:
                out[item_id] = (info.get(p, none), info.get(n, none))
        return out

    def _new_piece(self, like=None, title=None):
        base = self.conn.execute("SELECT title, kind FROM pieces WHERE id = ?", (like,)).fetchone() if like else None
        return self.conn.execute("INSERT INTO pieces (title, kind, created_at) VALUES (?, ?, ?)",
                                 (base[0] if base else title, base[1] if base else "run", _now())).lastrowid

    def _fix_pieces(self, cmd):
        """Pieces drawn by id (05 §5.2), for what the command touched: a whole piece moved keeps its id (4); items
        moved out of a piece, and new items, join the piece of their own work they land inside or beside, else start
        one (3, 4); a piece something foreign landed inside splits there — its first run keeps the id (5); an undo
        puts items back in the pieces they came from (`cmd.hints`); an emptied piece row is deleted (7)."""
        conn = self.conn
        touched = cmd.moved | cmd.reworked
        info = {}
        for chunk in _chunks(list(touched), 500):
            for r in conn.execute(f"SELECT id, tier, piece_id, work_id FROM items WHERE id IN "
                                  f"({','.join('?' * len(chunk))})", chunk):
                info[r[0]] = list(r[1:])
        if info:
            known = {v[1] for v in info.values() if v[1] is not None} | {h for h in cmd.hints.values() if h is not None}
            pieces = {r[0] for chunk in _chunks(sorted(known), 500)
                      for r in conn.execute(f"SELECT id FROM pieces WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
            whole = {}
            for p in {v[1] for v in info.values() if v[1] is not None}:
                whole[p] = all(r[0] in info for r in conn.execute("SELECT id FROM items WHERE piece_id = ?", (p,)))
            sets, fresh = [], set()
            for item_id, v in info.items():
                old = v[1]
                if item_id in cmd.hints:
                    want = cmd.hints[item_id] if cmd.hints[item_id] in pieces else None
                elif old is not None and whole.get(old):
                    want = old
                else:
                    want = None
                if want != old:
                    sets.append((want, item_id))
                    cmd.repieced.append((item_id, old, want))
                    if old is not None:
                        cmd.pieces_left.add(old)
                v[1] = want
                if want is None:
                    fresh.add(item_id)
            if sets:
                self._set_pieces(cmd, sets)
            view = self._order_view({v[0] for v in info.values()}) if len(info) > self.BIG_SETTLE else None
            # the neighbours that matter: every new item's, and the ends of every piece the command placed whole
            ends = {item_id: info[item_id][0] for item_id in fresh}
            by_piece = {}
            for item_id, v in info.items():
                if v[1] is not None:
                    by_piece.setdefault(v[1], []).append(item_id)
            for ids in by_piece.values():
                if view is not None and all(info[i][0] in view for i in ids):
                    at = lambda i: (info[i][0], view[info[i][0]][0][i][0])      # noqa: E731
                    ordered = sorted(ids, key=at)
                    for n, i in enumerate(ordered):                 # the ends of each run the piece makes
                        if n == 0 or at(ordered[n - 1]) != (at(i)[0], at(i)[1] - 1):
                            ends[i] = info[i][0]
                        if n == len(ordered) - 1 or at(ordered[n + 1]) != (at(i)[0], at(i)[1] + 1):
                            ends[i] = info[i][0]
                else:
                    for i in ids:
                        ends[i] = info[i][0]
            near = self._near(ends, view)
            # a whole piece put back beside a piece of its own title becomes part of it (05 §5.2 #4: a season put
            # back together); an undo's pieces stay as they were
            for p, ids in by_piece.items():
                if any(i in cmd.hints for i in ids) or not whole.get(p):
                    continue
                firsts = [i for i in ids if i in near and near[i][0][1] != p]
                lasts = [i for i in ids if i in near and near[i][1][1] != p]
                if len(firsts) != 1 or len(lasts) != 1:
                    continue                                    # not one run: the split below decides
                work = info[ids[0]][2]
                before, after = near[firsts[0]][0], near[lasts[0]][1]
                into = before[1] if before[1] is not None and before[2] == work else \
                    after[1] if after[1] is not None and after[2] == work else None
                if into is None or into == p:
                    continue
                self._set_pieces(cmd, [(into, i) for i in ids])
                cmd.repieced += [(i, p, into) for i in ids]
                cmd.pieces_left.add(p)
                for i in ids:
                    info[i][1] = into
            # runs of new items: side by side in one tier, one work
            runs, in_run = [], set()
            for start in fresh:
                prev = near[start][0][0]
                if prev in fresh and info[prev][2] == info[start][2]:
                    continue
                run, cur = [start], start
                while True:
                    nxt = near[cur][1][0]
                    if nxt in fresh and info[nxt][2] == info[cur][2] and nxt not in in_run:
                        run.append(nxt)
                        cur = nxt
                    else:
                        break
                in_run.update(run)
                runs.append(run)
            pending = []
            for run in runs:
                work = info[run[0]][2]
                before, after = near[run[0]][0], near[run[-1]][1]
                if before[1] is not None and before[1] == after[1] and before[2] == work and after[2] == work:
                    self._set_pieces(cmd, [(before[1], i) for i in run])
                    cmd.repieced += [(i, None, before[1]) for i in run]
                    for i in run:
                        info[i][1] = before[1]
                else:
                    pending.append(run)
            # the pieces the command touched: one run of one work in one tier each, the first run keeping the id
            affected = {v[1] for v in info.values() if v[1] is not None}
            for before, after in near.values():
                affected.update(p for p in (before[1], after[1]) if p is not None)
            placed = set(info)
            for p in sorted(affected):
                self._split_runs(p, placed, cmd, view)
            for run in pending:
                work = info[run[0]][2]
                before = self._side(run[0], -1)
                after = self._side(run[-1], 1)
                if before is not None and before[2] == work and before[1] is not None:
                    piece = before[1]
                elif after is not None and after[2] == work and after[1] is not None:
                    piece = after[1]
                else:
                    title = conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()
                    piece = self._new_piece(title=title[0] if title else None)
                self._set_pieces(cmd, [(piece, i) for i in run])
                cmd.repieced += [(i, None, piece) for i in run]
        if cmd.pieces_left:
            for chunk in _chunks(sorted(cmd.pieces_left), 500):
                conn.execute(f"DELETE FROM pieces WHERE id IN ({','.join('?' * len(chunk))}) AND NOT EXISTS "
                             "(SELECT 1 FROM items WHERE items.piece_id = pieces.id)", chunk)

    def _set_pieces(self, cmd, sets):
        """[(piece, item_id)] written with the command's `feed_in` in the same row write."""
        self.conn.executemany("UPDATE items SET piece_id = ?, feed_in = ? WHERE id = ?",
                              [(p, cmd.version, i) for p, i in sets])
        cmd.fed_inline.update(i for _p, i in sets)

    def _side(self, item_id, direction):
        """(id, piece_id, work_id) of the row just before (-1) or after (1) an item in its tier, or None."""
        row = self.conn.execute("SELECT tier, ord FROM items WHERE id = ?", (item_id,)).fetchone()
        if direction < 0:
            sql = ("SELECT id, piece_id, work_id FROM items WHERE tier = ? AND (ord, id) < (?, ?) "
                   "ORDER BY ord DESC, id DESC LIMIT 1")
        else:
            sql = "SELECT id, piece_id, work_id FROM items WHERE tier = ? AND (ord, id) > (?, ?) ORDER BY ord, id LIMIT 1"
        return self.conn.execute(sql, (row[0], row[1], item_id)).fetchone()

    def _split_runs(self, piece, placed, cmd, view=None):
        """Make `piece` one run again (05 §5.2 rules 1, 5): its members in (tier, ord, id), cut wherever the tier or
        the work changes or another row stands between two of them; the first run holding a member the command didn't
        place keeps the id (else the first run), each other run becomes a piece of its own."""
        conn = self.conn
        members = conn.execute("SELECT id, tier, ord, work_id FROM items WHERE piece_id = ? ORDER BY tier, ord, id",
                               (piece,)).fetchall()
        if len(members) <= 1:
            return

        first, last = members[0], members[-1]
        span = None                # {id: position} of the rows from its first member to its last, read at once
        if view is None and first[1] == last[1]:
            rows = conn.execute("SELECT id FROM items WHERE tier = ? AND (ord, id) >= (?, ?) AND (ord, id) <= (?, ?) "
                                "ORDER BY ord, id LIMIT ?", (first[1], first[2], first[0], last[2], last[0],
                                                             4 * len(members) + 64)).fetchall()
            if rows and rows[-1][0] == last[0]:                # a piece scattered wider than that: one look per gap
                if len(rows) == len(members) and len({m[3] for m in members}) == 1:
                    return
                span = {r[0]: n for n, r in enumerate(rows)}

        def gap(a, b):
            if a[1] != b[1] or a[3] != b[3]:
                return True
            if span is not None:
                return span[b[0]] != span[a[0]] + 1
            if view is not None and a[1] in view:
                index = view[a[1]][0]
                return index[b[0]][0] != index[a[0]][0] + 1
            return conn.execute("SELECT 1 FROM items WHERE tier = ? AND (ord, id) > (?, ?) AND (ord, id) < (?, ?) "
                                "LIMIT 1", (a[1], a[2], a[0], b[2], b[0])).fetchone() is not None
        runs, run = [], [members[0]]
        for a, b in zip(members, members[1:]):
            if gap(a, b):
                runs.append(run)
                run = [b]
            else:
                run.append(b)
        runs.append(run)
        if len(runs) == 1:
            return
        keep = next((r for r in runs if any(m[0] not in placed for m in r)), runs[0])
        for r in runs:
            if r is keep:
                continue
            new = self._new_piece(like=piece)
            ids = [m[0] for m in r]
            self._set_pieces(cmd, [(new, i) for i in ids])
            cmd.repieced += [(i, piece, new) for i in ids]

    def _write_feed(self, cmd):
        """`feed_in` = this version for every row the command changed that isn't written yet; tombstones for rows that
        left, none for rows that came back (04 §4.1)."""
        rest = sorted(cmd.fed - cmd.fed_inline)
        for chunk in _chunks(rest, 500):
            self.conn.execute(f"UPDATE items SET feed_in = ? WHERE id IN ({','.join('?' * len(chunk))})",
                              [cmd.version] + chunk)
        for chunk in _chunks(sorted(cmd.fed_works), 500):
            self.conn.execute(f"UPDATE works SET feed_in = ? WHERE id IN ({','.join('?' * len(chunk))})",
                              [cmd.version] + chunk)
        if cmd.gone:
            at = _now()
            self.conn.executemany("INSERT OR REPLACE INTO gone (kind, id, feed_in, at) VALUES (?, ?, ?, ?)",
                                  [(k, i, cmd.version, at) for k, i in cmd.gone])
        if cmd.back:
            self.conn.executemany("DELETE FROM gone WHERE kind = 'item' AND id = ?", [(i,) for i in cmd.back])

    # --- pieces (S5) ---------------------------------------------------------------------------- #

    def _piece_items(self, piece_id):
        return self.conn.execute("SELECT id, tier, ord, changed_in FROM items WHERE piece_id = ? "
                                 "ORDER BY tier, ord, id", (piece_id,)).fetchall()

    def split(self, piece_id, at_item_id):
        """A new piece of the items from `at_item_id` to the piece's end. Nothing moves."""
        with self._command("split") as cmd:
            items = self._piece_items(piece_id)
            at = [r[0] for r in items].index(at_item_id) if at_item_id in [r[0] for r in items] else -1
            if at <= 0:
                return None
            old = self.conn.execute("SELECT title, kind FROM pieces WHERE id = ?", (piece_id,)).fetchone()
            cur = self.conn.execute("INSERT INTO pieces (title, kind, created_at) VALUES (?, ?, ?)",
                                    (old[0], old[1], _now()))
            new_piece = cur.lastrowid
            moved = items[at:]
            self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?",
                                  [(new_piece, cmd.version, r[0]) for r in moved])
            cmd.feed(r[0] for r in moved)
            change = self._change(cmd, "split")
            change.pieces = {"items": [(r[0], piece_id, r[3]) for r in moved], "created": [new_piece],
                             "deleted": []}
            cmd.touch()
            return change

    def join(self, piece_ids):
        """One piece of several pieces of one title (05 §5.2 #6): the other pieces' items move to just after the first
        piece's last item — "a join across sections lands where the target part is" (W1.2 §8.2), across tiers or
        with other items between — and become one piece; one command, one undo. A join of two titles' pieces is
        refused: make them one title first (`merge_works`)."""
        piece_ids = list(dict.fromkeys(piece_ids))
        if len(piece_ids) < 2:
            return None
        with self._command("join") as cmd:
            members = {}
            for p in piece_ids:
                rows = self.conn.execute("SELECT id, tier, ord, changed_in, work_id FROM items WHERE piece_id = ?",
                                         (p,)).fetchall()
                members[p] = sorted(rows, key=lambda r: (TIERS[r[1]][3], r[2], r[0]))
            target = piece_ids[0]
            if not members[target]:
                raise ValueError("the piece to join onto is gone")
            if len({r[4] for p in piece_ids for r in members[p]}) > 1:
                raise ValueError("these are different titles — make them one title first")
            others = [p for p in piece_ids[1:] if members[p]]
            moving = [r for p in others for r in members[p]]
            if not moving:
                return None
            last = members[target][-1]
            tier = last[1]
            nxt = self._beyond(tier, (last[0], last[2]), set(), 1, len(moving))
            change = self._change(cmd, "join")
            if [r[0] for r in nxt] != [r[0] for r in moving] or any(r[1] != tier for r in moving):
                rows = self._rows([r[0] for r in moving])
                self._before(change, list(rows.values()))
                self._put(tier, [r[0] for r in moving], ("after", last[0]), cmd.version)
                cmd.touch({r[1] for r in moving} | {tier})
            self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?",
                                  [(target, cmd.version, r[0]) for r in moving])
            for r in moving:
                cmd.hints[r[0]] = target
            cmd.feed(r[0] for r in moving)
            gone = [self.conn.execute("SELECT id, title, kind, created_at FROM pieces WHERE id = ?", (p,)).fetchone()
                    for p in others]
            self.conn.executemany("DELETE FROM pieces WHERE id = ?", [(p,) for p in others])
            change.pieces = {"items": [(r[0], p, r[3]) for p in others for r in members[p]], "created": [],
                             "deleted": [tuple(g) for g in gone if g]}
            cmd.touch()
            return change

    def _undo_join(self, cmd, change):
        """A join that moved items: the pieces it emptied come back, the moved items go back where they stood and into
        the pieces they came from (`_replace`'s hints), the others take their pieces back by `changed_in`."""
        ids = [t[0] for t in change.pieces["items"]]
        rows = self._rows(ids)
        if not any(i in rows and rows[i][3] == change.version for i in ids):
            return self._change(cmd, "undo"), ids               # all changed since: nothing to put back
        for piece in change.pieces["deleted"]:
            self.conn.execute("INSERT OR IGNORE INTO pieces (id, title, kind, created_at) VALUES (?, ?, ?, ?)", piece)
            cmd.pieces_left.add(piece[0])                       # gone again at the end if nothing came back to it
        cmd.touch()
        moved = {it["id"] for it in change.items}
        out, skipped = self._replace(cmd, change) if change.items else (self._change(cmd, "undo"), [])
        rest = dict(change.pieces, items=[t for t in change.pieces["items"] if t[0] not in moved], deleted=[])
        holder = Change(change.kind, change.epoch, change.version)
        holder.pieces = rest
        _o, more = self._undo_pieces(cmd, holder)
        return out, list(skipped) + list(more)

    # --- status writes (§6.6): state_version only; undo by the value check ----------------------- #

    def _status(self, kind, ids, column, value, pins=False):
        with self._command(kind) as cmd:
            rows = self.conn.execute(f"SELECT id, {column} FROM items WHERE id IN ({','.join('?' * len(ids))})",
                                     list(ids)).fetchall()
            changes = [(i, old) for i, old in rows if old != value]
            if not changes:
                return None
            self.conn.executemany(f"UPDATE items SET {column} = ? WHERE id = ?", [(value, i) for i, _ in changes])
            cmd.feed(i for i, _ in changes)
            change = self._change(cmd, kind)
            change.status = [(i, column, old, value) for i, old in changes]
            cmd.touch(pins=pins)
            return change

    # --- the library's options (L2.2 04 §4.2): the Soon line, the mine line, New arrivals ------------ #

    def set_soon_line(self, n):
        """The line after `n` Current rows (the dragged line, the settings page; 05 §5.1): the rows it crosses change
        tier in the same transaction (the tiers follow the line). Undo puts the old `n` back, and the rows with it."""
        n = int(n)
        if n < 0:
            raise ValueError("the Soon line can't sit above the top")
        with self._command("set_soon_line") as cmd:
            old = self._soon_line()
            if old == n:
                return None
            self._set_meta({"soon_line": n})
            cmd.line_set = True
            cmd.touch()
            change = self._change(cmd, "set_soon_line")
            change.options = [("soon_line", old, n)]
            return change

    def set_library_options(self, mine_line=None, arrivals_on=None):
        """The user's two library options (Mado's gap 3): how many of Current's top rows Connect mines, and whether
        drops wait in New arrivals (D30). Undo by the value check."""
        wanted = {}
        if mine_line is not None:
            if int(mine_line) < 0:
                raise ValueError("the mine line can't be negative")
            wanted["mine_line"] = int(mine_line)
        if arrivals_on is not None:
            wanted["arrivals_on"] = 1 if arrivals_on else 0
        if not wanted:
            return None
        with self._command("set_library_options") as cmd:
            meta = self._meta()
            options = [(k, meta.get(k), v) for k, v in wanted.items() if meta.get(k) != v]
            if not options:
                return None
            self._set_meta({k: v for k, _o, v in options})
            if "mine_line" in wanted:
                cmd.mine_n = wanted["mine_line"]               # the log's crossings read the new line
            cmd.touch()
            change = self._change(cmd, "set_library_options")
            change.options = options
            return change

    def _undo_options(self, cmd, change):
        """The value check (§6.11): each option goes back only where it still holds what the change set."""
        out = self._change(cmd, "undo")
        meta = self._meta()
        back = {k: old for k, old, new in change.options if meta.get(k) == new}
        skipped = [k for k, _o, new in change.options if meta.get(k) != new]
        for key, old in back.items():
            if old is None:
                self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
            else:
                self._set_meta({key: old})
        if back:
            cmd.line_set = "soon_line" in back
            if "mine_line" in back:
                cmd.mine_n = int(back["mine_line"])
            cmd.touch()
            out.options = [(k, change_new, back[k]) for k, _o, change_new in change.options if k in back]
        return out, skipped

    # --- per-source placing (05 §5.12) and place (04 §4.2) ------------------------------------------- #

    def _apply_rule(self, item_id, record, rules):
        """Place an item waiting in New arrivals by its source's rule, inside the caller's command -> the target it
        was placed by, or None (it waits). The placement is the user's own (D30): logged as the source's, explicit."""
        found = _rule_for(record, rules)
        if found is None:
            return None
        source, target = found
        return target if self._place_one(item_id, target, record, source, 1) else None

    def _place_one(self, item_id, where, record, by, explicit):
        if where == "finished":
            return self.finish([item_id], by=by, explicit=explicit) is not None
        if where == "after-show":
            spot = self._after_show(item_id, record)
            if spot is None:
                return False
            tier, before_id, after_id = spot
            return self.move([item_id], tier, before_id=before_id, after_id=after_id, by=by,
                             explicit=explicit) is not None
        tier = {"top": "now", "now": "now", "soon": "soon", "goal": "goal", "later": "goal"}.get(where)
        if tier is None:
            raise ValueError(f"unknown place {where!r}")
        return self.move([item_id], tier, by=by, explicit=explicit) is not None

    def place(self, item_ids, where, by="user", explicit=None):
        """`place --where` (04 §4.2): `soon` — the first slot below the Soon line; `after-show` — after the title's
        episode before it in Current (before its next one when only later ones are there), a title only in Finished
        or 6+ Months goes to the top of Current (Q4-9), a title with nothing anywhere stays where it is; `top`, `goal`,
        `finished` — the rule targets. One command; undone as a move. Returns the change, or None."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return None
        explicit = int(by == "user") if explicit is None else explicit
        with self._command("place", by) as cmd:
            record = None
            if where == "after-show":
                row = self.conn.execute("SELECT pairing FROM pairings WHERE item_id = ? ORDER BY paired_at DESC "
                                        "LIMIT 1", (ids[0],)).fetchone()
                record = json.loads(row[0]) if row else None
                spot = self._after_show(ids[0], record, excl=set(ids))
                if spot is None:
                    return None
                tier, before_id, after_id = spot
                return self.move(ids, tier, before_id=before_id, after_id=after_id, by=by, explicit=explicit)
            if where == "finished":
                return self.finish(ids, by=by, explicit=explicit)
            tier = {"top": "now", "now": "now", "soon": "soon", "goal": "goal", "later": "goal"}.get(where)
            if tier is None:
                raise ValueError(f"unknown place {where!r}")
            return self.move(ids, tier, by=by, explicit=explicit)

    def _after_show(self, item_id, record, excl=()):
        """Where `after-show` puts an item (HC-N6, ✅ P2.1-2, Q4-9): (tier, before_id, after_id), or None (it stays).
        Its title's other items, by the episode numbers their records name (the same season); without numbers, after
        the title's last item in Current."""
        work = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()
        if work is None or work[0] is None:
            return None
        mine = _episode(record)
        others = [r for r in self.conn.execute("SELECT id, tier, ord FROM items WHERE work_id = ? AND id != ?",
                                               (work[0], item_id)) if r[0] not in excl]
        if not others:
            return None
        episodes = {}
        for other, text in self.conn.execute("SELECT item_id, pairing FROM pairings WHERE item_id IN "
                                             "(SELECT id FROM items WHERE work_id = ?)", (work[0],)):
            try:
                ep = _episode(json.loads(text))
            except ValueError:
                continue
            if ep is not None and (mine is None or ep[0] == mine[0]):
                episodes[other] = ep[1]
        current = [r for r in others if r[1] in CURRENT]
        if not current:
            if all(r[1] in ("graduated", "goal") for r in others):
                return ("now", None, None)                      # Q4-9: a finished title's new episode leads Current
            return None
        order = lambda r: (TIERS[r[1]][3], r[2], r[0])           # noqa: E731
        if mine is not None and all(r[0] in episodes for r in current):
            earlier = [r for r in current if episodes[r[0]] < mine[1]]
            if earlier:
                prev = max(earlier, key=lambda r: (episodes[r[0]], order(r)))
                return (prev[1], None, prev[0])
            nxt = min(current, key=lambda r: (episodes[r[0]], order(r)))
            return (nxt[1], nxt[0], None)
        last = max(current, key=order)
        return (last[1], None, last[0])

    # --- Finished (05 §5.7–5.8): never a known word, never a card deleted ------------------------------ #

    def finish(self, item_ids, keep_cards=True, by="user", explicit=None):
        """To Finished (the `graduated` tier), dated now (04 §4.2, D23). `keep_cards=False` — the toast's *Take its new
        cards out* (D14) — leaves the title's cards out of the learning order and ends its pin (G2.2-8: the later click
        wins); Anki's side and its record in `anki_changes` are the re-plan's. Writes no known word and deletes no card:
        nothing here touches KnownWord.json, the token store or Anki (Q2-5, Q2-6). A missing item finishes like any.
        Undo puts the rows, their date and their cards' place back."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return None
        with self._command("finish", by) as cmd:
            change = self.set_tier(ids, "graduated", by=by, explicit=explicit)
            status = []
            if not keep_cards:
                marks = ",".join("?" * len(ids))
                for item_id, order, pinned in self.conn.execute(
                        f"SELECT id, in_learning_order, pinned FROM items WHERE id IN ({marks})", ids).fetchall():
                    if order != 0:
                        status.append((item_id, "in_learning_order", order, 0))
                    if pinned is not None:
                        status.append((item_id, "pinned", pinned, None))
                for item_id, column, _old, new in status:
                    self.conn.execute(f"UPDATE items SET {column} = ? WHERE id = ?", (new, item_id))
                cmd.feed(i for i, _c, _o, _n in status)
                if status:
                    cmd.touch(pins=any(c == "pinned" for _i, c, _o, _n in status))
            if change is None and not status:
                return None
            if change is None:
                change = self._change(cmd, "finish")
            change.kind = "finish"
            change.status = status
            return change

    def _undo_finish(self, cmd, change):
        out, skipped = self._replace(cmd, change) if change.items else (self._change(cmd, "undo"), [])
        if change.status:
            _o, more = self._undo_status(cmd, change)
            skipped = list(skipped) + list(more)
        return out, skipped

    def ask_mining(self, item_ids, asked=True):
        """*Mine it too* (the finishing toast, W1.2 §8.2): when the user asked Connect to mine a Finished item; Connect
        reads it and its receipt answers it. Undo by the value check."""
        return self._status("ask_mining", list(item_ids), "mine_asked", _now() if asked else None)

    def import_finished(self, paths):
        """The Finished importer's command (05 §5.8), after its copying job: each file — one the job copied into
        `Graduated/`, or one already in the library — lands in Finished dated *Earlier* (`graduated_at` NULL), its work
        found or made by its folder, with a piece; never counted (Finished isn't analysed), never a known word. One
        command; undone as an Add (the copies to the trash by the caller's file code)."""
        rels = []
        for path in paths:
            rel = library_rel(self.data_dir, path)
            if rel is None:
                raise NotInLibrary(f"not in the library: {path}")
            rels.append(rel)
        prepared = self._prepare(rels, None, "Finished Import")
        with self._command("import_finished") as cmd:
            change = self._change(cmd, "import_finished")
            new, moving, seen = [], [], set()
            for item in prepared:
                if item[2] in seen:
                    continue
                seen.add(item[2])
                row = self.conn.execute("SELECT id, tier FROM items WHERE rel_key = ?", (item[2],)).fetchone()
                if row is None:
                    new.append(item)
                elif row[1] != "graduated":
                    moving.append(row[0])
            if not new and not moving:
                return None
            if moving:
                rows = self._rows(moving)
                self._before(change, list(rows.values()))
                self._put("graduated", moving, ("end",), cmd.version)
                self.conn.executemany("UPDATE items SET graduated_at = NULL WHERE id = ?", [(i,) for i in moving])
                cmd.touch({r[1] for r in rows.values()})
            if new:
                change.added = self._add_rows([it + ("graduated",) for it in new], cmd.version)
                self._put("graduated", change.added, ("end",), cmd.version)
            cmd.touch({"graduated"})
            for item_id in moving + change.added:
                cmd.event(item_id, "finished", 1)
            return change

    def _undo_import(self, cmd, change, trashed_paths):
        out, skipped = self._replace(cmd, change) if change.items else (self._change(cmd, "undo"), [])
        if change.added:
            rows = self._rows(change.added)
            ok = [i for i in change.added if i in rows and rows[i][3] == change.version]
            gone = [i for i in change.added if i not in ok]
            if trashed_paths and any(i in gone for i in trashed_paths):
                raise StoreConflict("an item changed since its file was moved; nothing was undone")
            if ok:
                self._remove_as(ok, trashed_paths, 1)
            skipped = list(skipped) + list(gone)
        return out, skipped

    # --- per title (05 §5.4–5.5): media type and cover ---------------------------------------------- #

    def set_media_type(self, work_ids, media_type):
        """*What is it?* for the selected titles (05 §5.4): the user's, never overwritten by hato, a sync or a merge;
        None clears it back to the guess. Undo by the value check."""
        if media_type is not None and media_type not in MEDIA_TYPES:
            raise ValueError(f"unknown media type {media_type!r}")
        with self._command("set_media_type") as cmd:
            change = self._change(cmd, "set_media_type")
            by = "user" if media_type is not None else None
            done = [self._set_work_fields(cmd, change, w, {"media_type": media_type, "media_type_by": by})
                    for w in dict.fromkeys(work_ids)]
            return change if any(done) else None

    def media_type(self, work_id):
        """(type, by) a title shows (05 §5.4): its stored type ('user' or 'hato'), else the guess with by None — or
        (None, None), which the window shows as *Video* (G2.2-5)."""
        row = self.conn.execute("SELECT media_type, media_type_by, anilist_id, tmdb_id FROM works WHERE id = ?",
                                (work_id,)).fetchone()
        if row is None:
            return None, None
        if row[0] is not None:
            return row[0], row[1]
        counts = {}
        for source, rel in self.conn.execute("SELECT source_type, rel_path FROM items WHERE work_id = ?", (work_id,)):
            kind = infer_source_type(rel or "", declared=source)      # no type stamped (Reset): its extension (§12.8)
            counts[kind] = counts.get(kind, 0) + 1
        return media_type_guess(counts, row[2], row[3]), None

    def set_cover(self, work_id, source, ref=None, path=None, locked=False):
        """A title's cover record (05 §5.5). The fetch (the window's services, `locked=False`) is refused — nothing
        written, no error — when the user's choice is locked; the user's *Change cover…* / *Use a generated cover*
        (`locked=True`) always writes. `path`: 'cache:<name>' (a fetched image, re-fetchable) or 'user:<name>' (the
        user's, in User Files/<lang>/covers/, kept by the window with a dated backup on replace). Undo by the value
        check. Returns the change, or None (refused, or nothing new)."""
        if source not in COVER_SOURCES:
            raise ValueError(f"unknown cover source {source!r}")
        if path is not None and not str(path).startswith(("cache:", "user:")):
            raise ValueError("a cover's path is 'cache:<name>' or 'user:<name>'")
        with self._command("set_cover") as cmd:
            row = self.conn.execute("SELECT cover_locked FROM works WHERE id = ?", (work_id,)).fetchone()
            if row is None or (row[0] and not locked):
                return None
            change = self._change(cmd, "set_cover")
            fetched = _now() if not locked and path and str(path).startswith("cache:") else None
            done = self._set_work_fields(cmd, change, work_id, {
                "cover_source": source, "cover_ref": ref, "cover_path": path, "cover_fetched_at": fetched,
                "cover_locked": 1 if locked else 0})
            return change if done else None

    def forget_downloaded_covers(self):
        """*Remove downloaded covers* (05 §5.5): the fetched, unlocked covers' paths cleared (the window empties the
        cache folder); a locked or user-picked cover is untouched (user data). No undo: the cache is re-fetchable.
        Returns the works cleared."""
        with self._command("forget_downloaded_covers") as cmd:
            ids = [r[0] for r in self.conn.execute("SELECT id FROM works WHERE cover_locked = 0 AND cover_path LIKE "
                                                   "'cache:%'")]
            if not ids:
                return []
            self.conn.executemany("UPDATE works SET cover_path = NULL, cover_fetched_at = NULL WHERE id = ?",
                                  [(w,) for w in ids])
            cmd.fed_works.update(ids)
            cmd.touch()
            return ids

    # --- the pin's readers (05 §5.6) and Connect's made words (04 §4.3 #7) ---------------------------- #

    def pinned(self):
        """*Study its cards first* (05 §5.6): `[Pin(item_id, rel_path, tier, pinned_at)]` for pinned items still in
        the library, any tier (Finished too), the oldest pin first, in one read transaction — the re-plan's input
        (E3.1, on its worker: `[(p.item_id, p.pinned_at) for p in store.pinned()]`). A trash row's pin acts only after
        Put back."""
        with self._reading():
            rows = self.conn.execute("SELECT id, rel_path, tier, pinned FROM items WHERE pinned IS NOT NULL "
                                     "ORDER BY pinned, id").fetchall()
        return [Pin(*r) for r in rows]

    def cards_of(self, item_ids):
        """{item_id: [note ids]} the store knows for each item (05 §5.6): its Anki links and the notes Connect made
        for it (`made_words`), sorted; Haya's match by a card's source field adds the cards mined before Connect."""
        ids = list(dict.fromkeys(item_ids))
        out = {i: set() for i in ids}
        with self._reading():
            for chunk in _chunks(ids, 500):
                marks = ",".join("?" * len(chunk))
                for item_id, note in self.conn.execute(f"SELECT item_id, note_id FROM anki_links WHERE item_id IN "
                                                       f"({marks})", chunk):
                    out[item_id].add(note)
                if self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'made_words'").fetchone():
                    for item_id, notes in self.conn.execute(f"SELECT item_id, note_ids FROM made_words WHERE item_id "
                                                            f"IN ({marks})", chunk):
                        try:
                            out[item_id].update(int(n) for n in json.loads(notes))
                        except (ValueError, TypeError):
                            continue
                if self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'made_lines'").fetchone():
                    for item_id, note in self.conn.execute(f"SELECT item_id, note_id FROM made_lines WHERE item_id IN "
                                                           f"({marks})", chunk):
                        out[item_id].add(note)
        return {i: sorted(v) for i, v in out.items()}

    def record_made(self, item_id, made, batch=None):
        """Connect's record of the words it made cards for (N15, 04 §4.3 #7): [(word, [note ids])] for an item, one
        short write per batch (role `connect`); a word already recorded for the item keeps its first record — it is
        never made again automatically, even when its notes were deleted (G1.3-4). An item removed meanwhile is
        recorded too (Put back finds it). A status write: `state_version` only. Returns the words recorded."""
        rows = [(item_id, str(w), _dumps([int(n) for n in notes]), _now(), batch) for w, notes in made if w]
        if not rows:
            return []
        with self._command("record_made", "connect") as cmd:
            for sql in ADDED_TABLES_SQL:
                self.conn.execute(sql)
            have = {r[0] for r in self.conn.execute("SELECT word FROM made_words WHERE item_id = ?", (item_id,))}
            fresh = [r for r in rows if r[1] not in have]
            if not fresh:
                return []
            self.conn.executemany("INSERT INTO made_words (item_id, word, note_ids, made_at, batch) "
                                  "VALUES (?, ?, ?, ?, ?)", fresh)
            cmd.touch()
            return [r[1] for r in fresh]

    def record_lines(self, item_id, lines):
        """Each card's line (✅ D1, 2026-10-07): [(note_id, start_ms, end_ms, text)] for the notes Connect made from an
        item's lines — the start and end as Connect's line reader (`app/cues.py`) gives them; of the text only its
        fingerprint is kept (`line_fingerprint`), so the line is found again after a re-sync shifts its timings, and no
        sentence or media is stored. A note recorded again takes its newer line. Like `record_made` (role `connect`, a
        status write: `state_version` only; an item removed meanwhile is recorded too). Returns the note ids recorded."""
        rows = []
        for note_id, start_ms, end_ms, text in lines:
            if note_id is None:
                continue
            rows.append((int(note_id), item_id, None if start_ms is None else int(start_ms),
                         None if end_ms is None else int(end_ms), line_fingerprint(text) if text else None, _now()))
        if not rows:
            return []
        with self._command("record_lines", "connect") as cmd:
            for sql in ADDED_TABLES_SQL:
                self.conn.execute(sql)
            self.conn.executemany("INSERT OR REPLACE INTO made_lines (note_id, item_id, start_ms, end_ms, line_fp, "
                                  "made_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
            cmd.touch()
            return [r[0] for r in rows]

    def card_lines(self, item_ids):
        """{item_id: [(note_id, start_ms, end_ms, line_fp)]} in the line's order — what 3.1's journey plays (D1)."""
        ids = list(dict.fromkeys(item_ids))
        out = {i: [] for i in ids}
        with self._reading():
            if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'made_lines'").fetchone():
                return out
            for chunk in _chunks(ids, 500):
                for item_id, *rest in self.conn.execute(
                        f"SELECT item_id, note_id, start_ms, end_ms, line_fp FROM made_lines WHERE item_id IN "
                        f"({','.join('?' * len(chunk))}) ORDER BY item_id, start_ms, note_id", chunk):
                    out[item_id].append(tuple(rest))
        return out

    def made(self, item_id):
        """{word: [note ids]} Connect made cards for, for one item (N15)."""
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'made_words'").fetchone():
            return {}
        return {w: json.loads(n) for w, n in self.conn.execute("SELECT word, note_ids FROM made_words WHERE item_id = ?",
                                                               (item_id,))}

    def record_anki_changes(self, changes):
        """The re-plan's record of the cards it changed for an item (05 §5.7, D14): [(item_id, action, [note ids],
        before, after)], one short write; *Put back* restores exactly these, never more. Returns the record ids."""
        rows = [(item_id, action, _dumps([int(n) for n in notes]), _dumps(before), _dumps(after), _now())
                for item_id, action, notes, before, after in changes]
        if not rows:
            return []
        with self._command("record_anki_changes", "connect") as cmd:
            first = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM anki_changes").fetchone()[0] + 1
            self.conn.executemany("INSERT INTO anki_changes (item_id, action, notes, before, after, at) "
                                  "VALUES (?, ?, ?, ?, ?, ?)", rows)
            cmd.touch()
            return list(range(first, first + len(rows)))

    def anki_changes_of(self, item_ids):
        """The open (not yet reverted) card changes recorded for these items, oldest first: what *Put back* restores."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return []
        cur = self.conn.execute(f"SELECT id, item_id, action, notes, before, after, at FROM anki_changes WHERE "
                                f"reverted_at IS NULL AND item_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)
        out = []
        for r in cur.fetchall():
            row = dict(zip(("id", "item_id", "action", "notes", "before", "after", "at"), r))
            for key in ("notes", "before", "after"):
                try:
                    row[key] = json.loads(row[key]) if row[key] is not None else None
                except ValueError:
                    pass
            out.append(row)
        return out

    def mark_anki_reverted(self, change_ids):
        """The re-plan put those cards back (Put back): their records are closed, kept. Returns how many."""
        ids = list(dict.fromkeys(change_ids))
        if not ids:
            return 0
        with self._command("mark_anki_reverted", "connect") as cmd:
            n = self.conn.execute(f"UPDATE anki_changes SET reverted_at = ? WHERE reverted_at IS NULL AND id IN "
                                  f"({','.join('?' * len(ids))})", [_now()] + ids).rowcount
            if n:
                cmd.touch()
            return n

    # --- moved files followed (9a, 05 §5.9) and gone files' text (9b, 05 §5.10) ----------------------- #

    def rename_asks(self):
        """9a's open questions for *Needs you* — *Is this the one from …?*: [{rel, size, mtime_ns, candidates}]."""
        return _rename_asks(self)

    def relink(self, item_id, path):
        """A missing item pointed at a file (9a's answer, the window's *Link a file*): the same id, tier, place,
        piece, work, ✓, pin, Anki links, pairing and made words, now at `path`; its open question goes. Undo points it
        back. Returns the change, or None (already there, or the item is gone)."""
        rel = library_rel(self.data_dir, path)
        if rel is None:
            raise NotInLibrary(f"not in the library: {path}")
        st = _stat(os.path.join(self.data_dir, rel))
        if st is None:
            raise ValueError(f"no file at {rel}")
        with self._command("relink") as cmd:
            row = self.conn.execute("SELECT rel_path, rel_key, size, mtime_ns, availability, tier FROM items "
                                    "WHERE id = ?", (item_id,)).fetchone()
            if row is None or row[1] == path_key(rel):
                return None
            holder = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (path_key(rel),)).fetchone()
            if holder is not None:
                raise StoreConflict(f"{rel} is in the library already")
            change = self._change(cmd, "relink")
            change.relink = {"id": item_id, "old": list(row[:5]), "new": rel}
            self._repoint(item_id, rel, st.st_size, st.st_mtime_ns)
            self._drop_ask(rel)
            cmd.touch({row[5]}, availability=row[4] != "available")
            return change

    def _tidy_asks(self):
        """9a's questions kept true (§12.8), in the settling step: a question goes once its file is an item
        (Add or hato's hand-off took it in as new), and once none of its candidates is a missing item any more; a
        candidate back, relinked or gone leaves its questions. Bookkeeping the copy carries."""
        asks = _rename_asks(self)
        kept = []
        for a in asks:
            if self.conn.execute("SELECT 1 FROM items WHERE rel_key = ?", (path_key(str(a.get("rel", ""))),)).fetchone():
                continue
            cands = [c for c in a.get("candidates") or [] if self.conn.execute(
                "SELECT 1 FROM items WHERE id = ? AND availability = 'missing'", (c,)).fetchone()]
            if cands:
                kept.append(dict(a, candidates=cands))
        if kept != asks:
            self._set_meta({"rename_asks": _dumps(kept), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})

    def _drop_ask(self, rel):
        asks = _rename_asks(self)
        kept = [a for a in asks if path_key(a.get("rel", "")) != path_key(rel)]
        if kept != asks:
            self._set_meta({"rename_asks": _dumps(kept), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})

    def _undo_relink(self, cmd, change):
        out = self._change(cmd, "undo")
        info = change.relink
        row = self.conn.execute("SELECT rel_path, tier FROM items WHERE id = ?", (info["id"],)).fetchone()
        if row is None or row[0] != info["new"]:
            return out, [info["id"]]
        old_rel, _key, size, mtime_ns, _availability = info["old"]
        if self.conn.execute("SELECT 1 FROM items WHERE rel_key = ? AND id != ?",
                             (path_key(old_rel), info["id"])).fetchone():
            return out, [info["id"]]                           # its old path is another item's now (§12.8)
        self._repoint(info["id"], old_rel, size, mtime_ns)
        if not os.path.exists(os.path.join(self.data_dir, _strip(old_rel))):
            self.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (info["id"],))
        cmd.touch({row[1]}, availability=True)
        return out, []

    def its_new(self, path):
        """9a's other answer, *It's new*: its question goes and the file joins the library as any new file does
        (§6.10 rule 3) — the items it was asked about stay missing. Returns the sync's summary."""
        rel = library_rel(self.data_dir, path)
        if rel is None:
            raise NotInLibrary(f"not in the library: {path}")
        with self._writing():
            self._drop_ask(rel)
        return self.sync_disk(folders=[_rel_dir(rel)] if _rel_dir(rel) else None)

    def text_lists(self):
        """9b (05 §5.10): (counted, kept) — the paths, relative to data/<lang>, whose text the token store keeps. Counted:
        the analysed tiers' items, a missing one too (it keeps counting until the user decides). Kept, never counted:
        Finished, New arrivals, and removed items whose sentences weren't forgotten (`trash.text_forgotten` 0). The token
        store (E2.2) takes these two lists in place of a run's one list: it keeps a kept file's text (in
        `kept_text_<lang>.db`, through any wipe) and sums only counted files. One read transaction."""
        with self._reading():
            counted = [r[0] for r in self.conn.execute(
                "SELECT rel_path FROM items WHERE tier IN ('now', 'soon', 'goal') ORDER BY tier, ord, id")]
            kept = [r[0] for r in self.conn.execute(
                "SELECT rel_path FROM items WHERE tier IN ('graduated', 'arrivals') ORDER BY tier, ord, id")]
            kept += [r[0] for r in self.conn.execute(
                "SELECT rel_path FROM trash WHERE restored_at IS NULL AND text_forgotten = 0 ORDER BY id")]
        have = {path_key(r) for r in counted}
        out, seen = [], set()
        for rel in kept:
            key = path_key(rel)
            if key not in have and key not in seen:
                seen.add(key)
                out.append(rel)
        return counted, out

    def text_elsewhere(self):
        """{rel_path: trashed_path} for the removed items in `text_lists`' kept list: where each one's file went
        (relative to data/<lang>), so the token store (E2.2) reads a removed file's text from the trash — one it never
        indexed, or one whose text it hasn't kept yet — before the trash's 30 days end. One read transaction."""
        with self._reading():
            return {r[0]: r[1] for r in self.conn.execute(
                "SELECT rel_path, trashed_path FROM trash WHERE restored_at IS NULL AND text_forgotten = 0 "
                "AND trashed_path IS NOT NULL ORDER BY id")}

    def text_forgotten(self):
        """The paths (relative to data/<lang>) of removed items whose sentences the user forgot (`forget_text`): the
        token store drops their rows and kept text (E2.2) — the only way kept text ever goes. One read transaction."""
        with self._reading():
            return [r[0] for r in self.conn.execute(
                "SELECT rel_path FROM trash WHERE restored_at IS NULL AND text_forgotten = 1 ORDER BY id")]

    def forget_text(self, item_ids):
        """*This file is junk — forget its sentences too* (G2.2-3, at Remove, off by default): the removed items'
        trash rows say so, and the token store (E2.2) drops their kept text. No undo (the dialog says so). Returns how
        many trash rows were marked."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return 0
        with self._command("forget_text") as cmd:
            n = self.conn.execute(f"UPDATE trash SET text_forgotten = 1 WHERE restored_at IS NULL AND text_forgotten = 0 "
                                  f"AND item_id IN ({','.join('?' * len(ids))})", ids).rowcount
            if n:
                cmd.touch()
            return n

    def set_watched(self, ids, watched=True):
        """The store's Watched record (✅ G1.1-5)."""
        return self._status("set_watched", ids, "watched", 1 if watched else 0)

    def pin(self, ids):
        """Pin (✅ G1.1-3): bumps `pins_version` beside `state_version`."""
        with self._command("pin") as cmd:
            rows = self.conn.execute(f"SELECT id, pinned FROM items WHERE id IN ({','.join('?' * len(ids))})",
                                     list(ids)).fetchall()
            changes = [(i, old) for i, old in rows if old is None]
            if not changes:
                return None
            stamp = _now()
            self.conn.executemany("UPDATE items SET pinned = ? WHERE id = ?", [(stamp, i) for i, _ in changes])
            cmd.feed(i for i, _ in changes)
            change = self._change(cmd, "pin")
            change.status = [(i, "pinned", None, stamp) for i, _ in changes]
            cmd.touch(pins=True)
            return change

    def unpin(self, ids):
        return self._status("unpin", ids, "pinned", None, pins=True)

    def receipt(self, item_id, mined_at):
        """Connect's receipt (2.7, ✅ G1.1-10): one row, `state_version` only — never `changed_in` or
        `order_version`."""
        return self._status("receipt", [item_id], "mined_at", mined_at)

    # --- bookkeeping (§6.6): no version moves ---------------------------------------------------- #

    def record_analysed(self, order_version):
        """At the end of a successful Generate that read the store (never after a JSON fallback). Keeps
        the larger of the stored value and the one given."""
        with self._writing():
            meta = self._meta()
            if order_version > meta.get("analysed_order_version", 0):
                self._set_meta({"analysed_order_version": order_version})

    def record_planned(self, order_version, pins_version):
        """At the end of a successful re-plan (2.6; Haya's E2.2). Keeps the larger values."""
        with self._writing():
            meta = self._meta()
            values = {}
            if order_version > meta.get("planned_order_version", 0):
                values["planned_order_version"] = order_version
            if pins_version > meta.get("planned_pins_version", 0):
                values["planned_pins_version"] = pins_version
            if values:
                self._set_meta(values)

    def plan_current(self):
        v = self.versions()
        return v["planned_order_version"] == v["order_version"] and v["planned_pins_version"] == v["pins_version"]

    def journey_pending(self):
        v = self.versions()
        return v["analysed_order_version"] < v["order_version"]

    # --- the placement log's readers (§6.6) ------------------------------------------------------ #

    def _log_seq(self):
        row = self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'placement_log'").fetchone()
        meta = self._meta()
        return max(row[0] if row else 0, meta.get("log_seq", 0))

    def register_reader(self, name):
        """A reader's watermark, set once — when it is first switched on — to `log_seq`, so older events
        are never read (✅ G1.1-2). From then on every command writes its events."""
        with self._writing():
            if f"reader:{name}" not in self._meta():
                self._set_meta({f"reader:{name}": self._log_seq(), f"reader_epoch:{name}": self._meta()["epoch"],
                                "copy_dirty": self._meta().get("copy_dirty", 0) + 1})

    def unregister_reader(self, name):
        """A reader switched off (Connect's preview, P3.1): its watermark goes. With no reader left nothing is
        logged any more; the log's rows stay — who placed what is kept — until `prune_log`'s 30 days age them out
        (✅ L3.1 call c), and the copy carries them meanwhile. `log_seq` keeps the last id, so ids are never reused and
        a reader switched on again starts past it (✅ G1.1-2). Bookkeeping: no version moves. False when no such
        reader was set."""
        with self._writing():
            meta = self._meta()
            if f"reader:{name}" not in meta:
                return False
            seq = self._log_seq()
            self.conn.execute("DELETE FROM meta WHERE key IN (?, ?)", (f"reader:{name}", f"reader_epoch:{name}"))
            self._set_meta({"log_seq": seq, "copy_dirty": int(meta.get("copy_dirty") or 0) + 1})
            return True

    def advance_reader(self, name, log_id):
        """Bookkeeping the copy carries: no version moves, `copy_dirty` set."""
        with self._writing():
            self._set_meta({f"reader:{name}": log_id, f"reader_epoch:{name}": self._meta()["epoch"], "copy_dirty": self._meta().get("copy_dirty", 0) + 1})

    def read_events(self, name):
        """(events after the reader's watermark, gap). A gap — the oldest id left above the watermark +
        1, an empty log while `log_seq` is above it, or a new epoch since the last read — means: resync
        from the top N of Current instead of reading events."""
        with self._reading():
            meta = self._meta()
            mark = meta.get(f"reader:{name}")
            if mark is None:
                raise StoreError(f"no reader named {name!r}")
            rows = self.conn.execute("SELECT id, item_id, kind, by, explicit, state_version, at FROM placement_log "
                                     "WHERE id > ? ORDER BY id", (mark,)).fetchall()
            oldest = self.conn.execute("SELECT MIN(id) FROM placement_log").fetchone()[0]
            seq = self._log_seq()
            epoch_seen = meta.get(f"reader_epoch:{name}")
        gap = (oldest is not None and oldest > mark + 1) or (oldest is None and seq > mark) or \
            (epoch_seen is not None and str(epoch_seen) != str(meta["epoch"]))
        return rows, gap

    def prune_log(self, now=None):
        """In the helper's run: delete events every reader has passed, or older than 30 days; with no reader left
        (`unregister_reader`), only those older than 30 days (✅ L3.1 call c)."""
        with self._writing():
            meta = self._meta()
            marks = [v for k, v in meta.items() if k.startswith("reader:")]
            cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.gmtime((now or time.time()) - LOG_KEEP_DAYS * 86400))
            young = self.conn.execute("SELECT MIN(id) FROM placement_log WHERE at >= ?", (cutoff,)).fetchone()[0]
            if young is None:
                young = self._log_seq() + 1
            bound = max(min(marks) + 1, young) if marks else young   # §12: as built; L3.1 call c
            return self.conn.execute("DELETE FROM placement_log WHERE id < ?", (bound,)).rowcount

    # --- undo (§6.11) ---------------------------------------------------------------------------- #

    def undo_check(self, change):
        """Read before any file work (Undo-Add checks before touching a file): (ids that can be undone,
        ids changed since by someone else)."""
        ids = change.added if change.kind in ("insert", "insert_at", "register", "restore", "import_finished") \
            else [it["id"] for it in change.items]
        rows = self._rows(ids)
        ok = [i for i in ids if i in rows and rows[i][3] == change.version]
        return ok, [i for i in ids if i not in ok]

    def undo(self, change, trashed_paths=None, rel_paths=None):
        """Undo one recorded change, in any order: a later change by anyone else is protected by the
        conflict rule (an item whose `changed_in` isn't the change's version is skipped, with a note);
        each undo restores the `changed_in` it replaced, so several undos in a row work. Returns the
        undo's own change (its `notes` say what was skipped), or None when nothing could be undone."""
        meta = self.meta()
        if change.epoch != meta["epoch"]:
            raise UndoRefused("the library was rebuilt since; that change can't be undone")
        kind = change.kind
        with self._command("undo", "undo") as cmd:
            if kind in ("insert", "insert_at", "restore") or (kind == "register" and change.added):
                ok, skipped = self.undo_check(change)
                if trashed_paths and any(i in skipped for i in trashed_paths):
                    raise StoreConflict("an item changed since its file was moved; nothing was undone")
                if not ok:
                    return self._skipped(cmd, len(skipped))
                explicit = 0 if kind == "register" else 1
                out = self._remove_as(ok, trashed_paths, explicit)
                if kind == "register" and getattr(change, "pairing_before", (None, None))[1] is not None:
                    content_key, old = change.pairing_before          # the key's pairing before hato moved it
                    if self.conn.execute("SELECT 1 FROM items WHERE id = ?", (old[0],)).fetchone():
                        self.conn.execute("INSERT OR IGNORE INTO pairings (content_key, item_id, pairing, paired_at) "
                                          "VALUES (?, ?, ?, ?)", (content_key,) + tuple(old))
            elif kind == "register":
                content_key, old = change.pairing_before
                now = self.conn.execute("SELECT item_id FROM pairings WHERE content_key = ?",
                                        (content_key,)).fetchone()
                if now is None or now[0] != change.pairing_item:
                    return self._skipped(cmd, 1)
                if old is None:
                    self.conn.execute("DELETE FROM pairings WHERE content_key = ?", (content_key,))
                else:
                    self.conn.execute("INSERT OR REPLACE INTO pairings (content_key, item_id, pairing, paired_at) "
                                      "VALUES (?, ?, ?, ?)", (content_key,) + tuple(old))
                cmd.touch()
                out, skipped = self._change(cmd, "undo"), []
            elif kind == "remove" or kind == "undo_add":
                rows = self.trash_rows(change.trash_ids)
                waiting = [r["id"] for r in rows if not r["restored_at"]]
                if not waiting:
                    return self._skipped(cmd, len(change.trash_ids))
                explicit = {it["id"]: it.get("explicit", 1) for it in change.items}
                out = self.restore(waiting, rel_paths, by="undo", kind="undo",
                                   explicit_of=lambda i: explicit.get(i, 1))
                skipped = [t for t in change.trash_ids if t not in waiting]
            elif kind == "relink":
                out, skipped = self._undo_relink(cmd, change)
            elif kind == "finish":
                out, skipped = self._undo_finish(cmd, change)
            elif kind == "import_finished":
                out, skipped = self._undo_import(cmd, change, trashed_paths)
            elif getattr(change, "options", None):
                out, skipped = self._undo_options(cmd, change)
            elif change.status:
                out, skipped = self._undo_status(cmd, change)
            elif kind == "join" and change.pieces is not None:
                out, skipped = self._undo_join(cmd, change)
            elif change.works is not None:
                out, skipped = self._undo_works(cmd, change)
            elif change.pieces is not None:
                out, skipped = self._undo_pieces(cmd, change)
            elif kind == "reset":
                out, skipped = self._undo_reset(cmd, change)
            else:
                out, skipped = self._replace(cmd, change)
            if skipped:
                out.notes.append(f"{len(skipped)} item{'s' if len(skipped) != 1 else ''} changed since and "
                                 f"{'were' if len(skipped) != 1 else 'was'} left as "
                                 f"{'they are' if len(skipped) != 1 else 'it is'}")
            if cmd.changed:
                self._unpiece(cmd, change)
            return out

    def _unpiece(self, cmd, change):
        """The pieces the change's settling step re-cut go back where each row still holds the piece it was given
        (the value check, §6.11): a foreign drop's split is mended when the drop is undone."""
        first, last = {}, {}
        for item_id, old, new in getattr(change, "repieced", ()):
            first.setdefault(item_id, old)                      # the piece before the change …
            last[item_id] = new                                 # … and the one it was left in
        for item_id, old in first.items():
            if item_id in cmd.hints or old is None:
                continue
            row = self.conn.execute("SELECT piece_id FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is not None and row[0] == last[item_id]:
                cmd.hints[item_id] = old
                cmd.reworked.add(item_id)

    def _skipped(self, cmd, n):
        out = self._change(cmd, "undo")
        out.notes.append(f"{n} item{'s' if n != 1 else ''} changed since and "
                         f"{'were' if n != 1 else 'was'} left as {'they are' if n != 1 else 'it is'}")
        return out

    def _remove_as(self, ids, trashed_paths, explicit):
        """Undo-Add: the rows go to the trash table, as `remove` does (pairings and links included, so
        Put back works); the files went to `.trash` by the caller's file code."""
        cmd = self._cmd
        events_before = len(cmd.events)
        out = self.remove(ids, trashed_paths, by="undo", kind="undo_add")
        cmd.events[events_before:] = [(i, k, explicit, b) for i, k, _e, b in cmd.events[events_before:]]
        for item in out.items:
            item["explicit"] = explicit
        return out

    def _undo_status(self, cmd, change):
        """The value check (§6.11): restore an item's previous value only where the column still holds
        the value the change set."""
        out = self._change(cmd, "undo")
        skipped, back = [], []
        for item_id, column, old, new in change.status:
            row = self.conn.execute(f"SELECT {column} FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None or row[0] != new:
                skipped.append(item_id)
            else:
                back.append((column, old, item_id))
        for column, old, item_id in back:
            self.conn.execute(f"UPDATE items SET {column} = ? WHERE id = ?", (old, item_id))
        cmd.feed(i for _c, _o, i in back)
        if back:
            cmd.touch(pins=any(c == "pinned" for c, _o, _i in back))
            news = {s[0]: s[3] for s in change.status}
            out.status = [(i, c, news[i], o) for c, o, i in back]
        return out, skipped

    def _undo_pieces(self, cmd, change):
        out = self._change(cmd, "undo")
        items = change.pieces["items"]
        rows = self._rows([i for i, _p, _c in items])
        ok = [(i, p, c) for i, p, c in items if i in rows and rows[i][3] == change.version]
        skipped = [i for i, _p, _c in items if i not in {o[0] for o in ok}]
        if not ok:
            return out, skipped
        for piece in change.pieces["deleted"]:
            self.conn.execute("INSERT OR IGNORE INTO pieces (id, title, kind, created_at) VALUES (?, ?, ?, ?)", piece)
            cmd.pieces_left.add(piece[0])
        there = {r[0] for r in self.conn.execute(f"SELECT id FROM pieces WHERE id IN ({','.join('?' * len(ok))})",
                                                 [p for _i, p, _c in ok])}
        skipped += [i for i, p, _c in ok if p not in there]     # its piece emptied and went since
        ok = [(i, p, c) for i, p, c in ok if p in there]
        cmd.pieces_left.update(rows[i][10] for i, _p, _c in ok if rows[i][10] is not None)   # left: gone if emptied
        self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?",
                              [(p, c, i) for i, p, c in ok])
        for i, p, _c in ok:                                     # the settling step checks the piece is one run again
            cmd.hints[i] = p
            cmd.reworked.add(i)
        cmd.feed(i for i, _p, _c in ok)
        for piece in change.pieces["created"]:
            if not self.conn.execute("SELECT 1 FROM items WHERE piece_id = ?", (piece,)).fetchone():
                self.conn.execute("DELETE FROM pieces WHERE id = ?", (piece,))
        cmd.touch()
        return out, skipped

    def _replace(self, cmd, change):
        """Re-place a change's items, as one new command, walking its list in the previous order: each
        item right after its recorded predecessor if that item is in the tier now (untouched, or put
        back earlier in this undo); else after that predecessor's own recorded predecessor, along the
        list; else before the nearest recorded successor outside the change's set that is in the tier;
        else at the tier's top. Each item's `changed_in` goes back to the value the change replaced."""
        out = self._change(cmd, "undo")
        items = change.items
        cur = self._rows([it["id"] for it in items])
        ok = [it for it in items if it["id"] in cur and cur[it["id"]][3] == change.version]
        skipped = [it["id"] for it in items if it not in ok]
        if not ok:
            return out, skipped
        okset = {it["id"] for it in ok}
        tiers = {it["tier"] for it in ok} | {cur[it["id"]][1] for it in ok}
        seqs, ords = self._seqs(tiers)
        for it in ok:
            seqs[cur[it["id"]][1]].remove(it["id"])
        info = {it["id"]: it for it in items}
        inset = set(info)
        restored = set()
        for it in items:
            if it["id"] not in okset:
                continue
            seq = seqs[it["tier"]]
            where = None
            p, seen = it["prev"], set()
            while p is not None and p not in seen:
                seen.add(p)
                if p in inset:
                    if p in restored:
                        where = ("after", p)
                        break
                    p = info[p]["prev"]
                    continue
                if p in seq:
                    where = ("after", p)
                break
            if where is None:
                n, seen = it["next"], set()
                while n is not None and n not in seen:
                    seen.add(n)
                    if n in inset:
                        n = info[n]["next"]
                        continue
                    if n in seq:
                        where = ("before", n)
                    break
            if where is None:
                seq.insert_after(it["id"], None)
            elif where[0] == "after":
                seq.insert_after(it["id"], where[1])
            else:
                seq.insert_before(it["id"], where[1])
            restored.add(it["id"])
        self._write_seqs(seqs, ords, okset, lambda i: info[i]["changed_in"])
        for it in ok:
            if it.get("piece") is not None:
                cmd.hints[it["id"]] = it["piece"]               # back in the piece it came from (05 §5.2)
        self.conn.executemany("UPDATE items SET graduated_at = ? WHERE id = ?",
                              [(it.get("graduated_at"), it["id"]) for it in ok if it["tier"] != cur[it["id"]][1]])
        cmd.touch(tiers)
        for it in ok:
            cmd.event(it["id"], "placed", it.get("explicit", 1))
        out.items = [{"id": it["id"], "tier": cur[it["id"]][1], "prev": None, "next": None,
                      "changed_in": change.version, "explicit": it.get("explicit", 1)} for it in ok]
        return out, skipped

    # --- the JSON copy's content (§6.7) ---------------------------------------------------------- #

    def export_snapshot(self):
        """(doc, state_version, copy_dirty): the copy's content, read in ONE short read transaction;
        serialising happens after it ends (K10). `doc` lacks only `content_sha`, added by `finish_doc`."""
        with self._reading():
            meta = self._meta()
            cur = self.conn.execute("SELECT * FROM items ORDER BY tier, ord, id")
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, r)) for r in cur.fetchall()]
            tables = {}
            present = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for name in COPY_TABLES:
                if name not in present:                            # an added table this store hasn't made yet
                    continue
                c = self.conn.execute(f"SELECT * FROM {name} ORDER BY rowid")
                fields = [d[0] for d in c.description]
                keep = [n for n, f in enumerate(fields) if not (name == "works" and f in WORK_NOT_COPIED)]
                tables[name] = {"fields": [fields[n] for n in keep],
                                "rows": [[r[n] for n in keep] for r in c.fetchall()]}
            log_seq = self._log_seq()
        rows.sort(key=lambda r: (TIERS[r["tier"]][3], r["ord"], r["id"]))
        by_tier = {t: [] for t in TIERS}
        for r in rows:
            by_tier[r["tier"]].append(json.loads(r["entry"]))
        doc = {}
        if "manifest_metadata" in meta:
            doc["metadata"] = json.loads(meta["manifest_metadata"])
        schedule = {TIERS[t][0]: by_tier[t] for t in ANALYSED}
        schedule.update(json.loads(meta.get("manifest_schedule_extra") or "{}"))
        doc["schedule"] = schedule
        for key, value in json.loads(meta.get("manifest_extra") or "{}").items():
            doc[key] = value
        lib_meta = {"epoch": meta["epoch"], "log_seq": log_seq, "mine_line": meta.get("mine_line", MINE_LINE_DEFAULT),
                    "arrivals_on": meta.get("arrivals_on", 0)}
        for key in COPY_META_KEYS:
            if key in meta:
                lib_meta[key] = meta[key]
        for key, value in meta.items():
            if key.startswith("reader"):
                lib_meta[key] = value
        doc["surasura_library"] = {
            "format": COPY_FORMAT, "store_schema": STORE_SCHEMA, "store_id": meta["store_id"],
            "version": meta["state_version"], "content_sha": None,
            "graduated": by_tier["graduated"], "arrivals": by_tier["arrivals"], "meta": lib_meta,
            "items": {"fields": list(ITEM_FIELDS), "rows": [[r[f] for f in ITEM_FIELDS] for r in rows]},
            "tables": tables}
        return doc, meta["state_version"], meta.get("copy_dirty", 0)


def content_sha(doc):
    """sha256 of the document minus `surasura_library`, in canonical form: line endings, a BOM,
    indentation and key order never matter, and no time stamp is inside (§6.7)."""
    body = {k: v for k, v in doc.items() if k != "surasura_library"}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def finish_doc(doc):
    doc["surasura_library"]["content_sha"] = content_sha(doc)
    return doc


def _stat_str(st):
    return f"{st.st_mtime_ns} {st.st_size}"


def _stat(path):
    try:
        return os.stat(path)
    except OSError:
        return None


class ManifestUnreadable(StoreError):
    """The manifest couldn't be read (a lock, an offline placeholder): retried, never treated as damage."""


def read_manifest(path):
    """(doc or None, read-time stat string, problem). Opened once, fstat'ed before and after the read;
    read again if the two differ — that fstat is the stat a builder records (§6.8). `doc` is None when
    the file is unusable: it doesn't parse, isn't a dict, or has no usable `schedule`."""
    raw = st = None
    for _ in range(5):
        try:
            with open(path, "rb") as f:
                st1 = os.fstat(f.fileno())
                raw = f.read()
                st = os.fstat(f.fileno())
        except OSError as exc:
            raise ManifestUnreadable(str(exc)) from exc
        if (st1.st_mtime_ns, st1.st_size) == (st.st_mtime_ns, st.st_size):
            break
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, _stat_str(st), f"doesn't parse: {exc}"
    if not isinstance(doc, dict):
        return None, _stat_str(st), "not a JSON object"
    if not isinstance(doc.get("schedule"), dict):
        return None, _stat_str(st), "no usable schedule"
    return doc, _stat_str(st), None


# ------------------------------------------------------------------------------------------------ #
# Normalising a manifest (§6.8)
# ------------------------------------------------------------------------------------------------ #

class _Norm:
    def __init__(self):
        self.tiers = {t: [] for t in TIERS}
        self.metadata = None
        self.has_metadata = False
        self.schedule_extra = {}
        self.extra = {}
        self.lib = None
        self.report = []


NEWER_COPY = "made by a newer Surasura"


def copy_is_newer(doc):
    """Was this copy written by a newer store (its `surasura_library` names a later schema or format)? Such a copy
    may carry tables and fields this version doesn't know: it is never rebuilt from, re-imported or repaired from
    here, and never overwritten (L2.2 G2.2-7)."""
    lib = doc.get("surasura_library") if isinstance(doc, dict) else None
    if not isinstance(lib, dict):
        return False
    try:
        return int(lib.get("store_schema") or 0) > STORE_SCHEMA or int(lib.get("format") or 0) > COPY_FORMAT
    except (TypeError, ValueError):
        return True                                    # a schema this version can't read: never built from


def normalise(doc, platform=sys.platform):
    """Keep what the copy re-emits (metadata, unknown schedule and top-level keys); drop, and list in
    the report, non-dict entries, `type == "Folder"` rows, rows without a non-empty string path, names
    that can't be encoded as UTF-8, and later duplicates of a key under this system's `path_key`
    (reading NOW → SOON → LATER, then the graduated and arrivals lists)."""
    norm = _Norm()
    if "metadata" in doc:
        norm.has_metadata, norm.metadata = True, doc["metadata"]
    schedule = doc.get("schedule") or {}
    for key, value in schedule.items():
        if key not in PHASES:
            norm.schedule_extra[key] = value
    for key, value in doc.items():
        if key not in ("metadata", "schedule", "surasura_library"):
            norm.extra[key] = value
    lib = doc.get("surasura_library")
    norm.lib = lib if isinstance(lib, dict) else None
    lists = [(TIER_OF_PHASE[p], schedule.get(p), p) for p in PHASES]
    if norm.lib:
        lists += [("graduated", norm.lib.get("graduated"), "graduated"), ("arrivals", norm.lib.get("arrivals"), "arrivals")]
    seen = {}
    for tier, entries, name in lists:
        if entries is None:
            if name in PHASES:
                norm.report.append(f"{name}: missing, read as empty")
            continue
        if not isinstance(entries, list):
            norm.report.append(f"{name}: not a list, read as empty")
            continue
        for n, entry in enumerate(entries):
            where = f"{name}[{n}]"
            if not isinstance(entry, dict):
                norm.report.append(f"{where}: dropped (not an object)")
                continue
            if entry.get("type") == "Folder":
                norm.report.append(f"{where}: dropped (a Folder row)")
                continue
            rel = entry.get("physical_path")
            if not isinstance(rel, str) or not rel.strip():
                norm.report.append(f"{where}: dropped (no file path)")
                continue
            try:
                rel.encode("utf-8")
            except UnicodeEncodeError:
                norm.report.append(f"{where}: dropped (a name that can't be encoded: {rel.encode('utf-8', 'replace').decode('utf-8')})")
                continue
            key = path_key(rel, platform)
            if key in seen:
                norm.report.append(f"{where}: dropped ({rel} duplicates {seen[key]})")
                continue
            seen[key] = rel
            norm.tiers[tier].append(entry)
    return norm


def _strip(rel):
    return rel[2:] if rel.startswith("./") else rel


def _fingerprint(data_dir, rel):
    try:
        st = os.stat(os.path.join(data_dir, _strip(rel)))
        return st.st_size, st.st_mtime_ns, "available"
    except OSError:
        return None, None, "missing"


def _item_from_entry(entry, tier, data_dir, now, **extra):
    rel = entry["physical_path"]
    size, mtime_ns, availability = _fingerprint(data_dir, rel)
    item = {"id": None, "root_id": None, "rel_path": rel, "rel_key": path_key(rel), "tier": tier, "entry": entry,
            "size": size, "mtime_ns": mtime_ns, "availability": availability, "added_at": now,
            "graduated_at": None, "piece_id": None, "watched": 0, "mined_at": None, "pinned": None,
            "in_learning_order": 1, "work_id": None, "mine_asked": None}
    item.update(extra)
    return item


def walk_tree(base, rel_prefix):
    """(rel, size, mtime_ns) for the content files under `base`, in the disk sync's walk order
    (`os.scandir`, top-down, files of a folder before its subfolders), fingerprints from the listing.
    Names that can't be encoded as UTF-8 are returned separately (K28)."""
    files, bad = [], []
    stack = [(base, rel_prefix)]
    while stack:
        folder, rel = stack.pop(0)
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        subdirs = []
        for e in entries:
            if e.name in SKIP_NAMES:
                continue
            child = f"{rel}/{e.name}" if rel else e.name
            try:
                child.encode("utf-8")
            except UnicodeEncodeError:
                bad.append(child.encode("utf-8", "replace").decode("utf-8"))
                continue
            try:
                if e.is_dir():
                    subdirs.append((e.path, child))
                elif is_content_name(e.name):
                    st = e.stat()
                    files.append((child, st.st_size, st.st_mtime_ns))
            except OSError:
                continue
        stack[0:0] = subdirs
    return files, bad


def _junban_current(user_files_dir):
    """Junban's mtime rule (`list_is_stale` false): the order CSV is newer than the manifest."""
    try:
        from app.path_utils import get_user_file
        csv = get_user_file(os.path.join("results", "priority_learning_list.csv"))
        return os.path.getmtime(csv) >= os.path.getmtime(manifest_path(user_files_dir))
    except OSError:
        return False


# ------------------------------------------------------------------------------------------------ #
# Building: one builder for migration, rebuild and Repair (§6.8, §6.9)
# ------------------------------------------------------------------------------------------------ #

def _helper_store(db_path, language, data_dir, user_files_dir):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return Store(db_path, language, data_dir, user_files_dir, role="helper")


def _ensure_schema(store):
    """The tables, empty, in their own transaction: a failure record always has a `meta` to go in.
    Returns the database's user_version before."""
    with store._writing(begin=False):
        store.conn.execute("PRAGMA journal_mode=WAL")
    with store._writing():
        version = store.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            existing = store.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                                          "AND name NOT LIKE 'sqlite_%'").fetchone()[0]
            if existing:
                raise StoreError("a library database without a schema version; left alone")
            for sql in SCHEMA_SQL + SCHEMA_2_SQL:
                store.conn.execute(sql)
            store.conn.execute(f"PRAGMA user_version = {STORE_SCHEMA}")
    return version


class UpgradeFailed(StoreError):
    """The upgrade's check before commit found a difference, or a step failed: nothing changed (L2.2 02 §2.6 #6)."""


def _upgrade(store):
    """Forward-only upgrades, each in one transaction, after a copy through the backup API (R-5). A failure rolls the
    whole step back, records why (`meta.upgrade_failed`, its own small transaction) and raises `UpgradeFailed`: the
    store stays at its schema and the next helper run tries again."""
    version = store.conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= STORE_SCHEMA:
        return False
    _backup_db(store.conn, store.db_path)
    try:
        with store._writing():
            while version < STORE_SCHEMA:
                _UPGRADES[version](store)
                version += 1
                store.conn.execute(f"PRAGMA user_version = {version}")
            store.conn.execute("DELETE FROM meta WHERE key = 'upgrade_failed'")
    except Exception as exc:
        try:
            with store._writing():
                store._set_meta({"upgrade_failed": _dumps({"at": _now(), "error": f"{type(exc).__name__}: {exc}",
                                                           "app_version": _app_version()})})
        except Exception:
            pass
        raise UpgradeFailed(f"{type(exc).__name__}: {exc}") from exc
    return True


def _order_snapshot(conn):
    """What an upgrade must never change (02 §2.6 #6): every id, tier, order, pin and watched mark."""
    return conn.execute("SELECT id, tier, ord, pinned, watched FROM items ORDER BY tier, ord, id").fetchall()


def _upgrade_1_to_2(store):
    """Schema 2 (L2.2 02 §2.6): the tables, columns and indexes; works seeded by folder, pieces completed, search keys,
    the Soon line at NOW's count (nobody's list changes, Q2-4), New arrivals on (D30), every row's `feed_in` the
    upgrade's version; checked before it commits. `epoch` stays (ids, order and tiers untouched)."""
    conn = store.conn
    before = _order_snapshot(conn)
    later = [sql for sql in SCHEMA_2_SQL if sql.startswith("CREATE INDEX items_")]
    for sql in ADDED_TABLES_SQL + SCHEMA_2_SQL:
        if sql not in later:
            conn.execute(sql)
    meta = store._meta()
    if "migrated_at" not in meta:
        for sql in later:
            conn.execute(sql)
        return                                                 # never built (no rows): the build seeds it
    version = meta["state_version"] + 1
    _seed_schema2(store, version)
    for sql in later:              # built once over the seeded rows, not kept up through 200k updates (§12.8)
        conn.execute(sql)
    now_count = conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'now'").fetchone()[0]
    store._set_meta({"state_version": version, "soon_line": now_count, "arrivals_on": 1,
                     "copy_dirty": int(meta.get("copy_dirty") or 0) + 1})
    if _order_snapshot(conn) != before:
        raise StoreError("the upgrade's check found a changed order, tier, pin or watched mark")
    problem = _pieces_ok(conn) or _works_ok(conn)
    if problem:
        raise StoreError(f"the upgrade's check: {problem}")


_UPGRADES[1] = _upgrade_1_to_2


def _next_id(conn, table):
    """The next id past every id the table ever issued (K30)."""
    seq = conn.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name = ?), 0), "
                       f"COALESCE((SELECT MAX(id) FROM {table}), 0)", (table,)).fetchone()
    return max(seq) + 1


def _work_ids_of(record):
    """The outside ids a record carries, cleaned: {anilist_id, tmdb_id, youtube_channel} (None where absent)."""
    out = {"anilist_id": None, "tmdb_id": None, "youtube_channel": None}
    if not isinstance(record, dict):
        return out
    a = record.get("anilist_id")
    if isinstance(a, int) and not isinstance(a, bool) and a > 0:
        out["anilist_id"] = a
    t = record.get("tmdb_id")
    if isinstance(t, str) and re.fullmatch(r"(tv|movie):\d+", t.strip()):
        out["tmdb_id"] = t.strip()
    c = record.get("channel_id")
    if isinstance(c, str) and c.strip():
        out["youtube_channel"] = c.strip()
    return out


Pin = namedtuple("Pin", "item_id rel_path tier pinned_at")
PLACING_TARGETS = ("wait", "top", "after-show", "soon", "goal", "finished")


def line_fingerprint(text):
    """A short fingerprint of a line's text (D1): 12 hex characters of the SHA-1 of its NFKC form with every space and
    line break taken out — the same for the same words whatever their timing, the file's line breaks or full-width
    letters, so a card's line is found again after a re-sync."""
    import unicodedata
    folded = "".join(unicodedata.normalize("NFKC", str(text or "")).split())
    return hashlib.sha1(folded.encode("utf-8")).hexdigest()[:12]


def _rule_for(record, rules):
    """(source, target) of the rule for a record's arrival, or None: it waits (05 §5.12, `app/connect/rules.py`'s
    rule). Sources: `<producer>:<channel id>` before the producer's own line; targets PLACING_TARGETS."""
    if not isinstance(rules, dict) or not rules:
        return None
    producer = str((record or {}).get("producer") or "hato").strip() if isinstance(record, dict) else "hato"
    channel = (record or {}).get("channel_id") if isinstance(record, dict) else None
    for source in ([f"{producer}:{channel}"] if channel else []) + [producer]:
        target = rules.get(source)
        if target == "wait":
            return None
        if target in PLACING_TARGETS:
            return source, target
    return None


def _episode(record):
    """(season, episode) a record's show names — none named is the first season — or None."""
    show = record.get("show") if isinstance(record, dict) else None
    if not isinstance(show, dict):
        return None
    episode, season = show.get("episode"), show.get("season")
    if isinstance(episode, bool) or not isinstance(episode, (int, float)):
        return None
    if isinstance(season, str) and season.strip().isdigit():
        season = int(season.strip())
    return (season if isinstance(season, int) and not isinstance(season, bool) else 1, episode)


def media_type_guess(counts, anilist_id=None, tmdb_id=None):
    """A title's type when nobody said (05 §5.4), from its items' source types ({type: count}) and its ids: YouTube
    or bilibili → youtube; an epub → book; text → text; subtitles → anime with an AniList id, drama with a TMDB `tv:`
    id, movie with `movie:`; anything else None (*Video*, G2.2-5). Computed on read, never stored."""
    if not counts:
        return None
    kind = max(counts, key=lambda k: (counts[k], k or ""))
    if kind in ("youtube", "bilibili"):
        return "youtube"
    if kind == "epub":
        return "book"
    if kind == "text":
        return "text"
    if kind == "subtitle":
        if tmdb_id and str(tmdb_id).startswith("movie:"):
            return "movie"
        if anilist_id:
            return "anime"
        if tmdb_id and str(tmdb_id).startswith("tv:"):
            return "drama"
    return None


def _show_title(record):
    """The show's title a record names (`show.title`, 09-hato-layer §1), or None."""
    show = record.get("show") if isinstance(record, dict) else None
    title = show.get("title") if isinstance(show, dict) else None
    return title.strip() if isinstance(title, str) and title.strip() else None


def _work_search_key(title, titles, language):
    return "\n".join(dict.fromkeys(k for k in [search_fold(title, language)] +
                                   [search_fold(t, language) for t in titles] if k))


def _seed_schema2(store, version):
    """Works, pieces, search keys and the feed for every row that lacks them (L2.2 02 §2.6 steps 2–5): the upgrade's
    seeding and every build's (`_write_image`). One pass over items:

    - **Works:** an item without one joins the work holding its folder key (`folder_key_of`), else a new one titled by
      its folder below the tier folder; a loose file is a work of its own, titled by its title. A pairing's record
      fills its item's work's AniList / TMDB ids; two works one id names are merged, the lower id kept (G2.2-6).
    - **Pieces:** each tier is read in (ord, id); a piece whose members aren't one run of one work in one tier keeps
      its id on its first run and each later run becomes a piece of its own; an item without a piece joins the piece
      of its work it directly follows, else starts one.
    - **Search keys** for every item and work; `feed_in` = `version` for every row; `feed_floor` = `version`."""
    conn = store.conn
    language = store.language
    now = _now()
    works = {r[0]: {"title": r[1], "titles": json.loads(r[2] or "[]"), "fk": r[3], "anilist_id": r[4],
                    "tmdb_id": r[5], "youtube_channel": r[6], "new": False}
             for r in conn.execute("SELECT id, title, titles, folder_key, anilist_id, tmdb_id, youtube_channel "
                                   "FROM works")}
    by_key = {}
    for wid in sorted(works):
        if works[wid]["fk"] is not None:
            by_key.setdefault(works[wid]["fk"], wid)
    next_work = _next_id(conn, "works")
    rows = conn.execute("SELECT id, rel_path, tier, title, work_id, piece_id FROM items").fetchall()
    item_work = {}
    fk_of = {}                                                  # one folder's key, worked out once
    for item_id, rel, tier, title, work_id, _piece in rows:
        if work_id in works:
            item_work[item_id] = work_id
            continue
        folder = _rel_dir(_strip(rel))
        fk = fk_of[folder] if folder in fk_of else fk_of.setdefault(folder, folder_key_of(rel))
        wid = by_key.get(fk) if fk is not None else None
        if wid is None:
            wid = next_work
            next_work += 1
            works[wid] = {"title": _below_tier(rel) if fk is not None else (title or rel.rsplit("/", 1)[-1]),
                          "titles": [], "fk": fk, "anilist_id": None, "tmdb_id": None, "youtube_channel": None,
                          "new": True}
            if fk is not None:
                by_key[fk] = wid
        item_work[item_id] = wid
    # the records' ids, and one title per id (G2.2-6): a union of the works an id names, the lowest id kept
    parent = {}

    def find(w):
        while parent.get(w, w) != w:
            w = parent[w]
        return w
    holder = {}
    for wid in sorted(works):
        for col in ("anilist_id", "tmdb_id"):
            if works[wid][col] is not None:
                holder.setdefault((col, works[wid][col]), wid)
    for item_id, text in conn.execute("SELECT item_id, pairing FROM pairings"):
        try:
            ids = _work_ids_of(json.loads(text))
        except ValueError:
            continue
        wid = item_work.get(item_id)
        if wid is None:
            continue
        for col in ("anilist_id", "tmdb_id"):
            if ids[col] is None:
                continue
            w = find(wid)
            other = holder.get((col, ids[col]))
            if other is None:
                if works[w][col] is None:
                    works[w][col] = ids[col]
                    holder[(col, ids[col])] = w
            elif find(other) != w:
                keep, drop = sorted((find(other), w))
                parent[drop] = keep
                for c2 in ("anilist_id", "tmdb_id", "youtube_channel"):
                    if works[keep][c2] is None:
                        works[keep][c2] = works[drop][c2]
                if works[keep]["fk"] is None:
                    works[keep]["fk"] = works[drop]["fk"]
                works[keep]["titles"] += [t for t in [works[drop]["title"]] + works[drop]["titles"]
                                          if t != works[keep]["title"] and t not in works[keep]["titles"]]
    for item_id in item_work:
        item_work[item_id] = find(item_work[item_id])
    merged = [w for w in works if find(w) != w]
    old_merged = [w for w in merged if not works[w]["new"]]
    if old_merged:                                              # an earlier store's works one id now names
        conn.executemany("UPDATE items SET work_id = NULL WHERE work_id = ?", [(w,) for w in old_merged])
        conn.executemany("DELETE FROM works WHERE id = ?", [(w,) for w in old_merged])
    keep_works = [w for w in works if find(w) == w]
    conn.executemany("UPDATE works SET anilist_id = NULL, tmdb_id = NULL WHERE id = ?",
                     [(w,) for w in keep_works if not works[w]["new"]])    # re-set below: no unique clash midway
    for w in sorted(keep_works):
        d = works[w]
        key = _work_search_key(d["title"], d["titles"], language)
        if d["new"]:
            conn.execute("INSERT INTO works (id, title, titles, search_key, folder_key, anilist_id, tmdb_id, "
                         "youtube_channel, feed_in, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (w, d["title"], _dumps(d["titles"]), key, d["fk"], d["anilist_id"], d["tmdb_id"],
                          d["youtube_channel"], version, now))
        else:
            conn.execute("UPDATE works SET titles = ?, search_key = ?, folder_key = ?, anilist_id = ?, tmdb_id = ?, "
                         "youtube_channel = ?, feed_in = ? WHERE id = ?",
                         (_dumps(d["titles"]), key, d["fk"], d["anilist_id"], d["tmdb_id"], d["youtube_channel"],
                          version, w))
    if next_work > 1:
        _set_seq(conn, "works", max(next_work - 1, conn.execute("SELECT COALESCE(MAX(id), 0) FROM works").fetchone()[0]))
    # pieces: one run of one work in one tier each
    pieces = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, title, kind FROM pieces")}
    next_piece = max([0] + list(pieces)) + 1
    new_pieces = []
    updates = []
    used = set()
    ordered = conn.execute("SELECT id, tier, piece_id, title FROM items ORDER BY tier, ord, id").fetchall()
    prev_tier = prev_work = prev_old = prev_new = None
    for item_id, tier, piece, title in ordered:
        wid = item_work[item_id]
        if tier != prev_tier:
            prev_work = prev_old = prev_new = None
            prev_tier = tier
        if piece is not None and piece not in pieces:
            piece = None
        if piece is not None and piece == prev_old and wid == prev_work:
            new = prev_new                                      # the run goes on
        elif piece is not None and piece not in used:
            new = piece                                         # a piece's first run keeps its id
            used.add(piece)
        elif piece is None and prev_new is not None and wid == prev_work:
            new = prev_new                                      # joins the piece of its work it directly follows
        else:
            new = next_piece
            next_piece += 1
            used.add(new)
            base = pieces.get(piece) if piece is not None else None
            new_pieces.append((new, base[0] if base else works[wid]["title"], base[1] if base else "run", now))
        updates.append((wid, new, search_fold(title, language), version, item_id))
        prev_work, prev_old, prev_new = wid, piece, new
    if new_pieces:
        conn.executemany("INSERT INTO pieces (id, title, kind, created_at) VALUES (?, ?, ?, ?)", new_pieces)
    conn.executemany("UPDATE items SET work_id = ?, piece_id = ?, search_key = ?, feed_in = ? WHERE id = ?", updates)
    conn.execute("DELETE FROM pieces WHERE id NOT IN (SELECT piece_id FROM items WHERE piece_id IS NOT NULL)")
    store._set_meta({"feed_floor": version, "search_fold": SEARCH_FOLD_VERSION})


def _pieces_ok(conn):
    """None when every piece is one contiguous run, in (ord, id), of one work's items in one tier and every item has a
    piece and a work (L2.2 05 §5.2 rule 1); else what's wrong."""
    seen = set()
    prev = None
    for item_id, tier, piece, work in conn.execute("SELECT id, tier, piece_id, work_id FROM items "
                                                   "ORDER BY tier, ord, id"):
        if piece is None:
            return f"item {item_id} has no piece"
        if prev is not None and prev[0] == tier and prev[1] == piece:
            if prev[2] != work:
                return f"piece {piece} holds two works"
        elif piece in seen:
            return f"piece {piece} is not one run in one tier"
        seen.add(piece)
        prev = (tier, piece, work)
    have = {r[0] for r in conn.execute("SELECT id FROM pieces")}
    if seen - have:
        return f"items in pieces that don't exist: {sorted(seen - have)[:5]}"
    if have - seen:
        return f"empty pieces: {sorted(have - seen)[:5]}"
    return None


def _works_ok(conn):
    """None when every item has a work that exists; else what's wrong."""
    row = conn.execute("SELECT id FROM items WHERE work_id IS NULL OR work_id NOT IN (SELECT id FROM works) "
                       "LIMIT 1").fetchone()
    return f"item {row[0]} has no work" if row else None


def _pieces_by_runs(items_by_tier, now):
    """Each tier's runs of one non-empty folder become one piece (a run, not a folder: §6.8)."""
    pieces = []
    for tier in TIERS:
        prev = None
        for item in items_by_tier.get(tier, []):
            folder = _entry_folder(item["entry"])
            if not folder:
                prev = None
                continue
            if prev != folder:
                pieces.append([len(pieces) + 1, folder, "run", now])
                prev = folder
            item["piece_id"] = len(pieces)
    return pieces


def _set_seq(conn, name, value):
    if conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (value, name)).rowcount == 0:
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (name, value))


def _write_image(store, image, meta):
    """Write a built image into the (empty) tables, inside the caller's transaction: roots, pieces,
    items (keys 1024, 2048, … per tier), every other table, the id sequences (K30) and `meta`."""
    conn = store.conn
    now = _now()
    for sql in ADDED_TABLES_SQL:
        conn.execute(sql)
    tables = image["tables"]
    roots = tables.get("roots")
    if roots and roots["rows"]:
        _insert_rows(conn, "roots", roots)
        root_id = conn.execute("SELECT id FROM roots WHERE kind = 'library' ORDER BY id LIMIT 1").fetchone()
        root_id = root_id[0] if root_id else conn.execute(
            "INSERT INTO roots (kind, path, created_at) VALUES ('library', NULL, ?)", (now,)).lastrowid
    else:
        root_id = conn.execute("INSERT INTO roots (kind, path, created_at) VALUES ('library', NULL, ?)",
                               (now,)).lastrowid
    for name in ("pieces", "trash", "exclusions", "anki_changes", "placement_log"):
        if tables.get(name) and tables[name]["rows"]:
            _insert_rows(conn, name, tables[name])
    t = tables.get("works")                                    # before the items that point at them
    if t and t["rows"]:
        fields = [f for f in t["fields"] if f not in WORK_NOT_COPIED]
        cols = [t["fields"].index(f) for f in fields]
        _insert_rows(conn, "works", {"fields": fields + ["search_key"],
                                     "rows": [[r[c] for c in cols] + [""] for r in t["rows"]]})
    work_ids = {r[0] for r in conn.execute("SELECT id FROM works")}
    used = [i["id"] for i in image["items"] if i["id"] is not None]
    next_id = max(used + [0]) + 1
    piece_ids = {r[0] for r in conn.execute("SELECT id FROM pieces")}
    rows = []
    position = {}
    for item in image["items"]:
        if item["id"] is None:
            item["id"] = next_id
            next_id += 1
        position[item["tier"]] = position.get(item["tier"], 0) + 1
        title, folder, source_type = _columns(item["entry"])
        rows.append((item["id"], item["root_id"] or root_id, item["rel_path"], item["rel_key"], item["tier"],
                     STEP * position[item["tier"]], _dumps(item["entry"]), title, folder, source_type,
                     item["availability"], item["size"], item["mtime_ns"], item.get("changed_in", 1),
                     item["added_at"] or now, item["graduated_at"],
                     item["piece_id"] if item["piece_id"] in piece_ids else None, item["watched"] or 0,
                     item["mined_at"], item["pinned"], 1 if item["in_learning_order"] is None else item["in_learning_order"],
                     item.get("work_id") if item.get("work_id") in work_ids else None, item.get("mine_asked")))
    conn.executemany(
        "INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, source_type, "
        "availability, size, mtime_ns, changed_in, added_at, graduated_at, piece_id, watched, mined_at, pinned, "
        "in_learning_order, work_id, mine_asked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?)", rows)
    have = {r[0] for r in rows}
    for name in ("anki_links", "pairings"):
        t = tables.get(name)
        if t and t["rows"]:
            col = t["fields"].index("item_id")
            kept = {"fields": t["fields"], "rows": [r for r in t["rows"] if r[col] in have]}
            _insert_rows(conn, name, kept)
    for name in ("made_words", "made_lines"):                   # outlive Remove: an item or its trash row
        t = tables.get(name)
        if t and t["rows"]:
            col = t["fields"].index("item_id")
            known = have | {r[0] for r in conn.execute("SELECT item_id FROM trash")}
            _insert_rows(conn, name, {"fields": t["fields"], "rows": [r for r in t["rows"] if r[col] in known]})
    # K30: AUTOINCREMENT learns only from the rows a table holds; ids are never reused.
    highest = max([0] + list(have) + [r[0] for r in conn.execute(
        "SELECT MAX(item_id) FROM trash UNION ALL SELECT MAX(item_id) FROM placement_log "
        "UNION ALL SELECT MAX(item_id) FROM pairings UNION ALL SELECT MAX(item_id) FROM anki_links "
        "UNION ALL SELECT MAX(item_id) FROM anki_changes UNION ALL SELECT MAX(item_id) FROM made_words "
        "UNION ALL SELECT MAX(item_id) FROM made_lines")
        if r[0] is not None])
    _set_seq(conn, "items", highest)
    marks = [v for k, v in meta.items() if k.startswith("reader:")]
    log_high = conn.execute("SELECT COALESCE(MAX(id), 0) FROM placement_log").fetchone()[0]
    _set_seq(conn, "placement_log", max([log_high, int(meta.get("log_seq", 0))] + [int(m) for m in marks]))
    store._set_meta(meta)
    _seed_schema2(store, int(meta["state_version"]))           # works, pieces, search keys, the feed (L2.2 02 §2.6)


def _insert_rows(conn, name, table):
    fields = table["fields"]
    conn.executemany(f"INSERT INTO {name} ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                     [tuple(r) for r in table["rows"]])


def _manifest_meta(norm):
    meta = {"manifest_schedule_extra": _dumps(norm.schedule_extra), "manifest_extra": _dumps(norm.extra)}
    if norm.has_metadata:
        meta["manifest_metadata"] = _dumps(norm.metadata)
    return meta


def _image_from_manifest(norm, data_dir, graduated_walk=True):
    """A first migration's image: every normalised entry as an item (its tier from its PHASE KEY, never
    its folder; the entry verbatim), the Graduated folder's content files as `graduated` (dated Earlier,
    de-duplicated by key), and piece ids from runs."""
    now = _now()
    items, keys = [], set()
    by_tier = {t: [] for t in TIERS}
    for tier in ANALYSED:
        for entry in norm.tiers[tier]:
            item = _item_from_entry(entry, tier, data_dir, now)
            keys.add(item["rel_key"])
            by_tier[tier].append(item)
    imported = []
    if graduated_walk:
        files, _bad = walk_tree(os.path.join(data_dir, GRADUATED_FOLDER), GRADUATED_FOLDER)
        marker_cache = {}
        for rel, size, mtime_ns in files:
            key = path_key(rel)
            if key in keys:
                continue
            keys.add(key)
            entry = make_entry(rel, "Graduated", _detect_source_type(os.path.join(data_dir, rel), marker_cache))
            by_tier["graduated"].append(_item_from_entry(entry, "graduated", data_dir, now))
            imported.append(rel)
    pieces = _pieces_by_runs(by_tier, now)
    for tier in sorted(TIERS, key=lambda t: TIERS[t][3]):
        items += by_tier[tier]
    return {"items": items, "tables": {"pieces": {"fields": ["id", "title", "kind", "created_at"], "rows": pieces}},
            "imported": imported, "pieces": len(pieces)}


def _records(lib):
    """The copy's item records: {rel_key: {field: value}} in their (tier, ord, id) order."""
    out = {}
    items = lib.get("items") if isinstance(lib, dict) else None
    if not isinstance(items, dict):
        return out
    fields = items.get("fields") or []
    for row in items.get("rows") or []:
        if isinstance(row, list) and len(row) == len(fields):
            rec = dict(zip(fields, row))
            if isinstance(rec.get("rel_path"), str):
                out.setdefault(path_key(rec["rel_path"]), rec)
    return out


def _image_from_copy(norm, data_dir, by_records=False):
    """A rebuild's image (a moved folder, a new PC): the copy's lists give the entries and their order,
    its item records the ids and the state, its tables everything else. `by_records`: the records give
    the order and the membership (a copy an older version edited; the edit is then re-imported)."""
    now = _now()
    recs = _records(norm.lib)
    items = []
    if by_records:
        entries = {path_key(e["physical_path"]): e for t in TIERS for e in norm.tiers[t]}
        listing = [(rec.get("tier"), entries.get(key) or make_entry(rec["rel_path"], "Rebuild", with_source_type=False))
                   for key, rec in recs.items() if rec.get("tier") in TIERS]
        listing.sort(key=lambda p: TIERS[p[0]][3])
    else:
        listing = [(tier, entry) for tier in sorted(TIERS, key=lambda t: TIERS[t][3]) for entry in norm.tiers[tier]]
    for tier, entry in listing:
            item = _item_from_entry(entry, tier, data_dir, now)
            rec = recs.get(item["rel_key"])
            if rec:
                for field in ITEM_FIELDS:
                    if field in rec and field not in ("rel_path", "tier", "availability", "size", "mtime_ns"):
                        item[field] = rec[field]
                if item["availability"] == "missing" and rec.get("size") is not None:
                    item["size"], item["mtime_ns"] = rec.get("size"), rec.get("mtime_ns")
            items.append(item)
    tables = {}
    for name, table in ((norm.lib.get("tables") or {}).items()):
        if name in COPY_TABLES and isinstance(table, dict) and isinstance(table.get("fields"), list):
            tables[name] = {"fields": table["fields"], "rows": [r for r in table.get("rows") or [] if isinstance(r, list)]}
    return {"items": items, "tables": tables}


def _copy_meta_block(lib):
    """The meta a copy brings back. The Soon line and New arrivals' switch are 3.0's (schema 2): a 2.x copy's
    `arrivals_on` was 2.x's off, so a library rebuilt from one starts as an upgraded one does (on, D30) and its line
    is re-derived from its tiers (`_line_after_build`)."""
    meta = {}
    block = lib.get("meta") if isinstance(lib, dict) else None
    if isinstance(block, dict):
        try:
            schema = int(lib.get("store_schema") or 0)
        except (TypeError, ValueError):
            schema = 0
        for key in ("mine_line", "log_seq") + COPY_META_KEYS + (("arrivals_on",) if schema >= 2 else ()):
            if key in block and not (key == "soon_line" and schema < 2):
                meta[key] = block[key]
        for key, value in block.items():
            if key.startswith("reader"):
                meta[key] = value
    return meta


def _fresh_meta(store_id, epoch, state_version, analysed_current=False):
    """A new store's meta. 3.0 builds every library with New arrivals on (D30), as the upgrade turns them on; the Soon
    line comes from the image (`_line_after_build`)."""
    return {"store_id": store_id, "epoch": epoch, "state_version": state_version, "order_version": 1,
            "availability_version": 1, "pins_version": 1, "analysed_order_version": 1 if analysed_current else 0,
            "planned_order_version": 0, "planned_pins_version": 0, "last_export_version": 0,
            "last_export_stat": "", "copy_dirty": 0, "log_seq": 0, "mine_line": MINE_LINE_DEFAULT, "arrivals_on": 1}


def _line_after_build(store, line=None):
    """The Soon line after a build, a Repair or a re-import (L2.2 05 §5.1): `line` (a 3.0 copy's, or the store's own
    before a re-import) where the tiers agree with it — Current's first `line` rows are NOW, all of Current when it
    holds fewer; else re-derived from the tiers (NOW's count: an older Surasura's copy or edit, a migration). A library
    with nothing in Current starts at 25 (Q2-4). Inside the caller's transaction."""
    conn = store.conn
    now = conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'now'").fetchone()[0]
    current = now + conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'soon'").fetchone()[0]
    try:
        line = int(line) if line is not None else None
    except (TypeError, ValueError):
        line = None
    if line is not None and line >= 0 and min(line, current) == now:
        value = line
    elif current == 0:
        value = SOON_LINE_NEW
    else:
        value = now
    store._set_meta({"soon_line": value})
    return value


def _prove(store, norm):
    """Prove a migration before committing (§6.8 step 4): the copy exported from the new rows equals
    the normalised manifest entry for entry, and `schedule()` gives `resolve_found_files` the same
    paths and declared source types (a missing and a null source_type read alike)."""
    doc, _v, _d = store.export_snapshot()
    for tier in ANALYSED:
        phase = TIERS[tier][0]
        if doc["schedule"].get(phase) != norm.tiers[tier]:
            raise StoreError(f"migration proof failed: the copy's {phase} differs from the manifest")
    if norm.has_metadata and doc.get("metadata") != norm.metadata:
        raise StoreError("migration proof failed: metadata")
    for key, value in norm.schedule_extra.items():
        if doc["schedule"].get(key) != value:
            raise StoreError("migration proof failed: schedule keys")
    for key, value in norm.extra.items():
        if doc.get(key) != value:
            raise StoreError("migration proof failed: top-level keys")
    schedule = store.schedule()

    def declared(e):
        value = e.get("source_type")
        return value if isinstance(value, str) else None

    for tier in ANALYSED:
        phase = TIERS[tier][0]
        mine = [(e.get("physical_path", ""), declared(e)) for e in schedule[phase]]
        theirs = [(e.get("physical_path", ""), declared(e)) for e in norm.tiers[tier]]
        if mine != theirs:
            raise StoreError(f"migration proof failed: schedule() differs in {phase}")


def _report(user_files_dir, title, lines):
    """`User Files/<lang>/library_migration_report.txt`: what was normalised, the counts, the Graduated
    files imported and the pieces made."""
    try:
        os.makedirs(user_files_dir, exist_ok=True)
        path = os.path.join(user_files_dir, "library_migration_report.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{title}\n{_now()}\n\n" + "\n".join(lines) + "\n")
        return path
    except OSError:
        return None


def _app_version():
    try:
        from app import __version__
        return __version__
    except Exception:
        return "unknown"


def _record_failure(store, doc_sha, exc):
    """A small separate transaction: the schema's stands, so the record survives the rollback (§6.8 6)."""
    try:
        with store._writing():
            store._set_meta({"migration_failed": _dumps({"at": _now(), "error": f"{type(exc).__name__}: {exc}",
                                                        "manifest_sha": doc_sha, "app_version": _app_version()})})
    except Exception:
        pass


def _failure(store):
    raw = store._meta().get("migration_failed")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"app_version": None}


def _migrate(store, user_files_dir, doc, read_stat, from_folders_files=None):
    """A first migration (or a build from the folders): two transactions — the schema, then the rows —
    proved before the commit; `migrated_at` set last, so the store is ready only when it is whole."""
    data_dir = store.data_dir
    norm = normalise(doc)
    if from_folders_files is not None:
        for tier, rel, entry in from_folders_files:
            norm.tiers[tier].append(entry)
    image = _image_from_manifest(norm, data_dir)
    meta = _fresh_meta(uuid.uuid4().hex, 1, 1, analysed_current=_junban_current(user_files_dir))
    meta.update(_manifest_meta(norm))
    meta["last_export_stat"] = read_stat or ""
    with store._writing():
        _write_image(store, image, meta)
        _line_after_build(store)                               # an older version's list: the line at NOW's count
        if meta["analysed_order_version"]:
            store._set_meta({"analysed_order_version": 1})
        _prove(store, norm)
        store._set_meta({"migrated_at": _now()})
        store.conn.execute("DELETE FROM meta WHERE key = 'migration_failed'")
    counts = {t: len(norm.tiers[t]) for t in ANALYSED}
    lines = [f"Rows: NOW {counts['now']} · Soon {counts['soon']} · 6+ Months {counts['goal']}",
             f"Missing files (kept, restorable): {sum(1 for i in image['items'] if i['availability'] == 'missing')}",
             f"Graduated folder files imported: {len(image['imported'])}",
             f"Pieces made: {image['pieces']}", "", "Normalised:"] + (norm.report or ["nothing"])
    lines += [f"  imported: {rel}" for rel in image["imported"]]
    return _report(user_files_dir, "Library moved to the new store", lines)


def _rebuild(store, user_files_dir, doc, read_stat, keep_store_id=None):
    """No database here, but the copy carries `surasura_library` (a moved folder, a new PC), or our own
    copy is newer than this database: ids, extra state, the lists and the tables come back; a new
    store_id (unless keeping ours), `state_version` above the copy's, the copy's epoch + 1. A copy an
    older version edited is kept in the trash first, and its edit re-imported in the same transaction:
    a failure leaves no store, never a store that has recorded the edited file as its own (§6.8, I2)."""
    norm = normalise(doc)
    lib = norm.lib
    sha_ok = lib.get("content_sha") == content_sha(doc)
    if not sha_ok:
        backup_to_trash(manifest_path(user_files_dir))       # byte-verified; if it fails, stop (I2)
    image = _image_from_copy(norm, store.data_dir, by_records=not sha_ok)
    epoch = int((lib.get("meta") or {}).get("epoch", 1) or 1) + 1
    meta = _fresh_meta(keep_store_id or uuid.uuid4().hex, epoch, int(lib.get("version") or 0) + 1)
    meta.update(_manifest_meta(norm))
    meta.update(_copy_meta_block(lib))
    meta["last_export_stat"] = read_stat or ""
    with store._writing():
        if keep_store_id:
            for sql in ADDED_TABLES_SQL:                         # an added table this store may not have made yet
                store.conn.execute(sql)
            for name in ("anki_links", "pairings", "made_words", "made_lines", "placement_log", "trash", "exclusions",
                         "anki_changes", "gone", "items", "pieces", "works", "roots", "meta"):
                store.conn.execute(f"DELETE FROM {name}")
        _write_image(store, image, meta)
        _line_after_build(store, meta.get("soon_line"))       # a 3.0 copy's line, else its tiers'
        if not sha_ok:
            store.reimport(doc, read_stat, own=True)          # the size guard applies here too (Q4-8)
        store._set_meta({"migrated_at": _now()})
    return True


class _Item:
    __slots__ = ("id", "rel_path", "rel_key", "tier", "ord", "entry", "size", "mtime_ns", "availability",
                 "changed_in", "new_entry", "new_rel", "new_tier", "added", "fp")

    def __init__(self, row):
        (self.id, self.rel_path, self.rel_key, self.tier, self.ord, entry, self.size, self.mtime_ns,
         self.availability, self.changed_in) = row
        self.entry = entry
        self.new_entry = None
        self.new_rel = None
        self.new_tier = None
        self.added = False
        self.fp = None


def _lis_keep(old_order, new_order):
    """The items of `new_order` (present in both) inside the longest run the two orders share — a
    longest increasing subsequence of their old positions. The rest moved."""
    pos = {k: i for i, k in enumerate(old_order)}
    seq = [k for k in new_order if k in pos]
    import bisect
    tails, tails_idx, prev = [], [], {}
    for n, k in enumerate(seq):
        p = pos[k]
        j = bisect.bisect_left(tails, p)
        if j == len(tails):
            tails.append(p)
            tails_idx.append(n)
        else:
            tails[j] = p
            tails_idx[j] = n
        prev[n] = tails_idx[j - 1] if j else None
    keep = set()
    n = tails_idx[-1] if tails_idx else None
    while n is not None:
        keep.add(seq[n])
        n = prev[n]
    return keep


def _reimport_plan(store, norm):
    """Rules 1–5 of a re-import (§6.8) against the store as it stands: (items by key, new orders per
    tier, the moved/added/re-tiered keys, how many analysed items would move, the analysed total)."""
    conn = store.conn
    data_dir = store.data_dir
    items = {}
    order = {t: [] for t in TIERS}
    for row in conn.execute("SELECT id, rel_path, rel_key, tier, ord, entry, size, mtime_ns, availability, "
                            "changed_in FROM items ORDER BY ord, id"):
        it = _Item(row)
        items[it.rel_key] = it
        order[it.tier].append(it.rel_key)
    listed = {}
    for tier in ANALYSED:
        for entry in norm.tiers[tier]:
            key = path_key(entry["physical_path"])
            if key in items and items[key].tier == "graduated":
                continue                                           # rule 2: graduated items stay graduated
            listed[key] = (tier, entry)
    unlisted = [it for k, it in items.items() if k not in listed and it.tier != "graduated"]

    def gone(it):
        return not os.path.exists(os.path.join(data_dir, _strip(it.rel_path)))

    def inner(rel):
        parts = _strip(rel).split("/", 1)
        return parts[1] if len(parts) == 2 and parts[0] in TIER_OF_FOLDER else None

    by_dir, by_inner = {}, {}
    for it in unlisted:
        by_dir.setdefault(path_key(_rel_dir(_strip(it.rel_path))), []).append(it)
        if inner(it.rel_path):
            by_inner.setdefault(path_key(inner(it.rel_path)), []).append(it)
    renamed = {}
    for key, (tier, entry) in list(listed.items()):
        if key in items:
            continue
        rel = entry["physical_path"]
        size, mtime_ns, availability = _fingerprint(data_dir, rel)
        if availability != "available":
            continue
        cands = list(by_dir.get(path_key(_rel_dir(_strip(rel))), []))
        if inner(rel):
            cands += [c for c in by_inner.get(path_key(inner(rel)), []) if c not in cands]
        cands = [c for c in cands if c.rel_key not in renamed.values() and c.size == size and
                 c.mtime_ns == mtime_ns and gone(c)]
        if len(cands) == 1:                                        # rule 3: renames first
            c = cands[0]
            renamed[key] = c.rel_key
    for key, old_key in renamed.items():
        it = items.pop(old_key)
        it.new_rel = listed[key][1]["physical_path"]
        items[key] = it
        for tier in TIERS:
            order[tier] = [key if k == old_key else k for k in order[tier]]
    to_graduated = []
    for it in [i for i in items.values() if i.rel_key not in listed and i.tier != "graduated" and i.new_rel is None]:
        ins = inner(it.rel_path)
        if not ins or not gone(it):
            continue
        target = f"{GRADUATED_FOLDER}/{ins}"
        size, mtime_ns, availability = _fingerprint(data_dir, target)
        if availability == "available" and size == it.size and mtime_ns == it.mtime_ns and path_key(target) not in items:
            to_graduated.append((it, target))                      # rule 3: an older version's Graduate
    for it, target in to_graduated:
        old_key = it.rel_key
        it.new_rel = target
        it.new_tier = "graduated"
        new_key = path_key(target)
        items.pop(old_key)
        items[new_key] = it
        for tier in TIERS:
            order[tier] = [k for k in order[tier] if k != old_key]
        order["graduated"].append(new_key)
    new_order = {t: list(order[t]) for t in TIERS}
    for tier in ANALYSED:
        seq = [k for k, (t, _e) in listed.items() if t == tier]
        listed_here = set(seq)
        tops, after = [], {}
        last = None
        for k in order[tier]:
            if k in listed_here:
                last = k
            elif k not in listed and items[k].new_tier is None:
                (after.setdefault(last, []) if last else tops).append(k)   # rule 4
        final = list(tops)
        for k in seq:
            final.append(k)
            final += after.get(k, [])
        new_order[tier] = final
    for key in listed:
        tier, entry = listed[key]
        if key not in items:                                       # rule 5: new
            it = _Item((None, entry["physical_path"], key, tier, None, None, None, None, None, None))
            it.added = True
            it.fp = _fingerprint(data_dir, entry["physical_path"])
            items[key] = it
        it = items[key]
        if it.tier != tier and not it.added:
            it.new_tier = tier
        if it.entry is None or json.loads(it.entry) != entry:
            it.new_entry = entry
    for tier in ("graduated", "arrivals"):
        new_order[tier] = [k for k in new_order[tier] if k not in listed]
    moved = set()
    for key, it in items.items():
        if it.added or it.new_tier is not None:
            moved.add(key)
    count = sum(1 for k in moved if not items[k].added and items[k].tier in ANALYSED)
    for tier in TIERS:
        old = [k for k in order[tier] if k in items and items[k].new_tier is None]
        keep = _lis_keep(old, new_order[tier])
        for k in new_order[tier]:
            if k in items and not items[k].added and items[k].new_tier is None and k not in keep:
                moved.add(k)
                if tier in ANALYSED:
                    count += 1
    total = sum(1 for it in items.values() if it.tier in ANALYSED and not it.added)
    return items, new_order, moved, count, total


def _guard_trips(count, total):
    """Q4-8: more than 5 % of the analysed items (and at least 10) would move."""
    return count >= 10 and count > 0.05 * total


def _store_reimport(self, doc, read_stat, own=False, force=False):
    """Apply an outside change to the copy (§6.8 re-import rules 1–6) in one transaction. Returns
    'applied', 'unchanged' or 'pending' (the size guard: nothing applied, `reimport_pending` set).
    The store keeps its own ids and extra state either way (rule 6)."""
    norm = normalise(doc)
    with self._command("reimport", "sync") as cmd:
        items, new_order, moved, count, total = _reimport_plan(self, norm)
        dirty = any(it.added or it.new_tier or it.new_rel or it.new_entry for it in items.values()) or bool(moved)
        if not dirty:
            # Nothing to apply, yet the copy's content isn't the store's (a returning 2.4.0 put a graduated file
            # back in NOW: rule 2 keeps it graduated): the copy is written again from the store.
            self._set_meta({"last_export_stat": read_stat,
                            "copy_dirty": int(self._meta().get("copy_dirty") or 0) + 1})
            return "unchanged"
        if not force and _guard_trips(count, total):
            self._set_meta({"reimport_pending": _dumps({"stat": read_stat, "count": count, "total": total,
                                                        "at": _now()})})
            return "pending"
        root = self._root_id()
        now = _now()
        added = [it for it in items.values() if it.added]
        if added:
            seq = self.conn.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'items'), 0)").fetchone()[0]
            next_id = max(seq, self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM items").fetchone()[0]) + 1
            rows = []
            for it in added:
                it.id = next_id
                next_id += 1
                entry = it.new_entry
                title, folder, source_type = _columns(entry)
                size, mtime_ns, availability = it.fp
                it.availability = availability
                rows.append((it.id, root, it.rel_path, it.rel_key, it.tier, 0.0, _dumps(entry), title, folder,
                             source_type, availability, size, mtime_ns, cmd.version, now,
                             search_fold(title, self.language)))
            self.conn.executemany(
                "INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, "
                "source_type, availability, size, mtime_ns, changed_in, added_at, search_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        edits = []
        for it in items.values():
            if it.added:
                continue
            if it.new_rel is not None or it.new_entry is not None:
                entry = it.new_entry if it.new_entry is not None else json.loads(it.entry)
                if it.new_rel is not None and it.new_entry is None:
                    entry = dict(entry, physical_path=it.new_rel, title=it.new_rel.rsplit("/", 1)[-1])
                rel = it.new_rel if it.new_rel is not None else it.rel_path
                size, mtime_ns, availability = _fingerprint(self.data_dir, rel) if it.new_rel else \
                    (it.size, it.mtime_ns, it.availability)
                if it.new_rel and availability != it.availability:
                    cmd.touch(availability=True)
                title, folder, source_type = _columns(entry)
                edits.append((rel, path_key(rel), _dumps(entry), title, folder, source_type, size, mtime_ns,
                              availability, search_fold(title, self.language), it.id))
        if edits:
            self.conn.executemany("UPDATE items SET rel_path = ?, rel_key = ?, entry = ?, title = ?, parent_folder = ?, "
                                  "source_type = ?, size = ?, mtime_ns = ?, availability = ?, search_key = ? WHERE id = ?",
                                  edits)
            cmd.feed(e[-1] for e in edits)
        ords = dict(self.conn.execute("SELECT id, ord FROM items").fetchall())
        changed_tiers = set()
        for tier, keys in new_order.items():
            ids = [items[k].id for k in keys if k in items]
            placed = {items[k].id for k in keys if k in moved}
            if placed:
                changed_tiers.add(tier)
                plan = _plan_ords(ids, ords, placed)
                self.conn.executemany("UPDATE items SET tier = ?, ord = ?, changed_in = ? WHERE id = ?",
                                      [(tier, plan[i], cmd.version, i) for i in placed])
                cmd.moved.update(placed)
                cmd.feed(placed)
                others = [(k, cmd.version, i) for i, k in plan.items() if i not in placed]
                if others:                                     # re-spaced keys reach the windows too (§12.8)
                    self.conn.executemany("UPDATE items SET ord = ?, feed_in = ? WHERE id = ?", others)
        for it in items.values():
            if it.new_tier == "graduated":
                self.conn.execute("UPDATE items SET graduated_at = ? WHERE id = ?", (now, it.id))
        cmd.touch(changed_tiers | {it.tier for it in items.values() if it.new_entry is not None or it.new_rel})
        self._set_meta({"last_export_stat": read_stat,
                        "reimport_note": _dumps({"count": count, "total": total, "at": now})})
        self.conn.execute("DELETE FROM meta WHERE key = 'reimport_pending'")
        _line_after_build(self, cmd.meta.get("soon_line"))     # its tiers win (06 §6.1): the line follows them
        return "applied"


Store.reimport = _store_reimport


# ------------------------------------------------------------------------------------------------ #
# Writing the copy (§6.7): a unique temp, fsync, then the replace under the copy lock
# ------------------------------------------------------------------------------------------------ #

REPLACE_BACKOFF = (0.05, 0.1, 0.2, 0.4, 0.8)


def _copy_lock(db_path):
    return _FileLock(db_path + ".copylock", byte_range=True)


def replace_under_copy_lock(db_path, temp, target, expect=None, look=None):
    """Replace `target` with `temp` under the copy lock, held for the re-stat and the replace only.
    `expect` is the stat string the target must still have ('' = still absent); `look`, if given, is
    called instead to decide. A sharing violation releases the lock, waits 50…800 ms and starts again
    from the re-stat; after the last try the temp is kept and False returned."""
    lock = _copy_lock(db_path)
    try:
        for wait in REPLACE_BACKOFF + (None,):
            if not lock.acquire(LOCK_TIMEOUT, LOCK_RETRY):
                return False                                   # never replace unlocked; the temp is kept
            try:
                st = _stat(target)
                now = _stat_str(st) if st else ""
                ok = look(now) if look else (expect is None or now == expect)
                if not ok:
                    try:
                        os.remove(temp)
                    except OSError:
                        pass
                    return False
                try:
                    os.replace(temp, target)
                    return True
                except PermissionError:
                    pass
            finally:
                lock.release()
            if wait is None:
                return False
            time.sleep(wait)
    finally:
        lock.close()


def _write_temp(target, doc):
    temp = f"{target}.{os.getpid()}.{random.getrandbits(48):012x}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        st = os.fstat(f.fileno())
    return temp, _stat_str(st)


def json_mode_save(language, data_dir, user_files_dir, doc):
    """A 2.5 JSON-mode write of the manifest (the Content Manager's `save_manifest`, the preview's
    `commit_to_front`): today's write, its `os.replace` under the copy lock so it can't land between the
    helper's re-stat and its replace. With no lock file it saves without the lock (and says so)."""
    target = manifest_path(user_files_dir)
    os.makedirs(user_files_dir, exist_ok=True)
    temp, _st = _write_temp(target, doc)
    try:
        db_path = library_db_path(language, data_dir)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    except (OSError, StoreError):
        os.replace(temp, target)
        return "unlocked"
    return replace_under_copy_lock(db_path, temp, target, look=lambda _now: True)


def _cleanup_temps(target, max_age=3600.0):
    folder, base = os.path.split(target)
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.startswith(base + ".") and name.endswith(".tmp"):
            path = os.path.join(folder, name)
            try:
                if time.time() - os.path.getmtime(path) > max_age:
                    os.remove(path)
            except OSError:
                pass


def export_copy(store):
    """Step 3 of `maintain`: export if behind. Returns True when the copy was replaced."""
    target = manifest_path(store.user_files_dir)
    meta = store.meta()
    st = _stat(target)
    if (meta["state_version"] == meta.get("last_export_version") and not meta.get("copy_dirty")
            and st is not None and _stat_str(st) == meta.get("last_export_stat")):
        return False
    if meta.get("reimport_pending"):
        return False
    seen = _stat_str(st) if st else ""
    if st is not None and seen != meta.get("last_export_stat"):
        try:
            other, _s, _p = read_manifest(target)
        except ManifestUnreadable:
            return False
        lib = other.get("surasura_library") if other else None
        if copy_is_newer(other):
            return False                                           # a newer store's copy is never overwritten here
        if not (isinstance(lib, dict) and lib.get("store_id") == meta["store_id"]
                and isinstance(lib.get("version"), int) and lib["version"] < meta["state_version"]
                and lib.get("content_sha") == content_sha(other)):
            return False                                           # step 2 handled it, or asked
    doc, version, dirty = store.export_snapshot()
    finish_doc(doc)
    os.makedirs(store.user_files_dir, exist_ok=True)
    temp, temp_stat = _write_temp(target, doc)
    if not replace_under_copy_lock(store.db_path, temp, target, expect=seen):
        return False
    with store._writing():
        now_meta = store._meta()
        values = {"last_export_version": version, "last_export_stat": temp_stat}
        if now_meta.get("copy_dirty", 0) == dirty:
            values["copy_dirty"] = 0
        store._set_meta(values)
    return True


def _forget_newer_copy_seen(store):
    """The newer copy is gone or replaced: exports may resume (bookkeeping, no version moves)."""
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = 'newer_copy_seen'")


def _check_copy(store, retry_wait=1.0):
    """Step 2 of `maintain`: has the JSON changed without the store? Returns what was done."""
    target = manifest_path(store.user_files_dir)
    meta = store.meta()
    st = _stat(target)
    pending = meta.get("reimport_pending")
    if pending and st is not None and json.loads(pending).get("stat") == _stat_str(st):
        return "pending"                                       # a question is waiting for the user
    if st is None or _stat_str(st) == meta.get("last_export_stat"):
        if meta.get("newer_copy_seen") is not None:
            _forget_newer_copy_seen(store)
        return "same"
    if meta.get("newer_copy_seen") == _stat_str(st):
        return "newer"                                         # unchanged since we last read it: not again
    doc, read_stat, problem = read_manifest(target)
    if doc is None:
        time.sleep(retry_wait)                                     # a program halfway through saving it?
        doc, read_stat, problem = read_manifest(target)
        if doc is None:
            backup_to_trash(target, move=True)
            return "set aside"
    if copy_is_newer(doc):
        store.bookkeeping({"newer_copy_seen": read_stat})      # export_due stays quiet while it sits there
        return "newer"                     # never re-imported or rebuilt from here; export won't overwrite it either
    if meta.get("newer_copy_seen") is not None:
        _forget_newer_copy_seen(store)
    lib = doc.get("surasura_library")
    ours = isinstance(lib, dict) and lib.get("store_id") == meta["store_id"]
    if ours and lib.get("content_sha") == content_sha(doc):
        version = lib.get("version")
        if version in (meta.get("last_export_version"), meta["state_version"]):
            # Re-saved unchanged by another program, or a helper killed after its replace but before its
            # bookkeeping (its version is then the current state_version): adopt, never re-import, no loop.
            store.bookkeeping({"last_export_stat": read_stat, "last_export_version": version})
            return "adopted"
        if isinstance(version, int) and version > meta["state_version"]:
            _backup_db(store.conn, store.db_path)
            _rebuild(store, store.user_files_dir, doc, read_stat, keep_store_id=meta["store_id"])
            return "rebuilt"
        return "stale"
    if quick_check(store.conn, store.db_path) != "ok":
        return "damaged"
    try:
        _backup_db(store.conn, store.db_path)
        backup_to_trash(target)
    except OSError:
        return "backup failed"
    return store.reimport(doc, read_stat, own=ours)


def resolve_reimport(language, data_dir, user_files_dir, use_theirs):
    """The size guard's answer (Q4-8): "Use that order" applies the pending change; "Keep mine" keeps
    the store's order and lets the next export replace the file. Under the maintenance lock, as every
    builder (§6.8); "Use that order" applies only the file the question was about — saved again since,
    the question is dropped and the next `maintain` checks the file again, with its backups."""
    lock = MaintenanceLock(library_db_path(language, data_dir))
    if not lock.acquire(MAINT_WAIT, 0.01):
        lock.close()
        return False
    try:
        return _resolve_reimport(language, data_dir, user_files_dir, use_theirs)
    finally:
        lock.close()


def _resolve_reimport(language, data_dir, user_files_dir, use_theirs):
    store = open_store(language, data_dir, user_files_dir, role="helper")
    if store is None:
        return False
    with store:
        meta = store.meta()
        pending = meta.get("reimport_pending")
        if not pending:
            return False
        asked = json.loads(pending).get("stat")                # the file the question was about

        def drop():                                            # saved again since: the next run checks it again
            with store._writing():
                store.conn.execute("DELETE FROM meta WHERE key = 'reimport_pending'")
            return False
        if use_theirs:
            try:
                doc, read_stat, _p = read_manifest(manifest_path(user_files_dir))
            except ManifestUnreadable:
                return False
            if doc is None or read_stat != asked:
                return drop()
            lib = doc.get("surasura_library")
            store.reimport(doc, read_stat, own=isinstance(lib, dict) and lib.get("store_id") == meta["store_id"],
                           force=True)
        else:
            st = _stat(manifest_path(user_files_dir))
            if (_stat_str(st) if st else "") != asked:
                return drop()
            store.bookkeeping({"last_export_stat": asked, "copy_dirty": 1})
            with store._writing():
                store.conn.execute("DELETE FROM meta WHERE key = 'reimport_pending'")
    return True


# ------------------------------------------------------------------------------------------------ #
# The helper: maintain (§6.7)
# ------------------------------------------------------------------------------------------------ #

def _log(db_path, text):
    try:
        path = os.path.join(os.path.dirname(db_path), "library_maintain.log")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{_now()} [{os.getpid()}] {text}\n")
    except OSError:
        pass


def _db_state(db_path):
    """'missing' | 'empty' (schema, no migrated_at) | 'failed' | 'older' | 'newer' | 'ready'."""
    if not os.path.exists(db_path):
        return "missing"
    conn = _connect(db_path, "reader")
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            return "missing"
        if version > STORE_SCHEMA:
            return "newer"
        rows = dict(conn.execute("SELECT key, value FROM meta WHERE key IN ('migrated_at', 'migration_failed')"))
        if "migrated_at" in rows:
            return "older" if version < STORE_SCHEMA else "ready"
        return "failed" if "migration_failed" in rows else "empty"          # never built: a build, not an upgrade
    finally:
        conn.close()


def _build(db_path, language, data_dir, user_files_dir, from_folders, retry):
    """Step 1: build if needed. Returns an exit code, or None when a store is now ready."""
    target = manifest_path(user_files_dir)
    store = _helper_store(db_path, language, data_dir, user_files_dir)
    try:
        version = store.conn.execute("PRAGMA user_version").fetchone()[0]
        if version:
            if quick_check(store.conn, db_path) != "ok":
                return EXIT_NEEDS_YOU
        if 0 < version < STORE_SCHEMA:
            _upgrade(store)                                    # an older store never built: its tables brought up first
        _ensure_schema(store)
        failed = _failure(store)
        if failed and not retry and failed.get("app_version") == _app_version():
            return EXIT_NEEDS_YOU                                  # JSON mode until a new version or Try again
        doc = read_stat = None
        if os.path.exists(target):
            try:
                doc, read_stat, problem = read_manifest(target)
            except ManifestUnreadable:
                return EXIT_FAILED                                 # retried, never treated as damage
        newer = doc is not None and copy_is_newer(doc)
        if newer or store.meta().get("newer_copy") is not None:
            with store._writing():                                 # read-only on that copy until it's ours again
                if newer:
                    store._set_meta({"newer_copy": _dumps({"stat": read_stat, "at": _now()})})
                else:
                    store.conn.execute("DELETE FROM meta WHERE key = 'newer_copy'")
            if newer:
                return EXIT_NEEDS_YOU
        try:
            if doc is not None and isinstance(doc.get("surasura_library"), dict):
                _rebuild(store, user_files_dir, doc, read_stat)
            elif doc is not None:
                if not failed:
                    backup_to_trash(target)                        # byte-verified; if it fails, stop (I2)
                _migrate(store, user_files_dir, doc, read_stat)
            elif from_folders:
                if os.path.exists(target):
                    backup_to_trash(target, move=True)             # a damaged manifest set aside
                files = []
                for tier in ANALYSED:
                    folder = FOLDER_OF_TIER[tier]
                    walked, _bad = walk_tree(os.path.join(data_dir, folder), folder)
                    marker_cache = {}
                    entries = [make_entry(rel, "Disk Sync", _detect_source_type(os.path.join(data_dir, rel),
                                                                                marker_cache))
                               for rel, _s, _m in walked]
                    files += [(tier, e["physical_path"], e) for e in place_new_entries([], entries)]
                _migrate(store, user_files_dir, {"schedule": {}}, "", from_folders_files=files)
            else:
                return EXIT_NEEDS_YOU                              # waits for the Content Manager's helper
        except Exception as exc:
            sha = hashlib.sha256(_dumps(doc).encode("utf-8")).hexdigest() if doc is not None else None
            _record_failure(store, sha, exc)
            _log(db_path, f"build failed: {type(exc).__name__}: {exc}")
            return EXIT_NEEDS_YOU
        return None
    finally:
        store.close()


def maintain(language, data_dir=None, user_files_dir=None, from_folders=False, repair=False,
             check_integrity=False, export=True, retry=False, lock=None):
    """The helper (§6.7): under the maintenance lock, (1) build if needed, (2) check the copy for an
    outside change, (3) export if behind. Dialog-free; exits 0 did something · 3 nothing to do · 4 needs
    the user · 5 busy (another holder, or an update staged) · 1 failed. The analyzer runs steps 1–2
    in-process (`export=False`)."""
    from app.path_utils import get_data_path, get_user_files_path
    data_dir = data_dir or get_data_path(language)
    user_files_dir = user_files_dir or get_user_files_path(language)
    try:
        if update_staged():
            return EXIT_BUSY
        db_path = library_db_path(language, data_dir)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    except StoreError:
        return EXIT_FAILED
    own_lock = lock is None
    lock = lock or MaintenanceLock(db_path)
    try:
        if own_lock and not lock.acquire(MAINT_WAIT, 0.01):
            return EXIT_BUSY
        return _maintain_locked(db_path, language, data_dir, user_files_dir, from_folders, repair,
                                check_integrity, export, retry, lock)
    except Exception as exc:
        _log(db_path, f"failed: {type(exc).__name__}: {exc}")
        return EXIT_FAILED
    finally:
        if own_lock:
            lock.close()


def _maintain_locked(db_path, language, data_dir, user_files_dir, from_folders, repair, check_integrity,
                     export, retry, lock):
    if repair:
        return repair_store(db_path, language, data_dir, user_files_dir, lock)
    if os.path.exists(damaged_marker(db_path)):
        return EXIT_NEEDS_YOU
    did = False
    state = _db_state(db_path)
    if state == "newer":
        return EXIT_NEEDS_YOU
    if state in ("missing", "empty", "failed"):
        code = _build(db_path, language, data_dir, user_files_dir, from_folders, retry)
        if code is not None:
            return code
        did = True
    store = _helper_store(db_path, language, data_dir, user_files_dir)
    try:
        if state == "older":
            if quick_check(store.conn, db_path) != "ok":
                return EXIT_NEEDS_YOU
            try:
                did = _upgrade(store) or did
            except UpgradeFailed as exc:
                _log(db_path, f"upgrade failed: {exc}")
                return EXIT_NEEDS_YOU                          # schema 1 still; the next helper run tries again
        if check_integrity and not did:
            result = quick_check(store.conn, db_path)
            if result != "ok":
                return EXIT_NEEDS_YOU
        found = _check_copy(store)
        if found in ("pending", "damaged"):
            return EXIT_NEEDS_YOU
        if found == "backup failed":
            return EXIT_FAILED
        did = did or found not in ("same", "stale", "unchanged", "newer")
        if export:
            did = export_copy(store) or did
            _cleanup_temps(manifest_path(user_files_dir))
        if any(k.startswith("reader:") for k in store.meta()) or \
                store.conn.execute("SELECT 1 FROM placement_log LIMIT 1").fetchone():   # a reader off: rows age out
            did = bool(store.prune_log()) or did
        did = bool(store.prune_gone()) or did
        did = bool(store.tidy_works()) or did
        store.checkpoint()
        return EXIT_DONE if did else EXIT_NOTHING
    finally:
        store.close()


def spawn_maintain(language, *extra):
    """Start the helper detached and untracked (§6.7: not in `active_processes`, so closing the dashboard
    doesn't kill it), with the same arguments frozen and from source. Spawns nothing while an update is
    staged. Returns the Popen, or None."""
    import subprocess
    if update_staged():
        return None
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    return subprocess.Popen(_helper_args(language, "maintain", *extra), env=_helper_env(), creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=(sys.platform != "win32"))


def _helper_args(language, command, *extra):
    """The helper's command line, frozen (`Surasura.exe library_maintain <command> …`, app_entry's branch)
    or from source (`python app/library_store.py <command> …`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "library_maintain", command, "--language", language, *extra]
    return [sys.executable, os.path.abspath(__file__), command, "--language", language, *extra]


def _helper_env():
    from app.path_utils import build_subprocess_env
    return build_subprocess_env()


# ------------------------------------------------------------------------------------------------ #
# Disk sync and Reset (§6.10)
# ------------------------------------------------------------------------------------------------ #

def walk_library(data_dir):
    """The walk, outside any transaction: the three tier folders, content files only, fingerprints
    from the listing. Returns {"files": [(rel, size, mtime_ns)], "bad": [names that can't be encoded]}."""
    files, bad = [], []
    for tier in ANALYSED:
        folder = FOLDER_OF_TIER[tier]
        f, b = walk_tree(os.path.join(data_dir, folder), folder)
        files += f
        bad += b
    return {"files": files, "bad": bad}


def reset_walk(data_dir):
    """Today's Reset order: each folder listed, sorted by `name.lower()`, subfolders recursed where they
    fall, the three tier folders in turn."""
    out = []

    def level(directory, rel):
        try:
            names = [n for n in os.listdir(directory) if n not in SKIP_NAMES]
        except OSError:
            return
        names.sort(key=lambda x: x.lower())
        for name in names:
            path = os.path.join(directory, name)
            child = f"{rel}/{name}"
            if os.path.isdir(path):
                level(path, child)
            elif is_content_name(name):
                try:
                    child.encode("utf-8")
                except UnicodeEncodeError:
                    continue
                out.append(child)

    for tier in ANALYSED:
        folder = FOLDER_OF_TIER[tier]
        level(os.path.join(data_dir, folder), folder)
    return out


def _known(store, scope=None):
    """{key: (id, rel_path, tier, availability, size, mtime_ns)} and state_version, in one read; with `scope` (folders
    relative to data/<lang>), only the items under them (the `items_key` index: no scan of the library)."""
    with store._reading():
        if scope is None:
            rows = store.conn.execute("SELECT rel_key, id, rel_path, tier, availability, size, mtime_ns FROM items").fetchall()
        else:
            rows = []
            for top in _scope_tops(scope):
                rows += store.conn.execute("SELECT rel_key, id, rel_path, tier, availability, size, mtime_ns FROM items "
                                           "WHERE rel_key > ? AND rel_key < ?", (top, top[:-1] + "0")).fetchall()
        version = store._meta()["state_version"]
    return {r[0]: r[1:] for r in rows}, version


def _scope_tops(folders):
    """The scope's key prefixes ('highpriority/frieren/'), a folder inside another listed one dropped."""
    tops = sorted({path_key(_strip(f).rstrip("/")) + "/" for f in folders if f and _strip(f).strip("/")})
    return [t for n, t in enumerate(tops) if not any(t.startswith(o) for o in tops[:n])]


def walk_folders(data_dir, folders):
    """The walk of a scoped sync: each folder (relative to data/<lang>) and everything under it, content files only,
    as `walk_library` lists them; a folder gone is an empty walk (its items go missing)."""
    files, bad = [], []
    by_top = {path_key(_strip(f).rstrip("/")) + "/": _strip(f).rstrip("/") for f in folders if f}
    for top in _scope_tops(folders):
        folder = by_top[top]
        f, b = walk_tree(os.path.join(data_dir, *folder.split("/")), folder)
        files += f
        bad += b
    return {"files": files, "bad": bad}


def _sync_delta(store, walk, known, scope=None):
    """What a sync would change, computed outside any transaction (§6.10); with `scope`, only within those folders
    (`known` read with the same scope): an item outside them is never looked at."""
    data_dir = store.data_dir
    walked_tops = _scope_tops(scope) if scope is not None else [path_key(FOLDER_OF_TIER[t]) + "/" for t in ANALYSED]
    seen, fresh, respell, refresh = set(), [], [], []
    for rel, size, mtime_ns in walk["files"]:
        key = path_key(rel)
        seen.add(key)
        k = known.get(key)
        if k is None:
            fresh.append((rel, key, size, mtime_ns))
            continue
        item_id, stored, _tier, availability, s, m = k
        if stored != rel:
            respell.append((item_id, rel))                         # rule 1: a case-only rename
        if (s, m) != (size, mtime_ns):
            refresh.append((size, mtime_ns, item_id))
    went, came = [], []
    for key, (item_id, rel, tier, availability, size, mtime_ns) in known.items():
        under = any(key.startswith(top) for top in walked_tops)
        if under:
            present = key in seen
        else:
            present = os.path.exists(os.path.join(data_dir, _strip(rel)))
        if availability == "available" and not present:
            went.append(item_id)
        elif availability == "missing" and present:
            came.append(item_id)
    # rule 2: a rename = an untracked file + exactly one known item in the same folder, same size and
    # modified time, that went missing since the last sync
    went_set = set(went)
    by_dir = {}
    for key, (item_id, rel, tier, availability, size, mtime_ns) in known.items():
        if item_id in went_set:
            by_dir.setdefault(path_key(_rel_dir(_strip(rel))), []).append((item_id, size, mtime_ns))
    renames, new, used = [], [], set()
    for rel, key, size, mtime_ns in fresh:
        cands = [c for c in by_dir.get(path_key(_rel_dir(rel)), []) if c[1] == size and c[2] == mtime_ns]
        if len(cands) == 1 and cands[0][0] not in used:
            used.add(cands[0][0])
            renames.append((cands[0][0], rel, size, mtime_ns))
        else:
            new.append((rel, key, size, mtime_ns))
    # rule 2b (9a, L2.2 05 §5.9): an untracked file + exactly ONE item anywhere in the library with the same file
    # name, size and modified time that went missing in this sync is that item, moved; two or more are asked, never
    # guessed (the file is held out until the user answers: `relink` or `its_new`)
    asked = {path_key(a.get("rel", "")) for a in _rename_asks(store)}
    by_name = {}
    for key, (item_id, rel, tier, availability, size, mtime_ns) in known.items():
        if item_id in went_set and item_id not in used:
            by_name.setdefault(path_key(_strip(rel).rsplit("/", 1)[-1]), []).append((item_id, size, mtime_ns))
    still, asks = [], []
    for rel, key, size, mtime_ns in new:
        if key in asked:
            continue                                               # held out: its question waits for the user
        cands = [c for c in by_name.get(path_key(rel.rsplit("/", 1)[-1]), [])
                 if c[1] == size and c[2] == mtime_ns and c[0] not in used]
        if len(cands) == 1:
            used.add(cands[0][0])
            renames.append((cands[0][0], rel, size, mtime_ns))
        elif cands:
            asks.append({"rel": rel, "size": size, "mtime_ns": mtime_ns, "candidates": sorted(c[0] for c in cands)})
        else:
            still.append((rel, key, size, mtime_ns))
    went = [i for i in went if i not in used]
    return {"new": still, "renames": renames, "respell": respell, "went": went, "came": came, "refresh": refresh,
            "asks": asks}


def _rename_asks(store):
    """9a's open questions (`meta.rename_asks`): [{rel, size, mtime_ns, candidates}], bookkeeping the copy carries."""
    row = store.conn.execute("SELECT value FROM meta WHERE key = 'rename_asks'").fetchone()
    try:
        asks = json.loads(row[0]) if row else []
    except ValueError:
        return []
    return [a for a in asks if isinstance(a, dict)] if isinstance(asks, list) else []


def _store_walk(self):
    return walk_library(self.data_dir)


def _store_sync_disk(self, walk=None, folders=None):
    """The disk sync (§6.10): files nothing tracks join the library by rule 3; renames keep their place;
    missing files are marked, never removed. No delta → no write lock, no commit. Returns a summary
    {"added", "renamed", "missing", "back", "bad"} or None when nothing changed. `folders`: only those folders
    (relative to data/<lang>) and what is under them — the ones the window's poll saw change (`DiskPoll.changed`,
    L3.1: a hato drop costs its folder's walk, not the library's)."""
    scope = list(folders) if folders else None
    walk = walk or (walk_folders(self.data_dir, scope) if scope else walk_library(self.data_dir))
    known, version = _known(self, scope)
    delta = _sync_delta(self, walk, known, scope)
    if scope and delta["went"]:
        # 9a: a file gone from a polled folder may have moved to a folder the poll can't see (one holding no item):
        # the whole library is looked at in this same check, so the move is followed (the intent review #5)
        scope, walk = None, walk_library(self.data_dir)
        known, version = _known(self, None)
        delta = _sync_delta(self, walk, known, None)
    asks = _rename_asks(self)
    live = [a for a in asks if os.path.exists(os.path.join(self.data_dir, _strip(str(a.get("rel", "")))))]
    if live != asks:                                       # a held-out file gone: its question goes with it
        with self._writing():
            self._set_meta({"rename_asks": _dumps(live), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})
    structural = delta["new"] or delta["renames"] or delta["respell"] or delta["went"] or delta["came"] or \
        delta["asks"]
    if not structural:
        if delta["refresh"]:
            with self._writing():                                  # bookkeeping the copy carries (§6.6)
                self.conn.executemany("UPDATE items SET size = ?, mtime_ns = ? WHERE id = ?", delta["refresh"])
                self._set_meta({"copy_dirty": self._meta().get("copy_dirty", 0) + 1})
        return None
    marker_cache = {}
    entries = {rel: make_entry(rel, "Disk Sync", _detect_source_type(os.path.join(self.data_dir, rel), marker_cache))
               for rel, _k, _s, _m in delta["new"]}
    with self._command("sync", "sync") as cmd:
        if cmd.meta["state_version"] != version:
            known, _v = _known(self, scope)
            delta = _sync_delta(self, walk, known, scope)
            for rel, _k, _s, _m in delta["new"]:
                if rel not in entries:
                    entries[rel] = make_entry(rel, "Disk Sync", _detect_source_type(os.path.join(self.data_dir, rel),
                                                                                     marker_cache))
        summary = {"added": [], "renamed": [], "missing": [], "back": [], "bad": list(walk.get("bad", [])),
                   "asked": [a["rel"] for a in delta["asks"]]}
        if delta["asks"]:                                      # bookkeeping the copy carries (9a)
            have = _rename_asks(self)
            keys = {path_key(a["rel"]) for a in have}
            self._set_meta({"rename_asks": _dumps(have + [a for a in delta["asks"] if path_key(a["rel"]) not in keys]),
                            "copy_dirty": self._meta().get("copy_dirty", 0) + 1})
        exists = lambda rel: os.path.exists(os.path.join(self.data_dir, _strip(rel)))
        rows = self._rows([r[0] for r in delta["renames"]] + [r[0] for r in delta["respell"]] + delta["went"] + delta["came"])
        tiers = set()
        for item_id, rel, size, mtime_ns in delta["renames"]:
            if not exists(rel) or exists(rows[item_id][5]) or self.conn.execute(
                    "SELECT 1 FROM items WHERE rel_key = ?", (path_key(rel),)).fetchone():
                continue                                           # a stale walk: leave it to the next sync
            self._repoint(item_id, rel, size, mtime_ns)
            tiers.add(rows[item_id][1])
            summary["renamed"].append(item_id)
        for item_id, rel in delta["respell"]:
            if exists(rel):
                self._repoint(item_id, rel)
                tiers.add(rows[item_id][1])
                summary["renamed"].append(item_id)
        gone = [i for i in delta["went"] if i in rows and not exists(rows[i][5])]
        back = [i for i in delta["came"] if i in rows and exists(rows[i][5])]
        if gone:
            self.conn.executemany("UPDATE items SET availability = 'missing' WHERE id = ?", [(i,) for i in gone])
        if back:
            self.conn.executemany("UPDATE items SET availability = 'available' WHERE id = ?", [(i,) for i in back])
        cmd.feed(gone + back)
        if gone or back:
            cmd.touch({rows[i][1] for i in gone + back}, availability=True)
        summary["missing"], summary["back"] = gone, back
        if delta["refresh"]:
            self.conn.executemany("UPDATE items SET size = ?, mtime_ns = ? WHERE id = ?", delta["refresh"])
            self._set_meta({"copy_dirty": self._meta().get("copy_dirty", 0) + 1})
        new = [(rel, key, size, mtime_ns) for rel, key, size, mtime_ns in delta["new"]
               if exists(rel) and not self.conn.execute("SELECT 1 FROM items WHERE rel_key = ?", (key,)).fetchone()]
        if new:
            prepared = [(rel, rel, key, entries[rel], (size, mtime_ns, "available")) for rel, key, size, mtime_ns in new]
            arrivals = cmd.meta.get("arrivals_on")
            dests = [("end", "arrivals") if arrivals and _in_hato(rel) else
                     self._destination(rel, entries[rel], TIER_OF_FOLDER.get(rel.split("/", 1)[0], "now"), set())
                     for rel, _k, _s, _m in new]
            dest_tier = [d[2] if d[0] in ("after", "before") else d[1] for d in dests]
            ids = self._add_rows([p + (t,) for p, t in zip(prepared, dest_tier)], cmd.version)
            groups = {}
            for item_id, dest, t in zip(ids, dests, dest_tier):
                where = (dest[0], dest[1]) if dest[0] in ("after", "before") else (dest[0],)
                groups.setdefault((t, where), []).append(item_id)
            for (t, where), group in groups.items():
                self._put(t, group, where, cmd.version)
            tiers |= set(dest_tier)
            summary["added"] = ids
            # K82, ✅ L3.1 call b: a hato drop waits in New arrivals by no rule; only hato's hand-off (`register`,
            # which knows the show) applies the placing rules, and a drop whose hand-off never comes waits there.
        if tiers:
            cmd.touch(tiers)
        if not (summary["added"] or summary["renamed"] or gone or back or summary["asked"]):
            if delta["refresh"]:
                cmd.changed = False
            return None
        return summary


def _repoint(self, item_id, rel, size=None, mtime_ns=None):
    """A rename or a re-spelling: `rel_path`, `rel_key`, the entry's `physical_path` / `title` and the
    columns updated in place; the item keeps its id, place and state."""
    entry = json.loads(self.conn.execute("SELECT entry FROM items WHERE id = ?", (item_id,)).fetchone()[0])
    entry["physical_path"] = rel
    entry["title"] = rel.rsplit("/", 1)[-1]
    title, folder, source_type = _columns(entry)
    sets = ("rel_path = ?, rel_key = ?, entry = ?, title = ?, parent_folder = ?, source_type = ?, search_key = ?, "
            "availability = 'available'")
    params = [rel, path_key(rel), _dumps(entry), title, folder, source_type, search_fold(title, self.language)]
    if size is not None:
        sets += ", size = ?, mtime_ns = ?"
        params += [size, mtime_ns]
    self.conn.execute(f"UPDATE items SET {sets} WHERE id = ?", params + [item_id])
    if self._cmd is not None:
        self._cmd.feed([item_id])


def _store_reset_order(self, walk=None):
    """Reset (R-1, D25): re-sort within each item's CURRENT tier in today's Reset order; tiers, ids and
    extra state kept; untracked files join as `Reset` entries in their folder's tier; items whose file
    is gone go to their tier's end, still marked missing. Never moves a file. Undoable: Undo puts back
    exactly the order it replaced."""
    order = walk if walk is not None else reset_walk(self.data_dir)
    pos = {path_key(rel): n for n, rel in enumerate(order)}
    with self._command("reset", "sync") as cmd:
        change = self._change(cmd, "reset")
        rows = self.conn.execute("SELECT id, rel_key, tier, ord, changed_in, rel_path, availability "
                                 "FROM items WHERE tier IN ('now', 'soon', 'goal') ORDER BY ord, id").fetchall()
        known = {r[0] for r in self.conn.execute("SELECT rel_key FROM items")}
        known |= {path_key(str(a.get("rel", ""))) for a in _rename_asks(self)}       # held out: the question waits
        arrivals = cmd.meta.get("arrivals_on")
        untracked = [rel for rel in order if path_key(rel) not in known and not (arrivals and _in_hato(rel))]
        prepared = [(rel, rel, path_key(rel), make_entry(rel, "Reset", with_source_type=False),
                     _fingerprint(self.data_dir, rel), TIER_OF_FOLDER[rel.split("/", 1)[0]]) for rel in untracked]
        new_ids = self._add_rows(prepared, cmd.version) if prepared else []
        seqs, ords = {}, {}
        moved = set()
        for tier in ANALYSED:
            here = [r for r in rows if r[2] == tier]
            fresh = [(i, p) for i, p in zip(new_ids, prepared) if p[5] == tier]
            present = sorted([(pos[r[1]], r[0]) for r in here if r[1] in pos] +
                             [(pos[p[2]], i) for i, p in fresh])
            gone = [r[0] for r in here if r[1] not in pos]
            final = [i for _p, i in present] + gone
            old = [r[0] for r in here]
            keep = _lis_keep(old, final)
            ords.update({r[0]: r[3] for r in here})
            moved |= {i for i in final if i not in keep}
            seqs[tier] = _Seq(final)
        moved_old = [r for r in rows if r[0] in moved]
        if not moved_old and not new_ids:
            return None
        self._before(change, [r[:1] + (r[2], r[3], r[4]) + (None,) * 4 + (None,) for r in moved_old])
        self._write_seqs(seqs, ords, moved, lambda i: cmd.version)
        change.added = new_ids
        cmd.touch(ANALYSED)
        return change


def _store_undo_reset(self, cmd, change):
    out, skipped = self._replace(cmd, change)
    if change.added:                                           # the untracked files Reset added go back out
        rows = self._rows(change.added)
        ok = [i for i in change.added if i in rows and rows[i][3] == change.version]
        skipped = list(skipped) + [i for i in change.added if i not in ok]
        if ok:
            self._remove_as(ok, None, 0)
    return out, skipped


def _store_folders(self):
    """Every folder that holds items (the tier folders, the Hato folder, each show's directory), as paths
    relative to data/<lang>: what the poll stats."""
    folders = {FOLDER_OF_TIER[t] for t in ANALYSED} | {HATO_FOLDER}
    for (rel,) in self.conn.execute("SELECT rel_path FROM items WHERE tier IN ('now', 'soon', 'goal')"):
        folders.add(_rel_dir(_strip(rel)))
    folders.discard("")
    return sorted(folders)


class DiskPoll:
    """The Content Manager's slow look (§6.10, G5; L3.2: only with no watch — not Windows, a drive that can't report,
    no bell — every `library_watch.SLOW_S` while the window is in front), run on its worker: one versions read, and a
    stat of every folder that holds items — a file dropped into a show's folder, or a new sub-folder (it changes
    its parent's modified time), is seen. `check()` answers "run a sync?"; the folder list is re-read only
    when the versions move. A drop into an existing folder that holds no item waits for focus, Refresh or the round."""

    def __init__(self, store):
        self.store = store
        self.token = None
        self.folders = []
        self.stats = None
        self.changed = []                # the folders whose modified time moved at the last check: `sync_disk(folders=)`

    def check(self):
        with self.store._reading():
            meta = self.store._meta()
        token = (meta["epoch"], meta["order_version"], meta["availability_version"])
        if token != self.token:
            self.folders = self.store.folders()
            self.token = token
        stats = {}
        for folder in self.folders:
            try:
                stats[folder] = os.stat(os.path.join(self.store.data_dir, folder)).st_mtime_ns
            except OSError:
                stats[folder] = None
        self.changed = [f for f, v in stats.items() if self.stats is not None and f in self.stats and self.stats[f] != v]
        self.stats = stats
        return bool(self.changed)


ROUND_FOLDERS = 200              # the hourly round (L3.2): at most this many folders a batch,
ROUND_BATCH_S = 0.05             # or this long, whichever comes first (one batch every 2 s: `library_watch.ROUND_GAP_S`)


class Round:
    """The hourly safety round (L3.2; the user's L3.1-4, "let windows handle it but with the fallback"): every folder
    under the tier folders — folders that hold no item included, which the old poll never looked at — listed a batch
    at a time (`step`), each folder's content files compared with the items the store holds directly in it.
    Listings, sizes and times only; a folder whose listing differs is handed back for a scoped sync. Nothing is kept
    between rounds: one a close interrupts starts over (the next open's full look covers it)."""

    def __init__(self, store):
        from collections import deque
        self.store = store
        self.queue = deque(FOLDER_OF_TIER[t] for t in ANALYSED)
        self.listed = 0                  # folders listed so far
        self.batches = []                # (folders, seconds) of each batch, for the figures

    @property
    def done(self):
        return not self.queue

    def step(self, max_folders=ROUND_FOLDERS, max_s=ROUND_BATCH_S, clock=time.perf_counter):
        """One batch: -> the folders (relative to data/<lang>) whose content differs from the store."""
        t0 = clock()
        differ, n = [], 0
        while self.queue and n < max_folders and (n == 0 or clock() - t0 < max_s):
            rel = self.queue.popleft()
            n += 1
            files, subdirs = self._listing(rel)
            self.queue.extendleft(reversed(subdirs))       # top-down, as the sync walks
            held, gone = self._held(rel, subdirs)
            # a sub-folder the store holds items in that is gone from disk is never listed itself: its parent differs
            # (one scoped sync of the parent: a folder renamed there is found as the same items, moved)
            if files != held or gone:
                differ.append(rel)
        self.listed += n
        self.batches.append((n, clock() - t0))
        return differ

    def _listing(self, rel):
        """{key: (size, mtime_ns)} of the content files directly in `rel`, and its sub-folders; a folder gone lists
        nothing (its items, if any, differ)."""
        files, subdirs = {}, []
        try:
            entries = list(os.scandir(os.path.join(self.store.data_dir, *rel.split("/"))))
        except OSError:
            return files, subdirs
        for e in entries:
            if e.name in SKIP_NAMES:
                continue
            child = f"{rel}/{e.name}"
            try:
                child.encode("utf-8")
                if e.is_dir():
                    subdirs.append(child)
                elif is_content_name(e.name):
                    st = e.stat()
                    files[path_key(child)] = (st.st_size, st.st_mtime_ns)
            except (OSError, UnicodeEncodeError):
                continue                                   # a name the sync can't take either (K28)
        return files, subdirs

    def _held(self, rel, subdirs=()):
        """({key: (size, mtime_ns)} of the available items directly in `rel`, [the sub-folders of `rel` (keys) that hold
        available items and aren't among `subdirs`, the ones on disk]). One walk of the `items_key` index inside
        SQLite: a seek per file and per sub-folder, never the range's rows (a tier folder at 200k: 9k sub-folders,
        ~0.1 s, the grouped range read 0.19 s), and only the gone sub-folders come back to Python (usually none), so
        the window's thread barely waits on this thread meanwhile."""
        prefix = path_key(rel) + "/"
        on_disk = json.dumps(sorted(path_key(d) for d in subdirs), ensure_ascii=False)
        with self.store._reading():
            rows = self.store.conn.execute(_HELD_WALK, {"p": prefix, "hi": prefix[:-1] + "0",       # '0' follows '/'
                                                        "n": len(prefix) + 1, "disk": on_disk}).fetchall()
        files, gone = {}, []
        for key, head, size, mtime_ns in rows:
            if head is None:
                files[key] = (size, mtime_ns)
            else:
                gone.append(head)
        return files, gone


# The round's walk of a folder's keys (`Round._held`): each step seeks the next available key past the last file, or
# past the whole sub-folder the last key was in (its keys run from 'show/' to 'show0': '0' follows '/'); a file comes
# back with its size and time, a sub-folder only when it isn't on disk (`:disk`, a JSON list of keys).
_HELD_WALK = """
WITH RECURSIVE w(k) AS (
  SELECT (SELECT min(rel_key) FROM items WHERE rel_key > :p AND rel_key < :hi AND availability = 'available')
  UNION ALL
  SELECT (SELECT min(rel_key) FROM items WHERE rel_key < :hi AND availability = 'available' AND rel_key >=
            CASE WHEN instr(substr(w.k, :n), '/') = 0 THEN w.k || char(1)
                 ELSE substr(w.k, 1, :n + instr(substr(w.k, :n), '/') - 2) || '0' END)
  FROM w WHERE w.k IS NOT NULL
),
heads(k, head) AS (
  SELECT k, CASE WHEN instr(substr(k, :n), '/') = 0 THEN NULL
                 ELSE substr(k, 1, :n + instr(substr(k, :n), '/') - 2) END FROM w WHERE k IS NOT NULL
)
SELECT h.k, h.head, i.size, i.mtime_ns FROM heads h JOIN items i ON i.rel_key = h.k AND i.availability = 'available'
WHERE h.head IS NULL OR h.head NOT IN (SELECT value FROM json_each(:disk))
"""


def _store_has_content(self):
    """Does an analysed tier hold a file that is there? (The dashboard's Generate button, §7.)"""
    return self.conn.execute("SELECT EXISTS (SELECT 1 FROM items WHERE tier IN ('now', 'soon', 'goal') "
                             "AND availability = 'available')").fetchone()[0] == 1


def _store_export_due(self):
    """Has the store something the copy lacks (the trigger rule, §6.7)? Read cheaply, no file I/O."""
    with self._reading():
        meta = self._meta()
    if meta.get("newer_copy_seen") is not None:
        return False                       # a newer store's copy sits there: nothing may be exported over it
    return meta["state_version"] != meta.get("last_export_version") or bool(meta.get("copy_dirty"))


def _store_copy_stat(self):
    """The copy's stat as `last_export_stat` records it, '' when there is no copy."""
    st = _stat(manifest_path(self.user_files_dir))
    return _stat_str(st) if st else ""


def maintain_due(store, handed=""):
    """A window's trigger rule (§6.7): spawn the helper only when it has something to do — a change since the
    last export, or a copy someone else rewrote whose stat this process hasn't already handed to a helper
    (`handed`). Returns (due, the copy's stat)."""
    seen = store.copy_stat()
    meta = store.meta()
    if meta.get("reimport_pending"):
        return False, seen                       # the helper would only wait for the same answer (exit 4)
    newer = meta.get("newer_copy_seen")
    if newer is not None:                        # a newer store's copy: due only once it changes or goes
        return seen != newer and (not seen or seen != handed), seen     # gone ("") is always due
    if store.export_due():
        return True, seen
    return bool(seen) and seen != store.meta().get("last_export_stat") and seen != handed, seen


def maintain_at_close(language, data_dir=None, user_files_dir=None):
    """The close trigger (§6.7), in-process once no window is left to freeze: `maintain` for a ready store with
    something to do. Never waits: a helper holding the maintenance lock is doing it already. Returns the exit
    code, or None when nothing ran."""
    from app.path_utils import get_data_path, get_user_files_path
    data_dir = data_dir or get_data_path(language)
    user_files_dir = user_files_dir or get_user_files_path(language)
    store = open_store(language, data_dir, user_files_dir, role="window", busy_wait=0.0)
    if store is None:
        return None
    with store:
        due, _seen = maintain_due(store)
    if not due:
        return None
    lock = MaintenanceLock(library_db_path(language, data_dir))
    try:
        if not lock.try_acquire():
            return EXIT_BUSY
        return maintain(language, data_dir, user_files_dir, lock=lock)
    finally:
        lock.close()


def read_only_schedule(language, data_dir, user_files_dir):
    """Read-only mode (§6.9): the copy's schedule, with the walk's untracked files added in memory by
    §6.10 rule 3 (never saved), so a file dropped into a tier folder is still analysed. Every file the
    copy knows, in any tier, counts as known (D6). None when the copy can't be read."""
    try:
        doc, _st, _p = read_manifest(manifest_path(user_files_dir))
    except ManifestUnreadable:
        return None
    if not doc:
        return None
    schedule = {k: (list(v) if isinstance(v, list) else v) for k, v in (doc.get("schedule") or {}).items()}
    lists = {t: schedule.setdefault(TIERS[t][0], []) for t in ANALYSED}
    lib = doc.get("surasura_library") if isinstance(doc.get("surasura_library"), dict) else {}
    held = [e for t in ANALYSED for e in lists[t] if isinstance(e, dict)]
    others = [e for key in ("graduated", "arrivals") for e in (lib.get(key) or []) if isinstance(e, dict)]
    try:                                                   # a 3.0 copy's switch: a hato drop waits (K82)
        waits = int(lib.get("store_schema") or 0) >= 2 and bool((lib.get("meta") or {}).get("arrivals_on"))
    except (TypeError, ValueError, AttributeError):
        waits = False
    known = {path_key(_strip(str(e.get("physical_path") or ""))) for e in held + others}
    with_items = {path_key(_rel_dir(_strip(str(e.get("physical_path") or "")))) for e in held + others}
    tops = {t: 0 for t in ANALYSED}
    marker_cache = {}
    hato = path_key(HATO_FOLDER)
    for rel, _size, _mtime in walk_library(data_dir)["files"]:
        key = path_key(rel)
        if key in known:
            continue
        known.add(key)
        entry = make_entry(rel, "Disk Sync", _detect_source_type(os.path.join(data_dir, rel), marker_cache))
        folder_dir = _rel_dir(rel)
        dkey = path_key(folder_dir)

        def show_last(tier):
            found = [n for n, e in enumerate(lists[tier]) if isinstance(e, dict)
                     and path_key(_rel_dir(_strip(str(e.get("physical_path") or "")))) == dkey]
            return found[-1] if found else None
        if dkey == hato or dkey.startswith(hato + "/"):
            if waits:
                continue                                   # in New arrivals, as the store files it: never analysed
            where = ("top", "now")
        elif folder_dir in TIER_OF_FOLDER:
            where = ("top", TIER_OF_FOLDER[folder_dir])
        elif dkey in with_items:
            where = ("top", "now")
            for tier in ("soon", "now"):
                last = show_last(tier)
                if last is not None:
                    where = ("after", tier, last)
                    break
        else:
            tier = TIER_OF_FOLDER.get(rel.split("/", 1)[0], "now")
            folder = _entry_folder(entry)
            last = max((n for n, e in enumerate(lists[tier]) if folder and _entry_folder(e) == folder), default=None)
            where = ("after", tier, last) if last is not None else ("top", tier)
        if where[0] == "top":
            lists[where[1]].insert(tops[where[1]], entry)
            tops[where[1]] += 1
        else:
            lists[where[1]].insert(where[2] + 1, entry)
            if where[2] < tops[where[1]]:
                tops[where[1]] += 1
        with_items.add(dkey)
    return schedule


SYNC_IN_PROCESS_AT = 20_000      # items: from here a window's process syncs in a process of its own (§12.1)
SYNC_TIMEOUT = 120.0
BUILD_SPAWN_EVERY = 60.0          # s: "no store yet" spawns the builder at most this often per language
_build_spawned = {}


def sync_for_window(store, folders=None):
    """`sync_disk` for a window's process (the dashboard's journey check, the Content Manager), called on a
    worker. At 100k a sync on a worker thread still stalled the window 20–60 ms through the interpreter
    lock, whatever the switch interval (§12.1), so from `SYNC_IN_PROCESS_AT` items the sync runs in a
    process of its own and this thread only waits for it. Returns sync_disk's summary (in-process) or None."""
    count = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if count < SYNC_IN_PROCESS_AT:
        return store.sync_disk(folders=folders)
    import subprocess
    args = _helper_args(store.language, "sync") + [a for f in (folders or ()) for a in ("--folder", f)]
    flags = 0x08000000 if sys.platform == "win32" else 0                # CREATE_NO_WINDOW
    subprocess.run(args, env=_helper_env(), creationflags=flags, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=SYNC_TIMEOUT)
    return None


def read_only_view(language, data_dir, user_files_dir):
    """The store as a caller that must write nothing sees it (surasura-cli `status`, P1.2): opened `mode=ro` — never
    built, synced, repaired, re-derived or marked damaged — and read in one transaction. -> (mode, schedule, versions,
    pending):

      * ("store", schedule, versions, pending): a ready store, its analysed tiers as `Store.schedule` reads them;
        `pending` is True when the disk holds a change its last sync hasn't taken in (a file dropped in since,
        renamed or gone): the walk a sync would make, its delta computed and never applied;
      * ("json", None, None, False): no ready store — the file is the list, as every reader takes it;
      * ("unknown", None, None, False): a store that can't be read this way now (damaged, made by a newer Surasura,
        busy, an I/O error).

    The disk is walked first, then the schedule, the versions and the rows the delta compares are read in one
    transaction: a sync committing in between is in all three or in none, so `pending` and the schedule always
    describe the same state."""
    db_path = library_db_path(language, data_dir)
    if not os.path.exists(db_path):
        return "json", None, None, False
    if os.path.exists(damaged_marker(db_path)):
        return "unknown", None, None, False
    import pathlib
    try:
        conn = sqlite3.connect(pathlib.Path(db_path).as_uri() + "?mode=ro", uri=True, timeout=1.0,
                               isolation_level=None)
    except sqlite3.Error:
        return "unknown", None, None, False
    try:
        conn.execute("PRAGMA query_only=1")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > STORE_SCHEMA:
            return "unknown", None, None, False
        if conn.execute("SELECT 1 FROM meta WHERE key = 'newer_copy'").fetchone():
            return "unknown", None, None, False                # read-only on a newer store's copy (G2.2-7)
        if version < STORE_SCHEMA or conn.execute("SELECT value FROM meta WHERE key = 'migrated_at'").fetchone() is None:
            return "json", None, None, False
        store = Store.__new__(Store)            # a reader on this connection: no write lock, nothing opened for writing
        store.db_path, store.language, store.data_dir, store.user_files_dir = db_path, language, data_dir, user_files_dir
        store.role, store.conn, store._depth, store._cmd, store._repairing = "reader", conn, 0, None, False
        walk = walk_library(data_dir)
        with store._reading():
            schedule, versions = store.schedule(with_versions=True)
            known, _version = _known(store)
        delta = _sync_delta(store, walk, known)
        pending = bool(delta["new"] or delta["renames"] or delta["respell"] or delta["went"] or delta["came"] or
                   delta["asks"])
        return "store", schedule, versions, pending
    except sqlite3.Error:
        return "unknown", None, None, False
    finally:
        conn.close()


def read_auto_band(language, data_dir):
    """Q4-3: the band Automatic rarity last chose, as this library's store remembers it (`meta.auto_band`), or None —
    no ready store, read-only, nothing remembered. A `mode=ro` look: never built, never waits."""
    db_path = library_db_path(language, data_dir)
    if not os.path.exists(db_path) or os.path.exists(damaged_marker(db_path)):
        return None
    import pathlib
    try:
        conn = sqlite3.connect(pathlib.Path(db_path).as_uri() + "?mode=ro", uri=True, timeout=0.5)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'auto_band'").fetchone()
        finally:
            conn.close()
        value = json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError):
        return None
    return value.get("band") if isinstance(value, dict) and isinstance(value.get("band"), str) else None


def record_auto_band(language, data_dir, user_files_dir, band, words):
    """Remember the band Automatic rarity chose (bookkeeping: no version moves; the copy carries it). Never into
    settings.json (S16). False when there is no store to write (JSON mode, read-only): the run then had today's rule."""
    try:
        store = open_store(language, data_dir, user_files_dir, role="analyzer", busy_wait=0.5)
    except StoreError:
        return False
    if store is None:
        return False
    try:
        with store:
            store.bookkeeping({"auto_band": _dumps({"band": band, "words": words, "at": _now()})}, copy_carries=True)
        return True
    except (StoreError, sqlite3.Error):
        return False


def forget_auto_band(language, data_dir, user_files_dir):
    """Automatic rarity is off: forget its band, so switching it on again starts from today's rule, not a band chosen
    months ago. A read first; written only when there is a band to forget."""
    if read_auto_band(language, data_dir) is None:
        return False
    try:
        store = open_store(language, data_dir, user_files_dir, role="analyzer", busy_wait=0.5)
    except StoreError:
        return False
    if store is None:
        return False
    try:
        with store:
            with store._writing():
                store.conn.execute("DELETE FROM meta WHERE key = 'auto_band'")
                store._set_meta({"copy_dirty": store._meta().get("copy_dirty", 0) + 1})
        return True
    except (StoreError, sqlite3.Error):
        return False


def spawn_build_if_waiting(language, data_dir, user_files_dir):
    """A window found no ready store: start the helper to build one when there is something to build from
    (a manifest it can read, in JSON mode), at most once a minute per language (the trigger rule, §6.7).
    The Content Manager's own open builds from the folders (`--from-folders`) instead."""
    now = time.monotonic()
    if now - _build_spawned.get(language, -BUILD_SPAWN_EVERY) < BUILD_SPAWN_EVERY:
        return None
    try:
        mode, reason = check_mode(language, data_dir, busy_wait=0.0)
    except StoreError:
        return None
    newer = mode == "read-only" and reason == NEWER_COPY   # the helper notices a copy put back or deleted
    if not newer and (mode != "json" or not os.path.exists(manifest_path(user_files_dir))):
        return None
    _build_spawned[language] = now
    return spawn_maintain(language)


Store.has_content = _store_has_content
Store.export_due = _store_export_due
Store.copy_stat = _store_copy_stat
Store.folders = _store_folders
Store.walk = _store_walk
Store.sync_disk = _store_sync_disk
Store._repoint = _repoint
Store.reset_order = _store_reset_order
Store._undo_reset = _store_undo_reset


# ------------------------------------------------------------------------------------------------ #
# Repair (§6.9)
# ------------------------------------------------------------------------------------------------ #

def _image_from_db(path):
    """Salvage what a damaged database still reads, table by table: {table: {"fields", "rows"} or None}."""
    import shutil
    import tempfile
    work = tempfile.mkdtemp(prefix="surasura_salvage_")
    try:
        copy = os.path.join(work, "salvage.db")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                shutil.copyfile(path + suffix, copy + suffix)
        out = {}
        try:
            conn = sqlite3.connect(copy)
        except sqlite3.DatabaseError:
            return {}
        try:
            for name in ("meta", "items") + COPY_TABLES:
                try:
                    cur = conn.execute(f"SELECT * FROM {name} ORDER BY rowid")
                    out[name] = {"fields": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
                except sqlite3.DatabaseError:
                    out[name] = None
        finally:
            conn.close()
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def repair_store(db_path, language, data_dir, user_files_dir, lock):
    """Repair (`maintain --repair`): the three files renamed aside (all or none, never deleted); each
    table salvaged from the damaged database when the whole table still reads and its `state_version`
    is at least the copy's, else from the copy (a plain manifest gives its lists, as a migration does);
    the store_id kept, `state_version` above both, a new epoch; then exported through the lock already
    held, and the marker removed. The manifest is read first and kept in the trash before anything is
    renamed: unreadable now → nothing done (retried); unusable → set aside, never overwritten unseen."""
    target = manifest_path(user_files_dir)
    doc = read_stat = None
    if os.path.exists(target):
        try:
            doc, read_stat, _p = read_manifest(target)
        except ManifestUnreadable:
            return EXIT_FAILED                                    # a lock or a placeholder: retried
        if copy_is_newer(doc):
            print(f"Repair refused: the library's copy was {NEWER_COPY}; open it there to repair it.")
            return EXIT_NEEDS_YOU                                 # nothing renamed: a newer copy is never rebuilt from
        try:
            backup_to_trash(target, move=doc is None)
        except OSError:
            return EXIT_FAILED
    stamp = _stamp()
    moved = []
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suffix):
            target = f"{db_path}.corrupt.{stamp}{suffix}"
            try:
                os.rename(db_path + suffix, target)
                moved.append((db_path + suffix, target))
            except OSError:
                for src, dst in reversed(moved):
                    try:
                        os.rename(dst, src)
                    except OSError:
                        pass
                return EXIT_NEEDS_YOU                                 # close other Surasura windows and try again
    damaged = _image_from_db(f"{db_path}.corrupt.{stamp}") if moved else {}
    norm = normalise(doc) if doc is not None else None
    lib = norm.lib if norm else None
    copy_version = int(lib.get("version") or 0) if lib else -1
    dmeta = {}
    if damaged.get("meta"):
        dmeta = {r[0]: r[1] for r in damaged["meta"]["rows"]}
    try:
        db_version = int(dmeta.get("state_version", -1))
    except ValueError:
        db_version = -1
    from_db = lambda name: damaged.get(name) is not None and db_version >= copy_version
    if lib:
        copy_image = _image_from_copy(norm, data_dir)
    elif norm:
        copy_image = _image_from_manifest(norm, data_dir)
    else:
        copy_image = {"items": [], "tables": {}}
    # Items from a plain manifest get new ids: the database's tables keyed by the old ones can't follow.
    plain = not from_db("items") and not lib
    image = {"items": [], "tables": {}}
    if from_db("items"):
        fields = damaged["items"]["fields"]
        rows = [dict(zip(fields, r)) for r in damaged["items"]["rows"]]
        rows.sort(key=lambda r: (TIERS.get(r["tier"], (0, 0, 0, 0))[3], r["ord"], r["id"]))
        for r in rows:
            item = {k: r.get(k) for k in ("id", "root_id", "rel_path", "rel_key", "tier", "size", "mtime_ns",
                                          "availability", "added_at", "graduated_at", "piece_id", "watched",
                                          "mined_at", "pinned", "in_learning_order", "changed_in", "work_id",
                                          "mine_asked")}
            item["entry"] = json.loads(r["entry"])
            image["items"].append(item)
    else:
        image["items"] = copy_image["items"]
    for name in COPY_TABLES:
        if from_db(name) and not plain:
            image["tables"][name] = damaged[name]
        elif name in copy_image["tables"]:
            image["tables"][name] = copy_image["tables"][name]
    try:
        epoch = max(int(dmeta.get("epoch", 0) or 0), int((lib or {}).get("meta", {}).get("epoch", 0) or 0)) + 1
    except ValueError:
        epoch = 1
    store_id = dmeta.get("store_id") or (lib or {}).get("store_id") or uuid.uuid4().hex
    meta = _fresh_meta(store_id, epoch, max(db_version, copy_version, 0) + 1)
    if norm:
        meta.update(_manifest_meta(norm))
        meta.update(_copy_meta_block(lib))
    for key in ("manifest_metadata", "manifest_extra", "manifest_schedule_extra", "mine_line",
                "arrivals_on") + COPY_META_KEYS:
        if key in dmeta and from_db("meta") and not plain:
            meta[key] = dmeta[key]
    for key, value in dmeta.items():
        if key.startswith("reader") and from_db("meta"):
            meta[key] = value
    meta["last_export_stat"] = read_stat if doc is not None else ""
    store = _helper_store(db_path, language, data_dir, user_files_dir)
    store._repairing = True
    try:
        _ensure_schema(store)
        with store._writing():
            _write_image(store, image, meta)
            store._set_meta({"migrated_at": _now()})
            _line_after_build(store, meta.get("soon_line"))
        try:
            os.remove(damaged_marker(db_path))
        except OSError:
            pass
        store._repairing = False
        export_copy(store)
    finally:
        store.close()
    return EXIT_DONE


# ------------------------------------------------------------------------------------------------ #
# File work (§6.6, §6.11): the caller's, outside every transaction — the store itself never moves a
# file (I3). Tk-free, so Phase 2's Content Manager calls these instead of its own copies.
# ------------------------------------------------------------------------------------------------ #

def copy_into_finished(data_dir, sources, progress=None, cancel=None):
    """The Finished importer's job (05 §5.8, run off the window's thread, outside the write lock): each content file
    picked — or in a folder picked, the folder keeping its name — copied into `data/<lang>/Graduated/`, which the disk
    sync never walks; a file already in the library is listed as it is, never copied. A taken name copies as
    `name_1.ext`; nothing is overwritten, the user's files stay where they were. `progress(done, total)`; `cancel()`
    True stops between files. Returns the paths relative to the data folder, for `Store.import_finished`."""
    import shutil
    plan = []
    for source in sources:
        rel = library_rel(data_dir, source) if os.path.isabs(source) else None
        if rel is not None and os.path.exists(os.path.join(data_dir, rel)):
            full = os.path.join(data_dir, rel)
            if os.path.isfile(full):
                plan.append((None, rel))
            else:                                  # a folder in the library: its files as they are (§12.8)
                for folder, _dirs, files in sorted(os.walk(full)):
                    for name in sorted(files):
                        if is_content_name(name):
                            plan.append((None, library_rel(data_dir, os.path.join(folder, name))))
            continue
        if os.path.isdir(source):
            base = os.path.basename(os.path.normpath(source))
            for folder, _dirs, files in sorted(os.walk(source)):
                for name in sorted(files):
                    if is_content_name(name):
                        inner = os.path.relpath(os.path.join(folder, name), source).replace("\\", "/")
                        plan.append((os.path.join(folder, name), f"{GRADUATED_FOLDER}/{base}/{inner}"))
        elif os.path.isfile(source) and is_content_name(source):
            plan.append((source, f"{GRADUATED_FOLDER}/{os.path.basename(source)}"))
    out = []
    for n, (src, rel) in enumerate(plan):
        if cancel is not None and cancel():
            break
        if src is not None:
            stem, ext = os.path.splitext(rel)
            candidate, k = rel, 0
            while os.path.exists(os.path.join(data_dir, *candidate.split("/"))):
                k += 1
                candidate = f"{stem}_{k}{ext}"
            dst = os.path.join(data_dir, *candidate.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            rel = candidate
        out.append(rel)
        if progress is not None:
            progress(n + 1, len(plan))
    return out


def trash_file(data_dir, rel):
    """A user's Remove or Undo-Add: the file to `data/<lang>/.trash/<base>_<stamp><ext>` (never
    `rmtree`), its 30-day clock restarted. Returns the trashed path relative to data/<lang>, or None
    when there was no file."""
    src = os.path.join(data_dir, _strip(rel))
    if not os.path.isfile(src):
        return None
    trash = os.path.join(data_dir, ".trash")
    os.makedirs(trash, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    stamp = time.strftime("%Y%m%d%H%M%S")
    name, n = f"{base}_{stamp}{ext}", 1
    while os.path.exists(os.path.join(trash, name)):
        name, n = f"{base}_{stamp}_{n}{ext}", n + 1
    dst = os.path.join(trash, name)
    os.rename(src, dst)
    restart_trash_clock(dst)
    return f".trash/{name}"


def _rename_no_overwrite(src, dst):
    """Never overwrite (§6.6): `os.rename` on Windows fails if the target exists; elsewhere a hard link
    then unlink, which fails too; without hard links (FAT, exFAT), check the target is free first."""
    if sys.platform == "win32":
        os.rename(src, dst)
        return
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        if os.path.exists(dst):
            raise FileExistsError(dst)
        os.rename(src, dst)
        return
    os.unlink(src)


def put_back(data_dir, trashed_rel, rel):
    """Undo-Remove / Put back's file half: the trashed file back at `rel`, its missing parent folders
    recreated; a taken name restores as `name_1.ext` (with a note); a file already purged after 30 days
    restores nothing. Returns (the rel path it went back to or None, note or None)."""
    src = os.path.join(data_dir, *trashed_rel.split("/"))
    if not os.path.isfile(src):
        return None, "purged"
    stem, ext = os.path.splitext(rel)
    candidate, n = rel, 0
    while True:
        dst = os.path.join(data_dir, *_strip(candidate).split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            _rename_no_overwrite(src, dst)
            break
        except FileExistsError:
            n += 1
            candidate = f"{stem}_{n}{ext}"
    return candidate, (None if candidate == rel else f"put back as {candidate.rsplit('/', 1)[-1]}: the name was taken")


def strip_graduated_block(user_files_dir, language, rels):
    """Undo-Graduate: remove each file's `# Source: <rel>` block from GraduatedList.txt, after a
    `backup_to_trash` copy, with an atomic write (today's strip was a non-atomic rewrite with no
    backup). Returns the number of blocks removed."""
    from app.path_utils import read_text
    path = os.path.join(user_files_dir, "GraduatedList.txt")
    if not os.path.exists(path):
        return 0
    lines = read_text(path, language, errors="strict").splitlines(True)
    removed = 0
    for rel in rels:
        header = f"# Source: {rel}"
        for i in range(len(lines) - 1, -1, -1):
            text = lines[i].rstrip("\r\n")
            if text == header or text.startswith(header + " ("):
                end = i + 1
                while end < len(lines) and lines[end].strip() and not lines[end].startswith("# Source:"):
                    end += 1
                if i > 0 and not lines[i - 1].strip():      # the blank line the append put before it
                    i -= 1
                del lines[i:end]
                removed += 1
                break
    if removed:
        backup_to_trash(path)
        temp = f"{path}.{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    return removed


# ------------------------------------------------------------------------------------------------ #
# register with no store yet (✅ G1.1-6), and the command line
# ------------------------------------------------------------------------------------------------ #

# What `register_headless` answers (P2.1, the command line's `register`): `code` (EXIT_*); for a registration, the
# item (`file_id`), where it is (`landed`: now-top · arrivals · show · already; `tier`, its 1-based `position` there)
# and what became of the pairing (`pairing`: new · same · replaced). The fields after `code` are None otherwise.
Registered = namedtuple("Registered", "code file_id landed tier position pairing rule", defaults=(None,))


def _registered(code):
    return Registered(code, None, None, None, None, None)


def register_headless(language, path, pairing, data_dir=None, user_files_dir=None, backfill=False, looks=1,
                      reader=None, rules=None):
    """`register` as hato's command line calls it: 5 while an update is staged (`looks`: how many looks at the
    update lock, `update_staged`); with no store yet, the store is built headless when a usable manifest exists (as
    Generate would), else 4 "needs you" and nothing written (the file still lands as today; only the pairing waits
    for a retry); 6 for a path outside the library. `reader`: a placement-log reader set (once) before the
    registration — Connect's watermark, so a store this call builds logs the drop too. Returns a `Registered`."""
    from app.path_utils import get_data_path, get_user_files_path
    data_dir = data_dir or get_data_path(language)
    user_files_dir = user_files_dir or get_user_files_path(language)
    if update_staged(looks=looks):
        return _registered(EXIT_BUSY)
    rel = library_rel(data_dir, path)
    if rel is None:
        return _registered(EXIT_BAD_DATA)          # refused before anything is written, a store's build included
    store = open_store(language, data_dir, user_files_dir, role="register")
    if store is None:
        mode, _reason = check_mode(language, data_dir)
        target = manifest_path(user_files_dir)
        usable = False
        if mode == "json" and os.path.exists(target):
            try:
                usable = read_manifest(target)[0] is not None
            except ManifestUnreadable:
                usable = False
        if not usable:
            return _registered(EXIT_NEEDS_YOU)
        code = maintain(language, data_dir, user_files_dir, export=False)
        if code not in (EXIT_DONE, EXIT_NOTHING):
            return _registered(code)
        store = open_store(language, data_dir, user_files_dir, role="register")
        if store is None:
            return _registered(EXIT_NEEDS_YOU)
    with store:
        if reader:
            store.register_reader(reader)
        try:
            change = store.register(rel, pairing, backfill=backfill, rules=rules)
        except NotInLibrary:
            return _registered(EXIT_BAD_DATA)
        # The change's own item (a move or remove after the commit can't lose it); a pairing already there: by its path
        item_id = getattr(change, "pairing_item", None) or (change.added[0] if change is not None and change.added
                                                             else store.item_id(rel))
        tier, position = store.place_of(item_id)
    if change is not None and change.added:
        dkey, hato = path_key(_rel_dir(rel)), path_key(HATO_FOLDER)
        landed = "arrivals" if tier == "arrivals" else \
            "now-top" if dkey == hato or dkey.startswith(hato + "/") else "show"
    else:
        landed = "already"
    before = getattr(change, "pairing_before", None)
    paired = "same" if before is None else "new" if before[1] is None else "replaced"
    rule = getattr(change, "rule", None)
    if rule and landed != "already":
        landed = "arrivals"                                    # where it landed; the rule placed it from there
    return Registered(EXIT_DONE, item_id, landed, tier, position, paired, rule)


def main(argv=None):
    """`python app/library_store.py maintain --language ja [--from-folders | --repair] [--check] [--retry]`,
    or `sync --language ja`. Dialog-free: it catches everything and exits with the command's code."""
    import argparse
    parser = argparse.ArgumentParser(prog="library_store")
    sub = parser.add_subparsers(dest="command")
    m = sub.add_parser("maintain")
    m.add_argument("--language", required=True)
    group = m.add_mutually_exclusive_group()
    group.add_argument("--from-folders", action="store_true")
    group.add_argument("--repair", action="store_true")
    m.add_argument("--check", action="store_true", help="run quick_check (once per launch)")
    m.add_argument("--retry", action="store_true", help="retry a failed migration (Try again)")
    y = sub.add_parser("sync")
    y.add_argument("--language", required=True)
    y.add_argument("--folder", action="append", help="only this folder (relative to data/<lang>); repeatable")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    if args.command == "sync":
        return sync_process(args.language, args.folder)
    if args.command != "maintain":
        return EXIT_USAGE
    try:
        return maintain(args.language, from_folders=args.from_folders, repair=args.repair,
                        check_integrity=args.check, retry=args.retry)
    except Exception:
        return EXIT_FAILED


def sync_process(language, folders=None):
    """`sync`: a window's `sync_disk` in a process of its own (`sync_for_window`, a large library). 0 when
    something changed, 3 nothing, 4 no ready store, 5 an update staged, 1 failed. Dialog-free."""
    from app.path_utils import get_data_path, get_user_files_path
    try:
        if update_staged():
            return EXIT_BUSY
        store = open_store(language, get_data_path(language), get_user_files_path(language), role="window")
        if store is None:
            return EXIT_NEEDS_YOU
        with store:
            return EXIT_DONE if store.sync_disk(folders=folders) else EXIT_NOTHING
    except Exception:
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
