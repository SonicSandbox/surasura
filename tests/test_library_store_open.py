"""WP-L1 of the library store (Library_Store_Spec.md §10): the path, opening, schema v1, integrity, the
maintenance lock and the write lock.

Why these matter: the store replaces master_manifest.json as the truth for the user's library order, so
it must never open the real library from a test (I7), never let two writers race into SQLite 3.39.4's
WAL-reset bug (K32: every write under one cross-process lock, enforced by `query_only`), and never lose
data when something is damaged (I2: set aside, salvaged, never deleted). Every test runs for Japanese and
Chinese alike (I11), under the per-test SURASURA_TEST_ROOT that tests/conftest.py sets.
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from app import library_store as ls
from app import path_utils
from tests.test_library_store_support import (LANGUAGES, library, migrated, paths, roots, subprocess_env,
                                              write_manifest)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _db(language):
    data_dir, _u = roots(language)
    return ls.library_db_path(language, data_dir)


def _hold_busy(db_path, seconds, ready):
    """Hold the database so another connection's read gets SQLITE_BUSY: an exclusive-locking-mode
    connection that has written keeps its lock until it closes."""
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=0.1)
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute("BEGIN EXCLUSIVE")
    conn.execute("CREATE TABLE IF NOT EXISTS _hold (x)")
    conn.execute("COMMIT")
    ready.set()
    time.sleep(seconds)
    conn.close()


# --- 1. connections --------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_connections_open_no_transaction_and_belong_to_their_thread(language):
    store = migrated(language)
    try:
        # Python opens no transaction of its own: every BEGIN is ours (§6.2)
        assert store.conn.in_transaction is False
        errors = []

        def other_thread():
            try:
                store.conn.execute("SELECT 1").fetchone()
            except sqlite3.ProgrammingError as exc:
                errors.append(exc)

        t = threading.Thread(target=other_thread)
        t.start()
        t.join()
        assert errors, "a connection used from another thread must raise (K31)"

        got = []

        def worker():
            data_dir, user_files_dir = roots(language)
            own = ls.open_store(language, data_dir, user_files_dir)
            got.append(len(own.ids("now")))
            own.close()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert got == [len(store.ids("now"))]
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_the_helper_auto_checkpoints(language):
    store = migrated(language)
    store.close()
    data_dir, user_files_dir = roots(language)
    for role in ls.ROLES:
        s = ls.Store(_db(language), language, data_dir, user_files_dir, role)
        try:
            expected = 1000 if role == "helper" else 0
            assert s.conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == expected, role
            assert s.conn.execute("PRAGMA synchronous").fetchone()[0] == 2          # FULL (R-3)
            assert s.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert s.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert s.conn.execute("PRAGMA query_only").fetchone()[0] == 1
        finally:
            s.close()


# --- 2. busy at open --------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_busy_for_half_a_second_still_opens(language):
    migrated(language).close()
    ready = threading.Event()
    t = threading.Thread(target=_hold_busy, args=(_db(language), 0.5, ready))
    t.start()
    ready.wait(5)
    data_dir, user_files_dir = roots(language)
    store = ls.open_store(language, data_dir, user_files_dir)
    t.join()
    assert store is not None, "busy for 0.5 s is retried, not a lesser mode"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_busy_for_two_seconds_settles_on_a_lesser_mode_after_one(language):
    migrated(language).close()
    ready = threading.Event()
    t = threading.Thread(target=_hold_busy, args=(_db(language), 2.0, ready))
    t.start()
    ready.wait(5)
    data_dir, _u = roots(language)
    started = time.perf_counter()
    mode, reason = ls.check_mode(language, data_dir)
    took = time.perf_counter() - started
    t.join()
    assert (mode, reason) == ("read-only", "busy")
    # settles after its 1 s retry, never by waiting out the 2 s hold; 1.2 s on this desktop's timed run
    upper = 1.2 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 1.9
    assert 1.0 <= took <= upper, took


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_window_never_waits_for_a_busy_store(language):
    """The window thread's call returns the mode it cached at once — within 5 ms in the timed run, and
    always far under the 1 s busy retry or the 5 s lock wait it must never sit in (a CI runner is slower);
    the retry runs on a worker."""
    migrated(language).close()
    data_dir, user_files_dir = roots(language)
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "store"
    ready = threading.Event()
    t = threading.Thread(target=_hold_busy, args=(_db(language), 2.0, ready))
    t.start()
    ready.wait(5)
    started = time.perf_counter()
    mode = opener.check()
    took = time.perf_counter() - started
    limit = 0.005 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 0.1
    assert mode == "store" and took < limit, took
    assert opener.wait(3) == "read-only" and opener.reason == "busy"
    t.join()
    assert opener.check() == "store"


# --- 3. the maintenance lock --------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_maintenance_lock_two_takers_at_different_positions(language):
    db = _db(language)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    a, b = ls.MaintenanceLock(db), ls.MaintenanceLock(db)
    try:
        assert a.try_acquire()
        b._open()
        os.lseek(b.fd, 50, 0)       # another position: msvcrt would lock from here without the seek (K27)
        assert not b.try_acquire()
        a.release()
        assert b.try_acquire()
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_maintenance_lock_released_when_its_holder_is_killed(language):
    db = _db(language)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    script = ("import sys, time\nfrom app import library_store as ls\n"
              f"lock = ls.MaintenanceLock({db!r})\nassert lock.try_acquire()\nprint('held', flush=True)\ntime.sleep(60)\n")
    proc = subprocess.Popen([sys.executable, "-c", script], cwd=REPO, env=subprocess_env(),
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        lock = ls.MaintenanceLock(db)
        assert not lock.try_acquire()
        proc.kill()
        proc.wait(10)
        assert lock.acquire(10, 0.05), "the OS releases a dead holder's lock"
        lock.close()
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("language", LANGUAGES)
def test_maintenance_lock_holder_that_raises_still_unlocks(language):
    db = _db(language)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    with pytest.raises(RuntimeError):
        with ls.MaintenanceLock(db) as lock:
            assert lock.try_acquire()
            raise RuntimeError("a build failed")
    other = ls.MaintenanceLock(db)
    assert other.try_acquire()
    other.close()


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt only on Windows")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiter_loops_on_the_non_blocking_lock(language, monkeypatch):
    """Never LK_LOCK, which gives up after ten one-second tries; the waiter retries LK_NBLCK."""
    import msvcrt
    db = _db(language)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    holder = ls.MaintenanceLock(db)
    assert holder.try_acquire()
    modes = []
    real = msvcrt.locking

    def spy(fd, mode, n):
        modes.append(mode)
        return real(fd, mode, n)

    monkeypatch.setattr(msvcrt, "locking", spy)
    threading.Timer(0.2, holder.release).start()
    waiter = ls.MaintenanceLock(db)
    assert waiter.acquire(5, 0.01)
    waiter.close()
    holder.close()
    assert msvcrt.LK_LOCK not in modes and modes.count(msvcrt.LK_NBLCK) > 2


# --- 4. the write lock (K32) --------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_bare_write_outside_the_helper_fails(language):
    store = migrated(language)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store.conn.execute("UPDATE items SET ord = ord")
        with store._writing():
            store.conn.execute("UPDATE items SET ord = ord")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store.conn.execute("UPDATE items SET ord = ord")
    finally:
        store.close()


def test_no_checkpoint_outside_the_write_helper():
    """A source scan: the only `wal_checkpoint` in the module is `Store.checkpoint`, which runs it under
    `_writing` — a second write path around the lock would bring back the WAL-reset race (K32)."""
    import ast
    source = open(ls.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = ast.get_source_segment(source, node) or ""
            if "wal_checkpoint" in body:
                inner = [n for n in ast.walk(node) if isinstance(n, ast.FunctionDef) and n is not node]
                if not inner:
                    found.append((node.name, "self._writing(begin=False)" in body))
    code_lines = [l for l in source.splitlines() if "wal_checkpoint" in l and not l.strip().startswith("#")]
    assert found == [("checkpoint", True)], found
    assert len([l for l in code_lines if "execute(" in l]) == 1


_WRITER = """
import json, sys, time
from app import library_store as ls
db, lang, data, uf, out, n, mode = sys.argv[1:8]
store = ls.Store(db, lang, data, uf, "helper" if mode == "checkpoint" else "window")
spans = []
for i in range(int(n)):
    if mode == "checkpoint":
        with store._writing(begin=False):
            t0 = time.perf_counter(); store.conn.execute("PRAGMA wal_check" + "point(PASSIVE)").fetchall(); t1 = time.perf_counter()
    else:
        with store._writing():
            t0 = time.perf_counter(); store.conn.execute("UPDATE items SET ord = ord WHERE id = ?", (1 + i % 5,)); t1 = time.perf_counter()
    spans.append((t0, t1))
