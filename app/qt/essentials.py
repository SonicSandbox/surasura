"""Essentials — the four picture cards Settings opens on (Mado-EZC; TheForge 3.0 `tracks/window/work/ez/SPEC-r2.md`
§0.3 and SPEC.md EZ-1 / §2.2; they replace *Your setup*; every word PROVISIONAL).

`EssentialsCards` fills the `essentials` row's slot (`settings_live.Live`, which reads the facts on its workers and
calls `paint` when they or the settings move). Each card shows what you chose as a picture, its values as chips, and
*Change ›*:

- **Known words** — how many words count as known, and where they come from (your Anki cards, or an imported list);
  chips: Anki's state, whether suspended cards count. *Change ›*: Fine-tune's Known words (`page.reveal`).
- **Cards made for you** — the next episode's two-new-word line with what the current *Words to make cards from* makes
  of it (the picker's own picture, `card_picker.Picture`); chips: the choice, the deck setup picked (Kantan-T: named on
  Settings' first page), how many episodes ahead, *i+1 first* (with 順). *Change ›*: the picker (`card_picker.open_card_picker`).
- **Example sentences** — a sample line on a length ruler; chips: the length, how many a word, *i+1 only*.
  *Change ›*: Fine-tune's Example sentences.
- **Level** — a word at four of the slider's stops, dimmed past your band, on the iris bar; chips: Automatic, the band,
  its words and coverage (`settings_live.level_line`). *Change ›*: Fine-tune's Level.

Two columns while the slab holds two cards of `CARD_MIN` side by side, else one. Everything repaints only what moved
(S19): a card's chips and words are set only when they changed. Colours from the theme; words from `strings.py`.
"""
from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QFontMetricsF, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app import settings_manager, theme, word_selection
from app.qt import card_picker, strings, style
from app.qt.card_picker import Chip, _f, _font
from app.qt.tooltip import AboutMark

CARDS = ("known", "cards", "sentences", "level")
CARD_MIN = 360              # px at 100 % (× the text size): a card's narrowest; two side by side need twice this
RULER_MAX = 100             # characters: the ruler's end
RULER_MARKS = (0, 10, 50)   # characters marked under the ruler (and its end)


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def _iris(x0, x1):
    """The iris (the theme's) from x0 to x1, as the header's level line paints it (`frame._iris`)."""
    g = QLinearGradient(x0, 0, x1, 0)
    for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
        g.setColorAt(pos, style.qcolor(colour))
    return g


def chips_of(card, settings, language, facts, line=None, ready=False):
    """[(words, tone)] a card's chips show, from the settings and what the workers read (`facts`, Live's)."""
    from app.connect import settings_values
    from app.qt import settings_catalog as catalog
    from app.qt import settings_live
    value = lambda key: catalog.value_of(settings, key)        # noqa: E731 (the settings, else the defaults)
    if card == "known":
        out = []
        anki = facts.get("anki")
        if anki:
            from app.qt import settings_strings as S
            out.append((S.ANKI_WORDS[anki], "plain"))
        out.append((strings.ESS_SUSPENDED[bool(value("anki_sync_include_suspended"))], "plain"))
        return out
    if card == "cards":
        # Kantan-T (PROVISIONAL): the deck setup picked stays named on Settings' first page (Your setup's *Cards in
        # Anki* led with it), this language's only, while 順 is on
        from app.services import setup_wizard
        deck = setup_wizard.junban_deck(settings, language) if value("enable_junban") else None
        first = [(strings.ESS_DECK.format(deck=deck), "plain")] if deck else []
        if not settings_manager.connect_on(settings):
            return [(strings.ESS_CARDS_OFF, "plain")] + first
        mode = value("connect_mine_words") or "list"
        name = next((label for v, label, _l in settings_values.WORDS if v == mode), mode)
        out = [(name, "value")] + first
        if line is not None:
            out.append((strings.ESS_AHEAD.format(n=line), "plain"))
        if ready and value("junban_ready_first"):
            out.append((strings.ESS_READY_FIRST, "plain"))
        return out
    if card == "sentences":
        lo, hi = _length(settings)
        out = [(strings.ESS_LENGTH.format(lo=lo, hi=hi), "value"),
               (strings.ESS_UP_TO.format(n=value("logic.context.max_contexts")), "plain")]
        if value("only_i_plus_one"):
            out.append((strings.ESS_I1_ONLY, "plain"))
        return out
    from app.qt import settings_strings as S
    parts = [p for p in settings_live.level_line(settings, language, facts).split(S.SEP) if p]
    return [(p, "value" if n == 0 else "plain") for n, p in enumerate(parts)]


