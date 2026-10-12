"""`shelf.ranks` keeps each word's best (lowest) place on the list (P2.4 gap check, mutant P2.4-F27).

The list gives one place per (Word, Reading) spelling. A word with two spellings counts at its better place,
because the shelf asks "where does this word stand?" and the learner's nearer place is the true one. The
mutant flips `<` to `>` and keeps the worse place, so a word looks further down the list than it is and the
shelf moves cards that the batch needs.

What a wrong answer would cost: a word shelved as "behind" when the batch still needs it, because its worse
spelling's place was taken instead of its better one.

Pure: a plain dict in, a plain dict out. No Anki, no sleeps, nothing written to disk.
"""
from app.connect import shelf


def test_ranks_keeps_the_best_place_when_a_word_has_two_spellings():
    # The worse place (40) comes first in one dict and last in the other. Keep-first fails the first dict
    # and keep-last fails the second, so only an implementation that keeps the true minimum passes both.
    listed = {("上", "うえ"): 40, ("上", "じょう"): 7, ("気配", "けはい"): 12}
    reversed_listed = {("上", "じょう"): 7, ("上", "うえ"): 40, ("気配", "けはい"): 12}

    assert shelf.ranks(listed) == {"上": 7, "気配": 12}
    assert shelf.ranks(reversed_listed) == {"上": 7, "気配": 12}
