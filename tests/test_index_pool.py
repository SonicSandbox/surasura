"""The tokenizing pool (`app/token_index.py`) and two first opens of a new store — W1.3, the window's spec 04 §4.2;
research/11 row 11-W3; Minato's Inbox race (2026-10-05).

What a wrong answer would cost:
  * a different list — a token store built by the pool that differs from one built in one process by a single row: every
    word count, sentence, name candidate and piece must be the same, in Japanese and Chinese;
  * a store written in a different order, or by two writers — the parent alone writes, file by file in the files' order;
  * leftovers — the indexer killed mid-pool must leave the store as it was and no worker running;
  * a deleted store — two first opens at once (Generate and the indexer on a first run) read "database is locked" as
    corruption and deleted the file the other was making;
  * a laptop out of memory, or Generate's peak raised — the pool's size is capped, and only the indexer uses it.

Real files from tests/Test Resources (ja, zh), each test under its own root.
"""
import ctypes
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback

import pytest

from app import token_index as ti
from tests import services_helpers as h

ZH_FILES = ("chinese_text_1.txt", "traditional_news.txt", "mixed_script_transcript.txt")


def _library(lang, copies=10):
    """Real files, and `copies` more made from them (each rotated, so every file differs): enough for a pool."""
    folder = os.path.join(h.root(), "lib", lang)
    os.makedirs(folder, exist_ok=True)
    names = h.LIBRARY["ja"] if lang == "ja" else ZH_FILES
    paths = []
    for name in names:
        shutil.copy2(os.path.join(h.RESOURCES, lang, name), os.path.join(folder, name))
        paths.append(os.path.join(folder, name))
    source = "runaway_transcript.txt" if lang == "ja" else "traditional_news.txt"
    text = open(os.path.join(h.RESOURCES, lang, source), encoding="utf-8").read()
    for n in range(copies):
        path = os.path.join(folder, f"part_{n:03d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text[n * 53:] + text[: n * 53])
        paths.append(path)
    return paths


def _rows(db):
    """Every table's every row, in a fixed order."""
    conn = sqlite3.connect(db)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in tables}
    finally:
        conn.close()


def _build(lang, paths, workers, name):
    db = os.path.join(h.root(), f"{name}_{lang}.db")
    store = ti.open_store(lang, path=db)
    try:
        store.reconcile(paths, ti.make_tokenizer(lang), build_signature=ti.build_signature(lang, False, "asis"),
                        workers=workers)
    finally:
        store.close()
    return db


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_store_built_with_the_pool_equals_one_built_in_one_process_row_for_row(lang):
    paths = _library(lang)
    one = _rows(_build(lang, paths, 0, "one"))
    pooled = _rows(_build(lang, paths, 2, "pool"))
    assert set(one) == set(pooled)
    for table in one:
        assert pooled[table] == one[table], table
    assert len(one["files"]) == len(paths) and one["aggregate"]


def test_a_delta_after_a_change_is_the_same_too():
    """The second reconcile tokenizes only what changed: one file edited, one removed, one added — pool or not."""
    paths = _library("ja")
    dbs = {w: _build("ja", paths, w, f"delta{w}") for w in (0, 2)}
    with open(paths[3], "a", encoding="utf-8") as f:
        f.write("\n新しい行が増えました。\n")
    added = os.path.join(os.path.dirname(paths[0]), "added.txt")
    shutil.copy2(paths[1], added)
    later = [p for p in paths if p != paths[5]] + [added]
    for w, db in dbs.items():
        store = ti.open_store("ja", path=db)
        try:
            store.reconcile(later, ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja", False, "asis"),
                            workers=w)
        finally:
            store.close()
    assert _rows(dbs[0]) == _rows(dbs[2])


def test_a_file_that_cant_be_read_is_the_same_empty_row_in_a_worker():
    paths = _library("ja", copies=2)
    broken = os.path.join(os.path.dirname(paths[0]), "broken.epub")
    with open(broken, "wb") as f:
        f.write(b"not a zip at all")
    paths.append(broken)
    assert _rows(_build("ja", paths, 0, "b1")) == _rows(_build("ja", paths, 2, "b2"))


