"""One show, one title (a8, alpha 7's try: the Finished tab showed "<show>" Ep 2–12 and "<show>!" Ep 2, 4–9 as two
titles). A source's folder `<show>!/` and a loose `<show> - 02.mkv` beside it were copied to two `Library/` folders
(`<show>!`, `<show>`), so the store saw two folder keys and made two titles. Sonic's answer (2026-10-31, "Yes to both
leans"): one "same show?" key that ignores punctuation (`episode_names.show_key`), and the pairs a store already holds
joined once, in the helper's run (`Store.join_same_shows`). Two shows apart only by punctuation count as one (accepted).

What a wrong answer would cost: one show as two rows for good; or the join taking apart what the user said, moving an
item, its order, its piece or its file (a Generate for nothing, a lost place), joining two shows the ids say differ,
or a season of one show swallowed by another. Every test runs for Japanese and Chinese, with real texts from
tests/Test Resources/ under the per-test SURASURA_TEST_ROOT.
"""
import json
import os

import pytest

from app import library_store as ls
from app.episode_names import show_key
from tests.test_library_store_sources import _empty, _found, _source_root  # noqa: F401
from tests.test_library_store_sources import _fresh_module_state  # noqa: F401  (each look a new run of the app)
from tests.test_library_store_support import LANGUAGES, names, pieces_ok, touch


def _work_of(store, rel):
    return store.item(store.item_id(rel))["work_id"]


def _works(store):
    return {w: (t, json.loads(ts), fk) for w, t, ts, fk in
            store.conn.execute("SELECT id, title, titles, folder_key FROM works")}


def _place(store):
    """Everything the join must leave as it was: each item's tier, order, piece, pin, watched mark and file."""
    return store.conn.execute("SELECT id, rel_path, tier, ord, piece_id, pinned, watched FROM items ORDER BY id"
                              ).fetchall()


_TEXTS = []


def _take(store, language, data_dir, root, src, folders):
    """Each `{folder below the source: [episode numbers]}` copied as the look did before a8 (`Library/<folder>/…`), one
    take-in -> {folder: [its files' rels]}."""
    found, out = [], {}
    for folder, eps in folders.items():
        for n in eps:
            text = len(_TEXTS) + 1                       # each file its own text (one text twice is one file)
            _TEXTS.append(folder)
            f = _found(language, data_dir, src, folder, f"{folder.split('/')[0].rstrip('!~')} - {n:02d}.srt", text)
            found.append(f)
            out.setdefault(folder, []).append(f["rel"])
    store.take_in(root, found, first=True)
    return out


def test_the_same_show_key_ignores_punctuation_and_keeps_letters_and_digits():
    """`Show!`, `Show`, `SHOW!!` are one show; `Re:Zero`, `Re Zero` and `Re：Zero` (full width) too; katakana reads as
    hiragana (as the search key); a number in the name stays (`Show 2` is not `Show`); nothing but marks is no key."""
    assert show_key("Tetsunabe no Jan!") == show_key("Tetsunabe no Jan") == show_key("TETSUNABE NO JAN!!")
    assert show_key("Re:Zero") == show_key("Re Zero") == show_key("Re：Zero") == "rezero"
    assert show_key("ホシゾラ！") == show_key("ほしぞら")
    assert show_key("星の図書館・下巻") == "星の図書館下巻"
    assert show_key("Show 2") != show_key("Show")
    assert show_key("86") == "86"
    assert show_key("!!") == show_key("") == show_key(None) == ""


