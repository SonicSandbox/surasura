"""Setup's load screen and the sort screen (Sonic 2026-10-30).

- **`LoadScreen`**: a calm, full cover over the setup wizard after its library step. The Surasura mark (its wings
  beating slowly on the one clock, the bird alone repainted; still under Reduced motion and the freeze switch), ONE
  task line with its live count (`set_task`) and
  a gentle line that fades out and in every `LINE_MS` (`LOAD_LINES`; Reduced motion: it changes without the fade, as
  the clock's "fade" kind keeps it short). Nothing in it acts but the quiet *Stop* (`stop` signal). The steps, their
  order and their counts are the wizard's (`SetupWizard._load_*`): this widget paints what it is told, and repaints
  only what changed (S19).
- **`SortScreen`**: every title in New arrivals (the reader's `arrival_groups`, followed as the window gets each view —
  `set_groups`), large: the title at the top is the one the keys act on — it looks picked (the window's `row-picked`
  wash, the accent edge) with a gap under it — then the next few, then *and N more*. Its five choices **Soon · Current
  · Goal · Finished · Ignore** (buttons on the top title, keys **S → ↓ ↑ ←**, shown on screen), *Put the rest in…*,
  *Undo* (Ctrl+Z), *Done*. A choice takes the title off at once (pending — the press rule) and the next comes up; a
  refused one comes back. **It decides nothing:** every placement is New arrivals' own (`arrivals.give_place`,
  `item_menu.give_skip`, `MovesController.undo_last`), through the window's writer. Opened by setup (after the load
  screen) and by New arrivals' *Sort them all…* (`open_over(win)`): one screen, both doors.
"""
import math
import os

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap, QPolygonF
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from app import theme
from app.qt import motion, style
from app.qt import wizard_strings as S

LINE_MS = 6500                  # a gentle line stays this long, then fades out and the next fades in
FADE_MS = 700                   # each half of its fade
FLAP_UPPER, FLAP_LOWER = 9.0, 6.0   # degrees each wing turns about its root at a beat's ends (`MOTION` "mark-flap")
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
QLabel#loadside {{ color: {c['ink-dim']}; {font('hero-sub')} }}
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


# --- the mark ------------------------------------------------------------------------------------------------------- #
# The mark's wings, from app_icon.png's own drawing (512 px; each feather is a shard of its own, apart from the body
# by a clear gap): each feather's outline, 3 px out into its gap, and the point its wing turns about. The upper wing's
# four feathers and the lower wing's two beat; the body and the head never move.
ICON = 512
UPPER_WING = (((44, 18), (49, 17), (177, 88), (243, 179), (243, 182), (238, 183), (91, 94), (73, 74)),
              ((167, 19), (173, 17), (301, 149), (301, 152), (296, 153), (175, 81)),
              ((56, 89), (60, 88), (205, 169), (265, 220), (266, 223), (259, 224), (101, 161), (56, 92)),
              ((106, 179), (114, 177), (213, 210), (267, 244), (263, 248), (152, 233)))
LOWER_WING = (((91, 421), (258, 283), (262, 283), (251, 340), (192, 457), (103, 496)),
              ((252, 348), (293, 326), (294, 329), (248, 419), (234, 435), (221, 444), (203, 450)))
UPPER_ROOT, LOWER_ROOT = (262, 215), (268, 300)
PAD = 0.12                      # room round the bird (a share of its side) for the wing tips at the top of a beat


def _wing_path(shards, scale):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for shard in shards:
        path.addPolygon(QPolygonF([QPointF(x * scale, y * scale) for x, y in shard]))
        path.closeSubpath()
    return path


