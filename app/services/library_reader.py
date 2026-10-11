"""The window's library reader (W2.2; the window's spec 04 §4.1, 02 §2.1, §2.4): the one place the window reads the
library store, on a plain thread of its own — never the window's thread.

- **Its own handle.** A store handle belongs to the thread that opened it (a sqlite3 connection), so the reader opens
  it on its thread through the opener (`library_store.StoreOpener`'s shape: `check()` → the mode, `reason`, `handle()`
  → this thread's store or None).
- **The change feed.** Every `poll` seconds (the store's `FEED_POLL`, 0.1 s: one `data_version()`, ~5 µs) it looks; when
  the number moved it reads `read_feed(seen, epoch)`, merges the rows by id into its own copy of the library
  (idempotent: the window's own commits come back too), and builds the view (`view_rows.build`), which it hands on
  through `subscribe(cb)` — called on this thread; the window's bridge queues it to the GUI thread.
- **The first screen's cache** (02 §2.1): before the first read, `window_cache_<lang>.json` is shown if its key (the
  store's epoch, order and availability versions, the plan's version) still matches; the live view replaces it. It is
  written from a full view only (rows the store has confirmed), atomically, off the window's thread.
- **The store's state** (02 §2.4): `store` → the live rows; `json` → *Getting ready* (rows read-only from the opener's
  fallback, the last copy, when it has one); `read-only` → the rows with the store's reason. A read that fails (the
  store busy, a raw database error) keeps the last view, marked busy, and tries again at the next poll.
- **Python's collector** (`freeze_gc`, off by default; the window process turns it on — `tests/qt/try_screens.py`, the
  bench — and the tests leave it off, so a test's own cycles are still collected): after each view is built, everything alive is moved out of the collector's
  sight (`gc.freeze()`). The library copy and the view are large (hundreds of thousands of objects at 20,000 files),
  long-lived and free of cycles (refcounting frees an old view the moment the window lets go of it); a full collection
  walking them holds Python's lock — every thread, the window's too — for as long as the walk takes
  (`tests/qt/bench_scroll.py` measures it, with and without).
- **The numbers** (*% known*, *N new*) come from a provider (the plan engine from W3.1; the seed's plan here):
  `numbers()` → (version, {item_id: (known_tokens, counted_tokens, n_new)}); a new version rebuilds the view. *Mining
  now* comes from Connect's status (`mining()` → item ids; none until Connect's record exists, 04 §4.4 gap 9).

Qt-free (the import guard): the window reaches it through `app/qt/bridge.py`.
"""
import gc
import json
import os
import threading
import time

from app.services import view_rows

POLL_S = 0.1                     # the store's FEED_POLL
MODE_RECHECK_S = 2.0             # while the store can't be used, its mode is asked again this often
CACHE_LATEST_S = 5.0             # the first screen's cache waits for a quiet look at most this long
CARDS_ALL_S = 2.0                # every item's cards asked again at most this often (between, only what changed)
CACHE_VERSION = 4                # 2: keyed (store id, epoch, state version, plan version); 3: an episode's `deleted`;
#                                  4: a status's words and tips (G2.3: ✓ N, a tip's action on a line of its own)


def cache_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"window_cache_{language}.json")


def _no_numbers():
    return (0, {})


def _no_mining():
    return ()


