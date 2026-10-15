"""The string of stones, planned (W3.1a package C): `app/services/stone_plan.py`, pure and Qt-free, tested on
real-shaped rows built from `view_rows.Episode` (the fields a Current row carries per file: watched, cards, in the top
20, missing, removed).

Each test names the rule it holds and why it matters to a learner: the tiers fuse only whole groups, there are always
twelve stones to click (or what is left), one ore for the rest, the next stone is big, the stones below the mining line
dim, each stone keeps its own look from run to run, the string fits its row in the order the redesign rules, and one
title width serves every row.
"""
import os
import subprocess
import sys

import pytest

from app.services import stone_plan as sp
from app.services import view_rows as vr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE = "星降る街の小さな工房"


def ep(i, watched=False, cards=0, in_top=True, missing=False, removed=False, title=TITLE):
    """One file as `view_rows._episode` makes it (only the fields the plan reads matter; the rest look real)."""
    return vr.Episode(id=1000 + i, label=f"Ep {i + 1}", number=i + 1, title=f"{title} - {i + 1:02d}",
                      watched=watched, cards=cards, mining=False, missing=missing, removed=removed, in_top=in_top,
                      pct=95.0, n_new=3, status=None, mark=None, rel_path=f"HighPriority/{title}/{title} - {i + 1:02d}.srt",
                      play_tip="", can_play=not missing)


def piece(n, next_at=0, extra=None):
    """n files, the first `next_at` watched (so the next is file `next_at`); `extra`: {index: {field: value}}."""
    extra = extra or {}
    return tuple(ep(i, watched=i < next_at, **extra.get(i, {})) for i in range(n))


def kinds(p):
    return [(e.kind, e.n if e.kind != "stone" else e.index) for e in p.items]


def stones(p):
    return [e for e in p.items if e.kind == "stone"]


# --- the plan ----------------------------------------------------------------------------------------------------- #
def test_a_one_file_row_is_a_single_stone_ringed_when_it_is_next():
    """A film or a one-off video is one stone to click; with nothing else to point at, it is the next one."""
    p = sp.plan(piece(1), 0, "movie", "i7")
    assert p.single and len(p.items) == 1 and p.items[0].kind == "stone"
    assert p.items[0].big and p.items[0].state == "rock" and p.next == 0
    watched = sp.plan(piece(1, next_at=1), 0, "movie", "i7")
    assert watched.items[0].state == "cut" and not watched.items[0].big and watched.next is None


def test_seven_files_are_seven_stones_with_no_tiers_and_no_ore():
    """Fewer than twelve: every file is a stone to click; nothing to fuse, nothing left for an ore."""
    p = sp.plan(piece(7, next_at=3), 3, "anime", "p1")
    assert kinds(p) == [("stone", i) for i in range(7)]
    assert [s.state for s in stones(p)] == ["cut"] * 3 + ["rock"] * 4
    assert [s.big for s in stones(p)] == [False, False, False, True, False, False, False]


def test_twelve_files_are_exactly_the_twelve_in_play():
    p = sp.plan(piece(12, next_at=11), 11, "anime", "p1")
    assert kinds(p) == [("stone", i) for i in range(12)] and p.twelve == (0, 12)


def test_thirteen_files_put_the_thirteenth_in_one_ore():
    """The twelve in play, then one ore for everything after — never a thirteenth stone."""
    p = sp.plan(piece(13), 0, "anime", "p1")
    assert kinds(p) == [("stone", i) for i in range(12)] + [("ore", 1)]
    assert p.items[-1].start == 12


def test_twenty_six_files_next_at_fourteen_fuse_the_first_twelve():
    """s0 = floor(14 / 12) × 12 = 12: one 12-group, the twelve 12–23 (two watched, the next big), an ore of 2."""
    p = sp.plan(piece(26, next_at=14), 14, "anime", "p2")
    assert kinds(p) == [("tier", 12)] + [("stone", i) for i in range(12, 24)] + [("ore", 2)]
    s = stones(p)
    assert [x.state for x in s[:3]] == ["cut", "cut", "rock"] and s[2].big and s[2].index == 14
    assert p.twelve == (12, 24) and p.next == 14


