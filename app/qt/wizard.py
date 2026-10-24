"""The setup wizard (W3.5 part 3; the signed draft `wizard-draft/WIZARD-DRAFT.md` + its pictures, WZ-1…WZ-7, RS-7;
the window's spec 05 §5.8; the contract `w35wiz/contract.md`).

Six pages inside the window — *Your language · What you know · Your shows · Card order · Cards made for you · Your list* —
each a picture that says what you get, a title that says the benefit, at most one short line, and its choices with the
recommended one already chosen, so most people just press *Next* (Enter). The frame: the header (the mark, *Surasura*,
*Finish later*), the step list on the left (words only; the iris vein beside where you are, ✓ on the steps passed), the
footer (*Back* · *Skip* · *Next*; page 1 has neither *Back* nor *Skip*; page 6's *Next* reads **Generate**).

**It decides nothing:** every rule is `app/services/setup_wizard.py`'s (the writes, the preselects, the Anki look, the
first sync, the library's rows, the level's numbers, Generate) and `app/services/anki_miner_setup.py`'s (Anki Miner's
state and its install route). This module paints their answers and asks them on workers (`bridge.run_in_worker`); the
GUI thread never waits.

- **Saving:** each page saves its own keys on *Next* (`setup_wizard.save`, one `set` call), nothing earlier; *Skip*
  writes nothing; *Back* keeps the choices (the pages keep their state). Page 2's *From Anki* starts the first
  known-words sync (an `anki-sync` job, the user's own act): its result goes to the window's bar and the wizard's
  footer, and never holds the page. Page 5 writes only when Anki Miner is ready (otherwise *Next* goes on as *Skip*
  does). Page 6's **Generate** saves the level, writes `onboarding_completed` (`finish`), asks the window's Generate and
  closes onto Current when that run ends; its *Skip* finishes without Generate. *Finish later* writes nothing more.
- **Keys:** Tab between groups; ← → within a choice channel (one Tab stop each) and on the level; Space toggles a switch;
  Enter is *Next* / **Generate** (on a page that can't go on — Anki not open on *Card order* — Enter is *Skip*), by the
  wizard's own key handling: no button is a default one, and Enter on another button (*Skip*, *Back*, *Finish later*,
  *Check again*…) does nothing — those act on Space or a click, as themselves. **One action per press:** a held key's
  repeats are no presses, and *Next* / *Skip* take a press only once the page shown was painted and a double click's
  time has gone since it came up (`settled`), so a double click or a quick second Enter never saves a page unseen —
  page 4's consent among them. **Esc
  does nothing here** (WZ-6): the wizard registers no overlay, so the shell's `EscapeRouter` hands Esc on and the main
  window is never closed; the mouse's Back button is the router's too.
- **Looks:** every colour from `app/theme.py` through `style` (no literal); the pictures are painted. Each painted part
  repaints only when what it shows changed (S19). A page change is instant: `app/qt/motion.py` offers no light-up for
  a page (the tab switch has none to borrow), so nothing fades; a switch's gem slides on the one clock (reduced motion:
  it jumps).
"""
import math
import os
import re
import threading
import time
from functools import lru_cache

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLayout,
                             QBoxLayout, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from app import path_utils, settings_manager, theme
from app.qt import applog, bridge, confirm, motion, strings, style, windows
from app.qt import wizard_strings as S
from app.services import tools_found

PAGES = ("language", "known", "shows", "order", "cards", "level")      # the contract's ids, in order
BUSY = ("queued", "running", "cancelling")      # a Generate under way (`generate.QUEUED` / `RUNNING` / `CANCELLING`)
ROWS_SHOWN = 6                                  # page 3's rows; the rest are "and N more"
ADD_ACTIONS = ("files", "folder", "extract", "youtube")     # W3.2 Q3: page 3's add actions, + Add's (IK-12)
ADD_DOORS = {"extract": "extract", "youtube": "youtube-downloader"}
COUNT_AGAIN_MS = 3000                           # page 6 asks for its numbers again while it says *Counting…* —
COUNT_MOST_MS = 30000                           # each time twice as long after, up to this (and when the indexer ran)
ASK_WAIT_S = 600                               # the install's question waits this long for an answer, then is No
GLYPH_GEM = {"ja": "sapphire", "zh": "ruby"}    # page 1's wash under each glyph
# The wizard's type sizes, as multiples of the theme's roles (theme.TYPE has no wizard roles yet: the notes carry the
# theme.py patch that names them). The title is `first-run-heading` × 1.3; the glyphs and the big numbers are larger.
TITLE_SCALE, SENTENCE_SCALE, GLYPH_SCALE, NUMBER_SCALE = 1.3, 1.45, 3.5, 2.0


def services_api():
    """The wizard's Qt-free rules (worker S's module; imported when the wizard opens)."""
    from app.services import setup_wizard
    return setup_wizard


def miner_api():
    """Anki Miner's look and install route (worker M's module)."""
    from app.services import anki_miner_setup
    return anki_miner_setup


def thaw(value):
    from app.services import settings as settings_service
    return settings_service.thaw(value)


# --- the look's small helpers ------------------------------------------------------------------------------------------ #
def _f():
    return theme.text_factor(style.current()[1])


def _px(n):
    return round(n * _f())


def _c(name):
    return style.qcolor(style.colours()[name])


def _font(role, weight=None, scale=1.0, families=None):
    """A type role (× the text size × `scale`) as a QFont, in `families` (default: the application's)."""
    f = QFont(QApplication.font())
    if families:
        f.setFamilies(list(families))
    px, drawn = theme.font(role, style.current()[1])
    f.setPointSizeF(px * scale * style.PT_PER_PX)
    f.setWeight(QFont.Weight(weight or drawn))
    return f


def _iris(x0, x1, y=0.0):
    g = QLinearGradient(QPointF(x0, y), QPointF(x1, y))
    for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
        g.setColorAt(pos, style.qcolor(colour))
    return g


def _ring(p, rect, radius=6):
    """The 2 px accent focus ring (the GUI rule), inside `rect`."""
    p.setPen(QPen(_c("accent"), 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), radius, radius)


def _gem(rect, kind="sapphire"):
    """A gem's fill: its light at the top left, its base at the edge (the redesign's gems, flat)."""
    base, light, _edge = theme.GEM[kind]
    g = QRadialGradient(QPointF(rect.left() + rect.width() * 0.38, rect.top() + rect.height() * 0.32),
                        rect.width() * 0.7)
    g.setColorAt(0.0, style.qcolor(light))
    g.setColorAt(1.0, style.qcolor(base))
    return g


@lru_cache(maxsize=None)
def sheet(text_size):
    """The wizard's own rules over the application's stylesheet (scoped to `#wizard`; every colour a theme token).
    🧭 They belong in `style.stylesheet()` (a later patch: style.py is another agent's file now)."""
    c = {k: style.qss_colour(v) for k, v in theme.colours().items()}
    on_accent = style.qss_colour(theme.FIXED["on-accent"])
    f = theme.text_factor(text_size)

    def font(role, weight=None, scale=1.0):
        size, drawn = theme.font(role, text_size)
        return f"font-size: {round(size * scale * style.PT_PER_PX, 3)}pt; font-weight: {weight or drawn};"
    hint = QFontMetricsF(_font("key-hint")).horizontalAdvance(S.KEY_ENTER)
    return f"""
QWidget#wizard {{ background: {c['bg']}; }}
QWidget#wizhead, QWidget#wizfoot {{ background: {c['frame']}; }}
QScrollArea#wizscroll {{ background: transparent; border: 0; }}
QLabel#wiztitle {{ color: {c['ink']}; {font('first-run-heading', 600, TITLE_SCALE)} }}
QLabel#wizline {{ color: {c['ink-dim']}; {font('hero-sub')} }}
QLabel#wizhint {{ color: {c['ink-dim']}; {font('footer')} }}
QLabel#wizlabel {{ color: {c['ink']}; {font('body', 400)} }}
QLabel#wizgroup {{ color: {c['ink']}; {font('body', 600)} }}
QLabel#wizsub {{ color: {c['ink-dim']}; {font('row-sub')} }}
QLabel#wizpath {{ color: {c['ink']}; {font('row-sub')} }}
QLabel#wizrec {{ color: {c['accent']}; {font('eyebrow')} letter-spacing: 1px; }}
QLabel#wizsay {{ color: {c['ink-dim']}; {font('footer')} }}
QLabel#wizclosed {{ color: {c['warn']}; {font('body', 600)} }}
QLabel#wizrowname {{ color: {c['ink']}; {font('row-title')} }}
QLabel#wizrowline {{ color: {c['ink-dim']}; {font('row-sub')} }}
QLabel#wizbig {{ color: {c['ink']}; {font('first-run-heading', 600, NUMBER_SCALE)} }}
QLabel#wizbig[tone="ok"] {{ color: {c['ok']}; }}
QLabel#wizbig[tone="warn"] {{ color: {c['warn']}; }}
QLabel#wizbigsub {{ color: {c['ink-dim']}; {font('body', 400)} }}
QLabel#wizkey {{ color: {on_accent}; {font('key-hint', 400)} background: transparent; }}
QPushButton#wizlater, QPushButton#wizquiet, QPushButton#wizlink {{ background: transparent; border: 0;
  color: {c['ink-dim']}; padding: 0 {round(10 * f)}px; {font('button', 400)} }}
QPushButton#wizquiet {{ color: {c['ink']}; }}
QPushButton#wizlink {{ text-decoration: underline; padding: 0; }}
QPushButton#wizlater:hover, QPushButton#wizquiet:hover, QPushButton#wizlink:hover {{ color: {c['ink']}; }}
QPushButton#wizlater:focus, QPushButton#wizquiet:focus, QPushButton#wizlink:focus {{ border: 2px solid {c['accent']};
  border-radius: 6px; padding: 0 {round(10 * f) - 2}px; }}
QPushButton#wizquiet:disabled, QPushButton#wizlater:disabled {{ color: {c['ink-faint']}; }}
QPushButton#wiznext {{ min-width: {round(92 * f)}px; min-height: {round(36 * f)}px;
  padding: 0 {round(13 * f + hint + 8)}px 0 {round(13 * f + hint * 0.4)}px; {font('button', 700)} }}
QPushButton#wizstar {{ background: transparent; border: 0; color: {c['ink']}; padding: 0; {font('body', 600)} }}
QPushButton#wizstar:focus {{ border: 2px solid {c['accent']}; border-radius: 6px; }}
"""


# --- the frame's parts -------------------------------------------------------------------------------------------------- #
class StepList(QWidget):
    """The steps, words only: the number (✓ once passed), the name; the iris vein beside the step you're on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(S.STEPS_NAME)
        self.current, self.passed = 0, frozenset()
        self.paints = 0

    def set_state(self, current, passed):
        passed = frozenset(passed)
        if (current, passed) == (self.current, self.passed):
            return
        self.current, self.passed = current, passed
        self.setAccessibleDescription(S.STEP_HERE_NAME.format(name=S.STEPS[PAGES[current]]))
        self.update()

    def row_h(self):
        return _px(39)

    def sizeHint(self):
        return QSize(int(round(theme.size("wizard-steps", style.current()[1]))), self.row_h() * len(PAGES) + _px(40))

    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        h, top = self.row_h(), _px(36)
        small, name_font, here_font = _font("mini", 400), _font("body", 400), _font("body", 700)
        for i, pid in enumerate(PAGES):
            y = top + i * h
            here, done = i == self.current, i in self.passed and i != self.current
            if here:
                vein = QLinearGradient(QPointF(0, y + h * 0.18), QPointF(0, y + h * 0.82))
                for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
                    vein.setColorAt(pos, style.qcolor(colour))
                p.fillRect(QRectF(_px(20), y + h * 0.18, 2, h * 0.64), vein)
            p.setFont(small)
            p.setPen(_c("ink") if here else _c("ink-dim"))
            mark = "✓" if done else str(i + 1)
            p.drawText(QRectF(_px(30), y, _px(16), h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, mark)
            p.setFont(here_font if here else name_font)
            p.setPen(_c("ink") if here else _c("ink-dim"))
            p.drawText(QRectF(_px(60), y, self.width() - _px(64), h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, S.STEPS[pid])
        p.end()


class Hairline(QWidget):
    """The header's lower edge: the frame's edge at rest; while the list is made, the iris grows along it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self.value = None

    def set_value(self, value):
        value = None if value is None else max(0.0, min(1.0, float(value)))
        if value != self.value:
            self.value = value
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), _c("frame-edge"))
        if self.value is not None:
            w = self.width() * self.value
            p.fillRect(QRectF(0, 0, w, self.height()), _iris(0, max(1.0, self.width())))
        p.end()


