"""Hover-W: the word card over a Current row's *N new* (app/services/title_words.py says what; this paints it). Sonic's
yes to the look, 2026-11-14 ("It's good for hover"); the mock and its PROVISIONAL leans: TheForge
tracks/window/reviews/hover-w-mock-2026-11-14.html, hover-w-register.md.

- **The hover** (the bubble's timing): the head (the title, *N new when you get here · M today*, a thin bar) and *New
  here* as a grid three across and four down (twelve words, the list's order across each row, each column as wide as
  its widest word — two columns when three won't fit, never a cut word), then *In Anki, not mature yet* and *Learned on
  the way* one line each, as many words as fit, then *+N more*. The card is as wide as its grid.
- **A click** (on *N new* or on the card) keeps it open and expands it: every part whole, scrolling inside, ✕ and
  *Open in the journey ↗*. *+N more* opens the card that way with its part brought to the top and washed.
  Esc, Back and a click away close it (`EscapeRouter`, `_Away`).
- **A word's sentence** (kept open, Sonic 2026-11-14): hovering or clicking a word shows its first sentence in this
  title on one line under the words, the word in the accent, and the part it is from; a click keeps it there. A word
  with none shows nothing.
- **Waiting to update**: while the rows' figures are faded (the last plan's), a band in the head says so.
- **Known / Ignore** (Kotoba-K, the lead's draft for Sonic; leans PROVISIONAL): kept open, a new word's hover shows a
  small ✓ and ⊘ under it (a word's own click stays its sentence, Hover-W); a click marks it (`word_marks`: Known — you
  know it; Ignore — not a word to learn), a second click on the lit one clears it. A marked word stays in place,
  dimmed, with its mark after it, until the card closes; the counts follow as the numbers do (no Generate first).
  *I know all of these* in the foot marks the title's every *New here* word known, then reads *Undo* for that one batch.

Built once per window (`R5`: an open sets words, makes no widget); every colour a theme token; nothing decided here.
"""
from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QApplication, QPushButton, QScrollArea, QToolButton, QWidget

from app import theme
from app.qt import motion, press, shadow, strings, style, tooltip
from app.qt.rows import TEXT, c, faded, fz

GRID_COLS, GRID_ROWS = 3, 4                    # the hover's New here: three across, four down (lean 2)
HOVER_W = (270, 390)                           # the hover's width range (× text size); kept open: the widest
KEPT_MAX_H = 430                               # the kept card's words scroll past this (× text size)
PAD_X, PAD_Y = 14, 11
WORD_ROLE, HEAD_ROLE = "episode-label", "eyebrow"
GRACE_MS = 220                                 # the pointer may cross from *N new* to the card (or back) this long
FADED = 0.6                                    # Waiting to update: the numbers and words dim, still readable
MARKED_INK = 0.38                              # a word marked Known / Ignore: dimmed, still readable, its mark after it
MARK_CELL = 21                                 # the ✓ / ⊘ pair under a hovered word: each cell's side (× text size)
MARKS = ("known", "ignore")


class _Item:
    """One painted thing on the words' sheet: its rect, text, role, ink, weight; `word` (a CardWord / AnkiWord: its
    sentence on hover) or `more` (the part its *+N more* opens)."""
    __slots__ = ("rect", "text", "role", "ink", "weight", "word", "more", "y_mid")

    def __init__(self, rect, text, role, ink, weight=None, word=None, more=None):
        self.rect, self.text, self.role, self.ink, self.weight, self.word, self.more = \
            rect, text, role, ink, weight, word, more
        self.y_mid = rect.center().y()


def _adv(text, role, weight=None):
    return TEXT.metrics(role, weight).horizontalAdvance(text)


def _line_h(role):
    return round(TEXT.metrics(role).height() * 1.45)


def grid_columns(labels, cols, gap):
    """Each column's width (the widest word in it), words placed across each row: [w, …]."""
    widths = [0] * cols
    for i, label in enumerate(labels):
        widths[i % cols] = max(widths[i % cols], _adv(label, WORD_ROLE))
    return widths


