"""The window's writer and the numbers at the drop (W3.1a row F): `app/services/moves.py`.

What a wrong answer would cost a learner:
  * a drag lost — the row back where it was after a busy store, a crash or a quit (charter G1: a move can't be lost);
  * a drag landing out of order, or somewhere the learner never put it (a busy store's queue reordered, a crash's moves
    replayed over a change made since);
  * Undo erasing later work (E21), or an Undo that says it worked and wrote nothing;
  * a drag accepted on a store that can't be written (E4), then silently thrown away;
  * the window freezing while a sync holds the store, or the numbers on a row lagging the drop (RP-6: 50 ms).

The write paths run on a real `library_store` (a small migrated library under the test's own root, Japanese and Chinese
show names from tests/Test Resources); another handle holding the store's write lock — a thread of this process
(another window's save) or a child process (another program's) — makes it busy, with the lock's 5 s wait cut to 0.2 s.
The branches a real store reaches only by accident (read-only in the middle of a write, a raw database error, an undo
from another epoch) run on a stand-in store recording each call. The numbers run on the window's 20,000-file seed with
a plan file shaped like a Generate's.
"""
import gzip
import json
import os
import random
import subprocess
import sys
import threading
import time

import pytest

from app import library_store as ls
from app import plan_engine
from app.qt.strings import MOVE_WORDS as WORDS
from app.services import moves as M
from tests import services_helpers as h
from tests.fixtures import window_seed
from tests.test_library_store_support import migrated, roots, subprocess_env


# --- helpers ------------------------------------------------------------------------------------------------------ #
@pytest.fixture
def short_lock_wait(monkeypatch):
    """The store's write lock waited 0.2 s instead of 5 s: a busy store answers StoreBusy quickly (the same path)."""
    real = ls._WriteLock.acquire

    def acquire(self, timeout=ls.LOCK_TIMEOUT):
        return real(self, min(timeout, 0.2))
    monkeypatch.setattr(ls._WriteLock, "acquire", acquire)


class Heard:
    """Every callback the writer makes, in order."""

    def __init__(self):
        self.lock = threading.Lock()
        self.saved, self.saving, self.notes, self.undone = [], [], [], []
        self.rereads = 0
        self.events = []

    def _add(self, kind, value):
        with self.lock:
            self.events.append((kind, value))

    def kw(self):
        def saved(change, label):
            self.saved.append((change, label))
            self._add("saved", label)

        def saving(on):
            self.saving.append(on)
            self._add("saving", on)

        def note(text):
            self.notes.append(text)
            self._add("note", text)

        def reread():
            self.rereads += 1
            self._add("reread", None)

        def undone(change, label):
            self.undone.append((change, label))
            self._add("undone", label)
        return dict(on_saved=saved, on_saving=saving, on_note=note, on_reread=reread, on_undone=undone)


class Library:
    """A migrated library (NOW, Soon, 6+ Months: three shows of four episodes and a loose file each) and a handle on the
    test's thread — the outside writer (another program, a hato drop)."""

    def __init__(self, language):
        self.language = language
        self.store = migrated(language)
        self.data_dir, self.user_files_dir = roots(language)
        self.db = self.store.db_path

    def opener(self):
        return ls.StoreOpener(self.language, self.data_dir, self.user_files_dir, role="window")

    def current(self):
        return self.store.ids("now") + self.store.ids("soon")

    def ids(self, tier):
        return self.store.ids(tier)

    def close(self):
        self.store.close()


@pytest.fixture(params=["ja", "zh"])
def lib(request):
    library = Library(request.param)
    yield library
    library.close()


@pytest.fixture
def make_writer(lib):
    made = []

    def make(heard=None, **kw):
        heard = heard or Heard()
        kw.setdefault("retry", 0.05)
        kw.setdefault("words", WORDS)
        w = M.Writer(lib.opener(), lib.language, journal_file=M.journal_path(lib.language), **heard.kw(), **kw)
        w.start()
        made.append(w)
        return w, heard
    yield make
    for w in made:
        if not w._abandoned:                            # a crashed writer is gone: nothing to finish
            w.finish(time.monotonic() + 5)


class LockHolder:
    """Another window's save in this process: a thread holding the store's write lock until `release()`."""

    def __init__(self, db):
        self.lock = ls._write_lock_for(db)
        self._go, self._held = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        assert self._held.wait(5)

    def _run(self):
        self.lock.acquire(5)
        self._held.set()
        self._go.wait(30)
        self.lock.release()

    def release(self):
        self._go.set()
        self.thread.join(5)


_PROGRAM = r"""
import sys
from app import library_store as ls
lock = ls._FileLock(sys.argv[1] + ".wlock", byte_range=True)
assert lock.try_acquire()
print("held", flush=True)
sys.stdin.read()
lock.close()
"""


