"""The phase strip (Sonic, 2026-10-23, build 6; `work/phase-strip/BUILD.md`): five circles at the bar's bottom left —
届 · ス · Anki Miner's 鉱 logo · 順 · Anki's star — each lit by the work it stands for (`app/services/phase.py`).

- **The logos are never changed** (LOGOS.md): each is drawn as it is, scaled evenly (`app/qt/logos.py`; Anki Miner's
  on its 1 px tile). The state is shown only **around** the mark, on its ring: dim at rest · the accent arc turning
  while it runs (`motion.spin_arc`, the press's one look; still under Reduced motion) · a still, fainter arc while it
  waits · a done tick — the ring in `ok`, held `press.LINGER_S` (2 s) then faded back (`MOTION["phase-fade"]`, the
  one clock) · failed red until hovered or the next run · needs-you amber — only with a decision waiting, and a
  press then opens where it is, highlighted (a7, below). Several can be lit at once.
- **The hover** (the bubble, `tooltip.py`, rich text; alpha 3, Sonic 2026-10-24: short and plain): the circle's name
  and what it does on one line; what it is doing now — one line per job under way (`status.job_line`), else its own
  standing line (Anki Miner: Connect's, 順: the re-order host's — the old ⇄ and ⇅ marks), else, lit by a press with no
  job yet, the press's words or *Starting…*, else *Nothing running now*; then the last that ended, named (*Last:
  Generating — done 14:02* / why it failed); then what a press does. Jobs are named in plain words (`strings.
  PHASE_JOB_NAMES`, by kind or label: *Indexing* is *Reading your files*). A failure or an ended wait on you counts as
  looked at once its bubble has really shown and the hover leaves it (`Tooltips.shown`: never on a pass by the keyboard
  or the pointer quicker than the bubble). Its words move in place while it shows.
- **Amber means a decision, and a press goes to it** (a7, Sonic 2026-10-29: "If yellow i would expect it to let me go
  somewhere to make a decision that is highlighted. If no decision it shouldn't be yellow but something else."): a
  circle is amber only while a wait on you names where it is decided (`phase.Go`, the circle's `go`), and its press
  opens that place with the row highlighted (`go(circle)`: the shell's `_circle_pressed`) — *Needs you* at the card
  (Anki Miner's episodes waiting on you, Anki asking for you, a gone folder) or 順's window at its control (the
  re-order host's `replan_preview.InJunban`: a deck to pick, an unfinished reorder to undo). What decides nothing is
  never amber: 順's other lines (Anki closed, a Generate to press, Only i+1 or Coverage) are words in its hover, a
  `replan_preview.Fails` is red; Anki closed is a plain wait (Connect's `anki_wait` slot); an offline folder is words
  in 届's hover. Its hover's last line says what to decide and where (`press_words`).
- **届 amber while a source folder is gone** (T6, Sonic 2026-10-24): the shell's own part (`set_extra`, with its
  `Go`), for as long as its *Needs you* card stands (*Keep waiting* takes both away).
- **A press opens the circle's settings** (alpha 3, Sonic: "I'd actually prefer if pressing it opened up their
  settings"; PROVISIONAL, he feels it in alpha 3 — it replaces build 6's "no buttons"): `opened(circle)`, the shell
  reveals `SETTINGS[circle]` (the Settings tab is there at once: no pending mark, the press rule's one-frame case). Only
  the circles in `opens` take a press and show the hand; one with no settings does nothing. A double-click or a held
  key opens once. The keyboard: one Tab stop, ← → between the circles that open, Enter or Space opens, an accent wash
  inside the one in focus (PROVISIONAL, the lead 2026-10-24), its hover shown when Tab brought it there.
- **S19:** the strip repaints only the circle whose look changed (`paints` counts them); the arc's clock (`motion.Turn`)
  runs only while one turns and stops the moment none does; one single-shot timer wakes it for the next automatic
  job to show (Q6's 1 s) or a tick's end — never a frame's pace.
- **Fed by** the registry's raw snapshot (`set_jobs`, `bridge.jobs_changed`), the status snapshot (`set_status`:
  *Needs you*'s entries by source), the window's presses (`follow_presses`) and the window's own (`set_extra`: the
  offline and gone folders, moves waiting on a busy store). The status snapshot's `replan` and `connect` lines are 順's and
  Anki Miner's standing lines (`set_status`; their words moved in place, no circle repainted: S19).
"""
import html
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app import theme
from app.qt import logos, motion, strings, style
from app import replan_preview
from app.services import phase
from app.services import press as press_service

