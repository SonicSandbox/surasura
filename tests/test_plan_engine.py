"""The fast re-plan's engine (app/plan_engine.py; E1.1-fast-replan/02-engine.md, RUNBOOK E1.3.2–E1.3.4).

What these tests prove, on real libraries (tests/plan_file_cases.py: the bundled samples, RP-2's Japanese and Chinese
libraries, and the every-word libraries where pieces, phrase-taken uses and siblings move a list):
  - parity (05 §1): the engine built from one Generate's plan, given another order — from scratch (`replan`) or by
    the moves that make it (`move`) — gives that order's Generate on every plan column: the priority list's order,
    Score, Occurrences, the tier counts, Orth / Forms, Tier; the progressive list's rows, places and percentages;
    first places; and Junban's match index (`anki_match.build_index(rows=…)` = from the CSV);
  - pins (02 §7) change no column, and come back grouped oldest first;
  - `check` names what moved since the plan; `load` refuses a damaged or foreign plan and holds no file open;
  - the engine imports nothing but the standard library and the app's pure helpers (rule 3).
The engine is checked against `tests/test_plan_file.py`'s `replay` too: E1.2's reference, kept small.
"""
import gzip
import json
import os
import shutil
import subprocess
import sys

import pytest

from app import analyzer, anki_match, plan_engine, plan_rules
from tests import plan_file_cases as cases
from tests.test_plan_file import (PRIORITY_COLUMNS, PROGRESSIVE_COLUMNS, _same, read_csv, read_run, replay,
                                  _rp2_orders)


# --------------------------------------------------------------------------------------------------------------- #
# The runs
# --------------------------------------------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Each case's library and its Generate, in its own order (a child process each, as the dashboard runs it)."""
    out = {}
    for case in cases.ALL_CASES:
        root = str(tmp_path_factory.mktemp(case))
        cases.build(root, case)
        cases.generate(root, case)
        out[case] = (root, read_run(root))
    return out


@pytest.fixture(scope="module")
def other_orders(runs, tmp_path_factory):
    """RP-2's other orders of the cases the parity test moves, each a full Generate of that order."""
    out = {}
    for case, name in ORDERED:
        language = cases.ALL_CASES[case][0]
        root = str(tmp_path_factory.mktemp(f"{case}-{name}"))
        cases.build(root, case, _orders(language)[name])
        cases.generate(root, case)
        out[(case, name)] = (root, read_run(root))
    return out


# B: a move within NOW · C: Soon -> NOW's front · D: NOW -> 6+ Months (each RP-2's, test_run_signature_forms.py) ·
# E: 6+ Months -> NOW's front (05 §1's Later -> NOW).
ORDERED = [("rp2-ja", "B"), ("rp2-ja", "C"), ("rp2-ja", "D"), ("rp2-ja", "E"), ("rp2-zh", "B"), ("rp2-zh", "C"),
           ("rp2-zh", "D"), ("rp2-zh", "E"), ("every-ja", "B"), ("every-ja", "D"), ("every-ja", "E"),
           ("every-ja-2", "C"), ("every-ja-2", "D"), ("every-ja-singles", "C")]


def _orders(language):
    orders = _rp2_orders(language)
    a = orders["A"]
    later = [x for x in a if x[0] == "goal"][-1]
    orders["E"] = [("now", later[1])] + [x for x in a if x != later]
    return orders


def _plan(root):
    return plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))


def _engine(root):
    plan = _plan(root)
    return plan, plan_engine.Engine(plan)


def _order_of(plan, order):
    """RP-2's [(tier, name)] as the engine's [(item_id, tier)] (item ids default to the plan's rel paths)."""
    by_name = {entry[0].rsplit("/", 1)[-1]: entry[0] for entry in plan.files}
    return [(by_name[name], tier) for tier, name in order]


def _results_dir(root):
    return os.path.join(root, "results")


def _check_parity(result, run):
    """The engine's result against a Generate's own files: both lists, column by column; first places."""
    _same(run["priority"], result.priority, PRIORITY_COLUMNS)
    _same(run["progressive"], result.progressive, PROGRESSIVE_COLUMNS)
    plan = run["plan"]
    seq = result.sequence
    for word, reading, *_rest in plan["keys"]:
        assert run["library_frequency"][f"{word}|{reading}"][4] == seq[result.first[(word, reading)]], (word, reading)


