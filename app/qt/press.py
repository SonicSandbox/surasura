"""A press painted (round 8 row 45; the scope `row45-54-scope.md` §3, Sonic's Q1 answer): the state of
`app/services/press.py` on its control, so every press reacts in the frame it happens in.

Sonic (Q1): "It cannot gray out … If it's an icon I'd rather it not have words … a very nice and theme-looking spin
arc … subtle but clean." So a pressed control keeps its colours and its words: a small accent arc turns in it
(`motion.Spinner("spin")`) until the work ends. A second press meanwhile does nothing (`Press.live`), never by greying.

**Nothing moves** (the round 8 trial; P1 widened the button as it was pressed, and its neighbour slid ~17 px): the arc
takes no layout space. A button that will be pressed keeps the arc's room at rest (`room`: its padding, both sides, so
its words stay centred — `theme.SIZES["press-room"]`, the arc and a little air, never scaled with the text), and the
arc, a child of the button laid over it, turns in its right padding: the button keeps its size, its words stay where
they are, no neighbour moves.

**Centred** (Sonic, round 2: "it's not centered. It MUST be centered"): the arc's middle is the button's middle as the
screen draws it — the box's edges land on whole device pixels (half up) while an antialiased arc lands anywhere, so a
logical centre missed by half a device pixel at 150 % and 225 % — and midway between the words' end and the right
border (`arc_box`, worked out where it is painted, at that paint's device ratio). The arc is the one look for a
pressed button (round 2's set-in sheen was not taken). A control with a look of its own paints it instead
(`press_look(on)`: the known count's underline filling).

`run(control, key, fn, …)` does, in order: the press, the arc on the control, `control.repaint()` — which paints
before it returns — and only then hands `fn` to the worker. Its answer ends the press (done, or failed with why) and
takes the arc off. Work that ends by itself elsewhere (a registry job the control follows) uses `begin` and `end`.
Words only where they are meant: `busy` (None by default) is held in the bar's slot while the press is live
(`ShellWindow.say(…, hold=)`) — a menu's press, whose menu has closed, or a wait worth naming; a failure's reason goes
to the bar through the caller's `failed`. A control rebuilt while its press is live takes the arc again (`adopt`).

**What a press marks** (Sonic's IK-2): a button press marks its button; a menu's press (`control` None: its menu has
closed) marks the thing it acts on where it is on screen — `at`, an object with `on()` / `off()`: `row_mark` (a file's
line in a list, at the part it was pressed from: ⋯ or ▶), `widget_mark` (the arc over a cover, a tile) — and where
nothing is on screen, the same accent arc in the bottom bar's slot, no words (`bar_mark`, the default; a secondary
window's own, in its status line's corner). `NOWHERE`: the caller marks it itself (*Mine now*'s pills).

A worker's report of a wait or a step reaches the press through `relay`; a registry job's states through `follow`;
another program, a folder or a link opens through `open`, on a worker — never on the window's thread.
"""
import math
import os
import sys

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF
from PyQt6.QtGui import QPainter, QTransform

from app import theme
from app.qt import bridge, motion, strings, style
from app.services import jobs as jobs_module
from app.services import press as service

ARC = 14                        # px: the arc's side (the spinner's own)

_loose = service.Presses()      # the presses of a control with no window
_painted = {}                   # Press -> (control or None, its mark or None: an _Arc or an _Own, which control: its
#                                 "action" property)
_at = {}                        # Press -> what it marks on screen (`at`: a row, a widget, the bar's arc)
_busy = {}                      # Press -> the words it holds in the bar (`busy`), given back after a wait's reason


def room(control, end=False):
    """`control` (a button) will be pressed through `run` / `begin`: it keeps its arc's room at rest (style's
    `[presses="true"]`; `end`: a link whose words sit at its left keeps it at its right end only, `[presses="end"]`).
    Call it as the button is made, before it is laid out."""
    control.setProperty("presses", "end" if end else True)
    control.style().unpolish(control)
    control.style().polish(control)
    return control