def test_a_loose_files_show_is_the_source_folder_of_the_same_show_named_exactly_first():
    """Where a loose file at a source's top is copied (`sources._show_of`): the top folder of its show by the key —
    the folder named exactly when there is one, else the first by name; never a season folder (it is no show of its
    own); with no such folder, as before (its name's show, else the source's name — `86 - 01` names no show)."""
    from app.sources import _show_of
    root = os.path.join("D:", os.sep, "Anime")
    name = "[Grp] Tetsunabe no Jan - 02 (1080p).ja.srt"
    assert _show_of(root, [], name, ["Other", "Tetsunabe no Jan!"]) == "Tetsunabe no Jan!"
    assert _show_of(root, [], name, ["Tetsunabe no Jan~", "tetsunabe no jan", "Tetsunabe no Jan!"]) == \
        "tetsunabe no jan"
    assert _show_of(root, [], name, ["Tetsunabe no Jan~", "Tetsunabe no Jan!"]) == "Tetsunabe no Jan!"
    assert _show_of(root, [], name, ["Tetsunabe no Jan 2", "Other"]) == "Tetsunabe no Jan"
    assert _show_of(root, [], name) == "Tetsunabe no Jan"
    assert _show_of(root, [], "[Grp] S2 - 01.ja.srt", ["S2"]) == "S2", "a show named like a season: by its name"
    assert _show_of(root, [], "86 - 01.ja.srt", ["86"]) == "Anime"
    assert _show_of(root, ["Tetsunabe no Jan!"], name, ["Tetsunabe no Jan"]) == "Tetsunabe no Jan!", "a folder's own"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_pair_apart_only_by_punctuation_becomes_one_title_and_nothing_else_moves(language):
    """His store: `<show>!` (2, 4) and `<show>` (2, 3) are two titles. The helper's join makes them one — the longer
    name kept (`<show>!`), the other among its titles so a search for either finds it — and leaves every item's tier,
    order, piece, pin, watched mark and file as they were; the order version stays (no Generate asked for). Once
    joined, a later run finds nothing."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[61]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (2, 4), show: (2, 3)})
        bang, plain = _work_of(store, rels[f"{show}!"][0]), _work_of(store, rels[show][0])
        assert bang != plain, "two titles before the join (the split)"
        store.set_watched([store.item_id(rels[show][0])], True)
        before, order = _place(store), store.token()[1]
        gone = store.join_same_shows()
        works = _works(store)
        assert gone == [plain]
        assert {_work_of(store, r) for rs in rels.values() for r in rs} == {bang}
        assert works[bang][0] == f"{show}!" and show in works[bang][1]
        assert plain not in works
        assert _place(store) == before and store.token()[1] == order
        assert all(os.path.exists(os.path.join(data_dir, *r.split("/"))) for rs in rels.values() for r in rs)
        assert store.search(show)[0] == [bang] and store.search(f"{show}!")[0] == [bang]
        assert store.join_same_shows() == [], "joined once: a second run finds nothing"
        # a later episode in either folder goes to the one title (its folder key, else the files beside it)
        later = [_found(language, data_dir, src, f"{show}!", f"{show} - 05.srt", 5),
                 _found(language, data_dir, src, show, f"{show} - 06.srt", 6)]
        store.take_in(root, later)
        assert {_work_of(store, f["rel"]) for f in later} == {bang}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_longer_name_is_kept_and_a_tie_keeps_the_older_title(language):
    """`<show>` made first and `<show>!` after: the longer name (`<show>!`) is kept whichever came first; two names of
    one length (`<show>~` and `<show>!`) keep the older title."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b = names(language)[62], names(language)[63]
    with store:
        root = store.add_source(src)
        first = _take(store, language, data_dir, root, src, {a: (1,), f"{b}~": (1,)})
        second = _take(store, language, data_dir, root, src, {f"{a}!": (2,), f"{b}!": (2,)})
        a_old, a_new = _work_of(store, first[a][0]), _work_of(store, second[f"{a}!"][0])
        b_old, b_new = _work_of(store, first[f"{b}~"][0]), _work_of(store, second[f"{b}!"][0])
        assert sorted(store.join_same_shows()) == sorted([a_old, b_new])
        works = _works(store)
        assert works[a_new][0] == f"{a}!" and a in works[a_new][1]
        assert works[b_old][0] == f"{b}~" and f"{b}!" in works[b_old][1]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_users_own_name_on_the_title_that_goes_is_the_name_kept(language):
    """Nobody asked for this join (`users_first`): a name the user gave the shorter title wins over the kept title's
    folder name, which stays findable among the titles."""
    store, data_dir = _empty(language)
    src = _source_root()
    show, mine = names(language)[64], names(language)[65]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2,)})
        bang, plain = _work_of(store, rels[f"{show}!"][0]), _work_of(store, rels[show][0])
        store.rename_work(plain, mine)
        assert store.join_same_shows() == [plain]
        title, titles, _fk = _works(store)[bang]
        assert title == mine and f"{show}!" in titles and store.search(f"{show}!")[0] == [bang]