class Mark(motion.Spinner):
    """The Surasura mark, its wings beating slowly on a seamless loop (Sonic 2026-10-30): on the one clock only while
    shown and its window not minimised (`motion.Spinner`'s rule); still, at rest in the mark's own pose, under Reduced
    motion and the freeze switch. Each frame turns the two wings' own pictures about their roots over the still body —
    three pictures cut once — and it paints every pixel of its own small square (the screen's ground first), so a beat
    repaints this widget alone: no layout, no other widget (S19)."""

    def __init__(self, size=96, parent=None):
        side = _px(size)
        super().__init__("flap", parent, size=side + 2 * round(side * PAD), period="mark-flap")
        self.bird = side
        self.angle = 0.0                # the beat now: -1 … 1 (0 = the mark's own pose)
        self._parts = None
        self.paints = 0                 # paint events (the tests' frame budget)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAccessibleName(S.LOAD_MARK_NAME)
        self.set_running(True)

    def _cut(self):
        """(body, upper wing, lower wing) at this size and pixel ratio, cut once from the icon."""
        if self._parts is None:
            dpr = self.devicePixelRatioF() or 1.0
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "images",
                                "app_icon.png")
            icon = QPixmap(path)
            if icon.isNull():
                self._parts = ()
                return self._parts
            side = round(self.bird * dpr)
            icon = icon.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            scale = icon.width() / ICON
            parts = []
            for shards in (None, UPPER_WING, LOWER_WING):
                pix = QPixmap(icon.size())
                pix.fill(Qt.GlobalColor.transparent)
                p = QPainter(pix)
                if shards is None:                  # the body: the icon with both wings cleared from it
                    p.drawPixmap(0, 0, icon)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                    for wing in (UPPER_WING, LOWER_WING):
                        p.fillPath(_wing_path(wing, scale), Qt.GlobalColor.black)
                else:
                    p.setClipPath(_wing_path(shards, scale))
                    p.drawPixmap(0, 0, icon)
                p.end()
                pix.setDevicePixelRatio(dpr)
                parts.append(pix)
            self._parts = tuple(parts)
        return self._parts

    def _on_frame(self, phase):
        angle = math.sin(phase * 2 * math.pi)
        if abs(angle - self.angle) >= 0.004:        # under a fiftieth of a degree's turn: nothing to paint
            self.angle = angle
            self.update()

    def _sync(self, *_args):
        super()._sync(*_args)
        if not self.on_clock and self.angle:
            self.angle = 0.0                        # stopped: at rest in the mark's own pose
            self.update()

    def paintEvent(self, _event):
        self.paints += 1
        p = QPainter(self)
        p.fillRect(self.rect(), _c("bg"))          # the screen's own ground: opaque, so nothing under it repaints
        parts = self._cut()
        if not parts:
            return
        body, upper, lower = parts
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        o, k = (self.width() - self.bird) / 2, self.bird / ICON
        p.drawPixmap(QPointF(o, o), body)
        for pix, (x, y), turn in ((upper, UPPER_ROOT, -FLAP_UPPER), (lower, LOWER_ROOT, FLAP_LOWER)):
            p.save()
            p.translate(o + x * k, o + y * k)
            p.rotate(turn * self.angle)
            p.translate(-(o + x * k), -(o + y * k))
            p.drawPixmap(QPointF(o, o), pix)
            p.restore()
        p.end()


class _FadeLine(QLabel):
    """The load screen's gentle line: its words in the label's own font and colour, drawn at `level` (0–1) — a fade
    repaints this line alone (the do-not list's T6: never a QGraphicsOpacityEffect)."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("loadline")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.level = 1.0

    def set_level(self, level):
        level = max(0.0, min(1.0, float(level)))
        if abs(level - self.level) >= 0.01 or level in (0.0, 1.0) and level != self.level:
            self.level = level
            self.update()

    def paintEvent(self, _event):
        if self.level <= 0.0:
            return
        p = QPainter(self)
        p.setOpacity(self.level)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.contentsRect(), int(self.alignment()), self.text())
        p.end()


# --- the load screen ------------------------------------------------------------------------------------------------ #
class LoadScreen(QWidget):
    """The load's calm cover (module docstring). `set_task(text)`; `set_side(text)` (alpha 8: what runs beside it —
    setup's YouTube videos — and how it ended; empty: none); `stopping()` after *Stop*; `stop` when pressed."""
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
        self.side = _label("loadside", "", self)
        self.side.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.side.setWordWrap(True)
        self.side.setVisible(False)
        box.addSpacing(_px(6))
        box.addWidget(self.side)
        box.addSpacing(_px(14))
        self.line = _FadeLine(self.lines[0] if self.lines else "", self)
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
        if self.task.text() != text:
            self.task.setText(text)
            self.task.setAccessibleName(text)

    def set_side(self, text):
        text = text or ""
        if self.side.text() != text:
            self.side.setText(text)
            self.side.setAccessibleName(text)
        if self.side.isHidden() == bool(text):
            self.side.setVisible(bool(text))

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

        line = self.line

        def swap():
            if sip.isdeleted(line):
                return
            _set(line, text)
            self._anim = motion.clock().animate(FADE_MS, line.set_level, kind="fade", owner=line)
        self._anim = motion.clock().animate(FADE_MS, lambda v: line.set_level(1.0 - v), on_done=swap, kind="fade",
                                            owner=line)


