"""The floor gate: a word off the plan reaches the cut-off through the uses its rare compounds give it (`room`)."""
from tests.test_arrivals_gates import GAKKOU, KYOUSHITSU, SENSEI, _gates, _rec


def test_a_word_whose_rare_compounds_give_it_uses_can_reach_the_cut_off():
    """教室 was met once in the store and its rare compounds give it room for two more (room 2, cut-off 3). An
    arrival using it once brings it to 3, so it reaches the cut-off and is a new list word. Without the room, its
    store count and the arrival's one use make 2 — under the cut-off — so nothing moves: the room is what counts.
    The plan's own words all meet the cut-off of 3, so only 教室 can move the floor gate."""
    keys = [[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3]]
    gates = _gates(keys, min_freq=3, floor0=3, counts={GAKKOU: 5, SENSEI: 3, KYOUSHITSU: 1},
                   room={KYOUSHITSU: 2})
    assert gates.check([_rec(uses={KYOUSHITSU: 1})]) == (False, ["floor"])


def test_store_count_and_room_are_summed_toward_the_cut_off():
    """教室 was met once in the store and its rare compounds give it room for one more (room 1, cut-off 3). The
    arrival's one use makes the store count, the room and the arrival together 3, so it reaches the cut-off and is a
    new list word. Counting the room alone would make 2 (under the cut-off) and nothing would move; dropping the
    store count would also make 2. Without any room (the counterfactual) the store count and the one use make 2, so
    nothing moves: both the store count and the room are needed to reach 3."""
    keys = [[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3]]
    gates = _gates(keys, min_freq=3, floor0=3, counts={GAKKOU: 5, SENSEI: 3, KYOUSHITSU: 1},
                   room={KYOUSHITSU: 1})
    assert gates.check([_rec(uses={KYOUSHITSU: 1})]) == (False, ["floor"])
    no_room = _gates(keys, min_freq=3, floor0=3, counts={GAKKOU: 5, SENSEI: 3, KYOUSHITSU: 1}, room={})
    assert no_room.check([_rec(uses={KYOUSHITSU: 1})]) == (True, [])
