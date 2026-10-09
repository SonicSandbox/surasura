"""The shelf's plan (P2.4 Part B, item B2; 🧭 the cap and the shelf): `shelf.plan` picks which of Connect's waiting cards
go to the shelf, lowest-ranked first. A card is *behind* when its list rank is worse than every word the next batch
needs; a small gap (under a quarter of the cap) moves nothing; on a big gap the batch's room is made, never more than
the cards behind, and a pinned show's cards are never chosen.

What a wrong answer would cost: a shelf that moves cards on every batch (a learner's queue reshuffled for a 1-card
gap); a shelf that frees too little so the cap is overrun; one that frees too much and buries good cards; a pinned
show's cards suspended while the learner is watching it; a card the batch needs shelved.

Pure: plain `shelf.Card` objects with real words, no Anki, no sleeps, nothing written to disk.
"""
from app.connect import shelf

# Real Japanese words for the cards' spellings (the plan never reads them, but they are real data, not test1).
WORDS = ["上層部", "一生懸命", "気配", "溜め息", "約束", "勇気"]


def _behind(count, start_rank, item_id=None):
    """`count` cards, each ranked behind the batch: ranks start_rank, start_rank+1, … (unique, all listed)."""
    return [shelf.Card(card_id=1000 + i, note_id=2000 + i, word=WORDS[i % len(WORDS)],
                       item_id=item_id if item_id is not None else 1, rank=start_rank + i)
            for i in range(count)]


def test_gap_needed_is_a_quarter_of_the_cap_and_at_least_one():
    # Why: the "big gap" threshold drives every shelf decision; a quarter of 300 is 75 and a tiny cap still needs 1.
    assert shelf.gap_needed(300) == 75
    assert shelf.gap_needed(1) == 1


def test_small_gap_of_74_cards_behind_moves_nothing():
    # Why: one card short of the quarter-cap gap must not shelve anything, even at the cap; a mutant that
    # subtracts 1 from the threshold shelves here.
    needed = [10, 20, 30]
    waiting = _behind(74, start_rank=31)
    assert shelf.plan(waiting, needed, cap=300, count=300) == []


def test_big_gap_of_75_cards_behind_shelves_the_lowest_ranked_first():
    # Why: at exactly the gap, the batch's one word (count 300 + 1 − 300 = 1 card of room) takes the worst-ranked card.
    needed = [5]
    waiting = _behind(75, start_rank=6)
    picked = shelf.plan(waiting, needed, cap=300, count=300)
    assert len(picked) == 1
    assert picked[0].rank == max(c.rank for c in waiting)


def test_room_is_count_plus_needed_minus_cap_and_takes_the_worst_ranks():
    # Why: with 305 waiting and 3 words in the next batch, 8 cards must go (305 + 3 − 300), and they are the 8
    # worst-ranked of those behind, in worst-first order.
    needed = [10, 20, 30]
    waiting = _behind(80, start_rank=31)
    picked = shelf.plan(waiting, needed, cap=300, count=305)
    assert len(picked) == 8
    expected = sorted((c.rank for c in waiting), reverse=True)[:8]
    assert [c.rank for c in picked] == expected


def test_never_more_than_the_cards_behind_even_when_room_is_bigger():
    # Why: 380 waiting with a 5-word batch wants 85 cards of room, but only 75 are behind; a shelf that reaches
    # into the cards the batch needs would bury a word the learner is about to meet.
    needed = [1, 2, 3, 4, 5]
    waiting = _behind(75, start_rank=6)
    picked = shelf.plan(waiting, needed, cap=300, count=380)
    assert len(picked) == 75
    assert all(c.rank > max(needed) for c in picked)


def test_a_pinned_show_is_never_shelved_even_when_it_ranks_worst():
    # Why: the 20 worst-ranked cards belong to the pinned show (item 7); the plan must skip them and take 5 of the
    # other cards behind, never a pinned card. A mutant that ignores pinned_items would pick item 7 here.
    needed = [10]
    unpinned = _behind(80, start_rank=11, item_id=1)
    pinned = _behind(20, start_rank=91, item_id=7)
    picked = shelf.plan(unpinned + pinned, needed, cap=300, count=305, pinned_items={7})
    assert len(picked) == 6  # 305 + 1 − 300
    assert all(c.item_id != 7 for c in picked)
    assert all(c.rank <= 90 for c in picked)  # the worst ranks are the pinned show's; they are skipped


def test_no_needed_ranks_means_nothing_is_shelved():
    # Why: a batch with no words to make asks for no room; even a huge waiting pile on a huge gap stays put.
    waiting = _behind(100, start_rank=1)
    assert shelf.plan(waiting, [], cap=300, count=400) == []


def test_unlisted_words_rank_behind_every_listed_word_and_shelve_first():
    # Why: a word no longer on the list has NOT_LISTED, behind every listed word, so a gap of unlisted cards is
    # the first thing the shelf frees.
    needed = [10, 20]
    listed = _behind(40, start_rank=21)
    unlisted = [shelf.Card(card_id=5000 + i, note_id=6000 + i, word=WORDS[i % len(WORDS)], item_id=1,
                           rank=shelf.NOT_LISTED) for i in range(40)]
    picked = shelf.plan(listed + unlisted, needed, cap=300, count=301)
    assert len(picked) == 3  # 301 + 2 − 300
    assert all(c.rank == shelf.NOT_LISTED for c in picked)
