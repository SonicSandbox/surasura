"""*Which words get a card?* — the picker over the window, and the picture it shares with Essentials (Mado-EZC;
TheForge 3.0 `tracks/window/work/ez/SPEC-r2.md` §0.3, EZ2-7 redone, EZ2-9's clicks; every word PROVISIONAL).

- **`open_card_picker(shell)`** — the one entry point: Essentials' *Cards made for you › Change* and Your path's step ④
  (*Pick your cards*, Mado-EZP: over Current). One picker per window, built at its first open (a later open only sets
  its values); it opens over whatever page shows.
- **The picture** (`Picture`): up to four lines of the learner's next episode with what each word gets under the choice
  looked at — a card (amber: its card holds a second new word), *another episode* (only *Only one-new-word sentences*,
  only when another episode of the mine line has it alone), *no card · rare* (not on the list), or none. The answer is
  Connect's own picker's (`card_sample`, run by the warm arrivals worker: `Sampler`); until it answers, and with no
  episode of the kind, the bundled sample (喫茶店の朝; 孔乙己), named a sample.
- **Three steps, one question each:** ① which words (*Your list · RECOMMENDED* first: Settings' own three choices,
  their names and lines one table, `settings_values.WORDS`); ② *A card's sentence has a second new word* — only with
  Card order 順 there and on, Japanese (`junban_ready_first`, the row's own rule); ③ *How far ahead?* — the library's
  mine line (5 · 10 · 20 · 40) and how many new cards may wait in Anki (this language's `connect_backlog_cap`).
  The controls are Settings' own (`settings_controls.Cards` / `Choice`).
- **Nothing is saved until *Done*** (EZ2-9): the foot counts the changes. *Cancel*, Esc, the mouse's Back or a click
  outside close it with nothing written. *Done*: one settings write (`services.settings.set`, the keys that moved),
  plus one store command when *How far ahead* moved (`services.writer.set_options(mine_line=)`), then the toast
  *✓ Saved: … · Undo*; Undo writes both back as they were.
- **Swap's marks are hidden until Swap lands** (3.1, lane 6): no ⇄, no *when Swap lands* foot (`SWAP` False).

GUI_Design_Guidelines_Qt: a `motion.Overlay` opened as a `dialog` over the scrim (the help card's look: `surface`),
registered with the window's router; Tab goes round its own controls; every button and control tipped; every word in
`strings.py`; colours from the theme only.
"""
import html

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from app import theme
from app.connect import settings_values
from app.qt import applog, bridge, motion, shadow, strings, style
from app.qt.confirm import MARGIN, Scrim, _register
from app.qt.tooltip import AboutMark
from app.services import card_sample

WIDTH = 1060                # px at 100 % (× the text size): the picker, at most (the window's width less its margins)
SWAP = False                # Swap's ⇄ marks and its foot: shown once Swap lands (3.1, SPEC-r2 §0.11 lane 6)
LIBRARY_LINE = 20           # the store's mine line when none is set (`library_store.MINE_LINE_DEFAULT`)
CAP_DEFAULT = 300           # `connect_backlog_cap`'s default (settings_manager)
STEPS = 3


def _f():
    return theme.text_factor(style.current()[1])


def _font(role, weight=None):
    """The app's font at `role`'s size (theme.TYPE × the text size)."""
    font = QFont(QApplication.font())
    font.setPointSizeF(style.point_size(role, style.current()[1]))
    px_weight = weight if weight is not None else theme.font(role, style.current()[1])[1]
    font.setWeight(QFont.Weight(min(900, max(100, int(px_weight)))))
    return font


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def words_label(names):
    """A choice's name, its marks after it (Settings' card label: one line)."""
    return " · ".join(n for n in names if n)


