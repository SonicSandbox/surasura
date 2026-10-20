"""The drag's moments and the other moves on this machine (W3.1a; ORDER W3.1a: a frame <= 8 ms at p95 and never over
16 ms, no GUI-thread step over 4 ms, drop -> numbers <= 50 ms; RP-6) — and, since M4.1 row 2, every moment of the
RUNBOOK's list that a move, an arrival or a toast makes, judged against the bar on this desktop (`bench_moments.BAR`).

    python tests/qt/bench_drag.py [--files 20000] [--runs 2] [--cycles 10] [--scales 100,125,150,175,200,250]
                                  [--reduced] [--json OUT.json]

Not collected by pytest (no `test_` prefix). A timed run: start it through `locks/with-lock.sh timed …` from the copy.

The parent builds the window's synthetic seed (`bench_scroll.save_seed`) and a Generate-shaped plan for it; each scale
× run is a child process on Windows' own platform, shown without taking the keyboard, in a fresh temp
`SURASURA_TEST_ROOT` with its own APPDATA / LOCALAPPDATA (`bench_moments.scaled_runs`), at the TRUE scale (each run
records its `dpr`). Motion runs (not frozen; `--reduced`: `app_motion` = reduced in the run's own settings). The
child's store is the stand-in, with the real `moves.Numbers` over the plan and a writer that, like the real one, works
out the numbers on its own thread before it writes (into the stand-in). The HUD watches every window's frames (the
main window, the drag's ghost, the ⋯ menu) and every GUI-thread step after the first paint while, `--cycles` times
each (>= 10 for a timed run), the moments run through the window's own paths:
  - **a drag** (the events `tests/qt/test_drag.py` sends): `pickup` (a press on a row's title, the 6 px that lift it,
    the hand drifting), `slide` (~7 rows down at 60 Hz, the rows part), `autoscroll` (1.5 s at the list's bottom edge,
    then back up), `drop` (the release, the glide home, the numbers);
  - **a drop across the top-20 line** (`drop-top20`) and **across the Soon line** (`drop-soon`) — R3-S6, the list's
    reset — a row dragged two rows over the line, down and up in turn;
  - **a move by the item menu**: `menu-open` (⋯'s popup), then its *Up next* / *Soon* / *Goal* action triggered as a
    click does (the menu hidden, the action's own `triggered`): `menu-top`, `menu-soon`, `menu-goal` — the rows slide,
    the wells rise;
  - **a move by key**: Alt+↑ (`key-up`) and Alt+↓ (`key-down`) on the current row (`RowsView.keyPressEvent`);
  - **the arrival moment** (`arrival`): a show never shown before lands in New arrivals (the store write the reader
    feeds as an arrival); the inset's covers part, the new one drops in, the count lifts (no toast exists: none added);
  - **the finish toasts**: `toast-done-all` — the last unwatched episode's Done (`done_requested`, drag.py's
    `DONE_ALL`); `toast-finished` — New arrivals' *Finished* (the tray's `act`: the Finished choice toast,
    arrivals.py); `toast-connect` — Connect's notice toast (`ShellWindow._show_chores`, its one line; Connect not run).
After each moment's last repetition the clock's wake-ups are counted once it is still. Timed beside, never judged
here: drop / move -> numbers (the moved row's *N new* in the window) and -> saved (the writer's `on_saved`; the
stand-in's — the real store's is the timed hold's own script, IK-7).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.qt import bench_moments                                    # noqa: E402

DRAG = ("pickup", "slide", "autoscroll", "drop")


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


def main_parent(a):
    import json
    from tests.qt.bench_scroll import save_seed
    work = tempfile.mkdtemp(prefix="surasura-bench-drag-seed-")
    seed_path, plan_path = os.path.join(work, "seed.pkl"), os.path.join(work, "plan.json.gz")
    t = time.perf_counter()
    files = save_seed(a.files, None, seed_path)
    save_plan(seed_path, plan_path)
    print(f"seed + plan: {files} files ({time.perf_counter() - t:.1f} s); this desktop's own scale "
          f"{bench_moments.system_scale()}", flush=True)

    def one_run(scale, root, env, i):
        env["SURASURA_ROW_PIXMAPS"] = "1"
        out_path = os.path.join(os.path.dirname(root), "result.json")
        cmd = [sys.executable, os.path.abspath(__file__), "--child", seed_path, "--plan", plan_path, "--out", out_path,
               "--cycles", str(a.cycles)]
        proc = subprocess.run(cmd, env=env, cwd=ROOT, timeout=1800, check=False, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if not os.path.exists(out_path):
            return {"error": f"no result (exit {proc.returncode}): {proc.stderr[-1500:]}"}
        with open(out_path, encoding="utf-8") as f:
            r = json.load(f)
        if proc.returncode:
            r["exit"] = proc.returncode
        if proc.stderr.strip():                          # (M4.1 A5) kept whatever the exit: a raise in a slot isn't one
            r.setdefault("extra", {})["stderr"] = proc.stderr[-1500:]
        return r
    bench_moments.scaled_runs("bench_drag", a.scales_list, a.runs, a.reduced, one_run, a.out,
                              meta={"files": files, "cycles": a.cycles})


# --- the child's stand-in writer (out here so its rules are tested: tests/qt/test_bench_drag.py) --------------------- #
class StandinWriter:
    """The window's writer as the moves call it, over the stand-in library and the real `moves.Numbers`: each command
    worked out and written on a thread of its own, where `moves.Writer` only queues on the caller's (M4.1 A3: a nudge
    worked out where it was called copied the whole library on the GUI thread) — the numbers worked out before the
    write (as `moves.Writer._numbers_move`), then the change written into the stand-in and its callbacks on that thread.
    Each command's time to `on_saved` noted on the moment it came from (`moments`, set once the HUD is up)."""
    from app.qt.strings import MOVE_WORDS as words

    def __init__(self, library, numbers):
        self.library, self.numbers, self.moments = library, numbers, None
        self.on_saved = self.on_saving = self.on_reread = self.on_note = self.on_undone = None
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

    def _run(self, ids, label, write):
        self._pending += 1
        t0 = time.perf_counter()
        moments = self.moments
        name = moments.reps[-1][0] if moments is not None and moments.reps else None

        def run():
            write()
            self._pending -= 1
            if name is not None:
                moments.note(name, "saved_ms", round((time.perf_counter() - t0) * 1000, 2))
            self.on_saved(_Change(ids), label)
        threading.Thread(target=run, daemon=True).start()
        return 1

    def _move_now(self, ids, tier, before_id=None, after_id=None, piece_id=None):
        """(The writer's thread.) The numbers, then the write."""
        self.numbers.after_move(ids, tier, before_id=before_id, after_id=after_id)
        _place(self.library, ids, tier, before_id, after_id, piece_id)

    def move(self, ids, tier, before_id=None, after_id=None, near=(), label=None, end=False):
        return self._run(ids, label, lambda: self._move_now(ids, tier, before_id, after_id))

    def nudge(self, ids, direction, label=None):
        """One place up or down in its tier (the store's `nudge`), worked out on the writer's thread: nothing at the
        tier's end."""
        def write():
            to = nudge_anchor(self.library, ids, direction)
            if to is not None:
                self._move_now(ids, *to)
        return self._run(ids, label, write)

    def join(self, piece_ids, label=None, ahead=False):
        """`Store.join` (W3.2 Q8: a drop on another part of the same title, `item_menu.join`): the other parts' items
        into the first part's piece and tier, after its last item (`ahead`: before its first). (M4.1 A5: the stand-in
        had no `join`, and such a drop raised in the child.)"""
        first, ids = piece_ids[0], []

        def write():
            lib = self.library
            with lib._lock:                              # (the writer's thread; a join is rare)
                parts = sorted((r["ord"], r["id"], r["piece_id"], r["tier"]) for r in lib._items.values()
                               if r["piece_id"] in piece_ids)
            target = [k for k in parts if k[2] == first]
            moving = [k[1] for k in parts if k[2] != first]
            if not target or not moving:
                return
            ids.extend([k[1] for k in target] + moving)
            before_id, after_id = (target[0][1], None) if ahead else (None, target[-1][1])
            self._move_now(moving, target[0][3], before_id, after_id, piece_id=first)
        return self._run(ids, label, write)

    def set_watched(self, ids, on=True, label=None):
        return self._run(ids, label, lambda: self.library.commit(
            items=[{"id": i, "watched": int(bool(on))} for i in ids]))

    def place(self, ids, where, label=None):
        if where == "finished":
            return self._run(ids, label, lambda: self.library.commit(
                items=[{"id": i, "tier": "graduated", "graduated_at": "2026-10-16T21:00:00Z"} for i in ids],
                order=True))
        return self.move(ids, "soon" if where == "soon" else "goal" if where == "goal" else "now", label=label)

    def _nothing(self, *a, **k):
        return None

    set_finished = insert_at = undo = _nothing


