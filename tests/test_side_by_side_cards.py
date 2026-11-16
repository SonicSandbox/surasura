"""Kyou-C: with *New cards come from: Current's top two, side by side* on, the window, Connect's top N and Generate's
order pick the titles Junban weaves in Anki — by Junban's count of each title's still-new cards (`Store.set_side_cards`,
written after every Junban run; `library_store.side_pair`, the one rule every reader follows). And the turns cost one
pass over Current, whatever its size: the same order, byte for byte, as before.

What a wrong answer would cost a learner: Anki weaving titles B and C while the window shows A and B (a tester's case:
A, a book whose parts have nothing new, kept a place it gives no card from) — the stones, *Waiting* and Connect's
mining on a title Anki shows nothing of; or, the other way, a title never mined yet stepping aside before Connect could
make a single card of it (it would never get one); or, with no count (Anki absent, no run yet), anything but today's
order. And a drop on a big library freezing the window for over a second (681 ms a read at 1,000 titles, two a drop).

Every store test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with
real words from tests/Test Resources/ (`library_store_support.names`).
"""
import random

import pytest

from app import library_store as ls
from app.connect import library
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES, names, roots
from tests.test_side_by_side import _library, _paths, _scheduled


def _write(store, a, b, loose, d, counts):
    """Junban's count, by title name (`a`, `b`, `loose`, `d` -> the title's still-new cards), into the store."""
    by = {"a": a, "b": b, "loose": [loose], "d": d}
    return store.set_side_cards([(by[name], n) for name, n in counts.items()])


def _view(store):
    feed = store.read_feed()
    return view_rows.build({r["id"]: r for r in feed["items"]}, {w["id"]: w for w in feed["works"]}, feed["options"],
                           pieces={p["id"]: p for p in feed["pieces"]})


def _in_top(view):
    return {e.id for row in view.rows for e in row.episodes if e.in_top}


# --- the one rule: Junban's count --------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_junban_counted_no_new_card_for_steps_aside_in_every_reader_and_the_next_takes_its_turn(language):
    """The tester's case. A (6 episodes: a book of parts with nothing new, its first already mined) has files left but
    Junban counted no still-new card for it; B, the loose file and Soon's D have cards. A steps aside as it does in
    Anki: B and the loose file take turns (the loose file runs out; Kyou-D: D is below the Soon line, so B goes on
    alone), then A's files after every turn — Connect's top N (still in turns), the window's top, Generate's order;
    Junban is still handed every title that can take turns, A too, so its next count can bring A back."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    store.receipt(a[0], ls._now())                      # Connect mined A's next file: nothing new came of it
    assert store._mine_ids(4) == [a[0], b[0], a[1], b[1]], "no count yet: by files, as before"
    order = store.versions()["order_version"]
    assert _write(store, a, b, loose, d, {"a": 0, "b": 2, "loose": 1, "d": 3}) is True
    assert store.versions()["order_version"] > order, "who takes turns moved: the order did (Generate follows)"
    turned = [b[0], loose, b[1], b[2]] + a + d
    assert store._mine_ids(4) == turned[:4], "Connect's top N: B and the loose file in turns, then B alone"
    assert store._mine_ids(20) == turned
    assert library.mine_line(store) == turned[:4], "Connect reads the store's own line"
    now = [i for i, tier in store.scheduled_ids() if tier == "now"]
    assert now[-len(a):] == a and set(now[:-len(a)]).isdisjoint(a), "Generate's order: A after every turn"
    assert _scheduled(store) == _paths(store, [i for i, _t in store.scheduled_ids()])
    view = _view(store)
    assert view.side_cards == ls.side_cards(store.read_feed()["options"]["side_cards"])
    assert _in_top(view) == set(turned[:4]), "the window's top: what Connect mines, A's files dimmed"
    assert store.side_by_side() == [a, b, [loose]], "Junban still counts every title that can take turns"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_connect_has_not_mined_yet_keeps_its_turn_so_it_can_get_its_cards(language):
    """A counted none because Connect never mined it (new to Current, or its mined files all watched): it keeps its
    turn, so its files enter the top and Connect mines them — Junban weaves its cards from the next count. Mining its
    next file then sets it aside (a receipt moves the order then, as the count does)."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    _write(store, a, b, loose, d, {"a": 0, "b": 2, "loose": 1, "d": 3})
    assert store._mine_ids(4) == [a[0], b[0], a[1], b[1]], "nothing of A mined yet: by its files"
    order = store.versions()["order_version"]
    store.receipt(a[0], ls._now())
    assert store.versions()["order_version"] > order, "the receipt moved who takes turns: the order moved"
    assert store._mine_ids(4) == [b[0], loose, b[1], b[2]], "Kyou-D: D, below the Soon line, never steps in"
    store.set_watched([a[0]])                           # its mined file watched: the next is new to Connect
    assert store._mine_ids(4) == [a[1], b[0], a[2], b[1]], "A's next file unmined: A takes its turn again"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("count", ["none", "unreadable", "names_no_title", "every_title_none"])
