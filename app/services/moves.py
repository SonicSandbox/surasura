"""The window's writer and the numbers at the drop (W3.1a row F; the window's spec 04 §4.5, 02 §2.3–2.4, 06 E4 / E5 / E6
/ E21): every store command the window gives runs here, on a plain thread of its own — never the window's thread.

- **`Writer`**, one per language: its own store handle (opened on its thread through an opener of
  `library_store.StoreOpener`'s shape, role "window"), commands queued in the order given — `move`, `nudge`, `set_tier`
  (Finished is the store's `graduated`), `set_watched`, `undo`. Each returns at once (the window has already painted its
  own copy of the order); what happened comes back through callbacks, called on the writer's thread (the window's bridge
  queues them):
  - saved → the `Change` pushed on the Undo stack (`UNDO_DEPTH`, the oldest let go) and `on_saved(change, label)`;
  - `StoreBusy` → **queued, never dropped**: retried in order (later commands wait behind it), `on_saving(True)` once a
    command has waited `SAVING_AFTER_S`, `on_saving(False)` when it lands; and **journalled** to
    `window_pending_<lang>.json` in the local data folder (written atomically; an entry leaves it when the store
    confirms it), so after a crash `replay()` at the next start applies them by id — or, where an item changed
    meanwhile, lists them once (`on_note`: *2 moves from before the crash couldn't be applied*);
  - `None` (nothing to change: the items gone, or already there) → `on_reread()`;
  - `ValueError` (the anchor gone or out of the tier meanwhile) → placed again by id beside the nearest neighbour the
    window named (`near`) that is still in that tier, else at the top of the tier, with one note and `on_reread()`;
  - `StoreConflict` / a refused undo → *Can't undo — that item changed since* (E21), the change let go, nothing written;
  - read-only → refused before it is painted: `can_write()` answers from the opener's mode (asked at the press, E4); a
    command that meets read-only anyway says the store's reason (`on_note`) and is let go.
  Never a dialog; the thread never dies of an error (a raw error → a logged note, the queue goes on).
- **`hold()` / `release()`** (E6): while a drag runs nothing new is applied; the window's moves queue, in order, and land
  after `release()`.
- **`finish(deadline)`**: the quit waits for the queue (*Saving your moves…*); what is left at the deadline stays in the
  journal for the next start.
- **`Numbers`**: the reader's numbers provider (`numbers()` → (version, {item_id: (known, counted, n_new)})) over the plan
  engine, built from the plan file on its own worker. *% known* is the plan's own per-file count (the tokens known before
  any file over the tokens counted: order-free, as the last Generate left it); *N new* is the engine's, kept live by
  `after_move` (the touched rows within RP-6's 50 ms) and `resync()` for everything else. With no plan, a plan that
  stands aside or one that no longer describes the library, `why()` says so and the moves answer nothing.

Qt-free (the import guard): no Qt, Tk or pandas; the store, the plan engine and the paths are imported where used.
"""
import itertools
import json
import os
import threading
import time
from collections import deque

from app.services.automation import Worker

UNDO_DEPTH = 40                 # A2: Ctrl+Z and every move toast's Undo reach this far back
SAVING_AFTER_S = 0.3            # a command waiting this long marks its rows *saving…* (04 §4.5)
RETRY_S = 0.25                  # a busy store is asked again this often (a write itself waits LOCK_TIMEOUT first)
WAIT_S = 0.5                    # the thread looks at its queue at least this often
MODE_RECHECK_S = 2.0            # idle, the thread asks the store's mode this often (`can_write` reads the answer)
JOURNAL_VERSION = 1
JOURNAL_TRIES = 10              # a journal write Windows refuses (the file held a moment) is tried this many times
JOURNALLED = ("move", "nudge", "set_tier", "set_watched")   # an undo needs its Change: never journalled
ANALYSED = ("now", "soon", "goal")                          # the plan engine's tiers, in a Generate's order
PLAN_FILE = "plan.json.gz"      # `analyzer.PLAN_FILE` (not imported: the analyzer is heavy; a test holds them equal)
CHANGED_KEPT = 64               # `Numbers.changed` remembers this many versions back

