"""*Needs you* in the window (W3.2 Q5; the RUNBOOK's §1 *Needs you* row, §5 leans 4–6, §5a IK-2, IK-3, IK-8, N8–N10;
the window's spec A2 #69–70, G4–G7, 06 E8, E10, E11, P1.2-1).

- **The tab's stone** (`stone`, `paint_stone`): the cracked amber stone (ref-extract row 115, `rough3`; flat) with the
  number of unseen entries, drawn once per size × dpr; the shell's `TabButton` paints it in place of a badge. The tab
  is shown only while something waits; empty, it hides and the window goes back to Current (A2 #70).
- **The entries** are `app/services/needs.entries`' (S3), worked out on a worker (`NeedsYou.refresh`) from the reader's
  view, the bar's failures, Connect's record, the seen file, the offline roots and the store's rename questions —
  never on the window's thread; an answer equal to the last one repaints nothing (N9, S19), and a view whose rows
  hold the same things in another order (a move) works nothing out (C1).
- **The cards** (`NeedsCards`): one per entry in S3's order, a 3 px amber left edge, its words and its buttons. Each
  action name maps to one call (`NeedsYou.act`); a name with no callable (P4.1's *Mine the text only*, *Make their
  cards*; Connect's when Connect isn't installed; the writer's with no library) is hidden. Writes go through the
  window's writer (`moves.Writer`: `relink`, `its_new`, `link_video`, `remove`) by the drag controller's tickets, so a
  toast's Undo and Ctrl+Z take them back as they take back a move; Connect's (`actions.mine_anyway`,
  `hato.backfill`, `status.dismiss`) and the seen file's (*Keep its words*, *Leave them*) run on a worker.
- **Remove** asks first, naming the count (`confirm.ask`: Esc, Back, a click outside are No); an offline root never
  offers it and *Remove all* never counts its files (IK-8).
- **Setup's first cards** (SRC D1): *Make cards* turns Connect on if it's off — Settings › Anki's own switch on a
  worker (`settings_connect`: the watermarks, the save, hato's back-fill, the service's reload), the write told on the
  bridge — then logs the first 20 of Current as entering the mine line by your choice (`setup_wizard.first_cards`);
  *Not now* writes nothing but its answer. Either answer's line says where the switch lives.
- **Known from Anki's question** (laptop round 7 #43): *Mark them known* → `known_signal.accept_offer` on a worker (only
  the cards still suspended / marked), then the automation's `known_changed` (the bar's count, the journey asked
  again), as a known-words import ends; *Leave them* → `decline_offer`. Either is the answer: the card goes. Pressed, the
  button's arc turns at once, before the worker starts (round 8 row 45: `app/qt/press.py`). A sync's end refreshes the
  page (`synced`), so the question shows as soon as the first read made it.
- **A source folder that is gone** (T6, Sonic 2026-10-24): the shell hands in the looks' gone rows (`gone_in`, those
  *Keep waiting* hid left out). *Find its new folder…*: the system's folder picker, opened where its episodes are read
  now if a look found them, then `SourceLooks.find_new_folder` on the looks' worker (MV-1's one rule: the folder read,
  the old folder's episodes joined there, never a second copy) — its arc turns until the answer; when an episode joined
  (`stop`), the old folder stops being read through the writer (`stop_reading`: the toast's Undo, Ctrl+Z), else the bar
  says why and the card stays. *Stop reading it*: the writer's `stop_reading` (one Undo; nothing on disk moves, every
  episode stays). Either's save, and its Undo, lists the folders again (`drag._sources_stopped`): the card goes, or comes
  back. *Keep waiting*: the shell's `keep_waiting_for` (the offline line's dismissal, kept in the seen file). B14: the
  looks let the folder go first, and read it again on the stop's Undo (`settings_sources.give_stop`, Settings' rule).
- **A folder's files, or the library's, mostly gone** (K3 / K1, Kura's cards): *Choose a folder…* matches each file at
  its place under the folder picked (`needs.match_tree`, a worker) and points them all back in ONE writer command
  (`relink_many`: one toast, one Undo; what the store couldn't take said in the bar). The library's card waits for
  every folder's look (`settled`: the shell's judged summary) and offers *Start fresh* — Settings' own sheet, then
  `SourceLooks.fresh` (the old library backed up in the trash, never deleted).
- **Opening the page** marks its entries seen (`needs.mark_all_seen`, on a worker): they stay listed and stop
  counting (P1.2-1).
"""
import collections
import os
import time

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from app import path_utils, settings_manager, theme
from app.qt import bridge, strings, style, toast
from app.qt import press as qpress
from app.services import needs as service
from app.services import view_rows

# --- the stone (ref-extract row 115: viewBox 24) ------------------------------------------------------------------- #
_OUTLINE = ((2.4, 10), (6.2, 3.4), (13, 1.4), (20.6, 5.2), (23, 13.2), (19.4, 20.6), (11, 23), (4, 19.6))
_TOP = ((6.2, 3.4), (13, 1.4), (20.6, 5.2), (14.6, 9), (8.2, 8.6))
_LEFT = ((2.4, 10), (8.2, 8.6), (14.6, 9), (12.4, 14), (5, 15.4))
_CRACK = ((13, 1.6), (11.6, 4.6), (13.4, 6.6))
_STONES = {}                                # (size, dpr) -> QPixmap: drawn once each
LINES_SHOWN = 12                            # a card's per-file lines shown (*and N more*: a 300-file show is no
#                                             1,000 widgets; the card's own answers still count every line — IK-L1-4)
FOLDER_LINES_SHOWN = 3                      # ... on a folder's or the library's card (K3 / K1): its own answers
#                                             stay in sight above them, and *and N more* says the rest
drawn = [0]                                 # stones drawn (tests)
BUILT_AT_ONCE = 30                          # alpha 4 B (Mattias: 3,000 cards opened in ~10 s, frozen): the cards built
#                                             as the page opens, and again each time it is scrolled near its end
SLICE_S = 0.004                             # ... those built a slice at a time, off idle time (one card a slice
#                                             at least: ~5 ms each under the style sheet, its layout ~20 ms more)
FIRST_FRAME = 2                             # the cards built in the press's own frame: the page is there at once, the
#                                             rest of the first ones follow on idle time
NEAR_END = 1.5                              # viewports from the end that ask for the next cards


def stone_size(factor):
    return round(theme.NEEDS_STONE_PX * factor)


def _poly(points):
    return QPolygonF([QPointF(x, y) for x, y in points])


def stone(size, dpr):
    """The stone without its number, `size` px square at `dpr` — drawn once per (size, dpr)."""
    key = (int(size), round(float(dpr), 3))
    pix = _STONES.get(key)
    if pix is not None:
        return pix
    k = theme.NEEDS_STONE
    pix = QPixmap(max(1, round(key[0] * key[1])), max(1, round(key[0] * key[1])))
    pix.setDevicePixelRatio(key[1])
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = key[0] / 24.0
    p.scale(s, s)
    p.setPen(QPen(style.qcolor(k["stroke"]), 1.0))
    p.setBrush(style.qcolor(k["fill"]))
    p.drawPolygon(_poly(_OUTLINE))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(style.qcolor(k["top"]))
    p.drawPolygon(_poly(_TOP))
    p.setOpacity(k["left-alpha"])
    p.setBrush(style.qcolor(k["left"]))
    p.drawPolygon(_poly(_LEFT))
    p.setOpacity(k["crack-alpha"])
    crack = QPainterPath(QPointF(*_CRACK[0]))
    for pt in _CRACK[1:]:
        crack.lineTo(QPointF(*pt))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(style.qcolor(k["crack"]), 0.8))
    p.drawPath(crack)
    p.end()
    _STONES[key] = pix
    drawn[0] += 1
    return pix


def paint_stone(p, x, line, size, number, font):
    """The stone at `x`, centred on the name's midline `line`, its number on it (warn, a dark shade 1 px under it:
    the reference's shadow, flat)."""
    from PyQt6.QtGui import QFontMetricsF
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    top = round((line - size / 2) * dpr) / dpr
    p.drawPixmap(QPointF(x, top), stone(size, dpr))
    text = str(number)
    p.setFont(font)
    fm = QFontMetricsF(font)
    tx = x + (size - fm.horizontalAdvance(text)) / 2
    ty = round((line + fm.capHeight() / 2) * dpr) / dpr
    p.setPen(style.qcolor(theme.NEEDS_STONE["number-shade"]))
    p.drawText(QPointF(tx, ty + 1), text)
    p.setPen(style.qcolor(style.colours()["warn"]))
    p.drawText(QPointF(tx, ty), text)


# --- the cards ----------------------------------------------------------------------------------------------------- #
class _Card(QWidget):
    """One entry's card: the stylesheet's `needscard` ground, a 3 px amber left edge painted over it."""

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        r = theme.RADII["r"]
        path.addRoundedRect(QRectF(self.rect()), r, r)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 3, self.height()), style.qcolor(style.colours()["warn"]))
        p.end()


class _Words(QLabel):
    """A card's words. Its height for a width is worked out once per width (alpha 4 B: under the app's style sheet a
    wrapping label measures its text again at every layout pass, and every pass asks every card — 3,000 cards made each
    pass ~0.6 ms a card, the page frozen while it grew); its words never change once made."""

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self._hfw = {}

    def heightForWidth(self, width):
        h = self._hfw.get(width)
        if h is None:
            if len(self._hfw) > 8:
                self._hfw.clear()
            h = self._hfw[width] = super().heightForWidth(width)
        return h

    def changeEvent(self, event):
        self._hfw.clear()                       # (a font or style change measures it again)
        super().changeEvent(event)


