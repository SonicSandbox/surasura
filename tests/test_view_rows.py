"""What the window derives from the library (W2.2; the window's spec 02 §2.2–2.4): `app/services/view_rows.py`, pure
and Qt-free, tested without a window on hand-made feed rows with real Japanese and Chinese titles.

Each test names the rule it holds (a piece is a row; the hero's *Up next*; the top-20 line counts available files; one
*% known*; one status vocabulary; Finished by month; Needs you per show; the subline) and why it matters to a learner.
"""
import pytest

from app.services import view_rows as vr

WORKS = {}


def work(wid, title, media="anime", channel=None, anilist=None):
    w = {"id": wid, "title": title, "title_by_user": 0, "titles": "[]", "folder_key": title, "anilist_id": anilist,
         "tmdb_id": None, "youtube_channel": channel, "media_type": media, "media_type_by": None,
         "cover_source": "generated", "cover_ref": None, "cover_path": None, "cover_fetched_at": None,
         "cover_locked": 0, "feed_in": 1}
    WORKS[wid] = w
    return w


def items_of(spec):
    """spec: [(tier, work_id, piece_id, [file names], {per-file overrides by index})] -> {id: feed row}."""
    out, ords, iid = {}, {}, 1
    for tier, wid, pid, names, extra in spec:
        for k, name in enumerate(names):
            ords[tier] = ords.get(tier, 0) + 1024.0
            row = {"id": iid, "tier": tier, "ord": ords[tier], "rel_path": f"HighPriority/{name}", "title": name,
                   "parent_folder": None, "source_type": "subtitle", "availability": "available", "work_id": wid,
                   "piece_id": pid, "watched": 0, "mined_at": None, "pinned": None, "mine_asked": None,
                   "graduated_at": None, "in_learning_order": 1, "added_at": "2026-10-01T00:00:00Z", "feed_in": 1}
            row.update(extra.get(k, {}))
            out[iid] = row
            iid += 1
    return out


def eps(title, a, b):
    return [f"{title} - {n:02d}.srt" for n in range(a, b + 1)]


@pytest.fixture(autouse=True)
def _works():
    WORKS.clear()
    work(1, "星降る街の小さな工房")
    work(2, "雲の上の郵便屋さん")
    work(3, "白銀の書庫番", media="lightnovel")
    work(4, "Tsubasa no Kitchen", media="youtube", channel="Tsubasa no Kitchen")
    yield


def test_episode_numbers_come_from_the_file_names_in_every_common_shape():
    """The store keeps no episode numbers (store digest §2.5): the window reads them from names, or the row would say
    *8 episodes* where the learner expects *Ep 1–8*."""
    assert vr.episode_number("星降る街 - 05.srt") == 5
    assert vr.episode_number("Show.S01E12.1080p.mkv") == 12
    assert vr.episode_number("雲の上の郵便屋さん 第7話.ass") == 7
    assert vr.episode_number("show_ep03_final.srt") == 3
    assert vr.episode_number("Hanashi Radio #28.srt") == 28
    assert vr.episode_number("白銀の書庫番 02 雨の街角.txt") == 2
    assert vr.episode_number("[Group] 海辺の図書室 - 11 [1080p].srt") == 11
    assert vr.episode_number("なぜ人は行列に並ぶのか.srt") is None
    # a year in brackets, a date and a resolution are never an episode (W2.2 review A-11)
    assert vr.episode_number("雨音の子 (2019).srt") is None
    assert vr.episode_number("Hanashi Radio 2026-09-02.srt") is None
    assert vr.episode_number("海辺の図書室 - 05 [1080p] x264.mkv") == 5
    # a release's checksum in brackets is never an episode: [E04F4EFB] was read as "E04"
    assert vr.episode_number("[SubsPlease] 海辺の図書室 - 01 (1080p) [E04F4EFB].mkv") == 1
    assert vr.episode_number("[Group] 星降る街 - 12 [1E2F3A4B].ja.ass") == 12
    assert vr.episode_number("Show S01E05 [ABCD1234].mkv") == 5


def test_ranges_say_the_parts_a_row_holds_with_gaps():
    assert vr.range_text("anime", [1, 2, 3, 4], 4) == "Ep 1–4"
    assert vr.range_text("anime", [5], 1) == "Ep 5"
    assert vr.range_text("anime", [1, 2, 3, 4, 6], 5) == "Ep 1–4, 6"
    assert vr.range_text("podcast", [28, 29, 30, 31, 32, 33, 34, 36], 8) == "#28–34, 36"
    assert vr.range_text("lightnovel", [5, 6, 7], 3) == "Parts 5–7"
    assert vr.range_text("youtube", [], 3) == "3 videos"
    assert vr.range_text("youtube", [], 1) == "1 video"
    assert vr.range_text("anime", [1, 2], 3) == "3 episodes"           # a name without a number: the count, not a lie


def test_a_row_is_a_piece_so_a_split_show_is_two_rows_and_each_says_its_part():
    """A piece is one contiguous run of one work's items in one tier (store digest §2.3): a show split in two shows as
    two rows, each with its own range."""
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 4), {}),
                      ("now", 2, 11, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("now", 1, 12, eps("星降る街の小さな工房", 5, 8), {})])
    view = vr.build(items, WORKS, {"mine_line": 20})
    assert [r.title for r in view.rows] == ["星降る街の小さな工房", "雲の上の郵便屋さん", "星降る街の小さな工房"]
    assert view.rows[0].line == "Ep 1–4" and view.rows[2].line == "Ep 5–8"
    assert [r.index for r in view.rows] == [1, 2, 3]


def test_without_piece_ids_a_works_run_is_one_row():
    """3.0-dev's stores before L3.1 leave new items without a piece: a run of one work still reads as one row."""
    items = items_of([("now", 1, None, eps("星降る街の小さな工房", 1, 6), {})])
    view = vr.build(items, WORKS, {})
    assert len(view.rows) == 1 and view.rows[0].n_files == 6


def test_current_is_now_then_soon_and_the_soon_line_sits_where_soon_starts():
    items = items_of([("soon", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {})])
    view = vr.build(items, WORKS, {"soon_line": 4})
    assert [r.tier for r in view.rows] == ["now", "soon"]
    soon = [ln for ln in view.lines if ln.kind == "soon"]
    assert soon and soon[0].after == 0 and "4" in soon[0].tip


def _straddle(piece_ids=True):
    """55 files in Current, the Soon line at 25 (the store's count): 星降る街 22 episodes, then 雲の上の郵便屋さん's 4
    episodes at files 23–26 — its first 3 NOW, its 4th the first file of Soon (the store cuts a piece at the line) —
    then 海辺の図書室's 29 episodes, wholly Soon."""
    work(5, "海辺の図書室")
    p = (lambda n: n) if piece_ids else (lambda n: None)
    return items_of([("now", 1, p(10), eps("星降る街の小さな工房", 1, 22), {}),
                     ("now", 2, p(11), eps("雲の上の郵便屋さん", 1, 3), {}),
                     ("soon", 2, p(12), eps("雲の上の郵便屋さん", 4, 4), {}),
                     ("soon", 5, p(13), eps("海辺の図書室", 1, 29), {})])


@pytest.mark.parametrize("piece_ids", [True, False])
def test_a_show_the_soon_line_runs_through_is_one_row_above_the_line_and_the_next_show_below(piece_ids):
    """P-LF-16 (Sonic, 2026-10-21): the Soon line counts files, so it can fall mid-series; the tiers and Generate stay
    per file, but the window never splits a show at the line — it is one row above the line, the line is drawn after
    it, and the first Soon show comes after. Before, its 4th episode was a second row of the same show below the
    line."""
    view = vr.build(_straddle(piece_ids), WORKS, {"mine_line": 20, "soon_line": 25})
    assert [r.title for r in view.rows] == ["星降る街の小さな工房", "雲の上の郵便屋さん", "海辺の図書室"]
    show = view.rows[1]
    assert show.tier == "now" and show.n_files == 4 and show.line == "Ep 1–4" and show.soon_from == 3
    assert [e.number for e in show.episodes] == [1, 2, 3, 4]
    soon = [ln for ln in view.lines if ln.kind == "soon"]
    assert len(soon) == 1 and soon[0].after == 1 and "25" in soon[0].tip       # after the show, never inside it
    assert view.rows[2].tier == "soon" and view.rows[2].soon_from is None
    # the counts and place numbers are the rows as shown: 3 rows, every file still counted once
    assert [r.index for r in view.rows] == [1, 2, 3]
    assert view.counts.current_rows == 3 and view.counts.current_files == 55
    assert "3 in Current · 55 files" in view.subline
    # the top-20 line is the files' own: through the first row, its first 20 episodes mine themselves
    top = [ln for ln in view.lines if ln.kind == "top"]
    assert len(top) == 1 and top[0].after == 0 and top[0].split == 20
    assert all(e.in_top for e in view.rows[0].episodes[:20]) and not any(e.in_top for e in show.episodes)


def test_a_show_wholly_below_the_line_stays_below_and_a_show_apart_from_the_line_is_never_joined():
    """Only a show the line runs through is kept whole: a show wholly in Soon stays below the line, and a later part of
    the last NOW show with another show between them stays its own row (a split the learner made)."""
    work(5, "海辺の図書室")
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 4), {}),
                      ("soon", 5, 13, eps("海辺の図書室", 1, 3), {}),
                      ("soon", 1, 14, eps("星降る街の小さな工房", 5, 8), {})])
    view = vr.build(items, WORKS, {"soon_line": 4})
    assert [(r.title, r.tier, r.n_files) for r in view.rows] == [
        ("星降る街の小さな工房", "now", 4), ("海辺の図書室", "soon", 3), ("星降る街の小さな工房", "soon", 4)]
    assert all(r.soon_from is None for r in view.rows)
    assert [ln.after for ln in view.lines if ln.kind == "soon"] == [0]


def test_B2_9_a_show_holding_the_whole_of_soon_still_has_the_soon_line_drawn_after_it():
    """B2-9: when Soon is nothing but the tail of the show the line runs through, the line is still drawn after that
    show (before, no row was in Soon, so none was drawn) — by the one rule the drag's lines use too."""
    items = _straddle()
    items = {k: v for k, v in items.items() if v["work_id"] != 5}     # no other show in Soon
    view = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 25})
    assert [(r.title, r.soon_from) for r in view.rows] == [("星降る街の小さな工房", None), ("雲の上の郵便屋さん", 3)]
    soon = [ln for ln in view.lines if ln.kind == "soon"]
    assert len(soon) == 1 and soon[0].after == 1 and "25" in soon[0].tip
    assert vr.soon_line_after(view.rows) == 1
    assert vr.soon_line_after(view.rows[:1]) is None                   # nothing in Soon, nothing cut: no line


def test_B2_8_before_connects_first_look_the_rows_show_no_top_line_and_no_waiting():
    """B2-8 (Michi's call): the reader builds with the feed's last look (`Provider.latest`); before any look Connect is
    not known to be on (`feed.NOT_LOOKED`: `on` False, the one test), so the first screen never shows the top line and
    *Waiting* only for them to go once a look finds Connect off. Nothing is read for it: no stamp, no record."""
    from app.connect import feed
    looked = []
    provider = feed.Provider("ja", lambda: {"connect_enabled": False}, stamp=lambda **k: looked.append("stamp"),
                             read=lambda **k: looked.append("read"))
    first = provider.latest()
    assert first is feed.NOT_LOOKED and first.on is False and first.line is None and looked == []
    items = _straddle()
    without = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 25})
    assert [ln.kind for ln in without.lines] == ["top", "soon"]           # no Feed at all: today's view
    start = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 25}, connect=first)
    assert [ln.kind for ln in start.lines] == ["soon"]
    assert not any(r.status is not None and r.status.kind == "waiting" for r in start.rows)
    off = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 25}, connect=provider.feed())
    assert off.lines == start.lines and [r.status for r in off.rows] == [r.status for r in start.rows]   # no flash


def test_B2_2_split_piece_names_each_episodes_own_piece_and_no_split_the_line_already_makes():
    view = vr.build(_straddle(), WORKS, {"mine_line": 20, "soon_line": 25})
    show = view.rows[1]
    assert (show.piece_id, show.soon_from, show.soon_piece) == (11, 3, 12)
    assert vr.split_piece(show, 1) == (11, 1) and vr.split_piece(show, 2) == (11, 2)
    assert vr.split_piece(show, 3) is None                             # the Soon line parts it there already
    assert vr.split_piece(show, 0) is None and vr.split_piece(view.rows[2], 5) == (13, 5)
    one = vr.build(_straddle(piece_ids=False), WORKS, {"mine_line": 20, "soon_line": 25}).rows[1]
    assert one.soon_from == 3 and vr.split_piece(one, 3) is None       # no piece: nothing to split


def test_a_show_the_soon_line_runs_through_is_the_same_row_object_next_build_and_survives_the_first_screen_cache():
    """S19: a build with nothing changed gives back the same row (the window repaints nothing); the first screen's
    cache keeps the cut, so the first frame draws the line after the show too."""
    import json
    items = _straddle()
    cache = vr.RowCache()
    one = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 25}, numbers=(1, {}), cache=cache)
    two = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 25}, numbers=(1, {}), cache=cache)
    assert two.rows[1] is one.rows[1] and two.rows[1].soon_from == 3
    back = vr.from_cache(json.loads(json.dumps(vr.to_cache(one))))
    assert back.rows[1].soon_from == 3 and back.rows[2].soon_from is None
    assert [ln.after for ln in back.lines if ln.kind == "soon"] == [1]


