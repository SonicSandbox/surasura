"""Gate P3: a phrase that is already a row, met in the arrival in a spelling the learner knows, moves the phrases gate."""
from tests.test_arrivals_gates import LIST, _Phrase, _PhraseSet, _gates, _rec

KIGA = ("気がする", "キガスル", 1, 0, 3)            # a phrase row already on the list, at the cut-off
KIGA_PHRASE = _Phrase("気がする", "キガスル", "気がする")
# The spelling the arrival meets the phrase in: kana, so it differs from the row's Word and display (気がする).
# A test that let this spelling equal the Word would pass whether or not the record's tally spelling is consulted.
KIGA_SPELLING = "きがする"


def test_a_phrase_row_met_in_a_spelling_the_learner_knows_is_no_row_any_more():
    """気がする is a row on the list (3 uses, at the cut-off). An arrival meets it as きがする, a spelling the learner
    already knows (known_lemmas, and the tally's spelling), so the phrase is known as a whole and its row goes: the
    list would change, so the verdict is not exact and the phrases gate moves. A false exact here would keep a row the
    learner no longer needs."""
    gates = _gates(
        [*LIST, KIGA], phrase_set=_PhraseSet([KIGA_PHRASE]), row_of_phrase={0: 3}, phrase_uses={0: 3},
        phrase_spellings={0: ["気がする"]}, known_lemmas={KIGA_SPELLING})     # the known spelling is the arrival's only
    record = _rec(phrases={0: 1}, tally=({0: (1, [KIGA_SPELLING])}, {}))
    assert gates.check([record]) == (False, ["phrases"])


def test_a_phrase_row_met_in_a_spelling_the_learner_does_not_know_stays_exact():
    """Control for the test above: the same row, the same arrival in the same spelling きがする, but the learner
    knows no spelling of it (known_lemmas empty). The phrase is not known as a whole, so its row stays and the
    verdict is exact. A gate that moved for every arrival of a phrase row would fail here."""
    gates = _gates(
        [*LIST, KIGA], phrase_set=_PhraseSet([KIGA_PHRASE]), row_of_phrase={0: 3}, phrase_uses={0: 3},
        phrase_spellings={0: [KIGA_SPELLING]})
    record = _rec(phrases={0: 1}, tally=({0: (1, [KIGA_SPELLING])}, {}))
    assert gates.check([record]) == (True, [])
