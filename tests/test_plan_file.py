"""The plan file (results/plan.json.gz; E1.1-fast-replan/01-plan-file.md, RUNBOOK E1.2.2).

Every full Generate writes, last before its stamp, what a re-plan needs to recompute the order's columns for any order
of the same files. These tests prove:
  - every output a Generate wrote before is byte for byte the same (the base's hashes, tests/plan_file_cases.py);
  - the plan adds up (01 §6): each word's uses = its Occurrences; its Score, tier counts and first place recomputed
    from the uses = the CSVs'; and further — the priority order, Orth / Forms where spellings tie, and the whole
    progressive list replayed from it (`replay`, below) = the run's own CSVs, Japanese (with set phrases) and Chinese;
  - the plan holds the order's inputs and not the order: replayed in RP-2's other orders (a move within NOW, across
    tiers up and down) it gives the CSVs a full Generate of that order writes;
  - the write is atomic and never fails a Generate; a run that dies between the plan and the stamp leaves a plan no
    stamp matches; the reuse path writes nothing.

`replay` is a reference for the engine (E1.3), kept small: the analyzer's own sort keys, nothing else.
"""
import csv
import gzip
import json
import os
from unittest.mock import patch

import pytest

from app import analyzer
from tests import plan_file_cases as cases

csv.field_size_limit(1 << 30)


# --------------------------------------------------------------------------------------------------------------- #
# Reading a run
# --------------------------------------------------------------------------------------------------------------- #

