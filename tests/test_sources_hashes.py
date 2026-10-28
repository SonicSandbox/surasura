"""A4K-7 (alpha 4, Sonic 2026-10-28: "Yes to both leans"): the store keeps each copy's content hash, so a look's check
(b) — "is this new file's text an item already?" — reads the hash instead of the copy. Before it, every copy of a new
file's size was read and hashed on every look: 100 books onto 60k parts read ~56,000 copies (92% of the look).

The column is added (no row rewritten), filled as a look writes copies and as check (b) reads one, and a trigger forgets
a hash whenever its row's file changes — whoever writes the row, an older Surasura too. A kept hash that matches is
trusted only while the copy on disk is still as its row records it. Never in the JSON copy."""
import hashlib
import json
import os
import sqlite3
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_k5_tables import _chapters
from tests.test_sources_scan import _drive, _empty, _epub, _fresh_module_state, _look, _text, _write  # noqa: F401

_SHOW = {"ja": "月影の旅人", "zh": "夜市小记"}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _kept(store):
    """{rel_path: content_sha256} of every available item."""
    return dict(store.conn.execute("SELECT rel_path, content_sha256 FROM items WHERE availability = 'available'"))


def _reads(monkeypatch, data_dir):
    """The copies inside the library that are read to be hashed (the source's own files are read anyway)."""
    inside, real = [], ls.sha256_of
    top = os.path.normcase(os.path.abspath(data_dir))

    def counting(path):
        if os.path.normcase(os.path.abspath(path)).startswith(top):
            inside.append(path)
        return real(path)
    monkeypatch.setattr(ls, "sha256_of", counting)
    return inside


def _same_size(language, n):
    """Two texts of one byte size with different bytes (check (b) meets the first's copy for the second)."""
    a = _text(language, n)
    return a, a[:-2] + ("x" if a[-2] != "x" else "y") + a[-1]


