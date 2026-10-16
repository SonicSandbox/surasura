"""The drag's budgets on this machine (W3.1a; ORDER W3.1a: a frame <= 8 ms at p95 and never over 16 ms, no GUI-thread
step over 4 ms, drop -> numbers <= 50 ms; RP-6).

    python tests/qt/bench_drag.py [--files 20000] [--runs 2] [--cycles 4] [--scale 150] [--out OUT.json]

Not collected by pytest (no `test_` prefix). A timed run: start it through `locks/with-lock.sh timed …` from the copy.

The parent builds the window's synthetic seed (`bench_scroll.save_seed`) and a Generate-shaped plan for it; each run is
a child process on Windows' own platform, shown without taking the keyboard, in a temp `SURASURA_TEST_ROOT`, at the
TRUE `--scale` % (`QT_SCALE_FACTOR` = scale / this desktop's own scaling; each run records its `dpr`). Motion runs (not
frozen). The child's store is the stand-in, with the real `moves.Numbers` over the plan and a writer that, like the
real one, works out the numbers on its own thread before it writes (into the stand-in). The HUD watches every
GUI-thread step and frame after the first paint while, `--cycles` times, a drag goes through the window's own mouse
path (the events `tests/qt/test_drag.py` sends):
  1. pick-up: a press on a row's title, then the 6 px that lift it (the ghost made and shown), the hand drifting;
  2. gap slide: the hand moves down ~7 rows at 60 Hz, the rows part under it;
  3. auto-scroll: the hand rests at the list's bottom edge 1.5 s (the list scrolls under it), then comes back up;
  4. drop: the release over a row; then the drop's glide home and the numbers (the moved row's *N new* in the window).
Printed per run and as the median of the runs, each phase on its own.
"""
import argparse
import gzip
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PHASES = ("pickup", "slide", "autoscroll", "drop")
BUDGET = {"frame_p95": 8.0, "frame_max": 16.0, "step": 4.0, "numbers": 50.0}


# --- the parent ------------------------------------------------------------------------------------------------------ #
def save_plan(seed_path, plan_path):
    """A plan file shaped like a Generate's, for the seed's analysed files in the order a Generate reads them."""
    import pickle
    from tests.test_services_moves import write_plan                  # (plain functions; no conftest imported)
    with open(seed_path, "rb") as f:
        items = pickle.load(f)["items"]
    order = ("now", "soon", "goal")
    analysed = sorted((r for r in items if r["tier"] in order), key=lambda r: (order.index(r["tier"]), r["ord"], r["id"]))
    write_plan(plan_path, [r["rel_path"] for r in analysed], [r["tier"] for r in analysed])


