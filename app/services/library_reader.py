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
- **The numbers** (*% known*, *N new*) come from a provider (the plan engine from W3.1; the seed's plan here):
  `numbers()` → (version, {item_id: (known_tokens, counted_tokens, n_new)}); a new version rebuilds the view. *Mining
  now* comes from Connect's status (`mining()` → item ids; none until Connect's record exists, 04 §4.4 gap 9).

Qt-free (the import guard): the window reaches it through `app/qt/bridge.py`.
"""
import json
import os
import threading
import time

from app.services import view_rows

POLL_S = 0.1                     # the store's FEED_POLL
CACHE_VERSION = 1


def cache_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"window_cache_{language}.json")


def _no_numbers():
    return (0, {})


def _no_mining():
    return ()


class LibraryReader:
    def __init__(self, opener, language="ja", numbers=None, mining=None, poll=POLL_S, cache_file=None,
                 cache_rows=view_rows.CACHE_ROWS):
        self.opener = opener
        self.language = language
        self.numbers = numbers or _no_numbers
        self.mining = mining or _no_mining
        self.poll = poll
        self.cache_file = cache_file
        self.cache_rows = cache_rows
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
        self.reads = 0                     # feed reads (tests)
        self.builds = 0                    # views built (tests)

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
            h = self.opener.handle()
            if h is not None and hasattr(h, "close") and getattr(self.opener, "closes_handles", False):
                h.close()
        except Exception:
            pass

    def _handle(self):
        mode = self.opener.check()
        reason = getattr(self.opener, "reason", None)
        if mode == "store":
            return mode, reason, self.opener.handle()
        fallback = getattr(self.opener, "fallback_handle", None)
        return mode, reason, (fallback() if fallback is not None else None)

    def _look(self):
        mode, reason, h = self._handle()
        changed_mode = (mode, reason) != self._mode
        self._mode = (mode, reason)
        version, numbers = self.numbers()
        if h is None:
            if changed_mode or self._view is None:
                self._items, self._works, self._cards, self._seen = {}, {}, {}, None
                self._publish(self._build(numbers, mode, reason, rows_known=False))
            return
        dv = h.data_version()
        if not changed_mode and dv == self._data_version and version == self._numbers_version \
                and self._view is not None and not self._view.busy:
            return
        feed = h.read_feed(self._seen, self._epoch)
        self.reads += 1
        self._merge(feed)
        ids = [r["id"] for r in feed["items"]]
        if feed["full"]:
            self._cards = {}
        if ids and hasattr(h, "cards_of"):
            got = h.cards_of(ids)
            for i in ids:
                if i in got:
                    self._cards[i] = len(got[i])
                else:
                    self._cards.pop(i, None)
        self._data_version = dv
        self._numbers_version = version
        view = self._build(numbers, mode, reason, rows_known=True)
        self._publish(view)
        if mode == "store" and self.cache_file:
            self._write_cache(view, h)

    def _merge(self, feed):
        if feed["full"]:
            self._items = {r["id"]: r for r in feed["items"]}
            self._works = {w["id"]: w for w in feed["works"]}
        else:
            for r in feed["items"]:
                self._items[r["id"]] = r
            for w in feed["works"]:
                self._works[w["id"]] = w
            for kind, ident in feed["gone"]:
                (self._items if kind == "item" else self._works).pop(ident, None)
                if kind == "item":
                    self._cards.pop(ident, None)
        self._options = dict(feed.get("options") or {})
        self._seen, self._epoch = feed["version"], feed["epoch"]

    def _build(self, numbers, mode, reason, rows_known):
        self.builds += 1
        return view_rows.build(self._items, self._works, self._options, numbers=numbers, cards=self._cards,
                               mining=set(self.mining()), language=self.language, mode=mode, reason=reason,
                               loading=not rows_known)

    def _busy(self, error):
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
    def _key(self, h):
        v = h.versions()
        return [v.get("epoch"), v.get("order_version"), v.get("availability_version"),
                v.get("planned_order_version"), self.numbers()[0]]

    def _first_screen(self):
        if not self.cache_file or not os.path.exists(self.cache_file):
            return
        mode, _reason, h = self._handle()
        if mode != "store" or h is None:
            return
        with open(self.cache_file, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or data.get("key") != self._key(h):
            return
        view = view_rows.from_cache(data.get("view"), language=self.language)
        if view is not None and self._view is None:
            self._publish(view)

    def _write_cache(self, view, h):
        try:
            data = {"version": CACHE_VERSION, "key": self._key(h), "written_at": time.time(),
                    "view": view_rows.to_cache(view, self.cache_rows)}
            tmp = self.cache_file + ".tmp"
            os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.cache_file)
        except OSError:
            pass                                    # a cache that can't be written is only slower next time
