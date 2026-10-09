"""Known from Anki, the first read asks for 150 cards at a time (P2.4 Part B final-adversary fix J16).

A first read of a big deck can hold 400 new cards. `_words_of` must ask Anki `cards_info` for no more than 150 card
ids in one request, and still come back with every card's word. A wrong answer here would either freeze Anki's
window (one huge request) or drop cards from the signal (a chunk lost in the join), so some cards would never be
offered or undone.

Anki is never reached: cards_info and notes_info are replaced by small fakes that record each request's size (no
network, no writer). monkeypatch restores both after the test.
"""
from app import anki_connect
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
CARD_COUNT = 400
WORD = "勇気"


def test_first_read_of_400_cards_asks_anki_at_most_150_ids_a_call(monkeypatch):
    """400 cards: every cards_info request holds 150 ids or fewer, and all 400 (word, card, note) triples come back."""
    card_ids = list(range(1000, 1000 + CARD_COUNT))
    card_note = {c: c + 5000 for c in card_ids}
    asked_sizes = []

    def cards_info(url, ids):
        asked_sizes.append(len(ids))
        return [{"cardId": c, "note": card_note[c], "queue": -1} for c in ids]

    def notes_info(url, ids):
        return [{"noteId": n, "modelName": "Lapis",
                 "fields": {"Expression": {"value": WORD, "order": 0}}} for n in ids]

    monkeypatch.setattr(anki_connect, "cards_info", cards_info)
    monkeypatch.setattr(anki_connect, "notes_info", notes_info)

    out = known_signal._words_of(URL, card_ids, ["Expression"], "ja")

    # Why the cap: Anki's window freezes on one huge request, so 400 cards must go as 150 + 150 + 100, never one call.
    assert max(asked_sizes) <= 150
    assert len(asked_sizes) == 3
    # Why every card: a chunk lost in the join would drop cards, so each card id must come back with its word.
    assert sorted(card for _, card, _ in out) == card_ids
    assert all(word == WORD for word, _, _ in out)
