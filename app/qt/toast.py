"""Toasts (M2.1; the window's spec 05 §5.4, A4 *Motion*, A2's toast list): the mock's one toast.

One at a time, bottom centre, its bottom 48 px above the window's (the mock's `.toast`), at most 92 % of the window's
width, the message on one line (elided when too long). It rises 12 px in 260 ms as it opens (`motion.open_overlay`,
"rise"), stays 6.5 s (12 s for the Anki offer: `long=True`), and closes. *Undo* (when the action can be undone) and up to
two more buttons; a click runs its callback and closes the toast. A new toast replaces the one shown **without rising
again** (the mock's `.steady`), with its own time. **Hidden while dragging** (`set_dragging(True)`: a toast never covers
the buckets): no input, its time still running; after the drop it is back, unanimated, if its time hasn't run out.

The message is plain text (a title is never read as markup). The window never waits on a toast; what Undo does is the
caller's (W3.1's undo stack).

**Why?** (the help cards, HG-2; spec §5.2): a toast for something Surasura did by itself carries its cause
(`show(why=Cause)`): a text button *Why?* at its right end, outside `MAX_BUTTONS` (the message is shortened before it,
never it). A press opens that cause's help card (`ToastHost.why_asked(cause, done)`, the shell's); the toast's time
pauses while the card is open and runs on from where it was once `done()` is called, so its Undo is never lost.

**Its write waiting** (round 8 row 45): a toast that stands for a write still on its way reads *"… · saving…"*
(`set_saving`, the drag controller's one rule for every write's toast, wherever it shows — `drag.DragController`).
**Nothing moves** as those words come and go: a toast that may say them keeps their room from the moment it shows
(`keep_room`), and a long message is elided before them, never they.
"""
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from app import scrub, theme
from app.qt import motion, shadow, strings, style

MAX_BUTTONS = 3                                 # Undo + two (the mock's widest: [Mine it too] [Remove unstudied cards])
WIDTH_SHARE = 0.92                              # the mock's max-width: 92 %
PAD = (16, 10, 12, 10)                          # left, top, right, bottom (the mock's `padding: 10px 12px 10px 16px`)


