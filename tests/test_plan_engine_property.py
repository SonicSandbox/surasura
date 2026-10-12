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
            u = rnd.randint(1, 25)
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
    for k, key in enumerate(keys):              # every key on the list is met somewhere (Occurrences >= the floor)
        if key[4] == 0:
            per_file[-1]["ph" if key[2] else "main"] += (k, 1)
            key[4] = 1
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
            _against_replay(plan, eng, order, (seed, i))


def _live_of(referee, order):
    referee.replan(order)
    return _live(referee)


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


# --------------------------------------------------------------------------------------------------------------- #
# Placement against Store.move, and what a move reports (adversary rows 3, 5, 9)
# --------------------------------------------------------------------------------------------------------------- #

def _store_move(order, block, tier, before=None, after=None):
    """`Store.move`'s placement on a plain list of (item, tier), written apart from the engine: the block in its
    current relative order, contiguous before / after the anchor, or at the top of `tier`."""
    in_block = set(block)
    moved = [item for item, _t in order if item in in_block]
    rest = [(item, t) for item, t in order if item not in in_block]
    names = [item for item, _t in rest]
    if before is not None:
        at = names.index(before)
    elif after is not None:
        at = names.index(after) + 1
    else:
        at = sum(1 for _item, t in rest if TIERS.index(t) < TIERS.index(tier))
    return rest[:at] + [(item, tier) for item in moved] + rest[at:]


def _against_replay(plan, eng, order, tag):
    """Every column of both lists, first places and N new against E1.2's replay of `order` — not the engine's own."""
    result = eng.result()
    assert [(eng._ids[f], TIERS[eng._tier[f]]) for f in eng._order] == order, (tag, "placement")
    index = {entry[0]: f for f, entry in enumerate(plan.files)}
    ref = replay(_as_dict(plan), [(index[item], tier) for item, tier in order])
    columns = ("Word", "Reading", "Score", "Count (High)", "Count (Low)", "Count (Goal)", "Orth", "Forms", "Tier")
    assert [tuple(r[c] for c in columns) for r in ref["priority"]] == \
        [tuple(r[c] for c in columns) for r in result.priority], (tag, "priority")
    columns = ("Sequence", "Source File", "Word", "Reading", "Score", "Occurrences (File)", "Known Count",
               "Total Count", "Baseline %", "Current %", "New %", "Orth", "Forms", "Tier")
    assert [tuple(r[c] for c in columns) for r in ref["progressive"]] == \
        [tuple(r[c] for c in columns) for r in result.progressive], (tag, "progressive")
    n_new = {}
    for k, key in enumerate(plan.keys):
        seq = ref["first"][k]
        item = None if seq is None else order[seq - 1][0]
        assert result.first.get((key[0], key[1])) == item, (tag, "first", key)
        if item is not None:
            n_new[item] = n_new.get(item, 0) + 1
    assert {item: result.n_new[item] for item, _t in order} == {item: n_new.get(item, 0) for item, _t in order}


@pytest.mark.parametrize("seed,gap,short", [(seed, gap, short) for seed in (1, 2, 3, 4) for gap in (1 << 40, 3)
                                            for short in (256, 4, 1)])
def test_every_move_is_placed_as_the_store_places_it_and_equals_the_reference(monkeypatch, seed, gap, short):
    """150 drags per seed — single items and blocks of up to six across tiers, a whole tier emptied and refilled,
    before / after anchors and tier tops, three items dropped first; with gaps of 3 places run out every few moves,
    and with `short` 1 every moved word finds its next file by walking the order (a common word's way), with 4 the
    common and the rare words' ways side by side (a replan's first files too) — each checked
    against a model of Store.move's placement and E1.2's replay, on every column."""
    monkeypatch.setattr(plan_engine, "_GAP", gap)
    monkeypatch.setattr(plan_engine, "_SHORT", short)
    plan = synthetic_plan(seed, n_files=24, n_words=120, n_phrases=10)
    eng = plan_engine.Engine(plan)
    rnd = random.Random(seed)
    order = [(entry[0], entry[1]) for entry in plan.files]
    dropped = set(rnd.sample([item for item, _t in order], 3))
    order = [(item, t) for item, t in order if item not in dropped]
    eng.replan(order)
    _against_replay(plan, eng, order, (seed, 0))
    for i in range(1, 151):
        items = [item for item, _t in order]
        block = rnd.sample(items, 1 if rnd.random() < 0.6 else rnd.randint(2, 6))
        tier = rnd.choice(TIERS)
        if rnd.random() < 0.05:                     # a whole tier moved away (emptied), refilled by later moves
            source = rnd.choice(TIERS)
            block = [item for item, t in order if t == source] or block
            tier = rnd.choice([t for t in TIERS if t != source])
        in_tier = [item for item, t in order if t == tier and item not in block]
        where = rnd.random()
        before = after = None
        if in_tier and where >= 0.25:
            if where < 0.6:
                before = rnd.choice(in_tier)
            else:
                after = rnd.choice(in_tier)
        eng.move(set(block) if i % 7 == 0 else block, tier, before_id=before, after_id=after)
        order = _store_move(order, block, tier, before, after)
        _against_replay(plan, eng, order, (seed, i))
    if gap == 3:
        assert eng.renumbered > 0