STRINGS = {
    "saving": "Saving your moves…",
    "cant_undo": "Can't undo — that item changed since",
    "nearest": "That spot changed meanwhile — placed next to the nearest item instead",
    "top": "That spot changed meanwhile — placed at the top instead",
    "crash_one": "1 move from before the crash couldn't be applied",
    "crash_many": "{n} moves from before the crash couldn't be applied",
    "read_only": "Your library can't be saved right now: {reason}",
    "failed": "That change couldn't be saved: {error}",
}


def journal_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"window_pending_{language}.json")


def store_opener(language):
    """The window's opener for `language`'s store (role "window"): a handle per thread, so one opener can serve the
    reader's thread and the writer's."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    return library_store.StoreOpener(language, get_data_path(language), get_user_files_path(language), role="window")


def _nothing(*_args):
    pass


def _ls():
    from app import library_store
    return library_store


class Writer:
    def __init__(self, opener, language="ja", journal_file=None, numbers=None, on_saved=None, on_saving=None,
                 on_reread=None, on_note=None, on_undone=None, depth=UNDO_DEPTH, retry=RETRY_S,
                 saving_after=SAVING_AFTER_S):
        self.opener = opener
        self.language = language
        self.journal_file = journal_file
        self.numbers = numbers
        self.on_saved = on_saved or _nothing
        self.on_saving = on_saving or _nothing
        self.on_reread = on_reread or _nothing
        self.on_note = on_note or _nothing
        self.on_undone = on_undone or _nothing
        self.retry = retry
        self.saving_after = saving_after
        self._cond = threading.Condition()
        self._jlock = threading.Lock()              # one journal write at a time (the thread, the timer, the quit)
        self._pending = deque()                     # commands in the order given; the head is the one being written
        self._seq = itertools.count(1)
        self._undo = deque(maxlen=depth)            # the Changes saved, newest last
        self._journalled = set()                    # seqs the journal file holds now
        self._journal_dirty = False
        self._held = False
        self._retry_at = 0.0
        self._saving = False
        self._replay_due = False
        self._replay_failed = 0
        self._replay_applied = 0
        self._stop = False
        self._abandoned = False
        self._mode_at = 0.0
        self._thread = None
        self.attempts = 0                           # store writes tried (tests)

    @classmethod
    def for_language(cls, language, **kw):
        return cls(store_opener(language), language, journal_file=journal_path(language), **kw)

    # --- the window's side (any thread; each returns at once) ------------------------------------------------------ #
    def can_write(self):
        """Whether a drag may start (E4), from the opener's mode as last checked (the thread asks it every
        `MODE_RECHECK_S` and before each write) — asked again here when that says no (the opener's `check()` never
        waits on the window's thread): a store that is only busy takes moves (they queue)."""
        if self._writable():
            return True
        try:
            self.opener.check()
        except Exception:
            return False
        return self._writable()

    def _writable(self):
        return self.opener.mode == "store" or getattr(self.opener, "reason", None) == "busy"

    def reason(self):
        """The store's reason when it can't be written (the read-only bar's words), else None."""
        return None if self._writable() else (getattr(self.opener, "reason", None) or self.opener.mode)

    def move(self, ids, tier, before_id=None, after_id=None, near=(), label=None):
        """`Store.move`. `near`: [(item_id, "before" | "after"), …], the nearest first — where the window would place the
        block if its anchor is gone when the write lands (its neighbours as painted). -> the command's number, or None
        when refused (read-only)."""
        return self._put({"op": "move", "ids": list(ids), "tier": tier, "before_id": before_id, "after_id": after_id,
                          "near": [list(n) for n in near or ()], "label": label})

    def nudge(self, ids, direction, label=None):
        return self._put({"op": "nudge", "ids": list(ids), "direction": direction, "label": label})

    def set_tier(self, ids, tier, label=None):
        """`Store.set_tier` — "graduated" is Finished."""
        return self._put({"op": "set_tier", "ids": list(ids), "tier": tier, "label": label})

    def set_watched(self, ids, on=True, label=None):
        """`Store.set_watched` on files (an episode is one file, one item)."""
        return self._put({"op": "set_watched", "ids": list(ids), "on": bool(on), "label": label})

    def undo(self, change=None, label=None):
        """Undo `change` (a toast's), or the newest saved change (Ctrl+Z) as it stands when the queue reaches it."""
        return self._put({"op": "undo", "ids": [], "change": change, "label": label}, check_mode=False)

    def can_undo(self):
        with self._cond:
            return bool(self._undo)

    def pending(self):
        with self._cond:
            return len(self._pending)

    def hold(self):
        """A drag starts (E6): nothing new is applied until `release()`; the window's moves queue."""
        with self._cond:
            self._held = True
            if self._pending:
                self._journal_dirty = True
            self._cond.notify_all()

    def release(self):
        with self._cond:
            self._held = False
            self._cond.notify_all()

    def replay(self):
        """At start: the journal's moves (a crash, or a quit that ran out of time) go first in the queue, applied by id;
        those whose items changed meanwhile are listed once. Nothing while the store can't be written (ask again)."""
        if not self.can_write():
            return False
        with self._cond:
            self._replay_due = True
            self._start()
            self._cond.notify_all()
        return True

    def start(self):
        """At open: the store's mode asked once here (`check()` never waits), then the thread."""
        try:
            self.opener.check()
        except Exception:
            pass
        with self._cond:
            self._start()
        return self

    def finish(self, deadline):
        """(The quit's worker.) Wait for the queue until `deadline` (monotonic), saying *Saving your moves…* while it
        waits; whatever is left stays in the journal. -> True when everything landed."""
        with self._cond:
            if self._stop:
                return not self._pending            # finished already: the journal is as that left it
            self._held = False
            waiting = bool(self._pending)
            self._cond.notify_all()
        if waiting:
            self._call(self.on_note, STRINGS["saving"])
        with self._cond:
            while self._pending and time.monotonic() < deadline:
                self._cond.wait(min(0.05, max(0.0, deadline - time.monotonic())))
            left = bool(self._pending)
            self._stop = True
            self._cond.notify_all()
        if left:
            self._sync_journal(everything=True)
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, deadline - time.monotonic()))
        return not left

    # --- queueing ------------------------------------------------------------------------------------------------- #
    def _put(self, cmd, check_mode=True):
        if check_mode and not self._writable():
            return None                             # E4: refused before it is painted
        with self._cond:
            if self._stop:
                return None
            cmd["seq"] = next(self._seq)
            self._pending.append(cmd)
            if self._held or self._journalled:
                self._journal_dirty = True          # stuck already: the journal takes it at once
            self._start()
            self._cond.notify_all()
        return cmd["seq"]

    def _start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name=f"window-writer-{self.language}", daemon=True)
            self._thread.start()

    def _abandon(self):
        """(Tests: a crash.) The thread stops at its next look, leaving the queue and the journal as they are."""
        with self._cond:
            self._abandoned = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(10)

    # --- the thread ----------------------------------------------------------------------------------------------- #
    def _run(self):
        try:
            self._check()
            while True:
                job, cmd = self._next()
                if job == "exit":
                    break
                try:
                    if job == "replay":
                        self._load_journal()
                    elif job == "journal":
                        self._sync_journal(everything=True, fill=True)
                    elif job == "check":
                        self._check()
                    else:
                        self._attempt(cmd)
                except Exception as e:              # never dies: the command is let go with a note, the queue goes on
                    print(f"Window writer: {e!r}")
                    if cmd is not None:
                        self._landed(cmd)
                        self._call(self.on_note, STRINGS["failed"].format(error=e))
                        self._call(self.on_reread)
        finally:
            try:
                self.opener.close()                 # this thread's handle (`StoreOpener.close`)
            except Exception:
                pass

    def _next(self):
        with self._cond:
            while True:
                if self._abandoned or self._stop:
                    return "exit", None
                if self._replay_due:
                    self._replay_due = False
                    return "replay", None
                now = time.monotonic()
                blocked = self._held or now < self._retry_at
                if self._pending and not blocked:
                    return "apply", self._pending[0]
                if self._journal_dirty and self._pending:
                    self._journal_dirty = False
                    return "journal", None
                if now - self._mode_at >= MODE_RECHECK_S:
                    return "check", None
                wait = WAIT_S
                if not self._held and now < self._retry_at:
                    wait = min(wait, self._retry_at - now)
                self._cond.wait(wait)

    def _check(self):
        self._mode_at = time.monotonic()
        try:
            self.opener.check()
        except Exception as e:
            print(f"Window writer: the store's mode couldn't be read: {e!r}")

    def _store(self):
        """(handle, busy): this thread's handle, or None with whether the store is only busy."""
        self._check()
        if self.opener.mode == "store":
            h = self.opener.handle()
            if h is not None:
                return h, False
        return None, getattr(self.opener, "reason", None) == "busy"

    def _attempt(self, cmd):
        lib = _ls()
        cmd.setdefault("first_try", time.monotonic())
        store, busy = self._store()
        if store is None and not busy:
            reason = getattr(self.opener, "reason", None) or self.opener.mode
            self._landed(cmd)
            self._call(self.on_note, STRINGS["read_only"].format(reason=reason))
            self._call(self.on_reread)
            self._numbers_resync()
            return
        self.attempts += 1
        timer = threading.Timer(self.saving_after, self._stuck, args=(cmd,))
        timer.daemon = True
        timer.start()
        try:
            if store is None:
                raise lib.StoreBusy("the library is busy")
            self._fill_seen(store)
            if cmd.get("replay"):
                if self._changed_since(store, cmd):
                    self._replay_failed += 1
                    self._landed(cmd)
                    return
            elif cmd["op"] == "move" and not cmd.get("numbered"):
                cmd["numbered"] = True              # the numbers follow the drop once, before its first write
                self._numbers_move(cmd)
            self._apply(store, cmd)
        except lib.StoreBusy:
            self._busy(cmd)
        except lib.StoreReadOnly as e:
            self._landed(cmd)
            self._call(self.on_note, STRINGS["read_only"].format(reason=e))
            self._call(self.on_reread)
            self._numbers_resync()
            try:
                self.opener.close()                 # a store gone read-only: its handle let go, the mode asked again
            except Exception:
                pass
        finally:
            timer.cancel()

    def _apply(self, store, cmd):
        lib = _ls()
        op = cmd["op"]
        if op == "undo":
            self._apply_undo(store, cmd, lib)
            return
        note = None
        try:
            if op == "move":
                change = store.move(cmd["ids"], cmd["tier"], before_id=cmd["before_id"], after_id=cmd["after_id"])
            elif op == "nudge":
                change = store.nudge(cmd["ids"], cmd["direction"])
            elif op == "set_tier":
                change = store.set_tier(cmd["ids"], cmd["tier"])
            elif op == "set_watched":
                change = store.set_watched(cmd["ids"], cmd["on"])
            else:
                raise ValueError(f"unknown command {op!r}")
        except ValueError:
            if op != "move":
                raise
            change, note = self._nearest(store, cmd)
        self._refresh_seen(store, cmd["ids"])
        self._landed(cmd)
        if cmd.get("replay"):
            if change is not None:
                self._replay_applied += 1
        elif change is not None:
            with self._cond:
                self._undo.append(change)
            self._call(self.on_saved, change, cmd.get("label"))
        if note is not None:
            self._call(self.on_note, STRINGS[note])
        if change is None or note is not None:
            self._call(self.on_reread)
        if op != "set_watched" and (op != "move" or change is None or note is not None):
            self._numbers_resync()

    def _nearest(self, store, cmd):
        """The anchor is gone or left the tier: the nearest neighbour the window named that is still in the tier, else
        the top of the tier. -> (change, the note's key)."""
        ids, tier = set(cmd["ids"]), cmd["tier"]
        for anchor, side in cmd.get("near") or ():
            if anchor in ids:
                continue
            try:                                    # one gone or out of the tier too: ValueError, nothing written
                if side == "before":
                    return store.move(cmd["ids"], tier, before_id=anchor), "nearest"
                return store.move(cmd["ids"], tier, after_id=anchor), "nearest"
            except ValueError:
                continue
        return store.move(cmd["ids"], tier), "top"

    def _apply_undo(self, store, cmd, lib):
        change = cmd.get("change")
        if change is None:
            with self._cond:
                change = cmd["change"] = self._undo[-1] if self._undo else None
        if change is None:
            self._landed(cmd)
            return
        refused = False
        try:
            _ok, changed = store.undo_check(change)
            if changed:
                refused = True
            else:
                out = store.undo(change)
                refused = out is None or bool(change.status and not out.status)
        except (lib.StoreConflict, lib.UndoRefused):
            refused = True
        with self._cond:
            try:
                self._undo.remove(change)
            except ValueError:
                pass
        self._landed(cmd)
        if refused:
            self._call(self.on_note, STRINGS["cant_undo"])
        else:
            self._call(self.on_undone, change, cmd.get("label"))
            self._numbers_resync()
        self._call(self.on_reread)

    def _busy(self, cmd):
        with self._cond:
            self._retry_at = time.monotonic() + self.retry
        if time.monotonic() - cmd["first_try"] >= self.saving_after:
            self._stuck(cmd)
        else:
            self._sync_journal(everything=True)

    def _stuck(self, cmd):
        """`cmd` has waited `saving_after`: its rows read *saving…* and everything queued is journalled. Called by the
        attempt's timer (its own thread) or after a busy answer; nothing once `cmd` has landed. `on_saving` is told under
        the queue's lock, so True and False reach the window in the order they happened."""
        with self._cond:
            if not any(c is cmd for c in self._pending):
                return
            if not self._saving:
                self._saving = True
                self._call(self.on_saving, True)
        self._sync_journal(everything=True)

    def _landed(self, cmd):
        """The head is done with (saved, let go or refused): out of the queue and out of the journal."""
        with self._cond:
            if self._pending and self._pending[0] is cmd:
                self._pending.popleft()
            else:
                try:
                    self._pending.remove(cmd)
                except ValueError:
                    pass
            journalled = cmd["seq"] in self._journalled
            replay_done = cmd.get("replay") and not any(c.get("replay") for c in self._pending)
            if self._saving:
                self._saving = False
                self._call(self.on_saving, False)
            self._cond.notify_all()
        if journalled:
            self._sync_journal(everything=False)
        if replay_done:
            self._replay_finished()

    # --- the journal (04 §4.5: queued moves survive a crash) ------------------------------------------------------ #
    def _sync_journal(self, everything, fill=False):
        """Write the journal: every journalable command queued (`everything`), or only those it already holds (an entry
        leaving it); none left → the file goes."""
        if not self.journal_file or self._replay_due:
            return                                  # a crash's journal is read before anything is written over it
        with self._jlock:
            with self._cond:
                if everything:
                    keep = [c for c in self._pending if c["op"] in JOURNALLED]
                else:
                    keep = [c for c in self._pending if c["seq"] in self._journalled]
                if everything and not fill and {c["seq"] for c in keep} == self._journalled:
                    return                          # the file holds these already (a busy store asked again)
            if fill and keep:
                store, _busy = self._store()
                if store is not None:
                    self._fill_seen(store)
            try:
                if keep:
                    _write_json(self.journal_file, {"version": JOURNAL_VERSION, "language": self.language,
                                                    "pending": [_entry(c) for c in keep]})
                elif os.path.exists(self.journal_file):
                    _patiently(os.remove, self.journal_file)
            except OSError as e:
                print(f"Window writer: the journal couldn't be written: {e!r}")
                return
            with self._cond:
                self._journalled = {c["seq"] for c in keep}

    def _load_journal(self):
        path = self.journal_file
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data["pending"] if data.get("version") == JOURNAL_VERSION else []
            cmds = [_from_entry(e) for e in entries]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Window writer: the journal couldn't be read, set aside: {e!r}")
            try:
                os.replace(path, path + ".bad")
            except OSError:
                pass
            return
        with self._cond:
            for cmd in cmds:
                cmd["seq"] = next(self._seq)
            self._pending.extendleft(reversed(cmds))
            self._journalled |= {c["seq"] for c in cmds}
            self._replay_failed = self._replay_applied = 0
            self._cond.notify_all()
        if not cmds:
            self._sync_journal(everything=False)

    def _replay_finished(self):
        failed, applied = self._replay_failed, self._replay_applied
        self._replay_failed = self._replay_applied = 0
        if failed:
            self._call(self.on_note, STRINGS["crash_one"] if failed == 1 else
                       STRINGS["crash_many"].format(n=failed))
        if failed or applied:
            self._call(self.on_reread)
            self._numbers_resync()

    def _fill_seen(self, store):
        """Each queued command's items as they stand (`Store.check`: their `changed_in`), read once, the first time the
        thread meets it: what a replay compares against. One the journal holds without them is written again."""
        with self._cond:
            todo = [c for c in self._pending if c["op"] in JOURNALLED and c.get("seen") is None]
        for cmd in todo:
            items = store.check(cmd["ids"]).items
            cmd["seen"] = [[i, items.get(i)] for i in cmd["ids"]]
        with self._cond:
            if any(c["seq"] in self._journalled for c in todo):
                self._journal_dirty = True

    def _refresh_seen(self, store, ids):
        """A command landed: the commands queued behind it that touch its items compare against what it left (a move
        made twice before a crash is the user's own, never a change "meanwhile")."""
        ids = set(ids)
        with self._cond:
            later = [c for c in itertools.islice(self._pending, 1, None) if c.get("seen") and ids & set(c["ids"])]
        if not later:
            return
        try:
            now = store.check(list(ids)).items
        except Exception as e:                      # the command itself was saved: never reported as failed
            print(f"Window writer: what a saved command left couldn't be read: {e!r}")
            return
        for cmd in later:
            cmd["seen"] = [[i, now.get(i) if i in ids else v] for i, v in cmd["seen"]]

    def _changed_since(self, store, cmd):
        """A replayed command whose items changed since it was queued (or are gone)."""
        seen = cmd.get("seen")
        if seen is None:
            return False
        now = store.check([i for i, _v in seen]).items      # `changed_in` is never NULL: None is gone
        return any(now.get(i) != v for i, v in seen)

    # --- the numbers ---------------------------------------------------------------------------------------------- #
    def _numbers_move(self, cmd):
        if self.numbers is None:
            return
        try:
            self.numbers.after_move(cmd["ids"], cmd["tier"], before_id=cmd["before_id"], after_id=cmd["after_id"])
        except Exception as e:
            print(f"Window writer: the numbers couldn't follow the move: {e!r}")

    def _numbers_resync(self):
        if self.numbers is not None:
            try:
                self.numbers.resync()
            except Exception as e:
                print(f"Window writer: the numbers couldn't be asked again: {e!r}")

    def _call(self, callback, *args):
        try:
            callback(*args)
        except Exception as e:                      # a listener's fault never stops the writer
            print(f"Window writer: a listener failed: {e!r}")


