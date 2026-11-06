"""F13b (3.0.1): a quick look reads only the origins that changed since the last look. Every look read every origin
(`Store.origins()`, ~0.25–0.45 s at 20k: the one long step left in a look that takes in one new file, F13's register
row 6). Now the store logs, by SQLite's own triggers, which items' origins changed (`ORIGIN_LOG_SQL`), and
`Store.origins_kept` reads only those items over the origins a look kept (`sources._KEPT`).
The proof that nothing a look reads moved: the whole read (`origins()`, what every look read before) is the oracle —
after every kind of write, through the store's commands and through a plain SQLite connection (another program, an
older Surasura), the kept read equals it, field for field and in key order. Each case the log can't answer reads in
full (counted, never timed: it holds on any runner)."""
import os
import random
import sqlite3

import pytest

from app import library_store as ls
from app import sources
from tests.test_sources_scan import (_drive, _empty, _fresh_module_state, _look, _seed, _settle,  # noqa: F401
                                     _text, _write)


def _counting(store, monkeypatch):
    """Counts the whole reads (`origins()` with no `items`) the store makes from here."""
    whole, real = [], store.origins

    def origins(items=None):
        if items is None:
            whole.append(1)
        return real(items=items)
    monkeypatch.setattr(store, "origins", origins)
    return whole


def _same(kept, store):
    """The kept read equals the whole read: the same keys in the same order, each Origin field for field."""
    want = store.origins()
    assert list(kept.items()) == list(want.items())


def _library(n=120, per_show=10):
    store, data_dir = _empty("ja")
    src = _drive("driveA")
    store.__enter__()
    root = store.add_source(src)
    _seed(store, root, data_dir, "ja", src, n, per_show=per_show, name="[Grp] {show} - {e:02d} (1080p).ja.srt")
    return store, data_dir, src, root


# --- the store's read ----------------------------------------------------------------------------------------------- #

def test_the_kept_read_equals_the_whole_read_after_every_kind_of_write():
    """300 random writes of every kind an origin's read depends on — a record rewritten, a key moved to another item
    by REPLACE (no delete trigger fires), an origin deleted, an item's copy moved or gone, an item deleted with its
    records, a new item and origin, a record made unreadable, the store's own take-in and update — each through a
    plain connection or the store; after each, the kept read is the whole read, in order."""
    store, data_dir, src, root = _library()
    try:
        rng = random.Random(13)
        raw = sqlite3.connect(store.db_path)
        raw.execute("PRAGMA foreign_keys=ON")
        kept = store.origins_kept(None)
        assert kept[0] is not None
        _same(kept[1], store)
        for step in range(300):
            keys = list(store.origins())
            ids = [r[0] for r in raw.execute("SELECT id FROM items")]
            what = rng.randrange(10)
            k = ls.SOURCE_KEY + rng.choice(keys) if keys else None
            if what == 0 and k:
                raw.execute("UPDATE pairings SET pairing = json_set(pairing, '$.size', ?) WHERE content_key = ? AND "
                            "json_valid(pairing)", (rng.randrange(10**6), k))
            elif what == 1 and k:                               # REPLACE onto another item
                row = raw.execute("SELECT pairing, paired_at FROM pairings WHERE content_key = ?", (k,)).fetchone()
                raw.execute("INSERT OR REPLACE INTO pairings (content_key, item_id, pairing, paired_at) VALUES "
                            "(?, ?, ?, ?)", (k, rng.choice(ids), row[0], row[1]))
            elif what == 2 and k:
                raw.execute("DELETE FROM pairings WHERE content_key = ?", (k,))
            elif what == 3 and ids:
                raw.execute("UPDATE items SET availability = ? WHERE id = ?",
                            (rng.choice(["available", "missing", "waiting"]), rng.choice(ids)))
            elif what == 4 and ids:
                raw.execute("UPDATE items SET rel_path = rel_path || 'x' WHERE id = ?", (rng.choice(ids),))
            elif what == 5 and ids:
                raw.execute("DELETE FROM items WHERE id = ?", (rng.choice(ids),))
            elif what == 6 and k:                               # an UPDATE moving the key to another item
                raw.execute("UPDATE pairings SET item_id = ? WHERE content_key = ?", (rng.choice(ids), k))
            elif what == 7 and k:
                raw.execute("UPDATE pairings SET pairing = 'not json' WHERE content_key = ?", (k,))
            elif what == 8:                                     # the store's own take-in: a new item and origin
                name = f"新作{step:03d}.ja.srt"
                rel = f"Library/新作/{name}"
                full = os.path.join(data_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(f"そんなことより、今日はどこへ行くの？ {step}\n")
                raw.commit()
                store.take_in(root, [{"origin": os.path.join(src, "新作", name), "size": 10, "mtime_ns": 1,
                                      "sha256": f"{10**6 + step:064x}", "show": "新作", "rel": rel,
                                      "episode": step + 1}])
            elif what == 9 and keys:                            # the store's own update of a record's stats
                raw.commit()
                readable = [o for o in store.origins().values() if o.origin]
                if readable:
                    o = rng.choice(readable)
                    store.update_origins([(o.origin, 11, 2, o.sha256, None)])
            raw.commit()
            kept = store.origins_kept(kept)
            assert kept[0] is not None
            _same(kept[1], store)
        raw.close()
    finally:
        store.__exit__(None, None, None)


def test_nothing_changed_reads_nothing_and_one_change_reads_one_item(monkeypatch):
    """No write since: the same origins, no read of any. One copy gone: that item's origins alone, no whole read."""
    store, data_dir, src, root = _library()
    try:
        kept = store.origins_kept(None)
        whole = _counting(store, monkeypatch)
        again = store.origins_kept(kept)
        assert again[1] is kept[1] and whole == []
        item = next(iter(kept[1].values())).item_id
        with store._writing():
            store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (item,))
        asked = []
        real = store.origins
        monkeypatch.setattr(store, "origins", lambda items=None: asked.append(items) or real(items=items))
        after = store.origins_kept(again)
        assert asked == [{item}]
        assert [o.availability for o in after[1].values() if o.item_id == item] == ["missing"]
    finally:
        store.__exit__(None, None, None)