def test_the_workers_tokenize_with_the_parents_settings_not_a_fresh_read():
    """A setting the parent's run reads (here: the katakana names switch, as a test or a just-saved window changes it)
    reaches every worker: the pool's rows still equal one process's."""
    from app import analyzer
    paths = _library("ja", copies=4)
    saved = dict(analyzer.LOGIC)
    try:
        analyzer.LOGIC["names_katakana"] = not analyzer.LOGIC.get("names_katakana", True)
        assert _rows(_build("ja", paths, 0, "s1")) == _rows(_build("ja", paths, 2, "s2"))
    finally:
        analyzer.LOGIC.clear()
        analyzer.LOGIC.update(saved)


def test_the_workers_are_gone_before_the_reconcile_works_out_its_tables(monkeypatch):
    """The pool ends with the last file (W1.3 adversary #9): the names and phrase tables are worked out by the parent
    alone, never beside idle workers holding 67 MB each."""
    import multiprocessing
    seen = []
    real = ti.Store._update_names_tables

    def recording(self, *a, **k):
        seen.append(len(multiprocessing.active_children()))
        return real(self, *a, **k)
    monkeypatch.setattr(ti.Store, "_update_names_tables", recording)
    _build("ja", _library("ja", copies=6), 2, "gone")
    assert seen == [0]


# --- who uses it, and how big --------------------------------------------------------------------------------- #
@pytest.mark.parametrize("n,setting,cpus,free_mb,expected", [
    (400, None, 8, 8000, 4),        # the laptop: 4 cores / 8 threads
    (400, None, 4, 8000, 2),
    (400, None, 2, 8000, 1),        # two logical CPUs: no pool
    (400, None, 16, 8000, 4),       # never more than 4
    (400, None, 8, 600, 1),         # a quarter of 600 MB holds one worker: no pool
    (400, None, 8, 1000, 2),
    (30, None, 8, 8000, 1),         # too few files to pay for the workers' start
    (30, 3, 8, 8000, 3),            # the setting decides
    (400, 0, 8, 8000, 1),           # 0: one process
    (2, 4, 8, 8000, 2),             # never more workers than files
    (400, "x", 8, 8000, 4),         # a hand edit that isn't a number: automatic
    (5000, 10 ** 9, 8, 8000, 8),    # a hand edit asking for a billion: never more than the CPUs
    (400, 64, 8, 300, 1),           # …nor than half the free memory holds
])
def test_the_pools_size(n, setting, cpus, free_mb, expected):
    assert ti.pool_workers(n, setting, cpus=cpus, free_mb=free_mb) == expected


def test_only_the_indexer_pools_automatically():
    """None decides: one process unless this process holds the `indexer` lock (Generate keeps its memory budget)."""
    from app import locks
    seen = []
    tokenize = ti.make_tokenizer("ja")
    real = ti.pool_workers
    try:
        ti.pool_workers = lambda n, setting=None, **k: seen.append((n, setting)) or 1
        list(ti._tokenized(_library("ja", copies=1), tokenize, None))
        assert seen == []
        with locks.take("indexer", "indexing"):
            list(ti._tokenized(_library("ja", copies=1), tokenize, None))
        assert seen and seen[0][0] == 4
    finally:
        ti.pool_workers = real


def _indexer(*extra_env):
    env = dict(os.environ, PYTHONPATH=h.PROJECT_ROOT)
    env.pop("PYTEST_CURRENT_TEST", None)
    return subprocess.run([sys.executable, os.path.join(h.PROJECT_ROOT, "app", "indexer.py"), "--language", "ja"],
                          cwd=h.root(), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)


def test_the_indexer_uses_the_pool_from_the_setting_and_its_store_equals_one_processs(monkeypatch):
    folder = h.seed_library("ja", copies=6)
    h.write_settings({"target_language": "ja", "anki_connect_url": "http://127.0.0.1:9", "index_pool_workers": 2})
    proc = _indexer()
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0 and "Indexer: tokenizing 9 files in 2 processes." in out, out[-2000:]
    child_db = next(os.path.join(dp, f) for dp, _d, fs in os.walk(h.root()) for f in fs if f == "token_store_ja.db")
    files = sorted(os.path.join(folder, f) for f in os.listdir(folder))
    one = _rows(_build("ja", files, 0, "indexer_one"))
    pooled = _rows(child_db)
    for table in ("files", "aggregate", "bound"):
        assert pooled[table] == one[table], table


