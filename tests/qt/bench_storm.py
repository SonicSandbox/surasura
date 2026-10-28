"""The window while the library grows under it (alpha 4, A4: "the window drags while background work runs") — a
synthetic library open in the window, then a + Add / a source look / an import committing in the store's normal batches
(≤ 200 files a command, `library_store._store_take_in`), and what each page did meanwhile.

    python tests/qt/bench_storm.py [--files 20000] [--more 20000] [--batch 200] [--gap 0.05] [--language ja]
                                   [--json OUT.json]

Not collected by pytest (no `test_` prefix); `tests/qt/test_storm.py` runs it small and asserts the counts don't grow
with the library. Offscreen, in this process, on the stand-in store (`tests/fixtures/window_seed.py`); the reader as the
window makes it, waking on its poll (the stand-in has no bell). Each batch is one commit from a thread of its own (as
the scan's own worker commits): most files a new show landing in New arrivals, some a show's next episodes landing in
its run in Current (a look's after-show rule: the row grows), some a new show at Soon's end (a row added).

Counted while the batches land, until the window shows the reader's last view (`Meter`):
- **views**: the views the reader published; **shown**: the views the window took in (`show_library`);
- per page (Current, Finished, Needs you, the Goal dock, New arrivals' tray): its `set_view` calls, the rows it took as
  changed, the model's resets, rows inserted / removed, rows laid out (the delegate's `sizeHint` calls), paint events
  on its list and rows painted / drawn afresh;
- the window thread's longest step (each turn of its event loop, timed around `processEvents`: what `app/qt/hud.py`'s
  *awake* → *aboutToBlock* measures in the running window) and the steps over 4 ms.
"""
import argparse
import json
import math
import os
import random
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BATCH = 200                     # the scan hands the store at most this many files a command (`_store_take_in`)
GAP_S = 0.05                    # between two batches' commits (a fast disk's look)
PAGES = ("current", "finished", "needs")


# --- the storm: what a + Add / a look commits --------------------------------------------------------------------- #
def storm_batches(seed, more, batch=BATCH, rng_seed=11):
    """`more` new files as the store's commands would land them, `batch` a command -> [(items, works)]. 70 % a new show
    into New arrivals, 20 % a show's next episodes into its run in Current (after its last one: the row grows), 10 % a
    new show at Soon's end (a row added); every title from the seed's own vocabulary."""
    rng = random.Random(rng_seed)
    lib = seed.library
    items = lib.items()
    next_id = max(r["id"] for r in items) + 1
    next_piece = max((r.get("piece_id") or 0) for r in items) + 1
    next_work = max(w["id"] for w in seed.works) + 1
    words = sorted(seed.vocabulary)
    by_tier = {}
    for r in items:
        by_tier.setdefault(r["tier"], []).append(r)
    for rows in by_tier.values():
        rows.sort(key=lambda r: (r["ord"] or 0.0, r["id"]))
    soon_end = max((r["ord"] for r in by_tier.get("soon", ())), default=0.0)
    arrivals_end = max((r["ord"] for r in by_tier.get("arrivals", ())), default=0.0)
    # Current's runs (a piece's last file and the next item's ord): a look adds a show's next episodes between them
    current = by_tier.get("now", []) + by_tier.get("soon", [])
    runs = []
    for k, r in enumerate(current[:-1]):
        nxt = current[k + 1]
        if r.get("piece_id") != nxt.get("piece_id") and r["tier"] == nxt["tier"] and r.get("work_id"):
            runs.append([r, nxt["ord"]])
    out = []
    left = more
    while left > 0:
        n = min(batch, left)
        left -= n
        rows, works = [], []
        while len(rows) < n:
            kind = rng.random()
            take = min(n - len(rows), rng.randint(6, 26))
            if kind < 0.2 and runs:
                run = runs[rng.randrange(len(runs))]
                last, ceiling = run
                if ceiling - last["ord"] < 1e-3:              # no room left between the two (floats run out)
                    runs.remove(run)
                    continue
                for _ in range(take):
                    at = last["ord"] + (ceiling - last["ord"]) / 64.0     # after the show's last, before the next
                    row = dict(last, id=next_id, ord=at, rel_path=f"{last['rel_path']}.{next_id}.srt",
                               title=f"{words[rng.randrange(len(words))]} - {next_id}.srt", watched=0, mined_at=None,
                               mine_asked=None, added_at="2026-10-27T10:00:00Z", feed_in=None)
                    next_id += 1
                    rows.append(row)
                    run[0] = last = row
                continue
            title = f"{words[rng.randrange(len(words))]} {next_work}"
            tier = "arrivals" if kind < 0.9 else "soon"
            folder = ("HighPriority/Hato/" if tier == "arrivals" else "LowPriority/") + title
            works.append({"id": next_work, "title": title, "title_by_user": 0, "titles": "[]", "folder_key": folder,
                          "media_type": "anime", "cover_source": "generated", "cover_locked": 0})
            for k in range(take):
                if tier == "arrivals":
                    arrivals_end += 1024.0
                    at = arrivals_end
                else:
                    soon_end += 1024.0
                    at = soon_end
                rows.append({"id": next_id, "tier": tier, "ord": at, "rel_path": f"{folder}/{title} - {k + 1:02d}.srt",
                             "title": f"{title} - {k + 1:02d}.srt", "parent_folder": title,
                             "source_type": "subtitle", "availability": "available", "work_id": next_work,
                             "piece_id": next_piece, "watched": 0, "mined_at": None, "pinned": None,
                             "mine_asked": None, "graduated_at": None, "in_learning_order": 1,
                             "added_at": "2026-10-27T10:00:00Z"})
                next_id += 1
            next_work += 1
            next_piece += 1
        out.append((rows, works))
    return out


