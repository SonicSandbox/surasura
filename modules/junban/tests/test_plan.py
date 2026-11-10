# SPDX-License-Identifier: GPL-3.0-or-later
"""The planner — where a bug costs the user their schedule rather than a bad reel.

Two failure modes drive this file, and neither announces itself:

  * **A review card gets repositioned.** Nothing errors. `due` on a review card is a day number, so
    the card is silently rescheduled to a garbage date, the change syncs to AnkiWeb and mobile, and
    Anki offers no undo (`setSpecificValueOfCard` hardcodes `skip_undo_entry=True`). The 8 matched
    review cards in the fixture below are the case that matters: they *look* exactly like work to
    do, because the priority list ranks their words.
  * **The block moves.** Positions that start at 1 instead of the existing minimum quietly promote
    this deck in front of every other one.

So the fixture mirrors the real test deck on the user's machine rather than a toy: deck `TheBank`,
**152 new + 17 review**, 8 of the reviews matched, words taken from a real Surasura export
(`tests/Test Resources/ja/expected_output.csv` — row index *is* the rank, exactly as
`priority_learning_list.csv` is read) so the match index is real linguistic data and not ASCII
stand-ins (`testing.md` §1). Review dues are day numbers an order of magnitude below the new-card
positions, which is what makes `min()` over the wrong set visible rather than plausible.

Nothing here touches Anki, the network or the filesystem beyond that one read-only fixture CSV.
"""
import csv
import os
import random

import pytest

from modules.junban.plan import plan, replan, with_answers

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RESOURCE_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")

# Real Japanese words that the fixture export does NOT rank — proper nouns, place names and ordinary
# vocabulary of the kind a learner mines indiscriminately with anki_miner. The fixtures assert this,
# so the day the resource CSV changes the suite says so instead of quietly testing nothing.
_UNRANKED_WORDS = ["須藤", "引きずる", "冒険", "鳥取", "美術館", "新幹線",
                   "味噌汁", "提出", "洗濯機", "駐車場", "自転車", "夕焼け"]   # (眼鏡: 蜘蛛の糸 says it, Hon-SM)


def _card(card_id, due, word, deck="TheBank", card_type=0, queue=0):
    """One `cardsInfo` row, reduced to the seven keys the planner is given. The note id is real
    data, not optional: a fixture without it let `replan` drop it unnoticed."""
    return {"card_id": card_id, "due": due, "type": card_type, "queue": queue,
            "word": word, "deck": deck, "note": card_id - 80000}


@pytest.fixture(scope="module")
def priority_rows():
    """`(Word, Orth)` per row of a real export, in the order Surasura ranks them."""
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        return [((row.get("Word") or "").strip(), (row.get("Orth") or "").strip())
                for row in csv.DictReader(handle)]


@pytest.fixture(scope="module")
def rank_of(priority_rows):
    """`{word: rank}` built the way WP-D specifies: `Orth` first, then `Word`, never overwriting a
    better (lower) rank. Row index is the rank because the file is already in learn order."""
    index = {}
    for rank, (word, orth) in enumerate(priority_rows):
        for key in (orth, word):
            if key and key not in index:
                index[key] = rank
    assert len(index) > 100, "the fixture export should give a realistically sized match index"
    return index


@pytest.fixture(scope="module")
def ranked_words(priority_rows, rank_of):
    """Distinct words the index ranks, in rank order — the pool the matched cards are drawn from."""
    seen = []
    for word, orth in priority_rows:
        key = orth or word
        if key and key not in seen:
            seen.append(key)
    return seen


@pytest.fixture
def the_bank(rank_of, ranked_words):
    """`TheBank`: 152 new cards (40 of them matched) + 17 review cards, 8 of them matched.

    New-card dues are scrambled with a fixed seed so the existing queue order deliberately disagrees
    with the priority order — a fixture already in the right order would let a planner that does
    nothing pass most of this file.
    """
    assert all(word not in rank_of for word in _UNRANKED_WORDS), \
        "the 'unmatched' words must genuinely be absent from the fixture export"

    matched_words = ranked_words[:40]
    unmatched_words = [_UNRANKED_WORDS[i % len(_UNRANKED_WORDS)] for i in range(112)]
    new_words = matched_words + unmatched_words
    assert len(new_words) == 152

    # Positions the user's backlog already occupies. Shuffled onto the words, not assigned in order.
    dues = list(range(2801, 2801 + 152))
    random.Random(7).shuffle(dues)
    new_cards = [_card(1789712080000 + i, dues[i], word) for i, word in enumerate(new_words)]

    # The case the whole invariant exists for: review cards whose words the list ranks. Their `due`
    # is a day number (~120), far below any queue position here, so a planner that let them into
    # `min()` would produce a visibly wrong base rather than a plausible one.
    review_words = ranked_words[40:48] + _UNRANKED_WORDS[:9]
    review_cards = [_card(1789712090000 + i, 120 + i, word, card_type=2, queue=2)
                    for i, word in enumerate(review_words)]
    assert sum(1 for c in review_cards if c["word"] in rank_of) == 8
    assert len(review_cards) == 17

    return new_cards + review_cards