def load_plan(path):
    """{"header", "files", "keys", "rows", "ties", "per_file"} from a plan file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    plan = {"header": lines[0], "files": [], "keys": [], "rows": [], "ties": [], "per_file": []}
    for line in lines[1:]:
        if "f" in line:
            plan["per_file"].append(line)
        else:
            (name, chunk), = line.items()
            plan[name].extend(chunk)
    return plan


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_run(root):
    results = os.path.join(root, "results")
    with open(os.path.join(results, "library_frequency.json"), encoding="utf-8") as f:
        lib = json.load(f)["words"]
    return {"priority": read_csv(os.path.join(results, "priority_learning_list.csv")),
            "progressive": read_csv(os.path.join(results, "progressive_learning_list.csv")),
            "library_frequency": lib,
            "plan": load_plan(os.path.join(results, "plan.json.gz")),
            "stamp": analyzer.read_run_stamp(results)}


# --------------------------------------------------------------------------------------------------------------- #
# The replay: the order's columns from the plan, for any order of its files
# --------------------------------------------------------------------------------------------------------------- #

def replay(plan, order):
    """`order`: [(file index in the plan, tier)] — every plan file once. Returns {"priority": [row dicts in order],
    "progressive": [...], "first": {k: seq}} with the columns a Generate of that order writes from the plan's data."""
    h = plan["header"]
    w = h["weights"]
    keys = plan["keys"]
    n = len(keys)
    score, counts, first = [0] * n, [[0, 0, 0] for _ in range(n)], [None] * n
    words, phrases, seen = [], [], set()
    spelled = {}                                     # k -> ([orths in first-met order], [surfaces in first-met order])
    tier_slot = {"now": 0, "soon": 1, "goal": 2}
    for seq, (f, tier) in enumerate(order, 1):
        line = plan["per_file"][f]
        for table, into in ((line["main"], words), (line["ph"], phrases)):
            for i in range(0, len(table), 2):
                k, u = table[i], table[i + 1]
                score[k] += w[tier] * u
                counts[k][tier_slot[tier]] += u
                if first[k] is None:
                    first[k] = seq
                if k not in seen:
                    seen.add(k)
                    into.append(k)
        for k, orths, surfaces in line["sp"]:
            o, s = spelled.setdefault(k, ([], []))
            o.extend(x for x in orths if x not in o)
            s.extend(x for x in surfaces if x not in s)
    for k in range(n):
        if keys[k][3]:
            score[k] //= 2
    ties = {t[0]: t for t in plan["ties"]}

    def spelling(k):
        row = plan["rows"][k]
        if k not in ties:
            return row[4], row[5], row[0]
        _k, orth_counts, surface_counts, tiers = ties[k]
        o_order, s_order = spelled.get(k, ([], []))
        orths = analyzer.Counter({x: orth_counts[x] for x in o_order})
        orths.update({x: c for x, c in orth_counts.items() if x not in orths})
        surfaces = analyzer.Counter({x: surface_counts[x] for x in s_order})
        surfaces.update({x: c for x, c in surface_counts.items() if x not in surfaces})
        word = keys[k][0]
        orth = analyzer._display_orth(word, orths)
        return orth, analyzer._display_forms(word, orths, surfaces), (tiers[orth] if tiers else row[0])

    insertion = words + [k for k in phrases if k not in set(words)]
    listed = [k for k in insertion if plan["rows"][k] is not None]
    listed.sort(key=lambda k: (-score[k], first[k], keys[k][2]))
    priority = []
    for k in listed:
        orth, forms, tier = spelling(k)
        priority.append({"Word": keys[k][0], "Reading": keys[k][1], "Score": score[k], "Occurrences": keys[k][4],
                         "Count (High)": counts[k][0], "Count (Low)": counts[k][1], "Count (Goal)": counts[k][2],
                         "Orth": orth, "Forms": forms, "Tier": tier})

    progressive, known, lemmas = [], set(), set()
    for seq, (f, _tier) in enumerate(order, 1):
        total, baseline, tokens, given, credits, phrase_uses, siblings = plan["per_file"][f]["prog"]
        given = dict(zip(given[::2], given[1::2]))
        current, unknown, credited = baseline, {}, {}
        for i in range(0, len(tokens), 2):
            k, count = tokens[i:i + 2]
            bound = given.get(k, 0)
            if k in known or keys[k][0] in lemmas:
                current += count
            elif bound < count:
                unknown[k] = unknown.get(k, 0) + count
        current += sum(c for lemma, c in siblings if lemma in lemmas)
        for i in range(0, len(credits), 2):
            k, c = credits[i:i + 2]
            if not (k in known or keys[k][0] in lemmas):
                credited[k] = credited.get(k, 0) + c
                unknown[k] = unknown.get(k, 0) + c
        for i in range(0, len(phrase_uses), 2):
            k, c = phrase_uses[i:i + 2]
            if k not in known:
                credited[k] = credited.get(k, 0) + c
                unknown[k] = unknown.get(k, 0) + c
        buffer = [(k, c) for k, c in unknown.items() if plan["rows"][k] is not None]
        buffer.sort(key=lambda kc: (score[kc[0]], keys[kc[0]][4]), reverse=True)
        pct = (lambda x: round(x / total * 100, 2)) if total else (lambda x: 0)
        for k, c in buffer:
            start = current
            current += c - credited.get(k, 0)
            orth, forms, _tier = spelling(k)
            row = plan["rows"][k]
            progressive.append({"Sequence": seq, "Source File": plan["files"][f][0].rsplit("/", 1)[-1],
                                "Word": keys[k][0], "Reading": keys[k][1], "Score": score[k],
                                "Occurrences (Global)": keys[k][4], "Occurrences (File)": c,
                                "Count (High)": counts[k][0], "Count (Low)": counts[k][1], "Count (Goal)": counts[k][2],
                                "Known Count": current, "Total Count": total,
                                "Baseline %": pct(baseline), "Current %": pct(start), "New %": pct(current),
                                "Orth": orth, "Forms": forms, "Tier": row[1] or row[0]})
        for k, _c in buffer:
            known.add(k)
            lemmas.add(keys[k][0])
    return {"priority": priority, "progressive": progressive, "first": first}


def _same(expected_rows, replayed_rows, columns):
    """Row by row, the columns compared as the CSV writes them (numbers by value)."""
    assert len(replayed_rows) == len(expected_rows)
    for i, (e, r) in enumerate(zip(expected_rows, replayed_rows)):
        for c in columns:
            got, want = r[c], e[c]
            if isinstance(got, bool) or isinstance(got, str) or got is None:
                assert (want or "") == (got or ""), (i, c, e["Word"], want, got)
            elif isinstance(got, int):
                assert int(want) == got, (i, c, e["Word"], want, got)
            elif isinstance(got, float):
                assert float(want) == pytest.approx(got, abs=1e-9), (i, c, e["Word"], want, got)
            else:
                assert (want or "") == (got or ""), (i, c, e["Word"], want, got)


PRIORITY_COLUMNS = ["Word", "Reading", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)", "Orth",
                    "Forms", "Tier"]