def test_sixty_one_files_next_at_sixty_fuse_one_sixty_not_five_twelves():
    """A whole 60 lies inside 0…60, so it is one hexagon; the twelve in play is the one file left."""
    p = sp.plan(piece(61, next_at=60), 60, "anime", "p3")
    assert kinds(p) == [("tier", 60), ("stone", 60)]


def test_a_hundred_and_thirty_files_next_at_125_fuse_one_120_then_the_last_ten_loose():
    """s0 = 120: the whole 120 is one octagon (no 12 after it — 120…130 is the twelve in play, ten files), no ore."""
    p = sp.plan(piece(130, next_at=125), 125, "anime", "p4")
    assert kinds(p) == [("tier", 120)] + [("stone", i) for i in range(120, 130)]
    assert p.twelve == (120, 130)


@pytest.mark.parametrize("next_at, expect", [
    (108, [60, 12, 12, 12, 12]),                 # a 60 fits at 0, then only 12s up to 108 (60 + 60 would pass it)
    (190, [120, 60]),                            # 0…120 whole, 120…180 a whole 60, s0 = 180
    (250, [120, 120]),
    (399, [120, 120, 120, 12, 12, 12]),          # s0 = 396: three 120s, then 360…396 in 12s (no whole 60 at 360)
])
def test_four_hundred_files_tier_by_the_biggest_whole_group_at_each_place(next_at, expect):
    """A tier is a 120 only where the whole 120 lies inside (and starts on a 120), else a 60 the same way, else a 12."""
    p = sp.plan(piece(400, next_at=next_at), next_at, "anime", "p5")
    assert [e.n for e in p.items if e.kind == "tier"] == expect
    starts = [e.start for e in p.items if e.kind == "tier"]
    assert starts[0] == 0 and all(b == a + e for a, b, e in zip(starts, starts[1:], expect))
    assert sum(expect) == next_at // 12 * 12


def test_a_group_starts_only_where_its_size_lines_up():
    """A 60 is files 60-119 of a piece, never 12-71: the groups line up from the piece's first file (from any start
    that is a multiple of 12)."""
    assert sp.tiers(12, 132) == [(12, 12), (24, 12), (36, 12), (48, 12), (60, 60), (120, 12)]
    assert sp.tiers(0, 0) == []


def test_the_ore_counts_what_comes_after_the_twelve():
    """400 files next at 250: the twelve is 240–251, the ore holds 252…399 = 148 files."""
    p = sp.plan(piece(400, next_at=250), 250, "anime", "p5")
    ore = p.items[-1]
    assert ore.kind == "ore" and ore.start == 252 and ore.n == 148 and ore.mined == 0 and ore.watched == 0
    assert ore.cut_points == 0 and ore.mined_step == 0


@pytest.mark.parametrize("watched, points", [(0, 0), (1, 1), (10, 1), (11, 2), (20, 2), (21, 3), (30, 3)])
def test_watched_files_past_the_twelve_show_as_one_to_three_cut_points_on_the_ore(watched, points):
    """A file watched out of order, past the twelve in play, still shows (gem-kit `o.cut`: > 1/3 → 2, > 2/3 → 3)."""
    eps = piece(42, extra={})
    eps = tuple(e._replace(watched=12 <= i < 12 + watched) for i, e in enumerate(eps))
    ore = sp.plan(eps, 0, "anime", "p6").items[-1]
    assert ore.n == 30 and ore.watched == watched and ore.cut_points == points