def _new_cards(cards):
    return [c for c in cards if c["type"] == 0 and c["queue"] == 0]


# --- the invariants ------------------------------------------------------------------------------- #
def test_review_cards_are_never_repositioned(the_bank, rank_of):
    """I1. The 8 review cards the priority list DOES rank must still produce zero writes — being
    matched is not permission to move; being new is."""
    writes, stats = plan(the_bank, rank_of)

    reviews = [c for c in the_bank if c["type"] != 0]
    matched_reviews = [c for c in reviews if c["word"] in rank_of]
    assert len(matched_reviews) == 8, "the fixture must keep exercising the matched-review case"

    written_ids = {card_id for card_id, _due in writes}
    assert not (written_ids & {c["card_id"] for c in reviews}), \
        "a review card was repositioned — this silently reschedules it to a garbage date"
    assert stats["skipped_review"] == 17
    assert stats["considered"] == 152
    # And their day-number dues must not have dragged the block's starting position down with them.
    assert stats["base"] == min(c["due"] for c in _new_cards(the_bank))


def test_suspended_cards_are_never_repositioned(the_bank, rank_of):
    """I2. Suspending is a deliberate act. A suspended card is still `type == 0`, so only the queue
    check catches it — and a suspended *review* card is reported as suspended, the reason the user
    would recognise."""
    suspended_new = [_card(1789712099001, 2500, "極楽", queue=-1),
                     _card(1789712099002, 2501, "御釈迦様", queue=-1)]
    suspended_review = [_card(1789712099003, 130, "血の池", card_type=2, queue=-1)]
    assert all(c["word"] in rank_of for c in suspended_new + suspended_review), \
        "suspended cards must be MATCHED ones, or this proves nothing"

    writes, stats = plan(the_bank + suspended_new + suspended_review, rank_of)

    written_ids = {card_id for card_id, _due in writes}
    assert not (written_ids & {c["card_id"] for c in suspended_new + suspended_review})
    assert stats["skipped_suspended"] == 3
    assert stats["considered"] == 152, "the suspended cards must not join the repositioned block"
    # Their dues (2500, 2501) are below every live position; the base must ignore them too.
    assert stats["base"] == min(c["due"] for c in _new_cards(the_bank))


def test_a_learning_card_is_not_repositioned(rank_of):
    """`type == 1` is a card already part-way through learning; `is:new` excludes it, and so must
    the per-card re-check that backs that query up."""
    cards = [_card(1, 2800, "極楽"),
             _card(2, 2801, "御釈迦様", card_type=1, queue=1),
             _card(3, 2802, "血の池")]
    writes, stats = plan(cards, rank_of)

    assert 2 not in {card_id for card_id, _due in writes}
    assert stats["skipped_review"] == 1
    assert stats["considered"] == 2


def test_a_buried_card_is_not_repositioned(rank_of):
    """Buried (`queue` -2/-3) is temporary, but it is still not in the new queue and still not
    ours to move. It is counted apart from suspended so the panel's counts stay honest."""
    cards = [_card(1, 2800, "極楽"), _card(2, 2801, "御釈迦様", queue=-2)]
    writes, stats = plan(cards, rank_of)

    assert [card_id for card_id, _due in writes] == []
    assert stats["skipped_other"] == 1
    assert stats["skipped_suspended"] == 0


# --- the ordering --------------------------------------------------------------------------------- #
def test_unmatched_cards_keep_their_relative_order_at_the_back(the_bank, rank_of):
    """Unmatched cards are not a bucket to shuffle: the list simply says nothing about them, so they
    keep the order the user already had, behind every card it does rank."""
    _writes, stats = plan(the_bank, rank_of)
    rows = stats["order"]

    ranks = [row.rank for row in rows]
    first_unmatched = ranks.index(None)
    assert all(r is None for r in ranks[first_unmatched:]), \
        "a matched card appeared after an unmatched one"
    assert first_unmatched == stats["matched"] == 40

    unmatched_cards = [c for c in _new_cards(the_bank) if c["word"] not in rank_of]
    expected = [c["card_id"] for c in sorted(unmatched_cards, key=lambda c: (c["due"], c["card_id"]))]
    assert [row.card_id for row in rows[first_unmatched:]] == expected


