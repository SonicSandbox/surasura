"""T6, the oracle (E2.2 RUNBOOK row 2.2.4, D6): the arrival record is one rule set with a Generate.

`app/arrivals.py` gives, for one file's tokens and a view of the last Generate, the plan line a full Generate would
write for that file were it counted. Here every counted file of every test library — the bundled samples and RP-2's
libraries (ja + zh), the every-word edge cases, and RP-2 under the settings that change what a file's line holds
(set phrases off, Ignore names on, a names layer off, pronoun bases off, Chinese read as Simplified or Traditional,
automatic rarity on; the intent keeper's K7) — goes through a real Generate (`plan_file_cases`, a child process as the
dashboard runs it), then through the view in another child process under the same root, as the warm worker will read
it: `record`'s `main`, `ph`, `sp` and `prog` equal the plan file's line for that file, byte for byte (`json.dumps`
with the plan's separators) — once over the store's cached tokens, once over the file tokenized afresh with the
view's name tables. The record's own additions add up too: each list word's spelling counts over every file are the
plan's (`spell` / `ties`, in the order first met), its counted uses its Occurrences, the files' tokens the run's total.
"""
import json
import os
import subprocess
import sys

import pytest

from app import analyzer
from tests import plan_file_cases as cases
from tests.test_plan_file import load_plan

# name -> (the library, its logic settings in settings.json, extra analyzer arguments the dashboard passes)
VARIANTS = {
    "rp2-ja-phrase-rows-off": ("rp2-ja", {"phrase_rows": False}, []),
    "rp2-ja-ignore-names": ("rp2-ja", {"ignore_names": True}, []),
    "rp2-ja-katakana-names-off": ("rp2-ja", {"names_katakana": False}, []),
    "rp2-ja-recurring-names-off": ("rp2-ja", {"names_recurring": False}, []),
    "rp2-ja-pronoun-bases-off": ("rp2-ja", {"pronoun_bases": False}, []),
    "rp2-ja-automatic-rarity": ("rp2-ja", {"selection": {"auto": True}}, []),
    "rp2-zh-simplified": ("rp2-zh", {}, ["--zh-script", "s"]),
    "rp2-zh-traditional": ("rp2-zh", {}, ["--zh-script", "t"]),
}

LIBRARIES = {case: (case, {}, []) for case in cases.ALL_CASES}
LIBRARIES.update(VARIANTS)

# The child: the view built once, as the worker builds it; each counted file recorded from the store's tokens and
# from a fresh tokenizing; one JSON line per file. A format-1 copy of the plan (2.x's) is viewed too: its record must
# be the same wherever the view can tell each phrase row's entry (`View.unsure`, empty here).
_CHILD = r"""
import json, os, sys
from app import analyzer, arrivals, plan_engine, token_index
from app.path_utils import get_data_path
language, argv = sys.argv[1], json.loads(sys.argv[2])
args = analyzer.parse_analysis_args([f"--language={language}"] + argv)
path = os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE)
plan = plan_engine.load(path)
store = token_index.open_store(language)
view = arrivals.View.build(language, plan, store, args)
old = plan_engine.Plan({k: v for k, v in dict(plan.header, format=1).items() if k != "phrase_entries"}, plan.files,
                       plan.keys, plan.rows, plan.ties, plan.per_file)
old_view = arrivals.View.build(language, old, store, args, tokenizer=view.tokenizer)
print("UNSURE " + json.dumps(sorted(old_view.unsure)))
data_dir = get_data_path(language)
NAMES = ("main", "ph", "sp", "prog")
for f, (rel, _tier, *_digest) in enumerate(plan.files):
    file_path = os.path.join(data_dir, *rel.split("/"))
    out = {"f": f}
    fresh = list(view.tokenizer.tokenize_sentences(analyzer.extract_text(file_path, language)))
    for how, sentences in (("cached", view.sentences(file_path)), ("fresh", fresh)):
        rec = arrivals.record(sentences, view, file_path, None)
        out[how] = {name: analyzer._plan_json(rec[name]) for name in NAMES}
        if how == "cached":
            out["spc"] = [[k, o, s] for k, (o, s) in rec["spc"].items()]
            out["uses"] = [[view.index[key], n] for key, n in rec["uses"].items() if key in view.index]
            out["tokens"] = rec["tokens"]
            old_rec = arrivals.record(sentences, old_view, file_path, None)
            out["format1"] = all(analyzer._plan_json(old_rec[name]) == out[how][name] for name in NAMES)
    print("LINE " + json.dumps(out, ensure_ascii=False))
"""