def _check_index(result, root, language, same_sentences=True):
    """Junban's index from the engine's rows = the index from the Generate's CSV, for both order modes. Example
    sentences (`contexts_of`) are the last Generate's until the next one (D1): equal only in the plan's own order."""
    for mode, name in (("content", "progressive_learning_list.csv"), ("priority", "priority_learning_list.csv")):
        from_csv = anki_match.build_index(os.path.join(_results_dir(root), name), want_contexts=True,
                                          language=language)
        from_rows = anki_match.build_index(rows=result.rows(mode), want_contexts=True, language=language)
        if not same_sentences:
            from_csv, from_rows = from_csv._replace(contexts_of=None), from_rows._replace(contexts_of=None)
        assert from_rows == from_csv, mode
        assert from_rows.rank_of and from_rows.journey_of, mode


# --------------------------------------------------------------------------------------------------------------- #
# Parity (05 §1)
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("case", list(cases.ALL_CASES))
def test_the_engine_in_the_plans_own_order_is_the_generate(runs, case):
    """Built from a plan, in that plan's own order: every plan column the run's CSVs hold, first places, Junban's
    index — and the same as E1.2's reference replay."""
    root, run = runs[case]
    plan, eng = _engine(root)
    result = eng.result()
    _check_parity(result, run)
    _check_index(result, root, cases.ALL_CASES[case][0])
    reference = replay(run["plan"], [(f, entry[1]) for f, entry in enumerate(run["plan"]["files"])])
    assert [(r["Word"], r["Reading"], r["Score"]) for r in reference["priority"]] == \
        [(r["Word"], r["Reading"], r["Score"]) for r in result.priority]


@pytest.mark.parametrize("case,name", ORDERED)
def test_a_replan_in_another_order_is_that_orders_generate(runs, other_orders, case, name):
    """Order A's plan re-planned from scratch into RP-2's order B, C or D = a full Generate of that order, on every
    plan column and on Junban's index (byte for byte, Japanese with set phrases and spelling ties, and Chinese)."""
    root, _run = runs[case]
    other_root, other = other_orders[(case, name)]
    plan, eng = _engine(root)
    result = eng.replan(_order_of(plan, _orders(cases.ALL_CASES[case][0])[name]))
    _check_parity(result, other)
    _check_index(result, other_root, cases.ALL_CASES[case][0], same_sentences=False)


def _moves_to(eng, plan, target):
    """Move the engine's items one by one into `target`'s order ([(item_id, tier)]), as a user drags them: each item,
    front to back, placed after the one before it (the first at its tier's top)."""
    prev = None
    for i, (item, tier) in enumerate(target):
        nxt = target[i + 1] if i + 1 < len(target) else None
        if prev is not None and prev[1] == tier:
            eng.move(item, tier, after_id=prev[0])
        elif (nxt is not None and nxt[1] == tier and i % 2
              and eng._tier[eng._f_of[nxt[0]]] == plan_engine._SLOT[tier]):
            eng.move(item, tier, before_id=nxt[0])      # before the next one: placed at its tier's top all the same
            eng.move(item, tier)
        else:
            eng.move(item, tier)
        prev = (item, tier)


@pytest.mark.parametrize("case,name", ORDERED)
def test_moves_that_make_another_order_give_that_orders_generate(runs, other_orders, case, name):
    """The incremental path: from order A, the drags that make order B / C / D (one item at a time, each kind — a move
    within NOW, Soon to NOW's front, NOW to 6+ Months) leave the engine equal to that order's Generate."""
    root, _run = runs[case]
    other_root, other = other_orders[(case, name)]
    plan, eng = _engine(root)
    _moves_to(eng, plan, _order_of(plan, _orders(cases.ALL_CASES[case][0])[name]))
    result = eng.result()
    _check_parity(result, other)
    _check_index(result, other_root, cases.ALL_CASES[case][0], same_sentences=False)


@pytest.mark.parametrize("case", ["rp2-ja", "rp2-zh", "every-ja"])
def test_a_move_and_its_reverse_give_the_first_order_back(runs, case):
    """A move, then its reverse (Later -> NOW's front and back; a block of two to Soon and back): every column as
    the Generate wrote it, and the live numbers equal to a fresh engine's."""
    root, run = runs[case]
    plan, eng = _engine(root)
    files = [(entry[0], entry[1]) for entry in plan.files]
    goal = [item for item, tier in files if tier == "goal"]
    now = [item for item, tier in files if tier == "now"]
    later = goal[-1]
    back_after = [item for item, tier in files if tier == "goal" and item != later]
    eng.move(later, "now")
    assert eng.result().sequence[later] == 1
    eng.move(later, "goal", after_id=back_after[-1])
    _check_parity(eng.result(), run)
    block = now[:2]
    keys, moved = eng.move(block, "soon")
    assert moved == block and keys
    eng.move(block, "now")
    _check_parity(eng.result(), run)