LOGOS = {phase.MINER: "anki_miner", phase.ANKI: "anki_outline"}   # the circles that show a logo (`logos.CLEARED`'s
#   names): Anki's outline star, Sonic's pick (2026-10-23; the alternative licence's reach to an app is confirmed
#   before any public release, else the classic icon, "anki", goes back in — LOGOS.md)
RING_W = 1.5                    # px: the ring at rest, amber, red, the done tick
ARC_W = 2.0                     # px: the accent arc over it
WAIT_STRENGTH = 0.55            # a waiting circle's still arc: the accent at this strength
FOCUS_WASH = 0.30               # the circle in the keyboard's focus: an accent wash inside its ring, this strong
# What a press opens (`SettingsPage.reveal`'s targets: a section id or a row id): 届 the library folders (Sources),
# ス Generate's level, Anki Miner the cards Connect makes, 順 Junban's section, Anki the known-words sync
SETTINGS = {phase.ARRIVALS: "library_folders", phase.SURASURA: "level", phase.MINER: "connect_enabled",
            phase.JUNBAN: "junban", phase.ANKI: "known"}
STANDING = {phase.JUNBAN: "replan", phase.MINER: "connect"}   # a circle -> its standing line's snapshot field


def _named(view):
    """`view` with its plain name for the hover (`strings.PHASE_JOB_NAMES`, by kind, else by label), or as it is."""
    name = strings.PHASE_JOB_NAMES.get(view.kind) or strings.PHASE_JOB_NAMES.get(view.label)
    return view._replace(label=name) if name and name != view.label else view


def _junban_part(line):
    """順's line as its circle's own part (a7): a decision in 順's window (`InJunban`) amber, with where — the Undo for
    the unfinished reorder, else the deck list; a fault (`Fails`) red."""
    if isinstance(line, replan_preview.Fails):
        return ("failed", str(line))
    return ("needs", str(line), phase.Go("junban", "restore" if line == replan_preview.RESTORE_FIRST else "deck"))


def _mix(a, b, t):
    """`a` toward `b` by `t` (0..1), alpha too."""
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