def _length(settings):
    """(min, preferred max) characters of a report's example line (the settings, else the defaults)."""
    from app.qt import settings_catalog as catalog
    return (int(catalog.value_of(settings, "logic.context.min_chars")),
            int(catalog.value_of(settings, "logic.context.preferred_max_chars")))


def known_from(settings, language, facts):
    """Where the known words come from, in words (`ESS_KNOWN_FROM`), or "" before anything is known."""
    from app.qt import settings_catalog as catalog
    if catalog._decks(settings, language):
        return strings.ESS_KNOWN_FROM["anki"]
    return strings.ESS_KNOWN_FROM["import"] if facts.get("known") else ""


def band_of(settings, facts):
    """The band the Level card marks: Automatic's (once read), else the saved one."""
    from app.qt import settings_catalog as catalog
    if catalog.value_of(settings, "logic.selection.auto") and facts.get("band"):
        return facts["band"]
    return catalog.value_of(settings, "logic.selection.band") or "common"


# --- the pictures ----------------------------------------------------------------------------------------------- #
class Ruler(QWidget):
    """The Example sentences card's ruler: 0 … RULER_MAX characters, your length lit in the iris, the sample line's
    own length a tick, the marks under it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.span = (10, 50)
        self.at = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, span, at):
        if (span, at) != (self.span, self.at):
            self.span, self.at = span, at
            self.update()

    def sizeHint(self):
        return QSize(round(200 * _f()), round(14 * _f() + QFontMetricsF(_font("row-sub")).height() + 8))

    def paintEvent(self, _event):
        c = style.colours()
        f = _f()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width() - 2
        track = QRectF(1, round(4 * f), w, round(6 * f))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(c["groove"]))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        x = lambda n: 1 + w * min(RULER_MAX, max(0, n)) / RULER_MAX        # noqa: E731
        lit = QRectF(x(self.span[0]), track.top(), max(2.0, x(self.span[1]) - x(self.span[0])), track.height())
        p.setBrush(_iris(lit.left(), lit.right()))
        p.drawRoundedRect(lit, track.height() / 2, track.height() / 2)
        pen = QPen(style.qcolor(c["ink"]))
        pen.setWidthF(max(1.0, round(2 * f)))
        p.setPen(pen)
        p.drawLine(QPointF(x(self.at), track.top() - 4 * f), QPointF(x(self.at), track.bottom() + 4 * f))
        p.setPen(style.qcolor(c["ink-faint"]))
        p.setFont(_font("row-sub"))
        top = track.bottom() + 6 * f
        h = QFontMetricsF(_font("row-sub")).height()
        for n in RULER_MARKS:                       # (the first mark from the ruler's left end: never cut)
            left = n == RULER_MARKS[0]
            p.drawText(QRectF(x(n) if left else x(n) - 20 * f, top, 40 * f, h),
                       int(Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignHCenter), str(n))
        p.drawText(QRectF(0, top, w + 1, h), int(Qt.AlignmentFlag.AlignRight),
                   strings.ESS_RULER_END.format(n=RULER_MAX))
        p.end()


class LevelBar(QWidget):
    """The Level card's bar: the iris, its knob at your band among the seven stops."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.band = "common"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_band(self, band):
        if band != self.band:
            self.band = band
            self.update()

    def sizeHint(self):
        return QSize(round(200 * _f()), round(22 * _f()))

    def place(self, band):
        bands = word_selection.BANDS_ORDER
        k = bands.index(band) if band in bands else 1
        return k / max(1, len(bands) - 1)

    def paintEvent(self, _event):
        c = style.colours()
        f = _f()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        knob = round(18 * f)
        track = QRectF(knob / 2, (self.height() - 6 * f) / 2, self.width() - knob, 6 * f)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_iris(track.left(), track.right()))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        cx = track.left() + track.width() * self.place(self.band)
        ring = QPen(style.qcolor(c["accent"]))
        ring.setWidthF(max(2.0, round(3 * f)))
        p.setPen(ring)
        p.setBrush(style.qcolor(c["ink"]))
        p.drawEllipse(QPointF(cx, self.height() / 2), knob / 2 - 1.5 * f, knob / 2 - 1.5 * f)
        p.end()


