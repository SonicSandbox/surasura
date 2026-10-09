"""L3.3 of the library store (Library_Store_Spec.md §6.12): closes and checks that touch only what they must.

Why these matter: SQLite checkpoints a WAL database when its last connection closes, and deletes the `-wal`. Connect
opens the store about ten times a job; with Surasura closed every one of those closes was the last, so each ran a
checkpoint outside the store's write lock (the spec allows checkpoints only under it: SQLite 3.39.4's WAL-reset bug)
and the next write paid for a new `-wal` (a receipt's hold up to 62 ms, P2.4's verifier). Now a close never
checkpoints outside the lock, Connect can hold one handle for a job (`held()`), the copy follows Connect's writes on
its own trigger, and the Content Manager's mode check, run twice a drag, reads through the
handle it already has instead of opening a connection each time (charter S19: a check that finds nothing does nothing).
Every test runs for Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT that tests/conftest.py sets.
"""

import hashlib
import json
import os
import sqlite3
import threading
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, roots


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _wal(store_or_path):
    """The `-wal`'s size, or None when there is none."""
    path = (store_or_path if isinstance(store_or_path, str) else store_or_path.db_path) + "-wal"
    return os.path.getsize(path) if os.path.exists(path) else None


def _until(condition, limit=5.0):
    """Poll `condition` until it holds or `limit` seconds pass; its last value."""
    deadline = time.perf_counter() + limit
    while True:
        value = condition()
        if value or time.perf_counter() >= deadline:
            return value
        time.sleep(0.02)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_close_alone_keeps_the_wal_for_window_and_connect_but_a_helper_checkpoints(language):
    """A window's and a connect's close, each the only connection, leaves the `-wal` and the `.db` bytes exactly as
    they were: the checkpoint waits for the helper's run under the write lock. The helper's own close, alone, still
    checkpoints (no `-wal` after), so the same check proves the test can fail. The idle copy trigger is off under the
    suite (SURASURA_NO_IDLE_EXPORT), so nothing else opens the store between the close and the check."""
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    connect = None
    helper = None
    try:
        item_id = window.ids("now")[-1]
        window.move([item_id], "now")                       # a write: it lands in the -wal
        db = window.db_path
        wal_before, db_before = _wal(db), _sha(db)
        assert wal_before, "precondition: the move left a -wal for the close to keep"
        window.close()
        window = None
        assert _wal(db) == wal_before, "a window close, alone, must not checkpoint"
        assert _sha(db) == db_before, "a window close, alone, must not touch the .db bytes"

        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        connect.receipt(item_id, "2026-10-08T10:00:00Z")   # a status write: one more -wal entry
        wal_before, db_before = _wal(db), _sha(db)
        assert wal_before, "precondition: the receipt left a -wal for the close to keep"
        connect.close()
        connect = None
        assert _wal(db) == wal_before, "a connect close, alone, must not checkpoint"
        assert _sha(db) == db_before, "a connect close, alone, must not touch the .db bytes"

        helper = ls.Store(db, language, data_dir, user_files_dir, "helper")
        helper.meta()                                       # a read, so the helper has a connection to close
        assert _wal(db) is not None, "precondition: the -wal is still there before the helper closes"
        helper.close()
        helper = None
        assert _wal(db) is None, "a helper close, alone, checkpoints and removes the -wal"
    finally:
        for store in (window, connect, helper):
            if store is not None:
                store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_helper_close_waits_for_the_write_lock(language):
    """A helper's close takes the write lock: while another thread holds it, the close returns only after the release,
    and the helper, the one that checkpoints, leaves no `-wal` behind. Why: a close that skipped the lock would
    checkpoint outside it (SQLite's WAL-reset bug, §6.12)."""
    window = migrated(language)
    db_path = window.db_path
    data_dir, user_files_dir = roots(language)
    window.close()
    helper = ls.Store(db_path, language, data_dir, user_files_dir, "helper")
    lock = ls._write_lock_for(db_path)
    holding = threading.Event()
    released_at = []

    def hold():
        lock.acquire()
        holding.set()
        time.sleep(0.4)                        # the hold the close is measured against
        released_at.append(time.perf_counter())
        lock.release()

    holder = threading.Thread(target=hold)
    closed = False
    try:
        helper.meta()                          # the helper has read, and is the only connection
        holder.start()
        assert holding.wait(5.0), "the holder never took the write lock"
        start = time.perf_counter()
        helper.close()
        closed = True
        elapsed = time.perf_counter() - start
        assert elapsed >= 0.3, "the helper's close did not wait for the held write lock"
        assert released_at and time.perf_counter() >= released_at[0], "the close returned before the release"
        assert _wal(db_path) is None, "the helper's close should checkpoint and delete the -wal"
    finally:
        holder.join(5.0)
        if not closed:
            helper.close()


def _no_anchor(*args, **kwargs):
    """Stands for a file that can't be read just now: no read-only anchor opens."""
    raise sqlite3.OperationalError("unable to open database file")