class _More(QToolButton):
    """A card's ⋯ (alpha 4 D2): the arrivals tray's ⋯ square, painted by the tray's own rule (`arrivals._paint_square`,
    one look for a ⋯ beside buttons)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        side = round(theme.size("icon-square", style.current()[1]))
        self.setFixedSize(side, side)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, _event):
        from app.qt.arrivals import _paint_square
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _paint_square(p, self.rect(), "more", self.underMouse() or self.isDown())
        p.end()


def _label(text, name, parent, wrap=True):
    lab = _Words(text, parent)
    lab.setObjectName(name)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setWordWrap(wrap)
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return lab


# round 8 row 45: the buttons whose press turns an arc (`app/qt/press.py`, `NeedsYou._press`) — a card's answers that
# take it away, one press per card (A-5: the other answer pressed meanwhile asks nothing), then its presses that leave
# it (a line's own answer, asking hato again, a folder, a program, the logs)
ANSWERS = ("mark_known", "leave_known", "keep_all", "leave_them", "mine_anyway", "dismiss", "make_cards",
           "first_cards", "first_cards_on", "not_now", "not_now_on", "find_folder", "stop_reading", "keep_waiting",
           "start_fresh")
PRESSED = ANSWERS + ("keep_words", "ask_hato", "choose_folder", "open_logs", "save_logs",
                     "open_anki")


class NeedsCards(QWidget):
    """The page's cards, in the entries' order; a card is rebuilt only when its own entry (or its find results, or its
    look running) changed (S19), and only while the page shows (C1: entries given while it is hidden are built when it
    shows, or when a card is asked for). `action(name, entry, line)`: a button pressed (`line` None for the card's own).

    Alpha 4 B: one long page, built as it is read — the first `BUILT_AT_ONCE` cards at once, the next ones each time
    the page is scrolled near its end (`scrolled`), a slice of `SLICE_S` at a time off idle time (`_grow`), never one
    long step; a card asked for (`card`, `reveal`) is built with those before it. The cards built are always the
    entries' first ones, each built once."""
    action = pyqtSignal(str, object, object)
    more = pyqtSignal(object, object)           # alpha 4 D2: a card's ⋯ pressed (entry, the ⋯)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("needscards")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(theme.SPACING["settings-card-gap"])
        self.cards = {}                         # key -> (signature, widget): the entries' first `len(order)`
        self.order = []
        self.builds = 0                         # cards built (tests: S19)
        self.epoch = 0                          # bumped when the callables change (`NeedsYou.rewire`): every card again
        self.shown = lambda name, entry, line=None: True
        self.adopt = lambda button, name, entry: None   # a button made again while its press is live: it shows it
        self.has_more = lambda entry: False     # alpha 4 D2: whether a card shows a ⋯ (`NeedsYou.more_entries`)
        self._owed = None                       # C1: the entries given while the page is hidden, built when it shows
        self._want = ()                         # alpha 4 B: every entry, in order (built or not)
        self._found, self._looking = {}, ()
        self.limit = BUILT_AT_ONCE              # ... how many of them are to be built
        self._growing = False                   # ... a slice is due on idle time
        self.box.addStretch(1)

    def show_entries(self, entries, found=None, looking=()):
        if not self.isVisible():
            self._owed = (entries, found, looking)
            return                              # C1: no card is made under the style sheet for a page nobody sees
        self._owed = None
        self._build(entries, found, looking)

    def showEvent(self, event):
        super().showEvent(event)
        self.flush(now=FIRST_FRAME)             # alpha 4 B: the page in the press's frame, its cards right after

    def flush(self, now=BUILT_AT_ONCE):
        """The cards the entries given while hidden owe, built now (the page shown, or a card asked for) — at most
        `now` of them at once, the rest on idle time."""
        owed, self._owed = self._owed, None
        if owed is not None:
            self._build(*owed, now=now)

    def _sig(self, e):
        # seen or not is the tab's count only (no card shows it): opening the page builds no card again (S19)
        return e._replace(unseen=False), self._found.get(e.key), e.key in self._looking, self.epoch

    def _build(self, entries, found, looking, now=BUILT_AT_ONCE):
        self._want, self._found, self._looking = tuple(entries), found or {}, looking
        keep, order, built = {}, [], self.builds
        for e in self._want[:self.limit]:       # alpha 4 B: the first ones; the rest as the page is scrolled
            sig = self._sig(e)
            old = self.cards.get(e.key)
            if old is not None and old[0] == sig:
                keep[e.key] = old
            else:
                if self.builds - built >= now:
                    break                       # (many to build: the rest in slices, `_grow` — a rewire, an open)
                if old is not None:
                    old[1].setParent(None)
                    old[1].deleteLater()
                keep[e.key] = (sig, self._card(e, self._found.get(e.key), e.key in self._looking))
                self.builds += 1
            order.append(e.key)
        for key, (_sig, w) in self.cards.items():
            if key not in keep:
                w.setParent(None)
                w.deleteLater()
        self.cards = keep
        if self.builds != built or order != self.order:
            for i, key in enumerate(order):     # a rebuilt card is a new widget: it takes its place in the layout even
                w = self.cards[key][1]          # when the order is the same (else it sits at 0,0 at 100x30, unlaid —
                if self.box.indexOf(w) != i:    # the laptop's "unviewable" page); a kept card in place isn't touched
                    self.box.removeWidget(w)
                    self.box.insertWidget(i, w)
            self.order = order
        for key in order:
            w = self.cards[key][1]
            if w.isHidden():
                w.show()
        if len(self.order) < min(self.limit, len(self._want)) and not self._growing:
            self._growing = True                # cut short above: the rest of what was built, in slices
            QTimer.singleShot(0, self._grow)
        elif len(self._want) > len(self.order):
            QTimer.singleShot(0, self.scrolled)     # (a page shorter than its view asks for the next ones by itself)

    def _area(self):
        area = self.parentWidget().parentWidget() if self.parentWidget() is not None else None
        return area if isinstance(area, QScrollArea) else None

    def scrolled(self, *_args):
        """Alpha 4 B: the page scrolled (or its length changed) — near its end with cards still to build, the next
        `BUILT_AT_ONCE` are built, a slice at a time on idle time."""
        if self._growing or len(self.order) >= len(self._want) or not self.isVisible():
            return
        area = self._area()
        if area is not None:
            bar = area.verticalScrollBar()
            if bar.maximum() - bar.value() > NEAR_END * area.viewport().height():
                return
        self.limit = max(self.limit, len(self.order) + BUILT_AT_ONCE)
        self._growing = True
        QTimer.singleShot(0, self._grow)

    def _grow(self, upto=None):
        """The next cards built in order, until `self.limit` (or `upto`, all at once: a card asked for) — on idle time,
        `SLICE_S` at a time."""
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        self._growing = False
        start = time.perf_counter()
        target = min(len(self._want), upto if upto is not None else self.limit)
        while len(self.order) < target:
            e = self._want[len(self.order)]
            w = self._card(e, self._found.get(e.key), e.key in self._looking)
            self.cards[e.key] = (self._sig(e), w)
            self.box.insertWidget(len(self.order), w)
            self.order.append(e.key)
            self.builds += 1
            w.show()
            if upto is None and time.perf_counter() - start > SLICE_S and len(self.order) < target:
                self._growing = True
                QTimer.singleShot(0, self._grow)
                return
        self.limit = max(self.limit, len(self.order))

    def settled(self):
        """Whether every card due is built (none waiting on idle time)."""
        return self._owed is None and not self._growing and len(self.order) >= min(self.limit, len(self._want))

    def card(self, key):
        self.flush()
        got = self.cards.get(key)
        if got is None:                         # alpha 4 B: not built yet — built now, with those before it
            at = next((i for i, e in enumerate(self._want) if e.key == key), None)
            if at is None:
                return None
            self._grow(upto=at + 1)
            got = self.cards.get(key)
        return got[1] if got is not None else None

    def reveal(self, key):
        """Card `key` scrolled into view in the page's scroll area (built first if it was owed)."""
        card = self.card(key)
        area = self._area()
        if card is not None and area is not None:
            area.ensureWidgetVisible(card, 0, round(theme.SPACING["settings-card-gap"]))

    def buttons(self, key=None):
        """The shown buttons (of one card, or of every card built) -> [QPushButton]."""
        self.flush()
        cards = [self.card(key)] if key is not None else [w for _s, w in self.cards.values()]
        return [b for c in cards if c is not None for b in c.findChildren(QPushButton)]

    def _button(self, parent, name, entry, line=None, label=None):
        text, tip = strings.NEEDS_ACTIONS[name]
        b = QPushButton(label or text, parent)
        b.setProperty("size", "sm")
        b.setProperty("action", name)
        if line is not None:
            b.setProperty("line", line.key)     # round 8 row 45: a line's own answer (its arc on that line's button)
        b.setToolTip(tip)
        b.setAccessibleName(label or text)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c=False, n=name, e=entry, ln=line: self.action.emit(n, e, ln))
        if name in PRESSED:
            qpress.room(b)                      # round 8 row 45: its arc's room kept at rest, so nothing moves
        self.adopt(b, name, entry)
        return b

    def _card(self, e, results, looking):
        card = style.styled(_Card(self), "needscard")
        card.setProperty("kind", e.kind)
        card.setAccessibleName(e.title)
        f = theme.text_factor(style.current()[1])
        pad = [round(v * f) for v in toast.PAD]
        pad[0] += 3                                 # clear of the amber edge
        box = QVBoxLayout(card)
        box.setContentsMargins(*pad)
        box.setSpacing(round(6 * f))
        box.addWidget(_label(e.title, "needstitle", card))
        if e.say:
            box.addWidget(_label(e.say, "sheetline", card))
        by_line = dict(zip((ln.key for ln in e.lines), results or ())) if results else {}
        shown = FOLDER_LINES_SHOWN if e.kind in (service.FILES_FOLDER, service.LIBRARY_GONE) else LINES_SHOWN
        for ln in e.lines[:shown]:
            row = QHBoxLayout()
            row.setSpacing(round(8 * f))
            words = QVBoxLayout()
            words.setSpacing(0)
            words.addWidget(_label(ln.text, "sheetline", card))
            hit = by_line.get(ln.key)
            if hit is not None:
                why = _label(hit[2], "needswhy", card)
                why.setProperty("found", hit[1] is not None)
                words.addWidget(why)
            row.addLayout(words, 1)
            names = list(ln.actions)
            if e.kind == service.NO_VIDEO and hit is not None and hit[1] is None:
                names.append("remove_episode")       # G7: a line that found nothing can leave the library
            for name in names:
                if name == "choose_video" and hit is not None and hit[1] is not None:
                    continue                          # found: *Link these* takes it
                if self.shown(name, e, ln):
                    row.addWidget(self._button(card, name, e, ln))
            box.addLayout(row)
        if len(e.lines) > shown:
            box.addWidget(_label(strings.NEEDS_MORE_LINES.format(n=f"{len(e.lines) - shown:,}"), "sheetline",
                                 card))
        acts = QHBoxLayout()
        acts.setSpacing(round(8 * f))
        labels = (e.data or {}).get("labels") or {}
        for name in e.actions:
            if not self.shown(name, e):
                continue
            label = labels.get(name)
            if name == "link_these":
                n = sum(1 for _l, path, _w in results or () if path is not None)
                if not n:
                    continue                          # nothing found yet: nothing to link
                label = strings.NEEDS_ACTIONS["link_these"][0].format(n=n)
            if name == "find_videos" and looking:
                label = strings.NEEDS_LOOKING
            b = self._button(card, name, e, None, label)
            if name in ("find_videos", "find_all") and looking:
                b.setEnabled(False)
            acts.addWidget(b)
        acts.addStretch(1)
        if self.has_more(e):                        # alpha 4 D2: *Not now* · *Stop asking*, tucked in its ⋯
            more = _More(card)
            more.setProperty("action", "more")
            more.setAccessibleName(strings.NEEDS_MORE_NAME.format(title=e.title))
            more.setToolTip(strings.NEEDS_MORE_TIP)
            more.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            more.clicked.connect(lambda _c=False, en=e, m=more: self.more.emit(en, m))
            card.more = more
            acts.addWidget(more)
        box.addLayout(acts)
        return card


