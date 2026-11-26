"""The feature guide in the window (Hoshi-S, Sonic 2026-11-12, part of the launch; spec: the 3.0 planning folder,
`tracks/window/work/feature-guide-2026-11-12/SPEC.md`): the ✦ beside the ?, its glow, its panel and *Show me*.

What a wrong answer would cost a learner: a ✦ that glows after every start (a nag) or never goes out; a panel that
reads files on the window's thread (a stutter as it opens); Esc closing the window instead of the panel; their own
kind of item buried; *Show me* going nowhere, or silently doing nothing.
"""
import json
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QLabel

from app.qt import guide as guide_ui, motion, strings
from app.services import guide
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import world  # noqa: F401  (`world`: the fixture — a window with its duties)

NOTES = {"version": "3.0.4", "date": "2026-11-12", "items": [
    {"id": "zh-cards", "kind": "new", "text": "エピソードからカードを作れる。", "for": ["miner"],
     "where": "settings:text_size"},
    {"id": "piyo-help", "kind": "new", "text": "Piyo に Surasura のことを聞ける。", "for": ["piyo"],
     "where": "settings:practice_ai"},
    {"id": "faster", "kind": "tweak", "text": "検索が速くなった。", "for": ["everyone"]},
    {"id": "skip-word", "kind": "tweak", "text": "Anki が受け付けない単語はスキップできる。", "for": ["miner"],
     "where": "tab:needs"},
    {"id": "report", "kind": "fix", "text": "報告の画面が短い画面に収まる。", "for": ["everyone"]},
    {"id": "words-split", "kind": "fix", "text": "という の切り方が正しくなった。", "for": ["miner"]}]}