class ProgramHolder:
    """Another program (a child Python) holding the store's OS write lock until `release()`."""

    def __init__(self, db):
        self.proc = subprocess.Popen([sys.executable, "-c", _PROGRAM, db], cwd=h.PROJECT_ROOT, env=subprocess_env(),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().strip()
        assert line == "held", self.proc.stderr.read()

    def release(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)


def journal(language):
    return read_journal(M.journal_path(language))


def read_journal(path):
    for _ in range(50):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:                       # (none, or removed between a look and the read)
            return None
        except PermissionError:                         # Windows: the writer's replace holds it this instant
            time.sleep(0.01)
    raise AssertionError(f"the journal stayed locked: {path}")


def journalled(language):
    data = journal(language)
    return [] if data is None else [(e["op"], e["ids"]) for e in data["pending"]]


# --- saved, Undo -------------------------------------------------------------------------------------------------- #
def test_a_drop_saves_in_the_store_and_its_change_goes_on_the_undo_stack(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    target = goal[5]
    w.move([target], "goal", before_id=goal[0], label="moved up")
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal")[0] == target
    change, label = heard.saved[0]
    assert isinstance(change, ls.Change) and label == "moved up"
    assert w.can_undo() and heard.notes == [] and heard.rereads == 0
    assert journal(lib.language) is None                # a move that lands at once is never journalled


def test_undo_takes_the_newest_change_back_and_says_so(lib, make_writer):
    w, heard = make_writer()
    before = lib.ids("goal")
    w.move([before[7]], "goal", before_id=before[1], label="m")
    w.undo(label="u")                                   # queued behind the move: it undoes the move once it lands
    assert h.until(lambda: heard.undone)
    assert lib.ids("goal") == before
    assert heard.undone[0][1] == "u" and heard.undone[0][0] is heard.saved[0][0]
    assert not w.can_undo()


def test_a_toasts_undo_takes_back_its_own_change_not_the_newest(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.move([goal[4]], "goal", before_id=goal[0])
    w.move([goal[9]], "goal", after_id=goal[11])
    assert h.until(lambda: len(heard.saved) == 2)
    first = heard.saved[0][0]
    w.undo(first)
    assert h.until(lambda: heard.undone)
    order = lib.ids("goal")
    assert order.index(goal[4]) == 4                    # back in its place
    assert order[-1] == goal[9] or order.index(goal[9]) > order.index(goal[11])   # the later move stays
    assert w.can_undo() and len(w._undo) == 1 and w._undo[0] is heard.saved[1][0]


def test_undo_reaches_forty_changes_back_and_lets_the_oldest_go(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    a, b = goal[3], goal[6]
    for n in range(45):                                 # alternate two items to the top: every move is a change
        w.move([a if n % 2 == 0 else b], "goal", before_id=lib.ids("goal")[0] if n == 0 else None)
    assert h.until(lambda: len(heard.saved) == 45, seconds=60)
    assert len(w._undo) == M.UNDO_DEPTH == 40
    kept = list(w._undo)
    assert kept == [c for c, _l in heard.saved[5:]]     # the newest forty, oldest first; the first five let go


def test_set_watched_and_finished_save_and_undo(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    w.set_watched([now[0], now[1]], True)
    w.set_tier([now[2]], "graduated", label="finished")
    assert h.until(lambda: len(heard.saved) == 2)
    assert lib.store.item(now[0])["watched"] == 1
    assert lib.store.place_of(now[2])[0] == "graduated"
    w.undo()                                            # Finished undone first (the newest)
    w.undo()                                            # then the watched marks
    assert h.until(lambda: len(heard.undone) == 2)
    assert lib.store.place_of(now[2])[0] in ("now", "soon")
    assert lib.store.item(now[0])["watched"] == 0 and lib.store.item(now[1])["watched"] == 0


def test_undo_with_nothing_saved_does_nothing(lib, make_writer):
    w, heard = make_writer()
    w.undo()
    w.move([lib.ids("goal")[2]], "goal")                # the queue goes on behind it
    assert h.until(lambda: heard.saved)
    assert heard.undone == [] and heard.notes == []


# --- None, ValueError --------------------------------------------------------------------------------------------- #
def test_a_move_to_where_it_already_is_writes_nothing_and_rereads(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.move([goal[0]], "goal")                           # already the top
    assert h.until(lambda: heard.rereads == 1)
    assert heard.saved == [] and not w.can_undo() and lib.ids("goal") == goal


def test_an_anchor_gone_meanwhile_places_beside_the_nearest_neighbour_the_window_named(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.hold()                                            # the drop is queued; meanwhile another program moves the anchor
    w.move([goal[10]], "goal", before_id=goal[3], near=[(goal[3], "before"), (goal[4], "before"), (goal[2], "after")])
    lib.store.move([goal[3], goal[4]], "now")           # the anchor and its first neighbour leave Goal
    w.release()
    assert h.until(lambda: heard.saved)
    order = lib.ids("goal")
    assert order.index(goal[10]) == order.index(goal[2]) + 1      # after the nearest one still there
    assert heard.notes == [WORDS["nearest"]] and heard.rereads >= 1
    assert w.can_undo()


def test_an_anchor_gone_with_no_neighbour_left_goes_to_the_top_of_the_tier(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.hold()
    w.move([goal[10]], "goal", after_id=goal[3], near=[(goal[3], "after"), (goal[10], "before")])
    lib.store.move([goal[3]], "now")
    w.release()
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal")[0] == goal[10]
    assert heard.notes == [WORDS["top"]]


# --- E4: read-only ------------------------------------------------------------------------------------------------ #
def test_E4_a_read_only_store_refuses_the_drag_before_it_is_painted_and_says_why(lib, make_writer):
    w, heard = make_writer()
    assert w.can_write() and w.reason() is None
    lib.close()
    ls.mark_damaged(lib.db, "test: a damaged store")
    assert h.until(lambda: not w.can_write(), seconds=M.MODE_RECHECK_S * 3)   # the thread asks the mode again
    assert w.reason() == "damaged"
    assert w.move([1], "goal") is None and w.pending() == 0
    assert w.set_watched([1]) is None and w.nudge([1], "up") is None


def test_E4_a_command_that_meets_read_only_anyway_says_the_reason_and_writes_nothing(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.hold()
    assert w.move([goal[5]], "goal") is not None        # accepted while the store could be written
    ls.mark_damaged(lib.db, "test: damaged mid-drag")
    w.release()
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["read_only"].format(reason="damaged")]
    assert heard.saved == [] and heard.rereads == 1 and w.pending() == 0
    os.remove(ls.damaged_marker(lib.db))
    assert lib.ids("goal") == goal


# --- E5: busy ----------------------------------------------------------------------------------------------------- #
def test_E5_a_busy_store_queues_the_moves_journals_them_and_lands_them_in_order_when_freed(lib, make_writer,
                                                                                         short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[8]], "goal", before_id=goal[0], label="first")
        w.move([goal[9]], "goal", before_id=goal[8], label="second")
        w.set_watched([goal[1]], True, label="third")
        assert h.until(lambda: heard.saving == [True])                    # saving… after 300 ms
        assert h.until(lambda: len(journalled(lib.language)) == 3)
        assert journalled(lib.language) == [("move", [goal[8]]), ("move", [goal[9]]), ("set_watched", [goal[1]])]
        time.sleep(0.3)
        assert lib.ids("goal") == goal and heard.saved == []              # nothing written, nothing dropped
        assert w.pending() == 3 and w.attempts >= 2                       # asked again and again
    finally:
        holder.release()
    assert h.until(lambda: len(heard.saved) == 3)
    assert [label for _c, label in heard.saved] == ["first", "second", "third"]
    assert lib.ids("goal")[:2] == [goal[9], goal[8]]
    assert lib.store.item(goal[1])["watched"] == 1
    assert heard.saving == [True, False]
    assert journal(lib.language) is None                                   # emptied entry by entry, then gone


def test_E5_another_programs_save_holding_the_store_queues_the_move_until_it_lets_go(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = ProgramHolder(lib.db)
    try:
        w.move([goal[6]], "goal", before_id=goal[0])
        assert h.until(lambda: journalled(lib.language) == [("move", [goal[6]])])
        assert lib.ids("goal") == goal
    finally:
        holder.release()
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal")[0] == goal[6] and journal(lib.language) is None


def test_E5_a_move_given_while_stuck_joins_the_journal_at_once(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[8]], "goal")
        assert h.until(lambda: len(journalled(lib.language)) == 1)
        w.move([goal[9]], "goal")
        assert h.until(lambda: len(journalled(lib.language)) == 2)
    finally:
        holder.release()
    assert h.until(lambda: len(heard.saved) == 2)
    assert journal(lib.language) is None


def test_E5_a_crash_with_the_queue_full_is_replayed_by_id_at_the_next_start_and_changed_items_are_listed_once(
        lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    x, y, z = goal[8], goal[9], goal[10]
    holder = LockHolder(lib.db)
    w.move([x], "goal", before_id=goal[0])
    w.move([y], "goal", before_id=x)
    w.move([z], "goal", before_id=goal[0])
    w.move([x], "goal", after_id=goal[11])             # the same item moved again: the learner's own, never "changed"
    assert h.until(lambda: len(journalled(lib.language)) == 4)
    w._abandon()                                        # the crash
    holder.release()
    lib.store.move([z], "now")                          # meanwhile another program moves z
    assert lib.ids("goal") != [] and journal(lib.language) is not None

    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: heard2.notes)
    assert heard2.notes == [WORDS["crash_one"]]
    order = lib.ids("goal")
    assert order[0] == y and order.index(x) == order.index(goal[11]) + 1
    assert lib.store.place_of(z)[0] in ("now", "soon")  # where the other program put it
    assert heard2.saved == [] and heard2.rereads >= 1   # replayed moves aren't this session's Undo
    assert journal(lib.language) is None


def test_E5_replay_with_no_journal_does_nothing_and_a_damaged_journal_is_set_aside(lib, make_writer):
    w, heard = make_writer()
    assert w.replay()
    w.move([lib.ids("goal")[3]], "goal")
    assert h.until(lambda: heard.saved)
    path = M.journal_path(lib.language)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: os.path.exists(path + ".bad"))
    assert not os.path.exists(path) and heard2.notes == []


def test_E5_replay_waits_while_the_store_cant_be_written(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    w.move([goal[7]], "goal")
    assert h.until(lambda: journalled(lib.language))
    w._abandon()
    holder.release()
    ls.mark_damaged(lib.db, "test")
    w2, heard2 = make_writer()
    assert not w2.replay()                              # asked again once it can be written
    assert journalled(lib.language) == [("move", [goal[7]])]
    os.remove(ls.damaged_marker(lib.db))
    assert w2.replay()
    assert h.until(lambda: journal(lib.language) is None)
    assert lib.ids("goal")[0] == goal[7] and heard2.notes == []


# --- E6: a drag holds the writer ----------------------------------------------------------------------------------- #
def test_E6_a_move_given_during_a_drag_waits_and_lands_after_release(lib, make_writer):
    # A held move's wait never reads *saving…*: held longer than saving_after, then each save gets a second of its
    # own — at the default 0.3 s, a save slowed by a loaded machine said *saving…*, as it should (a load red).
    w, heard = make_writer(saving_after=1.0)
    goal = lib.ids("goal")
    w.hold()
    w.move([goal[5]], "goal")
    w.move([goal[6]], "goal")
    assert h.until(lambda: len(journalled(lib.language)) == 2)        # held moves survive a crash too
    time.sleep(1.2)
    assert w.attempts == 0 and lib.ids("goal") == goal and heard.saved == []
    w.release()
    assert h.until(lambda: len(heard.saved) == 2)
    assert lib.ids("goal")[:2] == [goal[6], goal[5]]
    assert journal(lib.language) is None and heard.saving == []


# --- E21: Undo after an outside change ------------------------------------------------------------------------------ #
def test_E21_undo_after_an_outside_change_says_cant_undo_and_writes_nothing(lib, make_writer):
    w, heard = make_writer()
    goal = lib.ids("goal")
    w.move([goal[5]], "goal", before_id=goal[0])
    assert h.until(lambda: heard.saved)
    lib.store.move([goal[5]], "goal", after_id=goal[11])          # another program moves it again
    after_outside = lib.ids("goal")
    version = lib.store.versions()["state_version"]
    w.undo()
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]] and heard.undone == []
    assert lib.ids("goal") == after_outside and lib.store.versions()["state_version"] == version
    assert not w.can_undo()                                         # the change is let go


def test_E21_undoing_a_watched_mark_someone_changed_back_says_cant_undo(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    w.set_watched([now[0]], True)
    assert h.until(lambda: heard.saved)
    lib.store.set_watched([now[0]], False)
    w.undo()
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]] and heard.undone == []
    assert lib.store.item(now[0])["watched"] == 0


# --- closing ------------------------------------------------------------------------------------------------------- #
def test_finish_waits_for_the_queue_and_says_so(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    w.move([goal[4]], "goal")
    assert h.until(lambda: w.attempts >= 1)
    threading.Timer(0.6, holder.release).start()
    assert w.finish(time.monotonic() + 10)
    assert WORDS["saving"] in heard.notes
    assert lib.ids("goal")[0] == goal[4] and journal(lib.language) is None
    assert w.move([goal[5]], "goal") is None            # closed: nothing more


def test_finish_with_nothing_queued_returns_at_once(lib, make_writer):
    w, heard = make_writer()
    start = time.monotonic()
    assert w.finish(time.monotonic() + 5)
    assert time.monotonic() - start < 1 and heard.notes == []


def test_finish_leaves_what_it_couldnt_save_in_the_journal_for_the_next_start(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[4]], "goal")
        w.move([goal[5]], "goal")
        assert not w.finish(time.monotonic() + 0.5)
        assert journalled(lib.language) == [("move", [goal[4]]), ("move", [goal[5]])]
        w._thread.join(5)                               # the quit's process ends: its writer with it
        assert not w._thread.is_alive()
        assert journalled(lib.language) == [("move", [goal[4]]), ("move", [goal[5]])]
    finally:
        holder.release()
    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: journal(lib.language) is None)
    assert lib.ids("goal")[:2] == [goal[5], goal[4]] and heard2.notes == []


def test_finish_journals_what_was_queued_moments_before_the_deadline(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[4]], "goal")
        assert h.until(lambda: w.attempts >= 1)
        assert journal(lib.language) is None            # not stuck long enough yet to be journalled
        assert not w.finish(time.monotonic() + 0.05)
        assert journalled(lib.language) == [("move", [goal[4]])]
    finally:
        holder.release()


def test_a_journal_entry_that_isnt_a_move_sets_the_journal_aside(lib, make_writer):
    path = M.journal_path(lib.language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": M.JOURNAL_VERSION, "language": lib.language,
                   "pending": [{"op": "move", "ids": [1], "tier": "goal"}, {"op": "undo", "ids": []}]}, f)
    w, heard = make_writer()
    assert w.replay()
    assert h.until(lambda: os.path.exists(path + ".bad"))
    assert heard.saved == [] and heard.notes == []


def test_a_journal_from_another_version_is_dropped(lib, make_writer):
    path = M.journal_path(lib.language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 99, "pending": [{"op": "move", "ids": [1], "tier": "goal"}]}, f)
    w, heard = make_writer()
    goal = lib.ids("goal")
    assert w.replay()
    assert h.until(lambda: not os.path.exists(path))
    assert lib.ids("goal") == goal


def test_the_journal_lives_in_the_local_data_folder_per_language():
    from app import path_utils
    assert M.journal_path("ja") == os.path.join(path_utils.get_local_data_path(), "window_pending_ja.json")
    assert M.journal_path("zh").endswith("window_pending_zh.json")


def test_the_plan_files_name_is_the_analyzers():
    from app import analyzer
    assert M.PLAN_FILE == analyzer.PLAN_FILE


# --- the stand-in store: branches a real store reaches only by accident --------------------------------------------- #
class StubStore:
    """Records each call; `fail[op]` raises once (or every time with `always`)."""

    def __init__(self):
        self.calls, self.fail, self.always = [], {}, set()
        self.changed_in = {}
        self.gate = None

    def _maybe_fail(self, op):
        exc = self.fail.get(op)
        if exc is not None:
            if op not in self.always:
                del self.fail[op]
            raise exc

    def move(self, ids, tier, before_id=None, after_id=None):
        if self.gate is not None:
            self.gate.wait(10)                          # a slow write (the test opens the gate)
        self.calls.append(("move", list(ids), tier, before_id, after_id))
        self._maybe_fail("move")
        return ls.Change("move", 1, len(self.calls))

    def nudge(self, ids, direction):
        self.calls.append(("nudge", list(ids), direction))
        self._maybe_fail("nudge")
        return ls.Change("move", 1, len(self.calls))

    def set_tier(self, ids, tier):
        self.calls.append(("set_tier", list(ids), tier))
        self._maybe_fail("set_tier")
        return ls.Change("set_tier", 1, len(self.calls))

    def set_watched(self, ids, on):
        self.calls.append(("set_watched", list(ids), on))
        self._maybe_fail("set_watched")
        c = ls.Change("set_watched", 1, len(self.calls))
        c.status = [(i, "watched", 0, 1) for i in ids]
        return c

    def undo_check(self, change):
        self._maybe_fail("undo_check")
        return [], []

    def undo(self, change):
        self.calls.append(("undo", change))
        self._maybe_fail("undo")
        out = ls.Change("undo", 1, len(self.calls))
        out.status = list(change.status)
        return out

    def check(self, ids):
        return ls.Check({i: self.changed_in.get(i, 1) for i in ids}, {}, None)


class StubOpener:
    def __init__(self, store, mode="store", reason=None):
        self.store, self.mode, self.reason = store, mode, reason
        self.closed = 0

    def check(self):
        return self.mode

    def handle(self):
        return self.store if self.mode == "store" else None

    @property
    def data_dir(self):                                 # `StoreOpener.data_dir`: the copier's folder
        return getattr(self.store, "data_dir", None)

    def close(self):
        self.closed += 1


@pytest.fixture
def stub_writer(tmp_path):
    made = []

    def make(mode="store", reason=None, numbers=None, **kw):
        store = StubStore()
        opener = StubOpener(store, mode, reason)
        heard = Heard()
        kw.setdefault("retry", 0.02)
        w = M.Writer(opener, "ja", journal_file=str(tmp_path / "window_pending_ja.json"), numbers=numbers,
                     words=WORDS, **heard.kw(), **kw)
        w.start()
        made.append(w)
        return w, heard, store, opener
    yield make
    for w in made:
        w.finish(time.monotonic() + 5)


def test_a_store_that_turns_read_only_during_a_write_says_its_reason_and_lets_go_of_its_handle(stub_writer):
    w, heard, store, opener = stub_writer()
    store.fail["move"] = ls.StoreReadOnly("the library store is damaged and needs Repair")
    w.move([1], "goal")
    w.move([2], "goal")                                 # the queue goes on
    assert h.until(lambda: len(store.calls) == 2 and heard.saved)
    assert heard.notes[0] == WORDS["read_only"].format(reason="the library store is damaged and needs Repair")
    assert opener.closed >= 1 and len(heard.saved) == 1 and heard.rereads == 1


