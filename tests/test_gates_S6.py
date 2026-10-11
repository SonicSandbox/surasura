"""Gate S6: an untied listed word whose Forms change (a new surface appears, Orth unchanged, no tie) moves the spellings gate."""
from tests.test_arrivals_gates import _gates, _rec, _row

IU = ("言う", "イウ")
KEYS = [[*IU, 0, 0, 5]]


def test_an_untied_word_gaining_a_new_surface_while_its_orth_holds_moves_the_spellings_gate():
    """言う is met 5 times as 言う and 言った 3 times (no tie: one spelling, one surface). An arrival adds 言って once.
    Orth stays 言う, nothing ties, but the Forms the learner sees change from 言った to 言った|言って: the plan's
    spellings are no longer the Next Generate's, so the gate must name spellings. A second arrival that only adds a
    count to the held spellings leaves Forms as they are, so it stays exact."""
    gates = _gates(KEYS, rows=[_row("言う", "言った")], spell={0: ({"言う": 5}, {"言った": 3})})
    assert gates.check([_rec(spc={0: ({}, {"言って": 1})})]) == (False, ["spellings"])
    assert gates.check([_rec(spc={0: ({"言う": 1}, {})})]) == (True, [])
