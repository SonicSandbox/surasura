"""Python's lock in the window's process (A4 P-gil, A3; Mattias #8 "the window drags while background work runs"): how
late the window's thread gets to run while each background job of the window's process runs alone.

    python tests/qt/bench_gil.py [--files 20000] [--jobs idle,reader-full,...] [--reps 3] [--json OUT.json]

Not collected by pytest (no `test_` prefix). Source the a4 env first (a temp SURASURA_TEST_ROOT, APPDATA and
LOCALAPPDATA): the library is built there — a real store of `--files` items (`test_library_store_support.big_store`'s
shape: NOW 1 %, Soon 44.5 %, Goal the rest), its files on disk with real subtitle lines, a cover beside every third
show. A 1 ms precise `QTimer` on the window's thread (Windows' timer at 1 ms, the window process's own switch interval,
`shell.prepare_process`) records each tick's lateness — the gap past its 1 ms — while one job runs on a thread of its own,
as the window runs it:

  idle            nothing (the floor)
  reader-full     the library reader's first read and build (`moves.open_library`'s reader, a 20k feed)
  reader-change   one item marked watched (by another process), the reader's look and build
  needs-gather    *Needs you*'s gather (`app/qt/needs.py`'s `refresh` body, on the reader's view)
  cover-scan      the disk cover scan (`app/qt/covers._scan_library`, a writer that takes the covers and writes none)
  play-looks      ▶'s looks for Current's episodes (`play.look`)
  source-first    a source folder's first look (`sources.scan`) over `--files` / 4 new files (Kura's)
  source-again    the same folder looked at again, nothing changed (Kura's)
  add-insert      + Add's insert of `--files` / 4 files already copied (`Store.insert`, Kura's)

Printed: per job its time, the ticks' lateness p50 / p95 / max (ms), how many ticks were over 4 and 16 ms (and how
many of those a collection held), the full collections (`gc2`: how many, the longest, the thread that set them off) and a
2 ms window step's wall time p50 / p95 (Python's lock handed back and forth stretches it). The A/Bs:
`SURASURA_READER_GC_FREEZE=1` (the reader freezes the collector after each view, as the window process does since A4;
each rep's `reader-full` after the first is a new reader after a stop — a language switch's path) and
`SURASURA_BENCH_SWITCH_S` (another switch interval).
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

JOBS = ("idle", "reader-full", "reader-change", "needs-gather", "cover-scan", "play-looks", "source-first",
        "source-again", "add-insert")
LANGUAGE = "ja"


def _pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def _srt_lines():
    path = os.path.join(ROOT, "tests", "Test Resources", "ja", "placed_episode.srt")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _jpeg():
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QColor, QImage
    img = QImage(120, 170, QImage.Format.Format_RGB32)
    img.fill(QColor("#3b5b7a"))
    buf = QByteArray()
    b = QBuffer(buf)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, "JPG")
    return bytes(buf)


def build_library(files):
    """The store (big_store) and its files on disk, a cover beside every third show."""
    from tests import test_library_store_support as support
    t0 = time.perf_counter()
    store = support.big_store(LANGUAGE, files)
    data_dir, _uf = support.roots(LANGUAGE)
    text, jpg = _srt_lines(), _jpeg()
    rels = [r[0] for r in store.conn.execute("SELECT rel_path FROM items")]
    folders = set()
    for rel in rels:
        path = os.path.join(data_dir, *rel.split("/"))
        folder = os.path.dirname(path)
        if folder not in folders:
            os.makedirs(folder, exist_ok=True)
            folders.add(folder)
            if len(folders) % 3 == 0:
                with open(os.path.join(folder, "cover.jpg"), "wb") as f:
                    f.write(jpg)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    store.close()
    print(f"library: {files:,} items, {len(folders):,} folders, built in {time.perf_counter() - t0:.1f} s")
    return data_dir


def source_folder(n, name="source"):
    """A source folder of `n` episodes outside the library (12 a show), real subtitle lines."""
    from tests import test_library_store_support as support
    root = os.path.join(os.environ["SURASURA_TEST_ROOT"], name)
    shutil.rmtree(root, ignore_errors=True)
    text = _srt_lines()
    words = support.names(LANGUAGE)
    for i in range(n):
        show = f"{words[(i // 12) % len(words)]}{i // 12:04d}"
        folder = os.path.join(root, show)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{show} 第{i % 12 + 1:02d}話.srt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.utime(path, (time.time() - 3600, time.time() - 3600))     # settled: past the scan's half-written wait
    return root


class GcLog:
    """Python's collections: (start, end, generation, thread) — a full one holds Python's lock for its whole walk."""

    def __init__(self):
        import gc
        self.spans, self._at = [], {}
        gc.callbacks.append(self._cb)

    def _cb(self, phase, info):
        tid = threading.get_ident()
        if phase == "start":
            self._at[tid] = time.perf_counter()
        elif tid in self._at:
            self.spans.append((self._at.pop(tid), time.perf_counter(), info["generation"],
                               threading.current_thread().name))

    def since(self, t0):
        return [s for s in self.spans if s[0] >= t0]


class Probe:
    """The 1 ms tick on the window's thread: each tick's gap past 1 ms while `recording`."""

    def __init__(self):
        from PyQt6.QtCore import QTimer, Qt
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(1)
        self.timer.timeout.connect(self._tick)
        self.last = None
        self.late = None
        self.timer.start()
        # a window step: ~2 ms of the window's own Python every 16 ms, its wall time while a job runs (Python's lock
        # handed back and forth stretches it: a 2 ms step that takes 6 ms is a frame's budget gone)
        self.spins = self._calibrate()
        self.steps = None
        self.frame = QTimer()
        self.frame.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame.setInterval(16)
        self.frame.timeout.connect(self._step)
        self.frame.start()

    @staticmethod
    def _spin(n):
        x = 0
        for i in range(n):
            x += i & 7
        return x

    def _calibrate(self):
        n = 20000
        best = min(self._timed(n) for _ in range(5))
        return max(1000, int(n * 2.0 / max(best, 1e-6)))

    def _timed(self, n):
        t = time.perf_counter()
        self._spin(n)
        return (time.perf_counter() - t) * 1000.0

    def _step(self):
        ms = self._timed(self.spins)
        if self.steps is not None:
            self.steps.append(ms)

    def _tick(self):
        t = time.perf_counter()
        if self.late is not None and self.last is not None:
            self.late.append(max(0.0, (t - self.last) * 1000.0 - 1.0))
            self.at.append(t)
        self.last = t

    def run(self, job, *args):
        """`job(*args)` on a thread of its own, the window's loop turning meanwhile -> (seconds, [lateness ms], its
        answer)."""
        from PyQt6.QtCore import QEventLoop, QTimer
        out = {}

        def body():
            try:
                out["answer"] = job(*args)
            except BaseException as e:      # noqa: BLE001 - said, the bench goes on
                out["error"] = repr(e)
        loop = QEventLoop()
        watch = QTimer()
        watch.setInterval(20)
        self.last, self.late, self.at, self.steps = None, [], [], []
        t0 = self.t0 = time.perf_counter()
        th = threading.Thread(target=body, name="bench-job", daemon=True)
        watch.timeout.connect(lambda: (not th.is_alive()) and loop.quit())
        th.start()
        watch.start()
        loop.exec()
        watch.stop()
        took = time.perf_counter() - t0
        late, self.late = self.late, None
        self.last_steps, self.steps = self.steps, None
        if "error" in out:
            print(f"  (the job failed: {out['error']})")
        return took, late, out.get("answer")


def stats(name, took, late, at=(), gcs=(), steps=()):
    """The job's figures; `gc_*`: its full collections (any thread) and the ticks over 4 ms that a collection held."""
    full = [g for g in gcs if g[2] == 2]
    held = sum(1 for x, t in zip(late, at) if x > 4.0 and any(g[0] <= t and g[1] >= t - x / 1000.0 for g in gcs))
    return {"gc_full": len(full), "gc_full_max": round(max(((g[1] - g[0]) * 1000 for g in full), default=0.0), 1),
            "gc_threads": sorted({g[3] for g in full}), "over4_gc": held, "job": name, "s": round(took, 3),
            "ticks": len(late), "p50": round(_pct(late, 0.5), 2),
            "p95": round(_pct(late, 0.95), 2), "max": round(max(late) if late else 0.0, 2),
            "over4": sum(1 for x in late if x > 4.0), "over16": sum(1 for x in late if x > 16.0),
            "step_p50": round(_pct(steps, 0.5), 2), "step_p95": round(_pct(steps, 0.95), 2)}


