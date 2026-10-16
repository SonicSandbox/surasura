"""The window's search (W3.2 S4): `app/services/search.py`.

What a wrong answer would cost a learner:
  * a title they typed not found — by its kana, its kanji, its romaji name or (Chinese) the other script;
  * the wrong text lit, or a lit span that isn't the match (a romaji match lights nothing in a Japanese title);
  * a show split in two listed once, so ▶ / ⤒ act on the wrong part, or its two pieces indistinguishable;
  * a where-line that sends them to the wrong place (*#7 in Current* for the row at #3), or ⤒ offered on the hero;
  * a flood of results, or results for an empty box.

Each test runs on a real `library_store` (built from the window's seed — invented titles from W0.2's closed vocabulary,
Japanese and Chinese — under the test's own root) and the view the reader builds from its feed; the 20,000-file seed
measures a query on the searcher's own thread.
"""
import threading

import pytest

from app import library_store as ls
from app.services import search as S
from app.services import view_rows
from tests.fixtures import window_seed
from tests.test_library_store_support import roots, touch

ROMAJI = "Hoshifuru Machi no Chiisana Koubou"       # the hero's other title, as hato's record would bring it


# --- helpers ------------------------------------------------------------------------------------------------------ #
def real_store(seed, titles=None):
    """The seed written into a real store (one transaction, as `big_store` builds one): its works (their types, AniList
    ids and `titles` — {work id: [other titles]}), its items in their tiers and order, watched, finished dates, missing
    files and arrival times; the store seeds the pieces and the search keys itself. → an open Store."""
    language = seed.language
    data_dir, user_files_dir = roots(language)
    db = ls.library_db_path(language, data_dir)
    store = ls._helper_store(db, language, data_dir, user_files_dir)
    ls._ensure_schema(store)
    now = ls._now()
    first_rel = {}
    for r in seed.items:
        first_rel.setdefault(r["work_id"], r["rel_path"])
    fields = ["id", "title", "title_by_user", "titles", "folder_key", "anilist_id", "tmdb_id", "youtube_channel",
              "media_type", "media_type_by", "cover_source", "cover_locked", "feed_in", "created_at"]
    works = [[w["id"], w["title"], 0, ls._dumps((titles or {}).get(w["id"], [])),
              ls.folder_key_of(first_rel[w["id"]]), w["anilist_id"], None, w["youtube_channel"], w["media_type"],
              w["media_type_by"], "generated", 0, 1, now] for w in seed.works if w["id"] in first_rel]
    items = []
    for r in seed.items:
        entry = ls.make_entry(r["rel_path"], "Disk Sync", r["source_type"])
        items.append(ls._item_from_entry(entry, r["tier"], data_dir, now, id=r["id"], work_id=r["work_id"],
                                         watched=r["watched"], graduated_at=r["graduated_at"], mined_at=r["mined_at"],
                                         pinned=r["pinned"], added_at=r["added_at"], availability=r["availability"],
                                         size=100, mtime_ns=1))
    meta = ls._fresh_meta("search" + language, 1, 1)
    with store._writing():
        ls._write_image(store, {"items": items, "tables": {"works": {"fields": fields, "rows": works}}}, meta)
        store._set_meta({"migrated_at": now})
    store.close()
    return ls.open_store(language, data_dir, user_files_dir)


def view_of(store, language):
    """The view the reader builds from the store's feed (`LibraryReader._build`, without its thread)."""
    feed = store.read_feed()
    items = {r["id"]: r for r in feed["items"]}
    works = {w["id"]: w for w in feed["works"]}
    return view_rows.build(items, works, feed["options"], language=language)


def groups_of(store, view, query, **kw):
    return {g.kind: g for g in S.search(store, view, query, **kw)}


def lit(hit):
    return [hit.title[a:b] for a, b in hit.spans]


def work_title(seed, work_id):
    return next(w["title"] for w in seed.works if w["id"] == work_id)


