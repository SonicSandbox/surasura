"""🗑 *Removed* (alpha 4, D3; Mattias's note 6: a removed book's copy was kept out and nothing said so): what he removed
in the last 30 days, each with *Put back* — and Settings' *Bring back N removed* on a folder's line, which uses the same
reads and the same command.

- **The window** (`RemovedWindow`, on `windows.SecondaryWindow`; one of its kind, `open_window`; Esc closes it): one
  line per Remove and title, newest first (the store's `Store.removed`, read as it opens — never polled — on a pool
  thread with a store handle of its own, `read_store`: never queued behind a look on the looks' worker, A4B-7): its
  title, *3 files · 12 days left* (the first of its files to go) and *Put back*. Nothing removed: one line, *Nothing
  removed in the last 30 days*; the store unreadable (None): it says so. A4B-3: the first `BUILT_AT_ONCE` lines are
  built as the answer lands (`FIRST_FRAME` of them in its own turn, the rest a slice of `SLICE_S` at a time on idle
  time), the next ones as the list is scrolled near its end — 2,500 entries after a mass Remove open in one frame.
- ***Put back*** = the writer's `restore(entry["trash_ids"])` through the window's drag controller (`moves._give`: one
  Ticket, one toast, one Undo). The line goes at the press (on screen in the frame: no arc); a refusal brings it back
  and reads the list again. Greyed with the store's reason while it can't be written (IK2-10).
- **Read again only when the trash moved** (S19): a change the window's drag controller saved or undid that put files
  in the trash or took them out (`trash_heard`, called by whichever controller is current — a language switch makes a
  new one, A4B-6) while the window is open — any window's, any menu's. A change that touched no trash reads nothing;
  a closed window reads nothing (it is gone). Another language's library: read once it is shown (`library_switched`).
- **Settings' *Bring back N removed*** (`settings_sources.SourceLine`): every folder's removed files in one read
  (`removed_by_root`) when the *Library folders* window shows its folders (and when the trash moved while it is open);
  the button = `bring_back` (the writer's `restore(ids)`, one Undo), then a look of that folder so its next look sees
  them.

GUI_Design_Guidelines_Qt: the window's base (Esc closes it, its status line), the Settings doors' button style, a
tooltip on every button.
"""
import time

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app import theme
from app.qt import strings, style, windows
from app.qt import settings_controls as sc

WINDOW = "removed"                                        # its name among the main window's secondary windows
BUILT_AT_ONCE = 30                                        # A4B-3 (Needs you's rule): the lines built as the answer
#                                                           lands, and again each time the list nears its end
FIRST_FRAME = 2                                           # ... those built in the answer's own turn
SLICE_S = 0.004                                           # ... the rest a slice at a time, off idle time
NEAR_END = 1.5                                            # viewports from the end that ask for the next lines


def _f():
    return theme.text_factor(style.current()[1])


def open_window(shell):
    """🗑 *Removed…*: the window, one of its kind (raised when open)."""
    return windows.show(shell, WINDOW, RemovedWindow)


def trash_moved(change):
    """Did the saved or undone `change` put files in the trash or take them out (a Remove, a skip, a Put back)?"""
    return bool(getattr(change, "trash_ids", None) or getattr(change, "restored", None))


def trash_heard(shell, change):
    """A4B-6: the window's drag controller saved or undid `change` (`drag.DragController._saved` / `_undone`, on the
    window's thread — whichever controller is current, a language switch makes a new one): the open 🗑 list and
    *Library folders* read again when it moved the trash."""
    if not trash_moved(change):
        return
    tray, looks = getattr(shell, "arrivals_tray", None), getattr(shell, "looks", None)
    if tray is not None and looks is not None and tray.kept_out[0] and tray.giving is None:
        looks.listing()                    # alpha 4: New arrivals' kept-out foot as the trash stands now (a Put back or
    from app.qt import settings_sources    # an Undo here; never left offering a Remove already put back, review)
    for name in (WINDOW, settings_sources.WINDOW):
        heard = getattr(windows.opened(shell, name), "trash_heard", None)
        if heard is not None:
            heard()


