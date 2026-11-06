"""Work counts (WC, 2026-11-06): what one press costs the window, counted — never timed — so redraw waste fails a test at
build time instead of reaching Sonic by feel (Settings laid its page out 30–120× a click, a scroll repainted the page).

Charter S19's older tests ask "nothing changed → nothing redrawn"; these ask how much work a press does when something
DOES change. One press, measured with `measure(...)`:

    with work_counts.measure(win, readers=[reader]) as w:
        press()
    # (settled: the loop run until nothing is left to do, see `settle`)
    assert w.paints_outside(row) == [], w.report()

What is counted, between the press and the window at rest again:
- **paints** — every paint event, per widget, with its painted area in px² (the region's rectangles; a child painted
  under its parent counts on its own), and the whole against the top-level's area (`share`);
- **layout passes** — `QEvent.LayoutRequest` delivered (Qt's posted relayout of a widget, compressed one a turn), and
  **hints**: calls into the size hints this app writes in Python (`sizeHint`, `minimumSizeHint`, `heightForWidth` of
  every widget class under `app/qt/` and `modules/*/qt_*.py`) — a layout pass asks each row; a pass laid again per row
  shown multiplies them. `one_pass(widget)` counts one forced full pass of a widget's layouts, the unit a rule compares
  with;
- **geometry** — Move and Resize events reaching widgets (rows pushed about);
- **widgets** created and deleted (every live widget tagged before the press: one without the tag after is new);
- **reads** — the library reader's feed reads and views built (`LibraryReader.reads` / `.builds`), settings.json read
  from disk (`settings_manager.load_settings`) and the settings service's `get()`;
- **events** — every event the application delivered: each one is a call into every app-wide filter written in Python
  (the shell's `AppFilter`, motion's finisher, the click-away watchers), so it is that work's count.

Deterministic: no clock is read, only counts; the motion freeze is on (the harness's), so an overlay lands at once.
(The paint, hint and widget counts are; `events` and the settings reads also count what a `wait_until` inside the
measure lets in.) Paints in another window than `top` (a popup, the bubble, the drag's ghost) are kept apart
(`elsewhere`): the rect rules judge `top`'s own.

**The rules** (GUI_Design_Guidelines_Qt.md §3 *Work counts*; a screen that legitimately needs more names why in its
test):
- R0 a press that changes nothing → 0 paints;
- R1 one click → at most one layout pass of the page: no widget moved more than `MOVES_PER_PASS` times
  (`most_moved()`; a pass laid again per row shown moves every row under it again) and `hints <= one_pass(page) *
  PASS_SLACK`;
- R2 a scroll notch → the painted area at most the strip newly exposed (+ `STRIP_SLACK_PX` rows of pixels);
- R3 a move → only the rows that changed repainted (the rows between the old place and the new one, never the list);
- R4 a toggle → only its row and what it reveals (nothing above it, nothing outside its page repaints);
- R5 opening an overlay → built once; a later open reuses it (no widget created the second time).
"""
import sys
from collections import Counter, namedtuple
from contextlib import contextmanager

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect
from PyQt6.QtGui import QPainterPath, QRegion
from PyQt6.QtWidgets import QAbstractItemDelegate, QApplication, QLayout, QWidget

PASS_SLACK = 1.5             # R1: a real pass asks up to ~1.3× the forced one (Settings' paused pass resumes its layouts
                             # deepest first, and the rows it shows ask their own); a pass laid twice is 2×, a pass
                             # laid per row shown (a9.1's lag) 30–120×
MOVES_PER_PASS = 2           # R1: one press moves a widget at most twice (its pass, and a scroll that keeps an anchor)
STRIP_SLACK_PX = 4           # R2: rows of pixels over the strip a scroll exposes (the device-pixel rounding)
HINTS = ("sizeHint", "minimumSizeHint", "heightForWidth")
LAYOUT_HINTS = ("sizeHint", "minimumSize", "heightForWidth", "setGeometry")     # a layout written in Python
_E = QEvent.Type
Paint = namedtuple("Paint", "widget cls name area rect region window")