def presses_of(win):
    """`win`'s presses — made on it the first time when it has none (a stand-in window: its presses its own, never a
    module's shared with every other window) — or, with no window, the module's."""
    if win is None:
        return _loose
    got = getattr(win, "presses", None)
    if got is None:
        try:
            got = win.presses = service.Presses()
        except (AttributeError, TypeError):
            return _loose
    return got


def run(control, key, fn, *args, busy=None, then=None, failed=None, win=None, goes=False, at=None):
    """`control` pressed for the action `key` (an action's name with what it acts on): `fn(*args)` on a worker once
    the arc is painted; `then(value)` / `failed((exception, its traceback's text))` as `bridge.run_in_worker`'s, once
    the arc is off. `control` None: a menu's press (the hairline runs; `busy`, if given, in the bar), marking `at` —
    what it acts on, where it is on screen (`row_mark`, `widget_mark`; None: the bar's arc). `goes`: the control goes
    when done (a Needs-you card's answer) — a press in the moment before it goes does nothing.
    -> the press, or None when it was live (or just done, `goes`): nothing started."""
    p = begin(control, key, busy=busy, win=win, goes=goes, at=at)
    if p is None:
        return None

    def ended(value):
        end(p, win)
        if then is not None:
            then(value)

    def broke(info):
        end(p, win, failed=True, why=info[0] if info else None)
        if failed is not None:
            failed(info)
        else:
            print(f"A background task failed: {info[1]}", file=sys.stderr)
    bridge.run_in_worker(fn, *args, then=ended, failed=broke)
    return p


def begin(control, key, busy=None, win=None, goes=False, at=None):
    """The press, painted now (the arc on `control` — or, `control` None, `at`: the bar's arc when None —, `busy` held
    in the bar) and repainted before this returns — the caller starts its work after. -> the press, or None when it
    was live (or just done, `goes`): start nothing."""
    p = presses_of(win).get(key)
    if goes and p.state == service.DONE:
        return None
    if not p.press():
        return None
    _painted[p] = (control, None, _which(control))
    if control is None and at is None:
        at = bar_mark(win)
    if busy and win is not None:
        _busy[p] = busy
        _hold(win, key, busy)
    if at is not None:
        _at[p] = at
        try:
            at.on()
        except Exception as e:              # (A-10, as the arc's: a mark that couldn't be painted holds nothing)
            print(f"A press's mark wasn't painted: {e!r}", file=sys.stderr)
    if control is not None:
        try:
            _paint(p, control)
            control.repaint()
        except Exception as e:              # A-10: an arc that couldn't be painted never holds the press — the work
            print(f"A press's arc wasn't painted: {e!r}", file=sys.stderr)    # still starts, and its end ends it
    return p


def end(p, win=None, failed=False, why=None):
    """The press's work ended: done, or `failed` (`why`); its arc off, its held line let go."""
    if failed:
        p.failed(why)
    else:
        p.done()
    _restore(p, win)


def adopt(control, key, win=None):
    """A control made again while its press is live (a card rebuilt): the arc on it, and it is the one put back — the
    control that was pressed (its "action" property: one key may stand for a card's answers, A-5). Only `win`'s
    presses (A-11). -> True when it did."""
    p = presses_of(win).find(key)
    got = _painted.get(p) if p is not None and p.live() else None
    if got is None or got[0] is None or got[2] != _which(control):
        return False
    _unmark(got[1])
    _paint(p, control)
    return True


def mark(control):
    """What shows `control`'s live press (its arc, or its own look), or None (tests, captures)."""
    for c, got, _which_one in _painted.values():
        if c is control and got is not None and not (isinstance(got, QObject) and sip.isdeleted(got)):
            return got
    return None


