"""B1 (E2.2 gates): Gates.build marks a store whose total isn't the plan's total_tokens as stale, and check says only that."""
from types import SimpleNamespace

from app import arrivals
from tests.test_arrivals_gates import GAKKOU, _rec


class _Store:
    """The token store's answers for a Chinese library: no names, no phrases, no one-kanji pieces."""

    def bound_counts(self):
        return {}

    def phrase_tallies(self):
        return None

    def phrase_sums(self):
        return None

    def names_tables(self):
        return None

    def names_records(self):
        return []

    def get_meta(self, key):
        return None


def _build(store_total, plan_total):
    """Gates.build over a plan that holds 学校 five times, its header saying `plan_total` tokens, and a store
    whose counted total is `store_total`. The cut-off is fixed at 2 (min_freq), so only the total can differ."""
    plan = SimpleNamespace(keys=[["学校", "ガッコウ", False, False, 5]], rows=[], ties=[], spell={},
                           header={"floor": 2, "total_tokens": plan_total})
    view = SimpleNamespace(
        language="zh", plan=plan, args=SimpleNamespace(min_freq=2, exclude_freq_one=False, target_coverage=0),
        counts={("学校", "ガッコウ"): 5}, total=store_total, skip_singles=False, rare=frozenset(),
        learning=SimpleNamespace(parts={}, credits=lambda compound: []),
        known=lambda key: False, entry_of={}, phrase_set=None)
    return arrivals.Gates.build(view, _Store(), remembered=None)


def test_a_store_whose_total_is_not_the_plans_is_stale_and_every_check_says_so():
    """A store counting a different number of tokens than the plan's total_tokens is not the plan's library, so
    the list can't be called exact: build sets stale, and check names only "stale". The same plan over a store
    of the plan's total is not stale, so the flag comes from the total alone."""
    stale = _build(store_total=1200, plan_total=1000)
    assert stale.stale is not None
    assert stale.check([_rec(uses={GAKKOU: 1})]) == (False, ["stale"])
    assert _build(store_total=1000, plan_total=1000).stale is None
