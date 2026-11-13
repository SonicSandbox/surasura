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

***Sort again or start over…*** (K7; Fresh library 3.0.1, the spec §3): the door to one sheet (`open_fresh`; *Needs
you*'s *Start fresh* is the other; a9.1: App's *Start over completely…* went — this one offers it). **Sort my library again** (*Sort again* · *Change folders…*): the load screen over the window, the
looks' `fresh` on their worker, the sort screen (`sort_again`), *Library sorted again · Put back* at its end.
**Start over completely** (*Start over…* → a second step): the request written, the window restarts, the start gate
moves everything aside (`start_over`). **Backups** (listed on a worker; five, then *Show all*): each *Put back…*
(this language's Sorted-again ones in the window, `put_back`; Started-over ones by a restart) and *Show in folder*;
one a kill stopped part way first, with *Put it back*. Esc, Back, *Close* or a click outside close the sheet, doing
nothing. Greyed with why while there is no library or it can't be written, and while one runs.

GUI_Design_Guidelines_Qt: the page's controls and label styles, the window's base (Esc closes it), a tooltip on every
button.
"""
import os

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

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
        folder = QFileDialog.getExistingDirectory(parent, S.SOURCES_PICK_TITLE, pick_start(shell))
    return adder.read_folder(folder) if folder else False


def pick_start(shell):
    """Kantan-B2 (AUDIT A3, finding 14; Fresh-U row 11): where *Add a folder…* opens — the folder added last of those
    being read and reachable now (the newest source: a dead share would stall the dialog), else the Videos folder, else Documents (Qt's answers: never looked at on the
    window's thread; the dialog falls back by itself when one isn't there)."""
    rows = [r for r in getattr(shell, "sources", None) or ()
            if r.get("on", True) and r.get("path") and r.get("reachable") is not False]
    if rows:
        return max(rows, key=lambda r: r.get("id") or 0)["path"]
    from PyQt6.QtCore import QStandardPaths
    for where in (QStandardPaths.StandardLocation.MoviesLocation, QStandardPaths.StandardLocation.DocumentsLocation):
        path = QStandardPaths.writableLocation(where)
        if path:
            return path
    return ""


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
        # *Nothing removed…* when empty: no read only to decide whether it shows); the icon alone, named *Removed…*
        self.removed = sc.Door(strings.REMOVED_OPEN, tooltip=strings.REMOVED_OPEN_TIP, name=strings.REMOVED_OPEN_NAME,
                               parent=self.box)
        self.removed.clicked.connect(lambda _c=False: self.open_removed())
        skip_line.addWidget(self.removed)
        self._removed_reading = {}                        # root id -> in the read under way (True: again after it)
        self._removed_job = False                         # A4B-7: one read for every line, one at a time
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
            start = next((line.source["path"] for line in self.lines.values()), "") or windows.content_folder()
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

        heard = []

        def told(_ticket, event):                         # (the window may have closed meanwhile: `_answered` knows)
            if event in ("saved", "refused", "ended") and not heard:     # once (A4B-14): never again on its Undo
                heard.append(event)
                self._answered(key, failed=event != "saved")
        if not self._press(key, line.stop):               # one stop per click: its arc, painted before the writer
            return False
        _acting(self.shell).add(key)                      # before the ask: an answer may land at once
        if give_stop(self.shell, root_id, text, self.lines_of, told=told) is None:
            if not heard:                                 # refused before a ticket was given (the bar says why), or
                self._answered(key, failed=True)          # another language's
            return False
        return True

    # --- alpha 4 P-removed: 🗑 *Removed…* and a folder's *Bring back N removed* ------------------------------------ #
    def open_removed(self):
        """🗑 *Removed…*: its window (`app/qt/removed.py`), read as it opens."""
        from app.qt import removed
        return removed.open_window(self.shell)

    def read_removed(self, roots=None):
        """Each folder's removed files (A4B-7: every line's in ONE read, `removed.read_store` — a pool thread, never
        queued behind a look; `roots`: these folders only, else every line's): its *Bring back N removed* follows.
        Read as its line shows and when the trash moved (`trash_heard`), never on a look's summary (S19). One read at a
        time (asked meanwhile: one more after it). -> how many folders were asked."""
        if self.gone:
            return 0
        want = [r for r in (list(self.lines) if roots is None else roots) if r in self.lines]
        if not want:
            return 0
        if self._removed_job:
            for root in want:
                self._removed_reading[root] = True        # one more after the one under way
            return 0
        from app.qt import removed
        language = self.lines_of
        for root in want:
            self._removed_reading[root] = False
        self._removed_job = True
        if not removed.read_store(self.shell, language, lambda store: removed.removed_by_root(store, want),
                                  lambda found: self._removed_landed((language, found))):
            self._removed_job = False
            for root in want:
                self._removed_reading.pop(root, None)
            return 0
        return len(want)

    def _removed_landed(self, said):
        language, found = said
        self._removed_job = False
        reading, self._removed_reading = self._removed_reading, {}
        if self.gone:
            return
        again = [r for r, more in reading.items() if more]
        if language == self.lines_of and isinstance(found, dict):
            why = why_not(self.shell)
            for root, ids in found.items():
                line = self.lines.get(root)
                if line is not None and root not in again and ids is not None and line.show_removed(ids):
                    _turn(line.back, why is None, why or line.back_tip)
        if again:
            self.read_removed(again)

    def trash_heard(self):
        """A4B-6: the window's controller saved or undid a change that moved the trash (`removed.trash_heard`)."""
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
    """*Sort again or start over…* (K7; Fresh library 3.0.1): `button` opens the one sheet (`open_fresh`), Sort again
    first. `card` while the sheet is open; `running` while a Sort again or a Put back it began is under way (the
    window's `fresh_running`)."""

    first = "sort"
    row_id = FRESH_ID

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.card = None
        slot = page.custom_row(self.row_id)
        self.button = qpress.room(sc.Door(self._label(), tooltip=self._tip(), parent=slot))
        self.button.clicked.connect(lambda _c=False: self.ask())
        slot.layout().addWidget(self.button)
        seen = getattr(self.shell, "sources_seen", None)
        if seen is not None:
            seen.connect(self._seen)
        self.enable()

    def _label(self):
        return S.FRESH_OPEN

    def _tip(self):
        return S.FRESH_TIP

    @property
    def running(self):
        return running(self.shell)

    def alive(self):
        return _alive(self.page)

    def _looks(self):
        return _looks(self.shell)

    def why_not(self):
        """Why the sheet can't open now (the button's tooltip), or None. It opens without a library, or one that can't
        be written, too: the sheet greys Sort again with why, and Start over stays (a9.1: the one door to it)."""
        if self.running:
            return S.FRESH_RUNNING_TIP
        return None

    def enable(self):
        """Greyed with why while it can't open; repainted only when it turned (S19)."""
        if not self.alive():
            return
        why = self.why_not()
        _turn(self.button, why is None, why or self._tip())

    def _seen(self, _summary):
        self.enable()

    def ask(self):
        """The sheet, open at once (its counts and its backups read on workers as it shows). -> the sheet, or None."""
        self.enable()
        if self.card is not None and (sip.isdeleted(self.card) or self.card.answer is not None):
            self.card = None                              # dropped (its window hidden): no callback comes (H13)
        if self.why_not() is not None or self.card is not None or self.shell is None:
            return None
        self.card = open_fresh(self.shell, self.page, first=self.first, done=self._closed)
        return self.card

    def _closed(self):
        self.card = None
        self.enable()


# --- the one sheet (the spec §3.1: two choices, the Backups list; three doors) ----------------------------------- #
SHOWN_BACKUPS = 5                                   # the newest five, then *Show all* (P15)
RUNNING = "_fresh_running"                          # on the window: a Sort again or a Put back under way (its words)
KEPT = "_fresh_kept"                                # on the window: the sheet's card kept built since its close
_SIZES = {}                                         # (folder, its time) -> bytes: a backup's size, worked out once


def running(shell):
    """The words of a Sort again or a Put back under way in `shell`, or None."""
    return shell.__dict__.get(RUNNING) if shell is not None else None


def _set_running(shell, words):
    if shell is None:
        return
    if words:
        shell.__dict__[RUNNING] = words
    else:
        shell.__dict__.pop(RUNNING, None)


def _when(stamp):
    """A record's time (`2026-10-30T15:40:12`, as the stores write it) in the sheet's words: *30 Oct 2026, 15:40*."""
    import datetime
    text = str(stamp or "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d-%H%M%S"):
        try:
            return datetime.datetime.strptime(text[:19] if "T" in text or "-" in text[:5] else text, fmt).strftime(
                "%d %b %Y, %H:%M").lstrip("0")
        except ValueError:
            continue
    return text[:16] or "?"


def _size_words(n):
    if n is None:
        return S.FRESH_SIZE_WAIT
    mb = n / (1024 * 1024)
    return S.FRESH_SIZE_MB.format(mb=max(1, round(mb))) if mb < 1024 else S.FRESH_SIZE_GB.format(gb=mb / 1024)


def backup_line(entry, size=None):
    """One backup's line: *Sorted again · 30 Oct 2026, 15:40 · 182 MB* (*· stopped part way* first in its words)."""
    parts = [S.FRESH_KINDS.get(entry.get("kind"), entry.get("kind") or ""), _when(entry.get("date")), _size_words(size)]
    if entry.get("stopped"):
        parts.append(S.FRESH_STOPPED)
    return " · ".join(parts)


def list_backups(language):
    """(A worker.) The backups this window can put back: every Started-over one, and this language's Sorted-again ones
    (`profile_reset.backups`) -> the list, or None when it couldn't be read."""
    try:
        from app import profile_reset
        return [b for b in profile_reset.backups() if b.get("scope") == "profile" or b.get("language") == language]
    except Exception as e:
        print(f"Fresh library: the backups couldn't be listed: {e!r}")
        return None


def backup_sizes(entries):
    """(A worker.) {folder: bytes} for `entries` (`profile_reset.backup_size`), each worked out once per folder time."""
    from app import profile_reset
    out = {}
    for entry in entries:
        folder = entry["folder"]
        try:
            key = (folder, os.stat(folder).st_mtime_ns)
        except OSError:
            key = (folder, None)
        if key not in _SIZES:
            _SIZES[key] = profile_reset.backup_size(entry)
        out[folder] = _SIZES[key]
    return out


class FreshSheet(QObject):
    """The sheet's own parts inside the window's one confirmation card (`confirm.ask`, its title *Sort again or start
    over*, its one button *Close*): **Sort my library again** (*Sort again*, *Change folders…*), **Start over
    completely** (*Start over…*) — `first` on top — and **Backups** (hidden while there are none; *Looking for
    backups…* until the worker's list lands; five, then *Show all*; each *Put back…* / *Put it back* and *Show in
    folder*). A press sets `choice` (("sort",), ("folders",), ("over",), ("put-back", entry)) and closes the card
    with Yes; `on_choice(choice)` follows. Nothing here runs anything. Kept built with its card (`open_fresh`):
    `renew` makes it a new sheet again for the next opening."""

    def __init__(self, card, first="sort", why=None, connect_on=False, on_choice=None, busy=None):
        super().__init__(card)
        self.card, self.first, self.choice, self._on_choice = card, first, None, on_choice
        self.busy = busy                              # a Sort again / Put back / Generate under way: nothing acts
        self.backups = None                           # the worker's list (None: still looking)
        self.sizes = {}
        self.all_shown = False
        self.row_widgets = []
        self.row_words = []                           # [(entry, its words label)] of the rows listed
        self.on_show_all = None                       # (the sheet's opener: the sizes of the rest, on a worker)
        self._rows_key = None
        self.relay = None                             # (the opening's: its workers' answers, dropped with it)
        self.opening = 0                              # each opening's number: an earlier one's answer never lands
        f = theme.text_factor(style.current()[1])
        box = card.layout()
        at = box.count() - 1                          # (above the card's own button row)
        self.sort_part, sort_box = self._part(S.FRESH_SORT_HEAD, S.FRESH_SORT_BODY)
        self.counts_line = self._line(sort_box, "")
        self.cards_line = self._line(sort_box, S.FRESH_SORT_CARDS if connect_on else "")
        row = QHBoxLayout()
        row.setSpacing(round(10 * f))
        self.btn_sort = self._button(S.FRESH_SORT, why or S.FRESH_SORT_TIP, ("sort",), row, "primary")
        self.btn_folders = self._button(S.FRESH_FOLDERS, why or S.FRESH_FOLDERS_TIP, ("folders",), row, link=True)
        row.addStretch(1)
        sort_box.addLayout(row)
        for b in (self.btn_sort, self.btn_folders):
            b.setEnabled(why is None)
        self.over_part, over_box = self._part(S.FRESH_OVER_HEAD, S.FRESH_OVER_BODY)
        self.suspended_line = self._line(over_box, "")
        row = QHBoxLayout()
        self.btn_over = self._button(S.FRESH_OVER, busy or S.FRESH_OVER_TIP, ("over",), row, "danger")
        self.btn_over.setEnabled(busy is None)
        row.addStretch(1)
        over_box.addLayout(row)
        parts = (self.over_part, self.sort_part) if first == "over" else (self.sort_part, self.over_part)
        self.backups_part, backups_box = self._part(S.FRESH_BACKUPS, None)
        self.looking = self._line(backups_box, S.FRESH_LOOKING)
        self.scroll = QScrollArea(self.card)          # *Show all*: the list scrolls, the card never grows past it
        self.scroll.setObjectName("foldersscroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(self.scroll)
        body.setObjectName("foldersbody")
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(round(6 * f))
        self.scroll.setWidget(body)
        self.scroll.setVisible(False)
        backups_box.addWidget(self.scroll)
        row = QHBoxLayout()
        self.btn_all = self._button("", S.FRESH_SHOW_ALL_TIP, None, row, link=True)
        self.btn_all.clicked.connect(lambda _c=False: self.show_all())
        self.btn_all.setVisible(False)
        row.addStretch(1)
        backups_box.addLayout(row)
        for i, part in enumerate(parts + (self.backups_part,)):
            box.insertWidget(at + i, part)

    def renew(self, why=None, connect_on=False, busy=None):
        """(Kept, hidden.) As a new sheet opens: nothing chosen, its counts and its Backups not read yet (*Looking for
        backups…*), the greying of now."""
        self.choice, self.busy = None, busy
        self.backups, self.sizes, self.all_shown, self._rows_key = None, {}, False, None
        for w in self.row_widgets:
            self.rows.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.row_widgets, self.row_words = [], []
        _say(self.counts_line, "")
        _say(self.suspended_line, "")
        _say(self.cards_line, S.FRESH_SORT_CARDS if connect_on else "")
        for b, tip in ((self.btn_sort, S.FRESH_SORT_TIP), (self.btn_folders, S.FRESH_FOLDERS_TIP)):
            b.setToolTip(why or tip)
            b.setEnabled(why is None)
        self.btn_over.setToolTip(busy or S.FRESH_OVER_TIP)
        self.btn_over.setEnabled(busy is None)
        self.looking.setVisible(True)
        self.scroll.setVisible(False)
        self.btn_all.setVisible(False)
        self.backups_part.setVisible(True)

    # --- building ------------------------------------------------------------------------------------------------ #
    def _part(self, head, body):
        part = QWidget(self.card)
        lay = QVBoxLayout(part)
        lay.setContentsMargins(0, round(6 * _f()), 0, 0)
        lay.setSpacing(round(6 * _f()))
        title = QLabel(head, part)
        title.setObjectName("confirmhead")
        title.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(title)
        if body:
            self._line(lay, body)
        return part, lay

    def _line(self, layout, text):
        label = QLabel(text, self.card)
        label.setObjectName("confirmline")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setVisible(bool(text))
        layout.addWidget(label)
        return label

    def _button(self, text, tip, choice, row, kind=None, link=False):
        b = QPushButton(text, self.card)
        b.setToolTip(tip)
        b.setAccessibleName(text)
        b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        b.setAutoDefault(False)
        if link:
            b.setObjectName("windowlink")
        if kind:
            b.setProperty("kind", kind)
        if choice is not None:
            b.clicked.connect(lambda _c=False, c=choice: self.choose(c))
        row.addWidget(b)
        return b

    def buttons(self):
        """Every button of the sheet's own, in reading order (Tab's ring, with the card's *Close*)."""
        parts = (self.over_part, self.sort_part) if self.first == "over" else (self.sort_part, self.over_part)
        order = {self.sort_part: [self.btn_sort, self.btn_folders], self.over_part: [self.btn_over]}
        out = [b for p in parts for b in order[p]]
        for w in self.row_widgets:
            out += [b for b in w.findChildren(QPushButton) if b.isVisible()]
        if self.btn_all.isVisible():
            out.append(self.btn_all)
        return [b for b in out if b.isEnabled()]

    # --- what it shows ------------------------------------------------------------------------------------------- #
    def set_counts(self, counts):
        """The store's counts (`fresh_counts`): what never comes back on the Sort again side, the cards left
        suspended on the Start over side (a count of 0 says nothing)."""
        counts = counts or {}
        plural = lambda n: "" if n == 1 else "s"                                          # noqa: E731
        parts = [words.format(n=counts[key], s=plural(counts[key])) for key, words in (
            ("added", S.FRESH_GONE_ADDED), ("youtube", S.FRESH_GONE_YOUTUBE), ("other", S.FRESH_GONE_OTHER))
            if counts.get(key)]
        _say(self.counts_line, S.FRESH_GONE.format(parts=", ".join(parts)) if parts else "")
        n = counts.get("suspended") or 0
        _say(self.suspended_line, S.FRESH_SUSPENDED_OVER.format(n=n, s=plural(n)) if n else "")
        self.card.place()

    def set_backups(self, backups):
        """The worker's list (None: it couldn't be read: the part goes)."""
        self.backups = list(backups or ())
        self._paint_rows()

    def set_sizes(self, sizes):
        """Sizes from the worker: each listed row's words repainted in place (its buttons keep the keyboard)."""
        self.sizes.update(sizes or {})
        for entry, words in self.row_words:
            text = backup_line(entry, self.sizes.get(entry["folder"]))
            if words.text() != text:
                words.setText(text)

    def show_all(self):
        self.all_shown = True
        self._paint_rows()
        if self.on_show_all is not None:
            self.on_show_all([b for b in self.shown() if b["folder"] not in self.sizes])
        return self.shown()

    def shown(self):
        """The backups listed now (five, or all after *Show all*)."""
        rows = self.backups or []
        return rows if self.all_shown else rows[:SHOWN_BACKUPS]

    def _paint_rows(self):
        rows = self.shown()
        key = tuple((b["folder"], b.get("stopped")) for b in rows) + (len(self.backups or ()), self.all_shown)
        if key == self._rows_key:
            return                                    # nothing it shows changed (S19)
        self._rows_key = key
        self.looking.setVisible(False)
        for w in self.row_widgets:
            self.rows.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.row_words = []
        self.row_widgets = [self._row(b) for b in rows]
        for w in self.row_widgets:
            self.rows.addWidget(w)
        self.scroll.setVisible(bool(rows))
        more = len(self.backups or ()) - len(rows)
        self.btn_all.setText(S.FRESH_SHOW_ALL.format(n=len(self.backups or ())))
        self.btn_all.setAccessibleName(self.btn_all.text())
        self.btn_all.setVisible(more > 0)
        self.backups_part.setVisible(bool(self.backups))
        self.card.place()

    def fit(self):
        """(After the card's own placing.) The card measured at its real width: each part's wrapped lines in full,
        the Backups list five rows at most and never more than the window leaves (the rest scroll), the card centred
        at that height."""
        from app.qt import confirm
        card, lay = self.card, self.card.layout()
        lay.activate()
        room = card._window.height() - 2 * confirm.MARGIN
        parts = [p for p in (self.sort_part, self.over_part) if not p.isHidden()]     # (before it shows, too)
        need = sum(p.heightForWidth(p.width()) if p.hasHeightForWidth() else p.sizeHint().height() for p in parts)
        listed = not self.scroll.isHidden() and self.row_widgets
        rows_h = self.scroll.height() if listed else 0
        other = card.height() - sum(p.height() for p in parts) - rows_h
        if listed:                                    # each row at its narrowest, its scrollbar beside it (shown or
            #                                           not yet: measured as it will be, never as it is just now)
            width = self.scroll.contentsRect().width() - self.scroll.verticalScrollBar().sizeHint().width()
            one = max(w.heightForWidth(width) if w.hasHeightForWidth() else w.sizeHint().height()
                      for w in self.row_widgets) + self.rows.spacing()
            rows_h = max(one, min(min(len(self.row_widgets), SHOWN_BACKUPS) * one, room - other - need))
            self.scroll.setFixedHeight(rows_h)
        h = min(room, other + need + rows_h)
        g = card.geometry()
        card.setGeometry(g.x(), max(0, (card._window.height() - h) // 2), g.width(), h)

    def _row(self, entry):
        w = QWidget(self.rows.parentWidget())
        line = QHBoxLayout(w)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(10 * _f()))
        words = QLabel(backup_line(entry, self.sizes.get(entry["folder"])), w)
        words.setObjectName("confirmline")
        words.setTextFormat(Qt.TextFormat.PlainText)
        words.setWordWrap(True)                       # (its buttons always in the card, however long the line)
        line.addWidget(words, 1)
        self.row_words.append((entry, words))
        if entry.get("scope") == "profile" and entry.get("stopped"):
            words.setToolTip(S.FRESH_OVER_STOPPED_TIP)   # F8: never a restart that is sure to be refused: by hand
        else:
            label, tip = (S.FRESH_PUT_IT_BACK, S.FRESH_PUT_IT_BACK_TIP) if entry.get("stopped") else \
                (S.FRESH_PUT_BACK, S.FRESH_PUT_BACK_TIP)
            b = self._button(label, self.busy or tip, ("put-back", entry), line)
            b.setEnabled(self.busy is None)
        show = self._button(S.FRESH_SHOW, S.FRESH_SHOW_TIP, None, line, link=True)
        show.clicked.connect(lambda _c=False, e=entry: show_backup(e))
        return w

    # --- a press ------------------------------------------------------------------------------------------------- #
    def choose(self, choice):
        if self.choice is not None or self.card.answer is not None:
            return
        self.choice = choice
        self.card._answer(True)


def _say(label, text):
    if label.text() != text:
        label.setText(text)
    if label.isHidden() == bool(text):
        label.setVisible(bool(text))


def show_backup(entry):
    """*Show in folder*: the backup's folder (a Started-over one: the library folder's part, whose record names every
    part) in the system's file window."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    folder = entry.get("folder")
    if folder and os.path.isdir(folder):
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def _connect_on(shell):
    try:
        return bool(shell.services.settings.get().get("connect_enabled", True))
    except Exception:
        return False


def open_fresh(shell, parent, first="sort", done=None):
    """The one sheet over `parent`'s window, at once (≤ 5 ms on the window's thread: its counts and its Backups list
    read on workers as it shows; built once a window — kept at its close, `_kept` — and made a new sheet again at each
    opening, `FreshSheet.renew`). Esc, Back, *Close* or a click outside close it, doing nothing; a press acts
    (`act`). `done()` once it closed, either way. -> the card."""
    from app.qt import bridge, confirm
    looks = _looks(shell)
    busy = running(shell) or _busy_now(shell)
    why = busy or (S.STORE_NO_LIBRARY_TIP if looks is None else cant_write(getattr(shell, "services", None)))
    holder = {}

    def answered(_yes):
        sheet = holder.get("sheet")
        choice = sheet.choice if sheet is not None else None
        if done is not None:
            done()
        if choice is not None:
            act(shell, choice, parent=parent)

    def build(card):                                  # its parts made before the card shows: one show, one polish
        sheet = holder["sheet"] = FreshSheet(card, first=first, why=why, connect_on=_connect_on(shell), busy=busy)
        card.sheet = sheet
        card.ring = sheet.buttons                     # Tab goes round its buttons too (`confirm.Confirm`)
        card.keep, card.made_in = True, style.current()   # (kept at its close: the next opening shows it again)
        place = card.place

        def fitted():                                 # the card's own placing, then measured again at its width
            for w in sheet.row_widgets:               # (in their own fonts: the stylesheet's, before they show — the
                w.ensurePolished()                    # ... card polishes the rest at its first place; rows come later)
            card.layout().invalidate()
            place()
            card.layout().setGeometry(card.rect())    # (laid out at its placed size: hidden, no resize comes to do it)
            sheet.fit()
        card.place = fitted
    card = _kept(shell, parent, first)
    if card is not None:                              # built once: made a new sheet again, opened as a new one
        sheet = holder["sheet"] = card.sheet
        sheet.renew(why=why, connect_on=_connect_on(shell), busy=busy)
        card.again(answered)
    else:
        card = confirm.ask(parent, S.FRESH_SHEET, "", None, None, no=S.FRESH_CLOSE, no_tip=S.FRESH_CLOSE_TIP,
                           on_answer=answered, build=build)
        sheet = holder["sheet"]
        if shell is not None:
            shell.__dict__[KEPT] = card
    if sheet.relay is not None and not sip.isdeleted(sheet.relay):
        sheet.relay.deleteLater()                     # (an earlier opening's answers dropped: never in this one)
    relay = sheet.relay = bridge.Relay(card)
    sheet.opening += 1
    opening = sheet.opening
    relay.said.connect(lambda said: opening == sheet.opening and _heard_sheet(sheet, said))
    language = getattr(shell, "language", None)
    counts = getattr(looks, "fresh_counts", None)
    if counts is not None and not counts(lambda c: relay.call(("counts", c))):
        pass                                          # (closed: no counts, the lines that always hold)

    def listed(backups):
        relay.call(("backups", backups))
        if backups:
            relay.call(("sizes", backup_sizes(backups[:SHOWN_BACKUPS])))
    bridge.run_in_worker(lambda: listed(list_backups(language)),
                         failed=lambda info: relay.call(("backups", None)))
    sheet.on_show_all = lambda rest: rest and bridge.run_in_worker(
        lambda: relay.call(("sizes", backup_sizes(rest))), failed=lambda info: None)
    return card


def _kept(shell, parent, first):
    """The sheet's card kept since its close, for an opening over `parent`'s window with `first` on top — or None
    (none kept, open now, let go with its window, another window, `first` or look: then let go here)."""
    card = shell.__dict__.get(KEPT) if shell is not None else None
    if card is None:
        return None
    if (not sip.isdeleted(card) and card.keep and card.answer is not None and card._window is parent.window()
            and card.made_in == style.current() and card.sheet.first == first):
        return card
    shell.__dict__.pop(KEPT, None)
    if not sip.isdeleted(card):
        if card.answer is None:
            card.keep = False                         # (open now: let go at its answer, as any card)
        else:
            card.scrim.deleteLater()
            card.deleteLater()
    return None


def _busy_now(shell):
    """Why nothing on the sheet may act now (§3.1's greying, the press rule): a Generate under way, or an update
    staged (it swaps files at the next start) -> the words, or None. Connect's run is the store's own refusal."""
    try:
        if callable(getattr(shell, "generating", None)) and shell.generating():
            return S.FRESH_GENERATING
        from app import library_store
        if library_store.update_staged():
            return S.FRESH_UPDATING
    except Exception:
        return None
    return None


def _heard_sheet(sheet, said):
    if sip.isdeleted(sheet) or sip.isdeleted(sheet.card) or sheet.card.answer is not None:
        return
    what, value = said
    if what == "counts":
        sheet.set_counts(value)
    elif what == "backups":
        sheet.set_backups(value)
    else:
        sheet.set_sizes(value)


# --- what a press does (the spec §3.2–3.4, §6) -------------------------------------------------------------------- #
def act(shell, choice, parent=None):
    """The sheet's press, on the window's thread (the work on workers): *Sort again* → `sort_again`; *Change
    folders…* → the wizard's folders page alone, its *Next* → `sort_again(changes)`, its *Back* → the sheet again;
    *Start over…* → the second step, then `start_over`; *Put back…* → its confirm, then `put_back`."""
    from app.qt import confirm
    kind = choice[0]
    window = (parent or shell).window()
    if kind == "sort":
        return sort_again(shell)
    if kind == "folders":
        from app.qt import first_run
        wiz = first_run.open_again(shell, resort=lambda changes: sort_again(shell, changes))
        if wiz is None:
            windows.say_in_bar(shell, S.FRESH_FOLDERS_BUSY)
            return None
        wiz.finished.connect(lambda how: how == "later" and open_fresh(shell, parent or shell, first="sort"))
        return wiz
    if kind == "over":
        if shell.generating():
            windows.say_in_bar(shell, S.FRESH_OVER_GENERATING)
            return None
        return confirm.ask(window, S.FRESH_OVER_ASK, S.FRESH_OVER_ASK_BODY, S.FRESH_OVER_YES, S.FRESH_OVER_YES_TIP,
                           default_no=True, danger=True, no=S.FRESH_BACK, no_tip=S.FRESH_BACK_TIP,
                           on_answer=lambda yes: yes and start_over(shell))
    entry = choice[1]
    date = _when(entry.get("date"))
    if entry.get("scope") == "profile":
        title, body = S.FRESH_PB_OVER_ASK.format(date=date), S.FRESH_PB_OVER_BODY.format(date=date)
    elif entry.get("status") == "files-back":       # a Put back a kill stopped after its one write: finished
        title, body = S.FRESH_PB_STOPPED_ASK, S.FRESH_PB_FINISH_BODY.format(date=date)
    elif entry.get("stopped"):
        title, body = S.FRESH_PB_STOPPED_ASK, S.FRESH_PB_STOPPED_BODY.format(date=date)
    else:
        title, body = S.FRESH_PB_ASK.format(date=date), S.FRESH_PB_BODY.format(date=date)
        if entry.get("forgot_known"):                 # P9: a 3.0 backup made with *Also forget my known words*
            body += "\n\n" + S.FRESH_PB_KNOWN
    return confirm.ask(window, title, body, S.FRESH_PB_YES, S.FRESH_PB_YES_TIP, default_no=True,
                       no=S.FRESH_BACK, no_tip=S.FRESH_BACK_TIP,
                       on_answer=lambda yes: yes and put_back(shell, entry))


def sort_again(shell, folders=None):
    """*Sort my library again* (the spec §3.2, §6.1): the load screen over the window from the press (pending), the
    looks' `fresh` on their worker — the reset, *Change folders…*'s changes, every folder read again for sorting,
    its count on the screen (*Stop* ends the read between files and goes to the sorting) — then the load's other
    steps and the sort screen (`door="resort"`). Its *Done*: Current, and *Library sorted again · Put back*. Refused
    or failed: the cover goes and the bar says why (nothing changed). -> the `LoadRun`, or None."""
    import threading
    from app.qt import bridge, sort_screen
    looks = _looks(shell)
    if looks is None or running(shell):
        windows.say_in_bar(shell, running(shell) or S.STORE_NO_LIBRARY_TIP)
        return None
    stop = threading.Event()
    cover = sort_screen.cover_window(shell)
    held = {"backup": None}

    def ended():
        _set_running(shell, None)
        run.end()
        run.deleteLater()

    def after(_how):
        ended()
        _to_current(shell)
        _sorted_toast(shell, held["backup"], S.FRESH_SORTED)

    def empty():
        stopped = bool(run.state and run.state.get("stopped"))
        ended()
        _to_current(shell)
        if stopped:                                   # stopped before a title came in: the folders' next look now
            asked = getattr(looks, "asked", None)
            if asked is not None:
                asked(refreshed=True)
        _sorted_toast(shell, held["backup"], S.FRESH_SORTED_STOPPED if stopped else S.FRESH_SORTED_NOTHING)
    run = sort_screen.LoadRun(shell, cover, door="resort", stop_scan=stop.set, after=after, empty=empty,
                              parent=shell)
    screen = run.begin()
    screen.btn_stop.setEnabled(False)                 # F5: Stop once the order is aside (the reset never half-stops)
    run.task(S.FRESH_SETTING_ASIDE)
    _set_running(shell, S.FRESH_RUNNING_TIP)
    relay = bridge.Relay(run)

    def heard(said):
        what, value = said
        if run.ended:
            return
        if what == "answer":
            if value.get("done"):
                held["backup"] = value.get("backup")
                if not sip.isdeleted(screen):
                    screen.btn_stop.setEnabled(True)
                run.said((0, 0))
                refused = [why for _what, why in ((value.get("folders") or {}).get("refused") or ())]
                if refused:
                    windows.say_in_bar(shell, S.FRESH_FOLDERS_REFUSED.format(why=refused[0]))
            else:
                ended()
                windows.say_in_bar(shell, fresh_said(value))
        elif what == "said":
            run.said(value)
        else:
            run.scanned(value.get("ids"))
    relay.said.connect(heard)
    if not looks.fresh(lambda a: relay.call(("answer", a)), folders=folders,
                       progress=lambda found, shows: relay.call(("said", (found, shows))), stop=stop.is_set,
                       scanned=lambda found: relay.call(("scanned", found))):
        ended()
        return None
    return run


def _to_current(shell):
    try:
        shell.show_tab("current")
    except (AttributeError, RuntimeError):
        pass


def _sorted_toast(shell, backup, words):
    toasts = getattr(shell, "toasts", None)
    if toasts is None:
        windows.say_in_bar(shell, words)
        return
    buttons = []
    if backup:
        buttons = [(S.FRESH_TOAST_PUT_BACK, S.FRESH_TOAST_PUT_BACK_TIP,
                    lambda: put_back(shell, {"folder": backup, "scope": "library", "kind": "sorted-again"}))]
    toasts.show(words, buttons=buttons)


def put_back(shell, entry):
    """*Put back*: a Sorted-again backup (this language's) on the looks' worker (`SourceLooks.put_back`: the library
    from then in one write; the library now into a backup of its own), its running line in the bar until it answers,
    then *Your library from <date> is back · Undo* (Undo puts back the backup just made); a Started-over one by a
    restart (`start_over(..., backup=)`). -> True when it was asked."""
    if entry.get("scope") == "profile":
        return start_over(shell, backup=entry.get("stamp"))
    from app.qt import bridge
    looks = _looks(shell)
    if looks is None or running(shell):
        windows.say_in_bar(shell, running(shell) or S.STORE_NO_LIBRARY_TIP)
        return False
    p = qpress.begin(None, "settings:put-back", busy=S.FRESH_PB_RUNNING, win=shell)
    _set_running(shell, S.FRESH_PB_RUNNING)
    relay = bridge.Relay(shell)
    date = _when(entry.get("date"))

    def landed(answer):
        relay.deleteLater()
        _set_running(shell, None)
        if p is not None:
            qpress.end(p, shell, failed=not answer.get("done"))
        if not answer.get("done"):
            windows.say_in_bar(shell, put_back_said(answer))
            return
        _to_current(shell)
        toasts = getattr(shell, "toasts", None)
        made = answer.get("backup")
        words = S.FRESH_PB_DONE.format(date=date) if entry.get("date") else S.FRESH_PB_DONE_PLAIN
        if toasts is None:
            windows.say_in_bar(shell, words)
            return
        toasts.show(words, undo=(lambda: put_back(shell, {"folder": made, "scope": "library",
                                                           "kind": "put-back-over"})) if made else None)
    relay.said.connect(landed)
    if not looks.put_back(entry["folder"], relay.call):
        relay.deleteLater()
        _set_running(shell, None)
        if p is not None:
            qpress.end(p, shell, failed=True)
        return False
    return True


def put_back_said(answer):
    """The bar's words for a Put back that didn't happen."""
    if answer.get("aside"):
        return S.FRESH_NOT_ALL_BACK.format(folder=answer["aside"])
    if answer.get("failed"):
        return S.FRESH_PB_FAILED.format(reason=answer["failed"])
    return S.FRESH_PB_REFUSED.format(reason=_reason_words(answer.get("refused")))


def start_over(shell, backup=None):
    """*Start over* (or *Put back* a Started-over backup, `backup` its stamp): the request written (`profile_reset.
    request`, on the window's thread: one small file), then the window closes the quit's way and starts again; the
    move runs at that start, before anything opens (the start gate). Refused (an update staged, a move in flight, the
    request unwritable) or the program can't be started again: said, nothing changed, the window stays. -> True when
    the restart was asked."""
    from app import profile_reset
    from app.qt import shell as shell_module
    if running(shell):
        windows.say_in_bar(shell, running(shell))
        return False
    why = shell_module.relaunch_refused()
    if why:
        windows.say_in_bar(shell, S.FRESH_RESTART_FAILED.format(why=why))
        return False
    try:
        profile_reset.request(profile_reset.PUT_BACK if backup else profile_reset.START_OVER, backup)
    except profile_reset.MoveRefused as e:
        windows.say_in_bar(shell, e.words)
        return False
    except (OSError, ValueError) as e:
        windows.say_in_bar(shell, profile_reset.REFUSED_JOURNAL.format(why=e))
        return False
    shell.restart(move=True)
    return True


def _reason_words(reason):
    if reason == "no-library":
        return S.STORE_NO_LIBRARY_TIP
    if reason == "busy" or reason in strings.READ_ONLY_REASONS or str(reason).startswith("io"):
        why = strings.STORE_BUSY_NOW if reason == "busy" else strings.store_reason(reason)
        return why[:1].upper() + why[1:] + "."       # P-1: the store's own words, as a sentence
    return str(reason or "")


def fresh_said(answer):
    """The bar's words for `SourceLooks.fresh`'s answer when it didn't sort again: why nothing was changed."""
    if answer.get("done"):
        return S.FRESH_DONE
    if answer.get("aside"):
        return S.FRESH_NOT_ALL_BACK.format(folder=answer["aside"])
    if answer.get("failed"):
        return S.FRESH_FAILED.format(reason=answer["failed"])
    return S.FRESH_REFUSED.format(reason=_reason_words(answer.get("refused")))
