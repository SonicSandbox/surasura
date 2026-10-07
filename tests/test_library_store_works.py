"""Works, pieces and search (L3.1 row 3.1.4; the L2.2 pack 05 §5.2–5.3, 06 §6.5, 06 §6.8).

Why these matter: 3.0's window draws one row per title with its cover, and each block of episodes placed together as
one piece. A work is found the same way every time — a record's ids, then its show's title, then the folder below the
tier folder — so a new episode lands in its title and a show split across tier folders stays one title; one AniList or
TMDB id is never two titles (G2.2-6); a match by title alone is asked, never joined. A piece stays one contiguous run of
one title in one tier through every command — a foreign drop splits it, an episode put back beside its own rejoins it,
an undo puts rows back in their pieces. Search folds the title and the query alike: katakana as hiragana, NFKC, case,
and Chinese Traditional as Simplified. Every test runs for Japanese and Chinese, under the per-test SURASURA_TEST_ROOT,
with real words from tests/Test Resources/; the 200k search holds its budget in the timed run (SURASURA_STORE_BENCH=1).
"""

import json
import os
import random
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, arrivals_off, big_store, migrated, names, pieces_ok, roots,
                                              touch)

BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"


def _work(store, item_id):
    return store.item(item_id)["work_id"]


def _record(key, **more):
    record = {"schema": 1, "content_key": key, "producer": "hato", "verdict": "timed"}
    record.update(more)
    return record


# --- search_fold --------------------------------------------------------------------------------- #

def test_search_fold_katakana_hiragana_nfkc_case():
    """05 §5.3: one fold for keys and queries — NFKC (half-width and full-width forms), case-folded, katakana as
    hiragana, whitespace runs as one space."""
    fold = ls.search_fold
    assert fold("フリーレン", "ja") == fold("ふりーれん", "ja") == "ふりーれん"
    assert fold("ﾌﾘｰﾚﾝ", "ja") == "ふりーれん", "half-width katakana"
    assert fold("ＦＲＩＥＲＥＮ", "ja") == fold("Frieren", "ja") == "frieren"
    assert fold("  葬送の   フリーレン\t第2期 ", "ja") == "葬送の ふりーれん 第2期"
    assert fold("", "ja") == "" and fold(None, "ja") == ""


def test_search_fold_zh_traditional_simplified():
    """06 §6.8: a Chinese title and query are read as Simplified (app/zh_script's tables, no new data), so a
    Traditional query finds a Simplified title and back; a Japanese fold never converts."""
    fold = ls.search_fold
    assert fold("學習中文", "zh") == fold("学习中文", "zh") == "学习中文"
    assert fold("臺灣新聞", "zh") == fold("台湾新闻", "zh")
    assert fold("學習", "ja") == "學習"


