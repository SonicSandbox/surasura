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
from itertools import accumulate

from app.settings_manager import DEFAULT_SETTINGS

# Single source of truth for the NUMBERS lives in settings (logic.selection) — see settings.json,
# tunable like 'weights'. Mirror them here as fallbacks (for direct/test calls) so there are no
# duplicated magic numbers. ppm floors are calibrated to the standard vocabulary-coverage curve so
# the preview coverage spreads Core ~50% .. Native ~99% ("words this common cover X% of your text").
_SELECTION_DEFAULTS = DEFAULT_SETTINGS["logic"]["selection"]
DEFAULT_BANDS_PPM = dict(_SELECTION_DEFAULTS["bands_ppm"])
DEFAULT_MIN_COUNT = _SELECTION_DEFAULTS["min_count"]
MINUTES_PER_FILE = _SELECTION_DEFAULTS["minutes_per_file"]
DEFAULT_AUTO_MAX_WORDS = _SELECTION_DEFAULTS["auto_max_words"]
# Q4-3's second threshold: a band Automatic chose is kept until its list grows past this (never below the first line),
# so a list near 850 doesn't flip back and forth with every episode added or word learned.
DEFAULT_AUTO_STEP_BACK_WORDS = 1100

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
    floors = {b: band_floor_count(b, freqs.get("total_tokens", 0), bands_ppm, min_count) for b in BANDS_ORDER}
    given = _given_back(freqs.get("compounds"), floors.values())      # every band's at once
    ranked = _ranked(freqs.get("unknown", []))                       # and the words' counts, sorted once
    return {
        b: preview(freqs, b, bands_ppm, min_count, avg_file_tokens, minutes_per_file, given.get(floors[b]), ranked)
        for b in BANDS_ORDER
    }


def _ranked(unknown):
    """(every unknown word's count, ascending; their running sums): how many words, and how many uses, reach a floor
    are then found by bisection — the numbers a pass over the whole list gives, without the pass per band."""
    counts = sorted(c for _key, c in unknown)
    return counts, [0, *accumulate(counts)]


def auto_band(previews, max_words=DEFAULT_AUTO_MAX_WORDS, bands=None, remembered=None,
              step_back_words=DEFAULT_AUTO_STEP_BACK_WORDS):
    """Automatic rarity (logic.selection.auto): the RAREST band whose list holds `max_words` words or
    fewer — the same word counts the slider shows (band_previews). Learning shrinks every band, so the
    choice moves on by itself; new content can grow a band past the line again, and then it steps back
    — worked out fresh on every run, it always describes the list you have. A collapsed tail (Very
    Rare == Native) picks Native, the band the slider still shows. If even the first band (Core) holds
    more, the first band. None when there is no preview: the caller keeps the band it has.

    `remembered` (Q4-3, the band this library's store remembers Automatic last chose): a rarer band at or under the
    line is still taken; otherwise the remembered band stays while its list holds `step_back_words` words or fewer
    (never below `max_words`), and only above that does it step back. No remembered band: the rule above, as ever."""
    if not previews:
        return None
    bands = bands or BANDS_ORDER
    chosen = bands[0]
    for band in bands:
        if band in previews and previews[band]["word_count"] <= max_words:
            chosen = band
    if remembered in bands and remembered in previews and bands.index(chosen) < bands.index(remembered):
        if previews[remembered]["word_count"] <= max(step_back_words, max_words):
            return remembered
    return chosen


def _given_back(compounds, floors):
    """{floor: {"lemma|reading": uses}} — what the compounds too rare for each floor give their parts, by Generate's
    own rule (analyzer.LearningView): each use of a rare compound is a use of its free parts, a rare part's own in
    turn. So a band's word count is the list Generate writes at that band. `compounds` is unknown_distribution's
    (uses, parts, bases); {} without it (Chinese, no table).

    Every floor in one pass, lowest first: a compound whose parts hold no compound gives the same parts at every
    floor it is under, so it is added once, as the floor passes it; only one with a compound part is read again
    per floor (whether that part is rare too depends on it). Seven bands then cost about what one did."""
    if not compounds:
        return {}
    from app.analyzer import LearningView     # at call time: the analyzer imports this module
    uses, parts = compounds[0], compounds[1]
    nested = {key for key, ps in parts.items() if any((lemma, reading) in parts for lemma, reading, _f in ps)}
    # A plain one's credit is its parts as kept (unknown_distribution keeps exactly the free words a use can reach
    # the list through) — what LearningView.credits gives it wherever it is rare.
    plain = sorted((n, key) for key, n in uses.items() if n and key not in nested)
    running, out, i = {}, {}, 0
    for floor in sorted(set(floors)):
        while i < len(plain) and plain[i][0] < floor:
            n, key = plain[i]
            i += 1
            for lemma, reading, _free in parts[key]:
                name = f"{lemma}|{reading}"
                running[name] = running.get(name, 0) + n
        credit = dict(running)
        if nested:
            view = LearningView(uses, floor, parts=parts, joins={})
            for key in nested:
                n = uses[key]
                if n and n < floor:
                    for lemma, reading in view.credits(key):
                        name = f"{lemma}|{reading}"
                        credit[name] = credit.get(name, 0) + n
        out[floor] = credit
    return out


def preview(freqs, band, bands_ppm=None, min_count=DEFAULT_MIN_COUNT,
            avg_file_tokens=None, minutes_per_file=MINUTES_PER_FILE, given=None, ranked=None):
    """Live-preview numbers for a band selection.

    `freqs` is the dict from token_index.unknown_frequencies (total_tokens, known_tokens, unknown).
    Returns the word count, the coverage you'd reach after learning the selected set, the
    *effective* floor ppm, and the encounter rate of the FLOOR word per `files_per_unit` files
    (for the GUI's "~once per season (12 episodes)" line — units chosen so the phrasing stays
    truthful).

    A compound too rare for the band counts toward its parts, as in Generate's list (`_given_back`; `given` is
    this band's, when band_previews has worked every band out at once; `ranked`, the counts `_ranked` sorts).
    """
    total = freqs.get("total_tokens", 0)
    known = freqs.get("known_tokens", 0)
    floor_count = band_floor_count(band, total, bands_ppm, min_count)
    # The words whose count reaches the floor: how many, and their uses.
    counts, sums = ranked if ranked is not None else _ranked(freqs.get("unknown", []))
    first = bisect.bisect_left(counts, floor_count)
    word_count, selected_occ = len(counts) - first, sums[-1] - sums[first]
    credit = given if given is not None else _given_back(freqs.get("compounds"), (floor_count,)).get(floor_count)
    if credit:
        # Only the words a rare compound gives to change: listed once their own uses and those reach the floor.
        bases = freqs["compounds"][2]
        for name, n in credit.items():
            base = bases.get(name, 0)
            if base >= floor_count:
                selected_occ += n
            elif base + n >= floor_count:
                word_count += 1
                selected_occ += base + n

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
        "word_count": word_count,
        "coverage_percent": coverage,
        "floor_ppm": floor_ppm,
        "hours_between": hours_between,   # immersion hours between meeting the floor word
    }
