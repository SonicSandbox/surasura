"""Settings › Content › *Library folders* (SRC W1b; the RUNBOOK §3 W1): the folders Surasura reads where they are, drawn
into the slot the page leaves for them (`custom_row`), as *Where new arrivals go*'s lines are (`settings_rules.py`).

`attach(page)` -> `SourcesRow`: called once by whoever mounts the page (the shell's `mount_settings`), beside the other
rows' packages — never by the page itself.

- **One line per folder being read**, in the order added: its path (cut in the middle when the row is narrow, whole on
  hover), how many episodes came from it (*not reachable now* when the last look couldn't reach it) and *Stop reading*
  (`Store.stop_source` on the looks' worker: its items and their records stay — the tooltip says so, and the bar
  after). No folder yet: the line saying so, and *Add a folder…* beside it (the button that fixes it).
- ***Skipped folders*** (K6): under the folders, each folder Surasura never reads (⋯ › *Never read this folder*, setup's
  *Skip a folder…*) with ***Read again*** (`SourceLooks.read_again` on the looks' worker: its files come back at once);
  hidden while there is none.
- ***Add a folder…*** is + Add's *A folder…* (`Adder.read_folder`: read it where it is); ***Look again*** is Refresh
  (`ShellWindow.refresh_sources`: every folder, in full).
- **Shown from the shell's looks** (`ShellWindow.sources`, `sources_seen`): asked once as the row is made, repainted
  when a look, an add or a stop lands — only the lines that changed (S19), inside the page's hold (it never moves).
  Each line belongs to its language's library: another language's summary replaces every line, and *Stop reading*
  names its language, so a root id another store also holds is never stopped there (ids repeat across stores).
  Without a library (no looks), the buttons are greyed and say why.

GUI_Design_Guidelines_Qt: the page's controls and label styles (no new rules), a tooltip on every button.
"""
from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import theme
from app.qt import style, windows
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.qt.settings_rules import _SourceWords

ROW_ID = "library_folders"


def _f():
    return theme.text_factor(style.current()[1])


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def attach(page):
    """The *Library folders* row filled into `page`'s slot -> its `SourcesRow` (kept by the page as a child)."""
    return SourcesRow(page)


def count_words(source):
    """A folder's line: *412 episodes*, and *not reachable now* when the last look couldn't reach it."""
    n = source.get("items") or 0
    words = S.SOURCES_COUNT_ONE if n == 1 else S.SOURCES_COUNT.format(n=n)
    return S.SOURCES_AWAY.format(count=words) if source.get("reachable") is False else words


class SourceLine(QWidget):
    """One folder's line: its path, its count and *Stop reading* (`on_stop(root_id)`)."""

    def __init__(self, source, on_stop, parent=None):
        super().__init__(parent)
        self.setObjectName("settingssource")
        self.root = source["id"]
        self.source = None
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(8 * _f()))
        self.words = _SourceWords(source["path"], self)
        self.words.setObjectName("settingsaffix")
        line.addWidget(self.words, 1)
        self.count = QLabel(self)
        self.count.setObjectName("settingsvalue")
        line.addWidget(self.count)
        self.stop = sc.Door(S.SOURCES_STOP, name=S.SOURCES_STOP_NAME.format(path=source["path"]), parent=self)
        self.stop.clicked.connect(lambda _c=False: on_stop(self.root))
        line.addWidget(self.stop)
        self.show_source(source)

    def show_source(self, source):
        """-> True when anything it shows moved (repainted only then)."""
        if source == self.source:
            return False
        self.source = dict(source)
        words = count_words(source)
        if self.count.text() != words:
            self.count.setText(words)
        self.stop.setToolTip(S.SOURCES_STOP_TIP.format(path=source["path"], n=source.get("items") or 0))
        return True


class SkippedLine(QWidget):
    """K6: one skipped folder's line: its path and *Read again* (`on_read(folder_id)`)."""

    def __init__(self, folder, on_read, parent=None):
        super().__init__(parent)
        self.setObjectName("settingssource")
        self.folder = dict(folder)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(8 * _f()))
        self.words = _SourceWords(folder["path"], self)
        self.words.setObjectName("settingsaffix")
        line.addWidget(self.words, 1)
        self.read = sc.Door(S.SOURCES_READ_AGAIN, tooltip=S.SOURCES_READ_AGAIN_TIP.format(path=folder["path"]),
                            name=S.SOURCES_READ_AGAIN_NAME.format(path=folder["path"]), parent=self)
        self.read.clicked.connect(lambda _c=False: on_read(self.folder["id"]))
        line.addWidget(self.read)


