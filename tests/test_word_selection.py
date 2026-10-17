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


# --- Automatic rarity: the commonest band with auto_max_words words or more (G3.2) ------------ #
def _ladder(*counts):
    """Band previews holding these word counts, Core -> Native. The rule reads only word_count —
    the same "N words" the slider's line shows for each band."""
    return {b: {"band": b, "word_count": n, "coverage_percent": 0.0, "floor_ppm": 0.0,
                "hours_between": None} for b, n in zip(ws.BANDS_ORDER, counts)}


# Sonic's Japanese library at the G3.2 try (2026-10-16, 3,847,221 tokens): Common 14, Occasional 318, Uncommon
# 1,093 words. The bands past Uncommon weren't counted there; these only grow.
G32_LIBRARY = _ladder(0, 14, 318, 1_093, 2_600, 4_900, 10_400)


def test_automatic_takes_uncommon_on_sonics_library_where_the_old_rule_left_him_318_words():
    # Why: G3.2. The old rule took the rarest band at or under 850 (Occasional, 318 words: a list too short to
    # learn from); Sonic: "it will pick the next highest if the current would be less than 850".
    assert ws.auto_band(G32_LIBRARY, 850) == "uncommon"
    assert ws.auto_band(G32_LIBRARY) == "uncommon", "the default line is logic.selection.auto_max_words"
    assert ws.DEFAULT_AUTO_MAX_WORDS == 850


def test_a_band_of_exactly_850_words_is_taken_and_849_steps_on():
    # Why: "at least 850" is inclusive: exactly 850 is enough; one word fewer and the next band is taken.
    assert ws.auto_band(_ladder(0, 5, 193, 850, 2_474, 4_541, 9_978), 850) == "uncommon"
    assert ws.auto_band(_ladder(0, 5, 193, 849, 2_474, 4_541, 9_978), 850) == "rare"


def test_when_no_band_reaches_the_line_automatic_takes_native_everything_on_offer():
    # Why: an advanced learner (or a small library): even Native holds fewer than 850, so the longest list there is.
    assert ws.auto_band(_ladder(0, 3, 12, 40, 118, 305, 640), 850) == "native"


def test_an_empty_library_lands_on_native_not_on_nothing():
    # Why: every band at 0 words (a first start, nothing indexed with words in it): a band, never None or an error.
    assert ws.auto_band(_ladder(0, 0, 0, 0, 0, 0, 0), 850) == "native"


def test_when_core_already_holds_the_line_automatic_stays_on_core():
    # Why: a beginner: the commonest words alone are 850 or more, so the shortest list that is long enough is Core.
    assert ws.auto_band(_ladder(1_204, 3_010, 5_122, 6_030, 8_415, 9_120, 9_561), 850) == "core"


def test_a_collapsed_tail_lands_on_native_the_band_the_slider_still_shows():
    # Why: on a small library Very Rare selects exactly what Native does and the slider hides Very Rare; whether the
    # tail is under the line or reaches it, the pick is the band still on the slider.
    assert ws.auto_band(_ladder(0, 5, 193, 300, 520, 610, 610), 850) == "native"
    assert ws.auto_band(_ladder(0, 5, 193, 300, 520, 910, 910), 850) == "native"


def test_without_a_preview_automatic_says_none_so_the_caller_keeps_its_band():
    # Why: before the first Generate there are no numbers: None, never a guess.
    assert ws.auto_band(None, 850) is None
    assert ws.auto_band({}, 850) is None


def test_a_line_that_is_not_a_number_raises_so_the_callers_keep_your_band():
    # Why: auto_max_words is hand-edited in settings.json; "850" in quotes can't be compared, and every caller
    # (Generate, the dashboard, the window, arrivals) catches the error and keeps the user's own band.
    with pytest.raises(TypeError):
        ws.auto_band(G32_LIBRARY, "850")


def test_learning_moves_the_band_on_and_new_content_steps_it_back():
    # Why: worked out fresh every time. Learning brings Uncommon under the line, so Rare is taken; a new season then
    # grows Uncommon to the line again, and the shorter list that is long enough comes back.
    assert ws.auto_band(_ladder(0, 5, 150, 840, 2_300, 4_541, 9_978), 850) == "rare"
    assert ws.auto_band(_ladder(0, 6, 210, 900, 2_600, 5_100, 11_000), 850) == "uncommon"


# --- Q4-3: the second threshold (a band Automatic left is taken back only once it holds over ~1,100) ------ #

