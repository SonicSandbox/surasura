"""The start gate (W3.5 part 3; S3.1 D3, D11, D12, D13): before the window's services open the library.

`gate(app) -> bool` is called by `shell.main()` after the single-instance claim and before `Services()`: the store must
not open before an import ends, nor on a library that isn't there. It asks `first_run.state()` (file checks only, ~1 ms
on an everyday start) and returns True at once — no window — when nothing needs doing. Otherwise it opens a small
window of its own and runs the application's loop until it is safe to go on (True) or the user quits (False):

  * *Bringing your library over from Surasura 2…* — the stage and a hairline progress, *Cancel* (between files: the
    import's note says unfinished and the next screen offers *Try again*).
  * The refusals — the library folder not there (never made again, D3), an unfinished import (never used half, D11),
    the write check refused (Controlled Folder Access, D12: its steps), an import that stopped — each with its one
    sentence, *Try again* and *Quit*.
  * The folder ask (2.x used here, no note naming its folder): *Choose the old folder…*, *Start fresh*, *Quit*.

An everyday start that has quiet work (a new library's write check, a GraduatedList to merge, the library recorded for
the first time) runs it on a worker with no window; the window shows only if that work is refused. All work runs on
`bridge.run_in_worker`; the gate's thread only paints. Esc does nothing (the gate is the start, not an overlay); ✕ is
*Quit*. Its strings are here (`strings.py` is another agent's file); the look is the application's (`style.apply`).
"""
import os
import threading
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, \
    QWidget

from app import import_2x, theme
from app.qt import bridge, hud, style, tooltip
from app.services import first_run

# --- start_gate: the strings (RS-7: short, what it does for the user; a tip holds anything longer) ------------------ #
TITLE = "Surasura"
BRINGING = "Bringing your library over from Surasura 2…"
GETTING_READY = "Getting your library ready…"
STARTING = "Starting…"
STOPPING = "Stopping after this file…"
STAGES = {"files": "Copying your shows and books", "settings": "Bringing your settings",
          "store": "Keeping your order", "roaming": "Bringing your extras", "graduated": "Adding your finished words"}
STAGE_COUNT = "{stage} · {done:,} of {total:,}"
MISSING_HEADING = "Your library isn't there"
MISSING_LINE = "Surasura can't find {folder}. Connect its drive or go online, then try again."
UNFINISHED_HEADING = "Bringing your library over didn't finish"
UNFINISHED_LINE = "Try again to pick up where it stopped. Your old Surasura is unchanged."
BLOCKED_HEADING = "Surasura can't save to your library folder"
STOPPED_HEADING = "Bringing your library over stopped"
CHECK_HEADING = "Surasura couldn't look at your library"
ASK_HEADING = "Bring your library over from Surasura 2?"
ASK_LINE = "Choose the folder your old Surasura is in, or start fresh."
ASK_PICK = "Your old Surasura folder"
LOOKING = "Looking…"
CANCEL = "Cancel"
CANCEL_TIP = "Stop bringing your library over.\n• Your old Surasura stays as it is; finish next time."
TRY_AGAIN = "Try again"
TRY_AGAIN_TIP = "Look again and carry on."
QUIT = "Quit"
QUIT_TIP = "Close Surasura for now.\n• Nothing is lost."
CHOOSE = "Choose the old folder…"
CHOOSE_TIP = "Bring your shows, books and known words from Surasura 2.\n• Pick the folder Surasura.exe is in."
FRESH = "Start fresh"
FRESH_TIP = "Begin with an empty library.\n• You won't be asked again."

PROGRESS_EVERY = 0.05          # s: the import's progress reaches the window at most this often (a stage change always)


def _throttled(call):
    """`run_import`'s progress (a worker's call) handed on as `(stage, done, total)`, at most every PROGRESS_EVERY s —
    always on a new stage and at each stage's end — so a library of many files never floods the window's queue."""
    last = {"t": 0.0, "stage": None}

    def tick(stage, done, total):
        now = time.monotonic()
        if stage != last["stage"] or done >= total or now - last["t"] >= PROGRESS_EVERY:
            last.update(t=now, stage=stage)
            call((stage, done, total))
    return tick