def _view_lines(root, language, argv):
    p = subprocess.run([sys.executable, "-c", _CHILD, language, json.dumps(argv)], cwd=cases.REPO,
                       env=cases.child_env(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-4000:]
    lines = [json.loads(line[5:]) for line in p.stdout.splitlines() if line.startswith("LINE ")]
    unsure = next(json.loads(line[7:]) for line in p.stdout.splitlines() if line.startswith("UNSURE "))
    return lines, unsure


def _generate(root, name):
    case, logic, argv = LIBRARIES[name]
    cases.build(root, case)
    if logic:
        with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"logic": logic}, f, ensure_ascii=False)
    cases.generate(root, case, extra_args=argv)
    language, _library, _shipped, case_args = cases.ALL_CASES[case]
    return language, case_args + argv


@pytest.mark.parametrize("name", list(LIBRARIES))
def test_the_record_of_every_counted_file_is_its_plan_line(tmp_path, name):
    """For every counted file: `record` over the store's tokens, and over the file tokenized afresh, gives the plan
    line the Generate wrote for it — main, ph, sp and prog, byte for byte."""
    root = str(tmp_path / "root")
    language, argv = _generate(root, name)
    plan = load_plan(os.path.join(root, "results", analyzer.PLAN_FILE))
    if name == "rp2-ja-phrase-rows-off":
        assert plan["header"]["phrase_rows"] is False
    lines, unsure = _view_lines(root, language, argv)
    assert [line["f"] for line in lines] == list(range(len(plan["per_file"]))) != []
    for line, written in zip(lines, plan["per_file"]):
        for name_ in ("main", "ph", "sp", "prog"):
            want = analyzer._plan_json(written[name_])
            assert line["cached"][name_] == want, (line["f"], name_)
            assert line["fresh"][name_] == want, (line["f"], name_, "fresh")
        # 2.x's plan (format 1): the same line wherever every phrase row's entry is plain (here, every one).
        assert line["format1"] or unsure, line["f"]

    # The record's additions: every list word's spelling counts over the files, merged in the files' order, are the
    # plan's (`spell`, `ties`) in the order first met; its counted uses add up to Occurrences; the files' tokens to
    # the run's total.
    spellings = {row[0]: (row[1], row[2]) for row in plan["spell"]}
    spellings.update({tie[0]: (tie[1], tie[2]) for tie in plan["ties"]})
    merged, uses = {}, [0] * len(plan["keys"])
    for line in lines:
        for k, orths, surfaces in line["spc"]:
            o, s = merged.setdefault(k, ({}, {}))
            for into, counts in ((o, orths), (s, surfaces)):
                for x, n in counts.items():
                    into[x] = into.get(x, 0) + n
        for k, n in line["uses"]:
            uses[k] += n
    for k, (orths, surfaces) in spellings.items():
        met = merged.get(k, ({}, {}))           # none: a word met only inside rare compounds (credits have no spelling)
        assert list(met[0].items()) == list(orths.items()), plan["keys"][k][0]
        assert list(met[1].items()) == list(surfaces.items()), plan["keys"][k][0]
    words = [k for k, key in enumerate(plan["keys"]) if not key[2]]
    assert [uses[k] for k in words] == [plan["keys"][k][4] for k in words]
    assert sum(line["tokens"] for line in lines) == plan["header"]["total_tokens"]
