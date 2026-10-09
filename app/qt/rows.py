"""The painted rows (W2.2; the window's spec 05 §5.3, §5.9, §5.11, A3, A4; the mock's anatomy: the planning folder's
`tracks/window/work/w22/mock-anatomy.md`).

Every list in the window is a `QListView` over a `RowsModel`, painted by a `RowDelegate` — **no widget per row**
(BRIEF: paint lists, don't build them from widgets). What a row says is `app/services/view_rows.py`'s; this file only
paints it:
- **the hero** (*Up next*): the list's first row, painted taller (so a screen reader reaches it like any row) — the
  cover, the eyebrow, the title and its episode, the source, *% known · N new words*, the episode chips, ▶ *Watch* (or
  the muted *No video*) and the next episode's status;
- **a row**: its place, cover, title over its one line, *% · N new* in fixed tabular slots, the on-disk mark and the
  status pill; on hover or keyboard focus ▶; open, its episodes under it (the tick, the label, the numbers, the status, ▶);
- **the lines** in the gap after their rows: the top-20 line (dashed) and the Soon line;
- **Finished**'s month labels and rows (a date, no numbers), **Needs you**'s cards.

Text is cached as `QStaticText` per (text, font, width) and dropped when the text size or the screen's pixel ratio
changes; generated covers are cached pixmaps per (title, size, ratio). Tooltips on every painted part go through the
window's bubble (`tooltip.Tooltips.request(widget, rect, text)`); each row answers `AccessibleTextRole` (title · % known
· N new · status) and `AccessibleDescriptionRole` (its one line).

Display only (W2.2): nothing here writes. ▶ asks the page to open a file (`play_requested`); a row opens and closes.
"""
import bisect
import os
import time
from collections import OrderedDict

from PyQt6.QtCore import (QAbstractListModel, QItemSelectionModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize,
                          Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QStaticText, QTextOption)
from PyQt6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from app import theme
from app.qt import strings, style
from app.services import view_rows

ROW_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2

# Entry kinds the model holds
HERO, ROW, MONTH, FINISHED, NEED, FAILURE, EMPTY = "hero", "row", "month", "finished", "need", "failure", "empty"


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
        q = _QCOLOURS[key] = style.qcolor(colours[name] if name in colours else theme.FIXED[name])
    return q


def fz():
    return theme.text_factor(style.current()[1])


# --- covers -------------------------------------------------------------------------------------------------------- #
_COVERS = OrderedDict()
_COVER_BYTES = [0]
COVERS_MB = 8                                        # covers kept, by bytes (a row's cover is ~50 KB at 250 %): a
#                                                      painted row holds its cover, so only new rows need one


def clear_covers():
    _COVERS.clear()
    _COVER_BYTES[0] = 0


