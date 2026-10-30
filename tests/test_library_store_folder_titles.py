"""A season folder's title (alpha 6's try: a show's seasons in the Finished tab read as their folder paths, `<show>/S01`,
and none got a cover). A work is named by its folder below the tier (L2.2 05 §5.3 (4)) through one rule,
`episode_names.folder_title`: a season or specials folder is named with the show above it (`<show> Season 1`), any
other folder as written; the path stays among the work's other titles. A store that already holds path titles gets
them once, in the helper's run (`Store.retitle_folder_works`).

What a wrong answer would cost: a title that reads as a path for good (a work is never renamed by a scan), a cover
search that asks AniList for `S01`, a search for the old path that finds nothing, a title the user named renamed under
them, or a retitle that moves an item, its order or its folder key (one title split in two, a Generate for nothing).
Every test runs for Japanese and Chinese alike, with real subtitles and texts from tests/Test Resources/ under the
per-test SURASURA_TEST_ROOT.
"""
import json

import pytest

from app import library_store as ls
from app.services import covers_online
from tests.test_library_store_sources import _empty, _found, _source_root  # noqa: F401
from tests.test_library_store_sources import _fresh_module_state  # noqa: F401  (each look a new run of the app)
from tests.test_library_store_support import LANGUAGES, names


def _work_of(store, rel):
    return store.item(store.item_id(rel))["work_id"]


def _works(store):
    return {w: (t, json.loads(ts), u) for w, t, ts, u in
            store.conn.execute("SELECT id, title, titles, title_by_user FROM works")}