class _Change:
    def __init__(self, ids):
        self.ids, self.kind = list(ids), "move"


def nudge_anchor(library, ids, direction):
    """(tier, before_id, after_id) for `ids` one place up or down in their tier: before the run (piece) of the row
    above, or after the run of the row below; None at the tier's end. Only the tier's keys read."""
    tier = library._items[ids[0]]["tier"]
    line = sorted(library.tier_keys(tier))               # (ord, id, piece_id): the tier's order
    mine = set(ids)
    at = [k for k, key in enumerate(line) if key[1] in mine]
    if direction == "up":
        k = at[0] - 1
        if k < 0:
            return None
        piece = line[k][2]
        while k > 0 and line[k - 1][2] == piece:
            k -= 1
        return tier, line[k][1], None
    k = at[-1] + 1
    if k >= len(line):
        return None
    piece = line[k][2]
    while k + 1 < len(line) and line[k + 1][2] == piece:
        k += 1
    return tier, None, line[k][1]


def _place(library, ids, tier, before_id, after_id, piece_id=None):
    """`ids` written into `tier` before `before_id`, after `after_id`, or at its top (an anchor not in the tier: its
    top), spaced between their neighbours' `ord`s; `piece_id` too when given. Only the tier's keys read (M4.1 A4: every
    item was copied and the tier sorted, 6–60 ms a move at 20,000 files, holding Python's lock under the window)."""
    mine = set(ids)
    rest = [(o, i) for o, i, _p in library.tier_keys(tier) if i not in mine]
    anchor = before_id if before_id is not None else after_id
    at = next((k for k in rest if k[1] == anchor), None) if anchor is not None else None
    if at is not None and before_id is not None:
        hi = at[0]
        below = max((k for k in rest if k < at), default=None)
        lo = below[0] if below is not None else hi - 1024
    elif at is not None:
        lo = at[0]
        above = min((k for k in rest if k > at), default=None)
        hi = above[0] if above is not None else lo + 1024
    else:
        hi = min(rest)[0] if rest else 1024.0
        lo = hi - 1024
    step = (hi - lo) / (len(ids) + 1)
    extra = {} if piece_id is None else {"piece_id": piece_id}
    library.commit(items=[dict(extra, id=i, tier=tier, ord=lo + step * (n + 1)) for n, i in enumerate(ids)],
                   order=True)


