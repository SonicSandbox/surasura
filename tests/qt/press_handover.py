"""Round 8 row 45 (P5): what a press had painted at the moment its work was handed over — one helper for every
window's paint-before-work test (Settings, the wizard, the secondary windows, the modules' windows).

`HandOver(monkeypatch, widget, shown)`: `bridge.run_in_worker` wrapped — at each hand-over it records the function's
name, `shown()` (the press's mark, as the test reads it: the arc turning on the button, the corner arc, the counts'
mark) and how many times `widget` had been painted since, then runs the work as before. `at(name)` -> that
hand-over's record. A worker that `press.open` starts is recorded the same way (its function is `work`)."""
from types import SimpleNamespace

from PyQt6.QtCore import QEvent, QObject

from app.qt import bridge
from app.qt import press as qpress


class Paints(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.n = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.n += 1
        return False


def arc_turning(control):
    """The arc on `control` shown and turning (its press live)."""
    spinner = qpress.arc(control)
    return spinner is not None and spinner.isVisible() and spinner.running


def corner_turning(win):
    """A secondary window's corner arc (a press with no control of its own) shown and turning."""
    arc = getattr(win, "bar_arc", None)
    return arc is not None and arc.isVisible() and arc.running


class HandOver(list):
    def __init__(self, monkeypatch, widget, shown):
        super().__init__()
        self.paints = Paints(widget)
        self.before = self.paints.n
        real = bridge.run_in_worker

        def stub(fn, *args, then=None, failed=None, **kw):
            self.append(SimpleNamespace(name=getattr(fn, "__name__", repr(fn)), shown=shown(),
                                        painted=self.paints.n - self.before))
            return real(fn, *args, then=then, failed=failed, **kw)
        monkeypatch.setattr(bridge, "run_in_worker", stub)

    def at(self, name):
        return next(h for h in self if h.name == name)
