"""Kura alpha 4's mutant pass, round 1: one test per survivor that a real bug would let through
(`tracks/logic/work/alpha4/mutants.log`; the judged ones are in `tracks/logic/reviews/A4B-register.md` § Mutants).

What a wrong answer would cost a learner, row by row:
  * an Undo of his own drop listed among his Removes (and put back as a second copy) — R1, R2;
  * a Put back that was undone missing from the list while Connect keeps its log — R11;
  * the days left above 30 for a file whose clock ran ahead, or the most generous file's days shown for a Remove whose
    oldest file goes first — R8, R9;
  * *Choose a folder* giving one file to two items, pointing an item at a file that isn't there, a crash losing its
    queued relink, or one item changed since making the whole Undo say "can't undo" — L1, L6, L5, L4;
  * every move after one busy moment rewriting the journal — P3;
  * *Find its new folder* refusing a folder that holds the show under other names — T2;
  * one show's own gone folder turned into a folder card, losing its lines' own answers — N4.
"""
import os
import shutil
import time

import pytest

from app import library_store as ls
from app.services import needs, source_looks
from tests import services_helpers as h
from tests.test_library_store_support import LANGUAGES, migrated
from tests.test_relink_many import _move_away, _rel
from tests.test_services_moves import LockHolder, journalled, lib, make_writer, short_lock_wait  # noqa: F401
from tests.test_services_needs import MISSING, WORKS, _works, view_of  # noqa: F401 (a fixture)
from tests.test_services_needs_folders import SHOWS, _eps, _kinds
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _write  # noqa: F401


def _trashed(store, item_id, age_days=0):
    rel = store.conn.execute("SELECT rel_path FROM items WHERE id = ?", (item_id,)).fetchone()[0]
    to = ls.trash_file(store.data_dir, rel)
    t = time.time() - age_days * 86400
    os.utime(os.path.join(store.data_dir, *to.split("/")), (t, t))
    return to


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_R2_an_undone_add_of_a_file_from_no_folder_never_shows_as_removed(language):
    store = migrated(language)
    with store:
        first = store.ids("now")[0]
        store.remove([first], trashed_paths={first: _trashed(store, first)}, by="undo", kind="undo_add")
        assert store.removed() == []


def test_R11_a_put_back_undone_shows_again_while_connects_log_is_kept(lib, make_writer):
    lib.store.register_reader("connect")                            # the log is written (by "undo" for an undo)
    w, heard = make_writer()
    first = lib.current()[0]
    w.remove([first], label="removed")
    assert h.until(lambda: len(heard.saved) == 1)
    w.restore(lib.store.removed()[0]["trash_ids"], label="put back")
    assert h.until(lambda: len(heard.saved) == 2)
    assert lib.store.removed() == []
    w.undo(label="undo")
    assert h.until(lambda: heard.undone)
    assert [e["count"] for e in lib.store.removed()] == [1]


@pytest.mark.parametrize("language", LANGUAGES)
def test_R8_R9_days_left_stay_within_30_and_name_the_first_file_to_go(language):
    store = migrated(language)
    with store:
        a, b, c = store.ids("now")[:3]
        store.remove([a, b], trashed_paths={a: _trashed(store, a, 25), b: _trashed(store, b, 0)})
        store.remove([c], trashed_paths={c: _trashed(store, c, -2)})          # its clock two days ahead
        days = sorted(e["days_left"] for e in store.removed())
        assert days == [5, ls.REMOVED_DAYS]


def test_L1_L6_two_items_never_take_one_file_and_a_missing_file_is_no_place(lib):
    a, b, c = lib.current()[:3]
    pairs = _move_away(lib, [a])
    gone = os.path.join(lib.data_dir, "moved", "not there.srt")
    _move_away(lib, [b, c], to="elsewhere")
    change = lib.store.relink_many([(a, pairs[0][1]), (b, pairs[0][1]), (c, gone)])
    assert [r["id"] for r in change.relinks] == [a]
    assert sorted(change.left) == sorted([(b, "another item's file"), (c, "no file there")])


def test_L5_a_relink_given_while_the_store_is_busy_is_journalled(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    ids = lib.current()[:2]
    pairs = _move_away(lib, ids)
    holder = LockHolder(lib.db)
    try:
        w.relink_many(pairs, label="2 found")
        assert h.until(lambda: journalled(lib.language) == [("relink_many", ids)])
    finally:
        holder.release()
    assert h.until(lambda: heard.saved)


def test_L4_one_item_changed_since_leaves_the_rest_of_the_relink_undone(lib, make_writer):
    w, heard = make_writer()
    a, b = lib.current()[:2]
    before_b = _rel(lib, b)[0]
    pairs = _move_away(lib, [a, b])
    w.relink_many(pairs, label="2 found")
    assert h.until(lambda: heard.saved)
    again = os.path.join(lib.data_dir, "again", "a.srt")            # a relinked again since, by another program
    os.makedirs(os.path.dirname(again), exist_ok=True)
    shutil.move(pairs[0][1], again)
    lib.store.relink(a, again)
    w.undo(label="undo")
    assert h.until(lambda: heard.undone or heard.notes)
    assert heard.undone and _rel(lib, b)[0] == before_b             # b went back; a, changed since, stays
    assert _rel(lib, a)[0].startswith("again/")


def test_P3_once_the_head_that_met_a_busy_store_lands_the_writer_is_not_stuck(lib, make_writer, short_lock_wait):
    w, heard = make_writer()
    goal = lib.ids("goal")
    holder = LockHolder(lib.db)
    try:
        w.move([goal[5]], "goal", before_id=goal[0], label="first")
        assert h.until(lambda: w._head_waits)
    finally:
        holder.release()
    assert h.until(lambda: heard.saved) and h.until(lambda: not w._head_waits)


@pytest.mark.parametrize("language", LANGUAGES)
def test_T2_a_folder_holding_the_show_under_other_names_is_never_refused(language):
    store, data_dir = _empty(language)
    show = "月影の旅人" if language == "ja" else "夜市小记"
    old = os.path.join(_drive("Downloads"), show)
    paths = [_write(os.path.join(old, f"{show} - {n:02d}.srt"), _text(language, n, extra="「月」")) for n in (1, 2)]
    with store:
        root = store.add_source(old)
        _look(store, language, root, first=True)
        renamed = os.path.join(_drive("NAS"), show)
        os.makedirs(renamed)
        for n, p in enumerate(paths, 1):
            shutil.copyfile(p, os.path.join(renamed, f"Episode {n}.srt"))   # renamed: only their sizes match
        shutil.rmtree(old)
        assert source_looks._holds_one(store, root, renamed) is True


def test_N4_one_shows_whole_folder_gone_stays_that_shows_card():
    spec = []
    from tests.test_services_needs import work
    work(30, SHOWS[0])
    spec.append((30, "Library/X/A", [f"{SHOWS[0]} - {k:02d}.ja.srt" for k in range(1, 13)],
                 {k: MISSING for k in range(12)}))
    for i in (1, 2):
        work(30 + i, SHOWS[i])
        spec.append((30 + i, f"Library/X/{'BC'[i - 1]}", _eps(SHOWS[i]), {}))
    out = needs.entries(view_of(spec))
    assert _kinds(out) == [needs.GONE]