# --- a painted chip --------------------------------------------------------------------------------------------------- #
class Chip(QWidget):
    """A small pill: `tone` value (the accent's wash: a chosen value) · plain (the line's edge) · card (the accent's
    edge: a card) · amber (the heads-up edge: a card with a second new word) · other (a dashed accent edge: from another
    episode) · no (faint: no card). Its words and its tip; repainted only when they change."""

    EDGE = {"value": "accent-wash", "plain": "line", "card": "accent", "amber": "warn", "other": "accent", "no": "line"}
    INK = {"value": "ink", "plain": "ink-dim", "card": "ink", "amber": "warn", "other": "accent", "no": "ink-faint"}

    def __init__(self, text="", tone="plain", tip="", parent=None):
        super().__init__(parent)
        self._text, self._tone = "", "plain"
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set(text, tone, tip)

    def set(self, text, tone="plain", tip=""):
        if (text, tone) != (self._text, self._tone):
            self._text, self._tone = text, tone
            self.setAccessibleName(text)
            self.updateGeometry()
            self.update()
        if self.toolTip() != tip:
            self.setToolTip(tip)

    def text(self):
        return self._text

    def tone(self):
        return self._tone

    def sizeHint(self):
        m = QFontMetricsF(_font("chip"))
        f = _f()
        return QSize(int(m.horizontalAdvance(self._text) + 18 * f + 2), int(m.height() + 8 * f + 2))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2
        if self._tone == "value":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(style.qcolor(c["accent-wash"]))
        else:
            pen = QPen(style.qcolor(c[self.EDGE[self._tone]]))
            pen.setWidthF(1.0)
            if self._tone == "other":
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, radius, radius)
        p.setPen(style.qcolor(c[self.INK[self._tone]]))
        p.setFont(_font("chip"))
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._text)
        p.end()


# --- the picture ------------------------------------------------------------------------------------------------------ #
WORD_INK = {"list": "accent", "rare": "accent-2", "second": "warn"}


def line_html(line):
    """A picture's line as rich text: each drawn word in its colour, underlined (on the list: the accent; rare: the
    iris's purple; a line's second new word: the heads-up amber) — the journey page's marks."""
    c = style.colours()
    text = line["text"]
    out, at = [], 0
    marks = []
    for n, word in enumerate(line["words"]):
        surface = word.get("surface") or word.get("word") or ""
        found = text.find(surface, at) if surface else -1
        if found < 0:
            found = text.find(surface) if surface else -1
        if found < 0 or any(found < end and found + len(surface) > start for start, end, _k in marks):
            continue
        kind = "rare" if not word.get("listed") else ("second" if n and line["new"] > 1 else "list")
        marks.append((found, found + len(surface), kind))
    for start, end, kind in sorted(marks):
        out.append(html.escape(text[at:start]))
        out.append(f'<span style="color:{style.qss_colour(c[WORD_INK[kind]])}; text-decoration: underline">'
                   f'{html.escape(text[start:end])}</span>')
        at = end
    out.append(html.escape(text[at:]))
    return "".join(out)


def tinted(words, colour):
    """`words` in `colour` behind a short rule (the picture's legend), as rich text."""
    return '<span style="color:{c}">— {w}</span>'.format(c=style.qss_colour(colour), w=html.escape(words))


def chip_of(word, mode):
    """(words, tone, tip) of `word`'s chip under `mode`."""
    outcome = word["outcome"][mode]
    tone = {"card": "card", "amber": "amber", "other": "other", "rare": "no", "none": "no"}[outcome]
    name = word.get("surface") or word.get("word") or ""
    return strings.PICK_CHIP[outcome].format(word=name), tone, strings.PICK_CHIP_TIPS[outcome]


def new_badge(n):
    return strings.PICK_NEW.get(n) or strings.PICK_NEW_MORE.format(n=n)


