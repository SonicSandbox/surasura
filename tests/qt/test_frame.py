"""The frame (W3.1a package E; the RUNBOOK §1 *Frame*, *Header*, *Level ▾*, *Tabs*, *Footer*, *Goal dock*).

What a wrong answer would cost:
  * a frame drawn with lines and side edges again, or an edge that is a live effect (repainted with the list under it,
    or turning off the list's fast scroll by lying over it);
  * a level ▾ whose pop Esc can't close, whose Generate or journey does nothing, or whose mark hides a failed
    Generate (amber) behind a stale one;
  * a vein that never stops the clock (a laptop's battery), overshoots its tab, or travels under Reduced motion;
  * an emerald lit while Anki is closed — Sonic would believe his known words are current;
  * a Goal hand that greys every cover at every paint, shows more than nine, or a wells API that offers Goal when the
    drag comes from Goal, or lights Finished for a split's first part;
  * a tab switch or a dock hover repainting the whole window (S19).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from app import theme
from app.qt import frame, motion, shell, strings
from app.services import generate as G
from app.services.view_rows import Goal
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb_array

TITLES = ("ぼっち・ざ・ろっく！", "葬送のフリーレン", "薬屋のひとりごと", "スパイファミリー", "チェンソーマン",
          "呪術廻戦", "その着せ替え人形は恋をする", "よふかしのうた", "推しの子", "ダンジョン飯", "からかい上手の高木さん",
          "響け！ユーフォニアム")


def _goal(n=12, files=128):
    covers = TITLES[:n]
    return Goal(titles=n, files=files, covers=covers, line=f"{n} titles · {files} files", tip="Someday, in no order")


class Paints(QObject):
    """Counts the paint events each watched widget gets."""

    def __init__(self, *widgets):
        super().__init__()
        self.seen = {w: 0 for w in widgets}
        for w in widgets:
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint and obj in self.seen:
            self.seen[obj] += 1
        return False

    def reset(self):
        for w in self.seen:
            self.seen[w] = 0


def _settle(n=20):
    for _ in range(n):
        QApplication.processEvents()


@pytest.fixture
def window(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    _settle()
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def world(qapp, tmp_path):
    from tests.qt.test_jobs_bar import World
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    yield w
    w.close()


@pytest.fixture
def dock(qapp):
    host = QWidget()
    host.setGeometry(240, 180, 1280, 120)                 # off the screen's corner: a point is mapped, never assumed
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.addStretch(1)
    d = frame.GoalDock(host)
    box.addWidget(d)
    host.show()
    d.set_goal(_goal())
    _settle()
    yield d
    host.close()


@pytest.fixture
def test_clock(qapp):
    """The clock on test time, motion not frozen (a motion test drives the time itself)."""
    from app.qt import freeze
    freeze.set_frozen(False)
    c = motion.clock()
    c.mode.set_setting("full")
    c.use_test_time()
    yield c
    c.use_real_time()
    c.mode.set_setting("follow")


# --- the bands and their edges ------------------------------------------------------------------------------------- #
def test_the_frame_has_no_separators_and_its_edges_stand_in_the_layout(window):
    # W3.1a: header and tabs one band, the footer the bottom one; the old 1 px separators are gone, the edges are
    # strips in the layout — never a sibling over a list (which turns off the list's fast scroll)
    central = window.centralWidget()
    assert central.findChildren(QFrame, "separator") == []
    layout = central.layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert order.index(window.edge_top) == order.index(window.findChild(QWidget, "tabbar")) + 1
    assert order[order.index(window.edge_top) + 1] is window.pages
    for name, page in window.page_widgets.items():
        strips = page.findChildren(frame.EdgeStrip)
        assert len(strips) == 1 and strips[0].side == "bottom", name
        lay = page.layout()
        assert lay.indexOf(strips[0]) >= lay.count() - 2, name       # at the page's foot (above Current's dock)


def test_the_top_edge_is_a_shadow_falling_onto_the_content_with_no_side_edges(window):
    strip = window.edge_top
    arr = rgb_array(strip.grab()).astype(int)
    mid = arr.shape[1] // 2
    top, bottom = arr[0, mid].sum(), arr[-1, mid].sum()
    ground = sum(int(v) for v in theme.parse(theme.colours()["bg"])[:3])
    assert top < bottom <= ground + 3                               # darkest under the band, fading to the ground
    assert (abs(arr[:, 0] - arr[:, mid]) <= 2).all()                # the same at the window's side: no side edge
    bottom_strip = window.page_widgets["current"].findChildren(frame.EdgeStrip)[0]
    arr = rgb_array(bottom_strip.grab()).astype(int)
    assert arr[-1, mid].sum() < arr[0, mid].sum()                   # the bottom band's shadow rises


def test_an_edge_is_baked_once_per_width_and_ratio(window):
    strip = window.edge_top
    built = strip.pictures
    strip.repaint()
    strip.repaint()
    assert strip.pictures == built                                  # repainting blits: nothing drawn afresh
    window.resize(1100, 800)
    _settle()
    strip.repaint()
    assert strip.pictures == built + 1


# --- the header's progress ------------------------------------------------------------------------------------------ #
def test_the_progress_hairline_draws_generates_share_and_is_whole_and_quiet_without_one(window):
    p = window.progress
    assert p.height() == 1 and p.y() == window.header.height() - 1 and p.width() == window.header.width()
    assert p.set(True, 50)
    arr = rgb_array(p.grab()).astype(int)
    w = arr.shape[1]
    assert arr[0, w // 4].sum() > arr[0, 3 * w // 4].sum() + 30     # lit up to half, not past it
    assert not p.set(True, 50)                                      # the same share: no repaint
    painted = p.paints
    p.set(False)
    assert p.paints == painted + 1 and not p.busy


# --- the level ▾ and its pop ---------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("failed, stale, journey, mark", [
    (False, False, False, None), (False, False, True, "journey"), (False, True, False, "stale"),
    (False, True, True, "stale"), (True, False, False, "failed"), (True, True, True, "failed"),
    (True, False, True, "failed"),
])
def test_the_level_mark_is_failed_then_stale_then_the_journey(failed, stale, journey, mark):
    assert frame.level_mark(failed, stale, journey) == mark


def test_the_pop_opens_from_the_level_and_esc_closes_it(world):
    level, pop = world.d.level, world.d.pop
    assert not pop.isVisible()
    level.click()
    assert wait_until(pop.isVisible)
    assert level.open and pop.geometry().top() >= level.mapTo(world.win.centralWidget(), level.rect().bottomLeft()).y()
    QTest.keyClick(world.win, Qt.Key.Key_Escape)
    assert not pop.isVisible() and world.win.isVisible() and not level.open
    level.click()
    assert wait_until(pop.isVisible)
    level.click()                                                   # the ▾ again closes it
    assert not pop.isVisible()


def test_a_press_outside_the_pop_closes_it(world):
    world.d.level.click()
    assert wait_until(world.d.pop.isVisible)
    QTest.mouseClick(world.win.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(20, 400))
    assert not world.d.pop.isVisible()


def test_the_pops_generate_and_journey_act_as_the_header_ones_did(world, monkeypatch):
    import os
    from app import path_utils, static_html_generator
    opened = []
    monkeypatch.setattr(static_html_generator, "open_report", lambda app_mode=False: opened.append(app_mode) or True)
    world.d.level.click()
    assert wait_until(world.d.pop.isVisible)
    world.d.generate.button.click()
    assert wait_until(lambda: world.controller.called("controller.request"))
    results = path_utils.get_user_file("results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, shell.JOURNEY_FILE), "w", encoding="utf-8") as f:
        f.write("<html></html>")
    world.start()
    assert wait_until(lambda: not world.d.journey.isHidden())
    world.d.journey.click()
    assert wait_until(lambda: opened)


def test_the_pop_shows_the_band_and_automatics_state(world):
    world.services.settings.set({"logic.selection.band": "rare"}, now=True)
    world.start()
    assert wait_until(lambda: world.d.level.text() == "Rare")
    assert world.d.pop.slider.value() == "rare" and not world.d.pop.auto_toggle.value()     # W3.1b: the slider
    assert world.d.level.toolTip().startswith(strings.BAR_LEVEL_TIP.format(band="Rare"))


def test_the_level_mark_follows_generate_and_the_journey(world):
    level = world.d.level
    world.controller.push(state=G.STALE)
    assert wait_until(lambda: level.mark == "stale")
    assert strings.LEVEL_MARKS["stale"] in level.toolTip()
    accent = theme.colours()["accent"]
    assert count(rgb_array(level.grab()), accent, 12) > 0
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).")
    assert wait_until(lambda: level.mark == "failed")
    assert count(rgb_array(level.grab()), theme.STATUS["warn"], 12) > 0          # amber when failed
    world.controller.push(state=G.CURRENT)
    assert wait_until(lambda: level.mark is None)
    world.win._poll.stop()
    world.status.providers["journey"] = lambda: True
    world.status.refresh_soon("journey")
    assert wait_until(lambda: level.mark == "journey")
    assert strings.LEVEL_MARKS["journey"] in level.toolTip()


# --- the vein -------------------------------------------------------------------------------------------------------- #
def test_the_vein_sits_under_the_current_tab(window):
    vein, tab = window.vein, window.tab_buttons["current"]
    assert (vein.left, vein.right) == vein.span(tab)
    assert vein.y() + vein.height() == window.findChild(QWidget, "tabbar").height()


def test_the_vein_travels_on_its_springs_reaches_the_tab_and_stops_the_clock(window, test_clock):
    vein = window.vein
    start = (vein.left, vein.right)
    target = vein.span(window.tab_buttons["finished"])
    window.show_tab("finished")
    assert window.pages.currentWidget() is window.page_widgets["finished"]      # the page is there at once
    assert vein.moving()
    test_clock.advance(32)
    lead = (vein.right - start[1]) / (target[1] - start[1])                   # rightwards: the right end leads
    tail = (vein.left - start[0]) / (target[0] - start[0])
    assert 0 < tail < lead < 1
    widest = 0
    for _ in range(100):
        test_clock.advance(16)
        assert vein.right <= target[1] + 1e-6 and vein.left <= target[0] + 1e-6  # never past
        widest = max(widest, vein.right - vein.left)
        if not vein.moving():
            break
    assert (vein.left, vein.right) == target and not vein.moving()
    assert not any(isinstance(a, motion.Spring) for a in test_clock.active)   # at rest: off the clock


def test_under_reduced_motion_the_vein_jumps(window, test_clock):
    test_clock.mode.set_setting("reduced")
    window.show_tab("finished")
    assert (window.vein.left, window.vein.right) == window.vein.span(window.tab_buttons["finished"])
    assert not window.vein.moving()


def test_the_vein_takes_a_fixed_set_of_shapes_cached_per_width(qapp):
    frame._VEINS.clear()
    a = frame.vein_picture(0, 60, 1.0)
    assert frame.vein_picture(0, 60, 1.0) is a                       # cached
    assert frame.vein_picture(1, 60, 1.0) is not a                   # another seed, another shape
    assert frame.vein_points(3, 100) == frame.vein_points(3, 100)    # seeded: the same shape every time
    top, bottom, nodes = frame.vein_points(3, 100)
    assert top[0].y() == pytest.approx(bottom[0].y()) and top[-1].y() == pytest.approx(bottom[-1].y())  # tapered
    assert len(nodes) == 3


def test_a_tab_switch_repaints_the_tab_bar_and_the_page_only(window):
    spy = Paints(window.header, window.footer, window.edge_top, window.progress, window.anki_mark, window.known)
    _settle()
    spy.reset()
    window.show_tab("finished")
    _settle()
    assert all(n == 0 for n in spy.seen.values()), spy.seen


def test_no_frame_part_repaints_on_window_activation(window):
    parts = (window.header, window.footer, window.edge_top, window.progress, window.vein, window.anki_mark,
             window.known)
    spy = Paints(*parts)
    _settle()
    spy.reset()
    for w in parts:
        QApplication.sendEvent(w, QEvent(QEvent.Type.WindowDeactivate))
        QApplication.sendEvent(w, QEvent(QEvent.Type.WindowActivate))
    _settle()
    assert all(n == 0 for n in spy.seen.values()), spy.seen


# --- the footer's corner ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("key, lit", [("syncing", True), ("synced", True), ("anki-closed", False), ("failed", False),
                                      ("off", False), (None, False)])
def test_the_emerald_is_lit_only_while_anki_answers(key, lit):
    assert frame.emerald_lit(key) is lit


def test_the_emerald_lit_and_dark_and_its_hover_says_which(window):
    mark = window.anki_mark
    mark.show_state("synced", strings.BAR_ANKI["synced"], strings.BAR_ANKI_TIP["synced"])
    _settle()
    assert mark.lit and not mark.isHidden()
    lit = rgb_array(mark.grab())
    assert count(lit, theme.GEM["emerald"][0], 6) > 10
    mark.show_state("anki-closed", strings.BAR_ANKI["anki-closed"], strings.BAR_ANKI_TIP["anki-closed"])
    _settle()
    dark = rgb_array(mark.grab())
    assert not mark.lit and count(dark, theme.GEM["emerald"][0], 6) == 0
    assert count(dark, theme.FRAME_COLOURS["emerald-dark-base"], 6) > 10
    assert strings.BAR_ANKI["anki-closed"] in mark.toolTip() and strings.BAR_ANKI_TIP["anki-closed"] in mark.toolTip()
    painted = mark.paints
    assert not mark.show_state("anki-closed", strings.BAR_ANKI["anki-closed"], strings.BAR_ANKI_TIP["anki-closed"])
    assert mark.paints == painted                                    # the same state: not repainted


def test_the_known_corner_and_its_milestone_hairline(window):
    assert frame.milestone(12345) == (12500, pytest.approx(2345 / 2500))
    assert frame.milestone(0) == (2500, 0.0) and frame.milestone(2500) == (5000, 0.0)
    k = window.known
    assert k.set_known(12345, strings.BAR_KNOWN_TIP)
    _settle()
    assert k.text() == "12,345 known" and not k.isHidden()
    assert "155 to 12,500" in k.toolTip() and k.toolTip().startswith(strings.BAR_KNOWN_TIP)
    arr = rgb_array(k.grab())
    assert count(arr, theme.FRAME_COLOURS["known-ink"], 40) > 0                 # the number, large and dim
    assert not k.set_known(12345, strings.BAR_KNOWN_TIP)                         # unchanged: no repaint
    assert k.set_known(None) and k.isHidden()


# --- the Goal dock ---------------------------------------------------------------------------------------------------- #
def test_the_hand_holds_at_most_nine_covers_turned_from_minus_eight_to_eight():
    assert frame.hand_angles(12) == [-8, -6, -4, -2, 0, 2, 4, 6, 8]
    assert frame.hand_angles(3) == [-8, -6, -4]


def test_the_dock_greys_its_hand_once_and_blits_its_picture(dock):
    dock.repaint()
    assert dock.pictures == 1 and dock.hands == 1
    dock.repaint()
    assert dock.pictures == 1                                        # a repaint blits
    dock.parentWidget().resize(1000, 120)
    _settle()
    dock.repaint()
    assert dock.pictures == 2 and dock.hands == 1                    # a new width: the hand is not greyed again
    hand, room = dock._hand
    cw, ch = theme.FRAME["dock-cover"]
    step = cw - theme.FRAME["dock-cover-overlap"]
    assert hand.width() == pytest.approx(step * 8 + cw + 2 * room, abs=1)   # nine covers, not twelve
    img = hand.toImage()
    greys = [img.pixelColor(x, y) for x in range(0, img.width(), 3) for y in range(0, img.height(), 3)]
    opaque = [c for c in greys if c.alpha() > 250]
    assert opaque and all(abs(c.red() - c.green()) <= 3 and abs(c.green() - c.blue()) <= 3 for c in opaque)


def test_the_dock_paints_goals_bar_with_its_lift(dock):
    arr = rgb_array(dock.grab())
    c = theme.colours()
    assert count(arr, c["goal-bar"], 2) > 1000 and count(arr, c["frame"], 2) > 1000
    assert count(arr, c["goal-bar-edge"], 3) > 100                  # its lit top edge (L14)


def test_the_wells_api(dock):
    assert dock.well_at(dock.mapToGlobal(QPoint(dock.width() // 2, dock.height() // 2))) is None   # no drag: none
    dock.begin_drag("current")
    assert dock.wells == ("soon", "goal", "finished")
    for name, r in dock.well_rects().items():
        assert dock.well_at(dock.mapToGlobal(r.center().toPoint())) == name
    assert dock.well_at(dock.mapToGlobal(QPoint(2, 2))) is None
    dock.end_drag()
    assert dock.wells == ()
    dock.begin_drag("goal")
    assert dock.wells == ("soon", "finished")                       # never Goal's own well for a drag from Goal
    assert frame.wells_for("goal") == ("soon", "finished") and frame.wells_for("soon") == ("soon", "goal", "finished")


def test_a_hovered_well_lights_and_opens_its_slot_and_an_unlit_one_says_why(dock):
    dock.begin_drag("current")
    dock.hover("soon")
    assert dock.lit == "soon" and dock.slot_width("soon") == theme.FRAME["dock-cover"][0]
    assert dock.toolTip() == strings.WELL_TIPS["soon"]
    dock.set_unlit("finished", strings.WELL_UNLIT_SPLIT)
    dock.hover("finished")
    assert dock.lit is None and dock.slot_width("finished") == theme.FRAME["well-slot"]
    assert dock.slot_width("soon") == theme.FRAME["well-slot"]      # the last one closed again
    assert dock.toolTip() == strings.WELL_UNLIT_SPLIT and dock.unlit_tip("finished") == strings.WELL_UNLIT_SPLIT
    dock.end_drag()
    assert dock.unlit_tip("finished") is None                       # one drag's: lit again for the next


def test_the_slot_opens_on_its_spring(dock, test_clock):
    dock.begin_drag("current")
    test_clock.advance(400)
    dock.hover("goal")
    test_clock.advance(16)
    w = dock.slot_width("goal")
    assert theme.FRAME["well-slot"] < w < theme.FRAME["dock-cover"][0]
    peak = 0
    for _ in range(100):
        test_clock.advance(16)
        peak = max(peak, dock.slot_width("goal"))
    assert peak > theme.FRAME["dock-cover"][0]                      # ζ .5: it swings past a little, then settles
    assert dock.slot_width("goal") == theme.FRAME["dock-cover"][0]


def test_the_wells_rise_on_the_clock_and_jump_under_reduced_motion(dock, test_clock):
    dock.begin_drag("current")
    assert dock.rise == theme.MOTION["buckets-rise"]
    test_clock.advance(theme.MOTION["buckets"] / 2)
    assert 0 < dock.rise < theme.MOTION["buckets-rise"]
    test_clock.advance(theme.MOTION["buckets"])
    assert dock.rise == 0
    dock.end_drag()
    test_clock.advance(theme.MOTION["buckets"] + 16)
    assert dock.wells == ()
    test_clock.mode.set_setting("reduced")
    dock.begin_drag("current")
    assert dock.rise == 0 and dock.wells


def test_gap2_the_bars_new_count_and_name_come_at_the_drop_under_the_falling_wells(dock, test_clock):
    """Gap 2 (M4.1 P3): the bar's new count showed only once the wells had fallen (260 ms after the drop), its
    accessible name too. Now both come at the drop; the wells fall over the bar as a look only."""
    dock.begin_drag("current")
    test_clock.advance(theme.MOTION["buckets"] + 16)                 # risen
    dock.end_drag()                                                  # the drop: the wells begin to fall
    new = _goal(13, 140)
    dock.set_goal(new)                                               # the drop's numbers (drag.without → the shell)
    assert dock.wells                                                # still falling
    assert dock.accessibleName() == strings.GOAL_ACCESSIBLE.format(name=strings.GOAL_NAME, line=new.line)
    assert dock.toolTip() == new.tip
    test_clock.advance(theme.MOTION["buckets"] / 2)
    assert dock.wells and 0 < dock.rise < theme.MOTION["buckets-rise"]
    arr = rgb_array(dock.grab())
    assert dock._key[0] == frame._bar_of(new)                       # the bar drawn for the new count, mid-fall
    assert count(arr, theme.colours()["goal-bar"], 2) > 500          # and seen above the falling wells
    test_clock.advance(theme.MOTION["buckets"])
    assert dock.wells == () and dock.accessibleName().endswith(new.line)


def test_a_dock_hover_repaints_the_dock_only(qapp, dock):
    host = dock.parentWidget()
    other = QWidget(host)
    other.setGeometry(0, 0, host.width(), 40)
    other.show()
    dock.begin_drag("current")
    _settle()
    spy = Paints(host, other, dock)
    spy.reset()
    dock.hover("soon")
    _settle()
    assert spy.seen[dock] >= 1 and spy.seen[other] == 0 and spy.seen[host] == 0


def test_the_dock_takes_the_goal_the_strip_takes_from_the_readers_view(qapp):
    from tests.qt.test_current import open_on
    from tests.fixtures import window_seed
    seed = window_seed.build(files=window_seed.SMALL, language="ja")
    win, services = open_on(qapp, seed)
    try:
        page = win.page_widgets["current"]
        assert wait_until(lambda: win.dock.goal is not None)
        assert win.dock.goal == page.view_model.goal and page.isAncestorOf(win.dock)
        assert win.dock.isVisibleTo(win) and win.dock.toolTip() == page.view_model.goal.tip
        covers = frame.well_covers(page.view_model)
        assert covers["goal"] == tuple(page.view_model.goal.covers[-theme.FRAME["well-covers"]:])
        win.show_tab("finished")
        assert not win.dock.isVisible()                             # Current only (it lives in the Current page)
    finally:
        win.close()
        services.shutdown(0.5)


# --- W3.1a: the footer's quiet functions, the start path, the cover treatment --------------------------------------- #
def test_the_level_mark_shows_failed_over_stale_over_the_journey_all_at_once(world):
    """With the journey's sentences owed all along, a failed Generate is the amber mark, a stale one the accent mark,
    and only with Generate clean is the mark the journey's (a failure is never hidden behind the other two)."""
    level, win = world.d.level, world.win
    win._poll.stop()
    world.status.providers["journey"] = lambda: True
    world.status.refresh_soon("journey")
    assert wait_until(lambda: level.mark == "journey")
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).")
    assert wait_until(lambda: level.mark == "failed")
    arr = rgb_array(level.grab())
    assert count(arr, theme.STATUS["warn"], 12) > 0 and strings.LEVEL_MARKS["failed"] in level.toolTip()
    world.controller.push(state=G.STALE)
    assert wait_until(lambda: level.mark == "stale")
    assert count(rgb_array(level.grab()), theme.STATUS["warn"], 12) == 0
    assert strings.LEVEL_MARKS["stale"] in level.toolTip() and strings.LEVEL_MARKS["journey"] not in level.toolTip()
    world.controller.push(state=G.CURRENT)
    assert wait_until(lambda: level.mark == "journey")


