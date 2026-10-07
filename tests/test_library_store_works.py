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
    store.move(m1, "goal")                                      # the whole piece to the top: its id stays
    assert _members(store, p1) == m1
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
