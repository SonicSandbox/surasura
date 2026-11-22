"""Kura-GS (3.0.18; Sonic 2026-11-21, the journey's round 8): the store keeps what the learner understood of each item,
then — "what you would have understood when you added it vs what you understand now".

A Generate hands the store its own figures for every file it counted (the progressive pass's: the tokens known before
any file, the tokens counted — the window's *% known* — and the words not known, each once). The store keeps them as:

  * 'added' — the first Generate that counted the item, written once; `prior` when the item was in the library before
    the store began the snapshots (`growth_since`), so it is never a made-up *when you added it*;
  * 'last' — the newest Generate's, rewritten only when it moved (never in the copy);
  * 'done' — the newest Generate's figures at the item's ✓ Done or its move to Finished, whichever came first, written
    once: never by an Undo, never moved by a re-watch.

They outlive Remove (Put back keeps the item and its snapshots; a file added again is a new item and starts fresh),
travel in the JSON copy ('added' and 'done') and through Repair, and the table is added the way `made_words` was: no
schema change, an older Surasura never reads it.

What a wrong answer would cost a learner: a growth figure that was never true (a show he has had for months shown as
*when you added it* with today's number, a re-watch rewriting what he understood the first time), every snapshot
lost on a new PC or a Repair (history can't be rebuilt), or a store an older build made that can't open.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real
words from tests/Test Resources/.
"""
import os
import sqlite3

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, library, migrated, roots, schema1_store, touch


def _rel(store, item_id):
    return store.conn.execute("SELECT rel_path FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def _figures(store, ids, base=100):
    """A Generate's figures for `ids` as the analyzer hands them: {rel_path: (known, counted, unknown)} — each file
    its own numbers, so a mix-up between files shows."""
    return {_rel(store, i): (base + n, 2 * base + 3 * n, 40 + n) for n, i in enumerate(ids)}


def _snap(store, item_id, kind):
    got = store.growth_of([item_id], kinds=(kind,)).get(item_id, {}).get(kind)
    return None if got is None else (got["known"], got["counted"], got["unknown"])


def _move_db_away(db):
    for suffix in ("", "-wal", "-shm"):                         # a new PC: the JSON copy alone
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")


# --- a Generate's figures -------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_generate_is_each_items_added_and_a_later_one_moves_only_its_last(language):
    """The first Generate that counts an item writes its 'added' and its 'last'; a later Generate's other figures move
    only 'last' — 'added' is what it was then, for good. A file the store doesn't hold (moved away meanwhile) is passed
    by; a Generate whose figures moved nowhere writes nothing at all (no copy to write again)."""
    store = migrated(language)
    ids = store.ids("now") + store.ids("soon")
    first = _figures(store, ids)
    first["HighPriority/消えたフォルダ/gone.srt"] = (1, 2, 1)
    dirty = store._meta().get("copy_dirty", 0)
    assert store.record_growth(first) == len(ids)
    assert store._meta().get("copy_dirty", 0) > dirty, "a new 'added' goes out in the copy"
    for i in ids:
        assert _snap(store, i, "added") == _snap(store, i, "last") == first[_rel(store, i)]
    later = _figures(store, ids, base=150)
    dirty = store._meta().get("copy_dirty", 0)
    assert store.record_growth(later) == 0, "no new 'added': each item has one"
    for i in ids:
        assert _snap(store, i, "added") == first[_rel(store, i)], "'added' is written once"
        assert _snap(store, i, "last") == later[_rel(store, i)]
    assert store._meta().get("copy_dirty", 0) == dirty, "'last' alone never sends the copy out again"
    before = store.conn.execute("SELECT * FROM growth ORDER BY item_id, kind").fetchall()
    assert store.record_growth(later) == 0
    assert store.conn.execute("SELECT * FROM growth ORDER BY item_id, kind").fetchall() == before, "nothing moved"
    assert store.record_growth({}) == 0
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_in_the_library_before_the_snapshots_began_is_prior_and_one_added_after_is_not(language):
    """Never a made-up *when you added it*: every item the library held when the store began the snapshots gets its
    first Generate's figures as `prior` (the day they began); a file added after is the real thing."""
    store = migrated(language)
    data_dir, _u = roots(language)
    old = store.ids("now")
    since = store._meta()[ls.GROWTH_SINCE]
    show = _rel(store, old[0]).split("/")[1]
    new = store.insert([touch(data_dir, f"HighPriority/{show}/{show}_第09話.srt", f"{show} 9\n")], "now").added[0]
    assert store.item(new)["added_at"] > since
    store.record_growth(_figures(store, old + [new]))
    got = store.growth_of(old + [new])
    assert all(got[i]["added"]["prior"] for i in old)
    assert got[new]["added"]["prior"] is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_that_never_began_the_snapshots_begins_them_at_its_first_generate_every_item_prior(language):
    """A store with the table but no `growth_since` (a reset's fresh meta, a busy open that made the table elsewhere):
    its first Generate's write begins the snapshots now, and every item it holds is `prior` — never *when added*."""
    store = migrated(language)
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.GROWTH_SINCE,))
    ids = store.ids("now")
    store.record_growth(_figures(store, ids))
    assert ls.GROWTH_SINCE in store._meta()
    got = store.growth_of(ids)
    assert ids and len(got) == len(ids) and all(s["added"]["prior"] for s in got.values())
    store.close()