@pytest.mark.parametrize("language", LANGUAGES)
def test_close_without_anchor_takes_a_free_lock_and_checkpoints(language, monkeypatch):
    """No anchor and the write lock free: the close runs under the lock, so it is the checkpointing close and the
    `-wal` is gone afterwards."""
    store = migrated(language)
    try:
        ids = store.ids("now")
        store.move([ids[-1]], "now")
        assert _wal(store) is not None          # the write left a `-wal` for the close to checkpoint
        monkeypatch.setattr(ls, "_read_only", _no_anchor)
        store.close()
        assert _wal(store.db_path) is None
        with pytest.raises(sqlite3.ProgrammingError):
            store.conn.execute("SELECT 1")
    finally:
        try:
            store.close()
        except Exception:
            pass


@pytest.mark.parametrize("language", LANGUAGES)
def test_close_without_anchor_never_waits_for_a_held_lock(language, monkeypatch):
    """No anchor and another thread holds the write lock for 1 s: the close does not wait for it. The holder's open
    connection means this close isn't the last, so the close just closes its handle."""
    store = migrated(language)
    holding = threading.Event()

    def hold():
        lock = ls._write_lock_for(store.db_path)
        lock.acquire()
        try:
            holding.set()
            time.sleep(1.0)
        finally:
            lock.release()

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert _until(holding.is_set)
        monkeypatch.setattr(ls, "_read_only", _no_anchor)
        started = time.perf_counter()
        store.close()
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5                    # the holder keeps its 1 s; a wait would show here
        with pytest.raises(sqlite3.ProgrammingError):
            store.conn.execute("SELECT 1")
    finally:
        holder.join(5)
        try:
            store.close()
        except Exception:
            pass


@pytest.mark.parametrize("language", LANGUAGES)
def test_mode_check_reads_a_closed_store_without_writing_its_wal_or_db(language):
    """The Content Manager's mode check reads a closed store without writing it: a read-only probe never checkpoints
    at its close, so after a move and a close (the `-wal` kept) three probes leave the `-wal` size and the `.db`
    bytes exactly as they were."""
    data_dir, _user_files_dir = roots(language)
    store = migrated(language)
    db_path = store.db_path
    try:
        ids = store.ids("now")
        store.move([ids[0]], "now", after_id=ids[3])
    finally:
        store.close()
    before_wal = _wal(db_path)
    before_sha = _sha(db_path)
    # Premise: the close kept a `-wal`, so a checkpoint by a probe would show up as its removal.
    assert before_wal is not None and before_wal > 0
    for _ in range(3):
        assert ls.check_mode(language, data_dir, busy_wait=0.0) == ("store", None)
    assert _wal(db_path) == before_wal
    assert _sha(db_path) == before_sha


@pytest.mark.parametrize("language", LANGUAGES)
def test_held_span_gives_one_connect_handle_closed_only_at_the_span_end(language):
    """One handle for a span (§6.12): Connect asks for its store many times a job and gets one handle. Inside
    `held()` every same-role `open_store` returns it, `with s:` and a nested span leave it open, another role or
    another thread gets its own, and the handle closes when the outer span ends. Outside a span, each call opens
    its own store. A damaged marker makes the span's open return None."""
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    try:
        with ls.held():
            a = ls.open_store(language, data_dir, user_files_dir, role="connect")
            b = ls.open_store(language, data_dir, user_files_dir, role="connect")
            c = ls.open_store(language, data_dir, user_files_dir, role="connect")
            assert a is not None
            assert a is b is c
            with a:  # a job's `with store:` must not close the shared handle
                pass
            assert a.meta() is not None
            with ls.held():  # a nested span joins the outer one; its end leaves the handle open
                assert ls.open_store(language, data_dir, user_files_dir, role="connect") is a
            assert a.meta() is not None
            reader = ls.open_store(language, data_dir, user_files_dir, role="reader")
            assert reader is not None and reader is not a
            # another thread has no span: its open gets its own handle
            seen = {}

            def other_thread():
                # SQLite objects must close on the thread that made them
                store = ls.open_store(language, data_dir, user_files_dir, role="connect")
                seen["store"] = store
                if store is not None:
                    store.close()

            worker = threading.Thread(target=other_thread)
            worker.start()
            worker.join(5)
            assert seen.get("store") is not None and seen["store"] is not a
            # a damaged marker makes the span's open return None (the marker goes in a finally)
            ls.mark_damaged(a.db_path, "x")
            try:
                assert ls.open_store(language, data_dir, user_files_dir, role="connect") is None
            finally:
                os.remove(ls.damaged_marker(a.db_path))
        # the outer span's end closed the handle (and the reader opened inside it)
        with pytest.raises(sqlite3.ProgrammingError):
            a.conn.execute("SELECT 1")
        # outside any span, two calls give two stores
        x = ls.open_store(language, data_dir, user_files_dir, role="connect")
        y = ls.open_store(language, data_dir, user_files_dir, role="connect")
        try:
            assert x is not None and y is not None and x is not y
        finally:
            for s in (x, y):
                if s is not None:
                    s.close()
    finally:
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_opener_check_reads_through_its_open_handle_and_probes_only_when_it_must(language, monkeypatch):
    """The Content Manager's mode check runs twice a drag; once this thread holds the store open, a check reads the
    handle it has (no new connection), and it still probes when the store turns newer under it (a rule that
    would hide a newer Surasura's copy)."""
    data_dir, user_files_dir = roots(language)
    store = migrated(language)
    store.close()
    real_probe = ls._probe
    probes = []

    def counting_probe(db_path, busy_wait):
        probes.append(db_path)
        return real_probe(db_path, busy_wait)

    monkeypatch.setattr(ls, "_probe", counting_probe)
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    handle = None
    try:
        assert opener.check() == "store"          # no handle yet: the probe runs
        assert len(probes) >= 1
        handle = opener.handle()
        assert handle is not None
        before = len(probes)
        assert opener.check() == "store"
        assert opener.check() == "store"
        assert len(probes) == before              # both checks read through the handle: no probe

        # Make the store newer under the open handle: the handle's answer is no longer "store", so the probe runs.
        raw = sqlite3.connect(handle.db_path)
        try:
            raw.execute(f"PRAGMA user_version = {ls.STORE_SCHEMA + 1}")
            raw.commit()
        finally:
            raw.close()
        assert opener.check() == "read-only"
        assert opener.reason == "made by a newer Surasura"
        assert len(probes) > before
    finally:
        raw = sqlite3.connect(ls.library_db_path(language, data_dir))
        try:
            raw.execute(f"PRAGMA user_version = {ls.STORE_SCHEMA}")
            raw.commit()
        finally:
            raw.close()
        if handle is not None:
            handle.close()


