"""The frame (W3.1a package E; the RUNBOOK §1 *Frame*, *Header*, *Level ▾*, *Tabs*, *Footer*, *Goal dock*): the parts
of the window around the pages, in the redesign's flat look.

- **The edges** (`EdgeStrip`): the header + tabs band and the bottom band (the Goal dock over the footer) cast onto the
  content — a baked strip each, cached per width × device-pixel ratio, never a live effect; no side edges. The strips
  stand in the layout, never over a list: a sibling over a scrolling list turns off its fast scroll.
- **The header's progress** (`Progress`): Generate's share, a 1 px iris hairline along the header's foot; a job with
  no share shows it whole and quieter. It replaces the bar's pulsing dot: light never pulses.
- **The level ▾** (`LevelButton`) and **its pop** (`LevelPop`, a `motion.Overlay` in slate navy; W3.1b, the Level
  menu): *Level* ? and *Automatic*'s toggle, Settings' level slider (one name), words · % · how often, Generate and a
  gear to Settings › Level, *Open your journey*. A small mark on the ▾ while Generate is stale or failed (amber) or the
  journey's sentences are catching up (S6's lean).
- **The vein** (`Vein`): an uneven iris line under the current tab, from a fixed set of pre-drawn shapes (seeded,
  cached per width × ratio), its two ends travelling on springs (`vein-lead` ω 34, `vein-tail` ω 22); Reduced motion
  jumps it.
- **The footer's corner**: the emerald and *Anki · N waiting* (`AnkiMark`: lit while Anki answers, dark when it is
  closed, failed or off; N the new cards waiting in Anki, once the sync saved a backlog; the AnkiWeb mark's words in its
  hover) and the known number (`KnownCorner`: large and dim, a hairline under it toward the next 2,500, its progress in
  the hover; a click syncs now, Q30). The re-order's and Connect's lines are quiet marks beside it (`QuietMark`: a
  dim glyph, the words in the hover).
- **The Goal dock** (`GoalDock`): Goal's bar (its lift kept: the edge and a short cached shadow, L14) with the loose hand
  of covers, greyed once into its picture; while a drag runs, three wells — Soon · Goal · Finished — that package F
  drives through `begin_drag` / `well_at` / `hover` / `end_drag` / `set_unlit`.

Every picture is built at its first paint (nothing before the first frame); each part repaints only itself, only when
what it shows changed. Strings from `strings.py`, colours and sizes from `theme.py`.
"""
import html
import math
import random
from collections import OrderedDict

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from app import theme
from app.qt import motion, rows, shadow, strings, style
from app.qt import covers as qcovers                 # --- W3.2 Q6: the titles' own pictures

F = theme.FRAME
WELLS = ("soon", "goal", "finished")


# --- the choices (pure: the light mutants' targets) ---------------------------------------------------------------- #
def level_mark(failed, stale, journey_owed):
    """The ▾'s mark: "failed" (amber) before "stale" before "journey" (the sentences catching up), or None."""
    if failed:
        return "failed"
    if stale:
        return "stale"
    if journey_owed:
        return "journey"
    return None


def emerald_lit(key):
    """The emerald is lit while Anki answers (syncing, synced); closed, failed and off are the dark emerald."""
    return key in ("syncing", "synced")


