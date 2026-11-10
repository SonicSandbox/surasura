# SPDX-License-Identifier: GPL-3.0-or-later
"""The YouTube preview against the library, in Qt (W3.4 row 4; the RUNBOOK's row 4; the intent keeper's IK-2, IK-15).

A secondary window (`app/qt/windows.py`): one link (Enter starts it), *Add to the front of Current* (off, for this
preview only, never saved), *Preview*, and the status line. The pipeline is `preview.run_preview` (Qt-free, on a thread
of its own: a playlist can take minutes): the link looked up, the playlist question and the in-library guard there;
**the fetch a youtube job and the scoring a child** (`preview.Runs`: the tokenizer and the analyzer's globals never in
this process — AD4-2, IK-29; each run shown in the bottom bar and ended by a cancel there, the window's close or the
app's quit — IK-31); the add after. This file paints its outcome:

- the playlist question is asked here, in the window (`confirm.ask`: *Full playlist* / *Just this video*; Esc, Back,
  ✕ and a click outside are *Just this video*, as the Tk dialog's Esc was), while the run waits for the answer — and
  a window closed meanwhile ends the run, never leaving it waiting;
- **the add only in the store's mode** (IK-2: on 3.0 no JSON fallback; anything else says "busy, try again" and copies
  nothing), and **a refused add never hides the preview**: it opens, and the line says why nothing was added;
- no list to compare with, or another language's list → the window asks to Generate (through the shell's Generate) and
  runs the preview by itself when Generate is done;
- **each run has its own workspace** (AD4-3): a run that opened nothing removes its own at once, one that ends after
  the window closed removes its own then, and the close (Esc and Back too: the Tk window's Esc skipped it) removes the
  ended runs' workspaces kept for the previews it opened — nothing is imported or started on a thread of its own at
  close (IK-28).
"""
import shutil
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton

from app.qt import bridge, confirm, windows
from app.qt import press as qpress
from modules.youtube_downloader import qt_strings as S

NAME = "youtube-preview"
_RUNNING_STATES = ("queued", "running")                     # the Generate controller's, before it lands


