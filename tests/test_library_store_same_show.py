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


def _take(store, language, data_dir, root, src, folders, before_a8=True):
    """Each `{folder below the source: [episode numbers]}` copied as the look did before a8 (`Library/<folder>/…`), one
    take-in -> {folder: [its files' rels]}. `before_a8`: the store as alpha 7 left it — its first helper run (the
    test's empty library's) made no one-time join yet, so the mark is taken off."""
    found, out = [], {}
    for folder, eps in folders.items():
        for n in eps:
            text = len(_TEXTS) + 1                       # each file its own text (one text twice is one file)
            _TEXTS.append(folder)
            f = _found(language, data_dir, src, folder, f"{folder.split('/')[0].rstrip('!~')} - {n:02d}.srt", text)
            found.append(f)
            out.setdefault(folder, []).append(f["rel"])
    store.take_in(root, found, first=True)
    if before_a8:
        with store._writing():
            store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.SHOWS_JOINED,))
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


def test_a_loose_episodes_show_is_the_one_source_folder_of_the_same_show():
    """Where a loose file at a source's top is copied (`sources._show_of`, its folders from `_show_folders`): a loose
    EPISODE of the one top folder of its show by the key goes there; two of that key (`Show!/`, `Show~/`): its own
    show, as before (one of them named exactly as it is that show's folder already); never a season folder (no show
    of its own); never a book (no episode number: a book's show is its name); with no such folder, as before (its name's
    show, else the source's name — `86 - 01` names no show); a file inside a folder is that folder's."""
    from app.sources import _show_folders, _show_of
    root = os.path.join("D:", os.sep, "Anime")
    name = "[Grp] Tetsunabe no Jan - 02 (1080p).ja.srt"
    top = lambda *names: _show_folders([os.path.join(root, n) for n in names])     # noqa: E731
    assert _show_of(root, [], name, top("Other", "Tetsunabe no Jan!")) == "Tetsunabe no Jan!"
    assert _show_of(root, [], name, top("Tetsunabe no Jan~", "Tetsunabe no Jan", "Tetsunabe no Jan!")) == \
        "Tetsunabe no Jan"
    assert _show_of(root, [], name, top("Tetsunabe no Jan~", "Tetsunabe no Jan!")) == "Tetsunabe no Jan"
    assert _show_of(root, [], name, top("Tetsunabe no Jan 2", "Other")) == "Tetsunabe no Jan"
    assert _show_of(root, [], name) == "Tetsunabe no Jan"
    assert _show_of(root, [], "Toradora.epub", top("Toradora!")) == "Toradora", "a book: its own name"
    assert _show_of(root, [], "[Grp] Toradora - 03.mkv", top("Toradora!")) == "Toradora!"
    assert top("S2", "Season 3", "Specials", "!!", "Toradora!") == [("Toradora!", "toradora")]
    assert _show_of(root, [], "86 - 01.ja.srt", top("86")) == "Anime"
    assert _show_of(root, ["Tetsunabe no Jan!"], name, top("Tetsunabe no Jan")) == "Tetsunabe no Jan!", "its folder's"


