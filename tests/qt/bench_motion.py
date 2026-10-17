"""The motion's budgets on this machine (M2.1 row 7; the window's spec 07 §7.1 *Budgets*, BRIEF rule 12).

    python tests/qt/bench_motion.py [--rounds 12] [--scales 100,125,150,175,200,250] [--reduced] [--json OUT]

The shell, on screen without taking the keyboard, at `--scale` % (`QT_SCALE_FACTOR` over this desktop's own scaling),
in a fresh process under a temp `SURASURA_TEST_ROOT` (set and checked: the shell writes `window_state.json` at close).
Over a page that repaints like Current (a `QListView` of 2,000 painted rows of Japanese text, a cover box and numbers,
scrolled to its middle), after the first paint:
- each overlay kind (`motion.HOW`) opened `--rounds` times — a stand-in of its real size (the tray 452 px wide with ten
  rows of text, the Goal sheet the window's width, the side panel its height, a dialog card, a scrim) with its shadow —
  each closed before the next;
- a toast shown and closed `--rounds` times, so each one rises;
- the header's progress hairline shown all along (W3.1a: it replaced the bar's pulsing dot, and never pulses);
then 3 s with nothing moving. The HUD measures every animation frame (the motion clock's work + the paint and flush
that follow it), tagged by what moved, every GUI-thread step, and the late ticks with their causes.

**M4.1 row 2:** the HUD now sees every window's frames — the lift's own window above the main one (M2.1-3), whose
frames move in Windows' compositor and paint nothing — so the per-kind tags come back at every scale (W3.1a timed-1
found them empty at 125-200 %). Each kind's openings run one after another as one moment (`open-<kind>`, the toast
`toast-rise`), the clock's wake-ups counted once it is still after each; per moment the frames by window, the slow
frames with their causes, the steps' typical worst (`bench_moments`). `--scales` runs each scale in its own child at
true scale (a fresh test root with its own APPDATA / LOCALAPPDATA); `--reduced` sets `app_motion` = reduced there.

**This desktop's targets** are the laptop's budgets ÷ 2.5 (charter S8, as W2.1): an overlay opening ≤ 3.2 ms a frame
(p95), never over 6.4 ms; no GUI-thread step over 1.6 ms; no clock wake-up while nothing moves. The laptop's own budget
(≤ 8 / 16 / 4 ms at 150 %) is proven only by its own run, with Sonic's go. Run under `locks/with-lock.sh timed`.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tests.qt import bench_moments                                    # noqa: E402

DESKTOP = {"frame_p95": 3.2, "frame_max": 6.4, "step": 1.6}          # the laptop's 8 / 16 / 4 ÷ 2.5
ROWS = 2000
JA = ["進撃の巨人", "鬼滅の刃", "葬送のフリーレン", "薬屋のひとりごと", "ぼっち・ざ・ろっく！", "チェンソーマン", "呪術廻戦",
      "スパイファミリー", "ダンジョン飯", "その着せ替え人形は恋をする"]


def _system_scale():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def speed_ms():
    """A plain Python loop's time in this process: this desktop runs some processes ~5× slower than others (row D),
    so each run says which kind it was."""
    import time
    t = time.perf_counter()
    n = 0
    for i in range(3_000_000):
        n += i & 7
    return round((time.perf_counter() - t) * 1000, 1)


# --- the child: the shell, the page, the overlays ------------------------------------------------------------------ #
def child(rounds):
    sys.path.insert(0, ROOT)
    speed = speed_ms()
    from PyQt6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, QTimer
    from PyQt6.QtGui import QPainter
    from PyQt6.QtWidgets import QApplication, QLabel, QListView, QStyledItemDelegate, QVBoxLayout
    from app import theme
    from app.qt import hud, motion, shadow, shell, style

    class Rows(QAbstractListModel):
        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else ROWS

        def data(self, index, role=Qt.ItemDataRole.DisplayRole):
            if role == Qt.ItemDataRole.DisplayRole:
                return f"{JA[index.row() % len(JA)]}  第{index.row() % 24 + 1}話"
            return None

    from PyQt6.QtGui import QStaticText

    class Painted(QStyledItemDelegate):
        """Rows painted as the spec says the Current list paints them (05 §5.11: text cached as QStaticText)."""
        cache = {}

        def _text(self, key, text):
            st = self.cache.get(key)
            if st is None:
                st = self.cache[key] = QStaticText(text)
                st.setPerformanceHint(QStaticText.PerformanceHint.AggressiveCaching)
            return st

        def paint(self, p, option, index):
            c = style.colours()
            r = option.rect
            row = index.row()
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(style.qcolor(c["raised"]))
            p.drawRoundedRect(QRectF(r.left() + 12, r.top() + 6, 31, 44), 5, 5)
            p.setPen(style.qcolor(c["ink"]))
            mid = r.top() + r.height() // 2 - 9
            p.drawStaticText(r.left() + 56, mid, self._text(("t", row % 240), index.data()))
            p.setPen(style.qcolor(c["ink-dim"]))
            p.drawStaticText(r.right() - 190, mid, self._text(("p", row % 100), f"{(row * 37) % 100} %"))
            p.drawStaticText(r.right() - 100, mid, self._text(("n", row % 60), f"{(row * 13) % 60} new"))
            p.restore()

        def sizeHint(self, option, index):
            return QSize(600, 56)

    class StandIn(motion.Overlay):
        def grab(self, *a):
            with probe_hud().span("open-grab"):
                return super().grab(*a)

        def __init__(self, parent, how, rows):
            super().__init__(parent)
            self.how = how
            self.shadow_name = {"pop": "menu", "tray": "tray", "up": "sheet", "slide": "tray", "dialog": "dialog",
                                "rise": "toast", "fade": None}[how]
            self.setAutoFillBackground(True)
            pal = self.palette()
            pal.setColor(self.backgroundRole(), style.qcolor(style.colours()["surface"]))
            self.setPalette(pal)
            lay = QVBoxLayout(self)
            for i in range(rows):
                lay.addWidget(QLabel(f"{JA[i % len(JA)]} · 第{i + 1}話 · 新しい言葉 {12 + i}", self))
            self.hide()
            if self.shadow_name:
                self.follower = shadow.Follower(self, self.shadow_name)

    results = {}
    meters = []

    def probe_hud():
        return meters[0]
    orig_first = hud.Probe._first_frame

    def first(self):
        orig_first(self)
        QTimer.singleShot(600, lambda: exercise(self))
    hud.Probe._first_frame = first

    def exercise(probe):
        window, meter = probe.window, probe.hud
        meters.append(meter)
        bench_moments.apply_reduced()
        moments = bench_moments.Moments(meter, tag=False)      # (the tags stay the kinds, as M2.1 read them)
        # where a frame's time goes: the ghost's own paint and the list's, as spans (the rest is the flush and the rest
        # of the window repainted under the ghost)
        ghost_paint = motion._Ghost.paintEvent

        def timed_ghost(self, event):
            with meter.span("ghost-paint"):
                ghost_paint(self, event)
        motion._Ghost.paintEvent = timed_ghost

        def timed(owner, name, label):
            fn = getattr(owner, name)

            def wrapped(*a, **k):
                with meter.span(label):
                    return fn(*a, **k)
            setattr(owner, name, wrapped)
        # the opening's own steps, by name: which one is long (the click's own share, the overlay's snapshot, the picture
        # with its shadow, the lift's window shown and painted, the overlay itself shown at the end, a close)
        timed(motion.OverlayOpening, "start", "open-start")
        timed(motion.OverlayOpening, "_compose", "open-compose")
        timed(motion.OverlayOpening, "_snapshot", "open-snapshot")      # M2.1-1 (b): the pieces, each its own step
        timed(motion.OverlayOpening, "_go", "open-go")
        timed(motion.OverlayOpening, "_lift_place", "lift-place")   # M2.1-3: the lift's pieces
        timed(motion._Lift, "paint", "lift-paint")
        timed(motion._Lift, "flush", "lift-flush")
        timed(motion, "_show", "overlay-show")
        timed(motion, "_give_back", "lift-give-back")
        list_paint = QListView.paintEvent

        def timed_list(self, event):
            with meter.span("list-paint"):
                list_paint(self, event)
        central = window.centralWidget()
        page = window.pages
        view = type("TimedList", (QListView,), {"paintEvent": timed_list})(page)
        view.setModel(Rows(view))
        view.setItemDelegate(Painted(view))
        view.setUniformItemSizes(True)
        view.setGeometry(page.rect())
        view.show()
        view.scrollTo(view.model().index(ROWS // 2, 0), QListView.ScrollHint.PositionAtCenter)
        w, h = central.width(), central.height()
        stands = {
            "pop": (StandIn(central, "pop", 6), QRect(w - 300, 70, 264, 220)),
            "tray": (StandIn(central, "tray", 10), QRect(w - 480, 70, 452, 420)),
            "up": (StandIn(central, "up", 4), QRect(0, h - 300, w, 260)),
            "slide": (StandIn(central, "slide", 12), QRect(w - 360, 90, 360, h - 130)),
            "dialog": (StandIn(central, "dialog", 5), QRect((w - 560) // 2, (h - 300) // 2, 560, 300)),
            "fade": (StandIn(central, "fade", 0), QRect(0, 0, w, h)),
        }
        steps = []
        for kind, (widget, rect) in stands.items():              # M4.1: a kind's openings together, one moment
            for _round in range(rounds):
                steps.append(("open", kind, widget, rect))
                steps.append(("close", kind, widget, None))
            steps.append(("still", f"open-{kind}", None, None))
        for _round in range(rounds):
            steps.append(("toast", "rise", None, None))
            steps.append(("toast-close", "rise", None, None))
        steps.append(("still", "toast-rise", None, None))
        # a person clicks in the window in front: the lift is used only then (the final adversary's first finding).
        # The bench shows it without activation; Windows may refuse a background process the foreground, so the bench
        # then says so and takes the lifted path as in front (the lift paints and moves the same; only its stacking
        # over other programs differs)
        window.raise_()
        window.activateWindow()

        def begin():
            results["active"] = QApplication.activeWindow() is window
            if not results["active"] and motion._lifted():
                motion._in_front = lambda top: True
            results["in_front_forced"] = not results["active"] and motion._lifted()
            window.progress.set(True)              # W3.1a: the header's hairline (the dot is gone)
            meter.discard_current()
            run()

        def run(i=0):
            if i >= len(steps):
                return settle()
            what, kind, widget, rect = steps[i]
            if what == "still":
                moments.still(kind, lambda: run(i + 1))
                return
            if what == "open":
                widget.setGeometry(rect)
                moments.begin(f"open-{kind}")
                meter.tag = kind
                motion.open_overlay(widget, kind, widget.shadow_name, on_done=lambda: setattr(meter, "tag", None))
                wait = motion.duration(motion.HOW[kind][0]) + 120
            elif what == "close":
                moments.end()
                meter.tag = None
                with meter.span("close"):
                    widget.hide()
                wait = 80
            elif what == "toast":
                moments.begin("toast-rise")
                meter.tag = "toast"
                window.toasts.show("進撃の巨人 → Soon · #26, after the first 25 files", undo=lambda: None)
                op = motion.opening_of(window.toasts.card)
                if op is not None:
                    op.on_done = lambda: setattr(meter, "tag", None)
                wait = motion.duration("toast-rise") + 120
            else:
                moments.end()
                meter.tag = None
                window.toasts.close()
                wait = 80
            QTimer.singleShot(wait, lambda: run(i + 1))

        def settle():
            window.progress.set(False)
            clock = motion.clock()
            QTimer.singleShot(200, lambda: idle_start(clock))

        def idle_start(clock):
            results["wakes_before_idle"] = clock.stats.wakes
            results["clock_running_at_idle"] = clock.running
            QTimer.singleShot(3000, lambda: finish(clock))

        def finish(clock):
            results["idle_wakes"] = clock.stats.wakes - results["wakes_before_idle"]
            steps_ms = list(meter.steps)
            results["steps_over_desktop"] = sum(1 for s in steps_ms if s > DESKTOP["step"])
            results["steps_over_4ms"] = sum(1 for s in steps_ms if s > 4.0)
            results["step_max_ms"] = round(max(steps_ms, default=0.0), 2)
            results["step_p95_ms"] = round(hud.p95(steps_ms), 2)
            results["scale_dpr"] = window.devicePixelRatioF()
            results["speed_ms"] = speed
            results["speed_ms_after"] = speed_ms()
            probe.result["bench"] = results
            probe.result["moments"] = moments.summary()
            probe._finish()

        QTimer.singleShot(300, begin)                # (activation comes through the loop)

    return shell.main(["bench-motion"])


# --- the parent: one fresh process per scale ------------------------------------------------------------------------ #
def one_scale(scale, rounds, root=None, env=None):
    """One child at `scale` %: in `root` (with its env from `bench_moments.scaled_runs`), or a temp root of its own."""
    if root is None:
        work = tempfile.mkdtemp(prefix="m21-bench-")
        root, extra = bench_moments.fresh_root(work, assets=True)
        env = bench_moments.child_env(scale, extra)
    probe = os.path.join(root, "probe.json")
    env = dict(env, SURASURA_SHELL_PROBE=probe, SURASURA_SHELL_PROBE_IDLE="900", SURASURA_HUD="1",
               SURASURA_INSTANCE_NAME=f"surasura-bench-{os.getpid()}-{os.path.basename(os.path.dirname(root))}",
               QT_ENABLE_HIGHDPI_SCALING="1")
    for k in ("QT_QPA_PLATFORM", "SURASURA_FREEZE_MOTION", "SURASURA_SHELL_PROBE_EXERCISE", "SURASURA_GC_FREEZE"):
        env.pop(k, None)
    proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", "--rounds", str(rounds)], cwd=root,
                          env=env, capture_output=True, text=True, timeout=900)
    if not os.path.exists(probe):
        return {"scale": scale, "error": f"no probe file (exit {proc.returncode}): {proc.stderr[-1500:]}"}
    with open(probe, encoding="utf-8") as f:
        r = json.load(f)
    assert os.path.exists(os.path.join(root, "local")), "the run wrote its local data under the test root"
    r["scale"] = scale
    return r


def verdict(r):
    tags = r.get("hud", {}).get("tagged", {})
    overlays = {k: v for k, v in tags.items() if k != "toast"}
    worst_p95 = max((v["p95_ms"] for v in tags.values()), default=None)
    worst_max = max((v["max_ms"] for v in tags.values()), default=None)
    b = r.get("bench", {})
    ok = (worst_p95 is not None and worst_p95 <= DESKTOP["frame_p95"] and worst_max <= DESKTOP["frame_max"]
          and b.get("steps_over_desktop") == 0 and b.get("idle_wakes") == 0)
    return {"scale": r["scale"], "dpr": b.get("scale_dpr"), "speed_ms": [b.get("speed_ms"), b.get("speed_ms_after")],
            "frames_by_kind": tags, "overlays_n": len(overlays),
            "frame_p95_worst_ms": worst_p95, "frame_max_worst_ms": worst_max, "step_max_ms": b.get("step_max_ms"),
            "steps_over_1_6ms": b.get("steps_over_desktop"), "steps_over_4ms": b.get("steps_over_4ms"),
            "idle_wakes": b.get("idle_wakes"), "active": b.get("active"), "in_front_forced": b.get("in_front_forced"),
            "late": r.get("hud", {}).get("late", {}).get("causes"),
            "late_max_ms": r.get("hud", {}).get("late", {}).get("max_ms"),
            "clock": r.get("hud", {}).get("anim"), "spans": r.get("hud", {}).get("spans"),
            "desktop_targets_met": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--scale", default=None, help="the old flag: one or more, comma-separated (as --scales)")
    ap.add_argument("--repeat", type=int, default=1, help="runs per scale (this desktop's processes differ in speed)")
    bench_moments.add_arguments(ap)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        return child(args.rounds)

    def one_run(scale, root, env, i):
        r = one_scale(scale, args.rounds, root, env)
        if "error" in r:
            print(json.dumps(r))
            return r
        v = verdict(r)
        print("SCALE " + json.dumps(v), flush=True)
        return {"verdict": v, "raw": r, "dpr": v["dpr"], "moments": r.get("moments"),
                "extra": {"frames_by_kind": {k: [x["n"], x["p95_ms"], x["max_ms"]] for k, x in v["frames_by_kind"].items()},
                          "windows": r.get("hud", {}).get("windows")}}
    scales = bench_moments.parse_scales(args.scale or args.scales)
    out = bench_moments.scaled_runs("bench_motion", scales, args.repeat, args.reduced, one_run, args.out,
                                    meta={"rounds": args.rounds})
    ok = all("verdict" in o and o["verdict"]["desktop_targets_met"] for o in out["results"])
    print("BENCH " + ("MEETS THE DESKTOP TARGETS" if ok else "MISSES A DESKTOP TARGET"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