def test_with_no_count_that_names_a_title_with_cards_every_reader_reads_by_files_as_today(language, count):
    """Anki absent or no Junban run yet (no count), a count the store can't read, one naming none of Current's titles
    (written for another library state), or one where every title has none: today's order exactly, nothing crashes —
    the window falls back to the files as the store does."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    for item_id in (a[0], b[0], loose, d[0]):
        store.receipt(item_id, ls._now())
    today = (store._mine_ids(20), _scheduled(store), store.scheduled_ids(), _in_top(_view(store)))
    if count == "unreadable":
        with store._writing():
            store._set_meta({ls.SIDE_CARDS: "{not json"})
    elif count == "names_no_title":
        with store._writing():
            store._set_meta({ls.SIDE_CARDS: '{"w999999": 0, "i999999": 0}'})
    elif count == "every_title_none":
        _write(store, a, b, loose, d, {"a": 0, "b": 0, "loose": 0, "d": 0})
    assert (store._mine_ids(20), _scheduled(store), store.scheduled_ids(), _in_top(_view(store))) == today
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_the_count_does_not_name_takes_its_turn_by_its_files(language):
    """D came into Current after Junban's last run (the count doesn't name it): it takes its turn by its files (Kyou-D:
    the Soon line holds all of Current here, D too — a title below it never steps in)."""
    store, a, b, loose, d = _library(language)
    store.set_soon_line(12)
    store.set_library_options(mine_line=6, side_by_side=True)
    for item_id in (a[0], loose):
        store.receipt(item_id, ls._now())
    _write(store, a, b, loose, d, {"a": 0, "b": 2, "loose": 0})
    assert store._mine_ids(6) == [b[0], d[0], b[1], d[1], b[2]] + [a[0]]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_count_is_written_only_when_it_changes_and_moves_the_order_only_when_the_pair_does(language):
    """S19: the same count again writes nothing; a count that changes nobody's turn (B 2 -> 5 cards, both "has
    cards") is no write either; one whose title Connect hasn't mined (the loose file, now none) is written — the
    window reads it — but the order stays."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(side_by_side=True)
    store.receipt(a[0], ls._now())
    assert _write(store, a, b, loose, d, {"a": 0, "b": 2, "loose": 1, "d": 1}) is True
    v = store.versions()
    assert _write(store, a, b, loose, d, {"a": 0, "b": 5, "loose": 1, "d": 1}) is False
    assert store.versions() == v
    assert _write(store, a, b, loose, d, {"a": 0, "b": 5, "loose": 0, "d": 1}) is True
    after = store.versions()
    assert after["state_version"] > v["state_version"] and after["order_version"] == v["order_version"]
    assert store.read_feed()["options"]["side_cards"][ls.card_key(ls.title_key(loose, store.item(loose)["work_id"]))] == 0
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_side_by_side_off_reads_no_count(language):
    """Off, a count left from when it was on changes nothing: every reader as today."""
    store, a, b, loose, d = _library(language)
    today = (store._mine_ids(20), _scheduled(store), store.scheduled_ids())
    store.receipt(a[0], ls._now())
    _write(store, a, b, loose, d, {"a": 0, "b": 2, "loose": 1, "d": 1})
    assert (store._mine_ids(20), _scheduled(store), store.scheduled_ids()) == today
    assert store.side_by_side() == []
    store.close()


