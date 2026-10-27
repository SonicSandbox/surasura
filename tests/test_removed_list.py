"""K2 (alpha 4, Mattias's note 6): the Removed list and *Bring back N removed* — `Store.removed`, `removed_under`, the
looks' worker's `removed` / `removed_under`, and Put back through the window's writer (`Writer.restore`, with Undo).

What a wrong answer would cost a learner: a Remove keeps its files out for good (SRC-8), so a folder read again brings
nothing back (Mattias re-added his folder and got nothing) — without a list, a misclick is forever. The list must name
only HIS Removes (never a skipped folder's files — *Read again* brings those — nor an Undo of an add), say how long each
file has before the 30-day purge, tell one that can still come back from one that can't, and Put back must let the
originals in again with one Undo that sends them back.

Real Japanese / Chinese texts from tests/Test Resources/ in a source folder beside the test's data folder (the
sources scan's helpers), the real store; the writer on its own thread for the trash's file half.
"""
import os
import time

import pytest

from app import library_store as ls
from app.services import moves as M
from app.services import source_looks
from tests import services_helpers as h
from tests.test_library_store_support import LANGUAGES, migrated
from tests.test_services_moves import Heard, WORDS
from tests.test_sources_scan import (_SHOWS, _drive, _empty, _fresh_module_state, _items, _look, _text,  # noqa: F401
                                     _write)


def _show(language, src, show, n=3):
    """`n` episodes of `show`, each its own text (two shows never share bytes: the store would take them as one)."""
    folder = os.path.join(src, show)
    return [_write(os.path.join(folder, f"{show} - {i:02d}.srt"), _text(language, i, extra=f"「{show}」"))
            for i in range(1, n + 1)]


def _taken(store, language, src):
    root = store.add_source(src)
    ids = _look(store, language, root, first=True)["ids"]
    return root, sorted(ids)