@pytest.mark.parametrize("sync, auto, key", [(None, False, "off"), ("syncing", True, "syncing"),
                                             ("synced", True, "synced"), ("anki-closed", True, "anki-closed"),
                                             ("failed", True, "failed")])
def test_each_anki_state_has_its_emerald_and_its_hover_says_which(world, sync, auto, key):
    """A failed, closed or switched-off Anki is the dark emerald; its hover says which, in the sync's own words."""
    from app.services import automation as A
    mark = world.d.anki
    world.services.settings.set({"anki_sync_auto": auto}, now=True)
    if sync is not None:
        world.automation.push(sync=sync, message="AnkiConnect didn't answer")
    assert wait_until(lambda: mark.key == key)
    assert mark.lit is (key in ("syncing", "synced")) and not mark.isHidden()
    assert strings.BAR_ANKI[key] in mark.toolTip()
    tip = strings.BAR_ANKI_TIP[key]
    assert (tip.format(message="AnkiConnect didn't answer") if key == "failed" else tip) in mark.toolTip()
    assert mark.toolTip() and mark.accessibleName()


def test_the_covers_grey_is_lighter_for_a_generated_cover_than_for_real_art():
    assert frame.cover_grey(generated=False) == theme.FRAME["dock-cover-grey"] == 0.62     # the reference's, real art
    assert 0.85 <= frame.cover_grey(generated=True) <= 1.0                                # S4: lighter


def _hand_luminance(dock):
    """The mean luminance (0–255) of the hand's opaque pixels, greyed as the dock draws them."""
    import numpy as np
    dock._hand_key = None
    hand, _room = dock._hand_picture(1.0)
    img = hand.toImage()
    arr = rgb_array(img)
    alpha = np.array([[img.pixelColor(x, y).alpha() for x in range(img.width())] for y in range(img.height())])
    luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    return float(luma[alpha > 250].mean())


HAND_FLOOR = 40          # 0–255: at the reference's .62 a generated hand measures ~32 (three black tiles); at .9, ~46


def test_a_generated_cover_in_the_hand_stays_above_the_luminance_floor(dock, monkeypatch):
    """S4: the generated covers are already dark gradients — greyed at the reference's .62 they read as black tiles,
    their characters gone. Greyed lighter, the hand stays above a floor; the floor is one the old value falls under."""
    assert _hand_luminance(dock) >= HAND_FLOOR
    monkeypatch.setattr(frame, "F", dict(theme.FRAME, **{"dock-cover-grey-generated": theme.FRAME["dock-cover-grey"]}))
    assert _hand_luminance(dock) < HAND_FLOOR                                  # the floor tells the two apart
