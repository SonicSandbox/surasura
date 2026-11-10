"""Gate S3: a format-1 plan (no spelling counts kept for a listed untied word) cannot vouch for that word's spelling."""
from tests.test_arrivals_gates import GAKKOU, LIST, _gates, _rec


def test_an_arrival_spelling_a_listed_word_the_format_1_plan_has_no_counts_for_moves_the_spellings_gate():
    """学校 is a listed word with no tie and no `spell` entry (a format-1 plan keeps no spelling counts), so the plan
    cannot tell that the arrival's 学校 is spelled the way the list shows it: a false "exact" here would let a list
    with a changed spelling pass as the plan's own, so the verdict must name the spellings gate."""
    gates = _gates(LIST, spell=None)
    arrival = _rec(uses={GAKKOU: 1}, spc={0: ({"学校": 1}, {"学校": 1})})
    assert gates.check([arrival]) == (False, ["spellings"])
