# SPDX-License-Identifier: GPL-3.0-or-later
"""Spaced Anki numbers (E1.1 03, E2.1.1): the ladder, the delta, the window rule, the ceiling, request 1.

Everything here is numbers in, numbers out — `spaced.py` is pure, as `plan.py` is — so the proofs run
against plain lists, at the backlog sizes the gap re-run measured (2,000 to 30,000 new cards). What is
guarded, in order of what a mistake would cost the user:

  * **Never a position ≥ 1,000,000 or < 1** (03 §1): Anki's Check Database folds every new position at
    or above 1,000,000, scrambling the order and colliding cards. Every list `number` returns is
    checked; a list that would break it is refused, never written.
  * **Strictly increasing**: two cards on one number leave their order to Anki.
  * **Request 1 is tomorrow's cards** (05 §5): once the first request lands, Anki's first N new cards
    are the plan's first N — every move kind, N ∈ {1, 20, the whole backlog}.
  * **A move writes tens of cards**, and a second run of the same order writes nothing.

The card ids are real Anki magnitudes (`test_reposition.FIRST_CARD`); the words behind them belong to
the run tests (`test_spaced_runs.py`), which number real Japanese cards on the fake collection.
"""
import random
import statistics

import pytest

from modules.junban import spaced
from modules.junban.spaced import CEILING, SpacedError

FIRST_CARD = 1789712080000


def _strict(values):
    return all(b > a for a, b in zip(values, values[1:]))


def _in_bounds(values, base=1):
    return all(base <= value <= CEILING for value in values)


# --------------------------------------------------------------------------- #
# The ladder (a full write)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n", [1, 2, 20, 2000, 30000])
def test_the_ladder_is_strictly_increasing_inside_the_ceiling_and_front_weighted(n):
    base = 3131                                     # E0.1's test deck's lowest new position
    ladder = spaced.layout(n, base)
    assert len(ladder) == n
    assert _strict(ladder) and _in_bounds(ladder, base)
    assert ladder[-1] <= CEILING
    if n >= 3:
        # The front gets the widest gaps: moves to the top and newly mined cards land there.
        assert ladder[1] - ladder[0] > ladder[-1] - ladder[-2]
    # The spec's formula, card for card (03 §2).
    assert ladder[0] == base + int((CEILING - base) * (1 / (n + 1)) ** 0.6)


def test_the_ladder_reproduces_the_gap_re_runs_first_and_last_gaps():
    # E1.1-gap-sim: F-LLg at 2,000 cards from 3,000 had first/last gaps of 5,375 / 300.
    ladder = spaced.layout(2000, 3000)
    assert (ladder[1] - ladder[0], ladder[-1] - ladder[-2]) == (5375, 300)


def test_with_less_room_than_two_numbers_a_card_the_ladder_falls_back_to_dense_numbers():
    base = CEILING - 1999                           # room for 1,999 more numbers: < 2 x 1,000 cards
    assert spaced.layout(1000, base) == list(range(base, base + 1000))
    news, info = spaced.number([base + 3 * i for i in range(1000)])
    assert info["kind"] == spaced.DENSE and news == list(range(base, base + 1000))


def test_dense_numbers_that_would_pass_the_ceiling_are_moved_down_under_it():
    # Cards already numbered past 999,999 (a hand-made order, or a "too high" one from before): the
    # block moves down just enough to end at 999,999 — never one number above it.
    olds = list(range(999_000, 1_001_000, 2))[:1000]
    news, info = spaced.number(olds)
    assert info["kind"] == spaced.DENSE
    assert news[-1] == CEILING and _strict(news) and _in_bounds(news)


def test_more_cards_than_numbers_under_the_ceiling_is_refused_not_written():
    with pytest.raises(SpacedError):
        spaced.number(list(range(1, CEILING + 2)))


