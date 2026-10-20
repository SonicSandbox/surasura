"""The known-word importers (.apkg, Migaku, Jiten) and Extract, in Qt (W3.4 row 2; the RUNBOOK's row 2; the
inventory `inv-importers.md` §1–§4).

Four secondary windows, each one of a kind, each painting what `app/importers_view.py` decides. The work never runs
on this thread: a deck's fields and a Migaku export's word count are read on a worker (`bridge.run_in_worker`); the
imports, the Jiten fetch and Extract run as children (`app/services/tools.py`), jobs of the registry — `known-import`
(it shares `known-words` with the Anki sync) or `extract`. A child's lines reach the status line through a `Relay`;
its exit code decides; a failure offers *Open the log*. Replacing imports (Migaku, Jiten) read first and then ask once
with both numbers (IK-18), Cancel the default; the .apkg import asks once, naming what it adds. Jiten's key goes to
its child **by environment only** and is never saved. Closing a window never stops its child: the job carries on and
the bar shows its end.
"""
import os
import shutil
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QWidget)

from app import anki_db_import, extract, importers_view
from app.qt import bridge, confirm, strings, windows
from app.services import jobs as jobs_module, tools

PREVIEW_LINES = 4


WAITS_FOR = "waits for "                                 # the registry's reason for a job held back by another


def _pick_file(parent, title, filters):
    """The OS's own file picker (allowed by the RUNBOOK) -> a path or ""."""
    path, _chosen = QFileDialog.getOpenFileName(parent, title, "", filters)
    return path


def _button(parent, text, tip, slot, kind=None):
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    b.setAccessibleName(text)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if kind:
        b.setProperty("kind", kind)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _line(parent, text, name="windowline"):
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _kept(plan):
    """A replace's kept lines for its confirmation: past Graduates' and dismissed words, each only when there are any
    (never "0 … kept")."""
    return "".join(f"\n{lines[n != 1].format(n=n)}." for lines, n in ((strings.KEPT_GRADUATED, plan.graduated),
                                                                     (strings.KEPT_IGNORED, plan.ignored)) if n)


def _remove(kept):
    """A destroyed Jiten window's fetched cards (`kept[0]`, its folder): removed — the app quitting with the question
    open destroys the window with its main window, with no closeEvent."""
    folder, kept[0] = kept[0], None
    if folder:
        shutil.rmtree(folder, ignore_errors=True)


def _row(*widgets, stretch_at=None):
    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    for n, w in enumerate(widgets):
        box.addWidget(w, 1 if n == stretch_at else 0)
    return box


def _preview(parent, name):
    text = QPlainTextEdit(parent)
    text.setReadOnly(True)
    text.setAccessibleName(name)
    text.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    text.setMaximumHeight(text.fontMetrics().lineSpacing() * (PREVIEW_LINES + 1) + 12)
    return text