# --- killed mid-pool ---------------------------------------------------------------------------------------- #
_KILLED = r"""
import multiprocessing, os, sys, threading, time
from app import token_index as ti
folder = sys.argv[2]
paths = sorted(os.path.join(folder, f) for f in os.listdir(folder))
def report():
    while True:
        kids = multiprocessing.active_children()
        if len(kids) >= 2:
            print("workers", " ".join(str(k.pid) for k in kids), flush=True)
            return
        time.sleep(0.05)
threading.Thread(target=report, daemon=True).start()
store = ti.open_store("ja", path=sys.argv[1])
store.reconcile(paths, ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja", False, "asis"), workers=2)
print("finished", flush=True)
"""


def _alive(pid):
    """Whether a process is still running (Windows: its exit code is STILL_ACTIVE, 259)."""
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="the exit-code check is Windows'")
def test_the_indexer_killed_mid_pool_leaves_the_store_as_it_was_and_no_worker_running():
    paths = _library("ja", copies=400)
    db = _build("ja", paths[:3], 0, "killed")
    before = _rows(db)
    env = dict(os.environ, PYTHONPATH=h.PROJECT_ROOT)
    proc = subprocess.Popen([sys.executable, "-c", _KILLED, db, os.path.dirname(paths[0])], cwd=h.PROJECT_ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    seen = []
    while not (seen and seen[-1].startswith(("workers", "finished"))):
        seen.append(proc.stdout.readline().strip())
    assert seen[-1].startswith("workers"), seen
    pids = [int(p) for p in seen[-1].split()[1:]]
    proc.kill()                                              # the workers exist: inside the reconcile's transaction
    proc.wait(timeout=30)
    assert h.until(lambda: not any(_alive(pid) for pid in pids), seconds=60), "a worker outlived the indexer"
    assert _rows(db) == before


# --- two first opens at once ---------------------------------------------------------------------------------- #
def test_two_first_opens_at_once_never_delete_the_store(monkeypatch):
    """Minato's reproduction (2–3 % of two-thread first opens failed before the fix): 300 new stores, each opened by two
    threads in the same moment. None fails, and none is deleted as corrupt."""
    deleted = []
    real_delete = ti._delete_db
    monkeypatch.setattr(ti, "_delete_db", lambda path: (deleted.append(path), real_delete(path)))
    errors = []
    for i in range(300):
        db = os.path.join(h.root(), "race", str(i), "shared.db")
        os.makedirs(os.path.dirname(db))
        barrier = threading.Barrier(2)

        def opener():
            began = None
            try:
                barrier.wait()
                began = time.monotonic()
                ti.open_store("ja", path=db).close()
            except Exception:
                # where it failed and after how long (5 s: the busy wait ran out; at once: a refusal SQLite never
                # waits on) — a load flake on 2026-10-15 left only "database is locked" to read
                errors.append(f"after {time.monotonic() - (began or time.monotonic()):.3f} s: {traceback.format_exc()}")
        threads = [threading.Thread(target=opener) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == [] and deleted == []


@pytest.mark.parametrize("hold_at", ["CREATE INDEX", "PRAGMA user_version ="])
def test_a_second_first_open_mid_rebuild_never_drops_the_firsts_tables(monkeypatch, hold_at):
    """The load-flakes review's row 3, stepped by hand (no sleeps): A's first open is held mid-build — after its CREATE
    TABLE aggregate and before its CREATE INDEX on it, or before it writes the version — and B's first open then runs. Before the fix B read user_version 0
    too and ran the drops, A's CREATE INDEX met "no such table: main.aggregate", and open_store deleted the store as
    damaged. Now the build runs inside BEGIN IMMEDIATE and user_version is read again inside the lock: B waits, then
    finds A's finished store and builds nothing (the version written after the lock is let go would let B build again).
    Both opens succeed, nothing is deleted, the store is whole."""
    db = os.path.join(h.root(), "stepped", "shared.db")
    os.makedirs(os.path.dirname(db))
    deleted = []
    real_delete = ti._delete_db
    monkeypatch.setattr(ti, "_delete_db", lambda path: (deleted.append(path), real_delete(path)))
    a_held, b_asked, a_done = threading.Event(), threading.Event(), threading.Event()
    seen = {"A": [], "B": []}
    real_connect = sqlite3.connect

    def trace(sql):
        # runs on the thread stepping the statement, before the statement takes any lock
        who = threading.current_thread().name
        if who not in seen:
            return
        seen[who].append(sql)
        if who == "A" and hold_at in sql and not a_held.is_set():
            a_held.set()
            b_asked.wait(30)                    # B has asked for the write lock (fixed) or dropped A's tables (bug)
        elif who == "B" and ("BEGIN IMMEDIATE" in sql or "DROP TABLE IF EXISTS bound" in sql):
            b_asked.set()
            if "DROP" in sql:
                a_done.wait(30)                 # the bug: B's drop of aggregate (the statement before) has landed

    def connect(*args, **kwargs):
        c = real_connect(*args, **kwargs)
        c.set_trace_callback(trace)
        return c
    monkeypatch.setattr(sqlite3, "connect", connect)
    errors = {}

    def opener():
        who = threading.current_thread().name
        try:
            ti.open_store("ja", path=db).close()
        except Exception:
            errors[who] = traceback.format_exc()
        finally:
            if who == "A":
                a_done.set()
    a = threading.Thread(target=opener, name="A")
    a.start()
    assert a_held.wait(30), f"A never reached {hold_at}"
    b = threading.Thread(target=opener, name="B")
    b.start()
    a.join(60)
    b.join(60)
    assert not a.is_alive() and not b.is_alive()
    assert errors == {} and deleted == []
    assert not any(s.lstrip().startswith(("DROP", "CREATE")) for s in seen["B"]), "B built over A's store"
    conn = real_connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert {"files", "aggregate", "bound", "meta", "idx_aggregate_count"} <= names
    finally:
        conn.close()


def test_the_journal_switch_commits_at_synchronous_normal(monkeypatch):
    """The review's row 4: a new file's switch to WAL is a rollback-mode commit; at the default synchronous=FULL it
    fsyncs a journal for each attempt, and under an fsync storm one attempt's wait can use the loop's whole 5 s. NORMAL
    is set before the switch."""
    statements = []
    real_connect = sqlite3.connect
    me = threading.current_thread()

    def connect(*args, **kwargs):
        c = real_connect(*args, **kwargs)
        if threading.current_thread() is me:            # this test's open only, never a thread left by another test
            c.set_trace_callback(statements.append)
        return c
    monkeypatch.setattr(sqlite3, "connect", connect)
    db = os.path.join(h.root(), "sync", "new.db")
    os.makedirs(os.path.dirname(db))
    ti.open_store("ja", path=db).close()
    pragmas = [s for s in statements if s.startswith("PRAGMA synchronous") or s.startswith("PRAGMA journal_mode")]
    assert pragmas[:2] == ["PRAGMA synchronous=NORMAL", "PRAGMA journal_mode=WAL"]


@pytest.mark.parametrize("table", ["files", "aggregate", "bound", "meta"])
def test_a_store_at_the_version_missing_a_table_is_built_again(tmp_path, table):
    """The half-built guard, looked at outside the lock and again inside it: user_version says this schema, but a table
    is gone (a build cut short by an older copy, or a hand edit) — the open builds the schema again instead of handing
    out a store whose first read fails."""
    db = str(tmp_path / "half.db")
    ti.open_store("ja", path=db).close()
    conn = sqlite3.connect(db)
    conn.execute(f"DROP TABLE {table}")
    conn.commit()
    conn.close()
    store = ti.open_store("ja", path=db)
    try:
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
    finally:
        store.close()


def test_a_busy_look_at_a_current_store_is_raised_and_never_builds_it_again(tmp_path, monkeypatch):
    """The half-built check reads "no such table" as not ready, and nothing else: a busy answer to its look at a store
    at this version is raised (open_store never deletes on it) — never read as "build it again", which drops every
    table and its rows."""
    db = str(tmp_path / "current.db")
    store = ti.open_store("ja", path=db)
    store.set_meta("kept", "yes")
    store.close()
    real_connect = sqlite3.connect

    class Busy(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("SELECT 1 FROM aggregate"):
                raise sqlite3.OperationalError("database is locked")
            return super().execute(sql, *args)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: real_connect(*a, factory=Busy, **kw))
    deleted = []
    monkeypatch.setattr(ti, "_delete_db", deleted.append)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        ti.open_store("ja", path=db)
    monkeypatch.setattr(sqlite3, "connect", real_connect)
    store = ti.open_store("ja", path=db)
    try:
        assert deleted == [] and store.get_meta("kept") == "yes"
    finally:
        store.close()


def test_a_locked_store_is_never_deleted(tmp_path, monkeypatch):
    """Busy is not damage: an open that meets "database is locked" while it builds raises it and leaves the file."""
    db = str(tmp_path / "busy.db")
    ti.open_store("ja", path=db).close()
    deleted = []
    monkeypatch.setattr(ti, "_delete_db", deleted.append)

    def busy(conn):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(ti, "_ensure_schema", busy)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        ti.open_store("ja", path=db)
    assert deleted == [] and os.path.exists(db)


def test_a_damaged_store_is_still_rebuilt():
    """The corruption path stays for a file that really is damaged."""
    db = os.path.join(h.root(), "damaged.db")
    with open(db, "wb") as f:
        f.write(b"this is not a database" * 100)
    ti.open_store("ja", path=db).close()
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION


# --- only real damage drops a store (follow-up (b) of the first-open race) ---------------------------------------- #
def _sqlite_error(cls, text, code, name):
    """An error as SQLite's own carry it (Python 3.11: `sqlite_errorcode` / `sqlite_errorname`); `code` None: one raised
    by hand, read by its text alone."""
    error = cls(text)
    if code is not None:
        error.sqlite_errorcode, error.sqlite_errorname = code, name
    return error


def _failing_connect(monkeypatch, at, error, times=1):
    """sqlite3.connect whose connections raise `error` at the first `times` statements starting with `at`; the count."""
    real_connect = sqlite3.connect
    raised = []

    class Failing(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith(at) and len(raised) < times:
                raised.append(sql)
                raise error
            return super().execute(sql, *args)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: real_connect(*a, factory=Failing, **kw))
    return raised


def _store_with_a_row(db):
    store = ti.open_store("ja", path=db)
    store.set_meta("kept", "yes")
    store.close()


NOT_DAMAGE = [
    pytest.param(sqlite3.OperationalError, "disk I/O error", 266, "SQLITE_IOERR_READ", id="io-error"),
    pytest.param(sqlite3.OperationalError, "disk I/O error", 778, "SQLITE_IOERR_WRITE", id="io-write-error"),
    pytest.param(sqlite3.OperationalError, "database or disk is full", 13, "SQLITE_FULL", id="disk-full"),
    pytest.param(sqlite3.OperationalError, "locking protocol", 15, "SQLITE_PROTOCOL", id="locking-protocol"),
]


@pytest.mark.parametrize("coded", [True, False], ids=["coded", "by-text"])
@pytest.mark.parametrize("cls, text, code, name", NOT_DAMAGE)
def test_a_disk_or_locking_error_at_the_open_is_raised_and_never_deletes_the_store(tmp_path, monkeypatch,
                                                                                  cls, text, code, name, coded):
    """A full disk, a disk I/O error or SQLite's "locking protocol" (the WAL index changing as it looked) says nothing of
    the file: met at the open's look at a current store, it is raised and the store is kept — before, every database
    error but "locked" deleted it, and a passing I/O error cost a whole library's tokens. The next open, the error gone,
    reads the store as it was. Read by its code, and by its text when raised by hand."""
    db = str(tmp_path / "current.db")
    _store_with_a_row(db)
    deleted = []
    monkeypatch.setattr(ti, "_delete_db", lambda path: deleted.append(path))
    raised = _failing_connect(monkeypatch, "SELECT 1 FROM aggregate",
                              _sqlite_error(cls, text, code if coded else None, name))
    with pytest.raises(cls, match=text):
        ti.open_store("ja", path=db)
    assert raised and deleted == []
    monkeypatch.undo()
    store = ti.open_store("ja", path=db)
    try:
        assert store.get_meta("kept") == "yes"
    finally:
        store.close()


def test_a_full_disk_while_an_old_store_is_built_again_is_raised_and_keeps_the_file(tmp_path, monkeypatch):
    """A real SQLITE_FULL: a store from an older version is built again at the open, and the disk can't take the new
    tables (SQLite's page cap stands in for the full disk). The build rolls back and the error is raised; the file is
    not deleted — a full disk never deletes a store (the brief's rule; this one's rows are old, and the next good open
    drops them) — and the rollback leaves it as it was."""
    db = str(tmp_path / "old.db")
    old = sqlite3.connect(db)
    old.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    old.execute("INSERT INTO meta VALUES ('kept', 'yes')")
    old.execute(f"PRAGMA user_version = {ti.SCHEMA_VERSION - 1}")
    old.commit()
    pages = old.execute("PRAGMA page_count").fetchone()[0]
    old.close()
    deleted = []
    monkeypatch.setattr(ti, "_delete_db", lambda path: deleted.append(path))
    real_connect = sqlite3.connect

    def capped(*a, **kw):
        c = real_connect(*a, **kw)
        c.execute(f"PRAGMA max_page_count = {pages}")      # no room for one more page
        return c
    monkeypatch.setattr(sqlite3, "connect", capped)
    with pytest.raises(sqlite3.OperationalError) as caught:
        ti.open_store("ja", path=db)
    assert caught.value.sqlite_errorcode & 0xFF == 13 and deleted == []
    monkeypatch.undo()
    kept = sqlite3.connect(db)
    try:
        assert kept.execute("SELECT value FROM meta WHERE key = 'kept'").fetchone() == ("yes",)
    finally:
        kept.close()


@pytest.mark.parametrize("coded", [True, False], ids=["coded", "by-text"])
def test_a_locking_protocol_answer_to_the_wal_switch_is_asked_again(tmp_path, monkeypatch, coded):
    """SQLITE_PROTOCOL is SQLite's "try again" (the WAL index moved under it): the new file's switch to WAL waits on it
    as on "locked" and asks again — the open succeeds and deletes nothing. Before, the busy check missed it: the open
    deleted the file as damaged. By its code, and by its text when raised by hand."""
    db = str(tmp_path / "new.db")
    deleted = []
    monkeypatch.setattr(ti, "_delete_db", lambda path: deleted.append(path))
    raised = _failing_connect(monkeypatch, "PRAGMA journal_mode=WAL", _sqlite_error(
        sqlite3.OperationalError, "locking protocol", 15 if coded else None, "SQLITE_PROTOCOL"), times=2)
    ti.open_store("ja", path=db).close()
    assert len(raised) == 2 and deleted == []
    monkeypatch.undo()
    c = sqlite3.connect(db)
    try:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
    finally:
        c.close()


DAMAGE = [
    pytest.param(sqlite3.DatabaseError, "database disk image is malformed", 779, "SQLITE_CORRUPT_INDEX", id="corrupt"),
    pytest.param(sqlite3.DatabaseError, "database disk image is malformed", None, None, id="corrupt-by-text"),
    pytest.param(sqlite3.DatabaseError, "malformed database schema (files)", None, None, id="schema-by-text"),
]


@pytest.mark.parametrize("cls, text, code, name", DAMAGE)
def test_a_corrupt_store_is_still_deleted_and_built_again(tmp_path, monkeypatch, cls, text, code, name):
    """Real damage keeps its path: SQLITE_CORRUPT ("database disk image is malformed"; here its extended code, an index
    found damaged) met at the open deletes the store and builds it again — by its code, and by its text when raised by
    hand (SQLite's own words for it)."""
    db = str(tmp_path / "corrupt.db")
    _store_with_a_row(db)
    deleted = []
    real_delete = ti._delete_db
    monkeypatch.setattr(ti, "_delete_db", lambda path: (deleted.append(path), real_delete(path)))
    _failing_connect(monkeypatch, "SELECT 1 FROM aggregate", _sqlite_error(cls, text, code, name))
    store = ti.open_store("ja", path=db)
    try:
        assert deleted == [db] and store.get_meta("kept") is None
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
    finally:
        store.close()


@pytest.mark.parametrize("coded", [True, False], ids=["coded", "by-text"])
def test_an_error_is_read_by_its_code_before_its_text(tmp_path, monkeypatch, coded):
    """The code decides when SQLite gives one: "malformed JSON" is SQLITE_ERROR (a bad argument to a JSON function),
    no damage to the file, though its text says "malformed" — raised, the store kept. Without a code, only SQLite's own
    words for damage count, so it is raised then too."""
    db = str(tmp_path / "current.db")
    _store_with_a_row(db)
    deleted = []
    monkeypatch.setattr(ti, "_delete_db", lambda path: deleted.append(path))
    _failing_connect(monkeypatch, "SELECT 1 FROM aggregate", _sqlite_error(
        sqlite3.OperationalError, "malformed JSON", 1 if coded else None, "SQLITE_ERROR"))
    with pytest.raises(sqlite3.OperationalError, match="malformed JSON"):
        ti.open_store("ja", path=db)
    assert deleted == []
    monkeypatch.undo()
    store = ti.open_store("ja", path=db)
    try:
        assert store.get_meta("kept") == "yes"
    finally:
        store.close()
