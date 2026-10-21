"""The timing sweep and the full timed set: every bench's moments in one driver, each group of pieces its own timed hold
(M4.1's follow-up; Sonic, 2026-10-20 night: "this would be a replacement for a full [timed set] and the full [set] would
only be run right before a major point … 5 hours is too long. 1.5 hours would be acceptable").

    python tests/qt/bench_sweep.py run --out DIR [--set sweep|full] [--files 20000] [--reps N] [--baseline BASE.json]
                                       [--lock <locks>/with-lock.sh] [--holder "Mado (window) · …"] [--gap 60] [--plan]
    python tests/qt/bench_sweep.py compare DIR --baseline BASE.json      # sweep.md beside the pieces; exit 1 on a flag
    python tests/qt/bench_sweep.py baseline DIR --save BASE.json [--commit SHA]

Not collected by pytest (no `test_` prefix). Run it from the copy; with `--lock`, each group of pieces is its own
`with-lock.sh --max 15 timed` call (each measured under 15 minutes here; sweep.md names one that ran over), 60 s apart
with no lock of ours so queued test runs take their slots first; a group that gave up waiting is tried again a minute
later (for up to two hours). A piece whose JSON is written with no failed run is skipped on a re-run: run the same
command again to resume (a failed piece's JSON is moved aside as `_failed-…` and the piece runs again; a folder holding
another set, size or repetitions is refused).

**The sweep** (`--set sweep`, 12.7 minutes measured on this desktop, three holds of 3.7 / 2.2 / 4.8; routine checks, in
place of the full set): every bench moment once at the hard settings — `bench_drag` (every group: the drag, the lines,
the menu and key moves, hover-lift, the real Goal sheet, the arrival and the toasts) and `bench_scroll` (scroll,
notches, the opens, tabs, outside commits) at 20,000 files, `bench_motion` (each overlay, the toast) and
`bench_settings` (the build, the glide, the fold, the switch, slider-release, a keystroke), all at 150 % (this
desktop's own scale), 5 repetitions; then a short 250 % pass (drag and scroll, 3 repetitions), one Reduced pass (drag
and motion) and one `--cover-scan` pass (drag). Then the comparison: each piece and moment against the stored baseline
(`compare`).

**The full set** (`--set full`, ~50 minutes sized from the sweep's measured piece times — a drag costs ~22 s a
repetition plus ~22 s, a scroll ~5 s plus ~16 s — within Sonic's 90; only right before a major checkpoint the lead puts
to Sonic, on an idle machine): every bench at 100, 150 and 250 %, 10 repetitions (20 for drag and scroll at 150 %,
where the bar is judged), 20,000 files, plus drag and scroll at 2,000 files at 150 %, one Reduced pass of every bench
and one cover-scan pass (drag and scroll) at 150 %. Its table is `full.md` (no baseline: the bar's own table is the
planning folder's `timed_table.py`).

**The comparison** (`compare`, and `run` given `--baseline`): per piece and moment, the worse of the piece's runs — a
moment is **flagged** by name when its frame p95 or its steps' typical worst is over `RATIO` × the baseline's (and over
it by at least `FRAME_FLOOR` / `STEP_FLOOR` ms, so a 0.6 ms toast frame going to 0.95 is noise, not a flag), when it
shows a slow-frame cause of `WATCHED` it didn't have (at least `CAUSE_MIN` such frames: one stray paint frame in five
repetitions is listed, not flagged), when it drew no frames where it drew some, when it is missing, when a run failed,
or when the piece ran at other settings than the baseline; a planned piece with no JSON is flagged with or without a
baseline. `sweep.md` holds the table and what the sweep could miss (a moment slow at 2,000 items but reasonable at
20,000 among them: the sweep runs no 2,000-item pass); the exit is 1 on any flag, 2 when a named baseline is not there.
`baseline` stores a clean sweep's figures (with the commit it ran at and the machine) as the next sweeps' baseline, and
refuses a sweep with a failed or missing piece.
"""
import argparse
import collections
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

