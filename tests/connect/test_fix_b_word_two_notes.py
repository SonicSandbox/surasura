"""Known from Anki, one word on two notes (P2.4 Part B review fix B #12).

When two Anki notes carry the same word (勇気) and each has one card, and both cards are newly suspended, the
signal must keep both cards: `_words_of` reads the notes one by one, so the word is not deduped across them and
each card is paired with its own note. A wrong answer here would lose one card, so one of the two suspended cards
would never be un-suspended by undo or the offer.

Anki is never reached: cards_info and notes_info are replaced by a small fake (no network, no writer).
"""
from app import anki_connect
from app.connect import known_signal

URL = "http://127.0.0.1:8765"


def test_word_on_two_suspended_notes_keeps_both_cards(monkeypatch):
    """Two notes, one 勇気 each, cards 201 and 202: both (word, card, note) triples come back, not one."""
    card_note = {201: 21, 202: 22}
    note_word = {21: "勇気", 22: "勇気"}

    def cards_info(url, ids):
        return [{"cardId": c, "note": card_note[c], "queue": -1} for c in ids]

    def notes_info(url, ids):
        return [{"noteId": n, "modelName": "Lapis",
                 "fields": {"Expression": {"value": note_word[n], "order": 0}}} for n in ids]

    monkeypatch.setattr(anki_connect, "cards_info", cards_info)
    monkeypatch.setattr(anki_connect, "notes_info", notes_info)

    out = known_signal._words_of(URL, [201, 202], ["Expression"], "ja")

    # Why both: the word is the same on both notes, so a dedupe across notes would keep only one of the cards.
    assert sorted(out) == [("勇気", 201, 21), ("勇気", 202, 22)]
