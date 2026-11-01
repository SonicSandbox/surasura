"""The parsing-robustness suite's scorecard — every case, a baseline, and the diff against the last one: what a
parsing change fixes, what it breaks, and which decisions it touches. Not collected by pytest (no test_ prefix).

    python tests/parsing/scorecard.py                              # every case; diff against the latest plain run
    python tests/parsing/scorecard.py --variant no-affix-joins     # a prototype rule (variants.py) over every case
    python tests/parsing/scorecard.py --baseline latest|none|PATH|LABEL
    python tests/parsing/scorecard.py --save before-kigou-fix      # a label for the baseline this run writes
    python tests/parsing/scorecard.py --only F,G                   # categories, areas, layers or case ids

Every run writes tests/parsing/baselines/<YYYYmmdd-HHMMSS>[-label].json — each case's observed output, verdict and
problems, with the git rev and dirty flag, the variant, the settings snapshot, ENGINE_REVISION and SCHEMA_VERSION —
and the report it prints beside it as .txt (UTF-8, readable whatever the console's code page; set
PYTHONIOENCODING=utf-8 to read it in the console). "latest" is the newest plain run over every case, so a variant's
run and a partial run both diff against today's code and never become the reference themselves.
"""
import argparse
import contextlib
import glob
import json
import logging
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import analyzer, token_index  # noqa: E402
from tests.parsing import harness  # noqa: E402
from tests.parsing.case import CATEGORIES  # noqa: E402
from tests.parsing.cases import CASES  # noqa: E402
from tests.parsing.decisions import DECISIONS  # noqa: E402
from tests.parsing.variants import VARIANTS, load_variants  # noqa: E402


def select(cases, only):
    """The cases `--only` names: comma-separated category letters, areas, layers, ids or id prefixes (JA-AFX) —
    any match keeps a case."""
    if not only:
        return list(cases)
    wanted = {token.strip() for token in only.split(",") if token.strip()}
    return [case for case in cases if wanted & {case.category, case.area, case.layer}
            or any(case.id.startswith(token) for token in wanted if "-" in token)]


def show_lines(cases, results):
    """--show: every case's verdict and observed output, one line each (problems under a case that isn't a pass)."""
    lines = []
    for case in sorted(cases, key=lambda case: (case.category, case.id)):
        result = results[case.id]
        lines.append(f"[{case.category}] {case.id}  {case.status:<8} {result.verdict:<5} {case.span!r}  "
                     f"{_show(case.layer, result.observed)}")
        if result.verdict != "pass":
            lines.append(f"      {_cut('; '.join(result.problems), 600)}")
    return lines


def run(cases, variant):
    """{case id: harness.Result} — every case under the pins, inside the variant (if any), with one Context."""
    manager = VARIANTS[variant].manager() if variant else contextlib.nullcontext()
    results = {}
    with manager, tempfile.TemporaryDirectory(prefix="parsing_scorecard_") as scratch:
        ctx = harness.Context(scratch)
        for case in cases:
            results[case.id] = harness.evaluate(case, ctx, catch=True)
    return results


def _record(case, result):
    return {"area": case.area, "category": case.category, "layer": case.layer, "status": case.status,
            "decision": case.decision, "span": case.span, "expect": case.expect,
            # through JSON, so it compares equal to what a baseline reads back
            "observed": json.loads(json.dumps(result.observed, ensure_ascii=False)),
            "verdict": result.verdict, "problems": result.problems}


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def reference(spec):
    """(path, baseline) to diff against, or (None, None): "latest" — the newest plain run over every case —
    "none", a path, a file name in baselines/, or a label (the newest baseline saved with it)."""
    if spec == "none":
        return None, None
    files = sorted(glob.glob(os.path.join(harness.BASELINES, "*.json")), reverse=True)   # names start with the time
    if spec == "latest":
        for path in files:
            try:
                data = _load(path)
                if not data["meta"].get("variant") and not data["meta"].get("only"):
                    return path, data
            except (OSError, ValueError, KeyError, TypeError):
                continue                                        # not a baseline this scorecard wrote
        return None, None
    for path in (spec, os.path.join(harness.BASELINES, spec), os.path.join(harness.BASELINES, spec + ".json")):
        if os.path.isfile(path):
            return path, _load(path)
    labelled = [path for path in files if os.path.basename(path).endswith(f"-{spec}.json")]
    if labelled:
        return labelled[0], _load(labelled[0])
    raise SystemExit(f"no baseline {spec!r} in {harness.BASELINES}")


