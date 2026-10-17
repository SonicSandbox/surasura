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
  *Finished* · *Open its folder* · *Remove…*). Every placement goes through the window's writer (`moves.Writer.place`,
  S2) by the drag controller's tickets (its toast and Undo); *Finished* offers D14's choice as W3.1a's finish toast does
  (IK-11); *Remove…* asks first (`confirm.ask`, naming the count), then `Writer.remove` with Undo. A press and
  `drag-start-px` on a row drags it (`DragController.begin_by_id`: the list's gaps, the wells) while the tray fades
  (`tray-fade`), back once the drag ends. It stays open after a placement; ✕, Esc, Back and a click outside close it;
  Tab goes through the rows, Enter is the row's icon, the menu key its ⋯.
- **The numbers** (`ArrivalNumbers`): each arrival's files asked of the warm worker
  (`app/services/arrivals.ArrivalsWorker.estimate`) once each, when the arrival first shows, each with the piece's
  earlier files placed before it (IK-5) — the asks on a worker, never the window's thread; the answers kept by (item,
  the answer's plan signature, the known words' signature) (IK-10) and handed to the reader (`set_estimates`), whose
  next view fills the rows' numbers. A failed answer shows nothing (the dash stays).

Strings from `strings.py`, colours and sizes from `theme.py`; nothing here reads or writes the store.
"""
import math
import os
import threading

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from app import theme
from app.qt import motion, rows, shadow, strings, style
from app.qt import covers as qcovers                 # --- W3.2 L3: the titles' own pictures (Q6's door)
from app.services import view_rows

COVERS = 3                                  # tiny covers in the inset


def _fz():
    return theme.text_factor(style.current()[1])


# --- the choices (pure: the tests' and a light mutant pass's targets) --------------------------------------------- #
def inset_titles(arrivals, n=COVERS):
    """The inset's covers: the newest `n` arrivals' cover titles, newest first (the tray's order puts *New* first;
    the covers follow `added_at` across both groups)."""
    ordered = sorted(arrivals, key=lambda a: a.added_at or "", reverse=True)
    return tuple((a.cover_title or a.title or "") for a in ordered[:n])


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
    """The estimate requests for an arrival's files: [(item_id, path, placed, chained)] — each file with the piece's
    earlier files placed before it (IK-5: a show counts what each episode brings after the ones before it)."""
    paths = [os.path.join(data_path, *(rel or "").split("/")) for rel in arrival.rel_paths]
    return [(item_id, paths[k], paths[:k], k > 0) for k, item_id in enumerate(arrival.item_ids)]


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
class ArrivalNumbers:
    """The arrivals' estimates, asked of the warm worker (`client.estimate(path, placed, callback)`) once per file and
    kept by (item id, the answer's plan signature, the known words' signature) — IK-10. `want(arrivals)` (the window's
    thread, cheap) asks for the files not asked yet, on a worker; each answer lands in `kept` and the estimates under
    the newest signature go to `on_change({item_id: N new})` (the reader's `set_estimates`), on the answer's thread.
    `recheck()` (the tray opening): the known words' file and the plan's version read again; when either moved, every
    shown file is asked again (the worker keeps its own answers: an unchanged file is answered from its cache).
    `run(fn)`: how a task leaves the window's thread (a test's). `client` / `language` may be callables, read at each
    ask (N3: the window's own, as they stand)."""

    def __init__(self, client, language, on_change=None, data_path=None, known_file=None, plan_token=None,
                 run=None):
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

    def want(self, arrivals, force=False):
        """The window's newest arrivals (`View.arrivals`): a task for the files not asked yet (or all, `force`)."""
        arrivals = tuple(arrivals or ())
        with self._lock:
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
                for item_id, path, placed, chained in asks_for(a, self.data_path()):
                    self._asked.add(item_id)
                    todo.append((item_id, path, placed, chained))
        known = token[1] if token else None
        client = self.client if todo else None
        language = self.language if todo else None
        for item_id, path, placed, chained in todo:
            self.requests += 1
            try:
                client.estimate(path, placed=placed,
                                     callback=lambda ans, i=item_id, c=chained, k=known, l=language:
                                     self._answer(i, c, k, ans, l))
            except Exception as e:                  # a client that can't take it: the dash stays
                print(f"New arrivals: an estimate couldn't be asked: {e!r}")

    def _answer(self, item_id, chained, known, answer, language=None):
        n = answer_number(answer, chained)
        if n is None:
            return                                  # a failure shows nothing (never an error)
        if language is not None and language != self.language:
            return                                  # W3.2 H: asked before a switch — another library's item ids
        sig = (answer.get("plan"), known)
        with self._lock:
            self.kept[(item_id, sig[0], sig[1])] = n
            self._sig = sig
            self.answers += 1
            out = self.estimates_locked()
            if out == self._handed:
                return                              # S2: nothing moved, nothing handed on (no build)
            self._handed = out
        if self.on_change is not None:
            try:
                self.on_change(out)
            except Exception as e:
                print(f"New arrivals: the numbers couldn't be handed on: {e!r}")

    def estimates_locked(self):
        sig = self._sig
        return {i: n for (i, p, k), n in self.kept.items() if (p, k) == sig}

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
        self.keys = ()
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
        titles = inset_titles(arrivals)
        keys = tuple(a.key for a in arrivals)
        refs = tuple(getattr(a, "cover", None) for a in               # --- W3.2 L3: the newest's records, in order
                     sorted(arrivals, key=lambda a: a.added_at or "", reverse=True)[:COVERS])
        if count == self.count and titles == self.titles and set(keys) == set(self.keys) and refs == self.refs:
            self.keys = keys
            return False
        self.refs = refs                                                # --- end W3.2 L3
        new = [k for k in keys if k not in set(self.keys)]
        moved = self._had and count > 0 and bool(new) and self.window().isVisible()
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
            newest = {a.key for a in sorted(arrivals, key=lambda a: a.added_at or "", reverse=True)[:COVERS]}
            self.fresh = len(newest & set(new))
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


# --- the tray's parts ------------------------------------------------------------------------------------------------ #
class _Square(QToolButton):
    """An icon square (↑ Top, ✓ Finished, ⋯): one size on every row, painted; named first in its tooltip (A2 #95,
    #118)."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # the row takes the keyboard: Enter is its icon
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        side = round(theme.size("icon-square", style.current()[1]))
        self.setFixedSize(side, side)

    def set_kind(self, kind, name, tip):
        if (kind, name, tip) != (self.kind, self.accessibleName(), self.toolTip()):
            self.kind = kind
            self.setAccessibleName(name)
            self.setToolTip(tip)
            self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hot = self.underMouse() or self.isDown()
        if self.kind != "more":
            p.setPen(QPen(rows.c("line-hi"), 1))
            p.setBrush(rows.c("overlay-hover") if hot else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, theme.RADII["icon-button"], theme.RADII["icon-button"])
        elif hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rows.c("overlay-hover"))
            p.drawRoundedRect(r, theme.RADII["icon-button"], theme.RADII["icon-button"])
        s = min(r.width(), r.height()) * 0.52
        box = QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s)
        colour = rows.c("ok") if self.kind == "finished" else rows.c("ink") if hot else rows.c("overlay-ink-dim")
        rows.icon(p, {"top": "up", "finished": "check", "more": "more"}[self.kind], box, colour)
        p.end()


class _Number(QWidget):
    """The big *N new / ep* in its fixed column; its tooltip says the episode count and that it's an estimate."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = (strings.TRAY_NUMBER_NONE, "")
        self.setFixedWidth(round(theme.size("arrival-number", style.current()[1])))

    def set_number(self, text, tip):
        if text != self.text or tip != self.toolTip():
            self.text = text
            self.setToolTip(tip)
            self.setAccessibleName(" ".join(text))
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        big, unit = self.text
        h = self.height()
        fb = rows.TEXT.metrics("arrival-number")
        fu = rows.TEXT.metrics("new-per-episode")
        total = fb.height() + fu.height() - 4
        y0 = (h - total) / 2
        dash = big == strings.TRAY_NUMBER_NONE
        rows.TEXT.draw(p, 0, y0 + fb.height() / 2, big, "arrival-number", self.width(),
                       rows.c("overlay-ink-faint" if dash else "ink"), align="right", elide=False)
        rows.TEXT.draw(p, 0, y0 + fb.height() - 4 + fu.height() / 2, unit, "new-per-episode", self.width(),
                       rows.c("overlay-ink-dim"), align="right")
        p.end()


class TrayRow(QWidget):
    """One arrival: cover · title · its one line · the number · the icon · ⋯. A press and `drag-start-px` drags it."""

    def __init__(self, tray, arrival, parent=None):
        super().__init__(parent)
        self.tray = tray
        self.arrival = None
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.number = _Number(self)
        self.icon = _Square("top", self)
        self.icon.clicked.connect(lambda _c=False: self.tray.act(self.arrival, icon_of(self.arrival)))
        self.more = _Square("more", self)
        self.more.setAccessibleName(strings.TRAY_MORE_NAME)
        self.more.setToolTip(strings.TRAY_MORE_TIP)
        self.more.clicked.connect(lambda _c=False: self.tray.menu(self))
        self._press = None
        self.paints = 0
        self.set_arrival(arrival)

    def set_arrival(self, arrival):
        """-> True when it changed (repainted only then)."""
        if arrival is self.arrival:
            return False
        self.arrival = arrival
        kind = icon_of(arrival)
        name, tip = strings.TRAY_ICON[kind]
        self.icon.set_kind(kind, name, tip)
        self.number.set_number(number_text(arrival), arrival.tip)
        self.setAccessibleName(arrival.accessible)
        self.paints += 1
        self.update()
        return True

    def _m(self):
        f = _fz()
        vpad, hpad = theme.SPACING["tray-row"]
        cw = round(theme.size("row-cover-w", style.current()[1]))
        ch = round(theme.size("row-cover-h", style.current()[1]))
        return {"v": round(vpad * f), "h": round(hpad * f), "cw": cw, "ch": ch, "gap": round(12 * f),
                "to_number": round(theme.size("title-to-number", style.current()[1])), "sq_gap": round(6 * f)}

    def sizeHint(self):
        m = self._m()
        return QSize(m["cw"], m["ch"] + 2 * m["v"])         # as wide as the tray makes it

    def resizeEvent(self, event):
        super().resizeEvent(event)
        m = self._m()
        h = self.height()
        x = self.width() - m["h"] - self.more.width()
        self.more.move(x, (h - self.more.height()) // 2)
        x -= m["sq_gap"] // 2 + self.icon.width()
        self.icon.move(x, (h - self.icon.height()) // 2)
        x -= m["sq_gap"] + self.number.width()
        self.number.setGeometry(x, 0, self.number.width(), h)

    def text_right(self):
        """Where the title and its line must stop: 28 · fz short of the number (A2 #96)."""
        return self.number.x() - self._m()["to_number"]

    def paintEvent(self, _event):
        a = self.arrival
        m = self._m()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        dpr = self.devicePixelRatioF() or 1.0
        r = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        if self.underMouse() or self.hasFocus():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rows.c("overlay-hover"))
            p.drawRoundedRect(r, theme.RADII["r-sm"], theme.RADII["r-sm"])
        if self.hasFocus():
            p.setPen(QPen(rows.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), theme.RADII["r-sm"], theme.RADII["r-sm"])
        x = m["h"]
        cy = (self.height() - m["ch"]) / 2
        p.drawPixmap(QPointF(x, cy), qcovers.pixmap_for(getattr(a, "cover", None), a.cover_title or a.title,   # W3.2 L3
                                                        m["cw"], m["ch"], dpr, "row"))
        x += m["cw"] + m["gap"]
        right = self.text_right()
        width = max(0, right - x)
        fm_t = rows.TEXT.metrics("row-title")
        fm_l = rows.TEXT.metrics("row-sub")
        block = fm_t.height() + 2 + fm_l.height()
        y_title = (self.height() - block) / 2 + fm_t.height() / 2
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
        p.end()

    # --- the hand and the keys ---------------------------------------------------------------------------------- #
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            d = event.position() - self._press
            if math.hypot(d.x(), d.y()) >= theme.MOTION["drag-start-px"]:
                self._press = None
                self.tray.start_drag(self, event.globalPosition().toPoint())
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.tray.act(self.arrival, icon_of(self.arrival))
            return
        if key == Qt.Key.Key_Menu or (key == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.tray.menu(self)
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()


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
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("trayscroll")
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setAutoFillBackground(False)
        self.body = QWidget()
        self.body.setObjectName("traybody")
        self.body.setAutoFillBackground(False)
        self.body.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.list = QVBoxLayout(self.body)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(round(2 * f))
        self.scroll.setWidget(self.body)
        box.addWidget(self.scroll, 1)
        self.groups = ()                    # the view's arrival_groups shown
        self.rows = {}                      # arrival key -> TrayRow
        self.heads = {}                     # group kind -> (its head widget, its label, its button or None)
        self.last_menu = None
        self.mine_too = None                # P4.1: *Mine them too* (A2 behaviour 101), `mine_too(item_ids)`; None: hidden
        self.question = None                # Remove's confirmation, while it asks
        self.fade = None
        self._dragging = False
        self._drag_watch = QTimer(self)
        self._drag_watch.setInterval(30)
        self._drag_watch.timeout.connect(self._drag_ended)
        self.paints = 0
        self.shadow = shadow.Follower(self, self.shadow_name)
        self._away = _Away(self)
        parent.installEventFilter(self)
        qcovers.notifier().ready.connect(self._cover_ready)        # --- W3.2 L3
        self.hide()

    # --- W3.2 L3: a picture landing repaints only the rows of that title
    def _cover_ready(self, work_id):
        for row in self.rows.values():
            if row.arrival is not None and row.arrival.work_id == work_id:
                row.update()
    # --- end W3.2 L3

    # --- what it shows ------------------------------------------------------------------------------------------- #
    def set_groups(self, groups):
        """The reader's `View.arrival_groups`. -> True when anything changed: only the rows whose arrival is a new
        object are repainted; an unchanged view (the same tuple, S1's cache) touches nothing (S19)."""
        if groups is self.groups:
            return False
        flat = [a for g in groups for a in g.rows]
        keys = {a.key for a in flat}
        for key in [k for k in self.rows if k not in keys]:
            row = self.rows.pop(key)
            self.list.removeWidget(row)
            row.deleteLater()
        for kind in [k for k in self.heads if k not in {g.kind for g in groups}]:
            head = self.heads.pop(kind)[0]
            self.list.removeWidget(head)
            head.deleteLater()
        order = []
        for g in groups:
            order.append(self._head(g))
            for a in g.rows:
                row = self.rows.get(a.key)
                if row is None:
                    row = self.rows[a.key] = TrayRow(self, a, self.body)
                else:
                    row.set_arrival(a)
                order.append(row)
        current = [self.list.itemAt(i).widget() for i in range(self.list.count())]
        if current != order:
            for w in order:
                self.list.removeWidget(w)
            for w in order:
                self.list.addWidget(w)
                w.show()
        self.groups = groups
        self.paints += 1
        if self.isVisible():
            self.place()
        return True

    def _head(self, group):
        held = self.heads.get(group.kind)
        if held is None:
            head = QWidget(self.body)
            row = QHBoxLayout(head)
            f = _fz()
            row.setContentsMargins(round(8 * f), round(6 * f), round(4 * f), round(2 * f))
            label = QLabel(group.label.upper(), head)
            label.setObjectName("popeyebrow")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # never wider than the tray
            row.addWidget(label, 1)
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
        lay.activate()
        self.body.adjustSize()
        content = self.body.sizeHint().height()
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
        self.place()
        return super().open()

    def toggle(self):
        if self.isVisible() or motion.opening_of(self) is not None:
            self.close()
        else:
            self.open()

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self._away)
        self.inset.set_lit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().removeEventFilter(self._away)
        if not self._dragging:
            self.inset.set_lit(False)

    def closeEvent(self, event):
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
        """*Open its folder*: looked for on a worker first (a drive may be slow or gone, N4), then opened — or said."""
        from app.qt import bridge, windows
        path = self.folder_of(arrival)

        def found(there):
            if not there or not windows.open_url(path):
                say = getattr(self.win, "say", None)
                if say is not None:
                    say(strings.TRAY_NO_FOLDER.format(path=path))
        bridge.run_in_worker(os.path.isdir, path, then=found, failed=lambda _info: found(False))

    def _has_show(self, arrival):
        """Whether a part of the arrival's title is in Current (the view's rows), N1."""
        page = getattr(self.win, "page_widgets", {}).get("current")
        view = getattr(page, "view_model", None)
        return arrival.work_id is not None and view is not None and any(
            r.work_id == arrival.work_id and r.tier in ("now", "soon") for r in view.rows)

    def menu(self, row):
        """⋯: a plain menu in the theme's style (Esc closes it), its entries' tips shown."""
        a = row.arrival
        moves = self._moves()
        writable, reason = True, None
        if moves is None or not moves.writer.can_write():
            writable = False
            raw = (moves.writer.reason() if moves is not None else None) or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        m = QMenu(row)
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
        m.popup(row.more.mapToGlobal(QPoint(0, row.more.height())))
        return m

    # --- a drag from it ---------------------------------------------------------------------------------------------- #
    def start_drag(self, row, global_pos):
        """A press travelled `drag-start-px` on `row`: the drag controller lifts its items (`begin_by_id`, source
        "arrivals": every well lit) and the tray fades while it runs (`tray-fade`), back once it ends."""
        moves = self._moves()
        if moves is None:
            return False
        a = row.arrival
        if not moves.begin_by_id(list(a.item_ids), "arrivals", a.title, global_pos, QSize(row.width(), row.height())):
            return False
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
            self.place()
            QWidget.setVisible(self, True)
            self.raise_()
        else:
            self.inset.set_lit(False)
