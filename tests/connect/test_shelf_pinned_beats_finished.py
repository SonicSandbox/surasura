"""The shelf's plan, pinned beats finished (P2.4 Part B, item K2; 🧭 the cap and the shelf): `shelf.plan` never returns
a card whose show is both pinned and finished. A finished show's cards are the shelf's first candidates whatever
their rank, but a pinned show is the learner's choice to keep, so the pin wins over the finish.

What a wrong answer would cost: a show the learner pinned to keep watching is suspended the moment it finishes,
the one card set they asked the shelf to leave alone. The room for the batch must come from the other cards.

Pure: plain `shelf.Card` objects with real words, no Anki, no sleeps, nothing written to disk.
"""
from app.connect import shelf

# Real Japanese words for the cards' spellings (the plan never reads them, but they are real data, not test1).
WORDS = ["上層部", "一生懸命", "気配", "溜め息", "約束", "勇気"]


def test_a_pinned_show_that_is_also_finished_is_never_shelved():
    # Why: the 20 worst-ranked cards belong to show 7, which is pinned AND finished. Finished cards sort first, so a
    # mutant that drops the pin check would fill all 6 places of room from show 7; the plan must take 6 unpinned cards.
    needed = [10]
    unpinned = [shelf.Card(card_id=1000 + i, note_id=2000 + i, word=WORDS[i % len(WORDS)], item_id=1, rank=11 + i)
                for i in range(80)]
    pinned_finished = [shelf.Card(card_id=3000 + i, note_id=4000 + i, word=WORDS[i % len(WORDS)], item_id=7,
                                  rank=91 + i)
                       for i in range(20)]
    picked = shelf.plan(unpinned + pinned_finished, needed, cap=300, count=305,
                        pinned_items={7}, finished_items={7})
    assert len(picked) == 6  # 305 + 1 − 300: the plan does shelve, so the empty result below would not pass vacuously
    assert all(c.item_id != 7 for c in picked)
    assert all(c.item_id == 1 for c in picked)
