"""The sentence dictionary window (W3.4 row 1; the Tk dashboard's *Export Sentence Dictionary* dialog, ported).

The dictionary's name, *Show where each sentence came from* (saved alone — `sentence_dictionary_source` — when Export is
pressed with it changed; ✕ / Esc keep the remembered answer), and *Export…*: the library looked at on a worker (empty
→ the line says so, nothing runs), the system's Save-as, then the export as a child (`tools.run("sentence-corpus", …)`:
a job in the bar, waiting for Generate or the indexer, never two at once). **It made the dictionary only on exit 0 and
a fresh file** (`sentence_corpus.export_result`); then the line says what it holds, the one-line Yomitan note (with
"delete the older one in Yomitan first") and *Open folder*; a failure says so with *Open the log*. A run that ends after
the window closed says its line in the bottom bar.
"""
import os
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton

from app import sentence_corpus
from app.qt import bridge, strings
from app.qt.windows import SecondaryWindow, open_url
from app.services import tools

KIND = "sentence-corpus"


def library_has_content(language):
    """(A worker.) Whether the library has files to build from (the Tk dialog's check)."""
    from app.analyzer import resolve_found_files
    return bool(resolve_found_files(language, verbose=False))


class SentenceDictionaryWindow(SecondaryWindow):
    def __init__(self, shell, language=None):
        super().__init__(shell, strings.DICT_NAME, language)
        self.heading = QLabel(sentence_corpus.dictionary_title(self.language), self)
        self.heading.setObjectName("windowheading")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.heading)
        self.source = QCheckBox(strings.DICT_SOURCE, self)
        self.source.setToolTip(strings.DICT_SOURCE_TIP)
        self.source.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.source.blockSignals(True)                    # the remembered answer, loaded (not a click)
        self.source.setChecked(bool(self._settings().get("sentence_dictionary_source")))
        self.source.blockSignals(False)
        self.source.toggled.connect(lambda _on: None)     # read at Export: a tick alone saves nothing
        self.body.addWidget(self.source)
        self.note = QLabel(self)
        self.note.setObjectName("windowline")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note.setVisible(False)
        self.body.addWidget(self.note)
        row = QHBoxLayout()
        self.export_button = self._button(strings.DICT_EXPORT, strings.DICT_EXPORT_TIP, self.export, row, "primary")
        row.addStretch(1)
        self.folder_button = self._button(strings.DICT_OPEN_FOLDER, strings.DICT_OPEN_FOLDER_TIP, self.open_folder, row)
        self.log_button = self._button(strings.DICT_OPEN_LOG, strings.DICT_OPEN_LOG_TIP, self.open_log, row)
        self.folder_button.setVisible(False)
        self.log_button.setVisible(False)
        self.body.addLayout(row)
        self.saved_to = None                              # the last dictionary made
        self.job = None
        self._asked = 0                                   # the newest library look (an older answer is dropped)

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

    def _settings(self):
        return self.shell.services.settings.get()

    def language_changed(self, language):
        self.heading.setText(sentence_corpus.dictionary_title(language))
        self._result(None)

    # --- Export ----------------------------------------------------------------------------------------------- #
    def export(self):
        if self.busy():
            return
        self._asked += 1
        asked, language = self._asked, self.language
        self._exporting(True)
        self.say(strings.DICT_CHECKING)
        bridge.run_in_worker(library_has_content, language,
                             then=self.alive(lambda has: self._looked(asked, language, has)),
                             failed=self.alive(lambda info: self._looked(asked, language, False)))

    def _looked(self, asked, language, has_content):
        if asked != self._asked or self.gone:
            return
        if language != self.language or not has_content:
            self._exporting(False)
            if language == self.language:
                self.say(strings.DICT_EMPTY)
            return
        title = sentence_corpus.dictionary_title(language)
        path, _f = QFileDialog.getSaveFileName(self, strings.DICT_SAVE_TITLE, f"{title}.zip", strings.DICT_SAVE_FILTER)
        if not path:                                      # Cancel: nothing saved, nothing runs
            self._exporting(False)
            if language == self.language:
                self.say("")
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        show_source = self.source.isChecked()
        if show_source != bool(self._settings().get("sentence_dictionary_source")):
            self.shell.services.settings.set({"sentence_dictionary_source": show_source})    # the one key, alone
        self.start(language, path, show_source)

    def start(self, language, path, show_source):
        """The export as a child job; its end comes back through a relay on the main window (it outlives this one)."""
        title = sentence_corpus.dictionary_title(language)
        started = time.time()
        relay = bridge.Relay(parent=self.shell)
        relay.said.connect(lambda code: self._ended(relay, language, title, path, started, code))
        settings = self.shell.services.settings
        self.say(strings.DICT_RUNNING.format(title=title))
        self.job = tools.run(self.shell.services.registry, KIND, strings.DICT_JOB,
                             sentence_corpus.export_command(language, path, show_source),
                             before=lambda: settings.flush(10.0), on_end=relay.call)
        return self.job

    def _ended(self, relay, language, title, path, started, code):
        relay.deleteLater()
        made, summary = sentence_corpus.export_result(path, started, code)
        line = strings.DICT_READY.format(title=title, summary=summary).strip() if made else strings.DICT_FAILED
        self.job = None
        if self.gone:                                     # the window closed meanwhile: the bar says it
            bar = getattr(self.shell, "bar_line", None)
            if bar is not None:
                bar.set_full(line)
            return
        self._exporting(False, line)
        if not self.gone and self.language == language:   # a switch that waited for the run has cleared the window
            self._result((made, line, path))

    def _result(self, result):
        """The last run's line, note and buttons (None: cleared)."""
        made, line, path = result if result is not None else (None, "", None)
        self.saved_to = path if made else None
        self.say(line)
        note = strings.DICT_NOTE.format(file=path) if made else ""
        if self.note.text() != note:
            self.note.setText(note)
            self.note.setVisible(bool(note))
        self.folder_button.setVisible(bool(made))
        self.log_button.setVisible(made is False)

    def _exporting(self, on, line=None):
        """A run under way (Export off) — or over, with its line (a language switch that waited for it happens)."""
        if on:
            self.begin_write()
        else:
            self.end_write(line)
        self.export_button.setEnabled(not on)
        self.export_button.setToolTip(strings.DICT_EXPORT_BUSY_TIP if on else strings.DICT_EXPORT_TIP)

    def open_folder(self):
        if self.saved_to:
            open_url(os.path.dirname(self.saved_to))

    def open_log(self):
        open_url(tools.log_path(KIND))
