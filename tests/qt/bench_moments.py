"""What every bench reports, moment by moment (M4.1 row 2; the RUNBOOK's *The moments* and *The bar*). Not a bench
itself and not collected by pytest (no `test_` prefix): `bench_drag.py`, `bench_scroll.py`, `bench_motion.py` and
`bench_settings.py` share it.

**A moment** is one thing a user feels (a pick-up, a menu move, a toast rising, the nav's glide), repeated: the child
marks each repetition (`Moments.begin(name)` … `end()`), and after the moment's last one waits until the motion clock
is still, then counts its wake-ups over `QUIET_MS` (`Moments.still`: the bar says 0). Per moment, from the HUD's
every-window frames and timed steps (`app/qt/hud.py`):
- **frames** p95 / max (every window's — main, lift, ghost, popup — their count by window), and the clock's frames;
- **the slow frames** (over `hud.SLOW_MS`, 6.4 ms: the laptop's 16 ÷ 2.5) by cause (`hud.frame_cause`), the worst
  few listed with their window and where their time went;
- **the steps**: the typical worst — the p95 over the moment's repetitions of each repetition's worst GUI-thread step
  (every step overlapping it) — and the slowest, and how many went over 4 ms (a bench may time a moment's pieces
  itself: `own_steps`, said in `steps_from`);
- **wakes after**: the clock's wake-ups once still (None: it never stopped within `STILL_WAIT_MS`).

**The parent's side** (`scaled_runs`): each `--scales` value its own child process at TRUE scale (`QT_SCALE_FACTOR` =
scale ÷ this desktop's own scaling; each child records its `dpr`), in a fresh temp `SURASURA_TEST_ROOT` with fresh
`APPDATA` / `LOCALAPPDATA` beside it (the user's site-packages kept through `PYTHONUSERBASE`); `--reduced` writes
`app_motion: reduced` into that root's own `settings.json`. A JSON with every run, and a short markdown table.
"""
import bisect
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BAR = {"frame_p95": 3.2, "slow": 6.4, "step_worst": 4.0, "wakes_after": 0}     # this desktop's, judged at 150 %
QUIET_MS = 400                       # the clock watched this long once still
STILL_WAIT_MS = 4000                 # how long a moment may take to come to rest before "never still"
SCALES = (100, 125, 150, 175, 200, 250)
LONGEST_S = 2.0                      # a step that began this long before a repetition is never looked for


def _p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 2)


