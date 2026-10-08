"""The first screens (W2.2; the window's spec 05 §5.1–5.2, 02 §2.4, 06 E1–E4, E14–E16): Current (the hero, the rows,
the lines, the Goal strip), Finished and Needs you — display only; moves arrive in W3.1, the Goal sheet, Needs you's
actions and covers in W3.2.

Each page is a heading, a thin state bar (*Getting your library ready…*, *Read-only: …*, *Updating your library…*) and
one painted list (`rows.RowsView`); Current adds the Goal strip under its list. A page takes the reader's `View`
(`app/services/view_rows.py`, built off the GUI thread by `app/services/library_reader.py`) and turns it into the list's
entries — nothing is worked out here. ▶ asks for a file: the page looks for it on a worker (`bridge.run_in_worker`)
and hands it to the system's player, or says in the bar why it can't.
"""
import os
import re
import sys

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app import path_utils, theme
from app.qt import bridge, rows, strings, style
from app.services import view_rows

VIDEO_EXTS = (".mkv", ".mp4", ".webm", ".m4v", ".avi", ".mov")
AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".flac", ".wav")
_LANGUAGE_TAG = re.compile(r"\.[a-z]{2,3}(?:[-_][A-Za-z]{2,4})?$")


def state_line(view):
    """The page's state bar for a view, or "" (02 §2.4): getting ready, read-only with its reason, busy."""
    if view is None:
        return ""
    if view.state == "getting-ready":
        if view.reason == "migration failed":           # never "getting ready" forever (G1.2-18: why, what to do)
            return strings.STATE_LINES["migration-failed"]
        return strings.STATE_LINES["getting-ready"]
    if view.state == "read-only":
        reason = view.reason or ""
        plain = strings.READ_ONLY_REASONS.get(reason) or (strings.READ_ONLY_IO if reason.startswith("io") else reason)
        return strings.STATE_LINES["read-only"].format(reason=plain)
    if view.busy:
        return strings.STATE_LINES["busy"]
    return ""


def media_to_open(language, episode, media):
    """The file ▶ opens for an episode, or (None, why): the video (or audio) beside its content file — same name, a
    player's extension — else, for a book or a text, the file itself. Runs on a worker (it looks at the disk)."""
    rel = episode.rel_path or ""
    path = os.path.join(path_utils.get_data_path(language), *rel.split("/"))
    word = view_rows.MEDIA_WORD.get(media, "video")
    if word in ("EPUB", "file"):
        return (path, None) if os.path.exists(path) else (None, strings.PLAY_FAILED.format(
            name=episode.label, why=strings.PLAY_NOT_ON_DISK))
    base = os.path.splitext(path)[0]
    bases = [base]
    tagged = _LANGUAGE_TAG.sub("", base)            # `ep01.ja.srt`, `ep01.zh-Hans.ass` → `ep01.mkv`
    if tagged != base:
        bases.append(tagged)
    for b in bases:
        for ext in (AUDIO_EXTS if word == "audio" else VIDEO_EXTS):
            if os.path.exists(b + ext):
                return b + ext, None
    return None, strings.PLAY_FAILED.format(name=episode.label, why=strings.PLAY_NO_MEDIA_BESIDE.format(word=word))