def test_a_raw_error_is_a_logged_note_and_the_queue_goes_on(stub_writer, capsys):
    w, heard, store, _opener = stub_writer()
    store.fail["nudge"] = RuntimeError("disk I/O error")
    w.nudge([1], "up")
    w.move([2], "goal", label="next")
    assert h.until(lambda: heard.saved)
    assert heard.notes == [WORDS["failed"].format(error="disk I/O error")]
    assert heard.saved[0][1] == "next" and w.pending() == 0
    assert "disk I/O error" in capsys.readouterr().out


def test_a_value_error_outside_a_move_is_a_raw_error(stub_writer):
    w, heard, store, _opener = stub_writer()
    store.fail["set_tier"] = ValueError("unknown tier 'x'")
    w.set_tier([1], "x")
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["failed"].format(error="unknown tier 'x'")]
    assert [c[0] for c in store.calls] == ["set_tier"]  # never re-placed as a move


def test_an_undo_from_another_epoch_or_a_conflict_says_cant_undo(stub_writer):
    w, heard, store, _opener = stub_writer()
    w.set_watched([1], True)
    w.set_watched([2], True)
    assert h.until(lambda: len(heard.saved) == 2)
    store.fail["undo"] = ls.UndoRefused("the library was rebuilt since")
    w.undo()
    assert h.until(lambda: len(heard.notes) == 1)
    store.fail["undo_check"] = ls.StoreConflict("changed meanwhile")
    w.undo()
    assert h.until(lambda: len(heard.notes) == 2)
    assert heard.notes == [WORDS["cant_undo"]] * 2 and heard.undone == [] and not w.can_undo()


def test_an_undo_that_wrote_nothing_says_cant_undo(stub_writer, monkeypatch):
    w, heard, store, _opener = stub_writer()
    w.move([1], "goal")
    assert h.until(lambda: heard.saved)
    monkeypatch.setattr(store, "undo", lambda change: None)
    w.undo()
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]]


def test_an_undo_that_wrote_answers_with_the_change_and_rereads(stub_writer):
    w, heard, store, _opener = stub_writer()
    w.move([1], "goal")
    assert h.until(lambda: heard.saved)
    w.undo(label="u")
    assert h.until(lambda: heard.undone)
    assert heard.undone == [(heard.saved[0][0], "u")] and heard.rereads == 1 and heard.notes == []


def test_a_store_only_busy_at_open_queues_and_marks_saving_after_300_ms(stub_writer, tmp_path):
    w, heard, store, opener = stub_writer(mode="read-only", reason="busy")
    assert w.can_write() and w.reason() is None         # busy takes moves: they queue
    w.move([1], "goal")
    start = time.monotonic()
    assert h.until(lambda: heard.saving == [True])
    assert time.monotonic() - start >= M.SAVING_AFTER_S - 0.05
    assert store.calls == [] and os.path.exists(tmp_path / "window_pending_ja.json")
    opener.mode, opener.reason = "store", None
    assert h.until(lambda: heard.saved)
    assert heard.saving == [True, False] and not os.path.exists(tmp_path / "window_pending_ja.json")


def test_a_quick_busy_answer_is_journalled_before_the_saving_mark(stub_writer, tmp_path):
    w, heard, store, opener = stub_writer(saving_after=5.0)
    store.fail["move"] = ls.StoreBusy("busy")
    store.always.add("move")
    w.move([1], "goal")
    assert h.until(lambda: os.path.exists(tmp_path / "window_pending_ja.json"))
    store.always.discard("move")
    store.fail.pop("move", None)
    assert h.until(lambda: heard.saved)
    assert heard.saving == [] and not os.path.exists(tmp_path / "window_pending_ja.json")


def test_a_json_mode_store_is_not_writable_and_says_not_ready(stub_writer):
    w, heard, store, opener = stub_writer(mode="json", reason="not ready")
    assert not w.can_write() and w.reason() == "not ready"
    assert w.move([1], "goal") is None
    assert w.undo() is not None                          # an undo is never refused at the press (it may have nothing)


def test_a_listener_that_raises_never_stops_the_writer(stub_writer):
    calls = []

    def bad(change, label):
        calls.append(label)
        raise RuntimeError("listener")
    w, heard, store, _opener = stub_writer()
    w.on_saved = bad
    w.move([1], "goal", label="a")
    w.move([2], "goal", label="b")
    assert h.until(lambda: calls == ["a", "b"])


class Recorder:
    def __init__(self):
        self.moves, self.resyncs = [], 0

    def after_move(self, ids, tier, before_id=None, after_id=None):
        self.moves.append((list(ids), tier, before_id, after_id))
        return {}

    def resync(self):
        self.resyncs += 1


def test_the_numbers_follow_a_drop_once_before_its_write_even_when_the_store_is_busy(stub_writer):
    numbers = Recorder()
    w, heard, store, opener = stub_writer(numbers=numbers)
    store.fail["move"] = ls.StoreBusy("busy")
    w.move([5], "now", before_id=3)
    assert h.until(lambda: heard.saved)
    assert numbers.moves == [([5], "now", 3, None)] and numbers.resyncs == 0
    w.nudge([5], "up")
    w.set_tier([5], "graduated")
    w.set_watched([5], True)
    assert h.until(lambda: len(heard.saved) == 4)
    assert numbers.resyncs == 2                          # the nudge and Finished; a watched mark moves no number
    w.undo()
    assert h.until(lambda: heard.undone)
    assert numbers.resyncs == 3


def test_the_numbers_are_asked_again_when_a_drop_lands_elsewhere(stub_writer):
    numbers = Recorder()
    w, heard, store, opener = stub_writer(numbers=numbers)
    store.fail["move"] = ValueError("the anchor is not in that tier")
    w.move([5], "goal", before_id=9, near=[(8, "after")])
    assert h.until(lambda: heard.saved)
    assert store.calls[-1] == ("move", [5], "goal", None, 8)
    assert numbers.resyncs == 1 and heard.notes == [WORDS["nearest"]]


# --- the numbers at the drop ---------------------------------------------------------------------------------------- #
def write_plan(path, rel_paths, tiers, language="ja", seed=3, n_words=3000, header=None):
    """A plan file shaped like a Generate's (`analyzer.plan_lines`, format 1): Zipf-like word uses over the files, each
    file's known tokens before any file (`prog[1]`) and its counted tokens (`prog[0]`)."""
    rnd = random.Random(seed)
    keys = [[f"語{k}", f"ゴ{k}", False, False, 0] for k in range(n_words)]
    weights = [1.0 / (k + 1) ** 0.9 for k in range(n_words)]
    files, per_file = [], []
    for f, (rel, tier) in enumerate(zip(rel_paths, tiers)):
        files.append([rel, tier, f"d{f}"])
        met = list(dict.fromkeys(rnd.choices(range(n_words), weights=weights, k=40)))
        main, tokens = [], []
        for k in met:
            u = rnd.randint(1, 20)
            main += (k, u)
            keys[k][4] += u
            tokens += (k, u)
        total = sum(tokens[1::2]) + rnd.randint(200, 1500)
        per_file.append({"f": f, "main": main, "ph": [], "sp": [],
                         "prog": [total, rnd.randint(total // 3, total - 50), tokens, [], [], [], []]})
    for k, key in enumerate(keys):
        if key[4] == 0:
            per_file[-1]["main"] += (k, 1)
            key[4] = 1
    rows = [[f"JPDB:{k}", None, "", "test", key[0], "", ["一文。", "ep.srt"]] for k, key in enumerate(keys)]
    head = {"format": 1, "language": language, "engine": "test", "run_signature": "r", "order_free_signature": "o",
            "store": {"epoch": None}, "weights": {"now": 10, "soon": 5, "goal": 2}, "floor": 1, "total_tokens": 0,
            "phrase_rows": False, "target_coverage": 0, "only_i_plus_one": False, "max_contexts": 1,
            "files": len(files), "keys": len(keys), "shared_phrases": []}
    head.update(header or {})
    lines = [head, {"files": files}, {"keys": keys}, {"rows": rows}, {"ties": []}] + per_file
    with open(path, "wb") as f:
        f.write(gzip.compress("\n".join(json.dumps(x, ensure_ascii=False) for x in lines).encode("utf-8") + b"\n"))
    return per_file


def _in_order(items):
    """The analysed items as a Generate reads them (NOW, Soon, 6+ Months, each in order): the plan's files' order."""
    return sorted((r for r in items if r["tier"] in M.ANALYSED),
                  key=lambda r: (M.ANALYSED.index(r["tier"]), r["ord"], r["id"]))


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """The window's 20,000-file seed and a plan for every file it analyses (NOW, Soon, 6+ Months)."""
    root = tmp_path_factory.mktemp("moves-big")
    seed = window_seed.build(files=20000, root=str(root))
    analysed = _in_order(seed.items)
    plan_file = os.path.join(str(root), "plan.json.gz")
    per_file = write_plan(plan_file, [r["rel_path"] for r in analysed], [r["tier"] for r in analysed])
    return seed, analysed, plan_file, per_file


def _engine_from_scratch(plan_file, seed):
    """The referee: a fresh engine over the stand-in's order now."""
    plan = plan_engine.load(plan_file)
    by_path = {ls.path_key(r["rel_path"]): r["id"] for r in seed.library.items()}
    ids = [by_path.get(ls.path_key(e[0])) for e in plan.files]
    eng = plan_engine.Engine(plan, ids)
    eng._numbers([(r["id"], r["tier"]) for r in _in_order(seed.library.items())])
    return eng


def test_the_numbers_at_the_drop_come_within_50_ms_on_20000_files_and_equal_a_replan(big):
    seed, analysed, plan_file, per_file = big
    changes = []
    numbers = M.Numbers(seed.opener, "ja", plan_file=plan_file, on_change=lambda: changes.append(1))
    numbers.load()
    assert numbers.idle(120)
    assert numbers.why() is None, numbers.why()
    version, table = numbers()
    first = analysed[0]
    assert table[first["id"]][:2] == (per_file[0]["prog"][1], per_file[0]["prog"][0])   # % known: the plan's own
    assert all(v[2] is not None for i, v in table.items() if seed.library._items[i]["tier"] in M.ANALYSED)

    rnd = random.Random(11)
    times = []
    for _ in range(7):
        rows = {t: sorted((r for r in seed.library.items() if r["tier"] == t), key=lambda r: (r["ord"], r["id"]))
                for t in M.ANALYSED}
        mover = rnd.choice(rows["goal"])
        at = rnd.randrange(len(rows["now"]))
        anchor = rows["now"][at]
        prev = rows["now"][at - 1]["ord"] if at else anchor["ord"] - 1024
        before = numbers.version
        start = time.perf_counter()
        touched = numbers.after_move([mover["id"]], "now", before_id=anchor["id"])
        times.append((time.perf_counter() - start) * 1000)
        assert touched and mover["id"] in touched and numbers.version == before + 1
        assert numbers.changed(before) == set(touched)
        # the store follows (as the writer's write would): between the anchor and the row above it
        seed.library.commit(items=[{"id": mover["id"], "tier": "now", "ord": (prev + anchor["ord"]) / 2}], order=True)
    times.sort()
    print(f"after_move at 20,000 files: median {times[len(times) // 2]:.1f} ms, max {times[-1]:.1f} ms")
    assert times[len(times) // 2] <= 50, times
    referee = _engine_from_scratch(plan_file, seed)
    _v, table = numbers()
    for item, (_k, _c, n_new) in table.items():
        f = referee._f_of.get(item)
        if f is not None and referee._pos[f] is not None:
            assert n_new == referee._n_new[f], item
    numbers.close()


def test_the_numbers_follow_an_outside_move_on_resync_and_say_nothing_when_nothing_moved(big):
    seed, analysed, plan_file, _per_file = big
    numbers = M.Numbers(seed.opener, "ja", plan_file=plan_file)
    numbers.load()
    assert numbers.idle(120) and numbers.why() is None
    v = numbers.version
    numbers.resync()
    assert numbers.idle(60) and numbers.version == v                  # the same order: nothing new
    rows = sorted((r for r in seed.library.items() if r["tier"] == "goal"), key=lambda r: (r["ord"], r["id"]))
    top = min(r["ord"] for r in seed.library.items() if r["tier"] == "now")
    seed.library.commit(items=[{"id": rows[-1]["id"], "tier": "now", "ord": top - 1}], order=True)  # a hato-like move
    numbers.resync()
    assert numbers.idle(60) and numbers.version == v + 1
    assert rows[-1]["id"] in numbers.changed(v)
    referee = _engine_from_scratch(plan_file, seed)
    f = referee._f_of[rows[-1]["id"]]
    assert numbers()[1][rows[-1]["id"]][2] == referee._n_new[f]
    assert numbers.changed(None) is None and numbers.changed(numbers.version) == set()
    numbers.close()


def test_with_no_plan_the_numbers_answer_nothing_and_say_why(tmp_path):
    seed = window_seed.build(root=str(tmp_path))
    numbers = M.Numbers(seed.opener, "ja", plan_file=str(tmp_path / "plan.json.gz"))
    assert numbers.why() == "not read yet" and numbers.after_move([1], "now") == {}
    numbers.load()
    assert numbers.idle(30)
    assert numbers.why().startswith("no plan") and numbers() == (1, {})
    assert numbers.after_move([seed.items[0]["id"]], "now") == {}
    numbers.close()


def test_a_damaged_plan_answers_nothing_and_says_why(tmp_path):
    seed = window_seed.build(root=str(tmp_path))
    path = tmp_path / "plan.json.gz"
    path.write_bytes(b"not gzip")
    numbers = M.Numbers(seed.opener, "ja", plan_file=str(path))
    numbers.load()
    assert numbers.idle(30) and numbers.why().startswith("plan:") and numbers()[1] == {}
    numbers.close()


def _small(tmp_path, header=None, drop=0, language="ja"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    seed = window_seed.build(root=str(tmp_path), language=language)
    analysed = _in_order(seed.items)
    kept = analysed[drop:]
    path = str(tmp_path / "plan.json.gz")
    write_plan(path, [r["rel_path"] for r in kept], [r["tier"] for r in kept], n_words=400, header=header,
               language=language)
    return seed, analysed, path


def test_a_plan_that_stands_aside_keeps_percent_known_and_gives_no_new_count(tmp_path):
    seed, analysed, path = _small(tmp_path, header={"target_coverage": 90})
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30)
    assert numbers.why() == "stands aside: coverage"
    table = numbers()[1]
    assert all(table[r["id"]][2] is None and table[r["id"]][1] > 0 for r in analysed)
    assert numbers.after_move([analysed[-1]["id"]], "now") == {}
    numbers.close()


def test_a_plan_missing_a_file_the_library_counts_is_stale(tmp_path):
    seed, analysed, path = _small(tmp_path, drop=1)
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30)
    assert numbers.why() == "stale: files came in since the last Generate"
    assert analysed[0]["id"] not in numbers()[1] and numbers()[1][analysed[1]["id"]][2] is None
    numbers.close()


def test_a_plan_from_another_epoch_or_language_or_the_callers_check_is_stale(tmp_path):
    seed, analysed, path = _small(tmp_path, header={"store": {"epoch": 99}})
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30) and numbers.why() == "stale: the library was rebuilt since the last Generate"
    numbers.close()
    seed, analysed, path = _small(tmp_path / "zh", language="zh")
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30) and numbers.why() == "plan: another language"
    numbers.close()
    seed, analysed, path = _small(tmp_path / "check")
    numbers = M.Numbers(seed.opener, "ja", plan_file=path, check=lambda plan, store: "settings")
    numbers.load()
    assert numbers.idle(30) and numbers.why() == "stale: settings"
    numbers.close()


def test_a_move_to_finished_is_worked_out_again_on_the_worker(tmp_path):
    seed, analysed, path = _small(tmp_path)
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30) and numbers.why() is None
    item = analysed[0]["id"]
    v = numbers.version
    seed.library.commit(items=[{"id": item, "tier": "graduated"}], order=True)
    assert numbers.after_move([item], "graduated") == {}
    assert numbers.idle(30)
    assert numbers.version == v + 1 and numbers()[1][item][2] is None
    numbers.close()


def test_a_new_plan_file_is_read_again_on_resync(tmp_path):
    seed, analysed, path = _small(tmp_path)
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30)
    loads = numbers.renumbered
    write_plan(path, [r["rel_path"] for r in analysed], [r["tier"] for r in analysed], n_words=300, seed=9)
    os.utime(path, ns=(time.time_ns() + 10 ** 9, time.time_ns() + 10 ** 9))
    numbers.resync()
    assert numbers.idle(30) and numbers.renumbered == loads + 1 and numbers.why() is None
    numbers.close()


