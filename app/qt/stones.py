"""The string's stones as ready-made pictures (W3.1a row A; the RUNBOOK's §1 *The string*, §3 speed rules).

The redesign's gem kit (Design Doctrine `trials/surasura-2026-10-09/worlds/gem-kit.js`, and the trillion ▶ of
`list-r14m.html` L2735–2760) ported to flat `QPainterPath` facets: one colour per facet as the kit's recipe works it
out, **no filter, turbulence, gradient shade, bezel, glow or blur**. Its randomness is the kit's own — FNV-1a over the
seed's text, then mulberry32, bit-exact, with the kit's salts (1 structure, 2 character, 3 the ore's cut points) — so a
stone here is the stone the reference page draws for the same seed.

**The sheet.** Every picture a row can show is drawn once per (device-pixel ratio, text size) into one `QImage` atlas
(premultiplied ARGB, antialiased), off the GUI thread (`bridge.run_in_worker`), at the first paint that asks for it —
never before the first frame: a window holds every build back until its first frame is flushed (`hold` / `release`;
the shell asks for its sheet then, S1), and its rows paint stoneless meanwhile. A fixed set of variants:
- singles: rock / raw / cut × the three gems × `VARIANTS` seeds × three sizes (watched, next — big, waiting — small);
- the cut groups 12 / 60 / 120 × the gems, their count baked in (a row's groups are always whole);
- ores: the gems × four size buckets × four mined shares (none, some, most, all) × with or without cut points;
- the trillion ▶ in each gem, and not linked (greys); the cyan ring, one per single size;
- pre-studied's add (J-STONES): one per single (its sheen and sparkle, on the stone's own anchor), one per cut group and
  ore picture (the sparkle at its shoulder), and the sparkle alone — blitted over the stone, never instead of it.
The pictures themselves (their display lists, Qt-free) are `app/stone_shapes.py`'s; this file paints and holds them.
A stone is then a blit (`Sheet.draw`), never drawn per frame. Each picture keeps its anchor — the point that sits on the
string's hairline (the kit's origin; a single stone's vertical centre is its own box's, so every stone sits on one line).

**Budget:** ≤ `BUDGET_BYTES` over every sheet held (width × height × 4); the oldest goes first when a new one lands.
`QImage` and a painter on it are fine off the GUI thread; a `QPixmap` is not, so the sheet stays a `QImage`.
"""
import math
import threading
import time
from collections import OrderedDict

from PyQt6.QtCore import QObject, QPointF, QRectF, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from app import theme

# --- The geometry: Qt-free, in `app/stone_shapes.py` (journey v3 SPEC §2.4: the journey's headless render draws
# the same stones from it, never importing Qt); named here as before, so every `stones.<name>` keeps working
from app.stone_shapes import (  # noqa: F401
    FOLLOWS_TEXT_SIZE, hash_seed, prng, seed_of, character, warp, MITER, ROUND, BEVEL, SINGLE, IMP, BLOCK, stone_ops,
    group_scale, group_ops, ORE_CAP, ORE_V_SIZE, ore_size, ore_ops, UNLINKED, trillion_ops, ring_ops, VARIANTS, SEEDS,
    STATES, GEMS, SIZES, TIERS, ORE_N, ORE_SEEDS, MINED_SHARE, ORE_CUT_SHARE, TRILLION_SEED, GROUP_SEED, ROW_SCALE,
    variant_of, size_bucket, mined_step, pictures, pre_ops, pre_pictures, sheen_ops, sparkle_ops, shoulder, SPARK,
    _bounds,
)


# --- Painting the display list --------------------------------------------------------------------------------------- #
_JOINS = {MITER: Qt.PenJoinStyle.MiterJoin, ROUND: Qt.PenJoinStyle.RoundJoin, BEVEL: Qt.PenJoinStyle.BevelJoin}
_CAPS = {"butt": Qt.PenCapStyle.FlatCap, "round": Qt.PenCapStyle.RoundCap}
_FONT_PX = 100                                  # the count is laid out at 100 px, then scaled (fractional sizes)


def _qc(rgb, alpha=1.0):
    return QColor(rgb[0], rgb[1], rgb[2], int(round(alpha * 255)))


def _poly(pts):
    return QPolygonF([QPointF(p[0], p[1]) for p in pts])


def _count_path(text, x, baseline, size):
    font = QFont()
    font.setFamilies(list(theme.font_families("ja")))
    font.setPixelSize(_FONT_PX)
    font.setWeight(QFont.Weight.Bold)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    k = size / _FONT_PX
    width = QFontMetricsF(font).horizontalAdvance(text) * k
    return QTransform(k, 0, 0, k, x - width / 2, baseline).map(path)


