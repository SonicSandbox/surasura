"""The picks at 20,000 files (alpha 4, P-picks item 5: Mattias's 2,500 items from 2.x's Goal, all wanted in Goal) —
on the window's thread, offscreen, on the stand-in store with a recording writer (the store's own write runs on the
writer's thread; what is timed here is the window's part only).

    python tests/qt/bench_picks.py [--files 20000] [--share 0.5] [--reps 5] [--language ja] [--json OUT.json]

Not collected by pytest. `--share` puts that share of the library in Current (the seed's default is ~13 %): at 0.5 a
20,000-file library holds a few thousand rows in Current and Soon — Mattias's 2,500 picks. Each step is timed as the
call itself, then the event-loop turns that paint it (`processEvents` until nothing is left: the frame it costs):
- **ctrl-a**: Ctrl+A on Current's list (every row picked; only the rows on screen repainted);
- **menu**: the picks' ⋯ built and shown;
- **send-goal**: *Goal* on every pick — the window's own view of the move (the rows gone, Goal's bar counting them)
  and the one command handed to the writer;
- **lift**: a press on a picked row dragged — every pick lifted as one card;
- **goal-ctrl-a** / **goal-menu**: Ctrl+A on Goal's sheet's tiles, its picks' ⋯.
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _drain(qapp):
    """The turns of the event loop after a step (its paint): their longest, in ms."""
    longest = 0.0
    for _ in range(20):
        t = time.perf_counter()
        qapp.processEvents()
        longest = max(longest, (time.perf_counter() - t) * 1000)
    return longest


def timed(qapp, fn):
    """-> (the call's ms, the longest turn after it in ms, its answer)."""
    t = time.perf_counter()
    out = fn()
    call = (time.perf_counter() - t) * 1000
    return call, _drain(qapp), out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", type=int, default=20000)
    ap.add_argument("--share", type=float, default=0.5)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--language", default="ja")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication
    from app.qt import drag, shell, style
    from app.services import library_reader
    from tests.fixtures import window_seed
    from tests.qt.conftest import wait_until
    from tests.qt.test_picks import PicksWriter
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    style.apply(qapp, "night", "M", args.language)
    if args.language != "ja":
        from app import path_utils
        with open(path_utils.get_user_file("settings.json"), "w", encoding="utf-8") as f:
            json.dump({"target_language": args.language}, f)
    seed = window_seed.build(files=args.files, language=args.language, current_share=args.share)
    writer = PicksWriter(seed.library, apply=False)
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02, coalesce=True)
    services = shell.Services(library=reader, writer=writer)
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading, 60)
    _drain(qapp)
    lst = page.list
    n_rows = len(page.view_model.rows)
    at = win.mapToGlobal(QPoint(300, 300))
    out = {"files": args.files, "rows": n_rows, "steps": {}}

    def note(name, call, after, extra=None):
        out["steps"].setdefault(name, []).append({"call": round(call, 2), "after": round(after, 2), **(extra or {})})

    for _rep in range(args.reps):
        lst.clear_picks()
        _drain(qapp)
        call, after, _ = timed(qapp, lst.pick_all)
        note("ctrl-a", call, after, {"picked": len(lst.picked_rows)})
        row = next(r for r in page.view_model.rows if r.key in lst.picked_rows)
        call, after, m = timed(qapp, lambda: win.items.picks_menu(row, at))
        note("menu", call, after)
        m.close()
        _drain(qapp)
        call, after, _ = timed(qapp, lambda: drag.any_split_first(page.view_model.rows, lst.picked_rows))
        note("split-rule", call, after)
        idx = next(i for i, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) in lst.picked_rows)
        press = (idx, "title", None, QPoint(10, 10), lst.model().entries[idx][1].key)
        call, after, _ = timed(qapp, lambda: win.moves.begin(press, at))
        note("lift", call, after, {"many": getattr(win.moves.running, "many", 0)})
        win.moves.cancel()
        _drain(qapp)
    # *Goal* on every pick, once (it takes the rows out of the window's view)
    lst.pick_all()
    _drain(qapp)
    picked = len(lst.picked_rows)
    writer.calls.clear()
    call, after, _ = timed(qapp, lambda: win.items.send_picks("goal"))
    note("send-goal", call, after, {"picked": picked, "commands": len(writer.calls),
                                    "ids": len(writer.calls[0][1]) if writer.calls else 0})
    # Goal's sheet: its tiles picked, their ⋯
    sheet = win.goal_sheet
    sheet.open()
    assert wait_until(sheet.isVisible, 5)
    _drain(qapp)
    for _rep in range(args.reps):
        sheet.clear_picks()
        _drain(qapp)
        call, after, _ = timed(qapp, sheet.pick_all)
        note("goal-ctrl-a", call, after, {"picked": len(sheet.picks)})
        call, after, m = timed(qapp, lambda: sheet.menu(sheet.order[0]))
        note("goal-menu", call, after)
        m.close()
        _drain(qapp)
    summary = {name: {"call_median": statistics.median(s["call"] for s in steps),
                      "call_max": max(s["call"] for s in steps),
                      "after_max": max(s["after"] for s in steps),
                      **{k: v for k, v in steps[-1].items() if k not in ("call", "after")}}
               for name, steps in out["steps"].items()}
    out["summary"] = summary
    print(f"files {args.files}, Current rows {n_rows}, goal tiles {len(sheet.order)}")
    for name, s in summary.items():
        print(f"  {name:12s} call median {s['call_median']:7.2f} ms  max {s['call_max']:7.2f}  "
              f"longest turn after {s['after_max']:6.2f}  {({k: v for k, v in s.items() if 'call' not in k and 'after' not in k})}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
    win.close()
    services.shutdown(0.5)


if __name__ == "__main__":
    main()