def test_matched_cards_come_out_in_surasura_rank_order(the_bank, rank_of):
    """The point of the whole module: the head of the queue is the priority list's order."""
    _writes, stats = plan(the_bank, rank_of)
    matched_ranks = [row.rank for row in stats["order"] if row.rank is not None]

    assert matched_ranks == sorted(matched_ranks)
    assert matched_ranks[0] == min(rank_of[c["word"]] for c in _new_cards(the_bank)
                                   if c["word"] in rank_of)


def test_duplicate_cards_of_one_word_land_consecutively(rank_of):
    """The clustering promise. Three cards of 極楽, mined months apart and scattered through the
    backlog, share a rank — so `due` only breaks their tie and they arrive together, which is the
    behaviour the user explicitly asked for."""
    rouba = [_card(10, 2900, "極楽"), _card(11, 2802, "極楽"), _card(12, 2999, "極楽")]
    others = [_card(20, 2801, "御釈迦様"), _card(21, 2803, "血の池"), _card(22, 2804, "栗")]
    assert all(c["word"] in rank_of for c in rouba + others)

    _writes, stats = plan(rouba + others, rank_of)
    positions = sorted(row.position for row in stats["order"] if row.word == "極楽")

    assert positions == list(range(positions[0], positions[0] + 3)), \
        f"the three 極楽 cards were split apart: {positions}"
    # ...and within the cluster, the card that was already earliest in the queue stays earliest.
    cluster = [row for row in stats["order"] if row.word == "極楽"]
    assert [row.card_id for row in cluster] == [11, 10, 12]


def test_positions_are_a_contiguous_block_from_the_existing_minimum(the_bank, rank_of):
    """The block occupies exactly the span of positions it already occupied. Starting from 1 would
    hoist this deck in front of every deck the user deliberately left behind."""
    _writes, stats = plan(the_bank, rank_of)

    base = min(c["due"] for c in _new_cards(the_bank))
    assert stats["base"] == base
    assert [row.position for row in stats["order"]] == list(range(base, base + 152))


def test_no_two_cards_share_a_due(the_bank, rank_of):
    """A total order, with no ties left for Anki to break however it likes."""
    _writes, stats = plan(the_bank, rank_of)
    positions = [row.position for row in stats["order"]]

    assert len(set(positions)) == len(positions)


def test_two_cards_sharing_a_position_are_separated_deterministically(rank_of):
    """Anki permits two new cards at the same position, and `findCards` returns `SortOrder.NoOrder`.
    Without the card-id tiebreak the output would depend on that arbitrary order."""
    cards = [_card(200, 2801, "須藤"), _card(100, 2801, "鳥取")]
    writes_a, stats_a = plan(cards, rank_of)
    writes_b, stats_b = plan(list(reversed(cards)), rank_of)

    assert writes_a == writes_b
    # The lower card id takes the earlier position, whichever way round they arrived. Only the
    # card that actually moves is written — the other is already where it belongs.
    assert [row.card_id for row in stats_a["order"]] == [100, 200]
    assert [row.card_id for row in stats_b["order"]] == [100, 200]
    assert writes_a == [(200, 2802)]


def test_the_result_does_not_depend_on_the_order_cards_arrive_in(the_bank, rank_of):
    """Same reason: `findCards` is called with no sort order, so the input sequence is meaningless
    and must not leak into the output."""
    shuffled = list(the_bank)
    random.Random(11).shuffle(shuffled)

    assert plan(the_bank, rank_of)[0] == plan(shuffled, rank_of)[0]


def test_rank_zero_is_a_match_not_a_miss(rank_of):
    """Rank 0 is the most important card in the library and is falsy — a truth test instead of an
    `is None` check would banish it to the unmatched block at the back."""
    top = next(word for word, rank in rank_of.items() if rank == 0)
    _writes, stats = plan([_card(1, 2801, top), _card(2, 2802, "須藤")], rank_of)

    assert stats["matched"] == 1
    assert stats["order"][0].word == top and stats["order"][0].rank == 0


def test_a_card_is_ranked_by_the_list_key_its_word_reached(rank_of, ranked_words):
    """`key` is what `anki_match.lookup` found — a spelling the content used, or the kana fold. The
    card is ranked by it, and the preview still shows the card's OWN word."""
    target = ranked_words[3]
    _writes, stats = plan([_card(1, 2801, "須藤"), _card(2, 2802, "見とれる") | {"key": target}],
                          rank_of)

    assert stats["matched"] == 1
    first = stats["order"][0]
    assert first.word == "見とれる" and first.rank == rank_of[target]


