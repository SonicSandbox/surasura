"""Mado-LT — the review loop's moves are the learner's pick (Settings' three move cards; 3.0.18, WL mock 04).

Kyou-LR's reader read Ignore and Swap at fixed red and green (OPEN 55 e: "until the Settings cards exist"). Now every
reader asks one function, `review_loop.move_flags(settings)`: the reader's own searches, the waiting swap's taken-back
check, Connect's Known signal and the known-words sync (those two flags never count as known) and Settings' picks.

Pinned here, end to end through a stand-in Anki (Kyou-LR's `LoopAnki`): a purple Ignore and an orange Swap are read as
moves, red and green then mean nothing to the loop; the learner's Ignore / Swap flag never counts known, and red is
free to count again; a bad or clashing value reads as the default, never a wider search; settings that can't be read
keep red and green out. Real words (ja + zh); settings.json, KnownWord.json and every record in the test's temp root.

What a wrong answer would cost: a learner who moved Ignore to purple has every purple card's word ignored or never
read; a red card they now use for something else stays out of their known words for good (the sync is append-only).
"""
import json
import os

import pytest

from app import anki_sync, settings_manager
from app.connect import known_signal, review_loop
from app.path_utils import get_settings_path
from tests.connect.test_kyou_lr_review_loop import (DECK, GREEN, ORANGE, RED, URL, WORDS, WRITES, LoopAnki, _ignored,
                                                    _known, _waiting)

PURPLE, BLUE = 7, 4


def _save(**values):
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict({"connect_enabled": True}, **values), f)


def _sync(language):
    result, signal = anki_sync.sync_all(language, URL, [DECK], [], settings_manager.load_settings())
    assert not result.error, result.error
    return result


@pytest.fixture
def anki(monkeypatch):
    return LoopAnki(monkeypatch)


# --- the one function ---------------------------------------------------------------------------------------------- #
def test_the_defaults_are_red_for_ignore_and_green_for_swap():
    # why: the moves Sonic ruled (WL-46 / 46b) hold for every learner who never opens the cards
    assert review_loop.move_flags({}) == {"ignore": 1, "swap": 3}
    assert review_loop.move_flags(None) == {"ignore": 1, "swap": 3}
    assert settings_manager.DEFAULT_SETTINGS["loop_ignore_flag"] == 1
    assert settings_manager.DEFAULT_SETTINGS["loop_swap_flag"] == 3


@pytest.mark.parametrize("bad", [0, 8, -1, "x", "", None, True, 2.5, [1], "1 "])
def test_a_value_that_isnt_a_flag_reads_as_the_default_never_a_wider_search(bad):
    # why: a hand-edited settings.json must never make the loop read every card ("flag:0" = no flag at all)
    assert review_loop.move_flags({"loop_ignore_flag": bad, "loop_swap_flag": bad}) == {"ignore": 1, "swap": 3}


def test_a_flag_written_as_text_of_its_number_is_that_flag():
    assert review_loop.move_flags({"loop_ignore_flag": "7", "loop_swap_flag": "2"}) == {"ignore": 7, "swap": 2}


def test_swap_on_ignores_flag_falls_back_so_one_flag_never_means_both():
    # why: one card can't be both moves; Ignore keeps its pick (Ignore wins, OPEN 55 g)
    assert review_loop.move_flags({"loop_ignore_flag": 7, "loop_swap_flag": 7}) == {"ignore": 7, "swap": 3}
    assert review_loop.move_flags({"loop_ignore_flag": 3, "loop_swap_flag": 3}) == {"ignore": 3, "swap": 1}
    assert review_loop.move_flags({"loop_ignore_flag": 3}) == {"ignore": 3, "swap": 1}


def test_every_search_reads_the_picks():
    settings = {"loop_ignore_flag": PURPLE, "loop_swap_flag": ORANGE}
    assert "flag:7" in review_loop.query(review_loop.IGNORE, [DECK], settings).split()
    assert "flag:2" in review_loop.query(review_loop.SWAP, [DECK], settings).split()
    never = known_signal._never(settings)
    assert "-flag:7" in never and "-flag:2" in never and "-flag:1" not in never and "-flag:3" not in never
    assert "-flag:7" in known_signal.carries(["suspended"], settings).split()
    parts = anki_sync.known_query([DECK], False, settings).split()
    assert "-flag:7" in parts and "-flag:2" in parts and "-flag:1" not in parts and "-flag:3" not in parts


def test_the_plain_syncs_search_reads_the_saved_picks_when_none_are_given():
    # why: Replace and a bare sync() have no settings in hand: the saved ones, never the fixed red / green
    _save(loop_ignore_flag=BLUE, loop_swap_flag=PURPLE)
    parts = anki_sync.known_query([DECK]).split()
    assert "-flag:4" in parts and "-flag:7" in parts and "-flag:1" not in parts


def test_settings_that_cant_be_read_keep_red_and_green_out(monkeypatch):
    def broken():
        raise OSError("settings.json is locked")
    monkeypatch.setattr(settings_manager, "load_settings", broken)
    parts = anki_sync.known_query([DECK]).split()
    assert "-flag:1" in parts and "-flag:3" in parts