def test_the_same_stale_plan_is_not_read_again_on_every_resync(tmp_path, monkeypatch, capsys):
    seed, analysed, path = _small(tmp_path, drop=1)
    loads = []
    real = plan_engine.load
    monkeypatch.setattr(plan_engine, "load", lambda p: loads.append(p) or real(p))
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    numbers.resync()
    numbers.resync()
    assert numbers.idle(30) and numbers.why().startswith("stale") and len(loads) == 1
    numbers.close()
    assert "window-numbers-ja:" not in capsys.readouterr().out      # nothing failed on the worker either


def test_with_no_store_the_numbers_say_so_and_ask_again(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    seed = window_seed.build(root=str(tmp_path), mode="json", reason="not ready")
    analysed = _in_order(seed.items)
    path = str(tmp_path / "plan.json.gz")
    write_plan(path, [r["rel_path"] for r in analysed], [r["tier"] for r in analysed], n_words=400)
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30) and numbers.why() == "no store: not ready" and numbers()[1] == {}
    seed.library.set_mode("store")
    numbers.resync()
    assert numbers.idle(30) and numbers.why() is None and len(numbers()[1]) == len(analysed)
    numbers.close()



# --- the survivors of the first mutant run, each pinned ------------------------------------------------------------- #
@pytest.fixture
def long_lock_wait(monkeypatch):
    """The store's write lock waited 1.5 s: an attempt still blocked when its 300 ms pass."""
    real = ls._WriteLock.acquire

    def acquire(self, timeout=ls.LOCK_TIMEOUT):
        return real(self, min(timeout, 1.5))
    monkeypatch.setattr(ls._WriteLock, "acquire", acquire)


def _second_seen(language):
    data = journal(language)
    return bool(data and len(data["pending"]) == 2 and data["pending"][1].get("seen"))


def test_a_write_still_waiting_at_300_ms_journals_the_queue_then_and_its_items_once_read(lib, make_writer,
                                                                                         long_lock_wait):
    """(M10, M46) The first answer from a busy store comes only after the lock's wait: the queue is journalled at
    300 ms by the attempt's timer, and a command queued during the wait is written again once its items are read."""
    w, heard = make_writer(retry=0.3)
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[6]], "goal")
        assert h.until(lambda: w.attempts >= 1)
        w.move([goal[7]], "goal")
        assert h.until(lambda: len(journalled(lib.language)) == 2, seconds=1.2)     # before the 1.5 s answer
        assert journal(lib.language)["pending"][1].get("seen") is None
        assert h.until(lambda: _second_seen(lib.language), seconds=8)
    finally:
        holder.release()
    assert h.until(lambda: len(heard.saved) == 2)


def test_a_busy_store_is_asked_again_every_retry_not_in_a_spin(stub_writer):
    """(M07) The retry's pause holds between two asks."""
    w, heard, store, opener = stub_writer(mode="read-only", reason="busy", retry=0.3, saving_after=5.0)
    w.move([1], "goal")
    time.sleep(1.0)
    assert 2 <= w.attempts <= 6


def test_a_busy_store_asked_again_doesnt_write_the_same_journal_again(stub_writer, monkeypatch):
    """(M45) The journal is written when what it holds changes, not at every retry."""
    writes = []
    real = M._write_json
    monkeypatch.setattr(M, "_write_json", lambda path, data: writes.append(1) or real(path, data))
    w, heard, store, opener = stub_writer(mode="read-only", reason="busy", retry=0.02, saving_after=5.0)
    w.move([1], "goal")
    time.sleep(0.6)
    assert w.attempts >= 5 and len(writes) == 1


def test_a_move_given_while_stuck_is_journalled_before_the_next_retry(stub_writer, tmp_path):
    """(M13) Stuck already: a new command joins the journal at once, not at the next ask. Told by the order of the two
    events — the journal holds the second command while the writer has asked the store once — not by a 1 s bound (it
    failed under a loaded run); the waits' 30 s ceilings only end a stuck test, and the next ask is a minute away until
    the test lets it come."""
    w, heard, store, opener = stub_writer(retry=60.0, saving_after=120.0)
    store.fail["move"] = ls.StoreBusy("busy")
    store.always.add("move")
    path = tmp_path / "window_pending_ja.json"
    w.move([1], "goal")
    assert h.until(lambda: path.exists())
    w.move([2], "goal")
    assert h.until(lambda: len(read_journal(path)["pending"]) == 2)
    assert w.attempts == 1                              # before the next ask, not at it
    store.always.discard("move")
    store.fail.pop("move")
    with w._cond:                                       # the next ask now: both land
        w._retry_at = 0.0
        w._cond.notify_all()
    assert h.until(lambda: len(heard.saved) == 2 and not path.exists())


def test_a_drag_starting_over_queued_commands_journals_them(stub_writer, tmp_path):
    """(M14) Commands queued behind a slow write when a drag starts wait for the drop: journalled meanwhile."""
    w, heard, store, opener = stub_writer(saving_after=5.0)
    store.gate = threading.Event()
    path = tmp_path / "window_pending_ja.json"
    w.move([1], "goal")
    assert h.until(lambda: w.attempts == 1)
    w.move([2], "goal")
    w.hold()
    store.gate.set()
    assert h.until(lambda: heard.saved)
    assert h.until(lambda: path.exists())
    assert [e["ids"] for e in read_journal(path)["pending"]] == [[2]]
    w.release()
    assert h.until(lambda: len(heard.saved) == 2 and not path.exists())


def test_ctrl_z_undoes_the_newest_change(lib, make_writer):
    """(M27) Two drops, one Ctrl+Z: the second is taken back, the first stays."""
    w, heard = make_writer()
    goal = lib.ids("goal")
    a, b = goal[5], goal[8]
    w.move([a], "goal", before_id=goal[0])
    w.move([b], "goal", before_id=a)
    w.undo()
    assert h.until(lambda: heard.undone)
    assert lib.ids("goal")[0] == a and heard.undone[0][0] is heard.saved[1][0]


def test_a_saving_timer_that_fires_after_its_command_landed_marks_nothing(stub_writer):
    """(M33) The 300 ms timer races the write: a command already landed never turns *saving…* on."""
    w, heard, store, opener = stub_writer()
    w._stuck({"seq": 999, "op": "move", "ids": [1]})
    assert heard.saving == [] and w._saving is False


def test_resync_after_the_windows_own_move_works_nothing_out_again(tmp_path):
    """(M42) The store caught up with a drop the engine already followed: no full pass."""
    seed, analysed, path = _small(tmp_path)
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30) and numbers.why() is None
    passes = numbers.renumbered
    goal = [r for r in analysed if r["tier"] == "goal"]
    now = sorted((r for r in seed.library.items() if r["tier"] == "now"), key=lambda r: (r["ord"], r["id"]))
    assert numbers.after_move([goal[-1]["id"]], "now")
    seed.library.commit(items=[{"id": goal[-1]["id"], "tier": "now", "ord": now[0]["ord"] - 1}], order=True)
    numbers.resync()
    assert numbers.idle(30) and numbers.renumbered == passes
    numbers.close()


