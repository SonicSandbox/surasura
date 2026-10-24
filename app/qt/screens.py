"""The first screens (W2.2; the window's spec 05 §5.1–5.2, 02 §2.4, 06 E1–E4, E14–E16): Current (the hero, the rows,
the lines, the Goal strip), Finished and Needs you — display only; moves arrive in W3.1, the Goal sheet, Needs you's
actions and covers in W3.2.

Each page is a heading, a thin state bar (*Getting your library ready…*, *Read-only: …*, *Updating your library…*) and
one painted list (`rows.RowsView`); Current adds the Goal strip under its list. A page takes the reader's `View`
(`app/services/view_rows.py`, built off the GUI thread by `app/services/library_reader.py`) and turns it into the list's
entries — nothing is worked out here. ▶ asks for a file: the page looks for it on a worker (`bridge.run_in_worker`)
and hands it to the system's player, or says in the bar why it can't.
"""
import os
import sys

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget   # W3.2 Q4

from app import theme
from app.qt import bridge, rows, strings
from app.qt import standing as standing_qt                # round 8 row 54: the read-only line's ✕
from app.services import play
from app.services import standing

def state_line(view):
    """The page's state bar for a view, or "" (02 §2.4): getting ready, read-only with its reason, busy."""
    if view is None:
        return ""
    if view.state == "getting-ready":
        if view.reason == "migration failed":           # never "getting ready" forever (G1.2-18: why, what to do)
            return strings.STATE_LINES["migration-failed"]
        return strings.STATE_LINES["getting-ready"]
    if view.state == "read-only":
        reason = view.reason or ""
        plain = strings.READ_ONLY_REASONS.get(reason) or (strings.READ_ONLY_IO if reason.startswith("io") else reason)
        return strings.STATE_LINES["read-only"].format(reason=plain)
    if view.busy:
        return strings.STATE_LINES["busy"]
    return ""


def state_key(view):
    """The state bar's standing key (round 8 row 54: ✕ hides it until the reason changes), or None for a line that goes
    by itself (getting ready, updating)."""
    if view is None:
        return None
    if view.state == "read-only" or (view.state == "getting-ready" and view.reason == "migration failed"):
        return standing.read_only_key(view.reason or view.state)
    return None


def media_to_open(language, episode, media):
    """The file ▶ opens for an episode, or (None, the bar's line): `services.play.to_open`'s answer (the rule is the
    service's, shared with Connect), worded for the bar. Runs on a worker (it reads the store and looks at the disk)."""
    path, why = play.to_open(language, episode.id, episode.rel_path, media)
    return (path, None) if path else (None, strings.PLAY_FAILED.format(name=episode.label, why=why))


def _ole32():
    """Windows' COM library (a seam: the tests count its calls)."""
    import ctypes
    return ctypes.windll.ole32


def open_with_system(path):
    """A file or a folder in the user's own program. On Windows on a worker: COM set up around the call, as
    ShellExecuteEx asks — an association that goes through COM (a Store app as the default player) can't start without
    it; balanced only when this call set it up (not reproduced with a Store-app player: none runs in tests)."""
    if sys.platform == "win32":
        ole32 = _ole32()
        mine = ole32.CoInitializeEx(None, 0x2 | 0x4) >= 0    # COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE
        try:
            os.startfile(path)                      # the user's own player
        finally:
            if mine:
                ole32.CoUninitialize()
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# --- small parts ------------------------------------------------------------------------------------------------- #
class StateBar(standing_qt.StandingLine):
    """The page's thin state bar: its words across the page, a read-only line's ✕ at its right end."""

    def __init__(self, parent=None):
        super().__init__("statebartext", parent, fill=True, margins=(0, 0, 6, 0))
        self.setObjectName("statebar")
        self.label.setWordWrap(False)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


def same_objects(a, b):
    """Two tuples holding the same objects, in order."""
    return a is b or (len(a) == len(b) and all(x is y for x, y in zip(a, b)))