def test_a_list_that_breaks_a_bound_never_leaves_the_check():
    for bad in ([5, 5], [3, 2], [0, 4], [1, CEILING + 1], [1.5, 3]):
        with pytest.raises(SpacedError):
            spaced._check(bad, len(bad), CEILING)
    with pytest.raises(SpacedError):
        spaced._check([1, 2], 3, CEILING)               # one number per card, or nothing


# --------------------------------------------------------------------------- #
# The first spaced run, and the delta after it
# --------------------------------------------------------------------------- #
def test_the_first_spaced_run_is_a_full_write_that_changes_every_card_once():
    dense = list(range(3131, 3131 + 2000))          # 2.5's numbers
    news, info = spaced.number(dense)
    assert info["kind"] == spaced.FULL and info["full_rewrite"] and info["base"] == 3131
    assert news == spaced.layout(2000, 3131)
    assert all(new != old for new, old in zip(news, dense))
    # ...and a second run of the same order writes nothing.
    again, info = spaced.number(news)
    assert again == news and info["kind"] == spaced.DELTA and not info["windows"]


def test_the_ladders_bottom_is_kept_so_studying_the_front_never_makes_it_climb():
    # E2.1-1: the front's cards are studied and leave; their numbers are free again for the next move to
    # the top. Taken afresh as the lowest current number, the bottom would climb with every card studied.
    ladder = spaced.layout(2000, 3131)
    studied = ladder[200:]                          # ten days of 20 cards gone from the front
    order = list(range(len(studied)))
    order.insert(0, order.pop(900))                 # a card pulled to the very top
    olds = [studied[i] for i in order]
    kept, info = spaced.number(olds, floor=3131)
    assert info["base"] == 3131 and kept[0] < studied[0]
    assert sum(1 for o, v in zip(olds, kept) if o != v) == 1    # into the room the studied cards left
    climbed, info = spaced.number(olds)             # no record: the lowest current number
    assert info["base"] == studied[0] and min(climbed) >= studied[0]
    # A floor above the cards (stale, or another deck's) never lifts the bottom over them.
    _news, info = spaced.number(olds, floor=studied[0] + 50)
    assert info["base"] == min(olds)


def test_dense_numbers_never_read_as_a_ladder_already_there():
    assert not spaced.is_spaced(list(range(1, 300_001)), 1)          # dense, even reaching past a quarter
    assert not spaced.is_spaced(list(range(500, 2500)), 500)
    assert spaced.is_spaced(spaced.layout(2000, 500), 500)
    assert not spaced.is_spaced([7], 7)


def test_a_card_moved_to_the_top_of_a_ladder_is_the_only_card_written():
    ladder = spaced.layout(2000, 3131)
    order = list(range(2000))
    order.insert(0, order.pop(1500))               # one card, from the middle to the top
    olds = [ladder[i] for i in order]
    news, info = spaced.number(olds, floor=3131)     # the ladder's bottom, kept since its full write
    writes = [i for i, (o, v) in enumerate(zip(olds, news)) if o != v]
    assert writes == [0] and news[0] < news[1] and news[0] >= 3131
    assert info["kind"] == spaced.DELTA and not info["windows"]


def test_a_run_with_no_room_widens_its_window_and_respaces_the_kept_cards_inside_it():
    # Kept neighbours one number apart, three cards to fit between them: no free number, so the window
    # grows and the cards around the run are spread out again too (03 §2, "kept cards inside it are
    # rewritten too").
    region = [3480, 3481, 3482, 3483, 3484]           # five cards on consecutive numbers
    ladder = [3000 + 10 * i for i in range(48)] + region + [3500 + 10 * i for i in range(50)]
    planned = ladder[:48] + [3480, 3483, 3482, 3481, 3484] + ladder[53:]   # three of them reversed
    news, info = spaced.delta(planned, 3000)
    assert _strict(news) and _in_bounds(news, 3000)
    assert info["windows"], "a run with no room must widen"
    rewritten = sum(1 for o, v in zip(planned, news) if o != v)
    assert rewritten > 2                            # more than the run itself: its window was re-spaced


