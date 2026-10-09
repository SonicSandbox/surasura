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
    assert vr.episode_number("天気の子 (2019).srt") is None
    assert vr.episode_number("Hanashi Radio 2026-09-02.srt") is None
    assert vr.episode_number("海辺の図書室 - 05 [1080p] x264.mkv") == 5


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
    assert gone.removed and gone.status.kind == "in_anki" and gone.status.label == "7 in Anki"
    assert gone.mark is None or gone.mark.tone == "faint"
    assert row.status.kind == "in_anki" and row.status.label == "16 in Anki"
    assert row.mark is not None and row.mark.tone == "faint" and "deleted after mining" in row.mark.tip
    assert not gone.can_play and "removed" in gone.play_tip and "link" in gone.play_tip.lower()


def test_one_status_vocabulary_in_the_mocks_order():
    st = lambda **kw: vr.status_of([type("E", (), dict(dict(label="Ep 1", cards=0, mined=False, missing=False,
                                                            removed=False, in_top=False, mining=False), **kw))()],
                                   "video", 20)[0]
    assert st(cards=3, mined=True).label == "3 in Anki"
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
    # the hero is painted from Up next (its next episode), so it reads that way too (IK-12)
    assert view.rows[0].accessible == "Up next: 星降る街の小さな工房 Ep 1 · 95% known · 4 new · Waiting"


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
    assert row.status.kind == "in_anki" and row.status.label == "4 in Anki"
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
