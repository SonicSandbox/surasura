"""Finished's actions (W3.2 Q4; RUNBOOK §1 *Finished* and *What if I added it back?*, §5 leans 1 and 8, §5a IK-1, IK-5,
IK-11, N3, N15; Sonic's W3.2-1: the card with the numbers and the first 20 new words with their readings).

Finished keeps today's layout (`screens.FinishedPage`, `rows.py`'s FINISHED rows); this file is what its rows ask for:
- **Put back** (the hover's button, and ⋯): `Writer.put_back` — to the top of Current and its cards back in the learning
  order, one store command, one Undo (IK-1); its toast with Undo. Past Graduates (2.x's) are rows like any.
- **⋯** (a click, or Enter / Space / the menu key on a row the keyboard is on): *What if I added it back?* · *Put back* ·
  *Study its cards first* ↔ *Done with its cards* (`Writer.pin`; E23: a pin kept through finishing shows as *Done with
  its cards*) · *Its N cards in Anki* › *Leave its new cards out of your order* ↔ *Put them back in the order*
  (`Writer.keep_cards`, the row's `cards_out` the state shown; the Anki half is P4.1's: these words say what the store
  does, never that Anki changed) · *Open its folder* (`windows.open_url`, N3). *Mine* (no cards) and *Mine it too* show
  once P4.1 sets `on_mine` / `on_mine_too`. The writes greyed with the store's reason while it can't be written (E4).
- **What if I added it back?**: a small slate card under the row, at once — a dash while the arrivals worker
  (`app/services/arrivals.ArrivalsWorker`, E2.2 D10) answers for its files, each asked with the earlier ones `placed`
  at the top of NOW, in order (IK-5): *At the top of Current it would bring N new words · M % known* and the first 20
  new words with their readings, in the order he'd meet them; *Put back* · *Open your journey*. Nothing moves. Esc,
  Back, ✕ and a click outside close it. N = the distinct words over its files (each file's `words`: its list words, none
  known): a word in every episode is one new word. M = known ÷ counted over its files (G1.2-4's one definition).
- **Add what you finished before…** (the heading's button): files or a folder → `finished_import.ImportJob` (a registry
  job: its progress on the hairline and the bar's line; the button says *Stop adding* while it runs), then the toast
  *Added N to Finished* with Undo (only the job's copies go to the trash). **Files dropped from Explorer** on the
  Finished tab or the Finished list go through the same job (lean 8).

Nothing here reads or writes the store on the window's thread: the writes are the window's writer's (queued, journalled;
their toasts and Undo through W3.1a's `drag.DragController`), the folder check and the estimates run on workers.
"""
import os
import time

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPainter
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton,
                             QVBoxLayout)

from app import path_utils, theme
from app.qt import bridge, drag, motion, shadow, strings, style, windows

WORDS_SHOWN = 20                                     # Sonic's W3.2-1: the first 20 new words
LAND_MS = 50                                         # how often the import toast looks for the writer's answer
LAND_DEADLINE_S = 300                                # ... and for how long (W3.2 H T2): then a line, never for ever


def folder_of(language, row):
    """The folder a Finished row's first file is in (on disk), or None."""
    rel = next((e.rel_path for e in row.episodes if e.rel_path), None)
    if not rel:
        return None
    return os.path.dirname(os.path.join(path_utils.get_data_path(language), *rel.split("/")))


def file_paths(language, row):
    """(absolute path, data-folder-relative id) of each of a row's files, in its order."""
    data = path_utils.get_data_path(language)
    return [(os.path.join(data, *e.rel_path.split("/")), e.rel_path) for e in row.episodes if e.rel_path]


def placed_before(files, k):
    """IK-5: the files before file `k` as the worker's `placed` — the first at the top of NOW, each next one after the
    one before it (anchors are data-folder-relative ids, as the plan names its files)."""
    return [{"path": files[j][0], "tier": "now", "before": None, "after": files[j - 1][1] if j else None}
            for j in range(k)]