class _Sheet(QWidget):
    """The card's parts, painted from `items` (the card lays them out); the words' hover and clicks go to the card."""

    def __init__(self, card):
        super().__init__()
        self.card = card
        self.items = []
        self.bands = []                        # (y, h) of each part's top rule
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def paintEvent(self, _event):
        p = QPainter(self)
        stale = self.card.card is not None and self.card.card.kept
        rule = c("line-hi")
        for y in self.bands:
            p.fillRect(QRect(0, y, self.width(), 1), rule)
        marked = self.card.marked
        for it in self.items:
            ink = it.ink
            if stale and it.word is not None:
                ink = faded_q(ink, FADED)
            mark = marked.get(getattr(it.word, "word", None)) if it.word is not None and markable(it.word) else None
            if mark is not None:
                ink = faded_q(ink, MARKED_INK)
            TEXT.draw(p, it.rect.left(), it.y_mid, it.text, it.role, it.rect.width() + 2, ink, weight=it.weight,
                      elide=False)
            if mark is not None:
                glyph = strings.WORDS_MARK_GLYPH[mark]
                TEXT.draw(p, it.rect.right() + round(3 * fz()), it.y_mid, glyph, "badge",
                          _adv(glyph, "badge") + 2, c("accent") if mark == "known" else c("overlay-ink-dim"),
                          elide=False)
            if it.more is not None and it is self.card.hot_more:
                p.fillRect(QRect(it.rect.left(), it.rect.bottom() - 1, it.rect.width(), 1), c("accent"))
        self.card.paint_pair(p)
        p.end()

    def item_at(self, pos):
        pair = self.card.pair_at(pos)
        if pair is not None:
            return pair
        for it in self.items:
            if (it.word is not None or it.more is not None) and it.rect.adjusted(-3, -2, 3, 2).contains(pos):
                return it
        return None

    def mouseMoveEvent(self, event):
        self.card.hovered(self.item_at(event.position().toPoint()))

    def leaveEvent(self, event):
        self.card.hovered(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        event.accept()                         # (its release comes here: a word, a +N more)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.card.clicked(self.item_at(event.position().toPoint()))
        event.accept()


def faded_q(q, alpha):
    out = type(q)(q)
    out.setAlphaF(q.alphaF() * alpha)
    return out


def markable(word):
    """A word the card can mark: a list word of New here or Learned on the way (`title_words.CardWord`), never one of
    Anki's (its card says what it is)."""
    return hasattr(word, "label") and hasattr(word, "reading")


class _Pair:
    """The ✓ / ⊘ cell under the pointer: what `_Sheet.item_at` answers on it (the word it marks, which mark)."""
    __slots__ = ("item", "mark", "rect", "word", "more")

    def __init__(self, item, mark, rect):
        self.item, self.mark, self.rect, self.word, self.more = item, mark, rect, item.word, None


class _Away(QObject):
    """A press outside the kept card closes it, as Esc does; the press goes on to what it was on."""

    def __init__(self, card):
        super().__init__(card)
        self.card = card

    def eventFilter(self, _obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.card.isVisible() and self.card.kept:
            at = event.globalPosition().toPoint()
            if not QRect(self.card.mapToGlobal(QPoint(0, 0)), self.card.size()).contains(at):
                self.card.close()
        return False


class WordPeek(motion.Overlay):
    """The card (one per window). The host (`PeekHost`) shows it for a row and hands it the words as they come."""
    how = "pop"
    shadow_name = "menu"
    journey_asked = pyqtSignal(object)         # the card's `episode`: *Open in the journey ↗*
    mark_asked = pyqtSignal(object)            # Kotoba-K: [(word, mark, before)] — a ✓ / ⊘ click (None: cleared)
    sentences_wanted = pyqtSignal(object)      # the kept card's key: its words' sentences, once
    pointer_in = pyqtSignal(bool)              # (hover) the pointer came onto the card / left it

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("wordpeek")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAccessibleName(strings.WORDS_NAME)
        self.card = None                       # title_words.Card
        self.row = None                        # the row (or episode) asked for: its title before the words come
        self.kept = False
        self.sentences = None                  # {(word, reading): Sentence}: what the kept card shows ({}: none)
        self._sentences_key = None             # the card whose sentences were asked (once a card)
        self.hot_word = self.picked_word = None
        self.hot_more = None
        self.marked = {}                       # Kotoba-K: {word: "known" | "ignore"} marked on this card while open
        self.hot_item = None                   # the kept card's hovered markable word (its ✓ / ⊘ under it)
        self.hot_pair = None                   # ... and the cell under the pointer
        self.anchor = QRect()
        self.head_h = 0
        self.sheet = _Sheet(self)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("wordpeekscroll")
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(False)
        self.scroll.setWidget(self.sheet)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.sheet.setAutoFillBackground(False)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("wordpeekclose")
        self.close_button.setText(strings.WORDS_CLOSE)
        self.close_button.setToolTip(strings.WORDS_CLOSE_TIP)
        self.close_button.setAccessibleName(strings.WORDS_CLOSE_TIP)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(lambda _c=False: self.close())
        self.journey = QPushButton(strings.WORDS_JOURNEY, self)
        self.journey.setObjectName("wordpeekjourney")
        self.journey.setToolTip(strings.WORDS_JOURNEY_TIP)
        self.journey.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.journey.clicked.connect(lambda _c=False: self.journey_asked.emit(self.card.episode if self.card else None))
        self.all_known = press.room(QPushButton(strings.WORDS_ALL_KNOWN, self))   # Kotoba-K: the host connects it
        self.all_known.setObjectName("wordpeekallknown")
        self.all_known.setToolTip(strings.WORDS_ALL_KNOWN_TIP)
        self.all_known.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.all_known.hide()
        self.all_done = None                   # the words *I know all of these* marked (its Undo shows), or None
        self.marks = []
        for i in range(3):
            mark = tooltip.AboutMark(strings.WORDS_HELP_MARK, self.sheet)
            mark.set_about(strings.WORDS_PARTS[i], strings.WORDS_HELP[i])
            mark.setVisible(False)
            self.marks.append(mark)
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        self.lays = 0                          # (tests) how many times the card was laid out
        self.hide()

    # --- what the host asks ----------------------------------------------------------------------------------- #
    def show_for(self, row, anchor, card=None, kept=False):
        """Show the card for `row` under `anchor` (a QRect in the parent's coordinates): its words now (`card`) or as
        they come (`set_card`). `kept`: open and expanded at once (a click)."""
        same = self.row is not None and getattr(self.row, "key", None) == getattr(row, "key", None)
        self.row, self.anchor = row, QRect(anchor)
        if not same:
            self.sentences, self.hot_word, self.picked_word, self.hot_more = None, None, None, None
            self._sentences_key = None
            self.card = None
            self.marked, self.all_done = {}, None
        if card is not None:
            self.card = card
        self.kept = bool(kept) or (same and self.kept and self.isVisible())
        self._relayout()
        if not self.isVisible():
            self.open()
        self._sync_kept()

    def set_card(self, card):
        if card is None or self.row is None or card.key != getattr(self.row, "key", None):
            return
        if self.marked and self.card is not None and self.card.key == card.key:
            from app.services.title_words import keep_marked
            card = keep_marked(self.card, card, self.marked)    # a marked word stays in place while the card is open
        self.card = card
        self._relayout()
        self._sync_kept()

    def keep(self, part=None):
        """Kept open and expanded (a click); `part` (0 New here, 1 In Anki, 2 Learned on the way): brought to the top
        of the card and washed — what its *+N more* opens."""
        self.kept = True
        self._relayout()
        self._sync_kept()
        if part is not None:
            y = self._part_top.get(part)
            if y is not None:
                self.scroll.verticalScrollBar().setValue(y)
                band = QWidget(self.sheet)
                band.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                band.setGeometry(0, y, self.sheet.width(), self._part_h.get(part, 0))
                band.show()
                motion.wash(band, radius=round(6 * fz()))
                QTimer.singleShot(theme.SETTINGS_MOTION["row-wash"] + 400, band.deleteLater)

    def set_sentences(self, key, found):
        if self.card is None or key != self.card.key:
            return
        self.sentences = found or {}
        self._relayout()

    def closeEvent(self, event):
        self._forget()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._forget()
        super().hideEvent(event)

    def _forget(self):
        self.kept = False
        self.hot_word = self.picked_word = self.hot_more = None
        self.hot_item = self.hot_pair = None
        self.marked, self.all_done = {}, None   # (the next open reads the words as they are: marked ones gone)
        QApplication.instance().removeEventFilter(self._away)

    def _sync_kept(self):
        app = QApplication.instance()
        if self.kept:
            app.installEventFilter(self._away)
            if self.card is not None and self._sentences_key != self.card.key:
                self._sentences_key = self.card.key
                self.sentences_wanted.emit(self.card.key)
        else:
            app.removeEventFilter(self._away)

    # --- the pointer on the card ------------------------------------------------------------------------------ #
    def enterEvent(self, event):
        self.pointer_in.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.pointer_in.emit(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        event.accept()                         # a press on the card is the card's (never the rows' under it)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.kept:
            self.keep()
        event.accept()

    def hovered(self, item):
        word = item.word if item is not None and self.kept else None
        more = item if item is not None and item.more is not None else None
        pair = item if isinstance(item, _Pair) else None
        hot_item = pair.item if pair is not None else (item if self.kept and item is not None and item.word is not None
                                                          and markable(item.word) else None)
        if hot_item is not self.hot_item or pair is not self.hot_pair:
            for old in (self.hot_item, hot_item):
                if old is not None:
                    self.sheet.update(self._pair_rect(old).adjusted(-2, -2, 2, 2))
            self.hot_item, self.hot_pair = hot_item, pair
            self.sheet.setCursor(Qt.CursorShape.PointingHandCursor if pair is not None
                                 else Qt.CursorShape.ArrowCursor)
            tips = getattr(self, "tooltips", None)
            if tips is not None:
                if pair is not None:
                    tips.request(self.sheet, pair.rect, strings.WORDS_MARK_TIP[pair.mark])
                else:
                    tips.hide_part_unless(self.sheet, QPoint(-1, -1))
        changed = False
        if more is not self.hot_more:
            self.hot_more = more
            self.sheet.setCursor(Qt.CursorShape.PointingHandCursor if more is not None else Qt.CursorShape.ArrowCursor)
            self.sheet.update()
        if word is not self.hot_word:
            self.hot_word = word
            changed = True
        if changed and self.sentences:
            self.update(self._sentence_rect())

    def clicked(self, item):
        if isinstance(item, _Pair):
            word = item.word.word
            before = self.marked.get(word)
            mark = None if before == item.mark else item.mark                    # the lit side again: cleared
            self.set_marks({word: mark})
            self.mark_asked.emit([(word, mark, before)])
            return
        if item is not None and item.more is not None:
            self.keep(item.more)
        elif not self.kept:
            self.keep()
        elif item is not None and item.word is not None:
            self.picked_word = None if self.picked_word is item.word else item.word
            if self.sentences:
                self.update(self._sentence_rect())

    # --- Known / Ignore (Kotoba-K) ------------------------------------------------------------------------------ #
    def set_marks(self, marks):
        """{word: mark or None} painted at once (a press reacts in its own frame; the write follows)."""
        for word, mark in marks.items():
            if mark is None:
                self.marked.pop(word, None)
            else:
                self.marked[word] = mark
        self.sheet.update()

    def _pair_rect(self, item):
        """The ✓ / ⊘ pair's rect under `item` (the sheet's coordinates), kept inside the sheet."""
        f = fz()
        side = round(MARK_CELL * f)
        x = max(0, min(item.rect.left(), self.sheet.width() - 2 * side - 1))
        return QRect(x, item.rect.bottom() - round(2 * f), 2 * side + 1, side)

    def pair_at(self, pos):
        item = self.hot_item
        if item is None or not self.kept:
            return None
        r = self._pair_rect(item)
        if not r.contains(pos):
            return None
        half = r.width() // 2
        known = QRect(r.left(), r.top(), half, r.height())
        if known.contains(pos):
            return _Pair(item, "known", known)
        return _Pair(item, "ignore", QRect(r.left() + half + 1, r.top(), r.width() - half - 1, r.height()))

    def paint_pair(self, p):
        """The hovered word's ✓ / ⊘, drawn over the words under it (the card's raised fill, a hairline)."""
        item = self.hot_item
        if item is None or not self.kept:
            return
        r = self._pair_rect(item)
        lit = self.marked.get(item.word.word)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(c("line-hi"), 1))
        p.setBrush(c("raised"))
        radius = theme.RADII["r-sm"]
        p.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        half = r.width() // 2
        for i, mark in enumerate(MARKS):
            cell = QRect(r.left() + (half + 1) * i, r.top(), half if i == 0 else r.width() - half - 1, r.height())
            on = lit == mark
            hot = self.hot_pair is not None and self.hot_pair.mark == mark
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c("accent-deep") if mark == "known" else c("line-hi"))
                p.drawRoundedRect(QRectF(cell).adjusted(2, 2, -2, -2), radius, radius)
            ink = c("ink") if (on or hot) else c("overlay-ink-dim")
            glyph = strings.WORDS_MARK_GLYPH[mark]
            TEXT.draw(p, cell.center().x() - _adv(glyph, "row-sub") / 2, cell.center().y(), glyph, "row-sub",
                      cell.width(), ink, elide=False)
        p.fillRect(QRect(r.left() + half, r.top() + 3, 1, r.height() - 6), c("line-hi"))

    def set_all_done(self, words):
        """*I know all of these* landed (`words`: what it marked) — its button reads Undo — or (None) undone."""
        self.all_done = list(words) if words else None
        self.all_known.setText(strings.WORDS_ALL_UNDO.format(n=len(self.all_done)) if self.all_done
                               else strings.WORDS_ALL_KNOWN)
        self.all_known.setToolTip(strings.WORDS_ALL_UNDO_TIP if self.all_done else strings.WORDS_ALL_KNOWN_TIP)
        self._relayout()

    # --- layout ------------------------------------------------------------------------------------------------ #
    def _relayout(self):
        self.lays += 1
        f = fz()
        card = self.card
        px, py = round(PAD_X * f), round(PAD_Y * f)
        max_w = round(HOVER_W[1] * f)
        inner_max = max_w - 2 * px
        items, bands = [], []
        self._part_top, self._part_h, self._mark_at = {}, {}, {}
        y = 0
        word_h = _line_h(WORD_ROLE)
        head_role_h = _line_h(HEAD_ROLE)
        gap = round(20 * f)
        cols, rows = GRID_COLS, GRID_ROWS
        grid_w = 0
        if card is not None:
            shown_new = list(card.new) if self.kept else list(card.new[:cols * rows])
            widths = grid_columns([w.label for w in shown_new], cols, gap)
            if sum(widths) + gap * (cols - 1) > inner_max:
                cols = 2
                if not self.kept:
                    shown_new = list(card.new[:cols * rows])
                widths = grid_columns([w.label for w in shown_new], cols, gap)
            grid_w = sum(widths) + gap * (cols - 1)
        inner = inner_max if self.kept else max(round(HOVER_W[0] * f) - 2 * px, min(inner_max, grid_w))
        if card is not None:
            # 1 · New here
            y = self._part_head(items, bands, y, 0, strings.WORDS_PARTS[0], card.n_new, head_role_h, f)
            if not card.new:
                items.append(_Item(QRect(0, y, inner, word_h), strings.WORDS_NOTHING_HERE, "row-sub", c("ink-dim")))
                y += word_h
            else:
                x_at = [sum(widths[:i]) + gap * i for i in range(cols)]
                for i, w in enumerate(shown_new):
                    r, col = divmod(i, cols)
                    items.append(_Item(QRect(x_at[col], y + r * word_h, widths[col], word_h), w.label, WORD_ROLE,
                                       c("ink"), word=w))
                y += -(-len(shown_new) // cols) * word_h
                rest = len(card.new) - len(shown_new)
                if rest > 0:
                    text = strings.WORDS_MORE.format(n=rest)
                    items.append(_Item(QRect(0, y, _adv(text, "row-sub"), word_h), text, "row-sub", c("accent"),
                                       more=0))
                    y += word_h
            self._part_h[0] = y - self._part_top[0]
            # 2 · In Anki, not mature yet
            if card.anki is not None and card.anki != ():
                y = self._anki(items, bands, y, card, inner, word_h, head_role_h, f)
            # 3 · Learned on the way
            if card.before:
                y = self._before(items, bands, y, card, inner, word_h, head_role_h, f)
        self.sheet.items, self.sheet.bands = items, bands
        sheet_h = y + round(4 * f) + (round(MARK_CELL * f) if self.kept else 0)   # (room for the last row's ✓ / ⊘)
        width = inner + 2 * px
        self.head_h = self._head_height(f)
        foot_h = round(_line_h("row-sub") + 8 * f) if not self.kept else round(theme.SIZES["button-sm"] * f + 12 * f)
        sent_h = (_line_h("row-sub") + round(8 * f)) if (self.kept and self.sentences) else 0
        body_h = sheet_h if not self.kept else min(sheet_h, round(KEPT_MAX_H * f) - self.head_h)
        parent = self.parentWidget()
        if parent is not None:
            room = parent.height() - 2 * round(8 * f) - self.head_h - foot_h - sent_h - 2 * py
            body_h = max(word_h * 2, min(body_h, room))
        self.sheet.resize(inner, sheet_h)
        self.scroll.setGeometry(px, py + self.head_h, inner + (round(10 * f) if self.kept else 0), body_h)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if self.kept
                                               else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._marks()
        h = py + self.head_h + body_h + sent_h + foot_h + round(4 * f)
        self.resize(width + (round(10 * f) if self.kept else 0), h)
        self._sent_y = py + self.head_h + body_h + round(4 * f)
        self._foot_y = self._sent_y + sent_h
        bs = round(theme.SIZES["icon-button"] * f * 0.8)
        self.close_button.setGeometry(self.width() - px - bs + round(4 * f), py - round(3 * f), bs, bs)
        self.close_button.setVisible(self.kept)
        self.journey.setVisible(self.kept and self.card is not None and self.card.episode is not None)
        if self.journey.isVisible():
            self.journey.adjustSize()
            self.journey.move(px, self._foot_y + round(4 * f))
        self.all_known.setVisible(self.kept and self.card is not None and (bool(self.card.new) or bool(self.all_done)))
        if self.all_known.isVisible():
            self.all_known.adjustSize()
            self.all_known.move(self.width() - px - self.all_known.width(), self._foot_y + round(4 * f))
        if self.hot_item is not None and self.hot_item not in items:   # (a relayout made new items)
            self.hot_item = self.hot_pair = None
        self._place()
        self.sheet.update()
        self.update()

    def _part_head(self, items, bands, y, i, name, count, head_h, f):
        if y > 0:
            bands.append(y + round(3 * f))
            y += round(9 * f)
        self._part_top[i] = max(0, y - round(6 * f))
        text = name.upper()
        w = _adv(text, HEAD_ROLE)
        items.append(_Item(QRect(0, y, w, head_h), text, HEAD_ROLE, c("overlay-ink-dim")))
        x = w + round(6 * f)
        if count is not None:
            n = f"{count:,}"
            nw = _adv(n, HEAD_ROLE)
            items.append(_Item(QRect(x, y, nw, head_h), n, HEAD_ROLE, c("ink")))
            x += nw + round(6 * f)
        self._mark_at[i] = QPoint(x, y + head_h // 2)
        return y + head_h

    def _marks(self):
        side = round(15 * fz())
        at = getattr(self, "_mark_at", {})
        for i, mark in enumerate(self.marks):
            p = at.get(i)
            mark.setVisible(p is not None)
            if p is not None:
                mark.setGeometry(p.x(), p.y() - side // 2, side, side)

    def _flow(self, items, y, entries, inner, word_h, one_line, total, part):
        """Words left to right, wrapped (`one_line`: as many as fit, then *+N more* for the rest of `total`)."""
        f = fz()
        gap = round(11 * f)
        x = 0
        placed = 0
        for text, ink, word, extra in entries:
            w = _adv(text, WORD_ROLE) + (_adv(extra[0], extra[1]) + round(3 * f) if extra else 0)
            if one_line:
                left = total - placed - 1
                more_w = _adv(strings.WORDS_MORE.format(n=left), "row-sub") + gap if left > 0 else 0
                if x + w + more_w > inner and placed:
                    break
            elif x + w > inner and x > 0:
                x, y = 0, y + word_h
            items.append(_Item(QRect(x, y, _adv(text, WORD_ROLE), word_h), text, WORD_ROLE, ink, word=word))
            if extra:
                ex = x + _adv(text, WORD_ROLE) + round(3 * f)
                items.append(_Item(QRect(ex, y, _adv(extra[0], extra[1]), word_h), extra[0], extra[1],
                                   c("overlay-ink-dim")))
            x += w + gap
            placed += 1
        if one_line and total - placed > 0:
            text = strings.WORDS_MORE.format(n=total - placed)
            items.append(_Item(QRect(x, y, _adv(text, "row-sub"), word_h), text, "row-sub", c("accent"), more=part))
        return y + word_h

    def _anki(self, items, bands, y, card, inner, word_h, head_h, f):
        y = self._part_head(items, bands, y, 1, strings.WORDS_PARTS[1], None if card.anki == "closed" else
                            len(card.anki), head_h, f)
        if card.anki == "closed":
            items.append(_Item(QRect(0, y, inner, word_h), strings.WORDS_ANKI_CLOSED, "row-sub", c("ink-dim")))
            y += word_h
        else:
            def entry(a):
                if a.leech:
                    extra = (strings.WORDS_LEECH, "badge")
                elif a.lapses:
                    extra = (strings.WORDS_FORGOT.format(n=a.lapses), "badge")
                else:
                    extra = None
                return (a.word, c("ink"), a, extra)
            struggling = [a for a in card.anki if a.leech or a.lapses]
            young = [a for a in card.anki if not (a.leech or a.lapses)]
            if not self.kept:
                y = self._flow(items, y, [entry(a) for a in struggling + young], inner, word_h, True, len(card.anki), 1)
            else:
                for label, group in ((strings.WORDS_STRUGGLING, struggling), (strings.WORDS_YOUNG, young)):
                    if group:
                        sub_h = _line_h("subline")
                        items.append(_Item(QRect(0, y, inner, sub_h), label, "subline", c("overlay-ink-dim")))
                        y = self._flow(items, y + sub_h, [entry(a) for a in group], inner, word_h, False, len(group), 1)
        self._part_h[1] = y - self._part_top[1]
        return y

    def _before(self, items, bands, y, card, inner, word_h, head_h, f):
        total = sum(len(g.words) for g in card.before)
        y = self._part_head(items, bands, y, 2, strings.WORDS_PARTS[2], total, head_h, f)
        if not self.kept:
            flat = [(w.label, c("ink"), w, None) for g in card.before for w in g.words]
            y = self._flow(items, y, flat, inner, word_h, True, total, 2)
        else:
            sub_h = _line_h("subline")
            for g in card.before:
                text = strings.WORDS_GROUP.format(title=g.title, n=len(g.words))
                items.append(_Item(QRect(0, y + round(2 * f), inner, sub_h), text, "subline", c("overlay-ink-dim")))
                y = self._flow(items, y + sub_h + round(2 * f), [(w.label, c("ink"), w, None) for w in g.words],
                               inner, word_h, False, len(g.words), 2)
        self._part_h[2] = y - self._part_top[2]
        return y

    def _head_height(self, f):
        h = _line_h("row-title") + round(4 * f)
        if self.card is not None and self.card.kept:
            h += _line_h("row-sub") + round(12 * f)
        h += _line_h("arrival-number") + round(12 * f)
        return h

    def _place(self):
        """Under the anchor, its right edge on the figure; above it when there's no room below; inside the window."""
        parent = self.parentWidget()
        if parent is None:
            return
        f = fz()
        m = round(8 * f)
        x = self.anchor.right() - self.width() + round(4 * f)
        y = self.anchor.bottom() + round(6 * f)
        if y + self.height() > parent.height() - m and self.anchor.top() - self.height() - round(6 * f) >= m:
            y = self.anchor.top() - self.height() - round(6 * f)
        x = max(m, min(x, parent.width() - self.width() - m))
        y = max(m, min(y, parent.height() - self.height() - m))
        self.move(x, y)

    def _sentence_rect(self):
        f = fz()
        return QRect(round(PAD_X * f), self._sent_y, self.width() - 2 * round(PAD_X * f), _line_h("row-sub"))

    # --- painting ---------------------------------------------------------------------------------------------- #
    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["r"])
        f = fz()
        px, py = round(PAD_X * f), round(PAD_Y * f)
        width = self.width() - 2 * px
        card, row = self.card, self.row
        title = card.title if card is not None else getattr(row, "title", "")
        y = py
        th = _line_h("row-title")
        tw, _el = TEXT.draw(p, px, y + th / 2, title, "row-title", width - (round(30 * f) if self.kept else 0),
                            c("ink"))
        if card is not None and card.tier:
            scope = strings.WORDS_SCOPE.format(tier=card.tier, n=card.n_files) if card.n_files > 1 else card.tier
            TEXT.draw(p, px + tw + round(8 * f), y + th / 2, scope, "row-sub",
                      max(0, width - tw - round(8 * f) - (round(30 * f) if self.kept else 0)), c("overlay-ink-dim"))
        y += th + round(4 * f)
        if card is not None and card.kept:                     # Waiting to update: plain, in the head
            bh = _line_h("row-sub") + round(8 * f)
            band = QRect(px, y, width, bh)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(c("line-hi"), 1))
            p.setBrush(c("raised"))
            p.drawRoundedRect(QRectF(band).adjusted(0.5, 0.5, -0.5, -0.5), theme.RADII["r-sm"], theme.RADII["r-sm"])
            arc = QRectF(band.left() + round(9 * f), band.center().y() - 5 * f, 10 * f, 10 * f)
            p.setPen(QPen(c("accent"), max(1.5, 2 * f)))
            p.drawArc(arc, 45 * 16, 270 * 16)                    # a still arc: a wait that clears by itself
            x = arc.right() + round(7 * f)
            w1, _e = TEXT.draw(p, x, band.center().y(), strings.WORDS_WAITING, "row-sub", width, c("ink"), weight=650)
            TEXT.draw(p, x + w1, band.center().y(), " · " + strings.WORDS_WAITING_LINE, "row-sub",
                      max(0, band.right() - x - w1 - round(6 * f)), c("overlay-ink-dim"))
            y += bh + round(8 * f)
        nh = _line_h("arrival-number")
        if card is not None:
            alpha = FADED if card.kept else 1.0
            today = strings.WORDS_TODAY.format(n=f"{card.today:,}")
            tdw, _e = TEXT.draw(p, px, y + nh / 2, today, "row-sub", width, faded("overlay-ink-dim", alpha),
                                align="right", elide=False)
            room = width - tdw - round(12 * f)                  # the label never runs under "M today"
            if card.n_new:
                big = f"{card.n_new:,}"
                bw, _e = TEXT.draw(p, px, y + nh / 2, big, "arrival-number", room, faded("ink", alpha), elide=False)
                TEXT.draw(p, px + bw + round(6 * f), y + nh / 2, strings.WORDS_NEW_WHEN, "row-sub",
                          max(0, room - bw - round(6 * f)), faded("overlay-ink-dim", alpha))
            else:
                TEXT.draw(p, px, y + nh / 2, strings.WORDS_NOTHING_NEW, "row-title", room, faded("ink", alpha))
            bar = QRect(px, y + nh + round(3 * f), width, max(3, round(5 * f)))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("line"))
            p.drawRoundedRect(QRectF(bar), bar.height() / 2, bar.height() / 2)
            if card.today:
                a = round(bar.width() * card.n_new / card.today)
                p.setBrush(faded("accent-deep", 0.7 * alpha))
                p.drawRoundedRect(QRectF(bar), bar.height() / 2, bar.height() / 2)
                if a:
                    p.setBrush(faded("accent", alpha))
                    p.drawRoundedRect(QRectF(bar.left(), bar.top(), a, bar.height()), bar.height() / 2,
                                      bar.height() / 2)
        else:
            TEXT.draw(p, px, y + nh / 2, strings.WORDS_READING, "row-sub", width, c("overlay-ink-dim"))
        if self.kept and self.sentences:
            self._paint_sentence(p)
        if not self.kept:
            fy = self.height() - round(_line_h("row-sub") + 6 * f)
            p.fillRect(QRect(px, fy - round(3 * f), width, 1), c("line-hi"))
            TEXT.draw(p, px, fy + _line_h("row-sub") / 2, strings.WORDS_KEEP, "row-sub", width, c("overlay-ink-dim"))
        p.end()

    def sentence_parts(self):
        """The line under the words, kept open: (before, the word, after, its place) of the hovered (else the clicked)
        word's sentence, cut around the word to fit one line; None when that word has none (or none is pointed at)."""
        word = self.hot_word or self.picked_word
        if not self.sentences or word is None:
            return None
        found = self.sentences.get((getattr(word, "word", None), getattr(word, "reading", None)))
        if found is None:
            return None
        role = "row-sub"
        place = strings.WORDS_PLACE.format(place=found.place) if found.place else ""
        room = self._sentence_rect().width() - (_adv(place, role) if place else 0)
        before, mid, after = found.text[:found.start], found.text[found.start:found.end], found.text[found.end:]
        while _adv(before + mid + after, role) > room and (len(before) > 1 or len(after) > 1):
            if len(before) >= len(after) and len(before) > 1:
                before = "…" + before[2:]
            elif len(after) > 1:
                after = after[:-2] + "…"
        return before, mid, after, place

    def _paint_sentence(self, p):
        """The hovered (else the clicked) word's sentence on one line, the word in the accent, cut around it."""
        r = self._sentence_rect()
        p.fillRect(QRect(r.left(), r.top() - round(3 * fz()), r.width(), 1), c("line-hi"))
        parts = self.sentence_parts()
        if parts is None:
            return
        before, mid, after, place = parts
        x, ym = r.left(), r.center().y()
        for text, ink, weight in ((before, c("overlay-ink-dim"), None), (mid, c("accent"), 650),
                                  (after, c("overlay-ink-dim"), None), (place, c("overlay-ink-faint"), None)):
            if text:
                w, _e = TEXT.draw(p, x, ym, text, "row-sub", r.right() - x, ink, weight=weight)
                x += w


class _Relay(QObject):
    """The provider's answers, from its worker, to the window's thread."""
    card = pyqtSignal(object, object)
    sentences = pyqtSignal(object, object)


class PeekHost(QObject):
    """The rows' asks to the card: a hover on *N new* (the bubble's timing, the words asked at once), leaving it (a
    short grace so the pointer can reach the card), a click (kept open). `provider()`: the window's
    `title_words.TitleWords` or None; `view()`: the view the rows were built from (for the titles of what's taught where)."""

    def __init__(self, parent, provider, view, tooltips=None, router=None, open_journey=None, mark=None, undo=None,
                 say=None):
        super().__init__(parent)
        self.card = WordPeek(parent)
        self.provider, self.view, self.tooltips, self.open_journey = provider, view, tooltips, open_journey
        # Kotoba-K: `mark(marks)` / `undo()` write (a worker's: they block) and answer a `word_marks.Marked`; `say(line)`
        # the bar's (a failure). Without them the card marks nothing (no ✓ / ⊘, no *I know all of these*).
        self.mark, self.undo, self.say = mark, undo, say
        self.card.tooltips = tooltips
        self.card.mark_asked.connect(self._mark)
        self.card.all_known.clicked.connect(self._all_known)
        if router is not None:
            router.register(self.card)
        self.relay = _Relay(self)
        self.relay.card.connect(self._card_came)
        self.relay.sentences.connect(lambda key, found: self.card.set_sentences(key, found))
        self.card.sentences_wanted.connect(self._want_sentences)
        self.card.journey_asked.connect(self._journey)
        self.card.pointer_in.connect(self._pointer_in)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_now)
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.timeout.connect(self._leave_now)
        self._pending = None                       # (row, anchor) the hover waits to show
        self._cards = {}                           # row key -> its last card (this hover's)
        self._on_card = False

    @staticmethod
    def scope(row, episode=None):
        """The row, or one episode of it as a title of its own (its row's tier, its label after the title)."""
        if episode is None:
            return row
        return row._replace(key=(row.key, episode.id), title=strings.WORDS_EPISODE_TITLE.format(
            title=row.title, ep=episode.label), episodes=(episode,), next_index=0)

    def _shown(self):
        """On screen or opening (an opening keeps the widget hidden until its motion ends: review r1 #1)."""
        return self.card.isVisible() or motion.opening_of(self.card) is not None

    def hover(self, row, anchor):
        """The pointer rests on a row's *N new* (`anchor`: its rect in the card's parent)."""
        self._grace.stop()
        if self._shown() and getattr(self.card.row, "key", None) == row.key:
            return
        if self._shown() and self.card.kept:
            return                                   # a kept card stays until it is closed
        self._pending = (row, anchor)
        self._ask(row)
        wait = self.tooltips.delay() if self.tooltips is not None else theme.MOTION["tooltip-delay"]
        if self._shown():                            # another row's card, shown or still opening (r2)
            motion.cancel_opening(self.card)
            self.card.hide()
            wait = theme.MOTION["tooltip-again"]
        if wait <= 0:
            self._show_now()
        else:
            self._timer.start(wait)

    def left(self):
        """The pointer left *N new*: the hover card goes after a grace, unless the pointer is on it."""
        self._timer.stop()
        self._pending = None
        if self._shown() and not self.card.kept:
            self._grace.start(GRACE_MS)

    def keep(self, row, anchor):
        """A click on *N new*: the card for `row`, kept open at once (its words as soon as they come)."""
        self._timer.stop()
        self._grace.stop()
        self._pending = None
        card = self._cards.get(row.key)
        self.card.show_for(row, anchor, card, kept=True)       # pending painted first: the press reacts at once
        self._ask(row)                                         # always asked again: a move, a Generate since (r1 #2)

    def close(self):
        self._timer.stop()
        self._grace.stop()
        self._pending = None
        self.card.close()

    def _ask(self, row):
        provider = self.provider() if callable(self.provider) else self.provider
        if provider is None:
            return
        view = self.view() if callable(self.view) else self.view
        relay = self.relay
        provider.ask(row, view, lambda card, key=row.key: relay.card.emit(key, card))

    def _card_came(self, key, card):
        if card is None:
            if getattr(self.card.row, "key", None) == key and self.card.card is None and not self.card.kept:
                self.card.hide()
            return
        self._cards = {key: card}
        self.card.set_card(card)

    def _show_now(self):
        if self._pending is None:
            return
        row, anchor = self._pending
        self._pending = None
        card = self._cards.get(row.key)
        self.card.show_for(row, anchor, card, kept=False)

    def _pointer_in(self, inside):
        self._on_card = inside
        if inside:
            self._grace.stop()
        elif self._shown() and not self.card.kept:
            self._grace.start(GRACE_MS)

    def _leave_now(self):
        if not self._on_card and not self.card.kept:
            motion.cancel_opening(self.card)
            self.card.hide()

    def _want_sentences(self, key):
        provider = self.provider() if callable(self.provider) else self.provider
        row = self.card.row
        if provider is None or row is None or getattr(row, "key", None) != key:
            return
        relay = self.relay
        provider.sentences(row, lambda found, k=key: relay.sentences.emit(k, found))

    def _journey(self, episode):
        if self.open_journey is not None:
            self.open_journey(self.card.journey, episode)

    # --- Kotoba-K: Known / Ignore ------------------------------------------------------------------------------ #
    def _mark(self, marks):
        """A ✓ / ⊘ click (painted already): written on a worker; a failure puts back each word this click still shows
        (a later click on it wins) and says why. An answer for a card that has since moved to another row changes
        nothing on screen."""
        before = {w: was for w, _m, was in marks}
        sent = {w: m for w, m, _was in marks}
        if self.mark is None:
            self.card.set_marks(before)
            return
        from app.qt import bridge
        key = self._key()
        bridge.run_in_worker(self.mark, list(sent.items()),
                             then=lambda result: self._marked(result, key, sent, before),
                             failed=lambda info: self._marked(None, key, sent, before, info))

    def _key(self):
        return getattr(self.card.row, "key", None)

    def _here(self, key):
        """The card still shows the row `key` (open): an answer may change what it paints."""
        return self.card.isVisible() and self._key() == key

    def _still(self, sent):
        """Of `sent` {word: mark}, the words the card still shows with that mark (no later click on them)."""
        return [w for w, m in sent.items() if self.card.marked.get(w) == m]

    def _marked(self, result, key, sent, before, info=None):
        error = (str(info[0]) if info else "an error") if result is None else result.error
        if error is not None:
            if self._here(key):
                self.card.set_marks({w: before[w] for w in self._still(sent)})
            if self.say is not None:
                self.say(strings.WORDS_MARK_FAILED.format(why=error))
            return
        if self._here(key):
            self._again()

    def _all_known(self, _checked=False):
        """*I know all of these*: the title's every unmarked *New here* word known, in one write; then the button is
        that batch's Undo. (A press while one is on its way does nothing: `press.run`.)"""
        card = self.card
        if card.card is None or self.mark is None:
            return
        key = self._key()
        if card.all_done:
            words = list(card.all_done)
            press.run(card.all_known, "words:undo-all", self.undo,
                      then=lambda result, w=words: self._all_undone(result, w, key), win=card.window())
            return
        words = [w.word for w in card.card.new if card.marked.get(w.word) is None]
        if not words:
            return
        card.set_marks({w: "known" for w in words})                 # painted with the press's own arc
        press.run(card.all_known, "words:all-known", self.mark, [(w, "known") for w in words],
                  then=lambda result, w=words: self._all_marked(result, w, key), win=card.window())

    def _all_marked(self, result, words, key):
        here = self._here(key)
        if result.error is not None:
            if here:
                self.card.set_marks({w: None for w in self._still({w: "known" for w in words})})
            if self.say is not None:
                self.say(strings.WORDS_MARK_FAILED.format(why=result.error))
            return
        if here:
            self.card.set_all_done(words)
            self._again()

    def _all_undone(self, result, words, key):
        if result.error is not None:
            if self.say is not None:
                self.say(strings.WORDS_MARK_FAILED.format(why=result.error))
            return
        if self._here(key):
            self.card.set_marks({w: None for w in self._still({w: "known" for w in words})})
            self.card.set_all_done(None)
            self._again()

    def _again(self):
        """The card's words asked again after a mark landed: its counts follow the numbers (the marked words kept in
        place while it is open: `title_words.keep_marked`)."""
        row = self.card.row
        if row is not None and self.card.isVisible():
            self._ask(row)
