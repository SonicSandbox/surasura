"""User-made groups (LM11, Sonic's G1–G4, 2026-10-21): one piece rule — `Store.join(..., how=)`.

Why these matter: a learner wants several shows' or channels' episodes side by side in the list as one row (a "series
override") without touching any show: each episode keeps its own title, cover and AniList / channel. So a group is a
piece of `kind='group'` holding several works' items — still one contiguous run in one tier, never in Finished or New
arrivals. Finishing an episode takes it out of the group to Finished under its own title's piece; a group left holding
one title's episodes is a plain run again; Ungroup gives each title's runs back, in order, any time — after a restart
and a rebuild from the JSON copy too. A new episode of a grouped title never joins the group by itself: it lands after
the group, in a piece of its own. *Same show as…* (`how="titles"`) merges titles and is refused when their AniList,
TMDB or YouTube ids say they are different shows. Every command is one undo that puts the exact state back. Every test
runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words from tests/Test Resources/.
"""

import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, migrated, names, pieces_ok, read_doc, roots, touch,
                                              write_manifest)


def _piece(store, item_id):
    return store.item(item_id)["piece_id"]


def _members(store, piece):
    return [r[0] for r in store.conn.execute("SELECT id FROM items WHERE piece_id = ? ORDER BY ord, id", (piece,))]


def _kind(store, piece):
    row = store.conn.execute("SELECT kind FROM pieces WHERE id = ?", (piece,)).fetchone()
    return row[0] if row else None


def _work(store, item_id):
    return store.item(item_id)["work_id"]


def _state(store):
    """Everything an undo must put back: each tier's order, each item's piece and work, each piece's title and kind."""
    return ({t: store.ids(t) for t in ls.TIERS},
            dict(store.conn.execute("SELECT id, piece_id FROM items")),
            dict(store.conn.execute("SELECT id, work_id FROM items")),
            sorted(store.conn.execute("SELECT id, title, kind FROM pieces")))


def _shows(store, tier):
    """[(piece, members)] of the tier's show pieces (a folder's episodes), in order."""
    out = []
    for i in store.ids(tier):
        if store.item(i)["parent_folder"] and (not out or out[-1][0] != _piece(store, i)):
            out.append((_piece(store, i), None))
    return [(p, _members(store, p)) for p, _ in out]