@pytest.fixture(params=["ja"])
def small(request):
    seed = window_seed.build(language=request.param)
    store = real_store(seed, titles={seed.hero_work: [ROMAJI]})
    yield seed, store, view_of(store, seed.language)
    store.close()


# --- what it finds and where it says it is ----------------------------------------------------------------------- #
def test_a_kanji_query_finds_the_hero_lights_the_match_and_offers_play_but_never_top(small):
    """The hero is Current's first row: its where-line is *#1 in Current*, ▶ is offered (its next episode is on disk),
    ⤒ is not (it's already the top); the lit text is exactly the typed kanji in the title."""
    seed, store, view = small
    hero = view.rows[0]
    query = hero.title[-4:]                                          # 小さな工房's 工房 and the kana before it
    groups = groups_of(store, view, query)
    hit = groups["current"].hits[0]
    assert hit.key == hero.key and hit.title == hero.title
    assert lit(hit) == [query]
    assert hit.where == "#1 in Current"
    assert hit.can_play is True and hit.can_top is False
    assert hit.item_ids == tuple(e.id for e in hero.episodes)
    assert hit.accessible == f"{hero.title} · #1 in Current"


def test_a_hiragana_query_finds_a_katakana_title_in_finished_and_says_its_month(small):
    """Katakana and hiragana are one key (the store's fold), half-width katakana too: ガラスの鯨が泳ぐ空 is found by
    がらす and by ｶﾞﾗｽ, its ガラス lit; a Finished row says *Finished · <its month>* and offers ⤒ but never ▶."""
    seed, store, view = small
    row, month = next((r, m.label) for m in view.finished for r in m.rows if r.title.startswith("ガラス"))
    for query in ("がらす", "ｶﾞﾗｽ"):
        hit = groups_of(store, view, query)["finished"].hits[0]
        assert hit.key == row.key and lit(hit) == ["ガラス"], query
        assert hit.where == f"Finished · {month}" and month == "September 2026"
        assert hit.can_play is False and hit.can_top is True


def test_a_romaji_title_finds_the_show_but_lights_nothing_in_its_japanese_title(small):
    """By romaji the store matches the title's other names (G2.2-4: no converter), case and spacing folded; the shown
    title doesn't hold the match, so nothing is lit — and the hit is still the hero's row."""
    seed, store, view = small
    hit = groups_of(store, view, "chiisana  KOUBOU")["current"].hits[0]
    assert hit.key == view.rows[0].key and hit.spans == ()


def test_a_split_show_is_listed_once_per_piece_each_with_its_range_and_place(small):
    """A show in two parts in Current (Ep 1–4 at #3, Ep 5–8 at #7) is two hits, each naming its range before its
    place, so ▶ and ⤒ act on the part the learner means; a title in Goal in two runs is one Goal hit (Goal's sheet tiles
    by title) counting all its episodes, next up its first unwatched."""
    seed, store, view = small
    split_rows = [r for r in view.rows if r.title == view.rows[2].title]
    assert len(split_rows) == 2
    hits = groups_of(store, view, split_rows[0].title)["current"].hits
    assert [h.key for h in hits] == [r.key for r in split_rows]
    assert [h.where for h in hits] == [f"Ep 1–4 · #{split_rows[0].index} in Current",
                                       f"Ep 5–8 · #{split_rows[1].index} in Current"]
    assert split_rows[0].index == 3 and split_rows[1].index == 7
    goal_work = next(r["work_id"] for r in seed.items if r["tier"] == "goal")
    title = work_title(seed, goal_work)
    goal_ids = [r["id"] for r in seed.items if r["work_id"] == goal_work]
    g = groups_of(store, view, title)["goal"]
    assert len(g.hits) == 1 and g.total == 1
    assert g.hits[0].where == "Goal · 24 episodes · next up: Ep 1" and g.hits[0].key == f"w{goal_work}"
    assert sorted(g.hits[0].item_ids) == sorted(goal_ids) and lit(g.hits[0]) == [title]
    store.set_watched(goal_ids[:2])                                  # two watched: next up moves on
    assert groups_of(store, view, title)["goal"].hits[0].where == "Goal · 24 episodes · next up: Ep 3"