class Gate(QWidget):
    """The gate's window and its steps. `result` is None until it ends (`ended`), then True (go on) / False (quit)."""

    def __init__(self, app, st, error=None):
        super().__init__(None, Qt.WindowType.Window)
        self.app = app
        self.st = st
        self.error = error
        self.result = None
        self.ended = False
        self.looping = False                      # inside `gate`'s run of the application's loop
        self.working = False
        self.quit_after = False
        self._cancel = threading.Event()
        self.screen = None
        style.apply(app)                          # the shell applies the user's look again when its window opens
        self.setObjectName("startgate")
        self.setWindowTitle(TITLE)
        f = theme.text_factor(style.current()[1])
        root = QVBoxLayout(self)
        pad = round(24 * f)
        root.setContentsMargins(pad, pad, pad, pad)
        root.setSpacing(round(12 * f))
        self.heading = self._label("windowheading", root)
        self.line = self._label("windowline", root)
        self.line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stage = self._label("windowstatus", root)
        self.bar = QProgressBar(self)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(2)                # the hairline
        self.bar.setRange(0, 0)
        root.addWidget(self.bar)
        root.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(round(10 * f))
        self.choose_button = self._button(CHOOSE, CHOOSE_TIP, self.choose, row, "primary")
        self.fresh_button = self._button(FRESH, FRESH_TIP, self.fresh, row)
        self.try_button = self._button(TRY_AGAIN, TRY_AGAIN_TIP, self.try_again, row, "primary")
        row.addStretch(1)
        self.cancel_button = self._button(CANCEL, CANCEL_TIP, self.cancel, row)
        self.quit_button = self._button(QUIT, QUIT_TIP, self.quit, row)
        root.addLayout(row)
        self.setMinimumWidth(round(theme.size("dialog", style.current()[1])))
        self.tips = tooltip.Tooltips(parent=self).install(app)
        self.relay = bridge.Relay(self)
        self.relay.said.connect(self._progress)

    def _label(self, name, layout):
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setVisible(False)
        layout.addWidget(label)
        return label

    def _button(self, label, tip, slot, row, kind=None):
        b = QPushButton(label, self)
        b.setToolTip(tip)
        b.setAccessibleName(label)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setAutoDefault(False)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _c=False: slot())
        b.setVisible(False)
        row.addWidget(b)
        return b

    # --- what it shows ----------------------------------------------------------------------------------------- #
    def _set(self, label, text):
        text = text or ""
        if label.text() != text:
            label.setText(text)
        label.setVisible(bool(text))

    def show_screen(self, name, message=None):
        """One of: working, missing, unfinished, blocked, stopped, check, ask — its words and its buttons."""
        self.screen = name
        library = (self.st or {}).get("library") or ""
        heading, line = {
            "working": (BRINGING, None),
            "preparing": (GETTING_READY, None),
            "missing": (MISSING_HEADING, MISSING_LINE.format(folder=library)),
            "unfinished": (UNFINISHED_HEADING, UNFINISHED_LINE),
            "blocked": (BLOCKED_HEADING, message),
            "stopped": (STOPPED_HEADING, message),
            "check": (CHECK_HEADING, message),
            "ask": (ASK_HEADING, message or ASK_LINE),
        }[name]
        self._set(self.heading, heading)
        self._set(self.line, line)
        busy = name in ("working", "preparing")
        self._set(self.stage, STARTING if busy else None)
        self.bar.setVisible(busy)
        if busy:
            self.bar.setRange(0, 0)
        shown = {"working": (self.cancel_button,), "preparing": (),
                 "ask": (self.choose_button, self.fresh_button, self.quit_button)}.get(
            name, (self.try_button, self.quit_button))
        for b in (self.choose_button, self.fresh_button, self.try_button, self.cancel_button, self.quit_button):
            b.setVisible(b in shown)
            b.setEnabled(True)
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()

    def _progress(self, value):
        stage, done, total = value
        if self.ended or self.screen not in ("working", "preparing") or self._cancel.is_set():
            return
        name = STAGES.get(stage, stage)
        self._set(self.stage, STAGE_COUNT.format(stage=name, done=done, total=total) if total > 1 else name)
        if self.bar.maximum() != max(1, total):
            self.bar.setRange(0, max(1, total))
        self.bar.setValue(min(done, total))

    # --- the steps --------------------------------------------------------------------------------------------- #
    def start(self):
        """Decide the first screen from the state (or run the quiet work of an everyday start)."""
        if self.st is None:
            self.show_screen("check", str(self.error or ""))
            return
        kind = self.st["state"]
        if kind == first_run.LIBRARY_MISSING:
            self.show_screen("missing")
        elif kind == first_run.IMPORT_UNFINISHED:
            self.show_screen("unfinished")
        elif kind == first_run.ASK_FOLDER:
            self.show_screen("ask")
        elif kind == first_run.IMPORT:
            self._run()
        else:
            self._run(quiet=True)

    def _run(self, source=None, fresh=False, quiet=False):
        self.working = True
        self._cancel = threading.Event()
        if not quiet or self.isVisible():         # (quiet work after Try again: the shown window says it works)
            importing = self.st["state"] in (first_run.IMPORT, first_run.IMPORT_UNFINISHED) or source
            self.show_screen("working" if importing and not fresh else "preparing")
        bridge.run_in_worker(first_run.run, self.st, _throttled(self.relay.call), self._cancel.is_set, source, fresh,
                             then=self._ran, failed=self._crashed)

    def _ran(self, result):
        self.working = False
        if self.ended:
            return
        if self.quit_after:
            self.finish(False)
            return
        status = result["status"]
        if status == "done":
            self.finish(True)
        elif status == "cancelled":
            self.st = dict(self.st, state=first_run.IMPORT_UNFINISHED)
            self.show_screen("unfinished")
        elif status == "blocked":
            self.show_screen("blocked", result["message"])
        elif result.get("reason") == "library_missing":
            self.show_screen("missing")
        else:
            self.show_screen("stopped", result["message"])

    def _crashed(self, info):
        self.working = False
        if self.ended:
            return
        if self.quit_after:
            self.finish(False)
            return
        self.show_screen("stopped", str(info[0]))

    def try_again(self):
        """Look again (on a worker): an unfinished import resumes; anything else starts over from its new state."""
        if self.working:
            return
        self._looking()
        bridge.run_in_worker(first_run.state, then=self._looked_again, failed=self._look_failed)

    def _looking(self):
        for b in (self.choose_button, self.fresh_button, self.try_button):
            b.setEnabled(False)
        self._set(self.stage, LOOKING)

    def _looked_again(self, st):
        if self.ended:
            return
        self.st, self.error = st, None
        if st["state"] == first_run.IMPORT_UNFINISHED:
            self._run()
        else:
            self.start()

    def _look_failed(self, info):
        if not self.ended:
            self.st, self.error = None, info[0]
            self.start()

    def choose(self):
        """The old folder, chosen (the system's folder picker), checked on a worker, then brought over."""
        if self.working:
            return
        folder = QFileDialog.getExistingDirectory(self, ASK_PICK)
        if not folder:
            return
        folder = os.path.normpath(folder)
        self._looking()
        bridge.run_in_worker(import_2x.check_source, folder, then=lambda c: self._checked(folder, c),
                             failed=lambda info: self._checked(folder, {"ok": False, "message": str(info[0])}))

    def _checked(self, folder, check):
        if self.ended:
            return
        if check["ok"]:
            self._run(source=folder)
        else:
            self.show_screen("ask", check["message"])

    def fresh(self):
        if not self.working:
            self._run(fresh=True)

    def cancel(self):
        """Stop between two files: the note says unfinished, the next screen offers Try again."""
        if self.working and not self._cancel.is_set():
            self._cancel.set()
            self.cancel_button.setEnabled(False)
            self._set(self.stage, STOPPING)

    def quit(self):
        """Quit now — or, while the import copies, once it has stopped between two files."""
        if self.ended:
            return
        if self.working:
            self.quit_after = True
            self.cancel()
            self.quit_button.setEnabled(False)
            return
        self.finish(False)

    def finish(self, ok):
        if self.ended:
            return
        self.ended, self.result = True, bool(ok)
        self.tips.uninstall(self.app)
        self.hide()
        self.deleteLater()
        if self.looping:
            self.app.exit(0)

    # --- keys and ✕ -------------------------------------------------------------------------------------------- #
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:      # the start's window: Esc closes nothing
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.ended:
            event.accept()
            return
        event.ignore()                            # ✕ is Quit (once a running import has stopped)
        self.quit()


def gate(app):
    """Before `Services()`: True when the window may open the library, False to quit (see the module docstring)."""
    try:
        st, error = first_run.state(), None
    except Exception as e:                        # an unexpected read failure: the gate says so, never guesses
        st, error = None, e
    hud.mark("gate")
    if st is not None and not first_run.needs_run(st):
        return True
    g = Gate(app, st, error)
    g.start()
    if not g.ended:
        keep = app.quitOnLastWindowClosed()
        app.setQuitOnLastWindowClosed(False)      # the gate's window hiding must never quit the window's loop
        g.looping = True
        try:
            app.exec()
        finally:
            g.looping = False
            app.setQuitOnLastWindowClosed(keep)
    return bool(g.result)