def _idle_key(store):
    """The key `_outside_wrote` files a pending idle trigger under."""
    return os.path.normcase(os.path.abspath(store.db_path))


def _quick_idle(monkeypatch):
    """The idle trigger on, with a short wait (0.2 s, well under the 5 s bounds the tests poll with)."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT")
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 0.2)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_burst_of_connect_receipts_spawns_one_helper(language, store_helper_spawns, monkeypatch):
    """Connect's three receipts in a row are one burst: one idle trigger, one helper, not one per receipt."""
    _quick_idle(monkeypatch)
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    store_helper_spawns.clear()
    connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
    try:
        ids = connect.ids("now")
        assert len(ids) >= 3, "the library needs three items for the burst"
        for n, item in enumerate(ids[:3]):
            assert connect.receipt(item, f"2026-10-08T10:0{n}:00Z") is not None
        assert _until(lambda: store_helper_spawns), "the burst's trigger never spawned the helper"
        assert not _until(lambda: len(store_helper_spawns) > 1, limit=0.5), "a second spawn for one burst"
        assert store_helper_spawns == [(language,)]
    finally:
        connect.close()
        ls._outside_idle_now()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_window_move_with_the_copy_up_to_date_arms_nothing(language, store_helper_spawns, monkeypatch):
    """A window's own write is not Connect's: with the copy up to date, a move arms no idle trigger and spawns
    nothing (a window's copy follows its own window's trigger, not this one)."""
    _quick_idle(monkeypatch)
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    ls.maintain(language, data_dir, user_files_dir)
    store_helper_spawns.clear()
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        ids = store.ids("now")
        store.move([ids[-1]], "now")
        assert _idle_key(store) not in ls._IDLE, "a window's move armed the idle trigger"
        assert not _until(lambda: store_helper_spawns, limit=0.5), "a window's move spawned the helper"
    finally:
        store.close()
        ls._outside_idle_now()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_connect_receipt_that_changes_nothing_arms_no_trigger(language, store_helper_spawns, monkeypatch):
    """A repeated receipt (the same mined_at) writes no row, so it must not arm the idle trigger: the write lock and
    the commit are not Connect's cue to copy again."""
    _quick_idle(monkeypatch)
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    store_helper_spawns.clear()
    connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
    try:
        item = connect.ids("now")[0]
        assert connect.receipt(item, "2026-10-08T10:00:00Z") is not None, "the first receipt must change the row"
        ls._outside_idle_now()                  # run that trigger now, so _IDLE starts empty
        store_helper_spawns.clear()
        assert connect.receipt(item, "2026-10-08T10:00:00Z") is None, "the repeat must change nothing"
        assert _idle_key(connect) not in ls._IDLE, "a receipt that changed nothing armed the idle trigger"
        assert not _until(lambda: store_helper_spawns, limit=0.5)
    finally:
        connect.close()
        ls._outside_idle_now()


