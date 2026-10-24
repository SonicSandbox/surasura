"""The phase strip (Sonic, 2026-10-23, build 6; `work/phase-strip/BUILD.md`): five circles at the bar's bottom left —
届 · ス · Anki Miner's 鉱 logo · 順 · Anki's star — each lit by the work it stands for (`app/services/phase.py`).

- **The logos are never changed** (LOGOS.md): each is drawn as it is, scaled evenly (`app/qt/logos.py`; Anki Miner's
  on its 1 px tile). The state is shown only **around** the mark, on its ring: dim at rest · the accent arc turning
  while it runs (`motion.spin_arc`, the press's one look; still under Reduced motion) · a still, fainter arc while it
  waits · a done tick — the ring in `ok`, held `press.LINGER_S` (2 s) then faded back (`MOTION["phase-fade"]`, the
  one clock) · failed red until hovered or the next run · needs-you amber. Several can be lit at once.
- **The hover** (the bubble, `tooltip.py`, rich text): the circle's name and what it covers, one line per job under
  way (`status.job_line`), then the last that ended (*Done 14:02* / why it failed). No buttons. A failure or an ended
  wait on you counts as looked at once the hover leaves it. Its words move in place while it shows.
- **S19:** the strip repaints only the circle whose look changed (`paints` counts them); the arc's clock (`motion.Turn`)
  runs only while one turns and stops the moment none does; one single-shot timer wakes it for the next automatic
  job to show (Q6's 1 s) or a tick's end — never a frame's pace.
- **Fed by** the registry's raw snapshot (`set_jobs`, `bridge.jobs_changed`), the status snapshot (`set_status`:
  *Needs you*'s entries by source), the window's presses (`follow_presses`) and the window's own (`set_extra`: the
  offline folders, moves waiting on a busy store). The re-order's and Connect's lines keep their quiet marks at the
  bar's right (PROVISIONAL: the strip fits beside them at the narrowest window, so they stay where they are).
"""
import html
import time

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app import theme
from app.qt import logos, motion, strings, style
from app.services import phase
from app.services import press as press_service

LOGOS = {phase.MINER: "anki_miner", phase.ANKI: "anki_outline"}   # the circles that show a logo (`logos.CLEARED`'s
#   names): Anki's outline star, Sonic's pick (2026-10-23; the alternative licence's reach to an app is confirmed
#   before any public release, else the classic icon, "anki", goes back in — LOGOS.md)
RING_W = 1.5                    # px: the ring at rest, amber, red, the done tick
ARC_W = 2.0                     # px: the accent arc over it
WAIT_STRENGTH = 0.55            # a waiting circle's still arc: the accent at this strength


def _mix(a, b, t):
    """`a` toward `b` by `t` (0..1), alpha too."""
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


