"""New arrivals in the window (W3.2 Q1; the RUNBOOK §1 *New arrivals inset*, *The tray*, *The arrival's number*; A2
#22–32, #89–97, #100, #118; IK-5, IK-10, IK-11): the header's inset, the tray under it and the arrivals' numbers.

- **The inset** (`ArrivalsInset`): a pill cut into the header band (the `cut` floor, its top wall in shadow and its
  lower wall lit, flat), up to three tiny covers of the newest arrivals, *New arrivals* and the count of files
  (R4b-12). **Absent when nothing has arrived.** Pressed it sinks (`SPRINGS["press"]`, ω 36 critical) and its lower
  wall lights; released it lifts (`release`, ω 26). An arrival: the covers part, the new one drops in from 10 px, the
  count lifts once (`drag-part`, ω 22 critical; Reduced motion jumps). It repaints only itself, only when what it shows
  changed (S19).
- **The tray** (`ArrivalsTray`, a `motion.Overlay` opened as "tray"): slate navy with its lit top edge and the tray's
  shadow, 452 · fz wide, as tall as its rows up to the dock. The reader's `View.arrival_groups` (S1: newest first by
  `added_at`, *New* then *Already watched*, whose head offers *✓ All to Finished*); each row: the cover (generated until
  Q6), the title, the one line (the source chip in its colour, then the line's parts in their tones), the big *N new /
  ep* in a fixed 56 · fz column (its tooltip: the episode count, "an estimate until analysed"), ONE icon square always
  shown (↑ *Top*, or ✓ *Finished* for a watched one) and ⋯ (*Top of Current* · *After its show* · *Soon* · *Goal* ·
  *Finished* · *Never read this folder* › its folder and each above it, once the looks' worker answers — a list row's
  own entry, `item_menu.offer_skip` / `skip_menu` / `give_skip` (Q7) · *Open its folder* · *Remove…*). Every placement
  goes through the window's writer (`moves.Writer.place`, S2) by the drag controller's tickets (its toast and Undo);
  *Finished* offers D14's choice as W3.1a's finish toast does (IK-11); *Remove…* asks first (`confirm.ask`, naming the
  count), then `Writer.remove` with Undo. A press and `drag-start-px` on a row drags it (`DragController.begin_by_id`:
  the list's gaps, the wells) while the tray fades (`tray-fade`), back once the drag ends. It stays open after a
  placement; ✕, Esc, Back and a click outside close it; Tab goes through the rows, Enter is the row's icon, the menu key
  its ⋯. A4 (20,000 arrivals): its rows are a model of keys painted by a list (`TrayModel`, `TrayList`) — an arrival in
  or out is one row inserted or removed, a new number repaints its row alone, and a closed tray does no row work (the
  view waits for `open`). Rows that share a title name their folder first on their line (K7: where the
  original sits, from the looks' answer — the shell's `_named_arrival`, `view_rows.arrival_folder`).
- **The numbers** (`ArrivalNumbers`): each arrival's files asked of the warm worker
  (`app/services/arrivals.ArrivalsWorker.estimate`) once each, when the arrival first shows, each with the piece's
  earlier files placed before it (IK-5) — the asks on a worker, never the window's thread; the answers kept by (item,
  the answer's plan signature, the known words' signature) (IK-10) and handed to the reader (`set_estimates`), whose
  next view fills the rows' numbers. A failed answer shows nothing (the dash stays).

Strings from `strings.py`, colours and sizes from `theme.py`; nothing here reads or writes the store.
"""
import bisect
import collections
import heapq
import itertools
import math
import operator
import os
import threading
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (QAction, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QStandardItem,
                         QStandardItemModel)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QLabel, QListView, QMenu,
                             QSizePolicy, QStyledItemDelegate, QToolButton, QToolTip, QVBoxLayout, QWidget)

from app import theme
from app.qt import motion, rows, shadow, strings, style
from app.qt import covers as qcovers                 # --- W3.2 L3: the titles' own pictures (Q6's door)
from app.services import view_rows

COVERS = 3                                  # tiny covers in the inset


def _fz():
    return theme.text_factor(style.current()[1])


# --- the choices (pure: the tests' and a light mutant pass's targets) --------------------------------------------- #
def _stamp(a):
    return a.added_at or ""


def newest(arrivals, n=COVERS):
    """The newest `n` arrivals by `added_at`, newest first (equal stamps keep the tray's order) — never a sort of every
    arrival (A4: at 20,000, one a view). The reader's `View.arrivals` (a tuple) are *New* then *Already watched*, each
    newest first: the newest are among each group's first `n`, the second group found by halving."""
    if isinstance(arrivals, tuple) and len(arrivals) > 4 * n:
        cut = bisect.bisect_left(arrivals, True, key=lambda a: a.group != "new")
        arrivals = arrivals[:min(n, cut)] + arrivals[cut:cut + n]
    return heapq.nlargest(n, arrivals, key=_stamp)


def inset_titles(arrivals, n=COVERS):
    """The inset's covers: the newest `n` arrivals' cover titles, newest first (the tray's order puts *New* first;
    the covers follow `added_at` across both groups)."""
    return tuple((a.cover_title or a.title or "") for a in newest(arrivals, n))


def icon_of(arrival):
    """The row's one icon: ✓ *Finished* for an arrival whose every file is watched, else ↑ *Top*."""
    return "finished" if arrival.group == "watched" else "top"


def unit_of(arrival):
    return strings.TRAY_NUMBER_UNIT.format(
        unit=view_rows.STRINGS["per_unit"][view_rows._arrival_unit(arrival.media)])


def number_text(arrival):
    """(the big figure, its unit) of an arrival's number: the dash until every file's estimate came."""
    if arrival.per_ep is None:
        return strings.TRAY_NUMBER_NONE, unit_of(arrival)
    return f"{arrival.per_ep:,}", unit_of(arrival)


MENU = ("top", "after-show", "soon", "goal", "finished", "folder", "remove")


def menu_entries(arrival, writable=True, reason=None, has_show=True):
    """⋯'s entries: [(name, label, tip, enabled)], in order; the moves disabled with the store's reason while it can't
    be written (E4) — *Open its folder* never; *After its show* greyed while no part of its title is in Current
    (`has_show`, N1: it would place nothing)."""
    out = []
    for name in MENU:
        label, tip = strings.TRAY_MENU[name]
        ok = writable or name == "folder"
        if ok and name == "after-show" and not has_show:
            out.append((name, label, strings.TRAY_NO_SHOW, False))
            continue
        out.append((name, label, tip if ok else (reason or tip), ok))
    return out


def asks_for(arrival, data_path):
    """The estimate requests for an arrival's files: [(item_id, path, k, paths)] — each file with the piece's first `k`
    files (its earlier ones) placed before it (IK-5: a show counts what each episode brings after the ones before it);
    `paths`, the piece's, one tuple its files' asks share (A4: never a list of earlier paths per file)."""
    paths = tuple(os.path.join(data_path, *(rel or "").split("/")) for rel in arrival.rel_paths)
    return [(item_id, paths[k], k, paths) for k, item_id in enumerate(arrival.item_ids)]


def answer_number(answer, chained):
    """An estimate's *N new* for its file, or None (a failure, or no plan yet: nothing shown). A file asked after the
    piece's earlier ones reads the count after them (`n_new_after_show`: they are its show), the first the count at the
    top of Current (`n_new_top`)."""
    if not isinstance(answer, dict) or answer.get("error"):
        return None
    value = answer.get("n_new_after_show") if chained else None
    if value is None:
        value = answer.get("n_new_top")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# --- the numbers ---------------------------------------------------------------------------------------------------- #
FILL_FROM = 400              # IK-6: more rows than this to make at once and the tray fills in steps (a screen first)
FIRST_ROWS = 60             # ... the rows the press's own frame makes (a screen and more)
FILL_STEP_S = 0.003         # ... each later step's budget on the window's thread (the rows' items made, off the list)
FILL_CHUNK = 250            # ... items made between two looks at the clock
REPAINT_ROWS = 40            # picks moved on more rows than this: one repaint of the list's face (A4A-3)
HAND_EVERY = 0.25           # s: the numbers go to the reader at most four times a second (A4), the last never lost


def _later(seconds, fn):
    t = threading.Timer(seconds, fn)
    t.daemon = True
    t.start()


