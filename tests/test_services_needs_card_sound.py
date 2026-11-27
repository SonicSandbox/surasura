"""*Needs you*'s Card sound card (AUDIO-FILL, PROVISIONAL words; `services.needs._sound_entry`): ONE card while cards
can get real sound now (Card sound's count, kept by Connect), with *Add sound* · *Not now*; *Not now* holds until more
cards can get it; never while Connect is off; the AI voice's cards are never this card's (VOICE-SETUP's asks).

What a wrong answer would cost: a card that keeps asking after *Not now*, one shown with nothing to add, or the AI
voice's cards promised real sound.
"""
from app.services import needs as service


def _cards(sound, answered=(), cards_on=True, ai_waiting=None):
    return [e for e in service.entries(None, sound=sound, answered=frozenset(answered), cards_on=cards_on,
                                       ai_waiting=ai_waiting) if e.kind == service.CARD_SOUND]


def test_one_card_while_cards_can_get_real_sound_with_its_two_answers():
    [entry] = _cards({"cards": 40, "real": 12, "ai": 25, "silent": 3})
    assert entry.title == "12 cards have no sentence audio, and your library has their lines."
    assert entry.actions == ("add_sound", "sound_not_now") and entry.data == {"n": 12}
    assert service.answer_keys(entry) == [entry.key] and entry.kind in service.NO_LATER
    [one] = _cards({"real": 1})
    assert one.title == "A card has no sentence audio, and your library has its line."


def test_no_card_with_nothing_real_to_add_connect_off_or_no_count():
    assert _cards({"cards": 9, "real": 0, "ai": 9}) == []          # the AI voice's cards: never this card
    assert _cards({"real": 5}, cards_on=False) == []
    assert _cards(None) == []


def test_not_now_holds_until_more_cards_can_get_sound():
    key = service.sound_key({"real": 12})
    assert _cards({"real": 12}, answered=[key]) == []
    assert _cards({"real": 7}, answered=[key]) == [], "fewer never ask again"
    assert [e.data["n"] for e in _cards({"real": 13}, answered=[key])] == [13]


def test_the_ai_voices_own_card_stands_beside_it():
    kinds = [e.kind for e in service.entries(None, sound={"real": 2, "ai": 5}, cards_on=True, ai_waiting=5)]
    assert service.CARD_SOUND in kinds and service.VOICE_SETUP in kinds
