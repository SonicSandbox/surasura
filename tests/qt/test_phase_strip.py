"""The phase strip (Sonic, 2026-10-23; `app/qt/phase_strip.py`): five circles at the bar's bottom left, lit by the work
each stands for — the state painted around the mark, never on it.

What a wrong answer would cost a learner:
  * a circle that says nothing while its work runs, or keeps turning after it ended (and keeps the laptop awake);
  * a logo changed to show a state (Anki's and Anki Miner's terms: unmodified);
  * a failure gone before it was seen, or a hover that doesn't say what runs;
  * a strip that pushes the bar's other marks out at the narrowest window;
  * the same job said twice, on its circle and in the status line.
"""
import html
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
from tests.qt.conftest import logos_in, wait_until
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
    assert logos_in(s)                                  # what the strip paints is read only once it has finished opening
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
    assert len(strip._pix) == 2                                         # Anki Miner's and Anki's logos, decoded
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
    assert strip.states[P.SURASURA].running and strip.states[P.SURASURA].lines == ("Reading your files",)  # indexer's
    assert strings.PHASE_JOB_NAMES["indexer"] == "Reading your files"   # (alpha 3: its plain name, IKA3-3)
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
    assert ("Generating · Reading your files 3 / 12" in text
            and strings.PHASE_DONE.format(what="Generating", time=at) in text)
    assert "<button" not in text and "<a " not in text                    # no buttons in it
    gen.finish(ok=False, message="the analyzer stopped <exit 1>")
    strip.set_jobs(registry.snapshot())
    assert "Last: Generating — failed " in strip.hover_text(P.SURASURA)
    assert "&lt;exit 1&gt;" in strip.hover_text(P.SURASURA)
    assert strings.PHASE_IDLE in strip.hover_text(P.ARRIVALS)


def test_a_failure_stays_until_the_hover_leaves_it_and_the_hover_shows_the_bubble(strip):
    class Tips:
        def __init__(self):
            self.asked, self.hidden = [], 0

        def request(self, widget, rect, text):
            self.asked.append((rect, text))
            self.shown = (widget, rect)                                 # (shown at once: no delay in this stand-in)

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


def test_the_offline_folder_is_said_in_arrivals_hover_never_amber_and_moves_waiting_on_the_store_are_its_still_arc(
        world):
    """a7 (Sonic 2026-10-29: "If no decision it shouldn't be yellow"): a drive away decides nothing — it comes back by
    itself — so 届 says it in its hover (and the bar's offline line), and stays out of amber; a press opens Sources."""
    win = world.win
    win.moves_saving(True)
    assert win.phase.states[P.ARRIVALS].waiting
    assert strings.MOVE_WORDS["saving"] in win.phase.hover_text(P.ARRIVALS)
    win.moves_saving(False)
    assert not win.phase.states[P.ARRIVALS].waiting
    win.offline_text = lambda: "D:\\Anime can't be reached"
    win.sources = [object()]
    win._show_offline()
    st = win.phase.states[P.ARRIVALS]
    assert st.needs is None and win.phase.go(P.ARRIVALS) is None and not (st.waiting or st.running or st.failed)
    assert html.escape("D:\\Anime can't be reached") in win.phase.hover_text(P.ARRIVALS)
    assert strings.PHASE_PRESS in win.phase.hover_text(P.ARRIVALS)
    win.offline_text = lambda: ""
    win._show_offline()
    assert win.phase.states[P.ARRIVALS].lines == ()


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
    marks = [w for w in (win.bar_line, win.anki_mark, win.known) if w.isVisible()]     # (⇅ ⇄ went in alpha 3)
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


