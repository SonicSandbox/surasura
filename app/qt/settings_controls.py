"""The Settings page's controls (W3.3 P2; the foundation brief §7 *Controls*, §8 *Marks*; the old mock's controls,
mock-g16 :585–645): the three kinds — one or the other, on or off, adding — the level slider, and the fields.

Each is a `QWidget`: `value()`, `set_value(v)` — **no signal and no motion** (loading is never a click: it jumps) — and
`changed = pyqtSignal(object)`, emitted only on a user's change, once, with the new value. The page (P3) hands a
change on to the settings service; nothing here reads or writes a setting. Every one takes its tooltip (the shell's
bubble reads `toolTip()`) and its accessible name; the painted ones are one Tab stop (`TabFocus`: a click leaves no
ring and never scrolls the page to them), the text fields take a click too (`StrongFocus`). Sizes are the mock's
compact density × the text size (`theme.SIZES`' `settings-*`); colours, light and motion come from `app/theme.py`'s
W3.3 block. Flat (RS-1): a cut is a floor darker than its slab, its top wall dark and its lower wall lit, no side edges.

- **`Choice(options)`** — one or the other: one channel, a rib (a groove and its lip) between options, the chosen one's
  text bright and its vein (the iris at 0.75 of its light) under it. Arrows move, Space / Enter chooses.
- **`Cards(options)`** — the same one-of as choice cards (a label in bold, its line under it), the chosen one lit by
  the vein along its left edge.
- **`Toggle()`** — on or off: a hewn channel in a slate tablet, a rough gem in it, dark off, lit on. Space toggles.
- **`Tablets(options, multi=True)`** — adding: the values as tablets (lit = on; a multi-pick's lit tablet carries a
  tick, never the vein — the vein is a choice's one pick, and a one-pick's tablet keeps it: Q31); a list value's items
  each carry a ✕ (Delete), and an empty bed where the next one stands calls `on_add()`.
- **`LevelSlider(bands)`** — a well with a channel from the common blue to the rare purple, a chamber at each band, the
  band names under it, its gem. Click a chamber, drag the gem, or Left / Right / Home / End.
- **`NumberField`**, **`Range`**, **`TextField`** — the mock's field (a cut); a value commits on Enter, on leaving the
  field or on a spin step (Up / Down, the wheel while focused) — never while typing, never when it equals the last
  committed one (B3); a number is clamped, invalid text reverts (no signal); the wheel never changes an unfocused field.
- **`Select(options)`** — a long one-of: a field and a chevron that opens a menu (layer 2, as every menu in the shell).
- **`Door(label)`** — a button that opens a window or acts; **`StatusMark()`** — the emerald, always with its word (S6).

**The motions** (N7; each on `motion.clock()`, durations from `theme.SETTINGS_MOTION`; **reduced motion and the freeze
switch: each jumps to its end**):
- *the choice's vein travels* to the newly chosen option, its leading end there first and the trailing end catching up
  (the tab's travel, 260 ms; Cards' vein the same way, down or up);
- *the toggle's gem slides* from one end of its channel to the other (260 ms) while its light comes up quickly (120 ms)
  or leaves a little slower (260 ms) — never a blink;
- *the slider's gem lifts* when pressed (a spring, ω 34, ζ 0.9), *glides* after the hand while held, held back near
  each chamber, and, let go, *falls* into the nearest chamber (85 ms) and stops hard, never rising back.
The glint along the toggle and the light catching as the gem lands are 3.1's (the light comes with the stone).
"""
import math

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QActionGroup, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QWidget

from app import theme
from app.qt import freeze, motion, style
from app.qt.settings_strings import ADD, CROSS, PICKED_NONE, RANGE_TO, REMOVE_NAME, STATUS_NAME, TICK


M = theme.SETTINGS_MOTION


# --- shared helpers --------------------------------------------------------------------------------------------------- #
def _size():
    return style.current()[1]


def _f():
    return theme.text_factor(_size())


def _px(name):
    return theme.size(name, _size())


def _c(name):
    return style.qcolor(style.colours()[name])


def _font(role, weight=None, tabular=False):
    """A type role's font at the text size, in the language's families (tabular figures for numbers)."""
    _theme, size, language = style.current()
    px, w = theme.font(role, size)
    f = QFont(QApplication.font())
    f.setFamilies(list(theme.font_families(language)))
    f.setPointSizeF(px * style.PT_PER_PX)
    f.setWeight(QFont.Weight(weight or w))
    if tabular and hasattr(QFont, "Tag"):
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except (TypeError, AttributeError):
            pass
    return f


def jumps():
    """True when a control's motion jumps to its end: the freeze switch (tests, captures) or reduced motion."""
    return freeze.frozen() or motion.clock().mode.reduced