# --- works: the find order ------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_add_and_sync_find_the_work_by_folder(language):
    """05 §5.3 (3)–(4): a new episode — by Add or by the disk sync — joins the title of its folder, wherever that title's
    other episodes sit (another tier folder too); a new folder is a new title, a loose file a title of its own."""
    store = migrated(language, shows=2, episodes=3)
    data_dir, _u = roots(language)
    w = names(language)
    show = next(i for i in store.ids("goal") if store.item(i)["parent_folder"])
    folder = store.item(show)["rel_path"].split("/", 1)[1].rsplit("/", 1)[0]       # the folder below GoalContent
    added = store.insert([touch(data_dir, f"HighPriority/{folder}/{w[70]}_第09話.srt")], "now").added[0]
    assert _work(store, added) == _work(store, show), "the same folder below another tier folder: one title"
    touch(data_dir, f"GoalContent/{folder}/{w[71]}_第10話.srt")
    synced = store.sync_disk()["added"][0]
    assert _work(store, synced) == _work(store, show)
    fresh = store.insert([touch(data_dir, f"LowPriority/{w[72]}/{w[73]}.srt")], "soon").added[0]
    loose = store.insert([touch(data_dir, f"LowPriority/{w[74]}.srt")], "soon").added[0]
    assert len({_work(store, i) for i in (show, fresh, loose)}) == 3
    titles = dict(store.conn.execute("SELECT id, title FROM works"))
    assert titles[_work(store, fresh)] == w[72] and titles[_work(store, loose)] == f"{w[74]}.srt"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_register_finds_the_work_by_record_then_show_then_folder(language):
    """05 §5.3 (1)–(4), `register` only for (1)–(2): a drop whose record names an AniList id joins the title holding it
    (wherever its file sits); one naming only a show joins the title by that name (folded); else its folder decides; a
    loose drop with a show starts a title named by it. The record's ids and show title fill the work."""
    store = migrated(language, shows=2, episodes=3)
    data_dir, _u = roots(language)
    w = names(language)
    show = next(i for i in store.ids("now") if store.item(i)["parent_folder"])
    work = _work(store, show)
    store.register(os.path.join(data_dir, store.item(show)["rel_path"]),
                   _record("k0", anilist_id=154587, show={"title": "Sousou no Frieren", "episode": 1}))
    row = store.conn.execute("SELECT anilist_id, titles FROM works WHERE id = ?", (work,)).fetchone()
    assert row[0] == 154587 and "Sousou no Frieren" in json.loads(row[1]), "the record fills its work"
    by_id = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[75]}.srt"), _record("k1", anilist_id=154587))
    assert _work(store, by_id.added[0]) == work, "(1) the id"
    by_show = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[76]}.srt"),
                             _record("k2", show={"title": "SOUSOU NO FRIEREN", "episode": 2}))
    assert _work(store, by_show.added[0]) == work, "(2) the show's title, folded"
    folder = store.item(show)["rel_path"].rsplit("/", 1)[0]
    by_folder = store.register(touch(data_dir, f"{folder}/{w[77]}.srt"), _record("k3"))
    assert _work(store, by_folder.added[0]) == work, "(3) the folder"
    new = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[78]}.srt"),
                         _record("k4", show={"title": w[79], "episode": 1}))
    assert dict(store.conn.execute("SELECT id, title FROM works"))[_work(store, new.added[0])] == w[79], \
        "(4) a loose drop: a title named by its show"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_record_never_renames_a_users_work(language):
    """03 §3.3 #2: a title the user renamed (`title_by_user`) is never renamed by a record — its ids and other titles
    are added, its name stays; nor is a user's media type overwritten by hato's (06 §6.6)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    show = next(i for i in store.ids("now") if store.item(i)["parent_folder"])
    work = _work(store, show)
    store.rename_work(work, w[80])
    with store._writing():
        store.conn.execute("UPDATE works SET media_type = 'drama', media_type_by = 'user' WHERE id = ?", (work,))
    store.register(os.path.join(data_dir, store.item(show)["rel_path"]),
                   _record("k5", tmdb_id="tv:209867", media_type="anime", show={"title": "Some Show", "episode": 3}))
    row = store.conn.execute("SELECT title, title_by_user, titles, tmdb_id, media_type, media_type_by FROM works "
                             "WHERE id = ?", (work,)).fetchone()
    assert row[0] == w[80] and row[1] == 1 and "Some Show" in json.loads(row[2]) and row[3] == "tv:209867"
    assert (row[4], row[5]) == ("drama", "user")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_second_title_with_the_same_id_merges_into_the_first(language):
    """G2.2-6 ("one title, never two"): a record that would give a second work an AniList id another work holds makes
    them one title — the lower id kept — and an undo of the merge-by-hand puts both back."""
    store = migrated(language, shows=2, episodes=2)
    data_dir, _u = roots(language)
    shows = [i for i in store.ids("soon") if store.item(i)["parent_folder"]]
    a, b = shows[0], next(i for i in shows if _work(store, i) != _work(store, shows[0]))
    wa, wb = _work(store, a), _work(store, b)
    store.register(os.path.join(data_dir, store.item(a)["rel_path"]), _record("ka", anilist_id=21))
    store.register(os.path.join(data_dir, store.item(b)["rel_path"]), _record("kb", anilist_id=21))
    keep = min(wa, wb)
    assert _work(store, a) == _work(store, b) == keep
    assert store.conn.execute("SELECT COUNT(*) FROM works WHERE anilist_id = 21").fetchone()[0] == 1
    assert not store.conn.execute("SELECT 1 FROM works WHERE id = ?", (max(wa, wb),)).fetchone()
    assert ("work", max(wa, wb)) in [tuple(r) for r in store.conn.execute("SELECT kind, id FROM gone")]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_only_match_is_asked_never_joined(language):
    """05 §5.3: two titles that share only a name (no id says they're one) are never joined by Add or the sync: they
    are listed as *Same title?* until the user answers — *Join* (`merge_works`) or *Keep apart* (`keep_apart`)."""
    store = migrated(language, shows=1, episodes=2)
    data_dir, _u = roots(language)
    w = names(language)
    one = store.insert([touch(data_dir, f"HighPriority/{w[81]}/{w[82]}.srt")], "now").added[0]
    two = store.insert([touch(data_dir, f"GoalContent/Extra/{w[81]}/{w[83]}.srt")], "goal").added[0]
    store.rename_work(_work(store, two), w[81])
    assert _work(store, one) != _work(store, two), "never joined by a name alone"
    assert sorted([_work(store, one), _work(store, two)]) in store.same_titles()
    assert store.keep_apart([_work(store, one), _work(store, two)])
    assert store.same_titles() == []
    store.close()


# --- works: the user's corrections ----------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_rename_merge_and_split_works_and_undo_each(language):
    """04 §4.2: `rename_work` keeps the old name among the other titles (search still finds it); `merge_works` moves the
    others' items and ids to the kept title; `split_work` makes a new title of some items and splits their pieces where
    the title changes. Each undoes by the value check."""
    store = migrated(language, shows=2, episodes=4)
    w = names(language)
    shows = [i for i in store.ids("goal") if store.item(i)["parent_folder"]]
    a = shows[0]
    wa = _work(store, a)
    b = next(i for i in shows if _work(store, i) != wa)
    wb = _work(store, b)
    old = dict(store.conn.execute("SELECT id, title FROM works"))[wa]
    renamed = store.rename_work(wa, w[84])
    assert store.search(old)[0] == [wa] and store.search(w[84])[0] == [wa]
    store.undo(renamed)
    assert dict(store.conn.execute("SELECT id, title FROM works"))[wa] == old
    members_b = [i for i in store.ids("goal") if _work(store, i) == wb]
    merged = store.merge_works(wa, [wb])
    assert all(_work(store, i) == wa for i in members_b) and pieces_ok(store) is None
    store.undo(merged)
    assert all(_work(store, i) == wb for i in members_b)
    assert store.conn.execute("SELECT title FROM works WHERE id = ?", (wb,)).fetchone()
    members_a = [i for i in store.ids("goal") if _work(store, i) == wa]
    split = store.split_work(members_a[1:3], w[85])
    new = _work(store, members_a[1])
    assert new not in (wa, wb) and _work(store, members_a[2]) == new and _work(store, members_a[0]) == wa
    assert pieces_ok(store) is None, "the pieces split where the title changes"
    store.undo(split)
    assert all(_work(store, i) == wa for i in members_a)
    assert not store.conn.execute("SELECT 1 FROM works WHERE id = ?", (new,)).fetchone()
    assert pieces_ok(store) is None
    store.close()


# --- pieces ------------------------------------------------------------------------------------------ #

def _piece(store, item_id):
    return store.item(item_id)["piece_id"]


def _members(store, piece):
    return [r[0] for r in store.conn.execute("SELECT id FROM items WHERE piece_id = ? ORDER BY ord, id", (piece,))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_pieces_follow_their_rules(language):
    """05 §5.2: a whole piece moved keeps its id (4); a foreign item dropped inside a piece splits it there (5);
    items moved out start a piece of their own (4) and, put back beside their own, rejoin it; a new episode landing
    beside its show joins its piece (3); an emptied piece row is deleted (7)."""
    store = migrated(language, shows=3, episodes=4)
    data_dir, _u = roots(language)
    goal = store.ids("goal")
    shows = []
    for i in goal:
        p = _piece(store, i)
        if store.item(i)["parent_folder"] and p not in shows:
            shows.append(p)
    p1, p2 = shows[0], shows[1]
    m1, m2 = _members(store, p1), _members(store, p2)
    assert store.move(m1, "goal", after_id=store.ids("goal")[-1]) is not None   # the whole piece to the end
    assert _members(store, p1) == m1, "a whole piece moved keeps its id"
    store.move(m1, "goal")                                      # and back to the top
    loose = next(i for i in goal if not store.item(i)["parent_folder"])
    store.move([loose], "goal", after_id=m2[1])                 # a foreign drop inside p2: split there
    assert _members(store, p2) == m2[:2] and _piece(store, m2[2]) == _piece(store, m2[3]) != p2
    store.move([loose], "goal")                                 # moved away again: the split stays split
    tail = _piece(store, m2[2])
    assert _members(store, tail) == m2[2:]
    store.move([m1[3]], "goal", after_id=store.ids("goal")[-1])  # an episode moved out: a piece of its own
    alone = _piece(store, m1[3])
    assert alone != p1 and _members(store, alone) == [m1[3]]
    store.move([m1[3]], "goal", after_id=m1[2])                 # put back beside its own: rejoins
    assert _piece(store, m1[3]) == p1 and not store.conn.execute("SELECT 1 FROM pieces WHERE id = ?", (alone,)).fetchone()
    soon_show = next(i for i in store.ids("soon") if store.item(i)["parent_folder"])
    folder = store.item(soon_show)["rel_path"].rsplit("/", 1)[0]
    last = [i for i in store.ids("soon") if store.item(i)["rel_path"].rsplit("/", 1)[0] == folder][-1]
    new = store.insert([touch(data_dir, f"{folder}/{names(language)[86]}_第05話.srt")], "soon").added[0]
    assert store.ids("soon")[store.ids("soon").index(last) + 1] == new
    assert _piece(store, new) == _piece(store, last), "a new episode after its show's last row joins its piece"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_join_across_tiers_moves_then_joins_in_one_undo(language):
    """05 §5.2 #6 (W1.2 §8.2: "a join across sections lands where the target part is"): joining a title's piece in
    6+ Months onto its piece in Soon moves its items to just after the target's last, makes one piece, and one undo
    puts both pieces and every row back; a join of two titles' pieces is refused."""
    store = migrated(language, shows=2, episodes=4)
    goal_show = [i for i in store.ids("goal") if store.item(i)["parent_folder"]]
    target = _piece(store, goal_show[0])
    members = _members(store, target)
    store.set_soon_line(len(store.ids("now")))                  # keep the tiers where the test puts them
    store.move(members[2:], "soon")
    away = _piece(store, members[2])
    assert away != target and store.item(members[2])["tier"] == "soon"
    order = {t: store.ids(t) for t in ls.TIERS}
    pieces = {i: _piece(store, i) for i in members}
    change = store.join([away, target])                         # onto the Soon part: the 6+ Months part moves
    assert all(store.item(i)["tier"] == "soon" for i in members)
    assert _members(store, away) == members[2:] + members[:2]
    assert pieces_ok(store) is None
    store.undo(change)
    assert {t: store.ids(t) for t in ls.TIERS} == order
    assert {i: _piece(store, i) for i in members} == pieces
    other = next(i for i in store.ids("goal") if store.item(i)["parent_folder"] and _work(store, i) != _work(store, members[0]))
    with pytest.raises(ValueError):
        store.join([target, _piece(store, other)])
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_pieces_stay_contiguous_runs_of_one_work(language):
    """The property (05 §5.2 rule 1), over random command sequences with the Soon line kept: moves anywhere (into
    pieces, across the line, across tiers), set_tier, Adds into show folders and loose, removes and Put back, undos of
    earlier changes, splits and joins, the line dragged, a title split off and merged back — after every step each
    piece is one run of one work in one tier and every item has a work and a piece."""
    store = arrivals_off(migrated(language, shows=4, episodes=5, loose=2))
    data_dir, _u = roots(language)
    rng = random.Random(20261006)
    words = names(language)
    changes, trash = [], []
    for step in range(300):
        tiers = [t for t in ls.ANALYSED if store.ids(t)]
        tier = rng.choice(tiers)
        ids = store.ids(tier)
        op = rng.choice(["move", "move", "move", "tier", "insert", "remove", "restore", "undo", "split", "join",
                         "line", "rework"])
        out = None
        if op == "move":
            target = rng.choice(ls.ANALYSED)
            anchors = store.ids(target)
            picked = rng.sample(ids, min(len(ids), rng.randint(1, 3)))
            anchor = rng.choice([a for a in anchors if a not in picked] or [None])
            out = store.move(picked, target, after_id=anchor) if anchor and rng.random() < 0.5 else \
                store.move(picked, target, before_id=anchor) if anchor else store.move(picked, target)
        elif op == "tier":
            out = store.set_tier(rng.sample(ids, 1), rng.choice(["now", "soon", "goal", "graduated"]))
        elif op == "insert":
            some = rng.choice(ids)
            folder = store.item(some)["rel_path"].rsplit("/", 1)[0] if rng.random() < 0.7 else \
                ls.FOLDER_OF_TIER[tier]
            out = store.insert([touch(data_dir, f"{folder}/{words[step % len(words)]}_{step:04d}.srt")], tier)
        elif op == "remove" and len(ids) > 2:
            out = store.remove(rng.sample(ids, 1))
            trash += out.trash_ids
        elif op == "restore" and trash:
            try:
                out = store.restore([trash.pop(rng.randrange(len(trash)))])
            except ls.StoreConflict:                            # an undo put it back already
                pass
        elif op == "undo" and changes:
            try:
                store.undo(changes.pop(rng.randrange(len(changes))))
            except (ls.StoreConflict, ValueError):
                pass
        elif op == "split":
            piece = _piece(store, rng.choice(ids))
            members = _members(store, piece)
            if len(members) > 1:
                out = store.split(piece, rng.choice(members[1:]))
        elif op == "join":
            item = rng.choice(ids)
            mates = [_piece(store, i) for t in ls.ANALYSED for i in store.ids(t)
                     if _work(store, i) == _work(store, item) and _piece(store, i) != _piece(store, item)]
            if mates:
                out = store.join([_piece(store, item), rng.choice(mates)])
        elif op == "line":
            out = store.set_soon_line(rng.randint(0, len(store.ids("now")) + len(store.ids("soon")) + 2))
        elif op == "rework" and len(ids) > 1:
            out = store.split_work(rng.sample(ids, min(2, len(ids))), words[(step * 3) % len(words)])
        if out is not None and op not in ("restore",):
            changes.append(out)
        problem = pieces_ok(store)
        assert problem is None, f"step {step}: {op} — {problem}"
        n = store.meta()["soon_line"]
        current = store.ids("now") + store.ids("soon")
        assert store.ids("now") == current[:n], f"step {step}: {op} — the tiers left the line"
    store.close()


# --- search -------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_search_finds_titles_first_then_items_in_every_place(language):
    """05 §5.3: a search gives the titles whose name or other names hold the folded query, then the files whose own
    title does — over Current, 6+ Months, New arrivals and Finished; nothing for an empty query."""
    store = migrated(language, shows=2, episodes=2)
    data_dir, _u = roots(language)
    w = names(language)
    show = next(i for i in store.ids("goal") if store.item(i)["parent_folder"])
    work = _work(store, show)
    with store._writing():                                      # a romaji title, as hato's record or a match brings one
        store.conn.execute("UPDATE works SET titles = ? WHERE id = ?", (json.dumps(["Sousou no Frieren"]), work))
    store._cmd = None
    with store._command("test") as cmd:
        store._rekey_work(work)
        cmd.touch()
    store.set_tier([show], "graduated")
    works, items = store.search("sousou no FRIEREN")
    assert works == [work] and items == []
    title = store.item(show)["title"]
    works, items = store.search(title[:3])
    assert show in items, "a Finished file is found too"
    assert store.search("   ") == ([], [])
    arrived = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[87]}.srt"), _record("ks")).added[0]
    assert store.item(arrived)["tier"] == "arrivals" and arrived in store.search(w[87])[1]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_search_200k_under_20ms(language):
    """05 §5.3's measurement as a proof: a search scans the stored keys — at 200k files under 20 ms (the window
    debounces 120 ms on top). The budget holds in the timed run (200k); otherwise 20k, unbudgeted."""
    n = 200_000 if BENCH else 20_000
    store = big_store(language, n)
    word = names(language)[3]
    times = []
    for _ in range(9):
        t0 = time.perf_counter()
        works, items = store.search(word)
        times.append(time.perf_counter() - t0)
    assert works and items
    if BENCH:
        median = sorted(times)[4]
        print(f"\nsearch {language} {n}: median {median * 1000:.1f} ms")
        assert median <= 0.020, median
    store.close()