# --- the child's side ------------------------------------------------------------------------------------------------ #
class Moments:
    """The repetitions of each moment, by time, and the clock's wake-ups after each moment once it is still."""

    def __init__(self, hud, tag=True):
        self.hud = hud
        self.tag = tag                               # the moment's name as the HUD's tag (its clock frames by moment)
        self.reps = []                               # [name, t0, t1]
        self.order = []
        self.wakes = {}                              # name -> wake-ups once still (None: never still)
        self.notes = {}                              # name -> what the bench saw (counts, timings of its own)
        self.rep_worst = {}                          # name -> each repetition's worst step, timed by the bench itself
        self.rep_worst_from = {}
        hud.keep = 10 ** 6                           # a bench reads every frame and step of its run

    def begin(self, name):
        self.end()
        if name not in self.order:
            self.order.append(name)
        self.reps.append([name, time.perf_counter(), None])
        if self.tag:
            self.hud.tag = name

    def end(self):
        if self.reps and self.reps[-1][2] is None:
            self.reps[-1][2] = time.perf_counter()
            if self.tag:
                self.hud.tag = None

    def note(self, name, key, value):
        self.notes.setdefault(name, {}).setdefault(key, []).append(value)

    def own_steps(self, name, worst_ms, what):
        """A repetition's worst GUI-thread piece as the bench timed it — for a moment whose loop never waits (a build in
        `singleShot(0)` slices is one stretch to the dispatcher, though input runs between its slices)."""
        self.rep_worst.setdefault(name, []).append(worst_ms)
        self.rep_worst_from[name] = what

    def still(self, name, then, quiet_ms=QUIET_MS, wait_ms=STILL_WAIT_MS):
        """After `name`'s last repetition: once the clock has stopped, its wake-ups over `quiet_ms`; then `then()`."""
        from PyQt6.QtCore import QTimer
        from app.qt import motion
        self.end()
        clock = motion.clock()
        deadline = time.perf_counter() + wait_ms / 1000.0

        def poll():
            if clock.running and time.perf_counter() < deadline:
                QTimer.singleShot(20, poll)
                return
            if clock.running:
                self.wakes[name] = None
                then()
                return
            w0 = clock.stats.wakes

            def count():
                self.wakes[name] = clock.stats.wakes - w0
                then()
            QTimer.singleShot(quiet_ms, count)
        poll()

    def summary(self):
        """{moment: its figures} in the order the moments first ran."""
        from app.qt import hud as hud_module
        self.end()
        frames = sorted(self.hud.explain_frames(), key=lambda f: f["t0"])
        f_at = [f["t0"] for f in frames]
        steps = sorted(self.hud.step_log)
        s_at = [s for s, _ms in steps]
        out = {}
        for name in self.order:
            reps = [(t0, t1) for n, t0, t1 in self.reps if n == name and t1 is not None]
            fr, worsts, over = [], [], 0
            for t0, t1 in reps:
                fr.extend(frames[bisect.bisect_left(f_at, t0):bisect.bisect_right(f_at, t1)])
                # the steps that overlap it (the one holding its click began before it)
                st = [ms for s, ms in steps[bisect.bisect_left(s_at, t0 - LONGEST_S):bisect.bisect_right(s_at, t1)]
                      if s + ms / 1000.0 > t0]
                worsts.append(max(st, default=0.0))
                over += sum(1 for ms in st if ms > 4.0)
            own = self.rep_worst.get(name)
            if own:                                  # the bench timed this moment's GUI-thread pieces itself
                worsts = own
            ms = [f["ms"] for f in fr]
            windows = {}
            for f in fr:
                windows[f["window"]] = windows.get(f["window"], 0) + 1
            slow = sorted((f for f in fr if f["ms"] > hud_module.SLOW_MS), key=lambda f: -f["ms"])
            causes = {}
            for f in slow:
                causes[f["cause"]] = causes.get(f["cause"], 0) + 1
            out[name] = {"reps": len(reps), "frames_n": len(fr), "frames_p95_ms": _p95(ms),
                         "frames_max_ms": round(max(ms), 2) if ms else None, "windows": windows,
                         "clock_frames": sum(1 for f in fr if f["work_ms"] is not None),
                         "slow_n": len(slow), "slow_causes": causes,
                         "slow": [hud_module.slow_line(f, self.hud.ignore_before) for f in slow[:8]],
                         "step_worst_p95_ms": _p95(worsts), "step_slowest_ms": round(max(worsts), 2) if worsts else None,
                         "steps_over_4ms": over, "wakes_after": self.wakes.get(name, "not counted")}
            if own:
                out[name]["steps_from"] = self.rep_worst_from.get(name)
            if name in self.notes:
                out[name]["notes"] = {k: _stats(v) for k, v in self.notes[name].items()}
        return out


