"""The first screens' budgets (W2.2 row 5; the window's spec RUNBOOK W2.2: "the list draws at 20,000 within the frame
budget"; BRIEF's budgets: first frame ≤ 1 s, any GUI-thread step ≤ 4 ms, a frame ≤ 8 ms at p95 and never over 16 ms,
idle ≤ ~250 MB).

    python tests/qt/bench_scroll.py --files 20000 [--runs 3] [--current-share 0.9] [--scale 150]

Not collected by pytest (no `test_` prefix). A timed run: start it through `locks/with-lock.sh timed …` from the copy.

The parent builds the synthetic seed and saves it; each run is a child process on Windows' own platform, shown without
taking the keyboard, in a temp `SURASURA_TEST_ROOT` (nothing of the developer's read or written). The child's store is
the stand-in, loaded on the reader's thread (as the real store is opened there). The HUD (`app/qt/hud.py`) watches every
GUI-thread stretch and frame after the first paint while the child:
  1. waits for the live rows (the first frame may come first, from nothing or the cache);
  2. scrolls Current: 5 s at 60 Hz, 40 px a step, down then up — unbroken; with another program writing (a watched mark
     every 0.3 s, from a process of its own); resting 1 s at its turn; then as a wheel turns, notch by notch (bursts of
     3–5 notches 60 ms apart, a 0.4 s pause between: review B-8);
  3. opens and closes 20 rows: the pointer rests on each (0.3 s), it opens, then closes;
  4. switches tabs ten times;
  5. takes an outside commit (a hato drop at the top of Current) and repaints it;
  6. sits idle for 5 s; then reports memory and quits.
Printed: per run and as the median of the runs.
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
    scale / 100 / system (as `capture.py` and `bench_motion.py` do). Until 2026-10-08 this bench set scale / 100 alone:
    bench 9's "100 / 150 / 250 %" ran at 150 / 225 / 375 % on this 150 % desktop."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def run_child(seed_path, out_path, scale, root):
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    env["SURASURA_TEST_ROOT"] = root
    if scale:
        env["QT_SCALE_FACTOR"] = f"{scale / 100 / system_scale():.6f}"
    else:
        env.pop("QT_SCALE_FACTOR", None)
    env["SURASURA_FREEZE_MOTION"] = "1"
    env["SURASURA_READER_GC_FREEZE"] = "1" if GC_FREEZE else "0"
    cmd = [sys.executable, os.path.abspath(__file__), "--child", seed_path, "--out", out_path]
    subprocess.run(cmd, env=env, cwd=ROOT, timeout=300, check=False)
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


def main_parent(a):
    global GC_FREEZE
    GC_FREEZE = a.gc_freeze
    work = tempfile.mkdtemp(prefix="surasura-bench-scroll-")
    seed_path = os.path.join(work, "seed.pkl")
    t = time.perf_counter()
    files = save_seed(a.files, a.current_share, seed_path, a.language)
    print(f"seed: {files} files ({(time.perf_counter() - t):.1f} s)", flush=True)
    results = []
    for i in range(a.runs):
        root = tempfile.mkdtemp(prefix="surasura-bench-root-", dir=work)
        r = run_child(seed_path, os.path.join(work, f"run{i}.json"), a.scale, root)
        results.append(r)
        hud = r.get("hud", {})
        print(f"run {i + 1}: first frame {r.get('first_frame_ms')} ms · rows live {r.get('rows_live_ms')} ms · "
              f"steps max {hud.get('steps', {}).get('max_ms')} (>4 ms: {hud.get('steps', {}).get('over_4ms')}) · "
              f"frames p95 {hud.get('frames', {}).get('p95_ms')} max {hud.get('frames', {}).get('max_ms')} · "
              f"late max {hud.get('late', {}).get('max_ms')} · mem {r.get('memory')}", flush=True)
    out = {"files": files, "current_share": a.current_share, "scale": a.scale, "runs": results,
           "median": summary(results)}
    target = a.out or os.path.join(ROOT, ".w22", "out", f"bench_scroll_{a.files}"
                                   f"{'_cur' if a.current_share else ''}.json")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("median:", json.dumps(out["median"]), flush=True)
    print("written:", target)


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


def main_child(a):
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication

    from app.qt import hud as hud_module, shell
    from app.services import library_reader

    app = QApplication([sys.argv[0]])
    shell.prepare_process()
    opener = _LazyOpener(a.child)
    reader = library_reader.LibraryReader(opener, numbers=lambda: (1, opener.numbers_table),
                                          mining=lambda: opener.mining_ids,
                                          freeze_gc=os.environ.get("SURASURA_READER_GC_FREEZE") == "1")
    services = shell.Services(library=reader)
    window = shell.open_window(app, services)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    hud = hud_module.Hud(window, overlay=False).start()
    page = window.page_widgets["current"]
    lst = page.list
    result = {"first_frame_ms": None, "rows_live_ms": None}
    phases = {}                                          # name -> [start, end] (perf_counter)

    def mark(name, end=False):
        phases.setdefault(name, [None, None])[1 if end else 0] = time.perf_counter()

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
    real_show = window.show_library

    def show_library(view):
        with hud.span("show-library"):
            real_show(view)
        if result["rows_live_ms"] is None and not view.loading and view.rows:
            result["rows_live_ms"] = round(hud_module._process_age_ms() or 0, 1)
            result["rows"] = len(view.rows)
            QTimer.singleShot(400, phase_scroll)
    window.library_bridge.library_changed.disconnect(window.show_library)
    window.library_bridge.library_changed.connect(show_library)

    def first_frame():
        result["first_frame_ms"] = round(hud_module._process_age_ms() or 0, 1)
        hud.ignore_before = time.perf_counter()
    window.first_frame.connect(first_frame)

    # the phases ----------------------------------------------------------------------------------------------------- #
    def phase_scroll(writes=False, rest=False):
        # three passes: unbroken; another program writing; and one that rests 1 s at its turn, as a person does (the
        # rows past the screen are painted ahead then)
        name = "scroll-rest" if rest else "scroll-writes" if writes else "scroll"
        mark(name)
        bar = lst.verticalScrollBar()
        bar.setValue(0)
        # the second pass: another program writes while the person scrolls (review A-17) — a watched mark every 300 ms,
        # so the reader rebuilds the view on its thread while this one paints
        writer = None
        if writes:
            import multiprocessing
            ids = [r["id"] for r in opener.library.items() if r["tier"] == "now"][:50]
            mine, theirs = multiprocessing.Pipe(duplex=False)
            writer = multiprocessing.Process(target=write_watched, args=(theirs, ids), name="scroll-writer",
                                             daemon=True)
            writer.start()
            opener.inbox = mine
            result["scroll_commits_from"] = opener.library._meta["state_version"]
        state = {"n": 0, "dir": 1}
        timer = QTimer(window)
        timer.setTimerType(Qt.TimerType.PreciseTimer)

        def step():
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
                    QTimer.singleShot(1000, lambda: timer.start(16))
            if state["n"] >= 300:
                timer.stop()
                if writer is not None:
                    writer.terminate()
                    opener.inbox = None
                    result["scroll_commits"] = opener.library._meta["state_version"] - result["scroll_commits_from"]
                mark(name, end=True)
                QTimer.singleShot(300, phase_notches if rest else (lambda: phase_scroll(rest=True)) if writes else
                                  (lambda: phase_scroll(writes=True)))
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
        for when, direction in plan:
            def notch(direction=direction):
                with hud.span("scroll-step"):
                    bar.setValue(max(0, min(bar.maximum(), bar.value() + direction * 3 * bar.singleStep())))
            QTimer.singleShot(when, notch)
        QTimer.singleShot(at + 100, lambda: mark("scroll-notches", end=True))
        QTimer.singleShot(at + 400, phase_open)

    def phase_open():
        # the pointer comes to rest on a row (0.3 s: its hover is drawn, its episodes painted ahead), the row opens,
        # then closes; the next row
        from PyQt6.QtCore import QEvent, QPointF
        from PyQt6.QtGui import QHoverEvent, QMouseEvent
        mark("open")
        lst.verticalScrollBar().setValue(0)
        n = min(20, lst.model().rowCount())
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
        for i in range(n):
            t = 600 * i
            QTimer.singleShot(t, lambda i=i: hover(i))
            for dt in (300, 420):
                def toggle(i=i):
                    with hud.span("toggle"):
                        lst.toggle(lst.model().index(i, 0))
                QTimer.singleShot(t + dt, toggle)
        QTimer.singleShot(600 * n + 200, lambda: mark("open", end=True))
        QTimer.singleShot(600 * n + 300, phase_tabs)

    def phase_tabs():
        mark("tabs")
        names = ["finished", "needs", "current", "finished", "current", "finished", "current", "finished",
                 "current", "current"]
        for i, name in enumerate(names):
            def switch(name=name):
                with hud.span("tab-switch"):
                    window.show_tab(name)
            QTimer.singleShot(150 * i, switch)
        QTimer.singleShot(150 * len(names) + 200, lambda: mark("tabs", end=True))
        QTimer.singleShot(150 * len(names) + 300, phase_outside)

    def phase_outside():
        # another program's commit (a hato drop): it lands between two of the reader's polls, as a real store's would
        mark("outside")
        lib = opener.library
        items = lib.items()
        first = min((r for r in items if r["tier"] == "now"), key=lambda r: r["ord"])
        new_id = max(r["id"] for r in items) + 1
        result["outside_at"] = time.perf_counter()
        opener.pending.append({"items": [dict(first, id=new_id, ord=first["ord"] - 512, piece_id=10 ** 9,
                                              rel_path="HighPriority/Hato/outside - 01.srt",
                                              title="outside - 01.srt")], "order": True})

        def landed():
            entries = lst.model().entries
            if entries and getattr(entries[0][1], "key", None) == f"p{10 ** 9}":
                result["outside_ms"] = round((time.perf_counter() - result["outside_at"]) * 1000, 1)
                QTimer.singleShot(300, lambda: (mark("outside", end=True), mark("idle")))
                QTimer.singleShot(5000, finish)
            else:
                QTimer.singleShot(10, landed)
        landed()

    def finish():
        mark("idle", end=True)
        result["memory"] = hud_module._memory_mb()
        result["hud"] = hud.report()
        per = {}
        for name, (t0, t1) in phases.items():
            if t0 is None or t1 is None:
                continue
            over = [ms for ms, at in hud.over if t0 <= at <= t1]
            steps = [(ms, at) for ms, at in hud.over if t0 <= at <= t1]
            during = [ms for ms, at in steps                # a GUI step that ended inside a reader step (or 1 ms after)
                      if any(r0 <= at <= r0 + rms / 1000 + 0.001 for _n, r0, rms in reader_log)]
            per[name] = {"s": round(t1 - t0, 2), "over_4ms": len(over), "max_ms": max(over, default=0.0),
                         "gc": [(g, ms, th) for g, ms, th, at in gc_log if t0 <= at <= t1 and ms > 2],
                         "over_during_reader": len(during),
                         "reader": [(n, round(ms, 2)) for n, r0, ms in reader_log if t0 <= r0 <= t1 and ms > 2][:30]}
        result["phases"] = per
        result["gc_over_2ms"] = [(g, ms, th) for g, ms, th, _at in gc_log if ms > 2]
        result["gc_count"] = len(gc_log)
        result["paints"] = lst.delegate.paints if hasattr(lst.delegate, "paints") else None
        result["dpr"] = lst.viewport().devicePixelRatioF()
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f)
        app.quit()

    QTimer.singleShot(120000, finish)                  # never longer than 2 min
    window.show_first()
    try:
        app.exec()
    finally:
        services.shutdown(1.0)


def write_watched(conn, ids):
    """The scroll pass's other program, in a process of its own: a watched mark every 0.3 s (review A-17)."""
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
    ap.add_argument("--scale", type=int, default=0, help="the screen's scaling in % (0: Windows' own)")
    ap.add_argument("--language", default="ja")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gc-freeze", action="store_true", help="the reader freezes the collector after each view (A/B)")
    ap.add_argument("--child", default=None)
    a = ap.parse_args()
    if a.child:
        main_child(a)
    else:
        main_parent(a)


if __name__ == "__main__":
    main()
