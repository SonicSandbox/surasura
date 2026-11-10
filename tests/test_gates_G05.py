"""G05: a word's uses as a piece of something else are taken off its store count before the cut-off is checked."""
from tests.test_arrivals_gates import _gates, _rec, GAKKOU, SENSEI, KYOUSHITSU


def test_a_word_whose_uses_are_pieces_does_not_reach_the_cut_off_on_its_store_count_alone():
    """教室 is met 3 times in the library, but 2 of them are pieces of another word, so only 1 counts toward the cut-off
    of 3. An arrival uses it once more: 1 + 1 = 2 < 3, so the list is still exact. Without the pieces taken off, the
    store's 3 would reach the cut-off and move the floor gate."""
    gates = _gates([[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3]], counts={GAKKOU: 5, SENSEI: 3, KYOUSHITSU: 3},
                   pieces={KYOUSHITSU: 2}, min_freq=3, floor0=3)
    assert gates.check([_rec(uses={KYOUSHITSU: 1})]) == (True, [])
    # The other side of the boundary pins the rule exactly: 1 + 2 = 3 reaches the cut-off, so the floor gate fails.
    # Together with the line above this means the effective store count is exactly 3 - 2 = 1, not 0 and not 3.
    assert gates.check([_rec(uses={KYOUSHITSU: 2})]) == (False, ["floor"])
