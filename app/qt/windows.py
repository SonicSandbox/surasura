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
import json
import os
import re
import weakref
from collections import namedtuple

from PyQt6.QtCore import QEvent, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app import path_utils, theme
from app.qt import applog, bridge, strings, style

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
        self._closed = False                              # closed (a close that went through)
        alive = self._alive = [True]                      # False once Qt destroyed it (its main window gone too)
        self.destroyed.connect(lambda *_a: alive.__setitem__(0, False))
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
        heard = getattr(shell, "bridge", None)
        if heard is not None:
            heard.settings_written.connect(self._settings_written)

    @property
    def gone(self):
        """Closed, or destroyed with its main window: nothing paints it any more."""
        return self._closed or not self._alive[0]

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
            say_in_bar(self.shell, result)
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
        """A subclass that refuses a close calls `event.ignore()` before this (QWidget's own would accept it again)."""
        if event.isAccepted():
            self._closed = True
            self.closed.emit()


def say_in_bar(shell, text):
    """`text` in the main window's bottom bar — nothing when that window is gone (a worker's late answer at quit)."""
    try:
        shell.bar_line.set_full(text)
    except (AttributeError, RuntimeError):
        pass


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


def _open_frequency_lists(shell):
    from app.qt import frequency_lists_window
    return show(shell, "frequency-lists", frequency_lists_window.FrequencyListsWindow)


def _open_sentence_dictionary(shell):
    from app.qt import sentence_dictionary_window
    return show(shell, "sentence-dictionary", sentence_dictionary_window.SentenceDictionaryWindow)


# Each row adds its doors here (W3.4 rows 1–6), in the order the list shows them.
OPENERS = [
    Opener("frequency-lists", strings.FREQ_NAME, strings.FREQ_TIP, always, _open_frequency_lists),
    Opener("sentence-dictionary", strings.DICT_NAME, strings.DICT_TIP, always, _open_sentence_dictionary),
]
from app.qt import word_lists_strings as _wls  # noqa: E402  (W3.3 P10, n16: Words to leave out)
OPENERS += [Opener("word-lists", _wls.WORD_LISTS_NAME, _wls.WORD_LISTS_TIP, always,
                   lambda shell: importlib.import_module("app.qt.word_lists_window").open_window(shell))]
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

# row 4: Koe and YouTube — each module's own window, imported only when its door is pressed; shown as the Tk dashboard
# showed them: the downloader with `enable_youtube_transcripts`, the preview with `enable_youtube_preview`, Speech
# whenever revealed (the reveal line in settings.json, `modules.koe`, true or false).


def _koe_door(settings, _language):
    from modules.koe import koe_view
    return koe_view.door_open(settings)


def _open_koe(shell):
    from modules.koe import open_koe_settings
    return open_koe_settings(shell)


def _open_downloader(shell):
    from modules.youtube_downloader import open_downloader
    return open_downloader(shell, on_complete=youtube_arrivals(shell))     # W3.2 B: into New arrivals


# --- W3.2 B: the downloader's files into New arrivals (Sonic's W3.2-2: they wait there unless a rule places them) -- #
_YT_TOKEN = re.compile(r"\[(bilibili-)?([A-Za-z0-9_-]+)\][\s_()\-.\d]*$")   # the id the downloader ends a name with


def youtube_record(path, language):
    """(The writer's copier thread.) The pairing record of one transcript the downloader wrote, from what it keeps per
    file — read only: its cue sidecar (`<stem>.surasura.json`: the video's id, address and title) and the transcript's
    own header (line 2: `<channel> | <published> | <length>`), else the id its name ends with. Producer `youtube` (the
    module's, bilibili.tv's too); `channel_id` = the channel's name as the header gives it (the downloader keeps no
    channel id), which `placing_rules`' `youtube:<channel>` names; no channel (bilibili.tv names none) → the producer's
    rule alone. The show is the channel, so one channel's videos are one title."""
    stem = os.path.splitext(path)[0]
    side = {}
    try:
        with open(stem + path_utils.SIDECAR_SUFFIX, encoding="utf-8") as f:
            side = json.load(f)
    except (OSError, ValueError):
        pass
    side = side if isinstance(side, dict) else {}
    header = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            header = [f.readline().strip() for _ in range(2)]
    except OSError:
        pass
    m = _YT_TOKEN.search(os.path.basename(stem))
    site = "bilibili" if m and m.group(1) else "youtube"
    video = str(side.get("video_id") or (m.group(2) if m else "")).strip()
    # the date and the length are always the last two fields: a channel holding " | " (`TBS | 公式`) stays whole (L1 N1)
    channel = header[1].rsplit(" | ", 2)[0].strip() if len(header) > 1 and " | " in header[1] else ""
    record = {"schema": 1, "producer": "youtube", "language": language, "media_type": "youtube",
              "content_key": f"{site}:{video}" if video else f"{site}:file:{os.path.basename(path)}"}
    if video:
        record["video_id"] = video
    if side.get("url"):
        record["url"] = side["url"]
    title = side.get("title") or (header[0] if header else "")
    if title:
        record["title"] = title
    if channel and channel != "Unknown" and site == "youtube":
        record["channel_id"] = channel
        record["show"] = {"title": channel}
    return record