def read_store(shell, language, ask, then):
    """A4B-7: `ask(store)` on a pool thread with a store handle of its own (the library's opener, closed after — as
    Needs you's asks are read), never queued behind a look on the looks' worker; `then(answer)` on the window's thread,
    None when the store couldn't be read. -> False when no library of `language` is open to read (another language's
    is: the caller waits for `library_switched`)."""
    reader = getattr(getattr(shell, "services", None), "library", None)
    opener = getattr(reader, "opener", None)
    if opener is None or not hasattr(opener, "handle") or getattr(reader, "language", language) != language:
        return False

    def run():
        try:
            store = opener.handle()
            return None if store is None else ask(store)
        except Exception as e:
            print(f"Removed: the trash couldn't be read: {e!r}")
            return None
        finally:
            close = getattr(opener, "close", None)    # (this pool thread's handle: a pool thread keeps none)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
    from app.qt import bridge
    bridge.run_in_worker(run, then=then, failed=lambda _info: then(None))
    return True


def removed_by_root(store, roots):
    """Settings' *Bring back N removed*, every folder line in one read -> {root id: [trash id]} for `roots` (A4B-7): the
    store's own one-read answer when it offers it (Seams: `Store.removed_by_root()`), else each folder's
    `Store.removed_under` in this one job (off the window's thread and the looks' worker)."""
    by = getattr(store, "removed_by_root", None)
    if by is not None:
        got = by()
        return {r: sorted(got.get(r, ())) for r in roots}
    return {r: store.removed_under(r) for r in roots}


