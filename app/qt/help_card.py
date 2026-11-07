"""The help card (the help cards' spec §6; HG-1…HG-5, HC-2…HC-4; Sonic 2026-11-06 "Ok do it", into 3.0): one card per
area of the window, opened by its **?** (`help_mark`), by *Why?* on a toast (its cause on top), by the strip's ? (every
lit circle and why) and by the tour of what runs by itself (item 11). The catalog is Qt-free
(`app/services/help_cards.py`); the words are `strings.HELP_*`.

- **A sheet over the window** (`Confirm`'s look and scrim: a `motion.Overlay` opened as a `dialog`): Esc, Back and a
  click outside close it (the shell's `EscapeRouter`); Tab goes round its buttons; every button has a tooltip.
  **Built once** — the first open of a window makes it, every later open only sets its words (R5: a later open makes
  no widget); *All help*'s list is made the first time it shows.
- **In order:** title · (opened by *Why?*: *Why this happened* and the cause, in the accent) · what it is · the clip (or
  the still) · before → after · its extra line · *Try it* · *Open its settings* · the foot: *All help* · *What runs by
  itself* · *Online guide* (HG-3) · *Close*. In the tour: *n of N* · *Back* · *Next* / *Done*, and its last card's foot
  line. Nothing is remembered.
- **The clip** (`ClipPlayer`): the WebP read with `QImageReader` **on a worker** (`bridge.run_in_worker`; no widget
  touched there), two frames kept ahead, scaled to the box × the screen's scale; on the GUI thread only the frame is
  swapped, on `motion`'s one clock (a `loop`), and only while the card is shown, its window not minimised and nothing
  frozen. Closing the card stops it and frees its frames. **Reduced motion** (live): the poster (the *after*) and ▶,
  which plays it once. A missing or unreadable clip: the poster, else the words alone — never an error.
- **A toast stays** while its card is open: its time pauses and runs on as the card closes (`done`, the toast's).
- **Try it** (§6.5) runs a press the window already has (`host.help_try(key, control)`, through `press`), shown only
  when it can run (`host.help_try_ready(key)`: None, else what's missing — the card says it, and *Open its settings*).
"""
import collections
import threading
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QImageReader, QPainter
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
                             QWidget)

from app import theme
from app.qt import bridge, freeze, motion, shadow, strings, style
from app.qt.confirm import MARGIN, Scrim, _register
from app.services import causes as causes_service
from app.services import help_cards

WIDTH = 520                         # px at 100 % (× the text size): the card
BOX = (480, 300)                    # px at 100 %: the clip's box
AHEAD = 2                           # decoded frames kept ahead of the one shown
ROWS = 8                            # list lines made at most (the automation list: 7; the lit circles)


# --- the clip ------------------------------------------------------------------------------------------------------ #
def _reader(path, size):
    """(A worker.) A `QImageReader` for `path` that scales each frame to `size` (device pixels)."""
    reader = QImageReader(path)
    reader.setAutoTransform(False)
    if size is not None:
        reader.setScaledSize(size)
    return reader