def _excluded(store):
    return store.conn.execute("SELECT COUNT(*) FROM exclusions WHERE kind = 'removed'").fetchone()[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_remove_is_one_entry_per_title_with_its_files_and_comes_back_through_its_folder(language):
    store, _data = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("shows")
    _show(language, src, a)
    _show(language, src, b, n=2)
    with store:
        root, ids = _taken(store, language, src)
        store.remove(ids)                                   # one Remove of both shows (the window's picks)
        entries = store.removed()
        assert sorted((e["title"], e["count"]) for e in entries) == sorted([(a, 3), (b, 2)])
        assert all(e["can_return"] and e["roots"] == [root] for e in entries)
        assert all(e["days_left"] is None for e in entries)          # no file of theirs in the trash (store level)
        assert sorted(i for e in entries for i in e["trash_ids"]) == store.removed_under(root)
        assert store.removed_under(root + 1000) == []
        # read again, the folder brings nothing back (the exclusions) — Mattias's note 6
        assert _look(store, language, root, full=True)["added"] == 0 and _items(store) == 0
        store.restore(store.removed_under(root))
        assert _excluded(store) == 0 and store.removed() == [] and _items(store) == 5


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_list_leaves_out_a_skipped_folders_files_and_a_place_taken_again(language):
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("shows")
    _show(language, src, a)
    _show(language, src, b, n=2)
    with store:
        root, ids = _taken(store, language, src)
        store.skip_folder(os.path.join(src, b))                      # *Never read this folder*: Read again's to bring
        assert [e["title"] for e in store.removed()] == []
        mine = [i for i in ids if store.conn.execute("SELECT 1 FROM items WHERE id = ?", (i,)).fetchone()]
        rel = store.conn.execute("SELECT rel_path FROM items WHERE id = ?", (mine[0],)).fetchone()[0]
        store.remove([mine[0]])
        assert [(e["title"], e["count"]) for e in store.removed()] == [(a, 1)]
        # its place an item again (added again since): Put back would refuse it, so the list leaves it out
        entry = store.conn.execute("SELECT entry FROM trash WHERE item_id = ?", (mine[0],)).fetchone()[0]
        with store._writing():                                       # (a stand-in for the file read in again)
            store.conn.execute("INSERT INTO items (root_id, rel_path, rel_key, tier, ord, entry, title, availability, "
                               "changed_in, added_at) SELECT root_id, rel_path, ?, 'now', 0, entry, 'x', 'available', "
                               "0, removed_at FROM trash WHERE item_id = ?", (ls.path_key(rel), mine[0]))
        assert store.removed() == []
        assert entry


@pytest.mark.parametrize("language", LANGUAGES)
def test_days_left_follow_each_files_own_clock(language):
    """Each Remove's copy in the data folder's trash, its clock 0, 25 and 40 days old: 30, 5 and 0 days left (the purge
    takes it at 30); the file purged, its original still read: no days, but it can come back."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("shows")
    _show(language, src, a)
    with store:
        _root, ids = _taken(store, language, src)
        for i, age_days in zip(ids, (0, 25, 40)):
            rel = store.conn.execute("SELECT rel_path FROM items WHERE id = ?", (i,)).fetchone()[0]
            to = ls.trash_file(data_dir, rel)
            t = time.time() - age_days * 86400
            os.utime(os.path.join(data_dir, *to.split("/")), (t, t))
            store.remove([i], trashed_paths={i: to})
        entries = store.removed()
        assert sorted(e["days_left"] for e in entries) == [0, 5, ls.REMOVED_DAYS]
        trashed = store.conn.execute("SELECT trashed_path FROM trash WHERE item_id = ?", (ids[0],)).fetchone()[0]
        os.remove(os.path.join(data_dir, *trashed.split("/")))       # the purge took the newest one's file
        purged = [e for e in store.removed() if e["days_left"] is None]
        assert len(purged) == 1 and purged[0]["can_return"]             # its original is still in a folder read


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_file_with_no_trash_copy_and_no_original_cannot_come_back(language):
    """A 2.x-era file (no folder Surasura reads holds its original) removed with no copy in the trash: listed, but it
    would come back missing — the window greys its Put back."""
    store = migrated(language)
    with store:
        first = store.ids("now")[0]
        store.remove([first])
        entry = [e for e in store.removed() if first in [r["item_id"] for r in store.trash_rows(e["trash_ids"])]]
        assert len(entry) == 1 and not entry[0]["can_return"] and entry[0]["roots"] == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_through_the_writer_brings_the_files_back_and_one_undo_sends_them_away_again(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("shows")
    _show(language, src, a)
    with store:
        root, ids = _taken(store, language, src)
    heard = Heard()
    w = M.Writer(ls.StoreOpener(language, data_dir, store.user_files_dir, role="window"), language,
                 journal_file=M.journal_path(language), retry=0.05, words=WORDS, **heard.kw())
    w.start()
    try:
        w.remove(ids, label="removed")
        assert h.until(lambda: heard.saved)
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            entries = s.removed()
            assert [(e["title"], e["count"], e["days_left"]) for e in entries] == [(a, 3, ls.REMOVED_DAYS)]
            back = s.removed_under(root)
        w.restore(back, label="put back")
        assert h.until(lambda: len(heard.saved) == 2)
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            assert s.removed() == [] and _excluded(s) == 0
            assert s.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'available'").fetchone()[0] == 3
        w.undo(label="undo")
        assert h.until(lambda: heard.undone)
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            assert [e["count"] for e in s.removed()] == [3] and _items(s) == 0
    finally:
        w.finish(time.monotonic() + 5)


def test_the_looks_worker_answers_the_list_and_none_for_another_language():
    store, data_dir = _empty("ja")
    a = _SHOWS["ja"][0]
    src = _drive("shows")
    _show("ja", src, a, n=2)
    with store:
        root, ids = _taken(store, "ja", src)
        store.remove(ids)
    looks = source_looks.SourceLooks(ls.StoreOpener("ja", data_dir, store.user_files_dir, role="window"), "ja")
    try:
        got = []
        assert looks.removed(got.append)
        assert looks.removed_under(root, got.append)
        assert looks.removed(got.append, language="zh") is False      # another language's list: never this one's
        assert looks.idle(5)
        assert [e["count"] for e in got[0]] == [2] and got[1] == sorted(ids and got[0][0]["trash_ids"])
    finally:
        looks.close()