# --- the review's fix round (PS-A1 … A8) --------------------------------------------------------------------------- #
def test_a_press_that_ends_with_no_job_of_its_own_ticks_nothing_for_an_older_run(strip):
    # PS-A1: a press with no job (Refresh's look not built yet, a sync refused) ended -> the circle's older run ticked
    # green again as a fresh *Done*. A tick is for a run that ended since the circle went lit.
    registry = JobRegistry()
    presses = Presses()
    strip.follow_presses(presses)
    gen = registry.submit("generate", "Generating", lambda j: None)
    strip.set_jobs(registry.snapshot())
    gen.finish()
    strip.set_jobs(registry.snapshot())
    assert strip._ticks[P.SURASURA][0] == gen.id                        # its own run: the tick
    strip._untick(P.SURASURA)                                           # (faded)
    strip.now.now = gen.view().ended_at + 5
    p = presses.get("generate")
    p.press()
    assert strip.states[P.SURASURA].waiting
    p.done()                                                            # ended with no job of its own
    assert P.SURASURA not in strip._ticks


def test_a_press_that_failed_is_its_circles_failure_until_hovered_or_the_next_run(strip):
    # PS-A1: a press that failed (the sync couldn't be asked) isn't live, so nothing showed it. Now it is the circle's
    # failure, red with its words, until the hover leaves it or the circle's next run.
    presses = Presses()
    strip.follow_presses(presses)
    p = presses.get("known:sync")
    p.press()
    p.failed("Anki is closed")
    assert strip.states[P.ANKI].failed == "Anki is closed"
    assert "Anki is closed" in strip.hover_text(P.ANKI)
    from types import SimpleNamespace
    strip.tooltips = SimpleNamespace(shown=(strip, strip.rect_of(P.ANKI).toAlignedRect()), hide=lambda: None,
                                     retext=lambda *a: None, request=lambda *a: None)   # its bubble showed ...
    strip._looking = (P.ANKI, tuple(strip._marks(P.ANKI, strip.states[P.ANKI])))     # hovered ...
    strip._leave_hover(None)                                                         # ... and left
    assert strip.states[P.ANKI].failed is None
    p.press()                                                           # pressed again, failed again: red again
    p.failed("Anki is closed")
    assert strip.states[P.ANKI].failed == "Anki is closed"
    registry = JobRegistry()
    registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, automatic=False)
    strip.set_jobs(registry.snapshot())                                 # the circle's next run: the failure is over
    assert strip.states[P.ANKI].running and strip.states[P.ANKI].failed is None


def test_two_circles_turning_apart_never_repaint_the_one_between(strip, clock):
    # PS-A6: two dirty rects merge into one region whose bounding box held Anki Miner: it was painted every frame.
    registry = JobRegistry()
    registry.submit("generate", "Generating", lambda j: None)
    registry.submit("junban", "Re-ordering Anki", lambda j: None)
    strip.set_jobs(registry.snapshot())
    QApplication.processEvents()
    before = dict(strip.paints)
    for _ in range(5):
        clock.advance(40)                                               # a frame: both arcs turn
        QApplication.processEvents()
    assert strip.paints[P.SURASURA] > before[P.SURASURA] and strip.paints[P.JUNBAN] > before[P.JUNBAN]
    assert strip.paints[P.MINER] == before[P.MINER]


def test_a_new_screen_ratio_decodes_the_logos_again(strip, monkeypatch):
    # PS-A8: moved to a screen of another scale, the logos kept their old ratio (drawn soft).
    asked = []
    monkeypatch.setattr(phase_strip.logos, "logo", lambda name, px, got, dpr=1.0: asked.append((name, dpr)))
    monkeypatch.setattr(strip, "devicePixelRatioF", lambda: 2.5)
    QApplication.sendEvent(strip, QEvent(QEvent.Type.DevicePixelRatioChange))
    assert sorted(asked) == [("anki_miner", 2.5), ("anki_outline", 2.5)]


def test_an_automatic_job_held_before_it_starts_stays_on_the_status_line(world):
    # PS-A2: an automatic job held by a gate never starts, so its circle never lit — and it had left the status line:
    # shown nowhere. A job stays on the line until a circle will show it.
    win = world.win
    world.registry.gate(lambda kind: "Waits for the update" if kind == "anki-sync" else None)
    job = world.registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, automatic=True)
    assert job.view().state == J.WAITING
    assert wait_until(lambda: "Updating known words from Anki" in win.bar_line.full())
    assert not win.phase.states[P.ANKI].waiting
    job.cancel()