class ToolWindow(windows.SecondaryWindow):
    """A window whose writes are children: `_run` starts one as a job, its lines to the status line, its end to
    `done(code)`; *Open the log* shows after a run failed."""
    kind = "known-import"

    def __init__(self, shell, name, language=None):
        super().__init__(shell, name, language)
        self._lines = []
        self._result = None
        self.question = None                              # the open confirmation, dropped by a language switch
        self.child = None                                 # the child's job, followed while it waits (IK-58)
        self._job_state = None
        heard = getattr(shell, "bridge", None)
        if heard is not None:
            heard.jobs_changed.connect(self._follow)
        self.log_button = _button(self, strings.IMPORTERS_LOG, strings.IMPORTERS_LOG_TIP, self._open_log, "chip")
        self.log_button.setVisible(False)
        self.layout().addWidget(self.log_button, 0, Qt.AlignmentFlag.AlignRight)

    def _open_log(self):
        windows.open_url(tools.log_path(self.kind))

    def _run(self, label, argv, done, env=None, parse=None, after=None, on_quit="wait"):
        """`argv` as a child job of this window's kind. `parse(line)` -> a result or None (its RESULT line);
        `after(code)` runs on the tool's thread when it ends, the window open or not (a temporary file's cleanup).
        `on_quit`: a writer finishes before the app quits (`wait`: never cut between its backup or copy and its
        write); a child that only reads is cancelled."""
        self._lines, self._result = [], None
        lines, end = bridge.Relay(self), bridge.Relay(self)

        def line(text):
            found = parse(text) if parse is not None else None
            if found is not None:
                self._result = found
                return
            self._lines.append(text)
            if text.strip() and not text.startswith(" "):
                self.say(text.strip())

        def ended(code):
            self.log_button.setVisible(code != 0)
            done(code)                                    # it ends the write (`end_write`)
            self.refresh()

        lines.said.connect(self.alive(line))
        end.said.connect(self.alive(ended))

        def on_end(code):
            end.call(code)
            if after is not None:
                after(code)
        self.log_button.setVisible(False)
        self.begin_write()
        self.refresh()
        self.say(strings.IMPORTERS_BUSY)
        self.child = tools.run(self.shell.services.registry, self.kind, label, argv, env=env, on_line=lines.call,
                               on_end=on_end, on_quit=on_quit)
        self._job_state = None
        self._follow(self.shell.services.registry.snapshot())
        return self.child

    def _follow(self, views):
        """The registry's newest snapshot: while the child's job waits its turn (a sync holds the known words), the
        line says what runs first; once it runs, that it works. Repainted only when its state changed."""
        job = self.child
        if job is None or self.gone or not hasattr(job, "id"):
            return
        view = next((v for v in views if v.id == job.id), None)
        if view is None or (view.state, view.reason) == self._job_state:
            return
        self._job_state = (view.state, view.reason)
        if view.state == jobs_module.WAITING:
            reason = view.reason or ""
            self.say(strings.IMPORTERS_WAITING_FOR.format(what=reason[len(WAITS_FOR):]) if reason.startswith(WAITS_FOR)
                     else strings.IMPORTERS_WAITING.format(reason=reason))
        elif view.state == jobs_module.RUNNING:
            self.say(strings.IMPORTERS_BUSY)

    def ask(self, title, body, yes, yes_tip, on_answer, **how):
        """`confirm.ask` in this window, kept as `question` until it is answered or dropped."""
        self.question = confirm.ask(self, title, body, yes, yes_tip, on_answer=on_answer, **how)
        return self.question

    def language_changed(self, language):
        """The open question named the other language's numbers: dropped, unanswered (AD1-12's rule)."""
        if self.question is not None:
            self.question.drop()
            self.question = None

    def _why(self):
        """The last line the child printed that says why it failed, or None."""
        for text in reversed(self._lines):
            why = importers_view.error_of(text)
            if why:
                return why
        return None

    def _wrote(self):
        """Known words written: the bar's count and the journey asked again (the automation, once it is made)."""
        automation = getattr(self.shell.services, "automation", None)
        if automation is not None:
            automation.known_changed()

    def _failed_line(self, why):
        return strings.IMPORTERS_FAILED.format(why=why) if why else strings.IMPORTERS_FAILED_PLAIN

    def refresh(self):
        """A subclass enables its controls for what it holds now."""