def test_changed_across_a_whole_new_table_is_unknown(tmp_path):
    """(M47) A version that replaced every figure (a load) can't be read as a set of ids."""
    seed, analysed, path = _small(tmp_path)
    numbers = M.Numbers(seed.opener, "ja", plan_file=path)
    numbers.load()
    assert numbers.idle(30) and numbers.version == 1
    goal = [r for r in analysed if r["tier"] == "goal"]
    touched = numbers.after_move([goal[-1]["id"]], "now")
    assert numbers.changed(1) == set(touched) and numbers.changed(0) is None
    numbers.close()


def test_nothing_is_journalled_over_a_crashs_journal_before_it_is_read(stub_writer, tmp_path):
    """(M38's ground) A replay asked for: the old journal is read before any write could replace it."""
    w, heard, store, opener = stub_writer()
    path = tmp_path / "window_pending_ja.json"
    path.write_text(json.dumps({"version": M.JOURNAL_VERSION, "pending": [{"op": "move", "ids": [7], "tier": "goal"}]}),
                    "utf-8")
    w._replay_due = True
    w._sync_journal(everything=True)                    # e.g. the quit, or a timer, before the thread read it
    assert read_journal(path)["pending"][0]["ids"] == [7]
    with w._cond:
        w._cond.notify_all()
    assert h.until(lambda: store.calls and store.calls[0][1] == [7])


# --- W3.1a: the words, Goal's end, Finished's cards, an Explorer drop, the verdict, one opener ------------------- #
def test_the_writer_takes_its_words_from_the_window_and_holds_none_itself():
    """moves.py keeps no user string (the window's `strings.MOVE_WORDS`): a writer without every word refuses to start,
    so no note can ever show a bare key."""
    opener = StubOpener(StubStore())
    with pytest.raises(ValueError):
        M.Writer(opener, "ja")
    with pytest.raises(ValueError):
        M.Writer(opener, "ja", words={k: v for k, v in WORDS.items() if k != "cant_undo"})
    assert set(M.WORDS) <= set(WORDS) and not hasattr(M, "STRINGS")
    import ast
    with open(M.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs]
    pieces = [p.strip() for text in WORDS.values() for p in text.replace("}", "{").split("{")[::2] if len(p) > 8]
    assert pieces and not [s for s in literals for p in pieces if p in s]      # none in its code (its docs may cite one)


def _empty_goal(lib, keep=()):
    """Goal holding only `keep`: every other Goal item moved to Soon by another program."""
    rest = [i for i in lib.ids("goal") if i not in keep]
    if rest:
        lib.store.move(rest, "soon")


def test_a_drop_on_the_goal_well_goes_to_the_end_of_goal_and_undoes(lib, make_writer):
    w, heard = make_writer()
    goal, now = lib.ids("goal"), lib.ids("now")
    w.move([now[0]], "goal", end=True, label="to Goal")
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal") == goal + [now[0]] and heard.notes == [] and heard.saved[0][1] == "to Goal"
    w.undo()
    assert h.until(lambda: heard.undone)
    assert lib.ids("goal") == goal and lib.ids("now")[0] == now[0]


def test_a_drop_on_an_empty_goal_well_lands_as_its_only_item(lib, make_writer):
    _empty_goal(lib)
    w, heard = make_writer()
    now = lib.ids("now")
    w.move([now[1]], "goal", end=True)
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal") == [now[1]] and heard.notes == []


def test_a_goal_drop_with_goals_last_item_among_the_dragged_lands_them_together_at_the_end(lib, make_writer):
    """Goal's end is its last item the drop doesn't move: never one of the dragged themselves (the store refuses an
    anchor inside the block, and the drop would be lost)."""
    w, heard = make_writer()
    goal, now = lib.ids("goal"), lib.ids("now")
    w.move([now[0], goal[-1]], "goal", end=True)
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal")[-3:] == [goal[-2], now[0], goal[-1]] and heard.notes == []


def test_a_goal_drop_of_what_goal_already_holds_alone_changes_nothing(lib, make_writer):
    """Goal holding only the moved items: their end is where they are — nothing written, the window reads again."""
    goal = lib.ids("goal")
    _empty_goal(lib, keep=goal[:2])
    w, heard = make_writer()
    w.move(goal[:2], "goal", end=True)
    assert h.until(lambda: heard.rereads == 1)
    assert heard.saved == [] and lib.ids("goal") == goal[:2] and heard.notes == []


def test_a_queued_goal_drop_lands_after_what_another_program_added_to_goal_meanwhile(lib, make_writer):
    """The end is read when the write lands, never when the drop was given (E5: a queued write outlives the window's
    copy) — so the item lands after the one another program appended while it waited."""
    w, heard = make_writer()
    goal, now = lib.ids("goal"), lib.ids("now")
    w.hold()
    w.move([now[0]], "goal", end=True)
    lib.store.move([now[2]], "goal", after_id=goal[-1])     # another program appends to Goal meanwhile
    w.release()
    assert h.until(lambda: heard.saved)
    assert lib.ids("goal")[-2:] == [now[2], now[0]] and heard.notes == []


def test_a_goal_drop_replayed_after_a_crash_goes_to_goals_end_as_it_is_then(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal, now = lib.ids("goal"), lib.ids("now")
    holder = LockHolder(lib.db)
    w.move([now[0]], "goal", end=True)
    assert h.until(lambda: journalled(lib.language) == [("move", [now[0]])])
    assert journal(lib.language)["pending"][0]["end"] is True
    w._abandon()                                        # the crash
    holder.release()
    lib.store.move([now[3]], "goal", after_id=goal[-1])     # Goal's end moved before the next start
    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: journal(lib.language) is None)
    assert h.until(lambda: lib.ids("goal")[-2:] == [now[3], now[0]])
    assert heard2.notes == []


def test_a_goal_end_that_moves_between_the_read_and_the_write_is_read_again(stub_writer):
    """(The store's ValueError) The end left Goal between the writer reading it and writing: Goal's end as it is then,
    with no "spot changed" note."""
    w, heard, store, _opener = stub_writer()
    ends = [[1, 2, 3], [1, 2]]
    store.ids = lambda tier: ends.pop(0) if ends else [1, 2]
    store.fail["move"] = ValueError("the anchor is not in that tier")
    w.move([9], "goal", end=True)
    assert h.until(lambda: heard.saved)
    assert [c[4] for c in store.calls] == [3, 2] and heard.notes == []


def test_the_numbers_follow_a_goal_drop_to_goals_end_and_again_if_the_end_moved(stub_writer):
    numbers = Recorder()
    w, heard, store, _opener = stub_writer(numbers=numbers)
    store.ids = lambda tier: [4, 6]
    w.move([9], "goal", end=True)
    assert h.until(lambda: heard.saved)
    assert numbers.moves == [([9], "goal", None, 6)] and numbers.resyncs == 0
    ends = [[4, 6], [4]]
    store.ids = lambda tier: ends.pop(0) if ends else [4]
    store.fail["move"] = ValueError("the anchor is not in that tier")
    w.move([8], "goal", end=True)
    assert h.until(lambda: len(heard.saved) == 2)
    assert numbers.moves[-1] == ([8], "goal", None, 6) and numbers.resyncs == 1   # the end it landed after: 4


def _learning(lib, item_id):
    row = lib.store.item(item_id)
    return row["in_learning_order"], row["pinned"]


def test_finished_with_its_cards_kept_moves_it_to_finished_and_leaves_its_cards(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[0]])
    w.set_finished([now[0]], keep_cards=True, label="finished")
    assert h.until(lambda: heard.saved)
    assert lib.store.place_of(now[0])[0] == "graduated"
    assert _learning(lib, now[0])[0] == 1 and _learning(lib, now[0])[1] is not None
    assert heard.saved[0][0].kind == "finish" and heard.saved[0][1] == "finished"


def test_taking_a_finished_items_new_cards_out_ends_its_place_in_the_learning_order_and_undoes(lib, make_writer):
    """The Finished toast's *Take its new cards out*, after the drop already finished it: only its cards' choice is
    written — and its Undo puts them back and says so (never *Can't undo*)."""
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[1]])
    w.set_tier([now[1]], "graduated")                    # the drop on the Finished well
    w.set_finished([now[1]], keep_cards=False)           # then the toast's choice
    assert h.until(lambda: len(heard.saved) == 2)
    assert lib.store.place_of(now[1])[0] == "graduated" and _learning(lib, now[1]) == (0, None)
    w.undo(heard.saved[1][0], label="cards back")
    assert h.until(lambda: heard.undone)
    assert heard.notes == [] and heard.undone[0][1] == "cards back"
    assert _learning(lib, now[1])[0] == 1 and _learning(lib, now[1])[1] is not None
    assert lib.store.place_of(now[1])[0] == "graduated"


def test_finished_with_its_cards_taken_out_in_one_command_undoes_whole(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    w.set_finished([now[2]], keep_cards=False)
    assert h.until(lambda: heard.saved)
    assert lib.store.place_of(now[2])[0] == "graduated" and _learning(lib, now[2])[0] == 0
    w.undo()
    assert h.until(lambda: heard.undone)
    assert heard.notes == [] and lib.store.place_of(now[2])[0] in ("now", "soon") and _learning(lib, now[2])[0] == 1


def test_undoing_cards_taken_out_that_were_put_back_meanwhile_says_cant_undo(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[1]])
    w.set_tier([now[1]], "graduated")
    w.set_finished([now[1]], keep_cards=False)
    assert h.until(lambda: len(heard.saved) == 2)
    lib.store.undo(heard.saved[1][0])                   # another window put its cards back already
    version = lib.store.versions()["state_version"]
    w.undo(heard.saved[1][0])
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]] and heard.undone == []
    assert lib.store.versions()["state_version"] == version          # nothing written


def test_undoing_cards_taken_out_with_one_of_its_values_changed_since_puts_the_rest_back(lib, make_writer):
    """The value check: the pin someone set again stays; the learning order comes back — an undo, never *Can't undo*."""
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[1]])
    w.set_tier([now[1]], "graduated")
    w.set_finished([now[1]], keep_cards=False)
    assert h.until(lambda: len(heard.saved) == 2)
    lib.store.pin([now[1]])                             # pinned again meanwhile
    pinned = _learning(lib, now[1])[1]
    w.undo(heard.saved[1][0])
    assert h.until(lambda: heard.undone)
    assert heard.notes == [] and _learning(lib, now[1]) == (1, pinned)


def test_a_finish_given_while_the_store_is_busy_is_journalled_with_its_cards_choice(lib, make_writer,
                                                                                   short_lock_wait):
    w, heard = make_writer()
    now = lib.ids("now")
    holder = LockHolder(lib.db)
    try:
        w.set_finished([now[0]], keep_cards=False)
        assert h.until(lambda: journalled(lib.language) == [("finish", [now[0]])])
        assert journal(lib.language)["pending"][0]["keep_cards"] is False
    finally:
        holder.release()
    assert h.until(lambda: heard.saved)
    assert _learning(lib, now[0])[0] == 0 and journal(lib.language) is None


def test_a_finish_replayed_after_a_crash_keeps_its_cards_choice(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    now = lib.ids("now")
    holder = LockHolder(lib.db)
    w.set_finished([now[0]], keep_cards=False)
    assert h.until(lambda: journalled(lib.language) == [("finish", [now[0]])])
    w._abandon()
    holder.release()
    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: journal(lib.language) is None)
    assert h.until(lambda: lib.store.place_of(now[0])[0] == "graduated")
    assert _learning(lib, now[0])[0] == 0 and heard2.notes == []


# an Explorer drop ----------------------------------------------------------------------------------------------- #
_DROPPED = {"ja": "ドロップ_第1話.txt", "zh": "拖放_第1集.txt"}


def _outside_file(folder, language, extra=""):
    """A real text file from tests/Test Resources, outside the library (as Windows Explorer drags it in)."""
    with open(os.path.join(h.RESOURCES, language, h.LIBRARY[language][0]), encoding="utf-8") as f:
        text = f.read()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, _DROPPED[language])
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + extra)
    return path