# A copy elsewhere is named with no episode number (`kopie.srt`): only check (b) can find its item, never its episode's
# own record (A26)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_store_has_the_hash_column_and_an_older_one_gains_it_at_open_with_no_row_changed(language):
    """Why: the change must be additive — a store an older Surasura made gains the column and its trigger at the first
    open by a writer, every row as it was (the new column empty) and the schema version unchanged."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), _text(language, 1))
    with store:
        assert store._hash_column()
        assert store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                                  (ls.ADDED_HASH,)).fetchone()
        _look(store, language, store.add_source(src), first=True)
        user_files_dir, path = store.user_files_dir, store.db_path
    conn = sqlite3.connect(path)
    conn.execute(f"DROP TRIGGER {ls.ADDED_HASH}")                          # the store as an older build left it
    conn.execute("ALTER TABLE items DROP COLUMN content_sha256")
    conn.commit()
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert rows
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert again._hash_column()
        names = [r[1] for r in again.conn.execute("PRAGMA table_info(items)")]
        cols = ", ".join(n for n in names if n != "content_sha256")
        assert again.conn.execute(f"SELECT {cols} FROM items ORDER BY id").fetchall() == rows
        assert {v for (v,) in again.conn.execute("SELECT content_sha256 FROM items")} == {None}
        assert again.conn.execute("PRAGMA user_version").fetchone()[0] == version
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_look_keeps_each_copys_hash_as_it_writes_it_text_and_book_parts(language):
    """Why: a copy the look wrote is never read back to be known — its hash goes in with its item (a subtitle's copy and
    each part of a book), and it is the hash of the bytes on disk."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), _text(language, 1))
    _epub(os.path.join(src, "本棚", "星の歌.epub"), _chapters(language, 1))
    with store:
        result = _look(store, language, store.add_source(src), first=True)
        kept = _kept(store)
        assert result["added"] == len(kept) >= 3                 # the subtitle and the book's parts
        assert any(rel.endswith(".srt") for rel in kept) and any("星の歌" in rel for rel in kept)
        for rel, sha in kept.items():
            assert sha == _sha(os.path.join(data_dir, *rel.split("/"))), rel


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_look_finds_the_same_bytes_without_reading_any_copy(language, monkeypatch):
    """Why: the key case — a look that brings files the size of copies already in reads none of those copies: a file
    with an item's bytes is that item (attached, never copied), one of the same size with other bytes is new."""
    store, data_dir = _empty(language)
    one, other = _same_size(language, 1)
    src, more = _drive("driveA"), _drive("driveB")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), one)
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        _write(os.path.join(more, "backup", "kopie.srt"), one)
        _write(os.path.join(more, _SHOW[language], "ep02.srt"), other)
        reads = _reads(monkeypatch, data_dir)
        result = _look(store, language, store.add_source(more))
        assert reads == []
        assert (result["added"], result["attached"]) == (1, 1)
        origin = os.path.abspath(os.path.join(more, "backup", "kopie.srt"))
        assert store.origins()[ls.path_key(origin)].item_id == item


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_from_before_reads_each_copy_once_and_keeps_its_hash_for_the_next_look(language, monkeypatch):
    """Why: a library made before the change has no hashes: its first look reads the copies check (b) needs, as before,
    and keeps their hashes; the next look reads none of them."""
    store, data_dir = _empty(language)
    one, other = _same_size(language, 2)
    src, more, third = _drive("driveA"), _drive("driveB"), _drive("driveC")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), one)
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        with store._writing():
            store.conn.execute("UPDATE items SET content_sha256 = NULL")       # as the older build left them
        _write(os.path.join(more, "backup", "kopie.srt"), one)
        reads = _reads(monkeypatch, data_dir)
        result = _look(store, language, store.add_source(more))
        assert len(reads) == 1 and result["attached"] == 1
        rel = store.item(item)["rel_path"]
        assert _kept(store)[rel] == _sha(os.path.join(data_dir, *rel.split("/")))
        _write(os.path.join(third, _SHOW[language], "ep02.srt"), other)
        _write(os.path.join(third, "old", "kopie.srt"), one)
        reads.clear()
        again = _look(store, language, store.add_source(third))
        assert reads == [] and (again["added"], again["attached"]) == (1, 1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_kept_hash_is_forgotten_when_its_rows_file_changes_whoever_writes_it(language):
    """Why: the hash is the file's as the row records it; an older Surasura never knows the column, so the store itself
    forgets it when a write moves the row's size, time or path. A write that leaves them as they were keeps it."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, _SHOW[language], "ep02.srt"), _text(language, 2))
    _write(os.path.join(src, _SHOW[language], "ep03.srt"), _text(language, 3))
    with store:
        a, b, c = sorted(_look(store, language, store.add_source(src), first=True)["ids"])
        path = store.db_path
    conn = sqlite3.connect(path)                                          # raw writes, as an older build makes them
    conn.execute("UPDATE items SET size = size, mtime_ns = mtime_ns, title = 'x' WHERE id = ?", (a,))
    conn.execute("UPDATE items SET mtime_ns = mtime_ns + 1 WHERE id = ?", (b,))
    conn.execute("UPDATE items SET rel_path = rel_path || '.moved' WHERE id = ?", (c,))
    conn.commit()
    got = dict(conn.execute("SELECT id, content_sha256 FROM items"))
    conn.close()
    assert got[a] is not None and got[b] is None and got[c] is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_kept_hash_never_matches_a_copy_changed_on_disk_since_its_row(language):
    """Why: a kept hash is used only while the copy is as its row records it — a copy rewritten on disk (not yet seen
    by a sync) is read, so a file with its OLD bytes is never taken for it and one with its NEW bytes is (as reading
    every copy found it); no hash is kept for a file its row no longer describes."""
    store, data_dir = _empty(language)
    one, other = _same_size(language, 1)
    src, more = _drive("driveA"), _drive("driveB")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), one)
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        row = store.item(item)
        full = os.path.join(data_dir, *row["rel_path"].split("/"))
        with open(full, "w", encoding="utf-8", newline="\n") as f:          # its bytes changed, its size the same
            f.write(other)
        t = time.time() - 30
        os.utime(full, (t, t))
        _write(os.path.join(more, "old", "kopie.srt"), one)
        _write(os.path.join(more, "new", "kopie.srt"), other)
        result = _look(store, language, store.add_source(more))
        assert (result["added"], result["attached"]) == (1, 1)
        new = os.path.abspath(os.path.join(more, "new", "kopie.srt"))
        assert store.origins()[ls.path_key(new)].item_id == item              # its new bytes are that item's
        assert store.item(item)["content_sha256"] == hashlib.sha256(one.encode("utf-8")).hexdigest()   # not re-kept
        stale = [(item, row["size"], row["mtime_ns"] + 1, "0" * 64)]
        assert store.keep_hashes(stale) == 0 and store.item(item)["content_sha256"] != "0" * 64


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_json_copy_never_carries_the_hashes_a_removed_items_included(language):
    """Why: the hash is a cache the store fills again; the copy (and its content_sha) stays as an older build writes it
    — a Remove's trash state too (the trash table goes out in the copy whole)."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOW[language], "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, _SHOW[language], "ep02.srt"), _text(language, 2))
    with store:
        first, _second = sorted(_look(store, language, store.add_source(src), first=True)["ids"])
        assert all(_kept(store).values())
        store.remove([first])
        (state,) = store.conn.execute("SELECT item_state FROM trash").fetchone()
        assert "content_sha256" not in json.loads(state)["columns"]
        doc, _version, _dirty = store.export_snapshot()
        assert "content_sha256" not in json.dumps(doc, ensure_ascii=False)
        assert "content_sha256" not in doc["surasura_library"]["items"]["fields"]
