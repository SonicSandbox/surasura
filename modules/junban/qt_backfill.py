# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill on the 3.0 line (W3.4 row 5): the Tk window (`backfill_gui.py`, Patterns_Spec.md §17) in Qt — the main
window, its Fields window and its パターン data window. It paints what `backfill_view.py` decides and runs the engine
(`backfill.py`) off its thread:

    probe  ->  PREVIEW  ->  Fill        (and Restore)

* **The preview is the confirmation.** Fill stays off until a preview of the choices and language on screen has
  something to write; any choice throws the preview away; a preview that lands after a choice changed is dropped. Fill
  still asks once, its default the action (the preview showed it); Restore asks with **Cancel as the default** (Enter,
  Esc, Back, ✕ and a click outside all leave Anki as it is: 🧭 IK-10c, the Anki window's rule).
* **Every Fill and Restore is a `backfill` job** (the bottom bar shows it; 順's reorder, Connect's mining and the
  re-plan wait for it in this process, `anki_connect.take_writer` across processes); closing the window while it waits
  for another writer writes nothing.
* **`backfill-window` is held for the window's life** (taken and let go on a worker): `surasura-cli backfill` stands
  aside meanwhile.
* **The window's thread waits for nothing:** Anki, the databases (SQLite), the token store, the library build and
  the download run on workers; what the buttons need (`data_ready`, `general_ready`, the rebuild tooltip) is read on a
  worker and kept (inv defect 1). The preview table is a model and a view (up to 4,000 rows, filled in one reset),
  with a line saying how many more there are (inv defect 2).
* **It follows the main window's language when idle** (🧭 IK-12, the Tk window's tested behaviour): the preview goes,
  what is offered is read again, the session is made again for the new language on its next use.
