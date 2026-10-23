"""A press painted (round 8 row 45; the scope `row45-54-scope.md` §3, Sonic's Q1 answer): the state of
`app/services/press.py` on its control, so every press reacts in the frame it happens in.

Sonic (Q1): "It cannot gray out … If it's an icon I'd rather it not have words … a very nice and theme-looking spin
arc … subtle but clean." So a pressed control keeps its colours and its words: a small accent arc turns in it
(`motion.Spinner("spin")`) until the work ends. A second press meanwhile does nothing (`Press.live`), never by greying.

**Nothing moves** (the round 8 trial; P1 widened the button as it was pressed, and its neighbour slid ~17 px): the arc
takes no layout space. A button that will be pressed keeps the arc's room at rest (`room`: its padding, both sides, so
its words stay centred — `theme.SIZES["press-room"]`), and the arc, a child of the button laid over it, turns centred
in its right padding: the button keeps its size, its words stay where they are, no neighbour moves.

**Round 2 (Sonic judged the trial):** the arc is fine "for now"; beside it, a button may look *set* instead — "the
button acted as set or indented on click, and has the surasura sheen … that slowly moves across like it's thinking":
`BUTTON_LOOK` "sheen" sets it in (a shadow falling from its top edge inside it, painted over it: no restyle, which
would change its size hint) and sweeps the opened row's sheen (`rows.paint_sheen`) across it once each
`MOTION["press-sheen"]`, on the spinner's clock (`motion.Turn`: still under Reduced motion). A control with a look of its own paints it
(`press_look(on)`: the known count's underline filling).

`run(control, key, fn, …)` does, in order: the press, the arc on the control, `control.repaint()` — which paints
before it returns — and only then hands `fn` to the worker. Its answer ends the press (done, or failed with why) and
takes the arc off. Work that ends by itself elsewhere (a registry job the control follows) uses `begin` and `end`.
Words only where they are meant: `busy` (None by default) is held in the bar's slot while the press is live
(`ShellWindow.say(…, hold=)`) — a menu's press, whose menu has closed, or a wait worth naming; a failure's reason goes
to the bar through the caller's `failed`. A control rebuilt while its press is live takes the arc again (`adopt`).

Left for P3: a worker's report of a wait or a step (`relay`), a registry job followed (`follow`), another program
opened off the window's thread (`open`).
"""
import sys

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QBrush, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from app import theme
from app.qt import bridge, motion, style
from app.services import press as service

ARC = 14                        # px: the arc's side (the spinner's own)
BUTTON_LOOK = "arc"             # a pressed button: "arc" (the turning arc) or "sheen" (set in, a sheen crossing it):
#                                 PROVISIONAL, both kept for Sonic to compare (round 8, round 2)

_loose = service.Presses()      # the presses of a control with no window
_painted = {}                   # Press -> (control or None, its mark or None: a Spinner, a _Sheen or an _Own)


def room(control):
    """`control` (a button) will be pressed through `run` / `begin`: it keeps its arc's room at rest (style's
    `[presses="true"]`). Call it as the button is made, before it is laid out."""
    control.setProperty("presses", True)
    control.style().unpolish(control)
    control.style().polish(control)
    return control


def presses_of(win):
    got = getattr(win, "presses", None) if win is not None else None
    return got if got is not None else _loose


def run(control, key, fn, *args, busy=None, then=None, failed=None, win=None, goes=False):
    """`control` pressed for the action `key` (an action's name with what it acts on): `fn(*args)` on a worker once
    the arc is painted; `then(value)` / `failed((exception, its traceback's text))` as `bridge.run_in_worker`'s, once
    the arc is off. `control` None: a menu's press (the hairline runs; `busy`, if given, in the bar). `goes`: the
    control goes when done (a Needs-you card's answer) — a press in the moment before it goes does nothing.
    -> the press, or None when it was live (or just done, `goes`): nothing started."""
    p = begin(control, key, busy=busy, win=win, goes=goes)
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


def begin(control, key, busy=None, win=None, goes=False):
    """The press, painted now (the arc on `control`, `busy` held in the bar) and repainted before this returns — the
    caller starts its work after. -> the press, or None when it was live (or just done, `goes`): start nothing."""
    p = presses_of(win).get(key)
    if goes and p.state == service.DONE:
        return None
    if not p.press():
        return None
    _painted[p] = (control, None)
    if busy and win is not None:
        win.say(busy, hold=key)
        win.bar_line.repaint()
    if control is not None:
        _paint(p, control)
        control.repaint()
    return p


