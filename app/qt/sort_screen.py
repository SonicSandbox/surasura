"""Setup's load screen and the sort screen (Sonic 2026-10-30).

- **`LoadScreen`**: a calm, full cover over the setup wizard after its library step. The Surasura mark (its wings
  beating slowly on the one clock, the bird alone repainted; still under Reduced motion and the freeze switch), ONE
  task line with its live count (`set_task`) and
  a gentle line that fades out and in every `LINE_MS` (`LOAD_LINES`; Reduced motion: it changes without the fade, as
  the clock's "fade" kind keeps it short). Nothing in it acts but the quiet *Stop* (`stop` signal). The steps, their
  order and their counts are the wizard's (`SetupWizard._load_*`): this widget paints what it is told, and repaints
  only what changed (S19).
- **`SortScreen`**: every title in New arrivals (the reader's `arrival_groups`, followed as the window gets each view —
  `set_groups`), large: the title at the top is the one the keys act on — it looks picked (the window's `row-picked`
  wash, the accent edge) with a gap under it — then as many of the next few as the room holds, then *and N more*. Its
  five choices **Soon · Current · Goal · Finished · Ignore** are an arrow pad on the top title (Mado-P: Finished ↑,
  Ignore ←, Goal ↓, Current →, the S key of Soon beside them; each key its button, flashing as its key is pressed),
  *Put the rest in…*, *Undo* (Ctrl+Z), *Done*. Nothing is cut off at any window size: a long title wraps to
  `TITLE_LINES` (3 lines, 2 with the pad under it) then ends with "…", the just-done line is cut first, and the
  window's minimum makes room for the rest (`first_run._Cover`). A choice takes the title off at once (pending — the
  press rule) and the next comes up; a refused one comes back. **It decides nothing:** every placement is New
  arrivals' own (`arrivals.give_place`, `item_menu.give_skip`, `MovesController.undo_last`), through the window's writer. Opened by setup (after the load
  screen), by New arrivals' *Sort them all…* (`open_over(win)`) and by *Sort my library again* (after its load
  screen): one screen, three doors.
- **`LoadRun`** (Fresh library 3.0.1, P12): the load's steps in one sequence for both its callers — the setup wizard
  and *Sort my library again* over the window (`cover_window`): never a second copy.
"""
import math
import os
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPalette, QPixmap, QPolygonF, QTextLayout, QTextOption
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle,
                             QStyleOptionButton, QStylePainter, QVBoxLayout, QWidget)

from app import scrub, theme
from app.qt import motion, style
from app.qt import press as qpress
from app.qt import wizard_strings as S

LINE_MS = 6500                  # a gentle line stays this long, then fades out and the next fades in
FADE_MS = 700                   # each half of its fade
FLAP_UPPER, FLAP_LOWER = 9.0, 6.0   # degrees each wing turns about its root at a beat's ends (`MOTION` "mark-flap")
NEXT_SHOWN = 6                  # titles shown under the top one; the rest are "and N more"
COVER_W, COVER_H = 132, 186     # the top title's cover (× the text size); the next ones' are a third of it
KEYS = {Qt.Key.Key_Right: "now", Qt.Key.Key_S: "soon", Qt.Key.Key_Down: "goal", Qt.Key.Key_Up: "finished",
        Qt.Key.Key_Left: "ignore"}
# The arrow pad (Mado-P, Sonic's alpha 9 try: "a up down left right keypad like you normally see"): each choice's key at
# its place on a keyboard's arrow cross — (row, column) — and Soon's S a key of its own beside it, after a gap column.
PAD_AT = {"finished": (0, 1), "ignore": (1, 0), "goal": (1, 1), "now": (1, 2), "soon": (1, 4)}
PAD_DOWN_MS = 140               # a key pressed on the keyboard shows its pad key down this long (the press rule)
TITLE_LINES = (3, 2)            # the top title's most lines (the pad beside it, under it), then "…" (whole on hover)
WORDS_BESIDE = 300              # the top title's words keep at least this room (× the text size) with the pad beside
                                # them; less, and the pad goes under them (still a cross)
PLACE_OF = {"now": "top", "soon": "soon", "goal": "goal", "finished": "finished"}   # `moves.PLACES`' names


def _f():
    return theme.text_factor(style.current()[1])


def _px(n):
    return round(n * _f())


def _c(name):
    return style.qcolor(style.colours()[name])


def sheet():
    """The two screens' own rules (every colour a theme token), scoped to their object names."""
    c = {k: style.qss_colour(v) for k, v in theme.colours().items()}
    from app.qt import rows
    q = rows.c("row-picked")                          # the window's picked wash (a picked row's, Goal's sheet's)
    picked = f"rgba({q.red()}, {q.green()}, {q.blue()}, {q.alpha()})"
    f = _f()

    def font(role, weight=None, scale=1.0):
        size, drawn = theme.font(role, style.current()[1])
        return f"font-size: {round(size * scale * style.PT_PER_PX, 3)}pt; font-weight: {weight or drawn};"
    return f"""
QWidget#loadscreen, QWidget#sortscreen {{ background: {c['bg']}; }}
QLabel#loadtask {{ color: {c['ink']}; {font('hero-sub', 500, 1.35)} }}
QLabel#loadline {{ color: {c['ink-dim']}; {font('hero-sub', 400, 1.2)} }}
QLabel#loadside {{ color: {c['ink-dim']}; {font('hero-sub')} }}
QLabel#sorttitle {{ color: {c['ink']}; {font('first-run-heading', 600, 1.3)} }}
QLabel#sortline, QLabel#sortcount, QLabel#sortmore {{ color: {c['ink-dim']}; {font('hero-sub')} }}
QLabel#sortgroup {{ color: {c['accent']}; {font('eyebrow')} letter-spacing: 1px; }}
QLabel#sortname {{ color: {c['ink']}; {font('first-run-heading', 600, 1.05)} }}
QLabel#sortsub {{ color: {c['ink-dim']}; {font('row-sub')} }}
QLabel#sortnext {{ color: {c['ink-dim']}; {font('row-title', 500)} }}
QLabel#sortsaid {{ color: {c['ink-dim']}; {font('footer')} }}
QWidget#sorttop {{ background: {picked}; border-left: {max(2, round(3 * f))}px solid {c['accent']};
  border-radius: {round(8 * f)}px; }}
QPushButton#loadstop, QPushButton#sortquiet {{ background: transparent; border: 0; color: {c['ink-dim']};
  padding: 0 {round(10 * f)}px; {font('button', 400)} }}
QPushButton#loadstop:hover, QPushButton#sortquiet:hover {{ color: {c['ink']}; }}
QPushButton#loadstop:focus, QPushButton#sortquiet:focus {{ border: 2px solid {c['accent']}; border-radius: 6px; }}
QPushButton#loadstop:disabled {{ color: {c['ink-faint']}; }}
QPushButton#sortchoice {{ {font('button', 650)} }}
"""


def _label(name, text="", parent=None, wrap=False, lines=None):
    """A label; with `lines`, one that never asks for more room than that many lines (`Clamp`: cut with "…")."""
    lab = QLabel(text, parent) if lines is None else Clamp(text, lines, parent)
    lab.setObjectName(name)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    if lines is None:
        lab.setWordWrap(wrap)
    return lab