def _placed(card_id, due, word, sort, tier=None, key=None):
    card = _card(card_id, due, word)
    card["sort"] = sort
    if tier:
        card["tier"] = tier
    if key:
        card["key"] = key
    return card


def test_a_word_the_list_cut_off_is_placed_among_the_list_words_by_the_journey(rank_of, ranked_words):
    """Junban_Backlog_Spec §11.1, the user's D7: the cards Surasura can place follow the journey, so
    a library word first met in file 1 with a higher score than a listed file-1 word goes before
    it — one order, not "the list, then the rest". `sort` is the caller's journey key."""
    a, b = ranked_words[0], ranked_words[1]
    cards = [_placed(1, 2804, b, (2, -90, -20, 0, rank_of[b])),
             _placed(2, 2803, "引きずる", (1, -30, -3, 1, 0), tier="library"),
             _card(3, 2802, "須藤"),
             _placed(4, 2801, a, (1, -50, -10, 0, rank_of[a]))]

    _writes, stats = plan(cards, rank_of)

    assert [row.word for row in stats["order"]] == [a, "引きずる", b, "須藤"]
    assert [row.tier for row in stats["order"]] == ["list", "library", "list", None]
    assert stats["order"][1].rank is None, "a library word has no list rank"
    assert (stats["matched"], stats["library"], stats["unmatched"]) == (2, 1, 1)


def test_a_library_card_keeps_its_place_through_a_deselection(rank_of, ranked_words):
    """WP-O replans the rows on screen: a library card has no rank, so without its tier and sort
    it would fall to the back on the first click elsewhere."""
    a, b = ranked_words[0], ranked_words[1]
    _writes, stats = plan([_placed(1, 2803, b, (2, -90, -20, 0, rank_of[b])),
                           _placed(2, 2802, "引きずる", (1, -30, -3, 1, 0), tier="library"),
                           _placed(3, 2801, a, (1, -50, -10, 0, rank_of[a]))], rank_of)

    _writes, again = replan(stats["order"], exclude={3})

    assert [row.word for row in again["order"]] == ["引きずる", b, a]
    assert again["order"][0].tier == "library" and again["library"] == 1


def test_every_tier_takes_its_place_and_orders_by_its_own_key(rank_of, ranked_words):
    """§5.4 as the user's answers shaped it: the list's and the library's words as one journey
    (D7), then i+1, then fewest other unknowns, then FreqSort, and the known words last (D3) —
    whatever order the cards arrived in. `replan` reproduces it exactly."""
    top = ranked_words[0]
    cards = [_placed(1, 2806, "終わり", (), tier="known"),
             _placed(2, 2805, "味噌汁", (5000,), tier="rest"),
             _placed(3, 2804, "眼鏡", (2, 4000), tier="multi"),
             _placed(4, 2803, "美術館", (1, 6000), tier="multi"),
             _placed(5, 2802, "冒険", (9000,), tier="i+1"),
             _placed(6, 2801, "引きずる", (1, -30, -3, 1, 0), tier="library"),
             _placed(7, 2800, top, (1, -50, -10, 0, rank_of[top]))]

    _writes, stats = plan(cards, rank_of)

    assert [row.word for row in stats["order"]] == [top, "引きずる", "冒険", "美術館", "眼鏡", "味噌汁",
                                                  "終わり"]
    assert stats["tiers"] == {"list": 1, "library": 1, "phrase": 0, "i+1": 1, "multi": 2, "rest": 1,
                              "known": 1}
    assert stats["order"][0].why == f"list #{rank_of[top] + 1}" and stats["order"][-1].why == "known"
    assert replan(stats["order"])[1]["order"] == stats["order"]


def test_a_known_word_goes_last_even_when_the_list_ranks_it(rank_of, ranked_words):
    """D3: a word the learner already knows goes last whatever else matched it — its list rank too (a
    known だいぶ card reached the loanword ダイブ's row through the kana fold). The known tier places it,
    never its rank, even where its own word is a list key and no `key` is left on the card."""
    top, second = ranked_words[0], ranked_words[1]
    cards = [_placed(1, 2801, top, (), tier="known"),
             _placed(2, 2802, "味噌汁", (5000,), tier="rest"),
             _placed(3, 2803, second, (rank_of[second],))]

    _writes, stats = plan(cards, rank_of)

    assert [row.word for row in stats["order"]] == [second, "味噌汁", top]
    assert (stats["order"][-1].tier, stats["order"][-1].rank, stats["order"][-1].why) == ("known", None, "known")
    assert stats["matched"] == 1 and stats["tiers"]["known"] == 1
    assert replan(stats["order"])[1]["order"] == stats["order"]


