"""The drag in the window (W3.1a §2; the window's spec 04 §4.5, A2 #9–#21, 06 E4–E6, E21; the redesign's reference
`list-r14m.html`, extracted in the planning folder's `tracks/window/work/w31a/ref-extract.md` §8 *drag*): one controller
for Current's list — W3.2's tray and Goal sheet feed the same one through `begin_by_id`.

- **A press, then `drag-start-px`** (the list hands it over: `rows.RowsView.mouseMoveEvent`, B1) lifts the row: its
  cached picture becomes the **ghost** (a frameless window of its own over the list, so it moves without repainting a
  row; its long shadow, a 1 px accent ring, turned 0.8° and grown to 1.015, baked once); its **slot** stays open as a
  placeholder and travels to where it would land; the rows between **part** on springs (`drag-part`); near the list's
  edges (and just above the dock) the list **scrolls by itself**; the dock's **wells** rise (Soon · Goal · Finished;
  `frame.GoalDock`) and the toasts hide. While it runs the window's writer and the library reader are **held** (E6: an
  outside change waits for the drop, never moves a row under the hand; the dragged item removed meanwhile lets the drag
  go, *That item was removed*). **Esc, a pointer lost** (the button let go outside the window) **or the window losing
  the focus** cancel it: everything back. A click right after it is swallowed.
- **The drop** shows the new order at once — the window's own copy of the order (`reordered`; 04 §4.5's optimistic
  move: the rows swap in place, `RowsModel`'s "moved" path, W3.1a S3) — and hands the command to the writer
  (`app/services/moves.py`, its own thread: nothing here writes the store): in the list → `move` beside its painted
  neighbour (`placement`); the Soon well → `move(…, "soon")` (after the Soon line); the Goal well → Goal's end
  (`end=True`, read by the writer when it saves); the Finished well or the Finished tab → `set_tier(…, "graduated")`,
  the toast *X finished · its cards stay put* with *Keep* / *Leave its new cards out of your order* (live: the store's
  `finish`). A split's first part and hato's mix leave the Finished well unlit (its tip says why) and ⋯ leaves Finished
  out. **The numbers at the drop** come from the writer's `Numbers.after_move`, before its first write, through the
  reader.
- **Undo**: every move toast's *Undo*, and Ctrl+Z (the newest change, as the writer reaches it); *Can't undo — that
  item changed since* (E21) comes as a toast. Round 8 row 45: the bar says *Undoing…* from the press (Ctrl+Z, a
  toast's Undo) until the undo lands — an Undo asked before its change is saved waits so, never silently.
- **A write's toast** (round 8 row 45; every `_give`'s, wherever it shows — Current, Goal, search, Needs you, + Add):
  it never says done before the store does. From the press until its write lands it reads *"… · saving…"*
  (`ToastHost.set_saving`); saved, its own words; refused (the writer's note: read-only met, a failure), the reason
  in its place; landed as nothing, it goes. A toast shown in the turn a write was given without one stands for it
  (Needs you's *Link these*).
- **An expectation** keeps the drop's order on screen while the store catches up: a view from the reader with the
  same rows in another order is shown in the drop's order (with its fresh numbers), one still holding a row the drop
  sent to a well is shown without it; anything else waits. The expectation ends once the writer has been idle for
  `settle-ms`, or at once when the store says it placed something elsewhere — then the reader's view stands.
- **Moves without a drag**: ↑ ↓ (`nudge`; across the NOW / Soon edge, a `move` beside the neighbour), Alt+↑ / ↓, ⋯
  (*Up next*, *Soon*, *Goal*, *Finished*, *See it in your journey*). **A Done** (a stone, ✓ Done): `set_watched`, its
  toast with Undo, and after the Done that leaves no file unwatched the finish toast (*All N watched — finished with
  it?* [Move to Finished]), skipped for a split's first part and hato's mix. W-1, while the library's *Keep studying
  watched episodes* is off: the first plain mark of a library says its words left the list ([Keep studying them] opens
  that setting, [OK]; once per library, `hints_seen`), and an un-mark says they are back. **Files from Explorer**
  dropped on the list: the writer's `insert_at` beside the row under the hand.
- **E4**: a store that can't be written refuses at the press — the bar says why, and nothing moves.
"""
import itertools
import math
import os
import time
import weakref

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QRegion, QShortcut
from PyQt6.QtWidgets import QApplication, QMenu, QStyleOptionViewItem, QWidget

from app import theme
from app.qt import bridge, motion, rows, shadow, strings, style
from app.qt import press as qpress
from app.services import jobs as jobs_module
from app.services import view_rows

D = theme.DRAG
FINISHED = "graduated"                              # the store's name for Finished
HINT_LEFT = "keep_watched"                          # W-1: the first mark's toast (`hints_seen`, once per library)


# --- the order the window shows, and where a drop lands (pure) ---------------------------------------------------- #
def ids_of(row):
    """The store items a row stands for (a piece: its files, in order)."""
    return [e.id for e in row.episodes]


def tail_tier(row):
    """The tier of a row's last file: Soon for a show the Soon line runs through (`Row.soon_from`, P-LF-16: one row
    above the line, its last files Soon), else the row's. What lands after the row lands there — after the show."""
    return "soon" if getattr(row, "soon_from", None) is not None else row.tier


def placement(rows_, src, slot, near_n=None):
    """Where a row dropped in the list lands (04 §4.5): `rows_` Current's rows as painted; `src` the dragged row's place
    (None: a drag from outside the list, or files); `slot` its place in the new order. After the row before it (its
    last file), in that file's tier (`tail_tier`) — at the very top, before the first row, in its tier. `near`: the
    painted neighbours, nearest first, for an anchor gone or out of the tier when the write lands (the writer's
    fallback).
    -> (tier, before_id, after_id, near)."""
    near_n = D["near"] if near_n is None else near_n
    others = [r for i, r in enumerate(rows_) if i != src]
    prev = others[slot - 1] if 0 < slot <= len(others) else None
    nxt = others[slot] if 0 <= slot < len(others) else None
    if prev is not None:
        tier, before_id, after_id = tail_tier(prev), None, prev.episodes[-1].id
    elif nxt is not None:
        tier, before_id, after_id = nxt.tier, nxt.episodes[0].id, None
    else:
        tier, before_id, after_id = "now", None, None
    near = []
    for k in range(near_n):
        a, b = slot - 1 - k, slot + k
        if 0 <= a < len(others) and tail_tier(others[a]) == tier and others[a].episodes[-1].id != after_id:
            near.append((others[a].episodes[-1].id, "after"))
        if 0 <= b < len(others) and others[b].tier == tier and others[b].episodes[0].id != before_id:
            near.append((others[b].episodes[0].id, "before"))
    return tier, before_id, after_id, near


def order_after(keys, moved, slot):
    """The key order with `moved` taken out and put back at `slot` (its place in the new order)."""
    out = [k for k in keys if k != moved]
    out.insert(max(0, min(slot, len(out))), moved)
    return out


def soon_slot(rows_, src):
    """Where a row sent to Soon lands — the Soon well, ⋯ *Soon* and Goal's sheet, one rule: the top of Soon, after the
    Soon line. -> (slot, files, after_id): its place in the order without it; the NOW files above it (what the Soon
    line counts); and the file it is placed after — the last one of a show the Soon line runs through (`tail_tier`'s
    rule, as a drop after that row: the show ends in Soon, so what is sent lands after it, never at Soon's very top
    between the show's NOW and Soon files, B2-1), else None (the top of Soon)."""
    others = [r for i, r in enumerate(rows_) if i != src]
    slot = next((i for i, r in enumerate(others) if r.tier == "soon"), len(others))
    files = sum(r.n_files for r in others[:slot])
    prev = others[slot - 1] if slot else None
    if prev is not None and tail_tier(prev) == "soon":
        return slot, files - (prev.n_files - prev.soon_from), prev.episodes[-1].id    # its Soon files aren't NOW's
    return slot, files, None


def split_first(rows_, row):
    """A split's first part (A2: the Finished well stays unlit, ⋯ leaves Finished out): another Current row of the same
    title whose files come after this one's. (Goal's parts aren't in the view: a later part waiting in Goal isn't seen.)
    A group (LM11b G1: the learner's own row of several shows, its work_id its first show's) is never a part."""
    if row.work_id is None or getattr(row, "group", False):
        return False
    mine = _last_number(row)
    for r in rows_:
        if r.key != row.key and r.work_id == row.work_id and not getattr(r, "group", False):
            theirs = _first_number(r)
            if mine is None or theirs is None or theirs > mine:
                return True
    return False


def _first_number(row):
    return next((e.number for e in row.episodes if e.number is not None), None)


def _last_number(row):
    return next((e.number for e in reversed(row.episodes) if e.number is not None), None)


def is_mix(row):
    """hato's mix (it never finishes: it keeps bringing new videos)."""
    return row.source == "hato"


def finishes(row):
    """Whether Finished is offered for a row (the well lit, ⋯'s entry, the finish toast)."""
    return not is_mix(row)


def show_finished(row, ep):
    """LM11b G5 (GW-2 ⭐ A): marking `ep` leaves no episode of its show in a group unwatched while another show of the
    group still waits -> (the show's name, its episodes' ids in the group), else None. Never hato's mix; a run's last
    Done is the row's own finish (a group of one show is a run: the store's rule); episodes with no show to name (a
    first screen's cache from before) are offered nothing."""
    if not row.group or not finishes(row) or ep.work_id is None or not ep.show:
        return None
    mine = [e for e in row.episodes if e.work_id == ep.work_id]
    if any(not e.watched and e.id != ep.id for e in mine) or \
            not any(not e.watched for e in row.episodes if e.work_id != ep.work_id):
        return None
    return ep.show, [e.id for e in mine]


def lines_for(view, rows_):
    """The top-20 line and the Soon line for `rows_` (the drop's order) as the reader would draw them: the top line
    after the row holding the same number of available files as before (split through it when it falls inside one),
    the Soon line where the reader draws it (`view_rows.soon_line_after`: one rule). W-1: a file counts toward the top
    line by the store's one rule too (`library_store.counts`: a watched one only while the view's `keep_watched` is on).
    """
    from app.library_store import counts
    keep = bool(getattr(view, "keep_watched", False))
    out = []
    top = next((ln for ln in view.lines if ln.kind == "top"), None)
    if top is not None:
        n = 0
        for i, r in enumerate(view.rows[:top.after + 1]):
            eps = r.episodes if (i < top.after or top.split is None) else r.episodes[:top.split]
            n += sum(1 for e in eps if not e.missing and counts(r.tier, e.watched, keep))
        seen, at = 0, None
        for i, r in enumerate(rows_):
            for k, e in enumerate(r.episodes):
                if not e.missing and counts(r.tier, e.watched, keep):
                    seen += 1
                    if seen == n:
                        at = (i, k + 1)
                        break
            if at is not None:
                break
        if at is not None:
            i, k = at
            row = rows_[i]
            if k < len(row.episodes):
                out.append(view_rows.Line("top", i, view_rows.STRINGS["top_tip_split"].format(
                    n=n, title=row.title, k=k, m=len(row.episodes)), k))
            else:
                out.append(view_rows.Line("top", i, view_rows.STRINGS["top_tip"].format(n=n), None))
    soon_at = view_rows.soon_line_after(rows_)
    if soon_at is not None:
        old = next((ln for ln in view.lines if ln.kind == "soon"), None)
        tip = old.tip if old is not None else view_rows.STRINGS["soon_tip_nocount"]
        out.append(view_rows.Line("soon", soon_at, tip, None))
    return tuple(out)


def mines_itself(lines, place):
    """Whether Current's row at `place` stands above the top-20 line (it mines itself)."""
    top = next((ln for ln in lines if ln.kind == "top"), None)
    return top is not None and place <= top.after


def reordered(view, keys, tiers=None):
    """`view` with Current's rows in `keys`' order (each row's place number and, where `tiers` says, its tier), its lines
    redrawn for that order, its counts and subline. Rows keep their objects where nothing they show changed (the
    window repaints from their pictures)."""
    by = {r.key: r for r in view.rows}
    tiers = tiers or {}
    out = []
    for i, k in enumerate(keys):
        r = by[k]
        changes = {}
        if r.index != i + 1:
            changes["index"] = i + 1
        tier = tiers.get(k, r.tier)
        if tier != r.tier:
            changes["tier"] = tier
        if k in tiers and getattr(r, "soon_from", None) is not None:
            changes["soon_from"] = changes["soon_piece"] = None    # moved whole into one tier: no line through it
        out.append(r._replace(**changes) if changes else r)
    if out and view.rows and out[0].key != view.rows[0].key:
        out[0] = view_rows._as_hero(out[0])        # the new Up Next reads as one
    files = sum(r.n_files for r in out)
    counts = view.counts._replace(current_rows=len(out), current_files=files)
    lang = view_rows.LANGUAGE_NAMES.get(view.language, "")
    subline = view_rows.STRINGS["subline"].format(lang=lang, rows=len(out), files=files) if out else view.subline
    worst = view.worst
    if [r.key for r in out[1:]] != [r.key for r in view.rows[1:]] and \
            {r.key for r in out[1:]} != {r.key for r in view.rows[1:]}:
        worst = view_rows.worst_needs(out[1:])      # another row under Up Next: the one title width asked again
    return view._replace(rows=tuple(out), lines=lines_for(view, out), counts=counts, subline=subline, worst=worst)


