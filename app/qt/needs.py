"""*Needs you* in the window (W3.2 Q5; the RUNBOOK's §1 *Needs you* row, §5 leans 4–6, §5a IK-2, IK-3, IK-8, N8–N10;
the window's spec A2 #69–70, G4–G7, 06 E8, E10, E11, P1.2-1).

- **The tab's stone** (`stone`, `paint_stone`): the cracked amber stone (ref-extract row 115, `rough3`; flat) with the
  number of unseen entries, drawn once per size × dpr; the shell's `TabButton` paints it in place of a badge. The tab
  is shown only while something waits; empty, it hides and the window goes back to Current (A2 #70).
- **The entries** are `app/services/needs.entries`' (S3), worked out on a worker (`NeedsYou.refresh`) from the reader's
  view, the bar's failures, Connect's record, the seen file, the offline roots and the store's rename questions —
  never on the window's thread; an answer equal to the last one repaints nothing (N9, S19), and a view whose rows
  hold the same things in another order (a move) works nothing out (C1).
- **The cards** (`NeedsCards`): one per entry in S3's order, a 3 px amber left edge, its words and its buttons. Each
  action name maps to one call (`NeedsYou.act`); a name with no callable (P4.1's *Mine the text only*, *Make their
  cards*; Connect's when Connect isn't installed; the writer's with no library) is hidden. Writes go through the
  window's writer (`moves.Writer`: `relink`, `its_new`, `link_video`, `remove`) by the drag controller's tickets, so a
  toast's Undo and Ctrl+Z take them back as they take back a move; Connect's (`actions.mine_anyway`,
  `hato.backfill`, `status.dismiss`) and the seen file's (*Keep its words*, *Leave them*) run on a worker.
- **Remove** asks first, naming the count (`confirm.ask`: Esc, Back, a click outside are No); an offline root never
  offers it and *Remove all* never counts its files (IK-8).
- **Opening the page** marks its entries seen (`needs.mark_all_seen`, on a worker): they stay listed and stop
  counting (P1.2-1).
"""
import os

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from app import path_utils, theme
from app.qt import bridge, strings, style, toast
from app.services import needs as service
from app.services import view_rows

# --- the stone (ref-extract row 115: viewBox 24) ------------------------------------------------------------------- #
_OUTLINE = ((2.4, 10), (6.2, 3.4), (13, 1.4), (20.6, 5.2), (23, 13.2), (19.4, 20.6), (11, 23), (4, 19.6))
_TOP = ((6.2, 3.4), (13, 1.4), (20.6, 5.2), (14.6, 9), (8.2, 8.6))
_LEFT = ((2.4, 10), (8.2, 8.6), (14.6, 9), (12.4, 14), (5, 15.4))
_CRACK = ((13, 1.6), (11.6, 4.6), (13.4, 6.6))
_STONES = {}                                # (size, dpr) -> QPixmap: drawn once each
LINES_SHOWN = 12                            # a card's per-file lines shown (*and N more*: a 300-file show is no
#                                             1,000 widgets; the card's own answers still count every line — IK-L1-4)
drawn = [0]                                 # stones drawn (tests)


def stone_size(factor):
    return round(theme.NEEDS_STONE_PX * factor)


def _poly(points):
    return QPolygonF([QPointF(x, y) for x, y in points])


def stone(size, dpr):
    """The stone without its number, `size` px square at `dpr` — drawn once per (size, dpr)."""
    key = (int(size), round(float(dpr), 3))
    pix = _STONES.get(key)
    if pix is not None:
        return pix
    k = theme.NEEDS_STONE
    pix = QPixmap(max(1, round(key[0] * key[1])), max(1, round(key[0] * key[1])))
    pix.setDevicePixelRatio(key[1])
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = key[0] / 24.0
    p.scale(s, s)
    p.setPen(QPen(style.qcolor(k["stroke"]), 1.0))
    p.setBrush(style.qcolor(k["fill"]))
    p.drawPolygon(_poly(_OUTLINE))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(style.qcolor(k["top"]))
    p.drawPolygon(_poly(_TOP))
    p.setOpacity(k["left-alpha"])
    p.setBrush(style.qcolor(k["left"]))
    p.drawPolygon(_poly(_LEFT))
    p.setOpacity(k["crack-alpha"])
    crack = QPainterPath(QPointF(*_CRACK[0]))
    for pt in _CRACK[1:]:
        crack.lineTo(QPointF(*pt))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(style.qcolor(k["crack"]), 0.8))
    p.drawPath(crack)
    p.end()
    _STONES[key] = pix
    drawn[0] += 1
    return pix


