"""+ Add (W3.2 Q3; the RUNBOOK §1 *+ Add*, §5 lean 2, §5a N14; the reference's row 6, the + stone): the stone at the
header's right and its menu. (Setup's page 3 keeps its own three — a file, a folder, YouTube — since alpha 8; its
files go through `add_files`, the drop's path.)

- **The stone** (`AddStone`): a faceted deep-sapphire stone with a + cut in it, flat (no blur); under the hand it
  rises 1 px and brightens. A click opens its menu.
- **The menu** (built each time it opens, so a door that came or went is right): *Files…* · *A folder…* · *EPUB or
  Anki deck…* (W3.4's `extract` door) · *YouTube or bilibili…* (the `youtube-downloader` door, while it is available)
  · *Paste text…* · the line *Or drop files anywhere in your list*. A door that isn't there leaves its entry out
  (E13); with no writer (no library open) the entries that copy files are left out too.
- **What is added** (`Adder`) goes the way an Explorer drop goes (W3.1a: `moves.Writer.insert_at` — copied as
  `.part`, then renamed, never over a file; content files only, the rest named in a note), with its toast *Added X at
  #N · analysed on the next Generate* and its Undo — and lands **with its show when its show is in Current, else at
  the top of Current** (lean 2, G1.2-12: what you add yourself never waits in New arrivals). Its show: the Current row
  whose folder (or title) is the added files' folder name; the files are then copied into that show's folder and
  placed after its last episode. A folder no show in Current holds comes in as a folder of its own at the top of
  Current, its own folders kept. A folder is walked for content files on a worker, by the disk sync's own walk
  (`library_store.walk_tree`).
- **A folder…** (SRC W1b, D6): *read it where it is* — the folder becomes a source of the library open
  (`Store.add_source`, then its first look on the looks' worker: `app/services/source_looks.py`): Surasura keeps its own
  copy of each text and looks there again for new episodes; a show it never showed waits in New arrivals (S14 / D6), an
  episode of a show it holds joins its show. A folder it can't read there says why (`NotASource.reason`). Without the
  looks (no store open), the folder is copied in as before (`add_folder`).
- **Paste text…** (`PasteCard`): a small slate card — a title and the text — whose *Add* writes one UTF-8 `.txt`
  into a temporary folder (on a worker), then adds it like a file. Esc, Back and a click outside close it.

No section picker (N14): where it lands is the redesign's rule above, never a question.

**Every press reacts at once** (round 8 row 45): a folder's look (or its walk, copied in) marks the bar from the
moment it is chosen until it answers; the Paste card's *Add* says *Adding…* in the bar until its toast; the toast of
what is copied in reads *· saving…* while it copies (the drag controller's one rule for a write's toast).
"""
import math
import os
import re
import shutil
import tempfile

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit,
                             QPushButton, QToolButton, QVBoxLayout)

from app import theme
from app.qt import bridge, confirm, motion, shadow, strings, style, windows
from app.qt import press as qpress

ORDER = ("files", "folder", "extract", "youtube", "paste")
COPIES = frozenset({"files", "folder", "paste"})         # the entries that copy files in (they need the writer)
DOORS = {"extract": "extract", "youtube": "youtube-downloader"}
CURRENT = ("now", "soon")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.IGNORECASE)     # Windows' device names
TITLE_MAX = 80                                           # a pasted text's file name: its title, this long at most
LIGHT = (0.1, -0.6, -0.8, 0.3, 1.0, 0.8, 0.3, -0.2)       # the stone's eight bevel facets, by their facing (top left lit)
WOBBLE = (1.0, 0.94, 1.03, 0.97, 1.0, 0.95, 1.02, 0.96)   # … and its outline, a little uneven (the same every paint)


# --- where it lands (pure: the light mutants' targets) ------------------------------------------------------------- #
def _fold(text):
    from app.library_store import search_fold
    return search_fold(text or "").strip()


