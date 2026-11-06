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
- **widgets** created and deleted (`QApplication.allWidgets()` before and after);
- **reads** — the library reader's feed reads and views built (`LibraryReader.reads` / `.builds`), settings.json read
  from disk (`settings_manager.load_settings`) and the settings service's `get()`;
- **events** — every event the application delivered: each one is a call into every app-wide filter written in Python
  (the shell's `AppFilter`, motion's finisher, the click-away watchers), so it is that work's count.

Deterministic: no clock is read, only counts; the motion freeze is on (the harness's), so an overlay lands at once.

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

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QRect
from PyQt6.QtGui import QPainterPath, QRegion
from PyQt6.QtWidgets import QApplication, QLayout, QWidget

PASS_SLACK = 1.5             # R1: a real pass asks up to ~1.3× the forced one (Settings' paused pass resumes its layouts
                             # deepest first, and the rows it shows ask their own); a pass laid twice is 2×, a pass
                             # laid per row shown (a9.1's lag) 30–120×
MOVES_PER_PASS = 2           # R1: one press moves a widget at most twice (its pass, and a scroll that keeps an anchor)
STRIP_SLACK_PX = 4           # R2: rows of pixels over the strip a scroll exposes (the device-pixel rounding)
HINTS = ("sizeHint", "minimumSizeHint", "heightForWidth")
_E = QEvent.Type
Paint = namedtuple("Paint", "widget cls name area rect region")


def _ours(name):
    return name.startswith("app.qt.") or (name.startswith("modules.") and ".qt_" in name)


def hint_classes():
    """Every widget class this app writes in Python that answers a size hint itself: [(cls, name, function)]."""
    found = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not _ours(name):
            continue
        for obj in list(vars(mod).values()):
            if isinstance(obj, type) and obj.__module__ == name and issubclass(obj, QWidget):
                for h in HINTS:
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


def _addr(w):
    try:
        return sip.unwrapinstance(w)
    except (RuntimeError, TypeError):
        return None


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
            self.paints.append(Paint(obj, type(obj).__name__, obj.objectName(), area(region), here.boundingRect(), here))
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
            return 0
        return area(self._union.get(id(self.top), QRegion()).intersected(QRegion(rect)))

    def painted_in(self, widget):
        """px² painted on `widget` and its descendants."""
        return sum(p.area for p in self.paints if _within(p.widget, widget))

    def paints_outside(self, *widgets):
        """The paints that reach outside every one of `widgets` (where they stand in the window: a parent painting the
        ground under a child counts as inside the child): [(class, objectName, rect)]."""
        rects = [rect_in_window(x) for x in widgets]
        return [(p.cls, p.name, p.rect) for p in self.paints
                if not any(r.contains(p.rect) for r in rects) and not any(_within(p.widget, x) for x in widgets)]

    def paints_outside_rect(self, *rects):
        """The paints that reach outside every one of `rects` (in the top-level window's coordinates; a paint's own
        region, rectangle by rectangle, never only its bounding box): [(class, objectName, the part outside's box)]."""
        allowed = QRegion()
        for r in rects:
            allowed = allowed.united(QRegion(r))
        out = []
        for p in self.paints:
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
    before = {a for a in map(_addr, app.allWidgets()) if a is not None}
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
    after = {a for a in map(_addr, app.allWidgets()) if a is not None}
    w.created, w.deleted = len(after - before), len(before - after)
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
def kept(widget):
    """Keep `widget` (a top-level) open across a file's tests: the harness's per-test close skips it and its popups
    (`tests/qt/conftest.py::_kept`); the file's module fixture closes it at its end (`close_kept`)."""
    widget.setProperty("wc_keep", True)
    for top in QApplication.topLevelWidgets():   # what its build made on its own (the tooltip bubble, a lift's
        top.setProperty("wc_keep", True)          # window): called right after the build, every top-level is its
    return widget


def close_kept(widget, services=None):
    for top in QApplication.topLevelWidgets():
        if top.property("wc_keep"):
            top.setProperty("wc_keep", False)
    widget.close()
    if services is not None:
        services.shutdown(0.5)
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
    mp.setenv("SURASURA_TEST_ROOT", str(root))
    mp.setenv("SURASURA_FREEZE_MOTION", "1")
    mp.setenv("SURASURA_INSTANCE_NAME", f"surasura-wc-{uuid.uuid4().hex[:12]}")
    mp.setattr(star_ask.StarAsk, "_seen", lambda self: True)
    try:
        yield root
    finally:
        mp.undo()