class ToastCard(motion.Overlay):
    """The toast itself: the `toast` fill, a `line-hi` border, radius 12; the message and its buttons.

    **Its row is laid out in `body`, never in the card** (the card has no layout, placed by hand: `ToastHost.place`):
    a layout's pass asks its widget's parent to lay out again (Qt's `updateGeometry`), and the card's parent is the
    window's central widget — so a toast's new words laid out the central widget and the window at every move's toast.
    The body's parent is the card, which has no layout to ask: a toast's change stops there."""
    how = "rise"
    shadow_name = "toast"

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # a toast never takes the keyboard from the window
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.body = QWidget(self)
        self.body.setObjectName("toastbody")
        row = QHBoxLayout(self.body)
        f = theme.text_factor(style.current()[1])
        row.setContentsMargins(*(round(v * f) for v in PAD))
        row.setSpacing(round(12 * f))
        self.text = QLabel(self.body)
        self.text.setObjectName("toasttext")
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.text, 1)
        self.buttons = []                   # made as a toast first needs them, each wired once (the wiring check)
        self._callbacks = []
        self.why = None                     # *Why?* (help cards): made the first time a toast has a cause
        self.message = ""
        self.base = self.tail = ""          # the message's own words, and what follows them (*· saving…*), never elided
        self.room = ""                      # words whose room the card keeps while it shows (it never moves for them)

    def _button(self, i):
        while len(self.buttons) <= i:
            b = QPushButton(self.body)
            b.setProperty("size", "sm")
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)       # reachable by Tab; a click never takes the keyboard
            b.clicked.connect(lambda _c=False, n=len(self.buttons): self._press(n))
            lay = self.body.layout()
            if self.why is not None:                    # (*Why?* stays the last in the row)
                lay.insertWidget(lay.indexOf(self.why), b)
            else:
                lay.addWidget(b)
            self.buttons.append(b)
        return self.buttons[i]

    def _press(self, n):
        if n < len(self._callbacks) and self._callbacks[n] is not None:
            self._callbacks[n]()

    def set_message(self, message, tail=""):
        self.base, self.tail = message, tail
        self.message = message + tail
        self.setAccessibleName(self.message)

    def why_button(self, on_press):
        """*Why?* — made once, the last in the row (help cards)."""
        if self.why is None:
            self.why = QPushButton(strings.TOAST_WHY, self.body)
            self.why.setProperty("size", "sm")
            self.why.setProperty("kind", "link")
            self.why.setToolTip(strings.TOAST_WHY_TIP)
            self.why.setAccessibleName(strings.TOAST_WHY_NAME)
            self.why.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.why.clicked.connect(lambda _c=False: self._why_press())
            self.body.layout().addWidget(self.why)
        self._on_why = on_press
        return self.why

    def _why_press(self):
        call = getattr(self, "_on_why", None)
        if call is not None:
            call()

    def set_content(self, message, actions):
        """`actions`: [(label, tooltip, callback)], at most MAX_BUTTONS."""
        self.room = ""
        self.set_message(message)
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
        lay = self.body.layout()
        m = lay.contentsMargins()
        fm = QFontMetrics(self.text.font())
        width = fm.horizontalAdvance(self.base) + max(fm.horizontalAdvance(self.tail),
                                                      fm.horizontalAdvance(self.room)) + 2
        for b in self.buttons + ([self.why] if self.why is not None else []):
            if not b.isHidden():
                width += lay.spacing() + b.sizeHint().width()
        return width + m.left() + m.right()

    def fit_text(self):
        fm = QFontMetrics(self.text.font())
        tail = self.tail
        self.text.setText(fm.elidedText(scrub.shown(self.base), Qt.TextElideMode.ElideRight,
                                        max(0, self.text.width() - fm.horizontalAdvance(tail))) + tail)
        self.text.setToolTip(self.message if self.text.text() != self.message else "")

    shown_fit = fit_text            # (Report a problem's picture mode fits it again, the message scrubbed)

    def lay_out(self):
        """The row laid out at the card's size now, shown or not (a hidden body's own resize comes only as it shows,
        after the card's: the text would be fitted to the width it had before)."""
        self.body.setGeometry(self.rect())
        self.body.layout().setGeometry(self.body.rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.lay_out()
        self.fit_text()

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["toast"])
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
        self.text = ""                                # the message as shown, without *· saving…*
        self.saving = False
        self.on_show = None                           # called as each toast shows (the drag controller's: which writes
        parent.installEventFilter(self)               # it stands for)
        self.why_asked = None                         # (cause, done) -> the help card opened (the shell's); `done()`
        self.cause = None                             # ... when it closes. The shown toast's cause, else None
        self._paused = None                           # ms left while its card is open (the toast's time paused)

    # --- showing ---------------------------------------------------------------------------------------------- #
    def show(self, message, undo=None, buttons=(), long=False, why=None):
        """Show `message` (plain text). `undo`: a callback for *Undo*; `buttons`: [(label, tooltip, callback)] — each
        click runs its callback and closes the toast. `long`: 12 s (the Anki offer), else 6.5 s. `why`: what made it
        happen (`causes.Cause`, for what Surasura did by itself): a *Why?* at the end, outside the buttons' count."""
        opening = motion.opening_of(self.card)
        if opening is not None:
            opening.finish()                          # replaced mid-rise: the old one lands, the new one shows in place
        actions = []
        if undo is not None:
            actions.append((strings.TOAST_UNDO, strings.TOAST_UNDO_TIP, self._closing(undo)))
        actions.extend((label, tip, self._closing(cb)) for label, tip, cb in buttons)
        self.text, self.saving = message, False
        self.card.set_content(message, actions)
        self.cause, self._paused = why, None
        if why is not None and self.why_asked is not None:
            self.card.why_button(self._why).setVisible(True)
        elif self.card.why is not None:
            self.card.why.setVisible(False)
        self.alive = True
        if self.on_show is not None:
            self.on_show()
        self.life.start(theme.MOTION["toast-shown-anki" if long else "toast-shown"])
        self.place()
        self._announce(message)
        if self.dragging:
            return                                    # it shows after the drop
        if self.card.isVisible() or motion.opening_of(self.card) is not None:
            self.card.update()                        # a toast already up: replaced, never rising again
            return
        motion.open_overlay(self.card, self.card.how, self.card.shadow_name)

    def set_saving(self, on):
        """The shown toast's write is still on its way (`on`): *"… · saving…"* after its words; off, its words alone."""
        on = bool(on) and self.alive
        if on == self.saving:
            return
        self.saving = on
        if on:
            self.card.room = strings.TOAST_SAVING      # (kept from now on, if `keep_room` didn't already)
        self.card.set_message(self.text, strings.TOAST_SAVING if on else "")
        self.place()
        self.card.update()

    def keep_room(self):
        """The shown toast may say *· saving…*: its room kept from now on, so nothing moves when it does."""
        if self.alive and self.card.room != strings.TOAST_SAVING:
            self.card.room = strings.TOAST_SAVING
            self.place()

    def _why(self):
        """*Why?* pressed: the toast's time paused, its card opened; the time runs on when the card closes."""
        if not self.alive or self.cause is None or self.why_asked is None:
            return
        if self._paused is None and self.life.isActive():
            self._paused = self.life.remainingTime()
            self.life.stop()
        shown = self.text
        self.why_asked(self.cause, lambda: self._resume(shown))

    def _resume(self, shown):
        """The card closed: the same toast still up runs on from where its time was (a newer one has its own)."""
        left, self._paused = self._paused, None
        if left is not None and self.alive and self.text == shown and not self.life.isActive():
            self.life.start(max(1, left))

    @property
    def paused(self):
        return self._paused is not None

    def close(self):
        self.saving = False
        self.alive = False
        self._paused = None
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
        lay = card.body.layout()
        lay.activate()
        height = max(card.body.sizeHint().height(), round(theme.size("button-sm", style.current()[1])) + 2 * PAD[1])
        width = min(card.natural_width(), int(p.width() * WIDTH_SHARE))
        x = (p.width() - width) // 2
        y = p.height() - theme.MOTION["toast-bottom"] - height
        card.setGeometry(x, y, width, height)
        card.lay_out()                             # the text's width at this size (hidden, nothing else lays it out)
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