store.close()
json.dump(spans, open(out, "w"))
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_writers_and_a_checkpointer_never_overlap(language, tmp_path):
    """Two processes and two threads writing while one checkpoints: no two critical sections overlap."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    db = store.db_path
    store.close()
    procs = []
    for name, mode in (("p1", "write"), ("p2", "write"), ("cp", "checkpoint")):
        out = str(tmp_path / f"{name}.json")
        procs.append((out, subprocess.Popen([sys.executable, "-c", _WRITER, db, language, data_dir, user_files_dir,
                                             out, "60", mode], cwd=REPO, env=subprocess_env())))
    spans = []

    def thread_writer():
        s = ls.Store(db, language, data_dir, user_files_dir)
        for i in range(60):
            with s._writing():
                t0 = time.perf_counter()
                s.conn.execute("UPDATE items SET ord = ord WHERE id = ?", (2,))
                spans.append((t0, time.perf_counter()))
        s.close()

    threads = [threading.Thread(target=thread_writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for out, proc in procs:
        assert proc.wait(60) == 0
        spans += [tuple(s) for s in json.load(open(out))]
    spans.sort()
    assert len(spans) == 60 * 5
    for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
        assert b0 >= a1, "two critical sections overlapped"
    check = sqlite3.connect(db)
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_builder_holding_the_maintenance_lock_takes_the_write_lock(language):
    store = migrated(language)
    try:
        with ls.MaintenanceLock(store.db_path) as lock:
            assert lock.try_acquire()
            ids = store.ids("now")
            assert store.move([ids[0]], "now", after_id=ids[1]) is not None
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_process_opens_the_write_lock_file_once(language, monkeypatch):
    store = migrated(language)
    wlock = ls._write_lock_for(store.db_path)
    fd = wlock.file.fd
    opened = []
    real = os.open

    def spy(path, *a, **kw):
        if str(path).endswith(".wlock"):
            opened.append(path)
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "open", spy)
    data_dir, user_files_dir = roots(language)

    def writes():
        s = ls.open_store(language, data_dir, user_files_dir)
        ids = s.ids("soon")
        for i in range(10):
            s.move([ids[i % 3]], "soon", after_id=ids[3 + i % 3])
        s.close()

    threads = [threading.Thread(target=writes) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    writes()
    store.close()
    assert opened == [] and wlock.file.fd == fd is not None


@pytest.mark.parametrize("language", LANGUAGES)
def test_nested_commands_share_one_transaction(language):
    """`register` writes its pairing inside its own command: one BEGIN, one COMMIT, no deadlock; two
    threads each running nested commands both land, in turn."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    statements = []
    store.conn.set_trace_callback(statements.append)
    rel = "HighPriority/Hato/" + "新しい冒険.srt"
    from tests.test_library_store_support import touch
    touch(data_dir, rel)
    store.register(os.path.join(data_dir, rel), {"content_key": "k1", "video": "x"})
    store.conn.set_trace_callback(None)
    assert [s for s in statements if s.startswith(("BEGIN", "COMMIT"))] == ["BEGIN IMMEDIATE", "COMMIT"]
    store.close()
    errors = []

    def nested(n):
        try:
            s = ls.open_store(language, data_dir, user_files_dir)
            for i in range(5):
                r = f"HighPriority/Hato/{n}_{i}.srt"
                touch(data_dir, r)
                s.register(os.path.join(data_dir, r), {"content_key": f"t{n}-{i}"})
            s.close()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=nested, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors
    s = ls.open_store(language, data_dir, user_files_dir)
    assert s.conn.execute("SELECT COUNT(*) FROM pairings").fetchone()[0] == 11
    s.close()