def _show(layer, observed):
    """A case's observed output in its layer's one line — or its error, or JSON if the layer no longer reads it."""
    if isinstance(observed, dict) and set(observed) == {"error"}:
        return f"ERROR {observed['error']}"
    if isinstance(observed, dict) and set(observed) == {"skipped"}:
        return f"SKIPPED {observed['skipped']}"
    try:
        return harness.EVALUATORS[layer].show(observed)
    except Exception:
        return harness.short(observed, 400)


def _cut(text, width=300):
    return text if len(text) <= width else text[:width - 1] + "…"


def summary(cases, results, changed_ids):
    """The per-category table: LOCK ok / FAIL, TARGET fixed / still wrong, LIMIT and DISPUTED (changed since the
    reference), skipped (can't be judged here: harness.Skip), errors."""
    rows = defaultdict(Counter)
    for case in cases:
        verdict = results[case.id].verdict
        for row in (case.category, "all"):
            counts = rows[row]
            counts["cases"] += 1
            if verdict == "error":
                counts["errors"] += 1
            elif verdict == "skip":
                counts["skipped"] += 1
            elif case.status == "LOCK":
                counts["LOCK ok" if verdict == "pass" else "LOCK FAIL"] += 1
            elif case.status == "TARGET":
                counts["TARGET fixed" if verdict == "pass" else "TARGET wrong"] += 1
            else:
                counts[case.status] += 1
                counts[f"{case.status} changed"] += case.id in changed_ids
    columns = (("cases", "cases"), ("LOCK ok", "LOCK ok"), ("LOCK FAIL", "LOCK FAIL"), ("TARGET fixed", "TGT fixed"),
               ("TARGET wrong", "TGT wrong"), ("LIMIT", "LIMIT"), ("LIMIT changed", "(changed)"),
               ("DISPUTED", "DISPUTED"), ("DISPUTED changed", "(changed)"), ("skipped", "skipped"),
               ("errors", "errors"))
    lines = [f"  {'cat':<4} {'':<44}" + "".join(f"{header:>10}" for _name, header in columns)]
    for row in sorted(row for row in rows if row != "all") + ["all"]:
        lines.append(f"  {row:<4} {CATEGORIES.get(row, ''):<44}"
                     + "".join(f"{rows[row][name]:>10}" for name, _header in columns))
    return lines


def compare(cases, results, before, partial):
    """The diff against a reference baseline: {"fixed", "broken", "changed", "skipped", "judged", "new", "gone"} —
    "skipped" (now can't be judged here, harness.Skip) and "judged" (judged again after a skip) apart from the
    verdicts; "gone" (cases the reference had and this run lacks) only when neither run is partial (--only)."""
    old = before["cases"]
    groups = {"fixed": [], "broken": [], "changed": [], "skipped": [], "judged": [], "new": [], "gone": []}
    for case in cases:
        prev, now = old.get(case.id), results[case.id]
        if prev is None:
            groups["new"].append(case)
            continue
        observed = json.loads(json.dumps(now.observed, ensure_ascii=False))
        if "skip" in (prev["verdict"], now.verdict):
            if prev["verdict"] != now.verdict:
                groups["skipped" if now.verdict == "skip" else "judged"].append(case)
            elif prev["observed"] != observed:
                groups["changed"].append(case)
        elif prev["verdict"] != "pass" and now.verdict == "pass":
            groups["fixed"].append(case)
        elif prev["verdict"] == "pass" and now.verdict != "pass":
            groups["broken"].append(case)
        elif prev["observed"] != observed or prev["verdict"] != now.verdict:
            groups["changed"].append(case)
    if not partial and not before["meta"].get("only"):
        present = {case.id for case in cases}
        groups["gone"] = sorted(case_id for case_id in old if case_id not in present)
    return groups


