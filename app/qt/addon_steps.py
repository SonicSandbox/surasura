"""AnkiConnect missing, on screen (alpha 8, Mado-A): the one part setup's Anki step, Settings' *Connection* row and
*Needs you*'s Anki line (Mado-N) show when AnkiConnect may be missing (`ankiconnect_addon.needs_addon`), and the one
watch that runs *Check again* by itself.

- **`AddonSteps`**: *Copy code* (2055492159 on the clipboard; its press says *Copied* at once, its name again
  `COPIED_MS` later, the button never narrower meanwhile) beside the three steps on one line. The host hands its own
  button maker, so the part wears the host's look (the wizard's buttons, Settings' doors).
- **`Watch`**: while armed and its widget is on screen and live (not under the setup wizard, which disables the
  window's parts), every `EVERY` s on the shell's status poll (the window's one existing timer, `ShellWindow._poll`;
  none, no watch) it takes the light look (`ankiconnect_addon.answers`, on a worker, one at a time) and, the first
  time it has news (AnkiConnect answers; an Anki opened where the last look saw none), calls the host's *Check again*.
  Nothing loops: a tick off screen, unarmed or with a look out is a flag read; it stops with its widget.
"""
import time

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from app import ankiconnect_addon as A
from app.qt import bridge


class AddonSteps(QWidget):
    """*Copy code* + the steps. `button(text, tip)` -> a button in the host's look; `say(text)`: the host's bar line
    (the press's words for where to paste it); `name`: the steps' label's object name (its style)."""

    def __init__(self, button, name, say=None, parent=None):
        super().__init__(parent)
        self.say = say
        self._copies = 0
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.copy = button(A.COPY, A.COPY_TIP)
        self.copy.setAccessibleName(A.COPY)
        self.copy.clicked.connect(lambda _c=False: self.copy_code())
        row.addWidget(self.copy, 0, Qt.AlignmentFlag.AlignVCenter)
        self.line = QLabel(A.steps_line(), self)
        self.line.setObjectName(name)
        self.line.setTextFormat(Qt.TextFormat.PlainText)
        self.line.setWordWrap(True)
        row.addWidget(self.line, 1)

    def set_unsure(self, unsure):
        """*Open Anki* first when the look couldn't tell a closed Anki from AnkiConnect missing."""
        text = A.steps_line(unsure=bool(unsure))
        if self.line.text() != text:
            self.line.setText(text)

    def copy_code(self):
        QApplication.clipboard().setText(A.CODE)
        self.copy.setMinimumWidth(self.copy.width())      # *Copied* is shorter: the button keeps its width
        self.copy.setText(A.COPIED)
        self._copies = press = self._copies + 1           # a second press restarts the wait

        def back():
            if not sip.isdeleted(self.copy) and self._copies == press:
                self.copy.setText(A.COPY)
        QTimer.singleShot(A.COPIED_MS, back)
        if self.say is not None:
            self.say(A.COPIED_LINE)


def ticker(shell):
    """The shell's status poll (`POLL_MS`), the timer the watch rides; None for a shell without one."""
    timer = getattr(shell, "_poll", None)
    return timer if isinstance(timer, QTimer) else None


class Watch(QObject):
    """*Check again* by itself. `widget`: the part whose being on screen keeps it looking; `timer`: the tick (`ticker`);
    `url()`: the AnkiConnect address now; `answered()`: the host's *Check again*. `arm(on)` as the part shows."""

    def __init__(self, widget, timer, url, answered):
        super().__init__(widget)
        self.widget, self.url, self.answered = widget, url, answered
        self.armed = False
        self.seen = None                  # the host's last look: an Anki process seen True, none False, can't tell None
        self.looking = False
        self._last = 0.0
        self._timer = timer
        if timer is not None:
            timer.timeout.connect(self._tick)
            self.destroyed.connect(lambda _o=None, t=timer: _disconnect(t, self._tick))

    def arm(self, on, seen=None):
        """On: the first light look `EVERY` s from now (the host has just looked); off: none. `seen`: the host's look's
        `running` (False: the light look watches for an Anki opened too)."""
        on = bool(on)
        if on and not self.armed:
            self._last = time.monotonic()
        self.armed, self.seen = on, seen

    def _tick(self):
        if not self.armed or self.looking or not self._live():
            return
        now = time.monotonic()
        if now - self._last < A.EVERY:
            return
        self._last = now
        self.looking = True
        bridge.run_in_worker(A.answers, self.url(), self.seen, then=self._looked,
                             failed=lambda _info: self._looked(False))

    def _looked(self, ok):
        if sip.isdeleted(self):
            return
        self.looking = False
        self._last = time.monotonic()
        if ok and self.armed and self._live():
            self.armed = False                            # once: the host's look arms it again if Anki still isn't in
            self.answered()


    def _live(self):
        """Its part on screen and taking input (the setup wizard over the window disables the parts under it)."""
        return not sip.isdeleted(self.widget) and self.widget.isVisible() and self.widget.isEnabled()


def _disconnect(timer, slot):
    try:
        if not sip.isdeleted(timer):
            timer.timeout.disconnect(slot)
    except (TypeError, RuntimeError):
        pass
