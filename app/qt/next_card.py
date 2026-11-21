"""The Next card on Current (Hoshi-S PR 2, Kantan-X's model: the 3.0 planning folder's
`tracks/window/work/experience-2026-11-12/EXPERIENCE.md` §3, mocks 1 and 2; Mado-EZP's four stages, SPEC-r2 EZ2-1 /
§0.2 — every learner-visible choice PROVISIONAL). One slim card above Up Next (the strip the page's state bar uses: Up
Next is the painted list's first row, so the card sits just above it), one step at a time, from the path
(`app/services/path.py`): what to do, its one line of why behind a ? beside it (Kantan-S2, Sonic 2026-11-13: no
subtitles — `tooltip.AboutMark`), **the step's own press**, **Show me** and **Not now**.

- **The stage string** (`Stages`): the path's four stages — ① On board · ② First episode · ③ Automate · ④ Make it
  yours — as four stones from the rows' own sheet (`stones.Sheet`, never an SVG: a cut sapphire done, the next
  stone's rock with its cyan ring now, a small rock later), on the string's hairline, under *NEXT · <stage>*.
- **Every step acts from the card** (§0.2, Sonic: the first steps sent him to buttons up top): its primary does the
  step itself, or opens the thing it acts on in place — *Open Ep 3's words ↗*, *▶ Watch Ep 3* + *✓ Done*, *Make …'s
  cards* … The shell names them (`set_card(card, presses)`: (key, words, hover) each, from what it shows) and runs
  them (`act(key, control)`). **Show me** only lights where the same press lives, for next time — it never presses
  anything (`show_me(where)`); a later step outside the stages has none (its press goes to that place itself).
- Chapter 1's *Not now* hides the card until the next start; *Cards made for you* also offers **I make my own cards**
  (answered for good). Then *✓ Your first cards are made* once, with **OK**; then a later step only when it has become
  useful (*NEW FOR YOU*, or its stage), whose *Not now* is for good (it stays in ✦ → *Your path*).
- **It decides nothing** (the path does) and reads nothing: its presses are signals (`act`, `show_me`, `not_now`,
  `own_cards`, `made_ok`) the shell answers. Repainted only when what it shows changed (S19); hidden while setup runs
  (the shell's call).
"""
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app import theme
from app.qt import rows, stones, strings, style
from app.qt.tooltip import AboutMark, FitTitle
from app.services import path as path_service

STONE_GAP = 28                      # px between two stones' centres on the stage string (room for the now stone's ring)
STONE_PAD = 15                      # px from the edge to the first / last stone's centre (half the ring and a hair)
STONE_SEED = 1                      # one variant for every stone of the string (a picture of the stages, not files)


def stone_of(state):
    """The sheet's picture for a stage in `state` (a path `DONE` · `NOW` · `LATER`)."""
    if state == path_service.DONE:
        return ("stone", "cut", "sapphire", STONE_SEED, "watched")
    return ("stone", "rock", "sapphire", STONE_SEED, "next" if state == path_service.NOW else "waiting")