def test_connects_waiting_episodes_leave_the_headers_hairline_off(world):
    # PS-A3 (intent keeper drift 1): an episode not timed to its video can wait for days; the hairline said the window
    # was busy all that time. Its circle shows it (amber); the hairline counts only jobs under way.
    win = world.win
    wait = world.registry.record("mine-wait", "Connect", automatic=True, reason="Not timed to its video",
                                 needs="Not timed to its video")
    assert wait_until(lambda: win.phase.states[P.MINER].needs == "Not timed to its video")
    QApplication.processEvents()
    assert not win._busy and not win.progress.busy
    run = world.registry.record("mine", "Making cards", automatic=True)
    assert wait_until(lambda: win._busy)                                # a job under way: it runs
    run.finish()
    wait.finish()


# --- alpha 3 (Sonic 2026-10-24): ⇅ ⇄ gone into 順's and Anki Miner's hovers; a circle's press opens its settings ---- #
# What a wrong answer would cost him: a press on a circle that does nothing (or opens the wrong page); a hand over a
# circle that can't be pressed; a hover that says the same thing twice, or nothing about what 順 / Anki Miner wait on.
def _click(widget, pos, button=None):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    QTest.mouseClick(widget, button or Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def _centre(strip, circle):
    return strip.rect_of(circle).center().toPoint()


def test_a3_the_hover_is_name_and_what_it_does_then_now_then_the_last_run_named_then_the_click(strip):
    registry = JobRegistry()
    old = registry.submit("generate", "Generating", lambda j: None)
    old.finish()
    strip.set_jobs(registry.snapshot())
    strip.set_opens({P.SURASURA})
    text = strip.hover_text(P.SURASURA)
    at = time.strftime(strings.PHASE_TIME, time.localtime(old.view().ended_at))
    parts = text.split("<br>")
    assert "<b>Surasura</b>" in parts[0] and strings.PHASE_ABOUT[P.SURASURA] in parts[0]   # one line: name · what
    assert strings.PHASE_IDLE in parts[1]                               # nothing now, said once
    assert strings.PHASE_DONE.format(what="Generating", time=at) in parts[2]               # the last run, named
    assert strings.PHASE_PRESS in parts[3] and len(parts) == 4
    assert strings.PHASE_PRESS not in strip.hover_text(P.ANKI)           # not pressable: no promise of a click
    gen = registry.submit("generate", "Generating", lambda j: None)
    gen.progress("Reading your files", 3, 12)
    strip.set_jobs(registry.snapshot())
    text = strip.hover_text(P.SURASURA)
    assert "Generating · Reading your files 3 / 12" in text and strings.PHASE_IDLE not in text
    gen.finish(ok=False, message="the analyzer stopped")
    strip.set_jobs(registry.snapshot())
    at = time.strftime(strings.PHASE_TIME, time.localtime(gen.view().ended_at))
    assert strings.PHASE_FAILED.format(what="Generating", time=at, why="the analyzer stopped") in \
        strip.hover_text(P.SURASURA)


def test_a3_junban_and_anki_miner_say_their_standing_line_only_while_no_job_of_theirs_runs(strip):
    """⇅'s line (the re-order host's) is 順's now-line and ⇄'s (Connect's) Anki Miner's — only with no job of theirs
    live, so a mining job's own line (Michi's T3: it names the episode) is never said twice."""
    from app.services.status import Snapshot
    snap = Snapshot(lines=(), failure=None, needs_you=(), ankiweb=None, connect="Up to date · 12 cards made today",
                    logs=None, taken_at=0, replan="Anki is in a review — re-ordering after it")
    strip.set_status(snap)
    assert "Anki is in a review — re-ordering after it" in strip.hover_text(P.JUNBAN)
    assert "Up to date · 12 cards made today" in strip.hover_text(P.MINER)
    assert strings.PHASE_IDLE not in strip.hover_text(P.MINER)
    for c in (P.ARRIVALS, P.SURASURA, P.ANKI):
        assert "re-ordering" not in strip.hover_text(c) and "cards made" not in strip.hover_text(c)
    registry = JobRegistry()
    mine = registry.record("mine", "Making cards", automatic=False)
    mine.progress("Hyouka 3 · Filling fields 94%")
    strip.set_jobs(registry.snapshot())
    text = strip.hover_text(P.MINER)
    assert "Making cards · Hyouka 3 · Filling fields 94%" in text and "cards made today" not in text
    mine.finish()
    strip.set_jobs(registry.snapshot())
    assert "Up to date · 12 cards made today" in strip.hover_text(P.MINER)       # back once the job ended
    strip.set_status(snap._replace(connect=None, replan=None))
    assert strings.PHASE_IDLE in strip.hover_text(P.JUNBAN)


def test_a3_a_standing_line_moving_repaints_no_circle_and_its_words_are_never_markup(strip):
    # S19: the words move in the hover alone; AD-14 (moved from the ⇄ mark): a provider's line is text, never markup
    from app.services.status import Snapshot
    strip.set_status(Snapshot(lines=(), failure=None, needs_you=(), ankiweb=None, connect="Up to date", logs=None,
                              taken_at=0, replan=None))
    painted = dict(strip.paints)
    strip.set_status(Snapshot(lines=(), failure=None, needs_you=(), ankiweb=None, connect="Connect: <b>error</b> page",
                              logs=None, taken_at=1, replan="順 is busy"))
    QApplication.processEvents()
    assert strip.paints == painted
    assert "<b>error</b>" not in strip.hover_text(P.MINER) and "&lt;b&gt;error" in strip.hover_text(P.MINER)


def test_a3_a_press_on_a_circle_that_opens_says_which_and_one_that_doesnt_does_nothing(strip):
    from PyQt6.QtCore import Qt
    got = []
    strip.opened.connect(got.append)
    strip.set_opens({P.ARRIVALS, P.MINER})
    _click(strip, _centre(strip, P.MINER))
    assert got == [P.MINER]
    _click(strip, _centre(strip, P.ANKI))                               # no settings given it: nothing
    _click(strip, _centre(strip, P.MINER), Qt.MouseButton.RightButton)  # only the left button presses
    assert got == [P.MINER]
    from PyQt6.QtTest import QTest
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(strip, P.ARRIVALS))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(strip, P.MINER))
    assert got == [P.MINER]                                             # let go on another circle: no press