class LineRow:
    """One line of the picture: the sentence (and its *N new*), the chips of what its words get, on the right. Its
    widgets are the picture's own children, its layout one of the picture's (no widget of its own: one level less for
    the Settings page to settle)."""

    def __init__(self, line, parent, into):
        self.line = line
        f = _f()
        self.box = QHBoxLayout()
        self.box.setContentsMargins(0, round(6 * f), 0, round(6 * f))
        self.box.setSpacing(round(10 * f))
        self.sentence = QLabel(parent)
        self.sentence.setObjectName("nexttitle")
        self.sentence.setTextFormat(Qt.TextFormat.RichText)
        self.sentence.setWordWrap(True)
        self.sentence.setText(line_html(line))
        self.sentence.setAccessibleName(line["text"])
        self.badge = Chip(new_badge(line["new"]), "amber" if line["new"] > 1 else "value", parent=parent)
        self.box.addWidget(self.sentence, 1)
        self.box.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.chips = [Chip(parent=parent) for _w in line["words"]]
        column = QVBoxLayout()                          # a line's chips one under another (the sentence keeps its room)
        column.setSpacing(round(4 * f))
        for chip in self.chips:
            column.addWidget(chip, 0, Qt.AlignmentFlag.AlignRight)
        self.box.addLayout(column)
        into.addLayout(self.box)
        self.into = into

    def set_mode(self, mode):
        for chip, word in zip(self.chips, self.line["words"]):
            chip.set(*chip_of(word, mode))

    def remove(self):
        self.into.removeItem(self.box)
        for w in [self.sentence, self.badge] + self.chips:
            w.hide()
            w.deleteLater()


class Picture(QWidget):
    """The picture: where its lines come from (*Your next episode · …* / *A sample episode · …*), the legend, its
    lines; `set_mode(mode)` repaints only the chips. `only_two`: the Essentials card's — the two-new-word line alone."""

    def __init__(self, parent=None, only_two=False, legend=True):
        super().__init__(parent)
        self.only_two = only_two
        self.picture = None
        self.mode = "list"
        self.rows = []
        f = _f()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(round(2 * f))
        head = QHBoxLayout()
        head.setSpacing(round(10 * f))
        self.source = QLabel(self)
        self.source.setObjectName("helpalso")
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self.source, 1)
        self.legend = []
        if legend:
            c = style.colours()
            for kind, words in strings.PICK_LEGEND:
                mark = QLabel(self)
                mark.setObjectName("helpalso")
                mark.setTextFormat(Qt.TextFormat.RichText)
                mark.setText(tinted(words, c[WORD_INK[kind]]))
                mark.setAccessibleName(words)
                head.addWidget(mark)
                self.legend.append(mark)
        self.box.addLayout(head)
        self.lines_box = QVBoxLayout()
        self.lines_box.setSpacing(0)
        self.box.addLayout(self.lines_box)
        self.outcome = QLabel(self)
        self.outcome.setObjectName("helpalso")
        self.outcome.setTextFormat(Qt.TextFormat.PlainText)
        self.outcome.setVisible(only_two)
        self.box.addWidget(self.outcome)

    def lines(self):
        if self.picture is None:
            return []
        lines = self.picture["lines"]
        if self.only_two:
            two = [line for line in lines if line["new"] > 1]
            return two[:1] or lines[:1]
        return lines

    def set_picture(self, picture):
        """A new picture: its lines made again (a picture changes rarely: an episode, a list, a new answer)."""
        if picture == self.picture:
            return
        self.picture = picture
        for row in self.rows:
            row.remove()
        self.rows = [LineRow(line, self, self.lines_box) for line in self.lines()]
        name = picture.get("source") or ""
        sample = picture.get("sample")
        self.source.setText((strings.PICK_SAMPLE if sample else strings.PICK_SOURCE).format(name=name))
        self.source.setToolTip(strings.PICK_SAMPLE_TIP if sample else "")
        self.set_mode(self.mode, force=True)

    def set_mode(self, mode, force=False):
        if mode == self.mode and not force:
            return
        self.mode = mode
        for row in self.rows:
            row.set_mode(mode)
        if self.only_two:
            self.outcome.setText(self.outcome_words())

    def outcome_words(self):
        """What the current choice makes of the Essentials card's line, in one line."""
        lines = self.lines()
        if not lines:
            return ""
        got = [w["outcome"][self.mode] for w in lines[0]["words"]]
        here = sum(o in ("card", "amber") for o in got)
        if here:
            return strings.ESS_FROM_HERE.get(here) or strings.ESS_FROM_HERE_MORE.format(n=here)
        return strings.ESS_FROM_AWAY if any(o == "other" for o in got) else strings.ESS_FROM_NONE


