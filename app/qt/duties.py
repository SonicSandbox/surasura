"""The dashboard's duties in the window (W3.5 rows 2, 4, 5; the window's spec 05 §5.2, 03 — the update mark —, 06 E10):
**Generate** (in the level ▾'s pop since W3.1a, `frame.LevelPop`; its share is the header's hairline), the bottom
bar's update mark, the update sheet and Needs you's update cards. Each shows what its service's state says (`app/services/updates.py`, `generate.py`, `automation.py`), repaints
only when that changed (S19), and says what a click asks for through a signal: the window calls the service, on a worker.

Every look here is the shell's own widgets and the theme's tokens (Sonic is redesigning the theme, 2026-10-11): a
QPushButton (`kind=chip`, `kind=primary`, `size=sm`), the stylesheet's QProgressBar, labels named for the stylesheet,
a `motion.Overlay` with its `sheet` shadow. Nothing decides here: the states and their numbers are the services'.
"""
import os

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app import theme
from app.qt import motion, shadow, strings, style, toast
from app.qt import press as qpress
from app.services import generate as gen
from app.services import standing
from app.services import updates as upd


def _set_prop(widget, name, value):
    """A stylesheet property changed: set and repolished (only when it changed)."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


# --- the header: Generate --------------------------------------------------------------------------------------- #
def generate_look(state):
    """(text, tooltip, look, enabled, percent) of the Generate button for the controller's State (E10: `failed` reads
    as such; a click cancels only before *Writing your list* — on an automatic run it is the user's own run, IK-20)."""
    s = state.state
    if s == gen.CURRENT:
        return strings.GENERATE_CURRENT, strings.GENERATE_CURRENT_TIP, "current", True, None
    if s == gen.STALE:
        return strings.GENERATE, strings.GENERATE_STALE_TIP, "stale", True, None
    if s == gen.QUEUED:
        line = state.message or strings.GENERATE_WAITING
        if state.quiet:
            return strings.GENERATE_QUEUED, strings.GENERATE_AUTO_TIP.format(step=line), "busy", True, None
        return strings.GENERATE_QUEUED, strings.GENERATE_QUEUED_TIP.format(line=line), "busy", True, None
    if s == gen.RUNNING:
        pct = gen.percent(state)
        text = strings.GENERATE_RUNNING.format(pct=pct) if pct is not None else strings.GENERATE_RUNNING_NO_PCT
        step = state.step or strings.GENERATE_WAITING
        if state.quiet:
            return text, strings.GENERATE_AUTO_TIP.format(step=step), "busy", True, pct or 0
        if gen.can_cancel(state):
            return text, strings.GENERATE_RUNNING_TIP.format(step=step), "busy", True, pct or 0
        return text, strings.GENERATE_WRITING_TIP.format(step=step), "busy", False, pct or 0
    if s == gen.CANCELLING:
        return strings.GENERATE_STOPPING, state.message or strings.GENERATE_STOPPING, "busy", False, None
    if s == gen.FAILED:
        return (strings.GENERATE_FAILED, strings.GENERATE_FAILED_TIP.format(message=state.message or ""), "failed",
                True, None)
    return strings.GENERATE, strings.GENERATE_TIP, "idle", True, None


class GenerateControl(QWidget):
    """Generate and, after a failure, *Open the log* (W3.1a: quiet, in the level ▾'s pop; its share while it runs is
    the header's hairline, `frame.Progress`). `pressed`: the button was clicked (the window runs or cancels, as the
    state allows); `log_asked`: *Open the log*."""
    pressed = pyqtSignal()
    log_asked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = self.row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton(strings.GENERATE, self)
        self.button.setObjectName("generate")
        self.button.setProperty("look", "idle")
        self.button.setToolTip(strings.GENERATE_TIP)
        self.button.setAccessibleName(strings.GENERATE)
        self.button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.pressed)
        qpress.room(self.button)                           # round 8 row 45: its arc turns from the click (the shell's
        row.addWidget(self.button)                         # ... `_generate_pressed`), in room kept at rest
        self.log_button = QPushButton(strings.GENERATE_LOG, self)
        self.log_button.setProperty("kind", "chip")
        self.log_button.setToolTip(strings.GENERATE_LOG_TIP)
        self.log_button.setAccessibleName(strings.GENERATE_LOG)
        self.log_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.log_button.clicked.connect(self.log_asked)
        qpress.room(self.log_button)
        self.log_button.setVisible(False)
        row.addWidget(self.log_button)
        row.addStretch(1)
        self.percent = None                                # the share shown now (the header's hairline draws it)
        self._shown = None
        self._held = None                                  # the window is closing: off, with this tooltip
        self.paints = 0                                    # how many times a new state was painted (tests: S19)

    def hold(self, tip):
        """The window is closing (it waits for what can't stop part-way): a click would start nothing, so the button is
        off, with `tip` — whatever state comes next."""
        self._held = tip
        self.button.setEnabled(False)
        self.button.setToolTip(tip)

    def show_state(self, state):
        """-> True when something on it changed (and was repainted)."""
        text, tip, look, enabled, pct = generate_look(state)
        if self._held is not None:
            tip, enabled = self._held, False
        failed_log = state.state == gen.FAILED and bool(state.log_path)
        shown = (text, tip, look, enabled, pct, failed_log)
        if shown == self._shown:
            return False
        self._shown = shown
        self.paints += 1
        b = self.button
        if b.text() != text:
            b.setText(text)
            b.setAccessibleName(text)
        b.setToolTip(tip)
        b.setEnabled(enabled)
        _set_prop(b, "look", look)
        self.percent = pct
        self.log_button.setVisible(failed_log)
        return True