# --- .apkg known words (inv §2) ----------------------------------------------------------------------------------- #
class DeckWindow(ToolWindow):
    """Every word in one field of an exported deck becomes a known word (`anki_db_import`)."""

    def __init__(self, shell, language=None):
        super().__init__(shell, strings.APKG_NAME, language)
        self.deck = None
        self._reading = None
        self.body.addWidget(_line(self, strings.APKG_LINE))
        self.path = QLineEdit(self)
        self.path.setPlaceholderText(strings.APKG_FILE_HINT)
        self.path.setAccessibleName(strings.APKG_FILE_NAME)
        self.path.editingFinished.connect(lambda: self.choose(self.path.text().strip()))
        self.browse = _button(self, strings.APKG_BROWSE, strings.APKG_BROWSE_TIP, self._browse)
        self.body.addLayout(_row(self.path, self.browse, stretch_at=0))
        self.field = QComboBox(self)
        self.field.setAccessibleName(strings.APKG_FIELD_NAME)
        self.field.currentTextChanged.connect(lambda _t: self._show_sample())
        self.sample = _preview(self, strings.APKG_PREVIEW_NAME)
        self.body.addWidget(self.field)
        self.body.addWidget(self.sample)
        self.body.addWidget(_line(self, strings.APKG_EVERY_NOTE))
        self.go = _button(self, strings.APKG_IMPORT, strings.APKG_IMPORT_TIP, self._ask, "primary")
        self.body.addWidget(self.go, 0, Qt.AlignmentFlag.AlignRight)
        self.refresh()

    def _browse(self):
        path = _pick_file(self, strings.APKG_PICK_TITLE, strings.APKG_PICK_FILTER)
        if path:
            self.path.setText(path)
            self.choose(path)

    def choose(self, path):
        """A deck chosen: its fields read on a worker (a later choice wins)."""
        if path == self._reading or (self.deck is not None and path == getattr(self, "_deck_path", None)):
            return
        self.deck, self._deck_path = None, None
        self.field.clear()
        self.sample.setPlainText("")
        self.refresh()
        if not importers_view.is_deck(path):
            self._reading = None
            self.say(strings.APKG_NOT_A_DECK if path else "")
            return
        self._reading = path
        self.say(strings.APKG_READING)
        bridge.run_in_worker(anki_db_import.read_deck, path, then=self.alive(lambda d, p=path: self._read(p, d)),
                             failed=self.alive(lambda info, p=path: self._unread(p, info[0])))

    def _read(self, path, deck):
        if path != self._reading:
            return                                        # a later choice is being read
        self._reading = None
        self.deck, self._deck_path = deck, path
        self.field.blockSignals(True)
        self.field.addItems(deck.fields)
        if deck.default:
            self.field.setCurrentText(deck.default)
        self.field.blockSignals(False)
        self._show_sample()
        self.say(strings.APKG_READ.format(notes=deck.notes, fields=len(deck.fields)))
        self.refresh()

    def _unread(self, path, error):
        if path != self._reading:
            return
        self._reading = None
        self.say(strings.IMPORTERS_READ_FAILED.format(why=error))
        self.refresh()

    def _show_sample(self):
        text = self.deck.samples.get(self.field.currentText(), "") if self.deck is not None else ""
        if self.sample.toPlainText() != text:
            self.sample.setPlainText(text)
        self.refresh()

    def refresh(self):
        has = self.deck is not None
        self.field.setVisible(has)
        self.sample.setVisible(has)
        self.go.setEnabled(importers_view.can_import_deck(self._deck_path if has else None, self.deck,
                                                          self.field.currentText(), self.busy()))
        self.browse.setEnabled(not self.busy())

    def _ask(self):
        if not self.go.isEnabled():
            return
        field, deck, path, language = self.field.currentText(), self.deck, self._deck_path, self.language
        self.ask(strings.APKG_ASK_TITLE.format(language=strings.LANGUAGE_NAMES.get(language, language)),
                 strings.APKG_ASK_BODY.format(field=field, notes=deck.notes),
                 strings.APKG_ASK_YES, strings.APKG_ASK_YES_TIP,
                 on_answer=lambda yes: yes and self.start(path, field, language))

    def start(self, path, field, language):
        """The import as a child (`apkg_known_import`), in the language it was asked in."""
        return self._run(strings.APKG_NAME, ["anki_db_import.py", "--language", language, f"--file={path}",
                                             f"--field={field}"], self._done, parse=anki_db_import.parse_result)

    def _done(self, code):
        key, values = importers_view.deck_outcome(code, self._result, self._why())
        line = {"done": lambda: strings.APKG_DONE.format(**values), "nothing": lambda: strings.APKG_NOTHING,
                "failed": lambda: self._failed_line(values["why"])}[key]()
        if key == "done":
            self._wrote()
        self.say(line)
        self.end_write(line)