@pytest.mark.parametrize("language", LANGUAGES)
def test_titles_the_ids_say_differ_or_the_user_kept_apart_are_never_joined(language):
    """Two AniList ids are two shows (`TITLES_APART`), and *Keep apart* is the user's answer: neither pair is joined,
    and the helper's run touches nothing for them."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b = names(language)[66], names(language)[67]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {a: (1,), f"{a}!": (2,), b: (1,), f"{b}!": (2,)})
        ids = {k: _work_of(store, r[0]) for k, r in rels.items()}
        with store._command("test_ids", "sync") as cmd:
            store.conn.execute("UPDATE works SET anilist_id = 101 WHERE id = ?", (ids[a],))
            store.conn.execute("UPDATE works SET anilist_id = 202 WHERE id = ?", (ids[f"{a}!"],))
            cmd.touch()
        assert store.keep_apart([ids[b], ids[f"{b}!"]])
        before = _works(store)
        assert store.join_same_shows() == []
        assert _works(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_a_show_folders_own_titles_are_joined_never_a_season_or_another_number(language):
    """The split was two show folders at `Library/`'s top: a season folder below one (`<show>!/Season 1` beside
    `<show>/Season 1`) is left to the season rule, and `<show> 2` is another show (its digit stays in the key)."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[68]
    with store:
        root = store.add_source(src)
        _take(store, language, data_dir, root, src, {f"{show}!/Season 1": (1,), f"{show}/Season 1": (2,),
                                                     f"{show} 2": (3,), show: (4,)})
        before = _works(store)
        assert store.join_same_shows() == []
        assert _works(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_titles_taken_apart_after_the_join_stay_apart(language):
    """*Not part of this title* after the join is the user's way back: the title it makes has no folder key, so no
    later run joins it again."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[69]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2, 3)})
        assert len(store.join_same_shows()) == 1
        store.split_work([store.item_id(r) for r in rels[show]], show)
        apart = _works(store)
        assert len({_work_of(store, r) for rs in rels.values() for r in rs}) == 2
        assert store.join_same_shows() == [] and _works(store) == apart


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helpers_run_joins_a_store_alpha7_left_and_the_window_reads_the_works(language):
    """The join is the helper's (`maintain`, beside the season retitle), so his library gets it at the first helper
    run after the update; the window reads the kept title again from the feed, and the merged-away one goes."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[70]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (2, 4, 5), show: (2, 3)})
        bang, plain = _work_of(store, rels[f"{show}!"][0]), _work_of(store, rels[show][0])
        fed_before = dict(store.conn.execute("SELECT id, feed_in FROM works"))
        before = _place(store)
    user_files_dir = store.user_files_dir
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert {_work_of(again, r) for rs in rels.values() for r in rs} == {bang}
        assert _place(again) == before
        fed = {w for w, f in again.conn.execute("SELECT id, feed_in FROM works") if f > fed_before[w]}
        assert fed == {bang}
        assert ("work", plain) in [(k, i) for k, i in again.conn.execute("SELECT kind, id FROM gone")]
        assert again.join_same_shows() == [], "nothing left to join"
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_same_title_asks_about_two_titles_apart_only_by_punctuation(language):
    """*Same title?* groups by the same key: two titles with no folder (`<show>` and `<show>!`, the user's own) are
    asked about, as two of one spelling always were."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[71]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {show: (1, 2)})
        store.split_work([store.item_id(rels[show][1])], f"{show}!")
        ids = sorted({_work_of(store, r) for r in rels[show]})
        assert len(ids) == 2 and ids in store.same_titles()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_loose_episode_dropped_later_joins_the_show_apart_only_by_punctuation(language):
    """A loose file straight in a tier folder (or hato's) reads its show from its name: `<show> - 07` joins the title
    `<show>!` (no title spelled `<show>` yet) rather than becoming a title of its own."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[72]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (1,)})
        bang = _work_of(store, rels[f"{show}!"][0])
        touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show} - 07 (1080p) [ABCD1234].srt")
        drop = store.sync_disk()["added"][0]
        assert _work_of(store, store.item(drop)["rel_path"]) == bang
        assert pieces_ok(store) is None
