"""*Words to leave out* (W3.3 P10; the window's spec 01 §1.2 n16): the Ignore list and the Blacklist, one language at a
time — the main window's, followed when idle.

A tab per list; the list's words with a search and their count, ✕ on each (Delete on the current row too; a
KnownWord.json entry only after the in-window question, `confirm.ask`); an *Add* field (Enter commits; several words
separated by spaces); *Paste text…*: the text read by the library's own tokenizer in a child process of its own
(`word_lists.find_words`: the tokenizer never loads here; closing the window, hiding the text or a new paste kills it),
each word found a chip to keep or drop — a new word kept, one already known or left out dropped, one already on the
list shown and fixed — then *Add N words*. A chip adds the word's `Word` (the lemma), shown by its spelling. Every read
and write is `app/services/word_lists.py`'s, on a worker; the window decides nothing. After an add or a ✕ only the rows
that changed are inserted or removed (S19); every row is made again only for a list or language switch, or a read
that changed many rows.
"""
import re

from PyQt6.QtCore import QEvent, QRect, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QPalette, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QStyledItemDelegate, QWidget)

from app.qt import bridge, confirm, style
from app.qt import press as qpress
from app.qt import word_lists_strings as s
from app.qt.windows import SecondaryWindow, say_in_bar, show
from app.services import word_lists

WORD = Qt.ItemDataRole.UserRole                           # a row's word, as the list holds it
SOURCE = Qt.ItemDataRole.UserRole + 1                     # where it is held: "list" · "known" · "names"
_SPLIT = re.compile(r"[\s,、，]+")                          # the Add field's words
_REBUILD_OVER = 100                                       # rows changed by one read past which every row is made again


class _RemoveDelegate(QStyledItemDelegate):
    """Paints ✕ at the end of each row that can be taken off (not a name); a click on it calls `on_remove(index)`.
    `not_now()` true (a write under way): every ✕ painted greyed — "not now" (round 8 row 45, IK-4)."""

    def __init__(self, view, on_remove, not_now=lambda: False):
        super().__init__(view)
        self.on_remove = on_remove
        self.not_now = not_now

    def mark_colour(self, option):
        """The ✕'s ink: the row's text, or greyed as a greyed button's words are (`ink-faint`) while not now."""
        if self.not_now():
            return style.qcolor(style.colours()["ink-faint"])
        return option.palette.color(QPalette.ColorRole.Text)

    def mark_rect(self, option):
        side = option.rect.height()
        return QRect(option.rect.right() - side, option.rect.top(), side, side)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(SOURCE) == "names":
            return
        painter.save()
        painter.setPen(self.mark_colour(option))
        painter.drawText(self.mark_rect(option), Qt.AlignmentFlag.AlignCenter, s.WORD_LISTS_REMOVE_MARK)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                and index.data(SOURCE) != "names" and self.mark_rect(option).contains(event.position().toPoint())):
            self.on_remove(index)
            return True
        return super().editorEvent(event, model, option, index)


class _WordsView(QListView):
    """The list; Delete takes the current word off (never Backspace: it corrects the list's keyboard search)."""

    def __init__(self, parent, on_delete):
        super().__init__(parent)
        self.on_delete = on_delete

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and self.currentIndex().isValid():
            self.on_delete(self.currentIndex())
            return
        super().keyPressEvent(event)


