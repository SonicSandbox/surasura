"""*Sentences per word*'s All: `logic.context.max_contexts` 0 (J-SET; Sonic Q33, "up to all you have").

What a wrong answer would cost: a learner who picks All gets NO sentences (0 read as a count: the list's columns, the
plan's re-pick and word_stats.json all wrote none before), or a list whose first sentences are not the ones three gave
(All must only add), or a fast re-plan that disagrees with the Generate it re-plans (F7: a re-pick in the plan's own
order is that Generate's pick).

Real data: RP-2's Japanese and Chinese libraries (`tests/plan_file_cases.py`: the bundled samples and
tests/Test Resources), each Generated twice in one root — Sentences per word 3, then All.
"""
import csv
import json
import os

import pytest

from app import analyzer, plan_engine, plan_rules
from tests import plan_file_cases as cases

CASES = ("rp2-ja", "rp2-zh")


def _rows(root, name):
    with open(os.path.join(root, "results", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _sentences(row):
    """A row's sentences in order: its Context columns, the empty ones left out."""
    n = 1
    out = []
    while f"Context {n}" in row:
        if row[f"Context {n}"]:
            out.append(row[f"Context {n}"])
        n += 1
    return out


def _columns(row):
    return sum(1 for column in row if column.startswith("Context "))


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = {}
    for case in CASES:
        root = str(tmp_path_factory.mktemp(case.replace("-", "_")))
        cases.build(root, case)
        cases.generate(root, case, extra_args=["--max-contexts=3"])
        three = {name: _rows(root, name) for name in ("priority_learning_list.csv", "progressive_learning_list.csv")}
        cases.generate(root, case, extra_args=["--max-contexts=0"])
        every = {name: _rows(root, name) for name in ("priority_learning_list.csv", "progressive_learning_list.csv")}
        out[case] = (root, three, every)
    return out


def test_all_is_every_candidate_the_list_keeps_and_never_none():
    """The limit under All is the pool's whole size (its first, the shortlist, Finished, the nearest files, the audio
    slot); a number is itself; a hand-edited number below 0 is All too."""
    every = 1 + plan_rules.POOL + plan_rules.FINISHED_POOL + plan_rules.NEAR_FILES + 1
    assert plan_rules.context_limit(0) == plan_rules.context_limit(-2) == every
    assert [plan_rules.context_limit(n) for n in (1, 3, 10, 15)] == [1, 3, 10, 15]
    assert plan_rules.context_columns(0, [2, 5, 1]) == 5
    assert plan_rules.context_columns(0, []) == 0
    assert plan_rules.context_columns(4, [9, 1]) == 4


@pytest.mark.parametrize("case", CASES)
def test_all_gives_every_word_the_sentences_three_gave_first_and_more_where_there_are(runs, case):
    """The same words, each with the same first sentences as Sentences per word 3, and some with more; no word that
    had a sentence has none."""
    _root, three, every = runs[case]
    for name in three:
        assert len(three[name]) == len(every[name]), name
        more = 0
        for a, b in zip(three[name], every[name]):           # (the same order: the sentences never move a row)
            assert (a["Word"], a["Reading"]) == (b["Word"], b["Reading"])
            got, had = _sentences(b), _sentences(a)
            assert got[:len(had)] == had, (name, a["Word"])
            assert len(got) >= len(had)
            more += len(got) > 3
        assert more > 0, f"{case} {name}: no word got more than three sentences under All"


@pytest.mark.parametrize("case", CASES)
def test_all_writes_as_many_columns_as_its_widest_row_and_the_plan_keeps_all(runs, case):
    root, three, every = runs[case]
    rows = every["priority_learning_list.csv"]
    widest = max(len(_sentences(r)) for r in rows)
    assert widest > 3
    assert all(_columns(r) == widest for r in rows)
    assert all(_columns(r) == 3 for r in three["priority_learning_list.csv"])
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))
    assert plan.header["max_contexts"] == 0                    # the re-pick picks All too, never a count of 0
    with open(os.path.join(root, "results", "word_stats.json"), encoding="utf-8") as f:
        stats = json.load(f)
    longest = max(sum(1 for k in entry if k.startswith("final_context_")) for entry in stats.values()
                  if isinstance(entry, dict))
    assert longest == widest


@pytest.mark.parametrize("case", CASES)
def test_the_plans_re_pick_under_all_is_the_generates_pick(runs, case):
    """F7 under All: re-picked in the plan's own order, every row's sentences and their columns are the Generate's."""
    from tests.test_plan_engine import _texts
    root, _three, every = runs[case]
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))
    csv_rows = {(r["Word"], r["Reading"]): r for r in every["priority_learning_list.csv"]}
    if plan_rules.SENTENCE_TABLE >= 2:
        # release 2: a format-5 plan holds no sentences; a re-plan's are the one reader's, asked of this Generate's
        # table in its own order (the redraw's call, SPEC § 5.2): under All, every row's are the Generate's
        from tests.test_e_redraw import _reader
        assert plan.header["format"] == 5
        got = _reader(root, cases.ALL_CASES[case][0], list(csv_rows), max_contexts=0)
        for key, want in csv_rows.items():
            columns = [want[f"{c} {i}"] for i in range(1, _columns(want) + 1) for c in ("Context", "Src")]
            while columns and not columns[-1] and not columns[-2]:
                del columns[-2:]            # (a row with fewer sentences than columns is padded with "")
            assert got.get(key, []) == columns, key
        return
    result = plan_engine.Engine(plan).result(pick=True, texts=_texts(root, cases.ALL_CASES[case][0]))
    assert len(result.priority) == len(csv_rows)
    for row in result.priority:
        want = csv_rows[(row["Word"], row["Reading"])]
        columns = [c for c in want if c.startswith(("Context ", "Src "))]
        assert {c: row.get(c, "") for c in columns} == {c: want[c] for c in columns}, row["Word"]
        assert _columns(row) == _columns(want)
    # the plan read without a re-pick keeps the Generate's sentences, as many columns
    kept = plan_engine.Engine(plan).result()
    assert {_columns(r) for r in kept.priority} == {_columns(next(iter(csv_rows.values())))}