def milestone(n):
    """(the next multiple of `known-step` above `n`, the share of the way to it 0–1)."""
    step = F["known-step"]
    n = max(0, int(n))
    return (n // step + 1) * step, (n % step) / step


def hand_angles(n):
    """The loose hand's turns, degrees: cover i at (i − 4) · `dock-cover-turn`, at most `dock-covers` of them."""
    return [(i - 4) * F["dock-cover-turn"] for i in range(min(n, F["dock-covers"]))]


def cover_grey(generated):
    """The loose hand's brightness for a cover (S4): a generated one — already a dark gradient — greyed lighter
    (`dock-cover-grey-generated`), real cover art at the reference's .62 (`dock-cover-grey`)."""
    return F["dock-cover-grey-generated"] if generated else F["dock-cover-grey"]


def wells_for(source):
    """The wells a drag from `source` shows, in order: Soon · Goal · Finished, Goal's left out when it comes from Goal."""
    return tuple(w for w in WELLS if not (w == "goal" and source == "goal"))


def _iris(x0, x1):
    grad = QLinearGradient(QPointF(x0, 0), QPointF(x1, 0))
    for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
        grad.setColorAt(pos, style.qcolor(colour))
    return grad


def _alpha(colour, a):
    q = QColor(colour)
    q.setAlphaF(a)
    return q


def _font(role):
    return rows.TEXT.font(role)


# --- the edges ------------------------------------------------------------------------------------------------------ #
class EdgeStrip(QWidget):
    """The frame's baked edge onto the content: "top" under the header + tabs band (its shadow falling down), "bottom"
    over the dock or the footer (its shadow rising). The content's ground with the shadow on it, one picture per width ×
    device-pixel ratio; it never repaints for anything else."""

    def __init__(self, side, parent=None):
        super().__init__(parent)
        self.side = side
        self.setObjectName(f"edge-{side}")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(F["edge-strip"])
        self._pix = self._key = None
        self.pictures = 0                                   # pictures built (tests: once per width × ratio)

    def paintEvent(self, _event):
        dpr = self.devicePixelRatioF() or 1.0
        key = (self.width(), self.height(), dpr, style.current()[0])
        if key != self._key:
            self._pix, self._key = self._picture(self.width(), self.height(), dpr), key
            self.pictures += 1
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix)
        p.end()

    def _picture(self, w, h, dpr):
        pix = QPixmap(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(rows.c("bg"))
        q = QPainter(pix)
        wide = 4 * h                                        # the band reaches past both sides: no side edges
        if self.side == "top":
            band, name = QRectF(-wide, -10 * h, w + 2 * wide, 10 * h), "frame-edge"
        else:
            band, name = QRectF(-wide, h, w + 2 * wide, 10 * h), "dock-edge"
        shadow.paint(q, band, name)
        q.end()
        return pix


# --- the header's progress ------------------------------------------------------------------------------------------ #
class Progress(QWidget):
    """Generate's share as a 1 px iris hairline along the header's foot; a job running with no share to show draws it
    whole, quieter. Nothing at rest. It follows the header's width and repaints only when what it shows changed."""

    def __init__(self, header):
        super().__init__(header)
        self.setObjectName("progress")
        self.setAccessibleName(strings.GENERATE_PROGRESS_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.busy, self.share = False, None
        self.paints = 0
        header.installEventFilter(self)
        self._follow()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._follow()
        return False

    def _follow(self):
        p = self.parentWidget()
        self.setGeometry(0, p.height() - 1, p.width(), 1)
        self.raise_()

    def set(self, busy, share=None):
        """`share` 0–100 (Generate's), or None. -> True when what it shows changed (and it repainted)."""
        busy = bool(busy) or share is not None
        share = None if share is None else max(0, min(100, share))
        if (busy, share) == (self.busy, self.share):
            return False
        self.busy, self.share = busy, share
        self.paints += 1
        self.update()
        return True

    def paintEvent(self, _event):
        if not self.busy:
            return
        p = QPainter(self)
        w = self.width()
        p.setOpacity(F["progress-busy-alpha"] if self.share is None else F["progress-alpha"])
        lit = w if self.share is None else w * self.share / 100.0
        p.fillRect(QRectF(0, 0, lit, self.height()), _iris(0, w))
        p.end()


# --- the level ▾ ---------------------------------------------------------------------------------------------------- #
class LevelButton(QToolButton):
    """The header's level: "{Auto · }{band}" and a chevron (painted: no box), ink-faint, ink under the hand or while
    its pop is open; a small mark on the chevron while Generate is stale or failed (amber) or the journey is owed.
    A click opens the pop (the shell connects it)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("level")
        self.mark = None
        self.open = False                                   # its pop is open (lit as under the hand)
        self.setText(strings.LEVEL_WAITING)
        self.setAccessibleName(strings.LEVEL_NAME.format(level=strings.LEVEL_WAITING))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paints = 0

    def set_level(self, text, tip):
        """-> True when its words or tooltip changed (repainted only then)."""
        if text == self.text() and tip == self.toolTip():
            return False
        if text != self.text():
            self.setText(text)
            self.setAccessibleName(strings.LEVEL_NAME.format(level=text))
            self.updateGeometry()
        self.setToolTip(tip)
        self.paints += 1
        self.update()
        return True

    def set_mark(self, mark):
        if mark == self.mark:
            return False
        self.mark = mark
        self.paints += 1
        self.update()
        return True

    def set_open(self, on):
        if bool(on) != self.open:
            self.open = bool(on)
            self.update()

    def sizeHint(self):
        f = theme.text_factor(style.current()[1])
        fm = rows.TEXT.metrics("level")
        w = round(10 * f) + fm.horizontalAdvance(self.text()) + round(6 * f) + F["chevron"] + F["mark-dot"] + 6
        return QSize(w, max(fm.height() + 8, round(theme.SIZES["button"] * f)))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        f = theme.text_factor(style.current()[1])
        lit = self.open or self.underMouse()
        ink = rows.c("ink" if lit else "ink-faint")
        mid = self.height() / 2
        x = round(10 * f)
        w, _cut = rows.TEXT.draw(p, x, mid, self.text(), "level", self.width(), ink, elide=False)
        cx = x + w + round(6 * f)
        c = F["chevron"]
        pen = QPen(ink, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(cx, mid - c * 0.25))
        path.lineTo(QPointF(cx + c / 2, mid + c * 0.25))
        path.lineTo(QPointF(cx + c, mid - c * 0.25))
        p.drawPath(path)
        if self.mark is not None:
            d = F["mark-dot"]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rows.c("warn" if self.mark == "failed" else "accent"))
            p.drawEllipse(QRectF(cx + c + 2, mid - c * 0.6 - d / 2, d, d))       # beside the chevron, never on it
        if self.hasFocus():
            ring = QPen(rows.c("accent"), 2)
            p.setPen(ring)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), theme.RADII["icon-button"],
                              theme.RADII["icon-button"])
        p.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class _Away(QObject):
    """A press outside the pop (and outside its ▾) closes it, as Esc does; the press goes on to what it was on."""

    def __init__(self, pop):
        super().__init__(pop)
        self.pop = pop

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.pop.isVisible():
            at = event.globalPosition().toPoint()
            mine = (self.pop.rect().translated(self.pop.mapToGlobal(self.pop.rect().topLeft())).contains(at) or
                    self.pop.button.rect().translated(self.pop.button.mapToGlobal(
                        self.pop.button.rect().topLeft())).contains(at))
            if not mine:
                self.pop.close()
        return False


class _Gear(QToolButton):
    """The pop's door to Settings › Level: a small painted gear (no box), ink-faint, ink under the hand."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("popgear")
        self.setToolTip(strings.LEVEL_POP_GEAR_TIP)
        self.setAccessibleName(strings.LEVEL_POP_GEAR_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        side = round(theme.SIZES["button"] * theme.text_factor(style.current()[1]))
        return QSize(side, side)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ink = rows.c("ink" if self.underMouse() or self.hasFocus() else "ink-faint")
        c = QPointF(self.width() / 2, self.height() / 2)
        r = min(self.width(), self.height()) * 0.22
        pen = QPen(ink, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r, r)
        p.drawEllipse(c, r * 0.4, r * 0.4)
        teeth = QPen(ink, max(2.4, r * 0.42))               # eight short, square teeth
        teeth.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(teeth)
        for k in range(8):
            a = k * math.pi / 4 + math.pi / 8
            p.drawLine(QPointF(c.x() + r * 0.95 * math.cos(a), c.y() + r * 0.95 * math.sin(a)),
                       QPointF(c.x() + r * 1.4 * math.cos(a), c.y() + r * 1.4 * math.sin(a)))
        if self.hasFocus():
            p.setPen(QPen(rows.c("accent"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), theme.RADII["icon-button"],
                              theme.RADII["icon-button"])
        p.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


def level_readout(preview):
    """The pop's readout for one band's numbers (W3.1b; the brief: only words, %, how often): "" for none."""
    if not preview:
        return ""
    words, coverage = f"{preview['word_count']:,}", f"{preview['coverage_percent']:.1f}"
    hours = preview.get("hours_between")
    if hours and hours > 0:
        if hours < 1:
            return strings.LEVEL_POP_READ_MINUTES.format(words=words, coverage=coverage,
                                                         minutes=max(1, round(hours * 60)))
        shown = f"{hours:.1f}".rstrip("0").rstrip(".") if hours < 10 else f"{round(hours):,}"
        return strings.LEVEL_POP_READ_HOURS.format(words=words, coverage=coverage, hours=shown)
    return strings.LEVEL_POP_READ_NO_TIME.format(words=words, coverage=coverage)


class LevelPop(motion.Overlay):
    """The level ▾'s pop (W3.1b, the brief's round-5 pop): *Level* with a quiet ? and, on the right, *Automatic* and its
    toggle; the level slider (Settings' own, one name: the chosen band's under its gem) in its well; the readout —
    words, %, how often; the foot: Generate (the shell adds it: `add_action`) and a gear to Settings › Level; then
    *Open your journey ↗* with the journey's dot. Slate navy with its lit top edge (`style.paint_overlay`); Esc, Back, a
    press elsewhere and the ▾ again close it.

    It decides nothing and writes nothing: a band picked (`picked`, its key), Automatic flipped (`automatic`, a bool)
    and the ? or the gear (`settings_asked`) go to the shell, which writes through the settings service as Settings
    does. `shown` asks the shell for the bands' numbers (`set_previews`), read on a worker."""
    how = "pop"
    shadow_name = "menu"
    focus = True
    picked = pyqtSignal(str)
    automatic = pyqtSignal(bool)
    settings_asked = pyqtSignal()
    shown = pyqtSignal()

    def __init__(self, parent, button):
        super().__init__(parent)
        from app import word_selection
        from app.qt import settings_controls as sc
        self.button = button
        self.setObjectName("levelpop")
        self.setAccessibleName(strings.LEVEL_POP_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        box.setContentsMargins(round(16 * f), round(12 * f), round(16 * f), round(14 * f))
        box.setSpacing(round(6 * f))
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(round(6 * f))
        self.heading = QLabel(strings.LEVEL_POP_HEADING, self)
        self.heading.setObjectName("popheading")
        head.addWidget(self.heading)
        self.help = QToolButton(self)
        self.help.setObjectName("pophelp")
        self.help.setText(strings.LEVEL_POP_HELP)
        self.help.setToolTip(strings.LEVEL_POP_HELP_TIP)
        self.help.setAccessibleName(strings.LEVEL_POP_HELP_NAME)
        self.help.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help.clicked.connect(lambda _c=False: self._to_settings())
        head.addWidget(self.help)
        head.addStretch(1)
        self.auto_word = QLabel(strings.LEVEL_POP_AUTO_WORD, self)
        self.auto_word.setObjectName("popline")
        head.addWidget(self.auto_word)
        self.auto_toggle = sc.Toggle(False, tooltip=strings.LEVEL_POP_AUTO_TIP, name=strings.LEVEL_POP_AUTO_WORD,
                                parent=self)
        self.auto_toggle.changed.connect(lambda on: self.automatic.emit(bool(on)))
        head.addWidget(self.auto_toggle)
        box.addLayout(head)
        self.bands = [(band, word_selection.band_label(band)) for band in word_selection.BANDS_ORDER]
        self.slider = sc.LevelSlider(self.bands, word_selection.BANDS_ORDER[0], tooltip=strings.LEVEL_POP_SLIDER_TIP,
                                     name=strings.LEVEL_POP_SLIDER_NAME, parent=self, one_name=True)
        self.slider.changed.connect(self._picked)
        box.addWidget(self.slider)
        self.read = QLabel("", self)
        self.read.setObjectName("popread")
        self.read.setTextFormat(Qt.TextFormat.PlainText)
        self.read.setVisible(False)
        box.addWidget(self.read)
        box.addSpacing(round(4 * f))
        self.foot = QHBoxLayout()
        self.foot.setContentsMargins(0, 0, 0, 0)
        self.foot.addStretch(1)
        self.gear = _Gear(self)
        self.gear.clicked.connect(lambda _c=False: self._to_settings())
        self.foot.addWidget(self.gear)
        box.addLayout(self.foot)
        self.actions = QVBoxLayout()
        self.actions.setSpacing(round(6 * f))
        box.addLayout(self.actions)
        self.level = None                                   # (band, automatic, waiting, coverage) shown
        self.waiting = False                                # Automatic on, its band not read yet
        self.coverage = None                                # the coverage target while the list follows it
        self.previews = None                                # every band's numbers, or None (no store yet)
        self.paints = 0
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        parent.installEventFilter(self)
        self.hide()

    def add_action(self, widget):
        """Generate, at the foot's left (the gear stays at its right); Tab reaches it before the gear."""
        self.foot.insertWidget(0, widget)
        self.setTabOrder(widget, self.gear)

    def set_level(self, band, automatic, waiting=False, coverage=None):
        """Show `band` (a key of `word_selection.BANDS_ORDER`; None or an unknown one leaves the slider where it is) and
        Automatic — no signal, no motion (showing is never a pick, S2). `waiting`: Automatic's band not read yet (the
        readout says so, never the band as written: S16). `coverage`: the list follows its coverage target (2.x's
        coverage mode, where the band does nothing): the slider greyed, the readout names the target. -> True when
        any of it changed."""
        level = (band, bool(automatic), bool(waiting), coverage)
        if level == self.level:
            return False
        self.level = level
        self.waiting, self.coverage = bool(waiting), coverage
        self.slider.setEnabled(coverage is None)
        self.auto_toggle.setEnabled(coverage is None)       # Automatic does nothing in coverage mode either
        self.slider.set_named(not self.waiting)             # no band read yet: no band named (S16)
        if band in {k for k, _n in self.bands} and band != self.slider.value():
            if self.slider.busy():
                self.level = None                           # a gesture under way wins; the next show puts it right
            else:
                self.slider.blockSignals(True)              # a shown band is never a pick
                try:
                    self.slider.set_value(band)
                finally:
                    self.slider.blockSignals(False)
        if self.auto_toggle.value() != bool(automatic):
            self.auto_toggle.set_value(bool(automatic))
        self._paint_readout()
        self.paints += 1
        return True

    def set_previews(self, previews):
        """Every band's numbers (`word_selection.band_previews`), or None: the readout for the slider's band."""
        if previews == self.previews:
            return False
        self.previews = previews
        return self._paint_readout()

    def _paint_readout(self):
        """The readout for the slider's band; repainted (and the pop placed again) only when its words changed."""
        preview = (self.previews or {}).get(self.slider.value())
        if self.coverage is not None:
            text, tip = strings.LEVEL_POP_COVERAGE.format(n=self.coverage), strings.LEVEL_POP_COVERAGE_TIP
        elif self.waiting:
            text, tip = strings.LEVEL_POP_AUTO_WAITING, strings.BAR_LEVEL_AUTO_NONE_TIP
        else:
            text, tip = level_readout(preview), None
        if text and tip is None:
            from app.qt import settings_live
            tip = settings_live.readout(preview)
        if text == self.read.text() and (not text or tip == self.read.toolTip()):
            return False
        self.read.setText(text)
        if text:
            self.read.setToolTip(tip)
        self.read.setVisible(bool(text))
        if self.isVisible():
            self.place()
        return True

    def _picked(self, band):
        """The slider let go in another chamber: the numbers there at once (they change when it locks), the pick to
        the shell."""
        self._paint_readout()
        if self.auto_toggle.value():
            self.auto_toggle.set_value(False)               # a hand pick turns Automatic off: shown at once (S2)
        self.picked.emit(band)

    def _to_settings(self):
        self.close()
        self.settings_asked.emit()

    def place(self):
        """Under its ▾, its right edge on the ▾'s, kept inside the window."""
        p = self.parentWidget()
        self.ensurePolished()
        width = min(round(theme.size("pop", style.current()[1])), p.width() - 16)
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        b = self.button
        at = b.mapTo(p, b.rect().bottomRight())
        x = max(8, min(at.x() - width, p.width() - width - 8))
        self.setGeometry(x, at.y() + 6, width, height)

    def open(self):
        self.place()
        return super().open()

    def toggle(self):
        if self.isVisible() or motion.opening_of(self) is not None:
            self.close()
        else:
            self.open()

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)
        self.button.set_open(True)
        self.shown.emit()                                   # the bands' numbers asked again (a worker's read)

    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)
        self.button.set_open(False)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["menu"])
        p.end()


# --- the vein ------------------------------------------------------------------------------------------------------- #
_VEINS = OrderedDict()                                     # (seed, width, ratio, theme) -> pixmap
VEINS_KEPT = 32


def vein_points(seed, w):
    """The vein's outline for `seed` at width `w` (its 5 px height): (top points, bottom points, node centres) — the
    reference's `r14VeinSVG`: 14 segments, a half-thickness that swells and thins along it and tapers to nothing at both
    ends, its middle wobbling a little."""
    h = F["vein-h"]
    n = F["vein-segments"]
    rng = random.Random(seed)
    top, bottom, mids = [], [], []
    for i in range(n + 1):
        u = i / n
        half = h * 0.26 * (0.62 + 0.22 * math.sin(6.1 * u + seed) + 0.14 * math.sin(13.7 * u + 2 * seed)
                           + 0.08 * rng.random()) * math.sin(math.pi * u) ** 0.55
        y = h / 2 + (rng.random() * 2 - 1) * 0.15
        top.append(QPointF(u * w, y - half))
        bottom.append(QPointF(u * w, y + half))
        mids.append((u * w, y, half))
    return top, bottom, [mids[i] for i in (2, 7, 12)]


def vein_picture(seed, w, dpr):
    """The vein's pre-drawn picture (cached: a fixed set of seeds, per width × ratio)."""
    w = max(1, int(round(w)))
    key = (seed, w, round(dpr, 3), style.current()[0])
    pix = _VEINS.get(key)
    if pix is not None:
        _VEINS.move_to_end(key)
        return pix
    h = F["vein-h"]
    pix = QPixmap(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    q = QPainter(pix)
    q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    top, bottom, nodes = vein_points(seed, w)
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(_iris(0, w))
    q.drawPolygon(QPolygonF(top + bottom[::-1]))
    white = theme.STONE["white"]
    q.setPen(QPen(_alpha(style.qcolor(white), F["vein-top-alpha"]), F["vein-top-w"]))
    q.setBrush(Qt.BrushStyle.NoBrush)
    q.drawPolyline(QPolygonF(top))
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(_alpha(style.qcolor(theme.FRAME_COLOURS["vein-node"]), F["vein-node-alpha"]))
    half_w = 1.6 * w / 100.0
    for x, y, half in nodes:
        q.drawPolygon(QPolygonF([QPointF(x - half_w, y), QPointF(x, y - 0.7 * half), QPointF(x + half_w, y),
                                 QPointF(x, y + 0.7 * half)]))
    q.end()
    _VEINS[key] = pix
    while len(_VEINS) > VEINS_KEPT:
        _VEINS.popitem(last=False)
    return pix


class Vein(QWidget):
    """The vein under the current tab: a strip along the tab bar's foot that paints one pre-drawn shape (each tab its
    own seed) between its two ends. `go(tab)` sends the ends there on springs — the leading end `vein-lead`, the
    trailing `vein-tail`, never past — while the page is there at once; Reduced motion jumps. A tab that moves for a
    layout (a count, Needs you shown) takes it along at once. It repaints only the span it leaves and the span it
    takes, inside the tab bar."""

    def __init__(self, bar):
        super().__init__(bar)
        self.setObjectName("vein")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.target = None
        self.seed = 0
        self.left = self.right = None
        self._lead = self._tail = None                      # the springs (left end, right end) once one moves
        self._tabs = []
        self.paints = 0
        bar.installEventFilter(self)
        self._follow()

    def track(self, buttons):
        """The tabs it may sit under, in order (each its seed; their moves take it along)."""
        self._tabs = list(buttons)
        for b in self._tabs:
            b.installEventFilter(self)

    def _follow(self):
        bar = self.parentWidget()
        h = F["vein-h"]
        self.setGeometry(0, bar.height() - h, bar.width(), h)
        self.raise_()

    def span(self, button):
        """(left, right) under `button`, `vein-inset` in from its sides, never narrower than `vein-min`."""
        g = button.geometry()
        inset, least = F["vein-inset"], F["vein-min"]
        left, right = g.left() + inset, g.left() + g.width() - inset
        if right - left < least:
            mid = (left + right) / 2
            left, right = mid - least / 2, mid + least / 2
        return float(left), float(right)

    def go(self, button, animate=True):
        self.target = button
        self.seed = self._tabs.index(button) % F["vein-seeds"] if button in self._tabs else 0
        left, right = self.span(button)
        if self.left is None or not animate:
            self._jump(left, right)
            return
        rightwards = right > self.right
        lead, tail = motion.preset("vein-lead"), motion.preset("vein-tail")
        on_left, on_right = (tail, lead) if rightwards else (lead, tail)
        clock = motion.clock()
        if self._lead is None:
            self._lead = clock.spring(self._set_left, self.left, left, owner=self, **on_left)
            self._tail = clock.spring(self._set_right, self.right, right, owner=self, **on_right)
        else:
            self._lead.retarget(left, **on_left)
            self._tail.retarget(right, **on_right)

    def _jump(self, left, right):
        for s in (self._lead, self._tail):
            if s is not None:
                s.stop()
        self._lead = self._tail = None                      # the next move sets out from here
        old = self._rect()
        self.left, self.right = left, right
        self._dirty(old)

    def moving(self):
        return any(s is not None and s.alive for s in (self._lead, self._tail))

    def _set_left(self, v):
        old = self._rect()
        self.left = v
        self._dirty(old)

    def _set_right(self, v):
        old = self._rect()
        self.right = v
        self._dirty(old)

    def _rect(self):
        if self.left is None:
            return None
        return QRectF(min(self.left, self.right) - 1, 0, abs(self.right - self.left) + 2, self.height())

    def _dirty(self, old):
        new = self._rect()
        area = new if old is None else old.united(new)
        self.update(area.toAlignedRect())

    def eventFilter(self, obj, event):
        et = event.type()
        if obj is self.parentWidget() and et in (QEvent.Type.Resize, QEvent.Type.Show):
            self._follow()
            if self.target is not None and not self.moving():
                self._jump(*self.span(self.target))
        elif obj is self.target and et in (QEvent.Type.Move, QEvent.Type.Resize) and not self.moving():
            self._jump(*self.span(self.target))
        return False

    def paintEvent(self, _event):
        if self.left is None or self.target is None:
            return
        self.paints += 1
        left, right = min(self.left, self.right), max(self.left, self.right)
        rest = self.span(self.target)
        pix = vein_picture(self.seed, rest[1] - rest[0], self.devicePixelRatioF() or 1.0)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(left, 0, max(F["vein-min"], right - left), self.height()), pix,
                     QRectF(0, 0, pix.width(), pix.height()))
        p.end()


# --- the footer's corner -------------------------------------------------------------------------------------------- #
class AnkiMark(QWidget):
    """The footer's Anki: the emerald — flat, a filled circle with one facet highlight, lit while Anki answers, the dark
    emerald while it is closed, failed or off (its hover says which) — and *Anki*, or *Anki · N waiting* once the sync
    has saved a backlog (W31A-2: the new cards waiting in Anki; `set_waiting`). The AnkiWeb mark's words live in its
    hover. A status, no click (W3.3). Shown while it has something to say."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ankimark")
        self.key = None
        self.words = self.tip = self.ankiweb = ""
        self.waiting = None              # the cards waiting in Anki (None: no backlog saved — just *Anki*)
        self.lit = False
        self.paints = 0
        self.setVisible(False)

    def text(self):
        return strings.FOOT_ANKI if self.waiting is None else strings.FOOT_ANKI_WAITING.format(n=self.waiting)

    def set_waiting(self, n):
        """The new cards waiting in Anki (the status service's `backlog`: a count, or None while no backlog file
        exists). -> True when it changed (and the mark repainted)."""
        n = None if n is None else max(0, int(n))
        if n == self.waiting:
            return False
        self.waiting = n
        self._refresh()
        return True

    def show_state(self, key, words="", tip=""):
        """The sync's state (`strings.BAR_ANKI`'s key, or None: nothing to say). -> True when it changed."""
        if (key, words, tip) == (self.key, self.words, self.tip):
            return False
        self.key, self.words, self.tip = key, words, tip
        self.lit = emerald_lit(key)
        self._refresh()
        return True

    def set_ankiweb(self, text):
        """The AnkiWeb mark's words (or ""), shown in the hover. -> True when they changed."""
        text = text or ""
        if text == self.ankiweb:
            return False
        self.ankiweb = text
        self._refresh()
        return True

    def _refresh(self):
        tip = strings.FOOT_ANKI_TIP.format(words=self.words, tip=self.tip) if self.key is not None else ""
        if self.ankiweb:
            tip = strings.FOOT_ANKI_ANKIWEB.format(tip=tip, ankiweb=self.ankiweb) if tip else self.ankiweb
        words = self.words or self.ankiweb
        if self.waiting is not None:                        # what N counts, last in the hover
            said = strings.FOOT_ANKI_WAITING_TIP.format(n=self.waiting)
            tip = f"{tip}\n\n{said}" if tip else said
            words = f"{words} · {said}" if words else said
        if Qt.mightBeRichText(tip):                         # a provider's words are never markup: shown as written
            tip = "<p>" + html.escape(tip).replace("\n", "<br>") + "</p>"
        self.setToolTip(tip)
        self.setAccessibleName(strings.FOOT_ANKI_NAME.format(words=words))
        self.setVisible(self.key is not None or bool(self.ankiweb) or self.waiting is not None)
        self.updateGeometry()
        self.paints += 1
        self.update()

    def sizeHint(self):
        f = theme.text_factor(style.current()[1])
        w = round(9 * f) * 2 + F["emerald"] + round(6 * f) + rows.TEXT.metrics("foot-chip").horizontalAdvance(self.text())
        return QSize(w, round(27.6 / 1.15 * f))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = theme.text_factor(style.current()[1])
        d = F["emerald"]
        x, mid = round(9 * f), self.height() / 2
        if self.lit:
            base, light = theme.GEM["emerald"][0], theme.GEM["emerald"][1]
        else:
            base, light = theme.FRAME_COLOURS["emerald-dark-base"], theme.FRAME_COLOURS["emerald-dark-light"]
        r = d / 2
        cx, cy = x + r, mid
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(base))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(_alpha(style.qcolor(light), F["emerald-facet-alpha"]))      # the one facet, lit from the top left
        p.drawPolygon(QPolygonF([QPointF(cx - 0.62 * r, cy - 0.18 * r), QPointF(cx - 0.12 * r, cy - 0.74 * r),
                                 QPointF(cx + 0.4 * r, cy - 0.46 * r), QPointF(cx - 0.04 * r, cy + 0.02 * r)]))
        rows.TEXT.draw(p, x + d + round(6 * f), mid, self.text(), "foot-chip", self.width(), rows.c("ink-dim"),
                       elide=False)
        p.end()