def arrived_line(waiting, placed, missed=0):
    """The downloader's done line once its files landed: how many wait in New arrivals, how many a rule placed, how
    many weren't added (L1 S3)."""
    line = ""
    if waiting and placed:
        line = strings.YT_ARRIVED_BOTH.format(waiting=waiting, placed=placed)
    elif waiting:
        line = strings.YT_ARRIVED_WAITING.format(what=strings.yt_transcripts(waiting))
    elif placed:
        line = strings.YT_ARRIVED_PLACED.format(what=strings.yt_transcripts(placed))
    if missed:
        not_added = strings.YT_NOT_ADDED.format(what=strings.yt_transcripts(missed))
        line = f"{line} · {not_added}" if line else not_added
    return line


def youtube_arrivals(shell):
    """The downloader's `on_complete(paths)` (the window's thread): its created files (and the files in the folders it
    made) registered through the window's writer — never the store on this thread — each waiting in New arrivals
    unless the user's `placing_rules` (`youtube`, `youtube:<channel>`) place it; once they land, the downloader's
    status line and the bottom bar say where they went. Always the callable (the downloader's window is kept and
    raised: one opened before the library must still hand its files over; L1 N2). Raises when no library is open, the
    files aren't in the open library's folder (the language switched mid-download; L1 S3) or the store can't be
    written — the downloader says why; the files wait in Processed."""

    def complete(paths):
        writer = getattr(shell.services, "writer", None)  # the library open now (a switch makes another)
        if writer is None:
            raise RuntimeError(strings.YT_NO_LIBRARY)
        from app.library_store import library_rel
        data_dir = getattr(writer.opener, "data_dir", None)
        if data_dir is not None and any(library_rel(data_dir, os.fspath(p)) is None for p in paths):
            raise RuntimeError(strings.YT_OTHER_LIBRARY)
        try:
            rules = shell.services.settings.get().get("placing_rules")
        except Exception:
            rules = None
        rules = {str(k): v for k, v in rules.items()} if hasattr(rules, "items") else {}
        language = writer.language
        relay = bridge.Relay(parent=shell)
        relay.said.connect(lambda counts: _arrived(shell, relay, counts))
        seq = writer.register(paths, lambda path: youtube_record(path, language), rules=rules,
                              label=strings.YT_ARRIVED_LABEL,
                              done=lambda waiting, placed, missed: relay.call((waiting, placed, missed)))
        if seq is None:
            relay.deleteLater()
            raise RuntimeError(strings.YT_READ_ONLY.format(reason=writer.reason()))
    return complete


def _arrived(shell, relay, counts):
    try:
        relay.deleteLater()
    except RuntimeError:
        pass
    line = arrived_line(*counts)
    if not line:
        return
    say_in_bar(shell, line)
    win = shell.__dict__.get("_secondary_windows", {}).get("youtube-downloader")
    if win is not None and not win.gone and getattr(win, "running", None) is None:
        win.say(line)                                     # its done line names the tray (no link: the tray is Q1's)
# --- end W3.2 B


def _open_preview(shell):
    from modules.youtube_downloader import open_preview
    return open_preview(shell)


OPENERS += [
    Opener("youtube-downloader", strings.DOOR_TRANSCRIPTS, strings.DOOR_TRANSCRIPTS_TIP,
           lambda s, _l: bool(s.get("enable_youtube_transcripts")), _open_downloader, module="youtube_downloader"),
    Opener("youtube-preview", strings.DOOR_PREVIEW, strings.DOOR_PREVIEW_TIP,
           lambda s, _l: bool(s.get("enable_youtube_preview")), _open_preview, module="youtube_downloader"),
    Opener("koe", strings.DOOR_SPEECH, strings.DOOR_SPEECH_TIP, _koe_door, _open_koe, module="koe"),
]


# row 3: the Anki window
def _open_anki(shell):
    from app.qt import anki_window
    return anki_window.open_anki(shell)


OPENERS += [Opener("anki", strings.ANKI_DOOR, strings.ANKI_DOOR_TIP, always, _open_anki)]

# row 6: 順 Junban (+ Put Anki back) — the 順 button's rule (`enable_junban`, as the Tk dashboard shows it); Put back
# shows whenever Junban is installed (the way back stays, switched on or not: Settings → Data & System's rule).


def _junban_on(settings, _language):
    return bool(settings.get("enable_junban", False))


def _open_junban(shell):
    from modules.junban import open_junban_qt
    return open_junban_qt(shell)


def _open_put_back(shell):
    from modules.junban import open_put_back_qt
    return open_put_back_qt(shell)


OPENERS += [
    Opener("junban", strings.JUNBAN_DOOR, strings.JUNBAN_DOOR_TIP, _junban_on, _open_junban, module="junban"),
    Opener("put-back", strings.PUT_BACK_DOOR, strings.PUT_BACK_DOOR_TIP, always, _open_put_back, module="junban"),
]