def test_a_library_card_without_a_journey_key_is_simply_unplaced(rank_of):
    """A tier with nothing to sort by is not a placement: it keeps its order at the back."""
    _writes, stats = plan([_card(1, 2801, "引きずる") | {"tier": "library"}], rank_of)

    assert stats["order"][0].tier is None and stats["unmatched"] == 1


# --- idempotence ---------------------------------------------------------------------------------- #
def test_second_run_writes_nothing(the_bank, rank_of):
    """Pressing the button twice must be free. Every write is a sync and an un-undoable change, so a
    no-op run has to emit literally nothing rather than rewrite the same values."""
    writes, stats = plan(the_bank, rank_of)
    assert writes, "the fixture must actually require work the first time"
    assert stats["to_write"] == len(writes)

    applied = dict(writes)
    settled = [dict(card, due=applied.get(card["card_id"], card["due"])) for card in the_bank]

    second_writes, second_stats = plan(settled, rank_of)
    assert second_writes == []
    assert second_stats["to_write"] == 0
    assert second_stats["unchanged"] == 152


def test_a_card_already_in_place_is_not_rewritten(rank_of):
    """Partial idempotence: only the pairs that actually change are emitted, so the count the panel
    shows is the number of cards that will move, not the number it looped over."""
    cards = [_card(1, 2801, "極楽"), _card(2, 2803, "御釈迦様"), _card(3, 2802, "血の池")]
    writes, stats = plan(cards, rank_of)

    assert 1 not in {card_id for card_id, _due in writes}, "極楽 ranks first of the three and is already at the base"
    assert stats["to_write"] == len(writes) < 3


# --- empty and degenerate states ------------------------------------------------------------------ #
def test_no_cards_at_all(rank_of):
    """A deck with an empty backlog. `base` is None rather than 0, so nothing downstream can mistake
    "nothing to do" for "start at position zero"."""
    writes, stats = plan([], rank_of)

    assert writes == []
    assert stats["considered"] == 0 and stats["to_write"] == 0
    assert stats["base"] is None
    assert stats["order"] == []


def test_no_new_cards_at_all(the_bank, rank_of):
    """A deck the user has already finished mining through: 17 review cards and nothing new. Nothing
    is written, and the review count is still reported so the panel can say why."""
    reviews = [c for c in the_bank if c["type"] != 0]
    writes, stats = plan(reviews, rank_of)

    assert writes == []
    assert stats["skipped_review"] == 17 and stats["considered"] == 0
    assert stats["base"] is None


def test_zero_matches(rank_of):
    """A backlog the current priority list says nothing about — mined from content not in the
    library, or against a stale list. The cards keep their existing order exactly, so the run is a
    no-op rather than an arbitrary reshuffle."""
    cards = [_card(i, 2800 + i, word) for i, word in enumerate(_UNRANKED_WORDS)]
    writes, stats = plan(cards, rank_of)

    assert stats["matched"] == 0 and stats["unmatched"] == len(_UNRANKED_WORDS)
    assert writes == [], "already in due order, so there is nothing to change"
    assert [row.card_id for row in stats["order"]] == [c["card_id"] for c in cards]


def test_zero_matches_still_normalises_a_gappy_queue(rank_of):
    """The same case with gaps in the positions: order is preserved, but the block is made
    contiguous, which is what guarantees the no-ties property."""
    cards = [_card(1, 2801, "須藤"), _card(2, 2850, "鳥取"), _card(3, 2999, "冒険")]
    writes, stats = plan(cards, rank_of)

    assert [row.position for row in stats["order"]] == [2801, 2802, 2803]
    assert writes == [(2, 2802), (3, 2803)]


def test_every_card_matched(rank_of, ranked_words):
    """No unmatched tail at all — the ideal case, and the one where an off-by-one in the partition
    would be easiest to miss."""
    words = ranked_words[:12]
    cards = [_card(i, 2900 - i, word) for i, word in enumerate(words)]
    _writes, stats = plan(cards, rank_of)

    assert stats["matched"] == 12 and stats["unmatched"] == 0
    assert [row.rank for row in stats["order"]] == sorted(rank_of[w] for w in words)


def test_a_single_card(rank_of):
    """One card cannot move: the only position in the block is the one it already holds."""
    writes, stats = plan([_card(1, 2842, "極楽")], rank_of)

    assert writes == []
    assert stats["base"] == 2842 and stats["order"][0].position == 2842
    assert stats["considered"] == 1 and stats["matched"] == 1


