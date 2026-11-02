"""The accepted wrongs, readable — every LIMIT case grouped by the decided decision that accepts it: what the app
does, what the language says, and why it is accepted. The user asked for "a running list of accepted wrongs ... so
we can reflect on them in the future" (2026-09-28). Not collected by pytest (no test_ prefix).

    python tests/parsing/accepted_wrongs.py

Writes docs/agent instructions/Parsing_Accepted_Wrongs.md from the register and the newest plain scorecard baseline
(it runs nothing itself). Re-run it after every merge that records or clears a LIMIT.
"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.parsing import harness  # noqa: E402
from tests.parsing.case import CATEGORIES  # noqa: E402
from tests.parsing.cases import CASES  # noqa: E402
from tests.parsing.decisions import DECISIONS  # noqa: E402
from tests.parsing.scorecard import _cut, _show, reference  # noqa: E402

OUT = os.path.join(ROOT, "docs", "agent instructions", "Parsing_Accepted_Wrongs.md")


def _cell(text, width):
    return _cut(" ".join(str(text).split()), width).replace("|", "\\|")


def main():
    harness.load_evaluators()
    path, baseline = reference("latest")
    if not baseline:
        raise SystemExit("no plain scorecard baseline yet — run python tests/parsing/scorecard.py first")
    records = baseline["cases"]
    limits = [case for case in CASES if case.status == "LIMIT"]
    by_decision = defaultdict(list)
    for case in limits:
        by_decision[case.decision].append(case)
    order = sorted(by_decision, key=lambda d: (-len(by_decision[d]), d))
    meta = baseline["meta"]

    lines = [
        "# Accepted wrongs — a running list (local only)",
        "",
        "What the app knowingly gets wrong, and why each was accepted — kept so the choices can be looked back on. Every "
        "entry is a LIMIT case of the parsing suite (`tests/parsing/`), grouped by the decided decision that accepts "
        "it (`tests/parsing/decisions*.py`: its `tradeoff` is the price). A new accepted wrong becomes a LIMIT case "
        "citing its decision — then it appears here.",
        "",
        "**GENERATED — do not edit by hand.** Regenerate after any merge that records or clears a LIMIT: "
        "`PYTHONIOENCODING=utf-8 python tests/parsing/accepted_wrongs.py`.",
        "",
        f"From `{os.path.basename(path)}` ({meta.get('written')}, ENGINE {meta.get('engine_revision')} / SCHEMA "
        f"{meta.get('schema_version')}): **{len(limits)} accepted wrongs under {len(order)} decisions.**",
        "",
        "| Decision | Wrongs | Decided | What it gives up |",
        "|---|---|---|---|",
    ]
    for d in order:
        decision = DECISIONS.get(d)
        tradeoff = decision.tradeoff if decision else "(not in the register)"
        date = decision.date if decision else ""
        lines.append(f"| [{d}](#{d.lower()}) | {len(by_decision[d])} | {date} | {_cell(tradeoff, 150)} |")

    for d in order:
        decision = DECISIONS.get(d)
        lines += ["", f"## {d}", ""]
        if decision:
            if decision.status != "decided":
                lines.append(f"*The register has this decision as **{decision.status}** — a LIMIT must cite a "
                             "decided one.*")
                lines.append("")
            lines += [f"**{decision.question}**", "",
                      f"Decided {decision.date}: {decision.choice}", "",
                      f"**What it gives up:** {decision.tradeoff}", ""]
        else:
            lines += ["*Not in the register.*", ""]
        lines += ["| Case | Category | Judged | The app gives | How it differs from the answer |", "|---|---|---|---|---|"]
        for case in sorted(by_decision[d], key=lambda c: c.id):
            record = records.get(case.id)
            if record is None:
                gives, differs = "(not in this baseline)", ""
            elif record["verdict"] == "pass":
                gives, differs = _show(case.layer, record["observed"]), "**now right — promote to LOCK**"
            else:
                gives, differs = _show(case.layer, record["observed"]), "; ".join(record["problems"])
            judged = case.span or case.text
            lines.append(f"| {case.id} | {case.category} {CATEGORIES.get(case.category, '')} | {_cell(judged, 40)} | "
                         f"{_cell(gives, 160)} | {_cell(differs, 220)} |")

    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"{len(limits)} accepted wrongs under {len(order)} decisions -> {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
