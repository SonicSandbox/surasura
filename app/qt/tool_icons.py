"""The bottom bar's open windows (try a9 #5, Sonic 2026-11-02: "How about an Icon for what is running at the right side
to the left of Anki? showing that it's running? And same for youtube, etc. Like the windows that you can still get back
by clicking it if it's running. And if it's not running it wouldn't show"; PROVISIONAL, his idea at the lead's lean).

- **One icon per open tool window** (`windows.open_tools`: Junban, YouTube, Backfill, the Anki window, Report a
  problem…, in the order they opened), just left of *Anki · N waiting*; none open, nothing shows. A window closed takes
  its icon with it; the work it leaves finishing shows in the phase strip at the bar's left, as before.
- **The phase strip's look** (`phase_strip.py`): a circle at its size, the ring dim at rest, the window's mark inside
  (`strings.TOOL_MARKS`: 順, ▶, 声…, else its name's first letter; the Anki window Anki's star), the accent arc turning
  while the window works (`SecondaryWindow.at_work`: a write or a press of its).
- **A click brings the window back** (`windows.bring_back`): out of the icon a minimise tucked it into (no bare title bar
  in the desktop's corner any more), or to the front. **A right-click** (or the keyboard's menu key; try a9.1, Sonic:
  "they can right click on it for an option to stop it"): *Show* · *Stop* (while its window runs work it can stop,
  `SecondaryWindow.stoppable`) · *Close* (`close_for_good`: what it is doing stops too) — one menu for every icon. Its
  hover: the window's name and what it is doing (its status
  line, else *Working* / *Open*), then what a click does. One Tab stop per icon; Enter or Space brings it back.
- **S19:** an icon repaints only when its look changed (`paints`), its hover is set only when its words changed; the
  arc's clock runs only while one turns. Told by the windows themselves (`SecondaryWindow.tell_icon`): opened, closed,
  tucked, brought back, a write begun or ended, a press changed, a line said.
"""
from PyQt6 import sip
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QFont, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QMenu, QWidget

from app import theme
from app.qt import logos, motion, strings, style, windows
from app.qt import press as qpress
from app.qt.phase_strip import ARC_W, RING_W

LOGOS = {"anki": "anki_outline"}               # the windows whose icon is a logo (`logos.CLEARED`): the phase strip's star


def mark_of(name, title):
    """The character inside `name`'s icon: its own (`strings.TOOL_MARKS`), else its title's first letter."""
    mark = strings.TOOL_MARKS.get(name)
    if mark:
        return mark
    title = (title or name or "?").strip()
    return title[:1].upper() or "?"


def menu_of(parent, entries):
    """The bottom bar's one right-click menu (try a9.1), for its icons on both sides — the open windows' here and the
    phase strip's circles: `entries` [((words, tip), do), …] in order, each an item with its tip; a press runs `do()`.
    -> the QMenu (Esc closes it; nothing runs)."""
    m = QMenu(parent)
    m.setToolTipsVisible(True)
    for (words, tip), do in entries:
        act = m.addAction(words)
        act.setToolTip(tip)
        act.triggered.connect(lambda _c=False, do=do: do())
    return m