class ArrivalNumbers:
    """The arrivals' estimates, asked of the warm worker (`client.estimate(path, placed, callback)`) once per file and
    kept by (item id, the answer's plan signature, the known words' signature) — IK-10. `want(arrivals)` (the window's
    thread, cheap) asks for the files not asked yet, on a worker; each answer lands in `kept` and the estimates under
    the newest signature go to `on_change({item_id: N new})` (the reader's `set_estimates`), on the answer's thread —
    each answer merged as it comes, handed on at most once every `every` seconds (the first at once, the rest at the
    end of the wait: never one view built per answer, the last answer never lost; `flush()` hands on now).
    `recheck()` (the tray opening): the known words' file and the plan's version read again; when either moved, every
    shown file is asked again (the worker keeps its own answers: an unchanged file is answered from its cache).
    `run(fn)`: how a task leaves the window's thread (a test's). `client` / `language` may be callables, read at each
    ask (N3: the window's own, as they stand)."""

    def __init__(self, client, language, on_change=None, data_path=None, known_file=None, plan_token=None,
                 run=None, every=HAND_EVERY, later=None, clock=None):
        self._client = client
        self._language = language
        self.on_change = on_change
        self._data_path = data_path
        self._known_file = known_file
        self.plan_token = plan_token or (lambda: None)
        self._run = run or (lambda fn: threading.Thread(target=fn, name="arrival-numbers", daemon=True).start())
        self._lock = threading.Lock()
        self._asked = set()                 # item ids asked under the current token
        self._token = None                  # (plan version, known words' signature) the asks were made under
        self._sig = None                    # (plan signature, known words' signature) of the newest answer
        self.kept = {}                      # (item_id, plan signature, known signature) -> N new
        self._arrivals = ()
        self.requests = 0                   # estimates asked (tests)
        self.answers = 0                    # ... and answered with a number
        self._handed = None                 # the estimates last handed on (S2: the same never handed again)
        self._current = {}                  # A4: item id -> N new under `_sig`, each answer merged as it comes
        self._moved = False                 # answers merged since the last hand-on
        self._due = False                   # a hand-on waits for its time
        self._handed_at = None
        self._every = every
        self._later = later or _later
        self._clock = clock or time.monotonic
        self.handed = 0                     # hand-ons (tests, the bench)
        self._lang = None                   # A4A-4: the language every kept ask, answer and hand-on is of

    @property
    def client(self):
        return self._client() if callable(self._client) and not hasattr(self._client, "estimate") else self._client

    @property
    def language(self):
        return self._language() if callable(self._language) else self._language

    def data_path(self):
        if self._data_path is not None:
            return self._data_path
        from app import path_utils
        return path_utils.get_data_path(self.language)

    def known_file(self):
        if self._known_file is not None:
            return self._known_file
        from app import path_utils
        return os.path.join(path_utils.get_user_files_path(self.language), "KnownWord.json")

    def _language_locked(self, language):
        """(Under `_lock`.) `language` is the one kept: on a switch, everything of the other one goes — its asks, its
        answers, a hand-on waiting on its timer — since item ids repeat across libraries (A4A-4)."""
        if language == self._lang:
            return
        self._lang = language
        self._asked = set()
        self._token = None
        self._sig = None
        self.kept = {}
        self._current = {}
        self._handed = None
        self._moved = False

    def want(self, arrivals, force=False):
        """The window's newest arrivals (`View.arrivals`): a task for the files not asked yet (or all, `force`)."""
        arrivals = tuple(arrivals or ())
        language = self.language
        with self._lock:
            self._language_locked(language)
            if arrivals is self._arrivals and not force:
                return                      # A4 (S19): the same view's arrivals, nothing to look at
            self._arrivals = arrivals
            todo = force or any(i not in self._asked for a in arrivals for i in a.item_ids)
        if todo and arrivals:
            self._run(lambda: self._ask(force))

    def recheck(self):
        with self._lock:
            arrivals = self._arrivals
        if arrivals:
            self._run(lambda: self._ask(False, check=True))

    def _read_token(self):
        from app import token_index
        try:
            plan = self.plan_token()
        except Exception:
            plan = None
        return plan, token_index.known_signature(self.known_file())

    def _ask(self, force, check=False):
        """(A worker.) The token read; the asks made."""
        try:
            token = self._read_token()
        except Exception:
            token = None
        with self._lock:
            if token != self._token:
                if self._token is not None:
                    self._asked = set()          # the plan or the known words moved: every file asked again
                self._token = token
            elif check and not force:
                return
            if force:
                self._asked = set()
            arrivals = self._arrivals
            todo = []
            for a in arrivals:
                if all(i in self._asked for i in a.item_ids):
                    continue
                for item_id, path, k, paths in asks_for(a, self.data_path()):
                    self._asked.add(item_id)
                    todo.append((item_id, path, k, paths))
        known = token[1] if token else None
        client = self.client if todo else None
        language = self.language if todo else None
        for item_id, path, k, paths in todo:
            self.requests += 1
            try:
                client.estimate(path, placed=k, piece=paths,          # A4: its place in the piece, the piece shared
                                callback=lambda ans, i=item_id, c=k > 0, kn=known, l=language:
                                self._answer(i, c, kn, ans, l))
            except Exception as e:                  # a client that can't take it: the dash stays
                print(f"New arrivals: an estimate couldn't be asked: {e!r}")

    def _answer(self, item_id, chained, known, answer, language=None):
        n = answer_number(answer, chained)
        if n is None:
            return                                  # a failure shows nothing (never an error)
        now = self.language
        if language is not None and language != now:
            return                                  # W3.2 H: asked before a switch — another library's item ids
        sig = (answer.get("plan"), known)
        with self._lock:
            self._language_locked(now)
            self.kept[(item_id, sig[0], sig[1])] = n
            if sig != self._sig:                    # a new plan or known words (rare): its answers gathered once
                self._sig = sig
                self._current = {i: v for (i, p, k), v in self.kept.items() if (p, k) == sig}
            else:
                self._current[item_id] = n          # A4: merged, never the whole dict made again per answer
            self.answers += 1
            self._moved = True
            if self._due:
                return                              # its hand-on is waiting already: this answer goes with it
            wait = 0.0 if self._handed_at is None else self._handed_at + self._every - self._clock()
            if wait > 0:
                self._due = True
        if wait > 0:
            self._later(wait, self.flush)
        else:
            self.flush()

    def flush(self):
        """Hand on what the answers moved since the last hand-on (any thread) — nothing when nothing moved (S19), or
        when it comes to the numbers last handed on (S2: no build), or when they are another language's: a switch
        while the hand-on waited on its timer (A4A-4)."""
        language = self.language
        with self._lock:
            self._due = False
            self._language_locked(language)
            if not self._moved:
                return
            self._moved = False
            self._handed_at = self._clock()
            out = dict(self._current)
            if out == self._handed:
                return                              # S2: nothing moved, nothing handed on (no build)
            self._handed = out
            self.handed += 1
        if self.on_change is not None:
            try:
                self.on_change(out)
            except Exception as e:
                print(f"New arrivals: the numbers couldn't be handed on: {e!r}")

    def estimates_locked(self):
        return dict(self._current)

    def estimates(self):
        with self._lock:
            return self.estimates_locked()