def test_the_hero_is_the_first_row_and_up_next_skips_the_watched_episodes():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 8), {0: {"watched": 1}, 1: {"watched": 1}})])
    hero = vr.build(items, WORKS, {}).rows[0]
    assert hero.next_index == 2 and hero.title_ep == "Ep 3"
    assert [c.next for c in hero.chips].index(True) == 2
    assert hero.chips[0].watched and not hero.chips[2].watched


def test_when_every_episode_is_watched_up_next_is_the_last():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {k: {"watched": 1} for k in range(3)})])
    hero = vr.build(items, WORKS, {}).rows[0]
    assert hero.next_index == 2


def test_more_than_twelve_episodes_show_twelve_chips_and_the_rest_as_a_count():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 20), {})])
    hero = vr.build(items, WORKS, {}).rows[0]
    assert len(hero.chips) == 12 and hero.more_chips == 8


def test_the_top_20_line_counts_available_files_so_missing_ones_push_it_down():
    """The store's `_mine_ids`: the top n *available* files mine themselves. A missing file can't be mined, so it
    doesn't use up a place — the line sits after the row holding the 20th available file."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 12), {k: {"availability": "missing"} for k in (2, 3)}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 8), {}),
                      ("now", 3, 3, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 5)], {})])
    view = vr.build(items, WORKS, {"mine_line": 20})
    top = [ln for ln in view.lines if ln.kind == "top"]
    assert top and top[0].after == 2                     # 10 + 8 = 18 available, the 20th is in row 3
    assert "20" in top[0].tip


def test_W1_the_top_line_skips_a_watched_file_while_the_library_keeps_none_by_the_stores_one_rule():
    """W-1 (`library_store.counts`): a watched episode of Current has nothing left to mine while *Keep studying watched
    episodes* is off — it uses up no place under the line, as the store's `_mine_ids` reads it; with the option on it
    counts as before. The view carries the option (the stones' tip, the first mark's toast)."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 12), {k: {"watched": 1} for k in (0, 1)}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 8), {}),
                      ("now", 3, 3, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 5)], {})])
    current = sorted(items.values(), key=lambda r: r["ord"])
    off = vr._mine_ids(current, 20, False)
    assert off[:2] == [3, 4] and len(off) == 20 and 1 not in off and 2 not in off
    assert vr._mine_ids(current, 20, True)[:2] == [1, 2]
    view = vr.build(items, WORKS, {"mine_line": 20})                   # absent: off
    top = [ln for ln in view.lines if ln.kind == "top"]
    assert top and top[0].after == 2 and not view.keep_watched        # 10 + 8 count, the 20th is in row 3
    view = vr.build(items, WORKS, {"mine_line": 20, "keep_watched": 1})
    top = [ln for ln in view.lines if ln.kind == "top"]
    assert top and top[0].after == 1 and view.keep_watched            # 12 + 8: the line after row 2


def test_W1_the_first_screens_cache_keeps_the_librarys_option_and_an_older_cache_reads_off():
    """Review W-3: the cached first screen is shown before the store is read — it carries *Keep studying watched
    episodes*, or a library with it on would show the stones' and the mark's words for it off (and spend its hint)."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {})])
    for keep in (0, 1):
        view = vr.build(items, WORKS, {"mine_line": 20, "keep_watched": keep})
        assert vr.from_cache(vr.to_cache(view)).keep_watched is bool(keep)
    older = vr.to_cache(vr.build(items, WORKS, {"keep_watched": 1}))
    older.pop("keep_watched")
    assert vr.from_cache(older).keep_watched is False


def test_W1_a_mark_moves_the_list_only_where_the_stores_rule_says():
    """Review W-6: one rule (`library_store.counts`) for the stone's line, the mark's words and its hint — a studied
    tier's episode while the option is off; never with it on, never in Finished or New arrivals, never a video waiting
    for its subtitle."""
    ep = vr.build(items_of([("now", 1, 1, eps("雲の上の郵便屋さん", 1, 2), {})]), WORKS, {}).rows[0].episodes[0]
    assert [t for t in ("now", "soon", "goal", "graduated", "arrivals") if vr.mark_moves_list(t, ep, False)] == [
        "now", "soon", "goal"]
    assert not any(vr.mark_moves_list(t, ep, True) for t in ("now", "soon", "goal"))
    assert not vr.mark_moves_list("now", ep._replace(waiting=True), False)


def test_no_top_line_when_current_has_fewer_files_than_the_line():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 5), {})])
    assert not [ln for ln in vr.build(items, WORKS, {"mine_line": 20}).lines if ln.kind == "top"]


def test_three_missing_in_the_top_20_say_no_video_in_amber_and_the_row_says_so_too():
    """A2 #5: the three with no video in the top 20 say so, in amber (the heads-up tone), on each episode, and the
    row's mark counts them amber beside its Waiting pill."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 8), {k: {"availability": "missing"} for k in (2, 5, 7)}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 20), {})])
    row = vr.build(items, WORKS, {"mine_line": 20}).rows[0]
    missing = [e for e in row.episodes if e.missing]
    assert len(missing) == 3
    assert all(e.status.kind == "no_media" and e.status.tone == "warn" and e.status.label == "No video"
               for e in missing)
    assert row.status.kind == "waiting"
    assert row.mark.count == 3 and row.mark.tone == "warn" and "Ep 3" in row.mark.tip


def test_missing_below_the_line_is_faint_not_amber():
    items = items_of([("now", 2, 2, eps("雲の上の郵便屋さん", 1, 20), {}),
                      ("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {k: {"availability": "missing"} for k in range(4)})])
    row = vr.build(items, WORKS, {"mine_line": 20}).rows[1]
    assert row.status.kind == "no_media" and row.status.tone == "faint" and row.status.label == "No video · 4"


def test_mined_then_its_video_removed_is_in_anki_and_marked_and_its_play_names_the_removal():
    """A2 #7 and #8: an episode mined and then its video deleted is still ✓ in Anki, carries the dim no-video mark, and
    its ▶ says the video was removed and offers Link."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3),
                       {0: {"mined_at": "2026-10-01T00:00:00Z"}, 1: {"mined_at": "2026-10-01T00:00:00Z",
                                                                     "availability": "missing"},
                        2: {"mined_at": "2026-10-01T00:00:00Z"}})])
    view = vr.build(items, WORKS, {}, cards={1: 5, 2: 7, 3: 4})
    row = view.rows[0]
    gone = row.episodes[1]
    # the pill shows ✓ and the number only; the words are in its tooltip and what a screen reader says (G2.3 R2)
    assert gone.removed and gone.status.kind == "in_anki" and gone.status.label == "7"
    assert vr.spoken(gone.status) == "7 in Anki" and "in Anki" in gone.status.tip
    assert gone.mark is None or gone.mark.tone == "faint"
    assert row.status.kind == "in_anki" and row.status.label == "16" and " in Anki" in row.accessible   # the hero says it
    assert row.mark is not None and row.mark.tone == "faint" and "deleted after mining" in row.mark.tip
    assert not gone.can_play and "removed" in gone.play_tip and "link" in gone.play_tip.lower()


def test_one_status_vocabulary_in_the_mocks_order():
    st = lambda **kw: vr.status_of([type("E", (), dict(dict(label="Ep 1", cards=0, mined=False, missing=False,
                                                            removed=False, in_top=False, mining=False), **kw))()],
                                   "video", 20)[0]
    assert st(cards=3, mined=True).label == "3" and vr.spoken(st(cards=3, mined=True)) == "3 in Anki"
    assert st(mining=True).kind == "mining"
    assert st(in_top=True).label == "Waiting"
    assert st().label == "Mine"
    assert st(missing=True).label == "No video"
    many = [type("E", (), dict(label=f"Ep {k}", cards=2 if k < 2 else 0, mined=k < 2, missing=False, removed=False,
                               in_top=False, mining=False))() for k in range(5)]
    assert vr.status_of(many, "video", 20)[0].label == "2/5 · Mine rest"
    for e in many[2:]:
        e.in_top = True
    assert vr.status_of(many, "video", 20)[0].label == "2/5 · Waiting"


def test_percent_known_is_one_token_sum_never_a_mean_and_a_dash_before_a_generate():
    """QT-E8 / G1.2-4: known ÷ counted tokens over the whole piece. (90 % of 1,000 and 50 % of 10 is 89.6 %, not the
    70 % a mean gives.) Before a Generate the number is a dash, never 0 %."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 1), {})])
    view = vr.build(items, WORKS, {}, numbers={1: (900, 1000, 12), 2: (5, 10, 3)})
    row = view.rows[0]
    assert round(row.pct, 1) == 89.6 and row.n_new == 15
    assert row.pct_tone == "warn"
    assert view.rows[1].pct is None and vr.pct_text(view.rows[1].pct) == "—"
    assert "not analysed" in view.rows[1].accessible


def test_the_percent_colour_marks_learned_and_heads_up_and_leaves_the_middle_plain():
    assert vr.pct_tone(97.0) == "ok" and vr.pct_tone(96.6) == "ok"          # rounds as it's shown
    assert vr.pct_tone(95.0) == "plain" and vr.pct_tone(93.0) == "plain"
    assert vr.pct_tone(92.4) == "warn" and vr.pct_tone(None) == "plain"


def test_a_single_video_is_title_first_and_its_channel_below():
    items = items_of([("now", 4, 4, ["【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"], {0: {"source_type": "youtube"}})])
    row = vr.build(items, WORKS, {}).rows[0]
    assert row.title == "【検証】一週間お弁当を作り続けてみた" and row.line == "Tsubasa no Kitchen"
    assert row.source == "youtube" and not row.can_play and "online" in row.play_tip.lower()   # its video is online


def test_partly_watched_rows_say_how_many_but_the_hero_does_not():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 5), {0: {"watched": 1}, 1: {"watched": 1}})])
    view = vr.build(items, WORKS, {})
    assert view.rows[1].line == "Ep 1–5 · 2 of 5 watched"


def test_finished_is_by_month_newest_first_with_earlier_last_and_no_numbers():
    items = items_of([("graduated", 1, 1, eps("星降る街の小さな工房", 1, 2), {0: {"graduated_at": "2026-08-02T00:00:00Z"},
                                                                     1: {"graduated_at": "2026-08-02T00:00:00Z"}}),
                      ("graduated", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {}),
                      ("graduated", 3, 3, ["白銀の書庫番 01 章.txt"], {0: {"graduated_at": "2026-09-21T00:00:00Z",
                                                                       "pinned": "2026-09-22T00:00:00Z"}})])
    view = vr.build(items, WORKS, {})
    assert [m.label for m in view.finished] == ["September 2026", "August 2026", "Earlier"]
    sep = view.finished[0].rows[0]
    assert sep.studying and sep.date == "Sep 21"
    assert view.counts.finished == 3


def test_needs_you_lists_each_show_the_top_20_waits_on_with_one_line_per_episode():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 8), {k: {"availability": "missing"} for k in (2, 5)}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 20), {k: {"availability": "missing"} for k in (18, 19)})])
    view = vr.build(items, WORKS, {"mine_line": 20})
    assert len(view.needs) == 1                              # the second show's missing ones are below the line
    need = view.needs[0]
    assert need.title == "星降る街の小さな工房 · 2 episodes have no video"
    assert [e[0] for e in need.episodes] == ["Ep 3", "Ep 6"]
    assert "top 20" in need.line and view.badges["needs"] == 1


def test_the_subline_counts_rows_and_files_in_current_and_says_when_nothing_is_added():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {}), ("soon", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("goal", 3, 3, ["白銀の書庫番 01 章.txt"], {})])
    assert vr.build(items, WORKS, {}).subline == "日本語 · 2 in Current · 7 files"
    assert vr.build({}, WORKS, {}).subline == "日本語 · nothing added yet"
    assert vr.build({}, WORKS, {}, language="zh").subline == "中文 · nothing added yet"


def test_goals_strip_counts_titles_and_files_with_a_thousands_separator():
    items = items_of([("goal", 1, 1, eps("星降る街の小さな工房", 1, 600), {}), ("goal", 2, 2, eps("雲の上の郵便屋さん", 1, 700), {}),
                      ("goal", 1, 3, eps("星降る街の小さな工房", 601, 700), {})])
    goal = vr.build(items, WORKS, {}).goal
    assert goal.titles == 2 and goal.files == 1400 and goal.line == "2 titles · 1,400 files"
    assert goal.covers == ("星降る街の小さな工房", "雲の上の郵便屋さん")
    assert vr.build({}, WORKS, {}).goal.line == "Goal is empty"


@pytest.mark.parametrize("mode,reason,state", [("store", None, "empty"), ("json", "not ready", "getting-ready"),
                                               ("read-only", "damaged", "read-only")])
def test_each_mode_gives_its_state(mode, reason, state):
    assert vr.build({}, WORKS, {}, mode=mode, reason=reason).state == state
    assert vr.build({}, WORKS, {}, loading=True).state == "loading"


def test_a_chinese_library_reads_the_same_way():
    work(5, "雷鸣之剑与见习魔女")
    items = items_of([("now", 5, 5, ["雷鸣之剑与见习魔女 第3集.srt", "雷鸣之剑与见习魔女 第4集.srt"], {})])
    view = vr.build(items, WORKS, {}, language="zh")
    assert view.rows[0].line == "Ep 3–4" and view.subline.startswith("中文")