# --- a card ------------------------------------------------------------------------------------------------------ #
class Card(QWidget):
    """One Essentials card: its eyebrow and ?, its picture in its well (a layout the card paints), its chips and
    *Change ›*."""

    def __init__(self, card, on_change, parent=None):
        super().__init__(parent)
        from app.qt import settings_controls as sc
        self.card = card
        self.setObjectName(f"essentials-{card}")
        f = _f()
        box = QVBoxLayout(self)
        box.setContentsMargins(round(18 * f), round(16 * f), round(18 * f), round(14 * f))
        box.setSpacing(round(12 * f))
        head = QHBoxLayout()
        head.setSpacing(round(6 * f))
        self.title = QLabel(strings.ESS_TITLES[card].upper(), self)
        self.title.setObjectName("settingshead")
        self.title.setAccessibleName(strings.ESS_TITLES[card])
        head.addWidget(self.title)
        self.about = AboutMark(strings.HELP_MARK, self)
        self.about.set_about(strings.ESS_TITLES[card], strings.ESS_ABOUT[card])
        head.addWidget(self.about, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        box.addLayout(head)
        self.well = QVBoxLayout()           # the picture's well: painted by the card (one level less to settle)
        self.well.setContentsMargins(round(16 * f), round(14 * f), round(16 * f), round(14 * f))
        self.well.setSpacing(round(6 * f))
        box.addLayout(self.well, 1)
        foot = QHBoxLayout()
        foot.setSpacing(round(8 * f))
        self.chips_box = QHBoxLayout()
        self.chips_box.setSpacing(round(6 * f))
        foot.addLayout(self.chips_box)
        foot.addStretch(1)
        self.change = sc.Door(strings.ESS_CHANGE, tooltip=strings.ESS_CHANGE_TIPS[card],
                              name=strings.ESS_CHANGE_NAME.format(title=strings.ESS_TITLES[card]), parent=self)
        self.change.clicked.connect(lambda _c=False: on_change(card))
        foot.addWidget(self.change, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(foot)
        self.chips = []
        self.setMinimumWidth(round(CARD_MIN * f))

    def set_chips(self, chips):
        """[(words, tone)]: only what changed is redone."""
        if [(c.text(), c.tone()) for c in self.chips] == list(chips):
            return
        for chip in self.chips[len(chips):]:
            chip.hide()
            chip.deleteLater()
        self.chips = self.chips[:len(chips)]
        for n, (words, tone) in enumerate(chips):
            if n < len(self.chips):
                self.chips[n].set(words, tone)
            else:
                chip = Chip(words, tone, parent=self)
                self.chips_box.addWidget(chip)
                self.chips.append(chip)

    def chip_words(self):
        return [c.text() for c in self.chips]

    def paintEvent(self, _event):
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(style.qcolor(c["line"]))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(style.qcolor(c["raised"]))
        radius = theme.RADII["r"]
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.setPen(Qt.PenStyle.NoPen)                 # the picture's well: the cut, rounded
        p.setBrush(style.qcolor(c["cut"]))
        well = theme.RADII["r-sm"]
        p.drawRoundedRect(QRectF(self.well.geometry()), well, well)
        p.end()


def _text(parent, name, rich=False, align=None):
    label = QLabel(parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if align is not None:
        label.setAlignment(align)
    return label


class EssentialsCards(QWidget):
    """The four cards in the `essentials` row (`page`: the Settings page — its `reveal`, its shell)."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.setObjectName("essentials")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        f = _f()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(round(16 * f))
        self.cards = {card: Card(card, self.change, self) for card in CARDS}
        self.columns = 0
        # Known words: the number, *known*, where they come from
        well = self.cards["known"].well
        self.known_number = _text(self, "", align=Qt.AlignmentFlag.AlignCenter)
        self.known_number.setFont(_font("known-number"))
        self.known_word = _text(self, "helpalso", align=Qt.AlignmentFlag.AlignCenter)
        self.known_word.setText(strings.ESS_KNOWN_WORD)
        self.known_from = _text(self, "helpalso", align=Qt.AlignmentFlag.AlignCenter)
        for w in (self.known_number, self.known_word, self.known_from):
            well.addWidget(w)
        # Cards made for you: the picker's picture, its two-new-word line alone
        self.picture = card_picker.Picture(self, only_two=True, legend=False)
        self.cards["cards"].well.addWidget(self.picture)
        # Example sentences: a line on its ruler
        well = self.cards["sentences"].well
        self.sentence = _text(self, "nexttitle", rich=True)
        self.ruler = Ruler(self)
        well.addWidget(self.sentence)
        well.addWidget(self.ruler)
        # Level: four words over the bar
        well = self.cards["level"].well
        words = QHBoxLayout()
        self.level_words = []
        for _band, _word in strings.ESS_LEVEL_WORDS["ja"]:
            column = QVBoxLayout()
            word = _text(self, "nexttitle", align=Qt.AlignmentFlag.AlignCenter)
            band = _text(self, "helpalso", align=Qt.AlignmentFlag.AlignCenter)
            column.addWidget(word)
            column.addWidget(band)
            words.addLayout(column)
            self.level_words.append((word, band))
        well.addLayout(words)
        self.level_bar = LevelBar(self)
        well.addWidget(self.level_bar)
        self._arrange(force=True)
        self.shown = {}                 # card -> what it shows now (S19: set only when it moved)
        self.sampler = None

    # --- painting ------------------------------------------------------------------------------------------------ #
    def paint(self, settings, language, facts):
        """Every card from the settings and the facts as they stand: only what moved is set."""
        line = card_picker.mine_line(self.page.shell) if self.page.shell is not None else None
        ready = card_picker.ready_shown(settings, language, getattr(self.page, "_found", None))
        for card in CARDS:
            self.cards[card].set_chips(chips_of(card, settings, language, facts, line, ready))
        known = facts.get("known")
        self._set(self.known_number, strings.ESS_KNOWN_NUMBER.format(n=known) if known is not None else
                  strings.ESS_KNOWN_UNREAD)
        self._set(self.known_from, known_from(settings, language, facts))
        self._paint_picture(settings, language)
        text, word = strings.ESS_SAMPLE_SENTENCE.get(language) or strings.ESS_SAMPLE_SENTENCE["ja"]
        self._set(self.sentence, card_picker.line_html(
            {"text": text, "new": 1, "words": [{"surface": word, "listed": True}]}))
        self.ruler.set_values(_length(settings), len(text))
        band = band_of(settings, facts)
        bands = word_selection.BANDS_ORDER
        mine = bands.index(band) if band in bands else 1
        for (word_label, band_label), (stop, word) in zip(self.level_words, strings.ESS_LEVEL_WORDS.get(
                language) or strings.ESS_LEVEL_WORDS["ja"]):
            self._set(word_label, word)
            self._set(band_label, word_selection.band_label(stop))
            past = stop in bands and bands.index(stop) > mine
            word_label.setEnabled(not past)
            band_label.setEnabled(not past)
        self.level_bar.set_band(band)

    def _paint_picture(self, settings, language):
        shell = self.page.shell
        if shell is not None and (self.sampler is None or not _alive(self.sampler) or self.sampler.language != language):
            self.sampler = card_picker.sampler(shell, language, self.page.window())
            self.sampler.changed.connect(lambda: self._paint_picture(self.page._settings(), self.page.language))
        picture = self.sampler.picture if self.sampler is not None else card_picker.card_sample.fallback(language)
        self.picture.set_picture(picture)
        from app.qt import settings_catalog as catalog
        self.picture.set_mode(catalog.value_of(settings, "connect_mine_words") or "list")

    @staticmethod
    def _set(label, text):
        if label.text() != text:
            label.setText(text)

    def showEvent(self, event):
        super().showEvent(event)
        if self.sampler is not None:         # only a worker running already: opening Settings never starts one
            self.sampler.ask(start=False)    # (the worker keeps its answer: asked again, nothing is read again)

    # --- Change › ------------------------------------------------------------------------------------------------ #
    def change(self, card):
        if card == "cards":
            host = self.page.shell if self.page.shell is not None else self.page
            return card_picker.open_card_picker(host, getattr(self.page, "_found", None), window=self.page.window(),
                                                language=self.page.language)
        return self.page.reveal({"known": "known", "sentences": "sentences", "level": "level"}[card])

    # --- the columns ----------------------------------------------------------------------------------------------- #
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def _arrange(self, force=False):
        f = _f()
        columns = 2 if self.width() >= 2 * round(CARD_MIN * f) + self.grid.spacing() else 1
        if columns == self.columns and not force:
            return
        self.columns = columns
        for card in CARDS:
            self.grid.removeWidget(self.cards[card])
        for n, card in enumerate(CARDS):
            self.grid.addWidget(self.cards[card], n // columns, n % columns)
        for c in range(2):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)

    def minimumSizeHint(self):
        return QSize(round(CARD_MIN * _f()), super().minimumSizeHint().height())

    def card_chips(self, card):
        """A card's chips' words (a test's look)."""
        return self.cards[card].chip_words()
