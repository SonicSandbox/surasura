"""The ported windows' base (W3.4 row 1; the RUNBOOK's *rules for every row* and *Where the windows open from*).

`SecondaryWindow`: a top-level window parented to the main window (`Qt.Window`), titled "<name> — Surasura", sized
from its content, with one status line at its foot. Esc and the mouse's Back button close it through the shell's
`EscapeRouter` (never bound here); its in-window overlays (the confirmation) register with the main window's router.
It opened for one language and **follows the main window's language when idle** (🧭 IK-12): a switch while a write it
started is in flight waits for that write (never cut) — its result goes to the bottom bar too — then the window reads
again for the new language (`language_changed`, a subclass's re-read).

`OPENERS`: the one registry of the ported windows' doors — `Opener(name, label, tip, available(settings, language),
open(shell), module)`. **Until W3.3 (the Settings page) and W3.2 (the + Add menu, Finished) give each door its row,
the Settings tab's waiting page lists them** (`launchers`, the shell's one hook) as a row of buttons, each shown only
while `available` says so and its module (when it names one) imports — the Tk dashboard's visibility rules. W3.3 and
W3.2 attach the same openers to their rows and **retire the list** (IK-16: it never ships by default).
`show(shell, name, make)`: one window of a kind per main window, kept and raised if open.
"""
import importlib.util
from collections import namedtuple

from PyQt6.QtCore import QEvent, QObject, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app import theme
from app.qt import applog, strings, style

Opener = namedtuple("Opener", "name label tip available open module", defaults=(None,))


def language_of(shell):
    """The main window's language now (the settings service's copy: nothing read from disk)."""
    try:
        return shell.services.settings.get().get("target_language") or "ja"
    except Exception:
        return getattr(shell, "language", None) or "ja"


def open_url(url):
    """A link or a folder in the user's own program (IK-17: `QDesktopServices`, never `os.startfile`)."""
    return QDesktopServices.openUrl(QUrl(url) if "://" in url else QUrl.fromLocalFile(url))


class SecondaryWindow(QWidget):
    """A ported window. A subclass builds its controls into `self.body`, says what it is doing with `say`, wraps each
    write in `begin_write` / `end_write`, and re-reads in `language_changed`."""
    closed = pyqtSignal()

    def __init__(self, shell, name, language=None):
        super().__init__(shell, Qt.WindowType.Window)
        self.shell = shell
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(strings.SECONDARY_TITLE.format(name=name))
        self.setObjectName("secondary")
        self.language = language or language_of(shell)
        self.gone = False
        self._writes = 0
        self._language_waiting = None
        f = theme.text_factor(style.current()[1])
        root = QVBoxLayout(self)
        pad = round(16 * f)
        root.setContentsMargins(pad, pad, pad, pad)
        root.setSpacing(round(10 * f))
        self.body = QVBoxLayout()
        self.body.setSpacing(round(10 * f))
        root.addLayout(self.body, 1)
        self.status = QLabel(self)
        self.status.setObjectName("windowstatus")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setAccessibleName(strings.WINDOW_STATUS_NAME)
        self.status.setVisible(False)
        root.addWidget(self.status)
        self.status_paints = 0
        self.setMinimumWidth(round(theme.size("pop", style.current()[1])))
        bridge = getattr(shell, "bridge", None)
        if bridge is not None:
            bridge.settings_written.connect(self._settings_written)

    # --- what it says ------------------------------------------------------------------------------------------- #
    def say(self, text):
        """The status line: repainted only when its words changed (S19); hidden when empty."""
        text = text or ""
        if self.status.text() == text:
            return
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.status_paints += 1

    def alive(self, fn):
        """`fn`, dropped once the window closed: a worker's answer arriving after it is never painted."""
        def call(*args):
            if not self.gone:
                return fn(*args)
            return None
        return call

    def register_overlay(self, overlay):
        """An in-window overlay (the confirmation): Esc and Back close it before the window (the main window's router)."""
        register = getattr(self.shell, "register_overlay", None)
        if register is not None:
            register(overlay)

    # --- writes and the language -------------------------------------------------------------------------------- #
    def busy(self):
        return self._writes > 0

    def begin_write(self):
        self._writes += 1

    def end_write(self, result=None):
        """A write ended (`result`: its line). A language switch that waited for it happens now, and the result goes
        to the bottom bar as well (the window is about to show the other language)."""
        self._writes = max(0, self._writes - 1)
        if self._writes or self._language_waiting is None or self.gone:
            return
        language, self._language_waiting = self._language_waiting, None
        if result:
            bar = getattr(self.shell, "bar_line", None)
            if bar is not None:
                bar.set_full(result)
        if language != self.language:
            self._switch(language)

    def _settings_written(self, keys):
        if "target_language" not in keys or self.gone:
            return
        language = language_of(self.shell)
        if language == self.language and self._language_waiting is None:
            return
        if self.busy():
            self._language_waiting = language             # after the write in flight (never cut)
            return
        self._switch(language)

    def _switch(self, language):
        self.language = language
        self.language_changed(language)

    def language_changed(self, language):
        """A subclass re-reads for `language` (the window is idle)."""

    def closeEvent(self, event):
        self.gone = True
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit()


