"""T7, the parity (E2.2 RUNBOOK rows 2.2.5–2.2.6, D7 / D9): an arrival placed by the engine is the next Generate.

RP-2's libraries (`plan_file_cases`, ja + zh) are Generated with one more file in the data folder that no tier
schedules — an arrival, kept, never counted (D1): a short "recap" made of lines the library already holds (real text:
a recap episode's lines). In another process under the same root, as the warm worker will, the token store reads it
as a kept file, the view of the last Generate (`arrivals.View`) records it and the gates (`arrivals.Gates`) check it:
exact. The engine built from that Generate's plan then adds it (`Engine.add`) at the top of NOW, in the middle of Soon
and at the end of 6+ Months, and each result equals, on every plan column (05 §1: the priority order, Score,
Occurrences, the tier counts, Orth / Forms, Tier, first places, the progressive rows) and on Junban's index, a full
Generate of the library with the file scheduled there. Adding it and then re-planning from scratch gives the same; the
plan's `check` names the library a "files-added" re-plan.

The gates move where they should (row 2.2.6): one line each that makes a word reach the cut-off, makes a recurring
name join anew, makes an idiom a row, takes a compound off its rarity (it reaches the cut-off), or adds a spelling
tie; automatic rarity's step (the band's list grows past its line, no band remembered) — each gives `exact` False
with that gate named. And the engine's side of a provisional placement (K10): the arrival added while a gate moved,
then a drag, then the engine built again from the next Generate's plan, re-planned to the same order — its columns are
that Generate's, and the front of Junban's queue differs from the provisional one only in the words the gate moved.
"""
import json
import os
import subprocess
import sys

import pytest

from app import analyzer, plan_engine
from tests import plan_file_cases as cases
from tests.test_plan_engine import _check_index, _check_parity
from tests.test_plan_file import read_run

HELD = "HighPriority/Hato/recap.txt"      # hato's drop folder: the file waits in New arrivals


def _lines(case, sources):
    """A library's text lines in its own order, from the files named (subtitles: the spoken lines only)."""
    out = []
    for _tier, name, text in cases.ALL_CASES[case][1]():
        if name in sources:
            for line in text.splitlines():
                line = line.strip()
                if line and not line.isdigit() and "-->" not in line:
                    out.append(line)
    return out


_GOTOUBUN = ("gotoubun_ep01.srt", "gotoubun_ep02.srt")
_NOVELS = ("novel_school_part1.txt", "eighty_six_part2.txt", "runaway_transcript.txt")
# The recap each library receives: lines it holds already, whose every word is listed, known, or new and met once.
RECAP = {"rp2-ja": (_GOTOUBUN, 218, 232), "rp2-zh": (("zh_high_1.txt",), 12, 17)}
# One line each that moves a gate (row 2.2.6): (its library's files, its place among their lines, the gates it moves).
GATE_LINES = {
    "rp2-ja": {"floor": (_GOTOUBUN, 340, {"floor"}),                    # a word met once: now twice, the cut-off
               "names": (_GOTOUBUN, 319, {"names"}),                    # a katakana name the library joins anew
               "phrases": (_GOTOUBUN, 310, {"phrases"}),                # an idiom met once: now a row
               "compounds": (_GOTOUBUN, 332, {"floor", "compounds"}),   # a rare compound reaches the cut-off
               "spellings": (_NOVELS, 78, {"floor", "spellings"})},     # a list word's spellings now tie
    "rp2-zh": {"floor": (("zh_high_1.txt",), 0, {"floor"})},
}


def _text(case, sources, start, end=None):
    lines = _lines(case, sources)
    return "\n".join(lines[start:start + 1] if end is None else lines[start:end]) + "\n"


def _write(root, language, rel, text):
    path = os.path.join(root, "data", language, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.utime(path, (cases.MTIME, cases.MTIME))
    return path


def _schedule(root, language, rel, tier, at):
    """Schedule the file `rel` in `tier` at place `at` (None: the end) — the manifest the library store reads."""
    path = os.path.join(root, "User Files", language, "master_manifest.json")
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    phase = manifest["schedule"][cases.PHASE[tier]]
    phase.insert(len(phase) if at is None else at, {"physical_path": rel, "title": rel.rsplit("/", 1)[-1],
                                                    "origin_source": "Manual Import"})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def _settings(root, logic):
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"logic": logic}, f, ensure_ascii=False)


