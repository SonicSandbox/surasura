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
