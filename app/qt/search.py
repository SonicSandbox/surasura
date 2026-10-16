"""Search your library (W3.2 Q3; the RUNBOOK §1 *Search*, A2 #79–86, §5a N7; the reference's row 3, the search cut):
the header's cut and its results overlay. What it finds is `app/services/search.py`'s (S4), asked on that service's own
worker — never the window's thread.

- **The cut** (`SearchCut`): *Search your library*, unlit at rest (no floor, a hairline along its lower wall); focused
  it sinks — its floor (`cut`) comes up on a spring (`press` ω 36 going down, `release` ω 26 coming back; Reduced
  motion jumps) — and its lower wall lights as the vein (the iris). `/` (but on Settings, whose own search takes it)
  and Ctrl+K focus it. A keystroke asks again 120 ms after the last one (`DEBOUNCE_MS`); the answer of an older query
  is dropped. **Esc clears, then closes**: with text, the text goes (and the results with it); empty, the cut lets the
  focus go. ↑ ↓ pick a result, Enter shows it.
- **The results** (`Results`, a `motion.Overlay`): slate navy, the iris along its top edge, under the cut; grouped
  Current · Goal · New arrivals · Finished, at most six each (*and N more* under a group cut short), the matched text
  lit, each hit's where-line under its title; ▶ on a Current hit (plays as its row's ▶ does) and ⤒ *Top* on every hit
  but Current's first. They **animate in once, then hold while typing** (a new answer refills them in place); a view
  the reader publishes while they show asks again (the where-lines follow a move). Esc, Back and a press outside (not
  on the cut) close them.
- **A click on a hit shows it in place** (`reveal`): its tab, its list scrolled to it and the row washed once (1.6 s;
  Reduced motion: steady for 1 s); a New arrival opens the tray at it (`shell.show_arrival`, Q1's) — until the tray
  is there, Current; a Goal title opens Goal's sheet at it (`shell.show_goal`, Q2's) — until then Current, its Goal
  dock washed.
- **⤒ Top** goes through the window's writer, with its toast and Undo (`drag.DragController`): a Current row is made
  Up next (the ⋯ menu's own move); a Goal title's next part — the piece holding its next unwatched file — moves to the
  top of Current, the rest stays (A2 #83); an arrival is placed at the top (`place(…, "top")`, A2 #82); a Finished
  hit is put back (`put_back`: the top of Current and its cards back in your order, IK-1). A store that can't be
  written refuses at the press (E4).
"""
from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy,
                             QToolButton, QVBoxLayout, QWidget)

from app import theme
from app.qt import motion, rows, shadow, strings, style

DEBOUNCE_MS = 120                       # A2 #85: the query asked this long after the last keystroke
GROUP_ORDER = ("current", "goal", "arrivals", "finished")


def _f():
    return theme.text_factor(style.current()[1])


def _iris(x0, x1):
    g = QLinearGradient(QPointF(x0, 0), QPointF(x1, 0))
    for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
        g.setColorAt(pos, style.qcolor(colour))
    return g