def cover(title, w, h, dpr, large=False):
    """The generated cover of a title (05 §5.6: the fallback and the offline look): the mock's gradient, the title's
    first characters down it. Cached per (title, size, ratio)."""
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
    step = fm.height() * 0.92
    x = w - w * 0.08 - fm.horizontalAdvance("あ")
    y = h * 0.09
    for ch in (title or "")[: max(1, int((h * 0.82) // max(1.0, step)))]:      # vertical: one character under another
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
    elif kind == "no_media":
        p.drawEllipse(r.adjusted(w * 0.14, h * 0.14, -w * 0.14, -h * 0.14))
        p.drawLine(QPointF(x + w * 0.2, y + h * 0.8), QPointF(x + w * 0.8, y + h * 0.2))
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
    p.restore()


STATUS_ICON = {"in_anki": "check", "mining": "mining", "waiting": "waiting", "mine_rest": "check", "mine": "mine",
               "no_media": "no_media"}


def pill_size(status, dpr=1.0):
    f = fz()
    w_text = TEXT.metrics("status-pill", dpr=dpr).horizontalAdvance(status.label)
    pad = 8 if status.kind == "no_media" else 9
    return QSize(round(pad * 2 * f + 13 + 6 * f + w_text), round(theme.SIZES["status-pill"] * f))


def paint_pill(p, status, rect, dpr=1.0):
    """The one status pill (mock `stHTML`): its glyph, its label, its look by tone."""
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
    elif status.kind in ("mine", "deleted"):
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
    ic = QRectF(rect.x() + pad, rect.center().y() - 6.5, 13, 13)
    colour = style.qcolor(col[ink])
    icon(p, STATUS_ICON.get(status.kind, "dot"), ic, colour)
    TEXT.draw(p, ic.right() + 6 * f, rect.center().y(), status.label, "status-pill", rect.right() - ic.right() - 6 * f,
              colour, dpr=dpr)
    p.restore()


def paint_mark(p, mark, right, y_mid, dpr=1.0):
    """The on-disk mark (⌀ N) ending at `right`; -> its rect."""
    f = fz()
    col = style.colours()
    colour = style.qcolor(col["warn"] if mark.tone == "warn" else col["ink-faint"])
    label = str(mark.count) if mark.count > 1 else ""
    w_text = TEXT.metrics("disk-mark", dpr=dpr).horizontalAdvance(label) if label else 0
    w = round(5 * f * 2 + 14 + (3 + w_text if label else 0))
    h = round(22 * f)
    rect = QRect(round(right - w), round(y_mid - h / 2), w, h)
    icon(p, "no_media", QRectF(rect.x() + 5 * f, y_mid - 7, 14, 14), colour)
    if label:
        TEXT.draw(p, rect.x() + 5 * f + 17, y_mid, label, "disk-mark", w_text + 2, colour, dpr=dpr)
    return rect


def paint_diff(p, pct, tone, n_new, right, y_mid, dpr=1.0):
    """*94% · 138 new* in fixed tabular slots, right-aligned at `right` (G1.6 #3: the numbers line up row to row)."""
    f = fz()
    col = style.colours()
    fm = TEXT.metrics("diff", dpr=dpr)
    zero = fm.horizontalAdvance("0")
    pct_w, dot_w, cnt_w = 4.6 * zero, 1.8 * zero, 3.3 * zero
    new_txt = strings.ROWS_NEW_WORD
    new_w = fm.horizontalAdvance(" " + new_txt)
    x = right - new_w
    pct_colour = style.qcolor(col["ok"] if tone == "ok" else col["warn"] if tone == "warn" else col["ink-dim"])
    dim = style.qcolor(col["ink-dim"])
    if pct is None and n_new is None:
        TEXT.draw(p, right - 60 * f, y_mid, strings.ROWS_DASH, "diff", 60 * f, dim, align="right", dpr=dpr)
        return
    if n_new is not None:
        TEXT.draw(p, x, y_mid, " " + new_txt, "diff", new_w + 2, dim, dpr=dpr)
        TEXT.draw(p, x - cnt_w, y_mid, str(n_new), "diff", cnt_w, style.qcolor(col["ink"]), weight=600, align="right",
                  dpr=dpr)
    x -= cnt_w
    TEXT.draw(p, x - dot_w, y_mid, strings.ROWS_DOT, "diff", dot_w, dim, align="centre", dpr=dpr)
    x -= dot_w
    TEXT.draw(p, x - pct_w, y_mid, strings.ROWS_DASH if pct is None else strings.ROWS_PCT.format(pct=round(pct)),
              "diff", pct_w,
              pct_colour if pct is not None else dim, align="right", dpr=dpr)


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
            if kind in (HERO, ROW, FINISHED):
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
        """What decides an entry's height — the delegate's own rule (`RowDelegate._shape`): a closed row's episodes
        decide none, so a file joining a closed row is a "same" refresh, not a relayout of every row (review D-3)."""
        return RowDelegate._shape(entry, self.open_key is not None and
                                  self.open_key == getattr(entry[1], "key", None))

    def looks_different(self, i):
        """Whether changed row `i` paints differently from before the last "same" refresh: a closed row rebuilt with
        nothing it shows changed (`_same_face`) is no repaint (S19). The view asks it for the rows on screen and those
        painted ahead only: a row further off is checked by `_sprite` when it comes into view (review D-1: comparing
        every changed row cost ~6 ms on the window's thread after a numbers version at 2,000 rows)."""
        old, new = self.before[i], self.entries[i]
        return not (old[2] == new[2] and new[0] in (ROW, FINISHED) and
                    getattr(new[1], "key", None) != self.open_key and _same_face(old[1], new[1], new[0]))

    def set_entries(self, entries):
        """-> "same" (payloads swapped in place: the changed rows repaint, `self.changed`), "relayout" (same keys,
        another height somewhere) or "reset"."""
        keys = [self.key_of(e) for e in entries]
        if keys == self.keys and entries:
            old = self.entries
            shapes = [self.shape_of(e) for e in old] == [self.shape_of(e) for e in entries]
            self.changed = [i for i, (a, b) in enumerate(zip(old, entries)) if a[1] is not b[1] or a[2] != b[2]]
            self.before = old                       # what `looks_different` compares with
            self.entries = list(entries)
            return "same" if shapes else "relayout"
        # S19's written skip: a reset (a row added or gone, even below the screen) repaints the screen's rows — Qt's
        # QListView relays out and repaints its viewport on any reset or insert — but from their kept pixmaps (no row
        # drawn afresh: `_same_face`); an insert that repaints nothing on screen waits for W3.1's uniform rows (IK-38)
        self.beginResetModel()
        self.changed, self.before = [], []
        self.entries = list(entries)
        self.keys = keys
        if self.open_key is not None and not any(k[1] == self.open_key for k in keys):
            self.open_key = None
        self.endResetModel()
        return "reset"


# --- the delegate: geometry, painting, hit-testing ----------------------------------------------------------------- #
GRIP = 12                                            # the grip's column before a Current row's number (mock `.grip`)
EP_LABEL_IN = 12 + 20 + 12                           # an episode's label from its rule: a gap, the tick, a gap
CHIP_DOT = 4 + 6                                     # a mined chip's dot after its number: the mock's gap, the dot
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
# place (`_replace(index=…)`: its number is drawn over the pixmap, `_paint_number`), and a row leaving the top 20,
# rebuilt as its episodes' place in the top moved yet usually showing nothing new (W2.2 speed round 5, R2). The hero
# paints its episodes, so it is compared by identity alone.
_UNSHOWN = {ROW: frozenset(("index", "episodes", "accessible", "description")),
            FINISHED: frozenset(("index", "episodes", "accessible", "description")),
            "ep": frozenset(("in_top", "rel_path"))}


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

    def _sprite(self, kind, payload, size, dpr, hovered, draw, ident=None, ground="bg", to=None, spare=False):
        """A closed row painted once into a pixmap (on the list's own ground, so text keeps its subpixel smoothing) and
        reused while the row object, its width and height, the screen's ratio, the look and the hover are the same.
        The reader keeps an unchanged row the same object between builds, so a refresh repaints from these. Its lines
        (the top-20 and Soon lines) are drawn outside it, so a line that moves re-renders nothing (review B-13)."""
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
               hovered)
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
    def _lines_h(self, lines):
        return len(lines) * round(15 * fz() + 6)

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
        return kind, len(lines), is_open and kind in (HERO, ROW), n

    def _size_hint(self, entry, is_open):
        kind, payload, lines = entry
        f = fz()
        gap = theme.SPACING["list-gap"]
        if kind == HERO:
            h = max(theme.SIZES["hero-cover-h"] + 32, round(self._hero_text_h()) + 32)
            if is_open:
                h += self._episodes_h(payload) + 14
            return QSize(100, h + 8 + gap + self._lines_h(lines))
        if kind in (ROW, FINISHED):
            h = round(theme.SIZES["row"] * f)
            if is_open and kind == ROW:
                h += self._episodes_h(payload) + 10
            return QSize(100, h + gap + self._lines_h(lines))
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
        """An open row's episode list: 4 px, then one `episode-row` per episode (as `_episode_rows` lays them)."""
        return 4 + len(row.episodes) * round(theme.SIZES["episode-row"] * fz())

    def _hero_text_h(self):
        f = fz()
        return (11 * f * 1.45 + 21 * f * 1.2 + 12.5 * f * 1.45 + 12.5 * f * 1.45 + 24 * f + 4 + 4 * 5)

    # geometry ------------------------------------------------------------------------------------------------ #
    def columns(self, rect, kind=ROW):
        """The fixed right-hand columns of a row (mock `.rowline`): {name: QRect}, right to left."""
        f = fz()
        top, h = rect.top(), round(theme.SIZES["row"] * f)
        right = rect.right() - 8
        acts = QRect(round(right - theme.SIZES["col-acts"] * f), top, round(theme.SIZES["col-acts"] * f), h)
        stat = QRect(round(acts.left() - 12 - theme.SIZES["col-stat"] * f), top, round(theme.SIZES["col-stat"] * f), h)
        diff = QRect(round(stat.left() - 12 - theme.SIZES["col-diff"] * f), top, round(theme.SIZES["col-diff"] * f), h)
        if kind == FINISHED:
            date = QRect(round(stat.left() - 12 - 64 * f), top, round(64 * f), h)
            return {"acts": acts, "stat": stat, "date": date, "text_right": date.left() -
                    round(theme.SIZES["title-to-number"] * f)}
        return {"acts": acts, "stat": stat, "diff": diff,
                "text_right": diff.left() - round(theme.SIZES["title-to-number"] * f)}

    @staticmethod
    def lead(kind, left):
        """The left of a row (mock `.rowline`): (its number's slot, its cover, its title) x. A Current row keeps the
        grip's column before its number (12 px + 12, the drag's handle in W3.1) as the mock does; a Finished row has no
        grip and an empty number slot, so its cover sits 24 px further left (G2.3: matched to the mock's captures)."""
        f = fz()
        number = left + 4 + (GRIP + 12 if kind == ROW else 0)
        cover_x = number + round(20 * f) + 12
        return number, cover_x, cover_x + round(theme.SIZES["row-cover-w"] * f) + 12      # 13 past the cover's last px

    def parts(self, entry, rect):
        """Every hit-testable part of an entry: [(name, QRect, tooltip, payload)] — the view's tooltips and clicks."""
        kind, payload, lines = entry
        out = []
        f = fz()
        if kind == HERO:
            g = self._hero_geometry(payload, rect, lines)
            out.append(("play", g["play"], payload.play_tip, payload.episodes[payload.next_index]))
            if payload.episodes[payload.next_index].status:
                out.append(("status", g["status"], payload.episodes[payload.next_index].status.tip, None))
            for chip_rect, chip in g["chips"]:
                out.append(("chip", chip_rect, chip.tip, None))
            out.append(("title", g["title"], payload.title, None))
            if self.view.model().open_key == payload.key:
                out += self._episode_parts(payload, g["eps"], hero=True)
            out.append(("open", g["main"], None, None))
        elif kind in (ROW, FINISHED):
            h = round(theme.SIZES["row"] * f)
            line = QRect(rect.left(), rect.top(), rect.width(), h)
            cols = self.columns(line, kind)
            st_rect, mk_rect = self._status_rects(payload, cols["stat"])
            if kind == FINISHED:                       # Finished: only Mining… / ✓ N (words in its tip), no mark
                mk_rect = None
                if payload.status is None or payload.status.kind not in ("in_anki", "mining"):
                    st_rect = None
            if st_rect is not None:
                out.append(("status", st_rect, payload.status.tip, None))
            if mk_rect is not None:
                out.append(("mark", mk_rect, payload.mark.tip, None))
            if payload.studying:
                x0 = self.lead(kind, line.left())[2]
                out.append(("studying", QRect(x0, line.center().y(), self._studying_w(), round(19 * f) + 4),
                            strings.ROWS_STUDYING_TIP, None))
            if kind == ROW:
                out.append(("play", self._play_rect(cols["acts"]), payload.play_tip,
                            payload.episodes[payload.next_index]))
            out.append(("title", QRect(line.left(), line.top(), cols["text_right"] - line.left(), h),
                        payload.title + ("\n" + payload.line if payload.line else ""), None))
            if kind == ROW and self.view.model().open_key == payload.key:
                out += self._episode_parts(payload, QRect(rect.left(), line.bottom() + 1, rect.width(),
                                                          rect.height() - h))
            out.append(("open", line, None, None))
        elif kind == NEED:                             # its line lives in the tooltip (G2.3 N1: the card stays clean)
            out.append(("title", rect, payload.title + ("\n" + payload.line if payload.line else ""), None))
        y = rect.bottom() + 1 - self._lines_h(lines)
        for ln in lines:
            strip = QRect(rect.left(), y, rect.width(), round(15 * fz() + 6))
            out.append((ln.kind + "-line", strip, ln.tip, None))
            y += strip.height()
        return out

    def _play_rect(self, acts):
        side = round(theme.SIZES["icon-button"] * fz())
        return QRect(acts.left() + 2, acts.center().y() - side // 2, side, side)

    def _status_rects(self, row, stat):
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

    def _episode_rows(self, row, area, hero=False):
        """An open row's episodes, one rect each: from its rule (a tick and a gap before the label) to the row's own
        right edge, so an episode's label starts where its show's title does and its numbers, status and ▶ stand in
        the list's columns — a row's own, and in the hero those of the rows under it (G2.3 A1, A2; `_episode_cols`)."""
        f = fz()
        if hero:
            title_x = area.left() + 20 + theme.SIZES["hero-cover-w"] - 1 + 18      # `_hero_geometry`'s main column
        else:
            title_x = self.lead(ROW, area.left())[2]
        left = title_x - EP_LABEL_IN
        right = area.right()
        h = round(theme.SIZES["episode-row"] * f)
        y = area.top() + 4
        out = []
        for ep in row.episodes:
            out.append((QRect(left, y, right - left + 1, h), ep))     # its right is the row's (haiku-code G1: 1 px)
            y += h
        return out

    def _episode_parts(self, row, area, hero=False):
        out = []
        for r, ep in self._episode_rows(row, area, hero):
            cols = self._episode_cols(r)
            out.append(("play", cols["play"], ep.play_tip, ep))
            if ep.status is not None:
                size = pill_size(ep.status)
                out.append(("status", QRect(cols["stat"].right() - size.width(), cols["stat"].center().y() -
                                            size.height() // 2, size.width(), size.height()), ep.status.tip, None))
            out.append(("tick", cols["tick"], strings.ROWS_TICK_WATCHED if ep.watched else strings.ROWS_TICK_NOT, None))
        return out

    def _episode_cols(self, r):
        """An episode's parts: a list row's columns (`columns`, from the same right edge) at the episode's height —
        % · new, the status and ▶ line up with its show row's (G2.3 A1, A2); in the hero, with the rows under it."""
        cols = self.columns(r)
        acts, stat, diff = cols["acts"], cols["stat"], cols["diff"]
        play = self._play_rect(QRect(acts.left(), r.top(), acts.width(), r.height()))
        stat = QRect(stat.left(), r.top(), stat.width(), r.height())
        diff = QRect(diff.left(), r.top(), diff.width(), r.height())
        tick = QRect(r.left() + 12, r.center().y() - 10, 20, 20)
        return {"play": play, "stat": stat, "diff": diff, "tick": tick, "text_left": r.left() + EP_LABEL_IN,
                "text_right": diff.left() - 12}

    def _hero_geometry(self, row, rect, lines=()):
        f = fz()
        box = QRect(rect.left(), rect.top(), rect.width(), rect.height() - 8 - theme.SPACING["list-gap"] -
                    self._lines_h(lines))
        is_open = self.view.model().open_key == row.key
        head_h = max(theme.SIZES["hero-cover-h"] + 32, round(self._hero_text_h()) + 32)
        head = QRect(box.left(), box.top(), box.width(), head_h)
        cov = QRect(head.left() + 20, head.top() + (head_h - theme.SIZES["hero-cover-h"]) // 2,     # centred, as the
                    theme.SIZES["hero-cover-w"], theme.SIZES["hero-cover-h"])                      # mock's heroline
        side_w = round(max(150 * f, 120))
        side = QRect(head.right() - 18 - side_w, head.top() + 16, side_w, head_h - 32)
        main = QRect(cov.right() + 18, head.top() + 16, side.left() - 18 - cov.right() - 18, head_h - 32)
        btn_h = round(theme.SIZES["button"] * f)
        play_w = round(TEXT.metrics("button").horizontalAdvance(self._watch_label(row)) + 13 * 2 + 18)  # its own
        #                                                                       label (the mock's .btn: padding 13)
        play = QRect(side.right() - play_w, side.center().y() - btn_h - 5, play_w, btn_h)
        status = QRect(side.left(), side.center().y() + 5, side.width(), round(theme.SIZES["status-pill"] * f))
        if row.episodes[row.next_index].status is not None:
            size = pill_size(row.episodes[row.next_index].status)
            status = QRect(side.right() - size.width(), side.center().y() + 5, size.width(), size.height())
        # the text column, top to bottom (gap 5)
        y = main.top()
        eyebrow_h = round(11 * f * 1.45)
        title_h = round(21 * f * 1.25)
        sub_h = round(12.5 * f * 1.45)
        stats_h = round(12.5 * f * 1.45)
        g = {"box": box, "head": head, "cover": cov, "main": QRect(cov.left(), head.top(), main.right() - cov.left(),
                                                                   head_h),
             "play": play, "status": status}
        g["eyebrow"] = QRect(main.left(), y, main.width(), eyebrow_h)
        y += eyebrow_h + 5
        g["title"] = QRect(main.left(), y, main.width(), title_h)
        y += title_h + 5
        # the sub line (mock `heroSub`): *Hato* for a hato show, the channel for a video; otherwise dropped
        g["sub"] = QRect(main.left(), y, main.width(), sub_h) if row.source == "hato" or \
            (row.media == "youtube" and row.line) else None
        if g["sub"] is not None:
            y += sub_h + 5
        g["stats"] = QRect(main.left(), y, main.width(), stats_h)
        y += stats_h + 5 + 4
        chips = []
        if row.chips and not is_open:
            cx = main.left()
            ch_h = round(24 * f)
            fm = TEXT.metrics("chip")
            for chip in row.chips + ((None,) if row.more_chips else ()):
                text = chip.text if chip is not None else strings.ROWS_MORE_CHIP.format(n=row.more_chips)
                w = max(round(30 * f), fm.horizontalAdvance(text) + round(16 * f) + (CHIP_DOT if chip is not None and
                                                                                      chip.mined else 0))
                if cx + w > main.right():
                    break
                chips.append((QRect(cx, y, w, ch_h), chip if chip is not None else
                              type(row.chips[0])(text, False, False, False, strings.ROWS_MORE_CHIPS.format(
                                  n=row.more_chips))))
                cx += w + 5
        g["chips"] = chips
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
        body = QRect(rect.left(), rect.top(), rect.width(), rect.height() - theme.SPACING["list-gap"] -
                     self._lines_h(lines))
        is_open = self.view.model().open_key == getattr(payload, "key", None)
        if kind == HERO and not is_open:
            pix, box = self._closed(kind, payload, lines, rect, dpr, hovered, p)
            if pix is not None:
                p.drawPixmap(box.topLeft(), pix)
            if focused:
                self._focus_ring(p, box, theme.RADII["r-sm"])
        elif kind == HERO:
            self._paint_open_hero(p, payload, rect, lines, hovered, focused, dpr)
        elif kind in (ROW, FINISHED) and not is_open:
            pix, _box = self._closed(kind, payload, lines, rect, dpr, hovered, p)
            if pix is not None:
                p.drawPixmap(body.topLeft(), pix)
            if kind == ROW:
                self._paint_number(p, payload, body, dpr)
            if focused:
                self._focus_ring(p, body, theme.RADII["r-sm"])
                if kind == ROW and not hovered:
                    cols = self.columns(QRect(body.left(), body.top(), body.width(),
                                              round(theme.SIZES["row"] * fz())), kind)
                    self._paint_play_button(p, self._play_rect(cols["acts"]), payload.can_play)
        elif kind in (ROW, FINISHED):
            self._paint_open_row(p, kind, payload, body, hovered, focused, dpr, lines)
        elif kind == MONTH:
            TEXT.draw(p, rect.left() + 4, rect.bottom() - round(11.5 * fz() * 0.9) - 4, payload.upper(), "month",
                      rect.width() - 8, c("ink-faint"), dpr=dpr)
        elif kind == NEED:
            self._paint_need(p, payload, rect, dpr)
        elif kind == FAILURE:
            self._paint_failure(p, payload, rect, dpr)
        elif kind == EMPTY:
            title, line = payload
            mid = rect.center().y()
            TEXT.draw(p, rect.left(), mid - 12 * fz(), title, "page-heading", rect.width(), c("ink"), align="centre",
                      dpr=dpr)
            TEXT.draw(p, rect.left(), mid + 14 * fz(), line, "body", rect.width(), c("ink-dim"), weight=400,
                      align="centre", dpr=dpr)
        y = rect.bottom() + 1 - self._lines_h(lines)
        for ln in lines:
            self._paint_line(p, ln, QRect(rect.left(), y, rect.width(), round(15 * fz() + 6)), dpr)
            y += round(15 * fz() + 6)
        p.restore()

    def _closed(self, kind, payload, lines, rect, dpr, hovered, p=None):
        """A closed hero or row's pixmap (painted once, `_sprite`) and the box it fills in `rect` (pixmaps off and a
        painter `p` given: drawn there, and no pixmap)."""
        if kind == HERO:
            box_h = rect.height() - 8 - theme.SPACING["list-gap"] - self._lines_h(lines)
            local = QRect(0, 0, rect.width(), rect.height())
            pix = self._sprite(kind, payload, QSize(rect.width(), box_h), dpr, hovered,
                               lambda q: self._paint_hero(q, payload, local, lines, hovered, False, dpr),
                               to=None if p is None else (p, rect.topLeft()))
            return pix, QRect(rect.left(), rect.top(), rect.width(), box_h)
        body = QRect(rect.left(), rect.top(), rect.width(), rect.height() - theme.SPACING["list-gap"] -
                     self._lines_h(lines))
        local = QRect(0, 0, body.width(), body.height())
        pix = self._sprite(kind, payload, body.size(), dpr, hovered,
                           lambda q: self._paint_row(q, kind, payload, local, hovered, False, dpr, lines, number=False),
                           to=None if p is None else (p, body.topLeft()))
        return pix, body

    def _paint_open_row(self, p, kind, row, body, hovered, focused, dpr, lines):
        """An open row: its head painted once into a pixmap, then the episodes (each its own pixmap), all on the list's
        own ground — no box or outline (G2.3 R1, as the mock) — so opening a row costs a relayout and blits, and a
        repaint of an open row draws no row text or cover afresh: only its number, over the head (its rule and focus
        ring are a few strokes)."""
        h = round(theme.SIZES["row"] * fz())
        local = QRect(0, 0, body.width(), h)         # the head alone: its hover a whole rounded head, warmed or not
        radius = theme.RADII["r-sm"]
        rest = QRect(body.left(), body.top() + h, body.width(), body.height() - h)
        pix = self._sprite(kind, row, QSize(body.width(), h), dpr, hovered,
                           lambda q: self._paint_row(q, kind, row, local, hovered, False, dpr, lines, episodes=False,
                                                     number=False),
                           ident=(row.key, "open"), to=(p, body.topLeft()))
        if pix is not None:
            p.drawPixmap(body.topLeft(), pix)
        if kind == ROW:
            self._paint_number(p, row, body, dpr)
        if focused:
            self._focus_ring(p, body, radius)
            if kind == ROW and not hovered:
                cols = self.columns(QRect(body.left(), body.top(), body.width(), h), kind)
                self._paint_play_button(p, self._play_rect(cols["acts"]), row.can_play)
        if kind == ROW:
            self._paint_episodes(p, row, rest, dpr, lines=lines)

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
        if kind == HERO:
            head = max(theme.SIZES["hero-cover-h"] + 32, round(self._hero_text_h()) + 32)
        else:
            head = round(theme.SIZES["row"] * fz())
        area = QRect(rect.left(), rect.top() + head + 1, rect.width(), 1 << 20)
        before = self.warmed
        if kind == ROW:
            # its open head first, as the click will show it — under the pointer, so hovered (an open row's hover
            # lights its head only), the body's whole height below it as `_paint_open_row` lays
            # it: opening it then draws no head afresh (speed round 5: the head was each first opening's own render)
            local = QRect(0, 0, rect.width(), head)       # the head alone, as `_paint_open_row` draws it
            self._warming = True
            try:
                self._sprite(kind, row, QSize(rect.width(), head), dpr, True,
                             lambda q: self._paint_row(q, kind, row, local, True, False, dpr, lines, episodes=False,
                                                       number=False),
                             ident=(row.key, "open"), spare=True)
            finally:
                self._warming = False
            if self.warmed != before:
                return True
        budget = SPRITE_MB["ep"] * 1024 * 1024 // 2    # never more than half the episodes' cache: past it, each one
        self._warming = True                            # drawn would push out one drawn before, again and again
        try:
            for r, ep in self._episode_rows(row, area, kind == HERO):
                budget -= round(r.width() * dpr) * round(r.height() * dpr) * 4
                if r.top() - rect.top() > room or budget < 0:
                    break
                w, h = r.width(), r.height()
                self._sprite("ep", ep, r.size(), dpr, False,
                             lambda q, ep=ep, w=w, h=h: self._paint_episode(q, QRect(0, 0, w, h), ep, dpr),
                             ident=(ep.id, kind == HERO), ground="surface" if kind == HERO else "bg")
                if self.warmed != before:
                    return True
        finally:
            self._warming = False
        return False

    def _paint_line(self, p, ln, strip, dpr):
        col = style.colours()
        y = strip.center().y() + 0.5
        if ln.kind == "top":
            pen = QPen(style.qcolor(col["top20-line"]), 1)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 3])
            p.setPen(pen)
            p.drawLine(QPointF(strip.left() + 4, y), QPointF(strip.right() - 4, y))
        else:                                        # Soon: no word, a hairline in the separators' colour, from the
            p.setPen(QPen(style.qcolor(col["line"]), 1))     # covers on (G2.3 L1: quieter than the top-20 line)
            p.drawLine(QPointF(self.lead(ROW, strip.left())[1], y), QPointF(strip.right() - 4, y))

    def _paint_cover(self, p, title, rect, dpr, large=False):
        p.drawPixmap(rect.topLeft(), cover(title, rect.width(), rect.height(), dpr, large))

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
        for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS["hb"]):
            grad.setColorAt(pos, style.qcolor(colour))
        return QBrush(grad)

    def _focus_ring(self, p, r, radius):
        pen = QPen(c("accent"), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(r).adjusted(1, 1, -1, -1), radius, radius)

    def _paint_row(self, p, kind, row, body, hovered, focused, dpr, lines=(), episodes=True, number=True):
        f = fz()
        h = round(theme.SIZES["row"] * f)
        line = QRect(body.left(), body.top(), body.width(), h)
        radius = theme.RADII["r-sm"]
        is_open = kind == ROW and self.view.model().open_key == row.key
        if hovered:                                  # an open row has no ground or outline of its own (G2.3 R1, as
            p.setPen(Qt.PenStyle.NoPen)              # the mock): the pointer over it lights its head only
            p.setBrush(c("surface"))
            p.drawRoundedRect(QRectF(line if is_open else body), radius, radius)
        if focused:
            self._focus_ring(p, body, radius)
        if kind == ROW and number:
            self._paint_number(p, row, body, dpr)
        _number_x, x, title_x = self.lead(kind, line.left())
        cw, ch = round(theme.SIZES["row-cover-w"] * f), round(theme.SIZES["row-cover-h"] * f)
        crect = QRect(x, line.center().y() - ch // 2, cw, ch)
        self._paint_cover(p, row.cover_title, crect, dpr)
        if kind == ROW:
            self._paint_watched_bar(p, row, crect)
        x = title_x
        cols = self.columns(line, kind)
        text_w = cols["text_right"] - x
        t_h = round(13.5 * f * 1.3)
        s_h = round(12 * f * 1.3)
        top = line.center().y() - (t_h + 1 + s_h) / 2
        TEXT.draw(p, x, top + t_h / 2, row.title, "row-title", text_w, c("ink"), dpr=dpr)
        sx = x
        if row.studying:
            sw = self._paint_studying(p, sx, top + t_h + 1 + s_h / 2, dpr)
            sx += sw + 10
        TEXT.draw(p, sx, top + t_h + 1 + s_h / 2, row.line, "row-sub", cols["text_right"] - sx, c("ink-dim"), dpr=dpr)
        if kind == ROW:
            paint_diff(p, row.pct, row.pct_tone, row.n_new, cols["diff"].right(), line.center().y(), dpr)
        else:
            TEXT.draw(p, cols["date"].left(), line.center().y(), row.date, "date", cols["date"].width(),
                      c("ink-faint"), dpr=dpr)
        st_rect, mk_rect = self._status_rects(row, cols["stat"])
        if kind == FINISHED and row.status is not None and row.status.kind not in ("in_anki", "mining"):
            st_rect = None                                  # Finished shows only Mining… / ✓ N (words in its tip)
        if st_rect is not None:
            paint_pill(p, row.status, st_rect, dpr)
        if mk_rect is not None and kind == ROW:
            paint_mark(p, row.mark, mk_rect.right() + 1, line.center().y(), dpr)
        if kind == ROW and (hovered or focused):
            self._paint_play_button(p, self._play_rect(cols["acts"]), row.can_play)
        if is_open and episodes:
            area = QRect(body.left(), line.bottom() + 1, body.width(), body.bottom() - line.bottom())
            self._paint_episodes(p, row, area, dpr, lines=lines)

    def _paint_number(self, p, row, body, dpr):
        """A row's place in Current, drawn over its pixmap (never inside it): a file arriving above moves every number,
        and with the number inside, every row on screen was drawn again (~21 ms an arrival, bench 10; review B-5).
        Right-aligned in its slot and never cut: a number wider than the slot (#100 and on at a large text size) runs
        left into the grip's column, where an elided one read as nothing (G2.3 A4); `ink-dim`, so it shows."""
        f = fz()
        h = round(theme.SIZES["row"] * f)
        text = str(row.index)
        slot_right = self.lead(ROW, body.left())[0] + round(20 * f)
        w = max(round(20 * f), TEXT.metrics("position", dpr=dpr).horizontalAdvance(text) + 2)
        TEXT.draw(p, slot_right - w, QRect(body.left(), body.top(), body.width(), h).center().y(), text,
                  "position", w, c("ink-dim"), align="right", dpr=dpr, elide=False)

    def _studying_w(self, dpr=1.0):
        fm = TEXT.metrics("row-sub", 600, dpr)
        return round(11 * fz()) + 4 + fm.horizontalAdvance(strings.ROWS_STUDYING)

    def _paint_studying(self, p, x, y_mid, dpr):
        """*Studying its cards first* before a row's line: an up arrow and the words in the accent, on the row's own
        ground — no pill under the words (G2.3 R3: a pill with its words over it read badly). -> its width."""
        f = fz()
        side = round(11 * f)
        icon(p, "up", QRectF(x, y_mid - side / 2, side, side), c("accent"), width=1.5)
        w, _ = TEXT.draw(p, x + side + 4, y_mid, strings.ROWS_STUDYING, "row-sub", 400 * f, c("accent"), weight=600,
                         dpr=dpr)
        return side + 4 + w

    def _paint_play_button(self, p, r, enabled):
        p.save()
        if not enabled:
            p.setOpacity(0.4)
        icon(p, "play", QRectF(r.center().x() - 7, r.center().y() - 7, 14, 14), c("ink-dim"))
        p.restore()

    def _paint_episodes(self, p, row, area, dpr, hero=False, lines=()):
        f = fz()
        rows = self._episode_rows(row, area, hero)
        if not rows:
            return
        rule_x = rows[0][0].left() - 0.5
        p.setPen(QPen(c("line"), 1))
        p.drawLine(QPointF(rule_x, rows[0][0].top()), QPointF(rule_x, rows[-1][0].bottom()))
        clip = QRectF(self.view.viewport().rect()) if p.device() is self.view.viewport() else None
        split = next((ln.split for ln in (lines or ()) if ln.kind == "top" and ln.split), None)
        split_at = None
        for i, (r, ep) in enumerate(rows):
            if split is not None and i == split:       # the top-20 line runs through this row (A-12): drawn here too
                split_at = QRect(r.left() - 8, r.top() - 3, r.width() + 8, 6)
            if clip is not None and not clip.intersects(QRectF(r)):
                continue
            if clip is not None:                       # on screen: painted once into a pixmap, reused while unchanged
                w, h = r.width(), r.height()
                pix = self._sprite("ep", ep, r.size(), dpr, False,
                                   lambda q, ep=ep, w=w, h=h: self._paint_episode(q, QRect(0, 0, w, h), ep, dpr),
                                   ident=(ep.id, hero), ground="surface" if hero else "bg", to=(p, r.topLeft()))
                if pix is not None:
                    p.drawPixmap(r.topLeft(), pix)
            else:
                self._paint_episode(p, r, ep, dpr)
        if split_at is not None:
            self._paint_line(p, lines_top(lines), split_at, dpr)

    def _paint_episode(self, p, r, ep, dpr):
        """One episode row (an open row's): its tick, label, numbers, status, mark and ▶."""
        cols = self._episode_cols(r)
        tick = QRectF(cols["tick"])
        if ep.watched:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("accent"))
            p.drawEllipse(tick)
            icon(p, "check", tick.adjusted(4, 4, -4, -4), style.qcolor(theme.FIXED["on-accent"]))
        else:
            p.setPen(QPen(c("line-hi"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(tick.adjusted(0.75, 0.75, -0.75, -0.75))
        text_w = cols["text_right"] - cols["text_left"]
        lw, _ = TEXT.draw(p, cols["text_left"], r.center().y(), ep.label, "episode-label", text_w * 0.6,
                          c("ink-dim" if ep.watched else "ink"), dpr=dpr)
        paint_diff(p, ep.pct, view_tone(ep.pct), ep.n_new, cols["diff"].right(), r.center().y(), dpr)
        right = cols["stat"].right()
        if ep.status is not None:
            size = pill_size(ep.status, dpr)
            sr = QRect(right - size.width(), r.center().y() - size.height() // 2, size.width(), size.height())
            paint_pill(p, ep.status, sr, dpr)
            right = sr.left() - 4
        if ep.mark is not None:
            paint_mark(p, ep.mark, right, r.center().y(), dpr)
        self._paint_play_button(p, cols["play"], ep.can_play)

    def _paint_open_hero(self, p, row, rect, lines, hovered, focused, dpr):
        """An open hero: its head painted once into a pixmap, the rest of its box drawn around the episodes (each its
        own pixmap) — a repaint of the open hero draws no text or cover afresh (review B-13)."""
        g = self._hero_geometry(row, rect, lines)
        head = g["head"]
        local = QRect(0, 0, rect.width(), rect.height())
        self._hero_frame(p, g, hovered)              # the frame first, whole, then the head over it: a head pixmap
        pix = self._sprite(HERO, row, QSize(rect.width(), head.height()), dpr, hovered,    # that rounds short leaves
                           lambda q: self._paint_hero(q, row, local, lines, hovered, False, dpr, episodes=False),
                           ident=(row.key, "open"), to=(p, QPoint(rect.left(), head.top())))      # no ground line (C-3)
        if pix is not None:
            p.drawPixmap(QPoint(rect.left(), head.top()), pix)
        if focused:
            self._focus_ring(p, g["box"], theme.RADII["r-sm"])
        self._paint_episodes(p, row, g["eps"], dpr, hero=True, lines=lines)

    def _hero_frame(self, p, g, hovered):
        """The hero's box: its ground, the iris edge, the border."""
        box = QRectF(g["box"]).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.RADII["r-sm"]
        path = QPainterPath()
        path.addRoundedRect(box, radius, radius)
        p.fillPath(path, c("surface"))
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(box.left(), box.top(), 3, box.height()), self._iris(QRectF(box.left(), box.top(), 3,
                                                                                   box.height()), vertical=True))
        p.restore()
        p.setPen(QPen(c("line-hi" if hovered else "line"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_hero(self, p, row, rect, lines, hovered, focused, dpr, episodes=True):
        f = fz()
        g = self._hero_geometry(row, rect, lines)
        self._hero_frame(p, g, hovered)
        if focused:
            self._focus_ring(p, g["box"], theme.RADII["r-sm"])
        self._paint_cover(p, row.cover_title, g["cover"], dpr, large=True)
        self._paint_watched_bar(p, row, g["cover"])
        nxt = row.episodes[row.next_index]
        # eyebrow
        e = g["eyebrow"]
        icon(p, "dot", QRectF(e.left(), e.center().y() - 3.5, 7, 7), c("accent"))
        TEXT.draw(p, e.left() + 14, e.center().y(), strings.ROWS_UP_NEXT, "eyebrow", e.width() - 14, c("accent"),
                  dpr=dpr)
        # title + its episode
        t = g["title"]
        ep_txt = row.title_ep
        ep_w = TEXT.metrics("hero-title", 500, dpr).horizontalAdvance(ep_txt) + 8 if ep_txt else 0
        tw, _ = TEXT.draw(p, t.left(), t.center().y(), row.title, "hero-title", t.width() - ep_w, c("ink"), dpr=dpr)
        if ep_txt:
            TEXT.draw(p, t.left() + tw + 7, t.center().y(), ep_txt, "hero-title", ep_w, c("ink-dim"), weight=500,
                      dpr=dpr)
        if g["sub"] is not None:
            s = g["sub"]
            x = s.left()
            if row.source == "hato":
                w, _ = TEXT.draw(p, x, s.center().y(), strings.ROWS_SOURCE["hato"], "hero-sub", s.width(), c("ink"),
                                 weight=600, dpr=dpr)
                x += w + 8
            elif row.media == "youtube" and row.line:
                TEXT.draw(p, x, s.center().y(), row.line, "hero-sub", min(s.width(),
                                                                             theme.SIZES["channel-cap"] * f),
                          c("ink-dim"), dpr=dpr)
        st = g["stats"]
        stats = strings.ROWS_HERO_STATS_NONE if nxt.pct is None else strings.ROWS_HERO_STATS.format(
            pct=round(nxt.pct), n=nxt.n_new if nxt.n_new is not None else strings.ROWS_DASH)
        TEXT.draw(p, st.left(), st.center().y(), stats, "hero-sub", st.width(), c("ink-dim"), dpr=dpr)
        for chip_rect, chip in g["chips"]:
            self._paint_chip(p, chip_rect, chip, dpr)
        # the side: ▶ Watch / No video, then the next episode's status
        self._paint_watch(p, g["play"], row, nxt, dpr)
        if nxt.status is not None:
            paint_pill(p, nxt.status, g["status"], dpr)
        if episodes and self.view.model().open_key == row.key:
            self._paint_episodes(p, row, g["eps"], dpr, hero=True, lines=lines)

    def _paint_chip(self, p, r, chip, dpr):
        f = fz()
        rr = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        if chip.watched:
            p.setPen(QPen(c("watched-chip-border"), 1))
            p.setBrush(c("watched-chip-fill"))
        elif chip.next:
            p.setPen(QPen(c("accent"), 1.5))
            p.setBrush(c("bg"))
        else:
            p.setPen(QPen(c("line-hi"), 1))
            p.setBrush(c("bg"))
        p.drawRoundedRect(rr, 6, 6)
        ink = c("ink") if (chip.watched or chip.next) else c("ink-dim")
        fm = TEXT.metrics("chip", dpr=dpr)
        tw = fm.horizontalAdvance(chip.text)
        extra = CHIP_DOT if chip.mined else 0
        x = rr.center().x() - (tw + extra) / 2
        # the number's figures and the dot on the chip's true midline (G2.3 A3: the dot sat above it, and a QRect's
        # centre is half a pixel high): the text's box moved so its figures' middle (cap height) is the midline
        mid = rr.center().y()
        TEXT.draw(p, x, mid + fm.height() / 2 - fm.ascent() + fm.capHeight() / 2, chip.text, "chip", tw + 2, ink,
                  dpr=dpr)
        if chip.mined:
            icon(p, "dot", QRectF(x + tw + CHIP_DOT - 6, mid - 3, 6, 6), c("ok"))

    @staticmethod
    def _watch_label(row):
        """The hero's button's words: its verb (Watch / Listen / Read), *Online*, or *No <its media word>* (No video)."""
        if row.episodes[row.next_index].can_play:
            return row.verb
        if row.media == "youtube":
            return strings.ROWS_ONLINE_BUTTON
        return strings.ROWS_NO_MEDIA_BUTTON.format(word=row.media_word)

    def _paint_watch(self, p, r, row, nxt, dpr):
        f = fz()
        rr = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        if nxt.can_play:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._iris(rr))
            p.drawRoundedRect(rr, theme.RADII["button"], theme.RADII["button"])
            ink = style.qcolor(theme.FIXED["on-accent"])
            label = row.verb
        else:
            pen = QPen(c("line-hi"), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rr, theme.RADII["button"], theme.RADII["button"])
            ink = c("ink-faint")
            label = self._watch_label(row)
        fm = TEXT.metrics("button", dpr=dpr)
        total = 12 + 6 + fm.horizontalAdvance(label)
        x = r.center().x() - total / 2
        icon(p, "play", QRectF(x, r.center().y() - 6, 12, 12), ink)
        TEXT.draw(p, x + 18, r.center().y(), label, "button", fm.horizontalAdvance(label) + 2, ink, dpr=dpr)

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
        p.drawPixmap(cov.topLeft(), cover(need.cover_title, 44, 63, dpr))
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


def lines_top(lines):
    return next(ln for ln in lines if ln.kind == "top")


def view_tone(pct):
    return view_rows.pct_tone(pct)


# --- the view ----------------------------------------------------------------------------------------------------------- #
class RowsView(QListView):
    """A painted list: hover, tooltips and clicks by the delegate's parts; a click on a row opens or closes it; ▶ asks
    for its file (`play_requested`); Enter and Space open the current row."""

    play_requested = pyqtSignal(object)            # an Episode
    opened = pyqtSignal(object)                    # the key opened (None: closed)

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
        # the pointer resting on a closed row paints its episodes ahead (one a turn), so opening it only blits
        self._hover_warm = QTimer(self)
        self._hover_warm.setSingleShot(True)
        self._hover_warm.setInterval(HOVER_WARM_MS)
        self._hover_warm.timeout.connect(self._warm_hovered)

    def paintEvent(self, event):
        p = QPainter(self.viewport())
        p.fillRect(event.rect(), c("bg"))
        p.end()
        super().paintEvent(event)

    # entries ---------------------------------------------------------------------------------------------------- #
    def set_entries(self, entries):
        """Show these entries; a reset keeps the row that was at the top where it was."""
        model = self.model()
        anchor = self._anchor()
        before = model.entries
        how = model.set_entries(entries)
        if how == "same":
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
        elif how == "relayout":
            self.looks_changed = True
            self._rest()
            self.relayout()
            self.viewport().update()
        else:
            self.looks_changed = True
            self._rest()
            self._hover = None
            if anchor is not None and self.isVisible():
                self._restore = anchor
                self._apply_restore()
                self._restore = None                     # tried once: a place gone stays gone (W2.2 review A-15)
        return how

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
        if not self.isVisible():
            like = self.warm_like
            if like is not None and like.isVisible() and (like._warm.isActive() or
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
        model.open_key = None if model.open_key == key else key
        self.relayout()
        self.opened.emit(model.open_key)

    # hit-testing ------------------------------------------------------------------------------------------------- #
    def part_at(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid():
            return idx, None
        entry = self.model().entries[idx.row()]
        for part in self.delegate.parts(entry, self.visualRect(idx)):
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
        idx = self.indexAt(event.pos())
        row = idx.row() if idx.isValid() else None
        if row != self._hover:
            old, self._hover = self._hover, row
            for r in (old, row):
                if r is not None and r < self.model().rowCount():
                    self.update(self.model().index(r, 0))
            self._hover_warm.setInterval(HOVER_WARM_MS)
            self._hover_warm.start()
        if self.tooltips is not None:
            self.tooltips.hide_part_unless(self.viewport(), event.pos())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None and self._hover < self.model().rowCount():
            self.update(self.model().index(self._hover, 0))
        self._hover = None
        super().leaveEvent(event)

    def _show_focus(self, on):
        if self.focus_visible != on:
            self.focus_visible = on
            self._update_current()

    def mousePressEvent(self, event):
        self._show_focus(False)
        if event.button() == Qt.MouseButton.LeftButton:
            idx, part = self.part_at(event.pos())
            if idx.isValid():
                self.setCurrentIndex(idx)
                if part is not None and part[0] == "play" and part[3] is not None:
                    if part[3].can_play:
                        self.play_requested.emit(part[3])
                    event.accept()
                    return
                if part is not None and part[0] in ("open", "title"):
                    self.toggle(idx)
                    event.accept()
                    return
                if part is not None:                 # a pill, a mark, a chip, a tick: states, not buttons (W2.2)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        self._show_focus(True)
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
        event.accept()

    def focusOutEvent(self, event):
        """The ring goes with the focus (that row alone repainted, and only if it showed one). Leaving for another
        widget forgets the keyboard, as CSS's :focus-visible does; the window losing the focus keeps it, so the ring
        comes back with the window."""
        if self.focus_visible:
            self._update_current()
            if event.reason() != Qt.FocusReason.ActiveWindowFocusReason:
                self.focus_visible = False
        event.accept()

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
