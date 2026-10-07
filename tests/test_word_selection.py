"""Tests for the word-selection policy (app/word_selection.py).

The band MATH is exercised end-to-end over REAL ja text: index it, project to the unknown
distribution, then select. This keeps the test grounded in real tokenizer output rather than
invented counts, and verifies the properties that matter — band nesting, monotonic coverage,
scale-stability of the ppm floor, and the count-equivalent bridge the YouTube preview relies on.
"""

import pytest

from app import token_index as ti
from app import word_selection as ws

JA_TEXT = (
    "冒険だ。\n冒険する？\n今夜は冒険。\n彼は毎日冒険に出かけます。\n"
    "私たちは新しい冒険を求めている。\n冒険は危険だが、価値がある。\n冒険！\n"
    "今日はいい天気です。\n猫と犬が好きです。\n公園を散歩しました。\n"
)


@pytest.fixture
def freqs(tmp_path):
    f = tmp_path / "lib.txt"
    f.write_text(JA_TEXT, encoding="utf-8")
    store = ti.open_store("ja", path=str(tmp_path / "s.db"))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))
    fr = store.unknown_frequencies(skip_singles=True)
    store.close()
    return fr


# --- Pure math ------------------------------------------------------------------------------ #
def test_band_floor_ppm_values():
    assert ws.band_floor_ppm("core") == 2000.0
    assert ws.band_floor_ppm("occasional") == 25.0
    assert ws.band_floor_ppm("uncommon") == 10.0
    assert ws.band_floor_ppm("rare") == 4.0
    assert ws.band_floor_ppm("very_rare") == 2.5
    assert ws.band_floor_ppm("native") == 1.0          # tiny floor (~= min_count on typical libraries)


def test_band_label_formats_multiword_keys():
    assert ws.band_label("very_rare") == "Very Rare"
    assert ws.band_label("core") == "Core"


def test_band_floor_count_is_scale_invariant():
    """The SAME band ppm becomes proportionally more raw occurrences in a bigger library —
    that's the whole point: a ppm means the same density regardless of size."""
    assert ws.band_floor_count("core", 1_000_000) == 2000.0
    assert ws.band_floor_count("core", 2_000_000) == 4000.0   # 2x tokens -> 2x count for same ppm
    # 'native' carries a tiny 1ppm floor: on a big library it clears min_count (5M -> 5), but on a
    # small library it clamps up to the universal min_count (so it still just drops one-offs).
    assert ws.band_floor_count("native", 5_000_000) == 5.0
    assert ws.band_floor_count("native", 50) == ws.DEFAULT_MIN_COUNT


def test_ladder_is_nested_and_native_drops_only_one_offs():
    """On a real-sized library the bands form a strict nested ladder, and Native keeps everything
    EXCEPT true one-offs (count == 1). Uses a synthetic distribution so the ppm ladder is actually
    exercised (a tiny real sample can't span the ppm range)."""
    total = 1_000_000
    # counts (== ppm at 1M tokens) chosen to straddle each floor: core 2000, common 150,
    # occasional 25, uncommon 10, rare 4, very_rare 2.5, native = min_count 2. Last word (1) is a one-off.
    unknown = [("w0|", 3000), ("w1|", 500), ("w2|", 100), ("w3|", 20),
               ("w4|", 6), ("w5|", 3), ("w6|", 2), ("w7|", 1)]
    sizes = {b: len(ws.select_band(unknown, total, b)) for b in ws.BANDS_ORDER}
    assert sizes == {"core": 1, "common": 2, "occasional": 3, "uncommon": 4, "rare": 5,
                     "very_rare": 6, "native": 7}
    # Native excludes the single-occurrence word, and nothing more.
    native = ws.select_band(unknown, total, "native")
    assert ("w7|", 1) not in native and ("w6|", 2) in native
    assert len(native) < len(unknown)


def test_coverage_is_monotonic_across_bands(freqs):
    """Learning a wider band can only increase (never decrease) resulting coverage."""
    covs = [ws.preview(freqs, b, avg_file_tokens=1773)["coverage_percent"] for b in ws.BANDS_ORDER]
    assert covs == sorted(covs)
    assert covs[-1] >= covs[0]


def test_preview_reports_counts_and_immersion_hours(freqs):
    p = ws.preview(freqs, "common", avg_file_tokens=1773, minutes_per_file=18)
    total = freqs["total_tokens"]
    assert p["word_count"] == len(ws.select_band(freqs["unknown"], total, "common"))
    assert 0 <= p["coverage_percent"] <= 100
    # hours_between = (minutes/60) / (floor density x tokens per file) — self-consistent with floor_ppm.
    occ_per_file = p["floor_ppm"] / 1_000_000 * 1773
    assert p["hours_between"] == pytest.approx((18 / 60) / occ_per_file, rel=1e-6)


