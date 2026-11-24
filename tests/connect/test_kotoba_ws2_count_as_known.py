"""Kotoba-WS2 (Sonic 2026-11-19 / 2026-11-20): one *Count as known in Anki*, and a red or green flag never Known.

- *Count suspended cards as known* (`anki_sync_include_suspended`) is folded into *Count as known in Anki*
  (`known_from_anki`, default Suspended + Marked): with Connect's signal off (Make cards for me or Automation off) the
  known-words sync counts the studied cards you suspended in every picked state (`anki_sync.counted_suspended`), the
  same rule the signal reads (`known_signal.carries`); with it on, the signal reads every suspended card itself.
- A learner who had turned the old switch on, and never picked the states, keeps "a card I suspend counts": read as
  Suspended alone at load — nothing written.
- The review loop's moves (WL-46 / 46b): Suspend + Red flag = Ignore, Suspend + Green flag = Swap — never Known,
  whatever the picks; a plain suspend counts by default only with its Mark.

What a wrong answer would cost: a word the learner meant to ignore or swap counted known (it leaves their list and
their journey for good — the sync is append-only), or a learner's own pick widened or narrowed by the fold. Real
words, ja + zh; settings.json, KnownWord.json and the signal's record in the test root; a stand-in Anki that answers
the search as Anki does (`test_kantan_b3_suspend_default.SearchingAnki`), never a live one.
"""
import json
import os

import pytest

from app import anki_sync, settings_manager
from app.connect import known_signal
from app.path_utils import get_settings_path
from tests.connect.test_kantan_b3_suspend_default import (DECK, URL, WORDS, SearchingAnki, _known_forms,  # noqa: F401
                                                          _write_settings, anki)

RED, ORANGE, GREEN = 1, 2, 3


def _file():
    with open(get_settings_path(), encoding="utf-8") as f:
        return json.load(f)


# --- red and green: never Known ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_suspended_and_marked_card_flagged_red_or_green_is_never_known(anki, language):
    # why: the loop's Ignore (red) and Swap (green) are suspends with a reason; a Mark on the same card never wins
    knows, ignored, swapped, orange, *_rest = WORDS[language]
    _write_settings({"connect_enabled": True})
    settings = settings_manager.load_settings()
    known_signal.read(language, URL, [DECK], [], settings)                      # the baseline: nothing signalled yet
    anki.add(1, knows, new=False, suspended=True, tags=["marked"])
    anki.add(2, ignored, new=False, suspended=True, tags=["marked"], flag=RED)
    anki.add(3, swapped, new=False, suspended=True, tags=["marked"], flag=GREEN)
    anki.add(4, orange, new=False, suspended=True, tags=["marked"], flag=ORANGE)  # another colour: the learner's own
    got = known_signal.read(language, URL, [DECK], [], settings)
    assert sorted(got["marked"]) == sorted([knows, orange])
    assert _known_forms(language) == {knows, orange}


@pytest.mark.parametrize("terms", [["suspended"], ["marked"], ["flag:1"], ["suspended", "flag:3"]])
def test_whatever_the_picks_red_and_green_win(anki, terms):
    # why: "a red or green flag is never Known, whatever Count as known in Anki says" — even a pick saved before that
    # named red or green counts no red / green card
    word_red, word_green, *_rest = WORDS["ja"]
    _write_settings({"connect_enabled": True, "known_from_anki": terms, "known_from_anki_chosen": True})
    settings = settings_manager.load_settings()
    known_signal.read("ja", URL, [DECK], [], settings)
    anki.add(1, word_red, new=False, suspended=True, tags=["marked"], flag=RED)
    anki.add(2, word_green, new=False, suspended=True, tags=["marked"], flag=GREEN)
    got = known_signal.read("ja", URL, [DECK], [], settings)
    assert got["marked"] == [] and _known_forms("ja") == set()


def test_the_signals_search_excludes_red_and_green_and_surasuras_own_suspends():
    query = known_signal.query(["suspended", "marked"], [DECK], {})
    for part in ("is:suspended", "tag:marked", "-flag:1", "-flag:3", "-tag:Surasura::later", "-tag:leech"):
        assert part in query.split(), (part, query)
    assert "-flag:2" not in query and "-flag:7" not in query          # every other colour stays the learner's


# --- the fold: the known-words sync reads the same picks ---------------------------------------------------------- #
def test_with_connect_off_the_sync_counts_studied_suspended_cards_in_the_picked_states_only():
    clause = anki_sync.counted_suspended({})                            # nothing on file: Suspended + Marked
    query = anki_sync.scope_query([DECK], clause)
    assert query.startswith(f'(deck:"{DECK}") -is:new (-is:suspended OR (is:suspended ')
    assert "tag:marked" in query and "-flag:1" in query and "-flag:3" in query and "-tag:surasura::shelf" in query
    assert anki_sync.counted_suspended({"known_from_anki": ["suspended"]}).split()[0] == "is:suspended"
    assert anki_sync.counted_suspended({"known_from_anki": []}) is False        # off: no suspended card counts
    assert anki_sync.counted_suspended({"known_from_anki": ["purple?"]}) is False   # an unknown term: never wider
    assert anki_sync.scope_query([DECK], False).endswith("-is:new -is:suspended")


