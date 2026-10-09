"""L3.3 of the library store (Library_Store_Spec.md §6.12): closes and checks that touch only what they must.

Why these matter: SQLite checkpoints a WAL database when its last connection closes, and deletes the `-wal`. Connect
opens the store about ten times a job; with Surasura closed every one of those closes was the last, so each ran a
checkpoint outside the store's write lock (the spec allows checkpoints only under it: SQLite 3.39.4's WAL-reset bug)
and the next write paid for a new `-wal` (a receipt's hold up to 62 ms, P2.4's verifier). Now a close never
checkpoints outside the lock, Connect can hold one handle for a job (`held()`), the copy follows Connect's and the
command line's writes on its own trigger, and the Content Manager's mode check, run twice a drag, reads through the
handle it already has instead of opening a connection each time (charter S19: a check that finds nothing does nothing).
Every test runs for Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT that tests/conftest.py sets.
"""

import hashlib
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

    def counting(self):
        checkpoints.append(1)
        return real_checkpoint(self)

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
def test_a_command_line_register_receipt_arms_the_idle_trigger(language, monkeypatch, store_helper_spawns):
    """The command line (role "register") writes with no window of its own, so its commit is a cue like Connect's: its
    receipt arms the idle trigger, and at exit the behind copy is exported once. An analyzer's bookkeeping write is a
    window-less write too but not one that leaves the copy behind, so it arms nothing. The trigger is 30 s, so it
    stays pending until the exit call; nothing spawns before it."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 30)
    monkeypatch.setattr(ls, "_IDLE", {})
    data_dir, user_files_dir = roots(language)
    migrated(language).close()                # no maintain: the copy is behind from here on
    store_helper_spawns.clear()
    analyst = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
    try:
        assert analyst is not None
        analyst.bookkeeping({"analysed_order_version": analyst.meta().get("analysed_order_version", 0) + 1})
        assert _idle_key(analyst) not in ls._IDLE, "an analyzer's bookkeeping write armed the idle trigger"
    finally:
        analyst.close()
    register = ls.open_store(language, data_dir, user_files_dir, role="register")
    try:
        assert register is not None
        assert register.receipt(register.ids("now")[0], "2026-10-08T10:00:00Z") is not None
        key = _idle_key(register)
        assert key in ls._IDLE, "the command line's receipt did not arm the idle trigger"
        assert not _until(lambda: store_helper_spawns, limit=0.5), "the pending trigger spawned before exit"
        ls._outside_idle_now()
        assert store_helper_spawns == [(language,)], "the command line's behind copy is exported at exit, once"
    finally:
        register.close()
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

    def counting(self):
        checkpoints.append(1)
        return real_checkpoint(self)

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
    """A timer that has already taken its trigger and is mid-run (here: held 0.6 s inside maintain_due) is waited for
    at exit: `_outside_idle_now` returns only after that run is done, so the helper spawn is there the moment it
    returns. Without the wait the interpreter would stop the daemon timer mid-way and the copy would stay behind."""
    monkeypatch.delenv("SURASURA_NO_IDLE_EXPORT", raising=False)
    monkeypatch.setattr(ls, "OUTSIDE_IDLE_S", 0.1)
    monkeypatch.setattr(ls, "_IDLE", {})
    started = threading.Event()
    real_maintain_due = ls.maintain_due

    def slow_maintain_due(store):
        started.set()
        time.sleep(0.6)                     # the timer is mid-run for this long: exit must wait for it
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
        assert waited >= 0.3, f"exit did not wait for the running trigger (returned after {waited:.2f} s)"
    finally:
        ls._outside_idle_now()
        if connect is not None:
            connect.close()