@pytest.fixture
def notes(tmp_path, monkeypatch):
    """The notes in a folder of the test's, this window's version 3.0.4, and the looks counted by thread."""
    folder = tmp_path / "whats_new"
    folder.mkdir()
    (folder / "3.0.4.json").write_text(json.dumps(NOTES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(guide, "folder", lambda: str(folder))
    monkeypatch.setattr(guide, "current_version", lambda: "3.0.4")
    threads = []
    real = guide.look

    def look(*args, **kwargs):
        threads.append(threading.current_thread())
        return real(*args, **kwargs)
    monkeypatch.setattr(guide, "look", look)
    return threads


def _looked(world, notes, n=1):
    world.win._guide_look()
    panel = world.d.guide_panel
    assert wait_until(lambda: len(notes) >= n and panel.look is not None and not panel.building())


def test_the_star_waits_for_a_look_then_sits_just_left_of_the_question_mark_glowing(world, notes):
    g = world.d.guide
    assert g.isHidden()                                                     # nothing read yet: no ✦
    _looked(world, notes)
    assert wait_until(lambda: g.isVisible() and g.glow)
    row = world.win.header.layout()
    assert row.indexOf(g) == row.indexOf(world.d.help) - 1
    assert g.toolTip() == strings.GUIDE_TIP and g.accessibleName() == strings.GUIDE_GLOW_NAME
    assert all(t is not threading.main_thread() for t in notes)            # the files read on a worker


def test_opening_ends_the_glow_at_once_marks_it_seen_and_the_next_start_has_no_glow(world, notes):
    _looked(world, notes)
    g, panel = world.d.guide, world.d.guide_panel
    g.click()
    assert wait_until(panel.isVisible) and not g.glow                       # at once, before any worker answers
    assert wait_until(lambda: guide.read_state().get("seen") == "3.0.4")
    panel.close()
    world.win._guide_look()                                                 # the next start's look
    assert wait_until(lambda: len(notes) >= 3)
    QApplication.processEvents()
    assert not g.glow and g.isVisible()                                     # seen: no glow, still there to read


def test_an_open_with_the_same_answer_builds_nothing_again(world, notes):
    _looked(world, notes)
    panel = world.d.guide_panel
    assert panel.builds == 1
    for _ in range(2):
        count = len(notes)
        world.d.guide.click()
        assert wait_until(lambda: panel.isVisible() and len(notes) > count)
        QApplication.processEvents()
        panel.close()
    assert panel.builds == 1                                                 # the same answer: nothing rebuilt (S19)


def test_each_item_is_one_line_yours_first_and_every_fix_folds_into_one_line(world, notes):
    # Sonic, 2026-11-12: "everything earns its place" — one plain line an item, Show me only on something to try
    world.win.services.settings.set({"connect_enabled": True})
    _looked(world, notes)
    panel = world.d.guide_panel
    world.d.guide.click()
    assert wait_until(panel.isVisible)
    assert panel.heading.text() == strings.GUIDE_HEADING_ONE.format(version="3.0.4")    # one release: no version line
    shown = [c for c in panel.cards if c.isVisibleTo(panel)]
    assert [c.item.id for c in shown] == ["zh-cards", "skip-word", "piyo-help"]          # Connect on: the miner's first
    groups = [w for w in panel.body.findChildren(type(panel.heading)) if w.objectName() == "guidegroup"]
    assert [g.text() for g in groups] == [strings.GUIDE_FOR_YOU]                         # it explains the order, once
    (fold, fixes, _open), = panel.folds                                     # leads nowhere: folded (Kantan-X rule 2)
    assert [c.item.id for c in fixes] == ["words-split", "faster", "report"]
    assert not any(c.isVisibleTo(panel) for c in fixes)
    assert fold.text() == strings.GUIDE_FIXES.format(n=3) and fold.toolTip()
    fold.click()
    assert all(c.isVisibleTo(panel) for c in fixes) and fold.text() == strings.GUIDE_FIXES_OPEN.format(n=3)
    assert all(c.show_me is not None for c in panel.cards if c not in fixes)            # every shown item leads somewhere
    for card in panel.cards:
        assert card.text.text() == card.item.text and card.accessibleName() == card.item.text
        assert (card.show_me is not None) == bool(card.item.where)
        if card.show_me is not None:
            assert card.show_me.toolTip() and card.show_me.accessibleName()
    panel.close()


def test_esc_closes_the_panel_and_never_the_window(world, notes):
    _looked(world, notes)
    world.d.guide.click()
    panel = world.d.guide_panel
    assert wait_until(panel.isVisible)
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: not panel.isVisible())
    assert world.win.isVisible()


def test_the_panel_stays_inside_a_short_window_and_scrolls(world, notes):
    _looked(world, notes)
    world.win.resize(1000, 620)                                              # the window's least size
    world.d.guide.click()
    panel = world.d.guide_panel
    assert wait_until(panel.isVisible)
    for entry in panel.folds:
        if not entry[2]:
            entry[0].click()
    parent = panel.parentWidget()
    assert panel.geometry().bottom() <= parent.height() and panel.geometry().right() <= parent.width()
    assert panel.geometry().left() >= 0
    panel.close()


def test_show_me_reveals_a_setting(world, notes, monkeypatch):
    asked = []
    monkeypatch.setattr(world.win, "open_setting", lambda target: asked.append(target))
    _looked(world, notes)
    world.d.guide.click()
    panel = world.d.guide_panel
    assert wait_until(panel.isVisible)
    card = next(c for c in panel.cards if c.item.id == "zh-cards")
    card.show_me.click()
    assert asked == ["text_size"] and not panel.isVisible()                  # a row every learner's Settings shows


def test_show_me_washes_a_control_and_a_tab_with_nothing_in_it_says_so(world, notes, monkeypatch):
    washed = []
    monkeypatch.setattr(motion, "wash", lambda widget, radius=0.0, ms=None: washed.append(widget))
    world.win.guide_show_me("control:report")
    assert washed == [world.win.report_button]              # (recorded: the freeze switch ends a real wash at once)
    assert world.win.tab_buttons["needs"].isHidden()                         # Needs you lists nothing here
    world.win.show_tab("finished")                                           # (show_tab's own fallback is Current)
    before = world.win.current_tab()
    world.win.guide_show_me("tab:needs")
    assert wait_until(lambda: world.win.bar_line.accessibleDescription() == strings.GUIDE_NOT_HERE)
    assert world.win.current_tab() == before                                 # a hidden tab is never opened
    world.win.guide_show_me("tab:finished")
    assert world.win.current_tab() == "finished" and washed[-1] is world.win.tab_buttons["finished"]
    world.win.guide_show_me("control:nope")
    assert len(washed) == 2


def test_the_glow_is_painted_still_with_no_motion_on_the_clock(world, notes):
    _looked(world, notes)
    g = world.d.guide
    assert wait_until(lambda: g.glow)
    QApplication.processEvents()
    before = g.paints
    for _ in range(5):
        QApplication.processEvents()
    assert g.paints == before                                                # nothing repaints it while it rests
    assert not motion.clock()._timer.isActive()                              # and nothing runs on the clock for it


def test_release_name_says_the_version_and_its_day():
    rel = guide.Release("3.0.4", "2026-11-12", ())
    assert guide_ui.release_name(rel) == "Surasura 3.0.4 · 12 Nov"
    assert guide_ui.release_name(guide.Release("3.0.4", "", ())) == "Surasura 3.0.4"


# --- the adversary's round (2026-11-12) ------------------------------------------------------------------------ #
def _open(world):
    world.d.guide.click()
    assert wait_until(world.d.guide_panel.isVisible)
    return world.d.guide_panel


def test_an_open_panel_never_changes_under_the_learner_and_takes_the_newer_answer_once_closed(world, notes):
    older = dict(NOTES, version="3.0.3", date="2026-11-11")
    with open(os.path.join(guide.folder(), "3.0.3.json"), "w", encoding="utf-8") as f:
        json.dump(older, f, ensure_ascii=False)
    guide.write_state({"seen": "3.0.2"})                                    # two updates skipped: both show
    _looked(world, notes)
    panel = _open(world)
    shown = [c.item.version for c in panel.cards]
    assert set(shown) == {"3.0.4", "3.0.3"} and panel.builds == 1
    assert wait_until(lambda: panel._waiting is not None)                  # the seen mark's newer answer, held
    assert guide.read_state().get("seen") == "3.0.4"
    assert [c.item.version for c in panel.cards] == shown and panel.builds == 1     # still what they opened
    panel.close()
    assert wait_until(lambda: panel.builds == 2)                            # the newer answer, once closed
    assert {c.item.version for c in panel.cards} == {"3.0.4"}


def test_the_glow_never_relights_with_the_panel_open_and_an_older_answer_is_dropped(world, notes):
    _looked(world, notes)
    look = world.d.guide_panel.look._replace(glow=True)
    _open(world)
    world.win._guide_got((world.win._guide_asked, look, None, []))
    assert not world.d.guide.glow                                           # open: never lit again
    world.d.guide_panel.close()
    world.win._guide_got((world.win._guide_asked - 1, look, None, []))      # an older look, arriving late
    assert not world.d.guide.glow


def test_tab_stays_in_the_panel_and_esc_gives_the_keyboard_back_to_the_star(world, notes):
    _looked(world, notes)
    panel = _open(world)
    seen = set()
    for _ in range(6):
        panel.focusNextPrevChild(True)
        seen.add(QApplication.focusWidget())
    assert all(w is panel.scroll or panel.isAncestorOf(w) for w in seen) and panel.scroll in seen
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: not panel.isVisible())
    assert QApplication.focusWidget() is world.d.guide


