"""Settings › Content › *Library folders* (SRC W1b; the RUNBOOK §3 W1; laptop row 32): the folders Surasura reads
where they are — on the page a short summary, *Add a folder…* and *Manage folders…*; the folders themselves in their own
window (*Library folders*), so a long list never makes the page long.

`attach(page)` -> `SourcesRow`: called once by whoever mounts the page (the shell's `mount_settings`), beside the other
rows' packages — never by the page itself.

- **The page's row** (`SourcesRow`): *4 folders · 1 not reachable now · 2 skipped* (`summary_words`; no folder yet: the
  line saying so), ***Add a folder…*** right there (+ Add's *A folder…*: `Adder.read_folder`, read it where it is) and
  the door ***Manage folders…*** (`windows.OPENERS` "library-folders", the catalog's door). Repainted only when its
  words moved (S19), inside the page's hold.
- **The window** (`FoldersWindow`, on `windows.SecondaryWindow`; one of its kind, `open_window`): **one line per folder
  being read**, in the order added — its path (cut in the middle when narrow, whole on hover), how many episodes came
  from it (*not reachable now* when the last look couldn't reach it) and *Stop reading* (`Store.stop_source` on the
  looks' worker: its items and their records stay — the tooltip says so, and the bar after); ***Skipped folders*** (K6)
  under them, each with ***Read again*** (`SourceLooks.read_again` on the looks' worker: its files come back at once),
  hidden while there is none; ***Look again*** (Refresh: `ShellWindow.refresh_sources`, every folder in full) and *Add a
  folder…* (the page's one) at its foot. Only the lines that changed are touched (S19).
- **Both shown from the shell's looks** (`ShellWindow.sources`, `sources_seen`; `_heard`, one rule for both): asked once
  as each is made, repainted when a look, an add, a stop or a read-again lands. What is shown belongs to its language's
  library: another language's summary replaces it, a language left's late answer is dropped, and *Stop reading* names
  its language, so a root id another store also holds is never stopped there (ids repeat across stores). Without a
  library (no looks), the buttons are greyed and say why.

***Start a fresh library…*** (K7, its own row below): the confirm sheet says what goes and what stays, with *Also
forget my known words* (off); Esc, Back or a click outside is No. Yes → `SourceLooks.fresh` on the looks' worker (the
store's `start_fresh`: one dated backup, then the folders read again from scratch); the bar says *Fresh library:
reading your folders…* once the reset landed, or why nothing was changed. Greyed with why while there is no library
or it can't be written, and while one runs. No restore button (the backup's `reset.json` says how by hand).

GUI_Design_Guidelines_Qt: the page's controls and label styles, the window's base (Esc closes it), a tooltip on every
button.
"""
from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app import theme
from app.qt import style, windows
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.qt.settings_rules import _SourceWords
from app.services.source_looks import offline

ROW_ID = "library_folders"
FRESH_ID = "fresh_library"
WINDOW = "library-folders"                                # its opener's name (`windows.OPENERS`, the row's door)


def _f():
    return theme.text_factor(style.current()[1])


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def attach(page):
    """The *Library folders* row filled into `page`'s slot -> its `SourcesRow` (kept by the page as a child); the
    *Start a fresh library* row beside it (`SourcesRow.fresh`)."""
    return SourcesRow(page)


def open_window(shell):
    """*Manage folders…*: the *Library folders* window, one of its kind (raised when open)."""
    return windows.show(shell, WINDOW, FoldersWindow)


def count_words(source):
    """A folder's line: *412 episodes*, and *not reachable now* when the last look couldn't reach it."""
    n = source.get("items") or 0
    words = S.SOURCES_COUNT_ONE if n == 1 else S.SOURCES_COUNT.format(n=n)
    return S.SOURCES_AWAY.format(count=words) if source.get("reachable") is False else words


