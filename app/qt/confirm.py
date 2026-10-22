"""The one in-window confirmation (W3.4; the RUNBOOK's *Safety confirmations*, the intent keeper's IK-10).

`ask(window, title, body, yes, …, on_answer=…)` dims the window it is asked in (the scrim: it takes every click in that
window) and opens a card centred over it (a `motion.Overlay` opened as a `dialog`, layer 3), naming the action on its
primary button and the numbers in its words. **Esc, the mouse's Back button, ✕ (the window closing) and a click
outside the card are always No** — Esc and Back through the shell's `EscapeRouter` (the card is registered as an
overlay of its window); Enter presses the focused button, the default one at first: **Cancel when `default_no`** —
anything that removes, replaces or restores — else the primary (a write the preview already showed). It is never modal
(`exec` is never called): the answer comes back as `on_answer(yes)`, once, on the GUI thread — and never after its
window closed or was hidden (a window closing with a question open answers nothing: nothing happens). An optional
`check` (K7's *Also forget my known words*) sits under the words, off; its state is the card's `checked` when the
answer comes (No leaves it False). An optional `field` (LM11b G3: the group's *Rename…*) is a line of text under the
words, prefilled with it, in focus and selected as the card opens; Enter in it is Yes; its text is the card's `text`
when the answer comes (No leaves it None).

The looks are the stylesheet's (`QLabel#confirmtitle` / `#confirmline`, `kind="primary"` / `kind="danger"`) and the
theme's tokens (the `scrim` colour, the `dialog` radius and shadow): re-skinned with W3.3's surfaces.
"""
from PyQt6.QtCore import QEvent, QRectF, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                             QWidget)

from app import theme
from app.qt import motion, shadow, strings, style

MARGIN = 24                              # px kept between the card and its window's edges


class Scrim(QWidget):
    """The dimmed room: covers its window and takes every click in it; a click on it is No."""

    def __init__(self, window, on_click):
        super().__init__(window)
        self.setObjectName("confirmscrim")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._on_click = on_click
        self.setGeometry(window.rect())
        window.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def mousePressEvent(self, event):
        event.accept()                                    # nothing under the scrim hears it
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), style.qcolor(theme.FIXED["scrim"]))
        p.end()