# --- 5–7. keys and guards ------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_keys_are_stable_and_per_data_folder(language, tmp_path):
    data_dir, _u = roots(language)
    assert ls.library_db_path(language, data_dir) == ls.library_db_path(language, data_dir)
    other = str(tmp_path / "copy" / "data" / language)
    assert ls.library_db_path(language, other) != ls.library_db_path(language, data_dir)
    assert os.path.basename(ls.library_db_path(language, data_dir)).startswith(f"library_{language}_")


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS ignores case")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_case_only_rename_of_the_folder_keeps_the_key(language, tmp_path):
    folder = tmp_path / "Surasura" / "data"
    folder.mkdir(parents=True)
    before = ls.library_db_path(language, str(folder))
    os.rename(str(tmp_path / "Surasura"), str(tmp_path / "surasura"))
    assert ls.library_db_path(language, str(tmp_path / "surasura" / "DATA")) == before


def test_path_key_per_system():
    nfc = "第01話ガ.txt"
    import unicodedata
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    win = ls.path_key
    assert win("HighPriority/Ep01.srt", "win32") == win("HighPriority\\ep01.srt", "win32") == "highpriority/ep01.srt"
    assert win(nfc, "win32") != win(nfd, "win32")
    assert win("Ep01.srt", "darwin") == win("ep01.srt", "darwin")
    assert win(nfc, "darwin") == win(nfd, "darwin")
    keys = {win(p, "linux") for p in ("Ep01.srt", "ep01.srt", nfc, nfd)}
    assert len(keys) == 4
    assert win("./HighPriority/a.srt", "linux") == "HighPriority/a.srt"


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_test_root_under_pytest_the_store_raises(language, monkeypatch):
    data_dir, _u = roots(language)
    monkeypatch.delenv("SURASURA_TEST_ROOT")
    with pytest.raises(ls.StoreRefused, match="I7"):
        ls.library_db_path(language, data_dir)