# The child: the arrivals read as kept files (the indexer's kept list, D5), the view and the gates built once, as the
# warm worker builds them; each arrival recorded and checked. Also the library's signature with the first arrival
# counted, for `check`.
_CHILD = r"""
import json, os, sys
from app import analyzer, arrivals, plan_engine, plan_rules, token_index
from app.path_utils import get_data_path
language, argv, kept, remembered = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4]
args = analyzer.parse_analysis_args([f"--language={language}"] + argv)
plan = plan_engine.load(os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE))
data_dir = get_data_path(language)
store = token_index.open_store(language)
files = [os.path.join(data_dir, *entry[0].split("/")) for entry in plan.files]
paths = [os.path.join(data_dir, *rel.split("/")) for rel in kept]
store.reconcile(files, token_index.make_tokenizer(language, False, args.zh_script),
                build_signature=token_index.build_signature(language, False, args.zh_script), kept=paths)
assert len(store.kept_files()) == len(set(paths))
view = arrivals.View.build(language, plan, store, args)
gates = arrivals.Gates.build(view, store) if remembered == "store" else arrivals.Gates.build(view, store, None)
out = {}
for rel, path in zip(kept, paths):
    rec = arrivals.record(view.sentences(path), view, path, "text", names=view.names_record(path))
    exact, moved = gates.check([rec])
    out[rel] = {"exact": exact, "moved": moved,
                "record": {name: rec[name] for name in ("main", "ph", "sp", "prog", "spc", "plan", "keys", "name")}}
found = analyzer.resolve_found_files(language, verbose=False, missing=True)
found.append((paths[0], "GoalContent", analyzer.WEIGHT_GOAL, "text"))
parts = analyzer.run_signature_parts(language, found, args)
digest = [plan_rules.file_digest(entry) for entry in parts["files"] if os.path.basename(entry[0]) == "recap.txt"]
print("OUT " + json.dumps({"arrivals": out, "parts": parts, "digest": digest}, ensure_ascii=False))
"""


def _child(root, case, kept, remembered="store", argv=()):
    language, _library, _shipped, case_args = cases.ALL_CASES[case]
    p = subprocess.run([sys.executable, "-c", _CHILD, language, json.dumps(case_args + list(argv)), json.dumps(kept),
                        remembered], cwd=cases.REPO, env=cases.child_env(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-4000:]
    return json.loads(next(line for line in p.stdout.splitlines() if line.startswith("OUT "))[4:])


@pytest.fixture(scope="module")
def libraries(tmp_path_factory):
    """Each RP-2 library Generated with the recap (and one file per gate line) in its data folder, scheduled nowhere;
    then the child's records and verdicts."""
    out = {}
    for case in RECAP:
        language = cases.ALL_CASES[case][0]
        root = str(tmp_path_factory.mktemp(f"{case}-arrival"))
        cases.build(root, case)
        _write(root, language, HELD, _text(case, *RECAP[case]))
        kept = [HELD]
        for gate, (sources, at, _moves) in GATE_LINES[case].items():
            kept.append(f"HighPriority/Hato/gate_{gate}.txt")
            _write(root, language, kept[-1], _text(case, sources, at))
        cases.generate(root, case)
        out[case] = (root, read_run(root), _child(root, case, kept))
    return out


# Where the recap is placed: (tier, the place among the tier's items in the plan's order — None: the end).
PLACES = {"top-of-now": ("now", 0), "mid-soon": ("soon", "mid"), "end-of-later": ("goal", None)}


def _place(plan, tier, at):
    """(the place among the tier's items, None: the end; the engine's anchor as (before_id, after_id))."""
    items = [entry[0] for entry in plan.files if entry[1] == tier]
    if at == "mid":
        at = len(items) // 2
    if at is None:
        return None, (None, items[-1])
    return at, (None, items[at - 1] if at else None)


@pytest.fixture(scope="module")
def placed(libraries, tmp_path_factory):
    """For each library and place: a full Generate of the library with the recap scheduled there."""
    out = {}
    for case in RECAP:
        language = cases.ALL_CASES[case][0]
        plan = plan_engine.load(os.path.join(libraries[case][0], "results", analyzer.PLAN_FILE))
        for name, (tier, at) in PLACES.items():
            root = str(tmp_path_factory.mktemp(f"{case}-{name}"))
            cases.build(root, case)
            _write(root, language, HELD, _text(case, *RECAP[case]))
            _schedule(root, language, HELD, tier, _place(plan, tier, at)[0])
            cases.generate(root, case)
            out[(case, name)] = (root, read_run(root))
    return out


def _engine(root):
    return plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))