# ================================================================================================ #
# Media type, covers, the pin, Finished, placing (L3.1 row 3.1.5; the L2.2 pack 05 §5.4–5.8, 5.12)
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_users_media_type_is_never_overwritten(language):
    """05 §5.4, 06 §6.6: the user's *What is it?* is per title and wins — a hato record saying otherwise, a sync and a
    merge leave it; clearing it gives the guess back; undo by the value check."""
    store = migrated(language)
    data_dir, _u = roots(language)
    show = next(i for i in store.ids("now") if store.item(i)["parent_folder"])
    work = _work(store, show)
    change = store.set_media_type([work], "drama")
    assert store.media_type(work) == ("drama", "user")
    store.register(os.path.join(data_dir, store.item(show)["rel_path"]), _record("km", media_type="anime"))
    other = next(i for i in store.ids("goal") if store.item(i)["parent_folder"])
    store.merge_works(work, [_work(store, other)])
    store.sync_disk()
    assert store.media_type(work) == ("drama", "user")
    store.undo(change)
    assert store.media_type(work)[1] is None, "back to the guess"
    with pytest.raises(ValueError):
        store.set_media_type([work], "podcastz")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_episode_shows_its_titles_type(language):
    """05 §5.4: the type is the title's — every episode of it reads the same, so *What is it?* is answered once; a type
    hato's record carries is kept as hato's (until the user says)."""
    store = migrated(language, shows=2, episodes=4)
    data_dir, _u = roots(language)
    show = next(i for i in store.ids("soon") if store.item(i)["parent_folder"])
    work = _work(store, show)
    episodes = [i for t in ls.TIERS for i in store.ids(t) if _work(store, i) == work]
    store.register(os.path.join(data_dir, store.item(show)["rel_path"]), _record("kt", media_type="anime"))
    assert {store.media_type(_work(store, i)) for i in episodes} == {("anime", "hato")}
    store.set_media_type([work], "movie")
    assert {store.media_type(_work(store, i)) for i in episodes} == {("movie", "user")}
    store.close()


