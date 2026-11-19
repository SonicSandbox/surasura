"""*Words Surasura won't mine again* (Kantan-B2, a new tester 2026-11-18: "where does it keep a record of that? can it
ever be reset?"; every word PROVISIONAL): the words whose cards you deleted in Anki — Connect keeps each word it made a
card for (the store's `made_words`, G1.3-4) and never makes it again by itself — each with *Allow again*.

- **The window** (`UnminedWindow`, on `windows.SecondaryWindow`; one of its kind, `open_window`; one per episode from
  an episode's ⋯, `open_window(item_ids=…)`; Esc closes it): one line per word, the newest made first — the word,
  *from <episode>* and *Allow again*. Read as it opens, never polled, on a pool thread with a store handle of its own
  (`removed.read_store`), and again once an *Allow again* is saved or undone. At most `SHOWN` lines (*N more not
  shown*). Nothing to show: one line; the store unreadable: it says so.
- ***Allow again*** = the writer's `allow_again([word])` through the window's drag controller (`moves._give`: one
  Ticket, one toast, one Undo — Undo keeps it out again). The line goes at the press; a refusal brings it back and reads
  the list again. Greyed with the store's reason while it can't be written (IK2-10).
- **The doors:** Settings › Anki & mining's *Words it won't mine again* row (`windows.OPENERS` "unmined-words") and
  an episode's ⋯ (`mine_actions.episode_entries`, beside *Mine again*: that episode's words only).

GUI_Design_Guidelines_Qt: the window's base (Esc closes it, its status line), the Settings doors' button style, a
tooltip on every button.
"""
import os

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import theme
from app.qt import removed, strings, style, windows
from app.qt import settings_controls as sc

WINDOW = "unmined-words"                                  # its name among the main window's secondary windows
SHOWN = 300                                               # the lines built at most (the rest: one line saying so)


def _f():
    return theme.text_factor(style.current()[1])


def open_window(shell, item_ids=None, label=None):
    """The window, one of its kind (raised when open); `item_ids` (an episode's ⋯): that episode's words, its own."""
    if item_ids is None:
        return windows.show(shell, WINDOW, UnminedWindow)
    ids = tuple(item_ids)
    return windows.show(shell, f"{WINDOW}:{','.join(map(str, ids))}",
                        lambda s: UnminedWindow(s, item_ids=ids, label=label))


def words_heard(shell):
    """An *Allow again* saved or undone has landed (the drag controller's `_saved` / `_undone`): every open list of
    words reads again."""
    for name, win in list(shell.__dict__.get("_secondary_windows", {}).items()):
        if (name == WINDOW or name.startswith(WINDOW + ":")) and not win.gone:
            win.read()


def read(store, item_ids=None, shown=SHOWN):
    """(A pool thread's.) The words, each with `from`: the file name of the episode that made it last (its first
    `shown` only) -> the store's list."""
    entries = store.unmined_words(item_ids)
    for entry in entries[:shown]:
        item = store.item(entry["items"][0]) or {}
        entry["from"] = os.path.splitext(os.path.basename(str(item.get("rel_path") or "")))[0]
    return entries


def from_words(entry):
    label = entry.get("from") or ""
    more = len(entry.get("items") or ()) - 1
    if not label:
        return ""
    return strings.UNMINED_FROM_MORE.format(label=label, n=more) if more > 0 else strings.UNMINED_FROM.format(label=label)


def allow(shell, word, told=None):
    """The writer's `allow_again([word])` through the window's drag controller: one change, its toast with Undo.
    `told(event)`: the ticket's "saved" / "refused" / "undone" / "ended". -> the writer's number, or None."""
    moves = getattr(shell, "moves", None)
    if moves is None or moves.refused() is not None:
        return None
    from app.qt import drag
    ticket = drag.Ticket(strings.UNMINED_ALLOWED.format(word=word))
    if told is not None:
        ticket.told = told
    return moves._give(ticket, lambda t: moves.writer.allow_again([word], label=t))


class UnminedLine(QWidget):
    """One word: the word, where it was made, and *Allow again* (`on_allow(word)`)."""

    def __init__(self, entry, on_allow, parent=None):
        super().__init__(parent)
        self.setObjectName("settingssource")
        self.entry = dict(entry)
        self.key = entry["word"]
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(8 * _f()))
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        self.word = QLabel(entry["word"], self)
        self.word.setObjectName("settingsvalue")
        self.word.setTextFormat(Qt.TextFormat.PlainText)
        words.addWidget(self.word)
        self.detail = QLabel(from_words(entry), self)
        self.detail.setObjectName("windowline")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        words.addWidget(self.detail)
        line.addLayout(words, 1)
        self.tip = strings.UNMINED_ALLOW_TIP.format(word=entry["word"])
        self.allow = sc.Door(strings.UNMINED_ALLOW, tooltip=self.tip,
                             name=strings.UNMINED_ALLOW_NAME.format(word=entry["word"]), parent=self)
        self.allow.clicked.connect(lambda _c=False: on_allow(self.key))
        line.addWidget(self.allow, 0, Qt.AlignmentFlag.AlignVCenter)