def _stats(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums or len(nums) != len(values):
        return values
    return {"n": len(nums), "median": round(statistics.median(nums), 2), "p95": _p95(nums), "max": round(max(nums), 2)}


def reduced_wanted():
    return os.environ.get("SURASURA_BENCH_REDUCED") == "1"


def apply_reduced():
    """In the child, after the window opened: the clock told too (the settings file already says it)."""
    if reduced_wanted():
        from app.qt import motion
        motion.clock().mode.set_setting("reduced")


# --- the parent's side ----------------------------------------------------------------------------------------------- #
def system_scale():
    """This desktop's own scaling (1.5 at 150 %)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def parse_scales(text):
    return [int(x) for x in str(text).split(",") if x.strip()]


def fresh_root(work, reduced=False, assets=False):
    """A temp test root with its own APPDATA and LOCALAPPDATA beside it: (root, env changes)."""
    base = tempfile.mkdtemp(prefix="run-", dir=work)
    root = os.path.join(base, "root")
    for d in ("root", "appdata", "localappdata"):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    if assets:                                   # the test root is where bundled resources are read
        shutil.copytree(os.path.join(ROOT, "app", "assets"), os.path.join(root, "app", "assets"))
    if reduced:
        with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"app_motion": "reduced"}, f)
    user_base = os.environ.get("PYTHONUSERBASE") or os.path.join(os.environ.get("APPDATA", ""), "Python")
    env = {"SURASURA_TEST_ROOT": root, "APPDATA": os.path.join(base, "appdata"),
           "LOCALAPPDATA": os.path.join(base, "localappdata"), "PYTHONUSERBASE": user_base,
           "SURASURA_BENCH_REDUCED": "1" if reduced else "0"}
    return root, env


def child_env(scale, extra):
    env = dict(os.environ)
    for k in ("QT_QPA_PLATFORM", "SURASURA_FREEZE_MOTION", "QT_SCALE_FACTOR"):
        env.pop(k, None)
    if scale:
        env["QT_SCALE_FACTOR"] = f"{scale / 100 / system_scale():.6f}"
    env.update(extra)
    return env


def scaled_runs(name, scales, runs, reduced, one_run, out_path=None, meta=None):
    """Each scale × run its own child (`one_run(scale, root, env, i)` -> its result dict, with "dpr" and "moments"); the
    JSON written to `out_path` (+ its markdown beside, `.md`). -> the whole output."""
    work = tempfile.mkdtemp(prefix=f"surasura-{name}-")
    results = []
    for scale in scales:
        for i in range(runs):
            root, extra = fresh_root(work, reduced=reduced, assets=True)
            t = time.perf_counter()
            r = one_run(scale, root, child_env(scale, extra), i)
            r.update(scale=scale, run=i + 1, reduced=reduced, wall_s=round(time.perf_counter() - t, 1))
            if scale and r.get("dpr") and abs(r["dpr"] - scale / 100) > 0.01:
                r["scale_mismatch"] = True
                print(f"WARNING: {scale} % run {i + 1} ran at dpr {r['dpr']}", flush=True)
            results.append(r)
            print(f"{name} {scale} % run {i + 1}{' reduced' if reduced else ''}: dpr {r.get('dpr')} · "
                  f"{len(r.get('moments') or {})} moments · {r['wall_s']} s", flush=True)
    out = {"bench": name, "scales": scales, "runs_per_scale": runs, "reduced": reduced, "system_scale": system_scale(),
           "meta": meta or {}, "results": results}
    md = markdown(out)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        with open(os.path.splitext(out_path)[0] + ".md", "w", encoding="utf-8") as f:
            f.write(md)
        print("written:", out_path, flush=True)
    print(md, flush=True)
    return out


def _causes(c):
    return " ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])) if c else "–"


def markdown(out):
    """One table per run: a line per moment."""
    lines = [f"# {out['bench']}{' (reduced)' if out.get('reduced') else ''}", "",
             f"Bar here: frame p95 <= {BAR['frame_p95']} ms; a frame over {BAR['slow']} ms needs a cause; the steps' "
             f"typical worst <= {BAR['step_worst']} ms; {BAR['wakes_after']} clock wake-ups once still.", ""]
    for r in out["results"]:
        lines += [f"## {r.get('scale')} % · run {r.get('run')} · dpr {r.get('dpr')}"
                  + (f" · ERROR {r['error']}" if r.get("error") else ""), "",
                  "| moment | reps | frames | p95 | max | windows | slow > 6.4 by cause | step typ. worst | slowest | "
                  ">4 ms | wakes after |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, m in (r.get("moments") or {}).items():
            win = " ".join(f"{k} {v}" for k, v in m.get("windows", {}).items()) or "–"
            lines.append(f"| {name} | {m['reps']} | {m['frames_n']} | {m['frames_p95_ms']} | {m['frames_max_ms']} | "
                         f"{win} | {m['slow_n']}: {_causes(m['slow_causes'])} | {m['step_worst_p95_ms']} | "
                         f"{m['step_slowest_ms']} | {m['steps_over_4ms']} | {m['wakes_after']} |")
        extra = r.get("extra")
        if extra:
            lines += ["", "```", json.dumps(extra)[:1500], "```"]
        lines.append("")
    return "\n".join(lines)


def add_arguments(ap, default_scales="150"):
    ap.add_argument("--scales", default=default_scales,
                    help="comma-separated, each its own child at true scale (e.g. 100,125,150,175,200,250)")
    ap.add_argument("--reduced", action="store_true", help="app_motion = reduced in the bench's own temp settings")
    ap.add_argument("--json", "--out", dest="out", default=None, help="the JSON (a .md table is written beside)")
