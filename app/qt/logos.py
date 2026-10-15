"""The services' logos on Settings › Connections (W3.3 PL; Sonic W3.3-2: "Good to get the logo sourced as well").

Each logo was sourced and cleared in the planning folder's `tracks/window/work/w33/logos/LOGOS.md`; the files ship
unmodified in `app/assets/logos/` (with Anki's and Anki Miner's licence texts). Only the services in `CLEARED` have
one: AniList and YouTube are not cleared (name only), and every other row keeps its name alone.

`logo(name, px, callback, dpr=None)`: the logo `px` logical pixels tall (its width by its own aspect, scaled evenly),
handed to `callback` as a `QPixmap` — or `None` for a service with no cleared logo, or a file missing or unreadable
(the row keeps its name). The file is decoded once per (name, px, dpr), **on a worker** (`QSvgRenderer` /
`QImageReader` into a `QImage` at `px × dpr`; of a PNG set, the smallest source at least that tall); the GUI thread
only makes the `QPixmap` from it, once, and reuses it. A cached logo is handed back at once (inside the call); asks
for one still decoding wait for that decode. Nothing is recoloured, cropped or framed — except Anki Miner's black
tile, which gets a 1 px tile *behind* it so it reads on the dark ground (LOGOS.md).
"""
import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from app import path_utils
from app.qt import bridge

# Which service has a cleared logo, and its file(s) in `app/assets/logos/` (a PNG set smallest first). Anki's classic
# icon stands for AnkiWeb too: LOGOS.md's safe choice (the Anki logo licence names AnkiWeb).
CLEARED = {
    "anki": ("anki-icon-vector.svg",),
    "ankiweb": ("anki-icon-vector.svg",),
    "anki_miner": ("anki_miner.svg",),
    "hato": ("hato-32.png", "hato-64.png", "hato-128.png"),
    "tsubasa": ("tsubasa-32.png", "tsubasa-64.png", "tsubasa-128.png"),
    "tmdb": ("tmdb_blue_short.svg",),
}
# A tile drawn behind the logo (never over it): Anki Miner's black tile would vanish into the dark ground (LOGOS.md:
# "a 1 px #2d2d2d ring or a SURFACE tile behind it, never a change to its colours"). The colour is the card's own
# #2d2d2d: 3.0's `surface` (#0a0e14) is too near black to show the tile's edge.
BEHIND = {"anki_miner": "#2d2d2d"}
RING_PX = 1                     # logical pixels the tile behind shows around the logo
TILE_ROUND = 0.19               # the tile's corner radius by its side (the logo's own: 40 + 8 of 256)

_IMAGES = {}                    # (name, px, dpr) -> QImage or None, decoded on a worker
_PIXMAPS = {}                   # (name, px, dpr) -> QPixmap, made on the GUI thread from the image, once
_WAITING = {}                   # (name, px, dpr) -> the callbacks waiting for a decode under way


def folder():
    """`app/assets/logos/`: beside the code from source, in the bundle when frozen (Surasura.spec carries
    `app/assets`)."""
    if path_utils.is_frozen():
        return os.path.join(getattr(sys, "_MEIPASS", ""), "app", "assets", "logos")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "logos")


def _ratio(dpr):
    if dpr:
        return float(dpr)
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen else 1.0


