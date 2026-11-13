"""The Next card on Current (Hoshi-S PR 2, Kantan-X's model: the 3.0 planning folder's
`tracks/window/work/experience-2026-11-12/EXPERIENCE.md` §3, mocks 1 and 2 — every learner-visible choice
PROVISIONAL). One slim card above Up Next (the strip the page's state bar uses: Up Next is the painted list's first row,
so the card sits just above it), one step at a time, from the path (`app/services/path.py`): what to do, one line of
why, **Show me** and **Not now**.

- **Chapter 1** (*NEXT · n of 3 to your first cards*, three dots): its first undone step. *Not now* hides it until the
  next start. Step 3 offers **Set up Anki Miner** (its Show me) and **I make my own cards** (step 3 answered for good).
- **Then** *✓ Your first cards are made* once, with **OK**; then a chapter-2 step only when it has become useful (*NEW
  FOR YOU*), whose *Not now* is for good (it stays in ✦ → *Your path*).
- **It decides nothing** (the path does) and reads nothing: `set_card(card)` paints the path's choice; its presses are
  signals (`show_me(where)`, `not_now(step_id)`, `own_cards()`, `made_ok()`) the shell answers, writes on a worker.
  Repainted only when the card it shows changed (S19); hidden while setup runs (the shell's call).
"""
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app import theme
from app.qt import strings, style
from app.qt.frame import _iris
from app.services import path as path_service


class _Dots(QWidget):
    """Three dots under the eyebrow: the steps done, lit in the iris; the rest in the line colour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.n, self.total = 0, 0
        f = theme.text_factor(style.current()[1])
        self.setFixedHeight(round(8 * f))
        self.setFixedWidth(round(36 * f))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_count(self, n, total):
        if (n, total) != (self.n, self.total):
            self.n, self.total = n, total
            self.update()

    def paintEvent(self, _event):
        if not self.total:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        side = self.height() * 0.75
        gap = (self.width() - side * self.total) / max(1, self.total - 1)
        line = style.qcolor(style.colours()["line-hi"])
        for i in range(self.total):
            r = QRectF(i * (side + gap), (self.height() - side) / 2, side, side)
            p.setBrush(_iris(r.left(), r.right()) if i < self.n else line)
            p.drawEllipse(r)
        p.end()


class NextCard(QWidget):
    """The card. `set_card(card)`: the path's `next_card` answer (None hides it). -> True when it changed."""
    show_me = pyqtSignal(str)
    not_now = pyqtSignal(str)
    own_cards = pyqtSignal()
    made_ok = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nextcard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(strings.NEXT_NAME)
        self.card = None
        self.paints = 0
        f = theme.text_factor(style.current()[1])
        row = QHBoxLayout(self)
        row.setContentsMargins(round(16 * f), round(10 * f), round(12 * f), round(10 * f))
        row.setSpacing(round(14 * f))
        lead = QVBoxLayout()
        lead.setSpacing(round(4 * f))
        self.eyebrow = QLabel("", self)
        self.eyebrow.setObjectName("nexteyebrow")
        lead.addWidget(self.eyebrow)
        self.dots = _Dots(self)
        lead.addWidget(self.dots)
        row.addLayout(lead)
        words = QVBoxLayout()
        words.setSpacing(round(2 * f))
        self.title = QLabel("", self)
        self.title.setObjectName("nexttitle")
        self.line = QLabel("", self)
        self.line.setObjectName("nextline")
        for label in (self.title, self.line):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            words.addWidget(label)
        row.addLayout(words, 1)
        self.primary = self._button(row, "primary")
        self.secondary = self._button(row, "link")
        self.later = self._button(row, "link")             # step 3's *Not now* (beside *I make my own cards*)
        self._set(self.later, strings.NEXT_NOT_NOW, strings.NEXT_NOT_NOW_TIP)
        self.primary.clicked.connect(lambda _c=False: self._primary())
        self.secondary.clicked.connect(lambda _c=False: self._secondary())
        self.later.clicked.connect(lambda _c=False: self.card and self.not_now.emit(self.card[1]))
        self.later.hide()
        self.hide()

    def _button(self, row, kind):
        b = QPushButton("", self)
        b.setProperty("kind", kind)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setAutoDefault(False)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        return b

    @staticmethod
    def _set(button, text, tip):
        button.setText(text)
        button.setToolTip(tip)
        button.setAccessibleName(text)

    def set_card(self, card):
        """Paint the path's choice (None: hidden). The same choice again changes nothing (S19)."""
        if card == self.card:
            return False
        self.card = card
        if card is None:
            self.hide()
            return True
        if card[0] == "made":
            self.setProperty("look", "made")
            self.eyebrow.setText(strings.NEXT_MADE)
            self.dots.set_count(0, 0)
            self.dots.hide()
            self.title.hide()
            self.line.setText(strings.NEXT_MADE_LINE)
            self._set(self.primary, strings.NEXT_OK, strings.NEXT_OK_TIP)
            self.secondary.hide()
            self.later.hide()
        else:
            _kind, step_id, n, total = card
            title, line = strings.PATH_STEPS[step_id]
            self.setProperty("look", "step")
            self.eyebrow.setText(strings.NEXT_FIRST.format(n=n, total=total) if total else strings.NEXT_READY)
            self.dots.set_count(n - 1 if total else 0, total)
            self.dots.setVisible(bool(total))
            self.title.setText(title)
            self.title.show()
            self.line.setText(line)
            if step_id == "cards":
                self._set(self.primary, strings.NEXT_SET_UP_MINER, strings.NEXT_SET_UP_MINER_TIP)
                self._set(self.secondary, strings.NEXT_OWN_CARDS, strings.NEXT_OWN_CARDS_TIP)
            else:
                self._set(self.primary, strings.NEXT_SHOW_ME, strings.NEXT_SHOW_ME_TIP)
                self._set(self.secondary, strings.NEXT_NOT_NOW, strings.NEXT_NOT_NOW_TIP)
            self.secondary.show()
            self.later.setVisible(step_id == "cards")
        self.setAccessibleDescription(" ".join(t for t in (self.eyebrow.text(), self.title.text() if
                                                             self.title.isVisible() else "", self.line.text()) if t))
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        self.update()
        return True

    def _primary(self):
        card = self.card
        if card is None:
            return
        if card[0] == "made":
            self.made_ok.emit()
            return
        self.show_me.emit(path_service.BY_ID[card[1]].where)

    def _secondary(self):
        card = self.card
        if card is None or card[0] == "made":
            return
        if card[1] == "cards":
            self.own_cards.emit()
        else:
            self.not_now.emit(card[1])

    def paintEvent(self, event):
        self.paints += 1
        super().paintEvent(event)