def what_if_numbers(answers):
    """The card's numbers from the worker's answers (one per file, in order; None or {"error"} for one that failed) ->
    {"n": distinct new words or None, "pct": % known (rounded) or None, "words": the first `WORDS_SHOWN` [Word, Reading]
    in the order met, "state": "ok" · "no-plan" (no Generate yet: % only) · "none" (no answer at all)}."""
    good = [a for a in answers if isinstance(a, dict) and "error" not in a]
    if not good:
        return {"n": None, "pct": None, "words": [], "state": "none"}
    known = sum(a.get("known") or 0 for a in good)
    counted = sum(a.get("counted") or 0 for a in good)
    pct = round(known / counted * 100) if counted else None
    if any(a.get("reason") == "no-plan" or a.get("n_new_top") is None for a in good):
        return {"n": None, "pct": pct, "words": [], "state": "no-plan"}
    seen, words = set(), []
    for a in good:
        for w in a.get("words") or ():
            key = (w[0], w[1] if len(w) > 1 else "")
            if key not in seen:
                seen.add(key)
                words.append(list(key))
    return {"n": len(words), "pct": pct, "words": words[:WORDS_SHOWN], "state": "ok"}


def word_text(word, reading):
    """A word with its reading (none when the reading is the word as written)."""
    return word if not reading or reading == word else f"{word}（{reading}）"


class _ImportTicket(drag.Ticket):
    """The importer's ticket, kept in the drag controller's `tickets` while it copies and lands, so Ctrl+Z then takes
    the import back as it lands (AD2-5; L1 N6). `taken_back`: its Undo was asked before it landed (the controller
    clears `undo_asked` as it takes the change back) — no *Added N* toast then."""
    __slots__ = ("taken_back",)

    def __init__(self, text):
        self.taken_back = False
        super().__init__(text)

    @property
    def undo_asked(self):
        return drag.Ticket.undo_asked.__get__(self)

    @undo_asked.setter
    def undo_asked(self, on):
        if on:
            self.taken_back = True
        drag.Ticket.undo_asked.__set__(self, on)


class _TicketWriter:
    """The importer's writer: the window's own, its command labelled with the toast's ticket (so the toast's Undo is
    that change's, through W3.1a's `DragController`). `answer`: the writer's own answer for this import (its thread
    sets it) — `saved` / `changed`, or `refused` / `failed` — which the toast is decided from (L1 S6)."""

    def __init__(self, writer, ticket):
        self.writer, self.ticket = writer, ticket
        self.answer = None

    def can_write(self):
        return self.writer.can_write()

    def reason(self):
        return self.writer.reason()

    def stopped(self):
        stopped = getattr(self.writer, "stopped", None)
        return bool(stopped()) if stopped is not None else False

    def import_finished(self, paths, copied=(), label=None, answer=None):
        def answered(cmd):
            self.answer = {k: cmd[k] for k in ("saved", "changed", "refused", "failed") if k in cmd}
            if answer is not None:
                answer(cmd)
        return self.writer.import_finished(paths, copied=copied, label=self.ticket, answer=answered)


class _Relay(QObject):
    answer = pyqtSignal(object, object)             # (the card's token, (file index, answer))
    imported = pyqtSignal(object)                   # the ImportJob, ended


class _Away(QObject):
    """A press outside the card closes it, as Esc does; the press goes on to what it was on."""

    def __init__(self, card):
        super().__init__(card)
        self.card = card

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.card.isVisible():
            at = event.globalPosition().toPoint()
            if not self.card.rect().translated(self.card.mapToGlobal(QPoint(0, 0))).contains(at):
                self.card.close()
        return False