def test_a_move_reports_the_words_whose_numbers_changed_and_no_other():
    """A drag that leaves the order as it was reports nothing; a move between two tiers of the same weight reports
    every word whose tier counts changed (they feed Junban's ✦ / ⚖ marks) though no Score moved."""
    plan = synthetic_plan(11)
    eng = plan_engine.Engine(plan)
    order, _seq = _order(eng)
    a, x = order[0][0], order[1][0]
    eng.move(order[-1][0], "now", after_id=x)       # places no longer evenly spaced
    before = _live(eng)
    keys, items = eng.move(x, "now", after_id=a)    # the order stays A X …
    assert keys == [] and items == [x] and _live(eng) == before
    plan.header["weights"] = {"now": 5, "soon": 5, "goal": 2}
    eng = plan_engine.Engine(plan)
    order, _seq = _order(eng)
    mover = next(item for item, t in order if t == "soon")
    last_now = [item for item, t in order if t == "now"][-1]
    r0 = eng.result()
    keys, _items = eng.move(mover, "now", after_id=last_now)
    r1 = eng.result()
    moved = {k for k in r0.counts if r0.counts[k] != r1.counts[k]}
    assert moved and set(keys) == moved | {k for k in r0.first if r0.first[k] != r1.first[k]}
    assert r0.score == r1.score
    # NOW's first item to NOW's end: no count or Score moves, but first items do — and those are reported.
    now = [item for item, t in _order(eng)[0] if t == "now"]
    r0 = eng.result()
    keys, _items = eng.move(now[0], "now", after_id=now[-1])
    r1 = eng.result()
    firsts = {k for k in r0.first if r0.first[k] != r1.first[k]}
    assert firsts and set(keys) == firsts and r0.counts == r1.counts


def test_any_collection_of_ids_is_a_block():
    """As Store.move takes any iterable: a set, a dict's keys, a generator."""
    plan = synthetic_plan(12)
    for ids in (lambda o: {o[3][0], o[4][0]}, lambda o: {o[3][0]: 1, o[4][0]: 2}.keys(),
                lambda o: (item for item in (o[3][0], o[4][0]))):
        eng = plan_engine.Engine(plan)
        order, _seq = _order(eng)
        _keys, items = eng.move(ids(order), "goal")
        assert sorted(items) == sorted([order[3][0], order[4][0]])
        assert [item for item, t in _order(eng)[0] if t == "goal"][:2] == [order[3][0], order[4][0]]


# --------------------------------------------------------------------------------------------------------------- #
# Arrivals (E2.2 D9): `add` among the moves
# --------------------------------------------------------------------------------------------------------------- #

