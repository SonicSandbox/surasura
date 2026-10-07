"""Cached shadows (M2.1; the window's spec 05 §5.3, A4 *Shadows*): the mock's soft `box-shadow`s, painted from pixmaps
made once — never a `QGraphicsEffect` (a trap on scrolling lists).

A shadow is `theme.SHADOWS[name]` = (x, y, blur, spread, colour), as CSS defines a box shadow: the box moved by (x, y),
grown by `spread` (shrunk when negative), blurred by a Gaussian of σ = blur / 2, in `colour` (`accent` = the theme's).
The blur of a box is the product of two edge profiles, so each image is two gradient fills — the horizontal profile, then
the vertical one through `DestinationIn` — with no per-pixel Python. The corner's own radius (≤ 16 px, against σ ≥ 5 px)
is drawn square: the blur hides it.

**Cached** per (shadow, colour, device-pixel ratio), each axis on its own: a side of the box at least 6σ long is
*sliced* (the cached image keeps its two ramps and a 2 px middle, stretched when drawn: exact for any longer side, since
the blur is the product of the x and y profiles), a shorter side is drawn at its own length (a short box's shadow is
fainter: stretched from a long box's ramps it would be too dark). So a toast keys on its height alone, whatever its
width. At most 16 MB is kept, the least recently used going first.

`paint(painter, rect, name)` draws the shadow of the box `rect`; `margins(name)` is how far it reaches past the box (left,
top, right, bottom); `Follower(widget, name)` is a sibling under an overlay that draws its shadow and never takes the mouse.
"""
import math
from collections import OrderedDict

from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from app import theme
from app.qt import style

REACH = 3.0                                      # a shadow is drawn out to 3σ past its box (the rest is < 0.2 %)
STOPS = 24                                       # gradient stops across each edge's ramp
MIDDLE = 2                                       # a sliced side's middle in the cached image (stretched when drawn)
KEPT_BYTES = 16 * 1024 * 1024                    # the cache's bound (least recently used first out)

_cache = OrderedDict()                           # (name, colour, dpr, w or None, h or None) -> (pixmap, bytes)
_held = [0]


def spec(name):
    """(x, y, blur, spread, QColor) for a named shadow, the colour resolved for the current theme."""
    x, y, blur, spread, colour = theme.SHADOWS[name]
    if colour == "accent":
        colour = style.colours()["accent"]
    return x, y, blur, spread, style.qcolor(colour)


def sigma(name):
    return max(0.5, theme.SHADOWS[name][2] / 2.0)


def margins(name):
    """How far (left, top, right, bottom; logical px, whole) the named shadow reaches past its box."""
    x, y, _blur, spread, _c = theme.SHADOWS[name]
    reach = REACH * sigma(name) + spread
    return tuple(max(0, math.ceil(v)) for v in (reach - x, reach - y, reach + x, reach + y))


def _phi(v):
    return 0.5 * (1.0 + math.erf(v / math.sqrt(2.0)))


def profile(at, lo, hi, s):
    """The blurred box's edge profile at `at`: the share of a Gaussian (σ = s) over [lo, hi]."""
    return max(0.0, _phi((at - lo) / s) - _phi((at - hi) / s))


def _gradient(length, lo, hi, s, horizontal, colour, alpha_only=False):
    g = QLinearGradient(0, 0, length, 0) if horizontal else QLinearGradient(0, 0, 0, length)
    points = {0.0, float(length)}
    for edge in (lo, hi):                        # stops packed on each ramp, where the profile changes
        for i in range(STOPS + 1):
            points.add(min(float(length), max(0.0, edge - REACH * s + (2 * REACH * s) * i / STOPS)))
    for at in sorted(points):
        a = profile(at, lo, hi, s)
        c = QColor(0, 0, 0, round(255 * a)) if alpha_only else QColor(colour.red(), colour.green(), colour.blue(),
                                                                        round(colour.alpha() * a))
        g.setColorAt(at / length if length else 0.0, c)
    return g


def _render(w, h, box, s, colour, dpr):
    """An image w × h (logical px) holding the blurred `box` (a QRectF in its coordinates), at `dpr`."""
    pw, ph = max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr))
    img = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    sd = s * dpr
    p = QPainter(img)
    p.fillRect(QRect(0, 0, pw, ph), _gradient(pw, box.left() * dpr, box.right() * dpr, sd, True, colour))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.fillRect(QRect(0, 0, pw, ph), _gradient(ph, box.top() * dpr, box.bottom() * dpr, sd, False, colour,
                                                alpha_only=True))
    p.end()
    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    return pix


def _key_colour(c):
    return c.name(QColor.NameFormat.HexArgb)