class WhatIfCard(motion.Overlay):
    """*What if I added it back?*: the numbers, the first new words with their readings, *Put back* and *Open your
    journey*, in slate navy with its lit top edge (`style.paint_overlay`)."""
    how = "pop"
    shadow_name = "menu"
    focus = True

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("whatif")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        box.setContentsMargins(round(16 * f), round(12 * f), round(12 * f), round(14 * f))
        box.setSpacing(round(6 * f))
        top = QHBoxLayout()
        self.heading = QLabel(strings.WHATIF_HEADING, self)
        self.heading.setObjectName("popeyebrow")
        top.addWidget(self.heading, 1)
        self.close_button = QToolButton(self)
        self.close_button.setText("✕")
        self.close_button.setToolTip(strings.WHATIF_CLOSE_TIP)
        self.close_button.setAccessibleName(strings.WHATIF_CLOSE_NAME)
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.close)
        top.addWidget(self.close_button)
        box.addLayout(top)
        self.line = QLabel(self)
        self.line.setObjectName("popband")
        self.line.setTextFormat(Qt.TextFormat.PlainText)
        self.line.setWordWrap(True)
        box.addWidget(self.line)
        self.words = QLabel(self)
        self.words.setObjectName("popline")
        self.words.setTextFormat(Qt.TextFormat.PlainText)
        self.words.setWordWrap(True)
        box.addWidget(self.words)
        buttons = QHBoxLayout()
        buttons.setSpacing(round(8 * f))
        self.put_back = QPushButton(strings.FIN_PUT_BACK, self)
        self.put_back.setToolTip(strings.WHATIF_PUT_BACK_TIP)
        self.journey = QPushButton(strings.WHATIF_JOURNEY, self)
        self.journey.setToolTip(strings.WHATIF_JOURNEY_TIP)
        buttons.addWidget(self.put_back)
        buttons.addWidget(self.journey)
        buttons.addStretch(1)
        box.addLayout(buttons)
        self.row = None
        self.anchor = None                          # the row's rect, in the parent's coordinates
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        parent.installEventFilter(self)
        self.hide()

    def show_for(self, row, anchor):
        """Open under `anchor` (the row's rect in the parent) for `row`, its numbers a dash until they come."""
        self.row, self.anchor = row, anchor
        self.setAccessibleName(strings.WHATIF_NAME.format(title=row.title))
        self.show_numbers(None)
        if not self.isVisible() and motion.opening_of(self) is None:
            self.place()
            self.open()
        else:
            self.place()

    def show_numbers(self, numbers):
        dash = strings.WHATIF_DASH
        if numbers is None:                         # still counting
            self.line.setText(strings.WHATIF_LINE.format(n=dash, pct=dash))
            self.words.setText("")
            self.words.setVisible(False)
        else:
            pct = dash if numbers["pct"] is None else strings.WHATIF_PCT.format(pct=numbers["pct"])
            n = dash if numbers["n"] is None else f"{numbers['n']:,}"
            self.line.setText(strings.WHATIF_LINE.format(n=n, pct=pct))
            if numbers["state"] == "none":
                text = strings.WHATIF_NONE
            elif numbers["state"] == "no-plan":
                text = strings.WHATIF_NO_PLAN
            elif not numbers["words"]:
                text = strings.WHATIF_NO_WORDS
            else:
                text = strings.WHATIF_WORDS.format(words=" · ".join(word_text(*w) for w in numbers["words"]))
            self.words.setText(text)
            self.words.setVisible(True)
        if self.isVisible():
            self.place()

    def place(self):
        """Under its row, its left on the row's text, kept inside the window."""
        p = self.parentWidget()
        self.ensurePolished()
        width = min(round(theme.size("tray", style.current()[1])), p.width() - 16)
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        a = self.anchor
        x = max(8, min(a.left() + 40, p.width() - width - 8)) if a is not None else 8
        y = a.bottom() + 2 if a is not None else 8
        if y + height > p.height() - 8 and a is not None:       # no room under it: above it
            y = max(8, a.top() - height - 2)
        self.setGeometry(x, y, width, height)

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)

    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["menu"])
        p.end()