def test_a3_the_hand_shows_only_over_a_circle_that_opens(strip):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    strip.set_opens({P.SURASURA})
    QTest.mouseMove(strip, _centre(strip, P.SURASURA))
    assert wait_until(lambda: strip.cursor().shape() == Qt.CursorShape.PointingHandCursor)
    QTest.mouseMove(strip, _centre(strip, P.ANKI))
    assert wait_until(lambda: strip.cursor().shape() == Qt.CursorShape.ArrowCursor)
    gap = strip.rect_of(P.SURASURA).right() + 1.5
    QTest.mouseMove(strip, QPoint(round(gap), strip.height() // 2))
    assert strip.cursor().shape() == Qt.CursorShape.ArrowCursor          # between two circles: nothing to press
    strip.set_opens(set())
    assert strip.focusPolicy() == Qt.FocusPolicy.NoFocus                 # nothing to press: no Tab stop either


def test_a3_the_keyboard_tabs_in_moves_with_the_arrows_and_opens_with_enter_or_space(strip):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    got = []
    strip.opened.connect(got.append)
    strip.set_opens({P.ARRIVALS, P.SURASURA, P.ANKI})
    assert strip.focusPolicy() == Qt.FocusPolicy.TabFocus              # one Tab stop for the strip
    strip.window().activateWindow()
    strip.setFocus(Qt.FocusReason.TabFocusReason)
    assert wait_until(lambda: strip.hasFocus())
    assert strip._focus == P.ARRIVALS
    QTest.keyClick(strip, Qt.Key.Key_Return)
    QTest.keyClick(strip, Qt.Key.Key_Right)
    QTest.keyClick(strip, Qt.Key.Key_Right)                             # past 鉱 and 順 (no settings given them)
    assert strip._focus == P.ANKI
    QTest.keyClick(strip, Qt.Key.Key_Right)                             # the end: stays
    QTest.keyClick(strip, Qt.Key.Key_Space)
    QTest.keyClick(strip, Qt.Key.Key_Left)
    QTest.keyClick(strip, Qt.Key.Key_Enter)
    assert got == [P.ARRIVALS, P.ANKI, P.SURASURA]
    assert strings.PHASE_NAMES[P.SURASURA] in strip.accessibleDescription()


def test_a3_the_keyboards_circle_is_washed_in_the_accent_and_its_hover_shows(strip):
    from PyQt6.QtCore import Qt
    asked = []

    class Tips:
        def request(self, widget, rect, text):
            asked.append(text)

        def retext(self, widget, rect, text):
            pass

        def hide(self):
            pass

        def hide_part_unless(self, widget, pos):
            pass
    strip.tooltips = Tips()
    strip.set_opens({P.SURASURA})
    before = _image(strip).pixelColor(_centre(strip, P.SURASURA) + QPoint(-4, -4))
    strip.window().activateWindow()
    strip.setFocus(Qt.FocusReason.TabFocusReason)
    assert wait_until(lambda: strip.hasFocus())
    QApplication.processEvents()
    after = _image(strip).pixelColor(_centre(strip, P.SURASURA) + QPoint(-4, -4))
    assert after != before                                              # washed (inside its ring, off the mark)
    assert asked and "<b>Surasura</b>" in asked[-1]


@pytest.fixture
def junban_world(qapp, tmp_path, monkeypatch):
    """The window with Junban found (`modules/` isn't in the public repo's checkout: its look answers no there)."""
    from app.qt import shell
    from tests.qt.test_jobs_bar import World
    monkeypatch.setattr(shell, "_junban_here", lambda: True)
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    yield w
    w.close()


def test_a3_in_the_window_the_reorder_and_connect_marks_are_gone_and_each_circle_opens_its_settings(junban_world):
    from PyQt6.QtWidgets import QLabel
    win = junban_world.win
    assert not hasattr(win, "bar_replan") and not hasattr(win, "bar_connect")
    assert not [w for w in win.footer.findChildren(QLabel) if w.text() in ("⇅", "⇄")]
    assert wait_until(lambda: P.JUNBAN in win.phase.opens)            # Junban found (a worker's look)
    assert win.phase.opens == set(P.CIRCLES)
    opened = []
    win.open_setting = lambda target: opened.append(target) or True
    for c in P.CIRCLES:
        _click(win.phase, _centre(win.phase, c))
    assert opened == ["library_folders", "level", "connect_enabled", "junban", "known"]


def test_a3_each_circles_settings_target_is_a_place_the_settings_page_knows():
    from app.qt import settings_catalog
    for circle, target in phase_strip.SETTINGS.items():
        assert settings_catalog.locate(target) is not None, (circle, target)
    assert settings_catalog.locate(phase_strip.SETTINGS[P.JUNBAN]) == ("junban", None)
    assert settings_catalog.locate(phase_strip.SETTINGS[P.ANKI]) == ("known", None)


def test_a3_a_press_really_opens_the_settings_tab_on_that_circles_section(world):
    win = world.win
    _click(win.phase, _centre(win.phase, P.ANKI))
    assert win.current_tab() == "settings"
    page = win.settings_page
    assert wait_until(lambda: "known" in page.slabs and page.slabs["known"].isVisible())


def test_a3_without_junban_its_circle_has_no_settings_to_open(qapp, tmp_path, monkeypatch):
    from app.qt import shell
    from tests.qt.test_jobs_bar import World
    answered = []
    monkeypatch.setattr(shell, "_junban_here", lambda: answered.append(1) or False)
    found = shell.ShellWindow._junban_found
    monkeypatch.setattr(shell.ShellWindow, "_junban_found", lambda self, here: (found(self, here), answered.append(2)))
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    try:
        assert wait_until(lambda: answered == [1, 2])                   # the worker asked and its answer landed
        assert P.JUNBAN not in w.win.phase.opens and P.ANKI in w.win.phase.opens
        assert strings.PHASE_PRESS not in w.win.phase.hover_text(P.JUNBAN)
    finally:
        w.close()


# --- alpha 3's review round (intent keeper IKA3-*, adversary A3A-*) ------------------------------------------------- #
def _snap(**kw):
    from app.services.status import Snapshot
    base = dict(lines=(), failure=None, needs_you=(), ankiweb=None, connect=None, logs=None, taken_at=0, replan=None)
    base.update(kw)
    return Snapshot(**base)


def test_a7_junban_is_amber_only_while_a_decision_waits_in_its_window_and_its_press_goes_there(strip):
    """a7 (Sonic 2026-10-29: "If yellow i would expect it to let me go somewhere to make a decision that is
    highlighted. If no decision it shouldn't be yellow but something else."): 順 is amber only for a line whose decision
    is in 順's window (`InJunban`: the deck list, or the Undo for the unfinished reorder) and its press goes there; a
    line that gives up with nothing to decide (Anki closed, a Generate to press, Only i+1 / Coverage) is its hover's
    words, a wait that clears by itself the same, and a fault (`Fails`) red until looked at."""
    from app import replan_preview as rp
    strip.set_opens({P.JUNBAN})
    strip.set_status(_snap(replan=rp.REVIEWING))                         # a wait that clears by itself
    assert strip.states[P.JUNBAN].needs is None and strip.go(P.JUNBAN) is None
    for line in (rp.GivesUp(rp.CLOSED), rp.GivesUp(rp.PRESS_GENERATE), rp.GivesUp(rp.NEW_CONTENT),
                 rp.GivesUp(rp.AFTER_GENERATE.format(mode="Only i+1 sentences"))):
        strip.set_status(_snap(replan=line))                             # nothing to decide: words only
        st = strip.states[P.JUNBAN]
        assert st.needs is None and not st.failed and strip.go(P.JUNBAN) is None, line
        assert strip.hover_text(P.JUNBAN).count(html.escape(str(line))) == 1, line   # said once, as its now-line
        assert strings.PHASE_PRESS in strip.hover_text(P.JUNBAN)
    strip.set_status(_snap(replan=rp.InJunban(rp.RESTORE_FIRST)))
    assert strip.states[P.JUNBAN].needs == rp.RESTORE_FIRST and strip.go(P.JUNBAN) == P.Go("junban", "restore")
    assert html.escape(strings.PHASE_PRESS_RESTORE) in strip.hover_text(P.JUNBAN)
    strip.set_status(_snap(replan=rp.InJunban(rp.ONE_DECK)))
    assert strip.states[P.JUNBAN].needs == rp.ONE_DECK and strip.go(P.JUNBAN) == P.Go("junban", "deck")
    assert html.escape(strings.PHASE_PRESS_DECK) in strip.hover_text(P.JUNBAN)
    strip.set_status(_snap(replan=rp.Fails("Re-ordering as you move stopped: disk full")))
    st = strip.states[P.JUNBAN]
    assert st.failed == "Re-ordering as you move stopped: disk full" and st.needs is None and strip.go(P.JUNBAN) is None
    strip.set_status(_snap(replan=rp.UP_TO_DATE))                        # cleared: amber and red off, the settings again
    st = strip.states[P.JUNBAN]
    assert st.needs is None and not st.failed and strip.go(P.JUNBAN) is None
    assert html.escape(rp.UP_TO_DATE) in strip.hover_text(P.JUNBAN) and strings.PHASE_PRESS in strip.hover_text(P.JUNBAN)


def test_a3_in_the_window_junbans_press_on_an_unfinished_reorder_opens_junbans_window(junban_world, monkeypatch):
    from app import replan_preview as rp
    from app.qt import windows
    win = junban_world.win
    launched, opened = [], []
    monkeypatch.setattr(windows, "launch", lambda shell, op: launched.append(op.name))
    win.open_setting = lambda target: opened.append(target) or True
    assert wait_until(lambda: P.JUNBAN in win.phase.opens)
    win.show_status(win.services.status.snapshot()._replace(replan=rp.InJunban(rp.RESTORE_FIRST)))
    _click(win.phase, _centre(win.phase, P.JUNBAN))
    assert launched == ["junban"] and opened == []
    win.show_status(win.services.status.snapshot()._replace(replan=rp.UP_TO_DATE))
    _click(win.phase, _centre(win.phase, P.JUNBAN))
    assert launched == ["junban"] and opened == ["junban"]               # (Junban's settings section)


def test_a3_a_circle_lit_by_a_press_with_no_job_yet_says_the_press_not_nothing_running(strip):
    # A3A-1: the arc turns from the press; the hover never says *Nothing running now* or a stale standing line
    strip.set_status(_snap(connect="Up to date · 3 cards made today"))
    presses = Presses()
    strip.follow_presses(presses)
    presses.get("mine:ja:12").press()
    assert strip.states[P.MINER].running or strip.states[P.MINER].waiting
    text = strip.hover_text(P.MINER)
    assert strings.PHASE_IDLE not in text and "cards made today" not in text and strings.PHASE_STARTING in text


def test_a3_jobs_are_named_in_plain_words_in_the_hover_now_and_last(strip):
    # IKA3-3: *Indexing* is a word for us; the hover says what it does
    registry = JobRegistry()
    job = registry.submit("indexer", "Indexing", lambda j: None)
    strip.set_jobs(registry.snapshot())
    assert "Reading your files" in strip.hover_text(P.SURASURA) and "Indexing" not in strip.hover_text(P.SURASURA)
    job.finish()
    strip.set_jobs(registry.snapshot())
    assert "Last: Reading your files — done" in strip.hover_text(P.SURASURA)
    wait = registry.record("mine-anki", "Connect", automatic=True, reason="Waiting while you review in Anki · 19 episodes")
    strip.now = lambda: wait.started_at + 2
    strip.set_jobs(registry.snapshot())
    assert "Making cards · Waiting while you review in Anki · 19 episodes" in strip.hover_text(P.ANKI)


class _SlowTips:
    """A bubble that has been asked for but hasn't shown yet (its delay still running)."""
    def __init__(self):
        self.asked, self.shown = [], None

    def request(self, widget, rect, text):
        self.asked.append(text)

    def retext(self, widget, rect, text):
        pass

    def hide(self):
        pass

    def hide_part_unless(self, widget, pos):
        pass


def test_a3_passing_a_failed_circle_by_keyboard_before_its_bubble_shows_leaves_it_red(strip):
    # IKA3-5 / A3A-2: tabbing past 届 cleared its failure unseen; looked at only once its bubble really showed
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    strip.tooltips = tips = _SlowTips()
    registry = JobRegistry()
    bad = registry.submit("library-look", "Looking at your folders", lambda j: None)
    bad.finish(ok=False, message="D:\\Anime can't be read")
    strip.set_jobs(registry.snapshot())
    strip.set_opens({P.ARRIVALS, P.SURASURA})
    strip.window().activateWindow()
    strip.setFocus(Qt.FocusReason.TabFocusReason)
    assert wait_until(lambda: strip.hasFocus()) and strip._focus == P.ARRIVALS
    QTest.keyClick(strip, Qt.Key.Key_Right)                             # on, before the bubble came
    assert strip.states[P.ARRIVALS].failed                              # still red: nobody saw it
    QTest.keyClick(strip, Qt.Key.Key_Left)
    tips.shown = (strip, strip.rect_of(P.ARRIVALS).toAlignedRect())     # now its bubble shows ...
    QTest.keyClick(strip, Qt.Key.Key_Right)                             # ... and the keyboard moves on: seen
    assert strip.states[P.ARRIVALS].failed is None


def test_a3_the_window_coming_back_never_pops_the_bubble_by_itself(strip):
    # A3A-3: only Tab / Backtab / a shortcut shows the hover on focus, as the window's own tooltips do
    from PyQt6.QtCore import Qt
    strip.tooltips = tips = _SlowTips()
    strip.set_opens({P.SURASURA})
    strip.window().activateWindow()
    strip.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    assert wait_until(lambda: strip.hasFocus())
    assert tips.asked == [] and strip._focus == P.SURASURA              # washed, but no bubble
    strip.clearFocus()
    strip.setFocus(Qt.FocusReason.TabFocusReason)
    assert wait_until(lambda: tips.asked)


def test_a3_a_double_click_or_a_held_key_opens_once(strip):
    # A3A-4 / A3A-5: each open restarts the page's glide and wash
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtTest import QTest
    got = []
    strip.opened.connect(got.append)
    strip.set_opens({P.SURASURA})
    _click(strip, _centre(strip, P.SURASURA))                           # the OS: a click, then the double-click
    QTest.mouseDClick(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(strip, P.SURASURA))
    assert got == [P.SURASURA]
    strip.window().activateWindow()
    strip.setFocus(Qt.FocusReason.TabFocusReason)
    assert wait_until(lambda: strip.hasFocus())
    for repeat in (False, True, True):
        QApplication.sendEvent(strip, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                                Qt.KeyboardModifier.NoModifier, " ", repeat))
    assert got == [P.SURASURA, P.SURASURA]


def test_a3_set_opens_repaints_no_circle_and_turns_the_hand_on_under_a_resting_pointer(strip, monkeypatch):
    # A3A-8 / IKA3-8: Junban found at start-up changes no circle's look; a pointer already on 順 gets the hand
    from PyQt6.QtCore import Qt
    asked = []
    monkeypatch.setattr(strip, "update", lambda *a: asked.append(a))
    monkeypatch.setattr(strip, "_under_mouse", lambda: P.JUNBAN)
    strip.set_opens({P.SURASURA})
    strip.set_opens({P.SURASURA, P.JUNBAN})
    assert asked == []
    assert strip.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_a3_the_read_out_says_junbans_and_anki_miners_words_with_no_job_too(strip):
    # IKA3-9: a screen reader hears what the hover says, not only for a lit circle
    strip.set_status(_snap(connect="Up to date · 12 cards made today", replan="Anki's order is up to date"))
    said = strip.accessibleDescription()
    assert "Anki Miner: Up to date · 12 cards made today" in said and "Junban 順: Anki's order is up to date" in said


def test_a3_the_tooltips_know_which_part_really_showed(qapp):
    # IKA3-5's other half: `Tooltips.shown` is set only once the bubble shows, kept after it hides
    from PyQt6.QtCore import QRect
    from app.qt import tooltip
    host = QWidget()
    host.resize(100, 30)
    host.show()
    tips = tooltip.Tooltips()
    try:
        part = QRect(0, 0, 20, 20)
        freeze.set_frozen(False)
        tips.request(host, part, "words")
        assert tips.shown is None                                       # asked, its delay running
        tips._show_now()
        assert tips.shown == (host, part)
        tips.hide()
        assert tips.shown == (host, part)                               # kept once it hid (the strip asks on Leave)
        tips.request(host, QRect(30, 0, 20, 20), "other")
        assert tips.shown is None
    finally:
        freeze.set_frozen(None)
        tips.hide()
        tips.bubble.deleteLater()
        host.close()


def test_a3_a_press_on_arrivals_brings_the_library_folders_row_into_view(world):
    # A3A-9: a target far down the page (the Anki one is on screen at the top whatever `reveal` does)
    win = world.win
    win.resize(1100, 700)
    _click(win.phase, _centre(win.phase, P.ARRIVALS))
    assert win.current_tab() == "settings"
    page = win.settings_page
    assert wait_until(lambda: "library_folders" in page.rows and page.rows["library_folders"].isVisible()
                      and page.scroll.viewport().rect().contains(
                          page.rows["library_folders"].mapTo(page.scroll.viewport(), QPoint(0, 0))), timeout=8)
