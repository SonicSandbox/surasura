"""The Settings page (W3.3 P3; the RUNBOOK's P3 row and its register's resolutions; the old mock's page, mock-g16
:585–645 and `settingsHTML` / `sectionCard` / `findBox`, flat — RS-1; the foundation brief §2 *Overlays and
Settings*, §4: the page on the ground, its sections layer-0 slabs, the top hairline lit, the lower edge darker, no side
edges).

`SettingsPage(shell_or_services, language)`: the nav on the left (each section's icon and name, the one in view lit; a
click glides the page there on the motion clock, reduced motion jumps); on the right one scroll area holding the big
search first, then the section slabs in order, every other one tinted. A slab: its head, its rows, its *More options ·
N* fold (opened in place; *Fewer options*). The page **decides nothing**: what a row shows, when it shows and what a
change writes are `settings_catalog`'s; the page paints it and hands every change to the settings service.

- **Rows** from the catalog, one widget each (`RowView`): its label in bold and its one-line help under it, its control
  on the right (`settings_controls`); a `sub` row indented, group names above their rows. A door row's buttons open
  `windows.OPENERS` (each shown only while its opener is registered and `windows.available` says so; the modules looked
  for on a worker, as `windows._Doors` does). Status, summary, custom and action rows are laid out with an empty slot
  their own package fills (`custom_row(row_id)`: P4, P5, P8, P9, P11).
- **Saving:** a control's `changed(v)` → `catalog.change(row, settings, language, v)` → `services.settings.set(changes)`
  — only when there is something to write; nothing at build, search, fold or reveal, nothing for the same value. A
  per-language key (`catalog.PER_LANGUAGE`) is written as `set({}, update=…)` (the lead's S1 merge: onto the file's own
  value at write time); its control keeps the value it showed until that write lands. Never `save_settings` or
  `save_keys` from here.
- **Refresh:** a landed write (`bridge.settings_written(keys)`) re-reads only the rows showing those keys (signals
  blocked, repainted only when the value moved: S19) and asks every row's `when` again; a language switch asks them for
  the new language without rebuilding.
- **A choice never moves the page** (brief §2 ✅, "It shouldn't move"): Qt's focus scroll stays Tab's alone (a click
  never `ensureWidgetVisible`s), and a change that shows or hides rows keeps the changed control's place in the
  viewport: its y is taken before, the layout settled and the scroll bar corrected in the same turn, before a paint
  (`_keeping`).
- **Search** filters by `catalog.find`: group names hidden, *More options* opened where a row matches, empty slabs
  hidden, *No setting matches "q".* when none does; cleared, the folds are as they were. `/` on the page focuses it; Esc
  in it clears it first (the shell's router sends Esc on to the focused widget).
- **`reveal(target)`** (a row id or key, or a section id; `known`, `mine_line`, `soon_line`): the row's *More options*
  opened if needed, the page glided so the row stands at the top third, the row washed once (1.6 s; reduced motion a
  steady 1 s) — the only scroll the page makes by itself.
- **Built in slices** (B4): the frame (nav and search) at once, then the rows in slices of at most 4 ms a turn of the
  event loop (`QTimer.singleShot(0)`), the slab a reveal needs first, then from the top; `ready` when done; each slice's
  time in `slice_ms`.
"""
import bisect
import os
import time
from collections import Counter
from contextlib import contextmanager

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QEvent, QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from app import theme
from app.qt import applog, bridge, logos, motion, style, windows
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_live
from app.qt import settings_strings as S
from app.services import settings as settings_service

SLICE_MS = 4.0                  # the GUI thread's step (charter §4): what a slice may take
BUILD_MS = 2.5                  # rows built and shown until then; the section's layout fills the rest
BIG = 10 ** 6                   # a number field's ceiling where the catalog names none
# What a store line reveals until P6 draws it (the RUNBOOK: until then, the switch's row / the Content section)
FALLBACK = {"mine_line": "connect_enabled", "soon_line": "content"}
PLACEHOLDER_KINDS = ("summary", "status", "custom", "action")
SETTLE_MORE = 4                 # `hold`: layout passes after the first settle while the held row still moves

# The sections' icons: the old mock's line icons (mock-g16 `<symbol id="i-…">`, 16 × 16), drawn in a text colour.
ICONS = {
    "star": (1.4, '<path d="M8 1.8l1.9 4 4.3.5-3.2 2.9.9 4.3L8 11.4l-3.9 2.1.9-4.3L1.8 6.3l4.3-.5z"/>'),
    "words": (1.4, '<rect x="2" y="2.5" width="12" height="11" rx="2"/><path d="M5 6h6M5 8.5h6M5 11h3.5"/>'),
    "anki": (1.4, '<rect x="3.4" y="1.8" width="8.4" height="11" rx="1.4" transform="rotate(-8 7.6 7.3)"/>'
                  '<path d="M8.4 5.2l.7 1.4 1.5.2-1.1 1 .3 1.5-1.4-.7-1.3.7.2-1.5-1.1-1 1.5-.2z" fill="currentColor"'
                  ' stroke="none"/>'),
    "order": (1.5, '<path d="M4 3v10M2 11l2 2 2-2M8 4h6M8 8h4.5M8 12h3"/>'),
    "fill": (1.4, '<rect x="2.2" y="2.2" width="11.6" height="11.6" rx="2"/><path d="M5 6h6M5 9h3"/>'
                  '<path d="M10.5 9.5l1.2 1.2 2.1-2.4" stroke-width="1.6"/>'),
    "level": (1.5, '<path d="M2 12.5h12"/><rect x="3" y="8" width="2.2" height="4.5" rx=".6"/>'
                   '<rect x="6.9" y="5.5" width="2.2" height="7" rx=".6"/><rect x="10.8" y="3" width="2.2" height="9.5"'
                   ' rx=".6"/>'),
    "text": (1.4, '<path d="M3.8 1.8h5.6l2.9 2.9v9.5H3.8z"/><path d="M9.4 1.8v2.9h2.9M5.9 8h4.3M5.9 10.4h4.3"/>'),
    "content": (1.4, '<rect x="2" y="2.5" width="4.5" height="11" rx="1"/><rect x="8" y="2.5" width="6" height="5"'
                     ' rx="1"/><rect x="8" y="9" width="6" height="4.5" rx="1"/>'),
    "inbox": (1.4, '<path d="M2 9.2l1.8-6h8.4l1.8 6v3.6a1.2 1.2 0 0 1-1.2 1.2H3.2A1.2 1.2 0 0 1 2 12.8z"/>'
                   '<path d="M2 9.2h3.4l.9 1.6h3.4l.9-1.6H14"/>'),
    "link": (1.5, '<path d="M6.8 9.2a2.8 2.8 0 0 0 4 0l2.2-2.2a2.8 2.8 0 0 0-4-4l-.8.8"/>'
                  '<path d="M9.2 6.8a2.8 2.8 0 0 0-4 0L3 9a2.8 2.8 0 0 0 4 4l.8-.8"/>'),
    "reading": (1.4, '<path d="M1.8 3.2c2.2-.9 4.4-.6 6.2.8 1.8-1.4 4-1.7 6.2-.8v9.6c-2.2-.9-4.4-.6-6.2.8-1.8-1.4-4-1.7'
                     '-6.2-.8z"/><path d="M8 4v9.6"/>'),
    "sentence": (1.4, '<path d="M2 4.5h12M2 8h9M2 11.5h6"/><path d="M12.5 10.5l1.5 1.5-1.5 1.5"/>'),
    "export": (1.5, '<path d="M8 10V2.5M5 5.2l3-2.9 3 2.9"/><path d="M3 9.5v3a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-3"/>'),
    "app": (1.4, '<rect x="2" y="2.5" width="12" height="11" rx="2"/><path d="M2 5.5h12"/>'
                 '<circle cx="4" cy="4" r=".5" fill="currentColor"/><circle cx="5.6" cy="4" r=".5" fill="currentColor"/>'),
    "search": (1.6, '<circle cx="7" cy="7" r="4.6"/><path d="M10.5 10.5L14 14"/>'),
    "chev": (1.8, '<path d="M6 3.5L10.5 8 6 12.5"/>'),
    "chev-open": (1.8, '<path d="M3.5 6L8 10.5 12.5 6"/>'),
}
_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="{ink}" stroke-width="{w}" '
        'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