def show_folder(row):
    """A Current row's own folder, relative to the data folder (`HighPriority/<show>`), when its files sit in one
    folder below NOW's or Soon's (or `Library`'s) — else None (loose files, hato's drop folder, another root)."""
    from app import library_store as ls
    tops = {ls.FOLDER_OF_TIER[t] for t in CURRENT} | {ls.CONTENT_FOLDER}     # SRC K3: new copies' folder too
    folders = {e.rel_path.rsplit("/", 1)[0] for e in row.episodes if e.rel_path and "/" in e.rel_path}
    if len(folders) != 1:
        return None
    folder = folders.pop()
    parts = folder.split("/")
    if len(parts) < 2 or parts[0] not in tops or ls.path_key(folder).startswith(ls.path_key(ls.HATO_FOLDER)):
        return None
    return folder


def show_in_current(view, name):
    """The Current row the files of folder `name` belong with — the show's own folder under the tier (`parts[1]`:
    never a deeper leaf such as *Season 1* or *Subs*, which another show's folder holds too), else its title, is `name`
    (the store's fold: case, width, kana) — the last such row (a show split in two: after its later part), or None."""
    key = _fold(name)
    if not key or view is None:
        return None
    for row in reversed(view.rows):
        if row.tier not in CURRENT:
            continue
        folder = show_folder(row)
        names = {_fold(folder.split("/")[1])} if folder else set()
        names |= {_fold(row.cover_title), _fold(row.title)}
        if key in names:
            return row
    return None


def placement(view, paths, folder=None, rel_dirs=None):
    """Where + Add puts `paths` (files from anywhere; `folder`: the folder they were walked from, `rel_dirs` beside
    `paths`: each file's folder under it) -> (tier, after_id, into, n): with its show in Current, after the show's last
    episode, copied into the show's folder when it has one (`into`), at #n — the show's own place, or the place after
    it for a show of loose files; else the top of NOW (#1), a folder kept as a folder of its own under NOW's
    (`into` beside `paths`, its own folders kept), loose files into NOW's folder (`into` None)."""
    from app import library_store as ls
    name = os.path.basename(os.path.normpath(folder)) if folder else \
        os.path.basename(os.path.dirname(os.path.normpath(paths[0]))) if paths else ""
    row = show_in_current(view, name)
    picked = os.path.normpath(folder) if folder else os.path.dirname(os.path.normpath(paths[0])) if paths else ""
    if row is None and picked:                       # *Show B/Season 1*: its show is the parent's name, if any's
        row = show_in_current(view, os.path.basename(os.path.dirname(picked)))
    if row is not None and row.episodes:
        into = show_folder(row)
        return row.tier, row.episodes[-1].id, into, row.index if into else row.index + 1
    if folder:
        base = f"{ls.FOLDER_OF_TIER['now']}/{_UNSAFE.sub('_', name).strip()}"
        if ls.path_key(base + "/").startswith(ls.path_key(ls.HATO_FOLDER + "/")):
            base += " (2)"                           # never hato's drop folder: its files would read as hato's
        dirs = rel_dirs or [""] * len(paths)
        return "now", None, [f"{base}/{d}" if d else base for d in dirs], 1
    return "now", None, None, 1


def walk_folder(folder):
    """(A worker.) The content files under `folder`, as the disk sync walks a tier's folder -> [(path, rel_dir)]."""
    from app import library_store as ls
    files, _bad = ls.walk_tree(folder, "")
    out = []
    for rel, _size, _mtime in files:
        rel_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        out.append((os.path.join(folder, *rel.split("/")), rel_dir))
    return out


def safe_title(title):
    """A pasted text's file name from its title: no character Windows refuses, at most `TITLE_MAX` long, never a
    device's name (*con*, *NUL*, *com1* …: `_` before it, N2)."""
    name = _UNSAFE.sub(" ", title or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)[:TITLE_MAX].strip()
    if _RESERVED.match(name):
        name = "_" + name
    return name or strings.PASTE_DEFAULT_TITLE


