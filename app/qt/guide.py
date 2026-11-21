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
  (Kantan-X's rule 2). No Done tab (rule 3).
- **Your path** (PR 2, Kantan-X's model; `app/services/path.py`; Mado-EZP, SPEC-r2 EZ2-1 / EZ2-3: the two tabs merged
  into **one list**, PROVISIONAL): once the learner has a library the panel is *Your path* — the four stages as a string
  of stones (`_StageRow`), then *Now · <stage>* (its steps, and a later step useful now), *New for you · <version>*
  (each release's notes, as below), *Later on your path* and *Done* — each step with **its own press** (*Do it*;
  *Again* on a done one; `act`, the shell runs it). Without a library, the panel is *What's new* alone.
- **Built when the look changes, never on an open** (R5): `set_look` rebuilds only for a new answer; an open with the
  same answer makes no widget. Nothing here reads a file: the shell asks the service on a worker.
"""
import collections
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from app import scrub, theme
from app.qt import motion, shadow, stones, strings, style
from app.qt.frame import _Away, _iris
from app.qt.tooltip import AboutMark, FitTitle

EDGE = 8                            # px the panel keeps from the window's edges
FIRST_LOOK_MS = 3000                # the first look, this long after the duties start (never on the start's path)
RELOOK_MS = 2000                    # the path's look, this long after the view's few numbers moved (one per burst)
FOCUS_RELOOK_S = 30                 # ... and on the window's activation, at most this often
STAGE_BAND = 30                     # px the panel's stage stones take (the now stone's ring whole)
SLICES_KEPT = 256                   # the last pieces' times kept (tests: the largest slice ≤ 4 ms; 64 fell under 3.0.12's 69 cards)


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
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, w=item.where: on_show(w))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.show_me = b
        self.setAccessibleName(item.text)


class _StageRow(QWidget):
    """The panel's top (EZ2-1): the four stages as the Next card's string of stones, spread across, each named under
    its stone — the stage to do now in full ink. Painted (no child widgets); `set_states` repaints only on a change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pathstages")
        self.states = ()
        f = theme.text_factor(style.current()[1])
        self._label_h = round(18 * f)
        self.setFixedHeight(STAGE_BAND + self._label_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        stones.notifier().ready.connect(self._sheet_ready)

    def _sheet_ready(self, _key):
        if self.states:
            self.update()

    def set_states(self, states):
        from app.services import path as path_service
        states = tuple(states or ())
        if states == self.states:
            return False
        self.states = states
        self.setAccessibleName(strings.PATH_STRING_NAME.format(stages=", ".join(
            strings.PATH_STAGE_NAME.format(stage=strings.PATH_STAGES[s], state=strings.PATH_STAGE_STATES[st])
            for s, st in zip(path_service.STAGES, states))))
        self.update()
        return True

    def paintEvent(self, _event):
        if not self.states:
            return
        from app.qt import next_card, rows
        from app.services import path as path_service
        c = style.colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        n = len(self.states)
        step = self.width() / n
        mid = STAGE_BAND / 2
        xs = [step * (i + 0.5) for i in range(n)]
        p.fillRect(QRectF(xs[0], mid - 0.5, xs[-1] - xs[0], 1), rows.c("string"))
        sheet = stones.get(self.devicePixelRatioF() or 1.0, style.current()[1])
        font = self.font()
        for x, stage, state in zip(xs, path_service.STAGES, self.states):
            at = QPointF(x, mid)
            if sheet is not None:
                what = next_card.stone_of(state)
                if what in sheet:
                    sheet.draw(p, at, what)
                if state == path_service.NOW and ("ring", "next") in sheet:
                    sheet.draw(p, at, ("ring", "next"))
            font.setWeight(QFont.Weight.DemiBold if state == path_service.NOW else QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(style.qcolor(c["ink"] if state == path_service.NOW else c["overlay-ink-faint"]))
            p.drawText(QRectF(x - step / 2, STAGE_BAND, step, self._label_h), Qt.AlignmentFlag.AlignCenter,
                       scrub.shown(strings.PATH_STAGES[stage]))
        p.end()


class _StepRow(QWidget):
    """One step of the path: its tick, its title with its line behind a ? (Kantan-S2, Sonic 2026-11-13: no subtitles),
    and **its own press** while the step applies (§0.2: *Do it*; a done one *Again*, to do it again — Sonic: "they would
    need to be able to see past ones to try again"). `later`: a step that can't apply yet: no tick, no press (never a
    dead end), its ? says when it will (`strings.PATH_WHEN`)."""

    def __init__(self, status, on_act, parent=None):
        from app.services import path as path_service
        super().__init__(parent)
        self.setObjectName("pathrow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.status = status
        self.later = later = not (status.useful or status.done)
        done = status.done
        step_id = status.step.id
        f = theme.text_factor(style.current()[1])
        row = QHBoxLayout(self)
        row.setContentsMargins(round(10 * f), round(8 * f), round(8 * f), round(8 * f))
        row.setSpacing(round(10 * f))
        self.tick = QLabel(strings.PATH_TICK if done else "", self)
        self.tick.setObjectName("pathtick")
        self.tick.setProperty("done", "true" if done else "false")
        self.tick.setProperty("later", "true" if later else "false")
        self.tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side = round(20 * f)
        self.tick.setFixedSize(side, side)
        row.addWidget(self.tick, 0, Qt.AlignmentFlag.AlignVCenter)
        title, text = strings.PATH_STEPS[step_id]
        if later:
            text = strings.PATH_WHEN[step_id]
        self.title = FitTitle(title, self)
        self.title.setObjectName("pathtitle")
        self.title.setProperty("later", "true" if later else "false")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        row.addWidget(self.title, 1000, Qt.AlignmentFlag.AlignVCenter)
        self.about = AboutMark(strings.HELP_MARK, self)
        self.about.set_about(strings.PATH_ABOUT_NAME.format(title=title), text)
        row.addWidget(self.about, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        self.press = None
        if status.useful and path_service.has_press(step_id):     # (④: only while it opens Level)
            words = strings.PATH_AGAIN if done else strings.PATH_DO
            b = QPushButton(words, self)
            b.setObjectName("guideshow")
            b.setToolTip(strings.PATH_DO_TIPS[step_id])
            b.setAccessibleName(strings.PATH_DO_NAME.format(press=words, title=title))
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, s=step_id: on_act(s))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.press = b
        if later:
            self.setAccessibleName(strings.PATH_LATER_NAME.format(title=title, when=text))
        else:
            self.setAccessibleName((strings.PATH_TICK_NAME if done else strings.PATH_OPEN_NAME).format(title=title))
            self.setAccessibleDescription(text)


class GuidePanel(motion.Overlay):
    """The ✦'s panel: *Your path* and what's new, **one list** (EZ2-1 / EZ2-3: its two tabs merged). `set_look(look)`
    paints a `guide.Look`, `set_path(path)` a `path.Path` (None: no library yet — the panel is *What's new* alone).
    `show_me` carries a place (`where`) to the shell, `act` a step to do (its own press, §0.2); the panel closes first.
    `opened` tells the shell the panel opened (the glow ends, the look is asked again on a worker)."""
    how = "pop"
    shadow_name = "menu"
    focus = True
    show_me = pyqtSignal(str)
    act = pyqtSignal(str)               # a step's own press, from its row (the shell runs it)
    opened = pyqtSignal()
    path_shown = pyqtSignal()           # the path came into view (its steps' glow is over)

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
        self.stage_row = _StageRow(self)                   # the four stages (only with a path)
        self.stage_row.hide()
        box.addWidget(self.stage_row)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("guidescroll")
        self.scroll.setWidgetResizable(False)              # (sized here, by its wrapped lines: `place`)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.TabFocus)     # (its arrows and Page keys read every line)
        box.addWidget(self.scroll, 1)
        self.body = None                    # the body in view
        self.look = None                    # the guide.Look shown
        self.path = None                    # the path.Path shown (None: no path)
        self._waiting = None                # a newer look, kept while the panel is open
        self._waiting_path = None           # ... and a newer path
        self.cards = []
        self.folds = []                     # (button, [fix cards], n)
        self.rows = []                      # the path's step rows
        self.builds = 0                     # bodies made (tests: once per new answer, never per open)
        self._job = [0, collections.deque()]   # [token, pieces]
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
        return True

    def has_news(self):
        return bool(self.look is not None and self.look.releases)

    def has_path(self):
        return self.path is not None

    def set_path(self, path):
        """Paint `path` (a `path.Path`, or None: no library yet). Held while the panel is open, as a look is; the same
        steps again change nothing. -> True when rebuilt."""
        if self.isVisible() or motion.opening_of(self) is not None:
            self._waiting_path = (path,)
            return False
        self._waiting_path = None
        old = self.path
        same = (old is None and path is None) or (old is not None and path is not None and
                                                  (old.steps, old.stages) == (path.steps, path.stages))
        self.path = path
        if same:
            return False
        self._build()
        return True

    def _build(self):
        """The body, **one piece per event-loop turn** (the lead, 2026-11-12: the 4 ms rule strict — a whole release
        built at once took 3.3–4.8 ms at 100–200 %): the empty body at once, then each line, row, card and fold in a
        turn of its own (`_step`). A newer answer cancels the pieces still to come; the panel places itself once the
        last lands. With a path: *Now · <stage>* (its steps and the later steps useful now), *New for you* (each
        release's notes), *Later on your path* and *Done* (`path.listed`); without one, the notes alone, as before."""
        from app.services import path as path_service
        f = self._f
        body = QWidget()
        body.setObjectName("guidebody")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, round(2 * f), 0)
        col.setSpacing(round(6 * f))
        self.cards, self.folds, self.rows = [], [], []
        releases = self.look.releases if self.look else ()
        p = self.path
        if p is not None:
            self.heading.setText(strings.GUIDE_PATH_HEADING)
            self.stage_row.set_states(p.stages)
        else:
            self.heading.setText(strings.GUIDE_HEADING_ONE.format(version=releases[0].release.version)
                                 if len(releases) == 1 else strings.GUIDE_HEADING)
        self.stage_row.setVisible(p is not None)
        self.setAccessibleName(strings.GUIDE_PATH_NAME if p is not None else strings.GUIDE_PANEL_NAME)
        pieces = []

        def label(name, text):
            pieces.append(lambda: self._row(col, self._label(name, text, body)))

        def card(item, folded=False, into=None):
            def make():
                c = _Card(item, self._show, body, folded=folded)
                if folded:
                    c.setVisible(False)
                    into[1].append(c)
                self.cards.append(c)
                self._row(col, c)
            pieces.append(make)

        def fold(entry):
            def make():
                b = QPushButton("", body)
                b.setObjectName("guidefold")
                b.setProperty("kind", "link")
                b.setToolTip(strings.GUIDE_FIXES_TIP)
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                b.setAutoDefault(False)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                self._row(col, b, Qt.AlignmentFlag.AlignLeft)
                entry[0] = b
                self.folds.append(entry)
                b.clicked.connect(lambda _c=False, e=entry: self._fold(e))
            pieces.append(make)

        def row(st):
            def make():
                r = _StepRow(st, self._act, body)
                self.rows.append(r)
                self._row(col, r)
            pieces.append(make)

        if p is not None:
            stage, now, later, done = path_service.listed(p.steps)
        else:
            stage, now, later, done = None, [], [], []
        if now:
            label("guidegroup", strings.PATH_NOW.format(stage=strings.PATH_STAGES[stage].upper()) if stage
                  else strings.PATH_NOW_LATER)
            for st in now:
                row(st)
        for shown in releases:
            if p is not None:
                label("guidegroup", strings.PATH_NEWS.format(version=shown.release.version))
            elif len(releases) > 1:                    # (one release, no path: the heading names it)
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
        for name, sts in ((strings.PATH_LATER, later), (strings.PATH_DONE, done)):
            if sts:
                label("guidegroup", name)
                for st in sts:
                    row(st)
        pieces.append(lambda: col.addStretch(1))
        self._start(body, pieces)

    # --- the pieces: the body built one piece per event-loop turn ------------------------------------------------ #
    def _start(self, body, pieces):
        """The body replaced by `body`, its `pieces` made one a turn (`_step`); a newer start cancels the pieces still
        to come."""
        job = self._job
        job[0] += 1
        job[1] = collections.deque(pieces)
        taken = self.scroll.takeWidget()
        if taken is not None:
            taken.hide()
            taken.deleteLater()
        self.scroll.setWidget(body)
        body.show()
        self.body = body
        self._next_piece(job[0])

    def building(self):
        """Whether a body's pieces are still on their way."""
        return bool(self._job[1])

    def _next_piece(self, token):
        QTimer.singleShot(0, lambda: self._step(token))

    def _step(self, token):
        """One piece, timed; the next in the next turn."""
        job = self._job if not sip.isdeleted(self) else None
        if job is None or token != job[0] or not job[1]:
            return
        t0 = time.perf_counter()
        job[1].popleft()()
        done = not job[1]
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

    def _act(self, step_id):
        self.close()
        self.act.emit(step_id)

    # --- opening, closing ------------------------------------------------------------------------------------------ #
    def _widths(self, p):
        """(the panel's width, its body's width before any scroll bar) under the window `p`."""
        width = min(round(theme.size("tray", style.current()[1])), max(1, p.width() - 2 * EDGE))
        m = self.layout().contentsMargins()
        return width, max(1, width - m.left() - m.right())

    def _row(self, col, widget, align=None):
        """`widget` into a body's column, polished and its lines wrapped once at the width `place()` will ask, in this
        piece's own turn: the first `place()` after a build then wraps nothing for the first time (every row's first wrap
        there took 4.0 ms of its 4 at nine releases' notes, 3.0.11's cut)."""
        if align is None:
            col.addWidget(widget)
        else:
            col.addWidget(widget, 0, align)
        p = self.parentWidget()
        widget.ensurePolished()                  # (its style's font first: a later polish would drop the wrap)
        if p is not None and widget.hasHeightForWidth():
            m = col.contentsMargins()
            widget.heightForWidth(max(1, self._widths(p)[1] - m.left() - m.right()))
        return widget

    def place(self):
        """Under the ✦, its right edge on the ✦'s, kept inside the window; as tall as its content up to the window's
        room, then it scrolls. The body is sized here to its lines wrapped at its width (a scroll area sizing it by
        its hints showed a bar where none was needed): the bar only when the content passes the room."""
        p = self.parentWidget()
        self.ensurePolished()
        width, inner = self._widths(p)
        lay = self.layout()
        m = lay.contentsMargins()
        b = self.button
        at = b.mapTo(p, b.rect().bottomRight())
        top = at.y() + 6
        head = self.heading.sizeHint().height() + lay.spacing() + m.top() + m.bottom()
        if not self.stage_row.isHidden():
            head += self.stage_row.height() + lay.spacing()
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
        """Tab and Shift+Tab go round the panel's own buttons and ?s, in their rows' order (the window behind keeps its
        order; a not-yet step's ? is its only control: Kantan-S2 r1 #2)."""
        ring = [self.scroll] + [b for b in self.findChildren(QWidget) if isinstance(b, (QPushButton, AboutMark))
                                and b.isVisible() and b.isEnabled()]
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
        if self.path is not None:
            self.path_shown.emit()

    def hideEvent(self, event):
        held = self.isAncestorOf(QApplication.focusWidget()) if QApplication.focusWidget() is not None else False
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)
        if held and self.button.isVisible():
            self.button.setFocus(Qt.FocusReason.OtherFocusReason)    # (the keyboard back where it opened the panel)
        if self._waiting is not None:
            self.set_look(self._waiting)
        if self._waiting_path is not None:
            self.set_path(self._waiting_path[0])

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
