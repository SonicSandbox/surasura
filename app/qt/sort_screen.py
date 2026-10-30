"""Setup's load screen and the sort screen (Sonic 2026-10-30).

- **`LoadScreen`**: a calm, full cover over the setup wizard after its library step. The Surasura mark (breathing on
  the one clock; still under Reduced motion and the freeze switch), ONE task line with its live count (`set_task`) and
  a gentle line that fades out and in every `LINE_MS` (`LOAD_LINES`; Reduced motion: it changes without the fade, as
  the clock's "fade" kind keeps it short). Nothing in it acts but the quiet *Stop* (`stop` signal). The steps, their
  order and their counts are the wizard's (`SetupWizard._load_*`): this widget paints what it is told, and repaints
  only what changed (S19).
- **`SortScreen`**: every title in New arrivals (the reader's `arrival_groups`, followed as the window gets each view —
  `set_groups`), large: the title at the top is the one the keys act on — it looks picked (the window's `row-picked`
  wash, the accent edge) with a gap under it — then the next few, then *and N more*. Its five choices **Current · Soon
  · Goal · Finished · Ignore** (buttons on the top title, keys **→ S ↓ ↑ ←**, shown on screen), *Put the rest in…*,
  *Undo* (Ctrl+Z), *Done*. A choice takes the title off at once (pending — the press rule) and the next comes up; a
  refused one comes back. **It decides nothing:** every placement is New arrivals' own (`arrivals.give_place`,
  `item_menu.give_skip`, `MovesController.undo_last`), through the window's writer. Opened by setup (after the load
  screen) and by New arrivals' *Sort them all…* (`open_over(win)`): one screen, both doors.
"""
import math
import os

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget)

from app import path_utils, theme
from app.qt import motion, style
from app.qt import wizard_strings as S

LINE_MS = 6500                  # a gentle line stays this long, then fades out and the next fades in
FADE_MS = 700                   # each half of its fade
BREATHE_MS = 4200               # the mark's slow breathe, one full cycle
NEXT_SHOWN = 6                  # titles shown under the top one; the rest are "and N more"
COVER_W, COVER_H = 132, 186     # the top title's cover (× the text size); the next ones' are a third of it
KEYS = {Qt.Key.Key_Right: "now", Qt.Key.Key_S: "soon", Qt.Key.Key_Down: "goal", Qt.Key.Key_Up: "finished",
        Qt.Key.Key_Left: "ignore"}
PLACE_OF = {"now": "top", "soon": "soon", "goal": "goal", "finished": "finished"}   # `moves.PLACES`' names


def _f():
    return theme.text_factor(style.current()[1])


def _px(n):
    return round(n * _f())


def _c(name):
    return style.qcolor(style.colours()[name])


def sheet():
    """The two screens' own rules (every colour a theme token), scoped to their object names."""
    c = {k: style.qss_colour(v) for k, v in theme.colours().items()}
    from app.qt import rows
    q = rows.c("row-picked")                          # the window's picked wash (a picked row's, Goal's sheet's)
    picked = f"rgba({q.red()}, {q.green()}, {q.blue()}, {q.alpha()})"
    f = _f()

    def font(role, weight=None, scale=1.0):
        size, drawn = theme.font(role, style.current()[1])
        return f"font-size: {round(size * scale * style.PT_PER_PX, 3)}pt; font-weight: {weight or drawn};"
    return f"""
QWidget#loadscreen, QWidget#sortscreen {{ background: {c['bg']}; }}
QLabel#loadtask {{ color: {c['ink']}; {font('hero-sub', 500, 1.35)} }}
QLabel#loadline {{ color: {c['ink-dim']}; {font('hero-sub', 400, 1.2)} }}
QLabel#sorttitle {{ color: {c['ink']}; {font('first-run-heading', 600, 1.3)} }}
QLabel#sortline, QLabel#sortcount, QLabel#sortmore {{ color: {c['ink-dim']}; {font('hero-sub')} }}
QLabel#sortgroup {{ color: {c['accent']}; {font('eyebrow')} letter-spacing: 1px; }}
QLabel#sortname {{ color: {c['ink']}; {font('first-run-heading', 600, 1.05)} }}
QLabel#sortsub {{ color: {c['ink-dim']}; {font('row-sub')} }}
QLabel#sortnext {{ color: {c['ink-dim']}; {font('row-title', 500)} }}
QLabel#sortsaid {{ color: {c['ink-dim']}; {font('footer')} }}
QLabel#sortkey {{ color: {c['ink']}; background: {c['raised']}; border: 1px solid {c['line-hi']};
  border-radius: {round(4 * f)}px; padding: 0 {round(6 * f)}px; {font('key-hint')} }}
QLabel#sortkeyword {{ color: {c['ink-dim']}; {font('footer')} }}
QWidget#sorttop {{ background: {picked}; border-left: {max(2, round(3 * f))}px solid {c['accent']};
  border-radius: {round(8 * f)}px; }}
QPushButton#loadstop, QPushButton#sortquiet {{ background: transparent; border: 0; color: {c['ink-dim']};
  padding: 0 {round(10 * f)}px; {font('button', 400)} }}
QPushButton#loadstop:hover, QPushButton#sortquiet:hover {{ color: {c['ink']}; }}
QPushButton#loadstop:focus, QPushButton#sortquiet:focus {{ border: 2px solid {c['accent']}; border-radius: 6px; }}
QPushButton#loadstop:disabled {{ color: {c['ink-faint']}; }}
QPushButton#sortchoice {{ min-width: {round(96 * f)}px; min-height: {round(38 * f)}px; {font('button', 650)} }}
"""


