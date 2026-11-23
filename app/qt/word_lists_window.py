"""*Your words* (W3.3 P10; the window's spec 01 §1.2 n16): the words you know and the Ignore list (the Blacklist is
merged into the Ignore list since Kotoba-WS2), one language at a time — the main window's, followed when idle.

A tab per list, **Known** first (Mado-LT 4, words PROVISIONAL): every word you know, however it became known, newest
first, each with its reading and where it came from (`word_lists.read`), and its ✓ lit — a click on it (or Delete) and
the word is *Still learning* (`word_marks`' "learning", through `Services.mark_words`: the numbers follow), its ○ shown
in place at once; a click on the ○ puts it back (that write's own Undo, `undo_marks`; a word Still learning from
before: Known). The row changes in place, nothing read again. The Ignore tab: the list's words, ✕ on each (Delete on
the current row too; a KnownWord.json entry only after the in-window question, `confirm.ask`). Each tab: a search (a
known word's reading too) and the count; an *Add* field (Enter commits; several words
separated by spaces); *Paste text…*: the text read by the library's own tokenizer in a child process of its own
(`word_lists.find_words`: the tokenizer never loads here; closing the window, hiding the text or a new paste kills it),
each word found a chip to keep or drop — a new word kept, one already known or ignored dropped, one already on the
list shown and fixed — then *Add N words*. A chip adds the word's `Word` (the lemma), shown by its spelling. Every read
and write is `app/services/word_lists.py`'s, on a worker; the window decides nothing. After an add or a ✕ only the rows
that changed are inserted or removed (S19); every row is made again only for a list or language switch, or a read
that changed many rows. A row is made only when the view asks for it (`_Words`, Mado-LT 6): 10,000 known words open,
answer a search and take a ✓ in steps under the Qt guide's 4 ms.
"""
import bisect
import functools
import re
import time

from PyQt6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRect, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QStyledItemDelegate, QWidget)

from app import scrub
from app.journey_render import _hira
from app.qt import bridge, confirm, style
from app.qt import press as qpress
from app.qt import word_lists_strings as s
from app.qt.windows import SecondaryWindow, say_in_bar, show
from app.services import word_lists

WORD = Qt.ItemDataRole.UserRole                           # a row's word, as the list holds it
SOURCE = Qt.ItemDataRole.UserRole + 1                     # where it is held: "list" · "known" · "names" · "learning"
FIND = Qt.ItemDataRole.UserRole + 2                       # what the search looks in: the word, and a known word's reading
KNOWN_ROW = Qt.ItemDataRole.UserRole + 3                  # True on a Known tab's row (its mark ✓ / ○, never ✕)
_SPLIT = re.compile(r"[\s,、，]+")                          # the Add field's words
_REBUILD_OVER = 100                                       # rows changed by one read past which every row is made again
_FACE = {Qt.ItemDataRole.DisplayRole: 0, Qt.ItemDataRole.EditRole: 0, Qt.ItemDataRole.AccessibleTextRole: 0,
         Qt.ItemDataRole.ToolTipRole: 1, FIND: 2}         # the roles `_face` answers: its text, tip and search text
_ROLES = frozenset(_FACE) | {WORD, SOURCE, KNOWN_ROW}     # every role a row answers