def _alive(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


# --- the wash: a row (or the Goal dock) shown in place ------------------------------------------------------------ #
class Wash(QWidget):
    """A breath of the accent over `rect_of()` (a row's place, asked each frame: it follows a scroll), fading once over
    `row-flash` (1.6 s); Reduced motion, steady for 1 s. Never takes a click."""

    def __init__(self, parent, rect_of):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.rect_of = rect_of
        self.level = 1.0
        self._anim = None
        self._follow()
        self.show()
        self.raise_()
        if motion.clock().mode.reduced:
            QTimer.singleShot(theme.SETTINGS_MOTION["row-wash-steady"], self.end)
        else:
            self._anim = motion.clock().animate(theme.MOTION["row-flash"], self._frame, self.end, kind="fade",
                                                points="linear", owner=self, on_end=self.end)

    def _follow(self):
        r = self.rect_of()
        if r is None:
            self.end()
            return
        if r != self.geometry():
            self.setGeometry(r)

    def _frame(self, v):
        self.level = 1.0 - v
        self._follow()
        self.update()

    def end(self):
        if _alive(self):
            self.hide()
            self.deleteLater()

    def paintEvent(self, _event):
        colour = style.qcolor(style.colours()["settings-row-wash"])
        colour.setAlphaF(min(1.0, colour.alphaF() * 3.0) * self.level)     # (the settings wash × 3: a list row is busy)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawRoundedRect(QRectF(self.rect()), theme.RADII["r-sm"], theme.RADII["r-sm"])
        p.end()


# --- one hit -------------------------------------------------------------------------------------------------------- #
class HitRow(QWidget):
    """A hit: its title (the matched text lit), its where-line, ▶ (Current) and ⤒ (but on Current's first row). A
    click anywhere else shows it in place."""
    clicked = pyqtSignal(object)
    play = pyqtSignal(object)
    top = pyqtSignal(object)

    def __init__(self, hit, parent=None):
        super().__init__(parent)
        self.hit = hit
        self.current = False                              # picked with ↑ ↓
        self.setObjectName("searchhit")
        self.setAccessibleName(hit.accessible)
        self.setToolTip(strings.SEARCH_SHOW_TIP[hit.group])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        f = _f()
        self.setFixedHeight(round(44 * f))
        line = QHBoxLayout(self)
        line.setContentsMargins(round(12 * f), 0, round(8 * f), 0)
        line.setSpacing(round(4 * f))
        line.addStretch(1)
        self.play_button = self.top_button = None
        if hit.can_play:
            self.play_button = self._button(strings.SEARCH_PLAY, strings.SEARCH_PLAY_NAME, hit.play_tip or strings.SEARCH_PLAY_TIP,
                                            self.play)
            line.addWidget(self.play_button)
        if hit.can_top:
            self.top_button = self._button(strings.SEARCH_TOP, strings.SEARCH_TOP_NAME, strings.SEARCH_TOP_TIP[hit.group], self.top)
            line.addWidget(self.top_button)

    def _button(self, glyph, name, tip, signal):
        b = QToolButton(self)
        b.setObjectName("searchact")
        b.setText(glyph)
        b.setAccessibleName(name)
        b.setToolTip(tip if tip.startswith(name) else f"{name}: {tip}")
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # the cursor stays in the box while you type (A2 #81)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c=False: signal.emit(self.hit))
        return b

    def set_current(self, on):
        if on != self.current:
            self.current = on
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.hit)
        super().mouseReleaseEvent(event)

    def event(self, event):
        if event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
            self.update()
        return super().event(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        cs = style.colours()
        if self.current or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(style.qcolor(cs["overlay-hover"]))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 1, -4, -1), theme.RADII["r-sm"], theme.RADII["r-sm"])
        f = _f()
        x = round(12 * f)
        right = min((b.x() for b in (self.play_button, self.top_button) if b is not None), default=self.width())
        width = max(0, right - x - round(8 * f))
        mid = self.height() / 2
        title_font, sub_font = rows.TEXT.font("row-title"), rows.TEXT.font("row-sub")
        tm, sm = rows.TEXT.metrics("row-title"), rows.TEXT.metrics("row-sub")
        base = mid - 2 * f
        title = tm.elidedText(self.hit.title, Qt.TextElideMode.ElideRight, int(width))
        p.setFont(title_font)
        at = x
        for text, lit in split_lit(title, self.hit.spans):
            p.setPen(style.qcolor(cs["accent" if lit else "ink"]))
            p.drawText(QPointF(at, base), text)
            if lit:
                w = tm.horizontalAdvance(text)
                p.fillRect(QRectF(at, base + 2, w, 1), style.qcolor(cs["accent"]))
            at += tm.horizontalAdvance(text)
        p.setFont(sub_font)
        p.setPen(style.qcolor(cs["overlay-ink-dim"]))
        p.drawText(QPointF(x, base + sm.ascent() + 3 * f),
                   sm.elidedText(self.hit.where, Qt.TextElideMode.ElideRight, int(width)))
        p.end()


def split_lit(shown, spans):
    """`shown` (a title, maybe cut with …) in pieces: [(text, lit)], the spans lit where they fall in it."""
    out, at = [], 0
    for a, b in sorted(spans or ()):
        a, b = max(a, at), min(b, len(shown))
        if a >= b:
            continue
        if a > at:
            out.append((shown[at:a], False))
        out.append((shown[a:b], True))
        at = b
    if at < len(shown):
        out.append((shown[at:], False))
    return out