class Confirm(motion.Overlay):
    """The card. Made by `ask`; `answer` is None until answered, then True / False."""
    how = "dialog"
    shadow_name = "dialog"
    focus = True

    def __init__(self, window, title, body, yes, yes_tip, no=None, no_tip=None, default_no=False, danger=False,
                 on_answer=None, check=None, check_tip=None, field=None):
        super().__init__(window)
        self.setObjectName("confirm")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self._window = window
        self._on_answer = on_answer
        self.answer = None
        self.checked = False
        self.text = None
        self._before = QApplication.focusWidget()
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        pad = round(20 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(10 * f))
        self.title = QLabel(title, self)
        self.title.setObjectName("confirmtitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        self.body = QLabel(body, self)
        self.body.setObjectName("confirmline")
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        self.body.setVisible(bool(body))
        box.addWidget(self.body)
        self.check = None
        if check:
            self.check = QCheckBox(check, self)
            self.check.setToolTip(check_tip or "")
            self.check.setAccessibleName(check)
            self.check.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            box.addWidget(self.check)
        self.field = None
        if field is not None:                             # --- LM11b G3: a line of text, read as `text` with Yes
            self.field = QLineEdit(field, self)
            self.field.setAccessibleName(title)
            self.field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            box.addWidget(self.field)
        row = QHBoxLayout()
        row.setSpacing(round(10 * f))
        row.addStretch(1)
        self.no = QPushButton(no or strings.CONFIRM_NO, self)
        self.no.setToolTip(no_tip or strings.CONFIRM_NO_TIP)
        self.no.clicked.connect(lambda _c=False: self._answer(False))
        self.yes = QPushButton(yes, self)
        self.yes.setProperty("kind", "danger" if danger else "primary")
        self.yes.setToolTip(yes_tip)
        self.yes.clicked.connect(lambda _c=False: self._answer(True))
        for b in (self.no, self.yes):
            b.setAccessibleName(b.text())
            b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            b.setAutoDefault(False)
            row.addWidget(b)
        box.addLayout(row)
        if self.field is not None:
            self.field.returnPressed.connect(self.yes.click)          # Enter in the field: Yes
        self.default = self.no if default_no else self.yes
        self.scrim = Scrim(window, self.close)
        self.shadow = shadow.Follower(self, self.shadow_name)
        window.installEventFilter(self)
        self.hide()

    # --- opening ------------------------------------------------------------------------------------------------- #
    def place(self):
        w = self._window
        self.ensurePolished()
        width = min(round(theme.size("dialog", style.current()[1])), max(1, w.width() - 2 * MARGIN))
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        height = min(height, max(1, w.height() - 2 * MARGIN))
        self.setGeometry((w.width() - width) // 2, max(0, (w.height() - height) // 2), width, height)

    def open(self):
        self.place()
        self.scrim.show()
        self.scrim.raise_()
        QApplication.instance().focusChanged.connect(self._focus_moved)
        return motion.open_overlay(self, self.how, self.shadow_name, on_done=self._focus_default, focus=True)

    def _focus_default(self):
        if self.answer is None and self.isVisible():
            if self.field is not None:                    # the name to type over: in focus, selected
                self.field.setFocus(Qt.FocusReason.OtherFocusReason)
                self.field.selectAll()
            else:
                self.default.setFocus(Qt.FocusReason.OtherFocusReason)

    # --- the keyboard stays on the card while it is open --------------------------------------------------------- #
    def _focus_moved(self, _old, new):
        if (self.answer is None and new is not None and new is not self and not self.isAncestorOf(new)
                and new.window() is self._window and self.isVisible()):
            self._focus_default()

    def focusNextPrevChild(self, next_):
        """Tab and Shift+Tab go round the two buttons (and the check, the field), never out to the window behind the
        scrim."""
        now = QApplication.focusWidget()
        ring = [w for w in (self.check, self.field, self.no, self.yes) if w is not None]
        if now in ring:
            target = ring[(ring.index(now) + (1 if next_ else -1)) % len(ring)]
        else:
            target = self.default
        target.setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            now = QApplication.focusWidget()
            (now if now in (self.no, self.yes) else self.default).click()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- the answer ---------------------------------------------------------------------------------------------- #
    def _answer(self, yes, drop=False):
        """The answer, once. `drop`: the window is closing — nothing is answered."""
        if self.answer is not None:
            return
        self.answer = bool(yes)
        self.checked = bool(yes) and self.check is not None and self.check.isChecked()
        self.text = self.field.text() if yes and self.field is not None else None
        callback, self._on_answer = self._on_answer, None
        try:
            QApplication.instance().focusChanged.disconnect(self._focus_moved)
        except TypeError:
            pass
        alive = self._window.isVisible() and not drop
        if self.isVisible() or motion.opening_of(self) is not None:
            self.close()
        self.scrim.hide()
        self.scrim.deleteLater()
        self.deleteLater()
        before = self._before
        if alive and before is not None and before.window() is self._window and before.isVisible():
            before.setFocus(Qt.FocusReason.OtherFocusReason)
        if alive and callback is not None:                # never once its window closed or was hidden
            callback(self.answer)

    def drop(self):
        """The question no longer stands (its window moved on): closed, answered No, and no callback."""
        self._answer(False, drop=True)

    def closeEvent(self, event):
        super().closeEvent(event)
        self._answer(False)                               # Esc, Back, a click outside: No

    def eventFilter(self, obj, event):
        if obj is self._window:
            if event.type() == QEvent.Type.Resize and self.isVisible():
                self.place()
            elif event.type() == QEvent.Type.Hide and not event.spontaneous() and self.answer is None:
                # ✕ (a close that went through) or a hide with a question open: No, no callback, and no dimmed room
                # left for the window's next showing. (Minimising is a spontaneous hide: the question stays.)
                self._answer(False, drop=True)
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(style.colours()["surface"]))
        radius = theme.RADII["dialog"]
        p.drawRoundedRect(QRectF(self.rect()), radius, radius)
        p.end()


def _register(window, overlay):
    """The card as an overlay of its window's router (Esc / Back close it): the window's own `register_overlay`, else
    the nearest parent's that has one (a secondary window's main window)."""
    w = window
    while w is not None:
        register = getattr(w, "register_overlay", None)
        if register is not None:
            register(overlay)
            return True
        w = w.parentWidget()
    return False


def ask(window, title, body, yes, yes_tip, *, no=None, no_tip=None, default_no=False, danger=False, on_answer=None,
        check=None, check_tip=None, field=None):
    """Ask in `window` (a top-level: the main window or a secondary one). `yes` names the action ("Remove 2 lists");
    `default_no` for anything that removes, replaces or restores; `danger` paints the action as one; `check` a box
    under the words (off; read as `card.checked` in `on_answer`); `field` a line of text prefilled with it (read as
    `card.text` in `on_answer`; Enter in it is Yes). -> the card (answered later through `on_answer(yes)`)."""
    window = window.window()
    card = Confirm(window, title, body, yes, yes_tip, no=no, no_tip=no_tip, default_no=default_no, danger=danger,
                   on_answer=on_answer, check=check, check_tip=check_tip, field=field)
    _register(window, card)
    card.open()
    return card