def without(view, key, where):
    """`view` with Current's row `key` gone to a well (`where`: "goal" or "finished"): Goal's bar or Finished's count
    takes it at once (the reader's next view says the same)."""
    row = next((r for r in view.rows if r.key == key), None)
    if row is None:
        return view
    rest = tuple(r for r in view.rows if r.key != key)
    v = view._replace(rows=rest)
    if where == "goal" and view.goal is not None:
        g = view.goal
        cover = row.cover_title
        titles = g.titles + (1 if getattr(row, "group", False) or cover not in g.covers else 0)   # LM11b G1
        covers = g.covers if cover in g.covers or len(g.covers) >= 9 else g.covers + (cover,)
        files = g.files + row.n_files
        line = view_rows.STRINGS["goal_one"].format(files=view_rows.thousands(files)) if titles == 1 else \
            view_rows.STRINGS["goal_line"].format(titles=titles, files=view_rows.thousands(files))
        v = v._replace(goal=g._replace(titles=titles, files=files, covers=covers, line=line),
                       counts=v.counts._replace(goal_titles=titles, goal_files=files))
    elif where == FINISHED:
        badges = dict(v.badges or {})
        badges["finished"] = v.counts.finished + 1
        v = v._replace(counts=v.counts._replace(finished=v.counts.finished + 1), badges=badges)
    return reordered(v, [r.key for r in rest])


# --- the ghost --------------------------------------------------------------------------------------------------- #
def ghost_picture(pix, w, h, dpr):
    """The ghost baked once (ref-extract §8): the row's picture `pix` (w × h logical), grown by `ghost-scale` and turned
    `ghost-turn`°, its `drag-ghost` shadow under it and a 1 px accent ring around it. -> (picture, the unturned box's
    top-left in it)."""
    s, turn = D["ghost-scale"], D["ghost-turn"]
    a = math.radians(turn)
    bw, bh = w * s, h * s
    rw, rh = bw * math.cos(a) + bh * math.sin(a), bw * math.sin(a) + bh * math.cos(a)
    ml, mt, mr, mb = shadow.margins("drag-ghost")
    width, height = math.ceil(rw + ml + mr + 4), math.ceil(rh + mt + mb + 4)
    out = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    centre = QPointF(ml + 2 + rw / 2, mt + 2 + rh / 2)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.translate(centre)
    p.rotate(turn)
    p.scale(s, s)
    box = QRectF(-w / 2, -h / 2, w, h)
    shadow.paint(p, box, "drag-ghost")
    radius = D["ghost-radius"]
    path = QPainterPath()
    path.addRoundedRect(box, radius, radius)
    p.save()
    p.setClipPath(path)
    p.fillRect(box, rows.c("raised"))
    if pix is not None:
        p.drawPixmap(box.topLeft(), pix)
    p.restore()
    ring = D["ghost-ring"] / s
    p.setPen(QPen(rows.c("accent"), ring))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(box.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2), radius, radius)
    p.end()
    return out, QPointF(centre.x() - w / 2, centre.y() - h / 2)


