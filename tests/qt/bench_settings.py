"""Settings' moments on this machine (M4.1 row 2; the RUNBOOK's *The moments*: the nav's glide, the *More options*
fold, a switch landing — Junban's —, a search keystroke, the page's build slices; W3.3 FXP S3 / S5 measured them
offscreen, never timed).

    python tests/qt/bench_settings.py [--rounds 10] [--scales 100,125,150,175,200,250] [--reduced] [--json OUT.json]

Not collected by pytest (no `test_` prefix). A timed run: start it through `locks/with-lock.sh timed …` from the copy.

Each scale × run is a child process on Windows' own platform (`bench_moments.scaled_runs`: a fresh temp
`SURASURA_TEST_ROOT` with its own APPDATA / LOCALAPPDATA and settings, true scale, its `dpr` recorded). The child opens
the window (`shell.open_window`, shown without taking the keyboard), and with the HUD watching every window's frames
and every GUI-thread step, `--rounds` times each (>= 10 for a timed run):
  - `build`: the Settings page built in its slices — the first the shell's own (`mount_settings`, the process's first
    page), then fresh pages in the same tab (as FXP's "three pages per process"); each page's slices noted: the first,
    the rest's median and max, the loop's own turn between (`slice_ms`, `between_ms`);
  - `nav-glide`: a nav button clicked (`go_to`: the page glides on the motion clock; reduced: a jump), far sections in
    turn;
  - `more-options`: a section's *More options* clicked, open then closed;
  - `switch-junban`: Junban's on/off switch pressed and released (the slide, the light, the write, its landing: the
    section's rows shown or hidden) — skipped, and said, when `modules/junban` is absent;
  - `slider-release`: the level slider (Settings › Level) pressed on its band's chamber and dragged to the next before
    the repetition, then let go: its `changed` and the page's refresh and write at the release (Gap 2: the choice and
    its save at the action), through the gem's settle into its chamber;
  - `search-key`: a keystroke in the search (a word typed letter by letter, then taken back).
After each moment's last repetition the clock's wake-ups are counted once it is still.
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.qt import bench_moments                                    # noqa: E402

WORDS = ("anki", "motion")                       # the settings' names are English: the search's real queries


def main_parent(a):
    def one_run(scale, root, env, i):
        out_path = os.path.join(os.path.dirname(root), "result.json")
        env["SURASURA_INSTANCE_NAME"] = f"surasura-bench-settings-{os.getpid()}-{os.path.basename(os.path.dirname(root))}"
        cmd = [sys.executable, os.path.abspath(__file__), "--child", "--rounds", str(a.rounds), "--out", out_path]
        proc = subprocess.run(cmd, env=env, cwd=root, timeout=1200, check=False, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if not os.path.exists(out_path):
            return {"error": f"no result (exit {proc.returncode}): {proc.stderr[-1500:]}"}
        with open(out_path, encoding="utf-8") as f:
            r = json.load(f)
        return r
    bench_moments.scaled_runs("bench_settings", a.scales_list, a.runs, a.reduced, one_run, a.out,
                              meta={"rounds": a.rounds})


def main_child(a):
    from PyQt6.QtCore import QEvent, QPointF, Qt, QTimer
    from PyQt6.QtGui import QKeyEvent, QMouseEvent
    from PyQt6.QtWidgets import QApplication
    from app.qt import hud as hud_module, settings_catalog as catalog, settings_page as sp, shell

    app = QApplication([sys.argv[0]])
    shell.prepare_process()
    services = shell.Services()
    window = shell.open_window(app, services)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    bench_moments.apply_reduced()
    hud = hud_module.Hud(window, overlay=False).start()
    moments = bench_moments.Moments(hud)
    result = {"skipped": {}, "pages": []}
    plan = []                                            # (delay ms, action): the action, then the delay

    def at(ms, fn):
        plan.append((ms, fn))

    def first_frame():
        hud.ignore_before = time.perf_counter()
    window.first_frame.connect(first_frame)

    def until(pred, timeout_ms, why):
        def go(then):
            deadline = time.perf_counter() + timeout_ms / 1000.0

            def poll():
                if pred():
                    then()
                elif time.perf_counter() > deadline:
                    result["skipped"][why] = result["skipped"].get(why, 0) + 1
                    then()
                else:
                    QTimer.singleShot(20, poll)
            poll()
        return go

    state = {}

    def page():
        return window.settings_page

    # --- the build, in its slices ----------------------------------------------------------------------------------- #
    def build(c):
        def go():
            moments.begin("build")
            if c == 0:
                window.show_tab("settings")
                state["page"] = window.mount_settings()
                return
            holder = window.page_widgets["settings"]
            page().hide()
            fresh = sp.SettingsPage(window, page().language, parent=holder)
            holder.layout().insertWidget(0, fresh, 1)
            fresh.show()
            state["page"] = fresh
        at(0, go)
        at(0, lambda: until(lambda: state["page"].built, 8000, "build: never ready"))

        def done():
            moments.end()
            p = state["page"]
            sl, between = list(p.slice_ms), list(p.between_ms)
            line = {"slices": len(sl), "first_ms": round(sl[0], 2) if sl else None,
                    "rest_median_ms": round(sorted(sl[1:])[len(sl[1:]) // 2], 2) if len(sl) > 1 else None,
                    "rest_max_ms": round(max(sl[1:]), 2) if len(sl) > 1 else None,
                    "between_median_ms": round(sorted(between)[len(between) // 2], 2) if between else None}
            result["pages"].append(line)
            if sl:                                       # its loop never waits between slices: the slices are its steps
                moments.own_steps("build", round(max(sl), 2), "the page's build slices (slice_ms)")
            for k, v in line.items():
                moments.note("build", k, v)
            if p is not page():
                p.hide()
                p.deleteLater()
                page().show()
        at(300, done)

    # --- the nav's glide ---------------------------------------------------------------------------------------------- #
    far = [s.id for s in catalog.SECTIONS]

    def glide(c):
        def go():
            shown = [s for s in far if s in page().nav and page().nav[s].isVisible()]
            target = shown[-1 - (c % 3)] if c % 2 == 0 else shown[c % 3]
            moments.begin("nav-glide")
            page().nav[target].click()
        at(700, go)                                      # (the glide inside the repetition)
        at(250, lambda: moments.end())

    # --- the More options fold ---------------------------------------------------------------------------------------- #
    def fold(c):
        def go():
            p = page()
            folds = [sid for sid, slab in p.slabs.items() if slab.more.isVisible()]
            if not folds:
                result["skipped"]["more-options: no fold"] = result["skipped"].get("more-options: no fold", 0) + 1
                return
            sid = folds[(c // 2) % len(folds)]
            if c % 2 == 0:                               # its section in view first, never part of the moment
                p.scroll.verticalScrollBar().setValue(max(0, p._y_in_body(p.slabs[sid].more) - 200))
            state["fold"] = sid
        at(250, go)

        def click():
            if "fold" in state:
                moments.begin("more-options")
                page().slabs[state["fold"]].more.click()
        at(500, click)
        at(0, lambda: moments.end())

    # --- Junban's switch landing ------------------------------------------------------------------------------------- #
    def switch(c):
        def go():
            row = page().row("enable_junban")
            ctl = row.controls[0] if row is not None and row.controls and row.isVisible() else None
            state["switch"] = ctl
            if ctl is None:
                result["skipped"]["switch-junban: no row"] = result["skipped"].get("switch-junban: no row", 0) + 1
                return
            p = page()
            p.scroll.verticalScrollBar().setValue(max(0, p._y_in_body(row) - 200))
        at(250, go)

        def press():
            ctl = state.get("switch")
            if ctl is None:
                return
            moments.begin("switch-junban")
            pos = QPointF(ctl.width() / 2, ctl.height() / 2)
            for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                  (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                QApplication.sendEvent(ctl, QMouseEvent(kind, pos, QPointF(ctl.mapToGlobal(pos.toPoint())),
                                                        Qt.MouseButton.LeftButton, buttons,
                                                        Qt.KeyboardModifier.NoModifier))
        at(800, press)                                   # (its write and landing inside the repetition)
        at(0, lambda: moments.end())

    # --- the level slider let go ------------------------------------------------------------------------------------ #
    def slider(c):
        def go():
            row = page().row("level")
            ctl = row.controls[0] if row is not None and row.controls and row.isVisible() else None
            state["slider"] = ctl if ctl is not None and ctl.isEnabled() else None
            if state["slider"] is None:
                why = "slider-release: no slider"
                result["skipped"][why] = result["skipped"].get(why, 0) + 1
                return
            p = page()
            p.scroll.verticalScrollBar().setValue(max(0, p._y_in_body(row) - 200))
            n = len(ctl._bands)
            i = ctl._index
            state["slider_to"] = i + 1 if i + 1 < n else i - 1      # a neighbouring band: the next, or at the end
            state["slider_from"] = i                                  # where its gem is seated now
        at(250, go)

        def mouse(kind, i, buttons):
            ctl = state["slider"]
            pos = ctl.chamber(i)
            QApplication.sendEvent(ctl, QMouseEvent(kind, pos, QPointF(ctl.mapToGlobal(pos.toPoint())),
                                                    Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))

        def press():
            if state["slider"] is not None:              # pressed and dragged before the repetition (the lift)
                mouse(QEvent.Type.MouseButtonPress, state["slider_from"], Qt.MouseButton.LeftButton)
        at(16, press)
        for k in range(1, 13):                           # the hand travels to the other chamber at 60 Hz
            def drag_(k=k):
                ctl = state["slider"]
                if ctl is None:
                    return
                a_, b_ = ctl.chamber(state["slider_from"]), ctl.chamber(state["slider_to"])
                pos = a_ + (b_ - a_) * (k / 12)
                QApplication.sendEvent(ctl, QMouseEvent(QEvent.Type.MouseMove, pos,
                                                        QPointF(ctl.mapToGlobal(pos.toPoint())),
                                                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                                        Qt.KeyboardModifier.NoModifier))
            at(16, drag_)
        at(120, lambda: None)                            # held over it a moment, as a hand does

        def release():
            if state["slider"] is None:
                return
            state["slider_was"] = state["slider"].value()
            moments.begin("slider-release")              # the release: its `changed`, the page's refresh and write,
            mouse(QEvent.Type.MouseButtonRelease, state["slider_to"], Qt.MouseButton.NoButton)    # the gem's settle
        at(0, release)
        at(500, lambda: None)                            # (the settle, 85-205 ms, and the write's landing inside it)

        def released():
            moments.end()
            if state["slider"] is not None:              # its band changed at the release (a `changed` each time)
                moments.note("slider-release", "changed", int(state["slider"].value() != state["slider_was"]))
        at(0, released)
        at(150, lambda: None)

    # --- a search keystroke --------------------------------------------------------------------------------------------- #
    def keystrokes():
        out = []
        for word in WORDS:
            out += [(ch, Qt.Key(ord(ch.upper()))) for ch in word] + [(None, Qt.Key.Key_Backspace)] * len(word)
        return out

    def search(c, ch, key):
        def go():
            p = page()
            if c == 0 and ch is not None and not p.search.edit.text():
                p.scroll.verticalScrollBar().setValue(0)       # the search in view, as a person types into it
            moments.begin("search-key")
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(p.search.edit, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier, ch or ""))
        at(220, go)
        at(30, lambda: moments.end())

    def still(name):
        return lambda: (lambda then: moments.still(name, then))

    def run(i=0):
        if i >= len(plan):
            return finish()
        ms, fn = plan[i]
        r = fn()
        nxt = (lambda: QTimer.singleShot(ms, lambda: run(i + 1)))
        if callable(r):
            r(nxt)
        else:
            nxt()

    def start():
        n = a.rounds
        for c in range(n):
            build(c)
        at(0, still("build"))
        at(0, lambda: until(lambda: page()._found is not None, 5000, "modules never looked for"))
        for c in range(n):
            glide(c)
        at(0, still("nav-glide"))
        for c in range(2 * ((n + 1) // 2)):
            fold(c)
        at(0, still("more-options"))
        for c in range(2 * ((n + 1) // 2)):
            switch(c)
        at(0, still("switch-junban"))
        for c in range(n):
            slider(c)
        at(0, still("slider-release"))
        strokes = keystrokes()
        k = 0
        while k < max(n, len(strokes)):
            ch, key = strokes[k % len(strokes)]
            search(k, ch, key)
            k += 1
        at(0, lambda: page().search.edit.clear())
        at(0, still("search-key"))
        run()

    def finish():
        result["moments"] = moments.summary()
        result["hud"] = {k: v for k, v in hud.report().items() if k in ("steps", "frames", "windows", "slow_frames",
                                                                         "late", "anim")}
        result["hud"]["late"].pop("explained", None)
        result["dpr"] = window.devicePixelRatioF()
        result["modules_found"] = sorted(page()._found or ()) if page() is not None else None
        result["extra"] = {"skipped": result["skipped"], "pages": result["pages"]}
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f)
        app.quit()

    QTimer.singleShot(60000 + a.rounds * 20000, finish)  # never longer than this
    window.show_first()
    QTimer.singleShot(1500, start)
    try:
        app.exec()
    finally:
        services.shutdown(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10, help="repetitions of each moment (>= 10 for a timed run)")
    ap.add_argument("--runs", type=int, default=1)
    bench_moments.add_arguments(ap)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.child:
        main_child(a)
    else:
        a.scales_list = bench_moments.parse_scales(a.scales)
        main_parent(a)


if __name__ == "__main__":
    main()
