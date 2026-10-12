"""E2.2 gate build (B2): a rare compound gives each of its parts room equal to its own count (`Gates.build`, `room`).

Pins the one branch of `arrivals.Gates.build` the parity tests never reach: a rare compound whose count is n must give
every part n uses of room, so a word off the list can be counted as reaching the cut-off through its compounds."""
from collections import Counter
from types import SimpleNamespace

from app import analyzer, arrivals
from tests.test_arrivals_gates import JOUSOU, JOUSOUBU

BU = ("部", "ブ")                            # 上層部 = 上層 + 部
SEIKATSU = ("生活", "セイカツ")               # 生活習慣 = 生活 + 習慣, a compound that is NOT rare
SHUUKAN = ("習慣", "シュウカン")


def test_a_rare_compound_gives_each_of_its_parts_room_equal_to_its_own_count(monkeypatch):
    """上層部 is rare (under the cut-off) and met three times in the library: the compound's count is room for each of
    its parts, 上層 and 部, three uses each — and for nothing else. 生活習慣 is counted too (five uses) but is not rare,
    so it gives its parts no room. Why: the gates count a rare compound toward its free parts; a part given less room
    would stay off the list when the compound is the reason it reaches the cut-off, and a common compound's count
    must not be handed out as room."""
    monkeypatch.setitem(analyzer.LOGIC, "selection", {})
    seikatsu_shuukan = ("生活習慣", "セイカツシュウカン")
    parts = {JOUSOUBU: [(*JOUSOU, None), (*BU, None)],
             seikatsu_shuukan: [(*SEIKATSU, None), (*SHUUKAN, None)]}
    learning = SimpleNamespace(parts=parts, credits=lambda compound: [p[:2] for p in parts.get(compound, ())])
    view = SimpleNamespace(
        language="zh", plan=SimpleNamespace(keys=[], header={"floor": 3, "total_tokens": 1000}),
        args=SimpleNamespace(min_freq=2, exclude_freq_one=False, target_coverage=0),
        counts={JOUSOUBU: 3, seikatsu_shuukan: 5},
        total=1000, rare=frozenset([JOUSOUBU]), learning=learning, known=lambda key: False, skip_singles=False,
        phrase_set=None, entry_of={})
    gates = arrivals.Gates.build(view, SimpleNamespace(), remembered=None, user_files_dir="unused")
    assert dict(gates.room) == {JOUSOU: 3, BU: 3}, "each part of a rare compound gets the compound's count as room"
