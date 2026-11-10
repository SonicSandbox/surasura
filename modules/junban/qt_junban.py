# SPDX-License-Identifier: GPL-3.0-or-later
"""The 順番 window in Qt (W3.4 row 6): the one place a user moves a card, and the one confirmation they get.

    probe  ->  choose a scope  ->  PREVIEW  ->  Reorder        (and, if it went wrong, Restore · Put Anki back)

The window decides nothing: `junban_view` holds the rules (the engine settings, the I5 key and the gate, the saved
keys, the button rules, the workers' bodies, the preview's rows and lines) and this file paints its answers.

* **The preview is the confirmation (I5).** Reorder is on only while a preview of the key read when Preview was
  pressed is on screen (`Session.ready`). A click, a tick or a redraw never stamps that key again — and a preview that
  lands after a change, a language switch, a finished Reorder / Restore and a put-back each throw it away (the Tk
  window's defect D1). The sentence above the buttons — "Reorder will move N … OVERWRITE … Not on your list: …" — is
  never cut.
* **Nothing waits on the GUI thread.** The probe, the preview, every re-plan after a click (4,000 rows: ~14 ms in the
  planner), the restore's question and every write run on workers; the table is a `QAbstractTableModel` whose click is
  `dataChanged` on its own row at once, and on the rows the re-plan changed when it lands — never a rebuild.
* **One writer.** Reorder, Restore and Put back are `junban` jobs of the window's registry (the automatic re-order
  never runs beside them); the engine's Anki-write lock still decides across programs. The window holds
  `junban-window` for its whole life (`auto.blocked`, `surasura-cli junban --auto` stand aside), released at close.
* **Saved:** only the keys the user changed, through the settings service — never on open (IK-13: the first deck is
  shown, and saved on the first action or edit). The (language, deck) pair only on the user's own deck pick.
* **Generate & preview** asks W3.5's Generate controller (never the Tk host's `run_analyzer`), quiet, as the user's own
  request; any Generate's end previews again a window that was waiting for one.
* The AnkiWeb sync on a Reorder is the engine's (`junban_view.window_job` → `anki_sync_rule`), as it is (IK-11).
"""
import os
import threading

from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QObject, Qt, QTimer
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QSizePolicy,
                             QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app import theme
from app.qt import bridge, confirm, motion, style, windows
from app.qt import press as qpress
from app.services import jobs
from modules.junban import junban_view as view
from modules.junban import put_back_view, touchup
from modules.junban.plan import TRY_CARDS
from modules.junban import qt_strings as qs
from modules.junban.qt_put_back import Lines, PutBackFlow, Worker, run_job, said_when_closed, spawn

# The preview's columns: (fixed width at size S, alignment).
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_CENTRE = Qt.AlignmentFlag.AlignCenter
COLUMNS = ((46, _RIGHT), (90, _RIGHT), (150, _LEFT), (64, _CENTRE), (250, _LEFT), (130, _LEFT))
_TONE_INK = {"": "ink", "unchanged": "ink-dim", "unmatched": "ink-faint"}


class PreviewModel(QAbstractTableModel):
    """The planner's own rows (contract 5), as the view model painted them. `set_rows` with as many rows as before
    (a click's re-plan) emits `dataChanged` over the runs of rows that changed and nothing else; a new preview resets
    the model. `updates` counts the `dataChanged` runs (a test reads it)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.card_ids = []
        self.updates = 0
        self._ink = {}
        self.refresh_colours()

    def refresh_colours(self):
        c = style.colours()
        self._ink = {tone: style.qcolor(c[name]) for tone, name in _TONE_INK.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return row[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._ink.get(row[6], self._ink[""])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return COLUMNS[index.column()][1]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return qs.JUNBAN_COLUMNS[section].format(marks=view.MARKS_HEADER)
        return None

    def set_rows(self, rows, card_ids):
        rows, card_ids = list(rows), list(card_ids)
        if len(rows) != len(self.rows) or card_ids != self.card_ids and sorted(card_ids) != sorted(self.card_ids):
            self.beginResetModel()
            self.rows, self.card_ids = rows, card_ids
            self.endResetModel()
            return
        old = self.rows
        self.rows, self.card_ids = rows, card_ids
        start = None
        for i in range(len(rows) + 1):
            differs = i < len(rows) and rows[i] != old[i]
            if differs and start is None:
                start = i
            elif not differs and start is not None:
                self.dataChanged.emit(self.index(start, 0), self.index(i - 1, len(COLUMNS) - 1))
                self.updates += 1
                start = None

    def set_row(self, i, row):
        """One row at once (a click, before its re-plan lands)."""
        if 0 <= i < len(self.rows) and self.rows[i] != row:
            self.rows[i] = row
            self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLUMNS) - 1))
            self.updates += 1


class _Space(QObject):
    """Space on a table does what a click does (the row is the checkbox), never Qt's own selection toggle."""

    def __init__(self, table, act):
        super().__init__(table)
        self.act = act
        table.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
            index = obj.currentIndex()
            if index.isValid():
                self.act(index.row())
            return True
        return False


def _button(parent, text, tip, slot, name=None, kind=None):
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    b.setAccessibleName(name or text)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if kind:
        b.setProperty("kind", kind)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _box(parent, cls, text, tip, slot, name=None):
    b = cls(text, parent)
    b.setToolTip(tip)
    if name:
        b.setAccessibleName(name)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _quiet_corner(table):
    """A table's corner button (select all) means nothing here: off, and named for the wiring check."""
    table.setCornerButtonEnabled(False)
    for corner in table.findChildren(QAbstractButton):
        corner.setToolTip(qs.JUNBAN_CORNER)
        corner.setAccessibleName(qs.JUNBAN_CORNER)


def _label(parent, text="", name="windowline", tip=None):
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if tip:
        label.setToolTip(tip)
    return label