def test_the_rule_pure_steps_aside_only_a_mined_title_counted_none():
    """`side_pair` on rows: w1 counted 0 and its next file mined -> aside; w2 counted 0, next file not mined -> on;
    w3 not counted -> on; fewer than two titles to study -> None."""
    rows = [(1, "now", 1, "available", 0, "2026-10-16"), (2, "now", 1, "available", 0, None),
            (3, "now", 2, "available", 0, None), (4, "now", 2, "available", 0, "2026-10-16"),
            (5, "soon", 3, "available", 0, None)]
    cards = {"w1": 0, "w2": 0}
    w1, w2, w3 = ("w", 1), ("w", 2), ("w", 3)
    assert ls.side_pair(rows, cards=cards) == ([w1, w2, w3], [w2, w3], [w1])
    assert ls.side_pair(rows) == ([w1, w2, w3], [w1, w2, w3], [])
    assert ls.side_pair(rows[:2], cards=cards) is None
    assert ls.side_cards('{"w1": 1, "i5": 0, "bad": "x"}') == {"w1": 1, "i5": 0}
    assert ls.side_cards("[1, 2]") is None and ls.side_cards(None) is None
    title = {1: w1, 2: w1, 3: w2, 4: w2, 5: w3}.get
    assert ls.woven([1, 2, 3, 4, 5], title, [w2, w3], aside=[w1]) == [3, 5, 4, 1, 2], "aside: after every turn"
    assert ls.woven([1, 2, 3, 4, 5], title, [w2, w3], aside=[w1], n=2) == [3, 5]


# --- the cost: one pass, the same order byte for byte ----------------------------------------------------------- #
# The functions as they were (Kyou-B, 3.0.14), kept here as the reference the one-pass versions must equal.
def _old_turns(seqs, width=None):
    queues = [list(s) for s in seqs]
    out, at = [], [0] * len(queues)
    while True:
        moved = False
        live = [k for k, q in enumerate(queues) if at[k] < len(q)]
        for k in live[:width] if width is not None else live:
            out.append(queues[k][at[k]])
            at[k] += 1
            moved = True
        if not moved:
            return out


def _old_side_titles(rows, keep=False, n=None):
    out = []
    for item_id, tier, work_id, availability, watched in rows:
        if availability != "available" or not ls.counts(tier, watched, keep):
            continue
        key = ls.title_key(item_id, work_id)
        if key not in out:
            out.append(key)
            if len(out) == n:
                break
    return out


def _old_woven(ids, title_of, titles, width=ls.SIDE_TITLES):
    rank = {key: k for k, key in enumerate(titles)}
    groups = [[] for _t in titles]
    for item_id in ids:
        k = rank.get(title_of(item_id))
        if k is not None:
            groups[k].append(item_id)
    out, placed = [], False
    for item_id in ids:
        if title_of(item_id) in rank:
            if not placed:
                out.extend(_old_turns(groups, width))
                placed = True
            continue
        out.append(item_id)
    return out


def _generated(titles, seed):
    """Current as the store's rows: `titles` titles of 1–40 files (some items with no work, a title of their own), a
    file now and then watched, missing or waiting, NOW then Soon."""
    rng = random.Random(seed)
    rows, item = [], 0
    for t in range(titles):
        work = None if rng.random() < 0.1 else t
        for _f in range(1 if work is None else rng.randint(1, 40)):
            item += 1
            availability = rng.choices(("available", "missing", "waiting"), (90, 6, 4))[0]
            rows.append((item, "now" if t < titles // 10 else "soon", work, availability, int(rng.random() < 0.15),
                         None))
    return rows


@pytest.mark.parametrize("titles", [50, 200, 1000])
@pytest.mark.parametrize("keep", [False, True])
def test_the_turns_read_byte_for_byte_as_before_at_50_200_and_1000_titles(titles, keep):
    """The one-pass `turns` / `side_titles` / `woven` (and the window's `side_order`, stopping at the line's N) give
    exactly the order the per-round versions gave, two at a time and every one at once."""
    for seed in range(3):
        rows = _generated(titles, seed)
        old_titles = _old_side_titles([r[:5] for r in rows], keep)
        assert ls.side_titles(rows, keep) == old_titles
        assert ls.side_titles(rows, keep, n=2) == old_titles[:2]
        title_of = {r[0]: ls.title_key(r[0], r[2]) for r in rows}.get
        ok = [r[0] for r in rows if r[3] == "available" and ls.counts(r[1], r[4], keep)]
        every = [r[0] for r in rows]
        want = _old_woven(ok, title_of, old_titles)
        assert ls.woven(ok, title_of, old_titles) == want
        assert ls.woven(every, title_of, old_titles) == _old_woven(every, title_of, old_titles)
        assert ls.woven(ok, title_of, old_titles, width=None) == _old_woven(ok, title_of, old_titles, width=None)
        assert view_rows.side_order(rows, keep) == want, "the window's copy: the store's order"
        assert view_rows.side_order(rows, keep, n=20) == want[:20]
        groups = [[r[0] for r in rows if r[2] == t] for t in range(titles)]
        for width in (None, 1, 2, 3):
            assert ls.turns(groups, width) == _old_turns(groups, width)
    assert ls.turns([[1, 2]], 0) == _old_turns([[1, 2]], 0) == []