def write_pasted(title, text, folder=None):
    """(A worker.) `text` as one UTF-8 `.txt` named by `title`, in a new temporary folder (or `folder`) -> its path.
    (The folder is the system's temporary one: the copy in the library is what counts.)"""
    folder = folder or tempfile.mkdtemp(prefix="surasura-paste-")
    path = os.path.join(folder, safe_title(title) + ".txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def pick_files(parent):
    paths, _chosen = QFileDialog.getOpenFileNames(parent, strings.ADD_PICK_FILES, "", strings.ADD_PICK_FILTER)
    return [os.path.normpath(p) for p in paths]


def pick_folder(parent):
    folder = QFileDialog.getExistingDirectory(parent, strings.ADD_PICK_FOLDER, "")
    return os.path.normpath(folder) if folder else None


# --- the actions ------------------------------------------------------------------------------------------------ #
class Adder(QObject):
    """+ Add's actions for `shell` (the window: its `moves`, its Current page's view, its doors). `given(text)`: a
    command was handed to the writer (the wizard reads its rows again)."""
    given = pyqtSignal(str)

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.card = None                                  # the paste card open, if any

    def _moves(self):
        return getattr(self.shell, "moves", None)

    def door(self, name):
        op = next((o for o in windows.OPENERS if o.name == DOORS[name]), None)
        try:
            settings = self.shell.services.settings.get()
        except Exception:
            return None
        if op is None or not windows.available(op, settings, settings.get("target_language") or "ja"):
            return None
        return op

    def why_not(self):
        """S4 (E4): while the library can't be saved, the copying entries' greyed tip (the store's reason); else None.
        Read only: nothing said in the bar."""
        moves = self._moves()
        writer = getattr(moves, "writer", None)
        if writer is None or writer.can_write():
            return None
        raw = writer.reason() or ""
        return strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)

    def entries(self, names=ORDER):
        """The entries that act now, in order: [(name, label, tip)]."""
        out = []
        for name in names:
            if name in COPIES and self._moves() is None:
                continue
            if name in DOORS and self.door(name) is None:
                continue
            label, tip = strings.ADD_ITEMS[name]
            out.append((name, label, tip))
        return out

    def run(self, name, first=False):
        """`name`'s action. `first`: a folder read by setup's own first look (Current, SRC-1) — setup's page 3; + Add
        outside setup never (D6: a show never shown waits in New arrivals)."""
        if name == "files":
            self.add_files(pick_files(self.shell))
        elif name == "folder":
            self.read_folder(pick_folder(self.shell), first=first)
        elif name == "paste":
            self.paste()
        elif name in DOORS:
            op = self.door(name)
            if op is not None:
                windows.launch(self.shell, op)

    def _view(self):
        page = getattr(self.shell, "page_widgets", {}).get("current")
        return getattr(page, "view_model", None)

    def add_files(self, paths, name=None, folder=None, rel_dirs=None, then=None, origin=True):
        """`paths` in, where lean 2 says (see the module's doc) -> the writer's number, or None (nothing, or refused).
        `then()`: once the command landed (the pasted text's temporary folder removed, N7). `origin` (K21): each file's
        origin recorded on its item (where it came from, the video beside it); off for a pasted text."""
        moves = self._moves()
        if not paths or moves is None or moves.refused() is not None:
            return None
        from app.qt import drag
        tier, after_id, into, n = placement(self._view(), paths, folder, rel_dirs)
        if name is None and len(paths) > 1:
            text = strings.DRAG_ADDED_N.format(count=len(paths), n=n)
        else:
            text = strings.DRAG_ADDED.format(name=name or os.path.basename(paths[0]), n=n)
        writer = moves.writer
        ticket = drag.Ticket(text)
        ticket.then = then
        seq = moves._give(ticket, lambda t: writer.insert_at(list(paths), tier, after_id=after_id, label=t,
                                                                         into=into, origin=origin))
        if seq is not None:
            self.given.emit(text)
        return seq

    def add_folder(self, folder):
        """A folder: walked on a worker, then added (its name in the toast); nothing in it is said in the bar."""
        if not folder or self._moves() is None or self._moves().refused() is not None:
            return
        name = os.path.basename(os.path.normpath(folder))

        def walked(found):
            if not found:
                windows.say_in_bar(self.shell, strings.ADD_NOTHING.format(name=name))
                return
            self.add_files([p for p, _d in found], name=name, folder=folder, rel_dirs=[d for _p, d in found])
        qpress.run(None, ("add-folder", os.path.normpath(folder)), walk_folder, folder, then=walked,   # marked now
                   failed=lambda info: windows.say_in_bar(self.shell, strings.ADD_FOLDER_FAILED.format(
                       name=name, why=info[0])), win=self.shell)

    # --- SRC W1b: *Read it where it is* ------------------------------------------------------------------------- #
    def read_folder(self, folder, first=False):
        """`folder` becomes a source: `add_source` and its first look, on the looks' worker; what it found (or why it
        can't be read there) said in the bar, `given` once it landed. `first`: setup's own first scan (Current, SRC-1).
        Without the looks, copied in (`add_folder`). -> True when it was asked."""
        if not folder:
            return False
        looks = getattr(self.shell, "looks", None)
        if looks is None:
            self.add_folder(folder)
            return False
        moves = self._moves()
        if moves is not None and moves.refused() is not None:
            return False                                  # S4 (E4): said in the bar, nothing written
        name = os.path.basename(os.path.normpath(folder)) or folder
        p = qpress.begin(None, ("add-folder", os.path.normpath(folder)), win=self.shell)   # round 8 row 45: marked now,
        if p is None:                                                                    # until its look answers
            return True                                   # its look asked already, still running: asked once
        relay = bridge.Relay(self)
        relay.said.connect(lambda answer: self._read(name, answer, relay, folder, p))
        busy = looks.busy() if hasattr(looks, "busy") else False
        try:
            asked = bool(looks.add(os.path.normpath(folder), relay.call, first=first))
        except Exception:
            self._read_ended(p)
            raise
        if not asked:
            self._read_ended(p)
        elif busy:                                        # queued behind a look under way: said, never silent
            windows.say_in_bar(self.shell, strings.SOURCES_QUEUED.format(name=name))
        return asked

    def _read_ended(self, p, failed=False):
        if p is not None and p.live():
            qpress.end(p, self.shell, failed=failed)

    def _read(self, name, answer, relay, folder=None, p=None):
        relay.deleteLater()
        self._read_ended(p, failed=bool(answer.get("refused")))
        refused = answer.get("refused")
        result = answer.get("result") or {}
        if refused == "no-library" and folder:
            self.add_folder(folder)                       # a 2.x library (no store): copied in, as before (S3)
            return
        if answer.get("later"):
            text = strings.SOURCES_READ_LATER.format(name=name)
        elif refused == "busy":
            text = strings.SOURCES_BUSY.format(name=name)  # P-1: a store busy past its wait: nothing copied in
        elif refused:
            reason = strings.SOURCES_NO_LIBRARY if refused == "no-library" else strings.store_reason(refused)
            text = strings.SOURCES_REFUSED.format(name=name, reason=reason)
        elif not result.get("reachable", True):
            text = strings.SOURCES_UNREACHABLE.format(name=name)
        elif result.get("added"):
            line = strings.SOURCES_READ_ARRIVALS if answer.get("arrivals") else strings.SOURCES_READ
            text = line.format(name=name, added=result["added"])
        else:
            text = strings.SOURCES_READ_NOTHING.format(name=name)
        say = getattr(self.shell, "say", None)
        if say is not None:
            say(text)
        else:
            windows.say_in_bar(self.shell, text)
        if not refused:
            self.given.emit(text)

    def paste(self):
        if self.card is not None and _alive(self.card) and self.card.isVisible():
            return self.card
        moves = self._moves()
        if moves is None or moves.refused() is not None:
            return None                                   # S4: said in the bar; nothing typed to lose
        self.card = PasteCard(self.shell.window(), self._pasted, refused=lambda: moves.refused())
        register = getattr(self.shell, "register_overlay", None)
        if register is not None:
            register(self.card)
        self.card.open()
        return self.card

    def _pasted(self, title, text):
        title = title.strip() or strings.PASTE_DEFAULT_TITLE

        def written(path):
            folder = os.path.dirname(path)
            if self.add_files([path], name=title, origin=False, then=lambda: bridge.run_in_worker(
                    shutil.rmtree, folder, True)) is None:  # N7: removed once it landed; refused: where it is, said
                windows.say_in_bar(self.shell, strings.PASTE_KEPT.format(folder=folder))
        qpress.run(None, ("paste", id(text)), write_pasted, title, text, busy=strings.ADDING.format(name=title),
                   then=written, failed=lambda info: windows.say_in_bar(self.shell, strings.PASTE_FAILED.format(
                       why=info[0])), win=self.shell)         # round 8 row 45: *Adding…* in the bar from the press