_PIXMAPS = {}


def _f():
    return theme.text_factor(style.current()[1])


def _px(n):
    return round(n * _f())


def icon_pixmap(name, colour, size_name, dpr=None):
    """A section icon in a theme colour (by name) at a size token, drawn once per (icon, colour, size, ratio)."""
    dpr = dpr or (QApplication.primaryScreen().devicePixelRatio() if QApplication.primaryScreen() else 1.0)
    side = theme.size(size_name, style.current()[1])
    ink = style.colours()[colour]
    key = (name, ink, side, dpr)
    if key not in _PIXMAPS:
        width, body = ICONS[name]
        svg = _SVG.format(ink=ink[:7], w=width, body=body.replace("currentColor", ink[:7]))
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        n = max(1, round(side * dpr))
        pix = QPixmap(n, n)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(p, QRectF(0, 0, n, n))
        p.end()
        pix.setDevicePixelRatio(dpr)
        _PIXMAPS[key] = pix
    return _PIXMAPS[key]


def _show(widget, shows):
    """`widget` shown or hidden — only when that changes. A widget made into a shown slab is hidden-but-not-yet-shown
    until the layout's queued show reaches it: it is hidden explicitly here, or that show would bring a row back whose
    `when` says no (a row built hidden after its slab first showed)."""
    explicit = widget.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
    if widget.isHidden() == shows or not explicit:
        widget.setVisible(shows)


def _alive(w):
    try:
        return w is not None and not sip.isdeleted(w)
    except RuntimeError:
        return False