class Bench:
    def __init__(self, files):
        from app import library_store as ls, path_utils
        self.files = files
        self.data_dir = path_utils.get_data_path(LANGUAGE)
        self.user_dir = path_utils.get_user_files_path(LANGUAGE)
        self.ls = ls
        self.reader = None
        self.view = None

    # --- jobs (each runs on the bench's job thread) ---------------------------------------------------------------- #
    def idle(self):
        time.sleep(2.0)

    def _new_reader(self):
        from app.services import moves
        _opener, numbers, reader = moves.open_library(LANGUAGE,
                                                      freeze_gc=os.environ.get("SURASURA_READER_GC_FREEZE") == "1")
        got = threading.Event()

        def seen(view):
            if not view.loading and view.rows:
                self.view = view
                got.set()
        reader.subscribe(seen)
        return reader, got

    def reader_full(self):
        if self.reader is not None:
            self.reader.stop()
        self.reader, got = self._new_reader()
        self.reader.start()
        got.wait(120)

    def reader_change(self, ids):
        got = threading.Event()
        before = self.reader.builds
        self.reader.subscribe(lambda v: self.reader.builds > before and got.set())
        _mark_elsewhere(ids)                            # another process's commit: the reader wakes on its poll
        got.wait(30)

    def needs_gather(self):
        from app.services import needs as service
        from app import settings_manager
        view, lang, data_dir = self.view, LANGUAGE, self.data_dir
        settings = {}
        connect = None
        rels = [e.rel_path for r in view.rows for e in r.episodes if e.rel_path] if view.mode == "store" else []
        roots = service.find_offline(lang, rels, data_dir) if rels else []
        store = self.ls.open_store(LANGUAGE, self.data_dir, self.user_dir, role="reader")
        try:
            asks = service.asks_of(store)
        finally:
            store.close()
        service.prune(lang, view, offline_roots=roots, connect=connect, asks=asks or None, gone_folders=())
        return service.entries(view, (), connect, service.read_seen(lang), roots, asks, service.read_answered(lang),
                               offers=service.read_offers(lang), cards_on=settings_manager.connect_on(settings),
                               miner_found=False, gone_folders=())

    def cover_scan(self):
        from app.qt import covers
        opener = self.ls.StoreOpener(LANGUAGE, self.data_dir, self.user_dir)
        opener.check()
        cancel = threading.Event()
        return covers._scan_library(opener, LANGUAGE, _TakingWriter(), cancel, self.data_dir)

    def play_looks(self):
        from app.services import play
        asks = {e.id: e.ask for r in self.view.rows for e in r.episodes if e.ask is not None}
        return len(play.look(LANGUAGE, asks))

    def source_first(self, root):
        from app import sources
        store = self.ls.open_store(LANGUAGE, self.data_dir, self.user_dir)
        try:
            rid = store.add_source(root)
            return sources.scan(store, LANGUAGE, rid, full=True).get("added")
        finally:
            store.close()

    def source_again(self):
        from app import sources
        store = self.ls.open_store(LANGUAGE, self.data_dir, self.user_dir)
        try:
            rid = store.conn.execute("SELECT id FROM roots ORDER BY id DESC LIMIT 1").fetchone()[0]
            return sources.scan(store, LANGUAGE, rid, full=True).get("found")
        finally:
            store.close()

    def add_insert(self, paths):
        store = self.ls.open_store(LANGUAGE, self.data_dir, self.user_dir)
        try:
            change = store.insert(paths, "now", "top")
            return len(getattr(change, "added", ()) or ())
        finally:
            store.close()