class KnownCorner(QToolButton):
    """The known words, bottom right: the number large and dim, *known* beside it on its baseline, and a hairline under
    them toward the next 2,500 (lit up to the share), its progress in the hover. Q30: a button (painted, as the level
    ▾ is: a screen reader hears a button) — a click, Space or Enter, one Tab stop like the bar's buttons — asks for a
    sync now (`clicked`: the shell hands it to `Automation.sync_now`, or opens the Anki window while there is nothing
    to sync from yet). Its hover's last line, and its accessible description, say what a click does on the road shown
    (`set_road`, the page's known-words road: Anki's decks chosen, a sync; none, the Anki window), or, while a sync
    runs (`set_syncing`), that one is running (IK-7).
    Round 8 row 45 (round 2, Sonic: "the underline glow the surasura colors as it goes, so a bar that fills up until
    it's done … fitting the actual shape of it"): a click's sync shows at once on the hairline itself (`press_look`, the
    press's own look) — the iris filling it to the sync's share (`set_work_share`, the registry job's progress) or, with
    no share known, an iris glint running along it on the spinner's clock (`motion.Turn`; under Reduced motion the
    hairline whole, still). No words, nothing moves; the milestone's share comes back when the sync ends."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("knowncorner")
        self.n = None
        self.said = ""                   # the shell's words, the hover's first line
        self.syncing = False
        self.working = False             # round 8 row 45: a click's sync under way (the hairline shows it)
        self.work_share = None           # ... its share 0–100, when the registry knows it
        self._turn = None                # ... the glint's phase while no share is known
        self._line = QRectF()            # ... where the hairline was painted (a glint frame repaints that alone)
        self.road = "anki"               # "anki" (a click syncs) or "import" (no decks yet: it opens the Anki window)
        self.paints = 0
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(strings.FOOT_KNOWN_NAME)    # a button names itself, a count or not (the wiring check)
        self.setAccessibleDescription(self._click())
        self.setToolTip(self._tip(None))
        self.setVisible(False)

    def text(self):
        return strings.BAR_KNOWN.format(n=self.n) if self.n is not None else ""

    def set_known(self, n, tip=""):
        """-> True when the count (or its tip) changed."""
        if n is None:
            if self.n is None and self.isHidden():
                return False
            self.n = None
            self.setToolTip(self._tip(None))
            self.setAccessibleName(strings.FOOT_KNOWN_NAME)
            self.setVisible(False)
            self.paints += 1
            return True
        self.said = tip
        tip = self._tip(n)
        if n == self.n and tip == self.toolTip() and not self.isHidden():
            return False
        self.n = n
        self.setToolTip(tip)
        self.setAccessibleName(self.text())
        self.setVisible(True)
        self.updateGeometry()
        self.paints += 1
        self.update()
        return True

    def _click(self):
        """What a click does now, in words: a sync is running · it opens the Anki window · it syncs."""
        if self.syncing:
            return strings.FOOT_KNOWN_SYNCING
        return strings.FOOT_KNOWN_CLICK_ANKI if self.road == "import" else strings.FOOT_KNOWN_CLICK

    def _tip(self, n):
        if n is None:
            return strings.FOOT_KNOWN_NONE_TIP.format(name=strings.FOOT_KNOWN_NAME, click=self._click())
        nxt, _share = milestone(n)
        return strings.FOOT_KNOWN_TIP.format(tip=self.said, left=nxt - n, next=nxt, click=self._click())

    def _said_again(self):
        self.setAccessibleDescription(self._click())
        self.setToolTip(self._tip(self.n))

    def set_syncing(self, on):
        """A sync is running (the automation's state): the hover says so instead of what a click does. -> True when it
        changed."""
        on = bool(on)
        if on == self.syncing:
            return False
        self.syncing = on
        self._said_again()
        return True

    # --- round 8 row 45 (round 2): the press shown on the hairline ------------------------------------------------- #
    def press_look(self, on):
        """`app/qt/press.py`'s hook: a click's sync under way (on) or ended. Painted now (the press repaints)."""
        on = bool(on)
        if on == self.working:
            return
        self.working, self.work_share = on, None
        if on:
            self._turn = motion.Turn(self, self._glinted, period="press-glint")
            self._turn.show()
            self._turn.set_running(True)
        elif self._turn is not None:
            self._turn.set_running(False)
            self._turn.deleteLater()
            self._turn = None
        self.update()

    def set_work_share(self, share):
        """The sync's share (0–100), or None: not known (the glint runs). -> True when it changed."""
        share = None if share is None else max(0.0, min(100.0, float(share)))
        if not self.working or share == self.work_share:
            return False
        self.work_share = share
        self.update(self._line.toAlignedRect())
        return True

    def _glinted(self):
        if self.work_share is None:
            self.update(self._line.toAlignedRect())

    def _paint_work(self, p, x, y, span):
        """The hairline while a click's sync runs: its track, then the iris — filled to the share, or a glint running
        along it (still: whole, quieter) — with a soft glow a pixel either side."""
        p.setOpacity(1.0)
        p.fillRect(QRectF(x, y, span, 1), style.qcolor(theme.FRAME_COLOURS["milestone-left"]))
        phase = self._turn.turning if self._turn is not None else None
        if self.work_share is not None:
            lit, a = QRectF(x, y, span * self.work_share / 100.0, 1), 1.0
        elif phase is None:
            lit, a = QRectF(x, y, span, 1), F["progress-busy-alpha"] + 0.4
        else:
            w = span * 0.35                              # the glint: a third of the line, from past its left to past its right
            left = x - w + phase * (span + w)
            lit, a = QRectF(left, y, w, 1).intersected(QRectF(x, y, span, 1)), 1.0
        if lit.width() <= 0:
            return
        grad = _iris(x, x + span)
        if self.work_share is None and phase is not None:   # the glint's own ends fade into the track
            grad = QLinearGradient(QPointF(left, 0), QPointF(left + w, 0))
            for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
                c = QColor(colour)
                c.setAlphaF(math.sin(math.pi * pos) if 0 < pos < 1 else 0.0)
                grad.setColorAt(pos, c)
        p.setOpacity(a * 0.3)
        p.fillRect(lit.adjusted(0, -1, 0, 1), grad)       # the glow
        p.setOpacity(a)
        p.fillRect(lit, grad)
    # --- end round 8 row 45

    def set_road(self, road):
        """The known-words road shown ("anki" / "import"): the hover's click line follows it. -> True when it changed
        (only the tip and the description: nothing to repaint)."""
        road = "import" if road == "import" else "anki"
        if road == self.road:
            return False
        self.road = road
        self._said_again()
        return True

    # --- the click (Q30): the button's own press, release and Space; Enter too, as the bar's buttons take it -------- #
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def _parts(self):
        number = f"{self.n:,}" if self.n is not None else ""
        return number, strings.FOOT_KNOWN

    def sizeHint(self):
        number, word = self._parts()
        w = rows.TEXT.metrics("known-number").horizontalAdvance(number) + 6 + \
            rows.TEXT.metrics("foot-chip").horizontalAdvance(word) + 4
        return QSize(w, rows.TEXT.metrics("known-number").height())

    def paintEvent(self, _event):
        if self.n is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        number, word = self._parts()
        big, small = rows.TEXT.metrics("known-number"), rows.TEXT.metrics("foot-chip")
        base = round((self.height() + big.ascent() - big.descent()) / 2) - 2
        p.setFont(_font("known-number"))
        p.setPen(style.qcolor(theme.FRAME_COLOURS["known-ink"]))
        p.drawText(QPointF(2, base), number)
        x = 2 + big.horizontalAdvance(number) + 6
        p.setFont(_font("foot-chip"))
        p.setPen(rows.c("ink-faint"))
        p.drawText(QPointF(x, base), word)
        _nxt, share = milestone(self.n)
        y = min(self.height() - 1, base + max(3, small.descent()) + 1)
        span = self.width() - 4
        self._line = QRectF(0, y - 1, self.width(), 3)
        if self.working:                                 # round 8 row 45: the click's sync, on the hairline
            self._paint_work(p, 2, y, span)
        else:
            p.setOpacity(F["known-hairline-alpha"])
            p.fillRect(QRectF(2, y, span, 1), style.qcolor(theme.FRAME_COLOURS["milestone-left"]))
            p.fillRect(QRectF(2, y, span * share, 1), style.qcolor(theme.IRIS["night"][1][1]))
        if self.hasFocus():                              # the keyboard's ring, as the level ▾'s
            p.setOpacity(1.0)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(rows.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), theme.RADII["icon-button"],
                              theme.RADII["icon-button"])
        p.end()