# --- one window of a kind per main window ---------------------------------------------------------------------- #
def show(shell, name, make):
    """The window `name` of `shell`: raised when open, else made by `make(shell)` and shown. -> the window."""
    opened = shell.__dict__.setdefault("_secondary_windows", {})
    win = opened.get(name)
    if win is not None and not win.gone:
        win.show()
        win.raise_()
        win.activateWindow()
        return win
    win = make(shell)
    opened[name] = win
    win.closed.connect(lambda w=win: opened.get(name) is w and opened.pop(name, None))
    win.adjustSize()
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def opened(shell, name):
    """The open window `name` of `shell`, or None."""
    win = shell.__dict__.get("_secondary_windows", {}).get(name)
    return win if win is not None and not win.gone else None


# --- the registry ------------------------------------------------------------------------------------------------ #
def always(_settings, _language):
    return True


# Each row adds its doors here (W3.4 rows 1–6), in the order the list shows them.
OPENERS = []
# row 2: the known-word importers and Extract (app/qt/importers.py, imported when a door opens)
def _importers(opener_name):
    def open_it(shell):
        from app.qt import importers
        return getattr(importers, opener_name)(shell)
    return open_it


OPENERS += [
    Opener("apkg_known", strings.IMPORTERS_LAUNCH_APKG, strings.IMPORTERS_LAUNCH_APKG_TIP, always,
           _importers("open_deck")),
    Opener("migaku", strings.IMPORTERS_LAUNCH_MIGAKU, strings.IMPORTERS_LAUNCH_MIGAKU_TIP, always,
           _importers("open_migaku")),
    Opener("jiten", strings.IMPORTERS_LAUNCH_JITEN, strings.IMPORTERS_LAUNCH_JITEN_TIP,
           lambda _settings, language: language == "ja", _importers("open_jiten")),
    Opener("extract", strings.IMPORTERS_LAUNCH_EXTRACT, strings.IMPORTERS_LAUNCH_EXTRACT_TIP, always,
           _importers("open_extract")),
]


def module_present(name):
    """Whether `modules/<name>` can be imported (found, not run: nothing of it is loaded here)."""
    try:
        return importlib.util.find_spec(f"modules.{name}") is not None
    except (ImportError, ValueError):
        return False


def available(opener, settings, language):
    """Whether `opener`'s door shows: its module imports (when it names one) and its own rule says so."""
    if opener.module is not None and not module_present(opener.module):
        return False
    try:
        return bool(opener.available(settings, language))
    except Exception as e:
        applog.log("windows", f"{opener.name}'s door: {e}")
        return False


# --- the Settings tab's list, until W3.3 / W3.2 (IK-16) --------------------------------------------------------- #
class _Shown(QObject):
    def __init__(self, page, refresh):
        super().__init__(page)
        self.refresh = refresh
        page.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            self.refresh()
        return False


def launchers(shell, page):
    """The ported windows' doors on `page` (the Settings tab's waiting page): one button each, shown while its door is
    available — asked again each time the page shows. -> the row (its `buttons`: name -> button)."""
    row = QWidget(page)
    row.setObjectName("launchers")
    row.setAccessibleName(strings.LAUNCHERS_NAME)
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.addStretch(1)
    row.buttons = {}
    for op in OPENERS:
        b = QPushButton(op.label, row)
        b.setToolTip(op.tip)
        b.setAccessibleName(op.label)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(lambda _c=False, o=op: launch(shell, o))
        line.addWidget(b)
        row.buttons[op.name] = b
    line.addStretch(1)

    def refresh():
        settings = shell.services.settings.get()
        language = settings.get("target_language") or "ja"
        for op in OPENERS:
            b = row.buttons.get(op.name)
            show_it = available(op, settings, language)
            if b is not None and b.isHidden() == show_it:
                b.setVisible(show_it)
    row.refresh = refresh
    refresh()
    _Shown(page, refresh)
    box = page.layout()
    box.insertWidget(max(0, box.count() - 1), row)        # under the page's line, above its closing stretch
    return row


def launch(shell, opener):
    try:
        return opener.open(shell)
    except Exception as e:                                # a door that can't open says so in the bar, never a box
        applog.log("windows", f"{opener.name} didn't open: {e}")
        bar = getattr(shell, "bar_line", None)
        if bar is not None:
            bar.set_full(strings.OPEN_FAILED.format(name=opener.label, why=e))
        return None
