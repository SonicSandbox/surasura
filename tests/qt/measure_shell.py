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


def one_run(idle, hud, busy=False, fontengine=""):
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
    if busy:
        env["SURASURA_SHELL_PROBE_BUSY"] = "1"
    if fontengine:
        env["QT_QPA_PLATFORM"] = "windows:fontengine=" + fontengine

    else:
        env.pop("SURASURA_HUD", None)
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
    args = ap.parse_args()
    runs = []
    for _ in range(args.runs):
        r = one_run(args.idle, args.hud, args.busy, args.fontengine)
        print(json.dumps(r), flush=True)
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
        for span in ("tab-switch", "bar-update"):
            got = [r["hud"]["spans"].get(span) for r in ok if r["hud"]["spans"].get(span)]
            if got:
                summary[f"{span}_max_ms"] = max(g["max_ms"] for g in got)
                summary[f"{span}_p95_ms"] = max(g["p95_ms"] for g in got)
    print("SUMMARY " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
