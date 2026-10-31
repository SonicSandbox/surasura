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

import bisect
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
from app.path_utils import (CONTENT_EXTENSIONS, TRASH_DAYS, backup_to_trash, decode_text, infer_source_type,
                            read_source_marker, restart_trash_clock)

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


# --- W-1 (K-W1; Sonic 2026-10-22): ONE rule for what counts ------------------------------------------------------- #
# An item COUNTS (a list use: Generate's files, the Rarity preview's sums, the mine line) when its tier is analysed and
# it isn't watched, or the library's own option `keep_watched` is on (meta; absent = off). A watched item of an analysed
# tier while it's off is SET ASIDE (`text_lists`, `sets_aside`): its text kept, never summed, still the name tables'
# evidence and a sentence source — as Finished is (W-1b). Finished takes a show off the list by its tier, a stone one
# episode by this rule. Written once in Python (`counts`) and once in SQL (`counts_sql`), from the same constants; a
# test holds the two equal. Who reads it today: here, `Store.schedule` (Generate's list, and its set-aside items for
# the run signature's "reference" part), `_mine_ids`, `text_lists`, `_moves_counted`, `_watched_aside`,
# `_store_has_content`, `read_only_schedule` (the copy) and `watched_marks` (the journey's stones: the report's
# `static_html_generator._journey_stones`, the render signature's `analyzer._stones_fingerprint`); outside,
# `moves._set_aside` (the window's numbers) and Connect's `library.counting` / `library.counts` (`level._walk` beyond
# the line, a gap's `inbox._gone`; M-W1 — `level.watched_out` stays stricter, LF4-1). Not yet: the window's drawn
# lines (`view_rows._mine_ids`, `drag.lines_for`).
def _tiers_sql(tiers):
    return ", ".join(f"'{t}'" for t in tiers)


# Is any item Generate's list reads or sets aside watched? Through the partial index `items_watched` (its WHERE is
# this query's own term): ~0.05 ms at 200k items, against ~60 ms scanning every analysed row (the stones review, S-2)
STONES_EXIST_SQL = (f"SELECT EXISTS (SELECT 1 FROM items WHERE tier IN ({_tiers_sql(ANALYSED)}) AND watched != 0 "
                    "AND availability != 'waiting')")
STONES_COUNTED = "stones_counted"   # meta: this library's old watched marks were counted once (`count_old_stones`)
# `schedule(with_aside=True)`'s key: the SET-ASIDE items' entries, read in the same transaction as the list — the run
# signature's "reference" part (`analyzer.aside_files`): their text is the name tables' evidence and 例文's sentences, so
# a mark, its Undo, the option flipped or a set-aside file edited is a Generate first, never the fast re-plan.
ASIDE = "SET_ASIDE"


def counts(tier, watched, keep_watched=False):
    """Does an item of `tier` whose `watched` is 0 / 1 count, while the library's `keep_watched` is `keep_watched`?"""
    return tier in ANALYSED and (not watched or bool(keep_watched))


def counts_sql(keep_watched=False, alias=""):
    """`counts` as an SQL condition on `items` (`alias`: the table's name in the query)."""
    col = f"{alias}." if alias else ""
    tiers = f"{col}tier IN ({_tiers_sql(ANALYSED)})"
    return f"({tiers})" if keep_watched else f"({tiers} AND {col}watched = 0)"


# W-1b (Sonic 2026-10-23): Finished content is reference, as a watched episode is — never a list use, but the name
# tables' evidence and a sentence source. Its tier is REFERENCE: every item in it is set aside, watched or not, the
# option on or off. New arrivals (waiting to be placed) and removed items stay kept: text only.
REFERENCE = ("graduated",)


def sets_aside(tier, watched, keep_watched=False):
    """Is an item of `tier` (`watched` 0 / 1, the library's `keep_watched`) set aside — its text the name tables'
    evidence and a sentence source, never counted? A REFERENCE tier's item, and an analysed tier's item that doesn't
    count (`counts`: watched, the option off)."""
    return tier in REFERENCE or (tier in ANALYSED and not counts(tier, watched, keep_watched))


def sets_aside_sql(keep_watched=False, alias=""):
    """`sets_aside` as an SQL condition on `items` (`alias`: the table's name in the query)."""
    col = f"{alias}." if alias else ""
    return (f"({col}tier IN ({_tiers_sql(REFERENCE)}) OR "
            f"({col}tier IN ({_tiers_sql(ANALYSED)}) AND NOT {counts_sql(keep_watched, alias)}))")
# --- end W-1


def _scheduled_sql(keep_watched=False):
    """What `Store.schedule` lists of one tier (its `?`): the items that count, a video still waiting for its subtitle
    (K5) never — one condition for the schedule and the ids the window's numbers read (`Store.scheduled_ids`)."""
    return f"tier = ? AND {counts_sql(keep_watched)} AND availability != 'waiting'"


TIER_OF_PHASE = {v[0]: t for t, v in TIERS.items() if v[0]}
TIER_OF_FOLDER = {v[1]: t for t, v in TIERS.items() if v[1]}
FOLDER_OF_TIER = {t: v[1] for t, v in TIERS.items() if v[1]}
_TIER_OF_FOLDER_FOLDED = {k.casefold(): t for k, t in TIER_OF_FOLDER.items()}   # K8: a folder's name as Windows reads it
TIER_LABELS = {"now": "Current", "soon": "Soon", "goal": "Goal", "graduated": "Finished",     # 3.0's names (W4.1:
               "arrivals": "New arrivals"}                                                    # never 2.x's NOW / 6+ Months)
CURRENT = ("now", "soon")        # Current = NOW then Soon; the Soon line is their boundary
SORT = "sort"                    # `take_in(first=SORT)`: setup's first scan landing in New arrivals for its sort screen
HATO_FOLDER = "HighPriority/Hato"  # hato's drop folder: its files land at the top of NOW through 2.x
GRADUATED_FOLDER = "Graduated"
# 3.0's Sources (SRC): every new text copy goes into one content folder of Surasura's own, `Library/<show>/<file>`,
# whatever its place; grouping only (`_below_tier` strips it), never a place (a place is the store's alone)
CONTENT_FOLDER = "Library"
WALK_FOLDERS = tuple(TIERS[t][1] for t in ANALYSED) + (CONTENT_FOLDER,)   # what the disk sync walks and watches
SOURCE_PRODUCER = "source"       # an origin record's producer, and the placement log's name for a scan's take-in
SOURCE_KEY = "src:"              # an origin row's `pairings.content_key`: "src:" + path_key(<absolute origin>) (B1)
# An origin record's fields Connect never reads (`pairing_of` strips them, so none moves its pairing version): the
# original's stats a re-copy rewrites (`update_origin`), and D5's mark (`moved_to`, written by `take_in`'s `moved_from`)
SOURCE_STATS = ("size", "mtime_ns", "sha256", "moved_to")
# B1: a `pairings` row that is an origin's, and a source row read only when its item has no other (`p` = the row)
_ORIGIN_ROW = "(p.content_key >= 'src:' AND p.content_key < 'src;')"
# LM1b: an origin that is ANOTHER VERSION of its item's episode (a second group's subtitle, a lower release, one a
# number joined): its record says `"version": true`. It keeps its file in (found, never new again; Remove keeps it out)
# and is no reader's: never the item's text, video, number or pairing (A8, A26)
_VERSION_ROW = (f"({_ORIGIN_ROW} AND (CASE WHEN json_valid(p.pairing) THEN json_type(p.pairing, '$.version') END) "
                "IS 'true')")                    # (SQLite never short-circuits for a malformed record: the CASE does)
# D5 (PROVISIONAL): an origin whose original moved — its file gone from a folder still there, the same item's origin
# recorded in its new place (`take_in`'s `moved_from`) — says `"moved_to": <the new origin's path key>`. It stays an
# origin (found, kept out, its show's), never counted under its old folder (`sources`); Connect reads a live one first
# (Michi's `pairing_of`). A look listing the original in its old place again takes the mark off (`origins_back`).
_MOVED_ROW = ("((CASE WHEN json_valid(p.pairing) THEN json_type(p.pairing, '$.moved_to') END) IS NOT NULL)")
_PREFERRED_ROW = (f"NOT ({_ORIGIN_ROW} AND EXISTS (SELECT 1 FROM pairings q WHERE q.item_id = p.item_id AND NOT "
                  f"(q.content_key >= 'src:' AND q.content_key < 'src;'))) AND NOT {_VERSION_ROW}")
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
OLD_SURASURA_OWN = ("User Files", "_internal", "results")   # in a Surasura program's folder: never a source

# maintain's exit codes (spec §6.7); register_headless adds 6: the path can't be registered (not in the library)
EXIT_DONE, EXIT_FAILED, EXIT_USAGE, EXIT_NOTHING, EXIT_NEEDS_YOU, EXIT_BUSY = 0, 1, 2, 3, 4, 5
EXIT_BAD_DATA = 6

LOCK_TIMEOUT = 5.0               # the write lock and SQLite's busy wait
LOCK_RETRY = 0.0005              # 0.5 ms between tries of the OS write lock
CLOSE_WAIT_MS = 50               # a close's anchor and its write lock are waited for this long (§6.12)
BUSY_AT_OPEN = 1.0               # "database is locked" at open is retried this long (§6.2)
MAINT_WAIT = 10.0                # a helper waits this long for the maintenance lock, then exits 5
BAK_KEEP = 10                    # the store's own .bak files kept (R-5)
OUTSIDE_ROLES = ("connect",)     # a writer with no window of its own and a life long enough to batch (§6.12)
OUTSIDE_IDLE_WAIT = 1.0          # its checkpoint waits this long for the write lock (a writer then has it: skipped)
OUTSIDE_IDLE_S = 2.0             # its copy trigger fires this long after its last commit (a burst, one export)
TWIN_HASHES = 8                  # hato's file is checked by its bytes against this many items of its size at most (F12)

# Integer meta keys, and what a fresh store holds (spec §6.3, §6.8 step 3)
INT_META = ("epoch", "state_version", "order_version", "availability_version", "pins_version",
            "analysed_order_version", "planned_order_version", "planned_pins_version",
            "last_export_version", "copy_dirty", "log_seq", "mine_line", "arrivals_on", "soon_line",
            "feed_floor", "search_fold", "keep_watched")


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


class NotASource(StoreError):
    """`add_source` / `take_in` refused a folder (SRC B3): `reason` says why in plain words, for the window."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


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
    as written; '' for a loose file (directly in a tier folder, or in hato's drop folder). The content folder counts as
    one (`Library/Frieren/x.srt` → 'Frieren': one title with a 2.x `HighPriority/Frieren`), in any case the file
    system reads as it (as `take_in` and the sync compare it)."""
    folder = _rel_dir(_strip(rel))
    if not folder or path_key(folder) == path_key(HATO_FOLDER):
        return ""
    parts = folder.split("/")
    if parts[0] in TIER_OF_FOLDER or parts[0] == GRADUATED_FOLDER or path_key(parts[0]) == path_key(CONTENT_FOLDER):
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


def folder_title(below):
    """A folder work's title from its folder below the tier (`_below_tier`): `episode_names.folder_title`'s one rule
    (a season or specials folder named with the show above it, any other folder as written)."""
    from app.episode_names import folder_title as title_of
    return title_of(below)


def show_of_name(file_name):
    """A stranded episode's show, read from its file name (SRC-11) by LM1a's one rule (`episode_names.identity`): a
    leading `[group]`, every `[…]` / `(…)` tag, the extension and a language tag (`.ja`), resolution and hash tags, a
    version (`v2`), and the episode marker with all after it (` - 16`, `S01E13`, `E13`, `#13`, `第13話`) come off. A
    season stays part of the name, as `_work_by_record` keeps seasons apart (`S2`, `Season 2`, `II`, `2期`; `S02E05`
    reads as `… S2`). As written (NFKC), never folded: compare two with `search_fold`. None when nothing, or only
    digits and marks, is left. Pure."""
    from app.episode_names import identity
    return identity(file_name).show


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
    """The updater's own marker, `pending_update.json` in `<Houseki local root>\\update\\` (S3.1 D9:
    `updater.marker_path()`, worked out here without importing the updater or making its folder — a status look
    creates nothing): written at the hand-over, deleted by its swapper once the program is swapped. The store adds
    no second marker."""
    from app.path_utils import UPDATE_DIRNAME, UPDATE_MARKER, local_data_root
    return os.path.join(local_data_root(), UPDATE_DIRNAME, UPDATE_MARKER)


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


_NOW_LAST = [0]                  # the last stamp `_now` gave, in microseconds
_NOW_LOCK = threading.Lock()


def _now():
    """A sortable UTC time stamp with microseconds (`added_at`, `removed_at`, the log's `at`), never one this process
    gave already (Windows' clock moves ~15 ms at a time: two Removes in one tick were one Removed entry, alpha 5)."""
    with _NOW_LOCK:
        us = _NOW_LAST[0] = max(int(time.time() * 1e6), _NOW_LAST[0] + 1)
    secs, frac = divmod(us, 10 ** 6)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(secs)) + ".%06dZ" % frac


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
    "CREATE INDEX items_missing ON items (size) WHERE availability = 'missing'",   # D2: a scoped sync's missing items
    "CREATE INDEX items_watched ON items (tier) WHERE watched != 0",        # the journey's stones (`STONES_EXIST_SQL`)
    "CREATE INDEX items_available_size ON items (size) WHERE availability = 'available'",   # K5: `items_of_size`
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
    "CREATE INDEX pairings_item ON pairings (item_id)",   # an item's records (`_PREFERRED_ROW`, a show's episodes)
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

# Indexes added without a schema change (SRC perf): an index changes no row and an older Surasura reads the store as it
# was; a new store makes them in SCHEMA_SQL, an existing one at its first open by a writer (`_added_indexes`)
ADDED_INDEXES_SQL = (
    "CREATE INDEX IF NOT EXISTS pairings_item ON pairings (item_id)",
    "CREATE INDEX IF NOT EXISTS items_missing ON items (size) WHERE availability = 'missing'",   # D2 (`_lost_by_size`)
    "CREATE INDEX IF NOT EXISTS items_watched ON items (tier) WHERE watched != 0",
    # K5 (alpha 4): a look's check (b) per new file or book part (`items_of_size`) scanned every item without it: a first
    # look of 25k books spent minutes there. Dropped as easily (DROP INDEX): no row changes
    "CREATE INDEX IF NOT EXISTS items_available_size ON items (size) WHERE availability = 'available'",
)
ADDED_INDEXES = ("pairings_item", "items_missing", "items_watched", "items_available_size")
# A4K-7 (alpha 4, Sonic 2026-10-28): each copy's content hash, kept for a look's check (b), which read and hashed every
# copy of a new part's size (~56,000 files when 100 books came onto 60k parts). Made with the added indexes: an added
# column (no row rewritten: NULL until a look fills it) and a trigger that forgets a hash whenever its row's file
# changes (its size, time or path), whoever writes the row, an older Surasura too. Never in the copy (ITEM_FIELDS, and
# never in a Remove's trash state).
# Dropped as easily: DROP TRIGGER items_hash_stale, then the column (or left: older code never reads it)
ADDED_HASH_SQL = (
    "ALTER TABLE items ADD COLUMN content_sha256 TEXT",
    """CREATE TRIGGER IF NOT EXISTS items_hash_stale AFTER UPDATE OF size, mtime_ns, rel_path ON items
      WHEN NEW.content_sha256 IS NOT NULL AND (NEW.size IS NOT OLD.size OR NEW.mtime_ns IS NOT OLD.mtime_ns
                                               OR NEW.rel_path IS NOT OLD.rel_path)
      BEGIN UPDATE items SET content_sha256 = NULL WHERE id = NEW.id; END""",
)
ADDED_HASH = "items_hash_stale"

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
                    "in_learning_order", "added_at", "feed_in", "mtime_ns")
#   mtime_ns (a7): the file's own date — a source's copy keeps its original's (`sources._dated`) — what
#   `view_rows.still_arriving` reads beside `added_at` (a first look takes a whole show in at one time)
FEED_WORK_FIELDS = ("id", "title", "title_by_user", "titles", "folder_key", "anilist_id", "tmdb_id", "youtube_channel",
                    "media_type", "media_type_by", "cover_source", "cover_ref", "cover_path", "cover_fetched_at",
                    "cover_locked", "feed_in")
FEED_PIECE_FIELDS = ("id", "title", "kind")    # LM11: a full read every piece; a delta the pieces of its changed rows

# --- LM11 (Sonic's G1–G4, 2026-10-21): ONE piece rule — `Store.join(..., how=)` ------------------------------------- #
# A piece is a run of one work's items (kind 'run'), or a user-made GROUP of several works' items (kind 'group': no work
# changes; still one contiguous run in one tier). A group never lives in Finished or New arrivals, and one left holding
# one work's items is a run again (`Store._settle_kinds`).
JOIN_HOW = ("parts", "titles", "group")
NO_GROUP_TIERS = ("graduated", "arrivals")
TITLES_APART = {        # *Same show as…* refused (`how="titles"`, `merge_works`): the ids say two shows (plain words)
    "anilist_id": "AniList says these are two different shows. Group them instead.",
    "tmdb_id": "TMDB says these are two different shows. Group them instead.",
    "youtube_channel": "These are two different YouTube channels. Group them instead.",
}
GROUP_REFUSED = "A group lives in Current, Soon or Goal: move these there first."    # the window's list names
# --- end LM11

# Every table but meta and items goes out in the copy generically (fields + rows, §6.7); `works` without its derived
# columns (WORK_NOT_COPIED: a rebuild re-derives them)
COPY_TABLES = ("roots", "pieces", "trash", "exclusions", "anki_links", "anki_changes", "pairings",
               "placement_log", "made_words", "made_lines", "works")
WORK_NOT_COPIED = ("search_key", "feed_in")
# Meta keys the copy carries when the store holds them (beside epoch, log_seq, mine_line, arrivals_on and the readers)
COPY_META_KEYS = ("soon_line", "auto_band", "rename_asks", "kept_apart", "show_groups",   # LM2
                  "keep_watched",                                                          # W-1
                  "audiobook_answers")                                                     # Hon, H-8
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


def _read_only(path, busy_ms):
    """A read-only connection: SQLite never checkpoints at its close, so it writes neither the database nor its
    `-wal`, whenever it closes (§6.12)."""
    import pathlib
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=LOCK_TIMEOUT,
                           isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
    except BaseException:
        conn.close()
        raise
    return conn


def _close(conn, db_path, role):
    """Close a connection without a checkpoint outside the write lock (§6.12). SQLite checkpoints a WAL database
    when its last connection closes, and deletes the `-wal`: done by Connect's short-lived handles with Surasura
    closed, that ran outside the write lock at every close (P2.4's verifier: 406 of 406), and the next write paid for
    a new `-wal` (a receipt's hold up to 62 ms). A read-only connection never checkpoints, and while one is open no
    other close is the last: so a reader opened for the close (an anchor) keeps the `-wal` for the next checkpoint
    under the lock (the helper's run, Connect's idle trigger, or the close trigger). The helper is the checkpointer:
    its close keeps SQLite's checkpoint, under the write lock. The anchor and the lock are each waited for briefly
    (CLOSE_WAIT_MS: every close in WAL mode holds a lock for a moment, so two closes at once can meet). With no
    anchor, the close goes under the write lock; if it's still held after that wait, the close is plain: almost
    always a writer with its connection open, so this close isn't the last; rarely another close, and then this one
    may checkpoint outside the lock (SQLite's exclusive lock still guards that checkpoint)."""
    if role == "helper":
        lock = _write_lock_for(db_path)
        try:
            lock.acquire()
        except StoreBusy:                       # held all along by an open connection: this close isn't the last
            conn.close()
            return
        try:
            conn.close()
        finally:
            lock.release()
        return
    anchor = None
    try:
        anchor = _read_only(db_path, CLOSE_WAIT_MS)
        anchor.execute("PRAGMA user_version").fetchone()           # a read: the anchor's shared lock taken
    except sqlite3.Error:
        if anchor is not None:
            anchor.close()
        anchor = None
    try:
        if anchor is not None:
            conn.close()
            return
        lock = _write_lock_for(db_path)
        try:
            lock.acquire(timeout=CLOSE_WAIT_MS / 1000)
        except StoreBusy:
            conn.close()
            return
        try:
            conn.close()
        finally:
            lock.release()
    finally:
        if anchor is not None:
            anchor.close()


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

def _mode_on(conn):
    """(mode, reason) read on an open connection: the version, then whether the build finished."""
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


def _probe(db_path, busy_wait):
    """(mode, reason) for the database at `db_path`, retrying a busy database for `busy_wait` s. Read on a read-only
    connection, which never checkpoints at its close (§6.12); a database a read-only connection can't read (an error
    that isn't busy or damage) is read the way it was before L3.3, on a reader's connection closed by `_close`."""
    if not os.path.exists(db_path):
        return "json", "no store"
    if os.path.exists(damaged_marker(db_path)):
        return "read-only", "damaged"
    deadline = time.perf_counter() + busy_wait
    read_only = True
    while True:
        conn, ro = None, read_only
        try:
            busy_ms = 50 if busy_wait else 0
            conn = _read_only(db_path, busy_ms) if ro else _connect(db_path, "reader", busy_ms=busy_ms)
            return _mode_on(conn)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                if time.perf_counter() < deadline:
                    time.sleep(0.02)
                    continue
                return "read-only", "busy"
            if ro and not _is_malformed(exc):  # e.g. a -shm a read-only open can't make: read it as before
                read_only = False
                continue
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
                if ro:
                    conn.close()
                else:
                    _close(conn, db_path, "reader")


def check_mode(language, data_dir, busy_wait=BUSY_AT_OPEN):
    """('store' | 'read-only' | 'json', reason). Cheap: no scans, no parsing (I10)."""
    return _probe(library_db_path(language, data_dir), busy_wait)


def open_store(language, data_dir, user_files_dir, role="window", busy_wait=BUSY_AT_OPEN):
    """A `Store` handle for this thread, or None when no store is ready (not built, JSON mode,
    read-only). Cheap: it checks the version, the damage marker and readiness, nothing more (§6.2).
    Inside `held()` on this thread, the span's handle for this store and role (opened by the first call), its mode
    read again through it each time (two cached reads): a store marked damaged, made newer or no longer migrated
    meanwhile is let go of and None, as outside a span."""
    db_path = library_db_path(language, data_dir)
    span = _span()
    key = (os.path.normcase(os.path.abspath(db_path)), role)
    if span is not None and key in span:
        store = span[key]
        try:
            ready = not os.path.exists(damaged_marker(db_path)) and _mode_on(store.conn)[0] == "store"
        except sqlite3.Error:
            ready = False
        if ready:
            return store
        span.pop(key)                                   # let go of it now (damaged: so Repair can set the file aside)
        store._held = False
        try:
            store.close()
        except Exception:
            pass
        return None
    mode, _reason = _probe(db_path, busy_wait)
    if mode != "store":
        return None
    try:
        # Schema 2: the Soon line is canonical and the tiers follow it (L2.2 05 §5.1); an open no longer re-counts it
        store = Store(db_path, language, data_dir, user_files_dir, role)
    except (sqlite3.DatabaseError, StoreError):
        return None                                     # a failed open closed its own connection (`Store`, §6.12)
    if span is not None:
        store._held = True
        span[key] = store
    return store


_HELD = threading.local()


def _span():
    return getattr(_HELD, "span", None)


@contextmanager
def held():
    """One handle a store and role for a span on this thread (Connect's job, §6.12): `open_store` inside it returns
    the handle its first call opened, and that handle's `close()` waits for the span's end — so a job that asks for
    its store ten times opens it once. A span inside another joins the outer one. A store that isn't ready is asked
    again at each `open_store`, as outside a span; one marked damaged meanwhile is None, as outside. Never
    around a window's `StoreOpener.handle()` (it keeps its handle for the window's life)."""
    if _span() is not None:
        yield
        return
    span = _HELD.span = {}
    try:
        yield
    finally:
        _HELD.span = None
        for store in span.values():
            store._held = False
            try:
                store.close()
            except Exception:                    # one handle's failure never leaves the others open
                pass


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
        """The mode now (L3.3: read through this thread's open handle when it has one — a store already open stays
        a store unless damaged, made newer or no longer migrated, and that read costs two cached reads; the probe,
        a new connection each time, runs only without a handle or when the handle's answer isn't "store")."""
        with self._guard:
            if self._worker is not None and self._worker.is_alive():
                return self.mode
        store = getattr(self._local, "store", None)
        if store is not None and not os.path.exists(damaged_marker(store.db_path)):
            try:
                if _mode_on(store.conn)[0] == "store":
                    self.mode, self.reason = "store", None
                    return "store"
            except sqlite3.Error:
                pass
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

    def close(self):
        """Close this thread's handle through `_close` (§6.12: never left to the collector's plain close, which
        checkpoints outside the write lock when it is the last). The next `handle()` opens a new one."""
        store = getattr(self._local, "store", None)
        self._local.store = None
        if store is not None:
            store.close()

    def settling(self):
        """A busy look is being retried on the worker (`check()`): the mode cached is the last one, not its answer."""
        worker = self._worker
        return worker is not None and worker.is_alive()

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


def _json_list(raw):
    """A JSON list read leniently: [] for anything that isn't one."""
    try:
        value = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw):
    try:
        value = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _note_id(value):
    """A note id as an int, or None (a `null`, a string that isn't a number, a nested list)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


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
        self.piece_fields = []  # LM11: (piece, "kind" | "title", old, new) written, put back by the value check
        self.dropped = []     # LM11: the pieces' rows the command emptied and deleted (an undo brings them back)
        self.roots = []       # T6: [(root_id, old kind, new kind)] a *Stop reading* wrote (the value check puts it back)

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
        self.piece_fields = []  # LM11: (piece, column, old, new) — a piece's kind or title written, for undo
        self.dropped = []     # LM11: the pieces' rows deleted when emptied, for undo
        self.line_set = False  # set_soon_line: the line moved

    def touch(self, tiers=(), order=False, availability=False, pins=False, within=False):
        """Record a change: any tier in `tiers` that is analysed bumps `order_version`; so does a REFERENCE tier (W-1b:
        its files are the run signature's "reference" part, so one coming, going or re-pointed moves what a run reads),
        unless `within`: the rows only changed places inside their tier, which no run reads there."""
        self.changed = True
        self.tiers.update(t for t in tiers if t in TIERS)
        if order or any(TIERS[t][2] or (t in REFERENCE and not within) for t in tiers if t in TIERS):
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
        try:
            self._wlock = _write_lock_for(db_path)
            self._own = _own_bumps(db_path)
        except BaseException:                    # never left to the collector's plain close (§6.12)
            _close(self.conn, db_path, role)
            raise
        self._depth = 0
        self._cmd = None
        self._repairing = False          # Repair writes past the damage marker it is about to clear
        self._held = False               # inside `held()`: closed at the span's end
        if role != "reader":
            self._added_indexes()

    def _added_indexes(self):
        """ADDED_INDEXES, made at the first open by a writer of a store made before them, under the write lock: one
        read of the schema at every other open. A store not made yet, a newer one, a damaged or busy one (or this
        process inside a write already) is left as it is: a later open makes them. Never a version or data change.
        A4K-7: the copies' hash column and its trigger too (ADDED_HASH_SQL), the column only where it isn't yet."""
        names = ("pairings",) + ADDED_INDEXES + (ADDED_HASH,)
        try:
            have = {r[0] for r in self.conn.execute(f"SELECT name FROM sqlite_master WHERE name IN "
                                                    f"({','.join('?' * len(names))})", names)}
            if "pairings" not in have or have.issuperset(names) or self._wlock.depth:
                return
            if self.conn.execute("PRAGMA user_version").fetchone()[0] > STORE_SCHEMA:
                return
            with self._writing(wait=BUSY_AT_OPEN):
                for sql in ADDED_INDEXES_SQL:
                    self.conn.execute(sql)
                for sql in ADDED_HASH_SQL:
                    if sql.startswith("ALTER") and self._hash_column():   # another open made it meanwhile
                        continue
                    self.conn.execute(sql)
        except (StoreError, sqlite3.Error):
            pass

    def _hash_column(self):
        """A4K-7: whether this store has `items.content_sha256` yet (a busy first open leaves it to a later one)."""
        if not getattr(self, "_hashes", False):              # a reader made with `Store.__new__` has none
            self._hashes = any(r[1] == "content_sha256" for r in self.conn.execute("PRAGMA table_info(items)"))
        return self._hashes

    def close(self):
        """Close the handle, never checkpointing outside the write lock (`_close`, §6.12). Inside `held()`, nothing
        until the span ends."""
        if getattr(self, "_held", False):       # a reader made with `Store.__new__` has none
            return
        _close(self.conn, self.db_path, self.role)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- the one write helper (§6.2, K32) ------------------------------------------------------- #

    @contextmanager
    def _writing(self, begin=True, wait=LOCK_TIMEOUT):
        """Every write and every explicit checkpoint, under the write lock (waited for `wait` s, then StoreBusy).
        Re-entrant: a command called inside another joins the outer transaction; only the outermost call takes the
        OS lock, begins and commits. `query_only` is lifted here and nowhere else."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        if not self._repairing and os.path.exists(damaged_marker(self.db_path)):
            raise StoreReadOnly("the library store is damaged and needs Repair")
        self._wlock.acquire(wait)
        committed = wrote = False
        try:
            changes = self.conn.total_changes
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
                wrote = self.role in OUTSIDE_ROLES and self.conn.total_changes != changes
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
        if wrote:                                # Connect's commit: the copy's trigger
            try:
                _outside_wrote(self)
            except Exception:                    # a committed write never fails for its trigger
                pass

    def checkpoint(self, wait=LOCK_TIMEOUT):
        """A PASSIVE checkpoint (never TRUNCATE: K18), under the write lock like every write."""
        with self._writing(begin=False, wait=wait):
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
        change.piece_fields = cmd.piece_fields             # LM11: (the same lists: a nested command's too)
        change.dropped = cmd.dropped
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
        """The mine line: the top N of Current's AVAILABLE items (a missing item never counts) that count (W-1: a
        watched one while `keep_watched` is off has nothing left to mine)."""
        rule = counts_sql(self._keep_watched())
        ids = [r[0] for r in self.conn.execute(
            f"SELECT id FROM items WHERE tier = 'now' AND availability = 'available' AND {rule} ORDER BY ord, id "
            "LIMIT ?", (n,))]
        if len(ids) < n:
            ids += [r[0] for r in self.conn.execute(
                f"SELECT id FROM items WHERE tier = 'soon' AND availability = 'available' AND {rule} ORDER BY ord, id "
                "LIMIT ?", (n - len(ids),))]
        return ids

    def _keep_watched(self):
        """The library's `keep_watched` option (W-1): 1 when on; absent (every library before it) is off."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'keep_watched'").fetchone()
        try:
            return 1 if row and int(row[0]) else 0
        except (TypeError, ValueError):
            return 0

    def _root_id(self):
        row = self.conn.execute("SELECT id FROM roots WHERE kind = 'library' ORDER BY id LIMIT 1").fetchone()
        return row[0]

    def schedule(self, with_versions=False, with_aside=False):
        """{phase_key: [entries]} for the analysed tiers in (ord, id) order — what `resolve_found_files`
        loads — each entry {physical_path, source_type, title, parent_folder} straight from the columns; a video
        waiting for its subtitle (K5) is never in it, nor an item that doesn't count (W-1: watched, `keep_watched` off).
        With `with_versions`, also the versions, read in the same transaction; with `with_aside`, also `ASIDE`: the
        set-aside items (`sets_aside`, `text_lists`' aside: Finished's items and an analysed tier's items that don't
        count; a video still waiting for its subtitle has no text yet, so never), each {physical_path, source_type},
        in the same transaction."""
        out = {}
        with self._reading():
            keep = self._keep_watched()
            scheduled = _scheduled_sql(keep)
            for tier in ANALYSED:
                out[TIERS[tier][0]] = [
                    {"physical_path": p, "source_type": s, "title": t, "parent_folder": f}
                    for p, s, t, f in self.conn.execute(
                        f"SELECT rel_path, source_type, title, parent_folder FROM items WHERE {scheduled} "
                        "ORDER BY ord, id", (tier,))]
            if with_aside:
                out[ASIDE] = [{"physical_path": p, "source_type": s} for p, s in self.conn.execute(
                    f"SELECT rel_path, source_type FROM items WHERE {sets_aside_sql(keep)} "
                    "AND availability != 'waiting' ORDER BY tier, ord, id")]
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

    def scheduled_ids(self):
        """[(item_id, tier)] of what `schedule` lists, in its order (NOW, Soon, 6+ Months; each tier by ord, id): its
        rows' ids alone, no entry read — the window's numbers read the order with it after every arrival (W4.1)."""
        with self._reading():
            scheduled = _scheduled_sql(self._keep_watched())
            return [(i, tier) for tier in ANALYSED for (i,) in self.conn.execute(
                f"SELECT id FROM items WHERE {scheduled} ORDER BY ord, id", (tier,))]

    def item_keys(self):
        """{rel_key: item_id} of every item, no entry read: a file's `path_key` is its item's `rel_key` (a plan's files
        to items, W4.1)."""
        return dict(self.conn.execute("SELECT rel_key, id FROM items"))

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
        since) and `options` (the Soon line, the mine line, New arrivals, W-1's `keep_watched`). Applying it by id is
        idempotent: a window's own commits come back through it too.
        LM11: `pieces` (rows of FEED_PIECE_FIELDS: id, title, kind) — every piece when full, else the pieces its
        changed rows sit in (a piece's kind or name written feeds its rows: `_set_piece`). A piece no row names is gone.
        A group's `title` None: the window derives "<first item's work's title> + N more"; a run's title is never shown
        (its work's is)."""
        item_cols = ", ".join(FEED_ITEM_FIELDS)
        work_cols = ", ".join(FEED_WORK_FIELDS)
        piece_cols = ", ".join(FEED_PIECE_FIELDS)
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
            if full:
                pieces = self.conn.execute(f"SELECT {piece_cols} FROM pieces").fetchall()
            else:
                at = FEED_ITEM_FIELDS.index("piece_id")
                named = sorted({r[at] for r in items if r[at] is not None})
                pieces = [r for chunk in _chunks(named, 500) for r in self.conn.execute(
                    f"SELECT {piece_cols} FROM pieces WHERE id IN ({','.join('?' * len(chunk))})", chunk)]
        return {"full": full, "epoch": now_epoch, "version": version,
                "items": [dict(zip(FEED_ITEM_FIELDS, r)) for r in items],
                "works": [dict(zip(FEED_WORK_FIELDS, r)) for r in works], "gone": gone,
                "pieces": [dict(zip(FEED_PIECE_FIELDS, r)) for r in pieces],
                "options": {"soon_line": meta.get("soon_line"), "mine_line": meta.get("mine_line", MINE_LINE_DEFAULT),
                            "arrivals_on": meta.get("arrivals_on", 0), "keep_watched": meta.get("keep_watched", 0)}}

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

    def count_old_stones(self):
        """In the helper's run, once per library (meta `STONES_COUNTED`): watched marks made before a mark counted (build
        2's stones) leave the list at the first start (Q3 A), so the journey must hear it — `order_version` moves once
        when such a stone sits in a studied tier while `keep_watched` is off (the background Generate follows); a
        library without one is only stamped. One transaction. Returns True when it moved the order."""
        if STONES_COUNTED in self._meta():
            return False
        with self._command("count_old_stones", "sync") as cmd:
            if STONES_COUNTED in self._meta():       # another helper got there first
                return False
            self._set_meta({STONES_COUNTED: 1})
            moved = not self._keep_watched() and self._watched_aside()
            if moved:
                cmd.touch(order=True)
            return moved

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

    def retitle_folder_works(self):
        """In the helper's run: a title still named by its folder's path (`Show/S01`, as a season folder's work was
        named before alpha 7) gets its folder's title (`folder_title`: `Show Season 1`), the path kept among its other
        titles (search still finds it). Never a title the user named, one with no folder or one already its folder's;
        no item, order or folder key touched, so it is done once and every later run finds nothing. One command (the
        window reads the works). Returns the ids retitled."""
        found = [(w, folder_title(t), t) for w, t, fk in self.conn.execute(
            "SELECT id, title, folder_key FROM works WHERE title_by_user = 0 AND folder_key IS NOT NULL "
            "AND instr(title, '/') > 0")                       # a path title has a '/': the rest is never read again
            if path_key(t) == fk and folder_title(t) != t]
        if not found:
            return []
        with self._command("retitle_folder_works", "sync") as cmd:
            done = []
            for wid, title, old in found:
                row = self.conn.execute("SELECT title, titles, folder_key, title_by_user FROM works WHERE id = ?",
                                        (wid,)).fetchone()
                if row is None or row[0] != old or row[2] != path_key(old) or row[3]:
                    continue                    # renamed, merged or gone since the read: as it is now, it stands
                titles = row[1]
                others = [t for t in json.loads(titles or "[]") + [old] if t != title]
                self.conn.execute("UPDATE works SET title = ?, titles = ? WHERE id = ?",
                                  (title, _dumps(list(dict.fromkeys(others))), wid))
                self._rekey_work(wid)
                cmd.fed_works.add(wid)
                done.append(wid)
            if done:
                cmd.touch()
            return done

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
        process's own bumps did; a new epoch always did. A receipt or a pin never does; a watched mark only when it
        moves what counts (W-1: `set_watched`)."""
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
            # --- P4.1 L2 (TF fix 8, G1.6-10): out of Finished by any path, its cards come back into the order ---
            self._back_in_order(cmd, change, [r[0] for r in ordered if r[1] == "graduated" and tier != "graduated"])
            # --- end P4.1 L2 ---
            cmd.touch({r[1] for r in ordered} | {tier}, within=all(r[1] == tier for r in ordered))
            for item_id in block:
                cmd.event(item_id, "placed", int(by == "user" if explicit is None else explicit),
                          by if by != cmd.by else None)
                if by != cmd.by:
                    cmd.event_by[item_id] = by
            return change

    # --- P4.1 L2 (TF fix 8; adversary S5): leaving Finished brings an item back into the learning order ---
    def _back_in_order(self, cmd, change, ids):
        """Items leaving Finished by a move or a tier change (the command line's `place`, the Content Manager's
        Promote / Demote — not only *Put back* and a join): `in_learning_order` 1, as `put_back_finished` and `join` set
        it (G1.6-10: anything taken out comes back), the values replaced on the change for its undo, and `pins_version`
        bumped (T-4: its cards are owed back to Anki). Without it a Finished item taken out and moved to Current kept
        its new cards suspended at every re-order. W-1 (Q1 A, Sonic 2026-10-22): its stones clear too (`watched` 0),
        or a show put back would bring none of its words back; on the same change, so one Undo puts both back."""
        status = []
        for part in _chunks(list(ids), 500):
            marks = ",".join("?" * len(part))
            for i, order, watched in self.conn.execute(
                    f"SELECT id, in_learning_order, watched FROM items WHERE id IN ({marks})", part):
                if order != 1:
                    status.append((i, "in_learning_order", order, 1))
                if watched != 0:
                    status.append((i, "watched", watched, 0))
        if not status:
            return
        for column, value in (("in_learning_order", 1), ("watched", 0)):
            self.conn.executemany(f"UPDATE items SET {column} = ? WHERE id = ?",
                                  [(value, i) for i, c, *_r in status if c == column])
        cmd.feed(i for i, *_r in status)
        cmd.touch(pins=any(c == "in_learning_order" for _i, c, *_r in status))
        change.status = list(change.status) + status
    # --- end P4.1 L2 ---

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
        # LM11: past a group it jumps the group whole (inside, it would cut it); within its own group it moves there
        held = self.conn.execute("SELECT piece_id FROM items WHERE id = ?", (target,)).fetchone()[0]
        if held is not None and any(r[10] != held for r in block) and self._is_group(held):
            target = self._past_group(target, -1 if up else 1)
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
                where = ("after", self._past_group(last[0])) if last else self._tier_top(tier, excl)   # LM11 (G4)
                groups.setdefault(where, []).append(item_id)
            for where, group in groups.items():
                self._put(tier, group, where, cmd.version)
            # --- P4.1 L2 (TF fix 8, G1.6-10): Promote / Demote out of Finished brings its cards back into the order ---
            self._back_in_order(cmd, change, [i for i in moving if rows[i][1] == "graduated" and tier != "graduated"])
            # --- end P4.1 L2 ---
            if tier == "graduated":
                self.conn.executemany("UPDATE items SET graduated_at = ? WHERE id = ?",
                                      [(_now(), i) for i in moving])
                # --- W3.2 (IK-L2-3, A2 #28): an arrival to Finished is recorded as already watched (undone with it)
                came = [i for i in moving if rows[i][1] == "arrivals"]
                if came:
                    change.status = [(i, "watched", old, 1) for i, old in self.conn.execute(
                        f"SELECT id, watched FROM items WHERE id IN ({','.join('?' * len(came))})", came).fetchall()
                        if old != 1]
                    self.conn.executemany("UPDATE items SET watched = 1 WHERE id = ?",
                                          [(i,) for i, *_r in change.status])
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
                    return ("after", self._past_group(last[0]), tier)        # LM11 (G4): never inside a group
            return ("top", "now")
        folder = _entry_folder(entry)
        last = self._folder_last(fallback_tier, folder, excl) if folder else None
        return ("after", self._past_group(last[0]), fallback_tier) if last else ("top", fallback_tier)

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

    def insert(self, files, tier, placement="show", started_at=None, entries=None, check=None, origins=None):
        """Add the files the command itself copied (Add Files, Add Folder, the preview), as one command:
        a, b, c lands a, b, c (L-Q6). `placement` "show" follows §6.10 rule 3 with `tier` (the tab
        chosen) for a directory that holds no item yet; "top" puts them at the top of `tier` (the
        preview). A file already an item is left where it is and reported in `change.existing`.
        `origins` (K21: + Add / a drop): {file as given: where it was copied from} — see `_add_origins`."""
        prepared = self._prepare(files, entries, "Manual Import")
        return self._add(prepared, tier, placement, None, started_at, check, "insert", origins=origins)

    def insert_at(self, files, anchor_id, before=True, started_at=None, entries=None, check=None, origins=None):
        """`insert` at an anchor item: the files land contiguous, in the order given, before or after it,
        in its tier (the user chose the place, so Q4-9 doesn't apply)."""
        prepared = self._prepare(files, entries, "Manual Import")
        return self._add(prepared, None, "anchor", (anchor_id, before), started_at, check, "insert_at",
                         origins=origins)

    def _add(self, prepared, tier, placement, anchor, started_at, check, kind, by="user", explicit=1, origins=None):
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
            if origins:
                self._add_origins(zip(ids, [t[1] for t in taken] + new), origins)
            cmd.touch(set(dest_tier), availability=any(it[4][2] == "missing" for it in new))
            for item_id in ids:
                cmd.event(item_id, "placed", explicit)
            return change

    def _add_origins(self, added, origins):
        """K21 (laptop fixes): inside `_add`'s command, an origin record (B1's row, `_origin_record`'s shape) on each
        item it added from a file + Add or a drop copied in from outside the data folder (`origins` {file as given:
        {origin, size, mtime_ns, sha256, show, video_path?, video_size?}}, `moves._copy_in`'s): no source holds it
        (`root` None), `via` "add". So a folder read later takes the original as known (SRC-7: never a second item; a
        Remove's exclusion keeps it out, SRC-8) and Connect looks beside the original for its video. One origin, one
        row: the same original added again (changed since: other bytes, a new item) moves its row to the new item —
        only from an add's row or a row whose item is gone; a row a folder's look recorded stays its item's (LF-7: that
        item stays followed and restorable) and the new item records none."""
        for item_id, item in added:
            f = origins.get(item[0])
            if not f:
                continue
            old = self.conn.execute("SELECT p.pairing, i.id FROM pairings p LEFT JOIN items i ON i.id = p.item_id "
                                    "WHERE p.content_key = ?", (origin_key(f["origin"]),)).fetchone()
            if old is not None and old[1] is not None and (_json_dict(old[0]) or {}).get("via") != "add":
                continue
            record = dict(_origin_record(None, f["origin"], f), via="add")
            self.conn.execute("INSERT OR REPLACE INTO pairings (content_key, item_id, pairing, paired_at) "
                              "VALUES (?, ?, ?, ?)", (origin_key(f["origin"]), item_id,
                                                      json.dumps(record, sort_keys=True, ensure_ascii=False), _now()))

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
        settings.json (`placing_rules`; None or empty: it waits); a back-fill places by no rule.

        3.0 (SRC K3, SRC-7, never a duplicate): an episode already in is never a second item — see `_register`. A
        source's `Library` copy hato's file took over (`change.unused`) goes to the trash after the commit (inside an
        outer command: the caller's)."""
        outer = self._cmd is not None
        change = self._register(path, pairing, backfill, rules)
        for rel in () if outer else getattr(change, "unused", None) or ():
            try:
                trash_file(self.data_dir, rel)
            except OSError as e:                   # held open: left in `Library`, where the sync never adopts it (B2)
                print(f"Warning: a copy no item holds couldn't go to the trash ({rel}): {e!r}")
        return change

    def _register(self, path, pairing, backfill, rules):
        """`register`'s command. K3: when hato's path has no row — or only the row the disk sync made for it a moment
        before (`_sync_drop`: taken out in this command, R1) — the episode may be in already: a folder's video waiting
        for its subtitle takes hato's file in place (`_waiting_video`, K5's fill, R3); a source's `Library` copy
        holding the video is pointed at hato's file (the one hato timed: both orders end alike, R2), the copy left
        unused; any other live item holding the video or the same bytes (`_duplicate_of`) keeps it, hato's file kept
        out by a `duplicate` exclusion. hato's record goes on that item; hato's file is never deleted or moved."""
        content_key = pairing["content_key"]
        rel = library_rel(self.data_dir, path)
        if rel is None:
            raise NotInLibrary(f"not in the library: {path}")
        prepared = self._prepare([rel], None, "hato")     # normalised: one key per file (a/../b.srt is b.srt)
        by = _producer(pairing)
        full = os.path.join(self.data_dir, *prepared[0][1].split("/"))
        seen = self._twin_seen(full, content_key, pairing)    # F12: read and hashed before the write lock
        with self._command("register", by) as cmd:
            meta = cmd.meta
            _p, rel, key, entry, fp = prepared[0]
            row = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (key,)).fetchone()
            change = None
            # K3: the twin found before the command, its one item checked again in it (F12)
            gap = twin = None
            if row is None or (not backfill and self._sync_drop(row[0], rel, pairing)):   # a back-fill's row is old
                gap, twin = self._twin_now(seen, full, content_key, pairing)
                if (gap is not None or twin is not None) and row is not None:
                    self._take_out(cmd, row[0])            # R1: the sync's row for a file that is an episode already
                    row = None
            filled = self._fill_gap(cmd, gap, prepared[0], {}) if gap is not None else None
            if filled is not None:                         # R3: the folder's waiting video takes hato's subtitle
                item_id = filled
                change = self._change(cmd, "register")
                change.took_over = change.pairing_item = item_id
            elif twin is not None:                         # (a gap no longer waiting fills nothing: a new item below)
                item_id, copy = twin                       # K3 (SRC-7): the episode is in already — no item for it
                change = self._change(cmd, "register")
                change.pairing_item = item_id
                if copy is not None:                       # R2: the source item reads hato's file; its copy unused
                    self._repoint(item_id, rel, fp[0], fp[1])
                    cmd.touch({self.conn.execute("SELECT tier FROM items WHERE id = ?", (item_id,)).fetchone()[0]},
                              availability=True)
                    change.took_over, change.unused = item_id, [copy]
                else:
                    change.duplicate = rel
                    if not self.conn.execute("SELECT 1 FROM exclusions WHERE kind = 'duplicate' AND pattern = ?",
                                             (key,)).fetchone():
                        self.conn.execute("INSERT INTO exclusions (root_id, pattern, kind, created_at) "
                                          "VALUES (?, ?, 'duplicate', ?)", (self._root_id(), key, _now()))
                        change.excluded_key = key          # N1: its Undo takes the exclusion back too
                        cmd.touch()
            elif row is None:
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

    def remove(self, ids, trashed_paths=None, check=None, by="user", kind="remove", exclude=True, why=None):
        """Rows → the trash table, each with its neighbours just before the removal (removed ones
        included), its entry, its state, its pairings and Anki links, and where its file went
        (`trashed_paths`: {id: path relative to data/<lang>}, the caller's file work). The trash rows are
        written first, then the item rows deleted; their pairings and links follow by ON DELETE CASCADE. An item that
        came from a source folder leaves an exclusion per origin (SRC-8 / S6: `_exclude_origins`); its Put back or
        Undo deletes them. `exclude=False` (K21: the Undo of an add — + Add's origins) leaves none: an Undo is no
        Remove, so a folder read later brings the file in as any new one. `why` (K2, alpha 4): what took them out, kept
        in each trash row's state — None a learner's Remove, "skip" *Never read this folder*, "edition" a book's part
        given up; an Undo of an add keeps its `kind` — so the Removed list (`removed`) names only his own Removes."""
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
                state = {k: v for k, v in item.items()            # A4K-7: the hash is a cache, never in the copy
                         if k not in ("entry", "rel_path", "tier", "ord", "content_sha256")}
                state = {"columns": state, "pairings": pairs.get(r[0], []), "anki_links": links.get(r[0], [])}
                if why or kind != "remove":
                    state["why"] = why or kind
                trash_rows.append((r[0], item["root_id"], item["rel_path"], item["tier"], near[r[0]][0],
                                   near[r[0]][1], item["entry"], _dumps(state), trashed_paths.get(r[0]), now))
            first = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM trash").fetchone()[0] + 1
            self.conn.executemany(
                "INSERT INTO trash (item_id, root_id, rel_path, tier, prev_id, next_id, entry, item_state, "
                "trashed_path, removed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", trash_rows)
            change.trash_ids = list(range(first, first + len(trash_rows)))
            change.excluded = self._exclude_origins(pairs, now) if exclude else []   # SRC-8: never taken in again
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
                    size, mtime_ns, availability = cols.get("size"), cols.get("mtime_ns"), \
                        "waiting" if cols.get("availability") == "waiting" else "missing"
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
                self._let_origins_back([k for k, _p, _at in state["pairings"]])       # its exclusions go (SRC-8)
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
        its folder below the tier folder (`folder_title`: `Show/S01` is `Show Season 1`, the path kept among its other
        titles). A loose file's work is its show's, read from its name (`_stranded_work`)."""
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
        if wid is None and fk is None:
            return self._stranded_work(rel, title, cmd, cache)
        if wid is None:
            below = _below_tier(rel)
            wid = self._new_work(folder_title(below), fk, cmd, titles=(below,))
        if cache is not None:
            cache[fk] = wid
        return wid

    def _stranded_work(self, rel, title, cmd, cache=None):
        """A loose file's work (SRC-11): one in hato's drop folder or directly in a tier folder has no show folder, so
        its show is read from its file name (`show_of_name`): the work whose title (or another title) folds the same,
        else a new work titled by that show; a name no show is read from stays a title of its own, by its title. Only a
        new item comes here (`_settle_works`): an existing work is never regrouped and never renamed."""
        show = show_of_name(rel.rsplit("/", 1)[-1])
        if show is None:
            return self._new_work(title or rel.rsplit("/", 1)[-1], None, cmd)
        key = search_fold(show, self.language)
        if cache is not None and ("show", key) in cache:
            return cache[("show", key)]
        row = self.conn.execute("SELECT id FROM works WHERE instr(char(10) || search_key || char(10), ?) > 0 "
                                "ORDER BY id LIMIT 1", ("\n" + key + "\n",)).fetchone()
        wid = row[0] if row else self._new_work(show, None, cmd)
        if cache is not None:
            cache[("show", key)] = wid
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
                for (text,) in self.conn.execute(f"SELECT pairing FROM pairings p WHERE item_id IN "
                                                 f"(SELECT id FROM items WHERE work_id = ?) AND {_PREFERRED_ROW}",
                                                 (work,)):
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
        title of its own, named by its file (or the show read from it, SRC-11): on the first hand-off the record's title
        takes it, as `register` places a new drop (`_work_by_record`, else a new title named by its show). Only that
        title: alone, never paired, no id, nothing of the user's in it. The emptied title goes in the helper's run
        (`tidy_works`)."""
        if folder_key_of(rel) is not None or \
                self.conn.execute("SELECT 1 FROM pairings WHERE item_id = ?", (item_id,)).fetchone():
            return
        cur, title = self.conn.execute("SELECT work_id, title FROM items WHERE id = ?", (item_id,)).fetchone()
        w = self._work_row(cur) if cur is not None else None
        if w is None or w["title"] not in (title, show_of_name(rel)) or w["title_by_user"] or \
                w["media_type_by"] == "user" or w["cover_locked"] or w["cover_source"] == "user" or \
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
        self._settle_kinds(cmd, {r[0] for r in self.conn.execute(                  # LM11: one work's group: a run
            "SELECT DISTINCT piece_id FROM items WHERE work_id = ?", (keep_id,))})
        self.conn.executemany("UPDATE works SET anilist_id = NULL, tmdb_id = NULL, youtube_channel = NULL WHERE id = ?",
                              [(o["id"],) for o in others])           # the unique ids free before the kept takes them
        self._set_work_fields(cmd, change, keep_id, fields)
        self._carry_group(keep_id, [o["id"] for o in others])      # LM2: the show's group goes with it
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
        they are (each is still one title's; a group left holding one is a run: `_merge_into`). Undo restores the works
        and each item's work. LM11 (G1): refused when the ids say two shows (`TITLES_APART`)."""
        with self._command("merge_works") as cmd:
            apart = self._titles_apart([keep_id] + list(other_ids))
            if apart:
                raise ValueError(apart)
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
        # Hon (H-6): a row waiting for its text (an audiobook beside its book) is no row the line counts — it stays
        # with the row before it, on the same side of the line
        now = self.conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'now' AND availability != 'waiting'").fetchone()[0]
        if now > n:
            rows = self.conn.execute("SELECT id, availability FROM items WHERE tier = 'now' ORDER BY ord, id").fetchall()
            at, seen = 0, 0
            if n > 0:
                for at, r in enumerate(rows):                       # the n-th row with text ...
                    seen += r[1] != "waiting"
                    if seen == n:
                        break
                at += 1
                while at < len(rows) and rows[at][1] == "waiting":  # ... and the waiting rows right after it stay
                    at += 1
            down = [r[0] for r in rows[at:]]
            self._put("soon", down, ("top",), cmd.version)
            cmd.touch(CURRENT)
        elif now < n:
            up, need = [], n - now
            for item_id, availability in self.conn.execute("SELECT id, availability FROM items WHERE tier = 'soon' "
                                                           "ORDER BY ord, id"):
                if need == 0 and availability != "waiting":
                    break
                up.append(item_id)
                need -= availability != "waiting"
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
        """A new piece (`like`: of that piece's kind and name — a new GROUP starts unnamed, the window's "<first show> +
        N more": LM11 G4). Its id is past every piece id ever issued, never one a deleted piece held (K30's rule for
        items; LM11 G3: an undo puts a deleted group back under its own id, which nothing else can have taken)."""
        base = self.conn.execute("SELECT title, kind FROM pieces WHERE id = ?", (like,)).fetchone() if like else None
        kind = base[1] if base else "run"
        piece = _next_id(self.conn, "pieces")
        _set_seq(self.conn, "pieces", piece)
        self.conn.execute("INSERT INTO pieces (id, title, kind, created_at) VALUES (?, ?, ?, ?)",
                          (piece, None if kind == "group" else base[0] if base else title, kind, _now()))
        return piece

    def _fix_pieces(self, cmd):
        """Pieces drawn by id (05 §5.2), for what the command touched: a whole piece moved keeps its id (4); items
        moved out of a piece, and new items, join the piece of their own work they land inside or beside, else start
        one (3, 4); a piece something foreign landed inside splits there — its first run keeps the id (5); an undo
        puts items back in the pieces they came from (`cmd.hints`); an emptied piece row is deleted (7).
        LM11 (groups, kind 'group'): a row landing beside a group stays outside it, and a group never folds into a piece
        beside it; a row (or a whole part) landing between two of its rows joins it (GI1, PROVISIONAL); an item moved
        within its own group stays in it — NOW and Soon one tier for that (G1) — one whose title changed in place
        (*Not part of this title*) too; a group's items
        that land in Finished or New arrivals leave it (each to its own work's piece there: G4 "a finishing item goes
        to Finished under its own work"); what is left is settled by `_settle_kinds`, an emptied group's row kept on the
        change for its undo (`cmd.dropped`, a run's too: ids are never reused, G3)."""
        conn = self.conn
        touched = cmd.moved | cmd.reworked
        info = {}
        for chunk in _chunks(list(touched), 500):
            for r in conn.execute(f"SELECT id, tier, piece_id, work_id FROM items WHERE id IN "
                                  f"({','.join('?' * len(chunk))})", chunk):
                info[r[0]] = list(r[1:])
        news = set()
        if info:
            known = {v[1] for v in info.values() if v[1] is not None} | {h for h in cmd.hints.values() if h is not None}
            kinds = {r[0]: r[1] for chunk in _chunks(sorted(known), 500)
                     for r in conn.execute(f"SELECT id, kind FROM pieces WHERE id IN ({','.join('?' * len(chunk))})",
                                           chunk)}
            pieces = set(kinds)
            groups = {p for p, k in kinds.items() if k == "group"}
            is_group = lambda p: p is not None and (p in groups if p in kinds else self._is_group(p))  # noqa: E731
            whole = {}
            for p in {v[1] for v in info.values() if v[1] is not None}:
                ids = [r[0] for r in conn.execute("SELECT id FROM items WHERE piece_id = ?", (p,))]
                whole[p] = all(i in info for i in ids) and \
                    not (p in groups and any(info[i][0] in NO_GROUP_TIERS for i in ids))     # LM11: out of the group
            sets, fresh, olds = [], set(), {}
            for item_id, v in info.items():
                old = v[1]
                olds[item_id] = old
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
            # --- LM11: an item moved within its own group stays in it (beside another of its rows, or beside a row that
            # stays so): a reorder inside the group, never "a foreign drop"
            back = {}
            # G1: NOW and Soon are one tier for a group — a row at the line's edge has its neighbour across it
            across = {i: self._line_edge(info[i][0]) for i in fresh if olds[i] in groups and
                      (info[i][0] == "soon" and near[i][0][0] is None or info[i][0] == "now" and near[i][1][0] is None)}
            while True:
                more = {i: olds[i] for i in fresh if i not in back and olds[i] in groups
                        and info[i][0] not in NO_GROUP_TIERS
                        and any(n is not None and (n[1] == olds[i] or back.get(n[0]) == olds[i])
                                for n in list(near[i]) + [across.get(i)])}
                if not more:
                    break
                back.update(more)
            if back:
                self._set_pieces(cmd, [(g, i) for i, g in back.items()])
                cmd.repieced += [(i, None, g) for i, g in back.items()]
                for i, g in back.items():
                    info[i][1] = g
                fresh -= set(back)
            # --- end LM11
            # GI1, PROVISIONAL (Sonic 2026-10-21, accepted for building, to be checked in use; asked of him, LM11-Q1):
            # dropping in is putting in — a row (a new one, one moved, a whole part) landing between two rows of one
            # group joins that group, never cuts it; at its edge it stays outside. A group dropped inside one cuts it.
            # (No group stands in Finished or New arrivals, so neither does a row this puts in one.)
            inside = lambda b, a: b[1] is not None and b[1] == a[1] and is_group(b[1])     # noqa: E731
            # a whole piece put back beside a piece of its own title becomes part of it (05 §5.2 #4: a season put
            # back together); an undo's pieces stay as they were. LM11: never a group, never into one (but GI1)
            for p, ids in by_piece.items():
                if any(i in cmd.hints for i in ids) or not whole.get(p) or p in groups:
                    continue
                firsts = [i for i in ids if i in near and near[i][0][1] != p]
                lasts = [i for i in ids if i in near and near[i][1][1] != p]
                if len(firsts) != 1 or len(lasts) != 1:
                    continue                                    # not one run: the split below decides
                work = info[ids[0]][2]
                before, after = near[firsts[0]][0], near[lasts[0]][1]
                if inside(before, after):
                    into = before[1]                            # GI1: dropped between two rows of a group: into it
                else:
                    into = before[1] if before[1] is not None and before[2] == work and not is_group(before[1]) else \
                        after[1] if after[1] is not None and after[2] == work and not is_group(after[1]) else None
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
                if before[1] is not None and before[1] == after[1] and before[2] == work and after[2] == work \
                        and not is_group(before[1]) or inside(before, after):     # GI1
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
                news.update(self._split_runs(p, placed, cmd, view))
            news |= affected
            for run in pending:
                work = info[run[0]][2]
                before = self._side(run[0], -1)
                after = self._side(run[-1], 1)
                if before is not None and before[2] == work and before[1] is not None and not is_group(before[1]):
                    piece = before[1]
                elif after is not None and after[2] == work and after[1] is not None and not is_group(after[1]):
                    piece = after[1]
                else:
                    title = conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()
                    piece = self._new_piece(title=title[0] if title else None)
                self._set_pieces(cmd, [(piece, i) for i in run])
                cmd.repieced += [(i, None, piece) for i in run]
        self._settle_kinds(cmd, news | cmd.pieces_left)                     # LM11
        if cmd.pieces_left:
            for chunk in _chunks(sorted(cmd.pieces_left), 500):
                empty = (f"id IN ({','.join('?' * len(chunk))}) AND NOT EXISTS "
                         "(SELECT 1 FROM items WHERE items.piece_id = pieces.id)")
                cmd.dropped += [tuple(r) for r in conn.execute(           # LM11: its row, for its undo (an id is
                    f"SELECT id, title, kind, created_at FROM pieces WHERE {empty}", chunk)]   # never reused: G3)
                conn.execute(f"DELETE FROM pieces WHERE {empty}", chunk)

    # --- LM11: a piece's kind and name ------------------------------------------------------------------------- #
    def _line_edge(self, tier):
        """LM11 G1: (id, piece_id, work_id) of the row across the Soon line from `tier`'s edge — NOW's last row for
        Soon's first, Soon's first for NOW's last — or None."""
        sql = "ORDER BY ord DESC, id DESC" if tier == "soon" else "ORDER BY ord, id"
        return self.conn.execute(f"SELECT id, piece_id, work_id FROM items WHERE tier = ? {sql} LIMIT 1",
                                 ("now" if tier == "soon" else "soon",)).fetchone()

    def _is_group(self, piece):
        row = self.conn.execute("SELECT kind FROM pieces WHERE id = ?", (piece,)).fetchone()
        return row is not None and row[0] == "group"

    def _set_piece(self, cmd, piece, column, value):
        """A piece's `kind` or `title` written inside the command, the old value kept on it for the undo's value check
        (`_undo_piece_fields`); its rows fed (the feed's piece rows ride on them)."""
        row = self.conn.execute(f"SELECT {column} FROM pieces WHERE id = ?", (piece,)).fetchone()
        if row is None or row[0] == value:
            return
        self.conn.execute(f"UPDATE pieces SET {column} = ? WHERE id = ?", (value, piece))
        cmd.piece_fields.append((piece, column, row[0], value))
        cmd.feed(r[0] for r in self.conn.execute("SELECT id FROM items WHERE piece_id = ?", (piece,)))
        cmd.touch()

    def _settle_kinds(self, cmd, pieces):
        """LM11 (G4): a group left holding one work's items, or standing in Finished or New arrivals, is a run again
        (an emptied one is left to go whole: its row is the undo's)."""
        marks = ",".join("?" * len(NO_GROUP_TIERS))
        for chunk in _chunks(sorted(p for p in pieces if p is not None), 500):
            for piece, works, apart in self.conn.execute(
                    f"SELECT p.id, COUNT(DISTINCT i.work_id), MAX(i.tier IN ({marks})) FROM pieces p "
                    f"JOIN items i ON i.piece_id = p.id WHERE p.kind = 'group' AND p.id IN "
                    f"({','.join('?' * len(chunk))}) GROUP BY p.id", list(NO_GROUP_TIERS) + chunk).fetchall():
                if works <= 1 or apart:
                    self._set_piece(cmd, piece, "kind", "run")

    def _past_group(self, item_id, direction=1):
        """LM11 (G4): a row placed beside `item_id` by a rule (after its show, after its folder's last) never lands
        inside a group: the group's last row (its first, `direction` -1), else `item_id`."""
        row = self.conn.execute("SELECT i.piece_id FROM items i JOIN pieces p ON p.id = i.piece_id "
                                "WHERE i.id = ? AND p.kind = 'group'", (item_id,)).fetchone()
        if row is None:
            return item_id
        order = "ord DESC, id DESC" if direction > 0 else "ord, id"
        return self.conn.execute(f"SELECT id FROM items WHERE piece_id = ? ORDER BY {order} LIMIT 1",
                                 (row[0],)).fetchone()[0]

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
        place keeps the id (else the first run), each other run becomes a piece of its own. LM11: a group is cut where
        the tier changes or a row stands between, never where the work does (in Finished and New arrivals, where no
        group lives, it is), and never at the Soon line (G1). -> the pieces it made."""
        conn = self.conn
        members = conn.execute("SELECT id, tier, ord, work_id FROM items WHERE piece_id = ? ORDER BY tier, ord, id",
                               (piece,)).fetchall()
        if len(members) <= 1:
            return []
        group = self._is_group(piece)

        first, last = members[0], members[-1]
        span = None                # {id: position} of the rows from its first member to its last, read at once
        if view is None and first[1] == last[1]:
            rows = conn.execute("SELECT id FROM items WHERE tier = ? AND (ord, id) >= (?, ?) AND (ord, id) <= (?, ?) "
                                "ORDER BY ord, id LIMIT ?", (first[1], first[2], first[0], last[2], last[0],
                                                             4 * len(members) + 64)).fetchall()
            if rows and rows[-1][0] == last[0]:                # a piece scattered wider than that: one look per gap
                if len(rows) == len(members) and (len({m[3] for m in members}) == 1 or
                                                  group and first[1] not in NO_GROUP_TIERS):
                    return []
                span = {r[0]: n for n, r in enumerate(rows)}

        def gap(a, b):
            if a[1] != b[1] and group and a[1] in CURRENT and b[1] in CURRENT:
                # LM11 G1: NOW and Soon are one tier for a group (Current in one order, the line its boundary): cut
                # only if a row stands after its last NOW row or before its first Soon row
                between = conn.execute("SELECT 1 FROM items WHERE (tier = ? AND (ord, id) > (?, ?)) OR (tier = ? AND "
                                       "(ord, id) < (?, ?)) LIMIT 1", (a[1], a[2], a[0], b[1], b[2], b[0])).fetchone()
                return between is not None
            if a[1] != b[1] or (a[3] != b[3] and not (group and a[1] not in NO_GROUP_TIERS)):
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
            return []
        keep = next((r for r in runs if any(m[0] not in placed for m in r)), runs[0])
        made = []
        for r in runs:
            if r is keep:
                continue
            new = self._new_piece(like=piece)
            made.append(new)
            ids = [m[0] for m in r]
            self._set_pieces(cmd, [(new, i) for i in ids])
            cmd.repieced += [(i, piece, new) for i in ids]
        return made

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
        """A new piece of the items from `at_item_id` to the piece's end. Nothing moves. LM11: a group's halves are
        groups (the second one unnamed: a new group, G4), each holding one work's items a run (`_settle_kinds`)."""
        with self._command("split") as cmd:
            items = self._piece_items(piece_id)
            at = [r[0] for r in items].index(at_item_id) if at_item_id in [r[0] for r in items] else -1
            if at <= 0:
                return None
            new_piece = self._new_piece(like=piece_id)
            moved = items[at:]
            self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?",
                                  [(new_piece, cmd.version, r[0]) for r in moved])
            cmd.feed(r[0] for r in moved)
            change = self._change(cmd, "split")
            change.pieces = {"items": [(r[0], piece_id, r[3]) for r in moved], "created": [new_piece],
                             "deleted": []}
            cmd.touch()
            self._settle_kinds(cmd, (piece_id, new_piece))         # LM11
            return change

    def _part(self, piece_id):
        """A piece's rows (id, tier, ord, changed_in, work_id) in (tier, ord, id)."""
        rows = self.conn.execute("SELECT id, tier, ord, changed_in, work_id FROM items WHERE piece_id = ?",
                                 (piece_id,)).fetchall()
        return sorted(rows, key=lambda r: (TIERS[r[1]][3], r[2], r[0]))

    def _titles_apart(self, works):
        """LM11 (G1): the reason *Same show as…* is refused — two of `works` carry different AniList ids, TMDB ids or
        YouTube channels (both set, different: `TITLES_APART`'s words) — or None (one side unset merges)."""
        rows = [self._work_row(w) for w in works if w is not None]
        for column in TITLES_APART:
            if len({r[column] for r in rows if r and r[column] is not None}) > 1:
                return TITLES_APART[column]
        return None

    def join(self, piece_ids, ahead=False, how="parts"):
        """THE piece rule (LM11, Sonic 2026-10-21: the same-title join, *Same show as…* and a group are one rule): the
        other pieces' items move to just after the first piece's last item — "a join across sections lands where the
        target part is" (W1.2 §8.2), across tiers or with other items between — and become one piece; one command,
        one undo (journalled as `join`). `how`:
        - "parts" (05 §5.2 #6): one title's pieces; two titles' refused (make them one title, or a group).
        - "titles" (*Same show as…*, P-LF-4: the window's ⋯ menu, behind its confirm): the others' titles are merged
          into the first piece's (`merge_works`' body: its title kept) in the same command, so its one undo makes them
          two titles and two pieces again. Refused when the ids say two shows (`TITLES_APART`).
        - "group" (G1: a drop on another show): one piece of kind 'group' at the first one's place, title NULL (the
          window's "<first show> + N more" until renamed; a group joined onto keeps its name); no work changes. Never
          in Finished or New arrivals; one left with one work's items is a run (`_settle_kinds`).
        W3.2: `ahead` — they go just before the first piece's first item instead (the part coming in holds the earlier
        episodes: episode order, E22). Items that come in from Finished have their cards back in the learning order
        (`in_learning_order` 1, as `put_back_finished`: anything taken out comes back, G1.6-10); items that come in
        from New arrivals are placed (a `placed` event, as `move`'s) — in the same command, undone with it.
        -> the change (`change.piece_id`: the joined piece), or None."""
        if how not in JOIN_HOW:
            raise ValueError(f"unknown join {how!r}")
        piece_ids = list(dict.fromkeys(piece_ids))
        if len(piece_ids) < 2:
            return None
        with self._command("join") as cmd:
            return self._join(cmd, [(p, self._part(p), True) for p in piece_ids], ahead, how)

    def group(self, piece_ids=(), item_ids=()):
        """LM11 *Group…* / a drop onto a group (`add_to_group`): `join(how="group")` of the pieces given, in order, then
        of the items given — each taken out of its piece (a run of one piece's items moves as one; the rest of that
        piece stays one run each side: the settling step cuts it) in the list's order. The group stands at the first
        one's place (the first piece's, else the topmost item's). One command, one undo, journalled as `join`.
        -> the change (`change.piece_id`: the group), or None."""
        piece_ids = list(dict.fromkeys(piece_ids))
        with self._command("join") as cmd:
            parts = [(p, self._part(p), True) for p in piece_ids]
            taken = {r[0] for _p, rows, _w in parts for r in rows}
            ids = [i for i in dict.fromkeys(item_ids) if i not in taken]
            picked = {}
            for chunk in _chunks(ids, 500):
                for r in self.conn.execute(f"SELECT id, tier, ord, changed_in, work_id, piece_id FROM items "
                                           f"WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                    picked[r[0]] = r
            runs = []                       # [piece, rows, the piece's members, the member after the run's last]
            for r in sorted(picked.values(), key=lambda r: (TIERS[r[1]][3], r[2], r[0])):
                if r[5] is None:
                    continue
                if runs and runs[-1][0] == r[5] and runs[-1][3] == r[0]:
                    runs[-1][1].append(r[:5])                   # the next of the same piece's rows: one run
                else:
                    runs.append([r[5], [r[:5]], [m[0] for m in self._part(r[5])], None])
                members = runs[-1][2]
                at = members.index(r[0])
                runs[-1][3] = members[at + 1] if at + 1 < len(members) else None
            parts += [(p, rows, len(rows) == len(members)) for p, rows, members, _n in runs]
            if len(parts) < 2:
                return None
            return self._join(cmd, parts, False, "group")

    def _join(self, cmd, parts, ahead, how):
        """The one piece rule's body (`join`, `group`), inside their command: `parts` [(piece, rows, whole)] — a whole
        piece, or rows taken out of it (`group`'s selection; a first part taken out becomes a piece of its own)."""
        if not parts[0][1]:
            raise ValueError("the piece to join onto is gone")
        works = list(dict.fromkeys(r[4] for _p, rows, _w in parts for r in rows))
        if len(works) > 1 and how == "parts":
            raise ValueError("these are different titles — make them one title first")
        others = [(p, rows, w) for p, rows, w in parts[1:] if rows]
        moving = [r for _p, rows, _w in others for r in rows]
        if not moving:
            return None
        first = parts[0][1]
        last = first[0] if ahead else first[-1]
        tier = last[1]
        # W3.2 H (Bo1): never into Finished by a join — that would skip finishing (no watched / graduated_at, no
        # `finished` event); the window joins onto Current rows only, so this guards a stale row's race
        if tier == "graduated" and any(r[1] != "graduated" for r in moving):
            raise ValueError("a part can't join a finished one: finish it first")
        if how == "group" and tier in NO_GROUP_TIERS:           # LM11: a group never lives there
            raise ValueError(GROUP_REFUSED)
        merged = None
        if len(works) > 1 and how == "titles":   # --- P-LF-4: one title first, then one piece (one undo)
            keep = first[0][4]
            if keep is None or None in works:
                raise ValueError("a part without a title can't be joined")
            apart = self._titles_apart(works)                   # LM11 (G1): the ids say two shows
            if apart:
                raise ValueError(apart)
            merged = self._change(cmd, "merge_works")
            self._merge_into(cmd, merged, keep, [w for w in works if w != keep])
            self._drop_apart(keep, works)
        change = self._change(cmd, "join")
        target, created, carved = parts[0][0], [], []
        if not parts[0][2]:                                     # LM11: the first is rows taken out of their piece
            target = self._new_piece(like=parts[0][0])
            created.append(target)
            carved = [(r[0], parts[0][0], r[3]) for r in first]
            self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?",
                                  [(target, cmd.version, r[0]) for r in first])
            for r in first:
                cmd.hints[r[0]] = target
            cmd.reworked.update(r[0] for r in first)            # the piece they left is cut where they stood
            cmd.feed(r[0] for r in first)
        change.piece_id = target
        nxt = self._beyond(tier, (last[0], last[2]), set(), -1 if ahead else 1, len(moving))
        if ahead:
            nxt = nxt[::-1]
        if [r[0] for r in nxt] != [r[0] for r in moving] or any(r[1] != tier for r in moving):
            rows = self._rows([r[0] for r in moving])
            self._before(change, list(rows.values()))
            self._put(tier, [r[0] for r in moving], ("before" if ahead else "after", last[0]), cmd.version)
            cmd.touch({r[1] for r in moving} | {tier}, within=all(r[1] == tier for r in moving))
        # --- W3.2 (IK-L2-1): a part from Finished comes back with its cards; one from New arrivals is placed
        # (W-1: through the one "leaving Finished" place, `_back_in_order`: its cards owed to Anki, its stones cleared)
        self._back_in_order(cmd, change, [r[0] for r in moving if r[1] == "graduated" and tier != "graduated"])
        for r in moving:
            if r[1] == "arrivals" and tier != "arrivals":
                cmd.event(r[0], "placed", 1)
        # --- end W3.2
        self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?",
                              [(target, cmd.version, r[0]) for r in moving])
        for r in moving:
            cmd.hints[r[0]] = target
        cmd.feed(r[0] for r in moving)
        whole = [p for p, _rows, w in others if w]
        gone = [self.conn.execute("SELECT id, title, kind, created_at FROM pieces WHERE id = ?", (p,)).fetchone()
                for p in whole]
        self.conn.executemany("DELETE FROM pieces WHERE id = ?", [(p,) for p in whole])
        change.pieces = {"items": carved + [(r[0], p, r[3]) for p, rows, _w in others for r in rows],
                         "created": created, "deleted": [tuple(g) for g in gone if g]}
        if merged is not None:
            change.works = merged.works          # P-LF-4: `undo` puts the titles back too (`_undo_works`)
        if how == "group":                       # LM11: kind and name, put back by the undo's value check
            had = self.conn.execute("SELECT kind, title FROM pieces WHERE id = ?", (target,)).fetchone()
            if had is None or had[0] != "group" or had[1] is None:
                # IK-12: a target with no name of its own takes the one named group joined whole onto it (a named
                # group dragged onto a show keeps its name); two names, or none: the derived name
                named = {g[1] for g in gone if g and g[2] == "group" and g[1] is not None}
                self._set_piece(cmd, target, "title", named.pop() if len(named) == 1 else None)
            self._set_piece(cmd, target, "kind", "group")
        # LM11 G2: the group made and every group a row was taken from, settled here (the settling step never meets a
        # piece this body re-pieced): none is left holding one work's items
        self._settle_kinds(cmd, {target} | {p for p, _rows, _w in parts})
        cmd.touch()
        return change

    def ungroup(self, piece_id):
        """LM11 *Ungroup* (any time, after a restart too): each run of one work's items in the group becomes a run piece
        of its own, in order, nothing moved and nothing lost; the group's row goes. One command, one undo (the group
        back, its id, name and members). -> the change, or None (not a group)."""
        with self._command("ungroup") as cmd:
            row = self.conn.execute("SELECT id, title, kind, created_at FROM pieces WHERE id = ?",
                                    (piece_id,)).fetchone()
            if row is None or row[2] != "group":
                return None
            members = self.conn.execute("SELECT i.id, i.work_id, i.changed_in, w.title FROM items i LEFT JOIN works w "
                                        "ON w.id = i.work_id WHERE i.piece_id = ? ORDER BY i.tier, i.ord, i.id",
                                        (piece_id,)).fetchall()
            change = self._change(cmd, "ungroup")
            created, sets = [], []
            for n, m in enumerate(members):
                if n == 0 or m[1] != members[n - 1][1]:         # a run of one work's items: a piece of its own
                    created.append(self._new_piece(title=m[3]))
                sets.append((created[-1], cmd.version, m[0]))
            self.conn.executemany("UPDATE items SET piece_id = ?, changed_in = ? WHERE id = ?", sets)
            cmd.feed(m[0] for m in members)
            self.conn.execute("DELETE FROM pieces WHERE id = ?", (piece_id,))
            change.pieces = {"items": [(m[0], piece_id, m[2]) for m in members], "created": created,
                             "deleted": [tuple(row)]}
            cmd.touch()
            return change

    def rename_piece(self, piece_id, title):
        """LM11 (G3): a group's own name; None or blank = back to the derived "<first show> + N more" (title NULL). A
        run has none (its title's name is renamed: `rename_work`). One command; undo by the value check. -> the change,
        or None (no such piece, or the name it has)."""
        title = (title or "").strip() or None
        with self._command("rename_piece") as cmd:
            row = self.conn.execute("SELECT kind, title FROM pieces WHERE id = ?", (piece_id,)).fetchone()
            if row is None:
                return None
            if row[0] != "group":
                raise ValueError("only a group has a name of its own: rename the title instead")
            if row[1] == title:
                return None
            change = self._change(cmd, "rename_piece")
            self._set_piece(cmd, piece_id, "title", title)
            return change

    def _undo_piece_fields(self, cmd, change):
        """LM11: a command's piece rows deleted come back (gone again if nothing returns to them) and each piece's kind
        and name go back where they still hold what it wrote (the value check, §6.11). -> (out, skipped pieces)."""
        out, skipped = self._change(cmd, "undo"), []
        for row in getattr(change, "dropped", ()):
            if self.conn.execute("INSERT OR IGNORE INTO pieces (id, title, kind, created_at) VALUES (?, ?, ?, ?)",
                                 row).rowcount:
                cmd.pieces_left.add(row[0])
                cmd.touch()
        for piece, column, old, new in reversed(getattr(change, "piece_fields", ())):
            now = self.conn.execute(f"SELECT {column} FROM pieces WHERE id = ?", (piece,)).fetchone()
            if now is not None and now[0] == new:
                self._set_piece(cmd, piece, column, old)
            elif column == "title":
                skipped.append(piece)
        return out, skipped

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
        if change.status:                                       # W3.2: the cards a Finished part brought back
            _o, cards = self._undo_status(cmd, change)
            more = list(more) + [i for i in cards if i not in more and i not in skipped]
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
            cmd.touch(pins=pins, order=column == "watched" and self._moves_counted([i for i, _ in changes]))
            return change

    def _moves_counted(self, ids):
        """W-1: does a watched mark (set or taken back) on `ids` move what counts? Only while `keep_watched` is off,
        and only for an item whose tier the rule reads it in (an analysed one) and that `schedule()` lists: a mark in
        Finished or New arrivals, on a video waiting for its subtitle, or with the option on, is a status write."""
        keep = self._keep_watched()
        tiers = {r[0] for chunk in _chunks(list(ids), 500) for r in self.conn.execute(
            f"SELECT DISTINCT tier FROM items WHERE id IN ({','.join('?' * len(chunk))}) AND availability != 'waiting'",
            chunk)}
        return any(counts(t, 0, keep) != counts(t, 1, keep) for t in tiers)

    def _watched_aside(self):
        """W-1: is a watched item in an analysed tier, one `schedule()` would list (no video waiting for its subtitle)
        — would `keep_watched` flipping move what counts?"""
        return self.conn.execute(f"SELECT EXISTS (SELECT 1 FROM items WHERE {counts_sql(True)} AND NOT "
                                 f"{counts_sql(False)} AND availability != 'waiting')").fetchone()[0] == 1

    def watched_marks(self):
        """The journey's stones (Sonic 2026-10-23): [(rel_path, tier, watched, counts, show, media)] for every item of
        the analysed tiers that Generate's list reads or sets aside (`schedule`'s rows: no video waiting for its
        subtitle), in its order — once one of them is watched; [] while none is (the report then is what it was), asked
        through the partial index `items_watched` (`STONES_EXIST_SQL`: a library with no stone pays one look, S19).
        `counts` is the one rule's (`counts`): a watched item counts only with `keep_watched` on. `show`: which show or
        book it is of, as the window's rows read it (`view_rows._show_key`: its work, else its folder, else itself) —
        `w<id>` / `f<folder>` / `i<id>`; `media`: its work's type as the learner typed it, else None (a6: the journey
        folds a run of watched parts of one show into one row, `static_html_generator._journey_folds`). Finished stays
        out (its own view). One read transaction."""
        with self._reading():
            if not self.conn.execute(STONES_EXIST_SQL).fetchone()[0]:
                return []
            keep = self._keep_watched()
            return [(rel, tier, 1 if watched else 0, counts(tier, watched, keep),
                     f"w{work}" if work is not None else f"f{folder}" if folder else f"i{item}", media)
                    for tier in ANALYSED
                    for item, rel, watched, work, folder, media in self.conn.execute(
                        "SELECT i.id, i.rel_path, i.watched, i.work_id, i.parent_folder, w.media_type FROM items i "
                        "LEFT JOIN works w ON w.id = i.work_id WHERE i.tier = ? AND i.availability != 'waiting' "
                        "ORDER BY i.ord, i.id", (tier,))]

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

    def set_library_options(self, mine_line=None, arrivals_on=None, keep_watched=None):
        """The user's library options (Mado's gap 3): how many of Current's top rows Connect mines, whether drops wait
        in New arrivals (D30), and (W-1) whether watched episodes keep counting (`keep_watched`, absent = off): flipping
        it bumps `order_version` only when a watched item sits in an analysed tier. Undo by the value check."""
        wanted = {}
        if mine_line is not None:
            if int(mine_line) < 0:
                raise ValueError("the mine line can't be negative")
            wanted["mine_line"] = int(mine_line)
        if arrivals_on is not None:
            wanted["arrivals_on"] = 1 if arrivals_on else 0
        if keep_watched is not None:
            wanted["keep_watched"] = 1 if keep_watched else 0
        if not wanted:
            return None
        with self._command("set_library_options") as cmd:
            meta = self._meta()
            options = [(k, meta.get(k), v) for k, v in wanted.items()
                       if meta.get(k, 0 if k == "keep_watched" else None) != v]      # W-1: absent is off
            if not options:
                return None
            self._set_meta({k: v for k, _o, v in options})
            if "mine_line" in wanted:
                cmd.mine_n = wanted["mine_line"]               # the log's crossings read the new line
            cmd.touch(order=any(k == "keep_watched" for k, _o, _v in options) and self._watched_aside())
            change = self._change(cmd, "set_library_options")
            change.options = options
            return change

    def _undo_roots(self, cmd, change):
        """T6, *Stop reading*'s Undo by the value check (§6.11): each folder read again only where its row still holds
        what the stop wrote (turned back on meanwhile: left as it is, a note)."""
        out = self._change(cmd, "undo")
        back, skipped = [], []
        for root_id, old, new in change.roots:
            if self.conn.execute("UPDATE roots SET kind = ? WHERE id = ? AND kind = ?", (old, root_id, new)).rowcount:
                back.append((root_id, new, old))
            else:
                skipped.append(root_id)
        if back:
            self._copy_dirty()
            out.roots = back
        return out, skipped

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
            cmd.touch(order="keep_watched" in back and self._watched_aside())     # W-1
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
                row = self.conn.execute(f"SELECT pairing FROM pairings p WHERE item_id = ? AND NOT {_VERSION_ROW} "
                                        f"ORDER BY {_ORIGIN_ROW}, paired_at DESC LIMIT 1",
                                        (ids[0],)).fetchone()     # B1: hato's first; LM1b: never a version
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
        Its title's other items, by the episode numbers their records name (the same season: an item whose record
        names another season is another show's, as `connect/rules.py` read it before Decision 1); without numbers,
        after the title's last item in Current. LM11 (G4): never inside a group — after it (before it, when the
        anchor is the row it goes before), in a piece of its own (`_past_group`)."""
        spot = self._show_spot(item_id, record, excl)
        if spot is None:
            return None
        tier, before_id, after_id = spot
        if after_id is not None:
            return (tier, None, self._past_group(after_id))
        if before_id is not None:
            return (tier, self._past_group(before_id, -1), None)
        return spot

    def _show_spot(self, item_id, record, excl):
        """`_after_show`'s reading of the title's rows."""
        work = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()
        if work is None or work[0] is None:
            return None
        mine = _episode(record)
        others = [r for r in self.conn.execute("SELECT id, tier, ord FROM items WHERE work_id = ? AND id != ?",
                                               (work[0], item_id)) if r[0] not in excl]
        if not any(r[1] in CURRENT or r[1] in ("graduated", "goal") for r in others):
            return None              # it stays whatever their records say (a show still waiting): none read
        episodes, apart = {}, set()
        for other, text in self.conn.execute(f"SELECT item_id, pairing FROM pairings p WHERE item_id IN "
                                             f"(SELECT id FROM items WHERE work_id = ?) AND {_PREFERRED_ROW}",
                                             (work[0],)):
            try:
                ep = _episode(json.loads(text))
            except ValueError:
                continue
            if ep is not None and (mine is None or ep[0] == mine[0]):
                episodes[other] = ep[1]
            elif ep is not None:
                apart.add(other)
        others = [r for r in others if r[0] not in apart]
        if not others:
            return None
        current = [r for r in others if r[1] in CURRENT]
        if not current:
            if all(r[1] in ("graduated", "goal") for r in others):
                return ("now", None, None)                      # Q4-9: a finished title's new episode leads Current
            return None
        if isinstance(record, dict) and record.get("producer") == SOURCE_PRODUCER:
            # a folder's file goes in its show's run in order (S3: K4's number or its natural-order name)
            rels = dict(self.conn.execute(f"SELECT id, rel_path FROM items WHERE id IN "
                                          f"({','.join('?' * (len(current) + 1))})", [r[0] for r in current] +
                                          [item_id]).fetchall())
            ep = record.get("episode") if isinstance(record.get("episode"), (int, float)) else None
            tier, (how, anchor) = self._in_run([r + (rels[r[0]],) for r in current], rels[item_id], ep)
            return (tier, anchor, None) if how == "before" else (tier, None, anchor)
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
            status = [] if keep_cards else self._cards_out(cmd, ids)
            if change is None and not status:
                return None
            if change is None:
                change = self._change(cmd, "finish")
            change.kind = "finish"
            change.status = list(change.status) + status       # (W3.2: an arrival's watched, from `set_tier`)
            return change

    def _cards_out(self, cmd, ids):
        """*Take its new cards out* (D14), inside the caller's command: the items' cards out of the learning order and
        their pin ended (G2.2-8: the later click wins) -> the status values written, for undo."""
        status = []
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
            # --- P4.1 L2: the learning order moved too: owed to Anki through `pins_version` (T-4) ---
            cmd.touch(pins=True)
            # --- end P4.1 L2 ---
        return status

    def set_learning_order(self, item_ids, on=True):
        """A Finished item's *Put them back in the order* (on) ↔ *Take its new cards out* (off), D14: `in_learning_order`
        1 / 0. Off also ends the pin, as `finish(keep_cards=False)` does; on never pins again. Writes no card (Anki's
        side is the re-plan's). Undo by the value check. Returns the change, or None (nothing new)."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return None
        if on:
            return self._status("set_learning_order", ids, "in_learning_order", 1, pins=True)   # P4.1 L2 (T-4)
        with self._command("set_learning_order") as cmd:
            status = self._cards_out(cmd, ids)
            if not status:
                return None
            change = self._change(cmd, "set_learning_order")
            change.status = status
            return change

    def put_back_finished(self, item_ids):
        """*Put back* (Finished's hover and ⋯, G1.6-10: anything taken out comes back): to the top of Current and its
        cards back in the learning order (`in_learning_order` 1), one command, one undo. A pin Finish ended stays ended
        (the user pins again). Returns the change, or None (nothing new)."""
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return None
        with self._command("put_back_finished") as cmd:
            change = self.move(ids, "now")
            marks = ",".join("?" * len(ids))
            status = [(i, "in_learning_order", old, 1) for i, old in self.conn.execute(
                f"SELECT id, in_learning_order FROM items WHERE id IN ({marks})", ids).fetchall() if old != 1]
            self.conn.executemany("UPDATE items SET in_learning_order = 1 WHERE id = ?", [(i,) for i, *_r in status])
            cmd.feed(i for i, *_r in status)
            if status:
                cmd.touch(pins=True)        # P4.1 L2 (T-4): its cards back in the order are owed to Anki
            if change is None and not status:
                return None
            if change is None:
                change = self._change(cmd, "put_back_finished")
            change.kind = "put_back_finished"
            change.status = list(change.status) + status     # P4.1 L2 (TF fix 8): the move's own, when it set it
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

    def enter_mine_line(self, by="user"):
        """*Make cards for your first 20 episodes?* (SRC S1 + D1): the mine line's items, there since setup's first scan
        put them there quietly (it logs nothing), logged as entering it by `by`'s own choice — `entered_mine_line`,
        explicit: the event Connect's inbox makes a job of. Nothing moves; only the log is written (and the state
        version). With no reader set nothing is logged (the caller sets Connect's first: `connect.library.
        ensure_reader`). Not on the Undo (a job is Connect's to drop). -> the ids logged."""
        with self._command("enter_mine_line", by=by) as cmd:
            if not cmd.logging:
                return []
            ids = self._mine_ids(cmd.mine_n)
            for item_id in ids:
                cmd.event(item_id, "entered_mine_line", 1)
            if ids:
                cmd.touch()
            return ids

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
        check. Returns the change, or None (refused, or nothing new). An unlocked online cover (AniList, TMDB,
        YouTube: a background fetch) is written only over none, the generated one, or its own source's cache record —
        never over the art beside the files nor another source's, checked here, at write time (W3.2 L3 B2)."""
        if source not in COVER_SOURCES:
            raise ValueError(f"unknown cover source {source!r}")
        if path is not None and not str(path).startswith(("cache:", "user:")):
            raise ValueError("a cover's path is 'cache:<name>' or 'user:<name>'")
        with self._command("set_cover") as cmd:
            row = self.conn.execute("SELECT cover_locked, cover_source, cover_path FROM works WHERE id = ?",
                                    (work_id,)).fetchone()
            if row is None or (row[0] and not locked):
                return None
            if (not locked and source in ("anilist", "tmdb", "youtube") and row[1] not in (None, "generated")
                    and not (row[1] == source and (row[2] is None or str(row[2]).startswith("cache:")))):
                return None                             # a fetch never over disk art or another source (B2)
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

    # --- P4.1 L2: *Take its new cards out*, Anki's half (05 §5.7, D14): what the re-plan reads ---
    def cards_out(self):
        """The re-plan's input for *Take its new cards out* (05 §5.7), in one read transaction -> `{"out": [(item_id,
        rel_path)] — the items whose cards are out of the learning order (`in_learning_order` 0, not pinned since: a
        pin is the later click, G2.2-8), any tier; "back": the open `cards_out` records (`anki_changes_of`'s rows) of
        items back in the order since (*Put back*, *Put them back in the order*, an undo, a pin) — what the next run
        restores}`. A removed item's records wait in the table: its cards stay as they are until it is put back."""
        with self._reading():
            out = self.conn.execute("SELECT id, rel_path FROM items WHERE in_learning_order = 0 AND pinned IS NULL "
                                    "ORDER BY id").fetchall()
            back = [r[0] for r in self.conn.execute(
                "SELECT DISTINCT c.item_id FROM anki_changes c JOIN items i ON i.id = c.item_id WHERE c.reverted_at "
                "IS NULL AND c.action = 'cards_out' AND (i.in_learning_order != 0 OR i.pinned IS NOT NULL) "
                "ORDER BY c.item_id")]
            rows = [r for r in self.anki_changes_of(back) if r["action"] == "cards_out"] if back else []
        return {"out": [tuple(r) for r in out], "back": rows}
    # --- end P4.1 L2 ---

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
                        try:            # entry by entry: an odd entry `notes_gone` kept hides no note (IK-6)
                            out[item_id].update(n for n in map(_note_id, json.loads(notes)) if n is not None)
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
        never made again automatically, even when its notes were deleted (G1.3-4). A row `notes_gone` emptied (no note
        of it left in Anki) takes the notes of a card made again on request (IK-6, §12.10): the word is recorded again
        on that row. An item removed meanwhile is recorded too (Put back finds it). A status write: `state_version`
        only. Returns the words recorded."""
        rows = [(item_id, str(w), _dumps([int(n) for n in notes]), _now(), batch) for w, notes in made if w]
        if not rows:
            return []
        with self._command("record_made", "connect") as cmd:
            for sql in ADDED_TABLES_SQL:
                self.conn.execute(sql)
            have = {w: _json_list(raw) for w, raw in self.conn.execute("SELECT word, note_ids FROM made_words "
                                                                       "WHERE item_id = ?", (item_id,))}
            fresh = [r for r in rows if r[1] not in have]
            # emptied: no entry of the row is a note id any more (an odd entry is kept as it is, as `notes_gone` does)
            again = [r for r in rows if r[1] in have and json.loads(r[2])
                     and all(_note_id(n) is None for n in have[r[1]])]
            if not fresh and not again:
                return []
            if fresh:
                self.conn.executemany("INSERT INTO made_words (item_id, word, note_ids, made_at, batch) "
                                      "VALUES (?, ?, ?, ?, ?)", fresh)
            if again:
                self.conn.executemany("UPDATE made_words SET note_ids = ?, made_at = ?, batch = ? "
                                      "WHERE item_id = ? AND word = ?",
                                      [(_dumps(have[r[1]] + json.loads(r[2])), r[3], r[4], r[0], r[1])
                                       for r in again])
            cmd.touch()
            recorded = {r[1] for r in fresh + again}
            return [r[1] for r in rows if r[1] in recorded]

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

    def record_anki_changes(self, changes, by="connect"):     # P4.1 L2 (TF fix 10): `by`, the caller
        """The re-plan's record of the cards it changed for an item (05 §5.7, D14): [(item_id, action, [note ids],
        before, after)], one short write; *Put back* restores exactly these, never more. Returns the record ids.
        `by`: who recorded it — Connect's step ("connect"), the window's re-order host ("replan")."""
        rows = [(item_id, action, _dumps([int(n) for n in notes]), _dumps(before), _dumps(after), _now())
                for item_id, action, notes, before, after in changes]
        if not rows:
            return []
        with self._command("record_anki_changes", by) as cmd:
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

    def mark_anki_reverted(self, change_ids, by="connect"):     # P4.1 L2 (TF fix 10): `by`, as above
        """The re-plan put those cards back (Put back): their records are closed, kept. Returns how many."""
        ids = list(dict.fromkeys(change_ids))
        if not ids:
            return 0
        with self._command("mark_anki_reverted", by) as cmd:
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
            if row[2] == st.st_size and _same_time(row[3], st.st_mtime_ns):   # D7a: its file, by rule 2b's proof
                _note_moves(self, [(row[0], row[2], row[3], rel, st.st_size, st.st_mtime_ns)])
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

    def relink_many(self, pairs, left_out=None):
        """K3 / K1 (alpha 4): *Choose a folder…* on a folder's or the library's card — many missing items each pointed at
        its file (`pairs`: [(item_id, path)]), as `relink` does one, in ONE command: one change, one Undo (3,000 gone
        files never make 3,000). A pair that can't be (not in the library, no file there, its place another item's, the
        item gone or already there) is left out and named in `change.left` [(item_id, why)]. Returns the change, or None
        when none was relinked — never an empty change (it would be an Undo for nothing); then `left_out`, a list, gets
        the pairs left out and why (alpha 5, Mado: with none relinked, the why was lost)."""
        looked = []                                  # every file stat'ed before the write lock (A6: never under it)
        for item_id, path in pairs:
            rel = library_rel(self.data_dir, path)
            hidden = rel is not None and any(p.startswith(".") for p in rel.split("/"))   # the trash, a dot folder
            looked.append((item_id, rel, None if rel is None or hidden else _stat(os.path.join(self.data_dir, rel)),
                           hidden))
        with self._command("relink") as cmd:
            change = None
            done, left = [], []
            taken = set()
            for item_id, rel, st, hidden in looked:
                if rel is None or hidden:
                    left.append((item_id, "not in the library" if rel is None else "in the trash"))
                    continue
                if st is None:
                    left.append((item_id, "no file there"))
                    continue
                row = self.conn.execute("SELECT rel_path, rel_key, size, mtime_ns, availability, tier FROM items "
                                        "WHERE id = ?", (item_id,)).fetchone()
                if row is None or row[1] == path_key(rel):
                    left.append((item_id, "gone from the library" if row is None else "there already"))
                    continue
                if path_key(rel) in taken or self.conn.execute("SELECT id FROM items WHERE rel_key = ?",
                                                               (path_key(rel),)).fetchone() is not None:
                    left.append((item_id, "another item's file"))
                    continue
                if change is None:
                    change = self._change(cmd, "relink")
                taken.add(path_key(rel))
                done.append({"id": item_id, "old": list(row[:5]), "new": rel})
                self._repoint(item_id, rel, st.st_size, st.st_mtime_ns)
                if row[2] == st.st_size and _same_time(row[3], st.st_mtime_ns):
                    _note_moves(self, [(row[0], row[2], row[3], rel, st.st_size, st.st_mtime_ns)])
                cmd.touch({row[5]}, availability=row[4] != "available")
            if change is None:
                if left_out is not None:
                    left_out.extend(left)
                return None
            asks = _rename_asks(self)                  # their open questions go, in one write (never one per file)
            kept = [a for a in asks if path_key(a.get("rel", "")) not in taken]
            if kept != asks:
                self._set_meta({"rename_asks": _dumps(kept), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})
            change.relink, change.relinks, change.left = done[0], done, left
            return change

    def _undo_relink(self, cmd, change):
        """Undo a relink (one item, or `relink_many`'s list): each item pointed back where it was, by the value check —
        one relinked again since, or whose old place is another item's now, is skipped. Newest first: a later pair may
        hold an earlier one's old place (A → Y, then B → A's old X), which its own undo frees."""
        out = self._change(cmd, "undo")
        skipped = []
        for info in reversed(getattr(change, "relinks", None) or [change.relink]):
            row = self.conn.execute("SELECT rel_path, tier FROM items WHERE id = ?", (info["id"],)).fetchone()
            if row is None or row[0] != info["new"]:
                skipped.append(info["id"])
                continue
            old_rel, _key, size, mtime_ns, _availability = info["old"]
            if self.conn.execute("SELECT 1 FROM items WHERE rel_key = ? AND id != ?",
                                 (path_key(old_rel), info["id"])).fetchone():
                skipped.append(info["id"])                     # its old path is another item's now (§12.8)
                continue
            self._repoint(info["id"], old_rel, size, mtime_ns)
            if not os.path.exists(os.path.join(self.data_dir, _strip(old_rel))):
                self.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (info["id"],))
            cmd.touch({row[1]}, availability=True)
        return out, skipped

    def its_new(self, path):
        """9a's other answer, *It's new*: its question goes and the file joins the library as any new file does
        (§6.10 rule 3) — the items it was asked about stay missing. Returns the sync's summary."""
        rel = library_rel(self.data_dir, path)
        if rel is None:
            raise NotInLibrary(f"not in the library: {path}")
        with self._writing():
            self._drop_ask(rel)
        return self.sync_disk(folders=[_rel_dir(rel)] if _rel_dir(rel) else None, as_new=[rel])

    def text_lists(self):
        """9b (05 §5.10): (counted, kept, aside) — the paths, relative to data/<lang>, whose text the token store
        keeps. Counted: the items that count (`counts`), a missing one too (it keeps counting until the user decides).
        Aside (`sets_aside`): reference — Finished (W-1b) and an analysed tier's watched items while `keep_watched` is
        off (W-1), a missing one too — never summed, still the name tables' evidence and a sentence source (the token
        store's set-aside class). Kept, text only: New arrivals, and removed items whose sentences weren't forgotten
        (`trash.text_forgotten` 0).
        The token store (E2.2) takes these lists in place of a run's one list: it keeps a kept or set-aside file's text
        (in `kept_text_<lang>.db`, through any wipe) and sums only counted files. One read transaction."""
        with self._reading():
            keep = self._keep_watched()
            counted, aside, kept = [], [], []
            for rel, tier, watched in self.conn.execute(
                    "SELECT rel_path, tier, watched FROM items ORDER BY tier, ord, id"):
                (counted if counts(tier, watched, keep) else aside if sets_aside(tier, watched, keep)
                 else kept).append(rel)
            kept += [r[0] for r in self.conn.execute(
                "SELECT rel_path FROM trash WHERE restored_at IS NULL AND text_forgotten = 0 ORDER BY id")]
        have = {path_key(r) for r in counted + aside}
        out, seen = [], set()
        for rel in kept:
            key = path_key(rel)
            if key not in have and key not in seen:
                seen.add(key)
                out.append(rel)
        return counted, out, aside

    def text_elsewhere(self):
        """{rel_path: trashed_path} for the removed items in `text_lists`' kept list: where each one's file went
        (relative to data/<lang>), so the token store (E2.2) reads a removed file's text from the trash — one it never
        indexed, or one whose text it hasn't kept yet — before the trash's 30 days end. One read transaction."""
        with self._reading():
            return {r[0]: r[1] for r in self.conn.execute(
                "SELECT rel_path, trashed_path FROM trash WHERE restored_at IS NULL AND text_forgotten = 0 "
                "AND trashed_path IS NOT NULL ORDER BY id")}

    def text_moved(self):
        """D7a: the moves this store proved — [(old rel, old size, old mtime_ns, new rel, size, mtime_ns)], oldest
        first (`moved_paths`, the last MOVED_PATHS_KEEP): the token store's hint, so a file the sync followed under
        another name (rule 2, 2b) or *Link a file* found keeps its tokenized row (`token_index.Store.reconcile`'s
        `moved`). One read transaction."""
        with self._reading():
            return [tuple(m) for m in _moved_paths(self)]

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
        """The store's Watched record (✅ G1.1-5). W-1: a watched item in an analysed tier stops counting while
        `keep_watched` is off, so there a mark (and its undo) bumps `order_version` (the journey's Generate and the
        re-plan follow); anywhere else it stays a status write."""
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

    def notes_gone(self, note_ids, by="connect"):
        """Notes Anki no longer has (P2.4 row 2.4.14; Sonic, 2026-10-07: a card the learner deletes, theirs or
        Connect's, loses its *in Anki* mark at the next sync and is never offered): taken out of everything that reads
        a note as in Anki — `anki_links`, the note ids in `made_words` and, where it exists (3.0), `made_lines` —
        while each made word keeps its row (G1.3-4: never made again unless you ask); and out of what a removed item
        keeps for its Put back or undo (its trash row's `anki_links`), so a restore never brings the mark back. A
        status write, `state_version` only (the copy carries these tables where it carries them). Notes the store
        doesn't hold change nothing and write nothing: no write lock is taken (S19). Returns the note ids taken out,
        sorted."""
        gone = sorted({int(n) for n in note_ids})
        if not gone:
            return []
        with self._reading():
            found, made, trashed = self._notes_held(gone)
        if not found:
            return []
        wanted = set(gone)
        with self._command("notes_gone", by) as cmd:
            # Inside the write only what the read found, by its keys (never the whole made-words table under the
            # lock: it only grows). Rows another writer changed meanwhile are read again here.
            changed = 0
            lines = self._has_table("made_lines")
            for chunk in _chunks(gone, 500):
                marks = ",".join("?" * len(chunk))
                changed += self.conn.execute(f"DELETE FROM anki_links WHERE note_id IN ({marks})", chunk).rowcount
                if lines:
                    changed += self.conn.execute(f"DELETE FROM made_lines WHERE note_id IN ({marks})", chunk).rowcount
            for item_id, word in made:
                row = self.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?",
                                        (item_id, word)).fetchone()
                ids = _json_list(row[0]) if row else []
                kept = [n for n in ids if _note_id(n) not in wanted]
                if len(kept) != len(ids):
                    self.conn.execute("UPDATE made_words SET note_ids = ? WHERE item_id = ? AND word = ?",
                                      (json.dumps(kept), item_id, word))
                    changed += 1
            for trash_id in trashed:
                row = self.conn.execute("SELECT item_state FROM trash WHERE id = ? AND restored_at IS NULL",
                                        (trash_id,)).fetchone()
                state = _json_dict(row[0]) if row else None
                links = state.get("anki_links") if state else None
                if not isinstance(links, list):
                    continue
                kept = [a for a in links if not (isinstance(a, list) and a and _note_id(a[0]) in wanted)]
                if len(kept) != len(links):
                    state["anki_links"] = kept
                    self.conn.execute("UPDATE trash SET item_state = ? WHERE id = ?", (_dumps(state), trash_id))
                    changed += 1
            if changed:
                cmd.touch()
        return sorted(found)

    def _has_table(self, name):
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                                 (name,)).fetchone() is not None

    def _notes_held(self, gone):
        """(the gone notes the store holds, [(item_id, word)] for each made word that names one, [trash ids] for each
        removed item whose kept links name one). A list entry that isn't a note id is kept as it is, never a reason
        to skip its row."""
        wanted, found, made, trashed = set(gone), set(), [], []
        lines = self._has_table("made_lines")
        for chunk in _chunks(gone, 500):
            marks = ",".join("?" * len(chunk))
            found.update(r[0] for r in self.conn.execute(f"SELECT DISTINCT note_id FROM anki_links WHERE note_id IN "
                                                         f"({marks})", chunk))
            if lines:
                found.update(r[0] for r in self.conn.execute(f"SELECT note_id FROM made_lines WHERE note_id IN "
                                                             f"({marks})", chunk))
        if self._has_table("made_words"):
            for item_id, word, raw in self.conn.execute("SELECT item_id, word, note_ids FROM made_words"):
                hit = wanted.intersection(_note_id(n) for n in _json_list(raw))
                if hit:
                    found.update(hit)
                    made.append((item_id, word))
        # a removed item's kept links (`_dumps` writes `"anki_links": [[` only when it kept one)
        for trash_id, raw in self.conn.execute("SELECT id, item_state FROM trash WHERE restored_at IS NULL "
                                               "AND item_state LIKE '%\"anki_links\": [[%'"):
            state = _json_dict(raw)
            links = state.get("anki_links") if state else None
            if not isinstance(links, list):
                continue
            hit = wanted.intersection(_note_id(a[0]) for a in links if isinstance(a, list) and a)
            if hit:
                found.update(hit)
                trashed.append(trash_id)
        return found, made, trashed

    # --- bookkeeping (§6.6): no version moves ---------------------------------------------------- #

    def record_analysed(self, order_version):
        """At the end of a successful Generate that read the store (never after a JSON fallback). Keeps
        the larger of the stored value and the one given. W-1: that Generate read this build's list, the old watched
        marks already out of it — so they are counted (`STONES_COUNTED`): the helper's count, coming after, moves no
        version (no second Generate with nothing changed)."""
        with self._writing():
            meta = self._meta()
            values = {} if STONES_COUNTED in meta else {STONES_COUNTED: 1}
            if order_version > meta.get("analysed_order_version", 0):
                values["analysed_order_version"] = order_version
            if values:
                self._set_meta(values)

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
        if kind == "take_in":                     # SRC S6: a scan's take-in is not on the user's Undo; Remove is
            raise UndoRefused("what a folder's look took in is taken out with Remove")
        if kind == "register" and getattr(change, "took_over", None) is not None:   # K3 R2 / R3: the text moved
            raise UndoRefused("hato's subtitle is that episode's text now; remove the episode to take it out")
        if kind in ("switch_group", "switch_version"):   # LM2, LM3: the copies' bytes back, read outside the lock
            return self._undo_switch(change)
        with self._command("undo", "undo") as cmd:
            if kind in ("insert", "insert_at", "restore") or (kind == "register" and change.added):
                ok, skipped = self.undo_check(change)
                if trashed_paths and any(i in skipped for i in trashed_paths):
                    raise StoreConflict("an item changed since its file was moved; nothing was undone")
                if not ok:
                    return self._skipped(cmd, len(skipped))
                explicit = 0 if kind == "register" else 1
                out = self._remove_as(ok, trashed_paths, explicit, exclude=kind not in ("insert", "insert_at"),
                                      why="remove" if kind == "restore" else None)   # K2: a Put back undone: removed
                if kind == "register" and getattr(change, "pairing_before", (None, None))[1] is not None:
                    content_key, old = change.pairing_before          # the key's pairing before hato moved it
                    if self.conn.execute("SELECT 1 FROM items WHERE id = ?", (old[0],)).fetchone():
                        self.conn.execute("INSERT OR IGNORE INTO pairings (content_key, item_id, pairing, paired_at) "
                                          "VALUES (?, ?, ?, ?)", (content_key,) + tuple(old))
            elif kind == "register":
                if getattr(change, "pairing_before", None) is None:     # K3: a duplicate's hand-off that wrote none
                    return self._skipped(cmd, 1)
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
                if getattr(change, "excluded_key", None):              # N1: hato's file is no one's: the sync's again
                    self.conn.execute("DELETE FROM exclusions WHERE kind = 'duplicate' AND pattern = ?",
                                      (change.excluded_key,))
                cmd.touch()
                out, skipped = self._change(cmd, "undo"), []
            elif kind == "remove" or kind == "undo_add":
                folder = getattr(change, "folder", None)        # K6: a skip's Undo reads its folder again too
                if folder is not None:
                    if not self._unskip(folder):                # read again meanwhile: its files may be back
                        return self._skipped(cmd, max(1, len(change.trash_ids)))
                rows = self.trash_rows(change.trash_ids)
                waiting = [r["id"] for r in rows if not r["restored_at"]]
                if not waiting:
                    if folder is not None:
                        out = self._change(cmd, "undo")
                        out.folder_dropped = True
                        return out
                    return self._skipped(cmd, len(change.trash_ids))
                explicit = {it["id"]: it.get("explicit", 1) for it in change.items}
                out = self.restore(waiting, rel_paths, by="undo", kind="undo",
                                   explicit_of=lambda i: explicit.get(i, 1))
                out.folder_dropped = folder is not None
                skipped = [t for t in change.trash_ids if t not in waiting]
            elif kind == "relink":
                out, skipped = self._undo_relink(cmd, change)
            elif kind in ("finish", "put_back_finished"):
                out, skipped = self._undo_finish(cmd, change)
            elif kind == "import_finished":
                out, skipped = self._undo_import(cmd, change, trashed_paths)
            elif getattr(change, "options", None):
                out, skipped = self._undo_options(cmd, change)
            elif kind == "stop_source":
                out, skipped = self._undo_roots(cmd, change)
            elif kind == "set_tier" and change.status:              # W3.2: an arrival finished, its watched
                out, skipped = self._undo_finish(cmd, change)
            elif kind == "move" and change.status:      # P4.1 L2 (TF fix 8): out of Finished, back in the order
                out, skipped = self._undo_finish(cmd, change)
            elif kind == "audiobook_pick":                           # a5-2: *Find its book…*'s pick (Hon)
                out, skipped = self._undo_audiobook_pick(cmd, change)
            elif kind == "rename_piece":                             # LM11: a group's name (value check)
                out, skipped = self._undo_piece_fields(cmd, change)
            elif kind == "join" and change.pieces is not None:       # (before the status: W3.2's join has one)
                out, skipped = self._undo_join(cmd, change)
                if change.works is not None:        # P-LF-4: a title dropped on another: two titles again
                    for item_id, piece in self.conn.execute(   # the dragged title's other parts keep their pieces
                            "SELECT id, piece_id FROM items WHERE id IN (SELECT value FROM json_each(?))",
                            (_dumps([t[0] for t in change.works["items"]]),)):
                        if item_id not in cmd.hints and piece is not None:
                            cmd.hints[item_id] = piece      # (else settling folds one beside its own into it)
                    _o, more = self._undo_works(cmd, change)
                    skipped = list(skipped) + [i for i in more if i not in skipped]
            elif change.status:
                out, skipped = self._undo_status(cmd, change)
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
        (the value check, §6.11): a foreign drop's split is mended when the drop is undone. LM11: so do the group rows
        it emptied and every piece's kind and name it wrote (`_undo_piece_fields`), before the undo's settling step."""
        if change.kind != "rename_piece":
            self._undo_piece_fields(cmd, change)
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

    def _remove_as(self, ids, trashed_paths, explicit, exclude=True, why=None):
        """Undo-Add: the rows go to the trash table, as `remove` does (pairings and links included, so
        Put back works); the files went to `.trash` by the caller's file code. `exclude`, `why`: `remove`'s."""
        cmd = self._cmd
        events_before = len(cmd.events)
        out = self.remove(ids, trashed_paths, by="undo", kind="undo_add", exclude=exclude, why=why)
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
            cmd.touch(pins=any(c in ("pinned", "in_learning_order") for c, _o, _i in back),   # P4.1 L2 (T-4)
                      order=self._moves_counted([i for c, _o, i in back if c == "watched"]))   # W-1
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
        cmd.touch(tiers, within=all(it["tier"] == cur[it["id"]][1] for it in ok))
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
        waiting = []                                   # K5: an analysed tier's video-only rows, never in the schedule
        for r in rows:
            entry = json.loads(r["entry"])
            if r["availability"] == "waiting" and r["tier"] in ANALYSED:
                waiting.append(entry)
            else:
                by_tier[r["tier"]].append(entry)
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
        if waiting:
            doc["surasura_library"]["waiting"] = waiting
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
            for sql in SCHEMA_SQL + SCHEMA_2_SQL + ADDED_HASH_SQL:      # A4K-7: a new store has the hashes at once
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
    if kind == "audio":                                  # an audiobook alone (Hon, H-7): `view_rows`' rule too
        return "audiobook"
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
      its folder below the tier folder (`folder_title`, the path among its other titles); a loose file is a work of its
      own, titled by its title. A pairing's record
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
            below = _below_tier(rel) if fk is not None else None
            works[wid] = {"title": folder_title(below) if below else (title or rel.rsplit("/", 1)[-1]),
                          "titles": [below] if below and folder_title(below) != below else [], "fk": fk, "anilist_id": None, "tmdb_id": None, "youtube_channel": None,
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
    # pieces: one run of one work in one tier each — LM11: a group's run goes on across works (never in Finished or
    # New arrivals); a group left holding one work's items, or one there, is a run
    pieces = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, title, kind FROM pieces")}
    next_piece = _next_id(conn, "pieces")                      # LM11 G3: never an id issued before
    new_pieces = []
    updates = []
    used = set()
    ordered = conn.execute("SELECT id, tier, piece_id, title FROM items ORDER BY tier, ord, id").fetchall()
    prev_tier = prev_work = prev_old = prev_new = None
    for item_id, tier, piece, title in ordered:
        wid = item_work[item_id]
        crossed = tier != prev_tier
        if crossed:
            if not (prev_tier in CURRENT and tier in CURRENT):   # LM11 G1: a group runs on across the Soon line
                prev_work = prev_old = prev_new = None
            prev_tier = tier
        if piece is not None and piece not in pieces:
            piece = None
        if piece is not None and piece == prev_old and (wid == prev_work and not crossed or
                                                        pieces[piece][1] == "group" and tier not in NO_GROUP_TIERS):
            new = prev_new                                      # the run goes on
        elif piece is not None and piece not in used:
            new = piece                                         # a piece's first run keeps its id
            used.add(piece)
        elif piece is None and prev_new is not None and wid == prev_work and not crossed:
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
        _set_seq(conn, "pieces", next_piece - 1)
    conn.executemany("UPDATE items SET work_id = ?, piece_id = ?, search_key = ?, feed_in = ? WHERE id = ?", updates)
    conn.execute("DELETE FROM pieces WHERE id NOT IN (SELECT piece_id FROM items WHERE piece_id IS NOT NULL)")
    conn.execute(f"UPDATE pieces SET kind = 'run' WHERE kind = 'group' AND id IN (SELECT piece_id FROM items GROUP BY "
                 f"piece_id HAVING COUNT(DISTINCT work_id) <= 1 OR MAX(tier IN "
                 f"({','.join('?' * len(NO_GROUP_TIERS))})))", NO_GROUP_TIERS)
    store._set_meta({"feed_floor": version, "search_fold": SEARCH_FOLD_VERSION})


def _pieces_ok(conn):
    """None when every piece is one contiguous run, in (ord, id), of one work's items in one tier and every item has a
    piece and a work (L2.2 05 §5.2 rule 1); else what's wrong. LM11: a group (kind 'group') may hold several works'
    items — still one run in one tier (NOW and Soon one tier for it: G1), never in Finished or New arrivals, and never
    one work's alone (a run's)."""
    groups = {r[0] for r in conn.execute("SELECT id FROM pieces WHERE kind = 'group'")}
    seen, works = set(), {}
    prev = None
    for item_id, tier, piece, work in conn.execute("SELECT id, tier, piece_id, work_id FROM items "
                                                   "ORDER BY tier, ord, id"):
        if piece is None:
            return f"item {item_id} has no piece"
        if piece in groups and tier in NO_GROUP_TIERS:
            return f"group {piece} is in Finished or New arrivals"
        if prev is not None and prev[1] == piece and (prev[0] == tier or piece in groups and prev[0] in CURRENT and
                                                      tier in CURRENT):     # LM11 G1: a group runs across the line
            if prev[2] != work and piece not in groups:
                return f"piece {piece} holds two works"
        elif piece in seen:
            return f"piece {piece} is not one run in one tier"
        seen.add(piece)
        works.setdefault(piece, set()).add(work)
        prev = (tier, piece, work)
    single = sorted(p for p in groups if len(works.get(p, ())) == 1)
    if single:
        return f"groups of one work: {single[:5]}"
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
    # K5 (S9): a waiting row of an analysed tier is in no list, so the records give the order (the lists' own when
    # the copy is whole) and the copy's `waiting` list its entry
    by_records = by_records or any(r.get("availability") == "waiting" and r.get("tier") in ANALYSED
                                   for r in recs.values())
    if by_records:
        entries = {path_key(e["physical_path"]): e for t in TIERS for e in norm.tiers[t]}
        for e in norm.lib.get("waiting") or []:
            if isinstance(e, dict) and isinstance(e.get("physical_path"), str):
                entries.setdefault(path_key(e["physical_path"]), e)
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
                if rec.get("availability") == "waiting" and not is_content_name(item["rel_path"]):
                    item["availability"], item["size"], item["mtime_ns"] = "waiting", None, None
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
        _close(conn, db_path, "reader")                # the helper's checkpoint comes at its store's close


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
        if found == "damaged":
            return EXIT_NEEDS_YOU                # no explicit checkpoint: the damage marker just written refuses it
        if found == "pending":
            store.checkpoint()                   # closes keep the `-wal` (§6.12): it never grows while a question waits
            return EXIT_NEEDS_YOU
        if found == "backup failed":
            return EXIT_FAILED
        did = did or found not in ("same", "stale", "unchanged", "newer")
        did = store.count_old_stones() or did   # before the export: the copy carries its version
        if export:
            did = export_copy(store) or did
            _cleanup_temps(manifest_path(user_files_dir))
        if any(k.startswith("reader:") for k in store.meta()) or \
                store.conn.execute("SELECT 1 FROM placement_log LIMIT 1").fetchone():   # a reader off: rows age out
            did = bool(store.prune_log()) or did
        did = bool(store.prune_gone()) or did
        did = bool(store.tidy_works()) or did
        did = bool(store.retitle_folder_works()) or did
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
    from app.connect.power import popen_below_normal          # a7: background work, below the window
    return popen_below_normal(_helper_args(language, "maintain", *extra), env=_helper_env(), creationflags=flags,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=(sys.platform != "win32"))


def _helper_args(language, command, *extra):
    """The helper's command line, frozen (`Surasura.exe library_maintain <command> …`, app_entry's branch)
    or from source (`python app/library_store.py <command> …`). Frozen, it names the Surasura beside the running
    program, never `sys.executable`: Connect's receipts and the command line's writes start the helper from
    surasura-cli.exe, which has no `library_maintain` verb (it refused every one on the laptop's build). `--headless`:
    no window stands behind a detached helper, so its start check logs a version skew and never shows a box."""
    if getattr(sys, "frozen", False):
        from app.path_utils import program_beside
        return [program_beside("Surasura"), "library_maintain", "--headless", command, "--language", language, *extra]
    return [sys.executable, os.path.abspath(__file__), command, "--language", language, *extra]


def _helper_env():
    from app.path_utils import build_subprocess_env
    return build_subprocess_env()


# The copy's trigger after Connect's writes (§6.12: Connect's receipts → re-export): a window hands the copy to the
# helper after its own last change; Connect runs with Surasura closed as often as open, so it does the same —
# OUTSIDE_IDLE_S after its last commit (a burst coalesced into one export), `maintain` when the copy is behind (it
# checkpoints, under the write lock), else Connect's idle checkpoint here (under the write lock too). Nothing written,
# nothing scheduled; a process that exits first runs it at exit. Not the command line's role (`register`): one process
# a hato drop, so a burst of drops would be one export each; its changes reach the copy with Connect's next write, a
# window's, or the next open, as before. Off under the test suites (SURASURA_NO_IDLE_EXPORT, inherited by the command
# lines they start).
_IDLE = {}                       # db key -> (the pending Timer, its arguments)
_IDLE_GUARD = threading.Lock()
_IDLE_AT_EXIT = []               # [True] once the exit hook is registered
_IDLE_RUNNING = set()            # timer threads running a trigger now: the exit hook waits for them
_IDLE_QUIET = threading.local()  # set while a trigger runs on this thread: its own open's write arms no other


def _outside_wrote(store):
    if OUTSIDE_IDLE_S is None or os.environ.get("SURASURA_NO_IDLE_EXPORT") or getattr(_IDLE_QUIET, "on", False):
        return
    key = os.path.normcase(os.path.abspath(store.db_path))
    args = (store.language, store.data_dir, store.user_files_dir, key)
    timer = threading.Timer(OUTSIDE_IDLE_S, _outside_idle, args)
    timer.daemon = True
    with _IDLE_GUARD:
        pending = _IDLE.pop(key, None)
        if pending is not None:
            pending[0].cancel()
        _IDLE[key] = (timer, args)
        if not _IDLE_AT_EXIT:
            import atexit
            atexit.register(_outside_idle_now)
            _IDLE_AT_EXIT.append(True)
    timer.start()


def _outside_idle_now():
    """At exit: every pending trigger now, in this thread, and one a timer is running finished first (its thread is
    a daemon: the interpreter would stop it mid-way)."""
    with _IDLE_GUARD:
        pending = list(_IDLE.values())
        _IDLE.clear()
        running = list(_IDLE_RUNNING)
    for thread in running:
        thread.join(BUSY_AT_OPEN + OUTSIDE_IDLE_WAIT + LOCK_TIMEOUT)    # its waits are bounded: never forever
    for timer, args in pending:
        timer.cancel()
        _outside_idle(*args, at_exit=True)


def _outside_idle(language, data_dir, user_files_dir, key, at_exit=False):
    """One trigger: `maintain` when the copy is behind, else the idle checkpoint. A trigger a later commit replaced
    does nothing (`at_exit`: already taken off the list)."""
    me = threading.current_thread()
    if not at_exit:
        with _IDLE_GUARD:
            pending = _IDLE.get(key)
            if pending is None or pending[0] is not me:
                return
            del _IDLE[key]
            _IDLE_RUNNING.add(me)
    due = False
    _IDLE_QUIET.on = True
    try:
        store = open_store(language, data_dir, user_files_dir, role="connect")    # off any window: it may wait
        if store is None:
            _log(key, "idle trigger: no store to write just now; the next open or write exports")
            return
        try:
            due, _seen = maintain_due(store)
            if not due:
                try:
                    store.checkpoint(wait=OUTSIDE_IDLE_WAIT)
                except StoreBusy:            # a writer holds the lock: the -wal waits for the next checkpoint
                    _log(key, "idle trigger: the write lock was busy; the checkpoint is left to the next one")
        finally:
            store.close()
        if due:
            from app.path_utils import get_data_path
            if os.path.normcase(os.path.abspath(get_data_path(language))) == os.path.normcase(os.path.abspath(data_dir)):
                spawn_maintain(language)         # the helper finds its folders by language (the one install's)
            else:
                _log(key, "idle trigger: the language's data folder is another one now; the copy waits for the "
                          "next open or write")
    except Exception as exc:                     # never the writer's failure: the next window's open exports
        _log(key, f"idle trigger: {type(exc).__name__}: {exc}")
    finally:
        _IDLE_QUIET.on = False
        with _IDLE_GUARD:
            _IDLE_RUNNING.discard(me)


# ------------------------------------------------------------------------------------------------ #
# Disk sync and Reset (§6.10)
# ------------------------------------------------------------------------------------------------ #

def walk_library(data_dir):
    """The walk, outside any transaction: the three tier folders and the content folder (`WALK_FOLDERS`), content
    files only, fingerprints from the listing. Returns {"files": [(rel, size, mtime_ns)], "bad": [names that can't be
    encoded]}."""
    files, bad = [], []
    for folder in WALK_FOLDERS:
        f, b = walk_tree(os.path.join(data_dir, folder), folder)
        files += f
        bad += b
    return {"files": files, "bad": bad}


def reset_walk(data_dir):
    """Today's Reset order: each folder listed, sorted by `name.lower()`, subfolders recursed where they
    fall, the three tier folders in turn, then the content folder."""
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

    for folder in WALK_FOLDERS:
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


def _sync_delta(store, walk, known, scope=None, as_new=()):
    """What a sync would change, computed outside any transaction (§6.10); with `scope`, only within those folders
    (`known` read with the same scope): an item outside them is never looked at (but D2's missing items of a new
    file's size, `_lost_by_size`). `as_new`: keys the user called new (`its_new`) — never a rename. An untracked file in the content
    folder is never the sync's (SRC B2: every copy there comes in through `take_in` or K3; went / came / refresh for
    the known ones as anywhere), nor one a `duplicate` exclusion keeps out (another item's episode, K3)."""
    data_dir = store.data_dir
    walked_tops = _scope_tops(scope) if scope is not None else [path_key(f) + "/" for f in WALK_FOLDERS]
    content = path_key(CONTENT_FOLDER) + "/"
    kept_out = {r[0] for r in store.conn.execute("SELECT pattern FROM exclusions WHERE kind = 'duplicate'")}
    seen, fresh, respell, refresh = set(), [], [], []
    for rel, size, mtime_ns in walk["files"]:
        key = path_key(rel)
        seen.add(key)
        k = known.get(key)
        if k is None:
            if not key.startswith(content) and key not in kept_out:
                fresh.append((rel, key, size, mtime_ns))
            continue
        item_id, stored, _tier, availability, s, m = k
        if stored != rel:
            respell.append((item_id, rel))                         # rule 1: a case-only rename
        if (s, m) != (size, mtime_ns):
            refresh.append((size, mtime_ns, item_id))
    went, came, lost = [], [], []
    for key, (item_id, rel, tier, availability, size, mtime_ns) in known.items():
        under = any(key.startswith(top) for top in walked_tops)
        if under:
            present = key in seen
        else:
            present = os.path.exists(os.path.join(data_dir, _strip(rel)))
        if availability == "available" and not present:
            went.append(item_id)
            lost.append((item_id, rel, size, mtime_ns))
        elif availability == "missing" and present:
            came.append(item_id)
        elif availability == "missing":
            lost.append((item_id, rel, size, mtime_ns))            # D2: gone in an earlier sync, still gone
    # rule 2: a rename = an untracked file + exactly one known item in the same folder, same size and
    # modified time, that went missing since the last sync. FIX1 (MV-A3, Sonic's Decision 1 lean, PROVISIONAL): its
    # time exact and gone in THIS sync — a file of another name is never another's on a rounded time or long after
    # (a moved file keeps its name: rule 2b below reaches further)
    went_set = set(went)
    by_dir = {}
    for item_id, rel, size, mtime_ns in lost:
        if item_id in went_set:
            by_dir.setdefault(path_key(_rel_dir(_strip(rel))), []).append((item_id, size, mtime_ns))
    renames, new, used = [], [], set()
    for rel, key, size, mtime_ns in fresh:
        cands = [c for c in by_dir.get(path_key(_rel_dir(rel)), []) if c[1] == size and c[2] == mtime_ns
                 and key not in as_new]
        if len(cands) == 1 and cands[0][0] not in used:
            used.add(cands[0][0])
            renames.append((cands[0][0], rel, size, mtime_ns))
        else:
            new.append((rel, key, size, mtime_ns))
    # rule 2b (9a, L2.2 05 §5.9; D2): an untracked file + exactly ONE item anywhere in the library with the same file
    # name, size and modified time that went missing (in this sync or an earlier one) and is still gone is that item,
    # moved; two or more are asked, never guessed (the file is held out until the user answers: `relink` or `its_new`)
    asked = {path_key(a.get("rel", "")) for a in _rename_asks(store)}
    if scope is not None and new:
        lost += _lost_by_size(store, [n[2] for n in new], {k[0] for k in known.values()})
    by_name = {}
    for item_id, rel, size, mtime_ns in lost:
        if item_id not in used:
            by_name.setdefault(path_key(_strip(rel).rsplit("/", 1)[-1]), []).append((item_id, size, mtime_ns))
    still, asks = [], []
    for rel, key, size, mtime_ns in new:
        if key in asked:
            continue                                               # held out: its question waits for the user
        cands = [c for c in by_name.get(path_key(rel.rsplit("/", 1)[-1]), [])
                 if c[1] == size and _same_time(c[2], mtime_ns) and c[0] not in used and key not in as_new]
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


SAME_TIME_NS = 2_000_000_000            # D2: FAT keeps even seconds, exFAT 10 ms; an SMB share rounds within them
FAT_HOUR_NS = 3_600_000_000_000         # D2: FAT keeps local time — a summer-time change moves a file an hour


def _same_time(a, b):
    """Rule 2b (D2; rule 2 asks an exact time, FIX1): one file's modified time as two file systems kept it — equal, within 2 s, or an hour off
    within 2 s. A time 3 s off is another file (two episodes can be one size)."""
    if a == b:
        return True
    if a is None or b is None:
        return False
    d = abs(a - b)
    return d <= SAME_TIME_NS or abs(d - FAT_HOUR_NS) <= SAME_TIME_NS


def _lost_by_size(store, sizes, seen_ids):
    """D2, a scoped sync: the missing items outside its folders (not in `seen_ids`) of these sizes whose file is still
    gone, as `_sync_delta`'s `lost` [(id, rel_path, size, mtime_ns)] — read through `items_missing`, never a walk or a
    scan of the library (a store whose writer hasn't made the index yet reads them all the same, slower)."""
    sizes = [s for s in dict.fromkeys(sizes) if isinstance(s, int)]
    out = []
    for chunk in _chunks(sizes, 500):
        for item_id, rel, size, mtime_ns in store.conn.execute(
                f"SELECT id, rel_path, size, mtime_ns FROM items WHERE availability = 'missing' AND size IN "
                f"({','.join('?' * len(chunk))}) ORDER BY id", chunk):
            if item_id not in seen_ids and not os.path.exists(os.path.join(store.data_dir, _strip(rel))):
                out.append((item_id, rel, size, mtime_ns))
    return out


MOVED_PATHS_KEEP = 500                 # D7a: the move notes kept (a note older than the index's next pass is spent)


def _moved_paths(store):
    """D7a's notes (`meta.moved_paths`): [[old rel, old size, old mtime_ns, new rel, size, mtime_ns]], oldest first.
    Never in the copy: a note lost costs one file read, never a count."""
    row = store.conn.execute("SELECT value FROM meta WHERE key = 'moved_paths'").fetchone()
    try:
        notes = json.loads(row[0]) if row else []
    except ValueError:
        return []
    return [n for n in notes if isinstance(n, list) and len(n) == 6] if isinstance(notes, list) else []


def _note_moves(store, moves):
    """D7a, inside the write that follows the moves (the sync's rule 1 / 2 / 2b, `relink` — never `_repoint`, which an
    edition switch also calls for new bytes): each [old rel, old size, old mtime_ns, new rel, size, mtime_ns] the token
    store may re-key by (its row is the old file's, the new file is still that size and time)."""
    if moves:
        notes = _moved_paths(store) + [list(m) for m in moves]
        store._set_meta({"moved_paths": _dumps(notes[-MOVED_PATHS_KEEP:])})


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


def _store_sync_disk(self, walk=None, folders=None, as_new=()):
    """The disk sync (§6.10): files nothing tracks join the library by rule 3; renames keep their place;
    missing files are marked, never removed. No delta → no write lock, no commit. Returns a summary
    {"added", "renamed", "missing", "back", "bad"} or None when nothing changed. `folders`: only those folders
    (relative to data/<lang>) and what is under them — the ones the window's poll saw change (`DiskPoll.changed`,
    L3.1: a hato drop costs its folder's walk, not the library's). `as_new`: files the user called new (`its_new`,
    relative to data/<lang>), never matched to a missing item."""
    as_new = {path_key(r) for r in as_new}
    scope = list(folders) if folders else None
    walk = walk or (walk_folders(self.data_dir, scope) if scope else walk_library(self.data_dir))
    known, version = _known(self, scope)
    delta = _sync_delta(self, walk, known, scope, as_new)
    if scope and delta["went"]:
        # 9a: a file gone from a polled folder may have moved to a folder the poll can't see (one holding no item):
        # the whole library is looked at in this same check, so the move is followed (the intent review #5)
        scope, walk = None, walk_library(self.data_dir)
        known, version = _known(self, None)
        delta = _sync_delta(self, walk, known, None, as_new)
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
            delta = _sync_delta(self, walk, known, scope, as_new)
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
        tiers, found, moves = set(), [], []
        stamp = lambda item_id: self.conn.execute("SELECT size, mtime_ns FROM items WHERE id = ?", (item_id,)).fetchone()
        for item_id, rel, size, mtime_ns in delta["renames"]:
            if item_id not in rows or not exists(rel) or exists(rows[item_id][5]) or self.conn.execute(
                    "SELECT 1 FROM items WHERE rel_key = ?", (path_key(rel),)).fetchone():
                continue                                           # a stale walk: leave it to the next sync
            moves.append((rows[item_id][5], *stamp(item_id), rel, size, mtime_ns))
            self._repoint(item_id, rel, size, mtime_ns)
            tiers.add(rows[item_id][1])
            summary["renamed"].append(item_id)
            if rows[item_id][6] == "missing":
                found.append(item_id)                              # D2: missing since an earlier sync, available again
        for item_id, rel in delta["respell"]:
            if exists(rel):
                old_size, old_mtime = stamp(item_id)
                moves.append((rows[item_id][5], old_size, old_mtime, rel, old_size, old_mtime))
                self._repoint(item_id, rel)
                tiers.add(rows[item_id][1])
                summary["renamed"].append(item_id)
        _note_moves(self, moves)                                   # D7a: the token store's hint
        gone = [i for i in delta["went"] if i in rows and not exists(rows[i][5])]
        back = [i for i in delta["came"] if i in rows and exists(rows[i][5])]
        if gone:
            self.conn.executemany("UPDATE items SET availability = 'missing' WHERE id = ?", [(i,) for i in gone])
        if back:
            self.conn.executemany("UPDATE items SET availability = 'available' WHERE id = ?", [(i,) for i in back])
        cmd.feed(gone + back)
        if gone or back or found:
            cmd.touch({rows[i][1] for i in gone + back + found}, availability=True)
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
        known |= {r[0] for r in self.conn.execute("SELECT pattern FROM exclusions WHERE kind = 'duplicate'")}  # K3
        arrivals = cmd.meta.get("arrivals_on")
        content = path_key(CONTENT_FOLDER) + "/"           # the content folder's copies come in by `take_in` only (B2)
        untracked = [rel for rel in order if path_key(rel) not in known and not (arrivals and _in_hato(rel))
                     and not path_key(rel).startswith(content)]
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
    under the tier folders and the content folder — folders that hold no item included, which the old poll never looked at — listed a batch
    at a time (`step`), each folder's content files compared with the items the store holds directly in it.
    Listings, sizes and times only; a folder whose listing differs is handed back for a scoped sync. Nothing is kept
    between rounds: one a close interrupts starts over (the next open's full look covers it)."""

    def __init__(self, store):
        from collections import deque
        self.store = store
        self.queue = deque(WALK_FOLDERS)
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
    """Does an item that counts (`counts`, W-1) have a file that is there? (The dashboard's Generate button, §7.)"""
    return self.conn.execute(f"SELECT EXISTS (SELECT 1 FROM items WHERE {counts_sql(self._keep_watched())} "
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
    if STONES_COUNTED not in meta:
        return True, seen                        # W-1: the first start's count of old watched marks (`count_old_stones`)
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
            # Closes keep the `-wal` for a checkpoint under the lock (§6.12): with no helper to run (nothing to
            # export, or a re-import question waiting), it is this one, never waited for (a writer holding the lock
            # has its own trigger, or the next close)
            try:
                store.checkpoint(wait=0.0)
            except (StoreError, sqlite3.Error):
                pass
    if not due:
        return None
    lock = MaintenanceLock(library_db_path(language, data_dir))
    try:
        if not lock.try_acquire():
            return EXIT_BUSY
        return maintain(language, data_dir, user_files_dir, lock=lock)
    finally:
        lock.close()


def read_only_schedule(language, data_dir, user_files_dir, with_aside=False):
    """Read-only mode (§6.9): the copy's schedule, with the walk's untracked files added in memory by
    §6.10 rule 3 (never saved), so a file dropped into a tier folder is still analysed. Every file the
    copy knows, in any tier, counts as known (D6). W-1: an item that doesn't count by the copy's own records and
    meta (`counts`: watched, `keep_watched` off) leaves the list, as `Store.schedule` leaves it out — still known,
    never added back as untracked. `with_aside`: also `ASIDE`, the items the copy sets aside (`sets_aside`: its
    Finished entries, a video still waiting for its subtitle left out, and those watched items), as `Store.schedule`
    lists them. None when the copy can't be read."""
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
    known |= _copy_duplicates(lib)                     # another item's episode (K3): never added, as the sync's rule
    with_items = {path_key(_rel_dir(_strip(str(e.get("physical_path") or "")))) for e in held + others}
    tops = {t: 0 for t in ANALYSED}
    marker_cache = {}
    hato = path_key(HATO_FOLDER)
    content = path_key(CONTENT_FOLDER) + "/"
    for rel, _size, _mtime in walk_library(data_dir)["files"]:
        key = path_key(rel)
        if key in known or key.startswith(content):    # the content folder's copies are the store's only (B2)
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
    try:                                                   # W-1: the one rule, read from the copy
        keep = bool((lib.get("meta") or {}).get("keep_watched"))
    except AttributeError:
        keep = False
    records = _records(lib)
    watched = {key for key, rec in records.items() if rec.get("watched") == 1}
    aside = []                                             # W-1b: Finished's entries first, as `sets_aside` reads them
    for tier in REFERENCE:
        for e in lib.get(tier) or ():
            if not isinstance(e, dict):
                continue
            key = path_key(_strip(str(e.get("physical_path") or "")))
            if (records.get(key) or {}).get("availability") != "waiting":    # no text yet, as the store leaves it
                aside.append({"physical_path": e.get("physical_path"), "source_type": e.get("source_type")})
    if watched:
        for tier in ANALYSED:
            kept = []
            for e in lists[tier]:
                if not isinstance(e, dict) or counts(tier, path_key(_strip(str(e.get("physical_path") or ""))) in
                                                     watched, keep):
                    kept.append(e)
                else:
                    aside.append({"physical_path": e.get("physical_path"), "source_type": e.get("source_type")})
            lists[tier][:] = kept
    if with_aside:
        schedule[ASIDE] = aside
    return schedule


def _copy_duplicates(lib):
    """The patterns of the copy's `duplicate` exclusions (K3; K1a's N9): files read-only mode never adds. A table the
    copy lacks or can't be read as one: none."""
    table = (lib.get("tables") or {}).get("exclusions") if isinstance(lib.get("tables"), dict) else None
    if not isinstance(table, dict) or not isinstance(table.get("fields"), list):
        return set()
    fields = table["fields"]
    if "pattern" not in fields or "kind" not in fields:
        return set()
    p, k = fields.index("pattern"), fields.index("kind")
    return {r[p] for r in table.get("rows") or () if isinstance(r, list) and len(r) == len(fields) and
            r[k] == "duplicate" and isinstance(r[p], str)}


SYNC_IN_PROCESS_AT = 20_000      # items: from here a window's process syncs in a process of its own (§12.1)
SYNC_TIMEOUT = 120.0
BUILD_SPAWN_EVERY = 60.0          # s: "no store yet" spawns the builder at most this often per language
_build_spawned = {}


def sync_for_window(store, folders=None):
    """`sync_disk` for a window's process (the dashboard's journey check, the Content Manager), called on a
    worker. At 100k a sync on a worker thread still stalled the window 20–60 ms through the interpreter
    lock, whatever the switch interval (§12.1), so from `SYNC_IN_PROCESS_AT` items the sync runs in a
    process of its own and this thread only waits for it. Returns sync_disk's summary (in-process) or None
    (the Content Manager reads a summary as a dict). The helper's exit code is read: one that found the store
    busy, failed or ran out of time raises `StoreBusy`, as the sync in-process does — the caller keeps the
    folders owed (W3.2 L1 S1)."""
    count = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if count < SYNC_IN_PROCESS_AT:
        return store.sync_disk(folders=folders)
    import subprocess
    args = _helper_args(store.language, "sync") + [a for f in (folders or ()) for a in ("--folder", f)]
    flags = 0x08000000 if sys.platform == "win32" else 0                # CREATE_NO_WINDOW
    try:
        code = subprocess.run(args, env=_helper_env(), creationflags=flags, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=SYNC_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        raise StoreBusy("the library's sync took too long") from None
    if code in (EXIT_BUSY, EXIT_FAILED):
        raise StoreBusy("the library is busy" if code == EXIT_BUSY else "the library's sync failed")
    return None


def read_only_view(language, data_dir, user_files_dir):
    """The store as a caller that must write nothing sees it (surasura-cli `status`, P1.2): opened `mode=ro` — never
    built, synced, repaired, re-derived or marked damaged — and read in one transaction. -> (mode, schedule, versions,
    pending):

      * ("store", schedule, versions, pending): a ready store, its analysed tiers as `Store.schedule` reads them (its
        set-aside items too: `ASIDE`, the run signature's "reference" part);
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
            schedule, versions = store.schedule(with_versions=True, with_aside=True)
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


UNREAD = "unread"       # `read_watched_marks`: a store there, its marks not readable at this moment


def read_watched_marks(language, data_dir):
    """The journey's stones for the report and its render signature: `Store.watched_marks` through a `mode=ro` look
    (never built, synced or waited on, as `read_auto_band`), in one read transaction. None with no ready store (JSON
    mode, the switch off, a damaged store, one made by a newer Surasura or read-only on a newer one's copy): the
    report is then what it was. `UNREAD` when the store is there but can't be read now (busy, an sqlite error): a
    report drawn so is never recorded as current (`analyzer.signed_render`)."""
    if not STORE_LIVE:
        return None
    db_path = library_db_path(language, data_dir)
    if not os.path.exists(db_path) or os.path.exists(damaged_marker(db_path)):
        return None
    import pathlib
    try:
        conn = sqlite3.connect(pathlib.Path(db_path).as_uri() + "?mode=ro", uri=True, timeout=1.0,
                               isolation_level=None)
    except (ValueError, TypeError):
        return None
    except sqlite3.Error:
        return UNREAD
    try:
        conn.execute("PRAGMA query_only=1")
        if (conn.execute("PRAGMA user_version").fetchone()[0] != STORE_SCHEMA
                or conn.execute("SELECT 1 FROM meta WHERE key = 'newer_copy'").fetchone()
                or conn.execute("SELECT value FROM meta WHERE key = 'migrated_at'").fetchone() is None):
            return None
        store = Store.__new__(Store)            # a reader on this connection, as `read_only_view`'s
        store.db_path, store.language, store.data_dir, store.user_files_dir = db_path, language, data_dir, None
        store.role, store.conn, store._depth, store._cmd, store._repairing = "reader", conn, 0, None, False
        return store.watched_marks()
    except sqlite3.Error:
        return UNREAD
    finally:
        conn.close()


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
# Sources (3.0, SRC K1a): folders read where they are, their text copied into the content folder
# ------------------------------------------------------------------------------------------------ #
#
# A source is a `roots` row (`kind` 'source', 'source-off' once *Stop reading*, its `path` absolute and normalised).
# The scan (`app/sources.py`, K1b) copies each new text file into `Library/<show>/` outside any lock and hands the batch
# to `take_in`; every origin is one `pairings` row keyed "src:" + its path key (B1), so a file is read once whichever
# source found it. Remove keeps an origin out for good (an `exclusions` row); Finish keeps its records.

SKIP_DIRS = ("$recycle.bin", "#recycle", "@eadir", ".stversions", ".trash", "system volume information", "@recycle",
             "#snapshot", "@recently-snapshot", "~snapshot", ".snapshot",   # + QNAP's / Synology's bins and snapshots
             "node_modules",    # a web project's packages: thousands of folders, its `.ts` files no videos (K6, S9)
             ".appledouble", ".trashes", ".spotlight-v100", ".fseventsd", ".temporaryitems")   # a Mac's (LF-21)
PLACEHOLDER_ATTRS = 0x1000 | 0x40000 | 0x400000   # OFFLINE · RECALL_ON_OPEN · RECALL_ON_DATA_ACCESS (Connect's `_on_disk`)
_LINK_TAGS = (0xA000000C, 0xA0000003)              # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (a junction)
_DIGITS = re.compile(r"(\d+)")
_EPUB_PART = re.compile(r"\.epub#\d+$", re.I)    # an EPUB's part's origin (`<book>.epub#3`)
Origin = namedtuple("Origin", "item_id root origin size mtime_ns sha256 rel_path availability paired_at version "
                              "video_path video_size video_key declined thin moved_to chapter", defaults=(None,) * 8)


def origin_key(path):
    """An origin's `pairings.content_key` (B1): "src:" + the path key of its absolute, normalised path."""
    return SOURCE_KEY + path_key(os.path.abspath(path))


_LOCAL_SHARE = re.compile(r"^\\\\(?:localhost|127\.0\.0\.1)\\([A-Za-z])\$(?=\\|$)", re.IGNORECASE)


def folder_path(path):
    r"""A folder's one spelling (A2): absolute and normalised, with Windows' long-path prefixes (`\\?\C:\…`,
    `\\?\UNC\server\share\…`) and this computer's own admin share (`\\localhost\C$\…`) read back as the plain
    path."""
    p = str(path)
    if sys.platform == "win32":
        p = p.replace("/", "\\")
        if p[:8].upper() == "\\\\?\\UNC\\":
            p = "\\\\" + p[8:]
        elif p.startswith("\\\\?\\"):
            p = p[4:]
        p = _LOCAL_SHARE.sub(lambda m: m.group(1) + ":", p)
    return os.path.normpath(os.path.abspath(p))


def _folder_id(path):
    """(st_dev, st_ino) of a folder, its links followed, or None (gone, unreadable, or a file system with no ids)."""
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino) if st.st_ino else None


def _ancestors(path):
    """`path` and every folder above it, up to its drive."""
    while True:
        yield path
        up = os.path.dirname(path)
        if up == path:
            return
        path = up


def skip_dir(name, path):
    """Does a look at a source folder skip this folder (B3)? The folders SKIP_DIRS names — Syncthing's .stversions,
    .trash, the recycle bins (Windows' and a NAS's), a NAS's @eaDir and snapshots, System Volume Information, a web
    project's node_modules, the folders a Mac writes (.AppleDouble, .Trashes…: LF-21; any other dot folder is a name,
    `.hack`) — and a folder link or junction — never followed:
    one that loops never ends, one into the data folder brings it back. `path`: the folder's path, or its `os.DirEntry`
    (the listing's own stat: no call)."""
    if unicodedata.normalize("NFKC", name).casefold() in SKIP_DIRS:
        return True
    try:
        st = path.stat(follow_symlinks=False) if isinstance(path, os.DirEntry) else os.lstat(path)
    except OSError:
        return True
    return is_link(st)


def is_link(st):
    """Is this stat (never followed: `os.lstat`, a listing's own) a symlink or a junction? The one link rule: a look
    never walks into one (`skip_dir`), a fresh library never copies or removes through one (`_set_aside`, LF-4)."""
    import stat
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


def is_placeholder(st):
    """A cloud placeholder (B3, RD-S1): its read would download it, so neither its text nor a video's key is read. A
    stat with no attributes (POSIX) is an ordinary file (S17)."""
    return bool(getattr(st, "st_file_attributes", 0) & PLACEHOLDER_ATTRS)


def sha256_of(path):
    """The sha256 of a file's bytes, as an origin record and an exclusion's note hold it."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def same_size_items(conn, sizes, sources_only=False):
    """Never a duplicate (SRC-7, K3), its first half: {size: [(item_id, rel_path, title)]} of the live items whose file
    is one of these sizes, in id order; the title its work's, else its own. `sources_only`: only the items a source
    folder's origin is recorded on (hato after a source). One read: `conn` is a store's (inside its read) or a
    `mode=ro` look's. The second half, the bytes, is `holding`."""
    sizes = [s for s in dict.fromkeys(sizes) if isinstance(s, int)]
    only = f" AND EXISTS (SELECT 1 FROM pairings p WHERE p.item_id = i.id AND {_ORIGIN_ROW})" if sources_only else ""
    out = {}
    for chunk in _chunks(sizes, 500):
        for size, item_id, rel, title in conn.execute(
                f"SELECT i.size, i.id, i.rel_path, COALESCE(w.title, i.title) FROM items i LEFT JOIN works w ON "
                f"w.id = i.work_id WHERE i.availability = 'available' AND i.size IN ({','.join('?' * len(chunk))})"
                f"{only} ORDER BY i.id", chunk):
            out.setdefault(size, []).append((item_id, rel, title or ""))
    return out


def holding(data_dir, files, rows):
    """K3: {path: (item_id, title)} for each `(path, size)` of `files` whose bytes are another item's file's (`rows` from
    `same_size_items`; never the row of the file itself), the lowest id — a file read only when its size matches one,
    each file once. A file that can't be read holds nothing."""
    hashes, out = {}, {}
    for path, size in files:
        for item_id, rel, title in rows.get(size, ()):
            if path_key(os.path.abspath(os.path.join(data_dir, *rel.split("/")))) == path_key(os.path.abspath(path)):
                continue                           # the file's own row: never its own twin
            mine = _sha_once(hashes, path)
            if mine is not None and mine == _sha_once(hashes, os.path.join(data_dir, *rel.split("/"))):
                out[path] = (item_id, title)
                break
    return out


def _sha_once(hashes, path):
    if path not in hashes:
        try:
            hashes[path] = sha256_of(path)
        except OSError:
            hashes[path] = None
    return hashes[path]


def _store_items_holding(self, paths, sources_only=False):
    """K3: {path: (item_id, title)} of the files in `paths` whose bytes a live item's file holds (size first, then the
    sha256: `same_size_items`, `holding`) — the sizes read in one short read, the files hashed after it."""
    files = []
    for p in paths:
        try:
            files.append((p, os.stat(p).st_size))
        except OSError:
            continue
    if not files:
        return {}
    with self._reading():
        rows = same_size_items(self.conn, [s for _p, s in files], sources_only)
    return holding(self.data_dir, files, rows)


def _store_twin_seen(self, path, content_key, pairing):
    """K3 (1), before `register`'s command (F12: inside it, every record read and every file of the size hashed held the
    write lock 0.1 s at 20k origins, and seconds when sizes repeat): what hato's file at `path` may be already —
    (stamp, the waiting item of its video, the live item holding its video, (the item holding its bytes, its rel, its
    size)), each None when none — in one short read; the bytes hashed after it. Checked in this order: a folder's
    video waiting for its subtitle (`_waiting_video`, R3), the item holding the video (`_video_holder`: hato's key, an
    origin's `video_key`, any item's record: SRC-7, every channel), any live item but `path`'s own row whose file holds
    the same bytes (size first, then the sha256) — only when TWIN_HASHES items or fewer have its size; more, and the
    file is checked by its video alone. `stamp` (`_twin_stamp`): what a twin found since would have moved."""
    try:
        size = os.stat(path).st_size
    except OSError:
        size = None
    rows = {}
    with self._reading():
        stamp = self._twin_stamp()
        gap = self._waiting_video(content_key, pairing)
        video = self._video_holder(content_key) if gap is None else None
        if gap is None and video is None and size is not None:
            rows = same_size_items(self.conn, [size])
    mine = path_key(os.path.abspath(path))
    rows = [r for r in rows.get(size, ()) if path_key(os.path.abspath(os.path.join(
        self.data_dir, *r[1].split("/")))) != mine]                  # the file's own row: never its own twin
    same = None
    if rows and len(rows) <= TWIN_HASHES:
        held = holding(self.data_dir, [(path, size)], {size: rows})
        if path in held:
            same = (held[path][0], next(r[1] for r in rows if r[0] == held[path][0]), size)
    return stamp, gap, video, same


def _store_twin_stamp(self):
    """What a twin found before `register`'s command would have moved since (F12): a record or an item added (a record's
    rowid grows with every insert or replace; an item's id is AUTOINCREMENT's), an item's availability changed, or an
    item put back (Put back and Undo bring an item back under its old id, with no record when it had none: the trash's
    restored rows count them). A move, a pin or a title moves none of them."""
    return self.conn.execute("SELECT (SELECT MAX(rowid) FROM pairings), (SELECT seq FROM sqlite_sequence WHERE name = "
                             "'items'), (SELECT value FROM meta WHERE key = 'availability_version'), "
                             "(SELECT COUNT(restored_at) FROM trash)").fetchone()


def _store_video_holder(self, key):
    """The lowest live (not waiting) item whose record holds this video — hato's `content_key`, or an origin's
    `video_key` — or None: one read, the records' video read by SQLite (no copy of every record in Python)."""
    if not isinstance(key, str) or not key or key.startswith(SOURCE_KEY):
        return None
    return self.conn.execute(
        f"SELECT MIN(p.item_id) FROM pairings p JOIN items i ON i.id = p.item_id WHERE i.availability != 'waiting' AND "
        f"((p.content_key = ? AND NOT {_ORIGIN_ROW}) OR ({_ORIGIN_ROW} AND json_valid(p.pairing) AND "
        f"json_extract(p.pairing, '$.video_key') = ? AND NOT {_VERSION_ROW}))", (key, key)).fetchone()[0]


def _store_twin_now(self, seen, path, content_key, pairing):
    """K3 (1), inside `register`'s command: (the waiting item hato's file fills, (the live item it is another copy of,
    the `Library` copy hato's file takes over or None)) — None each when none. The item `_twin_seen` found is checked
    again, alone; when anything a twin would move has moved since (`_twin_stamp`), or that item is no longer what it
    was, the whole check runs again here (bounded as before: TWIN_HASHES files at most). The copy (R2) only for a
    source's item found by its own video (not by hato's record already on it: a retry of a kept-out file stays kept
    out) whose file is in `Library`: any other item's file (hato's, a 2.x file) is never left untracked."""
    stamp, gap, video, same = seen
    if tuple(stamp) != tuple(self._twin_stamp()) or not self._still_twin(gap, video, same, content_key, pairing):
        _stamp, gap, video, same = self._twin_seen(path, content_key, pairing)
    if gap is not None:
        return gap, None
    if video is not None:
        rel = self.conn.execute("SELECT rel_path FROM items WHERE id = ?", (video,)).fetchone()[0]
        source = self.conn.execute(f"SELECT 1 FROM pairings p WHERE p.item_id = ? AND {_ORIGIN_ROW}",
                                   (video,)).fetchone() and not self.conn.execute(
            "SELECT 1 FROM pairings WHERE item_id = ? AND content_key = ?", (video, content_key)).fetchone()
        inside = path_key(rel.split("/", 1)[0]) == path_key(CONTENT_FOLDER)
        return None, (video, rel if source and inside else None)
    return None, ((same[0], None) if same is not None else None)


def _store_still_twin(self, gap, video, same, content_key, pairing):
    """F12: is the one item `_twin_seen` found still that (read by its id: its row and its own records)?"""
    if gap is not None:
        row = self.conn.execute("SELECT availability FROM items WHERE id = ?", (gap,)).fetchone()
        keys = {content_key, *_video_keys(pairing)}
        return row is not None and row[0] == "waiting" and any(keys & set(_video_keys(_json_dict(t) or {})) for (t,) in
                                                                self.conn.execute(
            f"SELECT p.pairing FROM pairings p WHERE p.item_id = ? AND {_ORIGIN_ROW}", (gap,)))
    if video is not None:
        row = self.conn.execute("SELECT availability FROM items WHERE id = ?", (video,)).fetchone()
        if row is None or row[0] == "waiting":
            return False
        return any((k == content_key and not k.startswith(SOURCE_KEY)) or
                   (k.startswith(SOURCE_KEY) and (_json_dict(t) or {}).get("video_key") == content_key)
                   for k, t in self.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?", (video,)))
    if same is not None:
        row = self.conn.execute("SELECT availability, rel_path, size FROM items WHERE id = ?", (same[0],)).fetchone()
        return row is not None and tuple(row) == ("available", same[1], same[2])
    return True


def _store_sync_drop(self, item_id, rel, pairing):
    """K3 R1: is this the row the disk sync made for hato's file a moment before hato's hand-off — hato's drop folder,
    waiting in New arrivals (with New arrivals off: still at the top of NOW, where the sync puts hato's files — only
    hato's drops above it), hato's record, nothing of anyone's on it yet (no record, link, pin, watch, mining or
    placement by a person)? Only such a row is taken out when the file is an episode already in."""
    if _producer(pairing) != "hato" or not _in_hato(rel):
        return False
    row = self.conn.execute("SELECT tier, pinned, watched, mined_at, ord FROM items WHERE id = ?",
                            (item_id,)).fetchone()
    meta = self._cmd.meta if self._cmd is not None else self._meta()
    tiers = ("arrivals",) if meta.get("arrivals_on") else ("arrivals", "now")
    if row is None or row[0] not in tiers or row[1] is not None or row[2] or row[3] is not None:
        return False
    if row[0] == "now":                    # a drag elsewhere in NOW leaves no event unless a reader logs: its place
        hato = path_key(HATO_FOLDER) + "/"
        if self.conn.execute("SELECT 1 FROM items WHERE tier = 'now' AND (ord < ? OR (ord = ? AND id < ?)) AND "
                             "substr(rel_key, 1, ?) != ? LIMIT 1",
                             (row[4], row[4], item_id, len(hato), hato)).fetchone():
            return False
    return not any(self.conn.execute(sql, (item_id,)).fetchone() for sql in (
        "SELECT 1 FROM pairings WHERE item_id = ?", "SELECT 1 FROM anki_links WHERE item_id = ?",
        "SELECT 1 FROM placement_log WHERE item_id = ? AND (explicit = 1 OR by = 'user')"))


def _store_take_out(self, cmd, item_id):
    """K3 R1: the sync's row for hato's file leaves without a trash row (nothing to put back: its episode is another
    item's); the feed's tombstone written, its piece and title tidied as a Remove's are. The file stays."""
    tier, piece = self.conn.execute("SELECT tier, piece_id FROM items WHERE id = ?", (item_id,)).fetchone()
    self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    cmd.gone.append(("item", item_id))
    if piece is not None:
        cmd.pieces_left.add(piece)
    cmd.touch({tier})


def _store_waiting_video(self, content_key, pairing):
    """K3 R3: the item waiting for this video's subtitle (K5) — by hato's key, or the record's video path — or None."""
    gaps = self._waiting_videos()
    for k in [content_key] + _video_keys(pairing):
        if k in gaps:
            return gaps[k]
    return None


def content_target(data_dir, rel, size=None, sha256=None):
    """Where a copy goes (B2): (rel, reuse). `rel` itself when free; a file already there with the same size and bytes
    is re-used (a copy a crash left between the copy and its `take_in`: never copied again as `name (2)`); else
    `name (2).ext`, `name (3).ext`, … — moves' `_copy_whole` rule — the first free or same-bytes one. Only "not
    found" is free: any other stat error (access denied, a name Windows rejects) is raised, for the scan to skip the file."""
    base, ext = os.path.splitext(rel)
    n = 1
    while True:
        candidate = rel if n == 1 else f"{base} ({n}){ext}"
        n += 1
        full = os.path.join(data_dir, *candidate.split("/"))
        try:
            st = os.stat(full)
        except FileNotFoundError:
            return candidate, False
        if size is not None and sha256 and st.st_size == size and sha256_of(full) == sha256:
            return candidate, True


def _natural(name):
    """A file name's natural order key: `ep2` before `ep10`, full-width digits as digits, case folded."""
    parts = _DIGITS.split(unicodedata.normalize("NFKC", name).casefold())
    return [int(p) if n % 2 else p for n, p in enumerate(parts)]


def _origin_record(root_id, origin, f):
    """An origin's record (B1): hato's shape, so Connect's `video()` and the video index read it as they read hato's;
    `channel_id` is the source's id (S13: a `source:<id>` placing rule needs no code)."""
    record = {"producer": SOURCE_PRODUCER, "channel_id": root_id, "root": root_id, "origin": origin,
              "size": f.get("size"), "mtime_ns": f.get("mtime_ns"), "sha256": f.get("sha256"),
              "show": {"title": str(f.get("show") or "")}}
    for key in ("video_path", "video_size", "video_key", "episode", "chapter",    # chapter: a book's part's place
                "audiobook"):                                   # (`extract.book_split`, Hon); an audiobook's (H-7)
        if f.get(key) is not None:                              # files, length and pairing: `audiobooks.record`
            record[key] = f[key]
    return record


def _store_copy_dirty(self):
    """Bookkeeping the copy carries (§6.6): no version moves, the next export writes it."""
    self._set_meta({"copy_dirty": self._meta().get("copy_dirty", 0) + 1})


def _store_not_a_source(self, path):
    """Why `path` can't be a source (B3), or None: not a folder; a whole drive; the user's profile folder; Surasura's own
    folders — every language's data and user files, the store's folder — a folder inside one, or one that holds one
    (its scan would bring back the data folder's .trash as new episodes and read the word lists as books)."""
    if not isinstance(path, str) or not path.strip() or not os.path.isdir(folder_path(path)):
        return "That isn't a folder on this computer."
    norm = folder_path(path)                         # one spelling (A2), then one folder by its identity too
    forms = {norm, os.path.realpath(norm)}
    if any(os.path.dirname(p) == p for p in forms):
        return "A whole drive holds too much to read; choose the folder your shows and books are in."
    keys = {path_key(p).rstrip("/") for p in forms}
    ids = {_folder_id(norm)} - {None}
    home = os.path.expanduser("~")
    if home != "~" and (path_key(os.path.normpath(home)).rstrip("/") in keys or _folder_id(home) in ids):
        return "Your user folder holds too much to read; choose the folder your shows and books are in."
    own = [folder_path(os.path.dirname(os.path.abspath(d))) for d in (self.data_dir, self.user_files_dir, self.db_path)]
    own += [os.path.realpath(o) for o in own]
    mine, mine_ids = {path_key(o).rstrip("/") for o in own}, {_folder_id(o) for o in own} - {None}
    for f in forms:                                  # it, or a folder above it, is one of Surasura's own
        for up in _ancestors(f):
            if path_key(up).rstrip("/") in mine or _folder_id(up) in mine_ids:
                return "That folder is Surasura's own; choose the folder your shows and books are in."
    for o in own:                                    # it is a folder above one of Surasura's own
        for up in list(_ancestors(o))[1:]:
            if path_key(up).rstrip("/") in keys or _folder_id(up) in ids:
                return "That folder holds Surasura's own; choose the folder inside it your shows and books are in."
    from app import import_2x                        # a Surasura program's folder, or an old one's (the 2.x import
    for f in forms:                                  # brings no shows: they're added from where 2.x kept them)
        for up in _ancestors(f):
            if not (import_2x.holds_program(up) or import_2x.is_2x_folder(up)):
                continue
            below = os.path.relpath(f, up).replace(os.sep, "/").split("/")
            inside_own = below[0] in OLD_SURASURA_OWN or ".trash" in below or (below[0] == "data" and len(below) <= 2)
            if up == f or inside_own:
                return ("That's a Surasura folder: its program, word lists and trash would be read as books. Choose "
                        "the folders your shows and books are in (an old Surasura keeps them in its data folder).")
    return None


def _store_add_source(self, path):
    """A folder Surasura reads where it is (SRC-10) -> its root id. Refused with `NotASource` (its `reason` for the
    window) before anything is written (`_not_a_source`). The same folder again, however written, is its row — turned
    back on when it was stopped, so it is never copied in a second time."""
    reason = self._not_a_source(path)
    if reason:
        raise NotASource(reason)
    norm = folder_path(path)
    key, ident = path_key(norm), _folder_id(norm)
    sql = "SELECT id, path, kind FROM roots WHERE kind IN ('source', 'source-off') ORDER BY id"
    with self._reading():                            # a source's folder stat'ed outside the write lock (A6)
        rows = self.conn.execute(sql).fetchall()
    alike = {r[0] for r in rows if r[1] and ident is not None and _folder_id(r[1]) == ident}
    with self._writing():
        rows = self.conn.execute(sql).fetchall()
        same = [r for r in rows if r[1] and path_key(folder_path(r[1])) == key] or [r for r in rows if r[0] in alike]
        for root_id, _held, kind in same[:1]:       # its row, its path as first written: its origins' keys stay
            if kind != "source":
                self.conn.execute("UPDATE roots SET kind = 'source' WHERE id = ?", (root_id,))
                self._copy_dirty()
            return root_id
        root_id = self.conn.execute("INSERT INTO roots (kind, path, placement, catalogue_only, created_at) "
                                    "VALUES ('source', ?, NULL, 0, ?)", (norm, _now())).lastrowid
        self._copy_dirty()
    return root_id


def _store_sources(self, all=False, counts=True):
    """[{id, path, on, items}] of the sources being read (`all`: the stopped ones too), in the order added; `items` =
    the live items with an origin under its folder, whichever source recorded it (the offline line's count: *its 412
    episodes are kept*; item 8b: a show's folder added inside a folder read before counts the episodes that one took
    in) — by the origin keys' path, `/`-ended (`…\\Show` never counts `…\\Show S2`); an origin whose original
    moved to another folder (D5's `moved_to`) counts in its new place only. `counts=False` (a look,
    Connect's video index): the roots' rows alone, no origin read. Each folder's count is SQLite's, one row a folder,
    over its keys' range in the table's own key (`<folder>/` up to `<folder>0`): no origin key comes into Python (W4.1:
    at 20k origins every look's summary read them all, ~1 s while the window scrolled, its thread waiting for the
    interpreter row after row), and never a GROUP BY (its temporary B-tree went to disk: 14 MB written per call)."""
    kinds = ("source", "source-off") if all else ("source",)
    out = []
    with self._reading():
        rows = self.conn.execute(f"SELECT id, path, kind FROM roots WHERE kind IN ({','.join('?' * len(kinds))}) "
                                 "ORDER BY id", kinds).fetchall()
        for i, p, k in rows:
            held = 0
            if counts and p:
                prefix = SOURCE_KEY + path_key(os.path.abspath(p)).rstrip("/") + "/"
                held = self.conn.execute(f"SELECT COUNT(DISTINCT p.item_id) FROM pairings p WHERE p.content_key >= ? "
                                         f"AND p.content_key < ? AND NOT {_VERSION_ROW} AND NOT {_MOVED_ROW}",
                                         (prefix, prefix[:-1] + "0")).fetchone()[0]
            out.append({"id": i, "path": p, "on": k == "source", "items": held})
    return out


def _store_stop_source(self, root_id):
    """*Stop reading* a folder: its row kept as 'source-off' (adding it again turns it back on); its items, their copies
    and their records stay, and nothing on disk moves (T6: a gone folder's *Stop reading it*). -> the Change (T6: Undo
    reads it again, by the value check — `_undo_roots`), or None when it wasn't being read."""
    with self._command("stop_source") as cmd:
        if not self.conn.execute("UPDATE roots SET kind = 'source-off' WHERE id = ? AND kind = 'source'",
                                 (root_id,)).rowcount:
            return None
        self._copy_dirty()
        change = self._change(cmd, "stop_source")
        change.roots = [(root_id, "source", "source-off")]
        return change


def _folder_prefix(path):
    """A folder's origin-key range: its prefix (`/`-ended: `...Show` never holds `...Show S2`) and the key just past
    every key under it (`0` follows `/`) — a key-range read of `pairings`."""
    prefix = path_key(os.path.abspath(path)).rstrip("/") + "/"
    return SOURCE_KEY + prefix, SOURCE_KEY + prefix[:-1] + "0"


_LIVE_ORIGIN = f"{_ORIGIN_ROW} AND NOT {_VERSION_ROW} AND NOT {_MOVED_ROW}"


def _store_join_moved(self, root_id, folder):
    """T6, *Find its new folder...*: the GONE source `root_id`'s originals found again under `folder` (a look attached
    them there: the same items) — each live origin under its folder (no version, no mark) whose item has a live origin
    under `folder` holding the same bytes (sha256; a video's own origin: the same `video_key`) is marked `moved_to`
    that one (D5's mark, `mark_moved`'s rule; MV-A5: never by its name alone), in ONE write, bookkeeping the copy
    carries. An original still on disk is left (a copy, not a move; stat'ed outside the write lock). Nothing else
    moves: an episode not found there keeps its copy, its place and its record. -> how many originals were marked."""
    with self._reading():
        row = self.conn.execute("SELECT path FROM roots WHERE id = ?", (root_id,)).fetchone()
    if row is None or not row[0] or not isinstance(folder, str) or not folder.strip():
        return 0
    old_lo, old_hi = _folder_prefix(row[0])
    new_lo, new_hi = _folder_prefix(folder)
    if old_lo == new_lo:
        return 0
    sql = ("SELECT p.content_key, p.item_id, json_extract(p.pairing, '$.origin'), json_extract(p.pairing, "
           "'$.sha256'), json_extract(p.pairing, '$.video_key') FROM pairings p WHERE p.content_key >= ? AND "
           f"p.content_key < ? AND json_valid(p.pairing) AND {_LIVE_ORIGIN} ORDER BY p.content_key")
    # (in key order: of two copies with the same bytes in the folder picked, the mark names the first, every time)
    with self._reading():
        olds = self.conn.execute(sql, (old_lo, old_hi)).fetchall()
        news = self.conn.execute(sql, (new_lo, new_hi)).fetchall()
    found = {}
    for key, item_id, _origin, sha, vkey in news:
        if not old_lo <= key < old_hi:                # (a folder picked above the old one holds its old origins too)
            found.setdefault(item_id, []).append((key, sha, vkey))
    joins = []
    for key, item_id, origin, sha, vkey in olds:
        match = next((k for k, s, v in found.get(item_id, ())
                      if (sha and s == sha) or (not sha and vkey and v == vkey)), None)
        if match is None or not isinstance(origin, str) or os.path.lexists(origin):
            continue
        joins.append((item_id, match, key[len(SOURCE_KEY):]))
    if not joins:
        return 0
    with self._writing():
        for item_id, match, old in joins:
            self._mark_moved(item_id, match, [old])
        self._copy_dirty()
    return len(joins)


def _store_source_detail(self, root_ids):
    """T6, a gone folder's *Needs you* card: {root_id: {"shows": [the titles it holds, most episodes first],
    "finished": every one of its episodes Finished (*Stop reading it* first), "found_in": [the folders being read that
    hold its episodes now, in the order added — a look attached them there: *Find its new folder...* on one joins
    them]}}, of the episodes it held: its origins, live or marked moved (a look that joined them by itself leaves the
    card its show and their new place). Read-only."""
    out = {}
    with self._reading():
        paths = dict(self.conn.execute("SELECT id, path FROM roots WHERE kind IN ('source', 'source-off')").fetchall())
        reading = [(i, p, _folder_prefix(p)[0]) for i, p in self.conn.execute(
            "SELECT id, path FROM roots WHERE kind = 'source' ORDER BY id") if p]
        for root_id in root_ids:
            if not paths.get(root_id):
                continue
            lo, hi = _folder_prefix(paths[root_id])
            items = _dumps(sorted({i for (i,) in self.conn.execute(      # its moved ones too: a look that joined
                f"SELECT p.item_id FROM pairings p WHERE p.content_key >= ? AND p.content_key < ? AND {_ORIGIN_ROW} "
                f"AND NOT {_VERSION_ROW}", (lo, hi))}))              # them by itself leaves the card its show
            titles, tiers = {}, set()
            for tier, title in self.conn.execute(
                    "SELECT i.tier, COALESCE(w.title, i.title, '') FROM items i LEFT JOIN works w ON w.id = i.work_id "
                    "WHERE i.id IN (SELECT value FROM json_each(?))", (items,)):
                tiers.add(tier)
                if title:
                    titles[title] = titles.get(title, 0) + 1
            elsewhere = set()
            for (key,) in self.conn.execute(
                    f"SELECT p.content_key FROM pairings p WHERE p.item_id IN (SELECT value FROM json_each(?)) AND "
                    f"{_LIVE_ORIGIN} AND NOT (p.content_key >= ? AND p.content_key < ?)", (items, lo, hi)):
                held = [(len(k), n) for n, (i, _p, k) in enumerate(reading) if i != root_id and key.startswith(k)]
                if held:
                    elsewhere.add(max(held)[1])            # the innermost folder being read that holds it
            out[root_id] = {"shows": sorted(titles, key=lambda t: (-titles[t], t)),
                            "finished": bool(tiers) and tiers == {"graduated"},
                            "found_in": [reading[n][1] for n in sorted(elsewhere)]}
    return out


def _store_origins(self, items=None):
    """{path_key(origin): Origin(item_id, root, origin, size, mtime_ns, sha256, rel_path, availability, paired_at,
    version, video_path, video_size, video_key, declined, thin, moved_to, chapter)} for every origin recorded (`version`:
    another version of its item's episode, LM1b — a look knows its file, no reader takes it; `declined` / `thin`: a
    version the switch passes over while its file is as judged, LM3 `sources.passed_over`; `moved_to`: D5's mark, the
    path key its original moved to; `chapter`: a book's part's place, its JSON text — Hon), in any tier (a finished item
    is never taken in again): one read per look — the item's
    availability with it, so a look finds the copies gone (item 8a) with no stat of its own. The records' fields are read by SQLite
    (F13: decoding every record in Python held the interpreter 0.25 s at 20k, stretching a window's save meanwhile); a
    record that isn't a JSON object reads as one with no fields. `items` (LM3, A10): those items' origins only — a
    look's own after it switched a book."""
    field = lambda name: (f"CASE WHEN json_valid(p.pairing) THEN CASE WHEN json_type(p.pairing) = 'object' THEN "  # noqa
                          f"json_extract(p.pairing, '$.{name}') END END")
    with self._reading():
        rows = self.conn.execute(
            f"SELECT substr(p.content_key, {len(SOURCE_KEY) + 1}), p.item_id, {field('root')}, {field('origin')}, "
            f"{field('size')}, {field('mtime_ns')}, {field('sha256')}, i.rel_path, i.availability, p.paired_at, "
            f"{_VERSION_ROW}, {field('video_path')}, {field('video_size')}, {field('video_key')}, "
            f"{field('declined')}, {field('thin')}, {field('moved_to')}, {field('chapter')} FROM pairings p "
            f"JOIN items i ON i.id = p.item_id WHERE {_ORIGIN_ROW}"
            + ("" if items is None else " AND p.item_id IN (SELECT value FROM json_each(?))")
            + " ORDER BY p.content_key", () if items is None else (_dumps(sorted(set(items))),)).fetchall()
    return {r[0]: Origin._make(r[1:]) for r in rows}         # in key order (a look finds a folder's by its prefix)


def _store_excluded(self, root_ids=None):
    """{path_key(origin): {"size", "sha256", "video_key"?}} of the origins Remove keeps out (`root_ids`: only those
    sources'); a look checks a new file's path, bytes and video against them (S6; `take_in` checks them again)."""
    sql, params = "SELECT pattern, note FROM exclusions WHERE kind = 'removed'", []
    if root_ids is not None:
        root_ids = list(root_ids)
        if not root_ids:
            return {}
        sql += f" AND root_id IN ({','.join('?' * len(root_ids))})"
        params = root_ids
    with self._reading():
        return {pattern: (_json_dict(note) or {}) for pattern, note in self.conn.execute(sql, params).fetchall()}


def _store_items_of_size(self, sizes):
    """{size: [(item_id, rel_path, mtime_ns, content_sha256)]} of the available items of these sizes: K1b's check (b),
    an item whose copy may hold the same bytes (size first, then the bytes). The hash is the one kept for the file as
    its row records it (A4K-7), None where none is kept yet."""
    sizes = [s for s in dict.fromkeys(sizes) if isinstance(s, int)]
    sha = "content_sha256" if self._hash_column() else "NULL"
    out = {}
    with self._reading():
        for chunk in _chunks(sizes, 500):
            for size, item_id, rel, mtime_ns, kept in self.conn.execute(
                    f"SELECT size, id, rel_path, mtime_ns, {sha} FROM items WHERE availability = 'available' AND "
                    f"size IN ({','.join('?' * len(chunk))}) ORDER BY id", chunk):
                out.setdefault(size, []).append((item_id, rel, mtime_ns, kept))
    return out


def _store_keep_hashes(self, rows):
    """A4K-7: copies' content hashes a look worked out for check (b) (`rows`: [(item_id, size, mtime_ns, sha256)],
    the size and time the file had when it was read), kept on their items in ONE write — each only while its row still
    records that size and time (else the hash is of a file the row no longer names). A cache: no command, no version,
    never on Undo or in the copy. -> how many were kept (0 before the store has the column)."""
    rows = [(sha, item_id, size, mtime_ns) for item_id, size, mtime_ns, sha in rows if sha]
    if not rows or not self._hash_column():
        return 0
    with self._writing():
        before = self.conn.total_changes
        self.conn.executemany("UPDATE items SET content_sha256 = ? WHERE id = ? AND size = ? AND mtime_ns = ? AND "
                              "availability = 'available'", rows)
        return self.conn.total_changes - before


def _store_keep_hash(self, item_id, fp, sha):
    """A4K-7, inside `take_in`: a new copy's hash (`sha`: the bytes the look wrote) on its item, the row's file as
    `_prepare` read it (`fp`: size, time, availability)."""
    if sha and fp[2] == "available" and self._hash_column():
        self.conn.execute("UPDATE items SET content_sha256 = ? WHERE id = ? AND size = ? AND mtime_ns = ?",
                          (sha, item_id, fp[0], fp[1]))


def _store_origin_videos(self):
    """{video_key: the lowest live item id} of the origins' records (K1b's check (a), its origin half; a 'waiting'
    item left out): one read, which a look keeps up to date as it takes files in (`item_of_video_key(...,
    origins=)`; only a look writes an origin's video)."""
    found = {}
    with self._reading():
        for vkey, item_id in self.conn.execute(
                f"SELECT json_extract(p.pairing, '$.video_key'), p.item_id FROM pairings p JOIN items i ON "
                f"i.id = p.item_id WHERE {_ORIGIN_ROW} AND i.availability != 'waiting' AND json_valid(p.pairing) AND "
                f"NOT {_VERSION_ROW}"):
            if isinstance(vkey, str) and vkey and (vkey not in found or item_id < found[vkey]):
                found[vkey] = item_id
    return found


def _store_item_of_video_key(self, key, origins=None):
    """K1b's check (a): the live item whose record holds this video — hato's `content_key`, or an origin's
    `video_key` — the lowest id when several do, else None. A 'waiting' item (K5) is left out, so a video-only show's
    gap is filled by `take_in` from the copy.

    Asked once per video a look finds (review H17): the answers come from one read of every record's video, kept
    while nothing is written — stamped with this connection's changes and SQLite's `data_version` (another
    connection's commit, read before the records) — and never kept inside a write (one rolled back would leave it
    wrong). `origins` (a look's `origin_videos()`, kept up to date by it): the origin half from it, hato's from its
    row (a key lookup, so a drop paired meanwhile counts) — no read of every record per batch."""
    if not isinstance(key, str) or not key or key.startswith(SOURCE_KEY):
        return None
    if origins is not None:
        with self._reading():
            row = self.conn.execute("SELECT MIN(p.item_id) FROM pairings p JOIN items i ON i.id = p.item_id WHERE "
                                    "p.content_key = ? AND i.availability != 'waiting'", (key,)).fetchone()
        ids = [i for i in ((row[0] if row else None), origins.get(key)) if i is not None]
        return min(ids) if ids else None
    stamp = None if self._depth else (self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0])
    with self._reading():
        held = getattr(self, "_video_items", None)
        if stamp is None or held is None or held[0] != stamp:
            found = {}
            for vkey, item_id in self.conn.execute(
                    f"SELECT CASE WHEN {_ORIGIN_ROW} THEN json_extract(p.pairing, '$.video_key') ELSE p.content_key "
                    f"END, p.item_id FROM pairings p JOIN items i ON i.id = p.item_id WHERE i.availability != "
                    f"'waiting' AND (NOT {_ORIGIN_ROW} OR json_valid(p.pairing)) AND NOT {_VERSION_ROW}"):
                if isinstance(vkey, str) and vkey and (vkey not in found or item_id < found[vkey]):
                    found[vkey] = item_id
            held = (stamp, found)
            if stamp is not None:
                self._video_items = held
    return held[1].get(key)


def _store_update_origin(self, origin, size, mtime_ns, sha256, video=None):
    """A changed original re-copied (S5, K1b): only its row's `size`, `mtime_ns` and `sha256`, bookkeeping the copy
    carries — `paired_at` and every other key kept, so Connect's pairing version never moves (B1). `video` ({video_path,
    video_size, video_key}, LM1b: a video found for it later, A19, or its video renamed, A20): recorded on the row too,
    the one change here Connect reads (its pairing moves to that video; no new item). -> True when the row changed."""
    return bool(self.update_origins([(origin, size, mtime_ns, sha256, video)]))


def _store_update_origins(self, changes):
    """`update_origin` for many rows in ONE write (`changes`: [(origin, size, mtime_ns, sha256, video)]): a look that
    finds the videos of hundreds of known subtitles at once (an existing library's first look with LM1b) commits once
    per call, never once a row. -> the origins whose row changed."""
    done = []
    with self._writing():
        for origin, size, mtime_ns, sha256, video in changes:
            key = origin_key(origin)
            row = self.conn.execute("SELECT pairing FROM pairings WHERE content_key = ?", (key,)).fetchone()
            if row is None:
                continue
            record = _json_dict(row[0]) or {}
            new = dict(record, **{k: v for k, v in (("size", size), ("mtime_ns", mtime_ns), ("sha256", sha256))
                                  if v is not None})      # (None: as recorded — a video recorded alone)
            new.update({k: v for k, v in (video or {}).items() if k in ("video_path", "video_size", "video_key") and v})
            if new == record:
                continue
            self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                              (json.dumps(new, sort_keys=True, ensure_ascii=False), key))
            done.append(origin)
        if done:
            self._copy_dirty()
    return done


def _store_copies_back(self, back, records=None):
    """Item 8a: the copies a look wrote back into their own place (`back`: [(item_id, rel, size, mtime_ns)] — the
    copy's rel and its stats as written). Each item still at that rel and still 'missing' is available again in place,
    as the disk sync's *came back* is — its id, place, words, cards and records kept, its size and time the new copy's
    — in ONE command the window hears like any availability change (no event: nothing moved). A row removed, moved or
    back meanwhile is left as it is. `records` ({item_id: (origin, size, mtime_ns, sha256)}): the originals whose
    stats moved, rewritten for the items made available, in the same command (`update_origin`'s rule; H4). -> (the ids
    made available, the rels no item holds: the caller's to trash, never left in Library untracked — B2)."""
    back = [b for b in back if b[1]]
    if not back:
        return [], []
    with self._command("copy_back", SOURCE_PRODUCER) as cmd:
        done, tiers = [], set()
        for item_id, rel, size, mtime_ns in back:
            row = self.conn.execute("SELECT tier FROM items WHERE id = ? AND rel_key = ? AND availability = 'missing'",
                                    (item_id, path_key(rel))).fetchone()
            if row is None:
                continue
            self.conn.execute("UPDATE items SET availability = 'available', size = ?, mtime_ns = ? WHERE id = ?",
                              (size, mtime_ns, item_id))
            done.append(item_id)
            tiers.add(row[0])
        if done:
            cmd.feed(done)
            cmd.touch(tiers, availability=True)
        for item_id in done:
            if item_id in (records or {}):
                self.update_origin(*records[item_id])     # joins this command (the write lock is re-entrant)
        unused = [rel for _i, rel, _s, _m in back if not self.conn.execute(
            "SELECT 1 FROM items WHERE rel_key = ?", (path_key(rel),)).fetchone()]
    return done, unused


def _store_exclude_origins(self, pairs, now):
    """Inside `remove`: an exclusion per origin of the removed items (`pairs`: {item_id: [[content_key, the record's
    JSON text, paired_at]]}, as `remove` read them) — its path key, `kind` 'removed', the note {size, sha256,
    video_key?, show?, episode?} (S6: the same bytes or video found elsewhere stay out too, and K1b keeps a v2 of that
    show's episode out). -> the exclusion ids written."""
    rows = []
    for records in pairs.values():
        for key, text, _at in records:
            if not key.startswith(SOURCE_KEY):
                continue
            record = _json_dict(text) or {}
            note = {"size": record.get("size"), "sha256": record.get("sha256")}
            if record.get("video_key"):
                note["video_key"] = record["video_key"]
            show = record.get("show") if isinstance(record.get("show"), dict) else {}
            if show.get("title") and isinstance(record.get("episode"), (int, float)):
                note["show"], note["episode"] = show["title"], record["episode"]    # its re-release (v2) stays out
            rows.append((record.get("root"), key[len(SOURCE_KEY):], "removed", now, _dumps(note)))
    if not rows:
        return []
    first = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM exclusions").fetchone()[0] + 1
    self.conn.executemany("INSERT INTO exclusions (root_id, pattern, kind, created_at, note) VALUES (?, ?, ?, ?, ?)",
                          rows)
    return list(range(first, first + len(rows)))


def _store_let_origins_back(self, keys):
    """Inside `restore` (Put back, an Undo of a Remove): the item's origins are its own again — their exclusions go."""
    patterns = [k[len(SOURCE_KEY):] for k in keys if k.startswith(SOURCE_KEY)]
    for chunk in _chunks(patterns, 500):
        self.conn.execute(f"DELETE FROM exclusions WHERE kind = 'removed' AND pattern IN ({','.join('?' * len(chunk))})",
                          chunk)


# --- K2 (alpha 4, Mattias's note 6): the Removed list — his own Removes, to put back ------------------------------- #
REMOVED_DAYS = TRASH_DAYS        # a removed file's days in the trash (`path_utils`' purge: one number)


def _store_removed_rows(self):
    """(One read transaction.) The trash rows of his own Removes not put back -> [(trash_id, rel, trashed_path,
    removed_at, title, work_id, roots, keys)], newest first (`keys`: its originals' keys, as its exclusions hold
    them). His own: `why` None or "remove" (`remove`); a row written before `why` was kept is his when it left a
    `removed` exclusion for an original (only his Remove does: a book's part given up and an undone add leave none),
    else — a file from no folder read — by its removal's log entry while one is kept (`placement_log`, written while a
    reader is registered: removed by "user"), and never a row whose original lies under a folder he skipped (*Read
    again* brings those back). A row whose place is an item again (added again since) is left out: Put back would
    refuse it."""
    out = []
    with self._reading():
        rows = self.conn.execute("SELECT id, item_id, rel_path, trashed_path, removed_at, item_state FROM trash "
                                 "WHERE restored_at IS NULL ORDER BY id DESC").fetchall()
        if not rows:
            return out
        works = dict(self.conn.execute("SELECT id, title FROM works"))
        skips = [r[0] for r in self.conn.execute("SELECT pattern FROM exclusions WHERE kind = ?", (FOLDER_SKIP,))]
        by = dict(self.conn.execute("SELECT item_id, by FROM placement_log WHERE kind = 'removed' ORDER BY id"))
        excluded = {r[0] for r in self.conn.execute("SELECT pattern FROM exclusions WHERE kind = 'removed'")}
        for trash_id, item_id, rel, trashed, removed_at, raw in rows:
            state = _json_dict(raw) or {}
            keys = [k[len(SOURCE_KEY):] for k, _t, _a in state.get("pairings") or ()
                    if isinstance(k, str) and k.startswith(SOURCE_KEY)]
            if "why" in state:
                if state["why"] not in (None, "remove"):
                    continue
            elif keys and not any(k in excluded for k in keys):
                continue                                   # written before `why`: a book's part, an undone add
            elif not keys and by.get(item_id, "user") != "user":
                continue
            if any(_under(k, f) for k in keys for f in skips):
                continue
            if self.conn.execute("SELECT 1 FROM items WHERE rel_key = ?", (path_key(rel),)).fetchone():
                continue
            cols = state.get("columns") if isinstance(state.get("columns"), dict) else {}
            work = cols.get("work_id")
            title = works.get(work) or cols.get("title") or rel.rsplit("/", 1)[-1]
            roots = []
            for k, text, _at in state.get("pairings") or ():
                if isinstance(k, str) and k.startswith(SOURCE_KEY):
                    root = (_json_dict(text) or {}).get("root")
                    if root is not None and root not in roots:
                        roots.append(root)
            out.append((trash_id, rel, trashed, removed_at, title, work, roots, keys))
    return out


def _store_removed(self, now=None):
    """The Removed list (K2, alpha 4, Mattias's note 6): his own Removes not put back (`_removed_rows`), one entry per
    Remove, newest first -> [{"trash_ids", "title", "titles", "removed_at", "days_left", "count",
    "can_return", "roots"}]; a Remove of several titles is ONE entry (alpha 5, Mado: a picks Remove of 120 titles was
    120 lines) — `title` None, `titles` how many, its files', days' and folders' summed. `days_left`: the days before the purge takes the FIRST of its files still in the trash (each file's own
    clock, which the Remove restarted; 0 … REMOVED_DAYS), None when none is there; `can_return`: a file still in the
    trash, or an original in a folder Surasura still reads (`roots`: its originals' folders' ids). An entry that can't
    come back (no file left, no original read) is left out: Put back would bring nothing back. One read transaction; one
    stat per trashed file."""
    now = time.time() if now is None else now
    groups, order = {}, []
    rows = self._removed_rows()
    live = {i for i, _path in self._read_sources()} if rows else set()
    for trash_id, _rel, trashed, removed_at, title, work, roots, _keys in rows:
        key = (removed_at, work if work is not None else ("item", trash_id))
        entry = groups.get(key)
        if entry is None:
            entry = groups[key] = {"trash_ids": [], "title": title, "titles": 1, "removed_at": removed_at,
                                   "days_left": None, "count": 0, "can_return": False, "roots": []}
            order.append(key)
        entry["trash_ids"].append(trash_id)
        entry["count"] += 1
        if trashed:
            st = _stat(os.path.join(self.data_dir, *trashed.split("/")))
            if st is not None:
                left = min(REMOVED_DAYS, max(0, REMOVED_DAYS - int((now - st.st_mtime) // 86400)))
                entry["days_left"] = left if entry["days_left"] is None else min(entry["days_left"], left)
                entry["can_return"] = True
        if any(r in live for r in roots):
            entry["can_return"] = True                      # its original in a folder still read
        entry["roots"] += [r for r in roots if r not in entry["roots"]]
    out, removes = [], {}
    for k in order:
        entry = groups[k]
        if not entry["can_return"]:
            continue
        one = removes.get(entry["removed_at"])              # the same Remove's other titles: one entry
        if one is None:
            removes[entry["removed_at"]] = entry
            out.append(entry)
            continue
        days = [d for d in (one["days_left"], entry["days_left"]) if d is not None]
        one.update(title=None, titles=one["titles"] + 1, count=one["count"] + entry["count"],
                   days_left=min(days) if days else None)
        one["trash_ids"] += entry["trash_ids"]
        one["roots"] += [r for r in entry["roots"] if r not in one["roots"]]
    for entry in out:
        entry["trash_ids"].sort()                           # Put back's order: as they were removed
    return out


# --- A5K-2: a library folder emptied under its record (Sonic ✅ 2026-10-28) ----------------------------------------- #
# The record lives in `%LOCALAPPDATA%`, keyed by the data folder's path (`library_db_path`): deleting Surasura's folder
# and unzipping it again in the same place opens the old record, and the looks put every copy back from its original
# (item 8a), its Removes' exclusions, tiers and Finished with them — the K1 card never sees a file gone. Noted ONCE, by
# the run's first look before it puts anything back; *Needs you* then asks *Start fresh* · *Keep my old library*.
FOLDER_EMPTIED = "folder_emptied"


def _store_note_emptied(self):
    """The library folder holds none of this record's files — not one top folder its items' copies live in (`Library/`,
    a 2.x tier's folder) holds a file, nor is a loose one there (a waiting video, which has no file, never counts): noted
    in meta `folder_emptied` {"at", "files"} -> the files counted, or None (files there, an empty record). Asked at each
    run's first look: a note stays while the folder fills again (the card waits for its answer), and an emptying found
    later is a new note — a new `at`, so a card asked again even after *Keep my old library*. A bookkeeping write (no
    version moves; never in the JSON copy); *Start fresh*'s fresh meta drops it."""
    with self._reading():
        rels = [r[0] for r in self.conn.execute("SELECT rel_path FROM items WHERE availability != 'waiting'")]
    tops = {_strip(str(rel)).split("/", 1)[0] for rel in rels if rel}
    if not tops or any(_holds_a_file(os.path.join(self.data_dir, top)) for top in tops):
        return None
    self.bookkeeping({FOLDER_EMPTIED: _dumps({"at": _now(), "files": len(rels)})})
    return len(rels)


def _holds_a_file(path):
    """Is `path` a file, or a folder with a file anywhere under it (an empty `Library/` made again holds none)? The
    walk stops at the first file. On a doubt it holds one — a folder that can't be read, a link (a drive behind it
    may only be unplugged): never asked to start fresh for an offline drive."""
    if os.path.islink(path) or os.path.isfile(path):
        return True
    if not os.path.lexists(path):
        return False

    def unreadable(error):
        raise error
    try:
        for folder, dirs, files in os.walk(path, onerror=unreadable):
            if files or any(os.path.islink(os.path.join(folder, d)) for d in dirs):
                return True
    except OSError:
        return True
    return False


def _store_emptied(self):
    """`note_emptied`'s note {"at", "files"} while it is there (until a fresh library), else None. One read."""
    row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (FOLDER_EMPTIED,)).fetchone()
    return (_json_dict(row[0]) or None) if row else None


def _store_removed_under(self, root_id):
    """Settings' *Bring back N removed* on a folder's line (Mattias's note 6: read again, it brings nothing back — a
    Remove keeps its files out for good): the trash ids of his Removes whose own original lies in that folder ->
    [trash_id], oldest first — never another folder's file removed with them. Their Put back (`Writer.restore`) lets
    the originals back in. No file is looked at."""
    return sorted(r[0] for r in self._removed_rows() if root_id in r[6])


def _store_removed_for(self, keys):
    """Alpha 4 (Mattias: a copy of a book he removed, in another folder, was kept out and nothing said): of these
    removed originals' keys (`sources.notes`' `kept_out`: the ones a new file's bytes or video matched), those still
    out -> {key: [the trash ids of his Removes that keep it out]}. *Bring back* is their Put back (`Writer.restore`):
    the items come back, and the copies are theirs again. A key put back since is left out (nothing keeps it out)."""
    want = set(keys)
    out = {}
    if not want:
        return out
    for row in self._removed_rows():
        for k in want.intersection(row[7]):
            out.setdefault(k, []).append(row[0])
    return {k: sorted(v) for k, v in out.items()}


# --- K6: a folder no look reads (*Never read this folder*) ------------------------------------------------------- #
# A skipped folder is one `exclusions` row: kind FOLDER_SKIP, `pattern` its path key, `root_id` the innermost source
# being read that holds it, `note` {"path": the folder as written}. Its skip removes the items whose every origin lies
# under it as Remove does (the store's trash; each origin a 'removed' row, its note marked {"folder": <row id>}), in the
# same command — Undo puts them back and drops the row; *Read again* drops the row and its marked 'removed' rows, so
# the next look takes its files in as new (SRC-2), never twice (SRC-7). `sources._Look` never lists a skipped folder.
FOLDER_SKIP = "folder"
SKIP_NOT_FOLDER = "That isn't a folder."
SKIP_IS_SOURCE = "That's a folder Surasura reads: to leave all of it out, stop reading it."
SKIP_OUTSIDE = "That folder isn't inside a folder Surasura reads."
SKIP_HOLDS_SOURCE = "That folder holds a folder Surasura reads: stop reading that one first."
SKIP_ALREADY = "That folder is skipped already."


def _under(key, folder):
    """Is the path key `key` inside the folder key `folder` (never the folder itself)?"""
    return key.startswith(folder.rstrip("/") + "/")


def skip_refusal(path, sources, skipped=()):
    """Why the folder `path` can't be skipped (K6) -> (reason or None, the id of the innermost source holding it). Pure:
    `sources` [(id, path)] of the folders being read; `skipped` the keys of the folders skipped already. Refused: no
    path; a source folder itself (that's *Stop reading*); one inside no source being read; one holding a source being
    read (its look would read nothing); one skipped already, or inside one."""
    if not isinstance(path, str) or not path.strip():
        return SKIP_NOT_FOLDER, None
    key = path_key(folder_path(path)).rstrip("/")
    keys = [(i, path_key(folder_path(p)).rstrip("/")) for i, p in sources]
    if any(k == key for _i, k in keys):
        return SKIP_IS_SOURCE, None
    held = [(len(k), i) for i, k in keys if _under(key, k)]
    if not held:
        return SKIP_OUTSIDE, None
    if any(_under(k, key) for _i, k in keys):
        return SKIP_HOLDS_SOURCE, None
    if any(s == key or _under(key, s) for s in skipped):
        return SKIP_ALREADY, None
    return None, max(held, key=lambda h: h[0])[1]


def _store_read_sources(self):
    """[(id, path)] of the sources being read (their rows alone)."""
    return [(s["id"], s["path"]) for s in self.sources(counts=False)]


def _store_skipped_folders(self):
    """[{id, root, key, path}] of the folders no look reads, in the order skipped (K6): Settings' list, the look's
    skip."""
    with self._reading():
        rows = self.conn.execute("SELECT id, root_id, pattern, note FROM exclusions WHERE kind = ? ORDER BY id",
                                 (FOLDER_SKIP,)).fetchall()
    return [{"id": i, "root": r, "key": k, "path": (_json_dict(n) or {}).get("path") or k} for i, r, k, n in rows]


def _store_skip_refused(self, path):
    """Why `path` can't be skipped (K6, `skip_refusal`'s plain words), or None. A read."""
    return skip_refusal(path, self._read_sources(), [f["key"] for f in self.skipped_folders()])[0]


def _store_items_under(self, path):
    """K6: the live items whose every origin lies inside the folder `path`, in id order — an item with an origin
    elsewhere, or a record of another producer (hato's), stays. A range read on the origins' keys."""
    lo = SOURCE_KEY + path_key(folder_path(path)).rstrip("/") + "/"
    hi = lo[:-1] + "0"                                   # "/" + 1: every key inside the folder, none beside it
    with self._reading():
        inside = sorted({r[0] for r in self.conn.execute(
            f"SELECT item_id FROM pairings p WHERE content_key >= ? AND content_key < ? AND item_id IS NOT NULL AND "
            f"NOT {_VERSION_ROW}", (lo, hi))})               # LM1b: a version's place is never the item's
        out = []
        for chunk in _chunks(inside, 500):
            for item_id, every, there in self.conn.execute(
                    f"SELECT item_id, COUNT(*), SUM(content_key >= ? AND content_key < ?) FROM pairings p WHERE item_id "
                    f"IN ({','.join('?' * len(chunk))}) AND NOT {_VERSION_ROW} GROUP BY item_id ORDER BY item_id",
                    [lo, hi] + chunk):
                if every == there:
                    out.append(item_id)
    return out


def _store_skip_choices(self, item_ids, own=False):
    """⋯'s *Never read this folder* (K6): for the first of these items' origins inside a source being read, its folder
    and each folder above it up to (never) the innermost such source folder, deepest first — each one `skip_refusal`
    accepts -> [path]; [] when none of them came from a source being read. `own` (the sort screen's *Ignore*, Mado-O):
    from the folder holding ALL these items' originals, and only folders whose files are all theirs — never one that
    also holds another item's original; [] when one of them came from no folder."""
    ids = [i for i in item_ids if isinstance(i, int)][:500]
    if not ids:
        return []
    with self._reading():
        rows = self.conn.execute(
            f"SELECT p.item_id, p.pairing FROM pairings p WHERE {_ORIGIN_ROW} AND NOT {_VERSION_ROW} AND p.item_id IN "
            f"({','.join('?' * len(ids))}) "
            f"ORDER BY p.content_key", ids).fetchall()
    starts, came = [], set()
    for item_id, t in rows:
        origin = (_json_dict(t) or {}).get("origin")
        if isinstance(origin, str) and origin:
            starts.append(folder_path(os.path.dirname(_EPUB_PART.sub(".epub", origin))))
            came.add(item_id)
    if own:
        if not starts or came != set(ids):
            return []                                   # (one of them from no folder: no folder holds them all)
        try:
            starts = [folder_path(os.path.commonpath(starts))]
        except ValueError:                              # (on two drives)
            return []
    sources = self._read_sources()
    skipped = [f["key"] for f in self.skipped_folders()]
    keys = [path_key(folder_path(p)).rstrip("/") for _i, p in sources]
    for folder in starts:
        key = path_key(folder).rstrip("/")
        held = [k for k in keys if k == key or _under(key, k)]
        if not held:
            continue
        top, out = max(held, key=len), []
        while _under(path_key(folder).rstrip("/"), top):
            if own and self._holds_others(folder, ids):
                break                                   # (a folder above it holds those others too)
            if skip_refusal(folder, sources, skipped)[0] is None:
                out.append(folder)
            up = os.path.dirname(folder)
            if up == folder:
                break
            folder = up
        return out
    return []


def _store_holds_others(self, folder, ids):
    """Whether an item outside `ids` has a live original under `folder` (`skip_choices(own=True)`)."""
    prefix = origin_key(folder).rstrip("/") + "/"
    like = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    with self._reading():
        row = self.conn.execute(
            f"SELECT 1 FROM pairings p JOIN items i ON i.id = p.item_id WHERE {_ORIGIN_ROW} AND NOT {_VERSION_ROW} "
            f"AND p.content_key LIKE ? ESCAPE '!' AND p.item_id NOT IN ({','.join('?' * len(ids))}) LIMIT 1",
            [like] + list(ids)).fetchone()
    return row is not None


def _store_skip_folder(self, path, trashed_paths=None):
    """*Never read this folder* (K6), ONE command: the folder's row, then the items whose every origin lies under it
    removed as `remove` does (`trashed_paths` {id: rel}: where the caller's file work sent their copies — the window's
    writer trashes them under this write lock first; files in his own folders are never touched) -> the change, kind
    'remove' (Undo puts the items back and drops the row: `undo`), `folder` its row's id. Refused (`NotASource`, its
    reason) before anything is written."""
    with self._command("remove") as cmd:
        reason, root = skip_refusal(path, self._read_sources(), [f["key"] for f in self.skipped_folders()])
        if reason:
            raise NotASource(reason)
        norm = folder_path(path)
        folder = self.conn.execute("INSERT INTO exclusions (root_id, pattern, kind, created_at, note) VALUES "
                                   "(?, ?, ?, ?, ?)", (root, path_key(norm).rstrip("/"), FOLDER_SKIP, _now(),
                                                       _dumps({"path": norm}))).lastrowid
        self._skips_moved()
        ids = self.items_under(norm)
        change = (self.remove(ids, trashed_paths, why="skip") if ids else None) or self._change(cmd, "remove")
        for chunk in _chunks(list(getattr(change, "excluded", None) or ()), 500):
            self.conn.execute(f"UPDATE exclusions SET note = json_set(CASE WHEN json_valid(note) THEN note ELSE '{{}}' "
                              f"END, '$.folder', ?) WHERE id IN ({','.join('?' * len(chunk))})", [folder] + chunk)
        change.folder, change.folder_path = folder, norm
        return change


def _store_unskip(self, folder_id):
    """(Inside a write.) The folder row `folder_id` and the 'removed' rows its skip wrote go -> True when it was
    there."""
    if not self.conn.execute("DELETE FROM exclusions WHERE id = ? AND kind = ?", (folder_id, FOLDER_SKIP)).rowcount:
        return False
    self.conn.execute("DELETE FROM exclusions WHERE kind = 'removed' AND json_valid(note) AND "
                      "json_extract(note, '$.folder') = ?", (folder_id,))
    self._skips_moved()
    return True


def _store_skips_moved(self):
    """(Inside a write.) The skipped folders changed: the copy carries them (`copy_dirty`), and meta `folder_skips`
    moves, so a look reads them again (it reads no exclusion while that stays as its cache says)."""
    meta = self._meta()
    self._set_meta({"copy_dirty": int(meta.get("copy_dirty") or 0) + 1,
                    "folder_skips": int(meta.get("folder_skips") or 0) + 1})


def _store_read_folder_again(self, folder_id):
    """Settings' *Read again* (K6): the folder is read again — its row and the 'removed' rows its skip wrote go, so the
    next look takes its files in as new (shows never shown → New arrivals, SRC-2; never twice, SRC-7). Not on Undo.
    -> True when it was skipped."""
    with self._writing():
        return self._unskip(folder_id)


def _store_take_in(self, root_id, found, first=False, rules=None):
    """A look's files taken in, as ONE command per batch (the scan calls it per show, ≤ 200 files; an EPUB's parts all
    in one). Each copy is already on disk under `Library/` (the caller copied it outside the lock, as moves' drop does).

    `found`: [{origin (absolute), size, mtime_ns (the origin's), sha256 (the text's bytes), show (its title), rel (the
    copy, relative to the data folder, under `Library/`), copy_sha256? (A4K-7: the copy's bytes as the caller wrote
    them, kept on its new item), video_path?, video_size?, video_key?, episode? (K4's number),
    item_id? (K1b's checks (a) / (b): the item the origin belongs to; no copy, no `rel`), moved_from? (D5: with
    `item_id`, the path keys of that item's origins whose originals the look found gone: marked `moved_to` this one,
    when they are still its live records)}].

    Per file: an origin already recorded (by any source), or one Remove keeps out — its path, its bytes or its video
    (S6) — is skipped; an `item_id` gets the origin recorded and nothing else; a copy that is already an item is that
    item; else the item is added and placed. `first` (setup's own first scan, SRC-1): the end of Current, shows in name
    order, episodes in natural order (`ep2` before `ep10`), logged quiet like a back-fill — no placement event, so
    nothing is mined by itself (S1); a show read from inside a 2.x library's Goal folder at Goal's end (K8, `_tier_2x`).
    Later (SRC-2, S2, S3, S14; Decision 1, lean): it lands in New arrivals (in its show's run there, in order) and the
    placing rule for the source takes it on (D30: `source:<id>`, then `source`; `rules` None = settings.json's default,
    `source: after-show`): after-show puts a show with rows in Current in its run, before the first episode whose number
    (K4's, or hato's) or natural-order name is higher, else after the last; a show only in 6+ Months or Finished at the
    top of Current (Q4-9); a show never shown, or one still waiting, waits. With New arrivals off (`arrivals_on`; no
    rule runs): its show's run in Current, else the top of Current. Logged as `source`'s: the landing never explicit,
    the rule's move explicit (the user's own setting, D30).

    -> the change (kind 'take_in': never on the user's Undo, S6 — Remove takes an item out), with `added`, `attached`,
    `recorded` {origin (absolute): item_id}, `placed` {item_id: tier}, `skipped` {"known", "excluded", "gone":
    [origins]} and `unused` (the copies no item holds — a skipped file's, or a second file with the same bytes as one
    earlier in the batch, whose origin is recorded on that one's item (A5) — for the caller to send to the trash);
    None for nothing found. A copy outside the content
    folder raises ValueError, a source not being read `NotASource`, both before anything is written."""
    found = list(found or ())
    if not found:
        return None
    if rules is None:
        from app.settings_manager import placing_rules
        rules = placing_rules()
    rels = []
    for f in found:
        origin = f.get("origin")
        if not isinstance(origin, str) or not os.path.isabs(origin):
            raise ValueError(f"an origin must be an absolute path: {origin!r}")
        if f.get("item_id") is not None or f.get("version"):
            continue
        rel = library_rel(self.data_dir, str(f.get("rel") or ""))
        parts = rel.split("/") if rel else []
        if len(parts) < 2 or path_key(parts[0]) != path_key(CONTENT_FOLDER):
            raise ValueError(f"a copy outside the content folder: {f.get('rel')!r}")
        rels.append((rel, origin_key(origin)))
    known = set()                    # H19: a file recorded already is never read (its stat, its mark) to be skipped
    with self._reading():
        for chunk in _chunks(list({k for _r, k in rels}), 500):
            known.update(k for (k,) in self.conn.execute(f"SELECT content_key FROM pairings WHERE content_key IN "
                                                         f"({','.join('?' * len(chunk))})", chunk))
    rels = list(dict.fromkeys(rel for rel, k in rels if k not in known))
    prepared = dict(zip(rels, self._prepare(rels, None, "Source")))
    fold = lambda f: search_fold(str(f.get("show") or ""), self.language)                     # noqa: E731
    ep = lambda f: f.get("episode") if isinstance(f.get("episode"), (int, float)) else None    # noqa: E731
    order = sorted(found, key=lambda f: (bool(f.get("version")), fold(f), ep(f) is None, ep(f) or 0,
                                         _natural(os.path.basename(str(f.get("rel") or f["origin"])))))
    nested = self._depth > 0          # inside an outer write (P1): its rollback would leave the waiting videos' copy wrong
    with self._command("take_in", SOURCE_PRODUCER) as cmd:
        row = self.conn.execute("SELECT kind FROM roots WHERE id = ?", (root_id,)).fetchone()
        if row is None or row[0] != "source":
            raise NotASource("That folder isn't being read any more.")
        change = self._change(cmd, "take_in")
        change.attached, change.placed, change.recorded = [], {}, {}    # recorded: {origin: item_id}
        change.skipped = {"known": [], "excluded": [], "gone": []}
        change.versions = []         # LM1b: the items another version of whose episode was recorded
        out = {"patterns": set(), "sha256": set(), "video_key": set()}
        for pattern, note in self.conn.execute("SELECT pattern, note FROM exclusions WHERE kind = 'removed'"):
            note = _json_dict(note) or {}
            out["patterns"].add(pattern)
            for k in ("sha256", "video_key"):
                if note.get(k):
                    out[k].add(note[k])
        works, by_bytes, spare, taken = {}, {}, {}, {}
        episodes = {}                # {item_id: its episode number or None}: each show's read once a batch (`_in_run`)
        runs = {} if first else None  # {work: its rows in Current, in order}: setup's scan reads a show's run once
        gaps = self._waiting_videos() if any(_video_keys(f) for f in found) else None
        stamp, exact = (self.conn.execute("PRAGMA data_version").fetchone()[0], gaps is not None)
        gaps = {} if gaps is None else gaps
        for f in order:
            origin = os.path.abspath(f["origin"])
            key = origin_key(origin)
            if f.get("version"):
                self._take_version(cmd, change, root_id, origin, key, f, out)
                continue
            rel = None if f.get("item_id") is not None else library_rel(self.data_dir, str(f["rel"]))
            p = prepared.get(rel) if rel is not None else None
            # recorded already — by any source, or earlier in this batch (each record is written as it goes)
            if self.conn.execute("SELECT 1 FROM pairings WHERE content_key = ?", (key,)).fetchone():
                change.skipped["known"].append(origin)
                if rel is not None:
                    spare[rel] = path_key(rel)
                continue
            if rel is not None and p is None:        # recorded at the look, its record gone since: read it now
                p = prepared[rel] = self._prepare([rel], None, "Source")[0]
            if key[len(SOURCE_KEY):] in out["patterns"] or (f.get("sha256") and f["sha256"] in out["sha256"]) or \
                    any(k in out["video_key"] or k in out["patterns"] for k in _video_keys(f)):
                change.skipped["excluded"].append(origin)
                if p:
                    spare[p[1]] = p[2]
                continue
            record = _origin_record(root_id, origin, f)
            # an EPUB's part records its book's sha256 (K1b, K4): two parts of one book are never "the same bytes"
            same = None if _EPUB_PART.search(origin) else f.get("sha256")
            item_id = f.get("item_id")
            if item_id is None and not is_content_name(p[1]):  # H9: a video whose subtitle came earlier in this batch
                item_id = next((taken[k] for k in _video_keys(f) if k in taken), None)
            if item_id is None:
                held = self.conn.execute("SELECT id FROM items WHERE rel_key = ?", (p[2],)).fetchone()
                gap = next((gaps[k] for k in _video_keys(f) if k in gaps), None) if is_content_name(p[1]) else None
                other = gap is None and is_content_name(p[1]) and f.get("gap") in gaps.values()
                if other:
                    gap = f["gap"]                           # LM1b (A5): its episode's waiting item, another video's
                if held is None and gap is not None:         # a waiting video's (K5): its row takes the copy in place
                    gap = self._fill_gap(cmd, gap, p, gaps)
                    if gap is not None:
                        self._keep_hash(gap, p[4], f.get("copy_sha256"))
                    if gap is not None and other and f.get("video_path"):
                        self._as_versions(gap)               # the subtitle's own video is the episode's from now
                    exact = exact and gap is not None        # its row gone (P1): a new item, the videos read again
                if held is None and gap is None and same and same in by_bytes:   # the same bytes in this batch (A5)
                    item_id = by_bytes[same]
                    spare[p[1]] = p[2]
                elif held is None and gap is None:
                    item_id = self._take_new(cmd, change, p, key, record, f, first, rules, works, episodes, runs)
                    change.recorded[origin] = item_id
                    by_bytes.setdefault(same, item_id)
                    for k in _video_keys(f):                 # H9: the same video later in this batch finds it
                        (taken if is_content_name(p[1]) else gaps)[k] = item_id
                    continue
                else:                                        # its copy is an item, or a waiting video's (K5)
                    item_id = held[0] if held else gap
                    if held is not None and not is_content_name(p[1]):
                        exact = False                        # a video's record on a waiting row: read them again
            elif not self.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
                change.skipped["gone"].append(origin)
                continue
            by_bytes.setdefault(same, item_id)
            self._write_origin(key, item_id, record)
            if f.get("moved_from"):                          # D5: the originals this one replaced, marked
                self._mark_moved(item_id, key, f["moved_from"])
            if isinstance(record.get("audiobook"), dict):    # a5-2: its files named anew: the row's 🎧 hover
                cmd.feed([item_id])
            change.recorded[origin] = item_id
            episodes.pop(item_id, None)                      # its preferred record may be this one now
            change.attached.append(item_id)
            if p is None or is_content_name(p[1]):
                taken.update(dict.fromkeys(_video_keys(f), item_id))
            cmd.touch()
        if any(f.get("show_group") for f in found):   # LM2: the show's group, on its title once
            self._note_groups(found, change)
        # N1: the copies no item holds (a skipped file's, a same-bytes one's), for the caller to send to the trash
        change.unused = [rel for rel, rel_key in spare.items() if rel and not self.conn.execute(
            "SELECT 1 FROM items WHERE rel_key = ?", (rel_key,)).fetchone()]
    # the waiting videos as this batch left them, kept for the next while nothing else writes (this connection's
    # changes after the commit, and SQLite's data_version as read inside it: another connection's commit since moves it)
    self._gaps = ((self.conn.total_changes, stamp), gaps) if exact and not nested else None
    return change


def _store_mark_moved(self, item_id, key, olds):
    """D5, inside `take_in`: the records of `olds` (path keys) still this item's, live (no version) and unmarked, say
    their original moved to `key`'s (`"moved_to"`: its path key) — bookkeeping in a record, nothing deleted."""
    for old in dict.fromkeys(olds):
        old_key = SOURCE_KEY + str(old)
        if old_key == key:
            continue
        row = self.conn.execute("SELECT item_id, pairing FROM pairings WHERE content_key = ?", (old_key,)).fetchone()
        record = _json_dict(row[1]) if row is not None and row[0] == item_id else None
        if record is None or record.get("version") is True or record.get("moved_to"):
            continue
        record["moved_to"] = key[len(SOURCE_KEY):]
        self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                          (json.dumps(record, sort_keys=True, ensure_ascii=False), old_key))


def _store_origins_back(self, origins):
    """D5: originals a look listed in their old place again (`origins`: absolute paths) — their `moved_to` mark taken
    off, in ONE write, bookkeeping the copy carries. -> the origins whose row changed."""
    done = []
    with self._writing():
        for origin in origins:
            key = origin_key(origin)
            row = self.conn.execute("SELECT pairing FROM pairings WHERE content_key = ?", (key,)).fetchone()
            record = _json_dict(row[0]) if row is not None else None
            if record is None or "moved_to" not in record:
                continue
            del record["moved_to"]
            self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                              (json.dumps(record, sort_keys=True, ensure_ascii=False), key))
            done.append(origin)
        if done:
            self._copy_dirty()
    return done


def _store_take_version(self, cmd, change, root_id, origin, key, f, out):
    """LM1b, inside `take_in`: another version of an episode already in — a second group's subtitle, a lower release,
    one only its number joined (`f`: no copy; `item_id`, or `version_of`, the origin of the pick taken in earlier in
    this batch — the batch takes versions last). Recorded on the item flagged `version` (`_VERSION_ROW`: never its text,
    video, number or pairing; never a new item, never counted); not recorded when recorded already, kept out (S6) or
    its item isn't there (its pick not taken in: the next look asks again) — the look counted it skipped already."""
    if self.conn.execute("SELECT 1 FROM pairings WHERE content_key = ?", (key,)).fetchone():
        return
    if key[len(SOURCE_KEY):] in out["patterns"] or (f.get("sha256") and f["sha256"] in out["sha256"]):
        return
    item_id = f.get("item_id")
    if item_id is None:
        item_id = change.recorded.get(os.path.abspath(str(f.get("version_of") or "")))
    if item_id is None or not self.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
        return
    record = {k: v for k, v in _origin_record(root_id, origin, f).items() if not k.startswith("video_")}
    record["version"] = True
    self._write_origin(key, item_id, record)
    change.versions.append(item_id)
    cmd.touch()


def _store_as_versions(self, item_id):
    """LM1b (A5): a waiting item filled by a subtitle named like ANOTHER video of its episode — the records it waited
    on (the first video's) become other versions of it, so the item's one video is the one its subtitle was made for
    (Connect times cards to it); they stay recorded, so that video is never a new waiting item."""
    for key, text in self.conn.execute(f"SELECT p.content_key, p.pairing FROM pairings p WHERE p.item_id = ? AND "
                                       f"{_ORIGIN_ROW} AND NOT {_VERSION_ROW}", (item_id,)).fetchall():
        record = _json_dict(text)
        if record is None:
            continue
        record["version"] = True
        self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                          (json.dumps(record, sort_keys=True, ensure_ascii=False), key))


def _store_write_origin(self, key, item_id, record):
    self.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                      (key, item_id, json.dumps(record, sort_keys=True, ensure_ascii=False), _now()))


def _store_take_new(self, cmd, change, prepared, key, record, f, first, rules, works, episodes=None, runs=None):
    """One new item of `take_in`: its title (the folder's — `Library/<show>` and a 2.x `HighPriority/<show>` are one —
    else the record's show, else a new one), its place (`_source_spot`), its origin record, its events. A video with
    no text copy (K5: its `rel` the video's name, no file made) is 'waiting': in New arrivals even on setup's scan,
    never placed by a rule, never counted."""
    rel = prepared[1]
    audio = record.get("audiobook") if isinstance(record.get("audiobook"), dict) else None
    waiting = (record.get("video_path") is not None or audio is not None) and not is_content_name(rel)
    if waiting:                                      # fincov (LM1b): typed from its video — a subtitle episode waiting
        entry = dict(prepared[3], source_type="audio" if audio else "subtitle")   # for its text — never the fallback
        if audio and audio.get("title"):             # 'text' (a book's); an audiobook (Hon, H-7) its own type and title
            entry["title"] = str(audio["title"])
        prepared = prepared[:3] + (entry, (None, None, "waiting"))
    # H-6: an audiobook paired with a book is one more row of the book's title, after its last part, wherever that is;
    # alone or asked about, a title of its own by its own folder (`<title> (audio)`), never a book's of the same name
    joined = self._audiobook_place(audio["book"]) if audio and isinstance(audio.get("book"), dict) else None
    if audio and not joined and audio.get("book") is not None:
        record = dict(record, audiobook=dict(audio, book=None))      # its book gone meanwhile: alone, never half-paired
    if joined:
        work = joined[0]
    elif audio:
        work = self._folder_work(rel, str(audio.get("title") or "") or None, cmd, works)
    else:
        work = self._source_work(rel, record, cmd, works)
    if first == SORT and _tier_2x(record.get("origin")) in CURRENT:
        first = True                                 # K8: a 2.x library's NOW / Soon folder keeps Current, unsorted
    runs = runs if first and first != SORT and not waiting else None
    if joined:
        tier, where = joined[1], ("after", joined[2])
    elif first and not waiting and _tier_2x(record.get("origin")) in ("goal", "graduated"):
        # K8: a 2.x library's Goal folder read as his library's folder; a7: its Graduated one lands in Finished (Sonic
        # 2026-10-30), dated *Earlier* as every title finished before Surasura (`import_finished`, the 2.x image)
        tier, where = _tier_2x(record.get("origin")), ("end",)
        runs = None                                  # (no Current run of its show to keep)
    else:
        tier, where = self._source_spot(cmd, work, rel, f.get("episode"), first if not waiting else False, waiting,
                                        episodes, runs)
    item_id = self._add_rows([prepared + (tier,)], cmd.version)[0]
    self.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (work, item_id))
    if not waiting:
        self._keep_hash(item_id, prepared[4], f.get("copy_sha256"))    # A4K-7: its bytes are known — never read back
    self._write_origin(key, item_id, record)
    if episodes is not None:                         # its one record, so its number is the record's (`_episodes_of`)
        number = record.get("episode")
        episodes[item_id] = number if isinstance(number, (int, float)) and not isinstance(number, bool) else None
    self._put(tier, [item_id], where, cmd.version)
    if runs is not None:                             # the batch's copy of its show's run, as it now stands
        _run_insert(runs[work], (item_id, tier, None, rel), where)
    cmd.touch(() if joined else {tier}, availability=prepared[4][2] == "missing")   # (a waiting row moves no count)
    change.added.append(item_id)
    if first:
        cmd.quiet.add(item_id)                       # S1: setup's scan logs nothing (a back-fill's rule)
    else:
        cmd.event(item_id, "placed", 0)              # SRC-2: silent, the source's, never explicit
        if tier == "arrivals" and not waiting:       # Decision 1: the rule places it (after-show by default)
            self._apply_rule(item_id, record, rules)
    change.placed[item_id] = self.conn.execute("SELECT tier FROM items WHERE id = ?", (item_id,)).fetchone()[0]
    return item_id


def _tier_2x(origin):
    """K8 (alpha 4, Mattias's note 9; A4K-3 PROVISIONAL): the tier a 2.x library's own folders give a file read from
    inside them on setup's first look (and *Start fresh*'s, the same look) — `…/data/<ja|zh>/GoalContent/<show>/…`
    "goal" (`HighPriority` "now",
    `LowPriority` "soon": Current either way, in the order a look reads them; a7, Sonic 2026-10-30: `Graduated`
    "graduated", Finished, dated *Earlier*) — or None. No content migration (Sonic
    2026-10-23): it is still the folder he points setup at; his 2.x Goal stays his Goal — a show he had partly moved up in
    2.x (episodes 1–3 in HighPriority, the rest in GoalContent) keeps that split, whichever folder is picked first."""
    parts = os.path.normpath(origin).split(os.sep) if isinstance(origin, str) else []
    for i in range(len(parts) - 2, 1, -1):
        tier = _TIER_OF_FOLDER_FOLDED.get(parts[i].casefold()) or \
            ("graduated" if parts[i].casefold() == GRADUATED_FOLDER.casefold() else None)
        if tier and parts[i - 1].casefold() in ("ja", "zh") and parts[i - 2].casefold() == "data":
            return tier
    return None


def _video_keys(record):
    """A record's video as K5 matches it: its key, and its path's key (the pattern a waiting item's Remove writes)."""
    path = record.get("video_path")
    return [k for k in (record.get("video_key"), path and path_key(os.path.abspath(path))) if k]


def _store_waiting_videos(self):
    """{video key or path key: item id} of the items waiting for their subtitle (K5). Inside `take_in`: read once, then
    the copy the last batch left while nothing else was written (`_gaps`: every batch read every origin)."""
    held = getattr(self, "_gaps", None)
    if held is not None and held[0] == (self.conn.total_changes,
                                        self.conn.execute("PRAGMA data_version").fetchone()[0]):
        return dict(held[1])
    out = {}
    # the items first, each one's records by `pairings_item` (13 ms at 20k origins, against 34 ms reading every
    # origin's row); in the records' order, as before
    for item_id, text in self.conn.execute(f"SELECT p.item_id, p.pairing FROM items i CROSS JOIN pairings p ON "
                                           f"p.item_id = i.id WHERE i.availability = 'waiting' AND {_ORIGIN_ROW} "
                                           f"AND NOT {_VERSION_ROW} "
                                           f"ORDER BY p.content_key"):
        for k in _video_keys(_json_dict(text) or {}):
            out[k] = item_id
    return out


def _store_fill_gap(self, cmd, item_id, prepared, gaps):
    """A waiting item's subtitle came (K5): the item takes the copy in place — its id, place and records kept, no
    event (it was shown already) — and counts from now. -> its id; None, and its keys out of `gaps`, when its row is no
    longer a waiting one (P1: a copy of the waiting videos a rolled-back write left — never another item filled)."""
    if self.conn.execute("SELECT availability FROM items WHERE id = ?", (item_id,)).fetchone() != ("waiting",):
        for k in [k for k, v in gaps.items() if v == item_id]:
            del gaps[k]
        return None
    self.conn.execute("UPDATE items SET entry = ? WHERE id = ?", (_dumps(prepared[3]), item_id))
    self._repoint(item_id, prepared[1], prepared[4][0], prepared[4][1])
    cmd.touch({self.conn.execute("SELECT tier FROM items WHERE id = ?", (item_id,)).fetchone()[0]}, availability=True)
    for k in [k for k, v in gaps.items() if v == item_id]:
        del gaps[k]
    return item_id


def _store_source_work(self, rel, record, cmd, cache):
    """A new copy's title: the work holding its folder key (one title with the 2.x folder of that show), else the one
    its record's show names (`_work_by_record`: a show hato brought in first), else its folder's (`_folder_work`)."""
    fk = folder_key_of(rel)
    if fk is not None:
        row = self.conn.execute("SELECT id FROM works WHERE folder_key = ? ORDER BY id LIMIT 1", (fk,)).fetchone()
        if row:
            return row[0]
    return self._work_by_record(record) or self._folder_work(rel, None, cmd, cache)


def _run_insert(run, row, where):
    """A show's run (in order) with `row` put where `_put` put it: ('before', id), ('after', id), ('top',), ('end',)."""
    if where[0] in ("before", "after"):
        at = next(n for n, r in enumerate(run) if r[0] == where[1]) + (where[0] == "after")
    else:
        at = 0 if where[0] == "top" else len(run)
    run.insert(at, row)


def _store_source_spot(self, cmd, work, rel, episode, first, waiting=False, episodes=None, runs=None):
    """(tier, where) for a new copy of `work` (see `take_in`). Setup's scan: its show's run in Current, else Current's
    end — `first=SORT` (setup's scan since Mado-O): its show's run in New arrivals, else its end, quiet, for the sort
    screen (no rule takes it on). Later: New arrivals — its show's run there, else the end — and the placing rule
    takes it on from there (`_take_new`, Decision 1); with New arrivals off (no rule runs) its show's run in Current, else the top of it.
    `waiting` (K5, review H3): New arrivals always, whatever its show's rows (nothing to read or mine). `episodes`:
    `_in_run`'s cache of the batch; `runs` (setup's scan): each show's run in Current read once a batch, kept in
    order by `_take_new` (a long show's file is never placed by reading and sorting its whole run again)."""
    if first == SORT:                                # Mado-O: setup's scan waits for the sort screen, in New arrivals
        run = [r for r in self.conn.execute("SELECT id, tier, ord, rel_path FROM items WHERE work_id = ? AND tier = "
                                            "'arrivals'", (work,)).fetchall()]
        return self._in_run(run, rel, episode, episodes) if run else ("arrivals", ("end",))
    if first and runs is not None and work in runs:
        current = runs[work]
        return self._in_run(current, rel, episode, episodes, ordered=True) if current else \
            (("soon", ("end",)) if self._soon_line() is not None else ("now", ("end",)))
    rows = self.conn.execute("SELECT id, tier, ord, rel_path FROM items WHERE work_id = ?", (work,)).fetchall()
    current = [r for r in rows if r[1] in CURRENT]
    if first:
        if runs is not None:
            current = runs[work] = sorted(current, key=lambda r: (TIERS[r[1]][3], r[2], r[0]))
        if current:
            return self._in_run(current, rel, episode, episodes)
        return ("soon", ("end",)) if self._soon_line() is not None else ("now", ("end",))   # the line takes it up
    if not (waiting or cmd.meta.get("arrivals_on")):
        return self._in_run(current, rel, episode, episodes) if current else ("now", ("top",))
    run = [r for r in rows if r[1] == "arrivals"]
    return self._in_run(run, rel, episode, episodes) if run else ("arrivals", ("end",))


def _store_in_run(self, run, rel, episode, episodes=None, ordered=False):
    """Within a show's run (S3): before the first row whose episode number (when both have one) or natural-order
    name is higher, else after the last. `episodes`: a batch's cache of the numbers (`_episodes_of`); `ordered`: the
    run is in order already."""
    order = run if ordered else sorted(run, key=lambda r: (TIERS[r[1]][3], r[2], r[0]))
    if episode is None:
        numbers = {}
    elif episodes is not None:
        self._episodes_of([r[0] for r in order], episodes)
        numbers = episodes
    else:
        numbers = self._episodes_of([r[0] for r in order])
    name = _natural(rel.rsplit("/", 1)[-1])
    for r in order:
        theirs = numbers.get(r[0])
        later = theirs > episode if theirs is not None else _natural(r[3].rsplit("/", 1)[-1]) > name
        if later:
            return (r[1], ("before", r[0]))
    return (order[-1][1], ("after", order[-1][0]))


def _store_episodes_of(self, ids, cache=None):
    """{item_id: episode number} from each item's record (hato's `show.episode`, else an origin's K4 `episode`; B1:
    an origin row only when the item has no other). `cache` ({item_id: number or None}, one `take_in` batch's): only
    the ids it doesn't hold are read, and each one read is kept in it (a show's run read once a batch, not per file)."""
    if cache is not None:
        todo = [i for i in dict.fromkeys(ids) if i not in cache]
        found = self._episodes_of(todo) if todo else {}
        for i in todo:
            cache[i] = found.get(i)
        return {i: cache[i] for i in ids if cache[i] is not None}
    out = {}
    for chunk in _chunks(list(ids), 500):
        for item_id, text in self.conn.execute(f"SELECT p.item_id, p.pairing FROM pairings p WHERE p.item_id IN "
                                               f"({','.join('?' * len(chunk))}) AND {_PREFERRED_ROW}", chunk):
            record = _json_dict(text) or {}
            number = record.get("episode") if record.get("producer") == SOURCE_PRODUCER else \
                (_episode(record) or (None, None))[1]
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                out[item_id] = number
    return out


# --- LM2: one subtitle group per show, picked once (pick-and-stick) ---------------------------------------------- #
# PROVISIONAL (Sonic 2026-10-21: LM-1a, T2-A1, T2-A2, A29; to be checked in use). A show's subtitle group (the look's
# reading, `sources._group`: the leading `[tag]` and the name before the episode marker, folded) is recorded on its
# title in meta `show_groups` — {work id: {"group": [tag, name], "label", "by": "look" | "connect" | "user",
# "checked": Connect's first-cards check is done, "tried": the groups a check found no fit in, "pending": episodes a
# switch couldn't take yet}} — at the first take-in that takes one of its episodes, and never decided again by a look;
# the copy carries it (`COPY_META_KEYS`), a fresh library starts without it. Connect's first cards may switch it
# (`switch_group`: every episode holding that group's copy takes it in place; the last switch is kept, `last_switch`,
# so the window's Undo reaches it after a restart too: `undo_switch`).
SHOW_GROUPS = "show_groups"
LAST_SWITCH = "last_switch:"     # + work id: the title's last switch, as its Undo needs it
SWITCH_PENDING = "switch_pending:"   # + a switch step's token: the file moves of a step not committed (a crash's)
SWITCH_BATCH = 3                 # episodes a switch command swaps: ~10 ms of write lock here, a laptop's ≤ ~25 ms
SWITCH_STALE_S = 60              # a pending step older than this is a crashed one (a step waits ≤ LOCK_TIMEOUT)
EDITION_PENDING = SWITCH_PENDING + "edition:"   # + a token: a book's new edition, switched as ONE change (LM3)
PASSED_OVER = ("declined", "thin", "fit")   # a version's marks, each its file's sha256 (`fit`: [sha, copy size, time])


def is_hato(pairing):
    """LM3 (A8), the ONE "is this hato's?": a record hato's drop wrote (its producer, as the placement log reads it,
    `_producer`) — never a folder's origin record (`source`), Connect's *Link…* record (`surasura`) nor a YouTube
    registration. `_group_copies`, `hato_items` (the look's `_held`) and every LM3 reading ask it."""
    return _producer(pairing) == "hato"


def _groups_read(self):
    row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (SHOW_GROUPS,)).fetchone()
    return (_json_dict(row[0]) if row else None) or {}


def _group_value(group):
    """A group as recorded ([tag, name], two strings), or None for anything else."""
    if isinstance(group, (list, tuple)) and len(group) >= 2 and all(isinstance(g, str) for g in group[:2]):
        return [group[0], group[1]]
    return None


def _store_show_groups(self):
    """{a show's folder key: its group (tag, name)} — the look's read, once a look: the group of the title a new file
    of that folder joins, as `_folder_work` finds it — the lowest id holding the folder key, else the title of the
    files in that folder (a show merged into another title keeps going there)."""
    with self._reading():
        groups = _groups_read(self)
        if not groups:
            return {}
        out, owned = {}, set()
        for fk, work_id in self.conn.execute("SELECT folder_key, MIN(id) FROM works WHERE folder_key IS NOT NULL "
                                             "GROUP BY folder_key"):
            owned.add(fk)
            group = _group_value((groups.get(str(work_id)) or {}).get("group"))
            if group is not None:
                out[fk] = tuple(group)
        ids = [int(w) for w, r in groups.items() if w.isdigit() and _group_value((r or {}).get("group"))]
        for chunk in _chunks(ids, 500):
            for work_id, folder in self.conn.execute(
                    f"SELECT DISTINCT work_id, parent_folder FROM items WHERE work_id IN "
                    f"({','.join('?' * len(chunk))}) AND parent_folder IS NOT NULL AND parent_folder != ''", chunk):
                fk = path_key(folder)
                if fk not in owned and fk not in out:
                    out[fk] = tuple(_group_value(groups[str(work_id)]["group"]))
    return out


def _store_note_groups(self, found, change):
    """(Inside `take_in`.) The show's group a look decided (`found`'s `show_group`: the group of the file it took for
    the show's earliest episode, or of the earliest episode in), recorded on the title of the item each entry went to
    — only where the title has none yet (A29: never decided again)."""
    groups, changed = None, False
    for f in found:
        decided = f.get("show_group")
        group = _group_value(decided.get("group")) if isinstance(decided, dict) else None
        if group is None:
            continue
        item_id = change.recorded.get(os.path.abspath(f["origin"])) or f.get("item_id") or \
            change.recorded.get(os.path.abspath(str(f.get("version_of") or "")))
        row = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone() if item_id else None
        if row is None or row[0] is None:
            continue
        if groups is None:
            groups = _groups_read(self)
        record = groups.setdefault(str(row[0]), {})
        if _group_value(record.get("group")) is None:
            record.update(group=group, label=str(decided.get("label") or ""), by="look")
            record.setdefault("checked", False)
            changed = True
    if changed:
        self._set_meta({SHOW_GROUPS: _dumps(groups)})


def _carry_group(self, keep_id, other_ids):
    """(Inside `merge_works`.) A merged title's group record goes to the title kept when that one has none, or only a
    look's: a show Connect or the learner switched keeps its group as *Same title as…* joins it."""
    groups = _groups_read(self)
    kept = groups.get(str(keep_id)) or {}
    if _group_value(kept.get("group")) is not None and kept.get("by") != "look":
        return
    chosen = [groups[str(o)] for o in other_ids if _group_value((groups.get(str(o)) or {}).get("group"))]
    record = next((r for r in chosen if r.get("by") != "look"), None) or         (next(iter(chosen), None) if _group_value(kept.get("group")) is None else None)
    if record is not None:
        groups[str(keep_id)] = dict(record)
        self._set_meta({SHOW_GROUPS: _dumps(groups)})


def _store_group_of(self, work_id):
    """LM2, Connect's first cards (T2-A2): the title's subtitle group -> {"group": [tag, name] | None, "label": the
    group as a learner reads it | None, "by": who decided it ("look" | "connect" | "user") | None, "checked": Connect's
    first-cards check is done (a fit kept, `keep_group`; a switch; the learner's own switch or Undo), "tried": the
    groups a check tried and found no fit in ([[tag, name]]: check again once another group's copy is there),
    "pending": the episodes a switch couldn't take yet (offline, held open: `switch_group` again takes them)}; None
    when there is no such title."""
    with self._reading():
        if not self.conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone():
            return None
        record = _groups_read(self).get(str(work_id)) or {}
    return {"group": _group_value(record.get("group")), "label": record.get("label") or None,
            "by": record.get("by"), "checked": bool(record.get("checked")),
            "tried": [g for g in map(_group_value, record.get("tried") or ()) if g],
            "pending": [i for i in record.get("pending") or () if isinstance(i, int)]}


def _store_keep_group(self, work_id, by="connect", tried=None):
    """LM2 (T2-A2): Connect's first-cards check kept the title's group. `tried` None: the pick fits — "checked", so
    the check never runs again for that title. `tried` ([group, …]: the pick's and every other group's it tried, none
    fitting): the check stays open, the groups recorded, so Connect checks again only once another group's copy is
    there (PROVISIONAL, Sonic 2026-10-21, to be checked in use). Bookkeeping the copy carries (no version moves, never on the
    Undo stack). -> True when written."""
    with self._writing():
        if not self.conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone():
            return False
        groups = _groups_read(self)
        record = groups.setdefault(str(work_id), {})
        if tried is None:
            if record.get("checked"):
                return False
            record["checked"] = True
            record.pop("tried", None)
        else:
            seen = [g for g in map(_group_value, record.get("tried") or ()) if g]
            new = [g for g in map(_group_value, tried) if g and g not in seen]
            if not new:
                return False
            record["tried"] = seen + new
        record.setdefault("by", None)
        self._set_meta({SHOW_GROUPS: _dumps(groups), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})
    return True


def _group_copies(self, item_id):
    """(Inside a read.) An episode's subtitle copies by group -> (its pick's rows {content key: pairing text}, the
    pick's group, {group: (key, record, rank)} — of each other group the copy the look would pick — the pick's rank,
    the pick's origin), read by the ONE rule (`sources.group_copies`: `version_rank`, the latest release, then
    `subtitle_rank`; never a flagged track (signs, karaoke), a bilingual file, a double-episode file or the pick's own
    bytes); "hato" for an item hato's text is the pick of (LM3: never switched by a look, Connect or the learner's
    *Use [B]'s*; `is_hato`: Connect's own link record is no hato's); None for one that isn't a folder's episode (no
    origin, a book's part). The picks are the item's origin records only."""
    from app import sources
    rows = self.conn.execute(f"SELECT p.content_key, p.pairing, {_ORIGIN_ROW}, {_VERSION_ROW} FROM pairings p "
                             f"WHERE p.item_id = ? ORDER BY p.content_key", (item_id,)).fetchall()
    if not rows:
        return None
    if any(not o and is_hato(_json_dict(t) or {}) for _k, t, o, _v in rows):
        return "hato"                                # hato's text: not a folder's pick (LM3)
    picks = {k: t for k, t, o, version in rows if o and not version}
    records = {k: _json_dict(t) or {} for k, t, o, _v in rows if o}
    if not picks or any(_EPUB_PART.search(str(records[k].get("origin") or "")) for k in picks):
        return None
    mine, rank, best = sources.group_copies([(k, records[k]) for k in picks],
                                            [(k, records[k]) for k, _t, o, version in rows if o and version],
                                            self.language)
    pick = next((records[k] for k in picks if records[k].get("video_path")), records[next(iter(picks))])
    return picks, mine, {g: (k, records[k], r) for g, (k, r) in best.items()}, rank, str(pick.get("origin") or "")


def _store_other_subtitles(self, item_id):
    """LM2 (T2-A2), Connect's first cards: the episode's other groups' subtitles beside its pick -> [{"path": the
    original (absolute; not checked: a drive may be offline), "group": [tag, name], "label", "content_key"}], one per
    group other than the pick's — the copy `switch_group` would take for this episode — best first in the look's order
    (`sources.version_rank`)."""
    from app import sources
    with self._reading():
        copies = _group_copies(self, item_id)
    if not isinstance(copies, tuple):
        return []
    _picks, mine, best, _rank, _origin = copies
    return [{"path": record["origin"], "group": list(group),
             "label": sources.group_label(os.path.basename(record["origin"])), "content_key": key}
            for group, (key, record, _rank) in sorted(best.items(), key=lambda g: g[1][2]) if group != mine]


def _swapped(picks, record, to_key):
    """The records after a switch to `to_key` (its `record`): every row of the pick a version (no video: it moves),
    the new pick the item's own, with the video the old one held (and none of a version's passed-over marks, LM3)."""
    old = {k: _json_dict(t) or {} for k, t in picks.items()}
    video = next(({f: r[f] for f in ("video_path", "video_size", "video_key") if r.get(f) is not None}
                  for r in old.values() if r.get("video_path")), {})
    write = {k: dict({f: v for f, v in r.items() if not f.startswith("video_")}, version=True) for k, r in old.items()}
    write[to_key] = dict({f: v for f, v in record.items() if f not in ("version",) + PASSED_OVER and
                          not f.startswith("video_")}, **video)
    return write


def _switch_plan(self, item_id, rel, picks, key, record, keep_name=False):
    """(Inside a read.) One episode's swap to the version `key` (its `record`) -> the plan `_switch` carries out: the
    copy named as the subtitle it will hold (`_switch_rel`: a group switch, LM2 B1) — `keep_name` (LM3's better
    version, A16): its own name kept unless its format changes —, the bytes the original must still hold, the records
    as read (a step swaps only while they are still so) and as they will be (`_swapped`); None when another item has
    that name (held)."""
    same = os.path.splitext(rel)[1].lower() == os.path.splitext(record["origin"])[1].lower()
    to_rel = rel if keep_name and same else _switch_rel(self, rel, record["origin"], item_id)
    if to_rel is None:
        return None
    text = self.conn.execute("SELECT pairing FROM pairings WHERE content_key = ?", (key,)).fetchone()
    if text is None:
        return None                                  # its record gone meanwhile: held, the next look
    text = text[0]
    return {"item": item_id, "rel": rel, "to_rel": to_rel, "sha256": record.get("sha256"), "key": key,
            "origins": [record["origin"]], "expect": dict(picks, **{key: text}), "write": _swapped(picks, record, key)}


def _switch_rel(self, rel, origin, item_id):
    """Where the switched copy lives: named as the subtitle it now holds (`Library/<show>/<its name>`: its format the
    readers read by its extension — an `.srt`'s bytes never sit in an `.ass` — and the window names it), or None when
    another item already has that name."""
    to_rel = rel.rsplit("/", 1)[0] + "/" + os.path.basename(origin)
    if path_key(to_rel) == path_key(rel):
        return rel
    taken = self.conn.execute("SELECT 1 FROM items WHERE rel_key = ? AND id != ?", (path_key(to_rel), item_id))
    if taken.fetchone():
        return None                                  # (a file there that is no item's: the step holds it, unwritten)
    return to_rel


def _store_switch_group(self, work_id, group, by="connect"):
    """LM2 (T2-A2: Connect's first cards found another group's subtitle fits; LM3's *Use [B]'s subtitles*): the title
    switches to `group` ([tag, name], as `other_subtitles` names it) — every episode holding that group's copy takes
    it IN PLACE: the item keeps its id, place and cards; its copy gets that subtitle's bytes and name (the old copy to
    the data folder's trash first, its clock restarted); the pick's records become versions and the new one is the
    item's (its video moves with it, so Connect's `pairing_of` reads it). The originals are read and checked by their
    sha256 outside the write lock; the swaps go SWITCH_BATCH episodes a command (G1), each step's file moves noted
    first (`SWITCH_PENDING`: a crash's are put back, `settle_switches`). Once an episode switched, the group is recorded
    (`by`, `checked`; its episodes held this time `pending`: `switch_group` again takes them) — never over a record
    changed meanwhile (the learner's own switch) — and the switch kept for its Undo (`last_switch`, `undo_switch`).
    -> the Change (kind `switch_group`: `switched`; `missing` — episodes with no copy of that group; `held` — offline,
    changed since the look, held open, hato's text, or its name taken), undone by `Store.undo` or `undo_switch`;
    nothing recorded when nothing switched."""
    from app import sources
    target = _group_value(group)
    if target is None:
        raise ValueError(f"a group is [tag, name]: {group!r}")
    target = tuple(target)
    self.settle_switches()
    plans, missing, held, label = [], [], [], None
    with self._reading():
        if not self.conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone():
            raise ValueError(f"no title {work_id}")
        before = _groups_read(self).get(str(work_id))
        for item_id, rel, availability in self.conn.execute(
                "SELECT id, rel_path, availability FROM items WHERE work_id = ? ORDER BY id", (work_id,)).fetchall():
            copies = _group_copies(self, item_id)
            if copies == "hato":
                held.append(item_id)
                continue
            if copies is None:
                continue
            picks, mine, best, _rank, _origin = copies
            if mine == target:
                continue
            if target not in best:
                missing.append(item_id)
                continue
            key, record, _rank = best[target]
            label = label or sources.group_label(os.path.basename(record["origin"]))
            plan = _switch_plan(self, item_id, rel, picks, key, record) if availability == "available" else None
            if plan is None:
                held.append(item_id)
                continue
            plans.append(plan)
    after = {k: v for k, v in (before or {}).items() if k not in ("tried", "pending")}
    after.update(group=list(target), label=label or after.get("label") or "", by=by, checked=True)
    return self._switch("switch_group", by, work_id, plans, missing, held, (before, after), label_from=(
        before or {}).get("label"), label_to=label)


def _part_path(self, plan, token):
    return os.path.join(self.data_dir, _strip(plan["to_rel"])) + f".{token}.part"


def _read_into_part(self, plan, token):
    """A switch's bytes, outside the lock: the plan's own (`plan["data"]`: a book's new edition's part, LM3), else the
    first of `plan["origins"]` (then the trashed copy, `plan["trash"]`) whose bytes are `plan["sha256"]`, written beside
    the copy as `<copy>.<token>.part` (its own name: two switches never share one) -> True, else False. Never written
    where `Library` leads out of the data folder."""
    full = os.path.join(self.data_dir, _strip(plan["rel"]))
    if not _ours_to_move(self.data_dir, plan["rel"], full):
        return False
    tried = list(plan["origins"]) + ([os.path.join(self.data_dir, _strip(plan["trash"]))] if plan.get("trash") else [])
    part = _part_path(self, plan, token)
    for path in ([None] if plan.get("data") is not None else []) + tried:
        try:
            if path is None:
                data = plan["data"]
            else:
                with open(path, "rb") as f:
                    data = f.read()
        except OSError:
            continue
        if not plan["sha256"] or hashlib.sha256(data).hexdigest() != plan["sha256"]:
            continue
        try:
            with open(part, "wb") as f:
                f.write(data)
        except OSError:
            _remove_quietly(part)
            return False
        plan["part"] = part
        return True
    return False


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _part_holds(part, sha256):
    try:
        return sha256_of(part) == sha256
    except OSError:
        return False


def _trash_name(rel, token):
    base, ext = os.path.splitext(rel.rsplit("/", 1)[-1])
    return f".trash/{base}_{time.strftime('%Y%m%d%H%M%S')}_{token}{ext}"


def _store_switch(self, kind, by, work_id, plans, missing, held, record, label_from=None, label_to=None,
                  undoing=False):
    """THE swap path of every switch in place (LM2's `switch_group`; LM3's `switch_versions` and `switch_parts`; their
    Undo), SWITCH_BATCH episodes a command, one Change for all: per step, each episode's bytes read
    (`_read_into_part`), its file moves noted and committed first (`SWITCH_PENDING`), then ONE command: each episode
    whose records are still as read and whose part still holds those bytes swaps — its copy to the trash
    (`trash_file`), the new bytes in its place under its new name (`os.replace`, `_repoint`), its records made exactly
    the plan's (rewritten, a new one inserted, one it drops deleted), its size and time recorded — the note cleared,
    and (once an episode switched) the title's group record set to `record[1]` where it is still `record[0]` (G4: a
    switch made meanwhile is never written over) and the switch kept for its Undo (`last_switch`; an Undo drops it).
    `record` None (LM3: a better version, a book's new edition): the title's group and `last_switch` are left alone.
    An episode whose copy is held open, or whose records changed since, stays as it was (`held`); anything failing in
    a step puts its copies back (a later step's failure leaves the earlier steps done, the rest held). -> the Change,
    with `swaps` for its Undo."""
    meta = self.meta()
    change = Change(kind, meta["epoch"], meta["state_version"])
    change.work_id, change.switched, change.missing, change.held, change.swaps = work_id, [], list(missing), \
        list(held), []
    keep = record is not None                        # the title's group record and its last switch are this one's
    expected, new = record if keep else (None, None)
    change.group_before = expected
    written = False
    chunks = [plans[i:i + SWITCH_BATCH] for i in range(0, len(plans), SWITCH_BATCH)]
    for n, chunk in enumerate(chunks):
        token = uuid.uuid4().hex[:8]
        ready = []
        for plan in chunk:
            if _read_into_part(self, plan, token):
                plan["trash"] = _trash_name(plan["rel"], token)
                ready.append(plan)
            else:
                change.held.append(plan["item"])
        try:
            step = self._switch_step(kind, by, work_id, ready, token, change, expected, new, written, undoing,
                                     label_from, label_to, keep)
        except BaseException:
            if n == 0:
                raise
            print(f"Library store: a subtitle switch stopped after {len(change.switched)} of {len(plans)} episodes "
                  f"(the rest stay as they are)")
            change.held += [p["item"] for c in chunks[n:] for p in c if p["item"] not in change.held]
            break
        finally:
            for plan in ready:
                _remove_quietly(plan["part"])
        if step:
            written, expected = True, new
    if keep and written and not undoing and change.held:   # the episodes held wait as the record's `pending`
        try:
            with self._writing():
                groups = _groups_read(self)
                if _unpended(groups.get(str(work_id))) == _unpended(new):
                    groups[str(work_id)] = dict(groups[str(work_id)], pending=sorted(set(change.held)))
                    self._set_meta({SHOW_GROUPS: _dumps(groups)})
        except Exception:                            # the next switch_group finds them by their records anyway
            pass
    change.group_after = new if written else change.group_before
    return change


def _unpended(record):
    """A group record as a value check compares it: its `pending` list is the switch's own bookkeeping."""
    return {k: v for k, v in record.items() if k != "pending"} if isinstance(record, dict) else record


def _store_switch_step(self, kind, by, work_id, ready, token, change, expected, new, written, undoing, label_from,
                       label_to, keep=True):
    """One step of `_switch` (see there). -> True when the group record was written."""
    if not ready:
        return False
    pending = SWITCH_PENDING + token
    if ready:
        note = [dict({"rel": p["rel"], "to_rel": p["to_rel"], "trash": p["trash"], "part": _strip(library_rel(
            self.data_dir, p["part"]) or ""), "sha256": p["sha256"]}, **({"keep": True} if p.get("keep_part") else {}))
                for p in ready]                      # (`keep`: a new edition's part, staged in the trash: kept)
        self.bookkeeping({pending: _dumps({"at": time.time(), "moves": note})})
    moved, wrote = [], False
    try:
        with self._command(kind, by) as cmd:
            tiers = set()
            for plan in ready:
                item = self.conn.execute("SELECT rel_path, tier FROM items WHERE id = ?", (plan["item"],)).fetchone()
                now = dict(self.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?",
                                             (plan["item"],)).fetchall())
                if item is None or item[0] != plan["rel"] or \
                        any(now.get(k) != t for k, t in plan["expect"].items()) or \
                        any(k not in now and self.conn.execute("SELECT 1 FROM pairings WHERE content_key = ?",
                                                               (k,)).fetchone() for k in plan["write"]) or \
                        not _part_holds(plan["part"], plan["sha256"]):
                    change.held.append(plan["item"])  # changed since it was read (a new record another's): left
                    continue
                full = os.path.join(self.data_dir, _strip(plan["rel"]))
                to_full = os.path.join(self.data_dir, _strip(plan["to_rel"]))
                if to_full != full and os.path.exists(to_full):
                    change.held.append(plan["item"])  # its new name taken meanwhile
                    continue
                try:
                    old = os.stat(full)
                    trashed = trash_file(self.data_dir, plan["rel"], to=plan["trash"])
                except OSError:                      # held open: left as it is
                    trashed = None
                if trashed is None:
                    change.held.append(plan["item"])
                    continue
                gone = os.path.join(self.data_dir, _strip(trashed))
                try:
                    os.replace(plan["part"], to_full)
                except OSError:
                    _switch_back(gone, full, old)
                    change.held.append(plan["item"])
                    continue
                moved.append((gone, full, to_full, old, plan))
                after = {}
                for key, value in plan["write"].items():
                    after[key] = value if isinstance(value, str) else json.dumps(value, sort_keys=True,
                                                                                ensure_ascii=False)
                    if not self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ? AND item_id = ?",
                                             (after[key], key, plan["item"])).rowcount:
                        self.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES "
                                          "(?, ?, ?, ?)", (key, plan["item"], after[key], _now()))   # LM3: an edition's
                for key in plan["expect"]:            # a record the plan drops (an edition's, put back by its Undo)
                    if key not in plan["write"]:
                        self.conn.execute("DELETE FROM pairings WHERE content_key = ? AND item_id = ?",
                                          (key, plan["item"]))
                st = os.stat(to_full)
                if plan["to_rel"] != plan["rel"]:
                    self._repoint(plan["item"], plan["to_rel"], st.st_size, st.st_mtime_ns)
                else:
                    self.conn.execute("UPDATE items SET size = ?, mtime_ns = ? WHERE id = ?",
                                      (st.st_size, st.st_mtime_ns, plan["item"]))
                cmd.feed([plan["item"]])
                tiers.add(item[1])
                change.switched.append(plan["item"])
                change.swaps.append(dict({"item": plan["item"], "rel": plan["to_rel"], "to_rel": plan["rel"],
                                          "trash": trashed, "before": plan["expect"], "after": after},
                                         **({"old_sha256": plan["old_sha256"]} if plan.get("old_sha256") else {})))
            self.conn.execute("DELETE FROM meta WHERE key = ?", (pending,))
            if change.switched and keep:
                groups = _groups_read(self)
                if _unpended(groups.get(str(work_id))) == _unpended(expected):
                    record = dict(new) if new is not None else None
                    if record is None:
                        groups.pop(str(work_id), None)
                    else:
                        groups[str(work_id)] = record
                    self._set_meta({SHOW_GROUPS: _dumps(groups)})
                    wrote = True
                if undoing:
                    self.conn.execute("DELETE FROM meta WHERE key = ?", (LAST_SWITCH + str(work_id),))
                else:
                    self._set_meta({LAST_SWITCH + str(work_id): _dumps({
                        "at": _now(), "by": by, "epoch": change.epoch, "from": label_from, "to": label_to,
                        "group_before": change.group_before, "group_after": dict(new) if new else None,
                        "switched": change.switched, "missing": change.missing, "held": change.held,
                        "swaps": change.swaps})})
            cmd.touch(tiers)
    except BaseException:
        for gone, full, to_full, old, plan in reversed(moved):   # the old copies back where they were
            if plan.get("keep_part"):                # (LM3: a new edition's bytes back to their staged file)
                try:
                    os.replace(to_full, plan["part"])
                except OSError as e:
                    print(f"Library store: a new edition's part couldn't go back to its staged file: {e!a}")
            elif to_full != full:
                _remove_quietly(to_full)
            _switch_back(gone, full, old)
        try:
            with self._writing():
                self.conn.execute("DELETE FROM meta WHERE key = ?", (pending,))
        except Exception:                            # the next look settles it (`settle_switches`)
            pass
        raise
    return wrote


def _switch_back(gone, full, old=None):
    """A copy the trash took back in its place, its time as it was (no re-read for nothing)."""
    try:
        os.replace(gone, full)
        if old is not None:
            os.utime(full, ns=(old.st_atime_ns, old.st_mtime_ns))
    except OSError as e:
        print(f"Library store: a switched copy couldn't be put back ({full!a}): {e!a}")


def _store_settle_switches(self, now=None):
    """A crashed switch's file moves put back (G3, S5): each step noted (`SWITCH_PENDING`) and never committed for
    SWITCH_STALE_S — the old copy back from the trash where its place holds the new bytes or nothing, the new name's
    file and the part removed — the note dropped. The records were never written (the note goes with them), so the
    copies agree with them again. -> how many steps were settled."""
    rows = self.conn.execute("SELECT key, value FROM meta WHERE key >= ? AND key < ? AND NOT (key >= ? AND key < ?)",
                             (SWITCH_PENDING, SWITCH_PENDING[:-1] + ";", EDITION_PENDING,
                              EDITION_PENDING[:-1] + ";")).fetchall()   # (an edition's own note: settle_editions)
    stale = [(k, _json_dict(v) or {}) for k, v in rows]
    stale = [(k, v) for k, v in stale if (now or time.time()) - float(v.get("at") or 0) > SWITCH_STALE_S]
    if not stale:
        return 0
    with self._writing():
        for key, note in stale:
            for move in note.get("moves") or ():
                full = os.path.join(self.data_dir, _strip(str(move.get("rel") or "")))
                to_full = os.path.join(self.data_dir, _strip(str(move.get("to_rel") or "")))
                gone = os.path.join(self.data_dir, _strip(str(move.get("trash") or "")))
                if move.get("keep"):                 # LM3: a new edition's part — its bytes back to their staged
                    part = os.path.join(self.data_dir, _strip(str(move.get("part") or "")))     # file, never lost
                    if move.get("trash") and os.path.isfile(gone):
                        if os.path.isfile(to_full) and not os.path.exists(part) and \
                                _part_holds(to_full, move.get("sha256")):
                            os.replace(to_full, part)
                        if not os.path.exists(full):
                            _switch_back(gone, full)
                    continue
                if move.get("part"):
                    _remove_quietly(os.path.join(self.data_dir, _strip(move["part"])))
                if not move.get("trash") or not os.path.isfile(gone):
                    if to_full != full and os.path.isfile(full) and _part_holds(to_full, move.get("sha256")):
                        _remove_quietly(to_full)
                    continue
                if os.path.isfile(to_full) and _part_holds(to_full, move.get("sha256")):
                    _remove_quietly(to_full)
                if not os.path.exists(full):
                    _switch_back(gone, full)
            self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
    return len(stale)


def _store_undo_switch(self, change, decline=True):
    """Undo of `switch_group` (`Store.undo`, `undo_switch`): each episode whose records are still as the switch wrote
    them gets its old pick's bytes and name back — from its original, else the copy the switch sent to the trash — and
    its records as they were; the title keeps the group it had, `checked` by the learner (S16: Connect never switches
    it again by itself), where its record is still the switch's. One that changed since stays, with a note. LM3's
    `switch_version` (a better version, a book's new edition): the title's group is left alone, and the version it
    switched to stays a version marked declined (`_declined`; `decline` False: a book's edition put back because it
    couldn't switch whole, tried again by the next look). A book's new edition: `_undo_edition` (ONE change)."""
    if getattr(change, "epoch", None) != self.meta()["epoch"]:
        raise UndoRefused("the library was rebuilt since; that change can't be undone")
    if getattr(change, "edition", False):
        return _undo_edition(self, change)
    self.settle_switches()
    plans, skipped = [], []
    with self._reading():
        for swap in change.swaps:
            now = dict(self.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?",
                                         (swap["item"],)).fetchall())
            item = self.conn.execute("SELECT rel_path, availability FROM items WHERE id = ?",
                                     (swap["item"],)).fetchone()
            to_rel = swap.get("to_rel") or swap["rel"]
            if item is None or item[0] != swap["rel"] or item[1] != "available" or \
                    any(now.get(k) != t for k, t in swap["after"].items()) or \
                    (to_rel != swap["rel"] and os.path.exists(os.path.join(self.data_dir, _strip(to_rel)))):
                skipped.append(swap["item"])
                continue
            pick = [r for r in (_json_dict(t) or {} for t in swap["before"].values()) if not r.get("version")]
            plans.append({"item": swap["item"], "rel": swap["rel"], "to_rel": to_rel,
                          "sha256": swap.get("old_sha256") or (pick[0].get("sha256") if pick else None),
                          "origins": [str(r.get("origin") or "") for r in pick], "trash": swap["trash"],
                          "expect": swap["after"], "write": _declined(swap["before"], swap["after"]) if decline and
                          change.kind == "switch_version" else dict(swap["before"])})
    record = None                                    # LM3: a better version's or an edition's: no group of its own
    if change.kind != "switch_version":
        back = dict(change.group_before or {}, checked=True, by="user")
        back.pop("pending", None)
        record = (getattr(change, "group_after", None), back)
    out = self._switch("undo", "undo", change.work_id, plans, [], skipped, record, undoing=True)
    n = len(out.held)
    if n:
        out.notes.append(f"{n} episode{'s' if n != 1 else ''} changed since and {'were' if n != 1 else 'was'} left as "
                         f"{'they are' if n != 1 else 'it is'}")
    if change.kind == "switch_version":
        _drop_last_switch(self, change)
    return out


def _undo_edition(self, change):
    """LM3 (fix round 2; PROVISIONAL, Kura / the lead 2026-10-23): a book's new edition undone as ONE change, journalled
    as the edition was (an `EDITION_PENDING` note marked `undo`, carried by `_edition_go`): every part back to the old
    edition's bytes (the copy its switch sent to the trash, checked by its sha256) and records (the new edition's kept a
    version, declined: `_declined`), then the parts it added taken out (copies to the trash first, one removal), then
    the parts past its end put back (one restore) — all or none: a part held open → every part keeps the new edition,
    the Undo waits (`waiting`, said in its notes; the title keeps its last switch, so Undo stays) and the next look's
    `settle_editions` finishes it, as it finishes a crashed one; the last switch goes in the write that ends it. Pressed
    again while it waits, the same Undo is carried on, claimed as a look claims it (`_edition_take`); while another
    runner carries it, or a crashed step of it is not put back yet, the press is told it is under way. A part the learner removed since stays removed; a part changed
    since (its records, its name, its copy gone), an old copy no longer in the trash, or another switch of the book
    under way → `UndoRefused`, nothing changed. -> the Change (kind `undo`: `switched` the parts put back)."""
    self.settle_switches()
    sid = getattr(change, "switch_id", None)
    with self._reading():
        notes = [(k, _json_dict(v) or {}) for k, v in self.conn.execute(
            "SELECT key, value FROM meta WHERE key >= ? AND key < ?", (EDITION_PENDING, EDITION_PENDING[:-1] + ";"))]
    waiting = next((k for k, n in notes if sid is not None and n.get("undo") == sid), None)
    if waiting is not None:                                  # this very Undo: carried on now if it waits (claimed as
        if not _edition_take(self, waiting):                 # a look claims it), else it is under way elsewhere
            return _waits(_edition_change(self, {"undo": sid, "work": change.work_id}), why="it is under way")
        return self._edition_go(waiting)
    full = lambda rel: os.path.join(self.data_dir, _strip(rel))      # noqa: E731
    token = uuid.uuid4().hex[:8]
    parts, changed, epubs = [], 0, set()
    added = [i for i in getattr(change, "added", None) or () if isinstance(i, int)]
    back = [t for t in getattr(change, "removed_trash", None) or () if isinstance(t, int)]
    with self._reading():
        for n, swap in enumerate(change.swaps):
            item = self.conn.execute("SELECT rel_path, availability FROM items WHERE id = ?",
                                     (swap["item"],)).fetchone()
            if item is None:
                continue                                     # removed by the learner since: stays removed
            now = dict(self.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?",
                                         (swap["item"],)).fetchall())
            if item[0] != swap["rel"] or item[1] != "available" or \
                    any(now.get(k) != t for k, t in swap["after"].items()):
                changed += 1
                continue
            for text in list(swap["before"].values()) + list(swap["after"].values()):
                epub = str((_json_dict(text) or {}).get("origin") or "").rpartition("#")[0]
                if epub:
                    epubs.add(origin_key(epub)[len(SOURCE_KEY):])
            parts.append({"item": swap["item"], "rel": swap["rel"], "sha256": swap.get("old_sha256"),
                          "old_sha256": swap.get("sha256"), "part": swap["trash"],
                          "trash": _trash_name(swap["rel"], f"{token}u{n}"), "expect": dict(swap["after"]),
                          "write": {k: _row_text(v) for k, v in _declined(swap["before"], swap["after"]).items()}})
        rels = dict(self.conn.execute(f"SELECT id, rel_path FROM items WHERE id IN ({','.join('?' * len(added))})",
                                      added).fetchall()) if added else {}
    if changed:
        raise UndoRefused(f"{changed} part{'s' if changed != 1 else ''} of the book changed since its new edition came "
                          f"in; nothing was undone")
    if not parts and not rels and not back:
        return _edition_change(self, {"undo": sid or token})
    for p in parts:                                          # outside the lock: the old bytes, the new ones' sha256
        if not p["sha256"] or not _part_holds(full(p["part"]), p["sha256"]):
            raise UndoRefused("the old edition's text is no longer in the trash; nothing was undone")
        if not p["old_sha256"]:
            try:
                p["old_sha256"] = sha256_of(full(p["rel"]))
            except OSError:
                raise UndoRefused("a part of the book can't be read just now; nothing was undone - try again")
    if back and _edition_tail(self, back) is None:           # the parts past its end: each still in the trash
        raise UndoRefused(_TAIL_GONE)
    note = {"at": time.time(), "waiting": False, "undo": sid or token, "by": "undo", "work": change.work_id,
            "epubs": sorted(epubs), "parts": parts, "extras": [], "back": back,
            "surplus": [{"item": i, "rel": rels[i], "trash": _trash_name(rels[i], f"{token}a{n}")}
                        for n, i in enumerate(sorted(rels))]}
    key = EDITION_PENDING + token
    if not _edition_claim(self, key, note):
        raise UndoRefused("the book is switching to another edition just now; nothing was undone - try again after "
                          "the next look")
    return self._edition_go(key)


_TAIL_GONE = "the old edition's last parts are no longer in the trash; nothing was undone"


def _drop_last_switch(self, change):
    """LM3: a version's or an edition's last switch undone is no title's last switch any more (`last_switch` None)."""
    works = list(getattr(change, "switched_works", None) or ()) + \
        ([change.work_id] if getattr(change, "work_id", None) is not None else [])
    switch_id = getattr(change, "switch_id", None)
    if not works or switch_id is None:
        return
    try:
        with self._writing():
            for work_id in dict.fromkeys(works):
                row = self.conn.execute("SELECT value FROM meta WHERE key = ?",
                                        (LAST_SWITCH + str(work_id),)).fetchone()
                if row and (_json_dict(row[0]) or {}).get("id") == switch_id:
                    self.conn.execute("DELETE FROM meta WHERE key = ?", (LAST_SWITCH + str(work_id),))
    except StoreError:
        pass


def _declined(before, after):
    """LM3: the records a better version's (or a new edition's) Undo writes — as they were, the version it switched to
    kept a version marked `declined` with its bytes' sha256 (A4: a file only touched keeps it), so no look switches to
    it again while it holds those bytes (`sources.passed_over`; changed, it is judged again): a new edition's record
    kept so (its EPUB not split again until it changes), and an EPUB rewritten at its own path keeping the old text's
    sha256 and the file's new size and time, `declined` the new bytes' (A3: a touched file is never switched to)."""
    out = dict(before)
    for key, text in after.items():
        record = _json_dict(text) or {}
        if record.get("version"):
            continue                                 # the old text's record: `before` holds it as it was
        old = _json_dict(before.get(key)) if key in before else None
        if old is None:
            out[key] = dict(record, version=True, declined=record.get("sha256"))
        elif old.get("version"):                     # a version already (declined once: its file may have changed
            out[key] = dict({k: v for k, v in old.items() if k != "fit"},    # since) — declined as its bytes are now
                            **{k: record[k] for k in ("sha256", "size", "mtime_ns") if k in record},
                            declined=record.get("sha256"))
        else:                                        # A3: the same path's — the old text's sha, the file's stats
            out[key] = dict(old, size=record.get("size"), mtime_ns=record.get("mtime_ns"),
                            declined=record.get("sha256"))
    return out


def _store_last_switch(self, work_id):
    """The title's last switch, as the window says it ("Connect switched <show> to SubsB · 6 of 12 · Undo"; LM3's
    toast "6 of 12 episodes switched; 7–12 have no [B] subtitles") -> {"at", "by", "from", "to" (the groups' labels),
    "switched", "missing", "held" (counts), "missing_items", "held_items" (their item ids), "kind": "group" (LM2's,
    *Use [B]'s*) | "version" (LM3: a better version) | "edition" (a book's new edition)}, or None."""
    with self._reading():
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (LAST_SWITCH + str(work_id),)).fetchone()
    record = _json_dict(row[0]) if row else None
    if record is None:
        return None
    return {"at": record.get("at"), "by": record.get("by"), "from": record.get("from"), "to": record.get("to"),
            "kind": record.get("kind") or "group",
            **{k: len(record.get(k) or ()) for k in ("switched", "missing", "held")},
            **{f"{k}_items": [i for i in record.get(k) or () if isinstance(i, int)] for k in ("missing", "held")}}


def _store_undo_switch_of(self, work_id):
    """Undo of the title's last switch from its kept record (`last_switch`) — the window's way to Connect's switch,
    made in Connect's own process, after a restart too. -> the undo's Change, or None when there is none to undo."""
    with self._reading():
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (LAST_SWITCH + str(work_id),)).fetchone()
    record = _json_dict(row[0]) if row else None
    if record is None:
        return None
    change = Change(record.get("change") or "switch_group", record.get("epoch"), 0)
    change.work_id, change.swaps = work_id, list(record.get("swaps") or ())
    change.group_before, change.group_after = record.get("group_before"), record.get("group_after")
    change.switch_id, change.switched_works = record.get("id"), [work_id]
    change.edition = record.get("kind") == "edition"
    change.added, change.removed_trash = list(record.get("added") or ()), list(record.get("removed_trash") or ())
    return self._undo_switch(change)


# --- LM3: switch versions in place (PROVISIONAL, Sonic 2026-10-21: answer 3, LM-1a, T2-B6 A) ----------------------- #
# A better version later (`switch_versions`), a book's new edition (`switch_parts`) and *Use [B]'s subtitles*
# (`other_groups` + LM2's `switch_group`) all go through LM2's one swap path (`_switch`); hato's items count as a
# show's episodes in a look (`hato_items`).

def _store_hato_items(self):
    """LM3 (A9, LM1b deferred): the items whose text is hato's — its own drop, or a folder's episode its timed drop took over
    (K3 R2) — by the show folders of their titles: {a show's folder key: [Origin(item_id, None, <its file>, size,
    mtime_ns, None, rel_path, availability, paired_at, False, <hato's video>, video_size, <hato's key>)]}, so a look's
    "one episode per key per show" counts them (`sources._Look._held`). A title's show folders: its own folder key and
    its items' folders (`parent_folder`, as `show_groups` reads a merged title's) — never hato's drop folder. One read
    per look."""
    hato = path_key(HATO_FOLDER) + "/"
    with self._reading():
        rows = [r for r in self.conn.execute(
            f"SELECT i.id, i.work_id, i.rel_path, i.size, i.mtime_ns, i.availability, p.pairing, p.paired_at, "
            f"p.content_key FROM "
            f"pairings p JOIN items i ON i.id = p.item_id WHERE NOT {_ORIGIN_ROW} AND i.work_id IS NOT NULL "
            f"ORDER BY i.id, p.paired_at DESC") if is_hato(_json_dict(r[6]) or {})]   # (A8: not Connect's link)
        if not rows:
            return {}
        works, folders = sorted({r[1] for r in rows}), {}
        for chunk in _chunks(works, 500):
            marks = ",".join("?" * len(chunk))
            for work_id, fk in self.conn.execute(f"SELECT id, folder_key FROM works WHERE id IN ({marks}) AND "
                                                 f"folder_key IS NOT NULL", chunk):
                folders.setdefault(work_id, set()).add(fk)
            for work_id, folder in self.conn.execute(
                    f"SELECT DISTINCT work_id, parent_folder FROM items WHERE work_id IN ({marks}) AND parent_folder "
                    f"IS NOT NULL AND parent_folder != '' AND NOT (rel_key >= ? AND rel_key < ?)",
                    chunk + [hato, hato[:-1] + "0"]):
                folders.setdefault(work_id, set()).add(path_key(folder))
    out, seen = {}, set()
    for item_id, work_id, rel, size, mtime_ns, availability, text, paired_at, key in rows:
        if item_id in seen:                          # its newest record (hato's video)
            continue
        seen.add(item_id)
        record = _json_dict(text) or {}
        o = Origin(item_id, None, os.path.join(self.data_dir, *_strip(rel).split("/")), size, mtime_ns, None, rel,
                   availability, paired_at, False, record.get("video_path"), record.get("video_size"),
                   key)
        for fk in folders.get(work_id, ()):
            out.setdefault(fk, []).append(o)
    return out


def _store_switch_versions(self, item_ids, by=SOURCE_PRODUCER, stop=None):
    """LM3 (a), answer 3 (PROVISIONAL, to be checked in use): each item whose best version of its own text's group
    ranks above its text in the look's own order (the ONE rule: `sources.group_copies`, `sources.better` — a re-timed
    copy, `synced/`, the `.ass` over the `.srt`, our language's tag; never another group's: the show's group is LM2's;
    never a flagged or bilingual file; never on its name alone) takes it IN PLACE through LM2's one swap path
    (`_switch`: the bytes checked by their sha256 outside the lock, the old copy to the trash, SWITCH_BATCH a command,
    one Change): the item keeps its id, place and cards; its copy takes the version's bytes and name; the version's
    record becomes the item's (with its video), the old one a version. Never a version under 1/THIN of the copy's
    dialogue lines (A6, B4: `_thin_switch`, reading each file once and handing the version's bytes
    to the swap; remembered on its record by its sha256, `thin`, so it is read again only once its bytes changed); one
    whose original can't be read (a drive offline, A9) or whose copy is held is `held` — a later look tries it again,
    its verdict kept by both files (`fit`: no thin read while they are as judged), and nothing read at all while its
    copy is still held (asked first without moving it, `_free_to_move`). `stop()` is asked between
    candidates (a stopped look switches no more). The title's group record is never touched; each title switched keeps
    the switch as its last one (`last_switch`, kind "version", by `by`: the window's note and its Undo,
    `undo_switch`). -> the Change (kind `switch_version`; `switched_works`: the titles; `Store.undo` puts it back)."""
    from app import sources
    self.settle_switches()
    plans, held, works = [], [], {}
    with self._reading():
        for item_id in dict.fromkeys(item_ids):
            row = self.conn.execute("SELECT rel_path, availability, work_id, size, mtime_ns FROM items WHERE id = ?",
                                    (item_id,)).fetchone()
            copies = _group_copies(self, item_id) if row is not None else None
            if not isinstance(copies, tuple):
                continue
            picks, mine, best, rank, _origin = copies
            if mine not in best or not sources.better(best[mine][2], rank):
                continue
            key, record, _rank = best[mine]
            works[item_id] = row[2]
            plan = None if row[1] != "available" else _switch_plan(self, item_id, row[0], picks, key, record,
                                                                   keep_name=True)
            if plan is None:
                held.append(item_id)
                continue
            plan["fit"] = [record.get("sha256"), row[3], row[4]]
            plan["judged"] = record.get("fit") == plan["fit"]    # held before, judged on these very files
            plans.append(plan)
    ready, thin = [], []
    for plan in plans:
        if stop is not None and stop():
            break
        if plan["judged"] and not _free_to_move(os.path.join(self.data_dir, _strip(plan["rel"]))):
            held.append(plan["item"])                        # held last time and still: not read again
            continue
        if not plan["judged"]:
            verdict, data = _thin_switch(self, plan)
            if verdict:
                thin.append(plan)
                continue
            if data is not None:
                plan["data"] = data                          # (W3: the swap's bytes, never read twice)
        ready.append(plan)
    if thin:
        _passed_over(self, {p["key"]: p["sha256"] for p in thin}, "thin")
    change = self._switch("switch_version", by, None, ready, [], held, None)
    fits = {p["key"]: p["fit"] for p in ready if p["item"] in change.held and not p["judged"] and p["fit"][0]}
    if fits:                                                 # W2: a held switch is never judged again for nothing
        try:
            _passed_over(self, fits, "fit")
        except StoreError:                                   # (busy: judged once more at the next look)
            pass
    _note_last_switches(self, change, works, "version", by)
    return change


def _note_last_switches(self, change, works, kind, by, extra=None):
    """LM3 (IK-L3-3): each title a switch of `kind` ("version" | "edition") switched keeps it as its last switch
    (`LAST_SWITCH`, `change`: its Change kind) — the window's note "1 book updated to its new edition · Undo" reads it
    (`last_switch`), its Undo is `undo_switch(work)`; `change.switched_works` names the titles. One write; a busy store
    leaves the switch done, without the note."""
    by_work = {}
    for swap in change.swaps:
        by_work.setdefault(works.get(swap["item"]), []).append(swap)
    by_work.pop(None, None)
    change.switched_works = sorted(by_work)
    change.switch_id = uuid.uuid4().hex[:12]
    if not by_work:
        return
    values = {}
    for work_id, swaps in by_work.items():
        items = {s["item"] for s in swaps}
        values[LAST_SWITCH + str(work_id)] = _dumps(dict({
            "at": _now(), "by": by, "epoch": change.epoch, "kind": kind, "change": "switch_version",
            "id": change.switch_id, "from": None, "to": None, "group_before": None, "group_after": None,
            "switched": [i for i in change.switched if i in items],
            "missing": [], "held": [i for i in change.held if works.get(i) == work_id], "swaps": swaps},
            **(extra or {})))
    try:
        self.bookkeeping(values)
    except StoreError as e:
        print(f"Library store: a switch is done, its note for the window couldn't be written: {e!a}")


def _passed_over(self, marks, flag):
    """LM3: versions the switch passes over, remembered on their records (`flag`: `thin` — the version's sha256, as
    `sources.passed_over` reads it; `fit` — [its sha256, the copy's size, time]): no look reads them again until their
    bytes changed (S19). `marks` = {content key: value}."""
    with self._writing():
        for key, value in marks.items():
            row = self.conn.execute("SELECT pairing FROM pairings WHERE content_key = ?", (key,)).fetchone()
            record = _json_dict(row[0]) if row else None
            if record is None or value is None:
                continue
            record[flag] = value
            self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                              (json.dumps(record, sort_keys=True, ensure_ascii=False), key))
        self._copy_dirty()


def _thin_switch(self, plan):
    """A6 for a better version (outside the lock), each file read once -> (thin, the version's bytes or None): does the
    version hold under 1/THIN of the dialogue lines of the item's copy (`sources.dialogue_lines`) — a signs track the
    look would never have picked (B4: one with none is thin while the copy holds some; neither holding any — a text,
    not a subtitle — is no thin one)? The bytes go to the swap (`plan["data"]`, checked by their sha256 there). One
    that can't be read is not judged here (its swap holds it)."""
    from app import sources
    try:
        with open(plan["origins"][0], "rb") as f:
            new = f.read()
        with open(os.path.join(self.data_dir, _strip(plan["rel"])), "rb") as f:
            old = f.read()
    except OSError:
        return False, None
    lines = lambda data: sources.dialogue_lines(decode_text(data, self.language))      # noqa: E731
    return lines(new) * sources.THIN < lines(old), new


# --- a book's new edition: ONE change (LM3 fix round; PROVISIONAL, Kura / the lead 2026-10-22) ------------------- #
# One note for the whole edition (EDITION_PENDING): the kept parts' swaps, the extra parts' files and items, the parts
# past its end. Every new part's bytes are written to the data folder's trash first and checked by their sha256; what
# is done is read from the database, never from the note; a crash, a file held open or a failed write leaves the whole
# old edition or, once every new part is in, the whole new one — the next look (`settle_editions`) finishing it.

def _store_switch_parts(self, root_id, parts, extras=(), surplus=(), by=SOURCE_PRODUCER, rules=None, epub=None):
    """LM3 (c), T2-B6 A (PROVISIONAL, to be checked in use): a book's new edition switched WHOLE, as ONE change.
    `parts` = [{"item": the item that holds that part NUMBER of the book (A1: never by position), "data": the new
    edition's part (`sources.book_parts`), "origin": `<epub>#<n>`, "size", "mtime_ns", "sha256" (the EPUB's), "show",
    "episode"}]: each item keeps its id, place, cards and file name and takes the new part's bytes (the old copy to the
    trash, its Undo's); the new edition's record its own, the old edition's a version (the same path: rewritten).
    `extras` = [{... the same, "rel"}]: the new edition's parts the book has no item for — new items of the book (their
    file under a free name: a file there holding other bytes is never taken for the part, B1). `surplus` = [item ids]:
    the book's parts past the new edition's end — removed (their copies to the trash, Put back brings them).
    Outside the lock first: every item available (else `held`, nothing written: the look waits for a change, A7), the
    old copies' sha256, every new part's bytes staged in `.trash/`; then the note (EDITION_PENDING) and
    `_edition_go`. -> the Change (kind `switch_version`: `switched` the parts' items, `added` the extra parts' items,
    `removed` the surplus items; `waiting` True while the edition waits for a held file or a busy store — the next
    look's `settle_editions` finishes it; `switched_works`)."""
    self.settle_switches()
    change = _edition_change(self)
    token = uuid.uuid4().hex[:8]
    ids = [p["item"] for p in parts] + list(surplus)
    with self._reading():
        rows = {i: self.conn.execute("SELECT rel_path, availability, work_id FROM items WHERE id = ?",
                                     (i,)).fetchone() for i in ids}
        picks = {p["item"]: dict(self.conn.execute(
            f"SELECT p.content_key, p.pairing FROM pairings p WHERE p.item_id = ? AND {_ORIGIN_ROW} AND NOT "
            f"{_VERSION_ROW}", (p["item"],)).fetchall()) for p in parts}
        held = {p["item"]: self.conn.execute("SELECT pairing FROM pairings WHERE content_key = ? AND item_id = ?",
                                             (origin_key(p["origin"]), p["item"])).fetchone() for p in parts}
    out = [i for i in ids if rows[i] is None or rows[i][1] != "available"]
    if out or not parts:
        change.held = out or ids
        return change
    full = lambda rel: os.path.join(self.data_dir, _strip(rel))      # noqa: E731
    staged, planned, more = [], [], []
    try:
        for n, p in enumerate(parts):
            rel = rows[p["item"]][0]
            old = sha256_of(full(rel))                      # the old part's own bytes: its Undo's (B3)
            part = _trash_name(rel, f"{token}n{n}")
            _stage(self, part, p["data"])
            staged.append(part)
            write = {k: dict(_json_dict(t) or {}, version=True) for k, t in picks[p["item"]].items()}
            write[origin_key(p["origin"])] = _origin_record(root_id, os.path.abspath(p["origin"]), p)
            expect = dict(picks[p["item"]])
            if held[p["item"]] is not None:                  # (this EPUB's record on the part already: a declined
                expect.setdefault(origin_key(p["origin"]), held[p["item"]][0])   # edition's, rewritten)
            planned.append({"item": p["item"], "rel": rel, "sha256": hashlib.sha256(p["data"]).hexdigest(),
                            "old_sha256": old, "trash": _trash_name(rel, f"{token}o{n}"), "part": part,
                            "expect": expect, "write": {k: _row_text(v) for k, v in write.items()}})
        for n, x in enumerate(extras):
            sha = hashlib.sha256(x["data"]).hexdigest()
            rel, same = content_target(self.data_dir, x["rel"], len(x["data"]), sha)   # B1, S5: never another's bytes
            part = None
            if not same:
                part = _trash_name(rel, f"{token}x{n}")
                _stage(self, part, x["data"])
                staged.append(part)
            found = {k: x[k] for k in ("origin", "size", "mtime_ns", "sha256", "show", "episode", "chapter")
                     if k in x}
            more.append({"rel": rel, "part": part, "sha256": sha, "bytes": len(x["data"]),
                         "found": dict(found, rel=rel)})
    except OSError as e:                                     # an old part unreadable, the trash unwritable: waits
        for s in staged:
            _remove_quietly(full(s))
        print(f"Library store: a book's new edition waits (its files couldn't be read or written): {e!a}")
        change.held = [p["item"] for p in parts]
        return change
    try:
        _dumps(rules)
    except (TypeError, ValueError):
        rules = None
    note = {"at": time.time(), "waiting": False, "root": root_id, "by": by, "rules": rules, "epub": epub,
            "work": rows[parts[0]["item"]][2], "parts": planned, "extras": more,
            "surplus": [{"item": i, "rel": rows[i][0], "trash": _trash_name(rows[i][0], f"{token}s{n}")}
                        for n, i in enumerate(surplus)]}
    key = EDITION_PENDING + token
    claimed = False
    try:
        claimed = _edition_claim(self, key, note)
    finally:
        if not claimed:
            for s in staged:
                _remove_quietly(full(s))
    if not claimed:                                          # another switch of the book under way: it goes first
        change.held, change.waiting = ids, True
        return change
    return self._edition_go(key)


def _note_items(note):
    return {p.get("item") for p in list(note.get("parts") or ()) + list(note.get("surplus") or ())} - {None}


def _edition_claim(self, key, note):
    """The note written in one write — unless another note (an edition or its Undo) already holds one of its items:
    one change of a book at a time. -> True when written."""
    mine = _note_items(note)
    with self._writing():
        for (value,) in self.conn.execute("SELECT value FROM meta WHERE key >= ? AND key < ?",
                                          (EDITION_PENDING, EDITION_PENDING[:-1] + ";")).fetchall():
            if mine & _note_items(_json_dict(value) or {}):
                return False
        self._set_meta({key: _dumps(note)})
    return True


def _row_text(value):
    """A record as a step writes it (`_switch_step`): its text as stored, so what is done reads by value."""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)


def _stage(self, rel, data):
    """A new edition's part written to the data folder's trash (`rel`: `.trash/<name>`), whole and synced, its clock
    started: the bytes the switch takes, still there after a crash."""
    path = os.path.join(self.data_dir, _strip(rel))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    restart_trash_clock(path)


def _edition_change(self, note=None):
    meta = self.meta()
    undo = bool((note or {}).get("undo"))
    change = Change("undo" if undo else "switch_version", meta["epoch"], meta["state_version"])
    change.work_id = (note or {}).get("work")
    change.switched, change.missing, change.held, change.swaps, change.removed = [], [], [], [], []
    change.waiting, change.switched_works, change.removed_trash = False, [], []
    change.edition = not undo                                # (its Undo is `_undo_edition`)
    return change


def _edition_note(self, key):
    row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return _json_dict(row[0]) if row else None


def _edition_state(self, note):
    """(Inside a read.) What of the edition is done, read from the database (never from the note): {item: "new" |
    "old" | "changed"} of its parts (their records as the note will write them, as read, or anything else), the extra
    parts' origins recorded, the surplus items gone."""
    state = {}
    for p in note["parts"]:
        row = self.conn.execute("SELECT rel_path FROM items WHERE id = ?", (p["item"],)).fetchone()
        now = dict(self.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?",
                                     (p["item"],)).fetchall())
        if row is None or row[0] != p["rel"]:
            state[p["item"]] = "changed"
        elif all(now.get(k) == t for k, t in p["write"].items()):
            state[p["item"]] = "new"
        elif all(now.get(k) == t for k, t in p["expect"].items()) and \
                not any(k in now for k in p["write"] if k not in p["expect"]):
            state[p["item"]] = "old"
        else:
            state[p["item"]] = "changed"
    taken = {x["rel"] for x in note["extras"] if self.conn.execute(
        "SELECT 1 FROM pairings WHERE content_key = ?", (origin_key(x["found"]["origin"]),)).fetchone()}
    gone = {s["item"] for s in note["surplus"] if not self.conn.execute(
        "SELECT 1 FROM items WHERE id = ?", (s["item"],)).fetchone()}
    return state, taken, gone


def _edition_steps(self, plans, kind, by, touch=None):
    """The parts' swaps through LM2's one step (`_switch_step`, SWITCH_BATCH a command: a 60-part book in one command
    held the write lock ~195 ms, in steps of 3 ~35–49 ms each — measured 2026-10-22), each part's new bytes taken from
    its staged file and put back there if the step fails (`keep_part`); `touch()` before each step (the note's time
    renewed). -> (the items swapped, the items held)."""
    scratch = _edition_change(self)
    for i in range(0, len(plans), SWITCH_BATCH):
        if touch is not None:
            touch()
        chunk = [dict(p) for p in plans[i:i + SWITCH_BATCH]]
        self._switch_step(kind, by, None, chunk, uuid.uuid4().hex[:8], scratch, None, None, False, False,
                          None, None, keep=False)
        if scratch.held:
            break
    return scratch.switched, scratch.held


def _edition_unswap(self, note, kind, by, touch=None):
    """Every part of the edition (or of its Undo) that took its new bytes back to the bytes it had (the new bytes back
    to their staged file, the old copy back from the trash, the records as read): the whole book as it was. -> the
    parts that couldn't go back (held open meanwhile: they stay; the next look finishes it forward)."""
    full = lambda rel: os.path.join(self.data_dir, _strip(rel))      # noqa: E731
    with self._reading():
        state, _taken, _gone = _edition_state(self, note)
    plans = [{"item": p["item"], "rel": p["rel"], "to_rel": p["rel"], "sha256": p["old_sha256"], "origins": [],
              "expect": p["write"], "write": p["expect"], "part": full(p["trash"]), "trash": p["part"],
              "keep_part": True} for p in note["parts"] if state[p["item"]] == "new"]
    if not plans:
        return []
    _swapped_back, held = _edition_steps(self, plans, kind, by, touch)
    if held:
        print(f"Library store: {len(held)} part(s) of a book couldn't go back yet; the next look finishes the change")
    return held


def _edition_wait(self, key, note, held=()):
    """The edition (or its Undo) waits for the next look (`settle_editions`): its note marked so, the files held
    named."""
    note = dict(note, waiting=True, at=time.time(), held=sorted(set(held)))
    try:
        self.bookkeeping({key: _dumps(note)})
    except StoreError:                                       # it goes stale and is taken up the same way
        pass


def _edition_touch(self, key, note, at):
    """A running edition's (or Undo's) note gets its time renewed — at most every SWITCH_STALE_S / 4 — so another
    process's `settle_editions` never takes it for a crashed one while it works: its time only, the rest of the note as
    the store holds it (never another runner's waiting mark, held files or tries put back from this runner's own
    copy). -> the time the note holds."""
    now = time.time()
    if now - at < SWITCH_STALE_S / 4:
        return at
    try:
        with self._writing():
            stored = _edition_note(self, key)
            if stored is None:
                return at
            self._set_meta({key: _dumps(dict(stored, at=now))})
    except StoreError:                                       # busy: renewed at the next step
        return at
    return now


def _edition_due(note, now=None):
    """A note no runner carries: left waiting, or a crashed one's (its time not renewed for SWITCH_STALE_S)."""
    return note is not None and bool(note.get("waiting") or
                                     (now or time.time()) - float(note.get("at") or 0) > SWITCH_STALE_S)


def _edition_take(self, key, now=None):
    """An edition's (or its Undo's) note claimed by one runner, in ONE write: still due as read inside the write
    (`_edition_due`) and no swap step under way (a crashed one is put back first, `settle_switches`) → marked carried
    (`waiting` False, its time now). -> True when this runner carries it; else another does, or must first."""
    with self._writing():
        note = _edition_note(self, key)
        if not _edition_due(note, now):
            return False
        if self.conn.execute("SELECT COUNT(*) FROM meta WHERE key >= ? AND key < ? AND NOT (key >= ? AND key < ?)",
                             (SWITCH_PENDING, SWITCH_PENDING[:-1] + ";", EDITION_PENDING,
                              EDITION_PENDING[:-1] + ";")).fetchone()[0]:
            return False
        self._set_meta({key: _dumps(dict(note, waiting=False, at=time.time()))})
    return True


def _edition_unfinished(self, key, note, change):
    """(Inside a write.) The backstop before a note goes: a part not reading its target state (another runner put it
    back meanwhile) → the note written back waiting (the title's last switch untouched), the next look finishes it.
    -> the waiting Change, or None when every part reads its target."""
    state, _taken, _gone = _edition_state(self, note)
    if all(s == "new" for s in state.values()):
        return None
    print("Library store: a book's change found a part not done as it ended; the next look finishes it")
    self._set_meta({key: _dumps(dict(note, waiting=True, at=time.time()))})
    return _waits(change, why="it is under way")


def _waits(change, held=(), why="a file of the book is open elsewhere"):
    """The Change of an edition (or its Undo) left waiting for the next look: its held items, and an Undo says so."""
    change.held, change.waiting = sorted(set(held)), True
    if change.kind == "undo":
        change.notes.append(f"the Undo waits ({why}); the next look finishes it")
    return change


def _free_to_move(path):
    """Is the file free to move (not held open)? Asked without moving it: Windows opens it for deletion, sharing
    everything — refused while another program holds it without sharing deletion, as a move would be. Elsewhere a
    file held open moves anyway: free."""
    if not os.path.isfile(path):
        return True
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                       wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    # DELETE access; share read | write | delete; OPEN_EXISTING
    handle = create(os.path.abspath(path), 0x00010000, 0x7, None, 3, 0, None)
    if handle is None or handle == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error() not in (5, 32, 33)   # denied, shared, locked: held; anything else the move tells
    kernel32.CloseHandle(handle)
    return True


EDITION_TRIES = 3    # looks an extra part's failing move may wait before the edition finishes without it


def _unheld_name(self, rel):
    """A name for an extra part given up: `rel` itself, else `name (2).ext`, … — the first with no file AND no row
    holding it (a learner's item whose copy is missing keeps its name: never taken in onto it)."""
    base, ext = os.path.splitext(rel)
    n = 1
    while True:
        candidate = rel if n == 1 else f"{base} ({n}){ext}"
        n += 1
        if not os.path.lexists(os.path.join(self.data_dir, _strip(candidate))) and self.item_id(candidate) is None:
            return candidate


def _given_up(extras, aside):
    """The note's extra parts with those given up (`aside`: their origins) marked so: their staged file kept (on the
    trash list, or in the trash), never moved in nor deleted by a later look."""
    return [dict(x, part=None, given_up=True) if os.path.abspath(x["found"]["origin"]) in aside else x for x in extras]


def _give_up(self, key, took, aside, by):
    """(Inside the take-in's write.) The extra parts given up sent to the trash list at once — only the items this
    take-in itself added (never a learner's item it attached an origin to), each trash row naming its staged file — and
    the stored note marking them given up: all in the one write, so a crash keeps none of it or all of it."""
    added = set(getattr(took, "added", None) or ())
    recorded = getattr(took, "recorded", None) or {}
    ids = {recorded[o]: p for o, p in aside.items() if recorded.get(o) in added}
    if ids:
        self.remove(sorted(ids), trashed_paths=ids, by=by, exclude=False, why="edition")
    stored = _edition_note(self, key)
    if stored is not None:
        self._set_meta({key: _dumps(dict(stored, extras=_given_up(stored["extras"], aside)))})


def _edition_tail(self, back):
    """An edition's Undo: the files of the parts past the edition's end (`back`: their trash rows) — [their paths]
    when each is still in the trash (a row put back already, or one with no file, needs none) or already back at its
    library name with no item holding it (moved back by an Undo killed before its restore: the restore finishes it);
    None when one is gone (its row deleted, its file purged)."""
    rows = {r["id"]: r for r in self.trash_rows(back)} if back else {}
    if any(t not in rows for t in back):
        return None
    files = []
    for r in rows.values():
        if r["restored_at"] or not r["trashed_path"]:
            continue
        f = os.path.join(self.data_dir, _strip(r["trashed_path"]))
        if os.path.isfile(f):
            files.append(f)
        elif not (os.path.isfile(os.path.join(self.data_dir, _strip(r["rel_path"])))
                  and self.item_id(r["rel_path"]) is None):
            return None
    return files


def _store_edition_go(self, key):
    """Carry a book's new edition — or its Undo (a note marked `undo`, `_undo_edition`) — (its note `key`) as far as it
    goes: forward when every part not switched yet still holds the records as read and its staged bytes (else every
    part goes back, the note dropped: the next look judges the book again), the files held last time free first
    (`_free_to_move`). The parts' swaps a step at a time (the note's time renewed as it works, `_edition_touch`); a part
    held → every part back (`_edition_unswap`): the whole book as it was, the change waits. Then the parts past its end
    (an Undo: the parts the edition added) in ONE removal (their copies to the trash first; any failing → moved back,
    every part back, waits). Then an Undo's parts past the edition's end put back in ONE restore, an edition's extra
    parts in ONE take-in (busy → waits: forward next look; one that can never go in — its name taken meanwhile gets a
    free one, the source no longer read, a move failing EDITION_TRIES looks — is left out, said in the notes: never a
    wait for ever). Done: in ONE write the note goes and the title's last switch is this edition (`last_switch`, kind
    "edition") — or, an Undo, is gone. -> the Change."""
    with self._reading():
        note = _edition_note(self, key)
    change = _edition_change(self, note)
    if note is None:
        return change
    undo = bool(note.get("undo"))
    kind, by = ("undo", "undo") if undo else ("switch_version", note.get("by") or SOURCE_PRODUCER)
    full = lambda rel: os.path.join(self.data_dir, _strip(rel))      # noqa: E731
    clock = [float(note.get("at") or 0)]

    def touch():
        clock[0] = _edition_touch(self, key, note, clock[0])
    with self._reading():
        state, taken, gone = _edition_state(self, note)
    items = [p["item"] for p in note["parts"]]
    old = [p for p in note["parts"] if state[p["item"]] == "old"]
    if "changed" in state.values() or not all(_part_holds(full(p["part"]), p["sha256"]) for p in old):
        held = _edition_unswap(self, note, kind, by, touch)  # changed meanwhile (the learner's): judged again
        if held:
            _edition_wait(self, key, note, held)
        else:
            _edition_drop(self, key, note)
        change.held = items
        if undo:
            change.notes.append("the book changed since; nothing was undone")
        return change
    if undo and all(s == "old" for s in state.values()) and not gone:    # an Undo claimed, nothing of it done yet:
        tail = _edition_tail(self, note.get("back") or [])               # what it puts back still in the trash, each
        if tail is None:                                                 # file's 30 days counted from now
            _edition_drop(self, key, note)
            change.notes.append(_TAIL_GONE)
            return change
        for path in tail + [full(p["part"]) for p in note["parts"]]:
            restart_trash_clock(path)
    for i in note.get("held") or ():
        rel = next((p["rel"] for p in note["parts"] + note["surplus"] if p["item"] == i), None)
        if rel is not None and not _free_to_move(full(rel)):
            _edition_wait(self, key, note, note["held"])
            return _waits(change, note["held"])
    plans = [{"item": p["item"], "rel": p["rel"], "to_rel": p["rel"], "sha256": p["sha256"], "origins": [],
              "expect": p["expect"], "write": p["write"], "part": full(p["part"]), "trash": p["trash"],
              "keep_part": True} for p in old]
    try:
        _done, held = _edition_steps(self, plans, kind, by, touch) if plans else ([], [])
    except Exception as e:                                   # a step failing: its own moves were put back
        print(f"Library store: a book's new edition stopped switching ({e!a}); it goes back whole and waits")
        held = [p["item"] for p in old]
    if held:
        still = _edition_unswap(self, note, kind, by, touch)
        _edition_wait(self, key, note, held + still)
        return _waits(change, held)
    left = [s for s in note["surplus"] if s["item"] not in gone]
    moved, failing = [], None
    try:
        if left:
            touch()
        for s in left:
            failing = s["item"]
            if os.path.isfile(full(s["trash"])) and not os.path.exists(full(s["rel"])):
                moved.append(s)                              # (moved before a crash)
                continue
            if not os.path.isfile(full(s["rel"])):
                continue                                     # its copy gone already: the row goes alone
            if trash_file(self.data_dir, s["rel"], to=s["trash"]) is None:
                raise OSError(f"not Surasura's to move: {s['rel']}")
            moved.append(s)
        failing = None
        if left:
            self.remove([s["item"] for s in left], trashed_paths={s["item"]: s["trash"] for s in moved}, by=by,
                        exclude=False, why="edition")
    except Exception as e:                                   # held open (B2), or the store failing (S3): back whole
        print(f"Library store: a book's part couldn't be taken out ({e!a}); the change waits")
        for s in moved:
            _switch_back(full(s["trash"]), full(s["rel"]))
        still = _edition_unswap(self, note, kind, by, touch)
        _edition_wait(self, key, note, ([failing] if failing is not None else []) + still)
        return _waits(change, [failing] if failing is not None else [])
    if note.get("back") and not _edition_put_back(self, key, note, change):
        return change
    found, lost, aside = [], [], {}      # aside: {origin: the staged file} — given up: taken in and removed in one write
    tries = int(note.get("tries") or 0) + 1
    for x in note["extras"]:
        if x["rel"] in taken:
            continue
        if x.get("given_up"):                                # on the trash list already (a crash before the end)
            lost.append(x["rel"])
            continue
        at = full(x["rel"])
        if os.path.isfile(at) and _part_holds(at, x["sha256"]):
            found.append(x["found"])
            continue
        part = full(x["part"]) if x.get("part") else None
        rel = None
        try:
            size = x.get("bytes") or (os.path.getsize(part) if part and os.path.isfile(part) else None)
            rel, same = content_target(self.data_dir, x["rel"], size, x["sha256"])   # a name taken meanwhile: a free
            if not same:                                     # one (never another's bytes taken for the part)
                if part is None or not _part_holds(part, x["sha256"]):
                    print(f"Library store: a new edition's part is lost before it went in ({x['rel']!a}): left out")
                    lost.append(x["rel"])
                    continue
                os.makedirs(os.path.dirname(full(rel)), exist_ok=True)
                rename_no_overwrite(part, full(rel))
        except OSError as e:
            if tries < EDITION_TRIES:
                print(f"Library store: a new edition's part waits ({x['rel']!a}): {e!a}")
                _edition_wait(self, key, dict(note, tries=tries))
                return _waits(change, why="a new part couldn't be written yet")
            print(f"Library store: a new edition's part couldn't go in after {tries} looks ({x['rel']!a}): left out, "
                  f"in the trash to put back")
            lost.append(x["rel"])
            if rel is not None and part is not None and _part_holds(part, x["sha256"]):
                aside[os.path.abspath(x["found"]["origin"])] = x["part"]     # its row taken in at a free name and
                found.append(dict(x["found"], rel=_unheld_name(self, rel)))  # removed at once: Put back brings it in
            continue
        found.append(dict(x["found"], rel=rel))
    if found:
        touch()
        took = None
        try:
            with self._writing():        # ONE write: the parts taken in, the given-up ones' removal and their mark
                took = self.take_in(note["root"], found, rules=note.get("rules"))
                if aside:
                    _give_up(self, key, took, aside, by)
        except StoreBusy as e:                               # busy (S1): the next look takes them in
            print(f"Library store: a new edition's extra parts wait for the next look: {e!a}")
            _edition_wait(self, key, note)
            return _waits(change, why="the library was busy")
        except Exception as e:                               # a short failure waits; the source no longer read, or
            if not isinstance(e, NotASource) and tries < EDITION_TRIES:      # failing EDITION_TRIES looks: never a
                print(f"Library store: a new edition's extra parts wait ({e!a})")                  # wait for ever
                _edition_wait(self, key, dict(note, tries=tries))
                return _waits(change, why="a new part couldn't be taken in yet")
            print(f"Library store: a new edition's extra parts can't go in ({e!a}): left out")
            lost += [f["rel"] for f in found if os.path.abspath(f["origin"]) not in aside]
            for f in found:
                if os.path.abspath(f["origin"]) in aside:
                    continue                                 # its staged file stays in the trash
                try:
                    trash_file(self.data_dir, f["rel"])
                except OSError:
                    pass
        for rel in getattr(took, "unused", None) or ():
            try:
                trash_file(self.data_dir, rel)
            except OSError:
                pass
        for p in aside.values():
            restart_trash_clock(full(p))
    if aside:                                                # the staged files given up stay (in the trash)
        note = dict(note, extras=_given_up(note["extras"], aside))
    if lost:
        change.notes.append(f"{len(lost)} new part{'s' if len(lost) != 1 else ''} of the book couldn't go in")
    if undo:
        return _undo_done(self, key, note, change)
    return _edition_done(self, key, note, change)


def _edition_put_back(self, key, note, change):
    """An edition's Undo, its last step: the parts past the edition's end put back (their files from the trash, their
    rows as they were: ONE restore). Busy → the Undo waits (forward next look: what is put back reads from the trash
    rows). Anything else (a part purged meanwhile) → said in its notes, the Undo done. -> True when it goes on."""
    try:
        rows = [r for r in self.trash_rows(note["back"]) if not r["restored_at"]]
        rel_paths = {}
        for r in rows:
            if r["trashed_path"]:
                rel, _why = put_back(self.data_dir, r["trashed_path"], r["rel_path"])
                if rel is not None and rel != r["rel_path"]:
                    rel_paths[r["id"]] = rel
        if rows:
            self.restore([r["id"] for r in rows], rel_paths, by="undo", kind="undo")
    except StoreBusy as e:
        print(f"Library store: an edition's Undo waits to put its parts back: {e!a}")
        _edition_wait(self, key, note)
        _waits(change, why="the library was busy")
        return False
    except (OSError, StoreError) as e:
        change.notes.append(f"the book's parts past the new edition's end couldn't all be put back ({e})")
    return True


def _edition_drop(self, key, note):
    """The note dropped and its staged files with it (nothing of the edition left in; an Undo's own staged files are
    the old edition's copies in the trash: kept)."""
    full = lambda rel: os.path.join(self.data_dir, _strip(rel))      # noqa: E731
    try:
        with self._writing():
            self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
    except StoreError:
        return
    if note.get("undo"):
        return
    for p in note["parts"]:
        _remove_quietly(full(p["part"]))
    for x in note["extras"]:
        if x.get("part"):
            _remove_quietly(full(x["part"]))


def _edition_done(self, key, note, change):
    """The whole new edition is in: in ONE write the note goes and the title's last switch is this edition (its swaps
    rebuilt from the note, with each new part's sha256 for its Undo; the extra parts' items, the surplus items' trash
    rows), the staged files left removed — only once every part reads the new edition (`_edition_unfinished`)."""
    full = lambda rel: os.path.join(self.data_dir, _strip(rel))      # noqa: E731
    swaps = [{"item": p["item"], "rel": p["rel"], "to_rel": p["rel"], "trash": p["trash"], "before": p["expect"],
              "after": p["write"], "old_sha256": p["old_sha256"], "sha256": p["sha256"]} for p in note["parts"]]
    switched = [p["item"] for p in note["parts"]]
    removed = [s["item"] for s in note["surplus"]]
    with self._writing():
        unfinished = _edition_unfinished(self, key, note, change)
        if unfinished is not None:
            return unfinished
        added = []
        for x in note["extras"]:
            row = self.conn.execute("SELECT item_id FROM pairings WHERE content_key = ?",
                                    (origin_key(x["found"]["origin"]),)).fetchone()
            if row is not None:
                added.append(row[0])
        trash_ids = [r[0] for r in self.conn.execute(
            f"SELECT MAX(id) FROM trash WHERE restored_at IS NULL AND item_id IN ({','.join('?' * len(removed))}) "
            f"GROUP BY item_id", removed)] if removed else []
        self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        change.switch_id = uuid.uuid4().hex[:12]
        if note.get("work") is not None:
            self._set_meta({LAST_SWITCH + str(note["work"]): _dumps({
                "at": _now(), "by": note.get("by"), "epoch": change.epoch, "kind": "edition",
                "change": "switch_version", "id": change.switch_id, "from": None, "to": None, "group_before": None,
                "group_after": None, "switched": switched, "missing": [], "held": [], "swaps": swaps,
                "added": added, "removed": removed, "removed_trash": trash_ids})})
    for p in note["parts"]:
        _remove_quietly(full(p["part"]))
    for x in note["extras"]:
        if x.get("part"):
            _remove_quietly(full(x["part"]))
    change.switched, change.swaps, change.added, change.removed = switched, swaps, added, removed
    change.removed_trash = trash_ids
    change.switched_works = [note["work"]] if note.get("work") is not None else []
    return change


def _undo_done(self, key, note, change):
    """An edition's Undo is whole (every part back, its added parts out, the parts past its end back): in ONE write
    its note goes and so does the title's last switch it undid — only once every part reads the old edition
    (`_edition_unfinished`). -> the Change (`switched`: the parts put back)."""
    with self._writing():
        unfinished = _edition_unfinished(self, key, note, change)
        if unfinished is not None:
            return unfinished
        self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        if note.get("work") is not None:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?",
                                    (LAST_SWITCH + str(note["work"]),)).fetchone()
            if row and (_json_dict(row[0]) or {}).get("id") == note.get("undo"):
                self.conn.execute("DELETE FROM meta WHERE key = ?", (LAST_SWITCH + str(note["work"]),))
    change.switched = [p["item"] for p in note["parts"]]
    change.removed = [s["item"] for s in note["surplus"]]
    return change


def _store_settle_editions(self, now=None):
    """LM3: the books' new editions left waiting (a file held, the store busy) or by a crash (a note older than
    SWITCH_STALE_S) carried on (`_edition_go`) — each claimed first in a write (never two processes at one), a crashed
    swap step's files put back before (`settle_switches`), none while another process's step is under way. A failure
    is logged and the note kept for the next look (marked waiting only when this look claimed it). -> [the Changes]."""
    rows = self.conn.execute("SELECT key, value FROM meta WHERE key >= ? AND key < ?",
                             (EDITION_PENDING, EDITION_PENDING[:-1] + ";")).fetchall()
    if not rows:
        return []
    self.settle_switches(now)
    steps = self.conn.execute("SELECT COUNT(*) FROM meta WHERE key >= ? AND key < ? AND NOT (key >= ? AND key < ?)",
                              (SWITCH_PENDING, SWITCH_PENDING[:-1] + ";", EDITION_PENDING,
                               EDITION_PENDING[:-1] + ";")).fetchone()[0]
    if steps:
        return []                                            # a step under way elsewhere: the next look
    out = []
    for key, value in rows:
        if not _edition_due(_json_dict(value), now):
            continue
        taken = False
        try:
            taken = _edition_take(self, key, now)
            if not taken:
                continue
            out.append(self._edition_go(key))
        except Exception as e:
            print(f"Library store: a book's new edition couldn't be finished (the next look tries again): {e!a}")
            if not taken:                                    # its own claim failed (busy): the note is another's, or
                continue                                     # stays as it was — never marked waiting by this look
            try:
                with self._writing():
                    note = _edition_note(self, key)
                    if note is not None:
                        self._set_meta({key: _dumps(dict(note, waiting=True))})
            except Exception:
                pass
    return out


def _store_pending_editions(self):
    """The EPUBs (their keys as the look gives them) whose new edition — or its Undo: each EPUB its records name — is
    still waiting: never hashed nor split again while their note stands (`settle_editions` carries it)."""
    rows = self.conn.execute("SELECT value FROM meta WHERE key >= ? AND key < ?",
                             (EDITION_PENDING, EDITION_PENDING[:-1] + ";")).fetchall()
    out = set()
    for n in (_json_dict(v) for (v,) in rows):
        if n:
            out.update(([n["epub"]] if n.get("epub") else []) + list(n.get("epubs") or ()))
    return out


def _store_other_groups(self, work_id):
    """LM3 (b), *Use [B]'s subtitles* on a show's ⋯ (A27; Mado builds the entry and its toast): each subtitle group of
    the title but its own (its recorded group, LM2; else its episodes' commonest) -> [{"group": [tag, name], "label":
    as a learner reads it, "episodes": how many of the title's episodes have that group's copy (its text or a version
    the switch would take), "of": the title's episodes (hato's included)}], best first in the look's order (its best
    copy's rank, then the most episodes, then the label); [] when there is none or no such title. The entry calls
    `switch_group(work, group, by="user")`; `last_switch` says what it did."""
    from app import sources
    with self._reading():
        if not self.conn.execute("SELECT 1 FROM works WHERE id = ?", (work_id,)).fetchone():
            return []
        own = _group_value((_groups_read(self).get(str(work_id)) or {}).get("group"))
        of, found, picked = 0, {}, {}
        for (item_id,) in self.conn.execute("SELECT id FROM items WHERE work_id = ? ORDER BY id",
                                            (work_id,)).fetchall():
            copies = _group_copies(self, item_id)
            if copies is None:
                continue
            of += 1
            if copies == "hato":
                continue
            _picks, mine, best, rank, origin = copies
            have = {g: (r, record["origin"]) for g, (_k, record, r) in best.items()}
            if is_content_name(os.path.basename(origin)):    # (A9: a waiting item's video is no subtitle group)
                picked[mine] = picked.get(mine, 0) + 1
                have.setdefault(mine, (rank, origin))
            for group, (r, path) in have.items():
                entry = found.setdefault(group, {"rank": r, "label": sources.group_label(os.path.basename(path)),
                                                 "episodes": 0})
                entry["episodes"] += 1
                if tuple(r[:-1]) < tuple(entry["rank"][:-1]):
                    entry["rank"] = r
    if own is None and picked:
        own = list(max(picked, key=lambda g: (picked[g], g)))
    out = [(e["rank"][:-1], -e["episodes"], e["label"], g, e) for g, e in found.items() if list(g) != own]
    return [{"group": list(g), "label": e["label"], "episodes": e["episodes"], "of": of}
            for _r, _n, _l, g, e in sorted(out, key=lambda x: x[:3])]


Store.show_groups = _store_show_groups
Store._note_groups = _store_note_groups
Store._carry_group = _carry_group
Store.group_of = _store_group_of
Store.keep_group = _store_keep_group
Store.other_subtitles = _store_other_subtitles
Store.switch_group = _store_switch_group
Store._switch = _store_switch
Store._switch_step = _store_switch_step
Store.settle_switches = _store_settle_switches
Store._undo_switch = _store_undo_switch
Store.last_switch = _store_last_switch
Store.undo_switch = _store_undo_switch_of
Store.hato_items = _store_hato_items
Store.switch_versions = _store_switch_versions
Store.switch_parts = _store_switch_parts
Store._edition_go = _store_edition_go
Store.settle_editions = _store_settle_editions
Store.pending_editions = _store_pending_editions
Store.other_groups = _store_other_groups

Store._copy_dirty = _store_copy_dirty
Store._not_a_source = _store_not_a_source
Store.add_source = _store_add_source
Store.sources = _store_sources
Store.stop_source = _store_stop_source
Store.join_moved = _store_join_moved
Store.source_detail = _store_source_detail
Store.origins = _store_origins
Store.excluded = _store_excluded
Store.items_of_size = _store_items_of_size
Store.keep_hashes = _store_keep_hashes
Store._keep_hash = _store_keep_hash
Store.origin_videos = _store_origin_videos
Store.item_of_video_key = _store_item_of_video_key
Store.items_holding = _store_items_holding
Store._twin_seen = _store_twin_seen
Store._twin_stamp = _store_twin_stamp
Store._video_holder = _store_video_holder
Store._twin_now = _store_twin_now
Store._still_twin = _store_still_twin
Store._sync_drop = _store_sync_drop
Store._take_out = _store_take_out
Store._waiting_video = _store_waiting_video
Store.update_origin = _store_update_origin
Store.update_origins = _store_update_origins
Store.copies_back = _store_copies_back
Store._exclude_origins = _store_exclude_origins
Store._let_origins_back = _store_let_origins_back
Store._removed_rows = _store_removed_rows
Store.removed = _store_removed
Store.note_emptied = _store_note_emptied
Store.emptied = _store_emptied
Store.removed_under = _store_removed_under
Store.removed_for = _store_removed_for
Store._read_sources = _store_read_sources
Store.skipped_folders = _store_skipped_folders
Store.skip_refused = _store_skip_refused
Store.items_under = _store_items_under
Store.skip_choices = _store_skip_choices
Store._holds_others = _store_holds_others
Store.skip_folder = _store_skip_folder
Store._unskip = _store_unskip
Store._skips_moved = _store_skips_moved
Store.read_folder_again = _store_read_folder_again
Store.take_in = _store_take_in
Store._write_origin = _store_write_origin
Store._take_version = _store_take_version
Store._mark_moved = _store_mark_moved
Store.origins_back = _store_origins_back
Store._take_new = _store_take_new
Store._waiting_videos = _store_waiting_videos
Store._fill_gap = _store_fill_gap
Store._as_versions = _store_as_versions
Store._source_work = _store_source_work
Store._source_spot = _store_source_spot
Store._in_run = _store_in_run
Store._episodes_of = _store_episodes_of


# --- audiobooks (Hon, 3.0 E2; H-6…H-8 PROVISIONAL): `app/audiobooks.py` finds and pairs, `sources` takes them in ---- #
# An audiobook is ONE item waiting for Anki Miner (`source_type` 'audio', availability 'waiting': no file made, never
# counted, never Generate's or the mine line's), its origin record keyed by its first file and holding `"audiobook"`
# (`audiobooks.record`: its files in order, length, chapters; `book` once paired, `ask` while H-8's question is open).
# Paired, it is a row of the book's title after the book's last part (H-6). The answers live in meta (one JSON value,
# the copy carries it): {answer key: true / false}; a *No* sets AUDIOBOOKS_STALE so the next look weighs the lone
# audiobooks again (the next book, or none). No table, no schema: taking the key out of the records undoes it all.
AUDIOBOOK_ANSWERS = "audiobook_answers"
AUDIOBOOKS_STALE = "audiobooks_stale"


def _store_audiobook_rows(self, item_id=None):
    """[(content_key, item_id, record)] of the live origins holding an audiobook (`item_id`: that item's only)."""
    sql = (f"SELECT p.content_key, p.item_id, p.pairing FROM pairings p WHERE {_LIVE_ORIGIN} AND "
           f"json_valid(p.pairing) AND json_type(p.pairing, '$.audiobook') = 'object'")
    rows = self.conn.execute(sql + " AND p.item_id = ?", (item_id,)) if item_id is not None else self.conn.execute(sql)
    return [(k, i, _json_dict(t) or {}) for k, i, t in rows]


def _store_audiobooks(self, every=False):
    """[{item_id, key, audiobook}] of every audiobook item, one each (its first live record: an item holding the same
    audiobook from two sources keeps them alike, `pair_audiobook`) — what a look weighs again (one read); `every`: each
    live record (a6: an item's files in each source, its transcript's claim found by any of them)."""
    with self._reading():
        out = {}
        for k, i, r in self._audiobook_rows():
            out.setdefault(k if every else i, {"item_id": i, "key": k, "audiobook": r["audiobook"]})
        return list(out.values())


def _store_audiobook_answers(self):
    """H-8's answers: {answer key (`audiobooks.answer_key`): True (the same book) / False}."""
    with self._reading():
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (AUDIOBOOK_ANSWERS,)).fetchone()
    said = _json_dict(row[0]) if row else None
    return {k: v for k, v in (said or {}).items() if isinstance(v, bool)}


def _store_audiobook_asks(self):
    """H-8's open questions, for *Needs you*: [{item_id, key, title, files, seconds, book: {title, epub, item}}] — an
    audiobook item whose record asks, still in the library."""
    out, asked = [], set()
    with self._reading():
        for _k, item_id, rec in self._audiobook_rows():
            ab = rec.get("audiobook") or {}
            ask = ab.get("ask")
            if item_id in asked:                         # one question an item (its copy in another source: the same)
                continue
            asked.add(item_id)
            if isinstance(ask, dict) and ask.get("key") and \
                    self.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
                out.append({"item_id": item_id, "key": ask["key"], "title": ab.get("title") or "",
                            "files": list(ab.get("files") or ()), "seconds": ab.get("seconds"),
                            "book": {"title": ask.get("title") or "", "epub": ask.get("epub"),
                                     "item": ask.get("item")}})
    return out


def _store_audiobook_place(self, book):
    """(work, tier, its last part's id) of the book an audiobook reads — its EPUB's live parts (`<epub>#<n>`), else the
    part the pairing named — or None (the book is gone, or waits)."""
    ids = set()
    epub = book.get("epub")
    if isinstance(epub, str) and epub:
        lo = SOURCE_KEY + path_key(os.path.abspath(epub)) + "#"
        ids = {r[0] for r in self.conn.execute(f"SELECT p.item_id FROM pairings p WHERE p.content_key >= ? AND "
                                               f"p.content_key < ? AND {_LIVE_ORIGIN}", (lo, lo[:-1] + "$"))}
    if not ids and isinstance(book.get("item"), int) and not isinstance(book.get("item"), bool):
        ids = {book["item"]}
    rows = []
    for chunk in _chunks(sorted(ids), 500):
        rows += self.conn.execute(f"SELECT id, tier, ord, work_id FROM items WHERE id IN ({','.join('?' * len(chunk))}) "
                                  f"AND availability != 'waiting' AND work_id IS NOT NULL", chunk).fetchall()
    if not rows:
        return None
    rows = [r for r in rows if r[1] != "graduated"] or rows     # beside the parts still read, never into Finished
    last = max(rows, key=lambda r: (TIERS[r[1]][3], r[2], r[0]))
    return last[3], last[1], last[0]


def _store_pair_audiobook(self, item_id, book=None, ask=None, answer=None, stale=False, by=SOURCE_PRODUCER,
                          fields=None, mark=None):
    """An audiobook item's pairing written in ONE command: its records' `book` / `ask` (`audiobooks.set_pair`'s) —
    every live record of the item alike (the same audiobook in two sources) — and with a `book` the item joins the
    book's title after its last part (H-6; the title it leaves, emptied, is tidied as any). `answer` (key, True /
    False): H-8's answer kept; `stale`: the next look weighs the lone audiobooks again; `fields`: the audiobook as
    found now (its files, sizes, length: `audiobooks.record`'s), its pairing kept unless `book` / `ask` say otherwise;
    `mark` (a5-2): the learner's word kept on its records — `said_no` (the book's title a *No* answered: *Needs you* then
    offers *Find its book…*), `no_book` (*It has no book*: never weighed again). Its item is fed (the row's 🎧 hover).
    -> True when written; False: no such audiobook item, or its book is gone (nothing written but the answer)."""
    with self._command("audiobook", by) as cmd:
        if answer is not None or stale:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (AUDIOBOOK_ANSWERS,)).fetchone()
            said = (_json_dict(row[0]) if row else None) or {}
            if answer is not None:
                said[str(answer[0])] = bool(answer[1])
            self._set_meta({AUDIOBOOK_ANSWERS: _dumps(said), "copy_dirty": self._meta().get("copy_dirty", 0) + 1,
                            **({AUDIOBOOKS_STALE: "1"} if stale else {})})
            cmd.touch()
        rows = self._audiobook_rows(item_id)
        if not rows:
            return False
        placed = self._audiobook_place(book) if isinstance(book, dict) else None
        if isinstance(book, dict) and placed is None:
            return False
        for key, _i, rec in rows:
            ab = dict(rec["audiobook"], **(fields or {}))
            if fields is None or book is not None or ask is not None:
                ab.update(book=book if placed else None, ask=None if placed else ask)
            ab.update(mark or {})
            self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                              (json.dumps(dict(rec, audiobook=ab), sort_keys=True, ensure_ascii=False), key))
        cmd.feed([item_id])
        if placed is not None:
            work, tier, last = placed
            old = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]
            if old != work:
                self.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (work, item_id))
                cmd.reworked.add(item_id)
                cmd.fed_works.update(w for w in (old, work) if w is not None)
            self._put(tier, [item_id], ("after", last), cmd.version)
            cmd.feed([item_id])
        self._transcript_checked(cmd, item_id)           # a6 (H-12, H-13): its transcript counts only while alone
        cmd.touch()
        return True


def _store_answer_audiobook(self, item_id, yes, key=None):
    """H-8's answer to *Is this audiobook 「…」 the book 「…」?* — kept, never asked twice: *Yes, the same book* joins
    the book's title (`pair_audiobook`); *No* takes the question away and the next look asks about the next book, or
    none. `key`: the question the card showed (its answer key) — another one asked since is never answered by it.
    -> True when that question was still open."""
    with self._reading():
        rows = self._audiobook_rows(item_id)
    ask = (rows[0][2].get("audiobook") or {}).get("ask") if rows else None
    if not isinstance(ask, dict) or not ask.get("key") or (key is not None and ask["key"] != key):
        return False
    if yes and self.pair_audiobook(item_id, book=dict(ask, how="answered"), answer=(ask["key"], True), by="user"):
        return True
    self.pair_audiobook(item_id, answer=(ask["key"], bool(yes)), stale=True, by="user",
                        mark=None if yes else {"said_no": ask.get("title") or True})
    return True


def _store_audiobook_finds(self):
    """a5-2 (Sonic 2026-10-28: after a *No*, "offer that they find the book"): [{item_id, title, files, seconds,
    said_no}] — an audiobook item alone (no book, no question open) whose learner said *No* and never *It has no
    book*: *Needs you* offers *Find its book…* · *It has no book*. One an item."""
    out, seen = [], set()
    with self._reading():
        for _k, item_id, rec in self._audiobook_rows():
            ab = rec.get("audiobook") or {}
            if item_id in seen:
                continue
            seen.add(item_id)
            if ab.get("said_no") and not ab.get("no_book") and not ab.get("book") and not ab.get("ask") and \
                    self.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
                out.append({"item_id": item_id, "title": ab.get("title") or "", "files": list(ab.get("files") or ()),
                            "seconds": ab.get("seconds"),
                            "said_no": ab["said_no"] if isinstance(ab["said_no"], str) else ""})
    return out


def _store_audiobook_hovers(self):
    """a5-2: what the row's 🎧 says of each audiobook item -> {item_id: {title, n, first, last, seconds, paired,
    transcript}} (its files' count, the first and last file's names, its length, paired or alone; a6: what its
    transcript is for, `audiobooks.transcript_use`, None without one). One read; the reader asks again only when an
    audiobook's item changed (`pair_audiobook`, `set_transcript` feed it)."""
    from app import audiobooks
    out = {}
    with self._reading():
        for _k, item_id, rec in self._audiobook_rows():
            ab = rec.get("audiobook") or {}
            names = [os.path.basename(str(f)) for f in ab.get("files") or ()]
            out.setdefault(item_id, {"title": ab.get("title") or "", "n": len(names),
                                     "first": names[0] if names else "", "last": names[-1] if names else "",
                                     "seconds": ab.get("seconds"), "paired": isinstance(ab.get("book"), dict),
                                     "transcript": audiobooks.transcript_use(ab)})
    return out


def _store_library_books(self, item_id=None):
    """a5-2 *Find its book…*: the library's books (one per EPUB among the live origins `<epub>#<n>` whose parts are in
    the library, not waiting) -> [{epub, sha256, work_id, title (its title's; its file's when the title holds two
    books), parts}], the likeliest first for `item_id`'s
    audiobook (`audiobooks`' title levels, then its volume), then by title; a book it was told *No* about last. One
    read."""
    from app import audiobooks
    with self._reading():
        books = {}
        for _key, part_id, raw in self.conn.execute(
                f"SELECT p.content_key, p.item_id, p.pairing FROM pairings p WHERE {_LIVE_ORIGIN} AND "
                f"instr(p.content_key, '#') > 0"):
            rec = _json_dict(raw) or {}
            origin = rec.get("origin") or ""
            if not _EPUB_PART.search(origin):
                continue
            epub = origin.rsplit("#", 1)[0]
            books.setdefault(path_key(epub), {"epub": epub, "sha256": rec.get("sha256"), "ids": []})["ids"].append(
                part_id)
        out = []
        for b in books.values():
            rows = []
            for chunk in _chunks(b["ids"], 500):
                rows += self.conn.execute(
                    f"SELECT i.work_id, w.title FROM items i LEFT JOIN works w ON w.id = i.work_id WHERE i.id IN "
                    f"({','.join('?' * len(chunk))}) AND i.availability != 'waiting' AND i.work_id IS NOT NULL",
                    chunk).fetchall()
            if rows:
                work, title = rows[0]
                out.append({"epub": b["epub"], "sha256": b["sha256"], "work_id": work, "title": title,
                            "parts": len(rows)})
        shared = {}
        for b in out:
            shared[b["work_id"]] = shared.get(b["work_id"], 0) + 1
        for b in out:                                    # a title holding two books: each named by its own file
            if not b["title"] or shared[b["work_id"]] > 1:
                b["title"] = os.path.splitext(os.path.basename(b["epub"]))[0]
        recs = self._audiobook_rows(item_id) if item_id is not None else []
    ab = (recs[0][2].get("audiobook") or {}) if recs else {}
    forms, vols = audiobooks._forms(list(ab.get("titles") or ()) + ([ab["title"]] if ab.get("title") else []))
    answers = self.audiobook_answers() if ab else {}
    heard = audiobooks.from_record(ab) if ab else None

    def rank(b):
        b_forms, b_vols = audiobooks._forms([b["title"], os.path.splitext(os.path.basename(b["epub"]))[0]])
        level = audiobooks._title_level(forms, b_forms) if forms else 0
        same = 1 if vols and b_vols and vols & b_vols else 0
        no = heard is not None and answers.get(audiobooks.answer_key(heard, audiobooks.Book(
            id=None, path=os.path.abspath(b["epub"]), sha256=b["sha256"]))) is False     # said *No* to: last
        return (no, -level, -same, search_fold(b["title"]), b["epub"])
    return sorted(out, key=rank)


def _store_pick_audiobook_book(self, item_id, epub, by="user"):
    """a5-2 *Find its book…*: the learner's pick — `epub` (a book of the library, by its EPUB's path) is the book this
    audiobook reads. Paired exactly as a *Yes* pairs (`pair_audiobook`: the records' `book`, the answer kept True, the
    item after the book's last part, in its title) in ONE command whose Change (`audiobook_pick`) Undo takes back: the
    records as they were, the answer as it was, the item in its title and place again. -> the Change, or None (no such
    audiobook item, already paired, or the book has no part in the library)."""
    from app import audiobooks
    with self._command("audiobook_pick", by) as cmd:
        rows = self._audiobook_rows(item_id)
        if not rows or isinstance((rows[0][2].get("audiobook") or {}).get("book"), dict):
            return None
        lo = SOURCE_KEY + path_key(os.path.abspath(epub)) + "#"
        found = self.conn.execute(f"SELECT p.pairing FROM pairings p WHERE p.content_key >= ? AND p.content_key < ? "
                                  f"AND {_LIVE_ORIGIN} LIMIT 1", (lo, lo[:-1] + "$")).fetchone()
        placed = self._audiobook_place({"epub": epub})
        if found is None or placed is None:
            return None
        sha = (_json_dict(found[0]) or {}).get("sha256")
        title = self.conn.execute("SELECT title FROM works WHERE id = ?", (placed[0],)).fetchone()
        key = audiobooks.answer_key(audiobooks.from_record(rows[0][2]["audiobook"]),
                                    audiobooks.Book(id=placed[2], path=os.path.abspath(epub), sha256=sha))
        book = {"item": placed[2], "epub": os.path.abspath(epub), "sha256": sha, "key": key,
                "title": title[0] if title else os.path.splitext(os.path.basename(epub))[0], "how": "answered"}
        change = self._change(cmd, "audiobook_pick")
        self._before(change, list(self._rows([item_id]).values()))
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (AUDIOBOOK_ANSWERS,)).fetchone()
        said = (_json_dict(row[0]) if row else None) or {}
        change.audiobook = {"records": [(k, json.dumps(r, sort_keys=True, ensure_ascii=False)) for k, _i, r in rows],
                            "answer": (key, said.get(key)), "item": item_id}
        old = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]
        moved = old != placed[0]
        change.works = {"rows": [self._work_row(old)] if moved and old is not None else [],
                        "items": [(item_id, old, placed[0])] if moved else [], "fields": [], "created": []}
        if not self.pair_audiobook(item_id, book=book, answer=(key, True), by=by):
            return None
        return change


def _store_audiobook_no_book(self, item_id):
    """a5-2 *It has no book*: an audiobook alone stays alone — never weighed against a book again, never asked (its
    records' `no_book`). Only while it is still alone with no question open (a look that paired or asked meanwhile
    wins). -> True when written."""
    with self._command("audiobook", "user"):
        rows = self._audiobook_rows(item_id)
        ab = (rows[0][2].get("audiobook") or {}) if rows else None
        if not ab or ab.get("book") or ab.get("ask") or ab.get("no_book"):
            return False
        return self.pair_audiobook(item_id, mark={"no_book": True}, by="user")


def _store_undo_audiobook_pick(self, cmd, change):
    """Undo of *Find its book…*'s pick, by the value check (§6.11). The item first: still in the title the pick gave it
    (else nothing is undone, with the note — never records saying *alone* for an item sitting in a book). Then only
    what the pick wrote, on each live record of the item that still holds it: `book` / `ask` / `said_no` as they were
    (what a look wrote since — its files, a move's mark — stays; a record moved away stays as it is); the answer as it
    was; the item's title (the one it left, back if the helper tidied it away) and its place."""
    said = change.audiobook
    key = said["answer"][0]
    item = self.conn.execute("SELECT work_id FROM items WHERE id = ?", (said["item"],)).fetchone()
    moved = change.works["items"][0] if change.works["items"] else None
    if item is None or (moved is not None and item[0] != moved[2]):
        return self._skipped(cmd, 1), []
    before = {k: (json.loads(v).get("audiobook") or {}) for k, v in said["records"]}
    back, live = [], 0
    for content_key, _i, rec in self._audiobook_rows(said["item"]):
        live += 1
        now = rec.get("audiobook") or {}
        if not (isinstance(now.get("book"), dict) and now["book"].get("key") == key):
            continue
        was = before.get(content_key) or next(iter(before.values()), {})
        ab = dict(now, book=was.get("book"), ask=was.get("ask"))
        if was.get("said_no"):
            ab["said_no"] = was["said_no"]
        back.append((json.dumps(dict(rec, audiobook=ab), sort_keys=True, ensure_ascii=False), content_key))
    if not back:
        return self._skipped(cmd, 1), []
    self.conn.executemany("UPDATE pairings SET pairing = ? WHERE content_key = ?", back)
    row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (AUDIOBOOK_ANSWERS,)).fetchone()
    answers = (_json_dict(row[0]) if row else None) or {}
    if said["answer"][1] is None:
        answers.pop(key, None)
    else:
        answers[key] = said["answer"][1]
    self._set_meta({AUDIOBOOK_ANSWERS: _dumps(answers), "copy_dirty": self._meta().get("copy_dirty", 0) + 1})
    cmd.feed([said["item"]])
    self._audio_state(cmd, said["item"])                 # a6: alone again, its transcript is its content again
    skipped = []
    if change.works["items"]:
        _o, skipped = self._undo_works(cmd, change)
    out, more = self._replace(cmd, change)
    if len(back) < live:                                 # a record paired since is left as it is: said
        out.notes.append(f"{live - len(back)} of its records changed since and {'were' if live - len(back) != 1 else 'was'}"
                         f" left as {'they are' if live - len(back) != 1 else 'it is'}")
    cmd.touch()
    return out, list(skipped) + [i for i in more if i not in skipped]


def _store_audiobooks_weighed(self):
    """The look weighed the lone audiobooks again: AUDIOBOOKS_STALE off (bookkeeping)."""
    self.bookkeeping({AUDIOBOOKS_STALE: "0"})


# --- an audiobook's transcript (Hon a6: H-12 ✅ Sonic, H-13 PROVISIONAL) ------------------------------------------- #
# A subtitle file beside an audiobook is its transcript: its records' `"transcript"` {origin, rel (Surasura's copy in
# Library), sha256, size, mtime_ns, heard (the item's file name while it waits: its first audio file's), found (the
# content check against the book it is paired with: {book, share})}. ONE rule says what the item is
# (`_audio_state`, from `audiobooks.transcript_use`): alone (or asked about), the transcript is its content — the item
# points at the copy and counts as a subtitle does; paired, the book is the content — the item waits again (its audio's
# name, no file there), the copy kept for the audio's timing (Anki Miner's Z-16); a transcript the check finds isn't
# the book's (under CONTENT_SHARE of its cues in order) is never used, and *Needs you* says so. Taking the key out of
# the records, and each item's rel back to `heard`, undoes it all (no table, no schema).
def _store_audio_state(self, cmd, item_id):
    """The item's file and availability as its records say: TEXT → its transcript's copy (`available`, `missing` when
    the copy is gone), anything else → its audio's name, `waiting`. An item with no transcript is left as it is (a
    waiting audiobook). Its id, place, title and the learner's marks are kept. -> True when it changed."""
    from app import audiobooks
    rows = self._audiobook_rows(item_id)
    ab = (rows[0][2].get("audiobook") or {}) if rows else {}
    said = ab.get("transcript") if isinstance(ab.get("transcript"), dict) else None
    row = self.conn.execute("SELECT rel_path, availability, tier, entry, size, mtime_ns FROM items WHERE id = ?",
                            (item_id,)).fetchone()
    if row is None or not said or not said.get("rel") or not said.get("heard"):
        return False
    if audiobooks.transcript_use(ab) == audiobooks.TEXT:
        rel = said["rel"]
        size, mtime_ns, availability = _fingerprint(self.data_dir, rel)
    else:
        rel, size, mtime_ns, availability = said["heard"], None, None, "waiting"
    entry = _json_dict(row[3]) or {}
    if (row[0], row[1], entry.get("source_type"), row[4], row[5]) == (rel, availability, "audio", size, mtime_ns):
        return False                                     # (a copy written over in place: its new size and time)
    entry.update(physical_path=rel, source_type="audio")
    if ab.get("title"):
        entry["title"] = str(ab["title"])
    title, folder, source_type = _columns(entry)
    self.conn.execute("UPDATE items SET rel_path = ?, rel_key = ?, entry = ?, title = ?, parent_folder = ?, "
                      "source_type = ?, search_key = ?, availability = ?, size = ?, mtime_ns = ? WHERE id = ?",
                      (rel, path_key(rel), _dumps(entry), title, folder, source_type,
                       search_fold(title or "", self.language), availability, size, mtime_ns, item_id))
    if availability == "available" and said.get("sha256") and self._hash_column():
        self.conn.execute("UPDATE items SET content_sha256 = ? WHERE id = ?", (said["sha256"], item_id))
    cmd.touch({row[2]}, availability=True)
    cmd.feed([item_id])
    return True


def _store_transcript_found(self, said, book):
    """H-13's content check: the share of the transcript's cues (`audiobooks.cues`, of Surasura's copy) found in order
    in the book's text (its parts' copies, in the book's order) -> {book, share}; None when either can't be read (the
    check waits: never a guess). Milliseconds: one pass over each."""
    from app import audiobooks
    from app.path_utils import read_text
    try:
        lines = audiobooks.cues(read_text(os.path.join(self.data_dir, _strip(said["rel"])), self.language))
    except (OSError, KeyError, TypeError):
        return None
    epub = book.get("epub")
    if not isinstance(epub, str) or not epub:
        return None
    lo = SOURCE_KEY + path_key(os.path.abspath(epub)) + "#"
    parts = []
    for key, rel in self.conn.execute(f"SELECT p.content_key, i.rel_path FROM pairings p JOIN items i ON i.id = "
                                      f"p.item_id WHERE p.content_key >= ? AND p.content_key < ? AND {_LIVE_ORIGIN}",
                                      (lo, lo[:-1] + "$")):
        n = key[len(lo):]
        parts.append((int(n) if n.isdigit() else 0, rel))
    text = []
    for _n, rel in sorted(parts):
        try:
            with open(os.path.join(self.data_dir, _strip(rel)), encoding="utf-8", errors="replace") as f:
                text.append(f.read())
        except OSError:
            return None
    if not text:
        return None
    return {"book": audiobooks._book_mark(book),
            "share": audiobooks.found_in_order(lines, audiobooks.clean_text("".join(text)))}


def _store_transcript_checked(self, cmd, item_id):
    """An audiobook item's transcript checked against the book it is paired with when its check isn't for that book
    (`found`), then the item as its records say (`_audio_state`) — after any pairing write. -> True when it changed."""
    from app import audiobooks
    rows = self._audiobook_rows(item_id)
    ab = (rows[0][2].get("audiobook") or {}) if rows else {}
    said = ab.get("transcript")
    if not isinstance(said, dict):
        return False
    if audiobooks.transcript_use(ab) == audiobooks.UNCHECKED:
        found = self._transcript_found(said, ab["book"])
        if found is not None:
            for key, _i, rec in rows:
                one = dict(rec["audiobook"], transcript=dict(rec["audiobook"].get("transcript") or said, found=found))
                self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                                  (json.dumps(dict(rec, audiobook=one), sort_keys=True, ensure_ascii=False), key))
            cmd.feed([item_id])
            cmd.touch()
    return self._audio_state(cmd, item_id)


def _store_set_transcript(self, item_id, transcript=None, from_item=None, by=SOURCE_PRODUCER):
    """An audiobook item's transcript written in ONE command (the look's; H-12): `transcript` {origin, rel, sha256,
    size, mtime_ns} — its copy made by the look (`rel`), or the copy of `from_item`, a subtitle item the transcript was
    taken in as before its audiobook was known: that item becomes the audiobook's (`_adopt_transcript_item`). None:
    the transcript as recorded, checked again (a check that couldn't be made yet). Paired, it is checked against the
    book (`found`); the item then is what its records say (`_audio_state`). -> the audiobook's item id, or None (no
    such audiobook item, or `from_item` can't become it: nothing written)."""
    from app import audiobooks
    with self._command("audiobook", by) as cmd:
        rows = self._audiobook_rows(item_id)
        if not rows:
            return None
        target = item_id
        if from_item is not None and from_item != item_id:
            if not self._adopt_transcript_item(cmd, item_id, from_item, (transcript or {}).get("origin")):
                return None
            target = from_item
            rows = self._audiobook_rows(target)
        ab = rows[0][2].get("audiobook") or {}
        old = ab.get("transcript") if isinstance(ab.get("transcript"), dict) else {}
        if transcript is None:                           # checked again only: nothing written unless it changes
            if not old:
                return None
            self._transcript_checked(cmd, target)
            return target
        said = dict(old, **transcript)
        if not said.get("heard"):
            said["heard"] = self._heard_rel(target, ab, said)
        if old.get("sha256") != said.get("sha256") or old.get("rel") != said.get("rel"):
            said.pop("found", None)                      # another transcript: checked again
        for key, _i, rec in rows:
            one = dict(rec["audiobook"], transcript=said)
            self.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                              (json.dumps(dict(rec, audiobook=one), sort_keys=True, ensure_ascii=False), key))
        cmd.feed([target])
        cmd.touch()
        self._transcript_checked(cmd, target)
        return target


def _store_heard_rel(self, item_id, ab, said):
    """The item's file name while it waits (no file there): its own while it waits on an audio file's name, else
    `<the transcript copy's folder>/<its sizes' key> <its first audio file>` — a waiting audiobook's (`sources`)."""
    from app import audiobooks
    row = self.conn.execute("SELECT rel_path, availability FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is not None and row[1] == "waiting" and audiobooks.is_audio(row[0] or ""):
        return row[0]
    key = audiobooks.sizes_key(audiobooks.from_record(ab))
    first = os.path.basename(next(iter(ab.get("files") or ()), "") or "audio.m4b")
    folder = str(said.get("rel") or (row[0] if row is not None else "") or CONTENT_FOLDER + "/x").rsplit("/", 1)[0]
    return f"{folder}/{key[6:14]} {first}"


def _store_adopt_transcript_item(self, cmd, audio_item, text_item, origin=None):
    """H-12, a transcript already in as a subtitle of its own (taken in before its audiobook was known): THAT item
    becomes the audiobook's — it keeps its id, its marks, its cards and its copy; the audiobook's records move onto it
    (the transcript's own record, `origin`, dropped: it is the audiobook's `transcript` now, never a text a look
    follows); it takes the waiting audio item's title and place (in Finished, it stays there), and the audio item
    (waiting, no file: nothing of the learner's on it) goes, its title tidied as a Remove's. -> True when done; False (nothing written) when either is
    gone, the audio item isn't a waiting one, or the subtitle item is an audiobook's already."""
    a = self.conn.execute("SELECT work_id, tier, availability FROM items WHERE id = ?", (audio_item,)).fetchone()
    s = self.conn.execute("SELECT work_id, source_type, tier FROM items WHERE id = ?", (text_item,)).fetchone()
    if a is None or s is None or a[2] != "waiting" or s[1] == "audio" or self._audiobook_rows(text_item):
        return False
    if origin:
        self.conn.execute("DELETE FROM pairings WHERE item_id = ? AND content_key = ? AND "
                          "content_key >= 'src:' AND content_key < 'src;'", (text_item, origin_key(origin)))
    self.conn.execute("UPDATE pairings SET item_id = ? WHERE item_id = ?", (text_item, audio_item))
    if s[0] != a[0]:
        self.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (a[0], text_item))
        cmd.reworked.add(text_item)
        cmd.fed_works.update(w for w in (s[0], a[0]) if w is not None)
    if s[2] != "graduated":                              # finished as a title of its own: it stays in Finished
        self._put(a[1], [text_item], ("after", audio_item), cmd.version)
        cmd.touch({s[2], a[1]})                          # the tier it left counts one file fewer
    self._take_out(cmd, audio_item)
    cmd.feed([text_item])
    return True


def _store_transcript_mismatches(self):
    """H-13's lines for *Needs you*: [{item_id, title, book, share, key}] — an audiobook paired with a book whose
    transcript the check found isn't that book's (`audiobooks.OTHER`): never used, said once. `key`: the transcript's
    bytes and the book's (a new one of either is a new line)."""
    from app import audiobooks
    out, seen = [], set()
    with self._reading():
        for _k, item_id, rec in self._audiobook_rows():
            ab = rec.get("audiobook") or {}
            if item_id in seen or audiobooks.transcript_use(ab) != audiobooks.OTHER or \
                    not isinstance((ab["transcript"].get("found") or {}).get("share"), (int, float)):
                continue                                 # (no cue long enough to look for: nothing to say)
            seen.add(item_id)
            said, book = ab["transcript"], ab["book"]
            out.append({"item_id": item_id, "title": ab.get("title") or "", "book": book.get("title") or "",
                        "share": (said.get("found") or {}).get("share"), "transcript": said.get("origin") or "",
                        "key": f"{said.get('sha256')}|{audiobooks._book_mark(book)}"})
    return out


Store._audiobook_rows = _store_audiobook_rows
Store.audiobooks = _store_audiobooks
Store.audiobook_answers = _store_audiobook_answers
Store.audiobook_asks = _store_audiobook_asks
Store._audiobook_place = _store_audiobook_place
Store.pair_audiobook = _store_pair_audiobook
Store.answer_audiobook = _store_answer_audiobook
Store.audiobooks_weighed = _store_audiobooks_weighed
Store.audiobook_finds = _store_audiobook_finds
Store.audiobook_hovers = _store_audiobook_hovers
Store.library_books = _store_library_books
Store.pick_audiobook_book = _store_pick_audiobook_book
Store._undo_audiobook_pick = _store_undo_audiobook_pick
Store.audiobook_no_book = _store_audiobook_no_book
Store._audio_state = _store_audio_state
Store._transcript_found = _store_transcript_found
Store._transcript_checked = _store_transcript_checked
Store.set_transcript = _store_set_transcript
Store._heard_rel = _store_heard_rel
Store._adopt_transcript_item = _store_adopt_transcript_item
Store.transcript_mismatches = _store_transcript_mismatches


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
# Start a fresh library (K7, laptop fixes; Settings → Content): the library's own state set aside
# ------------------------------------------------------------------------------------------------ #

RESET_PREFIX = "library-reset-"   # User Files/<lang>/.trash/library-reset-<YYYYmmdd-HHMMSS>/ (that .trash is never purged)
RESET_RECORD = "reset.json"       # in it: what came from where, enough to put the old library back by hand
RESET_WAIT = 2.0                  # s: another writer's commit is waited for this long, then the reset is refused
# Emptied by the reset; `roots` stays (the folders he reads, their ids kept), and so does every exclusion but Remove's
# — but never Connect's never-again sets (`made_words`, `made_lines`, G1.3-4: a word whose card he deleted is never made
# again; item ids are never reused, so their stale ids meet no new item: I-R1 / LF-5)
RESET_TABLES = ("anki_links", "pairings", "placement_log", "trash", "anki_changes", "gone", "items", "pieces", "works")
# His library options (W-1's `keep_watched` too), and the log's numbering (+ readers)
RESET_KEEP_META = ("mine_line", "arrivals_on", "keep_watched", "log_seq")
# Why a reset is refused (nothing changed), in the window's words
RESET_UPDATE = "An update is being installed: sort your library again once it has finished."
RESET_GENERATE = "A Generate is running: sort your library again once it has finished."
RESET_CONNECT = "Connect is making cards: sort your library again once it has finished."
RESET_KNOWN = "Your known words are being updated: try again in a moment."
RESET_BUSY = "Another Surasura program is saving your library: try again in a moment."
RESET_DAMAGED = "Your library needs Repair first."
RESET_LINKED = ("A linked folder in your data folder is in the way ({path}): Surasura never moves or removes what a "
                "link leads to. Remove the link (never its folder), then sort your library again.")
RESET_NOT_ALL_BACK = "Part of your library couldn't be put back; it is in the backup ({folder})"


class ResetRefused(StoreError):
    """A fresh library refused before anything was changed; `reason` in the window's words."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _copy_db(conn, dest):
    """The store's rows through SQLite's backup API (a plain copy of the .db alone loses committed rows, K6), written
    under a `.part` name and renamed once whole. Never inside a transaction on `conn` (the backup then waits on it)."""
    target = sqlite3.connect(dest + ".part")
    try:
        conn.backup(target)
    finally:
        target.close()
    os.replace(dest + ".part", dest)


def _copy_whole(conn, dest):
    """Is the copy at `dest` the store as it stands? Its own check passes, and every table holds as many rows as the
    store's (read under the write lock: nothing moves meanwhile)."""
    copy = sqlite3.connect(dest)
    try:
        if [r[0] for r in copy.execute("PRAGMA quick_check")] != ["ok"]:
            return False
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            sql = f'SELECT COUNT(*) FROM "{name}"'
            if copy.execute(sql).fetchone() != conn.execute(sql).fetchone():
                return False
        return True
    except sqlite3.DatabaseError:
        return False
    finally:
        copy.close()


def _same_bytes(a, b):
    with open(a, "rb") as x, open(b, "rb") as y:
        while True:
            one, two = x.read(1 << 20), y.read(1 << 20)
            if one != two:
                return False
            if not one:
                return True


class ResetNotAllBack(StoreError):
    """A reset that failed before its commit, with part of the library left in the backup (`folder`): `reset.json`'s
    `not_put_back` names each piece. The window never says "Nothing was changed" for it."""

    def __init__(self, folder):
        super().__init__(RESET_NOT_ALL_BACK.format(folder=folder))
        self.folder = folder


def _links_under(src):
    """The first symlink or junction at or under `src` (`is_link`, never followed), or None."""
    try:
        if is_link(os.lstat(src)):
            return src
    except OSError:
        return None
    stack = [src] if os.path.isdir(src) else []
    while stack:
        with os.scandir(stack.pop()) as found:
            for entry in found:
                if is_link(entry.stat(follow_symlinks=False)):
                    return entry.path
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
    return None


def _set_aside(src, dst):
    """`src` to `dst`, a name in the backup folder: a rename (one volume); refused (another volume, a folder a watch
    holds open) → copied, every file's bytes checked, then the original removed — a file that can't be removed raises:
    left beside the library, the disk sync would walk it back in. A folder left empty (held open) stays, empty.
    A link or junction anywhere in it stops the copy before anything is copied or removed (LF-4: Python 3.11 walks a
    junction as a plain folder, so the removal would delete the files of the folder it leads to — his own): the reset
    is refused (`RESET_LINKED`) and everything already moved put back. A rename moves a link itself, never through it.
    The removal takes only the files checked, each only while its size and time are as checked (D5: one that arrived
    or changed after the check — hato's drop, the copier's — has no checked copy): -> those left where they are
    ([] after a rename), named in `reset.json` (`left`)."""
    import shutil
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)
        return []
    except OSError:
        pass
    link = _links_under(src)
    if link is not None:
        raise ResetRefused(RESET_LINKED.format(path=link))
    if os.path.isdir(src):
        shutil.copytree(src, dst, symlinks=True)
        files = [os.path.join(w, n) for w, _d, names in os.walk(src) for n in names]
        pairs = [(f, os.path.join(dst, os.path.relpath(f, src))) for f in files]
    else:
        shutil.copy2(src, dst)
        pairs = [(src, dst)]
    checked = {}
    for a, b in pairs:
        st = os.stat(a)
        if not _same_bytes(a, b):
            raise OSError(f"the backup copy of {a} did not match it")
        checked[a] = (st.st_size, st.st_mtime_ns)
    left = []

    def remove(path):                                   # D5: only a file checked, and unchanged since its check
        try:
            st = os.stat(path)
        except OSError:
            return
        if checked.get(path) != (st.st_size, st.st_mtime_ns):
            left.append(path)
            return
        os.remove(path)
    if not os.path.isdir(src):
        remove(src)
        return left
    for where, dirs, names in os.walk(src, topdown=False):
        for n in names:
            remove(os.path.join(where, n))
        for d in dirs:
            try:
                os.rmdir(os.path.join(where, d))
            except OSError:
                pass
    try:
        os.rmdir(src)
    except OSError:
        pass
    return left


def _put_back(dst, src):
    """One `_set_aside` undone — recorded before it began, so one that stopped part way (a copy checked, some files
    removed) is undone too (H1 / LF-6): when nothing is left at `src`, the backup renamed back; else each file of the
    backup missing at `src` copied back, never over a file there (the original: a byte check that failed leaves bad
    bytes in the backup). The backup's copy then stays."""
    import shutil
    if not os.path.lexists(dst):
        return
    if not os.path.lexists(src):
        try:
            os.rename(dst, src)
            return
        except OSError:
            pass
    if not os.path.isdir(dst):
        if not os.path.lexists(src):
            shutil.copy2(dst, src)
        return
    for where, _dirs, names in os.walk(dst):
        here = os.path.normpath(os.path.join(src, os.path.relpath(where, dst)))
        os.makedirs(here, exist_ok=True)
        for n in names:
            if not os.path.lexists(os.path.join(here, n)):
                shutil.copy2(os.path.join(where, n), os.path.join(here, n))


def _write_record(folder, record):
    with open(os.path.join(folder, RESET_RECORD + ".tmp"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(os.path.join(folder, RESET_RECORD + ".tmp"), os.path.join(folder, RESET_RECORD))


def start_fresh(store, forget_known=False, _step=None):
    """*Start a fresh library* (asked for 2026-10-21: "I need a reset library button as well") for `store`'s language ->
    {"backup": the backup folder, "known": "kept" | "forgotten" | "kept: <why>", "sources": [root ids being read]}.

    **Goes, into one dated backup** (`User Files/<lang>/.trash/library-reset-<stamp>/`, never purged; `reset.json` in
    it names what came from where): the store's rows — items, order, pieces, works, trash, the log, New arrivals,
    pairings and origins, Remove's exclusions, Anki links — as a SQLite backup; its JSON copy `master_manifest.json`
    (item 8: a store whose database is lost rebuilds itself from it — left here, the old library comes back); every
    entry of `data/<lang>/` (the `Library/` copies, a 2.x upgrade's tier folders — left, the disk sync walks them back
    in — hato's drop folder, `data/<lang>/.trash`); the sources' folder-time cache. **Stays:** the folders he reads
    (their `roots` rows and ids; nothing under them is ever written) and his library options (the mine line, New
    arrivals' switch); a folder he said never to read (an exclusion that isn't Remove's); Connect's never-again sets
    (`made_words`, `made_lines`: a card he deleted is never made again, LF-5); Anki; settings.json;
    results/; known words unless `forget_known` (then KnownWord.json is kept dated in the trash with
    `backup_to_trash`, copied into the backup, and replaced by an empty one in its own format). The caller reads the
    folders again (`SourceLooks.fresh`: a first look of each, `first=True`, landing in Current as setup's does).

    **The one write:** every table emptied and a fresh meta — a **new store_id** (a new library: Connect's queued jobs
    name the store they were read from and drop for another, P2.1 #12), `epoch` + 1 (every window reads in full; the
    folder-time cache is dropped), `state_version` and the other versions only ever up, item ids never reused (the
    sequences stay, K30), the Soon line at 25 (`_line_after_build`), works / search keys seeded as a build's are. The
    fresh JSON copy is exported at once (`export_copy`, under the maintenance lock held).

    **Refused** (`ResetRefused`, nothing changed) while an update is staged, a Generate holds `results`, Connect runs,
    the helper holds the maintenance lock, another writer keeps the write lock past RESET_WAIT, the known-words lock
    is held (when asked to forget them), or the store is damaged. Every lock is held to the end, the write lock from
    the backup copy to the commit, so the copy holds every row the write empties.

    **Crash-safe by its order** — a kill between any two steps leaves the old library in place or restorable by hand
    from `reset.json`: (1) the backup folder and `reset.json` (status "started", every move it will make); (2) the
    store copied and checked (`_copy_whole`: its own check, every table's count) — not whole → StoreError, nothing
    moved; (3) the JSON copy, (4) the folder times, (5) `data/<lang>`'s entries moved (`_set_aside`) — the store
    still holds the old library: a kill here leaves every moved thing at its `to`; (6) the one write, committed
    (status "written": the store copy is the old library); (7) the export; (8) the known words; status "done" —
    after the commit every step is best-effort, logged, never raised (`_after_commit`, H2: the fresh library stands).
    An error (not a kill) before the commit rolls the write back and puts every move back itself, each on its own, a
    move recorded before it began (status "undone"; a piece that couldn't go back is named in `not_put_back` and
    raised as `ResetNotAllBack`); a link in the data folder refuses it there (`RESET_LINKED`, LF-4).
    No restore button here (K7): `reset.json` says how by hand. `_step(name)` (tests) is called after each step."""
    step = _step or (lambda _name: None)
    if update_staged():
        raise ResetRefused(RESET_UPDATE)
    from app import locks
    token = object()                                    # this reset's holds: a hold by this thread too is refused
    held = []
    try:
        try:
            held.append(locks.take("results", "Sorting your library again", owner=token))
        except locks.Busy:
            raise ResetRefused(RESET_GENERATE) from None
        if locks.in_use("connect"):
            raise ResetRefused(RESET_CONNECT)
        if forget_known:
            from app.anki_sync import known_lock_name
            try:
                held.append(locks.take(known_lock_name(store.language), "Sorting your library again", wait=RESET_WAIT,
                                       owner=token))
            except locks.Busy:
                raise ResetRefused(RESET_KNOWN) from None
        lock = MaintenanceLock(store.db_path)
        try:
            if not lock.try_acquire():
                raise ResetRefused(RESET_BUSY)
            return _start_fresh(store, forget_known, step)
        finally:
            lock.close()
    finally:
        for h in reversed(held):
            h.release()


def _start_fresh(store, forget_known, step):
    from contextlib import ExitStack
    from app import sources
    language, data_dir, user_files_dir = store.language, store.data_dir, store.user_files_dir
    stack = ExitStack()
    try:
        stack.enter_context(store._writing(begin=False, wait=RESET_WAIT))
    except StoreBusy:
        raise ResetRefused(RESET_BUSY) from None
    except StoreReadOnly:
        raise ResetRefused(RESET_DAMAGED) from None
    with stack:
        trash = os.path.join(user_files_dir, ".trash")
        folder = os.path.join(trash, RESET_PREFIX + _stamp())
        n = 1
        while os.path.exists(folder):
            folder = os.path.join(trash, f"{RESET_PREFIX}{_stamp()}-{n}")
            n += 1
        os.makedirs(folder)
        moves = []
        target = manifest_path(user_files_dir)
        if os.path.lexists(target):
            moves.append({"step": "manifest", "from": target, "to": os.path.join(folder, MANIFEST_NAME)})
        cache = sources.cache_path(language)
        if os.path.lexists(cache):
            moves.append({"step": "cache", "from": cache, "to": os.path.join(folder, os.path.basename(cache))})
        if os.path.isdir(data_dir):
            for name in sorted(os.listdir(data_dir)):
                moves.append({"step": "data", "from": os.path.join(data_dir, name),
                              "to": os.path.join(folder, "data", name)})
        db_copy = os.path.join(folder, os.path.basename(store.db_path))
        record = {"language": language, "status": "started", "started_at": _now(), "db": store.db_path,
                  "db_copy": db_copy, "moves": moves, "known": None,
                  "how_to_put_back": "Close Surasura. Copy db_copy over db (delete db's -wal and -shm first) when the "
                                     "status is written or done, then move every 'to' back to its 'from'."}
        _write_record(folder, record)
        done = []
        try:
            step("folder")
            _copy_db(store.conn, db_copy)
            if not _copy_whole(store.conn, db_copy):
                raise StoreError("the library's backup copy isn't whole; nothing was changed")
            step("backup")
            for name in ("manifest", "cache", "data"):
                for move in moves:
                    if move["step"] == name:
                        done.append(move)               # before it begins: one stopping part way is put back (H1)
                        left = _set_aside(move["from"], move["to"])
                        if left:
                            move["left"] = left         # D5: never removed, no checked copy; named in reset.json
                step(name)
            _reset_tables(store)
            step("wipe")
            store.conn.execute("COMMIT")
        except Exception as e:
            if store.conn.in_transaction:
                store.conn.execute("ROLLBACK")
            left = []
            for move in reversed(done):                 # each on its own: one failing never keeps the rest away
                try:
                    _put_back(move["to"], move["from"])
                except Exception as why:
                    left.append({"from": move["from"], "to": move["to"], "error": repr(why)})
            record["status"] = "undone"
            if left:
                record["not_put_back"] = left
            _after_commit("its record", _write_record, folder, record)
            if left:
                raise ResetNotAllBack(folder) from e
            raise
        record["status"] = "written"                    # committed: from here on nothing is the reset's failure (H2)
        _after_commit("its record", _write_record, folder, record)
    return _after_write(store, folder, record, forget_known, step)


def _after_commit(what, call, *args):
    """A step after the reset's commit (or its record after an undo): logged when it fails, never raised — the fresh
    library stands, so the window never says "Nothing was changed" for it (H2). -> its answer, or None."""
    try:
        return call(*args)
    except Exception as e:
        print(f"Fresh library: {what} failed ({e!r}); the library stands as it was written")
        return None


def _after_write(store, folder, record, forget_known, step):
    """`start_fresh`'s steps (7)–(8), after the commit: each best-effort (`_after_commit`) — the JSON copy (the next
    maintain exports it), the known words (kept, with why), the last record write, the folders' list."""
    _after_commit("the windows' bell", library_watch.ring, store.db_path)   # every window reads the new epoch in full
    step("write")
    _after_commit("the JSON copy (it waits for the next save)", export_copy, store)   # the maintenance lock is held
    step("export")
    known = "kept"
    if forget_known:
        known = _after_commit("forgetting the known words", _forget_known, store, folder, record)
        known = known or "kept: they couldn't be forgotten"
    record.update(status="done", known=record["known"] or known, finished_at=_now())
    _after_commit("its record", _write_record, folder, record)
    step("known")
    rows = _after_commit("the folders' list", store.sources) or []
    return {"backup": folder, "known": known, "sources": [r["id"] for r in rows]}


def _reset_tables(store):
    """The one write's rows (inside the reset's write lock): BEGIN, every table of the library's own emptied, Remove's
    exclusions with them, and a fresh meta (`start_fresh`'s docstring). Committed by the caller."""
    conn = store.conn
    old = store._meta()
    conn.execute("BEGIN IMMEDIATE")
    for sql in ADDED_TABLES_SQL:                         # an added table this store may not have made yet
        conn.execute(sql)
    for name in RESET_TABLES:
        conn.execute(f"DELETE FROM {name}")
    conn.execute("DELETE FROM exclusions WHERE kind = 'removed'")
    conn.execute("DELETE FROM meta")
    meta = _fresh_meta(uuid.uuid4().hex, int(old.get("epoch") or 1) + 1, int(old.get("state_version") or 0) + 1)
    for key in ("order_version", "availability_version", "pins_version"):
        meta[key] = int(old.get(key) or 0) + 1
    meta.update({k: v for k, v in old.items() if k in RESET_KEEP_META or k.startswith("reader")})
    store._set_meta(meta)
    _seed_schema2(store, meta["state_version"])         # the feed's floor and the search fold, as every build's
    _line_after_build(store)                            # nothing in Current: 25 (Q2-4)
    store._set_meta({"migrated_at": _now()})


def _forget_known(store, folder, record):
    """*Also forget my known words*: KnownWord.json kept dated in the trash (`backup_to_trash`, byte-checked) and
    copied into the backup, then an empty one in its own format (`anki_sync`'s): a clean slate — no dismissed words,
    no past Graduates' words; both backups keep them all (I-R4, Q-1). -> "forgotten", or "kept: <why>" (the library
    is fresh either way). Words from his Anki cards come back at the next Anki sync (a file rewritten outside the sync
    makes its next run a full one, D4)."""
    from app import anki_sync
    path = os.path.join(store.user_files_dir, anki_sync.KNOWN_FILE)
    if not os.path.isfile(path):
        return "forgotten"
    try:
        dated = backup_to_trash(path)
        copy = os.path.join(folder, anki_sync.KNOWN_FILE)
        import shutil
        shutil.copyfile(path, copy)
        if not _same_bytes(path, copy):
            raise OSError("the backup copy did not match it")
        anki_sync._atomic_write_json(path, anki_sync._fresh_file([]))    # a clean slate (I-R4)
    except OSError as e:
        return f"kept: {e}"
    record["known"] = {"from": path, "dated": dated, "copy": copy}   # once it happened
    return "forgotten"


def fresh_counts(store):
    """What *Start a fresh library*'s sheet names, from the store (I-R1, I-R5, LF-8), in one read -> {"added": the +
    Add files whose original is in no folder Surasura reads (gone, or elsewhere: their records go with the library),
    "youtube": YouTube / bilibili transcripts, "other": every other item no folder being read brings back (pasted
    texts, hato's drops, 2.x content), "suspended": the cards *Take its new cards out* left suspended in Anki (the
    open `cards_out` records: they go into the backup, so the cards stay suspended — Put back is a Junban run over
    Anki, never the reset's)}. An item comes back when one of its origins lies under a folder being read."""
    on = [path_key(os.path.abspath(r["path"])).rstrip("/") + "/" for r in store.sources(counts=False) if r["path"]]
    with store._reading():
        items = store.conn.execute("SELECT id, source_type FROM items").fetchall()
        origins = store.conn.execute(
            f"SELECT p.item_id, substr(p.content_key, {len(SOURCE_KEY) + 1}), CASE WHEN json_valid(p.pairing) AND "
            f"json_type(p.pairing) = 'object' THEN json_extract(p.pairing, '$.via') END FROM pairings p WHERE "
            f"{_ORIGIN_ROW} AND NOT {_VERSION_ROW}").fetchall()
        changes = store.conn.execute("SELECT after FROM anki_changes WHERE reverted_at IS NULL AND action = "
                                     "'cards_out'").fetchall()
    back, added = set(), set()
    for item_id, key, via in origins:
        if any(key.startswith(prefix) for prefix in on):
            back.add(item_id)
        elif via == "add":
            added.add(item_id)
    out = {"added": 0, "youtube": 0, "other": 0, "suspended": 0}
    for item_id, source_type in items:
        if item_id in back:
            continue
        kind = "added" if item_id in added else "youtube" if source_type in ("youtube", "bilibili") else "other"
        out[kind] += 1
    cards = set()
    for (after,) in changes:
        record = _json_dict(after) or {}
        cards.update(c for c in record.get("suspended") or () if isinstance(c, int))
    out["suspended"] = len(cards)
    return out


def unfinished_reset(user_files_dir, told=False):
    """LF-11: the newest backup folder of a fresh library a kill stopped part way (`reset.json` still "started": its
    moves may be half done, the old library in the backup), or None. Read once a run, at the first look. D7: only one
    that moved something (a `moves[*].to` there: a kill during the store copy moved nothing) and wasn't told yet;
    `told` (the looks', with the bar line): its record says `"told": true` from now on, so the line shows once."""
    trash = os.path.join(user_files_dir, ".trash")
    try:
        names = sorted((n for n in os.listdir(trash) if n.startswith(RESET_PREFIX)), reverse=True)
    except OSError:
        return None
    for name in names:
        folder = os.path.join(trash, name)
        try:
            with open(os.path.join(folder, RESET_RECORD), encoding="utf-8") as f:
                record = json.load(f)
            if record.get("status") != "started" or record.get("told") or \
                    not any(os.path.lexists(m.get("to") or "") for m in record.get("moves") or ()):
                continue
            if told:
                record["told"] = True
                _after_commit("its record", _write_record, folder, record)
            return folder
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return None


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


def trash_file(data_dir, rel, to=None):
    """A user's Remove or Undo-Add: the file to `data/<lang>/.trash/<base>_<stamp><ext>` (never
    `rmtree`), its 30-day clock restarted. Returns the trashed path relative to data/<lang>, or None
    when there was no file — or when it isn't Surasura's to move (SRC K1a.6): a path that leads out of the data folder
    as written, or a copy under the content folder that a folder link leads out of it (the store makes every file
    there itself: one elsewhere may be a source's original). A 2.x tier folder's links move as they always did. The
    caller that drops the file's row checks `trash_refused` first. `to` (".trash/<name>", a name not taken): the trash
    file's name, chosen by the caller beforehand (LM2: a switch notes it before the move)."""
    if not rel or library_rel(data_dir, rel) is None:
        return None
    src = os.path.join(data_dir, _strip(rel))
    if not _ours_to_move(data_dir, rel, src):
        return None
    if not os.path.isfile(src):
        return None
    trash = os.path.join(data_dir, ".trash")
    os.makedirs(trash, exist_ok=True)
    if to is not None:
        name = to.split("/", 1)[1]
    else:
        base, ext = os.path.splitext(os.path.basename(src))
        stamp = time.strftime("%Y%m%d%H%M%S")
        name, n = f"{base}_{stamp}{ext}", 1
        while os.path.exists(os.path.join(trash, name)):
            name, n = f"{base}_{stamp}_{n}{ext}", n + 1
    dst = os.path.join(trash, name)
    if to is not None:
        rename_no_overwrite(src, dst)            # a chosen name is never written over
    else:
        os.rename(src, dst)
    restart_trash_clock(dst)
    return f".trash/{name}"


def _ours_to_move(data_dir, rel, src):
    """`trash_file`'s guard: a copy under the content folder only while its real path stays inside the data folder."""
    first = _strip(library_rel(data_dir, rel)).split("/", 1)[0]
    if path_key(first) != path_key(CONTENT_FOLDER):
        return True
    real, home = path_key(os.path.realpath(src)), path_key(os.path.realpath(data_dir)).rstrip("/")
    return real.startswith(home + "/")


def trash_refused(data_dir, rel):
    """Did `trash_file` leave a row's file where it is (None, yet the file is there)? Remove and every Undo of an add
    then refuse (`StoreConflict`) instead of dropping the row: a file left with no row is found again by the sync."""
    return bool(rel) and library_rel(data_dir, rel) is not None and os.path.isfile(os.path.join(data_dir, _strip(rel)))


def rename_no_overwrite(src, dst):
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


_rename_no_overwrite = rename_no_overwrite        # the name the store's own callers use


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
    something changed, 3 nothing, 4 no ready store, 5 an update staged or the store busy, 1 failed.
    Dialog-free."""
    from app.path_utils import get_data_path, get_user_files_path
    try:
        if update_staged():
            return EXIT_BUSY
        store = open_store(language, get_data_path(language), get_user_files_path(language), role="window")
        if store is None:
            return EXIT_NEEDS_YOU
        with store:
            return EXIT_DONE if store.sync_disk(folders=folders) else EXIT_NOTHING
    except StoreBusy:
        return EXIT_BUSY                                                # its own code: the window keeps it owed
    except Exception:
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