# --------------------------------------------------------------------------------------------------------------- #
# Pins (02 §7)
# --------------------------------------------------------------------------------------------------------------- #

def test_pins_change_no_column_and_come_back_oldest_first(runs):
    """A pin moves cards, never words: with items pinned (one of them not in the order at all, as a Finished show
    is), every column is the Generate's; `pinned` lists the groups oldest first, one pin command one group, a group's
    items in the order's sequence and an item outside the order last."""
    root, run = runs["rp2-ja"]
    plan, eng = _engine(root)
    items = [entry[0] for entry in plan.files]
    goal = [entry[0] for entry in plan.files if entry[1] == "goal"][0]
    pins = [(items[5], "2026-10-06T10:00:00"), (items[1], "2026-10-06T09:00:00"), (items[3], "2026-10-06T09:00:00"),
            ("Finished/a show I watched.srt", "2026-10-06T09:00:00"), (goal, "2026-10-06T11:00:00")]
    result = eng.replan([(entry[0], entry[1]) for entry in plan.files], pins=pins)
    _check_parity(result, run)
    assert result.pinned == [[items[1], items[3], "Finished/a show I watched.srt"], [items[5]], [goal]]
    eng.move(items[3], "now")                      # a move keeps the pins and re-lists the group in the new order
    assert eng.result().pinned[0][:2] == [items[3], items[1]]
    eng.set_pins([])
    assert eng.result().pinned == []


def test_pin_groups_is_one_rule_for_every_caller():
    """`plan_rules.pin_groups`: the engine's and Junban's writers' one grouping (03 §8)."""
    pins = [(7, "b"), (3, "a"), (9, "a"), (1, "c")]
    assert plan_rules.pin_groups(pins, place=lambda item: item) == [[3, 9], [7], [1]]
    assert plan_rules.pin_groups([], place=lambda item: item) == []


# --------------------------------------------------------------------------------------------------------------- #
# The order the engine is given
# --------------------------------------------------------------------------------------------------------------- #

def test_an_item_the_plan_doesnt_hold_is_refused_and_one_left_out_is_dropped(runs):
    """A new item means the library changed (Generate first); an item that left the counted tiers is dropped from the
    order (02 §6): its uses leave Score and the counts, the others keep their places."""
    root, _run = runs["rp2-ja"]
    plan, eng = _engine(root)
    order = [(entry[0], entry[1]) for entry in plan.files]
    with pytest.raises(plan_engine.PlanError, match="Generate first"):
        eng.replan(order + [("NewEpisode.srt", "goal")])
    with pytest.raises(plan_engine.PlanError, match="twice"):
        eng.replan(order + order[:1])
    with pytest.raises(plan_engine.PlanError, match="NOW, then Soon"):
        eng.replan(list(reversed(order)))
    left = order[0][0]
    result = eng.replan(order[1:])
    assert result.dropped == [left] and left not in result.sequence
    full = plan_engine.Engine(plan).result()
    assert sum(result.score.values()) < sum(full.score.values())


def test_front_is_the_first_words_of_junbans_order(runs):
    """`front(n)`: the first n distinct words of the progressive list ("content") or the priority list."""
    root, _run = runs["rp2-ja"]
    _plan_, eng = _engine(root)
    result = eng.result()
    front = result.front(20)
    assert len(front) == 20 == len(set(front))
    assert front[0] == (result.progressive[0]["Word"], result.progressive[0]["Reading"])
    assert result.front(5, order_mode="priority") == [(r["Word"], r["Reading"]) for r in result.priority[:5]]
    with pytest.raises(NotImplementedError):
        result.front(5, items={"x"})


# --------------------------------------------------------------------------------------------------------------- #
# check (01 §1, 04 §4)
# --------------------------------------------------------------------------------------------------------------- #