def test_the_log_reads_in_full_when_it_cant_say(monkeypatch):
    """A whole read whenever the log can't answer: nothing kept, another store (its id or epoch moved), a mark ahead of
    the log, the rows since the mark pruned, the reset mark among them, more than a quarter of the origins changed,
    or inside a write (and then nothing is kept)."""
    store, data_dir, src, root = _library()
    try:
        kept = store.origins_kept(None)
        whole = _counting(store, monkeypatch)
        mark, origins = kept
        store.origins_kept(((mark[0], mark[1] + 1, mark[2]), origins))         # another epoch
        store.origins_kept((("another store", mark[1], mark[2]), origins))
        store.origins_kept(((mark[0], mark[1], mark[2] + 5), origins))         # a mark ahead of the log
        assert len(whole) == 3
        with store._writing():
            store.conn.execute("INSERT INTO origin_changes (item_id) VALUES (0)")
        store.origins_kept(kept)
        assert len(whole) == 4, "the reset mark"
        kept = store.origins_kept(None)
        ids = sorted({o.item_id for o in kept[1].values()})
        with store._writing():
            store.conn.executemany("UPDATE items SET availability = 'missing' WHERE id = ?",
                                   [(i,) for i in ids[:len(kept[1]) // 4 + 1]])
        store.origins_kept(kept)
        assert len(whole) == 6, "a quarter changed"
        kept = store.origins_kept(None)
        with store._writing():
            store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (ids[-1],))
            store.conn.execute("DELETE FROM origin_changes WHERE seq <= ?", (kept[0][2] + 1,))
        store.origins_kept(kept)
        assert len(whole) == 8, "its rows pruned"
        with store._writing():
            assert store.origins_kept(kept)[0] is None
        assert len(whole) == 9, "inside a write"
    finally:
        store.__exit__(None, None, None)


def test_the_log_prunes_itself_and_a_mark_before_its_rows_reads_in_full(monkeypatch):
    """The log keeps its newest ORIGIN_LOG_KEEP rows, whoever writes (a trigger of its own); a reader whose mark is
    older reads all."""
    store, data_dir, src, root = _library(n=20)
    try:
        kept = store.origins_kept(None)
        with store._writing():
            store.conn.executemany("INSERT INTO origin_changes (item_id) VALUES (?)",
                                   [(1,)] * (ls.ORIGIN_LOG_KEEP + 3000))
        count, low, top = store.conn.execute("SELECT COUNT(*), MIN(seq), MAX(seq) FROM origin_changes").fetchone()
        assert count <= ls.ORIGIN_LOG_KEEP + 1024 and low > kept[0][2] + 1 and top - low + 1 == count
        whole = _counting(store, monkeypatch)
        got = store.origins_kept(kept)[1]
        assert whole == [1]
        _same(got, store)
    finally:
        store.__exit__(None, None, None)


def test_a_store_made_before_the_log_gets_it_at_open_with_its_reset_mark_and_without_it_reads_in_full(monkeypatch):
    """A store made before F13b (the log and its triggers dropped, as an older build made it) reads in full each time
    and keeps nothing; its first open by a writer makes the log, with the reset mark, and changes no other row; a
    trigger gone later (a table rebuilt) reads in full again until an open makes it back, its reset mark with it —
    so origins kept from before the gap are never trusted. A reader never makes it."""
    store, data_dir, src, root = _library(n=20)
    db, ud = store.db_path, store.user_files_dir
    kept = store.origins_kept(None)
    store.__exit__(None, None, None)
    raw = sqlite3.connect(db)
    for name in ls.ORIGIN_LOG[1:]:
        raw.execute(f"DROP TRIGGER {name}")
    raw.execute("DROP TABLE origin_changes")
    raw.commit()
    before = {t: raw.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in ("items", "pairings", "meta")}
    raw.close()
    reader = ls.Store(db, "ja", data_dir, ud, role="reader")
    try:
        assert reader.origins_kept(kept) == (None, reader.origins())
        assert not reader.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'origin_changes'").fetchone()
    finally:
        reader.close()
    store = ls.open_store("ja", data_dir, ud)
    with store:
        assert {t: store.conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                for t in ("items", "pairings", "meta")} == before
        assert store.conn.execute("SELECT item_id FROM origin_changes").fetchall() == [(0,)]
        whole = _counting(store, monkeypatch)
        again = store.origins_kept(kept)
        assert whole == [1] and again[0] is not None
        raw = sqlite3.connect(db)
        raw.execute("DROP TRIGGER origin_log_copy")
        raw.commit()
        raw.close()
        assert store.origins_kept(again)[0] is None and whole == [1, 1]
    store = ls.open_store("ja", data_dir, ud)
    with store:
        assert store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'origin_log_copy'").fetchone()
        whole = _counting(store, monkeypatch)
        got = store.origins_kept(again)[1]
        assert whole == [1], "the reset mark: nothing kept from before the gap is read as current"
        _same(got, store)


# --- the look ------------------------------------------------------------------------------------------------------- #

def test_a_quick_look_reads_only_what_changed_and_a_full_look_reads_all(monkeypatch):
    """The first look of a run and a Refresh read every origin; a quick look that takes in one new file after them
    reads only what changed since — and its origins are those a whole read gives (checked at every `_load`)."""
    store, data_dir, src, root = _library(n=600, per_show=50)
    try:
        real_load = sources._Look._load

        def load(look):                                 # the oracle at every look: the whole read
            fresh = look.origins is None
            real_load(look)
            if fresh:
                assert list(look.origins.items()) == list(ls._store_origins(look.store).items())
        monkeypatch.setattr(sources._Look, "_load", load)
        show = "既存0003"
        _write(os.path.join(src, "seeded", show, f"[Grp] {show} - 77 (1080p).ja.srt"), _text("ja", 77))
        _settle(src)
        whole = _counting(store, monkeypatch)
        assert _look(store, "ja", root)["added"] == 1
        assert whole == [1], "the first look of this run"
        for n in (78, 79):
            _write(os.path.join(src, "seeded", show, f"[Grp] {show} - {n} (1080p).ja.srt"), _text("ja", n))
            _settle(os.path.join(src, "seeded", show))
            assert _look(store, "ja", root)["added"] == 1
        assert whole == [1], "quick looks read only what changed"
        _write(os.path.join(src, "seeded", show, f"[Grp] {show} - 80 (1080p).ja.srt"), _text("ja", 80))
        _settle(os.path.join(src, "seeded", show))
        assert _look(store, "ja", root, full=True)["added"] == 1
        assert whole == [1, 1], "a Refresh reads all"
    finally:
        store.__exit__(None, None, None)


def test_the_origins_are_kept_for_two_stores_at_most(monkeypatch):
    """One store a language is kept between looks; another store's look lets the oldest go (a test run, or a language
    switch back and forth, never holds every store it opened)."""
    monkeypatch.setattr(sources, "_KEPT", {"older": (None, {}), "old": (None, {})})
    store, data_dir = _empty("ja")
    src = _drive("driveA")
    _write(os.path.join(src, "番組", "ep01.srt"), _text("ja", 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, "ja", root, first=True)["added"] == 1
    assert list(sources._KEPT) == ["old", sources._store_key(store)]