def test_a_word_that_cannot_be_read_is_simply_unmatched(rank_of):
    """`target_word` returns "" for a field that is only an `<img>` — a real shape in this
    collection. That card is not an error and not a match; it keeps its place at the back."""
    cards = [_card(1, 2801, ""), _card(2, 2802, None), _card(3, 2803, "極楽")]
    writes, stats = plan(cards, rank_of)

    assert stats["considered"] == 3 and stats["matched"] == 1 and stats["unmatched"] == 2
    assert dict(writes)[3] == 2801, "the matched card leads; the unreadable ones follow in order"


def test_cards_missing_the_fields_to_decide_on_are_skipped_not_guessed(rank_of):
    """`cardsInfo` keys are version-dependent, so everything is read with `.get()` — and a card that
    cannot supply a real integer `due`, `card_id`, `type` and `queue` is not repositionable. It is
    skipped rather than defaulted, because a guessed `due` is a write to a live collection.

    Booleans are rejected explicitly: `True == 1` and `False == 0` in Python, so a payload carrying
    booleans would otherwise read as a card type (`testing.md` §5.3 — decide against plain data)."""
    cards = [_card(1, 2801, "極楽"),
             _card(2, None, "御釈迦様"),                  # no due
             {"due": 2803, "type": 0, "queue": 0, "word": "血の池"},   # no card_id
             _card(4, 2804, "栗", card_type=False, queue=False),   # booleans, not ints
             _card(5, 2805, "蓮池")]
    writes, stats = plan(cards, rank_of)

    assert {card_id for card_id, _due in writes} <= {1, 5}
    assert stats["considered"] == 2
    assert stats["skipped_other"] + stats["skipped_review"] == 3


def test_stats_account_for_every_card_handed_in(the_bank, rank_of):
    """The panel's counts are the user's only confirmation before an un-undoable write (I5), so they
    have to add up exactly — no card may be silently unaccounted for."""
    _writes, stats = plan(the_bank, rank_of)

    assert stats["total"] == len(the_bank) == 169
    assert stats["considered"] + stats["skipped"] == stats["total"]
    assert stats["matched"] + stats["unmatched"] == stats["considered"]
    assert stats["to_write"] + stats["unchanged"] == stats["considered"]
    assert stats["skipped_review"] + stats["skipped_suspended"] + stats["skipped_other"] == stats["skipped"]


def test_an_empty_rank_index_is_not_a_crash(the_bank):
    """No `priority_learning_list.csv` yet, or one with no usable rows: every card is unmatched and
    the queue keeps its existing order."""
    _writes, stats = plan(the_bank, {})

    assert stats["matched"] == 0 and stats["unmatched"] == 152
    expected = sorted(_new_cards(the_bank), key=lambda c: (c["due"], c["card_id"]))
    assert [row.card_id for row in stats["order"]] == [c["card_id"] for c in expected]


# --- WP-O: rows the user clicked off in the preview ----------------------------------------------- #
def _matched_ids(stats):
    return [row.card_id for row in stats["order"] if row.rank is not None]


def test_nothing_is_excluded_by_default(the_bank, rank_of):
    """Every row starts selected: this is a way to drop one card, not a mode to be turned on.

    `exclude=None` and `exclude=set()` must both give the plan that existed before WP-O, byte for
    byte — the deselect path is the same path, taken with nothing in it."""
    baseline = plan(the_bank, rank_of)
    assert plan(the_bank, rank_of, exclude=None) == baseline
    assert plan(the_bank, rank_of, exclude=set()) == baseline
    assert baseline[1]["deselected"] == 0


def test_a_deselected_card_is_planned_exactly_like_an_unmatched_one(the_bank, rank_of):
    """The whole design of WP-O: deselecting invents no new ordering concept, it stops asking the
    list about that card. So excluding a matched card must give the identical plan to a list that
    never ranked its word — same writes, same order, same positions."""
    _writes, stats = plan(the_bank, rank_of)
    victim = [row for row in stats["order"] if row.rank is not None][7]
    assert sum(1 for c in the_bank if c["word"] == victim.word) == 1, \
        "the comparison only holds while this word is on exactly one card"

    as_deselected = plan(the_bank, rank_of, exclude={victim.card_id})
    without_the_word = plan(the_bank, {w: r for w, r in rank_of.items() if w != victim.word})

    assert as_deselected[0] == without_the_word[0], "the writes must be the same writes"
    assert [row.card_id for row in as_deselected[1]["order"]] == \
           [row.card_id for row in without_the_word[1]["order"]]