def summary_words(sources, skipped=(), known=True):
    """The page's summary of the folders being read (`sources`, the stopped ones left out) and the skipped folders
    under them (`skipped`: {id, root, path}; one under a stopped folder isn't counted): *4 folders · 1 not reachable
    now · 2 skipped*; no folder: the line saying so, alone; `known` False: still looking."""
    if not known:
        return S.SOURCES_LISTING
    wanted = [s for s in sources if s.get("on", True)]
    if not wanted:
        return S.SOURCES_NONE
    n = len(wanted)
    parts = [S.SOURCES_FOLDERS_ONE if n == 1 else S.SOURCES_FOLDERS.format(n=n)]
    away = len(offline(wanted))                           # the offline line's own rule
    if away:
        parts.append(S.SOURCES_AWAY_N.format(n=away))
    roots = {s["id"] for s in wanted}
    under = sum(1 for f in skipped if f.get("root") in roots)
    if under:
        parts.append(S.SOURCES_SKIPPED_N.format(n=under))
    return " · ".join(parts)


def _heard(holder, summary):
    """A look's summary as `holder` (the page's row, the window) takes it — one rule for both: None for a language
    left's late answer (or no summary), else whether it is another language's library than the one shown (`reset`);
    `holder.lines_of` follows it, and `holder.known` (False while the summary only says a listing is on its way: the
    shell's language switch)."""
    if not isinstance(summary, dict):
        return None
    language = summary.get("language", holder.lines_of)
    if language != getattr(holder.shell, "language", language):
        return None
    reset = language != holder.lines_of
    holder.lines_of = language
    holder.known = not summary.get("listing")
    return reset


def _looks(shell):
    return getattr(shell, "looks", None) if shell is not None else None


def cant_write(services):
    """Why the library open can't be written now (the writer's reason, in the page's words), or None — the one rule
    for *Start a fresh library*, *Add a folder…*, *Stop reading* and *Read again*."""
    writer = getattr(services, "writer", None)
    try:
        reason = writer.reason() if writer is not None else None
    except Exception:
        reason = None
    return S.FRESH_NOT_WRITABLE.format(reason=reason) if reason else None


def why_not(shell):
    """Why the folders can't be added, stopped or read again now (a button's greyed tip), or None."""
    if _looks(shell) is None:
        return S.STORE_NO_LIBRARY_TIP
    return cant_write(getattr(shell, "services", None))


def _turn(button, on, tip):
    """`button` on or greyed, with `tip` (its own words, or why it is greyed). Repainted only when it moved (S19)."""
    if button.isEnabled() != on:
        button.setEnabled(on)
    if button.toolTip() != tip:
        button.setToolTip(tip)


def _acting(shell):
    """The stops and read-agains under way, kept on the shell — ("stop" | "read", language, id) — so a window opened
    again before one answered shows its button greyed, never a second press."""
    return shell.__dict__.setdefault("_folders_acting", set()) if shell is not None else set()


def add_folder(shell, parent, folder=None):
    """*Add a folder…* (the page's and the window's): the picker over `parent` (or `folder`, tests), then + Add's *read
    it where it is*."""
    adder = getattr(shell, "adder", None)
    if adder is None or why_not(shell) is not None:
        return False
    if folder is None:
        folder = QFileDialog.getExistingDirectory(parent, S.SOURCES_PICK_TITLE)
    return adder.read_folder(folder) if folder else False


def look_again(shell):
    """*Look again*: every folder, in full (the Refresh key's)."""
    refresh = getattr(shell, "refresh_sources", None)
    return refresh() if refresh is not None else False


class SourceLine(QWidget):
    """One folder's line: its path, its count and *Stop reading* (`on_stop(root_id)`; `tip`: its own words)."""

    def __init__(self, source, on_stop, parent=None):
        super().__init__(parent)
        self.setObjectName("settingssource")
        self.root = source["id"]
        self.source = None
        self.tip = ""
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
        """-> True when anything it shows moved (repainted only then; the button's tip by the window's `_enable`)."""
        if source == self.source:
            return False
        self.source = dict(source)
        words = count_words(source)
        if self.count.text() != words:
            self.count.setText(words)
        self.tip = S.SOURCES_STOP_TIP.format(path=source["path"], n=source.get("items") or 0)
        return True


class SkippedLine(QWidget):
    """K6: one skipped folder's line: its path and *Read again* (`on_read(folder_id)`; `tip`: its own words)."""

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
        self.tip = S.SOURCES_READ_AGAIN_TIP.format(path=folder["path"])
        self.read = sc.Door(S.SOURCES_READ_AGAIN, name=S.SOURCES_READ_AGAIN_NAME.format(path=folder["path"]),
                            parent=self)
        self.read.clicked.connect(lambda _c=False: on_read(self.folder["id"]))
        line.addWidget(self.read)


