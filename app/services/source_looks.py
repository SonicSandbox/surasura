"""The window's looks at its source folders (SRC W1b; the RUNBOOK §1b S4, S10 / D5, S14 / D6): when `sources.scan` runs,
on which thread, and what the window is told. Qt-free; the shell (`app/qt/shell.py`) calls it and paints the answers.

- **When** (SRC-9, `sources.due`): on the window's focus (at most once per `FOCUS_S`), on Refresh (always, a full
  look), on the window's tick (hourly) — never while the window is behind or minimized. The first look after start and
  every Refresh list everything (`full`, S4); the others list only the folders whose time moved.
- **A local folder is watched** (S10 / D5, `sources.local_or_network`): a `library_watch.TreeWatch` on it, whose
  reports ask for a look of that folder alone once it has been quiet past the scan's half-written wait
  (`sources.SETTLE_S` + `AGAIN_S`: a file younger than SETTLE_S is never taken; every later report pushes the look back,
  so a long download is one look at its end, never one per burst) — held while the window is behind, looked at when it
  comes back. A watch that ends (the drive went) asks for a look at once (the offline line).
  A network folder, or one whose watch can't start or ended, gets the cadence only (the watch is tried again at the
  next look that reaches it). One thread waits on every watch (blocked inside Windows: nothing while nothing happens).
- **One look at a time** (`sources.scan` never two at once): every look, add and stop runs on one worker thread of its
  own (`automation.Worker`) with its own store handle (the window's opener, `StoreOpener.handle`: one per thread);
  a look asked while one runs is folded into one more after it (a Refresh's full look kept), the rest dropped.
- **What the window is told** (`on_result(summary)`, on the worker): `{"sources": [{id, path, on, items, reachable}],
  "added", "waiting", "full"}` after each look, add and stop — `reachable` None until a look reached it this run.
  `offline(sources)` is the offline line's list (SRC-3: nothing moved or marked, one quiet line).
- **+ Add → A folder…** (`add`): `Store.add_source` then its first look — a later look's landing (D6: a show never
  shown waits in New arrivals; `first=True` is setup's own first scan only). A refused folder answers its reason
  (`NotASource.reason`). **Stop reading** (`stop`): `Store.stop_source` (its items stay), its watch closed.
- **Arrival rows name their folder** (`folders(item_ids)`): each item's origin record (`connect.library.pairing_of`)
  read back to its source folder's path.
"""
import threading
import time

from app import settings_manager, sources
from app.services.automation import Worker


AGAIN_S = 1.0                   # a watch report's look: this long after the scan's half-written wait (SETTLE_S)


def _nothing(*_args):
    pass


def offline(rows):
    """[(path, items)] of the sources being read that the last look couldn't reach (the offline line), in order."""
    return [(r["path"], r.get("items") or 0) for r in rows or () if r.get("on", True) and r.get("reachable") is False]


def _make_watch(path, wake):
    from app import library_watch
    return library_watch.TreeWatch(path, wake=wake)