# --- ✓ Done and Finished ------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_keeps_the_newest_generates_figures_once_through_an_un_done_and_a_re_watch(language):
    """✓ Done keeps what the newest Generate counted of the episode then as its 'done'. Later Generates move 'last'
    only; an un-Done and a second Done (a re-watch) never rewrite it: it is what he understood the first time. (The
    Undo of the press itself takes it back: Kura-GS3's tests below.)"""
    store = migrated(language)
    ep, other = store.ids("now")[:2]
    store.record_growth(_figures(store, [ep, other]))
    then = _snap(store, ep, "last")
    store.set_watched([ep])
    assert _snap(store, ep, "done") == then
    assert _snap(store, other, "done") is None, "only the marked episode"
    store.record_growth(_figures(store, [ep, other], base=300))
    store.set_watched([ep], False)
    store.set_watched([ep])
    assert _snap(store, ep, "done") == then
    assert _snap(store, ep, "last") == _figures(store, [ep, other], base=300)[_rel(store, ep)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_episode_no_generate_counted_has_no_snapshot_when_it_is_done(language):
    """Nothing is invented: a Done on an episode no Generate counted yet (just added, or a store from before) keeps no
    'done', and a later Generate gives it an 'added' only."""
    store = migrated(language)
    ep = store.ids("soon")[0]
    store.set_watched([ep])
    assert store.growth_of([ep]) == {}
    store.record_growth(_figures(store, [ep]))
    assert set(store.growth_of([ep])[ep]) == {"added"}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_move_to_finished_keeps_its_figures_and_a_done_before_it_keeps_the_dones(language):
    """Finished is the other way an item leaves study: a show moved there keeps the newest figures as its 'done'; an
    episode already Done keeps its Done's (the first). An arrival finished at once (recorded watched) the same."""
    store = migrated(language)
    show = [i for i in store.ids("goal") if store.item(i)["parent_folder"]][:3]
    store.record_growth(_figures(store, show))
    store.set_watched([show[0]])
    done_first = _snap(store, show[0], "done")
    newest = _figures(store, show, base=500)
    store.record_growth(newest)
    store.finish(show)
    assert _snap(store, show[0], "done") == done_first
    for i in show[1:]:
        assert _snap(store, i, "done") == newest[_rel(store, i)]
    came = store.ids("soon")[:2]
    counted = _figures(store, came, base=700)
    store.record_growth(counted)
    store.set_tier(came, "arrivals")
    store.finish(came)
    assert all(_snap(store, i, "done") == counted[_rel(store, i)] for i in came)
    store.close()


# --- Remove, a new file, the reads -------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_episode_keeps_its_snapshots_through_put_back_and_one_added_again_starts_fresh(language):
    """A Remove keeps the item's id in its trash row: Undo and Put back bring it back with its snapshots. A file added
    again as a new item (after a Remove, its own name) is a new id: no snapshot until a Generate counts it."""
    store = migrated(language)
    data_dir, _u = roots(language)
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, [ep]))
    store.set_watched([ep])
    want = store.growth_of([ep], kinds=("added", "done", "last"))
    change = store.remove([ep])
    store.undo(change)
    assert store.growth_of([ep], kinds=("added", "done", "last")) == want
    rel = _rel(store, ep)
    store.remove([ep])
    trash = store.conn.execute("SELECT id FROM trash WHERE item_id = ? AND restored_at IS NULL", (ep,)).fetchone()[0]
    store.restore([trash])
    assert store.growth_of([ep], kinds=("added", "done", "last")) == want
    store.remove([ep])
    again = store.insert([touch(data_dir, rel, "また会えたね\n")], "now").added[0]
    assert again != ep and store.growth_of([again], kinds=("added", "done", "last")) == {}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_growth_of_reads_by_kind_and_by_ids_plainly(language):
    """The reads: every item with a snapshot of the kinds asked (default 'added' and 'done'; 'last' on asking), by ids
    (none, duplicates, unknown ids read plainly); an empty library or one no Generate counted reads {}."""
    store = migrated(language)
    assert store.growth_of() == {}
    ids = store.ids("now")[:3]
    store.record_growth(_figures(store, ids))
    store.set_watched([ids[0]])
    got = store.growth_of()
    assert set(got) == set(ids) and set(got[ids[0]]) == {"added", "done"} and set(got[ids[1]]) == {"added"}
    assert set(store.growth_of(kinds=("last",))[ids[2]]) == {"last"}
    assert store.growth_of([]) == {}
    assert set(store.growth_of([ids[1], ids[1], 999999])) == {ids[1]}
    snap = got[ids[1]]["added"]
    assert set(snap) == {"known", "counted", "unknown", "at", "prior"} and snap["at"].endswith("Z")
    store.close()