# row 5: Backfill (+ Fields, パターン data) — Junban's window: shown while 順 is switched on and Junban imports (the Tk
# dashboard's `backfill_available`), opened lazily through the module's `open_backfill_qt`.


def _backfill_available(settings, _language):
    return settings.get("enable_junban", True) is not False


def _open_backfill(shell):
    from modules.junban import open_backfill_qt
    return open_backfill_qt(shell)


OPENERS += [Opener("backfill", strings.BACKFILL_DOOR, strings.BACKFILL_DOOR_TIP, _backfill_available, _open_backfill,
                   "junban")]


# The optional modules the doors name, looked for once per process (a module can't appear mid-session), on a worker
# after the window opened: name -> bool. A door that names a module stays hidden until its module was found.
_FOUND = {}
_LOOKING = set()                                          # being looked for now (asked once, whichever row asks)
_ROWS = weakref.WeakSet()                                 # the rows told when the look ends


def _look_for(names):
    """(A worker.) -> {name: whether modules/<name> imports}."""
    return {name: module_present(name) for name in names}


def module_present(name):
    """Whether `modules/<name>` can be imported (found, not run: nothing of it is loaded here)."""
    try:
        return importlib.util.find_spec(f"modules.{name}") is not None
    except (ImportError, ValueError):
        return False


def available(opener, settings, language):
    """Whether `opener`'s door shows: its module imports (when it names one) and its own rule says so."""
    if opener.module is not None and not _FOUND.get(opener.module, False):
        return False
    try:
        return bool(opener.available(settings, language))
    except Exception as e:
        applog.log("windows", f"{opener.name}'s door: {e}")
        return False


# --- the Settings tab's list, until W3.3 / W3.2 (IK-16) --------------------------------------------------------- #
def _found(found):
    _FOUND.update(found)
    _LOOKING.difference_update(found)
    for row in list(_ROWS):
        row.refresh()


def _moves_doors(keys):
    """Whether a settings write can move a door: the language, or a module's switch (`enable_*`)."""
    return any(k == "target_language" or k.startswith("enable_") for k in keys)


def _look():
    """The optional modules no one has looked for yet, looked for on a worker (once per process)."""
    wanted = sorted({op.module for op in OPENERS if op.module} - set(_FOUND) - _LOOKING)
    if wanted:
        _LOOKING.update(wanted)
        bridge.run_in_worker(_look_for, wanted, then=_found,
                             failed=lambda info: applog.log("windows", f"looking for the modules: {info[1]}"))


def follow_doors(widget):
    """(Row 3.) A window with doors of its own: `widget.refresh()` is called when the modules were looked for — the
    look started now if no one asked yet (the Settings tab's row may not exist)."""
    _ROWS.add(widget)
    _look()


class _Doors(QWidget):
    """The Settings tab's row of doors. Asked again when the page shows, when a settings write can move a door, and
    when the modules were looked for; repaints only the buttons whose answer changed (S19)."""

    def __init__(self, shell, page):
        super().__init__(page)
        self.shell, self.page = shell, page
        self.buttons = {}
        self.paints = 0
        page.installEventFilter(self)
        _ROWS.add(self)

    def refresh(self):
        try:
            settings = self.shell.services.settings.get()
            language = settings.get("target_language") or "ja"
            for op in OPENERS:
                b = self.buttons.get(op.name)
                show_it = available(op, settings, language)
                if b is not None and b.isHidden() == show_it:
                    b.setVisible(show_it)
                    self.paints += 1
        except RuntimeError:                              # gone with its window
            pass

    def attach(self):
        """After the window's first pass: the settings' writes heard, the modules looked for on a worker."""
        heard = getattr(self.shell, "bridge", None)
        if heard is not None:
            heard.settings_written.connect(self._written)
        _look()

    def _written(self, keys):
        if _moves_doors(keys):
            self.refresh()

    def eventFilter(self, obj, event):
        if obj is self.page and event.type() == QEvent.Type.Show:
            self.refresh()
        return False


def launchers(shell, page):
    """The ported windows' doors on `page` (the Settings tab's waiting page): one button each, shown while its door is
    available. -> the row (its `buttons`: name -> button)."""
    row = _Doors(shell, page)
    row.setObjectName("launchers")
    row.setAccessibleName(strings.LAUNCHERS_NAME)
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.addStretch(1)
    for op in OPENERS:
        b = QPushButton(op.label, row)
        b.setToolTip(op.tip)
        b.setAccessibleName(op.label)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(lambda _c=False, o=op: launch(shell, o))
        line.addWidget(b)
        row.buttons[op.name] = b
    line.addStretch(1)
    row.refresh()
    QTimer.singleShot(0, row.attach)
    box = page.layout()
    box.insertWidget(max(0, box.count() - 1), row)        # under the page's line, above its closing stretch
    return row


def launch(shell, opener):
    try:
        return opener.open(shell)
    except Exception as e:                                # a door that can't open says so in the bar, never a box
        applog.log("windows", f"{opener.name} didn't open: {e}")
        say_in_bar(shell, strings.OPEN_FAILED.format(name=opener.label, why=e))
        return None