class SourcesRow(QObject):
    """The page's row: its summary (`summary`), *Add a folder…* (`add`); *Manage folders…* is the catalog's door
    (`page.row(ROW_ID).doors[WINDOW]`). `paints`: how many times the summary was repainted (S19)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.lines_of = getattr(self.shell, "language", None)     # the library the summary is of
        self.sources = tuple(getattr(self.shell, "sources", ()) or ())
        self.skipped = ()                                 # the skipped folders (K6), as the last summary said
        looks = _looks(self.shell)
        self.known = bool(self.sources) or looks is None  # a listing has landed, or there is none to wait for
        self.paints = 0
        slot = page.custom_row(ROW_ID)
        self.summary = QLabel(slot)
        self.summary.setObjectName("settingsvalue")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        slot.layout().addWidget(self.summary)
        self.add = sc.Door(S.SOURCES_ADD, tooltip=S.SOURCES_ADD_TIP, parent=slot)
        self.add.clicked.connect(lambda _c=False: self.add_folder())
        slot.layout().addWidget(self.add)
        self._enable()
        seen = getattr(self.shell, "sources_seen", None)
        if seen is not None:
            seen.connect(self._seen)
        self._paint()
        if looks is not None:
            looks.listing()                               # the counts as they stand, read on the looks' worker
        self.fresh = FreshRow(page) if FRESH_ID in getattr(page, "slots", {}) else None

    def alive(self):
        return _alive(self.page)

    def _enable(self):
        why = why_not(self.shell)
        _turn(self.add, why is None, why or S.SOURCES_ADD_TIP)

    def _seen(self, summary):
        if not self.alive():
            return
        reset = _heard(self, summary)
        if reset is None:
            return
        self._enable()
        self.sources = tuple(summary.get("sources") or ())
        if "skipped" in summary or reset:
            self.skipped = tuple(summary.get("skipped") or ())
        self._paint()

    def _paint(self):
        """The summary's words, set only when they moved (S19), inside the page's hold (it never moves)."""
        words = summary_words(self.sources, self.skipped, self.known)
        if self.summary.text() == words:
            return
        with self.page.hold(self.page.row(ROW_ID)):
            self.summary.setText(words)
            self.summary.setAccessibleName(words)
        self.paints += 1

    def add_folder(self, folder=None):
        return add_folder(self.shell, self.page, folder)


class FoldersWindow(windows.SecondaryWindow):
    """*Library folders*: the lines (`lines`: root id -> SourceLine), the empty state's words (`none`), K6's *Skipped
    folders* (`skipped`: folder id -> SkippedLine, in `skip_box`, hidden while there is none), *Look again* (`look`) and
    *Add a folder…* (`add`). `reads`: how many times the folders' lines were touched (S19)."""

    def __init__(self, shell, language=None):
        super().__init__(shell, S.FOLDERS_NAME, language)
        self.lines = {}
        self.skipped = {}
        self.reads = 0
        self.lines_of = getattr(shell, "language", None)         # the library the lines are of
        looks = _looks(shell)
        self.known = bool(getattr(shell, "sources", ())) or looks is None
        intro = QLabel(S.FOLDERS_LINE, self)
        intro.setObjectName("windowline")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("foldersscroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # its buttons take Tab, never the scroll itself
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.box = QWidget()
        self.box.setObjectName("foldersbody")
        column = QVBoxLayout(self.box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(round(6 * _f()))
        self.none = QLabel(self.box)
        self.none.setObjectName("windowline")
        self.none.setVisible(False)
        column.addWidget(self.none)
        self.skip_box = QWidget(self.box)
        skips = QVBoxLayout(self.skip_box)
        skips.setContentsMargins(0, round(10 * _f()), 0, 0)
        skips.setSpacing(round(6 * _f()))
        self.skip_title = QLabel(S.SOURCES_SKIPPED, self.skip_box)
        self.skip_title.setObjectName("windowheading")
        skips.addWidget(self.skip_title)
        self.skip_box.setVisible(False)
        column.addWidget(self.skip_box)
        column.addStretch(1)
        self.scroll.setWidget(self.box)
        self.body.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        self.look = sc.Door(S.SOURCES_LOOK, tooltip=S.SOURCES_LOOK_TIP, parent=self)
        self.look.clicked.connect(lambda _c=False: look_again(self.shell))
        foot.addWidget(self.look)
        self.add = sc.Door(S.SOURCES_ADD, tooltip=S.SOURCES_ADD_TIP, parent=self)
        self.add.clicked.connect(lambda _c=False: add_folder(self.shell, self))
        foot.addWidget(self.add)
        self.body.addLayout(foot)
        seen = getattr(shell, "sources_seen", None)
        if seen is not None:
            seen.connect(self._seen)
        self.show_sources(getattr(shell, "sources", ()) or ())
        self._enable()
        if looks is not None:
            looks.listing()                               # the counts and the skipped folders, on the looks' worker

    def _enable(self):
        """Every button greyed with why while nothing can be written (*Look again* only without a library); a stop
        or a read-again under way keeps its button greyed. Only what moved is touched (S19)."""
        why = why_not(self.shell)
        no_library = _looks(self.shell) is None
        _turn(self.look, not no_library, S.STORE_NO_LIBRARY_TIP if no_library else S.SOURCES_LOOK_TIP)
        _turn(self.add, why is None, why or S.SOURCES_ADD_TIP)
        acting = _acting(self.shell)
        for root, line in self.lines.items():
            _turn(line.stop, why is None and ("stop", self.lines_of, root) not in acting, why or line.tip)
        for folder_id, line in self.skipped.items():
            _turn(line.read, why is None and ("read", self.lines_of, folder_id) not in acting, why or line.tip)

    def _tab_order(self):
        """Tab as the window reads: the folders' *Stop reading*, the skipped folders' *Read again*, *Look again*,
        *Add a folder…* (lines made later would otherwise join the chain's end)."""
        def shown(layout):
            return [layout.itemAt(i).widget() for i in range(layout.count())]
        chain = [w.stop for w in shown(self.box.layout()) if isinstance(w, SourceLine)]
        chain += [w.read for w in shown(self.skip_box.layout()) if isinstance(w, SkippedLine)]
        chain += [self.look, self.add]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

    # --- showing ---------------------------------------------------------------------------------------------- #
    def _seen(self, summary):
        if self.gone:
            return
        reset = _heard(self, summary)
        if reset is None:
            return
        self.show_sources(summary.get("sources") or (), reset=reset)
        if "skipped" in summary or reset:
            self.show_skipped(summary.get("skipped") or (), reset=reset)
        self._enable()

    def _grow(self):
        """New lines shown: the window grows to hold them, up to the screen's room below it, then they scroll (it never
        shrinks). Measured from the lines themselves (the scroll area keeps the size it first asked for)."""
        if not self.isVisible():
            return
        self.box.layout().activate()
        need = self.box.sizeHint().height() - self.scroll.viewport().height()
        screen = self.screen()
        room = screen.availableGeometry().bottom() - self.frameGeometry().bottom() if screen is not None else need
        grow = min(need, room)
        if grow > 0:
            self.resize(self.width(), self.height() + grow)

    def show_sources(self, sources, reset=False):
        """The lines made to match `sources` (being read): only a line that changed is touched; `reset` (another
        language's library): every line made again. The empty state says *Looking…* until a listing has landed."""
        if self.gone:
            return
        empty_words = S.SOURCES_NONE if self.known else S.SOURCES_LISTING
        if self.none.text() != empty_words:
            self.none.setText(empty_words)
        wanted = [s for s in sources if s.get("on", True)]
        ids = [s["id"] for s in wanted]
        gone = [r for r in self.lines if reset or r not in ids]
        moved = [s for s in wanted if s["id"] in self.lines and s["id"] not in gone and self.lines[s["id"]].source != s]
        added = [s for s in wanted if s["id"] not in self.lines or s["id"] in gone]
        empty = not wanted
        if not (gone or moved or added) and self.none.isHidden() != empty:
            return
        self.reads += 1
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
            line.show()
        if self.none.isHidden() == empty:
            self.none.setVisible(empty)
        if added:
            self._enable()
            self._tab_order()
            self._grow()

    def show_skipped(self, folders, reset=False):
        """K6: the *Skipped folders* lines made to match `folders` ({id, path}): only a line that changed is touched;
        the list hidden while there is none."""
        if self.gone:
            return
        ids = [f["id"] for f in folders]
        gone = [i for i in self.skipped if reset or i not in ids]
        added = [f for f in folders if f["id"] not in self.skipped or f["id"] in gone]
        if not (gone or added) and self.skip_box.isHidden() != bool(ids):
            return
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
        if added:
            self._enable()
            self._tab_order()
            self._grow()

    # --- acting ----------------------------------------------------------------------------------------------- #
    def _answered(self, key):
        """A stop's or a read-again's answer landed: no longer under way; its button as the rule says (the window
        may have closed meanwhile: the bar was told all the same)."""
        _acting(self.shell).discard(key)
        if not self.gone:
            self._enable()

    def read_again(self, folder_id):
        """K6 *Read again*: on the looks' worker; the line goes and the bar says its files come back once it landed."""
        looks = _looks(self.shell)
        line = self.skipped.get(folder_id)
        if looks is None or line is None or not hasattr(looks, "read_again") or why_not(self.shell) is not None:
            return False
        path = line.folder["path"]
        key = ("read", self.lines_of, folder_id)
        from app.qt import bridge
        relay = bridge.Relay(self.shell)                 # the bar told even once the window closed

        def done(answer):
            relay.deleteLater()
            if answer.get("read") and self.shell is not None:
                windows.say_in_bar(self.shell, S.SOURCES_READ_AGAIN_DONE.format(path=path))
            self._answered(key)
        relay.said.connect(done)
        _acting(self.shell).add(key)                      # before the ask: an answer may land at once
        line.read.setEnabled(False)                       # one press per click
        if not looks.read_again(folder_id, relay.call, language=self.lines_of):
            relay.deleteLater()
            self._answered(key)
            return False
        return True

    def stop(self, root_id):
        """*Stop reading*: on the looks' worker; the bar says its episodes stay; the line goes once the stop landed."""
        looks = _looks(self.shell)
        line = self.lines.get(root_id)
        if looks is None or line is None or why_not(self.shell) is not None:
            return False
        source = dict(line.source)
        key = ("stop", self.lines_of, root_id)
        from app.qt import bridge
        relay = bridge.Relay(self.shell)

        def stopped(answer):
            relay.deleteLater()
            n = source.get("items") or 0
            text = S.SOURCES_STOPPED_ONE.format(path=source["path"]) if n == 1 else \
                S.SOURCES_STOPPED.format(path=source["path"], n=n)
            if answer.get("stopped") and self.shell is not None:
                windows.say_in_bar(self.shell, text)
            self._answered(key)
        relay.said.connect(stopped)
        busy = looks.busy() if hasattr(looks, "busy") else False
        _acting(self.shell).add(key)
        line.stop.setEnabled(False)                       # one stop per click
        if not looks.stop(root_id, relay.call, language=self.lines_of):
            relay.deleteLater()                           # refused (closed, another language): nothing stopped
            self._answered(key)
            return False
        if busy and self.shell is not None:               # S6: a look under way lets it go after the file it's on
            windows.say_in_bar(self.shell, S.SOURCES_STOPPING.format(path=source["path"]))
        return True


class FreshRow(QObject):
    """*Start a fresh library…* (K7): `button`; `card` while the sheet is open; `running` from Yes until the reset
    answered."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.card = None
        self.running = False
        self.counting = False                             # the sheet's counts being read (the looks' worker)
        slot = page.custom_row(FRESH_ID)
        self.button = sc.Door(S.FRESH_OPEN, tooltip=S.FRESH_TIP, parent=slot)
        self.button.clicked.connect(lambda _c=False: self.ask())
        slot.layout().addWidget(self.button)
        seen = getattr(self.shell, "sources_seen", None)
        if seen is not None:
            seen.connect(self._seen)
        self.enable()

    def alive(self):
        return _alive(self.page)

    def _looks(self):
        return getattr(self.shell, "looks", None) if self.shell is not None else None

    def why_not(self):
        """Why the library can't be started afresh now (the button's tooltip), or None."""
        if self.running:
            return S.FRESH_RUNNING_TIP
        if self._looks() is None:
            return S.STORE_NO_LIBRARY_TIP
        return cant_write(getattr(self.page, "services", None))

    def enable(self):
        """Greyed with why while it can't run; repainted only when it turned (S19)."""
        if not self.alive():
            return
        why = self.why_not()
        tip = why or S.FRESH_TIP
        if self.button.isEnabled() != (why is None):
            self.button.setEnabled(why is None)
        if self.button.toolTip() != tip:
            self.button.setToolTip(tip)

    def _seen(self, _summary):
        self.enable()

    def ask(self):
        """The sheet: what goes, what comes back, what stays, with the store's counts of what never comes back and of
        the cards left suspended (`SourceLooks.fresh_counts`, read on the looks' worker first: the card opens when they
        land), the known-words box (off). -> the card when it opened at once (looks that can't count), else None."""
        self.enable()
        if self.card is not None and self.card.answer is not None:
            self.card = None                              # dropped (its window hidden): no callback comes (H13)
        if self.why_not() is not None or self.card is not None or self.counting:
            return None
        counts = getattr(self._looks(), "fresh_counts", None)
        if counts is None:
            return self._sheet(None)
        from app.qt import bridge
        relay = bridge.Relay(self)

        def counted(found):
            relay.deleteLater()
            self.counting = False
            if self.alive() and self.why_not() is None and self.card is None:
                self._sheet(found)
        relay.said.connect(counted)
        self.counting = True
        if not counts(relay.call):
            relay.deleteLater()
            self.counting = False
            return self._sheet(None)
        return None

    def _sheet(self, counts):
        from app.qt import confirm
        self.card = confirm.ask(self.page, S.FRESH_ASK, fresh_body(counts), S.FRESH_YES, S.FRESH_YES_TIP,
                                default_no=True, danger=True, check=S.FRESH_KNOWN, check_tip=S.FRESH_KNOWN_TIP,
                                on_answer=self._answered)
        return self.card

    def _answered(self, yes):
        card, self.card = self.card, None
        if yes:
            self.start(forget_known=bool(card is not None and card.checked))

    def start(self, forget_known=False):
        """The reset on the looks' worker (never this thread); the bar says how it went. -> True when it was queued."""
        looks = self._looks()
        if looks is None or self.running:
            return False
        from app.qt import bridge
        relay = bridge.Relay(self)

        def landed(answer):
            relay.deleteLater()
            self.running = False
            self.enable()
            if answer.get("done"):
                known = answer.get("known") or ""
                text = S.FRESH_DONE_KNOWN_KEPT.format(why=known[len("kept: "):]) if known.startswith("kept: ") \
                    else S.FRESH_DONE
            elif answer.get("aside"):
                text = S.FRESH_NOT_ALL_BACK.format(folder=answer["aside"])
            elif answer.get("failed"):
                text = S.FRESH_FAILED.format(reason=answer["failed"])
            else:
                reason = answer.get("refused")
                text = S.FRESH_REFUSED.format(reason=S.STORE_NO_LIBRARY_TIP if reason == "no-library" else reason)
            if self.shell is not None:
                windows.say_in_bar(self.shell, text)
        relay.said.connect(landed)
        self.running = True                               # before the ask: an answer may land at once
        self.enable()
        if not looks.fresh(forget_known, relay.call):
            relay.deleteLater()
            self.running = False
            self.enable()
            return False
        return True


def fresh_body(counts):
    """The sheet's words: `FRESH_BODY`, then what never comes back and the cards left suspended, by the store's counts
    (`library_store.fresh_counts`; a count of 0 says nothing; None: the counts couldn't be read)."""
    counts = counts or {}
    plural = lambda n: "" if n == 1 else "s"                                              # noqa: E731
    parts = [words.format(n=counts[key], s=plural(counts[key])) for key, words in (
        ("added", S.FRESH_GONE_ADDED), ("youtube", S.FRESH_GONE_YOUTUBE), ("other", S.FRESH_GONE_OTHER))
        if counts.get(key)]
    lines = [S.FRESH_BODY]
    if parts:
        lines.append(S.FRESH_GONE.format(parts=", ".join(parts)))
    if counts.get("suspended"):
        lines.append(S.FRESH_SUSPENDED.format(n=counts["suspended"], s=plural(counts["suspended"])))
    return "\n\n".join(lines)