def end(p, win=None, failed=False, why=None):
    """The press's work ended: done, or `failed` (`why`); its arc off, its held line let go."""
    if failed:
        p.failed(why)
    else:
        p.done()
    _restore(p, win)


def adopt(control, key):
    """A control made again while its press is live (a card rebuilt): the arc on it, and it is the one put back.
    -> True when it did."""
    p = next((q for q in _painted if q.key == key and q.live()), None)
    if p is None or _painted[p][0] is None:
        return False
    _unmark(_painted[p][1])
    _paint(p, control)
    return True


def mark(control):
    """What shows `control`'s live press (its arc, its sheen, its own look), or None (tests, captures)."""
    for _p, (c, got) in _painted.items():
        if c is control and got is not None and not (isinstance(got, QObject) and sip.isdeleted(got)):
            return got
    return None


def arc(control):
    """The turning arc on `control` while its press is live, or None (tests, captures)."""
    got = mark(control)
    return got if isinstance(got, motion.Spinner) else None


def arc_rect(control):
    """Where the arc sits in `control`, taking no room of the layout's: centred in a button's right padding (`room`'s,
    × the text size; the border's 1 px outside)."""
    pad = theme.size("press-room", style.current()[1])
    x = round(control.width() - 1 - (pad + ARC) / 2)
    return QRect(x, (control.height() - ARC) // 2, ARC, ARC)


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


class _Sheen(QWidget):
    """Round 2's button look: the button set in (a shadow down from its top edge) and the sheen sweeping across it,
    laid over the whole button (no layout; it takes no clicks), clipped to its rounded box."""

    def __init__(self, control):
        super().__init__(control)
        self.control = control
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(control.rect())
        _Follow(control, self, lambda: self.setGeometry(self.control.rect()))
        self.turn = motion.Turn(self, self.update, period="press-sheen")
        self.turn.show()
        self.turn.set_running(True)

    def stop(self):
        self.turn.set_running(False)

    def paintEvent(self, _event):
        from app.qt import rows
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = theme.RADII["button-sm" if self.control.property("size") == "sm" else "button"]
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        p.setClipPath(clip)
        depth = rows.rl("press-inset")                  # set in: the shadow falling from the top edge
        shade = QLinearGradient(QPointF(0, 1), QPointF(0, 1 + depth))
        shade.setColorAt(0, rows.faded("shadow", rows.rl("press-inset-alpha")))
        shade.setColorAt(1, rows.faded("shadow", 0.0))
        p.fillRect(QRectF(0, 1, self.width(), depth), QBrush(shade))
        w = self.width()
        band = w * 0.4 * 0.46                   # the band's centre along its gradient (`rows.paint_sheen`)
        phase = self.turn.turning
        # still (Reduced motion, the freeze switch): the band at the middle; turning: from past the left to past the right
        dx = w / 2 - band if phase is None else -band - w * 0.2 + phase * w * 1.4
        rows.paint_sheen(p, self.rect(), rows.rl("press-sheen-alpha"), dx)
        p.end()


class _Own:
    """A control's own look for its press (`press_look(on)`)."""

    def __init__(self, control):
        self.control = control
        control.press_look(True)

    def stop(self):
        if not sip.isdeleted(self.control):
            self.control.press_look(False)


def _paint(p, control):
    if hasattr(control, "press_look"):
        _painted[p] = (control, _Own(control))
        return
    if BUTTON_LOOK == "sheen":
        sheen = _Sheen(control)
        sheen.raise_()
        sheen.show()
        _painted[p] = (control, sheen)
        return
    spinner = motion.Spinner("spin", control, size=ARC)
    _place(spinner, arc_rect(control))      # over the control's own room: no layout, nothing moves
    _Follow(control, spinner, lambda: _place(spinner, arc_rect(control)))
    spinner.raise_()
    spinner.show()
    spinner.set_running(True)
    _painted[p] = (control, spinner)


def _place(spinner, r):
    spinner.setFixedSize(r.size())
    spinner.move(r.topLeft())


def _unmark(got):
    if got is None:
        return
    if isinstance(got, _Own):
        got.stop()
        return
    if sip.isdeleted(got):
        return
    if isinstance(got, _Sheen):
        got.stop()
    else:
        got.set_running(False)
    got.hide()
    got.deleteLater()


def _restore(p, win):
    got = _painted.pop(p, None)
    if win is not None and not sip.isdeleted(win) and hasattr(win, "unsay"):
        win.unsay(p.key)
    if got is not None:
        _unmark(got[1])