def test_a_press_elsewhere_closes_the_panel(world, notes):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    _looked(world, notes)
    panel = _open(world)
    target = world.win.tab_buttons["current"]
    at = QPointF(target.rect().center())
    press = QMouseEvent(QEvent.Type.MouseButtonPress, at, target.mapToGlobal(at), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, press)
    assert wait_until(lambda: not panel.isVisible())


def test_show_me_for_a_settings_row_this_learner_doesnt_have_says_so_and_lights_nothing_else(world, notes):
    world.win.services.settings.set({"connect_enabled": False})
    tab = world.win.current_tab()
    world.win.guide_show_me("settings:connect_trust_timing")                # Connect's row: hidden while it's off
    assert world.win.bar_line.accessibleDescription() == strings.GUIDE_NOT_HERE
    assert world.win.current_tab() == tab


def test_setup_running_is_a_new_pc_and_the_star_doesnt_glow(world, notes):
    world.win.services.setup_open.set()
    try:
        _looked(world, notes)
        QApplication.processEvents()
        assert world.d.guide.isVisible() and not world.d.guide.glow
        assert guide.read_state().get("seen") == "3.0.4"
    finally:
        world.win.services.setup_open.clear()


def test_the_star_keeps_its_room_while_hidden_so_the_header_never_shifts(world, notes):
    assert world.d.guide.isHidden() and world.d.guide.sizePolicy().retainSizeWhenHidden()