def _entry(cmd):
    out = {k: cmd[k] for k in ("op", "ids") if k in cmd}
    for k in ("tier", "before_id", "after_id", "near", "direction", "on", "seen"):
        if k in cmd:
            out[k] = cmd[k]
    return out


def _from_entry(entry):
    if entry.get("op") not in JOURNALLED or not isinstance(entry.get("ids"), list):
        raise ValueError(f"not a journal entry: {entry!r}")
    cmd = dict(entry, replay=True, label=None)
    cmd.setdefault("before_id", None)
    cmd.setdefault("after_id", None)
    cmd.setdefault("near", [])
    return cmd


def _write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    _patiently(os.replace, tmp, path)


def _patiently(call, *args):
    """A file call Windows refuses while another program (a virus scanner, an indexer) holds the file a moment: tried
    again for up to ~0.1 s."""
    for _ in range(JOURNAL_TRIES - 1):
        try:
            return call(*args)
        except PermissionError:
            time.sleep(0.01)
    return call(*args)


# ------------------------------------------------------------------------------------------------------------------ #
# The numbers at the drop (RP-6)
# ------------------------------------------------------------------------------------------------------------------ #

class Numbers:
    """The reader's numbers provider over the plan engine. `opener`: `StoreOpener`'s shape (its handle is opened on this
    provider's own worker); `plan_file`: the plan (default: the results folder's); `check(plan, store)`: the caller's
    full staleness verdict — None when current, else the reason (the replan host's `plan_engine.check` with the run
    signature's parts; it stats every file, so it runs here, on the worker); `on_change()`: a new version (the reader's
    `refresh`)."""

    def __init__(self, opener, language="ja", plan_file=None, check=None, on_change=None):
        self.opener = opener
        self.language = language
        self.plan_file = plan_file
        self._check = check
        self._on_change = on_change or _nothing
        self._lock = threading.Lock()
        self.version = 0
        self._table = {}
        self._engine = None
        self._plan_key = None
        self._why = "not read yet"
        self._changed = {}                          # version -> the item ids it changed (None: all)
        self.worker = Worker(f"window-numbers-{language}")
        self.renumbered = 0                         # full passes (tests)

    def __call__(self):
        with self._lock:
            return self.version, self._table

    numbers = __call__

    def why(self):
        """None while *N new* follows the order; else why not (no plan, it stands aside, it's stale, not read yet)."""
        with self._lock:
            return self._why

    def changed(self, since):
        """The item ids whose figures changed after version `since` — None when unknown (too far back, or a whole new
        table): the reader then rebuilds every row."""
        with self._lock:
            if since == self.version:
                return set()
            if since is None or since < self.version - CHANGED_KEPT:
                return None
            out = set()
            for v in range(since + 1, self.version + 1):
                ids = self._changed.get(v)
                if ids is None:
                    return None
                out |= ids
            return out

    def load(self):
        """(Any thread.) Read the plan and build the engine on the worker."""
        self.worker.put(self._load)

    def resync(self):
        """(Any thread.) The store's order may differ from the engine's (a nudge, Finished, an undo, another program):
        compared on the worker, worked out again only when it does; a new plan file is read again."""
        self.worker.put(self._resync)

    def idle(self, timeout=None):
        return self.worker.idle(timeout)

    def close(self):
        self.worker.put(self._close_handle)
        self.worker.close()

    def after_move(self, ids, tier, before_id=None, after_id=None):
        """The window's drop, as `Store.move` places it: the touched rows' new figures {item_id: (known, counted,
        n_new)} — the moved items and every item whose *N new* changed — and a new version; {} when the engine can't
        follow (see `why()`), the rows keeping their figures."""
        from app import plan_engine
        with self._lock:
            eng = self._engine
            if eng is None:
                return {}
            if tier not in ANALYSED:
                self.worker.put(self._resync)       # Finished / New arrivals: out of the order
                return {}
            before = list(eng._n_new)
            try:
                _words, moved = eng.move(list(ids), tier, before_id=before_id, after_id=after_id)
            except plan_engine.PlanError as e:
                self.worker.put(self._resync)
                print(f"Window numbers: the move couldn't be followed: {e}")
                return {}
            after = eng._n_new
            files = {eng._f_of[i] for i in moved}
            files.update(f for f, (a, b) in enumerate(zip(before, after)) if a != b)
            touched = {}
            table = dict(self._table)
            for f in files:
                item = eng._ids[f]
                if item is None:
                    continue
                known, counted, _n = table.get(item, (0, 0, None))
                touched[item] = table[item] = (known, counted, after[f])
            if not touched:
                return {}
            self._publish(table, set(touched))
        self._call_change()
        return touched

    # --- the worker ----------------------------------------------------------------------------------------------- #
    def _plan_path(self):
        if self.plan_file:
            return self.plan_file
        from app.path_utils import get_user_file
        return os.path.join(get_user_file("results"), PLAN_FILE)

    def _store(self):
        self.opener.check()
        return self.opener.handle() if self.opener.mode == "store" else None

    def _load(self):
        from app import library_store, plan_engine
        path = self._plan_path()
        try:
            st = os.stat(path)
        except OSError:
            self._set(None, {}, "no plan: Generate first", None)
            return
        key = (st.st_mtime_ns, st.st_size)
        try:
            plan = plan_engine.load(path)
        except plan_engine.PlanError as e:
            self._set(None, {}, f"plan: {e}", key)
            return
        if plan.header.get("language") not in (None, self.language):
            self._set(None, {}, "plan: another language", key)
            return
        store = self._store()
        if store is None:                           # asked again at the next resync (no key kept)
            self._set(None, {}, f"no store: {getattr(self.opener, 'reason', None) or self.opener.mode}", None)
            return
        by_path = {}
        for tier in library_store.TIERS:
            for item_id, entry, _availability in store.ordered(tier):
                by_path[library_store.path_key(entry.get("physical_path") or "")] = item_id
        ids = [by_path.get(library_store.path_key(entry[0])) for entry in plan.files]
        counts = {}
        for f, item in enumerate(ids):
            if item is not None:
                total, baseline = plan.per_file[f]["prog"][0], plan.per_file[f]["prog"][1]
                counts[item] = (baseline, total, None)
        why = self._stale(plan, store, ids)
        if why is not None:
            self._set(None, counts, why, key)
            return
        try:
            eng = plan_engine.Engine(plan, ids)
            del plan                                # the per-file lines go: the engine keeps its own tables
            order = self._order(store)
            eng._numbers(order)
        except plan_engine.PlanError as e:
            self._set(None, counts, f"stale: {e}", key)
            return
        self.renumbered += 1
        self._set(eng, self._figures(eng, counts), None, key)

    def _stale(self, plan, store, ids):
        aside = _plan_engine().stands_aside(plan)
        if aside:
            return f"stands aside: {aside}"
        epoch = (plan.header.get("store") or {}).get("epoch")
        if epoch is not None and epoch != store.versions().get("epoch"):
            return "stale: the library was rebuilt since the last Generate"
        held = {i for i in ids if i is not None}
        if any(item not in held for item, _tier in self._order(store)):
            return "stale: files came in since the last Generate"
        if self._check is not None:
            try:
                why = self._check(plan, store)
            except Exception as e:
                why = f"the check failed: {e!r}"
            if why:
                return f"stale: {why}"
        return None

    def _order(self, store):
        return [(item, tier) for tier in ANALYSED for item in store.ids(tier)]

    def _resync(self):
        path = self._plan_path()
        try:
            st = os.stat(path)
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        with self._lock:
            eng, plan_key = self._engine, self._plan_key
        if key != plan_key:
            self._load()                            # a new plan file (a Generate), or the first that can be read
            return
        if eng is None:
            return                                  # the same plan still can't be followed: only a Generate changes that
        store = self._store()
        if store is None:
            return
        order = self._order(store)
        plan_engine = _plan_engine()
        with self._lock:
            if self._engine is not eng:
                return
            if [(eng._ids[f], ANALYSED[eng._tier[f]]) for f in eng._order] == order:
                return                              # the window's own moves, already followed
            counts = self._table
            try:
                eng._numbers(order)
            except plan_engine.PlanError as e:      # an item the plan doesn't hold came in: Generate first
                self._engine, self._why = None, f"stale: {e}"
                self._publish({i: (k, c, None) for i, (k, c, _n) in counts.items()}, None)
            else:
                self.renumbered += 1
                table = self._figures(eng, counts)
                changed = {i for i, v in table.items() if counts.get(i) != v}
                if not changed:
                    return
                self._publish(table, changed)
        self._call_change()

    def _figures(self, eng, counts):
        n_new = eng._n_new
        table = {}
        for item, (known, counted, _n) in counts.items():
            f = eng._f_of.get(item)
            table[item] = (known, counted, n_new[f] if f is not None and eng._pos[f] is not None else None)
        return table

    def _set(self, eng, table, why, key):
        with self._lock:
            self._engine, self._why, self._plan_key = eng, why, key
            self._publish(table, None)
        self._call_change()

    def _publish(self, table, changed):
        """(Under the lock.) A new table — a new dict: the reader may still hold the old one — and its version."""
        self._table = table
        self.version += 1
        self._changed[self.version] = changed
        self._changed.pop(self.version - CHANGED_KEPT - 1, None)

    def _call_change(self):
        try:
            self._on_change()
        except Exception as e:
            print(f"Window numbers: a listener failed: {e!r}")

    def _close_handle(self):
        try:
            self.opener.close()
        except Exception:
            pass


def _plan_engine():
    from app import plan_engine
    return plan_engine