RATIO = 1.5                    # a moment over 1.5 × its baseline's p95 frame or typical worst step is flagged
FRAME_FLOOR = 0.5              # … and over it by at least this many ms (frames) …
STEP_FLOOR = 2.0               # … or this many (steps): the noise of 5 repetitions on this desktop
WATCHED = ("gc", "other-thread", "paint")       # a slow-frame cause the moment didn't have is flagged …
CAUSE_MIN = 2                  # … from this many such frames
GROUP_MAX_MIN = 15             # one with-lock call per group, each under this


# --- the sets ------------------------------------------------------------------------------------------------------- #
def plan(name, files=20000, reps=None):
    """[(group, [(piece, bench file, [args])])] for the set `name`. `files` is the large library (`--files 2000` for a
    dry run), `reps` the repetitions (the sweep's 5, the full set's 10)."""
    if name == "sweep":
        r = reps or 5
        short = max(1, min(3, r))
        return [
            ("drag", [
                ("drag", "bench_drag.py", ["--files", files, "--runs", 1, "--cycles", r, "--scales", 150]),
                ("drag-250", "bench_drag.py", ["--files", files, "--runs", 1, "--cycles", short, "--scales", 250]),
            ]),
            ("scroll-motion-settings", [
                ("scroll", "bench_scroll.py", ["--files", files, "--runs", 1, "--reps", r, "--scales", 150]),
                ("scroll-250", "bench_scroll.py", ["--files", files, "--runs", 1, "--reps", short, "--scales", 250]),
                ("motion", "bench_motion.py", ["--rounds", r, "--repeat", 1, "--scales", 150]),
                ("settings-page", "bench_settings.py", ["--rounds", r, "--runs", 1, "--scales", 150]),
            ]),
            ("reduced-cover", [
                ("drag-reduced", "bench_drag.py", ["--files", files, "--runs", 1, "--cycles", r, "--scales", 150,
                                                   "--reduced"]),
                ("motion-reduced", "bench_motion.py", ["--rounds", r, "--repeat", 1, "--scales", 150, "--reduced"]),
                ("drag-cover", "bench_drag.py", ["--files", files, "--runs", 1, "--cycles", r, "--scales", 150,
                                                 "--cover-scan"]),
            ]),
        ]
    if name == "full":
        r = reps or 10
        judged = 2 * r                           # 150 %, where the bar is judged: twice the repetitions (20)

        def drag(scale, n=files, *more, k=r):
            return ["--files", n, "--runs", 1, "--cycles", k, "--scales", scale, *more]

        def scroll(scale, n=files, *more, k=r):
            return ["--files", n, "--runs", 1, "--reps", k, "--scales", scale, *more]
        return [
            ("drag-100-150", [("drag-100", "bench_drag.py", drag(100)),
                              ("drag-150", "bench_drag.py", drag(150, k=judged))]),
            ("drag-250-2k", [("drag-250", "bench_drag.py", drag(250)),
                             ("drag2k-150", "bench_drag.py", drag(150, 2000))]),
            ("scroll", [("scroll-100", "bench_scroll.py", scroll(100)),
                        ("scroll-150", "bench_scroll.py", scroll(150, k=judged)),
                        ("scroll-250", "bench_scroll.py", scroll(250)),
                        ("scroll2k-150", "bench_scroll.py", scroll(150, 2000))]),
            ("motion-settings", [
                ("motion", "bench_motion.py", ["--rounds", r, "--repeat", 1, "--scales", "100,150,250"]),
                ("settings-page", "bench_settings.py", ["--rounds", r, "--runs", 1, "--scales", "100,150,250"]),
            ]),
            ("reduced", [
                ("drag-reduced", "bench_drag.py", drag(150, files, "--reduced")),
                ("scroll-reduced", "bench_scroll.py", scroll(150, files, "--reduced")),
                ("motion-reduced", "bench_motion.py", ["--rounds", r, "--repeat", 1, "--scales", 150, "--reduced"]),
                ("settings-page-reduced", "bench_settings.py",
                 ["--rounds", r, "--runs", 1, "--scales", 150, "--reduced"]),
            ]),
            ("cover", [("drag-cover", "bench_drag.py", drag(150, files, "--cover-scan")),
                       ("scroll-cover", "bench_scroll.py", scroll(150, files, "--cover-scan"))]),
        ]
    raise SystemExit(f"unknown set: {name} (sweep, full)")


