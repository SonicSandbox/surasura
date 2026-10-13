"""Pins the rule that `shelf.cards()` keeps each card's item id, taken from the `made` mapping (mutant P2.4-F09).

Rule: a card the shelf finds carries the item id of the note it was made from. The shelf's choice (which cards to
suspend or restore) is made by item, so a card with no item id is placed on no item's row. A wrong answer here
would shelve the wrong item's cards or none at all.

Mutant id: P2.4-F09 (`app/connect/shelf.py`: `Card(..., word, None)` in place of `item_id`).
"""
from app.connect import shelf
from tests.connect.test_shelf_anki import FakeAnki  # noqa: F401  (fake Anki, the neighbours' own)


def test_cards_keeps_each_cards_item_id_from_its_note():
    # Why: two Connect notes, two items. Each card must report its own item id, not a shared or missing one.
    anki = FakeAnki({11: 1, 12: 2})
    made = {1: (7, "上層部"), 2: (8, "気配")}

    found = shelf.cards(anki, shelf.WAITING_QUERY, made)

    assert sorted((c.card_id, c.item_id) for c in found) == [(11, 7), (12, 8)]