def commit_storm(seed, batches, gap_s=GAP_S, done=None):
    """The batches committed one by one from a thread of its own (the scan's worker), `gap_s` apart. -> the thread."""
    def run():
        for rows, works in batches:
            seed.library.commit(items=rows, works=works, order=True)
            time.sleep(gap_s)
        if done is not None:
            done.set()
    t = threading.Thread(target=run, name="storm-commits", daemon=True)
    t.start()
    return t


# --- what the window did ------------------------------------------------------------------------------------------- #
class Meter:
    """Counts on the window while it is on (`start` / `stop`); `report()` the figures."""

    def __init__(self, win):
        self.win = win
        self.reader = win.services.library
        self.on = False
        self.views = 0
        self.shown = 0
        self.show_ms = 0.0
        self.pages = {}
        self.steps = []                 # each turn of the window's loop while on (`pump`), ms
        self._undo = []

    def _page(self, name):
        return self.pages.setdefault(name, {"set_view": 0, "ms": 0.0, "changed": 0, "resets": 0, "inserted": 0, "removed": 0,
                                            "laid_out": 0, "paint_events": 0, "row_paints": 0, "row_renders": 0})

    def start(self):
        from PyQt6.QtCore import QEvent, QObject
        from app.qt import rows as qrows
        win = self.win
        meter = self

        def counted_view(view):
            if meter.on:
                meter.views += 1
        self.reader.subscribe(counted_view)
        self._undo.append(lambda: self.reader._subscribers.remove(counted_view))
        show = win.show_library

        def show_library(view):
            t = time.perf_counter()
            out = show(view)
            if meter.on:
                meter.shown += 1
                meter.show_ms += (time.perf_counter() - t) * 1000
            return out
        try:                                          # the bridge holds the bound method: the slot swapped in place
            win.library_bridge.library_changed.disconnect(show)
        except (TypeError, RuntimeError):
            pass
        win.library_bridge.library_changed.connect(show_library)

        def undo_show():
            win.library_bridge.library_changed.disconnect(show_library)
            win.library_bridge.library_changed.connect(win.show_library)
        self._undo.append(undo_show)
        lists = {}
        for name in PAGES:
            page = win.page_widgets.get(name)
            if page is None or not hasattr(page, "set_view"):
                continue
            stats = self._page(name)
            original = page.set_view

            def set_view(view, _orig=original, _stats=stats, _page=page):
                t = time.perf_counter()
                how = _orig(view)
                if meter.on:
                    _stats["ms"] += (time.perf_counter() - t) * 1000
                    _stats["set_view"] += 1
                    model = _page.list.model()
                    _stats["changed"] += len(model.changed) if how != "reset" else model.rowCount()
                return how
            page.set_view = set_view
            self._undo.append(lambda _p=page: _p.__dict__.pop("set_view", None))
            model = page.list.model()
            for signal, key in ((model.modelAboutToBeReset, "resets"), (model.rowsInserted, "inserted"),
                                (model.rowsRemoved, "removed")):
                if key == "resets":
                    slot = (lambda _s=stats: meter.on and _s.__setitem__("resets", _s["resets"] + 1))
                else:
                    slot = (lambda _parent, first, last, _s=stats, _k=key:
                            meter.on and _s.__setitem__(_k, _s[_k] + last - first + 1))
                signal.connect(slot)
                self._undo.append(lambda _sig=signal, _slot=slot: _sig.disconnect(_slot))
            lists[page.list.viewport()] = stats
            stats["_base"] = (page.list.delegate.paints, page.list.delegate.renders)
            stats["_delegate"] = page.list.delegate

        class Paints(QObject):
            def eventFilter(self, obj, ev):
                if meter.on and ev.type() == QEvent.Type.Paint:
                    s = lists.get(obj)
                    if s is not None:
                        s["paint_events"] += 1
                return False
        self._paints = Paints()
        for vp in lists:
            vp.installEventFilter(self._paints)
        size_hint = qrows.RowDelegate.sizeHint
        by_delegate = {s["_delegate"]: s for s in lists.values()}

        def counted_hint(delegate, option, index):
            s = by_delegate.get(delegate)
            if s is not None and meter.on:
                s["laid_out"] += 1
            return size_hint(delegate, option, index)
        qrows.RowDelegate.sizeHint = counted_hint
        self._undo.append(lambda: setattr(qrows.RowDelegate, "sizeHint", size_hint))
        dock = getattr(win, "dock", None)
        if dock is not None:
            stats = self._page("goal-dock")
            dock_view = dock.set_view

            def dock_set_view(view, _orig=dock_view, _stats=stats):
                t = time.perf_counter()
                out = _orig(view)
                if meter.on:
                    _stats["set_view"] += 1
                    _stats["ms"] += (time.perf_counter() - t) * 1000
                return out
            dock.set_view = dock_set_view
            self._undo.append(lambda: dock.__dict__.pop("set_view", None))
        tray = getattr(win, "arrivals_tray", None)
        if tray is not None and hasattr(tray, "set_groups"):
            stats = self._page("arrivals-tray")
            groups = tray.set_groups

            def set_groups(g, _orig=groups, _stats=stats):
                t = time.perf_counter()
                out = _orig(g)
                if meter.on:
                    _stats["set_view"] += 1
                    _stats["ms"] += (time.perf_counter() - t) * 1000
                return out
            tray.set_groups = set_groups
            self._undo.append(lambda: tray.__dict__.pop("set_groups", None))
        import gc
        collected = self.collections = []             # Python's full collections (any thread): (ms, thread)

        def watch_gc(phase, info, _t=[0.0]):
            if not meter.on or info.get("generation") != 2:
                return
            if phase == "start":
                _t[0] = time.perf_counter()
            else:
                collected.append(((time.perf_counter() - _t[0]) * 1000, threading.current_thread().name))
        gc.callbacks.append(watch_gc)
        self._undo.append(lambda: gc.callbacks.remove(watch_gc))
        self._lists = lists
        self.on = True
        self.t0 = time.perf_counter()
        return self

    def pump(self):
        """One turn of the window's event loop, timed: a step of the window's thread (what the HUD's awake ->
        aboutToBlock measures; the loop here is the caller's, so the turn is timed around `processEvents`)."""
        from PyQt6.QtWidgets import QApplication
        t = time.perf_counter()
        QApplication.processEvents()
        if self.on:
            self.steps.append((time.perf_counter() - t) * 1000)

    def stop(self):
        self.on = False
        self.seconds = time.perf_counter() - self.t0
        for s in self._lists.values():
            d = s["_delegate"]
            s["row_paints"] = d.paints - s["_base"][0]
            s["row_renders"] = d.renders - s["_base"][1]
        for vp in self._lists:
            vp.removeEventFilter(self._paints)
        for undo in reversed(self._undo):
            try:
                undo()
            except (TypeError, RuntimeError, ValueError):
                pass
        self._undo = []

    def report(self):
        pages = {k: {n: (round(v, 1) if isinstance(v, float) else v) for n, v in s.items() if not n.startswith("_")}
                 for k, s in self.pages.items()}
        steps = sorted(self.steps)
        return {"seconds": round(self.seconds, 2), "views": self.views, "shown": self.shown,
                "show_library_ms": round(self.show_ms, 1),
                "views_bound": math.ceil(self.seconds * 4) + 1,
                "full_collections": len(self.collections),
                "full_collection_max_ms": round(max((ms for ms, _t in self.collections), default=0.0), 1),
                "longest_step_ms": round(steps[-1], 2) if steps else 0.0,
                "steps_over_4ms": sum(1 for s in steps if s > 4.0),
                "worst_steps_ms": [round(x, 1) for x in steps[-8:][::-1]],
                "step_p95_ms": round(steps[min(len(steps) - 1, int(round(0.95 * (len(steps) - 1))))], 2) if steps
                else 0.0, "pages": pages}