def arc(control):
    """The turning arc on `control` while its press is live, or None (tests, captures)."""
    got = mark(control)
    return got if isinstance(got, _Arc) else None


def arc_rect(control):
    """The arc's widget in `control`, taking no room of the layout's: around `arc_box` at the screen's own ratio, a
    pixel spare each side (where the arc is snapped to is worked out again as it is painted)."""
    box = arc_box(control)
    left, top = math.floor(box.left()) - 1, math.floor(box.top()) - 1
    return QRect(left, top, math.ceil(box.right()) + 1 - left, math.ceil(box.bottom()) + 1 - top)


def arc_box(control, to_device=None):
    """Where the arc is drawn in `control` (logical px, ARC square): its middle on the button's middle as the screen
    draws it, and midway between the end of its words (centred in it) and its right border's inner edge (2 px while it
    has focus, as a click gives it: the words never move, the arc keeps its middle).
    `to_device` (a painter's `deviceTransform`, mapped from `control`'s top left; None: the screen's ratio at the
    control's place in its window) says where the device's pixels fall — a box's edges land on whole ones, half up, so
    the arc's middle is put on theirs, on a half pixel (an antialiased arc's ink is then even on both sides)."""
    if to_device is None:
        at, dpr = control.mapTo(control.window(), QPoint(0, 0)), control.devicePixelRatioF()
        to_device = QTransform(dpr, 0, 0, dpr, at.x() * dpr, at.y() * dpr)
    back, _ok = to_device.inverted()
    w, h = control.width(), control.height()
    top_left, bottom_right = to_device.map(QPointF(0, 0)), to_device.map(QPointF(w, h))
    snap = lambda v: math.floor(v + 0.5)                     # noqa: E731 — an edge as it is drawn (half up)
    cy = (snap(top_left.y()) + snap(bottom_right.y())) / 2
    advance = control.fontMetrics().horizontalAdvance(control.text())
    if control.property("presses") == "end":                  # a link's words at its left, its room at its right end
        words = to_device.map(QPointF(advance, 0)).x()
    else:
        words = to_device.map(QPointF((w + advance) / 2, 0)).x()
    line = 2 if control.hasFocus() else 1                   # the border: 1 px, 2 focused (a click focuses it)
    border = to_device.map(QPointF(w - line, 0)).x()       # its inner edge (drawn antialiased: not snapped)
    cx = math.floor((words + border) + 0.5) / 2              # midway, on a half pixel
    centre = back.map(QPointF(cx, cy))
    return QRectF(centre.x() - ARC / 2, centre.y() - ARC / 2, ARC, ARC)


class _Arc(motion.Spinner):
    """The spin's arc on a pressed button: the spinner's clock and rules, drawn in `arc_box` — worked out at each paint,
    so it lands on the device's pixels as the button does wherever the button is and whatever the ratio."""

    def __init__(self, control):
        super().__init__("spin", control, size=ARC)
        self.control = control

    def paintEvent(self, _event):
        if not self.running or sip.isdeleted(self.control):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = arc_box(self.control, QTransform.fromTranslate(-self.x(), -self.y()) * p.deviceTransform())
        motion.spin_arc(p, box.translated(-self.x(), -self.y()), self.phase if self.on_clock else None,
                        style.qcolor(style.colours()["accent"]))
        p.end()


class _Follow(QObject):
    """A mark kept on its place as its control is resized (a card's width follows the window)."""

    def __init__(self, control, widget, place):
        super().__init__(widget)
        self.control, self.widget, self.place = control, widget, place
        control.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.control and event.type() == QEvent.Type.Resize and not sip.isdeleted(self.widget):
            self.place()
        return False


class _Own:
    """A control's own look for its press (`press_look(on)`: the known count's underline filling)."""

    def __init__(self, control):
        self.control = control
        control.press_look(True)

    def stop(self):
        if not sip.isdeleted(self.control):
            self.control.press_look(False)