# --- the sort screen ------------------------------------------------------------------------------------------------ #
class _Cover(QWidget):
    """A title's cover through the window's one door (`covers.pixmap_for`): its own picture once decoded, the
    generated one meanwhile; repainted when its decode lands."""

    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setFixedSize(_px(w), _px(h))
        self.arrival = None

    def set_arrival(self, a):
        shown = self._shows(self.arrival)
        self.arrival = a
        if self._shows(a) != shown:
            self.update()

    @staticmethod
    def _shows(a):
        return None if a is None else (getattr(a, "cover", None), getattr(a, "cover_title", None) or a.title)

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
        self.all = []               # [(group kind, arrival)] in New arrivals' order (`set_groups`)
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
        self.all = _rows_of(self.groups)
        present = {a.key for _k, a in self.all}
        for key in [k for k in self.hidden if k not in present]:
            del self.hidden[key]
        self._paint()

    def visible_rows(self, most=None):
        """The titles still to sort, in order — the first `most` only when asked (a press reads the top few: never the
        whole list, so a press costs the same at 15,000 titles as at 10)."""
        out = []
        for row in self.all:
            if row[1].key not in self.hidden:
                out.append(row)
                if most is not None and len(out) >= most:
                    break
        return out

    def left(self):
        """How many are still to sort (every pending key is one of the view's: `set_groups` lets the others go)."""
        return len(self.all) - len(self.hidden)

    def top_arrival(self):
        rows = self.visible_rows(1)
        return rows[0][1] if rows else None

    def _paint(self):
        rows, n = self.visible_rows(NEXT_SHOWN + 1), self.left()
        key = tuple((kind, a.key, a.title, getattr(a, "folder", None), len(a.item_ids), getattr(a, "cover", None),
                     getattr(a, "line", None), getattr(a, "media_word", None))
                    for kind, a in rows) + (n, bool(self.history), self.heard)
        if key == self._shown:
            return                                  # nothing it shows changed (S19)
        self._shown = key
        self.rows = rows
        _set(self.count, S.SORT_COUNT.format(n=n) if n else "")
        self.top.setVisible(bool(rows))
        self.empty.setVisible(not rows and self.heard)
        self.btn_rest.setEnabled(n > 1)
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
        more = n - 1 - NEXT_SHOWN
        _set(self.more, S.SORT_MORE.format(n=more) if more > 0 else "")
        self.more.setVisible(more > 0)

    # --- acting -------------------------------------------------------------------------------------------------- #
    # Each choice is one entry of `history` (Undo's order): {"keys", "name", "text", "ticket", "undone"} — `ticket` the
    # window's own (`drag.Ticket`) once its command is given, so Undo takes back that change and never another.
    def _moves(self):
        """The window's drag controller, or None — when its store can't be written, said here (the bar is under the
        screen) as the window says it."""
        moves = getattr(self.win, "moves", None)
        if moves is None:
            return None
        why = moves.refused()
        if why is not None:
            _set(self.said, why)
            return None
        return moves

    def _take(self, keys, name, text):
        """The titles of `keys` off the screen at once (pending until the view lets them go) -> their history entry."""
        entry = {"keys": tuple(keys), "name": name, "text": text, "ticket": None, "undone": False}
        for k in entry["keys"]:
            self.hidden[k] = name
        self.history.append(entry)
        self._shown = None
        self._paint()
        _set(self.said, text)
        return entry

    def choose(self, name, arrival=None):
        """A choice on the top title (or `arrival`): taken off at once (pending), handed to New arrivals' own call;
        refused — it comes back and the screen says so (the writer's note)."""
        if name not in PLACE_OF and name != "ignore":
            return None
        a = arrival or self.top_arrival()
        if a is None:
            return None
        moves = self._moves()
        if moves is None:
            return None
        entry = self._take((a.key,), name, S.SORT_PLACED[name].format(title=a.title))
        if name == "ignore":
            self._ignore(a, moves, entry)
            return True
        from app.qt import arrivals
        seq = arrivals.give_place(moves, entry["text"], list(a.item_ids), PLACE_OF[name], toast=False,
                                  ticket=self._ticket(entry, a.item_ids))
        if seq is None:
            self._refused(entry)
        return seq

    def _ticket(self, entry, ids):
        """The entry's own ticket — kept for its Undo, and told when its command ends unsaved (it landed as nothing,
        or was let go): the titles come back as a refusal does, never hidden for good."""
        from app.qt import drag
        ticket = entry["ticket"] = drag.Ticket(entry["text"], entry["keys"], ids)

        def told(event):
            if event == "ended" and ticket.change is None and not entry["undone"] and not sip.isdeleted(self):
                self._refused(entry)
        ticket.told = told
        return ticket

    def _ignore(self, a, moves, entry):
        """← Ignore: the title's own folder never read again (`give_skip`, Q7's) — only a folder holding no other title
        (`looks.skippable(..., own=True)`); else the title taken out of the library (`writer.remove`: its copy to the
        trash, the original where it is, kept out of every later look). One Undo either way; an Undo pressed while the
        folder is still being looked for gives nothing at all."""
        from app.qt import bridge, item_menu
        ids = list(a.item_ids)

        def act(folders):
            if entry["undone"]:
                return
            ticket = self._ticket(entry, ids)
            if folders:
                seq = item_menu.give_skip(moves, folders[0], ids, toast=False, ticket=ticket)
            else:
                seq = moves._give(ticket, lambda t: moves.writer.remove(ids, label=t), toast=False)
            if seq is None and not sip.isdeleted(self):
                self._refused(entry)
        looks = getattr(self.win, "looks", None)
        if looks is None or not hasattr(looks, "skippable"):
            act([])                                         # (no folder is being read: nothing to skip)
            return
        relay = bridge.Relay(self.win if isinstance(self.win, QObject) else self)     # (outlives a screen closed meanwhile)

        def found(folders):
            relay.deleteLater()
            act(list(folders or ()))
        relay.said.connect(found)
        if not looks.skippable(ids, relay.call, own=True):
            relay.deleteLater()                             # the looks can't answer now (closing): nothing guessed
            self._refused(entry)

    def _refused(self, entry):
        """A choice the writer refused: its titles back where they were, and the screen says it wasn't saved."""
        from app.qt import strings
        for k in entry["keys"]:
            self.hidden.pop(k, None)
        if entry in self.history:
            self.history.remove(entry)
        _set(self.said, strings.MOVE_NOT_SAVED)
        self._shown = None
        self._paint()

    def rest(self, name):
        """*Put the rest in…* `name`: every title still shown, in one command (one Undo)."""
        if name not in PLACE_OF:
            return None
        rows = self.visible_rows()
        if not rows:
            return None
        moves = self._moves()
        if moves is None:
            return None
        ids = [i for _k, a in rows for i in a.item_ids]
        label = next(lab for n, lab, *_r in S.SORT_CHOICES if n == name)
        entry = self._take([a.key for _k, a in rows], name, S.SORT_REST_PLACED.format(n=len(rows), place=label))
        from app.qt import arrivals
        seq = arrivals.give_place(moves, entry["text"], ids, PLACE_OF[name], toast=False,
                                  ticket=self._ticket(entry, ids))
        if seq is None:
            self._refused(entry)
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
        """Undo (Ctrl+Z): the last choice comes back to the top at once, and its own change is undone as the writer
        reaches it (`MovesController.undo`, its toast's Undo) — never another change of the window's."""
        moves = getattr(self.win, "moves", None)
        if not self.history or moves is None:
            return
        entry = self.history.pop()
        entry["undone"] = True
        for k in entry["keys"]:
            self.hidden.pop(k, None)
        if entry["ticket"] is not None:
            moves.undo(entry["ticket"])
        _set(self.said, "")
        self._shown = None
        self._paint()

    def _mine(self, event):
        """What a key press is to this screen: "undo", a choice's name, "close", or None (not its key)."""
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            return "undo"
        if key in KEYS and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return KEYS[key]
        if key == Qt.Key.Key_Escape and self.door != "setup":
            return "close"
        return None

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride and self._mine(event) is not None:
            event.accept()                                  # its keys are its own: the window's Ctrl+Z (`undo_last`,
            return True                                     # its newest change) never takes the sort's Undo
        return super().event(event)

    def keyPressEvent(self, event):
        what = self._mine(event)
        if what is None:
            super().keyPressEvent(event)
            return
        event.accept()
        if event.isAutoRepeat():                            # one action per press: a held key's repeats are none
            return
        if what == "undo":
            self.undo()
        elif what == "close":
            self.finish("closed")
        else:
            self.choose(what)

    def finish(self, how="done"):
        win = self.win
        if win is not None and win.__dict__.get("_sort_screen") is self:
            del win.__dict__["_sort_screen"]
        self.closed.emit(how)


def open_over(win):
    """New arrivals' *Sort them all…*: the sort screen over the window's central area (as the setup wizard covers it),
    following its size; closed by *Done* or Esc. -> the screen."""
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
