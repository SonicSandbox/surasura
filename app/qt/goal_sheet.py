"""Goal's sheet (W3.2 Q2; the RUNBOOK §1 *Goal's sheet*; A2 35–36 and 117, G1, G2; G1.6's n9, n11; §5a IK-11).

A click on Goal's bar (`frame.GoalDock.sheet_requested`, never during a drag) opens the sheet over the bottom 62 % of
Current's list column: slate navy with its iris top edge and its shadow (`sheet`), rising into place on a spring
(`theme.SPRINGS["sheet"]`; Reduced motion and the freeze switch: at once). It opens only on the hand's click; a new view
updates its tiles in place and never animates it again.

- **The tiles** (`Tile`): one per title in Goal's order (`view_rows.Goal.works`, made on the reader's thread): its
  cover (the generated one until Q6), its title, *N episodes / videos / parts*, and a ⋯ always shown. Tab goes through
  the tiles (and ✕), Enter opens a tile's ⋯.
- **⋯** (n11): *Move to the top* · *Move to Soon* — the sheet closes, the title's **first piece** moves (the writer's
  `move`, as Current's ⋯ does), the rest stays in Goal, and the list scrolls to it and washes it (G2) — · *Move to
  Finished* (all of it, with the Finished toast's choice, D14 / IK-11; left out for hato's mix, as on Current) · *Open
  its folder* · *Remove…* (a confirmation naming the count; the writer's `remove`, its toast's Undo).
- **A drag**: a press and 6 px on a tile lifts its first piece (`DragController.begin_by_id`, from Goal: the Goal well
  left out); the sheet closes as the drag starts.
- **The picks (A4):** Ctrl+click a tile picks it, Shift+click the tiles from the last one Ctrl picked, Ctrl+A every
  tile (Ctrl+Space the focused one); a plain click lets them go, and so does closing the sheet. ⋯ or a right-click on a
  picked tile while 2+ are picked offers *Up next* · *Soon* (each title's first part, as its single ⋯) · *Finished* ·
  *Remove…* for all of them, each one store command (`item_menu.fill_picks_menu`, `DragController.send_picks`); a drag
  from a picked tile carries them all.
- **It closes** on ✕, Esc and Back (the shell's `EscapeRouter`), a click outside it (G1: the sheet itself, Goal's bar —
  whose click toggles it — its ⋯ menu and the Remove question are not outside), and when Current is left.

Nothing here reads or writes the store: the tiles come from the reader's view, every command goes through the window's
writer (`drag.DragController._give`: its toast, Undo and E4's refusal).
"""
import os
import time

from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QAction, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QMenu, QScrollArea, QToolButton, QWidget

from app import path_utils, theme
from app.qt import confirm, frame, motion, rows, shadow, strings, style
from app.qt import covers as qcovers                 # --- W3.2 L3: the titles' own pictures (Q6's door)
from app.qt.drag import Ticket, is_mix, soon_slot

# The sheet's sizes (px at text size S; × the text size): the RUNBOOK's 62 % of the column, the mock's tile
SHEET = {"share": 0.62, "pad": 18, "head": 50, "tile-w": 116, "tile-pad": 8, "gap": 10, "more": 26, "wash-alpha": 0.22,
         "seek-s": 10.0}


def _f():
    return theme.text_factor(style.current()[1])


