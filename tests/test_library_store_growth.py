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
    assert store.record_growth(first) == len(ids)
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
    assert all(s["added"]["prior"] for s in store.growth_of(ids).values())
    store.close()


# --- ✓ Done and Finished ------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_keeps_the_newest_generates_figures_once_through_undo_un_done_and_a_re_watch(language):
    """✓ Done keeps what the newest Generate counted of the episode then as its 'done'. Later Generates move 'last'
    only; Undo, an un-Done and a second Done (a re-watch) never rewrite it: it is what he understood the first time."""
    store = migrated(language)
    ep, other = store.ids("now")[:2]
    store.record_growth(_figures(store, [ep, other]))
    then = _snap(store, ep, "last")
    change = store.set_watched([ep])
    assert _snap(store, ep, "done") == then
    assert _snap(store, other, "done") is None, "only the marked episode"
    store.record_growth(_figures(store, [ep, other], base=300))
    store.undo(change)
    store.set_watched([ep])
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
        assert all(s["added"]["prior"] for s in again.growth_of(ids).values())
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
    store.record_growth(_figures(store, ids))
    assert ids and all(s["added"]["prior"] for s in store.growth_of(ids).values())
    store.close()


def _write_json(path, doc):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ls.finish_doc(doc), f, ensure_ascii=False, indent=2)