def why_not(shell):
    """Why nothing can be put back now (*Put back*'s greyed tip: the store's reason, IK2-10), or None."""
    from app.qt import settings_sources
    return settings_sources.why_not(shell)


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
    """One entry: its title, its files and days, and *Put back* (`on_put(key)`; `tip`: its own words)."""

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
        self.tip = strings.REMOVED_PUT_BACK_TIP.format(title=title)     # (greyed: why, the window's `_enable`)
        self.put = sc.Door(strings.REMOVED_PUT_BACK, tooltip=self.tip,
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
    """*Removed*: the lines built (`lines`: key -> RemovedLine; `order`: their keys — the first of the entries shown, in
    their order), the empty / unreadable / looking line (`none`). `reads`: how many times the list was asked (S19);
    `answer`: the last one (None: unreadable); `builds`: how many lines were built (S19)."""

    def __init__(self, shell, language=None):
        super().__init__(shell, strings.REMOVED_NAME, language)
        self.lines = {}
        self.order = []
        self.builds = 0
        self.reads = 0
        self.answer = ()
        self.limit = BUILT_AT_ONCE                        # A4B-3: how many of the entries are to be built
        self._want = ()                                   # ... every entry shown, built or not
        self._growing = False                             # ... a slice due on idle time
        self._reading = False                             # a read under way
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
        bar = self.scroll.verticalScrollBar()             # A4B-3: the next lines as the list nears its end
        bar.valueChanged.connect(self.scrolled)
        bar.rangeChanged.connect(self.scrolled)
        switched = getattr(shell, "library_switched", None)
        if switched is not None:                          # A4B-6: another language's library shown: its trash read
            switched.connect(self._switched)
        self.read()

    # --- reading ------------------------------------------------------------------------------------------------ #
    def read(self):
        """The list asked (`read_store`; one at a time: asked meanwhile, one more after it). Another language's library
        still shown: *Looking…* until this one's is (`_switched`). -> True when asked."""
        if self.gone:
            return False
        if self._reading:
            self._again = True
            return False
        language = self.language
        self._reading = True
        self.reads += 1
        if read_store(self.shell, language, lambda store: store.removed(),
                      lambda found: self._landed((language, found))):
            return True
        self._reading = False
        reader = getattr(getattr(self.shell, "services", None), "library", None)
        if reader is not None and getattr(reader, "language", language) != language:
            self._show_lines(())                          # (the switch on its way: read once it is shown)
            self._words(strings.REMOVED_LOOKING)
        else:
            self._show(None)                              # no library open to read
        return False

    def trash_heard(self):
        """A4B-6: the window's controller saved or undid a change that moved the trash (`trash_heard`)."""
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

    def _switched(self):
        """A4B-6: the shell shows another library — this window's language's read, once it is the one shown (the
        settings write said the language first, `language_changed`, while the last one's was still shown)."""
        if not self.gone and not self._reading and not self.lines and self.none.text() == strings.REMOVED_LOOKING:
            self.read()

    def language_changed(self, language):
        self._show_lines(())
        self._words(strings.REMOVED_LOOKING)
        self.read()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and not self.gone:
            self._enable()                                # IK2-10: the store's state as it is now

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
        shown = [e for e in entries if entry_key(e) not in self._putting] if self._putting else entries
        self._show_lines(shown)
        self._words("" if shown else strings.REMOVED_NONE)

    def _show_lines(self, entries, now=FIRST_FRAME):
        """A4B-3: the first `limit` entries' lines — a line kept is the same widget, only its words that moved set
        (S19); at most `now` built in this turn, the rest in slices on idle time (`_build_more`)."""
        self._want = tuple(entries)
        keep, order, made = {}, [], []
        for entry in self._want[:self.limit]:
            k = entry_key(entry)
            line = self.lines.get(k)
            if line is not None:
                line.show_entry(entry)
            elif len(made) >= now:
                break                                     # (many to build: the rest in slices)
            else:
                line = self._line(entry)
                made.append(line)
            keep[k] = line
            order.append(k)
        column = self.box.layout()
        for k, line in self.lines.items():
            if k not in keep:
                column.removeWidget(line)
                line.hide()
                line.deleteLater()
        self.lines = keep
        if order != self.order:
            self._place(order)
        if made:
            for line in made:
                line.show()
            self._chain(min(order.index(line.key) for line in made))
            self._enable(made)
            self._grow()
        if len(self.order) < min(self.limit, len(self._want)):
            self._more()

    def _line(self, entry):
        self.builds += 1
        return RemovedLine(entry, self.put_back, parent=self.box)

    def _place(self, order):
        """The lines in `order` in the column (after the empty line, which leads it): only a line out of its place is
        moved — walked by key, never an `indexOf` per line."""
        column = self.box.layout()
        cur = [k for k in self.order if k in self.lines]
        placed = set(cur)
        for i, k in enumerate(order):
            if i < len(cur) and cur[i] == k:
                continue
            line = self.lines[k]
            if k in placed:
                cur.remove(k)
                column.removeWidget(line)
            cur.insert(i, k)
            placed.add(k)
            column.insertWidget(i + 1, line)
        self.order = list(order)

    def _chain(self, start):
        """Tab through the lines' *Put back* in order, from the line before `start` on (lines made later would
        otherwise join the chain's end)."""
        puts = [self.lines[k].put for k in self.order[max(0, start - 1):]]
        for a, b in zip(puts, puts[1:]):
            QWidget.setTabOrder(a, b)

    def _enable(self, lines=None):
        """IK2-10: every *Put back* (or `lines`') greyed with the store's reason while nothing can be written, its own
        tip back once it can. Only what moved is touched (S19)."""
        from app.qt import settings_sources
        why = why_not(self.shell)
        for line in (self.lines.values() if lines is None else lines):
            settings_sources._turn(line.put, why is None, why or line.tip)

    def _more(self):
        if not self._growing:
            self._growing = True
            QTimer.singleShot(0, self._build_more)

    def scrolled(self, *_args):
        """A4B-3: the list scrolled (or its length changed) — near its end with entries still to build, the next
        `BUILT_AT_ONCE` built, a slice at a time on idle time."""
        if self._growing or self.gone or len(self.order) >= len(self._want):
            return
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - bar.value() > NEAR_END * self.scroll.viewport().height():
            return
        self.limit = max(self.limit, len(self.order) + BUILT_AT_ONCE)
        self._more()

    def _build_more(self):
        """The next lines built in order, until `limit` — `SLICE_S` at a time on idle time."""
        from PyQt6 import sip
        self._growing = False
        if self.gone or sip.isdeleted(self):
            return
        start, made = time.perf_counter(), []
        column = self.box.layout()
        target = min(len(self._want), self.limit)
        while len(self.order) < target:
            line = self._line(self._want[len(self.order)])
            column.insertWidget(len(self.order) + 1, line)
            self.lines[line.key] = line
            self.order.append(line.key)
            made.append(line)
            line.show()
            if time.perf_counter() - start > SLICE_S and len(self.order) < target:
                self._more()
                break
        if made:
            self._chain(len(self.order) - len(made))
            self._enable(made)
            self._grow()

    def settled(self):
        """(Tests.) Every line due is built (none waiting on idle time)."""
        return not self._growing and len(self.order) >= min(self.limit, len(self._want))

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
        """*Put back*: its line goes at once; the writer's `restore` given (the list read again as the change lands,
        `trash_heard` — once, A4B-11; its toast's Undo brings the line back the same way). Refused or ended unsaved:
        the line comes back and the list is read again (an entry purged or put back elsewhere meanwhile goes, A4B-10).
        -> True when given."""
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
            if event in ("refused", "ended"):
                self._show(self.answer)
                self.read()
        if give_back(self.shell, entry.get("trash_ids"), strings.REMOVED_BACK.format(title=entry.get("title") or ""),
                     told=told) is None:
            self._putting.discard(key)
            if not self.gone:
                self._show(self.answer)
            return False
        return True