# --- the bottom bar's update mark ---------------------------------------------------------------------------------- #
def update_mark_look(state):
    """(text, tooltip) of the bar's update mark, or None while it has nothing to say (none, failed: its failure is the
    bar's failure line and a Needs you card)."""
    version = state.version or ""
    if state.state == upd.AVAILABLE:
        return strings.UPDATE_READY, strings.UPDATE_MARK_TIP.format(version=version)
    if state.state == upd.DOWNLOADING:
        pct = upd.percent(state)
        text = strings.UPDATE_DOWNLOADING.format(pct=pct) if pct is not None else strings.UPDATE_DOWNLOADING_NO_PCT
        return text, strings.UPDATE_MARK_DOWNLOADING_TIP.format(version=version)
    if state.state == upd.WAITING:
        return strings.UPDATE_RESTART, strings.UPDATE_MARK_WAIT_TIP.format(version=version)
    if state.state == upd.READY:
        return strings.UPDATE_HANDING, strings.UPDATE_MARK_HANDING_TIP
    return None


def update_mark_key(state):
    """The update chip's standing key (round 8 row 54: its ✕ hides it for this session until its version or state
    changes — *Later* for this run; *Skip this version* is the lasting answer), or None while it has nothing to say."""
    return standing.update_key(state.version, state.state) if update_mark_look(state) is not None else None