"""
import json
import os
import threading

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
                             QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
                             QRadioButton, QTableView)

from app import anki_connect, theme
from app.qt import bridge, confirm, motion, style, windows
from app.qt import press as qpress
from app.services import jobs
from app.services.settings import thaw
from modules.junban import backfill, patterns_package
from modules.junban import backfill_view as V
from modules.junban import qt_strings as S

NAME = "backfill"
FIELDS_NAME = "backfill-fields"
DATA_NAME = "backfill-data"
POLL_MS = 250                      # the background build's line, looked at while a build runs (a state, not a motion)
COLUMN_WIDTHS = (110, 70, 110)     # Word · Fill · Result; What goes in takes the rest
MAX_MESSAGES = 3                   # the status line keeps the newest few (the Tk pane's three lines)


def open_window(shell):
    """The one Backfill window of `shell`: opened, or raised when open."""
    return windows.show(shell, NAME, BackfillWindow)


def _factor():
    return theme.text_factor(style.current()[1])


class PreviewModel(QAbstractTableModel):
    """The preview, as rows `(word, fill, result, what goes in, writes)`: set in one reset, never row by row; rows that
    write nothing in the faint ink."""

    COLUMNS = (S.BF_COL_WORD, S.BF_COL_FILL, S.BF_COL_RESULT, S.BF_COL_VALUE)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.resets = 0

    def set_rows(self, rows):
        if not rows and not self.rows:
            return
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()
        self.resets += 1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 3 and row[3]:
            return row[3]
        if role == Qt.ItemDataRole.ForegroundRole and not row[4]:
            return style.qcolor(style.colours()["ink-faint"])
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None


class BackfillWindow(windows.SecondaryWindow):
    """The window. Its controls are built once; a choice repaints only what it changes."""

    def __init__(self, shell):
        super().__init__(shell, S.BF_TITLE)
        self.services = shell.services
        self.relay = bridge.Relay(self)
        self.relay.said.connect(self.alive(self._said))       # closed: no line wakes anything (AD5-7)
        self.stop = threading.Event()        # set at close: a Fill or Restore still waiting for another writer stops
        self.keeper = V.SessionKeeper()
        self.lock = V.WindowLock()
        self.watch = V.BuildWatch()
        self.choices = V.Choices.from_settings(self._saved())
        self.ready = None                    # V.Readiness for the language on screen, once a worker read it
        self.working = False                 # a worker job (a probe, a preview, a build, an install) or a write runs
        self.connected = False
        self.auto_previewed = False
        self.preview_wanted = False          # a choice changed while a job ran: preview when it ends
        self.preview = None                  # the preview on screen (backfill.preview's result)
        self.preview_key = None              # the choices and language it was made for; None = no preview
        self.models = {}                     # the deck's note types, from the last preview
        self.job = None                      # the Fill / Restore job while it runs
        self.question = None                 # the last Fill / Restore confirmation; open while its answer is None
        self.messages = []
        self._job_line = None                # the job's own line (waiting its turn / writing), dropped at its end
        self._job_state = None               # (state, reason) of the job as last said
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._watch_build)
        heard = getattr(shell, "bridge", None)
        if heard is not None:
            heard.jobs_changed.connect(self.alive(self._follow))
        self._sync()
        bridge.run_in_worker(self.lock.hold)
        self._read_readiness()
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            if not os.environ.get("SURASURA_NO_ANKI_SYNC"):
                QTimer.singleShot(0, self.alive(self.refresh_connection))
            QTimer.singleShot(0, self.alive(self._rebuild_if_grown))
        self._watch_build()

    # --- building ---------------------------------------------------------------------------------------------- #
    def _button(self, text, tip, slot, parent=None, name=None, kind=None):
        b = QPushButton(text, parent or self)
        b.setToolTip(tip)
        b.setAccessibleName(name or text)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _label(self, text, name="windowline", tip=None):
        label = QLabel(text, self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        if tip:
            label.setToolTip(tip)
        return label

    def _mark(self, text, name):
        """A "?" or "ⓘ": a word-less mark whose tooltip explains (rich text), reached by Tab, named for a reader."""
        mark = QLabel(text, self)
        mark.setObjectName("backfillmark")
        mark.setAccessibleName(name)
        mark.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        mark.setCursor(Qt.CursorShape.WhatsThisCursor)
        return mark

    def _build(self):
        f = _factor()
        head = QHBoxLayout()
        head.addWidget(self._label(S.BF_TITLE, "windowheading", S.BF_TITLE_TIP))
        head.addStretch(1)
        self.conn = self._label(S.BF_CONN_UNCHECKED, "backfillconnection", S.BF_CONN_TIP)
        self.conn.setAccessibleName(S.BF_CONN_TIP)
        head.addWidget(self.conn)
        self.btn_recheck = self._button(S.BF_RECHECK, S.BF_RECHECK_TIP, self.refresh_connection,
                                        name=S.BF_RECHECK_NAME)
        head.addWidget(self.btn_recheck)
        self.body.addLayout(head)

        scope = QHBoxLayout()
        scope.addWidget(self._label(S.BF_DECK))
        self.deck_box = QComboBox(self)
        self.deck_box.setToolTip(S.BF_DECK_TIP)
        self.deck_box.setAccessibleName(S.BF_DECK)
        self.deck_box.setMinimumContentsLength(18)
        self._set_decks([])
        self.deck_box.activated.connect(self._on_deck)            # the user's pick only, never a refill
        scope.addWidget(self.deck_box)
        scope.addSpacing(round(18 * f))
        scope.addWidget(self._label(S.BF_CARDS))
        self.cards_group = QButtonGroup(self)
        self.radios = {}
        for value, text, tip in (("all", S.BF_CARDS_ALL, S.BF_CARDS_ALL_TIP),
                                 ("new", S.BF_CARDS_NEW, S.BF_CARDS_NEW_TIP)):
            radio = QRadioButton(text, self)
            radio.setToolTip(tip)
            radio.setProperty("kind", "choice")
            radio.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            radio.setChecked(self.choices.cards == value)
            radio.clicked.connect(lambda _c=False, v=value: self._on_cards(v))
            self.cards_group.addButton(radio)
            self.radios[value] = radio
            scope.addWidget(radio)
        scope.addSpacing(round(18 * f))
        self.chk_replace = QCheckBox(S.BF_REPLACE, self)
        self.chk_replace.setToolTip(S.BF_REPLACE_TIP)
        self.chk_replace.setProperty("kind", "toggle")
        self.chk_replace.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.chk_replace.setChecked(self.choices.replace)
        self.chk_replace.clicked.connect(self._on_replace)
        scope.addWidget(self.chk_replace)
        scope.addStretch(1)
        self.body.addLayout(scope)

        self.checks, self.help_marks, self.targets = {}, {}, {}
        self.btn_copy = self.btn_get_data = self.btn_rebuild = None
        for fill in backfill.FILLS:
            self.body.addWidget(style.separator(self))
            row = QHBoxLayout()
            check = QCheckBox(fill.label, self)
            check.setProperty("kind", "toggle")
            check.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            check.setChecked(fill.key in self.choices.fills)
            check.clicked.connect(lambda on, k=fill.key: self._on_fill_tick(k, on))
            self.checks[fill.key] = check
            row.addWidget(check)
            mark = self._mark(S.BF_HELP_MARK, S.BF_HELP_NAME.format(fill=fill.label))
            self.help_marks[fill.key] = mark
            row.addWidget(mark)
            row.addStretch(1)
            if fill.key == "patterns":
                self.btn_rebuild = qpress.room(self._button(S.BF_REBUILD, S.BF_REBUILD_TIP, self.on_rebuild))
                self.btn_rebuild.setVisible(False)
                row.addWidget(self.btn_rebuild)
                self.btn_get_data = self._button(S.BF_GET_DATA, S.BF_GET_DATA_TIP, self.on_get_data)
                self.btn_get_data.setVisible(False)
                row.addWidget(self.btn_get_data)
            target = self._button(S.BF_TARGET_NONE, S.BF_TARGET_TIP, lambda f=fill: self.on_fields(f))
            self.targets[fill.key] = target
            row.addWidget(target)
            if fill.key == "patterns":
                self.btn_copy = self._button(S.BF_COPY_STYLE, S.BF_COPY_STYLE_TIP, self.on_copy_style)
                row.addWidget(self.btn_copy)
            self.body.addLayout(row)
        # Translations (Piyo-TR): how many cards have none, and the next step — counted on a worker, never an AI call
        self.tr_sep = style.separator(self)
        self.body.addWidget(self.tr_sep)
        row = QHBoxLayout()
        self.tr_line = self._label("", "windowline")
        self.tr_line.setWordWrap(True)
        row.addWidget(self.tr_line, 1)
        self.btn_tr_copy = self._button(S.BF_TR_COPY, S.BF_TR_COPY_TIP, self.on_copy_translate)
        row.addWidget(self.btn_tr_copy)
        self.body.addLayout(row)
        self.tr_count = None
        self._show_translations(None)
        self.body.addWidget(style.separator(self))

        line = QHBoxLayout()
        self.summary = self._label("", "backfillsummary")
        line.addWidget(self.summary)
        self.details = self._mark(S.BF_DETAILS_MARK, S.BF_DETAILS_NAME)
        self.details.setVisible(False)
        line.addWidget(self.details)
        self.spinner = motion.Spinner("spin", self)
        self.spinner.setVisible(False)
        line.addWidget(self.spinner)
        line.addStretch(1)
        self.build_line = self._label("", "windowline")
        line.addWidget(self.build_line)
        self.body.addLayout(line)

        self.model = PreviewModel(self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setAccessibleName(S.BF_TABLE_NAME)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setCornerButtonEnabled(False)
        for corner in self.table.findChildren(QAbstractButton):     # Qt's own select-all corner: hidden with the row
            corner.setToolTip(S.BF_TABLE_NAME)                      # numbers, named for the walk and a reader
            corner.setAccessibleName(S.BF_TABLE_NAME)
        rows = self.table.verticalHeader()
        rows.setVisible(False)
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        rows.setDefaultSectionSize(round(24 * f))
        columns = self.table.horizontalHeader()
        columns.setHighlightSections(False)
        for i, width in enumerate(COLUMN_WIDTHS):
            columns.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, round(width * f))
        columns.setSectionResizeMode(len(COLUMN_WIDTHS), QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(round(220 * f))
        self.body.addWidget(self.table, 1)
        self.more = self._label("", "windowline")
        self.more.setVisible(False)
        self.body.addWidget(self.more)

        self.bar = QProgressBar(self)
        self.bar.setAccessibleName(S.BF_PROGRESS_NAME)
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setFixedHeight(round(6 * f))
        self.body.addWidget(self.bar)

        actions = QHBoxLayout()
        self.btn_preview = self._button(S.BF_PREVIEW, S.BF_PREVIEW_TIP, self.on_preview)
        actions.addWidget(self.btn_preview)
        actions.addStretch(1)
        self.btn_restore = self._button(S.BF_RESTORE, S.BF_RESTORE_TIP, self.on_restore)
        actions.addWidget(self.btn_restore)
        self.btn_fill = self._button(S.BF_FILL, S.BF_FILL_TIP, self.on_fill, kind="primary")
        actions.addWidget(self.btn_fill)
        self.body.addLayout(actions)
        self.resize(round(780 * f), round(660 * f))

    # --- settings ---------------------------------------------------------------------------------------------- #
    def _saved(self):
        return thaw(self.services.settings.get())

    def _engine(self):
        return V.engine_settings(self._saved(), self.language, self.choices)

    def _on_choice(self, choices):
        """Any choice changes what a fill would write: saved (only the keys it changed), the preview goes, a new one
        follows (`_on_choice`)."""
        changes = choices.changed(self.choices)
        self.choices = choices
        self._clear_preview()
        if changes:
            self.services.settings.set(changes)
        self._sync()
        self._want_preview()

    def _on_deck(self, index):
        text = self.deck_box.itemText(index)
        self._on_choice(self.choices.but(deck="" if text == S.BF_ALL_DECKS else text))

    def _on_cards(self, value):
        self._on_choice(self.choices.but(cards=value))

    def _on_replace(self, checked):
        self._on_choice(self.choices.but(replace=bool(checked)))

    def _on_fill_tick(self, key, checked):
        fills = [k for k in backfill.FILL_KEYS if (k == key and checked) or (k != key and k in self.choices.fills)]
        self._on_choice(self.choices.but(fills=fills))

    def on_mapping(self, fill_key, model, label):
        """The Fields window: one note type's field for one fill — saved, shown on the fill's button, previewed."""
        choices, self.models = V.with_mapping(self.choices, self.models, fill_key, model, label)
        self._show_targets()
        self._on_choice(choices)

    def on_note_language(self, model, label):
        """The Fields window: one note type's language — saved and previewed; "Language?" unsets it."""
        choices, self.models = V.with_note_language(self.choices, self.models, model, label)
        self._on_choice(choices)

    # --- state ------------------------------------------------------------------------------------------------- #
    def _ready(self):
        ready = self.ready
        return ready if ready is not None and ready.language == self.language else None

    def _needs_build(self):
        ready = self._ready()
        return ready is not None and V.needs_build(self.choices, self.language, ready.data)

    def _asking(self):
        """A Fill or Restore question is open: nothing else starts under it (AD5-3) — not a probe, a preview, an
        install, nor a finished build's swap that would take the window busy and drop the user's "yes"."""
        question = self.question
        return question is not None and question.answer is None

    def _busy(self):
        return self.working or self._asking()

    @staticmethod
    def _set_text(widget, text):
        if widget.text() != text:
            widget.setText(text)

    @staticmethod
    def _set_tip(widget, tip):
        if widget.toolTip() != tip:
            widget.setToolTip(tip)

    @staticmethod
    def _show(widget, on):
        if widget.isHidden() == bool(on):
            widget.setVisible(bool(on))

    def _sync(self):
        """Every control's state from the window's (`_sync_buttons`): nothing here reads a file."""
        language, idle, ready = self.language, not self._busy(), self._ready()
        for fill in backfill.FILLS:
            available = V.offered(fill, language)
            check = self.checks[fill.key]
            if check.isEnabled() != available:
                check.setEnabled(available)
            self._set_tip(check, V.fill_tip(fill, language))
            self._set_tip(self.help_marks[fill.key], V.help_html(backfill.help_for(fill, language)))
            self.targets[fill.key].setEnabled(bool(self.models) and available)
        text, tip = V.preview_button(self._needs_build())
        self._set_text(self.btn_preview, text)
        self._set_tip(self.btn_preview, tip)
        if self.btn_preview.accessibleName() != text:
            self.btn_preview.setAccessibleName(text)
        self.btn_preview.setEnabled(idle and ready is not None)
        self.btn_restore.setEnabled(idle)
        self.btn_recheck.setEnabled(idle)
        self.btn_fill.setEnabled(V.fill_ready(not idle, self.preview_key, self.choices.key(language),
                                              self.preview))
        self._show(self.btn_get_data, ready is not None and V.show_get_data(language, ready.general))
        self.btn_get_data.setEnabled(idle)
        self._show(self.btn_rebuild, ready is not None and V.show_rebuild(language, ready.data))
        self.btn_rebuild.setEnabled(not backfill.building())
        if ready is not None:
            self._set_tip(self.btn_rebuild, ready.tip)
        data = windows.opened(self, DATA_NAME)
        if data is not None:
            data.set_idle(idle)

    def _read_readiness(self):
        """What the buttons need, read on a worker (SQLite, the token store) and kept for the language asked about."""
        language = self.language
        bridge.run_in_worker(V.read_readiness, language, then=self.alive(self._readiness_read))

    def _readiness_read(self, ready):
        if ready is None or ready.language != self.language:
            return
        self.ready = ready
        self._sync()
        self._maybe_preview()

    def _set_decks(self, decks):
        values = [S.BF_ALL_DECKS] + list(decks or [])
        current = self.choices.deck or S.BF_ALL_DECKS
        if current not in values:
            values.append(current)
        if [self.deck_box.itemText(i) for i in range(self.deck_box.count())] == values:
            return
        self.deck_box.blockSignals(True)
        self.deck_box.clear()
        self.deck_box.addItems(values)
        self.deck_box.setCurrentIndex(values.index(current))
        self.deck_box.blockSignals(False)

    def _show_targets(self):
        for fill in backfill.FILLS:
            self._set_text(self.targets[fill.key], V.target_text(fill, self.models))

    def _set_working(self, on):
        self.working = bool(on)
        self.spinner.setVisible(self.working)
        self.spinner.set_running(self.working)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self._sync()

    def _write(self, text):
        if not text:
            return
        self.messages = (self.messages + [str(text)])[-MAX_MESSAGES:]
        self.say("\n".join(self.messages))

    def _clear_messages(self):
        self.messages = []
        self._job_line = None
        self.say("")

    def _set_job_line(self, text):
        """The write's own line — waiting its turn, then writing — in place of the one before; None drops it."""
        if self._job_line is not None and self._job_line in self.messages:
            self.messages.remove(self._job_line)
        self._job_line = text or None
        if text:
            self.messages = (self.messages + [text])[-MAX_MESSAGES:]
        self.say("\n".join(self.messages))

    def _clear_preview(self):
        self.preview, self.preview_key = None, None
        self.model.set_rows([])
        self._set_text(self.summary, "")
        self._show(self.more, False)
        self._show(self.details, False)

    # --- the workers --------------------------------------------------------------------------------------------- #
    def _start(self, fn, *args, then=None):
        """`fn(*args)` on a worker, the window busy meanwhile; `then(value)` (else the usual follow-ups) at its end."""
        self._set_working(True)
        bridge.run_in_worker(self._guarded(fn), *args, then=self.alive(lambda value: self._done(value, then)))

    def _guarded(self, fn):
        def run(*args):
            try:
                return fn(*args)
            except Exception as e:
                self.relay.call(("message", S.BF_UNEXPECTED.format(e=e)))
                return None
            finally:
                if self.gone:                   # closed meanwhile: the session goes with the last worker
                    self.keeper.close()
        return run

    def _done(self, value, then):
        self._set_working(False)
        if then is not None:
            then(value)
        else:
            self._after_job()

    def _after_job(self):
        if self.gone:                            # a job that ended as the window closed starts nothing (AD5-7)
            return
        self._maybe_preview()
        self._watch_build()

    def _maybe_preview(self):
        if (self.preview_wanted and self.connected and not self._busy() and self._ready() is not None
                and not self._needs_build()):
            self._preview_now()

    def _said(self, item):
        """A worker's line, on the window's thread (the Tk queue's tags)."""
        tag = item[0]
        if tag == "message":
            self._write(item[1])
        elif tag == "summary":
            self._set_text(self.summary, item[1])
        elif tag == "progress":
            self.bar.setRange(0, max(1, item[2]))
            self.bar.setValue(item[1])
        elif tag == "conn":
            self._on_connection(item[1], item[2])
        elif tag == "preview":
            self._show_preview(item[1], item[2], item[3])
        elif tag == "built":
            self._on_built(*item[1:])
        elif tag == "installed":
            self._write(S.BF_INSTALLED.format(names=", ".join(item[1])))
            self._set_text(self.summary, "")
            self.preview_wanted = True
            self._read_readiness()
        elif tag == "written":
            self._on_written(item[1])
        elif tag == "translations":
            self._show_translations(*item[1:])

    def _status(self, line):
        """A slow step's line on the summary, and its numbers on the bar (a worker's call)."""
        self.relay.call(("summary", line))
        numbers = V.status_numbers(line)
        if numbers:
            self.relay.call(("progress",) + numbers)

    def _progress(self, done, total):
        self.relay.call(("progress", done, total))

    # --- Anki ---------------------------------------------------------------------------------------------------- #
    def refresh_connection(self):
        if self._busy():
            return
        self._set_text(self.conn, S.BF_CONN_CHECKING)
        self._start(self._probe_worker, self._engine())

    def _probe_worker(self, settings):
        url = backfill._url(settings)
        report = anki_connect.probe(url, required=backfill.REQUIRED_ACTIONS)
        decks = []
        if report.get("ok"):
            try:
                decks = sorted(anki_connect.deck_names(url))
            except Exception as e:
                self.relay.call(("message", S.BF_DECKS_FAILED.format(e=e)))
        self.relay.call(("conn", report, decks))
        if report.get("ok"):
            self._translations_worker(settings, self.language)

    def _on_connection(self, report, decks):
        self.connected = bool(report.get("ok"))
        if self.connected:
            version = report.get("version")
            self._set_text(self.conn, S.BF_CONN_OK_VERSION.format(version=version) if version else S.BF_CONN_OK)
            self._set_decks(decks)
        else:
            self._set_text(self.conn, S.BF_CONN_NO)
            self._write(S.BF_START_ANKI)
            self._show_translations(None)
        state = "ok" if self.connected else "bad"
        if self.conn.property("state") != state:
            self.conn.setProperty("state", state)
            self.conn.style().unpolish(self.conn)
            self.conn.style().polish(self.conn)
        self._sync()
        if V.auto_preview_due(self.connected, self.auto_previewed, os.environ):
            self.auto_previewed = True
            self.preview_wanted = True

    def on_preview(self):
        """Preview — or "Build & preview" while there is nothing to fill from yet (never started by itself)."""
        if self._busy() or self._ready() is None:
            return
        self._clear_messages()
        if self._needs_build():
            self._clear_preview()
            self._set_text(self.summary, S.BF_SUMMARY_BUILDING)
            self._start(self._build_worker, self.language, self._saved().get("reinforce_segmentation") is True)
            return
        self._preview_now()

    def _want_preview(self):
        """After a choice: a new preview now, or when the job running ends — the latest choices win."""
        if not self.connected or self._needs_build():
            return
        if self._busy() or self._ready() is None:
            self.preview_wanted = True
        else:
            self._preview_now()

    def _preview_now(self):
        self.preview_wanted = False
        self._clear_preview()
        choices = self.choices
        settings, key = self._engine(), choices.key(self.language)
        self._set_text(self.summary, S.BF_SUMMARY_READING)
        self._start(self._preview_worker, settings, key, choices)

    def _preview_worker(self, settings, key, choices):
        """The preview, and its rows made for the table here, never on the window's thread (AD5-1)."""
        try:
            result = backfill.preview(settings, self.keeper.get(settings), status=self._status)
        except anki_connect.AnkiError as e:
            self.relay.call(("message", str(e)))
            self.relay.call(("summary", ""))
            return
        self.relay.call(("preview", result, key, V.shown(result, choices)))
        self._translations_worker(settings, self.language)    # the deck may have changed: its count (no worker of its own)

    def _show_preview(self, result, key, shown):
        """One preview, as its worker made it (`V.shown`) — unless the choices or the language changed while it ran:
        then it describes other cards."""
        if key != self.choices.key(self.language):
            return
        self.models = shown.models
        self._show_targets()
        self.model.set_rows(shown.rows)
        self._set_text(self.more, S.BF_MORE_ROWS.format(n=f"{shown.more:,}") if shown.more else "")
        self._show(self.more, shown.more > 0)
        self._set_text(self.summary, shown.summary)
        self.preview, self.preview_key = result, key
        self._show(self.details, bool(shown.details))
        self._set_tip(self.details, shown.details)
        self._sync()

    # --- Fill and Restore ---------------------------------------------------------------------------------------- #
    def _ask(self, title, body, yes, yes_tip, on_answer, **kwargs):
        """A Fill or Restore question: the window counts as busy while it is open, and when it goes — answered, or
        dropped by a hide (`hideEvent`) — what waited for it (a preview, a finished build's swap) follows."""
        def answered(said):
            on_answer(said)
            self._question_gone()
        self.question = confirm.ask(self, title, body, yes, yes_tip, on_answer=answered, **kwargs)
        self._sync()

    def _question_gone(self):
        self.question = None
        self._sync()
        self._after_job()

    def hideEvent(self, event):
        """A hide drops an open question with no answer (confirm.py): the window stops waiting for it."""
        super().hideEvent(event)
        if self.question is not None and not self._asking():
            QTimer.singleShot(0, self.alive(self._question_gone))

    def on_fill(self):
        if not V.fill_ready(self._busy(), self.preview_key, self.choices.key(self.language), self.preview):
            return
        planned, language = self.preview, self.language
        count = len(planned["edits"])
        title = (S.BF_ASK_FILL_ONE if count == 1 else S.BF_ASK_FILL_MANY).format(n=count)
        self._ask(title, S.BF_ASK_FILL_LINE, S.BF_ASK_FILL_YES, S.BF_ASK_FILL_YES_TIP,
                  on_answer=lambda yes: self._fill_answered(planned, language, yes))

    def _fill_answered(self, planned, language, yes):
        """Fill, if the preview it was asked about is still the one on screen and nothing runs; a "yes" the window can
        no longer honour says so (never silence)."""
        if not yes:
            return
        if self.preview is not planned or not V.fill_ready(
                self._busy(), self.preview_key, self.choices.key(self.language), self.preview):
            self._write(S.BF_LOOK_AGAIN if language != self.language else S.BF_PREVIEW_CHANGED)
            return
        settings = self._engine()
        self._write_job(S.BF_JOB_FILL, V.fill_work(settings, self.keeper, planned, self.stop, self._waiting,
                                                   self._progress))

    def on_restore(self):
        if self._busy():
            return
        self._clear_messages()
        self._start(V.restore_plan, self.language, then=self._restore_planned)

    def _restore_planned(self, plan):
        if plan is None or plan.language != self.language:
            self._after_job()
            return
        if plan.kind == "nothing":
            self._write(S.BF_NOTHING_FILLED)
            self._after_job()
            return
        self._ask(plan.title(), plan.line, S.BF_ASK_RESTORE_YES, S.BF_ASK_RESTORE_YES_TIP, default_no=True,
                  on_answer=lambda yes: self._restore_answered(plan, yes))

    def _restore_answered(self, plan, yes):
        if not yes:
            return
        if plan.language != self.language:
            self._write(S.BF_LOOK_AGAIN)
            return
        if self._busy():
            self._write(S.BF_BUSY_LOOK_AGAIN)
            return
        self._write_job(S.BF_JOB_RESTORE, V.restore_work(plan, self._engine(), self.stop, self._waiting))

    def _write_job(self, label, work):
        """A Fill or a Restore: a `backfill` job; the language waits for it (never cut)."""
        self._clear_messages()
        self._set_working(True)
        self.begin_write()
        self._job_state = None
        self.job = V.submit_write(self.services.registry, label, work, self._job_ended, self.stop)
        if self.job is not None:
            self._follow(self.services.registry.snapshot())

    def _follow(self, views):
        """The registry's newest snapshot: while the write waits behind 順, mining or the re-plan, the window says what
        for; once it runs, that it writes (IK-75). Said again only when the job's state changed."""
        job = self.job
        if job is None:
            return
        view = next((v for v in views if v.id == job.id), None)
        if view is None or (view.state, view.reason) == self._job_state:
            return
        self._job_state = (view.state, view.reason)
        line = V.job_line(view.state, view.reason, view.label)
        if line is not None:
            self._set_job_line(line)

    def _job_ended(self, report):
        """(The job's thread — or the window's, when the close cancelled a job that never started.) Its report to the
        window; closed meanwhile, the session goes with it, never on the window's thread."""
        if self.gone:
            if threading.current_thread() is threading.main_thread():
                bridge.run_in_worker(self.keeper.close)
            else:
                self.keeper.close()
        self.relay.call(("written", report))

    def _on_written(self, report):
        self.job = None
        self._set_job_line(None)
        if report is None:
            line = S.BF_NOTHING_WRITTEN
            self._write(line)
        else:
            for problem in report.get("problems") or []:
                self._write(problem)
            line = report.get("message") or ""
            self._write(line)
        # What was on screen described the notes before this; a new look is one click away.
        self._clear_preview()
        self._set_working(False)
        self.end_write(line)
        self._after_job()

    def _waiting(self, holder):
        """Another Anki writer holds the lock: said once (a worker's call)."""
        self.relay.call(("message", anki_connect.waiting_line(holder)))

    # --- パターン data, the build ------------------------------------------------------------------------------ #
    def _build_worker(self, language, reinforce):
        """"Build & preview": the library's パターン built in its own process; the session goes after (its databases
        were the old ones); what the buttons need is read again."""
        try:
            result = V.build_library(language, reinforce, self._progress)
        except OSError as e:
            self.relay.call(("message", S.BF_BUILD_FAILED_START.format(e=e)))
            return
        if result is None:                       # never two builds at once
            self.relay.call(("message", S.BF_BUILD_BUSY))
            self.relay.call(("summary", ""))
            return
        self.keeper.close()
        self.relay.call(("built", language, result[0], result[1], V.read_readiness(language)))

    def _on_built(self, language, ok, last, ready):
        """A "Build & preview" ended. Built for another language than the one on screen now: nothing to say here (the
        window reads its own language's readiness) (AD5-10)."""
        self.bar.setValue(0)
        self._set_text(self.summary, "")
        if language != self.language:
            self._sync()
            return
        if ready is not None and ready.language == self.language:
            self.ready = ready
        if not ok:
            self._write(last or S.BF_BUILD_FAILED)
        elif self._needs_build():
            self._write(S.BF_BUILT_EMPTY)
        else:
            self.preview_wanted = True
        self._sync()

    def on_rebuild(self):
        """"Rebuild from my library": in the background, Preview and Fill reading the set in use meanwhile."""
        if backfill.building():
            return
        reinforce = self._saved().get("reinforce_segmentation") is True
        # round 8 row 45: its arc from the press, painted before the build is asked, until it has started (its own
        # quiet line then says it builds); a press meanwhile asks nothing
        qpress.run(self.btn_rebuild, "backfill:rebuild", V.rebuild_now, self.language, reinforce,
                   then=self.alive(self._rebuild_started),
                   failed=self.alive(lambda _info: self._rebuild_started("failed")), win=self)

    def _rebuild_started(self, outcome):
        if outcome == "deferred":
            self._write(S.BF_REBUILD_DEFERRED)
        elif outcome == "failed":
            self._write(S.BF_REBUILD_FAILED)
        self._watch_build()
        self._sync()

    def _rebuild_if_grown(self):
        """Opening the window: the library's set built again in the background once the library grew by a quarter —
        only while パターン is ticked and offered. Nothing waits for it."""
        if "patterns" in self.choices.fills and V.offered(backfill.FILLS[0], self.language):
            reinforce = self._saved().get("reinforce_segmentation") is True
            bridge.run_in_worker(backfill.rebuild_in_background, self.language, reinforce, True,
                                 then=self.alive(lambda _started: self._watch_build()))

    def _watch_build(self):
        """The background build's quiet line; when it ends, its new set goes in at the first idle moment (the session
        closed first, on a worker); a failure is said once. Looked at every POLL_MS only while a build runs."""
        line, started, ended = self.watch.step(backfill.background())
        self._set_text(self.build_line, line)
        if started or ended:
            self._sync()
        if ended:
            self._read_readiness()
        swap = self.watch.take_swap(self._busy())
        if swap is not None:
            self._start(V.promote_now, self.keeper, swap, then=lambda _went_in: (self._read_readiness(),
                                                                                  self._after_job()))
        note = backfill.failed_note()
        if note:
            self._write(note)
        running = self.watch.active() or backfill.building()
        if running and not self._timer.isActive():
            self._timer.start()
        elif not running and self._timer.isActive():
            self._timer.stop()

    def on_copy_style(self):
        QApplication.clipboard().setText(V.CARD_STYLE)
        self._write(S.BF_COPIED)

    def on_copy_translate(self):
        """The prompt names Backfill's deck when one is chosen: the AI translates the cards the line counted (r1 S8)."""
        deck = backfill._deck(self._engine())
        named = json.dumps(deck, ensure_ascii=False) if deck else None
        QApplication.clipboard().setText(S.BF_TR_PROMPT_DECK.format(deck=named) if deck else S.BF_TR_PROMPT)
        self._write(S.BF_TR_COPIED)

    def _translations_worker(self, settings, language):
        """How many cards in Backfill's deck have no translation (`card_translations.count`) — called on the
        connection check's worker and each preview's (a slot hands no work over but through a press)."""
        from app import card_translations
        deck = backfill._deck(settings)
        try:
            n = card_translations.count(card_translations.AnkiReads(backfill._url(settings)), deck or None, language)
        except Exception:
            n = None                            # Anki stopped answering: the line goes, nothing else says it
        self.relay.call(("translations", n, deck, language))

    def _show_translations(self, n, deck=None, language=None):
        if language is not None and (deck != backfill._deck(self._engine()) or language != self.language):
            return                              # a count for a deck or language no longer on screen (r1 N12)
        self.tr_count = n
        shown = bool(n)
        if shown:
            self._set_text(self.tr_line, S.BF_TR_COUNT.format(n=n))
        for w in (self.tr_sep, self.tr_line, self.btn_tr_copy):
            w.setVisible(shown)

    def on_fields(self, fill):
        """Where one fill goes, per note type — its own small window, one at a time."""
        open_now = windows.opened(self, FIELDS_NAME)
        if open_now is not None:
            if open_now.fill_key == fill.key:
                open_now.show()
                open_now.raise_()
                open_now.activateWindow()
                return
            open_now.close()
        if not self.models:
            return
        windows.show(self, FIELDS_NAME, lambda owner: FieldsWindow(owner, fill, V.fields_rows(fill, self.models)))

    def on_get_data(self):
        """Where パターン data comes from — its own small window, one at a time."""
        windows.show(self, DATA_NAME, DataWindow)

    def on_download(self):
        language, seen = self.language, [-1]

        def progress(done, total):
            """Bytes in, said once per MB (the worker's own count: AD5-5)."""
            line, mb = V.download_line(done, total)
            if mb != seen[0]:
                seen[0] = mb
                self._status(line)
        self._install(lambda: patterns_package.get_shared(progress=progress, language=language),
                      S.BF_SUMMARY_DOWNLOADING)

    def on_import(self):
        path = QFileDialog.getOpenFileName(self, S.BF_IMPORT_PICK, "", S.BF_IMPORT_FILTER)[0]
        if path:
            self._install(lambda: patterns_package.install(path, progress=self._progress), S.BF_SUMMARY_IMPORTING)

    def _install(self, get, line):
        """A download or an import, on a worker — the session closed there first (Windows won't replace an open
        database) — then what the buttons need read again, and a fresh preview."""
        if self._busy():
            return
        data = windows.opened(self, DATA_NAME)
        if data is not None:
            data.close()
        self._clear_preview()
        self._clear_messages()
        self._set_text(self.summary, line)
        self._start(self._install_worker, get)

    def _install_worker(self, get):
        self.keeper.close()
        try:
            names = get()
        except patterns_package.PackageError as e:
            self.relay.call(("message", str(e)))
            self.relay.call(("summary", ""))
            return
        self.relay.call(("installed", names))

    # --- the language, closing ----------------------------------------------------------------------------------- #
    def language_changed(self, language):
        """The main window switched language and this window is idle: the preview and the note types go, what is
        offered is read again, and a preview for the new language follows."""
        for name in (FIELDS_NAME, DATA_NAME):
            other = windows.opened(self, name)
            if other is not None:
                other.close()
        self.models = {}
        self._show_targets()
        self._clear_preview()
        self.ready = None
        self._read_readiness()
        self._sync()
        self._want_preview()

    def closeEvent(self, event):
        super().closeEvent(event)                # `gone` from here on: a worker ending now lets the session go
        self.stop.set()                         # a wait for another program's writer ends: nothing written
        job = self.job
        if job is not None and job.state in (jobs.QUEUED, jobs.WAITING):
            job.cancel()                         # not started: it never will (a write under way finishes)
        for name in (FIELDS_NAME, DATA_NAME):
            other = windows.opened(self, name)
            if other is not None:
                other.close()
        self._timer.stop()
        bridge.run_in_worker(self.lock.release)
        if not self.working:
            bridge.run_in_worker(self.keeper.close)