def open_with_system(path):
    if sys.platform == "win32":
        os.startfile(path)                          # the user's own player
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# --- small parts ------------------------------------------------------------------------------------------------- #
class StateBar(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statebar")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setVisible(False)

    def show_line(self, text):
        self.setText(text)
        self.setAccessibleName(text)
        self.setVisible(bool(text))


class GoalStrip(QWidget):
    """Goal, docked under Current's list (mock `.goalbar`): the box mark, *Goal*, up to nine small covers, *N titles ·
    N files*. Display only in W2.2 (the sheet it opens is W3.2's)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("goalstrip")
        self.goal = None
        self._pix = self._pix_key = None             # painted once into a pixmap, reused until it or its look changes
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(strings.GOAL_NAME)

    def sizeHint(self):
        return QSize(400, round(theme.SIZES["goal-strip"] * rows.fz()) + 18)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_goal(self, goal):
        self.goal = goal
        self.setToolTip(goal.tip if goal else "")
        self.setAccessibleName(strings.GOAL_ACCESSIBLE.format(name=strings.GOAL_NAME, line=goal.line) if goal
                               else strings.GOAL_NAME)
        self.setFixedHeight(self.sizeHint().height())
        self.update()

    def paintEvent(self, _event):
        """Blits its pixmap: a tab switch or a window repaint draws nothing afresh here (0.4–0.5 ms a paint at 150 %,
        W2.2 profile 2026-10-08)."""
        if self.goal is None:
            return
        dpr = self.devicePixelRatioF() or 1.0
        key = (self.goal, self.width(), self.height(), dpr, style.current())
        if key != self._pix_key:
            pix = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(rows.c("bg"))                   # the page's ground: text keeps its subpixel smoothing
            q = QPainter(pix)
            self._draw(q, dpr)
            q.end()
            self._pix, self._pix_key = pix, key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pix)
        p.end()

    def _draw(self, p, dpr):
        f = rows.fz()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        box = QRectF(24.5, 8.5, self.width() - 49, theme.SIZES["goal-strip"] * f - 1)
        p.setPen(QPen(rows.c("line"), 1))
        p.setBrush(rows.c("surface"))
        p.drawRoundedRect(box, 10, 10)
        x = box.left() + 14
        mid = box.center().y()
        rows.icon(p, "box", QRectF(x, mid - 8.5, 17, 17), rows.c("ink-dim"))
        x += 17 + 12
        w, _ = rows.TEXT.draw(p, x, mid, strings.GOAL_NAME, "goal-label", 200, rows.c("ink"), dpr=dpr)
        x += w + 12
        if self.goal.covers:
            cw, ch = 20 * f, 29 * f
            for i, title in enumerate(self.goal.covers):
                r = QRectF(x + i * (cw - 7), mid - ch / 2, cw, ch)
                path = QPainterPath()
                path.addRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 4, 4)
                p.fillPath(path, rows.c("surface"))
                p.drawPixmap(r.topLeft(), rows.cover(title, round(cw), round(ch), dpr))
            x += len(self.goal.covers) * (cw - 7) + 7 + 12
        rows.TEXT.draw(p, x, mid, self.goal.line, "row-sub", box.right() - x - 14, rows.c("ink-faint"), dpr=dpr)


# --- the pages ------------------------------------------------------------------------------------------------------ #
def same_objects(a, b):
    """Two tuples holding the same objects, in order."""
    return a is b or (len(a) == len(b) and all(x is y for x, y in zip(a, b)))


class Page(QWidget):
    message = pyqtSignal(str)                       # a line for the bottom bar (a file that couldn't open)

    def __init__(self, name, heading, tooltips=None, language="ja", parent=None):
        super().__init__(parent)
        self.setObjectName(f"page-{name}")
        self.name = name
        self.language = language
        self.view_model = None
        box = QVBoxLayout(self)
        top, side, _bottom = theme.SPACING["current-body"]
        box.setContentsMargins(side, top, side, 0)
        box.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.heading = QLabel(heading, self)
        self.heading.setObjectName("currentheading" if name == "current" else "pageheading")
        head.addWidget(self.heading)
        self.head_row = head
        head.addStretch(1)
        box.addLayout(head)
        self.state_bar = StateBar(self)
        box.addWidget(self.state_bar)
        self.list = rows.RowsView(strings.LIST_NAMES.get(name, heading), tooltips=tooltips, parent=self)
        self.list.play_requested.connect(self._play)
        box.addWidget(self.list, 1)

    def entries(self, view):
        raise NotImplementedError

    def unchanged(self, old, new):
        """Whether this page's part of the view is the same as last time (no entries built, nothing diffed)."""
        return False

    def set_view(self, view):
        old, self.view_model = self.view_model, view
        line = state_line(view)
        if line != self.state_bar.text() or self.state_bar.isHidden() == bool(line):   # only when it changes
            self.state_bar.show_line(line)
        if old is not None and view is not None and old.loading == view.loading and self.unchanged(old, view):
            self.list.model().changed = []
            return "same"                               # another page's change: this list's diff costs nothing
        return self.list.set_entries(self.entries(view))

    def _media_of(self, episode):
        """The media type of the row an episode is in (looked up on a click, not kept per view: a view at 20,000 files
        must cost the GUI thread as little as it can)."""
        for kind, payload, _lines in self.list.model().entries:
            if any(e.id == episode.id for e in getattr(payload, "episodes", ())):
                return payload.media
        return None

    def _play(self, episode):
        media = self._media_of(episode)
        bridge.run_in_worker(media_to_open, self.language, episode, media, then=self._open_found,
                             failed=lambda info: self.message.emit(strings.PLAY_FAILED.format(
                                 name=episode.label, why=str(info[0]))))

    def _open_found(self, found):
        path, why = found
        if path is None:
            self.message.emit(why)
            return
        if sys.platform != "win32":                       # Qt's own opener belongs on the GUI thread
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        bridge.run_in_worker(open_with_system, path,
                             failed=lambda info: self.message.emit(strings.PLAY_FAILED.format(
                                 name=os.path.basename(path), why=str(info[0]))))


class CurrentPage(Page):
    def __init__(self, tooltips=None, language="ja", parent=None):
        super().__init__("current", strings.CURRENT_HEADING, tooltips, language, parent)
        self.heading.setToolTip(strings.CURRENT_HEADING_TIP)
        self.goal_strip = GoalStrip(self)
        self.layout().addWidget(self.goal_strip)
        self.goal_strip.setVisible(False)

    def entries(self, view):
        if view is None:
            return []
        if not view.rows:
            return [] if view.loading else [(rows.EMPTY, strings.CURRENT_EMPTY, ())]
        after = {}
        for ln in view.lines:
            after.setdefault(ln.after, []).append(ln)
        out = []
        for i, r in enumerate(view.rows):
            out.append((rows.HERO if i == 0 else rows.ROW, r, tuple(after.get(i, ()))))
        return out

    def unchanged(self, old, new):
        # the reader's row cache keeps an unchanged row the same object, so an identity walk is the whole check
        return old.lines == new.lines and same_objects(old.rows, new.rows)

    def set_view(self, view):
        how = super().set_view(view)
        if view is not None and view.goal is not None:
            if view.goal != self.goal_strip.goal:         # repainted only when Goal changed
                self.goal_strip.set_goal(view.goal)
            self.goal_strip.setVisible(bool(view.rows) or bool(view.goal.files) or not view.loading)
        return how


class FinishedPage(Page):
    def __init__(self, tooltips=None, language="ja", parent=None):
        super().__init__("finished", strings.FINISHED_HEADING, tooltips, language, parent)
        self.help = QLabel(strings.FINISHED_HELP, self)
        self.help.setObjectName("helpmark")
        self.help.setToolTip(strings.FINISHED_HELP_TIP)
        self.help.setAccessibleName(strings.FINISHED_HELP_NAME)
        self.help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.head_row.insertWidget(1, self.help)

    def unchanged(self, old, new):
        return len(old.finished) == len(new.finished) and all(
            a.label == b.label and same_objects(a.rows, b.rows) for a, b in zip(old.finished, new.finished))

    def entries(self, view):
        if view is None:
            return []
        if not view.finished:
            return [] if view.loading else [(rows.EMPTY, strings.FINISHED_EMPTY, ())]
        out = []
        for month in view.finished:
            out.append((rows.MONTH, month.label, ()))
            out.extend((rows.FINISHED, r, ()) for r in month.rows)
        return out


class NeedsPage(Page):
    def __init__(self, tooltips=None, language="ja", parent=None):
        super().__init__("needs", strings.NEEDS_HEADING, tooltips, language, parent)
        self.failures = ()

    def set_failures(self, entries):
        self.failures = tuple(entries or ())
        if self.view_model is not None:
            self.list.set_entries(self.entries(self.view_model))

    def unchanged(self, old, new):
        return old.needs == new.needs

    def entries(self, view):
        out = [(rows.NEED, n, ()) for n in (view.needs if view is not None else ())]
        out += [(rows.FAILURE, e, ()) for e in self.failures]
        if not out and view is not None and not view.loading:
            out = [(rows.EMPTY, strings.NEEDS_EMPTY, ())]
        return out


PAGES = {"current": CurrentPage, "finished": FinishedPage, "needs": NeedsPage}


def make_page(name, tooltips=None, language="ja", parent=None):
    return PAGES[name](tooltips=tooltips, language=language, parent=parent)