def _ours(name):
    return name.startswith("app.qt.") or (name.startswith("modules.") and ".qt_" in name)


def hint_classes():
    """Every widget, item delegate (a painted list's rows: `RowDelegate`, the tray's) and layout class this app writes
    in Python that answers a size hint itself: [(cls, name, function)]."""
    found = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not _ours(name):
            continue
        for obj in list(vars(mod).values()):
            if not (isinstance(obj, type) and obj.__module__ == name):
                continue
            if issubclass(obj, (QWidget, QAbstractItemDelegate)):
                names = HINTS
            elif issubclass(obj, QLayout):
                names = LAYOUT_HINTS
            else:
                continue
            for h in names:
                f = obj.__dict__.get(h)
                if callable(f):
                    found.append((obj, h, f))
    return found


def area(region):
    """px² of a paint event's region (its rectangles don't overlap; PyQt6's QRegion can't be iterated, so they are
    read through a painter path, one rectangle a polygon)."""
    if region.rectCount() <= 1:
        r = region.boundingRect()
        return r.width() * r.height()
    path = QPainterPath()
    path.addRegion(region)
    return round(sum(p.boundingRect().width() * p.boundingRect().height() for p in path.toFillPolygons()))


def settle(turns=30):
    """The loop run until it has nothing more to do (posted events, layouts, the deferred deletes), a fixed number of
    turns: no clock read, so the same work lands in the count every run."""
    for _ in range(turns):
        QApplication.sendPostedEvents()
        QApplication.processEvents()


_TAG = "_wc_seen"
_TOKENS = __import__("itertools").count(1)


def _tag_all(token):
    """Every live widget tagged with `token`: one made during the press has no tag (an address can be reused by a
    widget made after one deleted, a property can't). -> how many were tagged."""
    n = 0
    for w in QApplication.allWidgets():
        w.setProperty(_TAG, token)
        n += 1
    return n