class ClipPlayer(QWidget):
    """The card's clip box. `set_clip(clip, poster, words)`; `stop()` lets every frame go. `reader_factory(path, size)`:
    a test's stand-in (it records the thread it decodes on)."""

    def __init__(self, parent=None, reader_factory=None):
        super().__init__(parent)
        self.setObjectName("helpclip")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._factory = reader_factory or _reader
        self.clip = self.poster_path = None
        self.words = ""
        self._image = None                  # the frame shown (a QImage, at the device-pixel size)
        self._poster = None
        self._ahead = collections.deque()   # (QImage, delay ms) decoded and waiting
        self._reader = {}                   # {"reader": QImageReader} — touched only by the one decode in flight
        self._busy = False                  # a decode in flight (one at a time)
        self._token = 0                     # which clip a worker's answer is for (a new clip drops older answers)
        self._due = 0.0                     # time.monotonic() the next frame may show from
        self._anim = None
        self._once = False                  # ▶ pressed under Reduced motion: play to the end, once
        self._watched = None
        self.decoded = 0                    # frames decoded (tests)
        self.swaps = 0                      # frames shown (tests)
        f = theme.text_factor(style.current()[1])
        self.setFixedSize(round(BOX[0] * f), round(BOX[1] * f))
        self.play = QToolButton(self)
        self.play.setText(strings.HELP_PLAY)
        self.play.setToolTip(strings.HELP_PLAY_TIP)
        self.play.setAccessibleName(strings.HELP_PLAY_TIP)
        self.play.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.play.clicked.connect(lambda _c=False: self.play_once())
        self.play.hide()
        motion.clock().mode.changed.connect(self._sync)

    # --- what it shows ----------------------------------------------------------------------------------------- #
    def set_clip(self, clip, poster, words):
        """A new clip (or none): everything of the last one let go, the poster asked for (on a worker)."""
        self.stop()
        self.clip, self.poster_path, self.words = clip, poster, words
        self.setAccessibleName(strings.HELP_CLIP_NAME.format(line=words))
        self.setVisible(bool(clip or poster))
        if poster:
            token = self._token
            bridge.run_in_worker(_load_image, poster, self._device_size(),
                                 then=lambda img, t=token: self._got_poster(t, img))
        self._sync()

    def stop(self):
        """Stop, and let every frame go (a closed card holds nothing)."""
        self._token += 1
        self._end_anim()
        self._ahead.clear()
        self._reader = {}
        self._busy = False
        self._image = self._poster = None
        self._once = False
        self.play.hide()

    def play_once(self):
        """▶ (Reduced motion): the clip once, from its start — the learner's own choice."""
        if not self.clip:
            return
        self._once = True
        self._token += 1
        self._ahead.clear()
        self._reader = {}
        self._busy = False
        self.play.hide()
        self._sync(force=True)

    # --- the one clock ----------------------------------------------------------------------------------------- #
    def _wanted(self):
        if not self.clip or freeze.frozen() or not self.isVisible():
            return False
        top = self.window()
        if top is not None and top.isMinimized():
            return False
        return self._once or not motion.clock().mode.reduced

    def _sync(self, *_args, force=False):
        if sip.isdeleted(self):
            return
        reduced = motion.clock().mode.reduced
        self.play.setVisible(bool(self.clip) and reduced and not self._once)
        if self._wanted():
            if self._anim is None or not self._anim.alive or force:
                self._end_anim()
                self._anim = motion.clock().animate(motion.duration("help-clip"), self._tick, kind="loop",
                                                    repeat=True, owner=self)
                self._due = time.monotonic()
            self._fill()
        else:
            self._end_anim()
            if reduced and not self._once and self._image is not None and self._poster is not None:
                self._image = None              # back on the poster (its *after*)
                self.update()

    def _end_anim(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def _tick(self, _phase):
        """(The clock.) The next frame, if its time has come and it is decoded: a picture swap, nothing more."""
        if time.monotonic() < self._due or not self._ahead:
            self._fill()
            return
        image, delay = self._ahead.popleft()
        self._image = image
        self.swaps += 1
        self._due = time.monotonic() + max(20, delay) / 1000.0
        self.update()
        self._fill()

    def _fill(self):
        """Ask the worker for the next frame while fewer than `AHEAD` wait (one decode at a time)."""
        if self._busy or len(self._ahead) >= AHEAD or not self.clip:
            return
        self._busy = True
        token = self._token
        bridge.run_in_worker(_decode, self._reader, self._factory, self.clip, self._device_size(), self._once,
                             then=lambda got, t=token: self._got(t, got),
                             failed=lambda _e, t=token: self._failed(t))

    def _got(self, token, got):
        if token != self._token or sip.isdeleted(self):
            return
        self._busy = False
        image, delay, ended = got
        if image is not None:
            self.decoded += 1
            self._ahead.append((image, delay))
        if ended and self._once:
            self._once = False                  # played once: it rests on its last frame
            if not self._ahead and image is None:
                self._end_anim()
            QTimer.singleShot(max(0, int(delay or 0)), self._sync)
            return
        if image is None and not ended:
            self.clip = None                    # unreadable: the poster, else the words alone
            self._sync()
            return
        if self._anim is not None:
            self._fill()

    def _failed(self, token):
        if token == self._token and not sip.isdeleted(self):
            self._busy = False
            self.clip = None
            self._sync()

    def _got_poster(self, token, image):
        if token == self._token and not sip.isdeleted(self) and image is not None:
            self._poster = image
            self.update()

    def _device_size(self):
        ratio = self.devicePixelRatioF() or 1.0
        return QSize(max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio)))

    # --- Qt -------------------------------------------------------------------------------------------------- #
    def showEvent(self, event):
        super().showEvent(event)
        top = self.window()
        if top is not self._watched and top is not None:
            if self._watched is not None and not sip.isdeleted(self._watched):
                self._watched.removeEventFilter(self)
            top.installEventFilter(self)
            self._watched = top
        self._sync()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync()

    def eventFilter(self, obj, event):
        if obj is self._watched and event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.Hide,
                                                    QEvent.Type.Show):
            QTimer.singleShot(0, self._sync)
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        side = round(28 * theme.text_factor(style.current()[1]))
        self.play.setGeometry((self.width() - side) // 2, (self.height() - side) // 2, side, side)

    def paintEvent(self, _event):
        image = self._image if self._image is not None else self._poster
        p = QPainter(self)
        c = style.colours()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(c["raised"]))
        radius = theme.RADII["toast"]
        p.drawRoundedRect(QRectF(self.rect()), radius, radius)
        if image is not None:
            p.drawImage(QRectF(self.rect()), image)          # (decoded at the box's device size: no scaling here)
        p.end()