def test_preview_native_drops_only_one_offs(freqs):
    """Native keeps every unknown that recurs (count >= 2) and drops one-offs — landing just under,
    not at, full coverage."""
    p = ws.preview(freqs, "native", avg_file_tokens=1773)
    recurring = [c for _, c in freqs["unknown"] if c >= ws.DEFAULT_MIN_COUNT]
    assert p["word_count"] == len(recurring)
    assert p["floor_ppm"] > 0.0    # effective floor reflects min_count, not a misleading 0


def test_preview_handles_empty_library():
    empty = {"total_tokens": 0, "known_tokens": 0, "unknown": []}
    p = ws.preview(empty, "occasional", avg_file_tokens=None)
    assert p["word_count"] == 0
    assert p["coverage_percent"] == 0.0
    assert p["hours_between"] is None            # no avg size -> no time estimate, no crash


def test_band_previews_returns_all_bands_ordered(freqs):
    """The GUI helper returns one preview per band, and word counts are non-decreasing along the
    slider (Core -> Native)."""
    previews = ws.band_previews(freqs, avg_file_tokens=1773)
    assert list(previews.keys()) == ws.BANDS_ORDER
    counts = [previews[b]["word_count"] for b in ws.BANDS_ORDER]
    assert counts == sorted(counts)
    assert previews["native"]["coverage_percent"] >= previews["core"]["coverage_percent"]


def test_low_bands_collapse_when_ppm_floor_dips_below_min_count():
    """DESIGN NOTE (not a bug): a band whose ppm-equivalent floor lands BELOW the universal
    min_count clamps up to min_count — so two low bands can select IDENTICALLY on a given library.

    With the tightened defaults (very_rare=2.5ppm), 'Very Rare' collapses into 'Native' on a SMALL
    library (both clamp to min_count) — the slider then hides the redundant band. On a large-enough
    library they stay distinct. This guards the calibration and documents the collapse as intended,
    size-dependent behaviour."""
    # Small library: very_rare's ppm-equivalent floor is below min_count, so it clamps to native's
    # floor (the reported collapse). very_rare=2.5ppm at 615k -> 1.54 < min_count 2.
    small = 615_221
    assert (ws.band_floor_count("very_rare", small, ws.DEFAULT_BANDS_PPM, ws.DEFAULT_MIN_COUNT)
            == ws.band_floor_count("native", small, ws.DEFAULT_BANDS_PPM, ws.DEFAULT_MIN_COUNT))

    # Large library: the two lowest bands are DISTINCT (very_rare=2.5ppm clears min_count).
    big = 2_000_000
    assert (ws.band_floor_count("very_rare", big, ws.DEFAULT_BANDS_PPM, ws.DEFAULT_MIN_COUNT)
            > ws.band_floor_count("native", big, ws.DEFAULT_BANDS_PPM, ws.DEFAULT_MIN_COUNT))


def test_custom_bands_ppm_override(freqs):
    """A user-tuned ppm floor changes the selection; a stricter floor selects fewer words."""
    total = freqs["total_tokens"]
    loose = len(ws.select_band(freqs["unknown"], total, "common", {"common": 1}))
    strict = len(ws.select_band(freqs["unknown"], total, "common", {"common": 1_000_000}))
    assert loose >= strict
    assert strict == 0    # an absurdly high floor selects nothing


# --- Automatic rarity: the rarest band with auto_max_words words or fewer ----------------------- #
def _ladder(*counts):
    """Band previews holding these word counts, Core -> Native. The rule reads only word_count —
    the same "N words" the slider's line shows for each band."""
    return {b: {"band": b, "word_count": n, "coverage_percent": 0.0, "floor_ppm": 0.0,
                "hours_between": None} for b, n in zip(ws.BANDS_ORDER, counts)}


# The user's Japanese library as measured on 2026-09-28 (1,987 files, 4.35M tokens; known words and
# the three lists applied, no single characters): the numbers the ratified rule was chosen on.
MEASURED_LIBRARY = _ladder(0, 5, 193, 756, 2_474, 4_541, 9_978)


def test_automatic_rarity_picks_uncommon_at_850_and_occasional_at_750_on_the_measured_library():
    """The ratified rule (D1: A with 850): the RAREST band whose list fits under the line. Uncommon's
    756 fits under 850 and Rare's 2,474 doesn't. Under the scope's first number, 750, Uncommon is 6
    over — which is why 850 was chosen: 94 words of room instead of a flip every few episodes."""
    assert ws.auto_band(MEASURED_LIBRARY, 850) == "uncommon"
    assert ws.auto_band(MEASURED_LIBRARY, 750) == "occasional"