def paint_stone(p, x, line, size, number, font):
    """The stone at `x`, centred on the name's midline `line`, its number on it (warn, a dark shade 1 px under it:
    the reference's shadow, flat)."""
    from PyQt6.QtGui import QFontMetricsF
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    top = round((line - size / 2) * dpr) / dpr
    p.drawPixmap(QPointF(x, top), stone(size, dpr))
    text = str(number)
    p.setFont(font)
    fm = QFontMetricsF(font)
    tx = x + (size - fm.horizontalAdvance(text)) / 2
    ty = round((line + fm.capHeight() / 2) * dpr) / dpr
    p.setPen(style.qcolor(theme.NEEDS_STONE["number-shade"]))
    p.drawText(QPointF(tx, ty + 1), text)
    p.setPen(style.qcolor(style.colours()["warn"]))
    p.drawText(QPointF(tx, ty), text)


# --- the cards ----------------------------------------------------------------------------------------------------- #
class _Card(QWidget):
    """One entry's card: the stylesheet's `needscard` ground, a 3 px amber left edge painted over it."""

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        r = theme.RADII["r"]
        path.addRoundedRect(QRectF(self.rect()), r, r)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 3, self.height()), style.qcolor(style.colours()["warn"]))
        p.end()


def _label(text, name, parent, wrap=True):
    lab = QLabel(text, parent)
    lab.setObjectName(name)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setWordWrap(wrap)
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return lab