PROGRESSIVE_COLUMNS = ["Sequence", "Source File", "Word", "Reading", "Score", "Occurrences (Global)",
                       "Occurrences (File)", "Count (High)", "Count (Low)", "Count (Goal)", "Known Count",
                       "Total Count", "Baseline %", "Current %", "New %", "Orth", "Forms", "Tier"]


def check_replay(plan, order, run):
    out = replay(plan, order)
    _same(run["priority"], out["priority"], PRIORITY_COLUMNS)
    _same(run["progressive"], out["progressive"], PROGRESSIVE_COLUMNS)
    # First places: library_frequency.json's first_file, every list word's.
    for k, (word, reading, *_rest) in enumerate(plan["keys"]):
        assert run["library_frequency"][f"{word}|{reading}"][4] == out["first"][k], (word, reading)


# --------------------------------------------------------------------------------------------------------------- #
# The runs: each case once (a child process each, as the dashboard runs Generate)
# --------------------------------------------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = {}
    for case in cases.ALL_CASES:
        root = str(tmp_path_factory.mktemp(case))
        cases.build(root, case)
        cases.generate(root, case)
        out[case] = (root, read_run(root))
    return out


def _base():
    with open(cases.BASE_HASHES, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", list(cases.CASES))
def test_every_output_a_generate_wrote_before_is_byte_identical(runs, case):
    """The four libraries' every output — both CSVs, the JSONs, the report, the reading words — hashes as the base
    (42325db) wrote it; only the plan file is new."""
    root, _run = runs[case]
    # A change that moves an output on purpose (a version or ENGINE_REVISION bump, a template, a new setting) records
    # the base's hashes again first, on its base, before its own change: python tests/plan_file_cases.py --record.
    assert cases.output_hashes(root) == _base()[case], "an output moved: see plan_file_cases.py's --record"
    assert os.path.exists(os.path.join(root, "results", analyzer.PLAN_FILE))


@pytest.mark.parametrize("case", list(cases.ALL_CASES))
def test_the_plan_adds_up_to_the_runs_own_lists(runs, case):
    """01 §6's self-checks and more, in the run's own order: each word's uses add up to its Occurrences; Score, the
    tier counts, first places, the priority order, Orth / Forms and the progressive list replayed from the plan are
    the CSVs'."""
    _root, run = runs[case]
    plan = run["plan"]
    h = plan["header"]
    assert h["format"] == 1 and h["language"] == cases.ALL_CASES[case][0]
    assert h["run_signature"] == run["stamp"]
    assert h["files"] == len(plan["files"]) == len(plan["per_file"])
    assert h["keys"] == len(plan["keys"]) == len(plan["rows"]) > 0
    uses = [0] * len(plan["keys"])
    for line in plan["per_file"]:
        for table in (line["main"], line["ph"]):
            for i in range(0, len(table), 2):
                uses[table[i]] += table[i + 1]
    assert uses == [k[4] for k in plan["keys"]]
    check_replay(plan, [(f, tier) for f, (_path, tier, *_digest) in enumerate(plan["files"])], run)


def test_the_japanese_plans_hold_set_phrases_half_scores_and_spelling_ties(runs):
    """What the self-check above must cover to mean anything: RP-2's Japanese library lists set phrases, words at half
    score, words met in more than one spelling (Forms' ties), and a word whose uses inside a phrase don't count."""
    plan = runs["rp2-ja"][1]["plan"]
    assert any(k[2] for k in plan["keys"]), "a phrase row"
    assert any(k[3] for k in plan["keys"]), "a half score"
    assert plan["ties"], "a spelling tie"
    assert any(line["sp"] for line in plan["per_file"]), "a file that meets tied spellings"
    assert any(line["ph"] for line in plan["per_file"])
    assert any(line["prog"][5] for line in plan["per_file"]), "phrase uses in the progressive pass"
    assert plan["header"]["phrase_rows"] is True
    assert runs["rp2-zh"][1]["plan"]["header"]["phrase_rows"] is False


def _rp2_orders(language):
    from tests.test_run_signature_forms import _rp2_orders as orders
    return orders(language)


@pytest.mark.parametrize("case,order_name", [("rp2-ja", "B"), ("rp2-ja", "C"), ("rp2-ja", "D"), ("rp2-zh", "C"),
                                             ("rp2-zh", "D"), ("every-ja", "B"), ("every-ja", "D"),
                                             ("every-ja-2", "C"), ("every-ja-2", "D")])
def test_the_plan_replayed_in_another_order_is_that_orders_generate(runs, tmp_path, case, order_name):
    """The plan holds the order's inputs, not the order: order A's plan replayed in RP-2's order B (a move within NOW),
    C (Soon → NOW's front) or D (NOW → 6+ Months) gives the priority list, the progressive list and the first places
    a full Generate of that order writes — the engine's parity (E1.3), proven possible from the file alone. The
    every-word libraries put each of the plan's branches where an order moves a list: pieces, uses a phrase takes,
    siblings, spellings met first elsewhere."""
    language = cases.ALL_CASES[case][0]
    plan = runs[case][1]["plan"]
    order = _rp2_orders(language)[order_name]
    root = str(tmp_path / order_name)
    cases.build(root, case, order)
    cases.generate(root, case)
    other = read_run(root)
    by_name = {path.rsplit("/", 1)[-1]: f for f, (path, _tier, *_digest) in enumerate(plan["files"])}
    check_replay(plan, [(by_name[name], tier) for tier, name in order], other)


def test_the_plans_signatures_are_the_runs(runs):
    """The plan carries the run's signature (its stamp's) and the order-free one Generate's own list gives now — which
    every order of the library shares (test_run_signature_forms.py)."""
    for case in ("rp2-ja", "samples-zh"):
        root, run = runs[case]
        header = run["plan"]["header"]
        assert header["run_signature"] == run["stamp"]
        assert header["order_free_signature"] == _order_free_of(root, case) != header["run_signature"]


def _order_free_of(root, case):
    """The order-free signature of the library under `root` as it stands, in a child process (its own root)."""
    import subprocess
    import sys
    language = cases.CASES[case][0]
    code = ("import sys\nfrom app import analyzer\n"
            "args = analyzer.parse_analysis_args(['--language', sys.argv[1]])\n"
            "print(analyzer.compute_run_signature(sys.argv[1], analyzer.resolve_found_files(sys.argv[1], False), args,"
            " order_free=True))\n")
    p = subprocess.run([sys.executable, "-c", code, language], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return p.stdout.strip().splitlines()[-1]


# --------------------------------------------------------------------------------------------------------------- #
# What a file's line records, branch by branch (the runs above don't reach every one so that an output moves)
# --------------------------------------------------------------------------------------------------------------- #

def _spy_run(monkeypatch):
    """What main() hands the plan's writer, kept for the test."""
    seen = {}
    real = analyzer.plan_lines

    def spy(run):
        seen.update(run)
        return real(run)

    monkeypatch.setattr(analyzer, "plan_lines", spy)
    return seen


def test_each_files_progressive_line_is_what_its_caches_say(monkeypatch):
    """The progressive pass records, as it reads each file, the list words met there (count after one-kanji pieces),
    the uses of each given to a set phrase, and the other readings of a list word's lemma (siblings: known there once
    that lemma is learned). Worked out again here from the run's own caches the slow way — every token of every file —
    they agree, and the every-word library has all three kinds, so none of them is checked against nothing."""
    seen = {"pieces": 0, "given": 0, "siblings": 0}
    for case in cases.EDGE_CASES:
        _check_progressive_lines(case, monkeypatch, seen)
    assert all(seen.values()), seen


def _check_progressive_lines(case, monkeypatch, seen):
    root = os.environ["SURASURA_TEST_ROOT"]
    cases.build(root, case)
    run = _spy_run(monkeypatch)
    _run_in_process(root, case)
    plan = load_plan(os.path.join(root, "results", analyzer.PLAN_FILE))
    keys = [tuple(k[:2]) for k in plan["keys"]]
    index = {key: k for k, key in enumerate(keys)}
    lemmas = {key[0] for key, k in zip(keys, plan["keys"]) if not k[2]}
    for f, (file_path, _label, _weight, _type) in enumerate(run["found_files"]):
        counter = run["token_cache"][file_path]
        pieces = run["piece_cache"].get(file_path) or {}
        bound = run["bound_cache"].get(file_path) or {}
        baseline, tokens, given, siblings = 0, [], [], {}
        for key, count in counter.items():
            if run["word_state"][key][0] & 5:
                baseline += count
                continue
            if key in pieces:
                baseline += pieces[key]
                count -= pieces[key]
                if key in index:
                    seen["pieces"] += 1
                if count <= 0:
                    continue
            if key[0] not in lemmas:
                continue
            if key in index:
                tokens += (index[key], count)
                if key in bound:
                    given += (index[key], bound[key])
            else:
                siblings[key[0]] = siblings.get(key[0], 0) + count
        seen["given"] += len(given)
        seen["siblings"] += len(siblings)
        total, base, p_tokens, p_given, _credits, _phrases, p_siblings = plan["per_file"][f]["prog"]
        assert (total, base) == (sum(counter.values()), baseline), file_path
        assert (p_tokens, p_given) == (tokens, given), file_path
        assert dict(map(tuple, p_siblings)) == siblings, file_path


def test_a_word_met_here_only_in_another_spelling_is_recorded_for_its_file():
    """A word first met anywhere as 譲っ: a file meeting it only as 譲ろう keeps that record (a later order may put this
    file first); a file meeting it only as first met anywhere keeps nothing (implied); a word met in two spellings here
    keeps both, in the order met."""
    entries = {("譲る", "ユズル"): {"orths": analyzer.Counter({"譲る": 3}),
                                  "surfaces": analyzer.Counter({"譲っ": 2, "譲ろう": 1})}}
    key = ("譲る", "ユズル")
    assert analyzer._unusual_spellings({key: ("譲る", "譲ろう")}, entries) == {key: ("譲る", "譲ろう")}
    assert analyzer._unusual_spellings({key: ("譲る", "譲っ")}, entries) == {}
    spelled = {key: [{"譲る": None}, {"譲ろう": None, "譲っ": None}]}         # met as 譲ろう, then as 譲っ
    assert analyzer._unusual_spellings(spelled, entries) == spelled
    ties = ([], ["譲っ", "譲ろう"])
    entry = entries[key]
    assert analyzer._plan_spellings(key, 4, True, {}, entry, ties) == [4, [], ["譲っ"]]          # implied
    assert analyzer._plan_spellings(key, 4, False, {}, entry, ties) is None                    # credits only
    assert analyzer._plan_spellings(key, 4, True, spelled, entry, ties) == [4, [], ["譲ろう", "譲っ"]]


# --------------------------------------------------------------------------------------------------------------- #
# The write: atomic, never fails a Generate, before the stamp; the reuse path writes nothing
# --------------------------------------------------------------------------------------------------------------- #

def _old_plan(results):
    os.makedirs(results, exist_ok=True)
    with gzip.open(os.path.join(results, analyzer.PLAN_FILE), "wt", encoding="utf-8") as f:
        f.write(json.dumps({"format": 1, "language": "ja", "run_signature": "the last run"}) + "\n")
    with open(os.path.join(results, analyzer.PLAN_FILE), "rb") as f:
        return f.read()


def test_a_write_that_fails_part_way_leaves_the_old_plan_whole(tmp_path):
    """Three failures — the lines stop mid-way, a header that isn't JSON (the read-back refuses it), the final replace —
    each raise to the caller, leave the old plan's bytes and no temp file."""
    results = str(tmp_path / "results")
    old = _old_plan(results)

    def stops():
        yield json.dumps({"format": 1, "language": "ja"})
        raise RuntimeError("the run's memory ran out")

    def garbled():
        yield '{"format": 1, "language": "j'      # the header, which the read-back parses (the rest: json.dumps')
        yield json.dumps({"f": 0, "main": [1, 2]})

    for lines in (stops(), garbled()):
        with pytest.raises(Exception):
            analyzer.write_plan_file(results, lines)
        assert open(os.path.join(results, analyzer.PLAN_FILE), "rb").read() == old
        assert sorted(os.listdir(results)) == [analyzer.PLAN_FILE]

    with patch("app.analyzer.os.replace", side_effect=OSError("the file is held open")):
        with pytest.raises(OSError):
            analyzer.write_plan_file(results, iter([json.dumps({"format": 1})]))
    assert open(os.path.join(results, analyzer.PLAN_FILE), "rb").read() == old
    assert sorted(os.listdir(results)) == [analyzer.PLAN_FILE]

    size = analyzer.write_plan_file(results, iter([json.dumps({"format": 1, "language": "ja"}),
                                                    json.dumps({"keys": [["席を譲る", "セキヲユズル", True, True, 13]]})]))
    assert size == os.path.getsize(os.path.join(results, analyzer.PLAN_FILE))
    written = load_plan(os.path.join(results, analyzer.PLAN_FILE))
    assert written["header"]["language"] == "ja" and written["keys"][0][0] == "席を譲る"


def _run_in_process(root, case, argv_extra=()):
    """A full Generate in this process (so the writer can be broken), on the case's library under `root`."""
    language, _library, _shipped, args = cases.ALL_CASES[case]
    results = os.path.join(root, "results")
    with patch("app.analyzer.RESULTS_DIR", results), \
            patch("app.analyzer.OUTPUT_CSV", os.path.join(results, "priority_learning_list.csv")), \
            patch("app.analyzer.OUTPUT_STATS", os.path.join(results, "file_statistics.txt")), \
            patch("app.analyzer.OUTPUT_PROGRESSIVE", os.path.join(results, "progressive_learning_list.csv")), \
            patch("sys.argv", ["analyzer.py", f"--language={language}", *args, *argv_extra]):
        analyzer.main()


def test_a_plan_that_cant_be_written_never_fails_the_generate(tmp_path, monkeypatch, capsys):
    """The writer throws (here: its lines can't be made): the run still writes every output and its stamp, logs one
    line, and the old plan stays as it was — its run signature no stamp matches, so no reader takes it."""
    root = os.environ["SURASURA_TEST_ROOT"]
    cases.build(root, "samples-zh")
    old = _old_plan(os.path.join(root, "results"))

    def broken(_run):
        raise MemoryError("no room for the plan")
        yield  # pragma: no cover

    monkeypatch.setattr(analyzer, "plan_lines", broken)
    _run_in_process(root, "samples-zh")
    results = os.path.join(root, "results")
    assert open(os.path.join(results, analyzer.PLAN_FILE), "rb").read() == old
    assert analyzer.read_run_stamp(results) not in (None, "the last run")
    assert os.path.exists(os.path.join(results, "priority_learning_list.csv"))
    log = capsys.readouterr().out
    assert log.count("could not write the plan file") == 1


def test_a_plan_held_open_for_a_moment_is_replaced_once_let_go(tmp_path):
    """Windows refuses to replace a file another process has open (a virus scan, the re-plan reading it): the replace
    is tried again for a moment — twice refused, then the new plan is in; refused every time, the error goes up and
    the old plan stays. A temp a killed run left behind (over a minute old) is cleared on the way."""
    results = str(tmp_path / "results")
    old = _old_plan(results)
    stale = os.path.join(results, analyzer.PLAN_FILE + ".4242.tmp")
    with open(stale, "wb") as f:
        f.write(b"half a plan")
    os.utime(stale, (1_700_000_000, 1_700_000_000))
    real, calls = os.replace, []

    def refuses(times):
        def replace(src, dst):
            calls.append(dst)
            if len(calls) <= times:
                raise PermissionError(13, "The process cannot access the file")
            return real(src, dst)
        return replace

    with patch("app.analyzer.os.replace", side_effect=refuses(2)), patch("time.sleep"):
        analyzer.write_plan_file(results, iter([json.dumps({"format": 1, "language": "zh"})]))
    assert len(calls) == 3
    assert load_plan(os.path.join(results, analyzer.PLAN_FILE))["header"]["language"] == "zh"
    assert sorted(os.listdir(results)) == [analyzer.PLAN_FILE]

    old = _old_plan(results)
    calls.clear()
    with patch("app.analyzer.os.replace", side_effect=refuses(99)), patch("time.sleep"):
        with pytest.raises(PermissionError):
            analyzer.write_plan_file(results, iter([json.dumps({"format": 1})]))
    assert len(calls) == 5
    assert open(os.path.join(results, analyzer.PLAN_FILE), "rb").read() == old
    assert sorted(os.listdir(results)) == [analyzer.PLAN_FILE]


def test_a_phrase_counts_only_on_a_phrase_row():
    """勝ち抜く written 勝ち抜く is one joined word on the list; written 勝抜く it matches the set phrase of the same Word
    and Reading, which has no row of its own (its lemmas joined are a library word). The progressive pass gives a
    phrase's uses only to a phrase row, so the plan maps that phrase to no row at all; a phrase with its own row maps
    to it, for its main uses only when its entry is the row's."""
    class _Entry:
        def __init__(self, word, reading):
            self.word, self.reading = word, reading

    class _Phrases:
        entries = {3: _Entry("勝ち抜く", "カチヌク"), 5: _Entry("腑に落ちる", "フニオチル"), 6: _Entry("腑に落ちる", "フニオチル")}

        def entry(self, index):
            return self.entries[index]

    index = {("勝ち抜く", "カチヌク"): 0, ("腑に落ちる", "フニオチル"): 1}
    phrase_keys = {("腑に落ちる", "フニオチル"): 6}
    phrase_key_of = {6: ("腑に落ちる", "フニオチル")}
    cache = {}
    assert analyzer._phrase_rows(cache, 3, _Phrases(), phrase_keys, phrase_key_of, index) == (None, None)
    assert analyzer._phrase_rows(cache, 5, _Phrases(), phrase_keys, phrase_key_of, index) == (None, 1)
    assert analyzer._phrase_rows(cache, 6, _Phrases(), phrase_keys, phrase_key_of, index) == (1, 1)
    assert cache == {3: (None, None), 5: (None, 1), 6: (1, 1)}


def test_a_coverage_mode_plan_lists_rows_as_the_csv_does():
    """Coverage mode (--target-coverage) cuts the list after it is sorted: the plan's rows are the CSV's words, and
    every other list word's row is null — the header says the run was in coverage mode, where the preview stands
    aside (D7)."""
    root = os.environ["SURASURA_TEST_ROOT"]
    cases.build(root, "samples-zh")
    _run_in_process(root, "samples-zh", ["--target-coverage", "60"])
    run = read_run(root)
    plan = run["plan"]
    listed = {(w, r) for (w, r, *_rest), row in zip(plan["keys"], plan["rows"]) if row is not None}
    assert plan["header"]["target_coverage"] == 60
    assert listed == {(r["Word"], r["Reading"]) for r in run["priority"]}
    assert 0 < len(listed) < len(plan["keys"])


def test_a_run_without_a_signature_writes_no_plan(monkeypatch, capsys):
    """The run signature can't be worked out (here: the frequency-list folder can't be listed): the run still writes
    its outputs, but no plan — a plan whose run_signature is null would match the missing stamp."""
    root = os.environ["SURASURA_TEST_ROOT"]
    cases.build(root, "samples-zh")
    monkeypatch.setattr(analyzer, "run_signature_parts", lambda *_a: None)
    _run_in_process(root, "samples-zh")
    results = os.path.join(root, "results")
    assert os.path.exists(os.path.join(results, "priority_learning_list.csv"))
    assert not os.path.exists(os.path.join(results, analyzer.PLAN_FILE))
    assert "could not write the plan file (the run has no signature)" in capsys.readouterr().out


def test_a_run_that_dies_between_the_plan_and_the_stamp_leaves_a_plan_no_stamp_matches(tmp_path, monkeypatch):
    """The run dies just after writing the plan (the final stamp throws): the plan is there with its run signature,
    and results/ has no stamp — dropped when the run began — so neither the skip nor a plan reader trusts it."""
    root = os.environ["SURASURA_TEST_ROOT"]
    cases.build(root, "samples-ja")
    real = analyzer._set_run_stamp

    def dies(results_dir, signature):
        if signature:
            raise KeyboardInterrupt("the machine went to sleep")
        real(results_dir, signature)

    monkeypatch.setattr(analyzer, "_set_run_stamp", dies)
    with pytest.raises(KeyboardInterrupt):
        _run_in_process(root, "samples-ja")
    results = os.path.join(root, "results")
    plan = load_plan(os.path.join(results, analyzer.PLAN_FILE))
    assert plan["header"]["run_signature"]
    assert analyzer.read_run_stamp(results) is None


def test_the_reuse_path_writes_no_plan(tmp_path):
    """Generate again with nothing changed: the run is skipped, and the plan it reuses is still the plan — the very
    file, untouched."""
    root = str(tmp_path / "again")
    cases.build(root, "samples-zh")
    cases.generate(root, "samples-zh")
    path = os.path.join(root, "results", analyzer.PLAN_FILE)
    before = (open(path, "rb").read(), os.stat(path).st_mtime_ns)
    out = cases.generate(root, "samples-zh")
    assert "reusing existing results" in out
    # The same bytes a rewrite would give too: the file itself was never touched.
    assert (open(path, "rb").read(), os.stat(path).st_mtime_ns) == before