def diff_lines(groups, results, before):
    old = before["cases"]
    lines = []
    for name, title in (("fixed", "FIXED (was wrong, now right)"), ("broken", "BROKEN (was right, now wrong)"),
                        ("changed", "CHANGED, same verdict"), ("skipped", "SKIPPED (can't be judged here — why)"),
                        ("judged", "JUDGED AGAIN (skipped in the reference)")):
        items = sorted(groups[name], key=lambda case: (case.category, case.id))
        if not items:
            continue
        lines.append(f"{title} — {len(items)}")
        for case in items:
            prev = old[case.id]
            edited = prev.get("expect") != case.expect or prev.get("status") != case.status
            lines.append(f"  [{case.category}] {case.id}  {case.status}  {case.span!r}"
                         + (f"  · {case.decision}" if case.decision else "")
                         + ("  (expectation edited since)" if edited else ""))
            lines.append(f"      {_cut(_show(case.layer, prev['observed']))}")
            lines.append(f"    → {_cut(_show(case.layer, results[case.id].observed))}")
    if groups["new"]:
        lines.append(f"NEW since the reference — {len(groups['new'])}: "
                     + _cut(", ".join(case.id for case in groups["new"]), 600))
    if groups["gone"]:
        lines.append(f"GONE since the reference — {len(groups['gone'])}: " + _cut(", ".join(groups["gone"]), 600))
    touched = defaultdict(Counter)
    for name in ("fixed", "broken", "changed"):
        for case in groups[name]:
            if case.decision:
                touched[case.decision][name] += 1
    if touched:
        lines.append("DECISIONS TOUCHED")
        for decision_id in sorted(touched):
            decision = DECISIONS.get(decision_id)
            counts = ", ".join(f"{touched[decision_id][name]} {name}" for name in ("fixed", "broken", "changed")
                               if touched[decision_id][name])
            if decision is None:
                lines.append(f"  {decision_id} (not in decisions.py): {counts}")
                continue
            lines.append(f"  {decision.id} ({decision.status}): {counts}")
            lines.append(f"      {_cut(decision.choice or decision.question, 220)}")
            lines.append(f"      gives up: {_cut(decision.tradeoff, 220)}")
    if not any(groups[name] for name in ("fixed", "broken", "changed", "skipped", "judged", "new", "gone")):
        lines.append("No difference: every case gives the same output and verdict as the reference.")
    return lines


