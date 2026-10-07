"""Shared helpers for the library store's tests (`app/library_store.py`, L1.2). No tests here.

Every library these build is synthetic and lives under the per-test SURASURA_TEST_ROOT that
tests/conftest.py sets (never the user's `User Files/`, `data/` or `results/`). File and show names are
real Japanese and Chinese words taken from tests/Test Resources/ (ja = zh: every proof runs for both).
"""

import json
import os
import re
import time

from app import library_store as ls

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
LANGUAGES = ("ja", "zh")
_CJK = re.compile(r"[ぁ-ヿ㐀-鿿]{2,6}")
_NAMES = {}


def names(language):
    """Distinct words of 2–6 Japanese or Chinese characters from the language's real test texts, in the
    order they first appear: show names, episode titles."""
    if language not in _NAMES:
        seen = []
        folder = os.path.join(RESOURCES, language)
        for fname in sorted(os.listdir(folder)):
            if not fname.endswith((".txt", ".srt")):
                continue
            with open(os.path.join(folder, fname), encoding="utf-8", errors="replace") as f:
                for word in _CJK.findall(f.read()):
                    if word not in seen:
                        seen.append(word)
        _NAMES[language] = seen
    return _NAMES[language]


def roots(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    return (os.path.join(root, "data", language), os.path.join(root, "User Files", language))


def touch(data_dir, rel, text=None):
    """A content file with a line of real text (its size tells files apart, like real subtitles)."""
    path = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text is not None else f"{rel}\n")
    return path


def entry(rel, origin="Manual Import", source_type="subtitle"):
    return ls.make_entry(rel, origin, source_type if rel.endswith(".srt") else "text")


def write_manifest(user_files_dir, doc):
    """As today's `save_manifest` writes it: indent=2, raw UTF-8, text mode (CRLF on Windows).

    The store knows its own copy by its stat (mtime + size, §6.7). A real outside writer comes seconds after the
    copy it replaces; here it can come within one clock tick (GitHub's runner ticks every 15.6 ms) at the same size
    (a move only reorders), and the store would take it for its own copy, unchanged. So it's written again until
    its stat differs from the file it replaced."""
    os.makedirs(user_files_dir, exist_ok=True)
    path = ls.manifest_path(user_files_dir)
    before = ls._stat(path)
    deadline = time.perf_counter() + 1
    while True:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        if before is None or ls._stat_str(ls._stat(path)) != ls._stat_str(before):
            return path
        assert time.perf_counter() < deadline, "the clock never moved"
        time.sleep(0.001)


def read_doc(user_files_dir):
    with open(ls.manifest_path(user_files_dir), encoding="utf-8-sig") as f:
        return json.load(f)


def library(language, shows=3, episodes=4, loose=1, tiers=("now", "soon", "goal"), create=True):
    """A small library whose folders match their tiers: per tier, `shows` show folders of `episodes`
    episodes and `loose` loose files, named with real words. Returns (data_dir, user_files_dir, doc)."""
    data_dir, user_files_dir = roots(language)
    words = names(language)
    n = 0
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for tier in tiers:
        folder = ls.FOLDER_OF_TIER[tier]
        rows = []
        for s in range(shows):
            show = words[n % len(words)]
            n += 1
            for e in range(1, episodes + 1):
                rel = f"{folder}/{show}/{show}_第{e:02d}話.srt"
                if create:
                    touch(data_dir, rel, f"{show} {e}\n")
                rows.append(entry(rel))
        for i in range(loose):
            word = words[n % len(words)]
            n += 1
            rel = f"{folder}/{word}.txt"
            if create:
                touch(data_dir, rel, f"{word}\n")
            rows.append(entry(rel))
        doc["schedule"][ls.TIERS[tier][0]] = rows
    return data_dir, user_files_dir, doc


def migrated(language, **kw):
    """A library migrated into a fresh store; returns an open Store (role 'window')."""
    data_dir, user_files_dir, doc = library(language, **kw)
    write_manifest(user_files_dir, doc)
    code = ls.maintain(language, data_dir, user_files_dir)
    assert code == ls.EXIT_DONE, code
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store is not None
    return store


def paths(store, tier):
    return [e["physical_path"] for _i, e, _a in store.ordered(tier)]


