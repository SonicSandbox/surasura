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
- **Python's collector** (`freeze_gc`, off by default; the window process turns it on — `shell.main`,
  `tests/qt/try_screens.py`, the benches — and the tests leave it off, so a test's own cycles are still collected): after
  each view is built, everything alive is moved out of the collector's sight (`gc.freeze()`). The library copy and the
  view are large (hundreds of thousands of objects at 20,000 files), long-lived and free of cycles (refcounting frees an
  old view the moment the window lets go of it); a full collection walking them holds Python's lock — every thread, the
  window's too — for 40–75 ms at 20,000 files, whichever thread's allocation set it off (A4 P-gil:
  `tests/qt/bench_gil.py` measures it; every window tick late by more than 16 ms behind a background job was one).
  A look whose build will be frozen pauses the collector until then (`_pause_gc`: the build's own allocations set off
  full collections too). A reader's stop gives everything back to the collector (`gc.unfreeze()`), so a library a
  language switch let go is freed; the next reader then never freezes its first view (the switch still holds the old
  library while it is built) and collects once before its first freeze (`_freeze`: the old library, let go by then, is
  freed, never frozen).
- **The numbers** (*% known*, *N new*) come from a provider (the plan engine from W3.1; the seed's plan here):
  `numbers()` → (version, {item_id: (known_tokens, counted_tokens, n_new)}); a new version rebuilds the rows holding the
  items it changed when the provider says which (`numbers.changed(since)`, W3.1a's `moves.Numbers`: a drop moves *N new*
  on a few rows), else every row. *Mining now* comes from Connect's status (`mining()` → item ids; none until Connect's
  record exists, 04 §4.4 gap 9).
- **Connect's feed** (P4.1 L2, row 4.1.10, W-A1): `connect()` → the `app/connect/feed.Feed` to build with (the window's
  `feed.Provider.latest`: what the status line's last tick read — no stamp of its own) or None; another Feed object
  than the last view's builds the view again (the Provider's `on_change` wakes the reader), the same one builds
  nothing (S19).
- **It wakes on the bell** (W3.2 B; IK0-5, L3.1-4: "let windows handle it but with the fallback"): given `watch`
  (`watch(store, wake)` -> an opened `library_watch.Lookout` on the reader's own wake event — the shell's
  `library_lookout`), made on this thread once the store can be used, the reader sleeps until the store's bell rings
  (any process's commit, the window's own writer's too), the tree watch reports a folder (a hand copy, hato's drop) or
  one of its own retries falls due (a failed read, the cache's quiet look, the cards' re-ask, the mode's recheck) —
  never every `poll` while the bell is live; with no bell (deaf: no slot, not Windows) it looks every `poll` as
  before. The folders the watch reports (all of them at the open and when Windows lost track; the slow look's
  without a watch) are synced on a worker of its own (`library_store.sync_for_window`, its own handle), never this
  thread or the window's; the sync's commit rings the bell back here. Without `watch`: every `poll`, as before.
- **▶'s answers** (row 55, `play`: an `app/services/play.Looks`, the window's; None in the tests and tools): after
  each build the rows it built anew hand their episodes' asks to the looker, which looks on its own worker and hands
  its answers back (`set_playable`) — a build then rebuilds only the rows whose answer moved. A folder the watch synced
  is looked at again (its episodes), a full sync and a new Connect feed (its index file changed) the ones not found;
  the first screen's cache seeds the answers.