@pytest.mark.parametrize("language", LANGUAGES)
def test_idle_trigger_checkpoints_and_spawns_nothing_when_the_copy_is_up_to_date(language, monkeypatch,
                                                                                 store_helper_spawns):
    """A copy that isn't behind has nothing to export, so the idle trigger only checkpoints. The write is a bookkeeping
    value the copy doesn't carry (no `copy_dirty`), so the copy stays current and no helper is spawned."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 0.2)
    monkeypatch.setattr(ls, "_IDLE", {})
    checkpoints = []
    real_checkpoint = ls.Store.checkpoint

    def counting(self, *args, **kwargs):
        checkpoints.append(1)
        return real_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(ls.Store, "checkpoint", counting)
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    connect = None
    try:
        ls.maintain(language, data_dir, user_files_dir)
        assert not ls.maintain_due(window)[0], "precondition: the copy must be up to date"
        store_helper_spawns.clear()
        checkpoints.clear()                   # the setup's own checkpoints are not the trigger's
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        key = os.path.normcase(os.path.abspath(connect.db_path))
        connect.bookkeeping({"analysed_order_version": connect.meta().get("analysed_order_version", 0) + 1})
        timer = ls._IDLE[key][0]              # taken at the commit, before the trigger can take it off the list
        timer.join(5.0)
        assert not timer.is_alive(), "the idle trigger never fired"
        assert len(checkpoints) == 1, "an up-to-date copy is checkpointed once"
        assert store_helper_spawns == [], "an up-to-date copy spawns no helper"
    finally:
        if connect is not None:
            connect.close()
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_exit_runs_a_pending_idle_trigger_at_once(language, monkeypatch, store_helper_spawns):
    """A Connect receipt makes the copy behind, and its idle trigger is still waiting (30 s). At exit the pending
    trigger runs now, in this thread: one helper spawn, and nothing left on the list."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)
    monkeypatch.setattr(ls, "_IDLE", {})
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    connect = None
    try:
        ls.maintain(language, data_dir, user_files_dir)
        store_helper_spawns.clear()
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        connect.receipt(connect.ids("now")[0], "2026-10-08T10:00:00Z")
        assert len(ls._IDLE) == 1, "the receipt leaves one idle trigger waiting"
        timer = next(iter(ls._IDLE.values()))[0]
        ls._outside_idle_now()
        timer.join(5.0)
        assert ls._IDLE == {}, "exit takes every pending trigger off the list"
        assert store_helper_spawns == [(language,)], "the behind copy is exported at exit, once"
    finally:
        if connect is not None:
            connect.close()
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_mode_check_falls_back_to_a_reader_when_a_read_only_open_says_readonly(language, monkeypatch):
    """A read-only open that fails with a "readonly" error does not make the store read-only: the mode check reads
    again on a reader's connection and answers that the store is live. Why: a library the read-only connection can't
    open just now is still a working library, and reporting it read-only would lock the Content Manager out of it."""
    data_dir, _user_files_dir = roots(language)
    store = migrated(language)
    store.close()
    attempts = []

    def read_only_refused(path, busy_ms):
        attempts.append(path)
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(ls, "_read_only", read_only_refused)
    assert ls.check_mode(language, data_dir, busy_wait=0.0) == ("store", None)
    # Premise: the read-only open really was tried and refused, so the answer came from the reader's retry. (The
    # reader's close also asks for a read-only anchor, so the count can be more than one.)
    assert attempts


@pytest.mark.parametrize("language", LANGUAGES)
def test_mode_check_reads_any_read_only_failure_again_and_reports_a_reader_failure_as_io(language, monkeypatch):
    """Any failure of the read-only open that isn't busy or damage (here a disk error) is read again on a reader's
    connection, as before L3.3: a store that one kind of connection can't open isn't called read-only for it. Only
    when the reader fails too is the answer ("read-only", "io: ...")."""
    data_dir, _user_files_dir = roots(language)
    store = migrated(language)
    store.close()
    attempts = []

    def disk_failed(path, busy_ms):
        attempts.append(path)
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(ls, "_read_only", disk_failed)
    assert ls.check_mode(language, data_dir, busy_wait=0.0) == ("store", None), "read again on a reader"
    attempts.clear()
    monkeypatch.setattr(ls, "_connect", lambda *a, **k: disk_failed(*a[:1], 0))
    assert ls.check_mode(language, data_dir, busy_wait=0.0) == ("read-only", "io: disk I/O error")
    assert len(attempts) == 2, "one read-only try, one reader try"