def test_with_connects_signal_on_the_sync_leaves_every_suspended_card_to_the_signal():
    # why: the signal reads suspended cards with its one-time offer and its undo; the sync adding them too would skip
    # the offer and leave words the signal's undo can't take back
    assert anki_sync.counted_suspended({"connect_enabled": True}) is False
    assert anki_sync.counted_suspended({"connect_enabled": True, "logic": {"automation": False}}) is not False


def test_a_changed_pick_reads_every_studied_card_again():
    # why: the sync is a delta by note id; a pick that now counts more cards must read them all once
    from tests.test_anki_sync import FakeCollection, _sync
    fake = FakeCollection()
    fake.add("残念")
    first = _sync(fake, include_suspended=anki_sync.counted_suspended({}))
    again = _sync(fake, include_suspended=anki_sync.counted_suspended({}))
    changed = _sync(fake, include_suspended=anki_sync.counted_suspended({"known_from_anki": ["suspended"]}))
    assert (first.mode, again.mode, changed.mode) == ("full", "delta", "full")
    assert anki_sync.load_state("ja")["include_suspended"].startswith("is:suspended")


# --- the old switch: a learner's pick kept ------------------------------------------------------------------------ #
def test_a_learner_who_turned_count_suspended_on_keeps_suspended_alone_and_nothing_is_written():
    _write_settings({"anki_sync_include_suspended": True, "known_from_anki": ["suspended", "marked"]})
    before = _file()
    loaded = settings_manager.load_settings()
    assert loaded["known_from_anki"] == ["suspended"] and loaded["known_from_anki_chosen"] is True
    assert _file() == before                                            # read, never written by a load
    assert anki_sync.counted_suspended(loaded).split()[0] == "is:suspended"
    assert "tag:marked" not in anki_sync.counted_suspended(loaded)


@pytest.mark.parametrize("on_disk, wanted", [
    ({"anki_sync_include_suspended": True, "known_from_anki": ["marked"], "known_from_anki_chosen": True}, ["marked"]),
    # a pick made before Kantan-B3's marker existed (no `known_from_anki_chosen`): the learner's own, kept
    ({"anki_sync_include_suspended": True, "known_from_anki": ["marked"]}, ["marked"]),
    ({"anki_sync_include_suspended": True, "known_from_anki": []}, []),
    ({"anki_sync_include_suspended": True}, ["suspended"]),                  # no key on file: their switch read
    ({"anki_sync_include_suspended": False}, ["suspended", "marked"]),
    ({"anki_sync_include_suspended": "yes"}, ["suspended", "marked"]),       # only a real True was ever on
    ({}, ["suspended", "marked"]),
])
def test_a_pick_made_since_or_the_switch_off_reads_as_it_is(on_disk, wanted):
    _write_settings(on_disk)
    assert settings_manager.load_settings()["known_from_anki"] == wanted


# --- a pick survives its own save (Kotoba-WS2F, the keeper's F1) -------------------------------------------------- #
@pytest.mark.parametrize("stored", [None, ["suspended"], ["suspended", "marked"]])     # the old default, today's
@pytest.mark.parametrize("old_switch", [True, False, "absent"])
@pytest.mark.parametrize("pick, wanted", [
    (["suspended"], ["suspended"]), (["marked", "suspended"], ["suspended", "marked"]), (["marked"], ["marked"]),
    ([], []), (["flag:2", "suspended"], ["suspended", "flag:2"]),
])
def test_a_pick_saved_from_settings_reads_back_as_picked_whatever_the_old_switch_was(stored, old_switch, pick, wanted):
    # why: the old switch's fold sets the marker in memory only, so a pick that wrote no marker beside it was read as
    # the old switch again on the next load — Suspended + Marked undid itself to Suspended alone (the rows with the
    # switch on are the ones the bug reached; the rest pin that nothing else moved). The key isn't per language: one
    # language's save covers both
    from app.qt import settings_catalog as catalog
    from app.services.settings import SettingsService
    on_disk = {} if old_switch == "absent" else {"anki_sync_include_suspended": old_switch}
    if stored is not None:
        on_disk["known_from_anki"] = stored
    _write_settings(on_disk)
    service = SettingsService(delay=0)
    changes, update = catalog.change(catalog.ROW["known_from_anki"], service.get(), "ja", pick)
    service.set(changes, update=update, now=True)
    assert service.flush(5)
    assert settings_manager.load_settings()["known_from_anki"] == wanted, (on_disk, pick, _file())