def test_every_row_answers_its_accessible_text_and_the_hero_reads_its_next_episode():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})])
    view = vr.build(items, WORKS, {}, numbers={1: (95, 100, 4), 2: (95, 100, 6), 3: (90, 100, 1), 4: (80, 100, 2)})
    # all four files are within the top 20, so they mine by themselves (Waiting), though no line is drawn under 20
    assert view.rows[1].accessible == "雲の上の郵便屋さん · 85% known · 3 new · Waiting"
    assert view.rows[1].description == "Ep 1–2"
    # the hero is painted from Up next (its next episode), so it reads that way too (IK-12); its status is its row's
    # (Q33), said as the whole's, never with the episode's numbers (AD-9)
    assert view.rows[0].accessible == "Up next: 星降る街の小さな工房 Ep 1 · 95% known · 4 new · all of it: Waiting"


def test_the_first_screen_round_trips_through_the_cache():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 30), {k: {"availability": "missing"} for k in (2,)}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {})])
    view = vr.build(items, WORKS, {"mine_line": 20}, numbers={1: (9, 10, 1)})
    import json
    data = json.loads(json.dumps(vr.to_cache(view)))
    back = vr.from_cache(data)
    assert back.cached and back.state == "loading"
    assert back.rows == view.rows[:vr.CACHE_ROWS] and back.lines == view.lines and back.subline == view.subline
    assert vr.from_cache({"rows": "nonsense"}) is None


def test_twenty_thousand_files_are_all_accounted_for():
    """Every file of a 20,000-file library lands in exactly one place the window shows (its build time is the bench's
    figure, measured under the timed lock: never a bound here, where a loaded machine would make it flake)."""
    from tests.fixtures import window_seed
    seed = window_seed.build(files=20000)
    items = {r["id"]: r for r in seed.items}
    works = {w["id"]: w for w in seed.works}
    view = vr.build(items, works, {"mine_line": 20, "soon_line": 40}, numbers=seed.numbers()[1])
    assert view.counts.current_files + view.counts.goal_files + view.counts.arrival_files + \
        sum(len(r.episodes) for m in view.finished for r in m.rows) == 20000



def test_a_mine_line_of_zero_draws_no_line_and_nothing_waits():
    """A-4: 0 is a setting (nothing mines itself), not "unset"."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 30), {})])
    view = vr.build(items, WORKS, {"mine_line": 0})
    assert not [ln for ln in view.lines if ln.kind == "top"]
    assert view.rows[0].status.kind == "mine"


def test_a_line_through_a_row_says_how_many_of_its_files_are_above_it():
    """A-12: the line falls inside a piece when the 20th file is one of its middle episodes; its tip and its `split`
    say the row's first k files are the ones above it."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 15), {}), ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 24), {})])
    view = vr.build(items, WORKS, {"mine_line": 20})
    top = [ln for ln in view.lines if ln.kind == "top"][0]
    assert top.after == 1 and top.split == 5
    assert "its first 5 of 24" in top.tip


def test_an_untyped_work_takes_the_stores_guess():
    """A-3: L3.1 leaves `media_type` empty until someone sets it; the window guesses as the store does (text → *Open*,
    an EPUB → a book, *Read*), never "video" for everything."""
    w = work(6, "旅路のノート", media=None)
    items = items_of([("now", 6, 6, ["旅路のノート 01 雨の街角.txt", "旅路のノート 02 帰り道.txt"],
                       {0: {"source_type": "text"}, 1: {"source_type": "text"}})])
    row = vr.build(items, WORKS, {}).rows[0]
    assert row.media == "text" and row.verb == "Open" and row.media_word == "file"
    assert vr.media_type_guess({"epub": 3}) == "book" and vr.media_type_guess({"subtitle": 2}, anilist_id=7) == "anime"
    assert w["media_type"] is None


def test_a_channels_row_is_titled_by_its_work_not_its_channel_id():
    """A-2: L3.1 keeps the channel's id in `youtube_channel`; the row reads the work's title."""
    work(7, "Kotoba Lab", media="youtube", channel="UC4R8DWoMoI7CAwX8_LjQHig")
    names = ["【解説】言葉の由来を調べてみたら面白かった [a1b2c3].srt", "町の小さな図書館を紹介します [d4e5f6].srt"]
    items = items_of([("now", 7, 7, names, {k: {"source_type": "youtube"} for k in range(2)}),
                      ("now", 7, 8, ["雨の日の散歩で見つけた小さな発見 [0a1b2c].srt"], {0: {"source_type": "youtube"}})])
    view = vr.build(items, WORKS, {})
    assert view.rows[0].title == "Kotoba Lab" and view.rows[1].line == "Kotoba Lab"
    assert not view.rows[0].episodes[0].can_play and "online" in view.rows[0].play_tip.lower()


def test_mining_outranks_no_video():
    """A-10, the mock's order (stHTML): an episode being mined shows *Mining* even if its video is gone meanwhile."""
    one = type("E", (), dict(label="Ep 1", cards=0, mined=False, missing=True, removed=False, in_top=True,
                             mining=True))()
    assert vr.status_of([one], "video", 20)[0].kind == "mining"


def test_needs_you_is_one_card_per_show_even_split_in_parts():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {1: {"availability": "missing"}}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("now", 1, 3, eps("星降る街の小さな工房", 5, 8), {0: {"availability": "missing"}})])
    view = vr.build(items, WORKS, {"mine_line": 20})
    assert len(view.needs) == 1 and [e[0] for e in view.needs[0].episodes] == ["Ep 2", "Ep 5"]


def test_the_modes_bar_outranks_loading():
    """A-6: a library that can't be used says so even before any rows were read."""
    assert vr.build({}, WORKS, {}, mode="read-only", reason="busy", loading=True).state == "read-only"
    assert vr.build({}, WORKS, {}, mode="json", reason="no store", loading=True).state == "getting-ready"


def test_a_row_cache_gives_back_the_same_rows_until_their_piece_changes():
    """The reader rebuilds the view on every change; an unchanged piece must come back as the same object (the window
    repaints nothing for it), a changed one rebuilt — a watched mark on one show rebuilds one row."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {}), ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("now", 3, 3, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 4)], {})])
    cache = vr.RowCache()
    first = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    again = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    assert all(a is b for a, b in zip(first.rows, again.rows))
    items[5] = dict(items[5], watched=1)                  # the second show's first episode watched (a new feed row)
    third = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    assert third.rows[0] is first.rows[0] and third.rows[2] is first.rows[2]
    assert third.rows[1] is not first.rows[1] and third.rows[1].n_watched == 1
    assert vr.build(items, WORKS, {}, numbers=(2, {}), cache=cache).rows[0] is not first.rows[0]   # new numbers


def test_a_receipt_without_cards_shows_nothing_from_anki():
    """Sonic (2026-10-07): what the window shows from a learner's Anki card is offered only while the card is there.
    `mined_at` outlives a deleted card, so on its own it is no ✓, no mined chip and no 'the cards keep their pictures
    and audio'."""
    receipt = {"mined_at": "2026-10-01T00:00:00Z"}
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3),
                       {0: receipt, 1: dict(receipt, availability="missing"), 2: receipt})])
    row = vr.build(items, WORKS, {}, cards={}).rows[0]
    assert all(e.status.kind != "in_anki" for e in row.episodes)
    assert row.status.kind != "in_anki"
    gone = row.episodes[1]
    assert gone.missing and not gone.removed and "removed" not in gone.play_tip
    assert row.mark is None or "deleted after mining" not in row.mark.tip
    assert not any(chip.mined for chip in row.chips)
    # the same three files with their cards are in Anki: the card is what counts, not the receipt
    row = vr.build(items, WORKS, {}, cards={1: 5, 2: 7, 3: 4}).rows[0]
    assert row.status.kind == "in_anki" and row.episodes[1].removed


def test_a_file_whose_cards_were_deleted_is_not_waiting_and_never_in_needs_you():
    """Sonic (2026-10-07, the shelf): a card the learner deletes is never made again unless they ask. A file mined
    whose cards are gone is therefore not *Waiting* (nothing will mine it), says so plainly in words true whatever
    removed them (no Anki mark), and never asks for its missing video — not in Needs you, not by a mark, not in ▶'s
    tip; the file beside it with no receipt still waits, and k/n counts only what can still be in Anki."""
    receipt = {"mined_at": "2026-10-01T00:00:00Z"}
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3),
                       {0: receipt, 1: dict(receipt, availability="missing")})])
    view = vr.build(items, WORKS, {}, cards={})
    row = view.rows[0]
    assert [e.status.kind for e in row.episodes] == ["deleted", "deleted", "waiting"]
    assert row.episodes[0].status.label == "No cards in Anki" and row.episodes[0].status.tone == "faint"
    assert row.status.kind == "waiting"                        # the third file still mines by itself
    assert not view.needs                                      # the missing one waits on nothing
    assert row.mark is None and row.episodes[1].mark is None
    assert "Needs you" not in row.episodes[1].play_tip
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {0: receipt, 1: receipt, 2: receipt})])
    row = vr.build(items, WORKS, {}, cards={}).rows[0]
    assert row.status.kind == "deleted" and row.status.label == "No cards in Anki · 3"
    row = vr.build(items, WORKS, {}, cards={2: 4}).rows[0]     # one file's cards still there: in Anki, by its cards
    assert row.status.kind == "in_anki" and row.status.label == "4"
    # asked to mine again: it is being mined (mining outranks the deletion), and an ask after the receipt undoes it
    row = vr.build(items, WORKS, {}, cards={}, mining=[1]).rows[0]
    assert row.episodes[0].status.kind == "mining" and row.status.kind == "mining"
    asked = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2),
                       {0: dict(receipt, mine_asked="2026-10-05T00:00:00Z"), 1: receipt})])
    row = vr.build(asked, WORKS, {}, cards={}).rows[0]
    assert row.episodes[0].status.kind == "waiting" and row.episodes[1].status.kind == "deleted"
    # k/n leaves the deleted files out: one in Anki, one deleted, one ready in the top → 1/2 · Waiting
    mixed = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {0: receipt, 1: receipt})])
    row = vr.build(mixed, WORKS, {}, cards={1: 3}).rows[0]
    assert row.status.kind == "waiting" and row.status.label == "1/2 · Waiting"


def test_an_untyped_titles_pieces_take_the_type_of_all_its_files():
    """L3.1's rule (review IK-24): a title nobody typed is guessed over ALL its files, not one piece's. A piece of one
    text file beside a piece of three EPUBs is read as a book, so its row's media is "book", not "text"."""
    work(8, "潮風の旅日記", media=None)
    items = items_of([("now", 8, 10, ["潮風の旅日記 01 港.txt"], {0: {"source_type": "text"}}),
                      ("now", 8, 11, ["潮風の旅日記 上.epub", "潮風の旅日記 中.epub", "潮風の旅日記 下.epub"],
                       {k: {"source_type": "epub"} for k in range(3)})])
    view = vr.build(items, WORKS, {})
    piece_a = [r for r in view.rows if r.piece_id == 10]
    assert len(piece_a) == 1 and piece_a[0].media == "book"


def test_a_cached_row_follows_its_untyped_titles_guess_when_another_piece_changes_it():
    """A title nobody typed is guessed from all its files (L3.1's rule), so a new file in another piece of the same
    title can move the type of a piece the cache would otherwise hand back unchanged: piece A's own items and work are
    the same objects in both builds, yet its row must say *Book* once B's four EPUBs make the title one (the reviews'
    2026-10-08 finding: a cached row kept the old type). Both builds share one `cards` dict, so nothing global moves and
    the cache's fast path is the one that must notice the new guess."""
    work(8, "月明かりの航路", media=None)
    items = items_of([("now", 8, 1, [f"月明かりの航路 0{k} 夜の港.srt" for k in range(1, 3)], {}),
                      ("now", 8, 2, ["月明かりの航路 03 霧の海峡.srt"], {})])
    cache = vr.RowCache()
    # one non-empty dict for both builds (`build` swaps an empty `{}` for a new one; `same_global` needs the same), and
    # the mine line at 0 keeps the set above it empty in both builds (the new files would otherwise change it)
    shared_cards, no_line = {99: 0}, {"mine_line": 0}
    first = vr.build(items, WORKS, no_line, numbers=(1, {}), cards=shared_cards, cache=cache)
    assert first.rows[0].media != "book"                  # two subtitles and one more: the title reads as video
    for k in range(4):                                    # piece B gains four EPUBs: the title's guess becomes a book
        items[4 + k] = dict(items[3], id=4 + k, source_type="epub", rel_path=f"HighPriority/月明かりの航路 04-{k} 章.epub",
                            title=f"月明かりの航路 04-{k} 章.epub", ord=4096.0 + 1024.0 * k)
    second = vr.build(items, WORKS, no_line, numbers=(1, {}), cards=shared_cards, cache=cache)
    assert cache.same_global                              # the fast path is the one under test, not a rebuild by accident
    assert second.rows[0].media == "book"                 # A's row is rebuilt, not the cached one with the old type


