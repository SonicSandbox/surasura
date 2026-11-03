"""Report a problem, in the window (alpha 3 on; `app/report.py` holds the list and the zip; the scope
`tracks/ship/work/report/scope.md`).

- **The bug** (`BugButton`): the header's rightmost control, a small bug painted in the header's own line (1.5 px,
  ink-dim at rest, ink under the hand or with focus, the focus ring `_Gear`'s), crisp at any scale (painted, never a
  picture). The saved reports' count sits beside it as Finished's tab count does (ink-faint figures, nothing at 0).
  Its tooltip: *Report a problem*, and the count when there is one.
- **The press** (`open_report`): the picture is taken first — `QWidget.grab()` of each visible Surasura window, the
  main window first, never the screen and never another program — then the window opens (or is raised: the picture
  taken again).
- **The window** (`ReportWindow`, a `windows.SecondaryWindow`: Esc closes it): *What happened?*, *What did you
  expect?*, the picture(s) with *Leave the picture out*, *Save to my list*; the list (each report: *Open*, *Remove*,
  Undo on the status line; an opened one shows its words, pictures and notes, and takes a note); *Show me what's in
  it*, *Include my last lists*.
- **Send report** (3.0, alpha 10; `tracks/ship/work/send-report/SPEC.md` §3, SR-Q1…Q3 at their leans, PROVISIONAL):
  the main button, *No personal data or identification is included* under it, always; an optional Discord name
  (remembered on this PC; a second line says it goes once typed). The press saves what's typed, builds the scrubbed
  zip into the outbox (`app/send_report.py`) and shows **What goes** — every file and its size, the placeholders, the
  pictures at full width, the name or none, the sender code, how long it's kept — with *Send*, *Open the zip*,
  *Back*. Sent: "Sent. Your report is #ID", *Copy* and the invite (`settings_strings.DISCORD_URL`, a link opened in
  the browser). Not sent: the zip waits (*Send now* · *Don't send*), never sent again by itself (Q4). The sender code
  shows with *New code*; *Sent reports* lists this PC's copies. *Make a zip instead* (the Discord / GitHub path by
  hand) writes the scrubbed zip into Downloads or a folder picked and shows it selected in its folder; its done line
  offers the invite, *GitHub Issues works too* the quieter way.
  Every read and write of the list, its pictures, the zips and the send runs on a worker. What the tester typed and
  didn't save is kept while Surasura runs (`DRAFT`): Esc never loses it.
- **Picture mode** (`PictureMode`, SR-2): while a window's picture is taken every name and path it shows is drawn
  scrubbed (`app/scrub.py`), and put back after; a picture taken before the scrub's Identity is ready is saved
  unmarked and never sent.
"""
import os
import re
import threading
import zipfile

from PyQt6.QtCore import (QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSignalBlocker, QSize, QStandardPaths, Qt,
                          QTimer)
from PyQt6.QtGui import QFontMetrics, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QApplication,
                             QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QItemDelegate, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                             QStackedWidget, QStyledItemDelegate, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from app import report as core
from app import scrub, send_report
from app import theme
from app.qt import bridge, rows, screens, strings, style
from app.qt import settings_strings as SS
from app.qt import press as qpress
from app.qt import windows
from app.qt.windows import SecondaryWindow

NAME = "report"                 # `windows.show`'s kind: one report window per main window
DRAFT = "_report_draft"         # the main window's attribute holding an unsaved report (words, expected, tick)
THUMB = 168                     # a picture's width in the form (logical px)


# --- the bug ------------------------------------------------------------------------------------------------------ #
def bug_path(cx, cy, s):
    """The bug's lines for a box of side `s` centred on (cx, cy): the head's arc, two antennae, the body, its middle
    line and three legs a side. -> (body rect, [QPainterPath …]). Pure geometry: the paint and its test share it."""
    body = QRectF(cx - 0.17 * s, cy - 0.15 * s, 0.34 * s, 0.44 * s)
    paths = []
    head = QPainterPath()
    head.arcMoveTo(QRectF(cx - 0.1 * s, cy - 0.26 * s, 0.2 * s, 0.2 * s), 0)
    head.arcTo(QRectF(cx - 0.1 * s, cy - 0.26 * s, 0.2 * s, 0.2 * s), 0, 180)
    paths.append(head)
    for side in (-1, 1):
        a = QPainterPath(QPointF(cx + side * 0.05 * s, cy - 0.25 * s))
        a.lineTo(QPointF(cx + side * 0.12 * s, cy - 0.34 * s))
        paths.append(a)
        for k, y in enumerate((-0.03, 0.08, 0.19)):
            leg = QPainterPath(QPointF(cx + side * 0.16 * s, cy + y * s))
            drop = (-0.05, 0.0, 0.06)[k]
            leg.lineTo(QPointF(cx + side * 0.29 * s, cy + (y + drop) * s))
            paths.append(leg)
    mid = QPainterPath(QPointF(cx, cy - 0.08 * s))
    mid.lineTo(QPointF(cx, cy + 0.29 * s))
    paths.append(mid)
    return body, paths


PREPARE_AFTER_MS = 3000         # the scrub's Identity worked out this long after the first frame (or on the bug's hover)
_preparing = [None]             # the worker working it out, while it does


def prepare_identity():
    """(The window's thread.) Who "you" are (`scrub.prepare`), on one worker at a time: nothing when it is ready or
    being worked out."""
    t = _preparing[0]
    if scrub.ready() or (t is not None and t.is_alive()):
        return
    _preparing[0] = scrub.prepare()


def bug_tip(n):
    return strings.REPORT_TIP_COUNT.format(n=n) if n else strings.REPORT_TIP