class Work(QObject):
    """The counts of one measured stretch (an app-wide event filter while it runs)."""

    def __init__(self, top=None, readers=()):
        super().__init__()
        self.top = top
        self.readers = list(readers)
        self.paints = []                     # Paint(widget, cls, name, area px², rect in its window)
        self._union = {}                     # id(window) -> the QRegion painted in it, in its own coordinates
        self.layout_requests = Counter()     # id(widget) -> LayoutRequest events
        self._layout_widgets = {}
        self.geometry = 0                    # Move + Resize events on widgets
        self.moves = Counter()               # id(widget) -> Move events (one layout pass moves a widget once)
        self._moved = {}
        self.events = 0
        self.kinds = Counter()
        self.hints = 0
        self.created = self.deleted = 0
        self.reads = self.builds = 0
        self.settings_reads = self.settings_gets = 0
        self.window_area = top.width() * top.height() if top is not None else 0

    # --- the filter ------------------------------------------------------------------------------------------- #
    def eventFilter(self, obj, ev):
        t = ev.type()
        self.events += 1
        self.kinds[t] += 1
        if t == _E.Paint:
            region = ev.region()
            win = obj.window() if obj.isWidgetType() else obj      # (a QWindow of its own: the lift, the ghost)
            at = obj.mapTo(win, QPoint(0, 0)) if win is not obj else QPoint(0, 0)
            here = region.translated(at)
            self.paints.append(Paint(obj, type(obj).__name__, obj.objectName(), area(region), here.boundingRect(), here, win))
            key = id(win)
            self._union[key] = self._union.get(key, QRegion()).united(here)
        elif t == _E.LayoutRequest:
            self.layout_requests[id(obj)] += 1
            self._layout_widgets[id(obj)] = obj
        elif t in (_E.Move, _E.Resize) and obj.isWidgetType():
            self.geometry += 1
            if t == _E.Move:
                self.moves[id(obj)] += 1
                self._moved[id(obj)] = obj
        return False

    # --- what was counted -------------------------------------------------------------------------------------- #
    @property
    def painted(self):
        return len(self.paints)

    @property
    def area(self):
        return sum(p[3] for p in self.paints)

    @property
    def share(self):
        """The painted area against the top-level window's (1.0 = a whole window's worth)."""
        return self.area / self.window_area if self.window_area else 0.0

    @property
    def union(self):
        """px² of the top-level window painted at least once (a parent painted under its child counts once)."""
        if self.top is None:
            return sum(area(r) for r in self._union.values())
        return area(self._union.get(id(self.top), QRegion()))

    def union_in(self, rect):
        """px² of `rect` (in the top-level's coordinates) painted at least once."""
        if self.top is None:
            raise ValueError("union_in needs the measure's top-level window")
        return area(self._union.get(id(self.top), QRegion()).intersected(QRegion(rect)))

    def painted_in(self, widget):
        """px² painted on `widget` and its descendants."""
        return sum(p.area for p in self.paints if _within(p.widget, widget))

    @property
    def elsewhere(self):
        """The paints in another window than `top` (a popup, the tooltip bubble, the drag's ghost, a lift): their
        coordinates are their own window's, so the rect rules never judge them — assert on these apart."""
        return [(p.cls, p.name, p.rect) for p in self.paints if self.top is not None and p.window is not self.top]

    def _here(self):
        return [p for p in self.paints if self.top is None or p.window is self.top]

    def paints_outside(self, *widgets):
        """The paints that reach outside every one of `widgets` (where they stand in the window: a parent painting the
        ground under a child counts as inside the child): [(class, objectName, rect)]. `top`'s own paints only (see
        `elsewhere`)."""
        rects = [rect_in_window(x) for x in widgets]
        return [(p.cls, p.name, p.rect) for p in self._here()
                if not any(r.contains(p.rect) for r in rects) and not any(_within(p.widget, x) for x in widgets)]

    def paints_outside_rect(self, *rects):
        """The paints that reach outside every one of `rects` (in the top-level window's coordinates; a paint's own
        region, rectangle by rectangle, never only its bounding box): [(class, objectName, the part outside's box)]."""
        allowed = QRegion()
        for r in rects:
            allowed = allowed.united(QRegion(r))
        out = []
        for p in self._here():
            left = p.region.subtracted(allowed)
            if not left.isEmpty():
                out.append((p.cls, p.name, left.boundingRect()))
        return out

    def layouts_of(self, widget):
        return self.layout_requests.get(id(widget), 0)

    def most_layouts(self):
        """The widget laid out most often by a posted relayout: (count, class name)."""
        if not self.layout_requests:
            return 0, None
        k, n = self.layout_requests.most_common(1)[0]
        return n, type(self._layout_widgets[k]).__name__

    def most_moved(self):
        """The widget moved most often: (Move events, class name). One layout pass moves a widget once; a page laid
        out again for each row it shows moves every row under it again and again (a9.1: 1,526 moves for 97 rows)."""
        if not self.moves:
            return 0, None
        k, n = self.moves.most_common(1)[0]
        return n, type(self._moved[k]).__name__

    def report(self):
        """One line for an assertion's message: what the press cost."""
        by = Counter()
        for p in self.paints:
            by[p.cls or p.name] += p.area
        top = ", ".join(f"{c} {a}" for c, a in by.most_common(6))
        return (f"paints {self.painted} ({self.area} px², {self.share:.2f} of the window; {self.union} px² of it "
                f"once: {top}) · "
                f"layout requests {sum(self.layout_requests.values())} (most {self.most_layouts()}) · "
                f"hints {self.hints} · geometry {self.geometry} (most moved {self.most_moved()}) · widgets +{self.created} -{self.deleted} · "
                f"reads {self.reads} builds {self.builds} · settings {self.settings_reads} file / "
                f"{self.settings_gets} get · events {self.events}")


def rect_in_window(widget):
    """`widget`'s rectangle in its top-level window's coordinates."""
    win = widget.window()
    at = widget.mapTo(win, QPoint(0, 0)) if win is not widget else QPoint(0, 0)
    return QRect(at, widget.size())


