"""*Which words get a card?* — the picker over the window, and the picture it shares with Essentials (Mado-EZC;
TheForge 3.0 `tracks/window/work/ez/SPEC-r2.md` §0.3, EZ2-7 redone, EZ2-9's clicks; every word PROVISIONAL).

- **`open_card_picker(shell)`** — the one entry point: Essentials' *Cards made for you › Change* and Your path's step ④
  (*Pick your cards*, Mado-EZP: over Current). One picker per window, built at its first open (a later open only sets
  its values); it opens over whatever page shows.
- **The result** (`Result`, round 2: one idea per screen): beside the choices, the cards the one looked at gives —
  *You'd get 4 cards from it*, each card drawn as a card (`CardTile`: its word, big; its sentence, the word lit and any
  other new word underlined amber, tagged *2 new words*; a card from a later episode dashed, saying so), then what is
  skipped and why; the choice's trade-off behind the heading's ?. The answer is Connect's own picker's (`card_sample`,
  run by the warm arrivals worker: `Sampler`; `card_sample.result` reads it per choice); until it answers, and with no
  episode of the kind, the bundled sample (喫茶店の朝; 孔乙己), named a sample.
- **Three steps, one question each:** ① which words (*Your list · RECOMMENDED* · *Only i+1 sentences* · *Every new
  word*, `PICK_MODES`: Settings' own choices and names, `settings_values.WORDS`; each card's line a state); ② *A card's sentence has a second new word* — only with
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
import functools
import html

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

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


# --- the result: the cards a choice gives, drawn as cards (round 2) ------------------------------------------------ #
WORD_INK = {"list": "accent", "rare": "accent-2", "second": "warn"}
PICK_MODES = ("list", "i1", "unknown")      # the choices' order (dropping *Every new word* is taking it out here)
TILES = 6                                   # cards drawn at most in the picker (Essentials: TILES_SMALL)
TILES_SMALL = 2


def _underlined(text, colour):
    return '<span style="color:{c}; text-decoration: underline">{t}</span>'.format(
        c=style.qss_colour(colour), t=html.escape(text))


def _marked(text, marks):
    """`text` as rich text with each (surface, colour) underlined in its colour (the first place each is found)."""
    found = []
    for surface, colour in marks:
        at = text.find(surface) if surface else -1
        if at >= 0 and not any(at < end and at + len(surface) > start for start, end, _c in found):
            found.append((at, at + len(surface), colour))
    out, at = [], 0
    for start, end, colour in sorted(found):
        out.append(html.escape(text[at:start]))
        out.append(_underlined(text[start:end], colour))
        at = end
    out.append(html.escape(text[at:]))
    return "".join(out)


def line_html(line):
    """A line as rich text: each drawn word underlined in its colour (on the list: the accent; rare: the iris's
    purple; a line's second new word: the heads-up amber) — the journey page's marks."""
    c = style.colours()
    marks = []
    for n, word in enumerate(line["words"]):
        kind = "rare" if not word.get("listed") else ("second" if n and line["new"] > 1 else "list")
        marks.append((word.get("surface") or word.get("word") or "", c[WORD_INK[kind]]))
    return _marked(line["text"], marks)


def card_html(card):
    """A card's sentence: its own word in the accent, any other new word in the heads-up amber."""
    c = style.colours()
    return _marked(card["text"], [(card["surface"], c["accent"])] + [(o, c["warn"]) for o in card["others"]])


class CardTile(QWidget):
    """One card as the learner would get it: its word, big; its sentence under it (its word lit, another new word
    underlined amber, tagged *2 new words*); a card from a later episode has a dashed edge and says so instead."""

    def __init__(self, card, parent=None):
        super().__init__(parent)
        self.card = card
        f = _f()
        box = QVBoxLayout(self)
        box.setContentsMargins(round(14 * f), round(10 * f), round(14 * f), round(12 * f))
        box.setSpacing(round(4 * f))
        top = QHBoxLayout()
        top.setSpacing(round(8 * f))
        self.word = QLabel(card["surface"], self)
        self.word.setObjectName("confirmtitle")
        self.word.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(self.word)
        top.addStretch(1)
        self.tag = None
        if card["outcome"] == "amber":
            self.tag = Chip(strings.PICK_TWO_NEW, "amber", strings.PICK_TWO_NEW_TIP, self)
            top.addWidget(self.tag, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(top)
        self.sentence = QLabel(self)
        self.sentence.setWordWrap(True)
        if card["text"]:
            self.sentence.setObjectName("confirmline")
            self.sentence.setTextFormat(Qt.TextFormat.RichText)
            self.sentence.setText(card_html(card))
        else:
            self.sentence.setObjectName("helpalso")
            self.sentence.setTextFormat(Qt.TextFormat.PlainText)
            self.sentence.setText(strings.PICK_LATER if card["outcome"] == "other" else strings.PICK_OTHER_LINE)
        self.sentence.setAccessibleName(card["text"] or self.sentence.text())
        box.addWidget(self.sentence)
        box.addStretch(1)
        self.setAccessibleName(card["surface"])
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.ensurePolished()                           # styled now: the picker measures it in this same turn

    def paintEvent(self, _event):
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        edge = {"amber": "warn", "other": "accent"}.get(self.card["outcome"], "line")
        pen = QPen(style.qcolor(c[edge]))
        pen.setWidthF(1.0)
        if self.card["outcome"] == "other":
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(style.qcolor(c["raised"]))
        radius = theme.RADII["r-sm"]
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.end()


def get_words(r, shown):
    """The result's heading: how many cards it gives (here, and from a later episode), *for example* when more than
    the cards drawn."""
    get = strings.PICK_GET.get(r["here"]) or strings.PICK_GET_MORE.format(n=r["here"])
    if r["elsewhere"]:
        get = (strings.PICK_GET_AWAY if r["exact"] else strings.PICK_GET_AWAY_UP_TO).format(get=get, m=r["elsewhere"])
    if shown < r["here"] + r["elsewhere"]:
        get = strings.PICK_FOR_EXAMPLE.format(get=get)
    return get


def skipped_words(r):
    if not r["skipped"]:
        return ""
    words = strings.PICK_SKIP_SEP.join(strings.PICK_SKIP_WHY[s["why"]].format(word=s["surface"]) for s in r["skipped"])
    more = r["skipped_all"] - len(r["skipped"])
    return strings.PICK_SKIPPED_MORE.format(words=words, n=more) if more > 0 else strings.PICK_SKIPPED.format(words=words)


def state_words(picture, mode):
    """A choice card's line: a state, never an explanation — *4 cards · 1 skipped*, *3 cards · 2 later*."""
    r = card_sample.result(picture, mode)
    parts = [strings.PICK_STATE.get(r["here"]) or strings.PICK_STATE_MORE.format(n=r["here"])]
    if r["elsewhere"]:
        parts.append(strings.PICK_STATE_LATER.format(m=r["elsewhere"]))
    if r["skipped_all"]:
        parts.append(strings.PICK_STATE_SKIPPED.format(k=r["skipped_all"]))
    return words_label(parts)


class Result(QWidget):
    """The result of one choice: where the cards come from, *You'd get N cards* with its trade-off behind a ?, the
    cards (two a row), and what is skipped, with why. `small`: Essentials' card — two cards, no heading, no skipped."""

    def __init__(self, parent=None, small=False):
        super().__init__(parent)
        self.small = small
        self.picture, self.mode = None, None
        self.tiles = []
        f = _f()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(round(8 * f))
        self.source = QLabel(self)
        self.source.setObjectName("helpalso")
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.source)
        head = QHBoxLayout()
        head.setSpacing(round(6 * f))
        self.heading = QLabel(self)
        self.heading.setObjectName("nexttitle")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self.heading)
        self.about = AboutMark(strings.HELP_MARK, self)
        head.addWidget(self.about, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        box.addLayout(head)
        self.grid = QGridLayout()
        self.grid.setSpacing(round(10 * f))
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        box.addLayout(self.grid)
        self.skipped = QLabel(self)
        self.skipped.setObjectName("helpalso")
        self.skipped.setTextFormat(Qt.TextFormat.PlainText)
        self.skipped.setWordWrap(True)
        box.addWidget(self.skipped)
        if small:
            self.heading.hide()
            self.about.hide()
            self.skipped.hide()

    def set(self, picture, mode):
        """The cards `mode` gives in `picture`, made again only when either changed."""
        if picture is self.picture and mode == self.mode:
            return
        self.picture, self.mode = picture, mode
        r = card_sample.result(picture, mode)
        for tile in self.tiles:
            self.grid.removeWidget(tile)
            tile.hide()
            tile.deleteLater()
        cards = r["cards"][:TILES_SMALL if self.small else TILES]
        self.tiles = [CardTile(card, self) for card in cards]
        for n, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, n // 2, n % 2)
            tile.show()                                 # (shown now, not a turn later: the picker measures them now)
        self.source.setText((strings.PICK_SAMPLE if r["sample"] else strings.PICK_SOURCE).format(name=r["source"]))
        self.source.setToolTip(strings.PICK_SAMPLE_TIP if r["sample"] else "")
        if not self.small:
            self.heading.setText(get_words(r, len(cards)))
            self.about.set_about(name_of(mode), strings.PICK_TRADEOFF[mode])
            self.skipped.setText(skipped_words(r))
            self.skipped.setVisible(bool(r["skipped"]))

    def set_mode(self, mode):
        if self.picture is not None:
            self.set(self.picture, mode)

    def card_words(self):
        """The cards' words, in order (a test's look)."""
        return [tile.card["surface"] for tile in self.tiles]


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
        try:
            ask(callback=self._relay.call)
        except Exception as e:                      # a worker that can't be asked: the picture as it is
            applog.log("settings", f"Which words get a card: the worker couldn't be asked: {e}")
            return False
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


@functools.lru_cache(maxsize=1)
def _junban_here():
    """{"modules.junban"} when 順 is in this Surasura (looked for once a process: a module never comes or goes while
    it runs), else an empty set."""
    import importlib.util
    try:
        return frozenset({"modules.junban"}) if importlib.util.find_spec("modules.junban") is not None else frozenset()
    except (ImportError, ValueError):
        return frozenset()


def ready_shown(settings, language, found=None):
    """Step ②: Card order 順 there (`found`: the modules a look found; None: looked for here) and on, and its *i+1
    first* applies (Japanese, the row's own rule: `settings_catalog`'s `junban_ready_first` row)."""
    from app.qt import settings_catalog as catalog
    if found is None:
        found = _junban_here()
    try:
        return bool(catalog.ROW["junban_ready_first"].when(settings, language, frozenset(found)))
    except Exception:
        return False


def _thaw(value):
    from app.services import settings as settings_service
    return settings_service.thaw(value)


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
        # ① which words: Settings' own three choice cards, and beside them the cards the one looked at gives
        self.page1 = QWidget(self)
        one = QHBoxLayout(self.page1)
        one.setContentsMargins(0, 0, 0, 0)
        one.setSpacing(round(22 * f))
        self.words = sc.Cards(self._word_options(None), "list", tooltip=strings.PICK_CHOICE_TIP.format(
            name=strings.PICK_TITLES[0]), name=strings.PICK_TITLES[0], parent=self.page1)
        self.words.changed.connect(self._words_changed)
        one.addWidget(self.words, 2, Qt.AlignmentFlag.AlignTop)
        self.result = Result(self.page1)
        one.addWidget(self.result, 3, Qt.AlignmentFlag.AlignTop)
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
        """Settings' choices as cards, in `PICK_MODES`' order: the name with its marks (RECOMMENDED for *Your list*,
        IN USE for the saved one) and, as its line, a state: the cards it gives here (*3 cards · 2 skipped*)."""
        out = []
        saved = (self.before or {}).get("words")
        for value in PICK_MODES:
            label = name_of(value)
            marks = [label, strings.PICK_RECOMMENDED if value == "list" else "",
                     strings.PICK_IN_USE if value == saved else ""]
            out.append((value, words_label(marks), state_words(picture, value) if picture is not None else "",
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
        self.result.set(picture, self.draft["words"] if self.draft else "list")
        self.words.set_options(self._word_options(picture))
        if self.draft is not None:
            self.words.set_value(self.draft["words"])
        lines = picture.get("lines") or []
        two = next((line for line in lines if line["new"] > 1), lines[0] if lines else None)
        self.two_line.setText(line_html(two) if two is not None else "")
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
        self.result.set_mode(value)
        self.place()                                    # (other cards: the panel's height may move)

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
        if not changes and line is None:
            self._told(done)
            return None
        if changes and store is not None:
            store.set(changes)
            from app.qt import settings_store
            settings_store.kick_on_release(settings, changes, store, win=self.shell)
        if line is not None:
            writer = getattr(services, "writer", None)
            if writer is None or writer.set_options(mine_line=int(line)) is None:
                line = None                                     # refused (read-only): the settings still saved
                self._refused(writer)
        self.written = (changes, line)
        undo_changes, _line = changes_of(self.draft, before, settings, self.language)    # each moved key as it was

        def undo():
            """Each key back as it was — only where it still holds what Done wrote (one changed since stays: the
            store's own value check, §6.11)."""
            if undo_changes and store is not None:
                now = store.get()
                back = {k: v for k, v in undo_changes.items() if _thaw(now.get(k)) == changes.get(k)}
                if back:
                    store.set(back)
            if line is not None and old_line is not None and mine_line(self.shell) in (line, None):
                writer = getattr(services, "writer", None)      # (a line moved since stays as it is)
                if writer is not None:
                    writer.set_options(mine_line=int(old_line))
        self.undo = undo
        name = name_of(self.draft["words"]) if "connect_mine_words" in changes else name_of(before["words"])
        toasts = getattr(self.shell, "toasts", None)
        if toasts is not None:
            toasts.show(strings.PICK_SAVED.format(name=name), undo=undo)
        self._told(done)
        return self.written

    def _refused(self, writer):
        """The library refused the line (read-only): the bar says why, in the store rows' words."""
        from app.qt import settings_strings as S
        from app.qt import windows
        raw = ""
        try:
            raw = (writer.reason() if writer is not None else "") or ""
        except Exception:
            pass
        reason = (strings.READ_ONLY_REASONS.get(raw) or raw) if raw else S.STORE_NO_LIBRARY_TIP
        try:
            windows.say_in_bar(self.shell, S.STORE_NOT_SAVED.format(reason=reason))
        except Exception as e:                      # a host with no bar: the log
            applog.log("settings", f"Which words get a card: the line wasn't kept: {e}")

    @staticmethod
    def _told(done):
        """Done's caller told, after the writes (Your path's step ④: the learner picked); its fault never stops one."""
        if done is None:
            return
        try:
            done()
        except Exception as e:
            applog.log("settings", f"Which words get a card: Done's callback failed: {e}")

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
            window.removeEventFilter(picker)
            picker.deleteLater()
        picker = window.__dict__["_card_picker"] = CardPicker(window, shell, language)
    services = getattr(shell, "services", None)
    store = getattr(services, "settings", None)
    settings = store.get() if store is not None else {}
    picker.start(settings, mine_line(shell), found, on_done)
    return picker