# --- the sampler: Connect's picker's answer, from the warm worker --------------------------------------------------- #
class Sampler(QObject):
    """The window's picture for its language (`sampler(shell)`): the bundled one at once, the worker's when it
    answers (`ask`, on every open of the picker — and on Essentials' show while the worker runs already: kept by the
    worker, so asking again reads nothing new). `changed` on a new one."""
    changed = pyqtSignal()

    def __init__(self, shell, language, parent=None):
        super().__init__(parent if parent is not None else shell)
        self.shell = shell
        self.language = language
        self.picture = card_sample.fallback(language)
        self._relay = bridge.Relay(self)
        self._relay.said.connect(self._got)
        self.asked = 0

    def ask(self, start=True):
        """Ask the warm worker for the picture. `start` False (Essentials shown): only a worker already running is
        asked — opening Settings never starts one; the picker's open does."""
        worker = None
        try:
            worker = self.shell.arrivals_worker()
        except Exception as e:                      # no worker here (a page alone): the bundled picture stays
            applog.log("settings", f"Which words get a card: no worker to ask: {e}")
        ask = getattr(worker, "sample", None)
        if ask is None or (not start and not getattr(worker, "running", False)):
            return False
        self.asked += 1
        ask(callback=self._relay.call)
        return True

    def _got(self, answer):
        picture = (answer or {}).get("picture") if isinstance(answer, dict) else None
        if not picture or not picture.get("lines") or picture == self.picture:
            return
        self.picture = picture
        self.changed.emit()


def sampler(shell, language=None, window=None):
    """The window's sampler for its language (one per window — kept on `window`, else on the shell — made again on a
    language switch). `shell`: what asks the worker (its `arrivals_worker`)."""
    language = language or getattr(shell, "language", "ja")
    keeper = window if window is not None else shell
    held = keeper.__dict__.get("_card_sampler")
    if held is None or not _alive(held) or held.language != language:
        held = keeper.__dict__["_card_sampler"] = Sampler(shell, language, parent=window)
    return held


# --- the values -------------------------------------------------------------------------------------------------- #
def mine_line(shell):
    """The library's mine line as the reader last read it (None: no library to write to)."""
    reader = getattr(getattr(shell, "services", None), "library", None)
    options = reader.options() if reader is not None else {}
    if not options:
        return None
    value = options.get("mine_line")
    return LIBRARY_LINE if value is None else int(value)


def ready_shown(settings, language, found=None):
    """Step ②: Card order 順 there (`found`: the modules a look found; None: looked for here) and on, and its *i+1
    first* applies (Japanese, the row's own rule: `settings_catalog`'s `junban_ready_first` row)."""
    from app.qt import settings_catalog as catalog
    if found is None:
        import importlib.util
        try:
            found = {"modules.junban"} if importlib.util.find_spec("modules.junban") is not None else set()
        except (ImportError, ValueError):
            found = set()
    try:
        return bool(catalog.ROW["junban_ready_first"].when(settings, language, frozenset(found)))
    except Exception:
        return False


def _cap(settings):
    """`connect_backlog_cap` as plain values (the service's settings are frozen: a per-language mapping read as one
    number would set every language's cap to this one's)."""
    from app.services import settings as settings_service
    return settings_service.thaw(settings.get("connect_backlog_cap", CAP_DEFAULT))


def values(settings, language, line):
    """{"words", "ready", "ahead", "wait"} as they stand."""
    words = settings.get("connect_mine_words") or "list"
    return {"words": words if words in card_sample.MODES else "list",
            "ready": bool(settings.get("junban_ready_first")),
            "ahead": line, "wait": settings_values.cap_of(_cap(settings), language)}


def changes_of(before, after, settings, language):
    """(the settings changes, the mine line or None) that take `before` to `after`."""
    changes = {}
    if after["words"] != before["words"]:
        changes["connect_mine_words"] = after["words"]
    if after["ready"] != before["ready"]:
        changes["junban_ready_first"] = after["ready"]
    if after["wait"] != before["wait"]:
        changes["connect_backlog_cap"] = settings_values.cap_value(_cap(settings), language, after["wait"])
    line = after["ahead"] if after["ahead"] != before["ahead"] and after["ahead"] is not None else None
    return changes, line