def _which(control):
    """Which of a card's controls it is: its "action" (and its "line", a line's own answer)."""
    return None if control is None else (control.property("action"), control.property("line"))


def _paint(p, control):
    if hasattr(control, "press_look"):
        _painted[p] = (control, _Own(control), _which(control))
        return
    spinner = _Arc(control)
    _painted[p] = (control, spinner, _which(control))
    _place(spinner, arc_rect(control))      # over the control's own room: no layout, nothing moves
    _Follow(control, spinner, lambda: _place(spinner, arc_rect(control)))
    spinner.raise_()
    spinner.show()
    spinner.set_running(True)


def _place(spinner, r):
    spinner.setFixedSize(r.size())
    spinner.move(r.topLeft())


def _unmark(got):
    if got is None:
        return
    if isinstance(got, _Own):
        got.stop()
        return
    if not sip.isdeleted(got):
        got.set_running(False)
        got.hide()
        got.deleteLater()


def _restore(p, win):
    got = _painted.pop(p, None)
    _busy.pop(p, None)
    if not _gone(win) and hasattr(win, "unsay"):
        win.unsay(p.key)
    if got is not None:
        _unmark(got[1])
    at = _at.pop(p, None)
    if at is not None:
        try:
            at.off()
        except Exception as e:
            print(f"A press's mark wasn't taken off: {e!r}", file=sys.stderr)


def _gone(obj):
    """None, or a Qt object already deleted (a plain stand-in, tests' windows, is never gone)."""
    return obj is None or (isinstance(obj, sip.simplewrapper) and sip.isdeleted(obj))


def _line(win):
    """The line a window's held words show in: the main window's bar, a secondary window's status line."""
    return getattr(win, "bar_line", None) or getattr(win, "status", None)


def _hold(win, key, words):
    """`words` held in `win`'s line for the press `key`, painted before this returns."""
    if _gone(win) or not hasattr(win, "say"):
        return
    win.say(words, hold=key)
    line = _line(win)
    if line is not None and line.isVisible():
        line.repaint()


# --- what a menu's press marks (IK-2) ------------------------------------------------------------------------------ #
class _Nowhere:
    """A press whose caller marks the thing itself (`mine_actions`: the pills of every list)."""

    def on(self):
        pass

    def off(self):
        pass


NOWHERE = _Nowhere()


class BarArc(motion.Spinner):
    """The accent arc in a window's bar slot while a menu's press with nothing of its own on screen is live, no words
    (IK-2). The main window's is laid out at the right end of its bar's slot, hidden at rest (shown, the stretching
    slot gives it its room: nothing moves); a secondary window's (`corner`) is laid over the bottom right corner of
    its padding, beside its status line, taking no room. Shown while any of its marks is on."""

    def __init__(self, parent, corner=False):
        super().__init__("spin", parent, size=ARC)
        self.marks = 0
        self.corner = corner
        self.setVisible(False)
        if corner:
            _Follow(parent, self, self._place)

    def _place(self):
        host = self.parentWidget()
        m = host.layout().contentsMargins() if host.layout() is not None else None
        right, bottom = (m.right(), m.bottom()) if m is not None else (ARC, ARC)
        self.move(host.width() - round((right + ARC) / 2), host.height() - round((bottom + ARC) / 2))

    def hold(self):
        self.marks += 1
        if self.marks == 1:
            if self.corner:
                self._place()
            self.show()
            self.raise_()
            self.set_running(True)
        self.repaint()

    def let_go(self):
        self.marks = max(0, self.marks - 1)
        if not self.marks:
            self.set_running(False)
            self.hide()


class _BarMark:
    def __init__(self, arc):
        self.arc = arc

    def on(self):
        if not sip.isdeleted(self.arc):
            self.arc.hold()

    def off(self):
        if not sip.isdeleted(self.arc):
            self.arc.let_go()