def _big(language, titles, per):
    """A store of `titles` titles of `per` files each in Current (two in NOW, the rest Soon), one work a show folder,
    named from the real word list; no files on disk (availability set), as `library_store_support.big_store`."""
    data_dir, user_files_dir = roots(language)
    store = ls._helper_store(ls.library_db_path(language, data_dir), language, data_dir, user_files_dir)
    ls._ensure_schema(store)
    words = names(language)
    items = []
    for t in range(titles):
        show = f"{words[t % len(words)]}{t:04d}"
        for e in range(per):
            tier = "now" if t < 2 else "soon"
            item = ls._item_from_entry(ls.make_entry(f"{ls.FOLDER_OF_TIER[tier]}/{show}/{show}_{e:03d}.srt",
                                                     "Disk Sync", "subtitle"), tier, data_dir, ls._now())
            item["availability"], item["size"], item["mtime_ns"] = "available", 100, 1
            items.append(item)
    with store._writing():
        ls._write_image(store, {"items": items, "tables": {}}, ls._fresh_meta("big" + language, 1, 1))
        store._set_meta({"migrated_at": ls._now()})
    store.close()
    store = ls.open_store(language, data_dir, user_files_dir)
    with store._writing():
        for (folder,) in store.conn.execute("SELECT DISTINCT parent_folder FROM items").fetchall():
            work = store.conn.execute("INSERT INTO works (title, search_key, created_at) VALUES (?, ?, ?)",
                                      (folder, folder, ls._now())).lastrowid
            store.conn.execute("UPDATE items SET work_id = ? WHERE parent_folder = ?", (work, folder))
    return store


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_big_librarys_line_and_generates_order_read_as_before(language):
    """200 titles / 4,000 files: the store's own readers (Connect's top N, Generate's order, the window's numbers) give
    the order the per-round functions give on the store's own rows."""
    store = _big(language, 200, 20)
    store.set_library_options(side_by_side=True)
    rows = [r[:5] for r in store._current_rows()]
    titles = _old_side_titles(rows)
    title_of = {r[0]: ls.title_key(r[0], r[2]) for r in rows}.get
    ok = [r[0] for r in rows if r[3] == "available" and ls.counts(r[1], r[4], False)]
    want = _old_woven(ok, title_of, titles)
    assert store._mine_ids(20) == want[:20] and store._mine_ids(5000) == want
    by_tier = {t: [r[0] for r in rows if r[1] == t] for t in ("now", "soon")}
    assert [i for i, _t in store.scheduled_ids() if _t in by_tier] == \
        _old_woven(by_tier["now"], title_of, titles) + _old_woven(by_tier["soon"], title_of, titles)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_soon_line_keeps_the_titles_taking_turns_above_it_not_the_one_aside(language):
    """The Soon line after 3 files: with A aside, the first three turns are B's — the loose file is below the line, so
    it never steps in (Kyou-D) — every row down to B's third stays in NOW (A's rows with it: the line never splits
    Current's order; A's three past the count are within the reach's allowance)."""
    store, a, b, loose, d = _library(language)
    store.set_soon_line(3)
    store.set_library_options(side_by_side=True)
    store.receipt(a[0], ls._now())
    _write(store, a, b, loose, d, {"a": 0, "b": 2, "loose": 1, "d": 1})
    assert store.ids("now") == a + b
    assert store._mine_ids(3) == [b[0], b[1], b[2]]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_missing_file_waits_in_the_top_when_its_titles_next_file_is_mined(language):
    """B's first episode is missing: the turns mine B's second, and the missing first waits on the top (Needs you's),
    in the window's own read as in a drop's."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    with store._writing():
        store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (b[0],))
    view = _view(store)
    assert store._mine_ids(4) == [a[0], b[1], a[1], b[2]]
    assert _in_top(view) == {a[0], a[1], b[0], b[1], b[2]}
    assert view_rows.side_top(view.rows, 4)[1] == _in_top(view)
    store.close()