class Page(QWidget):
    message = pyqtSignal(str)                       # a line for the bottom bar (a file that couldn't open)
    not_found = pyqtSignal(int)                     # an episode whose ▶ press found nothing: looked at again (row 55 A-7)
    state_dismissed = pyqtSignal(str)               # ✕ on the state bar: its key (the window hides it on every page)
    hidden = None                                   # the window's standing lines hidden this session (standing.Hidden)

    def __init__(self, name, heading, tooltips=None, language="ja", parent=None):
        super().__init__(parent)
        self.setObjectName(f"page-{name}")
        self.name = name
        self.language = language
        self.view_model = None
        outer = QVBoxLayout(self)                   # edge to edge: the Goal strip spans the window (G2.3 C2)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        box = QVBoxLayout()                         # the heading, the state bar and the list, inside the page's margins
        top, side, _bottom = theme.SPACING["current-body"]
        box.setContentsMargins(side, top, side, 0)
        box.setSpacing(8)
        outer.addLayout(box, 1)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.heading = QLabel(heading, self)
        self.heading.setObjectName("currentheading" if name == "current" else "pageheading")
        head.addWidget(self.heading)
        self.head_row = head
        head.addStretch(1)
        box.addLayout(head)
        self.state_bar = StateBar(self)
        self.state_bar.dismissed.connect(lambda: self.state_dismissed.emit(state_key(self.view_model) or ""))
        box.addWidget(self.state_bar)
        self.list = rows.RowsView(strings.LIST_NAMES.get(name, heading), tooltips=tooltips, parent=self)
        self.list.play_requested.connect(self._play)
        box.addWidget(self.list, 1)

    def entries(self, view):
        raise NotImplementedError

    def unchanged(self, old, new):
        """Whether this page's part of the view is the same as last time (no entries built, nothing diffed)."""
        return False

    def set_view(self, view):
        old, self.view_model = self.view_model, view
        self.paint_state()
        if old is not None and view is not None and old.loading == view.loading and self.unchanged(old, view):
            self.list.model().changed = []
            self.list.looks_changed = False
            return "same"                               # another page's change: this list's diff costs nothing
        return self.list.set_entries(self.entries(view))

    def paint_state(self):
        """The state bar for the view: a read-only line hidden by ✕ stays hidden until its reason changes (or it
        ended and came back); repainted only when it changes."""
        view = self.view_model
        line, key = state_line(view), state_key(view)
        if key is not None and self.hidden is not None and self.hidden.hid(key):    # read only (A-9): the window lets
            line = ""                                                               # the kind go as its trouble ends
        if line != self.state_bar.text() or self.state_bar.isHidden() == bool(line):   # only when it changes
            self.state_bar.show_line(line, closable=key is not None)

    def _media_of(self, episode):
        """The media type of the row an episode is in (looked up on a click, not kept per view: a view at 20,000 files
        must cost the GUI thread as little as it can)."""
        for kind, payload, _lines in self.list.model().entries:
            if any(e.id == episode.id for e in getattr(payload, "episodes", ())):
                return payload.media
        return None

    def _play(self, episode):
        media = self._media_of(episode)
        bridge.run_in_worker(media_to_open, self.language, episode, media,
                             then=lambda found: self._open_found(found, episode),
                             failed=lambda info: self.message.emit(strings.PLAY_FAILED.format(
                                 name=episode.label, why=str(info[0]))))

    def _open_found(self, found, episode=None):
        path, why = found
        if path is None:
            self.message.emit(why)
            if episode is not None:                       # row 55 A-7: the app now knows; its ▶ is looked at again
                self.not_found.emit(episode.id)
            return
        if sys.platform != "win32":                       # Qt's own opener belongs on the GUI thread
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        bridge.run_in_worker(open_with_system, path,
                             failed=lambda info: self.message.emit(strings.PLAY_FAILED.format(
                                 name=os.path.basename(path), why=str(info[0]))))


class CurrentPage(Page):
    def __init__(self, tooltips=None, language="ja", parent=None):
        super().__init__("current", strings.CURRENT_HEADING, tooltips, language, parent)
        self.heading.setToolTip(strings.CURRENT_HEADING_TIP)
        # W3.1a: what the rows ask for, handed to whoever does it (package F: the window's writer, the toasts, Undo).
        # Until a hook is set, nothing is written.
        self.on_done = None                         # (row, episode): the Done — watched, its toast, Undo, the finish
        self.on_nudge = None                        # (row, -1 | +1): ↑ ↓
        self.on_menu = None                         # (row, global QPoint): ⋯
        self.on_journey = None                      # (row, episode): Up Next's ↗
        self.on_line = None                         # --- P4.1 L2 (row 4.1.14): (kind): a line clicked ("top")
        self.list.done_requested.connect(self.done)
        self.list.nudge_requested.connect(lambda row, step: self._ask(self.on_nudge, row, step))
        self.list.menu_requested.connect(lambda row, at: self._ask(self.on_menu, row, at))
        self.list.journey_requested.connect(lambda row, ep: self._ask(self.on_journey, row, ep))
        self.list.line_requested.connect(lambda kind: self._ask(self.on_line, kind))     # --- P4.1 L2

    def done(self, row, episode):
        """**The one path for a Done** (S12), wherever it's clicked — a stone on a row, a stone or ✓ Done on Up Next,
        an episode's stone: `on_done(row, episode)` (package F's: `set_watched` through the window's writer, the toast
        `✓ X watched · next: Y` with Undo, and after a Done that leaves no file unwatched the signed finish toast). A
        stone already watched is the old chip's click: the hook reads `episode.watched` and turns it back."""
        self._ask(self.on_done, row, episode)

    @staticmethod
    def _ask(hook, *args):
        if hook is not None:
            hook(*args)

    def entries(self, view):
        if view is None:
            return []
        if not view.rows:
            return [] if view.loading else [(rows.EMPTY, strings.CURRENT_EMPTY, ())]
        after = {}
        for ln in view.lines:
            after.setdefault(ln.after, []).append(ln)
        out = []
        for i, r in enumerate(view.rows):
            out.append((rows.HERO if i == 0 else rows.ROW, r, tuple(after.get(i, ()))))
        return out

    def unchanged(self, old, new):
        # the reader's row cache keeps an unchanged row the same object, so an identity walk is the whole check
        return old.lines == new.lines and same_objects(old.rows, new.rows)