class FieldsWindow(windows.SecondaryWindow):
    """Where one fill goes, per note type in the deck, and each note type's language: a note type is filled only with
    its own language's data, and one whose language is not set ("Language?") is never filled. Not modal: a choice is
    saved as it is made; Esc, Back or Done closes it."""

    def __init__(self, owner, fill, rows):
        super().__init__(owner, fill.label, language=owner.language)
        self.owner = owner
        self.fill_key = fill.key
        self.body.addWidget(self._heading(S.BF_FIELDS_HEADING.format(fill=fill.label)))
        grid = QGridLayout()
        self.field_boxes, self.language_boxes = {}, {}
        for r, (name, count, fields, chosen, language) in enumerate(rows):
            label = QLabel(S.BF_FIELDS_MODEL.format(name=name, count=count), self)
            label.setObjectName("windowline")
            label.setTextFormat(Qt.TextFormat.PlainText)
            grid.addWidget(label, r, 0)
            box = QComboBox(self)
            box.addItems(fields)
            box.setCurrentIndex(fields.index(chosen) if chosen in fields else 0)
            box.setToolTip(S.BF_FIELDS_FIELD_TIP.format(name=name))
            box.setAccessibleName(S.BF_FIELDS_FIELD_TIP.format(name=name))
            box.activated.connect(lambda _i, m=name, b=box: owner.on_mapping(self.fill_key, m, b.currentText()))
            grid.addWidget(box, r, 1)
            self.field_boxes[name] = box
            pick = QComboBox(self)
            labels = list(V.LANGUAGE_LABELS.values()) + [S.BF_LANGUAGE_UNSET]
            pick.addItems(labels)
            pick.setCurrentIndex(labels.index(language) if language in labels else len(labels) - 1)
            pick.setToolTip(S.BF_FIELDS_LANGUAGE_TIP.format(name=name))
            pick.setAccessibleName(S.BF_FIELDS_LANGUAGE_TIP.format(name=name))
            pick.activated.connect(lambda _i, m=name, b=pick: owner.on_note_language(m, b.currentText()))
            grid.addWidget(pick, r, 2)
            self.language_boxes[name] = pick
        self.body.addLayout(grid)
        line = QHBoxLayout()
        line.addStretch(1)
        self.btn_done = QPushButton(S.BF_DONE, self)
        self.btn_done.setToolTip(S.BF_DONE_TIP)
        self.btn_done.setAccessibleName(S.BF_DONE)
        self.btn_done.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_done.clicked.connect(lambda _c=False: self.close())
        line.addWidget(self.btn_done)
        self.body.addLayout(line)

    def _heading(self, text):
        label = QLabel(text, self)
        label.setObjectName("windowheading")
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label


