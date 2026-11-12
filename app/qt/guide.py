"""The feature guide's window parts (Hoshi-S, Sonic 2026-11-12, part of the launch; spec: the 3.0 planning folder,
`tracks/window/work/feature-guide-2026-11-12/SPEC.md`, every learner-visible choice PROVISIONAL). The rules are Qt-free
(`app/services/guide.py`); this paints what it says.

- **The ✦** (`GuideButton`) in the header, just left of the ?: the header's own button look; while something is unseen
  it carries the theme's glow (`theme.GLOW`'s ring on the accent wash) and a small iris dot — painted once, **still**
  (no loop on the clock: S19, a laptop's battery). The glow goes the moment the panel opens.
- **The panel** (`GuidePanel`): a pop under the ✦ (the level ▾'s way: slate navy, its lit top edge; Esc, Back, a press
  elsewhere and the ✦ again close it), the tray's width, scrolling inside past the window's height. Sonic: "everything
  earns its place" — *What's new in 3.0.4* (one release; several: each its version line), then one plain line an item:
  the learner's own first (*For you* above them only when others follow), each something to try with **Show me**
  (`show_me`, its `where`: the shell goes there and washes it); the rest folded into *N fixes and small changes*
  (Kantan-X's rule 2). No Done tab (rule 3); *Your path* joins as a second tab with the path (PR 2).
- **Built when the look changes, never on an open** (R5): `set_look` rebuilds only for a new answer; an open with the
  same answer makes no widget. Nothing here reads a file: the shell asks the service on a worker.
"""
import collections
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from app import theme
from app.qt import motion, shadow, strings, style
from app.qt.frame import _Away, _iris

EDGE = 8                            # px the panel keeps from the window's edges
FIRST_LOOK_MS = 3000                # the first look, this long after the duties start (never on the start's path)
SLICES_KEPT = 64                    # the last pieces' times kept (tests: the largest slice ≤ 4 ms)


def release_name(release):
    """'Surasura 3.0.4 · 12 Nov' (the date as the notes give it, `YYYY-MM-DD`; an odd one is left out)."""
    try:
        _y, m, d = (int(p) for p in release.date.split("-"))
        when = f"{d} {strings.GUIDE_MONTHS[m - 1]}"
    except (ValueError, IndexError, AttributeError):
        when = ""
    if not when:
        return strings.GUIDE_RELEASE_NO_DATE.format(version=release.version)
    return strings.GUIDE_RELEASE.format(version=release.version, date=when)