class _Scroll(QScrollArea):
    """The page's scroll area: Qt scrolls a focused widget into view only when focus moved by Tab
    (`focusNextPrevChild`), never for a click — a choice never moves the page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab_scrolls = 0

    def focusNextPrevChild(self, forward):
        moved = super().focusNextPrevChild(forward)        # Qt's own: ensureWidgetVisible(the new focus) — Tab's only
        if moved:
            self.tab_scrolls += 1
        return moved


class Search(QWidget):
    """The big search (the mock's `.set-top .find`): a cut with the search icon, the field and its `/` hint. Esc in it
    clears it first; empty, Esc goes on (the shell's router)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        style.styled(self, "settingsfind")
        row = QHBoxLayout(self)
        self.icon = QLabel(self)
        self.edit = QLineEdit(self)
        self.edit.setObjectName("settingssearch")
        self.edit.setPlaceholderText(S.SEARCH_PLACEHOLDER)
        self.edit.setAccessibleName(S.SEARCH_NAME)
        self.edit.setToolTip(S.SEARCH_KEY_TIP)
        self.edit.setClearButtonEnabled(False)
        self.edit.installEventFilter(self)
        self.kbd = QLabel(self)
        self.kbd.setObjectName("settingskbd")
        self.kbd.setText(S.SEARCH_KEY)
        self.kbd.setToolTip(S.SEARCH_KEY_TIP)
        row.addWidget(self.icon)
        row.addWidget(self.edit, 1)
        row.addWidget(self.kbd)
        self.setFocusProxy(self.edit)
        self.restyle()

    def restyle(self):
        f = _f()
        self.layout().setContentsMargins(round(12 * f), 0, round(10 * f), 0)
        self.layout().setSpacing(round(8 * f))
        size = style.current()[1]
        self.setFixedHeight(round(theme.size("settings-search-h", size)))
        self.setMaximumWidth(round(theme.size("settings-search-max", size)))
        self.icon.setPixmap(icon_pixmap("search", theme.SETTINGS_TEXT["placeholder"], "settings-search-icon"))
        pal = self.edit.palette()          # the app's placeholder is the faint ink: here the proven role (S5)
        pal.setColor(QPalette.ColorRole.PlaceholderText, style.qcolor(style.colours()[theme.SETTINGS_TEXT["placeholder"]]))
        self.edit.setPalette(pal)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            if self.edit.text():
                self.edit.clear()
                return True                       # used: the search cleared first
        return False


class Slab(QWidget):
    """A section: a layer-0 slab (the stylesheet's `settingsslab`, tinted every other one), its head, its rows, its
    *More options · N* fold and the rows under it."""

    def __init__(self, section, tint, parent=None):
        super().__init__(parent)
        style.styled(self, "settingsslab")
        self.section = section
        self.setProperty("tint", "true" if tint else "false")
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.head = QWidget(self)
        head = QHBoxLayout(self.head)
        self.icon = QLabel(self.head)
        self.name = QLabel(self.head)
        self.name.setObjectName("settingshead")
        self.name.setText(section.name.upper())
        self.name.setAccessibleName(section.name)
        head.addWidget(self.icon)
        head.addWidget(self.name, 1)
        box.addWidget(self.head)
        self.main = QWidget(self)
        self.main_box = QVBoxLayout(self.main)
        self.main_box.setContentsMargins(0, 0, 0, 0)
        self.main_box.setSpacing(0)
        box.addWidget(self.main)
        self.more_row = QWidget(self)
        more = QHBoxLayout(self.more_row)
        self.more = QPushButton(self.more_row)
        self.more.setObjectName("settingsmore")
        self.more.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.addWidget(self.more)
        more.addStretch(1)
        box.addWidget(self.more_row)
        self.more_row.setVisible(False)
        self.adv = QWidget(self)
        self.adv.setObjectName("settingsadv")
        adv = QVBoxLayout(self.adv)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(0)
        adv.addWidget(style.separator(self.adv))
        self.adv_box = QVBoxLayout()
        self.adv_box.setContentsMargins(0, 0, 0, 0)
        self.adv_box.setSpacing(0)
        adv.addLayout(self.adv_box)
        box.addWidget(self.adv)
        self.adv.setVisible(False)
        self.placed = {"main": [], "adv": []}          # catalog index of each widget placed, per container
        self._fold = None
        self.restyle()

    def place(self, widget, index, adv):
        """`widget` into its container at the place of its catalog `index` (a slice may build out of order)."""
        placed = self.placed["adv" if adv else "main"]
        at = bisect.bisect(placed, index)
        placed.insert(at, index)
        (self.adv_box if adv else self.main_box).insertWidget(at, widget)

    def set_open(self, opened, count):
        if self._fold == (opened, count):
            return                                           # repainted only when its words change (S19)
        self._fold = (opened, count)
        name = "chev-open" if opened else "chev"
        self.more.setText(S.FEWER_OPTIONS if opened else S.MORE_OPTIONS.format(n=count))
        self.more.setToolTip(S.FEWER_TIP if opened else S.MORE_TIP)
        self.more.setIcon(QIcon(icon_pixmap(name, theme.SETTINGS_TEXT["more"], "settings-more-icon")))

    def restyle(self):
        f = _f()
        top, side, bottom = theme.SPACING["settings-head"]
        self.head.layout().setContentsMargins(round(side * f), round(top * f), round(side * f), round(bottom * f))
        self.head.layout().setSpacing(round(10 * f))
        self.icon.setPixmap(icon_pixmap(self.section.icon, "accent", "settings-head-icon"))
        top, side, bottom = theme.SPACING["settings-more"]
        self.more_row.layout().setContentsMargins(round(side * f), round(top * f), round(side * f), round(bottom * f))
        icon = round(theme.size("settings-more-icon", style.current()[1]))
        self.more.setIconSize(QSize(icon, icon))
        self.setMaximumWidth(round(theme.size("settings-card-max", style.current()[1])))


class RowView(QWidget):
    """One setting row (the mock's `.srow`): its label and help on the left, its control (and doors) on the right, in
    `slot`; when the row is too narrow for both side by side (text size L in a narrow window), its words stand above
    its control (B4). The level stands stacked always (S7): its label and *Automatic* (`aside`) on top, the slider the
    row's full width under them, its readout (the help line) under the slider. Washed once by a reveal (`wash`,
    0 … 1, painted under its children)."""

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsrow")
        self.row = row
        self.wash = 0.0
        self.controls = []                    # the value controls, in order (the level: its slider, then Automatic)
        self.doors = {}                       # opener name -> Door
        self.stacked = None                   # the words above the control (True) or beside it (False)
        self.label = QLabel(self)
        self.label.setObjectName("settingssublabel" if row.sub else "settingslabel")
        self.label.setWordWrap(True)
        self.help = QLabel(self)
        self.help.setObjectName("settingshelp")
        self.help.setWordWrap(True)
        self.slot = QWidget(self)
        self.slot.setObjectName("settingsslot")
        slot = QHBoxLayout(self.slot)
        slot.setContentsMargins(0, 0, 0, 0)
        self.aside = self.words = None
        if row.kind == "slider":
            line = QVBoxLayout(self)
            top = QHBoxLayout()
            top.addWidget(self.label, 1)
            self.aside = QHBoxLayout()
            top.addLayout(self.aside)
            line.addLayout(top)
            line.addWidget(self.slot)
            line.addWidget(self.help)
            self.stacked = True
        else:
            line = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
            self.words = QVBoxLayout()
            self.words.addWidget(self.label)
            self.words.addWidget(self.help)
            line.addLayout(self.words, 1)
            self.words.setAlignment(Qt.AlignmentFlag.AlignTop)    # the words together at the top beside a tall control
            # a list grows downward from the row's top (a folder added never moves the control the click was on)
            line.addWidget(self.slot, 0, self._slot_align(False))
        line.setSizeConstraint(QBoxLayout.SizeConstraint.SetNoConstraint)
        self.set_words(row.label, row.help)
        self.restyle()

    def _slot_align(self, stacked):
        if stacked:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        return Qt.AlignmentFlag.AlignTop if self.row.kind == "list" else Qt.AlignmentFlag.AlignVCenter

    def _words_min(self):
        return round(theme.size("settings-words-min", style.current()[1]))

    def side_by_side(self):
        """The width the words and the control need beside each other (the words never squeezed below their
        minimum: S7's `known_from_anki`)."""
        m = self.layout().contentsMargins()
        # a custom slot that narrows further once stacked says what it needs beside the words (`slot_needs`)
        needs = next((w.slot_needs for w in self.slot.children() if getattr(w, "slot_needs", None)), None)
        slot = needs() if needs is not None else self.slot.minimumSizeHint().width()
        return m.left() + m.right() + self._words_min() + self.layout().spacing() + slot

    def minimumSizeHint(self):
        """As narrow as the stacked row: the page never cuts a control at its right edge, it stacks the row (B4)."""
        hint = super().minimumSizeHint()
        m = self.layout().contentsMargins()
        return QSize(m.left() + m.right() + max(self.slot.minimumSizeHint().width(), self._words_min() // 2),
                     hint.height())

    def arrange(self, width=None):
        """Side by side when `width` (the row's own) holds both, else the words above the control."""
        if self.row.kind == "slider":
            return
        width = self.width() if width is None else width
        stacked = width < self.side_by_side()
        if stacked == self.stacked:
            return
        self.stacked = stacked
        line = self.layout()
        line.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)
        line.setAlignment(self.slot, self._slot_align(stacked))
        least = 0 if stacked else self._words_min()
        self.label.setMinimumWidth(least)
        self.help.setMinimumWidth(least)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange(event.size().width())

    def set_words(self, label, help_):
        self.label.setText(label)
        self.label.setVisible(bool(label))
        self.help.setText(help_)
        self.help.setVisible(bool(help_))

    def restyle(self):
        f = _f()
        pad_y, pad_x = theme.SPACING["settings-row"]
        left = theme.SPACING["settings-sub-indent"] if self.row.sub else pad_x
        self.layout().setContentsMargins(round(left * f), round(pad_y * f), round(pad_x * f), round(pad_y * f))
        self.layout().setSpacing(round((6 if self.row.kind == "slider" else 14) * f))
        self.slot.layout().setSpacing(round(8 * f))
        if self.aside is not None:
            self.aside.setSpacing(round(8 * f))
        else:
            self.words.setSpacing(round(1 * f))
        for c in self.controls:
            c.restyle()
        if self.row.id in logos.ROWS:         # PL: the service's cleared logo before its words, at this size
            logos.show(self)
        if self.row.kind != "slider" and self.stacked is not None:     # a new text size: asked again (a row not
            self.stacked = None                                         # yet laid out is asked at its first resize)
            self.arrange()

    def set_wash(self, level):
        level = max(0.0, min(1.0, level))
        if level != self.wash:
            self.wash = level
            self.update()

    def paintEvent(self, event):
        if self.wash <= 0:
            return
        p = QPainter(self)
        colour = style.qcolor(style.colours()["settings-row-wash"])
        colour.setAlphaF(colour.alphaF() * self.wash)
        p.fillRect(self.rect(), colour)
        p.end()


def auto_change(row, on, slider):
    """Automatic's toggle on the level row: on, Automatic alone; off, the band the slider shows (Automatic's, while it
    was on) written with it — 2.x's D3: the list doesn't change the moment you switch it off (W3.1b B1)."""
    if on:
        return {row.keys[1]: True}
    return {row.keys[1]: False, row.keys[0]: slider.value()}


class SettingsPage(QWidget):
    """The Settings tab's page. `shell_or_services`: the shell (its services, bridge, doors) or the services alone (a
    test, or the page standalone: it makes its own bridge, and a door asks through `door_asked`). `found`: the optional
    modules and the reveal gate as a catalog `ctx` (a test's); None looks for them on a worker."""

    ready = pyqtSignal()                      # every row built
    door_asked = pyqtSignal(str)              # a door's opener name, when the page has no shell to open it in
    row_built = pyqtSignal(str)               # a row's widget placed (P4: its live words filled then)
    language_set = pyqtSignal(str)            # `set_language` done (P4: the live rows read again)

    def __init__(self, shell_or_services, language=None, parent=None, found=None):
        super().__init__(parent)
        self.setObjectName("settingspage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        is_shell = hasattr(shell_or_services, "services")
        self.shell = shell_or_services if is_shell else None
        self.services = shell_or_services.services if is_shell else shell_or_services
        self.store = self.services.settings
        heard = getattr(self.shell, "bridge", None)
        self.bridge = heard if heard is not None else bridge.Bridge(settings=self.store, parent=self)
        self.language = language or self.store.get().get("target_language") or "ja"
        self._found = frozenset(found) if found is not None else None     # None: still being looked for
        self._road = None                     # the known-words road the user chose (page state, never a key)
        self._query = ""
        self._open = set()                    # the sections whose More options the user opened
        self._overlay = {}                    # per-language key -> [the whole value shown, landings when written]
        self._landings = 0
        self._last = None                     # the control the last change came from: what a later relayout keeps
        self._scroll_anim = None
        self._wash_anim = None
        self._washed = None
        self._wash_timer = None
        self._reveal_wanted = None
        self._revealed = None                 # a reveal made while the build goes on: aimed at again after each slice
        self.rows = {}                        # row id -> RowView, once built
        self.slabs = {}                       # section id -> Slab, once built
        self.nav = {}                         # section id -> its nav button
        self.slots = {row.id: self._slot(row) for row in catalog.ROWS if row.kind in PLACEHOLDER_KINDS}
        self.paints = Counter()               # row id -> times a refresh repainted it (S19)
        self.slice_ms = []                    # each build slice's time on the GUI thread
        self.between_ms = []                  # the event loop's own work between two slices (layout, paint)
        self._slice_end = None
        self.built_order = []                 # the sections in the order their first row was built
        self.built = False
        self._build_frame()
        self._queue = list(enumerate(catalog.ROWS))
        self.takes = {}                       # row id -> fn(value) -> True when it handled the change itself (P4)
        self.bridge.settings_written.connect(self._written)
        self.live = settings_live.Live(self)  # P4: the live rows (after `_written`: its repaint comes second)
        windows._ROWS.add(self)               # told when the doors' modules have been looked for (`refresh`)
        if self._found is None:
            QTimer.singleShot(0, self._look)
        if not _WARMED:
            bridge.run_in_worker(_warm, then=_warmed, failed=_warm_failed)
        QTimer.singleShot(0, self._slice)

    # --- the frame: the nav and the search, at once -------------------------------------------------------------- #
    def _build_frame(self):
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        self.nav_panel = style.styled(QWidget(self), "settingsnav")
        self.nav_panel.setAccessibleName(S.NAV_NAME)
        nav = QVBoxLayout(self.nav_panel)
        nav.setSpacing(round(2 * _f()))
        for section in catalog.SECTIONS:
            b = QPushButton(section.name.replace("&", "&&"), self.nav_panel)    # "&" shown, never a mnemonic (S2)
            b.setObjectName("settingsnavitem")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(S.CHANGE_TIP.format(section=section.name))
            b.setAccessibleName(section.name)
            b.clicked.connect(lambda _c=False, s=section.id: self.go_to(s))
            self.nav[section.id] = b
            nav.addWidget(b)
        nav.addStretch(1)
        line.addWidget(self.nav_panel)
        line.addWidget(style.separator(self, vertical=True))
        self.scroll = _Scroll(self)
        self.scroll.setObjectName("settingsscroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body = style.styled(QWidget(), "settingsbody")
        outer = QHBoxLayout(self.body)
        self.column = QWidget(self.body)
        outer.addWidget(self.column, 1)
        outer.addStretch(0)
        self.column_box = QVBoxLayout(self.column)
        self.column_box.setContentsMargins(0, 0, 0, 0)
        self.search = Search(self.column)
        self.search.edit.textChanged.connect(self._searched)
        self.column_box.addWidget(self.search, 0, Qt.AlignmentFlag.AlignLeft)
        self.nothing = QLabel(self.column)
        self.nothing.setObjectName("settingshint")
        self.nothing.setVisible(False)
        self.column_box.addWidget(self.nothing)
        self.column_box.addStretch(1)
        self.scroll.setWidget(self.body)
        line.addWidget(self.scroll, 1)
        self.scroll.verticalScrollBar().valueChanged.connect(self._light_nav)
        self.scroll.verticalScrollBar().actionTriggered.connect(self._let_go)     # a wheel, a drag, a key: the user's
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)    # Tab's focus scroll, anyone's setValue
        self.scroll.verticalScrollBar().rangeChanged.connect(self._ranged)      # a layout's clamp is nobody's scroll
        self._apply_sizes()
        settings, ctx = self._settings(), self._ctx()
        for section in catalog.SECTIONS:
            self.nav[section.id].setVisible(self._section_shows(section.id, settings, ctx))

    def _apply_sizes(self):
        f = _f()
        size = style.current()[1]
        top, right, bottom, left = theme.SPACING["settings-nav"]
        self.nav_panel.layout().setContentsMargins(round(left * f), round(top * f), round(right * f), round(bottom * f))
        self.nav_panel.setFixedWidth(round(theme.size("settings-nav", size)))
        icon = round(theme.size("settings-nav-icon", size))
        for section in catalog.SECTIONS:
            b = self.nav[section.id]
            ic = QIcon()
            ic.addPixmap(icon_pixmap(section.icon, theme.SETTINGS_TEXT["nav-unlit"], "settings-nav-icon"),
                         QIcon.Mode.Normal, QIcon.State.Off)
            ic.addPixmap(icon_pixmap(section.icon, theme.SETTINGS_TEXT["nav-lit"], "settings-nav-icon"),
                         QIcon.Mode.Normal, QIcon.State.On)
            b.setIcon(ic)
            b.setIconSize(QSize(icon, icon))
        top, side, bottom = theme.SPACING["settings-main"]
        self.body.layout().setContentsMargins(round(side * f), round(top * f), round(side * f), round(bottom * f))
        self.column.setMaximumWidth(round(theme.size("settings-card-max", size)))
        self.column_box.setSpacing(round(theme.SPACING["settings-card-gap"] * f))
        self.search.restyle()

    def restyle(self):
        """A text size applied live (the shell's `set_look`; Qt sends no event the painted parts could catch): every
        size the page set read again and every control's `restyle()` — the control last changed keeps its place."""
        with self._keeping(self._last):
            self._apply_sizes()
            for slab in self.slabs.values():
                slab.restyle()
            for view in self.rows.values():
                view.restyle()

    # --- the settings as the page shows them ---------------------------------------------------------------------- #
    def _settings(self):
        """The service's settings, with each per-language value whose write is still on its way as the page shows it."""
        settings = self.store.get()
        if not self._overlay:
            return settings
        settings = settings_service.thaw(settings)
        for key, (whole, _seen) in self._overlay.items():
            settings_service.put(settings, key, whole)
        return settings

    def _ctx(self):
        ctx = set(self._found or ())
        if self._road:
            ctx.add(self._road)
        return frozenset(ctx)

    def _look(self):
        """The optional modules and the Speech reveal gate, looked for on a worker (a file look); the doors' modules
        with them (`windows._FOUND`)."""
        wanted = sorted({op.module for op in windows.OPENERS if op.module} - set(windows._FOUND) - windows._LOOKING)
        windows._LOOKING.update(wanted)
        bridge.run_in_worker(_look_for, wanted, then=self._looked,
                             failed=lambda info: applog.log("settings", f"looking for the modules: {info[1]}"))

    def _looked(self, answer):
        if not _alive(self):
            return
        found, doors = answer
        if doors:
            windows._found(doors)               # tells every door row, this page's `refresh` among them
        self._found = frozenset(found)
        self._refresh_visibility()

    # --- building, in slices -------------------------------------------------------------------------------------- #
    def _slot(self, row):
        slot = QWidget()
        slot.setObjectName(f"slot-{row.id}")
        box = QHBoxLayout(slot)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(round(8 * _f()))
        return slot

    def custom_row(self, row_id):
        """The empty slot a status, summary, custom or action row lays out on its right (P4 / P5 / P8 / P9 / P11 fill
        it: add widgets to its layout). Made with the page, placed when the row is built. KeyError for another row."""
        return self.slots[row_id]

    def row(self, row_id):
        """The row's widget (`RowView`: its `label`, `help`, `slot`, `controls`, `doors`), or None until built."""
        return self.rows.get(row_id)

    def _slice(self):
        if not _alive(self):
            return
        t0 = time.perf_counter()
        if self._slice_end is not None:
            self.between_ms.append((t0 - self._slice_end) * 1000)   # the loop's own turn between: layout, paint
        with self._keeping(self._anchor_for_build(), fallback=False):
            settings, ctx = self._settings(), self._ctx()
            matches = self._matches(settings, ctx)
            while self._queue and (time.perf_counter() - t0) * 1000 < BUILD_MS:
                if not _WARMED and _WARM_ROWS(self._queue[0][1]):
                    break                     # its module is still being imported on the worker: never raced here
                index, row = self._queue.pop(0)
                if self._build_guarded(index, row, settings):
                    self._show_section(row.section, settings, ctx, matches)   # shown in the slice that built it
            self._show_nothing(matches)
        self._aim()
        self._slice_end = time.perf_counter()
        self.slice_ms.append((self._slice_end - t0) * 1000)
        if self._reveal_wanted is not None and self._section_built(catalog.locate(self._reveal_wanted)[0]):
            target, self._reveal_wanted = self._reveal_wanted, None
            self.reveal(target)
        if self._queue:
            QTimer.singleShot(0 if _WARMED or not _WARM_ROWS(self._queue[0][1]) else WARM_WAIT_MS, self._slice)
            return
        self.built = True
        self._revealed = None
        if self.built_order != [s.id for s in catalog.SECTIONS if s.id in self.slabs]:
            self._tab_order()                 # built out of order (a reveal first): Tab follows the page, not the build
        self._light_nav()
        self.ready.emit()

    def _tab_order(self):
        chain = [self.search.edit]
        for section in catalog.SECTIONS:
            slab = self.slabs.get(section.id)
            if slab is None:
                continue
            for row in catalog.rows(section.id):
                view = self.rows.get(row.id)
                if view is not None:
                    chain += [w for w in view.findChildren(QWidget)
                              if w.focusPolicy() & Qt.FocusPolicy.TabFocus and w.parentWidget() is not None]
            chain.append(slab.more)
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

    def _section_built(self, section_id):
        return not any(row.section == section_id for _i, row in self._queue)

    def _prioritise(self, section_id):
        """`section_id`'s rows first in what is left to build (a reveal's slab before the rest)."""
        first = [item for item in self._queue if item[1].section == section_id]
        self._queue = first + [item for item in self._queue if item[1].section != section_id]

    def _aim(self):
        """A reveal made while the build goes on: its row put at the top third again once the slabs above it are built
        (the page could not scroll that far before). Held until the build ends or the user scrolls or acts."""
        widget = self._revealed
        if widget is None or not _alive(widget) or not widget.isVisible():
            return
        if self._scroll_anim is not None and self._scroll_anim.alive:
            return                                         # the glide asks the row's place each frame itself
        self._settle()
        bar = self.scroll.verticalScrollBar()
        end = max(0, min(bar.maximum(), round(self._y_in_body(widget) - self.scroll.viewport().height() / 3)))
        if bar.value() != end:
            self._scroll_to(end)

    def _scroll_to(self, value):
        """The page's own scroll (a glide, a reveal's aim, the never-moves correction): never lets a reveal go."""
        self._own_scroll = True
        try:
            self.scroll.verticalScrollBar().setValue(value)
        finally:
            self._own_scroll = False

    def _scrolled(self, *_args):
        """A scroll the page didn't make itself (Tab focus's `ensureWidgetVisible`, anyone's `setValue`) lets a held
        reveal go, as the user's scroll does (the time lens's H7) — never the clamp a shorter page makes."""
        clamp, self._clamp = getattr(self, "_clamp", None), None
        if getattr(self, "_own_scroll", False) or (clamp is not None and _args and _args[0] == clamp):
            return
        self._let_go()

    def _ranged(self, low, high):
        """The scroll range moved (a relayout): the value Qt clamps into it in the same call (`setRange` emits
        `rangeChanged`, then the clamped `valueChanged`) is no one's scroll. Known by its value, never by a timer: a
        timer still pending let a real scroll after the relayout pass for the clamp (GitHub's #97 run 1)."""
        value = self.scroll.verticalScrollBar().value()      # still the value before the clamp
        self._clamp = min(max(value, low), high) if value < low or value > high else None

    def _let_go(self, *_args):
        """The user scrolled, went to a section or changed a setting: a reveal stops aiming at its row, and its wash
        ends (a washed row is what the build's slices keep in place: it would pull the page back to it)."""
        self._revealed = None
        if getattr(self, "_washed", None) is not None:
            self._end_wash()

    def _anchor_for_build(self):
        """What a slice keeps in place: a revealed row (its wash may be over: held until the build ends), else the
        first row in view (slabs built above it later)."""
        for widget in (self._revealed, self._washed):
            if self._in_view(widget):
                return widget
        if self.scroll.verticalScrollBar().value() > 0:
            return self._top_widget()
        return None

    def _slab(self, section_id):
        slab = self.slabs.get(section_id)
        if slab is None:
            order = [s.id for s in catalog.SECTIONS]
            index = order.index(section_id)
            slab = Slab(catalog.SECTIONS[index], tint=False, parent=self.column)
            slab.more.clicked.connect(lambda _c=False, s=section_id: self.fold(s))
            before = sum(1 for s in self.slabs if order.index(s) < index)
            self.column_box.insertWidget(1 + before, slab)         # after the search, among the slabs in order
            self.slabs[section_id] = slab
            self.built_order.append(section_id)
            slab.setVisible(False)
            slab.ensurePolished()
        return slab

    def _build_guarded(self, index, row, settings):
        """`_build_row`, never ending the build: a row that can't be built is logged and left out, the rest go on and
        `ready` still fires (B2). -> True when it was built."""
        try:
            self._build_row(index, row, settings)
            return True
        except Exception as e:                                    # noqa: BLE001 — one row never stops the page
            applog.log("settings", f"{row.id}: not built: {type(e).__name__}: {e}")
            return False

    def _build_row(self, index, row, settings):
        slab = self._slab(row.section)
        view = RowView(row, slab.adv if row.adv else slab.main)
        if "{" in row.label or "{" in row.help:                # a live word (the version, the deck): its owner's
            view.set_words(_live(row.label), _live(row.help))
        if row.kind in PLACEHOLDER_KINDS:
            view.slot.layout().addWidget(self.slots[row.id])
        else:
            self._make_controls(view, row, settings)
        for name in row.door:
            label, tip = S.ROW_DOORS.get(row.id, {}).get(name) or S.DOORS[name]
            door = sc.Door(label, tooltip=tip, name=label, parent=view.slot)
            door.clicked.connect(lambda _c=False, n=name: self.open_door(n))
            view.slot.layout().addWidget(door)
            view.doors[name] = door
        self._show_doors(view, settings)
        if row.group:
            group = QLabel(slab)
            group.setObjectName("settingsgroup")
            group.setText(S.GROUPS[row.group].upper())
            group.setAccessibleName(S.GROUPS[row.group])
            slab.place(group, index - 0.5, row.adv)
            view.group = group
        else:
            view.group = None
        slab.place(view, index, row.adv)
        self.rows[row.id] = view
        view.ensurePolished()                 # the style's work done in this slice, not when its slab first shows
        self.row_built.emit(row.id)

    def _make_controls(self, view, row, settings):
        kind, tip, name = row.kind, row.tip or None, row.label or None
        if kind == "door" or (kind != "link" and not row.keys and row.id != "known_road"):
            return
        if kind == "link":
            link = sc.Door(S.LINK_OPEN, tooltip=tip, name=name, parent=view.slot)
            link.clicked.connect(lambda _c=False: windows.open_url(S.HOW_PARSING_URL))
            view.slot.layout().addWidget(link)
            return
        value = None
        try:
            value = self._shown(row, settings)
            control = self._control(row, value, settings, tip, name)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            # a hand-edited value no control can take (an unknown band, a list for a number): the row shows the
            # default until the user picks — nothing written by showing it; the rest of the page builds (B2)
            applog.log("settings", f"{row.id}: shown at its default, the file's value can't be shown: {e}")
            held = value
            value = self._shown(row, catalog.defaults())
            if kind == "slider" and isinstance(held, dict):
                value = {**value, row.keys[1]: bool(held.get(row.keys[1]))}     # Automatic as the file holds it
            control = self._control(row, value, catalog.defaults(), tip, name)
        if control is None:
            return
        control.changed.connect(lambda v, r=row, c=control: self._changed(r, v, c))
        view.controls.append(control)
        view.slot.layout().addWidget(control)
        if kind == "slider":                     # *Automatic* beside the slider: the row's other key
            words = QLabel(view.slot)
            words.setObjectName("settingsaffix")
            words.setText(S.LEVEL_AUTOMATIC)
            auto_tip = S.LEVEL_AUTOMATIC_TIP.format(
                n=catalog.value_of(settings, "logic.selection.auto_max_words"))
            auto = sc.Toggle(value[row.keys[1]], tooltip=auto_tip, name=S.LEVEL_AUTOMATIC)
            auto.changed.connect(lambda v, r=row, c=auto, s=control: self._changed(r, auto_change(r, v, s), c))
            view.controls.append(auto)
            place = view.aside if view.aside is not None else view.slot.layout()
            place.addWidget(words)
            place.addWidget(auto)

    def _control(self, row, value, settings, tip, name):
        """`row`'s value control showing `value` (raises ValueError / TypeError for a value it can't take)."""
        kind = row.kind
        if kind == "toggle":
            control = sc.Toggle(value, tooltip=tip, name=name)
        elif kind in ("choice", "cards", "select"):
            opts = list(catalog.options(row, settings, self.language))
            if value not in [v for v, _l, _line in opts]:
                opts.append((value, str(value), ""))       # a value no option names (hand-edited): shown, kept
            tips = S.OPTION_TIPS.get(row.id, {})
            if kind == "cards":
                control = sc.Cards([(v, label, line) for v, label, line in opts], value, tooltip=tip, name=name)
            else:
                cls = sc.Choice if kind == "choice" else sc.Select
                control = cls([(v, label, tips.get(v)) for v, label, _line in opts], value, tooltip=tip, name=name)
        elif kind == "tablets":
            tips = S.OPTION_TIPS.get(row.id, {})
            opts = [(v, label, tips.get(v)) for v, label, _line in catalog.options(row, settings, self.language)]
            control = sc.Tablets(opts, multi=True, value=value, tooltip=tip, name=name)
        elif kind == "list":
            control = sc.Tablets(None, value=value, add_label=S.FOLDER_ADD, tooltip=tip, name=name)
            control.on_add = lambda c=control: self._add_folder(c)
        elif kind == "slider":
            bands = [(band, label) for band, label, _line in catalog.options(row, settings, self.language)]
            control = sc.LevelSlider(bands, value[row.keys[0]], tooltip=tip, name=name)    # its own hint: names apart
        elif kind == "number":
            low, high = row.bounds or (None, None)
            control = sc.NumberField(0 if low is None else low, BIG if high is None else high, value or 0,
                                     tooltip=tip, name=name)
        elif kind == "range":
            low, high = row.bounds or (None, None)
            control = sc.Range(0 if low is None else low, BIG if high is None else high, tuple(value), tooltip=tip,
                               name=name)
        elif kind == "text":
            control = sc.TextField(value, tooltip=tip, name=name)
        else:
            return None
        return control

    def _shown(self, row, settings):
        """What `row`'s controls show: the catalog's value, the road with the page's choice, several switches as the
        keys on."""
        if row.id == "known_road":
            return catalog.known_road(settings, self.language, self._ctx())
        value = catalog.value(row, settings, self.language)
        if row.kind == "tablets" and len(row.keys) > 1:
            return [key for key in row.keys if value.get(key)]
        if row.kind == "range":
            return tuple(value[key] or 0 for key in row.keys)
        return value

    def _show_value(self, view, settings):
        """Put the settings' value in `view`'s controls (no signal) -> True when one moved."""
        row = view.row
        if not view.controls:
            if row.id == "anki_decks":
                self._show_decks(view, settings)
            return False
        value = self._shown(row, settings)
        values = [value[row.keys[0]], value[row.keys[1]]] if row.kind == "slider" else [value]
        moved = False
        for control, v in zip(view.controls, values):
            if control.value() == v:
                continue
            control.blockSignals(True)
            try:
                control.set_value(v)
                moved = True
            except (ValueError, TypeError) as e:           # a value no option names: what it showed stays
                applog.log("settings", f"{row.id}: {e}")
            finally:
                control.blockSignals(False)
        return moved

    def _show_decks(self, view, settings):
        decks = " · ".join(catalog.value(view.row, settings, self.language) or [])
        label = getattr(view, "decks", None)
        if label is None:
            label = view.decks = QLabel(view.slot)
            label.setObjectName("settingsvalue")
            view.slot.layout().insertWidget(0, label)
        label.setText(decks)
        label.setVisible(bool(decks))

    # --- doors ---------------------------------------------------------------------------------------------------- #
    def _show_doors(self, view, settings):
        openers = {op.name: op for op in windows.OPENERS}
        if view.row.id == "anki_decks":
            self._show_decks(view, settings)
        for name, door in view.doors.items():
            op = openers.get(name)
            shows = op is not None and windows.available(op, settings, self.language)
            if door.isHidden() == shows:
                door.setVisible(shows)

    def refresh(self):
        """The doors asked again (`windows._found`: the modules were looked for; a write that can move a door)."""
        if not _alive(self):
            return
        settings = self._settings()
        with self._keeping(self._last):
            for view in self.rows.values():
                if view.doors:
                    self._show_doors(view, settings)
        self._refresh_visibility(anchor=self._last)       # a door row shows once one of its doors is there (S1)

    def open_door(self, name):
        """A door's click: its window, through the shell (`windows.launch`: a failure said in the bar), or `door_asked`."""
        op = next((op for op in windows.OPENERS if op.name == name), None)
        if self.shell is not None and op is not None:
            windows.launch(self.shell, op)
        else:
            self.door_asked.emit(name)

    def _add_folder(self, control):
        folder = QFileDialog.getExistingDirectory(self, S.FOLDER_PICK_TITLE)
        if folder:
            control.add_item(os.path.normpath(folder))

    # --- saving ---------------------------------------------------------------------------------------------------- #
    def _changed(self, row, value, control):
        """A control's change → the catalog's keys → the settings service (only what there is to write)."""
        self._last = control
        self._let_go()
        take = self.takes.get(row.id)
        if take is not None and take(value):
            return                            # its owner wrote it (P4: the shell's text size)
        if row.id == "known_road":
            self._road = f"road:{value}"
            self._refresh_visibility(anchor=control)
            return
        settings = self._settings()
        try:
            changes, update = catalog.change(row, settings, self.language, value)
        except (ValueError, TypeError) as e:
            applog.log("settings", f"{row.id}: {e}")
            return
        if row.keys[0] in catalog.PER_LANGUAGE:
            if update is None:
                return
            key = row.keys[0]
            self._overlay[key] = [changes[key], self._landings]          # shown until the merge lands (S1)
            self.store.set({}, update=update)
        elif changes:
            self.store.set(changes)
            from app.qt import settings_store
            settings_store.resume_connect(settings, changes)             # the automation row on: Connect's marks
            settings_store.kick_on_trust(settings, changes, self.store)  # trust turned on: the waiting ones mine
        else:
            return
        self._refresh_visibility(anchor=control)

    def _written(self, keys):
        """A write landed (anyone's): the rows showing its keys read again, every row's `when` asked again."""
        if not _alive(self):
            return
        self._landings += 1
        keys = set(keys)
        settings = self.store.get()
        for key, (whole, seen) in list(self._overlay.items()):
            mine = catalog.ROW[catalog.rows_for([key])[0]]
            if (catalog.value(mine, settings, self.language) == catalog.value(mine, {key: whole}, self.language)
                    or self._landings - seen >= 2):              # landed (or overtaken by another write: the file's)
                del self._overlay[key]
                keys.add(key)
        language = settings.get("target_language") or "ja"
        if "target_language" in keys and language != self.language:
            self.set_language(language)
            return
        settings = self._settings()
        for row_id in catalog.rows_for(keys):
            view = self.rows.get(row_id)
            if view is None or (view.row.keys and view.row.keys[0] in self._overlay):
                continue
            if self._show_value(view, settings):
                self.paints[row_id] += 1
        if windows._moves_doors(keys):
            self.refresh()
        self._refresh_visibility(anchor=self._last)

    def set_language(self, language):
        """The main window's language changed: every row asked again for it (the Japanese / Chinese rows), the
        per-language values read again; nothing rebuilt. The road starts again from that language's decks."""
        self.language = language
        self._road = None
        settings = self._settings()
        for view in self.rows.values():
            if self._show_value(view, settings):
                self.paints[view.row.id] += 1
        self._refresh_visibility(anchor=self._last)
        self.refresh()
        self.language_set.emit(language)

    # --- what shows ------------------------------------------------------------------------------------------------ #
    def _matches(self, settings, ctx):
        if not self._query.strip():
            return None
        return set(catalog.find(self._query, settings, self.language, ctx))

    def _row_shows(self, row, settings, ctx, matches):
        return self._visible(row, settings, ctx) and (matches is None or row.id in matches)

    def _visible(self, row, settings, ctx):
        """The catalog's `when`, and for a door row at least one of its doors there (registered in `windows.OPENERS`
        and available): a door row with no door never shows as a bare label (RUNBOOK 🧭 2)."""
        if not catalog.visible(row, settings, self.language, ctx):
            return False
        if row.kind != "door":
            return True
        openers = {op.name: op for op in windows.OPENERS}
        return any(name in openers and windows.available(openers[name], settings, self.language) for name in row.door)

    def _section_shows(self, section_id, settings, ctx):
        return any(self._visible(row, settings, ctx) for row in catalog.rows(section_id))

    def _refresh_visibility(self, anchor=None, fallback=True):
        """Every row's `when` (and the search) asked again; only what changed is shown or hidden; the anchor keeps its
        place in the viewport."""
        settings, ctx = self._settings(), self._ctx()
        matches = self._matches(settings, ctx)
        with self._keeping(anchor, fallback=fallback):
            for section in catalog.SECTIONS:
                self._show_section(section.id, settings, ctx, matches)
            self._show_nothing(matches)
        self._light_nav()

    def _show_section(self, section_id, settings, ctx, matches):
        nav = self.nav[section_id]
        nav_shows = self._section_shows(section_id, settings, ctx)
        if nav.isHidden() == nav_shows:
            nav.setVisible(nav_shows)
        slab = self.slabs.get(section_id)
        if slab is None:
            return
        any_main = adv_count = 0
        groups = {False: [], True: []}                       # per container: [group label, any row under it shown]
        shown = {row.id: self._row_shows(row, settings, ctx, matches) for row in catalog.rows(section_id)
                 if row.id in self.rows}
        if not any(shown.values()) and not slab.isHidden():
            slab.setVisible(False)                           # hidden first: its rows then change unseen (S3)
        for row in catalog.rows(section_id):
            view = self.rows.get(row.id)
            if view is None:
                continue
            shows = shown[row.id]
            _show(view, shows)
            if row.adv:
                adv_count += shows
            else:
                any_main += shows
            if view.group is not None:
                groups[row.adv].append([view.group, False])
            if shows and groups[row.adv]:
                groups[row.adv][-1][1] = True
        for group, shows in groups[False] + groups[True]:
            shows = shows and matches is None                # group names hidden while searching
            _show(group, shows)
        opened = adv_count > 0 and (section_id in self._open or matches is not None)
        if slab.adv.isHidden() == opened:
            slab.adv.setVisible(opened)
        if slab.more_row.isHidden() == (adv_count > 0):
            slab.more_row.setVisible(adv_count > 0)
        slab.set_open(opened, adv_count)
        slab_shows = bool(any_main or adv_count)
        if slab.isHidden() == slab_shows:
            slab.setVisible(slab_shows)
        self._tint()

    def _tint(self):
        """Every other shown section tinted (the mock's `nth-of-type(even)`), counted over the slabs shown."""
        n = 0
        for section in catalog.SECTIONS:
            slab = self.slabs.get(section.id)
            if slab is None or slab.isHidden():
                continue
            tint = "true" if n % 2 else "false"
            n += 1
            if slab.property("tint") != tint:
                slab.setProperty("tint", tint)
                slab.style().unpolish(slab)
                slab.style().polish(slab)
                slab.update()

    def _show_nothing(self, matches):
        none = matches is not None and not matches
        if none:
            self.nothing.setText(S.SEARCH_NONE.format(q=self._query.strip()))
        if self.nothing.isHidden() == none:
            self.nothing.setVisible(none)

    def fold(self, section_id):
        """*More options* / *Fewer options*: the section's other rows open or close in place (below the button)."""
        if section_id in self._open:
            self._open.discard(section_id)
        else:
            self._open.add(section_id)
        self._refresh_visibility(anchor=self.slabs[section_id].more)

    def folds(self):
        """The sections whose More options the user opened."""
        return set(self._open)

    # --- search ---------------------------------------------------------------------------------------------------- #
    def _searched(self, text):
        """A keystroke: rows hidden and shown, nothing rebuilt. With the search in view nothing above it can move, so
        the layout is left to the loop's own turn (no settle on the keystroke: S3)."""
        self._query = text
        self._refresh_visibility(anchor=None if self._in_view(self.search) else self.search,
                                 fallback=not self._in_view(self.search))

    def focus_search(self):
        """`/`: the search, brought into view (it stands first) and focused."""
        self._let_go()
        self.scroll.ensureWidgetVisible(self.search)
        self.search.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.edit.selectAll()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Slash and not isinstance(QApplication.focusWidget(), QLineEdit):
            self.focus_search()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- the nav, scrolling and the reveal ------------------------------------------------------------------------- #
    def _y_in_body(self, widget):
        return widget.mapTo(self.body, QPoint(0, 0)).y()

    def _light_nav(self, *_args):
        """The section in view lit: the last shown slab whose top is above the viewport's top third."""
        bar = self.scroll.verticalScrollBar()
        line = bar.value() + self.scroll.viewport().height() / 3
        lit = None
        for section in catalog.SECTIONS:
            slab = self.slabs.get(section.id)
            if slab is None or slab.isHidden():
                continue
            if lit is None or self._y_in_body(slab) <= line:
                lit = section.id
        for section_id, b in self.nav.items():       # one lit, by hand: a QButtonGroup takes Tab from all but one
            if b.isChecked() != (section_id == lit):
                b.setChecked(section_id == lit)

    def go_to(self, section_id):
        """The nav's click: the page glides so the section's slab stands at the top (reduced motion: a jump)."""
        self._let_go()
        self._light_nav()                     # a click toggled its button: the lit one is the section in view until the glide
        self._finish_build_of(section_id)
        slab = self.slabs.get(section_id)
        if slab is None or slab.isHidden():
            return
        self._settle()
        self._glide(slab, lambda: self._y_in_body(slab) - _px(theme.SPACING["settings-search-gap"]))

    def _finish_build_of(self, section_id):
        """A section wanted now (the nav, a reveal): its rows built at once if a slice hasn't yet."""
        if self._section_built(section_id):
            return
        self._prioritise(section_id)
        settings = self._settings()
        with self._keeping(self._anchor_for_build()):
            while self._queue and self._queue[0][1].section == section_id:
                index, row = self._queue.pop(0)
                self._build_guarded(index, row, settings)
            ctx = self._ctx()
            self._show_section(section_id, settings, ctx, self._matches(settings, ctx))

    def _glide(self, owner, target_y):
        """Scroll on the motion clock to `target_y()` (asked each frame: a slab built above meanwhile is counted)."""
        bar = self.scroll.verticalScrollBar()
        if self._scroll_anim is not None and self._scroll_anim.alive:
            self._scroll_anim.stop()
        start = bar.value()

        def frame(v):
            if _alive(owner):
                end = max(0, min(bar.maximum(), round(target_y())))
                self._scroll_to(round(start + (end - start) * v))
        self._scroll_anim = motion.clock().animate(theme.SETTINGS_MOTION["page-scroll"], frame, kind="move", owner=self)

    def reveal(self, target):
        """Bring a setting into view (W3.1a's three clicks; P7's `open_setting`): `target` a row id, a key, a section id
        or `known` / `mine_line` / `soon_line`. Its *More options* opened if needed, glided to the top third, washed
        once. -> False when the target names nothing."""
        located = catalog.locate(target)
        if located is None:
            return False
        section_id, row_id = located
        settings, ctx = self._settings(), self._ctx()
        if row_id is not None and (not self._visible(catalog.ROW[row_id], settings, ctx)
                                   or (row_id in FALLBACK and not self.slots[row_id].layout().count())):
            fallback = FALLBACK.get(row_id, section_id)
            section_id, row_id = catalog.locate(fallback)
            if row_id is not None and not self._visible(catalog.ROW[row_id], settings, ctx):
                row_id = None
        if not self._section_built(section_id):
            self._reveal_wanted = row_id or section_id
            self._prioritise(section_id)
            return True
        if self._query:
            self.search.edit.clear()                  # a reveal shows the row: the search would hide it
        row = catalog.ROW.get(row_id) if row_id else None
        if row is not None and row.adv and section_id not in self._open:
            self._open.add(section_id)
            self._refresh_visibility(anchor=self.slabs[section_id].more)
        self._settle()
        slab = self.slabs.get(section_id)
        view = self.rows.get(row_id) if row_id else self._first_shown_row(section_id)
        widget = view if view is not None else slab
        if widget is None or widget.isHidden():
            return False
        self._glide(widget, lambda: self._y_in_body(widget) - self.scroll.viewport().height() / 3)
        if not self.built:
            self._revealed = widget
        if view is not None:
            self._wash(view)
        return True

    def _first_shown_row(self, section_id):
        for row in catalog.rows(section_id):
            view = self.rows.get(row.id)
            if view is not None and not view.isHidden():
                return view
        return None

    def _wash(self, view):
        """The revealed row washed once: the wash fades over 1.6 s on the clock; reduced motion, steady for 1 s."""
        self._end_wash()
        self._washed = view
        view.set_wash(1.0)
        if motion.clock().mode.reduced:
            self._wash_timer = QTimer(self)
            self._wash_timer.setSingleShot(True)
            self._wash_timer.timeout.connect(self._end_wash)
            self._wash_timer.start(theme.SETTINGS_MOTION["row-wash-steady"])
            return
        self._wash_anim = motion.clock().animate(theme.SETTINGS_MOTION["row-wash"],
                                                 lambda v: _alive(view) and view.set_wash(1.0 - v),
                                                 self._end_wash, kind="fade", points="linear", owner=view,
                                                 on_end=self._end_wash)

    def _end_wash(self):
        view, self._washed = self._washed, None
        if self._wash_timer is not None:
            self._wash_timer.stop()
            self._wash_timer = None
        anim, self._wash_anim = self._wash_anim, None
        if anim is not None and anim.alive:
            anim.stop()
        if view is not None and _alive(view):
            view.set_wash(0.0)

    # --- a choice never moves the page ----------------------------------------------------------------------------- #
    def _settle(self):
        """The layouts done now, in this turn (before a paint): the rows shown or hidden, the slabs, the body and the
        scroll bar's range."""
        for _ in range(4):
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)

    def _in_view(self, widget):
        if widget is None or not _alive(widget) or not widget.isVisible() or not self.scroll.isAncestorOf(widget):
            return False
        vp = self.scroll.viewport()
        top = widget.mapTo(vp, QPoint(0, 0)).y()
        return top + widget.height() > 0 and top < vp.height()

    def _top_widget(self):
        """The first row (else slab) in view: what a relayout keeps in place when no control asked."""
        vp = self.scroll.viewport()
        for section in catalog.SECTIONS:
            slab = self.slabs.get(section.id)
            if slab is None or slab.isHidden():
                continue
            top = slab.mapTo(vp, QPoint(0, 0)).y()
            if top + slab.height() <= 0:
                continue
            for row in catalog.rows(section.id):
                view = self.rows.get(row.id)
                if view is not None and view.isVisible() and view.mapTo(vp, QPoint(0, 0)).y() + view.height() > 0:
                    return view
            return slab
        return None

    @contextmanager
    def hold(self, widget=None):
        """`with page.hold(widget): …` — a row's own late change (a worker's answer shown, a line filled, a part shown
        or hidden) keeps the reader's place: `widget`'s top keeps its y in the viewport when it is in view, else the
        first row in view does (a row above the reader growing never slides the page). Settled and corrected in the
        same turn, before a paint. Safe to nest; a dead page or widget holds nothing."""
        if not _alive(self):
            yield
            return
        with self._keeping(widget if _alive(widget) else None, stable=True):
            yield

    @contextmanager
    def _keeping(self, anchor=None, fallback=True, stable=False):
        """Whatever runs inside shows or hides rows; `anchor` (else, with `fallback`, the first row in view) keeps its y
        in the viewport: the layout settled and the scroll bar corrected in the same turn. `stable` (`hold`): settled
        again until the anchor stops moving (a help line re-wrapped after the first pass: FX-connect), at most
        `SETTLE_MORE` more passes."""
        if not self._in_view(anchor):
            anchor = self._top_widget() if fallback else None
        vp, bar = self.scroll.viewport(), self.scroll.verticalScrollBar()
        y0 = anchor.mapTo(vp, QPoint(0, 0)).y() if anchor is not None else None
        try:
            yield
        finally:
            if y0 is not None:                # nothing in view to keep: the loop lays out in its own turn
                self._settle()
                if stable and _alive(anchor):
                    y = anchor.mapTo(vp, QPoint(0, 0)).y()
                    for _ in range(SETTLE_MORE):
                        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
                        y, last = anchor.mapTo(vp, QPoint(0, 0)).y(), y
                        if y == last:
                            break
            if y0 is not None and _alive(anchor) and anchor.isVisible():
                dy = anchor.mapTo(vp, QPoint(0, 0)).y() - y0
                if dy:
                    self._scroll_to(bar.value() + dy)


_WARMED = []                          # [True] once `_warm` has run in this process (or failed: then a slice imports)
WARM_WAIT_MS = 2                      # a slice whose row needs a module still importing waits this long, then asks again


def _WARM_ROWS(row):
    """Whether building `row` imports what `_warm` imports (the level's bands, the video folders): built only once the
    worker has imported them — a slice meeting that import mid-way waited on Python's import lock (89.6 ms, IK S5)."""
    return row.kind == "slider" or row.id == "connect_video_folders"


def _warmed(_value=None):
    if not _WARMED:
        _WARMED.append(True)


def _warm_failed(info):
    applog.log("settings", f"warming: {info[1]}")
    _warmed()


def _warm():
    """(A worker.) The modules a row's value reads the first time, imported here so no slice waits for them."""
    from app import word_selection  # noqa: F401
    from app.connect import videos  # noqa: F401
    catalog.defaults()


def _look_for(wanted):
    """(A worker.) -> (the catalog's ctx: the modules found + "koe_revealed"; the doors' modules {name: found})."""
    found = set(catalog.installed_modules())
    if "modules.koe" in found:
        try:
            import importlib
            if importlib.import_module("modules.koe").is_revealed():
                found.add("koe_revealed")
        except Exception as e:                                   # the gate unread: Speech stays hidden
            applog.log("settings", f"the Speech gate: {e}")
    return found, windows._look_for(wanted)


def _live(text):
    """A label or help line with a live word in it: the version filled in; a word only its owner knows (the deck)
    leaves the line empty until that owner sets it (`RowView.set_words`)."""
    if "{version}" in text:
        from app import __version__
        text = text.replace("{version}", __version__)
    return "" if "{" in text else text