class SourceLooks:
    """`opener`: the window's store opener (its writer's); `rules()`: the placing rules a later look's arrivals obey
    (settings.json's `placing_rules`, read at each look); `on_result(summary)` / `on_progress(path, found, shows)`:
    the window's (any thread). `clock`, `watch(path, wake)`, `kind(path)`, `quiet` (seconds a watched folder stays quiet
    before its look): a test's."""

    def __init__(self, opener, language="ja", rules=None, on_result=None, on_progress=None, clock=time.monotonic,
                 watch=_make_watch, kind=sources.local_or_network, quiet=None):
        self.opener = opener
        self.language = language
        self._rules = rules
        self.on_result = on_result or _nothing
        self.on_progress = on_progress or _nothing
        self._clock = clock
        self._make_watch = watch
        self._kind = kind
        self._quiet = sources.SETTLE_S + AGAIN_S if quiet is None else quiet   # a watch's look, after its last report
        self._worker = Worker(f"window-sources-{language}")
        self._lock = threading.Lock()
        self._closing = threading.Event()             # the window closes: a look under way stops between files
        self._last = None                             # when the cadence's last look began (`sources.due`'s `last`)
        self._first = True                            # the first look after start lists everything (S4)
        self._running = False                         # a look queued or running (never two at once)
        self._again = None                            # asked meanwhile: (full, roots or None) — one more after it
        self._shown = True                            # the window in front (watch reports wait while it isn't)
        self._dirty = set()                           # roots a watch reported while the window was behind
        self._again_at = {}                           # root -> when its reports' look is due (B1 / S7: quiet, settled)
        self._stopping = set()                        # roots *Stop reading* was pressed on (a running look lets go: S6)
        self._watches = {}                            # root id -> TreeWatch (local folders being read)
        self._wake = threading.Event()                # every watch's reports wake the one watch thread
        self._watcher = None
        self._reachable = {}                          # root id -> the last look's answer (this run)
        self.looks = 0                                # looks run (tests)

    # --- the window's side (its thread; each returns at once) ---------------------------------------------------- #
    def asked(self, focused=False, refreshed=False, shown=True, now=None):
        """The window came to the front (`focused`), Refresh (`refreshed`) or its tick (neither): a look when
        `sources.due` says so; a look of the folders a watch reported while it was behind, on its focus. -> True when a
        look was queued."""
        now = self._clock() if now is None else now
        with self._lock:
            if self._closing.is_set():
                return False
            self._shown = bool(shown)
            if not sources.due(now, focused, refreshed, self._last, shown):
                if focused and shown and self._dirty:
                    roots, self._dirty = set(self._dirty), set()
                    return self._queue(False, roots)
                return False
            if self._running and not refreshed:
                return False                          # one at a time: the cadence's look is the one running
            self._last = now
            full = bool(refreshed) or self._first
            self._first = False
            self._dirty.clear()
            return self._queue(full, None)

    def set_shown(self, shown):
        """The window went behind / was minimized (False) or came back (True): watch reports wait while it is behind."""
        with self._lock:
            self._shown = bool(shown)

    def add(self, path, then=None, first=False):
        """*Read it where it is*: `then({"path", "root", "refused", "result"})` on the worker. -> False once closed."""
        return self._worker.put(self._add, path, then or _nothing, first) if not self._closing.is_set() else False

    def stop(self, root_id, then=None, language=None):
        """*Stop reading*: `then({"root", "stopped"})` on the worker. `language`: the language the root was listed in
        — another's (ids repeat across stores) is refused (B2)."""
        if self._closing.is_set() or (language is not None and language != self.language):
            return False
        with self._lock:
            self._stopping.add(root_id)               # a look reading it now stops between files (S6)
        return self._worker.put(self._stop, root_id, then or _nothing)

    def busy(self):
        """A look is queued or running (Settings says *Stop reading* waits for the file it is on)."""
        with self._lock:
            return self._running

    def listing(self):
        """The sources as they stand, to `on_result` (Settings' row as it opens): one read on the worker."""
        return self._worker.put(self._publish, None, {}) if not self._closing.is_set() else False

    def folders(self, item_ids, then):
        """`then({item_id: source folder path or None})` on the worker (the arrival rows' folder names)."""
        ids = list(item_ids)
        return self._worker.put(self._folders, ids, then) if ids and not self._closing.is_set() else False

    def close(self):
        """The window closes (or another language opens): the look under way stops between files, every watch closes,
        the worker's store handle closes after what was queued — and nothing it still finds is told (B2: a language
        left never paints over the one open)."""
        self._closing.set()
        self.on_result = self.on_progress = _nothing
        with self._lock:
            watches, self._watches = list(self._watches.values()), {}
        self._wake.set()
        self._worker.put(self._let_go, watches)
        self._worker.close()

    def idle(self, timeout=None):
        """(Tests.) Everything queued has run."""
        return self._worker.idle(timeout)

    # --- the worker -------------------------------------------------------------------------------------------- #
    def _queue(self, full, roots):
        """(Under the lock.) A look onto the worker, or folded into the one after the running one."""
        if self._running:
            held = self._again
            if held is None:
                self._again = (full, None if roots is None else set(roots))
            else:
                was_full, was = held
                self._again = (was_full or full, None if was is None or roots is None else was | set(roots))
            return False
        self._running = True
        if not self._worker.put(self._look, full, roots):
            self._running = False
            return False
        return True

    def _store(self):
        h = self.opener.handle()
        if h is None and getattr(self.opener, "mode", None) != "store":
            self.opener.check()
            h = self.opener.handle()
        return h

    def _look(self, full, roots):
        """(The worker.) Each source being read (`roots`: those alone) looked at once, then the window told."""
        try:
            store = self._store()
            if store is None:
                return
            self.looks += 1
            rows = store.sources()
            totals = {"added": 0, "waiting": 0, "full": full}
            for row in rows:
                if self._closing.is_set():
                    break
                if (roots is not None and row["id"] not in roots) or row["id"] in self._stopping:
                    continue
                result = self._scan(store, row, full=full)
                if result is not None:
                    totals["added"] += result.get("added", 0)
                    totals["waiting"] += result.get("waiting", 0)
            self._follow_watches(rows)
            self._publish(store, totals)
        except Exception as e:                        # a look that failed waits for the next: never the window's fault
            print(f"Sources: the look stopped: {e!r}")
        finally:
            with self._lock:
                self._running = False
                again, self._again = self._again, None
                if again is not None and not self._closing.is_set():
                    self._queue(*again)

    def _scan(self, store, row, full=False, first=False, progress=None):
        path = row["path"]
        try:
            result = sources.scan(store, self.language, row["id"], first=first, full=full, rules=self._rules_now(),
                                  progress=progress, stop=lambda: self._closing.is_set() or row["id"] in self._stopping)
        except Exception as e:                        # one folder's fault never stops the others
            print(f"Sources: {path} wasn't looked at: {e!r}")
            return None
        if not result.get("busy"):
            self._reachable[row["id"]] = bool(result.get("reachable"))
        return result

    def _rules_now(self):
        """The rules for this look, merged per key with their defaults (`settings_manager.placing_rules`) — the window's
        settings are frozen (a mapping, not a dict): a user's own rule, a folders' Wait too, reaches `take_in`."""
        if self._rules is None:
            return None
        try:
            rules = self._rules()
        except Exception:
            return None
        return settings_manager.placing_rules(rules)

    def _add(self, path, then, first):
        answer = {"path": path, "root": None, "refused": None, "result": None, "arrivals": 0,
                  "language": self.language}
        store = None
        try:
            store = self._store()
            if store is None:
                answer["refused"] = "no-library"
            else:
                from app import library_store as ls
                try:
                    root = store.add_source(path)
                except ls.NotASource as e:
                    answer["refused"] = e.reason
                else:
                    answer["root"] = root
                    row = next((r for r in store.sources() if r["id"] == root), {"id": root, "path": path})
                    answer["result"] = self._scan(store, row, full=True, first=first, progress=lambda found, shows:
                                                  self.on_progress(row["path"], found, shows))
                    if answer["result"] is None or answer["result"].get("busy"):
                        answer["later"] = True        # read from now on; its first look comes with the next one
                    for item_id in (answer["result"] or {}).get("ids") or ():
                        item = store.item(item_id)
                        if item is not None and item["tier"] == "arrivals":
                            answer["arrivals"] += 1      # D6: the shows never shown wait there
                    self._follow_watches(store.sources())
        except Exception as e:
            answer["refused"] = str(e) or repr(e)
        then(answer)
        if store is not None:
            self._publish(store, {})

    def _stop(self, root_id, then):
        answer = {"root": root_id, "stopped": False, "language": self.language}
        store = None
        try:
            store = self._store()
            if store is not None:
                answer["stopped"] = bool(store.stop_source(root_id))
                self._again_at.pop(root_id, None)
                with self._lock:
                    w = self._watches.pop(root_id, None)
                if w is not None:
                    _close(w)
                self._reachable.pop(root_id, None)
        except Exception as e:
            answer["refused"] = str(e) or repr(e)
        with self._lock:
            self._stopping.discard(root_id)
        then(answer)
        if store is not None:
            self._publish(store, {})

    def _publish(self, store, totals):
        if store is None:
            store = self._store()
            if store is None:
                return
        try:
            rows = store.sources()
        except Exception as e:
            print(f"Sources: the folders couldn't be read: {e!r}")
            return
        summary = dict(totals, language=self.language)
        summary["sources"] = [dict(r, reachable=self._reachable.get(r["id"])) for r in rows]
        self.on_result(summary)

    def _folders(self, ids, then):
        out = dict.fromkeys(ids)
        try:
            store = self._store()
            if store is not None:
                import json
                from app import library_store as ls
                paths = {r["id"]: r["path"] for r in store.sources(all=True)}
                for item_id in ids:                   # its origin row (B1's key), never hato's record before it
                    row = store.conn.execute(f"SELECT p.pairing FROM pairings p WHERE p.item_id = ? AND "
                                             f"{ls._ORIGIN_ROW} ORDER BY p.rowid LIMIT 1", (item_id,)).fetchone()
                    try:
                        record = json.loads(row[0]) if row else None
                    except ValueError:
                        record = None
                    if isinstance(record, dict):
                        out[item_id] = paths.get(record.get("root"))
        except Exception as e:
            print(f"Sources: the arrivals' folders couldn't be read: {e!r}")
        then(out)

    def _let_go(self, watches=()):
        for w in watches:
            _close(w)
        close = getattr(self.opener, "close", None)   # this thread's handle (a store handle belongs to its thread)
        if close is not None:
            close()

    # --- the watches (S10 / D5) -------------------------------------------------------------------------------- #
    def _follow_watches(self, rows):
        """(The worker.) A watch on every local source being read and reached; a stopped one's closed; one that ended
        (the drive went) let go — tried again at the next look that reaches it."""
        if self._closing.is_set():
            return
        on = {r["id"]: r["path"] for r in rows if r.get("on", True)}
        with self._lock:
            held = dict(self._watches)
        for root, w in held.items():
            if root not in on or getattr(w, "state", "watching") != "watching":
                with self._lock:
                    self._watches.pop(root, None)
                _close(w)
        for root, path in on.items():
            with self._lock:
                if root in self._watches:
                    continue
            if self._reachable.get(root) is not True or self._kind(path) != "local":
                continue                              # a network folder, or one not reached: the cadence alone
            w = self._make_watch(path, self._wake)
            try:
                started = w.start()
            except Exception:
                started = False
            if not started:
                _close(w)
                continue
            with self._lock:
                closing = self._closing.is_set()
                if not closing:
                    self._watches[root] = w
                if not closing and self._watcher is None:
                    self._watcher = threading.Thread(target=self._watch_loop, name=f"window-sources-watch-"
                                                     f"{self.language}", daemon=True)
                    self._watcher.start()
            if closing:                               # (closed outside the lock: a close may wait on its thread)
                _close(w)
                return

    def _watch_loop(self):
        """The watch thread: blocked until a watch reports (or a pending folder settles), then a look of the folders
        that changed — or, while the window is behind, kept for its focus."""
        while not self._closing.is_set():
            with self._lock:
                watches = list(self._watches.items())
            dues = [d for d in (w.due() for _r, w in watches) if d is not None]
            now = time.monotonic()                    # (the watches' own time: real, never the cadence's clock)
            dues += [max(0.0, at - now) for at in self._again_at.values()]
            self._wake.wait(min(dues) if dues else None)
            self._wake.clear()
            if self._closing.is_set():
                return
            now = time.monotonic()
            changed = set()
            for root, w in watches:
                if getattr(w, "state", "watching") != "watching":
                    with self._lock:                  # ended (the drive went): looked at now, the cadence after
                        if self._watches.get(root) is w:
                            del self._watches[root]
                    self._again_at.pop(root, None)
                    changed.add(root)
                    continue
                folders, whole = w.take()
                if folders or whole:
                    self._again_at[root] = now + self._quiet        # pushed back by every later report
            for root, at in list(self._again_at.items()):
                if at <= now:
                    del self._again_at[root]
                    changed.add(root)
            if not changed:
                continue
            with self._lock:
                if self._shown:
                    self._queue(False, changed)
                else:
                    self._dirty |= changed


def _close(watch):
    try:
        watch.close()
    except Exception:
        pass