def test_a_removed_loose_episodes_rerelease_copied_for_the_folder_stays_out():
    """A loose `Show - 03` removed before a8 is remembered under its show `Show`; its re-release, now copied for the
    folder `Show!/`, has the show `Show!`: one key, so it stays out (`_Look._removed`); another show never matches."""
    from types import SimpleNamespace

    from app.sources import _Look
    for language in LANGUAGES:
        look = SimpleNamespace(language=language)
        old = _Look._removed(look, "Tetsunabe no Jan", 3, "[Grp] Tetsunabe no Jan - 03 (1080p).ja.srt")
        new = _Look._removed(look, "Tetsunabe no Jan!", 3, "[Grp] Tetsunabe no Jan - 03v2 (1080p).ja.srt")
        assert old == new
        assert _Look._removed(look, "Tetsunabe no Jan 2", 3, "[Grp] Tetsunabe no Jan 2 - 03.ja.srt") != old
        assert _Look._removed(look, "♪♪", 3, "♪♪ - 03.srt") != _Look._removed(look, "★", 3, "★ - 03.srt")


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


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_join_runs_once_a_store_and_a_pair_made_later_is_asked_about(language):
    """"The existing pairs joined once": the first helper run joins them and marks the store; a pair made after it
    (another source's loose episode, a drop) is never joined without a word — *Same title?* asks about it (one key)."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b = names(language)[73], names(language)[74]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{a}!": (1,), a: (2,)})
        assert len(store.join_same_shows()) == 1
        assert store.meta()[ls.SHOWS_JOINED] == 1
        later = _take(store, language, data_dir, root, src, {f"{b}!": (1,), b: (2,)}, before_a8=False)
        ids = sorted({_work_of(store, r[0]) for r in later.values()})
        assert store.join_same_shows() == [] and len(ids) == 2
        assert ids in store.same_titles()
        assert len({_work_of(store, r) for rs in rels.values() for r in rs}) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_titles_the_user_grouped_together_or_of_two_types_stay_two(language):
    """A group of the two made by the user is his answer (they stay two titles in it; joined, the group would turn
    into a run across the Soon line), and a book beside a show (`Toradora/` an EPUB's, `Toradora!/` the anime's) is
    two titles of two types: neither pair is joined."""
    store, data_dir = _empty(language)
    src = _source_root()
    a, b = names(language)[75], names(language)[76]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{a}!": (1,), a: (2,), f"{b}!": (1,), b: (2,)})
        ids = {k: _work_of(store, r[0]) for k, r in rels.items()}
        pieces = [store.item(store.item_id(rels[k][0]))["piece_id"] for k in (f"{a}!", a)]
        assert store.join(pieces, how="group") is not None
        store.set_media_type([ids[b]], "book")
        store.set_media_type([ids[f"{b}!"]], "anime")
        before = _works(store)
        assert store.join_same_shows() == []
        assert _works(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_keep_apart_answer_about_the_title_that_goes_is_kept_for_the_title_kept(language):
    """The user kept `<show>` apart from another title outside the join (no folder): after `<show>` is joined into
    `<show>!`, that answer is about `<show>!`, so *Same title?* never asks about it again."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[77]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2, 3)})
        bang, plain = _work_of(store, rels[f"{show}!"][0]), _work_of(store, rels[show][0])
        store.split_work([store.item_id(rels[show][1])], f"{show}~")
        other = _work_of(store, rels[show][1])
        assert store.keep_apart([plain, other])
        assert store.join_same_shows() == [plain]
        assert json.loads(store.meta()["kept_apart"]) == [sorted([bang, other])]
        assert not any(other in g for g in store.same_titles())


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_users_own_subtitle_group_on_the_title_that_goes_wins(language):
    """Nobody asked for the join (G4): a subtitle group the learner switched on the shorter title wins over one
    Connect chose for the kept title."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[78]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2,)})
        bang, plain = _work_of(store, rels[f"{show}!"][0]), _work_of(store, rels[show][0])
        with store._writing():
            store._set_meta({ls.SHOW_GROUPS: json.dumps({
                str(bang): {"group": ["Grp", "Connect's"], "by": "connect"},
                str(plain): {"group": ["Mine", "the learner's"], "by": "user"}})})
        assert store.join_same_shows() == [plain]
        assert store.group_of(bang)["group"] == ["Mine", "the learner's"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_join_that_fails_leaves_the_store_as_it_was_and_the_helpers_run_goes_on(language, monkeypatch):
    """An unforeseen error inside the join rolls its command back (both titles, no mark) and the helper's run still
    ends well; the next run tries again."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[79]
    with store:
        root = store.add_source(src)
        _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2,)})
        before = _works(store)
    user_files_dir = store.user_files_dir
    store.close()

    def broken(self, *a, **k):
        raise RuntimeError("a planted failure")
    with monkeypatch.context() as patched:
        patched.setattr(ls.Store, "_carry_apart", broken)
        assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert _works(again) == before and not again.meta().get(ls.SHOWS_JOINED)
    finally:
        again.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert len(_works(again)) == len(before) - 1
    finally:
        again.close()


# --- the exceptions (Sonic 2026-10-31: "file the excepts as we go like gintama") ------------------------------- #

def test_every_exception_names_why_and_is_a_show_of_its_own():
    """Each entry of `SHOW_KEY_EXCEPTIONS` says why, keys apart from the title its punctuation leaves and from every
    other entry, and is found whatever its case or width (`ＧＩＮＴＡＭＡ'` is `Gintama'`); the title it leaves is
    the punctuation rule's as before."""
    from app.episode_names import SHOW_KEY_EXCEPTIONS
    keys = [show_key(title) for title, _why in SHOW_KEY_EXCEPTIONS]
    assert all(why.strip() for _t, why in SHOW_KEY_EXCEPTIONS)
    assert len(set(keys)) == len(keys)
    for title, _why in SHOW_KEY_EXCEPTIONS:
        bare = "".join(c for c in title if c.isalnum())
        assert show_key(title) != show_key(bare), title
    assert show_key("ＧＩＮＴＡＭＡ'") == show_key("Gintama'") != show_key("Gintama")
    assert show_key("Gintama!") == show_key("Gintama"), "a mark no entry names: the rule as before"


def test_a_loose_episode_beside_seasons_named_by_punctuation_goes_to_its_own_season():
    """`Gintama/`, `Gintama'/` and `Gintama°/` at a source's top: a loose `Gintama' - 04` is copied for `Gintama'`, a
    loose `Gintama - 05` for `Gintama` — never one season's episode in another's folder."""
    from app.sources import _show_folders, _show_of
    root = os.path.join("D:", os.sep, "Anime")
    top = _show_folders([os.path.join(root, n) for n in ("Gintama", "Gintama'", "Gintama°")])
    assert _show_of(root, [], "[Grp] Gintama' - 04 (1080p).ja.srt", top) == "Gintama'"
    assert _show_of(root, [], "[Grp] Gintama° - 02 (1080p).ja.srt", top) == "Gintama°"
    assert _show_of(root, [], "[Grp] Gintama - 05 (1080p).ja.srt", top) == "Gintama"
    assert _show_of(root, [], "[Grp] Gintama - 05 (1080p).ja.srt", top[1:]) == "Gintama", "no season 1 folder: its own"