def bar_mark(win):
    """The accent arc in `win`'s bar slot (its `bar_arc`), no words: what a menu's press marks when nothing it acts on
    is on screen — the default of `run` / `begin` / `open` with no control and no `at`. None: `win` has no bar."""
    arc = getattr(win, "bar_arc", None) if win is not None else None
    return _BarMark(arc) if arc is not None and not sip.isdeleted(arc) else None


class _RowMark:
    def __init__(self, view, ids, part):
        self.view, self.ids, self.part = view, tuple(ids), part
        self.bar = None

    def on(self):
        if not self.view.mark_ids(self.ids, self.part):      # none of them on this list: the bar's arc instead
            self.bar = bar_mark(self.view.window())
            if self.bar is not None:
                self.bar.on()

    def off(self):
        if not sip.isdeleted(self.view):
            self.view.unmark(self.ids)
        if self.bar is not None:
            self.bar.off()


def row_mark(view, ids, part="more"):
    """The files `ids` in the list `view` (a `RowsView`) marked while the press is live: the accent arc turns on each
    one's line at `part` — where it was pressed from: "more" (its ⋯), "play" (▶; the hero's: its cover), a status
    action's name (its pill: "no-media"), "journey" (the hero's ↗), "cover" — on a closed row's line, the hero, or the
    episode's own line when its row is open; painted before `on` returns (`RowsView.mark_ids`). None of them on that
    list: the bar's arc. The one rule for a file's line, as *Mine now*'s turning pill is the one for an ask
    (`RowsView.press_ids`)."""
    return _RowMark(view, ids, part)