@pytest.mark.parametrize("case", list(RECAP))
def test_the_recap_moves_no_gate(libraries, case):
    """The recap holds only words the list has, the learner knows, or meets for the first time once: no gate moves."""
    arrival = libraries[case][2]["arrivals"][HELD]
    assert (arrival["exact"], arrival["moved"]) == (True, [])
    assert arrival["record"]["main"], "the recap meets list words"


@pytest.mark.parametrize("case,place", [(case, place) for case in RECAP for place in PLACES])
def test_an_exact_arrival_placed_by_the_engine_is_the_next_generate(libraries, placed, case, place):
    """`Engine.add` at the top of NOW, mid-Soon and the end of 6+ Months: every plan column and Junban's index equal a
    full Generate of the library with the recap scheduled there; the same from a from-scratch re-plan after it."""
    root, _run, child = libraries[case]
    language = cases.ALL_CASES[case][0]
    record = child["arrivals"][HELD]["record"]
    plan = _engine(root)
    tier, at = PLACES[place]
    _at, (before, after) = _place(plan, tier, at)
    eng = plan_engine.Engine(plan)
    keys, items = eng.add(HELD, record, tier, before_id=before, after_id=after)
    assert items == [HELD] and keys
    result = eng.result()
    assert result.added == [HELD] and result.provisional == [] and result.reasons == {}
    other_root, other = placed[(case, place)]
    _check_parity(result, other)
    _check_index(result, other_root, language, same_sentences=False)
    # From scratch: the arrival added anywhere, then the order re-planned whole.
    order = [(entry[0], entry[1]) for entry in other["plan"]["files"]]
    fresh = plan_engine.Engine(plan)
    fresh.add(HELD, record, "goal")
    again = fresh.replan(order)
    _check_parity(again, other)
    for name in ("priority", "progressive", "first", "n_new", "score", "counts", "sequence"):
        assert getattr(again, name) == getattr(result, name), name


@pytest.mark.parametrize("case", list(RECAP))
def test_check_names_a_library_whose_only_change_is_the_arrival(libraries, case):
    """`check(…, added=)`: the library with the recap counted and nothing else changed is a "files-added" re-plan —
    only when the recap is one the engine added; otherwise a Generate first."""
    root, _run, child = libraries[case]
    language = cases.ALL_CASES[case][0]
    plan = _engine(root)
    h = plan.header
    args = (plan, language, h["engine"], h["run_signature"], child["parts"])
    assert len(child["digest"]) == 1
    assert plan_engine.check(*args, added=child["digest"]) == ("replan-now", ("files-added",))
    assert plan_engine.check(*args) == ("generate-first", "files")
    assert plan_engine.check(*args, added=["another file"]) == ("generate-first", "files")


@pytest.mark.parametrize("case,gate", [(case, gate) for case in GATE_LINES for gate in GATE_LINES[case]])
def test_each_gate_moves_where_it_should(libraries, case, gate):
    """Row 2.2.6: a line that makes a word reach the cut-off, a name join anew, an idiom a row, a rare compound reach
    the cut-off, a spelling tie — `exact` False, the gate named (and no gate it can't move)."""
    arrival = libraries[case][2]["arrivals"][f"HighPriority/Hato/gate_{gate}.txt"]
    assert arrival["exact"] is False
    assert set(arrival["moved"]) == GATE_LINES[case][gate][2], arrival["moved"]


def test_automatic_raritys_step_moves_the_band(tmp_path):
    """Automatic rarity, its line at the band's word count and no band remembered: an arrival adding a list word steps
    the band back (`band` named); with the band the store remembers (Q4-3) it stays — the gate reads it as `main()`."""
    case, language = "rp2-ja", "ja"
    root = str(tmp_path / "auto")
    cases.build(root, case)
    rel = "HighPriority/Hato/gate_floor.txt"
    sources, at, _moves = GATE_LINES[case]["floor"]
    _write(root, language, rel, _text(case, sources, at))
    _settings(root, {"selection": {"auto": True}})
    cases.generate(root, case)
    # The line: the rarest band's word count (every band at the min_count floor holds the same words here).
    counts = _band_counts(root, language)
    _settings(root, {"selection": {"auto": True, "auto_max_words": counts["native"]}})
    _forget_band(root, language)
    cases.generate(root, case)
    held = _child(root, case, [rel], remembered="none")["arrivals"][rel]
    assert held["exact"] is False and "band" in held["moved"], held["moved"]
    kept = _child(root, case, [rel], remembered="store")["arrivals"][rel]
    assert "band" not in kept["moved"], kept["moved"]
    # The band's word counts, worked out from what the arrival touches, against the slider's whole recount.
    p = subprocess.run([sys.executable, "-c", _BAND_CHILD, rel], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-4000:]
    out = json.loads(next(line for line in p.stdout.splitlines() if line.startswith("OUT "))[4:])
    assert len(out) == 13 and all(warm == whole for warm, whole in out), out
    assert len({json.dumps(whole) for _warm, whole in out}) > 1, "the arrivals move the counts"