def _alive(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


# --- the stone ---------------------------------------------------------------------------------------------------- #
def stone_points(cx, cy, r):
    """An octagon a little uneven (fixed: the same stone every paint), its points from the top left round."""
    return [QPointF(cx + r * w * math.cos(math.pi / 8 + k * math.pi / 4),
                    cy + r * w * math.sin(math.pi / 8 + k * math.pi / 4)) for k, w in enumerate(WOBBLE)]


class AddStone(QToolButton):
    """The + stone (see the module's doc); its menu is the adder's entries."""

    def __init__(self, adder, parent=None):
        super().__init__(parent)
        self.adder = adder
        self.setObjectName("addstone")
        self.setAccessibleName(strings.ADD_NAME)
        self.setToolTip(strings.ADD_TIP)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lift = 0.0                                   # 0 at rest, 1 under the hand (the 1 px rise)
        self._hover = None
        self.menu_ = QMenu(self)
        self.menu_.setObjectName("addmenu")
        self.menu_.setAccessibleName(strings.ADD_MENU_NAME)
        self.menu_.setToolTipsVisible(True)
        self.menu_.aboutToShow.connect(self._fill)
        self.menu_.aboutToHide.connect(lambda: QTimer.singleShot(0, self._empty))
        self.setMenu(self.menu_)
        self.restyle()

    def restyle(self):
        side = round(theme.size("button", style.current()[1]) * 1.15)       # the reference's 36.8 at Medium
        self.setFixedSize(side, side)

    def _fill(self):
        self.menu_.clear()
        why = self.adder.why_not()
        for name, label, tip in self.adder.entries():
            act = self.menu_.addAction(label)
            act.setToolTip(why if why and name in COPIES else tip)
            act.setEnabled(not (why and name in COPIES))  # S4 (E4): greyed with the store's reason
            act.setObjectName(f"add-{name}")
            act.triggered.connect(lambda _c=False, n=name: QTimer.singleShot(0, lambda: self.adder.run(n)))
        if self.adder._moves() is not None:
            self.menu_.addSeparator()
            line = self.menu_.addAction(strings.ADD_DROP_LINE)
            line.setEnabled(False)

    def _empty(self):
        if not self.menu_.isVisible():
            self.menu_.clear()                            # rebuilt at the next open (a door may come or go)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._rise(1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._rise(0.0)

    def _rise(self, target):
        """Under the hand it rises (`press`'s spring, ω 36: the reference's .12 s); Reduced motion jumps."""
        if self._hover is not None and self._hover.alive:
            self._hover.retarget(target)
            return
        omega, zeta = theme.SPRINGS["press"]
        self._hover = motion.clock().spring(self._set_lift, self.lift, target, omega, zeta, owner=self)

    def _set_lift(self, value):
        if value != self.lift:
            self.lift = value
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base, light, edge = (style.qcolor(v) for v in theme.GEM["sapphire"])
        bright = 100 + round(25 * self.lift)              # brightness 1.25 under the hand
        deep, face, table = base.darker(135).lighter(bright), base.lighter(bright), light.lighter(bright)
        w, h = self.width(), self.height()
        r = min(w, h) * 0.28
        cx, cy = w / 2, h / 2 - self.lift                 # rises 1 px
        outer = stone_points(cx, cy, r)
        inner = stone_points(cx - r * 0.06, cy - r * 0.08, r * 0.58)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(deep)
        p.drawPolygon(QPolygonF(outer))
        for k, facing in enumerate(LIGHT):              # the bevel's facets, lit by their facing (light: top left)
            facet = QPolygonF([outer[k], outer[(k + 1) % 8], inner[(k + 1) % 8], inner[k]])
            p.setBrush(face.lighter(100 + round(45 * facing)) if facing > 0 else face.darker(100 - round(40 * facing)))
            p.drawPolygon(facet)
        p.setBrush(table)
        p.drawPolygon(QPolygonF(inner))
        pen = QPen(edge.lighter(bright), max(1.6, r * 0.22))  # the + cut in its table
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        arm = r * 0.34
        c = QPointF(cx - r * 0.06, cy - r * 0.08)
        p.drawLine(QPointF(c.x() - arm, c.y()), QPointF(c.x() + arm, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - arm), QPointF(c.x(), c.y() + arm))
        if self.hasFocus():
            ring = QPen(style.qcolor(style.colours()["accent"]), 2)
            p.setPen(ring)
            p.setBrush(Qt.BrushStyle.NoBrush)
            radius = theme.RADII["icon-button"]
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), radius, radius)
        p.end()


