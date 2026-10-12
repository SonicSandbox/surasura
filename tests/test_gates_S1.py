"""E2.2 gate S1: a tied word that gains a surface tie the plan doesn't hold moves the spellings gate."""
from tests.test_arrivals_gates import _gates, _rec


def test_a_tied_word_whose_surfaces_newly_tie_moves_the_spellings_gate():
    """言う is listed with its two spellings (言う / いう) tied at 2, and the plan holds no tie among its surfaces.
    An arrival brings いった twice, so 言った and いった tie at 2 at the front (what Forms shows): the learner's
    list would change, so the gate names "spellings" (a false "exact" is the dangerous direction). Orth doesn't move,
    so only the surface check catches it."""
    keys = [("言う", "ユウ", 0, 0, 5)]
    gates = _gates(
        keys,
        ties=[[0, {"言う": 2, "いう": 2}, {"言った": 2}, None]],
        view_ties={0: (["言う", "いう"], [])},
    )
    assert gates.check([_rec(spc={0: ({}, {"いった": 2})})]) == (False, ["spellings"])


def test_a_surface_tie_the_plan_already_holds_keeps_the_spellings_gate_exact():
    """言う is listed with its two spellings (言う / いう) tied at 2, and the plan already holds the surface tie
    between 言った and いった. The arrival brings いった twice, which changes nothing the learner's list shows:
    the tie was already there, so the gate stays exact (empty reasons), not "spellings"."""
    keys = [("言う", "ユウ", 0, 0, 5)]
    gates = _gates(
        keys,
        ties=[[0, {"言う": 2, "いう": 2}, {"言った": 2}, None]],
        view_ties={0: (["言う", "いう"], ["言った", "いった"])},
    )
    assert gates.check([_rec(spc={0: ({}, {"いった": 2})})]) == (True, [])


def test_a_partly_held_surface_tie_still_moves_the_spellings_gate_when_a_third_surface_ties():
    """言う is listed with its two spellings tied at 2, and the plan holds the surface tie between 言った and いった
    only. An arrival brings 言って twice, so all three surfaces tie at 2 at the front: 言って is a new tied surface
    the plan does not hold (the held pair is a subset, not the whole tie), so the learner's Forms would change and
    the gate names "spellings" rather than staying exact."""
    keys = [("言う", "ユウ", 0, 0, 5)]
    gates = _gates(
        keys,
        ties=[[0, {"言う": 2, "いう": 2}, {"言った": 2, "いった": 2}, None]],
        view_ties={0: (["言う", "いう"], ["言った", "いった"])},
    )
    assert gates.check([_rec(spc={0: ({}, {"言って": 2})})]) == (False, ["spellings"])