class QuietMark(QLabel):
    """W31A-1: a status the redesign doesn't draw, kept quietly — the re-order's line, Connect's: a small dim glyph in
    the footer, its words in the hover and the accessible description (`full()`), shown only while it has something
    to say. A status, no click."""

    def __init__(self, glyph, name, parent=None):
        super().__init__(glyph, parent)
        self.setObjectName("barmark")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAccessibleName(name)
        self._full = ""
        self.setVisible(False)

    def set_full(self, text):
        self._full = text or ""
        self.setAccessibleDescription(self._full)

    def full(self):
        return self._full


# --- the Goal dock -------------------------------------------------------------------------------------------------- #
def _title(row):
    return getattr(row, "cover_title", None) or getattr(row, "title", "") or ""


def well_covers(view):
    """The covers each well shows of where a drop lands, from the reader's view: Soon — the three before the Soon line
    and the three after it; Goal — its last three; Finished — the three newest. -> {"soon": (before, after), "goal":
    titles, "finished": titles}."""
    k = F["well-covers"]
    rows_ = tuple(getattr(view, "rows", ()) or ())
    first = next((ln.after + 1 for ln in (getattr(view, "lines", ()) or ()) if ln.kind == "soon"), len(rows_))
    before = tuple(_title(r) for r in rows_[max(0, first - k):first])
    after = tuple(_title(r) for r in rows_[first:first + k])
    goal = getattr(view, "goal", None)
    goal_titles = tuple((goal.covers if goal is not None else ())[-k:])
    finished = []
    for month in getattr(view, "finished", ()) or ():
        for r in month.rows:
            finished.append(_title(r))
            if len(finished) == k:
                break
        if len(finished) == k:
            break
    return {"soon": (before, after), "goal": goal_titles, "finished": tuple(finished)}