# --- one run ------------------------------------------------------------------------------------------------------ #
def open_window(qapp, seed, size=(1280, 800), poll=0.02, coalesce=True, freeze_gc=False):
    """The window on the seed, as `tests/qt/test_current.open_on` opens it (the reader coalescing as the window's
    does, `coalesce`; `freeze_gc`: the collector frozen as the window process's reader does — the bench's own run, never
    a test's process), once its live rows are in."""
    from PyQt6.QtWidgets import QApplication
    from app.qt import shell
    from app.services import library_reader
    from tests.qt.conftest import wait_until
    if seed.language != "ja":                     # the window shows its own language's views only (W3.2 P0): the
        from app import path_utils                # test root's settings name it (never the developer's own)
        with open(path_utils.get_user_file("settings.json"), "w", encoding="utf-8") as f:
            json.dump({"target_language": seed.language}, f)
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=poll, freeze_gc=freeze_gc, coalesce=coalesce)
    services = shell.Services(library=reader)
    win = shell.open_window(qapp, services)
    win.resize(*size)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading, 30)
    for _ in range(50):
        QApplication.processEvents()
    return win, services


def run(win, seed, more, batch=BATCH, gap_s=GAP_S, settle_s=60.0):
    """The storm while `win` is open on `seed` -> the meter's report (`Meter.report`), once the window shows the
    reader's last view."""
    batches = storm_batches(seed, more, batch)
    reader = win.services.library
    page = win.page_widgets["current"]
    meter = Meter(win).start()
    done = threading.Event()
    commit_storm(seed, batches, gap_s, done)
    expect = sum(len(rows) for rows, _w in batches)
    target = len(seed.library.items()) + expect

    def landed():
        view = reader.view()
        return done.is_set() and view is not None and page.view_model is view and \
            reader._data_version == seed.library._data_version and not getattr(reader, "_view_owed", False)
    deadline = time.monotonic() + settle_s
    ok = False
    try:
        while time.monotonic() < deadline:
            meter.pump()
            if landed():
                ok = True
                break
            time.sleep(0.002)               # the loop's wait: the other threads run
        for _ in range(20):
            meter.pump()
    finally:
        meter.stop()
    out = meter.report()
    out.update(files=seed.files, more=expect, batches=len(batches), batch=batch, gap_s=gap_s, settled=bool(ok),
               store_files=target)
    return out