def _label(name, text="", parent=None, wrap=False):
    lab = QLabel(text, parent)
    lab.setObjectName(name)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setWordWrap(wrap)
    return lab


def _button(text, tip, slot, parent, name=None):
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    b.setAccessibleName(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoDefault(False)
    b.setDefault(False)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if name:
        b.setObjectName(name)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _set(label, text):
    """A label's text, only when it changed (S19)."""
    if label.text() != text:
        label.setText(text)


# --- the mark -------------------------------------------------------------------------------------------------------- #
class Mark(QWidget):
    """The Surasura mark, breathing slowly (its opacity 0.7–1.0) on the one clock while shown; still at full under
    Reduced motion (the clock never starts a loop then) and the freeze switch."""

    def __init__(self, size=96, parent=None):
        super().__init__(parent)
        self.setFixedSize(_px(size), _px(size))
        self._pix = None
        self.level = 1.0
        self._anim = None
        self.setAccessibleName("Surasura")

    def _pixmap(self):
        if self._pix is None:
            dpr = self.devicePixelRatioF() or 1.0
            path = os.path.join(path_utils.get_app_root(), "app", "assets", "images", "app_icon.png") \
                if hasattr(path_utils, "get_app_root") else ""
            if not path or not os.path.exists(path):
                path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "images",
                                    "app_icon.png")
            pix = QPixmap(path)
            if not pix.isNull():
                pix = pix.scaled(round(self.width() * dpr), round(self.height() * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                pix.setDevicePixelRatio(dpr)
            self._pix = pix
        return self._pix

    def showEvent(self, event):
        super().showEvent(event)
        if self._anim is None or not self._anim.alive:
            self._anim = motion.clock().animate(BREATHE_MS, self._breathe, kind="loop", repeat=True, owner=self,
                                                points="linear")

    def hideEvent(self, event):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self.level = 1.0
        super().hideEvent(event)

    def _breathe(self, phase):
        level = 0.85 + 0.15 * math.cos(phase * 2 * math.pi)
        if abs(level - self.level) >= 0.01:          # repaint only when it shows (S19)
            self.level = level
            self.update()

    def paintEvent(self, _event):
        pix = self._pixmap()
        if pix is None or pix.isNull():
            return
        p = QPainter(self)
        p.setOpacity(self.level)
        p.drawPixmap(0, 0, pix)


# --- the load screen ------------------------------------------------------------------------------------------------- #
class LoadScreen(QWidget):
    """The load's calm cover (module docstring). `set_task(text)`; `stopping()` after *Stop*; `stop` when pressed."""
    stop = pyqtSignal()

    def __init__(self, parent=None, lines=S.LOAD_LINES):
        super().__init__(parent)
        self.setObjectName("loadscreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(sheet())
        self.setAccessibleName(S.LOAD_NAME)
        self.lines, self.line_at = tuple(lines), 0
        box = QVBoxLayout(self)
        box.setContentsMargins(_px(40), _px(40), _px(40), _px(28))
        box.addStretch(3)
        self.mark = Mark(96, self)
        box.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addSpacing(_px(28))
        self.task = _label("loadtask", "", self)
        self.task.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(self.task)
        box.addSpacing(_px(14))
        self.line = _label("loadline", self.lines[0] if self.lines else "", self)
        self.line.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._fade = QGraphicsOpacityEffect(self.line)
        self._fade.setOpacity(1.0)
        self.line.setGraphicsEffect(self._fade)
        box.addWidget(self.line)
        box.addStretch(4)
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_stop = _button(S.LOAD_STOP, S.LOAD_STOP_TIP, self._stop, self, name="loadstop")
        foot.addWidget(self.btn_stop)
        box.addLayout(foot)
        self._timer = QTimer(self)
        self._timer.setInterval(LINE_MS)
        self._timer.timeout.connect(self.next_line)
        self._anim = None

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def set_task(self, text):
        _set(self.task, text)
        self.task.setAccessibleName(text)

    def stopping(self):
        self.btn_stop.setEnabled(False)
        _set(self.btn_stop, S.LOAD_STOPPING)

    def _stop(self):
        if self.btn_stop.isEnabled():
            self.stopping()
            self.stop.emit()

    def next_line(self):
        """The next gentle line: the one shown fades out, the next fades in (Reduced motion: the clock keeps the
        fade short)."""
        if len(self.lines) < 2:
            return
        self.line_at = (self.line_at + 1) % len(self.lines)
        text = self.lines[self.line_at]
        if self._anim is not None:
            self._anim.stop()

        def out(v):
            if not sip.isdeleted(self._fade):
                self._fade.setOpacity(1.0 - v)

        def swap():
            if sip.isdeleted(self.line):
                return
            _set(self.line, text)
            self._anim = motion.clock().animate(FADE_MS, lambda v: not sip.isdeleted(self._fade)
                                                and self._fade.setOpacity(v), kind="fade", owner=self.line)
        self._anim = motion.clock().animate(FADE_MS, out, on_done=swap, kind="fade", owner=self.line)


# --- the sort screen ------------------------------------------------------------------------------------------------- #
class _Cover(QWidget):
    """A title's cover through the window's one door (`covers.pixmap_for`): its own picture once decoded, the
    generated one meanwhile; repainted when its decode lands."""

    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setFixedSize(_px(w), _px(h))
        self.arrival = None

    def set_arrival(self, a):
        if a is not self.arrival:
            self.arrival = a
            self.update()

    def paintEvent(self, _event):
        a = self.arrival
        if a is None:
            return
        from app.qt import covers as qcovers
        dpr = self.devicePixelRatioF() or 1.0
        shape = "tile" if self.width() > _px(60) else "row"
        pix = qcovers.pixmap_for(getattr(a, "cover", None), getattr(a, "cover_title", None) or a.title,
                                 self.width(), self.height(), dpr, shape, on_ready=self._ready)
        if pix is not None and not pix.isNull():
            QPainter(self).drawPixmap(0, 0, pix)

    def _ready(self):
        if not sip.isdeleted(self):
            self.update()


def _rows_of(groups):
    """[(group kind, arrival)] in New arrivals' order (its groups, each newest first)."""
    return [(g.kind, a) for g in groups or () for a in g.rows]


def _sub_line(a):
    """The top title's line: its files and where they are (K7's folder, when the looks named it)."""
    n = len(getattr(a, "item_ids", ()) or ())
    word = getattr(a, "media_word", None) or "files"
    parts = [f"{n:,} {word}" if n != 1 else f"1 {str(word).rstrip('s')}"]
    if getattr(a, "line", None):
        parts.append(str(a.line))
    if getattr(a, "folder", None):
        parts.append(str(a.folder))
    return " · ".join(parts)


class SortScreen(QWidget):
    """Every title in New arrivals, sorted one at a time from the top (module docstring). `win`: the main window (its
    `moves`, `looks`, `language`); `door`: "setup" (Esc does nothing — setup's rule, WZ-6 — and *Done* goes on) or
    "arrivals" (Esc and ✕ close). `closed(how)`: "done" / "closed" / "empty"."""
    closed = pyqtSignal(str)

    def __init__(self, win, parent=None, door="setup"):
        super().__init__(parent)
        self.win, self.door = win, door
        self.setObjectName("sortscreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(sheet())
        self.setAccessibleName(S.SORT_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.groups = ()
        self.hidden = {}            # key -> the action it went with (pending until the view lets it go)
        self.history = []           # [(keys, name, title)] newest last: Undo's order
        self.rows = []
        self._shown = None
        self.heard = False          # a view with titles came (until then an empty list says nothing: not "All sorted")
        self._build()
        if win is not None:
            win.__dict__["_sort_screen"] = self     # the window hands it each view's groups (`_show_arrivals`)
            view = win.__dict__.get("_arrivals_view")
            groups = getattr(view, "arrival_groups", ()) if view is not None else ()
            if groups:
                self.set_groups(groups)

    # --- building ------------------------------------------------------------------------------------------------ #
    def _build(self):
        box = QVBoxLayout(self)
        box.setContentsMargins(_px(56), _px(36), _px(56), _px(24))
        box.setSpacing(0)
        head = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(_px(4))
        words.addWidget(_label("sorttitle", S.SORT_TITLE, self))
        words.addWidget(_label("sortline", S.SORT_LINE, self))
        head.addLayout(words, 1)
        self.count = _label("sortcount", "", self)
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        box.addLayout(head)
        box.addSpacing(_px(24))
        # the top title: picked (the window's wash, the accent edge), its cover, words and the five choices
        self.top = QWidget(self)
        self.top.setObjectName("sorttop")
        self.top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(_px(22), _px(18), _px(22), _px(18))
        tl.setSpacing(_px(22))
        self.top_cover = _Cover(COVER_W, COVER_H, self.top)
        tl.addWidget(self.top_cover)
        tw = QVBoxLayout()
        tw.setSpacing(_px(6))
        self.top_group = _label("sortgroup", "", self.top)
        tw.addWidget(self.top_group)
        self.top_name = _label("sortname", "", self.top, wrap=True)
        tw.addWidget(self.top_name)
        self.top_sub = _label("sortsub", "", self.top, wrap=True)
        tw.addWidget(self.top_sub)
        tw.addStretch(1)
        choices = QHBoxLayout()
        choices.setSpacing(_px(10))
        self.choice_buttons = {}
        for name, label, tip, key in S.SORT_CHOICES:
            b = _button(f"{label}   {key}", f"{tip}\n• {key}", lambda n=name: self.choose(n), self.top,
                        name="sortchoice")
            b.setAccessibleName(label)
            choices.addWidget(b)
            self.choice_buttons[name] = b
        choices.addStretch(1)
        tw.addLayout(choices)
        tl.addLayout(tw, 1)
        box.addWidget(self.top)
        box.addSpacing(_px(18))     # the gap that sets the top title apart
        self.next_box = QVBoxLayout()
        self.next_box.setSpacing(_px(8))
        self.next_rows = []
        for _i in range(NEXT_SHOWN):
            w = QWidget(self)
            line = QHBoxLayout(w)
            line.setContentsMargins(_px(25), 0, 0, 0)
            line.setSpacing(_px(14))
            cov = _Cover(COVER_W // 3, COVER_H // 3, w)
            line.addWidget(cov)
            name = _label("sortnext", "", w)
            line.addWidget(name, 1)
            w.setVisible(False)
            self.next_box.addWidget(w)
            self.next_rows.append((w, cov, name))
        self.more = _label("sortmore", "", self)
        self.more.setContentsMargins(_px(25), 0, 0, 0)
        self.next_box.addWidget(self.more)
        box.addLayout(self.next_box)
        self.empty = _label("sortname", S.SORT_EMPTY, self)
        self.empty.setVisible(False)
        box.addWidget(self.empty)
        box.addStretch(1)
        # the foot: the keys, what was just done with Undo, Put the rest in…, Done
        foot = QHBoxLayout()
        foot.setSpacing(_px(8))
        for _name, label, _tip, key in S.SORT_CHOICES:
            foot.addWidget(_label("sortkey", key, self))
            foot.addWidget(_label("sortkeyword", label, self))
            foot.addSpacing(_px(10))
        foot.addWidget(_label("sortkey", "Ctrl+Z", self))
        foot.addWidget(_label("sortkeyword", S.SORT_UNDO, self))
        foot.addStretch(1)
        self.said = _label("sortsaid", "", self)
        foot.addWidget(self.said)
        self.btn_undo = _button(S.SORT_UNDO, S.SORT_UNDO_TIP, self.undo, self, name="sortquiet")
        self.btn_undo.setEnabled(False)
        foot.addWidget(self.btn_undo)
        self.btn_rest = _button(S.SORT_REST, S.SORT_REST_TIP, self._rest_menu, self, name="sortquiet")
        foot.addWidget(self.btn_rest)
        self.btn_done = _button(S.SORT_DONE, S.SORT_DONE_TIP if self.door == "setup" else S.SORT_CLOSE_TIP,
                                lambda: self.finish("done"), self)
        self.btn_done.setProperty("kind", "primary")
        foot.addWidget(self.btn_done)
        box.addSpacing(_px(12))
        box.addLayout(foot)

    # --- what it shows ------------------------------------------------------------------------------------------- #
    def set_groups(self, groups):
        """The reader's `arrival_groups`, as the window got them: a pending title the view no longer holds landed (its
        pending mark goes); one still there stays hidden until it does."""
        self.groups = tuple(groups or ())
        self.heard = self.heard or bool(self.groups)
        present = {a.key for _k, a in _rows_of(self.groups)}
        for key in [k for k in self.hidden if k not in present]:
            del self.hidden[key]
        self._paint()

    def visible_rows(self):
        return [(k, a) for k, a in _rows_of(self.groups) if a.key not in self.hidden]

    def top_arrival(self):
        rows = self.visible_rows()
        return rows[0][1] if rows else None

    def _paint(self):
        rows = self.visible_rows()
        key = tuple((a.key, a.title, getattr(a, "folder", None), len(a.item_ids), getattr(a, "cover", None))
                    for _k, a in rows[:NEXT_SHOWN + 1]) + (len(rows), bool(self.history), self.heard)
        if key == self._shown:
            return                                  # nothing it shows changed (S19)
        self._shown = key
        self.rows = rows
        _set(self.count, S.SORT_COUNT.format(n=len(rows)) if rows else "")
        self.top.setVisible(bool(rows))
        self.empty.setVisible(not rows and self.heard)
        self.btn_rest.setEnabled(len(rows) > 1)
        self.btn_undo.setEnabled(bool(self.history))
        if rows:
            kind, a = rows[0]
            _set(self.top_group, S.SORT_GROUPS.get(kind, ""))
            _set(self.top_name, a.title)
            _set(self.top_sub, _sub_line(a))
            self.top_cover.set_arrival(a)
        for i, (w, cov, name) in enumerate(self.next_rows):
            r = rows[i + 1] if i + 1 < len(rows) else None
            w.setVisible(r is not None)
            if r is not None:
                _set(name, r[1].title)
                cov.set_arrival(r[1])
        more = len(rows) - 1 - NEXT_SHOWN
        _set(self.more, S.SORT_MORE.format(n=more) if more > 0 else "")
        self.more.setVisible(more > 0)

    # --- acting -------------------------------------------------------------------------------------------------- #
    def _moves(self):
        moves = getattr(self.win, "moves", None)
        return moves if moves is not None and moves.refused() is None else None

    def choose(self, name, arrival=None):
        """A choice on the top title (or `arrival`): taken off at once (pending), handed to New arrivals' own call;
        refused — it comes back and the bar says why (the writer's note)."""
        a = arrival or self.top_arrival()
        moves = self._moves()
        if a is None or moves is None or name not in dict((n, 1) for n, *_r in S.SORT_CHOICES):
            return None
        text = S.SORT_PLACED[name].format(title=a.title)
        self.hidden[a.key] = name
        self.history.append(((a.key,), name, a.title))
        self._shown = None
        self._paint()
        _set(self.said, text)
        if name == "ignore":
            self._ignore(a, moves, text)
            return True
        from app.qt import arrivals
        seq = arrivals.give_place(moves, text, list(a.item_ids), PLACE_OF[name], keys=(a.key,), toast=False)
        if seq is None:
            self._refused((a.key,))
        return seq

    def _ignore(self, a, moves, text):
        """← Ignore: the title's own folder never read again (`give_skip`, Q7's) — only a folder holding no other title
        (`looks.skippable(..., own=True)`); else the title taken out of the library (`writer.remove`: its copy to the
        trash, the original where it is, kept out of every later look). One Undo either way."""
        from app.qt import bridge, drag, item_menu
        ids = list(a.item_ids)

        def act(folders):
            if sip.isdeleted(self):
                return
            if folders:
                seq = item_menu.give_skip(moves, folders[0], ids, keys=(a.key,))
            else:
                ticket = drag.Ticket(text, (a.key,), ids)
                seq = moves._give(ticket, lambda t: moves.writer.remove(ids, label=t), toast=False)
            if seq is None:
                self._refused((a.key,))
        looks = getattr(self.win, "looks", None)
        if looks is None or not hasattr(looks, "skippable"):
            act([])
            return
        relay = bridge.Relay(self)

        def found(folders):
            relay.deleteLater()
            act(list(folders or ()))
        relay.said.connect(found)
        try:
            asked = looks.skippable(ids, relay.call, own=True)
        except TypeError:                                   # an older looks: never a folder that may hold others
            asked = False
        if not asked:
            relay.deleteLater()
            act([])

    def _refused(self, keys):
        for k in keys:
            self.hidden.pop(k, None)
        if self.history and tuple(self.history[-1][0]) == tuple(keys):
            self.history.pop()
        _set(self.said, "")
        self._shown = None
        self._paint()

    def rest(self, name):
        """*Put the rest in…* `name`: every title still shown, in one command (one Undo)."""
        rows = self.visible_rows()
        moves = self._moves()
        if not rows or moves is None or name not in PLACE_OF:
            return None
        keys = tuple(a.key for _k, a in rows)
        ids = [i for _k, a in rows for i in a.item_ids]
        label = next(lab for n, lab, *_r in S.SORT_CHOICES if n == name)
        text = S.SORT_REST_PLACED.format(n=len(rows), place=label)
        for k in keys:
            self.hidden[k] = name
        self.history.append((keys, name, text))
        self._shown = None
        self._paint()
        _set(self.said, text)
        from app.qt import arrivals
        seq = arrivals.give_place(moves, text, ids, PLACE_OF[name], keys=keys, toast=False)
        if seq is None:
            self._refused(keys)
        return seq

    def _rest_menu(self):
        m = QMenu(self.btn_rest)
        m.setObjectName("rowmenu")
        m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        for name, label, tip, _key in S.SORT_CHOICES:
            if name in PLACE_OF:
                act = m.addAction(label)
                act.setToolTip(tip)
                act.triggered.connect(lambda _c=False, n=name: self.rest(n))
        self.last_menu = m
        m.popup(self.btn_rest.mapToGlobal(self.btn_rest.rect().topLeft()))
        return m

    def undo(self):
        """Undo (Ctrl+Z): the last choice comes back to the top at once, and the window's own Ctrl+Z undoes it as the
        writer reaches it (`undo_last`)."""
        moves = getattr(self.win, "moves", None)
        if not self.history or moves is None:
            return
        keys, _name, _text = self.history.pop()
        for k in keys:
            self.hidden.pop(k, None)
        moves.undo_last()
        _set(self.said, "")
        self._shown = None
        self._paint()

    def finish(self, how="done"):
        win = self.win
        if win is not None and win.__dict__.get("_sort_screen") is self:
            del win.__dict__["_sort_screen"]
        self.closed.emit(how)


def open_over(win):
    """New arrivals' *Sort them all…*: the sort screen over the window's central area (as the setup wizard covers it),
    following its size; closed by *Done*, Esc or the window's language switch. -> the screen."""
    from app.qt import first_run
    old = win.__dict__.get("_sort_screen")
    if old is not None and not sip.isdeleted(old):
        old.raise_()
        old.setFocus()
        return old
    area = win.centralWidget()
    screen = SortScreen(win, parent=area, door="arrivals")
    screen.setGeometry(area.rect())
    first_run._Cover(screen, area)

    def closed(_how):
        if not sip.isdeleted(screen):
            screen.hide()
            screen.deleteLater()
    screen.closed.connect(closed)
    screen.show()
    screen.raise_()
    screen.setFocus()
    return screen

    def keyPressEvent(self, event):
        if event.isAutoRepeat():                            # one action per press: a held key's repeats are none
            event.accept()
            return
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self.undo()
        elif key in KEYS and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            self.choose(KEYS[key])
        elif key == Qt.Key.Key_Escape and self.door != "setup":
            self.finish("closed")
        else:
            super().keyPressEvent(event)
            return
        event.accept()
