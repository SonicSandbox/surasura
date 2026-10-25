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
  it*, *Make the zip* into Downloads or a folder picked, *Include my last lists*, and the hint to send it to Sonic.
  Every read and write of the list, its pictures and the zip runs on a worker; the zip's folder opens once it is
  written. What the tester typed and didn't save is kept while Surasura runs (`DRAFT`): Esc never loses it.
"""
import os
import re

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, QStandardPaths, Qt
from PyQt6.QtGui import QFontMetrics, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem,
                             QPlainTextEdit, QPushButton, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
                             QWidget)

from app import report as core
from app import theme
from app.qt import bridge, rows, strings, style
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
        first = getattr(shell, "first_frame", None)
        if first is not None:                                     # the count read after the first frame, on a worker
            first.connect(self.refresh)

    def refresh(self):
        bridge.run_in_worker(core.count, then=self.set_count, failed=lambda _info: None)

    def set_count(self, n):
        """-> True when the count changed (repainted only then)."""
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
        self.update()

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
    field drawn as dots while it is taken (`key_fields`: a shown Jiten key never in a picture). -> [QImage] (the main
    window's first). Thread-safe images: encoded on the worker at Save."""
    out = []
    for w in surasura_windows(shell):
        try:
            fields = [(f, f.echoMode()) for f in key_fields(w)]
            for f, _mode in fields:
                f.setEchoMode(QLineEdit.EchoMode.Password)
            try:
                img = w.grab().toImage()
            finally:
                for f, mode in fields:
                    f.setEchoMode(mode)
        except RuntimeError:                                       # a window deleted meanwhile
            continue
        if not img.isNull():
            out.append(img)
    return out


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
    pictures = take_pictures(shell)
    win = windows.opened(shell, NAME)
    if win is not None:
        win.set_pictures(pictures)
    return windows.show(shell, NAME, lambda s: ReportWindow(s, pictures))


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
        shown = self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        if shown != self.text():
            self.setText(shown)


# --- the window --------------------------------------------------------------------------------------------------- #
class ReportWindow(SecondaryWindow):
    FORM, OPENED, CONTENTS = 0, 1, 2

    def __init__(self, shell, pictures=()):
        super().__init__(shell, strings.REPORT_WINDOW_NAME)
        self.pictures = list(pictures)
        self.reports = None                                       # the list as last read (None: not read yet)
        self.opened_id = None
        self.list_paints = 0
        self.dest = downloads()
        self.last_removed = None
        self._thumbs = None                                       # the form's thumbnails, made once per set of pictures
        f = theme.text_factor(style.current()[1])
        self.pages = QStackedWidget(self)
        self.body.addWidget(self.pages, 1)
        self.pages.addWidget(self._form_page())
        self.pages.addWidget(self._opened_page())
        self.pages.addWidget(self._contents_page())
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
        self.hint = self._line(strings.REPORT_HINT)
        self.body.addWidget(self.hint)
        self.setMinimumWidth(round(560 * f))
        self._show_pictures()
        self._restore_draft()
        self.read()

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

    def _send_row(self):
        box = QVBoxLayout()
        where = QHBoxLayout()
        self.dest_line = self._line("")
        where.addWidget(self.dest_line, 1)
        self.change_button = self._button(strings.REPORT_CHANGE, strings.REPORT_CHANGE_TIP, self.pick_folder, where)
        box.addLayout(where)
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
                                       "primary", presses=True)
        self.zip_button.setEnabled(False)
        self.show_button.setEnabled(False)
        box.addLayout(row)
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
            self.set_pictures(draft["pictures"])

    def _keep_draft(self):
        what, expected = self.what.toPlainText(), self.expected.toPlainText()
        if what.strip() or expected.strip():
            setattr(self.shell, DRAFT, {"what": what, "expected": expected, "leave_out": self.leave_out.isChecked(),
                                        "pictures": list(self.pictures)})
        else:
            setattr(self.shell, DRAFT, None)

    def closeEvent(self, event):
        try:
            self._keep_draft()                                     # Esc or ✕: the words wait for the next press
        except RuntimeError:
            pass
        super().closeEvent(event)

    # --- the pictures ------------------------------------------------------------------------------------------ #
    def set_pictures(self, pictures):
        """The bug pressed again with the window open: the new pictures for the next report."""
        self.pictures = list(pictures)
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
            b.setAccessibleName(f"{text}: {title}")
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(slot)
            box.addWidget(b)
        return w

    def _form_changed(self):
        self.save_button.setEnabled(bool(self.what.toPlainText().strip()))

    # --- the presses ------------------------------------------------------------------------------------------- #
    def save(self):
        what = self.what.toPlainText().strip()
        if not what or not self.save_button.isEnabled():
            return
        expected = self.expected.toPlainText()
        images = [] if self.leave_out.isChecked() else list(self.pictures)
        sent = (self.what.toPlainText(), expected, self.pictures)
        where = _where(self.shell)

        def work():
            return core.save(what, expected, [png_bytes(i) for i in images], where=where)
        qpress.run(self.save_button, "report:save", work, win=self, then=self.alive(lambda r: self._saved(r, sent)),
                   failed=self.alive(lambda info: self.say(strings.REPORT_SAVE_FAILED.format(why=info[0]))))

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
        self.opened_id = None
        self.pages.setCurrentIndex(self.FORM)
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

    def make_zip(self):
        if not self.reports:
            return
        language, include, dest = self.language, self.include_results.isChecked(), self.dest
        library = library_summary(self.shell)

        shell = self.shell
        extra = about_extra(self)

        def made(path):
            words = strings.REPORT_ZIPPED.format(name=os.path.basename(path), folder=dest)
            if self.gone:                                          # closed while it was made: the main window says it
                windows.say_in_bar(shell, words)
                _count_again(shell)
                try:
                    qpress.open(shell, os.path.dirname(path), key="report:open-folder")
                except RuntimeError:
                    pass
                return
            self._hold(False)
            self.last_removed = None
            self.say_undo(False)
            self.back()
            self.read(then_say=words)
            qpress.open(self, os.path.dirname(path), key="report:open-folder")

        def broke(info):
            words = strings.REPORT_ZIP_FAILED.format(why=info[0])
            if self.gone:
                windows.say_in_bar(shell, words)
                return
            self._hold(False)
            self.say(words)
        self._hold(True)
        p = qpress.run(self.zip_button, "report:zip", core.make_zip, dest, language, include, library, None, extra,
                       win=self, then=made, failed=broke)
        if p is None:
            self._hold(False)

    def _hold(self, on):
        """While the zip is made: the list, a note and Undo wait (a report changed meanwhile would be kept anyway)."""
        self.list.setEnabled(not on)
        self.note_button.setEnabled(not on)
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(not on)


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