# --- the page's controller ---------------------------------------------------------------------------------------- #
def _connect_callable(module, name):
    """Connect's call for an action, or None (Connect not installed: its button hidden)."""
    try:
        mod = __import__(f"app.connect.{module}", fromlist=[name])
        return getattr(mod, name, None)
    except Exception:
        return None


def _find_miner(settings):
    """(A worker.) Row 13: whether setup's *Make cards* can be offered — Anki Miner as the one look finds it
    (`services.tools_found`, B2-7)."""
    from app.services import tools_found
    return tools_found.make_cards_shown(tools_found.tools_found(settings).miner)


def _default_asks(opener):
    """9a's questions through a store handle of this worker's own (closed after: a pool thread keeps none)."""
    if opener is None or getattr(opener, "mode", None) != "store" or not hasattr(opener, "handle"):
        return ()
    try:
        store = opener.handle()
        if store is None or not hasattr(store, "rename_asks"):
            return ()
        return service.asks_of(store)
    except Exception:
        return ()
    finally:
        close = getattr(opener, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass


def match_folder(folder, lines):
    """*Choose a folder…* (a worker): each gone line's file in `folder` by its own name, else the one file there with
    its extension and its episode number -> [(line, path)]."""
    try:
        with os.scandir(folder) as found:
            names = sorted(e.name for e in found if e.is_file())
    except OSError:
        return []
    folded = {n.casefold(): n for n in names}
    out = []
    for ln in lines:
        base = (ln.rel_path or "").replace("\\", "/").rsplit("/", 1)[-1]
        hit = folded.get(base.casefold())
        if hit is None and ln.number is not None:
            ext = os.path.splitext(base)[1].casefold()
            same = [n for n in names if os.path.splitext(n)[1].casefold() == ext
                    and view_rows.episode_number(n) == ln.number]
            hit = same[0] if len(same) == 1 else None
        if hit is not None:
            out.append((ln, os.path.join(folder, hit)))
    return out


def _matched_inside(folder, base, lines, tree, data):
    """(A worker.) *Choose a folder…*'s match — `needs.match_tree` for a folder's or the library's card, `match_folder`
    for a show's — split by the library folder (`data`): (the pairs inside it, how many matched outside it). The store
    points an item only at a file in the library folder (`library_store.library_rel`): one outside is never handed to
    the writer (A4B-4)."""
    from app import library_store
    pairs = service.match_tree(folder, base, lines) if tree else match_folder(folder, lines)
    inside = [(ln, path) for ln, path in pairs if library_store.library_rel(data, path) is not None]
    return inside, len(pairs) - len(inside)

def _find_none(answer):
    """Is *Find its new folder…*'s refusal T6 option 2's (a folder holding none of the gone folder's files, never read:
    `source_looks.FIND_NONE`)? It is said as the looks wrote it, never wrapped in *can't be read*. The looks' flag
    (`none`) when they give one; until then the refusal's shape — FIND_NONE's words around whatever folder the looks
    wrote (their spelling of the path may differ from the picker's: A4B-9), never the sentence formatted here."""
    if answer.get("none") is not None:
        return bool(answer["none"]) and bool(answer.get("refused"))
    from app.services import source_looks
    refused = answer.get("refused")
    head, _folder, tail = source_looks.FIND_NONE.partition("{folder}")
    return isinstance(refused, str) and len(refused) > len(head) + len(tail) and refused.startswith(head) and \
        refused.endswith(tail)

class NeedsYou(QObject):
    """The page's entries and their actions, for one window (`win`: the shell)."""
    changed = pyqtSignal()                       # new entries painted (the tab's count follows)

    def __init__(self, win, page, language):
        super().__init__(win)
        self.win = win
        self.page = page
        self.language = language
        switched = getattr(win, "library_switched", None)
        if switched is not None:                 # fix2: the library shown — it kept the one it opened with, so after a
            switched.connect(self._switched)     # switch its cards came from the language left's folder and seen file
        self.entries = ()
        self.found = {}                          # entry key -> find_videos' results
        self.looking = set()
        self.failures = ()
        self.view = None
        self.data_dir = None                     # None: the language's data folder (looked up on the worker)
        self.connect_line = None
        self.gathers = 0                         # entries worked out (tests: N9)
        self.gone_folders = None                 # T6: the looks' gone rows (None: no look has said yet)
        self._gone_judged = False                # ... and whether every folder was looked at (else no key is pruned)
        self._stopping = set()                   # T6: the gone folders whose *Stop reading it* was given (one each)
        self._asked = 0
        self._running = False
        self._again = False
        self._hidden_now = {}                    # alpha 4 D2: key -> the day *Not now* hid it (None: *Stop asking*) —
        #                                          off the page at the press, before its write lands
        self._landed = {}                        # A4A-11: key -> the first gather that reads its write (from it on
        #                                          the seen file alone says whether it is hidden)
        self._seen_jobs = collections.deque()    # A4A-8: the page's seen-file writes, one after another as pressed
        self.last_menu = None
        reader = getattr(win.services, "library", None)
        opener = getattr(reader, "opener", None)
        # what the entries are read from, each on a worker (tests replace them)
        self.read_connect = service.read_connect
        self.read_asks = lambda: _default_asks(opener)
        self.find_offline = service.find_offline
        self.read_settings = win.services.settings.get
        # the pickers (the system's own dialogs; tests replace them)
        self.pick_file = lambda title, folder: QFileDialog.getOpenFileName(self.win, title, folder)[0]
        self.pick_folder = lambda title, folder: QFileDialog.getExistingDirectory(self.win, title, folder)
        self.pick_save = lambda title, name: QFileDialog.getSaveFileName(self.win, title, name, "Zip (*.zip)")[0]
        # P4.1's hook (`make_cards(entry)`): hidden until set
        self.hooks = {}
        # D1's *Make cards* (each on a worker; tests replace them): Settings › Anki's switch, then the store's log
        self.switch_on = _settings_switch_on
        self.first_cards = _first_cards
        self.find_miner = _find_miner                   # row 13: Anki Miner looked for in the gather (a worker)
        self.accept_known, self.decline_known = _accept_known, _decline_known     # #43 (each on a worker)
        self.connect_calls = {"mine_anyway": _connect_callable("actions", "mine_anyway"),
                              "ask_hato": _connect_callable("hato", "backfill"),
                              "dismiss": _connect_callable("status", "dismiss"),
                              "save_logs": _connect_callable("status", "save_logs"),
                              "kick": _connect_callable("kick", "kick"),
                              "open_anki": _connect_callable("open_anki", "for_you")}     # A3W-6
        self.cards = page.cards
        self.cards.shown = self.available
        self.cards.has_more = lambda e: e.kind not in service.NO_LATER
        self.cards.more.connect(self.more_menu)
        self.cards.adopt = lambda b, name, entry: qpress.adopt(b, self._press_key(name, entry, b.property("line")),
                                                               win=self.win)
        self.cards.action.connect(self.act)
        heard = getattr(win, "bridge", None)
        if heard is not None and hasattr(heard, "settings_written"):
            heard.settings_written.connect(self._settings_written)
        self._day = QTimer(self)                 # alpha 4 D2: *Not now*'s cards come back the next day
        self._day.setSingleShot(True)
        self._day.timeout.connect(self._new_day)
        self._arm_day()

    def _arm_day(self):
        now = time.localtime()
        left = 86400 - (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec)
        self._day.start((left + 2) * 1000)

    def _new_day(self):
        """Midnight: what *Not now* hid yesterday is asked again (the next gather finds it, if it still needs you)."""
        today = service._today()
        self._hidden_now = {k: d for k, d in self._hidden_now.items() if d is None or d >= today}
        self._arm_day()
        if self._alive():
            self.refresh()

    # --- what comes in ------------------------------------------------------------------------------------------- #
    def _settings_written(self, keys):
        """Connect's switch written (setup's page 5, Settings › Anki): D1's line asks again in its words."""
        if "connect_enabled" in tuple(keys or ()) and self._alive():
            self.refresh()

    def _switched(self):
        """The shell showed another language's library (`library_switched`): its cards are that library's from here."""
        self.language = getattr(self.win, "language", None) or self.language

    def view_in(self, view):
        old, self.view = self.view, view
        if view is None:
            return
        if old is not None and old.mode == view.mode and old.loading == view.loading:
            if _same(old.rows, view.rows):
                return                               # another tab's change: these entries can't have moved
            if not self._running and _reads_same(old.rows, view.rows) and self._in_order(view.rows):
                return                               # C1: a reorder (a move's four views) — nothing they read moved
        self.refresh()

    def _in_order(self, rows):
        """Whether the cards that follow Current's order (a show's *file gone*, *no video*) stand in `rows`' order."""
        shown = list(dict.fromkeys((e.data or {}).get("group") for e in self.entries
                                   if e.kind in (service.GONE, service.NO_VIDEO)))
        if len(shown) < 2:
            return True
        wanted = set(shown)
        return [g for g in dict.fromkeys(service._group(r) for r in rows) if g in wanted] == shown

    def failures_in(self, failures):
        failures = tuple(failures or ())
        if failures == self.failures:
            return                                   # an empty tick: nothing to work out, nothing repainted (N9)
        self.failures = failures
        self.refresh()

    def connect_in(self, line):
        """Connect's line moved — or its episodes waiting on Anki for you did (A3W-6's line: the first job's reason, the
        line's words, can stay put while Anki closes or opens; review A-2): read from the feed's last look, in memory."""
        key = (line, self._anki_waiting())
        if key == self.connect_line:
            return
        self.connect_line = key
        self.refresh()

    def _anki_waiting(self):
        """The feed's episodes waiting on Anki for you, as (item, reason)s — no read (`Provider.latest`)."""
        try:
            from app.connect import feed
            from app.qt.shell import connect_feed
            latest = connect_feed(self.language, self.win.services.settings).latest()
            return frozenset((i, it.tip) for i, it in latest.items.items() if it.kind == feed.ANKI)
        except Exception:
            return frozenset()

    def gone_in(self, rows, language=None, judged=True):
        """T6: the source folders that are gone, as the looks' last summary says (the shell's: *Keep waiting*'s left
        out) — worked out again only when they moved (S19). `judged`: every folder was looked at — a summary with one
        not looked at yet (a listing before the first look, a language switch) prunes no gone folder's seen key (as
        `standing.not_back` keeps the offline line's: no look is no evidence the folder is back)."""
        rows = tuple(dict(r, language=language or self.language) for r in rows or ())
        judged = bool(judged)
        if rows == self.gone_folders and judged == self._gone_judged:
            return
        self.gone_folders, self._gone_judged = rows, judged
        self._stopping &= {r["id"] for r in rows}
        self.refresh()

    def reveal_gone(self):
        """T6 (finding 4): the first gone folder's card scrolled into view — 届's press opens the page at it."""
        first = next((e for e in self.entries if e.kind == service.FOLDER_GONE), None)
        if first is not None:
            self.cards.reveal(first.key)

    def shown_entries(self):
        """The entries on the page: the gather's, less those *Not now* / *Stop asking* hid since (alpha 4 D2: off at
        once, before the write lands and the next gather leaves them out by itself) — a line for many whose cards are
        all hidden goes with them."""
        if not self._hidden_now:
            return self.entries
        hid = self._hidden_now
        return tuple(e for e in self.entries if e.key not in hid and not (
            e.kind == service.BULK and (e.data or {}).get("keys") and all(k in hid for k in e.data["keys"])))

    def counts(self):
        """(listed, unseen) for the tab: the entries but the bulk answer, and the unseen ones (P1.2-1)."""
        shown = self.shown_entries()
        return sum(1 for e in shown if e.kind != service.BULK), service.badge(shown)

    def opened(self):
        """The page was shown: its unseen entries stop counting (still listed): the seen file and Connect's
        `seen_at`, on a worker; read again only when something was marked."""
        unseen = [e for e in self.shown_entries() if e.unseen and e.kind != service.FAILURE]
        if not unseen:
            return
        lang = self.language
        bridge.run_in_worker(service.mark_all_seen, lang, tuple(unseen),
                             then=lambda n: (n[0] or n[1]) and self.refresh(), failed=self._failed)

    # --- working the entries out (a worker) ----------------------------------------------------------------------- #
    def refresh(self):
        if self._running:
            self._again = True
            return
        if self.view is None:
            return
        self._running = True
        self._asked += 1
        asked = self._asked
        view, failures, lang, data_dir = self.view, self.failures, self.language, self.data_dir
        read_connect, read_asks, find_offline, read_settings = (self.read_connect, self.read_asks,
                                                                 self.find_offline, self.read_settings)
        find_miner = self.find_miner
        gone_folders = self.gone_folders
        library = self._library()
        gone_judged = gone_folders if self._gone_judged else None     # never pruned by a summary that judged none

        def gather():
            settings = read_settings() or {}
            connect = read_connect(lang) if settings.get("connect_enabled") else None
            rels = [e.rel_path for r in view.rows for e in r.episodes if e.rel_path] if view.mode == "store" else []
            roots = find_offline(lang, rels, data_dir) if rels else []
            asks = read_asks()
            try:                                    # IK-10: the answers are this library's (a new one asks again)
                service.keep_to_library(lang, library)
            except Exception as e:
                print(f"Needs you: the seen file wasn't tied to its library: {e!r}")
            try:                                    # W3.2 H (W5): the keys whose trouble is gone leave the seen file,
                service.prune(lang, view, offline_roots=roots, connect=connect,   # judged by what was read (no ask
                              asks=asks or None, gone_folders=gone_judged)       # read: a failed read looks the same)
            except Exception as e:                  # (a file that can't be read is left as it is: the gather goes on)
                print(f"Needs you: the seen file wasn't pruned: {e!r}")
            out = service.entries(view, failures, connect, service.read_seen(lang), roots, asks,
                                  service.read_answered(lang), offers=service.read_offers(lang),
                                  cards_on=settings_manager.connect_on(settings),    # B2-8: the one rule
                                  miner_found=bool(find_miner(settings)),     # row 13: D1's line waits for it
                                  gone_folders=gone_folders or (),
                                  hidden=service.read_hidden(lang),           # alpha 4 D2: Not now, Stop asking
                                  settled=gone_judged is not None)            # K1: every folder had its look
            return asked, tuple(out)
        bridge.run_in_worker(gather, then=self._got, failed=self._gather_failed)

    def _library(self):
        """The library's own id (`LibraryReader.store_id`: its store's, new with a reinstall or *Start fresh*), or
        None while it isn't known (no read yet, a reader without one)."""
        store_id = getattr(getattr(self.win.services, "library", None), "store_id", None)
        try:
            return store_id() if callable(store_id) else None
        except Exception:
            return None

    def _gather_failed(self, info):
        self._running = False
        self._failed(info)
        if self._again:
            self._again = False
            self.refresh()

    def _got(self, answer):
        asked, entries = answer
        self._running = False
        if not self._alive():
            return
        self.gathers += 1
        if self._again:
            self._again = False
            self.refresh()
        if asked != self._asked:
            return
        before = self.shown_entries() if self._landed else None
        moved = self._let_go(asked) and self.shown_entries() != before    # A4A-11: a card only the window still hid
        if entries == self.entries and not moved:
            return                                   # the same entries: nothing repainted (N9)
        self.entries = entries
        keys = {e.key for e in entries}
        self.found = {k: v for k, v in self.found.items() if k in keys}
        self._paint()
        if self.win.current_tab() == "needs" and self.win.isActiveWindow():
            self.opened()                            # looked at as it came

    def _let_go(self, asked):
        """(A4A-11) The keys whose write this gather read: the seen file says from now on whether they are hidden (a
        *Stop asking* goes with its trouble, N5, and its card asks again when the trouble comes back, this session
        too). -> whether any went."""
        done = [k for k, n in self._landed.items() if asked >= n]
        for k in done:
            del self._landed[k]
            self._hidden_now.pop(k, None)
        return bool(done)

    def _paint(self):
        if not self._alive():
            return
        self.page.show_entries(self.shown_entries(), self.found, self.looking)
        self.changed.emit()

    def rewire(self):
        """The callables changed (P4.1 set a hook, Connect came or went): every card built again with its buttons."""
        self.cards.epoch += 1
        self._paint()

    def _alive(self):
        from PyQt6 import sip
        return not sip.isdeleted(self.win) and not sip.isdeleted(self.cards)

    # --- the actions ------------------------------------------------------------------------------------------- #
    WRITES = frozenset(("choose_file", "choose_folder", "choose_video", "link_these", "remove", "remove_episode",
                        "remove_all", "this_one", "its_new"))

    def available(self, name, entry=None, line=None):
        """Whether `name` has a callable here (its button shown)."""
        if name in service.WIRED_LATER:
            return name in self.hooks
        if name in self.WRITES:
            return getattr(self.win, "moves", None) is not None
        if name in ("mine_anyway", "ask_hato", "dismiss", "save_logs", "open_anki"):
            return self.connect_calls.get(name) is not None
        if name == "stop_reading":                   # T6: through the window's writer (its Undo)
            return getattr(self.win, "moves", None) is not None
        if name == "find_folder":                    # ... and the looks read the folder picked
            return getattr(self.win, "moves", None) is not None and getattr(self.win, "looks", None) is not None
        if name == "start_fresh":                    # K1: the looks start the fresh library (`SourceLooks.fresh`)
            return callable(getattr(getattr(self.win, "looks", None), "fresh", None))
        return True

    def act(self, name, entry, line=None):
        try:
            getattr(self, "_do_" + name)(entry, line)
        except Exception as e:                       # a slot's escape never takes the window down
            self._failed((type(e), e, None))

    def _say(self, text):
        if self._alive():                            # (an answer coming in as the window closes says nothing)
            self.win.say(text)

    def _failed(self, info):
        from app.qt import applog
        # `act`'s (type, exception, None) or a worker's (exception, its traceback's text: `bridge.run_in_worker`)
        error = info[0] if info and isinstance(info[0], BaseException) else (info[1] if info else "")
        name = type(error).__name__ if isinstance(error, BaseException) else ""
        applog.log("needs", f"{name}: {error}")
        self._say(strings.NEEDS_FAILED.format(why=error))

    def _press_key(self, name, entry, line_key=None):
        """A card's answers are one press (A-5: one card, one answer at a time — the other answer pressed meanwhile
        asks nothing), of this language's card (A-11); a line's own button its line's (`line_key`: each line its own
        press, P3-A1); the arc on the button pressed (`qpress.adopt`). Every press of a card's button is under this
        key, so a card rebuilt meanwhile turns it again (P3-A10)."""
        key = f"needs:{self.language}:{'answer' if name in ANSWERS else name}:{entry.key}"
        return key if line_key is None or name in ANSWERS else f"{key}:{line_key}"

    def _control(self, name, entry, line=None):
        """The card's button for `name` (a line's: that line's), or None."""
        key = line.key if line is not None else None
        return next((b for b in self.cards.buttons(entry.key) if b.property("action") == name and
                     b.property("line") == key), None)

    def _press(self, name, entry, fn, *args, then, line=None, goes=True, failed=None):
        """Round 8 row 45: an answer whose work waits — the arc turns on its button, painted before `fn` goes to the
        worker; the card goes when it's done (`goes`; a line's answer may leave its card), and a failure says why in
        the bar (`failed`: the caller's own). -> the press, or None: one is live (nothing asked)."""
        return qpress.run(self._control(name, entry, line), self._press_key(name, entry, line and line.key), fn,
                          *args, then=then, failed=failed or self._failed, win=self.win, goes=goes)

    def _stays(self, name, entry):
        """An answer that ended with its card still here (a "couldn't" line): pressed again at once, it asks again
        (P3-A6 — `goes` holds a press only while its card is going)."""
        p = qpress.presses_of(self.win).find(self._press_key(name, entry))
        if p is not None:
            p.release()

    def _data(self):
        return self.data_dir or path_utils.get_data_path(self.language)

    def _give(self, text, ids, command, toast_it=True, told=None):
        """A write through the drag controller's tickets (its toast's Undo, Ctrl+Z) -> its number, or None.
        `told(ticket, event)`: the ticket's events ("saved", "refused", "undone", "ended": `drag.Ticket`)."""
        from app.qt import drag
        moves = self.win.moves
        if moves is None or moves.refused() is not None:
            return None
        ticket = drag.Ticket(text, (), ids)
        if told is not None:
            ticket.told = lambda event: told(ticket, event)
        return moves._give(ticket, command, toast=toast_it)

    def _offline_ids(self):
        return {i for e in self.entries if e.kind == service.OFFLINE for i in (e.data or {}).get("item_ids") or ()}

    # find / link (IK-2: a video never goes through relink)
    def _do_find_videos(self, entry, _line):
        self._look({entry.key}, lambda lang, settings, data: {entry.key: service.find_videos(lang, entry, settings,
                                                                                              data)})

    def _do_find_all(self, _entry, _line):
        cards = tuple(e for e in self.entries if e.kind == service.NO_VIDEO)
        self._look({e.key for e in cards}, lambda lang, settings, data: service.find_all(lang, cards, settings, data))

    def _look(self, keys, fn):
        self.looking |= keys
        self._paint()
        lang, data, read_settings = self.language, self.data_dir, self.read_settings

        def look():
            return fn(lang, read_settings() or {}, data or path_utils.get_data_path(lang))

        def done(results):
            if not self._alive():
                return
            self.looking -= keys
            self.found.update(results)
            self._paint()

        def failed(info):
            self.looking -= keys
            self._paint()
            self._say(strings.NEEDS_LOOK_FAILED.format(why=info[1]))
        bridge.run_in_worker(look, then=done, failed=failed)

    def _do_link_these(self, entry, _line):
        results = self.found.get(entry.key) or ()
        pairs = [(ln, path) for ln, (_label, path, _why) in zip(entry.lines, results) if path is not None]
        if not pairs:
            return
        writer = self.win.services.writer
        for ln, path in pairs:
            self._give(ln.label, (ln.item_id,), lambda t, i=ln.item_id, p=path: writer.link_video(i, p, label=t),
                       toast_it=False)
        self.win.toasts.show(strings.NEEDS_LINKING_ONE.format(label=pairs[0][0].label) if len(pairs) == 1 else
                             strings.NEEDS_LINKING.format(n=len(pairs)))
        self.found.pop(entry.key, None)
        self._paint()

    def _do_choose_video(self, entry, line):
        folder = os.path.join(self._data(), *[p for p in (entry.data or {}).get("folder", "").split("/") if p])
        path = self.pick_file(strings.NEEDS_CHOOSE_VIDEO_TITLE.format(label=line.label), folder)
        if not path:
            return
        writer = self.win.services.writer
        self._give(line.label, (line.item_id,), lambda t: writer.link_video(line.item_id, path, label=t),
                   toast_it=False)
        self.win.toasts.show(strings.NEEDS_LINKING_ONE.format(label=line.label))

    # a file gone: point it at its file (relink), keep its words, or remove it
    def _do_choose_file(self, entry, line):
        folder = os.path.join(self._data(), *[p for p in (entry.data or {}).get("folder", "").split("/") if p])
        path = self.pick_file(strings.NEEDS_CHOOSE_FILE_TITLE.format(label=line.label), folder)
        if not path:
            return
        writer = self.win.services.writer
        self._give(strings.NEEDS_RELINKED.format(label=line.label), (line.item_id,),
                   lambda t: writer.relink(line.item_id, path, label=t))

    def _do_choose_folder(self, entry, _line):
        """*Choose a folder…*: one press from the click to the toast (round 8 row 45) — its arc turns while the folder
        is looked for (a drive may be offline: its stat can take a while), and again once one is chosen, while its
        files are matched; a second click meanwhile does nothing. A folder's or the library's card (K3 / K1) matches
        each file at its place under the folder picked, then by its name, in the folders inside it too
        (`needs.match_tree`); a show's card, by name or episode number in that folder (`match_folder`). Either way
        they are pointed at all at once (`_relink_many`: one change, one Undo — IK2-2). The match lands on the window
        it was pressed in: closed, or another library shown since (ids repeat across stores), nothing is given
        (A4B-5)."""
        data = self._data()
        start = os.path.join(data, *[p for p in (entry.data or {}).get("folder", "").split("/") if p])
        lines = tuple(entry.lines)
        tree = entry.kind in (service.FILES_FOLDER, service.LIBRARY_GONE)
        language = getattr(self.win, "language", None)
        p = qpress.begin(self._control("choose_folder", entry), self._press_key("choose_folder", entry), win=self.win)
        if p is None:
            return

        def ended(why=None):
            if p.live():
                qpress.end(p, self.win, failed=why is not None, why=why)

        def here():
            return self._alive() and getattr(self.win, "language", None) == language

        def pick(there):                            # looked for on a worker: a drive may be offline (IK-L1-5)
            if not here():
                ended()
                return
            folder = self.pick_folder(strings.NEEDS_CHOOSE_FOLDER_TITLE, start if there else data)
            if not folder:
                ended()
                return

            def matched(found):
                if not self._alive():
                    return                          # (the window closed: nothing to say it in)
                ended()
                if here():
                    self._relink_many(found, len(lines), folder, tree)

            def broke(info):
                ended(info[0] if info else None)
                self._failed(info)
            bridge.run_in_worker(_matched_inside, folder, (entry.data or {}).get("folder", ""), lines, tree, data,
                                 then=matched, failed=broke)
        bridge.run_in_worker(os.path.isdir, start, then=pick, failed=lambda _info: pick(False))

    def _relink_many(self, found, n, folder, tree):
        """`found` = (the pairs matched inside the library folder, how many more were matched outside it): every one
        inside pointed at in ONE writer command (`Writer.relink_many`: one ticket, one toast with Undo, one Ctrl+Z —
        never one per file; K3 / K1, a show's card too: IK2-2). Once saved, what the store couldn't take (`change.left`:
        another item's file, no file there…) is said in the bar, how many and why, with those outside the library
        folder; all of them outside, nothing is given and the bar says why (A4B-4: the store can only point at a file
        in the library folder); none taken, the bar says so."""
        pairs, outside = found
        if not pairs and not outside:
            self._say(strings.NEEDS_RELINKED_NONE_TREE if tree else strings.NEEDS_RELINKED_NONE)
            return
        if not pairs:
            self._say(strings.NEEDS_RELINK_OUTSIDE.format(n=outside, folder=folder))
            return
        from app.qt import settings_sources
        writer = self.win.services.writer
        pairs = [(ln.item_id, path) for ln, path in pairs]
        language = getattr(self.win, "language", None)

        def told(ticket, event):
            if event == "ended" and self._alive() and getattr(self.win, "language", None) == language and                     settings_sources.cant_write(getattr(self.win, "services", None)) is None:
                self._say(strings.NEEDS_RELINK_NONE_TAKEN)           # (can't be written: the store's note says why)
            if event != "saved":
                return
            whys = {}
            for _item, why in getattr(ticket.change, "left", None) or ():
                whys[why] = whys.get(why, 0) + 1
            if outside:
                whys[strings.NEEDS_RELINK_WHY_OUTSIDE] = outside
            if whys:
                self._say(strings.NEEDS_RELINK_LEFT.format(n=sum(whys.values()), why=" · ".join(
                    strings.NEEDS_RELINK_WHY.format(why=why, n=k) for why, k in whys.items())))
        self._give(strings.NEEDS_RELINKED_N.format(k=len(pairs), n=n), [i for i, _p in pairs],
                   lambda t: writer.relink_many(pairs, label=t), told=told)

    def _do_keep_words(self, entry, line):
        self._answer("keep_words", entry, service.answer_keys(line if line is not None else entry), line=line)

    def _do_keep_all(self, entry, _line):
        self._answer("keep_all", entry, service.answer_keys(entry))

    def _do_leave_them(self, entry, _line):
        self._answer("leave_them", entry, service.answer_keys(entry))

    def _answer(self, name, entry, keys, line=None):
        """The card's answer kept (a worker), its button's arc turning until then (a line's answer: its card may
        stay, so a press on another line after it asks again)."""
        lang = self.language

        def done(_n):
            if self._alive():
                self.win.toasts.show(strings.NEEDS_KEPT)
                self.refresh()
        self._press(name, entry, service.answer, lang, list(keys), then=done, line=line, goes=line is None)

    def _do_remove(self, entry, line):
        if line is not None:
            self._remove([line.item_id], line.label)
        else:
            ids = list((entry.data or {}).get("item_ids") or ())
            self._remove(ids, entry.lines[0].label if len(ids) == 1 and entry.lines else None)

    def _do_remove_episode(self, entry, line):
        self._remove([line.item_id], line.label)

    def _do_remove_all(self, entry, _line):
        """*Forget every missing file* (alpha 4 B): every gone file below in ONE writer command — one ticket, one
        toast, one Undo."""
        self._remove(list((entry.data or {}).get("item_ids") or ()), None, forget=True)

    def _remove(self, ids, name, forget=False):
        """*Remove…*: asked first, naming the count (Esc, Back, a click outside: No); never a file under an offline
        root (IK-8); the trash (30 days) with Undo. `forget`: the line for every missing file, in its words."""
        offline = self._offline_ids()
        ids = [i for i in dict.fromkeys(ids) if i not in offline]
        if not ids:
            return
        from app.qt import confirm
        one = len(ids) == 1 and name
        title = strings.NEEDS_REMOVE_TITLE_ONE.format(name=name) if one else \
            strings.NEEDS_FORGET_TITLE.format(n=len(ids)) if forget else strings.NEEDS_REMOVE_TITLE.format(n=len(ids))
        yes = strings.NEEDS_REMOVE_YES_ONE if one else strings.NEEDS_FORGET_YES.format(n=len(ids)) if forget else \
            strings.NEEDS_REMOVE_YES.format(n=len(ids))
        writer = self.win.services.writer
        done = strings.NEEDS_REMOVED_ONE.format(name=name) if one else strings.NEEDS_FORGOT.format(n=len(ids)) \
            if forget else strings.NEEDS_REMOVED.format(n=len(ids))

        def answered(go):
            if go:
                self._give(done, ids, lambda t: writer.remove(ids, label=t))
        self.confirming = confirm.ask(self.win, title, strings.NEEDS_REMOVE_BODY, yes, strings.NEEDS_REMOVE_YES_TIP,
                                      default_no=True, danger=True, on_answer=answered)

    # 9a's questions (IK-3)
    def _do_this_one(self, entry, line):
        path = os.path.join(self._data(), *entry.data["rel"].split("/"))
        writer = self.win.services.writer
        self._give(strings.NEEDS_RELINKED.format(label=line.label), (line.item_id,),
                   lambda t: writer.relink(line.item_id, path, label=t))

    def _do_its_new(self, entry, _line):
        path = os.path.join(self._data(), *entry.data["rel"].split("/"))
        writer = self.win.services.writer
        if self._give(entry.data["rel"], (), lambda t: writer.its_new(path, label=t), toast_it=False) is not None:
            self._say(strings.NEEDS_ITS_NEW.format(name=entry.data["rel"].rsplit("/", 1)[-1]))

    # T6: a source folder that is gone
    def _do_find_folder(self, entry, _line):
        """*Find its new folder…*: the picker (where its episodes are read now, else the folder above where it was),
        then the looks read the folder picked and join the old folder's episodes there (MV-1's one rule) — its arc
        turns until they answer. An episode joined: the old folder stops being read, through the writer (the toast's
        Undo). Nothing joined, refused, failed or put off: the bar says why, nothing stops, the card stays."""
        data = entry.data
        if qpress.live(self.win, self._press_key("find_folder", entry)):
            return                                   # P5-A1: its Find (or Stop) is under way — no second picker
        looks = getattr(self.win, "looks", None)
        found = data.get("found_in") or ()
        start = found[0] if found else os.path.dirname(os.path.normpath(data["path"]))
        folder = self.pick_folder(strings.NEEDS_FIND_TITLE.format(name=data["name"]), start)
        if not folder:
            return
        folder = os.path.normpath(folder)
        if looks is None:
            self._say(strings.NEEDS_FIND_CLOSED)
            return
        key = self._press_key("find_folder", entry)
        p = qpress.begin(self._control("find_folder", entry), key, win=self.win, goes=True)
        if p is None:
            return
        relay = bridge.Relay(self.win)

        def answered(answer):
            relay.deleteLater()
            stops = self._found(entry, folder, answer or {})
            if p.live():
                qpress.end(p, self.win, failed=bool((answer or {}).get("refused")))
            if not stops:
                self._stays("find_folder", entry)    # the card stays: pressed again, it asks again
        relay.said.connect(answered)
        if not looks.find_new_folder(data["root"], folder, relay.call, language=data.get("language")):
            relay.deleteLater()
            qpress.end(p, self.win, failed=True)
            self._stays("find_folder", entry)
            self._say(strings.NEEDS_FIND_CLOSED)

    def _found(self, entry, folder, answer):
        """The looks' answer to *Find its new folder…* (the window's thread) -> True when the old folder is stopped."""
        from app import sources
        name = entry.data["name"]
        left = answer.get("language") not in (None, getattr(self.win, "language", None))   # a library left since
        if _find_none(answer):
            self._say(answer["refused"])             # T6 option 2: none of its files there — the folder isn't read
        elif answer.get("refused"):
            self._say(strings.NEEDS_FIND_REFUSED.format(folder=folder, why=answer["refused"]))
        elif answer.get("failed"):
            self._say(strings.NEEDS_FIND_FAILED.format(folder=folder, why=answer["failed"]))
        elif answer.get("later"):
            self._say(strings.NEEDS_FIND_LATER.format(folder=folder))
        elif answer.get("state") == sources.REACHED:     # (each answer that joined nothing says the folder picked
            self._say(strings.NEEDS_FIND_BACK.format(folder=folder, name=name))     # is read now: Sonic, 2026-10-25)
        elif answer.get("state") == sources.AWAY:
            self._say(strings.NEEDS_FIND_AWAY.format(folder=folder, name=name))
        elif answer.get("stop"):
            n = int(answer.get("joined") or 0)
            text = strings.NEEDS_FIND_JOINED_ONE.format(name=name, folder=folder) if n == 1 else \
                strings.NEEDS_FIND_JOINED.format(name=name, folder=folder, n=n)
            if left:                                 # that library's writer is gone — its card asks again there
                self._say(strings.NEEDS_FIND_JOINED_LEFT.format(name=name, folder=folder))
                return False
            return self._stop(entry, text)
        elif answer.get("dropped"):                  # T6 option 2: read, none of them there: not read any more —
            show = (entry.data.get("shows") or (name,))[0]     # what its look took in waits in New arrivals (IK2-9)
            n = int((answer.get("result") or {}).get("added") or 0)
            self._say(strings.NEEDS_FIND_DROPPED_ARRIVALS.format(folder=folder, show=show, n=n) if n > 1 else
                      strings.NEEDS_FIND_DROPPED_ARRIVAL.format(folder=folder, show=show) if n == 1 else
                      strings.NEEDS_FIND_DROPPED.format(folder=folder, show=show))
        else:
            show = (entry.data.get("shows") or (name,))[0]
            self._say(strings.NEEDS_FIND_NONE.format(folder=folder, show=show))
        return False

    def _do_stop_reading(self, entry, _line):
        """*Stop reading it*: the writer's `stop_reading` — its toast (*· saving…* until it lands) with Undo; the card
        goes with the folders' next listing (`drag._sources_stopped`). Nothing while its Find is under way (A-5)."""
        if qpress.live(self.win, self._press_key("stop_reading", entry)):
            return
        n, name = entry.data["items"], entry.data["name"]
        text = strings.NEEDS_STOPPED_READING_ONE.format(name=name) if n == 1 else \
            strings.NEEDS_STOPPED_READING.format(name=name, n=n) if n else \
            strings.NEEDS_STOPPED_READING_NONE.format(name=name)
        self._stop(entry, text)

    def _stop(self, entry, text):
        """The gone folder `entry` no longer read, through the window's writer (one Undo), once per card -> True when
        it was given. B14 (alpha 4): Settings' one rule (`settings_sources.give_stop`) — the looks let it go first (a
        look reading it stops between files), and read it again on its Undo, or when it is refused."""
        from app.qt import settings_sources
        root, language = entry.data["root"], entry.data.get("language") or self.language
        if root in self._stopping:
            return True                              # given already: the card goes with its listing

        def told(_ticket, event):                    # undone, refused or let go unsaved — it can be asked again
            if event in ("undone", "refused", "ended"):
                self._stopping.discard(root)
        self._stopping.add(root)
        if settings_sources.give_stop(self.win, root, text, language, told=told) is None:
            self._stopping.discard(root)
            return False
        return True

    def _do_keep_waiting(self, entry, _line):
        """*Keep waiting*: hidden until the folder is back (the offline line's dismissal, the shell's)."""
        keep = getattr(self.win, "keep_waiting_for", None)
        if qpress.live(self.win, self._press_key("keep_waiting", entry)):
            return                                   # A-5: its Find is under way
        if keep is not None:
            keep([entry.data["path"]])
            self._say(strings.NEEDS_KEEP_WAITING.format(name=entry.data["name"]))

    # alpha 4 D2: every card's ⋯ — *Not now* (until tomorrow) and *Stop asking* (with Undo); a line for many's "for all"
    def more_entries(self, entry):
        """The ⋯'s entries for `entry` -> [name]: a card's *Not now* · *Stop asking*; a line for many's *Not now for
        all* (when it isn't one of its buttons) · *Stop asking for all*."""
        if entry.kind in service.NO_LATER:
            return []
        if entry.kind == service.BULK:
            return [n for n in ("later_all", "stop_all") if n not in entry.actions]
        return ["later", "stop_asking"]

    def more_menu(self, entry, control=None):
        """The ⋯ pressed: a plain menu in the theme's style (Esc closes it), each entry's tip shown -> the menu."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QAction
        from app.qt import drag
        m = drag.list_menu(self.cards, entry.title)
        for name in self.more_entries(entry):
            label, tip = strings.NEEDS_ACTIONS[name]
            act = QAction(label, m)
            act.setToolTip(tip)
            act.setProperty("action", name)
            act.triggered.connect(lambda _c=False, n=name, e=entry: self.act(n, e))
            m.addAction(act)
        self.last_menu = m
        if control is not None and control.isVisible():      # under the ⋯, its right edge on the ⋯'s
            m.popup(control.mapToGlobal(QPoint(control.width() - m.sizeHint().width(), control.height())))
        return m

    def _covered(self, entry):
        """The cards a line for many answers (its `keys`), and the line itself."""
        return tuple((entry.data or {}).get("keys") or ()) + (entry.key,)

    def _do_later(self, entry, _line):
        self._hide((entry.key,), service.put_off, strings.NEEDS_LATER_ONE, later=True)

    def _do_stop_asking(self, entry, _line):
        self._hide((entry.key,), service.stop_asking, strings.NEEDS_STOPPED_ONE)

    def _do_later_all(self, entry, _line):
        keys = self._covered(entry)
        self._hide(keys, service.put_off, strings.NEEDS_LATER_N.format(n=len(keys) - 1), later=True)

    def _do_stop_all(self, entry, _line):
        keys = self._covered(entry)
        self._hide(keys, service.stop_asking, strings.NEEDS_STOPPED_N.format(n=len(keys) - 1))

    def _hide(self, keys, write, said, later=False):
        """*Not now* / *Stop asking*: the cards off the page at the press (one frame — no pending mark), the seen file
        written on a worker (its one writer), a toast with Undo. A write that fails puts them back and says why."""
        day = service._today() if later else None
        for k in keys:
            self._hidden_now[k] = day
            self._landed.pop(k, None)               # (its write still to land)
        self._paint()

        def landed(_n):
            for k in keys:
                if k in self._hidden_now:
                    self._landed[k] = self._asked + 1     # the next gather reads it (one running now: its again)
            if self._alive():
                self.refresh()

        def failed(info):
            for k in keys:
                self._hidden_now.pop(k, None)
            if self._alive():
                self._paint()
            self._failed(info)
        self._seen_write(write, keys, landed, failed)
        self.win.toasts.show(said, undo=lambda: self._ask_again(keys))

    def _ask_again(self, keys):
        """Undo: the cards asked again — back at once while the page still holds them, and in the seen file (after
        the write it undoes: A4A-8)."""
        for k in keys:
            self._hidden_now.pop(k, None)
            self._landed.pop(k, None)
        self._paint()
        self._seen_write(service.ask_again, keys, lambda _n: self._alive() and self.refresh(), self._failed)

    def _seen_write(self, write, keys, then, failed):
        """(A4A-8) `write(language, keys)` on a worker after every seen-file write pressed before it — *Not now*,
        *Stop asking* and their Undo, one queue in the order pressed (the pool runs jobs side by side: an Undo that
        ran first found nothing to undo, then its write hid the card); `then(n)` / `failed(info)` on this thread."""
        self._seen_jobs.append((write, self.language, list(keys), then, failed))
        if len(self._seen_jobs) == 1:
            self._seen_next()

    def _seen_next(self):
        if not self._seen_jobs:
            return
        write, lang, keys, then, failed = self._seen_jobs[0]

        def finish(callback, value):
            self._seen_jobs.popleft()
            try:
                callback(value)
            finally:
                self._seen_next()
        bridge.run_in_worker(write, lang, keys, then=lambda n: finish(then, n),
                             failed=lambda info: finish(failed, info))

    # K1: the library mostly gone — *Start fresh* (`SourceLooks.fresh`, with Settings' own sheet)
    def _do_start_fresh(self, entry, _line):
        """*Start fresh*: Settings' *Start a fresh library?* sheet (`settings_sources.fresh_sheet`: what goes, what
        stays, the store's counts read on the looks' worker first; *Also forget my known words* off; Enter, Esc or a
        click outside is No), then `SourceLooks.fresh` on the looks' worker — the old library in one dated backup in
        the trash, never deleted — and the bar says how it went (Settings' words). The arc turns from the press while
        the counts are read, and from Yes until the reset answers."""
        from app.qt import settings_sources
        looks = getattr(self.win, "looks", None)
        if looks is None:
            self._say(strings.NEEDS_FIND_CLOSED)
            return
        p = qpress.begin(self._control("start_fresh", entry), self._press_key("start_fresh", entry), win=self.win)
        if p is None:
            return                                   # one press: its counts or its reset under way

        def ask(counts):
            if p.live():
                qpress.end(p, self.win)
                p.release()                          # (the sheet is up: its Yes presses again, or No asks again)
            if not self._alive():
                return

            def answered(yes):
                card, self.confirming = self.confirming, None
                if yes:
                    forget = bool(card is not None and card.checked)
                    self._looks_press("start_fresh", entry, lambda then: looks.fresh(forget, then))
            self.confirming = settings_sources.fresh_sheet(self.win, counts, answered)
        counts = getattr(looks, "fresh_counts", None)
        if counts is None:
            ask(None)
            return
        relay = bridge.Relay(self.win)

        def counted(found):
            relay.deleteLater()
            ask(found)
        relay.said.connect(counted)
        if not counts(relay.call):
            relay.deleteLater()
            ask(None)

    def _looks_press(self, name, entry, call):
        """`SourceLooks.fresh` on the looks' worker, its button's arc turning until it answers; the bar says how it
        went (`settings_sources.fresh_said`). Done, the card goes with the fresh library's view; refused or failed,
        it stays (pressed again, it asks again)."""
        from app.qt import settings_sources
        p = qpress.begin(self._control(name, entry), self._press_key(name, entry), win=self.win, goes=True)
        if p is None:
            return
        relay = bridge.Relay(self.win)

        def answered(answer):
            relay.deleteLater()
            answer = answer or {}
            failed = not answer.get("done")
            if p.live():
                qpress.end(p, self.win, failed=failed)
            if failed:
                self._stays(name, entry)
            self._say(settings_sources.fresh_said(answer))
            self.refresh()
        relay.said.connect(answered)
        if not call(relay.call):
            relay.deleteLater()
            qpress.end(p, self.win, failed=True)
            self._stays(name, entry)
            self._say(strings.NEEDS_FIND_CLOSED)

    # Connect's entries (each on a worker; the window never makes Connect's ledger)
    def _do_mine_anyway(self, entry, _line):
        mine, kick, lang, read_settings = (self.connect_calls["mine_anyway"], self.connect_calls.get("kick"),
                                           self.language, self.read_settings)
        need_id = entry.data["need_id"]

        def run():
            ok = mine(lang, need_id)
            if ok and kick is not None:
                kick(read_settings() or {})
            return ok
        def done(ok):
            if not ok:
                self._stays("mine_anyway", entry)
            self._connect_done(strings.NEEDS_MINE_ANYWAY if ok else strings.NEEDS_MINE_ANYWAY_NOT)
        self._press("mine_anyway", entry, run, then=done)

    def _do_ask_hato(self, entry, _line):
        backfill, lang, read_settings = self.connect_calls["ask_hato"], self.language, self.read_settings
        self._press("ask_hato", entry, lambda: backfill(lang, read_settings() or {}),
                    then=lambda _s: self._connect_done(strings.NEEDS_ASKED_HATO), goes=False)

    def _do_open_anki(self, entry, _line):
        """A3W-6: *Open Anki* on the Anki line — Anki started on Connect's profile, on a worker; the line stays until
        Connect's next look finds it open (it goes by itself)."""
        def done(started):
            self._say(strings.NEEDS_ANKI_RUNNING if started == "running" else
                      strings.NEEDS_OPENING_ANKI if started else strings.NEEDS_ANKI_NOT_STARTED)
        self._press("open_anki", entry, self.connect_calls["open_anki"], self.read_settings() or {}, then=done,
                    goes=False)

    def _do_dismiss(self, entry, _line):
        dismiss = self.connect_calls["dismiss"]
        self._press("dismiss", entry, dismiss, entry.data["need_id"],
                    then=lambda _ok: self._connect_done(strings.NEEDS_DISMISSED))

    def _connect_done(self, text):
        self._say(text)
        self.refresh()

    # P4.1's (hidden until hooked)
    def _do_make_cards(self, entry, _line):
        self.hooks["make_cards"](entry)

    # setup's first cards (SRC D1)
    def _do_first_cards(self, entry, _line):
        """*Make cards*: Connect on if it's off (as Settings › Anki's switch turns it on), then the first 20 of Current
        logged as entering the mine line by your choice, then the answer kept — all on a worker. D29's automatic
        actions off: nothing written and said why (Connect couldn't read them, and turning automation on later moves
        its watermark past them). That, or Connect not turned on: the reason said, and the line stays. Round 8 row
        45: a press (its arc turns until it is done); a second click — or *Not now* — while it goes does nothing (the
        card's one answer at a time)."""
        name = "first_cards_on" if self._control("first_cards_on", entry) is not None else "first_cards"
        if qpress.presses_of(self.win).get(self._press_key(name, entry)).live():
            return
        services_settings = self.win.services.settings
        now = services_settings.get() or {}
        if not settings_manager.automation(now):
            self._say(strings.NEEDS_FIRST_CARDS_NOT_ON.format(why=strings.NEEDS_FIRST_CARDS_AUTOMATION_OFF))
            return
        lang, data = self.language, self.data_dir
        switch_on, first_cards = self.switch_on, self.first_cards
        was_on = bool(now.get("connect_enabled"))
        switched = []                                # Connect saved on here: told on the bridge, whatever comes next

        def run():
            if not was_on:
                ok, why = switch_on(services_settings, lambda _text: None)
                if not ok:
                    return False, why
                switched.append(True)
            from app.services.settings import thaw
            first_cards(lang, thaw(services_settings.get()), data)
            service.answer(lang, [entry.key])
            return True, None

        def told():
            heard = getattr(self.win, "bridge", None)
            if switched and heard is not None and hasattr(heard, "settings_written"):
                heard.settings_written.emit(("connect_enabled",))           # the shell's Connect line, Settings' row

        def failed(info):
            told()
            self._failed(info)

        def done(answer):
            ok, why = answer
            if not ok:
                self._stays(name, entry)                 # (the reason said, the line stays)
            told()
            made = strings.NEEDS_FIRST_CARDS_MADE_ON if was_on else strings.NEEDS_FIRST_CARDS_MADE
            self._say(made if ok else strings.NEEDS_FIRST_CARDS_NOT_ON.format(why=why))
            self.refresh()
        self._press(name, entry, run, then=done, failed=failed)

    def _do_first_cards_on(self, entry, line):
        """*Make cards* with Connect already on (setup's page 5): the same, only the first 20 logged."""
        self._do_first_cards(entry, line)

    def _do_not_now(self, entry, _line):
        """*Not now*: nothing but the answer (Connect left as it is); never while *Make cards* runs. Its line as
        Connect is: off, where to turn it on; on, that later episodes still get their cards."""
        name = "not_now_on" if self._control("not_now_on", entry) is not None else "not_now"
        lang = self.language
        on = settings_manager.connect_on(self.win.services.settings.get() or {})     # B2-8: the one rule

        def done(_n):
            self._say(strings.NEEDS_FIRST_CARDS_LATER_ON if on else strings.NEEDS_FIRST_CARDS_LATER)
            self.refresh()
        self._press(name, entry, service.answer, lang, [entry.key], then=done)    # (one press per card)

    def _do_not_now_on(self, entry, line):
        self._do_not_now(entry, line)

    # Known from Anki's question (#43)
    def _do_mark_known(self, entry, _line):
        lang, settings = self.language, self.win.services.settings.get() or {}
        accept = self.accept_known

        def done(added):
            n = len(added or ())
            self._say(strings.NEEDS_KNOWN_MARKED.format(n=n) if n else strings.NEEDS_KNOWN_MARKED_NONE)
            automation = getattr(self.win.services, "automation", None)
            if n and automation is not None:
                automation.known_changed()      # as a known-words import ends: the count, the journey asked again
            self.refresh()
        self._press("mark_known", entry, accept, lang, settings, then=done)

    def _do_leave_known(self, entry, _line):
        def done(_n):
            self._say(strings.NEEDS_KNOWN_LEFT)
            self.refresh()
        self._press("leave_known", entry, self.decline_known, self.language, then=done)

    def synced(self):
        """A known-words sync ended (the automation's): Known from Anki's question may have come or gone."""
        if self._alive():
            self.refresh()

    # the failures (W3.5's)
    def _do_open_logs(self, entry, _line):
        self.win.open_logs(control=self._control("open_logs", entry), key=self._press_key("open_logs", entry))

    def _do_save_logs(self, entry, _line):
        dest = self.pick_save(strings.NEEDS_SAVE_LOGS_TITLE, "surasura-logs.zip")
        if not dest:
            return
        save = self.connect_calls["save_logs"]
        self._press("save_logs", entry, save, dest, then=lambda _n: self._say(strings.NEEDS_SAVED_LOGS.format(path=dest)),
                    goes=False)


def _accept_known(language, settings):
    """(A worker.) Known from Anki's question, accepted -> the words newly known."""
    from app import anki_connect
    from app.connect import known_signal
    return known_signal.accept_offer(language, anki_connect.address(settings))


def _decline_known(language):
    from app.connect import known_signal
    return known_signal.decline_offer(language)


def _settings_switch_on(settings, log):
    """(A worker.) Connect's switch turned on as Settings › Anki turns it on -> (ok, why)."""
    from app.qt import settings_connect
    return settings_connect._switch_on(settings, log)


def _first_cards(language, settings, data_dir=None):
    """(A worker.) The first 20 of Current logged as entering the mine line by your choice -> the ids logged."""
    from app.services import setup_wizard
    return setup_wizard.first_cards(language, settings, data_dir)


def _same(a, b):
    return a is b or (len(a) == len(b) and all(x is y for x, y in zip(a, b)))


def _reads_same(a, b):
    """Whether rows `b` hold what the entries read of rows `a` (`service.entries`: a row's group, title and kind, each
    episode's id, label, number, file and whether it is missing), in any order (C1). A row kept by the reader's cache
    is the same object, or its copy with a new place number and the same episodes: no episode is read then."""
    if len(a) != len(b):
        return False
    was = {r.key: r for r in a}
    for r in b:
        o = was.get(r.key)
        if o is r:
            continue
        if o is None or (o.work_id, o.title, o.media) != (r.work_id, r.title, r.media):
            return False
        if o.episodes is not r.episodes and [_read(e) for e in o.episodes] != [_read(e) for e in r.episodes]:
            return False
    return True


def _read(e):
    return e.id, e.label, e.number, e.rel_path, e.missing


def make_area(parent):
    """The cards in a scroll area (the page's list's place)."""
    area = QScrollArea(parent)
    area.setObjectName("needsarea")
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    cards = NeedsCards(area)
    area.setWidget(cards)
    bar = area.verticalScrollBar()                  # alpha 4 B: the next cards as the page nears its end
    bar.valueChanged.connect(cards.scrolled)
    bar.rangeChanged.connect(cards.scrolled)
    area.viewport().setAutoFillBackground(False)
    cards.setAutoFillBackground(False)
    return area, cards

