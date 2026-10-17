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
    assert [(a.key, a.line) for a in split] == [("p12", "Ep 5–8"), ("p10", "Ep 1–4")]
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


def test_no_feed_or_an_off_feed_builds_todays_view_byte_for_byte():
    """`connect=None` (no Connect in this window) and Connect off (`Feed.on` False: IK S7) leave every row, episode
    and line as they are without the feed — a learner without Connect sees nothing new."""
    from app.connect import feed
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {2: {"availability": "missing"}}),
                      ("soon", 2, 2, eps("雲の上の郵便屋さん", 1, 3), {}),
                      ("graduated", 3, 3, ["白銀の書庫番 01 雨の街角.txt"], {})])
    plain = vr.build(items, WORKS, {"mine_line": 3})
    off = feed._off({"connect_enabled": True, "logic": {"automation": False}})
    assert vr.build(items, WORKS, {"mine_line": 3}, connect=None) == plain
    assert vr.build(items, WORKS, {"mine_line": 3}, connect=off)._replace(connect=None) == plain
    assert plain.connect is None


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
    assert (st[4].kind, st[4].tip) == ("waiting", runner.ANKI_CLOSED)
    assert (st[5].kind, st[5].tip) == ("waiting", runner.ON_BATTERY)
    assert (st[6].kind, st[6].tip) == ("waiting", feed.WORDS[feed.WAITING])
    assert (st[7].kind, st[7].label) == ("mine", "Mine"), "no job: as without Connect"
    assert (st[8].kind, st[8].tip) == ("waiting", feed.WORDS[feed.ASKED]), "an ask below the line waits, first"
    first, second = view.rows
    assert (first.status.kind, first.status.label) == ("mining", "Mining · 3/12"), "the row: its first job's"
    assert first.accessible.endswith("Mining · 3/12")
    assert (second.status.kind, second.status.tip) == ("waiting", feed.WORDS[feed.ASKED])
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
