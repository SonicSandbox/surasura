"""The engine's incremental move = its from-scratch re-plan (E1.1-fast-replan/05-tests.md §2, RUNBOOK E1.3.3).

A synthetic plan in the study's shape (seeded: Zipf-like word uses over files in three tiers, phrase rows, half
scores, words the list doesn't show, spelling ties, uses a phrase took, credits, siblings), 1,000 random drags per
seed, five seeds — single items and blocks, within a tier and across, to a tier's top or beside an anchor. After every
move the live numbers (Score, first places, *N new*, the priority order) equal a from-scratch `replan` of the same
order; every 50th move the whole result (the progressive list, Orth / Forms too) equals it, and equals E1.2's
reference replay (`tests/test_plan_file.py`). The parity with real Generates is `test_plan_engine.py`'s.
"""
import random

import pytest

from app import plan_engine
from tests.test_plan_file import replay

TIERS = ("now", "soon", "goal")


def synthetic_plan(seed, n_files=60, n_words=280, n_phrases=20):
    """A plan the engine accepts (`plan_engine._validate`), built the way a Generate's plan is shaped."""
    rnd = random.Random(seed)
    n_keys = n_words + n_phrases
    keys = []
    for k in range(n_keys):
        phrase = k >= n_words
        keys.append([f"語{k}" if not phrase else f"句{k}", f"ゴ{k}", phrase, rnd.random() < 0.1, 0])
    weights = [1.0 / (k + 1) ** 0.9 for k in range(n_words)]
    tiers = ["now"] * (n_files // 4) + ["soon"] * (n_files // 3)
    tiers += ["goal"] * (n_files - len(tiers))
    files, per_file = [], []
    tied = set(rnd.sample(range(n_words), 12))
    spellings = {k: [f"綴{k}a", f"綴{k}b", f"綴{k}c"] for k in tied}
    for f in range(n_files):
        files.append([f"{tiers[f]}/ep{f:03d}.srt", tiers[f], f"d{f}"])
        met = list(dict.fromkeys(rnd.choices(range(n_words), weights=weights, k=45)))
        main = []
        for k in met:
            u = 0 if rnd.random() < 0.03 else rnd.randint(1, 25)       # a file whose uses all went to a phrase
            main += (k, u)
            keys[k][4] += u
        ph = []
        for k in rnd.sample(range(n_words, n_keys), rnd.randint(0, 3)):
            u = rnd.randint(1, 4)
            ph += (k, u)
            keys[k][4] += u
        sp = [[k, rnd.sample(spellings[k], rnd.randint(1, 2)), rnd.sample(spellings[k], 1)] for k in met if k in tied]
        tokens = []
        for k in met:
            tokens += (k, rnd.randint(1, 30))
        given = []
        for k in rnd.sample(met, min(3, len(met))):
            given += (k, rnd.randint(1, 5))
        credits = []
        for k in rnd.sample(range(n_words), 2):
            credits += (k, rnd.randint(1, 3))
        phrases = list(ph)
        siblings = [[f"語{k}", rnd.randint(1, 4)] for k in rnd.sample(range(n_words), 2)]
        total = sum(tokens[1::2]) + rnd.randint(200, 2000)
        per_file.append({"f": f, "main": main, "ph": ph, "sp": sp,
                         "prog": [total, rnd.randint(50, total // 2), tokens, given, credits, phrases, siblings]})
    rows, ties = [], []
    for k, key in enumerate(keys):
        listed = key[4] > 0 and rnd.random() > 0.05
        rows.append([f"JPDB:{k}", "Outside" if key[2] else None, "", "test", key[0], "", ["一文。", "ep000.srt"]]
                    if listed else None)
        if k in tied:
            counts = {s: 4 for s in spellings[k]}
            ties.append([k, counts, dict(counts), None])
    header = {"format": 1, "language": "ja", "engine": "test", "run_signature": "r", "order_free_signature": "o",
              "store": {"epoch": None}, "weights": {"now": 10, "soon": 5, "goal": 2}, "floor": 1, "total_tokens": 0,
              "phrase_rows": True, "target_coverage": 0, "only_i_plus_one": False, "max_contexts": 1,
              "files": n_files, "keys": n_keys, "shared_phrases": []}
    plan = plan_engine.Plan(header, files, keys, rows, ties, per_file)
    plan_engine._validate(plan)
    return plan


def _as_dict(plan):
    return {"header": plan.header, "files": plan.files, "keys": plan.keys, "rows": plan.rows, "ties": plan.ties,
            "per_file": plan.per_file}


def _live(eng):
    """What `move` keeps in place: Score, first places, N new, the priority order."""
    r = eng.result()
    return (r.score, r.first, r.n_new, [(row["Word"], row["Reading"]) for row in r.priority])


def _order(eng):
    seq = eng.result().sequence
    tier = {f: TIERS[eng._tier[f]] for f in eng._order}
    return [(eng._ids[f], tier[f]) for f in eng._order], seq


def _random_move(rnd, eng):
    order, _seq = _order(eng)
    items = [item for item, _t in order]
    block = rnd.sample(items, 1 if rnd.random() < 0.8 else rnd.randint(2, 4))
    tier = rnd.choice(TIERS)
    in_tier = [item for item, t in order if t == tier and item not in block]
    where = rnd.random()
    if not in_tier or where < 0.2:
        return eng.move(block if len(block) > 1 else block[0], tier)
    anchor = rnd.choice(in_tier)
    if where < 0.6:
        return eng.move(block, tier, before_id=anchor)
    return eng.move(block if len(block) > 1 else block[0], tier, after_id=anchor)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_a_thousand_moves_keep_the_incremental_numbers_equal_to_a_replan(seed):
    plan = synthetic_plan(seed)
    eng = plan_engine.Engine(plan)
    referee = plan_engine.Engine(plan)
    rnd = random.Random(1000 + seed)
    for i in range(1, 1001):
        _random_move(rnd, eng)
        order, _seq = _order(eng)
        assert _live(eng) == _live_of(referee, order), (seed, i)
        if i % 50 == 0:
            got, want = eng.result(), referee.replan(order)
            for name in ("priority", "progressive", "first", "n_new", "score", "counts", "sequence"):
                assert getattr(got, name) == getattr(want, name), (seed, i, name)
            ref = replay(_as_dict(plan), [(plan_engine_index(plan, item), tier) for item, tier in order])
            assert [(r["Word"], r["Score"], r["Orth"], r["Forms"]) for r in ref["priority"]] == \
                [(r["Word"], r["Score"], r["Orth"], r["Forms"]) for r in got.priority], (seed, i)
            assert [(r["Sequence"], r["Word"], r["Known Count"], r["New %"]) for r in ref["progressive"]] == \
                [(r["Sequence"], r["Word"], r["Known Count"], r["New %"]) for r in got.progressive], (seed, i)


def _live_of(referee, order):
    referee.replan(order)
    return _live(referee)


def plan_engine_index(plan, item):
    return [entry[0] for entry in plan.files].index(item)


def test_places_run_out_and_every_item_is_numbered_afresh(monkeypatch):
    """Twenty drags into the same gap (a small gap here: forty halvings in the engine) (each one between the anchor and the last one dropped there) leave no room
    between two places: the engine numbers every item again, and the numbers still equal a replan."""
    monkeypatch.setattr(plan_engine, "_GAP", 1 << 8)
    plan = synthetic_plan(9)
    eng = plan_engine.Engine(plan)
    order, _seq = _order(eng)
    anchor = order[0][0]
    for item, _tier in order[-20:]:
        eng.move(item, "now", after_id=anchor)
        assert _live(eng) == _live_of(plan_engine.Engine(plan), _order(eng)[0])
    assert [item for item, _t in _order(eng)[0][1:21]] == [item for item, _t in reversed(order[-20:])]
    assert eng.renumbered > 0


def test_a_move_that_changes_nothing_reports_nothing():
    """A move onto its own place, or beside itself, touches no number."""
    plan = synthetic_plan(11)
    eng = plan_engine.Engine(plan)
    order, _seq = _order(eng)
    before = _live(eng)
    keys, items = eng.move(order[1][0], order[1][1], after_id=order[0][0])
    assert keys == [] and _live(eng) == before
    assert eng.move(order[3][0], order[3][1], before_id=order[3][0]) == ([], [])