@pytest.mark.parametrize("mined, step", [(0, 0), (1, 1), (15, 1), (16, 2), (29, 2), (30, 3)])
def test_the_ore_takes_one_of_four_mined_steps(mined, step):
    eps = tuple(e._replace(cards=4 if 12 <= i < 12 + mined else 0) for i, e in enumerate(piece(42)))
    ore = sp.plan(eps, 0, "anime", "p6").items[-1]
    assert ore.mined == mined and ore.mined_step == step


def test_none_watched_starts_the_twelve_at_the_first_file_with_no_tiers():
    p = sp.plan(piece(40), 0, "anime", "p7")
    assert p.items[0].kind == "stone" and p.items[0].big and p.watched == 0
    assert not [e for e in p.items if e.kind == "tier"]


def test_a_finished_piece_whose_last_twelve_is_whole_shows_its_tiers_only():
    """All 24 watched: two 12-groups, nothing loose, no next, no ring."""
    p = sp.plan(piece(24, next_at=24), 23, "anime", "p8")
    assert kinds(p) == [("tier", 12), ("tier", 12)] and p.next is None and p.watched == 24
    assert kinds(sp.plan(piece(120, next_at=120), 119, "anime", "p8")) == [("tier", 120)]


def test_a_finished_piece_with_a_partial_last_twelve_keeps_those_stones_loose():
    """26 all watched: the tiers never hold another count (12 · 60 · 120 only), so 24–25 stay two cut stones."""
    p = sp.plan(piece(26, next_at=26), 25, "anime", "p8")
    assert kinds(p) == [("tier", 12), ("tier", 12), ("stone", 24), ("stone", 25)]
    assert all(s.state == "cut" and not s.big for s in stones(p))


def test_a_split_part_counts_its_twelves_from_its_own_first_file():
    """A part holding episodes 21–36 (its own 16 files): its twelve is its files 0–11, not the work's 13–24."""
    eps = tuple(ep(i)._replace(number=21 + i, label=f"Ep {21 + i}") for i in range(16))
    p = sp.plan(eps, 0, "anime", "p9")
    assert kinds(p) == [("stone", i) for i in range(12)] + [("ore", 4)]
    eps = tuple(e._replace(watched=i < 13) for i, e in enumerate(eps))
    assert kinds(sp.plan(eps, 13, "anime", "p9"))[0] == ("tier", 12)


def test_a_stone_in_anki_but_not_watched_is_a_raw_crystal():
    p = sp.plan(piece(12, next_at=2, extra={4: {"cards": 6}}), 2, "anime", "p1")
    assert [s.state for s in stones(p)][:6] == ["cut", "cut", "rock", "rock", "raw", "rock"]
    assert p.in_anki == 1


def test_watched_beats_in_anki():
    """A watched file with cards is cut: watching is the further step."""
    p = sp.plan(piece(3, next_at=1, extra={0: {"cards": 9}}), 1, "anime", "p1")
    assert stones(p)[0].state == "cut"


def test_a_stone_below_the_top_20_dims_only_when_it_is_neither_mined_nor_watched():
    """Below the mining line a file won't mine itself: it dims so the learner sees where the line falls."""
    eps = piece(6, next_at=1, extra={2: {"in_top": False}, 3: {"in_top": False, "cards": 3},
                                     4: {"in_top": True}, 5: {"in_top": False}})
    eps = tuple(e._replace(in_top=False) if i == 0 else e for i, e in enumerate(eps))   # watched, below the line
    dims = [s.dim for s in stones(sp.plan(eps, 1, "anime", "p1"))]
    assert dims == [False, False, True, False, False, True]


def test_missing_and_removed_ride_on_each_stone_for_the_painter():
    p = sp.plan(piece(4, extra={1: {"missing": True}, 2: {"missing": True, "removed": True, "cards": 5}}), 0,
                "anime", "p1")
    assert [(s.missing, s.removed) for s in stones(p)] == [(False, False), (True, False), (True, True), (False, False)]