def _in_folder(lib, folder):
    base = os.path.splitext(_DROPPED[lib.language])[0]
    where = os.path.join(lib.data_dir, folder)
    return sorted(n for n in os.listdir(where) if n.startswith(base)) if os.path.isdir(where) else []


def test_an_explorer_drop_copies_the_file_into_the_tiers_folder_and_places_it_at_the_drop(lib, make_writer,
                                                                                          tmp_path):
    w, heard = make_writer()
    now = lib.ids("now")
    src = _outside_file(tmp_path / "Explorer", lib.language)
    w.insert_at([src], "now", before_id=now[1], label="added")
    assert h.until(lambda: heard.saved)
    change, label = heard.saved[0]
    assert label == "added" and len(change.added) == 1 and heard.notes == []
    new = change.added[0]
    assert lib.ids("now")[:3] == [now[0], new, now[1]]
    assert lib.store.item(new)["rel_path"] == f"HighPriority/{_DROPPED[lib.language]}"
    assert _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]] and os.path.isfile(src)
    assert journal(lib.language) is None                # never journalled


def test_an_explorer_drop_after_a_soon_row_lands_in_soons_folder_after_it(lib, make_writer, tmp_path):
    w, heard = make_writer()
    soon = lib.ids("soon")
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "soon", after_id=soon[2])
    assert h.until(lambda: heard.saved)
    new = heard.saved[0][0].added[0]
    assert lib.ids("soon")[3] == new and lib.store.item(new)["rel_path"].startswith("LowPriority/")


def test_an_explorer_drop_at_no_row_goes_to_the_top_of_its_tier_without_a_note(lib, make_writer, tmp_path):
    w, heard = make_writer()
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now")
    assert h.until(lambda: heard.saved)
    assert lib.ids("now")[0] == heard.saved[0][0].added[0] and heard.notes == []


def test_an_explorer_drop_never_copies_over_a_file(lib, make_writer, tmp_path):
    """An identical file already there is that file (left where it is, reported); another of the same name comes in
    as `name (2)` — never over the one the learner has."""
    w, heard = make_writer()
    now = lib.ids("now")
    same = _outside_file(tmp_path / "Explorer", lib.language)
    w.insert_at([same], "now", before_id=now[0])
    assert h.until(lambda: heard.saved)
    first = heard.saved[0][0].added[0]
    rereads = heard.rereads
    w.insert_at([same], "now", before_id=now[0])         # the same file again: already in the library (AD-9)
    assert h.until(lambda: heard.rereads > rereads)      # the window drops its ghost row …
    assert len(heard.saved) == 1 and list(w._undo) == [heard.saved[0][0]]  # … and nothing joins the Undo stack
    assert lib.ids("now").count(first) == 1 and _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]]
    differing = _outside_file(tmp_path / "Explorer2", lib.language, extra="\n")
    w.insert_at([differing], "now", before_id=now[0])
    assert h.until(lambda: len(heard.saved) == 2)
    base, ext = os.path.splitext(_DROPPED[lib.language])
    assert _in_folder(lib, "HighPriority") == sorted([_DROPPED[lib.language], f"{base} (2){ext}"])
    assert lib.store.item(heard.saved[1][0].added[0])["rel_path"] == f"HighPriority/{base} (2){ext}"


def test_an_explorer_drop_of_a_file_in_the_library_folder_places_it_without_a_copy(lib, make_writer):
    w, heard = make_writer()
    inside = os.path.join(lib.data_dir, "LowPriority", _DROPPED[lib.language])
    with open(os.path.join(h.RESOURCES, lib.language, h.LIBRARY[lib.language][0]), encoding="utf-8") as f:
        text = f.read()
    with open(inside, "w", encoding="utf-8") as f:
        f.write(text)
    soon = lib.ids("soon")
    w.insert_at([inside], "soon", before_id=soon[0])
    assert h.until(lambda: lib.ids("soon")[0] not in soon)
    new = lib.ids("soon")[0]
    assert lib.store.item(new)["rel_path"] == f"LowPriority/{_DROPPED[lib.language]}"
    assert _in_folder(lib, "LowPriority") == [_DROPPED[lib.language]]
    # (AD-9 / AD-10) nothing it copied, so nothing its Undo could take back for good: removing the row of a file
    # in a tier's folder would come undone at the next disk sync — the drop never joins the Undo stack
    assert h.until(lambda: heard.rereads) and heard.saved == [] and not w.can_undo()


def test_AD10_undoing_a_drop_takes_out_only_the_rows_of_the_files_it_copied(lib, make_writer, tmp_path):
    """A drop of an outside file and a file already in a tier's folder: its Undo trashes the copy and takes its row
    out; the learner's own file keeps its file and its row (a sync would only add it back)."""
    w, heard = make_writer()
    inside = os.path.join(lib.data_dir, "LowPriority", "既に_" + _DROPPED[lib.language])
    with open(os.path.join(h.RESOURCES, lib.language, h.LIBRARY[lib.language][0]), encoding="utf-8") as f:
        text = f.read()
    with open(inside, "w", encoding="utf-8") as f:
        f.write(text)
    now = lib.ids("now")
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language), inside], "now", before_id=now[0])
    assert h.until(lambda: heard.saved)
    added = heard.saved[0][0].added
    assert len(added) == 2
    copied = [i for i in added if lib.store.item(i)["rel_path"].startswith("HighPriority/")]
    kept = [i for i in added if i not in copied]
    w.undo()
    assert h.until(lambda: heard.undone)
    assert lib.store.item(copied[0]) is None and _in_folder(lib, "HighPriority") == []
    assert lib.store.item(kept[0]) is not None and os.path.isfile(inside) and heard.notes == []


def test_an_explorer_drop_whose_anchor_went_meanwhile_lands_beside_the_nearest_neighbour(lib, make_writer, tmp_path):
    w, heard = make_writer()
    soon = lib.ids("soon")
    w.hold()
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "soon", before_id=soon[3],
                near=[(soon[3], "before"), (soon[4], "before"), (soon[2], "after")])
    lib.store.move([soon[3], soon[4]], "goal")          # the anchor and its first neighbour leave Soon meanwhile
    w.release()
    assert h.until(lambda: heard.saved)
    new = heard.saved[0][0].added[0]
    order = lib.ids("soon")
    assert order.index(new) == order.index(soon[2]) + 1 and heard.notes == [WORDS["nearest"]]


def test_an_explorer_drop_with_no_neighbour_left_goes_to_the_top_of_the_tier(lib, make_writer, tmp_path):
    w, heard = make_writer()
    soon = lib.ids("soon")
    w.hold()
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "soon", after_id=soon[3],
                near=[(soon[3], "after")])
    lib.store.move([soon[3]], "goal")
    w.release()
    assert h.until(lambda: heard.saved)
    assert lib.ids("soon")[0] == heard.saved[0][0].added[0] and heard.notes == [WORDS["top"]]


def test_an_explorer_drop_whose_anchor_vanishes_at_the_write_tries_the_next_neighbour(stub_writer, tmp_path,
                                                                                      monkeypatch):
    """(StoreConflict) The anchor was there at the look and gone at the write: the next neighbour, with the note."""
    w, heard, store, _opener = stub_writer()
    store.data_dir = str(tmp_path / "data")
    store.item = lambda i: {"tier": "now"}
    tried = []

    def insert_at(files, anchor, before=True, started_at=None):
        tried.append((anchor, before))
        if anchor == 5:
            raise ls.StoreConflict("the anchor item is gone")
        return ls.Change("insert_at", 1, 1)
    store.insert_at = insert_at
    w.insert_at([_outside_file(tmp_path / "Explorer", "ja")], "now", before_id=5, near=[(5, "before"), (6, "after")])
    assert h.until(lambda: heard.saved)
    assert tried == [(5, True), (6, False)] and heard.notes == [WORDS["nearest"]]


def test_an_explorer_drops_undo_sends_its_copy_to_the_trash_and_takes_its_row_out(lib, make_writer, tmp_path):
    w, heard = make_writer()
    now = lib.ids("now")
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now", before_id=now[0])
    assert h.until(lambda: heard.saved)
    new = heard.saved[0][0].added[0]
    w.undo()
    assert h.until(lambda: heard.undone)
    assert lib.ids("now") == now and lib.store.item(new) is None and heard.notes == []
    assert _in_folder(lib, "HighPriority") == []
    assert any(n.startswith(os.path.splitext(_DROPPED[lib.language])[0])
               for n in os.listdir(os.path.join(lib.data_dir, ".trash")))


def test_an_explorer_drops_undo_the_store_refuses_puts_its_file_back(lib, make_writer, tmp_path, monkeypatch):
    w, heard = make_writer()
    now = lib.ids("now")
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now", before_id=now[0])
    assert h.until(lambda: heard.saved)

    def refuse(self, change, trashed_paths=None, rel_paths=None):
        raise ls.StoreConflict("an item changed since its file was moved; nothing was undone")
    monkeypatch.setattr(ls.Store, "undo", refuse)
    w.undo()
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]] and _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]]


def test_an_explorer_drop_the_store_refuses_sends_its_copy_to_the_trash(lib, make_writer, tmp_path, monkeypatch):
    """A drop let go (a raw error at the write) leaves no stray copy for a disk sync to place somewhere else."""
    def refuse(self, *a, **kw):
        raise RuntimeError("disk I/O error")
    monkeypatch.setattr(ls.Store, "insert_at", refuse)
    w, heard = make_writer()
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now", before_id=lib.ids("now")[0])
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["failed"].format(error="disk I/O error")] and heard.saved == []
    assert _in_folder(lib, "HighPriority") == []


def test_an_explorer_drop_on_a_busy_store_is_copied_once_and_lands_when_freed(lib, make_writer, tmp_path,
                                                                              short_lock_wait):
    w, heard = make_writer()
    now = lib.ids("now")
    holder = LockHolder(lib.db)
    try:
        w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now", before_id=now[0])
        assert h.until(lambda: w.attempts >= 2)
        assert journal(lib.language) is None            # never journalled
    finally:
        holder.release()
    assert h.until(lambda: heard.saved)
    assert _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]]
    w.undo()                                            # (X06) the copy made at the first try is still its own
    assert h.until(lambda: heard.undone)
    assert _in_folder(lib, "HighPriority") == []


def test_an_explorer_drop_cant_go_to_finished(stub_writer):
    w, heard, store, _opener = stub_writer()
    store.data_dir = "unused"
    w.insert_at(["x.srt"], "graduated")
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["failed"].format(error="files can't be dropped into 'graduated'")]


def _slow_copy(monkeypatch):
    """Each drop's copy waits for the test's gate (a big file, a slow USB stick or share). -> (started, gate)."""
    real = M._copy_whole
    started, gate = threading.Event(), threading.Event()

    def slow(src, dest):
        started.set()
        assert gate.wait(10)
        return real(src, dest)
    monkeypatch.setattr(M, "_copy_whole", slow)
    return started, gate


def test_R2B1_a_move_given_behind_a_slow_copy_is_saved_before_the_copy_ends(lib, make_writer, tmp_path, monkeypatch):
    """G1: a move is saved within moments, whatever an Explorer drop is copying; the drop lands once its file is in."""
    started, gate = _slow_copy(monkeypatch)
    w, heard = make_writer()
    goal, now = lib.ids("goal"), lib.ids("now")
    try:
        w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now", before_id=now[0], label="drop")
        assert started.wait(5)
        w.move([goal[5]], "goal", before_id=goal[0], label="move")
        assert h.until(lambda: heard.saved)                       # saved while the copy still runs
        assert [label for _c, label in heard.saved] == ["move"] and lib.ids("goal")[0] == goal[5]
        assert w.pending() == 1                                   # the drop: still copying, counted for the quit
    finally:
        gate.set()
    assert h.until(lambda: len(heard.saved) == 2)
    assert heard.saved[1][1] == "drop" and lib.ids("now")[0] == heard.saved[1][0].added[0]