class ToolIcon(QAbstractButton):
    """One open window's icon: a click brings it back."""

    def __init__(self, name, win, parent=None):
        super().__init__(parent)
        self.name, self.win = name, win
        self.setObjectName("toolicon")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.mark = mark_of(name, getattr(win, "tool_name", ""))
        self.paints = 0
        self._look = None
        self._pix = None
        self._turn = motion.Turn(self, self.update)
        side = round(theme.size("phase-circle"))
        self.setFixedSize(side, side)
        self.clicked.connect(self._clicked)
        if name in LOGOS:
            self._load_logo()

    def sizeHint(self):
        side = round(theme.size("phase-circle"))
        return QSize(side, side)

    def _clicked(self):
        if not self.win.gone:
            windows.bring_back(self.win)

    def _load_logo(self):
        def got(pix):
            if not sip.isdeleted(self):
                self._pix = pix
                self.update()
        logos.logo(LOGOS[self.name], theme.size("phase-mark"), got, dpr=self.devicePixelRatioF())

    def look(self):
        """(at work, tucked away, the hover's words): repainted only when the first two changed (S19)."""
        win = self.win
        working = win.at_work()
        said = win.status.text().strip()
        doing = said or (strings.TOOL_WORKING if working else strings.TOOL_OPEN)
        tucked = win.tucked()
        tip = strings.TOOL_TIP.format(name=win.tool_name, doing=doing)
        tip += "\n• " + (strings.TOOL_BACK_TIP if tucked else strings.TOOL_FRONT_TIP)
        tip += "\n• " + strings.TOOL_MENU_TIP
        return working, tucked, tip

    def refresh(self):
        working, tucked, tip = now = self.look()
        before = self._look
        self._look = now
        if before is None or before[2] != tip:
            self.setToolTip(tip)
            self.setAccessibleName(tip.replace("\n• ", ". "))
        self._turn.set_running(working)
        if before is None or before[:2] != (working, tucked):
            self.update()

    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        c = style.colours()
        side = float(min(self.width(), self.height()))
        r = QRectF((self.width() - side) / 2.0, (self.height() - side) / 2.0, side, side)
        ring = r.adjusted(ARC_W, ARC_W, -ARC_W, -ARC_W)
        working, tucked = (self._look or (False, False, ""))[:2]
        p.setPen(QPen(style.qcolor(c["line-hi"]), RING_W))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        if self.hasFocus() or self.underMouse():            # the keyboard's, or the hand's: the phase strip's wash
            wash = style.qcolor(c["accent"])
            wash.setAlphaF(0.30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(wash)
            p.drawEllipse(ring.adjusted(RING_W, RING_W, -RING_W, -RING_W))
            p.setBrush(Qt.BrushStyle.NoBrush)
        if working:
            motion.spin_arc(p, r, self._turn.turning, style.qcolor(c["accent"]), width=ARC_W)
        if self._pix is not None:
            pix = self._pix
            w, h = pix.width() / pix.devicePixelRatio(), pix.height() / pix.devicePixelRatio()
            p.drawPixmap(QRectF(r.center().x() - w / 2.0, r.center().y() - h / 2.0, w, h), pix, QRectF(pix.rect()))
        elif self.name not in LOGOS:
            mark = theme.size("phase-mark")
            font = QFont()
            font.setFamilies(theme.font_families("ja"))
            font.setPixelSize(max(1, round(mark)))
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(style.qcolor(c["ink"] if working or tucked else c["ink-dim"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.mark)
        p.end()

    def menu(self):
        """The icon's own menu: *Show* · *Stop* (while its window runs work it can stop) · *Close* — every icon's."""
        win = self.win
        return menu_of(self, [(pair, lambda do=do: None if win.gone else do())       # (one menu rule: menu_of)
                              for pair, do, shown in ((strings.TOOL_SHOW, lambda: windows.bring_back(win), True),
                                                      (strings.TOOL_STOP, win.stop_work, win.stoppable()),
                                                      (strings.TOOL_CLOSE, win.close_for_good, True)) if shown])

    def contextMenuEvent(self, event):
        if not self.win.gone:
            m = self.menu()
            m.exec(event.globalPos())
            m.deleteLater()                                 # (one menu a right-click, gone with it)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.isAutoRepeat():
            self.click()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class ToolIcons(QWidget):
    """The row of icons, one per open window of `main`'s; hidden while none is open."""

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.setObjectName("toolicons")
        self.setAccessibleName(strings.TOOL_ICONS_NAME)
        self.icons = {}                                     # id(window) -> its ToolIcon, in the order they opened
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(round(theme.size("phase-gap")))
        self.setVisible(False)

    def refresh(self):
        """The open windows asked again: an icon added for a window opened, taken away for one closed, and each looked
        at again (repainted only when its look changed)."""
        if sip.isdeleted(self):
            return
        tools = windows.open_tools(self.main)
        live = {id(win) for _name, win in tools}
        for key in [k for k in self.icons if k not in live]:
            icon = self.icons.pop(key)
            self.layout().removeWidget(icon)
            icon.hide()
            qpress.let_go(icon)                             # (its Turn filters the main window until it goes: Qt-C2)
        for name, win in tools:
            icon = self.icons.get(id(win))
            if icon is None or icon.win is not win:
                icon = self.icons[id(win)] = ToolIcon(name, win, self)
                self.layout().addWidget(icon)
            icon.refresh()
        self.setVisible(bool(self.icons))