# --- Migaku (inv §3) ------------------------------------------------------------------------------------------------ #
class MigakuWindow(ToolWindow):
    """Migaku's database export replaces the known words (`migaku_converter`), after one confirmation with both
    numbers."""

    def __init__(self, shell, language=None):
        from app import migaku_converter
        super().__init__(shell, strings.MIGAKU_NAME, language)
        self.body.addWidget(_line(self, strings.MIGAKU_STEP1))
        self.code = QLineEdit(migaku_converter.CONSOLE_CODE, self)
        self.code.setReadOnly(True)
        self.code.setAccessibleName(strings.MIGAKU_CODE_NAME)
        self.copy = _button(self, strings.MIGAKU_COPY, strings.MIGAKU_COPY_TIP, self._copy)
        self.body.addLayout(_row(self.code, self.copy, stretch_at=0))
        self.body.addWidget(_line(self, strings.MIGAKU_STEP2))
        self.find = _button(self, strings.MIGAKU_FIND, strings.MIGAKU_FIND_TIP, self.find_it)
        self.choose = _button(self, strings.MIGAKU_CHOOSE, strings.MIGAKU_CHOOSE_TIP, self._choose)
        self.body.addLayout(_row(self.find, self.choose))
        self.refresh()

    def _copy(self):
        QApplication.clipboard().setText(self.code.text())
        self.say(strings.MIGAKU_COPIED)

    def find_it(self, folder=None):
        self.say(strings.MIGAKU_LOOKING)
        bridge.run_in_worker(importers_view.find_migaku, folder, then=self.alive(self._found),
                             failed=self.alive(lambda info: self.say(strings.IMPORTERS_READ_FAILED.format(why=info[0]))))

    def _found(self, answer):
        path, count = answer
        if path is None:
            self.say(strings.MIGAKU_NOT_MIGAKU if count else strings.MIGAKU_NO_DB)
            return
        self.read(path)

    def _choose(self):
        path = _pick_file(self, strings.MIGAKU_PICK_TITLE, strings.MIGAKU_PICK_FILTER)
        if path:
            self.read(path)

    def read(self, path):
        """Read the export's words first (a worker), then ask with both numbers."""
        language = self.language
        bridge.run_in_worker(importers_view.migaku_plan, path, language,
                             then=self.alive(lambda plan: self._ask(plan, language)), failed=self.alive(self._unread))

    def _unread(self, info):
        from app import migaku_converter
        error = info[0]
        self.say(strings.MIGAKU_NOT_A_DB if isinstance(error, migaku_converter.NotMigaku)
                 else strings.KNOWN_UNREADABLE if isinstance(error, importers_view.KnownUnreadable)
                 else strings.IMPORTERS_READ_FAILED.format(why=error))

    def _ask(self, plan, language):
        if language != self.language:
            return                                        # read for the language the window has left
        if not plan.words:
            self.say(strings.MIGAKU_EMPTY)
            return
        saved = plan.saved.strftime(strings.MIGAKU_SAVED) if plan.saved else strings.MIGAKU_SAVED_UNKNOWN
        body = strings.MIGAKU_ASK_BODY.format(file=os.path.basename(plan.path), time=saved, now=plan.now,
                                              after=plan.after, kept=_kept(plan))
        self.ask(strings.MIGAKU_ASK_TITLE.format(language=strings.LANGUAGE_NAMES.get(language, language)), body,
                 strings.MIGAKU_ASK_YES, strings.MIGAKU_ASK_YES_TIP,
                 default_no=True, danger=True,
                 on_answer=lambda yes: yes and self.start(plan.path, language, importers_view.expect_arg(plan)))

    def start(self, path, language, expect=None):
        """The replace as a child, in the language its numbers were read for; `expect`: those numbers (moved by the
        time it holds the lock, it writes nothing and the window asks again)."""
        argv = ["migaku_converter.py", path, "--language", language] + (["--expect", expect] if expect else [])
        return self._run(strings.MIGAKU_NAME, argv, lambda code: self._done(code, path, language))

    def _done(self, code, path=None, language=None):
        key, values = importers_view.replace_outcome(code, self._why())
        if key == "changed":
            self.say(strings.KNOWN_CHANGED)
            self.end_write()
            if path and language == self.language:
                self.read(path)                           # the numbers as they are now, asked again
            return
        line = strings.MIGAKU_DONE if key == "done" else self._failed_line(values["why"])
        if key == "done":
            self._wrote()
        self.say(line)
        self.end_write(line)

    def refresh(self):
        for b in (self.find, self.choose):
            b.setEnabled(not self.busy())