def schema1_store(language, doc):
    """A 2.5–2.7 store (schema 1) as their migration left it, under the test root: the v1 tables (`SCHEMA_SQL`, which
    the store module keeps as 2.5 wrote them) and the made-words table 2.6 adds; each manifest row an item keyed 1024,
    2048, … per tier with ids 1, 2, …; 2.5's pieces (runs of one folder); 2.x's meta (New arrivals off, no Soon line,
    no works). The manifest is written and recorded as the store's copy. Returns (data_dir, user_files_dir, db)."""
    import sqlite3
    import uuid
    data_dir, user_files_dir = roots(language)
    path = write_manifest(user_files_dir, doc)
    db = ls.library_db_path(language, data_dir)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    norm = ls.normalise(doc)
    image = ls._image_from_manifest(norm, data_dir)
    now = ls._now()
    conn = sqlite3.connect(db, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN")
        for sql in ls.SCHEMA_SQL + ls.ADDED_TABLES_SQL:
            conn.execute(sql)
        conn.execute("INSERT INTO roots (id, kind, path, created_at) VALUES (1, 'library', NULL, ?)", (now,))
        conn.executemany("INSERT INTO pieces (id, title, kind, created_at) VALUES (?, ?, ?, ?)",
                         image["tables"]["pieces"]["rows"])
        position = {}
        for n, item in enumerate(image["items"], 1):
            position[item["tier"]] = position.get(item["tier"], 0) + 1
            title, folder, source_type = ls._columns(item["entry"])
            conn.execute(
                "INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, source_type, "
                "availability, size, mtime_ns, changed_in, added_at, piece_id) "
                "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (n, item["rel_path"], item["rel_key"], item["tier"], ls.STEP * position[item["tier"]],
                 ls._dumps(item["entry"]), title, folder, source_type, item["availability"], item["size"],
                 item["mtime_ns"], now, item["piece_id"]))
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('items', ?)", (len(image["items"]),))
        meta = ls._fresh_meta(uuid.uuid4().hex, 1, 1)
        meta.update(ls._manifest_meta(norm))
        meta.update({"arrivals_on": 0, "migrated_at": now, "last_export_stat": ls._stat_str(os.stat(path))})
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
        conn.execute("PRAGMA user_version = 1")
        conn.execute("COMMIT")
    finally:
        conn.close()
    return data_dir, user_files_dir, db


def no_line(store):
    """2.x's placement, line-free: the Soon line's key taken out, so the tiers no longer follow it (schema 2 always
    holds one). Only for the tests that hold the store's placement to 2.4's frozen code; the line's own rule, on top of
    every command, is tested in test_library_store_commands.py (the Soon line)."""
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = 'soon_line'")
    return store


def arrivals_off(store):
    """New arrivals switched off (the user's library option, `set_library_options`): hato's drops land at the top of
    NOW as through 2.x (Q4-11). 3.0 builds every library with them on (D30)."""
    store.set_library_options(arrivals_on=False)
    return store


def pieces_ok(store):
    """None when every piece is one contiguous run of one work's items in one tier and every item has a work and a
    piece (L2.2 05 §5.2 rule 1); else what's wrong."""
    return ls._pieces_ok(store.conn) or ls._works_ok(store.conn)


