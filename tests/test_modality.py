"""Reading-vs-listening classification.

The rule under test: a word earns a reading badge when more than `target_hours` of listening pass
between encounters — estimated from the bundled reference table, overridden by the learner's own
subtitle/YouTube material where they have enough of it.

The asymmetry is the part most likely to be broken by a later change, so it gets its own tests:
hearing a word proves it is hearable, but NOT hearing one proves almost nothing.
"""

import math
import os

from app import analyzer, modality


# --- the rank -> exposure curve ------------------------------------------------------------- #

def test_common_words_are_heard_constantly_and_rare_ones_effectively_never():
    """Anchored on the calibration points in modality.py, so a curve change is caught."""
    assert modality.estimated_hours_between(560) < 3          # 会社 — heard all the time
    assert 3 < modality.estimated_hours_between(8261) < 30    # 演説 — heard regularly
    assert modality.estimated_hours_between(63131) > 100      # 佇む — effectively never


def test_curve_is_monotonic():
    """A rarer word can never come out as more frequently heard."""
    hours = [modality.estimated_hours_between(r)
             for r in (500, 2000, 5000, 10000, 25000, 50000, 90000)]
    assert hours == sorted(hours)


def test_beyond_corpora_is_unhearable_not_merely_rare():
    """Rank 0 is the 'the corpora never saw it' sentinel and must read as infinite."""
    assert modality.estimated_hours_between(modality.BEYOND_CORPORA) == math.inf
    assert modality.estimated_hours_between(None) == math.inf


# --- classification ------------------------------------------------------------------------- #

BASE = dict(lib_count=20, spoken_count=0, series_count=12,
            library_series=38, listening_hours_total=115.0)


def test_rare_in_speech_is_a_reading_word():
    assert modality.classify(63131, **BASE) == "reading"      # 佇む


def test_common_in_speech_is_not():
    assert modality.classify(560, **BASE) is None             # 会社


def test_word_absent_from_the_table_makes_no_claim():
    """Proper nouns and non-written vocabulary never entered the table; silence is correct."""
    assert modality.classify(None, **BASE) is None


def test_too_rare_in_the_library_makes_no_claim():
    """Below the evidence floor we say nothing, however rare the word is in speech."""
    args = dict(BASE, lib_count=2)
    assert modality.classify(63131, **args) is None


# --- the override: observation beats estimate, in ONE direction only ------------------------ #

def test_hearing_it_yourself_removes_the_badge():
    """115 h of material and 20 encounters = once per ~6 h. You plainly hear this word."""
    args = dict(BASE, spoken_count=20)
    assert modality.classify(63131, **args) is None


def test_hearing_it_rarely_does_not_remove_the_badge():
    """Twice in 115 h is once per ~58 h — worse than the target, so the badge stands."""
    args = dict(BASE, spoken_count=2)
    assert modality.classify(63131, **args) == "reading"


def test_never_hearing_a_common_word_does_NOT_add_a_badge():
    """The asymmetry. Absence of evidence is not evidence of absence.

    会社 is rank 560 — common in speech. A learner with no subtitle files at all has simply never
    tested it, and must not be told to make a reading card for it.
    """
    args = dict(BASE, spoken_count=0, listening_hours_total=0.0)
    assert modality.classify(560, **args) is None


def test_no_listening_material_means_no_override():
    """With zero hours the observation is undefined, not zero — it must not divide by anything."""
    assert modality.observed_hours_between(5, 0) is None
    assert modality.observed_hours_between(0, 115.0) is None


# --- dispersion ------------------------------------------------------------------------------ #

def test_word_confined_to_one_work_is_not_general_vocabulary():
    """A character name or piece of series jargon, not something to build a reading card from."""
    args = dict(BASE, series_count=1)
    assert modality.classify(63131, **args) is None


def test_dispersion_is_skipped_on_a_small_library():
    """On a 3-work library 'appears in few works' says more about the library than the word."""
    args = dict(BASE, series_count=1, library_series=3)
    assert modality.classify(63131, **args) == "reading"


# --- series naming (the input dispersion depends on) ----------------------------------------- #

def test_series_name_groups_volumes_of_one_work():
    """A light novel split across volume folders is ONE work, or every character name looks
    beautifully dispersed while appearing in a single book."""
    data_dir = os.path.join("data", "ja")
    for folder in ("Honzuki v1", "Honzuki v2", "Honzuki_3", "Honzuki - 4"):
        path = os.path.join(data_dir, "HighPriority", folder, "ch01.txt")
        assert analyzer._series_name(path, data_dir) == "Honzuki"


def test_series_name_keeps_distinct_works_apart():
    data_dir = os.path.join("data", "ja")
    a = analyzer._series_name(os.path.join(data_dir, "HighPriority", "Bleach", "e01.srt"), data_dir)
    b = analyzer._series_name(os.path.join(data_dir, "HighPriority", "Vinland", "e01.srt"), data_dir)
    assert a != b


def test_loose_file_in_a_tier_is_its_own_work():
    """No evidence loose files belong together, so don't invent a grouping."""
    data_dir = os.path.join("data", "ja")
    path = os.path.join(data_dir, "LowPriority", "article.txt")
    assert analyzer._series_name(path, data_dir) == "article.txt"


# --- listening hours -------------------------------------------------------------------------- #

def test_listening_hours_uses_the_shared_minutes_per_file():
    """Same unit the band slider speaks, so both features phrase exposure identically."""
    assert modality.listening_hours(345, 20) == 115.0
    assert modality.listening_hours(0, 20) == 0.0
    assert modality.listening_hours(345, 0) == 0.0
