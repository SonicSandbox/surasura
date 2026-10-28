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
def test_a_remove_of_several_titles_is_one_entry_with_its_files_and_comes_back_through_its_folder(language):
    """Alpha 5 (Mado): one Remove of two shows (the window's picks) is ONE entry — `title` None, `titles` 2, every
    file's trash id in it — never a line per title (a picks Remove of 120 Goal titles was 120 lines)."""
    store, _data = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("shows")
    _show(language, src, a)
    _show(language, src, b, n=2)
    with store:
        root, ids = _taken(store, language, src)
        store.remove(ids)                                   # one Remove of both shows (the window's picks)
        entries = store.removed()
        assert [(e["title"], e["titles"], e["count"]) for e in entries] == [(None, 2, 5)]
        assert all(e["can_return"] and e["roots"] == [root] for e in entries)
        assert all(e["days_left"] is None for e in entries)          # no file of theirs in the trash (store level)
        assert sorted(i for e in entries for i in e["trash_ids"]) == store.removed_under(root)
        assert entries[0]["trash_ids"] == sorted(entries[0]["trash_ids"])     # Put back's order: as removed
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
def test_a_removed_file_with_no_trash_copy_and_no_original_is_left_out(language):
    """A 2.x-era file (no folder Surasura reads holds its original) removed with no copy left in the trash: nothing of
    it can come back, so the list never offers it (Put back would bring back only a missing row)."""
    store = migrated(language)
    with store:
        first = store.ids("now")[0]
        store.remove([first])
        assert all(first not in [r["item_id"] for r in store.trash_rows(e["trash_ids"])] for e in store.removed())


@pytest.mark.parametrize("language", LANGUAGES)
def test_bring_back_on_one_folder_brings_only_that_folders_files(language):
    """One Remove of a title whose episodes sit in two folders: *Bring back* on folder A's line puts back A's file
    only — never B's, which he didn't ask about (its exclusion stays)."""
    store, _data = _empty(language)
    a = _SHOWS[language][0]
    first, second = _drive("first"), _drive("second")
    _write(os.path.join(first, a, f"{a} - 01.srt"), _text(language, 1, extra="「一」"))
    _write(os.path.join(second, a, f"{a} - 02.srt"), _text(language, 2, extra="「二」"))
    with store:
        root_a, ids_a = _taken(store, language, first)
        root_b, ids_b = _taken(store, language, second)
        store.remove(ids_a + ids_b)
        assert [e["count"] for e in store.removed()] == [2]           # one entry: one Remove of one title
        back = store.removed_under(root_a)
        assert [r["item_id"] for r in store.trash_rows(back)] == ids_a
        store.restore(back)
        assert _excluded(store) == 1 and [e["count"] for e in store.removed()] == [1]


@pytest.mark.parametrize("language", LANGUAGES)
def test_rows_written_before_the_why_go_by_their_exclusions_and_a_skipped_folder_never_shows(language):
    """A library from alpha 3: its trash rows carry no `why`. His own Remove left an exclusion for its original (on the
    list); a book's part given up or an undone add left none (off it); a skipped folder's files never show."""
    store, _data = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("shows")
    _show(language, src, a)
    _show(language, src, b, n=2)
    with store:
        _root, ids = _taken(store, language, src)
        store.skip_folder(os.path.join(src, b))
        mine = [i for i in ids if store.conn.execute("SELECT 1 FROM items WHERE id = ?", (i,)).fetchone()]
        store.remove(mine[:1])
        store.remove(mine[1:2], exclude=False)                       # as a book's part given up: no exclusion
        with store._writing():                                       # as alpha 3 wrote them: no `why`
            store.conn.execute("UPDATE trash SET item_state = json_remove(item_state, '$.why')")
        assert [(e["title"], e["count"]) for e in store.removed()] == [(a, 1)]
        assert [r["item_id"] for e in store.removed() for r in store.trash_rows(e["trash_ids"])] == mine[:1]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_original_in_a_folder_no_longer_read_is_no_way_back(language):
    """Removed with no copy left in the trash, its folder then no longer read (*Stop reading*): nothing of it can come
    back, so the list leaves it out (its folder's own line still counts it)."""
    store, _data = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("shows")
    _show(language, src, a, n=2)
    with store:
        root, ids = _taken(store, language, src)
        store.remove(ids)                                            # (store level: no copy in the trash)
        assert [e["count"] for e in store.removed()] == [2]
        store.stop_source(root)
        assert store.removed() == []
        assert len(store.removed_under(root)) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_single_title_remove_keeps_its_title_and_two_removes_are_two_entries(language):
    """Alpha 5: a Remove of one title is as before (its title, `titles` 1); two Removes are two entries, newest first,
    even of the same show; a Remove of two titles whose one title can't come back is that one title's entry."""
    store, _data = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("shows")
    _show(language, src, a)
    _show(language, src, b, n=2)
    with store:
        root, ids = _taken(store, language, src)
        of_a = sorted(i for i in ids if f"/{a}/" in store.item(i)["rel_path"])
        of_b = sorted(set(ids) - set(of_a))
        store.remove(of_a[:1])                              # a's episode 1, then a's episodes 2-3 (one title each)
        store.remove(of_a[1:])
        entries = store.removed()
        assert [(e["title"], e["titles"], e["count"]) for e in entries] == [(a, 1, 2), (a, 1, 1)]
        assert entries[0]["removed_at"] > entries[1]["removed_at"]
        store.remove(of_b)                                  # b's two: one Remove, one title
        assert [(e["title"], e["titles"], e["count"]) for e in store.removed()][0] == (b, 1, 2)


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_removes_in_one_clock_tick_stay_two_entries(language, monkeypatch):
    """Alpha 5 review: the list merges a Remove's titles by its `removed_at`; Windows' clock moves ~15 ms at a time,
    so two Removes in one tick had one stamp — one entry, and its Put back brought both back. `_now` never gives a
    stamp twice: two Removes of two titles each, the clock standing still, are two entries."""
    store, _data = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("shows")
    _show(language, src, a, n=2)
    _show(language, src, b, n=2)
    _show(language, src, a + " 2", n=1)
    _show(language, src, b + " 2", n=1)
    with store:
        _root, ids = _taken(store, language, src)
        shows = {}
        for i in ids:
            shows.setdefault(store.item(i)["rel_path"].split("/")[1], []).append(i)
        still = time.time()
        monkeypatch.setattr(ls.time, "time", lambda: still)
        store.remove(shows[a] + shows[b])
        store.remove(shows[a + " 2"] + shows[b + " 2"])
        entries = store.removed()
        assert [(e["title"], e["titles"], e["count"]) for e in entries] == [(None, 2, 2), (None, 2, 4)]
        assert entries[0]["removed_at"] > entries[1]["removed_at"]