class _TakingWriter:
    """The scan's writer: idle, writes nothing, every cover taken (so each found cover costs the scan what it would)."""

    def can_write(self):
        return True

    def idle(self, timeout=None):
        return True

    def set_cover(self, *args, **kw):
        return 1


def _mark_elsewhere(ids):
    """One item marked watched by another process (the reader sees another program's commit)."""
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from app import library_store as ls, path_utils as p\n"
            "s = ls.open_store(%r, p.get_data_path(%r), p.get_user_files_path(%r))\n"
            "s.set_watched(%r, True); s.close()\n") % (ROOT, LANGUAGE, LANGUAGE, LANGUAGE, list(ids))
    subprocess.run([sys.executable, "-c", code], check=True, env=dict(os.environ))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=20000)
    ap.add_argument("--jobs", default=",".join(JOBS))
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args()
    if not os.environ.get("SURASURA_TEST_ROOT"):
        sys.exit("source the a4 env.sh first (a temp SURASURA_TEST_ROOT)")
    import tempfile
    run_root = tempfile.mkdtemp(prefix="gil-", dir=os.environ["SURASURA_TEST_ROOT"])     # each run its own library
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        os.environ[name] = os.path.join(run_root, name.lower())
        os.makedirs(os.environ[name], exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    from PyQt6.QtWidgets import QApplication
    app = QApplication([sys.argv[0]])
    from app.qt import shell
    shell.prepare_process()
    if os.environ.get("SURASURA_BENCH_SWITCH_S"):           # an A/B of Python's lock hand-over
        sys.setswitchinterval(float(os.environ["SURASURA_BENCH_SWITCH_S"]))
    jobs = [j for j in a.jobs.split(",") if j]
    build_library(a.files)
    bench = Bench(a.files)
    probe = Probe()
    gclog = GcLog()
    results = []

    def one(name, fn, *args):
        took, late, answer = probe.run(fn, *args)
        s = stats(name, took, late, probe.at, gclog.since(probe.t0), probe.last_steps)
        s["answer"] = answer if isinstance(answer, (int, type(None))) else len(answer) if hasattr(answer, "__len__") \
            else str(answer)[:40]
        results.append(s)
        print(f"  {name:<14} {s['s']:7.3f} s  ticks {s['ticks']:6d}  p50 {s['p50']:6.2f}  p95 {s['p95']:6.2f}  "
              f"max {s['max']:7.2f}  >4ms {s['over4']:4d} (gc {s['over4_gc']})  >16ms {s['over16']:3d}  "
              f"gc2 {s['gc_full']} max {s['gc_full_max']} ms {','.join(s['gc_threads'])}  "
              f"2ms-step p50 {s['step_p50']} p95 {s['step_p95']}  ({s['answer']})", flush=True)
    need_reader = any(j in jobs for j in ("reader-change", "needs-gather", "play-looks"))
    if need_reader and "reader-full" not in jobs:
        probe.run(bench.reader_full)
    store = bench.ls.open_store(LANGUAGE, bench.data_dir, bench.user_dir)
    now_ids = [r[0] for r in store.conn.execute("SELECT id FROM items WHERE tier='now' ORDER BY id")]
    store.close()
    src = source_folder(a.files // 4) if "source-first" in jobs else None
    add_paths = []
    if "add-insert" in jobs:                        # + Add's files, already copied into the library (its insert alone)
        lib_root = source_folder(a.files // 4, name=os.path.join("data", LANGUAGE, "HighPriority", "Added"))
        add_paths = [os.path.join(dp, f) for dp, _d, fs in os.walk(lib_root) for f in fs]
    for rep in range(a.reps):
        print(f"rep {rep + 1}/{a.reps}", flush=True)
        for name in jobs:
            if name == "idle":
                one(name, bench.idle)
            elif name == "reader-full":
                one(name, bench.reader_full)
            elif name == "reader-change":
                one(name, bench.reader_change, [now_ids[rep % len(now_ids)]])
            elif name == "needs-gather":
                one(name, bench.needs_gather)
            elif name == "cover-scan":
                one(name, bench.cover_scan)
            elif name == "play-looks":
                one(name, bench.play_looks)
            elif name == "source-first" and rep == 0:
                one(name, bench.source_first, src)
            elif name == "source-again":
                one(name, bench.source_again)
            elif name == "add-insert" and rep == 0:
                one(name, bench.add_insert, add_paths)
    if bench.reader is not None:
        bench.reader.stop()
    summary = {}
    for s in results:
        summary.setdefault(s["job"], []).append(s)
    print("\njob            runs   s(med)   p95(worst)  max(worst)  >4ms(sum)  >16ms(sum)")
    for name, runs in summary.items():
        print(f"{name:<14} {len(runs):4d} {statistics.median(r['s'] for r in runs):8.3f} "
              f"{max(r['p95'] for r in runs):10.2f} {max(r['max'] for r in runs):11.2f} "
              f"{sum(r['over4'] for r in runs):9d} {sum(r['over4_gc'] for r in runs):3d} "
              f"{sum(r['over16'] for r in runs):10d}  {sum(r['gc_full'] for r in runs):4d} "
              f"{max(r['gc_full_max'] for r in runs):6.1f}  {max(r['step_p95'] for r in runs):8.2f}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"files": a.files, "freeze": os.environ.get("SURASURA_READER_GC_FREEZE") == "1",
                       "runs": results}, f, ensure_ascii=False, indent=1)
    app.quit()


if __name__ == "__main__":
    main()
