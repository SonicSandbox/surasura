"""The painted rows (W2.2, rebuilt for Current in W3.1a; the window's spec 05 §5.3, §5.9, §5.11, A3, A4; the redesign's
reference `list-r14m.html`, extracted in the planning folder's `tracks/window/work/w31a/ref-extract.md` §3–§8).

Every list in the window is a `QListView` over a `RowsModel`, painted by a `RowDelegate` — **no widget per row**
(BRIEF: paint lists, don't build them from widgets). What a row says is `app/services/view_rows.py`'s; this file only
paints it:
- **Up Next** (the hero): the list's first row, the old mock's card in the new flat look — a `surface` slab, the cover
  with its watched bar, *UP NEXT*, the title and its episode, the source, *% known · N new words ↗*, **the string** of
  stones (where the chips were), ▶ *Play* (the trillion in its kind's gem) and ✓ *Done* side by side, *N in Anki*, ⋯;
- **a Current row**: one line at every text size (W3.1a §1 *Rows*) — its number (↑ ↓ on hover or focus), the wide art
  fading out, the title cut with "…" at its end, **the string** (one stone per file: `app/services/stone_plan.py`'s plan,
  blitted from the stones' sheet, `app/qt/stones.py`), the Anki count, *% · N new*. Hover and keyboard focus show the
  same things (S7): the row lifts on a spring with its baked shadow, its neighbours ease apart, the next stone's ring
  shows and the status, ▶ and ⋯ fade in over the string's end, holding no room. Opened, its episode lines under it,
  each with its stone at the left;
- **the lines** in the gap after their rows: the top-20 line and the Soon line, grooves (1 px dark, 1 px lit lip);
- **Finished**'s month labels and rows (today's layout: a date, no numbers — C-scope §2.3), **Needs you**'s cards.

Text is cached as `QStaticText` per (text, font, width) and dropped when the text size or the screen's pixel ratio
changes; generated covers and the rows' wide art are cached pixmaps per (title, size, ratio). Tooltips on every painted
part go through the window's bubble (`tooltip.Tooltips.request(widget, rect, text)`); each row answers
`AccessibleTextRole` (title · % known · N new · status) and `AccessibleDescriptionRole` (its line and its string read
as words: *8 of 12 watched, 3 in Anki*).

Nothing here writes. ▶ asks the page to open a file (`play_requested`); a click on a stone, or Up Next's ✓ Done, asks
for a Done (`done_requested`: one path, wherever it's clicked); ↑ ↓, ⋯ and the journey's ↗ ask too (`nudge_requested`,
`menu_requested`, `journey_requested`); a row opens and closes. P4.1 L2: a status that is a button — *Mine now* (Waiting's
icon), *Mine this* (Mine), *No video*'s *Link…* — asks too (`mine_requested`, `link_requested`), by a click or, with the keyboard, → then Enter / Space; while Connect is off (`connect_off`, set
by the window) it asks nothing and its tip says why.
"""
import bisect
import math
import os
import re
import time
import unicodedata
import weakref
from collections import OrderedDict, namedtuple

from PyQt6.QtCore import (QAbstractListModel, QItemSelectionModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize,
                          QObject, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QStaticText, QTextOption)
from PyQt6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from app import theme, unicode_ranges
from app.qt import motion, stones, strings, style
from app.qt import covers as qcovers                 # --- W3.2 Q6: a title's own picture, decoded off the GUI thread
from app.services import stone_plan, view_rows

ROW_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2

# Entry kinds the model holds
HERO, ROW, MONTH, FINISHED, NEED, FAILURE, EMPTY = "hero", "row", "month", "finished", "need", "failure", "empty"
PICK_KINDS = (HERO, ROW, FINISHED)                  # A4: the rows Ctrl / Shift+click and Ctrl+A pick (Current, Soon,
#                                                     Finished; Goal's sheet picks its tiles)


# --- text and fonts ---------------------------------------------------------------------------------------------- #
class Text:
    """Fonts per type role at the applied text size, and `QStaticText`s per (text, role, width), elided once."""

    def __init__(self):
        self._fonts = {}
        self._static = {}
        self._metrics = {}
        self._key = None

    def _check(self, dpr=None):
        # Logical pixels: a font, its metrics and a prepared static text hold at any device-pixel ratio, so the cache
        # follows the look (theme, text size, language) only — keyed on the ratio too, it emptied itself whenever a
        # caller asked at 1.0 between two paints at 1.5 (W2.2 review A-1).
        key = style.current()
        if key != self._key:
            self._fonts.clear()
            self._static.clear()
            self._metrics.clear()
            self._key = key

    def font(self, role, weight=None, dpr=1.0):
        self._check(dpr)
        k = (role, weight)
        f = self._fonts.get(k)
        if f is None:
            _theme, size, language = style.current()
            px, w = theme.font(role, size)
            f = QFont()
            f.setFamilies(list(theme.MONO) if role in MONO_ROLES else list(theme.font_families(language)))
            f.setPointSizeF(px * style.PT_PER_PX)
            f.setWeight(QFont.Weight(weight or w))
            spacing = theme.LETTER_SPACING_EM.get(role)
            if spacing:
                f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing * 100)
            if hasattr(QFont, "Tag"):                       # tabular figures (Qt 6.7+): numbers line up (n4)
                try:
                    f.setFeature(QFont.Tag("tnum"), 1)
                except (TypeError, AttributeError):
                    pass
            self._fonts[k] = f
        return f

    def metrics(self, role, weight=None, dpr=1.0):
        k = (role, weight)
        m = self._metrics.get(k)
        if m is None:
            m = self._metrics[k] = QFontMetrics(self.font(role, weight, dpr))
        return m

    def static(self, text, role, width, weight=None, dpr=1.0, elide=True):
        """(QStaticText, its width, whether it was cut) of `text` in `role`, elided to `width` px (`elide=False`:
        never cut — a number, whose figures' tabular widths `elidedText` measures wider than `horizontalAdvance`)."""
        self._check(dpr)
        k = (text, role, weight, int(width) if elide else None)
        hit = self._static.get(k)
        if hit is None:
            fm = self.metrics(role, weight, dpr)
            shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0, int(width))) if elide else text
            st = QStaticText(shown)
            st.setTextFormat(Qt.TextFormat.PlainText)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.NoWrap)
            st.setTextOption(opt)
            st.prepare(font=self.font(role, weight, dpr))
            hit = (st, fm.horizontalAdvance(shown), shown != text)
            if len(self._static) > 6000:
                self._static.clear()
            self._static[k] = hit
        return hit

    def draw(self, p, x, y_mid, text, role, width, colour, weight=None, align="left", dpr=1.0, elide=True):
        """Draw `text` vertically centred on `y_mid`; -> (the width drawn, whether it was elided)."""
        st, w, elided = self.static(text, role, width, weight, dpr, elide)
        fm = self.metrics(role, weight, dpr)
        p.setFont(self.font(role, weight, dpr))
        p.setPen(colour)
        left = x + width - w if align == "right" else x + (width - w) / 2 if align == "centre" else x
        p.drawStaticText(QPointF(left, y_mid - fm.height() / 2), st)
        return w, elided


MONO_ROLES = frozenset({"needs-file"})               # a file's name or its state, as the mock's `.fn` (Consolas)
TEXT = Text()


_QCOLOURS = {}                                       # (theme, name) -> QColor (`c`)


def c(name):
    """A colour of the applied theme by name, made once per theme: a row's first paint asks for ~12, and parsing each
    afresh was ~10 % of it (W2.2 speed round 5). Callers never change it in place (Qt copies it into a pen or brush)."""
    key = (style.current()[0], name)
    q = _QCOLOURS.get(key)
    if q is None:
        colours = style.colours()
        q = _QCOLOURS[key] = style.qcolor(colours[name] if name in colours else theme.FIXED[name]
                                          if name in theme.FIXED else theme.ROW_COLOURS[name])
    return q


def faded(name, alpha):
    """`c(name)` at an alpha 0–1 (a new colour: the shadow, the sheen, a fade's far end)."""
    q = QColor(c(name))
    q.setAlphaF(max(0.0, min(1.0, alpha)))
    return q


def fz():
    return theme.text_factor(style.current()[1])


def rl(name):
    """A size of Current's one-line row (`theme.ROW_LINE`)."""
    return theme.ROW_LINE[name]


# --- covers -------------------------------------------------------------------------------------------------------- #
_COVERS = OrderedDict()
_COVER_BYTES = [0]
COVERS_MB = 8                                        # covers kept, by bytes (a row's cover is ~50 KB at 250 %): a
#                                                      painted row holds its cover, so only new rows need one


def clear_covers():
    _COVERS.clear()
    _COVER_BYTES[0] = 0


_CJK = re.compile(f"[{unicode_ranges.HAN}{unicode_ranges.KANA}]")


def cover_label(title, w, fm):
    """What a generated cover `w` px wide writes on itself, in the font of `fm`: (True, the title) — its characters
    down the right edge, the mock's vertical cover — when it holds a Japanese or Chinese letter anywhere (W2.2:
    vertical for Japanese / Chinese; 7月のペンギン, a romaji name before its kana, half-width ｱﾆﾒ read through NFKC),
    else (False, one line) across its top, cut with "…" to the cover's width, its first letter alone where not even
    "P…" fits: a Latin title stood one letter under another read "P / C / R / e" (laptop try, FEEDBACK 11)."""
    title = title or ""
    t = title.strip()
    if not t or _CJK.search(unicodedata.normalize("NFKC", t)):
        return True, title
    first = next((ch for ch in t if ch.isalnum()), t[0])
    room = max(0, int(w * 0.84))
    line = fm.elidedText(t, Qt.TextElideMode.ElideRight, room)
    if line in ("", "…"):
        line = first if fm.horizontalAdvance(first) <= room else ""
    return False, line


