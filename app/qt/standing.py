"""Standing lines painted (round 8 row 54; the scope `row45-54-scope.md` §4): the ✕ every standing line carries, and the
line itself where it is a row of its own. What a line's key is, and how long ✕ hides it, is `app/services/standing.py`.

Sonic (Q1): never grey anything; as few words as possible; subtle, clean, theme-looking. So the ✕ is a small mark in
the line's own quiet colour (`#standingclose`, the theme's), its words only in its hover. **Nothing moves:** the ✕ keeps
its room while its line shows, so the line's words stay where they are; a line it hides goes as it would have gone by
itself (the bar's slot shows its next part in the same place). Esc is unchanged: a ✕ is a button, never an overlay.

- `Cross(parent)`: the ✕. The bar's failure line and the update chip carry one beside them, shown with them
  (`ShellWindow._paint_slot`).
- `StandingLine(name)`: a line as a row — its words (a `QLabel` named `name`), up to two answers (`add_answer`: chips),
  then its ✕. `dismissed` (✕) and `answered(name)` say what was pressed; the owner records the key and hides it.
  The offline line (`ShellWindow.offline_line`) and each page's state bar (`screens.StateBar`) are one.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from app.qt import strings


class Cross(QToolButton):
    """The ✕: hides its line until its state changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("standingclose")
        self.setText(strings.STANDING_HIDE)
        self.setToolTip(strings.STANDING_HIDE_TIP)
        self.setAccessibleName(strings.STANDING_HIDE_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class StandingLine(QWidget):
    """A standing line as a row: its words, its answers, its ✕. `fill`: the words take the row's width (a page's
    state bar, its ✕ at the right end); else the answers and the ✕ follow the words (the offline line)."""
    dismissed = pyqtSignal()
    answered = pyqtSignal(str)

    def __init__(self, name, parent=None, fill=False, margins=(0, 0, 0, 0)):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(*margins)
        row.setSpacing(8)
        self.label = QLabel(self)
        self.label.setObjectName(name)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setMinimumWidth(1)                 # a long path is cut, never the window widened
        row.addWidget(self.label, 1 if fill else 0)
        self.answers = {}
        self.cross = Cross(self)
        self.cross.clicked.connect(lambda _c=False: self.dismissed.emit())
        row.addWidget(self.cross, 0, Qt.AlignmentFlag.AlignVCenter)
        if not fill:
            row.addStretch(1)
        self.setVisible(False)

    def add_answer(self, name, words, tip):
        """An answer before the ✕ (a chip: its words, its hover) -> the button. Pressed: `answered(name)`."""
        button = QPushButton(words, self)
        button.setProperty("kind", "chip")
        button.setToolTip(tip)
        button.setAccessibleName(words)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda _c=False, n=name: self.answered.emit(n))
        row = self.layout()
        row.insertWidget(row.indexOf(self.cross), button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.answers[name] = button
        return button

    def text(self):
        return self.label.text()

    def show_line(self, text, closable=True):
        """Its words (none: the line hidden); `closable`: its ✕ and answers shown (a line of work running has none).
        Each part touched only when it changed (S19)."""
        if self.label.text() != text:
            self.label.setText(text)
            self.label.setAccessibleName(text)
        closable = bool(text) and closable
        for part in (self.cross, *self.answers.values()):
            if part.isHidden() == closable:
                part.setVisible(closable)
        if self.isHidden() == bool(text):
            self.setVisible(bool(text))