# --- older stores, the copy, Repair --------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_older_store_gains_the_table_at_a_writers_open_with_no_row_or_version_changed(language):
    """Additive, as `made_words`: a store an older Surasura made gains the table at the first open by a writer, and
    the day the snapshots begin (every item it holds `prior`), every item and the schema version as they were."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    path = store.db_path
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE growth")                           # the store as 3.0.17 left it
    conn.execute("DELETE FROM meta WHERE key = ?", (ls.GROWTH_SINCE,))
    conn.commit()
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert again._has_table(ls.GROWTH) and ls.GROWTH_SINCE in again._meta()
        assert again.conn.execute("SELECT * FROM items ORDER BY id").fetchall() == rows
        assert again.conn.execute("PRAGMA user_version").fetchone()[0] == version
        ids = again.ids("now")
        again.record_growth(_figures(again, ids))
        got = again.growth_of(ids)
        assert ids and len(got) == len(ids) and all(s["added"]["prior"] for s in got.values())
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_store_gains_the_table_at_the_helpers_first_open_and_keeps_snapshots_after_its_upgrade(language):
    """A 2.5–2.7 store (schema 1) opened by the helper before its upgrade: the table is made in that pass with the
    rest, the upgrade keeps it, and the upgraded store keeps a Generate's figures and a Done's."""
    _d, _u, doc = library(language, shows=2, episodes=3)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert store._has_table(ls.GROWTH) and ls.GROWTH_SINCE in store._meta()
        ep = store.ids("now")[0]
        store.record_growth(_figures(store, [ep]))
        store.set_watched([ep])
        assert set(store.growth_of([ep])[ep]) == {"added", "done"}
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_whose_open_left_the_table_out_marks_reads_and_writes_as_before(language, monkeypatch):
    """A busy first open leaves the table to a later one: until then a Done and its Undo work, the reads are empty,
    the copy goes out without it — and a Generate's write makes the table itself (every item `prior`)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    path = store.db_path
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE growth")
    conn.execute("DELETE FROM meta WHERE key = ?", (ls.GROWTH_SINCE,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(ls.Store, "_added_indexes", lambda self: None)     # the busy open
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        ep = store.ids("now")[0]
        store.undo(store.set_watched([ep]))
        assert store.growth_of() == {}
        doc, _v, _d = store.export_snapshot()
        assert ls.GROWTH not in doc["surasura_library"]["tables"]
        store.record_growth(_figures(store, [ep]))
        assert store.growth_of([ep])[ep]["added"]["prior"] is True
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_snapshots_come_back_through_a_rebuild_from_the_copy_and_a_repair_without_the_last(language):
    """History can't be rebuilt, so it travels: the JSON copy carries 'added' and 'done' and the day the snapshots
    began; a library rebuilt from it (a new PC) and a Repair read the very same — never a 'last', which the next
    Generate writes again (the copy stays the size of what it must keep)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")[:3]
    store.record_growth(_figures(store, ids))
    store.set_watched(ids[:1])
    store.finish(ids[1:2])
    want = store.growth_of()
    since = store._meta()[ls.GROWTH_SINCE]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    doc, _v, _d = store.export_snapshot()
    table = doc["surasura_library"]["tables"][ls.GROWTH]
    assert {r[table["fields"].index("kind")] for r in table["rows"]} == {"added", "done"}
    db = store.db_path
    store.close()
    _move_db_away(db)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.growth_of() == want and store._meta()[ls.GROWTH_SINCE] == since
    assert store.growth_of(kinds=("last",)) == {}
    store.close()
    ls.mark_damaged(db, "a test")                               # Repair
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.growth_of() == want and store._meta()[ls.GROWTH_SINCE] == since
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_from_before_the_snapshots_rebuilds_with_every_item_prior(language):
    """A copy an older Surasura wrote (no growth table, no `growth_since`) rebuilt here: the snapshots begin with the
    rebuild — every item it brings is `prior`, never *when you added it*."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    db = store.db_path
    store.close()
    _move_db_away(db)
    path = ls.manifest_path(user_files_dir)
    doc, _stat, _p = ls.read_manifest(path)
    lib = doc["surasura_library"]
    lib["tables"].pop(ls.GROWTH, None)                          # as 3.0.17 wrote it
    lib["meta"].pop(ls.GROWTH_SINCE, None)
    _write_json(path, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    ids = store.ids("now")
    show = _rel(store, ids[0]).split("/")[1]
    new = store.insert([touch(data_dir, f"HighPriority/{show}/{show}_第09話.srt", f"{show} 9\n")], "now").added[0]
    store.record_growth(_figures(store, ids + [new]))
    got = store.growth_of(ids + [new])
    assert ids and all(got[i]["added"]["prior"] for i in ids), "brought by the copy: from before"
    assert got[new]["added"]["prior"] is False, "added after the rebuild, before its first Generate: its own"
    store.close()


def _write_json(path, doc):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ls.finish_doc(doc), f, ensure_ascii=False, indent=2)


# --- the edges the review asked for -------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_prior_is_decided_to_the_microsecond_at_the_day_the_snapshots_began(language):
    """An item taken in at the very stamp the snapshots began (a build stamps both with one `now`) is from before;
    one taken in a microsecond after is its own."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    since = store._meta()[ls.GROWTH_SINCE]
    micro = int(since[-7:-1])
    assert micro < 999999, "a stamp with room for one more microsecond"
    later = since[:-7] + "%06dZ" % (micro + 1)
    with store._writing():
        store.conn.execute("UPDATE items SET added_at = ? WHERE id = ?", (since, a))
        store.conn.execute("UPDATE items SET added_at = ? WHERE id = ?", (later, b))
    store.record_growth(_figures(store, [a, b]))
    got = store.growth_of([a, b])
    assert got[a]["added"]["prior"] is True and got[b]["added"]["prior"] is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_un_done_of_an_episode_marked_before_any_generate_keeps_no_snapshot(language):
    """An episode marked watched before a Generate counted it, then counted (*Keep studying watched episodes*), then
    un-marked: taking a mark back writes no 'done' — only a mark set does."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.set_watched([ep])
    store.record_growth(_figures(store, [ep]))
    store.set_watched([ep], False)
    assert set(store.growth_of([ep], kinds=("added", "done"))[ep]) == {"added"}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_before_any_generate_taken_back_and_marked_again_keeps_the_figures_counted_in_between(language):
    """The first mark had no figures to keep (nothing invented); taken back, counted, marked again: that mark is the
    first with figures, so its 'done' is the count just before it, dated at that mark — not the first mark's day."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.set_watched([ep])
    first = store.growth_of([ep], kinds=("done",)).get(ep, {})
    store.set_watched([ep], False)
    store.record_growth(_figures(store, [ep], base=120))
    store.set_watched([ep])
    assert first == {}
    assert _snap(store, ep, "done") == _snap(store, ep, "last")
    got = store.growth_of([ep], kinds=("added", "done"))[ep]
    assert got["done"]["at"] >= got["added"]["at"]                # the second mark's day, after the count
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_snapshot_the_database_refuses_never_takes_back_the_learners_done(language):
    """The snapshot is the store's own bookkeeping: when SQLite refuses its write (a full disk, a constraint), the
    learner's ✓ Done still holds — only the snapshot is missing."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, [ep]))
    with store._writing():
        store.conn.execute("CREATE TEMP TRIGGER refuse_done BEFORE INSERT ON growth WHEN NEW.kind = 'done' "
                           "BEGIN SELECT RAISE(ABORT, 'refused'); END")
    store.set_watched([ep])
    watched, at = store.conn.execute("SELECT watched, watched_at FROM items WHERE id = ?", (ep,)).fetchone()
    assert watched and at is not None
    assert _snap(store, ep, "done") is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reimported_graduate_of_an_older_surasura_keeps_its_figures_as_done(language):
    """2.4.0's Graduate moved the file into Graduated/ and dropped its row; the store's reimport takes it to Finished
    — and, as every move to Finished, keeps its newest figures as its 'done'."""
    from tests.test_library_store_migration import _edit
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    graduated = ids[2]
    store.record_growth(_figures(store, ids))
    want = _snap(store, graduated, "last")
    old = _rel(store, graduated)
    new = "Graduated/" + old.split("/", 1)[1]
    os.makedirs(os.path.dirname(os.path.join(data_dir, new)), exist_ok=True)
    os.rename(os.path.join(data_dir, old), os.path.join(data_dir, new))

    def change(doc):
        s = doc["schedule"]
        s["PHASE_1_NOW"] = [e for e in s["PHASE_1_NOW"] if e["physical_path"] != old]

    _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.item(graduated)["tier"] == "graduated"
    assert _snap(store, graduated, "done") == want
    assert all(_snap(store, i, "done") is None for i in ids if i != graduated)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_more_than_one_chunk_of_items_is_written_marked_and_read_whole(language):
    """A long run of episodes marked at once and a read by ids both go 500 at a time: every one is kept and read."""
    from tests.test_library_store_support import big_store
    store = big_store(language, 1200)
    ids = store.ids("soon") + store.ids("goal")
    assert len(ids) > 1100
    store.record_growth(_figures(store, ids))
    store.set_watched(ids[:1050])
    got = store.growth_of(ids)
    assert len(got) == len(ids)
    assert sum(1 for v in got.values() if "done" in v) == 1050
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_fresh_library_starts_its_own_snapshots_and_put_back_brings_the_old_ones_back(language):
    """*Start a fresh library*: the snapshots go with the old library into its backup and begin again with the fresh
    one (a file read in again after it is its own, never `prior`); *Put back…* brings the old ones back exactly."""
    from tests.test_library_reset import _world
    from tests.test_sources_scan import _look
    store, data_dir, user_files_dir, src, root = _world(language)
    with store:
        ids = store.ids("now") + store.ids("soon")
        store.record_growth(_figures(store, ids))
        store.set_watched(ids[:1])
        before, since = store.growth_of(), store._meta()[ls.GROWTH_SINCE]
        assert before
        answer = ls.start_fresh(store)
        assert store.growth_of() == {} and store._meta()[ls.GROWTH_SINCE] > since
        for row in store.sources():
            _look(store, language, row["id"], first=True)
        fresh = store.ids("now") + store.ids("soon") + store.ids("goal") + store.ids("arrivals")
        assert fresh
        store.record_growth(_figures(store, fresh))
        assert all(v["added"]["prior"] is False for v in store.growth_of().values())
        ls.put_back_library(store, answer["backup"])
        assert store.growth_of() == before and store._meta()[ls.GROWTH_SINCE] == since


def test_the_generates_paths_leave_out_a_file_off_the_librarys_drive():
    """`_growth_figures`: each counted file by its path in the library (the store's `rel_path`); one with no path from
    the library's folder (another drive) is left out, never an error at the run's end."""
    from app import analyzer
    data_dir = os.path.join(os.environ["SURASURA_TEST_ROOT"], "data", "ja")
    inside = os.path.join(data_dir, "HighPriority", "喫茶店", "ep01.srt")
    drive = "R:" if data_dir[:1].upper() == "Q" else "Q:"
    elsewhere = os.path.join(drive + os.sep, "番組", "ep02.srt")
    got = analyzer._growth_figures(data_dir, [(inside, "now", 1, "subtitle"), (elsewhere, "now", 1, "subtitle")],
                                   [(5, 10, 3), (6, 12, 4)])
    assert got["HighPriority/喫茶店/ep01.srt"] == (5, 10, 3)
    if os.name == "nt":
        assert len(got) == 1, "another drive: no path, left out"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_generates_record_keeps_its_figures_after_the_analysed_mark_never_across_a_rebuild(language):
    """`analyzer.record_analysed`: the figures are kept only when the run read this epoch's store (a version means
    nothing across a rebuild), after the analysed mark — a failure in them never takes the mark back."""
    from app import analyzer
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    v = store.versions()
    figures = _figures(store, ids)
    analyzer.record_analysed(language, {"order_version": v["order_version"], "epoch": v["epoch"] + 1}, data_dir,
                             user_files_dir, growth=lambda: figures)
    assert store.growth_of() == {}, "another epoch: nothing kept"

    def broken():
        raise RuntimeError("the figures couldn't be worked out")
    analyzer.record_analysed(language, {"order_version": v["order_version"], "epoch": v["epoch"]}, data_dir,
                             user_files_dir, growth=broken)
    assert store.versions()["analysed_order_version"] == v["order_version"] and store.growth_of() == {}
    analyzer.record_analysed(language, {"order_version": v["order_version"], "epoch": v["epoch"]}, data_dir,
                             user_files_dir, growth=lambda: figures)
    assert set(store.growth_of()) == set(ids)
    store.close()


def test_the_windows_numbers_read_degrades_to_no_line_when_the_store_cant_answer():
    """`Numbers._read_growth`: a store that can't be opened, one without the read (an older handle) or one whose read
    fails leaves the hover with no growth line — never an error on the numbers' worker; an answer replaces the last,
    and a failed read keeps it."""
    from types import SimpleNamespace as NS
    from app.services import moves as M

    def opener(handle):
        return NS(mode="store", check=lambda: None, handle=lambda: handle)

    def fails(**_kw):
        raise sqlite3.OperationalError("database is locked")

    for handle in (None, object(), NS(growth_of=fails)):
        n = M.Numbers(opener(handle), "ja")
        n._read_growth()
        assert n.growth(1) is None
    n = M.Numbers(opener(NS(growth_of=lambda **_kw: {1: {"added": {"known": 1}}})), "ja")
    n._read_growth()
    assert n.growth(1) == {"added": {"known": 1}} and n.growth(2) is None

    def gone():
        raise OSError("the store went away")
    n.opener = NS(mode="store", check=gone, handle=lambda: None)
    n._read_growth()
    assert n.growth(1) == {"added": {"known": 1}}, "a failed read keeps the last answer"


# --- Kura-GS2: a whole write taken back, a file with no words, the read after a Generate ---------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_snapshot_failure_that_takes_back_the_whole_write_takes_back_the_whole_move(language):
    """G3, a store write is all or nothing: when SQLite takes back the whole write at the snapshot (a full disk, an I/O
    error — here a trigger's RAISE(ROLLBACK)), the Done or the move to Finished fails whole, never its rows taken back
    and the rest of it (the change, its Undo, the versions) saved line by line after. A refusal that takes back the one
    statement only keeps the learner's Done (the test above)."""
    store = migrated(language)
    show = [i for i in store.ids("goal") if store.item(i)["parent_folder"]][:3]
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, show + [ep]))
    with store._writing():
        store.conn.execute("CREATE TEMP TRIGGER fail_done BEFORE INSERT ON growth WHEN NEW.kind = 'done' "
                           "BEGIN SELECT RAISE(ROLLBACK, 'database or disk is full'); END")
    before = list(store.conn.iterdump())
    with pytest.raises(sqlite3.Error):
        store.finish(show)
    assert list(store.conn.iterdump()) == before, "nothing of the move saved"
    with pytest.raises(sqlite3.Error):
        store.set_watched([ep])
    assert list(store.conn.iterdump()) == before, "nothing of the Done saved"
    assert not store.conn.in_transaction
    with store._writing():
        store.conn.execute("DROP TRIGGER fail_done")
    store.finish(show)                                          # the next write goes through whole
    assert all(store.item(i)["tier"] == "graduated" and _snap(store, i, "done") for i in show)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_with_no_words_keeps_no_snapshot_until_a_generate_counts_its_words(language):
    """A file the Generate counted no words of (an empty subtitle) has no figure: no 'added' of 0 of 0 kept for good,
    nor a 'done' from it — no snapshot at all, so the journey shows no bar rather than a made-up one. The first
    Generate that counts its words is its 'added'; a later one that counts none moves nothing. A file whose words are
    all known (none unknown) has words: it is kept."""
    store = migrated(language)
    empty, other, known = store.ids("now")[:3]
    assert store.record_growth({_rel(store, empty): (0, 0, 0), _rel(store, known): (60, 60, 0),
                                **_figures(store, [other])}) == 2
    assert _snap(store, known, "added") == (60, 60, 0)
    assert store.growth_of([empty], kinds=("added", "done", "last")) == {}
    store.set_watched([empty])
    assert store.growth_of([empty], kinds=("added", "done", "last")) == {}
    words = _figures(store, [empty], base=300)
    assert store.record_growth(words) == 1
    assert _snap(store, empty, "added") == _snap(store, empty, "last") == words[_rel(store, empty)]
    assert store.record_growth({_rel(store, empty): (0, 0, 0)}) == 0
    assert _snap(store, empty, "last") == words[_rel(store, empty)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_generates_end_reads_its_snapshots_again_after_a_move_read_them_too_early(language):
    """A Generate writes its plan, then its snapshots: a move between the two reads the new plan, and the snapshots
    with it, before they are there. The Generate's end (`Services._generate_ended`) reads them again on the numbers'
    worker — after the snapshots' write — so the % hover's line is this Generate's, never none until the next one.
    A run whose list was written but not its report ends "failed" with its snapshots written too: read the same."""
    pytest.importorskip("PyQt6")
    import threading
    from types import SimpleNamespace as NS
    from app.qt import shell
    from app.services import moves as M
    store = migrated(language)
    numbers = M.Numbers(M.store_opener(language), language)

    def resync():
        raise RuntimeError("the numbers' re-read failed")          # (each step its own: the read still goes)
    numbers.resync = resync
    services = NS(closing=threading.Event(), gentle=None, writer=NS(numbers=numbers))
    try:
        for ep, outcome in zip(store.ids("now")[:2], ("current", "failed")):
            numbers._read_growth()                              # the move's plan read: no snapshot yet
            assert numbers.growth(ep) is None
            store.record_growth(_figures(store, [ep]))          # the Generate's write, after its plan
            shell.Services._generate_ended(services, None, outcome)
            read = threading.Event()
            numbers.worker.put(read.set)                        # (one worker: behind what the end queued)
            assert read.wait(20)
            got = (numbers.growth(ep) or {}).get("added")
            assert got is not None and (got["known"], got["counted"], got["unknown"]) == _snap(store, ep, "added"), \
                outcome
    finally:
        numbers.close()
        store.close()


# --- Kura-GS3: the snapshots written a chunk at a time -------------------------------------------------------------- #
# A Generate's end wrote every item's snapshot in ONE write: the store's write lock held 227 ms on a first Generate and
# 124 ms on a usual one at 20,000 items (Kura-GS2's F4), and a move or a ✓ Done in the window waited all that time. The
# rows now go `GROWTH_CHUNK` items a write (an item's 'last' and 'added' always in the same one), with a short pause
# after each so a save that waits gets in between.

import json
import subprocess
import sys
import time
from contextlib import contextmanager

from tests.test_library_store_support import big_store, names, subprocess_env

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spread(store):
    """A Generate's figures for every item, each its own (as `_figures`, without a read per item)."""
    rels = [r[0] for r in store.conn.execute("SELECT rel_path FROM items ORDER BY id")]
    return {rel: (100 + k % 50, 400 + k % 70, 30 + k % 20 + k // 1000) for k, rel in enumerate(rels)}


def _by_id(store, figs):
    key_to_id = {k: i for k, i in store.conn.execute("SELECT rel_key, id FROM items")}
    return {key_to_id[ls.path_key(rel)]: tuple(fig) for rel, fig in figs.items()}


def _watch_writes(monkeypatch, store, after=None):
    """Every outermost write `store` makes: [(seconds the write took, from the lock to its let-go; rows it changed)];
    `after(n)` is called once write n (from 1) has let the lock go."""
    seen = []
    real = ls.Store._writing

    @contextmanager
    def writing(self, *a, **kw):
        outer = self is store and not self._depth
        t, changes = time.perf_counter(), self.conn.total_changes
        with real(self, *a, **kw):
            yield
        if outer:
            seen.append((time.perf_counter() - t, self.conn.total_changes - changes))
            if after is not None:
                after(len(seen))
    monkeypatch.setattr(ls.Store, "_writing", writing)
    return seen


def _lasts(store):
    return {i: (v["last"]["known"], v["last"]["counted"], v["last"]["unknown"])
            for i, v in store.growth_of(kinds=("last",)).items()}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_20k_generates_snapshots_hold_the_write_lock_one_chunk_at_a_time(language, monkeypatch):
    """20,000 items: the first Generate (every 'added' + 'last') and a usual one (every 'last' moved) each write in
    ceil(20,000 / GROWTH_CHUNK) writes of at most a chunk's rows, and the longest single hold is a small part of the
    whole call (the one write was ~80 % of it on a first Generate before: 227 of 289 ms). Measured on this PC
    (Kura-GS3's register): the longest hold about one commit's floor."""
    big_store(language, 20_000).close()
    analyzer = ls.open_store(language, *roots(language), role="analyzer")
    first = _spread(analyzer)
    moved = {rel: (v[0] + 7, v[1], v[2] - 1) for rel, v in first.items()}
    writes = _watch_writes(monkeypatch, analyzer)
    for figs, rows_an_item in ((first, 2), (moved, 1)):
        writes.clear()
        t = time.perf_counter()
        analyzer.record_growth(figs)
        whole = time.perf_counter() - t
        assert len(writes) == -(-len(figs) // ls.GROWTH_CHUNK), writes
        assert max(rows for _s, rows in writes) <= ls.GROWTH_CHUNK * rows_an_item + 2     # (+ its meta rows)
        longest = max(s for s, _rows in writes)
        assert longest < 0.4 * whole, f"held {longest * 1000:.0f} ms of a {whole * 1000:.0f} ms call"
    assert _lasts(analyzer) == _by_id(analyzer, moved)
    analyzer.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reader_between_the_chunks_sees_each_items_older_or_newer_figures_never_a_mix(language, monkeypatch):
    """Between two writes a reader (the window's numbers, the journey) sees, for every item, either what it had
    before or this Generate's figures, whole: an item with an 'added' has its 'last' with it, and a 'last' is never
    another Generate's known with this one's counted. The figures differ in all three for every item."""
    monkeypatch.setattr(ls, "GROWTH_CHUNK", 300, raising=False)
    window = big_store(language, 1200)
    analyzer = ls.open_store(language, *roots(language), role="analyzer")
    first = _spread(analyzer)
    moved = {rel: (v[0] + 7, v[1] + 9, v[2] - 1) for rel, v in first.items()}
    old, new = _by_id(analyzer, first), _by_id(analyzer, moved)
    looks = []

    def look(_n):
        got = window.growth_of(kinds=("added", "last"))
        looks.append({i: {k: (v["known"], v["counted"], v["unknown"]) for k, v in kinds.items()}
                      for i, kinds in got.items()})
    writes = _watch_writes(monkeypatch, analyzer, after=look)
    analyzer.record_growth(first)
    assert len(writes) == 4 and len(looks) == 4
    for n, seen in enumerate(looks[:-1], 1):
        assert 0 < len(seen) < len(old), "a part of the set between the writes"
        for i, kinds in seen.items():
            assert kinds == {"added": old[i], "last": old[i]}, (n, i, kinds)
    looks.clear()
    analyzer.record_growth(moved)
    assert len(looks) == 4
    for n, seen in enumerate(looks[:-1], 1):
        assert len(seen) == len(old)
        assert 0 < sum(1 for i, k in seen.items() if k["last"] == new[i]) < len(new), n
        for i, kinds in seen.items():
            assert kinds["added"] == old[i] and kinds["last"] in (old[i], new[i]), (n, i, kinds)
    assert {i: k["last"] for i, k in looks[-1].items()} == new
    analyzer.close()
    window.close()


KILLED = ("import os, sys, json\n"
          "from contextlib import contextmanager\n"
          "from app import library_store as ls\n"
          "ls.GROWTH_CHUNK = 300\n"
          "store = ls.open_store(%(language)r, %(data)r, %(user)r, role='analyzer')\n"
          "figs = json.load(open(%(figs)r, encoding='utf-8'))\n"
          "real = ls.Store._writing\n"
          "@contextmanager\n"
          "def writing(self, *a, **kw):\n"
          "    outer = not self._depth\n"
          "    with real(self, *a, **kw):\n"
          "        yield\n"
          "    if outer:\n"
          "        os._exit(9)                     # the Generate's process gone right after its first write\n"
          "ls.Store._writing = writing\n"
          "store.record_growth({k: tuple(v) for k, v in figs.items()})\n"
          "os._exit(0)\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_generate_killed_between_chunks_leaves_a_part_and_the_next_generate_writes_the_rest(language, tmp_path):
    """The Generate's process dies after its first write (closed, crashed): what that write kept is whole, the rest
    is simply not there yet — and the next Generate, with the same figures, writes exactly what is missing, the
    'added' of the first part kept (written once) and every item `prior` as one whole write would have made it."""
    window = big_store(language, 1200)
    figs = _spread(window)
    path = tmp_path / "figs.json"
    path.write_text(json.dumps(figs, ensure_ascii=False), encoding="utf-8")
    data, user = roots(language)
    script = KILLED % dict(language=language, data=data, user=user, figs=str(path))
    out = subprocess.run([sys.executable, "-c", script], env=subprocess_env(), capture_output=True, text=True,
                         timeout=120, cwd=REPO)
    assert out.returncode == 9, out.stderr
    part = window.growth_of(kinds=("added", "last"))
    assert 0 < len(part) < len(figs), "the kill came between the writes"
    assert all(set(kinds) == {"added", "last"} for kinds in part.values())
    since = window._meta()[ls.GROWTH_SINCE]
    window.close()
    analyzer = ls.open_store(language, data, user, role="analyzer")
    assert analyzer.record_growth(figs) == len(figs) - len(part)
    whole = analyzer.growth_of(kinds=("added", "last"))
    assert len(whole) == len(figs)
    for i, kinds in part.items():
        assert whole[i]["added"] == kinds["added"], "written once"
    for i, fig in _by_id(analyzer, figs).items():
        got = whole[i]
        assert (got["last"]["known"], got["last"]["counted"], got["last"]["unknown"]) == fig
        assert got["added"]["prior"] is True
    assert analyzer._meta()[ls.GROWTH_SINCE] == since
    analyzer.close()


SLOW = ("import os, sys, json, time\n"
        "from contextlib import contextmanager\n"
        "from app import library_store as ls\n"
        "ls.GROWTH_CHUNK = 200\n"
        "store = ls.open_store(%(language)r, %(data)r, %(user)r, role='analyzer')\n"
        "figs = json.load(open(%(figs)r, encoding='utf-8'))\n"
        "real = ls.Store._writing\n"
        "n = [0]\n"
        "@contextmanager\n"
        "def writing(self, *a, **kw):\n"
        "    outer = not self._depth\n"
        "    with real(self, *a, **kw):\n"
        "        yield\n"
        "        if outer:\n"
        "            time.sleep(%(slow)r)            # a slow disk: each write holds the lock this much longer\n"
        "    if outer:\n"
        "        n[0] += 1\n"
        "        if n[0] == 1:\n"
        "            open(%(flag)r, 'w').close()\n"
        "ls.Store._writing = writing\n"
        "store.record_growth({k: tuple(v) for k, v in figs.items()})\n"
        "print(n[0])\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_in_the_window_during_the_generates_write_waits_one_chunk_not_the_whole_set(language, tmp_path):
    """The Generate's process writes its snapshots (six writes, each slowed to ~0.3 s as on a slow disk); the window
    marks two episodes ✓ Done once the first write is in. Its save gets in between two writes: it waits a write or two
    at most (a busy PC may miss one pause), never the five still to go, and the Generate still had writes to go when
    it was done. Each 'done' it kept is whole: the episode of the first write has this Generate's figures, the one of
    the last write none yet (its 'last' not written) — never a part."""
    window = big_store(language, 1200)
    figs = _spread(window)
    ids = _by_id(window, figs)
    early, late = list(ids)[50], list(ids)[1150]
    path, flag = tmp_path / "figs.json", str(tmp_path / "first-write")
    path.write_text(json.dumps(figs, ensure_ascii=False), encoding="utf-8")
    data, user = roots(language)
    slow = 0.3
    script = SLOW % dict(language=language, data=data, user=user, figs=str(path), flag=flag, slow=slow)
    gen = subprocess.Popen([sys.executable, "-c", script], env=subprocess_env(), cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 90
        while not os.path.exists(flag) and time.monotonic() < deadline and gen.poll() is None:
            time.sleep(0.001)
        assert os.path.exists(flag), "the Generate's first write never came"
        t0 = time.monotonic()
        window.set_watched([early, late])
        waited = time.monotonic() - t0
        lasts_then = len(_lasts(window))
    finally:
        try:
            out, err = gen.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            gen.kill()
            raise
    assert gen.returncode == 0 and out.strip() == "6", err
    assert waited < 2 * slow + 0.25, f"the Done waited {waited:.3f} s (a write is ~{slow} s; five were to go)"
    assert lasts_then < len(figs), "the Done saved while the Generate still had writes to go"
    assert len(_lasts(window)) == len(figs)
    assert window.item(early)["watched"] and window.item(late)["watched"]
    assert _snap(window, early, "done") == ids[early], "the first write's figures, whole"
    assert _snap(window, late, "done") is None, "its 'last' came after the Done"
    window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_fewer_items_than_a_chunk_are_one_write_as_before(language, monkeypatch):
    """A library smaller than a chunk (most are): the first Generate and a later one are one write each, as before."""
    store = migrated(language)
    analyzer = ls.open_store(language, *roots(language), role="analyzer")
    ids = store.ids("now") + store.ids("soon") + store.ids("goal")
    assert 0 < len(ids) < ls.GROWTH_CHUNK
    writes = _watch_writes(monkeypatch, analyzer)
    analyzer.record_growth(_figures(store, ids))
    assert len(writes) == 1
    later = _figures(store, ids, base=300)
    analyzer.record_growth(later)
    assert len(writes) == 2
    assert _snap(store, ids[-1], "last") == later[_rel(store, ids[-1])]
    analyzer.close()
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_empty_library_writes_no_snapshot_and_makes_no_write(language, monkeypatch):
    """A library with no items: nothing a Generate counted is held, so nothing is written — no write at all, no
    snapshot, no `growth_since` stamped by it."""
    window = big_store(language, 0)
    assert window.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    analyzer = ls.open_store(language, *roots(language), role="analyzer")
    writes = _watch_writes(monkeypatch, analyzer)
    counted = {f"Library/{w}/{w}_01.srt": (10, 40, 5) for w in names(language)[:3]}
    assert analyzer.record_growth(counted) == 0
    assert analyzer.record_growth({}) == 0
    assert writes == []
    assert window.growth_of(kinds=("added", "last", "done")) == {}
    analyzer.close()
    window.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reset_or_rebuild_between_the_chunks_ends_the_write_and_never_files_old_ids_in_the_new_library(
        language, monkeypatch):
    """The Generate read the old library's ids; a *Start a fresh library* or a rebuild between two writes gives the
    store another epoch (or store id), and its ids then name other files. The rest of the set is never written: the
    write that sees the new epoch ends it (`join_same_shows` reads its rows again in each command for the same
    reason). The epoch is moved here as the reset's fresh meta moves it (`_fresh_meta(…, epoch + 1, …)`)."""
    monkeypatch.setattr(ls, "GROWTH_CHUNK", 300, raising=False)
    window = big_store(language, 1200)
    analyzer = ls.open_store(language, *roots(language), role="analyzer")
    figs = _spread(analyzer)

    def reset(n):
        if n == 1:
            with window._writing():
                window._set_meta({"epoch": int(window._meta()["epoch"]) + 1})
    writes = _watch_writes(monkeypatch, analyzer, after=reset)
    made = analyzer.record_growth(figs)
    assert made == 300, "the first write's 'added' only"
    assert len(window.growth_of(kinds=("added", "last"))) == 300
    assert len(writes) == 2, "the second write saw the new epoch and wrote nothing"
    assert writes[1][1] == 0
    analyzer.close()
    window.close()


# --- Kura-GS3: the Undo of a ✓ Done takes back the snapshot that press made (Sonic 2026-11-22, OPEN 58a) ----------- #
# A Done pressed by mistake and undone at once left a 'done' snapshot for a watch that never happened. The Undo of the
# press (the toast's, right after it) now takes back that press's own snapshot — dated by the same stamp as its
# `watched_at` — inside the undo's write; an un-Done or a re-watch later is never an Undo, and keeps it.

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_undo_of_a_done_takes_back_the_snapshot_that_press_made(language):
    """Done, then its Undo at once: no 'done' left, the mark and its date back as they were, the 'added' and 'last'
    untouched; the other episode marked in the same press loses its own too."""
    store = migrated(language)
    ep, other = store.ids("now")[:2]
    store.record_growth(_figures(store, [ep, other]))
    before = store.growth_of([ep, other], kinds=("added", "last"))
    change = store.set_watched([ep, other])
    assert _snap(store, ep, "done") and _snap(store, other, "done")
    store.undo(change)
    assert _snap(store, ep, "done") is None and _snap(store, other, "done") is None
    assert not store.item(ep)["watched"] and store.item(ep)["watched_at"] is None
    assert store.growth_of([ep, other], kinds=("added", "last")) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_undone_then_done_again_later_keeps_one_snapshot_with_the_later_figures(language):
    """Done by mistake and undone; a Generate later counts the episode again; then the real Done: one 'done', this
    Done's figures (the later count), dated at it."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, [ep]))
    store.undo(store.set_watched([ep]))
    later = _figures(store, [ep], base=300)
    store.record_growth(later)
    store.set_watched([ep])
    rows = store.conn.execute("SELECT COUNT(*) FROM growth WHERE item_id = ? AND kind = 'done'", (ep,)).fetchone()[0]
    assert rows == 1
    assert _snap(store, ep, "done") == later[_rel(store, ep)]
    assert store.growth_of([ep])[ep]["done"]["at"] == store.item(ep)["watched_at"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_yesterday_and_an_un_done_today_keeps_yesterdays_snapshot(language):
    """An un-Done (the mark taken off later, its own press) is not the Done's Undo: yesterday's snapshot stays — and
    the Undo of that un-Done (the mark back) keeps it too, still yesterday's."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, [ep]))
    store.set_watched([ep])
    yesterday = "2026-11-21T09:30:00.000000Z"
    with store._writing():                                      # the Done was yesterday
        store.conn.execute("UPDATE items SET watched_at = ? WHERE id = ?", (yesterday, ep))
        store.conn.execute("UPDATE growth SET at = ? WHERE item_id = ? AND kind = 'done'", (yesterday, ep))
    want = _snap(store, ep, "done")
    store.record_growth(_figures(store, [ep], base=300))
    un_done = store.set_watched([ep], False)
    assert _snap(store, ep, "done") == want
    store.undo(un_done)
    assert store.item(ep)["watched"] and _snap(store, ep, "done") == want
    assert store.growth_of([ep])[ep]["done"]["at"] == yesterday
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_undo_of_a_re_watch_keeps_the_first_watchs_snapshot(language):
    """Only the press's own snapshot goes: a re-watch (Done, un-Done, Done again) wrote none of its own — the first
    Done's was kept — so the re-watch's Undo leaves the first one exactly."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, [ep]))
    store.set_watched([ep])
    first = store.growth_of([ep])[ep]["done"]
    store.set_watched([ep], False)
    store.record_growth(_figures(store, [ep], base=300))
    again = store.set_watched([ep])
    assert store.item(ep)["watched_at"] != first["at"]
    store.undo(again)
    assert not store.item(ep)["watched"]
    assert store.growth_of([ep])[ep]["done"] == first
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_undo_of_a_done_that_kept_no_snapshot_removes_nothing(language):
    """A file the Generate counted no words of keeps no figure (Kura-GS2), so its Done kept no 'done': the Undo has
    nothing to take back and goes through as before; the episode beside it, counted, loses only its own."""
    store = migrated(language)
    empty, ep = store.ids("now")[:2]
    figs = _figures(store, [ep])
    figs[_rel(store, empty)] = (0, 0, 0)
    store.record_growth(figs)
    change = store.set_watched([empty, ep])
    assert _snap(store, empty, "done") is None and _snap(store, ep, "done")
    store.undo(change)
    assert not store.item(empty)["watched"] and not store.item(ep)["watched"]
    got = store.growth_of([empty, ep], kinds=("added", "last", "done"))
    assert empty not in got and set(got[ep]) == {"added", "last"}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_whose_snapshot_cannot_be_taken_back_fails_whole(language):
    """The snapshot's removal is in the undo's own write: when the database refuses it, nothing of the Undo saves —
    the mark, its date and the snapshot all stay as the Done left them (whole or not at all, F1)."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.record_growth(_figures(store, [ep]))
    change = store.set_watched([ep])
    with store._writing():
        store.conn.execute("CREATE TEMP TRIGGER keep_done BEFORE DELETE ON growth WHEN OLD.kind = 'done' "
                           "BEGIN SELECT RAISE(ABORT, 'refused'); END")
    before = list(store.conn.iterdump())
    with pytest.raises(sqlite3.Error):
        store.undo(change)
    assert list(store.conn.iterdump()) == before, "nothing of the Undo saved"
    assert store.item(ep)["watched"] and _snap(store, ep, "done")
    with store._writing():
        store.conn.execute("DROP TRIGGER keep_done")
    store.undo(change)
    assert _snap(store, ep, "done") is None
    store.close()