def cover(title, w, h, dpr, large=False, ref=None):
    """The generated cover of a title (05 §5.6: the fallback and the offline look): the mock's gradient, the title's
    first characters down it — or, a title in Latin script, across its top (`cover_label`). Cached per (title, size,
    ratio)."""
    # --- W3.2 Q6: its own picture once decoded (`ref`: the row's `CoverRef`); the generated one meanwhile
    real = qcovers.decoded(ref, w, h, dpr, "tile" if large else "row") if ref is not None else None
    if real is not None:
        return real
    # --- end W3.2 Q6
    key = (title, int(w), int(h), dpr, large)
    pix = _COVERS.get(key)
    if pix is not None:
        _COVERS.move_to_end(key)
        return pix
    pix = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    top, bottom = theme.generated_cover(title)
    grad = QLinearGradient(QPointF(w * 0.33, 0), QPointF(w * 0.67, h))          # ~160°
    grad.setColorAt(0, style.qcolor(top))
    grad.setColorAt(1, style.qcolor(bottom))
    path = QPainterPath()
    radius = theme.RADII["cover-tile" if large else "cover-row"]
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.fillPath(path, QBrush(grad))
    role = "cover-title-large" if large else "cover-title"
    f = TEXT.font(role, dpr=dpr)
    p.setFont(f)
    p.setPen(style.qcolor(theme.FIXED["cover-ink"]))
    fm = QFontMetrics(f)
    vertical, text = cover_label(title, w, fm)
    if not vertical:                                    # one line across its top, cut with "…" to the cover's width
        p.drawText(QRectF(w * 0.08, h * 0.09, w * 0.84, fm.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        text = ""
    step = fm.height() * 0.92
    x = w - w * 0.08 - fm.horizontalAdvance("あ")
    y = h * 0.09
    for ch in text[: max(1, int((h * 0.82) // max(1.0, step)))]:               # vertical: one character under another
        if not ch.strip():
            y += step * 0.5
            continue
        p.drawText(QRectF(x, y, fm.horizontalAdvance("あ"), step), Qt.AlignmentFlag.AlignCenter, ch)
        y += step
    p.end()
    _COVERS[key] = pix
    _COVER_BYTES[0] += _size(pix)
    while len(_COVERS) > 1 and _COVER_BYTES[0] > COVERS_MB * 1024 * 1024:
        _COVER_BYTES[0] -= _size(_COVERS.popitem(last=False)[1])
    return pix


_ART = OrderedDict()
_ART_BYTES = [0]
ART_MB = 8                                           # the rows' wide art, by bytes (with the covers: well inside 64 MB)


def clear_art():
    _ART.clear()
    _ART_BYTES[0] = 0


def art(title, w, h, dpr, ref=None):
    """A Current row's wide art (W3.1a §1 *Rows*): its cover — the generated one, until the store holds pictures —
    cropped to a strip from `art-focus` down, its fade to nothing **baked in** (opaque for its first `art-fade`, then out
    at its right edge). Cached per (title, size, ratio), so a row's picture blits it."""
    # --- W3.2 Q6: its own picture once decoded (`ref`: the row's `CoverRef`); the generated one meanwhile
    real = qcovers.decoded(ref, w, h, dpr, "art") if ref is not None else None
    if real is not None:
        return real
    # --- end W3.2 Q6
    key = (title, int(w), int(h), dpr)
    pix = _ART.get(key)
    if pix is not None:
        _ART.move_to_end(key)
        return pix
    full_h = max(int(h), round(w * 1.5))                 # the cover at the strip's width (2 : 3), cropped below
    pix = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    # the generated cover's gradient (`cover`'s, ~160°) at the full cover's size, the strip cut from it — without its
    # characters down the side: the title stands right beside the art
    top, bottom = theme.generated_cover(title)
    y0 = -round((full_h - h) * rl("art-focus"))
    grad = QLinearGradient(QPointF(w * 0.33, y0), QPointF(w * 0.67, y0 + full_h))
    grad.setColorAt(0, style.qcolor(top))
    grad.setColorAt(1, style.qcolor(bottom))
    p.fillRect(QRectF(0, 0, w, h), QBrush(grad))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    fade = QLinearGradient(QPointF(0, 0), QPointF(w, 0))
    fade.setColorAt(0, faded("shadow", 1.0))
    fade.setColorAt(rl("art-fade"), faded("shadow", 1.0))
    fade.setColorAt(1, faded("shadow", 0.0))
    p.fillRect(QRectF(0, 0, w, h), QBrush(fade))
    p.end()
    _ART[key] = pix
    _ART_BYTES[0] += _size(pix)
    while len(_ART) > 1 and _ART_BYTES[0] > ART_MB * 1024 * 1024:
        _ART_BYTES[0] -= _size(_ART.popitem(last=False)[1])
    return pix


# --- icons (painted: one colour, recoloured per state, 05 §5.6) ----------------------------------------------------- #
def icon(p, kind, rect, colour, width=1.6):
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = QRectF(rect)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    if kind == "check":
        path = QPainterPath(QPointF(x + w * 0.18, y + h * 0.55))
        path.lineTo(QPointF(x + w * 0.42, y + h * 0.78))
        path.lineTo(QPointF(x + w * 0.84, y + h * 0.25))
        p.drawPath(path)
    elif kind == "mining":
        p.drawArc(r.adjusted(w * 0.12, h * 0.12, -w * 0.12, -h * 0.12), 90 * 16, 270 * 16)
    elif kind == "waiting":
        path = QPainterPath(QPointF(x + w * 0.25, y + h * 0.12))
        path.lineTo(QPointF(x + w * 0.75, y + h * 0.12))
        path.lineTo(QPointF(x + w * 0.25, y + h * 0.88))
        path.lineTo(QPointF(x + w * 0.75, y + h * 0.88))
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "mine":
        p.drawRoundedRect(r.adjusted(w * 0.18, h * 0.08, -w * 0.18, -h * 0.08), 1.5, 1.5)
        p.drawLine(QPointF(x + w * 0.5, y + h * 0.32), QPointF(x + w * 0.5, y + h * 0.68))
        p.drawLine(QPointF(x + w * 0.32, y + h * 0.5), QPointF(x + w * 0.68, y + h * 0.5))
    elif kind in ("no_media", "no_audio"):           # the mock's i-novid / i-noaud (16-unit box), struck through
        u = w / 16
        if kind == "no_media":
            p.drawRoundedRect(QRectF(x + 1.8 * u, y + 4.3 * u, 8.8 * u, 7.4 * u), 1.5 * u, 1.5 * u)
            shape = QPainterPath(QPointF(x + 10.6 * u, y + 7.2 * u))
            for px_, py_ in ((14.2, 5.2), (14.2, 10.8), (10.6, 8.8)):
                shape.lineTo(QPointF(x + px_ * u, y + py_ * u))
        else:
            shape = QPainterPath(QPointF(x + 2.5 * u, y + 6.2 * u))
            for px_, py_ in ((4.9, 6.2), (8.2, 3.4), (8.2, 12.6), (4.9, 9.8), (2.5, 9.8)):
                shape.lineTo(QPointF(x + px_ * u, y + py_ * u))
            shape.closeSubpath()
            shape.moveTo(QPointF(x + 11 * u, y + 6 * u))
            shape.quadTo(QPointF(x + 12.2 * u, y + 7.6 * u), QPointF(x + 11.6 * u, y + 9.4 * u))
        p.drawPath(shape)
        p.drawLine(QPointF(x + 1.6 * u, y + 2.2 * u), QPointF(x + 14.4 * u, y + 13.8 * u))
    elif kind == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        path = QPainterPath(QPointF(x + w * 0.3, y + h * 0.2))
        path.lineTo(QPointF(x + w * 0.82, y + h * 0.5))
        path.lineTo(QPointF(x + w * 0.3, y + h * 0.8))
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "box":
        p.drawRoundedRect(r.adjusted(w * 0.1, h * 0.28, -w * 0.1, -h * 0.1), 1.5, 1.5)
        p.drawLine(QPointF(x + w * 0.04, y + h * 0.28), QPointF(x + w * 0.96, y + h * 0.28))
        p.drawLine(QPointF(x + w * 0.38, y + h * 0.5), QPointF(x + w * 0.62, y + h * 0.5))
    elif kind == "up":                               # an arrow up (Studying its cards first)
        p.drawLine(QPointF(x + w * 0.5, y + h * 0.9), QPointF(x + w * 0.5, y + h * 0.12))
        path = QPainterPath(QPointF(x + w * 0.18, y + h * 0.42))
        path.lineTo(QPointF(x + w * 0.5, y + h * 0.1))
        path.lineTo(QPointF(x + w * 0.82, y + h * 0.42))
        p.drawPath(path)
    elif kind == "dot":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawEllipse(r)
    elif kind == "anki":                             # Anki's mark: a card with a star on it
        p.drawRoundedRect(r.adjusted(w * 0.16, h * 0.06, -w * 0.16, -h * 0.06), 1.8, 1.8)
        star = QPainterPath()
        cx, cy, ro, ri = x + w * 0.5, y + h * 0.5, w * 0.22, w * 0.09
        for k in range(10):
            a = math.pi * k / 5 - math.pi / 2
            rad = ro if k % 2 == 0 else ri
            pt = QPointF(cx + rad * math.cos(a), cy + rad * math.sin(a))
            star.moveTo(pt) if k == 0 else star.lineTo(pt)
        star.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawPath(star)
    elif kind == "warning":                          # a warning: a triangle, its ! inside
        path = QPainterPath(QPointF(x + w * 0.5, y + h * 0.1))
        path.lineTo(QPointF(x + w * 0.94, y + h * 0.88))
        path.lineTo(QPointF(x + w * 0.06, y + h * 0.88))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(x + w * 0.5, y + h * 0.38), QPointF(x + w * 0.5, y + h * 0.6))
        p.drawPoint(QPointF(x + w * 0.5, y + h * 0.74))
    elif kind == "more":                             # ⋯
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        for k in (0.22, 0.5, 0.78):
            p.drawEllipse(QPointF(x + w * k, y + h * 0.5), w * 0.08, w * 0.08)
    elif kind in ("chev-up", "chev-down"):           # ↑ ↓ in the number's column
        a, b = (0.62, 0.36) if kind == "chev-up" else (0.38, 0.64)
        path = QPainterPath(QPointF(x + w * 0.24, y + h * a))
        path.lineTo(QPointF(x + w * 0.5, y + h * b))
        path.lineTo(QPointF(x + w * 0.76, y + h * a))
        p.drawPath(path)
    p.restore()


STATUS_ICON = {"in_anki": "check", "mining": "mining", "waiting": "waiting", "mine_rest": "check", "mine": "mine",
               "no_media": "no_media", "no_subs": "waiting",           # SRC W1b: a video waiting for its subtitle
               "asked": "waiting",                                     # R47: an ask Connect has read
               "books": "waiting"}                                     # alpha 4 M1: waits for Anki Miner to read books

# --- P4.1 L2: the stones' actions (4.1.11; RUNBOOK C2, C3, C6, IK S7). A status that is a button: Waiting's icon is
# *Mine now*, Mine is *Mine this*, No video offers *Link…* (alpha 4 M1: *Mine text* gone). Its part's payload is an `Ask` (`id`: its first
# file's, so a press and its release match as an episode's do; `ids`: the files it asks for; `episode`: the first).
ACTIONS = {"waiting": "mine-now", "mine": "mine-this", "no_media": "no-media"}
HEADPHONES = "🎧 "                               # a5-2 (Hon): before an audiobook's title
STOP = "stop"                                       # R47: a *Mining* status's Stop (`Status.stop`: its job)
ACTION_NAMES = frozenset(ACTIONS.values()) | {STOP}
ASKS = ("mine-now", "mine-this")                    # the actions that ask Connect (round 8 row 45: they turn when pressed)
_ACTION_TIPS = {"mine-now": "ROWS_MINE_NOW_TIP", "mine-this": "ROWS_MINE_THIS_TIP", "no-media": "ROWS_NO_MEDIA_TIP"}


Ask = namedtuple("Ask", "id ids episode job", defaults=(None,))     # R47: `job`, the Connect job a Stop stops

# --- round 8 row 45 (the trial): *Mine now* pressed. From the frame of the press until Connect's feed says something new
# of the file (`mine_actions`; `RowsView.press_ids`), its pill (and a closed row's Mine now) shows a turning accent mark
# in the hourglass's place, no words — its hover says *Asked · starting…*. Sonic chose the hourglass itself turning over
# in place (round 8 trial, his look A: an eased half-turn each `MOTION["mining-spin"]`), and a little smaller while it
# turns ("so the spin and slightly smaller": `TURNING_SCALE`), full size again once it stops. Reduced motion and the
# freeze switch: the mark still, upright, still smaller — the difference shows without motion.
TURNING_SCALE = 0.85                # an icon's size while it turns (PROVISIONAL, ~85 %: Sonic's "slightly smaller")


def paint_pressed(p, rect, turning, radius=None):
    """A pressed *Mine now*'s mark in `rect` (the pill's box, round; or a closed row's icon button, `radius`): its
    ground, then the accent hourglass at `TURNING_SCALE`, turned over to `turning` (0–1; None: still, upright). The box
    keeps its size: only the glyph inside it is smaller."""
    r = QRectF(rect)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c("raised"))
    radius = r.height() / 2 if radius is None else radius
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.translate(r.center())
    p.scale(TURNING_SCALE, TURNING_SCALE)
    if turning is not None:
        p.rotate(180.0 * motion.ease(turning, theme.EASE_IN_OUT))
    icon(p, "waiting", QRectF(-6.5, -6.5, 13, 13), c("accent"))
    p.restore()


def paint_marked(p, rect, turning, place="button"):
    """A press's mark on a file's line (`RowsView.mark_ids`; round 8 row 45, IK-2: a menu's press marks what it acts
    on): the accent arc (the spin's; `turning` its phase, None: still) at the part it was pressed from, `rect`.
    `place`: "button" (⋯, an icon's ▶, a status: its ground, the arc in its middle), "middle" (a cover: a small round
    ground in its middle, the picture left around it), "after" (just right of a link's words: the hero's ↗)."""
    r = QRectF(rect)
    side = min(r.height(), 14.0)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if place == "after":
        box = QRectF(r.right() + 4, r.center().y() - side / 2, side, side)
    elif place == "button":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("raised"))
        radius = theme.RADII["icon-button"]
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        box = QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
    else:
        ground = QRectF(r.center().x() - side, r.center().y() - side, 2 * side, 2 * side)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("raised"))
        p.drawEllipse(ground)
        box = QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
    motion.spin_arc(p, box, turning, c("accent"))
    p.restore()


def paint_sheen(p, r, alpha):
    """The sheen (list-r14m :705): a band of light across `r` at 112°, at `alpha` at its brightest (an opened row's
    head bakes it)."""
    r = QRectF(r)
    x = r.left()
    grad = QLinearGradient(QPointF(x, r.top()), QPointF(x + r.width() * 0.4, r.bottom() + r.width() * 0.16))
    for at, k in ((0.3, 0.0), (0.42, 0.5), (0.46, 1.0), (0.5, 0.5), (0.62, 0.0)):
        grad.setColorAt(at, faded("sheen", alpha * k))
    p.fillRect(r, QBrush(grad))


def stone_tip(ep, state, leaves):
    """A stone's tip, the string's and an opened row's alike (W-1): when a mark takes its words off the list
    (`leaves`: `view_rows.mark_moves_list`), the line that says so."""
    if leaves:
        state += strings.ROWS_STONE_LEAVES
    return strings.ROWS_STONE_TIP.format(label=ep.label, state=state, action=strings.ROWS_STONE_ACTION[ep.watched])


def asked_files(kind, episodes):
    """The files a status's button stands for: *Mine now* the unmined ones in the top waiting on nothing but their
    turn, *Mine this* every unmined one that can be mined, *No video* the unmined ones with none (never one being mined,
    one in Anki, or one whose cards the learner deleted)."""
    open_ = [e for e in episodes if not (e.cards or e.mining or getattr(e, "deleted", False))]
    if kind == "waiting":                           # (an asked one below the line waits too: it goes first again)
        return [e for e in open_ if e.in_top and not e.missing] or [e for e in open_ if not e.missing]
    if kind == "mine":
        return [e for e in open_ if not e.missing]
    with_status = [e for e in open_ if e.status is not None and e.status.kind == "no_media"]
    return with_status or open_


def asks_connect(name, word="video"):
    """Whether a status's button is an ask for Connect (refused while Connect is off): *Mine now* / *Mine this* on a
    video. *No video*'s *Link…* and a non-video item's *Mine this* (the bar says it waits: alpha 4 M1) need no
    Connect, so they work while it is off (P4.1 WF, review IK N2)."""
    return name in ("mine-now", "mine-this") and word == "video"


def action_of(status, episodes, off=None, word="video"):
    """(part name, tip, payload) for a status shown as an icon: a button while Connect may run, its tip naming the
    click; Connect off (`off`: why, `feed.OFF_*`) the same part, its tip saying why nothing happens (an ask only:
    `asks_connect`). `word`: the row's media word — a non-video item's button asks nothing (alpha 4 M1: the bar says it waits).
    Not a button: ("status", its tip, None) — *Not timed* too (its way on is *Mine anyway* in Needs you), so its tip
    names the wait, never a click. A wait on Anki or on the battery is *Mine now* as every *Waiting* is (P4.1's C3
    as amended by Sonic 2026-10-22, M-3 A): its tip, worded by `view_rows`, already says what the click does."""
    if status.kind == "mining":
        return _stop_of(status, episodes, off)
    name = ACTIONS.get(status.kind)
    if status.kind == "waiting" and status.label == view_rows.STRINGS["not_timed"]:
        name = None
    files = asked_files(status.kind, episodes) if name is not None else ()
    said = status_tip(status)
    if not files:
        return "status", said, None
    if off and asks_connect(name, word):
        tip = strings.ROWS_ACTION_OFF.format(tip=said, why=off)
    elif view_rows.names_click(status):
        tip = said                      # a wait on Anki or on the battery: `view_rows` names the click (M-3)
    elif word != "video" and name != "no-media":
        tip = said                      # alpha 4 M1: no *Mine text* (Anki Miner's window): the bar says it waits
    else:
        words = getattr(strings, _ACTION_TIPS[name])
        if name == "no-media" and getattr(status, "moved", None):
            words = strings.ROWS_NO_MEDIA_MOVED_TIP     # MV-2: the click offers *Find its folder…* first
        if isinstance(words, dict):                 # a mining ask: how many files the click asks for (AD-2)
            words = words[len(files) == 1]
        tip = words.format(tip=said, n=len(files))
    return name, tip, Ask(files[0].id, tuple(e.id for e in files), files[0])
# --- end P4.1 L2


# --- R47 (laptop rows 47 + 56): *Stop* on a *Mining* pill. A button only while Connect's job can be stopped
# (`Status.stop`, the feed's `stoppable`) and Connect may run; its file the episode being mined (a row's status is its
# first such episode's). On hover the pill reads *■ Stop*; pressed, *Stopping…* from that frame until the job has
# stopped (`RowsView.press_stop`, `mine_actions.stop`). Past the stop point, a plain status: its hover says so.
def _stop_of(status, episodes, off):
    said = status_tip(status)
    if status.stop is None or off or not episodes:
        return "status", said, None
    ep = next((e for e in episodes if e.status is not None and e.status.stop == status.stop), episodes[0])
    return STOP, strings.ROWS_STOP_TIP.format(tip=said), Ask(ep.id, (ep.id,), ep, status.stop)


def paint_stop(p, rect, stopping, turning=None, radius=None, dpr=1.0, ground="surface"):
    """R47: a *Mining* pill's Stop over `rect` (its box, kept: nothing moves) — on hover *■ Stop*, pressed *Stopping…*
    with the mining glyph turning (`turning` 0–1; None: still). Too narrow for words (a closed row's icon at rest): the
    glyph alone (■, or the turning one). `ground`: the colour under the pill (the mining pill's own is see-through)."""
    f = fz()
    r = QRectF(rect)
    col = style.colours()
    colour = style.qcolor(col["accent"])
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    radius = r.height() / 2 if radius is None else radius
    p.setBrush(c(ground))
    p.drawRoundedRect(r, radius, radius)
    p.setBrush(style.qcolor(col["status-mining"]))
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    text = strings.ROWS_STOPPING if stopping else strings.ROWS_STOP
    pad = 9 * f
    wide = r.width() > r.height() * 1.6             # a pill with words (a closed row's icon is about square)
    ic = QRectF(r.x() + pad, r.center().y() - 6.5, 13, 13) if wide else \
        QRectF(r.center().x() - 6.5, r.center().y() - 6.5, 13, 13)
    if stopping:
        p.save()
        p.translate(ic.center())
        if turning is not None:
            p.rotate(360.0 * turning)
        icon(p, "mining", QRectF(-6.5, -6.5, 13, 13), colour)
        p.restore()
    else:
        p.setBrush(colour)
        side = 8 * f
        p.drawRoundedRect(QRectF(ic.center().x() - side / 2, ic.center().y() - side / 2, side, side), 1.5, 1.5)
    if wide:
        TEXT.draw(p, ic.right() + 6 * f, r.center().y(), text, "status-pill", r.right() - ic.right() - 6 * f - pad / 2,
                  colour, dpr=dpr)
    p.restore()
# --- end R47


def pill_text(status):
    """The words a pill shows. Laptop row 36's sibling, row 38 ("i don't need the words 'waiting' only the icon. It
    should tell you what it means when hover"): every *Waiting* is its icon alone — a k/n count stays, being no word —
    and says itself in its hover (`status_tip`). *Not timed* keeps its words: it asks for the learner, it doesn't wait."""
    if status.kind == "asked":                     # R47: the pressed mark, still — its hover names it
        return ""
    if status.kind != "waiting" or status.label == view_rows.STRINGS["not_timed"]:
        return status.label
    return status.label.replace(view_rows.STRINGS["waiting"], "").strip(" ·")


def status_tip(status):
    """A status's hover: what it is first when its pill doesn't say it (row 38: *Waiting*'s icon alone), then its tip."""
    if pill_text(status) == status.label:
        return status.tip
    return strings.ROWS_WAITING_TIP.format(label=status.label, tip=status.tip)


def pill_size(status, dpr=1.0):
    f = fz()
    text = pill_text(status)
    pad = 8 if status.kind == "no_media" else 9
    if not text:                                    # row 38: the icon alone, in a round pill
        h = round(theme.SIZES["status-pill"] * f)
        return QSize(max(h, round(13 + 12 * f)), h)
    w_text = TEXT.metrics("status-pill", dpr=dpr).horizontalAdvance(text)
    return QSize(round(pad * 2 * f + 13 + 6 * f + w_text), round(theme.SIZES["status-pill"] * f))


def heard_title(row):
    """a5-2 (Hon): a title as painted — 🎧 before it when the row holds an audiobook (`Row.audio`, its hover)."""
    return f"{HEADPHONES}{row.title}" if getattr(row, "audio", "") else row.title


def _audio_part(row, rect, role):
    """a5-2: the 🎧 before a title as a part of its own, its hover the audiobook's words ([] for a row without one)."""
    if not getattr(row, "audio", ""):
        return []
    w = TEXT.metrics(role).horizontalAdvance(HEADPHONES)
    return [("audio", QRect(rect.left(), rect.top(), w, rect.height()), row.audio, None)]


def paint_pill(p, status, rect, dpr=1.0, audio=False):
    """The one status pill (mock `stHTML`): its glyph (No audio's a struck speaker, the others' a struck camera, as
    the mock's `noIco`), its label, its look by tone. R47: an *Asked* one is the pressed mark, still."""
    if status.kind == "asked":
        paint_pressed(p, rect, None)
        return
    f = fz()
    col = style.colours()
    r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
    radius = r.height() / 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    tone = status.tone
    ink = {"ok": "ok", "accent": "accent", "dim": "ink-dim", "ink": "ink", "faint": "ink-faint", "warn": "warn"}[tone]
    if status.kind == "in_anki":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(col["status-in"]))
        p.drawRoundedRect(r, radius, radius)
    elif status.kind == "mining":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(col["status-mining"]))
        p.drawRoundedRect(r, radius, radius)
    elif status.kind == "waiting":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(col["raised"]))
        p.drawRoundedRect(r, radius, radius)
    elif status.kind == "mine_rest":
        p.setPen(QPen(style.qcolor(col["status-part-ring"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, radius, radius)
    elif status.kind in ("mine", "deleted", "no_subs"):
        p.setPen(QPen(style.qcolor(col["line-hi"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, radius, radius)
    elif status.kind == "no_media":
        pen = QPen(style.qcolor(col["status-nomedia-border"] if tone == "warn" else col["line-hi"]), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, radius, radius)
    pad = (8 if status.kind == "no_media" else 9) * f
    text = pill_text(status)
    if text:
        ic = QRectF(rect.x() + pad, rect.center().y() - 6.5, 13, 13)
    else:                                           # row 38: the icon alone, centred
        ic = QRectF(rect.center().x() - 6.5, rect.center().y() - 6.5, 13, 13)
    colour = style.qcolor(col[ink])
    kind = STATUS_ICON.get(status.kind, "dot")
    icon(p, "no_audio" if audio and kind == "no_media" else kind, ic, colour)
    if text:
        TEXT.draw(p, ic.right() + 6 * f, rect.center().y(), text, "status-pill", rect.right() - ic.right() - 6 * f,
                  colour, dpr=dpr)
    p.restore()


def paint_mark(p, mark, right, y_mid, dpr=1.0, audio=False):
    """The on-disk mark (a struck camera or speaker, then N) ending at `right`; -> its rect."""
    f = fz()
    col = style.colours()
    colour = style.qcolor(col["warn"] if mark.tone == "warn" else col["ink-faint"])
    label = str(mark.count) if mark.count > 1 else ""
    w_text = TEXT.metrics("disk-mark", dpr=dpr).horizontalAdvance(label) if label else 0
    w = round(5 * f * 2 + 14 + (3 + w_text if label else 0))
    h = round(22 * f)
    rect = QRect(round(right - w), round(y_mid - h / 2), w, h)
    icon(p, "no_audio" if audio else "no_media", QRectF(rect.x() + 5 * f, y_mid - 7, 14, 14), colour)
    if label:
        TEXT.draw(p, rect.x() + 5 * f + 17, y_mid, label, "disk-mark", w_text + 2, colour, dpr=dpr)
    return rect


PCT_INK = {"ok": "ok", "warn": "warn", "plain": "ink"}  # `view_rows.pct_tone` -> its ink (the brief's bands, ✅)


FADED_ALPHA = 0.45                                       # U-1: a kept *N new* (the last plan's), drawn at this much


def paint_diff(p, pct, tone, n_new, right, y_mid, dpr=1.0, new_faded=False):
    """*94% · 138 new* in fixed tabular slots, right-aligned at `right` (G1.6 #3: the numbers line up row to row).
    `new_faded` (U-1): the figure and its word faded — the last plan's, kept while the plan can't be followed."""
    f = fz()
    col = style.colours()
    fm = TEXT.metrics("diff", dpr=dpr)
    zero = fm.horizontalAdvance("0")
    pct_w, dot_w, cnt_w = 4.6 * zero, 1.8 * zero, 3.3 * zero
    new_txt = strings.ROWS_NEW_WORD
    new_w = fm.horizontalAdvance(" " + new_txt)
    x = right - new_w
    pct_colour = c(PCT_INK[tone])                       # the % bands: >= 97 ok, 93–96 ink (S11), < 93 warn
    dim = style.qcolor(col["ink-dim"])
    # Laptop row 36: a number or nothing — never a placeholder that sits ("— new" never filled on an i+1 plan). The %
    # keeps its slot either way, so the column still lines up row to row.
    if n_new is not None:
        word = faded("ink-dim", FADED_ALPHA) if new_faded else dim
        ink = faded("ink", FADED_ALPHA) if new_faded else style.qcolor(col["ink"])
        TEXT.draw(p, x, y_mid, " " + new_txt, "diff", new_w + 2, word, dpr=dpr)
        TEXT.draw(p, x - cnt_w, y_mid, str(n_new), "diff", cnt_w, ink, weight=600, align="right", dpr=dpr)
        if pct is not None:                             # (no % beside it: no dot hanging)
            TEXT.draw(p, x - cnt_w - dot_w, y_mid, strings.ROWS_DOT, "diff", dot_w, dim, align="centre", dpr=dpr)
    x -= cnt_w + dot_w
    if pct is not None:
        TEXT.draw(p, x - pct_w, y_mid, strings.ROWS_PCT.format(pct=round(pct)), "diff", pct_w, pct_colour,
                  align="right", dpr=dpr)


# --- the model ------------------------------------------------------------------------------------------------------ #
class RowsModel(QAbstractListModel):
    """Entries `(kind, payload, lines_after)`; a refresh keeps the scroll place: the same keys → the payloads swapped
    in place (one repaint), else a reset the view puts back at the same row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.keys = []
        self.open_key = None
        self.changed = []                           # rows a "same" refresh changed
        self.before = []                            # the entries before it (`looks_different`)
        self.came, self.gone = [], []               # a4: a "spliced" refresh's places put in (new) and taken out (old)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        kind, payload, _lines = self.entries[index.row()]
        if role == ROW_ROLE:
            return self.entries[index.row()]
        if role == KIND_ROLE:
            return kind
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            if kind in (HERO, ROW, FINISHED):
                return payload.accessible if role == Qt.ItemDataRole.AccessibleTextRole else payload.title
            if kind == MONTH:
                return payload
            if kind == NEED:
                return payload.title
            if kind == FAILURE:
                return payload.text
            if kind == EMPTY:
                return payload[0]
        if role == Qt.ItemDataRole.AccessibleDescriptionRole:
            if kind in (HERO, ROW):                 # its line, and its string read as words (Q6): the reader's plan
                plan = payload.string[0] if payload.string is not None else stone_plan.plan_of(payload)
                text = strings.ROWS_ACCESSIBLE_STRING.format(line=payload.description, string=stone_plan.words(
                    plan, strings.STRING_WORDS))
                # --- P4.1 L2: a status that is a button says how the keyboard presses it (none while Connect is off);
                # Up Next's head carries its row's own status, as every row (Q33)
                st = payload.status
                if st is not None:
                    name = action_of(st, payload.episodes, None, payload.media_word)[0]
                    view = self.parent()
                    off = getattr(view, "connect_off", None) and asks_connect(name, payload.media_word)
                    if name == STOP and (getattr(view, "connect_off", None) or     # R47-A4: no Stop while off, or
                                         getattr(view, "stopping", lambda _e: False)(payload.episodes)):   # pressed
                        off = True
                    if name in ACTION_NAMES and not off:
                        text += " · " + strings.ROWS_ACTION_KEY.format(action=strings.ROWS_ACTION_NAMES[name])
                return text                                 # --- end P4.1 L2
            if kind == FINISHED:
                return payload.description
            if kind == NEED:
                return payload.line
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        kind = self.entries[index.row()][0]
        if kind in (MONTH, EMPTY):
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    @staticmethod
    def key_of(entry):
        kind, payload, _lines = entry
        if kind in (HERO, ROW, FINISHED):
            return (kind, payload.key)
        if kind == NEED:
            return (kind, payload.key)
        return (kind, str(payload))

    def shape_of(self, entry):
        """What decides an entry's height — the delegate's own rule (`RowDelegate._shape`): its kind, its lines, open or
        not, and an open row's episodes. A closed Current row is one line however many files it holds, so a file joining
        it is a "same" refresh (review D-3) — and since its stones show (W3.1a B3), that row alone is painted again
        (`looks_different`), never a relayout of every row."""
        return RowDelegate._shape(entry, self.open_key is not None and
                                  self.open_key == getattr(entry[1], "key", None))

    def looks_different(self, i):
        """Whether changed row `i` paints differently from before the last "same" refresh: a closed row rebuilt with
        nothing it shows changed (`_same_face`) is no repaint (S19). The view asks it for the rows on screen and those
        painted ahead only: a row further off is checked by `_sprite` when it comes into view (review D-1: comparing
        every changed row cost ~6 ms on the window's thread after a numbers version at 2,000 rows)."""
        old, new = self.before[i], self.entries[i]
        if old[0] != new[0] or old[2] != new[2]:
            return True
        if new[0] in (MONTH, EMPTY):                 # a4: a month's label or the empty line, made anew each build
            return old[1] != new[1]
        return not (new[0] in (HERO, ROW, FINISHED) and getattr(new[1], "key", None) != self.open_key and
                    _same_face(old[1], new[1], new[0]))

    def set_entries(self, entries):
        """-> "same" (payloads swapped in place: the changed rows repaint, `self.changed`), "moved" (the same rows in
        another order, every place as tall as before: swapped in place too, `self.changed` the span the move touched —
        no reset, no relayout: W3.1a S3, a drop), "relayout" (same keys, another height somewhere — or a move whose lines
        moved inside its span, C3: swapped in place, `self.changed` its span) or "reset"."""
        keys = [self.key_of(e) for e in entries]
        if keys == self.keys and entries:
            old = self.entries
            shapes = [self.shape_of(e) for e in old] == [self.shape_of(e) for e in entries]
            self.changed = [i for i, (a, b) in enumerate(zip(old, entries)) if a[1] is not b[1] or a[2] != b[2]]
            self.before = old                       # what `looks_different` compares with
            self.entries = list(entries)
            return "same" if shapes else "relayout"
        moved = self._moved_span(keys, entries)
        if moved is not None:
            (self.changed, relaid), self.before = moved, self.entries
            self.entries, self.keys = list(entries), keys
            return "relayout" if relaid else "moved"
        if self._splice(keys, entries):
            return "spliced"
        # S19's written skip: a reset (rows in another order and rows added or gone at once, a list emptied or filled, a
        # language switch) repaints the screen's rows — Qt's QListView relays out and repaints its viewport on any
        # reset or insert — but from their kept pixmaps (no row drawn afresh: `_same_face`)
        self.beginResetModel()
        self.changed, self.before = [], []
        self.entries = list(entries)
        self.keys = keys
        if self.open_key is not None and not any(k[1] == self.open_key for k in keys):
            self.open_key = None
        self.endResetModel()
        return "reset"

    def _splice(self, keys, entries):
        """a4 (A2): rows added or gone, every other row in the order it had — a show landing at Soon's end, a piece
        leaving for Goal, Up Next handing its place on (its row comes down, a row goes up: both are the hero's and a
        row's own keys) — taken out and put in where they are (`beginRemoveRows` / `beginInsertRows`), never a reset:
        the current row, the hand's row, the open row and the picks stay on their rows. Qt's QListView still lays every
        row out again after an insert (`QListView::rowsInserted`), each height a look in the delegate's kept list, and
        repaints the screen from kept pixmaps. `self.changed`: the new rows and the kept ones rebuilt (a "same"
        refresh's rule); `self.came` / `self.gone`: the places put in (new) and taken out (old). -> True, or None (rows
        reordered too: a reset)."""
        old = self.keys
        if not old or not keys:
            return None
        new_set, old_set = set(keys), set(old)
        if len(new_set) != len(keys) or len(old_set) != len(old):
            return None                                 # a key twice: no row to keep it on
        kept = [k for k in old if k in new_set]
        if not kept or kept != [k for k in keys if k in old_set]:
            return None                                 # no row kept (another language's list), or in another order
        gone = [i for i, k in enumerate(old) if k not in new_set]
        came = [i for i, k in enumerate(keys) if k not in old_set]
        if not gone and not came:
            return None
        root = QModelIndex()
        for a, b in reversed(_runs(gone)):              # from the bottom: the places above stay as they were
            self.beginRemoveRows(root, a, b)
            self.entries = self.entries[:a] + self.entries[b + 1:]      # a new list each step (the delegate's heights
            self.keys = self.keys[:a] + self.keys[b + 1:]               # are kept by the list's identity)
            self.endRemoveRows()
        for a, b in _runs(came):                        # from the top: each run where it stands in the new order
            self.beginInsertRows(root, a, b)
            self.entries = self.entries[:a] + list(entries[a:b + 1]) + self.entries[a:]
            self.keys = self.keys[:a] + keys[a:b + 1] + self.keys[a:]
            self.endInsertRows()
        new = set(came)
        before = self.entries                           # the kept rows' old entries, in their new places
        self.changed = [i for i, (x, y) in enumerate(zip(before, entries))
                        if i in new or x[1] is not y[1] or x[2] != y[2]]
        self.before = before
        self.came, self.gone = came, gone
        self.entries, self.keys = list(entries), keys
        if self.open_key is not None and not any(k[1] == self.open_key for k in keys):
            self.open_key = None
        return True

    def _moved_span(self, keys, entries):
        """A reorder that keeps every place's height: the same rows (by their own key — Up Next's row coming down is
        the same row), each place the same shape as before (`shape_of`: kind, lines, open) — then the places whose row
        changed, first to last (what a drop moved: the rows between its two ends shift by one), and any other place
        whose entry changed as a "same" refresh would list it, and whether lines moved (C3, R3-S6: a drop across the
        top-20 or Soon line moves that line inside the span — the places relaid out, never a reset). Else None."""
        old = self.keys
        if len(keys) != len(old) or not keys:
            return None
        lo = next((i for i, (a, b) in enumerate(zip(old, keys)) if a != b), None)
        if lo is None:
            return None
        hi = next(i for i in range(len(keys) - 1, -1, -1) if old[i] != keys[i])
        if sorted(k[1] for k in old[lo:hi + 1]) != sorted(k[1] for k in keys[lo:hi + 1]):
            return None                             # a row came or went: not a move
        before = self.entries
        relaid = False
        for i in range(len(entries)):
            a, b = self.shape_of(before[i]), self.shape_of(entries[i])
            if a != b:                              # (kind, lines, open, episodes): only the lines may differ, inside
                if not lo <= i <= hi or a[0] != b[0] or a[2:] != b[2:]:
                    return None
                relaid = True
        if relaid and sum(len(e[2]) for e in before[lo:hi + 1]) != sum(len(e[2]) for e in entries[lo:hi + 1]):
            return None                             # a line came or went: not lines moving
        return [i for i, (a, b) in enumerate(zip(before, entries))
                if lo <= i <= hi or a[1] is not b[1] or a[2] != b[2]], relaid


def _runs(places):
    """Sorted places as runs of neighbours: [2, 3, 4, 9] -> [(2, 4), (9, 9)]."""
    out = []
    for i in places:
        if out and out[-1][1] == i - 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


# --- the delegate: geometry, painting, hit-testing ----------------------------------------------------------------- #
GRIP = 12                                            # Finished: the grip's column it leaves out (`lead`)
EP_LABEL_IN = 12 + 20 + 12                           # an episode's label from its rule: a gap, its stone, a gap
# --- W3.2 Q6: the opened row's standing cover: 64 × 96 (× the text size), 8 px in, 6 px under its head — left of the
# episodes' stones at every text size (they start 32 px before the art's right edge, the art ≥ 92 × the text size)
STAND_W, STAND_IN, STAND_TOP = 64, 8, 6
# --- end W3.2 Q6
SPRITES_KEPT = 64                                    # painted rows kept (~0.7 MB each at 150 %, a 1,280 px window)
EPISODES_KEPT = 64                                   # painted episode rows, kept apart: opening rows never pushes rows out
SPRITE_MB = {"row": 64, "ep": 16}                    # and by bytes, per list: a row is ~2 MB at 250 % (W2.2 review B-2)
WARM_AHEAD = 8                                       # rows past each edge of the screen painted ahead, in idle moments
WARM_IDLE_MS = 250                                   # how long the list rests (no scroll, no refresh) before it does —
#                                                      longer than the gap between a wheel's notches (review B-8)
HOVER_WARM_MS = 120                                  # the pointer rests this long on a row: its episodes painted ahead
# rows and episodes painted once into pixmaps and reused (on), or drawn afresh on every paint (off: the bench's A/B,
# review IK-30 — the consult's T7 / R2 warn against whole-row pictures; bench 10 measures both)
ROW_PIXMAPS = os.environ.get("SURASURA_ROW_PIXMAPS") != "0"


def _size(pix):
    return pix.width() * pix.height() * 4


# What a closed row's or an episode's pixmap never shows: a new object that differs from the kept one only here looks
# the same, so its pixmap is kept (Sonic's S19, 2026-10-08: nothing visible changed, nothing redrawn). A row in another
# place (`_replace(index=…)`: its number is drawn over the pixmap, `_paint_number`). A Current row's episodes **are**
# shown since W3.1a — its string, one stone per file (B3): a file watched, in Anki, joining or removed repaints that
# row; an episode's place in the top dims its stone. Finished's rows show no episodes (today's layout). The hero (a4,
# S19 on every page: compared by identity alone, a view built afresh with nothing changed drew it again) shows no number
# and none of its words for screen readers.
_UNSHOWN = {ROW: frozenset(("index", "accessible", "description")),
            HERO: frozenset(("index", "accessible", "description")),
            FINISHED: frozenset(("index", "episodes", "accessible", "description")),
            "ep": frozenset(("rel_path", "ask"))}         # row 55: ▶'s ask is never painted (`can_play` is)
_UNSHOWN[FINISHED] = _UNSHOWN[FINISHED] | {"cards_out"}      # --- W3.2 Q4: ⋯'s state, never painted
_UNSHOWN[FINISHED] = _UNSHOWN[FINISHED] | {"new_faded"}      # --- U-1 (U-A5): a Finished row paints no *N new*


def _same_face(old, new, kind):
    """Whether `new` would paint exactly as `old`: the same type, and every field the pixmap shows equal."""
    unshown = _UNSHOWN.get(kind)
    fields = getattr(new, "_fields", None)
    if unshown is None or fields is None or type(old) is not type(new):
        return False
    return all(a is b or a == b for name, a, b in zip(fields, old, new) if name not in unshown)


class RowDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.paints = 0                              # rows painted (tests: only what's on screen)
        self.renders = 0                             # rows drawn into a pixmap (tests: a repaint reuses them)
        self.warmed = 0                              # rows drawn ahead, before they came on screen (`warm`)
        self._warming = False
        self._sprites = {"row": OrderedDict(), "ep": OrderedDict()}     # two caches: episodes never evict rows
        self._hints = {}                             # an entry's shape -> its QSize, for `_hints_look` (`sizeHint`)
        self._hints_look = None
        self._model = view.model()                   # the list's own model, set before its delegate (`RowsView`)
        self._heights, self._h_entries, self._h_open, self._h_look = [], None, None, None
        self._bytes = {"row": 0, "ep": 0}
        self._infos, self._infos_look = {}, None     # a Current row's key -> its string's plan and needs (`_info`)
        self._eps_at = None                          # LM11b H-W2: `episode_at`'s (row, rect, lines, its lines, look)
        self._stat_ws = {}                           # what shows right of a string -> its width, this look (`_info`)
        self._tw = None                              # (the reader's needs or the entries, width, look, the one title
        #                                              width) (`title_w`)

    def _sprite(self, kind, payload, size, dpr, hovered, draw, ident=None, ground="bg", to=None, spare=False,
                extra=None):
        """A closed row painted once into a pixmap (on the list's own ground, so text keeps its subpixel smoothing) and
        reused while the row object, its width and height, the screen's ratio, the look and the hover are the same.
        The reader keeps an unchanged row the same object between builds, so a refresh repaints from these. Its lines
        (the top-20 and Soon lines) are drawn outside it, so a line that moves re-renders nothing (review B-13).
        `extra`: the rest of what the picture depends on (a Current row's title width; whether the stones' sheet was
        there — a tuple whose last item says so: a picture painted before it is let go when it lands, `drop_unsheeted`)."""
        if not ROW_PIXMAPS and to is not None:      # the A/B's other arm: drawn where it stands, nothing kept
            q, at = to
            q.save()
            q.translate(at)
            q.fillRect(QRect(0, 0, size.width(), size.height()), c(ground))
            draw(q)
            q.restore()
            self.renders += 1
            return None
        name = "ep" if kind == "ep" else "row"
        cache, kept = self._sprites[name], EPISODES_KEPT if kind == "ep" else SPRITES_KEPT
        key = (kind, payload.key if ident is None else ident, size.width(), size.height(), dpr, style.current(),
               hovered, extra)
        hit = cache.get(key)
        if hit is not None and (hit[0] is payload or _same_face(hit[0], payload, kind)):
            if hit[0] is not payload:
                cache[key] = (payload, hit[1])           # the moved row: the next look is by identity again
            if not spare:                                # a guess looked at again ahead stays first to go (D-4)
                cache.move_to_end(key)
            return hit[1]
        if spare and (len(cache) >= kept or self._bytes[name] + round(size.width() * dpr) * round(size.height() * dpr)
                      * 4 > SPRITE_MB[name] * 1024 * 1024):
            return None                              # a guess drawn ahead takes only free room: it never evicts (D-4)
        pix = QPixmap(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(c(ground))
        q = QPainter(pix)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        draw(q)
        q.end()
        if self._warming:
            self.warmed += 1
        else:
            self.renders += 1
        old = cache.pop(key, None)
        if old is not None:
            self._bytes[name] -= _size(old[1])
        cache[key] = (payload, pix)
        if spare:
            cache.move_to_end(key, last=False)       # ... and is the first to go when a row needs the room
        self._bytes[name] += _size(pix)
        cap = SPRITE_MB[name] * 1024 * 1024
        while len(cache) > 1 and (len(cache) > kept or self._bytes[name] > cap):
            self._bytes[name] -= _size(cache.popitem(last=False)[1][1])
        return pix

    # sizes ------------------------------------------------------------------------------------------------------ #
    @staticmethod
    def _lines_h(lines):
        """The strips after a row its lines take: each a groove's own few px in the gap (W3.1a: really subtle)."""
        return len(lines) * rl("line")

    def _entry(self, index):
        """The entry at `index`, read from the model's list (no trip through a QVariant: `index.data(ROW_ROLE)` costs
        a conversion each way, and a relayout asks every row)."""
        entries = self.view.model().entries
        row = index.row()
        return entries[row] if 0 <= row < len(entries) else None

    def sizeHint(self, option, index):
        """An entry's height: a relayout (a row opened, a file arrived) asks every row, one call each from Qt, so each
        answer is one look in a list made once per entries, open row and look (`_heights_now`); a call that does any
        more is paid a few hundred times (W2.2 speed round 5: 1.4 ms of an opening's ~3.5)."""
        model = self._model
        if model.entries is not self._h_entries or model.open_key != self._h_open or style.current() != self._h_look:
            self._heights_now(model)
        row = index.row()
        heights = self._heights
        return heights[row] if 0 <= row < len(heights) else QSize(0, 0)

    def same_heights(self, old_entries, new_entries):
        """A "same" refresh: every shape is as it was, so the height list made for `old_entries` holds for the new ones
        (review D-2: making it again walked every entry on the window's thread, ~6 ms at 20,000)."""
        if self._h_entries is old_entries:
            self._h_entries = new_entries

    def _heights_now(self, model):
        """Every entry's height, from the sizes kept by what decides them (`_shape`): a refresh makes every entry a new
        tuple and an arrival every row a new object (its number moved), yet only a shape not seen before is worked out
        (`_size_hint`)."""
        look = style.current()
        if look != self._hints_look:                 # a new look: every height again
            self._hints.clear()
            self._hints_look = look
        open_key, hints, shape = model.open_key, self._hints, self._shape
        out = []
        for entry in model.entries:
            is_open = open_key is not None and open_key == getattr(entry[1], "key", None)
            key = shape(entry, is_open)
            size = hints.get(key)
            if size is None:
                size = hints[key] = self._size_hint(entry, is_open)
            out.append(size)
        self._heights, self._h_entries, self._h_open, self._h_look = out, model.entries, open_key, look

    @staticmethod
    def _shape(entry, is_open):
        """What an entry's height is made of (`_size_hint` reads nothing else): its kind, its lines, open or not, and,
        open or a Needs-you item, how many episodes it lists. Closed rows with as many lines under them are as tall."""
        kind, payload, lines = entry
        n = len(payload.episodes) if (is_open and kind in (HERO, ROW)) or kind == NEED else 0
        shows = len(show_starts(payload)) if is_open and kind in (HERO, ROW) else 0     # LM11b: its show lines
        return kind, len(lines), is_open and kind in (HERO, ROW), n, shows

    def _size_hint(self, entry, is_open):
        kind, payload, lines = entry
        f = fz()
        gap = theme.SPACING["list-gap"]
        if kind == HERO:
            h = self._hero_head_h()
            if is_open:
                h += self._episodes_h(payload) + 14
            return QSize(100, h + rl("hero-below") + self._lines_h(lines))
        if kind == ROW:                              # one line at every size, its gap half above, half below
            h = self._line_h()
            if is_open:                              # W3.2 Q6: its standing cover's height at least
                h += max(self._episodes_h(payload), self.stand_h()) + rl("open-pad")
            return QSize(100, h + rl("gap") + self._lines_h(lines))
        if kind == FINISHED:                         # today's layout (C-scope §2.3)
            return QSize(100, round(theme.SIZES["row"] * f) + gap + self._lines_h(lines))
        if kind == MONTH:
            return QSize(100, round(11.5 * f * 1.45 + 20))
        if kind == NEED:
            return QSize(100, round(16 * 2 + 14 * f * 1.45 + 10 + len(payload.episodes) * 34 * f + 2 + 12))
        if kind == FAILURE:
            return QSize(100, round(16 * 2 + 14 * f * 1.45 + 12.5 * f * 1.45 + 4 + 12))
        if kind == EMPTY:
            return QSize(100, round(17 * f * 1.45 + 13 * f * 1.45 + 80))
        return QSize(100, round(theme.SIZES["row"] * f))

    def _episodes_h(self, row):
        """An open row's episode list: 4 px, then one `episode-row` per episode and, in a group, one `show-line` above
        each show's episodes (as `_episode_rows` lays them)."""
        f = fz()
        return 4 + len(row.episodes) * round(theme.SIZES["episode-row"] * f) + \
            len(show_starts(row)) * round(rl("show-line") * f)

    def _hero_text_h(self):
        """Up Next's text column: the eyebrow, the title, the source, the numbers and the string, 5 px apart."""
        f = fz()
        return (11 * f * 1.45 + 21 * f * 1.2 + 12.5 * f * 1.45 + 12.5 * f * 1.45 + rl("hero-string") * f + 4 * 5)

    def _hero_head_h(self):
        return max(theme.SIZES["hero-cover-h"] + 2 * rl("hero-pad-y"), round(self._hero_text_h()) + 2 * rl("hero-pad-y"))

    @staticmethod
    def _line_h():
        """A Current row's one line (60 × the text size)."""
        return round(rl("height") * fz())

    def slab_of(self, rect):
        """A Current row's slab in its entry's `rect`: the gap's half above it (where its lift goes), one line tall."""
        return QRect(rect.left(), rect.top() + rl("gap") // 2, rect.width(), self._line_h())

    # geometry ------------------------------------------------------------------------------------------------ #
    def columns(self, rect, kind=FINISHED):
        """A Finished row's fixed right-hand columns (today's layout, C-scope §2.3; mock `.rowline`): {name: QRect}."""
        f = fz()
        top, h = rect.top(), round(theme.SIZES["row"] * f)
        right = rect.right() - 8
        acts = QRect(round(right - theme.SIZES["col-acts"] * f), top, round(theme.SIZES["col-acts"] * f), h)
        stat = QRect(round(acts.left() - 12 - theme.SIZES["col-stat"] * f), top, round(theme.SIZES["col-stat"] * f), h)
        date = QRect(round(stat.left() - 12 - 64 * f), top, round(64 * f), h)
        return {"acts": acts, "stat": stat, "date": date,
                "text_right": date.left() - round(theme.SIZES["title-to-number"] * f)}

    @staticmethod
    def lead(kind, left):
        """The left of a Finished row (mock `.rowline`): (its number's empty slot, its cover, its title) x — no grip and
        no number, so its cover sits near the edge (G2.3: matched to the mock's captures)."""
        f = fz()
        number = left + 4
        cover_x = number + round(20 * f) + 12
        return number, cover_x, cover_x + round(theme.SIZES["row-cover-w"] * f) + 12      # 13 past the cover's last px

    # a Current row's one line (W3.1a §1 *Rows*; list-r14m `.row.lr .rowline`) ---------------------------------------- #
    def _art_w(self, width):
        """The wide art: 10 % of the list's width, between `art-min` and `art-max` (× the text size)."""
        f = fz()
        return round(min(max(rl("art-min") * f, width * rl("art-share")), rl("art-max") * f))

    def _fixed_w(self, width, stat_w):
        """Everything on a row's line but its title and its string: the number, the art, the gaps, the Anki count, the
        % · new column and the right padding (the flex row's items: `gap-x` between each, `string-in` before the
        string; the hover group holds no room)."""
        f, g = fz(), rl("gap-x")
        return (round(rl("pos") * f) + self._art_w(width) + g + g + rl("string-in") + g + stat_w + g +
                round(rl("diff") * f) + rl("pad-right"))

    @staticmethod
    def _stat_w(status):
        """What a row shows at rest right of its string (list-r14m `.rt .stat`): the Anki count (its mark and N), or
        mining's icon; nothing else, so 0 for every other status."""
        if status is None:
            return 0
        if status.kind == "in_anki":
            return round(2 + rl("anki-icon") + 5 + TEXT.metrics("status-pill", 700).horizontalAdvance(status.label) + 2)
        if status.kind == "mining":
            return round(rl("icon-w") * fz())
        return 0

    def _stat_w_of(self, kind):
        """`_stat_w` by what decides it (`view_rows.stat_kind`: the Anki count's label, mining, nothing), kept per look:
        the font is asked once per label, never once per row."""
        look = style.current()
        if look != self._infos_look:
            self._infos.clear()
            self._stat_ws.clear()
            self._infos_look = look
        w = self._stat_ws.get(kind)
        if w is None:
            status = None if kind is None else view_rows.Status("mining", "", "", "") if kind == "mining" else \
                view_rows.Status("in_anki", kind[1], "", "")
            w = self._stat_ws[kind] = self._stat_w(status)
        return w

    def _info(self, row):
        """A Current row's string: (its plan, its need at its tightest now or after its next fuse — px at the string's
        own scale —, the width of its Anki count). The plan and the need are the reader's (`Row.string`, planned off
        this thread once per row content: W3.1a B2); a row without them (a test's own) is planned here, kept by its key
        while its files, next file, media and source are the same."""
        stat_w = self._stat_w_of(view_rows.stat_kind(row.status))
        if row.string is not None:
            return row.string[0], row.string[1], stat_w
        hit = self._infos.get(row.key)
        if hit is not None and hit[0] is row.episodes and hit[1] == (row.next_index, row.media, row.source):
            return hit[2][0], hit[2][1], stat_w
        plan = stone_plan.plan_of(row)
        out = (plan, max(stone_plan.tightest(plan), stone_plan.ahead(plan)))
        if len(self._infos) > 50000:
            self._infos.clear()
        self._infos[row.key] = (row.episodes, (row.next_index, row.media, row.source), out)
        return out[0], out[1], stat_w

    def _keep_watched(self):
        """W-1: the library's *Keep studying watched episodes*, from the view the list's page shows (off: none)."""
        return bool(getattr(getattr(self.view.parent(), "view_model", None), "keep_watched", False))

    def _worst(self):
        """The reader's answer for the one title width (`View.worst`, `view_rows.worst_needs`): read from the view the
        list's page shows (`Page.view_model`, set before its entries) when these entries are that view's rows — else
        None, and `title_w` walks the rows itself."""
        view = getattr(self.view.parent(), "view_model", None)
        table = getattr(view, "worst", None)
        entries = self._model.entries
        if table is None or not entries or len(view.rows) != len(entries) or entries[0][1] is not view.rows[0] or \
                entries[-1][1] is not view.rows[-1]:
            return None
        return table

    def title_w(self, width):
        """The one title width every Current row shares at this list width (`stone_plan.title_width`): round(187 × the
        text size), narrowed by the row whose string is shortest of room at its tightest (now or after its next fuse),
        never under round(80 × the text size). The string keeps the reference's own px (`stones.FOLLOWS_TEXT_SIZE` is
        False: `string_fz` 1.0). The rows' needs come worked out by the reader, per kind of Anki count (`View.worst`):
        this thread adds each kind's width and takes the largest — a few numbers, never every row (W3.1a B2). Worked out
        once per (that answer, or the list's rows when there is none; its width; the look)."""
        model = self._model
        look = style.current()
        table = self._worst()
        key = model.entries if table is None else table
        hit = self._tw
        if hit is not None and hit[0] is key and hit[1] == width and hit[2] == look:
            return hit[3]
        worst, worst_w, worst_stat = None, -1.0, 0
        if table is not None:
            for kind, (need, plan) in table.items():
                stat_w = self._stat_w_of(kind)
                if need + stat_w > worst_w:          # the row shortest of room: its need and its own Anki count
                    worst, worst_w, worst_stat = plan, need + stat_w, stat_w
        else:
            for kind, row, _lines in model.entries:
                if kind != ROW:
                    continue
                plan, need, stat_w = self._info(row)
                if need + stat_w > worst_w:
                    worst, worst_w, worst_stat = plan, need + stat_w, stat_w
        tw = stone_plan.title_width((worst,) if worst is not None else (), width, fz(),
                                    self._fixed_w(width, worst_stat), string_fz=1.0)
        self._tw = (key, width, look, tw)
        return tw

    def _hover_items(self, row):
        """What a Current row shows over its string's end on hover or keyboard focus (list-r14m `.r11-hb`), in order:
        *Studying its cards first*, its status as its icon (the Anki count and mining show at rest instead), its on-disk
        mark, ▶ and ⋯ -> [(name, glyph, ink, tip, payload, w, h)]. Waiting's icon is the Mine now button (A2 #44); No
        video is a warning, amber when it's in the top 20 (A2 #5, #41)."""
        f = fz()
        iw, ih, b = round(rl("icon-w") * f), round(rl("icon-h") * f), round(rl("button") * f)
        out = []
        if row.studying:
            out.append(("studying", "up", "accent", strings.ROWS_STUDYING_TIP, None, iw, ih))
        st = row.status
        if st is not None and st.kind not in ("in_anki", "mining", "none"):
            name, tip, ask = action_of(st, row.episodes, self.view.connect_off, row.media_word)    # --- P4.1 L2
            if name in ASKS and self.view.pressed(row.episodes):
                tip = strings.ROWS_ASKED_TIP             # round 8 row 45: asked, starting
            if st.kind == "waiting":
                out.append((name, "waiting", "ink-dim", tip, ask, iw, ih))
            elif st.kind == "no_media":
                out.append((name, "warning", "warn" if st.tone == "warn" else "ink-faint", tip, ask, iw, ih))
            else:
                out.append((name, STATUS_ICON.get(st.kind, "mine"),
                            {"ok": "ok", "faint": "ink-faint", "ink": "ink",       # R47-A5: an Asked one, accent
                             "accent": "accent"}.get(st.tone, "ink-dim"), tip, ask, iw,
                            ih))
        if row.mark is not None:
            out.append(("mark", "no_audio" if row.media_word == "audio" else "no_media",
                        "warn" if row.mark.tone == "warn" else "ink-faint", row.mark.tip, None, iw, ih))
        out.append(("play", "play", "ink-dim", row.play_tip, row.episodes[row.next_index], b, b))
        out.append(("more", "more", "ink-dim", strings.ROWS_MORE_TIP, None, b, b))
        return out

    def line_geometry(self, row, slab, tw=None, opened=False):
        """A Current row's one line laid out in its `slab` (list-r14m's flex row: the number, the art — its number's
        −12 margin eats the gap —, the title, the string `string-in` further on, a zero-width anchor where the hover
        group hangs, the Anki count, % · new): {name: QRect}, `hover` [(name, QRect, glyph, ink, tip, payload)] and its
        width `hw`. `opened`: the head of an opened row (its string has dropped into its episode lines)."""
        f, g = fz(), rl("gap-x")
        top, h = slab.top(), slab.height()
        pos = QRect(slab.left(), top, round(rl("pos") * f), h)
        art_r = QRect(pos.right() + 1, top, self._art_w(slab.width()), h)
        if tw is None:
            tw = self.title_w(slab.width())
        right = slab.right() + 1 - rl("pad-right")              # the line's last px + 1
        diff_w = round(rl("diff") * f)
        diff = QRect(right - diff_w, top, diff_w, h)
        stat_w = self._info(row)[2]
        stat = QRect(diff.left() - g - stat_w, top, stat_w, h)
        main = QRect(art_r.right() + 1 + g, top, tw, h)
        end = stat.left() - g                                   # the string's end: the hover group hangs from it
        left = main.right() + 1 + g + rl("string-in")
        gstr = QRect(left, top, max(0, end - left), h)
        mid = top + h / 2
        hover, x = [], end
        for name, glyph, ink, tip, payload, w, ih in reversed(self._hover_items(row)):
            r = QRect(x - w, round(mid - ih / 2), w, ih)
            hover.append((name, r, glyph, ink, tip, payload))
            x = r.left() - rl("hover-gap")
        hover.reverse()
        hw = end - hover[0][1].left() + rl("hover-pad")
        mw, mh, mp = rl("mover-w"), rl("mover-h"), rl("mover-pad")
        cx = pos.left() + pos.width() // 2
        if opened:                                              # the full title takes the string's room
            main = QRect(main.left(), top, max(tw, end - hw - g - main.left()), h)
        return {"slab": slab, "pos": pos, "art": art_r, "main": main, "gstr": gstr, "stat": stat, "diff": diff,
                "hover": hover, "hw": hw, "end": end,
                "up": QRect(cx - mw // 2, top + mp, mw, mh), "down": QRect(cx - mw // 2, top + h - mp - mh, mw, mh)}

    @staticmethod
    def _stone_what(item, gem, big=False):
        """A plan's item as the sheet names its picture (`stones.Sheet`); `big`: every single at the next one's size (Up
        Next's string)."""
        if item.kind == "stone":
            size = "next" if (item.big or big) else "watched" if item.state == "cut" else "waiting"
            return ("stone", item.state, gem, item.variant % stones.VARIANTS, size)
        if item.kind == "tier":
            return ("group", gem, item.n)
        return ("ore", gem, stones.size_bucket(item.n), item.mined_step, 1 if item.cut_points else 0)

    def _stone_parts(self, row, plan, room, mid, big=False):
        """The single stones of a string, as parts: a click on one is a Done for its file (S12; list-r14m's hit areas
        26 × 30)."""
        out = []
        lay = stone_plan.layout(plan, room.width(), 1.0)
        for item, x in zip(plan.items, lay.xs):
            if item.kind != "stone" or room.left() + x > room.right():
                continue
            ep = row.episodes[item.index]
            state = strings.ROWS_STONE_STATE[item.state].format(n=ep.cards)
            if ep.missing:
                state += strings.ROWS_STONE_MISSING.format(word=ep.media_word or row.media_word)   # LM11b G1
            tip = stone_tip(ep, state, view_rows.mark_moves_list(row.tier, ep, self._keep_watched()))
            out.append(("stone", QRect(round(room.left() + x - 13), round(mid - 15), 26, 30), tip, ep))
        return out

    def parts(self, entry, rect):
        """Every hit-testable part of an entry: [(name, QRect, tooltip, payload)] — the view's tooltips and clicks. A
        part listed first wins where two overlap (the hover group over the string's end; ↑ ↓ over the number)."""
        kind, payload, lines = entry
        out = []
        f = fz()
        if kind == HERO:
            g = self._hero_geometry(payload, rect, lines)
            nxt = payload.episodes[payload.next_index]
            out.append(("play" if nxt.can_play else "no-play", g["play"], payload.play_tip, nxt))   # row 55
            all_tip = strings.ROWS_DONE_ALL_MIX_TIP if payload.source == "hato" else strings.ROWS_DONE_ALL_TIP
            out.append(("done", g["done"], all_tip if nxt.watched else
                        strings.ROWS_DONE_TIP.format(ep=nxt.label), nxt))
            out.append(("more", g["more"], strings.ROWS_MORE_TIP, None))
            if payload.status is not None:                 # --- P4.1 L2: the row's status, a button as a row's (Q33)
                out.append(self._status_part(payload, payload.episodes, g["status"], payload.media_word))
            if g["journey"] is not None:
                out.append(("journey", g["journey"], strings.ROWS_JOURNEY_TIP, nxt))
            is_open = self.view.model().open_key == payload.key
            if not is_open and self._sheet_there() and not view_rows.audio_only(payload):    # G16 / L4; a5-2
                s = g["string"]
                out += self._stone_parts(payload, self._info(payload)[0], s, s.top() + s.height() / 2, big=True)
            out += _audio_part(payload, g["title"], "hero-title")                   # a5-2
            out.append(("title", g["title"], payload.title, None))
            if is_open:
                out += self._episode_parts(payload, g["eps"], hero=True)
                out += self._seam_parts(payload, g["eps"], hero=True)       # --- W3.2 Q8
            out.append(("open", g["main"], None, None))
        elif kind == ROW:
            slab = self.slab_of(rect)
            is_open = self.view.model().open_key == payload.key
            g = self.line_geometry(payload, slab, opened=is_open)
            for name, r, _glyph, _ink, tip, pl in g["hover"]:
                if name == "play" and pl is not None and not pl.can_play:
                    continue                             # row 55: nothing to open, no ▶ (its column stays: IK-6)
                out.append((name, r, tip, pl))
            out.append(("up", g["up"], strings.ROWS_MOVE_TIP["up"], None))
            out.append(("down", g["down"], strings.ROWS_MOVE_TIP["down"], None))
            if not is_open and self._sheet_there() and not view_rows.audio_only(payload):  # L4: a stone is hit
                out += self._stone_parts(payload, self._info(payload)[0], g["gstr"],     # only where it is drawn
                                         slab.top() + slab.height() / 2)
            if g["stat"].width():                    # R47: mining's icon is its Stop while the job can be stopped
                out.append(self._status_part(payload, payload.episodes, g["stat"], payload.media_word))
            out += _audio_part(payload, g["main"], "row-title")                     # a5-2
            out.append(("title", QRect(slab.left(), slab.top(), g["main"].right() - slab.left() + 1, slab.height()),
                        payload.title + ("\n" + payload.line if payload.line else ""), None))
            if is_open:
                area = self._open_area(rect, slab)
                out += self._episode_parts(payload, area)
                out += self._seam_parts(payload, area)                       # --- W3.2 Q8
            out.append(("open", slab, None, None))
        elif kind == FINISHED:
            h = round(theme.SIZES["row"] * f)
            row_line = QRect(rect.left(), rect.top(), rect.width(), h)
            cols = self.columns(row_line, kind)
            st_rect, _mk = self._status_rects(payload, cols["stat"])
            if payload.status is None or payload.status.kind not in ("in_anki", "mining"):
                st_rect = None                         # Finished: only Mining… / ✓ N (words in its tip), no mark
            if st_rect is not None:
                out.append(("status", st_rect, status_tip(payload.status), None))
            if payload.studying:
                x0 = self.lead(kind, row_line.left())[2]
                out.append(("studying", QRect(x0, row_line.center().y(), self._studying_w(), round(19 * f) + 4),
                            strings.ROWS_STUDYING_TIP, None))
            # --- W3.2 Q4: Put back and ⋯ in the actions' column (shown on hover and keyboard focus alike)
            back, more = self.finished_acts(cols["acts"])
            out.append(("put-back", back, strings.FIN_PUT_BACK_TIP, None))
            out.append(("more", more, strings.FIN_MORE_TIP, None))
            # --- end W3.2 Q4
            out.append(("title", QRect(row_line.left(), row_line.top(), cols["text_right"] - row_line.left(), h),
                        payload.title + ("\n" + payload.line if payload.line else ""), None))
            out.append(("open", row_line, None, None))
        elif kind == NEED:                             # its line lives in the tooltip (G2.3 N1: the card stays clean)
            out.append(("title", rect, payload.title + ("\n" + payload.line if payload.line else ""), None))
        out = self._line_parts(lines, rect) + out      # a line's hover area overlaps its rows' edges: it wins there
        return out

    @staticmethod
    def _open_area(rect, slab):
        """An opened Current row's episodes' area: under its slab."""
        return QRect(rect.left(), slab.bottom() + 1, rect.width(), rect.bottom() - slab.bottom())

    def episode_at(self, entry, rect, pos):
        """The episode of an opened Current row (or Up Next) whose line `pos` (the viewport's) is on, else None (LM11b
        G2: a drop on an opened group's episode lands after it)."""
        kind, payload, lines = entry
        if kind not in (HERO, ROW) or self.view.model().open_key != payload.key:
            return None
        hit, look = self._eps_at, style.current()    # H-W2 (S19): asked on every move of a drag's hand — the row's
        if hit is not None and hit[0] is payload and hit[1] == rect and hit[2] is lines and hit[4] == look:
            eps = hit[3]                             # lines kept while the same row stands in the same rect
        else:
            if kind == HERO:
                eps = self._episode_rows(payload, self._hero_geometry(payload, rect, lines)["eps"], hero=True)
            else:
                eps = self._episode_rows(payload, self._open_area(rect, self.slab_of(rect)))
            self._eps_at = (payload, QRect(rect), lines, eps, look)
        return next((ep for r, ep in eps if r.top() <= pos.y() <= r.bottom()), None)

    def episode_lines(self, entry, rect):
        """An opened Current row's (or Up Next's) episode lines where `rect` lays them: [(QRect, Episode)]."""
        kind, payload, lines = entry
        if kind == HERO:
            return self._episode_rows(payload, self._hero_geometry(payload, rect, lines)["eps"], hero=True)
        return self._episode_rows(payload, self._open_area(rect, self.slab_of(rect)))

    def _sheet_there(self):
        """Whether the stones' sheet is there to draw a string from (L4: until it lands — or all session, if its build
        failed — a row paints no stone, so none can be clicked: a click on the bare string opens the row)."""
        return stones.get(self.view.viewport().devicePixelRatioF() or 1.0, style.current()[1]) is not None

    def _line_parts(self, lines, rect):
        """The lines after a row, as parts: each strip's hover area at least `line-hit` tall around its groove (S10),
        reaching into the rows either side; its tip says what it is and where its setting lives."""
        out = []
        y = rect.bottom() + 1 - self._lines_h(lines)
        hit = rl("line-hit")
        for ln in lines:
            mid = y + rl("line") // 2
            where = strings.ROWS_TOP_LINE_WHERE if ln.kind == "top" else strings.ROWS_SOON_LINE_WHERE
            out.append((ln.kind + "-line", QRect(rect.left(), mid - hit // 2, rect.width(), hit), where.format(tip=ln.tip),
                        None))
            y += rl("line")
        return out

    def _status_rects(self, row, stat):
        """A Finished row's status pill in its column (today's layout)."""
        st_rect = mk_rect = None
        y_mid = stat.center().y()
        right = stat.right()
        if row.status is not None and row.status.kind != "none":
            size = pill_size(row.status)
            st_rect = QRect(right - size.width(), round(y_mid - size.height() / 2), size.width(), size.height())
            right = st_rect.left() - 4
        if row.mark is not None:
            f = fz()
            label_w = TEXT.metrics("disk-mark").horizontalAdvance(str(row.mark.count)) if row.mark.count > 1 else 0
            w = round(5 * f * 2 + 14 + (3 + label_w if label_w else 0))
            mk_rect = QRect(right - w, round(y_mid - 11 * f), w, round(22 * f))
        return st_rect, mk_rect

    def _title_x(self, left, width):
        """Where a Current row's title starts (its episodes' labels start there too, G2.3 A2)."""
        return left + round(rl("pos") * fz()) + self._art_w(width) + rl("gap-x")

    def _episode_rows(self, row, area, hero=False):
        """An open row's episodes, one rect each: from its stone's column (a gap, the stone, a gap before the label) to
        the row's own right edge, so an episode's label starts where its show's title does and its numbers and status
        stand in the list's columns (G2.3 A1, A2; `_episode_cols`)."""
        f = fz()
        if hero:
            title_x = area.left() + rl("hero-pad-x") + theme.SIZES["hero-cover-w"] - 1 + rl("hero-gap")  # its main column
        else:
            title_x = self._title_x(area.left(), area.width())
        left = title_x - EP_LABEL_IN
        right = area.right()
        h = round(theme.SIZES["episode-row"] * f)
        y = area.top() + 4
        out = []
        starts = show_starts(row)                    # LM11b: a group's show lines take their room (`_show_lines`)
        sh = round(rl("show-line") * f)
        for k, ep in enumerate(row.episodes):
            if k in starts:
                y += sh
            out.append((QRect(left, y, right - left + 1, h), ep))     # its right is the row's (haiku-code G1: 1 px)
            y += h
        return out

    def _show_lines(self, row, eps):
        """LM11b: an opened group's show lines over `eps` (`_episode_rows`' lines): [(QRect, show)], each in the room
        left right above its show's first episode — so `_episode_rows` lists episodes only, as its callers expect."""
        starts = show_starts(row)
        if not starts:
            return []
        sh = round(rl("show-line") * fz())
        return [(QRect(r.left(), r.top() - sh, r.width(), sh), starts[k]) for k, (r, _ep) in enumerate(eps)
                if k in starts]

    def show_lines(self, entry, rect):
        """An opened group's (or Up Next's) show lines where `rect` lays them: [(QRect, show)] (LM11b)."""
        return self._show_lines(entry[1], self.episode_lines(entry, rect))

    def _status_part(self, item, episodes, rect, word):
        """A status as a part (P4.1 L2): its button (`action_of`) at `rect`, or itself. Pressed, its hover says so: a
        *Mine now* *Asked · starting…* (round 8 row 45), a *Stop* *Stopping…* (R47: no second Stop)."""
        name, tip, ask = action_of(item.status, episodes, self.view.connect_off, word)
        if name in ASKS and self.view.pressed(episodes):
            tip = strings.ROWS_ASKED_TIP
        elif name == STOP and self.view.stopping(episodes):
            name, tip, ask = "status", view_rows.STRINGS["tip_stopping"], None
        return name, rect, tip, ask

    def _episode_parts(self, row, area, hero=False):
        out = []
        hot = self.view.hot_eps(row.key)
        for r, ep in self._episode_rows(row, area, hero):
            cols = self._episode_cols(r)
            if ep.id in hot:                         # --- row 28: the episode's own ⋯ (`episode_menu_requested`)
                out.append(("more-ep", cols["more"], strings.ROWS_EP_MORE_TIP, ep))
            if ep.can_play:                          # row 55: nothing to open, no ▶ (its column stays: IK-6)
                out.append(("play", cols["play"], ep.play_tip, ep))
            if ep.status is not None:
                size = pill_size(ep.status)
                out.append(self._status_part(ep, (ep,), QRect(cols["stat"].right() - size.width(),   # --- P4.1 L2;
                                                              cols["stat"].center().y() - size.height() // 2,
                                                              size.width(), size.height()),
                                             ep.media_word or row.media_word))       # LM11b G1: its own type's word
            state = strings.ROWS_STONE_STATE["cut" if ep.watched else "raw" if ep.cards else "rock"].format(n=ep.cards)
            out.append(("stone", cols["tick"], stone_tip(
                ep, state, view_rows.mark_moves_list(row.tier, ep, self._keep_watched())), ep))
        return out

    # --- W3.2 Q8: the ✂ seam between two episodes of an opened row (A3 `split`), and drop-to-join's outline (G3) --- #
    def _seam_parts(self, row, area, hero=False):
        """An opened row's seams: one between each two of its episodes (a part of its own: a title's piece with 2+
        files, never hato's mix), clear of the stone and the buttons; its payload the episode that would start the new
        part."""
        if row.piece_id is None or row.source == "hato" or len(row.episodes) < 2:
            return []
        eps = self._episode_rows(row, area, hero)
        out = []
        half = max(4, round(5 * fz()))
        starts = show_starts(row)
        for k in range(1, len(eps)):
            if view_rows.split_piece(row, k) is None:     # B2-2: the Soon line parts the show there already
                continue
            r, ep = eps[k]
            cols = self._episode_cols(r)
            left = r.left() + EP_LABEL_IN
            y = eps[k - 1][0].bottom() + 1           # LM11b: under the run before, above a show line where one stands —
            if k in starts:                          # there wholly above it, so its ✂ chip never covers the show's name
                y -= half                            # and its hover takes none of the show line (AD-5)
            out.append(("seam", QRect(left, y - half, max(1, cols["more"].left() - 8 - left), 2 * half),
                        strings.SEAM_TIP.format(rest=_rest_of(row, k)), ep))
        return out

    def paint_seam(self, p, r):
        """The seam under the hand: a dashed accent line with *✂ Split here* on a chip at its left."""
        f, mid = fz(), r.center().y() + 0.5
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(c("accent"), 1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(r.left(), mid), QPointF(r.right(), mid))
        w = TEXT.metrics("status-pill").horizontalAdvance(strings.SEAM_LABEL) + round(16 * f)
        h = round(20 * f)
        chip = QRectF(r.left(), mid - h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("surface"))
        p.drawRoundedRect(chip, h / 2, h / 2)
        TEXT.draw(p, chip.left(), mid, strings.SEAM_LABEL, "status-pill", chip.width(), c("accent"), align="centre")
        p.restore()

    def _paint_picked(self, p, i, kind, row, rect, lines, is_open):
        """LM11b G4: a picked row's slab (Up Next: its head) and a picked episode's line washed in `row-picked` and
        ringed in the accent, where the row is painted now (a closed row's lift moves it)."""
        boxes = []
        if row.key in self.view.picked_rows:
            if kind == HERO:
                boxes.append(QRectF(rect.left(), rect.top(), rect.width(), self._hero_head_h()))
            elif kind == FINISHED:                   # --- A4: Finished's row, its body as it is painted
                boxes.append(QRectF(rect.left(), rect.top(), rect.width(), rect.height() - theme.SPACING["list-gap"] -
                                    self._lines_h(lines)))
            else:
                slab = self.slab_of(rect)
                dy = 0.0 if is_open else self.view.touch(i, row.key)[0]
                boxes.append(QRectF(slab).translated(0, dy))
        eps = {e for k, e in self.view.picked_eps if k == row.key}
        if eps and is_open:
            if kind == HERO:
                area, hero = self._hero_geometry(row, rect, lines)["eps"], True
            else:
                area, hero = self._open_area(rect, self.slab_of(rect)), False
            boxes += [QRectF(r) for r, ep in self._episode_rows(row, area, hero) if ep.id in eps]
        if not boxes:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(c("accent"), 1.5))
        p.setBrush(c("row-picked"))
        radius = theme.DRAG["placeholder-radius"]
        for r in boxes:
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
        p.restore()

    def paint_join(self, p, r, label=None):
        """The part a dragged part would join (G3): a green dashed outline and `label` (*Drop to join*; LM11b G2:
        *Drop to group* on another show)."""
        label = label or strings.JOIN_LABEL
        f = fz()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(c("ok"), max(1.5, round(2 * f)))
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius = theme.DRAG["placeholder-radius"]
        p.drawRoundedRect(QRectF(r).adjusted(1.5, 1.5, -1.5, -1.5), radius, radius)
        w = TEXT.metrics("status-pill").horizontalAdvance(label) + round(16 * f)
        h = round(20 * f)
        chip = QRectF(r.right() - w - round(12 * f), r.top() + 4, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("bg"))
        p.drawRoundedRect(chip, h / 2, h / 2)
        TEXT.draw(p, chip.left(), chip.center().y(), label, "status-pill", chip.width(), c("ok"),
                  align="centre")
        p.restore()
    # --- end W3.2 Q8

    def _episode_cols(self, r):
        """An episode's parts, in a Current row's columns at the episode's height (G2.3 A1, A2): % · new in the row's
        % · new column, the status ending where the row's Anki count does, ▶ before it; in Up Next, the rows' under it."""
        f, g = fz(), rl("gap-x")
        right = r.right() + 1 - rl("pad-right")
        diff_w = round(rl("diff") * f)
        diff = QRect(right - diff_w, r.top(), diff_w, r.height())
        stat_w = round(theme.SIZES["col-stat"] * f)
        stat = QRect(diff.left() - g - stat_w, r.top(), stat_w, r.height())
        side = round(theme.SIZES["icon-button"] * f)
        play = QRect(stat.left() - g - side, r.center().y() - side // 2, side, side)
        # row 28: its own ⋯, shown while hovered or the keyboard's — left of ▶, so ▶ keeps its place whether or not ⋯
        # shows (IK-6: in ⋯'s room ▶ sat one button left on every episode line)
        more = QRect(play.left() - rl("hover-gap") - side, play.top(), side, side)
        tick = QRect(r.left() + 12, r.center().y() - 10, 20, 20)
        return {"play": play, "more": more, "stat": stat, "diff": diff, "tick": tick,
                "text_left": r.left() + EP_LABEL_IN, "text_right": more.left() - 12}

    def _hero_geometry(self, row, rect, lines=()):
        """Up Next, the old mock's card flat (W3.1a §1 *Up Next*; ref-extract §7): a slab, the cover, the text column
        (eyebrow, title + its episode, the source, the numbers with ↗, the string), then ▶ Play and ✓ Done side by side
        over *N in Anki* and ⋯."""
        f = fz()
        box = QRect(rect.left(), rect.top(), rect.width(), rect.height() - rl("hero-below") - self._lines_h(lines))
        head_h = self._hero_head_h()
        pad_x, pad_y, pad_r, gap = rl("hero-pad-x"), rl("hero-pad-y"), rl("hero-pad-right"), rl("hero-gap")
        head = QRect(box.left(), box.top(), box.width(), head_h)
        cov = QRect(head.left() + pad_x, head.top() + (head_h - theme.SIZES["hero-cover-h"]) // 2,
                    theme.SIZES["hero-cover-w"], theme.SIZES["hero-cover-h"])
        btn_h = round(theme.SIZES["button"] * f)
        fm = TEXT.metrics("button")
        if row.episodes[row.next_index].can_play:
            play_w = round(13 + rl("hero-trillion") + 7 + fm.horizontalAdvance(self._watch_label(row)) + 13)
        else:                                       # R55-B: plain words, no trillion — their own width
            play_w = round(13 + fm.horizontalAdvance(self._watch_label(row)) + 13)
        done_w = round(13 + 14 + 7 + fm.horizontalAdvance(strings.ROWS_DONE) + 13)
        side_w = play_w + 8 + done_w
        side = QRect(head.right() - pad_r - side_w + 1, head.top() + pad_y, side_w, head_h - 2 * pad_y)
        main = QRect(cov.right() + gap, head.top() + pad_y, side.left() - gap - cov.right() - gap, head_h - 2 * pad_y)
        mid = side.top() + side.height() // 2
        done = QRect(side.right() - done_w + 1, mid - btn_h - 5, done_w, btn_h)
        play = QRect(done.left() - 8 - play_w, mid - btn_h - 5, play_w, btn_h)
        b = round(rl("button") * f)
        more = QRect(side.right() - b + 1, mid + 5, b, b)
        nxt = row.episodes[row.next_index]
        stat_w = max(self._stat_w(row.status), round(rl("icon-w") * f))       # the row's own status (Q33)
        status = QRect(more.left() - 4 - stat_w, mid + 5, stat_w, b)
        y = main.top()
        eyebrow_h = round(11 * f * 1.45)
        title_h = round(21 * f * 1.25)
        sub_h = round(12.5 * f * 1.45)
        stats_h = round(12.5 * f * 1.45)
        g = {"box": box, "head": head, "cover": cov, "main": QRect(cov.left(), head.top(), main.right() - cov.left(),
                                                                   head_h),
             "play": play, "done": done, "more": more, "status": status, "text": main}
        g["eyebrow"] = QRect(main.left(), y, main.width(), eyebrow_h)
        y += eyebrow_h + 5
        g["title"] = QRect(main.left(), y, main.width(), title_h)
        y += title_h + 5
        # the source (mock `heroSub`): *Hato* for a hato show, the channel for a video; otherwise dropped (G16)
        g["sub"] = QRect(main.left(), y, main.width(), sub_h) if row.source == "hato" or \
            (row.media == "youtube" and row.line) else None
        if g["sub"] is not None:
            y += sub_h + 5
        g["stats"] = QRect(main.left(), y, main.width(), stats_h)
        g["journey"] = None
        if nxt.pct is not None and nxt.n_new is not None:     # *N new words ↗*: the link into the journey (A3; S6);
            known = strings.ROWS_HERO_KNOWN.format(pct=round(nxt.pct))   # no number, no link (row 36)
            link = strings.ROWS_HERO_NEW_LINK.format(n=nxt.n_new)
            hs = TEXT.metrics("hero-sub")
            x0 = main.left() + hs.horizontalAdvance(known)
            g["journey"] = QRect(x0, y, min(hs.horizontalAdvance(link) + 2, max(0, main.right() - x0)), stats_h)
        y += stats_h + 5
        g["string"] = QRect(main.left(), y, main.width(), round(rl("hero-string") * f))
        g["eps"] = QRect(box.left(), head.bottom() + 1, box.width(), box.bottom() - head.bottom())
        return g

    # painting --------------------------------------------------------------------------------------------------- #
    def paint(self, p, option, index):
        entry = self._entry(index)
        if entry is None:
            return
        self.paints += 1
        kind, payload, lines = entry
        rect = option.rect
        dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = (bool(option.state & QStyle.StateFlag.State_HasFocus) and self.view.hasFocus() and
                   self.view.focus_visible)          # the ring for the keyboard only (G2.3 R1: a click drew it)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        is_open = self.view.model().open_key == getattr(payload, "key", None)
        p.save()                                     # (the body only: a drag's lines stay where they are)
        body = True
        if kind in (HERO, ROW):                      # W3.1a §2: a drag parts the rows; the dragged one leaves its slot
            parting = self.view.parting
            if parting is not None and parting.src == index.row():
                body = False                         # its slot travels with the hand (`drag.Parting.paint_over`)
            elif parting is not None:
                shift = parting.offset(index.row())
                if shift:
                    p.translate(0, shift)
            if self.view.landing is not None and self.view.landing == payload.key:
                body = False                         # a drop's ghost glides onto it: its slot shows meanwhile
                self.paint_slot(p, self.slot_rect(kind, rect, lines))
        if not body:
            pass
        elif kind == HERO and not is_open:
            pix, box = self._closed(kind, payload, lines, rect, dpr, hovered or focused, p)
            if pix is not None:
                p.drawPixmap(box.topLeft(), pix)
            if payload.status is not None and self.view.pressed(payload.episodes):     # round 8 row 45 (A-3): over
                self._paint_pressed(p, self._hero_geometry(payload, rect, lines)["status"])   # its cached picture
            part = self.view.marked_part(payload.episodes)                  # ... and a menu's press (IK-2)
            if part is not None:
                g = self._hero_geometry(payload, rect, lines)
                if part in ("play", "cover"):                               # (▶ Play is wide: its cover turns)
                    self._paint_marked(p, g["cover"], place="middle")
                elif part == "journey" and g["journey"] is not None:
                    self._paint_marked(p, g["journey"], place="after")
                else:
                    self._paint_marked(p, g["status"] if part in ACTION_NAMES else g.get(part) or g["more"])
            if self.view.stop_marks() and payload.status is not None and payload.status.kind == "mining":   # R47
                self._paint_stop_over(p, self._hero_geometry(payload, rect, lines)["status"], payload.status,
                                      payload.episodes, dpr)
            if focused:
                self._focus_ring(p, box, theme.RADII["r-sm"])
        elif kind == HERO:
            self._paint_open_hero(p, payload, rect, lines, hovered or focused, focused, dpr)
        elif kind == ROW:
            self._paint_current_entry(p, index.row(), payload, rect, lines, focused, dpr, is_open)
        elif kind == FINISHED:
            body = QRect(rect.left(), rect.top(), rect.width(), rect.height() - theme.SPACING["list-gap"] -
                         self._lines_h(lines))
            pix, _box = self._closed(kind, payload, lines, rect, dpr, hovered or focused, p)   # W3.2 Q4: focus too
            if pix is not None:
                p.drawPixmap(body.topLeft(), pix)
            if self.view.marked_part(payload.episodes) is not None:    # round 8 row 45 (IK-2): its ⋯'s press
                row_line = QRect(rect.left(), rect.top(), rect.width(), round(theme.SIZES["row"] * fz()))
                self._paint_marked(p, self.finished_acts(self.columns(row_line, kind)["acts"])[1])
            if focused:
                self._focus_ring(p, body, theme.RADII["r-sm"])
        elif kind == MONTH:
            TEXT.draw(p, rect.left() + 4, rect.bottom() - round(11.5 * fz() * 0.9) - 4, payload.upper(), "month",
                      rect.width() - 8, c("ink-dim"), dpr=dpr)
        elif kind == NEED:
            self._paint_need(p, payload, rect, dpr)
        elif kind == FAILURE:
            self._paint_failure(p, payload, rect, dpr)
        elif kind == EMPTY:
            title, line_ = payload
            mid = rect.center().y()
            TEXT.draw(p, rect.left(), mid - 12 * fz(), title, "page-heading", rect.width(), c("ink"), align="centre",
                      dpr=dpr)
            TEXT.draw(p, rect.left(), mid + 14 * fz(), line_, "body", rect.width(), c("ink-dim"), weight=400,
                      align="centre", dpr=dpr)
        if body and kind in PICK_KINDS and (self.view.picked_rows or self.view.picked_eps):    # --- LM11b G4, A4
            self._paint_picked(p, index.row(), kind, payload, rect, lines, is_open)
        if body and kind == ROW and payload.key in self.view.saving:
            self._paint_saving(p, payload, rect, dpr)
        p.restore()
        y = rect.bottom() + 1 - self._lines_h(lines)
        hot = self.view.line_hover
        for ln in lines:
            self._paint_line(p, ln, QRect(rect.left(), y, rect.width(), rl("line")), dpr,
                             hot=hot == (index.row(), ln.kind))
            y += rl("line")
        p.restore()

    def _paint_current_entry(self, p, i, row, rect, lines, focused, dpr, is_open):
        """A Current row where it stands: its picture at rest and, fading in over it, its hover look; lifted on its
        spring with its baked shadow, its neighbours eased apart (`RowsView.touch`: hover and keyboard focus alike, S7);
        its number and ↑ ↓ drawn over the picture (an arrival moves every number and draws no row afresh)."""
        slab = self.slab_of(rect)
        dy, lift, fade = self.view.touch(i, row.key)
        dy = round(dy * dpr) / dpr                   # whole device px: a picture blitted never smeared
        if is_open:
            self._paint_open_row(p, row, slab, rect, lines, fade, focused, dpr)
            return
        if lift > 0:
            self._paint_lift(p, slab, dy, lift, dpr)
        at = QPointF(slab.left(), slab.top() + dy)
        self._blit_faded(p, at, fade, lambda active: self._closed_row(row, slab, dpr, active, p, at))
        p.save()
        p.translate(0, dy)
        if lift > 0:                                 # the lifted slab's lit top edge
            p.fillRect(QRectF(slab.left(), slab.top(), slab.width(), 1), faded("lift-line",
                                                                                rl("lift-line-alpha") * lift / 2))
        self._paint_number(p, row, slab, dpr)
        if fade > 0:
            self._paint_movers(p, row, slab, fade)
        if self.view.pressed(row.episodes):          # round 8 row 45
            at = next((r for name, r, *_rest in self.line_geometry(row, slab)["hover"] if name in ASKS), None)
            if at is not None:                       # (the Mine now button's place, at rest too: it turns there)
                self._paint_pressed(p, at, radius=theme.RADII["icon-button"])
        part = self.view.marked_part(row.episodes)   # round 8 row 45 (IK-2): a menu's press on this row, at its part
        if part == "cover":
            self._paint_marked(p, self.line_geometry(row, slab)["art"], place="middle")
        elif part is not None:
            at = next((r for name, r, *_rest in self.line_geometry(row, slab)["hover"] if name == part), None)
            if at is not None:
                self._paint_marked(p, at)
        if self.view.stop_marks() and row.status is not None and row.status.kind == "mining":     # --- R47
            self._paint_stop_over(p, self.line_geometry(row, slab)["stat"], row.status, row.episodes, dpr,
                                  "row-hover" if fade > 0 else "surface")
        if focused:
            self._focus_ring(p, slab, theme.RADII["r-sm"])
        p.restore()

    def _paint_stop_over(self, p, rect, status, episodes, dpr, ground="surface"):
        """R47: a Mining pill's Stop over `rect` (its cached picture under it): *Stopping…* turning while its Stop is
        pressed (the view repaints that box alone as it turns), *■ Stop* while the hand is on it. `ground`: under it."""
        view = self.view
        if rect.height() > rect.width():             # a row's column (its icon at rest): the icon's own square
            side = rect.width()
            rect = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        if view.stopping(episodes):
            paint_stop(p, rect, True, view.turning(), dpr=dpr, ground=ground)
            if p.device() is view.viewport():
                view.turned_at(p.transform().mapRect(QRectF(rect)).toAlignedRect())
        elif view.stop_hot is not None and status.stop is not None and not view.connect_off and \
                QRectF(rect).contains(QPointF(view.stop_hot.center())):
            paint_stop(p, rect, False, dpr=dpr, ground=ground)

    def _paint_marked(self, p, rect, place="button"):
        """Round 8 row 45 (IK-2): a press's arc on a file's line at `rect`; repainted alone as it turns."""
        paint_marked(p, rect, self.view.turning(), place=place)
        if p.device() is self.view.viewport():
            box = QRectF(rect)
            if place == "after":
                box = QRectF(box.right(), box.top(), box.height() + 8, box.height())
            self.view.turned_at(p.transform().mapRect(box).toAlignedRect())

    def _ep_marked(self, p, r, ep, dpr):
        """A menu's press on an episode's own line (its row open): at its part — a status action at its pill."""
        part, cols = self.view.marked[ep.id][-1], self._episode_cols(r)
        if part in ACTION_NAMES and ep.status is not None:
            self._paint_marked(p, self._ep_pill(r, ep, dpr))
        else:
            self._paint_marked(p, cols.get(part) or cols["more"])

    def _paint_pressed(self, p, rect, radius=None):
        """Round 8 row 45: a pressed *Mine now*'s turning mark over `rect`; painted on the list, the view repaints that
        box alone as it turns."""
        paint_pressed(p, rect, self.view.turning(), radius=radius)
        if p.device() is self.view.viewport():
            self.view.turned_at(p.transform().mapRect(QRectF(rect)).toAlignedRect())

    @staticmethod
    def _blit_faded(p, at, fade, picture):
        """The rest picture, then the hover picture over it at `fade` (0–1): a fade costs two blits, never a paint."""
        if fade < 1:
            pix = picture(False)
            if pix is not None:
                p.drawPixmap(at, pix)
        if fade > 0:
            p.save()
            p.setOpacity(fade)
            pix = picture(True)
            if pix is not None:
                p.drawPixmap(at, pix)
            p.restore()

    def _closed_row(self, row, slab, dpr, active, p=None, at=None):
        """A closed Current row's picture (painted once, `_sprite`), at rest or active (hover, keyboard focus), keyed
        too on the one title width and on whether the stones' sheet was there to draw from."""
        sheet = stones.get(dpr, style.current()[1])
        tw = self.title_w(slab.width())
        local = QRect(0, 0, slab.width(), slab.height())
        return self._sprite(ROW, row, slab.size(), dpr, active,
                            lambda q: self._paint_current(q, row, local, active, dpr, sheet, tw=tw),
                            ground="row-hover" if active else "surface", to=None if p is None else (p, at),
                            extra=(tw, sheet is not None))

    def _paint_lift(self, p, slab, dy, lift, dpr):
        """The lifted row's shadow, baked once per width and ratio, at the lift's share; inside the row's own gap."""
        h = rl("shadow")
        key = (slab.width(), dpr)
        if getattr(self, "_shadow", (None,))[0] != key:
            pix = QPixmap(max(1, round(slab.width() * dpr)), max(1, round(h * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.GlobalColor.transparent)
            q = QPainter(pix)
            grad = QLinearGradient(QPointF(0, 0), QPointF(0, h))
            grad.setColorAt(0, faded("shadow", rl("shadow-alpha")))
            grad.setColorAt(1, faded("shadow", 0.0))
            q.fillRect(QRectF(0, 0, slab.width(), h), QBrush(grad))
            q.end()
            self._shadow = (key, pix)
        p.save()
        p.setOpacity(min(1.0, lift / theme.SPRINGS["lift-px"]))
        p.drawPixmap(QPointF(slab.left(), slab.bottom() + 1 + dy), self._shadow[1])
        p.restore()

    def _paint_current(self, p, row, slab, active, dpr, sheet, opened=False, tw=None):
        """A Current row's line drawn into its picture: the art, the title (cut with "…"), the string, the Anki
        count, % · new; active (hover or keyboard focus), the next stone's ring and the hover group over the string's
        end. Opened, its head: the title cut with "…" in the wider column (the string's room), a baked sheen, no
        string."""
        g = self.line_geometry(row, slab, tw, opened)
        ground = "open-row" if opened else "row-hover" if active else "surface"
        if opened:
            self._sheen(p, slab)
        a = g["art"]
        p.drawPixmap(a.topLeft(), art(row.cover_title, a.width(), a.height(), dpr, ref=row.cover))     # W3.2 Q6
        f = fz()
        m = g["main"]
        mid = slab.top() + slab.height() / 2
        # a video's channel and hato's mix keep their line; a numbered piece's range and watched count are the string's
        # Hon a5-2 (PROVISIONAL): 🎧 before the title (its words in its hover, `parts`); an audiobook alone keeps its
        # quiet line, *Audio only · waits for Anki Miner*, and no stones
        alone = view_rows.audio_only(row)
        sub = row.line if row.line and (row.media == "youtube" or row.source == "hato" or alone) else ""
        t_h, s_h = round(13.5 * f * 1.3), round(12 * f * 1.3)
        top = mid - (t_h + 1 + s_h) / 2 if sub else mid - t_h / 2
        # one line each, cut with "…" inside the title's column, left of the string (the full title is in the tooltip):
        # cut and faded at the column's edge it read as a title clipped by the stones (laptop try, FEEDBACK 11)
        TEXT.draw(p, m.left(), top + t_h / 2, heard_title(row), "row-title", m.width(), c("ink"), dpr=dpr)
        if sub:
            TEXT.draw(p, m.left(), top + t_h + 1 + s_h / 2, sub, "row-sub", m.width(), c("ink-dim"), dpr=dpr)
        if not opened and not alone:
            self._paint_string(p, self._info(row)[0], g["gstr"], mid, sheet, ring=active)
        self._paint_stat(p, row.status, g["stat"], mid, dpr)
        paint_diff(p, row.pct, row.pct_tone, row.n_new, g["diff"].right(), mid, dpr, row.new_faded)
        if active:
            self._paint_hover_group(p, g, ground, opened)

    def _sheen(self, p, r):
        """An opened row's one sheen (list-r14m :705, flat): a band of light across it at 112°, baked into its head."""
        paint_sheen(p, r, rl("sheen-alpha"))

    def _paint_string(self, p, plan, room, mid, sheet, ring=False, big=False):
        """The string of stones in `room` (its plan laid out once per width: `stone_plan.layout`), each a blit from
        the sheet: the hairline from the first stone's centre to the last's, a stone that won't mine itself at
        `dim`, a file whose video is gone marked under its stone, the next stone's ring when `ring`. Nothing until the
        sheet is there (the row is painted again once when it lands)."""
        if sheet is None or room.width() <= 0 or not plan.items:
            return
        lay = stone_plan.layout(plan, room.width(), 1.0)
        x0 = room.left()
        p.save()
        p.setClipRect(room)
        if len(lay.xs) > 1:
            p.fillRect(QRectF(x0 + lay.xs[0], mid - 0.5, lay.xs[-1] - lay.xs[0], 1), c("string"))
        for item, x in zip(plan.items, lay.xs):
            what = self._stone_what(item, plan.gem, big)
            at = QPointF(x0 + x, mid)
            single = item.kind == "stone"
            if single and item.dim:
                p.setOpacity(rl("dim"))
            sheet.draw(p, at, what)
            p.setOpacity(1.0)
            if single and (item.missing or item.removed):
                below = sheet.rect_of(what, at).bottom() + 2.5
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c("ink-faint" if item.removed else "warn"))
                p.drawEllipse(QPointF(at.x(), below), 1.5, 1.5)
            if single and item.big and ring:
                sheet.draw(p, at, ("ring", what[4]))
        p.restore()

    def _paint_stat(self, p, status, r, mid, dpr):
        """What a row shows at rest right of its string: the Anki count (its mark and N in the learned green), or
        mining's icon in the accent."""
        if status is None or not r.width():
            return
        side = rl("anki-icon")
        if status.kind == "in_anki":
            icon(p, "anki", QRectF(r.left() + 2, mid - side / 2, side, side), c("ok"), width=1.3)
            TEXT.draw(p, r.left() + 2 + side + 5, mid, status.label, "status-pill", r.width(), c("ok"), weight=700,
                      dpr=dpr, elide=False)
        elif status.kind == "mining":
            icon(p, "mining", QRectF(r.center().x() - side / 2, mid - side / 2, side, side), c("accent"))

    def _paint_hover_group(self, p, g, ground, opened=False):
        """The hover group over the string's end (list-r14m `.r11-hb`): never a box over the stones — under it the
        string fades out into the row's own ground — then the status icon, ▶ and ⋯."""
        end = g["end"]
        hx = end - g["hw"]
        if not opened:
            s = g["gstr"]
            fl = hx - rl("hover-fade")
            grad = QLinearGradient(QPointF(fl, 0), QPointF(hx + 2, 0))
            grad.setColorAt(0, faded(ground, 0.0))
            grad.setColorAt(1, faded(ground, 1.0))
            p.fillRect(QRectF(fl, s.top(), hx + 2 - fl, s.height()), QBrush(grad))
            p.fillRect(QRectF(hx + 2, s.top(), max(0, end - hx - 2), s.height()), c(ground))
        side = rl("anki-icon")
        for name, r, glyph, ink, _tip, payload in g["hover"]:
            if name == "play" and payload is not None and not payload.can_play:
                continue                             # row 55: not drawn — Sonic: "there shouldn't be a play button"
            p.save()
            if name == "mine-now":                   # a button: Waiting's icon is Mine now (A2 #44)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c("raised"))
                p.drawRoundedRect(QRectF(r), theme.RADII["icon-button"], theme.RADII["icon-button"])
            icon(p, glyph, QRectF(r.center().x() - side / 2 + 0.5, r.center().y() - side / 2 + 0.5, side, side), c(ink))
            p.restore()

    def _paint_number(self, p, row, body, dpr):
        """A row's place in Current, centred in its column, drawn over its picture (never inside it): a file arriving
        above moves every number, and with the number inside, every row on screen was drawn again (~21 ms an arrival,
        bench 10; review B-5). Never cut: a number wider than its column (#100 and on at Large) runs into the slab's
        edge (G2.3 A4)."""
        pos_w = round(rl("pos") * fz())
        text = str(row.index)
        w = max(pos_w, TEXT.metrics("position", dpr=dpr).horizontalAdvance(text) + 2)
        TEXT.draw(p, body.left() + pos_w / 2 - w / 2, body.top() + self._line_h() / 2, text, "position", w,
                  c("ink-dim"), align="centre", dpr=dpr, elide=False)

    def _paint_movers(self, p, row, slab, alpha):
        """↑ ↓ in the number's column on hover or keyboard focus (A2 #13), fading in with the hover look."""
        g = self.line_geometry(row, slab)
        p.save()
        p.setOpacity(alpha)
        for name, glyph in (("up", "chev-up"), ("down", "chev-down")):
            r = g[name]
            icon(p, glyph, QRectF(r.center().x() - 6.5 + 0.5, r.center().y() - 6.5 + 0.5, 13, 13), c("ink-faint"))
        p.restore()

    def _closed(self, kind, payload, lines, rect, dpr, hovered, p=None):
        """A closed entry's picture (painted once, `_sprite`) and the box it fills in `rect` (pixmaps off and a painter
        `p` given: drawn there, and no pixmap)."""
        if kind == HERO:
            box_h = rect.height() - rl("hero-below") - self._lines_h(lines)
            local = QRect(0, 0, rect.width(), rect.height())
            sheet = stones.get(dpr, style.current()[1])
            pix = self._sprite(kind, payload, QSize(rect.width(), box_h), dpr, hovered,
                               lambda q: self._paint_hero(q, payload, local, lines, hovered, dpr, sheet),
                               ground="surface", to=None if p is None else (p, rect.topLeft()),
                               extra=(sheet is not None,))
            return pix, QRect(rect.left(), rect.top(), rect.width(), box_h)
        if kind == ROW:
            slab = self.slab_of(rect)
            return self._closed_row(payload, slab, dpr, False, p, QPointF(slab.topLeft())), slab
        body = QRect(rect.left(), rect.top(), rect.width(), rect.height() - theme.SPACING["list-gap"] -
                     self._lines_h(lines))
        local = QRect(0, 0, body.width(), body.height())
        pix = self._sprite(kind, payload, body.size(), dpr, hovered,
                           lambda q: self._paint_row(q, kind, payload, local, hovered, dpr),
                           to=None if p is None else (p, body.topLeft()))
        return pix, body

    def _paint_open_row(self, p, row, slab, rect, lines, fade, focused, dpr):
        """An opened row: one panel on the opened row's ground — its head painted once into a picture (the full
        title, a baked sheen), then the episode lines, each its own picture with its stone at the left — so opening a
        row costs a relayout and blits, and a repaint of an open row draws no text afresh: only its number."""
        panel = QRect(slab.left(), slab.top(), slab.width(), rect.height() - rl("gap") - self._lines_h(lines))
        p.fillRect(panel, c("open-row"))
        local = QRect(0, 0, slab.width(), slab.height())
        at = QPointF(slab.topLeft())

        def head(active):
            return self._sprite(ROW, row, slab.size(), dpr, active,
                                lambda q: self._paint_current(q, row, local, active, dpr, None, opened=True),
                                ident=(row.key, "open"), ground="open-row", to=(p, at))
        self._blit_faded(p, at, fade, head)
        self._paint_number(p, row, slab, dpr)
        if self.view.stop_marks() and row.status is not None and row.status.kind == "mining":     # --- R47
            self._paint_stop_over(p, self.line_geometry(row, slab, opened=True)["stat"], row.status, row.episodes, dpr,
                                  "open-row")
        if fade > 0:
            self._paint_movers(p, row, slab, fade)
        if focused:
            self._focus_ring(p, panel, theme.RADII["r-sm"])
        self._paint_episodes(p, row, QRect(rect.left(), slab.bottom() + 1, rect.width(), panel.bottom() -
                                           slab.bottom()), dpr, lines=lines)
        # --- W3.2 Q6: the whole cover standing at its left (C-scope Q6: the opened row replaces the panel), flat
        st = self.stand_rect(slab)
        p.drawPixmap(st.topLeft(), qcovers.pixmap_for(row.cover, row.cover_title, st.width(), st.height(), dpr,
                                                      "stand"))
        # --- end W3.2 Q6

    # --- W3.2 Q6: the opened row's standing cover, and a title's picture landing ------------------------------- #
    @staticmethod
    def stand_size():
        """The standing cover (2 : 3) at the text size: inside the number's and the art's columns, left of the
        episodes' stones at every text size."""
        f = fz()
        return round(STAND_W * f), round(STAND_W * 1.5 * f)

    def stand_h(self):
        return STAND_TOP + self.stand_size()[1]

    def stand_rect(self, slab):
        w, h = self.stand_size()
        return QRect(slab.left() + STAND_IN, slab.bottom() + 1 + STAND_TOP, w, h)

    def drop_work(self, work_id):
        """A title's picture landed (or was let go): its rows' pictures let go, so the next paint draws them with it.
        -> whether any was."""
        dropped = False
        for name in ("row", "ep"):
            cache = self._sprites[name]
            for key in list(cache):
                if getattr(cache[key][0], "work_id", None) == work_id:
                    self._bytes[name] -= _size(cache.pop(key)[1])
                    dropped = True
        return dropped
    # --- end W3.2 Q6

    def keep_only(self, entries, dpr=None, width=None):
        """At rest, a list keeps the pixmaps of these entries only (its screen and the rows ahead, or a hidden list's
        screen): what it scrolled past is let go, so idle memory is a few screens whatever was seen (bench 9: 284 MB
        idle at 375 %). Pixmaps of another look, screen ratio (`dpr`) or list width (`width`, rows only: episodes are
        narrower) are let go too: they can never be drawn again (review C-5)."""
        look = style.current()
        keys, eps = set(), set()
        for kind, payload, _lines in entries:
            k = getattr(payload, "key", None)
            if k is not None:
                keys.add(k)
            if kind in (HERO, ROW):                  # a Needs-you card's episodes are lines, not episodes
                eps.update(e.id for e in payload.episodes)
                if getattr(payload, "group", False):     # LM11b: a group's show lines, kept as its episodes are
                    eps.update(("show", e.show) for e in payload.episodes)
        for name in ("row", "ep"):
            cache = self._sprites[name]
            for key in list(cache):
                ident = key[1]
                if name == "ep":
                    keep = ident[0] in eps
                else:
                    keep = ident in keys or (isinstance(ident, tuple) and ident[0] in keys)
                    keep = keep and (width is None or key[2] == width)
                keep = keep and key[5] == look and (dpr is None or key[4] == dpr)
                if not keep:
                    self._bytes[name] -= _size(cache.pop(key)[1])

    def drop_unsheeted(self, dpr):
        """The stones' sheet for `dpr` has landed: the pictures painted before it (without their stones) are let go,
        so the next paint draws them once with their stones. -> whether any was."""
        dropped = False
        for name in ("row", "ep"):
            cache = self._sprites[name]
            for key in list(cache):
                extra = key[7]
                if isinstance(extra, tuple) and extra and extra[-1] is False and abs(key[4] - dpr) < 0.01:
                    self._bytes[name] -= _size(cache.pop(key)[1])
                    dropped = True
        return dropped

    def warm(self, index, dpr, rect=None):
        """Paint a closed row's pixmap ahead of its first paint (the list's idle moments): -> whether it drew one.
        `rect`: where it will stand (a hidden list's, laid out as the shown list is)."""
        if not ROW_PIXMAPS:
            return False
        entry = self._entry(index)
        if entry is None or entry[0] not in (HERO, ROW, FINISHED):
            return False
        kind, payload, lines = entry
        if self.view.model().open_key == payload.key:
            return False
        before = self.warmed
        self._warming = True
        try:
            self._closed(kind, payload, lines, self.view.visualRect(index) if rect is None else rect, dpr, False)
        finally:
            self._warming = False
        return self.warmed != before

    def warm_episodes(self, index, dpr, room):
        """Paint ahead the episodes a closed row would show if it opened now (those starting within `room` px of its
        top), one a call: -> whether it drew one. The pointer resting on a row warms them, so opening it blits (bench 9: every
        toggle was one long step, its episodes' first paints)."""
        if not ROW_PIXMAPS:
            return False
        entry = self._entry(index)
        if entry is None or entry[0] not in (HERO, ROW):
            return False
        kind, row, lines = entry
        if self.view.model().open_key == row.key or len(row.episodes) < 1:
            return False
        rect = self.view.visualRect(index)
        before = self.warmed
        if kind == HERO:
            area = QRect(rect.left(), rect.top() + self._hero_head_h() + 1, rect.width(), 1 << 20)
        else:
            # its open head first, as the click will show it — under the pointer, so active (an open row's hover
            # lights its head only): opening it then draws no head afresh (speed round 5: the head was each first
            # opening's own render)
            slab = self.slab_of(rect)
            area = QRect(rect.left(), slab.bottom() + 1, rect.width(), 1 << 20)
            local = QRect(0, 0, slab.width(), slab.height())
            self._warming = True
            try:
                self._sprite(kind, row, slab.size(), dpr, True,
                             lambda q: self._paint_current(q, row, local, True, dpr, None, opened=True),
                             ident=(row.key, "open"), ground="open-row", spare=True)
            finally:
                self._warming = False
            if self.warmed != before:
                return True
        budget = SPRITE_MB["ep"] * 1024 * 1024 // 2    # never more than half the episodes' cache: past it, each one
        self._warming = True                            # drawn would push out one drawn before, again and again
        try:
            for r, ep, draw, ident, extra in self._episode_pictures(row, area, kind == HERO, dpr):
                budget -= round(r.width() * dpr) * round(r.height() * dpr) * 4
                if r.top() - rect.top() > room or budget < 0:
                    break
                self._sprite("ep", ep, r.size(), dpr, False, draw, ident=ident,
                             ground="surface" if kind == HERO else "open-row", extra=extra)
                if self.warmed != before:
                    return True
        finally:
            self._warming = False
        return False

    def slot_rect(self, kind, rect, lines):
        """The slot an entry leaves while it is dragged (W3.1a §2): its slab — Up Next's card, or a row with its gap's
        halves outside — never its lines."""
        if kind == HERO:
            return QRect(rect.left(), rect.top(), rect.width(), rect.height() - rl("hero-below") - self._lines_h(lines))
        half = rl("gap") // 2
        return QRect(rect.left(), rect.top() + half, rect.width(), rect.height() - self._lines_h(lines) - rl("gap"))

    @staticmethod
    def paint_slot(p, r):
        """The placeholder a dragged row leaves (list-r14m :4330): `placeholder` with an inset accent ring at 60 %."""
        d = theme.DRAG
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(theme.DRAG_COLOURS["placeholder"]))
        radius = d["placeholder-radius"]
        p.drawRoundedRect(QRectF(r), radius, radius)
        w = d["placeholder-ring"]
        p.setPen(QPen(faded("accent", d["placeholder-ring-alpha"]), w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(r).adjusted(w / 2, w / 2, -w / 2, -w / 2), radius - w / 2, radius - w / 2)
        p.restore()

    def _paint_saving(self, p, row, rect, dpr):
        """*saving…* over the string's end while the row's move waits for a busy store (04 §4.5, after 300 ms)."""
        slab = self.slab_of(rect)
        g = self.line_geometry(row, slab)
        text = strings.ROWS_SAVING
        fm = TEXT.metrics("row-sub", dpr=dpr)
        w = fm.horizontalAdvance(text) + 12
        box = QRectF(g["end"] - w, slab.top() + slab.height() / 2 - fm.height() / 2, w, fm.height())
        p.fillRect(box, c("surface"))
        TEXT.draw(p, box.left() + 6, box.center().y(), text, "row-sub", w, c("ink-dim"), dpr=dpr, elide=False)

    def _paint_line(self, p, ln, strip, dpr, hot=False):
        """A line after its row (W3.1a §1 *Top-20 line*, *Soon line*): a groove — 1 px dark, then 1 px lit lip —
        across the list in its own strip, no word; Soon's quieter still (the lip only). Under the hand it lights a step
        (its lip). Whole device pixels, so it stays crisp at every scale."""
        k = max(1, round(dpr)) / dpr                 # one line's height: whole device px
        y = round((strip.top() + (strip.height() - 2 * k) / 2) * dpr) / dpr
        x0, w = strip.left() + 4, strip.width() - 8
        if ln.kind == "top":
            p.fillRect(QRectF(x0, y, w, k), c("groove"))
        p.fillRect(QRectF(x0, y + k, w, k), c("line-hi" if hot else "groove-lip"))

    def _paint_cover(self, p, title, rect, dpr, large=False, ref=None):                          # W3.2 Q6: ref
        p.drawPixmap(rect.topLeft(), cover(title, rect.width(), rect.height(), dpr, large, ref=ref))

    def _paint_watched_bar(self, p, row, crect):
        if row.n_files <= 1 or not row.n_watched:
            return
        h = 3
        track = QRectF(crect.left(), crect.bottom() - h + 1, crect.width(), h)
        p.fillRect(track, style.qcolor(theme.FIXED["watched-track"]))
        fill = QRectF(track.left(), track.top(), track.width() * row.n_watched / row.n_files, h)
        p.fillRect(fill, self._iris(fill))

    def _iris(self, r, vertical=False):
        grad = QLinearGradient(QPointF(r.left(), r.top()), QPointF(r.left(), r.bottom()) if vertical else
                               QPointF(r.right(), r.top()))
        for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
            grad.setColorAt(pos, style.qcolor(colour))
        return QBrush(grad)

    def _focus_ring(self, p, r, radius):
        pen = QPen(c("accent"), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(r).adjusted(1, 1, -1, -1), radius, radius)

    def _paint_row(self, p, kind, row, body, hovered, dpr):
        """A Finished row (today's layout, C-scope §2.3, painted by the same delegate as Current's): its cover, its title
        over its one line, its date, and only Mining… / ✓ N of the statuses."""
        f = fz()
        h = round(theme.SIZES["row"] * f)
        line_r = QRect(body.left(), body.top(), body.width(), h)
        radius = theme.RADII["r-sm"]
        if hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("surface"))
            p.drawRoundedRect(QRectF(body), radius, radius)
        _number_x, x, title_x = self.lead(kind, line_r.left())
        cw, ch = round(theme.SIZES["row-cover-w"] * f), round(theme.SIZES["row-cover-h"] * f)
        crect = QRect(x, line_r.center().y() - ch // 2, cw, ch)
        self._paint_cover(p, row.cover_title, crect, dpr, ref=row.cover)                         # W3.2 Q6
        x = title_x
        cols = self.columns(line_r, kind)
        text_w = cols["text_right"] - x
        t_h = round(13.5 * f * 1.3)
        s_h = round(12 * f * 1.3)
        top = line_r.center().y() - (t_h + 1 + s_h) / 2
        TEXT.draw(p, x, top + t_h / 2, heard_title(row), "row-title", text_w, c("ink"), dpr=dpr)
        sx = x
        if row.studying:
            sw = self._paint_studying(p, sx, top + t_h + 1 + s_h / 2, dpr)
            sx += sw + 10
        TEXT.draw(p, sx, top + t_h + 1 + s_h / 2, row.line, "row-sub", cols["text_right"] - sx, c("ink-dim"), dpr=dpr)
        TEXT.draw(p, cols["date"].left(), line_r.center().y(), row.date, "date", cols["date"].width(), c("ink-dim"),
                  dpr=dpr)
        st_rect, _mk = self._status_rects(row, cols["stat"])
        if row.status is not None and row.status.kind in ("in_anki", "mining") and st_rect is not None:
            paint_pill(p, row.status, st_rect, dpr, audio=row.media_word == "audio")
        if hovered and kind == FINISHED:                 # --- W3.2 Q4: Put back · ⋯, on hover and keyboard focus
            self._paint_finished_acts(p, cols["acts"], dpr)

    # --- W3.2 Q4: a Finished row's Put back and ⋯ ------------------------------------------------------------------ #
    @staticmethod
    def finished_acts(acts):
        """(Put back's rect, ⋯'s rect) in a Finished row's actions column: ⋯ at its right, Put back before it."""
        f = fz()
        b = round(theme.SIZES["button"] * f)
        h = round(theme.SIZES["button-sm"] * f)
        mid = acts.center().y()
        more = QRect(acts.right() + 1 - b, round(mid - b / 2), b, b)
        w = round(TEXT.metrics("button-sm", 550).horizontalAdvance(strings.FIN_PUT_BACK) + 2 * 10 * f)
        back = QRect(more.left() - 6 - w, round(mid - h / 2), w, h)
        return back, more

    def _paint_finished_acts(self, p, acts, dpr):
        back, more = self.finished_acts(acts)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("raised"))
        p.drawRoundedRect(QRectF(back), theme.RADII["button-sm"], theme.RADII["button-sm"])
        TEXT.draw(p, back.left(), back.center().y() + 0.5, strings.FIN_PUT_BACK, "button-sm", back.width(), c("ink"),
                  weight=550, align="centre", dpr=dpr)
        side = rl("anki-icon")
        icon(p, "more", QRectF(more.center().x() - side / 2 + 0.5, more.center().y() - side / 2 + 0.5, side, side),
             c("ink-dim"))
        p.restore()
    # --- end W3.2 Q4

    def _studying_w(self, dpr=1.0):
        fm = TEXT.metrics("row-sub", 600, dpr)
        return round(11 * fz()) + 4 + fm.horizontalAdvance(strings.ROWS_STUDYING)

    def _paint_studying(self, p, x, y_mid, dpr):
        """*Studying its cards first* before a Finished row's line: an up arrow and the words in the accent, on the
        row's own ground — no pill under the words (G2.3 R3). -> its width. (A Current row shows it as a hover mark.)"""
        f = fz()
        side = round(11 * f)
        icon(p, "up", QRectF(x, y_mid - side / 2, side, side), c("accent"), width=1.5)
        w, _ = TEXT.draw(p, x + side + 4, y_mid, strings.ROWS_STUDYING, "row-sub", 400 * f, c("accent"), weight=600,
                         dpr=dpr)
        return side + 4 + w

    def _paint_play_button(self, p, r):
        icon(p, "play", QRectF(r.center().x() - 7, r.center().y() - 7, 14, 14), c("ink-dim"))

    def _episode_pictures(self, row, area, hero, dpr):
        """Each episode line of an open row with how its picture is drawn: (rect, episode, draw, ident, extra). Its
        stone is the file's own on the string (`stone_plan`: state, variant, the next one big and ringed, dimmed when
        it won't mine itself)."""
        audio = row.media_word == "audio"
        sheet = stones.get(dpr, style.current()[1])
        plan = self._info(row)[0]
        out = []
        for i, (r, ep) in enumerate(self._episode_rows(row, area, hero)):
            big = i == plan.next
            item = stone_plan._stone(ep, i, row.key, big)
            what = self._stone_what(item, plan.gem)
            w, h = r.width(), r.height()
            stone = (what, item.dim, big)
            out.append((r, ep, lambda q, ep=ep, w=w, h=h, stone=stone: self._paint_episode(
                q, QRect(0, 0, w, h), ep, dpr, audio, stone, sheet), (ep.id, hero, audio, what, item.dim),
                (sheet is not None,)))
        return out

    def _paint_episodes(self, p, row, area, dpr, hero=False, lines=()):
        pictures = self._episode_pictures(row, area, hero, dpr)
        if not pictures:
            return
        rows_ = [(r, ep) for r, ep, *_rest in pictures]
        stone_x = rows_[0][0].left() + 22             # the episodes' stones on a hairline, the string stood upright —
        cuts = sorted(show_starts(row)) or [0]        # LM11b: in a group, one per show, never through its show line
        for a, b in zip(cuts, cuts[1:] + [len(rows_)]):
            p.fillRect(QRectF(stone_x - 0.5, rows_[a][0].top() + 8, 1, rows_[b - 1][0].bottom() - rows_[a][0].top() -
                              16), c("string"))
        clip = QRectF(self.view.viewport().rect()) if p.device() is self.view.viewport() else None
        split = next((ln.split for ln in (lines or ()) if ln.kind == "top" and ln.split), None)
        split_at = None
        hot = self.view.hot_eps(row.key) if clip is not None else ()     # row 28: as a row's line, its hover look
        shows = self._show_lines(row, rows_)          # LM11b: a group's show lines
        above = {r.bottom() + 1: r.top() for r, _show in shows}
        for i, (r, ep, draw, ident, extra) in enumerate(pictures):
            if split is not None and i == split:       # the top-20 line runs through this row (A-12): drawn here too,
                top = above.get(r.top(), r.top())      # above its show's line where one stands (LM11b)
                split_at = QRect(r.left() - 8, top - 2, r.width() + 8, 4)
            if clip is not None and not clip.intersects(QRectF(r)):
                continue
            if clip is not None:                       # on screen: painted once into a pixmap, reused while unchanged
                on = ep.id in hot
                pix = self._sprite("ep", ep, r.size(), dpr, on, draw, ident=ident,
                                   ground="row-hover" if on else "surface" if hero else "open-row",
                                   to=(p, r.topLeft()), extra=extra)
                if pix is not None:
                    p.drawPixmap(r.topLeft(), pix)
                if ep.id in self.view.pressed_ids and ep.status is not None:      # round 8 row 45: over its picture
                    self._paint_pressed(p, self._ep_pill(r, ep, dpr))
                if ep.id in self.view.marked:                                      # ... a menu's press (IK-2)
                    self._ep_marked(p, r, ep, dpr)
                if self.view.stop_marks() and ep.status is not None and ep.status.kind == "mining":      # R47
                    self._paint_stop_over(p, self._ep_pill(r, ep, dpr), ep.status, (ep,), dpr,
                                          "row-hover" if on else "surface" if hero else "open-row")
                if on:
                    m, side = self._episode_cols(r)["more"], rl("anki-icon")
                    icon(p, "more", QRectF(m.center().x() - side / 2 + 0.5, m.center().y() - side / 2 + 0.5, side,
                                           side), c("ink-dim"))
            else:
                p.save()
                p.translate(r.topLeft())
                draw(p)
                p.restore()
                if ep.id in self.view.pressed_ids and ep.status is not None:
                    self._paint_pressed(p, self._ep_pill(r, ep, dpr))
                if ep.id in self.view.marked:
                    self._ep_marked(p, r, ep, dpr)
                if self.view.stop_marks() and ep.status is not None and ep.status.kind == "mining":      # R47
                    self._paint_stop_over(p, self._ep_pill(r, ep, dpr), ep.status, (ep,), dpr,
                                          "surface" if hero else "open-row")
        for r, show in shows:                         # --- LM11b: each a picture of its own, as an episode's line
            if clip is not None and not clip.intersects(QRectF(r)):
                continue
            w, h = r.width(), r.height()
            draw = lambda q, w=w, h=h, show=show: self._paint_show_line(q, QRect(0, 0, w, h), show, dpr)
            if clip is not None:
                pix = self._sprite("ep", ShowLine(show), r.size(), dpr, False, draw, ident=(("show", show), hero),
                                   ground="surface" if hero else "open-row", to=(p, r.topLeft()))
                if pix is not None:
                    p.drawPixmap(r.topLeft(), pix)
            else:
                p.save()
                p.translate(r.topLeft())
                draw(p)
                p.restore()
        if split_at is not None:
            self._paint_line(p, lines_top(lines), split_at, dpr)

    def _paint_show_line(self, p, r, show, dpr):
        """LM11b: a group's show line — the show's name in the row's dim sub-line style, from the stones' column to
        where the episodes' ▶ stands, its foot a little nearer its episodes than the run above."""
        cols = self._episode_cols(r)
        left = cols["tick"].left()
        TEXT.draw(p, left, r.center().y() + round(2 * fz()), show, "row-sub", cols["text_right"] - left,
                  c("ink-dim"), weight=600, dpr=dpr)

    def _ep_pill(self, r, ep, dpr):
        """An episode line's status pill, in the line `r`."""
        size = pill_size(ep.status, dpr)
        return QRect(self._episode_cols(r)["stat"].right() - size.width(), r.center().y() - size.height() // 2,
                     size.width(), size.height())

    def _paint_episode(self, p, r, ep, dpr, audio=False, stone=None, sheet=None):
        """One episode line (an open row's): its stone (the tick until the stones' sheet is there), its label, its
        numbers, status, mark and ▶ (`audio`: its show's media)."""
        cols = self._episode_cols(r)
        tick = QRectF(cols["tick"])
        if stone is not None and sheet is not None:
            what, dim, big = stone
            at = QPointF(tick.center())
            p.save()
            if dim:
                p.setOpacity(rl("dim"))
            sheet.draw(p, at, what)
            p.restore()
            if big:
                sheet.draw(p, at, ("ring", what[4]))
        elif ep.watched:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("accent"))
            p.drawEllipse(tick)
            icon(p, "check", tick.adjusted(4, 4, -4, -4), style.qcolor(theme.FIXED["on-accent"]))
        else:
            p.setPen(QPen(c("line-hi"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(tick.adjusted(0.75, 0.75, -0.75, -0.75))
        text_w = cols["text_right"] - cols["text_left"]
        TEXT.draw(p, cols["text_left"], r.center().y(), ep.label, "episode-label", text_w * 0.6,
                  c("ink-dim" if ep.watched else "ink"), dpr=dpr)
        paint_diff(p, ep.pct, view_tone(ep.pct), ep.n_new, cols["diff"].right(), r.center().y(), dpr, ep.new_faded)
        right = cols["stat"].right()
        if ep.status is not None:
            sr = self._ep_pill(r, ep, dpr)
            paint_pill(p, ep.status, sr, dpr, audio=audio)
            right = sr.left() - 4
        if ep.mark is not None:
            paint_mark(p, ep.mark, right, r.center().y(), dpr, audio=audio)
        if ep.can_play:                              # row 55: nothing to open, no ▶
            self._paint_play_button(p, cols["play"])

    def _paint_open_hero(self, p, row, rect, lines, hovered, focused, dpr):
        """An open Up Next: its head painted once into a pixmap, the rest of its slab drawn around the episodes (each
        its own pixmap) — a repaint of the open hero draws no text or cover afresh (review B-13)."""
        g = self._hero_geometry(row, rect, lines)
        head = g["head"]
        local = QRect(0, 0, rect.width(), rect.height())
        p.fillRect(g["box"], c("surface"))          # the slab first, whole, then the head over it (C-3)
        pix = self._sprite(HERO, row, QSize(rect.width(), head.height()), dpr, hovered,
                           lambda q: self._paint_hero(q, row, local, lines, hovered, dpr, None),
                           ident=(row.key, "open"), ground="surface", to=(p, QPoint(rect.left(), head.top())))
        if pix is not None:
            p.drawPixmap(QPoint(rect.left(), head.top()), pix)
        if self.view.stop_marks() and row.status is not None and row.status.kind == "mining":     # --- R47
            self._paint_stop_over(p, g["status"], row.status, row.episodes, dpr)
        if focused:
            self._focus_ring(p, g["box"], theme.RADII["r-sm"])
        self._paint_episodes(p, row, g["eps"], dpr, hero=True, lines=lines)

    def _paint_hero(self, p, row, rect, lines, hovered, dpr, sheet):
        """Up Next's head (the old mock's card, flat): no border and no iris bar (the iris is for what the hand
        opened); while it's open, no string (G16)."""
        g = self._hero_geometry(row, rect, lines)
        self._paint_cover(p, row.cover_title, g["cover"], dpr, large=True, ref=row.cover)        # W3.2 Q6
        self._paint_watched_bar(p, row, g["cover"])
        nxt = row.episodes[row.next_index]
        e = g["eyebrow"]
        icon(p, "dot", QRectF(e.left(), e.center().y() - 3.5, 7, 7), c("accent"))
        TEXT.draw(p, e.left() + 14, e.center().y(), strings.ROWS_UP_NEXT, "eyebrow", e.width() - 14, c("accent"),
                  dpr=dpr)
        t = g["title"]
        ep_txt = row.title_ep
        ep_w = TEXT.metrics("hero-title", 500, dpr).horizontalAdvance(ep_txt) + 8 if ep_txt else 0
        tw, _ = TEXT.draw(p, t.left(), t.center().y(), heard_title(row), "hero-title", t.width() - ep_w, c("ink"),
                          dpr=dpr)
        if ep_txt:
            TEXT.draw(p, t.left() + tw + 7, t.center().y(), ep_txt, "hero-title", ep_w, c("ink-dim"), weight=500,
                      dpr=dpr)
        if g["sub"] is not None:
            s = g["sub"]
            if row.source == "hato":
                TEXT.draw(p, s.left(), s.center().y(), strings.ROWS_SOURCE["hato"], "hero-sub", s.width(), c("ink"),
                          weight=600, dpr=dpr)
            elif row.media == "youtube" and row.line:
                TEXT.draw(p, s.left(), s.center().y(), row.line, "hero-sub", min(s.width(),
                                                                                    theme.SIZES["channel-cap"] * fz()),
                          c("ink-dim"), dpr=dpr)
        st = g["stats"]
        if view_rows.audio_only(row):                  # a5-2: an audiobook alone says so, never *not analysed yet*
            TEXT.draw(p, st.left(), st.center().y(), row.line, "hero-sub", st.width(), c("ink-dim"), dpr=dpr)
        elif nxt.pct is None:
            TEXT.draw(p, st.left(), st.center().y(), strings.ROWS_HERO_STATS_NONE, "hero-sub", st.width(),
                      c("ink-dim"), dpr=dpr)
        else:
            known = strings.ROWS_HERO_KNOWN.format(pct=round(nxt.pct))
            j = g["journey"]
            if j is None:                               # row 36: no *N new* yet, so no link — the % alone
                known = known.rstrip(" ·")
            TEXT.draw(p, st.left(), st.center().y(), known, "hero-sub", st.width(), c("ink-dim"), dpr=dpr)
            if j is not None:
                TEXT.draw(p, j.left(), st.center().y(), strings.ROWS_HERO_NEW_LINK.format(n=nxt.n_new), "hero-sub",
                          j.width(), faded("accent", FADED_ALPHA) if nxt.new_faded else c("accent"), dpr=dpr)
        if self.view.model().open_key != row.key and not view_rows.audio_only(row):   # G16; a5-2: none alone
            s = g["string"]
            self._paint_string(p, self._info(row)[0], s, s.top() + s.height() / 2, sheet, ring=True, big=True)
        self._paint_play(p, g["play"], row, nxt, dpr, sheet)
        self._paint_done(p, g["done"], nxt, dpr)
        mid = g["more"].center().y()
        # Q33: the head shows the row's own status, as every row does (the show's ✓ N); Up Next's own count stays on
        # its episode line
        if row.status is not None and row.status.kind in ("in_anki", "mining"):
            self._paint_stat(p, row.status, g["status"], mid, dpr)     # N in Anki at rest
        elif row.status is not None and hovered:    # the other statuses on hover, as a row's
            item = next((it for it in self._hover_items(row._replace(studying=False))
                         if it[0] == "status" or it[0] in ACTION_NAMES), None)
            if item is not None:
                r = g["status"]
                side = rl("anki-icon")
                icon(p, item[1], QRectF(r.right() - side - 4, mid - side / 2, side, side), c(item[2]))
        icon(p, "more", QRectF(g["more"].center().x() - 7, mid - 7, 14, 14), c("ink-dim"))

    @staticmethod
    def _watch_label(row):
        """Up Next's ▶ button's words: its verb (Watch / Listen / Read); with nothing to play, the plain words in its
        place — *Looking…* until the video check answered (R55-A), *Online*, or *No <its media word>* (No video)."""
        nxt = row.episodes[row.next_index]
        if nxt.can_play:
            return row.verb
        if nxt.looking:
            return strings.ROWS_LOOKING_BUTTON
        if row.media == "youtube":
            return strings.ROWS_ONLINE_BUTTON
        return strings.ROWS_NO_MEDIA_BUTTON.format(word=row.media_word)

    def _paint_play(self, p, r, row, nxt, dpr, sheet):
        """▶ Play (W3.1a §1 *Up Next*): the trillion in its kind's gem and the verb, on the kind's base colour; with
        nothing to play, plain muted words in its place — *Looking…*, *No video*, *Online* (R55-B, Sonic: no frame, no
        triangle, nothing button-shaped; its tip says why)."""
        if not nxt.can_play:
            x = r.left() + 13                         # the room the verb has beside the trillion: never elided
            TEXT.draw(p, x, r.center().y(), self._watch_label(row), "button", r.right() - x, c("ink-dim"), dpr=dpr)
            return
        rr = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        gem = stone_plan.gem_of(row.media, row.source == "hato")
        side = rl("hero-trillion")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(theme.GEM[gem][0]))
        p.drawRoundedRect(rr, theme.RADII["button"], theme.RADII["button"])
        ink, label = c("ink"), row.verb
        x = r.left() + 13
        box = QRectF(x, r.center().y() - side / 2, side, side)
        what = ("trillion", gem)
        if sheet is not None:                         # the trillion: a blit, shrunk into its box
            size = sheet.size_of(what)
            k = side / max(size.width(), size.height())
            src = sheet.rect_of(what, QPointF(0, 0))
            p.save()
            p.translate(box.center())
            p.scale(k, k)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            sheet.draw(p, QPointF(-src.center().x(), -src.center().y()), what)
            p.restore()
        else:
            icon(p, "play", box.adjusted(3, 3, -3, -3), ink)
        TEXT.draw(p, x + side + 7, r.center().y(), label, "button", r.right() - x - side - 7, ink, dpr=dpr)

    def _paint_done(self, p, r, nxt, dpr):
        """✓ Done, quiet beside ▶ Play (A2 #1); drawn whole once every file is watched too: it offers Move to Finished
        then (G3.2)."""
        p.save()
        rr = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(c("line-hi"), 1))
        p.setBrush(c("raised"))
        p.drawRoundedRect(rr, theme.RADII["button"], theme.RADII["button"])
        icon(p, "check", QRectF(r.left() + 13, r.center().y() - 7, 14, 14), c("ink"))
        TEXT.draw(p, r.left() + 13 + 14 + 7, r.center().y(), strings.ROWS_DONE, "button", r.width() - 13 - 21,
                  c("ink"), dpr=dpr)
        p.restore()

    def _paint_need(self, p, need, rect, dpr):
        f = fz()
        box = QRectF(rect).adjusted(0.5, 0.5, -0.5, -12.5)
        radius = theme.RADII["r"]
        path = QPainterPath()
        path.addRoundedRect(box, radius, radius)
        p.fillPath(path, c("surface"))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(box.left(), box.top(), 3, box.height()), c("warn"))
        p.restore()
        p.setPen(QPen(c("line"), 1))
        p.drawPath(path)
        cov = QRect(round(box.left() + 18), round(box.top() + 16), 44, 63)
        p.drawPixmap(cov.topLeft(), cover(need.cover_title, 44, 63, dpr, ref=getattr(need, "cover", None)))     # W3.2 Q6
        x = cov.right() + 16
        w = box.right() - 18 - x
        y = box.top() + 16
        th = 14 * f * 1.45
        TEXT.draw(p, x, y + th / 2, need.title, "needs-title", w, c("ink"), weight=700, dpr=dpr)
        y += th + 10                                 # its line is in the tooltip (G2.3 N1)
        rows_h = 34 * f
        listbox = QRectF(x, y, min(w, 760 * f), len(need.episodes) * rows_h)
        p.setPen(QPen(c("line"), 1))
        p.setBrush(c("bg"))
        p.drawRoundedRect(listbox.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        for i, (label, what) in enumerate(need.episodes):
            ry = listbox.top() + i * rows_h
            if i:
                p.setPen(QPen(c("needs-row-border"), 1))
                p.drawLine(QPointF(listbox.left() + 1, ry + 0.5), QPointF(listbox.right() - 1, ry + 0.5))
            slot = max(round(52 * f), TEXT.draw(p, listbox.left() + 10, ry + rows_h / 2, label, "hero-sub", 120 * f,
                                                c("ink"), weight=600, dpr=dpr)[0])     # the mock's .mrow .epn: 52 px
            x0 = listbox.left() + 10 + slot + 10
            TEXT.draw(p, x0, ry + rows_h / 2, what, "needs-file", listbox.right() - 10 - x0, c("ink-dim"), dpr=dpr)

    def _paint_failure(self, p, entry, rect, dpr):
        f = fz()
        box = QRectF(rect).adjusted(0.5, 0.5, -0.5, -12.5)
        radius = theme.RADII["r"]
        path = QPainterPath()
        path.addRoundedRect(box, radius, radius)
        p.fillPath(path, c("surface"))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(box.left(), box.top(), 3, box.height()), c("warn"))
        p.restore()
        p.setPen(QPen(c("line"), 1))
        p.drawPath(path)
        x, w = box.left() + 18, box.width() - 36
        y = box.top() + 16
        th = 14 * f * 1.45
        TEXT.draw(p, x, y + th / 2, entry.text, "needs-title", w, c("ink" if not entry.seen else "ink-dim"),
                  weight=700, dpr=dpr)
        y += th + 4
        TEXT.draw(p, x, y + 12.5 * f * 1.45 / 2, strings.ROWS_FAILURE_LINE, "hero-sub", w, c("ink-dim"), dpr=dpr)


def whole_step(dpr):
    """The smallest scroll step (logical px) whose device size is whole at this ratio: 1 at 100 / 200 %, 2 at 150 /
    250 %, 4 at 125 / 175 % (review C-2)."""
    for q in (1, 2, 3, 4):
        if abs(q * dpr - round(q * dpr)) < 1e-6:
            return q
    return 1


NO_DRAG = frozenset(("play", "more", "more-ep", "up", "down", "done", "journey", "put-back")) | ACTION_NAMES   # buttons (W3.2 Q4:
#                                                                                       put-back; P4.1 L2: the statuses')
# row 55, R55-B: Up Next's *No video* / *Online* / *Looking…* in ▶'s place is plain words on the card, a tip-only part
# ("no-play"): never a button's place — a press there is the card's (it drags it, Ctrl+click picks it), and `_act`
# does nothing with it


def _rest_of(row, k):                                # --- W3.2 Q8: the files from episode `k` on, in words
    eps = row.episodes[k:]
    nums = [e.number for e in eps if e.number is not None]
    if len(nums) == len(eps) and nums:
        return strings.ITEM_RANGE.format(a=nums[0], b=nums[-1]) if len(nums) > 1 else \
            strings.ITEM_RANGE_ONE.format(a=nums[0])
    return eps[0].label if len(eps) == 1 else f"{eps[0].label} – {eps[-1].label}"


# --- LM11b: an opened group's show lines — each show's episodes under its name: where one show ends reads at once
ShowLine = namedtuple("ShowLine", "show")           # a show line's picture payload (`_same_face`: its name alone)


def show_starts(row):
    """{k: show}: the episodes of an opened group a show line stands above, with the show's name — its first, and each
    where the show changes (`Episode.show_key`, the service's own reading of which show a file is of). Empty for a run,
    a group of one show (never `row.group`) and a group from a cache from before (no `show_key`): those look as
    before."""
    if not getattr(row, "group", False):
        return {}
    out, last = {}, None
    for k, ep in enumerate(row.episodes):
        here = getattr(ep, "show_key", None)
        if here is None or not ep.show:
            return {}
        if here != last:
            out[k], last = ep.show, here
    return out if len(out) > 1 else {}
# --- end LM11b show lines


def _same_payload(a, b):
    """A part's payload at the release is the press's: the same object, or the same episode (a refresh between)."""
    return a is b or (a is not None and b is not None and getattr(a, "id", object()) == getattr(b, "id", None))


def lines_top(lines):
    return next(ln for ln in lines if ln.kind == "top")


def view_tone(pct):
    return view_rows.pct_tone(pct)


# --- the view ----------------------------------------------------------------------------------------------------------- #
class _Touch:
    """A Current row's hover look in motion (W3.1a §1 *Rows*, §3): its lift (px, up), how far its neighbours part (px),
    how far its hover picture has faded in (0–1), and the springs and fade moving them."""
    __slots__ = ("lift", "nb", "fade", "s_lift", "s_nb", "a_fade", "on")

    def __init__(self):
        self.lift = self.nb = self.fade = 0.0
        self.s_lift = self.s_nb = self.a_fade = None
        self.on = False


_PICKERS = weakref.WeakSet()                         # A4: every list that picks (`picks_join`)


def picks_join(owner):
    """A4: `owner` picks (a list, Goal's sheet, New arrivals' tray): it has `clear_picks()`."""
    _PICKERS.add(owner)


def picks_here(owner):
    """A4 (PROVISIONAL): the picks live in one list at a time — `owner` picked something, so every other list of its
    window lets its picks go (picking in Goal drops Current's)."""
    from PyQt6 import sip
    win = owner.window()
    for other in list(_PICKERS):
        if other is not owner and not sip.isdeleted(other) and other.window() is win:
            other.clear_picks()


class _Picks(QObject):
    """LM11b G4: the list's picks as the shell's `EscapeRouter` sees an overlay — open while anything is picked; Esc
    and Back close it (every pick let go), as they close every overlay of the window."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def isVisible(self):
        return bool(self.view.picked_rows or self.view.picked_eps)

    def window(self):
        return self.view.window()

    def close(self):
        self.view.clear_picks()


class RowsView(QListView):
    """A painted list: hover, tooltips and clicks by the delegate's parts; a click on a row opens or closes it; ▶ asks
    for its file (`play_requested`); a stone or Up Next's ✓ Done asks for a Done (`done_requested`); Enter and Space
    open the current row."""

    play_requested = pyqtSignal(object)            # an Episode
    opened = pyqtSignal(object)                    # the key opened (None: closed)
    done_requested = pyqtSignal(object, object)    # (the Row, the Episode): one path for every Done (S12)
    nudge_requested = pyqtSignal(object, int)      # (the Row, -1 up / +1 down): ↑ ↓ in the number's column (A2 #13)
    menu_requested = pyqtSignal(object, object)    # (the Row, the global QPoint): its ⋯
    journey_requested = pyqtSignal(object, object)     # (the Row, the Episode): Up Next's *N new words ↗*
    put_back_requested = pyqtSignal(object)        # --- W3.2 Q4: (the Finished Row): its *Put back*
    split_requested = pyqtSignal(object, object)   # --- W3.2 Q8: (the Row, the episode that starts the new part): ✂
    episode_menu_requested = pyqtSignal(object, object, object)     # row 28: (the Row, the Episode, the global QPoint)
    line_requested = pyqtSignal(str)               # --- P4.1 L2 (row 4.1.14): a line clicked ("top"): its setting
    # --- P4.1 L2 (4.1.11): the statuses' buttons — (the Row, the item ids) *Mine now* / *Mine this*; (the Row, the
    # Episode) No video's *Link…*
    mine_requested = pyqtSignal(object, object)
    link_requested = pyqtSignal(object, object)
    find_folder_requested = pyqtSignal(object, object)      # MV-2: (the Row, the Episode) — *Find its folder…*
    # --- end P4.1 L2
    stop_requested = pyqtSignal(object, object)    # --- R47: (the Row, the Ask: its file, its job) a Mining pill's Stop

    def __init__(self, name, tooltips=None, parent=None):
        super().__init__(parent)
        self.setObjectName("rows")
        self.setAccessibleName(name)
        self.tooltips = tooltips
        self.setModel(RowsModel(self))
        self.delegate = RowDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.Shape.NoFrame)
        # an opaque viewport: a scroll then moves the pixels already drawn and paints only the strip that came into
        # view (a see-through viewport is repainted whole on every scroll step). WA_OpaquePaintEvent, with the ground
        # filled in `paintEvent` where it paints (the gaps between rows, the space under the last): autoFillBackground
        # did it once, but the app's style sheet turns it off again when it polishes the viewport — every 40 px step
        # then repainted all ~10 rows (W2.2 profile, 2026-10-08).
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSpacing(0)
        self.setLayoutMode(LAYOUT_MODE)
        if LAYOUT_MODE == QListView.LayoutMode.Batched:
            self.setBatchSize(LAYOUT_BATCH)
        self.verticalScrollBar().setSingleStep(round(theme.SIZES["row"] * fz() / 2))
        # a step the user makes (a drag, a touchpad, a notch) lands on a whole device pixel: Qt moves the pixels already
        # drawn only when the step's device size is whole; any other step repaints the whole list (review C-2, probed:
        # 1, 7, 13 px at 150 % → 514 px painted)
        self.verticalScrollBar().actionTriggered.connect(self._snap_step)
        self._hover = None
        self.focus_visible = False                   # CSS's :focus-visible: the ring after a key, never after a click
        self.connect_off = None                      # --- P4.1 L2: why Connect may not run (`feed.OFF_*`), or None
        self.action_focus = None                     # --- P4.1 L2: (row key, part name) the keyboard is on (→)
        self.action_menu = None                      # --- P4.1 L2: No video's last menu (tests)
        self.looks_changed = False                   # the last set_entries changed what the list shows
        self._restore = None
        self.warm_like = None                        # the shown list, while this one is hidden (its width and height)
        self._moved = 0.0                            # when it last scrolled or changed (`_rest`)
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)
        # a row's first paint (its text laid out, its cover drawn: up to ~15 ms, bench 7) moved out of the scroll's
        # frames: once the list rests, the rows just past the screen are painted ahead, one per turn of the loop
        self._warm = QTimer(self)
        self._warm.setSingleShot(True)
        self._warm.setInterval(WARM_IDLE_MS)
        self._warm.timeout.connect(self._warm_one)
        self.verticalScrollBar().valueChanged.connect(self._rest)
        self.verticalScrollBar().valueChanged.connect(self._hand_again)      # --- row 28 (AD-3)
        # the pointer resting on a closed row paints its episodes ahead (one a turn), so opening it only blits
        self._hover_warm = QTimer(self)
        self._hover_warm.setSingleShot(True)
        self._hover_warm.setInterval(HOVER_WARM_MS)
        self._hover_warm.timeout.connect(self._warm_hovered)
        self._touch = {}                             # a row key -> its hover look in motion (`_Touch`)
        self._active = set()                         # the row keys showing their hover look (the hand's, the keyboard's)
        self._key_rows = (None, {})                  # (the model's keys, key -> row) for the touches' repaints
        self.line_hover = None                       # (row, line kind) of the line under the hand: it lights a step
        # W3.1a §2, the drag (`app/qt/drag.py`): a press records its part and acts on its release over the same part,
        # unless the hand travels `drag-start-px` first — then the drag has it (B1: a drag begun on a stone never marks
        # it watched, one begun on a row never opens it)
        self.drag = None                             # the drag controller (Current's list only)
        self._press = None                           # (row, part name, payload, pos, key): a press waiting for release
        self.parting = None                          # the running drag's parting (`drag.Parting`): offsets, the slot
        self.landing = None                          # the key a drop's ghost is gliding onto: its slot shows meanwhile
        self.saving = frozenset()                    # keys whose moves wait for a busy store (*saving…*)
        self.pressed_ids = frozenset()               # round 8 row 45: file ids asked for (*Mine now*), not yet moved
        self._pressed_at = {}                        # ... each one's status at the press (it leaves when that changes)
        self._turn = None                            # ... their marks' phase (`motion.Turn`) while any is pressed
        self._turn_rects = []                        # ... where they were painted last (repainted alone as they turn)
        self._turn_idle = False                      # ... a frame found none painted (two: the clock stops, A-6)
        self.press_moved = None                      # ... `press_moved(ids)`: their status moved — the presses' owner
                                                     # ends them (`mine_actions`); None: this list lets them go
        self.stopping_ids = frozenset()              # --- R47: file ids whose Stop was pressed, not yet stopped
        self._stopping_at = {}                       # ... each one's row key at the press
        self.stop_moved = None                       # ... `stop_moved(ids)`: they left Mining — the presses' owner
        self.stop_hot = None                         # ... the Stop pill under the hand (its QRect): it reads ■ Stop
        self.marked = {}                             # ... file id -> the parts its live presses mark, oldest first
        #                                              (`mark_ids`, IK-2: one per press, the newest painted)
        self.seam = None                             # --- W3.2 Q8: (row key, episode id) of the ✂ seam under the hand
        self.ep_hover = None                         # --- W3.2 Q8: (row key, episode id) the hand was last on
        self.ep_hot = None                           # --- row 28: (row key, episode id) under the hand now
        self.ep_key = None                           # --- row 28: (row key, episode id) the keyboard is on (↓ in an
        #                                              opened row steps into its episodes, ↑ back out)
        self.join_key = None                         # --- W3.2 Q8: the part a drag would join (outlined)
        self.join_label = strings.JOIN_LABEL         # LM11b G2: its words (*Drop to group* on another show)
        # --- LM11b G4: the selection *Group…* takes — Ctrl+click on a row (or Ctrl+Space) picks the row, Shift+click
        # the rows from the last one Ctrl picked to this one instead (Ctrl+Shift+click adds them), Ctrl+click on an
        # opened row's stone that episode; under Ctrl or
        # Shift a row's part never acts (no Done, no ▶, no ⋯). A plain click, a drag, Esc or Back (the shell's router,
        # through `picks`) and a view without its key let them go
        self.pickable = None                         # (row) -> whether it may be picked: Current's (item_menu) and,
        #                                              A4, Finished's list (finished.py); None picks nothing
        self.picked_rows = set()                     # row keys
        self.picked_eps = set()                      # (row key, episode id)
        self.picks = _Picks(self)
        self._press_pick = None                      # the press's pick: "ctrl", "shift" or None
        self._pick_anchor = None                     # the row key Ctrl picked last: a Shift range starts there
        self._keep_picks = False                     # A4: a plain press on a picked row keeps them for its drag (its
        #                                              release, a click, lets them go)
        picks_join(self)                             # A4: picks in one list at a time
        # --- end LM11b G4
        self.opened.connect(self._closed_picks)                         # --- LM11b H-B5
        stones.notifier().ready.connect(self._sheet_ready)
        qcovers.notifier().ready.connect(self._cover_ready)              # --- W3.2 Q6

    def paintEvent(self, event):
        p = QPainter(self.viewport())
        p.fillRect(event.rect(), c("bg"))
        p.end()
        super().paintEvent(event)
        if self.parting is not None:                 # a drag: the rows it moved into view, and the slot it opens
            self.parting.paint_over(self, event)
        if self.seam is not None or self.join_key is not None:      # --- W3.2 Q8
            self._paint_q8(event)

    # --- W3.2 Q8: the seam under the hand, the part a drag would join ----------------------------------------------- #
    def _q8_rect(self, what):
        """The seam's rect (`what` = (key, episode id)) or the part's slot (`what` = key) as laid out now, or None."""
        model = self.model()
        key = what[0] if isinstance(what, tuple) else what
        i = next((n for n, e in enumerate(model.entries) if getattr(e[1], "key", None) == key), None)
        if i is None:
            return None
        rect = self.visualRect(model.index(i, 0))
        if not isinstance(what, tuple):
            return self.delegate.slot_rect(model.entries[i][0], rect, model.entries[i][2])
        return next((pt[1] for pt in self.delegate.parts(model.entries[i], rect)
                     if pt[0] == "seam" and pt[3].id == what[1]), None)

    def _paint_q8(self, event):
        p = QPainter(self.viewport())
        p.setClipRect(event.rect())
        if self.seam is not None:
            r = self._q8_rect(self.seam)
            if r is not None:
                self.delegate.paint_seam(p, r)
        if self.join_key is not None:
            r = self._q8_rect(self.join_key)
            if r is not None:
                self.delegate.paint_join(p, r, self.join_label)
        p.end()

    def _q8_update(self, what):
        r = self._q8_rect(what) if what is not None else None
        if r is not None:
            self.viewport().update(r.adjusted(-4, -16, 4, 16))

    def set_seam(self, seam):
        """The ✂ seam under the hand (or None): only its strip repainted, as it comes and as it goes."""
        if seam == self.seam:
            return
        old, self.seam = self.seam, seam
        self._q8_update(old)
        self._q8_update(seam)

    def set_join(self, key, label=None):
        """The part a drag would join (or None): its outline and `label` (None: *Drop to join*), that row alone
        repainted."""
        label = label or strings.JOIN_LABEL
        if key == self.join_key and label == self.join_label:
            return
        old, self.join_key, self.join_label = self.join_key, key, label
        self._q8_update(old)
        self._q8_update(key)

    # --- row 28: an opened row's episode under the hand or the keyboard shows its hover look and its own ⋯ ------- #
    def hot_eps(self, key):
        """The episode ids of row `key` showing their hover look: the hand's, and the keyboard's while its ring shows."""
        out = set()
        if self.ep_hot is not None and self.ep_hot[0] == key:
            out.add(self.ep_hot[1])
        if self.ep_key is not None and self.ep_key[0] == key and self.focus_visible and self.hasFocus():
            out.add(self.ep_key[1])
        return out

    def _ep_line(self, what):
        """(index, QRect) of episode `what` = (row key, episode id) of the opened row, as laid out now, or None."""
        model = self.model()
        if what is None or model.open_key != what[0]:
            return None
        i = self._row_of_key(what[0])
        if i is None:
            return None
        idx = model.index(i, 0)
        r = next((r for r, ep in self.delegate.episode_lines(model.entries[i], self.visualRect(idx))
                  if ep.id == what[1]), None)
        return (idx, r) if r is not None else None

    def _set_ep(self, field, what):
        """The hand's (`ep_hot`) or the keyboard's (`ep_key`) episode: only its line repainted, as it goes and comes."""
        old = getattr(self, field)
        if old == what:
            return
        setattr(self, field, what)
        for w in (old, what):
            at = self._ep_line(w)
            if at is not None:
                self.viewport().update(at[1])

    def _ep_under(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        entry = self.model().entries[idx.row()]
        ep = self.delegate.episode_at(entry, self.visualRect(idx), pos)
        return (entry[1].key, ep.id) if ep is not None else None

    def _hand_again(self, *_args):
        """The list moved under a resting hand (a wheel's scroll, a refresh): its episode read again where the cursor
        is — Qt sends no move — so the hover look and ⋯ stay on the line under it (one lookup; only lines that change
        repaint). Nothing while no row is open and no episode is lit."""
        if self.ep_hot is None and self.model().open_key is None:
            return
        pos = self.viewport().mapFromGlobal(QCursor.pos())
        self._set_ep("ep_hot", self._ep_under(pos) if self.viewport().rect().contains(pos) else None)

    def _action_parts(self, idx, entry):
        """The status buttons → can reach on row `entry`: on an opened row's episode (the keyboard's), that episode's
        own; on its head, the head's — never an episode's button while the keyboard is on the head (AD-2)."""
        rect = self.visualRect(idx)
        parts = [pt for pt in self.delegate.parts(entry, rect) if pt[0] in ACTION_NAMES]
        if entry[0] not in (HERO, ROW) or self.model().open_key != entry[1].key:
            return parts
        lines = self.delegate.episode_lines(entry, rect)
        on = self.ep_key[1] if self.ep_key is not None and self.ep_key[0] == entry[1].key else None
        if on is None:
            return [pt for pt in parts if not any(r.contains(pt[1]) for r, _ep in lines)]
        mine = next((r for r, ep in lines if ep.id == on), None)
        return [pt for pt in parts if mine is not None and mine.contains(pt[1])]

    def _episode_key(self, event):
        """↓ on an opened row steps into its episodes and on through them, ↑ back out to its head; Enter, Space or the
        menu key on an episode opens its ⋯ (its tip shown, as on hover). -> handled."""
        idx = self.currentIndex()
        entry = self.model().entries[idx.row()] if idx.isValid() else None
        if entry is None or entry[0] not in (HERO, ROW) or self.model().open_key != entry[1].key or \
                event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return False
        eps, key = entry[1].episodes, event.key()
        at = next((k for k, e in enumerate(eps) if self.ep_key == (entry[1].key, e.id)), None)
        if key == Qt.Key.Key_Down:
            if at is not None and at + 1 >= len(eps):
                nxt = self.moveCursor(QAbstractItemView.CursorAction.MoveDown, Qt.KeyboardModifier.NoModifier)
                if not nxt.isValid() or nxt.row() == idx.row():
                    return True                      # the list's last row: the keyboard stays on its last (AD-4)
                self._set_ep("ep_key", None)
                return False                         # past the last: on to the next row
            k = 0 if at is None else at + 1
        elif key == Qt.Key.Key_Up:
            if at is None:
                return False
            k = at - 1 if at > 0 else None
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Menu) and at is not None:
            self.open_episode_menu(idx, eps[at])
            return True
        else:
            return False
        self._set_ep("ep_key", None if k is None else (entry[1].key, eps[k].id))
        self.action_focus = None                     # AD-2: the keyboard's on an episode line now, not on a button
        line = self._ep_line(self.ep_key)
        if line is not None:                         # the episode stays in view
            vp, r, bar = self.viewport().rect(), line[1], self.verticalScrollBar()
            if r.bottom() > vp.bottom():
                bar.setValue(bar.value() + r.bottom() - vp.bottom())
            elif r.top() < vp.top():
                bar.setValue(bar.value() - (vp.top() - r.top()))
            more = next((pt for pt in self.delegate.parts(entry, self.visualRect(idx)) if pt[0] == "more-ep"), None)
            if more is not None and self.tooltips is not None:
                self.tooltips.request(self.viewport(), more[1], more[2])
        return True

    def open_episode_menu(self, idx, ep, at=None):
        """The episode's ⋯ menu asked for (`episode_menu_requested`): at `at` (a right-click's global point), else
        under its ⋯."""
        entry = self.model().entries[idx.row()]
        if at is None:
            more = next((pt for pt in self.delegate.parts(entry, self.visualRect(idx))
                         if pt[0] == "more-ep" and pt[3].id == ep.id), None)
            rect = more[1] if more is not None else self.visualRect(idx)
            at = self.viewport().mapToGlobal(rect.bottomLeft())
        self.episode_menu_requested.emit(entry[1], ep, at)
    # --- end row 28

    def _q8_hover(self, at, part):
        """The seam under the hand lit; the episode the hand is on remembered (⋯'s *Split here* after it)."""
        entry = self.model().entries[at.row()] if at.isValid() else None
        key = getattr(entry[1], "key", None) if entry is not None else None
        on_seam = part is not None and part[0] == "seam"
        self.set_seam((key, part[3].id) if on_seam else None)
        ep = part[3] if part is not None else None
        if key is not None and ep is not None and entry[0] in (HERO, ROW) and \
                any(e is ep for e in entry[1].episodes):
            self.ep_hover = (key, ep.id)
    # --- end W3.2 Q8

    # entries ---------------------------------------------------------------------------------------------------- #
    # --- round 8 row 45: *Mine now* pressed (`mine_actions._ask`) --------------------------------------------- #
    def _where(self, ids, keys=None):
        """{id: (row index, its episode)} of the files `ids` this list shows. `keys` ({id: the row's key it was in}):
        looked up in those rows alone, the whole list walked only for one not found there (A-12: a view while one is
        pressed never walks every episode)."""
        entries, found = self.model().entries, {}
        if keys:
            at = {row.key: n for n, (kind, row, _lines) in enumerate(entries) if kind in (HERO, ROW, FINISHED)}
            for i in ids:
                n = at.get(keys.get(i))
                ep = None if n is None else next((e for e in entries[n][1].episodes if e.id == i), None)
                if ep is not None:
                    found[i] = (n, ep)
        left = set(ids) - set(found)
        if left:
            for n, (kind, row, _lines) in enumerate(entries):
                for ep in (row.episodes if kind in (HERO, ROW, FINISHED) else ()):    # (a Finished row: its ⋯)
                    if ep.id in left:
                        found[ep.id] = (n, ep)
        return found

    def pressed(self, episodes):
        """Whether any of `episodes` is pressed (its row's *Mine now* turns)."""
        return bool(self.pressed_ids) and any(e.id in self.pressed_ids for e in episodes)

    def press_ids(self, ids):
        """The files `ids` asked for: their pills turn from now — painted before this returns — until their status
        moves (`_prune_pressed`) or their press ends (`unpress`: refused, undone, or given way to Connect's own state —
        `mine_actions`). Files this list doesn't show are no business of its. -> the ids it marks."""
        shown = self._where(ids)
        if not shown:
            return ()
        entries = self.model().entries
        self._pressed_at.update({i: (ep.status, entries[n][1].key) for i, (n, ep) in shown.items()})
        self._set_pressed(self.pressed_ids | set(shown))
        for row_i in sorted({n for n, _ep in shown.values()}):
            self.viewport().repaint(self.visualRect(self.model().index(row_i, 0)))
        return tuple(shown)

    def unpress(self, ids):
        gone = self.pressed_ids & set(ids)
        if not gone:
            return
        shown = self._where(gone, {i: self._pressed_at[i][1] for i in gone if i in self._pressed_at})
        for i in gone:
            self._pressed_at.pop(i, None)
        self._set_pressed(self.pressed_ids - gone)
        for row_i in sorted({n for n, _ep in shown.values()}):  # the rows that stop turning: their pills as they are
            self.update(self.model().index(row_i, 0))

    def mark_ids(self, ids, part="more"):
        """Round 8 row 45 (IK-2; `press.row_mark`): the files `ids` marked by a live press — the accent arc turns on
        each one's line at `part` ("more": its ⋯, "play": ▶), painted before this returns, until `unmark` takes that
        press's mark off. Two presses on one file keep a mark each (P3-A4): the newest is painted, and the first to end
        leaves the other's. Kept for a file this list doesn't show yet (it shows once it does). -> the ids it shows."""
        for i in ids:
            self.marked.setdefault(i, []).append(part)
        self._sync_turn()
        shown = self._where(ids)
        for row_i in sorted({n for n, _ep in shown.values()}):
            self.viewport().repaint(self.visualRect(self.model().index(row_i, 0)))
        return tuple(shown)

    def unmark(self, ids, part=None):
        """One press's marks off `ids` (`part`: the one it made; None: every mark of theirs)."""
        gone = set(self.marked) & set(ids)
        if not gone:
            return
        for i in gone:
            parts = self.marked[i]
            if part is not None and part in parts:
                parts.reverse()
                parts.remove(part)                   # (its newest such mark: a press's own)
                parts.reverse()
            else:
                parts.clear()
            if not parts:
                del self.marked[i]
        self._sync_turn()
        for row_i in sorted({n for n, _ep in self._where(gone).values()}):
            self.update(self.model().index(row_i, 0))

    def marked_part(self, episodes):
        """The part a press marks on any of `episodes`' lines, or None."""
        if not self.marked:
            return None
        return next((self.marked[e.id][-1] for e in episodes if e.id in self.marked), None)

    def _prune_pressed(self):
        """A new view: a pressed file whose status moved from what it was at the press (Connect read the ask: asked, a
        wait, mining), or that this list no longer shows, stops turning — its press ended by its owner."""
        if not self.pressed_ids:
            return
        shown = self._where(self.pressed_ids, {i: key for i, (_st, key) in self._pressed_at.items()})
        moved = {i for i in self.pressed_ids if i not in shown or shown[i][1].status != self._pressed_at[i][0]}
        if moved:
            (self.press_moved or self.unpress)(moved)

    def _set_pressed(self, ids):
        self.pressed_ids = frozenset(ids)
        self._sync_turn()

    def _sync_turn(self):
        """The marks' clock: on while any file is pressed, marked or stopping (R47), gone when none is."""
        if (self.pressed_ids or self.marked or self.stopping_ids) and self._turn is None:
            self._turn = motion.Turn(self.viewport(), self._turned)
            self._turn.show()
            self._turn.set_running(True)
        elif not (self.pressed_ids or self.marked or self.stopping_ids) and self._turn is not None:
            self._turn.set_running(False)
            self._turn.deleteLater()
            self._turn, self._turn_rects = None, []

    # --- R47: a Mining pill's *Stop* pressed (`mine_actions.stop`) --------------------------------------------- #
    def stop_marks(self):
        """Whether any Stop is pressed or under the hand (a paint looks no further while none is)."""
        return bool(self.stopping_ids) or self.stop_hot is not None

    def stopping(self, episodes):
        """Whether any of `episodes` has its Stop pressed (its pill reads *Stopping…*)."""
        return bool(self.stopping_ids) and any(e.id in self.stopping_ids for e in episodes)

    def press_stop(self, ids):
        """The files `ids` stopped: their pills read *Stopping…* from now — painted before this returns — until they
        leave Mining (`_prune_pressed`: stopped, or Connect no longer mining them) or the stop is refused (`unstop`).
        -> the ids it marks."""
        shown = self._where(ids)
        if not shown:
            return ()
        entries = self.model().entries
        self._stopping_at.update({i: entries[n][1].key for i, (n, _ep) in shown.items()})
        self.stopping_ids = frozenset(self.stopping_ids | set(shown))
        self.stop_hot = None
        self._sync_turn()
        for row_i in sorted({n for n, _ep in shown.values()}):
            self.viewport().repaint(self.visualRect(self.model().index(row_i, 0)))
        return tuple(shown)

    def unstop(self, ids):
        gone = self.stopping_ids & set(ids)
        if not gone:
            return
        shown = self._where(gone, {i: self._stopping_at[i] for i in gone if i in self._stopping_at})
        for i in gone:
            self._stopping_at.pop(i, None)
        self.stopping_ids = frozenset(self.stopping_ids - gone)
        self._sync_turn()
        for row_i in sorted({n for n, _ep in shown.values()}):
            self.update(self.model().index(row_i, 0))
        pos = self.viewport().mapFromGlobal(QCursor.pos())       # R47-A3: the hand still on a Stop reads ■ Stop again
        part = self.part_at(pos)[1] if self.viewport().rect().contains(pos) else None
        self._set_stop_hot(QRect(part[1]) if part is not None and part[0] == STOP else None)

    def _prune_stopping(self):
        """A new view: a stopped file no longer Mining (stopped: waiting for your *Mine now*; or Connect not mining it
        now), or no longer shown, lets its *Stopping…* go — its press ended by its owner. Connect's own *Stopping…*
        (the feed's `stopping`) is still Mining: held. R47-A1: still Mining, neither stoppable nor stopping, Connect
        dropped the stop (it accepted it, then naming began: `ledger.forget_stop`) — its press ends refused, too late."""
        if not self.stopping_ids:
            return
        shown = self._where(self.stopping_ids, dict(self._stopping_at))
        moved = {i for i in self.stopping_ids if i not in shown or shown[i][1].status is None
                 or shown[i][1].status.kind != "mining"}
        late = {i for i in self.stopping_ids - moved if shown[i][1].status.stop is None
                and shown[i][1].status.label != view_rows.STRINGS["stopping"]}
        for ids, too_late in ((moved, False), (late, True)):
            if ids and self.stop_moved is not None:
                self.stop_moved(ids, late=too_late)
            elif ids:
                self.unstop(ids)

    def _set_stop_hot(self, rect):
        """The Stop pill under the hand (`rect`, or None): it reads ■ Stop; the rows it leaves and enters repainted."""
        if rect == self.stop_hot:
            return
        for r in (self.stop_hot, rect):
            if r is not None:
                self.viewport().update(r.adjusted(-2, -2, 2, 2))
        self.stop_hot = rect
    # --- end R47

    def turning(self):
        """The pressed marks' phase (0–1), or None: still (Reduced motion, the freeze switch)."""
        return self._turn.turning if self._turn is not None else None

    def turned_at(self, rect):
        """A mark painted in `rect` (by the delegate, on the viewport): repainted alone at the next frame; the clock on
        again if it stopped with none on screen (A-6)."""
        self._turn_rects.append(rect)
        if self._turn is not None and not self._turn.running:
            self._turn.set_running(True)

    def _turned(self):
        """A frame of the turn: only the boxes the marks were painted in are painted again. Two frames running with
        none painted (scrolled away, a row closed, a file this list doesn't draw): the clock stops until one is
        painted again (A-6; S19: nothing ticks for nothing on screen)."""
        rects, self._turn_rects = self._turn_rects, []
        if not rects:
            if self._turn_idle and self._turn is not None:
                self._turn.set_running(False)
            self._turn_idle = True
            return
        self._turn_idle = False
        for r in rects:
            self.viewport().update(r)
    # --- end round 8 row 45

    def set_entries(self, entries):
        """Show these entries; a reset keeps the row that was at the top where it was."""
        model = self.model()
        anchor = self._anchor()
        before = model.entries
        held = self._held_keys(before)
        keys = model.keys
        how = model.set_entries(entries)
        self._trim_picks()                           # --- LM11b G4
        if how == "moved" or how == "relayout" and model.keys is not keys:     # AD-5 (C3: lines moved too): the
            self._follow_rows(*held)                 # keyboard's row and the hand's stay on their rows
        if how in ("same", "moved"):                 # a move keeps every place's height: no relayout (W3.1a S3)
            self.delegate.same_heights(before, model.entries)     # equal shapes: equal heights (review D-2)
            lo, hi = self._near()
            changed = model.changed
            looks = [i for i in changed[bisect.bisect_left(changed, lo):bisect.bisect_right(changed, hi)]
                     if model.looks_different(i)]
            self.looks_changed = bool(looks)
            if looks:                                # nothing shown changed: nothing to paint ahead or again either
                self._rest()
            if len(looks) > 40:
                self.viewport().update()
            else:
                for i in looks:                          # only the rows that look different (dirty rows, never all)
                    self.update(model.index(i, 0))
        elif how == "spliced":
            # a4 (A2): rows came or went, the rest in place: no reset — the current row, the open row and the picks are
            # Qt's persistent places (moved with the insert); the hand's row is followed by its key. Qt lays the rows
            # out again and repaints the screen from kept pixmaps (S19's written skip, as a relayout); the place the
            # learner reads stays put only when something came or went above it (the top row's offset put back)
            self.looks_changed = True
            self._rest()
            self._follow_rows(*held)
            if anchor is not None and self.isVisible() and anchor[0] in keys and anchor[0] in model.keys:
                old_at, new_at = keys.index(anchor[0]), model.keys.index(anchor[0])
                if any(i < new_at for i in model.came) or any(i < old_at for i in model.gone):
                    self._restore = anchor
                    self._apply_restore()
                    self._restore = None
        elif how == "relayout":
            # S19's written skip: a relayout (a row opened, or C3's lines moving inside a drop's span) repaints the whole
            # viewport — Qt's QListView repaints it on its delayed layout (`doItemsLayout`) whatever is asked here, so a
            # narrower update would change nothing; every row comes from its kept picture (`_same_face`). Only lines that
            # take no row height (a groove drawn in the gap) would let the span alone repaint: a look change, W4.1's.
            # The scroll value is kept, never the top row's anchor (IKB-8): a drop moved that row a place, as it painted.
            self.looks_changed = True
            self._rest()
            self.relayout()
            self.viewport().update()
        else:
            self.looks_changed = True
            self._rest()
            self._hover = None
            self._set_ep("ep_key", None)                 # --- row 28 (AD-1): a reset (a language switch) drops the row
            if anchor is not None and self.isVisible():
                self._restore = anchor
                self._apply_restore()
                self._restore = None                     # tried once: a place gone stays gone (W2.2 review A-15)
        if self.ep_key is not None and self._ep_line(self.ep_key) is None:
            self._set_ep("ep_key", None)                 # --- row 28: its episode, or its row's opening, gone
        if self.ep_hot is not None:
            self._hand_again()                           # --- row 28 (AD-3): the hand's episode where it is now
        self._prune_pressed()                            # --- round 8 row 45
        self._prune_stopping()                           # --- R47
        return how

    def _held_keys(self, entries):
        """(the current row's key, the hovered row's key) in `entries`: what a reorder must keep on its row."""
        def key(row):
            if row is None or not 0 <= row < len(entries):
                return None
            return getattr(entries[row][1], "key", None)
        cur = self.currentIndex()
        return key(cur.row() if cur.isValid() else None), key(self._hover)

    def _follow_rows(self, cur_key, hover_key):
        """AD-5: a "moved" refresh swaps the rows in their places with no reset, so Qt's current index and the hovered
        place still name places: put them back on the rows they were on (the focus ring, Enter / Space, the next ↑ ↓
        act on the same title). Only the two places repaint."""
        places = {}
        for i, (kind, payload, _lines) in enumerate(self.model().entries):
            k = getattr(payload, "key", None)
            if k is not None and k in (cur_key, hover_key):
                places[k] = i
        cur = self.currentIndex()
        if cur_key is not None and cur_key in places and (not cur.isValid() or cur.row() != places[cur_key]):
            scrolls = self.hasAutoScroll()
            self.setAutoScroll(False)                    # followed where it stands: the list doesn't jump
            self.selectionModel().setCurrentIndex(self.model().index(places[cur_key], 0),
                                                  QItemSelectionModel.SelectionFlag.NoUpdate)
            self.setAutoScroll(scrolls)
            if cur.isValid():
                self.update(cur)
            self.update(self.model().index(places[cur_key], 0))
        if hover_key is not None:
            self._hover = places.get(hover_key)

    def _near(self):
        """The rows on screen and those painted ahead past each edge (`WARM_AHEAD`): (first, last), by place."""
        n = self.model().rowCount()
        first = self.indexAt(QPoint(4, 1))
        last = self.indexAt(QPoint(4, self.viewport().height() - 2))
        lo = first.row() if first.isValid() else 0
        hi = last.row() if last.isValid() else n - 1
        return max(0, lo - WARM_AHEAD), hi + WARM_AHEAD

    def _anchor(self):
        """(entry key, its offset from the viewport's top) of the first row on screen, or None."""
        idx = self.indexAt(QPoint(4, 1))
        if not idx.isValid():
            return None
        key = RowsModel.key_of(self.model().entries[idx.row()])
        return key, self.visualRect(idx).top()

    def _apply_restore(self):
        if self._restore is None:
            return
        key, offset = self._restore
        keys = self.model().keys
        try:
            row = keys.index(key)
        except ValueError:
            self._restore = None
            return
        rect = self.visualRect(self.model().index(row, 0))
        if rect.isValid() and rect.height() > 0:
            bar = self.verticalScrollBar()
            target = bar.value() + rect.top() - offset
            if target <= bar.maximum():
                bar.setValue(target)
                self._restore = None

    def _snap_step(self, _action):
        bar = self.verticalScrollBar()
        pos, value = bar.sliderPosition(), bar.value()
        q = whole_step(self.viewport().devicePixelRatioF() or 1.0)
        if q == 1 or pos == value or pos in (bar.minimum(), bar.maximum()):
            return
        snapped = -(-pos // q) * q if pos > value else pos // q * q        # away from where it was: never stuck
        bar.setSliderPosition(max(bar.minimum(), min(bar.maximum(), snapped)))

    def _rest(self, *_args):
        self._moved = time.monotonic()
        self._warm.setInterval(WARM_IDLE_MS)
        self._warm.start()

    def _warm_one(self):
        """Paint one row ahead (the next below the screen first, then above); again on the next turn until done."""
        model = self.model()
        n = model.rowCount()
        if not n:
            self.delegate.keep_only(())                  # an emptied list lets its pixmaps go
            return
        if self.parting is not None:                 # C6: a drag parts the rows: nothing painted ahead under it, again
            self._rest()                             # once the list rests after it
            return
        if not self.isVisible():
            like = self.warm_like
            if like is not None and like.isVisible() and (like._warm.isActive() or like.parting is not None or
                                                          time.monotonic() - like._moved < WARM_IDLE_MS / 1000):
                self._rest()                         # the shown list first: it is moving, or warming its own rows (B-3)
                return
            if self._warm_hidden():
                self._warm.setInterval(0)
                self._warm.start()
            return
        first = self.indexAt(QPoint(4, 1))
        last = self.indexAt(QPoint(4, self.viewport().height() - 2))
        lo = first.row() if first.isValid() else 0
        hi = last.row() if last.isValid() else n - 1
        dpr = self.viewport().devicePixelRatioF() or 1.0
        below = range(hi + 1, min(n, hi + 1 + WARM_AHEAD))
        above = range(lo - 1, max(-1, lo - 1 - WARM_AHEAD), -1)
        for r in list(below) + list(above):
            if self.delegate.warm(model.index(r, 0), dpr):
                self._warm.setInterval(0)                # the next one on the loop's next turn
                self._warm.start()
                return
        # nothing left to paint ahead: keep the screen and the rows ahead, let the rest go
        self.delegate.keep_only(model.entries[max(0, lo - WARM_AHEAD):hi + 1 + WARM_AHEAD], dpr,
                                self.visualRect(first).width() if first.isValid() else None)

    def _warm_hovered(self):
        row = self._hover
        if row is None or not self.isVisible() or row >= self.model().rowCount():
            return
        wait = WARM_IDLE_MS / 1000 - (time.monotonic() - self._moved)
        if wait > 0:                                 # the list is moving (a wheel moves no pointer): after it rests
            self._hover_warm.setInterval(max(1, round(wait * 1000)))      # (review C-4)
            self._hover_warm.start()
            return
        index = self.model().index(row, 0)
        if not self.visualRect(index).intersects(self.viewport().rect()):
            return                                   # scrolled away from under the pointer: a stale hover (C-4)
        room = self.viewport().height() - self.visualRect(index).top()
        if self.delegate.warm_episodes(index, self.viewport().devicePixelRatioF() or 1.0, room):
            self._hover_warm.setInterval(0)              # the next one on the loop's next turn
            self._hover_warm.start()

    def _warm_hidden(self):
        """A hidden list (another tab): the screen it will show painted ahead, one row a turn, at the shown list's width
        — from the row at its own scroll place, so a list left scrolled keeps its real screen, not its top (review
        C-1), and its open row's pixmaps are kept too. The tab's first switch then blits. A width that comes out
        different (a scroll bar more or less) only misses."""
        like = self.warm_like
        if like is None or like is self or not like.isVisible():
            return False
        room = like.window().height()                # this list may stand taller (Current has the Goal strip under it)
        dpr = like.viewport().devicePixelRatioF() or 1.0
        model = self.model()
        first = self.indexAt(QPoint(4, 1))           # where it stands (its layout is kept while hidden)
        start = first.row() if first.isValid() else 0
        top = self.visualRect(first).top() if first.isValid() else 0
        heights, total = [], top
        for r in range(start, model.rowCount()):     # its screen's rows, and whether it will have a scroll bar
            heights.append(self.delegate.sizeHint(None, model.index(r, 0)).height())
            total += heights[-1]
            if total >= room:
                break
        if like.verticalScrollBar().isVisible():
            bar = like.width() - like.viewport().width()
        else:
            bar = self.verticalScrollBar().sizeHint().width()
        scrolls = start > 0 or total > like.viewport().height()
        width = like.width() - (bar if scrolls else 0)                                    # review B-4
        for k, h in enumerate(heights):
            if self.delegate.warm(model.index(start + k, 0), dpr, QRect(0, top, width, h)):
                return True
            top += h
        keep = model.entries[start:start + len(heights)]       # its screen only, while hidden
        if model.open_key is not None:
            keep = keep + [e for e in model.entries if e[0] in (HERO, ROW, FINISHED) and e[1].key == model.open_key]
        self.delegate.keep_only(keep, dpr, width)
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self._rest()

    def _range_changed(self, _lo, _hi):
        if self._restore is not None:
            self._apply_restore()

    def relayout(self):
        """A row changed height (opened, closed): lay the rows out again."""
        self.scheduleDelayedItemsLayout()

    # open / close -------------------------------------------------------------------------------------------------- #
    def toggle(self, index):
        model = self.model()
        entry = model.entries[index.row()]
        if entry[0] not in (HERO, ROW):
            return
        key = entry[1].key
        self._set_ep("ep_key", None)                 # --- row 28 (AD-1): opened or closed, the keyboard is on its head
        model.open_key = None if model.open_key == key else key
        self.relayout()
        self.opened.emit(model.open_key)

    # the hover look in motion (W3.1a §1 *Rows*, §3: springs on the one clock; S7) -------------------------------- #
    def touch(self, row, key):
        """(dy, lift, fade) for Current row `row` (its key `key`) as it's painted now: up by its own lift, apart from a
        lifted neighbour by that neighbour's parting, its hover picture faded in by `fade`."""
        touches = self._touch
        if not touches:
            return 0.0, 0.0, 0.0
        t = touches.get(key)
        lift = t.lift if t is not None else 0.0
        dy = -lift
        entries = self.model().entries
        for j, sign in ((row - 1, 1.0), (row + 1, -1.0)):   # the row above lifted: this one eases down; below: up
            if 0 <= j < len(entries) and entries[j][0] == ROW:
                n = touches.get(entries[j][1].key)
                if n is not None:
                    dy += sign * n.nb
        return dy, lift, t.fade if t is not None else 0.0

    def _focus_row(self):
        """The row the keyboard is on, while its ring shows (S7: it shows what the hand's hover shows)."""
        idx = self.currentIndex()
        return idx.row() if self.focus_visible and self.hasFocus() and idx.isValid() else None

    def _retouch(self):
        """The rows under the hand and the keyboard show their hover look; the others let it go — each on its springs
        (the lift `hover-lift` and its release `hover-release`, the neighbours `hover-neighbour`) and a fade."""
        model = self.model()
        want = set()
        for r in (self._hover, self._focus_row()):
            if r is not None and r < len(model.entries) and model.entries[r][0] == ROW:
                want.add(model.entries[r][1].key)
        if want == self._active:
            return
        for key in want - self._active:
            self._touch_to(key, True)
        for key in self._active - want:
            self._touch_to(key, False)
        self._active = want

    def _touch_to(self, key, on):
        t = self._touch.get(key)
        if t is None:
            t = self._touch[key] = _Touch()
        t.on = on
        closed = self.model().open_key != key        # an opened row doesn't lift: it fades its hover look only
        lift = theme.SPRINGS["lift-px"] if on and closed else 0.0
        nb = theme.SPRINGS["neighbour-px"] if on and closed else 0.0
        spring = motion.preset("hover-lift" if on else "hover-release")
        if t.s_lift is None:
            t.s_lift = motion.clock().spring(lambda v: self._touched(key, "lift", v), t.lift, lift, owner=self,
                                             on_end=lambda: self._touch_end(key), **spring)
        else:
            t.s_lift.retarget(lift, **spring)
        if t.s_nb is None:
            t.s_nb = motion.clock().spring(lambda v: self._touched(key, "nb", v), t.nb, nb, owner=self,
                                           on_end=lambda: self._touch_end(key), **motion.preset("hover-neighbour"))
        else:
            t.s_nb.retarget(nb, **motion.preset("hover-neighbour"))
        if t.a_fade is not None:
            t.a_fade.stop()
            t.a_fade = None
        start, target = t.fade, 1.0 if on else 0.0
        if start != target:
            t.a_fade = motion.clock().animate(
                theme.MOTION["hover"], lambda k: self._touched(key, "fade", start + (target - start) * k), kind="fade",
                points="linear", owner=self, on_end=lambda: self._touch_end(key))

    def _touched(self, key, field, value):
        """One touch value moved: the row repainted, and its two neighbours when it lifts or parts them — nothing else
        (§3: a hover repaints three rows while their springs run)."""
        t = self._touch.get(key)
        if t is None:
            return
        setattr(t, field, value)
        if field != "fade":                          # L5: a px spring rests once what it draws stops changing
            s = t.s_lift if field == "lift" else t.s_nb
            if s is not None and s.alive and abs(value - s.target) < theme.DRAG["px-rest"]:
                s.finish()                           # (its last value comes back through here, at rest)
                return
        row = self._row_of_key(key)
        if row is not None:
            entries = self.model().entries
            near = [r for r in ((row - 1, row, row + 1) if field != "fade" else (row,))
                    if 0 <= r < len(entries) and (r == row or entries[r][0] == ROW)]    # Up Next never eases apart
            if self.parting is not None:             # a drag parts the rows: each where the parting paints it (Gap 2)
                self.parting.repaint_rows(near)
            else:
                for r in near:
                    self.update(self.model().index(r, 0))
        if not t.on and not (t.lift or t.nb or t.fade):
            self._touch.pop(key, None)               # back at rest: nothing kept

    def _row_of_key(self, key):
        """The place of the row `key` (Up Next, a row, A4: a Finished row) in the model now, or None."""
        keys = self.model().keys
        if self._key_rows[0] is not keys:
            self._key_rows = (keys, {k[1]: i for i, k in enumerate(keys) if k[0] in PICK_KINDS})
        return self._key_rows[1].get(key)

    # --- LM11b G4: the picks ------------------------------------------------------------------------------------ #
    def _repaint_key(self, key):
        i = self._row_of_key(key)
        if i is not None:
            self.update(self.model().index(i, 0))

    def _repaint_keys(self, keys):
        """A4 (S19): the rows of `keys` repainted — those on screen only when there are many (Ctrl+A at 20,000: a row
        off screen is painted as it comes into view, from the picks as they are then)."""
        if len(keys) <= 32:
            for key in keys:
                self._repaint_key(key)
            return
        model = self.model()
        vp = self.viewport().rect()
        top, bottom = self.indexAt(vp.topLeft()), self.indexAt(vp.bottomLeft())
        first = max(0, (top.row() if top.isValid() else 0) - 2)
        last = min(model.rowCount() - 1, (bottom.row() if bottom.isValid() else model.rowCount() - 1) + 2)
        for i in range(first, last + 1):
            k = model.keys[i]
            if k[0] in PICK_KINDS and k[1] in keys:
                self.update(model.index(i, 0))

    def _picked_now(self):
        """A4: something is picked here: the window's other lists let theirs go."""
        if self.picked_rows or self.picked_eps:
            picks_here(self)

    def pick_row(self, row):
        """Ctrl+click on its slab, Ctrl+Space: `row` in the selection, or out of it again (its row alone repainted)."""
        if self.pickable is None or not self.pickable(row):
            return False
        self.picked_rows ^= {row.key}
        self._pick_anchor = row.key
        self._repaint_key(row.key)
        self._picked_now()
        return True

    def pick_all(self):
        """A4: Ctrl+A — every row this list can pick (an opened row's episode picks go: its row is picked whole); only
        the rows whose pick changed repainted. -> whether anything is picked."""
        if self.pickable is None:
            return False
        span = {e[1].key for e in self.model().entries if e[0] in PICK_KINDS and self.pickable(e[1])}
        changed = (span ^ self.picked_rows) | {k for k, _e in self.picked_eps}
        self.picked_rows, self.picked_eps = span, set()
        self._repaint_keys(changed)
        self._picked_now()
        return bool(span)

    def pick_range(self, row, add=False):
        """Shift+click: the picks become every row from the anchor (the row Ctrl picked last; with none, `row` itself)
        to `row`, as Explorer's; Ctrl+Shift+click (`add`) adds those rows to the picks. The anchor stays where it is.
        Only the rows whose state changed repainted."""
        if self.pickable is None or not self.pickable(row):
            return False
        here = self._row_of_key(row.key)
        there = self._row_of_key(self._pick_anchor) if self._pick_anchor is not None else None
        if there is None:
            self._pick_anchor, there = row.key, here
        entries = self.model().entries
        span = {entries[i][1].key for i in range(min(here, there), max(here, there) + 1)
                if entries[i][0] in PICK_KINDS and self.pickable(entries[i][1])}
        before_rows, before_eps = self.picked_rows, self.picked_eps
        if add:
            self.picked_rows = before_rows | span
            changed = span - before_rows
        else:
            self.picked_rows, self.picked_eps = span, set()
            changed = (span ^ before_rows) | {k for k, _e in before_eps}
        self._repaint_keys(changed)
        self._picked_now()
        return True

    def pick_episode(self, row, ep):
        """Ctrl+click on an opened row's stone: that episode in the selection, or out of it (never watched)."""
        if self.pickable is None or not self.pickable(row):
            return False
        self.picked_eps ^= {(row.key, ep.id)}
        self._repaint_key(row.key)
        self._picked_now()
        return True

    def clear_picks(self):
        """Let every pick go: only the rows that held one repainted."""
        if not self.picked_rows and not self.picked_eps:
            return
        keys = self.picked_rows | {k for k, _e in self.picked_eps}
        self.picked_rows, self.picked_eps = set(), set()
        self._pick_anchor = None
        self._keep_picks = False
        self._repaint_keys(keys)

    def _trim_picks(self):
        """A new view: the picks whose row (or episode in it) is gone let go — an episode's with its row closed too."""
        if not self.picked_rows and not self.picked_eps:
            return
        shown = {e[1].key: e[1] for e in self.model().entries if e[0] in PICK_KINDS}
        self.picked_rows &= shown.keys()
        open_key = self.model().open_key
        self.picked_eps = {(k, i) for k, i in self.picked_eps
                           if k == open_key and k in shown and any(e.id == i for e in shown[k].episodes)}

    def _closed_picks(self, _key=None):
        """H-B5 (`opened`: a row opened or closed, here or by *Search*): an episode is picked only while its row is
        open, so the picks of a row that closed let go, that row alone repainted — never a hidden pick grouped."""
        open_key = self.model().open_key
        gone = {k for k, _i in self.picked_eps if k != open_key}
        if gone:
            self.picked_eps = {(k, i) for k, i in self.picked_eps if k == open_key}
            for key in gone:
                self._repaint_key(key)

    def _pick_at(self, idx, part, how):
        """A Ctrl+ (`how` "ctrl"), Shift+ ("shift") or Ctrl+Shift+click's ("ctrl-shift") part of a row: Ctrl on an
        opened row's stone picks its episode; a button (▶, ⋯, ↑ ↓, ✓ Done, a status's), a seam or a line does nothing;
        anything else picks the row (a closed row's stone too), Shift the rows from the anchor to it (Ctrl+Shift adds
        them). -> whether anything was picked."""
        kind, row, _lines = self.model().entries[idx.row()]
        if kind not in PICK_KINDS:
            return False
        name, payload = part[0], part[3]
        if name in NO_DRAG or name == "seam" or name.endswith("-line"):
            return False
        if how in ("shift", "ctrl-shift"):
            return self.pick_range(row, add=how == "ctrl-shift")
        if name == "stone" and payload is not None and self.model().open_key == row.key:
            return self.pick_episode(row, payload)
        return self.pick_row(row)

    def contextMenuEvent(self, event):
        """A right-click on a row opens its ⋯ at the hand; the menu key, at the current row's ⋯ (the same
        `menu_requested` path as ⋯). On an opened row's episode (the hand's, or the keyboard's): that episode's own ⋯
        (IK-7)."""
        mouse = event.reason() == event.Reason.Mouse
        idx = self.indexAt(event.pos()) if mouse else self.currentIndex()
        if not idx.isValid() or self.model().entries[idx.row()][0] not in (HERO, ROW, FINISHED):
            super().contextMenuEvent(event)
            return
        entry = self.model().entries[idx.row()]
        if mouse:                                    # --- row 28 (IK-7): the hand's episode, as the menu key's
            ep = self.delegate.episode_at(entry, self.visualRect(idx), event.pos())
        else:
            ep = next((e for e in getattr(entry[1], "episodes", ()) if self.ep_key == (entry[1].key, e.id)), None)
        if ep is not None and self.model().open_key == entry[1].key:      # --- row 28: an opened row's episode
            self.open_episode_menu(idx, ep, event.globalPos() if mouse else None)
            event.accept()
            return
        if mouse:
            at = event.globalPos()
        else:
            more = next((pt for pt in self.delegate.parts(entry, self.visualRect(idx)) if pt[0] == "more"), None)
            at = self.viewport().mapToGlobal((more[1] if more is not None else self.visualRect(idx)).bottomLeft())
        self.menu_requested.emit(entry[1], at)
        event.accept()
    # --- end LM11b G4

    def _touch_end(self, key):
        """A touch's spring or fade ended short (the list hidden or gone): its values go to where they were headed."""
        t = self._touch.get(key)
        if t is None:
            return
        t.lift = t.s_lift.target if t.s_lift is not None else 0.0
        t.nb = t.s_nb.target if t.s_nb is not None else 0.0
        t.fade = 1.0 if t.on else 0.0
        if not t.on:
            self._touch.pop(key, None)

    # --- W3.2 Q6
    def _cover_ready(self, work_id):
        """A title's picture landed: only the rows showing that title are painted again (S19)."""
        self.delegate.drop_work(work_id)
        model = self.model()
        for i, (_kind, payload, _lines) in enumerate(model.entries):
            if getattr(payload, "work_id", None) == work_id:
                self.update(model.index(i))
    # --- end W3.2 Q6

    def _sheet_ready(self, key):
        """The stones' sheet landed: the pictures painted before it are drawn once more, with their stones (B3)."""
        if self.delegate.drop_unsheeted(key[0]):
            self.viewport().update()

    # hit-testing ------------------------------------------------------------------------------------------------- #
    def part_at(self, pos):
        """(index, part) under `pos`. A line's hover area reaches into the row under it (S10: at least 12 px around a
        2 px groove), so the row above's lines are asked first near a row's top."""
        idx = self.indexAt(pos)
        if not idx.isValid():
            return idx, None
        entries = self.model().entries
        if idx.row() > 0 and entries[idx.row() - 1][2]:
            above = self.model().index(idx.row() - 1, 0)
            for part in self.delegate._line_parts(entries[idx.row() - 1][2], self.visualRect(above)):
                if part[1].contains(pos):
                    return above, part
        for part in self.delegate.parts(entries[idx.row()], self.visualRect(idx)):
            if part[1].contains(pos):
                return idx, part
        return idx, None

    def viewportEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate):
            # QAbstractItemView repaints its whole viewport here, yet no row paints the window's active state:
            # nothing visible changes (S19; review D-5). The focus ring follows focus in / out (`focusInEvent`).
            return True
        if event.type() == QEvent.Type.ToolTip:
            idx, part = self.part_at(event.pos())
            if part is not None and part[2] and self.tooltips is not None:
                self.tooltips.request(self.viewport(), part[1], part[2])
            elif self.tooltips is not None:
                self.tooltips.hide()
            return True
        return super().viewportEvent(event)

    def mouseMoveEvent(self, event):
        press = self._press
        if press is not None and event.buttons() & Qt.MouseButton.LeftButton and \
                (event.pos() - press[3]).manhattanLength() >= theme.MOTION["drag-start-px"] and self.drag_from(press):
            self._press = None                           # B1: the press is the drag's now, never a click
            self.drag.begin(press, event.globalPosition().toPoint())
            event.accept()
            return
        idx = self.indexAt(event.pos())
        row = idx.row() if idx.isValid() else None
        if row != self._hover:
            old, self._hover = self._hover, row
            for r in (old, row):                     # the hero's and Finished's hover; a Current row's is its touch's
                if r is not None and r < self.model().rowCount() and self.model().entries[r][0] != ROW:
                    self.update(self.model().index(r, 0))
            self._retouch()
            self._hover_warm.setInterval(HOVER_WARM_MS)
            self._hover_warm.start()
        self._set_ep("ep_hot", self._ep_under(event.pos()))      # --- row 28 (before the parts: its ⋯ is one)
        at, part = self.part_at(event.pos())
        self._set_line_hover((at.row(), part[0][:-5]) if part is not None and part[0].endswith("-line") else None)
        self._set_stop_hot(QRect(part[1]) if part is not None and part[0] == STOP else None)     # --- R47
        self._q8_hover(at, part)                     # --- W3.2 Q8: the ✂ seam, the episode the hand is on
        if self.tooltips is not None:
            self.tooltips.hide_part_unless(self.viewport(), event.pos())
        super().mouseMoveEvent(event)

    def _set_line_hover(self, hot):
        """A line under the hand lights a step (its row alone repainted, as it goes and as it comes)."""
        if hot == self.line_hover:
            return
        old, self.line_hover = self.line_hover, hot
        for h in (old, hot):
            if h is not None and h[0] < self.model().rowCount():
                self.update(self.model().index(h[0], 0))

    def leaveEvent(self, event):
        hover = self._hover
        if hover is not None and hover < self.model().rowCount() and self.model().entries[hover][0] != ROW:
            self.update(self.model().index(hover, 0))
        self._hover = None
        self._retouch()
        self._set_line_hover(None)
        self.set_seam(None)                          # --- W3.2 Q8
        self._set_ep("ep_hot", None)                 # --- row 28
        self._set_stop_hot(None)                     # --- R47
        super().leaveEvent(event)

    def _show_focus(self, on):
        if self.focus_visible != on:
            self.focus_visible = on
            self._update_current()
            self._retouch()

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        self.action_focus = None                     # --- P4.1 L2: another row: its button lets the keyboard go
        if getattr(self, "ep_key", None) is not None and (not current.isValid() or getattr(
                self.model().entries[current.row()][1], "key", None) != self.ep_key[0]):
            self._set_ep("ep_key", None)             # --- row 28: another row: its episode lets the keyboard go
        if getattr(self, "focus_visible", False):     # the keyboard moved: its row shows the hover look (S7)
            self._retouch()

    def mousePressEvent(self, event):
        """B1 (W3.1a): a press only records the part under it; the part acts when the button comes up over it again
        (`mouseReleaseEvent`). A hand that travels `drag-start-px` first hands the press to the drag (`mouseMoveEvent`):
        a drag begun on a stone never marks it watched, one begun on a row never opens it."""
        self._show_focus(False)
        self._set_ep("ep_key", None)                 # --- row 28 (AD-1): the hand's now: the keyboard's episode let go
        self._press = None
        self._keep_picks = False
        if event.button() == Qt.MouseButton.LeftButton:
            idx, part = self.part_at(event.pos())
            mods = event.modifiers()                 # --- LM11b G4
            ctrl, shift = mods & Qt.KeyboardModifier.ControlModifier, mods & Qt.KeyboardModifier.ShiftModifier
            self._press_pick = ("ctrl-shift" if shift else "ctrl") if ctrl else "shift" if shift else None
            if self._press_pick is None and (part is None or part[0] != "more"):
                key = getattr(self.model().entries[idx.row()][1], "key", None) if idx.isValid() else None
                if key is not None and key in self.picked_rows and len(self.picked_rows) > 1:
                    self._keep_picks = True          # A4: a picked row's press keeps them: its drag carries them all
                else:
                    self.clear_picks()               # a plain click lets the picks go (⋯ keeps them: *Group…*)
            if idx.isValid():
                scrolls = self.hasAutoScroll()
                self.setAutoScroll(False)            # row 28: made current where it stands — Qt's scrollTo would pull
                self.setCurrentIndex(idx)            # a tall opened row's head back in, the part slid from under the hand
                self.setAutoScroll(scrolls)
                if part is not None:
                    entry = self.model().entries[idx.row()]
                    self._press = (idx.row(), part[0], part[3], event.pos(), getattr(entry[1], "key", None))
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """P4.1 WF (adversary N1): a double-click on a part acts once. The press records no `pressedIndex` for Qt (it
        never reaches `super`), so Qt would turn the second click into a second press, whose release acts again — a
        second ask, toast and Undo. Swallowed; a double-click off the parts is Qt's as before."""
        if event.button() == Qt.MouseButton.LeftButton:
            idx, part = self.part_at(event.pos())
            if idx.isValid() and part is not None:
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        if self._keep_picks and event.button() == Qt.MouseButton.LeftButton:
            self.clear_picks()                       # A4: no drag came of it — a plain click lets the picks go
        if press is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        event.accept()
        idx, part = self.part_at(event.pos())
        row, name, payload, _pos, key = press
        entries = self.model().entries
        if part is None or not idx.isValid() or idx.row() != row or part[0] != name or \
                getattr(entries[row][1], "key", None) != key or not _same_payload(part[3], payload):
            return                                       # let go somewhere else: nothing happens
        if self._press_pick is not None:             # --- LM11b G4: Ctrl / Shift+click picks, never acts — on any list
            if self.pickable is not None and entries[row][0] in PICK_KINDS:     # (H-C1: Finished's Put back, ▶, ⋯ too)
                self._pick_at(idx, part, self._press_pick)
            return
        if name == "play" and payload is not None:
            if payload.can_play:
                self.play_requested.emit(payload)
        elif name in ("open", "title", "audio"):     # a5-2: the 🎧 before a title is the title's
            self.toggle(idx)
        else:
            self._act(idx, part)

    def drag_from(self, press):
        """Whether a press may become a drag (W3.1a §2): on Current's rows (Up Next's card, a row's one line — never an
        opened row's episodes, a line, or a button: ▶, ⋯, ↑ ↓, ✓ Done, Mine now, ↗)."""
        row, name, _payload, pos, key = press
        entries = self.model().entries
        if self.drag is None or not 0 <= row < len(entries) or name in NO_DRAG or name.endswith("-line"):
            return False
        kind, payload, lines = entries[row]
        if getattr(payload, "key", None) != key:     # the list changed under the press (a view landed): not this row
            return False
        if kind not in (HERO, ROW):
            return False
        rect = self.visualRect(self.model().index(row, 0))
        if kind == HERO:
            head = QRect(rect.left(), rect.top(), rect.width(), self.delegate._hero_head_h())
            return head.contains(pos)
        return self.delegate.slab_of(rect).contains(pos)

    def _act(self, idx, part):
        """A click on a part that isn't ▶ or the row itself: a stone or ✓ Done asks for a Done for its file (one path,
        S12); ↑ ↓ ask for a nudge, ⋯ for its menu, ↗ for the journey; Waiting's icon (*Mine now*), Mine (*Mine this*) and No
        video (*Link…*) ask P4.1's routing (`mine_requested` …); the top-20 line opens its setting; any
        other status, a mark, the Soon line: states, not buttons."""
        name, rect, _tip, payload = part
        row = self.model().entries[idx.row()][1]
        if name == "stone" and payload is not None:
            self.done_requested.emit(row, payload)
        elif name == "done" and payload is not None:   # all watched: no file to mark, the finish offered (G3.2)
            self.done_requested.emit(row, None if payload.watched else payload)
        elif name in ("up", "down"):
            self.nudge_requested.emit(row, -1 if name == "up" else 1)
        elif name == "more":
            self.menu_requested.emit(row, self.viewport().mapToGlobal(rect.bottomLeft()))
        elif name == "more-ep" and payload is not None:      # --- row 28: the episode's own ⋯
            self.episode_menu_requested.emit(row, payload, self.viewport().mapToGlobal(rect.bottomLeft()))
        elif name == "journey":
            self.journey_requested.emit(row, payload)
        elif name == "top-line":                     # --- P4.1 L2 (row 4.1.14): the top-20 line opens its setting
            self.line_requested.emit("top")
        elif name == "put-back":                     # --- W3.2 Q4
            self.put_back_requested.emit(row)
        elif name == "seam" and payload is not None:     # --- W3.2 Q8: ✂ Split here
            self.set_seam(None)
            self.split_requested.emit(row, payload)
        elif name in ACTION_NAMES and payload is not None:     # --- P4.1 L2 (4.1.11): a status's button
            self._press_action(name, rect, row, payload, _tip)

    # --- P4.1 L2: the statuses' buttons (4.1.11) ------------------------------------------------------------------ #
    def _press_action(self, name, rect, row, ask, tip):
        """*Mine now* / *Mine this* ask for the files; *No video* offers *Link…* in a small menu. Connect
        off: an ask does nothing, its tip (saying why) is shown (IK S7); *Link…* still works. R47: a
        Mining pill's *Stop* asks the window to stop its job (offered only while Connect may run: `action_of`)."""
        if name == STOP:
            self.stop_requested.emit(row, ask)
            return
        if self.connect_off and asks_connect(name, getattr(row, "media_word", "video")):    # P4.1 WF: asks only
            if self.tooltips is not None:
                self.tooltips.request(self.viewport(), rect, tip)
            return
        if name != "no-media":
            self.mine_requested.emit(row, ask.ids)
            return
        from PyQt6.QtGui import QAction
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self)
        m.aboutToHide.connect(m.deleteLater)            # one menu per press, gone once it closes
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        offers = ((strings.ROWS_LINK, strings.ROWS_LINK_TIP, self.link_requested),)      # alpha 4 M1: no *Mine text*
        moved = getattr(getattr(ask.episode, "status", None), "moved", None)
        if moved:                                       # MV-2: its video left its folder — find that folder first
            offers = ((strings.ROWS_FIND_FOLDER, strings.ROWS_FIND_FOLDER_TIP.format(folder=moved),
                       self.find_folder_requested),) + offers
        for words, tip, signal in offers:
            act = QAction(words, m)
            act.setToolTip(tip)
            act.triggered.connect(lambda _c=False, s=signal: s.emit(row, ask.episode))
            m.addAction(act)
        self.action_menu = m
        m.popup(self.viewport().mapToGlobal(rect.bottomLeft()))

    def _action_key(self, event):
        """→ takes the keyboard to the current row's status button (its tip shown, as on hover: the same words on
        focus); Enter / Space press it; ← leaves it. -> handled."""
        idx = self.currentIndex()
        if not idx.isValid():
            return False
        entry = self.model().entries[idx.row()]
        key = event.key()
        if key == Qt.Key.Key_Right and entry[0] in (HERO, ROW):
            part = next(iter(self._action_parts(idx, entry)), None)     # row 28: the keyboard's episode's or the head's
            if part is None:
                return False
            self.action_focus = (entry[1].key, part[0])
            if self.tooltips is not None:
                self.tooltips.request(self.viewport(), part[1], part[2])
            return True
        if self.action_focus is None:
            return False
        if key == Qt.Key.Key_Left:
            self.action_focus = None
            if self.tooltips is not None:
                self.tooltips.hide()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            held, self.action_focus = self.action_focus, None
            part = None
            if getattr(entry[1], "key", None) == held[0]:         # the row the keyboard went to (P4.1 WF, N8)
                part = next((pt for pt in self._action_parts(idx, entry) if pt[0] == held[1]), None)
            if part is not None:
                self._act(idx, part)
                return True
        return False
    # --- end P4.1 L2

    MODIFIERS = frozenset({Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr})

    def keyPressEvent(self, event):
        if event.key() not in self.MODIFIERS:        # Ctrl held for a Ctrl+wheel is no navigation (D-6)
            self._show_focus(True)
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and \
                event.modifiers() & Qt.KeyboardModifier.AltModifier:     # A2 #14 (L7): Alt+↑ / ↓ moves the row
            idx = self.currentIndex()
            if idx.isValid() and self.model().entries[idx.row()][0] in (HERO, ROW):
                self.nudge_requested.emit(self.model().entries[idx.row()][1],
                                          -1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        idx = self.currentIndex()
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if event.key() == Qt.Key.Key_A and ctrl and self.pickable is not None:      # --- A4: Ctrl+A picks every row
            self.pick_all()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and ctrl and idx.isValid() and \
                self.model().entries[idx.row()][0] in PICK_KINDS:                  # --- LM11b G4 (A4: Finished's too)
            self.pick_row(self.model().entries[idx.row()][1])
            event.accept()
            return
        # --- W3.2 Q4: Enter, Space or the menu key: a Finished row's ⋯
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Menu) and \
                idx.isValid() and self.model().entries[idx.row()][0] == FINISHED:
            more = next(pt for pt in self.delegate.parts(self.model().entries[idx.row()], self.visualRect(idx))
                        if pt[0] == "more")
            self.menu_requested.emit(self.model().entries[idx.row()][1],
                                     self.viewport().mapToGlobal(more[1].bottomLeft()))
            event.accept()
            return                                   # --- end W3.2 Q4
        if self._action_key(event):                  # --- P4.1 L2: → to a status's button, Enter / Space press it
            event.accept()
            return
        if self._episode_key(event):                 # --- row 28: ↓ ↑ through an opened row's episodes
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            idx = self.currentIndex()
            if idx.isValid():
                self.toggle(idx)
                event.accept()
                return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        """Qt repaints the whole list when it gains or loses focus, yet only the current row's ring changes: that row
        alone is repainted (Sonic, 2026-10-08: nothing visible changed, nothing redrawn). Qt's own step is kept: by the
        keyboard, a list with no current row makes its first one current (`moveCursor`, as QAbstractItemView does)."""
        if not self.currentIndex().isValid() and event.reason() != Qt.FocusReason.MouseFocusReason:
            index = self.moveCursor(QAbstractItemView.CursorAction.MoveNext, Qt.KeyboardModifier.NoModifier)
            if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
                scrolls = self.hasAutoScroll()
                self.setAutoScroll(False)                # made current where it stands: the list doesn't jump
                self.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.setAutoScroll(scrolls)
        if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                              Qt.FocusReason.ShortcutFocusReason):
            self.focus_visible = True                # reached by the keyboard: its ring shows (`_update_current`)
        if self.focus_visible:                       # no ring shown (focus by a click): nothing to repaint (S19)
            self._update_current()
            self._retouch()
        event.accept()

    def focusOutEvent(self, event):
        """The ring goes with the focus (that row alone repainted, and only if it showed one). Leaving for another
        widget forgets the keyboard, as CSS's :focus-visible does; the window losing the focus keeps it, so the ring
        comes back with the window."""
        if self.focus_visible:
            self._update_current()
            if event.reason() != Qt.FocusReason.ActiveWindowFocusReason:
                self.focus_visible = False
            self._retouch()
        event.accept()

    # files dragged in from Windows Explorer (W3.1a §2): the drag controller places them --------------------------- #
    def dragEnterEvent(self, event):
        if self.drag is not None and self.drag.files_wanted(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.drag is not None and self.drag.files_wanted(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.drag is not None and self.drag.files_dropped(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _update_current(self):
        index = self.currentIndex()
        if index.isValid():
            self.update(index)

    def changeEvent(self, event):
        super().changeEvent(event)


# The list's layout mode (P-layout, W2.2 row 0, this desktop, 20,000 rows): one pass. Qt 6.11's batched mode was worse
# on every count — its batches ran in one stretch of the event loop (1,494 ms to lay 20,000 out, 120 ms for an insert,
# 258 ms for a reset, against one pass's 83 / 73 ms) and an insert lost the scroll place. One pass costs ~4 µs a row
# (the delegate's sizeHint): within the 4 ms step up to ~1,000 rows in one list; past that, a relayout (a row opened,
# the rows changed) is a long step — W3.1's (*As built*).
LAYOUT_MODE = QListView.LayoutMode.SinglePass
LAYOUT_BATCH = 100
