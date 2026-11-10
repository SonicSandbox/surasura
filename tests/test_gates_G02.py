"""A set phrase row that the risen cut-off passes is the phrases gate's move, not the floor's (E2.2 gate G02)."""
from tests.test_arrivals_gates import _gates, _rec, GAKKOU, SENSEI

KIGASURU = ("気がする", "キガスル")       # a set phrase row (is_phrase 1) the library meets 3 times


def test_a_phrase_row_falling_under_the_risen_cut_off_is_named_phrases():
    """The cut-off is 3.0 on a 1000-token library and 4.5 once an arrival of 500 unrelated tokens joins it. The phrase
    row 気がする, met 3 times, falls under 4.5: that is the phrases gate moving, named as such; a plain word at 10
    falls under nothing. Named "floor" instead, the gate list would send the learner to the wrong part of the list."""
    keys = [[*GAKKOU, 0, 0, 10], [*SENSEI, 0, 0, 10], [*KIGASURU, 1, 0, 3]]
    gates = _gates(keys, min_freq=0, min_count=1, ppm={"occasional": 3000}, total=1000,
                   counts={GAKKOU: 10, SENSEI: 10})
    assert gates.check([_rec(counts={("某", "ボウ"): 500})]) == (False, ["phrases"])