class UnminedWindow(windows.SecondaryWindow):
    """The words (`lines`: word -> UnminedLine, in `order`), the empty / unreadable / looking line (`none`), the more
    line (`more`). `reads`: how many times the list was asked (S19); `answer`: the last one (None: unreadable)."""

    def __init__(self, shell, language=None, item_ids=None, label=None):
        super().__init__(shell, strings.UNMINED_NAME, language, scroll=True)
        self.item_ids = tuple(item_ids) if item_ids is not None else None
        self.lines = {}
        self.order = []
        self.reads = 0
        self.answer = ()
        self._reading = False
        self._again = False
        self._allowing = set()                            # words allowed, not yet saved (their lines hidden)
        intro = QLabel(strings.UNMINED_LINE_OF.format(label=label) if label else strings.UNMINED_LINE, self)
        intro.setObjectName("windowline")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.box = QWidget(self)
        column = QVBoxLayout(self.box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(round(8 * _f()))
        self.none = QLabel(strings.UNMINED_LOOKING, self.box)
        self.none.setObjectName("windowline")
        self.none.setWordWrap(True)
        column.addWidget(self.none)
        self.more = QLabel("", self.box)
        self.more.setObjectName("windowline")
        self.more.setVisible(False)
        column.addWidget(self.more)
        self.body.addWidget(self.box)
        self.body.addStretch(1)
        self.read()

    # --- reading ------------------------------------------------------------------------------------------------ #
    def read(self):
        """The list asked (one at a time: asked meanwhile, one more after it). -> True when asked."""
        if self.gone:
            return False
        if self._reading:
            self._again = True
            return False
        language, ids = self.language, self.item_ids
        self._reading = True
        self.reads += 1
        if removed.read_store(self.shell, language, lambda store: read(store, ids),
                              lambda found: self._landed((language, found))):
            return True
        self._reading = False
        self._show(None)                                  # no library of this language open to read
        return False

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
        self._words(strings.UNMINED_LOOKING)
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
        """None: unreadable (said); []: the empty line; else the lines — a kept line is the same widget (S19)."""
        self.answer = entries
        if entries is None:
            self._show_lines(())
            self._words(strings.UNMINED_UNREADABLE)
            return
        shown = [e for e in entries if e["word"] not in self._allowing]
        self._show_lines(shown)
        none = strings.UNMINED_NONE_OF if self.item_ids is not None else strings.UNMINED_NONE
        self._words("" if shown else none)

    def _show_lines(self, entries):
        keep, order, made = {}, [], []
        for entry in entries[:SHOWN]:
            line = self.lines.get(entry["word"])
            if line is None:
                line = UnminedLine(entry, self.allow_again, parent=self.box)
                made.append(line)
            keep[line.key] = line
            order.append(line.key)
        column = self.box.layout()
        for k, line in self.lines.items():
            if k not in keep:
                column.removeWidget(line)
                line.hide()
                line.deleteLater()
        self.lines = keep
        if order != self.order:
            for i, k in enumerate(order):
                column.removeWidget(self.lines[k])
                column.insertWidget(i + 1, self.lines[k])     # (after the empty line, which leads the column)
            self.order = order
        rest = len(entries) - len(order)
        self.more.setText(strings.UNMINED_MORE.format(n=rest) if rest > 0 else "")
        self.more.setVisible(rest > 0)
        for line in made:
            line.show()
        if made:
            self._enable(made)
        for a, b in zip(order, order[1:]):
            QWidget.setTabOrder(self.lines[a].allow, self.lines[b].allow)

    def _enable(self, lines=None):
        """IK2-10: every *Allow again* greyed with the store's reason while nothing can be written."""
        from app.qt import settings_sources
        why = removed.why_not(self.shell)
        for line in (self.lines.values() if lines is None else lines):
            settings_sources._turn(line.allow, why is None, why or line.tip)

    # --- acting ------------------------------------------------------------------------------------------------- #
    def allow_again(self, word):
        """*Allow again*: its line goes at once; the writer's `allow_again` given — the list read again once it is
        saved or undone (its toast's Undo brings the line back); refused or ended unsaved: the line comes back.
        -> True when given."""
        if word not in self.lines or self.gone:
            return False
        self._allowing.add(word)
        self._show(self.answer)

        def told(event):
            if event in ("saved", "refused", "ended", "undone"):
                self._allowing.discard(word)
            if self.gone:
                return
            if event in ("refused", "ended"):
                self._show(self.answer)
            if event in ("refused", "ended"):
                self.read()                               # (saved, undone: read as it lands, `words_heard`)
        if allow(self.shell, word, told=told) is None:
            self._allowing.discard(word)
            if not self.gone:
                self._show(self.answer)
            return False
        return True
