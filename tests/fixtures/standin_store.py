"""A stand-in for the library store (W2.2; the window's spec RUNBOOK W2.2, 04 §4.3): the first screens draw from it at
real scale (2,000 and 20,000 files) before the window meets the real store (W3.1).

It mirrors `app/library_store.py`'s **read** API as the window uses it — names, signatures and shapes, nothing invented:
- 3.0-dev's reads: `check_mode`, `ordered`, `ids`, `item`, `versions`, `meta`, `token`, `changed_since`, `plan_current`,
  `journey_pending`;
- L3.1's (Kura, `kura/L3.1-store-additions`; its Inbox lines name them for the window): the change feed —
  `data_version()` and `read_feed(seen, epoch)` with `FEED_ITEM_FIELDS` / `FEED_WORK_FIELDS`, `FEED_POLL` — `pinned()`,
  `cards_of(item_ids)`, `MEDIA_TYPES`, `COVER_SOURCES`, and the Soon line as a count of files (`options["soon_line"]`).
Its rules are the store's: items in `(ord, id)` order per tier; Current = NOW then Soon; a piece = one contiguous run of
one work's items in one tier; `availability` is `available` or `missing`; status writes (watched, mined, pinned) move the
feed, never `changed_since`.

**A handle belongs to the thread that opened it**, as a sqlite3 connection does: a read from another thread raises
`ProgrammingError` (so a window that reads on the wrong thread fails here, not first at W3.1). Every handle reads the one
shared `StandinLibrary`; a commit made through the library (the tests' outside writer: a hato drop, another window)
moves `data_version` for every handle, as another connection's commit does.

Qt-free; test data only (it lives under `tests/`, and the app never imports it).
"""
import copy
import threading

FEED_POLL = 0.1
FEED_ITEM_FIELDS = ("id", "tier", "ord", "rel_path", "title", "parent_folder", "source_type", "availability",
                    "work_id", "piece_id", "watched", "mined_at", "pinned", "mine_asked", "graduated_at",
                    "in_learning_order", "added_at", "feed_in")
FEED_WORK_FIELDS = ("id", "title", "title_by_user", "titles", "folder_key", "anilist_id", "tmdb_id", "youtube_channel",
                    "media_type", "media_type_by", "cover_source", "cover_ref", "cover_path", "cover_fetched_at",
                    "cover_locked", "feed_in")
MEDIA_TYPES = ("anime", "drama", "movie", "youtube", "podcast", "audiobook", "book", "lightnovel", "manga", "game",
               "text")
COVER_SOURCES = ("anilist", "tmdb", "youtube", "file", "user", "generated")
READ_ORDER = {"arrivals": 0, "now": 1, "soon": 2, "goal": 3, "graduated": 9}
TIERS = tuple(READ_ORDER)
CURRENT = ("now", "soon")
MINE_LINE_DEFAULT = 20
SOON_LINE_NEW = 25
MODES = ("store", "json", "read-only")


class ProgrammingError(Exception):
    """A handle used from a thread other than the one that opened it (sqlite3's own message)."""


