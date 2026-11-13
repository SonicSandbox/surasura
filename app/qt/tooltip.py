"""The tooltip bubble (W2.1; the window's spec 05 §5.3–5.4, A4 *Motion*): the mock's one bubble, not Qt's `QToolTip`.

Every button and toggle carries a tooltip (D17); this is how it shows: after 380 ms, or 60 ms when another showed
within the last 500 ms; above its control and centred on it, 8 px away, flipped below at the top of the screen and
kept inside it; on keyboard focus too; hidden on a press, a scroll, a key, leaving the control or the window. Its text
is the control's `toolTip()` (rich text allowed), at the tooltip type size × the text size, at most 300 px × the text
size wide. Qt's own `QToolTip` is suppressed for any widget the bubble serves.

With the freeze switch on (tests, captures) it shows at once.

**The ? that says one line** (`AboutMark`; Sonic 2026-11-13: "I don't like subtitles, I like them hidden with a question
icon or something that reveals a succinct one. A subtitle would be best used as an example"): an explainer line under a
title stands behind a small ? beside it instead — its line in the bubble on hover, on keyboard focus (Tab) and on a click
or Enter / Space. A visible line under a title stays only where it is a concrete example, a state, or an action.
"""
import time

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QFont, QFontMetricsF, QGuiApplication, QPainter, QTextDocument
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from app import theme
from app.qt import freeze, style

GAP = 8
PAD = (10, 7)                                     # x, y (A4: padding 7px 10px)
BULLET = "\n• "                                   # a plain tip's action, on a line of its own (G2.3 T1)


def bulleted(text, indent):
    """A plain tip whose lines start "• " as rich text: each such line a bullet whose wrapped words stay indented under
    its first word (`indent`: the bullet and its space, measured in the tip's font), the other lines plain (G2.3 T1: an
    action on its own line reads at a glance)."""
    from html import escape
    out = []
    for line in text.split("\n"):
        if line.startswith("• "):
            out.append(f'<p style="margin-top:3px; margin-left:{indent}px; text-indent:-{indent}px">'
                       f'•&nbsp;{escape(line[2:])}</p>')
        else:
            out.append(f'<p style="margin:0">{escape(line)}</p>')
    return "".join(out)


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
        if BULLET in text or text.startswith(BULLET[1:]):   # first: a bulleted tip is plain words (names escaped)
            self._doc.setHtml(bulleted(text, round(QFontMetricsF(font).horizontalAdvance("• "))))
        elif Qt.mightBeRichText(text):
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
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["tooltip"])
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
    TYPES = frozenset(HIDE_ON | {QEvent.Type.ToolTip, QEvent.Type.FocusIn, QEvent.Type.Leave, QEvent.Type.Hide,
                                 QEvent.Type.FocusOut, QEvent.Type.DeferredDelete})   # every event `eventFilter` reads

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bubble = Bubble()
        self._target = None
        self._part = (None, None)                  # a painted part's (rect, text), or (None, None) for the widget's own
        self._last_hidden = 0.0
        self.shown = None                          # (widget, part rect or None) whose bubble last really showed — kept
        #   after it hides, until another is asked for (the phase strip counts a failure looked at only then: IKA3-5)
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
        if self.shown != (widget, rect):
            self.shown = None
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
        self.shown = (w, rect)

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

    def retext(self, widget, rect, text):
        """A painted part's words moved while its bubble shows (the phase strip's hover: a job's step): the bubble
        says them in place — no hide, no new wait. Nothing when the bubble isn't that part's."""
        if self._target is not widget or self._part[0] != rect or self._part[1] == text:
            return
        self._part = (rect, text)
        if self.bubble.isVisible():
            self._show_now()

    def showing(self):
        """The text shown now, or None."""
        return self.bubble.text if self.bubble.isVisible() else None


class FitTitle(QLabel):
    """A word-wrapped title with its `AboutMark` after it (laid out with a large stretch, the room after taking the
    rest): as wide as its words, so the ? sits right after them; it wraps only when the row is narrower (Settings' rows
    do the same, `RowView._fit_title`). Refitted when its words, font or style change (the text size changes live)."""

    REFIT = (QEvent.Type.FontChange, QEvent.Type.StyleChange)

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._fit()

    def setText(self, text):
        super().setText(text)
        self._fit()

    def _fit(self):
        import math
        m = self.contentsMargins()
        width = math.ceil(QFontMetricsF(self.font()).horizontalAdvance(self.text())) + 4 + m.left() + m.right()
        if self.maximumWidth() != width:
            self.setMaximumWidth(max(1, width))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in self.REFIT:
            self._fit()


class AboutMark(QLabel):
    """A small ? that reveals one succinct line (the module's note): its tooltip in the bubble on hover, on keyboard
    focus (Tab) and on a click or Enter / Space (the press hid the bubble: the release shows it again). `mark`: its glyph
    (the caller's strings table). Hidden while it has no line. Settings' rows build on it (`settings_page.HelpMark`)."""

    def __init__(self, mark, parent=None):
        super().__init__(mark, parent)
        self.setObjectName("helpmark")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setVisible(False)

    def set_about(self, name, text):
        """Its line `text` (empty: hidden) and `name`, what a screen reader calls it; only what changed is redone."""
        if self.toolTip() != text:
            self.setToolTip(text)
            self.setAccessibleName(name)
            self.setAccessibleDescription(text)
        if self.isHidden() == bool(text):
            self.setVisible(bool(text))

    def _ask(self):
        tips = getattr(self.window(), "tooltips", None)
        if tips is not None and self.toolTip():
            tips.request(self)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._ask()

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._ask()
