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
- **Your path** (PR 2, Kantan-X's model; `app/services/path.py`): a second tab once the learner has a library — *Your
  first cards* (three steps, folded to one ticked line once done) and *When you're ready* (only the steps useful now,
  or done), each undone step with **Show me**. The tabs show only with a path; alone, the panel is *What's new*.
- **Built when the look changes, never on an open** (R5): `set_look` rebuilds only for a new answer; an open with the
  same answer makes no widget. Nothing here reads a file: the shell asks the service on a worker.
"""
import collections
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                             QToolButton,
                             QVBoxLayout, QWidget)

from app import theme
from app.qt import motion, shadow, strings, style
from app.qt.frame import _Away, _iris

EDGE = 8                            # px the panel keeps from the window's edges
FIRST_LOOK_MS = 3000                # the first look, this long after the duties start (never on the start's path)
RELOOK_MS = 2000                    # the path's look, this long after the view's few numbers moved (one per burst)
FOCUS_RELOOK_S = 30                 # ... and on the window's activation, at most this often
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
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, w=item.where: on_show(w))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.show_me = b
        self.setAccessibleName(item.text)


class _StepRow(QWidget):
    """One step of the path: its tick, its title and line, and *Show me* while it isn't done. `line` alone: chapter 1
    folded into one ticked line."""

    def __init__(self, status, on_show, parent=None, line=None):
        super().__init__(parent)
        self.setObjectName("pathrow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.status = status
        done = status is None or status.done
        f = theme.text_factor(style.current()[1])
        row = QHBoxLayout(self)
        row.setContentsMargins(round(10 * f), round(8 * f), round(8 * f), round(8 * f))
        row.setSpacing(round(10 * f))
        self.tick = QLabel(strings.PATH_TICK if done else "", self)
        self.tick.setObjectName("pathtick")
        self.tick.setProperty("done", "true" if done else "false")
        self.tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side = round(20 * f)
        self.tick.setFixedSize(side, side)
        row.addWidget(self.tick, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(round(2 * f))
        if status is not None:
            title, text = strings.PATH_STEPS[status.step.id]
        else:
            title, text = None, line
        self.title = None
        if title:
            self.title = QLabel(title, self)
            self.title.setObjectName("pathtitle")
            words.addWidget(self.title)
        self.line = QLabel(text, self)
        self.line.setObjectName("pathline")
        for label in (self.title, self.line):
            if label is not None:
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        words.addWidget(self.line)
        row.addLayout(words, 1)
        self.show_me = None
        if status is not None and not done:
            b = QPushButton(strings.GUIDE_SHOW_ME, self)
            b.setObjectName("guideshow")
            b.setToolTip(strings.GUIDE_SHOW_ME_TIP)
            b.setAccessibleName(strings.GUIDE_SHOW_ME_NAME.format(text=title))
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, w=status.step.where: on_show(w))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.show_me = b
        name = title or text
        self.setAccessibleName((strings.PATH_TICK_NAME if done else strings.PATH_OPEN_NAME).format(title=name))


class GuidePanel(motion.Overlay):
    """The ✦'s panel. `set_look(look)` paints a `guide.Look`; `show_me` carries a place (`where`) to the shell, which
    closes nothing itself — the panel closes first. `opened` tells the shell the panel opened (the glow ends, the look
    is asked again on a worker)."""
    how = "pop"
    shadow_name = "menu"
    focus = True
    show_me = pyqtSignal(str)
    opened = pyqtSignal()
    path_shown = pyqtSignal()           # the *Your path* tab came into view (its glow is over)

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
        self.tabs = QWidget(self)                          # *What's new* · *Your path* (only with a path)
        tabs = QHBoxLayout(self.tabs)
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setSpacing(round(4 * f))
        self.tab_group = QButtonGroup(self.tabs)
        self.tab_group.setExclusive(True)
        self.tab_buttons = {}
        for name, text, tip in (("news", strings.GUIDE_TAB_NEWS, strings.GUIDE_TAB_NEWS_TIP),
                                ("path", strings.GUIDE_TAB_PATH, strings.GUIDE_TAB_PATH_TIP)):
            b = QPushButton(text, self.tabs)
            b.setObjectName("guidetab")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setAccessibleName(text)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, n=name: self.show_tab(n))
            b.installEventFilter(self)                     # ← → between the two (one Tab stop's way: the guide §3)
            self.tab_group.addButton(b)
            self.tab_buttons[name] = b
            tabs.addWidget(b, 1)
        self.tabs.hide()
        box.addWidget(self.tabs)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("guidescroll")
        self.scroll.setWidgetResizable(False)              # (sized here, by its wrapped lines: `place`)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.TabFocus)     # (its arrows and Page keys read every line)
        box.addWidget(self.scroll, 1)
        self.body = None                    # the body in view (the tab's)
        self._bodies = {"news": None, "path": None}
        self.tab = "news"
        self.look = None                    # the guide.Look shown
        self.path = None                    # the path.Path shown (None: no path — no tabs)
        self._waiting = None                # a newer look, kept while the panel is open
        self._waiting_path = None           # ... and a newer path
        self.cards = []
        self.folds = []                     # (button, [fix cards], n)
        self.rows = []                      # the path's step rows
        self.builds = 0                     # the news body made (tests: once per new look, never per open)
        self.path_builds = 0                # the path body made
        self._jobs = {"news": [0, collections.deque()], "path": [0, collections.deque()]}   # [token, pieces]
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

    def has_path(self):
        return self.path is not None

    def set_path(self, path):
        """Paint `path` (a `path.Path`, or None: no library yet — no tabs). Held while the panel is open, as a look is;
        the same steps again change nothing. -> True when rebuilt."""
        if self.isVisible() or motion.opening_of(self) is not None:
            self._waiting_path = (path,)
            return False
        self._waiting_path = None
        old = self.path
        same = old is not None and path is not None and (old.steps, old.first_done) == (path.steps, path.first_done)
        self.path = path
        if (old is None) != (path is None):                # the tabs come or go: the news body's version line too
            self.tabs.setVisible(path is not None)
            self.heading.setVisible(path is None)
            if path is None:
                self.show_tab("news")
            if self.look is not None:
                self._build()
        if same or path is None:
            return False
        self._build_path()
        return True

    def _build(self):
        """A new answer's body, **one piece per event-loop turn** (the lead, 2026-11-12: the 4 ms rule strict — a whole
        release built at once took 3.3–4.8 ms at 100–200 %): the empty body at once, then each line, card and fold
        piece in a turn of its own (`_step`). A newer answer cancels the pieces still to come; the panel places itself
        once the last lands. `builds` counts finished bodies."""
        f = self._f
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
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                b.setAutoDefault(False)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                col.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
                entry[0] = b
                self.folds.append(entry)
                b.clicked.connect(lambda _c=False, e=entry: self._fold(e))
            pieces.append(make)

        for shown in releases:
            if len(releases) > 1 or self.path is not None:     # (one release, no tabs: the heading names it)
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
        self._start("news", body, pieces)

    def _build_path(self):
        """The *Your path* body, in pieces as the news body is: *Your first cards* (its three steps, or one ticked line
        once done), *When you're ready* (the steps useful now or done, and *n of m*), a closing line while more steps
        may still come."""
        from app.services import path as path_service
        f = self._f
        body = QWidget()
        body.setObjectName("guidebody")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, round(2 * f), 0)
        col.setSpacing(round(6 * f))
        self.rows = []
        pieces = []
        p = self.path

        def header(chapter, right):
            pieces.append(lambda: col.addWidget(self._chapter(chapter, right, body)))

        def row(st):
            def make():
                r = _StepRow(st, self._show, body)
                self.rows.append(r)
                col.addWidget(r)
            pieces.append(make)

        first = [st for st in p.steps if st.step.chapter == path_service.FIRST]
        ready = [st for st in p.steps if st.step.chapter == path_service.READY and (st.useful or st.done)]
        header("first", strings.PATH_DONE if p.first_done else "")
        if p.first_done:
            pieces.append(lambda: col.addWidget(_StepRow(None, self._show, body, line=strings.PATH_FIRST_LINE)))
        else:
            for st in first:
                row(st)
        if ready:
            header("ready", strings.PATH_COUNT.format(n=sum(st.done for st in ready), total=len(ready)))
            for st in ready:
                row(st)
        if any(st.step.chapter == path_service.READY and not st.useful and not st.done for st in p.steps):
            pieces.append(lambda: col.addWidget(self._label("pathmore", strings.PATH_MORE, body)))
        pieces.append(lambda: col.addStretch(1))
        self._start("path", body, pieces)

    def _chapter(self, chapter, right, parent):
        w = QWidget(parent)
        row = QHBoxLayout(w)
        row.setContentsMargins(0, round(4 * self._f), 0, 0)
        row.addWidget(self._label("guidegroup", strings.PATH_CHAPTERS[chapter], w))
        row.addStretch(1)
        if right:
            row.addWidget(self._label("pathright" if right != strings.PATH_DONE else "pathdone", right, w))
        return w

    # --- the pieces: each body built one piece per event-loop turn ---------------------------------------------- #
    def _start(self, kind, body, pieces):
        """Body `kind` ("news" / "path") replaced by `body`, its `pieces` made one a turn (`_step`); a newer start of
        the same kind cancels the pieces still to come."""
        job = self._jobs[kind]
        job[0] += 1
        job[1] = collections.deque(pieces)
        old, self._bodies[kind] = self._bodies[kind], body
        body.setParent(self)
        body.hide()
        if self.tab == kind or self.body is None:
            self._mount(kind)
        if old is not None and old is not self.body:
            old.deleteLater()
        self._next_piece(kind, job[0])

    def _mount(self, kind):
        """Body `kind` into the scroll area (the other kept, hidden, for its tab)."""
        body = self._bodies[kind]
        if body is None or self.scroll.widget() is body:
            self.body = body if body is not None else self.body
            return
        taken = self.scroll.takeWidget()
        if taken is not None:
            taken.setParent(self)
            taken.hide()
            if taken not in self._bodies.values():
                taken.deleteLater()
        self.scroll.setWidget(body)
        body.show()
        self.body = body

    def building(self):
        """Whether a body's pieces are still on their way."""
        return any(job[1] for job in self._jobs.values())

    def _next_piece(self, kind, token):
        QTimer.singleShot(0, lambda: self._step(kind, token))

    def _step(self, kind, token):
        """One piece of body `kind`, timed; the next in the next turn."""
        job = self._jobs[kind] if not sip.isdeleted(self) else None
        if job is None or token != job[0] or not job[1]:
            return
        t0 = time.perf_counter()
        job[1].popleft()()
        done = not job[1]
        if done:
            if kind == "news":
                self.builds += 1
            else:
                self.path_builds += 1
            if self.isVisible():
                self.place()
        self.slices.append((time.perf_counter() - t0) * 1000)
        del self.slices[:-SLICES_KEPT]
        if not done:
            self._next_piece(kind, token)

    def show_tab(self, name):
        """*What's new* or *Your path* in view (a path's tab only with a path)."""
        if name == "path" and self.path is None:
            name = "news"
        self.tab = name
        button = self.tab_buttons[name]
        if not button.isChecked():
            button.setChecked(True)
        self._mount(name)
        if self.isVisible():
            self.place()
            if name == "path":
                self.path_shown.emit()

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
        top_row = self.tabs if self.path is not None else self.heading
        head = top_row.sizeHint().height() + lay.spacing() + m.top() + m.bottom()
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

    def open(self, tab=None):
        """Open on `tab`, else the one with something new (unseen news first), else the path (it is the living
        part), else *What's new*."""
        if tab is None:
            news_new = self.look is not None and self.look.glow
            tab = "news" if (news_new or self.path is None) else "path"
        self.show_tab(tab)
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
        if self._waiting_path is not None:
            self.set_path(self._waiting_path[0])

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        if event.type() == QEvent.Type.KeyPress and obj in self.tab_buttons.values() and \
                event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            other = "path" if self.tab == "news" else "news"
            self.show_tab(other)
            self.tab_buttons[self.tab].setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return False

    def sizeHint(self):
        return QSize(round(theme.size("tray", style.current()[1])), super().sizeHint().height())

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["tray"])
        p.end()
