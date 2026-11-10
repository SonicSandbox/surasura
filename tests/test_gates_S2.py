"""E2.2 gate S2: a tied phrase row's Tier follows its shown spelling (`_spellings_move`, the phrase-tier branch)."""
from tests.test_arrivals_gates import _gates, _rec, _row


def test_a_phrase_whose_shown_spelling_becomes_an_untied_spelling_outside_its_tier_moves_the_spellings_gate():
    """腑に落ちる is a tied phrase row (its Tier is given for 腑に落ちる only). An arrival spells it ふに落ちる nine
    times, which becomes the commonest spelling with no tie: the shown spelling (`Orth`) changes to one the row's
    Tier doesn't name, so the plan doesn't hold — `spellings` moves, never exact."""
    gates = _gates([("腑に落ちる", "フニオチル", True, 0, 4)], rows=[_row("腑に落ちる")],
                   ties=[[0, {"腑に落ちる": 4}, {"腑に落ちた": 2}, {"腑に落ちる": "NOW"}]],
                   view_ties={0: ((), ())})
    assert gates.check([_rec(spc={0: ({"ふに落ちる": 9}, {})})]) == (False, ["spellings"])


def test_a_phrase_whose_new_commonest_spelling_is_in_its_tier_or_is_its_orth_stays_exact():
    """The same phrase, where the spelling that takes the lead is one the Tier names (ふに落ちる given NOW too), or
    the row's own Orth (腑に落ちる) still leads: the tier holds, so the verdict is exact."""
    keys = [("腑に落ちる", "フニオチル", True, 0, 4)]
    tie_both = [[0, {"腑に落ちる": 4}, {"腑に落ちた": 2}, {"腑に落ちる": "NOW", "ふに落ちる": "NOW"}]]
    gates = _gates(keys, rows=[_row("腑に落ちる")], ties=tie_both, view_ties={0: ((), ())})
    assert gates.check([_rec(spc={0: ({"ふに落ちる": 9}, {})})]) == (True, [])
    own = [[0, {"腑に落ちる": 4}, {"腑に落ちた": 2}, {"腑に落ちる": "NOW"}]]
    gates = _gates(keys, rows=[_row("腑に落ちる")], ties=own, view_ties={0: ((), ())})
    assert gates.check([_rec(spc={0: ({"腑に落ちる": 9}, {})})]) == (True, [])