# --- Paste text… -------------------------------------------------------------------------------------------------- #
class PasteCard(motion.Overlay):
    """The paste card (see the module's doc). `on_add(title, text)` once *Add* is pressed."""
    how = "dialog"
    shadow_name = "dialog"
    focus = True

    def __init__(self, window, on_add, refused=None):
        super().__init__(window)
        self._refused = refused                           # S4: () -> None, or the bar's words (the card stays open)
        self.setObjectName("pastecard")
        self.setAccessibleName(strings.PASTE_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._window = window
        self._on_add = on_add
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        pad = round(20 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(10 * f))
        heading = QLabel(strings.PASTE_HEADING, self)
        heading.setObjectName("pasteheading")
        box.addWidget(heading)
        self.title = QLineEdit(self)
        self.title.setPlaceholderText(strings.PASTE_TITLE_PLACEHOLDER)
        self.title.setAccessibleName(strings.PASTE_TITLE_NAME)
        box.addWidget(self.title)
        self.text = QPlainTextEdit(self)
        self.text.setPlaceholderText(strings.PASTE_TEXT_PLACEHOLDER)
        self.text.setAccessibleName(strings.PASTE_TEXT_NAME)
        self.text.setMinimumHeight(round(180 * f))
        self.text.setTabChangesFocus(True)
        box.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel = QPushButton(strings.PASTE_CANCEL, self)
        self.cancel.setToolTip(strings.PASTE_CANCEL_TIP)
        self.cancel.clicked.connect(self.close)
        self.add = QPushButton(strings.PASTE_ADD, self)
        self.add.setProperty("kind", "primary")
        self.add.setToolTip(strings.PASTE_ADD_TIP)
        self.add.clicked.connect(self._add)
        self.add.setEnabled(False)
        self.text.textChanged.connect(lambda: self.add.setEnabled(bool(self.text.toPlainText().strip())))
        for b in (self.cancel, self.add):
            b.setAccessibleName(b.text())
            b.setAutoDefault(False)
            row.addWidget(b)
        box.addLayout(row)
        self.scrim = confirm.Scrim(window, self.close)
        self.shadow = shadow.Follower(self, self.shadow_name)
        window.installEventFilter(self)
        self.hide()

    def place(self):
        w = self._window
        f = theme.text_factor(style.current()[1])
        width = min(round(theme.size("dialog", style.current()[1])), max(1, w.width() - 2 * confirm.MARGIN))
        height = min(round(360 * f), max(1, w.height() - 2 * confirm.MARGIN))
        self.setGeometry((w.width() - width) // 2, max(0, (w.height() - height) // 2), width, height)

    def open(self):
        self.place()
        self.scrim.show()
        self.scrim.raise_()
        return motion.open_overlay(self, self.how, self.shadow_name, on_done=self._focus_title, focus=True)

    def _focus_title(self):
        if self.isVisible():
            self.title.setFocus(Qt.FocusReason.OtherFocusReason)

    def _add(self):
        text = self.text.toPlainText()
        if not text.strip():
            return
        title = self.title.text()
        if self._refused is not None and self._refused() is not None:
            return                                        # S4: can't be saved now: the text stays on screen
        callback, self._on_add = self._on_add, None
        self.close()
        if callback is not None:
            callback(title, text)

    def closeEvent(self, event):
        super().closeEvent(event)
        if _alive(self.scrim):
            self.scrim.hide()
            self.scrim.deleteLater()
        self.deleteLater()

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["dialog"])
        p.end()