def test_R2B1_a_move_behind_a_slow_copy_on_a_busy_store_is_journalled_before_the_copy_ends(
        lib, make_writer, tmp_path, monkeypatch, short_lock_wait):
    started, gate = _slow_copy(monkeypatch)
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now")
        assert started.wait(5)
        w.move([goal[5]], "goal")
        assert h.until(lambda: journalled(lib.language) == [("move", [goal[5]])])
    finally:
        gate.set()
        holder.release()
    assert h.until(lambda: len(heard.saved) == 2)


def test_AD2_a_drop_on_a_busy_store_at_quit_leaves_its_copy_whole_for_the_next_disk_sync(lib, make_writer, tmp_path,
                                                                                          short_lock_wait):
    """The quit runs out of time while the store is busy: the drop's file is already whole in the tier's folder, so
    the next start's disk sync takes it in — never lost, never half a file, no stray `.part`."""
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[4]], "goal")                       # a move waiting ahead of it
        w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now")
        assert h.until(lambda: _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]])
        assert not w.finish(time.monotonic() + 0.5)     # the quit: the store never freed
        assert journalled(lib.language) == [("move", [goal[4]])]
    finally:
        holder.release()
    folder = os.path.join(lib.data_dir, "HighPriority")
    assert _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]]
    assert not [n for n in os.listdir(folder) if n.endswith(M.PART)]
    with open(os.path.join(folder, _DROPPED[lib.language]), encoding="utf-8") as f, \
            open(os.path.join(tmp_path, "Explorer", _DROPPED[lib.language]), encoding="utf-8") as g:
        assert f.read() == g.read()
    if w._thread is not None:                           # the quit's process ends: its worker's last try (it may take
        w._thread.join(5)                               # the lock the holder just freed) is over before the next start
    lib.store.sync_disk()                               # the next start
    rel = f"HighPriority/{_DROPPED[lib.language]}"
    assert any(lib.store.item(i)["rel_path"] == rel for t in ("now", "soon", "goal", "arrivals") for i in lib.ids(t))
    w2, _heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: journal(lib.language) is None)
    assert lib.ids("goal")[0] == goal[4]


def test_AD2_a_drop_given_during_a_drag_is_copied_at_once_and_lands_after_the_release(lib, make_writer, tmp_path):
    w, heard = make_writer()
    w.hold()
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now")
    assert h.until(lambda: _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]])
    time.sleep(0.1)
    assert heard.saved == [] and w.pending() == 1
    w.release()
    assert h.until(lambda: heard.saved)


def test_AD3_a_copy_that_fails_part_way_leaves_no_file_and_no_part(lib, make_writer, tmp_path, monkeypatch):
    import shutil

    def broken(src, dst, *a, **kw):
        dst.write(src.read(64))                         # half a file …
        raise OSError(28, "No space left on device")    # … then the disk is full
    monkeypatch.setattr(shutil, "copyfileobj", broken)
    w, heard = make_writer()
    now = lib.ids("now")
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now", before_id=now[0])
    assert h.until(lambda: heard.notes)
    assert heard.notes[0].startswith(WORDS["failed"].split("{")[0]) and heard.saved == []
    assert _in_folder(lib, "HighPriority") == []        # neither the half file nor its part
    assert lib.ids("now") == now


def test_a_drop_whose_second_copy_fails_sends_its_first_copy_to_the_trash(lib, make_writer, tmp_path, monkeypatch):
    """(Mutant Q17) Two files dropped; the second can't be copied: the drop is let go whole — the first file's copy goes
    to the trash, never left in the tier's folder for a sync to place where nobody dropped it."""
    real = M._copy_whole
    made = []

    def second_fails(src, dest):
        if made:
            raise OSError(28, "No space left on device")
        made.append(real(src, dest))
        return made[-1]
    monkeypatch.setattr(M, "_copy_whole", second_fails)
    w, heard = make_writer()
    first = _outside_file(tmp_path / "Explorer", lib.language)
    second = os.path.join(str(tmp_path / "Explorer2"), "第2話.txt")
    os.makedirs(os.path.dirname(second))
    with open(second, "w", encoding="utf-8") as f:
        f.write("二つ目のファイル。\n")
    now = lib.ids("now")
    w.insert_at([first, second], "now", before_id=now[0])
    assert h.until(lambda: heard.notes)
    assert heard.saved == [] and len(made) == 1 and not os.path.exists(made[0])
    assert _in_folder(lib, "HighPriority") == [] and lib.ids("now") == now


def test_AD3_a_whole_copy_carries_the_files_bytes_and_leaves_no_part(lib, make_writer, tmp_path):
    w, heard = make_writer()
    src = _outside_file(tmp_path / "Explorer", lib.language)
    w.insert_at([src], "now")
    assert h.until(lambda: heard.saved)
    folder = os.path.join(lib.data_dir, "HighPriority")
    with open(src, "rb") as a, open(os.path.join(folder, _DROPPED[lib.language]), "rb") as b:
        assert a.read() == b.read()
    assert not [n for n in os.listdir(folder) if n.endswith(M.PART)]


def test_AD12_a_file_another_program_writes_under_the_same_name_meanwhile_is_never_written_over(
        lib, make_writer, tmp_path, monkeypatch):
    """The name was free when looked at; another program (an importer, the YouTube module) writes it before the copy
    is renamed: the copy steps to `name (2)`, the other file is left as it was."""
    real = ls._rename_no_overwrite
    folder = os.path.join(lib.data_dir, "HighPriority")
    theirs = os.path.join(folder, _DROPPED[lib.language])

    def racing(src, dst):
        if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(theirs)) \
                and not os.path.exists(theirs):
            with open(theirs, "w", encoding="utf-8") as f:
                f.write("別のプログラムのファイル")
        return real(src, dst)
    monkeypatch.setattr(ls, "_rename_no_overwrite", racing)
    w, heard = make_writer()
    w.insert_at([_outside_file(tmp_path / "Explorer", lib.language)], "now")
    assert h.until(lambda: heard.saved)
    base, ext = os.path.splitext(_DROPPED[lib.language])
    with open(theirs, encoding="utf-8") as f:
        assert f.read() == "別のプログラムのファイル"
    assert lib.store.item(heard.saved[0][0].added[0])["rel_path"] == f"HighPriority/{base} (2){ext}"
    assert not [n for n in os.listdir(folder) if n.endswith(M.PART)]


@pytest.mark.parametrize("named", [True, False])
def test_AD4_only_content_files_are_taken_and_the_rest_are_named_in_a_note(lib, make_writer, tmp_path, named):
    """Explorer hands over whatever was dragged: a shortcut, a video, a picture, a Word file, a folder. Only what the
    disk sync and Add Files take (text and subtitles) comes in; the rest is named, never silently dropped."""
    # the window's own word (strings.MOVE_WORDS has it), and a writer given words without it (the key is optional)
    words = dict(WORDS) if named else {k: v for k, v in WORDS.items() if k != "not_content"}
    w, heard = make_writer(words=words)
    src = tmp_path / "Explorer"
    keep = _outside_file(src, lib.language)
    others = []
    for name in ("番組.lnk", "第1話.mkv", "表紙.jpg", "メモ.docx"):
        (src / name).write_bytes(b"\x00\x01binary")
        others.append(str(src / name))
    (src / "フォルダ").mkdir()
    others.append(str(src / "フォルダ"))
    w.insert_at(others[:2] + [keep] + others[2:], "now")
    assert h.until(lambda: heard.saved and heard.notes)
    names = "番組.lnk, 第1話.mkv, 表紙.jpg, メモ.docx, フォルダ"
    expected = words["not_content"].format(names=names) if named else WORDS["failed"].format(error=names)
    assert heard.notes == [expected]
    assert len(heard.saved[0][0].added) == 1
    assert _in_folder(lib, "HighPriority") == [_DROPPED[lib.language]]
    assert not set(os.listdir(os.path.join(lib.data_dir, "HighPriority"))) & {os.path.basename(p) for p in others}


def test_AD4_a_drop_of_nothing_but_other_files_places_nothing_and_says_so(lib, make_writer, tmp_path):
    w, heard = make_writer()
    os.makedirs(tmp_path / "Explorer")
    (tmp_path / "Explorer" / "第1話.mkv").write_bytes(b"\x00video")
    now = lib.ids("now")
    w.insert_at([str(tmp_path / "Explorer" / "第1話.mkv")], "now")
    assert h.until(lambda: heard.notes and heard.rereads)
    assert heard.notes == [WORDS["not_content"].format(names="第1話.mkv")] and heard.saved == []
    assert lib.ids("now") == now and not os.path.exists(os.path.join(lib.data_dir, "HighPriority", "第1話.mkv"))


def test_AD11_a_file_dragged_out_of_the_trash_is_copied_in_never_placed_where_the_purge_deletes_it(
        lib, make_writer, tmp_path):
    w, heard = make_writer()
    trash = os.path.join(lib.data_dir, ".trash")
    os.makedirs(trash, exist_ok=True)
    gone = os.path.join(trash, _DROPPED[lib.language])
    with open(_outside_file(tmp_path / "Explorer", lib.language), encoding="utf-8") as f:
        text = f.read()
    with open(gone, "w", encoding="utf-8") as f:
        f.write(text)
    w.insert_at([gone], "now")
    assert h.until(lambda: heard.saved)
    new = heard.saved[0][0].added[0]
    assert lib.store.item(new)["rel_path"] == f"HighPriority/{_DROPPED[lib.language]}"
    assert os.path.isfile(gone)                         # the trash's copy is left as it is
    w.undo()                                            # a copy it made: its Undo takes it back
    assert h.until(lambda: heard.undone)
    assert lib.store.item(new) is None and _in_folder(lib, "HighPriority") == []


# AD-6: the Finished toast's Undo takes its cards' choice back too ----------------------------------------------- #
def test_AD6_the_drops_undo_puts_it_back_with_the_cards_its_follow_up_took_out(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[1]])
    pinned = _learning(lib, now[1])[1]
    w.set_tier([now[1]], "graduated", label="finished")             # the drop on the Finished well
    assert h.until(lambda: heard.saved)
    drop = heard.saved[0][0]
    w.set_finished([now[1]], keep_cards=False, follows=drop)        # the toast's *Take its new cards out*
    assert h.until(lambda: len(heard.saved) == 2)
    assert _learning(lib, now[1]) == (0, None)
    w.undo(drop, label="back")                                      # the toast's Undo
    assert h.until(lambda: heard.undone)
    assert heard.notes == [] and heard.undone == [(drop, "back")]
    assert lib.store.place_of(now[1])[0] in ("now", "soon") and _learning(lib, now[1]) == (1, pinned)
    assert not w.can_undo()                                         # both changes left the Undo stack


def test_AD6_ctrl_z_still_takes_the_cards_choice_back_first_then_the_drop(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[1]])
    pinned = _learning(lib, now[1])[1]
    w.set_tier([now[1]], "graduated")
    assert h.until(lambda: heard.saved)
    w.set_finished([now[1]], keep_cards=False, follows=heard.saved[0][0])
    assert h.until(lambda: len(heard.saved) == 2)
    w.undo()                                                        # Ctrl+Z: the newest, the cards' choice
    assert h.until(lambda: len(heard.undone) == 1)
    assert lib.store.place_of(now[1])[0] == "graduated" and _learning(lib, now[1]) == (1, pinned)
    w.undo()                                                        # Ctrl+Z again: the drop
    assert h.until(lambda: len(heard.undone) == 2)
    assert lib.store.place_of(now[1])[0] in ("now", "soon") and _learning(lib, now[1]) == (1, pinned)
    assert heard.notes == []


def test_AD6_the_drops_undo_after_the_cards_were_put_back_meanwhile_still_undoes_the_drop(lib, make_writer):
    w, heard = make_writer()
    now = lib.ids("now")
    w.set_tier([now[1]], "graduated")
    assert h.until(lambda: heard.saved)
    drop = heard.saved[0][0]
    w.set_finished([now[1]], keep_cards=False, follows=drop)
    assert h.until(lambda: len(heard.saved) == 2)
    lib.store.undo(heard.saved[1][0])                               # another window put its cards back
    w.undo(drop)
    assert h.until(lambda: heard.undone)
    assert heard.notes == [] and lib.store.place_of(now[1])[0] in ("now", "soon")
    assert _learning(lib, now[1])[0] == 1