class Stages(QWidget):
    """The four stages as a string of stones (`set_states(states)`: the path's `stage_states`; () paints nothing).
    Drawn from the stones' sheet once it is there (until then nothing, as a row's string; it repaints when it lands)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.states = ()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(STONE_GAP * 3 + 2 * STONE_PAD, 2 * STONE_PAD)
        self.setAccessibleName("")
        stones.notifier().ready.connect(self._sheet_ready)   # (the sheet landed: paint the stones)

    def _sheet_ready(self, _key):
        if self.states:
            self.update()

    def set_states(self, states):
        states = tuple(states or ())
        if states == self.states:
            return False
        self.states = states
        names = [strings.PATH_STAGE_NAME.format(stage=strings.PATH_STAGES[s], state=strings.PATH_STAGE_STATES[st])
                 for s, st in zip(path_service.STAGES, states)]
        self.setAccessibleName(strings.PATH_STRING_NAME.format(stages=", ".join(names)) if states else "")
        self.update()
        return True

    def paintEvent(self, _event):
        if not self.states:
            return
        dpr = self.devicePixelRatioF() or 1.0
        sheet = stones.get(dpr, style.current()[1])
        if sheet is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mid = self.height() / 2
        x0 = float(STONE_PAD)
        p.fillRect(QRectF(x0, mid - 0.5, STONE_GAP * (len(self.states) - 1), 1),
                   rows.c("string"))                # (the rows' hairline: a row token)
        for n, state in enumerate(self.states):
            at = QPointF(x0 + n * STONE_GAP, mid)
            what = stone_of(state)
            if what in sheet:
                sheet.draw(p, at, what)
            if state == path_service.NOW and ("ring", "next") in sheet:
                sheet.draw(p, at, ("ring", "next"))
        p.end()


class NextCard(QWidget):
    """The card. `set_card(card, presses)`: the path's `next_card` answer (None hides it) and the step's own presses
    ((key, words, hover) each, the shell's). -> True when it changed."""
    act = pyqtSignal(str, object)                   # (press key, the button pressed): the shell runs the step's press
    show_me = pyqtSignal(str)                       # the place to light (only a look)
    not_now = pyqtSignal(str)
    own_cards = pyqtSignal()
    made_ok = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nextcard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(strings.NEXT_NAME)
        self.card = None
        self.presses = ()
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
        self.stages = Stages(self)
        lead.addWidget(self.stages)
        row.addLayout(lead)
        words = QHBoxLayout()                              # the title, then its ? (its line behind it: Kantan-S2)
        words.setSpacing(round(6 * f))
        self.title = FitTitle("", self)
        self.title.setObjectName("nexttitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        words.addWidget(self.title, 1000, Qt.AlignmentFlag.AlignVCenter)
        self.about = AboutMark(strings.HELP_MARK, self)
        words.addWidget(self.about, 0, Qt.AlignmentFlag.AlignVCenter)
        words.addStretch(1)
        row.addLayout(words, 1)
        self.primary = self._button(row, "primary")       # the step's own press
        self.primary2 = self._button(row, None)            # its second (② *✓ Done* beside *▶ Watch*)
        self.show_button = self._button(row, "link")       # *Show me*: only a look
        self.secondary = self._button(row, "link")         # *Not now* (③'s cards: *I make my own cards*)
        self.later = self._button(row, "link")             # the cards step's *Not now* (beside *I make my own cards*)
        self._set(self.show_button, strings.NEXT_SHOW_ME, strings.NEXT_SHOW_ME_TIP)
        self._set(self.later, strings.NEXT_NOT_NOW, strings.NEXT_NOT_NOW_TIP)
        self.primary.clicked.connect(lambda _c=False: self._press(0, self.primary))
        self.primary2.clicked.connect(lambda _c=False: self._press(1, self.primary2))
        self.show_button.clicked.connect(lambda _c=False: self._show())
        self.secondary.clicked.connect(lambda _c=False: self._secondary())
        self.later.clicked.connect(lambda _c=False: self.card and self.not_now.emit(self.card[1]))
        for b in (self.primary2, self.show_button, self.later):
            b.hide()
        self.hide()

    def _button(self, row, kind):
        b = QPushButton("", self)
        if kind:
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

    def set_card(self, card, presses=()):
        """Paint the path's choice (None: hidden) with its presses. The same again changes nothing (S19)."""
        presses = tuple(presses or ())
        if card == self.card and presses == self.presses:
            return False
        self.card, self.presses = card, presses
        if card is None:
            self.hide()
            return True
        if card[0] == "made":
            self.setProperty("look", "made")
            self.eyebrow.setText(strings.NEXT_MADE)
            self.stages.set_states(())
            self.stages.hide()
            self.title.setText(strings.NEXT_MADE_WHERE)       # where later steps wait: a place, in sight (r1 #3)
            line = strings.NEXT_MADE_LINE
            self._set(self.primary, strings.NEXT_OK, strings.NEXT_OK_TIP)
            self.primary.show()                               # (a step with no press of its own hid it)
            for b in (self.primary2, self.show_button, self.secondary, self.later):
                b.hide()
        else:
            _kind, step_id, states = card
            step = path_service.BY_ID[step_id]
            title, line = strings.PATH_STEPS[step_id]
            self.setProperty("look", "step")
            self.eyebrow.setText(strings.NEXT_STAGE.format(stage=strings.PATH_STAGES[step.stage].upper())
                                 if step.stage is not None and states else strings.NEXT_READY)
            self.stages.set_states(states)
            self.stages.setVisible(bool(states))
            self.title.setText(title)
            for button, press in ((self.primary, presses[0] if presses else None),
                                  (self.primary2, presses[1] if len(presses) > 1 else None)):
                if press is not None:
                    self._set(button, press[1], press[2])
                button.setVisible(press is not None)
            self.show_button.setVisible(step.stage is not None)       # a later step's press goes to its place itself
            if step_id == "cards":
                self._set(self.secondary, strings.NEXT_OWN_CARDS, strings.NEXT_OWN_CARDS_TIP)
            else:
                self._set(self.secondary, strings.NEXT_NOT_NOW, strings.NEXT_NOT_NOW_TIP)
            self.secondary.show()
            self.later.setVisible(step_id == "cards")
        self.title.show()
        self.about.set_about(strings.NEXT_ABOUT_NAME, line)
        self.setAccessibleDescription(" ".join(t for t in (self.eyebrow.text(), self.title.text(), line) if t))
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        self.update()
        return True

    def _press(self, n, button):
        card = self.card
        if card is None:
            return
        if card[0] == "made":
            if n == 0:
                self.made_ok.emit()
            return
        if n < len(self.presses):
            self.act.emit(self.presses[n][0], button)

    def _show(self):
        card = self.card
        if card is not None and card[0] == "step":
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
