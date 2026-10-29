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
    assert card.actions == ("add_shows", "leave_shows") and card.data == {"ids": [11, 12, 13], "shows": 2}
    assert card.unseen and needs.BACKLOG_SHOWS in needs.NO_LATER


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_files_new_arrivals_still_holds_are_offered_and_none_left_is_no_card(language):
    card = next(e for e in needs.entries(view(12), backlog=offer(language)) if e.kind == needs.BACKLOG_SHOWS)
    assert card.data["ids"] == [12]                                     # 11 was placed by hand since
    assert not [e for e in needs.entries(view(99), backlog=offer(language)) if e.kind == needs.BACKLOG_SHOWS]
    assert not [e for e in needs.entries(view(11), backlog=None) if e.kind == needs.BACKLOG_SHOWS]


@pytest.mark.parametrize("language", LANGUAGES)
def test_leave_them_holds_until_another_show_waits(language):
    first = next(e for e in needs.entries(view(11, 12), backlog=offer(language)) if e.kind == needs.BACKLOG_SHOWS)
    answered = frozenset({first.key})
    assert not [e for e in needs.entries(view(11, 12), backlog=offer(language), answered=answered)
                if e.kind == needs.BACKLOG_SHOWS]
    more = offer(language, waiting=((11, 12), (13,)))
    again = [e for e in needs.entries(view(11, 12, 13), backlog=more, answered=answered)
             if e.kind == needs.BACKLOG_SHOWS]
    assert len(again) == 1 and again[0].key != first.key and again[0].unseen


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


def test_the_last_offer_is_read_only_through_the_module_and_none_without_it(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "modules.junban.backlog_shows", None)        # 順 not in this Surasura
    assert needs.backlog_offer("ja") is None