def _decode(holder, factory, path, size, from_start):
    """(A worker.) The clip's next frame: (QImage or None, its delay in ms, whether the clip ended). The reader lives in
    `holder`, made here; at its end it is made again (the loop) — unless it plays once."""
    reader = holder.get("reader")
    if reader is None:
        reader = holder["reader"] = factory(path, size)
    if not reader.canRead():
        if from_start and holder.get("read"):
            return None, 0, True
        reader = holder["reader"] = factory(path, size)    # the loop: from its first frame again
        if not reader.canRead():
            return None, 0, False
    image = reader.read()
    if image is None or image.isNull():
        return None, 0, bool(holder.get("read"))
    holder["read"] = True
    ended = not reader.canRead()
    return image, reader.nextImageDelay(), ended and from_start


def _load_image(path, size):
    """(A worker.) A still or a poster, scaled to `size` (device pixels) keeping its shape; None when unreadable."""
    image = QImage(path)
    if image.isNull():
        return None
    return image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


# --- the card ------------------------------------------------------------------------------------------------------ #
class HelpCard(motion.Overlay):
    """The window's one help card (made by `card_for`). `host`: the main window (`open_setting`, `_open_guide`,
    `help_try`, `help_try_ready`, `phase` — the strip, for the circles' card)."""
    how = "dialog"
    shadow_name = "dialog"
    focus = True

    def __init__(self, window, host, has_module=None):
        super().__init__(window)
        self.setObjectName("helpcard")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._window = window
        self.host = host
        self.has_module = has_module
        self.card_id = None                 # the card shown (None: *All help*)
        self.cause = None
        self.tour = None                    # (ids, index) while the tour runs
        self._done = []                     # callbacks for the close (a toast's paused time)
        self._before = None
        self.builds = 0                     # *All help*'s list made (tests: once)
        f = self._f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        pad = round(20 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(8 * f))
        self.title = self._label("confirmtitle", box)
        self.cause_head = self._label("helpcausehead", box)
        self.cause_head.setText(strings.HELP_CAUSE_HEADING)
        self.cause_line = self._label("helpcause", box)
        self.line = self._label("confirmline", box)
        self.clip = ClipPlayer(self)
        box.addWidget(self.clip, 0, Qt.AlignmentFlag.AlignHCenter)
        self.still = QLabel(self)
        self.still.setObjectName("helpstill")
        self.still.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.still.hide()
        box.addWidget(self.still, 0, Qt.AlignmentFlag.AlignHCenter)
        self.after = self._label("helpafter", box)
        self.also = self._label("helpalso", box)
        self.rows = []                      # the list's lines (the automation list, the lit circles), made once
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(round(2 * f))
        box.addLayout(self.list_box)
        self.all_box = QVBoxLayout()        # *All help*'s list (made the first time it shows)
        self.all_box.setSpacing(round(4 * f))
        box.addLayout(self.all_box)
        self.all_parts = []
        self.missing = self._label("helpalso", box)
        acts = QHBoxLayout()
        acts.setSpacing(round(10 * f))
        self.try_it = self._button(strings.HELP_TRY["sync_known"][0], "", self._try, acts, kind="primary")
        self.settings = self._button(strings.HELP_SETTINGS, strings.HELP_SETTINGS_TIP, self._settings, acts)
        acts.addStretch(1)
        box.addLayout(acts)
        steps = QHBoxLayout()
        steps.setSpacing(round(10 * f))
        self.step = QLabel(self)
        self.step.setObjectName("helpalso")
        steps.addWidget(self.step)
        steps.addStretch(1)
        self.back = self._button(strings.HELP_BACK, strings.HELP_BACK_TIP, lambda: self._step(-1), steps)
        self.next = self._button(strings.HELP_NEXT, strings.HELP_NEXT_TIP, lambda: self._step(1), steps,
                                 kind="primary")
        box.addLayout(steps)
        self.tour_foot = self._label("helpalso", box)
        self.tour_foot.setText(strings.HELP_TOUR_FOOT)
        foot = QHBoxLayout()
        foot.setSpacing(round(4 * f))
        self.all = self._button(strings.HELP_ALL, strings.HELP_ALL_TIP, self.show_all, foot, kind="link")
        self.tour_button = self._button(strings.HELP_TOUR, strings.HELP_TOUR_TIP, self.show_tour, foot, kind="link")
        self.guide = self._button(strings.HELP_GUIDE, strings.HELP_GUIDE_TIP, self._guide, foot, kind="link")
        foot.addStretch(1)
        self.close_button = self._button(strings.HELP_CLOSE, strings.HELP_CLOSE_TIP, self.close, foot)
        box.addLayout(foot)
        self._steps_parts = (self.step, self.back, self.next)
        self.scrim = Scrim(window, self.close)
        self.scrim.hide()
        self.shadow = shadow.Follower(self, self.shadow_name)
        window.installEventFilter(self)
        _register(window, self)
        self.hide()

    def _label(self, name, box):
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        box.addWidget(label)
        return label

    def _button(self, text, tip, on_press, row, kind=None):
        b = QPushButton(text, self)
        b.setToolTip(tip)
        b.setAccessibleName(text)
        b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        b.setAutoDefault(False)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _c=False: on_press())
        row.addWidget(b)
        return b

    # --- what it shows ---------------------------------------------------------------------------------------- #
    def show_card(self, card_id, cause=None, done=None, tour=None):
        """Card `card_id` (unknown or unavailable: *All help*); `cause` opened it (*Why?*: said first); `done()` when it
        closes; `tour`: (ids, index) while the tour runs. -> self."""
        if not help_cards.available(card_id, self.has_module):
            return self.show_all(done=done)
        if done is not None:
            self._done.append(done)
        self.card_id, self.cause, self.tour = card_id, cause, tour
        title, line, after = strings.HELP_CARDS[card_id]
        self.setAccessibleName(title)
        self.title.setText(title)
        said = causes_service.said(cause, None, strings.HELP_CAUSE_WHY, strings.HELP_CAUSE_WHY_AT) \
            if cause is not None else ""
        self.cause_head.setVisible(bool(said))
        self.cause_line.setVisible(bool(said))
        self.cause_line.setText(said)
        self.line.setText(line)
        self.line.show()
        files = help_cards.files(card_id)
        card = help_cards.BY_ID[card_id]
        self.clip.set_clip(files["clip"], files["poster"], after)
        self._still(None if files["clip"] or files["poster"] else (files["stills"] or [None])[0])
        self.after.setText(after)
        self.after.setVisible(bool(after))
        also = strings.HELP_ALSO.get(card_id, "")
        self.also.setText(also)
        self.also.setVisible(bool(also))
        self._list(self._lines(card_id))
        self._all_visible(False)
        self._try_it(card)
        self.settings.setVisible(bool(card.settings))
        self._tour_parts()
        self._open()
        return self

    def show_all(self, done=None):
        """*All help*: every card that shows, by area; a press opens it."""
        if done is not None:
            self._done.append(done)
        self.card_id, self.cause, self.tour = None, None, None
        self.setAccessibleName(strings.HELP_ALL_HEADING)
        self.title.setText(strings.HELP_ALL_HEADING)
        for w in (self.cause_head, self.cause_line, self.line, self.after, self.also, self.missing, self.try_it,
                  self.settings, self.still):
            w.hide()
        self.clip.set_clip(None, None, "")
        self._list(())
        self._build_all()
        self._all_visible(True)
        self._tour_parts()
        self._open()
        return self

    def show_tour(self):
        """The tour (item 11): its first available card; *Back* / *Next*, *n of N*."""
        ids = help_cards.tour(self.has_module)
        if not ids:
            return self.show_all()
        return self.show_card(ids[0], tour=(ids, 0))

    def _step(self, by):
        if self.tour is None:
            return
        ids, i = self.tour
        i += by
        if i >= len(ids):
            self.close()                        # *Done*
            return
        self.show_card(ids[max(0, i)], tour=(ids, max(0, i)))

    def _tour_parts(self):
        on = self.tour is not None
        for w in self._steps_parts:
            w.setVisible(on)
        if on:
            ids, i = self.tour
            self.step.setText(strings.HELP_STEP.format(n=i + 1, total=len(ids)))
            self.back.setEnabled(i > 0)
            last = i == len(ids) - 1
            self.next.setText(strings.HELP_DONE if last else strings.HELP_NEXT)
            self.next.setToolTip(strings.HELP_DONE_TIP if last else strings.HELP_NEXT_TIP)
            self.next.setAccessibleName(self.next.text())
            self.tour_foot.setVisible(last)
        else:
            self.tour_foot.hide()
        self.tour_button.setVisible(not on)

    def _lines(self, card_id):
        """The list under a card: the automation card's seven, or every lit circle and why (the strip's card)."""
        if card_id == "automation":
            return [strings.HELP_LIST_ITEM.format(line=line) for line in strings.HELP_AUTOMATION_LIST]
        if card_id == "circles":
            return [strings.HELP_LIT] + (lit_lines(getattr(self.host, "phase", None)) or [strings.HELP_LIT_NONE])
        return []

    def _list(self, lines):
        lines = list(lines)[:ROWS]
        while len(self.rows) < len(lines):
            self.rows.append(self._label("helpalso", self.list_box))
        for row, text in zip(self.rows, lines + [""] * (len(self.rows) - len(lines))):
            row.setText(text)
            row.setVisible(bool(text))

    def _build_all(self):
        if self.all_parts:
            return
        self.builds += 1
        for area, ids in help_cards.all_help(self.has_module):
            head = QLabel(strings.HELP_AREAS[area], self)
            head.setObjectName("helpcausehead")
            self.all_box.addWidget(head)
            row = QHBoxLayout()
            row.setSpacing(round(4 * self._f))
            for card_id in ids:
                b = QPushButton(strings.HELP_CARDS[card_id][0], self)
                b.setProperty("kind", "chip")
                b.setToolTip(strings.HELP_CARD_OPEN_TIP)
                b.setAccessibleName(strings.HELP_CARDS[card_id][0])
                b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                b.setAutoDefault(False)
                b.clicked.connect(lambda _c=False, i=card_id: self.show_card(i))
                row.addWidget(b)
                self.all_parts.append(b)
            row.addStretch(1)
            self.all_box.addLayout(row)
            self.all_parts.append(head)

    def _all_visible(self, on):
        for w in self.all_parts:
            w.setVisible(on)

    def _still(self, path):
        if not path:
            self.still.clear()
            self.still.hide()
            return
        self.still.show()
        size = QSize(round(BOX[0] * self._f), round(BOX[1] * self._f))
        self.still.setFixedSize(size)
        card = self.card_id

        def got(image, c=card):
            if c == self.card_id and image is not None and not sip.isdeleted(self):
                from PyQt6.QtGui import QPixmap
                pix = QPixmap.fromImage(image)
                pix.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
                self.still.setPixmap(pix)
        ratio = self.devicePixelRatioF() or 1.0
        bridge.run_in_worker(_load_image, path, QSize(round(size.width() * ratio), round(size.height() * ratio)),
                             then=got)

    def _try_it(self, card):
        key = card.try_it
        ready = getattr(self.host, "help_try_ready", None)
        why = None if key is None or ready is None else ready(key)
        can = key is not None and ready is not None and why is None
        if can:
            label, tip = strings.HELP_TRY[key]
            self.try_it.setText(label)
            self.try_it.setToolTip(tip)
            self.try_it.setAccessibleName(label)
        self.try_it.setVisible(can)
        self.missing.setText(why or "")
        self.missing.setVisible(bool(why))

    # --- the presses ------------------------------------------------------------------------------------------ #
    def _try(self):
        card = help_cards.BY_ID.get(self.card_id)
        run = getattr(self.host, "help_try", None)
        if card is not None and card.try_it and run is not None:
            run(card.try_it, self.try_it)

    def _settings(self):
        card = help_cards.BY_ID.get(self.card_id)
        if card is None or not card.settings:
            return
        self.close()
        opener = getattr(self.host, "open_setting", None)
        if opener is not None:
            opener(card.settings)

    def _guide(self):
        opener = getattr(self.host, "_open_guide", None)
        if opener is not None:
            opener(control=self.guide)

    # --- opening, closing ------------------------------------------------------------------------------------- #
    def place(self):
        w = self._window
        self.ensurePolished()
        width = min(round(WIDTH * self._f), max(1, w.width() - 2 * MARGIN))
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        if self.tour is not None and self.isVisible() and self.width() == width:
            height = max(height, self.height())     # (the tour never shrinks: the window behind is never re-exposed)
        height = min(height, max(1, w.height() - 2 * MARGIN))
        geometry = QRect((w.width() - width) // 2, max(0, (w.height() - height) // 2), width, height)
        if geometry != self.geometry():
            self.setGeometry(geometry)

    def _open(self):
        self.place()
        if self.isVisible() or motion.opening_of(self) is not None:
            self.update()                           # (the next card, in place: never opening again)
            return
        self._before = QApplication.focusWidget()
        self.scrim.setGeometry(self._window.rect())
        self.scrim.show()
        self.scrim.raise_()
        self.raise_()
        motion.open_overlay(self, self.how, self.shadow_name, on_done=self._focus_first, focus=True)

    def _focus_first(self):
        if self.isVisible():
            (self.next if self.tour is not None else self.close_button).setFocus(Qt.FocusReason.OtherFocusReason)

    def focusNextPrevChild(self, next_):
        """Tab and Shift+Tab go round the card's own buttons, never out to the window behind the scrim."""
        ring = [b for b in self.findChildren((QPushButton, QToolButton)) if b.isVisible() and b.isEnabled()]
        if not ring:
            return True
        now = QApplication.focusWidget()
        i = ring.index(now) if now in ring else -1
        ring[(i + (1 if next_ else -1)) % len(ring)].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous():
            self._closed()

    def closeEvent(self, event):
        super().closeEvent(event)
        self._closed()

    def _closed(self):
        self.scrim.hide()
        self.clip.stop()
        self.tour = None
        done, self._done = self._done, []
        for call in done:
            try:
                call()
            except Exception as e:
                print(f"Help card: a close's callback failed: {e}")
        before, self._before = self._before, None
        try:
            if before is not None and not sip.isdeleted(before) and before.isVisible():
                before.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(style.colours()["surface"]))
        radius = theme.RADII["dialog"]
        p.drawRoundedRect(QRectF(self.rect()), radius, radius)
        p.end()