class NeedsCards(QWidget):
    """The page's cards, in the entries' order; a card is rebuilt only when its own entry (or its find results, or its
    look running) changed (S19), and only while the page shows (C1: entries given while it is hidden are built when it
    shows, or when a card is asked for). `action(name, entry, line)`: a button pressed (`line` None for the card's own)."""
    action = pyqtSignal(str, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("needscards")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(theme.SPACING["settings-card-gap"])
        self.cards = {}                         # key -> (signature, widget)
        self.order = []
        self.builds = 0                         # cards built (tests: S19)
        self.epoch = 0                          # bumped when the callables change (`NeedsYou.rewire`): every card again
        self.shown = lambda name, entry, line=None: True
        self._owed = None                       # C1: the entries given while the page is hidden, built when it shows
        self.box.addStretch(1)

    def show_entries(self, entries, found=None, looking=()):
        if not self.isVisible():
            self._owed = (entries, found, looking)
            return                              # C1: no card is made under the style sheet for a page nobody sees
        self._owed = None
        self._build(entries, found, looking)

    def showEvent(self, event):
        super().showEvent(event)
        self.flush()

    def flush(self):
        """The cards the entries given while hidden owe, built now (the page shown, or a card asked for)."""
        owed, self._owed = self._owed, None
        if owed is not None:
            self._build(*owed)

    def _build(self, entries, found, looking):
        found = found or {}
        keep, order = {}, []
        for e in entries:
            sig = (e, found.get(e.key), e.key in looking, self.epoch)
            old = self.cards.get(e.key)
            if old is not None and old[0] == sig:
                keep[e.key] = old
            else:
                if old is not None:
                    old[1].setParent(None)
                    old[1].deleteLater()
                keep[e.key] = (sig, self._card(e, found.get(e.key), e.key in looking))
                self.builds += 1
            order.append(e.key)
        for key, (_sig, w) in self.cards.items():
            if key not in keep:
                w.setParent(None)
                w.deleteLater()
        self.cards = keep
        if order != self.order:
            for i, key in enumerate(order):
                w = self.cards[key][1]
                self.box.removeWidget(w)
                self.box.insertWidget(i, w)
            self.order = order
        for key in order:
            w = self.cards[key][1]
            if w.isHidden():
                w.show()

    def card(self, key):
        self.flush()
        got = self.cards.get(key)
        return got[1] if got is not None else None

    def buttons(self, key=None):
        """The shown buttons (of one card, or all) -> [QPushButton]."""
        self.flush()
        cards = [self.card(key)] if key is not None else [w for _s, w in self.cards.values()]
        return [b for c in cards if c is not None for b in c.findChildren(QPushButton)]

    def _button(self, parent, name, entry, line=None, label=None):
        text, tip = strings.NEEDS_ACTIONS[name]
        b = QPushButton(label or text, parent)
        b.setProperty("size", "sm")
        b.setProperty("action", name)
        b.setToolTip(tip)
        b.setAccessibleName(label or text)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c=False, n=name, e=entry, ln=line: self.action.emit(n, e, ln))
        return b

    def _card(self, e, results, looking):
        card = style.styled(_Card(self), "needscard")
        card.setProperty("kind", e.kind)
        card.setAccessibleName(e.title)
        f = theme.text_factor(style.current()[1])
        pad = [round(v * f) for v in toast.PAD]
        pad[0] += 3                                 # clear of the amber edge
        box = QVBoxLayout(card)
        box.setContentsMargins(*pad)
        box.setSpacing(round(6 * f))
        box.addWidget(_label(e.title, "needstitle", card))
        if e.say:
            box.addWidget(_label(e.say, "sheetline", card))
        by_line = dict(zip((ln.key for ln in e.lines), results or ())) if results else {}
        for ln in e.lines[:LINES_SHOWN]:
            row = QHBoxLayout()
            row.setSpacing(round(8 * f))
            words = QVBoxLayout()
            words.setSpacing(0)
            words.addWidget(_label(ln.text, "sheetline", card))
            hit = by_line.get(ln.key)
            if hit is not None:
                why = _label(hit[2], "needswhy", card)
                why.setProperty("found", hit[1] is not None)
                words.addWidget(why)
            row.addLayout(words, 1)
            names = list(ln.actions)
            if e.kind == service.NO_VIDEO and hit is not None and hit[1] is None:
                names.append("remove_episode")       # G7: a line that found nothing can leave the library
            for name in names:
                if name == "choose_video" and hit is not None and hit[1] is not None:
                    continue                          # found: *Link these* takes it
                if self.shown(name, e, ln):
                    row.addWidget(self._button(card, name, e, ln))
            box.addLayout(row)
        if len(e.lines) > LINES_SHOWN:
            box.addWidget(_label(strings.NEEDS_MORE_LINES.format(n=f"{len(e.lines) - LINES_SHOWN:,}"), "sheetline",
                                 card))
        acts = QHBoxLayout()
        acts.setSpacing(round(8 * f))
        labels = (e.data or {}).get("labels") or {}
        for name in e.actions:
            if not self.shown(name, e):
                continue
            label = labels.get(name)
            if name == "link_these":
                n = sum(1 for _l, path, _w in results or () if path is not None)
                if not n:
                    continue                          # nothing found yet: nothing to link
                label = strings.NEEDS_ACTIONS["link_these"][0].format(n=n)
            if name == "find_videos" and looking:
                label = strings.NEEDS_LOOKING
            b = self._button(card, name, e, None, label)
            if name in ("find_videos", "find_all") and looking:
                b.setEnabled(False)
            acts.addWidget(b)
        acts.addStretch(1)
        box.addLayout(acts)
        return card


# --- the page's controller ---------------------------------------------------------------------------------------- #
def _connect_callable(module, name):
    """Connect's call for an action, or None (Connect not installed: its button hidden)."""
    try:
        mod = __import__(f"app.connect.{module}", fromlist=[name])
        return getattr(mod, name, None)
    except Exception:
        return None