def _within(w, ancestor):
    try:
        while w is not None:
            if w is ancestor:
                return True
            w = w.parent()
    except RuntimeError:                    # a widget deleted since its paint
        return False
    return False


@contextmanager
def measure(top=None, readers=(), settle_turns=30):
    """Count the work of the `with` block's press, then of the loop until the window rests (`settle`). `top`: the
    top-level window the share is measured against; `readers`: the library readers whose reads are counted."""
    from app import settings_manager
    from app.services import settings as settings_service
    app = QApplication.instance()
    assert top is None or top.isWindow(), "measure's `top` is a top-level window (its coordinates are the rules')"
    w = Work(top, readers)
    patched = []

    def counting(cls, name, f):
        def wrapped(self, *a, **k):
            w.hints += 1
            return f(self, *a, **k)
        wrapped.__wrapped__ = f
        setattr(cls, name, wrapped)
        patched.append((cls, name, f))

    for cls, name, f in hint_classes():
        counting(cls, name, f)
    load, get = settings_manager.load_settings, settings_service.SettingsService.get

    def counted_load(*a, **k):
        w.settings_reads += 1
        return load(*a, **k)

    def counted_get(self):
        w.settings_gets += 1
        return get(self)
    settings_manager.load_settings = counted_load
    settings_service.SettingsService.get = counted_get
    token = next(_TOKENS)
    before = _tag_all(token)
    reads = [(r.reads, r.builds) for r in w.readers]
    app.installEventFilter(w)
    try:
        yield w
        settle(settle_turns)
    finally:
        app.removeEventFilter(w)
        settings_manager.load_settings = load
        settings_service.SettingsService.get = get
        for cls, name, f in reversed(patched):
            setattr(cls, name, f)
    now = QApplication.allWidgets()
    w.created = sum(1 for x in now if x.property(_TAG) != token)
    w.deleted = before - (len(now) - w.created)
    for (r0, b0), r in zip(reads, w.readers):
        w.reads += r.reads - r0
        w.builds += r.builds - b0


def one_pass(widget, top=None):
    """The hints one forced full layout pass of `widget` asks (every layout under it invalidated, then its own laid
    out at once): the unit R1 compares a press with. Paints and all are measured too, and thrown away."""
    layouts = [widget.layout()] if widget.layout() is not None else []
    layouts += [l for l in widget.findChildren(QLayout) if l not in layouts]
    with measure(top) as w:
        for layout in layouts:
            layout.invalidate()
        if layouts:
            layouts[0].activate()
    return w.hints


def exposed(before, after):
    """The strip a scroll of a view exposes: its height in px from the two scroll values."""
    return abs(after - before)


def visible_rect(widget):
    """`widget`'s rectangle in its own coordinates (for a paint rule that reads where something is)."""
    return QRect(0, 0, widget.width(), widget.height())


# --- a screen built once per file ------------------------------------------------------------------------------- #
ROOTS = {}                                   # a kept screen's name -> its file's root (`module_env`)