def test_an_untyped_titles_file_types_are_counted_once_and_kept_between_builds(monkeypatch):
    """Review C-6: the title's guess counts each file's type once, not on every window refresh. A build over the same
    rows counts none again (the reader's RowCache keeps the counts), and replacing one row's dict counts only that row,
    so a refresh stays cheap on a library of thousands of files while the guess stays right (both pieces are books)."""
    real_kind = vr._kind
    calls = []

    def spy(item):
        calls.append(item)
        return real_kind(item)

    monkeypatch.setattr(vr, "_kind", spy)
    work(9, "潮風の旅日記", media=None)
    items = items_of([("now", 9, 10, ["潮風の旅日記 上.epub", "潮風の旅日記 中.epub"],
                       {0: {"source_type": "epub"}, 1: {"source_type": "epub"}}),
                      ("now", 9, 11, ["潮風の旅日記 下.epub"], {0: {"source_type": "epub"}})])
    cache = vr.RowCache()
    first = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    assert len(calls) == 3                                # the first build counts each of the three files once
    assert {r.media for r in first.rows} == {"book"}
    calls.clear()
    second = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    assert calls == []                                    # nothing changed: no file is counted again
    assert {r.media for r in second.rows} == {"book"}
    items[2] = dict(items[2])                             # the feed replaces one row's dict (same content)
    calls.clear()
    third = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    assert len(calls) == 1 and calls[0] is items[2]       # only the replaced row is counted again
    assert {r.media for r in third.rows} == {"book"}


def test_an_unstamped_file_is_counted_by_its_extension_as_the_store_does():
    """IK-29: a file nobody stamped (source_type None) is counted by its extension, as the store counts it. A .srt under
    a title with an AniList id reads as anime, a .txt reads as text (Open), and a piece whose work is not on the list
    reads its own files the same way. Without this an unstamped file counts as no kind at all and shows as video."""
    work(9, "月明かりの航路の続き", media=None, anilist=77)
    work(10, "港町の朝市メモ", media=None)
    items = items_of([("now", 9, 9, ["月明かりの航路の続き 01 夜明け.srt", "月明かりの航路の続き 02 潮騒.srt"],
                       {k: {"source_type": None} for k in range(2)}),
                      ("now", 10, 10, ["港町の朝市メモ 01 魚河岸.txt"], {0: {"source_type": None}}),
                      ("now", 99, 11, ["雪解けの便り 01 春風.txt"], {0: {"source_type": None}})])
    rows = {r.piece_id: r for r in vr.build(items, WORKS, {}).rows}
    assert rows[9].media == "anime"                       # a title nobody typed: its .srt files and its id
    assert rows[10].media == "text" and rows[10].verb == "Open"
    assert rows[11].media == "text"                       # no work on the list: this piece's own .txt file


def test_guess_counts_moved_only_by_the_changed_ids_equal_a_full_count():
    """Speed round 5: the reader names the items that changed, and the untyped title's guess counts move by those alone
    instead of walking every item on each build. A file renamed .srt → .epub, one removed and one added must leave the
    kept counts exactly as a full count gives them, or the title's type drifts from what the store would guess."""
    work(12, "夜明けの写本", media=None)
    items = items_of([("now", 12, 1, ["夜明けの写本 01 朝霧.srt", "夜明けの写本 02 潮騒.srt"],
                       {k: {"source_type": "subtitle"} for k in range(2)}),
                      ("now", 12, 2, ["夜明けの写本 03 灯台.txt"], {0: {"source_type": "text"}})])
    cache = vr.RowCache()

    def untyped_media(view):
        return [(r.piece_id, r.media) for r in view.rows]

    def check(changed):
        view = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, changed=changed)
        assert cache.guess_counts == vr._Guesses(items, None)._count()
        assert untyped_media(view) == untyped_media(vr.build(items, WORKS, {}))
        return view

    check(None)
    assert cache.guess_counts[12] == {"subtitle": 2, "text": 1}
    items[1] = dict(items[1], rel_path="HighPriority/夜明けの写本 02 潮騒.epub",
                    title="夜明けの写本 02 潮騒.epub", source_type="epub")       # a new dict: .srt → .epub
    check([1])
    assert cache.guess_counts[12] == {"subtitle": 1, "epub": 1, "text": 1}
    del items[3]                                                              # the text file leaves the feed
    check([3])
    assert cache.guess_counts[12] == {"subtitle": 1, "epub": 1}
    items[4] = dict(items[2], id=4, rel_path="HighPriority/夜明けの写本 04 霧.srt",
                    title="夜明けの写本 04 霧.srt")                             # a new subtitle file arrives
    check([4])
    assert cache.guess_counts[12] == {"subtitle": 2, "epub": 1}


def test_ids_changed_in_a_build_that_counts_nothing_are_counted_at_the_next_build_that_does():
    """Speed round 5: a build with no untyped title on the list never counts the guesses, so an id the reader changed
    in that build must wait, kept beside the next change, until a build does count. Had the earlier change been dropped,
    a learner's untyped show would keep its old type after a file in it was renamed .srt → .epub, and the list would
    say the wrong thing about what they are watching."""
    work(13, "霧の燈台守", media=None)
    items = items_of([("now", 13, 1, ["霧の燈台守 01 朝霧.srt", "霧の燈台守 02 潮騒.srt"],
                       {k: {"source_type": "subtitle"} for k in range(2)}),
                      ("now", 13, 2, ["霧の燈台守 03 灯台.txt"], {0: {"source_type": "text"}})])
    cache = vr.RowCache()
    vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, changed=None)
    assert cache.guess_counts[13] == {"subtitle": 2, "text": 1}

    items[1] = dict(items[1], rel_path="HighPriority/霧の燈台守 01 朝霧.epub",
                    title="霧の燈台守 01 朝霧.epub", source_type="epub")       # item 1: .srt → .epub
    work(13, "霧の燈台守", media="anime")                                     # typed: no untyped title this build
    vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, changed=[1])
    assert cache.guess_pending == {1}                                         # not counted, so still owed
    assert cache.guess_counts[13] == {"subtitle": 2, "text": 1}

    work(13, "霧の燈台守", media=None)                                        # untyped again
    items[3] = dict(items[3], rel_path="HighPriority/霧の燈台守 03 灯台.srt",
                    title="霧の燈台守 03 灯台.srt", source_type="subtitle")     # item 3: .txt → .srt
    view = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, changed=[3])
    assert cache.guess_counts == vr._Guesses(items, None)._count()            # item 1's change is in it too
    assert cache.guess_counts[13] == {"epub": 1, "subtitle": 2}
    assert [(r.piece_id, r.media) for r in view.rows] == \
        [(r.piece_id, r.media) for r in vr.build(items, WORKS, {}).rows]


def test_a_goal_or_finished_part_that_changed_is_built_again_and_never_given_back_stale():
    """Sonic's rule (S19, review IK-36): a Goal or Finished section nothing changed in is given back as it was, but one
    that changed is built again. A finished file moved to another month, a Goal title's work renamed, and a Finished
    row's work renamed must each show at once, equal to a build without the cache, never the old object — or the
    window keeps a title or a month the library no longer has."""
    cards = {1: 0}                                   # one non-empty dict on every build: the cache's global state holds
    items = items_of([("graduated", 1, 1, eps("星降る街の小さな工房", 1, 2), {}),
                      ("goal", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {}),
                      ("graduated", 3, 3, ["白銀の書庫番 01 章.txt"], {0: {"graduated_at": "2026-09-21T12:00:00Z"}})])
    tiers = vr._by_tier(items)
    cache = vr.RowCache()

    def view(changed=(), changed_works=()):
        return vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache, tiers=tiers,
                        changed=list(changed), changed_works=list(changed_works))

    def without_cache():
        return vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, tiers=tiers)

    first = view()
    warm = view()                                    # the first build after a cache is new never keeps a section
    assert view().finished is warm.finished          # nothing changed: the section is given back as it was
    assert [m.label for m in first.finished] == ["September 2026", "Earlier"]

    # (a) a Finished file changed in place (a new dict, another month), swapped into its place in the same tier list
    old = items[5]
    new = dict(old, graduated_at="2026-08-02T12:00:00Z")
    items[5] = new
    tiers["graduated"][[r is old for r in tiers["graduated"]].index(True)] = new
    moved = view(changed=[5])
    assert moved.finished is not first.finished
    assert [(m.label, [r.date for r in m.rows]) for m in moved.finished] == \
        [(m.label, [r.date for r in m.rows]) for m in without_cache().finished]
    assert [m.label for m in moved.finished] == ["August 2026", "Earlier"]

    # (b) a Goal title's work renamed: the strip's covers show the new title
    assert first.goal.covers == ("雲の上の郵便屋さん",)
    work(2, "雲の上の郵便屋さんと空の手紙")
    renamed_goal = view(changed_works=[2])
    assert renamed_goal.goal.covers == ("雲の上の郵便屋さんと空の手紙",)
    assert renamed_goal.goal == without_cache().goal

    # (c) the work of a Finished row renamed: its row carries the new title
    work(3, "白銀の書庫番 改訂版", media="lightnovel")
    renamed_row = view(changed_works=[3])
    rows = [r for m in renamed_row.finished for r in m.rows if r.work_id == 3]
    assert [r.title for r in rows] == ["白銀の書庫番 改訂版"]
    assert [(m.label, [r.title for r in m.rows]) for m in renamed_row.finished] == \
        [(m.label, [r.title for r in m.rows]) for m in without_cache().finished]


def test_goal_and_finished_are_given_back_unbuilt_when_only_a_current_file_changed():
    """Speed (review IK-36): at 20,000 files the Goal strip and the Finished months were walked on every build, though a
    learner's usual change is one episode they are watching. A build told that only a Current file changed must hand back
    last build's Goal and Finished objects; they must still equal a build made with no cache, or the strip and the months
    would show a count that is out of date."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}),
                      ("goal", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("graduated", 3, 3, ["白銀の書庫番 01 章.txt"],
                       {0: {"graduated_at": "2026-09-21T00:00:00Z"}})])
    tiers = vr._by_tier(items)
    cards = {2: 3}      # one shared, non-empty dict: a build keeps Finished only while it is the same object
    cache = vr.RowCache()
    view1 = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache, tiers=tiers,
                     changed=None, changed_works=None)
    # the first build after a new cache stores Finished unkeepable (no same-global key yet), so the reference is the
    # second build, the one that stores the key the next build can give back
    view1 = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache, tiers=tiers,
                     changed=[], changed_works=set())
    items[1] = dict(items[1], watched=1)                  # a new dict: the first Current episode is now watched
    k = next(i for i, r in enumerate(tiers["now"]) if r["id"] == 1)
    tiers["now"][k] = items[1]                            # the same tier and place, in the reader's list too
    view2 = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache, tiers=tiers,
                     changed=[1], changed_works=set())
    assert view2.goal is view1.goal
    assert view2.finished is view1.finished
    assert view2.counts == view1.counts
    fresh = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards)
    assert view2.goal == fresh.goal and view2.finished == fresh.finished


# --- W3.1a: the string planned here (B2), the numbers' partial rebuild (on a drop) ---------------------------------- #
def _three_shows():
    return items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 30), {k: {"watched": 1} for k in range(14)}),
                     ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                     ("soon", 3, 3, eps("白銀の書庫番", 1, 5), {}),
                     ("graduated", 1, 9, eps("星降る街の小さな工房", 31, 32), {})])


def test_each_current_rows_string_is_planned_when_the_row_is_built_not_by_the_window():
    """B2: the plan and its need ride on the row, worked out on the reader's thread; Finished's rows carry none."""
    view = vr.build(_three_shows(), WORKS, {"mine_line": 20})
    from app.services import stone_plan as sp
    for r in view.rows:
        plan = sp.plan_of(r)
        assert r.string == (plan, max(sp.tightest(plan), sp.ahead(plan)))
    assert all(r.string is None for m in view.finished for r in m.rows)


def test_the_view_names_the_most_needing_string_per_kind_of_anki_count_below_up_next():
    """The window's one title width reads these few numbers (its font adds each kind's width), never every row; Up
    Next (the first row) isn't one of Current's one-line rows."""
    view = vr.build(_three_shows(), WORKS, {"mine_line": 20})
    below = view.rows[1:]
    assert set(view.worst) == {vr.stat_kind(r.status) for r in below}
    for kind, (need, plan) in view.worst.items():
        same = [r for r in below if vr.stat_kind(r.status) == kind]
        assert need == max(r.string[1] for r in same) and plan in [r.string[0] for r in same]
    assert vr.stat_kind(vr.Status("in_anki", "12", "", "ok")) == ("in_anki", "12")
    assert vr.stat_kind(vr.Status("mining", "Mining…", "", "accent")) == "mining"
    assert vr.stat_kind(vr.Status("waiting", "Waiting", "", "dim")) is None and vr.stat_kind(None) is None
    assert vr.worst_needs([]) == {}


def test_the_views_answer_stays_one_object_while_it_is_the_same():
    """A refresh that changes no row's need hands the window the very same answer: it works nothing out again."""
    items = _three_shows()
    cache = vr.RowCache()
    first = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache)
    again = vr.build(items, WORKS, {}, numbers=(2, {}), cache=cache)
    assert again.worst is first.worst
    items[32] = dict(items[32], watched=1)                     # a file of a row below Up Next watched: its need moves
    third = vr.build(items, WORKS, {}, numbers=(2, {}), cache=cache, changed=[32])
    assert third.worst == vr.worst_needs(third.rows[1:])