class _RemoveDelegate(QStyledItemDelegate):
    """Paints the row's mark at its end — ✕ on a row that can be taken off (not a name); on the Known tab ✓ (known, the
    accent) or ○ (Still learning, violet: `accent-2`, the word card's) — and a click on it calls `on_remove(index)`.
    `not_now()` true (a write under way): every mark painted greyed — "not now" (round 8 row 45, IK-4)."""

    def __init__(self, view, on_remove, not_now=lambda: False):
        super().__init__(view)
        self.on_remove = on_remove
        self.not_now = not_now

    def mark_colour(self, option, index=None):
        """The mark's ink: the row's text (✕), the accent (✓), violet (○), or greyed as a greyed button's words are
        (`ink-faint`) while not now."""
        if self.not_now():
            return style.qcolor(style.colours()["ink-faint"])
        source = index.data(SOURCE) if index is not None and index.data(KNOWN_ROW) else None
        if source in s.WORD_LISTS_KNOWN_MARK_INK:
            return style.qcolor(style.colours()[s.WORD_LISTS_KNOWN_MARK_INK[source]])
        return option.palette.color(QPalette.ColorRole.Text)

    def mark_glyph(self, index):
        """The mark painted: ✓ or ○ on a Known tab's row (its word known, or Still learning), ✕ on any other."""
        glyph = s.WORD_LISTS_KNOWN_MARK.get(index.data(SOURCE)) if index.data(KNOWN_ROW) else None
        return glyph or s.WORD_LISTS_REMOVE_MARK

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = scrub.shown(option.text)             # (Report a problem's picture: a name in a list scrubbed)

    def mark_rect(self, option):
        side = option.rect.height()
        return QRect(option.rect.right() - side, option.rect.top(), side, side)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(SOURCE) == "names":
            return
        painter.save()
        painter.setPen(self.mark_colour(option, index))
        painter.drawText(self.mark_rect(option), Qt.AlignmentFlag.AlignCenter, self.mark_glyph(index))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                and index.data(SOURCE) != "names" and self.mark_rect(option).contains(event.position().toPoint())):
            self.on_remove(index)
            return True
        return super().editorEvent(event, model, option, index)


