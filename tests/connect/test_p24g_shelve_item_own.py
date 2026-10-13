"""Mutant P2.4-F29: `shelve_item` must shelve only the removed show's own waiting cards.

The rule: when a finished show is removed, its never-seen Connect cards are shelved, and no other show's cards
are. `shelve_item` filters the made notes by item id (`v[0] == item_id`); the mutant flips that to `!=`, so the
removed show's cards stay in the queue and every other show's cards are suspended instead. What a wrong answer
would cost: a learner removes one finished show and another show's new cards vanish from the queue, with a
restore point that names the wrong show.
"""
from app.connect import shelf
from tests.connect.test_shelf_anki import FakeAnki, ledger  # noqa: F401  (fixture)


def test_removing_a_show_shelves_only_its_own_waiting_cards(monkeypatch, ledger):  # noqa: F811
    # Two shows' Connect notes: note 1 is item 7's (上層部), note 2 is item 8's (気配). Card 11 is item 7's; card 12
    # is item 8's and must stay waiting when item 7 is removed.
    monkeypatch.setattr(shelf, "made_notes", lambda store: {1: (7, "上層部"), 2: (8, "気配")})
    anki = FakeAnki({11: 1, 12: 2})

    run = shelf.shelve_item(anki, ledger, None, "ja", 7)

    assert run is not None
    assert anki.suspended == {11}
    # Why: the other show's note must not be tagged either, or a later restore would take its card back.
    assert anki.tags[2] == set()
    assert shelf.runs(ledger, "ja")[0]["cards"] == 1
