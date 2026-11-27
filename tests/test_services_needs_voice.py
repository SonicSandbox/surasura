"""VOICE-SETUP's *Some cards need the AI voice: set it up* (PROVISIONAL words; Sonic § 108): `app/services/needs.py`'s
`VOICE_SETUP` line, Qt-free, with real Japanese and Chinese titles from tests/Test Resources/.

When cards first wait for the AI voice (no real sound to cut from: Card sound's count, handed in by the window only
while the voice isn't set up), Needs you asks once: *Set it up* opens the voice's own guide; *Not now* answers it for
good (Settings › Anki & mining › *Card sound* has the voice any time). Never in the first-run setup.

What a wrong answer would cost a learner: the card with nothing waiting (a 4.9 GB question for no card), a card that
comes back after *Not now*, its explainer as a line under the title, or a ⋯ whose *Not now* says the same as its own.
"""
from types import SimpleNamespace

import pytest

from app.services import needs
from tests.test_library_store_support import LANGUAGES, names


def view(language):
    """Current with one show of 3 episodes (real titles), the mine line over all three."""
    title = names(language)[0]
    eps = tuple(SimpleNamespace(id=i + 1, label=f"Ep {i + 1}", number=i + 1, missing=False,
                                rel_path=f"{title}/{title} - {i + 1:02d}.srt", in_top=True, cards=4)
                for i in range(3))
    row = SimpleNamespace(key="w1", work_id=1, title=title, media="anime", tier="now", episodes=eps)
    return SimpleNamespace(mode="store", rows=(row,), loading=False, needs=(), mine_line=3)


def voice(language, ai_waiting):
    return [e for e in needs.entries(view(language), answered=needs.read_answered(language),
                                     seen=needs.read_seen(language), ai_waiting=ai_waiting)
            if e.kind == needs.VOICE_SETUP]


@pytest.mark.parametrize("language", LANGUAGES)
def test_cards_waiting_for_the_ai_voice_ask_once_with_its_two_answers(language):
    got = voice(language, 18)
    assert len(got) == 1
    e = got[0]
    assert e.key == needs.VOICE_SETUP and e.unseen and e.lines == ()
    assert e.title == "Some cards need the AI voice: set it up"
    assert e.actions == ("voice_setup", "voice_not_now") and e.data == {"n": 18}
    assert e.say.startswith("18 of your cards have no real sound to cut from.")
    assert needs.VOICE_SETUP in needs.NO_LATER, "its own two answers end it: no ⋯ Not now"


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_card_says_its_sentence_not_their_sentences(language):
    assert voice(language, 1)[0].say.startswith("1 of your cards has no real sound to cut from.")


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("ai_waiting", [None, 0, -3, "18", 2.0])
def test_nothing_waiting_or_nothing_known_asks_nothing(language, ai_waiting):
    # why: None = the window doesn't know (the voice set up, the module absent, a Chinese library): never asked
    assert voice(language, ai_waiting) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_not_now_answers_it_for_good(language):
    assert voice(language, 5)
    needs.answer(language, [needs.VOICE_SETUP])
    assert voice(language, 5) == [] and voice(language, 500) == []


def test_the_answer_is_one_languages_and_seen_marks_it_old():
    needs.answer("ja", [needs.VOICE_SETUP])
    assert voice("ja", 5) == [] and len(voice("zh", 5)) == 1       # (the window hands zh none: the guard is its)
    needs.mark_seen("zh", [needs.VOICE_SETUP])
    assert not voice("zh", 5)[0].unseen


def test_it_is_a_kind_of_its_own_and_its_key_never_collides():
    assert needs.VOICE_SETUP in needs.KINDS and needs.KINDS.count(needs.VOICE_SETUP) == 1
    assert needs.VOICE_SETUP not in needs.WIRED_LATER