def run_child(seed_path, plan_path, out_path, scale, root, cycles):
    from tests.qt.bench_scroll import system_scale
    env = dict(os.environ)
    for k in ("QT_QPA_PLATFORM", "SURASURA_FREEZE_MOTION"):
        env.pop(k, None)
    env["SURASURA_TEST_ROOT"] = root
    env["SURASURA_ROW_PIXMAPS"] = "1"
    if scale:
        env["QT_SCALE_FACTOR"] = f"{scale / 100 / system_scale():.6f}"
    else:
        env.pop("QT_SCALE_FACTOR", None)
    cmd = [sys.executable, os.path.abspath(__file__), "--child", seed_path, "--plan", plan_path, "--out", out_path,
           "--cycles", str(cycles)]
    subprocess.run(cmd, env=env, cwd=ROOT, timeout=600, check=False)
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def _med(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(statistics.median(vals), 2) if vals else None


def summary(results):
    out = {}
    for ph in PHASES + ("all",):
        rows = [r.get("phases", {}).get(ph, {}) for r in results]
        out[ph] = {k: _med([x.get(k) for x in rows]) for k in
                   ("frames_p95_ms", "frames_max_ms", "clock_p95_ms", "clock_max_ms", "steps_max_ms", "steps_over_4ms")}
    out["drop_numbers_ms"] = {k: _med([r.get("drop_numbers", {}).get(k) for r in results]) for k in ("median", "max")}
    out["drop_step_ms"] = _med([r.get("drop_step_max_ms") for r in results])
    out["lift_step_ms"] = _med([r.get("lift_step_max_ms") for r in results])
    return out


def main_parent(a):
    from tests.qt.bench_scroll import save_seed, system_scale
    work = tempfile.mkdtemp(prefix="surasura-bench-drag-")
    seed_path, plan_path = os.path.join(work, "seed.pkl"), os.path.join(work, "plan.json.gz")
    t = time.perf_counter()
    files = save_seed(a.files, None, seed_path)
    save_plan(seed_path, plan_path)
    print(f"seed + plan: {files} files ({time.perf_counter() - t:.1f} s); this desktop's own scale {system_scale()}",
          flush=True)
    results = []
    for i in range(a.runs):
        root = tempfile.mkdtemp(prefix="surasura-bench-root-", dir=work)
        r = run_child(seed_path, plan_path, os.path.join(work, f"run{i}.json"), a.scale, root, a.cycles)
        results.append(r)
        ph = r.get("phases", {})
        print(f"run {i + 1}: dpr {r.get('dpr')} · " + " · ".join(
            f"{k} frames p95 {v.get('frames_p95_ms')} max {v.get('frames_max_ms')} clock p95 {v.get('clock_p95_ms')} "
            f"max {v.get('clock_max_ms')} steps max {v.get('steps_max_ms')} (>4 ms: {v.get('steps_over_4ms')})"
            for k, v in ph.items()) + f" · drop->numbers {r.get('drop_numbers')} · lift step {r.get('lift_step_max_ms')}"
            f" · drop step {r.get('drop_step_max_ms')}", flush=True)
        if a.scale and r.get("dpr") and abs(r["dpr"] - a.scale / 100) > 0.01:
            r["scale_mismatch"] = True
            print(f"WARNING: run {i + 1} ran at dpr {r['dpr']}, not {a.scale / 100}", flush=True)
    out = {"files": files, "scale": a.scale, "runs": results, "median": summary(results)}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
    print("median:", json.dumps(out["median"]), flush=True)


# --- the child ------------------------------------------------------------------------------------------------------- #
class _Stamped(list):
    """The HUD's list of steps / frames, each append also stamped (so a phase reads its own)."""

    def __init__(self, log):
        super().__init__()
        self.log = log

    def append(self, ms):
        super().append(ms)
        self.log.append((ms, time.perf_counter()))


def main_child(a):
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication
    from app import theme
    from app.qt import hud as hud_module, rows, shell
    from app.services import library_reader, moves
    from tests.qt.bench_scroll import _LazyOpener

    app = QApplication([sys.argv[0]])
    shell.prepare_process()
    opener = _LazyOpener(a.child)
    opener.check()                                       # loaded here: the numbers' worker and the reader share it
    library = opener.library
    held = []
    numbers = moves.Numbers(opener, "ja", plan_file=a.plan, on_change=lambda: held and held[0].refresh())
    numbers.load()
    numbers.idle(300)
    reader = library_reader.LibraryReader(opener, numbers=numbers, mining=lambda: opener.mining_ids)
    held.append(reader)

    class Writer:
        """The window's writer as the drag calls it: the numbers worked out on its own thread before the write (as
        `moves.Writer._numbers_move`), then the move written into the stand-in and its callbacks on that thread."""
        from app.qt.strings import MOVE_WORDS as words

        def __init__(self):
            self.on_saved = self.on_saving = self.on_reread = self.on_note = self.on_undone = None
            self.numbers = numbers
            self._pending = 0

        def start(self):
            return self

        def replay(self):
            return True

        def can_write(self):
            return True

        def reason(self):
            return None

        def hold(self):
            pass

        def release(self):
            pass

        def pending(self):
            return self._pending

        def can_undo(self):
            return False

        def finish(self, deadline):
            return True

        def move(self, ids, tier, before_id=None, after_id=None, near=(), label=None, end=False):
            self._pending += 1

            def run():
                numbers.after_move(ids, tier, before_id=before_id, after_id=after_id)
                items = {r["id"]: r for r in library.items()}
                rest = sorted((r for r in items.values() if r["tier"] == tier and r["id"] not in ids),
                              key=lambda r: (r["ord"], r["id"]))
                if before_id is not None:
                    k = next(i for i, r in enumerate(rest) if r["id"] == before_id)
                    hi = rest[k]["ord"]
                    lo = rest[k - 1]["ord"] if k else hi - 1024
                elif after_id is not None:
                    k = next(i for i, r in enumerate(rest) if r["id"] == after_id)
                    lo = rest[k]["ord"]
                    hi = rest[k + 1]["ord"] if k + 1 < len(rest) else lo + 1024
                else:
                    hi = rest[0]["ord"] if rest else 1024.0
                    lo = hi - 1024
                step = (hi - lo) / (len(ids) + 1)
                library.commit(items=[{"id": i, "tier": tier, "ord": lo + step * (n + 1)} for n, i in enumerate(ids)],
                               order=True)
                self._pending -= 1
                self.on_saved(_Change(ids), label)
            threading.Thread(target=run, daemon=True).start()
            return 1

        def nudge(self, *a, **k):
            return None

        set_tier = set_finished = set_watched = insert_at = undo = nudge

    class _Change:
        def __init__(self, ids):
            self.ids, self.kind = list(ids), "move"

    result = {"lift_steps": [], "drop_steps": [], "numbers_ms": []}
    real_show = shell.ShellWindow.show_library
    watch = {}                                           # the drop being watched: key, t0, version before
    page_of = {}

    def show_library(self_, view):                       # (on the class, before the window opens: its first view
        real_show(self_, view)                           # can come before any connection made after)
        page = page_of.get("page")
        w = watch.get("key")
        if page is None or w is None or numbers.version <= watch["v0"]:
            return
        table = numbers()[1]
        row = next((r for r in page.view_model.rows if r.key == w), None) if page.view_model is not None else None
        if row is None:
            return
        news = [table.get(e.id, (0, 0, None))[2] for e in row.episodes]
        news = [n for n in news if n is not None]
        want = sum(news) if news else None
        if want is not None and row.n_new == want:
            result["numbers_ms"].append(round((time.perf_counter() - watch["t0"]) * 1000, 2))
            watch.clear()
    shell.ShellWindow.show_library = show_library
    writer = Writer()
    services = shell.Services(library=reader, writer=writer)
    window = shell.open_window(app, services)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    hud = hud_module.Hud(window, overlay=False).start()
    step_log, frame_log = [], []
    hud.steps, hud.frames = _Stamped(step_log), _Stamped(frame_log)
    tagged_log = []                                      # the motion clock's frames (its work + the paint after)
    hud.anim_frames = _Stamped(tagged_log)
    page = window.page_widgets["current"]
    page_of["page"] = page
    lst = page.list
    central = window.centralWidget()
    phases = []                                          # (name, t0, t1)
    LEFT, NONE = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton

    def send(widget, kind, pos, button, buttons):
        pos = QPointF(pos)
        QApplication.sendEvent(widget, QMouseEvent(kind, pos, QPointF(widget.mapToGlobal(pos.toPoint())), button,
                                                   buttons, Qt.KeyboardModifier.NoModifier))

    def move_global(gpos):
        send(central, QEvent.Type.MouseMove, central.mapFromGlobal(gpos), NONE, LEFT)

    def title_point(i):
        entry = lst.model().entries[i]
        rect = lst.visualRect(lst.model().index(i, 0))
        if entry[0] == rows.HERO:
            return lst.delegate._hero_geometry(entry[1], rect, entry[2])["title"].center()
        g = lst.delegate.line_geometry(entry[1], lst.delegate.slab_of(rect))
        return QPoint(g["main"].left() + 20, g["main"].center().y())

    def visible_rows():
        out = []
        for i, e in enumerate(lst.model().entries):
            if e[0] != rows.ROW:
                continue
            r = lst.visualRect(lst.model().index(i, 0))
            if r.top() >= 0 and r.bottom() <= lst.viewport().height():
                out.append(i)
        return out


    def first_frame():
        hud.ignore_before = time.perf_counter()
    window.first_frame.connect(first_frame)

    # the plan: a list of (delay ms, action) run one after another off the event loop
    plan = []

    def at(ms, fn):
        plan.append((ms, fn))

    def phase(name):
        def go():
            if phases and phases[-1][2] is None:
                phases[-1] = (phases[-1][0], phases[-1][1], time.perf_counter())
            if name:
                phases.append((name, time.perf_counter(), None))
            hud.tag = name
        return go

    state = {}

    def cycle(c):
        def pick():
            vis = visible_rows()
            i = vis[min(len(vis) - 1, 2 + c % 3)]
            state["src"] = i
            state["key"] = lst.model().entries[i][1].key
            state["at"] = lst.viewport().mapToGlobal(title_point(i))
            send(lst.viewport(), QEvent.Type.MouseButtonPress, lst.viewport().mapFromGlobal(state["at"]), LEFT, LEFT)
        at(16, phase("pickup"))
        at(0, pick)

        def lift():
            t0 = time.perf_counter()
            p = state["at"] + QPoint(0, theme.MOTION["drag-start-px"])
            send(lst.viewport(), QEvent.Type.MouseMove, lst.viewport().mapFromGlobal(p), NONE, LEFT)
            result["lift_steps"].append(round((time.perf_counter() - t0) * 1000, 2))
            state["hand"] = p
        at(16, lift)
        for k in range(18):                              # the hand drifts while the ghost settles
            at(16, lambda k=k: move_global(state["hand"] + QPoint(k % 3, k // 6)))
        at(16, phase("slide"))
        for k in range(90):                              # ~7 rows down at 60 Hz
            def down(k=k):
                state["hand"] = state["hand"] + QPoint(0, 4)
                move_global(state["hand"])
            at(16, down)
        at(16, phase("autoscroll"))
        for k in range(90):                              # rests at the bottom edge (the list scrolls under it)
            def edge(k=k):
                vp = lst.viewport()
                p = vp.mapToGlobal(QPoint(vp.width() // 2, vp.height() - 6 - k % 2))
                state["hand"] = p
                move_global(p)
            at(16, edge)
        for k in range(30):                              # and comes back up into the list
            def up(k=k):
                vp = lst.viewport()
                p = vp.mapToGlobal(QPoint(vp.width() // 2, vp.height() - 40 - 8 * k))
                state["hand"] = p
                move_global(p)
            at(16, up)
        at(16, phase("drop"))

        def let_go():
            if window.moves.running is None:
                return
            watch.update(key=state["key"], v0=numbers.version, t0=time.perf_counter())
            t0 = time.perf_counter()
            send(central, QEvent.Type.MouseButtonRelease, central.mapFromGlobal(state["hand"]), LEFT, NONE)
            result["drop_steps"].append(round((time.perf_counter() - t0) * 1000, 2))
        at(16, let_go)
        at(900, phase(None))                             # the glide home and the numbers
        at(400, lambda: None)

    def run(i=0):
        if i >= len(plan):
            return finish()
        ms, fn = plan[i]
        fn()
        QTimer.singleShot(ms, lambda: run(i + 1))

    def start(tries=[0]):
        v = page.view_model
        if v is None or v.loading or not v.rows:
            tries[0] += 1
            if tries[0] % 40 == 0:
                print(f"bench_drag: waiting for rows ({None if v is None else (v.state, v.loading, len(v.rows))})",
                      flush=True)
            QTimer.singleShot(50, start)
            return
        print(f"bench_drag: {len(v.rows)} rows live; {a.cycles} cycles", flush=True)
        lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 3)
        for c in range(a.cycles):
            cycle(c)
        QTimer.singleShot(1500, run)

    def finish():
        def slice_(log, t0, t1):
            return [ms for ms, t in log if t0 <= t <= t1]
        per = {}
        spans = [(n, t0, t1) for n, t0, t1 in phases if t1 is not None]
        for name in PHASES + ("all",):
            ss = [(t0, t1) for n, t0, t1 in spans if n == name or name == "all"]
            fr = [x for t0, t1 in ss for x in slice_(frame_log, t0, t1)]
            ck = [x for t0, t1 in ss for x in slice_(tagged_log, t0, t1)]
            st = [x for t0, t1 in ss for x in slice_(step_log, t0, t1)]
            per[name] = {"frames_n": len(fr), "frames_p95_ms": round(hud_module.p95(fr), 2) if fr else None,
                         "frames_max_ms": round(max(fr), 2) if fr else None,
                         "clock_n": len(ck), "clock_p95_ms": round(hud_module.p95(ck), 2) if ck else None,
                         "clock_max_ms": round(max(ck), 2) if ck else None,
                         "steps_max_ms": round(max(st), 2) if st else None,
                         "steps_over_4ms": sum(1 for x in st if x > BUDGET["step"])}
        nums = sorted(result["numbers_ms"])
        result["drop_numbers"] = {"n": len(nums), "of": a.cycles, "median": _med(nums),
                                  "max": nums[-1] if nums else None}
        result["lift_step_max_ms"] = max(result["lift_steps"], default=None)
        result["drop_step_max_ms"] = max(result["drop_steps"], default=None)
        result["phases"] = per
        result["hud"] = hud.report()
        result["memory"] = hud_module._memory_mb()
        result["dpr"] = lst.viewport().devicePixelRatioF()
        result["drops"] = window.moves.drops
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f)
        app.quit()

    QTimer.singleShot(240000, finish)                   # never longer than 4 min
    window.show_first()
    QTimer.singleShot(800, start)
    try:
        app.exec()
    finally:
        services.shutdown(1.0)
        numbers.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=20000)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--scale", type=int, default=0, help="the screen's scaling in % (0: Windows' own)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--child", default=None)
    a = ap.parse_args()
    if a.child:
        main_child(a)
    else:
        main_parent(a)


if __name__ == "__main__":
    main()