# --- the inset ------------------------------------------------------------------------------------------------------- #
class ArrivalsInset(QToolButton):
    """The header's New arrivals: a cut pill with its covers, words and count; a click opens the tray (the shell)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("arrivals")
        self.setText(strings.ARRIVALS)
        self.setToolTip(strings.ARRIVALS_TIP.format(n=0))
        self.setAccessibleName(strings.ARRIVALS_NAME.format(n=0))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.count = 0
        self.titles = ()
        self.refs = ()                       # --- W3.2 L3: the covers' records, beside `titles`
        self.keys = ()                       # the newest arrivals' keys (its covers')
        self._rows = 0                       # A4: how many arrivals it last showed
        self._shown = None                   # A4: the view's arrivals last given (the same tuple: nothing to look at)
        self.lit = False                     # its tray is open
        self.press = 0.0                     # 0 at rest, 1 sunk
        self.arrive = 1.0                    # an arrival's motion, 0 → 1 (1 at rest)
        self.fresh = 0                       # covers that are new in this arrival (they drop in)
        self._press_spring = None
        self._arrive_spring = None
        self._had = False                    # it has shown arrivals before (the first fill never moves)
        self.paints = 0                      # repaints asked (S19)
        self.arrivals_played = 0             # arrival motions started (tests)
        self.setVisible(False)
        qcovers.notifier().ready.connect(self._cover_ready)        # --- W3.2 L3

    # --- W3.2 L3: a picture landing repaints the inset only when it shows that title
    def _cover_ready(self, work_id):
        if any(r is not None and r[0] == work_id for r in self.refs):
            self.update()
    # --- end W3.2 L3

    # --- what it shows ----------------------------------------------------------------------------------------- #
    def set_arrivals(self, arrivals, count):
        """The reader's arrivals and their file count. -> True when anything it shows changed (repainted only then)."""
        if arrivals is self._shown and count == self.count:
            return False                     # A4 (S19): the reader's same rows, nothing looked at again
        self._shown = arrivals
        top = newest(arrivals)               # A4: one pass for the three newest, never a sort of every arrival
        titles = tuple((a.cover_title or a.title or "") for a in top)
        keys = tuple(a.key for a in top)
        refs = tuple(getattr(a, "cover", None) for a in top)          # --- W3.2 L3: the newest's records, in order
        rows, before = len(arrivals), self._rows
        self._rows = rows
        if count == self.count and titles == self.titles and refs == self.refs:
            self.keys = keys
            return False                     # nothing it shows moved: nothing repainted
        self.refs = refs                                                # --- end W3.2 L3
        # A4: something came when there are more rows than before — never a set of every arrival's key (at 60,000,
        # 19 ms an arrival); the covers that drop in are the newest not among the newest before
        grew = rows - before
        moved = self._had and count > 0 and grew > 0 and self.window().isVisible()
        fresh = min(grew, sum(1 for k in keys if k not in self.keys))
        self.count, self.titles, self.keys = count, titles, keys
        one = count == 1
        self.setToolTip(strings.ARRIVALS_TIP_ONE if one else strings.ARRIVALS_TIP.format(n=count))
        self.setAccessibleName(strings.ARRIVALS_NAME_ONE if one else strings.ARRIVALS_NAME.format(n=count))
        shown = count > 0
        if self.isHidden() == shown:
            self.setVisible(shown)
        self._had = self._had or shown
        self.updateGeometry()
        if moved:
            self.fresh = fresh
            self._play_arrival()
        self.paints += 1
        self.update()
        return True

    def set_lit(self, on):
        if bool(on) != self.lit:
            self.lit = bool(on)
            self.update()

    # --- motion -------------------------------------------------------------------------------------------------- #
    def _set_press(self, v):
        self.press = v
        self.update()

    def _set_arrive(self, v):
        self.arrive = max(0.0, min(1.0, v))
        self.update()

    def _play_arrival(self):
        """The covers part, the new one drops in from 10 px, the count lifts once (Reduced motion: at rest at once)."""
        self.arrivals_played += 1
        if self._arrive_spring is not None:
            self._arrive_spring.stop()
        self.arrive = 0.0
        self._arrive_spring = motion.clock().spring(self._set_arrive, 0.0, 1.0, owner=self,
                                                    **motion.preset("drag-part"))

    def _sink(self, down):
        name = "press" if down else "release"
        target = 1.0 if down else 0.0
        s = self._press_spring
        if s is not None and s.alive:
            s.retarget(target, **motion.preset(name))
        else:
            self._press_spring = motion.clock().spring(self._set_press, self.press, target, owner=self,
                                                       **motion.preset(name))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._sink(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._sink(False)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    # --- size and paint ------------------------------------------------------------------------------------------- #
    def _metrics(self):
        f = _fz()
        return {"h": round(32 * f), "left": round(8 * f), "right": round(12 * f), "gap": round(9 * f),
                "cw": round(14 * f), "ch": round(20 * f), "over": round(6 * f)}

    def _covers_w(self, m, n=None):
        n = len(self.titles) if n is None else n
        return 0 if not n else m["cw"] + (n - 1) * (m["cw"] - m["over"])

    def sizeHint(self):
        m = self._metrics()
        words = rows.TEXT.metrics("level", 600).horizontalAdvance(strings.ARRIVALS)
        count = rows.TEXT.metrics("level", 700).horizontalAdvance(f"{self.count:,}")
        covers = self._covers_w(m)
        w = m["left"] + covers + (m["gap"] if covers else 0) + words + m["gap"] + count + m["right"]
        return QSize(w, m["h"])

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        m = self._metrics()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        dpr = self.devicePixelRatioF() or 1.0
        h = min(self.height(), m["h"])
        top = (self.height() - h) / 2
        r = QRectF(0.5, top + 0.5, self.width() - 1, h - 1)
        radius = r.height() / 2
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, rows.c("cut"))
        p.save()                                       # the walls, inside the cut: the top in shadow, the lower lit
        p.setClipPath(path)
        sink = 1.5 * self.press
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 2 + sink), rows.c("cut-wall-top"))
        p.fillRect(QRectF(r.left(), r.bottom() - 1, r.width(), 1), rows.c("cut-wall-low"))
        if self.press > 0.01 or self.lit:              # pressed (or its tray open) the lower wall lights: the iris
            p.setOpacity(max(self.press, 0.6 if self.lit else 0.0))
            lg = QLinearGradient(QPointF(r.left() + radius, 0), QPointF(r.right() - radius, 0))
            for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
                lg.setColorAt(pos, style.qcolor(colour))
            pen = QPen(lg, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = r.bottom() - 1.2
            p.drawLine(QPointF(r.left() + radius * 0.8, y), QPointF(r.right() - radius * 0.8, y))
            p.setOpacity(1.0)
        p.restore()
        p.setPen(QPen(rows.c("cut-wall-top"), 1))      # its rim
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        mid = top + h / 2 + sink
        x = m["left"]
        t = self.arrive
        n = len(self.titles)
        step = m["cw"] - m["over"]
        for i in range(n - 1, -1, -1):                 # the oldest under, the newest on top
            title = self.titles[i]
            cx = x + i * step
            cy = mid - m["ch"] / 2
            alpha = 1.0
            if t < 1.0:
                if i < self.fresh:                     # the new one drops in from 10 px above
                    cy -= 10 * (1 - t)
                    alpha = t
                else:                                  # the others part: from a step to the left of where they rest
                    cx -= self.fresh * step * (1 - t)
            ref = self.refs[i] if i < len(self.refs) else None     # --- W3.2 L3: its own picture once decoded
            pix = qcovers.pixmap_for(ref, title, m["cw"], m["ch"], dpr, "stack")
            ring = QRectF(cx - 1.5, cy - 1.5, m["cw"] + 3, m["ch"] + 3)
            p.setOpacity(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rows.c("surface"))
            p.drawRoundedRect(ring, theme.RADII["cover-stack"] + 1, theme.RADII["cover-stack"] + 1)
            p.drawPixmap(QPointF(cx, cy), pix)
            p.setOpacity(1.0)
        if n:
            x += self._covers_w(m) + m["gap"]
        ink = rows.c("ink")
        w, _cut = rows.TEXT.draw(p, x, mid, strings.ARRIVALS, "level", self.width(), ink, weight=600, elide=False)
        x += w + m["gap"]
        lift = -2.0 * math.sin(math.pi * t) if t < 1.0 else 0.0     # the count lifts once
        rows.TEXT.draw(p, x, mid + lift, f"{self.count:,}", "level", self.width(), rows.c("accent"), weight=700,
                       elide=False)
        if self.hasFocus():
            p.setPen(QPen(rows.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        p.end()


# --- the tray's rows: a model of keys and a painted list (A4) ------------------------------------------------------- #
# The tray is a list view over a model of keys — a group's head ("head:<kind>", its widget on the row: the eyebrow and
# its buttons) then its arrivals (`Arrival.key`) — painted by `TrayDelegate` as the rows always looked (cover, title,
# the one line, the number, the icon square, ⋯). An arrival that comes or goes is a row inserted or removed
# (`TrayModel.apply`), never the list made again; the model is only brought up to date while the tray is open (a
# view that comes while it is closed waits for `open`), and the list lays itself out in batches (no step of it holds
# the window's thread at 20,000 rows).
HEAD = "head:"
_KEY = operator.attrgetter("key")
PARTS = ("more", "icon", "number")          # a row's controls, hit-tested in this order (anything else: the row)


def row_metrics():
    f = _fz()
    size = style.current()[1]
    vpad, hpad = theme.SPACING["tray-row"]
    return {"v": round(vpad * f), "h": round(hpad * f), "cw": round(theme.size("row-cover-w", size)),
            "ch": round(theme.size("row-cover-h", size)), "gap": round(12 * f),
            "to_number": round(theme.size("title-to-number", size)), "sq_gap": round(6 * f),
            "side": round(theme.size("icon-square", size)), "number": round(theme.size("arrival-number", size)),
            "space": round(2 * f)}


def row_height(m=None):
    """A row's height on the list: the cover and its padding, and the 2 · fz between rows."""
    m = m or row_metrics()
    return m["ch"] + 2 * m["v"] + m["space"]


def row_parts(rect, m=None):
    """A row's parts in `rect` (its slot on the list, the space below it included): {"row", "cover", "number", "icon",
    "more"} as QRects, and "text_right", where the title and its line stop — 28 · fz short of the number (A2 #96)."""
    m = m or row_metrics()
    r = QRect(rect.left(), rect.top(), rect.width(), rect.height() - m["space"])
    h, top, side = r.height(), r.top(), m["side"]
    x = r.left() + r.width() - m["h"] - side
    more = QRect(x, top + (h - side) // 2, side, side)
    x -= m["sq_gap"] // 2 + side
    icon = QRect(x, top + (h - side) // 2, side, side)
    x -= m["sq_gap"] + m["number"]
    number = QRect(x, top, m["number"], h)
    cover = QRect(r.left() + m["h"], top + (h - m["ch"]) // 2, m["cw"], m["ch"])
    return {"row": r, "cover": cover, "number": number, "icon": icon, "more": more,
            "text_right": number.left() - m["to_number"]}


def part_tip(arrival, part):
    """A part's tooltip: the icon named first (A2 #118), ⋯'s, the number's (its episodes, "an estimate")."""
    if part == "icon":
        return strings.TRAY_ICON[icon_of(arrival)][1]
    if part == "more":
        return strings.TRAY_MORE_TIP
    if part == "number":
        return arrival.tip
    return None


def _paint_square(p, rect, kind, hot):
    """An icon square (↑ Top, ✓ Finished, ⋯): one size on every row; ⋯ only grounded under the hand."""
    r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
    if kind != "more":
        p.setPen(QPen(rows.c("line-hi"), 1))
        p.setBrush(rows.c("overlay-hover") if hot else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, theme.RADII["icon-button"], theme.RADII["icon-button"])
    elif hot:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rows.c("overlay-hover"))
        p.drawRoundedRect(r, theme.RADII["icon-button"], theme.RADII["icon-button"])
    s = min(r.width(), r.height()) * 0.52
    box = QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s)
    colour = rows.c("ok") if kind == "finished" else rows.c("ink") if hot else rows.c("overlay-ink-dim")
    rows.icon(p, {"top": "up", "finished": "check", "more": "more"}[kind], box, colour)


def _paint_number(p, rect, text):
    """The big *N new / ep* in its fixed column, right-aligned; the dash dimmer."""
    big, unit = text
    fb = rows.TEXT.metrics("arrival-number")
    fu = rows.TEXT.metrics("new-per-episode")
    total = fb.height() + fu.height() - 4
    y0 = rect.top() + (rect.height() - total) / 2
    dash = big == strings.TRAY_NUMBER_NONE
    rows.TEXT.draw(p, rect.left(), y0 + fb.height() / 2, big, "arrival-number", rect.width(),
                   rows.c("overlay-ink-faint" if dash else "ink"), align="right", elide=False)
    rows.TEXT.draw(p, rect.left(), y0 + fb.height() - 4 + fu.height() / 2, unit, "new-per-episode", rect.width(),
                   rows.c("overlay-ink-dim"), align="right")


def paint_row(p, rect, a, hot=None, focused=False, picked=False, dpr=1.0, m=None):
    """One arrival's face in `rect` (its slot): cover · title · its one line · the number · the icon · ⋯ — `hot`, the
    part under the hand ("row" or a control: the row lit), `focused` its keyboard ring, `picked` the picks' wash."""
    m = m or row_metrics()
    parts = row_parts(rect, m)
    row = parts["row"]
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    r = QRectF(row).adjusted(2, 1, -2, -1)
    if picked:                                       # Current's picked row: the wash ringed in the accent (LM11b G4)
        p.setPen(QPen(rows.c("accent"), 1.5))
        p.setBrush(rows.c("row-picked"))
        radius = theme.DRAG["placeholder-radius"]
        p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
    elif hot is not None or focused:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rows.c("overlay-hover"))
        p.drawRoundedRect(r, theme.RADII["r-sm"], theme.RADII["r-sm"])
    if focused:
        p.setPen(QPen(rows.c("accent"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), theme.RADII["r-sm"], theme.RADII["r-sm"])
    cover = parts["cover"]
    p.drawPixmap(QPointF(cover.left(), row.top() + (row.height() - m["ch"]) / 2),
                 qcovers.pixmap_for(getattr(a, "cover", None), a.cover_title or a.title, m["cw"], m["ch"], dpr,
                                    "row"))                                     # W3.2 L3
    x = cover.left() + m["cw"] + m["gap"]
    right = parts["text_right"]
    width = max(0, right - x)
    fm_t = rows.TEXT.metrics("row-title")
    fm_l = rows.TEXT.metrics("row-sub")
    block = fm_t.height() + 2 + fm_l.height()
    y_title = row.top() + (row.height() - block) / 2 + fm_t.height() / 2
    y_line = y_title + fm_t.height() / 2 + 2 + fm_l.height() / 2
    rows.TEXT.draw(p, x, y_title, a.title, "row-title", width, rows.c("ink"))
    lx = x
    chip_ink = theme.SOURCE_INK.get(a.source)
    chip = style.qcolor(chip_ink) if chip_ink else rows.c("overlay-ink-dim")
    fm_c = rows.TEXT.metrics("source-chip")
    cw = fm_c.horizontalAdvance(a.chip) + 10
    ch = fm_c.height() + 2
    if cw < width:
        box = QRectF(lx, y_line - ch / 2, cw, ch)
        border = style.qcolor(chip_ink) if chip_ink else rows.c("overlay-ink-faint")
        border.setAlphaF(0.55)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box, theme.RADII["source-chip"], theme.RADII["source-chip"])
        rows.TEXT.draw(p, lx, y_line, a.chip, "source-chip", cw, chip, align="centre", elide=False)
        lx += cw + 8
    tones = {"dim": "overlay-ink-dim", "ok": "ok", "warn": "warn"}
    for k, (text, tone) in enumerate(a.parts):
        if lx >= right:
            break
        if k:
            w, _c = rows.TEXT.draw(p, lx, y_line, " · ", "row-sub", right - lx, rows.c("overlay-ink-faint"))
            lx += w
        w, _c = rows.TEXT.draw(p, lx, y_line, text, "row-sub", right - lx, rows.c(tones.get(tone, "overlay-ink-dim")))
        lx += w
    _paint_number(p, parts["number"], number_text(a))
    _paint_square(p, parts["icon"], icon_of(a), hot == "icon")
    _paint_square(p, parts["more"], "more", hot == "more")
    p.restore()


class TrayModel(QStandardItemModel):
    """The tray's rows as keys (C++ rows: laying out 20,000 calls no Python per row). `keys` / `objs` mirror its rows
    (a head's group, or an arrival); `paints[key]` counts each row's repaints asked (S19's tests)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keys = []
        self.objs = []
        self.keyset = set()                     # `keys` as a set, kept as rows come and go
        self._rows = None                       # {key: row}, made when asked after rows came or went (A4A-3)
        self.paints = collections.Counter()
        self.heads = {}                         # a head's key -> its row height
        self.size_of = lambda key: QSize(0, row_height())
        self.changed = 0                        # rows inserted, removed or repainted by the last `apply`
        self.gone_heads = []                    # heads' keys removed (their widgets go with their rows)

    def obj(self, row):
        return self.objs[row] if 0 <= row < len(self.objs) else None

    def row_of(self, key):
        """`key`'s row, or -1 — one lookup (the map made once after rows came or went, never a search per key)."""
        rows_ = self._rows
        if rows_ is None:
            rows_ = self._rows = {k: i for i, k in enumerate(self.keys)}
        return rows_.get(key, -1)

    def content_height(self, row_h):
        return (len(self.keys) - len(self.heads)) * row_h + sum(self.heads.values())

    def make(self, keys, objs):
        """The rows' items, not yet on the list -> (items, {head key: its row height}): an arrival's a copy of one
        made once (its size and flags), named for the screen reader."""
        size = self.size_of("")
        proto = QStandardItem()
        proto.setSizeHint(size)
        proto.setFlags(Qt.ItemFlag.ItemIsEnabled)
        out, heads = [], {}
        for key, obj in zip(keys, objs):
            if key.startswith(HEAD):
                it = QStandardItem(obj.label)
                head = self.size_of(key)
                it.setSizeHint(head)
                it.setFlags(Qt.ItemFlag.NoItemFlags)    # the keyboard walks the arrivals only: a head's buttons Tab
                heads[key] = head.height()
            else:
                it = proto.clone()
                it.setText(obj.accessible)
            out.append(it)
        return out, heads

    def _insert(self, at, keys, objs, made=None):
        if not keys:
            return
        items, heads, part = made if made is not None else self.make(keys, objs) + (None,)
        self.invisibleRootItem().insertRows(at, items)
        self.heads.update(heads)
        self.keys[at:at] = keys
        if part is not None and len(part) >= len(self.keyset):
            part |= self.keyset                    # (a fill's: its keys' set made with its items, the few joined in)
            self.keyset = part
        else:
            self.keyset.update(keys)
        self._rows = None
        self.objs[at:at] = objs
        self.paints.update(keys)
        self.changed += len(keys)

    def _remove(self, at, n):
        if n <= 0:
            return
        self.removeRows(at, n)
        for k in self.keys[at:at + n]:
            self.keyset.discard(k)
            if self.heads.pop(k, None) is not None:
                self.gone_heads.append(k)
        del self.keys[at:at + n]
        del self.objs[at:at + n]
        self._rows = None
        self.changed += n

    def _remove_where(self, gone):
        """Remove the rows whose index is in `gone` (a set), in runs, from the bottom."""
        i = len(self.keys) - 1
        while i >= 0:
            if i not in gone:
                i -= 1
                continue
            j = i
            while j - 1 >= 0 and (j - 1) in gone:
                j -= 1
            self._remove(j, i - j + 1)
            i = j - 1

    def _refresh(self, rows_):
        """Rows whose object changed: their text and their repaint (that row alone)."""
        for i in rows_:
            key, obj = self.keys[i], self.objs[i]
            it = self.item(i)
            if it is not None:
                it.setText(obj.accessible if not key.startswith(HEAD) else obj.label)
            idx = self.index(i, 0)
            self.dataChanged.emit(idx, idx)
            self.paints[key] = self.paints.get(key, 0) + 1
            self.changed += 1

    def append(self, keys, objs, made=None):
        """`keys` (with their objects; `made`: their items and heads from `make`, and `keys` as a set) added under
        the last row, in one insert — a fill's last step. -> the rows added."""
        self.changed = 0
        self._insert(len(self.keys), keys, objs, made)
        return self.changed

    def apply(self, new_keys, new_objs):
        """The rows become `new_keys` (each with its object in `new_objs`) by inserts, removes and repaints of the
        rows that changed — never a reset. -> the number of rows changed (0: nothing touched)."""
        self.changed = 0
        keys = self.keys
        if new_keys == keys:
            self._take(new_objs)
            return self.changed
        n_old, n_new = len(keys), len(new_keys)
        p = 0
        top = min(n_old, n_new)
        while p < top and keys[p] == new_keys[p]:
            p += 1
        d = n_new - n_old
        came = new_keys[p:p + d] if d > 0 else ()
        if d > 0 and keys[p:] == new_keys[p + d:] and len(set(came)) == d and self.keyset.isdisjoint(came):
            self._insert(p, came, new_objs[p:p + d])                # rows came in at one place (an arrival)
        elif d < 0 and keys[p - d:] == new_keys[p:]:                # rows went from one place (a placement)
            self._remove(p, -d)
        else:
            if len(set(new_keys)) != len(new_keys):                # never two rows on one key (the model's identity)
                new_keys = _unique(new_keys)
            self._reorder(new_keys, new_objs)
        self._take(new_objs)
        return self.changed

    def _take(self, new_objs):
        """The rows' keys are the wanted ones: the objects that changed taken in, those rows alone repainted."""
        moved = list(itertools.compress(range(len(new_objs)), map(operator.is_not, new_objs, self.objs)))
        self.objs = list(new_objs)
        self._refresh(moved)

    def _reorder(self, new_keys, new_objs):
        """The general case: the rows gone removed, those that moved out of order taken out (all but the longest run
        already in order), then every missing row inserted where it goes."""
        where = {k: n for n, k in enumerate(new_keys)}
        self._remove_where({i for i, k in enumerate(self.keys) if k not in where})
        pos = [where[k] for k in self.keys]
        keep = _longest_rising(pos)
        self._remove_where(set(range(len(pos))) - keep)
        held = set(self.keys)
        i = 0
        while i < len(new_keys):
            if i < len(self.keys) and self.keys[i] == new_keys[i]:
                i += 1
                continue
            j = i
            while j < len(new_keys) and new_keys[j] not in held:
                j += 1
            self._insert(i, new_keys[i:j], new_objs[i:j])
            i = j


def _unique(keys):
    seen, out = set(), []
    for k in keys:
        while k in seen:
            k = f"{k}+"
        seen.add(k)
        out.append(k)
    return out


def _longest_rising(seq):
    """The indices of a longest strictly rising run (not contiguous) of `seq` — the rows left where they are."""
    tails, tails_at, prev = [], [], [-1] * len(seq)
    for i, v in enumerate(seq):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v)
            tails_at.append(i)
        else:
            tails[k] = v
            tails_at[k] = i
        prev[i] = tails_at[k - 1] if k else -1
    out, i = set(), tails_at[-1] if tails_at else -1
    while i >= 0:
        out.add(i)
        i = prev[i]
    return out


class TrayDelegate(QStyledItemDelegate):
    """Paints an arrival's row (`paint_row`); a head's row is its widget's. No size hint of its own: each row's is the
    model's (laid out without Python)."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def paint(self, p, option, index):
        view = self.view
        model = view.model()
        key = model.keys[index.row()] if index.row() < len(model.keys) else None
        if key is None or key.startswith(HEAD):
            return
        a = model.objs[index.row()]
        hot = view.hot[1] if view.hot is not None and view.hot[0] == key else None
        focused = view.focus_visible and view.hasFocus() and view.currentIndex().row() == index.row()
        paint_row(p, option.rect, a, hot=hot, focused=focused, picked=view.picked(key),
                  dpr=view.viewport().devicePixelRatioF() or 1.0)


class TrayList(QListView):
    """The tray's list: hover, tooltips and presses by a row's parts — the icon square acts, ⋯ opens its menu, a press
    on the row that travels `drag-start-px` drags it; Tab and ↑ ↓ walk the arrivals, Enter is the row's icon, the
    menu key its ⋯."""

    def __init__(self, tray):
        super().__init__(tray)
        self.tray = tray
        self.setObjectName("traylist")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # one pass (IK-6): a batched layout drew no row at all until its last batch — the list stood blank ~250 ms
        # at 20,000 after every arrival, ~800 ms at 60,000; one pass is ~3 ms at 20,000 (10 at 60,000)
        self.setLayoutMode(QListView.LayoutMode.SinglePass)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setTabKeyNavigation(True)                            # Tab walks the rows (then on past the last)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setAutoFillBackground(False)
        self.setAccessibleName(strings.TRAY_NAME)
        self.hot = None                  # (key, part) under the hand
        self.focus_visible = False       # the keyboard moved last: the current row shows its ring
        self._press = None               # (key, part, pos) of a left press
        self.setItemDelegate(TrayDelegate(self))

    def picked(self, key):
        return key in self.tray.picks

    # --- where things are ------------------------------------------------------------------------------------------- #
    def at(self, pos):
        """(key, part) at a viewport point: part one of PARTS or "row"; (None, None) off the arrivals."""
        idx = self.indexAt(pos)
        model = self.model()
        if not idx.isValid() or idx.row() >= len(model.keys):
            return None, None
        key = model.keys[idx.row()]
        if key.startswith(HEAD):
            return None, None
        parts = row_parts(self.visualRect(idx))
        for name in PARTS:
            if parts[name].contains(pos):
                return key, name
        return key, "row"

    def row_of(self, key):
        return self.model().row_of(key)

    def update_key(self, key):
        """That row alone repainted (when it is on the list)."""
        row = self.row_of(key)
        if row >= 0:
            self.update(self.model().index(row, 0))

    def _set_hot(self, hot):
        if hot != self.hot:
            old, self.hot = self.hot, hot
            for h in (old, hot):
                if h is not None:
                    self.update_key(h[0])

    # --- the hand --------------------------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        self.focus_visible = False
        self._press = None
        if event.button() == Qt.MouseButton.LeftButton:
            key, part = self.at(event.position().toPoint())
            plain = not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            if plain and part != "more" and key not in self.tray.picks:
                self.tray.clear_picks()              # A4: a plain press lets the picks go (⋯ keeps them; a picked
            if key is not None:                      # row's press keeps them for its drag, its release lets them go)
                self._press = (key, part, event.position())
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            key, part, at = self._press
            d = event.position() - at
            if part in ("row", "number") and math.hypot(d.x(), d.y()) >= theme.MOTION["drag-start-px"]:
                self._press = None
                self.tray.start_drag(key, event.globalPosition().toPoint())
            return
        key, part = self.at(pos)
        self._set_hot((key, part) if key is not None else None)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        if press is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        event.accept()
        key, part = self.at(event.position().toPoint())
        if key != press[0] or part != press[1]:
            return                                   # let go somewhere else: nothing happens
        self.tray.released(key, part, event.modifiers())

    def mouseDoubleClickEvent(self, event):
        key, part = self.at(event.position().toPoint())
        if key is not None:
            event.accept()                           # never a second act (the press acts once, on its release)
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """A4: a right-click on a row is its ⋯ (the picks' menu on a picked row), where the hand is."""
        key, _part = self.at(event.pos())
        if key is None:
            super().contextMenuEvent(event)
            return
        event.accept()
        self.tray.menu(key, at=event.globalPos())

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._set_hot(None)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            key, part = self.at(event.pos())
            a = self.tray.arrival(key) if key is not None else None
            tip = part_tip(a, part) if a is not None else None
            if tip:
                QToolTip.showText(event.globalPos(), tip, self.viewport(),
                                  row_parts(self.visualRect(self.model().index(self.row_of(key), 0)))[part])
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().viewportEvent(event)

    # --- the keys --------------------------------------------------------------------------------------------------- #
    def _step(self, forward):
        """The next (or previous) arrival's row from the current one, or -1 past the end."""
        keys = self.model().keys
        i = self.currentIndex().row() if self.currentIndex().isValid() else (-1 if forward else len(keys))
        i += 1 if forward else -1
        while 0 <= i < len(keys) and keys[i].startswith(HEAD):
            i += 1 if forward else -1
        return i if 0 <= i < len(keys) else -1

    def keyPressEvent(self, event):
        key = event.key()
        cur = self.currentIndex()
        keys = self.model().keys
        here = keys[cur.row()] if cur.isValid() and cur.row() < len(keys) else None
        if here is not None and here.startswith(HEAD):
            here = None
        if event.matches(QKeySequence.StandardKey.SelectAll):         # A4: Ctrl+A picks every row
            self.tray.pick_all()
            event.accept()
            return
        if key == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier and here is not None:
            self.tray.pick(here)                                        # Ctrl+Space: the keyboard's row, as Current's
            event.accept()
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            forward = key == Qt.Key.Key_Tab and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            i = self._step(forward)
            if i < 0:
                self.focus_visible = False
                QWidget.focusNextPrevChild(self, forward)        # past the last row: on to the next control
            else:
                self._go(i)
            event.accept()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            i = self._step(key == Qt.Key.Key_Down)
            if i >= 0:
                self._go(i)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and here is not None:
            a = self.tray.arrival(here)
            self.tray.act(a, icon_of(a))
            event.accept()
            return
        if (key == Qt.Key.Key_Menu or (key == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier)) \
                and here is not None:
            self.tray.menu(here)
            event.accept()
            return
        super().keyPressEvent(event)

    def _go(self, row):
        self.focus_visible = True
        old = self.currentIndex()
        self.setCurrentIndex(self.model().index(row, 0))
        self.scrollTo(self.currentIndex())
        if old.isValid():
            self.update(old)
        self.update(self.currentIndex())

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self.focus_visible = True
            if not self.currentIndex().isValid() or self.model().keys[self.currentIndex().row()].startswith(HEAD):
                i = self._step(event.reason() == Qt.FocusReason.TabFocusReason)
                if i >= 0:
                    self.setCurrentIndex(self.model().index(i, 0))
        if self.currentIndex().isValid():
            self.update(self.currentIndex())

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.currentIndex().isValid():
            self.update(self.currentIndex())


class _MoreMark:
    """A row's ⋯ marked while *Open its folder* is live (the press's arc on its raised ground, `press.widget_mark`'s
    look), over the row's ⋯ on the list."""

    def __init__(self, view, key):
        self.view, self.key, self.spinner = view, key, None

    def on(self):
        from app.qt import press as qpress
        if sip.isdeleted(self.view):
            return
        row = self.view.row_of(self.key)
        if row < 0:
            return
        more = row_parts(self.view.visualRect(self.view.model().index(row, 0)))["more"]
        s = self.spinner = qpress._Grounded(self.view.viewport())
        s.move(more.center().x() - s.width() // 2, more.center().y() - s.height() // 2)
        s.raise_()
        s.show()
        s.set_running(True)

    def off(self):
        s, self.spinner = self.spinner, None
        if s is not None and not sip.isdeleted(s):
            s.set_running(False)
            s.hide()
            s.deleteLater()


class _Fade(QWidget):
    """The tray's picture fading while a drag from it runs (painted opacity: no effect on a widget, 05 §5.3)."""

    def __init__(self, parent, pix, geometry):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.pix = pix
        self.alpha = 1.0
        self.setGeometry(geometry)

    def set_alpha(self, a):
        self.alpha = a
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setOpacity(self.alpha)
        p.drawPixmap(0, 0, self.pix)
        p.end()


class _Away(QObject):
    """A press outside the tray and its inset closes it, as Esc does — never one on an overlay over it (a toast's Undo,
    a confirmation), on its scrim or in a menu; the press goes on to what it was on."""

    def __init__(self, tray):
        super().__init__(tray)
        self.tray = tray

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.tray.isVisible() \
                and self.tray.picks and isinstance(obj, QWidget) and self.tray.isAncestorOf(obj):
            self.tray.clear_picks()                  # A4: Esc lets the picks go first (as in Current); again, it closes
            return True
        if event.type() != QEvent.Type.MouseButtonPress or not self.tray.isVisible():
            return False
        if isinstance(obj, QWidget):
            win = obj.window()
            if win is not None and win.windowType() == Qt.WindowType.Popup:
                return False                         # the ⋯ menu (it closes itself)
            w = obj
            while w is not None:
                if w is self.tray or w is self.tray.inset:
                    return False
                if (isinstance(w, motion.Overlay) and w is not self.tray) or w.objectName() == "confirmscrim":
                    return False
                w = w.parentWidget()
        at = event.globalPosition().toPoint()
        for w in (self.tray, self.tray.inset):
            if w.rect().contains(w.mapFromGlobal(at)):
                return False
        self.tray.close()
        return False


# --- the tray ------------------------------------------------------------------------------------------------------- #
class ArrivalsTray(motion.Overlay):
    """The overlay under the inset (see the module's doc). `win`: the shell (its `moves`, `toasts`, `dock`, `say`)."""
    how = "tray"
    shadow_name = "tray"
    focus = True

    def __init__(self, parent, inset, win):
        super().__init__(parent)
        self.inset = inset
        self.win = win
        self.setObjectName("arrivalstray")
        self.setAccessibleName(strings.TRAY_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        f = _fz()
        box = QVBoxLayout(self)
        box.setContentsMargins(round(10 * f), round(10 * f), round(10 * f), round(10 * f))
        box.setSpacing(round(4 * f))
        head = QHBoxLayout()
        head.setContentsMargins(round(6 * f), 0, 0, 0)
        self.heading = QLabel(strings.ARRIVALS, self)
        self.heading.setObjectName("trayheading")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self.heading)
        self.loading = QLabel(strings.TRAY_LOADING, self)     # IK-6: a big tray's rows still coming in
        self.loading.setObjectName("trayloading")
        self.loading.setTextFormat(Qt.TextFormat.PlainText)
        self.loading.setToolTip(strings.TRAY_LOADING_TIP)
        self.loading.hide()
        head.addWidget(self.loading)
        head.addStretch(1)
        self.close_button = QToolButton(self)
        self.close_button.setText(strings.TRAY_CLOSE)
        self.close_button.setAccessibleName(strings.TRAY_CLOSE_NAME)
        self.close_button.setToolTip(strings.TRAY_CLOSE_TIP)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(lambda _c=False: self.close())
        head.addWidget(self.close_button)
        box.addLayout(head)
        self.model = TrayModel(self)                # A4: the rows as a model, painted by a list
        self.model.size_of = self._size_of
        self.view = TrayList(self)
        self.view.setModel(self.model)
        box.addWidget(self.view, 1)
        self.groups = ()                    # the view's arrival_groups last given (shown, or waiting for `open`)
        self._applied = ()                  # ... and those the rows show (the model is brought up to date open only)
        self._target = ((), [], [], {})     # IK-6: (groups, the rows' keys, their objects, {head kind: its row})
        self._filling = False               # ... the rows coming in in steps (a first open at 20,000)
        self._filled_of = None              # ... the groups the rows on the list are the first rows of
        self._made = ([], {}, set())        # ... the items made for the rows after them, not yet on the list
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.timeout.connect(self._fill_step)
        self._by_key = None                 # (groups, {key: arrival}) — `arrival(key)`, made when asked
        self.heads = {}                     # group kind -> (its head widget, its label, its button or None)
        self._head_objs = {}                # group kind -> its head's (kind, label) object (the same while unchanged)
        self._row_h = row_height()
        self.last_menu = None
        self.mine_too = None                # P4.1: *Mine them too* (A2 behaviour 101), `mine_too(item_ids)`; None: hidden
        self.question = None                # Remove's confirmation, while it asks
        self.fade = None
        self._dragging = False
        self._drag_watch = QTimer(self)
        self._drag_watch.setInterval(30)
        self._drag_watch.timeout.connect(self._drag_ended)
        self.paints = 0
        self.picks = set()                  # A4: the picked rows' keys (Ctrl / Shift+click, Ctrl+A)
        self._pick_anchor = None            # the row Ctrl picked last: a Shift range starts there
        rows.picks_join(self)               # A4 (picks): picks in one list at a time
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        parent.installEventFilter(self)
        qcovers.notifier().ready.connect(self._cover_ready)        # --- W3.2 L3
        self.hide()

    # --- W3.2 L3: a picture landing repaints only the rows of that title on screen (none while it is closed)
    def _cover_ready(self, work_id):
        if not self.open_now():
            return
        view = self.view
        first = view.indexAt(QPoint(0, 0))
        last = view.indexAt(QPoint(0, view.viewport().height() - 1))
        start = first.row() if first.isValid() else 0
        end = last.row() if last.isValid() else len(self.model.keys) - 1
        for i in range(start, min(end, len(self.model.keys) - 1) + 1):
            a = self.model.objs[i]
            if getattr(a, "work_id", None) == work_id and not self.model.keys[i].startswith(HEAD):
                self.repaint_row(self.model.keys[i])

    def repaint_row(self, key):
        self.view.update_key(key)
    # --- end W3.2 L3

    # --- what it shows ------------------------------------------------------------------------------------------- #
    def open_now(self):
        """Open, opening, or faded under a drag from it (it comes back): its rows are kept up to date."""
        return self.isVisible() or motion.opening_of(self) is not None or self._dragging

    def set_groups(self, groups):
        """The reader's `View.arrival_groups`. -> True when anything changed: only the rows whose arrival is a new
        object are repainted; an unchanged view (the same tuple, S1's cache) touches nothing (S19). While the tray is
        closed the groups are only kept (no row work): `open` brings the rows up to date."""
        if groups is self.groups:
            return False
        self.groups = groups
        if self.open_now():
            self._apply()
        return True

    def _apply(self):
        """The rows brought up to the groups last given: the model's inserts, removes and repaints of what changed. A
        big change (a first open at 20,000) makes a screen's rows in this frame and the rest in steps of
        `FILL_STEP_S` on the next ticks, *Loading…* beside the heading meanwhile (IK-6)."""
        groups = self.groups
        if groups is self._applied:
            return False
        groups, keys, objs, _heads = self._target_for(groups)
        if self._filling or len(keys) - len(self.model.keys) > FILL_FROM:
            changed = 0                        # a fill under way for these groups: its steps go on
            if self._filled_of is not groups:  # a fill starts (or a view landed mid-fill): a screen's rows now
                if not self._filling:
                    self._filling = True
                    self.loading.show()
                changed = self._rows_to(keys[:FIRST_ROWS], objs[:FIRST_ROWS])
                self._filled_of = groups
                self._made = ([], {}, set())
            self._fill_timer.start(0)
            return bool(changed)
        return bool(self._rows_to(keys, objs, whole=True))

    def _target_for(self, groups):
        """The rows `groups` want: (groups, keys, objects, {head kind: its row}) — made once per groups."""
        if self._target[0] is not groups:
            keys, objs, heads = [], [], {}
            for g in groups:
                heads[g.kind] = len(keys)
                keys.append(HEAD + g.kind)
                objs.append(self._head_obj(g))
                keys += map(_KEY, g.rows)
                objs += g.rows
            self._target = (groups, keys, objs, heads)
            if self.picks:                                     # a pick whose row went lets go
                gone = self.picks - set(keys)
                if gone:
                    self.picks -= gone
        return self._target

    def _rows_to(self, keys, objs, whole=False, append=False):
        """The model's rows made `keys` (all the groups' when `whole`; `append`: `keys` are the next rows under the
        last, their items made — `TrayModel.make`), each group's head widget on its row, the tray placed again when
        rows changed. -> the rows changed."""
        self._row_h = row_height()
        model = self.model
        changed = model.append(keys, objs, append) if append else model.apply(keys, objs)
        for key in model.gone_heads:                           # a head's row removed: the list let its widget go
            self.heads.pop(key[len(HEAD):], None)
        model.gone_heads = []
        groups, _keys, _objs, at = self._target
        for g in groups:                                       # each head's widget on its row; its words, *Mine…*
            row = at[g.kind]
            if row >= len(model.keys) or model.keys[row] != HEAD + g.kind:
                row = model.row_of(HEAD + g.kind)              # (rows made so far that aren't the groups' yet)
                if row < 0:
                    continue                                   # (its row not made yet: a fill's later step)
            idx = model.index(row, 0)
            head = self._head(g)
            if self.view.indexWidget(idx) is not head:
                self.view.setIndexWidget(idx, head)
                model.item(row).setSizeHint(self._size_of(HEAD + g.kind))
                model.heads[HEAD + g.kind] = self._size_of(HEAD + g.kind).height()
        if whole:
            self._applied = groups
        if changed:
            self.paints += 1
            if self.isVisible():
                self.place()
        return changed

    def _fill_step(self):
        """(IK-6) The next rows' items made within `FILL_STEP_S`, off the list (each insert lays the list out again);
        once all are made, a step of its own puts them on in one insert and lets *Loading…* go. A closed tray waits
        (no row work): its `open` goes on from where the fill stood."""
        if not self._filling or not self.open_now():
            return
        groups, keys, objs, _heads = self._target_for(self.groups)
        if self._filled_of is not groups:
            self._apply()                                      # (new groups while it was closed: from a screen's rows)
            return
        items, heads, made_keys = made = self._made
        base = len(self.model.keys)
        i = base + len(items)
        if i < len(keys):
            t0 = time.perf_counter()
            while i < len(keys) and time.perf_counter() - t0 < FILL_STEP_S:
                j = min(len(keys), i + FILL_CHUNK)
                more, hs = self.model.make(keys[i:j], objs[i:j])
                items += more
                heads.update(hs)
                made_keys.update(keys[i:j])
                i = j
            self._fill_timer.start(0)                          # more to make, or the insert: on the next tick
            return
        self._made = ([], {}, set())
        if self.model.keys == keys[:base]:
            self._rows_to(keys[base:], objs[base:], append=made)
        if self.model.keys != keys:
            self._rows_to(keys, objs)                          # (never left otherwise: the groups' rows, whole)
        self._filling = False
        self._filled_of = None
        self._applied = groups
        self.loading.hide()
        if self.isVisible():
            self.place()

    def filling(self):
        """A big tray's rows are still coming in (IK-6; tests, the bench)."""
        return self._filling

    def _size_of(self, key):
        if key.startswith(HEAD):
            held = self.heads.get(key[len(HEAD):])
            h = held[0].sizeHint().height() if held is not None else round(32 * _fz())
            return QSize(0, h + row_metrics()["space"])
        return QSize(0, self._row_h)

    def _head_obj(self, group):
        held = self._head_objs.get(group.kind)
        if held is None or held.label != group.label:
            held = self._head_objs[group.kind] = _HeadObj(group.kind, group.label)
        return held

    def arrival(self, key):
        """The arrival shown (or about to be) on `key`, from the groups last given."""
        held = self._by_key
        if held is None or held[0] is not self.groups:
            held = self._by_key = (self.groups, {a.key: a for g in self.groups for a in g.rows})
        return held[1].get(key)

    def keys(self):
        """The arrivals' keys as the rows show them, top to bottom (while a fill is under way, every row it is making:
        Ctrl+A and a Shift range reach the rows still to come)."""
        return [k for k in (self._target[1] if self._filling else self.model.keys) if not k.startswith(HEAD)]

    def part_rect(self, key, part="row"):
        """Where a row's part is on the list's viewport (scrolled to first), or None off the list."""
        row = self.view.row_of(key)
        if row < 0:
            return None
        idx = self.model.index(row, 0)
        self.view.scrollTo(idx)
        self.view.doItemsLayout()
        return row_parts(self.view.visualRect(idx))[part]

    def tip(self, key, part):
        a = self.arrival(key)
        return part_tip(a, part) if a is not None else None

    def _head(self, group):
        held = self.heads.get(group.kind)
        if held is None or sip.isdeleted(held[0]):
            head = QWidget(self.view.viewport())
            head.setAutoFillBackground(False)
            outer = QVBoxLayout(head)
            f = _fz()
            outer.setContentsMargins(round(8 * f), round(6 * f), round(4 * f), round(2 * f))
            outer.setSpacing(0)
            row = QHBoxLayout()
            outer.addLayout(row)
            label = QLabel(group.label.upper(), head)
            label.setObjectName("popeyebrow")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # never wider than the tray
            row.addWidget(label, 1)
            if group.kind == "watched":                  # A4: four buttons — they go on a line of their own, under
                row = QHBoxLayout()                      # its name, never squeezing it out
                row.addStretch(1)
                outer.addLayout(row)
            kind = group.kind
            for where, text, tip in (("soon", strings.TRAY_ALL_SOON, strings.TRAY_ALL_SOON_TIP),
                                     ("goal", strings.TRAY_ALL_GOAL, strings.TRAY_ALL_GOAL_TIP)):
                b = QToolButton(head)                    # A4: every group's All to Soon / All to Goal, as ✓ All to
                b.setObjectName(f"trayall{where}")       # Finished looks
                b.setText(text)
                b.setAccessibleName(text)
                b.setToolTip(tip)
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _c=False, w=where, k=kind: self.all_to(k, w))
                row.addWidget(b)
                setattr(head, where, b)
            button = None
            if group.kind == "watched":
                button = QToolButton(head)
                button.setText(strings.TRAY_ALL_FINISHED)
                button.setAccessibleName(strings.TRAY_ALL_FINISHED)
                button.setToolTip(strings.TRAY_ALL_FINISHED_TIP)
                button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _c=False: self.all_to_finished())
                row.addWidget(button)
                mine = QToolButton(head)                 # A2 behaviour 101, P4.1: hidden until `mine_too` is set
                mine.setObjectName("trayminetoo")
                mine.setText(strings.TRAY_MINE_TOO)
                mine.setAccessibleName(strings.TRAY_MINE_TOO)
                mine.setToolTip(strings.TRAY_MINE_TOO_TIP)
                mine.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                mine.setCursor(Qt.CursorShape.PointingHandCursor)
                mine.clicked.connect(lambda _c=False: self.mine_them_too())
                row.addWidget(mine)
                head.mine = mine
            held = self.heads[group.kind] = (head, label, button)
        if held[1].text() != group.label.upper():
            held[1].setText(group.label.upper())
        mine = getattr(held[0], "mine", None)
        if mine is not None and mine.isHidden() == (self.mine_too is not None):
            mine.setVisible(self.mine_too is not None)
        return held[0]

    def watched(self):
        return next((g.rows for g in self.groups if g.kind == "watched"), ())

    # --- placing it -------------------------------------------------------------------------------------------------- #
    def place(self):
        """Under the inset, its right edge on the inset's, kept inside the window; as tall as its rows, to the dock."""
        p = self.parentWidget()
        self.ensurePolished()
        width = min(round(theme.size("tray", style.current()[1])), p.width() - 16)
        lay = self.layout()
        if row_height() != self._row_h:                  # the text size moved: every row's height with it
            self._row_h = row_height()
            for i, key in enumerate(self.model.keys):
                it = self.model.item(i)
                if it is not None:
                    it.setSizeHint(self._size_of(key))
        content = self.model.content_height(self._row_h)
        margins = lay.contentsMargins()
        head = lay.itemAt(0).sizeHint().height()
        want = margins.top() + head + lay.spacing() + content + margins.bottom() + 2
        b = self.inset
        at = b.mapTo(p, QPoint(b.width(), b.height()))
        y = at.y() + 6
        bottom = p.height() - 8
        dock = getattr(self.win, "dock", None)
        if dock is not None and dock.isVisible():
            bottom = min(bottom, dock.mapTo(p, QPoint(0, 0)).y() - 8)
        height = max(round(80 * _fz()), min(want, bottom - y))
        x = max(8, min(at.x() - width, p.width() - width - 8))
        self.setGeometry(x, y, width, height)

    def open(self):
        self._apply()                    # A4: the rows brought up to date as it opens (closed, they waited)
        self.place()
        return super().open()

    def toggle(self):
        if self.isVisible() or motion.opening_of(self) is not None:
            self.close()
        else:
            self.open()

    def showEvent(self, event):
        self._apply()
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)
        self.inset.set_lit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)
        if not self._dragging:
            self.inset.set_lit(False)

    def closeEvent(self, event):
        self.clear_picks()
        self._dragging = False
        self._drag_watch.stop()
        if self.fade is not None:
            self.fade.hide()
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["tray"])
        p.end()

    # --- the actions ----------------------------------------------------------------------------------------------- #
    def _moves(self):
        return getattr(self.win, "moves", None)

    def released(self, key, part, modifiers):
        """A press let go where it was pressed: Ctrl / Shift+click picks (never acts); else the icon square acts, ⋯
        opens its menu, and a plain click anywhere else lets the picks go."""
        a = self.arrival(key)
        if a is None:
            return
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            self.pick_range(key, add=ctrl)
            return
        if ctrl:
            self.pick(key)
            return
        if part != "more":
            self.clear_picks()
        if part == "icon":
            self.act(a, icon_of(a))
        elif part == "more":
            self.menu(key)

    # --- A4: the picks ----------------------------------------------------------------------------------------------- #
    def _repaint_picks(self, keys):
        """The rows whose pick moved repainted: a few by their rows, many (Ctrl+A, letting them go) as one repaint of
        what the list shows — never a row looked up per key at 20,000 (A4A-3)."""
        if len(keys) > REPAINT_ROWS:
            self.view.viewport().update()
        else:
            for k in keys:
                self.repaint_row(k)
        if self.picks:
            rows.picks_here(self)           # A4 (picks): the window's other lists let theirs go

    def pick(self, key):
        """Ctrl+click (Ctrl+Space): the row picked, or let go."""
        self.picks ^= {key}
        self._pick_anchor = key
        self._repaint_picks((key,))

    def pick_range(self, key, add=False):
        """Shift+click: the picks become every row from the anchor (the row Ctrl picked last; with none, this one) to
        this one, as Explorer's; Ctrl+Shift+click adds them."""
        keys = self.keys()
        if key not in keys:
            return
        anchor = self._pick_anchor if self._pick_anchor in keys else key
        if anchor == key:
            self._pick_anchor = key
        a, b = sorted((keys.index(anchor), keys.index(key)))
        span = set(keys[a:b + 1])
        before = self.picks
        self.picks = (before | span) if add else span
        self._repaint_picks(before ^ self.picks)

    def pick_all(self):
        """Ctrl+A: every row of the tray picked."""
        before = self.picks
        self.picks = set(self.keys())
        self._repaint_picks(before ^ self.picks)

    def clear_picks(self):
        if self.picks:
            before, self.picks = self.picks, set()
            self._pick_anchor = None
            self._repaint_picks(before)

    def picked(self):
        """The picked arrivals in the tray's order."""
        if not self.picks:
            return []
        keys, objs = (self._target[1], self._target[2]) if self._filling else (self.model.keys, self.model.objs)
        return [objs[i] for i, k in enumerate(keys) if k in self.picks]

    def _many(self, rows_):
        """(title, ids) of several arrivals as one command names them, in the tray's order."""
        ids = [i for a in rows_ for i in a.item_ids]
        title = rows_[0].title if len(rows_) == 1 else strings.TRAY_TITLES.format(n=len(rows_))
        return title, ids

    def act_many(self, rows_, name):
        """*Up next* · *Soon* · *Goal* · *Finished* · *Remove…* on several arrivals: ONE writer command (one ticket, one
        toast, one Undo), their files in the tray's order; *Finished* with D14's choice, *Remove…* asked first."""
        moves = self._moves()
        if not rows_ or moves is None or moves.refused() is not None:
            return
        title, ids = self._many(rows_)
        if name == "finished":
            self.finish(title, ids)
        elif name == "remove":
            self.ask_remove_many(title, ids)
        else:
            from app.qt import drag
            ticket = drag.Ticket(strings.TRAY_PLACED[name].format(title=title), ids=ids)
            moves._give(ticket, lambda t: moves.writer.place(ids, name, label=t))
        self.clear_picks()

    def all_to(self, kind, where):
        """A group head's *All to Soon* / *All to Goal*: every arrival of the group in one command."""
        rows_ = next((g.rows for g in self.groups if g.kind == kind), ())
        self.act_many(list(rows_), where)

    def ask_remove_many(self, title, ids):
        from app.qt import confirm, drag
        moves = self._moves()
        n = len(ids)

        def answered(yes):
            self.question = None
            if not yes or moves.refused() is not None:
                return
            ticket = drag.Ticket(strings.TRAY_REMOVED.format(title=title), ids=ids)
            moves._give(ticket, lambda t: moves.writer.remove(ids, label=t))
        self.question = confirm.ask(
            self.win, strings.TRAY_REMOVE_TITLE.format(title=title),
            strings.TRAY_REMOVE_BODY_ONE if n == 1 else strings.TRAY_REMOVE_BODY.format(n=n),
            strings.TRAY_REMOVE_YES_ONE if n == 1 else strings.TRAY_REMOVE_YES.format(n=n), strings.TRAY_REMOVE_YES_TIP,
            default_no=True, danger=True, on_answer=answered)

    def picks_menu(self, key, at=None):
        """⋯ / right-click on a picked row while two or more are picked: the tray's moves for all of them."""
        rows_ = self.picked()
        n = len(rows_)
        moves = self._moves()
        writable, reason = True, None
        if moves is None or not moves.writer.can_write():
            writable = False
            raw = (moves.writer.reason() if moves is not None else None) or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        m = QMenu(self.view)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        m.setAccessibleName(strings.TRAY_PICKS_MENU_NAME.format(n=n))
        for name, (label, tip) in strings.TRAY_PICKS_MENU.items():
            if name == "remove":
                m.addSeparator()
            act = QAction(label, m)
            act.setToolTip(tip.format(n=n) if writable else reason)
            act.setEnabled(writable)
            act.triggered.connect(lambda _c=False, nm=name: self.act_many(self.picked(), nm))
            m.addAction(act)
        self.last_menu = m
        m.popup(at if at is not None else self._menu_at(key))
        return m

    def act(self, arrival, name):
        """An icon's or ⋯'s action on `arrival` (its items): a place through the writer (its toast and Undo), D14's
        choice for *Finished*, the folder, or *Remove…* (asked first)."""
        if arrival is None:
            return
        if name == "folder":
            self.open_folder(arrival)
            return
        moves = self._moves()
        if moves is None or moves.refused() is not None:
            return
        ids = list(arrival.item_ids)
        if name == "finished":
            self.finish(arrival.title, ids)
        elif name == "remove":
            self.ask_remove(arrival)
        else:
            from app.qt import drag
            ticket = drag.Ticket(strings.TRAY_PLACED[name].format(title=arrival.title), ids=ids)
            moves._give(ticket, lambda t: moves.writer.place(ids, name, label=t))

    def finish(self, title, ids):
        """To Finished (`place(…, "finished")`) and the finish toast's choice, D14 (IK-11): *Keep* or *Take its new
        cards out* — W3.1a's `DragController._finish`, through the arrivals' own command."""
        from app.qt import drag
        moves = self._moves()
        ticket = drag.Ticket(strings.DRAG_FINISHED.format(title=title), (), ids)
        if moves._give(ticket, lambda t: moves.writer.place(list(ids), "finished", label=t), toast=False) is None:
            return

        def choose(keep):
            choice = drag.Ticket(strings.DRAG_TAKEN_OUT.format(title=title), (), ids)
            choice.follows = ticket
            moves._give(choice, lambda t: moves._set_finished(list(ids), keep, t, ticket), toast=not keep)
        moves._toast(ticket, buttons=[(strings.DRAG_KEEP, strings.DRAG_KEEP_TIP, lambda: choose(True)),
                                      (strings.DRAG_TAKE_OUT, strings.DRAG_TAKE_OUT_TIP, lambda: choose(False))])

    def all_to_finished(self):
        """*Already watched › ✓ All to Finished* (A2 behaviour 100): every watched arrival recorded, in one command, with D14's
        choice; nothing mined."""
        rows_ = self.watched()
        moves = self._moves()
        if not rows_ or moves is None or moves.refused() is not None:
            return
        ids = [i for a in rows_ for i in a.item_ids]
        title = rows_[0].title if len(rows_) == 1 else strings.TRAY_ALL_TITLES.format(n=len(rows_))
        self.finish(title, ids)

    def mine_them_too(self):
        """*Mine them too* (A2 behaviour 101): the watched arrivals' files handed to P4.1's callable (hidden until it is set)."""
        ids = [i for a in self.watched() for i in a.item_ids]
        if ids and self.mine_too is not None:
            self.mine_too(ids)

    def ask_remove(self, arrival):
        from app.qt import confirm, drag
        n = len(arrival.item_ids)
        one = n == 1
        moves = self._moves()
        ids = list(arrival.item_ids)

        def answered(yes):
            self.question = None
            if not yes or moves.refused() is not None:
                return
            ticket = drag.Ticket(strings.TRAY_REMOVED.format(title=arrival.title), ids=ids)
            moves._give(ticket, lambda t: moves.writer.remove(ids, label=t))
        self.question = confirm.ask(
            self.win, strings.TRAY_REMOVE_TITLE.format(title=arrival.title),
            strings.TRAY_REMOVE_BODY_ONE if one else strings.TRAY_REMOVE_BODY.format(n=n),
            strings.TRAY_REMOVE_YES_ONE if one else strings.TRAY_REMOVE_YES.format(n=n), strings.TRAY_REMOVE_YES_TIP,
            default_no=True, danger=True, on_answer=answered)

    def folder_of(self, arrival):
        from app import path_utils
        rel = (arrival.rel_paths or ("",))[0] or ""
        language = getattr(self.win, "language", "ja")
        return os.path.dirname(os.path.join(path_utils.get_data_path(language), *rel.split("/")))

    def open_folder(self, arrival):
        """*Open its folder*: a press (`press.open`, round 8 row 45) — the row's ⋯ turns (IK-2) from the frame of the
        press; looked for (a drive may be slow or gone, N4) and opened on a worker — or said."""
        from app.qt import press as qpress
        path = self.folder_of(arrival)

        def nothing(_info=None):
            say = getattr(self.win, "say", None)
            if say is not None:
                say(strings.TRAY_NO_FOLDER.format(path=path))
        shown = self.view.row_of(arrival.key) >= 0 and self.open_now()
        return qpress.open(self.win, lambda: path if os.path.isdir(path) else None, key=("open-folder", arrival.key),
                           at=_MoreMark(self.view, arrival.key) if shown else None,
                           then=lambda found: found or nothing(), failed=nothing)

    def _has_show(self, arrival):
        """Whether a part of the arrival's title is in Current (the view's rows), N1 — inside a group too (a row names
        every show it holds: `Row.works`, LM11b IK-3)."""
        page = getattr(self.win, "page_widgets", {}).get("current")
        view = getattr(page, "view_model", None)
        return arrival.work_id is not None and view is not None and any(
            arrival.work_id in (getattr(r, "works", None) or (r.work_id,)) and r.tier in ("now", "soon")
            for r in view.rows)

    def _menu_at(self, key):
        rect = self.part_rect(key, "more")
        return self.view.viewport().mapToGlobal(rect.bottomLeft() + QPoint(0, 1)) if rect is not None else \
            self.mapToGlobal(QPoint(0, 0))

    def menu(self, key, at=None):
        """⋯ (or the menu key) on the row of `key` (an arrival is taken too): a plain menu in the theme's style (Esc
        closes it), its entries' tips shown; under the row's ⋯, or at `at`."""
        if not isinstance(key, str):
            key = key.key
        a = self.arrival(key)
        if a is None:
            return None
        if key in self.picks and len(self.picks) > 1:
            return self.picks_menu(key, at)                     # A4: the picks' moves, for all of them
        moves = self._moves()
        writable, reason = True, None
        if moves is None or not moves.writer.can_write():
            writable = False
            raw = (moves.writer.reason() if moves is not None else None) or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        m = QMenu(self.view)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)         # N4: gone once hidden
        m.setAccessibleName(strings.TRAY_MENU_NAME.format(title=a.title))
        for name, label, tip, ok in menu_entries(a, writable, reason, self._has_show(a)):
            if name == "folder":                                    # --- W3.2 L3: Change cover… after the moves
                qcovers.add_cover_menu(m, a, writable, reason)
            if name in ("folder", "remove"):
                m.addSeparator()
            act = QAction(label, m)
            act.setToolTip(tip)
            act.setEnabled(ok)
            act.triggered.connect(lambda _c=False, n=name, arr=a: self.act(arr, n))
            m.addAction(act)
        self.last_menu = m
        from app.qt import item_menu                                # --- Q7: *Never read this folder*, a list row's
        item_menu.offer_skip(self, list(a.item_ids), m, lambda folders: item_menu.skip_menu(
            m, folders, reason, lambda path: self.skip_folder(a, path)))     # own entry, once the looks' worker answers
        m.popup(at if at is not None else self._menu_at(key))
        return m

    def skip_folder(self, arrival, path):
        """Q7 *Never read this folder*: `Writer.skip_folder` through the window's writer (`item_menu.give_skip`, a list
        row's one rule): one change — every file under the folder leaves, the tray's rows and the list's with it, as
        *Remove…* takes them — its toast with one Undo, which brings them back; a refusal is the writer's note."""
        from app.qt import item_menu
        moves = self._moves()
        if moves is None or moves.refused() is not None:
            return None
        return item_menu.give_skip(moves, path, list(arrival.item_ids))

    # --- a drag from it ---------------------------------------------------------------------------------------------- #
    def start_drag(self, key, global_pos):
        """A press travelled `drag-start-px` on the row of `key`: the drag controller lifts its items (`begin_by_id`,
        source "arrivals": every well lit) and the tray fades while it runs (`tray-fade`), back once it ends."""
        moves = self._moves()
        a = self.arrival(key)
        if moves is None or a is None:
            return False
        row = self.view.row_of(key)
        size = row_parts(self.view.visualRect(self.model.index(row, 0)))["row"].size() if row >= 0 else None
        title, ids = a.title, list(a.item_ids)
        if key in self.picks and len(self.picks) > 1:       # A4: a picked row carries every pick, in the tray's order
            title, ids = self._many(self.picked())
        if not moves.begin_by_id(ids, "arrivals", title, global_pos, size):
            return False
        self.clear_picks()
        self._dragging = True
        pix = self.grab()
        if self.fade is None:
            self.fade = _Fade(self.parentWidget(), pix, self.geometry())
        else:
            self.fade.pix = pix
            self.fade.setGeometry(self.geometry())
        self.fade.set_alpha(1.0)
        self.fade.show()
        self.fade.raise_()
        self.hide()
        fade = self.fade
        motion.clock().animate(theme.MOTION["tray-fade"], lambda k: fade.set_alpha(1.0 - k), on_done=fade.hide,
                               kind="fade", owner=fade, on_end=fade.hide)
        self._drag_watch.start()
        return True

    def _drag_ended(self):
        moves = self._moves()
        if moves is not None and moves.running is not None:
            return
        self._drag_watch.stop()
        if self.fade is not None:
            self.fade.hide()
        if not self._dragging:
            return
        self._dragging = False
        if self.groups and self.inset.count:        # back where it was, still open (A2 #27), never animated again
            self._apply()
            self.place()
            QWidget.setVisible(self, True)
            self.raise_()
        else:
            self.inset.set_lit(False)


class _HeadObj:
    """A group head's row in the model: the same object while its words are (its row never repainted for nothing)."""
    __slots__ = ("kind", "label")

    def __init__(self, kind, label):
        self.kind, self.label = kind, label