def test_a_numbers_version_that_says_what_it_changed_rebuilds_only_those_rows():
    """A drop moves *N new* on a few rows; the rest stay the same objects (nothing repainted for them)."""
    items = _three_shows()
    cache = vr.RowCache()
    numbers = {i: (5, 10, 1) for i in items}
    first = vr.build(items, WORKS, {}, numbers=(1, numbers), cache=cache)
    moved = {**numbers, 34: (5, 10, 7)}                  # one file of the third show
    second = vr.build(items, WORKS, {}, numbers=(2, moved), cache=cache, numbers_changed={34})
    assert second.rows[0] is first.rows[0] and second.rows[1] is first.rows[1]
    assert second.rows[2] is not first.rows[2] and second.rows[2].n_new == first.rows[2].n_new + 6
    third = vr.build(items, WORKS, {}, numbers=(3, moved), cache=cache, numbers_changed=None)
    assert all(a is not b for a, b in zip(third.rows, second.rows))        # unknown: every row again
    same = vr.build(items, WORKS, {}, numbers=(3, moved), cache=cache, numbers_changed=set())
    assert all(a is b for a, b in zip(same.rows, third.rows))


def test_the_first_screens_rows_are_planned_again_as_they_are_read():
    view = vr.build(_three_shows(), WORKS, {"mine_line": 20})
    import json
    data = json.loads(json.dumps(vr.to_cache(view)))
    assert all(r[-1] is None for r in data["rows"])           # the plans aren't written: planned again when read
    back = vr.from_cache(data)
    assert back.rows == view.rows[:vr.CACHE_ROWS] and back.worst == view.worst


def test_hatos_mix_is_planned_as_the_mix_not_by_its_videos_kind():
    """(V06) hato's drop folder is one mix: its string is sapphire whatever its videos are, as `plan_of` reads it."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {}),
                      ("now", 4, 4, ["料理の基本 [abcdefghijk].srt", "包丁の使い方 [bcdefghijkl].srt"],
                       {k: {"rel_path": f"HighPriority/Hato/v{k}.srt", "source_type": "youtube"} for k in (0, 1)})])
    view = vr.build(items, WORKS, {"mine_line": 20})
    from app.services import stone_plan as sp
    mix = view.rows[1]
    assert mix.source == "hato" and mix.string[0] == sp.plan_of(mix)
    assert mix.string[0].gem == sp.gem_of(mix.media, mix=True) != sp.gem_of(mix.media)


# --- W3.2 S1: New arrivals in the view (the tray's rows; RUNBOOK §1 *The tray*, *The arrival's number*) ------------- #
def _at(stamp):
    return {"added_at": stamp}


def _hato(names, **more):
    return {k: dict({"rel_path": f"{vr.HATO_FOLDER}{n}"}, **more) for k, n in enumerate(names)}


def test_arrivals_are_newest_first_by_when_they_came_and_equal_times_keep_the_stores_order():
    """C-scope §3: what came last is what the learner looks for first. A piece is as new as its newest file (Ep 1–3 came
    on the 10th, Ep 4 on the 14th: the show is the 14th's); two pieces that came at the same moment stay in the store's
    order, or the tray would shuffle them on every refresh."""
    a = eps("星降る街の小さな工房", 1, 4)
    items = items_of([("arrivals", 1, 1, a, {0: _at("2026-10-10T09:00:00Z"), 1: _at("2026-10-10T09:00:00Z"),
                                              2: _at("2026-10-10T09:00:00Z"), 3: _at("2026-10-14T21:00:00Z")}),
                      ("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {k: _at("2026-10-12T08:00:00Z") for k in (0, 1)}),
                      ("arrivals", 3, 3, ["白銀の書庫番 01 章.txt"], {0: _at("2026-10-12T08:00:00Z")}),
                      ("arrivals", 4, 4, ["【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"],
                       {0: dict(_at("2026-10-15T07:00:00Z"), source_type="youtube")})])
    view = vr.build(items, WORKS, {})
    assert [a.title for a in view.arrivals] == ["【検証】一週間お弁当を作り続けてみた", "星降る街の小さな工房",
                                                "雲の上の郵便屋さん", "白銀の書庫番"]
    assert view.arrivals[1].added_at == "2026-10-14T21:00:00Z"
    assert view.arrivals[1].item_ids == (1, 2, 3, 4)                  # the whole piece: the drag's and the writer's ids
    assert view.arrivals[1].rel_paths[0] == "HighPriority/星降る街の小さな工房 - 01.srt"   # what the estimate is asked by
    # the same two pieces the other way round in the store: the tie follows the store, not the title or the id
    swapped = items_of([("arrivals", 3, 3, ["白銀の書庫番 01 章.txt"], {0: _at("2026-10-12T08:00:00Z")}),
                        ("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {k: _at("2026-10-12T08:00:00Z") for k in (0, 1)})])
    assert [a.title for a in vr.build(swapped, WORKS, {}).arrivals] == ["白銀の書庫番", "雲の上の郵便屋さん"]


def test_a_show_split_in_two_pieces_arrives_as_two_rows_each_with_its_own_episodes():
    """A row is a piece (store digest §2.3) in the tray too: a show whose second half came apart is two rows, each with
    its own *Ep x–y* and its own ids, so placing one never moves the other."""
    t = "星降る街の小さな工房"
    items = items_of([("arrivals", 1, 10, eps(t, 1, 4), {k: _at("2026-10-11T00:00:00Z") for k in range(4)}),
                      ("arrivals", 2, 11, eps("雲の上の郵便屋さん", 1, 2), {k: _at("2026-10-12T00:00:00Z") for k in (0, 1)}),
                      ("arrivals", 1, 12, eps(t, 5, 8), {k: _at("2026-10-13T00:00:00Z") for k in range(4)})])
    view = vr.build(items, WORKS, {})
    split = [a for a in view.arrivals if a.work_id == 1]
    assert [a.line for a in split] == ["Ep 5–8", "Ep 1–4"]
    # (A4A-5: each run keyed by its piece and its own smallest file id — a key that never moves to another run)
    assert [a.key for a in split] == [f"p12.i{min(split[0].item_ids)}", f"p10.i{min(split[1].item_ids)}"]
    assert set(split[0].item_ids).isdisjoint(split[1].item_ids)
    assert view.counts.arrivals == 3 and view.badges["arrivals"] == 10    # the badge stays the files (R4b-12)


def test_new_comes_first_and_already_watched_second_each_newest_first():
    """RUNBOOK §5 lean 3: an arrival whose every file is watched (YouTube's history, a hato record's flag) goes under
    *Already watched*, whose head offers *All to Finished*; one partly watched is still new to the learner."""
    both = {0: dict(_at("2026-10-15T00:00:00Z"), watched=1), 1: dict(_at("2026-10-15T00:00:00Z"), watched=1)}
    items = items_of([("arrivals", 1, 1, eps("星降る街の小さな工房", 1, 2), both),
                      ("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {0: dict(_at("2026-10-12T00:00:00Z"), watched=1),
                                                                   1: _at("2026-10-12T00:00:00Z")}),
                      ("arrivals", 3, 3, ["白銀の書庫番 01 章.txt"], {0: dict(_at("2026-10-14T00:00:00Z"), watched=1)}),
                      ("arrivals", 4, 4, ["町の小さな図書館を紹介します [d4e5f6].srt"],
                       {0: dict(_at("2026-10-13T00:00:00Z"), source_type="youtube")})])
    view = vr.build(items, WORKS, {})
    assert [(a.title, a.group) for a in view.arrivals] == [
        ("町の小さな図書館を紹介します", "new"), ("雲の上の郵便屋さん", "new"),
        ("星降る街の小さな工房", "watched"), ("白銀の書庫番", "watched")]
    assert [(g.kind, g.label, [a.title for a in g.rows]) for g in view.arrival_groups] == [
        ("new", "New", ["町の小さな図書館を紹介します", "雲の上の郵便屋さん"]),
        ("watched", "Already watched", ["星降る街の小さな工房", "白銀の書庫番"])]
    assert view.arrivals[2].watched and not view.arrivals[1].watched
    only_new = vr.build(items_of([("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})]), WORKS, {})
    assert [g.kind for g in only_new.arrival_groups] == ["new"]          # an empty group isn't shown
    only_watched = vr.build(items_of([("arrivals", 1, 1, eps("星降る街の小さな工房", 1, 2), both)]), WORKS, {})
    assert [g.kind for g in only_watched.arrival_groups] == ["watched"]


def test_a_hato_show_wears_hatos_chip_and_says_its_episodes_cards_and_missing_videos():
    """The tray's one line: the source chip, *Ep x–y*, *N in Anki* (ok) and *N no video* (amber). hato's drop folder
    names it hato even with an AniList id (hato brought it); an AniList show outside it is AniList's; the rest, disk."""
    work(5, "海辺の図書室", anilist=202)
    names = eps("海辺の図書室", 1, 6)
    extra = _hato(names)
    extra[1]["availability"] = "missing"
    extra[4]["availability"] = "missing"
    items = items_of([("arrivals", 5, 5, names, extra)])
    a = vr.build(items, WORKS, {}, cards={1: 4, 3: 7}).arrivals[0]
    assert (a.source, a.chip, a.title, a.line, a.media) == ("hato", "hato", "海辺の図書室", "Ep 1–6", "anime")
    assert (a.cards, a.no_media) == (11, 2)
    assert a.parts == (("Ep 1–6", "dim"), ("11 in Anki", "ok"), ("2 files gone", "warn"))
    assert a.cover_title == "海辺の図書室" and a.channel is None
    off_hato = vr.build(items_of([("arrivals", 5, 5, eps("海辺の図書室", 7, 8), {})]), WORKS, {}).arrivals[0]
    assert (off_hato.source, off_hato.chip) == ("anilist", "AniList")
    on_disk = vr.build(items_of([("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})]), WORKS, {}).arrivals[0]
    assert (on_disk.source, on_disk.chip, on_disk.parts) == ("disk", "disk", (("Ep 1–2", "dim"),))


def test_a_youtube_video_arrives_titled_by_itself_with_its_channel_and_a_channels_videos_by_the_channel():
    """The mock's video row: its own title, the channel on the line (per-channel rules read it); several videos of one
    channel arriving together read as the channel with *N videos*, as Current's rows do."""
    one = items_of([("arrivals", 4, 4, ["【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"], {0: {"source_type": "youtube"}})])
    a = vr.build(one, WORKS, {}).arrivals[0]
    assert (a.title, a.line, a.channel, a.source, a.chip, a.media) == (
        "【検証】一週間お弁当を作り続けてみた", "Tsubasa no Kitchen", "Tsubasa no Kitchen", "youtube", "YouTube", "youtube")
    assert a.media_word == "video" and a.cover_title == "Tsubasa no Kitchen"
    two = items_of([("arrivals", 4, 4, ["祖母に教わった味噌汁の作り方 [0a1b2c].srt", "手作りパンを毎朝焼いてみた [9f8e7d].srt"],
                     {k: {"source_type": "youtube"} for k in (0, 1)})])
    b = vr.build(two, WORKS, {}).arrivals[0]
    assert (b.title, b.line, b.channel) == ("Tsubasa no Kitchen", "2 videos", "Tsubasa no Kitchen")


def test_nothing_arrived_means_no_rows_and_no_group():
    """The inset is absent when nothing has arrived (A2 #22): the view gives it nothing to draw, never an empty group."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {})])
    for view in (vr.build(items, WORKS, {}), vr.build({}, WORKS, {})):
        assert view.arrivals == () and view.arrival_groups == ()
        assert view.badges["arrivals"] == 0 and view.counts.arrivals == 0


def test_the_number_per_episode_waits_for_every_files_estimate_then_is_their_mean_rounded():
    """*N new / ep* (E2.2, IK-5): each file's *N new at the top* summed over the show and divided by its files. A show
    with one answer still out shows a dash (None), never a number from part of it that would read too low or high."""
    items = items_of([("arrivals", 1, 1, eps("星降る街の小さな工房", 1, 3), {})])
    assert vr.build(items, WORKS, {}).arrivals[0].per_ep is None                      # nothing asked yet
    partial = vr.build(items, WORKS, {}, estimates={1: 30, 2: 25}).arrivals[0]
    assert partial.per_ep is None and "estimate" in partial.tip and "not counted yet" in partial.accessible
    full = vr.build(items, WORKS, {}, estimates={1: 30, 2: 25, 3: 20, 99: 400}).arrivals[0]
    assert full.per_ep == 25 and full.tip.startswith("About 25 new words an episode")
    assert "3 episodes" in full.tip and "an estimate until analysed" in full.tip
    assert full.accessible == "星降る街の小さな工房 · Ep 1–3 · 25 new / ep"
    assert vr.per_episode((1, 2), {1: 3, 2: 4}) == 4                  # 3.5 rounds up, as a learner reads it
    assert vr.per_episode((1, 2), {1: 0, 2: 0}) == 0                  # nothing new is a number, not a dash
    assert vr.per_episode((), {}) is None and vr.per_episode((1,), None) is None


def test_an_unchanged_arrivals_tier_gives_back_the_same_objects_and_one_changed_arrival_only_its_own():
    """S19: the reader rebuilds on every change; an unchanged tray must come back as the very same objects (the window
    repaints nothing), and when one arrival changes — a file watched, its estimate in — only that row is new, the others
    are last build's, so the tray repaints the one row that moved."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}),
                      ("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {k: _at("2026-10-14T00:00:00Z") for k in (0, 1)}),
                      ("arrivals", 3, 3, ["白銀の書庫番 01 章.txt"], {0: _at("2026-10-13T00:00:00Z")})])
    tiers = vr._by_tier(items)
    cards = {1: 0}
    cache = vr.RowCache()

    def view(changed=None, estimates=None):
        return vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache, tiers=tiers, changed=changed,
                        changed_works=None if changed is None else set(), estimates=estimates)
    first = view()
    again = view()                                    # no ids named: each row checked, every one the same
    assert again.arrivals is first.arrivals and again.arrival_groups is first.arrival_groups
    fast = view(changed=[])                           # the reader says nothing changed: given back whole (`_kept`)
    assert fast.arrivals is first.arrivals
    show, book = first.arrivals
    items[3] = dict(items[3], watched=1)              # one episode of the first arrival watched (a new feed row)
    tiers["arrivals"][0] = items[3]
    moved = view(changed=[3])
    assert moved.arrivals[0] is not show and moved.arrivals[1] is book
    assert moved.arrivals is not first.arrivals and moved.arrivals[0].n_files == 2
    estimated = view(changed=[], estimates={5: 12})   # the book's estimate comes in: only its row is new
    assert estimated.arrivals[0] is moved.arrivals[0] and estimated.arrivals[1] is not book
    assert estimated.arrivals[1].per_ep == 12
    assert view(changed=[], estimates={5: 12}).arrivals is estimated.arrivals
    fresh = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, estimates={5: 12})
    assert estimated.arrivals == fresh.arrivals and estimated.arrival_groups == fresh.arrival_groups


def test_new_arrivals_stay_out_of_the_first_screens_cache():
    """The first frame shows no tray (it opens by hand): the cache doesn't carry it, and a cached view has none."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}), ("arrivals", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})])
    view = vr.build(items, WORKS, {})
    import json
    data = json.loads(json.dumps(vr.to_cache(view)))
    assert "arrivals" not in data
    back = vr.from_cache(data)
    assert back.arrivals == () and back.arrival_groups == () and back.badges["arrivals"] == 2


def test_chinese_arrivals_read_the_same_way():
    work(5, "雷鸣之剑与见习魔女", anilist=88)
    work(6, "小厨房频道", media="youtube", channel="小厨房频道")
    names = ["雷鸣之剑与见习魔女 第3集.srt", "雷鸣之剑与见习魔女 第4集.srt"]
    items = items_of([("arrivals", 5, 5, names, _hato(names, added_at="2026-10-11T00:00:00Z")),
                      ("arrivals", 6, 6, ["【实测】连续一周做便当 [a3f9c1].srt"],
                       {0: dict(_at("2026-10-12T00:00:00Z"), source_type="youtube")})])
    view = vr.build(items, WORKS, {}, language="zh", estimates={1: 40, 2: 31, 3: 9})
    assert [(a.title, a.line, a.chip, a.per_ep) for a in view.arrivals] == [
        ("【实测】连续一周做便当", "小厨房频道", "YouTube", 9), ("雷鸣之剑与见习魔女", "Ep 3–4", "hato", 36)]
    assert view.arrivals[0].tip.startswith("About 9 new words a video")


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_seeds_tray_holds_every_state_the_mock_draws(language):
    """The seed (W3.2 S1): a YouTube channel's video, a hato show whose files came on two days, and a show watched
    elsewhere with a file mined and one with no video — newest first, in the two groups. Only New arrivals' files
    carry their own times, so no other test's expectations move."""
    from tests.fixtures import window_seed
    seed = window_seed.build(language=language)
    items = {r["id"]: r for r in seed.items}
    works = {w["id"]: w for w in seed.works}
    seed.opener.check()
    cards = {i: len(c) for i, c in seed.opener.handle().cards_of(list(items)).items() if c}
    view = vr.build(items, works, {"mine_line": 20}, cards=cards)
    assert [(a.source, a.group) for a in view.arrivals] == [("youtube", "new"), ("hato", "new"), ("hato", "watched")]
    video, show, watched = view.arrivals
    assert video.line == video.channel and video.n_files == 1 and video.chip == "YouTube"
    assert show.line == "Ep 1–6" and show.added_at == "2026-10-14T21:00:00Z"
    assert watched.cards == 6 and watched.no_media == 1 and watched.watched
    assert video.added_at > show.added_at > watched.added_at
    assert len({r["added_at"] for r in seed.items if r["tier"] == "arrivals"}) == 4
    assert {r["added_at"] for r in seed.items if r["tier"] != "arrivals"} == {window_seed.ADDED_AT}


# --- P4.1 L2 (row 4.1.10, W-A1): Connect's feed in the view --------------------------------------------------------- #
def _feed(jobs, needs=(), running=True, language="ja"):
    """Connect's feed as the window gets it: `feed.build` over a status record holding these jobs (the runner's own
    reason lines and states), so the kinds are told as Connect tells them."""
    from app.connect import feed
    return feed.build({"running": running, "languages": {language: {"line": "Up to date", "state": "idle",
                                                                    "jobs": list(jobs), "needs": list(needs)}}},
                      language)


def _job(item, state="waiting", reason=None, kind="mine", made=0, words=0):
    return {"item": item, "job": 100 + item, "state": state, "reason": reason, "kind": kind, "made": made,
            "words": words}


def test_no_feed_builds_todays_view_byte_for_byte():
    """`connect=None` (no Connect feed in this window) leaves every row, episode and line as they are without the
    feed. (An off Feed no longer does: row 13, the next test.)"""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {2: {"availability": "missing"}}),
                      ("soon", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("graduated", 3, 3, ["白銀の書庫番 01 雨の街角.txt"], {})])
    plain = vr.build(items, WORKS, {"mine_line": 3})
    assert vr.build(items, WORKS, {"mine_line": 3}, connect=None) == plain
    assert plain.connect is None


