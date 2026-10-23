"""A press painted (round 8 row 45; the scope `row45-54-scope.md` §3, Sonic's Q1 answer): the state of
`app/services/press.py` on its control, so every press reacts in the frame it happens in.

Sonic (Q1): "It cannot gray out … If it's an icon I'd rather it not have words … a very nice and theme-looking spin
arc … subtle but clean." So a pressed control keeps its colours and its words: a small accent arc turns at its right
edge (`motion.Spinner("spin")`, the button's right padding grown to hold it: `style`'s `[pressing="true"]`) until the
work ends. A second press meanwhile does nothing (`Press.live`), never by greying.

`run(control, key, fn, …)` does, in order: the press, the arc on the control, `control.repaint()` — which paints
before it returns — and only then hands `fn` to the worker. Its answer ends the press (done, or failed with why) and
takes the arc off. Words only where they are meant: `busy` (None by default) is held in the bar's slot while the press
is live (`ShellWindow.say(…, hold=)`) — a menu's press, whose menu has closed, or a wait worth naming; a failure's
reason goes to the bar through the caller's `failed`. A control rebuilt while its press is live takes the arc again
(`adopt`).

Left for P3: a worker's report of a wait or a step (`relay`), a registry job followed (`follow`), another program
opened off the window's thread (`open`).
"""
import sys

from PyQt6 import sip
from PyQt6.QtWidgets import QHBoxLayout

from app import theme
from app.qt import bridge, motion, style
from app.services import press as service

ARC_INSET = 8                   # px from the arc to the control's right edge (× the text size; `style`'s room for it)

_loose = service.Presses()      # the presses of a control with no window
_painted = {}                   # Press -> (control or None, the arc or None)


def presses_of(win):
    got = getattr(win, "presses", None) if win is not None else None
    return got if got is not None else _loose


def run(control, key, fn, *args, busy=None, then=None, failed=None, win=None, goes=False):
    """`control` pressed for the action `key` (an action's name with what it acts on): `fn(*args)` on a worker once
    the arc is painted; `then(value)` / `failed((exception, its traceback's text))` as `bridge.run_in_worker`'s, once
    the arc is off. `control` None: a menu's press (the hairline runs; `busy`, if given, in the bar). `goes`: the
    control goes when done (a Needs-you card's answer) — a press in the moment before it goes does nothing.
    -> the press, or None when it was live (or just done, `goes`): nothing started."""
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

    def ended(value):
        p.done()
        _restore(p, win)
        if then is not None:
            then(value)

    def broke(info):
        p.failed(info[0] if info else None)
        _restore(p, win)
        if failed is not None:
            failed(info)
        else:
            print(f"A background task failed: {info[1]}", file=sys.stderr)
    bridge.run_in_worker(fn, *args, then=ended, failed=broke)
    return p


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


def _paint(p, control):
    control.setProperty("pressing", True)
    _restyle(control)                       # the right padding grows to hold the arc; the words stay where they are
    spinner = motion.Spinner("spin", control)
    lay = control.layout()
    if lay is None:
        lay = QHBoxLayout(control)
        lay.addStretch(1)
    lay.setContentsMargins(0, 0, round(ARC_INSET * theme.text_factor(style.current()[1])), 0)
    lay.addWidget(spinner)
    lay.activate()                          # placed now: the repaint that follows paints it where it stays
    spinner.show()
    spinner.set_running(True)
    _painted[p] = (control, spinner)


def _unspin(spinner):
    if spinner is not None and not sip.isdeleted(spinner):
        spinner.set_running(False)
        spinner.hide()
        spinner.deleteLater()


def _restore(p, win):
    got = _painted.pop(p, None)
    if win is not None and not sip.isdeleted(win) and hasattr(win, "unsay"):
        win.unsay(p.key)
    if got is None or got[0] is None:
        return
    control, spinner = got
    _unspin(spinner)
    if sip.isdeleted(control):
        return
    control.setProperty("pressing", False)
    _restyle(control)


def _restyle(control):
    control.style().unpolish(control)
    control.style().polish(control)
    control.updateGeometry()
    holder = control.parentWidget()
    if holder is not None and holder.layout() is not None:
        holder.layout().activate()          # its new width laid out before the repaint, not a frame after