def done_candidates(rows_, used):
    """toast-done-all's rows: a Current row below Up Next — NOW or Soon: a Done finishes any Current row (`drag.py`'s
    `done` has no tier rule; M4.1 A2: NOW's rows ran out after the menu moves, and the moment ran with no toast and no
    skip noted) — of 2+ episodes, not all watched, Finished offered for it, not a split's first part, not used yet."""
    from app.qt import drag as drag_module
    return [r for r in rows_[1:] if r.tier in ("now", "soon") and r.key not in used and len(r.episodes) >= 2
            and drag_module.finishes(r) and not drag_module.split_first(rows_, r)
            and not all(e.watched for e in r.episodes)]


def arrival_template(library):
    """The arrival moment's template, read once before the moments (M4.1 A3: each arrival's `max` over every item was
    the whole of the moment at 20,000 files): (a row to copy, its work, the first new item id, the first new work
    id)."""
    items = library.items()
    temp = next((r for r in items if r["tier"] == "arrivals"), None) or next(r for r in items if r["tier"] == "now")
    work = dict(library._works[temp["work_id"]]) if temp.get("work_id") in library._works else None
    return temp, work, max(r["id"] for r in items) + 1, max(library._works) + 1


# --- the child ------------------------------------------------------------------------------------------------------- #
def main_child(a):
    from types import SimpleNamespace
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
    from PyQt6.QtGui import QKeyEvent, QMouseEvent
    from PyQt6.QtWidgets import QApplication, QListView
    from app import theme
    from app.qt import hud as hud_module, rows, shell, strings
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
    moments = None                                       # (made with the HUD, below)

    real_show = shell.ShellWindow.show_library
    watch = {}                                           # the move being watched: key, t0, version before, moment
    page_of = {}

    def show_library(self_, view):                       # (on the class, before the window opens: its first view
        real_show(self_, view)                           # can come before any connection made after)
        page = page_of.get("page")
        w = watch.get("key")
        if page is None or w is None or numbers.version <= watch["v0"]:
            return
        # the table read without `numbers()`'s lock, which the writer's `after_move` holds 4–10 ms a move (M4.1 A6; the
        # app never takes it on the GUI thread): it is replaced whole, never changed in place
        table = numbers._table
        row = next((r for r in page.view_model.rows if r.key == w), None) if page.view_model is not None else None
        if row is None:
            return
        news = [table.get(e.id, (0, 0, None))[2] for e in row.episodes]
        news = [n for n in news if n is not None]
        want = sum(news) if news else None
        if want is not None and row.n_new == want:
            moments.note(watch["moment"], "numbers_ms", round((time.perf_counter() - watch["t0"]) * 1000, 2))
            watch.clear()
    shell.ShellWindow.show_library = show_library
    writer = StandinWriter(library, numbers)
    services = shell.Services(library=reader, writer=writer)
    window = shell.open_window(app, services)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    bench_moments.apply_reduced()
    hud = hud_module.Hud(window, overlay=False).start()
    moments = bench_moments.Moments(hud)
    writer.moments = moments
    page = window.page_widgets["current"]
    page_of["page"] = page
    lst = page.list
    central = window.centralWidget()
    LEFT, NONE = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    result = {"skipped": {}}

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

    def entry_of(key):
        return next((i for i, e in enumerate(lst.model().entries)
                     if e[0] in (rows.HERO, rows.ROW) and getattr(e[1], "key", None) == key), None)

    def first_frame():
        hud.ignore_before = time.perf_counter()
    window.first_frame.connect(first_frame)

    # the plan: (delay ms, action) run one after another off the event loop — the action, then the delay before the
    # next; an action that returns a callable is a wait of its own (it calls its argument when done)
    plan = []

    def at(ms, fn):
        plan.append((ms, fn))

    def begin(name):
        return lambda: moments.begin(name)

    def end_after(ms):
        """A wait of `ms`, then the moment's repetition ends (the glide, the slide, the toast's rise inside it)."""
        return lambda: (lambda then: QTimer.singleShot(ms, lambda: (moments.end(), then())))

    def still(name):
        return lambda: (lambda then: moments.still(name, then))

    def until(pred, timeout_ms=4000, why=""):
        """A wait until `pred()` (polled every 20 ms); a timeout is noted, never fatal."""
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

    def watch_numbers(key, name):
        watch.update(key=key, v0=numbers.version, t0=time.perf_counter(), moment=name)

    # --- a drag (W3.1a's four phases) ---------------------------------------------------------------------------- #
    def cycle(c):
        def choose():                                    # (before the repetition: M4.1 A3, the bench's own row scan)
            vis = visible_rows()
            i = vis[min(len(vis) - 1, 2 + c % 3)]
            state["src"] = i
            state["key"] = lst.model().entries[i][1].key
            state["at"] = lst.viewport().mapToGlobal(title_point(i))

        def pick():
            send(lst.viewport(), QEvent.Type.MouseButtonPress, lst.viewport().mapFromGlobal(state["at"]), LEFT, LEFT)
        at(16, choose)
        at(16, begin("pickup"))
        at(0, pick)

        def lift():
            p = state["at"] + QPoint(0, theme.MOTION["drag-start-px"])
            send(lst.viewport(), QEvent.Type.MouseMove, lst.viewport().mapFromGlobal(p), NONE, LEFT)
            state["hand"] = p
        at(16, lift)
        for k in range(18):                              # the hand drifts while the ghost settles
            at(16, lambda k=k: move_global(state["hand"] + QPoint(k % 3, k // 6)))
        at(16, begin("slide"))
        for k in range(90):                              # ~7 rows down at 60 Hz
            def down(k=k):
                state["hand"] = state["hand"] + QPoint(0, 4)
                move_global(state["hand"])
            at(16, down)
        at(16, begin("autoscroll"))
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
        at(16, begin("drop"))
        at(16, let_go("drop"))
        at(0, end_after(900))                                   # the glide home and the numbers
        at(400, lambda: None)

    def let_go(name):
        def go():
            if window.moves.running is None:
                return
            watch_numbers(state["key"], name)
            send(central, QEvent.Type.MouseButtonRelease, central.mapFromGlobal(state["hand"]), LEFT, NONE)
        return go

    # --- a drop across the top-20 line or the Soon line (R3-S6) ----------------------------------------------------- #
    def line_cycle(kind, c):
        name = f"drop-{'top20' if kind == 'top' else 'soon'}"

        def prep():
            v = page.view_model
            ln = next((x for x in (v.lines if v is not None else ()) if x.kind == kind), None)
            state["line_ok"] = False
            if ln is None or ln.after + 2 >= len(v.rows) or ln.after < 1:
                result["skipped"][f"{name}: no line"] = result["skipped"].get(f"{name}: no line", 0) + 1
                return
            down = c % 2 == 0                            # down over the line, then back up over it
            src = v.rows[ln.after] if down else v.rows[ln.after + 1]
            dst = v.rows[ln.after + 2] if down else v.rows[ln.after - 1]
            si = entry_of(src.key)
            if si is None or entry_of(dst.key) is None:
                return
            lst.scrollTo(lst.model().index(si, 0), QListView.ScrollHint.PositionAtCenter)
            state.update(line_ok=True, key=src.key, dst=dst.key, down=down)
        at(300, prep)

        def press():
            if not state["line_ok"]:
                return
            si, di = entry_of(state["key"]), entry_of(state["dst"])
            state["at"] = lst.viewport().mapToGlobal(title_point(si))
            r = lst.visualRect(lst.model().index(di, 0))
            y = r.top() + r.height() * (0.8 if state["down"] else 0.2)
            state["to"] = lst.viewport().mapToGlobal(QPoint(title_point(si).x(), round(y)))
            send(lst.viewport(), QEvent.Type.MouseButtonPress, lst.viewport().mapFromGlobal(state["at"]), LEFT, LEFT)
        at(0, begin(name))
        at(0, press)

        def lift():
            if state["line_ok"]:
                p = state["at"] + QPoint(0, theme.MOTION["drag-start-px"] * (1 if state["down"] else -1))
                send(lst.viewport(), QEvent.Type.MouseMove, lst.viewport().mapFromGlobal(p), NONE, LEFT)
                state["hand"] = state["from"] = p
        at(16, lift)
        for k in range(1, 31):                           # to the far row at 60 Hz
            def go(k=k):
                if state["line_ok"]:
                    a_, b_ = state["from"], state["to"]
                    state["hand"] = QPoint(a_.x(), round(a_.y() + (b_.y() - a_.y()) * k / 30))
                    move_global(state["hand"])
            at(16, go)
        at(120, lambda: None)                            # a rest over the slot, then the release
        at(0, let_go(name))
        at(0, end_after(900))
        at(200, lambda: None)

    # --- a move by the item menu ------------------------------------------------------------------------------------ #
    def menu_cycle(which, c):
        name = {"up-next": "menu-top", "soon": "menu-soon", "goal": "menu-goal"}[which]

        def prep():
            vis = visible_rows()
            cands = [i for i in vis if lst.model().entries[i][1].tier == "now"] if which == "soon" else vis
            if not cands:
                lst.verticalScrollBar().setValue(0)
                vis = visible_rows()
                cands = [i for i in vis if lst.model().entries[i][1].tier == "now"] if which == "soon" else vis
            state["menu_row"] = lst.model().entries[cands[min(len(cands) - 1, 2 + c % 3)]][1] if cands else None
        at(250, prep)

        def open_menu():
            row = state["menu_row"]
            if row is None:
                return
            i = entry_of(row.key)
            rect = lst.visualRect(lst.model().index(i, 0))
            lst.menu_requested.emit(row, lst.viewport().mapToGlobal(rect.bottomLeft()))
        at(0, begin("menu-open"))
        at(0, open_menu)
        at(0, end_after(350))

        def pick():
            row = state["menu_row"]
            menus = [m for m in (getattr(getattr(window, "items", None), "last_menu", None),
                                 getattr(window.moves, "last_menu", None)) if m is not None]
            menu = next((m for m in menus if m.isVisible()), menus[0] if menus else None)
            label = strings.MENU_ITEMS[which][0]
            act = next((x for x in (menu.actions() if menu is not None else ()) if x.text() == label), None)
            if row is None or act is None:
                result["skipped"][f"{name}: no action"] = result["skipped"].get(f"{name}: no action", 0) + 1
                if menu is not None:
                    menu.hide()
                return
            if which != "goal":
                watch_numbers(row.key, name)
            menu.hide()                                  # as QMenu does on a click: hidden, then the action triggered
            act.trigger()
        at(0, begin(name))
        at(0, pick)
        at(0, end_after(800))
        at(150, lambda: None)

    # --- a move by key (Alt+↑ / Alt+↓) ------------------------------------------------------------------------------ #
    def key_cycle(step, c):
        name = "key-up" if step < 0 else "key-down"

        def prep():
            vis = visible_rows()
            i = vis[min(len(vis) - 1, 3 + c % 3)] if vis else None
            state["key_row"] = i
            if i is not None:
                lst.setCurrentIndex(lst.model().index(i, 0))
        at(250, prep)

        def press():
            i = state["key_row"]
            if i is None:
                return
            watch_numbers(lst.model().entries[i][1].key, name)
            key = Qt.Key.Key_Up if step < 0 else Qt.Key.Key_Down
            QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.AltModifier))
            QApplication.sendEvent(lst, QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.AltModifier))
        at(0, begin(name))
        at(0, press)
        at(0, end_after(700))

    # --- the arrival moment ----------------------------------------------------------------------------------------- #
    arrival_ids = []
    arrival_from = []                                    # arrival_template's, read in start() (never in a moment)

    def arrival_cycle(c):
        def land():
            inset = window.arrivals_inset
            state["played"] = inset.arrivals_played if inset is not None else 0
            temp, work, first_id, first_work = arrival_from[0]
            new_id, new_work = first_id + c, first_work + c
            title = f"新着の物語 {c + 1}"
            row = dict(temp, id=new_id, tier="arrivals", ord=temp["ord"] - 512 * (c + 1), piece_id=2 * 10 ** 9 + c,
                       work_id=new_work, rel_path=f"HighPriority/Hato/{title}/{title} - 01.srt",
                       title=f"{title} - 01.srt", watched=0, added_at=f"2026-10-16T21:{c // 60:02d}:{c % 60:02d}Z")
            works = [dict(work or {}, id=new_work, title=title)]
            arrival_ids.append(new_id)
            opener.pending.append({"items": [row], "works": works, "order": True})
            state["arrival_t0"] = time.perf_counter()
        at(0, begin("arrival"))
        at(0, land)

        def played():
            inset = window.arrivals_inset
            return inset is not None and inset.arrivals_played > state["played"]
        at(0, lambda: until(played, 4000, "arrival: never played"))
        at(0, lambda: moments.note("arrival", "landed_ms", round((time.perf_counter() - state["arrival_t0"]) * 1000, 1)))
        at(0, end_after(700))
        at(200, lambda: None)

    # --- the finish toasts ------------------------------------------------------------------------------------------ #
    used = set()

    def done_cycle(c):
        def prep():
            v = page.view_model
            cands = done_candidates(v.rows if v is not None else (), used)
            row = cands[0] if cands else None
            state["done_row"] = row.key if row is not None else None
            if row is None:
                result["skipped"]["toast-done-all: no row"] = result["skipped"].get("toast-done-all: no row", 0) + 1
                return
            used.add(row.key)
            others = [e.id for e in row.episodes[:-1] if not e.watched]
            if others:                                   # another program marks the rest watched first
                opener.pending.append({"items": [{"id": i, "watched": 1} for i in others]})

        def ready():
            key = state["done_row"]
            v = page.view_model
            row = next((r for r in (v.rows if v is not None else ()) if r.key == key), None)
            return key is None or (row is not None and all(e.watched for e in row.episodes[:-1]))
        at(0, prep)
        at(0, lambda: until(ready, 4000, "toast-done-all: rest not watched"))

        def done():
            key = state["done_row"]
            v = page.view_model
            row = next((r for r in (v.rows if v is not None else ()) if r.key == key), None)
            if row is None:
                return
            window.toasts.close()
            lst.done_requested.emit(row, row.episodes[-1])
        at(200, lambda: None)
        at(0, begin("toast-done-all"))
        at(0, done)
        at(0, end_after(700))
        at(0, window.toasts.close)
        at(150, lambda: None)

    def finished_cycle(c):
        def choose():
            tray = getattr(window, "arrivals_tray", None)
            v = page.view_model
            arrivals = [x for x in (getattr(v, "arrivals", ()) or ()) if x.key not in used]
            state["arrival"] = arrivals[0] if arrivals and tray is not None else None
            if state["arrival"] is not None:
                used.add(state["arrival"].key)

        def finish():
            arrival = state["arrival"]
            if arrival is None:
                result["skipped"]["toast-finished: no arrival"] = result["skipped"].get(
                    "toast-finished: no arrival", 0) + 1
                return
            window.toasts.close()
            window.arrivals_tray.act(arrival, "finished")
        at(250, choose)
        at(0, begin("toast-finished"))
        at(0, finish)
        at(0, end_after(700))
        at(0, window.toasts.close)
        at(150, lambda: None)

    chores = SimpleNamespace(duties=SimpleNamespace(notice=None), toasts=window.toasts)

    def connect_cycle(c):
        def notice():
            window.toasts.close()
            shell.ShellWindow._show_chores(chores, SimpleNamespace(
                notice=f"Connect: 3 new cards from 進撃の巨人 are in Anki ({c + 1})"))
        at(250, lambda: None)
        at(0, begin("toast-connect"))
        at(0, notice)
        at(0, end_after(700))
        at(0, window.toasts.close)

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

    def start(tries=[0]):
        v = page.view_model
        if v is None or v.loading or not v.rows:
            tries[0] += 1
            if tries[0] % 40 == 0:
                print(f"bench_drag: waiting for rows ({None if v is None else (v.state, v.loading, len(v.rows))})",
                      flush=True)
            QTimer.singleShot(50, start)
            return
        print(f"bench_drag: {len(v.rows)} rows live; {a.cycles} cycles a moment", flush=True)
        arrival_from.append(arrival_template(library))
        lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 3)
        n = a.cycles
        for c in range(n):
            cycle(c)
        at(0, still("drop"))
        for kind in ("top", "soon"):
            at(0, lambda: lst.verticalScrollBar().setValue(0))
            for c in range(n):
                line_cycle(kind, c)
            at(0, still(f"drop-{'top20' if kind == 'top' else 'soon'}"))
        for which in ("up-next", "soon", "goal"):
            at(0, lambda: lst.verticalScrollBar().setValue(0))
            for c in range(n):
                menu_cycle(which, c)
            at(0, still({"up-next": "menu-top", "soon": "menu-soon", "goal": "menu-goal"}[which]))
        at(0, still("menu-open"))
        for step in (-1, 1):
            at(0, lambda: lst.verticalScrollBar().setValue(0))
            for c in range(n):
                key_cycle(step, c)
            at(0, still("key-up" if step < 0 else "key-down"))
        for c in range(n):
            arrival_cycle(c)
        at(0, still("arrival"))
        at(0, lambda: lst.verticalScrollBar().setValue(0))
        for c in range(n):
            done_cycle(c)
        at(0, still("toast-done-all"))
        for c in range(n):
            finished_cycle(c)
        at(0, still("toast-finished"))
        for c in range(n):
            connect_cycle(c)
        at(0, still("toast-connect"))
        QTimer.singleShot(1500, run)

    def finish():
        for name in DRAG[:-1]:
            moments.wakes.setdefault(name, "with drop")   # a drag's phases end in its drop: counted after it
        result["moments"] = moments.summary()
        result["hud"] = {k: v for k, v in hud.report().items() if k in ("steps", "frames", "windows", "slow_frames",
                                                                         "late", "anim")}
        result["hud"]["late"].pop("explained", None)
        result["memory"] = hud_module._memory_mb()
        result["dpr"] = lst.viewport().devicePixelRatioF()
        result["drops"] = window.moves.drops
        result["reduced"] = motion_reduced()
        result["extra"] = {"skipped": result["skipped"], "drops": result["drops"]}
        import json
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f)
        app.quit()

    def motion_reduced():
        from app.qt import motion
        return bool(motion.clock().mode.reduced)

    QTimer.singleShot(120000 + a.cycles * 40000, finish)   # never longer than this
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
    ap.add_argument("--cycles", type=int, default=10, help="repetitions of each moment (>= 10 for a timed run)")
    ap.add_argument("--scale", type=int, default=None, help="one scale in % (the old flag: --scales takes a list)")
    bench_moments.add_arguments(ap)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--child", default=None)
    a = ap.parse_args()
    if a.child:
        main_child(a)
    else:
        a.scales_list = [a.scale] if a.scale is not None else bench_moments.parse_scales(a.scales)
        main_parent(a)


if __name__ == "__main__":
    main()