def table(rows):
    """A markdown table of runs' reports (label, report)."""
    head = ("| run | s | views | shown | show ms | longest step ms | steps > 4 ms | page | set_view | ms | changed | resets "
            "| inserted | removed | laid out | paint events | rows painted | drawn afresh |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for label, r in rows:
        first = True
        for name, s in r["pages"].items():
            lead = (f"| {label} | {r['seconds']} | {r['views']} | {r['shown']} | {r['show_library_ms']} | "
                    f"{r['longest_step_ms']} | {r['steps_over_4ms']} ") if first else "| | | | | | | "
            first = False
            lines.append(lead + f"| {name} | {s['set_view']} | {s['ms']} | {s.get('changed', '')} | "
                         f"{s.get('resets', '')} | {s.get('inserted', '')} | {s.get('removed', '')} | "
                         f"{s.get('laid_out', '')} | {s.get('paint_events', '')} | {s.get('row_paints', '')} | "
                         f"{s.get('row_renders', '')} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", type=int, default=20000)
    ap.add_argument("--more", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--gap", type=float, default=GAP_S)
    ap.add_argument("--language", default="ja")
    ap.add_argument("--json")
    ap.add_argument("--no-coalesce", action="store_true", help="the reader builds a view for every change (A/B)")
    ap.add_argument("--no-splice", action="store_true", help="a row added or gone resets the list (A/B: before a4)")
    ap.add_argument("--no-tray", action="store_true",
                    help="New arrivals' tray takes no rows (its own rebuild apart: P-arrivals' item 2)")
    ap.add_argument("--freeze-once", action="store_true",
                    help="gc.freeze() once the window shows its first live view (the collector's A/B)")
    ap.add_argument("--profile", help="a cProfile of the window's thread during the storm, written here")
    args = ap.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from app.qt import style
    from tests.fixtures import window_seed
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    from app.qt import shell
    shell.prepare_process()                       # fix3 (the verifier's D2): the window process's own settings — its
    style.apply(qapp, "night", "M", args.language)  # 1 ms switch interval; the reader below freezes the collector
    if args.no_splice:
        from app.qt import rows
        rows.RowsModel._splice = lambda _self, _keys, _entries: None
    seed = window_seed.build(files=args.files, language=args.language)
    win, services = open_window(qapp, seed, coalesce=not args.no_coalesce, freeze_gc=True)   # (as the window's)
    if args.no_tray and getattr(win, "arrivals_tray", None) is not None:
        win.arrivals_tray.set_groups = lambda groups: False
    if args.freeze_once:
        import gc
        gc.collect()
        gc.freeze()
    prof = None
    if args.profile:
        import cProfile
        prof = cProfile.Profile()
        prof.enable()
    try:
        out = run(win, seed, args.more, args.batch, args.gap)
    finally:
        if prof is not None:
            prof.disable()
            prof.dump_stats(args.profile)
        win.close()
        services.shutdown(0.5)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(table([(f"{args.files} + {args.more}", out)]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    main()