def test_a_panel_that_fits_shows_no_scroll_bar_and_folded_lines_are_quiet_and_lead_nowhere(world, notes):
    # the shipped 3.0.4 notes: lines long enough to wrap — a body sized by its unwrapped hints showed a bar here
    shipped = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           guide.FOLDER, "3.0.4.json")
    with open(shipped, encoding="utf-8") as src, open(os.path.join(guide.folder(), "3.0.4.json"), "w",
                                                      encoding="utf-8") as dst:
        dst.write(src.read())
    world.win.services.settings.set({"connect_enabled": True})
    _looked(world, notes)
    panel = _open(world)
    for entry in panel.folds:
        entry[0].click()
    QApplication.processEvents()
    room = panel.parentWidget().height() - panel.geometry().top() - guide_ui.EDGE
    assert panel.height() < room                                            # it fits (1280 × 800) …
    assert panel.scroll.verticalScrollBar().maximum() == 0                  # … so every line in view, no bar
    assert panel.body.height() == panel.scroll.viewport().height()
    for _fold, fixes, _shown in panel.folds:
        assert all(c.objectName() == "guidefix" and c.show_me is None for c in fixes)
    panel.close()


def _own_ms():
    """The window's thread's own CPU time so far, ms: what its steps themselves cost, never the time the machine gave
    to someone else meanwhile (another process on a shared runner, a worker holding Python's lock in a C call). On
    Windows its cycle counter (`hud.Counters`, the HUD's own; `time.thread_time` ticks at 15.6 ms there), elsewhere
    `time.thread_time`; a counter that won't read: the wall clock, as before."""
    import time
    from app.qt import hud
    counters = hud.Counters(calibrate=False)
    if counters.ok:
        # the clock rate from the least-interrupted of three short spins: an interrupted spin reads it low
        counters.mhz = max(counters._calibrate() or 0 for _ in range(3)) or None
        if counters.mhz and counters.sample():
            return lambda: counters.ms(counters.sample()[1])
        return lambda: time.perf_counter() * 1000
    return lambda: time.thread_time() * 1000


# The machine's own speed for the 4 ms below: a fixed piece of the same kind of work (one paragraph's lines wrapped
# at 20 widths, as `place()` and the pieces wrap theirs), timed by the same clock, the least of 5 (a calibration's
# least-disturbed reading, as `_own_ms`'s clock rate is). REF_DESKTOP_MS is that reading on the desktop the guide's
# 4 ms is set on (2026-11-22: 3.155-3.163 ms in five runs). A slower machine, or a clock that reads its cycles slow,
# reads the reference slower by the same ratio, and only then is the budget scaled by it (never below 4 ms): on
# GitHub's runner the last place() read 4.02 ms, here 0.8-1.2 ms — its work 3.5 times slower, no piece at the limit.
REF_TEXT = "この本は、毎日少しずつ読むことで、知らない言葉が自然に覚えられるように作られています。 " * 6
REF_DESKTOP_MS = 3.16


def _speed(own_ms):
    """How many times slower than the desktop this machine does the reference (1.0 at most as fast)."""
    label = QLabel(REF_TEXT)
    label.setWordWrap(True)
    label.ensurePolished()
    best = None
    for _ in range(5):
        t0 = own_ms()
        for w in range(200, 420, 11):
            label.heightForWidth(w)
        best = min(best, own_ms() - t0) if best is not None else own_ms() - t0
    label.deleteLater()
    return max(1.0, best / REF_DESKTOP_MS)


# A piece's or a place's cost is the least of QUIET_BUILDS builds of the same body (TEST-FLAKES, FLAKES.md): a single
# reading carries whatever slowed the thread's own clock meanwhile, and the reds read 4.02-4.61 ms of a 4 ms budget on
# GitHub's runners (a VM's stolen time counts as the thread's own cycles) and beside other runs here (all cores busy:
# a lower clock, so the same work counts more cycles). A piece or a place that really grew costs that much in every
# build, so the least is its cost: the estimator `_speed`'s reference and `_own_ms`'s clock rate already use.
QUIET_BUILDS = 3


