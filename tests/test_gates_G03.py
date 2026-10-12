"""The floor gate: a word off the plan counts as under the cut-off whatever its store count says."""
from tests.test_arrivals_gates import _gates, _rec, GAKKOU, KYOUSHITSU


def test_a_word_off_the_plan_used_fewer_times_than_the_cut_off_stays_under_it_even_with_a_big_store_count():
    """A word off the plan is used under the cut-off (ceil(3.0) - 1 = 2 uses at most), so its store count of 5
    must not let one more arrival use lift it over the new cut-off (3.003): 2 used + 1 = 3 < 3.003 holds, and the
    verdict is exact. Counting it as at most ceil(cut-off) would count the word as used 3 times and wrongly moves 'floor'.
    The plan holds one list word used 5 times (over the cut-off), so no list word falls under the new cut-off."""
    keys = [[*GAKKOU, 0, 0, 5]]
    counts = {GAKKOU: 5, KYOUSHITSU: 5}
    gates = _gates(keys, counts=counts, min_freq=0, min_count=1, ppm={"occasional": 3000}, total=1000, floor0=3.0)
    assert gates.check([_rec(uses={KYOUSHITSU: 1}, counts={KYOUSHITSU: 1})]) == (True, [])