def test_a_show_in_new_arrivals_says_so_with_its_episodes(small):
    """The tray's hato show is found in *New arrivals*, its where-line its episodes as the tray reads them."""
    seed, store, view = small
    arrival = next(a for a in view.arrivals if a.source == "hato" and a.group == "new")
    hit = groups_of(store, view, arrival.title)["arrivals"].hits[0]
    assert hit.key == arrival.key and hit.where == "New arrivals · Ep 1–6" and lit(hit) == [arrival.title]
    assert hit.item_ids == arrival.item_ids and hit.can_play is False and hit.can_top is True


def test_groups_come_in_the_overlays_order_and_each_is_cut_at_six_in_its_own_order(tmp_path):
    """On the 2,000-file seed a query every subtitle holds (.srt) matches hundreds of rows: each group holds at most 6,
    in its own order (Current by place, Finished newest month first), says how many matched, and the groups come
    Current · Goal · New arrivals · Finished."""
    seed = window_seed.build(files=2000, root=str(tmp_path))
    store = real_store(seed)
    try:
        view = view_of(store, "ja")
        groups = S.search(store, view, ".srt")
        assert [g.kind for g in groups] == ["current", "goal", "arrivals", "finished"]
        assert [g.label for g in groups] == ["Current", "Goal", "New arrivals", "Finished"]
        by = {g.kind: g for g in groups}
        for g in groups:
            assert len(g.hits) <= 6
        def srt(rows):                                                  # the rows holding a subtitle (books don't)
            return [r.key for r in rows if any(e.rel_path.endswith(".srt") for e in r.episodes)]
        current = srt(view.rows)
        assert by["current"].total == len(current) > 6
        assert [h.key for h in by["current"].hits] == current[:6]
        assert by["goal"].total > 6 and by["finished"].total > 6
        fin = srt([r for m in view.finished for r in m.rows])
        assert [h.key for h in by["finished"].hits] == fin[:6] and by["finished"].total == len(fin)
        assert len(by["arrivals"].hits) == by["arrivals"].total == len(view.arrivals)
        assert len(S.search(store, view, ".srt", limit=2)[0].hits) == 2
    finally:
        store.close()


def test_an_empty_or_blank_query_and_one_that_finds_nothing_give_no_groups(small):
    """No results overlay for an empty box (A2 #79), whitespace alone, nothing found, or no view yet."""
    seed, store, view = small
    for query in ("", "   ", "\t　", None):
        assert S.search(store, view, query) == ()
    assert S.search(store, view, "存在しない題名") == ()
    assert S.search(store, None, "工房") == ()


def test_chinese_titles_are_found_from_either_script_and_lit_in_their_own():
    """A Chinese title is keyed in Simplified (`search_fold`, app/zh_script): a Traditional query finds a Simplified
    title, a Simplified query finds a title written in Traditional, and each is lit in its own characters."""
    seed = window_seed.build(language="zh")
    store = real_store(seed)
    try:
        data_dir, _u = roots("zh")
        show = "雷鳴之劍外傳"                                           # a title written in Traditional, added to Goal
        added = store.insert([touch(data_dir, f"GoalContent/{show}/{show} 第{n:02d}集.srt", f"{show}\n")
                              for n in (1, 2)], "goal").added
        assert len(added) == 2
        view = view_of(store, "zh")
        simplified = next(r for r in view.rows if r.title.startswith("雷鸣之剑"))
        groups = groups_of(store, view, "雷鳴之劍")                       # typed in Traditional
        hit = groups["current"].hits[0]
        assert hit.key == simplified.key and lit(hit) == ["雷鸣之剑"]
        assert hit.where == f"#{simplified.index} in Current"
        groups = groups_of(store, view, "雷鸣之剑")                       # typed in Simplified
        goal = groups["goal"].hits[0]
        assert goal.title == show and lit(goal) == ["雷鳴之劍"]
        assert goal.where == "Goal · 2 episodes · next up: Ep 1" and sorted(goal.item_ids) == sorted(added)
        assert groups["current"].hits[0].key == simplified.key
    finally:
        store.close()