class PhaseStrip(QWidget):
    opened = pyqtSignal(str)                   # a circle pressed (or Enter / Space on it): its settings, please

    def __init__(self, parent=None, now=None):
        super().__init__(parent)
        self.setObjectName("phasestrip")
        self.setAccessibleName(strings.PHASE_STRIP_NAME)
        self.setMouseTracking(True)            # a hover's bubble goes as the pointer leaves its circle
        self.now = now or time.time            # the wall clock (the jobs' times are its); a test's stand-in
        self.tooltips = None                   # the window's bubble (`tooltip.Tooltips`)
        self.linger_s = press_service.LINGER_S
        self.states = {c: phase.IDLE for c in phase.CIRCLES}
        self.paints = {c: 0 for c in phase.CIRCLES}
        self._views = ()
        self._entries = ()
        self._extra = {}                       # circle -> {key: (state, words)}
        self._presses = None
        self._last = {}                        # `phase.fold`'s: the newest ended run of each circle
        self._seen = set()                     # the failures and ended waits on you looked at (or run past)
        self._looking = (None, ())             # (the circle hovered, what leaving it marks seen)
        self._lit = dict.fromkeys(phase.CIRCLES, False)
        self._lit_since = dict.fromkeys(phase.CIRCLES, 0.0)     # when each last went lit: a tick is for a run ended since
        self._shown = ()                       # the presses read last (live, or failed: a circle's failure)
        self._ticks = {}                       # circle -> [done id, strength 0..1, when its hold ends or None]
        self._fades = {}                       # circle -> its fade (an Animation on the clock)
        self._looks = {}                       # circle -> what it was last painted as
        self._pix = {}                         # circle -> its logo (QPixmap), once decoded
        self.logos = dict(LOGOS)               # ... and which (this strip's: made from `LOGOS` as it is now)
        self.opens = frozenset()               # the circles a press opens the settings of (`set_opens`)
        self._standing = {}                    # circle -> its standing line (`STANDING`), from the status snapshot
        self._pressed = None                   # the circle a mouse press went down on
        self._focus = None                     # the circle the keyboard is on
        self._hand = False                     # the pointer shows the hand (over a circle that opens)
        self._asks = None                      # 順's line when it is a part of its own (a decision or a fault), or None
        self.lands = None                      # Go -> whether its place holds the decision now (the shell's, a7)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self._turn = motion.Turn(self, self._turned)
        self._looks = {c: self.look(c) for c in phase.CIRCLES}
        side = theme.size("phase-circle")
        self.setFixedSize(round(len(phase.CIRCLES) * side + (len(phase.CIRCLES) - 1) * theme.size("phase-gap")),
                          round(side))

    # --- what comes in ---------------------------------------------------------------------------------------- #
    def set_jobs(self, views):
        self._views = tuple(views or ())
        self.refresh()

    def set_status(self, snap):
        standing = {c: getattr(snap, field, None) or "" for c, field in STANDING.items()}
        asks = standing.get(phase.JUNBAN)
        asks = asks if isinstance(asks, (replan_preview.InJunban, replan_preview.Fails)) and asks else None
        standing = {c: line for c, line in standing.items() if line and not (c == phase.JUNBAN and asks)}
        parts = self._extra.get(phase.JUNBAN, {})
        if (parts.get("asks") or (None, None))[1] != asks or type(self._asks) is not type(asks):
            self._asks = asks
            parts = self._extra.setdefault(phase.JUNBAN, {})
            if asks:
                parts["asks"] = _junban_part(asks)
                self._seen.discard(("extra", phase.JUNBAN, "asks", str(asks)))   # said again: news again
            else:
                parts.pop("asks", None)
            self._entries = tuple(getattr(snap, "needs_you", None) or ())
            self._standing = standing
            self.refresh()                     # 順's look moves: amber on, or off
            return
        entries = tuple(getattr(snap, "needs_you", None) or ())
        if entries != self._entries:
            self._entries = entries
            self._standing = standing
            self.refresh()
        elif standing != self._standing:       # words only: no circle's look moves (S19), the hover says them
            self._standing = standing
            self._retext()
            self.setAccessibleDescription(self.summary())

    def go(self, circle):
        """Where `circle`'s decision is (`phase.Go`) while it is amber, else None: its press opens that place, the row
        highlighted, instead of its settings (a7)."""
        st = self.states[circle]
        return st.go if st.needs else None

    def press_words(self, circle):
        """What a press on `circle` does, as its hover's last line says it: while it is amber, what to decide and where."""
        go = self.go(circle)
        if go is None:
            return strings.PHASE_PRESS
        if go.place == "junban":
            return strings.PHASE_PRESS_RESTORE if go.at == "restore" else strings.PHASE_PRESS_DECK
        return strings.PHASE_PRESS_NEEDS

    def set_opens(self, circles):
        """The circles whose press opens their settings (the shell's: those with settings to show)."""
        self.opens = frozenset(c for c in circles if c in SETTINGS)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if self.opens else Qt.FocusPolicy.NoFocus)
        if self._pressed not in self.opens:
            self._pressed = None
        if self._focus is not None and self._focus not in self.opens:
            dropped, self._focus = self._focus, None
            self.update(self.rect_of(dropped).toAlignedRect().adjusted(-1, -1, 1, 1))     # its wash goes; nothing else
        self._set_hand(self._pressable(self._under_mouse()))
        self._retext()

    def follow_presses(self, presses):
        """The window's presses (`services.press.Presses`): a live one lights its circle before any job exists."""
        self._presses = presses
        presses.subscribe(lambda _p: self.refresh())
        self.refresh()

    def set_extra(self, circle, key, state=None, words=None, go=None):
        """The window's own part of `circle` (`state` "waiting" · "running" · "info" · "failed" · "needs" — amber only
        with `go`, where it is decided: `phase.Go`, a7 — with its words), or none."""
        parts = self._extra.setdefault(circle, {})
        part = (state, words) if go is None else (state, words, go)
        if state is None:
            if parts.pop(key, None) is None:
                return
        elif parts.get(key) == part:
            return
        else:
            parts[key] = part
        self.refresh()

    # --- reading -------------------------------------------------------------------------------------------- #
    def refresh(self):
        """Read the state of every circle now and repaint the ones whose look changed."""
        if sip.isdeleted(self):
            return
        now = self.now()
        self._views = tuple(_named(v) for v in self._views)
        self._last = phase.fold(self._last, self._views)
        presses = self._shown = self._presses.showing() if self._presses is not None else ()
        for p in presses:
            if p.live():
                self._seen.discard(("press", p.key))           # pressed again: its next failure is news
        extra = {c: [("info", p[1]) if p[0] == "failed" and ("extra", c, key, p[1]) in self._seen else p
                     for key, p in parts.items()]          # (a fault looked at: still said, no longer red)
                 for c, parts in self._extra.items() if parts}
        got = phase.read(self._views, presses, self._entries, extra, self._last, self._seen, now)
        got = {c: self._landed(st) for c, st in got.items()}
        for c in phase.CIRCLES:
            st = got[c]
            lit = st.running or st.waiting
            if lit and not self._lit[c]:
                self._seen.update(self._marks(c, st))          # the next run: what failed before is over (Q3)
                self._untick(c)
                self._lit_since[c] = now
            elif (not lit and self._lit[c] and st.done is not None and st.done != self._ticks.get(c, (None,))[0]
                  and self._last[c].ended_at >= self._lit_since[c]):
                # (PS-A1: a press that ended with no job of its own ticks nothing — its circle's older run isn't news)
                self._ticks[c] = [st.done, 1.0, now + self.linger_s]
            self._lit[c] = lit
        self.states = got
        self._end_holds(now)
        self._turn.set_running(any(s.running for s in got.values()))
        self._paint_changed()
        self._wake(now)
        self._retext()

    def _landed(self, st):
        """a7: amber only while its place holds the decision — a *Needs you* card put away
        (*Not now*, *Stop asking*) or not gathered yet leaves nothing to land on: a plain wait, its words in the hover."""
        if not st.needs or st.go is None or self.lands is None or self.lands(st.go):
            return st
        return st._replace(needs=None, go=None, waiting=not st.running)

    def _marks(self, circle, st):
        """What looking at `circle` (or running it again) marks seen: its ended failure or wait on you, its *Needs
        you* entries and its presses that failed."""
        out = []
        end = self._last.get(circle)
        if end is not None:
            out.append(end.id)
        out += [("entry", e.text, e.at) for e in self._entries if phase.SOURCES.get(getattr(e, "source", None)) == circle]
        out += [("press", p.key) for p in self._shown if not p.live() and phase.press_circle(p.key) == circle]
        out += [("extra", circle, key, p[1]) for key, p in self._extra.get(circle, {}).items() if p[0] == "failed"]
        return out

    def _wake(self, now):
        """The one timer, for the next automatic job to show or a tick's hold to end."""
        due = [t[2] for t in self._ticks.values() if t[2] is not None]
        reveal = phase.reveal_at(self._views, now)
        if reveal is not None:
            due.append(reveal)
        if not due:
            self._timer.stop()
            return
        self._timer.start(max(1, round((min(due) - now) * 1000) + 1))

    # --- the done tick ---------------------------------------------------------------------------------------- #
    def _end_holds(self, now):
        for c, tick in list(self._ticks.items()):
            if tick[2] is not None and now >= tick[2]:
                tick[2] = None
                self._fade(c)

    def _fade(self, circle):
        self._fades[circle] = motion.clock().animate(theme.MOTION["phase-fade"],
                                                     lambda v, c=circle: self._fading(c, v),
                                                     on_done=lambda c=circle: self._untick(c), kind="fade", owner=self)

    def _fading(self, circle, v):
        tick = self._ticks.get(circle)
        if tick is not None:
            tick[1] = 1.0 - v
            self._paint_changed((circle,))

    def _untick(self, circle):
        anim = self._fades.pop(circle, None)
        if anim is not None and anim.alive:
            anim.stop()
        if self._ticks.pop(circle, None) is not None and not sip.isdeleted(self):
            self._paint_changed((circle,))

    # --- painting -------------------------------------------------------------------------------------------- #
    def rect_of(self, circle):
        side, gap = theme.size("phase-circle"), theme.size("phase-gap")
        i = phase.CIRCLES.index(circle)
        return QRectF(i * (side + gap), (self.height() - side) / 2.0, side, side)

    def circle_at(self, pos):
        for c in phase.CIRCLES:
            if self.rect_of(c).contains(float(pos.x()), float(pos.y())):
                return c
        return None

    def look(self, circle):
        """What `circle` is painted as now (S19: a circle repaints only when this changed)."""
        st = self.states[circle]
        tick = self._ticks.get(circle)
        return (st.running, st.waiting, bool(st.needs), bool(st.failed), round(tick[1], 3) if tick else None,
                st.running or st.waiting or bool(st.needs) or bool(st.failed))

    def _paint_changed(self, circles=phase.CIRCLES):
        for c in circles:
            now = self.look(c)
            if self._looks.get(c) != now:
                self._looks[c] = now
                self.update(self.rect_of(c).toAlignedRect().adjusted(-1, -1, 1, 1))
        self.setAccessibleDescription(self.summary())

    def _turned(self):
        for c in phase.CIRCLES:
            if self.states[c].running:
                self.update(self.rect_of(c).toAlignedRect().adjusted(-1, -1, 1, 1))

    def showEvent(self, event):
        super().showEvent(event)
        self._load_logos()

    def _load_logos(self):
        dpr = self.devicePixelRatioF()
        px = theme.size("phase-mark")
        for circle, name in self.logos.items():
            have = self._pix.get(circle)
            if have is not None and have.devicePixelRatio() == dpr:
                continue

            def got(pix, c=circle):
                if sip.isdeleted(self):
                    return
                self._pix[c] = pix
                self.update(self.rect_of(c).toAlignedRect())
            logos.logo(name, px, got, dpr=dpr)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        c = style.colours()
        area = event.region()                  # (its bounding rect would hold every circle between two dirty ones: PS-A6)
        for circle in phase.CIRCLES:
            r = self.rect_of(circle)
            if area.intersects(r.toAlignedRect()):
                self.paints[circle] += 1
                self._paint_circle(p, circle, r, c)
        p.end()

    def _paint_circle(self, p, circle, r, c):
        st = self.states[circle]
        ring = r.adjusted(ARC_W, ARC_W, -ARC_W, -ARC_W)
        track = style.qcolor(c["line-hi"])
        colour = track
        if st.needs:
            colour = style.qcolor(c["warn"])
        elif st.failed:
            colour = style.qcolor(c["bad"])
        else:
            tick = self._ticks.get(circle)
            if tick is not None:
                colour = _mix(track, style.qcolor(c["ok"]), tick[1])
        p.setPen(QPen(colour, RING_W))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        accent = style.qcolor(c["accent"])
        if st.running:
            motion.spin_arc(p, r, self._turn.turning, accent, width=ARC_W)       # (on the ring: inset by its pen)
        elif st.waiting:
            accent.setAlphaF(WAIT_STRENGTH)
            motion.spin_arc(p, r, None, accent, width=ARC_W)
        if circle == self._focus and self.hasFocus():   # the keyboard's: an accent wash inside the ring (the ring and
            wash = style.qcolor(c["accent"])            # its arc keep saying the state; no room outside the circle)
            wash.setAlphaF(FOCUS_WASH)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(wash)
            p.drawEllipse(ring.adjusted(RING_W, RING_W, -RING_W, -RING_W))
            p.setBrush(Qt.BrushStyle.NoBrush)
        mark = theme.size("phase-mark")
        box = QRectF(r.center().x() - mark / 2.0, r.center().y() - mark / 2.0, mark, mark)
        if circle in self.logos:
            pix = self._pix.get(circle)
            if pix is not None:
                w, h = pix.width() / pix.devicePixelRatio(), pix.height() / pix.devicePixelRatio()
                p.drawPixmap(QRectF(r.center().x() - w / 2.0, r.center().y() - h / 2.0, w, h), pix,
                             QRectF(pix.rect()))
            return
        font = QFont()
        font.setFamilies(theme.font_families("ja"))
        font.setPixelSize(max(1, round(mark)))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        lit = self.look(circle)[-1] or self._ticks.get(circle) is not None
        p.setPen(style.qcolor(c["ink"] if lit else c["ink-dim"]))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, strings.PHASE_MARKS[circle])

    # --- the hover ------------------------------------------------------------------------------------------- #
    def hover_text(self, circle):
        """The circle's hover (rich text; alpha 3): its name and what it does, what it is doing now (a line per job
        under way, else its standing line, else *Nothing running now*), the last that ended, named, and — on a circle
        that opens — what a click does. A provider's words are never markup (AD-14)."""
        st = self.states[circle]
        esc = html.escape
        dim = style.colours()["ink-dim"]
        out = [f'<b>{esc(strings.PHASE_NAMES[circle])}</b> '
               f'<span style="color:{dim}">· {esc(strings.PHASE_ABOUT[circle])}</span>']
        now = list(st.lines)
        if not now and (st.running or st.waiting):      # lit by a press with no job yet (A3A-1): its words
            said = [p.words for p in self._shown if p.live() and phase.press_circle(p.key) == circle and p.words]
            now = said[:1] or [strings.PHASE_STARTING]
        elif not now and circle in self._standing:
            now = [self._standing[circle]]
        out += [esc(line) for line in now]
        last = st.last
        if st.failed and (last is None or last.state != "failed" or last.id in self._seen):
            out.append(esc(strings.PHASE_FAILED_NOW.format(why=st.failed)))
        if not now and not st.failed and not st.needs:
            out.append(esc(strings.PHASE_IDLE))
        if last is not None:
            at = time.strftime(strings.PHASE_TIME, time.localtime(last.at)) if last.at else ""
            what = getattr(self._last.get(circle), "label", None) or strings.PHASE_NAMES[circle]   # the job's name
            if last.state == "failed":
                out.append(esc(strings.PHASE_FAILED.format(what=what, time=at, why=last.words or "")))
            elif last.state == "needs" and st.needs:
                out.append(esc(strings.PHASE_NEEDS.format(why=last.words)))
            elif last.state == "needs":                 # (a7: it named no place to decide — no *Needs you*)
                out.append(esc(strings.PHASE_ENDED_WAITING.format(what=what, time=at, why=last.words)))
            elif last.state == "stopped":
                out.append(esc(strings.PHASE_STOPPED.format(what=what, time=at)))
            else:
                out.append(esc(strings.PHASE_DONE.format(what=what, time=at)))
        if circle in self.opens or self.go(circle) is not None:
            press = self.press_words(circle)
            out.append(f'<span style="color:{dim}">{esc(press)}</span>')
        return '<p style="margin:0">' + "<br>".join(out) + "</p>"

    def summary(self):
        """The strip read out (its accessible description): the circle in the keyboard's focus and what a press does,
        then each lit circle's name and first line."""
        said = []
        if self._focus is not None and self.hasFocus():
            press = self.press_words(self._focus)
            said.append(f"{strings.PHASE_NAMES[self._focus]}: {press}")
        for c in phase.CIRCLES:
            st = self.states[c]
            if st.running or st.waiting or st.needs or st.failed:
                first = st.needs or st.failed or (st.lines[0] if st.lines else "")
                said.append(f"{strings.PHASE_NAMES[c]}: {first}" if first else strings.PHASE_NAMES[c])
            elif c in self._standing:                    # (IKA3-9: 順's and Anki Miner's words with no job too)
                said.append(f"{strings.PHASE_NAMES[c]}: {self._standing[c]}")
        return "; ".join(said) or strings.PHASE_IDLE

    # --- the press: a circle's settings (alpha 3) --------------------------------------------------------------- #
    def _pressable(self, circle):
        return circle is not None and (circle in self.opens or self.go(circle) is not None)

    def _under_mouse(self):
        return self.circle_at(self.mapFromGlobal(QCursor.pos())) if self.underMouse() else None

    def _set_hand(self, on):
        """The hand over a circle that opens, the arrow elsewhere — set only when it changes."""
        if on == self._hand:
            return
        self._hand = on
        if on:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def mouseMoveEvent(self, e):
        self._set_hand(self._pressable(self.circle_at(e.position().toPoint())))
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        circle = self.circle_at(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and self._pressable(circle):
            self._pressed = circle
            e.accept()
            return
        self._pressed = None
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        pressed, self._pressed = self._pressed, None
        if (e.button() == Qt.MouseButton.LeftButton and pressed is not None
                and self.circle_at(e.position().toPoint()) == pressed):
            e.accept()
            self._open(pressed)
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self._pressable(self.circle_at(e.position().toPoint())):
            e.accept()                         # the first click opened it: a double-click opens once (A3A-4)
            return
        super().mouseDoubleClickEvent(e)

    def _open(self, circle):
        if self.tooltips is not None:
            self.tooltips.hide()
        self.opened.emit(circle)

    def keyPressEvent(self, e):
        key = e.key()
        order = [c for c in phase.CIRCLES if self._pressable(c)]
        if not order or self._focus not in order:
            super().keyPressEvent(e)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not e.isAutoRepeat():           # a held key opens once (A3A-5)
                self._open(self._focus)
            e.accept()
            return
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(key)
        if step is None:
            super().keyPressEvent(e)
            return
        self._focus_on(order[max(0, min(len(order) - 1, order.index(self._focus) + step))])

    def focusInEvent(self, e):
        super().focusInEvent(e)
        order = [c for c in phase.CIRCLES if self._pressable(c)]
        if order:
            backwards = e.reason() == Qt.FocusReason.BacktabFocusReason
            asked = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                   Qt.FocusReason.ShortcutFocusReason)
            self._focus_on(self._focus if self._focus in order else order[-1 if backwards else 0], hover=asked)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self._focus is not None:
            self.update(self.rect_of(self._focus).toAlignedRect().adjusted(-1, -1, 1, 1))
            self._leave_hover(None)
        self.setAccessibleDescription(self.summary())

    def _focus_on(self, circle, hover=True):
        """The keyboard on `circle`: its wash, its hover (as a pointer's; not when the window's activation brought the
        focus back), its name read out."""
        was, self._focus = self._focus, circle
        for c in {was, circle} - {None}:
            self.update(self.rect_of(c).toAlignedRect().adjusted(-1, -1, 1, 1))
        if hover:
            self._hover(circle)
        self.setAccessibleDescription(self.summary())

    def event(self, e):
        et = e.type()
        if et == QEvent.Type.ToolTip:
            self._hover(self.circle_at(e.pos()))
            return True
        if et == QEvent.Type.Leave:
            self._set_hand(False)
            self._pressed = None
            self._leave_hover(self._focus if self.hasFocus() else None)   # (the keyboard's circle stays looked at)
        elif et == QEvent.Type.DevicePixelRatioChange:
            self._load_logos()                 # another screen's scale: decoded again at its ratio (PS-A8)
        elif et == QEvent.Type.MouseMove and self.tooltips is not None:
            self.tooltips.hide_part_unless(self, e.position().toPoint())
        return super().event(e)

    def _hover(self, circle):
        """`circle`'s hover shown (the pointer resting on it, or the keyboard on it); None: none."""
        self._leave_hover(circle)
        if circle is None:
            if self.tooltips is not None:
                self.tooltips.hide()
            return
        if self._looking[0] != circle:
            self._looking = (circle, tuple(self._marks(circle, self.states[circle])))
        if self.tooltips is not None:
            self.tooltips.request(self, self.rect_of(circle).toAlignedRect(), self.hover_text(circle))

    def _leave_hover(self, circle):
        """The hover left a circle (for another, or the strip): its failure, or its ended wait on you, looked at."""
        was, marks = self._looking
        if was is None or was == circle:
            return
        self._looking = (None, ())
        tips = self.tooltips
        if tips is None or getattr(tips, "shown", None) != (self, self.rect_of(was).toAlignedRect()):
            return                             # its bubble never showed: nothing was looked at (IKA3-5)
        if marks and not set(marks) <= self._seen:
            self._seen.update(marks)
            self.refresh()

    def _retext(self):
        circle = self._looking[0]
        if circle is not None and self.tooltips is not None:
            self.tooltips.retext(self, self.rect_of(circle).toAlignedRect(), self.hover_text(circle))