def _paint(p, ops):
    for op in ops:
        kind = op[0]
        if kind == "fill":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc(op[2], op[3]))
            p.drawPolygon(_poly(op[1]))
        elif kind == "plane":
            pen = QPen(_qc(op[2]), op[3])
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(_qc(op[2]))
            p.drawPolygon(_poly(op[1]))
        elif kind == "line":
            _k, pts, rgb, alpha, width, closed, join, cap = op
            pen = QPen(_qc(rgb, alpha), width)
            pen.setJoinStyle(_JOINS[join])
            pen.setCapStyle(_CAPS[cap])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if closed:
                p.drawPolygon(_poly(pts))
            else:
                p.drawPolyline(_poly(pts))
        elif kind == "clip":
            area = QPainterPath()
            for poly in op[1]:
                piece = QPainterPath()
                piece.addPolygon(_poly(poly))
                piece.closeSubpath()
                area = area.united(piece)
            p.save()                                            # inside the picture's own rect
            p.setClipPath(area, Qt.ClipOperation.IntersectClip)
        elif kind == "unclip":
            p.restore()
        elif kind == "text":
            _k, x, y, size, text, fill, stroke, stroke_alpha, stroke_w = op
            path = _count_path(text, x, y, size)
            pen = QPen(_qc(stroke, stroke_alpha), stroke_w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)                             # paint-order: stroke, then the fill over it
            p.fillPath(path, _qc(fill))
        elif kind == "circle":
            _k, cx, cy, r, rgb, width = op
            p.setPen(QPen(_qc(rgb), width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)


# --- The sheet --------------------------------------------------------------------------------------------------------- #
GAP = 2                                         # device px of nothing between two pictures (no bleed when scaled)


def paint_ops(p, ops):
    """A display list painted with `p` as it is set (ONB-1: setup's *Your start* draws a few stones at its own size)."""
    _paint(p, ops)


class Sheet:
    """Every picture at one (device-pixel ratio, text size), packed into `images` (QImage atlases)."""

    def __init__(self, dpr, text_size, images, entries, build_ms, thread_id):
        self.dpr, self.text_size = dpr, text_size
        self.images = images
        self.entries = entries                  # what -> (image index, src QRectF device px, anchor QPointF, QSizeF)
        self.build_ms = build_ms
        self.thread_id = thread_id              # the thread that drew it (a test reads it)
        self.bytes = sum(im.width() * im.height() * 4 for im in images)

    def __contains__(self, what):
        return what in self.entries

    def size_of(self, what):
        """The picture's size in logical px."""
        return self.entries[what][3]

    def rect_of(self, what, at):
        """Where the picture lands (logical px) when its anchor sits on `at`."""
        _i, _src, anchor, size = self.entries[what]
        return QRectF(at.x() - anchor.x(), at.y() - anchor.y(), size.width(), size.height())

    def draw(self, painter, at, what):
        """Blit the picture with its anchor on `at` (logical px)."""
        i, src, _anchor, _size = self.entries[what]
        painter.drawImage(self.rect_of(what, at), self.images[i], src)


def build(dpr, text_size):
    """Draw a whole sheet (any thread: only QImage and a painter on it). -> Sheet."""
    t0 = time.perf_counter()
    fz = theme.text_factor(text_size) if FOLLOWS_TEXT_SIZE else 1.0
    placed = []
    for what, ops, unit, anchor in pictures():
        k = unit * fz * dpr                                     # device px per unit
        x0, y0, x1, y1, pad = _bounds(ops)
        X0, Y0 = math.floor((x0 - pad) * k) - 1, math.floor((y0 - pad) * k) - 1
        X1, Y1 = math.ceil((x1 + pad) * k) + 1, math.ceil((y1 + pad) * k) + 1
        placed.append([what, ops, k, anchor, X0, Y0, X1 - X0, Y1 - Y0])
    area = sum((e[6] + GAP) * (e[7] + GAP) for e in placed)
    width = max(max(e[6] for e in placed) + GAP, int(math.ceil(math.sqrt(area) * 1.08)))
    width = (width + 15) // 16 * 16
    x = y = shelf = 0
    spots = {}
    for e in sorted(placed, key=lambda e: (-e[7], -e[6])):      # shelves, tallest first
        if x + e[6] + GAP > width:
            x, y, shelf = 0, y + shelf, 0
        spots[e[0]] = (x, y)
        x += e[6] + GAP
        shelf = max(shelf, e[7] + GAP)
    height = max(1, y + shelf)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    entries = {}
    for what, ops, k, anchor, X0, Y0, w, h in placed:
        px, py = spots[what]
        p.save()
        p.setClipRect(QRectF(px, py, w, h))
        p.translate(px - X0, py - Y0)
        p.scale(k, k)
        _paint(p, ops)
        p.restore()
        entries[what] = (0, QRectF(px, py, w, h), QPointF((anchor[0] * k - X0) / dpr, (anchor[1] * k - Y0) / dpr),
                         QSizeF(w / dpr, h / dpr))
    p.end()
    return Sheet(dpr, text_size, [image], entries, (time.perf_counter() - t0) * 1000, threading.get_ident())


# --- The sheets held, built on demand ----------------------------------------------------------------------------------- #
BUDGET_BYTES = 16 * 1024 * 1024
_SHEETS = OrderedDict()                         # (dpr, text size) -> Sheet, oldest first
_BUILDING = {}                                  # (dpr, text size) -> [one-shot callbacks]
_FAILED = set()                                 # a build that raised is not tried again this session
_HELD = set()                                   # windows whose first frame hasn't come yet: no build starts (S1)
_DEFERRED = []                                  # keys asked for while held, started at the release
_notifier = []


class _Notifier(QObject):
    ready = pyqtSignal(object)                  # (dpr, text size): a sheet landed — repaint once


def notifier():
    """The object whose `ready` signal says a sheet landed (made on the GUI thread at its first use)."""
    if not _notifier:
        _notifier.append(_Notifier())
    return _notifier[0]


def _key(dpr, text_size):
    if not FOLLOWS_TEXT_SIZE:
        text_size = theme.DEFAULT_TEXT_SIZE
    return (round(float(dpr), 2), text_size if text_size in theme.TEXT_SIZES else theme.DEFAULT_TEXT_SIZE)


def held_bytes():
    return sum(s.bytes for s in _SHEETS.values())


def hold(token):
    """S1: a window not yet past its first frame holds every build back (its rows may paint before it: stoneless) —
    `release(token)` once its first frame is flushed (the shell's `first_frame`), or when it goes. GUI thread."""
    _HELD.add(token)


def release(token):
    """`token` lets go; with no window holding, the builds asked for meanwhile start. GUI thread."""
    _HELD.discard(token)
    if _HELD:
        return
    while _DEFERRED:
        key = _DEFERRED.pop(0)
        if key in _BUILDING:
            _start(key)


def get(dpr, text_size, ready=None):
    """The sheet for (dpr, text size), or None while it is being built (the first ask starts the build on a worker —
    or, while a window's first frame is still coming, once it has come (`hold`); `ready(sheet)`, if given, runs once on
    the GUI thread when it lands, and `notifier().ready` fires). GUI thread."""
    key = _key(dpr, text_size)
    sheet = _SHEETS.get(key)
    if sheet is not None:
        _SHEETS.move_to_end(key)
        return sheet
    if key in _FAILED:
        return None
    if key in _BUILDING:
        if ready is not None:
            _BUILDING[key].append(ready)
        return None
    _BUILDING[key] = [ready] if ready is not None else []
    notifier()
    if _HELD:
        _DEFERRED.append(key)                   # never inside the first frame (S1): asked again at its release
    else:
        _start(key)
    return None


def _start(key):
    """The build of `key`'s sheet, on a worker."""
    from app.qt import bridge
    bridge.run_in_worker(build, key[0], key[1], then=lambda s, key=key: _landed(key, s),
                         failed=lambda info, key=key: _broke(key, info))


def _landed(key, sheet):
    waiting = _BUILDING.pop(key, [])
    _SHEETS[key] = sheet
    _SHEETS.move_to_end(key)
    while len(_SHEETS) > 1 and held_bytes() > BUDGET_BYTES:      # the newest stays; the oldest goes first
        _SHEETS.popitem(last=False)
    for cb in waiting:
        cb(sheet)
    notifier().ready.emit(key)


def _broke(key, info):
    import sys
    from app.qt import applog
    _BUILDING.pop(key, None)
    _FAILED.add(key)
    print(f"The stones' sheet could not be drawn: {info[1]}", file=sys.stderr)
    applog.log("stones", f"the sheet at {key} could not be drawn: {info[1]}")    # L4: the frozen app has no stderr


def clear():
    """Drop every sheet (tests; a theme change would call it), and every window's hold with the builds it deferred
    (AD-13: a window that never painted nor went must not hold every later build back)."""
    _SHEETS.clear()
    _FAILED.clear()
    _HELD.clear()
    for key in _DEFERRED:
        _BUILDING.pop(key, None)                # never started: asked for again, it starts
    _DEFERRED.clear()