def test_automatic_rarity_uses_the_settings_850_when_no_number_is_given():
    """No magic number in code: the default line is logic.selection.auto_max_words."""
    assert ws.DEFAULT_AUTO_MAX_WORDS == 850
    assert ws.auto_band(MEASURED_LIBRARY) == "uncommon"


def test_automatic_rarity_counts_850_words_as_fitting_and_851_as_not():
    """'850 words or fewer' is inclusive: a band of exactly 850 is the list; one word more and the
    rule steps back to the band before it."""
    assert ws.auto_band(_ladder(0, 5, 193, 850, 2_474, 4_541, 9_978), 850) == "uncommon"
    assert ws.auto_band(_ladder(0, 5, 193, 851, 2_474, 4_541, 9_978), 850) == "occasional"


def test_automatic_rarity_goes_all_the_way_to_native_when_every_band_fits():
    """An advanced learner: even Native (everything but one-offs) is under the line."""
    assert ws.auto_band(_ladder(0, 3, 12, 40, 118, 305, 640), 850) == "native"


def test_automatic_rarity_stays_on_core_when_even_core_is_over_the_line():
    """A beginner: the commonest words alone are more than 850. The list can't be smaller than Core,
    so it stays there rather than picking nothing."""
    assert ws.auto_band(_ladder(1_204, 3_010, 5_122, 6_030, 8_415, 9_120, 9_561), 850) == "core"


def test_automatic_rarity_on_a_collapsed_tail_picks_native_the_band_the_slider_still_shows():
    """On a small library Very Rare selects exactly what Native does, and the slider hides Very Rare.
    The rule must land on the band that is still on the slider."""
    assert ws.auto_band(_ladder(0, 5, 193, 300, 520, 610, 610), 850) == "native"


def test_automatic_rarity_without_a_preview_says_none_so_the_caller_keeps_its_band():
    """Before the first Generate there are no numbers: None, never a guess."""
    assert ws.auto_band(None, 850) is None
    assert ws.auto_band({}, 850) is None


def test_automatic_rarity_steps_back_a_band_when_new_content_grows_one_past_the_line():
    """D4: worked out fresh every time. Learning brought Rare down to 840, so it moved on; a new
    season then grows Rare past the line again, and the rule steps back rather than keep a list
    that is no longer 850 words or fewer."""
    assert ws.auto_band(_ladder(0, 5, 193, 756, 840, 4_541, 9_978), 850) == "rare"
    assert ws.auto_band(_ladder(0, 6, 210, 790, 1_020, 5_100, 11_000), 850) == "uncommon"


# --- Q4-3: the second threshold (a band Automatic chose is kept until its list passes ~1,100) -------- #

def test_the_second_threshold_keeps_the_remembered_band_until_its_list_passes_1100():
    # Why: a band hovering around 850 flipped back and forth with every episode added or word learned, each flip
    # reshuffling the list and Anki's order. The remembered band now stays while it holds 1,100 words or fewer.
    ladder = _ladder(0, 5, 193, 756, 900, 4_541, 9_978)          # Rare (900) is past the 850 line
    assert ws.auto_band(ladder, 850) == "uncommon", "nothing remembered: today's rule"
    assert ws.auto_band(ladder, 850, remembered="rare") == "rare", "remembered, 900 <= 1,100: kept"
    assert ws.auto_band(_ladder(0, 5, 193, 756, 1_100, 4_541, 9_978), 850, remembered="rare") == "rare"
    assert ws.auto_band(_ladder(0, 5, 193, 756, 1_101, 4_541, 9_978), 850, remembered="rare") == "uncommon", \
        "past 1,100: steps back to the rarest band at or under the line"


def test_a_rarer_band_under_the_line_is_still_taken_over_the_remembered_one():
    # Why: the threshold only slows stepping BACK; learning that brings a rarer band under 850 still moves on.
    assert ws.auto_band(_ladder(0, 5, 193, 300, 520, 840, 9_978), 850, remembered="rare") == "very_rare"


def test_a_remembered_band_the_preview_lacks_or_a_line_above_1100_behaves():
    # Why: a collapsed tail can drop a band from the preview; a hand-edited line above 1,100 is never undercut.
    ladder = _ladder(0, 5, 193, 756, 900, 4_541, 9_978)
    assert ws.auto_band({b: p for b, p in ladder.items() if b != "rare"}, 850, remembered="rare") == "uncommon"
    assert ws.auto_band(ladder, 850, remembered="no-such-band") == "uncommon"
    assert ws.auto_band(_ladder(0, 5, 193, 756, 1_400, 4_541, 9_978), 1_500) == "rare"
    # A line above 1,100 is its own step-back point: a remembered band past it steps back.
    assert ws.auto_band(_ladder(0, 5, 193, 756, 1_400, 1_600, 9_978), 1_500, remembered="very_rare") == "rare"