class WordListsWindow(SecondaryWindow):
    def __init__(self, shell, language=None):
        super().__init__(shell, s.WORD_LISTS_NAME, language)
        self.kind = s.WORD_LISTS_KINDS[0][0]
        self.entries = None                               # the list as last read (None: not read yet)
        self.list_paints = 0                              # how many times the rows were rebuilt (S19)
        self.candidates = None                            # the chips as last found (None: none asked)
        self._asked = 0                                   # the newest read: an older answer is dropped
        self._finds = 0                                   # the newest find: an older answer is dropped
        self.question = None                              # the open question (a known-words entry's removal)
        pasting = self._pasting = [None]                  # the paste whose child is running (`word_lists.Paste`)
        self.destroyed.connect(lambda *_a: pasting[0] is not None and pasting[0].cancel())   # gone with its main window

        self.kinds = QWidget(self)                        # one of the two lists, as the main window's tabs are
        self.kinds.setAccessibleName(s.WORD_LISTS_KINDS_NAME)
        row = QHBoxLayout(self.kinds)
        row.setContentsMargins(0, 0, 0, 0)
        self.kind_group = QButtonGroup(self.kinds)
        self.kind_group.setExclusive(True)
        self.kind_buttons = {}
        for kind, label, tip in s.WORD_LISTS_KINDS:
            b = QPushButton(label, self.kinds)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setAccessibleName(label)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(lambda _c=False, k=kind: self.show_kind(k))
            self.kind_group.addButton(b)
            self.kind_buttons[kind] = b
            row.addWidget(b)
        row.addStretch(1)
        self.kind_buttons[self.kind].setChecked(True)
        self.body.addWidget(self.kinds)

        row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(s.WORD_LISTS_SEARCH)
        self.search.setAccessibleName(s.WORD_LISTS_SEARCH_NAME)
        self.search.textChanged.connect(self._filter)
        row.addWidget(self.search, 1)
        self.count = QLabel(self)
        self.count.setObjectName("windowline")
        self.count.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.count)
        self.body.addLayout(row)

        self.model = QStandardItemModel(self)
        self.shown = QSortFilterProxyModel(self)
        self.shown.setSourceModel(self.model)
        self.shown.setFilterRole(WORD)
        self.shown.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.list = _WordsView(self, self._remove_index)
        self.list.setModel(self.shown)
        self.list.setObjectName("windowlist")
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setUniformItemSizes(True)
        self.list.setToolTip(s.WORD_LISTS_LIST_TIP)
        self.list.setAccessibleName(s.WORD_LISTS_LIST_NAME)
        self.list.setItemDelegate(_RemoveDelegate(self.list, self._remove_index, self.busy))
        self.body.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.add_field = QLineEdit(self)
        self.add_field.setPlaceholderText(s.WORD_LISTS_ADD_FIELD)
        self.add_field.setAccessibleName(s.WORD_LISTS_ADD_FIELD_NAME)
        self.add_field.setToolTip(s.WORD_LISTS_ADD_FIELD_TIP)
        self.add_field.returnPressed.connect(self.add_typed)
        row.addWidget(self.add_field, 1)
        self.add_button = qpress.room(self._button(s.WORD_LISTS_ADD, s.WORD_LISTS_ADD_TIP, self.add_typed, row))
        self.paste_button = self._button(s.WORD_LISTS_PASTE, s.WORD_LISTS_PASTE_TIP, self._toggle_paste, row)
        self.paste_button.setCheckable(True)
        self.body.addLayout(row)

        self.text = QPlainTextEdit(self)
        self.text.setPlaceholderText(s.WORD_LISTS_TEXT_HINT)
        self.text.setAccessibleName(s.WORD_LISTS_TEXT_NAME)
        self.text.setTabChangesFocus(True)
        self.text.setVisible(False)
        self.body.addWidget(self.text)
        row = QHBoxLayout()
        self.find_button = self._button(s.WORD_LISTS_FIND, s.WORD_LISTS_FIND_TIP, self.find, row)
        row.addStretch(1)
        self.add_kept_button = self._button(s.WORD_LISTS_ADD_KEPT.format(n=0), s.WORD_LISTS_ADD_KEPT_TIP,
                                            self.add_kept, row, "primary")
        self.find_button.setVisible(False)
        self.add_kept_button.setVisible(False)
        self.chips = QListWidget(self)
        self.chips.setObjectName("windowlist")
        self.chips.setFlow(QListView.Flow.LeftToRight)
        self.chips.setWrapping(True)
        self.chips.setResizeMode(QListView.ResizeMode.Adjust)
        self.chips.setSpacing(4)
        self.chips.setToolTip(s.WORD_LISTS_CHIPS_TIP)
        self.chips.setAccessibleName(s.WORD_LISTS_CHIPS_NAME)
        self.chips.itemChanged.connect(lambda _item: self._kept_changed())
        self.chips.setVisible(False)
        self.body.addWidget(self.chips)
        self.body.addLayout(row)
        self.read()

    def _button(self, label, tip, slot, row, kind=None):
        b = QPushButton(label, self)
        b.setToolTip(tip)
        b.setAccessibleName(label)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _c=False: slot())
        row.addWidget(b)
        return b

    # --- reading ---------------------------------------------------------------------------------------------- #
    def read(self, then_say=None):
        self._asked += 1
        asked, kind, language = self._asked, self.kind, self.language
        if self.entries is None:
            self.say(s.WORD_LISTS_READING)
        bridge.run_in_worker(word_lists.read, kind, language,
                             then=self.alive(lambda listing: self._show(asked, listing, then_say)),
                             failed=self.alive(lambda info: self.say(s.WORD_LISTS_READ_FAILED.format(why=info[0]))))

    def _show(self, asked, listing, line=None):
        if asked != self._asked:
            return                                        # read for a list or a language the window has left
        entries = [tuple(e) for e in listing.entries]
        if entries != self.entries:                       # touched only when the words changed (S19)
            self._update_rows(entries)
            self.entries = entries
            self.list_paints += 1
        self._count()
        lines = [line] if line else []
        if listing.error:
            lines.append(listing.error)
        elif not entries and not line:
            lines.append(s.WORD_LISTS_EMPTY)
        self.say(" · ".join(lines))

    def _update_rows(self, entries):
        """The model brought to `entries` from `self.entries` (the rows it holds): the run of rows that differs, past
        the common start and end, removed and the new ones inserted — an add's rows, a ✕'s row. Every row made again
        for a first read (a list or language switch) or a read that changed more than `_REBUILD_OVER` rows."""
        old = self.entries
        if old is not None:
            start, n = 0, min(len(old), len(entries))
            while start < n and old[start] == entries[start]:
                start += 1
            end_old, end_new = len(old), len(entries)
            while end_old > start and end_new > start and old[end_old - 1] == entries[end_new - 1]:
                end_old -= 1
                end_new -= 1
            if (end_old - start) + (end_new - start) <= _REBUILD_OVER:
                if end_old > start:
                    self.model.removeRows(start, end_old - start)
                for i in range(start, end_new):
                    self.model.insertRow(i, _item(*entries[i]))
                return
        self.model.clear()
        for entry in entries:
            self.model.appendRow(_item(*entry))

    def _count(self):
        n, shown = self.model.rowCount(), self.shown.rowCount()
        text = (s.WORD_LISTS_COUNT_SHOWN.format(shown=shown, n=n) if shown != n
                else s.WORD_LISTS_COUNT_ONE if n == 1 else s.WORD_LISTS_COUNT.format(n=n))
        if self.count.text() != text:
            self.count.setText(text)

    def _filter(self, text):
        self.shown.setFilterFixedString(text.strip())
        self._count()

    def show_kind(self, kind):
        """The Ignore list (`ignore`) or the Blacklist (`blacklist`), read on a worker."""
        if not self.kind_buttons[kind].isChecked():
            self.kind_buttons[kind].setChecked(True)
        if kind == self.kind:
            return
        self._drop_question()
        self.kind = kind
        self.entries = None
        self.model.clear()
        self._count()
        self.read()
        if self.candidates is not None:                   # the chips' marks name the list: asked again for this one
            self.find()

    def language_changed(self, language):
        self._drop_question()
        self._stop_paste()
        self.entries = None
        self.model.clear()
        self._clear_chips()
        self.read()

    # --- writing ---------------------------------------------------------------------------------------------- #
    def _remove_index(self, index):
        if self.busy() or self.question is not None:
            return
        word, source = index.data(WORD), index.data(SOURCE)
        if word and source == "list":
            self.remove(word, source)
        elif word and source == "known":
            self.ask_remove_known(word)

    def ask_remove_known(self, word):
        """A KnownWord.json entry can't come back from here (an add goes on the list): asked first, in the window."""
        kind, language = self.kind, self.language

        def answered(yes):
            self.question = None
            if yes and (kind, language) == (self.kind, self.language):
                self.remove(word, "known")
        self.question = confirm.ask(self, s.WORD_LISTS_KNOWN_REMOVE.format(word=word), s.WORD_LISTS_KNOWN_REMOVE_BODY,
                                    s.WORD_LISTS_KNOWN_REMOVE_YES, s.WORD_LISTS_KNOWN_REMOVE_YES_TIP,
                                    default_no=True, danger=True, on_answer=answered)
        return self.question

    def _drop_question(self):
        """The question no longer stands (the window shows another list or language): dropped, never answered."""
        if self.question is not None:
            self.question.drop()
            self.question = None

    def remove(self, word, source="list"):
        self._write(False, [word], source)

    def add_typed(self):
        words = [w for w in _SPLIT.split(self.add_field.text()) if w]
        if words and not self.busy():
            self.add_field.clear()
            self._write(True, words, control=self.add_button)

    def add_kept(self):
        words = [w for w, on in self.kept()]
        if words and not self.busy():
            self._clear_chips()
            self._write(True, words)

    def _write(self, adding, words, source=None, control=None):
        """`word_lists.add` (`adding`) or `.remove` of `words` on a worker; then the list is read again with the
        write's line. Round 8 row 45: `control`'s arc (*Add*), or the window's corner arc (a row's ✕, *Add N kept*,
        whose chips go as it is pressed), painted before the worker — never greyed; one write at a time."""
        if self.busy():
            return
        kind, language = self.kind, self.language
        fn = word_lists.add if adding else word_lists.remove
        args = (kind, language, list(words)) + (() if adding else (source,))
        self.begin_write()
        if qpress.run(control, "words:write", fn, *args, win=self,
                      then=lambda change: self._written(kind, language, _line(change, adding)),
                      failed=lambda info: self._written(kind, language,
                                                        s.WORD_LISTS_WRITE_FAILED.format(why=info[0]))) is None:
            self.end_write()                              # (one under way: the window was busy, nothing started)
        self._writing()

    def _writing(self):
        """While a write is under way the list's other controls are greyed — "not now" (IK-4, as the frequency lists'
        Add / Remove and Koe's Save / Remove): every row's ✕ (and Delete), *Add* and its field, *Add N kept*; the
        pressed one keeps its look and its arc (*Add*)."""
        add = not self.busy() or qpress.mark(self.add_button) is not None
        for w in (self.add_button, self.add_field):
            if w.isEnabled() != add:
                w.setEnabled(add)
        self.list.viewport().update()                     # the ✕ marks greyed, or back
        self._kept_changed()

    def _written(self, kind, language, line):
        if self.gone:                                     # the window closed meanwhile: the bar says what was done
            if line:
                say_in_bar(self.shell, line)
            return
        self.end_write(line)
        self._writing()                                   # (after: no write under way, every control back)
        if (kind, language) == (self.kind, self.language):
            self.read(then_say=line)

    # --- pasted text -> chips --------------------------------------------------------------------------------- #
    def _toggle_paste(self):
        on = self.paste_button.isChecked()
        if not on:
            self._stop_paste()                            # hidden: the text isn't being read any more
        for w in (self.text, self.find_button):
            w.setVisible(on)
        self.chips.setVisible(on and bool(self.candidates))
        self.add_kept_button.setVisible(on and bool(self.candidates))
        if on:
            self.text.setFocus(Qt.FocusReason.OtherFocusReason)

    def find(self):
        text = self.text.toPlainText()
        if not text.strip():
            return
        self._stop_paste()                                # an older paste's child: killed, its answer dropped
        self._finds += 1
        asked, kind, language = self._finds, self.kind, self.language
        paste = self._pasting[0] = word_lists.Paste()
        self.say(s.WORD_LISTS_FINDING)
        bridge.run_in_worker(word_lists.find_words, text, language, kind, paste,
                             then=self.alive(lambda found: self._found(asked, language, found)),
                             failed=self.alive(lambda info: self._find_failed(asked, info)))

    def _stop_paste(self):
        """The running paste's child killed (none: nothing); its answer is dropped."""
        paste, self._pasting[0] = self._pasting[0], None
        if paste is not None:
            paste.cancel()

    def _find_failed(self, asked, info):
        """The paste's child failed or timed out: said, the chips as they were. A cancelled one says nothing."""
        if asked != self._finds:
            return                                        # asked again since: the newer paste speaks
        self._pasting[0] = None
        if isinstance(info[0], word_lists.Cancelled):
            if self.status.text() == s.WORD_LISTS_FINDING:
                self.say("")
            return
        self.say(s.WORD_LISTS_FIND_FAILED.format(why=info[0]))

    def _found(self, asked, language, found):
        if language != self.language or asked != self._finds:
            return                                        # found for a language the window left, or asked again
        self._pasting[0] = None
        self.say("" if found else s.WORD_LISTS_FOUND_NONE)
        self.candidates = list(found)
        self.chips.blockSignals(True)                     # the marks, loaded: not a keep or drop
        self.chips.clear()
        for c in self.candidates:
            item = QListWidgetItem(c.spelling)
            item.setData(WORD, c.word)
            item.setToolTip(s.WORD_LISTS_CHIP[c.status].format(spelling=c.spelling))
            if c.status == "listed":
                item.setFlags(Qt.ItemFlag.ItemIsSelectable)           # shown, fixed: it is on the list already
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if c.status == "new" else Qt.CheckState.Unchecked)
            self.chips.addItem(item)
        self.chips.blockSignals(False)
        on = self.paste_button.isChecked()
        self.chips.setVisible(on and bool(self.candidates))
        self.add_kept_button.setVisible(on and bool(self.candidates))
        self._kept_changed()

    def kept(self):
        """The chips that would be added: [(word, True)], in the text's order."""
        out = []
        for i in range(self.chips.count()):
            item = self.chips.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled and item.checkState() == Qt.CheckState.Checked:
                out.append((item.data(WORD), True))
        return out

    def _kept_changed(self):
        n = len(self.kept())
        self.add_kept_button.setText(s.WORD_LISTS_ADD_KEPT_ONE if n == 1 else s.WORD_LISTS_ADD_KEPT.format(n=n))
        self.add_kept_button.setAccessibleName(self.add_kept_button.text())
        self.add_kept_button.setEnabled(n > 0 and not self.busy())

    def closeEvent(self, event):
        super().closeEvent(event)
        if self.gone:
            self._stop_paste()                            # closed mid-paste: its child killed

    def _clear_chips(self):
        """The chips gone (the pasted text kept: Find words reads it again)."""
        self.candidates = None
        self.chips.clear()
        self.chips.setVisible(False)
        self.add_kept_button.setVisible(False)