def test_next_index_none_means_the_first_file_not_watched():
    assert sp.plan(piece(30, next_at=17), None, "anime", "p").next == 17
    assert sp.plan(piece(30, next_at=17), None, "anime", "p") == sp.plan(piece(30, next_at=17), 17, "anime", "p")


def test_the_next_index_the_row_gives_is_the_one_drawn_big():
    """`Row.next_index` is the source; a stone past it is not big."""
    p = sp.plan(piece(30, next_at=17), 17, "anime", "p")
    assert [s.index for s in stones(p) if s.big] == [17]


def test_an_empty_piece_plans_nothing_and_says_nothing():
    p = sp.plan((), None, "anime", "p0")
    assert p.items == () and p.n == 0 and sp.words(p) == "" and sp.layout(p, 300, 1.0).end == 0


@pytest.mark.parametrize("media, mix, gem", [
    ("anime", False, "sapphire"), ("drama", False, "sapphire"), ("movie", False, "sapphire"), (None, False, "sapphire"),
    ("lightnovel", False, "emerald"), ("book", False, "emerald"), ("manga", False, "emerald"), ("text", False, "emerald"),
    ("audiobook", False, "emerald"), ("youtube", False, "ruby"), ("podcast", False, "ruby"),
    ("youtube", True, "sapphire"),               # hato's mix is sapphire whatever its files are
])
def test_the_gem_follows_the_rows_media(media, mix, gem):
    assert sp.plan(piece(3), 0, media, "p", mix).gem == gem


def test_plan_of_a_view_rows_row_matches_its_episodes_and_hato_reads_sapphire():
    row = vr.Row(key="p12", index=0, tier="now", work_id=1, piece_id=12, media="youtube", media_word="video",
                 verb="Watch", title="Tsubasa no Kitchen", title_ep="", line="", source="hato", n_files=3, n_watched=1,
                 pct=None, pct_tone="none", n_new=None, status=None, mark=None, episodes=piece(3, next_at=1),
                 next_index=1, studying=False, date="", cover_title="", accessible="", description="", chips=(),
                 more_chips=0, play_tip="", can_play=True)
    p = sp.plan_of(row)
    assert p.gem == "sapphire" and p.next == 1 and p == sp.plan(row.episodes, 1, "youtube", "p12", True)


def test_a_plan_is_hashable_so_the_row_cache_can_key_on_it():
    a = sp.plan(piece(26, next_at=14), 14, "anime", "p2")
    b = sp.plan(piece(26, next_at=14), 14, "anime", "p2")
    assert hash(a) == hash(b) and {a: 1}[b] == 1


# --- variants ----------------------------------------------------------------------------------------------------- #
_PROBE = ("from app.services import stone_plan as sp; "
          "print(','.join(str(sp.variant('p12', i)) for i in range(64)))")


def test_variants_are_the_same_in_two_separate_runs():
    """Each stone keeps its own look from one start to the next: two interpreters with different hash salts agree."""
    outs = []
    for seed in ("1", "2"):
        env = dict(os.environ, PYTHONPATH=ROOT, PYTHONHASHSEED=seed)
        proc = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, env=env, capture_output=True, text=True,
                              timeout=120)
        assert proc.returncode == 0, proc.stderr[-2000:]
        outs.append(proc.stdout.strip())
    assert outs[0] == outs[1] == ",".join(str(sp.variant("p12", i)) for i in range(64))


def test_variants_spread_over_all_eight_and_follow_the_row_key():
    """Neighbouring stones mostly differ (repetition is a "never"); every variant on the sheet gets used."""
    vs = [s.variant for s in stones(sp.plan(piece(12), 0, "anime", "p12"))]
    assert len(set(vs)) >= 5
    many = [sp.variant(f"p{k}", i) for k in range(20) for i in range(12)]
    counts = [many.count(v) for v in range(8)]
    assert set(many) == set(range(8)) and min(counts) >= len(many) / 8 / 2
    assert [sp.variant("p12", i) for i in range(12)] != [sp.variant("p13", i) for i in range(12)]