class _WidgetMark:
    def __init__(self, widget):
        self.widget, self.spinner = widget, None

    def on(self):
        w = self.widget
        if sip.isdeleted(w):
            return
        s = self.spinner = motion.Spinner("spin", w, size=ARC)

        def place():
            s.move((w.width() - ARC) // 2, (w.height() - ARC) // 2)
        place()
        _Follow(w, s, place)
        s.raise_()
        s.show()
        s.set_running(True)
        w.repaint()

    def off(self):
        s, self.spinner = self.spinner, None
        if s is not None and not sip.isdeleted(s):
            s.set_running(False)
            s.hide()
            s.deleteLater()


def widget_mark(widget):
    """The accent arc over the middle of `widget` (a cover, a tile) while the press is live, taking no room of its
    layout's; painted before `on` returns."""
    return _WidgetMark(widget)


# --- after the press: a worker's report, a registry job ---------------------------------------------------------- #
def report(p, win, kind, value=None):
    """A live press's next state, on the window's thread: `("wait", why)` — waiting, `why` held in the bar (a wait
    worth naming); `("run", step)` — running, the press's own words (`busy`) with `step` held, or none; `("stopping",)`
    — stopping. An answer after the press ended moves nothing."""
    if not p.live():
        return
    if kind == "wait":
        p.wait(value)
        words = value or _busy.get(p)
    elif kind == "run":
        p.run(value)
        words = " · ".join(w for w in (_busy.get(p), value) if w) or None
    elif kind == "stopping":
        p.stopping()
        words = _busy.get(p)
    else:
        return
    if words:
        _hold(win, p.key, words)
    elif not _gone(win) and hasattr(win, "unsay"):
        win.unsay(p.key)


def relay(p, win=None):
    """A worker's word to the press `p`: `relay.call(("wait", why))`, `relay.call(("run", step))`,
    `relay.call(("stopping",))`, from any thread, painted on the window's (`report`). Make it on the window's thread;
    with `win` gone, a call is dropped."""
    r = bridge.Relay(win if isinstance(win, QObject) else None)
    r.said.connect(lambda what: report(p, win, *(what if isinstance(what, tuple) else (what,))))
    return r


def _jobs_signal(win):
    for host in (win, getattr(win, "shell", None)):
        heard = getattr(host, "bridge", None) if host is not None else None
        if heard is not None and hasattr(heard, "jobs_changed"):
            return heard.jobs_changed
    return None


def follow(p, registry, job_id, win=None):
    """A registry job's states become the press `p`'s (the `importers._follow` pattern, shared): queued stays queued,
    waiting — its reason held in the bar —, running — its step —, cancelling, then done, or failed with its message;
    a job no longer listed has ended (done). Read now from `registry.snapshot()`, then from the window's
    `bridge.jobs_changed` (a secondary window's: its main window's), on the window's thread. -> `p`."""
    seen = {"job": False, "last": None}
    signal = _jobs_signal(win)
    hooked = []

    def stop():
        if hooked and signal is not None:
            try:
                signal.disconnect(hooked[0])
            except (TypeError, RuntimeError):
                pass
        hooked.clear()

    def look(views):
        if not p.live():
            stop()
            return
        view = next((v for v in views if v.id == job_id), None)
        if view is None:
            if seen["job"]:                         # it ended and was let go between two snapshots
                stop()
                end(p, win)
            return
        seen["job"] = True
        state = (view.state, view.reason, view.progress)
        if state == seen["last"]:
            return
        seen["last"] = state
        if view.state == jobs_module.WAITING:
            report(p, win, "wait", view.reason)
        elif view.state == jobs_module.RUNNING:
            pr = view.progress
            step = None
            if pr is not None and (pr.step or pr.total):
                step = " ".join(x for x in (pr.step, f"{pr.done} / {pr.total}" if pr.total else None) if x)
            report(p, win, "run", step)
        elif view.state == jobs_module.CANCELLING:
            report(p, win, "stopping")
        elif view.state == jobs_module.DONE:
            stop()
            end(p, win)
        elif view.state == jobs_module.FAILED:
            stop()
            end(p, win, failed=True, why=view.message)
    if signal is not None:
        hooked.append(look)
        signal.connect(look)
    look(registry.snapshot())
    return p


# --- another program, a folder, a link (the O and X classes) ------------------------------------------------------ #
def open_now(target):
    """(A worker.) `target` opened in the user's own program: a link through `windows.open_url` (IK-17:
    `QDesktopServices`, COM set up around it), a path — a file, a folder, a program — through
    `screens.open_with_system` (as ▶'s file and the logs folder open, AD-9: COM set up). Raises when it couldn't."""
    from app.qt import screens, windows
    if "://" in target:
        if not windows.open_url(target):
            raise OSError(strings.OPEN_NOT_OPENED)
    else:
        screens.open_with_system(target)


def open(win, target, control=None, key=None, at=None, then=None, failed=None):  # noqa: A001 — the press's verb
    """Another program, a folder or a link opened for a press: `control` marked (or `at`; neither: the bar's arc) and
    painted, then the open on a worker — never on the window's thread — and done when the call returned. `target`: a
    path or a link, or a callable worked out on that worker first (a lookup: `isdir`, the episode to play) returning
    one, or None — nothing to open (`then(None)`). `then(target)` once opened; `failed(info)`, else the reason in the
    bar (`OPEN_FAILED`). `key`: the press's (default `open:<target>`; a callable target needs its own).
    -> the press, or None while it is live (a second press does nothing)."""
    if key is None:
        key = f"open:{target}"

    resolved = []

    def work():
        t = target() if callable(target) else target
        if not t:
            return None
        resolved.append(t)
        open_now(t)
        return t

    def broke(info):
        if failed is not None:
            failed(info)
        elif not _gone(win) and hasattr(win, "say"):
            name = resolved[0] if resolved else target if isinstance(target, str) else ""
            if "://" not in name:
                name = os.path.basename(name.rstrip("\\/")) or name
            win.say(strings.OPEN_FAILED.format(name=name or strings.OPEN_IT, why=info[0] if info else ""))
    return run(control, key, work, then=then, failed=broke, win=win, at=at)
