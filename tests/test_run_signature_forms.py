"""The run signature's two forms (E1.1 01 §1, RUNBOOK E1.2.1): the full one, byte for byte the base's, and the
order-free one the plan file carries — one value for every order of the same library, another for anything else.

The full signature decides whether Generate runs at all (and the dashboard's ✓), so a digest that moved would cost
every user a full re-analysis; the base's digests on fixed inputs are in tests/Test Resources/plan_file_base_hashes.json
(recorded before E1.2 changed anything: tests/plan_file_cases.py). The orders are RP-2's (E0.1): A, then B (the last
NOW file to NOW's top), C (the first Soon file to NOW's front), D (the first NOW file to 6+ Months' top), all real text.
"""
import json
import os

import pytest

from app import analyzer
from tests import plan_file_cases as cases


def _base():
    with open(cases.BASE_HASHES, encoding="utf-8") as f:
        return json.load(f)


def test_the_full_signature_is_the_base_digest_on_fixed_inputs(tmp_path):
    """Two Japanese orders, a Chinese run in Simplified and an empty library with its own args: each digest equals the
    one the code before the split computed — the iterencode digest is json.dumps', and nothing joined or left the
    parts."""
    assert cases.signatures(str(tmp_path / "empty")) == _base()["signatures"]


def test_the_order_free_signature_ignores_the_order_and_only_the_order(tmp_path):
    """The same fixed inputs: the two orders of one library share their order-free digest; the full ones differ."""
    free = cases.signatures(str(tmp_path / "empty"), order_free=True)
    full = _base()["signatures"]
    assert full["ja-ordered"] != full["ja-moved"]
    assert free["ja-ordered"] == free["ja-moved"]
    assert len({free["ja-ordered"], free["zh-ordered"], free["ja-empty"]}) == 3


def _rp2_orders(language):
    """RP-2's four orders of its library, each as [(tier, name)]."""
    a = [(tier, name) for tier, name, _text in cases._rp2(language)]
    by = {t: [x for x in a if x[0] == t] for t in ("now", "soon", "goal")}
    b = [by["now"][-1]] + by["now"][:-1] + by["soon"] + by["goal"]
    c = [("now", by["soon"][0][1])] + by["now"] + by["soon"][1:] + by["goal"]
    d = by["now"][1:] + by["soon"] + [("goal", by["now"][0][1])] + by["goal"]
    return {"A": a, "B": b, "C": c, "D": d}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_rp2s_four_orders_have_one_order_free_signature(language):
    """The library as RP-2 reordered it, read through the manifest as Generate reads it (resolve_found_files): four
    orders, four full signatures, one order-free one. Then the order-free one moves for what isn't a move — a file's
    text edited, a file gone from the analysed tiers — as a re-plan must not take those."""
    root = os.environ["SURASURA_TEST_ROOT"]
    case = f"rp2-{language}"
    args = analyzer.parse_analysis_args(["--language", language])
    full, free = {}, {}
    for name, order in _rp2_orders(language).items():
        cases.build(root, case, order, preview=False)       # the switch is in no signature
        found = analyzer.resolve_found_files(language, verbose=False)
        assert len(found) == len(order)
        assert [os.path.basename(f[0]) for f in found] == [n for _t, n in order]
        full[name] = analyzer.compute_run_signature(language, found, args)
        free[name] = analyzer.compute_run_signature(language, found, args, order_free=True)
    assert len(set(full.values())) == 4, full
    assert len(set(free.values())) == 1, free
    assert free["A"] != full["A"]

    # An edited file: same order, another text.
    path = found[0][0]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + ("今日はいい天気ですね。" if language == "ja" else "今天天气很好。") + "\n")
    edited = analyzer.compute_run_signature(language, found, args, order_free=True)
    assert edited != free["A"]
    # A file gone from the analysed tiers (graduated, archived): not a re-plan either.
    assert analyzer.compute_run_signature(language, found[1:], args, order_free=True) not in (edited, free["A"])


def test_the_one_call_digest_is_the_chunked_one():
    """main() hashes its own signature in one call (json.dumps' C encoder); the journey check, chunk by chunk. The same
    parts give the same digest either way — non-ASCII paths, mtimes as floats, None for a file gone, nested lists."""
    parts = {"files": [["C:/ライブラリ/第1話.srt", [1759000000.123456, 4096], "HighPriority", 10, "subtitle"],
                       ["C:/library/gone.txt", None, "GoalContent", 2.5, "text"]],
             "known": '[true, 1759000000.5, 120]', "settings": '{"logic": {"weights": {"high": 10}}}',
             "args": ["ja", 0, 0, False, False, False, False, False, None, None, 3, "asis"],
             "engine": "2.5.0|schema19|rev30"}
    for order_free in (False, True):
        assert (analyzer.signature_digest(parts, order_free, chunked=False)
                == analyzer.signature_digest(parts, order_free) is not None)


def test_a_signature_that_cant_be_read_is_none_in_both_forms(monkeypatch):
    """The parts can't be read (the frequency-list folder can't be listed): no signature in either form, as before —
    the run then never skips, and the plan file carries none."""
    def _unreadable(*_args):
        raise OSError("User Files unreadable")

    monkeypatch.setattr(analyzer, "discover_yomitan_frequency_lists", _unreadable)
    args = analyzer.parse_analysis_args(["--language", "ja"])
    assert analyzer.run_signature_parts("ja", [], args) is None
    assert analyzer.compute_run_signature("ja", [], args) is None
    assert analyzer.compute_run_signature("ja", [], args, order_free=True) is None
    assert analyzer.signature_digest(None, order_free=True) is None