def _mix(a, b, t):
    """Two QColors, `t` of the way from a to b (a motion's in-between; its two ends are the theme's own)."""
    t = min(1.0, max(0.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def paint_cut(p, rect, radius, floor=None, lip=None):
    """A cut, flat (brief §4, rule 4): the floor (default the theme's `cut`), its top wall dark and its lower wall lit,
    each on a whole device row; no side edges."""
    rect = QRectF(rect)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(floor if isinstance(floor, QColor) else _c(floor or "cut"))
    p.drawPath(path)
    dev = p.device()
    dpr = dev.devicePixelRatioF() if dev is not None else 1.0
    edge = max(1, round(dpr)) / dpr
    top = round(rect.top() * dpr) / dpr
    bottom = round(rect.bottom() * dpr) / dpr - edge
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setClipPath(path)
    p.fillRect(QRectF(rect.left(), top, rect.width(), edge), _c("cut-wall-top"))
    p.fillRect(QRectF(rect.left(), bottom, rect.width(), edge), lip if lip is not None else _c("cut-wall-low"))
    p.restore()


def paint_vein(p, rect, vertical=False):
    """The vein: the iris across `rect` at 0.75 of its light (brief §7), rounded at its ends."""
    rect = QRectF(rect)
    if rect.width() <= 0 or rect.height() <= 0:
        return
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft() if vertical else rect.topRight())
    for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
        grad.setColorAt(pos, style.qcolor(colour))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(theme.SETTINGS_LIGHT["vein"])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    r = min(rect.width(), rect.height()) / 2
    p.drawRoundedRect(rect, r, r)
    p.restore()


def paint_ring(p, rect, radius):
    """The 2 px accent focus ring (the guidelines §3)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(_c("accent"), 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), radius, radius)
    p.restore()


def paint_tick(p, rect, colour):
    """A multi-pick's mark (Q31): the tick across `rect` in `colour` — one of several picks, never the vein a choice
    draws under its one."""
    p.save()
    p.setPen(colour)
    p.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, TICK)
    p.restore()


# A rough gem's outline (brief §8: never a circle or a pearl, never a point, a hexagon or an octagon — heavy, faceted,
# matte, a little uneven): a stone cut with straight, uneven sides, each corner a little off its place and its reach.
# (angle offset as a share of the step, reach). The toggle's has seven sides; the slider's, heavier, eight.
ROUGH = {
    "toggle": ((0.00, 0.98), (0.16, 1.05), (-0.10, 0.90), (0.12, 1.02), (0.04, 0.93), (-0.14, 1.06), (0.08, 0.95)),
    "slider": ((0.00, 0.96), (0.13, 1.05), (-0.09, 0.91), (0.15, 1.03), (0.02, 0.94), (-0.12, 1.06), (0.07, 0.97),
               (-0.06, 0.92)),
}


def gem_corners(centre, w, h, cut="toggle"):
    """The rough gem's corners around `centre`, `w` × `h`, clockwise from the top."""
    rough = ROUGH[cut]
    n = len(rough)
    pts = []
    for i, (da, reach) in enumerate(rough):
        a = (i + da) * 2 * math.pi / n - math.pi / 2
        pts.append(QPointF(centre.x() + math.cos(a) * w / 2 * reach, centre.y() + math.sin(a) * h / 2 * reach))
    return pts


def gem_path(centre, w, h, cut="toggle"):
    """The rough gem's outline: straight sides between its uneven corners."""
    pts = gem_corners(centre, w, h, cut)
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    return path


def paint_gem(p, centre, w, h, body, shade, facet, cut="toggle"):
    """A rough gem, flat and matte: its body, and two facet planes off its table (a point a little up and left of its
    centre) — the one facing the room's light (upper left) a step lighter, the one facing away (lower right) a step
    darker."""
    pts = gem_corners(centre, w, h, cut)
    n = len(pts)
    table = QPointF(centre.x() - w * 0.08, centre.y() - h * 0.10)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(body)
    p.drawPath(gem_path(centre, w, h, cut))
    toward = [(pt.x() - centre.x()) / w + (pt.y() - centre.y()) / h for pt in pts]
    for colour, i in ((shade, toward.index(max(toward))), (facet, toward.index(min(toward)))):
        plane = QPainterPath(table)
        for k in (i - 1, i, i + 1):
            plane.lineTo(pts[k % n])
        plane.closeSubpath()
        p.setBrush(colour)
        p.drawPath(plane)
    p.restore()


def spoken(label, tip):
    """An option's name in words: a tip that names it ("High leverage: …") gives its name, else the label (✦ ⚖ 📖
    say what they are, S8)."""
    if tip and ":" in tip:
        return tip.split(":", 1)[0].strip()
    return label


def _options(options):
    """(value, label[, tip]) → [(value, label, tip or None)]."""
    out = []
    for opt in options:
        value, label = opt[0], opt[1]
        out.append((value, label, opt[2] if len(opt) > 2 else None))
    return out


class _Control(QWidget):
    """What every control shares: `changed`, its tooltip and accessible name, its focus policy."""
    changed = pyqtSignal(object)

    def __init__(self, tooltip=None, name=None, parent=None, focus=Qt.FocusPolicy.TabFocus):
        super().__init__(parent)
        self.setFocusPolicy(focus)
        self._own_tip = tooltip or ""
        if tooltip:
            self.setToolTip(tooltip)
        if name:
            self.setAccessibleName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- a part's own tip (S8): the bubble shows the option under the pointer's tip, else the control's ------- #
    def _part_tip(self, pos):
        """The own tip of the part under `pos`, or None (the control's tip)."""
        return None

    def _tip_for(self, text):
        """The tooltip set to `text` (else the control's own); a bubble already showing for this control is asked
        again, so it says the new part's words."""
        want = text or self._own_tip
        if want == self.toolTip():
            return
        self.setToolTip(want)
        tips = getattr(self.window(), "tooltips", None)
        if tips is not None and getattr(tips, "_target", None) is self:
            tips.hide()
            tips.request(self)

    def mouseMoveEvent(self, event):
        if self.hasMouseTracking():
            self._tip_for(self._part_tip(event.position()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self.hasMouseTracking():
            self._tip_for(None)
        super().leaveEvent(event)

    def _ink(self, chosen):
        if not self.isEnabled():
            return _c(theme.SETTINGS_TEXT["greyed"])
        return _c(theme.SETTINGS_TEXT["chosen" if chosen else "unchosen"])

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.update()
        elif event.type() == QEvent.Type.StyleChange:
            self.restyle()
        super().changeEvent(event)

    def restyle(self):
        """A text size applied live (the page calls it, as the shell's `_apply_sizes`): sizes are read again."""
        self.updateGeometry()
        self.update()


class _Vein:
    """A vein's span (a, b) along one axis while it travels on the clock: the leading end there first (in the first
    `vein-lead` of the time), the trailing end catching up; None at rest (drawn at its option)."""

    def __init__(self, widget, repaint):
        self.widget, self.repaint = widget, repaint
        self.span = None
        self.anim = None

    def stop(self):
        anim, self.anim = self.anim, None
        if anim is not None and anim.alive:
            anim.stop()
        self.span = None

    def travel(self, start, end):
        self.stop()
        if start is None or start == end:
            return
        forward = end[0] > start[0]
        lead_share = M["vein-lead"]

        def frame(v):
            lead, trail = motion.ease(min(1.0, v / lead_share)), motion.ease(v)
            kl, kr = (trail, lead) if forward else (lead, trail)
            a = start[0] + (end[0] - start[0]) * kl
            b = start[1] + (end[1] - start[1]) * kr
            self.span = (a, max(a + 1.0, b))
            self.repaint()

        def done():
            self.span = None
            self.repaint()
        self.span = start
        self.anim = motion.clock().animate(M["vein-travel"], frame, done, kind="move", points="linear",
                                           owner=self.widget, on_end=done)


# --- one or the other ------------------------------------------------------------------------------------------------- #
class Choice(_Control):
    """One or the other: one channel (a cut), a rib between options, the chosen one's text bright and its vein under it;
    choosing, the vein travels to the new one. `options`: (value, label[, tip]). One Tab stop: Left / Right (Up / Down,
    Home / End) move, Space / Enter chooses."""

    def __init__(self, options, value=None, tooltip=None, name=None, parent=None):
        super().__init__(tooltip, name, parent)
        self._options = _options(options)
        self._index = self._find(value) if value is not None else 0
        self._cursor = self._index
        self._pressed = None
        self._vein = _Vein(self, self._repaint_vein)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(any(t for _v, _l, t in self._options))     # an option's own tip under the pointer
        self._describe()

    # --- value ---------------------------------------------------------------------------------------------- #
    def _find(self, value):
        for i, (v, _l, _t) in enumerate(self._options):
            if v == value:
                return i
        raise ValueError(f"not an option: {value!r}")

    def value(self):
        return self._options[self._index][0]

    def values(self):
        return [v for v, _l, _t in self._options]

    def set_value(self, value):
        """Show `value` as chosen — no signal, no motion."""
        self._vein.stop()
        self._index = self._cursor = self._find(value)
        self._describe()
        self.update()

    def vein(self):
        """The vein's (left, right) as drawn now."""
        return self._vein.span or self._rest(self._index)

    def _describe(self):
        _v, label, tip = self._options[self._index]
        self.setAccessibleDescription(spoken(label, tip))

    def _part_tip(self, pos):
        i = self._at(pos)
        return self._options[i][2] if i is not None else None

    def _choose(self, i):
        if i == self._index or not self.isEnabled():
            return
        start = self.vein()
        self._index = self._cursor = i
        self._describe()
        self._vein.travel(start, self._rest(i))
        self.update()
        self.changed.emit(self.value())

    # --- geometry ------------------------------------------------------------------------------------------- #
    def _pads(self):
        return _px("settings-seg-pad-y"), _px("settings-seg-pad-x")

    def _rects(self):
        pad_y, pad_x = self._pads()
        fm = QFontMetricsF(_font("segmented"))
        h = fm.height() + 2 * pad_y
        x, out = 0.0, []
        for _v, label, _t in self._options:
            w = math.ceil(fm.horizontalAdvance(label) + 2 * pad_x)
            out.append(QRectF(x, 0, w, h))
            x += w
        return out

    def _rest(self, i):
        r = self._rects()[i]
        inset = self._pads()[1] * 0.6
        return (r.left() + inset, r.right() - inset)

    def _vein_rect(self, span):
        h = max(2.0, round(2 * _f()))
        bottom = self.height() - 2
        return QRectF(span[0], bottom - h, span[1] - span[0], h)

    def _repaint_vein(self):
        h = max(2.0, round(2 * _f()))
        self.update(QRect(0, int(self.height() - h - 4), self.width(), int(h + 4)))

    def sizeHint(self):
        rects = self._rects()
        return QSize(math.ceil(rects[-1].right()), math.ceil(rects[-1].height()))

    def minimumSizeHint(self):
        return self.sizeHint()

    def _at(self, pos):
        for i, r in enumerate(self._rects()):
            if r.contains(QPointF(pos)):
                return i
        return None

    # --- input ---------------------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._at(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self._pressed = self._pressed, None
        if event.button() == Qt.MouseButton.LeftButton and pressed is not None and self._at(event.position()) == pressed:
            self._choose(pressed)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        k, n = event.key(), len(self._options)
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._cursor = max(0, self._cursor - 1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._cursor = min(n - 1, self._cursor + 1)
        elif k == Qt.Key.Key_Home:
            self._cursor = 0
        elif k == Qt.Key.Key_End:
            self._cursor = n - 1
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._choose(self._cursor)
        else:
            super().keyPressEvent(event)
            return
        self.update()
        event.accept()

    def focusInEvent(self, event):
        self._cursor = self._index
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    # --- paint ---------------------------------------------------------------------------------------------- #
    def paintEvent(self, _event):
        p = QPainter(self)
        rects = self._rects()
        radius = theme.RADII["r-sm"]
        paint_cut(p, QRectF(0, 0, rects[-1].right(), rects[-1].height()), radius)
        dpr = self.devicePixelRatioF()
        edge = max(1, round(dpr)) / dpr
        for r in rects[1:]:                              # the rib: a groove, then its lit lip
            x = round(r.left() * dpr) / dpr
            inset = r.height() * 0.22
            p.fillRect(QRectF(x - edge, r.top() + inset, edge, r.height() - 2 * inset), _c("groove"))
            p.fillRect(QRectF(x, r.top() + inset, edge, r.height() - 2 * inset), _c("groove-lip"))
        p.setFont(_font("segmented"))
        for i, ((_v, label, _t), r) in enumerate(zip(self._options, rects)):
            p.setPen(self._ink(i == self._index))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        if self.isEnabled():
            paint_vein(p, self._vein_rect(self.vein()))
        if self.hasFocus():
            paint_ring(p, rects[self._cursor], radius)
        p.end()


class Cards(Choice):
    """The same one-of drawn as choice cards (the mock's `.choice`): each a cut with its label in bold and its line
    under it; the chosen card lit by the vein along its left edge, which travels to the newly chosen one. `options`:
    (value, label, line[, tip]). Up / Down move, Space / Enter chooses."""

    def __init__(self, options, value=None, tooltip=None, name=None, parent=None):
        self._lines = [opt[2] if len(opt) > 2 else "" for opt in options]
        super().__init__([(o[0], o[1], o[3] if len(o) > 3 else None) for o in options], value, tooltip, name, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _rects(self):
        pad_y, pad_x = _px("settings-card-pad-y"), _px("settings-card-pad-x")
        bold, small = QFontMetricsF(_font("body", 600)), QFontMetricsF(_font("row-sub"))
        h = math.ceil(bold.height() + small.height() + 2 * pad_y)
        widest = max([bold.horizontalAdvance(l) for _v, l, _t in self._options]
                     + [small.horizontalAdvance(line) for line in self._lines])
        w = max(self.width(), 0) or math.ceil(widest + 3 * pad_x)
        gap = _px("settings-card-gap")
        return [QRectF(0, i * (h + gap), w, h) for i in range(len(self._options))]

    def _rest(self, i):
        r = self._rects()[i]
        inset = r.height() * 0.2
        return (r.top() + inset, r.bottom() - inset)

    def _vein_rect(self, span):
        w = max(2.0, round(3 * _f()))
        return QRectF(2, span[0], w, span[1] - span[0])

    def _repaint_vein(self):
        self.update(QRect(0, 0, int(max(2.0, round(3 * _f())) + 4), self.height()))

    def sizeHint(self):
        pad_x = _px("settings-card-pad-x")
        bold, small = QFontMetricsF(_font("body", 600)), QFontMetricsF(_font("row-sub"))
        widest = max([bold.horizontalAdvance(l) for _v, l, _t in self._options]
                     + [small.horizontalAdvance(line) for line in self._lines])
        rects = self._rects()
        w = min(math.ceil(widest + 3 * pad_x), math.ceil(_px("settings-card-w")))
        return QSize(w, math.ceil(rects[-1].bottom()))

    def paintEvent(self, _event):
        p = QPainter(self)
        radius = theme.RADII["button"]
        pad_y, pad_x = _px("settings-card-pad-y"), _px("settings-card-pad-x")
        bold_font, small_font = _font("body", 600), _font("row-sub")
        bold = QFontMetricsF(bold_font)
        for i, ((_v, label, _t), r) in enumerate(zip(self._options, self._rects())):
            chosen = i == self._index
            paint_cut(p, r, radius)
            text = r.adjusted(pad_x * 1.5, pad_y, -pad_x, -pad_y)
            p.setFont(bold_font)
            p.setPen(self._ink(chosen))
            p.drawText(QRectF(text.left(), text.top(), text.width(), bold.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.setFont(small_font)
            if not self.isEnabled():
                p.setPen(_c(theme.SETTINGS_TEXT["greyed"]))
            else:
                p.setPen(_c(theme.SETTINGS_TEXT["chosen-line" if chosen else "help"]))
            p.drawText(QRectF(text.left(), text.top() + bold.height(), text.width(), text.height() - bold.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self._lines[i])
            if self.hasFocus() and i == self._cursor:
                paint_ring(p, r, radius)
        if self.isEnabled():
            paint_vein(p, self._vein_rect(self.vein()), vertical=True)
        p.end()


# --- on or off -------------------------------------------------------------------------------------------------------- #
class Toggle(_Control):
    """On or off: a slate tablet with a hewn channel, a rough gem in it — off at the left and dark, on at the right and
    lit by the sapphire's light. The gem slides; its light comes up quickly and leaves a little slower. Space (or Enter)
    toggles."""

    def __init__(self, value=False, tooltip=None, name=None, parent=None):
        super().__init__(tooltip, name, parent)
        self._on = bool(value)
        self._k = self._light = 1.0 if self._on else 0.0
        self._slide = self._glow = None
        self._pressed = False
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def value(self):
        return self._on

    def set_value(self, value):
        """Show on or off — no signal, no motion."""
        self._stop()
        self._on = bool(value)
        self._k = self._light = 1.0 if self._on else 0.0
        self.update()

    def position(self):
        """(where the gem is: 0 off … 1 on, its light 0 … 1) as drawn now."""
        return self._k, self._light

    def _stop(self):
        for anim in (self._slide, self._glow):
            if anim is not None and anim.alive:
                anim.stop()
        self._slide = self._glow = None

    def _toggle(self):
        if not self.isEnabled():
            return
        self._stop()
        self._on = not self._on
        to = 1.0 if self._on else 0.0
        k0, l0 = self._k, self._light

        def slide(v):
            self._k = k0 + (to - k0) * v
            self.update()

        def light(v):
            self._light = l0 + (to - l0) * v
            self.update()

        def settle_k():
            self._k = to
            self.update()

        def settle_light():
            self._light = to
            self.update()
        clock = motion.clock()
        self._slide = clock.animate(M["toggle-slide"], slide, settle_k, kind="move", owner=self, on_end=settle_k)
        rate = M["toggle-light-up"] if self._on else M["toggle-light-down"]
        self._glow = clock.animate(rate, light, settle_light, kind="move", points="linear", owner=self,
                                   on_end=settle_light)
        self.changed.emit(self._on)

    def sizeHint(self):
        return QSize(round(_px("settings-toggle-w")), round(_px("settings-toggle-h")))

    def minimumSizeHint(self):
        return self.sizeHint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self._pressed = self._pressed, False
        if event.button() == Qt.MouseButton.LeftButton and pressed and self.rect().contains(event.position().toPoint()):
            self._toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        radius = theme.RADII["button-sm"] * 0.8
        p.setPen(Qt.PenStyle.NoPen)                     # the tablet: slate, nearer than the slab
        p.setBrush(_c("settings-tablet"))
        p.drawRoundedRect(r, radius, radius)
        channel = r.adjusted(3, 3, -3, -3)            # hewn: a dark floor, its top wall in shadow, its lower lip lit
        light = self._light if self.isEnabled() else 0.0
        paint_cut(p, channel, radius * 0.6, _mix(_c("cut"), _c("toggle-lit"), light), lip=_c("toggle-lip"))
        side = channel.height() - 1
        travel = channel.width() - side * 1.15 - 2
        centre = QPointF(channel.left() + 1 + side * 0.575 + travel * self._k, channel.center().y())
        paint_gem(p, centre, side * 1.15, side,
                  _mix(_c("toggle-gem-off"), _c("gem-sapphire"), light),
                  _mix(_c("toggle-gem-off-shade"), _c("gem-sapphire-shade"), light),
                  _mix(_c("toggle-gem-off-facet"), _c("gem-sapphire-facet"), light))
        if self.hasFocus():
            paint_ring(p, r, radius)
        p.end()


# --- adding ----------------------------------------------------------------------------------------------------------- #
class Tablets(_Control):
    """Adding: values as tablets. With `options` ((value, label[, tip])), each a tablet lit when picked, dim when not —
    any number picked (`multi`: a tick before its label, in a slot every option keeps so nothing moves; never the vein,
    which reads as a choice's one pick — Q31), or exactly one (its vein at its foot). Without `options`, a list value:
    each item a lit tablet with a small ✕ (Delete removes it from the keyboard), then an empty bed where the next one
    stands, which calls `on_add()` (the page opens its folder picker or text entry there, then calls `add_item`). One
    Tab stop: Left / Right move, Space / Enter picks or adds, Delete removes."""

    def __init__(self, options=None, multi=True, value=None, on_add=None, add_label=None, tooltip=None, name=None,
                 parent=None):
        super().__init__(tooltip, name, parent)
        self._options = _options(options) if options is not None else None
        self.multi = bool(multi)
        self.on_add = on_add
        self.add_label = add_label or ADD
        self._items = []
        self._picked = set()
        self._cursor = 0
        self._pressed = None
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(any(t for _v, _l, t in self._options or ()))   # a tablet's own tip under the pointer
        if value is not None:
            self._load(value)
        elif self._options is not None and not self.multi:
            self._picked = {self._options[0][0]}
        self._describe()

    def _describe(self):
        """The accessible description: the tablets picked (by name: ✦ is *High leverage*), or the list's items."""
        if self.is_list:
            names = list(self._items)
        else:
            names = [spoken(label, tip) for v, label, tip in self._options if v in self._picked]
        self.setAccessibleDescription(", ".join(names) if names else PICKED_NONE)

    def _part_tip(self, pos):
        _i, part, _cross = self._at(pos)
        if part is None or part[0] != "option":
            return None
        return next((t for v, _l, t in self._options if v == part[1]), None)

    @property
    def is_list(self):
        return self._options is None

    # --- value ---------------------------------------------------------------------------------------------- #
    def _load(self, value):
        if self.is_list:
            self._items = [str(v) for v in (value or [])]
        elif self.multi:
            known = {v for v, _l, _t in self._options}
            self._picked = {v for v in (value or []) if v in known}
        else:
            if value not in {v for v, _l, _t in self._options}:
                raise ValueError(f"not an option: {value!r}")
            self._picked = {value}

    def value(self):
        if self.is_list:
            return list(self._items)
        picked = [v for v, _l, _t in self._options if v in self._picked]
        return picked if self.multi else picked[0]

    def set_value(self, value):
        """Show `value` (a list of picked values, one value, or a list's items) — no signal."""
        self._load(value)
        self._describe()
        self._cursor = min(self._cursor, max(0, len(self._parts()) - 1))
        self.updateGeometry()
        self.update()

    def add_item(self, item):
        """A list's new item (the page's picker answered): added at the end and emitted, unless it is there already."""
        item = str(item)
        if not self.is_list or not item or item in self._items:
            return False
        self._items.append(item)
        self._describe()
        self.updateGeometry()
        self.update()
        self.changed.emit(self.value())
        return True

    def remove_item(self, item):
        if not self.is_list or item not in self._items:
            return False
        self._items.remove(item)
        self._describe()
        self._cursor = min(self._cursor, max(0, len(self._parts()) - 1))
        self.updateGeometry()
        self.update()
        self.changed.emit(self.value())
        return True

    def _pick(self, value):
        if not self.isEnabled():
            return
        if self.multi:
            self._picked ^= {value}
        elif value in self._picked:
            return
        else:
            self._picked = {value}
        self._describe()
        self.update()
        self.changed.emit(self.value())

    def _activate(self, part):
        kind, key = part[0], part[1]
        if kind == "bed":
            if self.on_add is not None and self.isEnabled():
                self.on_add()
        elif kind == "option":
            self._pick(key)

    # --- geometry ------------------------------------------------------------------------------------------- #
    def _entries(self):
        """(kind, key, label): the options, or the list's items then the bed."""
        if not self.is_list:
            return [("option", v, l) for v, l, _t in self._options]
        return [("item", it, it) for it in self._items] + [("bed", None, self.add_label)]

    def _tick_w(self, fm, pad):
        """A multi-pick option's tick slot (its tick and the space after it); 0 for a one-pick or a list."""
        return fm.horizontalAdvance(TICK) + pad * 0.4 if self.multi and not self.is_list else 0.0

    def _layout(self, width):
        """[(kind, key, label, rect, cross rect or None)] flowed into `width` (one line when it fits)."""
        fm = QFontMetricsF(_font("chip", 400))
        h = _px("settings-pill-h")
        pad = _px("settings-pill-pad-x")
        gap = round(6 * _f())
        cross_w = fm.horizontalAdvance(CROSS) + pad * 0.6
        tick_w = self._tick_w(fm, pad)
        x = y = 0.0
        out = []
        for kind, key, label in self._entries():
            w = math.ceil(fm.horizontalAdvance(label) + 2 * pad + (cross_w if kind == "item" else 0) +
                          (tick_w if kind == "option" else 0))
            if x > 0 and width > 0 and x + w > width:
                x, y = 0.0, y + h + gap
            r = QRectF(x, y, w, h)
            cross = QRectF(r.right() - cross_w - pad * 0.4, r.top(), cross_w, h) if kind == "item" else None
            out.append((kind, key, label, r, cross))
            x += w + gap
        return out

    def _parts(self):
        return self._layout(self.width())

    def sizeHint(self):
        parts = self._layout(0)
        if not parts:
            return QSize(0, round(_px("settings-pill-h")))
        return QSize(math.ceil(parts[-1][3].right()), math.ceil(parts[-1][3].bottom()))

    def minimumSizeHint(self):
        parts = self._layout(0)
        w = max((math.ceil(p[3].width()) for p in parts), default=0)
        return QSize(w, round(_px("settings-pill-h")))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        parts = self._layout(width)
        return math.ceil(parts[-1][3].bottom()) if parts else round(_px("settings-pill-h"))

    def _at(self, pos):
        pos = QPointF(pos)
        for i, part in enumerate(self._parts()):
            if part[3].contains(pos):
                return i, part, part[4] is not None and part[4].contains(pos)
        return None, None, False

    # --- input ---------------------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            i, _part, on_cross = self._at(event.position())
            self._pressed = (i, on_cross)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self._pressed = self._pressed, None
        if event.button() != Qt.MouseButton.LeftButton or pressed is None:
            super().mouseReleaseEvent(event)
            return
        i, part, on_cross = self._at(event.position())
        if i is not None and (i, on_cross) == pressed:
            self._cursor = i
            if part[0] == "item":
                if on_cross and self.isEnabled():
                    self.remove_item(part[1])
            else:
                self._activate(part)
        event.accept()

    def keyPressEvent(self, event):
        parts = self._parts()
        k = event.key()
        if not parts:
            super().keyPressEvent(event)
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._cursor = max(0, self._cursor - 1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._cursor = min(len(parts) - 1, self._cursor + 1)
        elif k == Qt.Key.Key_Home:
            self._cursor = 0
        elif k == Qt.Key.Key_End:
            self._cursor = len(parts) - 1
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate(parts[min(self._cursor, len(parts) - 1)])
        elif k == Qt.Key.Key_Delete and self.is_list:           # Delete alone: Backspace never removes (N2)
            part = parts[min(self._cursor, len(parts) - 1)]
            if part[0] == "item" and self.isEnabled():
                self.remove_item(part[1])
        else:
            super().keyPressEvent(event)
            return
        self.update()
        event.accept()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    # --- paint ---------------------------------------------------------------------------------------------- #
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = _font("chip", 400)
        p.setFont(font)
        radius = theme.RADII["button-sm"]
        pad = _px("settings-pill-pad-x")
        enabled = self.isEnabled()
        fm = QFontMetricsF(font)
        tick_w = self._tick_w(fm, pad)
        for i, (kind, key, label, r, cross) in enumerate(self._parts()):
            lit = kind == "item" or (kind == "option" and key in self._picked)
            if kind == "bed":
                paint_cut(p, r, radius)
                p.setPen(self._ink(False))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_c("settings-tablet-on" if lit and enabled else "settings-tablet"))
                p.drawRoundedRect(r, radius, radius)
                tick = tick_w if kind == "option" else 0.0
                text = QRectF(r.left() + pad + tick, r.top(),
                              r.width() - 2 * pad - tick - (cross.width() if cross else 0), r.height())
                p.setPen(self._ink(lit))
                p.drawText(text, Qt.AlignmentFlag.AlignCenter, label)
                if tick and lit:                        # Q31: a multi-pick's lit tablet, ticked
                    paint_tick(p, QRectF(r.left() + pad, r.top(), fm.horizontalAdvance(TICK), r.height()),
                               self._ink(True))
                if cross is not None:
                    p.setPen(_c(theme.SETTINGS_TEXT["chosen-line" if enabled else "greyed"]))
                    p.drawText(cross, Qt.AlignmentFlag.AlignCenter, CROSS)
                if lit and enabled and kind == "option" and not self.multi:        # a one-pick's vein alone
                    vh = max(2.0, round(2 * _f()))
                    paint_vein(p, QRectF(r.left() + pad * 0.6, r.bottom() - vh - 1, r.width() - pad * 1.2, vh))
            if self.hasFocus() and i == self._cursor:
                paint_ring(p, r, radius)
        p.end()

    def remove_name(self, item):
        """The words a screen reader gives a list item's ✕."""
        return REMOVE_NAME.format(item=item)


# --- the level -------------------------------------------------------------------------------------------------------- #
def _spring(t, omega, zeta):
    """A spring's reach from 0 toward 1 after `t` s (ζ < 1: a touch under-damped, settled in about 4 / ζω)."""
    if t <= 0:
        return 0.0
    wd = omega * math.sqrt(1 - zeta * zeta)
    return 1.0 - math.exp(-zeta * omega * t) * (math.cos(wd * t) + zeta / math.sqrt(1 - zeta * zeta) * math.sin(wd * t))


class LevelSlider(_Control):
    """The level: a well (a cut) with a channel from the common blue to the rare purple, a chamber at each band, the band
    names under it (the chosen one bright) and its gem. Pressed, the gem lifts; held, it glides after the hand, held back
    near each chamber; let go, it falls into the nearest chamber and stops hard. Click a chamber to choose it; Left /
    Right / Home / End. `bands`: (key, name). `value()` is the chosen band's key. `one_name` (the level ▾'s pop, W3.1b):
    only the chosen band's name, under its chamber."""

    def __init__(self, bands, value=None, tooltip=None, name=None, parent=None, one_name=False):
        super().__init__(tooltip, name, parent)
        self._bands = [(b[0], b[1]) for b in bands]
        self._one = bool(one_name)
        self._named = True                         # one name: shown (`set_named`)
        self._index = self._find(value) if value is not None else 0
        self._t = self._at_t(self._index)          # the gem's place along the channel, 0 … 1
        self._lift = 0.0                           # 0 seated … 1 lifted
        self._held = False
        self._hand = self._t
        self._anims = {}
        self._last = None
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._describe()

    # --- value ---------------------------------------------------------------------------------------------- #
    def _find(self, value):
        for i, (k, _n) in enumerate(self._bands):
            if k == value:
                return i
        raise ValueError(f"not a band: {value!r}")

    def value(self):
        return self._bands[self._index][0]

    def set_value(self, value):
        """Seat the gem in `value`'s chamber — no signal, no motion."""
        self._stop()
        self._index = self._find(value)
        self._t, self._lift, self._held = self._at_t(self._index), 0.0, False
        self._describe()
        self.update()

    def busy(self):
        """The hand holds the gem, or it is still gliding or falling into a chamber: a shown value waits (W3.1b)."""
        return self._held or any(anim is not None and anim.alive for anim in self._anims.values())

    def set_named(self, named):
        """`one_name`: show the chosen band's name, or none (a band not read yet)."""
        if bool(named) != self._named:
            self._named = bool(named)
            self.update()

    def gem(self):
        """(the gem's place along the channel 0 … 1, its lift 0 … 1) as drawn now."""
        return self._t, self._lift

    def chamber(self, i):
        """Band `i`'s chamber's centre, in the widget's coordinates."""
        left, width, cy = self._channel()
        return QPointF(left + self._at_t(i) * width, cy)

    def _describe(self):
        self.setAccessibleDescription(self._bands[self._index][1])

    def _at_t(self, i):
        return i / (len(self._bands) - 1) if len(self._bands) > 1 else 0.0

    def _nearest(self, t):
        n = len(self._bands) - 1
        return max(0, min(n, round(t * n))) if n > 0 else 0

    def _stop(self, *names):
        for name in names or list(self._anims):
            anim = self._anims.pop(name, None)
            if anim is not None and anim.alive:
                anim.stop()

    # --- geometry ------------------------------------------------------------------------------------------- #
    def _gem_size(self):
        return _px("settings-gem")

    def _well_h(self):
        return _px("settings-slider-well")

    def _channel(self):
        """(left, width, centre y) of the channel."""
        margin = self._gem_size() * 0.75 + 4
        return margin, max(1.0, self.width() - 2 * margin), self._well_h() / 2

    def _t_of(self, x):
        left, width, _cy = self._channel()
        return min(1.0, max(0.0, (x - left) / width))

    def _names_w(self, step):
        """The width at which no two band names `step` chambers apart meet (1: on one line; 2: every other name on
        a second line)."""
        fm = QFontMetricsF(_font("row-sub"))
        widths = [fm.horizontalAdvance(n) for _k, n in self._bands]
        gap = 12 * _f()
        pairs = list(zip(widths, widths[step:]))
        spacing = max(((a + b) / 2 + gap) / step for a, b in pairs) if pairs else 0
        margin = self._gem_size() * 0.75 + 4
        return (len(widths) - 1) * spacing + 2 * margin + (widths[0] + widths[-1]) / 2

    def staggered(self, width=None):
        """Whether the band names stand on two lines (every other one lower): the slider narrower than one line of
        them needs, so no two names ever touch (FX-page B4)."""
        if self._one:
            return False                             # one name: never two lines
        width = self.width() if width is None else width
        return width + 0.5 < self._names_w(1)

    def _height(self, lines):
        fm = QFontMetricsF(_font("row-sub"))
        return math.ceil(self._well_h() + 4 * _f() + lines * fm.height())

    def sizeHint(self):
        """Wide enough that no two band names meet on one line: the chambers spaced by the widest neighbouring
        pair."""
        if self._one:
            return QSize(math.ceil(_px("settings-slider-w")), self._height(1))
        return QSize(math.ceil(max(_px("settings-slider-w"), self._names_w(1))), self._height(1))

    def minimumSizeHint(self):
        """Narrower, every other name goes a line lower: still no two names meet."""
        if self._one:
            fm = QFontMetricsF(_font("row-sub"))
            return QSize(math.ceil(max(fm.horizontalAdvance(n) for _k, n in self._bands) * 2), self._height(1))
        return QSize(math.ceil(self._names_w(2)), self._height(2))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._height(2 if self.staggered(width) else 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.staggered(event.oldSize().width()) != self.staggered(event.size().width()):
            self.updateGeometry()                    # a line of names more or less: the row's height again

    # --- the gem's motions --------------------------------------------------------------------------------- #
    def _press(self, x):
        self._stop()
        self._held = True
        self._hand = self._t_of(x)
        l0 = self._lift

        def lift(v):
            self._lift = l0 + (1.0 - l0) * (1.0 if v >= 1.0 else _spring(v * M["slider-lift"] / 1000.0,
                                                                         M["slider-lift-omega"],
                                                                         M["slider-lift-zeta"]))
            self.update()
        self._anims["lift"] = motion.clock().animate(M["slider-lift"], lift, kind="move", points="linear", owner=self)
        self._last = motion.clock().now()
        follow = motion.clock().animate(M["vein-travel"], self._follow, kind="loop", repeat=True, owner=self,
                                        on_end=self._followed)
        if follow.alive:
            self._anims["follow"] = follow
        else:
            self._t = self._goal()                   # frozen or reduced: no glide, the gem is where the hand is
        self.update()

    def _goal(self):
        """Where the held gem is pulled: the hand, held back near each chamber."""
        k = self._nearest(self._hand)
        _left, width, _cy = self._channel()
        d = self._hand - self._at_t(k)
        if abs(d) * width < M["slider-hold-px"] * _f():
            return self._at_t(k) + d * M["slider-hold"]
        return self._hand

    def _follow(self, _phase):
        now = motion.clock().now()
        dt = max(0.0, (now - (self._last if self._last is not None else now)) / 1000.0)
        self._last = now
        if self._held:
            self._t += (self._goal() - self._t) * min(1.0, dt * M["slider-follow"])
            self.update()

    def _followed(self):
        """The follow loop stopped while the gem is held (Reduced motion turned on mid-drag): at the hand now."""
        if self._held:
            self._t = self._goal()
            self.update()

    def _move(self, x):
        self._hand = self._t_of(x)
        if "follow" not in self._anims or not self._anims["follow"].alive:
            self._t = self._goal()
            self.update()

    def _release(self):
        self._held = False
        self._stop("follow", "lift")
        self._settle(self._nearest(self._hand))

    def _settle(self, target):
        """The band is chosen at the release (Gap 2: the choice and its save at the action, never after the motion);
        then the gem glides over its chamber (if it isn't there) and falls in — 85 ms, falling faster as it goes,
        never rising back — and stops hard: a look only."""
        was, self._index = self._index, target
        self._describe()
        t0, l0, tt = self._t, self._lift, self._at_t(target)
        glide = M["slider-glide"] if abs(tt - t0) * self._channel()[1] > 0.5 else 0
        fall = M["slider-fall"] if l0 > 0 else 0
        total = glide + fall

        def frame(v):
            ms = v * total
            if ms < glide:
                self._t = t0 + (tt - t0) * motion.ease(ms / glide)
                self._lift = l0
            else:
                self._t = tt
                f = min(1.0, (ms - glide) / fall) if fall else 1.0
                self._lift = l0 * (1.0 - f * f)
            self.update()

        def seated():
            self._anims.pop("settle", None)
            self._t, self._lift = tt, 0.0
            self.update()
        if total <= 0:
            seated()
        else:
            self._anims["settle"] = motion.clock().animate(total, frame, seated, kind="move", points="linear",
                                                           owner=self, on_end=seated)
        self.update()                                # the chosen name lit now
        if target != was:                            # (after the settle starts: a shown value waits for it, `busy`)
            self.changed.emit(self.value())

    def _key_to(self, i):
        i = max(0, min(len(self._bands) - 1, i))
        if i == self._index or not self.isEnabled():
            return
        self._stop()
        t0, tt = self._t, self._at_t(i)
        self._index = i
        self._lift = 0.0
        self._describe()

        def glide(v):
            self._t = t0 + (tt - t0) * v
            self.update()

        def end():
            self._t = tt
            self.update()
        self._anims["glide"] = motion.clock().animate(M["slider-glide"], glide, end, kind="move", owner=self,
                                                      on_end=end)
        self.update()
        self.changed.emit(self.value())

    # --- input ---------------------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._press(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._held:
            self._move(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._held:
            self._move(event.position().x())
            self._release()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._key_to(self._index - 1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._key_to(self._index + 1)
        elif k == Qt.Key.Key_Home:
            self._key_to(0)
        elif k == Qt.Key.Key_End:
            self._key_to(len(self._bands) - 1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._held:                               # the hand is gone with the page: seat it where it is nearest
            self._held = False
        self._stop()
        self._t, self._lift = self._at_t(self._index), 0.0

    # --- paint ---------------------------------------------------------------------------------------------- #
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        well = QRectF(0, 0, self.width(), self._well_h())
        radius = theme.RADII["r-sm"]
        paint_cut(p, well, radius)
        left, width, cy = self._channel()
        gem = self._gem_size()
        x = left + self._t * width
        enabled = self.isEnabled()
        if enabled:                                  # at rest the gem glows faintly onto the well (flat)
            p.save()
            p.setOpacity(1.0 - self._lift)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("slider-glow"))
            p.drawEllipse(QPointF(x, cy), gem * 1.3, (self._well_h() - 6) / 2)
            p.restore()
        ch = max(3.0, round(4 * _f()))               # the channel: the iris's blue to its purple
        grad = QLinearGradient(QPointF(left, 0), QPointF(left + width, 0))
        iris = theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME])
        start = iris[1][0]
        for pos, colour in iris[1:]:
            grad.setColorAt((pos - start) / (1.0 - start), style.qcolor(colour))
        p.save()
        p.setOpacity(theme.SETTINGS_LIGHT["channel"] if enabled else theme.SETTINGS_LIGHT["channel"] / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(left, cy - ch / 2, width, ch), ch / 2, ch / 2)
        p.restore()
        cw, chh = max(4.0, round(6 * _f())), max(6.0, round(9 * _f()))
        for i in range(len(self._bands)):            # a chamber at each band: a hole cut in the channel, its lip lit
            cx = left + self._at_t(i) * width
            hole = QRectF(cx - cw / 2, cy - chh / 2, cw, chh)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("slider-chamber"))
            p.drawRoundedRect(hole, cw / 3, cw / 3)
            p.setBrush(_c("cut-wall-low"))
            p.drawRect(QRectF(hole.left() + 1, hole.bottom() - 1, cw - 2, 1))
        if enabled:
            lift = self._lift
            scale = 0.95 + 0.15 * lift
            centre = QPointF(x, cy + 1 - 4 * _f() * lift)
            paint_gem(p, centre, gem * 1.2 * scale, gem * 1.05 * scale,
                      _mix(_c("gem-sapphire"), _c("slider-gem-lifted"), lift), _c("gem-sapphire-shade"),
                      _c("gem-sapphire-facet"), cut="slider")
        fm_font = _font("row-sub")
        p.setFont(fm_font)
        fm = QFontMetricsF(fm_font)
        top = self._well_h() + 4 * _f()
        two = self.staggered()
        for i, (_k, name) in enumerate(self._bands):
            if self._one and (i != self._index or not self._named):
                continue
            cx = left + self._at_t(i) * width
            w = fm.horizontalAdvance(name)
            nx = min(max(0.0, cx - w / 2), self.width() - w)
            p.setPen(self._ink(i == self._index))
            y = top + (fm.height() if two and i % 2 else 0)
            p.drawText(QRectF(nx, y, w + 1, fm.height()), Qt.AlignmentFlag.AlignLeft, name)
        if self.hasFocus():
            paint_ring(p, well, radius)
        p.end()


# --- the fields ------------------------------------------------------------------------------------------------------- #
class _Field(QWidget):
    """A field (the mock's `.num` / input): a cut with a line edit in it; commits on Enter, on focus leaving and on a
    spin step — never while typing, never for the value it already holds (B3)."""
    changed = pyqtSignal(object)

    def __init__(self, tooltip=None, name=None, parent=None, prefix=None, suffix=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(round(6 * _f()))
        self.edit = QLineEdit(self)
        self.edit.setObjectName("settingsfield")
        self.edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.edit.installEventFilter(self)
        self.setFocusProxy(self.edit)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.prefix = self.suffix = None
        if prefix:
            self.prefix = QLabel(self)
            self.prefix.setObjectName("settingsaffix")
            self.prefix.setText(prefix)
            row.addWidget(self.prefix)
        row.addWidget(self.edit)
        if suffix:
            self.suffix = QLabel(self)
            self.suffix.setObjectName("settingsaffix")
            self.suffix.setText(suffix)
            row.addWidget(self.suffix)
        row.addStretch(0)
        for w in (self, self.edit):
            if tooltip:
                w.setToolTip(tooltip)
            if name:
                w.setAccessibleName(name)

    def eventFilter(self, obj, event):
        if obj is not self.edit:
            return False
        et = event.type()
        if et == QEvent.Type.KeyPress:
            k = event.key()
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._commit()
                return True
            if k in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._steps():
                self._step(1 if k == Qt.Key.Key_Up else -1)
                return True
            if k == Qt.Key.Key_Escape:
                self._revert()                       # typed text dropped; Esc goes on (the router)
                return False
        elif et == QEvent.Type.FocusOut:
            self._commit()
        elif et == QEvent.Type.Wheel:
            if not self.edit.hasFocus() or not self._steps():
                event.ignore()                       # never changes an unfocused field: the page scrolls
                return False
            dy = event.angleDelta().y()
            if dy:
                self._step(1 if dy > 0 else -1)
            event.accept()
            return True
        return False

    def wheelEvent(self, event):
        event.ignore()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange and getattr(self, "edit", None) is not None:
            self.restyle()                          # a text size applied live: the field's size and font again
        super().changeEvent(event)

    def restyle(self):
        """A text size applied live (the page calls it): the field's size and font read again."""

    def _steps(self):
        return False


class NumberField(_Field):
    """A number: right-aligned tabular figures in the mock's field, clamped to `minimum` … `maximum`; `decimals` 0 for
    a whole number. `prefix` / `suffix`: words beside it (from the strings table)."""

    def __init__(self, minimum, maximum, value=None, suffix=None, prefix=None, step=1, decimals=0, tooltip=None,
                 name=None, parent=None):
        super().__init__(tooltip, name, parent, prefix, suffix)
        self.minimum, self.maximum, self.step, self.decimals = minimum, maximum, step, decimals
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.restyle()
        self._value = self._clamp(minimum if value is None else value)
        self._show()

    def restyle(self):
        self.edit.setFont(_font("number-field", tabular=True))
        self.edit.setFixedWidth(round(_px("settings-num-w")))

    def _clamp(self, n):
        if isinstance(n, str):                       # a number hand-written as text ("500"): shown as it is held
            n = float(n.strip().replace(",", ""))    # (ValueError when it isn't one: the page shows the default)
            if not math.isfinite(n):
                raise ValueError(f"not a number: {n!r}")
        n = min(self.maximum, max(self.minimum, n))
        return round(n, self.decimals) if self.decimals else int(round(n))

    def _text(self, n):
        return f"{n:.{self.decimals}f}" if self.decimals else str(n)

    def _show(self):
        self.edit.setText(self._text(self._value))

    def _parse(self):
        text = self.edit.text().strip().replace(",", "")
        try:
            n = float(text)
        except ValueError:
            return None
        return n if math.isfinite(n) else None

    def value(self):
        return self._value

    def set_value(self, value):
        """Show `value` (clamped) — no signal."""
        self._value = self._clamp(value)
        self._show()

    def _revert(self):
        self._show()

    def _commit(self):
        n = self._parse()
        if n is None:
            self._revert()                           # invalid text: back to the last value, nothing said
            return
        n = self._clamp(n)
        self.edit.setText(self._text(n))
        if n != self._value:
            self._value = n
            self.changed.emit(n)

    def _steps(self):
        return self.isEnabled()

    def _step(self, direction):
        n = self._parse()
        base = self._value if n is None else n
        self.edit.setText(self._text(self._clamp(base + direction * self.step)))
        self._commit()


class TextField(_Field):
    """A line of text in the mock's field; commits on Enter or leaving it, when it differs from the last."""

    def __init__(self, value="", placeholder=None, tooltip=None, name=None, parent=None):
        super().__init__(tooltip, name, parent)
        self.restyle()
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        self._value = str(value or "")
        self.edit.setText(self._value)

    def restyle(self):
        self.edit.setFont(_font("input"))
        self.edit.setMinimumWidth(round(_px("settings-text-w")))

    def value(self):
        return self._value

    def set_value(self, value):
        """Show `value` — no signal."""
        self._value = str(value or "")
        self.edit.setText(self._value)

    def _revert(self):
        self.edit.setText(self._value)

    def _commit(self):
        text = self.edit.text().strip()
        if text != self.edit.text():
            self.edit.setText(text)
        if text != self._value:
            self._value = text
            self.changed.emit(text)


class Range(QWidget):
    """Two numbers with "to" between (Sentences' length): `value()` (low, high); each end commits as a NumberField
    does; one end set past the other carries the other with it."""
    changed = pyqtSignal(object)

    def __init__(self, minimum, maximum, value=None, suffix=None, step=1, tooltip=None, name=None, names=None,
                 parent=None):
        super().__init__(parent)
        lo, hi = value if value is not None else (minimum, maximum)
        low_name, high_name = names or (name, name)
        self.low = NumberField(minimum, maximum, lo, step=step, tooltip=tooltip, name=low_name, parent=self)
        self.high = NumberField(minimum, maximum, hi, suffix=suffix, step=step, tooltip=tooltip, name=high_name,
                                parent=self)
        between = QLabel(self)
        between.setObjectName("settingsaffix")
        between.setText(RANGE_TO)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(round(6 * _f()))
        row.addWidget(self.low)
        row.addWidget(between)
        row.addWidget(self.high)
        row.addStretch(0)
        if name:
            self.setAccessibleName(name)
        if tooltip:
            self.setToolTip(tooltip)
        self.setFocusProxy(self.low)
        self.low.changed.connect(lambda _v: self._part(self.low))
        self.high.changed.connect(lambda _v: self._part(self.high))

    def restyle(self):
        self.low.restyle()
        self.high.restyle()

    def value(self):
        return (self.low.value(), self.high.value())

    def set_value(self, value):
        lo, hi = value
        self.low.set_value(lo)
        self.high.set_value(hi)

    def _part(self, which):
        lo, hi = self.value()
        if lo > hi:
            (self.high if which is self.low else self.low).set_value(lo if which is self.low else hi)
        self.changed.emit(self.value())


# --- a long one-of ---------------------------------------------------------------------------------------------------- #
class Select(_Control):
    """A long one-of (the report's *Look*): a field showing the choice and a chevron; a click, Space, Enter or an arrow
    opens its menu (a layer-2 overlay, as every menu in the shell), where arrows move and Enter chooses."""

    def __init__(self, options, value=None, tooltip=None, name=None, parent=None):
        super().__init__(tooltip, name, parent)
        self._options = _options(options)
        self._index = 0
        self.menu = QMenu(self)
        group = QActionGroup(self.menu)
        group.setExclusive(True)
        self._actions = []
        for v, label, tip in self._options:
            action = self.menu.addAction(label)
            action.setCheckable(True)
            if tip:
                action.setToolTip(tip)
            action.triggered.connect(lambda _checked=False, v=v: self._pick(v))
            group.addAction(action)
            self._actions.append(action)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_value(self._options[0][0] if value is None else value)

    def _find(self, value):
        for i, (v, _l, _t) in enumerate(self._options):
            if v == value:
                return i
        raise ValueError(f"not an option: {value!r}")

    def value(self):
        return self._options[self._index][0]

    def set_value(self, value):
        """Show `value` — no signal."""
        self._index = self._find(value)
        self._actions[self._index].setChecked(True)
        self.setAccessibleDescription(self._options[self._index][1])
        self.update()

    def _pick(self, value):
        i = self._find(value)
        if i == self._index:
            return
        self.set_value(value)
        self.changed.emit(value)

    def open_menu(self):
        if not self.isEnabled():
            return
        self.menu.setActiveAction(self._actions[self._index])
        self.menu.popup(self.mapToGlobal(QPoint(0, self.height() + 2)), self._actions[self._index])

    def sizeHint(self):
        fm = QFontMetricsF(_font("select"))
        widest = max(fm.horizontalAdvance(l) for _v, l, _t in self._options)
        pad = round(10 * _f())
        w = max(_px("settings-select-w"), widest + 3 * pad + 12 * _f())
        return QSize(math.ceil(w), round(_px("settings-num-h")))

    def minimumSizeHint(self):
        return self.sizeHint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.open_menu()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Up, Qt.Key.Key_Down,
                           Qt.Key.Key_F4):
            self.open_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        radius = theme.RADII["r-sm"]
        paint_cut(p, r, radius)
        pad = round(10 * _f())
        p.setFont(_font("select"))
        p.setPen(_c(theme.SETTINGS_TEXT["value"]) if self.isEnabled() else _c(theme.SETTINGS_TEXT["greyed"]))
        chev = 8 * _f()
        p.drawText(r.adjusted(pad, 0, -(pad + chev + 6), 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._options[self._index][1])
        pen = QPen(self._ink(False), max(1.4, 1.5 * _f()))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = r.right() - pad - chev / 2, r.center().y()
        path = QPainterPath(QPointF(cx - chev / 2, cy - chev / 4))
        path.lineTo(QPointF(cx, cy + chev / 4))
        path.lineTo(QPointF(cx + chev / 2, cy - chev / 4))
        p.drawPath(path)
        if self.hasFocus():
            paint_ring(p, r, radius)
        p.end()


# --- doors and the status mark ---------------------------------------------------------------------------------------- #
class Door(QPushButton):
    """A button in the house style that opens a window or acts (*Anki…*, *Speech settings…*). Settings' doors are all
    the one plain kind (the lead, 2026-10-15: no iris-filled button in Settings). Buttons take focus by Tab (a click
    leaves no ring)."""

    def __init__(self, label, tooltip=None, name=None, parent=None):
        super().__init__(label.replace("&", "&&"), parent)       # an "&" is shown, never a mnemonic (S2)
        if tooltip:
            self.setToolTip(tooltip)
        self.setAccessibleName(name or label)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class StatusMark(QWidget):
    """The emerald (*connected*, brief §8): a round cut stone drawn flat — a filled circle with one facet lit — lit or
    dark, **always with its words beside it** (S6: never colour alone)."""

    def __init__(self, lit=False, words="", tooltip=None, name=None, parent=None):
        super().__init__(parent)
        self._lit, self._words = bool(lit), str(words)
        if tooltip:
            self.setToolTip(tooltip)
        self._name = name
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._describe()

    def value(self):
        return self._lit

    def words(self):
        return self._words

    def restyle(self):
        self.updateGeometry()
        self.update()

    def set_value(self, lit, words=None):
        """Lit or dark, with its words (kept when None)."""
        self._lit = bool(lit)
        if words is not None:
            self._words = str(words)
        self._describe()
        self.updateGeometry()
        self.update()

    def _describe(self):
        self.setAccessibleName(STATUS_NAME.format(name=self._name, words=self._words) if self._name else self._words)

    def _font(self):
        return _font("body", 600)

    def sizeHint(self):
        fm = QFontMetricsF(self._font())
        stone = _px("settings-emerald")
        return QSize(math.ceil(stone + 7 * _f() + fm.horizontalAdvance(self._words) + 2), math.ceil(fm.height()))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        stone = _px("settings-emerald")
        centre = QPointF(stone / 2 + 0.5, self.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c("emerald" if self._lit else "emerald-dark"))
        p.drawEllipse(centre, stone / 2, stone / 2)
        table = QPainterPath(QPointF(centre.x() - stone * 0.22, centre.y() - stone * 0.10))   # its table, lit
        table.lineTo(QPointF(centre.x() - stone * 0.02, centre.y() - stone * 0.30))
        table.lineTo(QPointF(centre.x() + stone * 0.12, centre.y() - stone * 0.12))
        table.lineTo(QPointF(centre.x() - stone * 0.06, centre.y() + stone * 0.06))
        table.closeSubpath()
        p.setBrush(_c("emerald-facet" if self._lit else "emerald-dark-facet"))
        p.drawPath(table)
        p.setFont(self._font())
        p.setPen(_c(theme.SETTINGS_TEXT["status" if self._lit else "status-off"]))
        x = stone + 7 * _f()
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._words)
        p.end()
