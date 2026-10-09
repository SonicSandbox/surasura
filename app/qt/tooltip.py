"""The tooltip bubble (W2.1; the window's spec 05 §5.3–5.4, A4 *Motion*): the mock's one bubble, not Qt's `QToolTip`.

Every button and toggle carries a tooltip (D17); this is how it shows: after 380 ms, or 60 ms when another showed
within the last 500 ms; above its control and centred on it, 8 px away, flipped below at the top of the screen and
kept inside it; on keyboard focus too; hidden on a press, a scroll, a key, leaving the control or the window. Its text
is the control's `toolTip()` (rich text allowed), at the tooltip type size × the text size, at most 300 px × the text
size wide. Qt's own `QToolTip` is suppressed for any widget the bubble serves.

With the freeze switch on (tests, captures) it shows at once.
"""
import time

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QFont, QGuiApplication, QPainter, QPen, QTextDocument
from PyQt6.QtWidgets import QApplication, QWidget

from app import theme
from app.qt import freeze, style

GAP = 8
PAD = (10, 7)                                     # x, y (A4: padding 7px 10px)


class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("tooltipBubble")
        self._doc = QTextDocument()
        self._doc.setDocumentMargin(0)
        self.text = ""

    def set_text(self, text):
        _theme, size, _lang = style.current()
        f = theme.text_factor(size)
        px, weight = theme.font("tooltip", size)
        font = QFont(QApplication.font())
        font.setPointSizeF(px * style.PT_PER_PX)
        font.setWeight(QFont.Weight(weight))
        self._doc.setDefaultFont(font)
        self._doc.setDefaultStyleSheet(f"body {{ color: {style.colours()['ink']}; }}")
        if Qt.mightBeRichText(text):
            self._doc.setHtml(text)
        else:
            self._doc.setPlainText(text)
        self._doc.setTextWidth(-1)
        widest = theme.SIZES["tooltip-max"] * f - 2 * PAD[0]
        if self._doc.idealWidth() > widest:
            self._doc.setTextWidth(widest)
        else:
            self._doc.setTextWidth(self._doc.idealWidth() + 1)
        self.text = text
        size_ = self._doc.size()
        self.resize(int(size_.width() + 2 * PAD[0] + 2), int(size_.height() + 2 * PAD[1] + 2))

    def paintEvent(self, _event):
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(style.qcolor(c["line-hi"]), 1))
        p.setBrush(style.qcolor(theme.FIXED["tooltip"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), theme.RADII["tooltip"],
                          theme.RADII["tooltip"])
        p.translate(PAD[0] + 1, PAD[1] + 1)
        self._doc.drawContents(p)
        p.end()


def place(bubble_size, target, screen):
    """Where the bubble goes (global coordinates): above `target` (a global QRect) and centred on it, GAP away;
    below it when there's no room above; kept inside `screen` (the available QRect)."""
    w, h = bubble_size.width(), bubble_size.height()
    x = target.center().x() - w // 2
    y = target.top() - GAP - h
    if y < screen.top():
        y = target.bottom() + GAP
    x = max(screen.left(), min(x, screen.right() - w + 1))
    y = max(screen.top(), min(y, screen.bottom() - h + 1))
    return QPoint(x, y)


class Tooltips(QObject):
    """The app-wide filter that shows the bubble for every widget with a tooltip (install once on the QApplication)."""

    HIDE_ON = {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel,
               QEvent.Type.KeyPress, QEvent.Type.WindowDeactivate, QEvent.Type.DragEnter}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bubble = Bubble()
        self._target = None
        self._part = (None, None)                  # a painted part's (rect, text), or (None, None) for the widget's own
        self._last_hidden = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_now)

    def install(self, app=None):
        (app or QApplication.instance()).installEventFilter(self)
        return self

    def uninstall(self, app=None):
        (app or QApplication.instance()).removeEventFilter(self)
        self.hide()
        self.bubble.deleteLater()

    def delay(self):
        if freeze.frozen():
            return 0
        recent = (time.monotonic() - self._last_hidden) * 1000 <= theme.MOTION["tooltip-again-within"]
        return theme.MOTION["tooltip-again"] if recent else theme.MOTION["tooltip-delay"]

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.ToolTip:
            if isinstance(obj, QWidget) and obj.toolTip():
                self.request(obj)
                return True                        # Qt's own QToolTip never shows for these
            return False
        if et == QEvent.Type.FocusIn and isinstance(obj, QWidget) and obj.toolTip():
            if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                  Qt.FocusReason.ShortcutFocusReason):
                self.request(obj)
            return False
        if self._target is not None:
            if et in self.HIDE_ON:
                self.hide()
            elif obj is self._target and et in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.FocusOut,
                                                QEvent.Type.DeferredDelete):
                self.hide()
        return False

    def request(self, widget, rect=None, text=None):
        """Show `widget`'s tooltip after the delay — or, for a part a view paints (W2.2: a row's pill, a line), `text`
        for `rect` (in the widget's coordinates): the bubble sits on that part, and goes when the pointer leaves it."""
        # Qt asks again on every pause of the mouse over the control (its own wait is 0): the first ask's clock runs.
        if (self._target is widget and self._part == (rect, text)
                and (self.bubble.isVisible() or self._timer.isActive())):
            return
        if self._target is not None and (self._target is not widget or self._part != (rect, text)):
            self.hide()
        self._target = widget
        self._part = (rect, text)
        wait = self.delay()
        if wait <= 0:
            self._show_now()
        else:
            self._timer.start(wait)

    def _show_now(self):
        w = self._target
        if w is None or not w.isVisible():
            return
        rect, text = self._part
        self.bubble.set_text(text if text is not None else w.toolTip())
        if rect is None:
            target = QRect(w.mapToGlobal(QPoint(0, 0)), w.size())
        else:
            target = QRect(w.mapToGlobal(rect.topLeft()), rect.size())
        screen = (w.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        self.bubble.move(place(self.bubble.size(), target, screen))
        self.bubble.show()

    def hide(self):
        self._timer.stop()
        if self.bubble.isVisible():
            self.bubble.hide()
            self._last_hidden = time.monotonic()
        self._target = None
        self._part = (None, None)

    def hide_part_unless(self, widget, pos):
        """A painted part's bubble goes when the pointer (`pos`, in `widget`'s coordinates) leaves its part."""
        rect = self._part[0]
        if self._target is widget and rect is not None and not rect.contains(pos):
            self.hide()

    def showing(self):
        """The text shown now, or None."""
        return self.bubble.text if self.bubble.isVisible() else None