class _Words(QAbstractListModel):
    """The list's rows, each made from its entry only when the view asks for it — no item per word (Mado-LT 6: 10,020
    known words were 10,020 items made in one ~130 ms step on the window's thread). It shows the search's rows itself:
    `finds` (each entry's search text, casefolded, made with the read on the worker) scanned on a keystroke, `rows` the
    entries shown (None: every one) — a Qt filter would ask `data()` of every row, here in Python (~14 ms a keystroke
    at 10,000)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []                                 # every entry, in order (tuples: word, source, reading, …)
        self.finds = []                                   # each entry's search text, casefolded
        self.needle = ""                                  # the search, casefolded ("": none)
        self.rows = None                                  # the places in `entries` shown, in order (None: every one)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries if self.rows is None else self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role not in _ROLES:                            # (half a row's paint asks roles no row holds: none made)
            return None
        row = index.row()
        if not index.isValid() or row >= (len(self.entries) if self.rows is None else len(self.rows)):
            return None
        entry = self.entries[row if self.rows is None else self.rows[row]]
        if role == WORD:
            return entry[0]
        if role == SOURCE:
            return entry[1]
        if role == KNOWN_ROW:
            return len(entry) > 3 and entry[3] is not None
        return _face(*entry)[_FACE[role]]

    def flags(self, index):
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable) if index.isValid() else Qt.ItemFlag.NoItemFlags

    def _matching(self, start, finds):
        return [start + i for i, find in enumerate(finds) if self.needle in find]

    def fill(self, entries, finds):
        """Every row made again: the list as read (a list or language switch, a read that changed many rows)."""
        self.beginResetModel()
        self.entries, self.finds = list(entries), list(finds)
        self.rows = self._matching(0, self.finds) if self.needle else None
        self.endResetModel()

    def search(self, text):
        """The rows whose search text holds `text`, in any case ("": every row): one scan of the search texts."""
        needle = text.casefold()
        if needle != self.needle:
            self.beginResetModel()
            self.needle = needle
            self.rows = self._matching(0, self.finds) if needle else None
            self.endResetModel()

    def splice(self, start, end, entries, finds):
        """Entries [start, end) replaced by `entries` (their search texts `finds`): only the rows of those removed, and
        the new ones inserted where the search shows them (S19)."""
        if self.rows is None:
            if end > start:
                self.beginRemoveRows(QModelIndex(), start, end - 1)
                del self.entries[start:end], self.finds[start:end]
                self.endRemoveRows()
            if entries:
                self.beginInsertRows(QModelIndex(), start, start + len(entries) - 1)
                self.entries[start:start], self.finds[start:start] = entries, finds
                self.endInsertRows()
            return
        a, b = bisect.bisect_left(self.rows, start), bisect.bisect_left(self.rows, end)
        if b > a:
            self.beginRemoveRows(QModelIndex(), a, b - 1)
            del self.rows[a:b]
            self.endRemoveRows()
        self.entries[start:end], self.finds[start:end] = entries, finds   # (the rows shown: the same entries, moved)
        shift = len(entries) - (end - start)
        if shift:
            self.rows[a:] = [r + shift for r in self.rows[a:]]
        new = self._matching(start, finds)
        if new:
            self.beginInsertRows(QModelIndex(), a, a + len(new) - 1)
            self.rows[a:a] = new
            self.endInsertRows()

    def place(self, row):
        """Row `row`'s place in `entries`."""
        return row if self.rows is None else self.rows[row]

    def row_of(self, at):
        """The row showing entry `at` (None: the search hides it)."""
        if self.rows is None:
            return at if 0 <= at < len(self.entries) else None
        row = bisect.bisect_left(self.rows, at)
        return row if row < len(self.rows) and self.rows[row] == at else None

    def set_entry(self, at, entry):
        """Entry `at` is `entry` (its search text unchanged: a ✓'s mark): its row alone painted again, when shown."""
        self.entries[at] = entry
        row = self.row_of(at)
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))


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
        self.cleared = {}                                 # Known tab: {word: undo id} made Still learning here (its ○)
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

        self.model = _Words(self)                         # every entry; it shows the search's rows itself
        # A Qt proxy in front of it, never filtering: the view lays out every row by asking `index()` of each, which a
        # Python model answers through Python (~20 ms at 10,000 rows); the proxy answers from its own table, in C++.
        self.shown = QSortFilterProxyModel(self)
        self.shown.setSourceModel(self.model)
        self.list = _WordsView(self, self._remove_index)
        self.list.setModel(self.shown)
        self.list.setObjectName("windowlist")
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setUniformItemSizes(True)
        self.list.setToolTip(s.WORD_LISTS_LIST_TIPS[self.kind])
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
        bridge.run_in_worker(_read, kind, language,
                             then=self.alive(lambda got: self._show(asked, got[0], then_say, got[1:])),
                             failed=self.alive(lambda info: self.say(s.WORD_LISTS_READ_FAILED.format(why=info[0]))))

    def _show(self, asked, listing, line=None, made=None):
        """`made`: the entries as tuples and their search texts, made with the read on the worker (`_read`)."""
        if asked != self._asked:
            return                                        # read for a list or a language the window has left
        entries, finds = made or _made(listing)
        if entries != self.entries:                       # touched only when the words changed (S19)
            self._update_rows(entries, finds)
            self.entries = entries
            self.list_paints += 1
        self._count()
        lines = [line] if line else []
        if listing.error:
            lines.append(listing.error)
        elif not entries and not line:
            lines.append(s.WORD_LISTS_EMPTY)
        self.say(" · ".join(lines))

    def _update_rows(self, entries, finds):
        """The model brought to `entries` (their search texts `finds`) from `self.entries` (the rows it holds): the run
        of rows that differs, past the common start and end, removed and the new ones inserted — an add's rows, a ✕'s
        row. Every row made again for a first read (a list or language switch) or a read that changed more than
        `_REBUILD_OVER` rows."""
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
                self.model.splice(start, end_old, entries[start:end_new], finds[start:end_new])
                return
        self.model.fill(entries, finds)

    def _count(self):
        n, shown = len(self.model.entries), self.model.rowCount()
        text = (s.WORD_LISTS_COUNT_SHOWN.format(shown=shown, n=n) if shown != n
                else s.WORD_LISTS_COUNT_ONE if n == 1 else s.WORD_LISTS_COUNT.format(n=n))
        if self.count.text() != text:
            self.count.setText(text)

    def _filter(self, text):
        """The search's rows shown; the current word stays current while the search still shows it."""
        current = self.shown.mapToSource(self.list.currentIndex())
        at = self.model.place(current.row()) if current.isValid() else None
        self.model.search(text.strip())
        row = self.model.row_of(at) if at is not None else None
        if row is not None:
            self.list.setCurrentIndex(self.shown.mapFromSource(self.model.index(row, 0)))
        self._count()

    def show_kind(self, kind):
        """The words you know (`known`) or the Ignore list (`ignore`), read on a worker."""
        if not self.kind_buttons[kind].isChecked():
            self.kind_buttons[kind].setChecked(True)
        if kind == self.kind:
            return
        self._drop_question()
        self.kind = kind
        self.list.setToolTip(s.WORD_LISTS_LIST_TIPS[kind])
        self.entries = None
        self.model.fill([], [])
        self._count()
        self.read()
        if self.candidates is not None:                   # the chips' marks name the list: asked again for this one
            self.find()

    def language_changed(self, language):
        self._drop_question()
        self._stop_paste()
        self.cleared = {}
        self.entries = None
        self.model.fill([], [])
        self._clear_chips()
        self.read()

    # --- writing ---------------------------------------------------------------------------------------------- #
    def _remove_index(self, index):
        if self.busy() or self.question is not None:
            return
        word, source = index.data(WORD), index.data(SOURCE)
        if word and index.data(KNOWN_ROW):
            self.mark_known_row(word)
        elif word and source == "list":
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

    # --- the Known tab's ✓: Still learning, and back (Mado-LT 4) ------------------------------------------------ #
    def mark_known_row(self, word):
        """`word`'s ✓ (or ○) on the Known tab: a known word is Still learning (its ○ painted at once); a Still learning
        one known again — the write that made it so undone when it was made here, else marked Known. On a worker,
        through the window's services (the numbers follow); a refusal puts the row back and says why."""
        services = getattr(self.shell, "services", None)
        at = self._row_of(word)
        if self.busy() or services is None or at is None:
            return
        before = self.entries[at]
        language = self.language
        if before[1] == "known":
            after, fn, args = "learning", services.mark_words, (language, [(word, "learning")])
        elif word in self.cleared:
            after, fn, args = "known", _known_again, (services, language, word, self.cleared[word])
        else:
            after, fn, args = "known", services.mark_words, (language, [(word, "known")])
        self._set_row(at, (word, after) + tuple(before[2:]))
        self._asked += 1                                  # (a read on its way answers what was before: dropped)
        self.begin_write()
        if qpress.run(None, "words:learning", fn, *args, win=self,
                      then=lambda result: self._row_marked(language, word, before, after, result),
                      failed=lambda info: self._row_marked(language, word, before, after, info[0])) is None:
            self.end_write()                              # (one under way: nothing started)
            self._set_row(at, before)
        self._writing()

    def _row_marked(self, language, word, before, after, result):
        """The ✓'s write answered: the row kept (and its Undo held) or put back with why."""
        if isinstance(result, (str, Exception)):          # (a break with no words still says what broke)
            error = str(result) or type(result).__name__
        else:
            error = result.error
        done = not error and any(d[0] == word for d in result.done)
        if error or not done:
            line = s.WORD_LISTS_WRITE_FAILED.format(why=error or s.WORD_LISTS_UNCHANGED.format(word=word))
        else:
            line = (s.WORD_LISTS_STILL_LEARNING if after == "learning" else s.WORD_LISTS_KNOWN_AGAIN).format(word=word)
        if self.gone:                                     # the window closed meanwhile: the bar says what was done
            say_in_bar(self.shell, line)
            return
        self.end_write(line)
        self._writing()
        if language != self.language or self.kind != word_lists.KNOWN:
            return                                        # another list or language shown now: its read is the truth
        at = self._row_of(word)
        if error:
            if at is not None:
                self._set_row(at, before)                 # refused: the row as it was
        elif not done:
            self.cleared.pop(word, None)                  # nothing changed: the word was already as the row now says
        elif after == "learning":
            self.cleared[word] = result.undo_id
        else:
            self.cleared.pop(word, None)
        self.say(line)

    def _row_of(self, word):
        """The row of `word` in the list shown now (None: not there)."""
        for i, entry in enumerate(self.entries or ()):
            if entry[0] == word:
                return i
        return None

    def _set_row(self, at, entry):
        """Entry `at` is `entry`: its row alone painted again (S19)."""
        entry = tuple(entry)
        self.entries[at] = entry
        self.model.set_entry(at, entry)

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
        write = word_lists.add if adding else word_lists.remove
        args = (kind, language, list(words)) + (() if adding else (source,))
        follow = getattr(getattr(self.shell, "services", None), "words_marked", None)

        @functools.wraps(write)
        def fn(*a):                                       # (the worker) Known / Ignore: the window's numbers follow
            change = write(*a)
            if follow is not None and change.done and kind in ("ignore", word_lists.KNOWN):
                follow(language)
            return change
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