# --- the update sheet ---------------------------------------------------------------------------------------------- #
class UpdateSheet(motion.Overlay):
    """The update, over the window's bottom edge (an overlay: Esc, Back and the router close it). Offered: the version,
    what it is, *What's new ↗*, *Update now* (or *Download* for a manual release) · *Skip this version* · *Later*.
    Downloading: its progress and *Cancel*. Waiting: each program still running with *Stop it* where it can be stopped,
    *Stop all and update now*, *Cancel*. `action(name, key)`: a click; `dismissed`: closed by Esc / Back / *Later*
    (the window cancels an update under way: IK-2)."""
    how = "up"
    shadow_name = "sheet"
    action = pyqtSignal(str, object)
    dismissed = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("updatesheet")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        box.setContentsMargins(*(round(v * f) for v in toast.PAD))
        box.setSpacing(round(toast.PAD[1] * f))
        self.title = QLabel(self)
        self.title.setObjectName("sheetheading")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.title)
        self.body = QLabel(self)
        self.body.setObjectName("sheetline")
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        box.addWidget(self.body)
        self.message = QLabel(self)
        self.message.setObjectName("sheetline")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        box.addWidget(self.message)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(strings.UPDATE_PROGRESS_NAME)
        box.addWidget(self.progress)
        self.programs_box = QVBoxLayout()
        self.programs_box.setSpacing(round(toast.PAD[1] * f / 2))
        box.addLayout(self.programs_box)
        self.program_rows = []
        buttons = QHBoxLayout()
        buttons.setSpacing(round(toast.PAD[1] * f))
        self.buttons = {}
        for name, label, tip, kind in (
                ("notes", strings.UPDATE_NOTES, strings.UPDATE_NOTES_TIP, None),
                ("start", strings.UPDATE_NOW, strings.UPDATE_NOW_TIP, "primary"),
                ("download", strings.UPDATE_DOWNLOAD, strings.UPDATE_DOWNLOAD_TIP, "primary"),
                ("stop-all", strings.UPDATE_STOP_ALL, strings.UPDATE_STOP_ALL_TIP, "primary"),
                ("skip", strings.UPDATE_SKIP, strings.UPDATE_SKIP_TIP, None),
                ("cancel", strings.UPDATE_CANCEL, strings.UPDATE_CANCEL_TIP, None),
                ("later", strings.UPDATE_LATER, strings.UPDATE_LATER_TIP, None)):
            b = QPushButton(label, self)
            if kind:
                b.setProperty("kind", kind)
            b.setProperty("action", name)                  # round 8 row 45: the shell finds the button it turns
            if name in ("notes", "start", "download", "stop-all"):
                qpress.room(b)
            b.setToolTip(tip)
            b.setAccessibleName(label)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            if name == "later":
                b.clicked.connect(self.close)
            else:
                b.clicked.connect(lambda _c=False, n=name: self.action.emit(n, None))
            if name == "notes":
                buttons.addWidget(b)
                buttons.addStretch(1)
            else:
                buttons.addWidget(b)
            self.buttons[name] = b
        box.addLayout(buttons)
        self.state = None
        self._programs = None
        self._held = False
        self.paints = 0
        self.shadow = shadow.Follower(self, self.shadow_name)
        parent.installEventFilter(self)
        self.hide()

    # --- what it shows ----------------------------------------------------------------------------------------- #
    def show_state(self, state):
        """Paint `state` (the update service's). -> True when anything changed."""
        old, self.state = self.state, state
        if old is not None and (old.state, old.version, old.cls, old.body, old.critical, old.done, old.total,
                                old.programs, old.message) == (state.state, state.version, state.cls, state.body,
                                                               state.critical, state.done, state.total,
                                                               state.programs, state.message):
            return False
        self.paints += 1
        s = state.state
        offered = s == upd.AVAILABLE
        manual = state.cls not in ("APP", "INSTALLER")
        title = (strings.UPDATE_SHEET_CRITICAL if state.critical else strings.UPDATE_SHEET_TITLE).format(
            version=state.version or "")
        self.title.setText(title)
        self.setAccessibleName(title)
        if offered:
            body = state.body
        elif s == upd.DOWNLOADING:
            pct = upd.percent(state)
            body = (strings.UPDATE_DOWNLOADING_LINE.format(pct=pct) if pct is not None
                    else strings.UPDATE_DOWNLOADING_LINE_NO_PCT)
        elif s == upd.WAITING:
            body = strings.UPDATE_WAITING_LINE if state.programs else strings.UPDATE_INSTALLING_LINE
        elif s == upd.READY:
            body = strings.UPDATE_INSTALLING_LINE
        else:
            body = state.message or ""
        self.body.setText(body)
        message = state.message if (state.message and s != upd.FAILED) else ""
        self.message.setText(message)
        self.message.setVisible(bool(message))
        pct = upd.percent(state)
        self.progress.setVisible(s == upd.DOWNLOADING)
        self.progress.setRange(0, 100 if pct is not None else 0)       # no size known: Qt's busy bar
        if pct is not None:
            self.progress.setValue(pct)
        self._show_programs(state.programs if s in (upd.DOWNLOADING, upd.WAITING) else ())
        stoppable = any(p.can_stop for p in state.programs) if s == upd.WAITING else False
        visible = {"notes": offered and bool(state.notes_url), "start": offered and not manual,
                   "download": offered and manual, "skip": offered, "later": offered,
                   "stop-all": stoppable, "cancel": s in (upd.DOWNLOADING, upd.WAITING)}
        for name, b in self.buttons.items():
            b.setVisible(visible[name])
        if self.isVisible():
            self.place()
        return True

    def _show_programs(self, programs):
        programs = tuple(programs)
        if programs == self._programs:
            return                                          # the wait list repaints only when it changed (S19)
        self._programs = programs
        for row in self.program_rows:
            row.setParent(None)
            row.deleteLater()
        self.program_rows = []
        f = theme.text_factor(style.current()[1])
        for program in programs:
            row = QWidget(self)
            row.setEnabled(not self._held)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(round(toast.PAD[1] * f))
            name = QLabel(program.name or "", row)
            name.setObjectName("sheetline")
            name.setTextFormat(Qt.TextFormat.PlainText)
            line.addWidget(name, 1)
            if program.can_stop:
                b = QPushButton(strings.UPDATE_STOP, row)
                b.setProperty("size", "sm")
                b.setProperty("action", "stop")
                b.setProperty("program", program.key)
                qpress.room(b)
                b.setToolTip(strings.UPDATE_STOP_TIP.format(name=program.name or ""))
                b.setAccessibleName(strings.UPDATE_STOP_NAME.format(name=program.name or ""))
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                b.clicked.connect(lambda _c=False, k=program.key: self.action.emit("stop", k))
                line.addWidget(b)
            self.programs_box.addWidget(row)
            self.program_rows.append(row)

    # --- its place --------------------------------------------------------------------------------------------- #
    def place(self):
        """Centred over the window's bottom edge, as wide as a dialog (`dialog`), at most the toast's share."""
        p = self.parentWidget()
        self.ensurePolished()
        width = min(round(theme.size("dialog", style.current()[1])), int(p.width() * toast.WIDTH_SHARE))
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        footer = p.findChild(QWidget, "footer")
        bottom = footer.mapTo(p, footer.rect().topLeft()).y() if footer is not None else p.height()
        self.setGeometry((p.width() - width) // 2, max(0, bottom - height), width, height)

    def open(self):
        self.place()
        return super().open()

    def hold(self, tip):
        """The window is closing: *Update now* would start nothing, so every action is off, with `tip`."""
        for b in self.buttons.values():
            b.setEnabled(False)
            b.setToolTip(tip)
        for row in self.program_rows:
            row.setEnabled(False)
        self._held = True

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def closeEvent(self, event):
        super().closeEvent(event)
        self.dismissed.emit()

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["sheet"])     # an overlay: slate navy, no sides (brief §4)
        p.end()