def _default_asks(opener):
    """9a's questions through a store handle of this worker's own (closed after: a pool thread keeps none)."""
    if opener is None or getattr(opener, "mode", None) != "store" or not hasattr(opener, "handle"):
        return ()
    try:
        store = opener.handle()
        if store is None or not hasattr(store, "rename_asks"):
            return ()
        return service.asks_of(store)
    except Exception:
        return ()
    finally:
        close = getattr(opener, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass


def match_folder(folder, lines):
    """*Choose a folder…* (a worker): each gone line's file in `folder` by its own name, else the one file there with
    its extension and its episode number -> [(line, path)]."""
    try:
        with os.scandir(folder) as found:
            names = sorted(e.name for e in found if e.is_file())
    except OSError:
        return []
    folded = {n.casefold(): n for n in names}
    out = []
    for ln in lines:
        base = (ln.rel_path or "").replace("\\", "/").rsplit("/", 1)[-1]
        hit = folded.get(base.casefold())
        if hit is None and ln.number is not None:
            ext = os.path.splitext(base)[1].casefold()
            same = [n for n in names if os.path.splitext(n)[1].casefold() == ext
                    and view_rows.episode_number(n) == ln.number]
            hit = same[0] if len(same) == 1 else None
        if hit is not None:
            out.append((ln, os.path.join(folder, hit)))
    return out


class NeedsYou(QObject):
    """The page's entries and their actions, for one window (`win`: the shell)."""
    changed = pyqtSignal()                       # new entries painted (the tab's count follows)

    def __init__(self, win, page, language):
        super().__init__(win)
        self.win = win
        self.page = page
        self.language = language
        self.entries = ()
        self.found = {}                          # entry key -> find_videos' results
        self.looking = set()
        self.failures = ()
        self.view = None
        self.data_dir = None                     # None: the language's data folder (looked up on the worker)
        self.connect_line = None
        self.gathers = 0                         # entries worked out (tests: N9)
        self._asked = 0
        self._running = False
        self._again = False
        reader = getattr(win.services, "library", None)
        opener = getattr(reader, "opener", None)
        # what the entries are read from, each on a worker (tests replace them)
        self.read_connect = service.read_connect
        self.read_asks = lambda: _default_asks(opener)
        self.find_offline = service.find_offline
        self.read_settings = win.services.settings.get
        # the pickers (the system's own dialogs; tests replace them)
        self.pick_file = lambda title, folder: QFileDialog.getOpenFileName(self.win, title, folder)[0]
        self.pick_folder = lambda title, folder: QFileDialog.getExistingDirectory(self.win, title, folder)
        self.pick_save = lambda title, name: QFileDialog.getSaveFileName(self.win, title, name, "Zip (*.zip)")[0]
        # P4.1's hooks (`mine_text_only(entry, line)`, `make_cards(entry)`): hidden until set
        self.hooks = {}
        self.connect_calls = {"mine_anyway": _connect_callable("actions", "mine_anyway"),
                              "ask_hato": _connect_callable("hato", "backfill"),
                              "dismiss": _connect_callable("status", "dismiss"),
                              "save_logs": _connect_callable("status", "save_logs"),
                              "kick": _connect_callable("kick", "kick")}
        self.cards = page.cards
        self.cards.shown = self.available
        self.cards.action.connect(self.act)

    # --- what comes in ------------------------------------------------------------------------------------------- #
    def view_in(self, view):
        old, self.view = self.view, view
        if view is None:
            return
        if old is not None and old.mode == view.mode and old.loading == view.loading:
            if _same(old.rows, view.rows):
                return                               # another tab's change: these entries can't have moved
            if not self._running and _reads_same(old.rows, view.rows) and self._in_order(view.rows):
                return                               # C1: a reorder (a move's four views) — nothing they read moved
        self.refresh()

    def _in_order(self, rows):
        """Whether the cards that follow Current's order (a show's *file gone*, *no video*) stand in `rows`' order."""
        shown = list(dict.fromkeys((e.data or {}).get("group") for e in self.entries
                                   if e.kind in (service.GONE, service.NO_VIDEO)))
        if len(shown) < 2:
            return True
        wanted = set(shown)
        return [g for g in dict.fromkeys(service._group(r) for r in rows) if g in wanted] == shown

    def failures_in(self, failures):
        failures = tuple(failures or ())
        if failures == self.failures:
            return                                   # an empty tick: nothing to work out, nothing repainted (N9)
        self.failures = failures
        self.refresh()

    def connect_in(self, line):
        if line == self.connect_line:
            return
        self.connect_line = line
        self.refresh()

    def counts(self):
        """(listed, unseen) for the tab: the entries but the bulk answer, and the unseen ones (P1.2-1)."""
        return sum(1 for e in self.entries if e.kind != service.BULK), service.badge(self.entries)

    def opened(self):
        """The page was shown: its unseen entries stop counting (still listed): the seen file and Connect's
        `seen_at`, on a worker; read again only when something was marked."""
        unseen = [e for e in self.entries if e.unseen and e.kind != service.FAILURE]
        if not unseen:
            return
        lang = self.language
        bridge.run_in_worker(service.mark_all_seen, lang, tuple(unseen),
                             then=lambda n: (n[0] or n[1]) and self.refresh(), failed=self._failed)

    # --- working the entries out (a worker) ----------------------------------------------------------------------- #
    def refresh(self):
        if self._running:
            self._again = True
            return
        if self.view is None:
            return
        self._running = True
        self._asked += 1
        asked = self._asked
        view, failures, lang, data_dir = self.view, self.failures, self.language, self.data_dir
        read_connect, read_asks, find_offline, read_settings = (self.read_connect, self.read_asks,
                                                                 self.find_offline, self.read_settings)

        def gather():
            settings = read_settings() or {}
            connect = read_connect(lang) if settings.get("connect_enabled") else None
            rels = [e.rel_path for r in view.rows for e in r.episodes if e.rel_path] if view.mode == "store" else []
            roots = find_offline(lang, rels, data_dir) if rels else []
            asks = read_asks()
            try:                                    # W3.2 H (W5): the keys whose trouble is gone leave the seen file,
                service.prune(lang, view, offline_roots=roots, connect=connect,   # judged by what was read (no ask
                              asks=asks or None)                                 # read: a failed read looks the same)
            except Exception as e:                  # (a file that can't be read is left as it is: the gather goes on)
                print(f"Needs you: the seen file wasn't pruned: {e!r}")
            out = service.entries(view, failures, connect, service.read_seen(lang), roots, asks,
                                  service.read_answered(lang))
            return asked, tuple(out)
        bridge.run_in_worker(gather, then=self._got, failed=self._gather_failed)

    def _gather_failed(self, info):
        self._running = False
        self._failed(info)
        if self._again:
            self._again = False
            self.refresh()

    def _got(self, answer):
        asked, entries = answer
        self._running = False
        if not self._alive():
            return
        self.gathers += 1
        if self._again:
            self._again = False
            self.refresh()
        if asked != self._asked:
            return
        if entries == self.entries:
            return                                   # the same entries: nothing repainted (N9)
        self.entries = entries
        keys = {e.key for e in entries}
        self.found = {k: v for k, v in self.found.items() if k in keys}
        self._paint()
        if self.win.current_tab() == "needs" and self.win.isActiveWindow():
            self.opened()                            # looked at as it came

    def _paint(self):
        if not self._alive():
            return
        self.page.show_entries(self.entries, self.found, self.looking)
        self.changed.emit()

    def rewire(self):
        """The callables changed (P4.1 set a hook, Connect came or went): every card built again with its buttons."""
        self.cards.epoch += 1
        self._paint()

    def _alive(self):
        from PyQt6 import sip
        return not sip.isdeleted(self.win) and not sip.isdeleted(self.cards)

    # --- the actions ------------------------------------------------------------------------------------------- #
    WRITES = frozenset(("choose_file", "choose_folder", "choose_video", "link_these", "remove", "remove_episode",
                        "remove_all", "this_one", "its_new"))

    def available(self, name, entry=None, line=None):
        """Whether `name` has a callable here (its button shown)."""
        if name in service.WIRED_LATER:
            return name in self.hooks
        if name in self.WRITES:
            return getattr(self.win, "moves", None) is not None
        if name in ("mine_anyway", "ask_hato", "dismiss", "save_logs"):
            return self.connect_calls.get(name) is not None
        return True

    def act(self, name, entry, line=None):
        try:
            getattr(self, "_do_" + name)(entry, line)
        except Exception as e:                       # a slot's escape never takes the window down
            self._failed((type(e), e, None))

    def _say(self, text):
        if self._alive():                            # (an answer coming in as the window closes says nothing)
            self.win.say(text)

    def _failed(self, info):
        from app.qt import applog
        applog.log("needs", f"{info[0].__name__ if info and info[0] else ''}: {info[1] if info else ''}")
        self._say(strings.NEEDS_FAILED.format(why=info[1] if info else ""))

    def _data(self):
        return self.data_dir or path_utils.get_data_path(self.language)

    def _give(self, text, ids, command, toast_it=True):
        """A write through the drag controller's tickets (its toast's Undo, Ctrl+Z) -> its number, or None."""
        from app.qt import drag
        moves = self.win.moves
        if moves is None or moves.refused() is not None:
            return None
        return moves._give(drag.Ticket(text, (), ids), command, toast=toast_it)

    def _offline_ids(self):
        return {i for e in self.entries if e.kind == service.OFFLINE for i in (e.data or {}).get("item_ids") or ()}

    # find / link (IK-2: a video never goes through relink)
    def _do_find_videos(self, entry, _line):
        self._look({entry.key}, lambda lang, settings, data: {entry.key: service.find_videos(lang, entry, settings,
                                                                                              data)})

    def _do_find_all(self, _entry, _line):
        cards = tuple(e for e in self.entries if e.kind == service.NO_VIDEO)
        self._look({e.key for e in cards}, lambda lang, settings, data: service.find_all(lang, cards, settings, data))

    def _look(self, keys, fn):
        self.looking |= keys
        self._paint()
        lang, data, read_settings = self.language, self.data_dir, self.read_settings

        def look():
            return fn(lang, read_settings() or {}, data or path_utils.get_data_path(lang))

        def done(results):
            if not self._alive():
                return
            self.looking -= keys
            self.found.update(results)
            self._paint()

        def failed(info):
            self.looking -= keys
            self._paint()
            self._say(strings.NEEDS_LOOK_FAILED.format(why=info[1]))
        bridge.run_in_worker(look, then=done, failed=failed)

    def _do_link_these(self, entry, _line):
        results = self.found.get(entry.key) or ()
        pairs = [(ln, path) for ln, (_label, path, _why) in zip(entry.lines, results) if path is not None]
        if not pairs:
            return
        writer = self.win.services.writer
        for ln, path in pairs:
            self._give(ln.label, (ln.item_id,), lambda t, i=ln.item_id, p=path: writer.link_video(i, p, label=t),
                       toast_it=False)
        self.win.toasts.show(strings.NEEDS_LINKING_ONE.format(label=pairs[0][0].label) if len(pairs) == 1 else
                             strings.NEEDS_LINKING.format(n=len(pairs)))
        self.found.pop(entry.key, None)
        self._paint()

    def _do_choose_video(self, entry, line):
        folder = os.path.join(self._data(), *[p for p in (entry.data or {}).get("folder", "").split("/") if p])
        path = self.pick_file(strings.NEEDS_CHOOSE_VIDEO_TITLE.format(label=line.label), folder)
        if not path:
            return
        writer = self.win.services.writer
        self._give(line.label, (line.item_id,), lambda t: writer.link_video(line.item_id, path, label=t),
                   toast_it=False)
        self.win.toasts.show(strings.NEEDS_LINKING_ONE.format(label=line.label))

    # a file gone: point it at its file (relink), keep its words, or remove it
    def _do_choose_file(self, entry, line):
        folder = os.path.join(self._data(), *[p for p in (entry.data or {}).get("folder", "").split("/") if p])
        path = self.pick_file(strings.NEEDS_CHOOSE_FILE_TITLE.format(label=line.label), folder)
        if not path:
            return
        writer = self.win.services.writer
        self._give(strings.NEEDS_RELINKED.format(label=line.label), (line.item_id,),
                   lambda t: writer.relink(line.item_id, path, label=t))

    def _do_choose_folder(self, entry, _line):
        data = self._data()
        start = os.path.join(data, *[p for p in (entry.data or {}).get("folder", "").split("/") if p])
        lines = tuple(entry.lines)

        def pick(there):                            # looked for on a worker: a drive may be offline (IK-L1-5)
            if not self._alive():
                return
            folder = self.pick_folder(strings.NEEDS_CHOOSE_FOLDER_TITLE, start if there else data)
            if not folder:
                return
            bridge.run_in_worker(match_folder, folder, lines, then=lambda pairs: self._relink_all(pairs, len(lines)),
                                 failed=self._failed)
        bridge.run_in_worker(os.path.isdir, start, then=pick, failed=lambda _info: pick(False))

    def _relink_all(self, pairs, n):
        if not pairs:
            self._say(strings.NEEDS_RELINKED_NONE)
            return
        writer = self.win.services.writer
        for ln, path in pairs:
            self._give(ln.label, (ln.item_id,), lambda t, i=ln.item_id, p=path: writer.relink(i, p, label=t),
                       toast_it=False)
        self.win.toasts.show(strings.NEEDS_RELINKED_N.format(k=len(pairs), n=n))

    def _do_keep_words(self, entry, line):
        self._answer(service.answer_keys(line if line is not None else entry))

    def _do_keep_all(self, entry, _line):
        self._answer(service.answer_keys(entry))

    def _do_leave_them(self, entry, _line):
        self._answer(service.answer_keys(entry))

    def _answer(self, keys):
        lang = self.language

        def done(_n):
            if self._alive():
                self.win.toasts.show(strings.NEEDS_KEPT)
                self.refresh()
        bridge.run_in_worker(service.answer, lang, list(keys), then=done, failed=self._failed)

    def _do_remove(self, entry, line):
        if line is not None:
            self._remove([line.item_id], line.label)
        else:
            ids = list((entry.data or {}).get("item_ids") or ())
            self._remove(ids, entry.lines[0].label if len(ids) == 1 and entry.lines else None)

    def _do_remove_episode(self, entry, line):
        self._remove([line.item_id], line.label)

    def _do_remove_all(self, entry, _line):
        self._remove(list((entry.data or {}).get("item_ids") or ()), None)

    def _remove(self, ids, name):
        """*Remove…*: asked first, naming the count (Esc, Back, a click outside: No); never a file under an offline
        root (IK-8); the trash (30 days) with Undo."""
        offline = self._offline_ids()
        ids = [i for i in dict.fromkeys(ids) if i not in offline]
        if not ids:
            return
        from app.qt import confirm
        one = len(ids) == 1 and name
        title = strings.NEEDS_REMOVE_TITLE_ONE.format(name=name) if one else \
            strings.NEEDS_REMOVE_TITLE.format(n=len(ids))
        yes = strings.NEEDS_REMOVE_YES_ONE if one else strings.NEEDS_REMOVE_YES.format(n=len(ids))
        writer = self.win.services.writer
        done = strings.NEEDS_REMOVED_ONE.format(name=name) if one else strings.NEEDS_REMOVED.format(n=len(ids))

        def answered(go):
            if go:
                self._give(done, ids, lambda t: writer.remove(ids, label=t))
        self.confirming = confirm.ask(self.win, title, strings.NEEDS_REMOVE_BODY, yes, strings.NEEDS_REMOVE_YES_TIP,
                                      default_no=True, danger=True, on_answer=answered)

    # 9a's questions (IK-3)
    def _do_this_one(self, entry, line):
        path = os.path.join(self._data(), *entry.data["rel"].split("/"))
        writer = self.win.services.writer
        self._give(strings.NEEDS_RELINKED.format(label=line.label), (line.item_id,),
                   lambda t: writer.relink(line.item_id, path, label=t))

    def _do_its_new(self, entry, _line):
        path = os.path.join(self._data(), *entry.data["rel"].split("/"))
        writer = self.win.services.writer
        if self._give(entry.data["rel"], (), lambda t: writer.its_new(path, label=t), toast_it=False) is not None:
            self._say(strings.NEEDS_ITS_NEW.format(name=entry.data["rel"].rsplit("/", 1)[-1]))

    # Connect's entries (each on a worker; the window never makes Connect's ledger)
    def _do_mine_anyway(self, entry, _line):
        mine, kick, lang, read_settings = (self.connect_calls["mine_anyway"], self.connect_calls.get("kick"),
                                           self.language, self.read_settings)
        need_id = entry.data["need_id"]

        def run():
            ok = mine(lang, need_id)
            if ok and kick is not None:
                kick(read_settings() or {})
            return ok
        bridge.run_in_worker(run, then=lambda ok: self._connect_done(
            strings.NEEDS_MINE_ANYWAY if ok else strings.NEEDS_MINE_ANYWAY_NOT), failed=self._failed)

    def _do_ask_hato(self, _entry, _line):
        backfill, lang, read_settings = self.connect_calls["ask_hato"], self.language, self.read_settings
        bridge.run_in_worker(lambda: backfill(lang, read_settings() or {}),
                             then=lambda _s: self._connect_done(strings.NEEDS_ASKED_HATO), failed=self._failed)

    def _do_dismiss(self, entry, _line):
        dismiss = self.connect_calls["dismiss"]
        bridge.run_in_worker(dismiss, entry.data["need_id"],
                             then=lambda _ok: self._connect_done(strings.NEEDS_DISMISSED), failed=self._failed)

    def _connect_done(self, text):
        self._say(text)
        self.refresh()

    # P4.1's (hidden until hooked)
    def _do_mine_text_only(self, entry, line):
        self.hooks["mine_text_only"](entry, line)

    def _do_make_cards(self, entry, _line):
        self.hooks["make_cards"](entry)

    # the failures (W3.5's)
    def _do_open_logs(self, _entry, _line):
        self.win.open_logs()

    def _do_save_logs(self, _entry, _line):
        dest = self.pick_save(strings.NEEDS_SAVE_LOGS_TITLE, "surasura-logs.zip")
        if not dest:
            return
        save = self.connect_calls["save_logs"]
        bridge.run_in_worker(save, dest, then=lambda _n: self._say(strings.NEEDS_SAVED_LOGS.format(path=dest)),
                             failed=self._failed)


def _same(a, b):
    return a is b or (len(a) == len(b) and all(x is y for x, y in zip(a, b)))


def _reads_same(a, b):
    """Whether rows `b` hold what the entries read of rows `a` (`service.entries`: a row's group, title and kind, each
    episode's id, label, number, file and whether it is missing), in any order (C1). A row kept by the reader's cache
    is the same object, or its copy with a new place number and the same episodes: no episode is read then."""
    if len(a) != len(b):
        return False
    was = {r.key: r for r in a}
    for r in b:
        o = was.get(r.key)
        if o is r:
            continue
        if o is None or (o.work_id, o.title, o.media) != (r.work_id, r.title, r.media):
            return False
        if o.episodes is not r.episodes and [_read(e) for e in o.episodes] != [_read(e) for e in r.episodes]:
            return False
    return True


def _read(e):
    return e.id, e.label, e.number, e.rel_path, e.missing


def make_area(parent):
    """The cards in a scroll area (the page's list's place)."""
    area = QScrollArea(parent)
    area.setObjectName("needsarea")
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    cards = NeedsCards(area)
    area.setWidget(cards)
    area.viewport().setAutoFillBackground(False)
    cards.setAutoFillBackground(False)
    return area, cards