class LibraryReader:
    def __init__(self, opener, language="ja", numbers=None, mining=None, poll=POLL_S, cache_file=None,
                 cache_rows=view_rows.CACHE_ROWS, freeze_gc=False):
        self.opener = opener
        self.language = language
        self.numbers = numbers or _no_numbers
        self.mining = mining or _no_mining
        self.poll = poll
        self.cache_file = cache_file
        self.cache_rows = cache_rows
        self.freeze_gc = bool(freeze_gc)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._subscribers = []
        self._thread = None
        self._view = None
        # the reader thread's own copy of the library (touched only there)
        self._items, self._works, self._cards = {}, {}, {}
        self._options = {}
        self._seen = self._epoch = None
        self._data_version = None
        self._numbers_version = None
        self._mode = None
        self.row_cache = view_rows.RowCache()       # rows kept between builds (the reader's thread only)
        self._tiers, self._pos, self._dirty = None, {}, set()
        self._moved_in = {}                # tier -> ids that came into it or moved in it since it was last sorted
        self._changed_ids = None
        self._build_changed = None         # ids changed or gone since the last build (None: a full read, all looked at)
        self._build_works = None           # ... and the works (`view_rows.build`'s `changed_works`)
        self._cache_due = None             # (view, key) to write as the first screen's cache, at the next quiet look
        self._cache_due_at = 0.0           # when a write first fell due (a store busy for long still gets one)
        self._cards_all_at = 0.0
        self._cards_stale = False
        self._mode_at = 0.0
        self._recheck = False
        self._store_id = None
        self.reads = 0                     # feed reads (tests)
        self.builds = 0                    # views built (tests)
        self.skipped = 0                   # reads that changed nothing the window shows (tests)

    # --- the window's side --------------------------------------------------------------------------------------- #
    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

    def view(self):
        with self._lock:
            return self._view

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="library-reader", daemon=True)
            self._thread.start()
        return self

    def refresh(self):
        """Look now, rather than at the next poll (the window's own change, a test)."""
        self._wake.set()

    def stop(self, timeout=2.0):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    # --- the thread ------------------------------------------------------------------------------------------------- #
    def _run(self):
        try:
            self._first_screen()
        except Exception:
            pass                                    # a cache that can't be read is no cache
        while not self._stop.is_set():
            try:
                self._look()
            except Exception as e:                  # never dies of a read: the last view, marked busy
                self._busy(e)
            self._wake.wait(self.poll)
            self._wake.clear()
        try:
            self._flush_cache()                         # the last view's cache, as the window closes
        except Exception:
            pass                                        # never in the way of closing (the store's handle below)
        try:
            h = self.opener.handle()
            if h is not None and hasattr(h, "close") and getattr(self.opener, "closes_handles", False):
                h.close()
        except Exception:
            pass

    def _handle(self):
        """(mode, reason, handle). The mode is asked of the opener at the start, after a failed read, and every few
        seconds while the store can't be used — never on every poll (the store's `StoreOpener.check` probes the file)."""
        now = time.monotonic()
        stale = self._mode is None or self._recheck or (self._mode[0] != "store" and
                                                         now - self._mode_at >= MODE_RECHECK_S)
        if stale:
            mode = self.opener.check()
            reason = getattr(self.opener, "reason", None)
            self._mode_at, self._recheck = now, False
        else:
            mode, reason = self._mode
        if mode == "store":
            return mode, reason, self.opener.handle()
        fallback = getattr(self.opener, "fallback_handle", None)
        return mode, reason, (fallback() if fallback is not None else None)

    def _look(self):
        mode, reason, h = self._handle()
        changed_mode = (mode, reason) != self._mode
        self._mode = (mode, reason)
        version, numbers = self.numbers()
        if h is None:                                   # nothing to read: the last rows stay, under the mode's bar
            if changed_mode or self._view is None or version != self._numbers_version:
                self._numbers_version = version         # the numbers' own version: a new one empties the row cache
                self._publish(self._build(numbers, mode, reason, rows_known=self._seen is not None))   # (review B-12)
            return
        dv = h.data_version()
        cards_due = self._cards_stale and time.monotonic() - self._cards_all_at >= CARDS_ALL_S
        if not changed_mode and dv == self._data_version and version == self._numbers_version \
                and self._view is not None and not self._view.busy and not cards_due:
            self._flush_cache()
            return
        feed = h.read_feed(self._seen, self._epoch)
        self.reads += 1
        options_before = dict(self._options)
        self._merge(feed)
        cards = self._card_counts(h)
        changed = (feed["full"] or feed["items"] or feed["works"] or feed["gone"] or changed_mode
                   or self._options != options_before or version != self._numbers_version
                   or cards != self._cards or self._view is None or self._view.busy or self._view.cached)
        self._cards = cards
        self._data_version = dv
        self._numbers_version = version
        if self._store_id is None and hasattr(h, "meta"):
            self._store_id = h.meta().get("store_id")
        if not changed:                                 # data_version moved with nothing for the window (a checkpoint)
            self.skipped += 1
            self._flush_cache()                         # a look with nothing new: as quiet as one that read nothing
            return
        view = self._build(numbers, mode, reason, rows_known=True)
        self._publish(view)
        if self.freeze_gc:
            gc.freeze()
        if mode == "store" and self.cache_file:
            # written at the next look that finds nothing new, not now: the window is taking this view in at this
            # very moment, and the cache's JSON would hold Python's lock against it (speed round 5)
            if self._cache_due is None:
                self._cache_due_at = time.monotonic()
            self._cache_due = (view, [self._store_id, feed["epoch"], feed["version"], version])
            if time.monotonic() - self._cache_due_at >= CACHE_LATEST_S:
                self._flush_cache()                     # a store that never rests: written anyway, now and then

    def _card_counts(self, h):
        """{item_id: cards} for the items whose rows show cards (Current, Finished). A card made for an item doesn't
        move its row in the feed (`record_made`), so every item is asked again at most every CARDS_ALL_S; between, only
        the items the feed changed. The same dict object comes back when nothing changed (the row cache reads that)."""
        if not hasattr(h, "cards_of"):
            return {}
        now = time.monotonic()
        if self._changed_ids is None or now - self._cards_all_at >= CARDS_ALL_S:
            ids = [i for i, r in self._items.items() if r.get("tier") in ("now", "soon", "graduated")]
            self._cards_all_at = now
            self._cards_stale = False
            got = h.cards_of(ids)
            new = {i: len(v) for i, v in got.items() if v}
        else:
            self._cards_stale = True                    # a card may be made elsewhere: every item asked again soon
            ids = [i for i in self._changed_ids if i in self._items]
            got = h.cards_of(ids) if ids else {}
            new = dict(self._cards)
            for i in ids:
                n = len(got.get(i) or ())
                if n:
                    new[i] = n
                else:
                    new.pop(i, None)
        self._changed_ids = set()
        return self._cards if new == self._cards else new

    def _merge(self, feed):
        if feed["full"]:
            self._items = {r["id"]: r for r in feed["items"]}
            self._works = {w["id"]: w for w in feed["works"]}
            self._tiers = None                          # sorted again in full at the next build
            self._changed_ids = None
            self._build_changed = None
            self._build_works = None
        else:
            changed = self._changed_ids if self._changed_ids is not None else set()
            for r in feed["items"]:
                old = self._items.get(r["id"])
                self._items[r["id"]] = r
                changed.add(r["id"])
                if self._tiers is None:
                    continue
                if old is None or old.get("tier") != r.get("tier") or old.get("ord") != r.get("ord"):
                    self._dirty.add(r.get("tier"))      # it moved: its tiers are sorted again
                    self._moved_in.setdefault(r.get("tier"), set()).add(r["id"])
                    if old is not None:
                        self._dirty.add(old.get("tier"))
                else:                                   # the same place: swapped in, no sort
                    at = self._pos.get(r["id"])
                    if at is not None:
                        self._tiers[at[0]][at[1]] = r
                    else:
                        self._dirty.add(r.get("tier"))
                        self._moved_in.setdefault(r.get("tier"), set()).add(r["id"])
            for w in feed["works"]:
                self._works[w["id"]] = w
            if self._build_changed is not None:
                self._build_changed.update(r["id"] for r in feed["items"])
                self._build_changed.update(ident for kind, ident in feed["gone"] if kind == "item")
            if self._build_works is not None:
                self._build_works.update(w["id"] for w in feed["works"])
                self._build_works.update(ident for kind, ident in feed["gone"] if kind != "item")
            for kind, ident in feed["gone"]:
                if kind == "item":
                    old = self._items.pop(ident, None)
                    if old is not None and self._tiers is not None:
                        self._dirty.add(old.get("tier"))
                else:
                    self._works.pop(ident, None)
            self._changed_ids = changed
        self._options = dict(feed.get("options") or {})
        self._seen, self._epoch = feed["version"], feed["epoch"]

    def _sorted_tiers(self):
        """Each tier's items in `(ord, id)` order: in full after a full read, else only the tiers something moved in."""
        if self._tiers is None:
            self._tiers = view_rows._by_tier(self._items)
            self._dirty, self._moved_in = set(), {}
            self._pos = {r["id"]: (t, i) for t, rows in self._tiers.items() for i, r in enumerate(rows)}
        elif self._dirty:
            for t in self._dirty:
                if t is None:
                    continue
                # the tier's own items and those that came into it, not all 20,000 (speed round 5: an arrival's
                # sort walked every item on the reader's thread); one gone or moved out drops out here
                ids = {r["id"] for r in self._tiers.get(t, ())} | self._moved_in.pop(t, set())
                items = self._items
                rows = [items[i] for i in ids if i in items and items[i].get("tier") == t]
                rows.sort(key=lambda r: (r.get("ord") or 0.0, r["id"]))
                self._tiers[t] = rows
                for i, r in enumerate(rows):
                    self._pos[r["id"]] = (t, i)
            self._dirty, self._moved_in = set(), {}
        return self._tiers

    def _build(self, numbers, mode, reason, rows_known):
        self.builds += 1
        view = view_rows.build(self._items, self._works, self._options, numbers=(self._numbers_version, numbers),
                               cards=self._cards, mining=set(self.mining()), language=self.language, mode=mode,
                               reason=reason, loading=not rows_known, cache=self.row_cache,
                               tiers=self._sorted_tiers() if self._items else None, changed=self._build_changed,
                               changed_works=self._build_works)
        self._build_changed = set()                     # built: from here on, only what the feed changes
        self._build_works = set()
        return view

    def _busy(self, error):
        self._recheck = True                            # a failed read: ask the store's mode again next time
        with self._lock:
            view = self._view
        if view is not None and not view.busy:
            self._publish(view._replace(busy=True))
        elif view is None:
            self._publish(view_rows.build({}, {}, {}, language=self.language, mode="store", busy=True, loading=True))

    def _publish(self, view):
        with self._lock:
            self._view = view
            subscribers = list(self._subscribers)
        for cb in subscribers:
            try:
                cb(view)
            except Exception:
                pass                                # a listener's fault never stops the reader

    # --- the first screen's cache (02 §2.1) ---------------------------------------------------------------- #
    def _key_now(self, h):
        """The key the store holds now: (its id, epoch, state version) and the plan's version — what a feed read at
        this moment would carry (`read_feed`'s epoch and version are the meta's)."""
        m = h.meta()
        return [m.get("store_id"), m.get("epoch"), m.get("state_version"), self.numbers()[0]]

    def _first_screen(self):
        if not self.cache_file or not os.path.exists(self.cache_file):
            return
        mode, _reason, h = self._handle()
        if mode != "store" or h is None:
            return
        with open(self.cache_file, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or data.get("key") != self._key_now(h):
            return
        view = view_rows.from_cache(data.get("view"), language=self.language)
        if view is not None and self._view is None:
            self._publish(view)

    def _flush_cache(self):
        due, self._cache_due = self._cache_due, None
        if due is not None:
            self._write_cache(*due)

    def _write_cache(self, view, key):
        try:
            data = {"version": CACHE_VERSION, "key": key, "written_at": time.time(),
                    "view": view_rows.to_cache(view, self.cache_rows)}
            tmp = self.cache_file + ".tmp"
            os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.cache_file)
        except OSError:
            pass                                    # a cache that can't be written is only slower next time