def _decode(name, px, dpr):
    """The logo as a QImage `px × dpr` device pixels tall (its device pixel ratio set), or None. Runs on a worker."""
    files = CLEARED.get(name)
    if not files or px <= 0:
        return None
    tall = max(1, round(px * dpr))
    paths = [os.path.join(folder(), f) for f in files]
    if paths[0].lower().endswith(".svg"):
        if not os.path.isfile(paths[0]):
            return None
        renderer = QSvgRenderer(paths[0])
        box = renderer.viewBoxF()
        if not renderer.isValid() or box.height() <= 0 or box.width() <= 0:
            return None
        wide = max(1, round(tall * box.width() / box.height()))
        image = QImage(wide, tall, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = QRectF(0, 0, wide, tall)
        if name in BEHIND:
            ring = max(1, round(RING_PX * dpr))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BEHIND[name]))
            p.drawRoundedRect(target, wide * TILE_ROUND, tall * TILE_ROUND)
            target = target.adjusted(ring, ring, -ring, -ring)
        renderer.render(p, target)
        p.end()
    else:
        sources = []
        for path in paths:
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid() and size.height() > 0:
                sources.append((size.height(), path))
        if not sources:
            return None
        sources.sort()
        path = next((pth for h, pth in sources if h >= tall), sources[-1][1])
        image = QImageReader(path).read()
        if image.isNull():
            return None
        if image.height() != tall:
            image = image.scaledToHeight(tall, Qt.TransformationMode.SmoothTransformation)
    image.setDevicePixelRatio(dpr)
    return image


def logo(name, px, callback, dpr=None):
    """Hand `callback` the logo of `name` `px` logical pixels tall as a QPixmap (or None: no cleared logo, or a file
    missing or unreadable). Call it on the GUI thread; `dpr` is the widget's device pixel ratio (the primary screen's
    when None)."""
    if name not in CLEARED:
        callback(None)
        return
    key = (name, int(px), _ratio(dpr))
    if key in _PIXMAPS or key in _IMAGES:
        callback(_pixmap(key))
        return
    if key in _WAITING:
        _WAITING[key].append(callback)
        return
    _WAITING[key] = [callback]

    def done(image):
        _IMAGES[key] = image
        pix = _pixmap(key)
        for fn in _WAITING.pop(key, []):
            fn(pix)

    def failed(_info):
        done(None)

    bridge.run_in_worker(_decode, *key, then=done, failed=failed)


def _pixmap(key):
    if key not in _PIXMAPS:
        image = _IMAGES.get(key)
        if image is None:
            return None
        _PIXMAPS[key] = QPixmap.fromImage(image)
    return _PIXMAPS[key]


# The Settings page's rows that show a logo, and whose (Connections' and Anki's own status row). AnkiWeb, tsubasa and
# TMDB have a cleared logo but no row of their own yet; AniList, jimaku, YouTube and More from Houseki keep the name.
ROWS = {"anki_connection": "anki", "anki_miner": "anki_miner", "hato": "hato"}
ROW_PX = 20                     # a row's logo, logical px at text size M: below the label's two lines, never the mark


def row_px():
    """ROW_PX at the current text size."""
    from app import theme
    from app.qt import style
    return max(1, round(ROW_PX * theme.text_factor(style.current()[1])))


def show(row_view, name=None, px=None):
    """Put the row's logo before its words (a `QLabel` named `settingslogo`, made once and reused); a restyle calls it
    again and only a new size or scale asks for a new decode. Only that label repaints. A row without a cleared logo,
    or one whose file can't be read, keeps its name alone (the label hidden)."""
    from PyQt6 import sip
    from PyQt6.QtWidgets import QLabel
    name = name or ROWS.get(getattr(getattr(row_view, "row", None), "id", ""), "")
    if name not in CLEARED:
        return None
    label = row_view.findChild(QLabel, "settingslogo")
    if label is None:
        label = QLabel(row_view)
        label.setObjectName("settingslogo")
        label.setAccessibleName(name)
        label.hide()
        row_view.layout().insertWidget(0, label, 0, Qt.AlignmentFlag.AlignVCenter)
    px = px or row_px()

    def paint(pix):
        if sip.isdeleted(label):
            return
        if pix is None:
            label.hide()
            return
        if label.pixmap().cacheKey() != pix.cacheKey():
            label.setPixmap(pix)
        label.setFixedSize(round(pix.width() / pix.devicePixelRatio()), round(pix.height() / pix.devicePixelRatio()))
        label.show()

    logo(name, px, paint, dpr=row_view.devicePixelRatioF())
    return label


def clear():
    """Forget every decoded logo (tests)."""
    _IMAGES.clear()
    _PIXMAPS.clear()
    _WAITING.clear()