def _tone(widget, tone):
    if widget.property("tone") == tone:
        return
    widget.setProperty("tone", tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class JunbanWindow(windows.SecondaryWindow):
    """順. `shell` is the main window (its services: settings, registry, the Generate controller)."""

    def __init__(self, shell, language=None):
        super().__init__(shell, qs.JUNBAN_NAME, language)
        self.services = shell.services
        self.session = view.Session()
        saved = self._saved()
        from modules.junban import connect
        self.connect_row = connect.preview_on(saved)
        self.unlisted_saved = str(saved.get("junban_unlisted") or "").strip().lower()
        self.controls = view.controls_from(saved, self.connect_row)
        self._last_saved = view.window_keys(self.controls, self.unlisted_saved)
        self._working = 0                       # reads in flight (the probe, a preview, the restore's question)
        self.highlighted = None                 # a7: the control the phase strip's 順 opened this window at
        self._replan_press = None               # round 8 row 45: a press that asked the planner, until its plan lands
        self._replan_token = None
        self._put_back_busy = False
        self._stops = set()                     # each job's stop: set at close (a wait for another writer ends)
        self._jobs = []
        self._connected = False
        self._probed = False
        self._decks = []
        self._auto_previewed = False
        self._ft = None                         # (language, anything kept to put back?) — asked on a worker (C21)
        self._picture = None                    # backlog onboarding: the backlog's picture shown (None: hidden)
        self._ft_asking = None
        self._touch_open = False
        self._controller_hooked = None
        self._relay = bridge.Relay(self)
        self._relay.said.connect(self._heard)
        self._job_words = {}                    # job id -> what the window says while it runs
        self._others = set()                    # other `junban` jobs seen live (Settings' put-back, the automatic run)
        bridge_ = getattr(shell, "bridge", None)
        if bridge_ is not None:
            bridge_.jobs_changed.connect(self._jobs_changed)
        self._build()
        self._paint_controls()
        self._sync()
        self._hook_controller()
        self._ask_first_touch()
        # Taken last, once nothing more can fail (the Tk window's D5, AD6-12: taken first, a failing build left it
        # held for the dashboard's life); let go at close, and if the window is destroyed with its parent.
        self.lock = view.WindowLock()
        relay = self._relay
        self.lock.start(on_failed=lambda: relay.call(("line", qs.JUNBAN_LOCK_NOT_HELD, "warning")))
        self._replanner = Worker(self, "junban-replan")     # a click's re-plan: handed over, never a thread per click
        lock, replanner, stops = self.lock, self._replanner, self._stops
        # Destroyed with its parent, or the app quitting: a write still waiting for another program's writer is
        # stopped (it would take the lock during the quit and be cut off mid-batch); one already writing finishes.
        self.destroyed.connect(lambda *_: (lock.release(), replanner.stop(), [stop.set() for stop in list(stops)]))
        closing = getattr(shell, "closing", None)
        if closing is not None:
            closing.connect(self._stop_writes)
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):      # never a test's: it would reach a real Anki
            QTimer.singleShot(50, self.alive(self.refresh_connection))

    # --- reading ------------------------------------------------------------------------------------------------- #
    def _saved(self):
        """The settings as the service holds them (memory: nothing read from disk), as a plain dict."""
        try:
            from app.services import settings as settings_service
            return settings_service.thaw(self.services.settings.get())
        except Exception:
            import modules.junban as junban
            return dict(junban.SETTINGS_DEFAULTS)

    def highlight(self, control):
        """a7 (Sonic 2026-10-29: "If yellow i would expect it to let me go somewhere to make a decision that is
        highlighted"): the phase strip's amber 順 opened this window at its decision — `control` "restore" (the
        unfinished reorder's Undo) or "deck" (the deck list: a deck to pick), given the focus and washed once."""
        widget = (self.btn_restore if control == "restore" else self.deck_box if self.controls.get("scope") == "deck"
                  else self.rb_deck)                  # (All decks chosen: the list is greyed until *This deck* is)
        self.highlighted = control
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        motion.wash(widget, theme.RADII["r"])

    def engine_settings(self, with_deselected=True):
        return view.engine_settings(self._saved(), self.controls, self.language,
                                    self.session.deselected if with_deselected else (), self.unlisted_saved)

    def key(self):
        return view.scope_key(self.language, self.controls, view.replan_on(self._saved(), self.language),
                              self.unlisted_saved)

    def is_busy(self):
        return bool(self.own_work() or self._put_back_elsewhere())

    def own_work(self):
        """A read, a write or a put-back of this window's own going (Settings' door refuses meanwhile)."""
        return bool(self._working or self.busy() or self._put_back_busy)

    def _put_back_elsewhere(self):
        """Settings' *Put Anki back…* is asking or writing (AD6-1): nothing of this window's may start meanwhile — a
        Reorder queued behind it would run from a preview of the collection as it was before."""
        other = windows.opened(self.shell, "put-back")
        return bool(other is not None and getattr(other, "working", False))

    def elsewhere_changed(self):
        """Settings' put-back started or ended: the buttons follow."""
        if not self.gone:
            self._sync()

    def can_generate(self):
        return getattr(self.services, "controller", None) is not None

    # --- building ------------------------------------------------------------------------------------------------ #
    def _build(self):
        f = theme.text_factor(style.current()[1])
        head = QHBoxLayout()
        self.header = _label(self, qs.JUNBAN_HEADER, "windowheading", qs.JUNBAN_HEADER_TIP)
        head.addWidget(self.header)
        head.addStretch(1)
        self.btn_backfill = _button(self, qs.JUNBAN_BACKFILL, qs.JUNBAN_BACKFILL_TIP, self.open_backfill, kind="chip")
        head.addWidget(self.btn_backfill)
        self.conn = _label(self, qs.JUNBAN_CONN_UNCHECKED)
        self.conn.setAccessibleName(qs.JUNBAN_CONN_NAME)
        head.addWidget(self.conn)
        self.btn_recheck = _button(self, "⟳", qs.JUNBAN_RECHECK_TIP, self.refresh_connection,
                                   name=qs.JUNBAN_RECHECK_NAME)
        head.addWidget(self.btn_recheck)
        self.body.addLayout(head)

        # Scope.
        row = QHBoxLayout()
        row.addWidget(_label(self, qs.JUNBAN_SCOPE))
        self.scope_group = QButtonGroup(self)
        self.rb_deck = _box(self, QRadioButton, qs.JUNBAN_THIS_DECK, qs.JUNBAN_THIS_DECK_TIP,
                            lambda: self._set("scope", "deck"))
        self.rb_all = _box(self, QRadioButton, qs.JUNBAN_ALL_DECKS, qs.JUNBAN_ALL_DECKS_TIP,
                           lambda: self._set("scope", "all"))
        for b in (self.rb_deck, self.rb_all):
            self.scope_group.addButton(b)
        row.addWidget(self.rb_deck)
        self.deck_box = QComboBox(self)
        self.deck_box.setToolTip(qs.JUNBAN_DECK_TIP)
        self.deck_box.setAccessibleName(qs.JUNBAN_DECK_NAME)
        self.deck_box.setMinimumWidth(round(220 * f))
        self.deck_box.activated.connect(lambda _i: self._deck_picked())
        row.addWidget(self.deck_box)
        row.addWidget(self.rb_all)
        row.addStretch(1)
        self.body.addLayout(row)
        self.counts = _label(self)
        self.body.addWidget(self.counts)

        # Order, the three switches, the markers.
        row = QHBoxLayout()
        row.addWidget(_label(self, qs.JUNBAN_ORDER))
        self.order_group = QButtonGroup(self)
        self.rb_met = _box(self, QRadioButton, qs.JUNBAN_AS_MET, qs.JUNBAN_AS_MET_TIP,
                           lambda: self._set("order", "content"))
        self.rb_leverage = _box(self, QRadioButton, qs.JUNBAN_LEVERAGE, qs.JUNBAN_LEVERAGE_TIP,
                                lambda: self._set("order", "priority"))
        for b in (self.rb_met, self.rb_leverage):
            self.order_group.addButton(b)
            row.addWidget(b)
        self.cb_list_first = _box(self, QCheckBox, qs.JUNBAN_LIST_FIRST, qs.JUNBAN_LIST_FIRST_TIP,
                                  lambda: self._set("list_first", self.cb_list_first.isChecked()))
        self.cb_phrases = _box(self, QCheckBox, qs.JUNBAN_PHRASES, qs.JUNBAN_PHRASES_TIP,
                               lambda: self._set("phrases", self.cb_phrases.isChecked()))
        self.cb_ready = _box(self, QCheckBox, qs.JUNBAN_READY_FIRST, qs.JUNBAN_READY_FIRST_TIP,
                             lambda: self._set("ready_first", self.cb_ready.isChecked()))
        for b in (self.cb_list_first, self.cb_phrases, self.cb_ready):
            row.addWidget(b)
        row.addSpacing(round(16 * f))
        row.addWidget(_label(self, qs.JUNBAN_ONLY))
        self.cb_markers = {}
        for name in view.match.MARKERS:
            b = _box(self, QCheckBox, view.MARKER_GLYPHS[name], qs.JUNBAN_MARKER_TIPS[name] + qs.JUNBAN_MARKER_TAIL,
                     self._markers_changed, name=qs.JUNBAN_MARKER_NAMES[name])
            self.cb_markers[name] = b
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)

        # Connect's row (only with its preview on: the 3.0 default with Connect, D29).
        self.own_tag = self.cb_order_all = None
        if self.connect_row:
            row = QHBoxLayout()
            row.addWidget(_label(self, qs.JUNBAN_OWN_TAG))
            self.own_tag = QLineEdit(self)
            self.own_tag.setToolTip(qs.JUNBAN_OWN_TAG_TIP)
            self.own_tag.setAccessibleName(qs.JUNBAN_OWN_TAG_NAME)
            self.own_tag.editingFinished.connect(lambda: self._set("own_tag", self.own_tag.text().strip()))
            row.addWidget(self.own_tag)
            self.cb_order_all = _box(self, QCheckBox, qs.JUNBAN_ORDER_ALL, qs.JUNBAN_ORDER_ALL_TIP,
                                     lambda: self._set("order_all", self.cb_order_all.isChecked()))
            row.addWidget(self.cb_order_all)
            row.addStretch(1)
            self.body.addLayout(row)

        # "Also update the cards" (collapsed).
        self.btn_touch = _button(self, qs.JUNBAN_TOUCH_SHUT, qs.JUNBAN_TOUCH_TIP, self._toggle_touch,
                                 name=qs.JUNBAN_TOUCH, kind="chip")
        line = QHBoxLayout()
        line.addWidget(self.btn_touch)
        line.addStretch(1)
        self.body.addLayout(line)
        self.touch_box = QWidget(self)
        box = QVBoxLayout(self.touch_box)
        box.setContentsMargins(round(24 * f), 0, 0, 0)
        row = QHBoxLayout()
        self.cb_tag = _box(self.touch_box, QCheckBox, qs.JUNBAN_TAG_ON, qs.JUNBAN_TAG_ON_TIP,
                           lambda: self._set("tag_on", self.cb_tag.isChecked()))
        row.addWidget(self.cb_tag)
        self.tag_name = QLineEdit(self.touch_box)
        self.tag_name.setToolTip(qs.JUNBAN_TAG_NAME_TIP)
        self.tag_name.setAccessibleName(qs.JUNBAN_TAG_NAME)
        self.tag_name.editingFinished.connect(lambda: self._set("tag_name", self.tag_name.text().strip()))
        row.addWidget(self.tag_name)
        self.cb_tag_markers = _box(self.touch_box, QCheckBox, qs.JUNBAN_MARKERS_ON, "",
                                   lambda: self._set("markers_on", self.cb_tag_markers.isChecked()))
        row.addWidget(self.cb_tag_markers)
        row.addStretch(1)
        box.addLayout(row)
        row = QHBoxLayout()
        self.cb_freq = _box(self.touch_box, QCheckBox, qs.JUNBAN_FREQ_ON, qs.JUNBAN_FREQ_ON_TIP,
                            lambda: self._set("freq_on", self.cb_freq.isChecked()))
        row.addWidget(self.cb_freq)
        self.freq_box = QComboBox(self.touch_box)
        self.freq_box.setEditable(True)
        self.freq_box.setToolTip(qs.JUNBAN_FREQ_FIELD_TIP)
        self.freq_box.setAccessibleName(qs.JUNBAN_FREQ_FIELD)
        self.freq_box.setMinimumWidth(round(160 * f))
        self.freq_box.activated.connect(lambda _i: self._set("freq_field", self.freq_box.currentText().strip()))
        self.freq_box.lineEdit().editingFinished.connect(
            lambda: self._set("freq_field", self.freq_box.currentText().strip()))
        row.addWidget(self.freq_box)
        row.addStretch(1)
        box.addLayout(row)
        field = touchup.FREQSORT_FIELD
        self.cb_freqsort = _box(self.touch_box, QCheckBox, qs.JUNBAN_FREQSORT.format(field=field),
                                qs.JUNBAN_FREQSORT_TIP.format(field=field),
                                lambda: self._set("freqsort_on", self.cb_freqsort.isChecked()))
        self.cb_freqsort.setProperty("tone", "danger")          # visibly the one that overwrites (to re-skin)
        box.addWidget(self.cb_freqsort)
        row = QHBoxLayout()
        row.addWidget(_label(self.touch_box, qs.JUNBAN_LATER))
        self.cb_later = {}
        for name in view.LATER:
            words, tip = qs.JUNBAN_LATER_BOXES[name]
            b = _box(self.touch_box, QCheckBox, words, tip, lambda n=name: self._set(f"later_{n}",
                                                                                  self.cb_later[n].isChecked()))
            self.cb_later[name] = b
            row.addWidget(b)
        self.later_state = _label(self.touch_box)
        row.addWidget(self.later_state)
        row.addStretch(1)
        box.addLayout(row)
        self.touch_box.setVisible(False)
        self.body.addWidget(self.touch_box)

        # Match.
        row = QHBoxLayout()
        row.addWidget(_label(self, qs.JUNBAN_MATCH))
        self.match = _label(self, qs.JUNBAN_MATCH_CHECKING)
        row.addWidget(self.match)
        self.fields = _label(self)
        _tone(self.fields, "good")
        row.addWidget(self.fields)
        row.addStretch(1)
        self.body.addLayout(row)

        # "Same word as one on your list?" — shown only while there is something to check.
        self.checks_box = QWidget(self)
        box = QVBoxLayout(self.checks_box)
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(_label(self.checks_box, qs.JUNBAN_CHECKS, "windowheading"))
        self.checks_count = _label(self.checks_box)
        row.addWidget(self.checks_count)
        row.addStretch(1)
        self.btn_earlier = qpress.room(_button(self.checks_box, qs.JUNBAN_EARLIER_SHOW.format(n=0),
                                               qs.JUNBAN_EARLIER_TIP, lambda: self._toggle_earlier(self.btn_earlier),
                                               kind="chip"))
        row.addWidget(self.btn_earlier)
        box.addLayout(row)
        self.check_table = QTableWidget(0, 5, self.checks_box)
        self.check_table.setToolTip(qs.JUNBAN_CHECKS_TIP)
        self.check_table.setAccessibleName(qs.JUNBAN_CHECKS_NAME)
        self.check_table.horizontalHeader().setVisible(False)
        self.check_table.verticalHeader().setVisible(False)
        self.check_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.check_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.check_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for column, width in enumerate((28, 100, 190, 100)):
            self.check_table.setColumnWidth(column, round(width * f))
        self.check_table.horizontalHeader().setStretchLastSection(True)
        self.check_table.clicked.connect(lambda index: self._tick(index.row()))
        _Space(self.check_table, self._tick)
        _quiet_corner(self.check_table)
        box.addWidget(self.check_table)
        self.checks_box.setVisible(False)
        self.body.addWidget(self.checks_box)
        self._check_rows = ()

        # The backlog's picture (backlog onboarding, Sonic 2026-10-29): before this language's first reorder only.
        self.picture_box = style.styled(QWidget(self), "needscard")
        self.picture_box.setAccessibleName(qs.JUNBAN_PICTURE_NAME)
        self.picture_box.setToolTip(qs.JUNBAN_PICTURE_TIP)
        box = QVBoxLayout(self.picture_box)
        pad = round(10 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(4 * f))
        self.picture_title = _label(self.picture_box, "", "needstitle")
        box.addWidget(self.picture_title)
        self.picture_lines = _label(self.picture_box)
        box.addWidget(self.picture_lines)
        self.known_row = QWidget(self.picture_box)
        row = QHBoxLayout(self.known_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.known_line = _label(self.known_row)
        row.addWidget(self.known_line)
        self.btn_show_known = qpress.room(_button(self.known_row, qs.JUNBAN_SHOW_KNOWN, qs.JUNBAN_SHOW_KNOWN_TIP,
                                                  self.on_show_known, kind="chip"))
        row.addWidget(self.btn_show_known)
        row.addStretch(1)
        box.addWidget(self.known_row)
        box.addWidget(_label(self.picture_box, qs.JUNBAN_PICTURE_UNDO, tip=qs.JUNBAN_UNDO_NOTE_TIP))
        row = QHBoxLayout()
        self.btn_try = _button(self.picture_box, qs.JUNBAN_TRY.format(n=TRY_CARDS, s="s"), qs.JUNBAN_TRY_TIP,
                               self.on_try)
        row.addWidget(self.btn_try)
        self.try_line = _label(self.picture_box)
        row.addWidget(self.try_line)
        row.addStretch(1)
        box.addLayout(row)
        self.picture_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)   # the table gives way
        self.picture_box.setVisible(False)
        self.body.addWidget(self.picture_box)

        # The preview.
        self.model = PreviewModel(self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setToolTip(qs.JUNBAN_TABLE_TIP)
        self.table.setAccessibleName(qs.JUNBAN_TABLE_NAME)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(round(26 * f))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column, (width, _align) in enumerate(COLUMNS):
            self.table.setColumnWidth(column, round(width * f))
        header.setStretchLastSection(True)
        self.table.clicked.connect(lambda index: self.toggle_row(index.row()))
        _Space(self.table, self.toggle_row)
        _quiet_corner(self.table)
        self.table.setMinimumHeight(round(200 * f))
        self.body.addWidget(self.table, 1)

        self.messages = Lines(self, qs.JUNBAN_MESSAGES_NAME)
        self.body.addWidget(self.messages)
        self.progress = QProgressBar(self)
        self.progress.setAccessibleName(qs.JUNBAN_PROGRESS_NAME)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        self.body.addWidget(self.progress)

        # B (backlog onboarding): said plainly, always — its own line, right above Undo, so it never crowds a button.
        line = QHBoxLayout()
        line.addStretch(1)
        self.undo_note = _label(self, qs.JUNBAN_UNDO_NOTE, tip=qs.JUNBAN_UNDO_NOTE_TIP)
        line.addWidget(self.undo_note)
        self.body.addLayout(line)

        row = QHBoxLayout()
        self.btn_preview = _button(self, qs.JUNBAN_PREVIEW, qs.JUNBAN_PREVIEW_TIP, self.on_preview)
        self.btn_preview.setMinimumWidth(round(160 * f))
        row.addWidget(self.btn_preview)
        row.addStretch(1)
        self.btn_put_back = _button(self, "⟲", f"{put_back_view.BUTTON_TEXT}\n{put_back_view.BUTTON_TIP}",
                                    self.on_put_back, name=qs.JUNBAN_PUT_BACK_NAME)
        row.addWidget(self.btn_put_back)
        self.btn_restore = qpress.room(_button(self, qs.JUNBAN_RESTORE, qs.JUNBAN_RESTORE_TIP, self.on_restore))
        row.addWidget(self.btn_restore)
        self.btn_reorder = _button(self, qs.JUNBAN_REORDER, qs.JUNBAN_REORDER_TIP, self.on_reorder, kind="primary")
        row.addWidget(self.btn_reorder)
        self.body.addLayout(row)
        self.resize(round(780 * f), round(660 * f))

    def _paint_controls(self):
        """The controls as `self.controls` says them, signals blocked (a restored control is not a click)."""
        c = self.controls
        widgets = [self.rb_deck, self.rb_all, self.rb_met, self.rb_leverage, self.cb_list_first, self.cb_phrases,
                   self.cb_ready, self.cb_tag, self.tag_name, self.cb_tag_markers, self.cb_freq, self.freq_box,
                   self.cb_freqsort, self.deck_box] + list(self.cb_markers.values()) + list(self.cb_later.values())
        for w in widgets:
            w.blockSignals(True)
        try:
            (self.rb_all if c["scope"] == "all" else self.rb_deck).setChecked(True)
            (self.rb_leverage if c["order"] == "priority" else self.rb_met).setChecked(True)
            self.cb_list_first.setChecked(bool(c["list_first"]))
            self.cb_phrases.setChecked(bool(c["phrases"]))
            self.cb_ready.setChecked(bool(c["ready_first"]))
            for name, b in self.cb_markers.items():
                b.setChecked(name in c["only_markers"])
            self.cb_tag.setChecked(bool(c["tag_on"]))
            self.tag_name.setText(c["tag_name"])
            self.cb_tag_markers.setChecked(bool(c["markers_on"]))
            self.cb_freq.setChecked(bool(c["freq_on"]))
            self.freq_box.setEditText(c["freq_field"])
            self.cb_freqsort.setChecked(bool(c["freqsort_on"]))
            for name, b in self.cb_later.items():
                b.setChecked(bool(c[f"later_{name}"]))
            self._offer_decks()
        finally:
            for w in widgets:
                w.blockSignals(False)
        if self.own_tag is not None:
            self.own_tag.setText(c.get("own_tag") or "")
            self.cb_order_all.setChecked(bool(c.get("order_all")))
        self._sync_touch()

    def _offer_decks(self):
        current = str(self.controls.get("deck") or "").strip()
        values = list(self._decks) if not current or current in self._decks else list(self._decks) + [current]
        if not values and current:
            values = [current]
        self.deck_box.blockSignals(True)
        try:
            if [self.deck_box.itemText(i) for i in range(self.deck_box.count())] != values:
                self.deck_box.clear()
                self.deck_box.addItems(values)
            if current:
                self.deck_box.setCurrentText(current)
        finally:
            self.deck_box.blockSignals(False)

    def _sync_touch(self):
        parts, none = view.touch_summary(self.controls)
        caption = qs.JUNBAN_TOUCH_OPEN if self._touch_open else qs.JUNBAN_TOUCH_SHUT
        text = qs.JUNBAN_TOUCH_ON.format(caption=caption, parts=", ".join(parts)) if parts else caption
        if self.btn_touch.text() != text:
            self.btn_touch.setText(text)
        tip = qs.JUNBAN_TOUCH_TIP                       # IK-91: while the automatic re-order applies them too, said
        if self._saved().get("junban_auto_actions") is True:
            tip = f"{tip} {qs.JUNBAN_TOUCH_AUTO_TIP}"
        if self.btn_touch.toolTip() != tip:
            self.btn_touch.setToolTip(tip)
        self.later_state.setText(qs.JUNBAN_LATER_NONE if none else "")
        tags = ", ".join(view.marker_tag_names(self.controls.get("tag_name")))
        self.cb_tag_markers.setToolTip(qs.JUNBAN_MARKERS_ON_TIP.format(tags=tags))
        self.touch_box.setVisible(self._touch_open)

    def _toggle_touch(self):
        self._touch_open = not self._touch_open
        self._sync_touch()

    # --- a control changed ----------------------------------------------------------------------------------------- #
    def _set(self, name, value, picked=False):
        """One control changed. Unchanged (an entry left as it was: the Tk window's D3) does nothing; changed, the
        preview is thrown away (I5), the changed keys saved, the buttons asked again."""
        if self.controls.get(name) == value:
            return
        self.controls[name] = value
        self._changed(picked)

    def _markers_changed(self):
        self._set("only_markers", tuple(n for n in view.match.MARKERS if self.cb_markers[n].isChecked()))

    def _deck_picked(self):
        """The user picked the deck in the list: the one change that records the (language, deck) pair (3.0)."""
        deck = self.deck_box.currentText().strip()
        if deck == self.controls.get("deck"):
            self._save(picked=True)
            return
        self.controls["deck"] = deck
        self._changed(picked=True)

    def _changed(self, picked=False):
        self.session.clear()
        self._clear_preview()
        self.match.setText(qs.JUNBAN_MATCH_REFRESH)
        self._sync_touch()
        self._save(picked)
        self._sync()

    def _save(self, picked=False):
        """Only what changed since the window last read or saved it (and the pair on a deck pick), through the
        settings service — never on open (IK-13)."""
        now = view.window_keys(self.controls, self.unlisted_saved)
        changes = view.changed_keys(self._last_saved, now)
        changes.update(view.pair_keys(self.controls.get("deck"), self.language, windows.language_of(self.shell),
                                      picked))
        if not changes:
            return
        try:
            self.services.settings.set(changes)
        except Exception as e:
            self.messages.add(qs.JUNBAN_SAVE_FAILED.format(why=e), "problem")
            return
        self._last_saved = now

    # --- state --------------------------------------------------------------------------------------------------- #
    def _sync(self):
        """Who may be pressed now (`junban_view.buttons`) — painted only where it changed."""
        must = self.session.must_generate(self.can_generate())
        b = view.buttons(self.is_busy(), self.session.generating, self.session.ready(self.key(), self.is_busy()),
                         must, self._first_touch_kept(), self.controls.get("scope"))
        text = {"generating": qs.JUNBAN_GENERATING, "generate": qs.JUNBAN_GENERATE_PREVIEW,
                "preview": qs.JUNBAN_PREVIEW}[b["preview_text"]]
        if self.btn_preview.text() != text:
            self.btn_preview.setText(text)
        # The button names the count its sentence moves (IK-10a) — only while that sentence is the run's.
        n = self.session.view.to_write if b["reorder"] and self.session.view is not None else 0
        text = qs.JUNBAN_REORDER_N.format(n=n, s="" if n == 1 else "s") if n else qs.JUNBAN_REORDER
        if self.btn_reorder.text() != text:
            self.btn_reorder.setText(text)
        restoring = qpress.mark(self.btn_restore) is not None    # its question being read: its arc, never greyed
        showing = qpress.mark(self.btn_show_known) is not None
        for widget, on in ((self.btn_preview, b["preview"]), (self.btn_restore, b["restore"] or restoring),
                           (self.btn_recheck, b["recheck"]), (self.btn_reorder, b["reorder"]),
                           (self.btn_put_back, b["put_back"]), (self.deck_box, b["deck"]),
                           (self.btn_try, b["reorder"] and self._picture is not None
                            and self._picture.try_moves > 0),
                           (self.btn_show_known, b["recheck"] or showing)):
            if widget.isEnabled() != on:
                widget.setEnabled(on)
        backfill = self._backfill_opener()
        show = backfill is not None and windows.available(backfill, self._saved(), self.language)
        if self.btn_backfill.isHidden() == show:
            self.btn_backfill.setVisible(show)

    def _first_touch_kept(self):
        kept = self._ft
        return bool(kept and kept[0] == self.language and kept[1])

    def _ask_first_touch(self):
        """C21: asked once per language, on a worker (local files only), again after a run, a restore, a put-back."""
        language = self.language
        if self._ft_asking == language:
            return
        self._ft_asking = language

        def landed(answer):
            if self._ft_asking == language:
                self._ft_asking = None
            if language == self.language:
                self._ft = (language, bool(answer))
                self._sync()
        spawn(self, put_back_view.available, language, then=self.alive(landed))

    def _first_touch_changed(self):
        self._ft = None
        self._ask_first_touch()

    def _read_started(self):
        self._working += 1
        self._sync()

    def _read_ended(self):
        self._working = max(0, self._working - 1)
        self._sync()

    # --- Anki's connection ----------------------------------------------------------------------------------------- #
    def refresh_connection(self):
        """Probe Anki (and list its decks) off the GUI thread, with the settings read here (D2)."""
        if self.is_busy():
            return
        self._probed = True
        self.conn.setText(qs.JUNBAN_CONN_CHECKING)
        _tone(self.conn, "")
        self._read_started()
        spawn(self, view.probe_work, self.engine_settings(False),
                             then=self.alive(self._probed_answer),
                             failed=self.alive(lambda info: self._probed_answer(
                                 ({"ok": False, "error": str(info[0])}, [], None))))

    def _probed_answer(self, answer):
        report, decks, line = answer
        self._read_ended()
        if line:
            self.messages.add(line, "warning")
        self._connected = bool(report.get("ok"))
        if self._connected:
            version = report.get("version")
            self.conn.setText(qs.JUNBAN_CONN_OK.format(version=version) if version else qs.JUNBAN_CONN_OK_PLAIN)
            self.conn.setToolTip("")
            _tone(self.conn, "good")
        else:
            self.conn.setText(qs.JUNBAN_CONN_DOWN)
            self.conn.setToolTip(qs.JUNBAN_CONN_DOWN_TIP)
            _tone(self.conn, "problem")
            self.messages.add(report.get("error") or qs.JUNBAN_ANKI_UNREACHABLE, "problem")
        if decks:
            self._decks = list(decks)
            if not str(self.controls.get("deck") or "").strip() and self.controls.get("scope") == "deck":
                # Shown, not saved (IK-13): saved on the user's first action or edit.
                self.controls["deck"] = decks[0]
            self._offer_decks()
        self._sync()
        if not self._connected:
            self.match.setText(qs.JUNBAN_MATCH_ANKI_DOWN)
            self.counts.setText("")
            return
        if self._auto_previewed or os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        if self.controls.get("scope") == "deck" and not str(self.controls.get("deck") or "").strip():
            return
        self._auto_previewed = True
        QTimer.singleShot(50, self.alive(lambda: self.on_preview(user=False)))

    # --- Preview ------------------------------------------------------------------------------------------------- #
    def on_preview(self, user=True):
        """The dry run: reads Anki and the list, writes nothing. Out of date (§16.9), Generate first. `user`: pressed
        by the user — the automatic first preview and the re-preview after a Generate save nothing (S16, IK-81)."""
        if self.is_busy() or self.session.generating:
            return
        if user:
            self._save()                                # the first action saves a shown pre-selection (IK-13)
        if self.session.must_generate(self.can_generate()):
            return self._generate()
        generation = self.session.ask()                 # the old preview and every one on its way are thrown away
        self._clear_preview()
        self.progress.setValue(0)
        self.match.setText(qs.JUNBAN_MATCH_WORKING)
        settings, key = self.engine_settings(), self.key()     # read HERE: the preview is stamped with what it was FOR
        is_current = view.list_current_of if self.can_generate() else None
        language = self.language
        self._read_started()

        def work():
            stats, checks = view.preview_work(settings, is_current)
            shown = view.preview_view(stats, checks, ticked=view.initial_ticks(stats), settings=settings,
                                      language=language)
            return stats, checks, shown
        spawn(self, work, then=self.alive(lambda answer: self._landed(generation, key, settings, answer)),
                             failed=self.alive(lambda info: self._landed(
                                 generation, key, settings,
                                 (None, {"ok": False, "problems": [str(info[0])], "warnings": []},
                                  view.preview_view(None, {"problems": [str(info[0])]})))))

    def _landed(self, generation, key, settings, answer):
        stats, checks, shown = answer
        self._read_ended()
        if not self.session.land(generation, key, self.key(), stats, checks, settings):
            if generation == self.session.generation:
                self.messages.add(qs.JUNBAN_LATE_PREVIEW, "warning")
            self._sync()
            return
        self.session.view = shown
        self.session.display_order = list(shown.display_order)
        self._paint(shown)
        self._sync()

    def _paint(self, shown):
        """One view: the counts, the match and fields lines, the rows (only those that changed), the field picker,
        the check list and the lines — the sentence last but the list's state (§16.9)."""
        self.counts.setText(shown.counts)
        self.match.setText(shown.match)
        self.fields.setText(shown.fields)
        self.model.set_rows(shown.rows, shown.card_ids)
        if shown.field_names:
            self._offer_fields(shown.field_names)
        self._paint_checks(shown.checks)
        link = None
        if shown.checks.link:
            link = (shown.checks.link, qs.JUNBAN_EARLIER_LINK, qs.JUNBAN_EARLIER_TIP,
                    lambda: self._toggle_earlier(self.messages.link_button))
        self.messages.set_lines(list(shown.lines) + view.tail_lines(self.session, self.can_generate()), link)
        self._paint_picture(shown.picture)

    def _paint_picture(self, picture):
        """The backlog's picture (backlog onboarding): shown only before this language's first reorder
        (`junban_view.picture_due`), with the preview's own numbers; hidden with no preview."""
        due = picture is not None and view.picture_due(self.session.stats, self._saved().get("hints_seen"),
                                                       self.language)
        self._picture = picture if due else None
        if due:
            self.picture_title.setText(picture.title)
            lines = [qs.JUNBAN_PICTURE_LINE.format(line=line) for line in picture.lines]
            self.picture_lines.setText(qs.JUNBAN_PICTURE_JOIN.join(lines))
            self.known_line.setText(qs.JUNBAN_PICTURE_LINE.format(line=picture.known_line)
                                    if picture.known_line else "")
            self.known_row.setVisible(bool(picture.known))
            self.btn_try.setText(qs.JUNBAN_TRY.format(n=picture.try_count, s="" if picture.try_count == 1 else "s"))
            self.try_line.setText(picture.try_line)
        if self.picture_box.isHidden() == due:
            self.picture_box.setVisible(due)

    def _picture_done(self):
        """The first reorder of this language finished: the picture never shows again (`hints_seen`, only that key
        written — the settings service's `save_keys` rule)."""
        hint = f"{view.PICTURE_HINT}:{self.language}"
        seen = self._saved().get("hints_seen")
        seen = [h for h in seen if isinstance(h, str)] if isinstance(seen, (list, tuple)) else []
        if hint not in seen:
            try:
                self.services.settings.set({"hints_seen": seen + [hint]})
            except Exception as e:
                self.messages.add(qs.JUNBAN_SAVE_FAILED.format(why=e), "problem")
        self._paint_picture(None)

    def _offer_fields(self, names):
        """The frequency field picker offers the fields these notes have; what the user typed stays."""
        current = self.freq_box.currentText().strip()
        values = list(names) + ([current] if current and current not in names else [])
        if [self.freq_box.itemText(i) for i in range(self.freq_box.count())] == values:
            return
        self.freq_box.blockSignals(True)
        try:
            self.freq_box.clear()
            self.freq_box.addItems(values)
            self.freq_box.setEditText(current)
        finally:
            self.freq_box.blockSignals(False)

    def _paint_checks(self, checks):
        if checks.rows == self._check_rows:
            return
        old, self._check_rows = self._check_rows, checks.rows
        table = self.check_table
        if table.rowCount() != len(checks.rows):
            table.setRowCount(len(checks.rows))
        ink = {tone: style.qcolor(style.colours()[name])
               for tone, name in (("", "ink"), ("ticked", "accent"), ("earlier", "ink-dim"))}
        for r, row in enumerate(checks.rows):
            if r < len(old) and old[r] == row:          # only the rows that changed (S19): a tick is one row
                continue
            for column, text in enumerate(row[:5]):
                item = QTableWidgetItem(text)
                item.setForeground(ink.get(row[5], ink[""]))
                table.setItem(r, column, item)
        f = theme.text_factor(style.current()[1])
        table.setFixedHeight(round(26 * f) * max(1, min(len(checks.rows), view.CHECK_ROWS)) + 4)
        self.checks_count.setText(qs.JUNBAN_CHECKS_PENDING.format(n=checks.pending) if checks.pending
                                  else qs.JUNBAN_CHECKS_DONE)
        self.btn_earlier.setVisible(bool(checks.earlier))
        self.btn_earlier.setText(qs.JUNBAN_EARLIER_HIDE if self.session.show_earlier
                                 else qs.JUNBAN_EARLIER_SHOW.format(n=checks.earlier))
        self.checks_box.setVisible(bool(checks.rows))

    def _clear_preview(self):
        self.model.set_rows([], [])
        self.counts.setText("")
        self.fields.setText("")
        self.messages.clear()
        self._paint_checks(view.CheckView((), (), 0, 0, None))
        self._paint_picture(None)

    # --- a click, a tick: re-planned on a worker ---------------------------------------------------------------- #
    def toggle_row(self, row):
        """A row in or out of the run: its row repaints at once (✗, or back in), the rest when the planner's
        answer lands. Reorder stays off until it has (the sentence must be the run's)."""
        if self.is_busy() or self.session.generating or not (0 <= row < len(self.model.card_ids)):
            return
        card_id = self.model.card_ids[row]
        if not self.session.toggle_row(card_id):
            return
        old = self.model.rows[row]
        if card_id in self.session.deselected:
            self.model.set_row(row, (view.DESELECTED_GLYPH, "", old[2], old[3], old[4], old[5], "unmatched"))
        else:
            self.model.set_row(row, ("…", "", old[2], old[3], old[4], old[5], ""))
        self._replan()

    def _tick(self, row):
        if self.is_busy() or self.session.generating or not (0 <= row < len(self.session.view.checks.words
                                                                            if self.session.view else ())):
            return
        word = self.session.view.checks.words[row]
        if self.session.toggle_tick(word):
            self._replan(at=qpress.widget_mark(self.check_table))

    def _toggle_earlier(self, control=None):
        if self.session.toggle_earlier():
            self._replan(control)

    def _replan(self, control=None, at=None):
        """The planner asked again on its worker. Round 8 row 45: a press that asked it (*Show N earlier*, its link
        chip: `control`; a tick: `at`, the check list) is marked from the press — painted before the planner has it —
        until the newest plan lands; a row in or out repaints its row at once and needs none."""
        token = self.session.replan_asked()
        generation = self.session.generation
        frozen = self.session.frozen()
        language = self.language
        if (control is not None or at is not None) and self._replan_press is None:
            self._replan_press = qpress.begin(control, "junban:replan", win=self, at=at)
        if self._replan_press is not None:
            self._replan_token = token
        self._sync()

        def work():
            return view.preview_view(frozen["stats"], frozen["checks"], frozen["deselected"], frozen["ticked"],
                                     frozen["display_order"], frozen["show_earlier"], frozen["settings"], language)
        self._replanner.ask(work, then=self.alive(lambda shown: self._replanned(generation, token, shown)),
                            failed=self.alive(lambda info: self._replan_failed(generation, token, info)))

    def _replanned(self, generation, token, shown):
        if self.session.replan_landed(generation, token, shown):
            self._paint(shown)
        self._replan_ended(token)
        self._sync()

    def _replan_failed(self, generation, token, info):
        if self.session.replan_failed(generation, token):
            self.messages.add(qs.JUNBAN_REPLAN_FAILED.format(why=info[0]), "problem")
        self._replan_ended(token, failed=True)
        self._sync()

    def _replan_ended(self, token, failed=False):
        """The newest plan a press asked for landed (or failed): its mark off."""
        if self._replan_press is not None and token == self._replan_token:
            p, self._replan_press = self._replan_press, None
            qpress.end(p, self, failed=failed)

    # --- Generate & preview (§16.9) ------------------------------------------------------------------------------ #
    def _hook_controller(self):
        controller = getattr(self.services, "controller", None)
        if controller is None or self._controller_hooked is controller:
            return
        relay = self._relay
        self._ended_listener = lambda run, outcome: relay.call(("generated", run, outcome))
        controller.on_end(self._ended_listener)
        self._controller_hooked = controller

    def _generate(self):
        """The Generate controller's run, quiet, as the user's request; this window previews again when any Generate
        ends. Never a write: the new order is previewed before Reorder can be pressed (I5)."""
        self._hook_controller()
        controller = self.services.controller
        self.session.generating = True
        self.session.generate_tried = True
        self.messages.set_lines([(qs.JUNBAN_GENERATE_STARTED, "good")])
        self._sync()
        settings = self._saved()
        language, services = self.language, self.services

        def ask():
            try:
                services.settings.flush(10.0)
            except Exception:
                pass
            try:
                from app import path_utils
                path_utils.ensure_data_setup(language)
            except Exception:
                pass
            automation = getattr(services, "automation", None)
            if automation is not None:
                try:
                    automation.before_generate()
                except Exception:
                    pass
            return controller.request(language, argv=view.generate_argv(settings, language),
                                      label=qs.JUNBAN_LABEL_GENERATE)
        spawn(self, ask, then=self.alive(self._generate_asked), failed=self.alive(self._generate_failed))

    def _generate_asked(self, run):
        if self.session.generating:
            self.session.generate_run = run

    def _generate_failed(self, info):
        self.session.generating = False
        self.messages.add(qs.JUNBAN_GENERATE_FAILED.format(why=info[0]), "problem")
        self._sync()

    def list_updated(self):
        """Any Generate ended (a run that never started included: D4). A window that was waiting for one previews
        again; one the user is working in is left alone."""
        if self.gone:
            return
        if self.session.list_updated(self.is_busy()):
            self.on_preview(user=False)
        else:
            self._sync()

    # --- Reorder ------------------------------------------------------------------------------------------------- #
    def on_reorder(self):
        """Write the order. Reachable only with a preview of this exact key on screen (I5)."""
        if not self.session.ready(self.key(), self.is_busy()):
            return
        self._save()
        answers = view.answers_to_record(self.session.stats, self.session.ticked)
        settings = self.engine_settings()            # the settings the key above was just checked against
        language = self.language
        self.messages.clear()
        self.progress.setValue(0)
        self.say(qs.JUNBAN_REORDERING)
        relay = self._relay

        def work(stop, progress, on_wait, job):
            # IK-11: the first run of a session syncs with AnkiWeb before its first write (~2 s): said in the window
            # and the bar until the first position lands, never a freeze.
            if view.session_sync_likely():
                job.progress(qs.JUNBAN_SYNC_FIRST)
                relay.call(("status", qs.JUNBAN_SYNC_FIRST))
            moved = []

            def placed(done, total):
                if not moved:
                    moved.append(True)
                    relay.call(("status", qs.JUNBAN_REORDERING))
                job.progress(qs.JUNBAN_REORDERING, done, total)
                progress(done, total)
            return dict(view.reorder_work(settings, language, answers, progress=placed, cancel=stop,
                                          on_wait=on_wait), job="reorder")
        self._submit(qs.JUNBAN_LABEL_REORDER, work)

    # --- Try it on my cards, Show them in Anki (backlog onboarding) ---------------------------------------------- #
    def on_try(self):
        """*Try it on my cards*: the preview's next cards to the front — a real reorder of those alone, with its own
        snapshot (*Undo the last reorder* puts them back exactly) — then Anki's browser on them. Reachable only as
        Reorder is (I5: this preview's key on screen; the button names the count), and only in the picture."""
        if (self._picture is None or not self._picture.try_moves
                or not self.session.ready(self.key(), self.is_busy())):
            return
        self._save()
        answers = view.answers_to_record(self.session.stats, self.session.ticked)
        settings, language = self.engine_settings(), self.language
        self.messages.clear()
        self.progress.setValue(0)
        self.say(qs.JUNBAN_TRYING)
        self._submit(qs.JUNBAN_LABEL_TRY,
                     lambda stop, progress, on_wait, _job: dict(view.try_work(settings, language, answers,
                                                                             progress=progress, cancel=stop,
                                                                             on_wait=on_wait), job="try"))

    def on_show_known(self):
        """*Show them in Anki*: Anki's browser on the cards whose words you already know, so you can suspend them
        there. A read on a worker; nothing written."""
        picture = self._picture
        if picture is None or not picture.known or self.is_busy():
            return
        p = qpress.begin(self.btn_show_known, "junban:show-known", win=self)
        if p is None:
            return
        settings = self.engine_settings(False)

        def shown(_how):
            qpress.end(p, self)
            self._sync()

        def failed(info):
            qpress.end(p, self, failed=True)
            self.messages.add(qs.JUNBAN_SHOW_FAILED.format(why=info[0]), "problem")
            self._sync()
        spawn(self, view.show_work, settings, list(picture.known), then=self.alive(shown),
              failed=self.alive(failed))

    # --- Restore ------------------------------------------------------------------------------------------------- #
    def on_restore(self):
        """Put back the saved order: the question read on a worker (it names what it restores), then asked (Enter
        is No: 🧭 IK-10c), then a `junban` job of only that snapshot or run."""
        if self.is_busy():
            return
        settings, language = self.engine_settings(), self.language
        p = qpress.begin(self.btn_restore, "junban:restore", win=self)   # round 8 row 45: its arc until the question
        self._read_started()

        def broke(info):
            if p is not None:
                qpress.end(p, self, failed=True)
            self._read_ended()
            self.messages.add(qs.JUNBAN_UNEXPECTED.format(why=info[0]), "problem")

        def asked(question):
            if p is not None:
                qpress.end(p, self)
            self._restore_asked(question, settings, language)
        spawn(self, view.restore_question, language, settings, then=self.alive(asked), failed=self.alive(broke))

    def _restore_asked(self, question, settings, language):
        self._read_ended()
        if language != self.language:                   # read for the language the window showed then: dropped
            return
        if question["kind"] == "none":
            self.messages.set_lines([(question["line"], "warning")])
            return
        title = qs.JUNBAN_RESTORE_RUN_Q if question["kind"] == "run" else qs.JUNBAN_RESTORE_Q
        run, confirmed = question.get("run"), question.get("confirmed")

        def answered(yes):
            if not yes or self.is_busy():
                return
            self.messages.clear()
            self.progress.setValue(0)
            self.say(qs.JUNBAN_RESTORING)
            self._submit(qs.JUNBAN_LABEL_RESTORE,
                         lambda stop, progress, on_wait, _job: view.restore_work(settings, confirmed=confirmed, run=run,
                                                                           progress=progress, cancel=stop,
                                                                           on_wait=on_wait))
        self.restore_card = confirm.ask(self, title, question["body"], qs.JUNBAN_RESTORE_YES,
                                        qs.JUNBAN_RESTORE_YES_TIP, no_tip=qs.JUNBAN_CONFIRM_NO_TIP, default_no=True,
                                        danger=True, on_answer=answered)

    # --- the jobs ------------------------------------------------------------------------------------------------ #
    def _submit(self, label, work):
        """`work(stop, progress, on_wait, job)` as a `junban` job; its report lands in `_reported`."""
        stop = threading.Event()
        self._stops.add(stop)
        relay = self._relay

        def progress(done, total):
            relay.call(("progress", done, total))

        def on_wait(holder):
            from app import anki_connect
            relay.call(("line", anki_connect.waiting_line(holder), "warning"))
        self.begin_write()
        self._sync()
        tell = said_when_closed(self)
        job = run_job(self.services.registry, label, lambda job: work(stop, progress, on_wait, job),
                      lambda report: (tell(report), relay.call(("report", report, stop))), stop)
        self._jobs.append(job)
        self._job_words[job.id] = self.status.text()
        self._jobs_changed(self.services.registry.snapshot())
        return job

    def _jobs_changed(self, views):
        """A write of this window's that waits says so — for what — until it runs (the Qt guide §3: anything that
        happens later says so while it hasn't); running, its own words again. Repainted only on a change (`say`)."""
        if self.gone:
            return
        self._others_moved(views)
        flow = getattr(self, "flow", None)
        if flow is not None and flow.job is not None and flow.job.id not in self._job_words:
            self._job_words[flow.job.id] = ""
        for v in views:
            words = self._job_words.get(v.id)
            if words is None:
                continue
            if v.state == "waiting":
                self.say(qs.JUNBAN_WAITS.format(reason=v.reason or ""))
            elif v.state == "running" and self.status.text().startswith(qs.JUNBAN_WAITS.format(reason="")):
                self.say(words)
            elif v.state in ("done", "failed"):
                self._job_words.pop(v.id, None)

    def _others_moved(self, views):
        """Another `junban` job that was live has ended (Settings' put-back — even with its window closed mid-write —
        or the automatic re-order): Anki has moved on, so the preview is thrown away (D1d through the other door)."""
        flow = getattr(self, "flow", None)
        own = {job.id for job in self._jobs} | set(self._job_words)
        if flow is not None and flow.job is not None:
            own.add(flow.job.id)
        ended = False
        for v in views:
            if v.kind != "junban" or v.id in own:
                continue
            if v.state in jobs.LIVE:
                self._others.add(v.id)
            elif v.id in self._others:
                self._others.discard(v.id)
                ended = True
        if ended:
            if self.session.stats is not None:
                self.messages.add(qs.JUNBAN_ANKI_MOVED, "warning")
            self.session.clear()                    # a preview still being read goes too: it read Anki before
            self._sync()

    def _heard(self, said):
        kind = said[0]
        if kind == "progress":
            self.progress.setMaximum(max(1, int(said[2] or 0)))
            self.progress.setValue(int(said[1] or 0))
        elif kind == "line":
            self.messages.add(said[1], said[2])
        elif kind == "report":
            self._reported(said[1] or {}, said[2])
        elif kind == "status":
            if self.busy():
                self.say(said[1])
        elif kind == "generated":
            self.list_updated()

    def _reported(self, report, stop):
        """A finished run or restore. The collection has moved on: the preview is thrown away (D1c) — its rows stay
        on screen, inert, until the next preview."""
        self._stops.discard(stop)
        self._jobs = [job for job in self._jobs if job.state not in ("done", "failed")]
        self.session.clear()
        self.say("")
        for text, tone in view.report_lines(report):
            self.messages.add(text, tone)
        self._first_touch_changed()
        self.end_write(report.get("message"))
        if report.get("job") == "reorder" and report.get("ok"):
            self._picture_done()                    # the first reorder: the backlog's picture never again
        self._sync()
        if report.get("job") == "try" and report.get("ok") and not os.environ.get("SURASURA_NO_UI_TIMERS"):
            # Anki has moved on: the new preview reads it again, so Reorder (or Try it) is one press away
            QTimer.singleShot(50, self.alive(lambda: self.on_preview(user=False)))

    # --- Put Anki back ------------------------------------------------------------------------------------------- #
    def on_put_back(self):
        """FT (D8): the flow Settings opens too. Refused while a run of this window's own is going."""
        if self.is_busy() or self.session.generating:
            return
        self.messages.clear()
        self.progress.setValue(0)
        stop = threading.Event()
        self._stops.add(stop)
        self.flow = PutBackFlow(self, self.language, self.services.registry, settings=self.engine_settings(),
                                show=self.messages.add, busy=self._set_put_back_busy, progress=self._show_progress,
                                done=lambda report: self._put_back_done(report, stop),
                                begin_write=self.begin_write, end_write=self.end_write, stop=stop)
        self.flow.start()

    def _set_put_back_busy(self, busy):
        self._put_back_busy = bool(busy)
        self._sync()

    def _show_progress(self, done, total):
        self.progress.setMaximum(max(1, int(total or 0)))
        self.progress.setValue(int(done or 0))

    def _put_back_done(self, report, stop):
        """After a put-back the collection has moved on: the preview is thrown away (D1d)."""
        self._stops.discard(stop)
        self._first_touch_changed()
        if report is not None:
            self.session.clear()
        self._sync()

    # --- Backfill ------------------------------------------------------------------------------------------------ #
    @staticmethod
    def _backfill_opener():
        return next((op for op in windows.OPENERS if op.name == "backfill"), None)

    def open_backfill(self):
        """The Backfill window — the same one its own door opens (row 5's opener), raised if open."""
        op = self._backfill_opener()
        if op is not None:
            windows.launch(self.shell, op)

    # --- the language and the close ------------------------------------------------------------------------------ #
    def language_changed(self, language):
        """The main window switched language while this one was idle (🧭 IK-12): the preview is another language's —
        thrown away (D1b) — and the window reads again for the new one. A question still open (Restore, Put back)
        was about the other language's cards: answered No, never carried into this one."""
        self.session.clear()
        self.session.list_current = None
        self._clear_preview()
        for card in self.findChildren(confirm.Confirm):     # after the lines are cleared: the flow's end is said
            if card.answer is None:
                card.close()
        self.match.setText(qs.JUNBAN_MATCH_REFRESH)
        saved = self._saved()
        recorded = view.recorded_deck(saved, language)
        if recorded and self.controls.get("scope") == "deck" and recorded != self.controls.get("deck"):
            self.controls["deck"] = recorded            # shown, not saved (IK-86; saved on the user's first action)
            self._offer_decks()
        # Only this language's own deck previews by itself (AD6-7); another waits for the user's Preview.
        self._auto_previewed = not view.previews_by_itself_after_a_switch(saved, language, self.controls)
        self._first_touch_changed()
        self._sync()
        if self._probed:
            self.refresh_connection()

    def _stop_writes(self):
        for stop in list(self._stops):
            stop.set()

    def closeEvent(self, event):
        self._stop_writes()
        for job in self._jobs:
            if job.state in ("queued", "waiting"):
                job.cancel()
        if hasattr(self, "lock"):                       # (an opening that failed took neither)
            self.lock.release()
            self._replanner.stop()
        controller = self._controller_hooked
        if controller is not None:
            try:
                controller.unsubscribe(self._ended_listener)
            except Exception:
                pass
        super().closeEvent(event)


def open(shell):
    """The 順 window of `shell` (one of a kind, raised if open)."""
    return windows.show(shell, "junban", JunbanWindow)