def columns(width, tile_w, gap, pad):
    """How many tiles a row of the sheet holds (at least one)."""
    return max(1, int((width - 2 * pad + gap) // (tile_w + gap)))


def menu_entries(work, writable, reason=None):
    """⋯'s entries for a tile, in order: [(name, label, tip, enabled)] — *top* / *soon* name the first piece when more
    stays in Goal; *finished* is left out for hato's mix; the moves are disabled, with the store's reason, while it
    can't be written (E4); *Open its folder* always works."""
    first = work.pieces[0].line if work.pieces else ""
    rest = len(work.pieces) > 1
    out = []
    for name in ("top", "soon", "finished", "folder", "remove"):
        if name == "finished" and work.source == "hato":
            continue
        key = name + "-all" if name in ("top", "soon") and not rest else name
        label, tip = strings.GOAL_MENU_ITEMS[key]
        tip = tip.format(first=first, n=work.n_files)
        ok = writable or name == "folder"
        out.append((name, label, tip if ok else reason, ok))
    return out


class Tile(QWidget):
    """One title in Goal: its cover, its title and *N episodes*, a ⋯ always shown. Repainted only when its title's
    tile changed (`set_work`: a new object)."""

    def __init__(self, sheet, work, parent):
        super().__init__(parent)
        self.sheet = sheet
        self.work = None
        self.setObjectName("goaltile")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.more = QToolButton(self)
        self.more.setObjectName("goaltilemore")
        self.more.setText(strings.GOAL_TILE_MORE)
        self.more.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # Enter on the tile opens it
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.clicked.connect(lambda _c=False: self.sheet.menu(self))
        self._press = None
        self.paints = self.sets = 0                      # paints; times its tile changed (S19)
        self.set_work(work)

    def set_work(self, work):
        """-> True when the tile changed (and repainted)."""
        if work is self.work:
            return False
        self.work = work
        self.sets += 1
        self.setToolTip(work.tip)
        self.setAccessibleName(work.accessible)
        name = strings.GOAL_TILE_MORE_NAME.format(title=work.title)
        self.more.setAccessibleName(name)
        self.more.setToolTip(strings.GOAL_TILE_MORE_TIP.format(title=work.title))
        self.update()
        return True

    def size_for(self):
        f = _f()
        w = round(SHEET["tile-w"] * f)
        pad = round(SHEET["tile-pad"] * f)
        cw = w - 2 * pad
        ch = round(cw * 1.42)
        h = pad + ch + round(8 * f) + rows.TEXT.metrics("row-title").height() + rows.TEXT.metrics("row-sub").height()
        h += pad
        return w, h, pad, cw, ch

    def apply_size(self):
        w, h, pad, cw, ch = self.size_for()
        self.setFixedSize(w, h)
        m = round(SHEET["more"] * _f())
        self.more.setGeometry(pad + cw - m + 4, pad + ch + round(6 * _f()), m, m)    # beside its title, off the cover

    # --- the hand and the keys ------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        self._press = event.position() if event.button() == Qt.MouseButton.LeftButton else None
        self._mods = event.modifiers()               # A4: Ctrl / Shift pick at the release (never a drag)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position() - self._press).manhattanLength() >= theme.MOTION["drag-start-px"]:
            self._press = None
            self.sheet.drag(self, event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        clicked, self._press = self._press is not None and event.button() == Qt.MouseButton.LeftButton, None
        event.accept()
        if not clicked:
            return
        mods = getattr(self, "_mods", Qt.KeyboardModifier.NoModifier)       # --- A4: the picks
        ctrl, shift = mods & Qt.KeyboardModifier.ControlModifier, mods & Qt.KeyboardModifier.ShiftModifier
        if shift:
            self.sheet.pick_range(self, add=bool(ctrl))
        elif ctrl:
            self.sheet.pick_tile(self)
        else:
            self.sheet.clear_picks()                 # a plain click lets them go

    def contextMenuEvent(self, event):
        """A4: a right-click opens the tile's ⋯ at the hand (the picks' on a picked tile)."""
        self.sheet.menu(self, event.globalPos())
        event.accept()

    def keyPressEvent(self, event):
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if event.key() == Qt.Key.Key_A and ctrl:      # --- A4: Ctrl+A picks every tile, Ctrl+Space this one
            self.sheet.pick_all()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and ctrl:
            self.sheet.pick_tile(self)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.sheet.menu(self)
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, _event):
        self.paints += 1
        w, h, pad, cw, ch = self.size_for()
        dpr = self.devicePixelRatioF() or 1.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = theme.RADII["cover-tile"]
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rows.c("overlay-hover"))
            p.drawRoundedRect(r, radius + 2, radius + 2)
        cover = QRectF(pad, pad, cw, ch)
        clip = QPainterPath()
        clip.addRoundedRect(cover, radius, radius)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(cover.topLeft(), qcovers.pixmap_for(getattr(self.work, "cover", None),      # --- W3.2 L3
                                                         self.work.cover_title, cw, ch, dpr, "tile"))
        p.restore()
        y = pad + ch + round(8 * _f())
        th = rows.TEXT.metrics("row-title").height()
        room = self.more.x() - pad - 2                   # the ⋯ stands right of the title and its line
        rows.TEXT.draw(p, pad, y + th / 2, self.work.title, "row-title", room, rows.c("ink"), dpr=dpr)
        sh = rows.TEXT.metrics("row-sub").height()
        rows.TEXT.draw(p, pad, y + th + sh / 2, self.work.line, "row-sub", room, rows.c("overlay-ink-dim"), dpr=dpr)
        if self.work.key in self.sheet.picks:          # --- A4: picked, as a picked row is (`row-picked`, the accent)
            p.setPen(QPen(rows.c("accent"), 1.5))
            p.setBrush(rows.c("row-picked"))
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), radius + 2, radius + 2)
        if self.hasFocus():
            p.setPen(QPen(rows.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, radius + 2, radius + 2)
        p.end()


class Wash(QWidget):
    """The wash over a row the sheet just brought up (G2's scroll): the accent, fading over `row-flash` (Reduced motion:
    steady for `row-wash-steady`, 1 s, as search's and Settings' washes); it goes as the list scrolls. Never takes the
    mouse."""

    def __init__(self, lst):
        super().__init__(lst.viewport())
        self.setObjectName("goalwash")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.alpha = 0.0
        self._anim = None
        self._steady = QTimer(self)                      # Reduced motion: the steady wash's one second
        self._steady.setSingleShot(True)
        self._steady.setInterval(theme.SETTINGS_MOTION["row-wash-steady"])
        self._steady.timeout.connect(self.hide)
        lst.verticalScrollBar().valueChanged.connect(lambda _v: self.hide())
        self.hide()

    def flash(self, rect):
        if self._anim is not None and self._anim.alive:
            self._anim.stop()
        self._steady.stop()
        self.setGeometry(rect)
        self.alpha = SHEET["wash-alpha"]
        self.show()
        self.raise_()
        if motion.clock().mode.reduced:
            self.update()
            self._steady.start()
            return

        def frame_(k):
            self.alpha = SHEET["wash-alpha"] * (1 - k)
            self.update()
        self._anim = motion.clock().animate(theme.MOTION["row-flash"], frame_, on_done=self.hide, kind="fade",
                                            owner=self, on_end=self.hide)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rows.faded("accent", self.alpha))
        p.drawRoundedRect(QRectF(self.rect()), theme.RADII["r-sm"], theme.RADII["r-sm"])
        p.end()


