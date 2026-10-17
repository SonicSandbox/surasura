"""The first screens' budgets (W2.2 row 5; the window's spec RUNBOOK W2.2: "the list draws at 20,000 within the frame
budget"; BRIEF's budgets: first frame ≤ 1 s, any GUI-thread step ≤ 4 ms, a frame ≤ 8 ms at p95 and never over 16 ms,
idle ≤ ~250 MB).

    python tests/qt/bench_scroll.py --files 20000 [--runs 3] [--current-share 0.9] [--scales 100,125,150,175,200,250]
                                    [--reduced] [--freeze-motion] [--outside 10] [--json OUT.json]

Not collected by pytest (no `test_` prefix). A timed run: start it through `locks/with-lock.sh timed …` from the copy.

The parent builds the synthetic seed and saves it; each run is a child process on Windows' own platform, shown without
taking the keyboard, in a temp `SURASURA_TEST_ROOT` (nothing of the developer's read or written). The child's store is
the stand-in, loaded on the reader's thread (as the real store is opened there). The HUD (`app/qt/hud.py`) watches every
GUI-thread stretch and frame after the first paint while the child:
  1. waits for the live rows (the first frame may come first, from nothing or the cache);
  2. scrolls Current: 5 s at 60 Hz, 40 px a step, down then up — unbroken; with another program writing (a watched mark
     every 0.3 s, from a process of its own); resting 1 s at its turn; then as a wheel turns, notch by notch (bursts of
     3–5 notches 60 ms apart, a 0.4 s pause between: review B-8);
  3. opens and closes rows on a screen it hasn't opened before (the pointer rests on each 0.3 s, it opens, then
     closes: "open-first"), the same rows again ("open-again"), then the rows of a third screen opened at once, with
     no rest (a quick click, a key: "open-quick") — review C-9;
  4. switches tabs ten times, with Current and Finished each scrolled a few screens down (review C-1);
  5. takes an outside commit (a hato drop at the top of Current) and repaints it;
  6. sits idle for 5 s; then reports memory and quits.
Printed: per run and as the median of the runs.

**M4.1 row 2:** each pass is a moment, its repetitions marked (`bench_moments.Moments`): a scroll pass's 30-step
stretches, a notch burst, each row opened and closed, each tab switch, each of `--outside` outside commits (10), and
the idle; per moment every window's frames p95 / max, the slow frames with their causes, the steps' typical worst and
slowest, the clock's wake-ups once still — a JSON and a markdown table (`--json`), each `--scales` value its own child
at true scale in a fresh test root with its own APPDATA / LOCALAPPDATA. Motion runs since M4.1 (a tab's vein, a row's
hover lift, as a person sees them); `--freeze-motion` freezes it as W2.2 and W3.1a's timed-1 ran; `--reduced` sets
`app_motion` = reduced in the run's own settings. **The writer process** of *scroll-writes* (another program writing)
is started as the child starts, before the window opens, and waits for its ids — never spawned on the window's thread
inside a measured pass (W3.1a timed-1 #4: one 25–50 ms step a run there).
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.qt import bench_moments                                    # noqa: E402


# --- the parent ------------------------------------------------------------------------------------------------------ #
def save_seed(files, share, path, language="ja"):
    from tests.fixtures import window_seed
    seed = window_seed.build(files=files, language=language, current_share=share)
    lib = seed.library
    data = {"items": seed.items, "works": seed.works, "cards": {str(k): v for k, v in lib._cards.items()},
            "numbers": {str(k): v for k, v in seed.numbers()[1].items()}, "mining": list(seed.mining()),
            "meta": {k: lib._meta[k] for k in ("mine_line", "soon_line", "arrivals_on")}, "language": language}
    import pickle
    with open(path, "wb") as f:                          # pickle: the child loads it fast (a store opens fast)
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    return seed.files


def system_scale():
    """This desktop's own scaling (1.5 at 150 %): `QT_SCALE_FACTOR` multiplies it, so a run at `--scale` % sets
    scale / 100 / system (as `capture.py` does, and M2.1's `bench_motion.py`). Until 2026-10-08 this bench set
    scale / 100 alone: bench 9's "100 / 150 / 250 %" ran at 150 / 225 / 375 % on this 150 % desktop."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def run_child(seed_path, out_path, scale, root, env=None):
    env = dict(os.environ) if env is None else env
    env.pop("QT_QPA_PLATFORM", None)
    env["SURASURA_TEST_ROOT"] = root
    if scale:
        env["QT_SCALE_FACTOR"] = f"{scale / 100 / system_scale():.6f}"
    else:
        env.pop("QT_SCALE_FACTOR", None)
    if FREEZE:
        env["SURASURA_FREEZE_MOTION"] = "1"
    else:
        env.pop("SURASURA_FREEZE_MOTION", None)
    env["SURASURA_BENCH_OUTSIDE"] = str(OUTSIDE)
    env["SURASURA_READER_GC_FREEZE"] = "1" if GC_FREEZE else "0"
    env["SURASURA_ROW_PIXMAPS"] = "1" if PIXMAPS else "0"
    if SWITCH is not None:
        env["SURASURA_BENCH_SWITCH_S"] = str(SWITCH)
    cmd = [sys.executable, os.path.abspath(__file__), "--child", seed_path, "--out", out_path]
    subprocess.run(cmd, env=env, cwd=ROOT, timeout=600, check=False)
    if not os.path.exists(out_path):
        return {"error": "no result"}
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def summary(results):
    def med(path):
        vals = []
        for r in results:
            v = r
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            if isinstance(v, (int, float)):
                vals.append(v)
        return round(statistics.median(vals), 2) if vals else None
    keys = {
        "first_frame_ms": ("first_frame_ms",), "rows_live_ms": ("rows_live_ms",),
        "steps_max_ms": ("hud", "steps", "max_ms"), "steps_p95_ms": ("hud", "steps", "p95_ms"),
        "steps_over_4ms": ("hud", "steps", "over_4ms"), "frames_p95_ms": ("hud", "frames", "p95_ms"),
        "frames_max_ms": ("hud", "frames", "max_ms"), "late_max_ms": ("hud", "late", "max_ms"),
        "late_over_4ms": ("hud", "late", "over_4ms"), "private_mb": ("memory", "private_mb"),
        "working_set_mb": ("memory", "working_set_mb"), "rows": ("rows",),
    }
    return {k: med(p) for k, p in keys.items()}


GC_FREEZE = False
PIXMAPS = True
SWITCH = None
FREEZE = False
OUTSIDE = 10


def main_parent(a):
    global GC_FREEZE, PIXMAPS, SWITCH, FREEZE, OUTSIDE
    GC_FREEZE = a.gc_freeze
    SWITCH = a.switch
    PIXMAPS = a.pixmaps == "on"
    FREEZE = a.freeze_motion
    OUTSIDE = a.outside
    work = tempfile.mkdtemp(prefix="surasura-bench-scroll-seed-")
    seed_path = os.path.join(work, "seed.pkl")
    t = time.perf_counter()
    files = save_seed(a.files, a.current_share, seed_path, a.language)
    print(f"seed: {files} files ({(time.perf_counter() - t):.1f} s); this desktop's own scale {system_scale()} "
          f"(1.0 when it couldn't be read: each run's `dpr` says what it ran at)", flush=True)

    def one_run(scale, root, env, i):
        r = run_child(seed_path, os.path.join(os.path.dirname(root), "result.json"), scale, root, env)
        hud = r.get("hud", {})
        print(f"run {i + 1}: first frame {r.get('first_frame_ms')} ms · rows live {r.get('rows_live_ms')} ms · "
              f"steps max {hud.get('steps', {}).get('max_ms')} (>4 ms: {hud.get('steps', {}).get('over_4ms')}) · "
              f"frames p95 {hud.get('frames', {}).get('p95_ms')} max {hud.get('frames', {}).get('max_ms')} · "
              f"late max {hud.get('late', {}).get('max_ms')} · mem {r.get('memory')} · dpr {r.get('dpr')}", flush=True)
        r["extra"] = summary([r])
        return r
    target = a.out or os.path.join(work, f"bench_scroll_{a.files}{'_cur' if a.current_share else ''}.json")
    out = bench_moments.scaled_runs("bench_scroll", a.scales_list, a.runs, a.reduced, one_run, target,
                                    meta={"files": files, "current_share": a.current_share, "pixmaps": a.pixmaps,
                                          "freeze_motion": FREEZE, "outside": OUTSIDE})
    by_scale = {}
    for r in out["results"]:
        by_scale.setdefault(r["scale"], []).append(r)
    for scale, rs in by_scale.items():
        print(f"median {scale} %:", json.dumps(summary(rs)), flush=True)


# --- the child ------------------------------------------------------------------------------------------------------- #
class _LazyOpener:
    """The stand-in's opener, its library loaded from the saved seed on the reader's thread (the real store is opened
    there too), so the window's start pays only what it would."""

    closes_handles = False

    def __init__(self, path):
        self.path = path
        self.mode, self.reason = "json", "not checked"
        self._opener = None
        self.library = None
        self.numbers_table = {}
        self.mining_ids = ()
        self.inbox = None                                # another process's commits (a Pipe), applied as it polls
        self.pending = []                                # commits from this process, applied the same way

    def _drain(self):
        """Another program's commits land between two polls, as a real store's would (the writer's own work — building
        them, its collector — runs in its process; here only the store's side of a commit runs, on the reader's
        thread)."""
        while self.pending:
            self.library.commit(**self.pending.pop(0))
        conn = self.inbox
        try:
            while conn is not None and conn.poll():
                self.library.commit(**conn.recv())
        except (EOFError, OSError):                      # the writer has stopped: its end of the pipe is closed
            self.inbox = None

    def _load(self):
        if self._opener is None:
            import pickle
            from tests.fixtures import standin_store
            with open(self.path, "rb") as f:
                data = pickle.load(f)
            self.library = standin_store.StandinLibrary(
                data["items"], data["works"], meta=data["meta"], cards={int(k): v for k, v in data["cards"].items()})
            self.numbers_table = {int(k): tuple(v) for k, v in data["numbers"].items()}
            self.mining_ids = tuple(data["mining"])
            self._opener = standin_store.StandinOpener(self.library)
        return self._opener

    def check(self):
        mode = self._load().check()
        self.mode, self.reason = mode, self._opener.reason
        return mode

    def handle(self):
        h = self._load().handle()
        if h is not None and not getattr(h, "drains", False):
            real = h.data_version

            def data_version():
                self._drain()
                return real()
            h.data_version, h.drains = data_version, True
        return h

    def fallback_handle(self):
        return self._load().fallback_handle()


def _timer_resolution_ms():
    """Windows' timer resolution now (a 1 ms wait lasts up to this long), or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        lo, hi, now = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        ctypes.windll.ntdll.NtQueryTimerResolution(ctypes.byref(lo), ctypes.byref(hi), ctypes.byref(now))
        return now.value / 10000
    except Exception:
        return None


def main_child(a):
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication

    from app.qt import hud as hud_module, shell
    from app.services import library_reader

    # the scroll-writes pass's other program: started now, before the window opens, waiting for its ids (W3.1a
    # timed-1 #4: spawned on the window's thread inside the pass, it cost one 25-50 ms step a run)
    import multiprocessing
    mine, theirs = multiprocessing.Pipe(duplex=False)
    go_r, go_w = multiprocessing.Pipe(duplex=False)
    writer = multiprocessing.Process(target=write_watched, args=(theirs, go_r), name="scroll-writer", daemon=True)
    writer.start()
    app = QApplication([sys.argv[0]])
    shell.prepare_process()
    if os.environ.get("SURASURA_BENCH_SWITCH_S"):           # the A/B of Python's lock hand-over (speed round 5)
        sys.setswitchinterval(float(os.environ["SURASURA_BENCH_SWITCH_S"]))
    opener = _LazyOpener(a.child)
    reader = library_reader.LibraryReader(opener, numbers=lambda: (1, opener.numbers_table),
                                          mining=lambda: opener.mining_ids,
                                          freeze_gc=os.environ.get("SURASURA_READER_GC_FREEZE") == "1")
    services = shell.Services(library=reader)
    # the views through the class, before the window opens (as bench_drag): the window's connection is made as it
    # opens, and a small library's first view can be on its way before any connection made after (M4.1 P2: at 2,000
    # files the rows never went live)
    real_show_cls = shell.ShellWindow.show_library
    view_hook = []

    def show_library_cls(self_, view):
        if view_hook:
            view_hook[0](view)
        else:
            real_show_cls(self_, view)
    shell.ShellWindow.show_library = show_library_cls
    window = shell.open_window(app, services)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    bench_moments.apply_reduced()
    hud = hud_module.Hud(window, overlay=False).start()
    moments = bench_moments.Moments(hud)
    page = window.page_widgets["current"]
    lst = page.list
    result = {"first_frame_ms": None, "rows_live_ms": None}
    phases = {}                                          # name -> [start, end] (perf_counter)

    counts = {}                                          # name -> [(paints, renders, warmed) at start, at end]

    def mark(name, end=False):
        phases.setdefault(name, [None, None])[1 if end else 0] = time.perf_counter()
        d = lst.delegate                                 # what Current drew in the phase: blits, afresh, ahead
        counts.setdefault(name, [None, None])[1 if end else 0] = (d.paints, d.renders, d.warmed)

    # Python's collector: every collection, its generation, its length and the thread it ran on (a full one on a big
    # heap holds Python's lock — every thread waits — so it shows here before anywhere else)
    import gc
    import threading
    gc_log, gc_start = [], {}

    def on_gc(phase_, info):
        tid = threading.get_ident()
        if phase_ == "start":
            gc_start[tid] = time.perf_counter()
        elif tid in gc_start:
            t0 = gc_start.pop(tid)
            gc_log.append((info["generation"], round((time.perf_counter() - t0) * 1000, 2),
                           threading.current_thread().name, t0))
    gc.callbacks.append(on_gc)
    # the reader's own steps (on its thread): when a GUI step runs long while one of them runs, Python's lock is the
    # likely cause (Kura's L3.1 verifier: a worker's long read stalls the window through it)
    reader_log = []

    def timed_step(name, fn):
        def run(*args, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kw)
            finally:
                reader_log.append((name, t0, (time.perf_counter() - t0) * 1000))
        return run
    for name in ("_merge", "_card_counts", "_build", "_write_cache", "_sorted_tiers"):
        if hasattr(reader, name):
            setattr(reader, name, timed_step(name, getattr(reader, name)))
    from app.qt import rows as rows_module
    real_cover = rows_module.cover

    def cover(*args, **kw):
        with hud.span("cover"):
            return real_cover(*args, **kw)
    rows_module.cover = cover
    delegate_cls = type(lst.delegate)
    real_paint = delegate_cls.paint

    def paint(self, p, option, index):                  # on the class: a C++ virtual looks there, not the instance
        with hud.span("paint-row"):
            real_paint(self, p, option, index)
    delegate_cls.paint = paint
    def show_library(view):
        with hud.span("show-library"):
            real_show_cls(window, view)
        if result["rows_live_ms"] is None and not view.loading and view.rows:
            result["rows_live_ms"] = round(hud_module._process_age_ms() or 0, 1)
            result["rows"] = len(view.rows)
            QTimer.singleShot(400, phase_scroll)
    # each list's refresh: when, how long, how ("same" / "relayout" / "reset") and how many rows changed — set beside
    # the long steps of the phases that refresh (W2.2 round 4: what an arrival's and a writer's long steps hold)
    entries_log = []
    real_set_entries = rows_module.RowsView.set_entries

    def set_entries(self_, entries):
        t0 = time.perf_counter()
        how = real_set_entries(self_, entries)
        entries_log.append((t0, (time.perf_counter() - t0) * 1000, how, len(self_.model().changed),
                            self_.accessibleName()))
        return how
    rows_module.RowsView.set_entries = set_entries
    view_hook.append(show_library)

    def catch_up():                                      # a view shown before the hook: its rows live already
        v = page.view_model
        if result["rows_live_ms"] is None and v is not None and not v.loading and v.rows:
            show_library(v)
    QTimer.singleShot(3000, catch_up)

    def first_frame():
        result["first_frame_ms"] = round(hud_module._process_age_ms() or 0, 1)
        hud.ignore_before = time.perf_counter()
    window.first_frame.connect(first_frame)

    # the phases ----------------------------------------------------------------------------------------------------- #
    def phase_scroll(writes=False, rest=False):
        # three passes: unbroken; another program writing; and one that rests 1 s at its turn, as a person does (the
        # rows past the screen are painted ahead then)
        name = "scroll-rest" if rest else "scroll-writes" if writes else "scroll"
        bar = lst.verticalScrollBar()
        bar.setValue(0)
        # the second pass: another program writes while the person scrolls (review A-17) — a watched mark every 300 ms,
        # so the reader rebuilds the view on its thread while this one paints; its process started with the child
        if writes:
            ids = [r["id"] for r in opener.library.items() if r["tier"] == "now"][:50]
            opener.inbox = mine
            go_w.send(ids)                               # (a pipe write: the writer starts its marks)
            result["scroll_commits_from"] = opener.library._meta["state_version"]
        mark(name)
        state = {"n": 0, "dir": 1}
        timer = QTimer(window)
        timer.setTimerType(Qt.TimerType.PreciseTimer)

        def step():
            if state["n"] % 30 == 0:                     # a repetition: 30 steps (half a second)
                moments.begin(name)
            with hud.span("scroll-step"):
                v = bar.value() + state["dir"] * 40
                if v >= bar.maximum():
                    state["dir"] = -1
                bar.setValue(max(0, min(bar.maximum(), v)))
            state["n"] += 1
            if state["n"] == 150:
                state["dir"] = -1
                if rest:
                    timer.stop()
                    moments.end()
                    QTimer.singleShot(1000, lambda: timer.start(16))
            if state["n"] >= 300:
                timer.stop()
                if writes:
                    writer.terminate()
                    opener.inbox = None
                    result["scroll_commits"] = opener.library._meta["state_version"] - result["scroll_commits_from"]
                mark(name, end=True)
                nxt = phase_notches if rest else (lambda: phase_scroll(rest=True)) if writes else \
                    (lambda: phase_scroll(writes=True))
                moments.still(name, lambda: QTimer.singleShot(300, nxt))
        timer.timeout.connect(step)
        timer.start(16)

    def phase_notches():
        # a wheel turned by a person (review B-8): bursts of 3–5 notches 60 ms apart (a notch = 3 single steps, as
        # QAbstractScrollArea scrolls one), a 0.4 s pause between — down for ~6 s, then up for ~6 s
        import random
        mark("scroll-notches")
        bar = lst.verticalScrollBar()
        bar.setValue(0)
        rng = random.Random(11)
        at, plan = 0, []
        for direction in (1, -1):
            end = at + 6000
            while at < end:
                for _ in range(rng.randint(3, 5)):
                    plan.append((at, direction))
                    at += 60
                at += 400
        last = None
        for when, direction in plan:
            first = last is None or when - last > 60     # a burst's first notch: a repetition
            last = when

            def notch(direction=direction, first=first):
                if first:
                    moments.begin("scroll-notches")
                with hud.span("scroll-step"):
                    bar.setValue(max(0, min(bar.maximum(), bar.value() + direction * 3 * bar.singleStep())))
            QTimer.singleShot(when, notch)
        QTimer.singleShot(at + 100, lambda: (mark("scroll-notches", end=True),
                                             moments.still("scroll-notches", lambda: QTimer.singleShot(200, phase_open))))

    def phase_open(stage="open-first"):
        # review C-9, three passes of the rows on one screen: "open-first" — a screen it hasn't opened before, the
        # pointer resting on each row (0.3 s: its hover drawn, its episodes painted ahead), the row opens, then closes;
        # "open-again" — the same rows again (their pixmaps kept); "open-quick" — a third screen's rows opened with no
        # rest (a quick click, Enter): the open draws its episodes afresh
        from PyQt6.QtCore import QEvent, QPointF
        from PyQt6.QtGui import QHoverEvent, QMouseEvent
        bar = lst.verticalScrollBar()
        vh = lst.viewport().height()
        if stage != "open-again":
            bar.setValue(min(bar.maximum(), vh * (2 if stage == "open-first" else 4)))
        for _ in range(3):
            QApplication.processEvents()
        mark(stage)
        shown = [i for i in range(lst.model().rowCount())    # the rows wholly on screen (a row below it is neither
                 if 0 <= lst.visualRect(lst.model().index(i, 0)).top() and   # hovered nor painted when it opens)
                 lst.visualRect(lst.model().index(i, 0)).bottom() <= vh]
        order = shown[:10]
        n = len(order)
        rest_ms, gap = (300, 600) if stage != "open-quick" else (30, 330)
        last = [QPointF(-1, -1)]

        def hover(i):
            rect = lst.visualRect(lst.model().index(i, 0))
            pos = QPointF(rect.left() + rect.width() * 0.4, rect.top() + 20)
            vp = lst.viewport()
            with hud.span("hover"):
                QApplication.sendEvent(vp, QHoverEvent(QEvent.Type.HoverMove, pos, QPointF(vp.mapToGlobal(pos)),
                                                       last[0]))
                QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, pos, QPointF(vp.mapToGlobal(pos)),
                                                       Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                                       Qt.KeyboardModifier.NoModifier))
            last[0] = pos
        for k, i in enumerate(order):
            t = gap * k
            QTimer.singleShot(t, lambda: moments.begin(stage))      # a repetition: one row hovered, opened, closed
            QTimer.singleShot(t, lambda i=i: hover(i))
            for dt in (rest_ms, rest_ms + 120):
                def toggle(i=i):
                    with hud.span("toggle"):
                        lst.toggle(lst.model().index(i, 0))
                QTimer.singleShot(t + dt, toggle)
        then = {"open-first": lambda: phase_open("open-again"), "open-again": lambda: phase_open("open-quick"),
                "open-quick": phase_tabs}[stage]
        QTimer.singleShot(gap * n + 200, lambda: (mark(stage, end=True), moments.still(stage, then)))

    def phase_tabs():
        # each list a few screens down first (review C-1: a hidden list kept its top, so a scrolled one's first switch
        # drew its whole screen); a second's rest lets the hidden lists paint their screens ahead
        fin_list = window.page_widgets["finished"].list
        for view_ in (lst, fin_list):
            vbar = view_.verticalScrollBar()
            vbar.setValue(min(vbar.maximum(), lst.viewport().height() * 3))
        QTimer.singleShot(1500, phase_tabs_go)

    def phase_tabs_go():
        mark("tabs")
        names = ["finished", "needs", "current", "finished", "current", "finished", "current", "finished",
                 "current", "current"]
        for i, name in enumerate(names):
            def switch(name=name):
                moments.begin("tabs")
                with hud.span("tab-switch"):
                    window.show_tab(name)
            QTimer.singleShot(150 * i, switch)
        QTimer.singleShot(150 * len(names) + 200, lambda: (mark("tabs", end=True),
                                                           moments.still("tabs", lambda: phase_outside())))

    outside_n = int(os.environ.get("SURASURA_BENCH_OUTSIDE", "10"))

    def phase_outside(k=0):
        # another program's commit (a hato drop): it lands between two of the reader's polls, as a real store's would;
        # `outside_n` of them, each its own piece at the top of Current
        if k == 0:
            mark("outside")
            lst.verticalScrollBar().setValue(0)
        moments.begin("outside")
        lib = opener.library
        items = lib.items()
        first = min((r for r in items if r["tier"] == "now"), key=lambda r: r["ord"])
        new_id = max(r["id"] for r in items) + 1
        piece = 10 ** 9 + k
        result["outside_at"] = time.perf_counter()
        opener.pending.append({"items": [dict(first, id=new_id, ord=first["ord"] - 512, piece_id=piece,
                                              rel_path=f"HighPriority/Hato/outside {k + 1} - 01.srt",
                                              title=f"outside {k + 1} - 01.srt")], "order": True})

        def landed():
            entries = lst.model().entries
            if entries and getattr(entries[0][1], "key", None) == f"p{piece}":
                result.setdefault("outside_ms_each", []).append(round((time.perf_counter() - result["outside_at"])
                                                                      * 1000, 1))
                result["outside_ms"] = result["outside_ms_each"][0]
                if k + 1 < outside_n:
                    QTimer.singleShot(300, lambda: phase_outside(k + 1))
                    return
                QTimer.singleShot(300, lambda: (mark("outside", end=True),
                                                moments.still("outside", lambda: (mark("idle"),
                                                                                  moments.begin("idle")))))
                QTimer.singleShot(5300, finish)
            else:
                QTimer.singleShot(10, landed)
        landed()

    def finish():
        mark("idle", end=True)
        moments.end()
        moments.wakes.setdefault("idle", "the idle itself")
        result["memory"] = hud_module._memory_mb()
        result["moments"] = moments.summary()
        result["hud"] = hud.report()
        per = {}
        for name, (t0, t1) in phases.items():
            if t0 is None or t1 is None:
                continue
            over = [ms for ms, at in hud.over if t0 <= at <= t1]
            steps = [(ms, at) for ms, at in hud.over if t0 <= at <= t1]
            during = [ms for ms, at in steps                # a GUI step that ended inside a reader step (or 1 ms after)
                      if any(r0 <= at <= r0 + rms / 1000 + 0.001 for _n, r0, rms in reader_log)]
            near = []                                    # the refreshes inside each long step (ended within it)
            for ms, at in sorted(steps, reverse=True)[:6]:
                near.append((round(ms, 1), [(how, round(sm, 2), n, nm[:8]) for e0, sm, how, n, nm in entries_log
                                            if at - ms / 1000 - 0.001 <= e0 <= at]))
            per[name] = {"s": round(t1 - t0, 2), "over_4ms": len(over), "max_ms": max(over, default=0.0),
                         "longest": near,
                         "gc": [(g, ms, th) for g, ms, th, at in gc_log if t0 <= at <= t1 and ms > 2],
                         "over_during_reader": len(during),
                         "reader": [(n, round(ms, 2)) for n, r0, ms in reader_log if t0 <= r0 <= t1 and ms > 2][:30]}
            c0, c1 = counts.get(name, (None, None))
            if c0 and c1:
                per[name]["painted_rendered_warmed"] = [b - a for a, b in zip(c0, c1)]
        result["phases"] = per
        result["gc_over_2ms"] = [(g, ms, th) for g, ms, th, _at in gc_log if ms > 2]
        result["gc_count"] = len(gc_log)
        result["paints"] = lst.delegate.paints if hasattr(lst.delegate, "paints") else None
        result["dpr"] = lst.viewport().devicePixelRatioF()
        result["switch_s"] = sys.getswitchinterval()
        result["timer_resolution_ms"] = _timer_resolution_ms()
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f)
        app.quit()

    QTimer.singleShot(150000 + 2000 * outside_n, finish)   # never longer than this
    window.show_first()
    try:
        app.exec()
    finally:
        services.shutdown(1.0)
        if writer.is_alive():
            writer.terminate()


def write_watched(conn, go):
    """The scroll pass's other program, in a process of its own: started with the child, it waits for the items it
    marks (`go`: they come as the pass begins), then a watched mark every 0.3 s (review A-17)."""
    try:
        ids = go.recv()
    except (EOFError, OSError):
        return
    k = 0
    while True:
        time.sleep(0.3)
        conn.send({"items": [{"id": ids[k % len(ids)], "watched": k % 2}]})
        k += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=20000)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--current-share", type=float, default=None)
    ap.add_argument("--scale", type=int, default=None, help="one scale in % (the old flag: --scales takes a list)")
    ap.add_argument("--language", default="ja")
    bench_moments.add_arguments(ap)
    ap.add_argument("--freeze-motion", action="store_true", help="motion frozen, as W2.2 and W3.1a's timed-1 ran")
    ap.add_argument("--outside", type=int, default=10, help="outside commits (hato drops), each a repetition")
    ap.add_argument("--gc-freeze", action="store_true", help="the reader freezes the collector after each view (A/B)")
    ap.add_argument("--pixmaps", choices=("on", "off"), default="on",
                    help="rows and episodes painted once into pixmaps (on) or drawn on every paint (off): review IK-30")
    ap.add_argument("--switch", type=float, default=None,
                    help="Python's switch interval in s for the window process (A/B; default: the shell's own)")
    ap.add_argument("--child", default=None)
    a = ap.parse_args()
    if a.child:
        main_child(a)
    else:
        a.scales_list = [a.scale] if a.scale is not None else bench_moments.parse_scales(a.scales)
        main_parent(a)


if __name__ == "__main__":
    main()