def _parts(root, case):
    """The run signature's parts for the library under `root` now, in a child process (its own root)."""
    language = cases.ALL_CASES[case][0]
    extra = cases.ALL_CASES[case][3]
    code = ("import sys, json\nfrom app import analyzer\n"
            "args = analyzer.parse_analysis_args(['--language', sys.argv[1]] + sys.argv[2:])\n"
            "print(json.dumps(analyzer.run_signature_parts(sys.argv[1], analyzer.resolve_found_files(sys.argv[1], "
            "False), args), default=str))\n")
    p = subprocess.run([sys.executable, "-c", code, language] + extra, cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_check_names_what_moved_since_the_plan(tmp_path):
    """None for the library as planned; "replan-now" for the known words, the word lists or files only gone from the
    counted tiers; "generate-first" for a file added or changed, a setting, another language or version, a run that
    didn't finish, another store; "stand-aside" for what the engine can't replay exactly."""
    root = str(tmp_path / "lib")
    case = "rp2-ja"
    cases.build(root, case)
    cases.generate(root, case)
    plan = _plan(root)
    h = plan.header
    stamp = analyzer.read_run_stamp(_results_dir(root))
    engine = h["engine"]
    parts = _parts(root, case)

    def check(**over):
        a = dict(plan=plan, language="ja", engine=engine, run_stamp=stamp, signature_parts=parts, epoch=None)
        a.update(over)
        return plan_engine.check(**a)

    assert check() is None
    assert check(language="zh") == ("generate-first", "language")
    assert check(engine=engine + "x") == ("generate-first", "engine")
    assert check(run_stamp=None) == ("generate-first", "unstamped")
    assert check(run_stamp="another run") == ("generate-first", "unstamped")
    assert check(epoch="another store") == ("generate-first", "epoch")
    assert check(signature_parts=None) == ("generate-first", "signature")
    assert check(signature_parts=dict(parts, known=["moved"])) == ("replan-now", ("known",))
    assert check(signature_parts=dict(parts, known=["moved"], lists=[None, None, [1, 2]])) == \
        ("replan-now", ("known", "lists"))
    assert check(signature_parts=dict(parts, settings="another")) == ("generate-first", "settings")
    gone = dict(parts, files=parts["files"][1:])
    assert check(signature_parts=gone) == ("replan-now", ("files-removed",))
    changed = [list(entry) for entry in parts["files"]]
    changed[0][1] = [1, 2]
    assert check(signature_parts=dict(parts, files=changed)) == ("generate-first", "files")
    added = parts["files"] + [[parts["files"][0][0] + "x", [1, 2], "Manual", 10, "subtitle"]]
    assert check(signature_parts=dict(parts, files=added)) == ("generate-first", "files")
    # The same library in another order (labels, weights and order out): nothing moved.
    moved = [list(entry) for entry in reversed(parts["files"])]
    for entry in moved:
        entry[2], entry[3] = "LowPriority", 5
    assert check(signature_parts=dict(parts, files=moved)) is None
    # A plan whose whole signature and parts disagree, or from before the parts were written: never a guess.
    assert check(signature_parts=dict(parts, known=["moved"])) == ("replan-now", ("known",))
    plan.header = dict(h, order_free_signature="stale")
    assert check() == ("generate-first", "signature")
    plan.header = {k: v for k, v in h.items() if k != "order_free_parts"}
    assert check(signature_parts=dict(parts, known=["moved"])) == ("generate-first", "signature")
    plan.header = h
    assert check(signature_parts={"files": object()}) == ("generate-first", "signature")
    # What the engine can't replay exactly.
    for name, value, reason in (("target_coverage", 90, "coverage"), ("only_i_plus_one", True, "i+1"),
                                ("shared_phrases", [0], "shared-phrase"),
                                ("weights", {"now": 10.5, "soon": 5, "goal": 2}, "weights")):
        plan.header = dict(h, **{name: value})
        assert check() == ("stand-aside", reason)
        with pytest.raises(plan_engine.PlanError, match="stands aside"):
            plan_engine.Engine(plan)
    plan.header = h


# --------------------------------------------------------------------------------------------------------------- #
# load (01 §7)
# --------------------------------------------------------------------------------------------------------------- #

def _write(path, lines):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_a_damaged_or_foreign_plan_is_refused_whole(runs, tmp_path):
    """Missing, cut short, a flipped byte (gzip's CRC), a line that isn't JSON, another format, tables that don't fit
    the header, uses that don't add up to Occurrences, an index out of range: each a PlanError, never half a plan."""
    root, _run = runs["rp2-ja"]
    good = os.path.join(_results_dir(root), analyzer.PLAN_FILE)
    with open(good, "rb") as f:
        data = f.read()
    bad = str(tmp_path / "plan.json.gz")

    def refused(match):
        with pytest.raises(plan_engine.PlanError, match=match):
            plan_engine.load(bad)

    refused("no plan file")
    with open(bad, "wb") as f:
        f.write(data[: len(data) // 2])
    refused("damaged")
    flipped = bytearray(data)
    flipped[len(flipped) // 2] ^= 0xFF
    with open(bad, "wb") as f:
        f.write(bytes(flipped))
    refused("damaged")
    with gzip.open(bad, "wb") as f:
        f.write(gzip.decompress(data) + b"{not json\n")
    refused("isn't JSON")

    lines = _lines(good)
    header, rest = lines[0], lines[1:]
    for broken, match in ((dict(header, format=2), "format"), (dict(header, files=header["files"] + 1), "files"),
                          (dict(header, keys=header["keys"] - 1), "keys"),
                          ({k: v for k, v in header.items() if k != "weights"}, "weights")):
        _write(bad, [broken] + rest)
        refused(match)
    files = [line for line in rest if "f" in line]
    tables = [line for line in rest if "f" not in line]
    first = dict(files[0], main=list(files[0]["main"]))
    first["main"][1] += 1                                                   # one use more than Occurrences
    _write(bad, [header] + tables + [first] + files[1:])
    refused("add up")
    first["main"][0] = header["keys"] + 5                                   # an index past the keys
    _write(bad, [header] + tables + [first] + files[1:])
    refused("damaged")
    _write(bad, [header] + tables + files[1:] + files[:1])                  # files out of order
    refused("out of order")
    # Valid JSON, wrong values (the adversary's hostile plans): refused whole, never a crash later.
    keys_line = next(i for i, line in enumerate(tables) if "keys" in line)
    sp_file = next(i for i, line in enumerate(files) if line["sp"])
    for mutate, match in (
            (lambda t, f: t[keys_line]["keys"][1].__setitem__(slice(0, 2), t[keys_line]["keys"][0][:2]), "twice"),
            (lambda t, f: f[0].__setitem__("main", [f[0]["main"][0], 0] + f[0]["main"][2:]), "damaged"),
            (lambda t, f: f[sp_file].__setitem__("sp", 7), "spellings"),
            (lambda t, f: f[0]["prog"].__setitem__(0, "100"), "progressive"),
            (lambda t, f: f[0]["prog"].__setitem__(6, [["x", 1, 2]]), "progressive"),
            (lambda t, f: t[0][next(iter(t[0]))][0].__setitem__(1, ["now"]), "damaged")):
        t2, f2 = json.loads(json.dumps(tables)), json.loads(json.dumps(files))
        mutate(t2, f2)
        _write(bad, [header] + t2 + f2)
        refused(match)
    _write(bad, [header] + tables + files)
    assert plan_engine.load(bad).header["keys"] == header["keys"]


def test_load_holds_no_file_open(runs, tmp_path):
    """The loader reads the bytes and closes before decoding: a Generate replacing the plan right after (Windows
    refuses to replace a file someone holds open) succeeds."""
    root, _run = runs["rp2-zh"]
    path = str(tmp_path / "plan.json.gz")
    shutil.copy(os.path.join(_results_dir(root), analyzer.PLAN_FILE), path)
    plan = plan_engine.load(path)
    newer = str(tmp_path / "newer.tmp")
    shutil.copy(path, newer)
    os.replace(newer, path)
    assert plan.header["language"] == "zh"


# --------------------------------------------------------------------------------------------------------------- #
# Pure (rule 3, E1.3.5)
# --------------------------------------------------------------------------------------------------------------- #

def test_the_engine_is_pure():
    """Imported alone, in a fresh interpreter, the engine brings in no Qt, Tk, pandas, numpy, tokenizer, analyzer,
    settings, store or Junban — and its own sources import only the standard library and the app's pure helpers."""
    code = ("import sys\nimport app.plan_engine\n"
            "bad = [m for m in sys.modules if m.split('.')[0] in ('tkinter', '_tkinter', 'PyQt6', 'PyQt5', 'PySide6',"
            " 'pandas', 'numpy', 'fugashi', 'jieba', 'modules', 'requests')"
            " or m in ('app.analyzer', 'app.settings_manager', 'app.library_store', 'app.token_index', 'app.path_utils')]\n"
            "print(bad)\n")
    p = subprocess.run([sys.executable, "-c", code], cwd=cases.REPO, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "[]"
    import ast
    STDLIB = getattr(sys, "stdlib_module_names", None) or {      # Python 3.9 has no list: the ones these files use
        "bisect", "gzip", "json", "zlib", "array", "hashlib", "re"}
    app_allowed = {"app", "app.plan_rules", "app.unicode_ranges", "app.jmdict_data"}
    for name in ("plan_engine.py", "plan_rules.py"):
        with open(os.path.join(cases.REPO, "app", name), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                found = [node.module if node.module != "app" else f"app.{a.name}" for a in node.names]
            else:
                continue
            for module in found:
                assert module.split(".")[0] in STDLIB or module in app_allowed, (name, module)
