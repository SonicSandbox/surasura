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
  "added", "waiting", "full", "moved"}` after each look, add and stop — `reachable` None until a look reached it this
  run; `moved`: the known files whose video or original the looks since the last summary recorded (`paired`,
  `attached`) — ▶'s looks are asked again only then (row 55 IK-1).
  `offline(sources)` is the offline line's list (SRC-3: nothing moved or marked, one quiet line).
- **Gone or away** (T6, Sonic 2026-10-24): a row the last look couldn't reach says `gone` — True when the folder is
  GONE (moved or deleted while the folder above it reads, `sources.reach`), False when it is AWAY (an unplugged drive,
  a share down, a parent unreadable) — and a gone one carries its card's data (`Store.source_detail`): `shows` (the
  titles it holds), `finished` (every episode Finished: *Stop reading it* first) and `found_in` (the folders being read
  that hold its episodes now). `gone(sources)` lists the *Needs you* card's folders; `offline(sources, gone=False)` the
  offline line's once the card is drawn (today's line, `gone=True`, still names both). The card's answers: *Find its
  new folder...* (`find_new_folder`: `Store.add_source` and its look — MV-1 / MV-2's one rule — then `Store.join_moved`:
  the old folder's episodes joined to the new place, never a second copy, also when it was read already; the answer
  says `stop`: give the window's writer `stop_reading` for the old folder, the toast's Undo), *Stop reading it* (the
  writer's `stop_reading`: `Store.stop_source`, one Undo, nothing on disk moves) and *Keep waiting* (the offline
  line's own dismissal). Each answer is followed by `listing()` (the card goes, or comes back after an Undo).
- **+ Add → A folder…** (`add`): `Store.add_source` then its first look — a later look's landing (D6: a show never
  shown waits in New arrivals; `first=True` is setup's own first scan only). A refused folder answers its reason
  (`NotASource.reason`). **Stop reading** (`stop`): `Store.stop_source` (its items stay), its watch closed.
- **Start a fresh library** (`fresh`, K7): `library_store.start_fresh` on the worker (the store's own write lock and
  backup), then a first look of every folder being read (`first=True`, in full: setup's first scan, so they land in
  Current), the window told twice — once the library is fresh (`then`), and the looks' summary after.
- **Arrival rows name their folder** (`folders(item_ids)`): each item's origin record (`connect.library.pairing_of`)
  read back to its source folder's path.
- **Skipped folders** (K6): every summary carries `skipped` (`Store.skipped_folders`: Settings' list);
  `skippable(item_ids)` answers ⋯'s *Never read this folder* submenu (`Store.skip_choices`), `skip_refused(path)`
  Settings' *Skip a folder…* (`Store.skip_refused`, Q7); *Read again* (`read_again`) drops the skip
  (`Store.read_folder_again`) and looks at its source folder at once.
"""
import threading
import time

from app import settings_manager, sources
from app.services.automation import Worker


AGAIN_S = 1.0                   # a watch report's look: this long after the scan's half-written wait (SETTLE_S)


def _nothing(*_args):
    pass


def offline(rows, gone=True):
    """[(path, items)] of the sources being read that the last look couldn't reach (the offline line), in order.
    `gone=False` (T6): the AWAY ones only — a gone folder is *Needs you*'s card (`gone`)."""
    return [(r["path"], r.get("items") or 0) for r in rows or () if r.get("on", True) and r.get("reachable") is False
            and (gone or not r.get("gone"))]


def gone(rows):
    """T6: the summary's rows of the sources being read that are GONE (moved or deleted, `sources.reach`) — one
    *Needs you* card each: {id, path, items, shows, finished, found_in}."""
    return [r for r in rows or () if r.get("on", True) and r.get("reachable") is False and r.get("gone")]


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
        self.on_ended = _nothing                      # round 8 row 45: `on_ended(told, why)` after every look (any
        #                                               thread): `told` False — no summary came (no store, a failure)
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
        self._gone = {}                               # T6: root id -> the last look found it GONE (not away)
        self._moved = 0                               # row 55 IK-1: files a look moved, since the last summary
        self._reset_told = False                      # a fresh library a kill left unfinished: said once a run (LF-11)
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

    def find_new_folder(self, root_id, path, then=None, language=None):
        """T6, a gone folder's *Find its new folder...*: `then({"old", "path", "root", "refused", "result", "state",
        "joined", "stop", "language"})` on the worker — `path` read (`Store.add_source`, as + Add's *A folder...*; the
        same folder again is its row) and looked at in full, then, the old folder still GONE, its episodes found there
        joined (`Store.join_moved`: `joined` how many; never a second copy) and `stop` True: the window gives its
        writer `stop_reading(root_id)` (the toast's Undo). The old folder back, or only away (`state`), joins and stops
        nothing; so does a look that couldn't run now (`later`: the folder is read from now on, and the next look
        joins what it attaches — D5 — while the card stays). A refused folder answers its reason (`refused`), nothing
        written; a failure after the folder was added answers `failed` (the folder is read; nothing joined or
        stopped). `language`: as `stop`'s. -> False once closed."""
        if self._closing.is_set() or (language is not None and language != self.language):
            return False
        return self._worker.put(self._find, root_id, path, then or _nothing)

    def stop(self, root_id, then=None, language=None):
        """*Stop reading*: `then({"root", "stopped"})` on the worker. `language`: the language the root was listed in
        — another's (ids repeat across stores) is refused (B2)."""
        if self._closing.is_set() or (language is not None and language != self.language):
            return False
        with self._lock:
            self._stopping.add(root_id)               # a look reading it now stops between files (S6)
        return self._worker.put(self._stop, root_id, then or _nothing)

    def fresh(self, forget_known=False, then=None):
        """*Start a fresh library* (K7): `then({"done", "refused", "failed", "backup", "known", "language"})` on the
        worker once the reset answered; every folder's first look follows, then the summary. -> False once closed."""
        if self._closing.is_set():
            return False
        return self._worker.put(self._fresh, bool(forget_known), then or _nothing)

    def fresh_counts(self, then):
        """What the fresh library's sheet names (`library_store.fresh_counts`), read on the worker: `then(counts)`, or
        `then(None)` when the store can't be read. -> False once closed."""
        if self._closing.is_set():
            return False
        return self._worker.put(self._fresh_counts, then)

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

    def skippable(self, item_ids, then):
        """`then([folder path])` on the worker: ⋯'s *Never read this folder* choices for these items, deepest first (K6;
        [] for items that came from no folder being read)."""
        ids = list(item_ids)
        return self._worker.put(self._skippable, ids, then) if ids and not self._closing.is_set() else False

    def skip_refused(self, path, then, language=None):
        """Settings' *Skip a folder…* (Q7): `then(why or None)` on the worker — the store's own rule
        (`Store.skip_refused`: a folder being read itself, one inside none, one holding one, one skipped already), asked
        before the writer is (which asks it again). `language`: as `read_again`'s. -> False once closed."""
        if self._closing.is_set() or (language is not None and language != self.language):
            return False
        return self._worker.put(self._skip_refused, path, then)

    def read_again(self, folder_id, then=None, language=None):
        """Settings' *Read again* (K6): `then({"folder", "read", "language"})` on the worker, then a look of the source
        holding it. `language`: the language it was listed in — another's (ids repeat across stores) is refused."""
        if self._closing.is_set() or (language is not None and language != self.language):
            return False
        return self._worker.put(self._read_again, folder_id, then or _nothing)

    def close(self):
        """The window closes (or another language opens): the look under way stops between files, every watch closes,
        the worker's store handle closes after what was queued — and nothing it still finds is told (B2: a language
        left never paints over the one open)."""
        self._closing.set()
        self.on_result = self.on_progress = self.on_ended = _nothing
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
        """(The worker.) This worker's store handle, or None (`_why_closed` says why). P-1: a store only busy this
        moment — another connection opening, closing or committing — is asked again until `BUSY_AT_OPEN` has passed,
        here on the looks' worker (never the window's thread): the opener's own retry of a busy look (`check()` hands
        it to its worker) is waited for and its answer read, never the mode it cached before — so a busy moment is
        never read as no library."""
        from app import library_store as ls
        deadline = time.monotonic() + ls.BUSY_AT_OPEN
        h = self.opener.handle()
        while h is None and not self._closing.is_set():
            check, wait = getattr(self.opener, "check", None), getattr(self.opener, "wait", None)
            if check is not None:
                check()
            if wait is not None:
                wait(max(0.0, deadline - time.monotonic()))
            h = self.opener.handle()
            if h is not None or self._why_closed() != "busy" or time.monotonic() >= deadline:
                break
            time.sleep(0.02)                          # "store", but busy at this thread's own open: again
        return h

    def _why_closed(self):
        """Why `_store()` gave no handle: "no-library" only for a library with no 3.0 store (+ Add copies the folder in,
        as 2.x did: S3); a read-only store's own reason (damaged, newer); else "busy" — said, never the copy-in."""
        settling = getattr(self.opener, "settling", None)
        if settling is not None and settling():
            return "busy"                             # its mode is the one cached before a busy look: no answer
        mode, reason = getattr(self.opener, "mode", None), getattr(self.opener, "reason", None)
        if mode == "json" and reason not in (None, "not checked"):
            return "no-library"
        if mode == "read-only" and reason:
            return reason
        return "busy"

    def _look(self, full, roots):
        """(The worker.) Each source being read (`roots`: those alone) looked at once, then the window told — its
        summary, and whatever happened, that the look ended (`on_ended`: a press waiting on it ends with it)."""
        told, why = False, None
        try:
            store = self._store()
            if store is None:
                why = "the library isn't open"
                return
            self.looks += 1
            rows = store.sources(counts=False)        # the roots alone: the counts are `_publish`'s (H9)
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
            if not self._reset_told:                  # LF-11: a reset a kill left half done, named once a run
                self._reset_told = True
                from app import library_store as ls
                totals["unfinished_reset"] = ls.unfinished_reset(store.user_files_dir, told=True)
            told = self._publish(store, totals)
        except Exception as e:                        # a look that failed waits for the next: never the window's fault
            print(f"Sources: the look stopped: {e!r}")
            why = str(e) or type(e).__name__
        finally:
            if not self._closing.is_set():
                try:
                    self.on_ended(told, why)
                except Exception as e:
                    print(f"Sources: the look's end wasn't told: {e!r}")
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
            self._gone[row["id"]] = not result.get("reachable") and bool(result.get("gone"))
            self._moved += sum(result.get(k) or 0 for k in ("paired", "attached"))     # row 55 IK-1
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
                answer["refused"] = self._why_closed()   # P-1: "no-library" (copied in) only with no 3.0 store
            else:
                from app import library_store as ls
                try:
                    root = store.add_source(path)
                except ls.NotASource as e:
                    answer["refused"] = e.reason
                else:
                    answer["root"] = root
                    row = next((r for r in store.sources(counts=False) if r["id"] == root), {"id": root, "path": path})
                    answer["result"] = self._scan(store, row, full=True, first=first, progress=lambda found, shows:
                                                  self.on_progress(row["path"], found, shows))
                    if answer["result"] is None or answer["result"].get("busy"):
                        answer["later"] = True        # read from now on; its first look comes with the next one
                    for item_id in (answer["result"] or {}).get("ids") or ():
                        item = store.item(item_id)
                        if item is not None and item["tier"] == "arrivals":
                            answer["arrivals"] += 1      # D6: the shows never shown wait there
                    self._follow_watches(store.sources(counts=False))
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
                with self._lock:
                    self._again_at.pop(root_id, None)
                    w = self._watches.pop(root_id, None)
                if w is not None:
                    _close(w)
                self._reachable.pop(root_id, None)
                self._gone.pop(root_id, None)
        except Exception as e:
            answer["refused"] = str(e) or repr(e)
        with self._lock:
            self._stopping.discard(root_id)
        then(answer)
        if store is not None:
            self._publish(store, {})

    def _find(self, root_id, path, then):
        answer = {"old": root_id, "path": path, "root": None, "refused": None, "failed": None, "result": None,
                  "state": None, "joined": 0, "stop": False, "language": self.language}
        store = None
        try:
            store = self._store()
            if store is None:
                answer["refused"] = self._why_closed()
            else:
                from app import library_store as ls
                old = next((r for r in store.sources(all=True, counts=False) if r["id"] == root_id), None)
                if old is None:
                    answer["refused"] = "That folder isn't being read any more."
                else:
                    try:
                        root = store.add_source(path)
                    except ls.NotASource as e:
                        answer["refused"] = e.reason
                    else:
                        answer["root"] = root
                        row = next((r for r in store.sources(counts=False) if r["id"] == root),
                                   {"id": root, "path": path})
                        answer["result"] = self._scan(store, row, full=True, progress=lambda found, shows:
                                                      self.on_progress(row["path"], found, shows))
                        if answer["result"] is None or answer["result"].get("busy"):
                            answer["later"] = True    # read from now on: the next look joins what it attaches (D5)
                        answer["state"] = sources.reach(old["path"], sources.volume_of(store, self.language, root_id,
                                                                                         old["path"]))
                        if answer["state"] == sources.GONE and root != root_id and not answer.get("later"):
                            answer["joined"] = store.join_moved(root_id, row["path"])
                            answer["stop"] = old["on"]
                        self._follow_watches(store.sources(counts=False))
        except Exception as e:
            if answer["root"] is None:
                answer["refused"] = str(e) or repr(e)
            else:                                     # the folder is read already: said as it stands, never refused
                answer["failed"] = str(e) or repr(e)
                answer["stop"] = False
        then(answer)
        if store is not None:
            self._publish(store, {})

    def _fresh(self, forget_known, then):
        answer = {"done": False, "refused": None, "failed": None, "backup": None, "known": None,
                  "language": self.language}
        store = None
        try:
            store = self._store()
            if store is None:
                answer["refused"] = self._why_closed()   # P-1: "no-library" (copied in) only with no 3.0 store
            else:
                from app import library_store as ls
                try:
                    out = ls.start_fresh(store, forget_known=forget_known)
                except ls.ResetRefused as e:
                    answer["refused"] = e.reason
                else:
                    answer.update(done=True, backup=out["backup"], known=out["known"])
        except Exception as e:                        # put back by the store itself (its status "undone")
            answer["failed"] = str(e) or repr(e)
            answer["aside"] = getattr(e, "folder", None)    # part of it left in the backup (`ResetNotAllBack`)
        try:
            then(answer)
        except Exception as e:                        # the window's fault never stops the folders' first look (H2)
            print(f"Sources: the fresh library's answer wasn't shown: {e!r}")
        if store is None:
            return
        totals = {"added": 0, "waiting": 0, "full": True}
        if answer["done"]:                            # committed: the folders are read again, whatever came after
            self._reachable.clear()
            with self._lock:
                self._again_at.clear()
            try:
                rows = store.sources(counts=False)
                for row in rows:                      # read again from scratch: setup's first scan (SRC-1)
                    if self._closing.is_set():
                        break
                    result = self._scan(store, row, full=True, first=True)
                    if result is not None:
                        totals["added"] += result.get("added", 0)
                        totals["waiting"] += result.get("waiting", 0)
                self._follow_watches(rows)
            except Exception as e:
                print(f"Sources: the fresh library's first look stopped: {e!r}")
        self._publish(store, totals)

    def _fresh_counts(self, then):
        counts = None
        try:
            store = self._store()
            if store is not None:
                from app import library_store as ls
                counts = ls.fresh_counts(store)
        except Exception as e:                        # the sheet opens without them
            print(f"Sources: the fresh library's counts couldn't be read: {e!r}")
        then(counts)

    def _skippable(self, ids, then):
        out = []
        try:
            store = self._store()
            if store is not None:
                out = store.skip_choices(ids)
        except Exception as e:
            print(f"Sources: the folders to skip couldn't be read: {e!r}")
        then(out)

    def _skip_refused(self, path, then):
        why = None
        try:
            store = self._store()
            if store is not None:
                why = store.skip_refused(path)
        except Exception as e:                        # the writer asks it again: a refusal is its note then
            print(f"Sources: a folder to skip couldn't be checked: {e!r}")
        then(why)

    def _read_again(self, folder_id, then):
        answer = {"folder": folder_id, "read": False, "language": self.language}
        store, root = None, None
        try:
            store = self._store()
            if store is not None:
                root = next((f["root"] for f in store.skipped_folders() if f["id"] == folder_id), None)
                answer["read"] = bool(store.read_folder_again(folder_id))
        except Exception as e:
            answer["refused"] = str(e) or repr(e)
        then(answer)
        if store is not None:
            self._publish(store, {})
        if answer["read"] and root is not None:
            with self._lock:                          # its files come back now, not at the next hour
                if not self._closing.is_set():
                    self._queue(False, {root})

    def _publish(self, store, totals):
        """The summary to `on_result`. -> True when it was told."""
        if store is None:
            store = self._store()
            if store is None:
                return False
        try:
            rows = store.sources()
        except Exception as e:
            print(f"Sources: the folders couldn't be read: {e!r}")
            return False
        summary = dict(totals, language=self.language)
        summary["moved"], self._moved = self._moved, 0
        summary["sources"] = [dict(r, reachable=self._reachable.get(r["id"]),
                                   gone=self._reachable.get(r["id"]) is False and self._gone.get(r["id"], False))
                              for r in rows]
        lost = [r["id"] for r in summary["sources"] if r["gone"]]
        for r in summary["sources"]:
            if r["gone"]:                                         # T6: the card's keys, whatever the read below says
                r.update(shows=[], finished=False, found_in=[])
        if lost:                                                  # T6: a gone folder's card (read only while one is)
            try:
                detail = store.source_detail(lost)
                for r in summary["sources"]:
                    r.update(detail.get(r["id"]) or {})
            except Exception as e:
                print(f"Sources: a gone folder's shows couldn't be read: {e!r}")
        try:
            summary["skipped"] = store.skipped_folders()          # K6: Settings' *Skipped folders*
        except Exception as e:
            print(f"Sources: the skipped folders couldn't be read: {e!r}")
        self.on_result(summary)
        return True

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
                                             f"{ls._ORIGIN_ROW} AND NOT {ls._VERSION_ROW} ORDER BY p.rowid LIMIT 1",
                                             (item_id,)).fetchone()     # never another version's (LM1b)
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
            try:
                self._watch_once()
            except Exception as e:                    # H10: one bad turn never ends the watches for the run
                print(f"Sources: a watch report wasn't handled: {e!r}")
                self._closing.wait(0.5)               # (never a busy loop on an error that repeats)

    def _watch_once(self):
        """One turn of the watch thread. `_again_at` is read and written under the lock only (H10: the worker clears
        it, a *Stop reading* pops it)."""
        with self._lock:
            watches = list(self._watches.items())
            again = list(self._again_at.values())
        dues = [d for d in (w.due() for _r, w in watches) if d is not None]
        now = time.monotonic()                        # (the watches' own time: real, never the cadence's clock)
        dues += [max(0.0, at - now) for at in again]
        self._wake.wait(min(dues) if dues else None)
        self._wake.clear()
        if self._closing.is_set():
            return
        now = time.monotonic()
        changed = set()
        for root, w in watches:
            if getattr(w, "state", "watching") != "watching":
                with self._lock:                      # ended (the drive went): looked at now, the cadence after
                    if self._watches.get(root) is w:
                        del self._watches[root]
                    self._again_at.pop(root, None)
                changed.add(root)
                continue
            folders, whole = w.take()
            if folders or whole:
                with self._lock:
                    self._again_at[root] = now + self._quiet        # pushed back by every later report
        with self._lock:
            for root, at in list(self._again_at.items()):
                if at <= now:
                    del self._again_at[root]
                    changed.add(root)
        if not changed:
            return
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