# Every counted file (an episode met twice) and the gate's arrival, each added alone: `Gates._band_words` = the Rarity
# slider's whole recount (`unknown_distribution` over the library with it added, `band_previews`).
_BAND_CHILD = r"""
import json, os, sys
from collections import Counter
from app import analyzer, arrivals, plan_engine, token_index, word_selection
from app.path_utils import get_data_path
args = analyzer.parse_analysis_args(["--language=ja"])
plan = plan_engine.load(os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE))
store = token_index.open_store("ja")
data_dir = get_data_path("ja")
view = arrivals.View.build("ja", plan, store, args)
gates = arrivals.Gates.build(view, store, None)
assert gates.auto and not gates.stale
paths = [os.path.join(data_dir, *entry[0].split("/")) for entry in plan.files]
paths.append(os.path.join(data_dir, *sys.argv[1].split("/")))
lists, table = gates.lists, gates.phrase_table
out = []
for path in paths:
    rec = arrivals.record(view.sentences(path), view, path)
    total = gates.total + sum(rec["counts"].values())
    warm = gates._band_words(rec["counts"], rec["bound"], [rec["tally"]], total)
    counts, bound = dict(gates.counts), dict(gates.bound)
    for key, n in rec["counts"].items():
        counts[key] = counts.get(key, 0) + n
    for key, n in rec["bound"].items():
        bound[key] = bound.get(key, 0) + n
    rows = {name: [row[0], list(row[1])] for name, row in (table.get("rows") or {}).items()}
    taken = Counter(table.get("taken") or {})
    uses, given = rec["tally"]
    for index, (n, spelled) in uses.items():
        phrase = view.phrase_set.entry(int(index))
        row = rows.setdefault(phrase.word + "|" + phrase.reading, [0, [phrase.display]])
        row[0] += n
        row[1].extend(x for x in spelled if x not in row[1])
    taken.update(given)
    freqs = token_index.unknown_distribution(counts, total, lists["known_tuples"], lists["known_lemmas"],
                                             lists["ignore_set"], lists["skip_singles"], "ja",
                                             {"rows": rows, "taken": dict(taken)},
                                             bound if lists["skip_singles"] else None)
    whole = {band: p["word_count"] for band, p in word_selection.band_previews(freqs, gates.ppm, gates.min_count).items()}
    out.append([warm, whole])
print("OUT " + json.dumps(out))
"""


def _band_counts(root, language):
    code = r"""
import json, sys
from app import token_index, word_selection
from app.path_utils import get_user_files_path
store = token_index.open_store(sys.argv[1])
freqs = token_index.preview_frequencies(store, sys.argv[1], get_user_files_path(sys.argv[1]))
print("OUT " + json.dumps({b: p["word_count"] for b, p in word_selection.band_previews(freqs).items()}))
"""
    p = subprocess.run([sys.executable, "-c", code, language], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-3000:]
    return json.loads(next(line for line in p.stdout.splitlines() if line.startswith("OUT "))[4:])


def _forget_band(root, language):
    code = r"""
import sys
from app import library_store
from app.path_utils import get_data_path, get_user_files_path
library_store.forget_auto_band(sys.argv[1], get_data_path(sys.argv[1]), get_user_files_path(sys.argv[1]))
"""
    p = subprocess.run([sys.executable, "-c", code, language], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-3000:]


