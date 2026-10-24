"""The phase strip (Sonic, 2026-10-23; `app/qt/phase_strip.py`): five circles at the bar's bottom left, lit by the work
each stands for — the state painted around the mark, never on it.

What a wrong answer would cost a learner:
  * a circle that says nothing while its work runs, or keeps turning after it ended (and keeps the laptop awake);
  * a logo changed to show a state (Anki's and Anki Miner's terms: unmodified);
  * a failure gone before it was seen, or a hover that doesn't say what runs;
  * a strip that pushes the bar's other marks out at the narrowest window;
  * the same job said twice, on its circle and in the status line.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF
from PyQt6.QtGui import QColor, QHelpEvent, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from app import credits, theme
from app.qt import freeze, motion, phase_strip, strings, style
from app.services import jobs as J
from app.services import phase as P
from app.services.jobs import JobRegistry
from app.services.press import Presses
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import world  # noqa: F401  (`world`: the fixture)


class Wall:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@pytest.fixture
def strip(qapp):
    host = QWidget()
    host.resize(200, 39)
    s = phase_strip.PhaseStrip(host, now=Wall())
    s.move(10, (39 - s.height()) // 2)
    host.show()
    QApplication.processEvents()
    yield s
    host.close()


@pytest.fixture
def clock(qapp):
    """The clock on test time, motion unfrozen and Full; put back afterwards."""
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    before = c.mode.setting
    c.mode.set_setting("full")
    yield c
    for a in c.active:
        a.stop()
    c.use_real_time()
    c.mode.set_setting(before)
    freeze.set_frozen(None)


def _image(s, dpr=1.0):
    img = QImage(round(s.width() * dpr), round(s.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(style.qcolor(theme.ROOM["frame"]))
    p = QPainter(img)
    s.render(p, QPoint(0, 0))
    p.end()
    return img


def _ring(s, circle, img, where="left", dpr=1.0):
    """The colour on `circle`'s ring at its left (the still arc covers it) or its top-right (the arc's gap)."""
    r = s.rect_of(circle)
    import math
    rad = r.width() / 2 - phase_strip.ARC_W
    angle = math.pi if where == "left" else math.pi / 4
    x = r.center().x() + rad * math.cos(angle)
    y = r.center().y() - rad * math.sin(angle)
    px, py = round(x * dpr - 0.5), round(y * dpr - 0.5)
    near = [img.pixelColor(px + dx, py + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    return max(near, key=lambda q: q.red() + q.green() + q.blue())     # the ring's core (the frame is darker)


def _near(a, b, tol=40):
    if isinstance(b, str):
        b = style.qcolor(b)
    return all(abs(x - y) <= tol for x, y in zip((a.red(), a.green(), a.blue()), (b.red(), b.green(), b.blue())))


C = style.colours


# --- painted states ----------------------------------------------------------------------------------------------- #
def test_at_rest_every_ring_is_dim_and_the_characters_and_logos_are_drawn(strip):
    assert wait_until(lambda: len(strip._pix) == 2)                     # Anki Miner's and Anki's logos, decoded
    strip.repaint()
    img = _image(strip)
    for c in P.CIRCLES:
        assert _near(_ring(strip, c, img), C()["line-hi"]), c
    assert strings.PHASE_MARKS == {"arrivals": "届", "surasura": "ス", "junban": "順"}
    assert strip.summary() == strings.PHASE_IDLE


def test_running_turns_the_accent_arc_around_the_mark_waiting_is_still_needs_amber_failed_red(strip):
    registry = JobRegistry()
    gen = registry.submit("generate", "Generating", lambda j: None)
    registry.submit("indexer", "Indexing", lambda j: None)
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None)
    registry.record("mine-wait", "Connect", automatic=True, reason="Not timed", needs="Not timed to its video")
    bad = registry.submit("junban", "Re-ordering Anki", lambda j: None)
    bad.finish(ok=False, message="Anki stopped answering")
    strip.set_jobs(registry.snapshot())
    strip.repaint()
    img = _image(strip)
    assert _near(_ring(strip, P.SURASURA, img), C()["accent"])          # the arc (still: the freeze switch)
    assert _near(_ring(strip, P.ANKI, img), C()["accent"])
    assert _near(_ring(strip, P.MINER, img), C()["warn"])                # amber: it waits on you
    assert _near(_ring(strip, P.JUNBAN, img), C()["bad"])                # red, kept
    assert _near(_ring(strip, P.ARRIVALS, img), C()["line-hi"])
    assert _near(_ring(strip, P.SURASURA, img, "top-right"), C()["line-hi"])   # the arc's gap shows the ring under it
    sync.finish()
    gen.finish()
    strip.set_jobs(registry.snapshot())
    strip.repaint()
    img = _image(strip)
    assert strip.states[P.SURASURA].running and strip.states[P.SURASURA].lines == ("Indexing",)   # the indexer's turn
    assert P.SURASURA not in strip._ticks                               # still lit: no tick between the two
    assert _near(_ring(strip, P.ANKI, img), C()["ok"])                   # done: the tick
    assert "Not timed to its video" in strip.summary() and "Anki stopped answering" in strip.summary()


def test_the_done_tick_holds_two_seconds_then_fades_back_on_the_clock_which_then_stops(strip, clock):
    registry = JobRegistry()
    job = registry.submit("backfill", "Filling your cards", lambda j: None)
    strip.set_jobs(registry.snapshot())
    assert strip._turn.on_clock                                         # one turns: the clock runs
    job.finish()
    strip.set_jobs(registry.snapshot())
    assert not strip._turn.on_clock                                     # none turns: off the clock at once (S19)
    assert strip._ticks[P.JUNBAN][1] == 1.0 and strip._timer.isActive()
    strip.now.now += strip.linger_s - 0.1
    strip.refresh()
    assert strip._ticks[P.JUNBAN][1] == 1.0 and not clock.active        # held: nothing on the clock
    strip.now.now += 0.2
    strip.refresh()                                                     # (the timer's look)
    assert clock.active                                                 # the fade
    clock.advance(theme.MOTION["phase-fade"] / 2)
    assert 0.0 < strip._ticks[P.JUNBAN][1] < 1.0
    clock.advance(theme.MOTION["phase-fade"])
    assert P.JUNBAN not in strip._ticks and not clock.active and not strip._timer.isActive()


def test_reduced_motion_shows_a_still_arc_and_nothing_on_the_clock(strip, clock):
    clock.mode.set_setting("reduced")
    registry = JobRegistry()
    registry.submit("generate", "Generating", lambda j: None)
    strip.set_jobs(registry.snapshot())
    assert strip.states[P.SURASURA].running and not strip._turn.on_clock and strip._turn.turning is None
    strip.repaint()
    assert _near(_ring(strip, P.SURASURA, _image(strip)), C()["accent"])


def test_only_the_circle_that_changed_repaints_and_a_step_moving_repaints_none(strip):
    registry = JobRegistry()
    strip.set_jobs(registry.snapshot())
    QApplication.processEvents()
    before = dict(strip.paints)
    job = registry.submit("youtube", "Downloading a transcript", lambda j: None)
    strip.set_jobs(registry.snapshot())
    assert wait_until(lambda: strip.paints[P.ARRIVALS] > before[P.ARRIVALS])     # its own rect, painted
    grown = {c: strip.paints[c] - before[c] for c in P.CIRCLES}
    assert all(grown[c] == 0 for c in P.CIRCLES if c != P.ARRIVALS), grown
    looks = dict(strip._looks)
    job.progress("Fetching", 1, 3)
    strip.set_jobs(registry.snapshot())
    assert strip._looks == looks                                        # its look didn't change: nothing asked


def test_a_change_asks_to_repaint_its_own_circle_alone(strip, monkeypatch):
    asked = []
    monkeypatch.setattr(strip, "update", lambda *a: asked.append(a[0] if a else None))
    registry = JobRegistry()
    registry.submit("junban", "Re-ordering Anki", lambda j: None)
    strip.set_jobs(registry.snapshot())
    assert asked == [strip.rect_of(P.JUNBAN).toAlignedRect().adjusted(-1, -1, 1, 1)]


def test_an_automatic_job_lights_only_after_a_second_and_one_shorter_leaves_no_tick(strip):
    registry = JobRegistry()
    job = registry.submit("indexer", "Indexing your library", lambda j: None, automatic=True)
    strip.now.now = job.started_at + 0.3
    strip.set_jobs(registry.snapshot())
    assert not strip.states[P.SURASURA].running and strip._timer.isActive()   # woken at its second
    strip.now.now = job.started_at + 1.0
    strip.refresh()
    assert strip.states[P.SURASURA].running
    quick = registry.submit("arrivals-ja", "Counting new arrivals", lambda j: None, automatic=True)
    strip.now.now = quick.started_at + 0.2
    strip.set_jobs(registry.snapshot())
    quick.finish()
    strip.set_jobs(registry.snapshot())
    assert P.ARRIVALS not in strip._ticks and not strip.states[P.ARRIVALS].running


# --- the hover ---------------------------------------------------------------------------------------------------- #
def test_the_hover_names_the_circle_each_job_under_way_and_the_last_that_ended(strip):
    registry = JobRegistry()
    old = registry.submit("generate", "Generating", lambda j: None)
    old.finish()
    gen = registry.submit("generate", "Generating", lambda j: None)
    gen.progress("Reading your files", 3, 12)
    strip.set_jobs(registry.snapshot())
    text = strip.hover_text(P.SURASURA)
    at = time.strftime(strings.PHASE_TIME, time.localtime(old.view().ended_at))
    assert "<b>Surasura</b>" in text and strings.PHASE_ABOUT[P.SURASURA] in text
    assert "Generating · Reading your files 3 / 12" in text and strings.PHASE_DONE.format(time=at) in text
    assert "<button" not in text and "<a " not in text                    # no buttons in it
    gen.finish(ok=False, message="the analyzer stopped <exit 1>")
    strip.set_jobs(registry.snapshot())
    assert "Failed " + at[:0] in strip.hover_text(P.SURASURA) and "&lt;exit 1&gt;" in strip.hover_text(P.SURASURA)
    assert strings.PHASE_IDLE in strip.hover_text(P.ARRIVALS)


def test_a_failure_stays_until_the_hover_leaves_it_and_the_hover_shows_the_bubble(strip):
    class Tips:
        def __init__(self):
            self.asked, self.hidden = [], 0

        def request(self, widget, rect, text):
            self.asked.append((rect, text))

        def retext(self, widget, rect, text):
            self.asked.append((rect, text))

        def hide(self):
            self.hidden += 1

        def hide_part_unless(self, widget, pos):
            pass
    strip.tooltips = tips = Tips()
    registry = JobRegistry()
    job = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None)
    job.finish(ok=False, message="Anki stopped answering")
    strip.set_jobs(registry.snapshot())
    assert strip.states[P.ANKI].failed
    centre = strip.rect_of(P.ANKI).center().toPoint()
    QApplication.sendEvent(strip, QHelpEvent(QEvent.Type.ToolTip, centre, strip.mapToGlobal(centre)))
    assert tips.asked and "Anki stopped answering" in tips.asked[-1][1]
    assert strip.states[P.ANKI].failed                                  # still red while it is read
    QApplication.sendEvent(strip, QEvent(QEvent.Type.Leave))
    assert strip.states[P.ANKI].failed is None                          # looked at: dim again
    assert "Anki stopped answering" in strip.hover_text(P.ANKI)          # ... still said in its hover


# --- in the window -------------------------------------------------------------------------------------------- #
def test_in_the_bar_the_strip_is_first_and_the_status_line_keeps_only_what_no_circle_shows(world):
    win = world.win
    row = win.footer.layout()
    assert row.itemAt(0).widget() is win.phase
    gen = world.registry.submit("generate", "Generating", lambda j: None)
    upd = world.registry.record("update", "Downloading the update")
    assert wait_until(lambda: win.phase.states[P.SURASURA].running)
    assert wait_until(lambda: win.bar_line.full() == "Downloading the update")       # Generating: on ス only (Q5)
    assert win._busy                                                                  # the hairline still runs
    gen.finish()
    upd.finish()


def test_the_offline_folder_is_arrivals_amber_and_moves_waiting_on_the_store_are_its_still_arc(world):
    win = world.win
    win.moves_saving(True)
    assert win.phase.states[P.ARRIVALS].waiting
    assert strings.MOVE_WORDS["saving"] in win.phase.hover_text(P.ARRIVALS)
    win.moves_saving(False)
    assert not win.phase.states[P.ARRIVALS].waiting
    win.offline_text = lambda: "D:\\Anime can't be reached"
    win.sources = [object()]
    win._show_offline()
    assert win.phase.states[P.ARRIVALS].needs == "D:\\Anime can't be reached"
    win.offline_text = lambda: ""
    win._show_offline()
    assert win.phase.states[P.ARRIVALS].needs is None


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_at_the_narrowest_window_the_strip_fits_the_footer_beside_every_mark(world, size):
    win = world.win
    style.apply(QApplication.instance(), "night", size, "ja")
    win._apply_sizes()
    win.resize(*theme.WINDOW_MIN)
    win.show_status(world.status.snapshot()._replace(replan="Anki: placing tomorrow's 20 cards…",
                                                     connect="Up to date", ankiweb="AnkiWeb: synced 18:42"))
    QApplication.processEvents()
    assert wait_until(lambda: win.width() == theme.WINDOW_MIN[0])
    footer = win.footer
    assert footer.height() == theme.size("footer")
    r = win.phase.geometry()
    assert r.top() >= 0 and r.bottom() < footer.height() and r.left() >= 0
    marks = [w for w in (win.bar_line, win.bar_replan, win.bar_connect, win.anki_mark, win.known) if w.isVisible()]
    for w in marks:
        g = w.geometry()
        assert g.right() < footer.width() and not g.intersects(r), w.objectName()
    assert win.bar_line.width() >= 120                                  # the status line keeps room to say something
    print(f"{size}: footer {footer.width()} px, strip {r.width()} px, line {win.bar_line.width()} px, marks "
          + ", ".join(f"{w.objectName() or type(w).__name__} {w.width()}" for w in marks))


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_at_100_and_200_percent_the_circles_paint_inside_the_footers_height(strip, dpr):
    registry = JobRegistry()
    registry.submit("generate", "Generating", lambda j: None)
    strip.set_jobs(registry.snapshot())
    img = _image(strip, dpr)
    assert img.height() == round(strip.height() * dpr) <= round(theme.size("footer") * dpr)
    assert _near(_ring(strip, P.SURASURA, img, dpr=dpr), C()["accent"])
    assert strip.width() == 5 * theme.size("phase-circle") + 4 * theme.size("phase-gap")


def test_the_credits_name_ankis_trademark_its_link_and_anki_miners_licence():
    text = credits.all_credits()
    assert "Anki® is a registered trademark of Ankitects Pty Ltd" in text
    assert "Surasura is not affiliated with or endorsed by the Anki project" in text
    assert "https://apps.ankiweb.net" in text
    assert "Anki Miner icon © 0xzerolight (Zero), GPL-3.0" in text


def test_a_hovers_words_move_in_place_while_its_bubble_shows(strip):
    from app.qt import tooltip
    tips = tooltip.Tooltips()
    strip.tooltips = tips
    registry = JobRegistry()
    job = registry.submit("generate", "Generating", lambda j: None)
    strip.set_jobs(registry.snapshot())
    centre = strip.rect_of(P.SURASURA).center().toPoint()
    QApplication.sendEvent(strip, QHelpEvent(QEvent.Type.ToolTip, centre, strip.mapToGlobal(centre)))
    assert wait_until(lambda: tips.showing() is not None and "Generating" in tips.showing())
    job.progress("Counting words", 1, 2)
    strip.set_jobs(registry.snapshot())
    assert "Generating · Counting words 1 / 2" in tips.showing()       # the same bubble, its words moved
    tips.retext(strip, strip.rect_of(P.ANKI).toAlignedRect(), "another part's")      # not its part: nothing
    assert "Counting words" in tips.showing()
    tips.hide()
    tips.bubble.deleteLater()