# --- the results ---------------------------------------------------------------------------------------------------- #
class _Away(QObject):
    """A press outside the results — and outside the cut — closes them; the press goes on to what it was on."""

    def __init__(self, results):
        super().__init__(results)
        self.results = results

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.results.isVisible():
            at = event.globalPosition().toPoint()
            mine = any(w.rect().translated(w.mapToGlobal(w.rect().topLeft())).contains(at)
                       for w in (self.results, self.results.cut))
            if not mine:
                self.results.cut.wanted = False          # a late answer doesn't bring them back
                self.results.hide()
        return False


class Results(motion.Overlay):
    """The results overlay (see the module's doc). `show_groups` refills it in place."""
    how = "pop"
    shadow_name = "search-results"
    focus = False

    def __init__(self, parent, cut):
        super().__init__(parent)
        self.cut = cut
        self.setObjectName("searchresults")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        f = _f()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, round(8 * f), 0, round(8 * f))
        box.setSpacing(0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("searchscroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body = QWidget()
        self.body.setObjectName("searchbody")
        self.lines = QVBoxLayout(self.body)
        self.lines.setContentsMargins(round(4 * f), 0, round(4 * f), 0)
        self.lines.setSpacing(0)
        self.scroll.setWidget(self.body)
        box.addWidget(self.scroll)
        self.hits = []                                   # the HitRows shown, in order
        self.query = None
        self.groups = ()
        self.fills = 0                                   # times refilled (tests: a keystroke refills, never re-opens)
        self.opens = 0
        self.picked = -1
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        self.setAccessibleName(strings.SEARCH_RESULTS_NAME.format(query=""))
        parent.installEventFilter(self)
        self.hide()

    def show_groups(self, query, groups):
        """Fill it with `groups` (S4's) for `query`; opened (with its motion) only when it isn't showing."""
        self.query, self.groups = query, tuple(groups or ())
        self.fills += 1
        self.setAccessibleName(strings.SEARCH_RESULTS_NAME.format(query=query))
        while self.lines.count():
            item = self.lines.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.hits, self.picked = [], -1
        if not self.groups:
            self._label("searchnone", strings.SEARCH_NONE.format(query=query.strip()))
        for g in self.groups:
            self._label("searchgroup", g.label.upper())
            for hit in g.hits:
                row = HitRow(hit, self.body)
                row.clicked.connect(self.cut.reveal)
                row.play.connect(self.cut.play)
                row.top.connect(self.cut.top)
                self.lines.addWidget(row)
                self.hits.append(row)
            if g.total > len(g.hits):
                self._label("searchmore", strings.SEARCH_MORE.format(n=g.total - len(g.hits)))
        self.place()
        if not self.isVisible() and motion.opening_of(self) is None:
            self.opens += 1
            self.open()
        else:
            self.raise_()

    def _label(self, name, text):
        f = _f()
        label = QLabel(text, self.body)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setContentsMargins(round(12 * f), round(8 * f) if name == "searchgroup" else round(4 * f),
                                 round(12 * f), round(4 * f))
        self.lines.addWidget(label)
        return label

    def pick(self, step):
        """↑ ↓: the hit picked moves by `step` (kept in view)."""
        if not self.hits:
            return
        if 0 <= self.picked < len(self.hits):
            self.hits[self.picked].set_current(False)
        self.picked = (self.picked + step) % len(self.hits) if self.picked >= 0 else (0 if step > 0 else len(self.hits) - 1)
        row = self.hits[self.picked]
        row.set_current(True)
        self.scroll.ensureWidgetVisible(row, 0, 0)

    def picked_hit(self):
        return self.hits[self.picked].hit if 0 <= self.picked < len(self.hits) else None

    def place(self):
        """Under the cut, its left edge on the cut's, kept inside the window; no taller than 70 % of it."""
        p = self.parentWidget()
        cut = self.cut
        width = min(round(theme.size("search-results", style.current()[1])), p.width() - 16)
        self.body.setFixedWidth(width - 2)
        self.lines.activate()
        margins = self.layout().contentsMargins()
        height = min(self.body.sizeHint().height() + margins.top() + margins.bottom() + 2, round(p.height() * 0.7))
        at = cut.mapTo(p, cut.rect().bottomLeft())
        x = max(8, min(at.x(), p.width() - width - 8))
        self.setGeometry(x, at.y() + 6, width, height)

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)

    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)

    def closeEvent(self, event):
        """Esc and Back (the shell's router) close it: the search is cleared with it (*Esc clears, then closes*)."""
        super().closeEvent(event)
        self.cut.closed()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        r = self.rect()
        style.paint_overlay(p, r, theme.RADII["search-results"])
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)        # the iris along its top edge (brief §2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), theme.RADII["search-results"], theme.RADII["search-results"])
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, r.width(), 1.5), _iris(0, r.width()))
        p.end()


