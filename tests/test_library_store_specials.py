"""One show, one title: a specials folder is part of the title of the folder it sits in (Kura-G, 2026-11-06,
PROVISIONAL — a technical rule under Sonic's "one show, one title" and "point it at your library and it figures it
out"). The laptop try's Code Geass (report 061403, "comes out as 4 different entries rather than 2"): the source
`Code Geass/` holds `… R1/` and `… R2/` (the 2 he expects: two series, each its own title, as seasons are — 05 §5.3),
and each holds an `extras/` of picture dramas and creditless openings with no subtitle, which made the titles `… R1
Extras` and `… R2 Extras` (tiles 3 and 4).

The rule is by folders only (`library_store.specials_home`): `<folder>/Extras` (`Specials`, `SPs`, `OVA`, `OAD`) joins
the title of `<folder>`, when `<folder>` has one. Never by a name, so two shows that share words (the alpha's Peko Peko
Vlog beside another channel) never join here; a season stays its own title; a specials folder with no title above it
(`<show>/S01`, `<show>/S02`, `<show>/Specials`) stays `<show> Specials`. Titles made without the rule (a store made
before it; specials that came in before their show) are joined in the helper's run (`Store.join_specials`, a8's
`join_same_shows` way), each run reading only the titles changed since its last.

What a wrong answer would cost: Code Geass as four tiles for good; or the join taking what the user said apart (his
name, his split, his group, his *Keep apart*), moving an item, its order, its piece, its mark or its file, or a season
or another show swallowed. Every test runs for Japanese and Chinese, with real texts from tests/Test Resources/ under
the per-test SURASURA_TEST_ROOT.
"""
import json
import os

import pytest

from app import library_store as ls
from tests.test_library_store_sources import _empty, _found, _source_root  # noqa: F401
from tests.test_library_store_sources import _fresh_module_state  # noqa: F401  (each look a new run of the app)
from tests.test_library_store_support import LANGUAGES, names, pieces_ok, touch

_N = [0]


def _work_of(store, rel):
    return store.item(store.item_id(rel))["work_id"]


def _works(store):
    return {w: (t, json.loads(ts), fk) for w, t, ts, fk in
            store.conn.execute("SELECT id, title, titles, folder_key FROM works")}


def _place(store):
    """Everything the join must leave as it was: each item's tier, order, piece, pin, watched mark and file."""
    return store.conn.execute("SELECT id, rel_path, tier, ord, piece_id, pinned, watched FROM items ORDER BY id"
                              ).fetchall()


def _files(language, data_dir, src, folders):
    """Each `{folder below the source: [file names]}` as the scan finds it, in the order given -> (found, {folder:
    [its rels]}); every file its own real text."""
    found, out = [], {}
    for folder, files in folders.items():
        for name in files:
            _N[0] += 1
            f = _found(language, data_dir, src, folder, name, 300 + _N[0])
            found.append(f)
            out.setdefault(folder, []).append(f["rel"])
    return found, out


def _before_rule(store, root, found):
    """Taken in as a store made before this rule did: every specials folder a title of its own (no `_specials_work`),
    and its first helper run's mark taken off (the test's empty library's run set it)."""
    rule = ls.Store._specials_work
    ls.Store._specials_work = lambda self, rel, cache=None: None
    try:
        store.take_in(root, found, first=True)
    finally:
        ls.Store._specials_work = rule
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.SPECIALS_JOINED,))


def _geass(show):
    """His Code Geass's shape (made-up names): two series folders, each with its `extras/`."""
    return {f"{show} R1": [f"[Grp] {show} - {n:02d} (1080p).srt" for n in (1, 2)],
            f"{show} R1/extras": [f"[Grp] {show} Picture Drama 3.25.srt", f"[Grp] {show} Picture Drama 9.75.srt"],
            f"{show} R2": [f"{show} Hangyaku {n:02d}.srt" for n in (1, 2)],
            f"{show} R2/extras": [f"{show} Creditless OP1.srt"]}


