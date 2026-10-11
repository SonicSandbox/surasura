"""B4: with the one-kanji rule on, a Japanese list's gate pieces are the store's bound counts (one-kanji uses that stand on
their own), so an arrival's one-kanji words are judged against the same counts Generate counts."""
from types import SimpleNamespace

from app import analyzer, arrivals

from tests.test_arrivals_gates import GAKKOU


class _Store:
    """The token store's answers for a Japanese library with no name tables yet."""
    def __init__(self, bound):
        self._bound = bound

    def bound_counts(self):
        return dict(self._bound)

    def phrase_tallies(self):
        return None

    def names_tables(self):
        return None

    def names_records(self):
        return []

    def get_meta(self, key):
        return None


def _view(skip_singles):
    """A Japanese plan of one word (学校, used 3 times) with the one-kanji rule set as `skip_singles` says."""
    plan = SimpleNamespace(keys=[[GAKKOU[0], GAKKOU[1], False, False, 3]],
                           header={"floor": 2, "total_tokens": 1000})
    return SimpleNamespace(
        language="ja", plan=plan, args=analyzer.parse_analysis_args(["--language=zh"]),
        counts={GAKKOU: 3}, total=1000, skip_singles=skip_singles, rare=frozenset(),
        learning=SimpleNamespace(parts={}, credits=lambda compound: []),
        known=lambda key: False, phrase_set=None, entry_of={})


def test_with_the_one_kanji_rule_on_the_gates_pieces_are_the_stores_bound_counts(monkeypatch):
    """The one-kanji rule counts a one-kanji word's uses that stand on their own (年 twice, 前 once here). Gates.build
    must hold exactly the store's bound counts as its pieces, not an empty table, or an arrival's one-kanji uses would
    be judged against nothing."""
    monkeypatch.setitem(analyzer.LOGIC, "selection", {"band": "occasional"})
    bound = {("年", "ネン"): 2, ("前", "マエ"): 1}
    gates = arrivals.Gates.build(_view(skip_singles=True), _Store(bound), remembered=None, user_files_dir="")
    assert gates.pieces == bound
