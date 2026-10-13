"""The shelf's tied-rank rule (P2.4 gap test, mutant P2.4-F04; `shelf.plan`): a waiting card whose list rank equals the
worst rank the next batch needs is not *behind* that word, so it is never shelved. Only a card ranked strictly worse
than every needed word counts as behind.

What a wrong answer would cost: a card the next batch needs (its word sits at the same place as the batch's worst word)
suspended to the shelf and kept from the learner's queue, because it was counted as behind when it is not.

Pure: plain `shelf.Card` objects with real words, no Anki, no sleeps, nothing written to disk.
"""
from app.connect import shelf


def test_card_tied_with_the_worst_needed_rank_is_never_shelved():
    # Why: rank 5 is the batch's worst needed place, so a card at rank 5 is not behind it. Room for every
    # candidate (count 400 + 1 − cap 300 = 101 ≥ 76) means a card that counts as behind is always picked; the tied
    # card must not be.
    needed = [5]
    behind_cards = [shelf.Card(card_id=1000 + i, note_id=2000 + i, word=w, item_id=1, rank=6 + i)
                    for i, w in enumerate(["上層部", "一生懸命", "気配", "溜め息", "約束"] * 15)]
    tied = shelf.Card(card_id=9000, note_id=9100, word="勇気", item_id=1, rank=5)
    waiting = behind_cards[:75] + [tied]
    picked = shelf.plan(waiting, needed, cap=300, count=400)
    assert len(picked) == 75
    assert 9000 not in [c.card_id for c in picked]
