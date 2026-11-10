# SPDX-License-Identifier: GPL-3.0-or-later
"""*Study its cards first* in the planner (P2.2 rows 2.2.1–2.2.2; E1.1 03 §8; G1.6-10).

The user's own pin is the only pin there is: a finished show they still want to work through. What these tests hold
still is the promise behind the button — its still-new cards go first, group by group in the order the pins were made,
each group in Junban's own order — and that nothing else moves: an unpinned plan is the plan it always was, row for
row, and a pinned card is never "not on your list" (its show's words leave the list once it's finished).

Real Japanese words from the shipped export (`tests/Test Resources/ja/expected_output.csv`, row index = rank) and the
words a learner mines by hand; no Anki, no files beyond that one read.
"""
import csv
import os

import pytest

from modules.junban import spaced, unlisted
from modules.junban.plan import Placement, plan, replan

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RESOURCE_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")

# Words a learner mines from a show of their own that the export doesn't rank (proper nouns, everyday words).
_SHOW_WORDS = ["須藤", "引きずる", "冒険", "鳥取", "美術館", "新幹線"]


@pytest.fixture(scope="module")
def ranked():
    """The export's first words, in Surasura's order."""
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        words = [(row.get("Word") or "").strip() for row in csv.DictReader(handle)]
    words = [w for w in dict.fromkeys(words) if w]
    assert not set(_SHOW_WORDS) & set(words), "the fixture's show words must stay unranked"
    return words[:12]


def _card(card_id, due, word, card_type=0, queue=0):
    return {"card_id": card_id, "due": due, "type": card_type, "queue": queue, "word": word, "deck": "TheBank",
            "note": card_id + 1000}


@pytest.fixture
def deck(ranked):
    """Twelve ranked cards (ids 1–12, in reverse of their rank, so the plan has work to do) and six cards of a show
    the list no longer ranks (ids 21–26), all new; plus a review card of the show (id 30) and a suspended one (31)."""
    cards = [_card(i + 1, 3000 + (12 - i), word) for i, word in enumerate(ranked)]
    cards += [_card(21 + i, 2000 + i, word) for i, word in enumerate(_SHOW_WORDS)]
    cards += [_card(30, 140, "冒険", card_type=2, queue=2), _card(31, 3100, "鳥取", queue=-1)]
    rank_of = {word: rank for rank, word in enumerate(ranked)}
    return cards, rank_of


def _ids(stats):
    return [row.card_id for row in stats["order"]]


def test_no_pin_is_the_plan_it_always_was(deck):
    """None, an empty list and empty groups all give today's writes and rows exactly — no `pinned` count, no row
    marked — so 2.x, where nothing is pinned, changes nothing (E1.3-3)."""
    cards, rank_of = deck
    before = plan(cards, rank_of)
    for pins in (None, [], [[]], [[], []]):
        writes, stats = plan(cards, rank_of, pins=pins)
        assert writes == before[0]
        assert stats == before[1]
        assert "pinned" not in stats
        assert all(row.pinned is None for row in stats["order"])


def test_a_pinned_shows_new_cards_go_first_in_junbans_own_order(deck):
    """The show's cards jump the whole list, keeping among themselves the order Junban gave them; everything else
    keeps its planned order behind them; the block keeps its span (it starts at min(due), as always)."""
    cards, rank_of = deck
    _writes, plain = plan(cards, rank_of)
    show = [23, 21, 25]
    writes, stats = plan(cards, rank_of, pins=[show])
    planned = _ids(plain)
    expected_first = [i for i in planned if i in show]
    assert _ids(stats)[:3] == expected_first
    assert _ids(stats)[3:] == [i for i in planned if i not in show]
    assert [row.pinned for row in stats["order"][:3]] == [0, 0, 0]
    assert all(row.pinned is None for row in stats["order"][3:])
    assert stats["pinned"] == 3
    assert stats["order"][0].position == min(c["due"] for c in cards if c["type"] == 0 and c["queue"] == 0)
    assert writes and all(isinstance(due, int) for _cid, due in writes)