@pytest.mark.parametrize("settings", [{}, {"connect_enabled": True, "logic": {"automation": False}}],
                         ids=["switch-off", "automation-off"])
def test_connect_off_shows_no_top_line_and_no_waiting_row(settings):
    """Row 13 (laptop fixes): with Connect off (its switch, or D29's automation: `Feed.on` False) nothing mines by
    itself, so no *Everything above this line mines itself* line and no *Waiting — it mines by itself* on a top row:
    the rows read *Mine* / *Mine rest* with no "top" in their tips. Its cards in Anki and *No video* stay as they were.
    What a wrong answer costs: every top row promising cards that never come. On (or no feed) the line stays."""
    from app.connect import feed
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {}),
                      ("soon", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("now", 3, 3, eps("白銀の書庫番", 1, 2), {0: {"availability": "missing"},
                                                             1: {"availability": "missing"}})])
    cards = {1: 5}                                       # its first episode's cards are in Anki
    plain = vr.build(items, WORKS, {"mine_line": 4}, cards=cards)
    assert [ln.kind for ln in plain.lines].count("top") == 1                       # (the baseline: a line, Waiting)
    assert any(r.status.kind == "waiting" for r in plain.rows)
    off = vr.build(items, WORKS, {"mine_line": 4}, cards=cards, connect=feed._off(settings))
    assert "top" not in [ln.kind for ln in off.lines]
    statuses = [r.status for r in off.rows] + [e.status for r in off.rows for e in r.episodes]
    assert not [s for s in statuses if s.kind == "waiting"]
    assert not [s for s in statuses if "top" in s.tip]
    assert {r.title: r.status.kind for r in off.rows} == {"星降る街の小さな工房": "mine_rest", "雲の上の郵便屋さん": "mine",
                                                          "白銀の書庫番": "no_media"}
    assert next(r for r in off.rows if r.title == "星降る街の小さな工房").status.tip == "1/4 mined"


def test_each_of_connects_kinds_is_a_stone_with_its_own_words():
    """Row 4.1.10: Connect's *No video* (its video not found) is the amber *No video* with the runner's reason; *Not
    timed* waits on *Mine anyway* in Needs you; a job waiting on Anki, on battery or its turn is *Waiting* with the
    job's own reason as its tip (C7); an ask below the line is *Waiting* (no longer *Mine*); *Mining* counts the
    cards made of the words picked. What a wrong answer would cost: a top-20 episode that reads *Waiting — it mines by
    itself* while Connect can't find its video or Anki is closed, so the learner never knows to act."""
    from app.connect import feed, runner
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 6), {}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})])
    connect = _feed([_job(1, state="mining", made=3, words=12), _job(2, reason=runner.NO_VIDEO),
                     _job(3, reason="not timed to its video"), _job(4, reason=runner.ANKI_CLOSED),
                     _job(5, reason=runner.ON_BATTERY), _job(6),
                     _job(8, kind="asked", state="queued")],
                    needs=[{"kind": "not-timed", "item": 3}])
    view = vr.build(items, WORKS, {"mine_line": 6}, connect=connect)
    st = {e.id: e.status for r in view.rows for e in r.episodes}
    assert (st[1].kind, st[1].label, st[1].tone) == ("mining", "Mining · 3/12", "accent")
    assert (st[2].kind, st[2].label, st[2].tone) == ("no_media", "No video", "warn") and runner.NO_VIDEO in st[2].tip
    assert (st[3].kind, st[3].label, st[3].tone) == ("waiting", "Not timed", "warn")
    assert "Mine anyway" in st[3].tip and "Needs you" in st[3].tip and feed.WORDS[feed.NOT_TIMED] in st[3].tip
    # M-3 A (Sonic 2026-10-22): a wait on Anki or on battery takes *Mine now*; its hover says what the press does
    assert (st[4].kind, st[4].tip) == ("waiting", vr.STRINGS["tip_ask_anki"].format(tip=runner.ANKI_CLOSED))
    assert st[4].tip.endswith("Click: it goes first once Anki answers")
    assert (st[5].kind, st[5].tip) == ("waiting", vr.STRINGS["tip_ask_battery"].format(tip=runner.ON_BATTERY))
    assert st[5].tip.endswith("Click to mine this one now, on battery")
    assert (st[6].kind, st[6].tip) == ("waiting", feed.NEXT_LOOK), "no reason yet: when Connect comes to it (T2)"
    assert (st[7].kind, st[7].label) == ("mine", "Mine"), "no job: as without Connect"
    # R47: an ask Connect has read is its own status (*Asked*, the press's mark still), its tip the reason or its words
    assert (st[8].kind, st[8].tip) == ("asked", vr.STRINGS["tip_asked"]), "an ask below the line waits, first"
    first, second = view.rows
    assert (first.status.kind, first.status.label) == ("mining", "Mining · 3/12"), "the row: its first job's"
    assert first.accessible.endswith("Mining · 3/12")
    assert (second.status.kind, second.status.tip) == ("asked", vr.STRINGS["tip_asked"])
    assert view.connect is connect


def test_a_job_on_an_item_with_its_cards_in_anki_or_no_file_keeps_its_own_status():
    """A level job (new words for an item already mined) leaves ✓ *N in Anki*; an item whose file is gone from disk
    keeps the disk's *No video* (Connect's own reason would be the same want, said less exactly)."""
    from app.connect import runner
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {1: {"availability": "missing"}})])
    connect = _feed([_job(1, reason=runner.ANKI_CLOSED, kind="level"), _job(2, reason=runner.NO_VIDEO)])
    plain = vr.build(items, WORKS, {"mine_line": 20}, cards={1: 4})
    view = vr.build(items, WORKS, {"mine_line": 20}, cards={1: 4}, connect=connect)
    assert [e.status for e in view.rows[0].episodes] == [e.status for e in plain.rows[0].episodes]
    assert view.rows[0].episodes[0].status.kind == "in_anki"


def test_a_level_job_on_an_episode_in_anki_or_one_whose_cards_were_deleted_never_takes_the_rows_status():
    """P4.1 WF (adversary S1): a level raise queues a job for every episode already mined; one waiting on Anki left the
    row's *Mine rest* as it was only if the row skips episodes in Anki — else the row read *Waiting*, whose *Mine now*
    asked for every file below the line. An episode whose cards the learner deleted is skipped the same way; a job on
    an episode still to mine (an ask below the line) is the row's, as before."""
    from app.connect import feed, runner
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 6), {2: {"mined_at": "2026-10-02T00:00:00Z"}})])
    cards = {1: 4}                      # the top 1: mined; 3: its cards deleted
    plain = vr.build(items, WORKS, {"mine_line": 1}, cards=cards)
    assert plain.rows[0].status.kind == "mine_rest"
    connect = _feed([_job(1, reason=runner.ANKI_CLOSED, kind="level"), _job(3, reason=runner.ON_BATTERY)])
    view = vr.build(items, WORKS, {"mine_line": 1}, cards=cards, connect=connect)
    assert view.rows[0].status == plain.rows[0].status, "the row keeps its own: Mine rest"
    asked = _feed([_job(1, reason=runner.ANKI_CLOSED, kind="level"), _job(5, kind="asked", state="queued")])
    view = vr.build(items, WORKS, {"mine_line": 1}, cards=cards, connect=asked)
    assert (view.rows[0].status.kind, view.rows[0].status.tip) == ("asked", vr.STRINGS["tip_asked"])


def test_a_chinese_row_reads_its_wait_from_connects_feed():
    """zh: Connect waits on a Chinese episode (Anki Miner's Chinese support) with its reason — the same rule."""
    from app.connect import runner
    WORKS[5] = dict(WORKS[1], id=5, title="雷鸣之剑与见习魔女")
    items = items_of([("now", 5, 5, ["雷鸣之剑与见习魔女 第3集.srt", "雷鸣之剑与见习魔女 第4集.srt"], {})])
    connect = _feed([_job(1, reason=runner.CHINESE)], language="zh")
    view = vr.build(items, WORKS, {"mine_line": 20}, language="zh", connect=connect)
    assert (view.rows[0].status.kind, view.rows[0].status.tip) == ("waiting", runner.CHINESE)