def test_deselecting_moves_the_card_to_the_back_and_the_rest_close_up(the_bank, rank_of):
    """The rest renumber immediately and contiguously — no hole where the card was, because the
    block still runs from `min(due)` with one position per card."""
    _writes, before = plan(the_bank, rank_of)
    victim = before["order"][3]

    _writes, after = plan(the_bank, rank_of, exclude={victim.card_id})
    positions = [row.position for row in after["order"]]

    assert positions == list(range(before["base"], before["base"] + len(positions))), \
        "the block must stay contiguous from the same starting position"
    assert _matched_ids(after) == [cid for cid in _matched_ids(before) if cid != victim.card_id]
    moved = [row for row in after["order"] if row.card_id == victim.card_id][0]
    assert moved.rank is None, "a deselected card is rankless, so the touch-ups pass it by"
    assert after["order"].index(moved) >= after["matched"], "it belongs behind every matched card"


def test_toggling_a_card_back_on_restores_the_original_plan(the_bank, rank_of):
    """Deselection is not a one-way door and it leaves nothing behind: the plan with the card put
    back must equal the plan that never lost it, down to the `Placement` tuples."""
    baseline = plan(the_bank, rank_of)
    victim = baseline[1]["order"][11].card_id

    off = plan(the_bank, rank_of, exclude={victim})
    on_again = plan(the_bank, rank_of, exclude=set())

    assert off != baseline, "the fixture must actually be changed by the exclusion"
    assert on_again == baseline


def test_a_deselected_card_keeps_its_place_among_the_unmatched_ones(the_bank, rank_of):
    """"Keeps its existing relative order" is measured against the WHOLE back block, not against a
    bucket of its own. A deselected card sorted behind every unmatched one would be a move the user
    asked for by asking for no move."""
    _writes, stats = plan(the_bank, rank_of)
    victim = [row for row in stats["order"] if row.rank is not None][2]

    _writes, after = plan(the_bank, rank_of, exclude={victim.card_id})
    back = [row for row in after["order"] if row.rank is None]

    assert [row.due for row in back] == sorted(row.due for row in back), \
        "the back block is one block, in the order the user already had"
    assert victim.card_id in {row.card_id for row in back}


def test_deselecting_every_matched_card_is_legal_and_reorders_nothing(the_bank, rank_of):
    """The extreme case, and it must not be a special one: with nothing left for the list to order,
    the queue is its own existing order, and an already contiguous queue means zero writes."""
    _writes, stats = plan(the_bank, rank_of)
    every_matched = set(_matched_ids(stats))
    assert len(every_matched) == 40

    writes, after = plan(the_bank, rank_of, exclude=every_matched)

    assert after["matched"] == 0 and after["deselected"] == 40
    assert writes == [], "the fixture's 152 new cards already occupy a contiguous span"
    expected = sorted(_new_cards(the_bank), key=lambda c: (c["due"], c["card_id"]))
    assert [row.card_id for row in after["order"]] == [c["card_id"] for c in expected]


def test_the_deselected_are_counted_apart_from_the_unmatched(the_bank, rank_of):
    """Two different answers — the list's and the user's — so two numbers. Merging them would report
    the user's own choice back to them as a shortfall, and the counts must still account for every
    card handed in (I5)."""
    _writes, before = plan(the_bank, rank_of)
    victims = set(_matched_ids(before)[:3])

    _writes, after = plan(the_bank, rank_of, exclude=victims)

    assert after["deselected"] == 3
    assert after["unmatched"] == before["unmatched"], "an unmatched card is not 'deselected'"
    assert after["matched"] == before["matched"] - 3
    assert after["matched"] + after["unmatched"] + after["deselected"] == after["considered"]
    assert after["to_write"] + after["unchanged"] == after["considered"]


def test_deselecting_a_card_that_was_already_unmatched_changes_only_the_count(the_bank, rank_of):
    """It was at the back for the list's reasons and it stays there for the user's — the order is
    untouched, and only the number that explains it moves."""
    _writes, before = plan(the_bank, rank_of)
    stranger = [row for row in before["order"] if row.rank is None][5]

    _writes, after = plan(the_bank, rank_of, exclude={stranger.card_id})

    assert [row.card_id for row in after["order"]] == [row.card_id for row in before["order"]]
    assert after["deselected"] == 1 and after["unmatched"] == before["unmatched"] - 1


def test_an_exclusion_naming_a_card_outside_the_scope_changes_nothing(the_bank, rank_of):
    """A stale id is inert rather than an error: the panel drops its deselections with the preview,
    but an id that outlived one must not be able to shift an order it does not name."""
    baseline = plan(the_bank, rank_of)
    assert plan(the_bank, rank_of, exclude={99999999999}) == baseline


def test_a_review_card_cannot_be_deselected_into_the_block(the_bank, rank_of):
    """I1 outranks WP-O. The exclusion is applied AFTER the movable check, so naming a review card
    changes nothing at all — it was never a candidate to be excluded from."""
    reviews = {c["card_id"] for c in the_bank if c["type"] != 0}
    writes, stats = plan(the_bank, rank_of, exclude=reviews)

    assert stats["deselected"] == 0 and stats["skipped_review"] == 17
    assert (writes, stats) == plan(the_bank, rank_of)


