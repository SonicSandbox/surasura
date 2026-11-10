"""G06: a compound the learner already knows is skipped by the compounds gate, so an arrival using it never flips a rarity."""
from tests.test_arrivals_gates import _gates, _rec, LIST, JOUSOUBU


def test_a_known_compound_met_by_an_arrival_never_flips_the_compounds_gate():
    """上層部 (a compound of 上層 + 部) is known to the learner, is not rare, and the library has never counted it
    (store count 0). An arrival uses it once: under the cut-off of 2 it would look like a rare compound becoming
    common, but a known compound is not judged by its rarity at all — so the verdict stays exact, nothing moves."""
    parts = {JOUSOUBU: [("上層", "ジョウソウ", True), ("部", "ブ", True)]}
    gates = _gates(LIST, parts=parts, known=(JOUSOUBU,), floor0=2, min_freq=2)
    assert gates.check([_rec(counts={JOUSOUBU: 1})]) == (True, [])