def test_groups_go_oldest_pin_first_and_a_card_claimed_twice_goes_with_the_older(deck):
    """E1.3-1: the oldest pin first; a card two pins both claim belongs to the older one."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, pins=[[24, 22], [22, 3, 26]])
    order = _ids(stats)
    assert set(order[:2]) == {22, 24}
    assert set(order[2:4]) == {3, 26}
    assert {row.card_id: row.pinned for row in stats["order"][:4]} == {22: 0, 24: 0, 3: 1, 26: 1}


def test_only_still_new_cards_move_and_a_review_or_suspended_card_is_never_touched(deck):
    """A pin is about cards still to learn: the show's review card (30) and suspended one (31) stay out of every
    write, however the pin names them (I1 / I2)."""
    cards, rank_of = deck
    writes, stats = plan(cards, rank_of, pins=[[30, 31, 21]])
    assert {cid for cid, _due in writes}.isdisjoint({30, 31})
    assert _ids(stats)[0] == 21
    assert stats["pinned"] == 1


def test_a_card_the_user_clicked_off_stays_off_but_stays_a_member(deck):
    """The click wins: a pinned card the user deselected in 順's preview isn't lifted — it keeps its place at the back
    — yet it stays its pin's member, so no "not on your list" action ever reaches it (no tag-suspend-unsuspend flip
    from run to run)."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, exclude={22}, pins=[[21, 22]])
    rows = {row.card_id: row for row in stats["order"]}
    assert _ids(stats)[0] == 21
    assert _ids(stats).index(22) > 0 and rows[22].pinned == 0
    assert stats["pinned"] == 1
    later = unlisted.plan(stats["order"], {}, "ja", {}, {}, {"tag": True, "flag": True, "suspend": True},
                          parent="Surasura", exclude=set(), taken_off={22})
    assert 21 not in later["suspend"] and 22 not in later["suspend"]


def test_a_click_replan_keeps_the_pinned_cards_first_as_the_run_will(deck, ranked):
    """順's preview re-plans after a click from its own rows (WP-O): the pins ride on the rows, so the preview after
    the click is what the run (which reads the pins again) will write (I5)."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, pins=[[25, 21], [2]])
    clicked = 5
    by_rows = replan(stats["order"], exclude={clicked})
    by_run = plan(cards, rank_of, exclude={clicked}, pins=[[25, 21], [2]])
    assert by_rows[0] == by_run[0]
    assert _ids(by_rows[1]) == _ids(by_run[1])
    assert [r.pinned for r in by_rows[1]["order"]] == [r.pinned for r in by_run[1]["order"]]


def test_on_the_spaced_ladder_the_pinned_run_takes_the_front(deck):
    """With E2.1's numbers the partitioned order is what gets numbered: the pinned cards hold the lowest numbers and
    the order is strictly increasing, inside Anki's limit."""
    cards, rank_of = deck
    numbering = spaced.Numbering(floor=None)
    _w, stats = plan(cards, rank_of, number=numbering, pins=[[26, 24]])
    positions = [row.position for row in stats["order"]]
    assert positions == sorted(positions) and len(set(positions)) == len(positions)
    assert {row.card_id for row in stats["order"][:2]} == {24, 26}
    assert positions[-1] <= 999_999


def test_garbage_pins_are_no_pins(deck):
    """Anything that isn't a list of groups of real card ids is no pin: text, booleans, floats, None in a group."""
    cards, rank_of = deck
    before = plan(cards, rank_of)
    assert plan(cards, rank_of, pins=["21", [True, 2.0, None, "21"]]) == before


def _row(card_id, word, tier, pinned=None):
    return Placement(position=2800 + card_id, card_id=card_id, due=2800, word=word, rank=None, deck="TheBank",
                     changed=False, note_id=card_id + 1000, tier=tier, sort=(), why="", pinned=pinned)


def test_a_pinned_card_is_never_not_on_your_list():
    """Tag, flag and suspend all pass a pinned card by — the show was finished, so its words left the list — while
    the same card unpinned is acted on as before."""
    marks = {"散歩": frozenset()}
    opts = {"tag": True, "flag": True, "suspend": True}
    rows = [_row(1, "須藤", "rest", pinned=0), _row(2, "鳥取", "rest"), _row(3, "冒険", "rest", pinned=1)]
    planned = unlisted.plan(rows, marks, "ja", {}, {}, opts, parent="Surasura")
    assert planned["suspend"] == [2]
    assert set(planned["note_of"]) == {2}
    # taken off the list by a click and pinned can't both be (a click unpins), but a pinned row still wins
    assert unlisted.plan(rows, marks, "ja", {}, {}, opts, parent="Surasura", taken_off={1})["suspend"] == [2]