def _bar_of(goal):
    """--- W3.2 Q2: what Goal's bar shows of a `Goal` (all but the sheet's tiles), or None."""
    return None if goal is None else tuple(goal)[:5]


class GoalDock(QWidget):
    """The bottom band's dock over the footer (Current only): Goal's bar — the box mark, *Goal*, the loose hand of up to
    nine covers (26 × 37, overlapping by 12, each turned (i − 4) · 2°, greyed once into the picture), *N titles · N
    files* — on the `goal-bar` stone with its lit edge and a short shadow, all one picture cached per goal × width ×
    ratio. While a drag runs (package F), the bar gives way to the wells:

    - `begin_drag(source)`: Soon · Goal · Finished rise (Goal's left out when the drag comes from Goal);
    - `well_at(global_pos)` -> the well's name under that point, or None;
    - `hover(name or None)`: that well lit (`well-lit`) and its slot opening on a spring (`slot`, ω 28.3, ζ .5);
    - `set_unlit(name, tip or None)`: that well never lights (a split's first part, hato's mix on Finished), its
      tooltip says why (`unlit_tip(name)`);
    - `end_drag()`: the wells fall, the bar comes back, the unlit wells are lit again. The bar is back at once, under
      the falling wells — its new count (and the dock's accessible name) at the drop, never after the fall (Gap 2).

    Only the dock repaints, and only for what moved.

    W3.2 Q2: a click on the bar (a press and its release on it, never during a drag) asks for Goal's sheet
    (`sheet_requested`; the shell opens or closes it)."""
    sheet_requested = pyqtSignal()                   # --- W3.2 Q2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("goaldock")
        self.setCursor(Qt.CursorShape.PointingHandCursor)       # --- W3.2 Q2: the bar opens the sheet
        self._pressed_at = None                                  # --- W3.2 Q2
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(strings.GOAL_NAME)
        self.goal = None
        self.wells = ()                  # the wells shown while a drag runs, in order (none: the bar)
        self.source = None
        self.lit = None                  # the well under the hand
        self.rise = 0.0                  # how far below their place the wells are (rising, falling)
        self.falling = False             # the drag ended: the wells fall over the bar, shown again under them
        self._covers = {"soon": ((), ()), "goal": (), "finished": ()}
        self._unlit = {}
        self._slots = {}                 # well -> its slot's spring
        self._slot_w = {}                # well -> its slot's width now
        self._anim = None
        self._pix = self._key = None
        self._hand = self._hand_key = None
        self.pictures = self.hands = self.paints = 0
        # --- W3.2 Q6: each cover's record by title (the wells'), a title's picture landing repaints the dock
        self._refs = {}
        self._seen = None                # (rows, finished, goal) the refs were walked from (C2)
        self.walks = 0                   # walks of the view's rows (tests)
        qcovers.notifier().ready.connect(self._cover_ready)
        # --- end W3.2 Q6
        self.apply_size()

    # --- size and the goal -------------------------------------------------------------------------------------- #
    def bar_h(self):
        return F["goal-bar"] * theme.text_factor(style.current()[1])

    def apply_size(self):
        top, _side = F["dock-pad"]
        self.setFixedHeight(round(2 * top + self.bar_h()))

    def sizeHint(self):
        return QSize(400, self.height())

    def set_goal(self, goal):
        """The same `Goal` the strip took (`view_rows.Goal`). -> True when it changed (and the dock repainted)."""
        bar = _bar_of(goal)                                     # --- W3.2 Q2: the bar never reads the sheet's tiles
        if bar == _bar_of(self.goal):
            self.goal = goal                                    # the newest kept; nothing the bar shows changed
            return False
        self.goal = goal
        self.setToolTip(goal.tip if goal is not None else "")
        if not self.wells or self.falling:
            self._name_bar()
        self.update()
        return True

    def _name_bar(self):
        """The bar's tooltip and accessible name, for the goal it shows."""
        goal = self.goal
        self.setToolTip(goal.tip if goal is not None else "")
        self.setAccessibleName(strings.GOAL_ACCESSIBLE.format(name=strings.GOAL_NAME, line=goal.line)
                               if goal is not None else strings.GOAL_NAME)

    def set_view(self, view):
        """The covers the wells show, from the reader's newest view (kept for the next drag; nothing repaints)."""
        self._covers = well_covers(view)
        # --- W3.2 Q6: the wells' covers' records, by title (`well_covers` keeps titles)
        seen = (getattr(view, "rows", None), getattr(view, "finished", None), getattr(view, "goal", None))
        if self._seen is not None and seen[2] is self._seen[2] and all(
                a is b or (a is not None and b is not None and len(a) == len(b) and all(x is y for x, y in zip(a, b)))
                for a, b in zip(seen[:2], self._seen[:2])):
            return                       # C2: a move's next view of the same rows (in a new tuple too): nothing walked
        self._seen = seen
        self.walks += 1
        refs = {}
        for r in tuple(getattr(view, "rows", ()) or ()) + tuple(r for m in getattr(view, "finished", ()) or ()
                                                              for r in m.rows):
            refs.setdefault(_title(r), getattr(r, "cover", None))
        goal = getattr(view, "goal", None)
        if goal is not None:
            for title, ref in zip(goal.covers, getattr(goal, "cover_refs", ())):
                refs.setdefault(title, ref)
        self._refs = refs

    def _cover_ready(self, work_id):
        """A title's picture landed: the bar's picture drawn again when its hand shows it, the wells when they do."""
        goal_refs = getattr(self.goal, "cover_refs", ()) if self.goal is not None else ()
        if any(ref and tuple(ref)[0] == work_id for ref in goal_refs):
            self._key = self._hand_key = None
            self.update()
        elif self.wells and any(ref and tuple(ref)[0] == work_id for ref in self._refs.values()):
            self.update()
        # --- end W3.2 Q6

    def bar_rect(self):
        top, side = F["dock-pad"]
        return QRectF(side, top, max(0, self.width() - 2 * side), self.bar_h())

    # --- W3.2 Q2: the bar's click --------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        on_bar = not self.wells and self.bar_rect().contains(event.position())
        self._pressed_at = event.position() if on_bar and event.button() == Qt.MouseButton.LeftButton else None
        event.accept()

    def mouseReleaseEvent(self, event):
        at, self._pressed_at = self._pressed_at, None
        if at is None or self.wells or event.button() != Qt.MouseButton.LeftButton:
            return
        moved = (event.position() - at).manhattanLength()
        if self.bar_rect().contains(event.position()) and moved < theme.MOTION["drag-start-px"]:
            self.sheet_requested.emit()
    # --- end W3.2 Q2

    # --- the wells' API (package F drives it) ------------------------------------------------------------------- #
    def begin_drag(self, source):
        self.source = source
        self.falling = False
        self.wells = wells_for(source)
        self.lit = None
        self._unlit = {}                         # a drag begun while the last one's wells fell: never its dark wells
        self._slot_w = {w: float(F["well-slot"]) for w in self.wells}
        for s in self._slots.values():
            s.stop()
        self._slots = {}
        self.setAccessibleName(strings.WELLS_NAME.format(wells=" · ".join(strings.WELLS[w] for w in self.wells)))
        self.setToolTip("")
        self._move(0.0, from_=float(theme.MOTION["buckets-rise"]))

    def end_drag(self):
        if not self.wells:
            return
        self.hover(None)
        self.falling = True                      # the bar (and its name) back now; the wells' fall is a look only
        self._name_bar()

        def gone():
            self.wells, self.source, self._unlit, self.falling = (), None, {}, False
            self.update()
        self._move(float(theme.MOTION["buckets-rise"]), done=gone)

    def _move(self, to, from_=None, done=None):
        """The wells rising (to 0) or falling (to `buckets-rise`) on the clock, `buckets` long; Reduced motion jumps."""
        if self._anim is not None:
            self._anim.stop()
        start = self.rise if from_ is None else from_
        self.rise = start

        def frame(v):
            self.rise = start + (to - start) * v
            self.update()
        self._anim = motion.clock().animate(theme.MOTION["buckets"], frame, on_done=done, kind="move", owner=self)

    def well_rects(self):
        """{well: its rect at rest} (the hit areas: a rising well is hit where it lands)."""
        bar = self.bar_rect()
        n = len(self.wells)
        if not n:
            return {}
        gap = F["well-gap"]
        w = (bar.width() - gap * (n - 1)) / n
        return {name: QRectF(bar.left() + i * (w + gap), bar.top(), w, bar.height())
                for i, name in enumerate(self.wells)}

    def well_at(self, global_pos):
        if not self.wells or not self.isVisible():
            return None
        at = QPointF(self.mapFromGlobal(global_pos))
        for name, r in self.well_rects().items():
            if r.contains(at):
                return name
        return None

    def hover(self, name):
        """The hand is over well `name` (or none): it lights, unless unlit, and its slot opens; the others close."""
        name = name if name in self.wells else None
        lit = name if name not in self._unlit else None
        if name is not None:
            self.setToolTip(self._unlit.get(name) or strings.WELL_TIPS[name])
        if lit == self.lit:
            return
        rects = self.well_rects()
        for w in {self.lit, lit} - {None}:
            self.update(rects[w].adjusted(-2, -2, 2, 2).toAlignedRect())
        self.lit = lit
        cw = float(F["dock-cover"][0])
        for w in self.wells:
            target = cw if w == lit else float(F["well-slot"])
            spring = self._slots.get(w)
            if spring is None:
                if target == self._slot_w.get(w):
                    continue
                self._slots[w] = motion.clock().spring(lambda v, w=w: self._set_slot(w, v), self._slot_w[w], target,
                                                       owner=self, **motion.preset("slot"))
            else:
                spring.retarget(target, **motion.preset("slot"))

    def _set_slot(self, well, v):
        self._slot_w[well] = v
        r = self.well_rects().get(well)
        if r is not None:
            self.update(r.adjusted(-2, -2, 2, 2).toAlignedRect())

    def slot_width(self, well):
        return self._slot_w.get(well)

    def set_unlit(self, well, tip):
        """`well` stays unlit for this drag, its tooltip `tip` (None: lit again)."""
        if tip:
            self._unlit[well] = tip
            if self.lit == well:
                self.hover(None)
        else:
            self._unlit.pop(well, None)

    def unlit_tip(self, well):
        return self._unlit.get(well)

    # --- painting ------------------------------------------------------------------------------------------------ #
    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        if self.wells:
            if self.falling:                     # the bar under the wells falling away from it
                p.drawPixmap(0, 0, self._bar_pixmap())
                band = self.bar_rect().adjusted(-1, -1, 1, 1)           # (the wells' clip)
                p.fillRect(band.translated(0, self.rise).intersected(band), rows.c("frame"))
            else:
                p.fillRect(self.rect(), rows.c("frame"))
            self._paint_wells(p)
        else:
            p.drawPixmap(0, 0, self._bar_pixmap())
        p.end()

    def _bar_pixmap(self):
        """The bar's picture, drawn again only when the goal, the size, the ratio or the look changed."""
        dpr = self.devicePixelRatioF() or 1.0
        key = (_bar_of(self.goal), self.width(), self.height(), dpr, style.current())     # (W3.2 Q2)
        if key != self._key:
            self._pix, self._key = self._bar_picture(dpr), key
            self.pictures += 1
        return self._pix

    def _bar_picture(self, dpr):
        pix = QPixmap(max(1, math.ceil(self.width() * dpr)), max(1, math.ceil(self.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(rows.c("frame"))
        if self.goal is None:
            return pix
        q = QPainter(pix)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        bar = self.bar_rect()
        radius = F["goal-bar-radius"]
        shadow.paint(q, bar, "goal-bar")                    # its lift: a short shadow and its lit edge (L14)
        path = QPainterPath()
        path.addRoundedRect(bar, radius, radius)
        q.fillPath(path, rows.c("goal-bar"))
        q.save()
        q.setClipPath(path)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        edge = max(1, round(dpr)) / dpr
        q.fillRect(QRectF(bar.left(), bar.top(), bar.width(), edge), rows.c("goal-bar-edge"))
        q.restore()
        mid = bar.center().y()
        x = bar.left() + 14
        rows.icon(q, "box", QRectF(x, mid - 8.5, 17, 17), rows.c("ink-dim"))
        x += 17 + 12
        w, _cut = rows.TEXT.draw(q, x, mid, strings.GOAL_NAME, "goal-label", 200, rows.c("ink"), dpr=dpr)
        x += w + 12
        if self.goal.covers:
            hand, room = self._hand_picture(dpr)
            q.setOpacity(F["dock-cover-alpha"])
            q.drawPixmap(QPointF(x - room, mid - hand.height() / dpr / 2), hand)
            q.setOpacity(1.0)
            x += hand.width() / dpr - 2 * room + 12
        rows.TEXT.draw(q, x, mid, self.goal.line, "row-sub", bar.right() - x - 14, rows.c("ink-dim"), dpr=dpr)
        q.end()
        return pix

    def _hand_picture(self, dpr):
        """The loose hand, greyed once: (pixmap, the room around it for the turned covers)."""
        covers = tuple(self.goal.covers[:F["dock-covers"]])
        cw, ch = F["dock-cover"]
        # --- W3.2 Q6: each title's own picture once decoded (greyed darker: real art at .62), the generated meanwhile
        refs = tuple(getattr(self.goal, "cover_refs", ()))[:len(covers)]
        refs += (None,) * (len(covers) - len(refs))
        real = tuple(qcovers.decoded(ref, cw, ch, dpr, "stack") is not None for ref in refs)
        key = (covers, refs, real, dpr, style.current())
        # --- end W3.2 Q6
        if key == self._hand_key:
            return self._hand
        step = cw - F["dock-cover-overlap"]
        room = math.ceil(ch * math.sin(math.radians(4 * F["dock-cover-turn"]))) + 2
        w = step * (len(covers) - 1) + cw + 2 * room
        h = ch + 2 * room
        img = QImage(math.ceil(w * dpr), math.ceil(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ring = style.qcolor(theme.ROOM["ground"])
        radius = theme.RADII["cover-stack"]
        for i, (title, turn) in enumerate(zip(covers, hand_angles(len(covers)))):
            q.save()
            q.translate(room + i * step + cw / 2, room + ch / 2)
            q.rotate(turn)
            r = QRectF(-cw / 2, -ch / 2, cw, ch)
            ring_path = QPainterPath()
            ring_path.addRoundedRect(r.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
            q.fillPath(ring_path, ring)
            clip = QPainterPath()
            clip.addRoundedRect(r, radius, radius)
            q.setClipPath(clip)
            q.drawPixmap(r.topLeft(), qcovers.pixmap_for(refs[i], title, cw, ch, dpr, "stack"))      # W3.2 Q6
            if real[i]:                                     # --- W3.2 Q6: real art to .62 (the generated .9 below)
                q.fillRect(r, _alpha(style.qcolor(theme.STONE["black"]),
                                     1 - cover_grey(generated=False) / cover_grey(generated=True)))
            q.restore()
        q.end()
        grey = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied)
        grey.setDevicePixelRatio(dpr)
        q = QPainter(grey)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        q.drawImage(0, 0, img)                              # the covers' own shape back (grey has no alpha)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        # every cover greyed as a generated one is — lighter, or its dark gradient goes black (S4); a real picture was
        # darkened in the loop above, so it ends at the reference's .62 (W3.2 Q6)
        q.fillRect(QRectF(0, 0, w, h), _alpha(style.qcolor(theme.STONE["black"]), 1 - cover_grey(generated=True)))
        q.end()
        pix = QPixmap.fromImage(grey)
        pix.setDevicePixelRatio(dpr)
        self._hand, self._hand_key = (pix, room), key
        self.hands += 1
        return self._hand

    def _paint_wells(self, p):
        dpr = self.devicePixelRatioF() or 1.0
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.save()
        p.setClipRect(self.bar_rect().adjusted(-1, -1, 1, 1))
        p.translate(0, self.rise)
        radius = F["goal-bar-radius"]
        wall = F["well-wall"]
        cw, ch = F["dock-cover"]
        gap = F["well-cover-gap"]
        for name, r in self.well_rects().items():
            floor = QPainterPath()
            floor.addRoundedRect(r, radius, radius)
            p.fillPath(floor, rows.c("well-lit" if name == self.lit else "cut"))
            p.save()
            p.setClipPath(floor)
            p.fillRect(QRectF(r.left(), r.top(), r.width(), wall), rows.c("cut-wall-top"))      # the wall in shadow
            p.fillRect(QRectF(r.left(), r.bottom() - 1, r.width(), 1), rows.c("cut-wall-low"))  # the lower wall lit
            p.restore()
            mid = r.center().y()
            x = r.left() + 14
            name_w, _cut = rows.TEXT.draw(p, x, mid - 8, strings.WELLS[name], "bucket", r.width() / 2, rows.c("ink"),
                                          dpr=dpr)
            sub_w, _cut = rows.TEXT.draw(p, x, mid + 9, strings.WELL_SUBS[name], "row-sub", r.width() / 2,
                                         rows.c("ink-faint"), dpr=dpr)
            room = r.right() - 14 - (x + max(name_w, sub_w) + 12)
            slot = self._slot_w.get(name, float(F["well-slot"]))
            strip = self._strip(name, room, slot, cw, gap)
            cx = r.right() - 14 - sum(width for _kind, _t, width in strip) - gap * max(0, len(strip) - 1)
            top = mid - ch / 2
            for kind, title, width in strip:
                if kind == "slot":
                    self._paint_slot(p, QRectF(cx, top, width, ch), name, width > F["well-slot"] + 0.5)
                else:
                    cover = QRectF(cx, top, cw, ch)
                    clip = QPainterPath()
                    clip.addRoundedRect(cover, theme.RADII["cover-stack"], theme.RADII["cover-stack"])
                    p.save()
                    p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                    if name == "goal":
                        p.setOpacity(F["dock-cover-alpha"])
                    p.drawPixmap(cover.topLeft(), qcovers.pixmap_for(self._refs.get(title), title, cw, ch, dpr,
                                                                     "stack"))                      # W3.2 Q6
                    p.restore()
                cx += width + gap
        p.restore()

    def _strip(self, name, room, slot, cw, gap):
        """[(kind, title, width)] across a well: its covers either side of the slot, as many as the room holds."""
        if name == "soon":
            before, after = self._covers["soon"]
        elif name == "goal":
            before, after = self._covers["goal"], ()
        else:
            before, after = (), self._covers["finished"]
        before, after = list(before), list(after)

        def width():
            n = len(before) + len(after)
            return n * cw + slot + gap * n
        while (before or after) and width() > room:
            if len(before) >= len(after):
                before.pop(0)
            else:
                after.pop()
        return ([("cover", t, cw) for t in before] + [("slot", None, slot)] +
                [("cover", t, cw) for t in after])

    def _paint_slot(self, p, r, name, open_):
        radius = theme.RADII["cover-stack"]
        gem = theme.GEM["emerald" if name == "finished" else "sapphire"][1]
        p.save()
        if open_:
            p.setPen(QPen(style.qcolor(gem), 1))
            p.setBrush(_alpha(style.qcolor(gem), F["slot-fill-alpha"]))
        else:
            p.setPen(QPen(rows.c("line-hi"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.restore()