def test_the_store_is_switched_on():
    """WP-L8: 2.5 keeps the library order in the store."""
    assert ls.STORE_LIVE is True


@pytest.mark.parametrize("language", LANGUAGES)
def test_store_live_false_refuses_without_a_test_root(language, monkeypatch, tmp_path):
    """The switch still works as one: off, every open refuses (the app runs in JSON mode, as 2.4)."""
    data_dir, user_files_dir = roots(language)
    # With no test root, maintain() takes its lock in the real local data folder: keep that folder in tmp_path
    # (conftest's _guard_real_local_data fails any test that creates the real one).
    monkeypatch.setattr(path_utils, "_local_data_root", lambda: str(tmp_path / "local_root"))
    monkeypatch.delenv("SURASURA_TEST_ROOT")
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(ls, "STORE_LIVE", False)
    with pytest.raises(ls.StoreRefused, match="STORE_LIVE"):
        ls.library_db_path(language, data_dir)
    with pytest.raises(ls.StoreRefused):
        ls.open_store(language, data_dir, user_files_dir)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_FAILED


# --- 8. schema ----------------------------------------------------------------------------------- #

def test_the_tier_check_names_equal_tiers():
    import re
    items_sql = [s for s in ls.SCHEMA_SQL if "CREATE TABLE items" in s][0]
    check = re.search(r"CHECK \(tier IN \(([^)]*)\)\)", items_sql).group(1)
    assert {n.strip(" '") for n in check.split(",")} == set(ls.TIERS)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_tier_check_refuses_finished(language):
    store = migrated(language)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with store._writing():
                store.conn.execute("UPDATE items SET tier = 'finished' WHERE id = 1")
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_tables_without_migrated_at_are_not_ready(language):
    data_dir, user_files_dir = roots(language)
    db = _db(language)
    store = ls._helper_store(db, language, data_dir, user_files_dir)
    ls._ensure_schema(store)
    store.close()
    assert ls.open_store(language, data_dir, user_files_dir) is None
    assert ls.check_mode(language, data_dir) == ("json", "not ready")


# --- 9. modes ------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_newer_schema_is_read_only(language):
    store = migrated(language)
    with store._writing():
        store.conn.execute(f"PRAGMA user_version = {ls.STORE_SCHEMA + 1}")
    store.close()
    data_dir, user_files_dir = roots(language)
    assert ls.check_mode(language, data_dir) == ("read-only", "made by a newer Surasura")
    assert ls.open_store(language, data_dir, user_files_dir) is None
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_damage_marker_is_read_only_in_every_process(language):
    store = migrated(language)
    ls.mark_damaged(store.db_path, "a test")
    with pytest.raises(ls.StoreReadOnly):
        store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    store.close()
    data_dir, _u = roots(language)
    script = f"from app import library_store as ls\nprint(ls.check_mode({language!r}, {data_dir!r})[0])"
    out = subprocess.run([sys.executable, "-c", script], cwd=REPO, env=subprocess_env(), capture_output=True,
                         text=True, timeout=60)
    assert out.stdout.strip() == "read-only"