def _take_seasons(store, language, data_dir, root, src, show):
    """`<show>/Season 1`, `<show>/S02`, `<show>/第3期` and `<show>/Specials` below the source, one episode each, as the
    look copies them (`Library/<show>/<season folder>/…`) -> {folder below the tier: its file's rel}."""
    found = {}
    for n, season in enumerate(("Season 1", "S02", "第3期", "Specials"), 1):
        f = _found(language, data_dir, src, f"{show}/{season}", f"{show} - 0{n}.srt", n)
        found[f"{show}/{season}"] = f
    store.take_in(root, list(found.values()), first=True)
    return {below: f["rel"] for below, f in found.items()}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_season_folders_new_title_is_its_show_and_season_and_search_still_finds_its_path(language):
    """The Finished tab read `<show>/S01`: a new work by a season folder is `<show> Season N` (written out for season
    1 too), a specials folder `<show> Specials`; each season stays its own title (L2.2 05: two seasons, two titles) and
    the path is among its other titles, so a search for either finds it."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[53]
    with store:
        root = store.add_source(src)
        rels = _take_seasons(store, language, data_dir, root, src, show)
        works = _works(store)
        got = {below: works[_work_of(store, rel)] for below, rel in rels.items()}
        assert {below: t for below, (t, _ts, _u) in got.items()} == {
            f"{show}/Season 1": f"{show} Season 1", f"{show}/S02": f"{show} Season 2", f"{show}/第3期": f"{show} Season 3",
            f"{show}/Specials": f"{show} Specials"}
        assert all(ts == [below] and not u for below, (_t, ts, u) in got.items()), "the path kept, nobody's name"
        assert len({_work_of(store, rel) for rel in rels.values()}) == 4, "each season its own title"
        for below, rel in rels.items():
            wid = _work_of(store, rel)
            assert wid in store.search(below)[0] and wid in store.search(got[below][0])[0]
        # a later episode of a season joins its title by the folder key, the title unchanged
        later = _found(language, data_dir, src, f"{show}/S02", f"{show} - 12.srt", 12)
        store.take_in(root, [later])
        assert _work_of(store, later["rel"]) == _work_of(store, rels[f"{show}/S02"])
        assert _works(store)[_work_of(store, later["rel"])][0] == f"{show} Season 2"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_folder_or_any_other_folder_keeps_its_name_as_written(language):
    """Only a season or specials folder is named anew: `<show>` is `<show>` (nothing else kept), and a folder that is
    no season (`<show>/Part 2`, a split cour's) stays as written — that is the grouping question, not this one."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        one = _found(language, data_dir, src, w[54], "01.srt", 1)
        part = _found(language, data_dir, src, f"{w[55]}/Part 2", "13.srt", 2)
        store.take_in(root, [one, part], first=True)
        works = _works(store)
        assert works[_work_of(store, one["rel"])][:2] == (w[54], [])
        assert works[_work_of(store, part["rel"])][:2] == (f"{w[55]}/Part 2", [])


def _as_before_alpha7(store, rels):
    """The store as alpha 6 left it: each season work titled by its path, no other title, its search key so."""
    with store._command("test_old_titles", "sync") as cmd:
        for below, rel in rels.items():
            wid = _work_of(store, rel)
            store.conn.execute("UPDATE works SET title = ?, titles = '[]' WHERE id = ?", (below, wid))
            store._rekey_work(wid)
            cmd.touch()


def _place(store):
    return (store.conn.execute("SELECT id, tier, ord, work_id, piece_id, pinned, watched FROM items ORDER BY id")
            .fetchall(), store.conn.execute("SELECT id, folder_key FROM works ORDER BY id").fetchall())


@pytest.mark.parametrize("language", LANGUAGES)
def test_path_titles_already_in_a_store_are_retitled_once_never_a_users_and_nothing_moves(language):
    """His store holds the path titles already, and a scan never renames a work: the helper's run retitles every work
    still named by its folder's path, once (a second run finds nothing), keeps the path among its other titles, leaves
    a title the user named (even one that is the path) and touches no item, order, piece or folder key — and no
    Generate is asked for (the order version stays)."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[56]
    with store:
        root = store.add_source(src)
        rels = _take_seasons(store, language, data_dir, root, src, show)
        _as_before_alpha7(store, rels)
        mine = _work_of(store, rels[f"{show}/第3期"])
        store.rename_work(mine, f"{show}/第3期")            # the user's own name, written as the path
        assert _works(store)[mine][2] == 1
        before, order = _place(store), store.token()[1]
        done = store.retitle_folder_works()
        works = _works(store)
        assert sorted(done) == sorted(_work_of(store, rels[b]) for b in (f"{show}/Season 1", f"{show}/S02",
                                                                          f"{show}/Specials"))
        assert works[_work_of(store, rels[f"{show}/S02"])][:2] == (f"{show} Season 2", [f"{show}/S02"])
        assert works[_work_of(store, rels[f"{show}/Specials"])][:2] == (f"{show} Specials", [f"{show}/Specials"])
        assert works[mine][0] == f"{show}/第3期", "the user's name stands"
        assert _place(store) == before and store.token()[1] == order
        assert store.search(f"{show} Season 2")[0] == [_work_of(store, rels[f"{show}/S02"])]
        assert _work_of(store, rels[f"{show}/S02"]) in store.search(f"{show}/S02")[0]
        assert store.retitle_folder_works() == [], "once: a second run finds nothing"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_that_is_not_its_own_folders_path_is_never_retitled(language):
    """Only a title still named by ITS folder's path is the old naming: a work titled by another folder's path (a
    merge kept the other's title, `<show>/Season 1` over the `<show>/S02` folder) or by a record is left as it is."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[58]
    with store:
        root = store.add_source(src)
        rels = _take_seasons(store, language, data_dir, root, src, show)
        second = _work_of(store, rels[f"{show}/S02"])
        with store._command("test_other_title", "sync") as cmd:
            store.conn.execute("UPDATE works SET title = ?, titles = '[]' WHERE id = ?", (f"{show}/Season 1", second))
            store._rekey_work(second)
            cmd.touch()
        assert store.retitle_folder_works() == []
        assert _works(store)[second][0] == f"{show}/Season 1"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_added_or_a_work_merged_between_the_read_and_the_write_is_kept(language, monkeypatch):
    """The helper reads the candidates, then writes in its own command while the window writes too: what changed in
    between stands — a show title a record added stays among the other titles (search and `_work_by_record` still find
    it), and a work no longer of that folder (a merge moved its key) keeps its title."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[59]
    with store:
        root = store.add_source(src)
        rels = _take_seasons(store, language, data_dir, root, src, show)
        _as_before_alpha7(store, rels)
        one, two = _work_of(store, rels[f"{show}/Season 1"]), _work_of(store, rels[f"{show}/S02"])
        real, moved = ls.folder_title, []

        def meanwhile(below):                            # the window's writes, after the helper's read
            if not moved:
                moved.append(1)
                with store._command("test_meanwhile", "sync") as cmd:
                    store.conn.execute("UPDATE works SET titles = ? WHERE id = ?", (json.dumps(["Sousou no Frieren"]), one))
                    store.conn.execute("UPDATE works SET folder_key = ? WHERE id = ?", (ls.path_key(f"{show}/other"), two))
                    store._rekey_work(one)
                    cmd.touch()
            return real(below)
        monkeypatch.setattr(ls, "folder_title", meanwhile)
        done = store.retitle_folder_works()
        works = _works(store)
        assert one in done and two not in done
        assert works[one][:2] == (f"{show} Season 1", ["Sousou no Frieren", f"{show}/Season 1"])
        assert store.search("Sousou no Frieren")[0] == [one]
        assert works[two][0] == f"{show}/S02", "merged elsewhere meanwhile: its title stands"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helpers_run_retitles_a_store_alpha6_left(language):
    """The retitle is the helper's (`maintain`, beside `tidy_works`), so his library gets it at the window's first
    helper run after the update, and the window reads the new titles from the feed."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[57]
    with store:
        root = store.add_source(src)
        rels = _take_seasons(store, language, data_dir, root, src, show)
        _as_before_alpha7(store, rels)
        ids = {b: _work_of(store, r) for b, r in rels.items()}
    user_files_dir = store.user_files_dir
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        works = _works(again)
        assert {b: works[w][0] for b, w in ids.items()} == {
            f"{show}/Season 1": f"{show} Season 1", f"{show}/S02": f"{show} Season 2",
            f"{show}/第3期": f"{show} Season 3", f"{show}/Specials": f"{show} Specials"}
        fed = {r[0] for r in again.conn.execute("SELECT id FROM works WHERE feed_in = "
                                                "(SELECT MAX(feed_in) FROM works)")}
        assert fed == set(ids.values()), "the window reads these works again"
    finally:
        again.close()


@pytest.mark.parametrize("show, folder, aniList", [
    ("Sousou no Frieren", "Season 2", "Sousou no Frieren 2nd Season"),
    ("Kusuriya no Hitorigoto", "S02", "Kusuriya no Hitorigoto 2nd Season"),
    ("葬送のフリーレン", "第2期", "葬送のフリーレン 第2期"),
    ("Dungeon Meshi", "Season 1", "Dungeon Meshi"),
])
def test_the_cover_search_asks_for_the_show_and_its_season_never_the_folder_alone(show, folder, aniList):
    """No cover: the AniList search kept a title's last path part, so it asked for `S02` (and every season folder sent
    a search for nothing). Named `<show> Season N`, the whole name is asked and the gate compares its season with
    AniList's (`2nd Season`, `第2期`; season 1 is a title with none said)."""
    title = ls.folder_title(f"{show}/{folder}")
    asked, _year = covers_online.clean_title(title)
    assert asked == title
    media = [{"id": 1, "title": {"romaji": aniList}}, {"id": 2, "title": {"romaji": f"{show} 3rd Season"}}]
    assert covers_online.gate(asked, media) == media[0]