# --- Jiten (inv §4) -------------------------------------------------------------------------------------------------- #
class JitenWindow(ToolWindow):
    """Jiten's words replace the known words (`jiten_converter`): fetched first in a child (the key by environment
    only), then one confirmation with both numbers, then the replace from the fetched cards (no second fetch).
    Japanese only."""

    def __init__(self, shell, language=None):
        super().__init__(shell, strings.JITEN_NAME, language)
        self._kept = [None]                               # the fetched cards' folder (`_folder`), in a box the
        self.destroyed.connect(lambda *_a, kept=self._kept: _remove(kept))   # window's end empties, close or not
        self.key = QLineEdit(self)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(strings.JITEN_KEY_HINT)
        self.key.setAccessibleName(strings.JITEN_KEY_NAME)
        self.key.textChanged.connect(lambda _t: self.refresh())
        self.show_key = QCheckBox(strings.JITEN_SHOW, self)
        self.show_key.setProperty("kind", "toggle")
        self.show_key.setToolTip(strings.JITEN_SHOW_TIP)
        self.show_key.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.show_key.toggled.connect(self._show)
        self.get_key = _button(self, strings.JITEN_GET_KEY, strings.JITEN_GET_KEY_TIP,
                               lambda: windows.open_url(strings.JITEN_URL))
        self.body.addLayout(_row(self.key, self.show_key, self.get_key, stretch_at=0))
        self.go = _button(self, strings.JITEN_IMPORT, strings.JITEN_IMPORT_TIP, self.fetch, "primary")
        self.credit = _button(self, strings.JITEN_CREDIT, strings.JITEN_CREDIT_TIP,
                              lambda: windows.open_url(strings.JITEN_CREDIT_URL), "chip")
        line = QHBoxLayout()
        line.addWidget(self.credit)
        line.addStretch(1)
        line.addWidget(self.go)
        self.body.addLayout(line)
        self.refresh()
        self.language_changed(self.language)

    @property
    def _folder(self):
        return self._kept[0]

    @_folder.setter
    def _folder(self, folder):
        self._kept[0] = folder

    def _show(self, on):
        self.key.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)

    def language_changed(self, language):
        if self.question is not None:                     # Japanese only: the question and its cards go
            super().language_changed(language)
            self._drop_folder()
        self.say("" if language == "ja" else strings.JITEN_JAPANESE_ONLY)
        self.refresh()

    def refresh(self):
        self.go.setEnabled(self.language == "ja" and bool(self.key.text().strip()) and not self.busy())

    def fetch(self):
        """Step 1: the cards fetched into a folder of this window's own (the key in the child's environment)."""
        from app import jiten_converter
        if self.language != "ja":
            self.say(strings.JITEN_JAPANESE_ONLY)
            return None
        key = self.key.text().strip()
        if not key:
            self.say(strings.JITEN_NO_KEY)
            return None
        self._drop_folder()
        self._folder = tempfile.mkdtemp(prefix="surasura-jiten-")
        cards = os.path.join(self._folder, "cards.json")
        folder = self._folder

        def after(code):
            # On the tool's thread: the cards are kept only for a window still open to ask about them
            if code != 0 or self.gone:
                shutil.rmtree(folder, ignore_errors=True)
        job = self._run(strings.JITEN_NAME, ["jiten_converter.py", "--language", "ja", "--save-cards", cards],
                        lambda code: self._fetched(code, cards), env={jiten_converter.API_KEY_ENV: key}, after=after,
                        on_quit="cancel")
        self.say(strings.JITEN_FETCHING)
        return job

    def _fetched(self, code, cards):
        if code != 0:
            self._folder = None                           # removed by the fetch's `after`
            line = self._failed_line(self._why())
            self.say(line)
            self.end_write(line)
            return
        self.end_write()
        bridge.run_in_worker(importers_view.jiten_plan, cards, "ja", then=self.alive(self._ask),
                             failed=self.alive(self._unplanned))

    def _unplanned(self, info):
        """The fetched cards or the known words couldn't be read: said, nothing asked, the cards removed."""
        error = info[0]
        self.say(strings.KNOWN_UNREADABLE if isinstance(error, importers_view.KnownUnreadable)
                 else strings.IMPORTERS_READ_FAILED.format(why=error))
        self._drop_folder()

    def _ask(self, plan):
        if self.language != "ja":
            self._drop_folder()                           # the window left Japanese while the cards were read
            return
        if plan is None or not plan.words:
            self.say(strings.JITEN_EMPTY)
            self._drop_folder()
            return
        body = strings.JITEN_ASK_BODY.format(now=plan.now, after=plan.after, kept=_kept(plan))

        def answered(yes):
            if yes:
                self.replace(plan.path, importers_view.expect_arg(plan))
            else:
                self._drop_folder()
        self.ask(strings.JITEN_ASK_TITLE, body, strings.JITEN_ASK_YES, strings.JITEN_ASK_YES_TIP,
                 default_no=True, danger=True, on_answer=answered)

    def replace(self, cards, expect=None):
        """Step 2: the replace from the cards step 1 kept (no key, no fetch); `expect`: the numbers confirmed."""
        from app import anki_sync
        folder = self._folder
        self._folder = None                               # the child's now: removed when it ends

        def after(code):
            # On the tool's thread: the numbers moved — the cards stay for the window to ask again, if it is open
            if code == anki_sync.EXIT_CHANGED and not self.gone:
                self._folder = folder
            elif folder:
                shutil.rmtree(folder, ignore_errors=True)
        argv = ["jiten_converter.py", "--language", "ja", "--cards", cards] + (["--expect", expect] if expect else [])
        return self._run(strings.JITEN_NAME, argv, lambda code: self._done(code, cards, folder), after=after)

    def _done(self, code, cards=None, folder=None):
        key, values = importers_view.replace_outcome(code, self._why())
        if key == "changed":
            self.say(strings.KNOWN_CHANGED)
            self.end_write()
            self._folder = folder or self._folder         # kept by `after`, whichever of the two comes first
            if cards and self._folder:
                self._fetched(0, cards)                   # the same cards, the numbers as they are now
            return
        line = strings.JITEN_DONE if key == "done" else self._failed_line(values["why"])
        if key == "done":
            self._wrote()
        self.say(line)
        self.end_write(line)

    def _drop_folder(self, closing=False):
        """The fetched cards' folder removed — never under a fetch still writing it, unless the window is closing (the
        fetch's `after` removes what it writes then)."""
        if self._folder and (closing or not self.busy()):
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None

    def closeEvent(self, event):
        self.key.clear()
        self._drop_folder(closing=True)
        super().closeEvent(event)