def test_variants_are_pinned_so_a_stone_keeps_its_look_across_versions():
    """Changing the hash would re-cut every stone in every library at an update: these values are the contract."""
    assert [sp.variant("p12", i) for i in range(12)] == [0, 2, 4, 1, 0, 5, 7, 7, 3, 3, 3, 2]
    assert sp.variant("p12", "t", 0) == sp.plan(piece(26, next_at=14), 14, "anime", "p12").items[0].variant


# --- layout ------------------------------------------------------------------------------------------------------- #
def test_the_layout_steps_28_from_a_first_centre_at_24_and_ends_12_past_the_last_slot():
    p = sp.plan(piece(13), 0, "anime", "p1")
    lay = sp.layout(p, 1000, 1.0)
    assert lay.xs[:3] == (24.0, 52.0, 80.0) and lay.fits and lay.ws == 28 and lay.cf == 1
    assert lay.xs[12] == 24 + 11 * 28 + 14 + 23     # the ore's 46 slot after the twelfth stone
    assert lay.end == 10 + 12 * 28 + 46 + 12


def test_group_slots_are_40_50_54_and_scale_with_the_text_size():
    p = sp.plan(piece(400, next_at=190), 190, "anime", "p5")     # 120 · 60 · the twelve · the ore
    lay = sp.layout(p, 2000, 1.0)
    assert lay.xs[0] == 10 + 27 and lay.xs[1] == 10 + 54 + 25
    big = sp.layout(p, 3000, 1.3)
    assert big.xs == tuple(pytest.approx(x * 1.3) for x in lay.xs) and big.end == pytest.approx(lay.end * 1.3)
    assert sp.layout(sp.plan(piece(30, next_at=13), 13, "anime", "p"), 999, 1.0).xs[0] == 10 + 20


def test_short_of_room_watched_loose_stones_step_closer_first():
    """26 next at 23: eleven watched loose stones; a little short, they close up (28 → 14) and nothing else moves."""
    p = sp.plan(piece(26, next_at=23), 23, "anime", "p")
    full = sp.layout(p, 2000, 1.0).end
    lay = sp.layout(p, full - 55, 1.0)
    assert lay.fits and 14 <= lay.ws < 28 and lay.cf == 1 and lay.end == pytest.approx(full - 55)


def test_then_consecutive_groups_overlap_but_keep_half_of_themselves():
    p = sp.plan(piece(400, next_at=399), 399, "anime", "p")    # six tiers in a row, then 396…399 loose
    at14 = sp.layout(p, 2000, 1.0).end - 3 * 14             # three watched loose stones at 14
    lay = sp.layout(p, at14 - 40, 1.0)
    assert lay.fits and lay.ws == 14 and .5 <= lay.cf < 1 and lay.end == pytest.approx(at14 - 40)
    # the last group before the loose stones keeps its whole width: only five of the six overlap
    assert lay.xs[6] - lay.xs[5] == pytest.approx(40 / 2 + 14 / 2)
    # only just short at 14: the groups give the room, the watched stones stay at 14 (not 8 with whole groups)
    lay = sp.layout(p, at14 - 10, 1.0)
    assert lay.ws == 14 and lay.cf < 1 and lay.end == pytest.approx(at14 - 10)


def test_then_watched_stones_step_down_to_8_and_the_rest_is_a_shortfall():
    p = sp.plan(piece(400, next_at=399), 399, "anime", "p")
    tight = sp.tightest(p)
    lay = sp.layout(p, tight + 6, 1.0)
    assert lay.fits and lay.cf == .5 and 8 < lay.ws < 14 and lay.end == pytest.approx(tight + 6)   # the loosest
    worse = sp.layout(p, tight - 30, 1.0)
    assert not worse.fits and worse.ws == 8 and worse.cf == .5 and worse.shortfall == pytest.approx(30)
    assert sp.layout(p, tight - 30, 1.3).shortfall == pytest.approx(tight * 1.3 - (tight - 30))


