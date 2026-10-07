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
            try:
                barrier.wait()
                ti.open_store("ja", path=db).close()
            except Exception as e:
                errors.append(repr(e))
        threads = [threading.Thread(target=opener) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == [] and deleted == []


def test_a_damaged_store_is_still_rebuilt():
    """The corruption path stays for a file that really is damaged."""
    db = os.path.join(h.root(), "damaged.db")
    with open(db, "wb") as f:
        f.write(b"this is not a database" * 100)
    ti.open_store("ja", path=db).close()
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