def test_a_specials_folder_belongs_to_the_folder_it_sits_in_and_nothing_else_does():
    """The one rule, pure: the last part a specials folder with a folder above it -> that folder (as written, or as a
    folder key); a season, a movie, `Bonus`, a show NAMED with Extras, a specials folder alone -> None."""
    assert ls.specials_home("Code Geass R1/extras") == "Code Geass R1"
    assert ls.specials_home("code geass r1/extras") == "code geass r1"
    assert ls.specials_home("Show/Season 1/OVA") == "Show/Season 1"
    for folder in ("Show/Specials", "Show/SPs", "Show/SP", "Show/OAD", "Show/Extras"):
        assert ls.specials_home(folder) == "Show", folder
    for folder in ("Show/Season 2", "Show/S02", "Show/Movie", "Show/Bonus", "Show/Part 2", "Extras", "Show Extras",
                   "Peko Peko Vlog", "peko peko vlog - 【Japanese Podcast", "Show/Extras/NCOP", "", None):
        assert ls.specials_home(folder) is None, folder


@pytest.mark.parametrize("language", LANGUAGES)
def test_code_geass_two_series_each_with_extras_are_two_titles_in_one_take_in(language):
    """His shape in one take-in, the extras listed FIRST (take-in reads a folder before the folders below it): two
    titles, `<show> R1` and `<show> R2`, each holding its extras; their names are the series folders'."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[80]
    with store:
        root = store.add_source(src)
        shape = _geass(show)
        found, rels = _files(language, data_dir, src, {k: shape[k] for k in reversed(list(shape))})
        store.take_in(root, found, first=True)
        r1 = {_work_of(store, r) for f in (f"{show} R1", f"{show} R1/extras") for r in rels[f]}
        r2 = {_work_of(store, r) for f in (f"{show} R2", f"{show} R2/extras") for r in rels[f]}
        assert len(r1) == len(r2) == 1 and r1 != r2
        works = _works(store)
        assert works[r1.pop()][0] == f"{show} R1" and works[r2.pop()][0] == f"{show} R2"
        assert len(works) == 2
        assert pieces_ok(store) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_tier_folders_specials_added_first_join_the_show_and_a_sync_after_too(language):
    """The other ways in: an Add of a 2.x tier folder's files, the specials one FIRST (it gets the lower item id, so
    `_settle_works` reads it first unless it takes a folder before the folders below it) — one title; then a special
    found by the sync joins it too."""
    store, data_dir = _empty(language)
    show = names(language)[81]
    with store:
        paths = [touch(data_dir, f"HighPriority/{show}/Specials/{show} OVA - 01.srt"),
                 touch(data_dir, f"HighPriority/{show}/{show} - 01.srt"),
                 touch(data_dir, f"HighPriority/{show}/{show} - 02.srt")]
        store.insert(paths, "now")
        added = [store.item_id(os.path.relpath(p, data_dir).replace(os.sep, "/")) for p in paths]
        assert None not in added and added[0] < added[1]
        assert len({store.item(i)["work_id"] for i in added}) == 1
        touch(data_dir, f"HighPriority/{show}/Specials/{show} OVA - 02.srt")
        later = store.sync_disk()["added"]
        assert {store.item(i)["work_id"] for i in later} == {store.item(added[0])["work_id"]}
        assert [t for t, _ts, _fk in _works(store).values()] == [show]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_specials_folder_with_no_title_above_it_stays_its_own_and_seasons_stay_apart(language):
    """`<show>/S01`, `<show>/S02`, `<show>/Specials` with nothing in `<show>/` itself: three titles as before (the
    specials never guessed into a season), the specials named `<show> Specials`. A season's own `OVA/` joins that
    season only."""
    store, data_dir = _empty(language)
    src = _source_root()
    show, other = names(language)[82], names(language)[83]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {
            f"{show}/S01": [f"{show} - 01.srt"], f"{show}/S02": [f"{show} - 01.srt"],
            f"{show}/Specials": [f"{show} SP - 01.srt"],
            f"{other}/Season 1": [f"{other} - 01.srt"], f"{other}/Season 1/OVA": [f"{other} OVA - 01.srt"],
            f"{other}/Season 2": [f"{other} - 01.srt"]})
        store.take_in(root, found, first=True)
        work = {k: _work_of(store, v[0]) for k, v in rels.items()}
        works = _works(store)
        assert len({work[f"{show}/S01"], work[f"{show}/S02"], work[f"{show}/Specials"]}) == 3
        assert works[work[f"{show}/Specials"]][0] == f"{show} Specials"
        assert work[f"{other}/Season 1/OVA"] == work[f"{other}/Season 1"] != work[f"{other}/Season 2"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_shows_that_share_words_never_join(language):
    """The too-eager side (the alpha's Peko Peko): the rule reads folders, never names — `<show>`, a show named
    `<show> Extras` (no specials folder: a name), `<show> Cooking` with its own `Extras/`: three titles; the
    `Extras/` is `<show> Cooking`'s, never `<show>`'s; a `Bonus/` folder stays its own."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[84]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {
            show: [f"{show} - 01.srt"], f"{show} Extras": [f"{show} Extras - 01.srt"],
            f"{show} Cooking": [f"{show} Cooking - 01.srt"], f"{show} Cooking/Extras": [f"{show} Cooking SP - 01.srt"],
            f"{show}/Bonus": [f"{show} Bonus - 01.srt"]})
        store.take_in(root, found, first=True)
        work = {k: _work_of(store, v[0]) for k, v in rels.items()}
        assert work[f"{show} Cooking/Extras"] == work[f"{show} Cooking"]
        assert len({work[show], work[f"{show} Extras"], work[f"{show} Cooking"], work[f"{show}/Bonus"]}) == 4


