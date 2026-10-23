"""A press painted (round 8 row 45; the scope `row45-54-scope.md` §3, Sonic's Q1 answer): the state of
`app/services/press.py` on its control, so every press reacts in the frame it happens in.

Sonic (Q1): "It cannot gray out … If it's an icon I'd rather it not have words … a very nice and theme-looking spin
arc … subtle but clean." So a pressed control keeps its colours and its words: a small accent arc turns in it
(`motion.Spinner("spin")`) until the work ends. A second press meanwhile does nothing (`Press.live`), never by greying.

**Nothing moves** (the round 8 trial; P1 widened the button as it was pressed, and its neighbour slid ~17 px): the arc
takes no layout space. A button that will be pressed keeps the arc's room at rest (`room`: its padding, both sides, so
its words stay centred — `theme.SIZES["press-room"]`), and the arc, a child of the button laid over it, turns centred
in its right padding: the button keeps its size, its words stay where they are, no neighbour moves. A control with a
place of its own for it says where (`press_arc()`: the known-words corner's slot at its left).

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
from PyQt6.QtCore import QEvent, QObject, QRect

from app import theme
from app.qt import bridge, motion, style
from app.services import press as service

ARC = 14                        # px: the arc's side (the spinner's own)

_loose = service.Presses()      # the presses of a control with no window
_painted = {}                   # Press -> (control or None, the arc or None)


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
    _unspin(_painted[p][1])
    _paint(p, control)
    return True


def arc(control):
    """The turning arc on `control` while its press is live, or None (tests, captures)."""
    for p, (c, spinner) in _painted.items():
        if c is control and spinner is not None and not sip.isdeleted(spinner):
            return spinner
    return None


def arc_rect(control):
    """Where the arc sits in `control`, taking no room of the layout's: the control's own place for it
    (`press_arc()`), else centred in a button's right padding (`room`'s, × the text size; the border's 1 px outside)."""
    own = getattr(control, "press_arc", None)
    if own is not None:
        return own()
    pad = theme.size("press-room", style.current()[1])
    x = round(control.width() - 1 - (pad + ARC) / 2)
    return QRect(x, (control.height() - ARC) // 2, ARC, ARC)


class _Follow(QObject):
    """The arc kept on its place as its control is resized (a card's width follows the window)."""

    def __init__(self, control, spinner):
        super().__init__(spinner)
        self.control, self.spinner = control, spinner
        control.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.control and event.type() == QEvent.Type.Resize and not sip.isdeleted(self.spinner):
            _place(self.spinner, arc_rect(self.control))
        return False


def _paint(p, control):
    r = arc_rect(control)
    spinner = motion.Spinner("spin", control, size=r.width())
    _place(spinner, r)                      # over the control's own room: no layout, nothing moves
    _Follow(control, spinner)
    spinner.raise_()
    spinner.show()
    spinner.set_running(True)
    _painted[p] = (control, spinner)


def _place(spinner, r):
    spinner.setFixedSize(r.size())
    spinner.move(r.topLeft())


def _unspin(spinner):
    if spinner is not None and not sip.isdeleted(spinner):
        spinner.set_running(False)
        spinner.hide()
        spinner.deleteLater()


def _restore(p, win):
    got = _painted.pop(p, None)
    if win is not None and not sip.isdeleted(win) and hasattr(win, "unsay"):
        win.unsay(p.key)
    if got is not None:
        _unspin(got[1])
