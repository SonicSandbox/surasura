"""P2.4 gap tests (Kura's review, mutants P2.4-E03, P2.4-E04, P2.4-F34): the cap's own values.

Rules pinned, in plain words:
- a cap of 0 means no cap, so `cap()` returns 0 (not 1);
- a negative cap reads as 0 too (no cap, never a negative number of waiting cards);
- with no `connect_backlog_cap` in the settings, every language's cap is 300;
- Connect's default in the settings file is 300 cards waiting per language.

What a wrong answer would cost: a cap of 1 (E03) would hold a whole language's backlog to one card, so the user's
"no cap" choice quietly stops filling Anki; a default of 200 (E04, F34) would hold every new user to 200 waiting
cards instead of the 300 the design promises, and a fresh install would never show the 300.

Pure: `runner.Steps` over a plain settings dict and `settings_manager.DEFAULT_SETTINGS`; no Anki, no network, no files.
"""
from app import settings_manager
from app.connect import runner


def test_a_cap_of_zero_means_no_cap_and_stays_zero():
    # Why: 0 is the user's "no cap" choice; it must come back as 0, not be lifted to a minimum of 1.
    assert runner.Steps({"connect_backlog_cap": 0}).cap("ja") == 0


def test_a_negative_cap_reads_as_no_cap_zero():
    # Why: a hand-edited -5 must never turn into a negative waiting limit; it reads as 0, the same as "no cap".
    assert runner.Steps({"connect_backlog_cap": -5}).cap("ja") == 0


def test_with_no_cap_in_the_settings_every_language_gets_300():
    # Why: an install that never set the cap gets the design's 300 for each language, not an older 200.
    steps = runner.Steps({"connect_enabled": True})
    assert steps.cap("ja") == 300
    assert steps.cap("zh") == 300


def test_the_settings_file_default_cap_is_300_per_language():
    # Why: the default written into DEFAULT_SETTINGS is what a fresh settings.json holds; it must be 300 too,
    # and a Steps built from that default must give 300 for Japanese.
    assert settings_manager.DEFAULT_SETTINGS["connect_backlog_cap"] == 300
    steps = runner.Steps({"connect_enabled": True,
                          "connect_backlog_cap": settings_manager.DEFAULT_SETTINGS["connect_backlog_cap"]})
    assert steps.cap("ja") == 300