def subprocess_env():
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def big_store(language, n, available=True):
    """A synthetic store of `n` items built in one transaction, the 100k shape the reviews measured
    (NOW 1 %, Soon 44.5 %, 6+ Months the rest), names from the real word list. No files on disk:
    availability is set as asked, so the mine line counts them."""
    data_dir, user_files_dir = roots(language)
    db = ls.library_db_path(language, data_dir)
    store = ls._helper_store(db, language, data_dir, user_files_dir)
    ls._ensure_schema(store)
    words = names(language)
    now, soon = max(20, n // 100), int(n * 0.445)
    items = []
    for i in range(n):
        tier = "now" if i < now else "soon" if i < now + soon else "goal"
        show = words[(i // 12) % len(words)]
        rel = f"{ls.FOLDER_OF_TIER[tier]}/{show}{i // 12}/{show}_{i:06d}.srt"
        item = ls._item_from_entry(ls.make_entry(rel, "Disk Sync", "subtitle"), tier, data_dir, ls._now())
        if available:
            item["availability"], item["size"], item["mtime_ns"] = "available", 100, 1
        items.append(item)
    meta = ls._fresh_meta("bench" + language, 1, 1)
    with store._writing():
        ls._write_image(store, {"items": items, "tables": {}}, meta)
        store._set_meta({"migrated_at": ls._now()})
    store.close()
    return ls.open_store(language, data_dir, user_files_dir)


def _episodes(language, prefix, count, start=0):
    """`count` episode paths under `prefix`, 12 to a show, shows named from the real word list."""
    words = names(language)
    mark = "話" if language == "ja" else "集"
    out = []
    for n in range(start, start + count):
        show = f"{words[(n // 12) % len(words)]}{n // 12:03d}"
        out.append(f"{prefix}/{show}/{show}_第{n % 12 + 1:02d}{mark}.srt")
    return out


def _ia(entry, n):
    """The retired Immersion Architect's keys, as 1,818 laptop rows carry them."""
    entry["reason"] = f"Planned for week {n % 52 + 1}: density band {n % 7}, coverage {(n * 37) % 100}%"
    entry["metrics"] = {"unknown_words": (n * 13) % 400, "density": round((n % 97) / 97, 4),
                        "i_plus_one": (n * 7) % 60, "coverage": round((n % 89) / 89, 4)}
    entry["simulated_day_start"] = n % 365
    entry["simulated_day_end"] = n % 365 + 3
    return entry


def laptop_library(language, create=True):
    """The laptop-shaped fixture (L0.1, store spec §4.1), synthetic — never the user's titles: 2,034 rows
    (NOW 143 · Soon 154 · 6+ Months 1,737), 267 dead rows (NOW 50, 6+ Months 217), 851 rows in another
    tier's folder (810 LowPriority files filed in 6+ Months, 41 HighPriority files in Soon with status
    "overflow"), 53 doubled titles (the same inner path and size in LowPriority and GoalContent, both rows
    live), 1,818 rows with the Immersion Architect's keys, folders split into several runs; on disk
    134 / 923 / 710 content files. Returns (data_dir, user_files_dir, doc)."""
    data_dir, user_files_dir = roots(language)
    high = _episodes(language, "HighPriority", 93 + 50 + 41)
    now_live, now_dead, overflow = high[:93], high[93:143], high[143:]
    low = _episodes(language, "LowPriority", 113 + 810, start=1000)
    soon_low, later_low = low[:113], low[113:]
    goal = _episodes(language, "GoalContent", 710 + 217, start=3000)
    goal_live, goal_dead = goal[:710], goal[710:]
    for n in range(53):                                        # doubled titles: same inner path, both live
        goal_live[n] = "GoalContent/" + later_low[n].split("/", 1)[1]
    status = {}
    for rel in overflow:
        status[rel] = "overflow"
    for rel in (now_live + now_dead)[:143] + soon_low[:71]:
        status[rel] = "New"

    def row(rel, n, origin, ia=False):
        e = entry(rel, origin)
        e["status"] = status.get(rel, "active")
        e["type"] = "book_chapter" if ia else "File"
        return _ia(e, n) if ia else e

    later = later_low + goal_live + goal_dead
    chunks = [later[i:i + 7] for i in range(0, len(later), 7)]  # 7 of a 12-episode show: shows split in runs
    order = [c for pair in zip(chunks[0::2], chunks[1::2]) for c in pair[::-1]] + \
        ([chunks[-1]] if len(chunks) % 2 else [])
    later = [rel for c in order for rel in c]
    schedule = {
        "PHASE_1_NOW": [row(r, n, "01_NOW") for n, r in enumerate(now_live + now_dead)],
        "PHASE_2_SOON": [row(r, n, "02_SOON", ia=n < 81) for n, r in enumerate(overflow + soon_low)],
        "PHASE_3_LATER": [row(r, n, "03_LATER", ia=True) for n, r in enumerate(later)],
    }
    doc = {"metadata": {"generated_at": "2026-06-12", "strategy": "smart_sort", "days": 365, "version": 3},
           "schedule": schedule}
    if create:
        dead = set(now_dead + goal_dead)
        sizes = {}
        for rel in now_live + overflow + soon_low + later_low + goal_live:
            if rel in dead:
                continue
            inner = rel.split("/", 1)[1]
            text = sizes.setdefault(inner, f"{inner}\n")         # a doubled title has the same size twice
            touch(data_dir, rel, text)
    return data_dir, user_files_dir, doc