# --- Extract (inv §1) -------------------------------------------------------------------------------------------- #
class ExtractWindow(ToolWindow):
    """A file split into parts and added to the chosen section (`app/extract.py`, in a child)."""
    kind = "extract"

    def __init__(self, shell, language=None):
        super().__init__(shell, strings.EXTRACT_NAME, language)
        self.deck = None
        self._deck_path = None
        self._reading = None
        settings = shell.services.settings.get()
        self._length = str(settings.get("split_length", extract.DEFAULT_LENGTH) or extract.DEFAULT_LENGTH)
        self.path = QLineEdit(self)
        self.path.setPlaceholderText(strings.EXTRACT_FILE_HINT)
        self.path.setAccessibleName(strings.EXTRACT_FILE_NAME)
        self.path.editingFinished.connect(lambda: self.choose(self.path.text().strip()))
        self.browse = _button(self, strings.EXTRACT_BROWSE, strings.EXTRACT_BROWSE_TIP, self._browse)
        self.body.addLayout(_row(self.path, self.browse, stretch_at=0))
        self.name = QLineEdit(self)
        self.name.setPlaceholderText(strings.EXTRACT_OUT_HINT)
        self.name.setAccessibleName(strings.EXTRACT_OUT_NAME)
        self.name.textChanged.connect(lambda _t: self.refresh())
        self.body.addWidget(self.name)

        # the split (anything but a deck)
        self.split_box = QWidget(self)
        split = QHBoxLayout(self.split_box)
        split.setContentsMargins(0, 0, 0, 0)
        self.by_length = QRadioButton(strings.EXTRACT_BY_LENGTH, self.split_box)
        self.by_pattern = QRadioButton(strings.EXTRACT_BY_PATTERN, self.split_box)
        self.by_length.setToolTip(strings.EXTRACT_BY_LENGTH_TIP)
        self.by_pattern.setToolTip(strings.EXTRACT_BY_PATTERN_TIP)
        self.methods = QButtonGroup(self.split_box)
        for r in (self.by_length, self.by_pattern):
            r.setProperty("kind", "choice")
            r.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.methods.addButton(r)
            split.addWidget(r)
        self.by_length.setChecked(True)
        self.by_length.toggled.connect(self._method_changed)
        self.by_pattern.toggled.connect(lambda _on: self.refresh())
        self.value = QLineEdit(self._length, self.split_box)
        self.value.setAccessibleName(strings.EXTRACT_VALUE_NAME)
        split.addWidget(self.value, 1)
        self.body.addWidget(self.split_box)
        self.group_box = QWidget(self)
        group = QHBoxLayout(self.group_box)
        group.setContentsMargins(0, 0, 0, 0)
        self.group = QCheckBox(strings.EXTRACT_GROUP, self.group_box)
        self.group.setProperty("kind", "toggle")
        self.group.setToolTip(strings.EXTRACT_GROUP_TIP)
        self.group.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.group.toggled.connect(lambda on: self.parts.setEnabled(on))
        self.parts = QSpinBox(self.group_box)
        self.parts.setRange(1, 999)
        self.parts.setValue(extract.DEFAULT_PARTS)
        self.parts.setAccessibleName(strings.EXTRACT_PARTS_NAME)
        self.parts.setEnabled(False)
        group.addWidget(self.group)
        group.addWidget(self.parts)
        group.addStretch(1)
        self.body.addWidget(self.group_box)

        # a deck
        self.deck_box = QWidget(self)
        deck = QHBoxLayout(self.deck_box)
        deck.setContentsMargins(0, 0, 0, 0)
        self.field = QComboBox(self.deck_box)
        self.field.setAccessibleName(strings.EXTRACT_FIELD_NAME)
        self.field.currentTextChanged.connect(lambda _t: self._show_sample())
        self.understand = QCheckBox(strings.EXTRACT_UNDERSTAND, self.deck_box)
        self.understand.setProperty("kind", "toggle")
        self.understand.setToolTip(strings.EXTRACT_UNDERSTAND_TIP)
        self.understand.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.understand.toggled.connect(lambda _on: self.refresh())
        deck.addWidget(self.field, 1)
        deck.addWidget(_line(self.deck_box, strings.EXTRACT_DECK_LINE))
        deck.addWidget(self.understand)
        self.body.addWidget(self.deck_box)
        self.sample = _preview(self, strings.EXTRACT_PREVIEW_NAME)
        self.body.addWidget(self.sample)

        # where it goes, and the button
        self.section = QComboBox(self)
        self.section.setAccessibleName(strings.EXTRACT_SECTION_NAME)
        for tier in extract.SECTIONS:
            self.section.addItem(strings.EXTRACT_SECTIONS[tier], tier)
        self.go = _button(self, strings.EXTRACT_GO, strings.EXTRACT_GO_TIP, self.check, "primary")
        line = QHBoxLayout()
        line.addWidget(self.section)
        line.addStretch(1)
        line.addWidget(self.go)
        self.body.addLayout(line)
        self.refresh()

    def _browse(self):
        path = _pick_file(self, strings.EXTRACT_PICK_TITLE, strings.EXTRACT_PICK_FILTER)
        if path:
            self.path.setText(path)
            self.choose(path)

    def choose(self, path):
        """A file chosen: its name offered for the folder; a deck's fields read on a worker."""
        if not self.name.text().strip() and path:
            self.name.setText(importers_view.default_name(path))
        if importers_view.is_deck(path) and path in (self._reading, self._deck_path):
            self.refresh()
            return
        self.deck, self._deck_path = None, None
        self.field.clear()
        self.sample.setPlainText("")
        self._reading = None
        if importers_view.is_deck(path):
            self._reading = path
            self.say(strings.APKG_READING)
            bridge.run_in_worker(anki_db_import.read_deck, path, 10,
                                 then=self.alive(lambda d, p=path: self._read(p, d)),
                                 failed=self.alive(lambda info, p=path: self._unread(p, info[0])))
        else:
            self.say("")
        self.refresh()

    def _read(self, path, deck):
        if path != self._reading:
            return
        self._reading = None
        self.deck, self._deck_path = deck, path
        self.field.blockSignals(True)
        self.field.addItems(deck.fields)
        default = importers_view.extract_field(deck.fields)
        if default:
            self.field.setCurrentText(default)
        else:
            self.field.setCurrentIndex(-1)
        self.field.blockSignals(False)
        self._show_sample()
        self.say(strings.APKG_READ.format(notes=deck.notes, fields=len(deck.fields)))

    def _unread(self, path, error):
        if path != self._reading:
            return
        self._reading = None
        self.say(strings.IMPORTERS_READ_FAILED.format(why=error))
        self.refresh()

    def _show_sample(self):
        text = self.deck.samples.get(self.field.currentText(), "") if self.deck is not None else ""
        if self.sample.toPlainText() != text:
            self.sample.setPlainText(text)
        self.refresh()

    def _method_changed(self, by_length):
        value = importers_view.split_value(by_length, self.value.text(), self._length)
        if value is not None:
            self.value.setText(value)

    def refresh(self):
        path = self.path.text().strip()
        deck = importers_view.is_deck(path)
        self.split_box.setVisible(not deck)
        self.group_box.setVisible(not deck)
        self.deck_box.setVisible(deck)
        self.sample.setVisible(deck and self.deck is not None)
        self.go.setEnabled(importers_view.can_extract(path, self.name.text(), self.field.currentText(),
                                                      self.understand.isChecked(), self.busy(), self.deck))

    def options(self):
        """The split as the child takes it: (method, value, parts — 0 when not grouping)."""
        method = "length" if self.by_length.isChecked() else "delimiter"
        return method, self.value.text(), (self.parts.value() if self.group.isChecked() else 0)

    def job(self):
        """What Extract runs, as the window holds it now (taken at the click: an edit during the name's check never
        changes it)."""
        method, value, parts = self.options()
        return {"path": self.path.text().strip(), "method": method, "value": value, "parts": parts,
                "section": self.section.currentData(), "field": self.field.currentText(), "language": self.language}

    def check(self):
        """Extract: the options checked here, the name on a worker (a taken one refused, its free name proposed),
        then the child. The window counts as writing from the click (one Extract at a time)."""
        if not self.go.isEnabled():
            return
        job = self.job()
        if not importers_view.is_deck(job["path"]):
            fault = extract.check_options(job["method"], job["value"], bool(job["parts"]), job["parts"] or None)
            if fault:
                self.say(strings.EXTRACT_FAULTS[fault])
                return
        self.begin_write()
        self.refresh()
        self.say(strings.EXTRACT_CHECKING)
        bridge.run_in_worker(extract.check_name, self.name.text(), job["language"],
                             then=self.alive(lambda answer: self._named(answer, job)),
                             failed=self.alive(lambda info: self._checked(self._failed_line(info[0]))))

    def _checked(self, line):
        """The check ended without a child: said, and the window idle again."""
        self.say(line)
        self.end_write(line)
        self.refresh()

    def _named(self, answer, job):
        if answer.name is None:
            self._checked(strings.EXTRACT_BAD_NAME)
            return
        if answer.taken:
            self.name.setText(answer.proposal)
            self._checked(strings.EXTRACT_TAKEN.format(name=answer.name, proposal=answer.proposal))
            return
        self.start(answer.name, job)
        self.end_write()                                  # the check's; the child's write goes on

    def start(self, name, job=None):
        """The child, every value glued to its option (a --- delimiter or a -draft name is a value, never an
        option)."""
        job = job or self.job()
        argv = ["extract.py", "--language", job["language"], f"--file={job['path']}", f"--name={name}",
                "--section", job["section"]]
        if importers_view.is_deck(job["path"]):
            argv += [f"--field={job['field']}"]
        else:
            argv += ["--split", job["method"], f"--value={job['value']}", "--parts", str(job["parts"])]
        return self._run(strings.EXTRACT_NAME, argv, self._done, parse=extract.parse_result)

    def _done(self, code):
        key, values = importers_view.extract_outcome(code, self._result, self._why())
        section = strings.EXTRACT_SECTIONS.get(values.get("section"), "")
        if key == "done":
            line = strings.EXTRACT_DONE.format(parts=values["parts"], section=section, name=values["name"])
        elif key == "processed":
            line = strings.EXTRACT_DONE_PROCESSED.format(parts=values["parts"], name=values["name"])
        elif key == "processed-only":
            line = strings.EXTRACT_PROCESSED_ONLY.format(parts=values["parts"], name=values["name"], section=section)
        elif key == "already":                          # SRC K3: never a duplicate
            line = strings.EXTRACT_ALREADY.format(title=values["title"], parts=values["parts"], name=values["name"])
        elif key == "taken":
            line = strings.EXTRACT_TAKEN.format(name=values["name"], proposal=values["name"] + " 2")
        elif key == "name":
            line = strings.EXTRACT_BAD_NAME
        elif key == "empty":
            line = strings.EXTRACT_EMPTY
        else:
            line = self._failed_line(values["why"])
        self.say(line)
        self.end_write(line)


# --- the doors (row 2: the importers and Extract) ------------------------------------------------------------------ #
def open_deck(shell):
    return windows.show(shell, "apkg_known", DeckWindow)


def open_migaku(shell):
    return windows.show(shell, "migaku", MigakuWindow)


def open_jiten(shell):
    return windows.show(shell, "jiten", JitenWindow)


def open_extract(shell):
    return windows.show(shell, "extract", ExtractWindow)