# --- the cut ------------------------------------------------------------------------------------------------------ #
class _Answer(QObject):
    said = pyqtSignal(str, object, float)               # (query, groups, ms) from the searcher's worker


class SearchCut(QWidget):
    """The header's search (see the module's doc). `searcher`: S4's `Searcher` shape (`ask(query, callback)`,
    `close()`), made from the window's library reader at the first keystroke when not given."""

    def __init__(self, shell, parent=None, searcher=None):
        super().__init__(parent)
        self.shell = shell
        self.setObjectName("librarycut")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.sink = 0.0                                  # 0 at rest (unlit) … 1 focused (sunk, the vein lit)
        self._spring = None
        self.searcher = searcher
        self.results = None
        self.asked = 0                                   # queries handed to the searcher (tests)
        self.wanted = False                              # the results may show (typing; not after a press away)
        self.washed = None                               # the last wash (a reveal)
        self.washed_at, self.washes = None, 0
        line = QHBoxLayout(self)
        self.icon_room = QWidget(self)                   # the magnifier is painted in this room
        self.icon_room.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        line.addWidget(self.icon_room)
        self.edit = QLineEdit(self)
        self.edit.setObjectName("librarysearch")
        self.edit.setPlaceholderText(strings.SEARCH_PLACEHOLDER)
        self.edit.setAccessibleName(strings.SEARCH_NAME)
        self.edit.setToolTip(strings.SEARCH_TIP)
        self.edit.setClearButtonEnabled(False)
        self.edit.installEventFilter(self)
        line.addWidget(self.edit, 1)
        self.kbd = QLabel(strings.SEARCH_KEY, self)
        self.kbd.setObjectName("searchkbd")
        self.kbd.setToolTip(strings.SEARCH_TIP)
        line.addWidget(self.kbd)
        self.setFocusProxy(self.edit)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DEBOUNCE_MS)
        self.timer.timeout.connect(self._ask)
        self.edit.textChanged.connect(self._typed)
        self._answer = _Answer(self)
        self._answer.said.connect(self._answered, Qt.ConnectionType.QueuedConnection)
        self.slash = QShortcut(QKeySequence("/"), shell)
        self.slash.setContext(Qt.ShortcutContext.WindowShortcut)
        self.slash.activated.connect(self._slash)
        self.ctrl_k = QShortcut(QKeySequence("Ctrl+K"), shell)
        self.ctrl_k.setContext(Qt.ShortcutContext.WindowShortcut)
        self.ctrl_k.activated.connect(self.focus_now)
        shell.installEventFilter(self)
        self.restyle()

    def restyle(self):
        f = _f()
        size = style.current()[1]
        self.layout().setContentsMargins(round(10 * f), 0, round(8 * f), 0)
        self.layout().setSpacing(round(8 * f))
        self.icon_room.setFixedSize(14, 14)
        self.setFixedHeight(round(theme.size("search-h", size)))
        self._fit_width()

    def _fit_width(self):
        size = style.current()[1]
        narrow = self.shell.width() < theme.NARROW_BELOW
        self.setFixedWidth(round(theme.size("search-w-narrow" if narrow else "search-w", size)))

    # --- focus: / and Ctrl+K; the sink ------------------------------------------------------------------------- #
    def _slash(self):
        """`/`: the library's search — but on a page with a search of its own (Settings), that one (its page's `/`)."""
        pages = getattr(self.shell, "pages", None)
        page = pages.currentWidget() if pages is not None else None
        if page is not None:
            own = page if hasattr(page, "focus_search") else next(
                (w for w in page.findChildren(QWidget) if hasattr(w, "focus_search")), None)
            if own is not None:
                own.focus_search()
                return
        self.focus_now()

    def focus_now(self):
        if not self.isVisible():
            return
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.edit.selectAll()

    def _sink_to(self, target):
        omega, zeta = theme.SPRINGS["press" if target else "release"]
        if self._spring is not None and self._spring.alive:
            self._spring.omega, self._spring.zeta = omega, zeta
            self._spring.retarget(target)
            return
        self._spring = motion.clock().spring(self._set_sink, self.sink, target, omega, zeta, owner=self)

    def _set_sink(self, value):
        value = max(0.0, min(1.0, value))
        if value != self.sink:
            self.sink = value
            self.update()

    def eventFilter(self, obj, event):
        et = event.type()
        if obj is self.shell:
            if et == QEvent.Type.Resize:
                self._fit_width()
            return False
        if et == QEvent.Type.FocusIn:
            self._sink_to(1.0)
            self.wanted = True
            if self.edit.text().strip() and (self.results is None or not self.results.isVisible()):
                self.timer.start()                       # back in the box with words in it: the results again
        elif et == QEvent.Type.FocusOut:
            self._sink_to(0.0)
        elif et == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                if self.edit.text():
                    self.edit.clear()                    # Esc clears …
                else:
                    self.shell.centralWidget().setFocus(Qt.FocusReason.OtherFocusReason)     # … then closes
                return True
            showing = self.results is not None and self.results.isVisible()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and showing:
                self.results.pick(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and showing:
                hit = self.results.picked_hit() or (self.results.hits[0].hit if self.results.hits else None)
                if hit is not None:
                    self.reveal(hit)
                return True
        return False

    # --- asking -------------------------------------------------------------------------------------------------- #
    def _typed(self, text):
        if text.strip():
            self.wanted = True
            self.timer.start()
        else:
            self.timer.stop()
            if self.results is not None and self.results.isVisible():
                self.results.hide()

    def _searcher(self):
        if self.searcher is None:
            library = self.shell.services.library
            if library is None:
                return None
            from app.services import search as search_service
            self.searcher = search_service.Searcher(library.opener, library.view)
        return self.searcher

    def _ask(self):
        query = self.edit.text()
        searcher = self._searcher()
        if not query.strip() or searcher is None:
            return
        self.asked += 1
        said = self._answer.said

        def answer(q, groups, ms):
            try:
                said.emit(q, groups, ms)
            except RuntimeError:                         # the window is gone
                pass
        searcher.ask(query, answer)

    def _answered(self, query, groups, _ms):
        if query != self.edit.text() or not self.wanted:
            return                                       # an older query's, or the hand has gone elsewhere
        if self.results is None:
            self.results = Results(self.shell.centralWidget(), self)
            self.shell.register_overlay(self.results)
        self.results.show_groups(query, groups)

    def library_moved(self, _view=None):
        """The reader published a view: the results showing ask again (their where-lines follow a move)."""
        if self.results is not None and self.results.isVisible() and self.edit.text().strip():
            self.timer.start()

    def closed(self):
        """The results were closed by Esc or Back: the search is cleared."""
        self.wanted = False
        if self.edit.text():
            self.edit.blockSignals(True)
            self.edit.clear()
            self.edit.blockSignals(False)
            self.timer.stop()

    def close_searcher(self):
        if self.searcher is not None:
            try:
                self.searcher.close()
            except Exception:
                pass

    # --- what a hit does ----------------------------------------------------------------------------------------- #
    def _row(self, page_name, key):
        page = self.shell.page_widgets.get(page_name)
        view = getattr(page, "view_model", None)
        if view is None:
            return None
        if page_name == "current":
            return next((r for r in view.rows if r.key == key), None)
        return next((r for m in view.finished for r in m.rows if r.key == key), None)

    def reveal(self, hit):
        """A click on a hit: shown in place (see the module's doc); the results close."""
        self.wanted = False
        if self.results is not None:
            self.results.hide()
        if hit.group in ("current", "finished"):
            self.shell.show_tab(hit.group)
            QTimer.singleShot(0, lambda: self._scroll_to(hit.group, hit.key))
            return
        if hit.group == "arrivals":
            show = getattr(self.shell, "show_arrival", None)            # Q1's tray, opened at it
            if show is not None:
                show(hit.key)
                return
            self.shell.show_tab("current")
            return
        show = getattr(self.shell, "show_goal", None)                   # Q2's sheet, opened at it
        if show is not None:
            show(hit.work_id)
            return
        self.shell.show_tab("current")
        dock = getattr(self.shell, "dock", None)
        if dock is not None and dock.isVisible():
            self._wash(dock.parentWidget(), lambda: dock.geometry() if _alive(dock) else None)

    def _wash(self, parent, rect_of):
        self.washed_at = rect_of()                       # where the last wash went (tests: its fade may be over)
        self.washes += 1
        self.washed = Wash(parent, rect_of)

    def _scroll_to(self, page_name, key):
        if not _alive(self):
            return                                       # the window closed meanwhile
        page = self.shell.page_widgets.get(page_name)
        lst = getattr(page, "list", None)
        if lst is None or not _alive(lst):
            return
        model = lst.model()
        at = next((i for i, e in enumerate(model.entries) if getattr(e[1], "key", None) == key), None)
        if at is None:
            return
        index = model.index(at, 0)
        lst.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        held = [at]

        def rect():
            if not _alive(lst):
                return None
            entries = lst.model().entries
            if not (0 <= held[0] < len(entries) and getattr(entries[held[0]][1], "key", None) == key):
                found = next((i for i, e in enumerate(entries) if getattr(e[1], "key", None) == key), None)
                if found is None:
                    return None
                held[0] = found
            return lst.visualRect(lst.model().index(held[0], 0))
        self._wash(lst.viewport(), rect)

    def play(self, hit):
        """▶ on a Current hit: its row's next episode, as the row's ▶ opens it."""
        row = self._row("current", hit.key)
        if row is None or not row.can_play or not row.episodes:
            return
        self.shell.page_widgets["current"]._play(row.episodes[row.next_index])

    def top(self, hit):
        """⤒: up next / the top of Current, through the writer, with its toast and Undo (see the module's doc)."""
        moves = getattr(self.shell, "moves", None)
        if moves is None or moves.refused() is not None:
            return
        from app.qt import drag
        writer = moves.writer
        text = strings.DRAG_UP_NEXT.format(title=hit.title)
        if hit.group == "current":
            row = self._row("current", hit.key)
            if row is not None:
                moves.menu_pick(row, "up-next")
            return
        if hit.group == "arrivals":
            ids = list(hit.item_ids)
            moves._give(drag.Ticket(text, (), ids), lambda t: writer.place(ids, "top", label=t))
        elif hit.group == "finished":
            ids = list(hit.item_ids)
            moves._give(drag.Ticket(text, (), ids), lambda t: writer.put_back(ids, label=t))
        else:
            ids = list(hit.top_ids or hit.item_ids)
            moves._give(drag.Ticket(text, (), ids), lambda t: writer.move(ids, "now", label=t))
        self.timer.start()                               # the where-lines asked again (the view follows)

    # --- painting ---------------------------------------------------------------------------------------------- #
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cs = style.colours()
        r = QRectF(self.rect())
        radius = 10 * _f()
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)
        if self.sink > 0:                                # the floor comes up as it sinks (unlit at rest)
            floor = style.qcolor(cs["cut"])
            floor.setAlphaF(self.sink)
            p.fillRect(r, floor)
            top = style.qcolor(cs["cut-wall-top"])
            top.setAlphaF(self.sink)
            p.fillRect(QRectF(0, 0, r.width(), 1), top)
        p.fillRect(QRectF(0, r.height() - 1, r.width(), 1), style.qcolor(cs["line"]))
        if self.sink > 0:                                # the vein lights along its lower wall
            p.setOpacity(self.sink)
            p.fillRect(QRectF(0, r.height() - 1.5, r.width(), 1.5), _iris(0, r.width()))
            p.setOpacity(1.0)
        icon = QRectF(self.icon_room.geometry())
        pen = QPen(style.qcolor(cs["ink" if self.sink > 0.5 else "ink-faint"]), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(icon.left() + 1, icon.top() + 1, icon.width() * 0.62, icon.height() * 0.62))
        p.drawLine(QPointF(icon.left() + icon.width() * 0.6, icon.top() + icon.height() * 0.6),
                   QPointF(icon.right() - 1, icon.bottom() - 1))
        p.end()