class Clamp(QLabel):
    """Words wrapped to at most `lines` lines, the last cut with "…" (then the whole words on hover), laid out and
    painted here: the height it asks for is the height its lines take (each line's own, a fallback font's taller
    glyphs included), and it never asks for its whole words' width — a long title is cut, never the window widened.
    `text()` stays the whole words (screen readers, the tests); what it draws is read through `scrub.shown` (Send
    report's picture: `shown_fit`)."""

    def __init__(self, text="", lines=1, parent=None):
        super().__init__(text, parent)
        self.lines = lines
        self._at = None                 # (width, text, font) its lines were laid out for
        self._shown, self._cut = (), False
        self.setWordWrap(lines > 1)     # (a wrapping label is asked its height for a width)
        self.setSizePolicy(QSizePolicy.Policy.Ignored if lines == 1 else QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)

    def _lay(self, width, tip=False):
        """((line, its height), …) at `width` px: at most `lines`, the last cut with "…" when there is more. `tip`: the
        width is its own (not a layout's question): the whole words on hover when they're cut."""
        text = scrub.shown(self.text())
        key = (round(width), text, self.font().key())
        if key == self._at:
            if tip:
                self.setToolTip(self.text() if self._cut else "")
            return self._shown
        fm = QFontMetricsF(self.font())
        out, cut = [], False
        if text and width > 0:
            lay = QTextLayout(text, self.font())
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if self.lines > 1
                            else QTextOption.WrapMode.NoWrap)
            lay.setTextOption(opt)
            spans = []
            lay.beginLayout()
            while True:
                line = lay.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width)
                spans.append((line.textStart(), line.textLength(), max(line.height(), fm.lineSpacing())))
            lay.endLayout()
            for i, (start, n, h) in enumerate(spans[:self.lines]):
                last = i == self.lines - 1
                if last and (len(spans) > self.lines or fm.horizontalAdvance(text[start:]) > width):
                    out.append((fm.elidedText(text[start:], Qt.TextElideMode.ElideRight, width), h))
                    cut = True
                else:
                    out.append((text[start:start + n].rstrip(), h))
        self._at, self._shown, self._cut = key, tuple(out), cut
        if tip:
            self.setToolTip(self.text() if cut else "")
        return self._shown

    def shown_fit(self):
        """(Send report's picture mode, `report.PictureMode`: drawn again from its words as `scrub.shown` reads them.)"""
        self.update()

    def heightForWidth(self, width):
        m = self.contentsMargins()
        return round(sum(h for _t, h in self._lay(width - m.left() - m.right()))) + m.top() + m.bottom()

    def sizeHint(self):
        fm, m = QFontMetricsF(self.font()), self.contentsMargins()
        w = fm.horizontalAdvance(self.text())
        if self.lines > 1:
            w = min(w, fm.averageCharWidth() * 60)
        w = round(w) + m.left() + m.right()
        one = round(fm.lineSpacing()) + m.top() + m.bottom()
        return QSize(w, max(one, self.heightForWidth(w)))

    def minimumSizeHint(self):
        fm, m = QFontMetricsF(self.font()), self.contentsMargins()
        return QSize(round(fm.averageCharWidth() * 4) + m.left() + m.right(),
                     round(fm.lineSpacing()) + m.top() + m.bottom())

    def setText(self, text):
        super().setText(text)
        self._lay(self.contentsRect().width(), tip=True)    # its tooltip follows its words at once
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._lay(self.contentsRect().width(), tip=True)

    def paintEvent(self, _event):
        r = self.contentsRect()
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        shown = self._lay(r.width())
        spare = max(0.0, r.height() - sum(h for _t, h in shown))
        down = self.alignment() & Qt.AlignmentFlag.AlignVertical_Mask
        y = r.top() + (spare / 2 if down == Qt.AlignmentFlag.AlignVCenter else
                       spare if down == Qt.AlignmentFlag.AlignBottom else 0.0)
        across = self.alignment() & Qt.AlignmentFlag.AlignHorizontal_Mask
        for text, h in shown:
            p.drawText(QRectF(r.left(), y, r.width(), h), int(across | Qt.AlignmentFlag.AlignVCenter), text)
            y += h
        p.end()


class PadKey(QPushButton):
    """One key of the arrow pad: its glyph large above its word, on the window's button (the sheet's frame, hover,
    pressed and focus looks). Every key the size of the widest word's, so the pad reads as a keypad."""

    def __init__(self, glyph, word, parent=None):
        super().__init__(word, parent)
        self.glyph = glyph
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _fonts(self):
        big = self.font()
        big.setPointSizeF(big.pointSizeF() * 1.35)
        return big, self.font()

    def sizeHint(self):
        big, small = self._fonts()
        w = max(QFontMetricsF(small).horizontalAdvance(word) for _n, word, _t, _k in S.SORT_CHOICES) + _px(28)
        h = QFontMetricsF(big).lineSpacing() + QFontMetricsF(small).lineSpacing() + _px(12)
        return QSize(round(w), round(h))

    def minimumSizeHint(self):
        return self.sizeHint()

    def event(self, event):
        done = super().event(event)
        if event.type() in (QEvent.Type.Polish, QEvent.Type.FontChange, QEvent.Type.StyleChange):
            # the window's sheet gives every button a `min-height` (one line's), and an explicit minimum is what a
            # layout squeezes a button down to — under its two lines here: its own size is its minimum
            self.setMinimumSize(self.sizeHint())
        return done

    def paintEvent(self, _event):
        p = QStylePainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        p.drawControl(QStyle.ControlElement.CE_PushButton, opt)
        big, small = self._fonts()
        hb, hs = QFontMetricsF(big).lineSpacing(), QFontMetricsF(small).lineSpacing()
        top = (self.height() - hb - hs) / 2
        centre = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        p.setPen(_c("ink") if self.isEnabled() else _c("ink-faint"))
        p.setFont(big)
        p.drawText(QRectF(0, top, self.width(), hb), centre, self.glyph)
        p.setFont(small)
        p.drawText(QRectF(0, top + hb, self.width(), hs), centre, self.text())
        p.end()


def _button(text, tip, slot, parent, name=None, glyph=None):
    b = QPushButton(text, parent) if glyph is None else PadKey(glyph, text, parent)
    b.setToolTip(tip)
    b.setAccessibleName(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoDefault(False)
    b.setDefault(False)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if name:
        b.setObjectName(name)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _set(label, text):
    """A label's text, only when it changed (S19)."""
    if label.text() != text:
        label.setText(text)


# --- the mark ------------------------------------------------------------------------------------------------------- #
# The mark's wings, from app_icon.png's own drawing (512 px; each feather is a shard of its own, apart from the body
# by a clear gap): each feather's outline, 3 px out into its gap, and the point its wing turns about. The upper wing's
# four feathers and the lower wing's two beat; the body and the head never move.
ICON = 512
UPPER_WING = (((44, 18), (49, 17), (177, 88), (243, 179), (243, 182), (238, 183), (91, 94), (73, 74)),
              ((167, 19), (173, 17), (301, 149), (301, 152), (296, 153), (175, 81)),
              ((56, 89), (60, 88), (205, 169), (265, 220), (266, 223), (259, 224), (101, 161), (56, 92)),
              ((106, 179), (114, 177), (213, 210), (267, 244), (263, 248), (152, 233)))
LOWER_WING = (((91, 421), (258, 283), (262, 283), (251, 340), (192, 457), (103, 496)),
              ((252, 348), (293, 326), (294, 329), (248, 419), (234, 435), (221, 444), (203, 450)))
UPPER_ROOT, LOWER_ROOT = (262, 215), (268, 300)
PAD = 0.12                      # room round the bird (a share of its side) for the wing tips at the top of a beat


def _wing_path(shards, scale):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for shard in shards:
        path.addPolygon(QPolygonF([QPointF(x * scale, y * scale) for x, y in shard]))
        path.closeSubpath()
    return path


class Mark(motion.Spinner):
    """The Surasura mark, its wings beating slowly on a seamless loop (Sonic 2026-10-30): on the one clock only while
    shown and its window not minimised (`motion.Spinner`'s rule); still, at rest in the mark's own pose, under Reduced
    motion and the freeze switch. Each frame turns the two wings' own pictures about their roots over the still body —
    three pictures cut once — and it paints every pixel of its own small square (the screen's ground first), so a beat
    repaints this widget alone: no layout, no other widget (S19)."""

    def __init__(self, size=96, parent=None):
        side = _px(size)
        super().__init__("flap", parent, size=side + 2 * round(side * PAD), period="mark-flap")
        self.bird = side
        self.angle = 0.0                # the beat now: -1 … 1 (0 = the mark's own pose)
        self._parts = None
        self.paints = 0                 # paint events (the tests' frame budget)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAccessibleName(S.LOAD_MARK_NAME)
        self.set_running(True)

    def _cut(self):
        """(body, upper wing, lower wing) at this size and pixel ratio, cut once from the icon."""
        if self._parts is None:
            dpr = self.devicePixelRatioF() or 1.0
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "images",
                                "app_icon.png")
            icon = QPixmap(path)
            if icon.isNull():
                self._parts = ()
                return self._parts
            side = round(self.bird * dpr)
            icon = icon.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            scale = icon.width() / ICON
            parts = []
            for shards in (None, UPPER_WING, LOWER_WING):
                pix = QPixmap(icon.size())
                pix.fill(Qt.GlobalColor.transparent)
                p = QPainter(pix)
                if shards is None:                  # the body: the icon with both wings cleared from it
                    p.drawPixmap(0, 0, icon)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                    for wing in (UPPER_WING, LOWER_WING):
                        p.fillPath(_wing_path(wing, scale), Qt.GlobalColor.black)
                else:
                    p.setClipPath(_wing_path(shards, scale))
                    p.drawPixmap(0, 0, icon)
                p.end()
                pix.setDevicePixelRatio(dpr)
                parts.append(pix)
            self._parts = tuple(parts)
        return self._parts

    def _on_frame(self, phase):
        angle = math.sin(phase * 2 * math.pi)
        if abs(angle - self.angle) >= 0.004:        # under a fiftieth of a degree's turn: nothing to paint
            self.angle = angle
            self.update()

    def _sync(self, *_args):
        super()._sync(*_args)
        if not self.on_clock and self.angle:
            self.angle = 0.0                        # stopped: at rest in the mark's own pose
            self.update()

    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        p.fillRect(self.rect(), _c("bg"))          # the screen's own ground: opaque, so nothing under it repaints
        parts = self._cut()
        if not parts:
            return
        body, upper, lower = parts
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        o, k = (self.width() - self.bird) / 2, self.bird / ICON
        p.drawPixmap(QPointF(o, o), body)
        for pix, (x, y), turn in ((upper, UPPER_ROOT, -FLAP_UPPER), (lower, LOWER_ROOT, FLAP_LOWER)):
            p.save()
            p.translate(o + x * k, o + y * k)
            p.rotate(turn * self.angle)
            p.translate(-(o + x * k), -(o + y * k))
            p.drawPixmap(QPointF(o, o), pix)
            p.restore()
        p.end()