class SourcesRow(QObject):
    """The row's lines (`lines`: root id -> SourceLine), the empty state's words (`none`), *Add a folder…* (`add`) and
    *Look again* (`look`); under the folders, K6's *Skipped folders* (`skipped`: folder id -> SkippedLine, in
    `skip_box`, hidden while there is none)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.lines = {}
        self.language = getattr(self.shell, "language", None)     # the library the lines are of
        slot = page.custom_row(ROW_ID)
        self.box = QWidget(slot)
        self.box.setObjectName("settingssources")
        column = QVBoxLayout(self.box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(round(6 * _f()))
        self.skipped = {}                                 # K6: the skipped folders' lines (under the folders)
        self.skip_box = QWidget(self.box)
        skips = QVBoxLayout(self.skip_box)
        skips.setContentsMargins(0, round(4 * _f()), 0, 0)
        skips.setSpacing(round(6 * _f()))
        self.skip_title = QLabel(S.SOURCES_SKIPPED, self.skip_box)
        self.skip_title.setObjectName("settingsvalue")
        skips.addWidget(self.skip_title)
        self.skip_box.setVisible(False)
        column.addWidget(self.skip_box)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        self.known = bool(getattr(self.shell, "sources", ()))    # a listing has landed (until then: the waiting words)
        self.none = QLabel(S.SOURCES_NONE, self.box)
        self.none.setObjectName("settingsaffix")
        self.none.setVisible(False)
        foot.addWidget(self.none)
        foot.addStretch(1)
        self.look = sc.Door(S.SOURCES_LOOK, tooltip=S.SOURCES_LOOK_TIP, parent=self.box)
        self.look.clicked.connect(lambda _c=False: self.look_again())
        foot.addWidget(self.look)
        self.add = sc.Door(S.SOURCES_ADD, tooltip=S.SOURCES_ADD_TIP, parent=self.box)
        self.add.clicked.connect(lambda _c=False: self.add_folder())
        foot.addWidget(self.add)
        column.addLayout(foot)
        slot.layout().addWidget(self.box)
        self.reads = 0                                    # the sources shown (tests: repainted only when they moved)
        looks = self._looks()
        self._enable(looks is not None)
        if looks is not None and not self.known:
            self.none.setText(S.SOURCES_LISTING)            # waiting for the first listing, never "No folders yet"
        seen = getattr(self.shell, "sources_seen", None)
        if seen is not None:
            seen.connect(self._seen)
        self.show_sources(getattr(self.shell, "sources", ()) or ())
        if looks is not None:
            looks.listing()                               # the counts as they stand, read on the looks' worker

    def alive(self):
        return _alive(self.page)

    def _looks(self):
        return getattr(self.shell, "looks", None) if self.shell is not None else None

    def _enable(self, on):
        """*Look again* and *Add a folder…* act while there are looks (a library open); greyed with why when not."""
        for button, tip in ((self.look, S.SOURCES_LOOK_TIP), (self.add, S.SOURCES_ADD_TIP)):
            if button.isEnabled() != on:
                button.setEnabled(on)
                button.setToolTip(tip if on else S.STORE_NO_LIBRARY_TIP)

    # --- showing ---------------------------------------------------------------------------------------------- #
    def _seen(self, summary):
        if not self.alive() or not isinstance(summary, dict):
            return
        language = summary.get("language", self.language)
        if language != getattr(self.shell, "language", language):
            return                                        # a language left's late answer
        self._enable(self._looks() is not None)
        reset = language != self.language
        self.language = language
        if not self.known:
            self.known = True
            self.none.setText(S.SOURCES_NONE)
        self.show_sources(summary.get("sources") or (), reset=reset)
        if "skipped" in summary or reset:
            self.show_skipped(summary.get("skipped") or (), reset=reset)

    def show_skipped(self, folders, reset=False):
        """K6: the *Skipped folders* lines made to match `folders` ({id, path}): only a line that changed is touched;
        the list hidden while there is none."""
        if not self.alive():
            return
        ids = [f["id"] for f in folders]
        gone = [i for i in self.skipped if reset or i not in ids]
        added = [f for f in folders if f["id"] not in self.skipped or f["id"] in gone]
        if not (gone or added) and self.skip_box.isHidden() != bool(ids):
            return
        with self.page.hold(self.page.row(ROW_ID)):
            box = self.skip_box.layout()
            for i in gone:
                line = self.skipped.pop(i)
                box.removeWidget(line)
                line.hide()
                line.deleteLater()
            for f in added:
                line = SkippedLine(f, self.read_again, parent=self.skip_box)
                box.insertWidget(1 + ids.index(f["id"]), line)
                self.skipped[f["id"]] = line
                line.show()
            if self.skip_box.isHidden() == bool(ids):
                self.skip_box.setVisible(bool(ids))
        if added and getattr(self.page, "built", False):
            self.page._tab_order()

    def read_again(self, folder_id):
        """K6 *Read again*: on the looks' worker; the line goes and the bar says its files come back once it landed."""
        looks = self._looks()
        line = self.skipped.get(folder_id)
        if looks is None or line is None or not hasattr(looks, "read_again"):
            return False
        path = line.folder["path"]
        from app.qt import bridge
        relay = bridge.Relay(self)

        def done(answer):
            relay.deleteLater()
            if answer.get("read") and self.shell is not None:
                windows.say_in_bar(self.shell, S.SOURCES_READ_AGAIN_DONE.format(path=path))
            elif _alive(line):
                line.read.setEnabled(True)
        relay.said.connect(done)
        if not looks.read_again(folder_id, relay.call, language=self.language):
            relay.deleteLater()
            return False
        line.read.setEnabled(False)                       # one press per click
        return True

    def show_sources(self, sources, reset=False):
        """The lines made to match `sources` (being read): only a line that changed is touched; `reset` (another
        language's library): every line made again."""
        if not self.alive():
            return
        wanted = [s for s in sources if s.get("on", True)]
        ids = [s["id"] for s in wanted]
        gone = [r for r in self.lines if reset or r not in ids]
        moved = [s for s in wanted if s["id"] in self.lines and s["id"] not in gone and self.lines[s["id"]].source != s]
        added = [s for s in wanted if s["id"] not in self.lines or s["id"] in gone]
        empty = not wanted
        if not (gone or moved or added) and self.none.isHidden() != empty:
            return
        self.reads += 1
        with self.page.hold(self.page.row(ROW_ID)):
            column = self.box.layout()
            for root in gone:
                line = self.lines.pop(root)
                column.removeWidget(line)
                line.hide()
                line.deleteLater()
            for source in moved:
                self.lines[source["id"]].show_source(source)
            for source in added:
                line = SourceLine(source, self.stop, parent=self.box)
                column.insertWidget(ids.index(source["id"]), line)
                self.lines[source["id"]] = line
                if self.box.isVisible():
                    line.show()
            if self.none.isHidden() == empty:
                self.none.setVisible(empty)
        if added and getattr(self.page, "built", False):
            self.page._tab_order()

    # --- acting ----------------------------------------------------------------------------------------------- #
    def add_folder(self, folder=None):
        """*Add a folder…*: the picker (or `folder`, tests), then + Add's *read it where it is*."""
        adder = getattr(self.shell, "adder", None)
        if adder is None:
            return False
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self.page, S.SOURCES_PICK_TITLE)
        return adder.read_folder(folder) if folder else False

    def look_again(self):
        refresh = getattr(self.shell, "refresh_sources", None)
        return refresh() if refresh is not None else False

    def stop(self, root_id):
        """*Stop reading*: on the looks' worker; the bar says its episodes stay; the line goes once the stop landed."""
        looks = self._looks()
        line = self.lines.get(root_id)
        if looks is None or line is None:
            return False
        source = dict(line.source)
        from app.qt import bridge
        relay = bridge.Relay(self)

        def stopped(answer):
            relay.deleteLater()
            n = source.get("items") or 0
            text = S.SOURCES_STOPPED_ONE.format(path=source["path"]) if n == 1 else \
                S.SOURCES_STOPPED.format(path=source["path"], n=n)
            if answer.get("stopped") and self.shell is not None:
                windows.say_in_bar(self.shell, text)
            elif _alive(line):
                line.stop.setEnabled(True)
        relay.said.connect(stopped)
        busy = looks.busy() if hasattr(looks, "busy") else False
        if not looks.stop(root_id, relay.call, language=self.language):
            relay.deleteLater()                           # refused (closed, another language): nothing stopped
            return False
        line.stop.setEnabled(False)                       # one stop per click
        if busy and self.shell is not None:               # S6: a look under way lets it go after the file it's on
            windows.say_in_bar(self.shell, S.SOURCES_STOPPING.format(path=source["path"]))
        return True
