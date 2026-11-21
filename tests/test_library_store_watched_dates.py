"""Kura-WD (3.0.18; Sonic's ruling, the mining-ordering model's step 4): the store dates what the learner saw.

Connect's *Best* sentence ranks a line by how recently its learner saw it (tracks/logic/work/mining-ordering MODEL.md,
ADVERSARY.md F7): a show finished last week beats one finished 8 months ago. Before this, only a show moved to
Finished had a date (`graduated_at`); a watched episode had a flag and no date. Now:

  * each item's `watched_at` — stamped when it is marked watched (✓ Done: Up Next's, the row's; an arrival finished,
    which is recorded as watched), cleared when the mark is taken back (an un-Done; leaving Finished, Q1 A), and put
    back exactly by Undo — a status value like the mark itself, so one Undo takes both back;
  * the finished date is `graduated_at` (a Finished item's; None for *Earlier*);
  * `Store.seen_dates()` reads both per show, `Store.watched_dates()` per file — the ranking's read.

The column is added the way the copies' hash was (no schema change: an older Surasura never reads it), carried by the
JSON copy, a Remove's trash row and Repair. A mark made before it has no date (None), never a made-up one.

What a wrong answer would cost a learner: a Best sentence from a show seen months ago ranked as fresh (a stale date
after an un-Done or an Undo), every date lost on a new PC or a Repair, or a store an older build made that can't open.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real
words from tests/Test Resources/.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, library, migrated, roots, schema1_store


def _at(store, item_id):
    return store.conn.execute("SELECT watched_at FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def _watched(store, item_id):
    return store.conn.execute("SELECT watched FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def _when(stamp):
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def _show(store, item_id):
    item = store.item(item_id)
    return (f"w{item['work_id']}" if item.get("work_id") is not None
            else f"f{item['parent_folder']}" if item.get("parent_folder") else f"i{item_id}")


def _move_db_away(db):
    for suffix in ("", "-wal", "-shm"):                         # a new PC: the JSON copy alone
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")


# --- the watched date --------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_stamps_its_date_and_an_un_done_clears_it(language):
    """✓ Done dates the episode now (UTC, the store's own stamp, as `graduated_at`); taking the mark back clears it, and
    a second Done later is dated again, later — a re-watch is the newest sighting."""
    store = migrated(language)
    ep, other = store.ids("now")[:2]
    assert _at(store, ep) is None, "no mark, no date"
    before = datetime.now(timezone.utc)
    store.set_watched([ep])
    first = _at(store, ep)
    # (`_now` gives every stamp a microsecond of its own, a few past the clock inside one of Windows' ~15.6 ms ticks:
    # the upper bound has a second's room — the stress run met one past `datetime.now()`)
    assert first and before <= _when(first) <= datetime.now(timezone.utc) + timedelta(seconds=1)
    assert _at(store, other) is None, "only the marked episode is dated"
    store.set_watched([ep], False)
    assert _watched(store, ep) == 0 and _at(store, ep) is None
    store.set_watched([ep])
    assert _when(_at(store, ep)) > _when(first)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_second_done_on_a_watched_episode_keeps_its_first_date(language):
    """A Done on an episode already watched writes nothing (S19), its date included: the date is when it was first
    seen, never moved by a repeated press (a row's Done over a run of which some are watched)."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.set_watched([a])
    first = _at(store, a)
    store.set_watched([a, b])
    assert _at(store, a) == first and _at(store, b) > first
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_takes_a_done_and_its_date_back_and_an_un_done_undone_brings_the_first_date_back(language):
    """One Undo is one press back: an Undone Done leaves no date; an Undone un-Done brings back the date it had (never
    today's: the episode was seen then). Undoing the Undo (the value check on both values) gives a whole mark again —
    the mark 1 with its date, never a date written into the mark."""
    store = migrated(language)
    ep = store.ids("soon")[0]
    done = store.set_watched([ep])
    first = _at(store, ep)
    back = store.undo(done)
    assert _watched(store, ep) == 0 and _at(store, ep) is None
    store.undo(back)                                            # the Undo undone
    assert _watched(store, ep) == 1 and _at(store, ep) == first
    undone = store.set_watched([ep], False)
    assert _at(store, ep) is None
    again = store.undo(undone)
    assert _watched(store, ep) == 1 and _at(store, ep) == first, "the date it was seen, not now"
    store.undo(again)
    assert _watched(store, ep) == 0 and _at(store, ep) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_old_done_undone_after_a_re_watch_takes_the_new_date_with_its_mark(language):
    """Done, un-Done, Done again (a re-watch: a new date), then the FIRST Done's Undo: the mark goes back to 0 by the
    value check, and its date must go with it — never a mark 0 left holding the re-watch's date. A skipped mark is one
    value skipped: its date goes with it, never counted on its own (the window reads the count: `moves._refused`)."""
    store = migrated(language)
    ep = store.ids("now")[0]
    first = store.set_watched([ep])
    store.set_watched([ep], False)
    store.set_watched([ep])
    store.undo(first)
    assert _watched(store, ep) == 0 and _at(store, ep) is None
    store.set_watched([ep])
    rewatch = _at(store, ep)
    undone = store.set_watched([ep], False)
    store.set_watched([ep])                                     # watched again since: the un-Done's Undo is skipped
    again = _at(store, ep)
    out = store.undo(undone)
    assert _watched(store, ep) == 1 and _at(store, ep) == again != rewatch, "the mark and its date left as they are"
    assert out is not None and out.notes == ["1 item changed since and was left as it is"], "its date isn't a skip"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_arrival_finished_is_dated_watched_and_undo_takes_both_back(language):
    """W3.2: an arrival sent to Finished is recorded as already watched — and dated so, with its finished date; one
    Undo takes the tier, the mark and the date back."""
    store = migrated(language)
    came = store.ids("goal")[:2]
    store.set_tier(came, "arrivals")
    change = store.finish(came)
    for i in came:
        assert _watched(store, i) == 1 and _at(store, i)
        assert store.item(i)["graduated_at"]
    store.undo(change)
    assert all(store.item(i)["tier"] == "arrivals" and _watched(store, i) == 0 and _at(store, i) is None
               for i in came)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ["put_back", "move", "set_tier"])
def test_leaving_finished_clears_the_dates_with_the_stones_and_one_undo_puts_them_back(language, how):
    """Q1 A: a show put back from Finished clears its stones (its words come back) — and their dates; one Undo puts
    the show back in Finished with its stones and their very dates."""
    store = migrated(language)
    back = [i for i in store.ids("soon") if store.item(i)["parent_folder"]][:3]
    store.finish(back)
    store.set_watched(back)
    dates = {i: _at(store, i) for i in back}
    assert all(dates.values())
    change = {"put_back": lambda: store.put_back_finished(back),
              "move": lambda: store.move(back, "now"),
              "set_tier": lambda: store.set_tier(back, "soon")}[how]()
    assert all(_watched(store, i) == 0 and _at(store, i) is None for i in back)
    store.undo(change)
    assert {i: _at(store, i) for i in back} == dates
    assert all(store.item(i)["tier"] == "graduated" and _watched(store, i) == 1 for i in back)
    store.close()


# --- the read the ranking uses ------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_empty_library_or_one_with_nothing_seen_reads_no_dates(language):
    """Nothing watched and nothing finished: both reads are empty (the ranking's *unseen* for every line)."""
    store = migrated(language)
    assert store.seen_dates() == {} and store.watched_dates() == {}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_seen_dates_give_each_show_its_newest_watched_episode_and_its_finished_date(language):
    """Per show: the newest date among its watched episodes (an un-Done one no longer counts), whether any of it is in
    Finished, and the newest Finished date (None for *Earlier*: finished, the date unknown). Per file: each watched
    file's date. A show never seen is in neither."""
    store = migrated(language)
    eps = [i for i in store.ids("now") if store.item(i)["parent_folder"]]
    show = _show(store, eps[0])
    same = [i for i in eps if _show(store, i) == show]
    assert len(same) >= 3, "the library's first show has episodes to watch"
    store.set_watched([same[0]])
    store.set_watched([same[1]])
    store.set_watched([same[2]])
    store.set_watched([same[2]], False)                         # an un-Done: no longer seen
    newest = _at(store, same[1])
    finished = [i for i in store.ids("goal") if store.item(i)["parent_folder"]]
    done_show = _show(store, finished[0])
    done = [i for i in finished if _show(store, i) == done_show]
    store.finish(done)
    finished_at = max(store.item(i)["graduated_at"] for i in done)
    seen = store.seen_dates()
    assert seen[show] == {"watched_at": newest, "finished": False, "finished_at": None}
    assert seen[done_show] == {"watched_at": None, "finished": True, "finished_at": finished_at}
    assert set(seen) == {show, done_show}, "a show never seen is not there"
    assert store.watched_dates() == {same[0]: _at(store, same[0]), same[1]: newest}
    assert store.watched_dates([same[1], same[2]]) == {same[1]: newest}
    with store._writing():                                      # Finished *Earlier* (an import): no date
        store.conn.executemany("UPDATE items SET graduated_at = NULL WHERE id = ?", [(i,) for i in done])
    assert store.seen_dates()[done_show] == {"watched_at": None, "finished": True, "finished_at": None}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mark_made_before_the_dates_reads_as_watched_with_no_date(language):
    """A stone an older build made (the mark alone) is never given a made-up date: its show reads as seen, the date
    unknown, and the file isn't in the per-file dates."""
    store = migrated(language)
    ep = store.ids("now")[0]
    with store._writing():
        store.conn.execute("UPDATE items SET watched = 1 WHERE id = ?", (ep,))
    assert store.seen_dates() == {_show(store, ep): {"watched_at": None, "finished": False, "finished_at": None}}
    assert store.watched_dates() == {}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_seen_dates_take_the_newest_across_tiers_old_marks_and_finishes(language):
    """One show's episodes in Current and Soon: the newest date of them all, an undated old mark beside them never
    hiding a date; two of its files finished at different times: the later Finished date, not the first."""
    store = migrated(language)
    eps = [i for i in store.ids("now") if store.item(i)["parent_folder"]]
    show = _show(store, eps[0])
    same = [i for i in eps if _show(store, i) == show]
    store.move([same[-1]], "soon")                              # the same show, split across tiers
    store.set_watched([same[-1]])
    store.set_watched([same[0]])
    newest = _at(store, same[0])
    with store._writing():                                      # an older build's mark beside them: no date
        store.conn.execute("UPDATE items SET watched = 1 WHERE id = ?", (same[1],))
    assert store.seen_dates()[show]["watched_at"] == newest
    store.set_watched([same[0]], False)
    assert store.seen_dates()[show]["watched_at"] == _at(store, same[-1]), "the Soon episode's date, still seen"
    goal = [i for i in store.ids("goal") if store.item(i)["parent_folder"]]
    done_show = _show(store, goal[0])
    done = [i for i in goal if _show(store, i) == done_show]
    store.finish([done[1]])
    store.finish([done[0]])                                     # finished later: the newest date
    later = store.item(done[0])["graduated_at"]
    assert later > store.item(done[1])["graduated_at"]
    assert store.seen_dates()[done_show]["finished_at"] == later
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_date_an_older_build_left_behind_is_never_read(language):
    """An older Surasura's un-Done writes the mark alone, leaving its date: neither read gives it (the episode is
    unseen again), and a Done after it is dated afresh."""
    store = migrated(language)
    ep = store.ids("soon")[0]
    store.set_watched([ep])
    old = _at(store, ep)
    with store._writing():
        store.conn.execute("UPDATE items SET watched = 0 WHERE id = ?", (ep,))
    assert store.watched_dates() == {} and store.watched_dates([ep]) == {} and store.seen_dates() == {}
    store.set_watched([ep])
    assert _at(store, ep) > old
    store.finish([ep])                                          # and in Finished: finished, but not seen on that day
    with store._writing():
        store.conn.execute("UPDATE items SET watched = 0 WHERE id = ?", (ep,))
    assert store.seen_dates()[_show(store, ep)]["watched_at"] is None
    assert store.seen_dates()[_show(store, ep)]["finished"] is True
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_watched_dates_by_ids_read_none_duplicates_and_unknown_ids_plainly(language):
    """`ids` empty reads nothing; a repeated id once; an id the store doesn't hold is simply not there."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.set_watched([a])
    assert store.watched_dates([]) == {}
    assert store.watched_dates([a, a, b, 10 ** 9]) == {a: _at(store, a)}
    store.close()


# --- the column: an older store, the copy, a Remove, Repair ------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_older_store_gains_the_date_column_at_open_with_no_row_changed(language):
    """Additive, as the copies' hash: a store an older Surasura made gains `watched_at` (and its index) at the first
    open by a writer, every row as it was (the new column empty) and the schema version unchanged."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    assert store._dates_column()
    assert store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
                              (ls.ADDED_DATES,)).fetchone()
    store.set_watched([store.ids("now")[0]])
    path = store.db_path
    store.close()
    conn = sqlite3.connect(path)
    conn.execute(f"DROP INDEX {ls.ADDED_DATES}")                # the store as an older build left it
    conn.execute("ALTER TABLE items DROP COLUMN watched_at")
    conn.commit()
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert again._dates_column()
        names = [r[1] for r in again.conn.execute("PRAGMA table_info(items)")]
        now = again.conn.execute(f"SELECT {', '.join(n for n in names if n != 'watched_at')} FROM items "
                                 f"ORDER BY id").fetchall()
        assert now == rows and again.conn.execute("PRAGMA user_version").fetchone()[0] == version
        assert again.conn.execute("SELECT COUNT(*) FROM items WHERE watched_at IS NOT NULL").fetchone()[0] == 0
        assert again.seen_dates() and again.watched_dates() == {}, "the old mark: seen, no date"
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_store_gains_the_column_at_the_helpers_first_open_before_its_upgrade(language):
    """A 2.5–2.7 store (schema 1, no works yet) is opened by the helper before its upgrade adds `work_id`: the date's
    column and its index are made there with the hash's, none of that pass lost, and the upgraded store dates a Done."""
    _d, _u, doc = library(language, shows=2, episodes=3)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    conn = sqlite3.connect(db)
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        made = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()
    assert {"watched_at", "content_sha256", "work_id"} <= columns
    assert {ls.ADDED_DATES, ls.ADDED_HASH} <= made
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        ep = store.ids("now")[0]
        store.set_watched([ep])
        assert store.watched_dates() == {ep: _at(store, ep)}
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_still_without_the_column_marks_reads_and_writes_its_copy_as_before(language, monkeypatch):
    """A busy first open leaves the column to a later one: until then a Done, its Undo, both reads and the copy work as
    they did (no date anywhere), never an error."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    path = store.db_path
    store.close()
    conn = sqlite3.connect(path)
    conn.execute(f"DROP INDEX {ls.ADDED_DATES}")
    conn.execute("ALTER TABLE items DROP COLUMN watched_at")
    conn.commit()
    conn.close()
    monkeypatch.setattr(ls.Store, "_added_indexes", lambda self: None)     # the busy open
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert not store._dates_column()
        ep = store.ids("now")[0]
        change = store.set_watched([ep])
        assert _watched(store, ep) == 1
        assert store.watched_dates() == {} and store.seen_dates()[_show(store, ep)]["watched_at"] is None
        store.undo(change)
        assert _watched(store, ep) == 0
        store.set_watched([ep])
        doc, _v, _d = store.export_snapshot()
        fields = doc["surasura_library"]["items"]["fields"]
        assert all(r[fields.index("watched_at")] is None for r in doc["surasura_library"]["items"]["rows"])
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_dates_come_back_through_a_rebuild_from_the_copy_and_a_repair(language):
    """The JSON copy carries each item's `watched_at` beside `graduated_at` (its item records): a library rebuilt from
    it (a new PC) and one Repair rebuilt read the very same dates."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.set_watched(store.ids("now")[:2])
    store.finish(store.ids("goal")[:2])
    want = (store.seen_dates(), store.watched_dates())
    assert want[1] and any(v["finished_at"] for v in want[0].values())
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    _move_db_away(db)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert (store.seen_dates(), store.watched_dates()) == want
    store.close()
    ls.mark_damaged(db, "a test")                               # Repair
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert (store.seen_dates(), store.watched_dates()) == want
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_without_the_column_rebuilt_from_its_own_newer_copy_keeps_every_date(language, monkeypatch):
    """A database restored from a backup an older build made (no column) meets its own newer copy and is rebuilt from
    it in place, at an open too busy to add the column first: the rebuild makes the column itself and keeps each date
    (never a failed rebuild on every run of the helper)."""
    import shutil
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ep = store.ids("now")[0]
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)   # the copy written
    db = store.db_path
    store.checkpoint()
    store.close()
    shutil.copyfile(db, db + ".backup")
    conn = sqlite3.connect(db + ".backup")                      # the backup as an older build left it
    conn.execute(f"DROP INDEX {ls.ADDED_DATES}")
    conn.execute("ALTER TABLE items DROP COLUMN watched_at")
    conn.commit()
    conn.close()
    store = ls.open_store(language, data_dir, user_files_dir)
    store.set_watched([ep])                                     # the copy moves on past the backup, with a date
    want = store.watched_dates()
    assert want and ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.close()
    for suffix in ("-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    shutil.copyfile(db + ".backup", db)                         # restored
    with monkeypatch.context() as busy:
        busy.setattr(ls.Store, "_added_indexes", lambda self: None)
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.watched_dates() == want, "rebuilt from the newer copy, dates and all"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_episode_put_back_keeps_its_watched_date(language):
    """A Remove keeps the item's whole state in its trash row; Undo (or Put back) brings the episode back watched on
    the day it was watched."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.set_watched([ep])
    first = _at(store, ep)
    change = store.remove([ep])
    assert store.watched_dates() == {}
    store.undo(change)
    assert _watched(store, ep) == 1 and _at(store, ep) == first
    store.remove([ep])                                          # Removed again, then *Put back* from Removed
    trash = store.conn.execute("SELECT id FROM trash WHERE item_id = ? AND restored_at IS NULL", (ep,)).fetchone()[0]
    store.restore([trash])
    assert _watched(store, ep) == 1 and _at(store, ep) == first
    store.close()
