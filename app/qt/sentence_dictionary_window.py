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

from PyQt6.QtCore import QDir, Qt
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton

from app import sentence_corpus
from app.qt import bridge, confirm, strings
from app.qt.windows import SecondaryWindow, open_url, say_in_bar
from app.services import jobs as jobs_module
from app.services import tools

KIND = "sentence-corpus"
WAITS_FOR = "waits for "                                 # the registry's reason for a job held back by another


def library_has_content(language):
    """(A worker.) Whether the library has files to build from (`sentence_corpus.has_sources`, the Tk dialog's check)."""
    return sentence_corpus.has_sources(language)


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
        # The wiring check's one waiver: the box is read at Export (a tick alone saves nothing), so its signal goes
        # nowhere on purpose — never a pattern for a control that does nothing.
        self.source.toggled.connect(lambda _on: None)
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
        self._job_state = None                            # (state, reason) of its job as last shown
        heard = getattr(shell, "bridge", None)
        if heard is not None:
            heard.jobs_changed.connect(self._follow)

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
        moved = self._language_waiting not in (None, language)     # the main window switched while it looked
        if language != self.language or moved or not has_content:
            self._exporting(False)                        # (a switch that waited happens now)
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
        if path.lower().endswith(".zip"):                 # the OS asked about this very name already
            self._chosen(language, path)
            return
        path += ".zip"                                    # a name it never asked about: is one there? (a worker)
        bridge.run_in_worker(os.path.exists, path, then=self.alive(lambda taken: self._suffixed(language, path, taken)),
                             failed=self.alive(lambda info: self._suffixed(language, path, True)))

    def _suffixed(self, language, path, taken):
        if not taken:
            self._chosen(language, path)
            return

        def answered(yes):
            if yes and language == self.language:
                self._chosen(language, path)
            else:
                self._exporting(False)
                self.say("")
        confirm.ask(self, strings.DICT_REPLACE_ONE.format(name=os.path.basename(path)), strings.DICT_REPLACE_BODY,
                    strings.DICT_REPLACE_YES, strings.DICT_REPLACE_YES_TIP, default_no=True, danger=True,
                    on_answer=answered)

    def _chosen(self, language, path):
        show_source = self.source.isChecked()
        if show_source != bool(self._settings().get("sentence_dictionary_source")):
            self.shell.services.settings.set({"sentence_dictionary_source": show_source})    # the one key, alone
        self.start(language, path, show_source)

    def start(self, language, path, show_source):
        """The export as a child job. Its end is judged on the tool's thread (the file's time and index read there, a
        stopped run's `.tmp` removed) and comes back through a relay on the main window (it outlives this one)."""
        title = sentence_corpus.dictionary_title(language)
        clock = {"started": time.time()}                  # moved to the child's start, in `before`
        relay = bridge.Relay(parent=self.shell)
        relay.said.connect(lambda outcome: self._ended(relay, language, title, path, outcome))
        settings = self.shell.services.settings

        def before():                                     # (the tool's thread) settings first, then the clock
            settings.flush(10.0)
            clock["started"] = time.time()

        def judged(result):                               # (the tool's thread)
            try:
                outcome = sentence_corpus.export_outcome(path, clock["started"], result.code, result.cancelled)
            except Exception:
                outcome = ("stopped" if result.cancelled else "failed", "")
            relay.call(outcome)
        self.say(strings.DICT_RUNNING.format(title=title))
        self.job = tools.run(self.shell.services.registry, KIND, strings.DICT_JOB,
                             sentence_corpus.export_command(language, path, show_source),
                             before=before, on_result=judged)
        self._job_state = None
        self._follow(self.shell.services.registry.snapshot())
        return self.job

    def _follow(self, views):
        """The registry's newest snapshot: while its job waits, the line says what for (IK-22); once it runs, that it
        builds. Repainted only when the job's state changed."""
        job = self.job
        if job is None or self.gone:
            return
        view = next((v for v in views if v.id == job.id), None)
        if view is None or (view.state, view.reason) == self._job_state:
            return
        self._job_state = (view.state, view.reason)
        if view.state == jobs_module.WAITING:
            reason = view.reason or ""
            self.say(strings.DICT_WAITING_FOR.format(what=reason[len(WAITS_FOR):]) if reason.startswith(WAITS_FOR)
                     else strings.DICT_WAITING.format(reason=reason))
        elif view.state == jobs_module.RUNNING:
            self.say(strings.DICT_RUNNING.format(title=sentence_corpus.dictionary_title(self.language)))

    def _ended(self, relay, language, title, path, outcome):
        try:
            relay.deleteLater()
        except RuntimeError:                              # gone with the main window already
            pass
        state, summary = outcome
        line = {"made": strings.DICT_READY.format(title=title, summary=summary).strip(),
                "stopped": strings.DICT_STOPPED}.get(state, strings.DICT_FAILED)
        self.job = None
        if self.gone:                                     # the window closed meanwhile: the bar says it
            say_in_bar(self.shell, line)
            return
        self._exporting(False, line)
        if not self.gone and self.language == language:   # a switch that waited for the run has cleared the window
            self._result((state, line, path))

    def _result(self, result):
        """The last run's line, note and buttons (None: cleared). A stopped run offers no log: nothing went wrong."""
        state, line, path = result if result is not None else (None, "", None)
        made = state == "made"
        self.saved_to = path if made else None
        self.say(line)
        note = strings.DICT_NOTE if made else ""
        tip = strings.DICT_NOTE_TIP.format(file=QDir.toNativeSeparators(path)) if made else ""
        if self.note.text() != note or self.note.toolTip() != tip:
            self.note.setText(note)
            self.note.setToolTip(tip)
            self.note.setVisible(bool(note))
        self.folder_button.setVisible(made)
        self.log_button.setVisible(state == "failed")

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