class PhaseStrip(QWidget):
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
        self._ticks = {}                       # circle -> [done id, strength 0..1, when its hold ends or None]
        self._fades = {}                       # circle -> its fade (an Animation on the clock)
        self._looks = {}                       # circle -> what it was last painted as
        self._pix = {}                         # circle -> its logo (QPixmap), once decoded
        self.logos = dict(LOGOS)               # ... and which (this strip's: made from `LOGOS` as it is now)
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
        entries = tuple(getattr(snap, "needs_you", None) or ())
        if entries != self._entries:
            self._entries = entries
            self.refresh()

    def follow_presses(self, presses):
        """The window's presses (`services.press.Presses`): a live one lights its circle before any job exists."""
        self._presses = presses
        presses.subscribe(lambda _p: self.refresh())
        self.refresh()

    def set_extra(self, circle, key, state=None, words=None):
        """The window's own part of `circle` (`state` "waiting" · "running" · "needs", with its words), or none."""
        parts = self._extra.setdefault(circle, {})
        if state is None:
            if parts.pop(key, None) is None:
                return
        elif parts.get(key) == (state, words):
            return
        else:
            parts[key] = (state, words)
        self.refresh()

    # --- reading -------------------------------------------------------------------------------------------- #
    def refresh(self):
        """Read the state of every circle now and repaint the ones whose look changed."""
        if sip.isdeleted(self):
            return
        now = self.now()
        self._last = phase.fold(self._last, self._views)
        presses = self._presses.live_ones() if self._presses is not None else ()
        extra = {c: list(parts.values()) for c, parts in self._extra.items() if parts}
        got = phase.read(self._views, presses, self._entries, extra, self._last, self._seen, now)
        for c in phase.CIRCLES:
            st = got[c]
            lit = st.running or st.waiting
            if lit and not self._lit[c]:
                self._seen.update(self._marks(c, st))          # the next run: what failed before is over (Q3)
                self._untick(c)
            elif not lit and self._lit[c] and st.done is not None and st.done != self._ticks.get(c, (None,))[0]:
                self._ticks[c] = [st.done, 1.0, now + self.linger_s]
            self._lit[c] = lit
        self.states = got
        self._end_holds(now)
        self._turn.set_running(any(s.running for s in got.values()))
        self._paint_changed()
        self._wake(now)
        self._retext()

    def _marks(self, circle, st):
        """What looking at `circle` (or running it again) marks seen: its ended failure or wait on you, and its
        *Needs you* entries."""
        out = []
        end = self._last.get(circle)
        if end is not None:
            out.append(end.id)
        out += [("entry", e.text, e.at) for e in self._entries if phase.SOURCES.get(getattr(e, "source", None)) == circle]
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
        area = QRectF(event.rect())
        for circle in phase.CIRCLES:
            r = self.rect_of(circle)
            if r.intersects(area):
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
        """The circle's hover (rich text): its name and what it covers, a line per job under way, then the last one
        that ended."""
        st = self.states[circle]
        esc = html.escape
        dim = style.colours()["ink-dim"]
        out = [f"<b>{esc(strings.PHASE_NAMES[circle])}</b>",
               f'<span style="color:{dim}">{esc(strings.PHASE_ABOUT[circle])}</span>']
        out += [esc(line) for line in st.lines]
        last = st.last
        if st.failed and (last is None or last.state != "failed" or last.id in self._seen):
            out.append(esc(strings.PHASE_FAILED_NOW.format(why=st.failed)))
        if last is not None:
            at = time.strftime(strings.PHASE_TIME, time.localtime(last.at)) if last.at else ""
            if last.state == "failed":
                out.append(esc(strings.PHASE_FAILED.format(time=at, why=last.words or "")))
            elif last.state == "needs":
                out.append(esc(strings.PHASE_NEEDS.format(why=last.words)))
            elif last.state == "stopped":
                out.append(esc(strings.PHASE_STOPPED.format(time=at)))
            else:
                out.append(esc(strings.PHASE_DONE.format(time=at)))
        elif not st.lines:
            out.append(esc(strings.PHASE_IDLE))
        return '<p style="margin:0">' + "<br>".join(out) + "</p>"

    def summary(self):
        """The strip read out (its accessible description): each lit circle's name and first line."""
        said = []
        for c in phase.CIRCLES:
            st = self.states[c]
            if st.running or st.waiting or st.needs or st.failed:
                first = st.needs or st.failed or (st.lines[0] if st.lines else "")
                said.append(f"{strings.PHASE_NAMES[c]}: {first}" if first else strings.PHASE_NAMES[c])
        return "; ".join(said) or strings.PHASE_IDLE

    def event(self, e):
        et = e.type()
        if et == QEvent.Type.ToolTip:
            circle = self.circle_at(e.pos())
            self._leave_hover(circle)
            if circle is None:
                if self.tooltips is not None:
                    self.tooltips.hide()
                return True
            if self._looking[0] != circle:
                self._looking = (circle, tuple(self._marks(circle, self.states[circle])))
            if self.tooltips is not None:
                self.tooltips.request(self, self.rect_of(circle).toAlignedRect(), self.hover_text(circle))
            return True
        if et == QEvent.Type.Leave:
            self._leave_hover(None)
        elif et == QEvent.Type.MouseMove and self.tooltips is not None:
            self.tooltips.hide_part_unless(self, e.position().toPoint())
        return super().event(e)

    def _leave_hover(self, circle):
        """The hover left a circle (for another, or the strip): its failure, or its ended wait on you, looked at."""
        was, marks = self._looking
        if was is None or was == circle:
            return
        self._looking = (None, ())
        if marks and not set(marks) <= self._seen:
            self._seen.update(marks)
            self.refresh()

    def _retext(self):
        circle = self._looking[0]
        if circle is not None and self.tooltips is not None:
            self.tooltips.retext(self, self.rect_of(circle).toAlignedRect(), self.hover_text(circle))
