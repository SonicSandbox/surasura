"""Toasts (M2.1; the window's spec 05 §5.4, A4 *Motion*, A2's toast list): the mock's one toast.

One at a time, bottom centre, its bottom 48 px above the window's (the mock's `.toast`), at most 92 % of the window's
width, the message on one line (elided when too long). It rises 12 px in 260 ms as it opens (`motion.open_overlay`,
"rise"), stays 6.5 s (12 s for the Anki offer: `long=True`), and closes. *Undo* (when the action can be undone) and up to
two more buttons; a click runs its callback and closes the toast. A new toast replaces the one shown **without rising
again** (the mock's `.steady`), with its own time. **Hidden while dragging** (`set_dragging(True)`: a toast never covers
the buckets): no input, its time still running; after the drop it is back, unanimated, if its time hasn't run out.

The message is plain text (a title is never read as markup). The window never waits on a toast; what Undo does is the
caller's (W3.1's undo stack).
"""
from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy

from app import theme
from app.qt import motion, shadow, strings, style

MAX_BUTTONS = 3                                 # Undo + two (the mock's widest: [Mine it too] [Remove unstudied cards])
WIDTH_SHARE = 0.92                              # the mock's max-width: 92 %
PAD = (16, 10, 12, 10)                          # left, top, right, bottom (the mock's `padding: 10px 12px 10px 16px`)


class ToastCard(motion.Overlay):
    """The toast itself: the `toast` fill, a `line-hi` border, radius 12; the message and its buttons."""
    how = "rise"
    shadow_name = "toast"

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # a toast never takes the keyboard from the window
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        row = QHBoxLayout(self)
        f = theme.text_factor(style.current()[1])
        row.setContentsMargins(*(round(v * f) for v in PAD))
        row.setSpacing(round(12 * f))
        self.text = QLabel(self)
        self.text.setObjectName("toasttext")
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.text, 1)
        self.buttons = []                   # made as a toast first needs them, each wired once (the wiring check)
        self._callbacks = []
        self.message = ""

    def _button(self, i):
        while len(self.buttons) <= i:
            b = QPushButton(self)
            b.setProperty("size", "sm")
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)       # reachable by Tab; a click never takes the keyboard
            b.clicked.connect(lambda _c=False, n=len(self.buttons): self._press(n))
            self.layout().addWidget(b)
            self.buttons.append(b)
        return self.buttons[i]

    def _press(self, n):
        if n < len(self._callbacks) and self._callbacks[n] is not None:
            self._callbacks[n]()

    def set_content(self, message, actions):
        """`actions`: [(label, tooltip, callback)], at most MAX_BUTTONS."""
        self.message = message
        self.setAccessibleName(message)
        actions = actions[:MAX_BUTTONS]
        self._callbacks = [callback for _label, _tip, callback in actions]
        for i, (label, tip, _callback) in enumerate(actions):
            b = self._button(i)
            b.setText(label)
            b.setToolTip(tip)
            b.setAccessibleName(label)
            b.setVisible(True)
        for b in self.buttons[len(actions):]:
            b.setVisible(False)

    def natural_width(self):
        """The width that shows the whole message and the buttons."""
        lay = self.layout()
        m = lay.contentsMargins()
        width = QFontMetrics(self.text.font()).horizontalAdvance(self.message) + 2
        for b in self.buttons:
            if not b.isHidden():
                width += lay.spacing() + b.sizeHint().width()
        return width + m.left() + m.right()

    def fit_text(self):
        fm = QFontMetrics(self.text.font())
        self.text.setText(fm.elidedText(self.message, Qt.TextElideMode.ElideRight, max(0, self.text.width())))
        self.text.setToolTip(self.message if self.text.text() != self.message else "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_text()

    def paintEvent(self, _event):
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(style.qcolor(c["line-hi"]), 1))
        p.setBrush(style.qcolor(theme.FIXED["toast"]))
        radius = theme.RADII["toast"]
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.end()


class ToastHost(QObject):
    """The window's toasts, over `parent` (the shell's central widget). One shown at a time."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_widget = parent
        self.card = ToastCard(parent)
        self.card.hide()
        self.shadow = shadow.Follower(self.card, "toast")
        self.life = QTimer(self)
        self.life.setSingleShot(True)
        self.life.timeout.connect(self.close)
        self.dragging = False
        self.alive = False
        parent.installEventFilter(self)

    # --- showing ---------------------------------------------------------------------------------------------- #
    def show(self, message, undo=None, buttons=(), long=False):
        """Show `message` (plain text). `undo`: a callback for *Undo*; `buttons`: [(label, tooltip, callback)] — each
        click runs its callback and closes the toast. `long`: 12 s (the Anki offer), else 6.5 s."""
        opening = motion.opening_of(self.card)
        if opening is not None:
            opening.finish()                          # replaced mid-rise: the old one lands, the new one shows in place
        actions = []
        if undo is not None:
            actions.append((strings.TOAST_UNDO, strings.TOAST_UNDO_TIP, self._closing(undo)))
        actions.extend((label, tip, self._closing(cb)) for label, tip, cb in buttons)
        self.card.set_content(message, actions)
        self.alive = True
        self.life.start(theme.MOTION["toast-shown-anki" if long else "toast-shown"])
        self.place()
        self._announce(message)
        if self.dragging:
            return                                    # it shows after the drop
        if self.card.isVisible() or motion.opening_of(self.card) is not None:
            self.card.update()                        # a toast already up: replaced, never rising again
            return
        motion.open_overlay(self.card, self.card.how, self.card.shadow_name)

    def close(self):
        self.alive = False
        self.life.stop()
        self.card.hide()
        self.card._callbacks = []                     # a late click on a closed toast does nothing

    def set_dragging(self, on):
        """A drag started (True) or ended (False): hidden meanwhile; back after it, unanimated, if still alive."""
        self.dragging = bool(on)
        if self.dragging:
            self.card.hide()
        elif self.alive:
            self.place()
            self.card.show()
            self.card.raise_()

    @property
    def shown(self):
        return self.card.isVisible() or motion.opening_of(self.card) is not None

    # --- placing --------------------------------------------------------------------------------------------- #
    def place(self):
        p = self.parent_widget
        card = self.card
        card.ensurePolished()                      # the stylesheet's font, before anything is measured
        card.text.ensurePolished()
        card.layout().activate()
        height = max(card.sizeHint().height(), round(theme.size("button-sm", style.current()[1])) + 2 * PAD[1])
        width = min(card.natural_width(), int(p.width() * WIDTH_SHARE))
        x = (p.width() - width) // 2
        y = p.height() - theme.MOTION["toast-bottom"] - height
        card.setGeometry(x, y, width, height)
        card.layout().activate()                   # the text's width at this size (hidden, nothing else lays it out)
        card.fit_text()

    def eventFilter(self, obj, event):
        if obj is self.parent_widget and event.type() == QEvent.Type.Resize and self.alive:
            self.place()
        return False

    # --- the rest ---------------------------------------------------------------------------------------------- #
    def _closing(self, callback):
        def run(*_args):
            self.close()
            callback()
        return run

    def _announce(self, message):
        """Tell a screen reader a toast appeared (best effort: Narrator reads the alert's name)."""
        try:
            from PyQt6.QtGui import QAccessible, QAccessibleEvent
            QAccessible.updateAccessibility(QAccessibleEvent(self.card, QAccessible.Event.Alert))
        except Exception:
            pass