class FinishedActions(QObject):
    """Finished's rows' actions, the card, the importer and Explorer's drops, on the window's thread. Made by the shell
    when it has a writer (W3.1a's `DragController` holds the toasts and Undo). `estimator(path, placed, callback)`: the
    arrivals worker's `estimate` (default: the window's worker, made on first use). The controller, the writer and the
    language are the window's as they are at each call (L1 S5): a library or language switch (P0's, which rebuilds
    `win.moves`) needs nothing rebuilt here, and never sends a write to the library left."""

    def __init__(self, win, estimator=None):
        super().__init__(win)
        self.win = win
        self.page = win.page_widgets["finished"]
        self.lst = self.page.list
        self.estimator = estimator
        self.on_mine = None                         # P4.1: (row) — *Mine* on a row with no cards (hidden until set)
        self.on_mine_too = None                     # P4.1: (row) — *Mine it too* (hidden until set)
        self.running = None                         # (the list's drag API: no drag of Finished's rows)
        self.relay = _Relay(self)
        q = Qt.ConnectionType.QueuedConnection
        self.relay.answer.connect(self._answered, q)
        self.relay.imported.connect(self._imported, q)
        self.page.on_put_back = self.put_back
        self.page.on_menu = self.menu
        self.page.on_import = self.pick
        self.page.importer.setVisible(True)
        self.lst.drag = self                        # Explorer's files on the list come here (`files_dropped`)
        self.lst.setAcceptDrops(True)
        self.tab = win.tab_buttons.get("finished")
        if self.tab is not None:                    # ... and on the Finished tab (lean 8)
            self.tab.setAcceptDrops(True)
            self.tab.installEventFilter(self)
        self.card = WhatIfCard(win.centralWidget())
        self.card.put_back.clicked.connect(self._card_put_back)
        self.card.journey.clicked.connect(self._card_journey)
        win.register_overlay(self.card)
        self._asking = None                         # (token, row, answers) of the card's estimates
        self.import_job = None
        self._landing = None                        # (the import handed to the writer, idle looks) until it lands
        self._land_until = 0.0                      # ... and the monotonic time `_land` stops looking (T2)
        self._land_timer = QTimer(self)
        self._land_timer.setSingleShot(True)
        self._land_timer.setInterval(LAND_MS)
        self._land_timer.timeout.connect(self._land)
        self.last_menu = None

    @property
    def moves(self):
        return self.win.moves

    @property
    def writer(self):
        return self.win.services.writer

    @property
    def language(self):
        return self.win.language

    def _refused(self):
        """No controller (no library open now), or the store can't be written (said in the bar): True."""
        moves = self.moves
        return moves is None or self.writer is None or moves.refused() is not None

    # --- the writes ----------------------------------------------------------------------------------------------- #
    def put_back(self, row):
        """*Put back*: to the top of Current and its cards back in the order (IK-1), its toast with Undo."""
        if self._refused():
            return None
        if self.card.isVisible() and self.card.row is not None and self.card.row.key == row.key:
            self.card.close()
        ids = drag.ids_of(row)
        return self.moves._give(drag.Ticket(strings.FIN_PUT_BACK_DONE.format(title=row.title), (row.key,), ids),
                                lambda t: self.writer.put_back(ids, label=t))

    def pin(self, row, on):
        """*Study its cards first* (on) ↔ *Done with its cards* (off)."""
        if self._refused():
            return None
        ids = drag.ids_of(row)
        text = (strings.FIN_PINNED if on else strings.FIN_UNPINNED).format(title=row.title)
        return self.moves._give(drag.Ticket(text, (row.key,), ids), lambda t: self.writer.pin(ids, on, label=t))

    def keep_cards(self, row, on):
        """*Put them back in the order* (on) ↔ *Leave its new cards out of your order* (off): the store's flag."""
        if self._refused():
            return None
        ids = drag.ids_of(row)
        text = (strings.FIN_CARDS_IN if on else strings.FIN_CARDS_OUT).format(title=row.title)
        return self.moves._give(drag.Ticket(text, (row.key,), ids), lambda t: self.writer.keep_cards(ids, on, label=t))

    def open_folder(self, row):
        """*Open its folder* (N3: `windows.open_url`), looked for on a worker first (a drive may be slow or gone)."""
        path = folder_of(self.language, row)

        def found(there):
            if there:
                windows.open_url(path)
            else:
                self._say(strings.FIN_NO_FOLDER.format(title=row.title))
        if path is None:
            found(False)
            return
        bridge.run_in_worker(os.path.isdir, path, then=found, failed=lambda _info: found(False))

    # --- ⋯ ------------------------------------------------------------------------------------------------------------ #
    def menu_entries(self, row):
        """⋯'s entries for a Finished row, in order: [(name, label, tip, enabled, children)] — `children` the
        submenu's entries in the same shape (or None)."""
        writer = self.writer
        writable = writer is not None and self.moves is not None and writer.can_write()
        reason = None
        if not writable:
            raw = (writer.reason() if writer is not None else None) or ""
            reason = strings.FIN_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)

        def entry(name, key=None, label=None, writes=True, children=None):
            words, tip = strings.FIN_MENU[key or name]
            ok = writable or not writes
            return (name, label or words, tip if ok else reason, ok, children)
        out = [entry("what-if", writes=False), entry("put-back"),
               entry("unpin") if row.studying else entry("pin")]
        cards = sum(e.cards or 0 for e in row.episodes)
        if cards:
            label = strings.FIN_MENU["cards"][0].format(n=f"{cards:,}")
            out.append(entry("cards", label=label, writes=False,
                             children=[entry("cards-in") if row.cards_out else entry("cards-out")]))
            if self.on_mine_too is not None:
                out.append(entry("mine-too"))
        else:
            out.append(entry("cards", key="cards-none", writes=False,
                             children=[entry("cards-in") if row.cards_out else entry("cards-out")]))
            if self.on_mine is not None:
                out.append(entry("mine"))
        out.append(entry("folder", writes=False))
        return out

    def menu(self, row, at):
        """⋯: a plain menu in the theme's style (Esc closes it), its entries' tips shown."""
        m = QMenu(self.lst)
        m.aboutToHide.connect(m.deleteLater)            # one menu per click, gone once it closes (L1 N7)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        m.setAccessibleName(strings.FIN_MENU_NAME.format(title=row.title))
        for name, label, tip, ok, children in self.menu_entries(row):
            if children is not None:
                sub = m.addMenu(label)
                sub.setObjectName("rowmenu")
                sub.setToolTipsVisible(True)
                sub.menuAction().setToolTip(tip)
                for c_name, c_label, c_tip, c_ok, _c in children:
                    self._action(sub, row, c_name, c_label, c_tip, c_ok)
                continue
            self._action(m, row, name, label, tip, ok)
        self.last_menu = m
        m.popup(at)
        return m

    def _action(self, menu, row, name, label, tip, ok):
        act = QAction(label, menu)
        act.setToolTip(tip)
        act.setEnabled(ok)
        act.triggered.connect(lambda _c=False, n=name: self.menu_pick(row, n))
        menu.addAction(act)
        return act

    def menu_pick(self, row, name):
        if name == "what-if":
            self.what_if(row)
        elif name == "put-back":
            self.put_back(row)
        elif name in ("pin", "unpin"):
            self.pin(row, name == "pin")
        elif name in ("cards-in", "cards-out"):
            self.keep_cards(row, name == "cards-in")
        elif name == "folder":
            self.open_folder(row)
        elif name == "mine" and self.on_mine is not None:
            self.on_mine(row)
        elif name == "mine-too" and self.on_mine_too is not None:
            self.on_mine_too(row)

    # --- What if I added it back? --------------------------------------------------------------------------------- #
    def what_if(self, row):
        """The card under the row at once (a dash), then the worker's answers for its files (IK-5)."""
        model = self.lst.model()
        i = next((n for n, e in enumerate(model.entries) if getattr(e[1], "key", None) == row.key), None)
        parent = self.card.parentWidget()
        anchor = None
        if i is not None:
            r = self.lst.visualRect(model.index(i, 0))
            top_left = self.lst.viewport().mapTo(parent, r.topLeft())
            anchor = r.translated(top_left - r.topLeft())
        self.card.show_for(row, anchor)
        files = file_paths(self.language, row)
        token = object()
        self._asking = (token, row, [None] * len(files), set())
        if not files:
            self.card.show_numbers(what_if_numbers([]))
            return
        ask = self.estimator or self._worker_estimate
        for k, (path, _rel) in enumerate(files):
            try:
                ask(path, placed_before(files, k),
                    lambda answer, k=k, token=token: self.relay.answer.emit(token, (k, answer)))
            except Exception as e:                   # no worker: that file counts as no answer
                self.relay.answer.emit(token, (k, {"error": str(e)}))

    def _worker_estimate(self, path, placed, callback):
        """The window's arrivals worker (one per language, shared with New arrivals: `services.arrivals_worker`)."""
        return self.win.arrivals_worker().estimate(path, placed=placed, callback=callback)    # IK-L2-2: one slot

    def _answered(self, token, answer):
        asking = self._asking
        if asking is None or asking[0] is not token:
            return                                  # an older card's answer
        k, value = answer
        _token, _row, answers, got = asking
        answers[k] = value
        got.add(k)
        if len(got) == len(answers) and self.card.isVisible():
            self.card.show_numbers(what_if_numbers(answers))

    def _card_put_back(self):
        row = self.card.row
        self.card.close()
        if row is not None:
            self.put_back(row)

    def _card_journey(self):
        self.card.close()
        self.win._open_journey(asked=True)

    # --- Add what you finished before… --------------------------------------------------------------------------- #
    def pick(self):
        """The heading's button: its menu (*Files…* · *A folder…*) — or, while an import runs, *Stop adding*."""
        if self.import_job is not None:
            self.import_job.cancel()
            return None
        m = QMenu(self.page.importer)
        m.aboutToHide.connect(m.deleteLater)            # (L1 N7)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        for (label, tip), how in ((strings.FIN_IMPORT_FILES, "files"), (strings.FIN_IMPORT_FOLDER, "folder")):
            act = QAction(label, m)
            act.setToolTip(tip)
            act.triggered.connect(lambda _c=False, h=how: self._choose(h))
            m.addAction(act)
        self.last_menu = m
        b = self.page.importer
        m.popup(b.mapToGlobal(b.rect().bottomLeft()))
        return m

    def _choose(self, how):
        if how == "files":
            paths, _f = QFileDialog.getOpenFileNames(self.page, strings.FIN_IMPORT_PICK, "")
        else:
            folder = QFileDialog.getExistingDirectory(self.page, strings.FIN_IMPORT_PICK, "")
            paths = [folder] if folder else []
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths):
        """Files or folders from anywhere into Finished, dated *Earlier* (`ImportJob`). -> the job, or None. A file or
        folder already in the library (its data folder) is left out with a line: finishing it is its row's (the drag,
        ⋯) with the choice for its cards, never an import dated *Earlier* (L1 N5)."""
        paths = [os.path.normpath(p) for p in paths if p]
        if not paths or self.import_job is not None or self._refused():
            return None
        from app.library_store import library_rel
        data = path_utils.get_data_path(self.language)
        mine = [p for p in paths if library_rel(data, p) is not None]
        if mine:
            self._say(strings.FIN_IMPORT_IN_LIBRARY.format(name=os.path.basename(mine[0]))
                               if len(mine) == 1 else strings.FIN_IMPORT_IN_LIBRARY_N.format(n=f"{len(mine):,}"))
            paths = [p for p in paths if p not in mine]
            if not paths:
                return None
        from app.services import finished_import
        ticket = _ImportTicket("")
        job = finished_import.ImportJob(self.language, paths, _TicketWriter(self.writer, ticket),
                                        self.win.services.registry, on_done=self.relay.imported.emit)
        job.ticket = ticket
        if job.start() is None:
            self.moves.refused()
            return None
        self.moves.tickets.append(ticket)           # Ctrl+Z meanwhile takes this import back as it lands (L1 N6)
        self.import_job = job
        self._show_importing(True)
        return job

    def _show_importing(self, on):
        b = self.page.importer
        b.setText(strings.FIN_IMPORT_STOP if on else strings.FIN_IMPORT)
        b.setToolTip(strings.FIN_IMPORT_STOP_TIP if on else strings.FIN_IMPORT_TIP)
        b.setAccessibleName(b.text())

    def _imported(self, job):
        if job is self.import_job:
            self.import_job = None
            self._show_importing(False)
        outcome = job.outcome
        if outcome in ("imported", "pending"):      # (pending: Stop pressed as the store saved it — the writer's)
            self._landing = job                     # its toast once the writer answers (`_land`)
            self._land_until = time.monotonic() + LAND_DEADLINE_S
            self._land()
            return
        self._settle(job.ticket)
        if outcome == "nothing":
            self._say(strings.FIN_IMPORT_NOTHING)
        elif outcome == "cancelled":
            self._say(strings.FIN_IMPORT_STOPPED)
        elif outcome == "stopped":                  # T2: the writer stopped first — its journal lands it next start
            self._say(strings.FIN_IMPORT_LATER)
        else:
            writer = self.writer
            why = (job.job.message if job.job is not None else None) or \
                (writer.reason() if writer is not None else None) or outcome
            self._say(strings.FIN_IMPORT_FAILED.format(why=why))

    def _land(self):
        """The import handed to the writer, decided from the writer's own answer for it (L1 S6) — never from how long
        it took (a busy store, a slow journal): *Added N to Finished* with Undo once its change reaches the toast (N
        what the store added or moved in), *Nothing new to add* when it saved nothing (everything was in Finished
        already), the store's reason when it refused or failed; nothing when Ctrl+Z took it back as it landed."""
        job = self._landing
        if job is None:
            return
        ticket, got = job.ticket, job.writer.answer
        if got is None or (got.get("saved") and got.get("changed") and ticket.change is None):
            if (got is None and job.writer.stopped()) or time.monotonic() > self._land_until:
                self._landing = None                # T2: no answer will come (the writer stopped), or none in time:
                self._settle(ticket)                # a line, never a poll for ever
                self._say(strings.FIN_IMPORT_LATER)
                return
            self._land_timer.start()                # not answered yet, or its change on its way to the controller
            return
        self._landing = None
        self._settle(ticket)
        if not got.get("saved"):
            why = got.get("refused") or got.get("failed") or (self.writer.reason() if self.writer else None) or ""
            self._say(strings.FIN_IMPORT_FAILED.format(why=why))
            return
        if not got.get("changed"):
            self._say(strings.FIN_IMPORT_NOTHING)
            return
        if ticket.taken_back or self.moves is None:
            return
        change = ticket.change
        n = len(getattr(change, "added", None) or ()) + len(getattr(change, "items", None) or ()) or len(job.paths)
        ticket.text = strings.FIN_IMPORTED_ONE.format(name=os.path.basename(job.paths[0])) \
            if n == 1 and len(job.paths) == 1 else strings.FIN_IMPORTED.format(n=f"{n:,}")
        self.moves._toast(ticket)

    def _say(self, text):
        moves = self.moves
        if moves is not None:
            moves.say(text)
        else:
            windows.say_in_bar(self.win, text)

    def _settle(self, ticket):
        moves = self.moves
        if moves is not None:
            moves._settle_ticket(ticket)            # out of the controller's waiting tickets (a no-op once saved)

    # --- Explorer's files: on the list (its drag API) and on the tab (a filter) ----------------------------------- #
    @staticmethod
    def _files(event):
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        return [os.path.normpath(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]

    def files_wanted(self, event):
        return bool(self._files(event)) and self.import_job is None

    def files_dropped(self, event):
        return self.import_paths(self._files(event)) is not None

    def eventFilter(self, obj, event):
        if obj is self.tab:
            et = event.type()
            if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if self.files_wanted(event):
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True
            if et == QEvent.Type.Drop:
                if self.files_dropped(event):
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True
        return False
