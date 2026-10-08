"""The shell's budgets on this machine (W2.1 rows 8 and 11; the window's spec 07 §7.1 *Budgets*, BRIEF rule 12).

    python tests/qt/measure_shell.py [--runs 5] [--idle 5] [--hud]

Starts the window the way a user does (`app_entry.py`, no arguments: the 3.0 line's default start), `--runs` times,
each in a fresh process under a temp `SURASURA_TEST_ROOT` (checked: never the real settings or local data). Each run
writes, through `SURASURA_SHELL_PROBE`:
- **first frame**: milliseconds from the process's creation to the window's first frame flushed (Python's start, the
  imports, the settings read, the look, the window: everything a user waits through);
- **idle memory** after `--idle` seconds: private bytes and the working set;
- with `--hud`: the frame-time HUD over the run, after the first paint, while the window switches tabs ten times and
  takes 500 bar updates in a burst — the count of GUI-thread steps over 4 ms (row 8).

- with `--phases` (M2.1 row D): where each run's first frame went — Python and `app_entry`, the imports, the
  QApplication, the single-instance claim, the services, the look, the window, showing, the first paint, its flush — each
  with the process's CPU, page faults, bytes read and the machine's idle share; then each phase's median and spread;
- with `--hud`, also each late tick's cause (`hud.classify`: gc · step · gui-busy · gil · machine · timer).
- `--gc-freeze` (an A/B for row D): the window's collector freezes its start-up objects after the first frame.

The window is shown without taking the keyboard (it opens on this desktop for `--idle` seconds each run). Prints one
JSON line per run and the medians. Budgets (BRIEF rule 12, on a mid-range laptop at 150 %): first frame ≤ 1 s, idle ≤
~250 MB, no step over 4 ms. This desktop's target is ≤ 0.4 s (a laptop is 2–3× slower: charter S8); the laptop's own
run waits for Sonic's go.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def one_run(idle, hud, busy=False, fontengine="", gc_freeze=False, piled=False):
    root = tempfile.mkdtemp(prefix="w21-measure-")
    probe = os.path.join(root, "probe.json")
    import shutil                                   # the test root is also where bundled resources are read: the mark
    shutil.copytree(os.path.join(ROOT, "app", "assets"), os.path.join(root, "app", "assets"))
    env = dict(os.environ, SURASURA_TEST_ROOT=root, SURASURA_SHELL_PROBE=probe, SURASURA_SHELL_PROBE_IDLE=str(idle),
               SURASURA_INSTANCE_NAME=f"surasura-measure-{os.getpid()}-{os.path.basename(root)}")
    env.pop("QT_QPA_PLATFORM", None)
    env.pop("SURASURA_FREEZE_MOTION", None)
    if hud:
        env.update(SURASURA_HUD="1", SURASURA_SHELL_PROBE_EXERCISE="1")
    else:
        env.pop("SURASURA_HUD", None)
    if busy:
        env["SURASURA_SHELL_PROBE_BUSY"] = "1"
    env.pop("SURASURA_GC_FREEZE", None)
    if gc_freeze:
        env["SURASURA_GC_FREEZE"] = "1"
    env.pop("SURASURA_SHELL_PROBE_PILED", None)
    if piled:
        env["SURASURA_SHELL_PROBE_PILED"] = "1"
    if fontengine:
        env["QT_QPA_PLATFORM"] = "windows:fontengine=" + fontengine
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "app_entry.py")], cwd=root, env=env,
                          capture_output=True, text=True, timeout=idle + 60)
    if not os.path.exists(probe):
        return {"error": f"no probe file (exit {proc.returncode}): {proc.stderr[-800:]}"}
    with open(probe, encoding="utf-8") as f:
        result = json.load(f)
    assert os.path.exists(os.path.join(root, "local")), "the run wrote its local data under the test root"
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--idle", type=float, default=5.0)
    ap.add_argument("--hud", action="store_true")
    ap.add_argument("--busy", action="store_true", help="a CPU-bound Python worker beside the burst (worst case)")
    ap.add_argument("--fontengine", default="", help="e.g. gdi: Qt's Windows font engine, for comparison")
    ap.add_argument("--phases", action="store_true", help="where the first frame went, phase by phase (M2.1 row D)")
    ap.add_argument("--gc-freeze", action="store_true", help="A/B: freeze the collector's start-up objects")
    ap.add_argument("--piled", action="store_true", help="A/B: W2.1's burst, 500 timers set at once")
    args = ap.parse_args()
    runs = []
    for _ in range(args.runs):
        r = one_run(args.idle, args.hud, args.busy, args.fontengine, args.gc_freeze, args.piled)
        print(json.dumps(r), flush=True)
        if args.phases and r.get("phases"):
            print("  " + " · ".join(f"{p['phase']} {p['ms']}" + (f" (cpu {p['cpu_ms']}, idle {p['idle_share']}, "
                                                                  f"faults {p.get('faults')}, read {p.get('read_kb')} KB)"
                                                                  if p.get("cpu_ms") is not None else "")
                                    for p in r["phases"]), flush=True)
        runs.append(r)
    ok = [r for r in runs if "error" not in r and r.get("first_frame_ms")]
    if not ok:
        print("NO RUN MEASURED")
        return 1
    summary = {
        "runs": len(ok),
        "first_frame_ms_median": round(statistics.median(r["first_frame_ms"] for r in ok), 1),
        "first_frame_ms_max": round(max(r["first_frame_ms"] for r in ok), 1),
        "private_mb_median": round(statistics.median(r["memory"]["private_mb"] for r in ok), 1),
        "working_set_mb_median": round(statistics.median(r["memory"]["working_set_mb"] for r in ok), 1),
    }
    if args.hud:
        summary["steps_over_4ms_after_first_paint"] = [r["hud"]["steps"]["over_4ms"] for r in ok]
        summary["step_max_ms"] = max(r["hud"]["steps"]["max_ms"] for r in ok)
        summary["frame_p95_ms"] = max(r["hud"]["frames"]["p95_ms"] for r in ok)
        summary["late_ticks_over_4ms"] = [r["hud"]["late"]["over_4ms"] for r in ok]
        summary["late_max_ms"] = max(r["hud"]["late"]["max_ms"] for r in ok)
        causes = {}
        for r in ok:
            for k, v in r["hud"]["late"].get("causes", {}).items():
                causes[k] = causes.get(k, 0) + v
        summary["late_causes"] = causes
        for span in ("tab-switch", "bar-update"):
            got = [r["hud"]["spans"].get(span) for r in ok if r["hud"]["spans"].get(span)]
            if got:
                summary[f"{span}_max_ms"] = max(g["max_ms"] for g in got)
                summary[f"{span}_p95_ms"] = max(g["p95_ms"] for g in got)
    if args.phases:
        names = [p["phase"] for p in ok[0].get("phases", [])]
        summary["phases_median_ms"] = {}
        for name in names:
            got = [p["ms"] for r in ok for p in r.get("phases", []) if p["phase"] == name and p["ms"] is not None]
            if got:
                summary["phases_median_ms"][name] = [round(statistics.median(got), 1), round(min(got), 1),
                                                     round(max(got), 1)]
    print("SUMMARY " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
