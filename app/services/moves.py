"""The window's writer and the numbers at the drop (W3.1a row F; the window's spec 04 §4.5, 02 §2.3–2.4, 06 E4 / E5 / E6
/ E21): every store command the window gives runs here, on a plain thread of its own — never the window's thread.

- **`Writer`**, one per language: its own store handle (opened on its thread through an opener of
  `library_store.StoreOpener`'s shape, role "window"), commands queued in the order given — `move` (a Goal-well drop:
  `end=True`, Goal's end as it stands when the write lands), `nudge`, `set_tier` (Finished is the store's `graduated`),
  `set_finished` (the store's `finish`: the Finished toast's *Keep* / *Take its new cards out*; `follows=` the drop's
  change, so that drop's Undo takes the cards' choice back too), `set_watched`, `insert_at` (an Explorer drop: the
  content files copied into the tier's folder at once on a copier thread of its own, then queued and placed), `undo`;
  W3.2's: `place` (New arrivals' icons and ⋯), `put_back` (Finished → the top of Current, its cards back in the
  order), `import_finished` (the Finished importer's store half), `relink` / `its_new` (Needs you's *Link these*, the
  rename asks), `link_video` (Connect's *Link…*: a video, never `relink`), `remove` / `restore` (the trash, 30 days),
  `pin`, `keep_cards` (a Finished item's cards out of / back in the order), `ask_mining`, `split` / `join`,
  `set_media_type`, `set_cover`. Each
  returns at once (the window has already painted its
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

- **`plan_check(language, settings)`**: `Numbers`' full staleness verdict (the replan host's `plan_engine.check`);
  **`open_library(language)`**: the reader and the numbers on one opener (the writer takes the same opener).

Its user-facing words are the window's (`app/qt/strings.py`'s `MOVE_WORDS`, handed to `words`): nothing here holds one.
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
JOURNALLED = ("move", "nudge", "set_tier", "finish", "set_watched",
              "place", "put_back", "import_finished", "relink", "its_new", "link_video", "remove", "restore", "pin",
              "keep_cards", "ask_mining", "split", "join", "set_media_type", "set_cover")
#   an undo needs its Change: never journalled; nor an Explorer drop (`insert_at`: no ids yet). Its files are copied into
#   the tier's folder at once, on the copier's thread — a busy store or a drag never holds the copy back, and the copy
#   never holds a move back (G1) — so a quit or a crash before it lands leaves them whole in the folder, where the next
#   disk sync adds them (AD-2)
ANALYSED = ("now", "soon", "goal")                          # the plan engine's tiers, in a Generate's order
PLAN_FILE = "plan.json.gz"      # `analyzer.PLAN_FILE` (not imported: the analyzer is heavy; a test holds them equal)
CHANGED_KEPT = 64               # `Numbers.changed` remembers this many versions back

WORDS = ("saving", "cant_undo", "nearest", "top", "crash_one", "crash_many", "read_only", "failed", "put_back_as")
#   the keys `words` must hold (`strings.MOVE_WORDS`); "not_content" ({names}: the files an Explorer drop left out) may
#   be held too — without it that note is `failed`'s, with the names. "put_back_as" ({names}): files a Put back brought
#   back under a new name (theirs was taken)
PLACES = ("top", "after-show", "soon", "goal", "finished")  # `place`'s targets (`Store.place`)
KEPT = ("tier", "before_id", "after_id", "near", "direction", "on", "keep_cards", "end", "seen",
        "where", "paths", "copied", "path", "trash_ids", "piece_id", "piece_ids", "work_ids", "media_type",
        "work_id", "source", "ref", "locked")
#   a journal entry's values beside its op and ids (`_entry`): each command's own
PART = ".part"                  # a dropped file is copied under its name + this (no content name: no sync takes it up),
#                                 then renamed whole


def journal_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"window_pending_{language}.json")


def store_opener(language):
    """The window's opener for `language`'s store (role "window"): a handle per thread, so one opener can serve the
    reader's thread and the writer's."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    return library_store.StoreOpener(language, get_data_path(language), get_user_files_path(language), role="window")


def plan_check(language, settings):
    """`Numbers`' full staleness verdict (`check=`), built as the replan host's (`replan_preview.Host._parts` /
    `_verdict`): the run signature's parts for the library as it stands — every file stat'd, a missing item keeping its
    place — checked by `plan_engine.check`. `settings`: settings.json's values, or a function giving them (read at each
    check: a setting changed since is a Generate first). -> `check(plan, store)` (it runs on the numbers' worker): the
    reason when a Generate must come first, else None — current, re-plan now (only the known words or the lists moved:
    *N new* still follows the order), or stands aside (`Numbers` says so itself)."""
    def check(plan, store):
        from app import analyzer, plan_engine, run_args
        from app.path_utils import get_user_file
        values = settings() if callable(settings) else settings
        found = analyzer.resolve_found_files(language, verbose=False, schedule=store.schedule(), missing=True)
        args = analyzer.parse_analysis_args(run_args.analyzer_args(values, language)[1:])
        parts = analyzer.run_signature_parts(language, found, args)
        stamp = analyzer.read_run_stamp(get_user_file("results"))
        verdict = plan_engine.check(plan, language, analyzer.engine_id(), stamp, parts, store.versions().get("epoch"))
        return verdict[1] if verdict is not None and verdict[0] == "generate-first" else None
    return check