class StandinLibrary:
    """The shared library: items and works by id, the meta, and each item's cards. Thread-safe; tests change it through
    `commit` (as another program would) and the window's handles see it through the feed."""

    def __init__(self, items, works, meta=None, cards=None, mode="store", reason=None):
        self._lock = threading.RLock()
        self._items = {}
        self._works = {}
        self._gone = []                                # (feed_in, kind, id)
        self._cards = dict(cards or {})
        self._data_version = 1
        self.mode, self.reason = mode, reason
        m = {"epoch": 1, "state_version": 1, "order_version": 1, "availability_version": 1, "pins_version": 1,
             "analysed_order_version": 1, "planned_order_version": 1, "planned_pins_version": 1,
             "mine_line": MINE_LINE_DEFAULT, "soon_line": None, "arrivals_on": 1, "feed_floor": 0}
        m.update(meta or {})
        self._meta = m
        for row in items:
            r = {k: row.get(k) for k in FEED_ITEM_FIELDS}
            r["feed_in"] = r["feed_in"] or 1
            self._items[r["id"]] = r
        for row in works:
            w = {k: row.get(k) for k in FEED_WORK_FIELDS}
            w["feed_in"] = w["feed_in"] or 1
            self._works[w["id"]] = w
        self.reads = 0                                 # full and partial feed reads served (tests count them)

    # --- the store's module-level calls ---------------------------------------------------------------------- #
    def check_mode(self):
        """(mode, reason), as `library_store.check_mode`: `store` · `json` ("no store", "not ready", "migration failed")
        · `read-only` ("damaged", "made by a newer Surasura", "busy", "io: …")."""
        return self.mode, self.reason

    def open(self):
        """A handle for the calling thread (`open_store(...)`), or None when the mode isn't `store` (as the real one)."""
        if self.mode != "store":
            return None
        return StandinStore(self)

    def open_any(self):
        """A handle even when the mode isn't `store` (the rows the window shows read-only from the JSON copy, or the
        last saved state: the stand-in's one source)."""
        return StandinStore(self)

    # --- an outside writer (tests; a hato drop, another window, the command line) ------------------------------- #
    def commit(self, items=(), works=(), gone=(), meta=None, order=False, availability=False, pins=False,
               new_epoch=False):
        """Apply rows (dicts with an `id`; a known id is updated, an unknown one added) and tombstones (kind, id) in
        one transaction: `state_version` and every changed row's `feed_in` move; `order` / `availability` / `pins`
        move their versions (what `changed_since` and `plan_current` read). -> the new state version."""
        with self._lock:
            m = self._meta
            if new_epoch:
                m["epoch"] += 1
            m["state_version"] += 1
            v = m["state_version"]
            for row in items:
                cur = self._items.get(row["id"])
                r = dict(cur) if cur else {k: None for k in FEED_ITEM_FIELDS}
                r.update({k: row[k] for k in row if k in FEED_ITEM_FIELDS})
                r["feed_in"] = v
                self._items[r["id"]] = r
            for row in works:
                cur = self._works.get(row["id"])
                w = dict(cur) if cur else {k: None for k in FEED_WORK_FIELDS}
                w.update({k: row[k] for k in row if k in FEED_WORK_FIELDS})
                w["feed_in"] = v
                self._works[w["id"]] = w
            for kind, ident in gone:
                (self._items if kind == "item" else self._works).pop(ident, None)
                self._gone.append((v, kind, ident))
            for key, value in (meta or {}).items():
                m[key] = value
            if order:
                m["order_version"] += 1
            if availability:
                m["availability_version"] += 1
            if pins:
                m["pins_version"] += 1
            self._data_version += 1
            return v

    def set_mode(self, mode, reason=None):
        with self._lock:
            self.mode, self.reason = mode, reason

    def items(self):
        with self._lock:
            return [dict(r) for r in self._items.values()]


class StandinOpener:
    """`library_store.StoreOpener`'s shape: `check()` → the mode (never waits), `mode`, `reason`, `handle()` → this
    thread's long-lived handle (or None when the mode isn't `store`), `wait(timeout)`. `fallback_handle()`: the rows the
    window shows read-only while the store can't be used (*Getting ready*: the library's last copy) — the stand-in reads
    its own library for them."""

    closes_handles = True

    def __init__(self, library):
        self.library = library
        self.mode, self.reason = "json", "not checked"
        self._local = threading.local()

    def check(self):
        self.mode, self.reason = self.library.check_mode()
        return self.mode

    def wait(self, timeout=5.0):
        return self.check()

    def handle(self):
        if self.mode != "store":
            return None
        h = getattr(self._local, "store", None)
        if h is None or h.closed:
            h = self._local.store = StandinStore(self.library)
        return h

    def fallback_handle(self):
        h = getattr(self._local, "copy", None)
        if h is None or h.closed:
            h = self._local.copy = StandinStore(self.library)
        return h