def test_the_same_feed_gives_back_the_same_rows_and_a_new_one_rebuilds_only_the_rows_it_changed():
    """S19 with the reader's RowCache: the Provider hands back the same Feed object while Connect is unchanged, so
    every row is the same object (nothing repainted); a new Feed that changes one item's job rebuilds that row alone."""
    from app.connect import runner
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {})])
    cache = vr.RowCache()
    one = _feed([_job(1, reason=runner.ANKI_CLOSED)])
    first = vr.build(items, WORKS, {"mine_line": 20}, numbers=(1, {}), cache=cache, connect=one)
    again = vr.build(items, WORKS, {"mine_line": 20}, numbers=(1, {}), cache=cache, connect=one)
    assert all(a is b for a, b in zip(first.rows, again.rows))
    two = _feed([_job(1, reason=runner.ANKI_CLOSED), _job(4, reason=runner.NO_VIDEO)])
    moved = vr.build(items, WORKS, {"mine_line": 20}, numbers=(1, {}), cache=cache, connect=two)
    assert moved.rows[0] is again.rows[0] and moved.rows[1] is not again.rows[1]
    assert moved.rows[1].episodes[0].status.kind == "no_media"


# --- LM11b G1: a group the learner made is one row ----------------------------------------------------------------- #
def _group_items(names_b=None, wid_b=2, extra_b=None):
    """Two shows in one group piece (10) at the top of Current — 星降る街の小さな工房 Ep 1–2, then another show's files —
    and 白銀の書庫番 as a run (piece 3) below it."""
    names_b = names_b if names_b is not None else eps("雲の上の郵便屋さん", 1, 3)
    return items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("now", wid_b, 10, names_b, extra_b or {}),
                     ("now", 3, 3, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 3)], {})])


def _group(title=None):
    return {10: {"id": 10, "title": title, "kind": "group"}, 3: {"id": 3, "title": "白銀の書庫番", "kind": "run"}}


def test_LM11b_G1_two_shows_grouped_are_one_row_named_after_the_first_show_plus_how_many_more():
    """Sonic's G3: a group is one row named "<first show> + N more" until he names it, with the first episode's show's
    cover and title (its work) — each episode still labelled and numbered by its own show, the line saying how many
    files and shows it holds. Wrong, a group would read as two rows again, or as the first show alone."""
    view = vr.build(_group_items(), WORKS, {"mine_line": 20}, pieces=_group())
    assert [r.title for r in view.rows] == ["星降る街の小さな工房 + 1 more", "白銀の書庫番"]
    row = view.rows[0]
    assert row.group is True and view.rows[1].group is False
    assert (row.work_id, row.cover_title, row.cover) == (1, "星降る街の小さな工房", vr.cover_of(WORKS[1]))
    assert row.media == "anime" and row.media_word == "video"
    assert [e.label for e in row.episodes] == ["Ep 1", "Ep 2", "Ep 1", "Ep 2", "Ep 3"]
    assert row.line == "5 files · 2 shows" and row.n_files == 5
    assert row.title_ep == "星降る街の小さな工房 · Ep 1"            # the next episode named with its own show


def test_LM11b_G1_a_groups_next_episode_names_its_own_show_and_the_line_keeps_the_watched_count():
    """The row's *next* is the first unwatched episode, whichever show it is of — named with that show, so "Ep 1" never
    reads as the first show's; a part-watched group keeps the "· K of N watched" a part-watched show has."""
    items = _group_items()
    for i in (1, 2):                                       # the first show's two episodes watched
        items[i] = dict(items[i], watched=1)
    view = vr.build(items, WORKS, {"mine_line": 20}, pieces=_group())
    row = view.rows[0]
    assert row.title_ep == "雲の上の郵便屋さん · Ep 1" and row.next_index == 2
    assert row.line == "5 files · 2 shows · 2 of 5 watched"


def test_LM11b_G1_the_name_the_learner_gave_a_group_wins_and_a_runs_stored_title_is_never_shown():
    """*Rename…* stores a group's own name: the row shows it. A run's piece title is its work's at cut time (Kura's
    LM11 notes: never shown) — a run reads its work's title as before."""
    pieces = _group("日曜の夜に見るもの")
    pieces[3] = dict(pieces[3], title="古い書庫番")
    view = vr.build(_group_items(), WORKS, {"mine_line": 20}, pieces=pieces)
    assert [r.title for r in view.rows] == ["日曜の夜に見るもの", "白銀の書庫番"]
    assert view.rows[0].cover_title == "星降る街の小さな工房"     # the cover stays the first episode's show's


def test_LM11b_G1_a_youtube_video_in_a_group_is_labelled_as_a_video_and_the_anime_beside_it_as_episodes():
    """Each episode is read by its own show's type: a video grouped with an anime keeps its own title (never "Ep 1"
    from a number in it, never playable from here), the anime's files stay *Ep N*. Wrong, the video would be read by
    the anime's rules or the anime's by the video's."""
    video = "【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"
    items = _group_items([video], wid_b=4, extra_b={0: {"source_type": "youtube"}})
    row = vr.build(items, WORKS, {"mine_line": 20}, pieces=_group()).rows[0]
    assert [e.label for e in row.episodes] == ["Ep 1", "Ep 2", "【検証】一週間お弁当を作り続けてみた"]
    assert row.episodes[2].number is None and not row.episodes[2].can_play
    assert row.episodes[0].number == 1 and row.title == "星降る街の小さな工房 + 1 more"
    assert row.line == "3 files · 2 shows"