class PreviewWindow(windows.SecondaryWindow):
    def __init__(self, shell, language=None):
        super().__init__(shell, S.PREVIEW_TITLE, language)
        self.setObjectName("previewwindow")
        self.running = False
        self._thread = None
        self._runs = None                                   # the run's jobs (preview.Runs), cancelled by a close
        self._ws_lock = threading.Lock()
        self._workspaces = []                               # the ended runs' workspaces kept for their open previews
        self._ws_closed = False
        self._after_generate = None                         # (link, add) waiting for Generate; True once it ran
        self._steps = bridge.Relay(self)
        self._steps.said.connect(self._step)
        self._questions = bridge.Relay(self)
        self._questions.said.connect(self._ask_playlist)
        self._ends = bridge.Relay(self)
        self._ends.said.connect(self._ended)
        b = getattr(shell, "bridge", None)
        if b is not None:
            b.generate_changed.connect(self._generate_changed)

        heading = QLabel(S.PREVIEW_HEADING, self)
        heading.setObjectName("windowheading")
        self.body.addWidget(heading)
        self.link = QLineEdit(self)
        self.link.setPlaceholderText(S.PREVIEW_LINK_HINT)
        self.link.setToolTip(S.PREVIEW_LINK_TIP)
        self.link.setAccessibleName(S.PREVIEW_LINK_NAME)
        self.link.returnPressed.connect(self._submit)
        self.body.addWidget(self.link)
        self.add_front = QCheckBox(S.ADD_FRONT, self)
        self.add_front.setToolTip(S.ADD_FRONT_TIP)
        self.add_front.setAccessibleName(S.ADD_FRONT)
        self.add_front.setProperty("kind", "toggle")
        self.add_front.toggled.connect(lambda _on: self._sync())     # a per-preview choice, read when one starts
        self.body.addWidget(self.add_front)
        row = QHBoxLayout()
        row.addStretch(1)
        self.go = qpress.room(QPushButton(S.PREVIEW, self))
        self.go.setToolTip(S.PREVIEW_TIP)
        self.go.setAccessibleName(S.PREVIEW)
        self.go.setProperty("kind", "primary")
        self.go.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.go.clicked.connect(lambda _c=False: self._submit())
        row.addWidget(self.go)
        self.body.addLayout(row)
        self.link.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync(self):
        """*Preview* greyed while a preview runs that it didn't start; its own keeps its look — its arc turns from the
        press until the run ends (round 8 row 45), and a press meanwhile does nothing."""
        on = not self.running or qpress.mark(self.go) is not None
        if self.go.isEnabled() != on:
            self.go.setEnabled(on)

    # --- a preview ----------------------------------------------------------------------------------------------- #
    def _submit(self, link=None, add=None):
        if self.running or self.gone:
            return
        link = (self.link.text() if link is None else link).strip()
        if not link:
            return
        add = self.add_front.isChecked() if add is None else add
        language = self.language
        settings = self.shell.services.settings
        registry = self.shell.services.registry
        app_mode = bool(settings.get().get("open_app_mode", False))
        self.running = True
        self._press = qpress.begin(self.go, "preview:run", win=self)     # painted before the run's thread starts
        self._sync()
        if add:
            self.begin_write()                              # a language switch waits for the add (never cut)

        def run():
            from modules.youtube_downloader import preview
            runs = preview.Runs(registry, language, link, S.JOB_PREVIEW, before=lambda: settings.flush(10.0))
            self._runs = runs
            if self.gone:                                   # closed while this run was being set up
                runs.cancel()

            def stopped():
                return self.gone or runs.cancelled
            outcome, opened = None, False
            try:
                outcome = preview.run_preview(link, language, add, self._wait_for_answer, self._steps.call,
                                              should_stop=stopped, fetch=runs.fetch, score=runs.score)
                if outcome.html and not stopped():
                    preview.open_report(outcome.html, app_mode)
                    opened = True
            except Exception as e:                           # said in the window, never raised into the thread
                outcome = preview.Outcome(error=preview.UNEXPECTED.format(why=e))
            self._settle(outcome.workspace, opened)
            self._ends.call((link, add, outcome, opened))
        self._thread = threading.Thread(target=run, name="youtube-preview", daemon=True)
        self._thread.start()

    def _settle(self, workspace, opened):
        """(The run's thread, as it ends.) Its workspace kept while the window shows the preview it opened, else
        removed now — by the run itself, whether or not its window is still open (AD4-3)."""
        if not workspace:
            return
        with self._ws_lock:
            keep = opened and not self._ws_closed
            if keep:
                self._workspaces.append(workspace)
        if not keep:
            shutil.rmtree(workspace, ignore_errors=True)

    def _step(self, line):
        self.say(line)

    def _ended(self, payload):
        link, add, outcome, opened = payload
        self.running = False
        p, self._press = getattr(self, "_press", None), None
        if p is not None:
            qpress.end(p, self, failed=bool(outcome.error))
        self._sync()
        if outcome.generate:
            self._offer_generate(link, add, outcome.error)
            line = outcome.error
        elif outcome.error:
            line = outcome.error
        elif opened and outcome.note:
            line = S.PREVIEW_NOT_ADDED.format(why=outcome.note)
        elif opened and outcome.added:
            line = S.PREVIEW_ADDED.format(what=S.files(len(outcome.added)))
        elif opened:
            line = S.PREVIEW_OPENED
        else:
            line = ""
        self.say(line)
        if add:
            self.end_write(line)

    # --- the playlist question ----------------------------------------------------------------------------------- #
    def _wait_for_answer(self, count):
        """(The run's thread.) Ask in the window and wait: True / False, or None once the window closed."""
        box = {"answer": None, "done": threading.Event()}
        self._questions.call((count, box))
        while not box["done"].wait(0.05):
            if self.gone:
                return None
        return box["answer"]

    def _ask_playlist(self, payload):
        count, box = payload

        def answered(yes):
            box["answer"] = bool(yes)
            box["done"].set()
        confirm.ask(self, S.PLAYLIST_TITLE, S.PLAYLIST_BODY.format(count=count), S.PLAYLIST_FULL, S.PLAYLIST_FULL_TIP,
                    no=S.PLAYLIST_ONE, no_tip=S.PLAYLIST_ONE_TIP, on_answer=answered)

    # --- no list for this language yet: Generate, then the preview by itself ------------------------------------ #
    def _offer_generate(self, link, add, why):
        confirm.ask(self, S.GENERATE_TITLE, why, S.GENERATE_YES, S.GENERATE_YES_TIP, no_tip=S.GENERATE_NO_TIP,
                    on_answer=lambda yes: self._generate(yes, link, add))

    def _generate(self, yes, link, add):
        if not yes or self.gone:
            return
        self._after_generate = [link, add, False]           # [link, add, seen it run]
        self.say(S.GENERATING)
        bridge.run_in_worker(self.shell.services.generate, failed=self.alive(lambda _i: self._generate_failed()))

    def _generate_failed(self):
        self._after_generate = None
        self.say(S.GENERATE_FAILED)

    def _generate_changed(self, state):
        waiting = self._after_generate
        if waiting is None or self.gone:
            return
        now = getattr(state, "state", None)
        if now in _RUNNING_STATES:
            waiting[2] = True
        elif waiting[2] and now == "current":
            self._after_generate = None
            self._submit(waiting[0], waiting[1])
        elif waiting[2] and now in ("failed", "idle", "stale"):
            self._generate_failed()

    # --- closing ------------------------------------------------------------------------------------------------- #
    def closeEvent(self, event):
        """The run in flight is cancelled (its fetch's yt-dlp child, or its scoring child, ended; it removes its own
        workspace as it ends); the ended runs' workspaces go on a pool worker. Nothing is imported here, and no thread
        of its own is started (IK-28)."""
        super().closeEvent(event)
        if not event.isAccepted():
            return
        runs = self._runs
        if runs is not None:
            runs.cancel()
        with self._ws_lock:
            self._ws_closed = True
            kept, self._workspaces = self._workspaces, []
        if kept:
            bridge.run_in_worker(_remove, kept)


def _remove(paths):
    """(A worker.) The workspaces removed."""
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def open(shell):
    """The preview window of `shell`: raised when open, else made and shown."""
    return windows.show(shell, NAME, PreviewWindow)