def test_numbers_outside_the_ceiling_are_never_kept():
    olds = [3000, 1_200_000, 5000, 7000]            # one card "too high" (Anki's word) from before
    news, info = spaced.delta(olds, 3000)
    assert news[1] != 1_200_000 and _strict(news) and _in_bounds(news, 3000)
    assert [news[0], news[2], news[3]] == [3000, 5000, 7000]
    # ...even where it would sit in order: last, after every other card.
    news, info = spaced.delta([3000, 5000, 1_200_000], 3000)
    assert news[:2] == [3000, 5000] and 5000 < news[2] <= CEILING


def test_a_numbering_that_breaks_a_bound_is_refused_by_number_itself(monkeypatch):
    # The guard is wired, not only written: whatever a later change to the delta returns, `number`
    # checks it before anyone can write it.
    monkeypatch.setattr(spaced, "delta", lambda olds, base, ceiling=CEILING: (
        [base] * len(olds), {"kind": spaced.DELTA, "windows": [], "full_rewrite": False}))
    with pytest.raises(SpacedError):
        spaced.number(spaced.layout(100, 3000), floor=3000)


def test_a_card_mined_at_ankis_counter_is_placed_by_the_next_delta():
    # E0.1: a mined card lands at Anki's next-position counter, below the ladder; the plan puts it 700th.
    ladder = spaced.layout(2000, 3131)
    olds = ladder[:700] + [5131] + ladder[700:]
    news, info = spaced.number(olds, floor=3131)
    assert info["base"] == 3131 and _strict(news) and _in_bounds(news)
    assert [i for i, (o, v) in enumerate(zip(olds, news)) if o != v] == [700]


