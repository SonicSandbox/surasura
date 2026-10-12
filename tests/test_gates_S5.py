"""E2.2 gate S5: an untied list word whose shown spelling (Orth) changes moves the spellings gate."""
from tests.test_arrivals_gates import GAKKOU, LIST, _gates, _rec


def test_an_untied_word_whose_other_spelling_overtakes_its_orth_moves_the_spellings_gate():
    """学校 is held as the commonest spelling (3 times, no tie); an arrival that writes it 學校 five times makes 學校
    the commonest spelling, so the row's Orth would change with no tie involved. The gate must say so, and only so:
    the Forms column stays the same (nothing else was met), so the verdict is exactly ["spellings"]."""
    gates = _gates(LIST, spell={0: ({"学校": 3}, {})})
    assert gates.check([_rec(uses={GAKKOU: 1}, spc={0: ({"學校": 5}, {})})]) == (False, ["spellings"])
    # The control: a second spelling that stays behind the held one moves nothing.
    assert gates.check([_rec(uses={GAKKOU: 1}, spc={0: ({"學校": 2}, {})})]) == (True, [])
