"""The compounds gate when the cut-off rises: a compound the arrival does
not hold, whose library count sits between the old and the new cut-off, falls under the new cut-off and moves the gate."""
from tests.test_arrivals_gates import GAKKOU, JOUSOU, JOUSOUBU, SENSEI, TOMODACHI, _gates, _rec


def test_a_compound_the_arrival_doesnt_hold_falls_under_a_risen_cut_off():
    """上層部 is counted 3 times in the library. The arrival is 199 uses of a filler word and does not carry 上層部: the
    total rises to 1199, so the cut-off rises from 3.0 to about 3.6 and 上層部 (3 < 3.6) falls under it — the plan's
    list would change, so the verdict is not exact and names the compounds gate. The rule is pinned on the whole
    verdict because a false "exact" is the dangerous direction."""
    keys = [[*GAKKOU, 0, 0, 50], [*SENSEI, 0, 0, 50], [*TOMODACHI, 0, 0, 50]]
    parts = {JOUSOUBU: ((JOUSOU[0], JOUSOU[1], True), ("部", "ブ", True))}
    gates = _gates(keys, min_freq=0, min_count=1, ppm={"occasional": 3000}, total=1000, floor0=3.0,
                   counts={GAKKOU: 50, SENSEI: 50, TOMODACHI: 50, JOUSOUBU: 3}, parts=parts)
    assert gates.check([_rec(counts={GAKKOU: 199})]) == (False, ["compounds"])
