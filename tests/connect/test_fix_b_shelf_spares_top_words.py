"""The shelf spares the top 20's words (P2.4 Part B final-adversary fix, J8): `shelf.plan` never shelves a waiting card
whose word the top 20 holds (`top_words`), even when that card ranks lowest of all. The swap-in would bring such a card
straight back, so shelving it is a suspend-and-restore cycle that buys nothing.

What a wrong answer would cost: a learner's top-20 word suspended on the shelf while the next batch is built, then
brought back by the swap-in on the next pass, every batch. The test shows the same waiting cards with and without
`top_words`: without it the lowest-ranked card (勇気) is the one shelved; with it that card is spared and the next
lowest (約束) goes instead.

Pure: plain `shelf.Card` objects with real words, no Anki, no sleeps, nothing written to disk.
"""
from app.connect import shelf

# A cap of 8 makes the big-gap threshold 2 (a quarter of the cap, rounded up); the three cards behind the batch are
# a real gap, so the decision is about the top-20 word alone.
CAP = 8
COUNT = 8
NEEDED = [5]  # the next batch makes one word, ranked 5; every waiting card ranks behind it


def _waiting():
    # Ranks: 勇気 is the worst (50), then 約束 (30) and 気配 (20). Higher rank = further behind the batch.
    return [
        shelf.Card(card_id=1, note_id=11, word="勇気", item_id=1, rank=50),
        shelf.Card(card_id=2, note_id=12, word="約束", item_id=1, rank=30),
        shelf.Card(card_id=3, note_id=13, word="気配", item_id=1, rank=20),
    ]


def test_without_top_words_the_lowest_ranked_card_is_shelved():
    # Why: the control. Without the top-20 list, 勇気 is the lowest card and room is 1, so it goes; this proves the
    # next test's sparing is the top-words rule and not a gap that was too small to shelve anything.
    picked = shelf.plan(_waiting(), NEEDED, cap=CAP, count=COUNT)
    assert [c.word for c in picked] == ["勇気"]


def test_a_top_20_word_is_spared_even_when_it_ranks_lowest():
    # Why: with 勇気 in the top 20, plan must not return its card, however far behind it ranks; the room goes to the
    # next lowest card, 約束. Removing the top-words filter brings 勇気 back and fails here.
    picked = shelf.plan(_waiting(), NEEDED, cap=CAP, count=COUNT, top_words={"勇気"})
    assert all(c.word != "勇気" for c in picked)
    assert [c.word for c in picked] == ["約束"]
