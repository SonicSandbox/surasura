"""The shelf ranks Chinese cards the same way Japanese ones are ranked (P2.4 Part J, item K1): `shelf.ranks` turns a
Chinese list {(Word, Reading): place} into each word's best place, and `shelf.plan` shelves the waiting cards that rank
behind the batch's words lowest-ranked first.

What a wrong answer would cost: a Chinese learner's shelf sends the words they need most (the top of the list) away
while the rare ones stay in the queue, the reverse of what the shelf is for.

Pure: plain `shelf.Card` objects with real Chinese words, no Anki, no sleeps, nothing written to disk.
"""
from app.connect import shelf

# A small Chinese list: (Word, Reading) -> place. 努力, 认真 are the batch's words; 坚持 and 机会 wait behind them.
CHINESE_LIST = {("努力", "nǔlì"): 1, ("认真", "rènzhēn"): 2, ("坚持", "jiānchí"): 400, ("机会", "jīhuì"): 500}


def _waiting_cards():
    """Two waiting Chinese cards, one per word, each with its list rank read through `shelf.ranks`."""
    ranks = shelf.ranks(CHINESE_LIST)
    return [
        shelf.Card(card_id=1, note_id=11, word="坚持", item_id=3, rank=ranks["坚持"]),
        shelf.Card(card_id=2, note_id=22, word="机会", item_id=4, rank=ranks["机会"]),
    ]


def _needed():
    ranks = shelf.ranks(CHINESE_LIST)
    return [ranks["努力"], ranks["认真"]]


def test_chinese_cards_shelve_the_worst_ranked_word_first_when_there_is_room_for_two():
    # Why: the rank-400 word 坚持 must not go before the rank-500 word 机会. A mutant that sorts ascending by rank
    # shelves 坚持 first, so this assertion on the order of the picks catches it.
    picked = shelf.plan(_waiting_cards(), _needed(), cap=4, count=4)
    assert [c.word for c in picked] == ["机会", "坚持"]


def test_chinese_cards_with_room_for_one_shelve_only_the_worst_ranked_word():
    # Why: room is count + words − cap = 3 + 2 − 4 = 1, so only the worst-ranked card (机会) may go; a sort that
    # reads ranks the wrong way would shelve 坚持 here instead and leave the worse word in the queue.
    picked = shelf.plan(_waiting_cards(), _needed(), cap=4, count=3)
    assert [c.word for c in picked] == ["机会"]