def test_stones_never_shrink_unwatched_stones_keep_their_step():
    """The twelve's waiting stones are the ones to click: however short the room, they stay 28 apart."""
    p = sp.plan(piece(40, next_at=3), 3, "anime", "p")
    lay = sp.layout(p, 50, 1.0)
    assert not lay.fits and lay.xs[4] - lay.xs[3] == 28 and lay.xs[3] - lay.xs[2] == pytest.approx(8 / 2 + 28 / 2)


# a Current row's other columns (the extract §3): number 26·fz − 12, art clamp(92·fz, 10 % of the window, 150·fz),
# six gaps of 12, the string's margin 14, the hover anchor's −12, the Anki count ~45·fz, % · new 104·fz, padding 10;
# the list's inset 24 each side
def fixed_columns(window, fz):
    art = min(max(92 * fz, .1 * window), 150 * fz)
    return 26 * fz - 12 + art + 6 * 12 + 14 - 12 + 45 * fz + 104 * fz + 10


def list_width(window):
    return window - 48


# his rows' shapes (the brief's "one layout for all rows" checked on them)
REAL = [(1, 0), (7, 3), (12, 11), (13, 0), (26, 14), (61, 60), (130, 125), (400, 250), (24, 12), (50, 37)]


def _fit(window, fz, string_fz=None):
    plans = {(n, k): sp.plan(piece(n, next_at=k), k, "anime", f"p{n}") for n, k in REAL}
    fixed = fixed_columns(window, fz)
    tw = sp.title_width(list(plans.values()), list_width(window), fz, fixed, string_fz)
    room = list_width(window) - fixed - tw
    s = fz if string_fz is None else string_fz
    return tw, {nk: sp.layout(p, room, s) for nk, p in plans.items()}


@pytest.mark.parametrize("window, fz", [(1280, 1.0), (1280, 1.15), (1280, 1.3), (1024, 1.0)])
def test_real_rows_fit_on_one_line_at_1280_at_every_text_size_and_at_1024_small(window, fz):
    """His rows' shapes (a 400-file show among them) take one line, with one title width for every row."""
    tw, lays = _fit(window, fz)
    assert round(80 * fz) <= tw <= round(187 * fz)
    assert all(lay.fits for lay in lays.values()), (window, fz, tw)
    if window == 1280 and fz == 1.0:
        assert tw == 187                         # at the widest, nothing narrows


@pytest.mark.parametrize("fz, short", [(1.15, {(50, 37)}), (1.3, {(13, 0), (26, 14), (24, 12), (50, 37)})])
def test_at_1024_medium_and_large_the_title_reaches_its_floor_and_the_rest_comes_back_as_a_shortfall(fz, short):
    """With the string scaled by the text size (the stones' sheet is), a twelve still to come — never cut — doesn't fit
    1024 at Medium or Large beside these columns: the title stops at its floor and the plan says by how much each row
    is short (C.md: the finding for Mado). Stones never shrink to hide it."""
    tw, lays = _fit(1024, fz)
    assert tw == round(80 * fz)
    assert {nk for nk, lay in lays.items() if not lay.fits} == short
    assert all(lay.ws == 8 * fz and lay.shortfall > 0 for lay in lays.values() if not lay.fits)


def test_at_1024_with_the_string_at_the_reference_pages_own_px_medium_fits_and_large_nearly():
    """The reference page lays its string out in plain px at every text size (28 a step): passed as the string's own
    scale (`string_fz` 1.0), 1024 at Medium fits every row with the title at 98, and Large leaves one row 11 px short
    — the choice of scale is Mado's (C.md)."""
    tw, lays = _fit(1024, 1.15, string_fz=1.0)
    assert tw == 98 and all(lay.fits for lay in lays.values())
    tw, lays = _fit(1024, 1.3, string_fz=1.0)
    assert tw == 104 and [nk for nk, lay in lays.items() if not lay.fits] == [(50, 37)]
    assert lays[(50, 37)].shortfall == pytest.approx(11.1, abs=.1)


