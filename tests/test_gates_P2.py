"""Gate P2: when the store's phrase tallies are not current, an arrival that meets a phrase can't be judged exact."""
from tests.test_arrivals_gates import LIST, _Phrase, _PhraseSet, _gates, _rec


def test_an_arrival_meeting_a_phrase_with_no_current_tallies_names_the_phrases_gate():
    """The store's phrase tallies aren't current (phrase_uses None), so the engine can't tell whether 気がする (キガスル,
    an idiom met as itself) would make a new phrase row. The verdict must name "phrases" (can't tell), never exact:
    a false exact would promise a list the next Generate doesn't give."""
    phrase_set = _PhraseSet([_Phrase("気がする", "キガスル", "気がする")])
    gates = _gates(LIST, phrase_set=phrase_set, row_of_phrase={}, phrase_uses=None)
    assert gates.check([_rec(uses={}, phrases={0: 1})]) == (False, ["phrases"])


def test_an_arrival_with_no_phrase_and_no_current_tallies_is_still_exact():
    """The tallies gate only bites when a phrase arrives: with no phrase in the arrival, a missing tally must not
    turn an exact verdict into "phrases" (the guard before the phrase_uses None check)."""
    phrase_set = _PhraseSet([_Phrase("気がする", "キガスル", "気がする")])
    gates = _gates(LIST, phrase_set=phrase_set, row_of_phrase={}, phrase_uses=None)
    assert gates.check([_rec(uses={}, phrases={})]) == (True, [])