class NextButton(QPushButton):
    """*Next* (or **Generate**) with its key, *Enter*, inside it (the draft's)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("wiznext")
        self.setProperty("kind", "primary")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAutoDefault(False)                        # Enter is the wizard's own (`SetupWizard.keyPressEvent`)
        self.setDefault(False)
        self.key = QLabel(S.KEY_ENTER, self)
        self.key.setObjectName("wizkey")
        self.key.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mouseDoubleClickEvent(self, event):
        event.accept()                                    # a double click's second press is no press (AD-3)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.key.adjustSize()
        self.key.move(self.width() - self.key.width() - _px(14), (self.height() - self.key.height()) // 2)


# --- choices ------------------------------------------------------------------------------------------------------------- #
class Choice(QAbstractButton):
    """One option of a choice channel (the vein under the chosen one). A channel is one Tab stop — the chosen option —
    and ← → move the choice within it."""

    def __init__(self, key, title, tip, parent=None, line="", recommended=False, dot=None, small=False):
        super().__init__(parent)
        self.key, self.title, self.line, self.recommended, self.dot, self.small = (key, title, line, recommended,
                                                                                    dot, small)
        self.setCheckable(True)
        self.setAutoExclusive(False)
        self.setText(title)
        self.setToolTip(tip)
        self.setAccessibleName(title)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.channel = None
        self._keyed = False
        self.paints = 0

    def set_parts(self, line=None, recommended=None, dot=False):
        """The sub line, the *Recommended* mark and the dot ("ok" · "off" · None) — repainted only when they changed."""
        new = (self.line if line is None else line, self.recommended if recommended is None else recommended,
               self.dot if dot is False else dot)
        if new != (self.line, self.recommended, self.dot):
            self.line, self.recommended, self.dot = new
            self.updateGeometry()                         # its words' width moved (`minimumSizeHint`)
            if self.channel is not None:
                self.channel.updateGeometry()
                self.channel.fit()
            self.update()

    def sizeHint(self):
        return QSize(_px(150), _px(42 if self.small else 76))

    def minimumSizeHint(self):
        return QSize(self.needed_width(), self.sizeHint().height())     # never narrower than its words

    def needed_width(self):
        """The width its words are drawn in (`paintEvent`): the dot, the title and *Recommended*; the line."""
        pad = _px(16 if not self.small else 12)
        title = QFontMetricsF(_font("body", 600)).horizontalAdvance(self.title)
        if self.dot:
            title += _px(10) + _px(10)
        if self.recommended:
            rec = _font("eyebrow")
            rec.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
            title += _px(12) + QFontMetricsF(rec).horizontalAdvance(S.RECOMMENDED)
        line = QFontMetricsF(_font("row-sub")).horizontalAdvance(self.line) if self.line and not self.small else 0
        return math.ceil(2 * pad + max(title, line)) + 1

    def focusInEvent(self, event):
        self._keyed = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)

    def keyPressEvent(self, event):
        if self.channel is not None and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.channel.step(self, -1 if event.key() == Qt.Key.Key_Left else 1)
            return
        super().keyPressEvent(event)

    def _paint_ground(self, p):
        p.fillRect(self.rect(), _c("row-hover") if self.underMouse() and not self.isChecked() else _c("surface"))

    def _paint_vein(self, p, y, x0, x1):
        p.fillRect(QRectF(x0, y, x1 - x0, 2), _iris(x0, x1))

    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint_ground(p)
        pad = _px(16 if not self.small else 12)
        chosen = self.isChecked()
        title_font = _font("body", 600)
        fm = QFontMetricsF(title_font)
        if self.small:
            x = (self.width() - fm.horizontalAdvance(self.title)) / 2
            base = (self.height() + fm.ascent() - fm.descent()) / 2
        else:
            x = pad
            base = pad + fm.ascent() + _px(4)
        if self.dot:
            d = _px(10)
            dot = QRectF(x, base - fm.ascent() / 2 - d / 2 - _px(1), d, d)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_gem(dot, "emerald") if self.dot == "ok"
                       else style.qcolor(theme.mix(theme.GEM["emerald"][0], 35, style.colours()["cut"])))
            p.drawEllipse(dot)
            x += d + _px(10)
        p.setFont(title_font)
        p.setPen(_c("ink") if chosen or not self.small else _c("ink-dim"))
        p.drawText(QPointF(x, base), self.title)
        end = x + fm.horizontalAdvance(self.title)
        if self.recommended:
            rec = _font("eyebrow")
            rec.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
            p.setFont(rec)
            p.setPen(_c("accent"))
            p.drawText(QPointF(end + _px(12), base - _px(1)), S.RECOMMENDED)
        if self.line and not self.small:
            p.setFont(_font("row-sub"))
            p.setPen(_c("ink-dim"))
            p.drawText(QPointF(pad, base + _px(22)), self.line)
        if chosen:
            if self.small:
                self._paint_vein(p, self.height() - _px(8), x - _px(2), end + _px(2))
            else:
                self._paint_vein(p, self.height() - _px(8), pad - _px(4), self.width() - pad)
        if self.hasFocus() and self._keyed:
            _ring(p, self.rect())
        p.end()


class GlyphChoice(Choice):
    """Page 1's two big glyphs, 日本語 and 中文, each over a faint wash of its gem, its English name under it."""

    def __init__(self, key, parent=None):
        super().__init__(key, S.LANGUAGE_WORDS[key], S.LANGUAGE_TIPS[key], parent)
        self.glyph = S.LANGUAGE_GLYPHS[key]
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(_px(430), _px(250))

    def needed_width(self):
        glyph = QFontMetricsF(_font("first-run-heading", 700, GLYPH_SCALE, theme.font_families(self.key)))
        name = QFontMetricsF(_font("body", 400))
        return math.ceil(2 * _px(30) + max(glyph.horizontalAdvance(self.glyph), name.horizontalAdvance(self.title))) + 1

    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect())
        p.fillRect(r, _c("surface"))
        wash = QRadialGradient(QPointF(r.width() * 0.55, 0), r.width() * 0.62)
        light = theme.GEM[GLYPH_GEM[self.key]][0]
        wash.setColorAt(0.0, style.qcolor(theme.mix(light, 55, "transparent")))
        wash.setColorAt(1.0, style.qcolor(theme.mix(light, 0, "transparent")))
        p.fillRect(r, wash)
        chosen = self.isChecked()
        pad = _px(30)
        glyph = _font("first-run-heading", 700, GLYPH_SCALE, theme.font_families(self.key))
        fm = QFontMetricsF(glyph)
        p.setFont(glyph)
        p.setPen(_c("ink") if chosen else style.qcolor(theme.mix(style.colours()["ink"], 80, style.colours()["cut"])))
        word_y = r.height() - _px(30)
        p.drawText(QPointF(pad, word_y - _px(26) - fm.descent()), self.glyph)
        p.setFont(_font("body", 400))
        p.setPen(_c("ink"))
        p.drawText(QPointF(pad, word_y), self.title)
        if chosen:
            self._paint_vein(p, r.height() - _px(15), pad, r.width() - pad)
        if self.hasFocus() and self._keyed:
            _ring(p, self.rect())
        p.end()