def _item(word, source):
    """A row of the list: the word, marked by where it is held, with its tip."""
    if source == "known":
        text, tip = s.WORD_LISTS_MARK_KNOWN.format(word=word), s.WORD_LISTS_ROW_KNOWN
    elif source == "names":
        text, tip = s.WORD_LISTS_MARK_NAMES.format(word=word), s.WORD_LISTS_ROW_NAMES
    else:
        text, tip = word, s.WORD_LISTS_ROW_LIST
    item = QStandardItem(text)
    item.setData(word, WORD)
    item.setData(source, SOURCE)
    item.setData(tip.format(word=word), Qt.ItemDataRole.ToolTipRole)
    item.setData(text, Qt.ItemDataRole.AccessibleTextRole)
    item.setEditable(False)
    return item


def _line(change, adding):
    """The status line for a `word_lists.Change`."""
    if change.error:
        return change.error
    parts = []
    if change.done:
        verb = s.WORD_LISTS_ADDED if adding else s.WORD_LISTS_REMOVED
        parts.append(verb.format(words=", ".join(change.done)))
    if change.skipped:
        verb = s.WORD_LISTS_ALREADY if adding else s.WORD_LISTS_NOT_THERE
        parts.append(verb.format(words=", ".join(change.skipped)))
    if change.backup:
        parts.append(s.WORD_LISTS_BACKUP)
    return " · ".join(parts)


def open_window(shell):
    """The door (`windows.OPENERS`' "word-lists"): one window per main window, raised when open."""
    return show(shell, "word-lists", WordListsWindow)