@pytest.mark.parametrize("language", LANGUAGES)
def test_his_store_joins_once_and_nothing_else_moves(language):
    """His store as alpha 6 left it: four titles. The one-time join makes them two — the series folder's title kept,
    the extras title's names among its titles (a search finds it) — and leaves every item's tier, order, piece, pin,
    watched mark and file as they were; the order version stays (no Generate asked for). Once joined, a later run
    finds nothing, and a later picture drama goes to R1."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[85]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, _geass(show))
        _before_rule(store, root, found)
        ids = {k: _work_of(store, v[0]) for k, v in rels.items()}
        assert len(set(ids.values())) == 4
        extras_name = _works(store)[ids[f"{show} R1/extras"]][0]
        store.set_watched([store.item_id(rels[f"{show} R1/extras"][0])], True)
        before, order = _place(store), store.token()[1]
        gone = store.join_specials()
        assert sorted(gone) == sorted([ids[f"{show} R1/extras"], ids[f"{show} R2/extras"]])
        works = _works(store)
        assert set(works) == {ids[f"{show} R1"], ids[f"{show} R2"]}
        assert works[ids[f"{show} R1"]][0] == f"{show} R1" and extras_name in works[ids[f"{show} R1"]][1]
        assert {_work_of(store, r) for f in (f"{show} R1", f"{show} R1/extras") for r in rels[f]} == {ids[f"{show} R1"]}
        assert _place(store) == before and store.token()[1] == order
        assert all(os.path.exists(os.path.join(data_dir, *r.split("/"))) for rs in rels.values() for r in rs)
        assert ids[f"{show} R1"] in store.search(extras_name)[0]
        assert store.meta()[ls.SPECIALS_JOINED] == _top(store) and store.join_specials() == []
        assert store.meta()[ls.SPECIALS_JOINED] == _top(store), "its own joins: never read again"
        later, more = _files(language, data_dir, src, {f"{show} R1/extras": [f"[Grp] {show} Picture Drama 22.25.srt"]})
        store.take_in(root, later)
        assert _work_of(store, more[f"{show} R1/extras"][0]) == ids[f"{show} R1"]
        assert pieces_ok(store) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_users_own_names_groups_and_answers_win_over_the_join(language):
    """Nobody asked for this join: a specials title the user named stays his; one he kept apart from the series
    title stays apart; one the ids say is another show stays; one he put in a group with the series title stays
    (his answer: two titles in it). The helper's run touches nothing for them."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b, c, d = (names(language)[i] for i in (86, 87, 88, 89))
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {
            **{f"{s}": [f"{s} - 01.srt"] for s in (a, b, c, d)},
            **{f"{s}/Extras": [f"{s} SP - 01.srt"] for s in (a, b, c, d)}})
        _before_rule(store, root, found)
        ids = {k: _work_of(store, v[0]) for k, v in rels.items()}
        store.rename_work(ids[f"{a}/Extras"], f"{a} の特典")
        assert store.keep_apart([ids[b], ids[f"{b}/Extras"]])
        with store._command("test_ids", "sync") as cmd:
            store.conn.execute("UPDATE works SET anilist_id = 301 WHERE id = ?", (ids[c],))
            store.conn.execute("UPDATE works SET anilist_id = 302 WHERE id = ?", (ids[f"{c}/Extras"],))
            cmd.touch()
        pieces = [store.item(store.item_id(rels[f][0]))["piece_id"] for f in (d, f"{d}/Extras")]
        store.join(pieces, how="group")
        before = _works(store)
        assert store.join_specials() == []
        assert _works(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_special_taken_apart_after_the_join_stays_apart_and_its_next_file_follows_it(language):
    """*Not part of this title* is the user's way back from the join: the title it makes has no folder key, so no
    later run joins it again, and a new file in that extras folder goes where its neighbours are — his split."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[90]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {show: [f"{show} - 01.srt"],
                                                      f"{show}/Extras": [f"{show} SP - 01.srt"]})
        _before_rule(store, root, found)
        assert len(store.join_specials()) == 1
        split = store.split_work([store.item_id(rels[f"{show}/Extras"][0])], f"{show} SP")
        assert split is not None
        mine = _work_of(store, rels[f"{show}/Extras"][0])
        apart = _works(store)
        assert mine != _work_of(store, rels[show][0])
        with store._writing():
            store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.SPECIALS_JOINED,))
        assert store.join_specials() == [] and _works(store) == apart
        later, more = _files(language, data_dir, src, {f"{show}/Extras": [f"{show} SP - 02.srt"]})
        store.take_in(root, later)
        assert _work_of(store, more[f"{show}/Extras"][0]) == mine


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helpers_run_joins_his_store_and_the_window_reads_the_works(language):
    """The join is the helper's (`maintain`, after a8's), so his library gets it at the first helper run after the
    update; the window reads the kept titles again from the feed, and the merged-away ones go."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[91]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, _geass(show))
        _before_rule(store, root, found)
        ids = {k: _work_of(store, v[0]) for k, v in rels.items()}
        fed_before = dict(store.conn.execute("SELECT id, feed_in FROM works"))
        before = _place(store)
    user_files_dir = store.user_files_dir
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert {_work_of(again, r) for f in (f"{show} R1", f"{show} R1/extras") for r in rels[f]} == \
            {ids[f"{show} R1"]}
        assert _place(again) == before
        fed = {w for w, f in again.conn.execute("SELECT id, feed_in FROM works") if f > fed_before[w]}
        assert fed == {ids[f"{show} R1"], ids[f"{show} R2"]}
        gone = {i for k, i in again.conn.execute("SELECT kind, id FROM gone") if k == "work"}
        assert {ids[f"{show} R1/extras"], ids[f"{show} R2/extras"]} <= gone
        assert again.join_specials() == []
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_join_goes_on_across_its_commands_and_marks_the_store_only_at_the_end(language, monkeypatch):
    """Commands of `JOIN_BATCH` pairs (the window's writes go between them): with one pair a command, both of his
    extras titles are joined, and the store is marked only by the command that ends the list."""
    monkeypatch.setattr(ls, "JOIN_BATCH", 1)
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[92]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, _geass(show))
        _before_rule(store, root, found)
        marks = []
        merge = ls.Store._merge_into

        def watched(self, *a, **k):
            marks.append(self._meta().get(ls.SPECIALS_JOINED))
            return merge(self, *a, **k)
        monkeypatch.setattr(ls.Store, "_merge_into", watched)
        assert len(store.join_specials()) == 2
        assert marks == [None, None] and store.meta()[ls.SPECIALS_JOINED] is not None
        assert len(_works(store)) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_empty_or_new_library_is_marked_at_once_with_nothing_to_join(language):
    """A store with no specials title (an empty one, a new one): the first run marks it and joins nothing; a mark
    ahead of the store's feed (a store rebuilt under it) reads every title again."""
    store, _data_dir = _empty(language)
    with store:
        assert store.meta()[ls.SPECIALS_JOINED] == _top(store)
        with store._writing():
            store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.SPECIALS_JOINED,))
        assert store.join_specials() == [] and store.meta()[ls.SPECIALS_JOINED] == _top(store)
        with store._writing():
            store._set_meta({ls.SPECIALS_JOINED: _top(store) + 50})
        assert store.join_specials() == [] and store.meta()[ls.SPECIALS_JOINED] == _top(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_specials_that_came_in_before_their_show_join_it_at_the_next_helper_run(language):
    """Adversary #1: a look that found `<show>/Specials/` first (its show's copy locked, or the show downloaded
    later) made `<show> Specials`; the show's own folder came in at a later look, a title of its own. The next helper
    run (reading only the titles changed since its last) joins them; a run with nothing changed reads nothing."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[93]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {f"{show}/Specials": [f"{show} SP - 01.srt"]})
        store.take_in(root, found, first=True)
        assert store.join_specials() == []
        sp = _work_of(store, rels[f"{show}/Specials"][0])
        later, more = _files(language, data_dir, src, {show: [f"{show} - 01.srt", f"{show} - 02.srt"]})
        store.take_in(root, later)
        main = _work_of(store, more[show][0])
        assert main != sp
        assert store.join_specials() == [sp]
        assert {_work_of(store, r) for rs in (rels, more) for f in rs for r in rs[f]} == {main}
        assert _works(store)[main][0] == show
        reads = []
        execute = store.conn.execute
        store.conn = _Counting(store.conn, reads)
        try:
            assert store.join_specials() == []
        finally:
            store.conn = store.conn.inner
        assert not any("folder_key >" in q for q in reads), "nothing changed since: no title read"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_whose_title_was_merged_away_takes_its_specials_where_its_files_went(language):
    """Adversary #2: the user made `<show>` part of `<other>` (*Same title as…*: `<show>`'s folder key went with it).
    The helper's join and a new specials file give one answer: the title of `<show>/`'s files, `<other>`. A folder
    whose title went the same way and whose files the user then split into two titles gives none (adversary #6):
    its specials stay their own."""
    store, data_dir = _empty(language)
    src = _source_root()
    show, other, movies = names(language)[94], names(language)[95], names(language)[96]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {
            show: [f"{show} - 01.srt"], f"{show}/Extras": [f"{show} SP - 01.srt"], other: [f"{other} - 01.srt"],
            movies: [f"{movies} A.srt", f"{movies} B.srt"], f"{movies}/Extras": [f"{movies} SP - 01.srt"]})
        _before_rule(store, root, found)
        ids = {k: _work_of(store, v[0]) for k, v in rels.items()}
        store.merge_works(ids[other], [ids[show], ids[movies]])
        store.split_work([store.item_id(rels[movies][1])], f"{movies} B")
        assert store.join_specials() == [ids[f"{show}/Extras"]]
        assert _work_of(store, rels[f"{show}/Extras"][0]) == ids[other]
        assert _work_of(store, rels[f"{movies}/Extras"][0]) == ids[f"{movies}/Extras"]
        later, more = _files(language, data_dir, src, {f"{show}/OVA": [f"{show} OVA - 01.srt"],
                                                      f"{movies}/OVA": [f"{movies} OVA - 01.srt"]})
        store.take_in(root, later)
        assert _work_of(store, more[f"{show}/OVA"][0]) == ids[other]
        assert _work_of(store, more[f"{movies}/OVA"][0]) not in {_work_of(store, r) for r in rels[movies]}
        assert len({_work_of(store, r) for r in rels[movies]}) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_id_or_matched_cover_travels_from_a_specials_title_to_its_show(language):
    """Adversary #3: a specials title's AniList id is the OVA's entry, never the series': the join leaves the show
    with its own id (none here) and its own cover, never the OVA's; a cover the user chose for the specials still
    wins (nobody asked for the join)."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b = names(language)[97], names(language)[98]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {a: [f"{a} - 01.srt"], f"{a}/OVA": [f"{a} OVA - 01.srt"],
                                                      b: [f"{b} - 01.srt"], f"{b}/OVA": [f"{b} OVA - 01.srt"]})
        _before_rule(store, root, found)
        ids = {k: _work_of(store, v[0]) for k, v in rels.items()}
        with store._command("test_ids", "sync") as cmd:
            store.conn.execute("UPDATE works SET anilist_id = 999, cover_source = 'anilist', cover_ref = 'ova' "
                               "WHERE id = ?", (ids[f"{a}/OVA"],))
            store.conn.execute("UPDATE works SET cover_source = 'user', cover_ref = 'mine' WHERE id = ?",
                               (ids[f"{b}/OVA"],))
            cmd.touch()
        assert sorted(store.join_specials()) == sorted([ids[f"{a}/OVA"], ids[f"{b}/OVA"]])
        show_a, show_b = store._work_row(ids[a]), store._work_row(ids[b])
        assert show_a["anilist_id"] is None and show_a["cover_source"] in (None, "generated")
        assert show_b["cover_source"] == "user" and show_b["cover_ref"] == "mine"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_specials_title_of_another_type_stays_and_a_keep_apart_answer_moves_to_the_kept_title(language):
    """Two types are two titles (a book's `Extras/` beside a show stays its own, `_media_family`); and a *Keep apart*
    the user gave about the specials title and a third title is, after the join, about the show's title."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b, c = names(language)[99], names(language)[100], names(language)[101]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {a: [f"{a} - 01.srt"], f"{a}/Extras": [f"{a} SP - 01.srt"],
                                                      b: [f"{b} - 01.srt"], f"{b}/Extras": [f"{b} SP - 01.srt"],
                                                      c: [f"{c} - 01.srt"]})
        _before_rule(store, root, found)
        ids = {k: _work_of(store, v[0]) for k, v in rels.items()}
        with store._command("test_type", "sync") as cmd:
            store.conn.execute("UPDATE works SET media_type = 'book', media_type_by = 'user' WHERE id = ?",
                               (ids[f"{a}/Extras"],))
            cmd.touch()
        assert store.keep_apart([ids[f"{b}/Extras"], ids[c]])
        assert store.join_specials() == [ids[f"{b}/Extras"]]
        assert _work_of(store, rels[f"{a}/Extras"][0]) == ids[f"{a}/Extras"]
        assert sorted([ids[b], ids[c]]) in json.loads(store.meta()["kept_apart"])


class _Counting:
    """The store's connection, every statement's text kept (what a run read)."""

    def __init__(self, inner, out):
        self.inner, self.out = inner, out

    def execute(self, sql, *a):
        self.out.append(sql)
        return self.inner.execute(sql, *a)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _top(store):
    return store.conn.execute("SELECT MAX(feed_in) FROM works").fetchone()[0] or 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_folder_joining_its_shows_title_takes_its_specials_with_it_in_the_same_sync(language):
    """`<show>!` is a title; a 2.x tier's `<show>/` and its `Specials/` are found by one sync. `<show>/` joins the one
    title of its show (item 12, `_same_show_folder`), and its specials go where it went — read from the command's own
    answer for `<show>/`, since no title holds that folder key and its files have no title yet inside the command."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[102]
    with store:
        root = store.add_source(src)
        found, rels = _files(language, data_dir, src, {f"{show}!": [f"{show} - 01.srt"]})
        store.take_in(root, found, first=True)
        bang = _work_of(store, rels[f"{show}!"][0])
        touch(data_dir, f"HighPriority/{show}/{show} - 02.srt")
        touch(data_dir, f"HighPriority/{show}/Specials/{show} SP - 01.srt")
        added = store.sync_disk()["added"]
        assert len(added) == 2 and {store.item(i)["work_id"] for i in added} == {bang}
