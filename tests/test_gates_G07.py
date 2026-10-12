"""G07: a compound the arrival holds that the risen cut-off passes is counted as crossing, never as falling under it."""
from tests.test_arrivals_gates import _gates, _rec, GAKKOU, SENSEI, TOMODACHI, JOUSOUBU, JOUSOU


def test_a_compound_the_arrival_carries_over_a_risen_cut_off_is_not_counted_twice():
    """The cut-off rises from 3.0 to 3.6 because the arrival adds 200 tokens. 上層部 was met 3 times (in [3.0, 3.6),
    so it falls under the new cut-off) but this arrival uses it once more, to 4 (over it): it is counted as
    crossing, once. The verdict stays exact; counting it under the cut-off as well would name compounds."""
    list_50 = [[*GAKKOU, 0, 0, 50], [*SENSEI, 0, 0, 50], [*TOMODACHI, 0, 0, 50]]
    gates = _gates(list_50, min_freq=0, min_count=1, ppm={"occasional": 3000}, total=1000, floor0=3.0,
                   counts={GAKKOU: 50, SENSEI: 50, TOMODACHI: 50, JOUSOUBU: 3},
                   parts={JOUSOUBU: [(JOUSOU, ("部", "ブ"))]})
    arrival = _rec(counts={JOUSOUBU: 1, TOMODACHI: 199})
    # Pin the precondition: the arrival's 1,200 tokens must actually raise the cut-off above floor0 (3.6, not 3.0),
    # or the crossing block never runs and this test would pass without exercising it.
    assert gates._floor(1200, gates.band0) > gates.floor0
    assert gates.check([arrival]) == (True, [])
