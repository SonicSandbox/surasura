"""The store's schema 2 (L3.1 row 3.1.1; the L2.2 pack 02 §2.3–2.7): the upgrade of a live 2.5–2.7 store, and what
every build now seeds — works, pieces, search keys and the feed.

Why these matter: every 2.5–2.7 user's library order lives in a schema-1 store with real orders, pins and watched
marks in it. The upgrade runs once, in the helper, and must change none of that: the same ids, tiers, order, pins and
watched marks, and the same Generate output (Q2-4: nobody's list changes at the switch). A failure, or a check that
finds any difference, rolls the whole step back and leaves a `.bak` (02 §2.6 #6). Works are found by the folder below
the tier folder, so one show split across tier folders (the laptop library has 53) is one title; pieces become
contiguous runs of one work in one tier. Every test runs for Japanese and Chinese, under the per-test
SURASURA_TEST_ROOT, with real words from tests/Test Resources/.
"""

import json
import os
import sqlite3
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, library, names, pieces_ok, read_doc, roots, schema1_store,
                                              touch, write_manifest)

BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"


def _upgrade(language):
    data_dir, user_files_dir = roots(language)
    assert ls.check_mode(language, data_dir)[0] == "json", "a schema-1 store reads as not ready until the helper runs"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store is not None
    return store


def _raw(db):
    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _snapshot(conn):
    return conn.execute("SELECT id, tier, ord, pinned, watched FROM items ORDER BY tier, ord, id").fetchall()


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_to_2_keeps_every_order_tier_and_id(language):
    """A live 2.x store — moves made, a pin, watched marks — upgraded: every id, (tier, ord), pin and watched mark is
    identical; the epoch stays (a window's undo survives); `state_version` moves by one; user_version 2."""
    _d, _u, doc = library(language, shows=3, episodes=4)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    conn = _raw(db)
    ids = [r[0] for r in conn.execute("SELECT id FROM items WHERE tier = 'soon' ORDER BY ord")]
    conn.execute("UPDATE items SET ord = -5 WHERE id = ?", (ids[-1],))           # a drag to the top, as 2.5 keyed it
    conn.execute("UPDATE items SET tier = 'now', ord = 99999 WHERE id = ?", (ids[0],))   # a promote to NOW's end
    conn.execute("UPDATE items SET pinned = '2026-10-05T10:00:00.000000Z' WHERE id = ?", (ids[1],))
    conn.execute("UPDATE items SET watched = 1 WHERE id IN (?, ?)", (ids[2], ids[3]))
    before = _snapshot(conn)
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    conn.close()
    store = _upgrade(language)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert _snapshot(store.conn) == before
    after = store.meta()
    assert str(after["epoch"]) == meta["epoch"] and after["state_version"] == int(meta["state_version"]) + 1
    assert pieces_ok(store) is None
    assert not after.get("upgrade_failed")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_seeds_one_work_per_title_folder_across_tiers(language):
    """02 §2.6 step 2: the folder below the tier folder is the title — one show in NOW's and 6+ Months' folders is one
    work (L0.1: shows split across tier folders); `A/Season 1` and `B/Season 1` stay two; a loose file is a work of its
    own, titled by its title."""
    w = names(language)
    data_dir, user_files_dir = roots(language)
    rels = {"now": [f"HighPriority/{w[1]}/{w[1]}_01.srt", f"HighPriority/{w[2]}/Season 1/{w[2]}_01.srt",
                    f"HighPriority/{w[4]}.txt"],
            "goal": [f"GoalContent/{w[1]}/{w[1]}_02.srt", f"GoalContent/{w[3]}/Season 1/{w[3]}_01.srt"]}
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for tier, paths in rels.items():
        for rel in paths:
            touch(data_dir, rel)
            doc["schedule"][ls.TIERS[tier][0]].append(ls.make_entry(rel, "Manual Import", "subtitle"))
    schema1_store(language, doc)
    store = _upgrade(language)
    work = {store.item(store.item_id(r))["rel_path"]: store.item(store.item_id(r))["work_id"]
            for paths in rels.values() for r in paths}
    assert work[rels["now"][0]] == work[rels["goal"][0]], "one show across two tier folders: one title"
    assert work[rels["now"][1]] != work[rels["goal"][1]], "A/Season 1 and B/Season 1: two titles"
    assert len(set(work.values())) == 4
    titles = dict(store.conn.execute("SELECT id, title FROM works"))
    assert titles[work[rels["now"][0]]] == w[1] and titles[work[rels["now"][1]]] == f"{w[2]}/Season 1"
    assert titles[work[rels["now"][2]]] == f"{w[4]}.txt", "a loose file: its own title"
    store.close()