def title_card(title, w, h, dpr):
    """A drag by item id has no row on screen (W3.2's tray, the Goal sheet): its ghost is a card with its title."""
    pix = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pix.setDevicePixelRatio(dpr)
    pix.fill(rows.c("raised"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    rows.TEXT.draw(p, 16, h / 2, title, "row-title", w - 32, rows.c("ink"), dpr=dpr)
    p.end()
    return pix


class Ghost(QWidget):
    """The lifted row: a frameless window of its own that never takes the mouse or the focus (the tooltip bubble's
    kind), so moving it repaints nothing under it."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setObjectName("dragghost")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pix, self.anchor, self.alpha = None, QPointF(), D["ghost-alpha"]

    def set_picture(self, pix, anchor):
        self.pix, self.anchor = pix, anchor
        self.resize(round(pix.width() / pix.devicePixelRatio()), round(pix.height() / pix.devicePixelRatio()))
        self.update()

    def place(self, box_top_left):
        """The row's box (unturned) with its top-left at `box_top_left` (global)."""
        self.move(QPoint(round(box_top_left.x() - self.anchor.x()), round(box_top_left.y() - self.anchor.y())))

    def box_at(self):
        return QPointF(self.pos()) + self.anchor

    def set_alpha(self, alpha):
        if alpha != self.alpha:
            self.alpha = alpha
            self.update()

    def paintEvent(self, _event):
        if self.pix is None:
            return
        p = QPainter(self)
        p.setOpacity(self.alpha)
        p.drawPixmap(0, 0, self.pix)
        p.end()


class _Resting(QObject):
    """The pointer moving over the list with no button down starts `timer` again, so it fires once the pointer rests
    there (C5); leaving the list stops it."""

    def __init__(self, viewport, timer):
        super().__init__(timer)
        self.timer = timer
        viewport.installEventFilter(self)

    def eventFilter(self, _obj, event):
        t = event.type()
        if t == QEvent.Type.MouseMove and not event.buttons():
            self.timer.start()
        elif t == QEvent.Type.Leave:
            self.timer.stop()
        return False


# --- the parting rows ------------------------------------------------------------------------------------------ #
class Parting:
    """What the list paints while a drag runs (`rows.RowsView.parting`): each row's offset as the slot travels (the
    rows between the dragged row's place and its slot moved by the slot's height, on `drag-part` springs while on
    screen), the dragged row's own place left empty (`src`), and the slot painted where it would land.
    Only what moved repaints (R3-S5, Gap 2): each frame, the band a moving row was and is painted in, and the slot's
    old and new places — never the whole list; a frame's bands asked for once, at its end, the rows' rects worked out
    once a frame (C6)."""

    def __init__(self, lst, src, height):
        self.lst = lst
        self.src = src                               # the dragged row's place, or None (from outside the list)
        self.h = height                              # the slot's height (the dragged row's, without its lines)
        self.slot = src if src is not None else None
        self.springs = {}                            # place -> its offset's spring (only while it moves)
        self.slot_y = None                           # the slot's top, in the list's content (a spring)
        self._slot_spring = None
        self._shown = {}                             # place -> the offset its row was last asked to paint at
        self._slot_shown = None                      # the slot's box as last asked to paint (the list's content y)
        self._rects = None                           # C6: place -> its rect, for the clock frame running now
        self._bands = []                             # C6: the bands this frame asked to repaint
        self.alive = True

    def target(self, r):
        """The offset place `r` rests at for the current slot."""
        s, t = self.src, self.slot
        if t is None or r == s:
            return 0.0
        if s is None:
            return float(self.h) if r >= t else 0.0
        if t < s:
            return float(self.h) if t <= r < s else 0.0
        if t > s:
            return -float(self.h) if s < r <= t else 0.0
        return 0.0

    def offset(self, r):
        spring = self.springs.get(r)
        return spring.value if spring is not None else self.target(r)

    def slot_top(self):
        """Where the slot opens (the list's content y) for the current slot."""
        lst, model = self.lst, self.lst.model()
        n = model.rowCount()
        bar = lst.verticalScrollBar().value()
        t, s = self.slot, self.src
        if n == 0:
            return 0.0
        if s is not None and t > s:
            r = lst.visualRect(model.index(min(t, n - 1), 0))
            return float(r.bottom() + 1 - self.h + bar)
        if t >= n:
            r = lst.visualRect(model.index(n - 1, 0))
            return float(r.bottom() + 1 + bar)
        return float(lst.visualRect(model.index(t, 0)).top() + bar)

    def move_to(self, slot):
        """The slot moves to `slot`: the rows whose resting offset changes move on springs (those on screen; the rest
        take their place at once), and the slot glides to its new place."""
        if slot == self.slot and (self.slot_y is not None or slot is None):
            return
        old, self.slot = self.slot, slot
        lst = self.lst
        lo, hi = self._screen()
        if old is None or slot is None:              # from outside: every row past the slot moves
            changed = range(lo, hi + 1)
        else:
            changed = range(min(old, slot) - 1, max(old, slot) + 2)
        for r in changed:
            if r == self.src:
                continue
            if not lo <= r <= hi:                    # off screen: at its place at once (seen if it reaches in)
                if r not in self.springs:
                    self._row_moved(r, self.target(r), self._shown.get(r, self._was(r, old)))
                continue
            to = self.target(r)
            spring = self.springs.get(r)
            start = spring.value if spring is not None else self._was(r, old)
            if spring is not None:
                spring.retarget(to, **motion.preset("drag-part"))
            elif start != to:
                self._shown[r] = start
                spring = motion.clock().spring(lambda v, r=r: self._row_moved(r, v), start, to, owner=lst.viewport(),
                                               on_rest=lambda r=r: self._rested(r),
                                               on_end=lambda r=r: self.springs.pop(r, None),
                                               **motion.preset("drag-part"))
                if spring.alive:                     # (at rest at once — reduced motion, frozen — is never kept)
                    self.springs[r] = spring
        if slot is None:                             # no slot: the rows close up, nothing is painted for it
            if self._slot_spring is not None:
                self._slot_spring.stop()
            self._slot_spring, self.slot_y = None, None
            self._slot_moved(None)
            return
        top = self.slot_top()
        if self._slot_spring is None or self.slot_y is None:
            if self.src is not None and self._slot_shown is None:     # the lift: the dragged row leaves its place
                place = lst.visualRect(lst.model().index(self.src, 0))
                self._repaint_band(place.top() - 1, place.bottom() + 1)
            self.slot_y = top
            self._slot_spring = motion.clock().spring(self._slot_moved, top, top, owner=lst.viewport(),
                                                      **motion.preset("drag-part"))
        else:
            self._slot_spring.retarget(top, **motion.preset("drag-part"))

    def _was(self, r, old_slot):
        keep, self.slot = self.slot, old_slot
        try:
            return self.target(r)
        finally:
            self.slot = keep

    def _slot_moved(self, v):
        """The slot at `v` (None: gone): its old box and its new one repaint."""
        self.slot_y = v
        bar = self.lst.verticalScrollBar().value()
        was, box = self._slot_shown, self._slot_box()
        self._slot_shown = box.translated(0, bar) if box is not None else None
        if not self.alive or was == self._slot_shown:
            return
        for b in (was, self._slot_shown):
            if b is not None:
                self._repaint_band(b.top() - bar - 1, b.bottom() - bar + 1)

    def _row_moved(self, r, v, was=None):
        """Place `r`'s row now paints at offset `v` (a spring's frame, or a jump from `was`): the band it was and is
        painted in repaints, its own place too (the list paints a row only where its place is asked)."""
        was = self._shown.get(r, v) if was is None else was
        self._shown[r] = v
        if not self.alive or was == v:
            return
        rect = self._rect(r)
        if rect.isValid():
            self._repaint_band(rect.top() + math.floor(min(0.0, was, v)) - 1,
                               rect.bottom() + math.ceil(max(0.0, was, v)) + 1)

    def repaint_rows(self, places):
        """(The list's hover look in motion, during a drag: Gap 2 item 4.) Each place's row repaints where it is painted
        now — the band from its place to its place moved by its offset — never the whole list."""
        for r in places:
            rect = self._rect(r)
            if rect.isValid():
                off = self.offset(r) if r != self.src else 0.0
                self._repaint_band(rect.top() + math.floor(min(0.0, off)) - 1,
                                   rect.bottom() + math.ceil(max(0.0, off)) + 1)

    def _collect(self):
        """Inside a clock frame (C6): True, and the frame's collection begun — the rows' rects kept for the frame, its
        bands asked for at its end, in one update."""
        if self._rects is not None:
            return True
        if not motion.clock().in_frame:
            return False
        self._rects = {}
        motion.clock().after_frame(self._frame_done)
        return True

    def _rect(self, r):
        """Place `r`'s rect in the viewport — worked out once a clock frame (C6)."""
        if not self._collect():
            return self.lst.visualRect(self.lst.model().index(r, 0))
        got = self._rects.get(r)
        if got is None:
            got = self._rects[r] = self.lst.visualRect(self.lst.model().index(r, 0))
        return got

    def _repaint_band(self, top, bottom):
        """The viewport's rows `top` … `bottom` repaint — inside a clock frame, with the frame's other bands at its end
        (C6: one update of their union)."""
        if self._collect():
            self._bands.append((top, bottom))
        else:
            self._update_bands([(top, bottom)])

    def _frame_done(self):
        bands, self._bands = self._bands, []
        try:
            self._update_bands(bands)
        finally:
            self._rects = None

    def _update_bands(self, bands):
        """Each band repaints — widened to a parted row whose place lies outside it but whose picture reaches into it
        (so the list paints that row too) — in one update of their union."""
        lst = self.lst
        vp = lst.viewport()
        bands = [(top, bottom) for top, bottom in bands if not (bottom < 0 or top > vp.height())]
        if not bands:
            return
        lo, hi = self._screen()
        parted = []
        for q in range(lo, hi + 1):
            off = self.offset(q) if q != self.src else 0.0
            if off:
                parted.append((self._rect(q), off))
        region = QRegion()
        for top, bottom in bands:
            grew = True
            while grew:
                grew = False
                for rq, off in parted:
                    if (rq.bottom() < top or rq.top() > bottom) and \
                            rq.bottom() + math.ceil(off) + 1 >= top and rq.top() + math.floor(off) - 1 <= bottom:
                        top, bottom, grew = min(top, rq.top()), max(bottom, rq.bottom()), True
            region = region.united(QRect(0, top, vp.width(), bottom - top + 1))
        vp.update(region)

    def scrolled(self, dy):
        """The list scrolled by `dy` (the scroll bar's value; Qt has moved what was painted): the strip that scrolled in
        repaints, widened to the parted rows whose pictures reach into it from places outside it (Qt paints only the
        rows whose places lie in the strip: a row pushed down into the bottom strip, or pulled up into the top one, was
        left unpainted — the M4.1 adversary's S1). Never the whole list."""
        if self._rects is not None:                  # (inside a clock frame: the frame's rects are from before it)
            self._rects = {}
        h = self.lst.viewport().height()
        if dy > 0:
            self._update_bands([(h - dy - 1, h)])
        elif dy < 0:
            self._update_bands([(-1, -dy)])

    def _rested(self, r):
        self.springs.pop(r, None)

    def _screen(self):
        lst = self.lst
        n = lst.model().rowCount()
        first = lst.indexAt(QPoint(4, 1))
        last = lst.indexAt(QPoint(4, lst.viewport().height() - 2))
        lo = first.row() if first.isValid() else 0
        hi = last.row() if last.isValid() else n - 1
        return max(0, lo - 2), min(n - 1, hi + 2)

    def stop(self):
        self.alive = False
        for spring in list(self.springs.values()):
            spring.stop()
        self.springs = {}
        if self._slot_spring is not None:
            self._slot_spring.stop()

    def paint_over(self, lst, event):
        """(The list's paint.) The rows just past the screen's edges that the parting moved into view, then the slot."""
        model = lst.model()
        n = model.rowCount()
        if not n:
            return
        p = QPainter(lst.viewport())
        p.setClipRect(event.rect())
        first = lst.indexAt(QPoint(4, 1))
        last = lst.indexAt(QPoint(4, lst.viewport().height() - 2))
        lo = first.row() if first.isValid() else 0
        hi = last.row() if last.isValid() else n - 1
        reach = 1 + int(self.h // max(1, rows.RowDelegate._line_h())) + 1
        option = QStyleOptionViewItem()
        lst.initViewItemOption(option)
        for r in list(range(max(0, lo - reach), lo)) + list(range(hi + 1, min(n, hi + 1 + reach))):
            if r == self.src or not self.offset(r):
                continue
            idx = model.index(r, 0)
            option.rect = lst.visualRect(idx)
            option.state = option.state & ~rows.QStyle.StateFlag.State_MouseOver
            lst.delegate.paint(p, option, idx)
        slot = self._slot_box()
        if slot is not None:
            lst.delegate.paint_slot(p, slot)
        p.end()

    def _slot_box(self):
        """The slot's box in the viewport now, or None (no slot)."""
        if self.slot_y is None:
            return None
        lst, model = self.lst, self.lst.model()
        src = self.src
        if src is not None and 0 <= src < model.rowCount():
            kind, _payload, lines = model.entries[src]
            rect = self._rect(src)
        else:
            kind, lines = rows.ROW, ()
            rect = QRect(0, 0, lst.viewport().width(), self.h)
        y = round(self.slot_y - lst.verticalScrollBar().value())
        return lst.delegate.slot_rect(kind, QRect(rect.left(), y, rect.width(), self.h + lst.delegate._lines_h(lines)),
                                      lines)


# --- ⋯: one menu per list (C4) ------------------------------------------------------------------------------------ #
class _KeptMenu(QMenu):
    """A menu kept between opens: closed (a click outside it, `close()`) it only hides — Qt's close destroys a
    window's native window, and a new one is most of an open's cost."""

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def list_menu(lst, title):
    """List `lst`'s one ⋯ menu, empty, named for `title`: made once and kept hidden between opens (a new menu was a new
    native window at every open, its first show the slowest part of opening it). What an open put in it goes as it
    hides (its actions deleted later: a pick still lands, after the hide), so a closed menu holds nothing."""
    m = getattr(lst, "row_menu", None)
    if m is None:
        m = _KeptMenu(lst)
        m.setObjectName("rowmenu")
        m.setToolTipsVisible(True)
        m.aboutToHide.connect(lambda: _empty_menu(m))   # never exec() it, only popup(): exec's own loop could run
        #                                                 the emptied actions' deleteLater before its pick is read
        lst.row_menu = m
    elif m.isVisible():
        m.hide()
    _empty_menu(m)
    m.setAccessibleName(strings.MENU_NAME.format(title=title))
    return m


def _empty_menu(m):
    for act in m.actions():
        m.removeAction(act)
        if act.parent() is m:
            act.deleteLater()
    for sub in m.findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
        sub.deleteLater()


# --- the writer's callbacks, on the window's thread -------------------------------------------------------------- #
WRITER_CALLBACKS = ("on_saved", "on_undone", "on_saving", "on_reread", "on_note")     # what a controller wires


def _no_callback(*_args):
    pass


class _Relay(QObject):
    saved = pyqtSignal(object, object)
    undone = pyqtSignal(object, object)
    saving = pyqtSignal(bool)
    reread = pyqtSignal()
    note = pyqtSignal(str)
    gone = pyqtSignal(object)
    versions = pyqtSignal(object)                    # finish-pending: the store's versions (the reader's thread)
    line = pyqtSignal(object)                        # ... and the re-order host's lines (its worker)


class Ticket:
    """A command the window gave (its toast's words and its Undo): `change` once the writer saved it. `told(event)`,
    if set: "saved", "refused" (nothing written), "undone" (its Undo asked, or the change undone) or "ended" (settled
    unsaved: it landed as nothing, or was let go) — round 8 row 45: a pressed *Mine now* stops turning when its ask is
    refused, undone or ends unsaved, and asks Connect's feed again once saved; Q7's *Skip a folder…* turns until saved.
    `anki` (finish-pending): its command's Anki half waits for the host's re-order — what its press marks (`_give`)."""
    __slots__ = ("text", "keys", "ids", "change", "undo_asked", "toast", "follows", "then", "told", "anki")

    def __init__(self, text, keys=(), ids=()):
        self.text, self.keys, self.ids = text, tuple(keys), tuple(ids)
        self.change = None
        self.undo_asked = False
        self.toast = False
        self.follows = None                          # the ticket this one's command follows (a Finished choice)
        self.then = None                             # a command waiting for this one's change (a Finished choice)
        self.told = None
        self.anki = None


def _tell(ticket, event):
    if ticket.told is not None:
        ticket.told(event)


def _sources_stopped(win, change):
    """T6: a *Stop reading it* (`Writer.stop_reading`, a gone folder's card) saved or undone — the folders listed again
    by the looks (`SourceLooks.listing`, its worker), so the card goes, or comes back with its Undo, and Settings'
    *Library folders* follows."""
    if getattr(change, "kind", None) != "stop_source":
        return
    looks = getattr(win, "looks", None)
    if looks is not None:
        try:
            looks.listing()
        except Exception as e:                       # (the looks closing: the next look lists them)
            print(f"Sources: the folders weren't listed after a stop: {e!r}")


def _skips_moved(win, change, undone=False):
    """K6 / Q7: a skip's change (the store's `folder` on it: ⋯'s, New arrivals', Settings' *Skip a folder…*) saved or
    undone — *Library folders*' skipped lines and the Settings row's count read again where they show, and an undone
    one's line in that window goes (`settings_sources.skips_moved`); the rows it took are the reader's, as any
    Remove's."""
    if getattr(change, "folder", None) is None:
        return
    try:
        from app.qt import settings_sources
        settings_sources.skips_moved(win, undone=change if undone else None)
    except Exception as e:                           # (the lines stay as they were until the next listing)
        print(f"Window drag: the skipped folders weren't read again: {e!r}")


_anki_keys = itertools.count(1)                     # finish-pending: one press per command (two Finishes: two)


def on_bar():
    """finish-pending: a press whose thing has left the screen marks the bar's arc (`press.bar_mark`, the default)."""
    return None


def _aside(settings, language):
    """(A worker.) Why the re-order host does nothing for `language` now (`replan_preview.stands_aside`), or None."""
    from app import replan_preview
    from app.services.settings import thaw
    return replan_preview.stands_aside(thaw(settings), language)


class _Drag:
    """One drag in progress."""
    __slots__ = ("src", "key", "row", "ids", "title", "source", "grab", "target", "parting", "at", "external",
                 "holding")

    def __init__(self):
        self.src = self.key = self.row = self.title = self.source = None
        self.ids = []
        self.grab = QPointF()
        self.target = None
        self.parting = None
        self.at = QPoint()
        self.external = False
        self.holding = False                         # the writer and the reader held (released once, at its end)


class DragController(QObject):
    """Current's drags, moves, Done and Undo, on the window's thread; the writer does the writing."""

    def __init__(self, win, writer, reader=None):
        super().__init__(win)
        self.win = win
        self.writer = writer
        self.reader = reader
        self.page = win.page_widgets["current"]
        self.lst = self.page.list
        self.lst.drag = self
        self.lst.setAcceptDrops(True)
        self.running = None                          # the drag in progress (`_Drag`)
        self.ghost = Ghost(win)                      # C5: made once, its native window too, kept hidden between drags
        self.ghost.winId()
        self.destroyed.connect(self.ghost.deleteLater)   # (a language switch remakes the controller)
        self._ghost_anim = None                      # the last drop's glide or fade (stopped by the next lift)
        # C5: the pointer resting on a row (`rows.HOVER_WARM_MS`, as the list warms its episodes) bakes its ghost ahead,
        # kept per row key and size while the row's picture is the same: a lift right after only shows it
        self._ghosts = {}                            # (row key, w, h, dpr) -> (row picture's cacheKey, picture, anchor)
        self.ghost_bakes = 0                         # ghost pictures baked (tests)
        self._rest = QTimer(self)
        self._rest.setSingleShot(True)
        self._rest.setInterval(rows.HOVER_WARM_MS)
        self._rest.timeout.connect(self._warm_ghost)
        _Resting(self.lst.viewport(), self._rest)
        self.expect = None                           # the key order the window shows ahead of the store
        self.expect_tiers = {}
        self.expect_gone = {}                        # key -> where it went (a well), until the reader says so
        self.expect_off = {}                         # LM11b G5: key -> ids taken off its row (the reader builds it so)
        self._reader_off = None                      # ... the ticket whose landing lets the reader's build go (H-C3)
        self._closed = False                         # H-T1: let go by the window (its close, a language switch)
        self.held = None                             # the reader's newest view, not shown yet
        self.tickets = []                            # commands given, not settled yet (oldest first)
        self.saving_keys = frozenset()
        self.toasted = None                          # the ticket whose toast shows
        self.toast_for = ()                          # round 8 row 45: the tickets the shown toast stands for …
        self._fresh = []                             # … the ones given this turn (a toast shown in it stands for them)
        self._showing = None                         # … or the one `_toast` names
        self._reason = None                          # … and the writer's last word since it showed (why one was refused)
        self._undoing = None                         # round 8 row 45: the bar's *Undoing…* (a live press), and the
        self._undos = 0                              # undos handed to the writer it waits for
        self._own = False
        self._swallow_until = 0.0
        self._filtering = False
        self.drops = 0                               # drops handed to the writer (tests)
        self.relay = _Relay(self)
        self._gate = bridge.Gate(self.relay)         # the writer's and the reader's threads reach the relay through it
        #   only: a write landing as the window is deleted (a close the quit's wait put off) is dropped, never an emit
        #   on a deleted relay (round 8's crash)
        q = Qt.ConnectionType.QueuedConnection
        self.relay.saved.connect(self._saved, q)
        self.relay.undone.connect(self._undone, q)
        self.relay.saving.connect(self._saving, q)
        self.relay.reread.connect(self._reread, q)
        self.relay.note.connect(self._note, q)
        self.relay.gone.connect(self._gone, q)
        for name in WRITER_CALLBACKS:                # on_saved -> the relay's `saved`, …
            setattr(writer, name, self._gate.caller(name[len("on_"):]))
        self._gone_told = None                       # the very callback the reader holds (`unwire` lets it go)
        subscribe = getattr(reader, "subscribe_gone", None)
        if subscribe is not None:
            self._gone_told = self._gate.caller("gone")
            subscribe(self._gone_told)
        # finish-pending: a command whose Anki half waits for its Generate keeps its press live until the host's
        # re-order for it lands (`_give(…, anki=)`): the store's versions from the reader, the host's lines, the
        # Generate's end
        self._landing = {}                           # ticket -> its press, until the writer saved it (or let it go)
        self._asking = {}                            # ... then while the host's gate is asked (a worker)
        self._owed = []                              # (press, the change's `landed` versions, ticket) until it lands
        self._versions = None                        # the store's versions as the reader last told them
        self._generates = set()                      # Generate jobs seen live while a press waits
        self._heard_line = None                      # a line that gave up while a press's gate was asked (FP-A6)
        self._on_bar = set()                         # the presses marking the bar's arc (its hover says the wait)
        self._anki_of = weakref.WeakKeyDictionary()  # a saved change -> its mark: Ctrl+Z's undo waits the same way
        self.relay.versions.connect(self._versions_in, q)
        self.relay.line.connect(self._line_in, q)
        self._versions_told = None
        subscribe = getattr(reader, "subscribe_versions", None)
        if subscribe is not None:
            self._versions_told = self._gate.caller("versions")
            subscribe(self._versions_told)
        self._heard = self._gate.caller("line")
        heard = getattr(getattr(win, "services", None), "replan_heard", None)
        if heard is not None:
            heard.append(self._heard)
        jobs = getattr(getattr(win, "bridge", None), "jobs_changed", None)
        if jobs is not None:
            jobs.connect(self._jobs_in)
        self.page.on_done = self.done
        self.page.on_nudge = self.nudge
        self.page.on_menu = self.menu
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(D["settle-ms"])
        self._settle.timeout.connect(self._settled)
        # Auto-scroll is the hand's, not motion (M4.1, the lead's call IK-4): it runs under Reduced motion too, on a
        # timer of its own (never the clock, whose Reduced would stop it) — the one view timer named as allowed.
        self._scroll = QTimer(self)
        self._scroll.setInterval(theme.MOTION["auto-scroll-tick"])
        self._scroll.timeout.connect(self._auto_scroll)
        # A scroll during a drag asks for the strip that scrolled in, no more (Gap 2): Qt moves what was painted and
        # paints that strip — but only the rows whose places lie in it (and, `Parting.paint_over`, a parted row from off
        # screen); `Parting.scrolled` widens it to the parted rows whose pictures reach in from outside it (S1).
        bar = self.lst.verticalScrollBar()
        self._bar_was = bar.value()
        bar.valueChanged.connect(self._scrolled)
        self.undo_key = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), win)
        self.undo_key.setContext(Qt.ShortcutContext.WindowShortcut)
        self.undo_key.activated.connect(self.undo_last)
        toasts = getattr(win, "toasts", None)
        if toasts is not None:
            toasts.on_show = self._toast_shown
        self._replay_owed = False
        self.joins = None                            # --- W3.2 Q8: drop-to-join (`item_menu.ItemActions`: target/show/drop)
        self.blocked = None                          # W3.2 P0: why nothing can be moved now (a language switch), or None
        self._started = False

    # --- the writer's start ----------------------------------------------------------------------------------- #
    def start(self, on_worker=False):
        """The writer started, then the journal of a crash or a quit that ran out of time replayed (again once the
        store can be written, if it can't be now). `on_worker` (W3.2 P0, the real window's): both on a worker — the
        writer's first look at the store opens it, never on the window's thread (S6). Once: a second replay would
        load the journal's moves twice."""
        if self._started:
            return
        self._started = True
        if not on_worker:
            self.writer.start()
            self._replay_owed = not self.writer.replay()
            return
        from app.qt import bridge
        writer = self.writer
        bridge.run_in_worker(lambda: (writer.start(), writer.replay())[1], then=self._writer_started,
                             failed=lambda info: print(f"Window writer: its start failed: {info[1]}"))

    def _writer_started(self, replayed):
        self._replay_owed = not replayed

    def switching(self, text):
        """W3.2 P0 (AD0-5): `text` — every move refused with it said (a drag running let go), until `switching(None)`."""
        self.blocked = text
        if text and self.running is not None:
            self.cancel(text)

    # --- the reader's views (the shell's `show_library` asks first) ------------------------------------------------ #
    def view_in(self, view):
        """-> the view to show now, or None (held): every view while a drag runs (E6); while the window's own order is
        ahead of the store, a view of the same rows in that order (its numbers fresh), else held until it settles."""
        if self._own:
            return view
        if self._replay_owed and getattr(view, "mode", None) == "store":
            self._replay_owed = not self.writer.replay()
        if self.running is not None:
            self.held = view
            return None
        if self.expect is None:
            self.held = None
            return view
        out = self._conform(view)
        if out is None:
            self.held = view
            return None
        self.held = None
        return out

    def _conform(self, view):
        if any(r.key in self.expect_off and not self.expect_off[r.key].isdisjoint(e.id for e in r.episodes)
               for r in view.rows):
            return None                              # LM11b G5: still holding a show taken off — the reader's comes next
        keys = [r.key for r in view.rows]
        if tuple(keys) == self.expect:
            return view
        rest = [k for k in keys if k not in self.expect_gone]
        if sorted(rest) != sorted(self.expect):
            return None
        v = view
        for k in keys:
            if k in self.expect_gone:
                v = without(v, k, self.expect_gone[k])
        if tuple(r.key for r in v.rows) == self.expect and all(
                r.tier == self.expect_tiers.get(r.key, r.tier) for r in v.rows):
            return v
        return reordered(v, list(self.expect), self.expect_tiers)

    def _show(self, view):
        """Show a view of the window's own making (the drop's order), past the filter."""
        self._own = True
        try:
            self.win.show_library(view)
        finally:
            self._own = False

    def _ahead(self, view, gone=None, off=None):
        """The window shows `view` (its own order) ahead of the store until the writer settles. `off` (LM11b G5): (key,
        ids) — a row that stays with those episodes taken off."""
        self.expect = tuple(r.key for r in view.rows)
        self.expect_tiers = {r.key: r.tier for r in view.rows}
        if gone is not None:
            self.expect_gone[gone[0]] = gone[1]
        if off is not None:
            self.expect_off[off[0]] = self.expect_off.get(off[0], frozenset()) | frozenset(off[1])  # two in a row: both
        self._show(view)
        self._settle.start()

    def _settled(self):
        if self._closed:                             # H-T1: the window let this controller go: nothing more of it shown
            return
        if self.writer.pending() and not self._writer_stopped():
            # unbounded by design (G3): a busy store's moves are queued, never dropped, so the window keeps its own
            # order until they land — however long another program holds the store. A writer stopped (a language
            # switch, the quit) lands nothing more here: what is left stays in its journal, and the order is let go
            self._settle.start()
            return
        self._let_go(idle=True)
        self._undo_answered(idle=True)               # (an undo that found nothing to undo answers nothing)
        republish = getattr(self.reader, "republish", None)
        if republish is not None:                    # every write landed: the store's own view once more, changed or
            republish()                              # not — where it placed a row otherwise than drawn (AD2-4)

    def _writer_stopped(self):
        stopped = getattr(self.writer, "stopped", None)
        return bool(stopped()) if stopped is not None else False

    def _let_go(self, idle=False):
        """The expectation ends: the reader's newest view stands (held, or the next one). The reader's own build of a
        show taken off its row (`_reader_off`, LM11b G5) goes only once that command landed or failed (H-C3: never
        while it still waits behind another that landed as nothing) — or the writer is idle or stopped."""
        off = self._reader_off
        if off is not None and (idle or off not in self.tickets or self._writer_stopped()):
            self._reader_off = None
            self._reader_expects(None)
        self.expect, self.expect_tiers, self.expect_gone, self.expect_off = None, {}, {}, {}
        held, self.held = self.held, None
        if held is not None and self.running is None:
            self._show(held)
        elif held is not None:
            self.held = held
        if self.reader is not None:
            self.reader.refresh()

    def base(self):
        """The view the next move starts from: the reader's newest (held) when it has the same rows, else the page's."""
        shown = self.page.view_model
        held = self.held
        if held is not None and shown is not None and {r.key for r in held.rows} >= {r.key for r in shown.rows} and \
                self.expect is None:
            return held
        return shown

    # --- E4: can it be written? --------------------------------------------------------------------------------- #
    def refused(self):
        """None when the store takes moves; else the bar's words (said now)."""
        if self.blocked:
            self.say(self.blocked)
            return self.blocked
        if self.writer.can_write():
            return None
        reason = self.writer.reason() or ""
        plain = strings.store_reason(reason)
        text = strings.DRAG_REFUSED.format(reason=plain)
        self.say(text)
        return text

    def say(self, text):
        say = getattr(self.win, "say", None)
        if say is not None:
            say(text)
        else:
            self.page.message.emit(text)

    # --- a drag from the list ----------------------------------------------------------------------------------- #
    def begin(self, press, global_pos):
        """(The list.) A press on row `press[0]` has travelled `drag-start-px`: lift it — or, with a store that can't
        be written, say why and lift nothing (E4)."""
        if self.running is not None or self.refused() is not None:
            return False
        model = self.lst.model()
        src = press[0]
        kind, row, lines = model.entries[src]
        rect = self.lst.visualRect(model.index(src, 0))
        slot = self.lst.delegate.slot_rect(kind, rect, lines)
        d = _Drag()
        d.src, d.key, d.row, d.ids, d.title = src, row.key, row, ids_of(row), row.title
        d.source = "current"
        d.grab = QPointF(press[3] - slot.topLeft())
        height = rect.height() - self.lst.delegate._lines_h(lines)
        pix = self._row_picture(kind, row, lines, rect, slot)
        unlit = None
        if is_mix(row):
            unlit = strings.WELL_UNLIT_MIX
        elif split_first(self.page.view_model.rows if self.page.view_model is not None else (), row):
            unlit = strings.WELL_UNLIT_SPLIT
        return self._lift_safely(d, pix, slot.size(), height, global_pos, unlit)

    def begin_by_id(self, item_ids, source, title, global_pos, size=None):
        """A drag of items the list doesn't show (W3.2's tray, the Goal sheet: `source` its tier, "goal" leaves the
        Goal well out): a card with its title as the ghost, the same drop."""
        if self.running is not None or self.refused() is not None:
            return False
        d = _Drag()
        d.ids, d.title, d.source, d.external = list(item_ids), title, source, True
        w = size.width() if size is not None else self.lst.viewport().width()
        h = size.height() if size is not None else rows.RowDelegate._line_h()
        dpr = self.lst.viewport().devicePixelRatioF() or 1.0
        d.grab = QPointF(min(w / 2, 40), h / 2)
        return self._lift_safely(d, title_card(title, w, h, dpr), QRect(0, 0, w, h).size(),
                                 h + theme.ROW_LINE["gap"], global_pos, None)

    def _row_picture(self, kind, row, lines, rect, slot):
        """The row's cached picture (its hover look, as the hand lifts it), else the list's own pixels there."""
        delegate = self.lst.delegate
        dpr = self.lst.viewport().devicePixelRatioF() or 1.0
        pix = None
        if self.lst.model().open_key != row.key:
            try:
                if kind == rows.ROW:
                    pix = delegate._closed_row(row, slot, dpr, True)
                else:
                    pix = delegate._closed(kind, row, lines, rect, dpr, True)[0]
            except Exception:
                pix = None
        if pix is None:
            pix = self.lst.viewport().grab(slot)
        return pix

    def _ghost_for(self, key, pix, size, dpr):
        """Row `key`'s ghost from its picture `pix` (`size`, `dpr`): the one baked as the pointer rested on it while
        that is the same picture at the same size, else baked now (and kept). -> (picture, anchor)."""
        k = (key, size.width(), size.height(), round(dpr, 3))
        hit = self._ghosts.get(k) if key is not None else None
        if hit is not None and hit[0] == pix.cacheKey():
            return hit[1], hit[2]
        picture, anchor = ghost_picture(pix, size.width(), size.height(), dpr)
        self.ghost_bakes += 1
        if key is not None:
            self._ghosts.pop(k, None)
            self._ghosts[k] = (pix.cacheKey(), picture, anchor)
            while len(self._ghosts) > D["ghosts-kept"]:
                del self._ghosts[next(iter(self._ghosts))]
        return picture, anchor

    def _warm_ghost(self):
        """(The pointer rests on the list.) The closed row under it gets its ghost baked now, for a lift (C5)."""
        lst = self.lst
        r, model = lst._hover, lst.model()
        if self.running is not None or r is None or not lst.isVisible() or not 0 <= r < model.rowCount():
            return
        kind, row, lines = model.entries[r]
        if kind not in (rows.HERO, rows.ROW) or model.open_key == row.key:
            return                                   # (an opened row's picture is the screen's, taken at the lift)
        rect = lst.visualRect(model.index(r, 0))
        slot = lst.delegate.slot_rect(kind, rect, lines)
        dpr = lst.viewport().devicePixelRatioF() or 1.0
        try:
            self._ghost_for(row.key, self._row_picture(kind, row, lines, rect, slot), slot.size(), dpr)
        except Exception as e:                       # (ahead of time only: the lift bakes its own)
            print(f"Window drag: a ghost baked ahead failed: {e!r}")

    def _lift_safely(self, *args):
        """`_lift`, and on any error on the way the drag let go at once (the writer's and the reader's holds ended): a
        half-made drag never leaves the window holding every view and refusing every move (round 2, R3-S2)."""
        try:
            self._lift(*args)
            return True
        except Exception as e:                       # (raised out of a Qt event handler it would end the program)
            print(f"Window drag: the lift failed: {e!r}")
            d = self.running
            if d is not None:
                try:
                    self._end(d)
                except Exception as e2:
                    print(f"Window drag: letting go after a failed lift failed too: {e2!r}")
            if self.ghost is not None:
                self.ghost.hide()
            return False

    def _lift(self, d, pix, size, height, global_pos, unlit):
        lst = self.lst
        dpr = lst.viewport().devicePixelRatioF() or 1.0
        self.running = d
        d.at = global_pos
        lst._hover = None
        lst._retouch()                               # the hover look goes: nothing under the hand lifts now
        lst.clear_picks()                            # --- LM11b G4: a drag lets the picks go
        anim, self._ghost_anim = self._ghost_anim, None
        if anim is not None and anim.alive:          # a lift within the last drop's glide / fade: that one ends now
            anim.stop()                              # (never hides this drag's ghost when it would have finished)
        picture, anchor = self._ghost_for(d.key, pix, size, dpr)
        self.ghost.set_picture(picture, anchor)
        self.ghost.set_alpha(D["ghost-alpha"])
        self.ghost.place(QPointF(global_pos) - d.grab)
        self.ghost.show()
        d.parting = Parting(lst, d.src, height)
        lst.parting = d.parting
        dock = self.win.dock
        if dock is not None:
            dock.begin_drag(d.source)
            if unlit:
                dock.set_unlit("finished", unlit)
        self.win.toasts.set_dragging(True)
        tips = getattr(self.win, "tooltips", None)
        if tips is not None:
            tips.hide()
        d.holding = True
        self.writer.hold()
        if self.reader is not None and hasattr(self.reader, "hold"):
            self.reader.hold()
        self._filter(True)
        self._scroll.start()
        self._follow(global_pos)

    # --- the hand ---------------------------------------------------------------------------------------------- #
    def _filter(self, on):
        app = QApplication.instance()
        if on and not self._filtering:
            app.installEventFilter(self)
            self._filtering = True
        elif not on and self._filtering:
            app.removeEventFilter(self)
            self._filtering = False

    def eventFilter(self, obj, event):
        t = event.type()
        d = self.running
        if d is None:
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
                if time.monotonic() < self._swallow_until:
                    return True                      # the click right after a drag
            if time.monotonic() >= self._swallow_until:
                self._filter(False)
            return False
        if t == QEvent.Type.MouseMove:
            if not event.buttons() & Qt.MouseButton.LeftButton:
                self.cancel()                        # the button came up where the window couldn't hear it
                return True
            self._follow(event.globalPosition().toPoint())
            return True
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.drop(event.globalPosition().toPoint())
            return True
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.ToolTip,
                 QEvent.Type.HoverMove, QEvent.Type.HoverEnter):
            return True
        if t == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
            return True
        if t == QEvent.Type.WindowDeactivate and obj is self.win:
            self.cancel()
        elif t == QEvent.Type.ApplicationStateChange and \
                QApplication.instance().applicationState() != Qt.ApplicationState.ApplicationActive:
            self.cancel()
        return False

    def _follow(self, global_pos):
        d = self.running
        if d is None:
            return
        d.at = global_pos
        self.ghost.place(QPointF(global_pos) - d.grab)
        target = self.target_at(global_pos)
        d.target = target
        over_well = target[0] in ("well", "tab")
        self.ghost.set_alpha(D["ghost-alpha-well"] if over_well else D["ghost-alpha"])
        dock = self.win.dock
        if dock is not None:
            dock.hover(target[1] if target[0] == "well" else None)
        tab = self.win.tab_buttons.get("finished")   # G3.2: the Finished tab lit as the well lights, by its rule
        if tab is not None:
            tab.set_drop_lit(target == ("tab", "finished") and not (dock is not None and dock.unlit_tip("finished")))
        # over a well or the tab the slot goes back to the row's own place (from outside: none opens)
        d.parting.move_to(target[1] if target[0] == "list" else d.src)
        if self.joins is not None:                   # --- W3.2 Q8: the part to join outlined (the rows hold still)
            self.joins.show(target[1] if target[0] == "join" else None)

    def target_at(self, global_pos):
        """What the hand is over: ("well", name) · ("tab", "finished") · ("list", slot)."""
        dock = self.win.dock
        if dock is not None:
            well = dock.well_at(global_pos)
            if well is not None:
                return "well", well
        tab = self.win.tab_buttons.get("finished")
        if tab is not None and tab.isVisible() and tab.rect().contains(tab.mapFromGlobal(global_pos)):
            return "tab", "finished"
        if self.joins is not None and self.running is not None:     # --- W3.2 Q8: over another part of the same title
            key = self.joins.target(self.running, global_pos)
            if key is not None:
                return "join", key
        return "list", self.slot_at(self.lst.viewport().mapFromGlobal(global_pos).y())

    def slot_at(self, y):
        """The place in the new order for a hand at `y` (the list's viewport): before a row when over its upper half,
        after it over its lower half, by the rows' resting places."""
        lst, d = self.lst, self.running
        model = lst.model()
        n = model.rowCount()
        if not n or model.entries[0][0] not in (rows.HERO, rows.ROW):
            return 0
        src = d.src if d is not None else None
        top = lst.visualRect(model.index(0, 0)).top()
        if y < top:
            return 0
        idx = lst.indexAt(QPoint(4, y))
        if not idx.isValid():
            return n - 1 if src is not None else n
        j = idx.row()
        if j == src:
            return src
        mid = lst.visualRect(idx).center().y()
        jj = j if src is None or j < src else j - 1   # its place without the dragged row
        return jj if y < mid else jj + 1

    def _auto_scroll(self):
        d = self.running
        if d is None:
            self._scroll.stop()
            return
        vp = self.lst.viewport()
        y = vp.mapFromGlobal(d.at).y()
        edge, step = theme.MOTION["auto-scroll-edge"], theme.MOTION["auto-scroll-px-per-frame"]
        dy = 0
        if y < edge:
            dy = -max(1, round(step * min(1.0, (edge - y) / edge)))
        else:
            bottom = vp.height()
            dock = self.win.dock
            if dock is not None and dock.isVisible():   # just above the dock: the list's end comes to the hand
                bottom = min(bottom, vp.mapFromGlobal(dock.mapToGlobal(QPoint(0, 0))).y() -
                             theme.MOTION["auto-scroll-dock"] + edge)
            if y > bottom - edge and y < vp.height() + theme.MOTION["auto-scroll-dock"]:
                dy = max(1, round(step * min(1.0, (y - (bottom - edge)) / edge)))
        if dy and d.target is not None and d.target[0] == "list":
            bar = self.lst.verticalScrollBar()
            before = bar.value()
            bar.setValue(before + dy)
            if bar.value() != before:
                self._follow(d.at)

    def _scrolled(self, value):
        was, self._bar_was = self._bar_was, value
        parting = self.lst.parting
        if parting is not None and parting.alive and value != was:
            parting.scrolled(value - was)

    # --- the end of a drag ------------------------------------------------------------------------------------- #
    def cancel(self, why=None):
        """Esc, a pointer lost, the window let go, the item removed: everything back where it was, nothing written."""
        d = self.running
        if d is None:
            return
        self._end(d)
        if self.ghost is not None:
            self.ghost.hide()
        if why:
            self.say(why)
        self._show_held()

    def _end(self, d, repaint=True):
        """The drag's machinery down (wells, toasts, the hold on the writer and the reader) and the rows closed up —
        repainted whole on a cancel; a drop's own paint is its moved rows (W3.1a §3: the rows the parting moved are
        exactly the rows the drop moved)."""
        self.running = None
        self._scroll.stop()
        self._swallow_until = time.monotonic() + theme.MOTION["click-swallow-after-drag"] / 1000.0
        QTimer.singleShot(theme.MOTION["click-swallow-after-drag"] + 1, self._unfilter)
        if d.parting is not None:
            d.parting.stop()
        self.lst.parting = None
        if repaint:
            self.lst.viewport().update()
        dock = self.win.dock
        if dock is not None:
            dock.end_drag()
        tab = self.win.tab_buttons.get("finished")   # G3.2
        if tab is not None:
            tab.set_drop_lit(False)
        if self.joins is not None:                   # --- W3.2 Q8
            self.joins.show(None)
        self.win.toasts.set_dragging(False)
        if d.holding:                                # (a lift that failed before its holds holds nothing)
            d.holding = False
            if self.reader is not None and hasattr(self.reader, "release"):
                self.reader.release()
            self.writer.release()

    def _unfilter(self):
        if self.running is None and time.monotonic() >= self._swallow_until:
            self._filter(False)

    def _show_held(self):
        held, self.held = self.held, None
        if held is not None:
            if self.expect is None:
                self._show(held)
            else:
                out = self._conform(held)
                if out is not None:
                    self._show(out)
                else:
                    self.held = held

    def drop(self, global_pos):
        d = self.running
        if d is None:
            return
        target = self.target_at(global_pos)
        kind, name = target
        if kind == "well":
            unlit = self.win.dock.unlit_tip(name) if self.win.dock is not None else None
            if unlit:
                self.cancel(unlit)                   # the well never lit: it goes back, and the tip says why
                return
            self._to_well(d, name)
        elif kind == "tab":                          # the Finished tab takes a drop too (A2 #21), with the well's rule
            if not d.external and is_mix(d.row):
                self.cancel(strings.WELL_UNLIT_MIX)
                return
            if not d.external and split_first(self.page.view_model.rows, d.row):
                self.cancel(strings.WELL_UNLIT_SPLIT)
                return
            self._to_well(d, "finished")
        elif kind == "join":                         # --- W3.2 Q8: dropped on another part of the same title
            self._end(d)
            self._glide_away()
            self.joins.drop(d, name)
        else:
            vp = self.lst.viewport()
            if not vp.rect().contains(vp.mapFromGlobal(global_pos)):
                self.cancel()                        # let go outside the list (off the window): given up, nothing written
                return
            slot = name
            if d.src is not None and slot == d.src:
                self.cancel()                        # back where it was: nothing to write
                return
            self._to_place(d, slot)

    def _to_place(self, d, slot):
        view = self.page.view_model
        rows_ = view.rows
        tier, before_id, after_id, near = placement(rows_, d.src, slot)
        if d.external:
            self._end(d)
            self._glide_away()
            text = strings.DRAG_UP_NEXT.format(title=d.title) if slot == 0 else \
                strings.DRAG_PLACED.format(title=d.title, n=slot + 1)
            self._give(Ticket(text, ids=d.ids), lambda t: self.writer.move(d.ids, tier, before_id=before_id,
                                                                           after_id=after_id, near=near, label=t))
            return
        base = self.base()
        keys = [r.key for r in base.rows]
        moved = order_after([r.key for r in rows_], d.key, slot)
        new_keys = self._fit(keys, moved, d.key)
        new = reordered(base, new_keys, {d.key: tier})
        place = new_keys.index(d.key)
        text = strings.DRAG_UP_NEXT.format(title=d.title) if place == 0 else \
            (strings.DRAG_PLACED_MINES if mines_itself(new.lines, place) else strings.DRAG_PLACED).format(
                title=d.title, n=place + 1)
        ticket = Ticket(text, keys=(d.key,), ids=d.ids)
        self._end(d, repaint=False)
        self.held = None
        self.lst.landing = d.key
        self._ahead(new)
        self._give(ticket, lambda t: self.writer.move(d.ids, tier, before_id=before_id, after_id=after_id, near=near,
                                                      label=t))
        self._glide_home(d.key)

    @staticmethod
    def _fit(keys, moved, key):
        """The drop's order laid onto `keys` (the reader's newest, which may hold a row the screen didn't): the moved
        row after the row it follows on screen, else before the one it precedes."""
        if sorted(keys) == sorted(moved):
            return moved
        at = moved.index(key)
        out = [k for k in keys if k != key]
        prev = moved[at - 1] if at > 0 else None
        nxt = moved[at + 1] if at + 1 < len(moved) else None
        if prev is not None and prev in out:
            out.insert(out.index(prev) + 1, key)
        elif nxt is not None and nxt in out:
            out.insert(out.index(nxt), key)
        else:
            out.insert(min(at, len(out)), key)
        return out

    def _to_well(self, d, name):
        if d.external:
            self._end(d)
            self._glide_away()
            self._well_command(d, name, None)
            return
        base = self.base()
        if name == "soon":
            slot, files, after_id = soon_slot(base.rows, next((i for i, r in enumerate(base.rows) if r.key == d.key),
                                                              None))
            new_keys = order_after([r.key for r in base.rows], d.key, slot)
            new = reordered(base, new_keys, {d.key: "soon"})
            place = new_keys.index(d.key)
            text = strings.DRAG_SOON.format(title=d.title, n=place + 1, files=files) if files else \
                strings.DRAG_SOON_NO_COUNT.format(title=d.title, n=place + 1)
            ticket = Ticket(text, keys=(d.key,), ids=d.ids)
            self._end(d)
            self.held = None
            self._ahead(new)
            self._give(ticket, lambda t: self.writer.move(d.ids, "soon", after_id=after_id, label=t))
            self._glide_away()
            return
        where = "goal" if name == "goal" else FINISHED
        new = without(base, d.key, where)
        self._end(d)
        self.held = None
        self._ahead(new, gone=(d.key, where))
        self._well_command(d, name, d.key)
        self._glide_away()

    def _well_command(self, d, name, key):
        keys = (key,) if key is not None else ()
        if name == "soon":
            base = self.base()
            after_id = soon_slot(base.rows, None)[2] if base is not None else None    # after a show the line cuts
            ticket = Ticket(strings.DRAG_SOON_NO_COUNT.format(title=d.title, n=1), keys, d.ids)
            self._give(ticket, lambda t: self.writer.move(d.ids, "soon", after_id=after_id, label=t))
        elif name == "goal":
            ticket = Ticket(strings.DRAG_GOAL.format(title=d.title), keys, d.ids)
            self._give(ticket, lambda t: self.writer.move(d.ids, "goal", end=True, label=t))
        else:
            self._finish(d.title, d.ids, keys)

    def _finish(self, title, ids, keys=()):
        """To Finished: `set_tier(…, "graduated")`, and its toast's choice (D14) — *Keep* or *Leave its new cards out of
        your order*, each written as `set_finished` (live, never greyed). finish-pending: the drop and *Leave its new
        cards out* each a press until the host's re-order for it lands (Anki moves after the Generate it starts: the
        bar's arc — the row has left this list)."""
        ticket = Ticket(strings.DRAG_FINISHED.format(title=title), keys, ids)
        if self._give(ticket, lambda t: self.writer.set_tier(list(ids), FINISHED, label=t), toast=False,
                      anki=on_bar) is None:
            return None

        def choose(keep):
            choice = Ticket(strings.DRAG_TAKEN_OUT.format(title=title), keys, ids)
            choice.follows = ticket
            self._give(choice, lambda t: self._set_finished(list(ids), keep, t, ticket), toast=not keep,
                       anki=None if keep else on_bar)
        self._toast(ticket, buttons=[(strings.DRAG_KEEP, strings.DRAG_KEEP_TIP, lambda: choose(True)),
                                     (strings.DRAG_TAKE_OUT, strings.DRAG_TAKE_OUT_TIP, lambda: choose(False))])
        return ticket

    def _set_finished(self, ids, keep, label, follows):
        """The Finished toast's choice, linked to the drop's change (`follows=`: the drop's Undo then undoes both). Chosen
        before the drop is saved (a busy store), it waits for that change and is given as it lands — unlinked if the
        drop lands as nothing to change; dropped if its own Undo was asked meanwhile. -> the command's number (or True
        while it waits), None when refused."""
        if follows.change is None and follows in self.tickets:
            def given():
                if label.undo_asked:                 # taken back before it was ever given
                    self._settle_ticket(label)
                    return
                if self.writer.set_finished(ids, keep_cards=keep, label=label, follows=follows.change) is None:
                    self._settle_ticket(label)
                    self.refused()
            follows.then = given
            return True
        return self.writer.set_finished(ids, keep_cards=keep, label=label, follows=follows.change)

    # --- the ghost's last move ------------------------------------------------------------------------------------ #
    def _glide_home(self, key):
        """The ghost glides onto the row's new place (`ghost-glide`; Reduced motion: none), its slot showing there
        meanwhile; then the row."""
        ghost = self.ghost
        model = self.lst.model()
        at = next((i for i, e in enumerate(model.entries) if getattr(e[1], "key", None) == key), None)
        if ghost is None or at is None:
            self._landed(key)
            return
        kind, _row, lines = model.entries[at]
        slot = self.lst.delegate.slot_rect(kind, self.lst.visualRect(model.index(at, 0)), lines)
        to = QPointF(self.lst.viewport().mapToGlobal(slot.topLeft()))
        start = ghost.box_at()
        ghost.set_alpha(D["ghost-alpha"])
        self.lst.update(model.index(at, 0))
        self._ghost_anim = motion.clock().animate(
            theme.MOTION["ghost-glide"], lambda k: ghost.place(start + (to - start) * k),
            on_done=lambda: self._landed(key), kind="move", owner=ghost, on_end=lambda: self._landed(key))

    def _landed(self, key):
        if self.ghost is not None:
            self.ghost.hide()
        if self.lst.landing == key:
            self.lst.landing = None
            model = self.lst.model()
            at = next((i for i, e in enumerate(model.entries) if getattr(e[1], "key", None) == key), None)
            if at is not None:
                self.lst.update(model.index(at, 0))

    def _glide_away(self):
        """Into a well (or from outside): the ghost fades out (`ghost-removed`; Reduced motion: a fade kept, no longer
        than FAST)."""
        ghost = self.ghost
        if ghost is None:
            return
        start = ghost.alpha
        self._ghost_anim = motion.clock().animate(
            theme.MOTION["ghost-removed"], lambda k: ghost.set_alpha(start * (1 - k)),
            on_done=ghost.hide, kind="fade", owner=ghost, on_end=ghost.hide)

    # --- commands, toasts, Undo ------------------------------------------------------------------------------------ #
    def _give(self, ticket, command, toast=True, anki=None):
        """Hand a command to the writer (`command(label)` -> its number, or None when refused); its toast with Undo.
        `anki` (finish-pending): the command's Anki half waits for the Generate it starts — `anki()` makes what its
        press marks (None: the bar's arc), painted before the hand-over (`_anki_begin`)."""
        if anki is not None:
            ticket.anki = anki
            self._anki_begin(ticket)
        urgent = getattr(self.reader, "urgent", None)
        if urgent is not None:                       # a4: its views build at once, an import's burst aside
            urgent()
        seq = command(ticket)
        if seq is None:                              # refused (E4 meanwhile): nothing written, the store's view stands
            _tell(ticket, "refused")
            self._ended(ticket)
            self._anki_landed(ticket)                # (its press ends: the bar says why, below)
            if self.refused() is None:               # W3.2 P0 (AD0-5): never silent — a writer let go at a switch
                self.say(strings.MOVE_NOT_SAVED)
            held = self.held
            self._let_go()
            view = getattr(self.reader, "view", None)
            view = view() if held is None and view is not None else None
            if view is not None and view is not self.page.view_model:
                self._show(view)                     # ... and the order painted ahead of it put back as the store has it
            return None
        self.drops += 1
        self.tickets.append(ticket)
        if not self._fresh:                          # this turn's writes: a toast shown in it stands for them
            QTimer.singleShot(0, self._fresh.clear)
        self._fresh.append(ticket)
        self._settle.start()
        if toast:
            self._toast(ticket)
        return seq

    def _toast(self, ticket, buttons=()):
        ticket.toast = True
        self.toasted = ticket
        self._showing = (ticket,)                    # what this toast stands for (`_toast_shown`, as it shows)
        self.win.toasts.show(ticket.text, undo=lambda: self.undo(ticket), buttons=buttons)

    # --- round 8 row 45: a write's toast reads *· saving…* while it waits (one rule, wherever the toast shows) --- #
    def _toast_shown(self):
        """(The toast host, as any toast shows.) It stands for the writes given this turn — none for a toast of its own
        (a note, the Anki offer); `_toast` names its ticket itself."""
        self.toast_for = self._showing if self._showing is not None else tuple(self._fresh)
        self._showing = None
        self._fresh.clear()
        self._reason = None
        if any(t.change is None for t in self.toast_for):
            self.win.toasts.keep_room()              # it says *· saving…* until it lands: nothing moves as that goes
        self._paint_toast()

    def _paint_toast(self):
        toasts = getattr(self.win, "toasts", None)
        if toasts is None:
            return
        waiting = not self._closed and any(t.change is None and any(t is w for w in self.tickets)
                                           for t in self.toast_for)
        try:
            toasts.set_saving(waiting)
        except RuntimeError:                         # (the window going: its toast with it)
            pass

    def _ended(self, ticket):
        """`ticket` settled (saved, refused, landed as nothing): the toast's words — done once saved; if none of the
        writes it stands for was saved, the store's reason in its place, or no toast."""
        mine = self.toast_for
        toasts = getattr(self.win, "toasts", None)
        if not self._closed and toasts is not None and toasts.alive and any(ticket is t for t in mine) and all(
                t.change is None and not any(t is w for w in self.tickets) for t in mine):
            reason, self._reason = self._reason, None
            self.toast_for = ()
            if self.toasted is not None and any(self.toasted is t for t in mine):
                self.toasted = None
            if reason:
                toasts.show(reason)                  # refused: why, where it said what it would do
            else:
                toasts.close()                       # nothing to change: nothing to say, nothing to undo
            return
        self._paint_toast()

    # --- Undo ---------------------------------------------------------------------------------------------------- #
    def _undo_pressed(self):
        """Round 8 row 45: *Undoing…* in the bar from the press — painted before the writer is asked — until the undo
        lands (`_undo_answered`)."""
        if self._undoing is None:
            self._undoing = qpress.begin(None, "undo", busy=strings.UNDOING, win=self.win)

    def _undo_to_writer(self, change=None, label=None):
        """An undo handed to the writer — watched until the writer is idle, as every command `_give` hands it is
        (`_settled`): one that finds nothing to undo answers nothing at all, and *Undoing…* ends there. `label`
        (finish-pending): the undo's own ticket, so a change whose Anki half waited waits the same way back. -> the
        writer's answer (None: refused)."""
        self._undos += 1
        seq = self.writer.undo(change) if label is None else self.writer.undo(change, label=label)
        self._settle.start()
        return seq

    def _undo_answered(self, answered=True, idle=False):
        """An undo landed (`answered`), or the writer is idle (`idle`: one that undid nothing, or failed): *Undoing…*
        ends once none waits — none handed over unanswered, no Undo asked of a change not saved yet."""
        if idle:
            self._undos = 0
        elif answered:
            self._undos = max(0, self._undos - 1)
        p = self._undoing
        if p is None or self._undos or any(t.undo_asked for t in self.tickets):
            return
        self._undoing = None
        qpress.end(p, self.win)

    def undo(self, ticket):
        """A toast's Undo: that change (once the writer saved it; asked before, it is undone as it lands).
        finish-pending: a change whose Anki half waits — its press lets go, and the Undo's own waits the same way back;
        asked before the change was saved, its press stays and waits for the Undo's re-order (`_saved`)."""
        _tell(ticket, "undone")
        if ticket.change is not None:
            self._anki_drop(lambda t: t is ticket or t.follows is ticket)     # (a drop's choice with it)
            back = self._anki_back(ticket) if ticket.anki is not None else None
            self._undo_pressed()
            if self._undo_to_writer(ticket.change, label=back) is None and back is not None:
                self._anki_landed(back)
            self._let_go()
        else:
            ticket.undo_asked = True
            if any(ticket is t for t in self.tickets):   # (one that landed as nothing has nothing to wait for)
                self._undo_pressed()
            self._paint_toast()


    def undo_last(self):
        """Ctrl+Z: the newest change, as the writer reaches it — the newest command the window gave if it isn't saved yet
        (a busy store, an Explorer drop still copying, a Finished choice waiting on its drop): that one, as it lands, as
        its toast's Undo does (never the change before it; round 2, AD2-5 / AD2-6)."""
        if self.running is not None:
            return
        waiting = [t for t in self.tickets if t.change is None and not t.undo_asked]
        if waiting:
            self.undo(waiting[-1])
            return
        if self.writer.can_undo() or self.writer.pending():
            self._undo_pressed()
            self._undo_to_writer(label=Ticket(None))  # finish-pending: its undo waits for Anki if its change did (`_undone`)
            self._let_go()

    def _saved(self, change, label):
        if isinstance(label, Ticket):
            label.change = change
            _tell(label, "saved")
            then, label.then = label.then, None
            if label.anki is not None:
                self._anki_of[change] = label.anki   # finish-pending: Ctrl+Z's undo of it waits for Anki too
            if label.undo_asked:
                label.undo_asked = False
                if then is not None:                 # the drop taken back: its waiting choice with it
                    then = None
                    self._drop_waiting(label)
                p = self._landing.pop(label, None)   # finish-pending: its press waits for the Undo's re-order now
                back = self._anki_back(label, p) if p is not None else None
                if self._undo_to_writer(change, label=back) is None and back is not None:
                    self._anki_landed(back)
                self._let_go()
            if then is not None:
                then()
        self._settle_ticket(label)
        if self.reader is not None:
            self.reader.refresh()
        _skips_moved(self.win, change)
        _sources_stopped(self.win, change)

    def _undone(self, change, label):
        _skips_moved(self.win, change, undone=True)
        _sources_stopped(self.win, change)
        mark = self._anki_of.pop(change, None) if change is not None else None    # (an undo that undid nothing)
        if isinstance(label, Ticket):
            _tell(label, "undone")
            if label not in self._landing and mark is not None and label.anki is None:
                # finish-pending (intent finding 2): Ctrl+Z of a change whose Anki half waited — the change's press
                # lets go, and the undo's own waits the same way back (the toast's Undo started its own at the click)
                self._anki_drop(lambda t: t.change is change or (t.follows is not None and t.follows.change is change))
                label.anki = mark
                self._anki_begin(label)
            if label in self._landing:               # finish-pending: an Undo's own press, its change landed
                label.change = change
                self._anki_landed(label)
        if self.toasted is not None and self.toasted.change is change:
            self.win.toasts.close()                  # its toast goes with it
            self.toasted = None
        self._let_go()
        self._undo_answered()

    def _settle_ticket(self, ticket):
        if isinstance(ticket, Ticket) and ticket.change is None:
            _tell(ticket, "ended")                   # (Q7: a press waiting for "saved" never turns for ever)
        self._anki_landed(ticket)
        try:
            self.tickets.remove(ticket)
        except ValueError:
            pass
        self._settle.start()
        self._paint_saving()
        self._ended(ticket)
        self._undo_answered(answered=False)

    def _saving(self, on):
        """*saving…* on the rows whose moves wait (after 300 ms; 04 §4.5), until the store takes them."""
        self.saving_keys = frozenset(k for t in self.tickets for k in t.keys) if on else frozenset()
        self._paint_saving()
        told = getattr(self.win, "moves_saving", None)       # the phase strip: 届 waits while the store holds them
        if told is not None:
            told(bool(on))

    def _paint_saving(self):
        keys = self.saving_keys if self.tickets else frozenset()
        if keys == self.lst.saving:
            return
        changed = keys ^ self.lst.saving
        self.lst.saving = keys
        model = self.lst.model()
        for i, e in enumerate(model.entries):
            if getattr(e[1], "key", None) in changed:
                self.lst.update(model.index(i, 0))

    def _drop_waiting(self, ticket):
        """The choices waiting for `ticket`'s change, let go (never given)."""
        for t in list(self.tickets):
            if t.follows is ticket and t.change is None:
                self._settle_ticket(t)

    # --- finish-pending: a command whose Anki half waits for its Generate ---------------------------------------- #
    # Kura's W-1b (PROVISIONAL, the lead + Sonic: "Finish acts after its Generate; pending shown at once"): Finish (a
    # drop on Finished, the toast's *Leave its new cards out of your order*), Finished's *Put back* and *Leave its new
    # cards out* / *Put them back in the order*, and their Undo (the toast's, Ctrl+Z's, one asked before the change was
    # saved) write the store at once while Anki moves only once the host re-orders for that write — after the Generate
    # it starts. Sonic's doctrine, every press reacts at once: one press per command, painted before the writer has it
    # (`_anki_begin`), live until the store records that re-order (`planned_order_version` / `planned_pins_version`
    # reach the change's `landed` versions, told by the reader — never a store read here). One rule ends it otherwise
    # (`_anki_end`): the line the host leaves it with — a line that gives up (`replan_preview.GivesUp`: Anki closed, a
    # Generate to press, 順's deck to pick; said as that kind by the host, never matched by its words) ends it failed,
    # with those words; `OFF` (automation or 順 off, 順 absent: the user's own choice — at the write, from the gate
    # asked once, or later, from the host letting go) ends it quietly. A Generate that fails, or that the learner stops
    # (never one the journey keeper withdrew, nor one their own Generate joined), ends it failed with Generate's words.
    # No host, or nothing written: done as it lands. A language switch and the window's close let it go (`close`).
    # Words: none in the bar while it waits (FP-1 lean b, PROVISIONAL): a hover on the bar's arc says what it waits
    # for (`strings.ANKI_WAIT_TIP`); the host's line is in 順's hover and Generate's steps in its own, and the toast
    # keeps its own words.
    def _anki_begin(self, ticket):
        try:
            at = ticket.anki()
        except Exception as e:
            print(f"A press's mark couldn't be made: {e!r}")
            at = None
        p = qpress.begin(None, ("anki", next(_anki_keys)), win=self.win, at=at)
        if p is None:
            return
        self._landing[ticket] = p
        arc = getattr(self.win, "bar_arc", None)
        if at is None and arc is not None and not sip.isdeleted(arc):
            self._on_bar.add(p)
            arc.setToolTip(strings.ANKI_WAIT_TIP)

    def _anki_end(self, p, why=None):
        """The one end of a press waiting for Anki: `why` words (a line that gives up, Generate's) -> failed, with
        them; None or `OFF` -> done, quietly. Its key leaves the window's press table (FP-A7)."""
        if p.live():
            qpress.end(p, self.win, failed=bool(why), why=why or None)
        self._on_bar.discard(p)
        arc = getattr(self.win, "bar_arc", None)
        if not self._on_bar and arc is not None and not sip.isdeleted(arc):
            arc.setToolTip("")
        qpress.presses_of(self.win).forget(p.key)

    def _anki_end_owed(self, why):
        """Every press owed a re-order ends with `why` (`_anki_end`), said once in the bar when it has words."""
        owed, self._owed = self._owed, []
        for p, _stamp, _ticket in owed:
            self._anki_end(p, why)
        if owed and why:
            self.say(why)

    def _anki_drop(self, mine):
        """The presses of the tickets `mine(ticket)` picks let go (their change undone): done, quietly."""
        for waiting in (self._landing, self._asking):
            for t in [t for t in waiting if mine(t)]:
                self._anki_end(waiting.pop(t))
        for got in [w for w in self._owed if mine(w[2])]:
            self._owed.remove(got)
            self._anki_end(got[0])

    def _anki_back(self, ticket, p=None):
        """The ticket an Undo of `ticket`'s change is given with: its press waits the same way back — `p` taken over
        (an Undo asked before the change was saved: the mark never stops), else a new one."""
        back = Ticket(ticket.text, ticket.keys, ticket.ids)
        back.anki = ticket.anki
        if p is None:
            self._anki_begin(back)
        else:
            self._landing[back] = p
        return back

    def _anki_landed(self, ticket):
        """`ticket`'s write landed (its change, the store's versions with it), or never will: what its press waits
        for."""
        p = self._landing.pop(ticket, None)
        if p is None or not p.live():
            return
        stamp = getattr(ticket.change, "landed", None) if ticket.change is not None else None
        services = getattr(self.win, "services", None)
        if stamp is None or self._closed or getattr(services, "replan", None) is None:
            self._anki_end(p)                        # nothing written, or no host: nothing is owed to Anki
            return
        self._asking[ticket] = p
        bridge.run_in_worker(_aside, services.settings.get(), getattr(self.win, "language", None) or "ja",
                             then=lambda why: self._owing(p, stamp, ticket, why),
                             failed=lambda _info: self._owing(p, stamp, ticket, None))

    def _owing(self, p, stamp, ticket, why):
        if sip.isdeleted(self) or self._asking.get(ticket) is not p:
            return                                   # (its Undo asked meanwhile: let go)
        del self._asking[ticket]
        heard = self._heard_line
        if not self._asking:
            self._heard_line = None
        if not p.live():
            return
        if self._closed:
            self._anki_end(p)
            return
        if why is not None:
            from app import replan_preview
            why = replan_preview.ends_with(why)      # the user's own choice: OFF, quietly; the deck to pick: its words
            self._anki_end(p, why)
            if why:
                self.say(why)
            return
        self._owed.append((p, stamp, ticket))
        if heard is not None:
            self._anki_end_owed(heard)               # FP-A6: a line that gave up while the gate was asked
            return
        self._caught_up()

    def _caught_up(self):
        """The presses whose re-order the store has recorded end (done); a library made again (another epoch) too."""
        v = self._versions
        for got in list(self._owed):
            p, stamp, _ticket = got
            if not p.live():
                self._owed.remove(got)
                self._anki_end(p)
            elif v is not None and (v.get("epoch") != stamp["epoch"] or (
                    v.get("planned_order_version", 0) >= stamp["order_version"]
                    and v.get("planned_pins_version", 0) >= stamp["pins_version"])):
                self._owed.remove(got)
                self._anki_end(p)

    def _versions_in(self, versions):
        self._versions = versions
        if self._owed:
            self._caught_up()

    def _line_in(self, line):
        """The host's line: one that gives up (or `OFF`) ends the presses owed a re-order (`_anki_end`); heard while a
        press's gate is still asked, it waits for that press (FP-A6) — until a line of another kind follows it."""
        if not (self._owed or self._asking):
            return
        from app import replan_preview
        if not isinstance(line, replan_preview.GivesUp):
            if line:
                self._heard_line = None              # the host went on: its give-up is not the last word
            return
        if self._asking:
            self._heard_line = line
        if self._owed:
            self._anki_end_owed(line)

    def _jobs_in(self, views):
        """A Generate that ends without its list while a press waits for it — failed, or stopped by the learner
        (FP-3; never one the journey keeper withdrew to ask again, nor one the learner's own Generate joined): the
        press fails, with Generate's words."""
        if not self._owed:
            self._generates.clear()
            return
        running = any(v.kind == "generate" and v.state in jobs_module.LIVE for v in views)
        for v in views:
            if v.kind != "generate":
                continue
            if v.state in jobs_module.LIVE:
                self._generates.add(v.id)
            elif v.id in self._generates:
                self._generates.discard(v.id)
                if v.cancelled:
                    withdrawn = getattr(getattr(self.win.services, "controller", None), "withdrawn", None)
                    if not running and not (withdrawn is not None and withdrawn(v.id)):
                        self._anki_end_owed(strings.ANKI_WAIT_GENERATE_STOPPED)
                        return
                elif v.state == jobs_module.FAILED:
                    self._anki_end_owed(strings.ANKI_WAIT_GENERATE_FAILED.format(message=v.message or "—"))
                    return

    def _anki_let_go(self):
        """A language switch, the window's close: no press of this controller's left turning."""
        landing = list(self._landing.values()) + list(self._asking.values())
        self._landing, self._asking = {}, {}
        owed, self._owed = [w[0] for w in self._owed], []
        for p in landing + owed:
            self._anki_end(p)

    def _reread(self):
        """The store placed something elsewhere, or had nothing to change: its view stands now (a choice waiting for a
        drop that landed as nothing is given unlinked). W3.2 (S5): while others still wait, the tickets whose own
        command landed as nothing settle (Ctrl+Z never picks one that has nothing to undo)."""
        landed = getattr(self.writer, "landed_empty", None)
        empty = landed() if landed is not None else ()
        if not self.writer.pending():
            for t in list(self.tickets):
                then, t.then = t.then, None
                if then is not None and not t.undo_asked:
                    then()
            settled, self.tickets = self.tickets, []
            self._paint_saving()
            for t in settled:
                if isinstance(t, Ticket) and t.change is None:
                    _tell(t, "ended")
                self._ended(t)
            self._undo_answered(idle=True)
        else:
            for t in list(self.tickets):
                if t.change is None and any(t is e for e in empty):
                    then, t.then = t.then, None
                    if then is not None and not t.undo_asked:
                        then()
                    self._settle_ticket(t)
        for t in [t for t in self._landing if any(t is e for e in empty)]:
            self._anki_landed(t)                     # finish-pending FP-A1: only a press whose own command landed as
        self._let_go()                               # nothing (an Undo refused) — never "the queue is empty"

    def _note(self, text):
        if self.toast_for:
            self._reason = text                      # (a write it stands for may be refused with it)
        if text == strings.MOVE_WORDS["cant_undo"]:
            self._undo_answered()
            self.win.toasts.show(text)               # E21: said where the Undo was asked
        else:
            self.say(text)

    def _gone(self, ids):
        """(E6) Items removed while a drag held the view: the drag of one of them is let go."""
        d = self.running
        if d is not None and set(d.ids) & set(ids or ()):
            self.cancel(strings.DRAG_GONE)

    # --- a Done ----------------------------------------------------------------------------------------------------- #
    def done(self, row, ep):
        """A stone or ✓ Done (the one path, S12): watched (its toast and Undo) — a stone already watched turns back —
        and, when no file of the row is left unwatched, the finish toast (A2 #2; not for a split's first part or hato's
        mix). `ep` None: Up Next's ✓ Done with every file already watched — nothing to mark, the finish toast offered
        (G3.2; a split's first part or hato's mix: the bar says why it can't)."""
        if self.refused() is not None:
            return
        title = row.title
        if ep is None:
            view = self.page.view_model
            if not finishes(row):
                self.say(strings.WELL_UNLIT_MIX)
            elif split_first(view.rows if view is not None else (), row):
                self.say(strings.WELL_UNLIT_SPLIT)
            else:
                self.win.toasts.show(strings.DONE_ALL.format(n=len(row.episodes)), buttons=[
                    (strings.DONE_MOVE_FINISHED, strings.DONE_MOVE_FINISHED_TIP, lambda: self.to_finished(row))])
            return
        # W-1: does this mark move what the list counts (the store's one rule; never a video waiting for its subtitle)
        moves_list = view_rows.mark_moves_list(row.tier, ep, getattr(self.page.view_model, "keep_watched", False))
        if ep.watched:
            text = strings.DONE_UNDONE_BACK.format(ep=ep.label) if moves_list else \
                strings.DONE_UNDONE.format(title=title, ep=ep.label)
            ticket = Ticket(text, (row.key,), (ep.id,))
            self._give(ticket, lambda t: self.writer.set_watched([ep.id], False, label=t))
            return
        left = [e for e in row.episodes if not e.watched and e.id != ep.id]
        view = self.page.view_model
        rows_ = view.rows if view is not None else ()
        if not left and finishes(row) and not split_first(rows_, row):
            ticket = Ticket(strings.DONE_ALL.format(n=len(row.episodes)), (row.key,), (ep.id,))
            if self._give(ticket, lambda t: self.writer.set_watched([ep.id], True, label=t), toast=False) is None:
                return
            self._toast(ticket, buttons=[(strings.DONE_MOVE_FINISHED, strings.DONE_MOVE_FINISHED_TIP,
                                          lambda: self.to_finished(row))])
            return
        shown = show_finished(row, ep)               # LM11b G5: one show of a group all watched, the rest not yet
        if shown is not None:
            show, ids = shown
            ticket = Ticket(strings.DONE_SHOW_IN_GROUP.format(show=show, n=len(ids)), (row.key,), (ep.id,))
            if self._give(ticket, lambda t: self.writer.set_watched([ep.id], True, label=t), toast=False) is None:
                return
            self._toast(ticket, buttons=[(strings.DONE_MOVE_SHOW_FINISHED.format(show=show),
                                          strings.DONE_MOVE_SHOW_FINISHED_TIP.format(show=show, n=len(ids)),
                                          lambda: self.finish_show(row, show, ids))])
            return
        hint = self._unseen(HINT_LEFT) if moves_list else None   # --- W-1: the first mark, once per library
        if hint is not None:
            ticket = Ticket(strings.DONE_LEFT.format(ep=ep.label), (row.key,), (ep.id,))
            if self._give(ticket, lambda t: self.writer.set_watched([ep.id], True, label=t), toast=False) is None:
                return
            self._seen(hint)
            self._toast(ticket, buttons=[(strings.DONE_KEEP, strings.DONE_KEEP_TIP,
                                          lambda: self.win.open_setting("keep_watched")),
                                         (strings.DONE_OK, strings.DONE_OK_TIP, lambda: None)])
            return
        after = [e for e in row.episodes[row.episodes.index(ep) + 1:] if not e.watched] if ep in row.episodes else []
        nxt = after[0] if after else (left[0] if left else None)
        text = strings.DONE_NEXT.format(title=title, ep=ep.label, next=nxt.label) if nxt is not None else \
            strings.DONE_ONE.format(title=title, ep=ep.label)
        self._give(Ticket(text, (row.key,), (ep.id,)), lambda t: self.writer.set_watched([ep.id], True, label=t))

    # --- W-1: a hint shown once per library (settings.json's `hints_seen`: hint ids, each with the library's id) -- #
    def _hint_id(self, name):
        """`name`'s hint id for the library shown (its store id), or None before a read has found it: never keyed by
        the language, so a hint is never shown twice in one library."""
        store_id = None
        try:
            store_id = self.reader.store_id() if self.reader is not None else None
        except Exception:
            pass
        return f"{name}:{store_id}" if store_id else None

    def _hints_seen(self):
        """settings.json's `hints_seen` as a list of ids — a hand-edited value that isn't a list (a number, true, a text)
        reads as none seen, its odd entries left out; the next write puts a clean list in its place."""
        value = self.win.services.settings.get().get("hints_seen")
        return [h for h in value if isinstance(h, str)] if isinstance(value, (list, tuple)) else []

    def _unseen(self, name):
        """`name`'s hint id for this library when it hasn't been shown here yet, else None."""
        hint = self._hint_id(name)
        if hint is None:
            return None
        try:
            seen = self._hints_seen()
        except Exception:
            return None                              # no settings to keep it in: never a hint shown every time
        return None if hint in seen else hint

    def _seen(self, hint):
        """`hint` recorded as shown: its key alone written (`save_keys`' rule, the settings service's)."""
        seen = self._hints_seen()
        if hint not in seen:
            self.win.services.settings.set({"hints_seen": seen + [hint]})
    # --- end W-1

    def to_finished(self, row):
        """*Move to Finished* (the finish toast, ⋯): the row leaves Current at once; the Finished toast."""
        if self.refused() is not None:
            return
        base = self.base()
        if base is not None and any(r.key == row.key for r in base.rows):
            self._ahead(without(base, row.key, FINISHED), gone=(row.key, FINISHED))
        self._finish(row.title, ids_of(row), (row.key,))

    def finish_show(self, row, show, ids):
        """LM11b G5: *Move {show} to Finished* (the Done's toast) — the finish of that show's episodes in the group alone
        (`_finish`: D14's Keep / Leave out kept). The store puts them in Finished under their own show and the group
        keeps the rest; until it has, the reader builds every view with them there (`LibraryReader.expect`: each row by
        the view's own rule, a busy store's wait included) and a view still holding them is held."""
        if self.refused() is not None:
            return
        base = self.base()
        if base is not None and any(r.key == row.key for r in base.rows):
            self._ahead(base, off=(row.key, ids))
        ticket = self._finish(show, ids, (row.key,))
        if ticket is not None and self.expect_off:
            self._reader_off = ticket
            self._reader_expects({i: FINISHED for off in self.expect_off.values() for i in off})

    def _reader_expects(self, tiers):
        expect = getattr(self.reader, "expect", None)
        if expect is not None:
            expect(tiers)

    # --- ↑ ↓ and ⋯ ---------------------------------------------------------------------------------------------- #
    def nudge(self, row, step):
        """↑ ↓ (A2 #13, Alt+↑ / ↓): one place up or down. Within its tier the store's `nudge`; across the NOW / Soon edge
        a `move` beside the neighbour (the store's nudge stays in its tier) — and for a show the Soon line runs through,
        or past one (P-LF-16: its files are in both tiers). The window shows the swap at once."""
        base = self.base()
        if base is None or self.running is not None or self.refused() is not None:
            return
        rows_ = base.rows
        i = next((n for n, r in enumerate(rows_) if r.key == row.key), None)
        if i is None:
            return
        j = i + step
        if not 0 <= j < len(rows_):
            return
        nb = rows_[j]
        keys = [r.key for r in rows_]
        keys[i], keys[j] = keys[j], keys[i]
        land = nb.tier if step < 0 else tail_tier(nb)    # before its first file, or after its last
        new = reordered(base, keys, {row.key: land})
        place = j
        text = strings.DRAG_UP_NEXT.format(title=row.title) if place == 0 else \
            (strings.DRAG_PLACED_MINES if mines_itself(new.lines, place) else strings.DRAG_PLACED).format(
                title=row.title, n=place + 1)
        ids = ids_of(row)
        ticket = Ticket(text, (row.key,), ids)
        self._ahead(new)
        if land == row.tier and getattr(row, "soon_from", None) is None:
            self._give(ticket, lambda t: self.writer.nudge(ids, "up" if step < 0 else "down", label=t))
        elif step < 0:
            self._give(ticket, lambda t: self.writer.move(ids, land, before_id=nb.episodes[0].id, label=t))
        else:
            self._give(ticket, lambda t: self.writer.move(ids, land, after_id=nb.episodes[-1].id, label=t))

    def menu_entries(self, row):
        """⋯'s entries for a row, in order: [(name, label, tip, enabled)]. *Up next* not for Up Next itself; *Finished*
        not for a split's first part or hato's mix; the moves disabled, with the store's reason, while it can't be
        written (E4)."""
        view = self.page.view_model
        rows_ = view.rows if view is not None else ()
        writable = self.writer.can_write()
        reason = None
        if not writable:
            raw = self.writer.reason() or ""
            reason = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        out = []
        for name in ("up-next", "soon", "goal", "finished", "journey"):
            if name == "up-next" and rows_ and rows_[0].key == row.key:
                continue
            if name == "finished" and (not finishes(row) or split_first(rows_, row)):
                continue
            label, tip = strings.MENU_ITEMS[name]
            ok = writable or name == "journey"
            out.append((name, label, tip if ok else reason, ok))
        return out

    def menu(self, row, at):
        """⋯: a plain menu in the theme's style (Esc closes it), its entries' tips shown."""
        m = list_menu(self.lst, row.title)
        for name, label, tip, ok in self.menu_entries(row):
            act = QAction(label, m)
            act.setToolTip(tip)
            act.setEnabled(ok)
            act.triggered.connect(lambda _c=False, n=name: self.menu_pick(row, n))
            m.addAction(act)
        self.last_menu = m
        m.popup(at)
        return m

    def menu_pick(self, row, name):
        if name == "journey":
            from app.qt import press as qpress       # round 8 row 45: the row's ⋯ turns while it opens (IK-2)
            ep = view_rows.journey_episode(row)                            # opened ON it (Sonic 2026-10-24)
            self.win._open_journey(asked=True, at=qpress.row_mark(self.lst, [ep.id]) if ep else None, episode=ep)
            return
        if self.refused() is not None:
            return
        base = self.base()
        if base is None or not any(r.key == row.key for r in base.rows):
            return
        if name == "finished":
            self.to_finished(row)
            return
        ids = ids_of(row)
        if name == "goal":
            self._ahead(without(base, row.key, "goal"), gone=(row.key, "goal"))
            self._give(Ticket(strings.DRAG_GOAL.format(title=row.title), (row.key,), ids),
                       lambda t: self.writer.move(ids, "goal", end=True, label=t))
            return
        src = next(i for i, r in enumerate(base.rows) if r.key == row.key)
        if name == "soon":
            slot, files, after_id = soon_slot(base.rows, src)
            keys = order_after([r.key for r in base.rows], row.key, slot)
            self._ahead(reordered(base, keys, {row.key: "soon"}))
            place = keys.index(row.key)
            text = strings.DRAG_SOON.format(title=row.title, n=place + 1, files=files) if files else \
                strings.DRAG_SOON_NO_COUNT.format(title=row.title, n=place + 1)
            self._give(Ticket(text, (row.key,), ids),
                       lambda t: self.writer.move(ids, "soon", after_id=after_id, label=t))
            return
        hero = base.rows[0]                          # *Up next*: before Up Next, in its tier
        keys = order_after([r.key for r in base.rows], row.key, 0)
        self._ahead(reordered(base, keys, {row.key: hero.tier}))
        self._give(Ticket(strings.DRAG_UP_NEXT.format(title=row.title), (row.key,), ids),
                   lambda t: self.writer.move(ids, hero.tier, before_id=hero.episodes[0].id, label=t))

    # --- files from Explorer ----------------------------------------------------------------------------------- #
    @staticmethod
    def _files(event):
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        return [os.path.normpath(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]

    def files_wanted(self, event):
        return bool(self._files(event)) and self.running is None

    def files_dropped(self, event):
        """Files dropped on the list from Explorer (A2's toast *Added X at #N*): copied into the tier's folder and placed
        beside the row under the hand, by the writer (`insert_at`)."""
        paths = self._files(event)
        if not paths or self.running is not None or self.refused() is not None:
            return False
        view = self.page.view_model
        rows_ = view.rows if view is not None else ()
        save, self.running = self.running, None
        y = event.position().toPoint().y()
        slot = self._slot_outside(y)
        self.running = save
        tier, before_id, after_id, near = placement(rows_, None, slot)
        if tier not in ("now", "soon"):
            tier = "now"
        name = os.path.basename(paths[0])
        text = strings.DRAG_ADDED.format(name=name, n=slot + 1) if len(paths) == 1 else \
            strings.DRAG_ADDED_N.format(count=len(paths), n=slot + 1)
        self._give(Ticket(text), lambda t: self.writer.insert_at(paths, tier, before_id=before_id, after_id=after_id,
                                                                 near=near, label=t))
        return True

    def _slot_outside(self, y):
        """`slot_at` for something from outside the list (no row of its own)."""
        lst = self.lst
        model = lst.model()
        n = model.rowCount()
        if not n or model.entries[0][0] not in (rows.HERO, rows.ROW):
            return 0
        idx = lst.indexAt(QPoint(4, y))
        if not idx.isValid():
            return 0 if y < lst.visualRect(model.index(0, 0)).top() else n
        return idx.row() if y < lst.visualRect(idx).center().y() else idx.row() + 1

    # --- the quit ------------------------------------------------------------------------------------------------ #
    def unwire(self):
        """The writer's callbacks and the reader's `subscribe_gone` let go — a language switch and the window's close,
        before any widget of this controller's can be deleted: a write landing later (the quit's last moves, on the
        writer's thread) tells no one, and one telling right now has ended when this returns (the gate's close waits
        for it). A window deleted without this (a close the quit's wait put off) closes the gate as its relay goes."""
        for name in WRITER_CALLBACKS:
            setattr(self.writer, name, _no_callback)
        self._gate.close()
        toasts = getattr(self.win, "toasts", None)
        if toasts is not None and toasts.on_show == self._toast_shown:
            toasts.on_show = None
        unsubscribe = getattr(self.reader, "unsubscribe_gone", None)
        if unsubscribe is not None and self._gone_told is not None:
            unsubscribe(self._gone_told)
        self._gone_told = None
        unsubscribe = getattr(self.reader, "unsubscribe_versions", None)
        if unsubscribe is not None and self._versions_told is not None:
            unsubscribe(self._versions_told)
        self._versions_told = None
        heard = getattr(getattr(self.win, "services", None), "replan_heard", None)
        if heard is not None and self._heard in heard:
            heard.remove(self._heard)

    def close(self):
        """The window closes (or a language switch lets this controller go): a drag running is let go, and the settle
        stops — H-T1: nothing of this controller's is shown past it (its writer's moves left stay in its journal)."""
        if self.running is not None:
            self.cancel()
        self._closed = True
        self._settle.stop()
        self._anki_let_go()
        self._filter(False)
        for t in self.tickets:                       # round 8 row 45: nothing of this controller's left turning
            if isinstance(t, Ticket) and t.change is None:
                _tell(t, "ended")                    # (Q7A-2: a press waiting for "saved" lets go at a switch)
            self._ended(t)
        p, self._undoing, self._undos = self._undoing, None, 0
        if p is not None:
            qpress.end(p, self.win)
