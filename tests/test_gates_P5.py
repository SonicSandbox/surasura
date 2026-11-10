"""Gate P5: a phrase off the list that reaches the cut-off but is known as a whole makes no row, so nothing moves."""
from tests.test_arrivals_gates import LIST, _Phrase, _PhraseSet, _gates, _rec


def test_a_phrase_reaching_the_cut_off_that_the_learner_knows_whole_makes_no_row_and_moves_no_gate():
    """気がする (キガスル) is met twice in an arrival, enough to reach the cut-off of 2, but the learner already knows
    the phrase as a whole: its display spelling (気が為る, a different spelling from its word) is a known word, and
    neither the word nor the arrival's spelling is. It gets no row, so the list stays exact. Without the known-whole
    check the gate would name "phrases" and the list would wrongly grow a row for it. The display is the only
    spelling in known_lemmas, so the test fails if the check looks at the word alone."""
    phrase_set = _PhraseSet([_Phrase("気がする", "キガスル", "気が為る")])
    gates = _gates(LIST, phrase_set=phrase_set, phrase_uses={0: 0}, phrase_spellings={0: ("気がする",)},
                   known_lemmas={"気が為る"})
    assert gates.check([_rec(phrases={0: 2})]) == (True, [])
