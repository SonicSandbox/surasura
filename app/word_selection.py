"""Word-selection policy — turn the raw unknown-word distribution into the 'learn now' set.

Two scale-stable methods replace the old raw `min_freq` count:
  - 'bands'    : density bands (Core / Common / Occasional / Uncommon / Rare / Very Rare / Native) — a per-word ppm
                 floor. Scale-invariant: the same band means the same 'how common' at any
                 library size, because the floor is a density, not a raw tally.
  - 'coverage' : reach a target coverage % (kept as the analyzer's existing target_coverage
                 behaviour — this module doesn't re-implement it).

This module owns the BAND math and the live-preview numbers (word count, resulting coverage,
encounter rate) so the analyzer's run-time cut and the GUI's live slider share ONE
implementation. It is pure arithmetic over the distribution from `token_index.unknown_frequencies`
— no tokenization, no I/O — so the preview is instant.
"""

import bisect

from app.settings_manager import DEFAULT_SETTINGS

# Single source of truth for the NUMBERS lives in settings (logic.selection) — see settings.json,
# tunable like 'weights'. Mirror them here as fallbacks (for direct/test calls) so there are no
# duplicated magic numbers. ppm floors are calibrated to the standard vocabulary-coverage curve so
# the preview coverage spreads Core ~50% .. Native ~99% ("words this common cover X% of your text").
_SELECTION_DEFAULTS = DEFAULT_SETTINGS["logic"]["selection"]
DEFAULT_BANDS_PPM = dict(_SELECTION_DEFAULTS["bands_ppm"])
DEFAULT_MIN_COUNT = _SELECTION_DEFAULTS["min_count"]
MINUTES_PER_FILE = _SELECTION_DEFAULTS["minutes_per_file"]

# Slider order = the band keys in their defined order ('native', the min_count baseline, last).
BANDS_ORDER = list(DEFAULT_BANDS_PPM.keys())

# Human display names (band key -> label). 'very_rare' must not naively .capitalize().
BAND_LABELS = {
    "core": "Core", "common": "Common", "occasional": "Occasional",
    "uncommon": "Uncommon", "rare": "Rare", "very_rare": "Very Rare", "native": "Native",
}


def band_label(band):
    """Display name for a band key (e.g. 'very_rare' -> 'Very Rare')."""
    return BAND_LABELS.get(band, band.replace("_", " ").title())

# min_count (above) is a universal floor applied to EVERY band: a word occurring only once in the
# whole library is a one-off (a name / typo / OCR artifact), never worth a card — at any size. So
# no band includes it. 'Native' is essentially this baseline (a tiny 1ppm floor that clamps up to
# min_count on typical libraries), which is why it lands *just under* 100% and keeps the slider
# ordered even on a tiny library where the ppm floors collapse below 1.


def band_floor_ppm(band, bands_ppm=None):
    """The configured density floor (parts-per-million) for a band. Native carries only a tiny floor
    (~= min_count on typical libraries, via band_floor_count). Unknown bands default to 0."""
    bands_ppm = bands_ppm or DEFAULT_BANDS_PPM
    return float(bands_ppm.get(band, 0.0))


def band_floor_count(band, total_tokens, bands_ppm=None, min_count=DEFAULT_MIN_COUNT):
    """The effective occurrence-count floor for a band in THIS library: the larger of the band's
    ppm-equivalent and the universal min_count (drop one-offs).

    This is the bridge that keeps a ppm floor meaning the same thing at any size — and it's
    exactly the 'minimum count' the YouTube preview needs (so a video pushing a word's combined
    count over this floor still surfaces it).
    """
    ppm_equiv = band_floor_ppm(band, bands_ppm) / 1_000_000 * total_tokens
    return max(min_count, ppm_equiv)


def select_band(unknown, total_tokens, band, bands_ppm=None, min_count=DEFAULT_MIN_COUNT):
    """Filter an unknown-word list [(key, count), ...] to those at/above the band's effective
    floor. Native keeps everything except one-offs (min_count)."""
    floor = band_floor_count(band, total_tokens, bands_ppm, min_count)
    if floor <= 0:
        return list(unknown)
    return [(k, c) for (k, c) in unknown if c >= floor]


def band_previews(freqs, bands_ppm=None, min_count=DEFAULT_MIN_COUNT,
                  avg_file_tokens=None, minutes_per_file=MINUTES_PER_FILE):
    """Preview numbers for EVERY band at once — what the GUI slider needs. Computed once from the
    (cached) distribution; sliding just indexes into the result. Returns {band: preview_dict}."""
    return {
        b: preview(freqs, b, bands_ppm, min_count, avg_file_tokens, minutes_per_file)
        for b in BANDS_ORDER
    }


def preview(freqs, band, bands_ppm=None, min_count=DEFAULT_MIN_COUNT,
            avg_file_tokens=None, minutes_per_file=MINUTES_PER_FILE):
    """Live-preview numbers for a band selection.

    `freqs` is the dict from token_index.unknown_frequencies (total_tokens, known_tokens, unknown).
    Returns the word count, the coverage you'd reach after learning the selected set, the
    *effective* floor ppm, and the encounter rate of the FLOOR word per `files_per_unit` files
    (for the GUI's "~once per season (12 episodes)" line — units chosen so the phrasing stays
    truthful).
    """
    total = freqs.get("total_tokens", 0)
    known = freqs.get("known_tokens", 0)
    floor_count = band_floor_count(band, total, bands_ppm, min_count)
    selected = [(k, c) for (k, c) in freqs.get("unknown", []) if c >= floor_count]
    selected_occ = sum(c for _, c in selected)

    # Coverage = the STANDARD vocabulary-coverage curve: what fraction of the library's text is
    # made of words at least this common (known + unknown). Baseline-independent, so it spans
    # ~50%..~99% across the bands. Falls back to personal (baseline + selected) if the full
    # distribution isn't supplied.
    all_counts = freqs.get("all_counts")
    if all_counts and total:
        i = bisect.bisect_left(all_counts, floor_count)
        coverage = sum(all_counts[i:]) / total * 100
    else:
        coverage = ((known + selected_occ) / total * 100) if total else 0.0
    # Effective ppm (from the count floor) so 'native' reflects its real, near-the-floor density
    # instead of a misleading 0.
    floor_ppm = (floor_count / total * 1_000_000) if total else 0.0
    # Immersion hours between encounters of the floor (rarest included) word: how long you'd
    # immerse, on average, before meeting it once. occ_per_file = floor density x tokens/file.
    hours_between = None
    if avg_file_tokens and floor_ppm > 0:
        occ_per_file = floor_ppm / 1_000_000 * avg_file_tokens
        if occ_per_file > 0:
            hours_between = (minutes_per_file / 60.0) / occ_per_file
    return {
        "band": band,
        "word_count": len(selected),
        "coverage_percent": coverage,
        "floor_ppm": floor_ppm,
        "hours_between": hours_between,   # immersion hours between meeting the floor word
    }