def lit_lines(strip):
    """The circles' card's list (HC-2): each lit circle — its name and first line — and, under each job Surasura started
    by itself, why (`PhaseStrip.causes`, the hover's own words)."""
    if strip is None or not hasattr(strip, "states"):
        return []
    why = {}
    for circle, line, cause in strip.causes():
        why.setdefault(circle, []).append(strip.why_line(cause))
    out = []
    for circle, st in strip.states.items():
        if not (st.running or st.waiting or st.needs or st.failed or st.lines):
            continue
        first = st.needs or st.failed or (st.lines[0] if st.lines else "")
        name = strings.PHASE_NAMES[circle]
        out.append(strings.HELP_LIT_LINE.format(name=name, line=first) if first else name)
        out += [strings.HELP_LIT_WHY.format(line=line) for line in why.get(circle, ())]
    return out


def card_for(window, host=None, has_module=None):
    """`window`'s one help card, made on its first ask (then kept: R5)."""
    window = window.window()
    card = getattr(window, "_help_card", None)
    if card is None or sip.isdeleted(card):
        card = HelpCard(window, host or window, has_module=has_module)
        window._help_card = card
    return card


def open_card(widget, card_id, cause=None, done=None):
    """Open card `card_id` in `widget`'s window (its main window's card: a secondary window's ? opens it there)."""
    return card_for(_main(widget)).show_card(card_id, cause=cause, done=done)


def _main(widget):
    """The main window `widget` belongs to (a secondary window's parent chain), else its own window."""
    w = widget.window()
    while w is not None and not hasattr(w, "register_overlay"):
        parent = w.parentWidget()
        w = parent.window() if parent is not None else None
    return w or widget.window()


def help_mark(card_id, parent, has_module=None):
    """The shared ? (§6.4): Finished's `helpmark` look as a focusable button with its tooltip, opening card `card_id` —
    or None when the card doesn't show here (`help_cards.available`: its module is missing)."""
    if not help_cards.available(card_id, has_module):
        return None
    title = strings.HELP_CARDS[card_id][0]
    b = QToolButton(parent)
    b.setObjectName("helpmark")
    b.setText(strings.HELP_MARK)
    b.setToolTip(strings.HELP_MARK_TIP.format(title=title))
    b.setAccessibleName(strings.HELP_MARK_NAME.format(title=title))
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setProperty("help_card", card_id)
    b.clicked.connect(lambda _c=False: open_card(b, card_id))
    return b