def _quiet_costs(panel, own_ms, build, monkeypatch, budget, builds=QUIET_BUILDS):
    """(each piece's least cost, the first place()'s least cost) over up to `builds` builds, ms of the window's thread's
    own time. `build()` asks the panel for the same body again; every build makes the same pieces, one a turn. It stops
    once every least is under `budget` (the least is never above the first: the same verdict, fewer builds)."""
    real_step = panel._step
    runs = []

    def step(token):
        t0 = own_ms()
        real_step(token)
        runs[-1].append(own_ms() - t0)
    monkeypatch.setattr(panel, "_step", step)
    places = []
    for _ in range(builds):
        runs.append([])
        build()
        assert panel.building()                                             # nothing built in the asking turn
        assert wait_until(lambda: not panel.building())
        t0 = own_ms()
        panel.place()
        places.append(own_ms() - t0)
        assert len({len(r) for r in runs}) == 1, [len(r) for r in runs]     # the same pieces at every build
        least = [min(costs) for costs in zip(*runs)]
        if max(least) < budget and min(places) < budget:
            break
    return least, min(places)


def test_no_slice_of_a_new_answer_passes_4_ms_and_a_newer_answer_cancels_the_rest(world, notes, monkeypatch):
    # The lead, 2026-11-12: the 4 ms rule strict. Two releases, the shipped notes (wrapping lines): the body is built one
    # piece a turn — each piece, and the place after the last, under 4 ms on the window's thread.
    # The 4 ms is the Qt guide's step budget (§ 4: no step on the GUI thread over 4 ms; § 7: this desktop's bar, the
    # laptop's ÷ 2.5): what a piece costs the window's thread. So each piece is timed by that thread's own CPU time
    # (`_own_ms`), not the wall clock: on GitHub's runner a piece of ~0.4 ms here (the largest ~1 ms) once read 5.47 ms
    # of wall time, the thread taken away mid-piece. A piece that grew (a release in one turn) costs the thread itself,
    # on any machine; each cost is the least of three builds (`_quiet_costs`, TEST-FLAKES). Here at 17 releases' notes
    # (2026-11-26): the pieces ~1.1 ms, the first place() 3.1-3.4 ms: it lays out every row, ~0.19 ms a release shown.
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), guide.FOLDER)
    releases = guide.read_notes(here)
    look = guide.Look("3.0.4", tuple(guide.arrange(r, {"everyone", "ja", "miner", "books"}) for r in releases), True)
    panel = world.d.guide_panel
    own_ms = _own_ms()
    budget = 4.0 * _speed(own_ms)                                           # 4 ms here; scaled on a slower machine
    panel.slices.clear()
    panel.set_look(look)
    assert panel.building() and not panel.cards                             # nothing built in the asking turn
    assert wait_until(lambda: not panel.building())
    assert len(panel.slices) >= len(panel.cards)                            # one piece a turn

    def again():
        panel.look = None                                                   # (the same releases rebuild nothing)
        assert panel.set_look(look)
    pieces, placed = _quiet_costs(panel, own_ms, again, monkeypatch, budget)
    assert max(pieces) < budget, (max(pieces), budget)
    assert placed < budget, (placed, budget)
    built = panel.builds
    panel.set_look(look._replace(releases=look.releases[:1]))               # a newer answer mid-way …
    QApplication.processEvents()
    panel.set_look(look)                                                     # … and another: only the last finishes
    assert wait_until(lambda: not panel.building())
    QApplication.processEvents()
    assert panel.builds == built + 1 and len({c.item.version for c in panel.cards}) == len(look.releases)