class _Away(QObject):
    """G1: a press outside the sheet closes it, and goes on to what it was on. Not outside: the sheet, Goal's bar (its
    own click toggles the sheet), a menu or another window (the ⋯ menu), the Remove question and its dimmed room."""

    def __init__(self, sheet):
        super().__init__(sheet)
        self.sheet = sheet

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.MouseButtonPress or not isinstance(obj, QWidget) or not self.sheet.isVisible():
            return False
        if obj.window() is not self.sheet.window():
            return False                                # the ⋯ menu (a popup), another window
        at = event.globalPosition().toPoint()
        s, dock = self.sheet, self.sheet.dock
        if s.rect().contains(s.mapFromGlobal(at)):
            return False
        if dock is not None and dock.isVisible() and dock.rect().contains(dock.mapFromGlobal(at)):
            return False
        w = obj
        while w is not None:
            if isinstance(w, (confirm.Confirm, confirm.Scrim)):
                return False
            w = w.parentWidget()
        s.close()
        return False


class GoalSheet(motion.Overlay):
    """The sheet (see the module's doc). `win` the shell (its `moves`, `toasts`, `say`, `language`), `page` Current's
    page (its list: the column), `dock` Goal's dock."""
    shadow_name = "sheet"
    focus = True

    def __init__(self, win, page, dock):
        super().__init__(page)
        self.win, self.page, self.dock = win, page, dock
        self.setObjectName("goalsheet")
        self.setAccessibleName(strings.GOAL_SHEET_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.goal = None
        self.tiles = {}                                  # key -> Tile
        self.order = []                                  # the tiles in Goal's order
        self._dirty = True                               # the tiles wait for the next open (built only when shown)
        self._spring = None
        self.offset = 0.0                                # how far below its place it is (rising)
        self.opens = self.paints = self.builds = 0
        self.seeking = None                              # (item id, until): a moved piece the list scrolls to
        self.washed = None                               # the last row washed (tests)
        self.last_menu = None
        self.picks = set()                               # A4: the picked tiles' keys
        self._pick_anchor = None                         # ... the one Ctrl picked last (a Shift range starts there)
        self.question = None                             # ... the picks' *Remove…* question while it is open
        rows.picks_join(self)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("goalsheetclose")
        self.close_button.setText(strings.GOAL_SHEET_CLOSE)
        self.close_button.setAccessibleName(strings.GOAL_SHEET_CLOSE_NAME)
        self.close_button.setToolTip(strings.GOAL_SHEET_CLOSE_TIP)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(lambda _c=False: self.close())
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("goalsheetscroll")
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.viewport().setAutoFillBackground(False)
        self.body = QWidget()
        self.body.setObjectName("goalsheetbody")
        self.body.setAutoFillBackground(False)
        self.scroll.setWidget(self.body)
        self.scroll.setWidgetResizable(False)
        self.scroll.viewport().installEventFilter(self)
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        self.wash = Wash(page.list)
        qcovers.notifier().ready.connect(self._cover_ready)        # --- W3.2 L3
        page.installEventFilter(self)
        if dock is not None:
            dock.installEventFilter(self)
        self.hide()

    # --- W3.2 L3: a picture landing repaints only the tiles of that title
    def _cover_ready(self, work_id):
        for tile in self.tiles.values():
            if tile.work is not None and tile.work.work_id == work_id:
                tile.update()
    # --- end W3.2 L3

    # --- the goal ----------------------------------------------------------------------------------------------- #
    def set_goal(self, goal):
        """The reader's `view.goal`. -> True when it changed: the heading and the tiles that changed repaint (only
        while open; else they are made at the next open). The same object: nothing at all (N9)."""
        if goal is self.goal:
            return False
        self.goal = goal
        if self.isVisible():
            self._sync()
            self.update(QRect(0, 0, self.width(), round(SHEET["head"] * _f())))
        else:
            self._dirty = True
        return True

    def _sync(self):
        """The tiles to the goal's titles, in its order: a title's tile kept (repainted only if its tile changed), new
        ones made, gone ones dropped; laid out again only when the order changed."""
        works = self.goal.works if self.goal is not None else ()
        keys = [w.key for w in works]
        for key in [k for k in self.tiles if k not in set(keys)]:
            tile = self.tiles.pop(key)
            tile.hide()
            tile.deleteLater()
        self.picks &= self.tiles.keys()                  # A4: a title gone from Goal lets its pick go
        for w in works:
            tile = self.tiles.get(w.key)
            if tile is None:
                tile = self.tiles[w.key] = Tile(self, w, self.body)
                tile.apply_size()
                tile.show()
            else:
                tile.set_work(w)
        order = [self.tiles[k] for k in keys]
        if order != self.order:
            self.order = order
            for a, b in zip(order, order[1:]):
                QWidget.setTabOrder(a, b)
            if order:
                QWidget.setTabOrder(order[-1], self.close_button)
            self._lay_out()
        self._dirty = False
        self.builds += 1

    def _lay_out(self):
        f = _f()
        pad, gap = round(SHEET["pad"] * f), round(SHEET["gap"] * f)
        width = self.scroll.viewport().width()
        if not self.order:
            self.body.resize(width, 0)
            return
        tw, th = self.order[0].width(), self.order[0].height()
        n = columns(width, tw, gap, pad)
        for i, tile in enumerate(self.order):
            r, c = divmod(i, n)
            tile.move(pad + c * (tw + gap), r * (th + gap))
        rows_n = (len(self.order) + n - 1) // n
        self.body.resize(width, rows_n * (th + gap) - gap + pad)

    # --- its place, opening and closing ---------------------------------------------------------------------- #
    def rest_rect(self):
        """Over the bottom 62 % of the list column: from the dock's top (the page's foot when it's hidden) up."""
        lst = self.page.list
        g = lst.geometry()
        dock = self.dock
        bottom = dock.geometry().top() if dock is not None and dock.isVisible() else self.page.height()
        h = max(1, round(SHEET["share"] * (bottom - g.top())))
        return QRect(g.left(), bottom - h, g.width(), h)

    def place(self):
        rest = self.rest_rect()
        self.setGeometry(rest.translated(0, round(self.offset)))
        f = _f()
        head = round(SHEET["head"] * f)
        m = round(theme.SIZES["icon-button"] * f)
        pad = round(SHEET["pad"] * f)
        self.close_button.setGeometry(rest.width() - pad - m + 6, (head - m) // 2 + 2, m, m)
        self.scroll.setGeometry(0, head, rest.width(), max(0, rest.height() - head))

    def open(self):
        """Opened by the hand (the bar's click): its tiles brought up to date, then it rises on its spring — once; a
        view while it is open never moves it again."""
        if self.isVisible():
            return None
        self.opens += 1
        self.offset = float(theme.MOTION["buckets-rise"])
        self.place()
        if self._dirty:
            self._sync()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        if self._spring is not None:
            self._spring.stop()
        self._spring = motion.clock().spring(self._rise, self.offset, 0.0, owner=self, **motion.preset("sheet"))
        return self._spring

    def _rise(self, v):
        self.offset = v
        rest = self.rest_rect()
        self.move(rest.left(), rest.top() + round(v))

    def rising(self):
        return self._spring is not None and self._spring.alive

    def toggle(self):
        if self.isVisible():
            self.close()
        else:
            self.open()

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)

    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)
        self.clear_picks()                               # A4: the picks go with the sheet
        if self._spring is not None:
            self._spring.stop()
            self._spring = None
        self.offset = 0.0

    def eventFilter(self, obj, event):
        et = event.type()
        if obj is self.page and et == QEvent.Type.Hide and self.isVisible():
            self.close()                                 # Current left: the sheet goes with it
        elif obj in (self.page, self.dock) and et in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show,
                                                      QEvent.Type.Hide) and self.isVisible():
            self.place()
        elif obj is self.scroll.viewport() and et == QEvent.Type.Resize:
            self._lay_out()
        return False

    def focusNextPrevChild(self, next_):
        """Tab and Shift+Tab go round the tiles and ✕, never out of the sheet while it is open."""
        ring = list(self.order) + [self.close_button]
        now = QApplication.focusWidget()
        i = ring.index(now) if now in ring else (-1 if next_ else 0)
        target = ring[(i + (1 if next_ else -1)) % len(ring)]
        target.setFocus(Qt.FocusReason.TabFocusReason if next_ else Qt.FocusReason.BacktabFocusReason)
        if isinstance(target, Tile):
            self.scroll.ensureWidgetVisible(target)
        return True

    # --- painting -------------------------------------------------------------------------------------------- #
    def paintEvent(self, _event):
        self.paints += 1
        f = _f()
        dpr = self.devicePixelRatioF() or 1.0
        p = QPainter(self)
        r = QRectF(self.rect())
        radius = theme.RADII["sheet"]
        style.paint_overlay(p, r, radius)
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.save()
        p.setClipPath(path)
        edge = max(1, round(dpr)) / dpr
        p.fillRect(QRectF(0, 0, r.width(), edge), frame._iris(0, r.width()))     # the iris top edge
        p.restore()
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        head = round(SHEET["head"] * f)
        pad = round(SHEET["pad"] * f)
        mid = head / 2 + 2
        w, _cut = rows.TEXT.draw(p, pad, mid, strings.GOAL_NAME, "sheet-heading", 200, rows.c("ink"), dpr=dpr)
        if self.goal is not None:
            room = self.close_button.x() - (pad + w + 12) - 8
            rows.TEXT.draw(p, pad + w + 12, mid, self.goal.line, "row-sub", room, rows.c("overlay-ink-dim"), dpr=dpr)
        p.end()

    # --- A4: the picks ------------------------------------------------------------------------------------------ #
    @staticmethod
    def pickable(work):
        """A title the picks can take: one with a part in Goal, never hato's mix (as on Current)."""
        return bool(work.pieces) and not is_mix(work)

    def _repaint(self, keys):
        for key in keys:
            tile = self.tiles.get(key)
            if tile is not None:
                tile.update()

    def pick_tile(self, tile):
        """Ctrl+click, Ctrl+Space: the tile in the picks, or out of them again (that tile alone repainted)."""
        if not self.pickable(tile.work):
            return False
        self.picks ^= {tile.work.key}
        self._pick_anchor = tile.work.key
        self._repaint((tile.work.key,))
        if self.picks:
            rows.picks_here(self)
        return True

    def pick_range(self, tile, add=False):
        """Shift+click: the tiles from the anchor to this one (Ctrl+Shift adds them); only those that changed repainted."""
        if not self.pickable(tile.work):
            return False
        order = [t.work.key for t in self.order]
        here = order.index(tile.work.key)
        there = order.index(self._pick_anchor) if self._pick_anchor in self.tiles else here
        if self._pick_anchor not in self.tiles:
            self._pick_anchor = tile.work.key
        span = {k for k in order[min(here, there):max(here, there) + 1] if self.pickable(self.tiles[k].work)}
        before = self.picks
        self.picks = before | span if add else span
        self._repaint(before ^ self.picks)
        if self.picks:
            rows.picks_here(self)
        return True

    def pick_all(self):
        """Ctrl+A: every tile the picks can take; only those that changed repainted."""
        before = self.picks
        self.picks = {k for k, t in self.tiles.items() if self.pickable(t.work)}
        self._repaint(before ^ self.picks)
        if self.picks:
            rows.picks_here(self)
        return bool(self.picks)

    def clear_picks(self):
        if self.picks:
            before, self.picks = self.picks, set()
            self._pick_anchor = None
            self._repaint(before)

    def picked(self):
        """The picked titles in Goal's order."""
        return [t.work for t in self.order if t.work.key in self.picks] if self.picks else []

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.pick_all()                              # A4: Ctrl+A with the sheet itself focused
            event.accept()
            return
        super().keyPressEvent(event)

    def picks_menu(self, tile, at=None):
        """⋯ / right-click on a picked tile while 2+ are picked: *Up next* · *Soon* · *Finished* · *Remove…* for all
        of them (no *Goal*: they are there; *Finished* left out for hato's mix, which is never picked). -> the menu."""
        from app.qt import item_menu
        _moves, writer = self._writer()
        n = len(self.picked())
        m = QMenu(self)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        m.aboutToHide.connect(m.deleteLater)
        item_menu.fill_picks_menu(m, n, "goal", writer, self.send_picks, goal=True)
        self.last_menu = m
        m.popup(at if at is not None else tile.more.mapToGlobal(tile.more.rect().bottomLeft()))
        return m

    def send_picks(self, name):
        """A picks' ⋯ entry: ONE store command (`DragController.send_picks`) — *Up next* / *Soon* each title's first
        part, *Finished* / *Remove…* all of each (as the single ⋯); the picks let go. The sheet stays open."""
        from app.qt import item_menu
        moves, _writer = self._writer()
        works = self.picked()
        if moves is None or not works:
            return None
        every = [i for w in works for i in w.item_ids]
        if name == "remove":
            self.question = item_menu.ask_remove_picks(self.win, moves, len(works), every, then=self.clear_picks)
            return self.question
        ids = [i for w in works for i in w.pieces[0].item_ids] if name in ("top", "soon") else every
        seq = moves.send_picks(name, ids, len(works), (), "goal")
        if seq is not None:
            self.clear_picks()
        return seq

    # --- ⋯ and its actions ------------------------------------------------------------------------------------ #
    def _writer(self):
        moves = getattr(self.win, "moves", None)
        return moves, (moves.writer if moves is not None else None)

    def menu(self, tile, at=None):
        """A tile's ⋯: a plain menu in the theme's style (Esc closes it), its entries' tips shown. A4: at `at` (a
        right-click), else under its ⋯; on a picked tile while 2+ are picked, the picks' own (`picks_menu`)."""
        if tile.work.key in self.picks and len(self.picks) > 1:
            return self.picks_menu(tile, at)
        moves, writer = self._writer()
        work = tile.work
        writable = writer is not None and writer.can_write()
        reason = None
        if not writable:
            raw = (writer.reason() if writer is not None else None) or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        m = QMenu(self)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        m.setAccessibleName(strings.MENU_NAME.format(title=work.title))
        for name, label, tip, ok in menu_entries(work, writable, reason):
            if name == "folder":                                    # --- W3.2 L3: Change cover… after the moves
                qcovers.add_cover_menu(m, work, writable, reason)
            if name == "remove":
                m.addSeparator()
            act = QAction(label, m)
            act.setToolTip(tip or "")
            act.setEnabled(ok)
            act.triggered.connect(lambda _c=False, n=name, w=work, t=tile: self.pick(w, n, t))
            m.addAction(act)
        self.last_menu = m
        m.popup(at if at is not None else tile.more.mapToGlobal(tile.more.rect().bottomLeft()))
        return m

    def pick(self, work, name, tile=None):
        if name == "folder":
            self.open_folder(work, tile)
        elif name in ("top", "soon"):
            self.bring_up(work, name)
        elif name == "finished":
            self.finish(work)
        elif name == "remove":
            self.ask_remove(work)

    def bring_up(self, work, where):
        """G2: the sheet closes, the title's first piece goes to the top of Current (before Up Next, in its tier, as
        Current's ⋯ does) or the top of Soon; the rest stays in Goal; the list scrolls to it once it's there."""
        moves, writer = self._writer()
        if moves is None or not work.pieces or moves.refused() is not None:
            return None
        piece = work.pieces[0]
        ids = list(piece.item_ids)
        base = moves.base()
        rows_ = base.rows if base is not None else ()
        rest = len(work.pieces) > 1
        if where == "top":
            n = 1
            text = (strings.GOAL_UP if rest else strings.GOAL_UP_ALL).format(title=work.title, first=piece.line, n=n)
            hero = rows_[0] if rows_ else None           # before Up Next, in its tier (Current's ⋯ *Up next*)

            def command(t):
                if hero is None:
                    return writer.move(ids, "now", label=t)
                return writer.move(ids, hero.tier, before_id=hero.episodes[0].id, label=t)
        else:
            slot, _files, after_id = soon_slot(rows_, None)     # Current's ⋯ *Soon*'s rule: after a show the line cuts
            n = slot + 1
            words = strings.GOAL_SOON if rest else strings.GOAL_SOON_ALL
            text = words.format(title=work.title, first=piece.line, n=n)

            def command(t):
                return writer.move(ids, "soon", after_id=after_id, label=t)
        self.close()
        seq = moves._give(Ticket(text, ids=ids), command)
        if seq is not None:
            self.seeking = (ids[0], time.monotonic() + SHEET["seek-s"])
        return seq

    def finish(self, work):
        """*Move to Finished*: all of the title in Goal, with the Finished toast's choice (D14, IK-11)."""
        moves, _writer = self._writer()
        if moves is None or is_mix(work) or moves.refused() is not None:
            return
        moves._finish(work.title, list(work.item_ids))

    def ask_remove(self, work):
        """*Remove…*: asked first, naming the count (Esc, Back, a click outside: No); then the writer's `remove`."""
        moves, _writer = self._writer()
        if moves is None or moves.refused() is not None:
            return None
        n = work.n_files
        one = n == 1
        return confirm.ask(self.win, strings.GOAL_REMOVE_ASK.format(title=work.title),
                           strings.GOAL_REMOVE_BODY_ONE if one else strings.GOAL_REMOVE_BODY.format(n=n),
                           strings.GOAL_REMOVE_YES_ONE if one else strings.GOAL_REMOVE_YES.format(n=n),
                           strings.GOAL_REMOVE_YES_TIP, default_no=True, danger=True,
                           on_answer=lambda yes: yes and self.remove(work))

    def remove(self, work):
        moves, writer = self._writer()
        if moves is None:
            return None
        ids = list(work.item_ids)
        text = strings.GOAL_REMOVED_ONE.format(title=work.title) if len(ids) == 1 else \
            strings.GOAL_REMOVED.format(title=work.title, n=len(ids))
        return moves._give(Ticket(text, ids=ids), lambda t: writer.remove(ids, label=t))

    def open_folder(self, work, tile=None):
        """⋯ *Open folder*: a press (`press.open`, round 8 row 45) — the tile's ⋯ turns (IK-2), and the folder opens
        on a worker, never on the window's thread (it stalled it)."""
        from app.qt import press as qpress
        base = path_utils.get_data_path(getattr(self.win, "language", None) or "ja")
        path = os.path.join(base, *work.folder.split("/")) if work.folder else base

        def failed(_info):
            say = getattr(self.win, "say", None)
            if say is not None:
                say(strings.GOAL_FOLDER_FAILED.format(title=work.title))
        return qpress.open(self.win, path, key=("open-folder", work.key), failed=failed,
                           at=qpress.widget_mark(tile.more) if tile is not None else None)

    # --- a drag ----------------------------------------------------------------------------------------------- #
    def drag(self, tile, global_pos):
        """A press and 6 px on a tile: its first piece lifts (from Goal) and the sheet closes. A4: a picked tile carries
        every pick — the wells take each title's first part, the Finished well every part of each (IK2-6: as the
        picks' ⋯ *Finished*)."""
        moves, _writer = self._writer()
        work = tile.work
        if moves is None or not work.pieces:
            return False
        if work.key in self.picks and len(self.picks) > 1:      # --- A4: a picked tile carries every pick
            works = self.picked()
            ids = [i for w in works for i in w.pieces[0].item_ids]     # (Up next / Soon: each title's first part;
            every = [i for w in works for i in w.item_ids]             # Finished: every part, as their ⋯, IK2-6)
            if not moves.begin_by_id(ids, "goal", strings.PICKS_TITLES.format(n=f"{len(works):,}"), global_pos,
                                     many=len(works), every=every):
                return False
        elif not moves.begin_by_id(list(work.pieces[0].item_ids), "goal", work.title, global_pos):
            return False
        self.close()
        return True

    # --- G2: the list scrolls to what came up ----------------------------------------------------------------- #
    def view_shown(self, view):
        """The shell showed a view: a piece moved up from here and now on Current's list is scrolled to and washed."""
        if self.seeking is None:
            return False
        item_id, until = self.seeking
        if time.monotonic() > until:
            self.seeking = None
            return False
        lst = self.page.list
        model = lst.model()
        at = next((i for i, e in enumerate(model.entries)
                   if any(ep.id == item_id for ep in getattr(e[1], "episodes", ()))), None)
        if at is None:
            return False
        self.seeking = None
        index = model.index(at, 0)
        lst.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        self.washed = model.entries[at][1].key
        self.wash.flash(lst.visualRect(index))
        return True