def test_the_second_threshold_keeps_the_remembered_band_until_the_commoner_one_passes_1100():
    # Why: a band hovering around 850 flipped the list back and forth with every episode added or word learned, each
    # flip reshuffling the list and Anki's order. Learning took Uncommon under 850, so Automatic moved on to Rare (and
    # remembers it); an episode then brings Uncommon back to 860. Rare stays until Uncommon holds more than 1,100.
    # (Bands far apart, as in a real library: Rare holds thousands, so its own size can't be the test.)
    ladder = _ladder(0, 14, 318, 860, 2_600, 4_900, 10_400)
    assert ws.auto_band(ladder, 850) == "uncommon", "nothing remembered: the plain rule"
    assert ws.auto_band(ladder, 850, remembered="rare") == "rare", "Uncommon at 860 <= 1,100: Rare kept"
    assert ws.auto_band(_ladder(0, 14, 318, 1_100, 2_600, 4_900, 10_400), 850, remembered="rare") == "rare"
    assert ws.auto_band(_ladder(0, 14, 318, 1_101, 2_600, 4_900, 10_400), 850, remembered="rare") ==         "uncommon", "past 1,100: steps back to the commonest band at or over the line"


def test_a_remembered_band_that_falls_under_the_line_gives_way_to_a_rarer_one():
    # Why: the threshold only slows stepping BACK; learning that brings the remembered band under 850 moves on.
    assert ws.auto_band(_ladder(0, 5, 150, 840, 2_300, 4_541, 9_978), 850, remembered="uncommon") == "rare"


def test_the_list_no_longer_flips_with_each_episode_and_each_word_learned():
    # Why: the flip Q4-3 was built to stop, walked through: Uncommon at 849 / 860 / 849 / 860 as words are learned and
    # episodes added. Each pick is remembered, as Generate records it; the list stays on Rare all the way.
    remembered = None
    picks = []
    for uncommon in (849, 860, 849, 860, 1_050):
        remembered = ws.auto_band(_ladder(0, 14, 318, uncommon, 2_600, 4_900, 10_400), 850, remembered=remembered)
        picks.append(remembered)
    assert picks == ["rare"] * 5, picks


def test_a_remembered_band_the_preview_lacks_or_a_line_above_1100_behaves():
    # Why: a collapsed tail can drop a band from the preview; a hand-edited line above 1,100 is never undercut.
    ladder = _ladder(0, 14, 318, 860, 2_600, 4_900, 10_400)
    assert ws.auto_band({b: p for b, p in ladder.items() if b != "rare"}, 850, remembered="rare") == "uncommon"
    assert ws.auto_band(ladder, 850, remembered="no-such-band") == "uncommon"
    assert ws.auto_band(_ladder(0, 5, 193, 756, 1_400, 4_541, 9_978), 1_500) == "very_rare"
    # A line above 1,100 is its own step-back point: a commoner band at the line is still kept off, one past it isn't.
    assert ws.auto_band(_ladder(0, 5, 193, 1_500, 2_600, 4_541, 9_978), 1_500, remembered="rare") == "rare"
    assert ws.auto_band(_ladder(0, 5, 193, 1_501, 2_600, 4_541, 9_978), 1_500, remembered="rare") == "uncommon"


# --- The rule over real text, both languages ------------------------------------------------------ #

# A ladder for a few real files (the shipped floors collapse to min_count on a library this small).
REAL_TEXT_BANDS_PPM = {"core": 20_000, "common": 10_000, "occasional": 6_000, "uncommon": 4_000, "rare": 2_500,
                       "very_rare": 1_500, "native": 1}
REAL_TEXT = {"ja": ["library_episode.ass", "phrases_sample.srt", "tv_captions.ass", "runaway_transcript.txt",
                    "placed_episode.srt", "context_test.txt"],
             "zh": ["chinese_text_1.txt", "patterns_zh_sample.txt", "traditional_news.txt", "night_market.srt",
                    "mixed_script_transcript.txt", "context_test.txt"]}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_over_real_text_automatic_takes_the_first_band_whose_list_reaches_the_line(
        tmp_path, language, ja_resources_dir, zh_resources_dir):
    # Why: the rule reads the slider's own numbers (band_previews over the token store), Japanese and Chinese alike.
    # For a line at each band's own count and one word past it, the pick holds at least that many words and every
    # commoner band (one with a different list) fewer; a line past Native's count lands on Native.
    import os
    folder = ja_resources_dir if language == "ja" else zh_resources_dir
    store = ti.open_store(language, path=str(tmp_path / "s.db"))
    try:
        store.reconcile([os.path.join(folder, name) for name in REAL_TEXT[language]], ti.make_tokenizer(language))
        previews = ws.band_previews(store.unknown_frequencies(skip_singles=language == "ja"), REAL_TEXT_BANDS_PPM)
    finally:
        store.close()
    counts = [previews[b]["word_count"] for b in ws.BANDS_ORDER]
    assert len(set(counts)) >= 4, (language, counts)              # a real ladder to draw lines on
    for line in sorted({c + step for c in counts[:-1] for step in (0, 1)} - {0}):
        if line > counts[-1]:
            continue
        pick = ws.auto_band(previews, line)
        at = ws.BANDS_ORDER.index(pick)
        assert counts[at] >= line, (language, line, pick, counts)
        assert all(c < line for c in counts[:at] if c != counts[at]), (language, line, pick, counts)
    assert ws.auto_band(previews, counts[-1] + 1) == "native", (language, counts)
