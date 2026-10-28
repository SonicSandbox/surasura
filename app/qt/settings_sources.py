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
  from it (*not reachable now* when the last look couldn't reach it) and *Stop reading* (K9: `give_stop`, the window's
  writer — a toast with Undo, as a gone folder's card stops one: its items and their records stay, the tooltip says
  so); ***Skipped folders*** (K6) under them, each with ***Read again*** (`SourceLooks.read_again` on the looks' worker: its files come back at once),
  hidden while there is none, then ***Skip a folder…*** (Q7, shown with none skipped too: the wizard's picker, the
  store's rule asked on the looks' worker — refused, why in the window's line — then ⋯'s own write,
  `item_menu.give_skip`, its toast with Undo; `skips_moved` reads the lines again as any skip lands or is undone);
  ***Look again*** (Refresh: `ShellWindow.refresh_sources`, every folder in full) and *Add a folder…* (the page's one)
  at its foot. Only the lines that changed are touched (S19).
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
import os

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app import theme
from app.qt import press as qpress
from app.qt import strings, style, windows
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.qt import wizard_strings as W
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


def _press_key(key):
    """A stop's or a read-again's press key: ("stop" | "read", language, id) -> "folders:stop:ja:3"."""
    return "folders:" + ":".join(str(part) for part in key)


def skips_moved(shell, undone=None):
    """A skip saved or undone (K6 / Q7: ⋯'s, New arrivals', *Skip a folder…*'s — the drag controller's `_skips_moved`):
    the skipped folders and the page's count read again (`looks.listing()`, on the looks' worker) while either shows —
    the *Library folders* window open, or the Settings page mounted. `undone`: the change an undo took back (its toast's
    Undo, this window's or Ctrl+Z): the window's own line for it goes (`FoldersWindow.skip_undone`). -> True when
    asked."""
    win = windows.opened(shell, WINDOW) if undone is not None else None
    if win is not None:
        win.skip_undone(undone)
    looks = _looks(shell)
    if looks is None or not hasattr(looks, "listing"):
        return False
    if windows.opened(shell, WINDOW) is None and getattr(shell, "settings_page", None) is None:
        return False
    return bool(looks.listing())


def add_folder(shell, parent, folder=None):
    """*Add a folder…* (the page's and the window's): the picker over `parent` (or `folder`, tests), then + Add's *read
    it where it is*."""
    adder = getattr(shell, "adder", None)
    if adder is None or why_not(shell) is not None:
        return False
    if folder is None:
        folder = QFileDialog.getExistingDirectory(parent, S.SOURCES_PICK_TITLE)
    return adder.read_folder(folder) if folder else False


def look_again(shell, control=None):
    """*Look again*: every folder, in full — the Refresh key's press (`refresh_sources`: `control`'s arc until the look
    ends; none, the bar's)."""
    refresh = getattr(shell, "refresh_sources", None)
    return refresh(control=control) if refresh is not None else False


class SourceLine(QWidget):
    """One folder's line: its path, its count and *Stop reading* (`on_stop(root_id)`; `tip`: its own words); alpha 4
    (Mattias's note 6): *Bring back N removed* (`back`, `on_back(root_id)`) while that folder has removed files."""

    def __init__(self, source, on_stop, parent=None, on_back=None):
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
        # --- alpha 4 P-removed: *Bring back N removed* (hidden while none; `show_removed`)
        self.removed = ()                                 # the trash ids of its removed files (`removed_under`)
        self.back_tip = ""                                # its own words (greyed: why, the window's `_enable`)
        self.back = sc.Door(strings.REMOVED_BRING_BACK.format(n=0), parent=self)
        self.back.setVisible(False)
        if on_back is not None:
            self.back.clicked.connect(lambda _c=False: on_back(self.root))
        line.addWidget(self.back)
        # --- end alpha 4 P-removed
        self.stop = qpress.room(sc.Door(S.SOURCES_STOP, name=S.SOURCES_STOP_NAME.format(path=source["path"]),
                                        parent=self))
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

    def show_removed(self, ids):
        """alpha 4 P-removed: its removed files' trash ids (`removed_under`): *Bring back N removed*, hidden at 0.
        -> True when it moved (repainted only then, S19)."""
        ids = tuple(ids or ())
        if ids == self.removed:
            return False
        self.removed = ids
        n, path = len(ids), self.source["path"] if self.source else ""
        if n:
            self.back.setText(strings.REMOVED_BRING_BACK.format(n=n))
            self.back_tip = strings.REMOVED_BRING_BACK_TIP.format(n=n, path=path)
            self.back.setAccessibleName(strings.REMOVED_BRING_BACK_NAME.format(n=n, path=path))
        if self.back.isHidden() == bool(n):
            self.back.setVisible(bool(n))
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
        name = S.SOURCES_READ_AGAIN_NAME.format(path=folder["path"])
        self.read = qpress.room(sc.Door(S.SOURCES_READ_AGAIN, name=name, parent=self))
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
        skip_line = QHBoxLayout()                         # Q7: *Skip a folder…* under them, shown with none skipped too
        skip_line.setContentsMargins(0, 0, 0, 0)
        self.skip = qpress.room(sc.Door(S.SOURCES_SKIP, tooltip=S.SOURCES_SKIP_TIP, parent=self.box))
        self.skip.clicked.connect(lambda _c=False: self.skip_folder())
        qpress.adopt(self.skip, _press_key(("skip", self.lines_of)), win=shell)   # opened again while it is checked
        skip_line.addWidget(self.skip)
        # lean B (2026-10-24, PROVISIONAL): a skip saved from here says so beside it, with the toast's one Undo
        self.skip_said = QLabel(self.box)
        self.skip_said.setObjectName("windowline")
        self.skip_said.setTextFormat(Qt.TextFormat.PlainText)
        self.skip_said.setVisible(False)
        skip_line.addWidget(self.skip_said)
        self.skip_undo = sc.Door(strings.TOAST_UNDO, tooltip=S.SOURCES_SKIP_UNDO_TIP, parent=self.box)
        self.skip_undo.clicked.connect(lambda _c=False: self.undo_skip())
        self.skip_undo.setVisible(False)
        skip_line.addWidget(self.skip_undo)
        self.skip_ticket = self.skip_language = None      # the skip whose line shows (its Undo's), its library
        # --- alpha 4 P-removed (D3): 🗑 *Removed…* beside the skips — always shown, as *Skip a folder…* is (the list says
        # *Nothing removed…* when empty: no read only to decide whether it shows)
        self.removed = sc.Door(strings.REMOVED_OPEN, tooltip=strings.REMOVED_OPEN_TIP, parent=self.box)
        self.removed.clicked.connect(lambda _c=False: self.open_removed())
        skip_line.addWidget(self.removed)
        self._removed_reading = {}                        # root id -> a `removed_under` read under way (True: again)
        from app.qt import bridge, removed
        self._removed_relay = bridge.Relay(self)
        self._removed_relay.said.connect(self._removed_landed)
        removed.follow_trash(shell, self._trash_heard)
        # --- end alpha 4 P-removed
        skip_line.addStretch(1)
        column.addLayout(skip_line)
        # the folder picker (the system's own dialog, as the wizard's; tests replace it)
        self.pick_dialog = lambda title, start: QFileDialog.getExistingDirectory(self, title, start)
        column.addStretch(1)
        self.scroll.setWidget(self.box)
        self.body.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        self.look = qpress.room(sc.Door(S.SOURCES_LOOK, tooltip=S.SOURCES_LOOK_TIP, parent=self))
        self.look.clicked.connect(lambda _c=False: self.look_again())
        qpress.adopt(self.look, "sources:refresh", win=shell)   # opened again while its look runs: the arc on it
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
        self.look.setFocus()                              # it opens on *Look again*, as before *Skip a folder…* (Q7)
        if looks is not None:
            looks.listing()                               # the counts and the skipped folders, on the looks' worker

    def _enable(self):
        """Every button greyed with why while nothing can be written (*Look again* only without a library). A stop or
        a read-again under way keeps its arc turning (round 8 row 45: never greyed; a window opened again before it
        answered takes the arc on its button, `qpress.adopt`) — a press meanwhile does nothing. Only what moved is
        touched (S19)."""
        why = why_not(self.shell)
        no_library = _looks(self.shell) is None
        _turn(self.look, not no_library, S.STORE_NO_LIBRARY_TIP if no_library else S.SOURCES_LOOK_TIP)
        _turn(self.add, why is None, why or S.SOURCES_ADD_TIP)
        _turn(self.skip, why is None, why or S.SOURCES_SKIP_TIP)
        acting = _acting(self.shell)
        for kind, lines, button in (("stop", self.lines, "stop"), ("read", self.skipped, "read")):
            for key, line in lines.items():
                control = getattr(line, button)
                _turn(control, why is None, why or line.tip)
                if (kind, self.lines_of, key) in acting and qpress.mark(control) is None:
                    qpress.adopt(control, _press_key((kind, self.lines_of, key)), win=self.shell)
        for line in self.lines.values():                  # alpha 4 P-removed: *Bring back N removed*, greyed with why
            _turn(line.back, why is None, why or line.back_tip)

    def look_again(self):
        """*Look again*: every folder looked at in full — the Refresh key's press, on this button (round 8 row 45, P3's
        rule: its arc from the press until the look's summary, or a look that couldn't run, said in the bar). A press
        meanwhile does nothing. -> True when one was asked."""
        return look_again(self.shell, control=self.look)

    def _tab_order(self):
        """Tab as the window reads: the folders' *Stop reading*, the skipped folders' *Read again*, *Skip a folder…*, its
        line's *Undo* (while it shows), *Look again*, *Add a folder…* (lines made later would otherwise join the chain's end)."""
        def shown(layout):
            return [layout.itemAt(i).widget() for i in range(layout.count())]
        chain = [b for w in shown(self.box.layout()) if isinstance(w, SourceLine) for b in (w.back, w.stop)]
        chain += [w.read for w in shown(self.skip_box.layout()) if isinstance(w, SkippedLine)]
        chain += [self.skip, self.skip_undo, self.removed, self.look, self.add]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

    # --- showing ---------------------------------------------------------------------------------------------- #
    def _seen(self, summary):
        if self.gone:
            return
        reset = _heard(self, summary)
        if reset is None:
            return
        if reset and self.skip_ticket is not None:
            self._skip_said(None)                         # (Q7A-3: another library's lines: its skip's line goes)
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
            line = SourceLine(source, self.stop, parent=self.box, on_back=self.bring_back)
            column.insertWidget(ids.index(source["id"]), line)
            self.lines[source["id"]] = line
            line.show()
        if added:
            self.read_removed([s["id"] for s in added])  # alpha 4 P-removed: its removed files, on the looks' worker
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
    def _press(self, key, control):
        """Round 8 row 45: a stop or a read-again pressed — the arc on its button, painted before the looks' worker is
        asked; kept on the shell's presses, so a window opened again shows it. -> False when one is under way."""
        return qpress.begin(control, _press_key(key), win=self.shell) is not None

    def _answered(self, key, failed=False):
        """A stop's or a read-again's answer landed: no longer under way; its arc off and its button as the rule says
        (the window may have closed meanwhile: the bar was told all the same)."""
        _acting(self.shell).discard(key)
        p = qpress.presses_of(self.shell).find(_press_key(key))
        if p is not None and p.live():
            qpress.end(p, self.shell, failed=failed)
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
                said = self.skip_ticket
                if not self.gone and said is not None and getattr(said.change, "folder", None) == folder_id:
                    self._skip_said(None)                 # (Q7A-4: read again: its "won't be read again" goes)
            self._answered(key)
        relay.said.connect(done)
        if not self._press(key, line.read):               # one press per click: its arc, painted before the ask
            relay.deleteLater()
            return False
        _acting(self.shell).add(key)                      # before the ask: an answer may land at once
        if not looks.read_again(folder_id, relay.call, language=self.lines_of):
            relay.deleteLater()
            self._answered(key, failed=True)
            return False
        return True

    def skip_folder(self, path=None):
        """Q7 *Skip a folder…*: the wizard's picker (`pick_dialog`, `SKIP_TITLE`) starting in the first folder being read
        (`path`: tests), then a press — its arc from the press — while the store's own rule is asked on the looks'
        worker (`SourceLooks.skip_refused`; behind a look under way, this window's line says it waits): refused,
        `FOLDER_REFUSED` in this window's line; else the window's writer skips it (`item_menu.give_skip`, ⋯'s one rule:
        one change, its toast with Undo; a refusal meanwhile is the writer's note). Lean B (2026-10-24, PROVISIONAL):
        the arc turns until the skip is saved, then this window's own line says so with the toast's one Undo
        (`show_skip`). Its skipped line and the page's count follow the change's landing (`skips_moved`). A press
        meanwhile does nothing. -> True when it was asked."""
        looks = _looks(self.shell)
        key = _press_key(("skip", self.lines_of))
        moves = getattr(self.shell, "moves", None)
        if looks is None or moves is None or why_not(self.shell) is not None or qpress.live(self.shell, key):
            return False
        if path is None:
            start = next((line.source["path"] for line in self.lines.values()), "")
            path = self.pick_dialog(W.SKIP_TITLE, start)
            if not path:
                return False
        path = os.path.normpath(path)
        language = self.lines_of
        from app.qt import bridge, item_menu
        relay = bridge.Relay(self.shell)                 # the answer heard even once the window closed
        busy = looks.busy() if hasattr(looks, "busy") else False
        p = qpress.begin(self.skip, key, win=self.shell)  # its arc, painted before the looks' worker is asked
        if p is None:
            relay.deleteLater()
            return False
        waiting = S.SOURCES_SKIP_QUEUED.format(name=os.path.basename(path) or path) if busy else None

        def ended(failed=False, words=None):
            if p.live():
                qpress.end(p, self.shell, failed=failed)
            if self.gone:
                if words:
                    windows.say_in_bar(self.shell, words)
            elif words is not None:
                self.say(words)
            elif waiting is not None and self.status.text() == waiting:
                self.say("")

        def told(ticket, event):
            win = self if not self.gone else windows.opened(self.shell, WINDOW)   # (Q7A-5: opened again meanwhile)
            if event == "saved":
                ended()
                if not ticket.undo_asked and win is not None and win.lines_of == language:
                    win.show_skip(ticket)
            elif event == "undone":                       # its toast's Undo (before it was saved: nothing shown)
                ended()
                if win is not None and win.skip_ticket is ticket:
                    win._skip_said(None)
            else:                                         # refused, or ended unsaved: the bar / toast said why
                ended(failed=True)

        def checked(why):
            relay.deleteLater()
            moves = getattr(self.shell, "moves", None)
            if why or moves is None or language != getattr(self.shell, "language", language):
                if why:
                    words = W.FOLDER_REFUSED.format(folder=path, why=why)
                else:                                     # (H2: never a press that ends with no word)
                    words = S.SOURCES_SKIP_SWITCHED if moves is not None else None
                qpress.end(p, self.shell, failed=True, why=why)
                ended(words=words)
                return
            given = refused = None
            try:
                refused = moves.refused()                 # (the bar says why; this window's line too, H5)
                if refused is None:
                    given = item_menu.give_skip(moves, path, told=told)
            finally:
                if given is None:                         # refused, or broke (H8): never a press left turning
                    ended(failed=True, words=None if self.gone else refused)
        relay.said.connect(checked)
        if waiting is not None:
            self.say(waiting)                             # behind a look under way: said, never silent
        asks = getattr(looks, "skip_refused", None)
        if asks is None:                                  # (no pre-check: the writer's own rule answers)
            checked(None)
            return True
        if not asks(path, relay.call, language=language):
            relay.deleteLater()                           # closed, or another language's: nothing asked
            ended(failed=True)
            return False
        return True

    def show_skip(self, ticket):
        """Lean B: a skip saved from this window — its toast's words in the window's own line beside *Skip a folder…*,
        with *Undo*, the toast's one Undo (`undo_skip`). The newest skip's line only."""
        if not self.gone:
            self._skip_said(ticket)

    def undo_skip(self):
        """The line's *Undo*: the same Undo as the skip's toast (`moves.undo(ticket)`: *Undoing…* in the bar until it
        lands; the toast closes with it, Q7A-6); the line goes at once. Only the library it was saved in (Q7A-3: never
        another language's writer). -> True when asked."""
        ticket, of, moves = self.skip_ticket, self.skip_language, getattr(self.shell, "moves", None)
        self._skip_said(None)
        if ticket is None or moves is None or of != getattr(self.shell, "language", None):
            return False
        toasts = getattr(self.shell, "toasts", None)
        if toasts is not None and getattr(moves, "toasted", None) is ticket:
            toasts.close()
        moves.undo(ticket)
        return True

    def skip_undone(self, change):
        """The skip `change` undone (this line's Undo, its toast's, Ctrl+Z): its line goes. Another change: nothing."""
        ticket = self.skip_ticket
        if not self.gone and ticket is not None and change is not None and ticket.change is change:
            self._skip_said(None)

    def _skip_said(self, ticket):
        """The line beside *Skip a folder…*: `ticket`'s words and *Undo*, or none (hidden). Of the library shown."""
        self.skip_ticket = ticket
        self.skip_language = self.lines_of if ticket is not None else None
        if ticket is not None:
            self.skip_said.setText(ticket.text)
        self.skip_said.setVisible(ticket is not None)
        self.skip_undo.setVisible(ticket is not None)

    def stop(self, root_id):
        """*Stop reading* (K9, alpha 4): through the window's writer, as a gone folder's card stops one (`give_stop`):
        a look reading the folder lets it go between files, then one change — its toast says the episodes stay, with
        Undo (Ctrl+Z too), which reads it again. The line goes with the folders' listing once the stop is saved
        (`drag._sources_stopped`), and comes back with its Undo; its arc turns from the press until it is saved."""
        line = self.lines.get(root_id)
        if _looks(self.shell) is None or line is None or why_not(self.shell) is not None:
            return False
        source = dict(line.source)
        key = ("stop", self.lines_of, root_id)
        n = source.get("items") or 0
        text = S.SOURCES_STOPPED_ONE.format(path=source["path"]) if n == 1 else \
            S.SOURCES_STOPPED.format(path=source["path"], n=n)

        def told(_ticket, event):                         # (the window may have closed meanwhile: `_answered` knows)
            self._answered(key, failed=event in ("refused", "ended"))
        if not self._press(key, line.stop):               # one stop per click: its arc, painted before the writer
            return False
        _acting(self.shell).add(key)                      # before the ask: an answer may land at once
        if give_stop(self.shell, root_id, text, self.lines_of, told=told) is None:
            self._answered(key, failed=True)              # refused (the bar says why) or another language's
            return False
        return True

    # --- alpha 4 P-removed: 🗑 *Removed…* and a folder's *Bring back N removed* ------------------------------------ #
    def open_removed(self):
        """🗑 *Removed…*: its window (`app/qt/removed.py`), read as it opens."""
        from app.qt import removed
        return removed.open_window(self.shell)

    def read_removed(self, roots=None):
        """Each folder's removed files (`SourceLooks.removed_under`, on the looks' worker; `roots`: these folders only,
        else every line's): its *Bring back N removed* follows. Read as its line shows and when the trash moved, never
        on a look's summary (S19). One read per folder at a time (asked meanwhile: one more after it). -> how many were
        asked."""
        looks = _looks(self.shell)
        if looks is None or not hasattr(looks, "removed_under") or self.gone:
            return 0
        asked = 0
        for root in list(self.lines) if roots is None else roots:
            if root not in self.lines:
                continue
            if root in self._removed_reading:
                self._removed_reading[root] = True        # one more after the one under way
                continue
            language = self.lines_of
            self._removed_reading[root] = False
            if looks.removed_under(root, lambda found, r=root: self._removed_relay.call((language, r, found)),
                                   language=language):
                asked += 1
            else:
                self._removed_reading.pop(root, None)
        return asked

    def _removed_landed(self, said):
        language, root, found = said
        again = self._removed_reading.pop(root, False)
        if self.gone:
            return
        if again:
            self.read_removed([root])
            return
        line = self.lines.get(root)
        if line is not None and language == self.lines_of and found is not None and line.show_removed(found):
            why = why_not(self.shell)
            _turn(line.back, why is None, why or line.back_tip)

    def _trash_heard(self, change, _label=None):
        from app.qt import removed
        if removed.trash_moved(change):
            self.read_removed()

    def bring_back(self, root_id):
        """*Bring back N removed*: the writer's `restore` of that folder's removed files (one change, its toast's one
        Undo); the button goes at once; once saved, that folder is looked at so its look sees them (the looks'
        `look_at(root)` when they offer it, else a focus's look, `asked`). -> True when given."""
        line = self.lines.get(root_id)
        if line is None or not line.removed or why_not(self.shell) is not None:
            return False
        from app.qt import removed
        ids, path = list(line.removed), line.source["path"]
        name = os.path.basename(os.path.normpath(path)) or path
        text = strings.REMOVED_BROUGHT_BACK_ONE.format(name=name) if len(ids) == 1 else \
            strings.REMOVED_BROUGHT_BACK.format(n=len(ids), name=name)
        shell, language = self.shell, self.lines_of

        def told(event):
            if event == "saved":
                looks = _looks(shell)
                if looks is not None and language == getattr(shell, "language", language):
                    look_at = getattr(looks, "look_at", None)     # (Seams: a one-folder look, when the looks offer it)
                    if look_at is not None:
                        look_at(root_id, language=language)
                    elif hasattr(looks, "asked"):
                        looks.asked(focused=True)
            elif event in ("refused", "ended") and not self.gone:
                self.read_removed([root_id])                  # (nothing written: its button as the store has it)
        line.show_removed(())                                 # the press's answer, in the frame
        if removed.give_back(shell, ids, text, told=told) is None:
            self.read_removed([root_id])
            return False
        return True


def give_stop(shell, root_id, text, language, told=None):
    """K9 / B14 (alpha 4): a folder no longer read, through the window's writer — one rule for Settings' *Stop
    reading* and a gone folder's card. The looks let it go first (`SourceLooks.let_go`: a look reading it stops
    between files, and none reads it while it is stopped), then `Writer.stop_reading`: one change, its toast (`text`)
    with Undo. Refused, or settled unsaved: the looks read it again (`let_go(on=False)`); saved or undone, the same as
    it lands, from the toast or Ctrl+Z (`drag._sources_stopped`: saved, the store's row is off — added again, it is
    read, A4B-1). `told(ticket, event)` as `item_menu.give_skip`'s. ->
    the writer's number, or None (nothing given: the folder is read as before)."""
    from app.qt import drag
    moves, looks = getattr(shell, "moves", None), _looks(shell)
    if moves is None or moves.refused() is not None:
        return None
    let_go = getattr(looks, "let_go", None)
    if let_go is not None and not let_go(root_id, language=language):
        return None                                       # the looks closing, or another language's library
    ticket = drag.Ticket(text, (), ())

    def heard(event):
        if event in ("refused", "ended") and let_go is not None:
            let_go(root_id, on=False, language=language)
        if told is not None:
            told(ticket, event)
    ticket.told = heard
    return moves._give(ticket, lambda t: moves.writer.stop_reading(root_id, t, language=language))


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
        self.button = qpress.room(sc.Door(S.FRESH_OPEN, tooltip=S.FRESH_TIP, parent=slot))
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
        """Greyed with why while it can't run; repainted only when it turned (S19). Round 8 row 45: never greyed while
        it runs — its arc turns (`ask`, `start`) and its tooltip says it is starting."""
        if not self.alive():
            return
        why = self.why_not()
        tip = why or S.FRESH_TIP
        on = why is None or (self.running and why == S.FRESH_RUNNING_TIP)
        if self.button.isEnabled() != on:
            self.button.setEnabled(on)
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
        p = qpress.begin(self.button, "settings:fresh", win=self.shell)   # round 8 row 45: the arc from the press,
        #                                                                    painted before the counts are asked

        def counted(found):
            relay.deleteLater()
            self.counting = False
            if p is not None:
                qpress.end(p, self.shell)
            if self.alive() and self.why_not() is None and self.card is None:
                self._sheet(found)
        relay.said.connect(counted)
        self.counting = True
        if not counts(relay.call):
            relay.deleteLater()
            self.counting = False
            if p is not None:
                qpress.end(p, self.shell)
            return self._sheet(None)
        return None

    def _sheet(self, counts):
        self.card = fresh_sheet(self.page, counts, self._answered)
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
        # round 8 row 45: the arc from Yes, and *Starting a fresh library…* held in the bar until the reset answers
        p = qpress.begin(self.button if self.alive() else None, "settings:fresh", busy=S.FRESH_RUNNING_TIP,
                         win=self.shell)

        def landed(answer):
            relay.deleteLater()
            if p is not None:
                qpress.end(p, self.shell, failed=not answer.get("done"))
            self.running = False
            self.enable()
            if self.shell is not None:
                windows.say_in_bar(self.shell, fresh_said(answer))
        relay.said.connect(landed)
        self.running = True                               # before the ask: an answer may land at once
        self.enable()
        if not looks.fresh(forget_known, relay.call):
            relay.deleteLater()
            if p is not None:
                qpress.end(p, self.shell, failed=True)
            self.running = False
            self.enable()
            return False
        return True


def fresh_sheet(parent, counts, on_answer):
    """*Start a fresh library?* — the one sheet (Settings' row, and *Needs you*'s card for a library mostly gone, K1):
    what goes, what comes back, what stays (`fresh_body`), *Also forget my known words* (off); Esc, Back, Enter or a
    click outside is No. `on_answer(yes)`; the card's `checked` is the box. -> the card."""
    from app.qt import confirm
    return confirm.ask(parent, S.FRESH_ASK, fresh_body(counts), S.FRESH_YES, S.FRESH_YES_TIP, default_no=True,
                       danger=True, check=S.FRESH_KNOWN, check_tip=S.FRESH_KNOWN_TIP, on_answer=on_answer)


def fresh_said(answer):
    """The bar's words for `SourceLooks.fresh`'s answer: the folders being read, or why nothing was changed."""
    if answer.get("done"):
        known = answer.get("known") or ""
        return S.FRESH_DONE_KNOWN_KEPT.format(why=known[len("kept: "):]) if known.startswith("kept: ") \
            else S.FRESH_DONE
    if answer.get("aside"):
        return S.FRESH_NOT_ALL_BACK.format(folder=answer["aside"])
    if answer.get("failed"):
        return S.FRESH_FAILED.format(reason=answer["failed"])
    reason = answer.get("refused")
    if reason == "no-library":
        reason = S.STORE_NO_LIBRARY_TIP
    elif reason == "busy" or reason in strings.READ_ONLY_REASONS or str(reason).startswith("io"):
        why = strings.STORE_BUSY_NOW if reason == "busy" else strings.store_reason(reason)
        reason = why[:1].upper() + why[1:] + "."         # P-1: the store's own words, as a sentence
    return S.FRESH_REFUSED.format(reason=reason)


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