def test_the_title_narrows_by_the_worst_shortfall_and_never_under_its_floor():
    """One title width for every row: narrower by exactly what the worst string still lacks at its tightest."""
    p = sp.plan(piece(400, next_at=399), 399, "anime", "p")
    tight = sp.tightest(p)
    base = round(187 * 1.15)
    fixed = 1000 - base - tight * 1.15 + 20                 # 20 px short at the base width
    assert sp.title_width([p], 1000, 1.15, fixed) == base - 20
    assert sp.title_width([p], 1000, 1.15, fixed - 19.7) == base   # within half a pixel: no change
    assert sp.title_width([p], 1000, 1.15, fixed - 19.3) == base - 1
    assert sp.title_width([p], 1000, 1.15, fixed + 500) == round(80 * 1.15)
    assert sp.title_width([], 1000, 1.15, 0) == base


def test_the_title_is_decided_for_the_next_fuse_too():
    """13 files next at 11: today eleven watched stones can close up, but after the fuse the next twelve can't —
    the title is narrowed for that now, so it doesn't jump in the middle of the fuse."""
    p = sp.plan(piece(30, next_at=11), 11, "anime", "p")
    assert sp.ahead(p) > sp.tightest(p)
    base = round(187 * 1.0)
    fixed = 1000 - base - sp.tightest(p) + 5                # fits today with 5 px to spare at the tightest …
    assert sp.title_width([p], 1000, 1.0, fixed) < base     # … but not after the fuse


def test_the_ahead_width_is_the_next_twelve_waiting_and_an_ore_only_when_files_remain():
    # 24 files next at 3: after the fuse a 12-group and the twelve 12-23, nothing left for an ore
    assert sp.ahead(sp.plan(piece(24, next_at=3), 3, "anime", "p")) == 10 + 40 + 12 * 28 + 12
    assert sp.ahead(sp.plan(piece(25, next_at=3), 3, "anime", "p")) == 10 + 40 + 12 * 28 + 46 + 12


def test_the_ahead_width_is_zero_with_nothing_after_the_twelve():
    assert sp.ahead(sp.plan(piece(12), 0, "anime", "p")) == 0
    assert sp.ahead(sp.plan(piece(1), 0, "anime", "p")) == 0
    assert sp.ahead(sp.plan(piece(24, next_at=24), 23, "anime", "p")) == 0


def test_the_title_width_reads_the_same_for_a_list_or_a_tuple_of_plans():
    plans = [sp.plan(piece(n, next_at=k), k, "anime", f"p{n}") for n, k in REAL]
    assert sp.title_width(plans, 900, 1.3, 600) == sp.title_width(tuple(plans), 900, 1.3, 600)


# --- words -------------------------------------------------------------------------------------------------------- #
def test_the_screen_reader_counts_over_the_whole_piece_not_just_the_twelve():
    eps = piece(26, next_at=14, extra={14: {"cards": 4}, 15: {"cards": 2}, 25: {"cards": 1}})
    assert sp.words(sp.plan(eps, 14, "anime", "p")) == "14 of 26 watched, 3 in Anki"
    assert sp.words(sp.plan(piece(12, next_at=8), 8, "anime", "p")) == "8 of 12 watched"


def test_a_one_file_row_reads_as_watched_or_not():
    assert sp.words(sp.plan(piece(1), 0, "movie", "p")) == "Not watched yet"
    assert sp.words(sp.plan(piece(1, next_at=1, extra={0: {"cards": 3}}), 0, "movie", "p")) == "Watched, in Anki"