def _releases(n):
    """A look with `n` releases' notes: the shipped ones, repeated past the last (a learner who skipped many
    releases sees every one since the last they saw)."""
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), guide.FOLDER)
    shown = tuple(guide.arrange(r, {"everyone", "ja", "miner", "books"}) for r in guide.read_notes(here))
    return guide.Look("3.0.4", (shown * (n // len(shown) + 1))[:n], True)


def test_the_first_place_and_the_open_cost_the_same_at_5_17_and_40_releases(world, notes):
    # GUIDE-LAYOUT (3.0.20): the first place() after a build walked every row for its height and the open laid out and
    # showed every row: 1.1 / 3.2 / 7.0 ms of place() and 2.0 / 5.5 / 12.5 ms of show() at 5 / 17 / 40 releases'
    # notes here, ~0.19 ms more a release; past ~21 releases place() alone passed the guide's 4 ms. A learner who
    # skipped releases sees them all. Now the heights are kept as each row lands and only the first screen's rows
    # are shown at the open: both costs stay flat however many releases are shown. Each cost is the least of
    # QUIET_BUILDS builds of the thread's own time (as `_quiet_costs`), the margin scaled on a slower machine.
    panel = world.d.guide_panel
    panel.blockSignals(True)                                # (an open asks no new look here: the same body each time)
    own_ms = _own_ms()
    margin = 1.0 * _speed(own_ms)
    costs = {}
    for n in (5, 17, 40):
        look = _releases(n)
        place = show = None
        for _ in range(QUIET_BUILDS):
            panel.look = None
            assert panel.set_look(look)
            assert wait_until(lambda: not panel.building())
            t0 = own_ms()
            panel.place()
            t1 = own_ms()
            panel.show()
            t2 = own_ms()
            panel.hide()
            QApplication.processEvents()
            place = t1 - t0 if place is None else min(place, t1 - t0)
            show = t2 - t1 if show is None else min(show, t2 - t1)
        costs[n] = (round(place, 2), round(show, 2))
    panel.blockSignals(False)
    assert costs[40][0] - costs[5][0] < margin, costs          # place(): flat
    assert costs[40][1] - costs[5][1] < margin, costs          # the open's show(): flat


def _rows(panel):
    col = panel.body.layout()
    return [w for w in (col.itemAt(n).widget() for n in range(col.count())) if w is not None]


def _same_as_all_shown(panel):
    """The body as if every row were shown at once: its kept heights at both widths are the walk's, no room held, and
    each shown row where it would be."""
    m = panel.body.layout().contentsMargins()
    for cw in panel._ws:
        width = cw + m.left() + m.right()
        assert panel._content_height(width) == panel._walk_height(width), cw
    assert panel._spacer.sizeHint().height() == 0
    QApplication.processEvents()
    _in_place(panel)
    assert panel.body.height() == panel._walk_height(panel.body.width())


def _in_place(panel):
    """Each shown row at its kept height, right under the one before (the column's spacing between shown rows, a fixed
    space its own px): a wrong room held for the waiting rows squeezes or stretches the rows above it."""
    col = panel.body.layout()
    m = col.contentsMargins()
    at = panel._ws.index(panel._column_width())
    y, after = m.top(), False
    for n in range(col.count()):
        item = col.itemAt(n)
        w = item.widget()
        if w is None:
            y += item.spacerItem().sizeHint().height() if item.spacerItem() is not None else 0
            continue
        if w.isHidden():
            continue
        y += col.spacing() if after else 0
        assert (w.y(), w.height()) == (y, w._heights[at]), (n, w.y(), y)      # where it would have been
        y, after = y + w.height(), True


def test_rows_past_the_first_screen_wait_then_come_in_place_and_a_fold_opens_among_them(world, notes,
                                                                                              monkeypatch):
    # GUIDE-LAYOUT: what a learner sees is the same panel: the rows past the window's first screen wait hidden with
    # their room held (the scroll bar the same), come a batch a turn once it is open, land where they would have been,
    # and a close hides those below the screen again for the next open. A fold pressed before they came opens in place
    # (its fixes counted in the height) and they still come. Each batch's turn and the close's hiding stay in 4 ms.
    panel = world.d.guide_panel
    panel.blockSignals(True)
    own_ms = _own_ms()
    budget = 4.0 * _speed(own_ms)
    rounds, paused = [[]], [False]                  # each turn's cost, one list a round of open + close
    for name in ("_reveal", "_hide_below"):
        def timed(*args, _real=getattr(panel, name)):
            if paused[0]:
                return
            t0 = own_ms()
            _real(*args)
            rounds[-1].append(own_ms() - t0)
        monkeypatch.setattr(panel, name, timed)
    panel.set_look(_releases(40))
    assert panel.building() and not panel.cards
    assert wait_until(lambda: not panel.building())
    assert panel._ws and panel.cards
    held = panel._held_rows()
    assert held and all(w.isHidden() for w in held)                           # past the first screen: waiting
    assert len([w for w in _rows(panel) if not w.isHidden()]) < len(held)     # (most of the body)
    panel.place()
    want = panel.body.height()
    paused[0] = True
    panel.open()
    QApplication.processEvents()
    _in_place(panel)                                                          # the first frame: the screen's rows
    assert panel._spacer.sizeHint().height() > 0 and panel._held_rows() == held
    paused[0] = False
    panel._reveal(panel._turn)
    assert wait_until(lambda: not panel._held_rows())                         # a batch a turn, open
    assert not any(w.isHidden() for w in held)
    _same_as_all_shown(panel)
    assert panel.body.height() == want                                        # the room held was theirs exactly
    def closed():                                   # the close's hiding done: what waits is below the screen
        panel.hide()
        assert wait_until(lambda: all(w.y() <= panel.scroll.verticalScrollBar().value() + panel._cut
                                      for w in panel._later[:panel._shown_to]))
        again = panel._held_rows()
        assert again and all(w.isHidden() for w in again)
        return again
    again = closed()
    assert abs(len(again) - len(held)) <= 1                                   # (the same rows, to the boundary row)
    rounds.append([])
    panel.open()                                                              # a second round: each turn's least
    assert wait_until(lambda: not panel._held_rows())
    again = closed()
    least = [min(a, b) for a, b in zip(*rounds)]
    assert len(least) >= 6 and max(least) < budget, (rounds, budget)          # (40 releases: many batches each way)
    paused[0] = True
    panel.open()
    QApplication.processEvents()
    entry = next(e for e in panel.folds if not e[0].isHidden())               # a fold on the first screen, pressed
    assert entry[1] and panel._held_rows() == again
    entry[0].click()                                                          # before the rest came
    QApplication.processEvents()
    assert all(not c.isHidden() for c in entry[1]) and panel._held_rows() == again  # its fixes in place, the rest wait
    _in_place(panel)
    paused[0] = False
    panel._reveal(panel._turn)
    assert wait_until(lambda: not panel._held_rows())
    _same_as_all_shown(panel)
    panel.hide()
    QApplication.processEvents()
    assert not panel._held_rows()                                             # (a fold open: they stay)
    panel.open()
    entry[0].click()                                                          # ... and closed again
    assert all(c.isHidden() for c in entry[1])
    _same_as_all_shown(panel)
    bar = panel.scroll.verticalScrollBar()
    assert bar.maximum() > 2 * panel._cut
    bar.setValue(bar.maximum() // 2)                                          # closed halfway down: only the rows
    panel.hide()                                                              # below what it showed wait
    assert wait_until(lambda: all(w.y() <= bar.value() + panel._cut for w in panel._later[:panel._shown_to]))
    assert 0 < len(panel._held_rows()) < len(held)                            # (the bottom up, a batch a turn: done)
    assert all(w.isHidden() and w.y() > bar.value() + panel._cut for w in panel._held_rows())
    assert not any(w.isHidden() for w in panel._later[:panel._shown_to])
    panel.open()
    assert bar.value() == bar.maximum() // 2                                  # where it was left
    assert wait_until(lambda: not panel._held_rows())
    _same_as_all_shown(panel)
    panel.hide()
    panel.blockSignals(False)


def test_opened_while_its_body_is_still_being_built_every_row_still_comes(world, notes):
    # GUIDE-LAYOUT (its review): the ✦ pressed while a new answer's pieces are still landing. The rows made after the
    # reveal caught up waited for the next open (the panel cut short, blank room under it): now the build's last piece
    # starts their turn too.
    panel = world.d.guide_panel
    panel.blockSignals(True)
    panel.set_look(_releases(17))
    assert wait_until(lambda: len(panel._later) >= 1)                         # past the first screen, still building
    assert panel.building()
    panel.open()
    assert wait_until(lambda: not panel.building() and not panel._held_rows())
    assert panel._later and not any(w.isHidden() for w in panel._later)
    _same_as_all_shown(panel)
    panel.hide()
    panel.blockSignals(False)