# --- Needs you: the update's cards ------------------------------------------------------------------------------- #
class UpdateCards(QWidget):
    """Needs you's update entries: *Install the update* while one is on offer, and each update failure (P1.2-1: looked
    at, it stops counting and stays listed) with *Skip this version* and *Open the logs folder*. `action(name, key)`."""
    action = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updatecards")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(theme.SPACING["settings-card-gap"])
        self.cards = []
        self._key = None
        self.logs = False                       # whether *Open the logs folder* has a folder to open
        self._held = None                       # the window is closing: *Update now* off, with this tooltip
        self.setVisible(False)

    def hold(self, tip):
        """The window is closing: *Update now* would start nothing, so it is off, with `tip`."""
        self._held = tip
        for b in self.findChildren(QPushButton):
            if b.property("action") == "start":
                b.setEnabled(False)
                b.setToolTip(tip)

    def counts(self):
        """(listed, unseen): what the Needs you tab counts for these cards (the offer is listed, never counted)."""
        if self._key is None:
            return 0, 0
        offer, failures, _logs = self._key
        return (1 if offer else 0) + len(failures), sum(1 for f in failures if not f[2])

    def show_state(self, state, logs=False):
        """-> True when the cards changed (rebuilt only then: S19)."""
        offer = (state.version, state.cls, state.state == upd.AVAILABLE and state.cls in ("APP", "INSTALLER")) \
            if state.state == upd.AVAILABLE else None
        failures = tuple((f.text, f.version, f.seen, f.report) for f in state.needs_you)
        key = (offer, failures, bool(logs))
        if key == self._key:
            return False
        self._key = key
        self.logs = bool(logs)
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        if offer is not None:
            version, _cls, in_app = offer
            self._card(strings.NEEDS_UPDATE_TITLE, strings.NEEDS_UPDATE_LINE.format(version=version or ""),
                       [("start" if in_app else "download", strings.UPDATE_NOW if in_app else strings.UPDATE_DOWNLOAD,
                         strings.UPDATE_NOW_TIP if in_app else strings.UPDATE_DOWNLOAD_TIP, None),
                        ("skip", strings.UPDATE_SKIP, strings.UPDATE_SKIP_TIP, version)])
        for text, version, _seen, report in failures:
            actions = []
            if version:
                actions.append(("skip", strings.UPDATE_SKIP, strings.UPDATE_SKIP_TIP, version))
            folder = os.path.dirname(report) if report else ""     # its report is beside the install, not in the logs
            if logs or folder:
                actions.append(("logs", strings.BAR_LOGS, strings.BAR_LOGS_TIP, folder or None))
            self._card(strings.NEEDS_UPDATE_FAILED_TITLE, text, actions)
        self.setVisible(bool(self.cards))
        return True

    def _card(self, title, line, actions):
        card = style.styled(QWidget(self), "needscard")
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(card)
        box.setContentsMargins(*(round(v * f) for v in toast.PAD))
        heading = QLabel(title, card)
        heading.setObjectName("needstitle")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(heading)
        text = QLabel(line, card)
        text.setObjectName("sheetline")
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box.addWidget(text)
        row = QHBoxLayout()
        for name, label, tip, key in actions:
            b = QPushButton(label, card)
            b.setProperty("size", "sm")
            b.setProperty("action", name)
            if name in ("start", "download", "logs"):
                qpress.room(b)                             # round 8 row 45: its arc turns from the click
            if name == "start" and self._held is not None:
                tip = self._held
                b.setEnabled(False)
            b.setToolTip(tip)
            b.setAccessibleName(label)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(lambda _c=False, n=name, k=key: self.action.emit(n, k))
            row.addWidget(b)
        row.addStretch(1)
        box.addLayout(row)
        self.box.addWidget(card)
        self.cards.append(card)