class Channel(QWidget):
    """A pick between options side by side (no walls between them but the ground's hairline): one chosen, one Tab
    stop, ← → within."""
    changed = pyqtSignal(str)

    def __init__(self, name, parent=None, gap=1):
        super().__init__(parent)
        self.setAccessibleName(name)
        self.choices = []
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(gap)

    def _needed(self):
        """The width its choices' words take side by side (each at least its own: `Choice.minimumSizeHint`)."""
        return sum(ch.needed_width() for ch in self.choices) + self.row.spacing() * max(0, len(self.choices) - 1)

    def minimumSizeHint(self):
        # as narrow as one choice: narrower than all side by side, they stack (`resizeEvent`)
        least = self.row.minimumSize()
        return QSize(max((ch.needed_width() for ch in self.choices), default=0), least.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def fit(self):
        way = (QBoxLayout.Direction.LeftToRight if self.width() >= self._needed()
               else QBoxLayout.Direction.TopToBottom)
        if self.row.direction() != way:                   # the words never cut: one above another when narrow
            self.row.setDirection(way)
            self.updateGeometry()

    def add(self, choice):
        choice.channel = self
        choice.clicked.connect(lambda _c=False, ch=choice: self.choose(ch.key, user=True))
        self.choices.append(choice)
        self.row.addWidget(choice, 1)
        return choice

    def value(self):
        return next((ch.key for ch in self.choices if ch.isChecked()), None)

    def choice(self, key):
        return next((ch for ch in self.choices if ch.key == key), None)

    def choose(self, key, user=False):
        """Check `key` alone (signals blocked: a restored choice is not a click); `changed` only for the user's."""
        for ch in self.choices:
            on = ch.key == key
            if ch.isChecked() != on:
                ch.blockSignals(True)
                ch.setChecked(on)
                ch.blockSignals(False)
                ch.update()
            policy = Qt.FocusPolicy.TabFocus if on else Qt.FocusPolicy.NoFocus
            if ch.focusPolicy() != policy:
                ch.setFocusPolicy(policy)
        if user:
            self.changed.emit(key)

    def step(self, current, delta):
        shown = [ch for ch in self.choices if not ch.isHidden()]
        if current not in shown:
            return
        i = max(0, min(len(shown) - 1, shown.index(current) + delta))
        target = shown[i]
        if target is not current:
            self.choose(target.key, user=True)
            target.setFocus(Qt.FocusReason.TabFocusReason)

    def focus(self):
        chosen = next((ch for ch in self.choices if ch.isChecked()), None)
        if chosen is not None:
            chosen.setFocus(Qt.FocusReason.TabFocusReason)


class Switch(QAbstractButton):
    """A switch: its gem slides and lands on the one clock (reduced motion: it jumps). Space toggles it."""

    def __init__(self, name, tip, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAccessibleName(name)
        self.setToolTip(S.SWITCH_TIP.format(name=name, tip=tip))      # no words: it names itself first (the wiring)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(theme.size("switch-w") + 10, theme.size("switch-h") + 4)
        self._pos = 0.0
        self._keyed = False
        self.toggled.connect(self._slide)

    def set_quiet(self, on):
        """Set without a click and without the slide (a loaded choice)."""
        self.blockSignals(True)
        self.setChecked(bool(on))
        self.blockSignals(False)
        self._at(1.0 if on else 0.0)

    def _at(self, pos):
        self._pos = pos
        self.update()

    def _slide(self, on):
        start, end = self._pos, 1.0 if on else 0.0
        motion.clock().animate(motion.duration("switch-knob"), lambda t: self._at(start + (end - start) * t),
                               kind="move", owner=self, on_end=lambda: self._at(end))

    def focusInEvent(self, event):
        self._keyed = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(_c("line-hi"), 1.0))
        p.setBrush(_c("accent-wash") if self.isChecked() else _c("cut"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 2
        knob = QRectF(r.left() + 1 + self._pos * (r.width() - d - 2), r.top() + 1, d, d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_gem(knob) if self.isChecked() else _c("ink-faint"))
        p.drawEllipse(knob)
        if self.hasFocus() and self._keyed:
            _ring(p, self.rect(), self.height() / 2)
        p.end()


class SwitchRow(QWidget):
    """A switch with its name, *Recommended* when it is, and its one line; a picture before it when given."""

    def __init__(self, name, line, tip, parent=None, recommended=False, picture=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, _px(6), 0, _px(6))
        row.setSpacing(_px(14))
        if picture is not None:
            row.addWidget(picture)
        words = QVBoxLayout()
        words.setSpacing(_px(2))
        head = QHBoxLayout()
        head.setSpacing(_px(10))
        self.name = _label("wizlabel", name, self, wrap=True)
        head.addWidget(self.name, 1)
        self.rec = _label("wizrec", S.RECOMMENDED, self)
        self.rec.setVisible(recommended)
        head.addWidget(self.rec)
        words.addLayout(head)
        self.line = _label("wizsub", line, self, wrap=True)
        self.line.setVisible(bool(line))
        words.addWidget(self.line)
        row.addLayout(words, 1)
        self.switch = Switch(name, tip, self)
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)


def _label(name, text="", parent=None, wrap=False):
    lab = QLabel(text, parent)
    lab.setObjectName(name)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setWordWrap(wrap)
    return lab


def _button(text, tip, slot, parent=None, name=None, kind=None):
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    b.setAccessibleName(text)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoDefault(False)                               # never Enter's: a button acts on Space or a click (AD-1)
    b.setDefault(False)
    if name:
        b.setObjectName(name)
    if kind:
        b.setProperty("kind", kind)
    b.clicked.connect(lambda _c=False: slot())
    return b


class _PageScroll(QScrollArea):
    """Scrolls up and down only, so it asks for its page's least width (never a page cut at the right)."""

    def minimumSizeHint(self):
        page = self.widget()
        least = super().minimumSizeHint()
        if page is None:
            return least
        return QSize(page.minimumSizeHint().width() + self.verticalScrollBar().sizeHint().width(), least.height())

    def eventFilter(self, obj, event):
        # (QScrollArea watches its page) the page's layout changed — decks or rows came in: its least width is asked
        # again, never left cut at the right until another page shows
        if obj is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(obj, event)


def _scrolled(page):
    """`page` in a frameless scroll area: at its full height when the window is shorter than it (the text, the
    pictures and the buttons are never squeezed into each other), the window's height otherwise; never sideways."""
    area = _PageScroll()
    area.setObjectName("wizscroll")
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    area.setWidget(page)
    area.viewport().setAutoFillBackground(False)
    page.setAutoFillBackground(False)
    return area


def _breakable(text):
    """`text` as drawn: a line may break after a path's backslash (a zero-width space there), so a long path wraps
    instead of widening the window past the screen. Only in labels nobody selects (the breaks would be copied)."""
    return text.replace("\\", "\\​")


def _split_path(text):
    """(the words, a Windows path that ends them) — a fix's steps end in the file to pick (*…choose file: C:\\…*): the
    path goes on its own line, whole and copyable. ("", "") for nothing; (text, "") when no path ends it."""
    found = _PATH_AT_END.search(text or "")
    if not found:
        return text or "", ""
    return text[:found.start()].rstrip(), found.group(0).strip()


_PATH_AT_END = re.compile(r"(?<!\S)[A-Za-z]:\\\S(?:.*\S)?\.\w+\s*$", re.S)


def _set_text(label, text):
    if label.text() != text:
        label.setText(text)


def _show(widget, on):
    if widget.isHidden() == bool(on):
        widget.setVisible(bool(on))


def _enable(widget, on):
    if widget.isEnabled() != bool(on):
        widget.setEnabled(bool(on))


def _tabular(font):
    """Tabular figures (Qt 6.7+): a count that grows doesn't jiggle (the window's rule for numbers)."""
    if hasattr(QFont, "Tag"):
        try:
            font.setFeature(QFont.Tag("tnum"), 1)
        except (TypeError, AttributeError):
            pass
    return font


def _count(pair, n):
    """(one, many) for `n`: *1 episode*, *412 episodes*."""
    n = int(n or 0)
    return pair[0] if n == 1 else pair[1].format(n=n)


class FlowLayout(QLayout):
    """Items left to right, wrapping to the next line (page 2's decks, page 5's buttons, Settings' Anki Miner card)."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, move):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._gap, 0
            if move:                                      # never past the line's end (a button wider than it)
                item.setGeometry(QRect(QPoint(x, y), QSize(min(hint.width(), rect.right() + 1 - x), hint.height())))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


DECK_CHIP_MAX = 420                 # a deck chip's widest (px × the text size): inside the least window's page


class DeckChip(QAbstractButton):
    """A deck as a tablet: ✓ when it is read, its name, its studied cards."""

    def __init__(self, name, count, parent=None):
        super().__init__(parent)
        self.name, self.count = name, count
        self.setCheckable(True)
        self.setText(name)
        self.setAccessibleName(name)
        self.setToolTip(S.DECK_TIP.format(deck=name, n=count or 0))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._keyed = False

    def _parts(self):
        return _font("body", 400), _font("row-sub", 400)

    def sizeHint(self):
        name_f, count_f = self._parts()
        w = (_px(36) + QFontMetricsF(name_f).horizontalAdvance(self.name)
             + QFontMetricsF(count_f).horizontalAdvance(S.DECK_CARDS.format(n=self.count or 0)) + _px(14))
        return QSize(min(math.ceil(w), _px(DECK_CHIP_MAX)), _px(34))   # a long name shortened (`paintEvent`)

    def focusInEvent(self, event):
        self._keyed = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        on = self.isChecked()
        p.fillRect(self.rect(), _c("accent-wash") if on else _c("raised"))
        p.fillRect(QRectF(0, 0, self.width(), 1), _c("line-hi"))
        name_f, count_f = self._parts()
        base = (self.height() + QFontMetricsF(name_f).ascent() - QFontMetricsF(name_f).descent()) / 2
        x = _px(12)
        if on:
            p.setFont(count_f)
            p.setPen(_c("accent"))
            p.drawText(QPointF(x, base), "✓")
        x += _px(20)
        p.setFont(name_f)
        p.setPen(_c("ink") if on else _c("ink-dim"))
        count = QFontMetricsF(count_f).horizontalAdvance(S.DECK_CARDS.format(n=self.count or 0))
        name = QFontMetricsF(name_f).elidedText(self.name, Qt.TextElideMode.ElideMiddle,
                                                max(0.0, self.width() - x - _px(8) - count - _px(14)))
        p.drawText(QPointF(x, base), name)                # (whole in its tooltip and its name for a reader)
        x += QFontMetricsF(name_f).horizontalAdvance(name) + _px(8)
        p.setFont(count_f)
        p.setPen(_c("ink-dim"))
        p.drawText(QPointF(x, base), S.DECK_CARDS.format(n=self.count or 0))
        if self.hasFocus() and self._keyed:
            _ring(p, self.rect(), 4)
        p.end()


class Dot(QWidget):
    """One of Connect's setup checks, summed up: a dot and its name (status is never colour alone: the tooltip and the
    accessible name say its state)."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name, self.state = name, "off"
        self.setAccessibleName(S.DOT_NAME.format(name=name, state=S.DOT_STATE["off"]))

    def set_state(self, state, tip):
        state = state if state in S.DOT_STATE else "off"
        if state != self.state:
            self.state = state
            self.setAccessibleName(S.DOT_NAME.format(name=self.name, state=S.DOT_STATE[state]))
            self.update()
        if self.toolTip() != (tip or ""):
            self.setToolTip(tip or "")

    def sizeHint(self):
        return QSize(math.ceil(_px(18) + QFontMetricsF(_font("body", 400)).horizontalAdvance(self.name)), _px(24))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        d = _px(10)
        r = QRectF(0, (self.height() - d) / 2, d, d)
        p.setPen(Qt.PenStyle.NoPen)
        if self.state == "ok":
            p.setBrush(_gem(r, "emerald"))
        elif self.state == "warn":
            p.setBrush(_c("warn"))
        else:
            p.setBrush(style.qcolor(theme.mix(theme.GEM["emerald"][0], 30, style.colours()["cut"])))
        p.drawEllipse(r)
        f = _font("body", 400)
        p.setFont(f)
        p.setPen(_c("ink") if self.state != "off" else _c("ink-dim"))
        fm = QFontMetricsF(f)
        p.drawText(QPointF(_px(18), (self.height() + fm.ascent() - fm.descent()) / 2), self.name)
        p.end()


# --- the pictures (each says what you get; decoration, never a control) ------------------------------------------------ #
class FadedSentence(QWidget):
    """Page 2: a sentence with every known word faded and the one new word bright, the vein under it."""

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language
        self.setAccessibleName(S.KNOWN_SENTENCE_NAME)

    def set_language(self, language):
        if language != self.language:
            self.language = language
            self.update()

    def sizeHint(self):
        return QSize(_px(600), _px(62))

    def paintEvent(self, _event):
        words, new = S.KNOWN_SENTENCE.get(self.language, S.KNOWN_SENTENCE["ja"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        faded = _font("first-run-heading", 400, SENTENCE_SCALE, theme.font_families(self.language))
        bright = _font("first-run-heading", 700, SENTENCE_SCALE, theme.font_families(self.language))
        gap = _px(18)
        fm = QFontMetricsF(faded)
        drawn = sum(QFontMetricsF(bright if i == new else faded).horizontalAdvance(w) for i, w in enumerate(words))
        k = min(1.0, self.width() / max(1.0, drawn + gap * (len(words) - 1)))   # narrower than the line: smaller
        if k < 1.0:
            p.scale(k, k)
        base = fm.ascent() + _px(6)
        x = 0.0
        dim = style.qcolor(theme.mix(style.colours()["ink-faint"], 70, style.colours()["bg"]))
        for i, word in enumerate(words):
            font = bright if i == new else faded
            p.setFont(font)
            p.setPen(_c("ink") if i == new else dim)
            p.drawText(QPointF(x, base), word)
            w = QFontMetricsF(font).horizontalAdvance(word)
            if i == new:
                p.fillRect(QRectF(x, base + fm.descent() + _px(3), w, 2), _iris(x, x + w))
            x += w + gap
        p.end()


class CardsPicture(QWidget):
    """Page 4: four new cards scattered (*Today*), then the same four in the order you'll meet them (*With
    Surasura*), the next one ringed."""

    TILTS = (-3.0, 2.0, -2.0, 3.0)

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language
        self.setAccessibleName(S.ORDER_PICTURE_NAME)

    def set_language(self, language):
        if language != self.language:
            self.language = language
            self.update()

    def sizeHint(self):
        return QSize(_px(490), _px(140))

    def paintEvent(self, _event):
        words = S.ORDER_CARDS.get(self.language, S.ORDER_CARDS["ja"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        label_w, card_w, card_h, gap = _px(70), _px(96), _px(58), _px(10)
        k = min(1.0, self.width() / max(1, label_w + len(words) * (card_w + gap)))   # narrower: all of it, smaller
        if k < 1.0:
            p.scale(k, k)
        word_f = _font("body", 700, 1.25, theme.font_families(self.language))
        small = _font("mini", 400)
        rows = ((S.ORDER_TODAY, words, False), (S.ORDER_WITH, tuple(reversed(words)), True))
        for r, (name, order, straight) in enumerate(rows):
            top = r * (card_h + _px(12)) + _px(4)
            p.setFont(_font("row-sub"))
            p.setPen(_c("ink-dim"))
            p.drawText(QRectF(0, top, label_w, card_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       name)
            for i, word in enumerate(order):
                x = label_w + i * (card_w + gap)
                p.save()
                p.translate(x + card_w / 2, top + card_h / 2)
                if not straight:
                    p.rotate(self.TILTS[i])
                card = QRectF(-card_w / 2, -card_h / 2, card_w, card_h)
                p.fillRect(card, _c("raised"))
                p.fillRect(QRectF(card.left(), card.top(), card.width(), 1), _c("line-hi"))
                p.setFont(word_f)
                p.setPen(_c("ink") if straight else _c("ink-dim"))
                text_rect = card.adjusted(0, 0, 0, -_px(14) if straight else 0)
                p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, word)
                if straight:
                    p.setFont(small)
                    p.setPen(_c("ink-dim"))
                    p.drawText(card.adjusted(0, card_h * 0.55, 0, 0), Qt.AlignmentFlag.AlignHCenter
                               | Qt.AlignmentFlag.AlignTop, S.ORDER_EPISODE.format(n=S.ORDER_EPISODES[i]))
                    if i == 0:
                        p.setPen(QPen(style.qcolor(theme.ROOM["ring"]), 1.5))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawRect(card.adjusted(0.75, 0.75, -0.75, -0.75))
                p.restore()
        p.end()


class MinePicture(QWidget):
    """Page 5: a scene with its subtitle line → an Anki card (a picture, the reading, the word, the line, its audio)."""

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language
        self.setAccessibleName(S.CARDS_PICTURE_NAME)

    def set_language(self, language):
        if language != self.language:
            self.language = language
            self.update()

    def sizeHint(self):
        return QSize(_px(680), _px(170))

    def paintEvent(self, _event):
        line, reading, word = S.CARDS_LINE_SAMPLE.get(self.language, S.CARDS_LINE_SAMPLE["ja"])
        fam = theme.font_families(self.language)
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        k = min(1.0, self.width() / max(1, self.sizeHint().width()))   # narrower than drawn: all of it, smaller
        if k < 1.0:
            p.scale(k, k)
        h = self.height() / k
        scene = QRectF(0, 0, _px(300), h)
        sky = QLinearGradient(QPointF(0, 0), QPointF(0, h))
        sky.setColorAt(0.0, style.qcolor(theme.mix(theme.GEM["sapphire"][0], 40, c["bg"])))
        sky.setColorAt(0.65, style.qcolor(theme.mix(theme.GEM["ruby"][0], 22, c["bg"])))
        sky.setColorAt(1.0, _c("cut"))
        p.fillRect(scene, sky)
        moon = QRectF(_px(30), _px(24), _px(58), _px(58))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(theme.mix(theme.FIXED["cover-ink"], 72, c["bg"])))
        p.drawEllipse(moon)
        p.setFont(_font("body", 600, 1.05, fam))
        p.setPen(_c("ink"))
        p.drawText(scene.adjusted(0, 0, 0, -_px(14)), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   line)
        arrow_x = scene.right() + _px(28)
        p.setFont(_font("body", 400, 1.4))
        p.setPen(_c("ink-faint"))
        p.drawText(QRectF(arrow_x, 0, _px(30), h), Qt.AlignmentFlag.AlignCenter, "→")
        card = QRectF(arrow_x + _px(48), _px(20), _px(300), h - _px(40))
        p.fillRect(card, _c("raised"))
        p.fillRect(QRectF(card.left(), card.top(), card.width(), 1), _c("line-hi"))
        top, bottom = theme.generated_cover(word)
        thumb = QRectF(card.left() + _px(18), card.top() + _px(16), _px(72), _px(54))
        g = QLinearGradient(thumb.topLeft(), thumb.bottomRight())
        g.setColorAt(0.0, style.qcolor(top))
        g.setColorAt(1.0, style.qcolor(bottom))
        p.fillRect(thumb, g)
        tx = thumb.right() + _px(14)
        p.setFont(_font("mini", 400, 1.0, fam))
        p.setPen(_c("ink-dim"))
        p.drawText(QPointF(tx, card.top() + _px(28)), reading)
        p.setFont(_font("body", 700, 1.5, fam))
        p.setPen(_c("ink"))
        p.drawText(QPointF(tx, card.top() + _px(58)), word)
        p.setFont(_font("row-sub", 400, 1.0, fam))
        p.setPen(_c("ink-dim"))
        p.drawText(QPointF(tx, card.top() + _px(82)), line)
        bars = (5, 9, 13, 7, 15, 11, 6, 12, 8, 14, 7, 10, 5, 9)
        for i, b in enumerate(bars):
            bh = _px(b)
            p.fillRect(QRectF(tx + i * _px(5), card.top() + _px(102) - bh / 2, _px(2), bh), _c("accent"))
        p.end()


class CoversPicture(QWidget):
    """Page 3: a plain tile → the show's cover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(S.COVERS_PICTURE_NAME)
        self.setFixedSize(_px(92), _px(46))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = _px(30), self.height()
        p.fillRect(QRectF(0, 0, w, h), _c("raised"))
        p.setFont(_font("mini", 400))
        p.setPen(_c("ink-faint"))
        p.drawText(QRectF(w, 0, self.width() - 2 * w, h), Qt.AlignmentFlag.AlignCenter, "→")
        top, bottom = theme.generated_cover(S.COVERS)
        g = QLinearGradient(QPointF(0, 0), QPointF(0, h))
        g.setColorAt(0.0, style.qcolor(top))
        g.setColorAt(1.0, style.qcolor(bottom))
        p.fillRect(QRectF(self.width() - w, 0, w, h), g)
        p.end()


class LevelSlider(QWidget):
    """The level: seven chambers in a well, the gem on the chosen band, its name under it, the two ends named."""
    moved = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bands, self.index = [], 0
        self.setAccessibleName(S.SLIDER_NAME)
        self.setToolTip(S.SLIDER_TIP)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._keyed = False

    def set_bands(self, bands, index):
        bands = list(bands)
        index = max(0, min(len(bands) - 1, index)) if bands else 0
        if (bands, index) != (self.bands, self.index):
            self.bands, self.index = bands, index
            self._describe()
            self.update()

    def _describe(self):
        if self.bands:
            self.setAccessibleDescription(band_name(self.bands[self.index]))

    def set_index(self, index, user=False):
        if not self.bands:
            return
        index = max(0, min(len(self.bands) - 1, index))
        if index != self.index:
            self.index = index
            self._describe()
            self.update()
            if user:
                self.moved.emit(index)

    def sizeHint(self):
        return QSize(_px(700), _px(118))

    def _xs(self):
        pad = _px(34)
        n = max(1, len(self.bands) - 1)
        return [pad + (self.width() - 2 * pad) * i / n for i in range(len(self.bands))]

    def mousePressEvent(self, event):
        xs = self._xs()
        if xs:
            x = event.position().x()
            self.set_index(min(range(len(xs)), key=lambda i: abs(xs[i] - x)), user=True)

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.set_index(self.index - 1, user=True)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.set_index(self.index + 1, user=True)
        elif k == Qt.Key.Key_Home:
            self.set_index(0, user=True)
        elif k == Qt.Key.Key_End:
            self.set_index(len(self.bands) - 1, user=True)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):
        self._keyed = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), _c("surface"))
        xs = self._xs()
        y = _px(38)
        if xs:
            track = QLinearGradient(QPointF(xs[0], y), QPointF(xs[-1], y))
            track.setColorAt(0.0, style.qcolor(theme.mix(theme.GEM["sapphire"][0], 60, style.colours()["cut"])))
            track.setColorAt(1.0, style.qcolor(theme.mix(style.colours()["accent-2"], 45, style.colours()["cut"])))
            p.fillRect(QRectF(xs[0], y - 1.5, xs[-1] - xs[0], 3), track)
            d = _px(12)
            for i, x in enumerate(xs):
                if i == self.index:
                    continue
                p.setPen(QPen(_c("line-hi"), 1.0))
                p.setBrush(_c("bg"))
                p.drawEllipse(QRectF(x - d / 2, y - d / 2, d, d))
            g = _px(24)
            gem = QRectF(xs[self.index] - g / 2, y - g / 2, g, g)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_gem(gem))
            p.drawEllipse(gem)
            name = band_name(self.bands[self.index])
            f = _font("body", 600)
            p.setFont(f)
            p.setPen(_c("ink"))
            fm = QFontMetricsF(f)
            w = fm.horizontalAdvance(name)
            nx = max(0.0, min(self.width() - w, xs[self.index] - w / 2))
            p.drawText(QPointF(nx, y + g / 2 + _px(8) + fm.ascent()), name)
        ends = _font("mini", 400)
        p.setFont(ends)
        p.setPen(_c("ink-dim"))
        bottom = self.height() - _px(12)
        p.drawText(QPointF(_px(34), bottom), S.SLIDER_LOW)
        p.drawText(QPointF(self.width() - _px(34) - QFontMetricsF(ends).horizontalAdvance(S.SLIDER_HIGH), bottom),
                   S.SLIDER_HIGH)
        if self.hasFocus() and self._keyed:
            _ring(p, self.rect(), 4)
        p.end()


def band_name(band):
    """A band's name as the window says it (`word_selection.band_label`: a key, or a name given as it is)."""
    from app import word_selection
    return word_selection.band_label(str(band))


# --- the pages ------------------------------------------------------------------------------------------------------------ #
class _Page(QWidget):
    """One step: its title (the benefit), at most one line, its picture and its choices. `answers()` is the contract's
    shape for the page; `load(answers)` shows them (signals blocked); `entered()` runs when the page shows."""
    id = None

    def __init__(self, wiz, title, line=""):
        super().__init__()
        self.wiz = wiz
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, _px(36), 0, _px(20))
        self.box.setSpacing(_px(14))
        self.title = _label("wiztitle", title, self, wrap=True)
        self.box.addWidget(self.title)
        self.line = _label("wizline", line, self, wrap=True)
        self.line.setVisible(bool(line))
        self.box.addWidget(self.line)

    def paintEvent(self, event):
        self.wiz.page_painted(self)                       # the page was seen: it may take a press (`settled`)
        super().paintEvent(event)

    def answers(self):
        return {}

    def kept(self):
        """What the page keeps over a language switch (its `answers`, as `load` takes them)."""
        return self.answers()

    def load(self, answers):
        """Show `answers` (a page's preselects, or what the user chose)."""

    def entered(self):
        """The page shows: what it reads is asked again on a worker."""

    def next_offered(self):
        """False while the page can't go on (Anki not open on *Card order*): *Next* hides, Enter is *Skip*."""
        return True

    def focus_first(self):
        """Where the keyboard starts on this page (nothing: the wizard keeps it; a key's Tab finds the controls)."""

    def language_changed(self, language):
        """Page 1 changed the language: the pictures and what is read follow."""


class LanguagePage(_Page):
    id = "language"

    def __init__(self, wiz):
        super().__init__(wiz, S.LANGUAGE_TITLE, S.UPGRADE_LINE if wiz.upgrading else S.LANGUAGE_LINE)
        self.channel = Channel(S.LANGUAGE_CHOICE_NAME, self, gap=0)
        for key in ("ja", "zh"):
            self.channel.add(GlyphChoice(key, self.channel))
        self.box.addSpacing(_px(14))
        self.box.addWidget(self.channel)
        self.box.addWidget(_label("wizhint", S.LANGUAGE_HINT, self))
        self.box.addStretch(1)

    def answers(self):
        return {"language": self.channel.value() or "ja"}

    def load(self, answers):
        self.channel.choose((answers or {}).get("language") if (answers or {}).get("language") in ("ja", "zh")
                            else "ja")

    def focus_first(self):
        self.channel.focus()                              # ← → choose at once (the draft draws the ring here)


class KnownPage(_Page):
    id = "known"

    def __init__(self, wiz):
        super().__init__(wiz, S.KNOWN_TITLE)
        self.sentence = FadedSentence(wiz.language, self)
        self.box.insertWidget(1, self.sentence)
        self.line.setText(S.UPGRADE_KNOWN_LINE if wiz.upgrading else S.KNOWN_LINE)
        self.line.setObjectName("wizsub")
        self.line.setVisible(True)
        self.box.addSpacing(_px(10))
        self.channel = Channel(S.KNOWN_HOW_NAME, self)
        self.anki = self.channel.add(Choice("anki", S.FROM_ANKI, S.FROM_ANKI_TIP, self.channel, line=S.CHECKING,
                                            dot="off"))
        self.channel.add(Choice("import", S.IMPORT_LIST, S.IMPORT_LIST_TIP, self.channel, line=S.IMPORT_LIST_LINE))
        if wiz.upgrading:                                 # known words came over: nothing more is the third way
            self.channel.add(Choice("fresh", S.KEEP_CAME_OVER, S.KEEP_CAME_OVER_TIP, self.channel,
                                    line=S.KEEP_CAME_OVER_LINE))
        else:
            self.channel.add(Choice("fresh", S.START_FRESH, S.START_FRESH_TIP, self.channel, line=S.START_FRESH_LINE))
        self.channel.changed.connect(self._picked)
        self.box.addWidget(self.channel)
        self.box.addSpacing(_px(8))
        # under the channel: the decks (From Anki, open), Anki isn't open + Check again, or the importers' doors
        self.decks_part = QWidget(self)
        decks = QVBoxLayout(self.decks_part)
        decks.setContentsMargins(0, 0, 0, 0)
        decks.setSpacing(_px(10))
        decks.addWidget(_label("wizlabel", S.DECKS, self.decks_part))
        self.deck_well = QWidget(self.decks_part)
        self.deck_well.setAccessibleName(S.DECKS_NAME)
        self.flow = FlowLayout(self.deck_well, _px(10))
        decks.addWidget(self.deck_well)
        self.no_decks = _label("wizsub", S.NO_DECKS, self.decks_part)
        decks.addWidget(self.no_decks)
        self.box.addWidget(self.decks_part)
        self.closed_part = QWidget(self)
        closed = QHBoxLayout(self.closed_part)
        closed.setContentsMargins(0, 0, 0, 0)
        closed.setSpacing(_px(14))
        self.closed_line = _label("wizclosed", S.ANKI_CLOSED, self.closed_part)
        closed.addWidget(self.closed_line)
        self.btn_check = _button(S.CHECK_AGAIN, S.CHECK_AGAIN_TIP, self.wiz.look_anki, self.closed_part)
        closed.addWidget(self.btn_check)
        closed.addStretch(1)
        self.box.addWidget(self.closed_part)
        self.import_part = QWidget(self)
        doors = QHBoxLayout(self.import_part)
        doors.setContentsMargins(0, 0, 0, 0)
        doors.setSpacing(_px(10))
        self.doors = {}
        for name, text, tip in (("migaku", S.IMPORT_MIGAKU, S.IMPORT_MIGAKU_TIP),
                                ("jiten", S.IMPORT_JITEN, S.IMPORT_JITEN_TIP),
                                ("apkg_known", S.IMPORT_FILE, S.IMPORT_FILE_TIP)):
            b = _button(text, tip, lambda n=name: self.wiz.open_door(n), self.import_part)
            self.doors[name] = b
            doors.addWidget(b)
        doors.addStretch(1)
        self.box.addWidget(self.import_part)
        self.box.addStretch(1)
        self.chips = {}
        self._deck_key = None
        self._how = None                     # the preselected way, until the user picks
        self._touched = False
        self._wanted = None                  # the decks the answers name (None: Anki's own preselect)
        self.deck_paints = 0

    # what the page shows
    def load(self, answers):
        answers = answers or {}
        self._how = answers.get("how") if answers.get("how") in ("anki", "import", "fresh") else "anki"
        self._touched = False
        decks = answers.get("decks")
        self._wanted = list(decks) if decks else None
        self._show()

    def _effective(self):
        """The way shown: the user's pick; untouched, the preselected one — *Import a list* in place of *From Anki*
        while Anki isn't open (the draft)."""
        how = self._how
        look = self.wiz.anki
        if not self._touched and how == "anki" and (look is None or not look.get("open")):
            # an upgrader's stand-in is *Keep what came over*: the import already brought the words (IK2-3)
            return ("fresh" if self.wiz.upgrading else "import") if look is not None else "anki"
        return how

    def _picked(self, key):
        self._how, self._touched = key, True
        self._show()

    def _show(self):
        look = self.wiz.anki
        is_open = bool(look and look.get("open"))
        if look is None:
            self.anki.set_parts(line=S.CHECKING, recommended=False, dot="off")
        elif is_open:
            self.anki.set_parts(line=S.FROM_ANKI_OPEN, recommended=True, dot="ok")
        else:
            self.anki.set_parts(line=look.get("say") or S.ANKI_CLOSED, recommended=False, dot="off")
        how = self._effective()
        self.channel.choose(how)
        self.sentence.set_language(self.wiz.language)
        _show(self.decks_part, how == "anki" and is_open)
        # Anki not open: *Anki isn't open* + *Check again*, also while *Import a list* stands in for it untouched (the
        # draft; the intent keeper's IK-17) — gone once the learner picked another way themselves
        _show(self.closed_part, look is not None and not is_open and (how == "anki" or not self._touched))
        _show(self.import_part, how == "import")
        if is_open:
            self._render_decks(look)
        for name, b in self.doors.items():
            _show(b, self.wiz.door(name) is not None)
        self.wiz.paint_footer()

    def _render_decks(self, look):
        decks = [(name, count) for name, count in (look.get("decks") or [])]
        key = tuple(decks)
        if key != self._deck_key:
            self._deck_key = key
            self.deck_paints += 1
            for chip in self.chips.values():
                self.flow.removeWidget(chip)
                chip.deleteLater()
            self.chips = {}
            wanted = self._wanted if self._wanted is not None else list(look.get("preselected") or [])
            for name, count in decks:
                chip = DeckChip(name, count, self.deck_well)
                chip.setChecked(name in wanted)
                chip.toggled.connect(lambda _on: self.wiz.paint_footer())
                self.flow.addWidget(chip)
                chip.show()
                self.chips[name] = chip
            self.deck_well.updateGeometry()
        _show(self.no_decks, not decks)

    def chosen_decks(self):
        """The ticked decks, and each saved deck the open Anki doesn't hold (another profile open, a deck renamed: R2-3)
        kept as it was — never dropped by a *Next*."""
        absent = [d for d in (self._wanted or []) if d not in self.chips] if self.chips else []
        return [name for name, chip in self.chips.items() if chip.isChecked()] + absent

    def answers(self):
        how = self._effective()
        return {"how": how, "decks": self.chosen_decks() if how == "anki" else []}

    def next_offered(self):
        if self._effective() != "anki":
            return True
        look = self.wiz.anki
        return bool(look and look.get("open")) and bool(self.chosen_decks())

    def entered(self):
        if self.wiz.anki is None or not self.wiz.anki.get("open"):
            self.wiz.look_anki()
        self._show()

    def anki_changed(self):
        self._show()

    def language_changed(self, language):
        self._deck_key = None
        self._show()


class ShowsPage(_Page):
    id = "shows"

    def __init__(self, wiz):
        super().__init__(wiz, S.SHOWS_TITLE, S.UPGRADE_SHOWS_LINE if wiz.upgrading else "")
        # --- SRC W1a: the folders your shows and books are in, read where they are (added and looked at on *Next*)
        self.folders = []                   # the folders picked, not read yet (as the dialog gave them)
        self.folders_part = QWidget(self)
        self.folders_part.setAccessibleName(S.FOLDERS_NAME)
        fbox = QVBoxLayout(self.folders_part)
        fbox.setContentsMargins(0, 0, 0, _px(4))
        fbox.setSpacing(_px(8))
        fbox.addWidget(_label("wizgroup", S.FOLDERS, self.folders_part))
        self.folder_list = QVBoxLayout()
        self.folder_list.setSpacing(_px(6))
        fbox.addLayout(self.folder_list)
        pick = QHBoxLayout()
        pick.setSpacing(_px(14))
        self.btn_pick = _button(S.PICK_FOLDER, S.PICK_FOLDER_TIP, self.wiz.pick_folder, self.folders_part)
        pick.addWidget(self.btn_pick)
        self.skips = []                     # K6: folders inside the picked ones never read (skipped on *Next*)
        self.btn_skip = _button(S.SKIP_FOLDER, S.SKIP_FOLDER_TIP, self.wiz.skip_folder, self.folders_part,
                                name="wizlink")
        self.btn_skip.setVisible(False)
        pick.addWidget(self.btn_skip)
        self.reading_line = _label("wizsub", "", self.folders_part)
        f = self.reading_line.font()
        _tabular(f)
        self.reading_line.setFont(f)
        self.reading_line.setVisible(False)
        pick.addWidget(self.reading_line)
        self.btn_stop = _button(S.STOP, S.STOP_TIP, self.wiz.stop_reading, self.folders_part)
        self.btn_stop.setVisible(False)
        pick.addWidget(self.btn_stop)
        pick.addStretch(1)
        fbox.addLayout(pick)
        self.refused_line = _label("wizclosed", "", self.folders_part, wrap=True)
        self.refused_line.setVisible(False)
        fbox.addWidget(self.refused_line)
        self.box.addWidget(self.folders_part)
        self.folders_part.setVisible(wiz.can_read_folders())
        self._folders_key = None
        self.folder_paints = 0
        # --- end SRC W1a
        # --- W3.2 Q3: + Add's own actions (Files / Folder / EPUB / YouTube), each shown while it can act (IK-12)
        adds = QHBoxLayout()
        adds.setSpacing(_px(10))
        self.add_buttons = {}
        for name in ADD_ACTIONS:
            label, tip = strings.ADD_ITEMS[name]
            b = _button(label, tip, lambda n=name: self.wiz.add(n), self)
            adds.addWidget(b)
            self.add_buttons[name] = b
        self.btn_files, self.btn_youtube = self.add_buttons["files"], self.add_buttons["youtube"]
        adds.addStretch(1)
        # --- end W3.2 Q3
        self.box.addLayout(adds)
        self.rows_part = QWidget(self)
        self.rows_part.setAccessibleName(S.ROWS_NAME)
        self.rows = QVBoxLayout(self.rows_part)
        self.rows.setContentsMargins(0, _px(4), 0, _px(4))
        self.rows.setSpacing(_px(8))
        self.box.addWidget(self.rows_part)
        self.covers = SwitchRow(S.COVERS, S.COVERS_LINE, S.COVERS_TIP, self, recommended=True,
                                picture=CoversPicture())
        self.box.addWidget(self.covers)
        samples = QHBoxLayout()
        self.btn_samples = _button(S.SAMPLES, S.SAMPLES_TIP, self.wiz.add_samples, self, name="wizlink")  # W3.2 Q3
        samples.addWidget(self.btn_samples)
        samples.addStretch(1)
        self.box.addLayout(samples)
        self.box.addStretch(1)
        self._rows_key = None
        self.row_paints = 0

    def load(self, answers):
        self.covers.switch.set_quiet(bool((answers or {}).get("covers", True)))

    def answers(self):
        return {"covers": self.covers.switch.isChecked()}

    def entered(self):
        for name, b in self.add_buttons.items():          # --- W3.2 Q3: an action that can't act now isn't shown
            _show(b, self.wiz.can_add(name))
        self.wiz.read_rows()

    # --- SRC W1a: the folders picked, and their first look ------------------------------------------------------- #
    def has_folder(self, path):
        key = os.path.normcase(os.path.normpath(path))
        return any(os.path.normcase(os.path.normpath(p)) == key for p in self.folders)

    def add_folder(self, path):
        """A folder the store's rule accepted: listed, with *Remove*; the refusal said before goes."""
        if not self.has_folder(path):
            self.folders.append(path)
        self.refuse(None)
        self._paint_folders()

    def remove_folder(self, path):
        """*Remove* beside a folder: left out before going on (nothing was added: that happens on *Next*)."""
        self.folders = [p for p in self.folders if p != path]
        self._paint_folders()

    def add_skip(self, path):
        """K6: a folder the store's rule lets be skipped (inside a picked one): listed, with *Read it after all*."""
        key = os.path.normcase(os.path.normpath(path))
        if not any(os.path.normcase(os.path.normpath(p)) == key for p in self.skips):
            self.skips.append(path)
        self.refuse(None)
        self._paint_folders()

    def remove_skip(self, path):
        self.skips = [p for p in self.skips if p != path]
        self._paint_folders()

    def refuse(self, text):
        _set_text(self.refused_line, text or "")
        _show(self.refused_line, bool(text))

    def _paint_folders(self):
        """The picked folders, each a row with *Remove* (rebuilt only when the list changed, S19)."""
        key = (tuple(self.folders), tuple(self.skips), self.wiz.reading is not None)
        if key == self._folders_key:
            return
        self._folders_key = key
        self.folder_paints += 1
        while self.folder_list.count():
            item = self.folder_list.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()                      # never painted again while its delete waits for the loop
                item.widget().deleteLater()
        for path in self.folders:
            w = QWidget(self.folders_part)
            line = QHBoxLayout(w)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(_px(14))
            name = _label("wizrowline", path, w)
            f = name.font()
            f.setFamilies(list(theme.path_font_families(self.wiz.language)))      # a path's ¥ is a backslash again
            name.setFont(f)
            line.addWidget(name)
            b = _button(S.FOLDER_REMOVE, S.FOLDER_REMOVE_TIP, lambda p=path: self.remove_folder(p), w, name="wizlink")
            b.setAccessibleName(S.FOLDER_REMOVE_NAME.format(folder=path))
            _enable(b, self.wiz.reading is None)
            line.addWidget(b)
            line.addStretch(1)
            self.folder_list.addWidget(w)
        for path in self.skips:                           # K6: the folders inside them never read
            w = QWidget(self.folders_part)
            line = QHBoxLayout(w)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(_px(14))
            name = _label("wizsub", S.SKIPPED_ROW.format(folder=path), w)
            f = name.font()
            f.setFamilies(list(theme.path_font_families(self.wiz.language)))
            name.setFont(f)
            line.addWidget(name)
            b = _button(S.SKIP_REMOVE, S.SKIP_REMOVE_TIP, lambda p=path: self.remove_skip(p), w, name="wizlink")
            b.setAccessibleName(S.SKIP_REMOVE_NAME.format(folder=path))
            _enable(b, self.wiz.reading is None)
            line.addWidget(b)
            line.addStretch(1)
            self.folder_list.addWidget(w)
        _show(self.btn_skip, bool(self.folders))          # only inside a folder picked
        _enable(self.btn_skip, self.wiz.reading is None)
        text = S.PICK_ANOTHER if self.folders else S.PICK_FOLDER
        if self.btn_pick.text() != text:
            self.btn_pick.setText(text)
            self.btn_pick.setAccessibleName(text)
        _enable(self.btn_pick, self.wiz.reading is None)

    def show_reading(self, found, shows):
        """The first look's progress line, *Found 412 episodes in 37 shows…*, with *Stop*."""
        _set_text(self.reading_line, S.READING.format(episodes=_count(S.EPISODES, found), shows=_count(S.SHOWS_N,
                                                                                                         shows)))
        _show(self.reading_line, True)
        _show(self.btn_stop, True)
        self._paint_folders()

    def stopping(self):
        _enable(self.btn_stop, False)
        _set_text(self.btn_stop, S.STOPPING)

    def show_read(self, result):
        """The look ended: what it found (or that it stopped, keeping what came in), and why a folder wasn't read. The
        folders it dealt with leave the list (the next *Next* goes on); one it never reached — after a Stop, no library
        yet, a look already running — stays listed, to read or remove (never dropped unsaid); one picked meanwhile
        too."""
        result = result or {}
        _show(self.btn_stop, False)
        _enable(self.btn_stop, True)
        _set_text(self.btn_stop, S.STOP)
        if not result.get("ready", True):
            text = S.READ_NOT_READY
        elif result.get("busy"):
            text = S.READ_BUSY
        else:
            counts = dict(episodes=_count(S.EPISODES, result.get("found", 0)),
                          shows=_count(S.SHOWS_N, result.get("shows", 0)))
            text = (S.READ_STOPPED if result.get("stopped") else S.READ_DONE).format(**counts)
        _set_text(self.reading_line, text)
        _show(self.reading_line, True)
        problems = [S.FOLDER_REFUSED.format(folder=p, why=why) for p, why in result.get("refused") or ()]
        problems += [S.READ_UNREACHABLE.format(folder=p) for p in result.get("unreachable") or ()]
        problems += [S.READ_FAILED.format(folder=p, why=why) for p, why in result.get("failed") or ()]
        self.refuse("\n".join(problems))
        read = set(result.get("read") or ())
        self.folders = [p for p in self.folders if p not in read]
        self.skips = [p for p in self.skips if p not in set(result.get("skips") or ())]   # K6: the ones it dealt with
        self._paint_folders()
    # --- end SRC W1a

    def show_rows(self, rows):
        rows = list(rows or [])
        key = tuple((r.get("name"), r.get("count"), r.get("folder"), r.get("kind")) for r in rows)
        if key == self._rows_key:
            return
        self._rows_key = key
        self.row_paints += 1
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for r in rows[:ROWS_SHOWN]:
            self.rows.addWidget(self._row(r))
        if len(rows) > ROWS_SHOWN:
            self.rows.addWidget(_label("wizsub", S.ROWS_MORE.format(n=len(rows) - ROWS_SHOWN), self.rows_part))
        _show(self.rows_part, bool(rows))

    def _row(self, r):
        w = QWidget(self.rows_part)
        line = QHBoxLayout(w)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(_px(14))
        name = str(r.get("name") or "")
        tile = _Tile(name, w)
        line.addWidget(tile)
        title = _label("wizrowname", name, w)
        title.setMinimumWidth(_px(190))
        line.addWidget(title)
        count = row_count(r)
        folder = str(r.get("folder") or "")
        # wraps, a long folder after a backslash too (it widened the page past the window: the review's B1)
        sub = _label("wizrowline", _breakable(S.ROW_LINE.format(count=count, folder=folder)) if folder else count, w,
                     wrap=True)
        f = sub.font()
        f.setFamilies(list(theme.path_font_families(self.wiz.language)))      # a path's ¥ is a backslash again
        sub.setFont(f)
        line.addWidget(sub, 1)
        return w


def row_count(row):
    """A library row's count in words: episodes, books or videos by its kind, else files."""
    n = row.get("count")
    if not isinstance(n, int):
        return ""
    one, many = S.ROW_COUNT.get(row.get("kind"), S.ROW_FILES)
    return one if n == 1 else many.format(n=n)


class _Tile(QWidget):
    """A row's placeholder cover: its first character on the generated cover's colour (W2.2's fallback)."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.setFixedSize(_px(26), _px(36))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        top, _bottom = theme.generated_cover(self.title)
        p.fillRect(self.rect(), style.qcolor(theme.mix(top, 35, style.colours()["raised"])))
        p.setFont(_font("mini", 400))
        p.setPen(_c("ink-dim"))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.title[:1])
        p.end()


class _Combo(QComboBox):
    """A menu that takes the wheel only once focused (the page scrolls under it otherwise), and never asks for a long
    deck name's width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(16)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class OrderPage(_Page):
    id = "order"

    def __init__(self, wiz):
        super().__init__(wiz, S.ORDER_TITLE)
        self.picture = CardsPicture(wiz.language, self)
        self.box.addWidget(self.picture)
        self.closed_part = QWidget(self)
        closed = QHBoxLayout(self.closed_part)
        closed.setContentsMargins(0, 0, 0, 0)
        closed.setSpacing(_px(14))
        closed.addWidget(_label("wizclosed", S.ANKI_CLOSED, self.closed_part))
        self.btn_check = _button(S.CHECK_AGAIN, S.CHECK_AGAIN_TIP, self.wiz.look_anki, self.closed_part)
        closed.addWidget(self.btn_check)
        closed.addStretch(1)
        self.box.addWidget(self.closed_part)
        # 順 switched off or not in this Surasura: no control that does nothing (the intent keeper's IK-14)
        self.off_line = _label("wizclosed", S.ORDER_OFF, self, wrap=True)
        self.off_line.setVisible(False)
        self.box.addWidget(self.off_line)
        self.controls = QWidget(self)
        rows = QVBoxLayout(self.controls)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(_px(8))
        self.keep = SwitchRow(S.KEEP_ORDER, S.KEEP_ORDER_LINE, S.KEEP_ORDER_TIP, self.controls, recommended=True)
        rows.addWidget(self.keep)
        # D29's switch off: the consent is kept, and the page says it waits for it (IK-20)
        self.automation_line = _label("wizsub", S.ORDER_AUTOMATION_OFF, self.controls, wrap=True)
        self.automation_line.setVisible(False)
        rows.addWidget(self.automation_line)
        rows.addWidget(style.separator(self.controls))
        deck = QHBoxLayout()
        deck.setSpacing(_px(14))
        deck.addWidget(_label("wizlabel", S.DECK, self.controls))
        self.deck_box = _Combo(self.controls)
        self.deck_box.setToolTip(S.DECK_PICK_TIP)
        self.deck_box.setAccessibleName(S.DECK)
        self.deck_box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.deck_box.setMinimumWidth(_px(150))
        self.deck_box.activated.connect(lambda _i: self._deck_picked())
        deck.addWidget(self.deck_box)
        deck.addStretch(1)
        rows.addLayout(deck)
        rows.addWidget(style.separator(self.controls))
        later = QVBoxLayout()                             # the words above the three (beside them they were wider
        later.setSpacing(_px(6))                          # than the least window at Large text)
        later.addWidget(_label("wizlabel", S.LATER, self.controls, wrap=True))
        self.later = Channel(S.LATER_NAME, self.controls)
        for key in ("leave", "mark", "aside"):
            self.later.add(Choice(key, S.LATER_CHOICES[key], S.LATER_TIPS[key], self.later, small=True))
        self.later.setMaximumWidth(_px(430))              # (narrower only in a window narrower than it)
        later.addWidget(self.later, 0, Qt.AlignmentFlag.AlignLeft)
        rows.addLayout(later)
        rows.addWidget(style.separator(self.controls))
        self.open_anki = SwitchRow(S.OPEN_ANKI, S.OPEN_ANKI_LINE, S.OPEN_ANKI_TIP, self.controls)
        rows.addWidget(self.open_anki)
        self.box.addWidget(self.controls)
        self.box.addStretch(1)
        self._deck = None
        self._deck_key = None

    def load(self, answers):
        a = answers or {}
        self.keep.switch.set_quiet(bool(a.get("keep_in_order", True)))
        self.later.choose(a.get("later") if a.get("later") in S.LATER_CHOICES else "leave")
        self.open_anki.switch.set_quiet(bool(a.get("open_anki", False)))
        self._deck = a.get("deck") or None
        self._deck_key = None
        self._show()

    def _deck_picked(self):
        self._deck = self.deck_box.currentText() or None

    def _decks(self):
        look = self.wiz.anki or {}
        return [name for name, _count in (look.get("decks") or [])]

    def _show(self):
        look = self.wiz.anki
        off = self.wiz.junban_off()
        _set_text(self.off_line, off or "")
        _show(self.off_line, bool(off))
        is_open = bool(look and look.get("open")) and not off
        _show(self.closed_part, not off and look is not None and not is_open)
        _show(self.controls, is_open)
        _show(self.automation_line, is_open and not settings_manager.automation(self.wiz._settings()))
        self.picture.set_language(self.wiz.language)
        decks = self._decks()
        if self._deck and self._deck not in decks:
            decks.append(self._deck)                      # the saved deck stays chosen though this Anki lacks it (R2-3)
        if is_open and tuple(decks) != self._deck_key:
            self._deck_key = tuple(decks)
            self.deck_box.blockSignals(True)
            self.deck_box.clear()
            self.deck_box.addItems(decks)
            self.deck_box.blockSignals(False)
        if is_open:
            want = self._deck if self._deck in decks else next(
                (d for d in self.wiz.known_decks() if d in decks), decks[0] if decks else None)
            index = self.deck_box.findText(want) if want else -1
            if self.deck_box.currentIndex() != index:
                self.deck_box.blockSignals(True)
                self.deck_box.setCurrentIndex(index)
                self.deck_box.blockSignals(False)
        self.wiz.paint_footer()

    def answers(self):
        return {"keep_in_order": self.keep.switch.isChecked(), "deck": self.deck_box.currentText() or None,
                "later": self.later.value() or "leave", "open_anki": self.open_anki.switch.isChecked()}

    def next_offered(self):
        look = self.wiz.anki
        return bool(look and look.get("open")) and not self.wiz.junban_off()

    def entered(self):
        if not self.wiz.junban_off() and (self.wiz.anki is None or not self.wiz.anki.get("open")):
            self.wiz.look_anki()
        self._show()

    def anki_changed(self):
        self._show()

    def language_changed(self, language):
        self._deck_key = None
        self._show()


class CardsPage(_Page):
    id = "cards"

    def __init__(self, wiz):
        super().__init__(wiz, S.CARDS_TITLE, S.CARDS_LINE)
        self.picture = MinePicture(wiz.language, self)
        self.box.addWidget(self.picture)
        self.box.addSpacing(_px(12))
        state = QHBoxLayout()
        state.setSpacing(_px(12))
        self.dot = Dot("", self)
        self.dot.setFixedWidth(_px(14))
        state.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        # the words take the row's whole width and wrap (a fix's sentence and its steps run long: they were squeezed
        # beside the buttons into one line's height, Sonic's first try); the buttons go under them; steps by hand
        # (a fix that leads with the update, or ends in a file to pick) go last, the path on its own line, copyable
        words = QVBoxLayout()
        words.setSpacing(_px(2))
        self.head = QHBoxLayout()
        self.head.setSpacing(_px(10))
        self.name = _label("wizlabel", S.MINER_LOOKING, self, wrap=True)
        self.head.addWidget(self.name, 1)
        self.rec = _label("wizrec", S.RECOMMENDED, self)
        self.head.addWidget(self.rec)
        self.head.addStretch(0)
        words.addLayout(self.head)
        self.sub = _label("wizsub", "", self, wrap=True)
        words.addWidget(self.sub)
        self.acts = QWidget(self)                         # the buttons, wrapping to a second line when narrow
        acts_box = QVBoxLayout(self.acts)
        acts_box.setContentsMargins(0, _px(6), 0, 0)
        acts = FlowLayout(None, _px(12))
        acts_box.addLayout(acts)
        self.btn_install = _button(S.INSTALL, S.INSTALL_TIP, self.wiz.install_miner, self.acts)
        acts.addWidget(self.btn_install)
        self.btn_check = _button(S.CHECK_AGAIN, S.MINER_CHECK_TIP, self.wiz.look_miner, self.acts)
        acts.addWidget(self.btn_check)
        self.btn_star = _button(f"{S.STAR}  {S.STAR_ASK} {S.STAR_LINK}", S.STAR_TIP, self.wiz.open_star, self.acts,
                                name="wizstar")
        acts.addWidget(self.btn_star)
        words.addWidget(self.acts)
        self.steps = _label("wizsub", "", self, wrap=True)
        self.steps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.steps.setContentsMargins(0, _px(10), 0, 0)
        self.steps.setVisible(False)
        words.addWidget(self.steps)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, _px(4), 0, 0)
        path_row.setSpacing(_px(10))
        # the path whole, wrapping at its backslashes; never mouse-selected (the breaks drawn there would be copied
        # with it): *Copy path* copies it as it is
        self.path = _label("wizpath", "", self, wrap=True)
        self.path.setAccessibleName(S.PATH_NAME)
        self.path.setToolTip(S.PATH_NAME)
        self.path_text = ""
        f = self.path.font()
        f.setFamilies(list(theme.path_font_families(wiz.language)))           # a path's ¥ is a backslash again
        self.path.setFont(f)
        self.path.setVisible(False)
        path_row.addWidget(self.path, 1)
        self.btn_copy = _button(S.COPY_PATH, S.COPY_PATH_TIP, self._copy_path, self)
        self.btn_copy.setVisible(False)
        path_row.addWidget(self.btn_copy, 0, Qt.AlignmentFlag.AlignTop)
        words.addLayout(path_row)
        state.addLayout(words, 1)
        self.make = Switch(S.MINER_READY, S.MINER_READY_TIP, self)
        state.addWidget(self.make, 0, Qt.AlignmentFlag.AlignVCenter)
        self.box.addLayout(state)
        dots = QHBoxLayout()
        dots.setSpacing(_px(20))
        self.dots = [Dot(name, self) for name in S.DOTS]
        for d in self.dots:
            dots.addWidget(d)
        dots.addStretch(1)
        self.box.addLayout(dots)
        loading = QHBoxLayout()
        loading.setSpacing(_px(12))
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(S.DOWNLOADING_NAME)
        loading.addWidget(self.progress, 1)
        self.progress_line = _label("wizsub", "", self)
        loading.addWidget(self.progress_line)
        self.btn_cancel = _button(S.CANCEL_DOWNLOAD, S.CANCEL_DOWNLOAD_TIP, self.wiz.cancel_install, self)
        loading.addWidget(self.btn_cancel)
        self.loading = QWidget(self)
        self.loading.setLayout(loading)
        self.loading.setVisible(False)
        self.box.addWidget(self.loading)
        self.busy_line = _label("wizsub", S.INSTALL_BUSY, self, wrap=True)
        self.busy_line.setVisible(False)
        self.box.addWidget(self.busy_line)
        star = QHBoxLayout()
        self.star_quiet = _button(f"{S.STAR}  {S.STAR_ASK} {S.STAR_LINK}", S.STAR_TIP, self.wiz.open_star, self,
                                  name="wizlink")
        star.addWidget(self.star_quiet)
        star.addStretch(1)
        self.box.addLayout(star)
        self.box.addStretch(1)
        self._wanted = True
        self.look = None
        self._paint(None)

    def load(self, answers):
        self._wanted = bool((answers or {}).get("make_cards", True))
        self.make.set_quiet(self._wanted)

    def ready(self):
        return bool(self.look) and self.look.get("state") == "ready"

    def offered(self):
        """Whether *Make cards for me* is shown: the shared rule's *ready* answer (`services.tools_found`, WZ-4: on by
        default once Anki Miner is ready; Settings and *Needs you* ask its *installed* answer)."""
        return bool(self.look) and tools_found.make_cards_shown(tools_found.miner_level(self.look.get("state")),
                                                                ready=True)

    def answers(self):
        """The switch's answer; None while it isn't shown (a False would turn Connect off on *Set up again*)."""
        return {"make_cards": self.make.isChecked() if self.offered() else None}

    def kept(self):
        return {"make_cards": self.make.isChecked()}      # the switch as left, shown or not (a language switch)

    def show_progress(self, done, total):
        """The download's progress with *Cancel* (None, None: it ended; *Cancel* leaves once every byte is in: his
        installer opens then, and the route no longer looks at it). Repainted only when a tenth of a percent moved."""
        running = done is not None
        _show(self.loading, running)
        _enable(self.btn_install, not running and self.wiz.installing is None)
        if not running:
            return
        _show(self.btn_cancel, not total or done < total)
        value = round(1000 * done / total) if total else 0
        if self.progress.value() != value:
            self.progress.setValue(value)
            _set_text(self.progress_line, S.DOWNLOADING.format(mb=done / 1048576, of=(total or 0) / 1048576))

    def show_busy(self, busy):
        _show(self.busy_line, busy)

    def entered(self):
        self.wiz.look_miner()

    def show_look(self, look):
        self.look = look
        self._paint(look)

    def _paint(self, look):
        state = (look or {}).get("state")
        fix = (look or {}).get("fix") or None
        ready = state == "ready"
        if look is None:
            name, sub, dot = S.MINER_LOOKING, "", "off"
        elif ready:
            name = S.MINER_READY
            sub = S.MINER_READY_LINE.format(version=look.get("version") or "")
            dot = "ok"
        elif state == "missing":
            name, sub, dot = S.MINER_MISSING, S.MINER_MISSING_LINE, "off"
        else:                                             # too-old · needs-setup: only you can fix it
            name = (fix or {}).get("say") or S.MINER_MISSING
            sub = (fix or {}).get("do") or ""
            dot = "warn"
        update = bool((fix or {}).get("update")) and not ready      # before 3.7: the update first (option A)
        sub, path = _split_path(sub)
        by_hand = update or bool(path)                    # the steps go under the buttons, the path on its own line
        if update:
            name = S.MINER_UPDATE_FIRST
            sub = f"{S.MINER_BY_HAND}\n{sub}" if sub else ""
        _set_text(self.name, _breakable(name))            # (neither is selected: a path in them may break)
        _set_text(self.sub, "" if by_hand else _breakable(sub))
        _show(self.sub, bool(sub) and not by_hand)
        _set_text(self.steps, sub if by_hand else "")
        _show(self.steps, bool(sub) and by_hand)
        self.path_text = path
        _set_text(self.path, _breakable(path))
        self.path.setAccessibleDescription(path)          # a reader hears the path, not its break marks
        _show(self.path, bool(path))
        _show(self.btn_copy, bool(path))
        self.head.setStretchFactor(self.name, 0 if ready else 1)     # *Recommended* beside the name, not far right
        self.dot.set_state(dot, S.MINER_FIX_TIP if dot == "warn" else "")
        _show(self.rec, ready)
        _show(self.make, self.offered())                  # absent unless Anki Miner is ready (WZ-4)
        _show(self.btn_star, look is not None and not ready)
        _show(self.star_quiet, ready)                     # the star line stays, quieter, once it's ready
        _show(self.btn_install, state in ("missing", "too-old") or update)
        older = state == "too-old" or update
        text, tip = (S.UPDATE_MINER, S.UPDATE_MINER_TIP) if older else (S.INSTALL, S.INSTALL_TIP)
        if self.btn_install.text() != text or self.btn_install.toolTip() != tip:      # only what changed (S19)
            self.btn_install.setText(text)
            self.btn_install.setToolTip(tip)
            self.btn_install.setAccessibleName(text)
        _show(self.btn_check, look is not None and not ready and (state != "missing" or self.wiz.install_opened))
        _show(self.acts, any(not b.isHidden() for b in (self.btn_install, self.btn_check, self.btn_star)))
        dots = (look or {}).get("dots") or []
        for i, d in enumerate(self.dots):
            _name, st, tip = dots[i] if i < len(dots) else (None, "off", "")
            d.set_state(st, tip or S.DOT_NAME.format(name=d.name, state=S.DOT_STATE.get(st, S.DOT_STATE["off"])))
        self.wiz.paint_footer()

    def _copy_path(self):
        QApplication.clipboard().setText(self.path_text)
        self.wiz.say(S.PATH_COPIED)

    def language_changed(self, language):
        self.picture.set_language(language)
        f = self.path.font()
        f.setFamilies(list(theme.path_font_families(language)))
        self.path.setFont(f)
        self.look = None
        self._paint(None)


class LevelPage(_Page):
    id = "level"

    def __init__(self, wiz):
        super().__init__(wiz, S.LEVEL_TITLE, S.LEVEL_LINE)
        head = QHBoxLayout()
        head.addWidget(_label("wizgroup", S.LEVEL, self))
        head.addStretch(1)
        head.addWidget(_label("wizlabel", S.AUTOMATIC, self))
        self.auto = Switch(S.AUTOMATIC, S.AUTOMATIC_TIP, self)
        self.auto.toggled.connect(self._auto_toggled)
        head.addWidget(self.auto)
        head.addWidget(_label("wizrec", S.RECOMMENDED, self))
        self.box.addLayout(head)
        self.slider = LevelSlider(self)
        self.slider.moved.connect(self._moved)
        self.box.addWidget(self.slider)
        self.box.addSpacing(_px(14))
        numbers = QHBoxLayout()
        numbers.setSpacing(_px(56))
        self.big = {}
        for key, sub in (("words", S.WORDS), ("coverage", S.COVERAGE), ("every", S.EVERY)):
            col = QVBoxLayout()
            col.setSpacing(0)
            big = _label("wizbig", S.NONE_YET, self)
            col.addWidget(big)
            col.addWidget(_label("wizbigsub", sub, self, wrap=True))
            numbers.addLayout(col)
            self.big[key] = big
        numbers.addStretch(1)
        numbers.setContentsMargins(0, 0, 0, 0)
        self.numbers_part = QWidget(self)
        self.numbers_part.setLayout(numbers)
        self.box.addWidget(self.numbers_part)
        self.counting = _label("wizsub", S.COUNTING, self, wrap=True)
        self.box.addWidget(self.counting)
        self.box.addStretch(1)
        self.numbers = None
        self._band = None                   # the band the user moved to (None: Automatic's)
        self._shown = None
        self.number_paints = 0
        _show(self.numbers_part, False)

    def load(self, answers):
        a = answers or {}
        self.auto.set_quiet(bool(a.get("automatic", True)))
        self._band = a.get("band") or None
        self._paint()

    def answers(self):
        automatic = self.auto.isChecked()
        band = None
        if not automatic:
            bands = (self.numbers or {}).get("bands") or []
            band = bands[self.slider.index] if bands and 0 <= self.slider.index < len(bands) else self._band
        return {"automatic": automatic, "band": band}

    def entered(self):
        self.wiz.read_numbers(fresh=True)

    def show_numbers(self, numbers):
        self.numbers = numbers
        self._paint()

    def _auto_toggled(self, on):
        if on:
            self._band = None
        else:
            bands = (self.numbers or {}).get("bands") or []
            if bands and self.slider.index < len(bands):
                self._band = bands[self.slider.index]
        self._paint()

    def _moved(self, index):
        bands = (self.numbers or {}).get("bands") or []
        if index < len(bands):
            self._band = bands[index]
        if self.auto.isChecked():
            self.auto.setChecked(False)                   # moving the gem picks one yourself (the pop's rule)
        self._paint()

    def _band_now(self):
        n = self.numbers or {}
        bands = n.get("bands") or []
        if self.auto.isChecked() or self._band not in bands:
            for band in (n.get("auto_band") if self.auto.isChecked() else None, n.get("chosen")):
                if band in bands:
                    return band
            return bands[0] if bands else None
        return self._band

    def _paint(self):
        n = self.numbers
        _show(self.counting, n is None)
        _show(self.numbers_part, n is not None)
        if n is None:
            return
        bands = list(n.get("bands") or [])
        band = self._band_now()
        self.slider.set_bands(bands, bands.index(band) if band in bands else 0)
        words, coverage, every = (number_for(n, k, band) for k in ("words", "coverage", "every_hours"))
        shown = (words, coverage, every)
        if shown == self._shown:
            return
        self._shown = shown
        self.number_paints += 1
        _set_text(self.big["words"], S.WORDS_N.format(n=words) if isinstance(words, (int, float)) else S.NONE_YET)
        _set_text(self.big["coverage"], S.COVERAGE_N.format(pct=coverage) if isinstance(coverage, (int, float))
                  else S.NONE_YET)
        if isinstance(every, (int, float)):
            text = S.EVERY_N.format(h=every) if every >= 1 else S.EVERY_MIN.format(m=every * 60)
        else:
            text = S.NONE_YET
        _set_text(self.big["every"], text)
        from app.services import view_rows
        tone = view_rows.pct_tone(coverage if isinstance(coverage, (int, float)) else None)
        if self.big["coverage"].property("tone") != tone:
            self.big["coverage"].setProperty("tone", tone)
            self.big["coverage"].style().unpolish(self.big["coverage"])
            self.big["coverage"].style().polish(self.big["coverage"])

    def language_changed(self, language):
        self.numbers, self._shown = None, None
        self._paint()


def number_for(numbers, key, band):
    """One of `level_numbers`' figures (`words` · `coverage` · `every_hours`) for `band`: from its `numbers` per band,
    else the chosen band's own (None when it can't be said)."""
    per_band = numbers.get("numbers")
    if isinstance(per_band, dict) and isinstance(per_band.get(band), dict):
        return per_band[band].get(key)
    return numbers.get(key) if band == numbers.get("chosen") else None


# --- the wizard ------------------------------------------------------------------------------------------------------------ #
class SetupWizard(QWidget):
    """The wizard's frame and its six pages. `finished(how)`: "later" (*Finish later*), "done" (*Skip* on the last
    page, or a Generate that couldn't start) or "generated" (the window's Generate ended)."""
    finished = pyqtSignal(str)

    def __init__(self, shell, parent=None, api=None, miner=None):
        super().__init__(parent)
        style.styled(self, "wizard")
        self.shell = shell
        self.services = shell.services
        self.api = api if api is not None else services_api()
        self.miner = miner if miner is not None else miner_api()
        settings = self._settings()
        self.language = settings.get("target_language") if settings.get("target_language") in ("ja", "zh") else "ja"
        self.anki = None                    # the newest `anki_look` answer for the language (pages 2 and 4)
        self._anki_seq = 0
        self._anki_looking = False
        self._miner_seq = 0
        self._numbers_seq = 0
        self._rows_seq = 0
        self.install_opened = False         # *Install* opened the releases page: the page offers *Check again*
        self.installing = None              # the install route's cancel (a threading.Event) while it runs
        self.index = 0
        self.passed = set()
        self.generating = False
        self._saw_busy = False
        self._gone = False
        self._stopped = False               # the window's quit began: no question is asked from here on
        self._shown_at, self._painted = 0.0, False      # the page shown: when it came up, whether it was painted
        self._fresh = {}                    # Next / Skip: was its press taken on a settled page (`settled`)
        self._offered = None                # *Next* offered on the page shown (None: not painted yet)
        self._synced = None                 # (language, decks) of the first sync started (one per change, AD-10)
        self._count_wait = COUNT_AGAIN_MS   # page 6's next ask while it counts (twice as long each time)
        self._junban_found = None           # modules/junban looked for on a worker (None: not known yet)
        self.saves = []                     # (page, answers) as each *Next* saved them (what the wizard asked)
        self._finished = False              # `finish` written (Generate, or *Skip* on the last page)
        self.reading = None                 # SRC W1a: page 3's first look running (its Stop: a threading.Event)
        self._read_seq = 0
        # the folder picker (the system's own dialog; tests replace it)
        self.pick_dialog = lambda title, start: QFileDialog.getExistingDirectory(self, title, start)
        self.upgrading = self._upgrading(settings)      # brought over from 2.x: shown once, its choices picked (WZ-8)
        answers = self._preselect(self.language)
        self._build()
        for page in self.pages:
            page.load(answers.get(page.id) or {})
        self.setStyleSheet(sheet(style.current()[1]))
        windows.follow_doors(self)          # the doors (YouTube) shown once the modules were looked for
        adder = self._adder()               # --- W3.2 Q3: what + Add hands the writer shows in page 3's rows
        if adder is not None:
            adder.given.connect(self._added)
        lib = getattr(shell, "library_bridge", None)
        if lib is not None:
            lib.library_changed.connect(self._added)
        bridge.run_in_worker(windows.module_present, "junban", then=self.alive(self._junban_looked),
                             failed=lambda info: applog.log("wizard", f"looking for 順: {info[0]}"))
        closing = getattr(shell, "closing", None)
        if closing is not None:             # the quit began: a question still open answers No, a download stops
            closing.connect(self._shell_closing)
        heard = getattr(shell, "bridge", None)
        if heard is not None and hasattr(heard, "indexed"):
            heard.indexed.connect(self._indexed)
        self._go(0)

    # --- reading the settings ------------------------------------------------------------------------------------ #
    def _settings(self):
        return self.services.settings.get()

    def junban_off(self):
        """Why page 4 offers no control (順 switched off, or not in this Surasura), else None."""
        if self._settings().get("enable_junban") is False:
            return S.ORDER_OFF
        return S.ORDER_ABSENT if self._junban_found is False else None

    def _junban_looked(self, found):
        self._junban_found = bool(found)
        self.pages[3]._show()

    def _upgrading(self, settings):
        try:
            return bool(getattr(self.api, "upgrading", lambda _s: False)(thaw(settings)))
        except Exception as e:
            applog.log("wizard", f"upgrading: {e}")
            return False

    def _seen(self):
        """A 2.x profile's wizard closing unfinished: its pages seen, so it opens once (*Skip* / close keep the rest)."""
        if not self.upgrading or self._finished:
            return
        self._finished = True
        try:
            self.api.seen(self.services.settings)
        except Exception as e:
            applog.log("wizard", f"seen: {e}")

    def _preselect(self, language):
        try:
            pre = self.api.preselect(thaw(self._settings()), language) or {}
        except Exception as e:                            # a broken preselect still opens the wizard, on the draft's
            applog.log("wizard", f"preselect: {e}")
            pre = {}
        out = {pid: dict(pre.get(pid) or {}) for pid in PAGES}
        out["language"].setdefault("language", language)
        return out

    # --- building ----------------------------------------------------------------------------------------------- #
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = style.styled(QWidget(self), "wizhead")
        row = QHBoxLayout(head)
        top, side, bottom = theme.SPACING["header"]
        row.setContentsMargins(side, top, side, bottom)
        row.setSpacing(12)
        from app.qt.shell import Mark, Wordmark
        row.addWidget(Mark(path_utils.get_icon_path(), head))
        row.addWidget(Wordmark(head))
        row.addStretch(1)
        self.btn_later = _button(S.FINISH_LATER, S.FINISH_LATER_TIP, self.finish_later, head, name="wizlater")
        row.addWidget(self.btn_later)
        root.addWidget(head)
        self.hairline = Hairline(self)
        root.addWidget(self.hairline)
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.steps = StepList(self)
        self.steps.setFixedWidth(round(theme.size("wizard-steps", style.current()[1])))
        middle.addWidget(self.steps)
        self.stack = QStackedWidget(self)
        self.pages = [LanguagePage(self), KnownPage(self), ShowsPage(self), OrderPage(self), CardsPage(self),
                      LevelPage(self)]
        for page in self.pages:                           # a page taller than the window scrolls, never squeezed
            self.stack.addWidget(_scrolled(page))
        middle.addWidget(self.stack, 1)
        middle.addSpacing(_px(70))
        root.addLayout(middle, 1)
        foot = style.styled(QWidget(self), "wizfoot")
        foot.setMinimumHeight(_px(66))                    # (taller only for a line that wraps to a third line)
        row = QHBoxLayout(foot)
        row.setContentsMargins(_px(36), 0, _px(28), 0)
        row.setSpacing(_px(14))
        self.btn_back = _button(S.BACK, S.BACK_TIP, self.back, foot, name="wizquiet")
        row.addWidget(self.btn_back)
        row.addStretch(0)                                 # (the line, when shown, takes the room: it wraps there)
        self.say_line = _label("wizsay", "", foot, wrap=True)      # a long line wraps, never pushes or is cut
        self.say_line.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.say_line.setVisible(False)
        row.addWidget(self.say_line, 1)
        self.btn_skip = _button(S.SKIP, S.SKIP_TIP, lambda: self._pressed_through(self.btn_skip, self.skip), foot,
                                name="wizquiet")
        row.addWidget(self.btn_skip)
        self.btn_next = NextButton(foot)
        self.btn_next.clicked.connect(lambda _c=False: self._pressed_through(self.btn_next, self.next))
        row.addWidget(self.btn_next)
        for b in (self.btn_skip, self.btn_next):          # a press (mouse, Space, a reader's click) on a settled page
            b.pressed.connect(lambda b=b: self._fresh.__setitem__(b, self.settled()))
        root.addWidget(foot)
        self.footer = foot

    def keyPressEvent(self, event):
        """Enter is *Next* (the wizard's own: no button here is a default one) — a held key's repeats and a page not
        settled yet take nothing, and on another button Enter does nothing (that button acts on Space or a click, as
        itself). Esc is left alone (WZ-6)."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            focus = self.focusWidget()
            if event.isAutoRepeat() or not self.settled() or (isinstance(focus, QPushButton)
                                                               and focus is not self.btn_next):
                return
            self.enter()
            return
        super().keyPressEvent(event)

    # --- one action per press (AD-1 … AD-3) -------------------------------------------------------------------- #
    def settled(self):
        """Does the page shown take a press? Once it was painted and a double click's time has gone since it came up:
        the second click of a double click, or a quick second Enter, never lands on a page the learner hasn't seen."""
        return self._painted and (time.monotonic() - self._shown_at) * 1000 >= QApplication.doubleClickInterval()

    def _rearm(self):
        """The page shown changed under the learner (Anki's look came back, *Next* came up): a press waits again."""
        self._shown_at = time.monotonic()
        self._fresh.clear()

    def page_painted(self, page):
        if page is self.pages[self.index]:
            self._painted = True

    def _pressed_through(self, button, act):
        """A click on *Next* / *Skip*: `act` only when its press came on a settled page."""
        if self._fresh.pop(button, False):
            act()

    # --- the footer --------------------------------------------------------------------------------------------- #
    @property
    def page(self):
        return self.pages[self.index]

    def paint_footer(self):
        """*Back* · *Skip* · *Next* for the page shown (each repainted only when it changed)."""
        if not hasattr(self, "btn_next"):
            return
        last = self.index == len(PAGES) - 1
        busy = self.generating or self.reading is not None       # Generate, or page 3's first look (its Stop)
        _show(self.btn_back, self.index > 0)
        _show(self.btn_skip, self.index > 0)
        offered = self.page.next_offered() or busy
        if offered and self._offered is False:
            self._rearm()                                 # *Next* just came up: its first press waits (R2-1)
        self._offered = offered
        _show(self.btn_next, offered)
        text, tip = (S.GENERATE, S.GENERATE_TIP) if last else (S.NEXT, S.NEXT_TIP)
        if self.btn_next.text() != text:
            self.btn_next.setText(text)
            self.btn_next.setAccessibleName(text)
            self.btn_next.setToolTip(tip)
        for b in (self.btn_back, self.btn_skip, self.btn_next):
            if b.isEnabled() == busy:
                b.setEnabled(not busy)
        _show(self.btn_next.key, not busy)                 # the key's hint only while Enter does something

    def say(self, text):
        text = text or ""
        _set_text(self.say_line, _breakable(text))
        self.say_line.setAccessibleName(text)             # a reader hears the words, not the break marks
        _show(self.say_line, bool(text))

    # --- moving between pages ------------------------------------------------------------------------------------- #
    def _go(self, index):
        self.index = max(0, min(len(PAGES) - 1, index))
        self._shown_at, self._painted = time.monotonic(), False        # a press waits until it was seen (`settled`)
        self._offered = None
        self._fresh.clear()
        if self.say_line.text() and self.say_line.text() == getattr(self, "samples_said", None):
            self.say("")                                  # the samples' line is page 3's (AD-12)
        self.stack.setCurrentIndex(self.index)              # instant: no page light-up to borrow (module docstring)
        self.steps.set_state(self.index, self.passed)
        self.page.entered()
        self.paint_footer()
        if self.index == 0:
            self.start_focus()
        elif self.focusWidget() is None or not self.focusWidget().isVisible():
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def start_focus(self):
        """Where the keyboard starts (page 1: the glyphs, so ← → choose at once)."""
        self.page.focus_first()

    def enter(self):
        """Enter: *Next* (or **Generate**); *Skip* on a page that can't go on (never while Anki is being looked
        for: the answer may yet let it go on)."""
        if self.generating or self.reading is not None or (self._anki_looking and self.page.id in ("known", "order")):
            return
        if self.page.next_offered():
            self.next()
        elif self.index > 0:
            self.skip()

    def next(self):
        if self.generating or self._gone or self.reading is not None:
            return
        page = self.page
        if not page.next_offered():
            return
        if page.id == "shows" and page.folders:
            self._read_folders(list(page.folders))         # SRC W1a: the folders read first; the page stays for the rows
            return
        answers = page.answers()
        if page.id == "level":
            self._generate(answers)
            return
        self._save(page.id, answers)
        if page.id == "language" and answers.get("language") != self.language:
            self._language_changed(answers["language"])
        if page.id == "known" and answers.get("how") == "anki" and answers.get("decks"):
            synced = (self.language, tuple(answers["decks"]))
            if synced != self._synced:                    # Back and Next again over the same decks: no second sync
                self._synced = synced
                self._first_sync(list(answers["decks"]))
        self._advance()

    def _advance(self):
        self.passed.add(self.index)
        self._go(self.index + 1)

    def skip(self):
        """Nothing written; on the last page, setup finishes without Generate."""
        if self.generating or self.reading is not None or self.index == 0:
            return
        if self.index == len(PAGES) - 1:
            self._finish()
            self._close("done")
            return
        self._advance()

    def back(self):
        if self.generating or self.reading is not None or self.index == 0:
            return
        self._go(self.index - 1)                          # the pages keep their choices

    def finish_later(self):
        """Close and keep what was saved: never `onboarding_completed` (the contract)."""
        self._close("later")

    def _save(self, page_id, answers):
        self.saves.append((page_id, dict(answers)))
        try:
            before = self._settings()
            changes = self.api.save(self.services.settings, page_id, answers, self.language)
            if changes:
                from app.qt import settings_store
                settings_store.resume_connect(before, changes)          # *Make cards for me* on: Connect's marks
        except Exception as e:
            applog.log("wizard", f"saving {page_id}: {e}")
            windows.say_in_bar(self.shell, str(e))
            self.say(str(e))                              # the bar is under the wizard (AD-11)

    def _finish(self):
        self._finished = True
        try:
            self.api.finish(self.services.settings)
        except Exception as e:
            applog.log("wizard", f"finish: {e}")

    def _close(self, how):
        if self._gone:
            return
        self._gone = True
        self._seen()
        self._stop_workers()
        heard = getattr(self.shell, "bridge", None)
        for signal, slot in ((getattr(heard, "generate_changed", None), self._generate_state),
                             (getattr(heard, "indexed", None), self._indexed),
                             (getattr(self.shell, "closing", None), self._shell_closing)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError, AttributeError):
                pass
        self.finished.emit(how)

    def _stop_workers(self):
        """No worker left waiting on the wizard: a download under way stops (nothing is left half-made) and a question
        still open is answered No at once, its card gone with it."""
        self._stopped = True
        self.cancel_install()
        self.stop_reading()                               # page 3's look stops between files, keeping what came in
        for ask in self.findChildren(_AskFromWorker):
            ask.answer_now(False)
            if ask.card is not None and not sip.isdeleted(ask.card):
                ask.card.drop()

    def _shell_closing(self):
        """(`shell.closing`) The window's quit began — ✕, or the update's hand-over — with the wizard up (AD-4)."""
        if not self._gone and not sip.isdeleted(self):
            self._seen()
            self._stop_workers()

    def alive(self, fn):
        """`fn`, dropped once the wizard closed or was deleted: a worker's late answer is never painted."""
        def call(*args):
            if not self._gone and not sip.isdeleted(self):
                return fn(*args)
            return None
        return call

    # --- the language ------------------------------------------------------------------------------------------- #
    def _language_changed(self, language):
        """Page 1 picked another language: the pages that hang on it — the decks of *What you know* and *Card order* —
        start again from that language's preselects (their ✓ gone: not passed for this language yet); the others keep
        what was chosen and saved (AD-9) and only read again what they show for it."""
        self.language = language
        self.anki = None
        self._anki_seq += 1
        self._anki_looking = False
        answers = self._preselect(language)
        for page in self.pages[1:]:
            again = page.id in ("known", "order")
            kept = None if again else page.kept()
            page.language_changed(language)
            page.load((answers.get(page.id) or {}) if again else kept)
            if again:
                self.passed.discard(self.pages.index(page))

    # --- Anki (pages 2 and 4) ------------------------------------------------------------------------------------- #
    def look_anki(self):
        """`anki_look` on a worker; pages 2 and 4 repaint from its answer."""
        if self._anki_looking or self._gone:
            return
        self._anki_looking = True
        self._anki_seq += 1
        seq, language = self._anki_seq, self.language
        closed = {"open": False, "say": None, "decks": [], "preselected": []}
        bridge.run_in_worker(self.api.anki_look, thaw(self._settings()), language,
                             then=self.alive(lambda look: self._anki_looked(look, seq, language)),
                             failed=self.alive(lambda info: self._anki_looked(dict(closed, say=str(info[0])), seq,
                                                                              language)))

    def _anki_looked(self, look, seq, language):
        if seq != self._anki_seq or language != self.language:
            return
        self._anki_looking = False
        self.anki = dict(look or {})
        if self.page.id in ("known", "order"):
            self._rearm()                                 # its controls change now: never a press aimed before (R2-1)
        for page in self.pages:
            if hasattr(page, "anki_changed"):
                page.anki_changed()

    def known_decks(self):
        """The decks page 2 reads (page 4's deck is preselected from them)."""
        return self.pages[1].chosen_decks()

    def _first_sync(self, decks):
        """The first known-words sync, the user's own (the wizard's *Next* is that act): an `anki-sync` job; its result
        in the window's bar and the wizard's footer."""
        relay = bridge.Relay(self.shell)
        services, language, settings = self.services, self.language, thaw(self._settings())

        def ended(result):
            if not sip.isdeleted(relay):
                relay.deleteLater()
            line = sync_line(result)
            if line:
                windows.say_in_bar(self.shell, line)
            if not self._gone and not sip.isdeleted(self) and (line or self.say_line.text() == S.SYNC_STARTED):
                self.say(line)                            # its outcome (over any line since), or nothing more to say
        relay.said.connect(ended)

        def start():
            return self.api.first_sync(services.registry, settings, language, decks, relay.call,
                                       automation=lambda: getattr(services, "automation", None))

        def not_started(why):
            self._synced = None                           # Next again may try again
            if not sip.isdeleted(relay):
                relay.deleteLater()
            windows.say_in_bar(self.shell, why)
            if not self._gone and not sip.isdeleted(self):
                self.say(why)                             # the bar is under the wizard (AD-11)

        def started(job):
            if job is None:
                not_started(strings.ANKI_UPDATE_WAITS)
        self.say(S.SYNC_STARTED)
        bridge.run_in_worker(start, then=started, failed=lambda info: not_started(str(info[0])))

    # --- the doors and the library (page 2's importers, page 3) ------------------------------------------------------ #
    def door(self, name):
        op = next((o for o in windows.OPENERS if o.name == name), None)
        if op is None or not windows.available(op, self._settings(), self.language):
            return None
        return op

    def open_door(self, name):
        """An importer's (or YouTube's) window, through the window's own `windows.launch`; a door that can't open is
        said in the wizard too, as the bar says it (the bar is under the wizard, AD-11)."""
        op = self.door(name)
        if op is None:
            return

        def opening(shell, _open=op.open):
            try:
                return _open(shell)
            except Exception as e:
                if not self._gone and not sip.isdeleted(self):
                    self.say(strings.OPEN_FAILED.format(name=op.label, why=e))
                raise                                     # `launch` logs it and says it in the bar
        windows.launch(self.shell, op._replace(open=opening))

    def refresh(self):
        """(`windows.follow_doors`) The modules were looked for: the doors shown again."""
        if self._gone or sip.isdeleted(self):
            return
        if self.page.id == "shows":
            self.page.entered()
        elif self.page.id == "known":
            self.page.anki_changed()

    # --- W3.2 Q3: page 3's add actions are + Add's (`shell.adder`, app/qt/add_menu.py); the doors are the wizard's own
    def _adder(self):
        return getattr(self.shell, "adder", None)

    def can_add(self, name):
        """Whether page 3's `name` (`ADD_ACTIONS`) acts now: a door while it is available; Files and Folder while the
        window can copy into its library (+ Add's own rule); Folder also while the page reads folders itself."""
        if name in ADD_DOORS:
            return self.door(ADD_DOORS[name]) is not None
        if name == "folder" and self.can_read_folders():
            return True
        adder = self._adder()
        return adder is not None and bool(adder.entries((name,)))

    def add(self, name):
        if name in ADD_DOORS:
            self.open_door(ADD_DOORS[name])
            return
        if name == "folder" and self.can_read_folders():
            self.pick_folder()          # SRC W1 fix (Decision 2): as *Choose a folder…*, setup's own: Current (SRC-1)
            return
        adder = self._adder()
        if adder is not None:
            if name == "folder":
                adder.run(name, first=True)       # no folders part: still setup's first look
            else:
                adder.run(name)

    def _added(self, _text=None):
        """+ Add handed something to the writer: the rows read again (now, and as the library's view moves)."""
        if not self._gone and not sip.isdeleted(self) and self.page.id == "shows":
            self.read_rows()

    def add_samples(self):
        """*Try it with samples first*: the bundled samples copied into the empty tier folders (`seed_samples`, the
        Content Manager's own), on a worker; the disk sync takes them in and the rows follow."""
        language = self.language
        _enable(self.pages[2].btn_samples, False)

        def done(n):
            _enable(self.pages[2].btn_samples, True)
            self.samples_said = S.SAMPLES_ADDED_LINE.format(n=n) if n else S.SAMPLES_NONE
            self.say(self.samples_said)
            self.read_rows()
        bridge.run_in_worker(self.api.add_samples, language, then=self.alive(done),
                             failed=self.alive(lambda info: (_enable(self.pages[2].btn_samples, True),
                                                             self.say(str(info[0])))))
    # --- end W3.2 Q3

    # --- SRC W1a: the folders your shows and books are in (page 3) ---------------------------------------------- #
    def can_read_folders(self):
        """Page 3 offers its folders when the services can read them (`folder_refused`, `read_folders`)."""
        return callable(getattr(self.api, "read_folders", None))

    def pick_folder(self):
        """*Choose a folder…*: the system's folder dialog; the folder picked is checked by the store's own rule on a
        worker (`folder_refused`) — refused, its reason in plain words; else listed."""
        if self.reading is not None or self._gone:
            return
        page = self.pages[2]
        start = page.folders[-1] if page.folders else os.path.expanduser("~")
        path = self.pick_dialog(S.PICK_TITLE, start)
        if not path:
            return
        path = os.path.normpath(path)
        if page.has_folder(path):
            return
        refused = getattr(self.api, "folder_refused", None)
        if refused is None:
            page.add_folder(path)
            return
        language = self.language

        def checked(why):
            if language != self.language:
                return
            if why:
                page.refuse(S.FOLDER_REFUSED.format(folder=path, why=why))
            else:
                page.add_folder(path)
        bridge.run_in_worker(refused, language, path, then=self.alive(checked),
                             failed=self.alive(lambda info: page.refuse(S.FOLDER_REFUSED.format(folder=path,
                                                                                                why=info[1]))))

    def skip_folder(self):
        """K6 *Skip a folder…*: the system's folder dialog, starting in the last folder picked; the folder is checked by
        the store's own rule on a worker (`skip_refused`: inside a folder picked or read, never one itself) — refused,
        its reason in the page's refusal line; else listed, skipped on *Next* before the first look."""
        page = self.pages[2]
        if self.reading is not None or self._gone or not page.folders:
            return
        path = self.pick_dialog(S.SKIP_TITLE, page.folders[-1])
        if not path:
            return
        path = os.path.normpath(path)
        refused = getattr(self.api, "skip_refused", None)
        if refused is None:
            return
        language, chosen = self.language, list(page.folders)

        def checked(why):
            if language != self.language:
                return
            if why:
                page.refuse(S.FOLDER_REFUSED.format(folder=path, why=why))
            else:
                page.add_skip(path)
        bridge.run_in_worker(refused, language, path, chosen, then=self.alive(checked),
                             failed=self.alive(lambda info: page.refuse(S.FOLDER_REFUSED.format(folder=path,
                                                                                                why=info[1]))))

    def _read_folders(self, paths):
        """*Next* with folders picked: each added and given setup's first look (`read_folders`) on a worker — never the
        window's thread — its progress on the page with *Stop*; then the rows read again, and Needs you looks for its
        line (D1). The page stays: the next *Next* goes on."""
        page = self.pages[2]
        stop = threading.Event()
        self.reading = stop
        self._read_seq += 1
        seq, language = self._read_seq, self.language
        skips = list(page.skips)                              # K6: skipped before each folder's first look
        progress = bridge.Relay(self)
        progress.said.connect(lambda counts: self.alive(page.show_reading)(*counts))
        page.refuse(None)
        page.show_reading(0, 0)
        self.paint_footer()

        def ended(result):
            if not sip.isdeleted(progress):
                progress.deleteLater()
            if seq != self._read_seq:
                return
            self.reading = None
            self._rearm()                                     # the page changed under the learner: a press waits
            if skips:                                         # K6: the skips inside a folder it read are done with
                read = [os.path.normcase(os.path.normpath(p)) + os.sep for p in (result or {}).get("read") or ()]
                result = dict(result or {}, skips=[s for s in skips
                                                   if any(os.path.normcase(s).startswith(r) for r in read)])
            page.show_read(result)
            self.paint_footer()
            self.read_rows()
        shell = self.shell

        def needs_look():
            """D1's line, offered by the look: Needs you reads again — the wizard closed meanwhile (*Finish later*
            mid-look) or not."""
            needs = getattr(shell, "needs_you", None)
            if needs is not None and not sip.isdeleted(needs):
                needs.refresh()

        def failed(info):
            ended({"failed": [(p, str(info[1])) for p in paths], "read": list(paths)})
        read = (lambda *a: self.api.read_folders(*a, skips=skips)) if skips else self.api.read_folders
        bridge.run_in_worker(read, language, paths, lambda found, shows: progress.call((found, shows)),
                             stop.is_set, then=lambda result: (self.alive(ended)(result), needs_look()),
                             failed=lambda info: (self.alive(failed)(info), needs_look()))

    def stop_reading(self):
        """*Stop*: the look stops between files; what it took in is kept."""
        if self.reading is not None and not self.reading.is_set():
            self.reading.set()
            if not self._gone and not sip.isdeleted(self):
                self.pages[2].stopping()
    # --- end SRC W1a

    def read_rows(self):
        self._rows_seq += 1
        seq, language = self._rows_seq, self.language
        bridge.run_in_worker(self.api.library_rows, thaw(self._settings()), language,
                             then=self.alive(lambda rows: seq == self._rows_seq and language == self.language
                                             and self.pages[2].show_rows(rows)),
                             failed=lambda info: applog.log("wizard", f"library rows: {info[0]}"))

    # --- Anki Miner (page 5) -------------------------------------------------------------------------------------------- #
    def look_miner(self):
        self._miner_seq += 1
        seq, language = self._miner_seq, self.language
        bridge.run_in_worker(self.miner.look, thaw(self._settings()), language,
                             then=self.alive(lambda look: seq == self._miner_seq and language == self.language
                                             and self.pages[4].show_look(look)),
                             failed=lambda info: applog.log("wizard", f"Anki Miner's look: {info[0]}"))

    def install_miner(self):
        """*Install Anki Miner…*: its route on a worker (Sonic's yes, 2026-10-15: the installer from Anki Miner's GitHub
        release). Before any byte the worker asks here, in the window (`confirm.ask`: *Download* · *Not now*), and waits
        for the answer on its own thread; the download shows its progress with *Cancel* on the page; when the route
        ends the page looks again (`installer-closed`, `busy`) or offers *Check again* (`opened-releases`)."""
        if self.installing is not None or self._stopped:
            return
        page = self.pages[4]
        cancel = threading.Event()
        self.installing = cancel
        progress = bridge.Relay(self)
        progress.said.connect(lambda done_total: self.alive(page.show_progress)(*done_total))
        ask = _AskFromWorker(self)
        page.show_progress(None, None)

        def done(answer):
            self.installing = None
            progress.deleteLater()
            ask.deleteLater()
            page.show_progress(None, None)
            self.install_opened = self.install_opened or answer == "opened-releases"
            page.show_busy(answer == "busy")
            # `cancelled`: the learner's own Cancel, no browser (the route's result once M's route returns it: the
            # W-fix notes, For the lead)
            self.say({"opened-releases": S.INSTALL_OPENED, "cancelled": S.INSTALL_STOPPED}.get(answer, ""))
            if answer != "declined":
                self.look_miner()

        def failed(info):
            self.installing = None
            page.show_progress(None, None)
            self.say(str(info[0]))
        registry = getattr(self.services, "registry", None)
        install = getattr(self.miner, "install_as_job", None)
        if install is not None and registry is not None:            # the bar lists it once the learner says yes
            run = lambda: install(registry, lambda d, t: progress.call((d, t)), cancel, lambda _r: None, confirm=ask)
        else:
            run = lambda: self.miner.install(lambda d, t: progress.call((d, t)), cancel, lambda _r: None, confirm=ask)
        bridge.run_in_worker(run, then=self.alive(done), failed=self.alive(failed))

    def cancel_install(self):
        if self.installing is not None:
            self.installing.set()

    def open_star(self):
        windows.open_url(self.miner.STAR_URL)

    # --- the level and Generate (page 6) ----------------------------------------------------------------------------- #
    def read_numbers(self, fresh=False):
        """`level_numbers` on a worker; `fresh` (the page shown): its asking-again starts at its shortest wait."""
        if fresh:
            self._count_wait = COUNT_AGAIN_MS
        self._numbers_seq += 1
        seq, language = self._numbers_seq, self.language
        bridge.run_in_worker(self.api.level_numbers, thaw(self._settings()), language,
                             then=self.alive(lambda n: self._numbers(n, seq, language)),
                             failed=lambda info: applog.log("wizard", f"level numbers: {info[0]}"))

    def _numbers(self, numbers, seq, language):
        if seq != self._numbers_seq or language != self.language:
            return
        self.pages[5].show_numbers(numbers)
        if numbers is None:                               # still counting (or no shows yet): asked again while shown,
            self._count_later(seq)                        # each time twice as long after, and when the indexer ran

    def later(self, ms, fn):
        QTimer.singleShot(ms, fn)

    def _count_later(self, seq):
        wait = self._count_wait
        self._count_wait = min(COUNT_MOST_MS, wait * 2)
        self.later(wait, self.alive(lambda: self._count_tick(seq)))

    def _count_tick(self, seq):
        if self.page.id != "level" or seq != self._numbers_seq:
            return                                        # the page left, or asked again since
        if self.window().isMinimized():
            self.later(self._count_wait, self.alive(lambda: self._count_tick(seq)))      # nothing asked while away
            return
        self.read_numbers()

    def _indexed(self, language):
        """(`bridge.indexed`) The indexer ran: page 6, still counting for that language, asks at once (IK-18)."""
        if (not self._gone and not sip.isdeleted(self) and self.page.id == "level" and language == self.language
                and self.pages[5].numbers is None):
            self.read_numbers()

    def _generate(self, answers):
        """**Generate**: the level saved, setup finished (`onboarding_completed`), the window's Generate asked; the
        footer says *Making your list…* with the hairline until that run ends, then the wizard closes onto Current."""
        self._save("level", answers)
        self._finish()
        self.generating = True
        self._saw_busy = False
        self.hairline.set_value(0.0)
        self.say(S.MAKING)
        self.paint_footer()
        b = getattr(self.shell, "bridge", None)
        if b is not None:
            b.generate_changed.connect(self._generate_state)
        bridge.run_in_worker(self.api.generate, self.services, then=self.alive(self._accepted),
                             failed=self.alive(lambda info: self._accepted(False, str(info[0]))))

    def _accepted(self, ok, why=None):
        if not ok:
            windows.say_in_bar(self.shell, why or S.NOT_STARTED)
            self._close("done")

    def _generate_state(self, state):
        """The window's Generate, heard as the header hears it (`bridge.generate_changed`)."""
        if self._gone or not self.generating or getattr(state, "quiet", False):
            return                                        # an automatic run's states are never the learner's (AD-7)
        name = getattr(state, "state", None)
        if name in BUSY:
            self._saw_busy = True
            from app.services import generate as generate_module
            pct = generate_module.percent(state)
            self.hairline.set_value(0.0 if pct is None else pct / 100.0)
            self.say(S.MAKING_PCT.format(pct=pct) if pct is not None else S.MAKING)
        elif self._saw_busy:
            self.hairline.set_value(1.0)
            self._close("generated")


class _AskFromWorker(QObject):
    """The install's `confirm`: called on the route's worker, it asks the GUI thread for the in-window confirmation and
    waits there — on the worker, never the GUI thread — for the answer (No when the wizard closes meanwhile)."""
    asked = pyqtSignal()

    def __init__(self, wiz):
        super().__init__(wiz)
        self.wiz = wiz
        self._event = threading.Event()
        self._answer = False
        self.card = None
        self.asked.connect(self._ask, Qt.ConnectionType.QueuedConnection)
        self._gate = bridge.Gate(self)                    # the worker reaches it only so (`bridge.Gate`)
        # the wizard gone with its window (a question's card answers nothing then): the worker waits no longer
        wiz.destroyed.connect(lambda *_a, event=self._event: event.set())

    def __call__(self):
        self._event.clear()
        self._answer = False
        self._gate.emit("asked")
        if not self._gate.open:                           # the wizard is gone
            return False
        self._event.wait(ASK_WAIT_S)
        return self._answer

    def _ask(self):
        if sip.isdeleted(self.wiz) or self.wiz._gone or self.wiz._stopped:
            self.answer_now(False)
            return
        self.card = confirm.ask(self.wiz, S.INSTALL_ASK_TITLE, S.INSTALL_ASK_BODY, S.INSTALL_ASK_YES,
                                S.INSTALL_ASK_YES_TIP, no=S.INSTALL_ASK_NO, no_tip=S.INSTALL_ASK_NO_TIP,
                                on_answer=self.answer_now)
        # a card dropped with its window (✕, a hide) answers nothing: its end is the No (AD-4) — after a yes, nothing
        self.card.destroyed.connect(lambda *_a: self.answer_now(False))

    def answer_now(self, yes):
        """The answer, the first one only (a card's end after *Download* never turns it to No)."""
        if self._event.is_set():
            return
        self._answer = bool(yes)
        self._event.set()


def sync_line(result):
    """The first sync's result in words (the Anki window's own lines)."""
    from app import anki_window as AW
    kind, n = AW.result_view(result)
    if kind == "error":
        return n.get("text") or ""
    if kind == "synced":
        return strings.ANKI_SYNCED.format(**n)
    return ""