def name_of(mode):
    return next(label for value, label, _line in settings_values.WORDS if value == mode)


def counts_words(picture, mode):
    """A choice's count in the picture: *4 cards here*, *3 here · 2 from another episode* (the bundled one: up to)."""
    c = picture["counts"][mode]
    if not c["elsewhere"]:
        return strings.PICK_HERE.format(n=c["here"])
    words = strings.PICK_HERE_AWAY if picture.get("elsewhere_exact") else strings.PICK_HERE_UP_TO
    return words.format(n=c["here"], m=c["elsewhere"])


# --- the picker ------------------------------------------------------------------------------------------------------- #
class CardPicker(motion.Overlay):
    """The window's one picker (`open_card_picker`). `values` the choices as they stand, `draft` as picked."""
    how = "dialog"
    shadow_name = "dialog"
    focus = True

    def __init__(self, window, shell, language="ja"):
        super().__init__(window)
        self.setObjectName("cardpicker")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._window, self.shell = window, shell
        self.language = language
        self.step = 1
        self.before = self.draft = None
        self.settings = {}
        self.found = None
        self.written = None                 # the last Done's (changes, line) — a test's look
        self.on_done = None
        self._before_focus = None
        self._done = []
        from app.qt import settings_controls as sc
        f = self._f = _f()
        box = QVBoxLayout(self)
        pad = round(22 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(10 * f))
        top = QHBoxLayout()
        self.eyebrow = QLabel(strings.PICK_EYEBROW, self)
        self.eyebrow.setObjectName("nexteyebrow")
        top.addWidget(self.eyebrow)
        self.with_junban = Chip(strings.PICK_READY_WITH, "plain", parent=self)
        top.addWidget(self.with_junban)
        top.addStretch(1)
        self.dots = QLabel(self)
        self.dots.setObjectName("helpalso")
        top.addWidget(self.dots)
        box.addLayout(top)
        heading = QHBoxLayout()
        heading.setSpacing(round(8 * f))
        self.title = QLabel(self)
        self.title.setObjectName("confirmtitle")
        heading.addWidget(self.title)
        self.about = AboutMark(strings.HELP_MARK, self)
        heading.addWidget(self.about, 0, Qt.AlignmentFlag.AlignVCenter)
        heading.addStretch(1)
        box.addLayout(heading)
        self.where = Chip(strings.PICK_WHERE, "plain", strings.PICK_WHERE_TIP, self)
        box.addWidget(self.where, 0, Qt.AlignmentFlag.AlignLeft)
        # ① which words: the picture beside Settings' own three choice cards
        self.page1 = QWidget(self)
        one = QHBoxLayout(self.page1)
        one.setContentsMargins(0, 0, 0, 0)
        one.setSpacing(round(18 * f))
        self.picture = Picture(self.page1)
        one.addWidget(self.picture, 3)
        self.words = sc.Cards(self._word_options(None), "list", tooltip=strings.PICK_CHOICE_TIP.format(
            name=strings.PICK_TITLES[0]), name=strings.PICK_TITLES[0], parent=self.page1)
        self.words.changed.connect(self._words_changed)
        one.addWidget(self.words, 2, Qt.AlignmentFlag.AlignTop)
        box.addWidget(self.page1)
        # ② the second new word (with 順)
        self.page2 = QWidget(self)
        two = QVBoxLayout(self.page2)
        two.setContentsMargins(0, 0, 0, 0)
        two.setSpacing(round(10 * f))
        self.two_line = QLabel(self.page2)
        self.two_line.setObjectName("nexttitle")
        self.two_line.setTextFormat(Qt.TextFormat.RichText)
        self.two_line.setWordWrap(True)
        two.addWidget(self.two_line)
        self.ready = sc.Cards([(on, title, line) for on, title, line in strings.PICK_READY], False,
                              tooltip=strings.PICK_CHOICE_TIP.format(name=strings.PICK_TITLES[1]),
                              name=strings.PICK_TITLES[1], parent=self.page2)
        self.ready.changed.connect(lambda v: self._set("ready", bool(v)))
        two.addWidget(self.ready, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(self.page2)
        # ③ how far ahead
        self.page3 = QWidget(self)
        three = QHBoxLayout(self.page3)
        three.setContentsMargins(0, 0, 0, 0)
        three.setSpacing(round(40 * f))
        self.ahead_box, self.ahead = self._numbers(strings.PICK_AHEAD, strings.PICK_AHEAD_UNIT)
        self.wait_box, self.wait = self._numbers(strings.PICK_WAIT, "")
        self.ahead.changed.connect(lambda v: self._set("ahead", v))
        self.wait.changed.connect(lambda v: self._set("wait", v))
        three.addLayout(self.ahead_box)
        three.addLayout(self.wait_box)
        three.addStretch(1)
        box.addWidget(self.page3)
        # the foot
        foot = QHBoxLayout()
        foot.setSpacing(round(10 * f))
        self.cancel = self._button(strings.PICK_CANCEL, strings.PICK_CANCEL_TIP, self.close, foot)
        self.back = self._button(strings.PICK_BACK, strings.PICK_BACK_TIP, lambda: self.go(self.step - 1), foot,
                                 kind="link")
        self.summary = QLabel(self)
        self.summary.setObjectName("helpalso")
        foot.addWidget(self.summary, 1)
        self.next = self._button(strings.PICK_NEXT, strings.PICK_NEXT_TIP, lambda: self.go(self.step + 1), foot,
                                 kind="primary")
        self.done = self._button(strings.PICK_DONE, strings.PICK_DONE_TIP, self.finish, foot, kind="primary")
        box.addLayout(foot)
        self.scrim = Scrim(window, self.close)
        self.scrim.hide()
        self.shadow = shadow.Follower(self, self.shadow_name)
        window.installEventFilter(self)
        _register(window, self)
        self.sampler = sampler(shell, self.language, window)
        self.sampler.changed.connect(self._picture_changed)
        self.hide()

    def _numbers(self, heading, unit):
        from app.qt import settings_controls as sc
        box = QVBoxLayout()
        box.setSpacing(round(8 * self._f))
        label = QLabel(heading, self.page3)
        label.setObjectName("helpalso")
        box.addWidget(label)
        row = QHBoxLayout()
        control = sc.Choice([(0, "0")], 0, tooltip=heading, name=heading, parent=self.page3)
        row.addWidget(control)
        if unit:
            words = QLabel(unit, self.page3)
            words.setObjectName("helpalso")
            row.addWidget(words)
        row.addStretch(1)
        box.addLayout(row)
        return box, control

    def _button(self, text, tip, on_press, row, kind=None):
        b = QPushButton(text, self)
        b.setToolTip(tip)
        b.setAccessibleName(text)
        b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        b.setAutoDefault(False)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _c=False: on_press())
        row.addWidget(b)
        return b

    def _word_options(self, picture):
        """Settings' three choices as cards: its name with its marks (RECOMMENDED for *Your list*, IN USE for the
        saved one), its count in the picture and its line."""
        out = []
        saved = (self.before or {}).get("words")
        for value, label, line in settings_values.WORDS:
            marks = [label, strings.PICK_RECOMMENDED if value == "list" else "",
                     strings.PICK_IN_USE if value == saved else ""]
            count = counts_words(picture, value) if picture is not None else ""
            out.append((value, words_label(marks), words_label([count, line]),
                        strings.PICK_CHOICE_TIP.format(name=label)))
        return out

    # --- opening ----------------------------------------------------------------------------------------------- #
    def start(self, settings, line, found=None, on_done=None):
        """Open on step ①, from the values as they stand (`settings`, the library's mine `line`). `on_done()`: after a
        Done, whatever it changed (Your path's step ④: the learner picked) — never after Cancel, Esc or a click outside."""
        self.settings = settings
        self.found = found
        self.on_done = on_done
        self.before = values(settings, self.language, line)
        self.draft = dict(self.before)
        self.steps = (1, 2, 3) if ready_shown(settings, self.language, found) else (1, 3)
        self._fill_numbers()
        self.ready.set_value(self.draft["ready"])
        self._picture_changed()
        self.sampler.ask()
        self.go(1)
        self._open()

    def _fill_numbers(self):
        for control, key, choices in ((self.ahead, "ahead", strings.PICK_AHEAD_CHOICES),
                                      (self.wait, "wait", strings.PICK_WAIT_CHOICES)):
            now = self.draft[key]
            shown = sorted(set(choices) | ({now} if now is not None else set()))
            control.set_options([(n, str(n), strings.PICK_NUMBER_TIP.format(n=n)) for n in shown], now)
            control.setEnabled(now is not None)
            if key == "ahead":
                control.setToolTip(strings.PICK_AHEAD if now is not None else strings.PICK_NO_LIBRARY)

    def _picture_changed(self):
        picture = self.sampler.picture
        self.picture.set_picture(picture)
        self.picture.set_mode(self.draft["words"] if self.draft else "list")
        self.words.set_options(self._word_options(picture))
        if self.draft is not None:
            self.words.set_value(self.draft["words"])
        two = next((line for line in picture["lines"] if line["new"] > 1), picture["lines"][0])
        self.two_line.setText(line_html(two))
        self.place()

    # --- stepping ---------------------------------------------------------------------------------------------- #
    def go(self, step):
        steps = self.steps
        if step not in steps:
            step = min((s for s in steps if s > self.step), default=steps[-1]) if step > self.step else \
                max((s for s in steps if s < self.step), default=steps[0])
        self.step = step
        k = steps.index(step)
        for n, page in ((1, self.page1), (2, self.page2), (3, self.page3)):
            page.setVisible(n == step)
        self.title.setText(strings.PICK_TITLES[step - 1])
        self.about.set_about(strings.PICK_TITLES[step - 1], strings.PICK_WHAT if step == 1 else "")
        self.where.setVisible(step == 1)
        self.with_junban.setVisible(step == 2)
        self.dots.setText(" ".join("●" if i <= k else "○" for i in range(len(steps))))
        self.dots.setAccessibleName(strings.PICK_STEP_NAME.format(n=k + 1, total=len(steps)))
        self.back.setVisible(k > 0)
        last = k == len(steps) - 1
        self.next.setVisible(not last)
        self.done.setVisible(last)
        self._summary()
        self.place()
        if self.isVisible():
            (self.done if last else self.next).setFocus(Qt.FocusReason.OtherFocusReason)

    def _words_changed(self, value):
        self._set("words", value)
        self.picture.set_mode(value)
        self.place()                                    # (its chips' words changed: the lines may wrap again)

    def _set(self, key, value):
        if self.draft is None:
            return
        self.draft[key] = value
        self._summary()

    def _summary(self):
        n = self.changes()
        self.summary.setText(strings.PICK_CHANGES.get(n) or strings.PICK_CHANGES_MORE.format(n=n))

    def changes(self):
        if self.draft is None:
            return 0
        return sum(self.draft[k] != self.before[k] for k in ("words", "ready", "ahead", "wait"))

    # --- Done ------------------------------------------------------------------------------------------------- #
    def finish(self):
        """One settings write (the keys that moved) and one store command (the mine line, when it moved), then the
        toast with Undo. Nothing moved: it closes."""
        services = getattr(self.shell, "services", None)
        store = getattr(services, "settings", None)
        settings = store.get() if store is not None else self.settings
        changes, line = changes_of(self.before, self.draft, settings, self.language)
        before, old_line = dict(self.before), self.before["ahead"]
        self.close()
        done, self.on_done = self.on_done, None
        if done is not None:
            try:
                done()
            except Exception as e:                  # a caller's tick never stops the save
                applog.log("settings", f"Which words get a card: Done's callback failed: {e}")
        if not changes and line is None:
            return None
        if changes and store is not None:
            store.set(changes)
            from app.qt import settings_store
            settings_store.kick_on_release(settings, changes, store, win=self.shell)
        if line is not None:
            writer = getattr(services, "writer", None)
            if writer is None or writer.set_options(mine_line=int(line)) is None:
                line = None                                     # refused (read-only): the settings still saved
        self.written = (changes, line)
        undo_changes, _line = changes_of(self.draft, before, settings, self.language)    # each moved key as it was

        def undo():
            if undo_changes and store is not None:
                store.set(undo_changes)
            if line is not None and old_line is not None:
                writer = getattr(services, "writer", None)
                if writer is not None:
                    writer.set_options(mine_line=int(old_line))
        self.undo = undo
        name = name_of(self.draft["words"]) if "connect_mine_words" in changes else name_of(before["words"])
        toasts = getattr(self.shell, "toasts", None)
        if toasts is not None:
            toasts.show(strings.PICK_SAVED.format(name=name), undo=undo)
        return self.written

    # --- the overlay's place, its Tab ring, its close ---------------------------------------------------------- #
    def place(self):
        w = self._window
        self.ensurePolished()
        width = min(round(WIDTH * self._f), max(1, w.width() - 2 * MARGIN))
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        height = min(height, max(1, w.height() - 2 * MARGIN))
        geometry = QRect((w.width() - width) // 2, max(0, (w.height() - height) // 2), width, height)
        if geometry != self.geometry():
            self.setGeometry(geometry)

    def _open(self):
        self.place()
        if self.isVisible() or motion.opening_of(self) is not None:
            return
        self._before_focus = QApplication.focusWidget()
        self.scrim.setGeometry(self._window.rect())
        self.scrim.show()
        self.scrim.raise_()
        self.raise_()
        motion.open_overlay(self, self.how, self.shadow_name, on_done=self._focus_first, focus=True)

    def _focus_first(self):
        if self.isVisible():
            (self.done if self.done.isVisible() else self.next).setFocus(Qt.FocusReason.OtherFocusReason)

    def focusNextPrevChild(self, next_):
        """Tab and Shift+Tab go round the picker's own controls, never out to the window behind the scrim."""
        ring = [w for w in self.findChildren(QWidget) if w.focusPolicy() & Qt.FocusPolicy.TabFocus
                and w.isVisible() and w.isEnabled() and not isinstance(w, QLabel)]
        if not ring:
            return True
        now = QApplication.focusWidget()
        i = ring.index(now) if now in ring else -1
        ring[(i + (1 if next_ else -1)) % len(ring)].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous():
            self._closed()

    def closeEvent(self, event):
        super().closeEvent(event)
        self._closed()

    def _closed(self):
        self.scrim.hide()
        before, self._before_focus = self._before_focus, None
        try:
            if before is not None and not sip.isdeleted(before) and before.isVisible():
                before.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_window", None) and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(style.colours()["surface"]))
        radius = theme.RADII["dialog"]
        p.drawRoundedRect(QRectF(self.rect()), radius, radius)
        p.end()


def open_card_picker(shell, found=None, window=None, language=None, on_done=None):
    """The one entry point (Essentials' *Change ›*; Your path's step ④, Mado-EZP: *Pick your cards* over Current): the
    window's picker opened on step ①, from the settings and the library's mine line as they stand -> the picker.
    `shell`: the main window (its `services`, `toasts`, `arrivals_worker`, `language`) or what stands for it;
    `window`: the window it opens over (default: the shell's own); `found`: the modules the Settings page's look found
    (else looked for here); `on_done()`: after Done (Your path: `lambda: shell.path_moment("yours")`, Mado-EZP's
    `ShellWindow.pick_your_cards`). One picker per window, made at its first open."""
    if window is None:
        window = shell.window() if isinstance(shell, QWidget) else None
    if window is None:
        raise ValueError("the picker needs a window to open over")
    language = language or getattr(shell, "language", None) or "ja"
    picker = window.__dict__.get("_card_picker")
    if picker is None or not _alive(picker) or picker.language != language:
        if picker is not None and _alive(picker):
            picker.close()
            picker.deleteLater()
        picker = window.__dict__["_card_picker"] = CardPicker(window, shell, language)
    services = getattr(shell, "services", None)
    store = getattr(services, "settings", None)
    settings = store.get() if store is not None else {}
    picker.start(settings, mine_line(shell), found, on_done)
    return picker
