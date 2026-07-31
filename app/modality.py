"""Reading-vs-listening classification — is this a word you'll READ, or one you'll HEAR?

The learner's question is which kind of card to make: listening-first for words they'll meet in
anime and YouTube, reading-first for words that essentially only appear in text. Answering it
comes down to one quantity:

    How many hours of listening pass, on average, between encounters with this word?

Meet it every few hours and listening will teach it to you; meet it once per 250 hours and it
will never stick from audio no matter how much you immerse. Everything else — ranks, ratios,
corpora — is machinery for estimating that number.

Two sources feed it, and they are NOT symmetric:

  ESTIMATE   The bundled table (app/reference_data.py) gives the word's rank in spoken Japanese,
             distilled at build time from subtitle corpora. Applies to everyone.

  OBSERVATION The user's own subtitle/YouTube files. Where they have enough material, what they
             actually heard beats what the reference corpora predict.

Observation may only ever REMOVE a reading badge, never add one. Hearing a word proves it is
hearable; NOT hearing it proves very little — at 115 hours of material a rank-20,000 word is
expected about 1.6 times, so observing zero is unremarkable. Proving absence takes far more
evidence than proving presence, and the asymmetry is deliberate.

Pure arithmetic over counts the analyzer already has: no I/O, no tokenization, no corpus loading.
Mirrors app/word_selection.py, which owns the band math the same way.
"""

import math

from app.settings_manager import DEFAULT_SETTINGS

_DEFAULTS = DEFAULT_SETTINGS["logic"]["modality"]

DEFAULT_TARGET_HOURS = _DEFAULTS["target_hours"]
DEFAULT_MIN_SERIES = _DEFAULTS["min_series"]
DEFAULT_MIN_LIB_COUNT = _DEFAULTS["min_lib_count"]
DEFAULT_MIN_LIBRARY_SERIES = _DEFAULTS["min_library_series"]

# Rank -> hours-between-encounters, calibrated against a real subtitle library (696k tokens,
# 2,018 tokens per ~20-minute episode). Measured points:
#
#     rank  2,000- 5,000  ->    7 h        rank 25,000-40,000  ->  138 h
#     rank  5,000-10,000  ->   26 h        rank 40,000-60,000  ->  264 h
#
# which is steeper than plain Zipf (hours would scale linearly with rank); the tail of a spoken
# corpus thins faster than that. Fitting the two ends gives the exponent below. Kept as an
# explicit curve rather than a lookup table so the relationship stays inspectable — and because
# ranks past ~40,000 are noisy in any corpus this size, so pretending to per-band precision there
# would be false confidence.
_RANK_ANCHOR = 3162.0        # geometric centre of the 2,000-5,000 band
_HOURS_AT_ANCHOR = 7.0
_RANK_EXPONENT = 1.29

# A word the spoken corpora never saw. Not "infinitely rare" — just rarer than they can measure,
# which for this purpose means "you will not learn this by listening".
BEYOND_CORPORA = 0


def estimated_hours_between(spoken_rank):
    """Hours of listening between encounters with a word at this spoken rank.

    `spoken_rank` comes from the bundled table; BEYOND_CORPORA (0) means the corpora never saw
    it, which yields infinity — the word is treated as unhearable rather than merely rare.
    """
    if spoken_rank is None or spoken_rank <= BEYOND_CORPORA:
        return math.inf
    return _HOURS_AT_ANCHOR * (spoken_rank / _RANK_ANCHOR) ** _RANK_EXPONENT


def observed_hours_between(spoken_count, listening_hours):
    """Hours between encounters in the user's OWN listening material, or None if never heard.

    None means "no evidence", explicitly not "never occurs" — see the module docstring on why
    absence can't be treated as proof.
    """
    if not spoken_count or not listening_hours:
        return None
    return listening_hours / spoken_count


def listening_hours(spoken_file_count, minutes_per_file):
    """How many hours of listening material the library holds.

    Reuses `minutes_per_file` from logic.selection — the same figure the band slider already
    uses to phrase "meet each word every N hours", so both features speak one unit.
    """
    return (spoken_file_count or 0) * (minutes_per_file or 0) / 60.0


def classify(spoken_rank, lib_count, spoken_count=0, series_count=0,
             library_series=0, listening_hours_total=0.0, config=None):
    """Return "reading" for a word worth a reading-first card, else None.

    None is the honest answer for most words: either they're hearable, or there isn't enough
    evidence to say. Only a confident verdict earns a badge.
    """
    cfg = config or {}
    target = cfg.get("target_hours", DEFAULT_TARGET_HOURS)
    min_series = cfg.get("min_series", DEFAULT_MIN_SERIES)
    min_lib = cfg.get("min_lib_count", DEFAULT_MIN_LIB_COUNT)
    min_library_series = cfg.get("min_library_series", DEFAULT_MIN_LIBRARY_SERIES)

    # Too rare in the user's own material to be worth any card, whatever its modality.
    if lib_count < min_lib:
        return None

    # Not in the table: either not written vocabulary, or filtered at build time as a proper
    # noun / interjection. Either way we have nothing to say about it.
    if spoken_rank is None:
        return None

    if estimated_hours_between(spoken_rank) <= target:
        return None                      # the reference corpora say you'll hear it

    observed = observed_hours_between(spoken_count, listening_hours_total)
    if observed is not None and observed <= target:
        return None                      # ...and your own material proves you already do

    # Series dispersion: a word confined to one or two works is that story's vocabulary — a
    # character name, a place, a piece of jargon — not general reading vocabulary. Skipped on
    # small libraries, where "appears in few works" is a statement about the library rather
    # than about the word.
    if library_series >= min_library_series and series_count < min_series:
        return None

    return "reading"