def open_library(language, check=None, **reader_kw):
    """The window's library on one opener: the reader, and the numbers it shows — told of every move of
    the order (another program's, hato's drop, an undo elsewhere) and refreshing the reader when they change. Nothing
    started: the caller calls `numbers.load()` and `reader.start()`, and hands the same opener to the `Writer`.
    `check`: `Numbers`' verdict (`plan_check`). -> (opener, numbers, reader)."""
    from app.services.library_reader import LibraryReader
    opener = store_opener(language)
    held = []
    numbers = Numbers(opener, language, check=check, on_change=lambda: held and held[0].refresh())
    reader = LibraryReader(opener, language, numbers=numbers, **reader_kw)
    held.append(reader)
    reader.subscribe_moves(lambda _language, _versions: numbers.resync())
    return opener, numbers, reader


def _nothing(*_args):
    pass


def _ls():
    from app import library_store
    return library_store


class Writer:
    def __init__(self, opener, language="ja", journal_file=None, numbers=None, on_saved=None, on_saving=None,
                 on_reread=None, on_note=None, on_undone=None, depth=UNDO_DEPTH, retry=RETRY_S,
                 saving_after=SAVING_AFTER_S, words=None, after_commit=None):
        missing = [k for k in WORDS if k not in (words or {})]
        if missing:                                 # the window's words (`strings.MOVE_WORDS`): never a key shown
            raise ValueError(f"the writer's words lack {missing}")
        self.words = words
        self.opener = opener
        self.language = language
        self.journal_file = journal_file
        self.numbers = numbers
        self.on_saved = on_saved or _nothing
        self.on_saving = on_saving or _nothing
        self.on_reread = on_reread or _nothing
        self.on_note = on_note or _nothing
        self.on_undone = on_undone or _nothing
        self.after_commit = after_commit or _nothing    # (change, op) after every write the store committed, a replay's
        #                                                 too, on this thread (P4.1 hangs `window_link.Link.after_change`)
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
        self._copier = Worker(f"window-copier-{language}")    # an Explorer drop's files, off the writer's thread
        self._copying = 0                           # drops whose files are being copied (not queued yet)
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

    def move(self, ids, tier, before_id=None, after_id=None, near=(), label=None, end=False):
        """`Store.move`. `near`: [(item_id, "before" | "after"), …], the nearest first — where the window would place the
        block if its anchor is gone when the write lands (its neighbours as painted). `end`: the tier's end as it stands
        when the write lands (a drop on the Goal well: read from the store on this thread, again at a replay — never an
        id from the window's copy, which a queued write can outlive). -> the command's number, or None when refused
        (read-only)."""
        cmd = {"op": "move", "ids": list(ids), "tier": tier, "before_id": before_id, "after_id": after_id,
               "near": [list(n) for n in near or ()], "label": label}
        if end:
            cmd.update(before_id=None, after_id=None, end=True)
        return self._put(cmd)

    def nudge(self, ids, direction, label=None):
        return self._put({"op": "nudge", "ids": list(ids), "direction": direction, "label": label})

    def set_tier(self, ids, tier, label=None):
        """`Store.set_tier` — "graduated" is Finished."""
        return self._put({"op": "set_tier", "ids": list(ids), "tier": tier, "label": label})

    def set_finished(self, ids, keep_cards=True, label=None, follows=None):
        """`Store.finish`: to Finished, dated now; `keep_cards=False` (the Finished toast's *Take its new cards out*)
        also takes the items' cards out of the learning order and ends their pin. An item already in Finished keeps its
        place and date (only its cards' choice is written). `follows`: the change this one follows (the drop on
        Finished: `set_tier`'s, as `on_saved` handed it on) — an `undo` of that change undoes this one first, so the
        toast's Undo puts the item back with its cards; Ctrl+Z still takes this one back first (it is the newer)."""
        return self._put({"op": "finish", "ids": list(ids), "keep_cards": bool(keep_cards), "label": label,
                          "follows": follows})

    def insert_at(self, paths, tier, before_id=None, after_id=None, near=(), label=None):
        """An Explorer drop: `paths` (files from anywhere) copied at once, on the copier's own thread, into `tier`'s
        folder of the data folder (never over a file: an identical one is already there, another comes in under a new
        name; a file already in a tier's folder stays where it is), then queued and placed by `Store.insert_at` before
        `before_id` / after `after_id`, or at the top of `tier` with neither. The anchor gone or out of the tier when
        the write lands → beside the nearest surviving `near` neighbour, else the top of the tier, with a note. Content
        files only (the disk sync's `is_content_name`): the rest are left out, with a note. The moves given meanwhile
        never wait for the copy (G1): the drop joins the queue once its files are in place, so it may land after them.
        Not journalled: a quit or a crash before it lands leaves the copies whole in the folder, where the next disk
        sync places them (AD-2). Its Undo sends the files it copied to the trash and takes their rows out; a drop that
        copied nothing (its files were in the tiers' folders already) isn't put on the Undo stack."""
        if not self._writable():
            return None                             # E4
        cmd = {"op": "insert_at", "ids": [], "files": [os.fspath(p) for p in paths], "tier": tier,
               "before_id": before_id, "after_id": after_id, "near": [list(n) for n in near or ()], "label": label}
        with self._cond:
            if self._stop:
                return None
            cmd["seq"] = next(self._seq)
            self._copying += 1
        if not self._copier.put(self._copy_then_queue, cmd):
            with self._cond:                        # closed meanwhile (the quit)
                self._copying -= 1
                self._cond.notify_all()
            return None
        return cmd["seq"]

    def set_watched(self, ids, on=True, label=None):
        """`Store.set_watched` on files (an episode is one file, one item)."""
        return self._put({"op": "set_watched", "ids": list(ids), "on": bool(on), "label": label})

    # --- W3.2: New arrivals, Finished, Needs you, the trash, pins, pieces, titles -------------------------------- #
    def place(self, ids, where, label=None):
        """`Store.place`: New arrivals' icons and ⋯ — `where` in `PLACES` (`top` · `after-show` · `soon` · `goal` ·
        `finished`); `after-show` with no show to follow writes nothing (`on_reread`). Undone as a move (a finish)."""
        if where not in PLACES:
            raise ValueError(f"unknown place {where!r}")
        return self._put({"op": "place", "ids": list(ids), "where": where, "label": label})

    def put_back(self, ids, label=None):
        """`Store.put_back_finished`: Finished's *Put back* — the top of Current and its cards back in the order, one
        change (G1.6-10)."""
        return self._put({"op": "put_back", "ids": list(ids), "label": label})

    def import_finished(self, paths, copied=(), label=None):
        """`Store.import_finished` (the importer's store half; its copying job is the caller's, done first): `paths`
        in the data folder land in Finished, dated *Earlier*. `copied`: those the job copied in — its Undo sends
        those to the trash and takes every row it placed out; a file it didn't copy stays where it is."""
        return self._put({"op": "import_finished", "ids": [], "paths": [os.fspath(p) for p in paths],
                          "copied": [os.fspath(p) for p in copied], "label": label})

    def relink(self, item_id, path, label=None):
        """`Store.relink`: a missing item pointed at its content file (`path`, in the data folder) — *Link these*,
        the rename ask's *This one*. Never a video (`link_video`)."""
        return self._put({"op": "relink", "ids": [item_id], "path": os.fspath(path), "label": label})

    def its_new(self, path, label=None):
        """`Store.its_new`: the rename ask's *It's new* — the ask goes, the file joins as any new file. The store keeps
        no change for it: never on the Undo stack (`on_reread`)."""
        return self._put({"op": "its_new", "ids": [], "path": os.fspath(path), "label": label})

    def link_video(self, item_id, video_path, label=None):
        """Connect's *Link…* (`app/connect/link.link`): the episode's video, as a pairing on the existing item —
        anywhere on disk, never through `relink` (which repoints the content file). Refused (`link.Refused`, its
        words) → `failed`'s note, nothing written."""
        return self._put({"op": "link_video", "ids": [item_id], "path": os.fspath(video_path), "label": label})

    def remove(self, ids, label=None):
        """*Remove…*: under the store's write lock (a busy store moves no file), each item's file to the data folder's
        trash (`library_store.trash_file`: its 30-day clock restarted), then `Store.remove` in the same transaction —
        the files back if anything fails. Undo puts the files back (never over a
        file: a taken name comes back as `name_1.ext`, named in a note) and the rows where they stood."""
        return self._put({"op": "remove", "ids": list(ids), "label": label})

    def restore(self, trash_ids, label=None):
        """Put back from the trash (`Store.restore` by trash ids, the files first, as Undo of a remove does). Undo sends
        them back to the trash."""
        return self._put({"op": "restore", "ids": [], "trash_ids": list(trash_ids), "label": label})

    def pin(self, ids, on=True, label=None):
        """`Store.pin` / `Store.unpin`: *Study its cards first* ↔ *Done with its cards*."""
        return self._put({"op": "pin", "ids": list(ids), "on": bool(on), "label": label})

    def keep_cards(self, ids, on, label=None):
        """`Store.set_learning_order`: a Finished item's *Put them back in the order* (on) ↔ *Take its new cards out*
        (off — its pin ends too, as Finish's choice does)."""
        return self._put({"op": "keep_cards", "ids": list(ids), "on": bool(on), "label": label})

    def ask_mining(self, ids, asked=True, label=None):
        """`Store.ask_mining`: the finishing toast's *Mine it too*."""
        return self._put({"op": "ask_mining", "ids": list(ids), "on": bool(asked), "label": label})

    def split(self, piece_id, at_item_id, label=None):
        """`Store.split`: a new piece from `at_item_id` to the piece's end (*Split here*)."""
        return self._put({"op": "split", "ids": [at_item_id], "piece_id": piece_id, "label": label})

    def join(self, piece_ids, label=None):
        """`Store.join`: one piece of several of one title (a drop on a seam); two titles' pieces → `failed`'s note."""
        return self._put({"op": "join", "ids": [], "piece_ids": list(piece_ids), "label": label})

    def set_media_type(self, work_ids, media_type, label=None):
        """`Store.set_media_type`: *What is it?* for the titles (None: back to the guess)."""
        return self._put({"op": "set_media_type", "ids": [], "work_ids": list(work_ids), "media_type": media_type,
                          "label": label})

    def set_cover(self, work_id, source, ref=None, path=None, locked=False, label=None):
        """`Store.set_cover`: a title's cover record; a fetch (`locked=False`) never writes over the user's locked
        choice (nothing written, `on_reread`)."""
        return self._put({"op": "set_cover", "ids": [], "work_id": work_id, "source": source, "ref": ref,
                          "path": path, "locked": bool(locked), "label": label})

    def undo(self, change=None, label=None):
        """Undo `change` (a toast's), or the newest saved change (Ctrl+Z) as it stands when the queue reaches it."""
        return self._put({"op": "undo", "ids": [], "change": change, "label": label}, check_mode=False)

    def can_undo(self):
        with self._cond:
            return bool(self._undo)

    def pending(self):
        with self._cond:
            return len(self._pending) + self._copying

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
            waiting = bool(self._pending or self._copying)
            self._cond.notify_all()
        if waiting:
            self._call(self.on_note, self.words["saving"])
        with self._cond:
            while (self._pending or self._copying) and time.monotonic() < deadline:
                self._cond.wait(min(0.05, max(0.0, deadline - time.monotonic())))
            left = bool(self._pending or self._copying)
            self._stop = True
            self._cond.notify_all()
        self._copier.close()                        # a copy still running finishes; its drop isn't queued (AD-2)
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
                        self._call(self.on_note, self.words["failed"].format(error=e))
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
            self._call(self.on_note, self.words["read_only"].format(reason=reason))
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
            if cmd.get("end"):                      # the tier's end as it stands now (each attempt, a replay's too)
                cmd["after_id"] = self._tier_end(store, cmd)
            if cmd.get("replay"):
                if self._changed_since(store, cmd):
                    self._replay_failed += 1
                    self._landed(cmd)
                    return
            elif cmd["op"] == "move" and not cmd.get("numbered"):
                cmd["numbered"] = (cmd["before_id"], cmd["after_id"])   # the numbers follow the drop once, before its
                self._numbers_move(cmd)                                 # first write
            self._apply(store, cmd)
        except lib.StoreBusy:
            self._busy(cmd)
        except lib.StoreReadOnly as e:
            self._landed(cmd)
            self._call(self.on_note, self.words["read_only"].format(reason=e))
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
            elif op == "finish":
                change = store.finish(cmd["ids"], keep_cards=cmd["keep_cards"])
            elif op == "set_watched":
                change = store.set_watched(cmd["ids"], cmd["on"])
            elif op == "insert_at":
                change, note = self._insert(store, cmd)
            elif op in ("remove", "restore"):
                change = self._remove(store, cmd) if op == "remove" else self._restore(store, cmd)
            else:
                change = self._w32(store, cmd)
        except ValueError:
            if op != "move":
                raise
            change, note = self._nearest(store, cmd)
        if op == "insert_at":
            cmd["saved"] = True                     # its copies are the library's now (never sent to the trash)
            if change is not None:                  # what its Undo may send to the trash: the copies it made only
                change.copied = [_ls().library_rel(cmd["data_dir"], p) for p in cmd["copied"]]
                if not change.copied:               # nothing it copied (its files were in the tiers' folders, or rows
                    change = None                   # already): nothing its Undo could take back — never on the stack
        elif op == "finish" and change is not None and cmd.get("follows") is not None:
            change.follows = cmd["follows"]         # the drop's Undo takes this one back first (AD-6)
            cmd["follows"].follow_up = change
        elif op == "import_finished" and change is not None:   # what its Undo sends to the trash: the job's copies
            change.copied = [_ls().library_rel(store.data_dir, p) for p in cmd["copied"]]
        elif op == "restore" and change is not None:           # ... and a Put back's: every file it brought back
            change.copied = [r["rel_path"] for r in map(store.item, change.added) if r is not None]
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
            self._call(self.on_note, self.words[note])
        if cmd.get("left_out"):                     # (AD-4) never a silent drop
            names = ", ".join(cmd["left_out"])
            self._call(self.on_note, self.words["not_content"].format(names=names) if "not_content" in self.words
                       else self.words["failed"].format(error=names))
        if change is not None:
            self._call(self.after_commit, change, op)
        if cmd.get("renamed"):                      # a Put back that couldn't take its own name
            self._call(self.on_note, self.words["put_back_as"].format(names=", ".join(cmd["renamed"])))
        if change is None or note is not None:
            self._call(self.on_reread)
        if op not in UNORDERED and (op != "move" or change is None or note is not None or
                                    cmd.get("numbered") not in (None, (cmd["before_id"], cmd["after_id"]))):
            self._numbers_resync()                  # (a tier's end that moved between the numbers and the write too)

    def _w32(self, store, cmd):
        """W3.2's store commands, each one store call. -> the change, or None."""
        op, ids = cmd["op"], cmd["ids"]
        if op == "place":
            return store.place(ids, cmd["where"])
        if op == "put_back":
            return store.put_back_finished(ids)
        if op == "import_finished":
            return store.import_finished(cmd["paths"])
        if op == "relink":
            return store.relink(ids[0], cmd["path"])
        if op == "its_new":
            store.its_new(cmd["path"])              # a sync's summary, no change: nothing to undo
            return None
        if op == "link_video":
            from app.connect import link
            return link.link(store, ids[0], cmd["path"])
        if op == "pin":
            return store.pin(ids) if cmd["on"] else store.unpin(ids)
        if op == "keep_cards":
            return store.set_learning_order(ids, cmd["on"])
        if op == "ask_mining":
            return store.ask_mining(ids, cmd["on"])
        if op == "split":
            return store.split(cmd["piece_id"], ids[0])
        if op == "join":
            return store.join(cmd["piece_ids"])
        if op == "set_media_type":
            return store.set_media_type(cmd["work_ids"], cmd["media_type"])
        if op == "set_cover":
            return store.set_cover(cmd["work_id"], cmd["source"], ref=cmd["ref"], path=cmd["path"],
                                   locked=cmd["locked"])
        raise ValueError(f"unknown command {op!r}")

    # --- the trash: Remove, Put back, their Undo ------------------------------------------------------------------ #
    def _remove(self, store, cmd):
        """*Remove...*: under the store's write lock first (busy → StoreBusy before any file moves), each file to the
        trash (`trash_file`: its 30-day clock restarted; a missing item has none), then `Store.remove` in the same
        transaction; the files back where they were if anything fails. (The renames are quick: the lock is held for
        them, so nothing can change the rows between the look and the write.)"""
        lib = _ls()
        moved = []
        try:
            with store._writing():
                trashed = {}
                for item_id in cmd["ids"]:
                    row = store.item(item_id)
                    if row is None:
                        continue
                    to = lib.trash_file(store.data_dir, row["rel_path"])
                    if to:
                        trashed[item_id] = to
                        moved.append((_full(store, to), _full(store, row["rel_path"])))
                return store.remove(cmd["ids"], trashed)
        except BaseException:
            _move_back(moved)
            raise

    def _from_trash(self, store, rows, cmd, moved):
        """A Put back's file half (Undo of a remove, `restore`), under the caller's write lock: each row's file back
        from the trash (`put_back`: never over a file; a taken name comes back as `name_1.ext`, named in a note; one
        the trash purged brings its row back missing); each move added to `moved`, for `_move_back`. -> {trash_id:
        rel}."""
        lib = _ls()
        rel_paths = {}
        for row in rows:
            if row["restored_at"] or not row["trashed_path"]:
                continue
            back, _note = lib.put_back(store.data_dir, row["trashed_path"], row["rel_path"])
            if back:
                rel_paths[row["id"]] = back
                moved.append((_full(store, back), _full(store, row["trashed_path"])))
                if back != row["rel_path"]:
                    cmd.setdefault("renamed", []).append(back.rsplit("/", 1)[-1])
        return rel_paths

    def _restore(self, store, cmd):
        """Put back from the trash by trash ids: under the write lock, the files first, then `Store.restore`; the files
        back to the trash if it refuses (a row put back meanwhile, its name an item's again)."""
        moved = []
        try:
            with store._writing():
                rel_paths = self._from_trash(store, store.trash_rows(cmd["trash_ids"]), cmd, moved)
                return store.restore(cmd["trash_ids"], rel_paths)
        except BaseException:
            cmd.pop("renamed", None)
            _move_back(moved)
            raise

    def _undo_removed(self, store, change, cmd):
        """Undo a remove: its rows are in the trash, so what it checks is theirs (a row put back meanwhile is
        skipped). Under the write lock, the files back first, then the rows where they stood (`Store.undo`:
        `restore`); the files back to the trash if the store refuses."""
        lib = _ls()
        moved = []
        try:
            with store._writing():
                rel_paths = self._from_trash(store, store.trash_rows(change.trash_ids), cmd, moved)
                out = store.undo(change, rel_paths=rel_paths)
                if _refused(change, out):
                    raise lib.UndoRefused("every row was put back meanwhile")
                return out
        except BaseException:
            cmd.pop("renamed", None)
            _move_back(moved)
            raise

    def _nearest(self, store, cmd):
        """The anchor is gone or left the tier: the nearest neighbour the window named that is still in the tier, else
        the top of the tier. -> (change, the note's key)."""
        ids, tier = set(cmd["ids"]), cmd["tier"]
        if cmd.get("end"):                          # the end moved since it was read: its end again, no note
            cmd["after_id"] = self._tier_end(store, cmd)
            try:
                return store.move(cmd["ids"], tier, after_id=cmd["after_id"]), None
            except ValueError:
                pass
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

    def _tier_end(self, store, cmd):
        """The last item of the command's tier that it doesn't move (`Store.ids`: one indexed read), or None — the top
        of an empty tier is its end."""
        moving = set(cmd["ids"])
        rest = [i for i in store.ids(cmd["tier"]) if i not in moving]
        return rest[-1] if rest else None

    # --- an Explorer drop ----------------------------------------------------------------------------------------- #
    def _copy_then_queue(self, cmd):
        """(The copier's thread.) The drop's files into the tier's folder, then the drop into the writer's queue — not
        once the writer has stopped (the quit): its copies stay whole in the folder for the next disk sync. A copy that
        fails lets the drop go with a note, its copies to the trash."""
        try:
            data_dir = getattr(self.opener, "data_dir", None)
            if data_dir is None:
                raise ValueError("the library's folder isn't known")
            self._copy_in(data_dir, cmd)
        except Exception as e:
            print(f"Window writer: a dropped file couldn't be copied: {e!r}")
            self._trash_copies(cmd)
            with self._cond:
                self._copying -= 1
                self._cond.notify_all()
            self._call(self.on_note, self.words["failed"].format(error=e))
            self._call(self.on_reread)
            return
        with self._cond:
            self._copying -= 1
            if not self._stop and not self._abandoned:
                self._pending.append(cmd)
                self._start()
            self._cond.notify_all()

    def _copy_in(self, data_dir, cmd):
        """The dropped files into the tier's folder, once, before the drop is queued: content files only (the disk sync's rule; a shortcut, a video, a folder are left out and named in a note); never
        over a file (an identical one is the file already there; another comes in as `name (2).ext`); one already in a
        tier's folder left where it is (one elsewhere in the data folder — its trash — is copied in). `copied`: the
        files made here (the trash's, if the command is let go)."""
        import filecmp
        lib = _ls()
        folder = lib.FOLDER_OF_TIER.get(cmd["tier"])
        if folder is None:
            raise ValueError(f"files can't be dropped into {cmd['tier']!r}")
        cmd["data_dir"] = data_dir
        cmd["started_at"] = lib._now()              # a sync that meets a copy made: the command takes the row over
        walked = {lib.path_key(f) for f in lib.FOLDER_OF_TIER.values()}    # the folders the disk sync walks
        out, made, left = [], [], []
        try:
            for path in cmd["files"]:
                if not os.path.isfile(path) or not lib.is_content_name(path):
                    left.append(os.path.basename(os.path.normpath(path)))       # (AD-4)
                    continue
                rel = lib.library_rel(data_dir, path)
                if rel is not None and lib.path_key(rel.split("/", 1)[0]) in walked:   # (AD-11: not the trash)
                    out.append(path)
                    continue
                dest = os.path.join(data_dir, folder, os.path.basename(path))
                if os.path.exists(dest) and filecmp.cmp(path, dest, shallow=False):
                    out.append(dest)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                dest = _copy_whole(path, dest)
                made.append(dest)
                out.append(dest)
        finally:
            cmd["copied"] = made
        cmd["files"] = out
        cmd["left_out"] = left

    def _insert(self, store, cmd):
        """`Store.insert_at` beside the anchor; gone or out of the tier → beside the nearest surviving `near`
        neighbour, else the top of the tier (with neither anchor: the top, as asked). -> (change, the note's key)."""
        lib = _ls()
        if not cmd["files"]:
            return None, None
        anchor = cmd["before_id"] if cmd["before_id"] is not None else cmd["after_id"]
        if anchor is not None:
            tries = [(anchor, cmd["before_id"] is not None, None)]
            tries += [(a, side == "before", "nearest") for a, side in cmd.get("near") or () if a != anchor]
            for a, before, note in tries:
                item = store.item(a)
                if item is None or item["tier"] != cmd["tier"]:
                    continue
                try:
                    return store.insert_at(cmd["files"], a, before=before, started_at=cmd["started_at"]), note
                except lib.StoreConflict:           # gone between the look and the write
                    continue
        change = store.insert(cmd["files"], cmd["tier"], "top", started_at=cmd["started_at"])
        return change, None if anchor is None else "top"

    def _trash_copies(self, cmd):
        """A drop let go (read-only, an error): the copies it made go to the trash, never left for a sync to place."""
        lib = _ls()
        for path in cmd.get("copied") or ():
            try:
                lib.trash_file(cmd["data_dir"], lib.library_rel(cmd["data_dir"], path))
            except OSError as e:
                print(f"Window writer: a dropped file's copy couldn't go to the trash: {e!r}")

    def _undo_added(self, store, change, ok):
        """Undo an Add: the files it brought in to the trash first, then the rows; the files put back if the store
        refuses. An Explorer drop: its own copies and their rows only (a file that was in the data folder already
        stays where it is, row and all: a sync would add it back, AD-10). The Finished importer's: its job's copies
        (`copied`), and every row it placed out (Finished isn't walked: no sync takes a file up again), its moved rows
        back. A Put back (`restore`): every file it brought back, back to the trash."""
        import copy
        lib = _ls()
        copied = {lib.path_key(r) for r in getattr(change, "copied", ()) if r}
        trashed, moved, mine = {}, [], []
        try:
            for item_id in ok:
                row = store.item(item_id)
                if row is None or lib.path_key(row["rel_path"]) not in copied:
                    continue                        # a file it didn't copy keeps its row: a sync would add it back
                mine.append(item_id)
                to = lib.trash_file(store.data_dir, row["rel_path"])
                if to:
                    trashed[item_id] = to
                    moved.append((_full(store, to), _full(store, row["rel_path"])))
            only = change
            if change.kind != "import_finished":
                if not mine:
                    raise lib.UndoRefused("none of its copies is left to undo")
                only = copy.copy(change)            # its own copies' rows only (AD-10)
                only.added = mine
            out = store.undo(only, trashed_paths=trashed)
            if out is None or _refused(change, out):
                raise lib.UndoRefused("nothing was undone")
            return out
        except BaseException:
            _move_back(moved)
            raise

    def _apply_undo(self, store, cmd, lib):
        change = cmd.get("change")
        if change is None:
            with self._cond:
                change = cmd["change"] = self._undo[-1] if self._undo else None
        if change is None:
            self._landed(cmd)
            return
        refused = False
        then = getattr(change, "follow_up", None)   # the cards' choice made after this drop (AD-6): undone first
        tried = False                               # the choice's undo asked: it leaves the stack (else it stays there)
        try:
            if change.kind == "remove":             # its rows are in the trash: what it checks is theirs
                self._undo_removed(store, change, cmd)
                ok, changed = None, ()
            else:
                ok, changed = store.undo_check(change)
            if changed:
                refused = True
            elif ok is not None:
                if then is not None:                # nothing left of it to undo (its cards put back meanwhile) is no
                    tried = True                    # reason to leave the drop
                    self._undo_one(store, then)
                if change.kind in ("insert", "insert_at", "import_finished", "restore"):
                    self._undo_added(store, change, ok)
                else:
                    refused = self._undo_one(store, change)
        except (lib.StoreConflict, lib.UndoRefused):
            refused = True
            cmd.pop("renamed", None)
        with self._cond:
            for done in (change, then if tried else None):     # a drop refused first: its choice stays undoable
                try:
                    self._undo.remove(done)
                except ValueError:
                    pass
        first = getattr(change, "follows", None)
        if first is not None and getattr(first, "follow_up", None) is change:
            first.follow_up = None                  # undone on its own (Ctrl+Z): the drop's Undo is the drop's alone
        self._landed(cmd)
        if refused:
            self._call(self.on_note, self.words["cant_undo"])
        else:
            self._call(self.on_undone, change, cmd.get("label"))
            self._call(self.after_commit, change, "undo")
            if cmd.get("renamed"):
                self._call(self.on_note, self.words["put_back_as"].format(names=", ".join(cmd["renamed"])))
            self._numbers_resync()
        self._call(self.on_reread)

    def _undo_one(self, store, change):
        """`Store.undo` of a change other than an Add. -> True when it was refused (nothing written)."""
        if change.kind in ("finish", "put_back_finished") and not change.items and \
                not _still_set(store, change.status):
            return True                             # only its cards' choice, and every value changed since: nothing
        if change.kind in ("set_cover", "set_media_type") and not _works_as_set(store, change.works["fields"]):
            return True                             # one of the title's values changed since: a cover's record is one
        return _refused(change, store.undo(change))

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
        the queue's lock, so True and False reach the window in the order they happened — and after the journal is
        written: a row that reads *saving…* survives a crash."""
        with self._cond:
            if not any(c is cmd for c in self._pending):
                return
        self._sync_journal(everything=True)
        with self._cond:
            if not self._saving and any(c is cmd for c in self._pending):
                self._saving = True
                self._call(self.on_saving, True)

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
        if cmd["op"] == "insert_at" and not cmd.get("saved"):
            self._trash_copies(cmd)
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
            self._call(self.on_note, self.words["crash_one"] if failed == 1 else
                       self.words["crash_many"].format(n=failed))
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
        """A replayed command whose items changed since it was queued (or are gone); a Put back's, a trash row put back
        meanwhile (or purged from the table)."""
        if cmd["op"] == "restore" and cmd.get("trash_ids"):
            rows = store.trash_rows(cmd["trash_ids"])
            if len(rows) != len(set(cmd["trash_ids"])) or any(r["restored_at"] for r in rows):
                return True
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


UNORDERED = ("set_watched", "pin", "keep_cards", "ask_mining", "set_cover", "set_media_type", "split")
#   commands that never change the order: the numbers aren't asked again after them


def _refused(change, out):
    """An undo that wrote nothing: no answer, or a status undo that restored nothing. A finish: no row put back and
    every one of its values skipped — the store doesn't hand a finish's restored values back, but its notes count what
    it skipped, its rows' and its values' (AD-15)."""
    if out is None:
        return True
    if change.kind in ("finish", "put_back_finished"):
        return not out.items and _skips(out) - len(change.items) >= len(change.status)
    if change.kind == "remove":
        return not out.restored                     # every row put back meanwhile
    if change.kind == "restore":
        return not out.trash_ids                    # every row it put back changed since
    if change.kind == "import_finished":
        return _skips(out) >= len(change.items) + len(change.added)
    if change.kind in ("split", "join"):
        return _skips(out) >= len(change.pieces["items"])
    if change.kind in ("relink", "register"):       # one item each: its undo skipped it (`link_video`'s is a register)
        return _skips(out) > 0
    return bool(change.status and not out.status)


def _skips(out):
    """How many an undo's notes say it skipped (the store's "N item(s) changed since …")."""
    n = 0
    for note in getattr(out, "notes", None) or ():
        head = str(note).split(" ", 1)[0]
        if head.isdigit() and "changed since" in str(note):
            n += int(head)
    return n


def _works_as_set(store, fields):
    """Whether every title value a change set still holds it. The store's value check (`_undo_works`) goes field by
    field, silently: a cover chosen again since would come back half (another's path, the old source) — so a title's
    change undoes whole or not at all (E21)."""
    for work_id, column, _old, new in fields:
        row = store._work_row(work_id)
        if row is None or row[column] != new:
            return False
    return True


def _still_set(store, status):
    """Whether any of a change's status values still holds what the change set (the store's value check, §6.11)."""
    for item_id, column, _old, new in status:
        row = store.item(item_id)
        if row is not None and row[column] == new:
            return True
    return False


def _copy_whole(src, dest):
    """`src` copied to `dest`, or `name (2).ext`, `name (3).ext`, … — the first free (the importer's `_unique_path`) —
    never over a file: written into `<name>.part`, created exclusively, then renamed without overwriting; a name taken
    meanwhile (another program writing into the folder) steps to the next (AD-12). A sync never meets half a file (a
    `.part` isn't a content name), and a copy that fails removes its part (AD-3). -> the path made."""
    import shutil
    base, ext = os.path.splitext(dest)
    n = 1
    while True:
        name = dest if n == 1 else f"{base} ({n}){ext}"
        n += 1
        if os.path.exists(name):
            continue
        part = name + PART
        try:
            f = open(part, "xb")
        except FileExistsError:
            continue
        try:
            with f, open(src, "rb") as s:
                shutil.copyfileobj(s, f)
            shutil.copystat(src, part)
            _ls()._rename_no_overwrite(part, name)
        except FileExistsError:
            _remove_part(part)
            continue
        except BaseException:
            _remove_part(part)
            raise
        return name


def _full(store, rel):
    return os.path.join(store.data_dir, *rel.split("/"))


def _move_back(moved):
    """The file moves of a command the store refused, undone newest first: [(where it is now, where it was)]."""
    for src, dst in reversed(moved):
        try:
            os.rename(src, dst)
        except OSError as e:
            print(f"Window writer: a file couldn't go back where it was: {e!r}")


def _remove_part(path):
    try:
        os.remove(path)
    except OSError as e:
        print(f"Window writer: a half-made copy couldn't be removed: {e!r}")


def _entry(cmd):
    out = {k: cmd[k] for k in ("op", "ids") if k in cmd}
    for k in KEPT:
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