def _read(kind, language):
    """(on the worker) The list read, its entries as tuples and each one's search text: none made on the window's
    thread."""
    listing = word_lists.read(kind, language)
    return (listing,) + _made(listing)


def _made(listing):
    entries = [tuple(e) for e in listing.entries]
    return entries, [_find(*e).casefold() for e in entries]


def _shown_reading(word, reading):
    return reading if reading and _hira(reading) != _hira(word) else ""          # (a word in kana: its own reading)


def _find(word, source=None, reading=None, origin=None, created=None):
    """What the search looks in: the word, and a known word's reading as its row shows it."""
    shown = _shown_reading(word, reading) if origin is not None else ""
    return f"{word} {shown}" if shown else word


def _face(word, source, reading=None, origin=None, created=None):
    """A row of the list, as the view asks for it: (text, tip, search text) — the word, marked by where it is held,
    with its tip. A Known tab's row (`origin` given): the word, its reading and where it came from; its tip says since
    when it is known (or that it is Still learning)."""
    if origin is not None:
        shown = _shown_reading(word, reading)
        text = (s.WORD_LISTS_KNOWN_ROW if shown else s.WORD_LISTS_KNOWN_ROW_BARE).format(
            word=word, reading=shown, origin=s.WORD_LISTS_ORIGINS[origin])
        if source == "learning":
            tip = s.WORD_LISTS_ROW_LEARNING
        elif created:
            tip = s.WORD_LISTS_ROW_KNOWN_SINCE.replace("{date}", _date(created))
        else:
            tip = s.WORD_LISTS_ROW_KNOWN_UNDATED
    elif source == "known":
        text, tip = s.WORD_LISTS_MARK_KNOWN.format(word=word), s.WORD_LISTS_ROW_KNOWN
    elif source == "names":
        text, tip = s.WORD_LISTS_MARK_NAMES.format(word=word), s.WORD_LISTS_ROW_NAMES
    else:
        text, tip = word, s.WORD_LISTS_ROW_LIST
    return text, tip.format(word=word), _find(word, source, reading, origin)


def _known_again(services, language, word, undo_id):
    """(on the worker) ○ on a word made Still learning here: that write undone — or, when it is gone from the Undo
    stack (the main window's Undo took it, or later writes pushed it out), the word marked Known."""
    result = services.undo_marks(language, undo_id)
    if not result.error and not any(d[0] == word for d in result.done):
        result = services.mark_words(language, [(word, "known")])
    return result


def _date(ms):
    """A known word's date as the window says it: 22 Nov 2026 (the PC's own time)."""
    try:
        day = time.localtime(ms / 1000)
    except (OverflowError, OSError, ValueError):
        return "?"
    return f"{day.tm_mday} {time.strftime('%b %Y', day)}"


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
