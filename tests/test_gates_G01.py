"""The floor gate: the cut-off is worked out on the library's total PLUS the arrivals'
tokens, so an arrival that adds tokens can raise the cut-off past a list word it leaves unused."""
from tests.test_arrivals_gates import _gates, _rec, GAKKOU, SENSEI, TOMODACHI, KYOUSHITSU


def test_an_arrival_that_raises_the_cut_off_drops_a_list_word_it_leaves_unused():
    """A library of 1000 tokens has a cut-off of 3.0 (3 per million), and 先生 is met 3 times: exactly on it, so it
    stays. An arrival of 500 tokens of 教室 (no use of any list word) makes the total 1500, the cut-off 4.5, and 先生
    at 3 now falls under it: the list moves on the floor gate. An arrival with no tokens at all moves nothing: the cut-off
    follows the total the arrivals bring, not the library's total alone."""
    keys = [[*GAKKOU, 0, 0, 10], [*TOMODACHI, 0, 0, 10], [*SENSEI, 0, 0, 3]]
    gates = _gates(keys, min_freq=0, min_count=1, ppm={"occasional": 3000}, band="occasional", total=1000)
    assert gates.check([_rec(counts={KYOUSHITSU: 500})]) == (False, ["floor"])
    assert gates.check([_rec()]) == (True, [])