def _corner(s):
    """A sliced side's ramp in the cached image: from 3σ outside the box's edge to 3σ inside it (logical px)."""
    return math.ceil(2 * REACH * s)


def _short(length, s):
    """None when a side of the box is long enough to slice (≥ 6σ: its ramps don't meet, so a longer side is the same
    ramps with more middle), else its length (a short side's shadow is fainter: drawn at its own length)."""
    reach = REACH * s
    return None if length + 2 * reach >= 2 * _corner(s) + 1 else round(length, 2)


def image(name, dpr, w_short, h_short):
    """The cached image for a box whose sides are `w_short` / `h_short` (None = a long, sliced side). -> pixmap."""
    _x, _y, _blur, _spread, colour = spec(name)
    key = (name, _key_colour(colour), round(dpr, 3), w_short, h_short)
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
        return hit[0]
    s = sigma(name)
    reach = REACH * s
    corner = _corner(s)
    w = 2 * corner + MIDDLE if w_short is None else w_short + 2 * reach
    h = 2 * corner + MIDDLE if h_short is None else h_short + 2 * reach
    box = QRectF(reach, reach, w - 2 * reach, h - 2 * reach)
    pix = _render(w, h, box, s, colour, dpr)
    size = pix.width() * pix.height() * 4
    _cache[key] = (pix, size)
    _held[0] += size
    while _held[0] > KEPT_BYTES and len(_cache) > 1:
        _old, (_p, old_size) = _cache.popitem(last=False)
        _held[0] -= old_size
    return pix


def cached():
    """How many images and bytes the cache holds now."""
    return len(_cache), _held[0]


def shape(rect, name):
    """The shadow's own box for an element at `rect` (QRectF): moved by (x, y), grown by spread."""
    x, y, _blur, spread, _c = theme.SHADOWS[name]
    return QRectF(rect).adjusted(-spread, -spread, spread, spread).translated(x, y)


def paint(painter, rect, name):
    """Draw the named shadow of an element at `rect` (logical px, the painter's coordinates)."""
    box = shape(rect, name)
    if box.width() <= 0 or box.height() <= 0:
        return                                   # a spread larger than the box: nothing (as CSS)
    s = sigma(name)
    reach = REACH * s
    dpr = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
    w_short, h_short = _short(box.width(), s), _short(box.height(), s)
    pix = image(name, dpr, w_short, h_short)
    outer = box.adjusted(-reach, -reach, reach, reach)
    c = _corner(s)
    xs = _segments(outer.left(), outer.right(), w_short, c)
    ys = _segments(outer.top(), outer.bottom(), h_short, c)
    pdpr = pix.devicePixelRatio()
    for (sx0, sx1), (dx0, dx1) in xs:
        for (sy0, sy1), (dy0, dy1) in ys:
            if dx1 - dx0 <= 0 or dy1 - dy0 <= 0:
                continue
            painter.drawPixmap(QRectF(dx0, dy0, dx1 - dx0, dy1 - dy0), pix,
                               QRectF(sx0 * pdpr, sy0 * pdpr, (sx1 - sx0) * pdpr, (sy1 - sy0) * pdpr))


def _segments(start, end, short, corner):
    """[(source span, target span)] along one axis: one span for a short side, three (ramp, middle, ramp) for a long."""
    if short is not None:
        return [((0.0, end - start), (start, end))]
    return [((0.0, corner), (start, start + corner)),
            ((corner, corner + MIDDLE), (start + corner, end - corner)),
            ((corner + MIDDLE, 2 * corner + MIDDLE), (end - corner, end))]


def clear():
    """Forget every cached image."""
    _cache.clear()
    _held[0] = 0


class Follower(QWidget):
    """A shadow under `target` (an in-window overlay): a sibling stacked just below it, following its place, size and
    visibility, transparent to the mouse."""

    def __init__(self, target, name):
        super().__init__(target.parentWidget())
        self.target, self.name = target, name
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("shadowFollower")
        self._watch = _Watch(self)
        target.installEventFilter(self._watch)
        self.follow()

    def follow(self):
        t = self.target
        left, top, right, bottom = margins(self.name)
        self.setGeometry(t.geometry().adjusted(-left, -top, right, bottom))
        if t.isVisible():
            self.show()
            self.stackUnder(t)
        else:
            self.hide()

    def paintEvent(self, _event):
        left, top, _right, _bottom = margins(self.name)
        p = QPainter(self)
        paint(p, QRectF(left, top, self.target.width(), self.target.height()), self.name)
        p.end()


class _Watch(QObject):
    def __init__(self, follower):
        super().__init__(follower)
        self.follower = follower

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide,
                            QEvent.Type.ZOrderChange):
            self.follower.follow()
        return False