# --- WP-O: `replan`, the panel re-planning rows it already has ------------------------------------- #
def test_replan_reproduces_the_planners_own_answer(the_bank, rank_of):
    """The panel cannot read Anki again on every click, so it re-plans the rows it already has. That
    has to be the SAME answer the engine reaches when it re-plans from the collection with the same
    ids excluded, or the preview is a second implementation of the ordering (I5)."""
    _writes, stats = plan(the_bank, rank_of)
    victims = set(_matched_ids(stats)[:4]) | {stats["order"][-1].card_id}

    from_the_panel = replan(stats["order"], victims)
    from_the_engine = plan(the_bank, rank_of, exclude=victims)

    assert from_the_panel[0] == from_the_engine[0], "the writes must agree card for card"
    assert from_the_panel[1]["order"] == from_the_engine[1]["order"]
    for key in ("matched", "unmatched", "deselected", "to_write", "unchanged", "base"):
        assert from_the_panel[1][key] == from_the_engine[1][key], key


def test_replan_with_nothing_excluded_returns_the_plan_it_was_given(the_bank, rank_of):
    """Toggling a row off and on again must leave the table exactly as it was found.

    Including the writes: the rows carry each card's CURRENT `due`, not the position the plan gave
    it, so re-planning them is still measured against the collection as it really stands."""
    original_writes, stats = plan(the_bank, rank_of)

    writes, replanned = replan(stats["order"], set())

    assert replanned["order"] == stats["order"]
    assert writes == original_writes
    assert replanned["to_write"] == stats["to_write"]


def test_replan_keeps_every_cards_note(the_bank, rank_of):
    """Touch-ups are planned per note. Losing the id made the confirmation promise "tag 0 notes"
    after one click while the run tagged them anyway — the confirmation must describe the run."""
    _writes, stats = plan(the_bank, rank_of)
    victim = _matched_ids(stats)[0]
    _writes, replanned = replan(stats["order"], {victim})
    notes = {row.card_id: row.note_id for row in stats["order"]}
    assert replanned["order"], "the fixture should still have rows"
    for row in replanned["order"]:
        assert row.note_id == notes[row.card_id] and row.note_id is not None


def test_replan_of_an_empty_preview_is_not_a_crash():
    """Empty state: a deck with nothing new in it, where a stray keypress still reaches the table."""
    writes, stats = replan([], {1})

    assert writes == [] and stats["order"] == []
    assert stats["considered"] == 0 and stats["base"] is None


# --------------------------------------------------------------------------- #
# §16 — a tick in "Same word as one on your list?", re-planned by the planner itself
# --------------------------------------------------------------------------- #
def _checked_rows():
    """冒険 on the list (#1); 見とれる by its sentence (i+1), offered as 見惚れる (#5); 美術館 by its
    sentence with nothing to offer."""
    cards = [dict(_card(1789712080001, 2802, "美術館"), tier="multi", sort=(1, 6000), why="1 unknown"),
             dict(_card(1789712080002, 2801, "見とれる"), tier="i+1", sort=(12000,), why="i+1",
                  suggestion=("見惚れる", 4, (4,), "list #5 · you matched it")),
             _card(1789712080003, 2800, "冒険")]
    return plan(cards, {"冒険": 0})[1]["order"]


def test_a_ticked_word_takes_the_list_words_place_and_keeps_its_sentences_as_fallback():
    rows = with_answers(_checked_rows(), {"見とれる": True})
    _writes, stats = replan(rows)
    assert [row.word for row in stats["order"]] == ["冒険", "見とれる", "美術館"]
    moved = stats["order"][1]
    assert (moved.tier, moved.rank, moved.why) == ("list", 4, "list #5 · you matched it")
    assert moved.fallback == ("i+1", (12000,), "i+1")
    assert moved.suggestion[0] == "見惚れる", "replan carries it, so it can be unticked again"


def test_unticking_sends_it_back_to_its_sentences_place_and_other_rows_are_untouched():
    ticked = replan(with_answers(_checked_rows(), {"見とれる": True}))[1]["order"]
    _writes, stats = replan(with_answers(ticked, {"見とれる": False}))
    assert [(row.word, row.tier, row.why) for row in stats["order"]] == [
        ("冒険", "list", "list #1"), ("見とれる", "i+1", "i+1"), ("美術館", "multi", "1 unknown")]
    untouched = _checked_rows()
    assert with_answers(untouched, {"美術館": True, "冒険": False}) == untouched,         "a row with nothing to tick is never changed by one"