def test_folder_key_is_the_path_below_the_tier_folder():
    """The work's folder key: `path_key` of the folder below its tier folder (02 §2.6), never the tier folder, never
    hato's drop folder (its files are loose: a work each until a record names their show)."""
    key = ls.folder_key_of
    assert key("HighPriority/冒険/Season 1/第01話.srt") == ls.path_key("冒険/Season 1")
    assert key("HighPriority/冒険/Season 1/x.srt") == key("GoalContent/冒険/Season 1/y.srt") == \
        key("Graduated/冒険/Season 1/z.srt") == key("LowPriority/冒険/Season 1/w.srt")
    assert key("HighPriority/A/Season 1/x.srt") != key("HighPriority/B/Season 1/x.srt")
    assert key("HighPriority/x.srt") is None and key("GoalContent/新闻.txt") is None
    assert key(ls.HATO_FOLDER + "/Frieren - 05.ja.ass") is None
    assert key(ls.HATO_FOLDER + "/葬送のフリーレン/05.ja.ass") == ls.path_key("Hato/葬送のフリーレン")


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_completes_pieces_and_keeps_2_5s(language):
    """02 §2.6 step 3: 2.5's pieces (runs of one folder) keep their ids and members; an item added since (no piece)
    joins the piece of its work it directly follows, a loose file gets a piece of its own; a 2.5 piece a later move
    left in two tiers keeps its id on its first run and its other run becomes a piece of its own. `pieces_ok` holds."""
    _d, _u, doc = library(language, shows=2, episodes=4, loose=1)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    conn = _raw(db)
    pieces_25 = {p: sorted(i for (i,) in conn.execute("SELECT id FROM items WHERE piece_id = ?", (p,)))
                 for (p,) in conn.execute("SELECT id FROM pieces")}
    goal = conn.execute("SELECT id, piece_id, rel_path, ord FROM items WHERE tier = 'goal' AND piece_id IS NOT NULL "
                        "ORDER BY ord").fetchall()
    first_show = [r for r in goal if r[1] == goal[0][1]]
    rel = first_show[-1][2].rsplit("/", 1)[0] + f"/{names(language)[90]}_第05話.srt"
    touch(data_dir, rel)
    title, folder, st = ls._columns(ls.make_entry(rel, "Disk Sync", "subtitle"))
    conn.execute("INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, source_type, "
                 "availability, changed_in, added_at) VALUES (900, 1, ?, ?, 'goal', ?, ?, ?, ?, ?, 'available', 2, ?)",
                 (rel, ls.path_key(rel), first_show[-1][3] + 1, ls._dumps(ls.make_entry(rel, "Disk Sync", "subtitle")),
                  title, folder, st, ls._now()))
    moved = first_show[0][0]                                     # 2.5 moved one episode to NOW: its piece in two tiers
    conn.execute("UPDATE items SET tier = 'now', ord = -1 WHERE id = ?", (moved,))
    conn.close()
    store = _upgrade(language)
    piece = lambda i: store.item(i)["piece_id"]                  # noqa: E731
    assert piece(900) == first_show[1][1], "joins the piece of its work it directly follows"
    assert piece(moved) not in pieces_25 or piece(moved) != first_show[0][1], "the run in another tier: a piece of its own"
    for p, members in pieces_25.items():
        if p == first_show[0][1]:
            continue
        assert sorted(i for (i,) in store.conn.execute("SELECT id FROM items WHERE piece_id = ?", (p,))) == members
    loose = [i for i in store.ids("now") if store.item(i)["parent_folder"] == ""]
    assert loose and all(piece(i) is not None for i in loose)
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_backup_killed_mid_copy_never_looks_whole(language):
    """L3.1's smoothness drills (R3): a process killed while the `.bak` is copied left an empty `.bak` with its
    `-journal`, counted among the backups kept. A copy is written as `.part` and renamed only when whole; the next
    backup clears a killed one's leftovers (an older version's `.bak` still holding its journal too), and only whole
    backups count toward the newest kept."""
    _d, _u, doc = library(language)
    _data_dir, _user_files_dir, db = schema1_store(language, doc)
    folder, base = os.path.split(db)
    for name in (".bak.20260101-000000.part", ".bak.20260101-000000.part-journal", ".bak.20260101-000001",
                 ".bak.20260101-000001-journal"):
        open(os.path.join(folder, base + name), "wb").close()
    conn = _raw(db)

    class Killed(Exception):
        pass

    class Dying:                                               # the process dies inside SQLite's copy
        def backup(self, target, *a, **k):
            target.execute("CREATE TABLE half (x)")
            raise Killed("killed mid-copy")
    with pytest.raises(Killed):
        ls._backup_db(Dying(), db)
    assert not [f for f in os.listdir(folder) if f.startswith(base + ".bak.") and not f.endswith((".part", "-journal"))], \
        "a killed copy leaves no whole-looking .bak (the older one with its journal cleared too)"
    dest = ls._backup_db(conn, db)
    conn.close()
    left = sorted(f for f in os.listdir(folder) if f.startswith(base + ".bak."))
    assert left == [os.path.basename(dest)], left
    check = sqlite3.connect(dest)
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_failure_leaves_schema_1_and_a_bak(language, monkeypatch):
    """02 §2.6 #6: a step that fails rolls the whole upgrade back — schema 1, no works table, every row as it was — with
    a `.bak` beside it and the reason recorded; the next helper run tries again and succeeds."""
    _d, _u, doc = library(language)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    conn = _raw(db)
    before = _snapshot(conn)
    conn.close()

    def boom(store, version):
        raise RuntimeError("an injected failure halfway")
    real = ls._seed_schema2
    monkeypatch.setattr(ls, "_seed_schema2", boom)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    conn = _raw(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'works'").fetchone()
    assert _snapshot(conn) == before
    assert "injected failure" in json.loads(dict(conn.execute("SELECT key, value FROM meta"))["upgrade_failed"])["error"]
    conn.close()
    assert [f for f in os.listdir(os.path.dirname(db)) if f.startswith(os.path.basename(db) + ".bak.")]
    monkeypatch.setattr(ls, "_seed_schema2", real)
    store = _upgrade(language)
    assert _snapshot(store.conn) == before and "upgrade_failed" not in store.meta()
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_upgrade_check_refuses_a_changed_order(language, monkeypatch):
    """The check before commit (02 §2.6 #6): a seeding step that changed one item's order key — a bug — is refused, and
    nothing of the upgrade is kept."""
    _d, _u, doc = library(language)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    conn = _raw(db)
    before = _snapshot(conn)
    conn.close()
    real = ls._seed_schema2

    def changes_an_order(store, version):
        real(store, version)
        store.conn.execute("UPDATE items SET ord = ord + 0.5 WHERE id = (SELECT MIN(id) FROM items)")
    monkeypatch.setattr(ls, "_seed_schema2", changes_an_order)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    conn = _raw(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1 and _snapshot(conn) == before
    assert "changed order" in json.loads(dict(conn.execute("SELECT key, value FROM meta"))["upgrade_failed"])["error"]
    conn.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_seeds_the_soon_line_at_nows_count(language):
    """Q2-4 ("nobody's list changes at the switch"): the line sits at NOW's count, every row of Current counted;
    New arrivals are on (D30, 08 §8.1 #14); every row's feed version is the upgrade's, and so is the feed's floor."""
    _d, _u, doc = library(language, shows=3, episodes=4)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    conn = _raw(db)
    now = conn.execute("SELECT COUNT(*) FROM items WHERE tier = 'now'").fetchone()[0]
    soon = conn.execute("SELECT id FROM items WHERE tier = 'soon'").fetchall()
    conn.close()
    store = _upgrade(language)
    meta = store.meta()
    assert meta["soon_line"] == now and len(store.ids("now")) == now and len(store.ids("soon")) == len(soon)
    assert meta["arrivals_on"] == 1 and meta["search_fold"] == ls.SEARCH_FOLD_VERSION
    version = meta["state_version"]
    assert meta["feed_floor"] == version
    assert {r[0] for r in store.conn.execute("SELECT DISTINCT feed_in FROM items")} == {version}
    assert {r[0] for r in store.conn.execute("SELECT DISTINCT feed_in FROM works")} == {version}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_writes_every_search_key(language):
    """02 §2.4: each item's key is its folded title, each work's its folded title and other titles (`search_fold`)."""
    _d, _u, doc = library(language)
    schema1_store(language, doc)
    store = _upgrade(language)
    for title, key in store.conn.execute("SELECT title, search_key FROM items"):
        assert key == ls.search_fold(title, language) and key
    for title, titles, key in store.conn.execute("SELECT title, titles, search_key FROM works"):
        assert key.split("\n")[0] == ls.search_fold(title, language)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_records_ids_make_one_title_of_two_works(language):
    """G2.2-6 (one title per AniList / TMDB id): two shows in different folders whose pairings name the same AniList id
    are one work after the upgrade, the lower id kept, its TMDB id filled; made words 2.6 recorded stay untouched."""
    w = names(language)
    data_dir, user_files_dir = roots(language)
    rels = [f"HighPriority/{w[10]}/{w[10]}_01.srt", f"HighPriority/{w[11]}/{w[11]}_02.srt", f"HighPriority/{w[12]}.txt"]
    doc = {"schedule": {"PHASE_1_NOW": [], "PHASE_2_SOON": [], "PHASE_3_LATER": []}}
    for rel in rels:
        touch(data_dir, rel)
        doc["schedule"]["PHASE_1_NOW"].append(ls.make_entry(rel, "Manual Import", "subtitle"))
    _d, _u, db = schema1_store(language, doc)
    conn = _raw(db)
    for n, (item, record) in enumerate([(1, {"anilist_id": 154587}), (2, {"anilist_id": 154587, "tmdb_id": "tv:209867"}),
                                        (3, {"anilist_id": None})]):
        conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                     (f"v1-{n}", item, json.dumps(dict(record, content_key=f"v1-{n}")), ls._now()))
    conn.execute("INSERT INTO made_words VALUES (2, '冒険', '[1700000000001]', ?, 'b1')", (ls._now(),))
    conn.close()
    store = _upgrade(language)
    a, b, c = (store.item(i)["work_id"] for i in (1, 2, 3))
    assert a == b != c
    row = store.conn.execute("SELECT anilist_id, tmdb_id, titles FROM works WHERE id = ?", (a,)).fetchone()
    assert row[:2] == (154587, "tv:209867") and w[11] in json.loads(row[2])
    assert store.conn.execute("SELECT item_id, word, note_ids FROM made_words").fetchall() == \
        [(2, "冒険", "[1700000000001]")]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_generate_is_byte_identical_after_the_upgrade(language):
    """Q2-4 and K3 (08 §8.1 #1): the upgraded store hands Generate the same list as the file it came from — the same
    words, counts, scores and weights, byte for byte — so nobody's list changes at the switch."""
    from tests.test_library_store_readers import _clear_results, _library, _outputs, _run
    from app import analyzer
    from unittest.mock import patch
    env = {"root": os.environ["SURASURA_TEST_ROOT"], "results": os.path.join(os.environ["SURASURA_TEST_ROOT"], "results")}
    os.makedirs(env["results"], exist_ok=True)
    data_dir, user_files_dir, doc = _library(language)
    with patch.object(analyzer, "_library_store", lambda: None):
        _run(env, language)                                     # 2.4's path: the file, no store
    before = _outputs(env)
    schema1_store(language, doc)
    store = _upgrade(language)
    store.close()
    _clear_results(env)
    _run(env, language)
    assert analyzer.read_library_schedule(language)[0] is not None, "the list came from the upgraded store"
    assert _outputs(env) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_never_built_schema_1_store_is_built_not_upgraded(language):
    """A schema-1 database 2.x left with no rows (its first build failed, or it waited on a newer copy): the helper
    brings its tables up to schema 2 and builds it from the manifest, as a new store (§12.6 #2's note for 3.0)."""
    _d, _u, doc = library(language)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    conn = _raw(db)
    conn.execute("BEGIN")
    for table in ("items", "pieces", "roots"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM meta WHERE key = 'migrated_at'")
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('migration_failed', ?)",
                 (json.dumps({"app_version": "2.4.0"}),))          # an older version's failure: built anew
    conn.execute("COMMIT")
    conn.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert len(store.ids("now")) == len(doc["schedule"]["PHASE_1_NOW"]) and pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_older_surasura_reads_a_schema_2_store_read_only(language, monkeypatch):
    """06 §6.1 (built in 2.5): a store made by a newer Surasura is read-only to an older one, which shows the library and
    changes nothing."""
    _d, _u, doc = library(language)
    data_dir, user_files_dir, _db = schema1_store(language, doc)
    _upgrade(language).close()
    monkeypatch.setattr(ls, "STORE_SCHEMA", 1)
    assert ls.check_mode(language, data_dir) == ("read-only", "made by a newer Surasura")
    assert ls.open_store(language, data_dir, user_files_dir) is None


def _schema1_big(language, n):
    """A schema-1 store of `n` items in one transaction, the reviews' 100k shape (NOW 1 %, Soon 44.5 %, 6+ Months the
    rest; 12 episodes a show), 2.5's pieces by folder runs."""
    data_dir, user_files_dir = roots(language)
    words = names(language)
    now, soon = max(20, n // 100), int(n * 0.445)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    _d, _u, db = schema1_store(language, doc)
    conn = _raw(db)
    conn.execute("BEGIN")
    stamp = ls._now()
    rows, pieces, piece_of = [], [], {}
    for i in range(n):
        tier = "now" if i < now else "soon" if i < now + soon else "goal"
        show = f"{words[(i // 12) % len(words)]}{i // 12}"
        rel = f"{ls.FOLDER_OF_TIER[tier]}/{show}/{show}_{i:06d}.srt"
        key = (tier, show)
        if key not in piece_of:
            piece_of[key] = len(pieces) + 1
            pieces.append((len(pieces) + 1, show, "run", stamp))
        entry = ls.make_entry(rel, "Disk Sync", "subtitle")
        rows.append((i + 1, rel, ls.path_key(rel), tier, ls.STEP * (i + 1), ls._dumps(entry), entry["title"],
                     entry["parent_folder"], "subtitle", 100, 1, stamp, piece_of[key]))
    conn.executemany("INSERT INTO pieces VALUES (?, ?, ?, ?)", pieces)
    conn.executemany("INSERT INTO items (id, root_id, rel_path, rel_key, tier, ord, entry, title, parent_folder, "
                     "source_type, availability, size, mtime_ns, changed_in, added_at, piece_id) VALUES "
                     "(?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, 1, ?, ?)", rows)
    conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'items'", (n,))
    conn.execute("COMMIT")
    conn.close()
    return data_dir, user_files_dir, db


@pytest.mark.parametrize("language", LANGUAGES)
def test_upgrade_200k_under_10_s(language):
    """02 §2.6's cost model: one pass over the items, one insert per work — ≤ 10 s at 200k in the helper, never in a
    window. The budget holds in the timed run (SURASURA_STORE_BENCH=1, 200k); otherwise 20k, unbudgeted."""
    n = 200_000 if BENCH else 20_000
    data_dir, user_files_dir, db = _schema1_big(language, n)
    store = ls._helper_store(db, language, data_dir, user_files_dir)
    try:
        t0 = time.perf_counter()
        assert ls._upgrade(store) is True
        took = time.perf_counter() - t0
        assert pieces_ok(store) is None
        assert store.conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == -(-n // 12)
    finally:
        store.close()
    if BENCH:
        print(f"\nupgrade {language} {n}: {took:.2f} s")
        assert took <= 10.0, took