def _library(language):
    """Two shows in 6+ Months (A, B: four episodes each), two in Soon, two in NOW; the tiers kept where the test puts
    them."""
    store = migrated(language, shows=2, episodes=4)
    store.set_soon_line(len(store.ids("now")))
    return store


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_titles_grouped_are_one_row_every_title_unchanged_and_one_undo_puts_it_all_back(language):
    """G1: a drop on another show makes a GROUP: one piece of kind 'group' at the first one's place, title NULL (the
    window derives "<first show> + N more"), each episode keeping its own title; one undo puts back every piece, kind,
    title and row."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    works = store.conn.execute("SELECT * FROM works ORDER BY id").fetchall()
    item_works = {i: _work(store, i) for i in ma + mb}
    before = _state(store)
    change = store.join([pa, pb], how="group")
    assert change is not None and change.kind == "join"
    assert _members(store, pa) == ma + mb and _kind(store, pa) == "group"
    assert store.conn.execute("SELECT title FROM pieces WHERE id = ?", (pa,)).fetchone()[0] is None
    assert {i: _work(store, i) for i in ma + mb} == item_works, "no work changes"
    cols = [r[1] for r in store.conn.execute("PRAGMA table_info(works)")]
    strip = lambda rows: [tuple(v for c, v in zip(cols, r) if c != "feed_in") for r in rows]   # noqa: E731
    assert strip(store.conn.execute("SELECT * FROM works ORDER BY id").fetchall()) == strip(works)
    assert pieces_ok(store) is None
    feed = {p["id"]: p for p in store.read_feed()["pieces"]}
    assert feed[pa]["kind"] == "group" and feed[pa]["title"] is None and pb not in feed
    store.undo(change)
    assert _state(store) == before
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_group_moves_and_changes_tier_as_one_row(language):
    """A group is one row: moved whole it keeps its id and kind (it never folds into a piece of one of its titles beside
    it), Promoted whole it stays one group, and each undo puts it back."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    before = _state(store)
    change = store.move(ma + mb, "soon")
    assert _members(store, pa) == ma + mb and _kind(store, pa) == "group"
    assert store.ids("soon")[:8] == ma + mb
    assert pieces_ok(store) is None
    tiered = store.set_tier(ma + mb, "now")
    assert {store.item(i)["tier"] for i in ma + mb} == {"now"} and _kind(store, pa) == "group"
    assert len({_piece(store, i) for i in ma + mb}) == 1
    assert pieces_ok(store) is None
    store.undo(tiered)
    store.undo(change)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_episode_finished_leaves_the_group_for_finished_under_its_own_title(language):
    """Sonic's rule: a finishing item leaves the group and goes to Finished under its own work's piece (a second one of
    that title joins the first there); the group keeps the rest; undo puts it back in the group."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    before = _state(store)
    first = store.finish([ma[0]])
    assert store.item(ma[0])["tier"] == "graduated"
    done = _piece(store, ma[0])
    assert done != pa and _kind(store, done) == "run" and _members(store, done) == [ma[0]]
    assert _members(store, pa) == ma[1:] + mb and _kind(store, pa) == "group"
    second = store.finish([ma[1]])
    assert _piece(store, ma[1]) == done, "under its own title's piece in Finished"
    assert pieces_ok(store) is None
    store.undo(second)
    store.undo(first)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_group_left_with_one_titles_episodes_is_a_run_again_and_undo_makes_it_a_group(language):
    """G4: a group holds only what you put in — finish every episode of one of its two titles and what is left is one
    title's run (kind 'run'); the undo makes it the group it was."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    before = _state(store)
    change = store.finish(ma)
    assert _members(store, pa) == mb and _kind(store, pa) == "run"
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_whole_group_finished_never_lives_in_finished(language):
    """A group never lives in Finished: finished whole, each title's episodes are a run of their own there; the undo
    brings the group back under its own id."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    before = _state(store)
    change = store.finish(ma + mb)
    kinds = {_kind(store, _piece(store, i)) for i in ma + mb}
    assert kinds == {"run"}
    assert len({_piece(store, i) for i in ma}) == 1 and len({_piece(store, i) for i in mb}) == 1
    assert _piece(store, ma[0]) != _piece(store, mb[0])
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_from_finished_never_forms_a_group_again(language):
    """Put back brings each title's episodes back to the top of Current as their own runs, never as the group they
    left."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    store.finish([ma[0], mb[0]])
    store.put_back_finished([ma[0], mb[0]])
    assert {_kind(store, _piece(store, i)) for i in (ma[0], mb[0])} == {"run"}
    assert _piece(store, ma[0]) != _piece(store, mb[0])
    assert _members(store, pa) == ma[1:] + mb[1:] and _kind(store, pa) == "group"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_ungroup_gives_each_titles_runs_back_in_order_and_undo_regroups(language):
    """Ungroup, any time: each run of one title's items becomes a run piece of its own, the order kept; nothing moves,
    nothing lost; its undo makes the group again (same id, same name)."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    (pc, mc), _d = _shows(store, "soon")
    store.join([pa, pb], how="group")
    store.join([pa, pc], how="group")                       # a third title, after the others
    store.move([ma[3]], "goal", after_id=mb[1])             # inside: A A A B B A B B C C C C
    assert _kind(store, pa) == "group"
    store.rename_piece(pa, names(language)[40])
    order = store.ids("goal")
    before = _state(store)
    change = store.ungroup(pa)
    assert store.ids("goal") == order, "nothing moves"
    runs = [ma[:3], mb[:2], [ma[3]], mb[2:], mc]
    pieces = [_piece(store, r[0]) for r in runs]
    assert all(_members(store, p) == r for p, r in zip(pieces, runs)), "each run of one title, in order"
    assert len(set(pieces)) == 5 and {_kind(store, p) for p in pieces} == {"run"}
    assert not store.conn.execute("SELECT 1 FROM pieces WHERE id = ?", (pa,)).fetchone()
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    assert store.ungroup(_shows(store, "now")[0][0]) is None, "a run has nothing to ungroup"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_group_survives_a_restart_a_rebuild_from_the_copy_and_a_repair(language):
    """A group is the user's: a store closed and opened, a new PC rebuilding from the JSON copy and Repair each keep it
    (kind, name, members, every title unchanged) — and Ungroup still gives each title's runs back after them."""
    store = _library(language)
    data_dir, user_files_dir = roots(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    store.move([ma[3]], "goal", after_id=mb[0])                 # A A A B A B B B: a mix inside
    label = names(language)[41]
    store.rename_piece(pa, label)
    want = (_members(store, pa), {i: _work(store, i) for i in ma + mb})
    db = store.db_path
    store.close()
    store = ls.open_store(language, data_dir, user_files_dir)   # a restart
    assert (_members(store, pa), {i: _work(store, i) for i in ma + mb}) == want and _kind(store, pa) == "group"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.close()
    for suffix in ("", "-wal", "-shm"):                         # a new PC: the JSON copy alone
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    piece = _piece(store, ma[0])
    assert _members(store, piece) == want[0] and _kind(store, piece) == "group"
    assert store.conn.execute("SELECT title FROM pieces WHERE id = ?", (piece,)).fetchone()[0] == label
    assert {i: _work(store, i) for i in ma + mb} == want[1]
    assert pieces_ok(store) is None
    store.close()
    ls.mark_damaged(db, "a test")                               # Repair
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    piece = _piece(store, ma[0])
    assert _members(store, piece) == want[0] and _kind(store, piece) == "group"
    assert pieces_ok(store) is None
    store.ungroup(piece)
    assert [_members(store, _piece(store, i)) for i in (ma[0], mb[0], ma[3], mb[1])] == \
        [ma[:3], [mb[0]], [ma[3]], mb[1:]]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_holding_a_one_title_group_or_a_group_in_finished_rebuilds_as_runs(language):
    """A copy an older version or a hand edit left with a group of one title, or a group in Finished, rebuilds as runs
    (the store's rule, never an error at the user's new PC)."""
    store = _library(language)
    data_dir, user_files_dir = roots(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.finish(mb)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    doc = read_doc(user_files_dir)
    pieces = doc["surasura_library"]["tables"]["pieces"]
    kind = pieces["fields"].index("kind")
    done = {r[0] for r in store_rows(doc, "piece_id", mb)}
    for row in pieces["rows"]:
        if row[0] == pa or row[0] in done:
            row[kind] = "group"
    write_manifest(user_files_dir, doc)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert {_kind(store, _piece(store, i)) for i in ma + mb} == {"run"}
    assert pieces_ok(store) is None
    store.close()


def store_rows(doc, field, ids):
    lib = doc["surasura_library"]
    fields = lib["items"]["fields"]
    return [(r[fields.index(field)],) for r in lib["items"]["rows"] if r[fields.index("id")] in ids]


@pytest.mark.parametrize("language", LANGUAGES)
def test_add_to_group_and_group_of_selected_episodes(language):
    """A drop onto a group adds the dropped piece after its last; *Group…* on selected episodes takes them out of their
    pieces (the rest of each stays one run) into one group at the first one's place. One undo each, exact."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    (pc, mc), (pd, md) = _shows(store, "soon")
    store.join([pa, pb], how="group")
    before = _state(store)
    change = store.group(piece_ids=[pa, pc])                    # a drop of Soon's C onto the group
    assert _members(store, pa) == ma + mb + mc and _kind(store, pa) == "group"
    assert all(store.item(i)["tier"] == "goal" for i in mc)
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    picked = store.group(item_ids=[md[1], md[2], mc[1]])        # two of D's, one of C's, in Soon
    target = _piece(store, mc[1])                               # the first in the list's order: C's
    assert _kind(store, target) == "group" and _members(store, target) == [mc[1], md[1], md[2]]
    assert store.ids("soon")[:6] == [mc[0], mc[1], md[1], md[2], mc[2], mc[3]]
    assert _members(store, _piece(store, mc[0])) == [mc[0]] and _members(store, _piece(store, mc[2])) == mc[2:]
    assert _members(store, _piece(store, md[0])) == [md[0], md[3]], "D's rest: side by side again, one run"
    assert {_work(store, i) for i in md} == {_work(store, md[0])} and _work(store, mc[1]) == _work(store, mc[0])
    assert pieces_ok(store) is None
    store.undo(picked)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_rename_a_group_and_back_to_its_derived_name(language):
    """G3: a group is renameable; None (or blank) is back to the derived "<first show> + N more" (title NULL); each is
    one undo; a run has no name of its own (its title's is renamed instead)."""
    store = _library(language)
    (pa, _ma), (pb, _mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    title = lambda: store.conn.execute("SELECT title FROM pieces WHERE id = ?", (pa,)).fetchone()[0]   # noqa: E731
    word = names(language)[42]
    named = store.rename_piece(pa, f"  {word} ")
    assert title() == word
    assert {p["id"]: p for p in store.read_feed()["pieces"]}[pa]["title"] == word
    seen = store.read_feed()["version"]
    cleared = store.rename_piece(pa, None)
    assert title() is None
    delta = store.read_feed(seen=seen, epoch=store.meta()["epoch"])
    assert {p["id"]: p for p in delta["pieces"]}[pa]["title"] is None, "the delta carries the renamed piece"
    assert store.rename_piece(pa, "") is None, "already the derived name"
    store.undo(cleared)
    assert title() == word
    store.undo(named)
    assert title() is None
    with pytest.raises(ValueError):
        store.rename_piece(_shows(store, "soon")[0][0], word)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_grouped_titles_new_episode_lands_after_the_group_in_its_own_piece(language):
    """G4: a grouped show's new episodes arrive on their own: placed after their show (`after-show`), one whose show's
    last episode sits inside a group lands after the group, in a piece of its own — never inside, never joined."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "soon")
    store.set_tier([ma[3]], "arrivals")                         # A's 4th waits in New arrivals
    assert store.item(ma[3])["tier"] == "arrivals"
    store.join([pa, pb], how="group")                           # A A A B B B B
    assert _members(store, pa) == ma[:3] + mb
    change = store.place([ma[3]], "after-show")
    assert change is not None
    soon = store.ids("soon")
    assert soon.index(ma[3]) == soon.index(mb[-1]) + 1, "after the group, never inside it"
    assert _piece(store, ma[3]) != pa and _members(store, _piece(store, ma[3])) == [ma[3]]
    assert _members(store, pa) == ma[:3] + mb
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_placing_rule_lands_a_grouped_titles_episode_after_the_group_never_in_it(language):
    """G4 for every placing rule: New arrivals' *After its show* for the title the group ends with (the row beside it
    is that title's own, still never joined), and for a title whose last row sits mid-group; a new file of a grouped
    title's folder (after its folder's last row); a Promote (after its folder's last row in the new tier) — each lands
    right after the group, in a piece of its own, and the group is left whole."""
    store = _library(language)
    data_dir, _u = roots(language)
    (pa, ma), (pb, mb) = _shows(store, "soon")
    store.set_tier([ma[3], mb[3]], "arrivals")
    store.join([pb, pa], how="group")                           # B B B A A A
    end = lambda: store.ids("soon").index(ma[2])                # noqa: E731  (the group's last row)
    store.place([ma[3]], "after-show")                          # A's last is the group's last: beside it, own piece
    assert store.ids("soon").index(ma[3]) == end() + 1 and _members(store, _piece(store, ma[3])) == [ma[3]]
    store.place([mb[3]], "after-show")                          # B's last is mid-group: after the group
    assert store.ids("soon").index(mb[3]) == end() + 1 and _members(store, _piece(store, mb[3])) == [mb[3]]
    store.move([mb[3]], "goal")
    store.set_tier([mb[3]], "soon")                             # Promote: after B's folder's last row in Soon
    assert store.ids("soon").index(mb[3]) == end() + 1 and _piece(store, mb[3]) != pb
    store.move([mb[3]], "goal")
    folder = store.item(mb[0])["rel_path"].rsplit("/", 1)[0]
    new = store.insert([touch(data_dir, f"{folder}/{names(language)[87]}_第09話.srt")], "soon").added[0]
    assert store.ids("soon").index(new) == end() + 1 and _piece(store, new) != pb     # a new file of B's folder
    assert _members(store, pb) == mb[:3] + ma[:3] and _kind(store, pb) == "group"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_inside_a_group_a_reorder_or_a_title_split_keeps_it_and_a_foreign_drop_cuts_it(language):
    """An episode moved within its group stays in it; *Not part of this title* inside a group keeps the group; a
    foreign row dropped inside cuts it (05 §5.2 rule 5) — a half holding one title is a run; the undo mends it."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    store.move([ma[0]], "goal", after_id=mb[1])                 # within: A A A B B A B B
    assert _members(store, pa) == ma[1:3] + [ma[3]] + mb[:2] + [ma[0]] + mb[2:] and _kind(store, pa) == "group"
    store.move([ma[0]], "goal", after_id=mb[3])                 # to the group's end, still within
    assert _piece(store, ma[0]) == pa
    store.split_work([mb[0]], names(language)[43])
    assert _piece(store, mb[0]) == pa and _kind(store, pa) == "group"
    assert pieces_ok(store) is None
    loose = next(i for i in store.ids("goal") if not store.item(i)["parent_folder"])
    before = _state(store)
    drop = store.move([loose], "goal", after_id=ma[3])          # A A A | L | B B B B A
    assert _members(store, pa) == ma[1:]
    assert _kind(store, pa) == "run" and _kind(store, _piece(store, mb[0])) == "group"
    assert pieces_ok(store) is None
    store.undo(drop)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_pieces_ok_takes_groups_and_flags_what_a_group_may_never_be(language):
    """`_pieces_ok` lifts "one piece = one work" for kind 'group' only: a group still is one run in one tier, never in
    Finished or New arrivals, and a run still holds one work."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    assert ls._pieces_ok(store.conn) is None
    with store._writing():                                      # a broken store, as a bug would leave it
        store.conn.execute("UPDATE pieces SET kind = 'run' WHERE id = ?", (pa,))
    assert "two works" in ls._pieces_ok(store.conn)
    with store._writing():
        store.conn.execute("UPDATE pieces SET kind = 'group' WHERE id = ?", (pa,))
        store.conn.execute("UPDATE items SET tier = 'graduated' WHERE piece_id = ?", (pa,))
    assert "Finished" in ls._pieces_ok(store.conn)
    with store._writing():
        store.conn.execute("UPDATE items SET tier = 'goal' WHERE piece_id = ?", (pa,))
        store.conn.execute("UPDATE items SET work_id = ? WHERE piece_id = ?", (_work(store, ma[0]), pa))
    assert "of one work" in ls._pieces_ok(store.conn)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("column, a, b", [("anilist_id", 101, 202), ("tmdb_id", 303, 404),
                                          ("youtube_channel", "UCabc", "UCdef")])
def test_same_show_is_refused_when_the_ids_say_two_shows_and_allowed_when_one_is_unset(language, column, a, b):
    """G1: *Same show as…* (`how="titles"`) and `merge_works` are refused, with a reason the window can show, when the
    two titles carry different AniList ids, TMDB ids or YouTube channels; one side unset, they merge; a group never
    asks (it changes no title)."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    wa, wb = _work(store, ma[0]), _work(store, mb[0])
    with store._writing():                                      # as a record's ids or a channel would set them
        store.conn.execute(f"UPDATE works SET {column} = ? WHERE id = ?", (a, wa))
        store.conn.execute(f"UPDATE works SET {column} = ? WHERE id = ?", (b, wb))
    before = _state(store)
    with pytest.raises(ValueError) as refused:
        store.join([pa, pb], how="titles")
    assert str(refused.value) == ls.TITLES_APART[column]
    with pytest.raises(ValueError) as merged:
        store.merge_works(wa, [wb])
    assert str(merged.value) == ls.TITLES_APART[column]
    assert _state(store) == before
    grouped = store.join([pa, pb], how="group")
    assert _kind(store, pa) == "group"
    store.undo(grouped)
    with store._writing():
        store.conn.execute(f"UPDATE works SET {column} = NULL WHERE id = ?", (wb,))
    change = store.join([pa, pb], how="titles")
    assert change is not None and {_work(store, i) for i in ma + mb} == {wa}
    assert _members(store, pa) == ma + mb and _kind(store, pa) == "run"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_parts_join_still_refuses_two_titles_and_a_group_never_lands_in_finished_or_new_arrivals(language):
    """`how="parts"` is today's join (two titles refused); a group onto a piece in Finished or New arrivals is refused
    (a group never lives there); an unknown `how` is a programming error."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    with pytest.raises(ValueError):
        store.join([pa, pb])
    store.finish(ma)
    with pytest.raises(ValueError):
        store.join([_piece(store, ma[0]), pb], how="group")
    with pytest.raises(ValueError):
        store.join([pb, _piece(store, ma[0])], how="sideways")
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_split_or_merge_inside_a_group_leaves_a_one_title_half_a_run(language):
    """*Split here* in a group: a half holding several titles stays a group, one holding one title is a run; *Same title
    as…* making a group's two titles one makes it a run. Each undo puts the exact state back."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    store.move([mb[0]], "goal", after_id=ma[1])                 # A A B A A B B B
    before = _state(store)
    change = store.split(pa, ma[2])                             # A A B | A A B B B
    assert _kind(store, pa) == "group" and _kind(store, _piece(store, ma[2])) == "group"
    store.undo(change)
    assert _state(store) == before
    change = store.split(pa, mb[1])                             # A A B A A | B B B
    assert _kind(store, pa) == "group" and _kind(store, _piece(store, mb[1])) == "run"
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    merged = store.merge_works(_work(store, ma[0]), [_work(store, mb[0])])
    assert _kind(store, pa) == "run" and _members(store, pa) == ma[:2] + [mb[0]] + ma[2:] + mb[1:]
    assert pieces_ok(store) is None
    store.undo(merged)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_nudge_jumps_a_group_whole_and_moves_within_one(language):
    """▲▼ past a group jumps it whole (never lands inside: that would cut it); within a group it swaps neighbours and
    the episode stays in the group."""
    store = _library(language)
    (pa, ma), (pb, mb) = _shows(store, "goal")
    store.join([pa, pb], how="group")
    loose = next(i for i in store.ids("goal") if not store.item(i)["parent_folder"])
    assert store.ids("goal").index(loose) > store.ids("goal").index(mb[3])
    store.nudge([loose], "up")
    goal = store.ids("goal")
    assert goal.index(loose) == goal.index(ma[0]) - 1, "before the group's first row"
    assert _members(store, pa) == ma + mb and _kind(store, pa) == "group"
    store.nudge([ma[1]], "down")
    assert _piece(store, ma[1]) == pa and store.ids("goal").index(ma[1]) == store.ids("goal").index(ma[2]) + 1
    assert pieces_ok(store) is None
    store.close()