class _FadeLine(QLabel):
    """The load screen's gentle line: its words in the label's own font and colour, drawn at `level` (0–1) — a fade
    repaints this line alone (the do-not list's T6: never a QGraphicsOpacityEffect)."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("loadline")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.level = 1.0

    def set_level(self, level):
        level = max(0.0, min(1.0, float(level)))
        if abs(level - self.level) >= 0.01 or level in (0.0, 1.0) and level != self.level:
            self.level = level
            self.update()

    def paintEvent(self, _event):
        if self.level <= 0.0:
            return
        p = QPainter(self)
        p.setOpacity(self.level)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.contentsRect(), int(self.alignment()), self.text())
        p.end()


# --- the load screen ------------------------------------------------------------------------------------------------ #
class LoadScreen(QWidget):
    """The load's calm cover (module docstring). `set_task(text)`; `set_side(text)` (alpha 8: what runs beside it —
    setup's YouTube videos — and how it ended; empty: none); `stopping()` after *Stop*; `stop` when pressed."""
    stop = pyqtSignal()

    def __init__(self, parent=None, lines=S.LOAD_LINES):
        super().__init__(parent)
        self.setObjectName("loadscreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(sheet())
        self.setAccessibleName(S.LOAD_NAME)
        self.lines, self.line_at = tuple(lines), 0
        box = QVBoxLayout(self)
        box.setContentsMargins(_px(40), _px(40), _px(40), _px(28))
        box.addStretch(3)
        self.mark = Mark(96, self)
        box.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addSpacing(_px(28))
        self.task = _label("loadtask", "", self)
        self.task.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(self.task)
        self.side = _label("loadside", "", self)
        self.side.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.side.setWordWrap(True)
        self.side.setVisible(False)
        box.addSpacing(_px(6))
        box.addWidget(self.side)
        box.addSpacing(_px(14))
        self.line = _FadeLine(self.lines[0] if self.lines else "", self)
        box.addWidget(self.line)
        self.offer = None                             # Mado-FU2: what the load asks while it reads (`add_offer`)
        self._offer_at = box.count()
        box.addStretch(4)
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_stop = _button(S.LOAD_STOP, S.LOAD_STOP_TIP, self._stop, self, name="loadstop")
        foot.addWidget(self.btn_stop)
        box.addLayout(foot)
        self._timer = QTimer(self)
        self._timer.setInterval(LINE_MS)
        self._timer.timeout.connect(self.next_line)
        self._anim = None

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def set_task(self, text):
        if self.task.text() != text:
            self.task.setText(text)
            self.task.setAccessibleName(text)

    def set_side(self, text):
        text = text or ""
        if self.side.text() != text:
            self.side.setText(text)
            self.side.setAccessibleName(text)
        if self.side.isHidden() == bool(text):
            self.side.setVisible(bool(text))

    def add_offer(self, widget):
        """Mado-FU2 (Fresh-U 19a): one control the load asks while it reads (setup's *Use every core*), centred
        under the gentle line, kept to the load's end; a second one takes the first one's place."""
        box, old = self.layout(), self.offer
        if old is not None and not sip.isdeleted(old):
            box.removeWidget(old)
            old.hide()
            old.deleteLater()
        else:
            box.insertSpacing(self._offer_at, _px(22))
        self.offer = widget
        widget.setParent(self)
        widget.setMaximumWidth(_px(480))
        box.insertWidget(self._offer_at + 1, widget, 0, Qt.AlignmentFlag.AlignHCenter)
        widget.show()

    def stopping(self):
        self.btn_stop.setEnabled(False)
        _set(self.btn_stop, S.LOAD_STOPPING)

    def _stop(self):
        if self.btn_stop.isEnabled():
            self.stopping()
            self.stop.emit()

    def next_line(self):
        """The next gentle line: the one shown fades out, the next fades in (Reduced motion: the clock keeps the
        fade short)."""
        if len(self.lines) < 2:
            return
        self.line_at = (self.line_at + 1) % len(self.lines)
        text = self.lines[self.line_at]
        if self._anim is not None:
            self._anim.stop()

        line = self.line

        def swap():
            if sip.isdeleted(line):
                return
            _set(line, text)
            self._anim = motion.clock().animate(FADE_MS, line.set_level, kind="fade", owner=line)
        self._anim = motion.clock().animate(FADE_MS, lambda v: line.set_level(1.0 - v), on_done=swap, kind="fade",
                                            owner=line)


# --- the sort screen ------------------------------------------------------------------------------------------------ #
class _Cover(QWidget):
    """A title's cover through the window's one door (`covers.pixmap_for`): its own picture once decoded, the
    generated one meanwhile; repainted when its decode lands."""

    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setFixedSize(_px(w), _px(h))
        self.arrival = None

    def set_arrival(self, a):
        shown = self._shows(self.arrival)
        self.arrival = a
        if self._shows(a) != shown:
            self.update()

    @staticmethod
    def _shows(a):
        return None if a is None else (getattr(a, "cover", None), getattr(a, "cover_title", None) or a.title)

    def paintEvent(self, _event):
        a = self.arrival
        if a is None:
            return
        from app.qt import covers as qcovers
        dpr = self.devicePixelRatioF() or 1.0
        shape = "tile" if self.width() > _px(60) else "row"
        pix = qcovers.pixmap_for(getattr(a, "cover", None), getattr(a, "cover_title", None) or a.title,
                                 self.width(), self.height(), dpr, shape, on_ready=self._ready)
        if pix is not None and not pix.isNull():
            QPainter(self).drawPixmap(0, 0, pix)

    def _ready(self):
        if not sip.isdeleted(self):
            self.update()


class _Room(QWidget):
    """The next titles' room under the top one: it asks only for its *and N more* line (its minimum height) — the
    titles it shows are as many as the room it is given holds (`SortScreen._fit_rows`), never a reason for the window
    to be taller."""

    def sizeHint(self):
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def minimumSizeHint(self):
        return QSize(super().minimumSizeHint().width(), self.minimumHeight())


def _rows_of(groups):
    """[(group kind, arrival)] in New arrivals' order (its groups, each newest first)."""
    return [(g.kind, a) for g in groups or () for a in g.rows]


def _sub_line(a):
    """The top title's line: its files and where they are (K7's folder, when the looks named it). The count is worded
    as New arrivals' and Goal's are (`view_rows.STRINGS["arr_units"]` by the title's media): *12 episodes*, *3 videos*,
    *48 parts* — never the play verb's word (*12 video*, Mado-SB)."""
    from app.services import view_rows
    n = len(getattr(a, "item_ids", ()) or ())
    one, many = view_rows.STRINGS["arr_units"][view_rows._arrival_unit(getattr(a, "media", None))]
    parts = [f"{n:,} {one if n == 1 else many}"]
    if getattr(a, "line", None):
        parts.append(str(a.line))
    if getattr(a, "folder", None):
        parts.append(str(a.folder))
    return " · ".join(parts)


class SortScreen(QWidget):
    """Every title in New arrivals, sorted one at a time from the top (module docstring). `win`: the main window (its
    `moves`, `looks`, `language`); `door`: "setup" (Esc does nothing — setup's rule, WZ-6 — and *Done* goes on),
    "arrivals" (Esc and ✕ close) or "resort" (*Sort my library again*'s: Esc closes, as *Done*; Finished asks nothing,
    as in setup — Q7). `closed(how)`: "done" / "closed" / "empty"."""
    closed = pyqtSignal(str)

    def __init__(self, win, parent=None, door="setup"):
        super().__init__(parent)
        self.win, self.door = win, door
        self.setObjectName("sortscreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # its ground painted by itself, opaque (`paintEvent`): Qt never paints what it covers — Current's list laid
        # out again under it by a choice's placement was painted, and the screen over it, at every choice (WC B4)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet(sheet())
        self.setAccessibleName(S.SORT_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.groups = ()
        self.all = []               # [(group kind, arrival)] in New arrivals' order (`set_groups`)
        self.hidden = {}            # key -> the action it went with (pending until the view lets it go)
        self.history = []           # [(keys, name, title)] newest last: Undo's order
        self.rows = []
        self._shown = None
        self.heard = False          # a view with titles came (until then an empty list says nothing: not "All sorted")
        self.question = None        # *Start sorting over*'s confirmation, while it is open
        self._over_waiting = None   # a *Start sorting over* waiting for a placement still being saved
        self._over_flight = None    # ... one given and not saved yet (the screen says *Putting N back…* meanwhile)
        self._over_undoing = None   # ... one whose Undo was pressed before it was saved (no other Undo goes ahead)
        self._build()
        if win is not None:
            win.__dict__["_sort_screen"] = self     # the window hands it each view's groups (`_show_arrivals`)
            view = win.__dict__.get("_arrivals_view")
            groups = getattr(view, "arrival_groups", ()) if view is not None else ()
            if groups:
                self.set_groups(groups)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), _c("bg"))          # the sheet's `background` (an opaque widget's isn't drawn by Qt)
        p.end()

    # --- building ------------------------------------------------------------------------------------------------ #
    def _build(self):
        box = QVBoxLayout(self)
        box.setContentsMargins(_px(56), _px(28), _px(56), _px(20))
        box.setSpacing(0)
        head = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(_px(4))
        words.addWidget(_label("sorttitle", S.SORT_TITLE, self))
        words.addWidget(_label("sortline", S.SORT_LINE, self))
        head.addLayout(words, 1)
        self.count = _label("sortcount", "", self)
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        box.addLayout(head)
        box.addSpacing(_px(18))
        # the top title: picked (the window's wash, the accent edge), its cover, words and the five choices
        self.top = QWidget(self)
        self.top.setObjectName("sorttop")
        self.top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(_px(22), _px(18), _px(22), _px(18))
        tl.setSpacing(_px(22))
        self.top_cover = _Cover(COVER_W, COVER_H, self.top)
        tl.addWidget(self.top_cover)
        tw = QVBoxLayout()
        tw.setSpacing(_px(6))
        self.top_group = _label("sortgroup", "", self.top)
        tw.addWidget(self.top_group)
        self.top_name = _label("sortname", "", self.top, lines=TITLE_LINES[0])
        tw.addWidget(self.top_name)
        self.top_sub = _label("sortsub", "", self.top, lines=2)
        tw.addWidget(self.top_sub)
        tw.addStretch(1)
        self.top_words = tw
        tl.addLayout(tw, 1)
        # the five choices: the arrow pad (the keys where a keyboard has them; each key is its button) — beside the
        # words, vertically centred, while they keep `WORDS_BESIDE`; under them when the window is narrower (`_place_pad`)
        self.pad = QWidget(self.top)
        grid = QGridLayout(self.pad)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_px(6))
        grid.setColumnMinimumWidth(3, _px(10))
        self.choice_buttons = {}
        for name, label, tip, key in S.SORT_CHOICES:
            b = _button(label, f"{tip}\n• {key}", lambda n=name: self.choose(n), self.pad, name="sortchoice",
                        glyph=key)
            grid.addWidget(b, *PAD_AT[name])
            self.choice_buttons[name] = b
        self.top_row = tl
        self._pad_beside = True
        self._key_up = QTimer(self)
        self._key_up.setSingleShot(True)
        self._key_up.timeout.connect(lambda: [b.setDown(False) for b in self.choice_buttons.values()])
        tl.addWidget(self.pad, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addWidget(self.top)
        box.addSpacing(_px(18))     # the gap that sets the top title apart
        self.empty = _label("sortname", S.SORT_EMPTY, self)
        self.empty.setVisible(False)
        box.addWidget(self.empty)
        # the next few: as many as the room under the top title holds (never squeezed: `_fit_rows`), then "and N more"
        self.next_area = _Room(self)
        self.next_area.installEventFilter(self)
        self.next_box = QVBoxLayout(self.next_area)
        self.next_box.setContentsMargins(0, 0, 0, 0)
        self.next_box.setSpacing(_px(8))
        self.next_rows = []
        for _i in range(NEXT_SHOWN):
            w = QWidget(self.next_area)
            line = QHBoxLayout(w)
            line.setContentsMargins(_px(25), 0, 0, 0)
            line.setSpacing(_px(14))
            cov = _Cover(COVER_W // 3, COVER_H // 3, w)
            line.addWidget(cov)
            name = _label("sortnext", "", w, lines=1)
            line.addWidget(name, 1)
            w.setVisible(False)
            self.next_box.addWidget(w)
            self.next_rows.append((w, cov, name))
        self._fits = NEXT_SHOWN
        self.more = _label("sortmore", "", self.next_area)
        self.more.setContentsMargins(_px(25), 0, 0, 0)
        self.next_box.addWidget(self.more)
        self.next_box.addStretch(1)
        self.more.ensurePolished()
        self.next_area.setMinimumHeight(self.more.sizeHint().height())     # "and N more" always has its line
        box.addWidget(self.next_area, 1)
        # the foot: what was just done (cut first when the room is short), Start over, Undo, Put the rest in…, Done.
        # (The keys' legend it had is the pad now; Ctrl+Z is on Undo's tooltip.)
        foot = QHBoxLayout()
        foot.setSpacing(_px(8))
        self.said = _label("sortsaid", "", self, lines=1)
        self.said.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        foot.addWidget(self.said, 1)
        self.btn_over = _button(S.SORT_OVER, S.SORT_OVER_TIP, self.ask_over, self, name="sortquiet")
        self.btn_over.setEnabled(False)
        foot.addWidget(self.btn_over)
        self.btn_undo = _button(S.SORT_UNDO, S.SORT_UNDO_TIP, self.undo, self, name="sortquiet")
        self.btn_undo.setEnabled(False)
        foot.addWidget(self.btn_undo)
        self.btn_rest = _button(S.SORT_REST, S.SORT_REST_TIP, self._rest_menu, self, name="sortquiet")
        foot.addWidget(self.btn_rest)
        self.btn_done = _button(S.SORT_DONE, S.SORT_DONE_TIPS.get(self.door, S.SORT_CLOSE_TIP),
                                lambda: self.finish("done"), self)
        self.btn_done.setProperty("kind", "primary")
        foot.addWidget(self.btn_done)
        self.btn_tour = None                    # help cards (§6.6): setup's last page — Done, then the tour
        if self.door == "setup":
            self.btn_tour = _button(S.SORT_TOUR, S.SORT_TOUR_TIP, self.done_then_tour, self)
            self.btn_tour.setProperty("kind", "link")
        for b in self.findChildren(QPushButton):
            b.installEventFilter(self)
        box.addSpacing(_px(12))
        box.addLayout(foot)
        if self.btn_tour is not None:
            under = QHBoxLayout()
            under.addStretch(1)
            under.addWidget(self.btn_tour)
            box.addLayout(under)

    # --- room (Mado-P: nothing cut off at any window size) ------------------------------------------------------- #
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_pad()

    def _place_pad(self):
        """The pad beside the top title's words while they keep `WORDS_BESIDE` px (× the text size), else under them
        — by the width alone, so the screen's minimum (the window's: `first_run._Cover`) never holds it beside."""
        m, tm = self.layout().contentsMargins(), self.top_row.contentsMargins()
        room = (self.width() - m.left() - m.right() - tm.left() - tm.right() - self.top_cover.width()
                - 2 * self.top_row.spacing() - self.pad.sizeHint().width())
        beside = room >= _px(WORDS_BESIDE)
        if beside == self._pad_beside:
            return
        self._pad_beside = beside
        self.top_name.lines = TITLE_LINES[0 if beside else 1]
        self.top_name._at = None
        self.top_name._lay(self.top_name.contentsRect().width(), tip=True)
        self.top_name.updateGeometry()
        if beside:
            self.top_words.removeWidget(self.pad)
            self.top_row.addWidget(self.pad, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            self.top_row.removeWidget(self.pad)
            self.top_words.insertWidget(self.top_words.count() - 1, self.pad, 0, Qt.AlignmentFlag.AlignLeft)
        self.updateGeometry()                               # its minimum changed: the window's cover asks again

    def eventFilter(self, obj, event):
        if obj is self.next_area and event.type() == QEvent.Type.Resize:
            self._fit_rows()
        elif event.type() == QEvent.Type.KeyPress and isinstance(obj, QPushButton) and self._mine(event) is not None:
            self.keyPressEvent(event)                       # a button with the focus (Tab) never keeps the screen's
            return True                                     # keys: an arrow sorts, it doesn't move the focus
        return False

    def _fit_rows(self):
        """How many of the next titles the room under the top one holds (each row whole; "and N more" counts the rest):
        a short window shows fewer, never squeezed ones."""
        h = self.next_area.height()
        row = self.next_rows[0][0].sizeHint().height() + self.next_box.spacing()
        fits = max(0, min(NEXT_SHOWN, (h - self.more.sizeHint().height()) // max(1, row)))
        if fits != self._fits:
            self._fits = fits
            self._paint()

    def _flash(self, name):
        """A key pressed on the keyboard: its pad key shows pressed at once (the press rule), a moment; with motion on,
        it also flashes (the window's wash, short) — Reduced motion: the pressed look alone."""
        b = self.choice_buttons.get(name)
        if b is None:
            return
        for other in self.choice_buttons.values():
            other.setDown(other is b)
        self._key_up.start(PAD_DOWN_MS)                     # (a second press restarts it: each key down its while)
        if not motion.clock().mode.reduced:
            motion.wash(b, _px(9), ms=theme.MOTION["pad-flash"])

    # --- what it shows ------------------------------------------------------------------------------------------- #
    def set_groups(self, groups):
        """The reader's `arrival_groups`, as the window got them: a pending title the view no longer holds landed (its
        pending mark goes); one still there stays hidden until it does."""
        self.groups = tuple(groups or ())
        self.heard = self.heard or bool(self.groups)
        self.all = _rows_of(self.groups)
        present = {a.key for _k, a in self.all}
        for key in [k for k in self.hidden if k not in present]:
            del self.hidden[key]
        self._paint()

    def visible_rows(self, most=None):
        """The titles still to sort, in order — the first `most` only when asked (a press reads the top few: never the
        whole list, so a press costs the same at 15,000 titles as at 10)."""
        out = []
        for row in self.all:
            if row[1].key not in self.hidden:
                out.append(row)
                if most is not None and len(out) >= most:
                    break
        return out

    def left(self):
        """How many are still to sort (every pending key is one of the view's: `set_groups` lets the others go)."""
        return len(self.all) - len(self.hidden)

    def top_arrival(self):
        rows = self.visible_rows(1)
        return rows[0][1] if rows else None

    def _paint(self):
        rows, n = self.visible_rows(NEXT_SHOWN + 1), self.left()
        key = tuple((kind, a.key, a.title, getattr(a, "folder", None), len(a.item_ids), getattr(a, "cover", None),
                     getattr(a, "line", None), getattr(a, "media_word", None))
                    for kind, a in rows) + (n, bool(self.history), self.heard, self._can_start_over(),
                                            self._over_flight is not None, self._fits)
        if key == self._shown:
            return                                  # nothing it shows changed (S19)
        self._shown = key
        self.rows = rows
        _set(self.count, S.SORT_COUNT.format(n=n) if n else "")
        self.top.setVisible(bool(rows))
        self.empty.setVisible(not rows and self.heard and self._over_flight is None)   # (not while titles come back)
        self.btn_rest.setEnabled(n > 1)
        self.btn_undo.setEnabled(bool(self.history))
        self.btn_over.setEnabled(self._can_start_over())
        if rows:
            kind, a = rows[0]
            _set(self.top_group, S.SORT_GROUPS.get(kind, ""))
            _set(self.top_name, a.title)
            _set(self.top_sub, _sub_line(a))
            self.top_cover.set_arrival(a)
        fits = min(self._fits, max(0, len(rows) - 1))
        for i, (w, cov, name) in enumerate(self.next_rows):
            r = rows[i + 1] if i < fits else None
            w.setVisible(r is not None)
            if r is not None:
                _set(name, r[1].title)
                cov.set_arrival(r[1])
        more = n - 1 - fits
        _set(self.more, S.SORT_MORE.format(n=more) if more > 0 else "")
        self.more.setVisible(more > 0)

    # --- acting -------------------------------------------------------------------------------------------------- #
    # Each choice is one entry of `history` (Undo's order): {"keys", "name", "text", "ticket", "undone"} — `ticket` the
    # window's own (`drag.Ticket`) once its command is given, so Undo takes back that change and never another.
    def _moves(self):
        """The window's drag controller, or None — when its store can't be written, said here (the bar is under the
        screen) as the window says it."""
        moves = getattr(self.win, "moves", None)
        if moves is None:
            return None
        why = moves.refused()
        if why is not None:
            _set(self.said, why)
            return None
        return moves

    def _take(self, keys, name, text):
        """The titles of `keys` off the screen at once (pending until the view lets them go) -> their history entry."""
        entry = {"keys": tuple(keys), "name": name, "text": text, "ticket": None, "undone": False}
        for k in entry["keys"]:
            self.hidden[k] = name
        self.history.append(entry)
        self._shown = None
        self._paint()
        _set(self.said, text)
        return entry

    def choose(self, name, arrival=None):
        """A choice on the top title (or `arrival`): taken off at once (pending), handed to New arrivals' own call;
        refused — it comes back and the screen says so (the writer's note)."""
        if name not in PLACE_OF and name != "ignore":
            return None
        a = arrival or self.top_arrival()
        if a is None:
            return None
        moves = self._moves()
        if moves is None:
            return None
        after = self._current_end() if name == "now" else None
        entry = self._take((a.key,), name, S.SORT_PLACED[name].format(title=a.title))
        if name == "ignore":
            self._ignore(a, moves, entry)
            return True
        from app.qt import arrivals
        seq = arrivals.give_place(moves, entry["text"], list(a.item_ids), PLACE_OF[name], toast=False,
                                  ticket=self._ticket(entry, a.item_ids), after=after)
        if seq is None:
            self._refused(entry)
        return seq

    def _current_end(self):
        """Choice 1 (Sonic, 2026-11-09: "sure"): Current keeps the order titles are sent in — the first sent stays on
        top. -> the last item this screen sent to Current and still holds there (its newest choice or *Put the rest
        in…* not undone, refused or put back), for the next one to go after; None: the top, as before."""
        for entry in reversed(self.history):
            if entry["name"] == "now" and not entry.get("gone") and entry["ticket"] is not None and entry["ticket"].ids:
                return entry["ticket"].ids[-1]
        return None

    def _ticket(self, entry, ids):
        """The entry's own ticket — kept for its Undo, and told when its command ends unsaved (it landed as nothing,
        or was let go): the titles come back as a refusal does, never hidden for good."""
        from app.qt import drag
        ticket = entry["ticket"] = drag.Ticket(entry["text"], entry["keys"], ids)

        def told(event):
            if event in ("saved", "refused", "ended"):
                entry["settled"] = True
            if event == "ended" and ticket.change is None and not entry["undone"] and not sip.isdeleted(self):
                self._refused(entry)
            over = self._over_waiting                       # (a screen closed meanwhile still gives it: Done is no No)
            if over is not None and _among(entry, over["entries"]):
                self._give_over(over)                       # Start over waited for this one's save
        ticket.told = told
        return ticket

    def _ignore(self, a, moves, entry):
        """← Ignore: the title's own folder never read again (`give_skip`, Q7's) — only a folder holding no other title
        (`looks.skippable(..., own=True)`); else the title taken out of the library (`writer.remove`: its copy to the
        trash, the original where it is, kept out of every later look). One Undo either way; an Undo pressed while the
        folder is still being looked for gives nothing at all."""
        from app.qt import bridge, item_menu
        ids = list(a.item_ids)

        def act(folders):
            if entry["undone"]:
                return
            ticket = self._ticket(entry, ids)
            if folders:
                seq = item_menu.give_skip(moves, folders[0], ids, toast=False, ticket=ticket)
            else:
                seq = moves._give(ticket, lambda t: moves.writer.remove(ids, label=t), toast=False)
            if seq is None and not sip.isdeleted(self):
                self._refused(entry)
        looks = getattr(self.win, "looks", None)
        if looks is None or not hasattr(looks, "skippable"):
            act([])                                         # (no folder is being read: nothing to skip)
            return
        relay = bridge.Relay(self.win if isinstance(self.win, QObject) else self)     # (outlives a screen closed meanwhile)

        def found(folders):
            relay.deleteLater()
            act(list(folders or ()))
        relay.said.connect(found)
        if not looks.skippable(ids, relay.call, own=True):
            relay.deleteLater()                             # the looks can't answer now (closing): nothing guessed
            self._refused(entry)

    def _refused(self, entry):
        """A choice the writer refused: its titles back where they were, and the screen says it wasn't saved."""
        from app.qt import strings
        entry["gone"] = True                                # (a Start over's Undo never brings it back)
        if not _among(entry, self.history):
            return                                          # (taken into a Start over, or undone: nothing shown)
        for k in entry["keys"]:
            self.hidden.pop(k, None)
        self.history = [e for e in self.history if e is not entry]
        _set(self.said, strings.MOVE_NOT_SAVED)
        self._shown = None
        self._paint()

    def rest(self, name):
        """*Put the rest in…* `name`: every title still shown, in one command (one Undo)."""
        if name not in PLACE_OF:
            return None
        rows = self.visible_rows()
        if not rows:
            return None
        moves = self._moves()
        if moves is None:
            return None
        ids = [i for _k, a in rows for i in a.item_ids]
        label = next(lab for n, lab, *_r in S.SORT_CHOICES if n == name)
        after = self._current_end() if name == "now" else None
        entry = self._take([a.key for _k, a in rows], name, S.SORT_REST_PLACED.format(n=len(rows), place=label))
        from app.qt import arrivals
        seq = arrivals.give_place(moves, entry["text"], ids, PLACE_OF[name], toast=False,
                                  ticket=self._ticket(entry, ids), after=after)
        if seq is None:
            self._refused(entry)
        return seq

    def _rest_menu(self):
        """*Put the rest in…*: its entries never change, so the menu is made once and kept hidden between opens (R5)."""
        m = getattr(self, "_rest_kept", None)
        if m is None:
            from app.qt.drag import _KeptMenu            # (closed, it only hides: its native window kept too)
            m = self._rest_kept = _KeptMenu(self.btn_rest)
            m.setObjectName("rowmenu")
            for name, label, tip, _key in S.SORT_CHOICES:
                if name in PLACE_OF:
                    act = m.addAction(label)
                    act.setToolTip(tip)
                    act.triggered.connect(lambda _c=False, n=name: self.rest(n))
        self.last_menu = m
        m.popup(self.btn_rest.mapToGlobal(self.btn_rest.rect().topLeft()))
        return m

    def undo(self):
        """Undo (Ctrl+Z): the last choice comes back to the top at once, and its own change is undone as the writer
        reaches it (`MovesController.undo`, its toast's Undo) — never another change of the window's."""
        moves = getattr(self.win, "moves", None)
        if not self.history or moves is None:
            return
        if self._over_undoing is not None:                  # a Start over's Undo waits for it to be saved: an Undo
            from app.qt import strings                      # now would reach the writer before it (adversary #2)
            _set(self.said, strings.UNDOING)
            return
        entry = self.history.pop()
        entry["undone"] = True
        for k in entry["keys"]:
            self.hidden.pop(k, None)
        if entry["name"] == "over":                         # the sorting it put back is placed again: hidden at once
            if self._over_waiting is entry:
                self._over_waiting = None
            if self._over_flight is entry:
                self._over_flight = None
                if entry["ticket"] is not None:
                    self._over_undoing = entry
            self.history = [e for e in entry["before"] if not e.get("gone")]
            for e in entry["entries"]:
                if not e.get("gone"):
                    for k in e["keys"]:
                        self.hidden[k] = e["name"]
        if entry["ticket"] is not None:
            moves.undo(entry["ticket"])
        _set(self.said, "")
        self._shown = None
        self._paint()

    # --- Mado-O (alpha 8): *Start sorting over* ----------------------------------------------------------------- #
    def _placed(self):
        """The choices this screen made that *Start sorting over* puts back: Current, Soon, Goal, Finished (a *Put the
        rest in…* among them) and — SO-1, Sonic 2026-10-31 ("I did accidentally ignore something") — Ignore: the
        title back to sort, its folder read again. Ignores made anywhere else stay."""
        return [e for e in self.history if e["name"] in PLACE_OF or e["name"] == "ignore"]

    def _can_start_over(self):
        """Something to put back, and no Start over (or its Undo) still on its way to the writer."""
        return (self._over_flight is None and self._over_undoing is None and       # (a waiting one is in flight)
                any(e["name"] in PLACE_OF or e["name"] == "ignore" for e in self.history))

    def ask_over(self):
        """*Start sorting over*: asked first (the one confirmation; No by default — it puts back), then `start_over`."""
        n = sum(len(e["keys"]) for e in self._placed())
        if not n or self.question is not None or not self._can_start_over():
            return None
        from app.qt import confirm

        def answered(yes):
            self.question = None
            if yes and not sip.isdeleted(self):
                self.start_over()
        if any(e["name"] == "ignore" for e in self._placed()):     # (the ignored ones named only when there are)
            body = S.SORT_OVER_BODY_ONE if n == 1 else S.SORT_OVER_BODY.format(n=n)
        else:
            body = S.SORT_OVER_BODY_PLAIN_ONE if n == 1 else S.SORT_OVER_BODY_PLAIN.format(n=n)
        self.question = confirm.ask(self, S.SORT_OVER_ASK, body, S.SORT_OVER_YES, S.SORT_OVER_YES_TIP, default_no=True,
                                    on_answer=answered)
        return self.question

    def start_over(self):
        """Every title this screen placed back in New arrivals in ONE command (`Writer.start_over`: each placement's
        own change, undone together — one moved since stays where it was put) and the screen from the top; one Undo
        (Ctrl+Z) puts the sorting back. The press shows at once; a placement still being saved is waited for (its
        change is what is put back). -> the history entry, or None."""
        entries = self._placed()
        if not entries or not self._can_start_over():
            return None
        moves = self._moves()
        if moves is None:
            return None
        n = sum(len(e["keys"]) for e in entries)
        text = S.SORT_OVER_SAID_ONE if n == 1 else S.SORT_OVER_SAID.format(n=n)
        entry = {"keys": (), "name": "over", "text": text, "ticket": None, "undone": False, "entries": entries,
                 "before": list(self.history)}
        taken = {id(e) for e in entries}
        self.history = [e for e in self.history if id(e) not in taken] + [entry]
        for e in entries:
            if e["ticket"] is None:                         # an Ignore still looking for its folder: never given now
                e["undone"] = e["gone"] = True
        for e in entries:
            for k in e["keys"]:
                self.hidden.pop(k, None)
        self._over_flight = entry                           # pending at once: *Putting N back…* until it is saved
        self._shown = None
        self._paint()
        _set(self.said, S.SORT_OVER_SAYING_ONE if n == 1 else S.SORT_OVER_SAYING.format(n=n))
        self._give_over(entry)
        return entry

    def _give_over(self, entry):
        """The reset's one command, once every placement it puts back has settled (saved, or ended unsaved)."""
        if entry["ticket"] is not None or entry["undone"]:
            return
        if any(not e.get("settled") and e["ticket"] is not None and e["ticket"].change is None
               for e in entry["entries"]):
            self._over_waiting = entry
            return
        self._over_waiting = None
        changes = [e["ticket"].change for e in entry["entries"] if e["ticket"] is not None and
                   e["ticket"].change is not None and not e["ticket"].undo_asked]
        moves = getattr(self.win, "moves", None)
        if not changes or moves is None:
            self._over_landed(entry, quiet=True)            # (none saved: they're back in New arrivals as they were)
            return
        from app.qt import drag
        ids = [i for e in entry["entries"] if e["ticket"] is not None for i in e["ticket"].ids]
        ticket = entry["ticket"] = drag.Ticket(entry["text"], (), ids)

        def told(event):
            if event in ("saved", "refused", "ended") and self._over_undoing is entry:
                self._over_undoing = None                   # its Undo is the writer's now: other Undos go after it
            if event == "saved":
                self._over_landed(entry)
            elif event == "ended" and ticket.change is None and not entry["undone"]:
                self._over_refused(entry, quiet=True)       # every title moved since: nothing to put back
        ticket.told = told
        if moves._give(ticket, lambda t: moves.writer.start_over(changes, label=t), toast=False) is None:
            self._over_refused(entry)

    def _over_landed(self, entry, quiet=False):
        """The reset saved (or there was nothing to give): the screen says so, no longer pending."""
        if self._over_flight is not entry:
            return
        self._over_flight = None
        if sip.isdeleted(self):
            return
        if not entry["undone"]:
            _set(self.said, "" if quiet else entry["text"])
        self._shown = None
        self._paint()

    def _over_refused(self, entry, quiet=False):
        """A Start over the writer refused (or that put back nothing): the sorting stands, its choices back on Undo."""
        if self._over_flight is entry:
            self._over_flight = None
        if sip.isdeleted(self) or not _among(entry, self.history):
            return
        at = next(n for n, e in enumerate(self.history) if e is entry)
        self.history = [e for e in entry["before"] if not e.get("gone")] + self.history[at + 1:]
        if quiet:
            _set(self.said, "")
        else:
            from app.qt import strings
            for e in entry["entries"]:
                if not e.get("gone"):
                    for k in e["keys"]:
                        self.hidden[k] = e["name"]
            _set(self.said, strings.MOVE_NOT_SAVED)
        self._shown = None
        self._paint()

    def _mine(self, event):
        """What a key press is to this screen: "undo", a choice's name, "close", or None (not its key)."""
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            return "undo"
        if key in KEYS and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return KEYS[key]
        if key == Qt.Key.Key_Escape and self.door != "setup":
            return "close"
        return None

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride and self._mine(event) is not None:
            event.accept()                                  # its keys are its own: the window's Ctrl+Z (`undo_last`,
            return True                                     # its newest change) never takes the sort's Undo
        return super().event(event)

    def keyPressEvent(self, event):
        what = self._mine(event)
        if what is None:
            super().keyPressEvent(event)
            return
        event.accept()
        if event.isAutoRepeat():                            # one action per press: a held key's repeats are none
            return
        if what == "undo":
            self.undo()
        elif what == "close":
            self.finish("closed")
        else:
            self._flash(what)
            self.choose(what)

    def done_then_tour(self):
        """*See what Surasura does by itself* (help cards §6.6): Done, and the tour opens once the window is up — when
        setup has ended (`ShellWindow.setup_held(False)`), never over the wizard's later pages."""
        win = self.win
        if win is not None and hasattr(win, "__dict__"):
            win.__dict__["_tour_after_setup"] = True
        self.finish("done")

    def finish(self, how="done"):
        win = self.win
        if win is not None and win.__dict__.get("_sort_screen") is self:
            del win.__dict__["_sort_screen"]
        self.closed.emit(how)


def _among(entry, entries):
    """Whether `entry` (a history entry: a dict) is one of `entries` — by identity, never by its values."""
    return any(e is entry for e in entries)


def open_over(win):
    """New arrivals' *Sort them all…*: the sort screen over the window's central area (as the setup wizard covers it),
    following its size; closed by *Done* or Esc. -> the screen."""
    from app.qt import first_run
    old = win.__dict__.get("_sort_screen")
    if old is not None and not sip.isdeleted(old):
        old.raise_()
        old.setFocus()
        return old
    area = win.centralWidget()
    screen = SortScreen(win, parent=area, door="arrivals")
    screen.setGeometry(area.rect())
    first_run._Cover(screen, area)

    def closed(_how):
        if not sip.isdeleted(screen):
            screen.hide()
            qpress.let_go(screen)                         # (its `_Cover` filters the area until it goes: Qt-C2)
    screen.closed.connect(closed)
    screen.show()
    screen.raise_()
    screen.setFocus()
    return screen


# --- one load, two callers (Fresh library 3.0.1, P12: setup and *Sort my library again*) --------------------------- #
class LoadRun(QObject):
    """The load sequence (Mado-O's, from the setup wizard; one copy): the scan's count (`said`, the caller's look
    reports it), then, once the caller says the scan ended (`scanned(ids)`), the words (the window's own indexer,
    `Chores.index(force=True)`, its count read from its log), the covers from disk (`shell.scan_covers`) and — setup
    only — the wait for page 2's Anki sync (`sync_running()`, its end `synced()`) and for page 3's YouTube videos
    (`fetching()`); then the sort screen (`SortScreen(shell, door=)`). *Stop* keeps what each step did and goes to the
    sorting; a step with nothing to do is passed by. `cover(widget or None)` puts the load screen and the sort screen
    over the caller (None: neither); `stop_scan()` stops the caller's look between files; `sort()` (the wizard's
    `_load_sort`) opens the sorting, `open_sort` by default; `after(how)` once the sort screen closed (`state["ids"]`:
    the scan's items); `empty()` when the scan took nothing in (the cover gone). `language()`: whose indexer runs
    count. `state`: {"step", "ids", "stopped", "indexed", "since"}. Outside setup it hears the window's indexer itself
    (`shell.bridge.indexed`)."""

    def __init__(self, shell, cover, door="setup", stop_scan=None, language=None, sort=None, after=None, empty=None,
                 sync_running=None, fetching=None, long_read=None, parent=None):
        super().__init__(parent)
        self.shell, self._cover, self.door = shell, cover, door
        self.setup = door == "setup"
        self._stop_scan = stop_scan
        self._language = language or (lambda: getattr(shell, "language", None))
        self._sort, self._after, self._empty = sort, after, empty
        self._sync_running = sync_running or (lambda: False)
        self._fetching = fetching or (lambda: False)
        self._long_read = long_read if self.setup else None    # Mado-FU2: `long_read(screen)`, once (`_reading`)
        self.state = None
        self.loading = None                           # the load screen (gone with the cover once the sorting opens)
        self.ended = False
        self._heard = None
        if not self.setup:                            # (setup's wizard hears it and hands it on: `indexed`)
            heard = getattr(shell, "bridge", None)
            if heard is not None and hasattr(heard, "indexed"):
                heard.indexed.connect(self.indexed)
                self._heard = heard

    def _alive(self):
        return not self.ended and not sip.isdeleted(self)

    def _guard(self, fn):
        """`fn`, dropped once the run ended (a worker's or a timer's late call)."""
        def call(*args):
            return fn(*args) if self._alive() else None
        return call

    def begin(self):
        """The load screen over the caller, its first count. -> the screen."""
        self.loading = LoadScreen()
        self.loading.stop.connect(self._guard(self.stop))
        self.state = {"step": "scan", "ids": [], "stopped": False, "indexed": 0, "since": None}
        self._cover(self.loading)
        self.said((0, 0))
        return self.loading

    def task(self, text):
        screen = self.loading
        if screen is not None and not sip.isdeleted(screen) and self.state is not None and \
                self.state["step"] != "sort":
            screen.set_task(text)

    def said(self, said):
        """The scan's progress: the wait (`(on,)`), the copy's count (`("copy", done, total)`) or what it found
        (`(found, shows)`)."""
        if self.state is None or self.state["step"] != "scan":
            return
        if len(said) == 1:
            if said[0]:
                self.task(S.LOAD_WAIT)
        elif said[0] == "copy":
            self.task(S.LOAD_COPY.format(done=said[1], total=said[2]))
            self._reading(said[2])
        else:
            self.task(S.LOAD_SCAN.format(episodes=_count(S.EPISODES, said[0]), shows=_count(S.SHOWS_N, said[1])))
            self._reading(said[0])

    def _reading(self, files):
        """Mado-FU2 (Fresh-U 19a, Sonic 2026-11-13): the load's first long read — the scan's or the copy's count of
        at least `token_index.POOL_MIN_FILES` files (fewer are read by one process, whatever *Use every core* says) —
        asks the caller's `long_read(screen)` once (setup's *Use every core*). Never the indexer's count: its pool is
        sized before its first count, so a flip then would speed nothing on screen; asked during the scan, it counts
        for the copy's pools and the indexer after it."""
        ask = self._long_read
        screen = self.loading
        if ask is None or screen is None or sip.isdeleted(screen):
            return
        from app.token_index import POOL_MIN_FILES
        try:
            if int(files) < POOL_MIN_FILES:
                return
        except (TypeError, ValueError):
            return
        self._long_read = None
        ask(screen)

    def stop(self):
        """*Stop*: the step under way keeps what it did (the scan stops between files; the indexer and the covers go on
        by themselves behind the screen) and the sorting comes up."""
        if self.state is None:
            return
        self.state["stopped"] = True
        if self.state["step"] == "scan":
            if self._stop_scan is not None:
                self._stop_scan()                     # its end goes on to the sorting (`scanned`)
        else:
            self._to_sort()

    def scanned(self, ids):
        """The scan ended with `ids` taken in: none — the cover goes (`empty()`); else the next step (the sorting at
        once after *Stop*)."""
        if self.state is None:
            return
        self.state["ids"] = list(ids or ())
        if not self.state["ids"]:
            self.end()
            if self._empty is not None:
                self._empty()
            return
        if self.state["stopped"]:
            self._to_sort()
        else:
            self.index()

    def _chores(self):
        """The window's chores — its services' (Kantan-B1: `shell.chores` is no attribute of the window, so this step
        was passed by in the app and setup never said *Reading the words*)."""
        return getattr(getattr(self.shell, "services", None), "chores", None)

    def index(self):
        """The token store's indexing, the window's own (`Chores.index(force=True)`), its count read from its log (only
        once this run wrote it)."""
        load = self.state
        load["step"] = "index"
        load["since"] = time.time()
        chores = self._chores()
        asked = chores.index(force=True) if chores is not None else "none"
        if asked not in (None, "busy"):               # off (a test's switch), closed, no chores: nothing to wait for
            self.covers()
            return
        self.task(S.LOAD_INDEX_START)
        self.tick()

    def tick(self):
        """Every half second while the words are read: the count from the log; and the step ends as soon as the
        window's chores have no index ask left — its run ended, or none came: never a cover waiting for a run that
        won't come."""
        load, chores = self.state, self._chores()
        if load is None or load["step"] != "index" or chores is None:
            return
        idle = getattr(chores, "indexing", None)
        if callable(idle) and not idle():
            self.covers()
            return
        from app.qt import applog, bridge
        from app.services import setup_load

        def shown(count):
            if count is not None and self.state is load and load["step"] == "index":
                self.task(S.LOAD_INDEX.format(done=count[0], total=count[1]))
        bridge.run_in_worker(setup_load.read_count, chores.index_log(), load["since"], then=self._guard(shown),
                             failed=lambda info: applog.log("load", f"indexer count: {info[0]}"))
        QTimer.singleShot(500, self._guard(self.tick))

    def indexed(self, language):
        """An indexer run ended: after three runs (the library changing all along) the step ends whatever they left —
        the indexer finishes it behind the window; before that, the tick sees the chores idle."""
        load = self.state
        if not self._alive() or load is None or load["step"] != "index" or language != self._language():
            return
        load["indexed"] += 1
        if load["indexed"] >= 3:
            self.covers()

    def covers(self):
        """The covers beside the files and in the EPUBs (`shell.scan_covers`, the window's own disk scan)."""
        from app.qt import bridge
        load = self.state
        load["step"] = "covers"
        scan = getattr(self.shell, "scan_covers", None)
        relay = bridge.Relay(self)

        def heard(said):
            if said[0] == "end" and not sip.isdeleted(relay):
                relay.deleteLater()                   # (after a Stop too: never left behind)
            if self.state is not load or load["step"] != "covers":
                return
            if said[0] == "end":
                self.anki()
            else:
                self.task(S.LOAD_COVERS.format(done=said[1], total=said[2]))
        relay.said.connect(self._guard(heard))
        thread = scan(progress=lambda done, total: relay.call(("count", done, total)),
                      then=lambda _found: relay.call(("end",))) if scan is not None else None
        if thread is None:
            relay.deleteLater()
            self.anki()
            return
        self.task(S.LOAD_COVERS_START)

    def anki(self):
        """Setup's page 2 known-words sync, still running: waited for (its end, `synced`); else on."""
        self.state["step"] = "anki"
        if self.setup and self._sync_running():
            self.task(S.LOAD_ANKI)
            return
        self.youtube()

    def synced(self):
        if self._alive() and self.state is not None and self.state["step"] == "anki":
            self.youtube()

    def youtube(self):
        """Alpha 8: setup's page 3 YouTube videos, still coming: waited for (their end goes on to the sorting; a
        stalled fetch ends itself, and *Stop* goes on without them); else on to the sorting."""
        if self.state is None:
            return
        self.state["step"] = "youtube"
        if self.setup and self._fetching():
            self.task(S.LOAD_YOUTUBE)
            return
        self._to_sort()

    def _to_sort(self):
        (self._sort or self.open_sort)()

    def open_sort(self):
        """The sort screen over the caller: every title in New arrivals (the window hands it each view)."""
        load = self.state
        if load is None or load["step"] == "sort" or not self._alive():
            return None
        load["step"] = "sort"
        screen = SortScreen(self.shell, door=self.door)
        screen.closed.connect(self._guard(self._sorted))
        self._cover(screen)
        return screen

    def _sorted(self, how=None):
        if self._after is not None:
            self._after(how)
        else:
            self.end()

    def end(self):
        """The run over: the cover gone, nothing more painted."""
        if self.ended:
            return
        self.ended = True
        if self._heard is not None:
            try:
                self._heard.indexed.disconnect(self.indexed)
            except (TypeError, RuntimeError):
                pass
        self._cover(None)


def _count(pair, n):
    """(one, many) for `n`: *1 episode*, *412 episodes* (the wizard's own)."""
    n = int(n or 0)
    return pair[0] if n == 1 else pair[1].format(n=n)


def cover_window(shell):
    """A cover over the window's central area for a `LoadRun` outside setup (Sort again): `cover(widget)` shows
    `widget` there, following its size (the one before it gone); `cover(None)` takes it away. `cover.covered()`: the
    widget shown, or None."""
    from app.qt import first_run
    area = shell.centralWidget()
    held = {"w": None, "parts": None}

    def cover(widget):
        old, held["w"] = held["w"], widget
        if widget is not None and held["parts"] is None:
            held["parts"] = first_run._hold(area)     # the window's parts under it take no focus (Tab, Enter)
        if widget is None and held["parts"] is not None:
            first_run._release(held["parts"])
            held["parts"] = None
        if widget is not None:
            widget.setParent(area)
            widget.setGeometry(area.rect())
            first_run._Cover(widget, area)
            widget.show()
            widget.raise_()
            widget.setFocus(Qt.FocusReason.OtherFocusReason)
        if old is not None and old is not widget and not sip.isdeleted(old):
            if shell.__dict__.get("_sort_screen") is old:
                del shell.__dict__["_sort_screen"]
            old.hide()
            qpress.let_go(old)                            # (its `_Cover` filters the area until it goes: Qt-C2)
    cover.covered = lambda: held["w"]
    return cover