def test_a_provisional_arrival_is_corrected_by_the_next_generate(libraries, tmp_path):
    """K10, the engine's side: an arrival that moves a gate is added provisionally (`provisional`, `reasons`), then an
    item is dragged; the engine built again from the next Generate's plan (that library, that order), re-planned to the
    same order, gives that Generate's columns — and the front of Junban's queue differs from the provisional one only
    in the words the gate moved (the word that reached the cut-off)."""
    case, language = "rp2-ja", "ja"
    root, _run, child = libraries[case]
    rel = "HighPriority/Hato/gate_floor.txt"
    arrival = child["arrivals"][rel]
    plan = _engine(root)
    eng = plan_engine.Engine(plan)
    eng.add(rel, arrival["record"], "now", exact=arrival["exact"], moved=arrival["moved"])
    later = [entry[0] for entry in plan.files if entry[1] == "goal"]
    eng.move(later[-1], "soon")
    provisional = eng.result()
    assert provisional.provisional == [rel] and provisional.reasons == {rel: ["floor"]}
    order = [(eng._ids[f], plan_engine.TIERS[eng._tier[f]]) for f in eng._order]

    # The next Generate: the library with the file at NOW's top and the item dragged to Soon's top.
    other = str(tmp_path / "next")
    by_rel = {entry[0]: entry[0].rsplit("/", 1)[-1] for entry in plan.files}
    cases.build(other, case, [(tier, by_rel[item]) for item, tier in order if item != rel])
    _write(other, language, rel, _text(case, *GATE_LINES[case]["floor"][:2]))
    _schedule(other, language, rel, "now", 0)
    cases.generate(other, case)
    run = read_run(other)
    rebased = plan_engine.Engine(_engine(other)).replan(order)
    _check_parity(rebased, run)
    assert rebased.provisional == []

    before = {(key[0], key[1]) for key in plan.keys}
    after = {(key[0], key[1]) for key in run["plan"]["keys"]}
    moved = before ^ after
    assert moved, "the gate moved a word onto the list"
    for mode in plan_engine.ORDER_MODES:
        a = [w for w in provisional.front(200, order_mode=mode) if w not in moved]
        b = [w for w in rebased.front(200, order_mode=mode) if w not in moved]
        n = min(len(a), len(b))
        assert a[:n] == b[:n], mode


# The name tables' gate against the whole rule: every counted file's record, and the arrivals', added as one more file
# (an episode met twice is one) — and two at once — decided again only where a record touches the sums, against
# `names.compute_tables` over every record with it added, from the tables as they stand.
_NAMES_CHILD = r"""
import json, os, sys, time
from app import analyzer, arrivals, names, plan_engine, token_index
from app.path_utils import get_data_path
args = analyzer.parse_analysis_args(["--language=ja"])
plan = plan_engine.load(os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE))
store = token_index.open_store("ja")
tables, records = store.names_tables(), store.names_records()
view = arrivals.View.build("ja", plan, store, args)
gates = arrivals.Gates.build(view, store)
data_dir = get_data_path("ja")
arriving = [store.names_record(os.path.join(data_dir, *rel.split("/"))) for rel in json.loads(sys.argv[1])]
sanitize = analyzer._sanitize_term
out = {"same": names.compute_tables(records, tables, sanitize) == tables, "cases": [], "ms": []}
held = records + arriving
for i, record in enumerate(held):
    for more in ([record], [record, held[(i + 1) % len(held)]]):
        start = time.perf_counter()
        moved = gates._names_move(more)
        out["ms"].append((time.perf_counter() - start) * 1000)
        whole = names.compute_tables(records + more, tables, sanitize)
        out["cases"].append([moved, whole["stamp"] != tables["stamp"]])
out["sums"] = [len(gates.table_sums.ways), len(gates.table_sums.pieces), len(gates.term_sums.uses)]
print("OUT " + json.dumps(out))
"""


def test_the_name_tables_gate_decides_as_the_whole_rule(libraries):
    """`Gates._names_move` (only the spellings a record touches decided again, on sums kept warm) = whether
    `names.compute_tables` over every counted record plus the arrivals' gives another stamp — for each counted file
    and each arrival, alone and in pairs; and the tables worked out again from the records as they stand are the
    stored ones (the sums and choices apart, one rule)."""
    root, _run, child = libraries["rp2-ja"]
    kept = [rel for rel in child["arrivals"]]
    p = subprocess.run([sys.executable, "-c", _NAMES_CHILD, json.dumps(kept)], cwd=cases.REPO,
                       env=cases.child_env(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-4000:]
    out = json.loads(next(line for line in p.stdout.splitlines() if line.startswith("OUT "))[4:])
    assert out["same"]
    assert [moved for moved, _whole in out["cases"]] == [whole for _moved, whole in out["cases"]]
    assert any(whole for _moved, whole in out["cases"]) and not all(whole for _moved, whole in out["cases"])
    assert all(n > 0 for n in out["sums"])