def report(cases, results, meta, before_path, before):
    lines = [f"Parsing scorecard {meta['written']} — {len(cases)} cases · "
             + (f"variant {meta['variant']!r}" if meta["variant"] else "plain (no variant)")
             + (f" · only {meta['only']}" if meta["only"] else "")
             + f" · rev {(meta['git']['rev'] or '?')[:7]}{' (dirty)' if meta['git']['dirty'] else ''}"
             + f" · settings {meta['settings_snapshot']} · ENGINE {meta['engine_revision']} / SCHEMA "
               f"{meta['schema_version']}"]
    if meta["variant"]:
        lines.append(f"  {VARIANTS[meta['variant']].about}")
    groups = compare(cases, results, before, bool(meta["only"])) if before else None
    changed_ids = ({case.id for name in ("fixed", "broken", "changed", "skipped", "judged") for case in groups[name]}
                   if groups else set())
    lines += [""] + summary(cases, results, changed_ids) + [""]
    failing = [case for case in cases
               if results[case.id].verdict == "error"
               or (case.status == "LOCK" and results[case.id].verdict not in ("pass", "skip"))]
    if failing:
        lines.append(f"LOCK FAILURES AND ERRORS — {len(failing)} (the guard fails on these)")
        for case in sorted(failing, key=lambda case: (case.category, case.id)):
            lines.append(f"  [{case.category}] {case.id}  {case.status}  {case.span!r}: "
                         + _cut("; ".join(results[case.id].problems), 400))
        lines.append("")
    if before is None:
        lines.append("No reference baseline — this run is the first (or --baseline none); the next run diffs "
                     "against it.")
    else:
        bmeta = before["meta"]
        lines.append(f"Against {os.path.basename(before_path)} — "
                     + (f"variant {bmeta['variant']!r}" if bmeta.get("variant") else "plain")
                     + f", rev {(bmeta['git'].get('rev') or '?')[:7]}{' (dirty)' if bmeta['git'].get('dirty') else ''}"
                     + f", {bmeta['cases']} cases, written {bmeta['written']}")
        lines += diff_lines(groups, results, before)
    return lines


def _label(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") if text else ""


def main(argv=None):
    harness.load_evaluators()
    load_variants()                                             # variants_<area>.py too, before the choices
    parser = argparse.ArgumentParser(
        description="Run every parsing case, write a baseline, and diff it against the reference.",
        epilog="variants: " + "; ".join(f"{name} — {v.about}" for name, v in sorted(VARIANTS.items())))
    parser.add_argument("--variant", choices=sorted(VARIANTS), help="apply a prototype rule for this run")
    parser.add_argument("--baseline", default="latest",
                        help="what to diff against: latest (the newest plain full run; default), none, a path, a file "
                             "name in baselines/ or a --save label")
    parser.add_argument("--save", metavar="LABEL", help="a label for the baseline this run writes")
    parser.add_argument("--only", metavar="WHICH",
                        help="comma-separated categories (F,G), areas (ja_tokens), layers (tokens_ja), case ids or "
                             "id prefixes (JA-AFX)")
    parser.add_argument("--show", action="store_true",
                        help="print every selected case's verdict and observed output, and write nothing — for "
                             "writing and checking cases")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")     # a cp1252 console must not end the run

    cases = select(CASES, args.only)
    if not cases:
        raise SystemExit(f"--only {args.only!r} matches no case")
    if any(case.lang == "zh" for case in cases):
        import jieba
        jieba.setLogLevel(logging.WARNING)                    # its dictionary-loading chatter is not the report
    if args.show:
        print("\n".join(show_lines(cases, run(cases, args.variant))))
        return 0
    before_path, before = reference(args.baseline)            # chosen BEFORE this run's baseline exists
    results = run(cases, args.variant)

    meta = {"written": datetime.now().isoformat(timespec="seconds"), "label": _label(args.save) or None,
            "variant": args.variant, "only": args.only, "git": harness.git_state(),
            "settings_snapshot": harness.SETTINGS_SNAPSHOT, "engine_revision": analyzer.ENGINE_REVISION,
            "schema_version": token_index.SCHEMA_VERSION, "cases": len(cases),
            "reference": os.path.basename(before_path) if before_path else None}
    lines = report(cases, results, meta, before_path, before)

    os.makedirs(harness.BASELINES, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{meta['label']}" if meta["label"] else "")
    path, n = os.path.join(harness.BASELINES, stem + ".json"), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(harness.BASELINES, f"{stem}-{n}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as handle:      # whole or not at all: "latest" reads it
        json.dump({"meta": meta, "cases": {case.id: _record(case, results[case.id]) for case in cases}}, handle,
                  ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)
    lines += ["", f"Baseline written: {os.path.relpath(path, ROOT)} (report beside it: .txt)"]
    with open(path[:-len(".json")] + ".txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