@pytest.mark.parametrize("language", LANGUAGES)
def test_seasons_named_by_punctuation_are_never_joined_nor_asked_about(language):
    """A store holding `Gintama`, `Gintama'`, `Gintama°` and `銀魂'` beside a real pair (`<show>!` / `<show>`): the
    one-time join joins only the pair, and *Same title?* never asks about the seasons."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[80]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {"Gintama": (1,), "Gintama'": (2,), "Gintama°": (3,),
                                                            "銀魂'": (4,), "銀魂": (5,), f"{show}!": (1,), show: (2,)})
        seasons = {k: _work_of(store, r[0]) for k, r in rels.items() if k not in (show, f"{show}!")}
        plain = _work_of(store, rels[show][0])
        assert store.join_same_shows() == [plain]
        assert {k: _work_of(store, r[0]) for k, r in rels.items() if k in seasons} == seasons
        assert len(set(seasons.values())) == 5
        assert not any(set(g) & set(seasons.values()) for g in store.same_titles())


# --- the mutant pass's gaps ------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_join_reads_its_once_mark_again_inside_its_command(language, monkeypatch):
    """Another process (a second helper, the window's import) may mark the store between the join's first read and
    its write lock: the mark read inside the command decides, so the join never runs twice."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[81]
    with store:
        root = store.add_source(src)
        _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2,)})
        with store._writing():
            store._set_meta({ls.SHOWS_JOINED: 1})
        real, calls = ls.Store._meta, []

        def first_read_stale(self):                      # the first read comes before the other process's mark
            calls.append(1)
            meta = real(self)
            return {k: v for k, v in meta.items() if k != ls.SHOWS_JOINED} if len(calls) == 1 else meta
        monkeypatch.setattr(ls.Store, "_meta", first_read_stale)
        before = _works(store)
        assert store.join_same_shows() == [] and _works(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_loose_drops_of_one_show_in_one_sync_are_one_title(language):
    """Two loose drops in one disk sync, `<show>!! - 01` (a new title) and `<show> - 02`: the second finds the title
    the first made in the same command (one key), never a second title."""
    store, data_dir = _empty(language)
    show = names(language)[82]
    with store:
        touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show}!! - 01 (1080p) [ABCD1234].srt")
        touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show} - 02 (1080p) [1A2B3C4D].srt")
        added = store.sync_disk()["added"]
        assert len(added) == 2
        assert len({store.item(i)["work_id"] for i in added}) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_same_title_still_asks_about_two_titles_of_marks_alone(language):
    """Titles with no letter or digit (`♪♪`) have no show key: *Same title?* keys them as folded, so two of them are
    asked about as before a8."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[83]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {show: (1, 2, 3)})
        store.split_work([store.item_id(rels[show][1])], "♪♪")
        store.split_work([store.item_id(rels[show][2])], "♪♪")
        two = sorted({_work_of(store, r) for r in rels[show][1:]})
        assert len(two) == 2 and two in store.same_titles()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_kept_titles_own_subtitle_group_stands_when_both_are_the_learners(language):
    """Both titles' subtitle groups switched by the learner: the kept title's own stays (only a group that isn't the
    learner's gives way to the learner's)."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[84]
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{show}!": (1,), show: (2,)})
        bang, plain = _work_of(store, rels[f"{show}!"][0]), _work_of(store, rels[show][0])
        with store._writing():
            store._set_meta({ls.SHOW_GROUPS: json.dumps({
                str(bang): {"group": ["Kept", "the kept title's"], "by": "user"},
                str(plain): {"group": ["Gone", "the other's"], "by": "user"}})})
        assert store.join_same_shows() == [plain]
        assert store.group_of(bang)["group"] == ["Kept", "the kept title's"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_long_list_of_pairs_is_joined_in_short_commands_and_marked_by_the_last(language, monkeypatch):
    """The join gives the write lock back between batches (`JOIN_BATCH` pairs a command, here one): every pair is
    joined, a pair left apart is asked about once only, and only the command that ends the list sets the mark."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        rels = _take(store, language, data_dir, root, src, {f"{w[85]}!": (1,), w[85]: (2,), f"{w[86]}!": (1,),
                                                            w[86]: (2,), f"{w[87]}!": (1,), w[87]: (2,)})
        apart = [_work_of(store, rels[k][0]) for k in (f"{w[86]}!", w[86])]
        assert store.keep_apart(apart)
        commands, real = [], ls.Store._command

        def counted(self, kind, by="user"):
            if kind == "join_same_shows":
                commands.append(self._meta().get(ls.SHOWS_JOINED))
            return real(self, kind, by)
        monkeypatch.setattr(ls, "JOIN_BATCH", 1)
        monkeypatch.setattr(ls.Store, "_command", counted)
        assert len(store.join_same_shows()) == 2
        assert commands == [None, None, None] and store.meta()[ls.SHOWS_JOINED] == 1
        assert len({_work_of(store, r[0]) for r in rels.values()}) == 4