class GuideButton(QToolButton):
    """The header's ✦. `set_glow(on)` -> True when it changed (a repaint only then)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("headguide")
        self.setText(strings.GUIDE_MARK)
        self.setToolTip(strings.GUIDE_TIP)
        self.setAccessibleName(strings.GUIDE_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.glow = False
        self.paints = 0

    def set_glow(self, on):
        on = bool(on)
        if on == self.glow:
            return False
        self.glow = on
        self.setAccessibleName(strings.GUIDE_GLOW_NAME if on else strings.GUIDE_NAME)
        self.setProperty("glow", "true" if on else "false")
        self.style().unpolish(self)                         # (the ✦ in full ink while it glows: the sheet's rule)
        self.style().polish(self)
        self.update()
        return True

    def paintEvent(self, event):
        self.paints += 1
        if not self.glow:
            return super().paintEvent(event)
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.RADII["icon-button"]
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, style.qcolor(c["accent-wash"]))
        ring = theme.GLOW.get(style.current()[0], theme.GLOW[theme.DEFAULT_THEME])[0]
        p.setPen(QPen(style.qcolor(ring), 1.0))
        p.drawPath(path)
        p.end()
        super().paintEvent(event)                          # the ✦ itself, the header's look (its focus ring too)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = theme.text_factor(style.current()[1])
        side = 6 * f
        dot = QRectF(self.width() - side - 3, 3, side, side)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_iris(dot.left(), dot.right()))
        p.drawEllipse(dot)
        p.end()


class _Card(QWidget):
    """One item: its one plain line and, when it is something to try, *Show me*. A folded one is a quiet line alone."""

    def __init__(self, item, on_show, parent=None, folded=False):
        super().__init__(parent)
        self.setObjectName("guidefix" if folded else "guidecard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.item = item
        f = theme.text_factor(style.current()[1])
        row = QHBoxLayout(self)
        row.setContentsMargins(round(12 * f), round(8 * f), round(8 * f), round(8 * f))
        row.setSpacing(round(10 * f))
        self.text = QLabel(item.text, self)
        self.text.setObjectName("guidetext")
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        row.addWidget(self.text, 1)
        self.show_me = None
        if item.where and not folded:
            b = QPushButton(strings.GUIDE_SHOW_ME, self)
            b.setObjectName("guideshow")
            b.setToolTip(strings.GUIDE_SHOW_ME_TIP)
            b.setAccessibleName(strings.GUIDE_SHOW_ME_NAME.format(text=item.text))
            b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, w=item.where: on_show(w))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.show_me = b
        self.setAccessibleName(item.text)


class GuidePanel(motion.Overlay):
    """The ✦'s panel. `set_look(look)` paints a `guide.Look`; `show_me` carries a place (`where`) to the shell, which
    closes nothing itself — the panel closes first. `opened` tells the shell the panel opened (the glow ends, the look
    is asked again on a worker)."""
    how = "pop"
    shadow_name = "menu"
    focus = True
    show_me = pyqtSignal(str)
    opened = pyqtSignal()

    def __init__(self, parent, button):
        super().__init__(parent)
        self.button = button
        self.setObjectName("guidepanel")
        self.setAccessibleName(strings.GUIDE_PANEL_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        f = self._f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        box.setContentsMargins(round(14 * f), round(12 * f), round(14 * f), round(14 * f))
        box.setSpacing(round(8 * f))
        self.heading = QLabel(strings.GUIDE_HEADING, self)
        self.heading.setObjectName("popheading")
        box.addWidget(self.heading)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("guidescroll")
        self.scroll.setWidgetResizable(False)              # (sized here, by its wrapped lines: `place`)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.TabFocus)     # (its arrows and Page keys read every line)
        box.addWidget(self.scroll, 1)
        self.body = None
        self.look = None                    # the guide.Look shown
        self._waiting = None                # a newer one, kept while the panel is open
        self.cards = []
        self.folds = []                     # (button, [fix cards], n)
        self.builds = 0                     # the body made (tests: once per new look, never per open)
        self._token = 0                     # which body the pieces on their way are for
        self._pieces = collections.deque()  # the body's pieces still to make, one a turn
        self.slices = []                    # each piece's time on the GUI thread, ms (the last SLICES_KEPT)
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        parent.installEventFilter(self)
        self.hide()

    # --- what it shows --------------------------------------------------------------------------------------------- #
    def set_look(self, look):
        """Paint `look` (a `guide.Look`). The same releases again change nothing (S19: the glow alone isn't the
        panel's); while the panel is open a new answer waits for it to close — what the learner reads never changes
        under them. -> True when rebuilt."""
        if self.isVisible() or motion.opening_of(self) is not None:
            self._waiting = look
            return False
        self._waiting = None
        same = self.look is not None and look is not None and look.releases == self.look.releases
        self.look = look
        if same:
            return False
        self._build()
        if self.isVisible():
            self.place()
        return True

    def has_news(self):
        return bool(self.look is not None and self.look.releases)

    def _build(self):
        """A new answer's body, **one piece per event-loop turn** (the lead, 2026-11-12: the 4 ms rule strict — a whole
        release built at once took 3.3–4.8 ms at 100–200 %): the empty body at once, then each line, card and fold
        piece in a turn of its own (`_step`). A newer answer cancels the pieces still to come; the panel places itself
        once the last lands. `builds` counts finished bodies."""
        f = self._f
        self._token += 1
        body = QWidget()
        body.setObjectName("guidebody")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, round(2 * f), 0)
        col.setSpacing(round(6 * f))
        self.cards, self.folds = [], []
        releases = self.look.releases if self.look else ()
        self.heading.setText(strings.GUIDE_HEADING_ONE.format(version=releases[0].release.version)
                             if len(releases) == 1 else strings.GUIDE_HEADING)
        pieces = []

        def label(name, text):
            pieces.append(lambda: col.addWidget(self._label(name, text, body)))

        def card(item, folded=False, into=None):
            def make():
                c = _Card(item, self._show, body, folded=folded)
                if folded:
                    c.setVisible(False)
                    into[1].append(c)
                self.cards.append(c)
                col.addWidget(c)
            pieces.append(make)

        def fold(entry):
            def make():
                b = QPushButton("", body)
                b.setObjectName("guidefold")
                b.setProperty("kind", "link")
                b.setToolTip(strings.GUIDE_FIXES_TIP)
                b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                b.setAutoDefault(False)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                col.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
                entry[0] = b
                self.folds.append(entry)
                b.clicked.connect(lambda _c=False, e=entry: self._fold(e))
            pieces.append(make)

        for shown in releases:
            if len(releases) > 1:                          # (one release: its version is the heading's)
                label("guidever", release_name(shown.release))
            if shown.for_you and shown.others:             # "For you" only where it explains the order
                label("guidegroup", strings.GUIDE_FOR_YOU)
            for n, item in enumerate(shown.for_you + shown.others):
                if n == len(shown.for_you) and shown.for_you:
                    pieces.append(lambda: col.addSpacing(round(6 * f)))
                card(item)
            if shown.fixes:
                entry = [None, [], False]
                fold(entry)
                for item in shown.fixes:
                    card(item, folded=True, into=entry)
                pieces.append(lambda e=entry: self._fold_words(e))
        pieces.append(lambda: col.addStretch(1))
        old, self.body = self.body, body
        self.scroll.setWidget(body)                        # (the old body is the scroll area's to delete)
        del old
        self._pieces = collections.deque(pieces)
        self._next_piece(self._token)

    def building(self):
        """Whether a body's pieces are still on their way."""
        return bool(self._pieces)

    def _next_piece(self, token):
        QTimer.singleShot(0, lambda: self._step(token))

    def _step(self, token):
        """One piece of the body (`_build`), timed; the next in the next turn."""
        if sip.isdeleted(self) or token != self._token or not self._pieces:
            return
        t0 = time.perf_counter()
        self._pieces.popleft()()
        done = not self._pieces
        if done:
            self.builds += 1
            if self.isVisible():
                self.place()
        self.slices.append((time.perf_counter() - t0) * 1000)
        del self.slices[:-SLICES_KEPT]
        if not done:
            self._next_piece(token)

    def _label(self, name, text, parent):
        label = QLabel(text, parent)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _fold_words(self, entry):
        fold, fixes, open_ = entry
        n = len(fixes)
        if open_:
            words = strings.GUIDE_FIXES_OPEN_ONE if n == 1 else strings.GUIDE_FIXES_OPEN.format(n=n)
        else:
            words = strings.GUIDE_FIXES_ONE if n == 1 else strings.GUIDE_FIXES.format(n=n)
        fold.setText(words)
        fold.setAccessibleName(words)

    def _fold(self, entry):
        entry[2] = not entry[2]
        for card in entry[1]:
            card.setVisible(entry[2])
        self._fold_words(entry)
        self.place()

    def _show(self, where):
        self.close()
        self.show_me.emit(where)

    # --- opening, closing ------------------------------------------------------------------------------------------ #
    def place(self):
        """Under the ✦, its right edge on the ✦'s, kept inside the window; as tall as its content up to the window's
        room, then it scrolls. The body is sized here to its lines wrapped at its width (a scroll area sizing it by
        its hints showed a bar where none was needed): the bar only when the content passes the room."""
        p = self.parentWidget()
        self.ensurePolished()
        width = min(round(theme.size("tray", style.current()[1])), max(1, p.width() - 2 * EDGE))
        lay = self.layout()
        m = lay.contentsMargins()
        inner = max(1, width - m.left() - m.right())
        b = self.button
        at = b.mapTo(p, b.rect().bottomRight())
        top = at.y() + 6
        head = self.heading.sizeHint().height() + lay.spacing() + m.top() + m.bottom()
        room = max(1, p.height() - top - EDGE)
        body_w, want = inner, 0
        if self.body is not None:
            want = self._content_height(inner)
            if head + want > room:                         # it scrolls: the bar takes its width from the lines
                body_w = max(1, inner - self.scroll.verticalScrollBar().sizeHint().width())
                want = self._content_height(body_w)
            self.body.resize(body_w, want)
        height = min(head + want, room)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if head + want > room
                                               else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(max(1, height - head))
        x = max(EDGE, min(at.x() - width, p.width() - width - EDGE))
        geometry = QRect(x, top, width, height)
        if geometry != self.geometry():
            self.setGeometry(geometry)

    def _content_height(self, width):
        """The body's height at `width`: each shown row's own height for that width, its lines wrapped as they will
        be."""
        col = self.body.layout()
        m = col.contentsMargins()
        width = max(1, width - m.left() - m.right())
        total, shown = m.top() + m.bottom(), 0
        for n in range(col.count()):
            entry = col.itemAt(n)
            w = entry.widget()
            if w is not None:
                if w.isHidden():
                    continue
                w.ensurePolished()
                total += w.heightForWidth(width) if w.hasHeightForWidth() else w.sizeHint().height()
                shown += 1
            elif entry.spacerItem() is not None:
                total += entry.spacerItem().sizeHint().height()
        return total + col.spacing() * max(0, shown - 1)

    def open(self):
        self.place()
        return super().open()

    def toggle(self):
        if self.isVisible() or motion.opening_of(self) is not None:
            self.close()
        else:
            self.open()

    def focusNextPrevChild(self, next_):
        """Tab and Shift+Tab go round the panel's own buttons (the window behind keeps its order)."""
        ring = [self.scroll] + [b for b in self.findChildren(QPushButton) if b.isVisible() and b.isEnabled()]
        if not ring:
            return True
        now = QApplication.focusWidget()
        i = ring.index(now) if now in ring else -1
        target = ring[(i + (1 if next_ else -1)) % len(ring)]
        target.setFocus(Qt.FocusReason.TabFocusReason)
        self.scroll.ensureWidgetVisible(target)
        return True

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)
        self.opened.emit()

    def hideEvent(self, event):
        held = self.isAncestorOf(QApplication.focusWidget()) if QApplication.focusWidget() is not None else False
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)
        if held and self.button.isVisible():
            self.button.setFocus(Qt.FocusReason.OtherFocusReason)    # (the keyboard back where it opened the panel)
        if self._waiting is not None:
            self.set_look(self._waiting)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def sizeHint(self):
        return QSize(round(theme.size("tray", style.current()[1])), super().sizeHint().height())

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["tray"])
        p.end()