- **A burst builds a few views a second** (a4, `coalesce`: off by default, the window's reader turns it on): a change
  within `COALESCE_S` of the last view built waits for that much to pass — a + Add, a look or an import committing
  batch after batch is a few views a second, the last change always in the last — and the numbers' new version with the
  store unchanged waits `NUMBERS_GRACE_S` for the write it comes just before (a move: one view, never two). The window's
  own asks build at once: a drop (`release`), the settle's `republish`, an expectation (`expect`), a mode, a full read,
  and for a second after the window hands its writer a learner's command (`urgent`), that command's views.
- **A drag holds it** (06 E6, `hold()` / `release()`): while held it still reads and merges the feed (its copy stays
  current) but builds and publishes nothing, so nothing moves under the hand; `release()` builds and publishes once. An
  item gone meanwhile is told at once (`subscribe_gone(cb)`: `cb(item_ids)`) — the drag of a removed item is let go.
- **What arrived** (Hon a7, `subscribe_arrived(cb)`: `cb(work_ids)`; None at the first read): after each read, the
  works whose files arrived or changed (a look, + Add, Extract, a drop; an item regrouped) — the window's covers look
  at those titles only (`app/qt/covers.look`), never the library again.

Qt-free (the import guard): the window reaches it through `app/qt/bridge.py`.
"""
import bisect
import gc
import json
import os
import threading
import time
import weakref

from app.services import view_rows

POLL_S = 0.1                     # the store's FEED_POLL
_THAWED = [False]                # A4 P-gil: a reader stopped since the last freeze (its library may still be held)
MODE_RECHECK_S = 2.0             # while the store can't be used, its mode is asked again this often
CACHE_LATEST_S = 5.0             # the first screen's cache waits for a quiet look at most this long
CARDS_ALL_S = 2.0                # every item's cards asked again at most this often (between, only what changed)
# --- a4 (A2, the commit storm): a burst of changes — a + Add, a look or an import committing batch after batch — builds
# at most one view this often, the last change never lost (the build waits, it is never skipped); the window's own
# asks (a drop, the settle's republish, an expectation, a mode) build at once
COALESCE_S = 0.25
# a4 (C2): the numbers' new version with the store unchanged waits this long for the write it comes just before (the
# window's writer works a move's numbers out, then writes it): the move's one view holds both, never two builds a move
NUMBERS_GRACE_S = 0.05
# a4: the window's own command (`urgent`): for this long its numbers and its write build at once, a burst's hold-back aside
URGENT_S = 1.0
# --- end a4
CACHE_VERSION = 5                # 2: keyed (store id, epoch, state version, plan version); 3: an episode's `deleted`;
#                                  4: a status's words and tips (G2.3: ✓ N, a tip's action on a line of its own);
#                                  5: `can_play` is ▶'s found file (row 55), and the seed of its answers


def cache_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"window_cache_{language}.json")


FEW_SORTED = 64                  # a tier with at most this many ids touched: they are put in place, never a full sort


def _sort_key(r):
    return (r.get("ord") or 0.0, r["id"])       # `view_rows._by_tier`'s order


def _no_numbers():
    return (0, {})


def _no_mining():
    return ()


def _no_connect():
    return None


def _hand_folders(ref, found):
    """New arrivals' folders to the reader, while it is alive (A4B-8)."""
    reader = ref()
    if reader is not None:
        reader.set_folders(found)


def _hand_playable(ref, answers):
    """▶'s answers to the reader, while it is alive (row 55)."""
    reader = ref()
    if reader is not None:
        reader.set_playable(answers)


class LibraryReader:
    def __init__(self, opener, language="ja", numbers=None, mining=None, poll=POLL_S, cache_file=None,
                 cache_rows=view_rows.CACHE_ROWS, freeze_gc=False, watch=None, connect=None, play=None,
                 coalesce=False):
        self.opener = opener
        self.language = language
        self.numbers = numbers or _no_numbers
        self.mining = mining or _no_mining
        self.connect = connect or _no_connect       # P4.1 L2: Connect's feed (row 4.1.10)
        self._connect_built = None                  # ... the Feed the last view was built with
        # --- row 55: ▶'s answers (`play.Looks`), handed back through a weak reference (never a cycle reader -> looker
        # -> reader: a reader a language switch let go is freed by its count alone, AD0-2)
        self.play = play
        self._playable = None if play is None else {}
        self._playable_new = False
        self._play_rows = {}                        # key -> the row the last build asked for (a new object: asked)
        if play is not None:
            import weakref
            me = weakref.ref(self)
            play.on_change = lambda answers: _hand_playable(me, answers)
        # --- end row 55
        self.poll = poll
        self.cache_file = cache_file
        self.cache_rows = cache_rows
        self.freeze_gc = bool(freeze_gc)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._subscribers = []
        self._move_subscribers = []
        self._gone_subscribers = []
        self._arrived_subscribers = []     # Hon a7: told the works whose files arrived or changed (`_arrived`)
        self._version_subscribers = []     # finish-pending: told every move of the versions (the planned ones too)
        self._hold = threading.Event()     # a drag holds the view (E6)
        self._held_dirty = False           # something came in while held: built and published at the release
        self._republish = False            # the drag's settle asked for the store's view (`republish`)
        self._thread = None
        self._view = None
        # the reader thread's own copy of the library (touched only there)
        self._items, self._works, self._cards = {}, {}, {}
        self._pieces = {}                  # LM11b G1: the feed's pieces {id: {id, title, kind}} (a group's kind and name)
        self._options = {}
        self._seen = self._epoch = None
        self._data_version = None
        self._numbers_version = None
        self._built_numbers = None         # the numbers' version the row cache last built with (`numbers.changed`)
        self._mode = None
        self.row_cache = view_rows.RowCache()       # rows kept between builds (the reader's thread only)
        self._tiers, self._pos, self._dirty = None, {}, set()
        self._moved_in = {}                # tier -> ids that came into it, moved in it or left it since it was last sorted
        self._changed_ids = None
        self._build_changed = None         # ids changed or gone since the last build (None: a full read, all looked at)
        self._build_works = None           # ... and the works (`view_rows.build`'s `changed_works`)
        self._cache_due = None             # (view, key) to write as the first screen's cache, at the next quiet look
        self._cache_due_at = 0.0           # when a write first fell due (a store busy for long still gets one)
        self._cards_all_at = 0.0
        self._cards_stale = False
        self._cards_asked = {}             # item -> its cards when last asked, for every item asked (`cards_rose`)
        self._cards_rose = 0               # how many times an item asked before came back with more cards
        self._mode_at = 0.0
        self._recheck = False
        self._store_id = None
        self._emptied = None                # A5K-2: the store's `emptied()` note, read with every look
        self._order_key = None             # (epoch, order_version, pins_version) the last read found
        self._versions_seen = None         # finish-pending: every version the last read found
        self.reads = 0                     # feed reads (tests)
        self.builds = 0                    # views built (tests)
        self.skipped = 0                   # reads that changed nothing the window shows (tests)
        # --- a4: a view owed (`COALESCE_S`, `NUMBERS_GRACE_S`): built once it falls due, whatever else comes meanwhile
        self._built_at = None              # when a look last built and published a view
        self._view_owed = False
        self._owed_at = 0.0                # when the owed view falls due
        self._numbers_at = None            # when a numbers' version with the store unchanged was first seen
        self._numbers_dv = None            # ... and the store's data_version then (the write moves it)
        self.held_back = 0                 # looks whose build waited (tests)
        self._held_at = None               # fix round (IK-2): when a look's build last waited (a burst under way)
        self._urgent_until = 0.0           # the window's own command on its way (`urgent`)
        self.coalesce = bool(coalesce)     # off by default (a test's looks each build); the window turns it on
        # --- end a4
        # --- W3.2 Q1: New arrivals' estimates ({item_id: N new}, the window's `arrivals.ArrivalNumbers`), built into
        # the next view (`view_rows.build(estimates=)`); new ones rebuild it (only the arrivals' rows change)
        self._estimates = {}
        self._estimates_new = False
        # --- end W3.2 Q1
        # --- A4B-8: New arrivals' folders ({first item id: where its original sits}, the looks' answers), named into
        # the next view on this thread (`view_rows.build(folders=)`) — never on the window's; new ones rebuild it
        self._folders = {}
        self._folders_version = 0
        self._folders_new = False
        self._folders_ask = None           # (ask, then): the looks' `folders`, handed by the window (`follow_folders`)
        self._folders_asked = set()
        self._folders_owed = False         # ... the last view's arrivals to ask at the next look (no build for it)
        # --- end A4B-8
        # --- LM11b G5: a window command not written yet ({item_id: tier}, `expect`), built in until the feed holds it
        self._expected = {}
        self._expected_new = None          # the window's newest, taken in by the next look
        self._overlaid = {}                # id -> (its feed row, tier, ord, the row as built in): kept while the same
        self._overlay_tiers = {}           # tier -> (reader's list, ids built in, list as built in, ids taken out)
        self._cache_owed = None            # the store's key a view holding the expectation was built at (never cached)
        # --- end LM11b G5
        # --- W3.2 B: the bell and the tree watch (`watch`), the folders they report synced on a worker of its own
        self.watch = watch
        self._lookout = None
        self._syncer = None
        self._owed = (set(), False, False)  # (folders, full, slow) still to sync (a busy store's are tried again)
        self._syncing = False
        self._disk_poll = None             # the slow look's `DiskPoll` (the sync worker's own)
        self.looks = 0                     # looks at the store (tests: an idle reader on the bell makes none)
        self.syncs = 0                     # syncs the watch asked for (tests)
        # --- end W3.2 B

    # --- the window's side --------------------------------------------------------------------------------------- #
    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

    def subscribe_moves(self, callback):
        """`callback(language, versions)` once per move of the order or the pins (any writer), on the reader's thread."""
        with self._lock:
            self._move_subscribers.append(callback)

    def subscribe_versions(self, callback):
        """finish-pending: `callback(versions)` once per move of any of the store's versions — a re-order recorded
        (`planned_order_version`, any process) too —, on the reader's thread."""
        with self._lock:
            self._version_subscribers.append(callback)

    def unsubscribe_versions(self, callback):
        """`callback` (the very one subscribed) told no more."""
        with self._lock:
            self._version_subscribers = [cb for cb in self._version_subscribers if cb is not callback]

    def subscribe_gone(self, callback):
        """`callback(item_ids)` for the items the feed lets go of while a drag holds the view, on the reader's thread."""
        with self._lock:
            self._gone_subscribers.append(callback)

    def unsubscribe_gone(self, callback):
        """`callback` (the very one subscribed) told no more: a window's drag controller let go."""
        with self._lock:
            self._gone_subscribers = [cb for cb in self._gone_subscribers if cb is not callback]

    def subscribe_arrived(self, callback):
        """Hon a7: `callback(work_ids)` for the works whose files arrived or changed since the last read (`_arrived`;
        None at the first read: the whole library) — on the reader's thread, so it only hands them on (the window's
        covers look on a worker of their own)."""
        with self._lock:
            self._arrived_subscribers.append(callback)

    # --- W3.2 Q1
    def set_estimates(self, estimates):
        """New arrivals' numbers ({item_id: N new}), from any thread: built into the next view, looked at now."""
        new = dict(estimates or {})
        with self._lock:
            if new == self._estimates:
                return                                  # W3.2 S2: the same numbers build nothing
            self._estimates = new
            self._estimates_new = True
        self._wake.set()
    # --- end W3.2 Q1

    # --- A4B-8
    def follow_folders(self, ask):
        """New arrivals' folders asked through `ask(item_ids, then)` (the looks' `folders(..., detail=True)`; None: no
        looks) — every arrival's first file asked afresh at the next look (no view built for it), its answers (`then`,
        any thread) named into the views from then on. Any thread."""
        me = weakref.ref(self)                          # (never a cycle reader -> ask -> reader: AD0-2)
        with self._lock:
            self._folders_ask = None if ask is None else (ask, lambda found: _hand_folders(me, found))
            self._folders_asked = set()
            self._folders_owed = True
        self._wake.set()

    def set_folders(self, found):
        """The looks' answers ({item_id: where its original sits, or None}), from any thread: built into the next view
        when any moved (a file from no folder read names nothing: no view for it)."""
        if not isinstance(found, dict):
            return
        with self._lock:
            moved = {k: v for k, v in found.items() if self._folders.get(k) != v}
            if not moved:
                return                                  # the same answers build nothing (S19)
            self._folders = {**self._folders, **moved}
            self._folders_version += 1
            self._folders_new = True
        self._wake.set()

    def _ask_folders(self, view):
        """(The reader's thread.) The arrivals' first files no answer was asked for yet, asked of the looks."""
        with self._lock:
            ask, asked = self._folders_ask, self._folders_asked
        if ask is None or not view.arrivals:
            return
        want = [a.item_ids[0] for a in view.arrivals if a.item_ids and a.item_ids[0] not in asked]
        if not want:
            return
        asked.update(want)
        try:
            ask[0](want, ask[1])
        except Exception as e:                          # (the looks closing: the next view asks again)
            asked.difference_update(want)
            print(f"Library reader: the arrivals' folders weren't asked: {e!r}")
    # --- end A4B-8

    # --- row 55
    def set_playable(self, answers):
        """▶'s answers ({item_id: found}, the looker's), from any thread: built into the next view, looked at now."""
        with self._lock:
            if answers == self._playable:
                return                                  # S19: the same answers build nothing
            self._playable = answers
            self._playable_new = True
        self._wake.set()

    def _ask_play(self, view):
        """The episodes' asks of the rows this build made anew, to the looker (an unchanged row is the same object:
        nothing asked, nothing looked at); the episodes of the rows gone and in no row now, forgotten (fix round A-8:
        a finished or removed item is never looked at again)."""
        before, now, asks = self._play_rows, {}, {}
        for r in view.rows:
            now[r.key] = r
            if before.get(r.key) is not r:
                for e in r.episodes:
                    asks[e.id] = e.ask
        self._play_rows = now
        gone = {e.id for k, r in before.items() if k not in now for e in r.episodes}
        if gone:
            gone -= {e.id for r in view.rows for e in r.episodes}
        if gone:
            self.play.forget(gone)
        if asks:
            self.play.want(asks)

    def _seed_play(self, view):
        """The first screen's cache: last session's answers seed the looker's, until the looks answer — never for an
        episode still being looked for when it was written (R55-A: it says *Looking…* until it is looked at)."""
        self.play.seed({e.id: e.can_play for r in view.rows for e in r.episodes if not e.looking})
        self._playable = self.play.answers()
    # --- end row 55

    # --- LM11b G5
    def expect(self, tiers):
        """{item_id: tier} a command of the window's will write (*Move {show} to Finished*), from any thread: every
        build reads those items in that tier until the feed holds them — together at its top in the order given, a
        Finished one finished now — their rows by the view's own rule (`_row`), a busy store's wait included. None or
        {}: forgotten (the window let go of its order). Looked at now."""
        with self._lock:
            self._expected_new = dict(tiers or {})
        self._wake.set()

    def _take_expected(self):
        """The window's newest `expect`, taken in: its items and those it replaces built again -> whether it moved."""
        with self._lock:
            new, self._expected_new = self._expected_new, None
        if new is None or new == self._expected:
            return False
        if self._build_changed is not None:
            self._build_changed.update(set(new) | set(self._expected))
        self._expected = new
        return True
    # --- end LM11b G5

    def urgent(self):
        """(a4) The window hands its writer a learner's command (`drag.DragController._give`: a drop, a menu's move, a
        key's, a Done): for `URGENT_S` the views it makes build at once — never held back behind an import's burst —
        its numbers still waiting `NUMBERS_GRACE_S` for its write, so the move is one view. Any thread."""
        self._urgent_until = time.monotonic() + URGENT_S
        self._wake.set()

    def hold(self):
        """A drag starts (E6): the feed is still read, but nothing is built or published until `release()`."""
        self._hold.set()

    def release(self):
        """The drop (or a cancel): what came in meanwhile is built and published at the next look, now."""
        self._hold.clear()
        self._wake.set()

    def options(self):
        """The store's options as the last feed read gave them ({soon_line, mine_line, arrivals_on}; empty until the
        first read): Settings' store lines show them (W3.3 P6). A copy; any thread."""
        return dict(self._options)

    def view(self):
        with self._lock:
            return self._view

    def cards_rose(self):
        """How many times an item whose cards were asked before came back with more (Current, Soon, Finished): cards
        that landed while this reader looked. Never an item's first count — cards there at the open, or a show with old
        cards coming back into Current, start from theirs (Surasura's star ask, `app/qt/star_ask.py`). Any thread."""
        return self._cards_rose

    def store_id(self):
        """The library's own id (its meta's `store_id`) once a read found it, else None (W-1: a hint shown once per
        library). Any thread."""
        return self._store_id

    def emptied(self):
        """A5K-2: the store's note that its library folder held none of its files ({"at", "files"}), else None. Any
        thread."""
        return self._emptied

    def republish(self):
        """The window let go of its own order once every write landed: the next look builds and publishes the store's
        view, changed or not (where the store placed a row otherwise than the window drew it, round 2 AD2-4): the last
        one built, the same object, when nothing changed since (M4.1 B1: no build)."""
        self._republish = True
        self._wake.set()

    def start(self):
        """The thread started — never once `stop()` was asked (W3.2 P0: a reader a second language switch let go)."""
        with self._lock:
            if self._thread is None and not self._stop.is_set():
                self._thread = threading.Thread(target=self._run, name="library-reader", daemon=True)
                self._thread.start()
        return self

    def stopped(self):
        return self._stop.is_set()

    def refresh(self):
        """Look now, rather than at the next poll (the window's own change, a test)."""
        self._wake.set()

    def stop(self, timeout=2.0):
        with self._lock:
            self._stop.set()
            thread = self._thread
        self._wake.set()
        if thread is not None:
            thread.join(timeout)

    # --- the thread ------------------------------------------------------------------------------------------------- #
    def _run(self):
        try:
            if not self._stop.is_set():
                self._first_screen()
        except Exception:
            pass                                    # a cache that can't be read is no cache
        while not self._stop.is_set():
            paused = self._pause_gc()               # A4 P-gil
            try:
                self._look()
            except Exception as e:                  # never dies of a read: the last view, marked busy
                self._busy(e)
            finally:
                if paused:
                    gc.enable()
            self._wait()                            # W3.2 B: the bell, the watch or a retry (no watch: `poll`)
        self._unwatch()                             # W3.2 B
        if self.freeze_gc:                          # A4 P-gil: what it froze back in the collector's sight (a library
            gc.unfreeze()                           # a switch lets go is freed, its cycles too)
            _THAWED[0] = True
        if self.play is not None:
            self.play.close()                       # row 55: its worker ends (a look running finishes first)
        try:
            self._owed_cache()                          # LM11b H-T2: a command still waiting: the store's own view
            self._flush_cache()                         # the last view's cache, as the window closes
        except Exception:
            pass                                        # never in the way of closing (the store's handle below)
        try:
            close = getattr(self.opener, "close", None)
            if close is not None:
                close()                                 # this thread's handle, as the store closes it (`StoreOpener.close`,
            else:                                       # §6.12: never the collector's; a language switch drops a reader)
                h = self.opener.handle()
                if h is not None and hasattr(h, "close") and getattr(self.opener, "closes_handles", False):
                    h.close()
        except Exception:
            pass
        # W3.2 P0 (AD0-2): the library copy and the row cache let go — hundreds of thousands of objects at 20,000
        # files — so a reader a language switch dropped holds none of them, whoever still holds the reader. The last
        # view stays (`view()`: the window shows it until the next language's first view comes)
        self._items, self._works, self._cards, self._options = {}, {}, {}, {}
        self._cards_asked = {}
        self._pieces = {}
        self._folders, self._folders_ask = {}, None     # A4B-8
        self._tiers, self._pos, self._dirty, self._moved_in = None, {}, set(), {}
        self._overlaid, self._overlay_tiers = {}, {}
        self.row_cache = view_rows.RowCache()
        self._cache_due = None

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
        self.looks += 1                                 # W3.2 B
        if self._folders_owed:                          # A4B-8: the looks handed: the last view's arrivals asked
            self._folders_owed = False
            if self._view is not None:
                self._ask_folders(self._view)
        mode, reason, h = self._handle()
        changed_mode = (mode, reason) != self._mode
        self._mode = (mode, reason)
        if mode == "store" and h is not None and self.watch is not None:
            self._watching(h)                           # W3.2 B: the watch made once, what it reports synced
        version, numbers = self.numbers()
        held = self._hold.is_set()
        released = self._held_dirty and not held        # the drop: what came in during the drag, built once now
        again = self._republish and not held            # M4.1 B1: the settle's ask, taken before the store is read
        if again:
            self._republish = False
        if h is None:                                   # nothing to read: the last rows stay, under the mode's bar
            owed, self._view_owed = self._view_owed, False  # fix round (A4A-2): a view owed is this build (or the drop's)
            if changed_mode or self._view is None or version != self._numbers_version or released or again or owed:
                self._numbers_version = version         # the numbers' own version: a new one empties the row cache
                if held:
                    self._held_dirty = True
                    return
                self._held_dirty = False
                self._publish(self._build(numbers, mode, reason, rows_known=self._seen is not None))   # (review B-12)
            return
        with self._lock:                                # W3.2 Q1: new estimates from the window
            estimates_new, self._estimates_new = self._estimates_new, False
            estimates_new, self._folders_new = estimates_new or self._folders_new, False    # A4B-8: their folders
            numbers_new = estimates_new                 # fix round (IK-2): the arrivals' own numbers
            estimates_new, self._playable_new = estimates_new or self._playable_new, False     # row 55: ▶'s answers
        estimates_new = estimates_new or self._connect_moved()      # P4.1 L2: a new Connect feed rebuilds the same way
        expected_moved = self._take_expected()                      # LM11b G5: and the window's expectation
        estimates_new = expected_moved or estimates_new
        dv = h.data_version()
        now = time.monotonic()
        cards_due = self._cards_stale and not held and now - self._cards_all_at >= CARDS_ALL_S
        owed = self._view_owed                          # a4: a build held back (what comes meanwhile is still read)
        if not changed_mode and dv == self._data_version and version == self._numbers_version \
                and self._view is not None and not self._view.busy and not cards_due and not released \
                and not estimates_new and not owed:     # W3.2 Q1
            if again:                                   # M4.1 B1: nothing changed since the last build
                self._publish(self._view)
            self._flush_cache()
            return
        feed = h.read_feed(self._seen, self._epoch)
        self.reads += 1
        options_before = dict(self._options)
        before = set(self._items) if held and feed["full"] else None
        arrived = self._arrived(feed)                   # Hon a7: read against the copy before the merge
        self._merge(feed)
        self._audio_hovers(h, feed)                     # a5-2 (Hon): an audiobook's 🎧 hover, on its own row
        if arrived is None or arrived:
            self._tell("_arrived_subscribers", arrived)
        if held:                                        # E6: the dragged item gone meanwhile lets the drag go
            gone = [i for k, i in feed["gone"] if k == "item"] if before is None else sorted(before - set(self._items))
            if gone:
                self._tell_gone(gone)
        cards = self._card_counts(h)
        changed = (feed["full"] or feed["items"] or feed["works"] or feed["gone"] or changed_mode
                   or feed.get("pieces")                # LM11b G1: a group's kind or name
                   or self._options != options_before or version != self._numbers_version
                   or cards != self._cards or self._view is None or self._view.busy or self._view.cached or released
                   or estimates_new or owed)            # W3.2 Q1; a4: the build held back
        urgent = (changed_mode or released or again or expected_moved or feed["full"] or self._view is None
                  or self._view.busy or self._view.cached)
        numbers_only = dv == self._data_version and version != self._numbers_version
        estimates_only = numbers_new and dv == self._data_version and version == self._numbers_version    # IK-2
        self._cards = cards
        self._data_version = dv
        self._numbers_version = version
        self._moved(h)
        if (self._store_id is None or feed["full"]) and hasattr(h, "meta"):
            self._store_id = h.meta().get("store_id")      # W-1 (W-5): a fresh library has an id of its own
        if hasattr(h, "emptied"):
            self._emptied = h.emptied()                     # A5K-2 (one row read): *Needs you* asks once it is there
        if held:                                        # E6: merged, never built or shown under the hand; a quiet
            if changed:                                 # look later in the drag never forgets what came in (AD-1)
                self._held_dirty = True
            self._view_owed = False                     # fix round (A4A-2): a view owed is the drop's build now — owed
            return                                      # under the hand it fell due and the reader looked back to back
        self._held_dirty = False
        if not changed:                                 # data_version moved with nothing for the window (a checkpoint)
            self.skipped += 1
            if again:                                   # M4.1 B1
                self._publish(self._view)
            self._flush_cache()                         # a look with nothing new: as quiet as one that read nothing
            return
        if self.coalesce and not urgent and self._hold_back(now, numbers_only, dv, estimates_only):
            return                                      # a4: built once it falls due (`_timeout` wakes the reader)
        view = self._build(numbers, mode, reason, rows_known=True)
        self._publish(view)
        self._view_owed, self._numbers_at = False, None     # a4
        if not estimates_only:                          # fix round (IK-2): a burst is the store's commits — a view of
            self._built_at = time.monotonic()           # the arrivals' numbers alone never holds the next commit back
        if self.freeze_gc:
            self._freeze()                              # A4 P-gil
        if mode == "store" and self.cache_file:
            # written at the next look that finds nothing new, not now: the window is taking this view in at this
            # very moment, and the cache's JSON would hold Python's lock against it (speed round 5)
            key = [self._store_id, feed["epoch"], feed["version"], version]
            if self._expected:                          # LM11b G5: a view of what isn't written yet is never cached —
                self._cache_owed = key                  # owed (H-T2): written once it settles, or at the stop
                return
            self._cache_owed = None
            if self._cache_due is None:
                self._cache_due_at = time.monotonic()
            self._cache_due = (view, key)
            if time.monotonic() - self._cache_due_at >= CACHE_LATEST_S:
                self._flush_cache()                     # a store that never rests: written anyway, now and then

    # --- a4 (A2, C2): one view for a burst, one for a move ------------------------------------------------------ #
    def _hold_back(self, now, numbers_only, dv, estimates_only=False):
        """Whether this look's build waits -> True (owed: `_timeout` wakes the reader when it falls due). A change
        within `COALESCE_S` of the last view built waits for that much to pass (a burst of commits: a few views a
        second, the last change in the last one); the numbers' new version with the store unchanged waits
        `NUMBERS_GRACE_S` for the write it comes before (the bell wakes the reader at the write: one build). New
        arrivals' numbers alone (`estimates_only`, handed on at most four a second) wait only while a burst is under
        way — a view owed, or a build held back within `COALESCE_S` — else a lone arrival's *N new* came a burst's wait
        after its own view (fix round, IK-2)."""
        if estimates_only and not self._view_owed and (self._held_at is None or now - self._held_at >= COALESCE_S):
            return False
        due = self._built_at + COALESCE_S if self._built_at is not None and now >= self._urgent_until else now
        if numbers_only and self._numbers_at is None:
            self._numbers_at, self._numbers_dv = now, dv
        if self._numbers_at is not None and dv == self._numbers_dv:     # the write it comes before: not yet
            due = max(due, self._numbers_at + NUMBERS_GRACE_S)
        if due <= now:
            return False
        self._view_owed, self._owed_at, self._held_at = True, due, now
        self.held_back += 1
        return True
    # --- end a4

    # --- W3.2 B: the window wakes on the bell (IK0-5, L3.1-4, W2.2's *How the window wakes*) -------------------- #
    def _wait(self):
        """Until the next look. No watch, or a deaf one (no bell to hear other programs by): every `poll`, as before.
        Else until the bell or the tree watch wakes it (`wake` is the Lookout's), a Lookout timer falls due (the slow
        look without a watch, the watch's retry, its settle), or one of the reader's own retries does."""
        self._wake.wait(self._timeout())
        self._wake.clear()

    def _timeout(self):
        """The wait's seconds. While the store can't be used `_watching` (which takes what the watch says is due) isn't
        reached, so a timer already due would wake the reader at once, every time: floored at `poll` then (L1 B1)."""
        lookout = self._lookout
        view = self._view
        # fix round (A4A-2): a view owed wakes the reader when it falls due — never while a drag holds the view (the
        # drop builds it) or the store is busy (tried again at `poll`): either looked back to back once it fell due
        owed_due = self._view_owed and not self._hold.is_set() and not (view is not None and view.busy)
        if lookout is None or lookout.deaf:
            timeout = self.poll
            if owed_due:                                # a4: the view held back, built when it falls due
                timeout = min(timeout, max(0.0, self._owed_at - time.monotonic()))
        else:
            timeout = lookout.timeout()
            with self._lock:
                owed = any(self._owed) and not self._syncing
            if owed or self._cache_due is not None or self._recheck or self._held_dirty or \
                    (view is not None and view.busy):
                timeout = min(timeout, self.poll)       # a sync, a read or the cache's quiet look to try again
            if self._cards_stale and not self._hold.is_set():   # a card made elsewhere moves no row: asked again when
                #                                                 due (M4.1 B2: after a drag, which `release` wakes)
                timeout = min(timeout, max(0.0, self._cards_all_at + CARDS_ALL_S - time.monotonic()))
            if self._mode is not None and self._mode[0] != "store":
                timeout = max(self.poll, min(timeout, MODE_RECHECK_S))
            elif owed_due:                              # a4: the view held back, built when it falls due
                timeout = min(timeout, max(0.0, self._owed_at - time.monotonic()))
        return timeout

    def _watching(self, h):
        """(The reader's thread.) The watch made once the store can be used — the open's full sync owed first (the
        watch before the walk: a change while it runs is reported, never lost) — then what it says is due, handed to
        the sync worker (one sync at a time; what comes in meanwhile waits for the next)."""
        if self._lookout is None:
            try:
                self._lookout = self.watch(h, self._wake)
            except Exception as e:                      # no watch: every `poll`, as without one
                print(f"Library reader: the library's watch couldn't start: {e!r}")
                self.watch = None
                return
            from app.services.automation import Worker
            self._syncer = Worker(f"library-sync-{self.language}")
            jobs_full, folders, slow = True, (), False
        else:
            jobs = self._lookout.jobs()
            jobs_full, folders, slow = jobs.full, jobs.folders, jobs.slow
            # the hourly full look (no `make_round` here): owed and `looked()`, else the Lookout's round stays due and
            # the reader would wake at once, for good, an hour after the open (L1 B1)
            from app.library_watch import ROUND_S
            jobs_full = jobs_full or self._lookout.clock() - self._lookout._last_full >= ROUND_S
        if jobs_full:
            self._lookout.looked()
        with self._lock:
            owed = self._owed
            self._owed = (owed[0] | set(folders), owed[1] or jobs_full, owed[2] or slow)
            if self._syncing or not any(self._owed):
                return
            self._syncing = True
        if not self._syncer.put(self._sync):
            with self._lock:
                self._syncing = False

    def _sync(self):
        """(The sync worker.) What the watch reported, synced through this thread's own handle; the commit rings the
        bell. A busy store keeps it owed (the reader's next look hands it back); any other failure lets it go — the
        next report or slow look syncs again (the disk is the truth)."""
        from app import library_store
        while True:
            with self._lock:
                folders, full, slow = self._owed
                self._owed = (set(), False, False)
                if not (folders or full or slow):
                    self._syncing = False
                    return
            store = None
            try:
                store = self.opener.handle()
                if store is None:
                    raise library_store.StoreBusy("the library can't be read now")
                if slow and not full:                   # no watch: the folders that hold items, stat'ed
                    if self._disk_poll is None:
                        self._disk_poll = library_store.DiskPoll(store)
                    if self._disk_poll.check():
                        folders = folders | set(self._disk_poll.changed)
                if full:
                    library_store.sync_for_window(store)
                elif folders:
                    library_store.sync_for_window(store, folders=sorted(folders))
                self.syncs += 1
                if self.play is not None and (full or folders):     # row 55: what a video beside them may change
                    self.play.again(None if full else folders)
            except library_store.StoreBusy:
                with self._lock:
                    owed = self._owed
                    self._owed = (owed[0] | folders, owed[1] or full, owed[2] or slow)
                    self._syncing = False
                if store is not None:                   # (it waited the store's lock first): the reader, asleep
                    self._wake.set()                    # since this began, hands it back at its next look
                return
            except Exception as e:                      # never dies of a sync
                print(f"Library reader: the library's folders couldn't be synced: {e!r}")

    def _unwatch(self):
        """(The reader's thread, at its stop.) The watch and the bell closed; the sync worker closes its handle and
        ends (a sync running finishes first: its transaction is whole or not at all)."""
        lookout, self._lookout = self._lookout, None
        if lookout is not None:
            try:
                lookout.close()
            except Exception:
                pass
        syncer, self._syncer = self._syncer, None
        if syncer is not None:
            close = getattr(self.opener, "close", None)
            if close is not None:
                syncer.put(close)                       # the sync worker's own handle (`StoreOpener.close`)
            syncer.close()

    # --- end W3.2 B

    def _moved(self, h):
        """The order or the pins moved since the last read: told once (`subscribe_moves`); any version moved (a re-order
        recorded too): told once (`subscribe_versions`). Read only after `data_version` moved; a version read that fails
        tells nothing (the next change is told)."""
        with self._lock:
            subscribers = list(self._move_subscribers)
            watchers = list(self._version_subscribers)
        if not (subscribers or watchers) or not hasattr(h, "versions"):
            return
        try:
            versions = h.versions()
        except Exception:
            return
        seen = tuple(sorted(versions.items()))
        if watchers and seen != self._versions_seen:
            for cb in watchers:
                try:
                    cb(versions)
                except Exception:
                    pass                            # a listener's fault never stops the reader
        self._versions_seen = seen
        key = (versions.get("epoch"), versions.get("order_version"), versions.get("pins_version"))
        before, self._order_key = self._order_key, key
        if before is None or key == before:
            return
        for cb in subscribers:
            try:
                cb(self.language, versions)
            except Exception:
                pass                                # a listener's fault never stops the reader

    def _tell_gone(self, ids):
        self._tell("_gone_subscribers", ids)

    def _tell(self, which, ids):
        with self._lock:
            subscribers = list(getattr(self, which))
        for cb in subscribers:
            try:
                cb(ids)
            except Exception:
                pass                                # a listener's fault never stops the reader

    def _arrived(self, feed):
        """Hon a7: the works (sorted ids) whose files arrived or changed in this read — an item new to the reader's
        copy, or its file or its work moved — read before the merge; none for a move, a mark or a cover written: only
        what changed is looked at again (S19). None at the first read: the whole library, the open's scan's (scanned
        by the look only when the open found no store to read)."""
        with self._lock:
            if not self._arrived_subscribers:
                return []
        if self._seen is None:
            return None
        out = set()
        for r in feed["items"]:
            work, old = r.get("work_id"), self._items.get(r["id"])
            if work is not None and (old is None or old.get("work_id") != work or old.get("rel_path") != r.get("rel_path")):
                out.add(work)
        return sorted(out)

    def _card_counts(self, h):
        """{item_id: cards} for the items whose rows show cards (Current, Finished). A card made for an item doesn't
        move its row in the feed (`record_made`), so every item is asked again at most every CARDS_ALL_S; between, only
        the items the feed changed — and not while a drag holds the view (nothing is built then; asked at the next look
        after it). The same dict object comes back when nothing changed (the row cache reads that)."""
        if not hasattr(h, "cards_of"):
            return {}
        now = time.monotonic()
        if self._changed_ids is None or (now - self._cards_all_at >= CARDS_ALL_S and not self._hold.is_set()):
            tiers = self._sorted_tiers()                # M4.1 B2: the three tiers' ids, not a scan of every item
            ids = [r["id"] for t in ("now", "soon", "graduated") for r in tiers.get(t, ())]
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
        asked = self._cards_asked
        for i in ids:
            n = new.get(i, 0)
            if n > asked.get(i, n):
                self._cards_rose += 1
            asked[i] = n
        return self._cards if new == self._cards else new

    def _merge(self, feed):
        if feed["full"]:
            self._items = {r["id"]: r for r in feed["items"]}
            self._works = {w["id"]: w for w in feed["works"]}
            self._pieces = {p["id"]: p for p in feed.get("pieces") or ()}       # LM11b G1
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
                        self._moved_in.setdefault(old.get("tier"), set()).add(r["id"])     # M4.1 B3: left it
                else:                                   # the same place: swapped in, no sort
                    at = self._pos.get(r["id"])
                    if at is not None:
                        self._tiers[at[0]][at[1]] = r
                    else:
                        self._dirty.add(r.get("tier"))
                        self._moved_in.setdefault(r.get("tier"), set()).add(r["id"])
            for w in feed["works"]:
                self._works[w["id"]] = w
            for p in feed.get("pieces") or ():          # LM11b G1: an equal piece keeps its object (its row cached)
                if self._pieces.get(p["id"]) != p:
                    self._pieces[p["id"]] = p
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
                        self._moved_in.setdefault(old.get("tier"), set()).add(ident)       # M4.1 B3
                else:
                    self._works.pop(ident, None)
            self._changed_ids = changed
        self._options = dict(feed.get("options") or {})
        self._seen, self._epoch = feed["version"], feed["epoch"]

    def _audio_hovers(self, h, feed):
        """a5-2 (Hon): each audiobook item's summary for its row's 🎧 hover (`Store.audiobook_hovers`: its files, the
        first and last, its length), put on its own feed row as `audio` — read only when the feed brought an audiobook's
        item (its record's change feeds it, `pair_audiobook`), so a row's cache keeps every other row (S19)."""
        if feed["full"]:
            ids = [i for i, r in self._items.items() if r.get("source_type") == "audio"]
        else:
            ids = [r["id"] for r in feed["items"] if r.get("source_type") == "audio"]
        if not ids or not hasattr(h, "audiobook_hovers"):
            return
        try:
            hovers = h.audiobook_hovers()
        except Exception:
            return
        for i in ids:
            r = self._items.get(i)
            if r is not None and i in hovers:
                r["audio"] = hovers[i]                  # the feed's new row (never one a built view holds)

    def _sorted_tiers(self):
        """Each tier's items in `(ord, id)` order: in full after a full read, else only the tiers something moved in."""
        if self._tiers is None:
            self._tiers = view_rows._by_tier(self._items)
            self._dirty, self._moved_in = set(), {}
            self._pos = {r["id"]: (t, i) for t, rows in self._tiers.items() for i, r in enumerate(rows)}
        elif self._dirty:
            items = self._items
            for t in self._dirty:
                if t is None:
                    continue
                touched, old = self._moved_in.pop(t, set()), self._tiers.get(t)
                if old is not None and len(touched) <= FEW_SORTED:
                    # M4.1 B3: a few ids (a menu's move into Goal's ~16,000): taken out, those still in the tier put
                    # back in place; the rest keep their order (a full sort was up to 28 ms at 20,000 files)
                    lo = next((k for k, r in enumerate(old) if r["id"] in touched), len(old))
                    rows = old[:lo] + [r for r in old[lo:] if r["id"] not in touched]
                    for i in touched:
                        r = items.get(i)
                        if r is not None and r.get("tier") == t:
                            k = bisect.bisect_right(rows, _sort_key(r), key=_sort_key)
                            rows.insert(k, r)
                            lo = min(lo, k)
                else:
                    # the tier's own items and those that came into it, not all 20,000 (speed round 5: an arrival's
                    # sort walked every item on the reader's thread); one gone or moved out drops out here
                    ids = {r["id"] for r in old or ()} | touched
                    rows = [items[i] for i in ids if i in items and items[i].get("tier") == t]
                    rows.sort(key=_sort_key)
                    lo = 0
                self._tiers[t] = rows
                for i in range(lo, len(rows)):
                    self._pos[rows[i]["id"]] = (t, i)
            self._dirty, self._moved_in = set(), {}
        return self._tiers

    # --- P4.1 L2: Connect's feed (row 4.1.10)
    def _connect_moved(self):
        """Another Connect Feed than the last view was built with (an object compare: the Provider hands back the
        same object while nothing changed)."""
        try:
            return self.connect() is not self._connect_built
        except Exception:
            return False
    # --- end P4.1 L2

    def _build(self, numbers, mode, reason, rows_known):
        self.builds += 1
        try:                                            # --- P4.1 L2: Connect's feed, read once a build
            connect = self.connect()
        except Exception:
            connect = None
        if self.play is not None and connect is not self._connect_built:
            self.play.index_moved()                     # row 55: its video index may have been saved anew
        self._connect_built = connect
        # a new numbers version rebuilds only the rows holding an item it changed, when the provider says which (a
        # drop moves *N new* on a few rows); the seed's provider can't say: every row, as before
        numbers_changed = None
        changed_since = getattr(self.numbers, "changed", None)
        if changed_since is not None and self._built_numbers is not None:
            try:
                numbers_changed = changed_since(self._built_numbers)
            except Exception:
                numbers_changed = None
        items, tiers = self._items, (self._sorted_tiers() if self._items else None)
        if self._expected:                              # LM11b G5: what the feed holds already is the feed's own
            self._expected = {i: t for i, t in self._expected.items() if i in items and items[i].get("tier") != t}
            if self._expected:                          # the rest read in their new tier, while it lasts
                items, tiers = self._overlay(items, tiers)
        if not self._expected:
            self._overlaid, self._overlay_tiers = {}, {}
        with self._lock:
            folders = (self._folders_version, self._folders) if self._folders else None     # A4B-8
        view = view_rows.build(items, self._works, self._options, numbers=(self._numbers_version, numbers),
                               cards=self._cards, mining=set(self.mining()), language=self.language, mode=mode,
                               reason=reason, loading=not rows_known, cache=self.row_cache,
                               tiers=tiers, changed=self._build_changed,
                               changed_works=self._build_works, numbers_changed=numbers_changed,
                               estimates=self._estimates,     # W3.2 Q1
                               connect=connect,               # P4.1 L2
                               pieces=self._pieces,           # LM11b G1
                               playable=self._playable,       # row 55
                               folders=folders)               # A4B-8
        view = view._replace(epoch=self._epoch)         # LM11b: a library rebuilt or reset lets the window's picks go
        if self.play is not None:
            self._ask_play(view)                        # row 55
        self._ask_folders(view)                         # A4B-8
        self._built_numbers = self._numbers_version
        self._build_changed = set()                     # built: from here on, only what the feed changes
        self._build_works = set()
        return view

    def _overlay(self, items, tiers):
        """(LM11b G5) The expectation built in -> (items, tiers): each expected item in its new tier, together at that
        tier's top in the order given (a Finished one finished now). H-W1 (S19): an overlaid row is the same dict while
        its feed row is the same object at the same place (its row stays cached), and only the tiers it moves between
        are made again — each the same list while the reader's and the rows built into it are (Goal's and Finished's
        sections kept); the other tiers are the reader's own, never sorted again."""
        expected = self._expected
        top = {t: min(0.0, (tiers[t][0].get("ord") or 0.0) if tiers.get(t) else 0.0) for t in set(expected.values())}
        now = None
        built, made = {}, {}
        for k, (i, t) in enumerate(expected.items()):
            src = items[i]
            at = top[t] - 1024.0 + k / (len(expected) + 1)
            old = self._overlaid.get(i)
            if old is not None and old[0] is src and old[1] == t and old[2] == at:
                row = old[3]
            else:
                if now is None:
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                row = dict(src, tier=t, ord=at, **({"graduated_at": now} if t == "graduated" else {}))
            built[i] = (src, t, at, row)
            made.setdefault(t, []).append(row)
        self._overlaid = built
        items = dict(items)
        items.update((i, b[3]) for i, b in built.items())
        out, lists, gone = dict(tiers), {}, frozenset(expected)
        for t in set(made) | {b[0].get("tier") for b in built.values()}:
            mine, src_list = made.get(t, []), tiers.get(t) or []
            old = self._overlay_tiers.get(t)
            # the ids taken out are part of the key — a second show expected out of the same tier list (two
            # finishes in a row) has no row of its own there, and the first's filtered list kept it in
            if old is not None and old[0] is src_list and old[3] == gone and len(old[1]) == len(mine) and \
                    all(a is b for a, b in zip(old[1], mine)):
                rows = old[2]
            else:
                rows = mine + [r for r in src_list if r["id"] not in expected]
            lists[t] = (src_list, mine, rows, gone)
            out[t] = rows
        self._overlay_tiers = lists
        return items, out

    def _pause_gc(self):
        """(A4 P-gil) A look whose build will be frozen pauses the collector until it is: the read and the build make
        the library's objects anew (a full read: hundreds of thousands), and each full collection they set off walked
        them all under Python's lock (34-43 ms at 20,000 files, up to 110 ms at 60,000, two to seven in a first view).
        The freeze then takes them out of the collector's sight uncounted. -> whether it paused it."""
        if not self.freeze_gc or not gc.isenabled() or (_THAWED[0] and self.builds < 1):
            return False                            # (after a switch the first view isn't frozen: never paused)
        gc.disable()
        return True

    def _freeze(self):
        """(A4 P-gil) Everything alive moved out of the collector's sight after a build — but after another reader's stop
        (a language switch), never at this reader's first view (the switch still holds the library it left), and the
        first freeze after it collects first, so that library, let go by then, is freed rather than frozen."""
        if _THAWED[0]:
            if self.builds < 2:
                return
            gc.collect()
            _THAWED[0] = False
        gc.freeze()

    def _owed_cache(self):
        """(H-T2) At the stop, a cache owed while the window's command still waits: the store's own view (built without
        that command's rows) under the key the store held. A busy store's wait is unbounded (the window's moves are
        queued, never dropped), so the cache is written here rather than skipped for good."""
        if self._cache_owed is None or not self._expected or not self.cache_file or not self._items:
            return
        key, self._cache_owed = self._cache_owed, None
        expected, self._expected = self._expected, {}
        try:
            view = self._build(self.numbers()[1], "store", None, rows_known=True)
        finally:
            self._expected = expected
        self._cache_due = (view, key)

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
        if view is not None:
            view = view._replace(epoch=data["key"][1])  # the key matched: the store's epoch now
        if view is not None and self.play is not None:  # row 55: last session's answers, until the looks answer
            self._seed_play(view)
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