class FinishedPage(Page):
    def __init__(self, tooltips=None, language="ja", parent=None):
        super().__init__("finished", strings.FINISHED_HEADING, tooltips, language, parent)
        self.help = QLabel(strings.FINISHED_HELP, self)
        self.help.setObjectName("helpmark")
        self.help.setToolTip(strings.FINISHED_HELP_TIP)
        self.help.setAccessibleName(strings.FINISHED_HELP_NAME)
        self.help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.head_row.insertWidget(1, self.help)
        # --- W3.2 Q4: what the rows ask for, handed to Finished's actions (`app/qt/finished.py`); until a hook is set,
        # nothing is written. The importer's button shows once its hook is set (a window with a writer).
        self.on_put_back = None                     # (row): the hover's *Put back*
        self.on_menu = None                         # (row, global QPoint): ⋯ (Enter on the keyboard)
        self.on_import = None                       # (): *Add what you finished before…*
        self.list.put_back_requested.connect(lambda row: self._ask(self.on_put_back, row))
        self.list.menu_requested.connect(lambda row, at: self._ask(self.on_menu, row, at))
        self.importer = QPushButton(strings.FIN_IMPORT, self)
        self.importer.setObjectName("finimport")
        self.importer.setToolTip(strings.FIN_IMPORT_TIP)
        self.importer.setAccessibleName(strings.FIN_IMPORT)
        self.importer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.importer.clicked.connect(lambda _c=False: self._ask(self.on_import))
        self.importer.setVisible(False)
        self.head_row.addWidget(self.importer)

    @staticmethod
    def _ask(hook, *args):
        if hook is not None:
            hook(*args)
    # --- end W3.2 Q4

    def unchanged(self, old, new):
        return len(old.finished) == len(new.finished) and all(
            a.label == b.label and same_objects(a.rows, b.rows) for a, b in zip(old.finished, new.finished))

    def entries(self, view):
        if view is None:
            return []
        if not view.finished:
            return [] if view.loading else [(rows.EMPTY, strings.FINISHED_EMPTY, ())]
        out = []
        for month in view.finished:
            out.append((rows.MONTH, month.label, ()))
            out.extend((rows.FINISHED, r, ()) for r in month.rows)
        return out


class NeedsPage(Page):
    def __init__(self, tooltips=None, language="ja", parent=None):
        super().__init__("needs", strings.NEEDS_HEADING, tooltips, language, parent)
        self.failures = ()
        # --- W3.2 Q5: the cards with their buttons (`app/qt/needs.py`) take the painted list's place; their entries
        # come from `needs.NeedsYou` (the shell's `needs_you`), worked out on a worker
        from app.qt import needs as needs_ui
        self.controller = None
        box = self.layout().itemAt(0).layout()
        self.list.setVisible(False)
        self.area, self.cards = needs_ui.make_area(self)
        box.addWidget(self.area, 1)
        self.empty = QLabel(strings.NEEDS_EMPTY_TEXT, self)
        self.empty.setObjectName("sheetline")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setVisible(False)
        box.addWidget(self.empty)

    def set_view(self, view):
        if self.controller is None:
            return super().set_view(view)
        self.view_model = view
        self.paint_state()                              # round 8 (A-1): the ✕ rule, as every page's
        self.controller.view_in(view)
        self.list.looks_changed = False
        return "same"                                   # its cards repaint on their own entries (`show_entries`)

    def show_entries(self, entries, found=None, looking=()):
        self.cards.show_entries(entries, found, looking)
        empty = not entries and self.view_model is not None and not self.view_model.loading
        if self.empty.isHidden() == empty:
            self.empty.setVisible(empty)
    # --- end W3.2 Q5

    def set_failures(self, entries):
        if self.controller is not None:                # W3.2 Q5: the controller works them in
            self.controller.failures_in(entries)
            return
        entries = tuple(entries or ())
        if same_objects(entries, self.failures):    # the bar's every snapshot comes here: unchanged, nothing to do
            return
        self.failures = entries
        if self.view_model is not None:
            self.list.set_entries(self.entries(self.view_model))

    def unchanged(self, old, new):
        return old.needs == new.needs

    def entries(self, view):
        out = [(rows.NEED, n, ()) for n in (view.needs if view is not None else ())]
        out += [(rows.FAILURE, e, ()) for e in self.failures]
        if not out and view is not None and not view.loading:
            out = [(rows.EMPTY, strings.NEEDS_EMPTY, ())]
        return out


PAGES = {"current": CurrentPage, "finished": FinishedPage, "needs": NeedsPage}


def make_page(name, tooltips=None, language="ja", parent=None):
    return PAGES[name](tooltips=tooltips, language=language, parent=parent)