@pytest.mark.parametrize("language", LANGUAGES)
def test_under_the_suites_a_connect_receipt_arms_no_idle_trigger(language, store_helper_spawns, monkeypatch):
    """The suites set SURASURA_NO_IDLE_EXPORT, so a Connect receipt that changes a row must arm no idle trigger and
    spawn no helper. The contrast in the same test (switch off, a second receipt) arms one, so the first half
    can't pass just because the trigger is broken."""
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 0.2)
    monkeypatch.setattr(ls, "_IDLE", {})
    assert os.environ.get("SURASURA_NO_IDLE_EXPORT"), "the suites set the switch; this test relies on it"
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    store_helper_spawns.clear()
    connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
    try:
        ids = connect.ids("now")
        assert len(ids) >= 2, "the library needs two items for the two receipts"
        assert connect.receipt(ids[0], "2026-10-08T10:00:00Z") is not None, "the receipt must change the row"
        assert _idle_key(connect) not in ls._IDLE, "under the suites' switch a receipt armed the idle trigger"
        assert not _until(lambda: store_helper_spawns, limit=0.5), "under the suites a receipt spawned the helper"

        # The contrast: with the switch off the same kind of receipt arms the trigger. The wait is long here so
        # the timer cannot fire before the check.
        monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT")
        monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 5.0)
        assert connect.receipt(ids[1], "2026-10-08T10:01:00Z") is not None, "the second receipt must change its row"
        assert _idle_key(connect) in ls._IDLE, "with the switch off a receipt must arm the idle trigger"
    finally:
        connect.close()
        ls._outside_idle_now()


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_connects_writes_arm_the_idle_trigger_not_the_command_lines(language, monkeypatch, store_helper_spawns):
    """Connect's process lives long enough to batch a burst into one export; the command line (role "register") is one
    process a hato drop, so arming it would export once a drop (the intent keeper's IK-3). Its receipt arms nothing,
    nor does an analyzer's bookkeeping write; a Connect receipt arms the trigger, and at exit the behind copy is
    exported once. The trigger is 30 s, so it stays pending until the exit call."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)
    monkeypatch.setattr(ls, "_IDLE", {})
    data_dir, user_files_dir = roots(language)
    migrated(language).close()                # no maintain: the copy is behind from here on
    store_helper_spawns.clear()
    for role in ("analyzer", "register"):
        other = ls.open_store(language, data_dir, user_files_dir, role=role)
        try:
            assert other is not None
            if role == "analyzer":
                other.bookkeeping({"analysed_order_version": other.meta().get("analysed_order_version", 0) + 1})
            else:
                assert other.receipt(other.ids("now")[1], "2026-10-08T09:00:00Z") is not None
            assert ls._IDLE == {}, f"a {role} write armed the idle trigger"
        finally:
            other.close()
    connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
    try:
        assert connect.receipt(connect.ids("now")[0], "2026-10-08T10:00:00Z") is not None
        assert _idle_key(connect) in ls._IDLE, "Connect's receipt did not arm the idle trigger"
        assert not _until(lambda: store_helper_spawns, limit=0.5), "the pending trigger spawned before exit"
        ls._outside_idle_now()
        assert store_helper_spawns == [(language,)], "the behind copy is exported at exit, once"
    finally:
        connect.close()
        ls._outside_idle_now()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_trigger_called_off_its_own_timer_thread_does_nothing(language, monkeypatch, store_helper_spawns):
    """Only the thread that owns a pending trigger (its timer) or the exit hook takes it. A call from any other thread
    must leave the entry on the list, spawn nothing and checkpoint nothing: a trigger a later commit replaced must not
    fire on its own. Exit then runs the waiting trigger once."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)
    monkeypatch.setattr(ls, "_IDLE", {})
    checkpoints = []
    real_checkpoint = ls.Store.checkpoint

    def counting(self, *args, **kwargs):
        checkpoints.append(1)
        return real_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(ls.Store, "checkpoint", counting)
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    connect = None
    try:
        ls.maintain(language, data_dir, user_files_dir)
        store_helper_spawns.clear()
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        key = _idle_key(connect)
        assert connect.receipt(connect.ids("now")[0], "2026-10-08T10:00:00Z") is not None
        assert key in ls._IDLE, "the receipt leaves one idle trigger waiting"
        store_helper_spawns.clear()
        checkpoints.clear()
        ls._outside_idle(language, data_dir, user_files_dir, key)   # this test's thread is not the timer
        assert key in ls._IDLE, "a call off the timer's thread took the pending trigger off the list"
        assert not _until(lambda: store_helper_spawns, limit=0.5), "a call off the timer's thread spawned the helper"
        assert checkpoints == [], "a call off the timer's thread checkpointed"
        ls._outside_idle_now()                  # exit: the waiting trigger runs now, once
        assert ls._IDLE == {}, "exit left the trigger on the list"
        assert store_helper_spawns == [(language,)], "exit did not export the behind copy exactly once"
    finally:
        ls._outside_idle_now()                  # no-op when the test got this far; clears a waiting timer on failure
        if connect is not None:
            connect.close()
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_exit_waits_for_a_trigger_its_timer_is_already_running(language, store_helper_spawns, monkeypatch):
    """A timer that has already taken its trigger and is mid-run (here: held 1.0 s inside maintain_due) is waited for
    at exit: `_outside_idle_now` returns only after that run is done, so the helper spawn is there the moment it
    returns. Without the wait the interpreter would stop the daemon timer mid-way and the copy would stay behind."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 0.1)
    monkeypatch.setattr(ls, "_IDLE", {})
    started = threading.Event()
    real_maintain_due = ls.maintain_due

    def slow_maintain_due(store):
        started.set()
        time.sleep(1.0)                     # the timer is mid-run for this long: exit must wait for it
        return real_maintain_due(store)

    monkeypatch.setattr(ls, "maintain_due", slow_maintain_due)
    data_dir, user_files_dir = roots(language)
    migrated(language).close()              # no maintain after this: the copy is behind
    store_helper_spawns.clear()
    connect = None
    try:
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        key = _idle_key(connect)
        assert connect.receipt(connect.ids("now")[0], "2026-10-08T10:00:00Z") is not None
        assert _until(started.is_set), "the idle trigger never started its run"
        assert key not in ls._IDLE, "the running trigger still sits on the list; its entry should be taken"
        started_at = time.monotonic()
        ls._outside_idle_now()
        waited = time.monotonic() - started_at
        assert store_helper_spawns == [(language,)], "exit returned before the running trigger finished its export"
        assert waited >= 0.5, f"exit did not wait for the running trigger (returned after {waited:.2f} s)"
    finally:
        ls._outside_idle_now()
        if connect is not None:
            connect.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_spans_handle_on_a_store_marked_damaged_is_let_go_at_once(language):
    """Repair sets a damaged store's files aside, which Windows refuses while any handle is open (the intent keeper's
    IK-4): a span that finds the damage marker closes its handle there and then, not at the span's end."""
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    db = ls.library_db_path(language, data_dir)
    try:
        with ls.held():
            held = ls.open_store(language, data_dir, user_files_dir, role="connect")
            assert held is not None
            ls.mark_damaged(db, "a test's damage")
            assert ls.open_store(language, data_dir, user_files_dir, role="connect") is None
            with pytest.raises(sqlite3.ProgrammingError):
                held.conn.execute("SELECT 1")
            os.remove(ls.damaged_marker(db))            # repaired meanwhile: the span opens a working handle again
            again = ls.open_store(language, data_dir, user_files_dir, role="connect")
            assert again is not None and again is not held
            assert again.meta()["state_version"] >= 0
    finally:
        if os.path.exists(ls.damaged_marker(db)):
            os.remove(ls.damaged_marker(db))


