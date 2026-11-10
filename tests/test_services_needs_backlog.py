"""*Needs you*'s card for the shows behind the Anki backlog (Michi-C, A7B-1…A7B-3 PROVISIONAL; `app/services/needs.py`
`_backlog_entry`, `backlog_head`). Qt-free and module-free: the offer is handed in as `modules/junban/backlog_shows`
keeps it, so it runs on GitHub too (no private modules there: `backlog_offer` is None and no card is made).

What a wrong answer would cost a learner who arrives with a big Anki Miner backlog: one card per show (or per card)
instead of one, a show offered that he already placed by hand, a *Leave them* that never lets a new show ask, or words
that miscount the shows he has.
"""
from types import SimpleNamespace

import pytest

from app.services import needs
from tests.test_library_store_support import LANGUAGES, names


def view(*arrival_ids):
    """A store view whose New arrivals hold these items (one tray row each)."""
    return SimpleNamespace(mode="store", rows=(), loading=False, needs=(),
                           arrivals=tuple(SimpleNamespace(item_ids=(i,)) for i in arrival_ids))


def offer(language, waiting=((11, 12),), away=1, placed=1, cards=2300, every=None):
    titles = names(language)
    shows = [{"title": titles[i], "cards": 900 - i, "ids": list(ids), "state": "waiting"}
             for i, ids in enumerate(waiting)]
    shows += [{"title": titles[5 + i], "cards": 50, "ids": [], "state": "in"} for i in range(placed)]
    shows += [{"title": titles[8 + i], "cards": 40, "ids": [], "state": "away"} for i in range(away)]
    return {"cards": cards, "all": cards if every is None else every, "shows": shows, "id": "x"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_backlog_is_one_card_naming_the_shows_waiting_and_those_not_on_this_pc(language):
    titles = names(language)
    entries = needs.entries(view(11, 12, 13), backlog=offer(language, waiting=((11, 12), (13,))))
    cards = [e for e in entries if e.kind == needs.BACKLOG_SHOWS]
    assert len(cards) == 1
    card = cards[0]
    assert card.title == ("Your 2,300 new cards come from 4 shows; 3 are on this PC. "
                          "Add the 2 that aren't in your list yet?")
    assert card.say == (f"Waiting in New arrivals: {titles[0]} (900), {titles[1]} (899). "
                        f"Not on this PC: {titles[8]} (40).")
    assert card.actions == ("add_shows", "leave_shows") and card.data["ids"] == [11, 12, 13] and card.data["shows"] == 2
    assert card.unseen and needs.BACKLOG_SHOWS in needs.NO_LATER


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_files_new_arrivals_still_holds_are_offered_and_none_left_is_no_card(language):
    card = next(e for e in needs.entries(view(12), backlog=offer(language)) if e.kind == needs.BACKLOG_SHOWS)
    assert card.data["ids"] == [12]                                     # 11 was placed by hand since
    assert not [e for e in needs.entries(view(99), backlog=offer(language)) if e.kind == needs.BACKLOG_SHOWS]
    assert not [e for e in needs.entries(view(11), backlog=None) if e.kind == needs.BACKLOG_SHOWS]


@pytest.mark.parametrize("language", LANGUAGES)
def test_leave_them_holds_until_another_show_waits(language):
    """The review's MUST 2: *Leave them* answers each show it held — a new episode of a show left, one of its files
    placed by hand, an Undo: still left; another show waiting: asked about that show alone."""
    titles = names(language)
    first = next(e for e in needs.entries(view(11, 12), backlog=offer(language)) if e.kind == needs.BACKLOG_SHOWS)
    answered = frozenset(needs.answer_keys(first))
    assert answered == {needs.behind_key({"title": titles[0]})}

    def card(v, record):
        return [e for e in needs.entries(v, backlog=record, answered=answered) if e.kind == needs.BACKLOG_SHOWS]
    assert not card(view(11, 12), offer(language))
    assert not card(view(11, 12, 14), offer(language, waiting=((11, 12, 14),)))     # a new episode of it
    assert not card(view(12), offer(language))                                       # one placed by hand
    again = card(view(11, 12, 13), offer(language, waiting=((11, 12), (13,))))
    assert len(again) == 1 and again[0].key != first.key and again[0].unseen
    assert again[0].data["ids"] == [13] and again[0].data["left"] == [needs.behind_key({"title": titles[1]})]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_sentence_counts_right_for_one_some_and_none(language):
    assert needs.backlog_head(offer(language, waiting=(), away=0, placed=1)) == \
        "Your 2,300 new cards come from 1 show, on this PC."
    assert needs.backlog_head(offer(language, waiting=(), away=1, placed=0)) == \
        "Your 2,300 new cards come from 1 show, not on this PC."
    assert needs.backlog_head(offer(language, waiting=((11,),), away=2, placed=0)) == \
        "Your 2,300 new cards come from 3 shows; one is on this PC."
    assert needs.backlog_head(offer(language, waiting=(), away=3, placed=0)) == \
        "Your 2,300 new cards come from 3 shows; none of them is on this PC."
    assert needs.backlog_head(offer(language, every=2302)).startswith("2,300 of your new cards come from")
    assert needs.backlog_head(offer(language, cards=1, waiting=(), away=0)) == \
        "Your new card comes from 1 show, on this PC."


def test_the_last_offer_is_read_only_for_the_saved_deck_and_none_without_junban(monkeypatch):
    """The review's SHOULD 7: no deck saved, 順 off, an offer for another deck (setup's page looked at one never
    saved), or no 順 in this Surasura: no card."""
    import sys
    import types
    kept = {"deck": "Mining", "shows": [], "cards": 1, "all": 1}
    fake = types.ModuleType("modules.junban.backlog_shows")
    fake.offer = lambda language, deck=None: kept if deck in (None, kept["deck"]) else None
    # the module stood in, its packages too (GitHub's checkout has no private modules/ at all)
    parent = sys.modules.get("modules.junban") or types.ModuleType("modules.junban")
    monkeypatch.setitem(sys.modules, "modules", sys.modules.get("modules") or types.ModuleType("modules"))
    monkeypatch.setitem(sys.modules, "modules.junban", parent)
    monkeypatch.setattr(parent, "backlog_shows", fake, raising=False)
    monkeypatch.setitem(sys.modules, "modules.junban.backlog_shows", fake)
    assert needs.backlog_offer("ja", {"junban_deck": "Mining"}) == kept
    assert needs.backlog_offer("ja", {"junban_deck": "Other"}) is None
    assert needs.backlog_offer("ja", {}) is None
    assert needs.backlog_offer("ja", {"junban_deck": "Mining", "enable_junban": False}) is None
    monkeypatch.delattr(parent, "backlog_shows")                                  # 順 not in this Surasura
    monkeypatch.setitem(sys.modules, "modules.junban.backlog_shows", None)
    assert needs.backlog_offer("ja", {"junban_deck": "Mining"}) is None
