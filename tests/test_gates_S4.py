"""The spellings gate: an untied word whose surfaces come to tie at the
front moves the gate, even when its spelling (Orth) is not tied."""
from app import plan_rules
from tests.test_arrivals_gates import _gates, _rec, _row


def test_an_untied_word_whose_surfaces_come_to_tie_at_the_front_moves_the_spellings_gate():
    """言う is held with one spelling (言う) and one surface (言った, met 3 times). An arrival meets いった 3 times too,
    so the two surfaces tie at the front and `Forms` could come out either way: the plan is no longer exact, and the
    gate names "spellings". The spelling itself doesn't tie or change, so only the surface tie can move the gate; the
    row holds the Orth and Forms the plan would show for the combined counts, so no display check moves it either."""
    word = "言う"
    orth = plan_rules.display_orth(word, {word: 5})
    forms = plan_rules.display_forms(word, {word: 5}, {"言った": 3, "いった": 3})
    keys = [[word, "いう", 0, 0, 5]]
    gates = _gates(keys, rows=[_row(orth, forms)], spell={0: ({word: 5}, {"言った": 3})})
    assert gates.check([_rec(spc={0: ({}, {"いった": 3})})]) == (False, ["spellings"])


def test_a_surface_tie_past_the_front_does_not_move_the_spellings_gate():
    """The same 言う, but nine surfaces met more often (20 down to 12 times) sit ahead of the tied pair, so the pair
    starts at place 9, past the front that `Forms` can reach (`_spelling_ties` looks at places 0 to 8). Nothing the
    display shows can change, so the gate must hold: the plan stays exact and the gate says nothing."""
    word = "言う"
    ahead = {s: 20 - i for i, s in enumerate(["言わない", "言います", "言えば", "言おう", "言える", "言わず",
                                               "言わせる", "言われる", "言ってる"])}
    held = {**ahead, "言った": 3}
    combined = {**held, "いった": 3}
    orth = plan_rules.display_orth(word, {word: 5})
    forms = plan_rules.display_forms(word, {word: 5}, combined)
    keys = [[word, "いう", 0, 0, 5]]
    gates = _gates(keys, rows=[_row(orth, forms)], spell={0: ({word: 5}, held)})
    assert gates.check([_rec(spc={0: ({}, {"いった": 3})})]) == (True, [])