def test_every_reader_connection_the_store_opens_is_closed_through_close():
    """A source scan (the intent keeper's IK-2): a plain `close()` of a read-write connection that is the database's
    last checkpoints it outside the write lock. Every function that opens one with `_connect(` closes it through
    `_close(` (a `Store` closes its own through `Store.close`)."""
    import inspect
    source = inspect.getsource(ls)
    offenders = []
    for block in source.split("\ndef ")[1:]:
        name = block.split("(", 1)[0]
        if "= _connect(" in block and name not in ("_probe",) and "_close(" not in block:
            offenders.append(name)
    assert offenders == [], offenders


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_restore_never_brings_back_a_gone_notes_mark(language):
    """A removed item keeps its Anki links in its trash row, so Put back restores them. A note Anki no longer has
    (`notes_gone`) must leave that kept list too: the restore brings back only the links whose notes still exist. Why:
    a deleted card must never show as "in Anki" again after its item comes back."""
    store = migrated(language)
    try:
        victim = store.ids("now")[2]
        with store._writing():
            store.conn.executemany("INSERT INTO anki_links (item_id, note_id, source, linked_at) VALUES (?, ?, ?, ?)",
                                   [(victim, 701, "anki_miner", "t"), (victim, 702, "anki_miner", "t")])
        removed = store.remove([victim])
        assert store.notes_gone([701]) == [701]
        assert store.notes_gone([701]) == [], "a note already gone is no longer held anywhere"
        store.restore(removed.trash_ids)
        links = store.conn.execute("SELECT note_id FROM anki_links WHERE item_id = ?", (victim,)).fetchall()
        assert links == [(702,)], "the gone note's mark stays gone after Put back"
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_made_word_keeps_its_odd_note_entries_and_loses_only_the_gone_ids(language):
    """A made word's `note_ids` may hold entries that aren't note numbers (`null`, `"x"`): `notes_gone` must keep them
    as they are, never stop on them, and still take out the gone note's id. A second `notes_gone` for the same note
    finds nothing left to take out."""
    store = migrated(language)
    try:
        with store._writing():
            for sql in ls.ADDED_TABLES_SQL:
                store.conn.execute(sql)
            store.conn.execute("INSERT INTO made_words (item_id, word, note_ids, made_at, batch) "
                               "VALUES (?, ?, ?, ?, ?)",
                               (901, "上層部", json.dumps([801, None, "x", 802]), "t", None))
        assert store.notes_gone([801]) == [801]
        row = store.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?",
                                 (901, "上層部")).fetchone()
        assert json.loads(row[0]) == [None, "x", 802]
        assert store.notes_gone([801]) == []
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_span_handle_on_a_store_no_longer_migrated_is_let_go_at_once(language):
    """A store whose `migrated_at` is gone is no longer a ready store, though its file is not damaged: a span that
    opened it earlier must not keep handing it out. The mode is read again on the handle's own connection each time,
    so the check it does is the one that finds the store not ready, and the handle is closed there and then."""
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    with ls.held():
        held = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert held is not None
        with held._writing():
            held.conn.execute("DELETE FROM meta WHERE key = 'migrated_at'")
        assert ls.open_store(language, data_dir, user_files_dir, role="connect") is None
        with pytest.raises(sqlite3.ProgrammingError):
            held.conn.execute("SELECT 1")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_whose_open_fails_after_its_connection_opened_is_closed_through_close(language, monkeypatch):
    """A failed open: `open_store` builds the `Store`, then the soon-line read raises a database error. The connection
    the store already holds must go through `_close` (never the collector's plain close, which may checkpoint outside
    the write lock), exactly once, and `open_store` returns None."""
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    closed = []
    real_close = ls._close

    def spy_close(conn, db_path, role):
        closed.append((db_path, role))
        return real_close(conn, db_path, role)

    def failing_soon_line(store):
        raise sqlite3.DatabaseError("x")

    monkeypatch.setattr(ls, "_rederive_soon_line", failing_soon_line)
    monkeypatch.setattr(ls, "_close", spy_close)
    assert ls.open_store(language, data_dir, user_files_dir, role="window") is None
    assert len(closed) == 1, closed
    assert closed[0][1] == "window"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_reimport_question_still_gets_a_checkpoint(language, monkeypatch):
    """A re-import question waiting on the user (meta `reimport_pending` holding the copy's current stat) must not
    leave the `-wal` growing: `maintain` checkpoints before it returns EXIT_NEEDS_YOU (§6.12). The copy is made first
    by one clean run, so the stat the question holds is a real one, and the checkpoint count is taken only for the
    waiting run."""
    checkpoints = []
    real_checkpoint = ls.Store.checkpoint

    def counting(self, *args, **kwargs):
        checkpoints.append(1)
        return real_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(ls.Store, "checkpoint", counting)
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    try:
        assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
        window.bookkeeping({"reimport_pending": json.dumps({"stat": window.copy_stat()})})
        checkpoints.clear()                   # the setup's own checkpoints are not the waiting run's
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
        assert len(checkpoints) >= 1, "a waiting question must still checkpoint the store"
    finally:
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_close_trigger_with_nothing_to_export_checkpoints_exactly_once(language, monkeypatch):
    """Nothing due (the copy is current, no re-import waiting): the close trigger exports nothing, and its single
    checkpoint is the one that keeps the `-wal` for the write lock (§6.12). Exactly one: zero would leave the `-wal`
    for the next writer to pay for, and two would checkpoint twice at every exit."""
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    try:
        ls.maintain(language, data_dir, user_files_dir)
        assert not ls.maintain_due(window)[0], "precondition: the copy must be up to date"
    finally:
        window.close()                          # every handle is closed before the trigger runs
    checkpoints = []
    real_checkpoint = ls.Store.checkpoint

    def counting(self, *args, **kwargs):
        checkpoints.append(1)
        return real_checkpoint(self, *args, **kwargs)

    monkeypatch.setattr(ls.Store, "checkpoint", counting)
    assert ls.maintain_at_close(language, data_dir, user_files_dir) is None
    assert len(checkpoints) == 1, "an empty close trigger checkpoints exactly once"


