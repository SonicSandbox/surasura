"""A finished show's waiting cards go to the shelf first (app/connect/shelf.py `plan`, `finished_items`): such a card
is a candidate even when it ranks ahead of every word the next batch needs, and it is chosen before a lower-ranked
card of a show still running when only one card must go. What a wrong answer would cost: a finished show's card
keeps its place in Anki's queue while a show the learner is still watching is shelved (the shelf works from the
wrong end), or a finished show's card is skipped only because it ranks well (the shelf never clears what the learner
has finished)."""
from app.connect import shelf


def _card(card_id, word, item_id, rank):
    return shelf.Card(card_id, card_id * 10, word=word, item_id=item_id, rank=rank)


def test_finished_show_card_ahead_of_every_needed_word_is_shelved_before_a_lower_ranked_running_card():
    # cap 8, 7 waiting, 2 words in the next batch -> room = 7 + 2 - 8 = 1, and the gap is 2 candidates (cap / 4).
    # The batch's worst needed place is 200. 上層部 (item 7, finished) ranks 10, AHEAD of every needed word, so only
    # the finished-first rule makes it a candidate. 一生懸命 and 気配 (items 3 and 4, still running) rank behind 200.
    # Finished first means 上層部 is chosen; a rank-only rule would pick the lowest-ranked running card, 一生懸命 (300).
    finished_ahead = _card(1, "上層部", item_id=7, rank=10)
    running_low = _card(2, "一生懸命", item_id=3, rank=300)
    running_mid = _card(3, "気配", item_id=4, rank=250)
    waiting = [finished_ahead, running_low, running_mid]

    chosen = shelf.plan(waiting, needed_ranks=[100, 200], cap=8, count=7, finished_items={7})

    assert [c.card_id for c in chosen] == [1], chosen