# --- end to end, through the sync ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_purple_ignore_and_an_orange_swap_are_read_and_red_and_green_mean_nothing_then(anki, language):
    # why: the learner's pick is the move; their old colours are free for something else (a plain suspend + flag)
    _save(loop_ignore_flag=PURPLE, loop_swap_flag=ORANGE)
    ignore, swap, red, green, *_ = WORDS[language]
    _sync(language)                                                      # the first read: nothing yet
    anki.add(1, ignore, suspended=True, flag=PURPLE)
    anki.add(2, swap, suspended=True, flag=ORANGE)
    anki.add(3, red, suspended=True, flag=RED)
    anki.add(4, green, suspended=True, flag=GREEN)
    result = _sync(language)
    assert _ignored(language) == {ignore}
    assert _waiting(language) == [(swap, 2)]
    assert result.loop["ignored"] == 1 and result.loop["swap"] == 1
    assert not WRITES & set(anki.asked), anki.asked                      # still only reads Anki


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_learners_ignore_flag_never_counts_known_and_red_counts_again(anki, language):
    # why: a studied card flagged with the Ignore move never counts known, suspended or not (Kotoba-WS2 note b) —
    # and red, no longer a move, is a card like any other
    _save(loop_ignore_flag=PURPLE)
    purple, red, *_ = WORDS[language]
    anki.add(1, purple, flag=PURPLE)                                     # studied, unsuspended
    anki.add(2, red, flag=RED)
    _sync(language)
    assert red in _known(language) and purple not in _known(language)


def test_a_waiting_swap_is_taken_back_against_the_swap_flag_picked_now(anki):
    # why: `_taken_back` asked `flags == 3`; with Swap on orange a card still suspended + orange stays waiting
    _save(loop_swap_flag=ORANGE)
    swap, other, *_ = WORDS["ja"]
    _sync("ja")
    anki.add(1, swap, suspended=True, flag=ORANGE)
    anki.add(2, other, suspended=True, flag=ORANGE)
    _sync("ja")
    assert _waiting("ja") == [(swap, 1), (other, 2)]
    anki.set(1, tags=["leech"])                                          # left the search, still suspended + orange
    anki.set(2, flag=0)                                                  # the learner took it back
    _sync("ja")
    assert _waiting("ja") == [(swap, 1)]


def test_the_empty_state_no_decks_reads_nothing_whatever_the_picks():
    assert review_loop.query(review_loop.IGNORE, [], {"loop_ignore_flag": PURPLE}) is None


# --- the edge cases (For Sonic 2-4) -------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_flags_swapped_ignore_green_and_swap_red_read_each_as_its_move(anki, language):
    # why: two valid picks that trade the defaults must never read as a clash: green is Ignore, red is Swap, and
    # neither counts known
    _save(loop_ignore_flag=GREEN, loop_swap_flag=RED)
    assert review_loop.move_flags(settings_manager.load_settings()) == {review_loop.IGNORE: GREEN, review_loop.SWAP: RED}
    ignore, swap, studied_green, studied_red, *_ = WORDS[language]
    _sync(language)
    anki.add(1, ignore, suspended=True, flag=GREEN)
    anki.add(2, swap, suspended=True, flag=RED)
    anki.add(3, studied_green, flag=GREEN)                               # studied, unsuspended: never known either
    anki.add(4, studied_red, flag=RED)
    _sync(language)
    assert _ignored(language) == {ignore}
    assert _waiting(language) == [(swap, 2)]
    assert not {ignore, swap, studied_green, studied_red} & set(_known(language))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_ignore_moved_off_red_reads_the_cards_already_purple_and_red_counts_known_again(anki, language):
    # why (For Sonic 2, 3): a colour picked later works as the loop's first read does — cards already carrying it are
    # read at the next sync; the red card the learner keeps, studied, counts known like any other from then on
    ignore, red, *_ = WORDS[language]
    _save()
    anki.add(1, ignore, suspended=True, flag=PURPLE)                     # purple means nothing yet
    anki.add(2, red, flag=RED)                                           # studied red: Ignore's colour, never known
    _sync(language)
    assert _ignored(language) == set() and red not in _known(language)
    _save(loop_ignore_flag=PURPLE)
    _sync(language)
    assert _ignored(language) == {ignore}                                # read at the next sync
    assert red in _known(language)                                       # red is a card like any other again


def test_swap_moved_off_green_drops_a_swap_waiting_on_green_as_taken_back(anki):
    # why (For Sonic 2): the reader can't tell a card still green from one the learner flagged for another reason, so
    # a swap waiting on the old colour ends — PROVISIONAL, the register's For Sonic
    swap, *_ = WORDS["ja"]
    _save()
    _sync("ja")
    anki.add(1, swap, suspended=True, flag=GREEN)
    _sync("ja")
    assert _waiting("ja") == [(swap, 1)]
    _save(loop_swap_flag=ORANGE)
    _sync("ja")
    assert _waiting("ja") == []


@pytest.mark.parametrize("edited", ["purple", 9, "", None, [7]])
def test_a_hand_edited_flag_reads_red_end_to_end_and_red_never_counts_known(anki, edited):
    # why: settings.json is the learner's to edit; a value that isn't a flag must read as the default all the way
    # through the sync — never a search with no flag (every flagged card read as Ignore) nor red counting known
    _save(loop_ignore_flag=edited)
    ignore, studied, *_ = WORDS["ja"]
    _sync("ja")
    anki.add(1, ignore, suspended=True, flag=RED)
    anki.add(2, studied, flag=RED)
    _sync("ja")
    assert _ignored("ja") == {ignore} and studied not in _known("ja")


def test_anki_absent_with_picked_flags_reads_nothing_and_writes_nothing(anki):
    # why: the picks change no failure path — Anki closed, the sync says so, no record and no list written
    _save(loop_ignore_flag=PURPLE, loop_swap_flag=ORANGE)
    word, *_ = WORDS["zh"]
    anki.add(1, word, suspended=True, flag=PURPLE)
    anki.closed = True
    result, signal = anki_sync.sync_all("zh", URL, [DECK], [], settings_manager.load_settings())
    assert result.error and signal is None
    assert not os.path.exists(review_loop.record_path("zh")) and _ignored("zh") == set()