def test_AD6_a_drop_whose_undo_is_refused_leaves_its_cards_choice_on_the_undo_stack(lib, make_writer):
    """Round 2 (the Haiku lenses): the drop moved on in another program, so its Undo is refused — the cards' choice made
    after it was never undone, so it stays on the stack and Ctrl+Z can still put the cards back."""
    w, heard = make_writer()
    now = lib.ids("now")
    lib.store.pin([now[1]])
    pinned = _learning(lib, now[1])[1]
    w.set_tier([now[1]], "graduated")
    assert h.until(lambda: heard.saved)
    drop = heard.saved[0][0]
    w.set_finished([now[1]], keep_cards=False, follows=drop)
    assert h.until(lambda: len(heard.saved) == 2)
    lib.store.set_tier([now[1]], "goal")                            # another program moves it on
    w.undo(drop)                                                    # the toast's Undo: refused
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]] and heard.undone == []
    assert _learning(lib, now[1]) == (0, None)                      # the choice was left as it was
    assert w.can_undo()                                             # and is still there to take back
    w.undo()
    assert h.until(lambda: heard.undone)
    assert _learning(lib, now[1]) == (1, pinned)


# AD-15: a finish undo that restored nothing says so ------------------------------------------------------------- #
def test_AD15_a_finish_undo_whose_rows_all_changed_after_the_check_says_cant_undo(lib, make_writer, monkeypatch):
    """The rows changed between `undo_check` and the undo (another program's write in between): the store skips them
    all — the toast says *Can't undo*, never *undone*."""
    w, heard = make_writer()
    now = lib.ids("now")
    w.set_finished([now[2]], keep_cards=True)
    assert h.until(lambda: heard.saved)
    real = ls.Store.undo_check
    monkeypatch.setattr(ls.Store, "undo_check", lambda self, change: (real(self, change)[0] or
                                                                       [it["id"] for it in change.items], []))
    lib.store.move([now[2]], "goal")                                # another program, after the look
    w.undo()
    assert h.until(lambda: heard.notes)
    assert heard.notes == [WORDS["cant_undo"]] and heard.undone == []
    assert lib.store.place_of(now[2])[0] == "goal"


def test_AD15_the_store_skip_count_is_read_from_its_notes():
    out = ls.Change("undo", 1, 2)
    out.notes = ["2 items changed since and were left as they are"]
    finish = ls.Change("finish", 1, 1)
    finish.items = [{"id": 1}]
    finish.status = [(1, "pinned", "x", None)]
    assert M._skips(out) == 2 and M._refused(finish, out)
    out.notes = ["1 item changed since and was left as it is"]
    assert M._skips(out) == 1 and not M._refused(finish, out)       # its value came back
    out.items = [{"id": 1}]
    out.notes = ["1 item changed since and was left as it is"]
    assert not M._refused(finish, out)                              # its row came back


# the verdict, one opener ---------------------------------------------------------------------------------------- #
def test_plan_check_names_the_reason_only_when_a_generate_must_come_first(lib, tmp_path, monkeypatch):
    from app import analyzer, settings_manager
    path = str(tmp_path / "plan.json.gz")
    rels = [e["physical_path"] for t in ("now", "soon", "goal") for _i, e, _a in lib.store.ordered(t)]
    write_plan(path, rels, ["now"] * len(rels), language="zh" if lib.language == "ja" else "ja", n_words=50)
    plan = plan_engine.load(path)
    check = M.plan_check(lib.language, settings_manager.load_settings())
    assert check(plan, lib.store) == "language"         # the real verdict, on the library's own parts
    seen, answer = {}, []

    def verdict(plan_, language, engine, stamp, parts, epoch):
        seen.update(language=language, engine=engine, parts=parts, epoch=epoch)
        return answer[-1]
    monkeypatch.setattr(plan_engine, "check", verdict)
    for given, expected in ((("generate-first", "files"), "files"), (("replan-now", ("known",)), None),
                            (("stand-aside", "coverage"), None), (None, None)):
        answer.append(given)
        assert check(plan, lib.store) == expected, given
    assert seen["language"] == lib.language and seen["engine"] == analyzer.engine_id()
    assert seen["epoch"] == lib.store.versions()["epoch"] and seen["parts"] is not None


def test_plan_check_reads_the_settings_at_each_check(lib, monkeypatch):
    from app import run_args
    calls = []
    real = run_args.analyzer_args

    def spy(values, language=None, headless=False):
        calls.append(dict(values))
        return real(values, language, headless)
    monkeypatch.setattr(run_args, "analyzer_args", spy)
    monkeypatch.setattr(plan_engine, "check", lambda *a: None)
    from app import settings_manager
    base = settings_manager.load_settings()
    values = [dict(base, target_language=lib.language, marker=1), dict(base, target_language=lib.language, marker=2)]
    check = M.plan_check(lib.language, lambda: values.pop(0))
    assert check(None, lib.store) is None and check(None, lib.store) is None
    assert [c.get("marker") for c in calls] == [1, 2]


def test_open_library_shares_one_opener_and_resyncs_the_numbers_on_every_move(lib):
    opener, numbers, reader = M.open_library(lib.language, cache_file=None)
    resyncs = []
    numbers.resync = lambda: resyncs.append(1)
    try:
        assert reader.opener is opener and numbers.opener is opener and reader.numbers is numbers
        reader.start()
        assert h.until(lambda: reader.view() is not None and reader.view().rows)
        goal = lib.ids("goal")
        lib.store.move([goal[4]], "goal", before_id=goal[0])    # another program's move
        assert h.until(lambda: resyncs)
        refreshed = []
        reader.refresh = lambda: refreshed.append(1)
        numbers._call_change()                          # a new figure: the reader looks again
        assert refreshed == [1]
    finally:
        reader.stop()
        numbers.close()


def test_a_reader_let_go_is_freed_by_its_count_alone_and_its_numbers_then_refresh_nothing(lib):
    """W3.2 P0 (AD0-2): the numbers held the reader (`on_change` → the reader's refresh) and the reader held the
    numbers: a cycle only Python's collector frees — and the window process once froze the collector after every view,
    so a library a language switch let go (its whole copy, hundreds of thousands of objects at 20,000 files) was
    never freed. The numbers now hold the reader weakly: let go, it is freed at once, collector or not, and a late
    figure from its numbers refreshes nothing."""
    import gc
    import weakref
    opener, numbers, reader = M.open_library(lib.language, cache_file=None)
    reader.start()
    assert h.until(lambda: reader.view() is not None and reader.view().rows)
    reader.stop()
    assert reader._items == {} and reader._works == {}          # the copy let go at the stop, whoever holds it
    assert reader.view() is not None                            # (the last view stays: the window shows it meanwhile)
    gone = weakref.ref(reader)
    was = gc.isenabled()
    gc.disable()                                                # no collector: only a cycle-free reader goes
    try:
        del reader
        assert gone() is None
    finally:
        if was:
            gc.enable()
    numbers._call_change()                                      # nothing left to refresh: no error
    numbers.close()
    opener.close()


def test_a_stopped_reader_never_starts_again(lib):
    """W3.2 P0 (AD0-4): a reader a second language switch stopped before the window got to it is never started — no
    cache read, no store handle, no view published for a library that is no longer open."""
    _opener, numbers, reader = M.open_library(lib.language, cache_file=None)
    reader.stop()
    reader.start()
    assert reader._thread is None and reader.view() is None
    numbers.close()


# --- W3.3 P6: Settings' two store lines through the writer ---------------------------------------------------------- #
def _meta(lib, key):
    return lib.store.meta().get(key)


def test_settings_store_lines_are_written_by_the_writer_and_never_go_on_the_undo_stack(lib, make_writer):
    # *Soon starts after N files* moves the rows that cross it (the store's own rule); *Mine automatically: the top N*
    # sets the mine line. A Ctrl+Z in Current must never take a Settings value back: the row is where it changes.
    w, heard = make_writer()
    now = lib.ids("now")
    assert len(now) >= 2
    assert w.set_options(soon_line=len(now) - 1) is not None
    assert h.until(lambda: _meta(lib, "soon_line") == len(now) - 1)
    assert h.until(lambda: lib.ids("now") == now[:-1])                    # the last NOW file is Soon's first now
    assert lib.ids("soon")[0] == now[-1]
    assert w.set_options(mine_line=7) is not None
    assert h.until(lambda: _meta(lib, "mine_line") == 7)
    assert heard.saved == [] and not w.can_undo()
    assert h.until(lambda: heard.rereads >= 2)                           # the reader looks again after each
    assert w.pending() == 0 and journal(lib.language) is None


def test_settings_store_lines_with_nothing_to_set_or_a_negative_line_write_nothing(lib, make_writer):
    w, heard = make_writer()
    before = (_meta(lib, "soon_line"), _meta(lib, "mine_line"))
    assert w.set_options() is None
    with pytest.raises(ValueError):
        w.set_options(soon_line=-1)
    with pytest.raises(ValueError):
        w.set_options(mine_line=-3)
    assert w.pending() == 0
    assert (_meta(lib, "soon_line"), _meta(lib, "mine_line")) == before
    w.set_options(mine_line=_meta(lib, "mine_line") or 20)                # (written or the same: the reader looks again)
    assert h.until(lambda: heard.rereads >= 1)
    assert heard.notes == []


def test_a_store_line_set_while_the_store_is_busy_is_journalled_and_replayed_after_a_crash(lib, make_writer,
                                                                                          short_lock_wait):
    # A busy store (a sync holding it) queues the Settings change with the moves; a crash before it lands leaves it in
    # the journal and the next start writes it.
    w, heard = make_writer()
    holder = LockHolder(lib.db)
    w.set_options(mine_line=5)
    assert h.until(lambda: journalled(lib.language) == [("set_options", [])])
    assert journal(lib.language)["pending"][0]["mine_line"] == 5
    w._abandon()
    holder.release()
    assert _meta(lib, "mine_line") != 5
    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: _meta(lib, "mine_line") == 5)
    assert h.until(lambda: journal(lib.language) is None)
    assert heard2.notes == [] and heard2.saved == []


def test_a_store_line_on_a_read_only_store_is_refused_before_it_is_queued(lib, make_writer):
    w, heard = make_writer()
    lib.close()
    ls.mark_damaged(lib.db, "test: a damaged store")
    assert h.until(lambda: not w.can_write(), seconds=M.MODE_RECHECK_S * 3)
    assert w.set_options(soon_line=1) is None and w.pending() == 0


def test_a_move_queued_behind_a_soon_line_that_moved_its_row_survives_a_crash(lib, make_writer):
    # The line moves NOW's last file into Soon; a drag of that file queued behind the line, then a crash
    # right after the line lands: the replay must apply the learner's move, never list it as "changed since".
    heard = Heard()
    kw = heard.kw()
    w = None

    def crash_after_the_line():
        with w._cond:
            w._abandoned = True                         # the crash: the thread stops at its next look
            w._cond.notify_all()
    kw["on_reread"] = crash_after_the_line
    w = M.Writer(lib.opener(), lib.language, journal_file=M.journal_path(lib.language), retry=0.05, words=WORDS, **kw)
    w.start()
    now, goal = lib.ids("now"), lib.ids("goal")
    w.hold()
    w.set_options(soon_line=len(now) - 1)
    w.move([now[-1]], "goal", before_id=goal[0])
    assert h.until(lambda: len(journalled(lib.language)) == 2)
    w.release()
    assert h.until(lambda: _meta(lib, "soon_line") == len(now) - 1)
    assert h.until(lambda: not w._thread.is_alive())
    assert journalled(lib.language) == [("move", [now[-1]])]
    w2, heard2 = make_writer()
    assert w2.replay()
    assert h.until(lambda: lib.ids("goal")[:1] == [now[-1]])
    assert heard2.notes == []