def home(monkeypatch, name):
    """Each test of a kept screen's file back in the file's own root (the core conftest gives every test a new one): the
    window's settings service rebuilds each write from the file it finds, so a write in a fresh root would leave the
    window with that test's keys only — the next test meeting default settings (the first mark's hint, …)."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", ROOTS[name])


def quiet(win=None, timeout_ms=10000):
    """Everything a kept window has on its way landed before a test ends (the harness drops the answers still coming
    at each test's end — on a kept window, for good): the thread pool's workers done, the moves' tickets cleared, the
    hover's bubble hidden, the loop settled."""
    from PyQt6.QtCore import QThreadPool
    from app.qt import bridge
    QThreadPool.globalInstance().waitForDone(timeout_ms)
    bridge.wait_for_workers(timeout_ms)
    moves = getattr(win, "moves", None) if win is not None else None
    if moves is not None:
        from tests.qt.conftest import wait_until
        wait_until(lambda: not getattr(moves, "tickets", None), timeout_ms / 1000)
    bubble = getattr(getattr(win, "tooltips", None), "bubble", None) if win is not None else None
    if bubble is not None:
        bubble.hide()
    settle()
def kept(widget):
    """Keep `widget` (a top-level) open across a file's tests: the harness's per-test close skips it and its popups
    (`tests/qt/conftest.py::_kept`); the file's module fixture closes it at its end (`close_kept`)."""
    widget.setProperty("wc_keep", True)
    for top in QApplication.topLevelWidgets():   # what its build made on its own (the tooltip bubble, a lift's
        top.setProperty("wc_keep", True)          # window): called right after the build, every top-level is its
    return widget


def close_kept(widget, services=None):
    """The file's screen closed at its end, while the file's own root is still set: its workers and its source looks
    waited for (the harness's per-test waits never saw them: they were made before its patch), then deleted."""
    from app.qt import bridge
    for top in QApplication.topLevelWidgets():
        if top.property("wc_keep"):
            top.setProperty("wc_keep", False)
    widget.close()
    if services is not None:
        services.shutdown(0.5)
    looks = getattr(widget, "looks", None)
    if looks is not None and hasattr(looks, "idle"):
        looks.idle(10)
    bridge.wait_for_workers(10000)
    widget.deleteLater()
    QApplication.sendPostedEvents(None, _E.DeferredDelete)
    QApplication.processEvents()


@contextmanager
def module_env(tmp_path_factory, name):
    """What the harness gives each test, given for a file's whole life (a module fixture builds its screen before any
    test's own fixtures run): a test root of its own, the motion freeze, an instance name, Surasura's star ask taken as
    seen. Each test still gets its own root on top (the core conftest); the kept screen's later reads and writes follow
    the env, so they land in that test's root."""
    import uuid
    import pytest
    from app.qt import star_ask
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp(f"wc_{name}")
    ROOTS[name] = str(root)
    mp.setenv("SURASURA_TEST_ROOT", str(root))
    mp.setenv("SURASURA_FREEZE_MOTION", "1")
    mp.setenv("SURASURA_INSTANCE_NAME", f"surasura-wc-{uuid.uuid4().hex[:12]}")
    mp.setattr(star_ask.StarAsk, "_seen", lambda self: True)
    try:
        yield root
    finally:
        mp.undo()


@contextmanager
def window_screen(qapp, tmp_path_factory, name, writer="undo", **build):
    """The 3.0 window on the synthetic library (`tests/fixtures/window_seed`, Japanese titles), its writes recorded and
    written into the stand-in store (`writer`: "undo" — moves undone back, test_drag's `UndoingWriter`; "arrivals" —
    New arrivals' placements too, test_arrivals' `ArrivalsWriter`), built once for a file: `(seed, win, writer)`.
    A module fixture: `with work_counts.window_screen(qapp, tmp_path_factory, "needs") as s: yield s`."""
    from app.qt import stones
    from tests.fixtures import window_seed
    with module_env(tmp_path_factory, name):
        key = stones._key(1.0, "M")
        if key not in stones._SHEETS:
            stones._landed(key, stones.build(*key))
        seed = window_seed.build(**build)
        if writer == "arrivals":
            from tests.qt.test_arrivals import ArrivalsWriter, open_window
            w = ArrivalsWriter(seed.library)
        else:
            from tests.qt.test_drag import UndoingWriter, open_window
            w = UndoingWriter(seed.library)
        win, services = open_window(qapp, seed, w)
        try:
            kept(win)
        except BaseException:
            close_kept(win, services)
            raise
        rest(300)
        try:
            yield seed, win, w
        finally:
            close_kept(win, services)


def rest(ms=150):
    """The loop run for `ms` (workers' answers land: a view, a toast), then settled — between presses, unmeasured, or
    inside a measure after a press whose work lands from a worker."""
    from PyQt6.QtTest import QTest
    QTest.qWait(ms)
    settle()
