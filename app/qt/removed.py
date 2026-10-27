"""🗑 *Removed* (alpha 4, D3; Mattias's note 6: a removed book's copy was kept out and nothing said so): what he removed
in the last 30 days, each with *Put back* — and Settings' *Bring back N removed* on a folder's line, which uses the same
reads and the same command.

- **The window** (`RemovedWindow`, on `windows.SecondaryWindow`; one of its kind, `open_window`; Esc closes it): one
  line per Remove and title, newest first (`SourceLooks.removed`, the store's `Store.removed`, read on the looks'
  worker as it opens — never polled): its title, *3 files · 12 days left* (the first of its files to go) and *Put back*.
  Nothing removed: one line, *Nothing removed in the last 30 days*; the store unreadable (`then(None)`): it says so.
- ***Put back*** = the writer's `restore(entry["trash_ids"])` through the window's drag controller (`moves._give`: one
  Ticket, one toast, one Undo). The line goes at the press (on screen in the frame: no arc); a refusal brings it back.
- **Read again only when the trash moved** (S19): a change the writer saved or undid that put files in the trash or took
  them out (`trash_moved`: a Remove, a skip, a Put back, their Undo) while the window is open — any window's, any menu's.
  A change that touched no trash reads nothing; a closed window reads nothing (it is gone).
- **Settings' *Bring back N removed*** (`settings_sources.SourceLine`): `SourceLooks.removed_under(root)` read when the
  *Library folders* window shows its folders (and when the trash moved while it is open); the button = `bring_back`
  (the writer's `restore(ids)`, one Undo), then a look of that folder so its next look sees them.

GUI_Design_Guidelines_Qt: the window's base (Esc closes it, its status line), the Settings doors' button style, a
tooltip on every button.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app import theme
from app.qt import strings, style, windows
from app.qt import settings_controls as sc

WINDOW = "removed"                                        # its name among the main window's secondary windows


def _f():
    return theme.text_factor(style.current()[1])


def open_window(shell):
    """🗑 *Removed…*: the window, one of its kind (raised when open)."""
    return windows.show(shell, WINDOW, RemovedWindow)


def trash_moved(change):
    """Did the saved or undone `change` put files in the trash or take them out (a Remove, a skip, a Put back)?"""
    return bool(getattr(change, "trash_ids", None) or getattr(change, "restored", None))


def follow_trash(shell, slot):
    """`slot(change, label)` — a bound method of a QObject on the window's thread (its connections go with it) — each
    time the writer saved or undid a change; the slot asks `trash_moved(change)`. -> True when wired (no writer:
    nothing to follow)."""
    relay = getattr(getattr(shell, "moves", None), "relay", None)
    if relay is None:
        return False
    q = Qt.ConnectionType.QueuedConnection                # (emitted on the writer's thread: heard on the window's)
    relay.saved.connect(slot, q)
    relay.undone.connect(slot, q)
    return True


def detail_words(entry):
    """An entry's second line: *3 files · 12 days left* (*last day* at 0; nothing in the trash, its original in a
    folder read: *from a folder Surasura reads*)."""
    n = entry.get("count") or 0
    files = strings.REMOVED_FILES_ONE if n == 1 else strings.REMOVED_FILES.format(n=n)
    days = entry.get("days_left")
    if days is None:
        left = strings.REMOVED_FROM_FOLDER
    elif days <= 0:
        left = strings.REMOVED_DAYS_LAST
    else:
        left = strings.REMOVED_DAYS_ONE if days == 1 else strings.REMOVED_DAYS.format(n=days)
    return f"{files} · {left}"


def give_back(shell, trash_ids, text, told=None):
    """The writer's `restore(trash_ids)` through the window's drag controller: one change, its toast with Undo.
    `told(event)`: the ticket's "saved" / "refused" / "undone" / "ended". -> the writer's number, or None."""
    moves = getattr(shell, "moves", None)
    if moves is None or not trash_ids or moves.refused() is not None:
        return None
    from app.qt import drag
    ticket = drag.Ticket(text)
    if told is not None:
        ticket.told = told
    ids = list(trash_ids)
    return moves._give(ticket, lambda t: moves.writer.restore(ids, label=t))


def entry_key(entry):
    return tuple(entry.get("trash_ids") or ())


class RemovedLine(QWidget):
    """One entry: its title, its files and days, and *Put back* (`on_put(key)`)."""

    def __init__(self, entry, on_put, parent=None):
        super().__init__(parent)
        self.setObjectName("settingssource")
        self.entry = dict(entry)
        self.key = entry_key(entry)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(8 * _f()))
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        self.title = QLabel(entry.get("title") or "", self)
        self.title.setObjectName("settingsvalue")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        words.addWidget(self.title)
        self.detail = QLabel(detail_words(entry), self)
        self.detail.setObjectName("windowline")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        words.addWidget(self.detail)
        line.addLayout(words, 1)
        title = entry.get("title") or ""
        self.put = sc.Door(strings.REMOVED_PUT_BACK, tooltip=strings.REMOVED_PUT_BACK_TIP.format(title=title),
                           name=strings.REMOVED_PUT_BACK_NAME.format(title=title), parent=self)
        self.put.clicked.connect(lambda _c=False: on_put(self.key))
        line.addWidget(self.put, 0, Qt.AlignmentFlag.AlignVCenter)

    def show_entry(self, entry):
        """-> True when anything it shows moved (its days, its count): only that label is set (S19)."""
        if entry == self.entry:
            return False
        self.entry = dict(entry)
        words = detail_words(entry)
        if self.detail.text() != words:
            self.detail.setText(words)
        return True


class RemovedWindow(windows.SecondaryWindow):
    """*Removed*: the lines (`lines`: key -> RemovedLine, newest first), the empty / unreadable / looking line (`none`).
    `reads`: how many times the list was asked of the looks (S19); `answer`: the last one (None: unreadable)."""

    def __init__(self, shell, language=None):
        super().__init__(shell, strings.REMOVED_NAME, language)
        self.lines = {}
        self.reads = 0
        self.answer = ()
        self._reading = False                             # a read on the looks' worker
        self._again = False                               # the trash moved meanwhile: one more after it
        self._putting = set()                             # keys put back, not yet saved (their lines hidden)
        intro = QLabel(strings.REMOVED_LINE, self)
        intro.setObjectName("windowline")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("foldersscroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.box = QWidget()
        self.box.setObjectName("foldersbody")
        column = QVBoxLayout(self.box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(round(8 * _f()))
        self.none = QLabel(strings.REMOVED_LOOKING, self.box)
        self.none.setObjectName("windowline")
        self.none.setWordWrap(True)
        column.addWidget(self.none)
        column.addStretch(1)
        self.scroll.setWidget(self.box)
        self.body.addWidget(self.scroll, 1)
        from app.qt import bridge
        self._relay = bridge.Relay(self)
        self._relay.said.connect(self._landed)
        follow_trash(shell, self._heard)
        self.read()

    # --- reading ------------------------------------------------------------------------------------------------ #
    def read(self):
        """The list asked of the looks' worker (one at a time: asked meanwhile, one more after it). -> True when asked."""
        if self.gone:
            return False
        if self._reading:
            self._again = True
            return False
        looks = getattr(self.shell, "looks", None)
        if looks is None or not hasattr(looks, "removed"):
            self._show(None)
            return False
        language = self.language
        self._reading = True
        self.reads += 1
        if not looks.removed(lambda found: self._relay.call((language, found)), language=language):
            self._reading = False
            self._show(None)
            return False
        return True

    def _heard(self, change, _label=None):
        if trash_moved(change):
            self.read()

    def _landed(self, said):
        language, found = said
        self._reading = False
        if self.gone:
            return
        if self._again:
            self._again = False
            self.read()
            return
        if language == self.language:
            self._show(found)

    def language_changed(self, language):
        self._show_lines(())
        self._words(strings.REMOVED_LOOKING)
        self.read()

    # --- showing ------------------------------------------------------------------------------------------------ #
    def _words(self, text):
        if self.none.text() != text:
            self.none.setText(text)
        if self.none.isHidden() == bool(text):
            self.none.setVisible(bool(text))

    def _show(self, entries):
        """The answer shown: None, the store unreadable (said); [] the empty line; else the lines, only what moved."""
        self.answer = entries
        if entries is None:
            self._show_lines(())
            self._words(strings.REMOVED_UNREADABLE)
            return
        shown = [e for e in entries if entry_key(e) not in self._putting]
        self._show_lines(shown)
        self._words("" if shown else strings.REMOVED_NONE)

    def _show_lines(self, entries):
        keys = [entry_key(e) for e in entries]
        gone = [k for k in self.lines if k not in keys]
        column = self.box.layout()
        for k in gone:
            line = self.lines.pop(k)
            column.removeWidget(line)
            line.hide()
            line.deleteLater()
        added = False
        for n, entry in enumerate(entries):
            k = keys[n]
            line = self.lines.get(k)
            if line is not None:
                line.show_entry(entry)
                if column.indexOf(line) != n + 1:
                    column.removeWidget(line)
                    column.insertWidget(n + 1, line)
                continue
            line = RemovedLine(entry, self.put_back, parent=self.box)
            column.insertWidget(n + 1, line)                  # (after the empty line, which leads the column)
            self.lines[k] = line
            line.show()
            added = True
        if added:
            chain = [self.lines[k].put for k in keys]
            for a, b in zip(chain, chain[1:]):
                QWidget.setTabOrder(a, b)
            self._grow()

    def _grow(self):
        """As *Library folders* grows: up to the screen's room below it, then the lines scroll (never shrinks)."""
        if not self.isVisible():
            return
        self.box.layout().activate()
        need = self.box.sizeHint().height() - self.scroll.viewport().height()
        screen = self.screen()
        room = screen.availableGeometry().bottom() - self.frameGeometry().bottom() if screen is not None else need
        grow = min(need, room)
        if grow > 0:
            self.resize(self.width(), self.height() + grow)

    # --- acting ------------------------------------------------------------------------------------------------- #
    def put_back(self, key):
        """*Put back*: its line goes at once; the writer's `restore` given (its toast's Undo brings the line back, as
        the list is read again). Refused: the line comes back. -> True when given."""
        line = self.lines.get(key)
        if line is None or self.gone:
            return False
        entry = line.entry
        self._putting.add(key)
        self._show(self.answer)

        def told(event):
            self._putting.discard(key)
            if self.gone:
                return
            if event == "saved":
                self.read()                                # (a read under way: its answer, from before, is dropped)
            elif event in ("refused", "ended"):
                self._show(self.answer)
        if give_back(self.shell, entry.get("trash_ids"), strings.REMOVED_BACK.format(title=entry.get("title") or ""),
                     told=told) is None:
            self._putting.discard(key)
            if not self.gone:
                self._show(self.answer)
            return False
        return True