def pieces(name, files=20000, reps=None):
    return {p: (bench, [str(x) for x in args]) for _, group in plan(name, files, reps) for p, bench, args in group}


# --- reading a run -------------------------------------------------------------------------------------------------- #
def _worse(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def flatten(doc):
    """A bench's JSON -> {"settings": what it ran at, "errors": [...], "moments": {moment: {p95, step, causes,
    frames}}}: per moment the worse of its runs' frame p95 and steps' typical worst, the slow frames' causes summed. An
    error: a run that failed or exited non-zero, ran at another scale than asked, or raised in a slot (its stderr)."""
    moments = collections.OrderedDict()
    errors = []
    for r in doc.get("results") or []:
        if r.get("error") or r.get("exit"):
            errors.append(str(r.get("error") or f"exit {r.get('exit')}")[:200])
        if r.get("scale_mismatch"):
            errors.append(f"ran at dpr {r.get('dpr')}, not {r.get('scale')} %")
        if "Traceback" in str((r.get("extra") or {}).get("stderr") or ""):
            errors.append("a traceback in the child's stderr")
        for m, v in (r.get("moments") or {}).items():
            c = moments.setdefault(m, {"p95": None, "step": None, "causes": {}, "frames": 0})
            c["p95"] = _worse(c["p95"], v.get("frames_p95_ms"))
            c["step"] = _worse(c["step"], v.get("step_worst_p95_ms"))
            c["frames"] += v.get("frames_n") or 0
            for k, n in (v.get("slow_causes") or {}).items():
                c["causes"][k] = c["causes"].get(k, 0) + n
    meta = dict(doc.get("meta") or {})
    meta.pop("only", None)                       # the groups' names: what ran is the moments themselves
    settings = {"bench": doc.get("bench"), "scales": doc.get("scales"), "runs": doc.get("runs_per_scale"),
                "reduced": bool(doc.get("reduced")), **meta}
    return {"settings": settings, "errors": errors, "moments": moments}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and "results" in doc else None


def load(out):
    """{piece: flattened} for every `<piece>.json` in `out` (`_`-named files are the driver's own)."""
    found = collections.OrderedDict()
    for f in sorted(os.listdir(out)):
        if f.endswith(".json") and not f.startswith("_"):
            doc = _read(os.path.join(out, f))
            if doc is not None:
                found[f[:-5]] = flatten(doc)
    return found


# --- the comparison ------------------------------------------------------------------------------------------------- #
def _over(now, base, floor, ratio):
    return now is not None and base is not None and now > ratio * base and now - base >= floor


def _grew(what, now, base):
    return f"{what} ×{now / base:.2f}" if base else f"{what} {_fmt(now)} (base 0)"


def compare(now, base, ratio=RATIO, frame_floor=FRAME_FLOOR, step_floor=STEP_FLOOR, cause_min=CAUSE_MIN):
    """[(piece, moment, base entry or None, now entry or None, [flags], [notes])], the baseline's pieces first, in its
    order, then any piece or moment new since it (noted, never flagged)."""
    rows = []
    for piece, b in base.items():
        n = now.get(piece)
        if n is None:
            rows.append((piece, "-", None, None, ["piece not run"], []))
            continue
        if n["settings"] != b["settings"]:
            diff = sorted(k for k in set(n["settings"]) | set(b["settings"])
                          if n["settings"].get(k) != b["settings"].get(k))
            rows.append((piece, "-", None, None, ["other settings than the baseline: " + ", ".join(diff)], []))
        for e in n["errors"]:
            rows.append((piece, "-", None, None, ["run failed: " + e], []))
        for m, bm in b["moments"].items():
            nm = n["moments"].get(m)
            if nm is None:
                rows.append((piece, m, bm, None, ["missing"], []))
                continue
            flags, notes = [], []
            if _over(nm["p95"], bm["p95"], frame_floor, ratio):
                flags.append(_grew("p95", nm["p95"], bm["p95"]))
            if _over(nm["step"], bm["step"], step_floor, ratio):
                flags.append(_grew("step", nm["step"], bm["step"]))
            if bm["frames"] and not nm["frames"]:
                flags.append("no frames")
            for cause in WATCHED:
                k = nm["causes"].get(cause, 0)
                if k and not bm["causes"].get(cause):
                    (flags if k >= cause_min else notes).append(f"new cause {cause} {k}")
            rows.append((piece, m, bm, nm, flags, notes))
        for m, nm in n["moments"].items():
            if m not in b["moments"]:
                rows.append((piece, m, None, nm, [], ["new moment (no baseline)"]))
    for piece, n in now.items():
        if piece not in base:
            for m, nm in n["moments"].items():
                rows.append((piece, m, None, nm, [], ["new piece (no baseline)"]))
    return rows


def figures(now):
    """The rows without a baseline: the figures, and every failed run flagged."""
    rows = [(p, m, None, v, [], []) for p, n in now.items() for m, v in n["moments"].items()]
    return rows + [(p, "-", None, None, ["run failed: " + e], []) for p, n in now.items() for e in n["errors"]]


def unplayed(now, planned):
    """A planned piece with no JSON (it crashed before writing one, or never ran): flagged, baseline or not."""
    return [(p, "-", None, None, ["piece not run"], []) for p in planned if p not in now]


def _fmt(v):
    return "-" if v is None else f"{v:.2f}".rstrip("0").rstrip(".")


def _causes(c):
    return " ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])) if c else "-"


def markdown(rows, title, head_lines=(), misses=()):
    flagged = [r for r in rows if r[4]]
    lines = [f"# {title}", "", *head_lines]
    if flagged:
        lines += ["", f"**FLAGGED: {len(flagged)}** — " + "; ".join(
            f"{p}{' · ' + m if m != '-' else ''} ({', '.join(f)})" for p, m, _, _, f, _ in flagged)]
    else:
        lines += ["", "**No flags.**"]
    lines += ["", f"Flag: p95 frame or typical-worst step > {RATIO} × the baseline's (and by ≥ {FRAME_FLOOR} / "
                  f"{STEP_FLOOR} ms), a new slow-frame cause of {', '.join(WATCHED)} (≥ {CAUSE_MIN} frames), "
                  "no frames, missing, a piece not run, a failed run, other settings."]
    if misses:
        lines += ["", "**What it could miss:**", *[f"- {m}" for m in misses]]
    lines += ["", "| piece | moment | p95 base → now | step base → now | slow causes now | flag |",
              "|---|---|---|---|---|---|"]
    for piece, m, b, n, flags, notes in rows:
        p95 = f"{_fmt(b and b['p95'])} → {_fmt(n and n['p95'])}"
        step = f"{_fmt(b and b['step'])} → {_fmt(n and n['step'])}"
        verdict = "**" + ", ".join(flags) + "**" if flags else ""
        if notes:
            verdict = (verdict + "; " if verdict else "") + ", ".join(notes)
        lines.append(f"| {piece} | {m} | {p95} | {step} | {_causes(n['causes']) if n else '-'} | {verdict or 'ok'} |")
    return "\n".join(lines) + "\n"


SIZE_BLIND = ("a moment slow at 2,000 items that looks reasonable at 20,000 (work that doesn't scale with the library, "
              "a cache or index that only pays off on a big library)")
MISSES = {
    "sweep": [
        "100, 125, 175 and 200 % (150 % only, and a short 250 % pass for drag and scroll)",
        SIZE_BLIND + ": the sweep runs no 2,000-item pass",
        "a slow-frame cause rarer than about 1 in 5 repetitions, and run-to-run spread (one run per piece)",
        "Reduced for scroll and Settings, the cover scan beside scroll",
        "a moment crossing the bar by less than 1.5 × its baseline (the full set's bar table judges the bar)",
    ],
    "full": [
        "125, 175 and 200 % (100, 150 and 250 % only: the bar is judged at 150 %, 250 % is the laptop's scale)",
        SIZE_BLIND + ": only drag and scroll run at 2,000 items, at 150 % (Reduced, the cover scan and 100 / 250 % at "
        "20,000 only)",
        "a slow-frame cause rarer than about 1 in 10 repetitions (1 in 20 for drag and scroll at 150 %), and "
        "run-to-run spread (one run per scale)",
        "Reduced and the cover scan at any scale but 150 %",
    ],
}


def read_baseline(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc, doc["pieces"]


def _planned(out):
    r = _run_info(out)
    return list(pieces(r["set"], r["files"], r.get("reps"))) if r.get("set") else []


def save_baseline(out, path, commit=None):
    """A clean sweep's figures as the baseline: refused when a planned piece is missing or a run failed."""
    now = load(out)
    bad = [r for r in figures(now) + unplayed(now, _planned(out)) if r[4]]
    if bad:
        raise SystemExit("not a clean sweep, no baseline stored: " + "; ".join(f"{b[0]} ({b[4][0]})" for b in bad))
    info = _run_info(out)
    doc = {"set": info.get("set", "sweep"), "commit": commit or info.get("commit") or _commit()[0],
           "dirty": info.get("dirty"), "taken": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "ran": info.get("started"), "machine": os.environ.get("COMPUTERNAME", "?"), "from": os.path.abspath(out),
           "wall_s": info.get("total_s"), "pieces": now}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def write_report(out, baseline_path, name="sweep.md", set_name="sweep"):
    """The table (against the baseline when there is one) written beside the pieces. -> the exit: 1 on a flag, 2 when
    a baseline is named but not there."""
    if baseline_path and not os.path.exists(baseline_path):
        print(f"bench_sweep: the baseline {baseline_path} is not there", file=sys.stderr)
        return 2
    now = load(out)
    info = _run_info(out)
    head = [f"Run: `{os.path.abspath(out)}` at {info.get('commit') or _commit()[0]}"
            f"{' (with uncommitted changes)' if info.get('dirty') else ''}; {_minutes(info.get('total_s'))} in all "
            f"({', '.join(f'{p} {_minutes(s)}' for p, s in info.get('pieces', {}).items())})."]
    long = [f"{g} {_minutes(s)}" for g, s in info.get("groups", {}).items() if s > GROUP_MAX_MIN * 60]
    if long:
        head.append(f"Over the {GROUP_MAX_MIN}-minute hold: {', '.join(long)} — split the group.")
    if baseline_path:
        doc, base = read_baseline(baseline_path)
        head.append(f"Baseline: `{baseline_path}` (commit {doc.get('commit')}, taken {doc.get('taken')} on "
                    f"{doc.get('machine')}).")
        rows = compare(now, base)
    else:
        head.append("No baseline: the figures only (store a clean sweep with `baseline`).")
        rows = figures(now)
    seen = {r[0] for r in rows if r[4] == ["piece not run"]}
    rows += [r for r in unplayed(now, _planned(out)) if r[0] not in seen]
    md = markdown(rows, f"Timing {name[:-3]}", head, MISSES.get(set_name, ()))
    with open(os.path.join(out, name), "w", encoding="utf-8") as f:
        f.write(md)
    print(md, flush=True)
    return 1 if any(r[4] for r in rows) else 0


# --- running -------------------------------------------------------------------------------------------------------- #
MAX_WAIT_S = 2 * 3600          # a group still waiting for the machine after this is left out (and flagged "not run")


def _commit():
    """(short sha, whether tracked files have uncommitted changes)."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             check=False).stdout.strip() or "?"
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                    capture_output=True, text=True, check=False).stdout.strip())
    except OSError:
        return "?", None
    return sha, dirty


def _minutes(s):
    return "-" if s is None else f"{s / 60:.1f} min"


def _run_info(out):
    """`_run.json`: the set, the library size and repetitions it was started with, the commit (and whether the tree
    had uncommitted changes) when it started, each piece's and group's time."""
    path = os.path.join(out, "_run.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        t = json.load(f)
    t["total_s"] = round(t["end"] - t["start"], 1) if t.get("end") and t.get("start") else None
    return t


def _note(out, **changes):
    path = os.path.join(out, "_run.json")
    t = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            t = json.load(f)
    for k in ("pieces", "groups"):
        t.setdefault(k, {}).update(changes.pop(k, {}))
    t.update(changes)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=1)


def iso_env(tmp):
    """The bench's environment: fresh APPDATA / LOCALAPPDATA / TEMP (deleted after), no test root of the caller's, no
    update check, no Anki sync, telemetry at dev, UTF-8 output; the user's site-packages kept."""
    env = dict(os.environ)
    env.pop("SURASURA_TEST_ROOT", None)
    env.setdefault("PYTHONUSERBASE", os.path.join(os.environ.get("APPDATA", ""), "Python"))
    for k, d in (("APPDATA", "ad"), ("LOCALAPPDATA", "lad"), ("TEMP", "tmp"), ("TMP", "tmp")):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
        env[k] = os.path.join(tmp, d)
    env.update(SURASURA_NO_UPDATE_CHECK="1", SURASURA_NO_ANKI_SYNC="1", TELEMETRY_ENV="dev", TELEMETRY_URL="",
               PYTHONIOENCODING="utf-8")
    return env


def _done(result):
    """A piece is done when its JSON is there and no run of it failed; a failed one is moved aside (`_failed-…`, kept
    for reading) so a re-run plays it again."""
    if not (os.path.exists(result) and os.path.getsize(result)):
        return False
    doc = _read(result)
    if doc is not None and not flatten(doc)["errors"]:
        return True
    d, f = os.path.split(result)
    os.replace(result, os.path.join(d, f"_failed-{f[:-5]}-{time.strftime('%Y%m%d-%H%M%S')}.json"))
    return False


def run_group(out, names, set_name, files, reps):
    """Each piece in turn (the with-lock call's command): its bench, its JSON and log in `out`. The benches' own exits
    are not the verdict (bench_motion exits 1 on a missed target): a piece without its JSON is flagged by the report."""
    known = pieces(set_name, files, reps)
    for name in names:
        bench, args = known[name]
        result = os.path.join(out, name + ".json")
        if _done(result):
            continue
        tmp = tempfile.mkdtemp(prefix="surasura-sweep-")
        t = time.time()
        try:
            with open(os.path.join(out, name + ".log"), "a", encoding="utf-8") as log:
                p = subprocess.run([sys.executable, os.path.join(HERE, bench), *args, "--json", result], cwd=ROOT,
                                   env=iso_env(tmp), stdout=log, stderr=subprocess.STDOUT, check=False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        _note(out, pieces={name: round(time.time() - t, 1)})
        print(f"{time.strftime('%Y-%m-%d %H:%M')} {name} rc={p.returncode} {time.time() - t:.0f}s", flush=True)
    return 0


def git_bash():
    """Git's bash.exe, found beside git (Windows' own search, and PATH from PowerShell, find WSL's bash first)."""
    git = shutil.which("git")
    if git:
        d = os.path.dirname(os.path.realpath(git))
        for _ in range(4):                       # <Git>\cmd, <Git>\bin, <Git>\mingw64\bin -> <Git>
            for rel in (("usr", "bin", "bash.exe"), ("bin", "bash.exe")):
                if os.path.exists(os.path.join(d, *rel)):
                    return os.path.join(d, *rel)
            d = os.path.dirname(d)
    b = shutil.which("bash")
    system = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    if b and not os.path.normcase(os.path.abspath(b)).startswith(system):
        return b
    raise SystemExit("bench_sweep: Git's bash not found (with-lock.sh needs it)")


def run(a):
    groups = plan(a.set, a.files, a.reps)
    if a.plan:
        for g, ps in groups:
            print(g)
            for p, bench, args in ps:
                print(f"  {p}: {bench} {' '.join(str(x) for x in args)}")
        return 0
    if a.baseline and not os.path.exists(a.baseline):
        print(f"bench_sweep: the baseline {a.baseline} is not there", file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    info = _run_info(a.out)
    asked = {"set": a.set, "files": a.files, "reps": a.reps}
    held = {k: info.get(k) for k in asked}
    if info.get("set") and held != asked:
        print(f"bench_sweep: {a.out} holds another run ({held}): use a fresh folder", file=sys.stderr)
        return 2
    if not info.get("start"):
        sha, dirty = _commit()
        _note(a.out, start=time.time(), started=time.strftime("%Y-%m-%d %H:%M"), commit=sha, dirty=dirty, **asked)
    bash = git_bash() if a.lock else None
    ran = False
    for g, ps in groups:
        todo = [p for p, _, _ in ps if not _done(os.path.join(a.out, p + ".json"))]
        if not todo:
            continue
        if ran and a.lock:
            time.sleep(a.gap)                    # no lock of ours: a queued test run takes its slot first
        ran = True
        cmd = [sys.executable, os.path.abspath(__file__), "_group", "--out", os.path.abspath(a.out), "--set", a.set,
               "--files", str(a.files)] + (["--reps", str(a.reps)] if a.reps else []) + todo
        if a.lock:
            cmd = [bash, a.lock, "--max", str(GROUP_MAX_MIN), "timed", a.holder, ROOT, f"{a.set} {g}", "--"] + cmd
        waited = time.time()
        while True:
            t = time.time()
            rc = subprocess.run(cmd, cwd=ROOT, check=False).returncode
            if rc != 75:
                _note(a.out, groups={g: round(time.time() - t, 1)})
                break
            if time.time() - waited > MAX_WAIT_S:         # left out: the report flags its pieces "not run"
                print(f"{time.strftime('%Y-%m-%d %H:%M')} {g} never got the machine; left out", flush=True)
                break
            print(f"{time.strftime('%Y-%m-%d %H:%M')} {g} gave up waiting; again in 60 s", flush=True)
            time.sleep(60)                       # with-lock gave up waiting for the slots: again in a minute
    _note(a.out, end=time.time())
    if a.set == "sweep":
        return write_report(a.out, a.baseline)
    return write_report(a.out, None, "full.md", "full")


def utf8_stdout():
    """The table's → × ≥ printed on a cp1252 console (Git Bash, a redirected log) rather than raising after sweep.md
    was written. Called when run as a script, never on an importer's stdout."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--set", default="sweep", choices=("sweep", "full"))
    r.add_argument("--files", type=int, default=20000)
    r.add_argument("--reps", type=int, default=None)
    r.add_argument("--baseline", default=os.environ.get("SURASURA_SWEEP_BASELINE"))
    r.add_argument("--lock", default=None, help="with-lock.sh: each group its own timed hold")
    r.add_argument("--holder", default="bench_sweep")
    r.add_argument("--gap", type=int, default=60)
    r.add_argument("--plan", action="store_true", help="print the pieces and stop")
    g = sub.add_parser("_group")
    g.add_argument("--out", required=True)
    g.add_argument("--set", required=True)
    g.add_argument("--files", type=int, required=True)
    g.add_argument("--reps", type=int, default=None)
    g.add_argument("names", nargs="+")
    c = sub.add_parser("compare")
    c.add_argument("out")
    c.add_argument("--baseline", default=os.environ.get("SURASURA_SWEEP_BASELINE"))
    b = sub.add_parser("baseline")
    b.add_argument("out")
    b.add_argument("--save", required=True)
    b.add_argument("--commit", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(a)
    if a.cmd == "_group":
        return run_group(a.out, a.names, a.set, a.files, a.reps)
    if a.cmd == "compare":
        set_name = _run_info(a.out).get("set") or "sweep"
        return write_report(a.out, a.baseline, f"{set_name}.md", set_name)
    doc = save_baseline(a.out, a.save, a.commit)
    print(f"baseline: {a.save} ({len(doc['pieces'])} pieces, commit {doc['commit']})")
    return 0


if __name__ == "__main__":
    utf8_stdout()
    sys.exit(main())
