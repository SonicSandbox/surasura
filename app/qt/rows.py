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
from collections import OrderedDict

from PyQt6.QtCore import (QAbstractListModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal)
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
            f.setFamilies(list(theme.font_families(language)))
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

    def static(self, text, role, width, weight=None, dpr=1.0):
        """(QStaticText, its width) of `text` in `role`, elided to `width` px."""
        self._check(dpr)
        k = (text, role, weight, int(width))
        hit = self._static.get(k)
        if hit is None:
            fm = self.metrics(role, weight, dpr)
            shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0, int(width)))
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

    def draw(self, p, x, y_mid, text, role, width, colour, weight=None, align="left", dpr=1.0):
        """Draw `text` vertically centred on `y_mid`; -> (the width drawn, whether it was elided)."""
        st, w, elided = self.static(text, role, width, weight, dpr)
        fm = self.metrics(role, weight, dpr)
        p.setFont(self.font(role, weight, dpr))
        p.setPen(colour)
        left = x + width - w if align == "right" else x + (width - w) / 2 if align == "centre" else x
        p.drawStaticText(QPointF(left, y_mid - fm.height() / 2), st)
        return w, elided


TEXT = Text()


def c(name):
    return style.qcolor(style.colours()[name] if name in style.colours() else theme.FIXED[name])


def fz():
    return theme.text_factor(style.current()[1])


# --- covers -------------------------------------------------------------------------------------------------------- #
_COVERS = {}


def cover(title, w, h, dpr, large=False):
    """The generated cover of a title (05 §5.6: the fallback and the offline look): the mock's gradient, the title's
    first characters down it. Cached per (title, size, ratio)."""
    key = (title, int(w), int(h), dpr, large)
    pix = _COVERS.get(key)
    if pix is not None:
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
    if len(_COVERS) > 800:
        _COVERS.clear()
    _COVERS[key] = pix
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
    elif status.kind == "mine":
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
        self.changed = []                           # rows a "same" refresh changed (repainted alone)

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

    @staticmethod
    def shape_of(entry):
        """What decides an entry's height: its kind, its episodes, its lines."""
        kind, payload, lines = entry
        return (kind, len(getattr(payload, "episodes", ()) or ()), len(lines))

    def set_entries(self, entries):
        """-> "same" (payloads swapped in place: the changed rows repaint, `self.changed`), "relayout" (same keys,
        another height somewhere) or "reset"."""
        keys = [self.key_of(e) for e in entries]
        if keys == self.keys and entries:
            old = self.entries
            shapes = [self.shape_of(e) for e in old] == [self.shape_of(e) for e in entries]
            self.changed = [i for i, (a, b) in enumerate(zip(old, entries)) if a[1] is not b[1] or a[2] != b[2]]
            self.entries = list(entries)
            return "same" if shapes else "relayout"
        self.beginResetModel()
        self.entries = list(entries)
        self.keys = keys
        if self.open_key is not None and not any(k[1] == self.open_key for k in keys):
            self.open_key = None
        self.endResetModel()
        return "reset"


# --- the delegate: geometry, painting, hit-testing ----------------------------------------------------------------- #
SPRITES_KEPT = 64                                    # painted rows kept (~0.7 MB each at 150 %, a 1,280 px window)


class RowDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.paints = 0                              # rows painted (tests: only what's on screen)
        self.renders = 0                             # rows drawn into a pixmap (tests: a repaint reuses them)
        self._sprites = OrderedDict()

    def _sprite(self, kind, payload, lines, size, dpr, hovered, draw, ident=None, ground="bg"):
        """A closed row painted once into a pixmap (on the list's own ground, so text keeps its subpixel smoothing) and
        reused while the row object, its lines, its width, the screen's ratio, the look and the hover are the same.
        The reader keeps an unchanged row the same object between builds, so a refresh repaints from these."""
        key = (kind, payload.key if ident is None else ident, size.width(), size.height(), dpr, style.current(),
               hovered)
        hit = self._sprites.get(key)
        if hit is not None and hit[0] is payload and hit[1] == lines:
            self._sprites.move_to_end(key)
            return hit[2]
        pix = QPixmap(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(c(ground))
        q = QPainter(pix)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        draw(q)
        q.end()
        self.renders += 1
        self._sprites[key] = (payload, lines, pix)
        self._sprites.move_to_end(key)
        while len(self._sprites) > SPRITES_KEPT:
            self._sprites.popitem(last=False)
        return pix

    # sizes ------------------------------------------------------------------------------------------------------ #
    def _lines_h(self, lines):
        return len(lines) * round(15 * fz() + 6)

    def sizeHint(self, option, index):
        entry = index.data(ROW_ROLE)
        if entry is None:
            return QSize(0, 0)
        kind, payload, lines = entry
        f = fz()
        gap = theme.SPACING["list-gap"]
        is_open = self.view.model().open_key == getattr(payload, "key", None)
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
            return QSize(100, round(16 * 2 + 14 * f * 1.45 + 4 + 12.5 * f * 1.45 + 10 +
                                    len(payload.episodes) * 34 * f + 2 + 12))
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
            if kind == FINISHED:                       # Finished paints only Mining… / N in Anki, never the mark
                mk_rect = None
                if payload.status is None or payload.status.kind not in ("in_anki", "mining"):
                    st_rect = None
            if st_rect is not None:
                out.append(("status", st_rect, payload.status.tip, None))
            if mk_rect is not None:
                out.append(("mark", mk_rect, payload.mark.tip, None))
            if payload.studying:
                fm = TEXT.metrics("badge")
                sw = fm.horizontalAdvance(strings.ROWS_STUDYING) + round(16 * f)
                x0 = line.left() + 4 + round(20 * f) + 12 + round(theme.SIZES["row-cover-w"] * f) + 13
                out.append(("studying", QRect(x0, line.center().y(), sw, round(19 * f) + 4),
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
        elif kind == NEED:
            out.append(("title", rect, payload.title, None))
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
        f = fz()
        left = area.left() + (128 if hero else 60)
        right = area.right() - (11 if hero else 12)
        h = round(theme.SIZES["episode-row"] * f)
        y = area.top() + 4
        out = []
        for ep in row.episodes:
            out.append((QRect(left, y, right - left, h), ep))
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
        f = fz()
        play_side = round(theme.SIZES["icon-button"] * f)
        play = QRect(r.right() - play_side, r.center().y() - play_side // 2, play_side, play_side)
        stat = QRect(round(play.left() - 12 - theme.SIZES["col-stat"] * f), r.top(),
                     round(theme.SIZES["col-stat"] * f), r.height())
        diff = QRect(round(stat.left() - 12 - theme.SIZES["col-diff"] * f), r.top(),
                     round(theme.SIZES["col-diff"] * f), r.height())
        tick = QRect(r.left() + 12, r.center().y() - 10, 20, 20)
        return {"play": play, "stat": stat, "diff": diff, "tick": tick, "text_left": tick.right() + 12,
                "text_right": diff.left() - 12}

    def _hero_geometry(self, row, rect, lines=()):
        f = fz()
        box = QRect(rect.left(), rect.top(), rect.width(), rect.height() - 8 - theme.SPACING["list-gap"] -
                    self._lines_h(lines))
        is_open = self.view.model().open_key == row.key
        head_h = max(theme.SIZES["hero-cover-h"] + 32, round(self._hero_text_h()) + 32)
        head = QRect(box.left(), box.top(), box.width(), head_h)
        cov = QRect(head.left() + 20, head.top() + 16, theme.SIZES["hero-cover-w"], theme.SIZES["hero-cover-h"])
        side_w = round(max(150 * f, 120))
        side = QRect(head.right() - 18 - side_w, head.top() + 16, side_w, head_h - 32)
        main = QRect(cov.right() + 18, head.top() + 16, side.left() - 18 - cov.right() - 18, head_h - 32)
        btn_h = round(theme.SIZES["button"] * f)
        play_w = round(TEXT.metrics("button").horizontalAdvance(strings.ROWS_NO_MEDIA_BUTTON.format(word="video")) +
                       13 * f * 2 + 18)
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
                w = max(round(30 * f), fm.horizontalAdvance(text) + round(16 * f) + (8 if chip is not None and
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
        entry = index.data(ROW_ROLE)
        if entry is None:
            return
        self.paints += 1
        kind, payload, lines = entry
        rect = option.rect
        dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus) and self.view.hasFocus()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        body = QRect(rect.left(), rect.top(), rect.width(), rect.height() - theme.SPACING["list-gap"] -
                     self._lines_h(lines))
        is_open = self.view.model().open_key == getattr(payload, "key", None)
        if kind == HERO and not is_open:
            box_h = rect.height() - 8 - theme.SPACING["list-gap"] - self._lines_h(lines)
            local = QRect(0, 0, rect.width(), rect.height())
            pix = self._sprite(kind, payload, lines, QSize(rect.width(), box_h), dpr, hovered,
                               lambda q: self._paint_hero(q, payload, local, lines, hovered, False, dpr))
            p.drawPixmap(rect.topLeft(), pix)
            if focused:
                self._focus_ring(p, QRect(rect.left(), rect.top(), rect.width(), box_h), theme.RADII["r-sm"])
        elif kind == HERO:
            self._paint_hero(p, payload, rect, lines, hovered, focused, dpr)
        elif kind in (ROW, FINISHED) and not is_open:
            local = QRect(0, 0, body.width(), body.height())
            pix = self._sprite(kind, payload, lines, body.size(), dpr, hovered,
                               lambda q: self._paint_row(q, kind, payload, local, hovered, False, dpr, lines))
            p.drawPixmap(body.topLeft(), pix)
            if focused:
                self._focus_ring(p, body, theme.RADII["r-sm"])
                if kind == ROW and not hovered:
                    cols = self.columns(QRect(body.left(), body.top(), body.width(),
                                              round(theme.SIZES["row"] * fz())), kind)
                    self._paint_play_button(p, self._play_rect(cols["acts"]), payload.can_play)
        elif kind in (ROW, FINISHED):
            self._paint_row(p, kind, payload, body, hovered, focused, dpr, lines)
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

    def _paint_line(self, p, ln, strip, dpr):
        col = style.colours()
        y = strip.center().y() + 0.5
        if ln.kind == "top":
            pen = QPen(style.qcolor(col["top20-line"]), 1)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 3])
            p.setPen(pen)
            p.drawLine(QPointF(strip.left() + 4, y), QPointF(strip.right() - 4, y))
        else:
            w, _ = TEXT.draw(p, strip.left() + 8, strip.center().y(), strings.ROWS_SOON_LABEL, "group-label",
                             120, c("ink-faint"), dpr=dpr)
            p.setPen(QPen(style.qcolor(col["line-hi"]), 1))
            p.drawLine(QPointF(strip.left() + 8 + w + 10, y), QPointF(strip.right() - 4, y))

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

    def _paint_row(self, p, kind, row, body, hovered, focused, dpr, lines=()):
        f = fz()
        h = round(theme.SIZES["row"] * f)
        line = QRect(body.left(), body.top(), body.width(), h)
        radius = theme.RADII["r-sm"]
        is_open = kind == ROW and self.view.model().open_key == row.key
        if hovered or is_open:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("surface"))
            p.drawRoundedRect(QRectF(body), radius, radius)
        if focused:
            self._focus_ring(p, body, radius)
        x = line.left() + 4
        pos_w = round(20 * f)
        if kind == ROW:
            TEXT.draw(p, x, line.center().y(), str(row.index), "position", pos_w, c("ink-faint"), align="right",
                      dpr=dpr)
        x += pos_w + 12
        cw, ch = round(theme.SIZES["row-cover-w"] * f), round(theme.SIZES["row-cover-h"] * f)
        crect = QRect(x, line.center().y() - ch // 2, cw, ch)
        self._paint_cover(p, row.cover_title, crect, dpr)
        if kind == ROW:
            self._paint_watched_bar(p, row, crect)
        x = crect.right() + 13
        cols = self.columns(line, kind)
        text_w = cols["text_right"] - x
        t_h = round(13.5 * f * 1.3)
        s_h = round(12 * f * 1.3)
        top = line.center().y() - (t_h + 1 + s_h) / 2
        TEXT.draw(p, x, top + t_h / 2, row.title, "row-title", text_w, c("ink"), dpr=dpr)
        sx = x
        if row.studying:
            sw = self._paint_studying(p, sx, top + t_h + 1 + s_h / 2, dpr)
            sx += sw + 6
        TEXT.draw(p, sx, top + t_h + 1 + s_h / 2, row.line, "row-sub", cols["text_right"] - sx, c("ink-dim"), dpr=dpr)
        if kind == ROW:
            paint_diff(p, row.pct, row.pct_tone, row.n_new, cols["diff"].right(), line.center().y(), dpr)
        else:
            TEXT.draw(p, cols["date"].left(), line.center().y(), row.date, "date", cols["date"].width(),
                      c("ink-faint"), dpr=dpr)
        st_rect, mk_rect = self._status_rects(row, cols["stat"])
        if kind == FINISHED and row.status is not None and row.status.kind not in ("in_anki", "mining"):
            st_rect = None                                  # Finished shows only Mining… / ✓ N in Anki
        if st_rect is not None:
            paint_pill(p, row.status, st_rect, dpr)
        if mk_rect is not None and kind == ROW:
            paint_mark(p, row.mark, mk_rect.right() + 1, line.center().y(), dpr)
        if kind == ROW and (hovered or focused):
            self._paint_play_button(p, self._play_rect(cols["acts"]), row.can_play)
        if is_open:
            area = QRect(body.left(), line.bottom() + 1, body.width(), body.bottom() - line.bottom())
            self._paint_episodes(p, row, area, dpr, lines=lines)

    def _paint_studying(self, p, x, y_mid, dpr):
        f = fz()
        text = strings.ROWS_STUDYING
        fm = TEXT.metrics("badge", dpr=dpr)
        w = fm.horizontalAdvance(text) + round(16 * f)
        h = round(19 * f)
        r = QRectF(x, y_mid - h / 2, w, h)
        p.setPen(QPen(c("study-first-ring"), 1))
        p.setBrush(c("badge-new"))
        p.drawRoundedRect(r, h / 2, h / 2)
        TEXT.draw(p, x + 8 * f, y_mid, text, "badge", w, c("accent"), dpr=dpr)
        return w

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
                pix = self._sprite("ep", ep, (), r.size(), dpr, False,
                                   lambda q, ep=ep, w=w, h=h: self._paint_episode(q, QRect(0, 0, w, h), ep, dpr),
                                   ident=(ep.id, hero), ground="surface")
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

    def _paint_hero(self, p, row, rect, lines, hovered, focused, dpr):
        f = fz()
        g = self._hero_geometry(row, rect, lines)
        box = QRectF(g["box"]).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.RADII["r-sm"]
        path = QPainterPath()
        path.addRoundedRect(box, radius, radius)
        p.fillPath(path, c("surface"))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(box.left(), box.top(), 3, box.height()), self._iris(QRectF(box.left(), box.top(), 3,
                                                                                   box.height()), vertical=True))
        p.restore()
        p.setPen(QPen(c("line-hi" if hovered else "line"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if focused:
            self._focus_ring(p, g["box"], radius)
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
        if self.view.model().open_key == row.key:
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
        tw = TEXT.metrics("chip", dpr=dpr).horizontalAdvance(chip.text)
        extra = 8 if chip.mined else 0
        x = r.center().x() - (tw + extra) / 2
        TEXT.draw(p, x, r.center().y(), chip.text, "chip", tw + 2, ink, dpr=dpr)
        if chip.mined:
            icon(p, "dot", QRectF(x + tw + 2, r.center().y() - 3, 6, 6), c("ok"))

    def _paint_watch(self, p, r, row, nxt, dpr):
        f = fz()
        rr = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        word = row.media_word
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
            if row.media == "youtube":
                label = strings.ROWS_ONLINE_BUTTON
            else:
                label = strings.ROWS_NO_MEDIA_BUTTON.format(word=word)
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
        y += th + 4
        lh = 12.5 * f * 1.45
        TEXT.draw(p, x, y + lh / 2, need.line, "hero-sub", w, c("ink-dim"), dpr=dpr)
        y += lh + 10
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
            lw, _ = TEXT.draw(p, listbox.left() + 10, ry + rows_h / 2, label, "hero-sub", 120 * f, c("ink"), weight=600,
                              dpr=dpr)
            TEXT.draw(p, listbox.left() + 10 + lw + 12, ry + rows_h / 2, what, "hero-sub", listbox.width() - lw - 40,
                      c("ink-faint"), dpr=dpr)

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
        # an opaque ground (filled by Qt, the theme's `bg`): a scroll then moves the pixels already drawn and paints
        # only the strip that came into view (a see-through viewport is repainted whole on every scroll step). Not
        # WA_OpaquePaintEvent: the gaps between rows and the space under the last are Qt's to fill.
        self.viewport().setAutoFillBackground(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSpacing(0)
        self.setLayoutMode(LAYOUT_MODE)
        if LAYOUT_MODE == QListView.LayoutMode.Batched:
            self.setBatchSize(LAYOUT_BATCH)
        self.verticalScrollBar().setSingleStep(round(theme.SIZES["row"] * fz() / 2))
        self._hover = None
        self._restore = None
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)

    # entries ---------------------------------------------------------------------------------------------------- #
    def set_entries(self, entries):
        """Show these entries; a reset keeps the row that was at the top where it was."""
        model = self.model()
        anchor = self._anchor()
        how = model.set_entries(entries)
        if how == "same":
            if len(model.changed) > 40:
                self.viewport().update()
            else:
                for i in model.changed:                  # only the rows that changed (dirty rows, never all)
                    self.update(model.index(i, 0))
        elif how == "relayout":
            self.relayout()
            self.viewport().update()
        else:
            self._hover = None
            if anchor is not None and self.isVisible():
                self._restore = anchor
                self._apply_restore()
                self._restore = None                     # tried once: a place gone stays gone (W2.2 review A-15)
        return how

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
        if self.tooltips is not None:
            self.tooltips.hide_part_unless(self.viewport(), event.pos())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None and self._hover < self.model().rowCount():
            self.update(self.model().index(self._hover, 0))
        self._hover = None
        super().leaveEvent(event)

    def mousePressEvent(self, event):
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
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            idx = self.currentIndex()
            if idx.isValid():
                self.toggle(idx)
                event.accept()
                return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)


# The list's layout mode (P-layout, W2.2 row 0, this desktop, 20,000 rows): one pass. Qt 6.11's batched mode was worse
# on every count — its batches ran in one stretch of the event loop (1,494 ms to lay 20,000 out, 120 ms for an insert,
# 258 ms for a reset, against one pass's 83 / 73 ms) and an insert lost the scroll place. One pass costs ~4 µs a row
# (the delegate's sizeHint): within the 4 ms step up to ~1,000 rows in one list; past that, a relayout (a row opened,
# the rows changed) is a long step — W3.1's (*As built*).
LAYOUT_MODE = QListView.LayoutMode.SinglePass
LAYOUT_BATCH = 100