class DataWindow(windows.SecondaryWindow):
    """Where パターン data comes from, for the language on screen: Surasura's shared data (a download), or a package from
    another computer (an import). Not modal; Esc, Back or Close closes it."""

    def __init__(self, owner):
        super().__init__(owner, S.BF_DATA_TITLE, language=owner.language)
        shared = patterns_package.shared_for(owner.language)       # constants: no file is read
        name = V.LANGUAGE_NAMES.get(owner.language, owner.language)
        heading = QLabel(S.BF_DATA_TITLE, self)
        heading.setObjectName("windowheading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(heading)
        self.info = QLabel(S.BF_DATA_SHARED.format(lang=name, mb=shared["mb"]) if shared
                           else S.BF_DATA_NONE.format(lang=name), self)
        self.info.setObjectName("windowline")
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setWordWrap(True)
        if shared:
            self.info.setToolTip(S.BF_DATA_SHARED_TIP.format(credit=shared["credit"]))
        self.body.addWidget(self.info)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text, tip, slot in (("download", S.BF_DOWNLOAD, S.BF_DOWNLOAD_TIP, owner.on_download),
                                     ("import", S.BF_IMPORT, S.BF_IMPORT_TIP, owner.on_import),
                                     ("close", S.BF_CLOSE, S.BF_CLOSE_TIP, self.close)):
            if key == "close":
                row.addStretch(1)
            b = QPushButton(text, self)
            b.setToolTip(tip)
            b.setAccessibleName(text)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(b)
            self.buttons[key] = b
        self.shared = bool(shared)
        self.body.addLayout(row)
        self.set_idle(not owner._busy())

    def set_idle(self, idle):
        """Download and Import only while Backfill is idle (an install waits for nothing: AD5-11)."""
        self.buttons["download"].setEnabled(idle and self.shared)
        self.buttons["import"].setEnabled(idle)