def test_LM11b_G1_a_group_whose_first_show_is_a_channel_takes_the_channels_name_type_and_cover():
    """The first episode's show leads: a channel's video first gives the row the channel's name, cover and type (its
    media word *video*), the anime after it still *Ep N*."""
    items = items_of([("now", 4, 10, ["【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"], {0: {"source_type": "youtube"}}),
                      ("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {})])
    row = vr.build(items, WORKS, {"mine_line": 20}, pieces=_group()).rows[0]
    assert (row.title, row.media, row.work_id) == ("Tsubasa no Kitchen + 1 more", "youtube", 4)
    assert row.cover == vr.cover_of(WORKS[4]) and row.cover_title == "Tsubasa no Kitchen"
    assert [e.label for e in row.episodes] == ["【検証】一週間お弁当を作り続けてみた", "Ep 1", "Ep 2"]
    assert row.title_ep == "Tsubasa no Kitchen · 【検証】一週間お弁当を作り続けてみた"


def test_LM11b_G1_a_run_row_is_the_same_with_or_without_the_feeds_pieces():
    """A run's row never reads its piece's meta: built with the feed's pieces it equals the row built without them,
    field for field (the window's other rules — split, join, the stones — read the same row as before)."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {}), ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {})])
    pieces = {1: {"id": 1, "title": "古い名前", "kind": "run"}, 2: {"id": 2, "title": None, "kind": "run"}}
    with_meta = vr.build(items, WORKS, {"mine_line": 20}, pieces=pieces)
    without = vr.build(items, WORKS, {"mine_line": 20})
    assert with_meta.rows == without.rows and not any(r.group for r in without.rows)


def test_LM11b_G1_the_cache_keeps_an_unchanged_group_and_rebuilds_it_after_a_rename_or_its_second_shows_change():
    """S19: an unchanged group comes back as the same object (nothing repainted); a new name (the feed's piece meta)
    or a change to its second show's work (a new cover, a type said) rebuilds it — the first show's work alone would
    leave a stale second show. The run beside it is kept throughout."""
    items, pieces = _group_items(), _group()
    cache = vr.RowCache()
    first = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, pieces=pieces)
    again = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, pieces=pieces)
    assert again.rows[0] is first.rows[0] and again.rows[1] is first.rows[1]
    renamed = {**pieces, 10: dict(pieces[10], title="日曜の夜に見るもの")}
    third = vr.build(items, WORKS, {}, numbers=(1, {}), cache=cache, pieces=renamed)
    assert third.rows[0] is not first.rows[0] and third.rows[0].title == "日曜の夜に見るもの"
    assert third.rows[1] is first.rows[1]
    works = {**WORKS, 2: dict(WORKS[2], cover_ref="anilist:21")}     # the second show's cover found
    fourth = vr.build(items, works, {}, numbers=(1, {}), cache=cache, pieces=renamed)
    assert fourth.rows[0] is not third.rows[0] and fourth.rows[1] is first.rows[1]
    works2 = {**works, 2: dict(works[2], media_type="youtube")}       # its type said: its files read as videos
    fifth = vr.build(items, works2, {}, numbers=(1, {}), cache=cache, pieces=renamed)
    assert fifth.rows[0] is not fourth.rows[0] and fifth.rows[0].episodes[2].label == "雲の上の郵便屋さん - 01"


def test_LM11b_G1_a_group_row_round_trips_through_the_first_screen_cache_and_an_older_cache_still_reads():
    """The first screen's cache keeps a group a group; a cache written before groups (its rows without `group` and
    `works`) still reads, every row a run."""
    import json
    view = vr.build(_group_items(), WORKS, {"mine_line": 20}, numbers={1: (9, 10, 1)}, pieces=_group())
    data = json.loads(json.dumps(vr.to_cache(view)))
    back = vr.from_cache(data)
    assert back.rows == view.rows and back.rows[0].group is True
    at = vr.Row._fields.index("group")
    old = dict(data, rows=[r[:at] + r[at + 2:] for r in data["rows"]])     # `group`, `works`
    before = vr.from_cache(old)
    assert before is not None and not any(r.group for r in before.rows)
    assert [r.title for r in before.rows] == [r.title for r in view.rows]


def test_LM11b_G1_a_chinese_group_reads_the_same_way():
    """zh: two Chinese shows in one group — the same name, line and per-show labels."""
    WORKS[5] = dict(WORKS[1], id=5, title="雷鸣之剑与见习魔女")
    WORKS[6] = dict(WORKS[2], id=6, title="山海经异闻录")
    items = items_of([("now", 5, 10, ["雷鸣之剑与见习魔女 第3集.srt", "雷鸣之剑与见习魔女 第4集.srt"], {}),
                      ("now", 6, 10, ["山海经异闻录 第1集.srt"], {})])
    row = vr.build(items, WORKS, {"mine_line": 20}, language="zh", pieces=_group()).rows[0]
    assert (row.title, row.line) == ("雷鸣之剑与见习魔女 + 1 more", "3 files · 2 shows")
    assert [e.label for e in row.episodes] == ["Ep 3", "Ep 4", "Ep 1"]


def test_LM11b_G1_a_group_at_the_soon_line_never_takes_its_last_shows_soon_files_into_its_row():
    """P-LF-16 makes one row of a show the Soon line runs through; a group ending with a show whose next files wait in
    Soon as a run of their own is not that show: the group stays one row above the line, the run one row below it
    (the store's rule: a group never takes a run beside it). Wrong, the row would hold files that aren't in the group."""
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 10, eps("雲の上の郵便屋さん", 1, 2), {}),
                      ("soon", 2, 12, eps("雲の上の郵便屋さん", 3, 4), {})])
    view = vr.build(items, WORKS, {"mine_line": 20}, pieces=_group())
    assert [(r.title, r.group, r.n_files) for r in view.rows] == [("星降る街の小さな工房 + 1 more", True, 4),
                                                                ("雲の上の郵便屋さん", False, 2)]
    assert view.rows[0].soon_from is None and [ln.after for ln in view.lines if ln.kind == "soon"] == [0]


def test_LM11b_G1_a_group_the_soon_line_runs_through_is_one_row_with_its_key_once_even_between_its_shows():
    """IK-1: the store keeps a group one piece across NOW and Soon (Kura's LM11), so the line can fall inside it — even
    between its two shows, where no show runs through the line. Wrong, two rows would carry the same key `p10`
    (the window finds rows by key) and the group would read as two."""
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("soon", 2, 10, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("soon", 3, 3, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 3)], {})])
    view = vr.build(items, WORKS, {"mine_line": 20, "soon_line": 2}, pieces=_group())
    assert [r.key for r in view.rows] == ["p10", "p3"]
    row = view.rows[0]
    assert row.group and row.n_files == 5 and (row.soon_from, row.soon_piece) == (2, 10)
    assert [ln.after for ln in view.lines if ln.kind == "soon"] == [0]
    assert vr.split_piece(row, 3) == (10, 3)                # ✂ in its Soon files splits the one piece, at its place


def test_LM11b_G1_a_group_in_goal_is_a_tile_of_its_own_never_its_first_shows():
    """IK-7: a group in 6+ Months is its own tile, named as its row is, its cover its first episode's show's, its files
    counted once — never folded into its first show's tile with the second show's files under the first's name."""
    items = items_of([("goal", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("goal", 2, 10, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("goal", 1, 12, eps("星降る街の小さな工房", 3, 4), {})])
    goal = vr.build(items, WORKS, {}, pieces=_group()).goal
    assert [(t.key, t.title, t.n_files) for t in goal.works] == [("p10", "星降る街の小さな工房 + 1 more", 5),
                                                                 ("w1", "星降る街の小さな工房", 2)]
    tile = goal.works[0]
    assert tile.cover == vr.cover_of(WORKS[1]) and tile.cover_title == "星降る街の小さな工房"
    assert tile.line == "5 files · 2 shows" and tile.item_ids == (1, 2, 3, 4, 5)
    assert sum(t.n_files for t in goal.works) == goal.files == 7


def test_LM11b_G3_each_goal_piece_names_its_piece_so_same_show_as_can_offer_goals_shows():
    """IK-6: *Same show as…* joins by piece, so each of a Goal tile's pieces carries its own `piece_id` (a show in two
    parts: both, in Goal's order; a group's tile: the group's) — without it Goal's shows were never offered. A piece
    made by hand without one stays None."""
    items = items_of([("goal", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("goal", 2, 10, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("goal", 3, 12, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 3)], {}),
                      ("goal", 3, 13, [f"白銀の書庫番 0{k} 章.txt" for k in range(3, 5)], {})])
    tiles = vr.build(items, WORKS, {}, pieces=_group()).goal.works
    assert [(t.key, [p.piece_id for p in t.pieces]) for t in tiles] == [("p10", [10]), ("w3", [12, 13])]
    assert vr.GoalPiece((1, 2), "Ep 1–2").piece_id is None


def test_LM11b_G1_a_group_of_channels_says_videos_and_channels_and_a_mixed_one_shows():
    """IK-10: a group whose every show is a YouTube channel counts *videos · channels*; one channel and one anime
    count *files · shows*, named from the channel when its video comes first."""
    WORKS[7] = dict(WORKS[4], id=7, title="週末キャンプ日和", youtube_channel="週末キャンプ日和")
    yt = {"source_type": "youtube"}
    both = items_of([("now", 4, 10, ["【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"], {0: yt}),
                     ("now", 7, 10, ["雨の日の焚き火 [d4e5f6].srt", "冬の湖でテント泊 [g7h8i9].srt"], {0: yt, 1: yt})])
    row = vr.build(both, WORKS, {}, pieces=_group()).rows[0]
    assert (row.title, row.line) == ("Tsubasa no Kitchen + 1 more", "3 videos · 2 channels")
    mixed = items_of([("now", 4, 10, ["【検証】一週間お弁当を作り続けてみた [a1b2c3].srt"], {0: yt}),
                      ("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {})])
    row = vr.build(mixed, WORKS, {}, pieces=_group()).rows[0]
    assert (row.title, row.line) == ("Tsubasa no Kitchen + 1 more", "3 files · 2 shows")


def test_LM11b_G1_a_row_names_its_works_in_episode_order_and_keeps_them_through_the_cache():
    """IK-3 (New arrivals' *After its show* reads it): a group's distinct works in episode order, a run's one, a row
    of no work none — and the first screen's cache gives them back as they were."""
    import json
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 10, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("now", 3, 3, [f"白銀の書庫番 0{k} 章.txt" for k in range(1, 3)], {}),
                      ("now", None, None, ["古い手紙.txt"], {})])
    view = vr.build(items, WORKS, {}, pieces=_group())
    assert [r.works for r in view.rows] == [(1, 2), (3,), ()]
    back = vr.from_cache(json.loads(json.dumps(vr.to_cache(view))))
    assert [r.works for r in back.rows] == [(1, 2), (3,), ()]


def test_LM11b_G1_goals_strip_counts_a_group_as_one_title_with_its_first_shows_cover_once():
    """A group is one row to the learner, so 6+ Months' strip counts it as one title (its first show's cover), even
    beside a part of that same show on its own — never as two titles for its two shows."""
    WORKS[5] = dict(WORKS[1], id=5, title="風の谷の薬草師")
    items = items_of([("goal", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("goal", 2, 10, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("goal", 5, 12, eps("風の谷の薬草師", 1, 2), {}), ("goal", 1, 13, eps("星降る街の小さな工房", 3, 4), {})])
    view = vr.build(items, WORKS, {}, pieces=_group())
    goal = view.goal
    assert (goal.titles, goal.files, goal.line) == (3, 9, "3 titles · 9 files") and view.counts.goal_titles == 3
    assert goal.covers == ("星降る街の小さな工房", "風の谷の薬草師", "星降る街の小さな工房")
    assert goal.cover_refs[0] == vr.cover_of(WORKS[1]) and len(goal.cover_refs) == 3
    assert [t.group for t in goal.works] == [True, False, False]          # GoalWork.group: the group's tile


def _mixed(missing=()):
    """星降る街の小さな工房 (an anime: Ep 1–2) grouped with 白銀の書庫番 (a light novel: its EPUB, Part 1); `missing`:
    the indexes whose file is gone."""
    return items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {k: {"availability": "missing"} for k in missing
                                                                    if k < 2}),
                     ("now", 3, 10, ["白銀の書庫番 01 章.epub"], {0: {"availability": "missing", "source_type": "epub"}}
                      if 2 in missing else {0: {"source_type": "epub"}})])


def test_LM11b_G1_a_video_and_epub_group_says_of_each_file_what_it_is():
    """(4) A group of an anime's videos and a book's EPUB claims nothing false: each episode's status, ▶ tip and word
    are its own type's — the EPUB gone is *No EPUB*, never *No video* — and the row's ⌀ mark speaks of the EPUB."""
    row = vr.build(_mixed(missing=(2,)), WORKS, {"mine_line": 20}, pieces=_group()).rows[0]
    book = row.episodes[2]
    assert [e.media_word for e in row.episodes] == ["video", "video", "EPUB"]
    assert (book.label, book.status.label) == ("Part 1", "No EPUB") and "video" not in book.status.tip
    assert row.mark is not None and row.mark.tip.startswith("Part 1: ")
    assert "video" not in row.mark.tip


def test_LM11b_G1_a_video_and_epub_group_with_both_gone_uses_the_neutral_word_on_its_row():
    """When the files the row speaks of are of different types, its status says *media*: "No media · 3" — each
    episode still its own *No video* / *No EPUB*; when only its videos are gone, its mark speaks of videos."""
    row = vr.build(_mixed(missing=(0, 1, 2)), WORKS, {"mine_line": 20}, pieces=_group()).rows[0]
    assert row.status.label == "No media · 3" and "No media on disk" in row.status.tip
    assert [e.status.label for e in row.episodes] == ["No video", "No video", "No EPUB"]
    videos = vr.build(_mixed(missing=(0, 1)), WORKS, {"mine_line": 20}, pieces=_group()).rows[0]
    assert videos.mark.tip.startswith("Ep 1, Ep 2: ")                       # only its videos gone: them named


def test_R55_C_a_missing_files_mark_says_what_happened_and_what_to_do_in_up_nexts_words():
    """R55-C (Sonic, 2026-10-23: "Your lean is fine"): with ▶ gone for a missing file, its mark carries the words ▶'s
    tip had — what happened and what to do, one string with Up Next's — never "No video on disk" for a file that was
    there and went (a book's or a podcast's too)."""
    row = vr.build(_mixed(missing=(0, 2)), WORKS, {"mine_line": 20}, pieces=_group()).rows[0]
    assert row.mark.tip == "Ep 1, Part 1: " + vr.STRINGS["play_missing"]
    assert "on disk" not in row.mark.tip and "Needs you" in row.mark.tip


def test_LM11b_G1_a_cached_rows_fast_path_reads_the_type_guess_and_never_keeps_a_stale_one():
    """(6) The cache's fast path (nothing global moved, the same items and work) compared Connect's part of the row's
    signature where it meant the untyped title's guess: a title whose guess moved — another piece's files gone from
    6+ Months — kept its old type. Its row must follow the guess."""
    WORKS[9] = dict(WORKS[1], id=9, title="夏草の記憶", media_type=None, anilist_id=None, tmdb_id=None)
    items = items_of([("now", 9, 1, eps("夏草の記憶", 1, 2), {}),
                      ("goal", 9, 2, [f"夏草の記憶 第{k}章.txt" for k in range(1, 6)], {k: {"source_type": "text"}
                                                                          for k in range(5)})])
    cache, cards = vr.RowCache(), {1: 0}          # one dict both builds (an empty one is made anew): the fast path
    first = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache)
    assert first.rows[0].media == "text"                 # five text files outweigh two subtitles: a text
    current = {i: r for i, r in items.items() if r["tier"] == "now"}         # the 6+ Months part removed
    second = vr.build(current, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache)
    assert second.rows[0].media is None and second.rows[0].media_word == "video"


def test_LM11b_G5_each_episode_names_its_own_show_and_keeps_it_through_the_first_screens_cache():
    """G5 offers *Move {show} to Finished* for one show of a group: each episode says which show it is of (its work)
    and that show's name as the group labels it — a run's episodes their work and no name. The first screen's cache
    keeps both; a cache from before (episodes without them) still reads, with neither. Wrong, the toast could not tell
    one show's episodes from the other's, or a restart would lose them."""
    import json
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 10, eps("雲の上の郵便屋さん", 7, 8), {}),
                      ("now", 3, 11, ["白銀の書庫番 01 章.epub"], {0: {"source_type": "epub"}})])
    pieces = {10: {"id": 10, "title": None, "kind": "group"}, 11: {"id": 11, "title": None, "kind": "run"}}
    view = vr.build(items, WORKS, {"mine_line": 20}, pieces=pieces)
    group, run = view.rows
    shows = [(1, "星降る街の小さな工房")] * 2 + [(2, "雲の上の郵便屋さん")] * 2
    assert [(e.work_id, e.show) for e in group.episodes] == shows
    assert [(e.work_id, e.show) for e in run.episodes] == [(3, None)]
    back = vr.from_cache(json.loads(json.dumps(vr.to_cache(view))))
    assert [(e.work_id, e.show) for e in back.rows[0].episodes] == shows
    old = json.loads(json.dumps(vr.to_cache(view)))
    at = vr.Row._fields.index("episodes")
    for r in old["rows"]:
        r[at] = [e[:vr.Episode._fields.index("work_id")] for e in r[at]]
    before = vr.from_cache(old)
    assert [(e.work_id, e.show) for e in before.rows[0].episodes] == [(None, None)] * 4
    assert [e.id for e in before.rows[0].episodes] == [e.id for e in group.episodes]


def test_LM11b_G5_a_group_holding_one_show_reads_as_its_run():
    """The store makes a group left with one work's items a run (`_settle_kinds`); the view reads such a piece so too —
    what the reader shows while a show's finish waits for a busy store: the show's own title and range, no group."""
    items = items_of([("now", 2, 10, eps("雲の上の郵便屋さん", 7, 8), {})])
    row = vr.build(items, WORKS, {"mine_line": 20}, pieces={10: {"id": 10, "title": None, "kind": "group"}}).rows[0]
    assert (row.group, row.title, row.line, row.title_ep) == (False, "雲の上の郵便屋さん", "Ep 7–8", "Ep 7")
    assert [e.show for e in row.episodes] == [None, None]


# --- LM11b review fix round (H-B2 / H-B3 / H-B4) -------------------------------------------------------------------- #
@pytest.mark.parametrize("with_pieces", (True, False))
def test_LM11b_H_B2_goals_title_count_is_its_tiles_count_so_untitled_pieces_never_collapse_into_one_title(with_pieces):
    """H-B2: three files with no title (no work), each its own piece, are three tiles in Goal; its strip counts three
    titles — by the tiles' own key, one rule with or without the feed's pieces. Wrong, the strip said "1 title" over
    three tiles (every untitled piece keyed as the one title None)."""
    items = items_of([("goal", None, 21, ["古い手紙.txt"], {}), ("goal", None, 22, ["祖母の日記.txt"], {}),
                      ("goal", None, 23, ["夏休みの記録.txt"], {}), ("goal", 1, 24, eps("星降る街の小さな工房", 1, 2), {})])
    view = vr.build(items, WORKS, {}, pieces=_group() if with_pieces else None)
    goal = view.goal
    assert len(goal.works) == 4
    assert (goal.titles, goal.line, view.counts.goal_titles) == (4, "4 titles · 5 files", 4)
    assert len(goal.covers) == 4 and goal.covers[3] == "星降る街の小さな工房"


def test_LM11b_H_B3_a_groups_goal_tile_holds_every_run_of_the_group_never_its_first_alone():
    """H-B3: a group in Goal whose files sit in two runs (another title between them) is one tile holding all of its
    files — counted, listed by id and brought up whole (its one GoalPiece). Wrong, the second run's files vanished
    from the tile: never counted, never moved with it."""
    items = items_of([("goal", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("goal", 3, 12, ["白銀の書庫番 01 章.txt"], {}),
                      ("goal", 2, 10, eps("雲の上の郵便屋さん", 1, 3), {})])
    goal = vr.build(items, WORKS, {}, pieces=_group()).goal
    assert [(t.key, t.n_files) for t in goal.works] == [("p10", 5), ("w3", 1)]
    tile = goal.works[0]
    assert tile.item_ids == (1, 2, 4, 5, 6) and tile.line == "5 files · 2 shows"
    assert [(p.item_ids, p.piece_id) for p in tile.pieces] == [((1, 2, 4, 5, 6), 10)]
    assert sum(t.n_files for t in goal.works) == goal.files == 6


def test_LM11b_H_B4_a_group_holding_one_show_is_that_shows_run_in_goal_and_at_the_soon_line_too():
    """H-B4 / H-C4: `_group_of` reads a group as `_row` does — one holding a single show is that show's run (the store
    makes it one, `_settle_kinds`): its Goal tile is the show's, never "2 files · 1 shows" under the group's name.
    Wrong, the tile said "1 shows" and was named as a group."""
    items = items_of([("goal", 2, 10, eps("雲の上の郵便屋さん", 7, 8), {})])
    tile = vr.build(items, WORKS, {}, pieces={10: {"id": 10, "title": None, "kind": "group"}}).goal.works[0]
    assert (tile.group, tile.title, tile.line) == (False, "雲の上の郵便屋さん", "2 episodes")
    assert "shows" not in tile.line and "1 show" not in tile.line
    assert vr._group_of({10: {"id": 10, "title": None, "kind": "group"}}, [items[1], items[2]]) is None
