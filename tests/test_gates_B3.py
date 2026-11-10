"""B3: `Gates.build` keeps only the unknown compounds' counts in `compound_counts` (a compound the learner knows never
counts toward a cut-off, so it must not be in the sorted list the compounds gate walks)."""
from types import SimpleNamespace

from app import analyzer, arrivals
from tests.test_arrivals_gates import JOUSOUBU


def test_build_leaves_a_known_compound_out_of_the_unknown_compound_counts(monkeypatch, tmp_path):
    """A library with a known compound (上層部, count 4), two unknown compounds (新学期 count 7 inserted before
    大学生 count 2, so the order differs from the sorted order) and a plain unknown word (学校, count 5, not a
    compound) gives `compound_counts == [2, 7]`: the known compound is left out, every unknown compound counts,
    the list is ascending, and the plain word is left out (only compounds count)."""
    monkeypatch.setitem(analyzer.LOGIC, "selection", {})
    shingakki = ("新学期", "シンガッキ")
    daigakusei = ("大学生", "ダイガクセイ")
    gakkou = ("学校", "ガッコウ")
    parts = {
        JOUSOUBU: [("上層", "ジョウソウ", True), ("部", "ブ", True)],
        shingakki: [("新", "シン", True), ("学期", "ガッキ", True)],
        daigakusei: [("大学", "ダイガク", True), ("生", "セイ", True)],
    }
    counts = {JOUSOUBU: 4, shingakki: 7, daigakusei: 2, gakkou: 5}
    plan = SimpleNamespace(keys=[], rows=[], ties=[], spell={},
                           header={"floor": 3.0, "total_tokens": 1000})
    view = SimpleNamespace(
        language="zh", plan=plan, args=analyzer.parse_analysis_args(["--language=zh"]),
        counts=counts, total=1000, skip_singles=False, rare=frozenset(), phrase_set=None, entry_of={},
        learning=SimpleNamespace(parts=parts, credits=lambda compound: []),
        known=lambda key: key == JOUSOUBU)
    store = SimpleNamespace(get_meta=lambda key: None)
    gates = arrivals.Gates.build(view, store, remembered=None, user_files_dir=tmp_path)
    assert gates.compound_counts == [2, 7]