def test_the_guess_by_source_and_record():
    """05 §5.4's table (the guess, computed, never stored): YouTube / bilibili → youtube; epub → book; text → text;
    subtitles → anime with an AniList id, drama with a TMDB tv: id, movie with movie:; else None (*Video*, G2.2-5)."""
    guess = ls.media_type_guess
    assert guess({"youtube": 3}) == guess({"bilibili": 1}) == "youtube"
    assert guess({"epub": 2}) == "book" and guess({"text": 5}) == "text"
    assert guess({"subtitle": 12}, anilist_id=154587) == "anime"
    assert guess({"subtitle": 12}, tmdb_id="tv:1396") == "drama"
    assert guess({"subtitle": 1}, tmdb_id="movie:603") == "movie"
    assert guess({"subtitle": 12}) is None and guess({}) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_locked_cover_refuses_the_fetch(language):
    """05 §5.5, 06 §6.6: the fetch fills an unlocked cover; once the user chose one (locked), a fetch landing later is
    refused — no write, no error — and the user's choice undoes by the value check."""
    store = migrated(language)
    work = _work(store, store.ids("now")[0])
    fetched = store.set_cover(work, "anilist", ref="154587", path="cache:154587.jpg")
    assert fetched is not None
    row = store._work_row(work)
    assert (row["cover_source"], row["cover_locked"]) == ("anilist", 0) and row["cover_fetched_at"]
    mine = store.set_cover(work, "user", path="user:frieren.png", locked=True)
    assert store.set_cover(work, "tmdb", ref="tv:209867", path="cache:209867.jpg") is None, "refused"
    assert store._work_row(work)["cover_path"] == "user:frieren.png"
    store.undo(mine)
    assert store._work_row(work)["cover_path"] == "cache:154587.jpg" and store._work_row(work)["cover_locked"] == 0
    with pytest.raises(ValueError):
        store.set_cover(work, "user", path="C:/Users/x.png", locked=True)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_forget_downloaded_keeps_user_images(language):
    """05 §5.5: *Remove downloaded covers* clears the fetched, unlocked covers' paths; a user's image (user data) and a
    locked choice stay."""
    store = migrated(language, shows=3, episodes=2)
    works = sorted({_work(store, i) for i in store.ids("now") + store.ids("soon")})[:3]
    store.set_cover(works[0], "anilist", ref="1", path="cache:1.jpg")
    store.set_cover(works[1], "user", path="user:mine.png", locked=True)
    store.set_cover(works[2], "anilist", ref="2", path="cache:2.jpg", locked=True)
    assert store.forget_downloaded_covers() == [works[0]]
    assert store._work_row(works[0])["cover_path"] is None
    assert store._work_row(works[1])["cover_path"] == "user:mine.png"
    assert store._work_row(works[2])["cover_path"] == "cache:2.jpg"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_nothing_automatic_writes_pinned(language):
    """05 §5.6 (G1.6-10: "nothing is automatic"): only the user's pin, unpin and *Take its new cards out* write the
    pin — a register, a sync, a re-import, Connect's receipt and made words, a merge, the line, Reset, the upgrade's
    tidy leave every pinned item's pin as it was; a new episode of a pinned title is not pinned."""
    store = migrated(language, shows=2, episodes=3)
    data_dir, user_files_dir = roots(language)
    show = next(i for i in store.ids("now") if store.item(i)["parent_folder"])
    work = _work(store, show)
    episodes = [i for t in ls.TIERS for i in store.ids(t) if _work(store, i) == work]
    store.pin(episodes)
    pins = {i: store.item(i)["pinned"] for i in episodes}
    folder = store.item(show)["rel_path"].rsplit("/", 1)[0]
    new = store.register(touch(data_dir, f"{folder}/{names(language)[88]}.srt"), _record("kp")).added[0]
    store.receipt(show, "2026-10-06T11:00:00Z")
    store.record_made(show, [(names(language)[5], [1700000000009])], "b9")
    store.sync_disk()
    store.set_soon_line(1)
    store.merge_works(work, [_work(store, store.ids("goal")[0])])
    store.reset_order()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.tidy_works()
    assert {i: store.item(i)["pinned"] for i in episodes} == pins
    assert store.item(new)["pinned"] is None, "a new episode of a pinned title: not pinned"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pin_survives_finish_put_back_and_rebuild(language):
    """05 §5.6: the pin goes on through Finish ("stays on through Finish"), Remove → Put back and a rebuild from the
    copy; `pinned()` lists it in any tier, the oldest pin first, with what the re-plan needs."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    a, b = store.ids("now")[:2]
    store.pin([a])
    store.pin([b])
    stamp = store.item(a)["pinned"]
    store.finish([a])
    removed = store.remove([b])
    store.restore(removed.trash_ids)
    pins = store.pinned()
    assert [(p.item_id, p.tier, p.pinned_at) for p in pins] == [(a, "graduated", stamp),
                                                                 (b, store.item(b)["tier"], store.item(b)["pinned"])]
    assert pins[0].rel_path == store.item(a)["rel_path"]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert [(p.item_id, p.pinned_at) for p in store.pinned()] == [(a, stamp), (b, pins[1].pinned_at)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_taking_cards_out_ends_the_pin(language):
    """G2.2-8 (the later click wins): *Take its new cards out* at Finish — or after it — ends the pin and leaves the
    cards out of the learning order; its undo puts the pin and the cards' place back."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.pin([a, b])
    stamp = store.item(a)["pinned"]
    change = store.finish([a], keep_cards=False)
    assert store.item(a)["tier"] == "graduated" and store.item(a)["pinned"] is None
    assert store.item(a)["in_learning_order"] == 0
    store.undo(change)
    assert store.item(a)["tier"] == "now" and store.item(a)["pinned"] == stamp and store.item(a)["in_learning_order"] == 1
    store.finish([b])
    later = store.finish([b], keep_cards=False)                 # the toast's button, after Finish
    assert later is not None and store.item(b)["pinned"] is None and store.item(b)["tier"] == "graduated"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_finish_never_writes_a_known_word_or_a_card(language):
    """Q2-5, Q2-6 (05 §5.7): Finish moves the item to Finished, dated now, and writes nothing else — KnownWord.json,
    the word lists and the Anki records the store holds are unchanged byte for byte, in either keep-cards choice."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    known = os.path.join(user_files_dir, "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        json.dump({"words": [names(language)[1], names(language)[2]]}, f, ensure_ascii=False)
    with store._writing():
        store.conn.execute("INSERT INTO anki_links VALUES (?, 1700000000100, 'connect', 't')", (store.ids("now")[0],))
    before = (open(known, "rb").read(), store.conn.execute("SELECT * FROM anki_links").fetchall(),
              store.conn.execute("SELECT * FROM anki_changes").fetchall())
    a, b = store.ids("now")[:2]
    store.finish([a])
    store.finish([b], keep_cards=False)
    assert store.item(a)["tier"] == store.item(b)["tier"] == "graduated" and store.item(a)["graduated_at"]
    after = (open(known, "rb").read(), store.conn.execute("SELECT * FROM anki_links").fetchall(),
             store.conn.execute("SELECT * FROM anki_changes").fetchall())
    assert after == before
    assert a not in [e["physical_path"] for e in store.schedule()["PHASE_1_NOW"]], "not analysed: never counted"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_restores_exactly_the_recorded_card_changes(language):
    """05 §5.7 (D14's recorded default): the re-plan records every card it changes at Finish in `anki_changes`; Put
    back reads exactly the open records of those items — never another item's, never one already reverted — and marks
    them reverted. The store keeps the record; Anki's side is the re-plan's."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.finish([a, b], keep_cards=False)
    ids = store.record_anki_changes([(a, "suspend", [11, 12], {"queue": 0}, {"queue": -1}),
                                     (b, "suspend", [13], {"queue": 0}, {"queue": -1})])
    open_a = store.anki_changes_of([a])
    assert [(r["item_id"], r["notes"]) for r in open_a] == [(a, [11, 12])]
    store.move([a], "now")                                      # Put back
    assert store.mark_anki_reverted([r["id"] for r in open_a]) == 1
    assert store.anki_changes_of([a]) == [] and [r["notes"] for r in store.anki_changes_of([b])] == [[13]]
    assert len(ids) == 2
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_mine_it_too_is_answered_by_the_receipt(language):
    """05 §5.7 (A2 #31): *Mine it too* records when the user asked; Connect reads it and its receipt answers it (the
    window shows asked-and-not-mined); undo by the value check."""
    store = migrated(language)
    item = store.ids("now")[0]
    store.finish([item])
    asked = store.ask_mining([item])
    row = store.item(item)
    assert row["mine_asked"] and row["mined_at"] is None
    store.receipt(item, "2026-10-06T12:30:00Z")
    row = store.item(item)
    assert row["mined_at"] == "2026-10-06T12:30:00Z" and row["mined_at"] >= "2026" and row["mine_asked"]
    store.undo(asked)
    assert store.item(item)["mine_asked"] is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_import_finished_copies_outside_the_write_lock_and_never_re_adds(language, tmp_path):
    """05 §5.8: the importer's copying job (no store, no lock) copies files from outside the library into Graduated/,
    folders keeping their name; one short command records them in Finished, dated *Earlier*, each with its work and a
    piece; a file already in the library goes to Finished in the store only; the disk sync never re-adds them; one
    undo takes them out as an Add."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    outside = tmp_path / "finished-before"
    season = outside / w[90]
    season.mkdir(parents=True)
    for n in (1, 2):
        (season / f"{w[90]}_第{n:02d}話.srt").write_text(f"{w[91]} {n}\n", encoding="utf-8")
    single = outside / f"{w[92]}.txt"
    single.write_text(w[93] + "\n", encoding="utf-8")
    already = store.ids("soon")[0]
    copied = ls.copy_into_finished(data_dir, [str(season), str(single),
                                              os.path.join(data_dir, store.item(already)["rel_path"])])
    assert sorted(copied) == sorted([f"Graduated/{w[90]}/{w[90]}_第01話.srt", f"Graduated/{w[90]}/{w[90]}_第02話.srt",
                                     f"Graduated/{w[92]}.txt", store.item(already)["rel_path"]])
    assert season.exists(), "a copy: the user's files stay where they were"
    change = store.import_finished(copied)
    assert len(change.added) == 3 and store.item(already)["tier"] == "graduated"
    for item in change.added + [already]:
        row = store.item(item)
        assert row["tier"] == "graduated" and row["graduated_at"] is None and row["work_id"] and row["piece_id"]
    assert _work(store, change.added[0]) == _work(store, change.added[1]) != _work(store, change.added[2])
    assert store.sync_disk() is None, "never walked, never re-added"
    assert store.import_finished(copied) is None
    store.undo(change)
    assert all(store.item(i) is None for i in change.added) and store.item(already)["tier"] == "soon"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_rule_target_for_hato_youtube_a_channel_and_another_tool(language):
    """05 §5.12 (Q2-3, G1.2-12): `register` places a drop waiting in New arrivals by the user's rule for its source —
    hato, YouTube, one channel (`youtube:<id>` over `youtube`), another tool by its producer name — in the same command:
    top (Current's first row), soon (the first slot below the line), goal, finished, after-show; `wait` and no rule
    leave it in New arrivals."""
    store = migrated(language, shows=2, episodes=3)
    data_dir, _u = roots(language)
    w = names(language)
    rules = {"hato": "top", "youtube": "goal", "youtube:UC123": "soon", "my-tool": "finished", "another": "wait"}
    top = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[94]}.srt"), _record("r1"), rules=rules)
    assert store.ids("now")[0] == top.added[0] and top.rule == "top"
    yt = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[95]}.srt"), _record("r2", producer="youtube"), rules=rules)
    assert store.ids("goal")[0] == yt.added[0]
    ch = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[96]}.srt"),
                        _record("r3", producer="youtube", channel_id="UC123"), rules=rules)
    assert store.ids("soon")[0] == ch.added[0], "the channel's line wins; Soon's first row"
    done = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[97]}.srt"), _record("r4", producer="my-tool"),
                          rules=rules)
    assert store.item(done.added[0])["tier"] == "graduated"
    waits = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[98]}.srt"), _record("r5", producer="another"),
                           rules=rules)
    assert store.ids("arrivals") == waits.added
    show = next(i for i in store.ids("soon") if store.item(i)["parent_folder"] and i != ch.added[0])
    folder = store.item(show)["rel_path"].rsplit("/", 1)[0]
    last = [i for i in store.ids("soon") if store.item(i)["rel_path"].rsplit("/", 1)[0] == folder][-1]
    after = store.register(touch(data_dir, f"{folder}/{w[99]}.srt"), _record("r6", producer="tool"),
                           rules={"tool": "after-show"})
    soon = store.ids("soon")
    assert soon[soon.index(last) + 1] == after.added[0], "after its title's last episode in Current"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_rules_off_means_new_arrivals(language):
    """D30, RD-S16: with no rule (the default: `placing_rules` empty in settings.json) every drop waits in New
    arrivals — nothing places itself, nothing writes settings.json; a back-fill places by no rule."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    settings = os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")
    before = open(settings, "rb").read() if os.path.exists(settings) else None
    one = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[100]}.srt"), _record("o1"))
    two = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[101]}.srt"), _record("o2"), backfill=True,
                         rules={"hato": "top"})
    assert store.ids("arrivals") == one.added + two.added
    assert (open(settings, "rb").read() if os.path.exists(settings) else None) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_rule_placement_is_the_users_own_and_mined(language):
    """D30, P1.5-8: a rule the user turned on places the drop as the user's own action — logged as its source's,
    explicit — so it enters the mine line like any of the user's placements; without a rule it waits, logged as the
    producer's, never explicit, and nothing mines it there."""
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    mark = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM placement_log").fetchone()[0]
    placed = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[102]}.srt"), _record("m1"),
                            rules={"hato": "top"}).added[0]
    waiting = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[103]}.srt"), _record("m2"),
                             rules={}).added[0]
    log = [tuple(r) for r in store.conn.execute("SELECT item_id, kind, by, explicit FROM placement_log WHERE id > ? "
                                                "ORDER BY id", (mark,))]
    assert (placed, "placed", "hato", 1) in log and (placed, "entered_mine_line", "hato", 1) in log
    assert [e for e in log if e[0] == waiting] == [(waiting, "placed", "hato", 0)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sync_lands_a_hato_drop_in_new_arrivals(language):
    """Michi's P2.1 review #6 (K82), ✅ L3.1 call b: with New arrivals on, a file the disk sync finds in hato's drop
    folder before its `register` waits in New arrivals by no rule — even with a rule for hato turned on in
    settings.json — so a show's own rule gets its turn: only hato's hand-off (`register`, which knows the show) applies
    the placing rules, and a drop whose hand-off never comes keeps waiting. With them off, 2.x's rule: the top of NOW
    (Q4-11)."""
    from app.path_utils import get_user_file
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    with open(get_user_file("settings.json"), "w", encoding="utf-8") as f:
        json.dump({"placing_rules": {"hato": "top"}}, f)
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[104]}.srt")
    first = store.sync_disk()["added"][0]
    assert store.item(first)["tier"] == "arrivals", "the scan applies no rule"
    change = store.register(os.path.join(data_dir, ls.HATO_FOLDER, f"{w[104]}.srt"), _record("s1"))
    assert change.added == [] and store.item(first)["tier"] == "arrivals", "a hand-off without rules: it waits"
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[105]}.srt")
    ruled = store.sync_disk()["added"][0]
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[107]}.srt")
    never = store.sync_disk()["added"][0]
    assert store.ids("arrivals")[-2:] == [ruled, never]
    change = store.register(os.path.join(data_dir, ls.HATO_FOLDER, f"{w[105]}.srt"), _record("s2"),
                            rules={"hato": "top"})
    assert change.rule == "top" and store.ids("now")[0] == ruled, "hato's hand-off places it by the caller's rules"
    assert store.item(never)["tier"] == "arrivals", "no hand-off: it waits"
    store.set_library_options(arrivals_on=False)
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[106]}.srt")
    old = store.sync_disk()["added"][0]
    assert store.ids("now")[0] == old
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_place_soon_and_after_show(language):
    """04 §4.2: `place --where soon` is the first slot below the Soon line; `after-show` goes after the title's episode
    before it in Current, before the next when only later episodes are there, and to Current's top when its title is
    only in Finished or 6+ Months (Q4-9). Each is one undoable command."""
    store = migrated(language, shows=2, episodes=4)
    now = store.ids("now")
    change = store.place([now[0]], "soon")
    assert store.ids("soon")[0] == now[0]
    store.undo(change)
    assert store.ids("now") == now
    goal_show = [i for i in store.ids("goal") if store.item(i)["parent_folder"]]
    work = _work(store, goal_show[0])
    mates = [i for i in goal_show if _work(store, i) == work]
    placed = store.place([mates[-1]], "after-show")
    assert store.ids("now")[0] == mates[-1], "its title only in 6+ Months: Current's top"
    soon_show = [i for i in store.ids("soon") if store.item(i)["parent_folder"]]
    mates = [i for i in soon_show if _work(store, i) == _work(store, soon_show[0])]
    store.move([mates[1]], "goal")
    store.place([mates[1]], "after-show")
    soon = store.ids("soon")
    assert soon[soon.index(mates[-1]) + 1] == mates[1], "after the title's last item in Current (no episode numbers)"
    assert placed is not None and pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_cards_of_and_made_words(language):
    """05 §5.6, 04 §4.3 #7: `cards_of` = an item's Anki links ∪ the notes Connect made for it; `record_made` keeps a
    word's first record (never made again, even with its notes deleted) and records for an item removed meanwhile."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    with store._writing():
        store.conn.execute("INSERT INTO anki_links VALUES (?, 500, 'miner', 't')", (a,))
    assert store.record_made(a, [(names(language)[1], [501, 502]), (names(language)[2], [503])], "b1") == \
        [names(language)[1], names(language)[2]]
    assert store.record_made(a, [(names(language)[1], [999])], "b2") == []
    assert store.cards_of([a, b]) == {a: [500, 501, 502, 503], b: []}
    assert store.made(a)[names(language)[1]] == [501, 502]
    store.remove([b])
    assert store.record_made(b, [(names(language)[3], [504])], "b3") == [names(language)[3]]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_register_headless_applies_the_callers_rules_and_says_so(language):
    """05 §5.12 (3.0: the rule inside `register`, the command line's own step goes): `register_headless(rules=)` —
    the rules the caller read from settings.json — places the drop in the same command and answers which rule did;
    without rules it waits, as before."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.close()
    placed = ls.register_headless(language, touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[116]}.srt"),
                                  _record("h1"), data_dir, user_files_dir, rules={"hato": "top"})
    assert (placed.landed, placed.rule, placed.tier, placed.position) == ("arrivals", "top", "now", 1)
    waits = ls.register_headless(language, touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[117]}.srt"),
                                 _record("h2"), data_dir, user_files_dir)
    assert (waits.landed, waits.rule, waits.tier) == ("arrivals", None, "arrivals")


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_season_is_another_title(language):
    """W1.2 §1.3 (a season is a title, its own cover): a record naming the same show in another season starts a title
    of its own; no season named is the first."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    one = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[118]}.srt"),
                         _record("s1", show={"title": "Example Show", "season": 1, "episode": 4})).added[0]
    two = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[119]}.srt"),
                         _record("s2", show={"title": "Example Show", "season": 2, "episode": 1})).added[0]
    plain = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[120]}.srt"),
                           _record("s3", show={"title": "Example Show", "season": None, "episode": 5})).added[0]
    assert _work(store, one) != _work(store, two) and _work(store, plain) == _work(store, one)
    store.close()