def test_a_quick_check_that_raises_is_not_damage(tmp_path):
    class Exploding:
        def execute(self, sql):
            raise sqlite3.OperationalError("disk I/O error")

    db = str(tmp_path / "x.db")
    assert ls.quick_check(Exploding(), db) == "error"
    assert not os.path.exists(ls.damaged_marker(db))


def _corrupt_table(db_path, table):
    """Overwrite the root page of one table, leaving every other table readable."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    root = conn.execute("SELECT rootpage FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
    conn.close()
    with open(db_path, "r+b") as f:
        f.seek((root - 1) * page)
        f.write(b"\x0d\xff\xff\xff" + b"\xa5" * (page - 4))


@pytest.mark.parametrize("language", LANGUAGES)
def test_repair_salvages_table_by_table(language):
    """A damaged trash table beside a readable items table: the items come from the database (newer
    than the copy), the trash from the copy; the store_id kept; state_version above both; epoch + 1;
    the three files set aside, never deleted; exported without a re-import."""
    data_dir, user_files_dir = roots(language)
    store = migrated(language)
    ids = store.ids("goal")
    store.remove([ids[0]])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE      # the copy holds the trash row
    copy_trash = store.trash_rows()
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[3])     # the database is newer
    order_now = store.ids("now")
    before = store.meta()
    db = store.db_path
    store.close()
    _corrupt_table(db, "trash")
    probe = sqlite3.connect(db)
    assert probe.execute("SELECT COUNT(*) FROM items").fetchone()[0] > 0
    with pytest.raises(sqlite3.DatabaseError):
        probe.execute("SELECT * FROM trash").fetchall()
    probe.close()
    helper = ls.Store(db, language, data_dir, user_files_dir, "helper")
    assert ls.quick_check(helper.conn, db) == "damaged"
    helper.close()
    assert ls.check_mode(language, data_dir)[0] == "read-only"
    copy_before = os.stat(ls.manifest_path(user_files_dir)).st_mtime_ns
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    folder = os.path.dirname(db)
    aside = [f for f in os.listdir(folder) if ".corrupt." in f]
    assert any(f.endswith(tuple("0123456789")) for f in aside), aside            # the .db itself, kept
    assert not os.path.exists(ls.damaged_marker(db))
    store = ls.open_store(language, data_dir, user_files_dir)
    after = store.meta()
    assert after["store_id"] == before["store_id"]
    assert after["epoch"] == before["epoch"] + 1
    assert after["state_version"] > before["state_version"]
    assert store.ids("now") == order_now
    assert [r["item_id"] for r in store.trash_rows()] == [r["item_id"] for r in copy_trash]
    doc = json.load(open(ls.manifest_path(user_files_dir), encoding="utf-8"))
    assert doc["surasura_library"]["version"] == after["state_version"]
    assert os.stat(ls.manifest_path(user_files_dir)).st_mtime_ns != copy_before
    assert store.versions()["epoch"] == after["epoch"]
    store.close()


def _trash_copies(user_files_dir):
    trash = os.path.join(user_files_dir, ".trash")
    return [os.path.join(trash, f) for f in os.listdir(trash) if f.startswith("master_manifest.")]         if os.path.isdir(trash) else []


@pytest.mark.parametrize("language", LANGUAGES)
def test_repair_with_a_plain_manifest_and_an_unreadable_items_table_keeps_every_row(language):
    """Review R1: a damaged items table beside a plain manifest (the migration's backup put back, or an
    older version's save, no `surasura_library`) once built an EMPTY store and exported it over the
    manifest. Repair now takes the manifest's lists, as a migration does, and keeps the file in the trash
    before anything is written."""
    data_dir, user_files_dir = roots(language)
    store = migrated(language)                                 # exported: the copy carries surasura_library
    db = store.db_path
    store.close()
    doc = json.load(open(ls.manifest_path(user_files_dir), encoding="utf-8"))
    del doc["surasura_library"]
    write_manifest(user_files_dir, doc)
    plain = open(ls.manifest_path(user_files_dir), "rb").read()
    before = set(_trash_copies(user_files_dir))
    _corrupt_table(db, "items")
    ls.mark_damaged(db, "a test")
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    for tier, phase in (("now", "PHASE_1_NOW"), ("soon", "PHASE_2_SOON"), ("goal", "PHASE_3_LATER")):
        assert [e["physical_path"] for _i, e, _a in store.ordered(tier)] ==             [e["physical_path"] for e in doc["schedule"][phase]], tier
    store.close()
    kept = [f for f in _trash_copies(user_files_dir) if f not in before]
    assert any(open(f, "rb").read() == plain for f in kept), "the plain manifest is kept in the trash"
    exported = json.load(open(ls.manifest_path(user_files_dir), encoding="utf-8"))
    assert len(exported["schedule"]["PHASE_2_SOON"]) == len(doc["schedule"]["PHASE_2_SOON"]) > 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_repair_while_the_manifest_cannot_be_read_does_nothing(language, monkeypatch):
    """Review R1 (b): a manifest locked at that moment (antivirus, OneDrive) was read as "no copy": the
    repaired store came out empty and the next run exported it. Now Repair stops before renaming
    anything and is tried again."""
    data_dir, user_files_dir = roots(language)
    store = migrated(language)                                 # exported: the copy carries surasura_library
    db = store.db_path
    store.close()
    _corrupt_table(db, "items")
    ls.mark_damaged(db, "a test")
    manifest = open(ls.manifest_path(user_files_dir), "rb").read()

    def locked(path):
        raise ls.ManifestUnreadable("a sharing violation")
    with monkeypatch.context() as m:
        m.setattr(ls, "read_manifest", locked)
        assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_FAILED
    assert os.path.exists(db) and not [f for f in os.listdir(os.path.dirname(db)) if ".corrupt." in f]
    assert os.path.exists(ls.damaged_marker(db))
    assert open(ls.manifest_path(user_files_dir), "rb").read() == manifest
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert len(store.ids("soon")) > 0
    store.close()


# --- 10. upgrades -------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_upgrade_leaves_a_backup(language, monkeypatch):
    store = migrated(language)
    store.close()
    data_dir, user_files_dir = roots(language)
    monkeypatch.setattr(ls, "STORE_SCHEMA", ls.STORE_SCHEMA + 1)
    monkeypatch.setitem(ls._UPGRADES, ls.STORE_SCHEMA - 1,
                        lambda store: store.conn.execute("ALTER TABLE items ADD COLUMN upgraded INTEGER"))
    assert ls.check_mode(language, data_dir)[0] == "json"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = _db(language)
    assert [f for f in os.listdir(os.path.dirname(db)) if ".bak." in f]
    s = ls.open_store(language, data_dir, user_files_dir)
    assert s.conn.execute("PRAGMA user_version").fetchone()[0] == ls.STORE_SCHEMA
    assert "upgraded" in [r[1] for r in s.conn.execute("PRAGMA table_info(items)")]
    s.close()


# --- 11. 2.4.0's runtime ------------------------------------------------------------------------- #

def _internal_240():
    for candidate in (os.environ.get("SURASURA_240_INTERNAL"),
                      os.path.join(REPO, "dist", "Surasura", "_internal"),
                      os.path.join(REPO, "..", "..", "surasura", "dist", "Surasura", "_internal")):
        if candidate and os.path.isfile(os.path.join(candidate, "_sqlite3.pyd")):
            return os.path.abspath(candidate)
    return None


_RUNTIME = """
import os, sys
internal, repo, lib, data, uf, lang = sys.argv[1:7]
sys.path[:] = [repo, internal, lib]
os.environ["SURASURA_TEST_ROOT"] = os.path.dirname(os.path.dirname(data))
from app import library_store as ls
import sqlite3
assert ls.maintain(lang, data, uf) == ls.EXIT_DONE
store = ls.open_store(lang, data, uf)
ids = store.ids("now")
assert store.move([ids[0]], "now", after_id=ids[2]) is not None
store.close()
for name, mod in list(sys.modules.items()):
    f = getattr(mod, "__file__", None) or ""
    if f.endswith(".pyd"):
        assert os.path.abspath(f).startswith(internal), (name, f)
print("ok", sqlite3.sqlite_version)
"""


@pytest.mark.skipif(sys.platform != "win32" or _internal_240() is None, reason="needs 2.4.0's frozen _internal")
@pytest.mark.parametrize("language", LANGUAGES)
def test_imports_and_commits_with_2_4_0s_runtime(language):
    """2.5 installs in place through 2.4.0's updater, which keeps `_internal\\` (Python's extension
    modules and sqlite3.dll): the store must import, build and commit a move with exactly those."""
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    lib = os.path.join(sys.base_prefix, "Lib")
    out = subprocess.run([sys.executable, "-I", "-S", "-c", _RUNTIME, _internal_240(), REPO, lib, data_dir,
                          user_files_dir, language], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.startswith("ok 3.39.4"), out.stdout