# --------------------------------------------------------------------------- #
# The property test: random moves of the study's kinds, every bound, every time
# --------------------------------------------------------------------------- #
def _simulate(n, moves, seed, daily=20, every=20, front=None, firsts=None):
    """The gap re-run's shape, in miniature and without its library: blocks of 20–80 cards (a file's
    words) moved to the top, pulled up from far down, sent to the back and brought back; every
    `every` moves the front `daily` cards are studied and `daily` are mined at Anki's counter, then
    placed where the plan meets them. Returns the writes per reorder after the first (full) run."""
    rng = random.Random(seed)
    order = [FIRST_CARD + i for i in range(n)]
    due = {card: 3131 + i for i, card in enumerate(order)}
    counter, next_id = 3131 + n, FIRST_CARD + n
    news, info = spaced.number([due[card] for card in order])
    assert info["kind"] == spaced.FULL and info["base"] == 3131
    due.update(zip(order, news))
    counts, floor = [], info["base"]

    def reorder():
        olds = [due[card] for card in order]
        new, info = spaced.number(olds, floor=floor, front=front)
        assert len(new) == len(order) and _strict(new) and _in_bounds(new)
        assert min(new) >= 3131 and info["base"] == 3131    # the bottom never moves down, nor climbs
        counts.append(sum(1 for o, v in zip(olds, new) if o != v))
        if firsts is not None:                      # tomorrow's request: its size, and Anki's first N once it lands
            group = spaced.front_group(list(zip(order, olds)), new, front)
            firsts.append((len(group), info["front_first"]))
            state = dict(zip(order, olds))
            state.update(group)
            assert sorted(state, key=lambda card: (state[card], card))[:front] == order[:front]
        due.update(zip(order, new))
        again, _ = spaced.number(new, floor=floor, front=front)  # a second run of the same order writes nothing
        assert again == new

    for move in range(1, moves + 1):
        size = rng.randrange(20, 81)
        kind = rng.choice(("top", "far", "back"))
        if kind == "top":
            start = rng.randrange(0, max(1, min(400, len(order) - size)))
            block, order = order[start:start + size], order[:start] + order[start + size:]
            at = rng.randrange(0, 40)
        elif kind == "far":
            start = rng.randrange(min(len(order) // 2, len(order) - size), len(order) - size)
            block, order = order[start:start + size], order[:start] + order[start + size:]
            at = rng.randrange(0, 30)
        else:
            start = rng.randrange(0, max(1, min(400, len(order) - size)))
            block, order = order[start:start + size], order[:start] + order[start + size:]
            at = len(order) - rng.randrange(0, 40)
        order[at:at] = block
        reorder()
        if move % every == 0:
            studied = set(order[:daily])
            order = order[daily:]
            for card in studied:
                del due[card]
            for _ in range(daily):
                due[next_id] = counter
                order.insert(rng.randrange(len(order) // 4, len(order) // 2), next_id)
                counter, next_id = counter + 1, next_id + 1
            reorder()
    return counts


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_random_moves_keep_every_bound_and_write_tens_of_cards_not_the_backlog(seed):
    counts = _simulate(2000, 300, seed)
    # Dense numbering rewrites ~880 cards a reorder here (E1.1-gap-sim); the ladder writes tens (these
    # blocks of 20–80 cards are rougher than the study's moves). The gap re-run's own figures (median
    # 19, p95 99 at 2,000) are reproduced on its library in As built.
    assert statistics.median(counts) <= 80          # measured 62–64 on these three seeds
    assert statistics.mean(counts) <= 200           # a tenth of the deck; dense numbering rewrites ~880
    assert sorted(counts)[int(0.95 * len(counts))] <= 800   # measured 544–600: a block sent to the back
    assert max(counts) < 2000                       # never the whole backlog again


def test_a_large_backlog_keeps_every_bound_too():
    counts = _simulate(30000, 40, 7)
    assert statistics.median(counts) <= 200


# --------------------------------------------------------------------------- #
# Request 1: tomorrow's cards first (05 §5)
# --------------------------------------------------------------------------- #
def _first_n_after(batches, olds, n, front=None):
    """Anki's first n new cards by position once the front group's requests have landed (`front`: how
    many requests it took; one by default). A tie straddling the cut would be Anki's to order: the
    sort by card id here would hide it, so `_no_tie_at_the_cut` checks that apart."""
    state = dict(olds)
    for batch in batches[:front or 1]:
        for card, new in batch:
            state[card] = new
    return [card for card, _due in sorted(state.items(), key=lambda pair: (pair[1], pair[0]))][:n]


def _front_requests(planned, olds, news, n, chunk):
    group = spaced.front_group(list(zip(planned, olds)), news, n)
    return -(-len(group) // chunk) if group else 0


def _moves(cards):
    """Every move kind the study names, as (name, planned order)."""
    within_top = cards[:5] + [cards[7]] + cards[5:7] + cards[8:]
    far_up = [cards[1500]] + cards[:1500] + cards[1501:]
    block_up = cards[1200:1260] + cards[:1200] + cards[1260:]
    to_back = cards[40:] + cards[:40]
    back_up = cards[-30:] + cards[:-30]
    reverse = cards[:10][::-1] + cards[10:]
    return [("within the top", within_top), ("one far card to the top", far_up),
            ("a file's 60 words pulled up", block_up), ("the top 40 sent to the back", to_back),
            ("the back brought to the top", back_up), ("a move's reverse", reverse),
            ("nothing moved", list(cards))]


@pytest.mark.parametrize("front", [1, 20, None])
def test_after_request_1_ankis_first_n_new_cards_are_the_plans_first_n(front):
    cards = [FIRST_CARD + i for i in range(2000)]
    ladder = spaced.layout(2000, 3131)
    current = dict(zip(cards, ladder))
    for name, planned in _moves(cards):
        n = len(planned) if front is None else front
        olds = [current[card] for card in planned]
        news, _info = spaced.number(olds)
        batches = spaced.requests(list(zip(planned, olds)), news, n, 150)
        if not batches:
            assert news == olds, name
            continue
        front_requests = _front_requests(planned, olds, news, n, 150)
        assert _first_n_after(batches, current, n, front=front_requests) == planned[:n], name
        # Every write is a changed card, once, each request in new-position order, the rest chunked.
        written = [pair for batch in batches for pair in batch]
        assert len({card for card, _ in written}) == len(written) == sum(1 for o, v in zip(olds, news) if o != v)
        old_of = dict(zip(planned, olds))
        for batch in batches:                     # inside each group: back first, then forward (review 2 #1)
            back = [new for card, new in batch if new > old_of[card]]
            forward = [new for card, new in batch if new < old_of[card]]
            assert [new for _card, new in batch] == sorted(back, reverse=True) + sorted(forward), name
        assert all(len(batch) <= 150 for batch in batches), name


def test_request_1_holds_for_the_first_spaced_run_and_for_cards_mined_at_the_front():
    cards = [FIRST_CARD + i for i in range(500)]
    dense = dict(zip(cards, range(3131, 3631)))
    planned = cards[250:] + cards[:250]
    olds = [dense[card] for card in planned]
    news, info = spaced.number(olds)
    assert info["kind"] == spaced.FULL
    batches = spaced.requests(list(zip(planned, olds)), news, 20, 150)
    # The first spaced run's front group is the whole deck (every old number is under the ladder's 20th):
    # four requests of 150, never one of 500 (review #1) — and the guarantee holds after the fourth.
    assert [len(batch) for batch in batches] == [150, 150, 150, 50]
    assert _first_n_after(batches, dense, 20, front=4) == planned[:20]
    # A card mined at Anki's counter, below the whole ladder, that the plan puts 300th: pushed out in
    # request 1, so it is not studied first tomorrow.
    ladder = dict(zip(planned, news))
    mined = FIRST_CARD + 9999
    ladder[mined] = 3631
    planned2 = planned[:300] + [mined] + planned[300:]
    olds2 = [ladder[card] for card in planned2]
    news2, _ = spaced.number(olds2)
    batches2 = spaced.requests(list(zip(planned2, olds2)), news2, 20, 150)
    assert (mined, news2[300]) in batches2[0]
    assert _first_n_after(batches2, ladder, 20) == planned2[:20]


def test_a_card_tied_with_tomorrows_last_number_is_pushed_out_in_request_1():
    # Two cards on one number (Anki allows it): the one the plan puts later must not stay level with
    # the front's last card, or Anki could show it among tomorrow's.
    planned = [101, 102, 103]
    olds = [10, 20, 30]
    news = [10, 30, 40]                                 # card 102 takes 30, which card 103 holds now
    batches = spaced.requests(list(zip(planned, olds)), news, 2, 150)
    assert sorted(batches[0]) == [(102, 30), (103, 40)]


def test_nothing_changed_is_no_request_at_all():
    assert spaced.requests([(1, 10), (2, 20)], [10, 20], 20, 150) == []


def test_the_front_is_the_decks_new_cards_a_day_never_fewer_than_20():
    assert spaced.front_size(None) == 20
    assert spaced.front_size(10) == 20
    assert spaced.front_size(50) == 50
    assert spaced.front_size(True) == 20                # a bool is not a count


def test_the_ceiling_is_the_one_e0_1_measured():
    # Check Database folds every new position >= 1,000,000 (E0.1): the ceiling is a measured number,
    # not a tunable — a change here is a change to what Anki keeps.
    assert CEILING == 999_999 and spaced.FLOOR == 1
    assert max(spaced.layout(30000, 1)) <= 999_999


def test_the_window_bar_is_list_labellings_graded_threshold():
    # max(2, (g/2)^(log w / log n)): a small window may stay denser than a large one; the whole ladder
    # needs half its average gap.
    half = 249.5
    assert spaced._bar(1, 2000, half) == 2.0
    assert spaced._bar(2000, 2000, half) == pytest.approx(half)
    assert 2.0 < spaced._bar(50, 2000, half) < spaced._bar(500, 2000, half) < half


def test_numbering_30000_cards_stays_far_inside_the_plans_budget():
    # 03 §4: plan() at 30,000 cards ~200 ms on the worker; the numbering is a small part of it (measured
    # ~20 ms here, budgets in As built). A coarse guard against a numbering gone quadratic: the tight
    # budget in a timed run only (SURASURA_STORE_BENCH=1, the machine alone), 3x on a shared one.
    import os
    import time
    budget = 0.5 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 1.5
    ladder = spaced.layout(30000, 3131)
    order = list(range(30000))
    moved = order[15000:15060] + order[:15000] + order[15060:]
    started = time.perf_counter()
    spaced.number(list(range(3131, 33131)))
    spaced.number([ladder[i] for i in moved], floor=3131)
    assert time.perf_counter() - started < budget


def test_a_dense_deck_with_a_stray_card_far_above_is_not_a_ladder():
    # Review #10 (a): 2.5's dense numbers plus one card someone put at 600,000 — still dense: the first
    # spaced run is the full write, not a delta that writes nothing until a later move re-spaces most of it.
    olds = list(range(3000, 5000)) + [600_000]
    news, info = spaced.number(olds)
    assert info["kind"] == spaced.FULL and not spaced.is_spaced(olds, 3000)


def test_cards_all_past_the_ceiling_report_the_bottom_they_really_got():
    # Review #10 (c): the dense fallback moves the block under 999,999 and says where it starts, and no
    # floor above the ceiling is ever recorded.
    olds = list(range(1_000_000, 1_000_500))
    news, info = spaced.number(olds)
    assert info["kind"] == spaced.DENSE and info["base"] == news[0] == CEILING - 499
    from modules.junban import undo
    assert undo.record_floor("ja", ["TheBank"], 1_000_000) is False
    assert undo.ladder_floor("ja", ["TheBank"]) is None


@pytest.mark.parametrize("n", [20, 2000])
def test_a_first_spaced_run_stopped_part_way_never_sends_tomorrows_cards_back(n):
    # Review 2 #1: the job can stop between two requests (Anki closed, the app quit). Nothing moved, a dense
    # deck going onto the ladder: at every stopping point Anki's first 20 are still the plan's first 20.
    cards = [FIRST_CARD + i for i in range(2000)]
    dense = dict(zip(cards, range(3131, 5131)))
    olds = [dense[card] for card in cards]
    news, _info = spaced.number(olds)
    batches = spaced.requests(list(zip(cards, olds)), news, n, 150)
    assert len(batches) > 10
    for stop in range(len(batches) + 1):
        assert _first_n_after(batches, dense, 20, front=stop) == cards[:20], stop


def test_a_stopped_move_leaves_every_card_behind_only_cards_it_followed_or_should_follow():
    # The same promise for a move: a block pulled up, a block sent back, stopped after any request.
    rng = random.Random(5)
    cards = [FIRST_CARD + i for i in range(600)]
    ladder = dict(zip(cards, spaced.layout(600, 3131)))
    planned = cards[300:360] + cards[:300] + cards[360:]
    planned = planned[:100] + planned[160:] + planned[100:160]
    olds = [ladder[card] for card in planned]
    news, _info = spaced.number(olds, floor=3131)
    batches = spaced.requests(list(zip(planned, olds)), news, 20, 7)
    place = {card: index for index, card in enumerate(planned)}
    before = {card: index for index, card in enumerate(sorted(cards, key=ladder.get))}
    for stop in range(len(batches) + 1):
        state = dict(ladder)
        for batch in batches[:stop]:
            state.update(batch)
        queue = sorted(cards, key=lambda card: (state[card], card))
        for i, card in enumerate(queue[:60]):
            for ahead in queue[:i]:                 # whatever is ahead came before it, in the plan or before
                assert place[ahead] < place[card] or before[ahead] < before[card], (stop, card, ahead)
    rng.random()


def test_a_ladder_laid_before_is_never_re_laid_by_a_guess():
    # Review 2 #4: a small deck the deltas reshaped (most of it low, a few cards high) still sits on a
    # ladder; with its bottom recorded (`floor`), a run that changes nothing writes nothing.
    olds = [3131 + 40 * i for i in range(130)] + [600_000 + 1000 * i for i in range(10)]
    assert not spaced.is_spaced(olds, 3131)                 # a guess alone would call it dense...
    news, info = spaced.number(olds, floor=3131)
    assert news == olds and info["kind"] == spaced.DELTA and info["laid"]      # ...the record knows better
    dense = list(range(3131, 3271))                         # a ladder renumbered densely (Anki, or 2.5)
    news, info = spaced.number(dense, floor=3131)
    assert info["kind"] == spaced.FULL
    # ...also far above the recorded bottom: 2.5 numbers from the cards' own lowest, after cards were studied
    # (review 3 #1) — the gap is measured from the lowest card, so the block is re-laid, announced, once.
    above = list(range(297_320, 299_320))
    news, info = spaced.number(above, floor=3131)
    assert info["kind"] == spaced.FULL and news[0] >= 3131


def test_a_job_front_of_zero_or_less_still_puts_tomorrow_first():
    # Review 2 #12: N is at least 1, whatever a caller hands in.
    assert spaced.Job(front=0).front == 1 and spaced.Job(front=-5).front == 1 and spaced.Job().front is None


def test_a_window_that_grows_to_take_in_every_card_is_the_one_full_rewrite():
    # Only the last card is kept and the run before it has no room, so the window grows to the whole
    # ladder; that write is the one full rewrite, announced as such (kind FULL, full_rewrite True).
    news, info = spaced.delta([5, 4, 3, 2, 1], 1, ceiling=5)
    assert info["kind"] == spaced.FULL
    assert info["full_rewrite"] is True
    assert news == [1, 2, 3, 4, 5]


# --------------------------------------------------------------------------- #
# Tomorrow's own numbers first (E3.3, Sonic's A for E3.1-B3)
# --------------------------------------------------------------------------- #
def _final(batches, olds):
    """The order Anki holds once every request landed."""
    state = dict(olds)
    for batch in batches:
        for card, new in batch:
            state[card] = new
    return [card for card, _due in sorted(state.items(), key=lambda pair: (pair[1], pair[0]))]


@pytest.mark.parametrize("front", [20, 50])
def test_an_item_at_the_front_sent_to_the_back_writes_tomorrows_own_cards_first(front):
    """E3.1-B3's big move: an item's 120 cards at the top of NOW sent to the end of 6+ Months. Numbered as before, all
    120 are pushed out of tomorrow's and ride in the first request (Anki took ~0.6 s to write them on DevTest);
    now tomorrow's N cards take numbers below every other card instead, so the first request is those N alone and
    the 120 follow — Anki's first N are the plan's once it lands and after every request, and a second run writes
    nothing."""
    cards = [FIRST_CARD + i for i in range(2000)]
    current = dict(zip(cards, spaced.layout(2000, 3131)))
    planned = cards[120:] + cards[:120]
    olds = [current[card] for card in planned]
    plain, _ = spaced.number(olds, floor=3131)
    assert len(spaced.front_group(list(zip(planned, olds)), plain, front)) >= 120     # the old rule: all 120 first
    news, info = spaced.number(olds, floor=3131, front=front)
    assert info["front_first"] is True and _strict(news) and _in_bounds(news, 3131)
    assert news[front:] == plain[front:]                    # only tomorrow's numbers differ from the old rule
    batches = spaced.requests(list(zip(planned, olds)), news, front, 150)
    assert sorted(card for card, _new in batches[0]) == sorted(planned[:front])
    for landed in range(1, len(batches) + 1):              # wherever the job stops, tomorrow's are first
        assert _first_n_after(batches, current, front, front=landed) == planned[:front]
    assert _final(batches, current) == planned
    again, info2 = spaced.number(news, floor=info["base"], front=front)
    assert again == news and info2["front_first"] is False


def test_a_move_that_pushes_no_more_than_tomorrow_out_is_numbered_as_before():
    """Tomorrow's own numbers come first only where they make the first request smaller: every other move kind of
    the study (tens of cards, the back brought up, a reverse) numbers exactly as before, with the guarantee intact."""
    cards = [FIRST_CARD + i for i in range(2000)]
    current = dict(zip(cards, spaced.layout(2000, 3131)))
    for name, planned in _moves(cards):
        olds = [current[card] for card in planned]
        news, info = spaced.number(olds, floor=3131, front=20)
        if name == "the top 40 sent to the back":
            assert info["front_first"] is True, name            # 40 pushed out of a front of 20
            continue
        assert info["front_first"] is False and news == spaced.number(olds, floor=3131)[0], name
        batches = spaced.requests(list(zip(planned, olds)), news, 20, 150)
        if batches:
            front_requests = _front_requests(planned, olds, news, 20, 150)
            assert _first_n_after(batches, current, 20, front=front_requests) == planned[:20], name


def test_with_no_room_below_the_others_tomorrows_cards_keep_the_old_rule():
    """Tomorrow's numbers must sit above the ladder's bottom and below every other card, in the upper half of that
    room with two numbers a card at least: a deck whose other cards start right above the bottom keeps the old rule
    (the pushed-out cards in the first request) — slower, never wrong — and the bottom is never passed."""
    olds = [3140, 3141, 3142, 3131, 3132, 3133]           # the first three's places pushed out by the last three
    news = [3134, 3135, 3136, 3137, 3138, 3139]
    assert spaced._front_first(olds, news, 3131, 2) is None
    roomy = [5000, 5001, 5002, 3200, 3201, 3202]
    first = spaced._front_first(roomy, [5000, 5001, 5002, 5003, 5004, 5005], 3131, 2)
    assert first is not None and 3131 <= first[0] < first[1] < 3200 and first[0] >= 3131 + (3200 - 3131) // 2 - 1


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_random_moves_with_tomorrows_numbers_first_keep_every_bound_and_a_small_first_request(seed):
    """E3.3 over the gap re-run's moves, studying and mining: the bounds hold as without it, a second run writes
    nothing, Anki's first 20 are the plan's once the first request lands — and wherever tomorrow's numbers came
    first, that request is tomorrow's 20 cards at most."""
    firsts = []
    counts = _simulate(2000, 300, seed, front=20, firsts=firsts)
    assert statistics.median(counts) <= 80 and statistics.mean(counts) <= 200 and max(counts) < 2000
    assert any(first for _size, first in firsts), "the rule never came into play"
    assert all(size <= 20 for size, first in firsts if first)


def test_tomorrows_numbers_come_first_only_when_more_than_tomorrow_would_be_pushed_out():
    """The rule's edges (03 departure 12): N pushed out is the old rule (the first request no bigger than with
    tomorrow's numbers first); one more is the new one — a card tied with tomorrow's last new number counting as
    pushed out, as `front_group` counts it; and the room above the bottom must give two numbers a card."""
    # One front card; card 2 is pushed out (old 30 under the front's new 70), card 1 only when its tie counts.
    assert spaced._front_first([100, 71, 30], [70, 80, 90], 1, 1) is None             # one pushed: N = 1
    tied = spaced._front_first([100, 70, 30], [70, 80, 90], 1, 1)                     # 70 ties tomorrow's 70
    assert tied is not None and tied[0] < 30 and tied[1:] == [80, 90]
    # Two front cards and three pushed out, but only 3 numbers in the upper half above the bottom: two a card is 4.
    assert spaced._front_first([100, 101, 7, 8, 9], [102, 103, 104, 105, 106], 1, 2) is None
    assert spaced._front_first([100, 101, 9, 10, 11], [102, 103, 104, 105, 106], 1, 2) == [5, 7, 104, 105, 106]
