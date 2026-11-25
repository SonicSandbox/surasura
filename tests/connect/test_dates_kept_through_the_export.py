"""The library's dates Connect keeps (`connect/sentences._dates`) survive the store's own bookkeeping (L2-WASTE, 3.0.19).

A Generate or a redraw after a move starts the store's helper (`spawn_maintain`: the copy it owes) and reads the
library's dates on a thread of their own (E-FAST 6). The helper's export commits a second or two later — only its own
bookkeeping (`last_export_*`, `copy_dirty`), or a checkpoint folding the -wal into the file — and the store's file
stamp moves with it: the list then threw the dates away and read them again on the main thread (0.40 s at 20,000
files). Kept now while the store's own counter of what changed (`state_version`, its epoch and id) holds; any move,
mark or file added still reads them again.

What a wrong answer would cost a learner: a card weighed by yesterday's dates (a move or a ✓ Done kept out of the
dates), or the list waiting on the main thread for a read it already had. Japanese and Chinese, real names from
tests/Test Resources/, a real store under the per-test SURASURA_TEST_ROOT.
"""
import sqlite3

import pytest

from app import library_store as ls
from app.connect import sentences
from tests.test_library_store_support import LANGUAGES, migrated


@pytest.fixture
def reads(monkeypatch):
    """Each read of the library's dates (`_library`), counted; nothing kept from another test."""
    got = []
    real = sentences._library
    monkeypatch.setattr(sentences, "_library", lambda *a, **k: got.append(a[0]) or real(*a, **k))
    sentences._DATES.clear()
    sentences._AHEAD.clear()
    yield got
    sentences._DATES.clear()
    sentences._AHEAD.clear()


def _view(info):
    """A dates answer without its clock: each file's weight is a decay from now, so two reads differ in its last digits."""
    return {at: (v[0], round(v[1], 4)) + tuple(v[2:]) for at, v in info.items()}


def _fresh(language, reads):
    """The dates as a read made now gives them (nothing kept), without its clock (`_view`); not one of the counted."""
    n = len(reads)
    try:
        return _view(sentences._library(language, None, False, scored=True))
    finally:
        del reads[n:]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_exports_own_commit_after_a_move_keeps_the_dates_read_ahead(language, reads, monkeypatch):
    # why: the move the learner made before Generate owes the copy; the helper's export lands after the dates were
    # read ahead — its commit is bookkeeping only, so the read must stand (it was read again on the main thread)
    store = migrated(language)
    now = store.ids("now")
    store.set_tier(now[:1], "soon")                 # a move: the copy is owed
    assert store.export_due()
    counted = []
    real_state = ls.read_state
    monkeypatch.setattr(ls, "read_state", lambda *a: counted.append(1) or real_state(*a))
    first = sentences._dates(language, False)
    assert len(reads) == 1 and first[0]
    before = sentences._store_stamp(language)
    assert ls.export_copy(store) is True            # the helper's export: the copy written, its bookkeeping committed
    assert sentences._store_stamp(language) != before, "the export moved the store's file stamp"
    again = sentences._dates(language, False)
    assert len(reads) == 1, "the export's own commit threw the dates away"
    assert again[0] is first[0] and _view(again[0]) == _fresh(language, reads)
    assert len(counted) == 2, "the count asked once at the read, once when the stamp moved"
    assert sentences._dates(language, False)[0] is first[0] and len(reads) == 1, "kept under the new stamp too"
    assert len(counted) == 2, "the new stamp kept: the count not asked again"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_checkpoint_folding_the_wal_in_keeps_the_dates(language, reads):
    # why: the db rewritten and its -wal emptied by a checkpoint changes nothing the dates read
    store = migrated(language)
    store.set_watched(store.ids("now")[:1])
    first = sentences._dates(language, False)
    before = sentences._store_stamp(language)
    other = sqlite3.connect(store.db_path)          # (the store's own connection writes only inside its commands)
    try:
        other.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        other.close()
    assert sentences._store_stamp(language) != before
    assert sentences._dates(language, False)[0] is first[0] and len(reads) == 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("change", ["move", "done", "file"])
def test_a_move_a_mark_or_a_new_file_after_the_read_reads_the_dates_again(language, change, reads):
    # why: the counter is the store's own "something changed" — a move, a ✓ Done or a file taken in must never be
    # served from the dates read before it, even when the export's commit follows in the same breath
    store = migrated(language)
    now = store.ids("now")
    first = sentences._dates(language, False)
    assert len(reads) == 1
    if change == "move":
        store.set_tier(now[:1], "goal")
    elif change == "done":
        store.set_watched(now[:1])
    else:
        from tests.test_library_store_support import touch
        name = next(rel for rel in first[0]).rsplit("\\", 1)[-1].replace(".srt", "_追加.srt")
        touch(store.data_dir, f"{ls.FOLDER_OF_TIER['now']}/{name}", "追加\n")
        store.sync_disk()
    ls.export_copy(store)
    again = sentences._dates(language, False)
    assert len(reads) == 2, f"a {change} was served from the dates read before it"
    assert _view(again[0]) == _fresh(language, reads)
    if change != "move":
        assert _view(again[0]) != _view(first[0])
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_no_counter_to_read_a_changed_stamp_reads_the_dates_again(language, reads, monkeypatch):
    # why: a store whose counter can't be read (busy, damaged, gone) can't vouch for the dates: the old rule holds
    store = migrated(language)
    store.set_tier(store.ids("now")[:1], "soon")
    sentences._dates(language, False)
    monkeypatch.setattr(ls, "read_state", lambda *a, **k: None)
    ls.export_copy(store)
    sentences._dates(language, False)
    assert len(reads) == 2
    other = sqlite3.connect(store.db_path)          # the stamp moved again, the count unreadable then as now
    try:
        other.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        other.close()
    sentences._dates(language, False)
    assert len(reads) == 3, "two counts that can't be read are no match"
    store.close()
