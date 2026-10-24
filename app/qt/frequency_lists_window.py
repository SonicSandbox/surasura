"""The frequency lists window (W3.4 row 1; the Tk Frequency List Manager, `app/frequency_list_gui.py`, ported).

This language's lists (`frequency_lists.listed`), *Add…* (the system's file picker, several at once; a same-named list
is replaced with its old copy kept in the trash folder), *Remove…* (the shared confirmation, Cancel by default; the
lists move to the trash folder, never deleted), *Get lists ↗* (jiten.moe/other) and the credit to mattias. The note on
what a list does is the list's tooltip. The rules are `app/frequency_lists.py`'s; every read and write runs on a worker.
"""
import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton

from app import frequency_lists
from app.qt import bridge, confirm, strings
from app.qt import press as qpress
from app.qt.windows import SecondaryWindow, say_in_bar


class FrequencyListsWindow(SecondaryWindow):
    def __init__(self, shell, language=None):
        super().__init__(shell, strings.FREQ_NAME, language)
        self.names = None                                 # the lists as last read (None: not read yet)
        self.list_paints = 0                              # how many times the list was rebuilt (S19)
        self.question = None                              # the Remove question while it is open
        self.list = QListWidget(self)
        self.list.setObjectName("windowlist")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setToolTip(strings.FREQ_LIST_TIP)
        self.list.setAccessibleName(strings.FREQ_LIST_NAME)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.body.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_button = qpress.room(self._button(strings.FREQ_ADD, strings.FREQ_ADD_TIP, self.pick, row, "primary"))
        self.remove_button = qpress.room(self._button(strings.FREQ_REMOVE, strings.FREQ_REMOVE_NONE_TIP,
                                                      self.ask_remove, row))
        self.remove_button.setEnabled(False)
        row.addStretch(1)
        self.get_button = qpress.room(self._button(strings.FREQ_GET, strings.FREQ_GET_TIP,
                                                   lambda: qpress.open(self, strings.FREQ_GET_URL,
                                                                       control=self.get_button), row))
        self.credit_button = qpress.room(self._button(strings.FREQ_CREDIT, strings.FREQ_CREDIT_TIP,
                                                      lambda: qpress.open(self, strings.FREQ_CREDIT_URL,
                                                                          control=self.credit_button), row, "chip"))
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
        language = self.language
        bridge.run_in_worker(frequency_lists.listed, language,
                             then=self.alive(lambda names: self._show(language, names, then_say)),
                             failed=self.alive(lambda info: self.say(strings.FREQ_READ_FAILED.format(why=info[0]))))

    def _show(self, language, names, line=None):
        if language != self.language:
            return                                        # read for a language the window has left
        names = list(names)
        if names != self.names:                           # repainted only when the lists changed (S19)
            self.names = names
            self.list.clear()
            for name in names:                            # each by its own name (the report's), the file behind it
                item = QListWidgetItem(frequency_lists.display_name(name, language))
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setToolTip(name)
                self.list.addItem(item)
            self.list_paints += 1
        self._selection_changed()
        self.say(line if line is not None else ("" if names else strings.FREQ_EMPTY))

    def language_changed(self, language):
        if self.question is not None:                     # it named the other language's lists: dropped, unanswered
            self.question.drop()
            self.question = None
        self.names = None
        self.list.clear()
        self.read()

    def _selection_changed(self):
        on = bool(self.list.selectedItems()) and (not self.busy() or qpress.mark(self.remove_button) is not None)
        if self.remove_button.isEnabled() != on:
            self.remove_button.setEnabled(on)
            self.remove_button.setToolTip(strings.FREQ_REMOVE_TIP if on else strings.FREQ_REMOVE_NONE_TIP)

    def selected(self):
        """The selected lists' file names, in the list's order."""
        rows = sorted(self.list.row(item) for item in self.list.selectedItems())
        return [self.list.item(r).data(Qt.ItemDataRole.UserRole) for r in rows]

    # --- adding ----------------------------------------------------------------------------------------------- #
    def pick(self):
        if self.busy():
            return                                        # a write under way: a second press opens nothing (P5-A1)
        paths, _f = QFileDialog.getOpenFileNames(self, strings.FREQ_PICK_TITLE, "", strings.FREQ_PICK_FILTER)
        if paths:
            self.add(paths)

    def add(self, paths):
        """Copy `paths` in for the window's language, on a worker."""
        language = self.language
        self._write(self.add_button, _add_all, list(paths), language)

    # --- removing --------------------------------------------------------------------------------------------- #
    def ask_remove(self):
        names = self.selected()
        if not names or self.busy():
            return None
        language = self.language
        one = len(names) == 1
        title = (strings.FREQ_REMOVE_ONE.format(name=frequency_lists.display_name(names[0], language)) if one
                 else strings.FREQ_REMOVE_MANY.format(n=len(names)))
        body = strings.FREQ_REMOVE_BODY_ONE if one else strings.FREQ_REMOVE_BODY_MANY

        def answered(yes):
            self.question = None
            if yes:
                self.remove(names, language)
        self.question = confirm.ask(self, title, body, strings.FREQ_REMOVE_YES, strings.FREQ_REMOVE_YES_TIP,
                                    default_no=True, danger=True, on_answer=answered)
        return self.question

    def remove(self, names, language):
        if language != self.language or self.busy():
            return                                        # asked for another language's lists: nothing moves
        self._write(self.remove_button, _remove_all, list(names), language)

    # --- a write and its line --------------------------------------------------------------------------------- #
    def _write(self, control, fn, names, language):
        """`fn(names, language)` on a worker — `control`'s arc painted first (round 8 row 45: never greyed); a press
        meanwhile starts nothing — then the list read again with its line."""
        if self.busy():
            return
        self.begin_write()
        if qpress.run(control, "freq:write", fn, names, language, win=self,
                      then=lambda lines: self._written(language, lines),
                      failed=lambda info: self._written(language, [str(info[0])])) is None:
            self.end_write()                              # (one under way: the window was busy, nothing started)
        self._writing()

    def _writing(self):
        """While a write is under way the other button is greyed (one at a time); the pressed one keeps its look."""
        add = not self.busy() or qpress.mark(self.add_button) is not None
        if self.add_button.isEnabled() != add:
            self.add_button.setEnabled(add)
        self._selection_changed()

    def _written(self, language, lines):
        line = " · ".join(lines)
        if self.gone:                                     # the window closed meanwhile: the bar says what was done
            if line:
                say_in_bar(self.shell, line)              # (nothing once the main window is gone too)
            return
        self.end_write(line)
        self._writing()                                   # (after: no write under way, so both buttons are back)
        if language == self.language:
            self.read(then_say=line)


def _add_all(paths, language):
    """(A worker.) Each list added; -> the window's lines."""
    added, lines = 0, []
    for src in paths:
        name = os.path.basename(src)
        try:
            name, kept = frequency_lists.add(src, language)
            added += 1
            if kept:
                lines.append(strings.FREQ_KEPT.format(name=frequency_lists.display_name(name, language)))
        except shutil.SameFileError:
            lines.append(strings.FREQ_SAME.format(name=name))
        except OSError as e:
            lines.append(strings.FREQ_ADD_FAILED.format(name=name, why=e.strerror or e))
    return [strings.FREQ_ADDED.format(n=added)] + lines if added else lines


def _remove_all(names, language):
    """(A worker.) Each list moved to the trash folder; -> the window's lines."""
    removed, lines = 0, []
    for name in names:
        try:
            frequency_lists.remove(name, language)
            removed += 1
        except OSError as e:
            lines.append(strings.FREQ_REMOVE_FAILED.format(name=name, why=e.strerror or e))
    return [strings.FREQ_REMOVED.format(n=removed)] + lines if removed else lines