def test_spans_follow_the_fold_and_map_back_to_the_titles_own_characters():
    """The lit spans are in the title's characters whatever the fold did: full-width letters, a whitespace run read as
    one space, every occurrence, overlapping ones merged; none for a query the title doesn't hold."""
    assert S.spans("ＦＲＩＥＲＥＮ　第2期", "frieren", "ja") == ((0, 7),)
    assert S.spans("海辺の   図書室", "の 図書", "ja") == ((2, 8),)
    assert S.spans("ほのか ほのか", "ほのか", "ja") == ((0, 3), (4, 7))
    assert S.spans("ああああ", "ああ", "ja") == ((0, 4),)
    assert S.spans("星降る街", "kitchen", "ja") == () and S.spans("", "a") == () and S.spans("星", "  ") == ()
    assert S.spans("學習中文頻道", "学习", "zh") == ((0, 2),)


# --- the searcher: off the window's thread, the latest query wins ------------------------------------------------ #
def test_the_searcher_answers_on_its_own_thread_over_twenty_thousand_files_and_the_latest_query_wins(tmp_path):
    """On the 20,000-file seed: a query runs on the searcher's thread with its own handle (never the caller's), answers
    with the groups and its time (printed; RUNBOOK's 50 ms is the timed run's budget), and of a burst of keystrokes the
    last is always answered — the ones queued behind it are dropped, never answered after it."""
    seed = window_seed.build(files=20000, root=str(tmp_path))
    store = real_store(seed, titles={seed.hero_work: [ROMAJI]})
    data_dir, user_files_dir = roots("ja")
    try:
        view = view_of(store, "ja")
        assert view.counts.current_files + view.counts.goal_files + view.counts.finished > 0
        opener = ls.StoreOpener("ja", data_dir, user_files_dir)
        searcher = S.Searcher(opener, lambda: view)
        answers, threads = [], []

        def heard(query, groups, ms):
            threads.append(threading.current_thread().name)
            answers.append((query, groups, ms))
        queries = [view.rows[0].title[:3], "がらす", ROMAJI.split()[0].lower(), ".srt", view.rows[2].title]
        for _ in range(3):
            for q in queries:
                searcher.ask(q, heard)
                assert searcher.idle(30)
        assert set(threads) == {"library-search"}
        times = sorted(ms for _q, _g, ms in answers[len(queries):])          # the first round warms the handle
        print(f"\nsearch over {seed.files} files, off-thread: median {times[len(times) // 2]:.1f} ms, "
              f"max {times[-1]:.1f} ms")
        last = {q: g for q, g, _ms in answers}
        assert last[queries[0]][0].hits[0].key == view.rows[0].key
        assert last[queries[2]][0].hits[0].spans == ()
        assert all(len(g.hits) <= 6 for g in last[".srt"])
        answers.clear()
        for q in queries:                                                  # a burst: no waiting between keystrokes
            searcher.ask(q, heard)
        assert searcher.idle(30)
        assert answers[-1][0] == queries[-1] and len(answers) <= len(queries)
        searcher.close()
    finally:
        store.close()


def test_the_searcher_finds_nothing_while_the_store_cant_be_read_and_never_raises():
    """A store not in store mode (getting ready, read-only) answers no groups; a read that fails answers none too, and
    the next query is still answered."""
    calls = []

    class Opener:
        mode = "json"

        def check(self):
            return self.mode

        def handle(self):
            raise RuntimeError("the store went away")

    opener = Opener()
    searcher = S.Searcher(opener, lambda: None)
    searcher.ask("工房", lambda q, g, ms: calls.append((q, g)))
    assert searcher.idle(5)
    opener.mode = "store"
    searcher.ask("工房", lambda q, g, ms: calls.append((q, g)))
    assert searcher.idle(5)
    assert calls == [("工房", ()), ("工房", ())]
    searcher.close()