@pytest.mark.parametrize("language", LANGUAGES)
def test_close_trigger_with_nothing_to_export_never_waits_for_a_held_write_lock(language):
    """Another thread holds the write lock for 2 s: the close trigger's checkpoint is skipped (wait=0), so it returns
    None well before the holder lets go. A waiting checkpoint would run out the holder's 2 s and fail the bound."""
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    try:
        ls.maintain(language, data_dir, user_files_dir)
        assert not ls.maintain_due(window)[0], "precondition: the copy must be up to date"
    finally:
        window.close()
    db = ls.library_db_path(language, data_dir)
    holding = threading.Event()

    def hold():
        lock = ls._write_lock_for(db)
        lock.acquire()
        try:
            holding.set()
            time.sleep(2.0)
        finally:
            lock.release()

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert _until(holding.is_set), "the holder never took the write lock"
        started = time.perf_counter()
        result = ls.maintain_at_close(language, data_dir, user_files_dir)
        elapsed = time.perf_counter() - started
        assert result is None
        assert elapsed < 1.0, "the close trigger waited for a write lock another thread holds"
    finally:
        holder.join(5.0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_openers_close_closes_its_handle_and_the_next_handle_is_a_new_working_one(language):
    """StoreOpener.close() (§6.12) closes this thread's handle through `_close` and forgets it: the old handle's
    connection is shut, and the next handle() opens a fresh, working store rather than handing back the closed one.
    The opener's own close in the finally also closes the fresh handle, so no connection outlives the test."""
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    try:
        assert opener.check() == "store"
        first = opener.handle()
        assert first is not None
        opener.close()
        with pytest.raises(sqlite3.ProgrammingError):
            first.conn.execute("SELECT 1")
        fresh = opener.handle()
        assert fresh is not None and fresh is not first
        assert fresh.meta()["state_version"] >= 0  # a working connection, not the closed one
    finally:
        opener.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_content_manager_close_ends_its_worker_and_closes_its_own_handle(language):
    """The window's close (§6.12, the Content Manager's `_close_store_handles`): its worker is stopped and ended, and
    the handle its opener holds on this thread is closed through the store's close, so its connection can no longer
    be used. The worker is a stand-in that waits on the stop event, so the test needs no window; the real app's
    short join (STORE_CLOSE_WAIT_S) is far longer than the stop event takes to end it."""
    from app.content_importer_gui import ContentImporterApp
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "store"
    handle = opener.handle()
    assert handle is not None
    stop, wake = threading.Event(), threading.Event()
    worker = threading.Thread(target=lambda: stop.wait(30), daemon=True)
    worker.start()
    app = ContentImporterApp.__new__(ContentImporterApp)
    app._worker_stop, app._worker_wake, app._worker, app._store_opener = stop, wake, worker, opener
    try:
        app._close_store_handles()
        assert not worker.is_alive()
        with pytest.raises(sqlite3.ProgrammingError):
            handle.conn.execute("SELECT 1")
    finally:
        stop.set()
        worker.join(5.0)
        opener.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_triggers_own_open_arms_no_second_trigger(language, monkeypatch, store_helper_spawns):
    """The idle trigger's own open rewrites a wrong soon line (the rederive). That write must arm NO new trigger, or the
    trigger would keep re-arming itself: the guard in `_outside_wrote` is what stops it."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)       # long: a receipt's trigger must still be waiting when read
    monkeypatch.setattr(ls, "_IDLE", {})
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    connect = None
    try:
        ls.maintain(language, data_dir, user_files_dir)
        store_helper_spawns.clear()
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        connect.receipt(connect.ids("now")[0], "2026-10-08T10:00:00Z")
        assert len(ls._IDLE) == 1, "the receipt leaves one idle trigger waiting"
        with window._writing():                               # written after the receipt, so nothing repairs it first
            window._set_meta({"soon_line": 9999})             # a wrong soon line for the trigger's open to rewrite
        timer = next(iter(ls._IDLE.values()))[0]
        ls._outside_idle_now()
        timer.join(5.0)
        assert str(window.meta().get("soon_line")) != "9999", "the trigger's own open rewrote the wrong soon line"
        assert ls._IDLE == {}, "a trigger's own write arms no second trigger"
    finally:
        for pending_timer, _args in list(ls._IDLE.values()):
            pending_timer.cancel()
        ls._IDLE.clear()
        if connect is not None:
            connect.close()
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_idle_trigger_spawns_no_helper_when_the_data_folder_is_another_one_now(language, monkeypatch,
                                                                               store_helper_spawns):
    """The copy is behind, but the language's data folder has moved since the store was written: a helper would
    export into a folder the app no longer reads. The trigger spawns nothing and logs, beside the db, that the copy
    waits for the next open or write. The copy-behind precondition keeps the test from passing on a copy that was
    never due (the no-helper branch is only reached when `due`)."""
    from app import path_utils
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)
    monkeypatch.setattr(ls, "_IDLE", {})
    data_dir, user_files_dir = roots(language)
    moved = os.path.join(os.environ["SURASURA_TEST_ROOT"], "another data folder", language)
    window = migrated(language)
    connect = None
    try:
        ls.maintain(language, data_dir, user_files_dir)
        store_helper_spawns.clear()
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        connect.receipt(connect.ids("now")[0], "2026-10-08T10:00:00Z")
        assert ls.maintain_due(window)[0], "precondition: the copy must be behind"
        assert len(ls._IDLE) == 1, "the receipt leaves one idle trigger waiting"
        monkeypatch.setattr(path_utils, "get_data_path", lambda *args, **kwargs: moved)
        ls._outside_idle_now()
        assert ls._IDLE == {}, "exit takes every pending trigger off the list"
        assert store_helper_spawns == [], "a copy behind for another data folder spawns no helper"
        log = os.path.join(os.path.dirname(connect.db_path), "library_maintain.log")
        with open(log, encoding="utf-8") as f:
            assert "data folder is another one now" in f.read()
    finally:
        if connect is not None:
            connect.close()
        window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_idle_trigger_checkpoint_gives_up_on_a_busy_lock_within_its_short_wait(language, monkeypatch):
    """The idle trigger's checkpoint waits OUTSIDE_IDLE_WAIT (0.2 s) for the write lock, not the 5 s the store allows:
    another thread holds the lock for up to 3 s, so the trigger returns at once, the checkpoint is left to the next
    one and the log says so. Why: a trigger that waited the full lock timeout would hold up the exit behind a writer."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_WAIT", 0.2)
    monkeypatch.setattr(ls, "_IDLE", {})
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    connect = None
    holder = None
    release = threading.Event()
    try:
        ls.maintain(language, data_dir, user_files_dir)
        assert not ls.maintain_due(window)[0], "precondition: the copy must be up to date"
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert connect is not None
        key = os.path.normcase(os.path.abspath(connect.db_path))
        connect.bookkeeping({"analysed_order_version": connect.meta().get("analysed_order_version", 0) + 1})
        assert key in ls._IDLE, "precondition: the write arms one idle trigger"

        locked = threading.Event()

        def hold_write_lock():
            # Another connection in this process takes the same write lock and keeps it until released (3 s at most).
            other = ls.open_store(language, data_dir, user_files_dir, role="connect")
            try:
                with other._writing(begin=False):
                    locked.set()
                    release.wait(3.0)
            finally:
                other.close()

        holder = threading.Thread(target=hold_write_lock, daemon=True)
        holder.start()
        assert locked.wait(5.0), "the other connection never took the write lock"

        started = time.perf_counter()
        ls._outside_idle_now()
        elapsed = time.perf_counter() - started
        release.set()
        assert elapsed < 1.5, f"the trigger waited {elapsed:.2f} s for a busy lock; its wait is 0.2 s"
        with open(os.path.join(os.path.dirname(connect.db_path), "library_maintain.log"), encoding="utf-8") as f:
            assert "write lock was busy" in f.read()
    finally:
        release.set()
        if holder is not None:
            holder.join(5.0)
        if connect is not None:
            connect.close()
        window.close()