class BugButton(QToolButton):
    """The header's *Report a problem*: the painted bug and the saved reports' count. A click opens the window."""

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setObjectName("reportbug")
        self.count = 0
        self.paints = 0
        self.setToolTip(bug_tip(0))
        self.setAccessibleName(strings.REPORT_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda _c=False: open_report(self.shell))
        self.counted = bridge.Relay(self)                         # the count, read on its own thread: never one of
        self.counted.said.connect(self.set_count)                 # ... the window's worker jobs, never a wait
        first = getattr(shell, "first_frame", None)
        if first is not None:                                     # the count read after the first frame, and who
            first.connect(self.refresh)                           # ... "you" are worked out on a worker a moment
            self.prepare_timer = QTimer(self)                     # ... after (the scrub's Identity: never beside
            self.prepare_timer.setSingleShot(True)                # ... the start's own work)
            self.prepare_timer.setInterval(PREPARE_AFTER_MS)
            self.prepare_timer.timeout.connect(prepare_identity)
            first.connect(self.prepare_timer.start)

    def refresh(self):
        relay = self.counted

        def read():
            try:
                relay.call(core.count())
            except Exception:                                     # a folder that can't be read: the count stays
                pass
        threading.Thread(target=read, name="report-count", daemon=True).start()

    def set_count(self, n):
        """-> True when the count changed (repainted only then)."""
        if n is None:
            return False
        n = max(0, int(n or 0))
        if n == self.count:
            return False
        self.count = n
        self.setToolTip(bug_tip(n))
        self.updateGeometry()
        self.paints += 1
        self.update()
        return True

    def _count_font(self):
        font = self.font()
        px, weight = theme.font("tab-count", style.current()[1])
        font.setPointSizeF(px * style.PT_PER_PX)
        font.setWeight(weight)
        return font

    def _side(self):
        return round(theme.SIZES["button"] * theme.text_factor(style.current()[1]))

    def sizeHint(self):
        side = self._side()
        if not self.count:
            return QSize(side, side)
        w = QFontMetrics(self._count_font()).horizontalAdvance(str(self.count))
        return QSize(side + w + round(4 * theme.text_factor(style.current()[1])), side)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lit = self.underMouse() or self.hasFocus() or self.isDown()
        ink = rows.c("ink" if lit else "ink-dim")
        side = self._side()
        cx, cy = side / 2, self.height() / 2
        pen = QPen(ink, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        body, paths = bug_path(cx, cy, side)
        p.drawEllipse(body)
        for path in paths:
            p.drawPath(path)
        if self.count:
            font = self._count_font()
            p.setFont(font)
            p.setPen(rows.c("ink" if lit else "ink-faint"))
            fm = QFontMetrics(font)
            p.drawText(QPointF(side + round(2 * theme.text_factor(style.current()[1])),
                               cy + fm.capHeight() / 2 - 0.12 * side), str(self.count))
        if self.hasFocus():
            p.setPen(QPen(rows.c("accent"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), theme.RADII["icon-button"],
                              theme.RADII["icon-button"])
        p.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        prepare_identity()                                        # (the hand on its way: ready by the press)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        prepare_identity()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


# --- the picture -------------------------------------------------------------------------------------------------- #
def surasura_windows(shell):
    """The windows a picture is taken of: the main window, then each visible window of Surasura's own (a ported
    window, a dialog) — never a menu, a tooltip, a pop or the report window itself."""
    out = [shell]
    kinds = (Qt.WindowType.Window, Qt.WindowType.Dialog)
    for w in QApplication.topLevelWidgets():
        if w is shell or isinstance(w, ReportWindow) or not w.isVisible() or w.isMinimized():
            continue
        if (w.windowFlags() & Qt.WindowType.WindowType_Mask) not in kinds:
            continue
        out.append(w)
    return out[:core.MAX_PICTURES]


_KEY_FIELD = re.compile(r"(key|token|secret|password|credential)", re.IGNORECASE)


def key_fields(window):
    """The text fields in `window` that hold a key or a token: a password field (shown or not — Jiten's *Show*), or
    one named for a key. Their letters are never drawn in a picture."""
    out = []
    for f in window.findChildren(QLineEdit):
        named = " ".join((f.accessibleName(), f.objectName(), f.placeholderText(), f.toolTip()))
        if f.echoMode() != QLineEdit.EchoMode.Normal or getattr(f, "_shown_secret", False) or _KEY_FIELD.search(named):
            out.append(f)
    return out


def take_pictures(shell):
    """Each Surasura window's own picture (`QWidget.grab()`: the window draws itself; nothing of the screen), every key
    field drawn as dots while it is taken (`key_fields`: a shown Jiten key never in a picture), in picture mode
    (`PictureMode`: every name and path drawn scrubbed). -> ([QImage] (the main window's first), scrubbed): `scrubbed`
    False when the scrub's Identity wasn't ready yet (`scrub.prepare`, at the main window's first frame) — such a
    picture is saved unmarked and Send report never sends it. Thread-safe images: encoded on the worker at Save."""
    out = []
    ident = scrub.kept()                                          # (never read here, never waited for)
    for w in surasura_windows(shell):
        try:
            fields = [(f, f.echoMode()) for f in key_fields(w)]
            for f, _mode in fields:
                f.setEchoMode(QLineEdit.EchoMode.Password)
            try:
                with PictureMode(w, ident):
                    img = w.grab().toImage()
            finally:
                for f, mode in fields:
                    f.setEchoMode(mode)
        except RuntimeError:                                       # a window deleted meanwhile
            continue
        if not img.isNull():
            out.append(img)
    return out, ident is not None


class _ShownItems(QStyledItemDelegate):
    """An item view's own delegate while its picture is taken: each item's words scrubbed (`initStyleOption`)."""

    def __init__(self, ident, parent):
        super().__init__(parent)
        self.ident = ident

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = self.ident.scrub(option.text)


class PictureMode:
    """While one window's picture is taken (SPEC §2.4; `grab()` paints at once, so it lasts only that): every name and
    path it shows drawn scrubbed, and everything put back after — even when the grab fails.

    - a label that shortens its text (a `shown_fit()` of its own: `ElidedLabel`, the bar's line, a source's *From …*, a
      toast) fits it again from its whole text, which it reads through `scrub.shown` — never half a name;
    - every other label's and button's words, swapped only where the scrub changes them, under a `QSignalBlocker`;
    - a text field, a text box and a drop-down are never touched: a stand-in showing the scrubbed words is laid over
      each one that holds a name (no signal, the cursor, the undo history and the document all as they were);
    - an item view drawn by Qt's own delegate gets `_ShownItems` for the moment; one with a delegate of its own reads
      its words through `scrub.shown` (`rows.Text.static`, the word lists' `_RemoveDelegate`), as every painted widget
      does (the audit test in `tests/qt/test_picture_mode.py`).
    `ident` None (the Identity not ready): nothing is changed. Only visible widgets are looked at. `scrub.shown`
    scrubs from `__enter__` to `__exit__`'s start (`scrub.picture_mode`): the shortened labels fit again after it."""

    EDITS = (QLineEdit, QPlainTextEdit, QTextEdit, QComboBox)

    def __init__(self, window, ident):
        self.window, self.ident = window, ident
        self.fitted, self.swapped, self.standins, self.views = [], [], [], []
        self.mode = None

    def __enter__(self):
        if self.ident is None:
            return self
        self.mode = scrub.picture_mode()
        self.mode.__enter__()
        try:
            self._swap()
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_exc):
        if self.mode is not None:
            mode, self.mode = self.mode, None
            mode.__exit__(None, None, None)
        self._restore()
        return False

    def _swap(self):
        scrub_text = self.ident.scrub
        for w in self.window.findChildren(QWidget):
            if not w.isVisible() or w.window() is not self.window:     # (another window: its own picture, or none)
                continue
            if callable(getattr(w, "shown_fit", None)):
                self.fitted.append(w)
                w.shown_fit()
            elif isinstance(w, self.EDITS):
                if isinstance(w, QLineEdit) and isinstance(w.parentWidget(), (QComboBox, QAbstractSpinBox)):
                    continue                                       # (a drop-down's stand-in covers it; a spin
                    #                                                  box's holds a number)
                stand = _stand_in(w, scrub_text)
                if stand is not None:
                    self.standins.append(stand)
            elif isinstance(w, (QLabel, QAbstractButton)):
                text = w.text()
                new = scrub_text(text) if text else text
                if new != text:
                    with QSignalBlocker(w):
                        w.setText(new)
                    self.swapped.append((w, text))
            elif isinstance(w, QAbstractItemView):
                d = w.itemDelegate()
                if type(d) in (QStyledItemDelegate, QItemDelegate):
                    self.views.append((w, d))
                    w.setItemDelegate(_ShownItems(self.ident, w))

    def _restore(self):
        for w, text in reversed(self.swapped):
            try:
                with QSignalBlocker(w):
                    w.setText(text)
            except RuntimeError:
                pass
        for stand in self.standins:
            try:
                stand.hide()
                stand.deleteLater()
            except RuntimeError:
                pass
        for view, d in self.views:
            try:
                shown = view.itemDelegate()
                view.setItemDelegate(d)
                shown.deleteLater()
            except RuntimeError:
                pass
        for w in self.fitted:                                      # (picture mode is off by now: the whole text)
            try:
                w.shown_fit()
            except RuntimeError:
                pass
        self.fitted, self.swapped, self.standins, self.views = [], [], [], []


def _stand_in(w, scrub_text):
    """A stand-in laid over the text field, text box or drop-down `w` for its picture, showing its words scrubbed —
    or None when they name no one. Never focused, never pressed; dropped after the grab."""
    if isinstance(w, QLineEdit):
        if w.echoMode() != QLineEdit.EchoMode.Normal:
            return None                                            # dots: nothing to read
        text, hint = w.text(), w.placeholderText()
        new, new_hint = scrub_text(text), scrub_text(hint)
        if (new, new_hint) == (text, hint):
            return None
        stand = QLineEdit(w.parentWidget())
        stand.setText(new)
        stand.setPlaceholderText(new_hint)
        stand.setAlignment(w.alignment())
        stand.setFrame(w.hasFrame())
        stand.setReadOnly(w.isReadOnly())
        stand.setTextMargins(w.textMargins())
        stand.setCursorPosition(min(w.cursorPosition(), len(new)))
    elif isinstance(w, QPlainTextEdit):
        text = w.toPlainText()
        new = scrub_text(text)
        if new == text:
            return None
        stand = QPlainTextEdit(w.parentWidget())
        stand.setPlainText(new)
        stand.setLineWrapMode(w.lineWrapMode())
        stand.setReadOnly(w.isReadOnly())
    elif isinstance(w, QTextEdit):
        text = w.toPlainText()                                     # (its words: never its markup's)
        new = scrub_text(text)
        if new == text:
            return None
        stand = QTextEdit(w.parentWidget())
        stand.setPlainText(new)
        stand.setLineWrapMode(w.lineWrapMode())
        stand.setReadOnly(w.isReadOnly())
    else:                                                          # a drop-down: the words it shows
        text = w.currentText()
        new = scrub_text(text)
        if new == text:
            return None
        stand = QComboBox(w.parentWidget())
        stand.setEditable(w.isEditable())
        stand.addItem(w.itemIcon(w.currentIndex()) if w.currentIndex() >= 0 else QIcon(), new)
        stand.setIconSize(w.iconSize())
    stand.setObjectName(w.objectName())
    for key in w.dynamicPropertyNames():
        name = bytes(key).decode("utf-8", "replace")
        stand.setProperty(name, w.property(name))
    stand.setStyleSheet(w.styleSheet())
    stand.setFont(w.font())
    stand.setEnabled(w.isEnabled())
    stand.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    stand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    stand.setGeometry(w.geometry())
    if isinstance(w, QAbstractScrollArea):                         # the same lines in view
        stand.setHorizontalScrollBarPolicy(w.horizontalScrollBarPolicy())
        stand.setVerticalScrollBarPolicy(w.verticalScrollBarPolicy())
    stand.show()
    stand.raise_()
    if isinstance(w, QAbstractScrollArea):
        stand.verticalScrollBar().setValue(w.verticalScrollBar().value())
        stand.horizontalScrollBar().setValue(w.horizontalScrollBar().value())
    return stand


def png_bytes(image):
    """(Any thread.) A QImage as PNG bytes."""
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(data)


def open_report(shell):
    """The bug's press: the pictures first, then the window (raised with the new pictures when open)."""
    pictures, scrubbed = take_pictures(shell)
    win = windows.opened(shell, NAME)
    if win is not None:
        win.set_pictures(pictures, scrubbed)
    return windows.show(shell, NAME, lambda s: ReportWindow(s, pictures, scrubbed))


def downloads():
    """The tester's Downloads folder (its real place, wherever Windows keeps it), else their home folder."""
    path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return os.path.normpath(path if path and os.path.isdir(path) else os.path.expanduser("~"))


class ElidedLabel(QLabel):
    """A list row's words on one line, cut with … to the room it has (its whole words in its tooltip)."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.full = text
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        """Cut to its room — the whole text scrubbed first while a picture is taken (`PictureMode`)."""
        shown = self.fontMetrics().elidedText(scrub.shown(self.full), Qt.TextElideMode.ElideRight, max(0, self.width()))
        if shown != self.text():
            self.setText(shown)

    shown_fit = _fit


# --- the window --------------------------------------------------------------------------------------------------- #
class ReportWindow(SecondaryWindow):
    FORM, OPENED, CONTENTS, GOES, SENT = 0, 1, 2, 3, 4

    def __init__(self, shell, pictures=(), scrubbed=False):
        super().__init__(shell, strings.REPORT_WINDOW_NAME)
        self.pictures = list(pictures)
        self.scrubbed = bool(scrubbed)                            # the pictures were taken in picture mode
        self.reports = None                                       # the list as last read (None: not read yet)
        self.opened_id = None
        self.list_paints = 0
        self.dest = downloads()
        self.last_removed = None
        self.sending = False                                      # *Send report* under way (its save, then its zip)
        self.outbox = None                                        # the zip the What goes page shows (send_report.Outbox)
        self.waiting = None                                       # a zip kept after a send that didn't go
        self.sent_id = None                                       # the last report sent (#ID), for Copy
        self.sent_opened = None                                   # the sent report its page shows (#ID, zip path)
        self.name_filled = False                                  # the remembered Discord name filled in (once)
        self.goes_name_value = ""                                 # the name What goes said goes
        self._thumbs = None                                       # the form's thumbnails, made once per set of pictures
        self.gathering = False                                    # What goes is up, its zip still being made (try a9.1)
        self.gathered = bridge.Relay(self)                        # ... the worker's count of the files gathered so far
        self.gathered.said.connect(self._gathered)
        f = theme.text_factor(style.current()[1])
        self.pages = QStackedWidget(self)
        self.body.addWidget(self.pages, 1)
        self.pages.addWidget(self._form_page())
        self.pages.addWidget(self._opened_page())
        self.pages.addWidget(self._contents_page())
        self.pages.addWidget(self._goes_page())
        self.pages.addWidget(self._sent_page())
        self.pages.currentChanged.connect(self._page_changed)
        self.body.addWidget(self._heading(strings.REPORT_LIST_HEADING.format(n=0)))
        self.list_heading = self.body.itemAt(self.body.count() - 1).widget()
        self.list = QListWidget(self)
        self.list.setObjectName("windowlist")
        self.list.setToolTip(strings.REPORT_LIST_TIP)
        self.list.setAccessibleName(strings.REPORT_LIST_NAME)
        self.list.setMinimumHeight(round(96 * f))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # a long line elides instead
        self.body.addWidget(self.list)
        self.body.addLayout(self._send_row())
        self.body.addLayout(self._after_rows())
        self.hint = self._line(strings.REPORT_HINT)
        self.body.addWidget(self.hint)
        where = QHBoxLayout()
        self.send_where = self._line(strings.REPORT_SEND_WHERE)
        where.addWidget(self.send_where, 1)
        self.issues_button = self._button(strings.REPORT_ISSUES, strings.REPORT_ISSUES_TIP, self.open_issues, where)
        self.issues_button.setObjectName("windowlink")                # a link: its arc's room at its right end only
        qpress.room(self.issues_button, end=True)
        self.issues_button.setCursor(Qt.CursorShape.PointingHandCursor)
        where.setAlignment(self.issues_button, Qt.AlignmentFlag.AlignBottom)
        self.body.addLayout(where)
        for w in (self.send_where, self.issues_button):           # try a9 #6: GitHub only on the zip's path, never
            w.setVisible(False)                                    # ... beside Send (it goes privately to Sonic)
        self.dest_row += [self.send_where, self.issues_button]
        self.setMinimumWidth(round(560 * f))
        self._show_pictures()
        self._restore_draft()
        prepare_identity()                                        # (worked out after the first frame; else now)
        self.read()
        self.read_send()

    # --- parts ------------------------------------------------------------------------------------------------- #
    def _heading(self, text):
        h = QLabel(text, self)
        h.setObjectName("windowheading")
        h.setTextFormat(Qt.TextFormat.PlainText)
        return h

    def _line(self, text):
        line = QLabel(text, self)
        line.setObjectName("windowline")
        line.setTextFormat(Qt.TextFormat.PlainText)
        line.setWordWrap(True)
        return line

    def _button(self, label, tip, slot, row, kind=None, presses=False):
        b = QPushButton(label, self)
        b.setToolTip(tip)
        b.setAccessibleName(label)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if kind:
            b.setProperty("kind", kind)
        if presses:
            qpress.room(b)
        b.clicked.connect(lambda _c=False: slot())
        row.addWidget(b)
        return b

    def _text(self, tip, name, lines):
        t = QPlainTextEdit(self)
        t.setToolTip(tip)
        t.setAccessibleName(name)
        t.setTabChangesFocus(True)
        t.setFixedHeight(round(QFontMetrics(t.font()).lineSpacing() * lines + 16))
        return t

    def _form_page(self):
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._heading(strings.REPORT_WHAT))
        self.what = self._text(strings.REPORT_WHAT_TIP, strings.REPORT_WHAT, 4)
        self.what.setPlaceholderText(strings.REPORT_WHAT_HINT)
        self.what.textChanged.connect(self._form_changed)
        box.addWidget(self.what)
        box.addWidget(self._line(strings.REPORT_EXPECTED))
        self.expected = self._text(strings.REPORT_EXPECTED_TIP, strings.REPORT_EXPECTED, 2)
        box.addWidget(self.expected)
        self.picture_row = QHBoxLayout()
        self.picture_row.setSpacing(8)
        box.addLayout(self.picture_row)
        row = QHBoxLayout()
        self.leave_out = QCheckBox(strings.REPORT_LEAVE_OUT, self)
        self.leave_out.setToolTip(strings.REPORT_LEAVE_OUT_TIP)
        self.leave_out.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.leave_out.toggled.connect(self._show_pictures)
        row.addWidget(self.leave_out)
        row.addStretch(1)
        self.save_button = self._button(strings.REPORT_SAVE, strings.REPORT_SAVE_TIP, self.save, row, "primary",
                                        presses=True)
        self.save_button.setEnabled(False)
        box.addLayout(row)
        QShortcut(QKeySequence("Ctrl+Return"), page, activated=self.save)
        return page

    def _opened_page(self):
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.opened_heading = self._heading("")
        box.addWidget(self.opened_heading)
        self.opened_text = QPlainTextEdit(self)
        self.opened_text.setReadOnly(True)
        self.opened_text.setToolTip(strings.REPORT_OPENED_TIP)
        self.opened_text.setAccessibleName(strings.REPORT_OPENED_NAME)
        box.addWidget(self.opened_text, 1)
        self.opened_pictures = QHBoxLayout()
        self.opened_pictures.setSpacing(8)
        box.addLayout(self.opened_pictures)
        self.note = self._text(strings.REPORT_NOTE_TIP, strings.REPORT_NOTE_NAME, 2)
        self.note.setPlaceholderText(strings.REPORT_NOTE_HINT)
        box.addWidget(self.note)
        row = QHBoxLayout()
        self.back_button = self._button(strings.REPORT_BACK, strings.REPORT_BACK_TIP, self.back, row)
        row.addStretch(1)
        self.note_button = self._button(strings.REPORT_ADD_NOTE, strings.REPORT_ADD_NOTE_TIP, self.add_note, row,
                                        "primary", presses=True)
        box.addLayout(row)
        return page

    def _contents_page(self):
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._heading(strings.REPORT_CONTENTS_HEADING))
        self.contents = QPlainTextEdit(self)
        self.contents.setReadOnly(True)
        self.contents.setToolTip(strings.REPORT_CONTENTS_TIP)
        self.contents.setAccessibleName(strings.REPORT_CONTENTS_HEADING)
        self.contents.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        box.addWidget(self.contents, 1)
        row = QHBoxLayout()
        self.contents_back = self._button(strings.REPORT_BACK, strings.REPORT_BACK_TIP, self.back, row)
        row.addStretch(1)
        box.addLayout(row)
        return page

    def _goes_page(self):
        """*What goes* (Q1): every file that goes and its size, the placeholders, the pictures at full width, the
        Discord name or none, the sender code, how long it's kept and by whom, and what's left out and why."""
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._heading(strings.REPORT_GOES_HEADING))
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget(scroll)
        lines = QVBoxLayout(inner)
        lines.setContentsMargins(0, 0, 0, 0)
        self.goes_gathering = self._line(strings.REPORT_GATHERING)              # (try a9.1: shown while it's made)
        self.goes_gathering.setVisible(False)
        lines.addWidget(self.goes_gathering)
        self.goes_placeholders = self._line(strings.REPORT_GOES_PLACEHOLDERS)
        self.goes_name = self._line("")
        self.goes_sender = self._line("")
        self.goes_kept = self._line(strings.REPORT_GOES_KEPT)
        for line in (self.goes_placeholders, self.goes_name, self.goes_sender, self.goes_kept):
            lines.addWidget(line)
        self.goes_files = QLabel(inner)
        self.goes_files.setObjectName("windowline")
        self.goes_files.setTextFormat(Qt.TextFormat.PlainText)
        self.goes_files.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.goes_files.setToolTip(strings.REPORT_GOES_TIP)
        self.goes_files.setAccessibleName(strings.REPORT_GOES_HEADING)
        lines.addWidget(self.goes_files)
        self.goes_pictures_line = self._line(strings.REPORT_GOES_PICTURES)
        lines.addWidget(self.goes_pictures_line)
        self.goes_pictures = QVBoxLayout()
        lines.addLayout(self.goes_pictures)
        lines.addStretch(1)
        scroll.setWidget(inner)
        self.goes_scroll = scroll
        box.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.goes_back = self._button(strings.REPORT_BACK, strings.REPORT_GOES_BACK_TIP, self.back, row)
        row.addStretch(1)
        self.goes_open = self._button(strings.REPORT_GOES_OPEN, strings.REPORT_GOES_OPEN_TIP, self.open_outbox, row,
                                      presses=True)
        self.goes_send = self._button(strings.REPORT_GOES_SEND, strings.REPORT_GOES_SEND_TIP, self.send, row,
                                      "primary", presses=True)
        box.addLayout(row)
        return page

    def _sent_page(self):
        """A sent #ID opened (try a9 #6): the reports it held — each one's words, then its pictures at the page's
        width — read from the zip kept on this PC, as they went; *Open the zip* shows that zip in its folder."""
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.sent_opened_heading = self._heading("")
        box.addWidget(self.sent_opened_heading)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setToolTip(strings.REPORT_SENT_OPENED_TIP)
        inner = QWidget(scroll)
        self.sent_lines = QVBoxLayout(inner)
        self.sent_lines.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        self.sent_scroll = scroll
        box.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.sent_back = self._button(strings.REPORT_BACK, strings.REPORT_BACK_TIP, self.back, row)
        row.addStretch(1)
        self.sent_zip = self._button(strings.REPORT_SENT_ZIP, strings.REPORT_SENT_ZIP_TIP, self.open_sent_zip, row,
                                     presses=True)
        box.addLayout(row)
        return page

    def _send_row(self):
        """The name field, then *Include my last lists* · *Show me what's in it* · *Make a zip instead* · **Send
        report**, the promise under it, always, and a second line once a Discord name is typed."""
        box = QVBoxLayout()
        named = QHBoxLayout()
        self.name_label = self._line(strings.REPORT_NAME_LABEL)
        self.name_label.setWordWrap(False)
        named.addWidget(self.name_label)
        self.name_field = QLineEdit(self)
        self.name_field.setMaxLength(send_report.NAME_MAX)
        self.name_field.setPlaceholderText(strings.REPORT_NAME_HINT)
        self.name_field.setToolTip(strings.REPORT_NAME_TIP)
        self.name_field.setAccessibleName(strings.REPORT_NAME_LABEL)
        self.name_field.textChanged.connect(self._name_changed)
        self.name_label.setBuddy(self.name_field)
        named.addWidget(self.name_field, 1)
        box.addLayout(named)
        row = QHBoxLayout()
        self.include_results = QCheckBox(strings.REPORT_RESULTS, self)
        self.include_results.setChecked(True)
        self.include_results.setToolTip(strings.REPORT_RESULTS_TIP)
        self.include_results.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.include_results.toggled.connect(lambda _on: self._contents_stale())
        row.addWidget(self.include_results)
        row.addStretch(1)
        self.show_button = self._button(strings.REPORT_SHOW, strings.REPORT_SHOW_TIP, self.show_contents, row,
                                        presses=True)
        self.zip_button = self._button(strings.REPORT_ZIP, strings.REPORT_ZIP_NONE_TIP, self.make_zip, row,
                                       presses=True)
        self.send_button = self._button(strings.REPORT_SEND, strings.REPORT_SEND_NONE_TIP, self.send_report, row,
                                        "primary", presses=True)
        self.zip_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.show_button.setEnabled(False)
        box.addLayout(row)
        self.promise = self._line(strings.REPORT_PROMISE)
        self.promise.setAlignment(Qt.AlignmentFlag.AlignRight)
        box.addWidget(self.promise)
        self.name_goes = self._line(strings.REPORT_NAME_GOES)
        self.name_goes.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.name_goes.setVisible(False)
        box.addWidget(self.name_goes)
        return box

    def _after_rows(self):
        """The sender code and *New code*; after a send, the #ID with *Copy* and the invite, and *Sent reports* right
        under it (try a9 #6: where the reports went); a report waiting to send with *Send now* · *Don't send*; the
        zip's folder (after *Make a zip instead*)."""
        box = QVBoxLayout()
        code = QHBoxLayout()
        self.sender_line = self._line("")
        self.sender_line.setToolTip(strings.REPORT_SENDER_TIP)
        code.addWidget(self.sender_line, 1)
        self.new_code_button = self._button(strings.REPORT_NEW_CODE, strings.REPORT_NEW_CODE_TIP, self.new_code, code,
                                            "chip", presses=True)
        self.new_code_button.setEnabled(False)                    # (until the code is read)
        box.addLayout(code)
        done = QHBoxLayout()
        self.done_line = self._line("")
        done.addWidget(self.done_line, 1)
        self.copy_button = self._button(strings.REPORT_COPY, strings.REPORT_COPY, self.copy_id, done, "chip")
        self.invite_button = self._button(strings.REPORT_INVITE, strings.REPORT_INVITE_TIP.format(url=SS.DISCORD_URL),
                                          self.open_invite, done, presses=True)
        self.invite_button.setObjectName("windowlink")
        self.invite_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_row = [self.done_line, self.copy_button, self.invite_button]
        for w in self.done_row:
            w.setVisible(False)
        box.addLayout(done)
        self.sent_box = QWidget(self)                             # (one switch: held while What goes is up)
        sent = QVBoxLayout(self.sent_box)
        sent.setContentsMargins(0, 0, 0, 0)
        self.sent_heading = self._heading(strings.REPORT_SENT_HEADING)
        sent.addWidget(self.sent_heading)
        self.sent_rows = QVBoxLayout()
        sent.addLayout(self.sent_rows)
        self.sent_box.setVisible(False)
        box.addWidget(self.sent_box)
        wait = QHBoxLayout()
        self.waiting_line = self._line(strings.REPORT_WAITING)
        wait.addWidget(self.waiting_line, 1)
        self.send_now_button = self._button(strings.REPORT_SEND_NOW, strings.REPORT_SEND_NOW_TIP, self.send_now, wait,
                                            presses=True)
        self.dont_send_button = self._button(strings.REPORT_DONT_SEND, strings.REPORT_DONT_SEND_TIP, self.dont_send,
                                             wait, presses=True)
        self.waiting_row = [self.waiting_line, self.send_now_button, self.dont_send_button]
        for w in self.waiting_row:
            w.setVisible(False)
        box.addLayout(wait)
        where = QHBoxLayout()
        self.dest_line = self._line("")
        where.addWidget(self.dest_line, 1)
        self.change_button = self._button(strings.REPORT_CHANGE, strings.REPORT_CHANGE_TIP, self.pick_folder, where)
        self.dest_row = [self.dest_line, self.change_button]
        for w in self.dest_row:                                   # the GitHub path: shown once a zip is made
            w.setVisible(False)
        box.addLayout(where)
        self._show_dest()
        return box

    def _show_dest(self):
        self.dest_line.setText(strings.REPORT_SAVE_TO.format(folder=self.dest))
        self.dest_line.setToolTip(self.dest)

    # --- the draft: what was typed and not saved, kept on the main window while Surasura runs ----------------------- #
    def _restore_draft(self):
        draft = getattr(self.shell, DRAFT, None)
        if not draft:
            return
        self.what.setPlainText(draft.get("what", ""))
        self.expected.setPlainText(draft.get("expected", ""))
        self.leave_out.setChecked(bool(draft.get("leave_out")))
        if not self.pictures and draft.get("pictures"):            # opened without a new picture: the draft's
            self.set_pictures(draft["pictures"], draft.get("scrubbed", False))

    def _keep_draft(self):
        what, expected = self.what.toPlainText(), self.expected.toPlainText()
        if what.strip() or expected.strip():
            setattr(self.shell, DRAFT, {"what": what, "expected": expected, "leave_out": self.leave_out.isChecked(),
                                        "pictures": list(self.pictures), "scrubbed": self.scrubbed})
        else:
            setattr(self.shell, DRAFT, None)

    def closeEvent(self, event):
        try:
            self._keep_draft()                                     # Esc or ✕: the words wait for the next press
            if self.outbox is not None and not qpress.live(self, "report:send"):     # looked at, not sent: deleted
                sha, self.outbox = self.outbox.sha256, None
                threading.Thread(target=discard, args=(sha,), name="report-discard", daemon=True).start()
        except RuntimeError:
            pass
        super().closeEvent(event)

    # --- the pictures ------------------------------------------------------------------------------------------ #
    def set_pictures(self, pictures, scrubbed=False):
        """The bug pressed again with the window open: the new pictures for the next report (`scrubbed`: taken in
        picture mode)."""
        self.pictures = list(pictures)
        self.scrubbed = bool(scrubbed)
        self._thumbs = None
        self._show_pictures()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _thumb(self, pixmap, tip):
        label = QLabel(self)
        label.setPixmap(pixmap)
        label.setToolTip(tip)
        label.setAccessibleName(tip)
        return label

    def _show_pictures(self, *_):
        """The form's pictures: their thumbnails made once per set of pictures (`_thumbs`); the tick only hides them
        and says so."""
        if getattr(self, "_thumbs", None) is None:
            self._clear(self.picture_row)
            self._thumbs = []
            dpr = self.devicePixelRatioF()
            for img in self.pictures:
                pm = QPixmap.fromImage(img).scaledToWidth(round(THUMB * dpr),
                                                          Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                thumb = self._thumb(pm, strings.REPORT_PICTURE_TIP)
                self._thumbs.append(thumb)
                self.picture_row.addWidget(thumb)
            self.picture_note = self._line("")
            self.picture_row.addWidget(self.picture_note)
            self.picture_row.addStretch(1)
        out = self.leave_out.isChecked()
        for thumb in self._thumbs:
            thumb.setVisible(not out)
        if not self.pictures:
            note = strings.REPORT_NO_PICTURE_TAKEN
        elif out:
            note = strings.REPORT_NO_PICTURE
        else:
            note = ""
        self.picture_note.setText(note)
        self.picture_note.setVisible(bool(note))

    # --- the list ---------------------------------------------------------------------------------------------- #
    def read(self, then_say=None):
        bridge.run_in_worker(core.listed, then=self.alive(lambda got: self._show(got, then_say)),
                             failed=self.alive(lambda info: self.say(strings.REPORT_READ_FAILED.format(why=info[0]))))

    def _show(self, reports, line=None):
        reports = list(reports)
        ids = [(r.id, len(r.notes)) for r in reports]
        if self.reports is None or ids != [(r.id, len(r.notes)) for r in self.reports]:     # repainted on change
            self.reports = reports
            self.list.clear()
            for r in reports:
                item = QListWidgetItem(self.list)
                row = self._row(r)
                item.setSizeHint(row.sizeHint())
                self.list.setItemWidget(item, row)
            self.list_paints += 1
        else:
            self.reports = reports
        n = len(reports)
        self.list_heading.setText(strings.REPORT_LIST_HEADING.format(n=n))
        self.zip_button.setEnabled(n > 0)
        self.show_button.setEnabled(n > 0)
        self.zip_button.setToolTip(strings.REPORT_ZIP_TIP if n else strings.REPORT_ZIP_NONE_TIP)
        self._send_ready()
        button = getattr(self.shell, "report_button", None)
        if button is not None:
            button.set_count(n)
        if line is not None:
            self.say(line)
        elif not n and not self.status.text():
            self.say(strings.REPORT_EMPTY)

    def _row(self, r):
        w = QWidget(self.list)
        box = QHBoxLayout(w)
        box.setContentsMargins(6, 2, 6, 2)
        title = r.title()
        notes = strings.REPORT_ROW_NOTES.format(n=len(r.notes)) if r.notes else ""
        label = ElidedLabel(strings.REPORT_ROW.format(when=_when(r.created), what=title, notes=notes), w)
        label.setObjectName("windowline")
        label.setToolTip(r.what)
        box.addWidget(label, 1)
        for text, tip, slot in ((strings.REPORT_OPEN, strings.REPORT_OPEN_TIP, lambda _c=False, i=r.id: self.open(i)),
                                (strings.REPORT_REMOVE, strings.REPORT_REMOVE_TIP,
                                 lambda _c=False, i=r.id: self.remove(i, self.sender()))):
            b = QPushButton(text, w)
            b.setToolTip(tip)
            b.setAccessibleName(strings.REPORT_ROW_BUTTON_NAME.format(action=text, what=title))
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(slot)
            box.addWidget(b)
        return w

    def _form_changed(self):
        self.save_button.setEnabled(bool(self.what.toPlainText().strip()))
        self._send_ready()

    def _send_ready(self):
        """*Send report*: ready with a saved report, or with words typed (saved first)."""
        if not hasattr(self, "send_button"):                      # (the form is built before the send row)
            return
        ready = bool(self.reports) or self.save_button.isEnabled() or self.sending
        self.send_button.setEnabled(ready and not self.gathering)    # (What goes is up, gathering: pressed already)
        self.send_button.setToolTip(strings.REPORT_SEND_TIP if ready else strings.REPORT_SEND_NONE_TIP)

    def _name_changed(self, text):
        self.name_goes.setVisible(bool(text.strip()))

    # --- the presses ------------------------------------------------------------------------------------------- #
    def save(self, then=None, control=None, broke=None):
        """`then()`: once it is saved, `broke()` when it couldn't be (*Send report*'s zip, its arc on `control`). Its
        pictures are marked scrubbed only when taken in picture mode: an unmarked one is never sent."""
        what = self.what.toPlainText().strip()
        if not what or not self.save_button.isEnabled():
            return
        expected = self.expected.toPlainText()
        images = [] if self.leave_out.isChecked() else list(self.pictures)
        scrubbed = self.scrubbed and bool(images)
        sent = (self.what.toPlainText(), expected, self.pictures)
        where = _where(self.shell)

        def work():
            return core.save(what, expected, [png_bytes(i) for i in images], where=where, scrubbed=scrubbed)
        def saved(r):
            self._saved(r, sent)
            if then is not None:
                then()

        def failed(info):
            self.say(strings.REPORT_SAVE_FAILED.format(why=info[0]))
            if broke is not None:
                broke()
        return qpress.run(control or self.save_button, "report:save", work, win=self, then=self.alive(saved),
                          failed=self.alive(failed))

    def _saved(self, _report, sent=None):
        """Saved: the form clears — only what was saved (words typed or a picture taken meanwhile stay)."""
        if sent is not None and (self.what.toPlainText(), self.expected.toPlainText()) != sent[:2]:
            setattr(self.shell, DRAFT, None)
            self._contents_stale()
            self.read(then_say=strings.REPORT_SAVED)
            return
        setattr(self.shell, DRAFT, None)
        self.what.clear()
        self.expected.clear()
        self.leave_out.setChecked(False)
        if sent is not None and self.pictures is not sent[2]:      # the bug pressed again meanwhile: its picture stays
            self._contents_stale()
            self.read(then_say=strings.REPORT_SAVED)
            return
        self.set_pictures([])                                      # the next report's picture: the next press
        self._contents_stale()
        self.read(then_say=strings.REPORT_SAVED)

    def open(self, rid):
        r = next((x for x in (self.reports or []) if x.id == rid), None)
        if r is None:
            return
        self.opened_id = rid
        self.sent_opened = None
        self.opened_heading.setText(_when(r.created))
        parts = [r.what]
        if r.expected:
            parts += ["", strings.REPORT_EXPECTED_LINE, r.expected]
        for note in r.notes:
            parts += ["", strings.REPORT_NOTE_LINE.format(when=_when(note.get("at", "")), text=note.get("text", ""))]
        self.opened_text.setPlainText("\n".join(parts))
        self._clear(self.opened_pictures)
        paths = [os.path.join(r.path, name) for name in r.pictures]
        dpr = self.devicePixelRatioF()
        bridge.run_in_worker(_thumbnails, paths, round(THUMB * dpr),
                             then=self.alive(lambda got, i=rid: self._opened_pictures(i, got, dpr)),
                             failed=lambda _info: None)
        self.note.clear()
        self.pages.setCurrentIndex(self.OPENED)
        self.note.setFocus()

    def _opened_pictures(self, rid, got, dpr):
        """The opened report's pictures (read on a worker), each a button that opens it in the picture viewer."""
        if rid != self.opened_id:
            return                                                 # another report opened meanwhile
        for path, img in got:
            b = QPushButton(self)
            if not img.isNull():
                pm = QPixmap.fromImage(img)
                pm.setDevicePixelRatio(dpr)
                b.setIcon(QIcon_from(pm))
                b.setIconSize(QSize(THUMB, round(pm.height() / dpr)))
            b.setToolTip(strings.REPORT_PICTURE_OPEN_TIP)
            b.setAccessibleName(strings.REPORT_PICTURE_OPEN_TIP)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(lambda _c=False, p=path, c=b: qpress.open(self, p, control=c))
            self.opened_pictures.addWidget(b)
        self.opened_pictures.addStretch(1)

    def add_note(self):
        text = self.note.toPlainText().strip()
        rid = self.opened_id
        if not text or rid is None:
            return
        def noted(r):
            if self.opened_id == rid and self.note.toPlainText().strip() == text:
                self.note.clear()                                  # only once it is written: a failure keeps it
            self._contents_stale()
            self.read(then_say=strings.REPORT_NOTED)
            if self.opened_id == rid and r is not None:            # the opened page shows the note too
                self.opened_text.appendPlainText("\n" + strings.REPORT_NOTE_LINE.format(
                    when=_when(r.notes[-1].get("at", "")), text=r.notes[-1].get("text", "")))
        qpress.run(self.note_button, f"report:note:{rid}", core.add_note, rid, text, win=self, then=self.alive(noted),
                   failed=self.alive(lambda info: self.say(strings.REPORT_NOTE_FAILED.format(why=info[0]))))

    def back(self):
        """Back to the form. From What goes: its zip is deleted unsent (the reports stay on the list); while it is still
        being made, it is deleted once made (`_build`)."""
        self.gathering = False
        self.opened_id = None
        self.sent_opened = None
        if self.outbox is not None and not qpress.live(self, "report:send"):
            sha, self.outbox = self.outbox.sha256, None
            qpress.run(None, "report:send", discard, sha, win=self, then=self.alive(lambda _g: self.read_send()),
                       failed=lambda _info: None)
        self.pages.setCurrentIndex(self.FORM)
        if hasattr(self, "send_button"):
            self._goes_hold(False)
        self.what.setFocus()

    def remove(self, rid, control=None):
        def done(gone):
            if not gone:                                           # already gone (a zip took it): the list read again
                self.read(then_say=strings.REPORT_GONE)
                return
            self.last_removed = rid
            if self.opened_id == rid:
                self.back()
            self._contents_stale()
            self.read(then_say=strings.REPORT_REMOVED)
            self.say_undo(True)
        qpress.run(control, f"report:remove:{rid}", core.remove, rid, win=self, then=self.alive(done),
                   failed=self.alive(lambda info: self.say(strings.REPORT_REMOVE_FAILED.format(why=info[0]))))

    def say_undo(self, on):
        if not hasattr(self, "undo_button"):
            self.undo_button = QPushButton(strings.REPORT_UNDO, self)
            self.undo_button.setToolTip(strings.REPORT_UNDO_TIP)
            self.undo_button.setAccessibleName(strings.REPORT_UNDO)
            self.undo_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.undo_button.setProperty("kind", "chip")
            self.undo_button.clicked.connect(lambda _c=False: self.undo())
            self.layout().addWidget(self.undo_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.undo_button.setVisible(on)

    def undo(self):
        rid = self.last_removed
        if rid is None:
            return
        self.last_removed = None
        self.say_undo(False)
        def restored(ok):                                          # (the button hides: the press marks the status line)
            self.read(then_say=strings.REPORT_RESTORED if ok else strings.REPORT_NOT_RESTORED)
        qpress.run(None, f"report:undo:{rid}", core.restore, rid, win=self, then=self.alive(restored),
                   failed=self.alive(lambda info: self.say(strings.REPORT_REMOVE_FAILED.format(why=info[0]))))

    def pick_folder(self):
        got = QFileDialog.getExistingDirectory(self, strings.REPORT_PICK, self.dest)
        if got:
            self.dest = os.path.normpath(got)
            self._show_dest()

    def _contents_stale(self):
        if self.pages.currentIndex() == self.CONTENTS:
            self.back()

    def show_contents(self):
        language = self.language
        include = self.include_results.isChecked()

        def shown(plan):
            self.contents.setPlainText(core.describe(plan))
            self.pages.setCurrentIndex(self.CONTENTS)
        library = library_summary(self.shell)
        qpress.run(self.show_button, "report:plan", core.plan, language, include, library, None, about_extra(self),
                   win=self,
                   then=self.alive(shown),
                   failed=self.alive(lambda info: self.say(strings.REPORT_ZIP_FAILED.format(why=info[0]))))

    # --- Send report (SPEC §3: press → look → Send) ------------------------------------------------------------ #
    def send_report(self):
        """*Send report*: what's typed saved first, then the scrubbed zip made and checked into the outbox, then the
        What goes page — nothing leaves the PC until its *Send*."""
        if qpress.live(self, "report:zip") or qpress.live(self, "report:send"):    # a report under way: said why
            self.say(strings.REPORT_ZIP_BUSY)
            return
        if self.save_button.isEnabled():
            self._sending(True)
            self._gather()
            if self.save(then=lambda: self._build(saved=True), control=self.send_button,
                         broke=self._not_gathered) is None:
                self._not_gathered()
        elif self.reports:
            self._gather()
            self._build()

    def _gather(self):
        """Send report's press, in its frame (try a9.1, Sonic: "it lagged when i hit the button, just hung there until it
        got to the screen of exactly what goes. need something to indicate that it's thinking"): What goes opens now,
        saying it is gathering, and counts the files in as the worker scrubs them (`_gathered`); filled in once the
        zip is made (`_show_goes`). The window's thread never waited (measured: the press returns in 2 ms, its longest
        stall while a 17 MB zip is made 50 ms) — only the page came at the end, after seconds of a small arc."""
        self.outbox = None
        self.opened_id = self.sent_opened = None
        self.gathering = True
        self.goes_gathering.setText(strings.REPORT_GATHERING)
        self.goes_gathering.setVisible(True)
        for w in (self.goes_placeholders, self.goes_name, self.goes_sender, self.goes_kept, self.goes_files,
                  self.goes_pictures_line):
            w.setVisible(False)
        self._clear(self.goes_pictures)
        self.goes_send.setEnabled(False)
        self.goes_open.setEnabled(False)
        self.pages.setCurrentIndex(self.GOES)
        self._goes_hold(True)
        self.goes_back.setFocus()

    def _gathered(self, count):
        """(The window's thread.) The worker's count, `(done, total)` files gathered: said only while What goes still
        waits for its zip, and only when the words changed."""
        if not self.gathering:
            return
        done, total = count
        if not total:
            words = strings.REPORT_GATHERING
        elif done >= total:
            words = strings.REPORT_GATHERING_CHECK
        else:
            words = strings.REPORT_GATHERING_N.format(done=done + 1, total=total)
        if self.goes_gathering.text() != words:
            self.goes_gathering.setText(words)

    def _not_gathered(self):
        """The press made nothing (its save failed, nothing to save, the zip refused): back to the form; the bar says
        why."""
        was, self.gathering = self.gathering, False
        self._sending(False)
        if was and self.pages.currentIndex() == self.GOES and self.outbox is None:
            self.pages.setCurrentIndex(self.FORM)
            self._goes_hold(False)

    def _sending(self, on):
        self.sending = on
        self._send_ready()

    def _build(self, saved=False):
        """(The window's thread.) The outbox zip made on a worker; `saved`: a report was just saved."""
        if not self.reports and not saved:
            self._sending(False)
            self.say(strings.REPORT_EMPTY)
            return
        language, include = self.language, self.include_results.isChecked()
        library, extra = library_summary(self.shell), about_extra(self)
        relay = self.gathered
        width = round(self._goes_width() * self.devicePixelRatioF())

        def built(got):
            if self.gone or not self.gathering:                    # closed, or Back, before it was looked at: never kept
                self.sending = False
                if got[0] == "built":                              # (only the zip this press made)
                    threading.Thread(target=discard, args=(got[1].sha256,), name="report-discard",
                                     daemon=True).start()
                if not self.gone:
                    self._sending(False)
                    self._hold(False)
                return
            self._sending(False)
            self._hold(False)
            self._built(*got)

        def broke(info):
            self.sending = False
            if not self.gone:
                self._not_gathered()
                self._hold(False)
                self.say(strings.REPORT_SEND_FAILED.format(why=info[0]))
        self._hold(True)
        # (no words in the bar: What goes says it, counting — try a9.1, nothing said twice)
        p = qpress.run(self.send_button, "report:send", prepare_send, language, include, library, extra,
                       lambda done, total: relay.call((done, total)), width, win=self, then=built, failed=broke)
        if p is None:
            self._hold(False)
            self._not_gathered()

    def _built(self, kind, outbox, pictures, code=None):
        if kind != "built":
            self._not_gathered()
        if kind == "limit":
            self.say(strings.REPORT_SEND_LIMIT)
        elif kind == "too big":
            self.say(strings.REPORT_SEND_TOO_BIG)
        elif kind == "unsafe":
            self.say(strings.REPORT_SEND_UNSAFE)
        else:
            self._show_goes(outbox, pictures, code)
        self.read_send()

    def _goes_width(self):
        """The What goes page's width for a picture (logical px)."""
        return max(1, self.goes_scroll.viewport().width() - 4, self.pages.width() - 24)

    def _show_goes(self, outbox, pictures, code=None):
        """The What goes page for `outbox`, its pictures (QImages read from the zip) at the page's width. The Discord
        name and the sender code it shows are the ones that go: the row under it waits while it's up (`_goes_hold`)."""
        self.outbox = outbox
        self.opened_id = self.sent_opened = None
        self.gathering = False
        self.goes_gathering.setVisible(False)
        for w in (self.goes_placeholders, self.goes_name, self.goes_kept, self.goes_files):
            w.setVisible(True)
        self.goes_send.setEnabled(True)
        self.goes_open.setEnabled(True)
        self.goes_name_value = " ".join(self.name_field.text().split())       # (as send_report cleans it)
        name = self.goes_name_value
        self.goes_name.setText(strings.REPORT_GOES_NAME.format(name=name) if name else strings.REPORT_GOES_NO_NAME)
        if code:
            self.sender_line.setText(strings.REPORT_SENDER.format(code=code))
        self.goes_sender.setText(self.sender_line.text())
        self.goes_sender.setVisible(bool(self.sender_line.text()))
        self.goes_files.setText(outbox.describe())
        self._clear(self.goes_pictures)
        self.pages.setCurrentIndex(self.GOES)
        self._goes_hold(True)
        self.pages.currentWidget().layout().activate()            # (laid out: the pictures' width is the page's)
        width = self._goes_width()
        dpr = self.devicePixelRatioF()
        for img in pictures:                                       # (scaled on the worker to the page's width at the
            pm = QPixmap.fromImage(img)                            # ... press: here only when the window grew since)
            if pm.width() > round(width * dpr) + 1:
                pm = pm.scaledToWidth(round(width * dpr), Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.goes_pictures.addWidget(self._thumb(pm, strings.REPORT_GOES_PICTURE_TIP))
        self.goes_pictures_line.setVisible(bool(pictures))
        self.goes_send.setFocus()

    def _goes_hold(self, on):
        """While What goes is up (and while its zip is sent): the name, the code and the send row wait, so what goes
        is what the page says."""
        for w in (self.name_field, self.send_button, self.zip_button, self.show_button, self.new_code_button,
                  self.include_results):
            w.setEnabled(not on)
        for w in (self.list_heading, self.list, self.hint):       # (the page's room: the list is in the zip it shows)
            w.setVisible(not on)
        self.sent_box.setEnabled(not on)                          # (a sent #ID opens once What goes is left)
        if not on:
            self.new_code_button.setEnabled(bool(self.sender_line.text()))
            self._send_ready()
            n = len(self.reports or [])
            self.zip_button.setEnabled(n > 0)
            self.show_button.setEnabled(n > 0)

    def send(self):
        """The What goes page's *Send*: the zip it showed, once (another one waiting instead is never sent)."""
        if self.outbox is not None:
            self._send(self.goes_send, self.outbox)

    def send_now(self):
        """*Send now*: the waiting zip again, with its own nonce (the receiver gives the same #ID)."""
        if self.waiting is not None:
            self._send(self.send_now_button, self.waiting)

    def _send(self, control, outbox):
        if qpress.live(self, "report:send") or qpress.live(self, "report:zip"):
            self.say(strings.REPORT_ZIP_BUSY)
            return
        name = self.goes_name_value if outbox is self.outbox else self.name_field.text()
        shell = self.shell

        def done(result):
            words = _send_words(result)
            if self.gone:                                          # Esc while it went: the main window says it
                windows.say_in_bar(shell, words)
                _count_again(shell)
                return
            self._hold(False)
            self.outbox = None
            if result.outcome == send_report.SENT:
                self.sent_id = result.id
                self.last_removed = None
                self.say_undo(False)
                self._done_row(sent_where(result.id, len(outbox.zipped)), copy=True, invite=strings.REPORT_INVITE)
            if self.pages.currentIndex() == self.GOES:
                self.back()
            self.read(then_say=words)
            self.read_send()

        def broke(info):
            words = strings.REPORT_SEND_FAILED.format(why=info[0])
            if self.gone:
                windows.say_in_bar(shell, words)
                return
            self._hold(False)
            self.outbox = None
            if self.pages.currentIndex() == self.GOES:
                self.back()
            self.say(words)
            self.read_send()
        self._hold(True)
        p = qpress.run(control, "report:send", send_report.send, name, None, None, None, outbox.nonce, win=self,
                       busy=strings.REPORT_SENDING.format(size=core._mb(outbox.size)), then=done, failed=broke)
        if p is None:
            self._hold(False)

    def dont_send(self):
        """*Don't send*: the waiting zip deleted; the saved reports stay on the list."""
        def gone(_was):
            self.read_send(then_say=strings.REPORT_DISCARDED)
        sha = self.waiting.sha256 if self.waiting is not None else None      # (only the one it showed)
        qpress.run(self.dont_send_button, "report:send", discard, sha, win=self, then=self.alive(gone),
                   failed=self.alive(lambda info: self.say(strings.REPORT_SEND_FAILED.format(why=info[0]))))

    def open_outbox(self):
        """*Open the zip*: the zip that goes, selected in its folder (the exact bytes)."""
        if self.outbox is not None:
            show_zip(self, self.outbox.path, control=self.goes_open)

    def read_send(self, then_say=None):
        """(A worker.) This PC's send state: a waiting zip, the sent copies, the sender code, the remembered name."""
        self._reads = getattr(self, "_reads", 0) + 1
        n = self._reads
        bridge.run_in_worker(send_state, then=self.alive(lambda got: self._show_send(got, then_say, n)),
                             failed=lambda _info: None)

    def _show_send(self, got, line=None, n=None):
        if n is not None and n != self._reads:                    # a newer read is on its way
            return
        self.send_read = n                                        # (the read last shown: a test waits for it)
        waiting, sent, code, name = got
        self.waiting = waiting
        shown = waiting is not None and self.outbox is None and not qpress.live(self, "report:send")
        for w in self.waiting_row:                                 # (never beside What goes, which shows that zip, nor
            w.setVisible(shown)                                    # ... while a send or a delete is under way)
        if code:
            self.sender_line.setText(strings.REPORT_SENDER.format(code=code))
            self.new_code_button.setEnabled(self.outbox is None and not qpress.live(self, "report:send"))
        if name and not self.name_filled and not self.name_field.isModified():      # once, never over an edit
            self.name_field.setText(name)
        self.name_filled = True
        self._clear(self.sent_rows)
        for rid, when, path in sent[:SENT_SHOWN]:
            self.sent_rows.addWidget(self._sent_row(rid, when, path))
        self.sent_heading.setVisible(bool(sent))
        self.sent_box.setVisible(bool(sent))
        if line is not None:
            self.say(line)

    def _sent_row(self, rid, when, path):
        """A sent #ID: *Open* (the reports it held, try a9 #6) and *Open the zip* (selected in its folder)."""
        w = QWidget(self.sent_box)
        box = QHBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)
        when = when.strftime("%Y-%m-%d %H:%M")
        label = self._line(strings.REPORT_SENT_ROW.format(id=rid, when=when))
        box.addWidget(label, 1)
        for text, tip, slot in (
                (strings.REPORT_SENT_OPEN, strings.REPORT_SENT_OPEN_TIP.format(id=rid),
                 lambda c: self.open_sent(rid, when, path, control=c)),
                (strings.REPORT_SENT_ZIP, strings.REPORT_SENT_ZIP_TIP, lambda c: show_zip(self, path, control=c))):
            b = QPushButton(text, w)
            b.setToolTip(tip)
            b.setAccessibleName(strings.REPORT_ROW_BUTTON_NAME.format(action=text, what=f"#{rid}"))
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setProperty("kind", "chip")
            qpress.room(b)
            b.clicked.connect(lambda _c=False, s=slot, c=b: s(c))
            box.addWidget(b)
        return w

    def open_sent(self, rid, when, path, control=None):
        """A sent #ID's reports on their page: read from its zip on a worker (their pictures scaled there, to the
        page's width), shown when they arrive — unless Back or another page came meanwhile."""
        dpr = self.devicePixelRatioF()
        width = max(1, self.pages.width() - 24)
        self.sent_opened = (rid, path)

        def shown(got):
            if self.sent_opened != (rid, path):
                return
            self._show_sent_reports(rid, when, got, dpr)

        def failed(info):
            if self.sent_opened == (rid, path):
                self.sent_opened = None
            self.say(strings.REPORT_SENT_READ_FAILED.format(id=rid, why=info[0]))
        qpress.run(control, f"report:sent:{rid}", sent_contents, path, round(width * dpr), win=self,
                   then=self.alive(shown), failed=self.alive(failed))

    def _page_changed(self, index):
        """Any other page shown (Show me, What goes, a saved report, Back): a sent #ID still being read shows nothing."""
        if index != self.SENT:
            self.sent_opened = None

    def _show_sent_reports(self, rid, when, got, dpr):
        if not got:                                                # (a zip with no reports in it: said, no blank page)
            self.sent_opened = None
            self.say(strings.REPORT_SENT_EMPTY.format(id=rid))
            return
        self.opened_id = None
        self.sent_opened_heading.setText(strings.REPORT_SENT_OPENED.format(id=rid, when=when))
        self._clear(self.sent_lines)
        for _report_id, text, images in got:
            words = self._line(text.rstrip("\n"))
            words.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.sent_lines.addWidget(words)
            for img in images:
                pm = QPixmap.fromImage(img)
                pm.setDevicePixelRatio(dpr)
                self.sent_lines.addWidget(self._thumb(pm, strings.REPORT_SENT_PICTURE_TIP))
        self.sent_lines.addStretch(1)
        self.pages.setCurrentIndex(self.SENT)
        self.sent_back.setFocus()

    def open_sent_zip(self):
        """The opened sent report's zip, selected in its folder."""
        if self.sent_opened is not None:
            show_zip(self, self.sent_opened[1], control=self.sent_zip)

    def new_code(self):
        def made(code):
            self.sender_line.setText(strings.REPORT_SENDER.format(code=code))
            self.say(strings.REPORT_NEW_CODE_DONE.format(code=code))
        qpress.run(self.new_code_button, "report:new-code", send_report.new_code, win=self, then=self.alive(made),
                   failed=self.alive(lambda info: self.say(strings.REPORT_SEND_FAILED.format(why=info[0]))))

    def _done_row(self, words, copy=False, invite=None):
        """After a send (#ID, *Copy*, the invite) or a zip made (the invite): what comes next."""
        self.done_line.setText(words)
        self.done_line.setVisible(bool(words))
        self.copy_button.setVisible(copy)
        if copy and self.sent_id:
            self.copy_button.setToolTip(strings.REPORT_COPY_TIP.format(id=self.sent_id))
        self.invite_button.setVisible(invite is not None)
        if invite is not None:
            self.invite_button.setText(invite)
            self.invite_button.setAccessibleName(invite)

    def copy_id(self):
        if self.sent_id:
            QApplication.clipboard().setText(strings.REPORT_ID.format(id=self.sent_id))
            self.say(strings.REPORT_COPIED.format(id=self.sent_id))

    def open_invite(self):
        qpress.open(self, SS.DISCORD_URL, control=self.invite_button)

    def open_issues(self):
        qpress.open(self, SS.ISSUES_URL, control=self.issues_button)

    # --- Make a zip instead (the GitHub / Discord path by hand) ---------------------------------------------------- #
    def make_zip(self):
        """The zip into Downloads or the folder picked, scrubbed (a file the check flags is named, never a reason to
        stop), shown selected in its folder; the done line offers the invite."""
        if not self.reports or qpress.live(self, "report:zip") or qpress.live(self, "report:send"):
            if self.reports:
                self.say(strings.REPORT_ZIP_BUSY)
            return
        language, include, dest = self.language, self.include_results.isChecked(), self.dest
        library = library_summary(self.shell)
        shell = self.shell
        extra = about_extra(self)

        def made(got):
            path, flagged = got
            name = os.path.basename(path)
            words = (strings.REPORT_ZIPPED_CHECK.format(name=name, folder=dest, n=len(flagged)) if flagged
                     else strings.REPORT_ZIPPED.format(name=name, folder=dest))
            if self.gone:                                          # closed while it was made: the main window says it
                windows.say_in_bar(shell, words)
                _count_again(shell)
                try:
                    show_zip(shell, path)
                except RuntimeError:
                    pass
                return
            self._hold(False)
            self.last_removed = None
            self.say_undo(False)
            self.back()
            for w in self.dest_row:
                w.setVisible(True)
            self._done_row("", invite=strings.REPORT_INVITE_ZIP)
            self.read(then_say=words)
            show_zip(self, path)

        def broke(info):
            words = strings.REPORT_ZIP_FAILED.format(why=info[0])
            if self.gone:
                windows.say_in_bar(shell, words)
                return
            self._hold(False)
            self._send_ready()
            self.say(words)
        self._hold(True)
        p = qpress.run(self.zip_button, "report:zip", zip_checked, dest, language, include, library, extra, win=self,
                       then=made, failed=broke)
        if p is None:
            self._hold(False)

    def _hold(self, on):
        """While a report is made or sent: the list, a note and Undo wait (a report changed meanwhile would be kept
        anyway)."""
        self.list.setEnabled(not on)
        self.note_button.setEnabled(not on)
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(not on)


SENT_SHOWN = 5                  # *Sent reports*: the newest shown (each kept 90 days)


def prepare_send(language, include, library, extra, step=None, width=None):
    """(A worker.) *Send report*'s press: refused before anything is made on the 6th send of a day; else the outbox
    zip (`send_report.build`, `step(done, total)` told each file as it is gathered) and its pictures as QImages, each
    scaled down to `width` device pixels when wider (never on the window's thread). -> (kind, Outbox or None,
    [QImage], the sender code that goes, when built): kind `built`,
    `limit`, `too big` (over 10 MB even trimmed) or `unsafe` (the guard's hit: no zip offered)."""
    from PyQt6.QtGui import QImage
    if send_report.sent_today() >= send_report.PER_DAY:
        return "limit", None, []
    try:
        ob = send_report.build(language, include, library, None, extra, step=step)
    except send_report.TooBig:
        return "too big", None, []
    except core.Unsafe:
        return "unsafe", None, []
    pictures = []
    with zipfile.ZipFile(ob.path) as z:
        for name in z.namelist():
            if name.lower().endswith(".png"):
                img = QImage.fromData(z.read(name), "PNG")
                if not img.isNull():
                    if width and img.width() > width:
                        img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
                    pictures.append(img)
    return "built", ob, pictures, send_report.sender_code()


def discard(sha256=None, tries=5):
    """(A worker.) The outbox zip deleted (`send_report.discard`) — only when it is still the one this window made
    (`sha256`, checked under send_report's lock: another window's newer one, or an older one waiting, is left
    alone) — tried again a moment later while
    a read of it holds it open (Windows refuses the delete then). -> whether one was deleted."""
    import time
    for n in range(tries):
        try:
            return send_report.discard(expect=sha256)
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(0.05)


def send_state():
    """(A worker.) (the waiting Outbox or None, [(id, when, path)] sent, the sender code, the remembered name)."""
    return (send_report.waiting(), send_report.sent_reports(), send_report.sender_code(),
            send_report.remembered_name())


def zip_checked(dest, language, include, library, extra):
    """(A worker.) *Make a zip instead*: the zip and the files its check flagged. -> (path, [names])."""
    found = []
    path = core.make_zip(dest, language, include, library, None, extra, found=found)
    return path, found


def sent_where(rid, n):
    """The done line after a send (try a9 #6): its #ID, and where the reports it held are now."""
    if n > 1:
        return strings.REPORT_SENT_WHERE_MANY.format(id=rid, n=n)
    return strings.REPORT_SENT_WHERE_ONE.format(id=rid)


def sent_contents(path, width):
    """(A worker.) The reports a sent zip held, oldest first: [(report id, its report.txt, [QImage])], each picture
    scaled down to `width` device pixels when wider. Only `reports/<id>/report.txt` and its `.png`s are read."""
    from PyQt6.QtGui import QImage
    found = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            parts = name.split("/")
            if len(parts) != 3 or parts[0] != core.REPORTS_DIR or not parts[1]:
                continue
            entry = found.setdefault(parts[1], {"text": "", "pictures": []})
            if parts[2] == "report.txt":
                entry["text"] = z.read(name).decode("utf-8", errors="replace")
            elif parts[2].lower().endswith(".png"):
                entry["pictures"].append(name)
        out = []
        for rid in sorted(found):
            images = []
            for name in sorted(found[rid]["pictures"], key=_picture_order):
                img = QImage.fromData(z.read(name), "PNG")
                if img.isNull():
                    continue
                if img.width() > width:
                    img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
                images.append(img)
            out.append((rid, found[rid]["text"], images))
    return out


def _picture_order(name):
    """picture-2.png before picture-10.png."""
    digits = re.findall(r"\d+", os.path.basename(name))
    return (int(digits[-1]) if digits else 0, name)


def _send_words(result):
    """The status line's words for a send's Result (SPEC §3)."""
    o = result.outcome
    if o == send_report.SENT:
        return strings.REPORT_SENT_ID.format(id=result.id)
    if o == send_report.LIMIT:
        return strings.REPORT_SEND_LIMIT
    if o == send_report.OFFLINE:
        return strings.REPORT_SEND_OFFLINE
    if o == send_report.BUSY:
        return strings.REPORT_SEND_BUSY
    if o == send_report.TOO_BIG:
        return strings.REPORT_SEND_TOO_BIG
    if o == send_report.PAUSED:
        return strings.REPORT_SEND_PAUSED
    return strings.REPORT_SEND_REFUSED.format(status=result.status or "?")


def show_zip(win, path, control=None):
    """A zip shown selected in its folder (Explorer's `/select,`), on a worker — never the window's thread."""
    if qpress.OFF_THREAD:
        qpress.run(control, f"report:show-zip:{path}", screens.show_in_folder, path, win=win,
                   failed=lambda _info: None)
        return
    try:
        screens.show_in_folder(path)
    except Exception:
        pass


def about_extra(win):
    """What about.txt says of the window: its scale, text size, theme and Qt's version."""
    from PyQt6.QtCore import QT_VERSION_STR
    try:
        theme_name, size = style.current()
    except Exception:
        theme_name, size = "?", "?"
    return {"screen scale": f"{round(win.devicePixelRatioF() * 100)} %", "theme": theme_name, "text size": size,
            "qt": QT_VERSION_STR}


def _count_again(shell):
    button = getattr(shell, "report_button", None)
    if button is not None:
        try:
            button.refresh()
        except RuntimeError:
            pass


def _where(shell):
    """The tab the main window shows (a report's *Where*), or ""."""
    try:
        return strings.REPORT_WHERE.format(tab=shell.current_tab())
    except Exception:
        return ""


def library_summary(shell):
    """(The window's thread; nothing read from disk.) The library's counts and its source folders as the window shows
    them (each folder's path, on or off, its item count, reachable) — no title, no file name."""
    out = {"language": windows.language_of(shell)}
    library = getattr(getattr(shell, "services", None), "library", None)
    view = None
    try:
        view = library.view() if library is not None else None
    except Exception as e:                                         # said as it is, never as "none open"
        out["library"] = f"couldn't be read: {e}"
        view = None
    if view is not None:
        counts = getattr(view, "counts", None)
        out["counts"] = counts._asdict() if hasattr(counts, "_asdict") else counts
        out["state"] = getattr(view, "state", None)
        out["mode"] = getattr(view, "mode", None)
    elif "library" not in out:
        out["library"] = "none open"
    out["sources"] = [{k: s.get(k) for k in ("id", "path", "on", "items", "reachable")}
                      for s in (getattr(shell, "sources", None) or ()) if isinstance(s, dict)]
    return out


def _thumbnails(paths, width):
    """(A worker.) Each saved picture read and scaled to `width` device pixels: [(path, QImage)] (a null image for one
    that can't be read)."""
    from PyQt6.QtGui import QImage
    out = []
    for path in paths:
        img = QImage(path)
        if not img.isNull():
            img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        out.append((path, img))
    return out


def QIcon_from(pixmap):
    from PyQt6.QtGui import QIcon
    return QIcon(pixmap)


def _when(iso):
    """'2026-10-24 21:05' from an ISO time (the list's and a note's)."""
    return (iso or "").replace("T", " ")[:16]