def _arrival(rnd, plan, number):
    """A synthetic arrival record (`arrivals.record`'s shape) for `plan`: words, phrase rows, tied spellings with their
    counts, a progressive line."""
    keys = plan.keys
    words = [k for k, key in enumerate(keys) if not key[2]]
    phrases = [k for k, key in enumerate(keys) if key[2]]
    ties = {tie[0]: tie for tie in plan.ties}
    met = list(dict.fromkeys(rnd.sample(words, rnd.randint(1, 30))))
    main, sp, spc, tokens = [], [], {}, []
    for k in met:
        u = rnd.randint(1, 12)
        main += (k, u)
        tokens += (k, rnd.randint(1, 20))
        if k in ties:
            spelled = rnd.sample(list(ties[k][1]), rnd.randint(1, 2))
            sp.append([k, spelled, spelled[:1]])
            spc[k] = [{s: rnd.randint(1, 3) for s in spelled}, {spelled[0]: 1}]
    ph = []
    for k in rnd.sample(phrases, rnd.randint(0, 2)):
        ph += (k, rnd.randint(1, 3))
    total = sum(tokens[1::2]) + rnd.randint(50, 500)
    return {"main": main, "ph": ph, "sp": sp, "spc": spc, "plan": plan.header["run_signature"], "keys": len(keys),
            "name": f"new{number:03d}.srt",
            "prog": [total, rnd.randint(10, total // 2), tokens, [], [], list(ph), []]}


def _with_arrivals(plan, added):
    """`plan` as a Generate of its files and the arrivals (`added`: [(item, record, tier)]) would write it, for E1.2's
    replay: their lines appended, Occurrences and the tied counts grown."""
    keys = [list(key) for key in plan.keys]
    ties = {tie[0]: [tie[0], dict(tie[1]), dict(tie[2]), tie[3]] for tie in plan.ties}
    files, per_file = list(plan.files), list(plan.per_file)
    for item, rec, tier in added:
        for table in ("main", "ph"):
            for k, u in zip(rec[table][0::2], rec[table][1::2]):
                keys[k][4] += u
        for k, (orths, surfaces) in rec["spc"].items():
            for into, more in ((ties[k][1], orths), (ties[k][2], surfaces)):
                for s, n in more.items():
                    into[s] = into.get(s, 0) + n
        files.append([item, tier, item])
        per_file.append({"f": len(per_file), "main": rec["main"], "ph": rec["ph"], "sp": rec["sp"],
                         "prog": rec["prog"]})
    header = dict(plan.header, files=len(files))
    return plan_engine.Plan(header, files, keys, plan.rows, list(ties.values()), per_file)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_arrivals_among_moves_keep_the_incremental_numbers_equal_to_a_replan(seed):
    """400 operations per seed, one in eight an arrival (`add` at a tier's top or beside an anchor), the rest drags:
    after each, the live numbers equal a from-scratch `replan` of the same order by an engine holding the same
    arrivals (`replan` accepts added items); every 40th, every column equals it and E1.2's replay of a plan holding
    the arrivals' lines."""
    plan = synthetic_plan(seed)
    eng, referee = plan_engine.Engine(plan), plan_engine.Engine(plan)
    rnd = random.Random(2000 + seed)
    added = []
    for i in range(1, 401):
        if rnd.random() < 0.125:
            order, _seq = _order(eng)
            tier = rnd.choice(TIERS)
            in_tier = [item for item, t in order if t == tier]
            rec = _arrival(rnd, plan, len(added))
            item = f"{tier}/new{len(added):03d}.srt"
            where, before, after = rnd.random(), None, None
            if in_tier and where >= 0.3:
                before, after = (rnd.choice(in_tier), None) if where < 0.6 else (None, rnd.choice(in_tier))
            keys, items = eng.add(item, rec, tier, before_id=before, after_id=after,
                                  exact=i % 2 == 0, moved=() if i % 2 == 0 else ("floor",))
            assert items == [item] and len(keys) == len(rec["main"]) // 2 + len(rec["ph"]) // 2
            referee.add(item, rec, "goal")
            added.append((item, rec, tier))
            assert _order(eng)[0] == _store_add(order, item, tier, before, after), (seed, i, "placement")
        else:
            _random_move(rnd, eng)
        order, _seq = _order(eng)
        assert _live(eng) == _live_of(referee, order), (seed, i)
        if i % 40 == 0:
            got, want = eng.result(), referee.replan(order)
            for name in ("priority", "progressive", "first", "n_new", "score", "counts", "sequence"):
                assert getattr(got, name) == getattr(want, name), (seed, i, name)
            assert got.added == [item for item, _r, _t in added]
            assert got.provisional == [item for n, (item, _r, _t) in enumerate(added) if item in got.reasons]
            _against_replay(_with_arrivals(plan, added), eng, order, (seed, i))


def _store_add(order, item, tier, before=None, after=None):
    """Where `Store.move` places a new item (`_store_move`'s rule for a block of one)."""
    return _store_move(order + [(item, tier)], [item], tier, before, after)


def test_an_arrival_read_against_another_plan_or_damaged_is_refused():
    """`add` checks the record as the loader checks a plan's lines: another plan's (its run, its words' count), a word
    out of range, a phrase row in the words' table, a tied spelling for an untied word — a PlanError, the engine
    unchanged; an item the plan holds already, an unknown tier or an anchor in another tier too."""
    plan = synthetic_plan(13)
    eng = plan_engine.Engine(plan)
    before = _live(eng)
    rec = _arrival(random.Random(5), plan, 0)
    untied = next(k for k in range(len(plan.keys)) if k not in {tie[0] for tie in plan.ties} and not plan.keys[k][2])
    phrase = next(k for k, key in enumerate(plan.keys) if key[2])
    for damaged in (dict(rec, plan="another run"), dict(rec, keys=len(plan.keys) + 1),
                    dict(rec, main=rec["main"] + [len(plan.keys), 1]), dict(rec, main=rec["main"] + [phrase, 1]),
                    dict(rec, main=rec["main"][:2] + rec["main"][:2]), dict(rec, sp=[[untied, ["x"], []]]),
                    dict(rec, prog=[1, 2, [], [], [], [], []]), dict(rec, spc={"x": [{}, {}]}),
                    dict(rec, main=[rec["main"][0], 0] + rec["main"][2:]),            # a use of none
                    dict(rec, spc={str(len(plan.keys)): [{}, {}]}), None):           # a word out of range
        with pytest.raises(plan_engine.PlanError):
            eng.add("goal/new.srt", damaged, "goal")
    first = plan.files[0][0]
    with pytest.raises(plan_engine.PlanError, match="already"):
        eng.add(first, rec, "goal")
    with pytest.raises(plan_engine.PlanError, match="tier"):
        eng.add("goal/new.srt", rec, "later")
    with pytest.raises(plan_engine.PlanError, match="anchor"):
        eng.add("goal/new.srt", rec, "goal", after_id=first)
    assert _live(eng) == before and eng.result().added == []


def test_an_arrival_keeps_its_own_file_name_whatever_its_item_id():
    """The progressive list's Source File for an added file is its record's file name (`arrivals.record`'s "name"),
    never a piece of its item id: the library store's item ids aren't paths."""
    plan = synthetic_plan(17)
    eng = plan_engine.Engine(plan)
    rec = _arrival(random.Random(9), plan, 7)
    eng.add("item:42", rec, "now")
    result = eng.result()
    seq = result.sequence["item:42"]
    rows = [row for row in result.progressive if row["Sequence"] == seq]
    assert rows, "the arrival's words reach the progressive list"
    assert {row["Source File"] for row in rows} == {"new007.srt"}


def test_files_added_only_when_every_plan_file_is_still_there_unchanged():
    """`check(..., added=)`'s rule (`_only_added`): the library is the plan's files, each unchanged, plus files the
    engine added — never when a plan file left or changed as well, and never for a plan whose files don't all carry
    their digest (it can't tell which are its own)."""
    from types import SimpleNamespace
    from app import plan_rules
    entries = [[f"HighPriority/作品/第{n:02d}話.srt", [1700000000 + n, 4000 + n], "HighPriority", 10, "subtitle"]
               for n in range(1, 4)]
    one, two, new = (plan_rules.file_digest(entry) for entry in entries)
    plan = SimpleNamespace(files=[[entries[0][0], "now", one], [entries[1][0], "now", two]])
    parts = {"files": entries}
    assert plan_engine._only_added(plan, parts, [new]) is True
    assert plan_engine._only_added(plan, {"files": [entries[0], entries[2]]}, [new]) is False, "a plan file left"
    assert plan_engine._only_added(plan, parts, []) is False, "nothing the engine added"
    no_digest = SimpleNamespace(files=[[entries[0][0], "now"], [entries[1][0], "now", two]])
    assert plan_engine._only_added(no_digest, {"files": [entries[1], entries[2]]}, [new]) is False