class StandinStore:
    """One handle (one 'connection'), bound to the thread that opened it."""

    def __init__(self, library):
        self._lib = library
        self._thread = threading.get_ident()
        self.closed = False

    def _here(self):
        if self.closed:
            raise ProgrammingError("Cannot operate on a closed database.")
        if threading.get_ident() != self._thread:
            raise ProgrammingError("SQLite objects created in a thread can only be used in that same thread.")

    def close(self):
        self.closed = True

    # --- L3.1: the change feed ------------------------------------------------------------------------------------ #
    def data_version(self):
        self._here()
        with self._lib._lock:
            return self._lib._data_version

    def read_feed(self, seen=None, epoch=None):
        """`{full, epoch, version, items, works, gone, options}` (L3.1's `read_feed`): every row when `seen` is None,
        the epoch changed or `seen` is older than the tombstones kept; else the rows whose `feed_in` > `seen` and the
        tombstones since. The next `seen` is `version`."""
        self._here()
        lib = self._lib
        with lib._lock:
            m = lib._meta
            version, now_epoch = m["state_version"], m["epoch"]
            full = seen is None or epoch != now_epoch or seen < int(m.get("feed_floor") or 0)
            if full:
                items = [dict(r) for r in lib._items.values()]
                works = [dict(w) for w in lib._works.values()]
                gone = []
            else:
                items = [dict(r) for r in lib._items.values() if r["feed_in"] > seen]
                works = [dict(w) for w in lib._works.values() if w["feed_in"] > seen]
                gone = [(k, i) for f, k, i in lib._gone if f > seen]
            lib.reads += 1
            return {"full": full, "epoch": now_epoch, "version": version, "items": items, "works": works, "gone": gone,
                    "options": {"soon_line": m.get("soon_line"), "mine_line": m.get("mine_line", MINE_LINE_DEFAULT),
                                "arrivals_on": m.get("arrivals_on", 0)}}

    # --- 3.0-dev's reads --------------------------------------------------------------------------------------- #
    def _tier_rows(self, tier):
        if tier not in READ_ORDER:
            raise ValueError(f"unknown tier {tier!r}")
        rows = [r for r in self._lib._items.values() if r["tier"] == tier]
        rows.sort(key=lambda r: (r["ord"], r["id"]))
        return rows

    def ordered(self, tier):
        """[(item_id, entry, availability)] of a tier in order (the entry: the keys the window may read)."""
        self._here()
        with self._lib._lock:
            return [(r["id"], {"title": r["title"], "physical_path": r["rel_path"], "parent_folder": r["parent_folder"],
                               "source_type": r["source_type"]}, r["availability"]) for r in self._tier_rows(tier)]

    def ids(self, tier):
        self._here()
        with self._lib._lock:
            return [r["id"] for r in self._tier_rows(tier)]

    def item(self, item_id):
        self._here()
        with self._lib._lock:
            r = self._lib._items.get(item_id)
            if r is None:
                return None
            out = copy.deepcopy(r)
            out["entry"] = {"title": r["title"], "physical_path": r["rel_path"], "parent_folder": r["parent_folder"],
                            "source_type": r["source_type"]}
            return out

    def versions(self):
        self._here()
        with self._lib._lock:
            m = self._lib._meta
            return {k: m.get(k, 0) for k in ("epoch", "state_version", "order_version", "availability_version",
                                             "pins_version", "analysed_order_version", "planned_order_version",
                                             "planned_pins_version")}

    def meta(self):
        self._here()
        with self._lib._lock:
            return dict(self._lib._meta)

    def token(self):
        self._here()
        with self._lib._lock:
            m = self._lib._meta
            return (m["epoch"], m["order_version"], m["availability_version"], 0, 0)

    def changed_since(self, token):
        self._here()
        epoch, order, avail, _own_order, _own_avail = token
        with self._lib._lock:
            m = self._lib._meta
            return m["epoch"] != epoch or m["order_version"] != order or m["availability_version"] != avail

    def plan_current(self):
        self._here()
        with self._lib._lock:
            m = self._lib._meta
            return m["planned_order_version"] == m["order_version"] and m["planned_pins_version"] == m["pins_version"]

    def journey_pending(self):
        self._here()
        with self._lib._lock:
            m = self._lib._meta
            return m["analysed_order_version"] < m["order_version"]

    # --- L3.1's per-item reads ---------------------------------------------------------------------------------- #
    def pinned(self):
        """[(item_id, rel_path, tier, pinned_at)], oldest pin first (L3.1's `Pin` tuples)."""
        self._here()
        with self._lib._lock:
            rows = [r for r in self._lib._items.values() if r["pinned"]]
            rows.sort(key=lambda r: (r["pinned"], r["id"]))
            return [(r["id"], r["rel_path"], r["tier"], r["pinned"]) for r in rows]

    def cards_of(self, item_ids):
        """{item_id: [note ids]} for the items that have cards (L3.1)."""
        self._here()
        with self._lib._lock:
            return {i: list(self._lib._cards[i]) for i in item_ids if self._lib._cards.get(i)}
