"""Reduced motion everywhere (M4.1 row 1; the window's spec 05 §5.10, the Qt GUI guide *Motion*): **the sweep**.

With `app_motion = reduced` and the freeze switch off (the clock on its test time: no test waits on real time for a
motion), every motion entry point of the window is driven once: no move runs a frame, no fade outlives FAST, a spinner
is a still, visible mark, a row flash is a 1 s steady wash, a drag's auto-scroll and the ghost under the hand go on
(direct manipulation is not motion), a scroll the app makes jumps. Then the live flip — Windows' message (to the app's
own filter only, never Windows' real setting) and the Settings row (through the settings service) — mid-move, mid-fade
and mid-loop; the filter as the setting changes; the re-read on activation; *Full* and *Reduced* over Windows' switch.

The sweep keeps the list of the entry points it drives (`SITES`, `OVERLAYS`): a scan of `app/qt` finds every call that
starts a motion (`.animate(`, `.spring(`, `open_overlay(`, `fall_into_place(`) and every overlay class, and fails when
one has no entry — a new motion joins the sweep. Each sweep test names the entry points it drives (`@drives`), and a
profile of its calls proves they ran.

What a wrong answer would cost a learner who turned motion down (often for a reason: motion sickness, a migraine):
  * a slide, a rising well or a gliding ghost after all — the one thing they asked to be spared;
  * a fade that lingers, or a wash that pulses, where a steady mark was promised;
  * a spinner that vanishes (no sign the app is busy) or keeps turning;
  * a drag that can't reach rows below the fold (auto-scroll stopped too) — reduced motion must never cost a function;
  * a setting that only applies after a restart, or a motion that runs on to its end after the switch.
"""
import ast
import ctypes
import os
import sys

import pytest

pytest.importorskip("PyQt6")
from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QEvent, QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app import theme
from app.qt import freeze, motion, shell
from app.qt import settings_controls as sc
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import _arrive, lift_row, world  # noqa: F401  (`world`: the fixture)
from tests.qt.test_drag import LEFT, NONE, lift, lst_of, mouse, move_global, release_global, row_point, well_point

JA = "今日は新しいエピソードを見た"
QT = os.path.dirname(motion.__file__)


# --- the list: every motion entry point the sweep drives ------------------------------------------------------------ #
# "file:function" (the function holding the call that starts the motion) -> what it is (the survey's table A)
SITES = {
    "motion.py:fall_into_place": "the reference's inset fall",
    "motion.py:OverlayOpening.start": "a top-level popup's opening (its window's opacity and place)",
    "motion.py:OverlayOpening._go": "an in-window overlay's opening (lifted or painted)",
    "motion.py:Overlay.open": "every motion.Overlay's open",
    "motion.py:Spinner._sync": "the spinner (pulse / spin)",
    "add_menu.py:AddStone._rise": "+ Add's stone rising under the hand",
    "add_menu.py:PasteCard.open": "the paste card",
    "arrivals.py:ArrivalsInset._play_arrival": "the covers part, the new one drops in, the count lifts",
    "arrivals.py:ArrivalsInset._sink": "a cover's press sink",
    "arrivals.py:ArrivalsTray.start_drag": "the tray's picture fading as a drag leaves it",
    "confirm.py:Confirm.open": "a question's card",
    "drag.py:Parting.move_to": "the gap slide and the slot's glide",
    "drag.py:DragController._glide_home": "the ghost's glide home",
    "drag.py:DragController._glide_away": "the ghost's fade into a well",
    "frame.py:Vein.go": "the tab vein",
    "frame.py:GoalDock._move": "the wells rising and falling",
    "frame.py:GoalDock.hover": "a well's slot opening",
    "goal_sheet.py:Wash.flash": "Goal's sheet's row wash",
    "goal_sheet.py:GoalSheet.open": "Goal's sheet rising",
    "rows.py:RowsView._touch_to": "a row's hover lift, its neighbours and its hover look",
    "search.py:Wash.__init__": "search's row flash",
    "search.py:SearchCut._sink_to": "the search field's sink",
    "settings_controls.py:_Vein.travel": "a choice's vein",
    "settings_controls.py:Toggle._toggle": "a switch's slide and light",
    "settings_controls.py:LevelSlider._press": "the slider's lift and its follow loop",
    "settings_controls.py:LevelSlider._settle": "the slider's settle",
    "settings_controls.py:LevelSlider._key_to": "the slider's glide by key",
    "settings_page.py:SettingsPage._glide": "Settings' glide to a row (an app-made scroll)",
    "settings_page.py:SettingsPage._wash": "Settings' row wash",
    "toast.py:ToastHost.show": "a toast's rise",
    "wizard.py:Switch._slide": "the wizard's switch knob",
}
# "file:Class" -> each overlay (a `motion.Overlay` no other overlay builds on) opened at least once
OVERLAYS = {
    "add_menu.py:PasteCard", "arrivals.py:ArrivalsTray", "confirm.py:Confirm", "duties.py:UpdateSheet",
    "finished.py:WhatIfCard", "frame.py:LevelPop", "goal_sheet.py:GoalSheet", "search.py:Results",
    "settings_live.py:FormatPop", "settings_live.py:CreditsCard", "toast.py:ToastCard",
}
STARTS = ("animate", "spring", "open_overlay", "fall_into_place")
_DECLARED = {}                                 # test name -> the entry points it drives (`@drives`)


def drives(*keys):
    def mark(fn):
        _DECLARED[fn.__name__] = set(keys)
        fn._drives = set(keys)
        return fn
    return mark


def scan():
    """(the motion call sites, the leaf overlay classes) of `app/qt`, as "file:qualname" (qualnames as Python names
    them: `Class.method`, `f.<locals>.g`)."""
    sites, classes = set(), {}
    for name in sorted(os.listdir(QT)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(QT, name), encoding="utf-8").read())

        def walk(node, qual, in_function):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    own = "<lambda>" if isinstance(child, ast.Lambda) else child.name
                    q = own if not qual else qual + (".<locals>." if in_function else ".") + own
                    if isinstance(child, ast.ClassDef):
                        bases = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", None)
                                 for b in child.bases}
                        classes[f"{name}:{q}"] = (child.name, bases)
                    walk(child, q, not isinstance(child, ast.ClassDef))
                    continue
                if isinstance(child, ast.Call):
                    f = child.func
                    called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if called in STARTS and qual:
                        sites.add(f"{name}:{qual}")
                walk(child, qual, in_function)
        walk(tree, "", False)
    overlay = {"Overlay"}                      # motion.Overlay, then whatever builds on an overlay (to a fixed point)
    while True:
        more = {own for own, bases in classes.values() if bases & overlay} - overlay
        if not more:
            break
        overlay |= more
    leaves = set()
    for key, (own, bases) in classes.items():
        if own in overlay and own != "Overlay" and not any(own in b for _o, b in classes.values()):
            leaves.add(key)
    return sites, leaves


class Recorder:
    """The sweep's witness: which entry points ran (a profile of Python calls while `on`), and the clock's checks."""

    def __init__(self, clock):
        self.clock = clock
        self.hit = set()
        self._before = None
        self._sites = set(SITES)

    def _profile(self, frame, event, _arg):
        if event != "call":
            return
        code = frame.f_code
        key = f"{os.path.basename(code.co_filename)}:{code.co_qualname}"
        if key in self._sites:
            self.hit.add(key)
        if code.co_name in ("open", "open_overlay"):           # an overlay's own open, or the animator's
            owner = frame.f_locals.get("self" if code.co_name == "open" else "widget")
            if isinstance(owner, motion.Overlay):
                cls = type(owner)
                self.hit.add(f"{os.path.basename(sys.modules[cls.__module__].__file__)}:{cls.__qualname__}")

    def on(self):
        self._before = sys.getprofile()
        sys.setprofile(self._profile)

    def off(self):
        if sys.getprofile() == self._profile:
            sys.setprofile(self._before)

    def still(self):
        """Reduced motion as the clock holds it: nothing on it but fades, none longer than FAST (a move never runs a
        frame, a loop never starts); after FAST nothing at all (a fade's end may start another fade: each judged)."""
        c = self.clock
        for _ in range(4):
            live = c.active
            if not live:
                return
            for a in live:
                assert a.kind == "fade", f"a {a.kind} on the clock under Reduced motion"
                if isinstance(a, motion.Animation):
                    assert not a.repeat and a.duration <= theme.FAST, a.duration
                else:
                    assert c.now() - a.started <= theme.FAST
            c.advance(theme.FAST + motion.FRAME_MS)
        assert c.active == []


@pytest.fixture
def sweep(qapp, request):
    """Reduced motion, the freeze switch off, the clock on its test time; the entry points the test names proven run."""
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    was = c.mode.setting
    c.mode.set_setting("reduced")
    rec = Recorder(c)
    yield rec
    rec.off()
    c = motion.clock()
    for a in c.active:
        a.stop()
    c.use_real_time()
    c.mode.set_setting(was)
    freeze.set_frozen(None)
    missed = getattr(request.function, "_drives", set()) - rec.hit
    assert not missed, f"named but never driven: {sorted(missed)}"


def _settle(n=20):
    for _ in range(n):
        QApplication.processEvents()


def _reduced_window(sweep, make, size=(1280, 900)):
    """The window opened (frozen, as every window test), then Reduced motion on the clock's test time."""
    seed, win, writer = make(size=size)
    c = sweep.clock
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    c.mode.set_setting("reduced")       # (the window set the clock from its settings: Follow Windows)
    return seed, win, writer


# --- the list is whole ---------------------------------------------------------------------------------------------- #
def test_every_motion_entry_point_has_a_sweep_entry_and_every_entry_is_driven():
    # A new motion (an `.animate(`, a `.spring(`, an overlay) without an entry here fails: add it to SITES / OVERLAYS
    # and drive it in a sweep test below. An entry whose call has gone fails too (the list stays true).
    sites, overlays = scan()
    assert sites == set(SITES), (sorted(sites - set(SITES)), sorted(set(SITES) - sites))
    assert overlays == OVERLAYS, (sorted(overlays - OVERLAYS), sorted(OVERLAYS - overlays))
    driven = set().union(*_DECLARED.values())
    assert driven == set(SITES) | OVERLAYS, sorted((set(SITES) | OVERLAYS) - driven)


# --- the sweep ------------------------------------------------------------------------------------------------------ #
class Card(motion.Overlay):
    def __init__(self, parent, how):
        super().__init__(parent)
        self.how = how
        self.setAutoFillBackground(True)
        QVBoxLayout(self).addWidget(QLabel(JA, self))
        self.setGeometry(200, 120, 320, 140)


def _painted(widget):
    return widget.grab().toImage()


def _ink(image):
    """How many pixels of `image` are drawn on (not see-through)."""
    return sum(1 for y in range(image.height()) for x in range(image.width()) if image.pixelColor(x, y).alpha() > 0)


@drives("motion.py:OverlayOpening._go", "motion.py:OverlayOpening.start", "motion.py:Overlay.open",
        "motion.py:Spinner._sync", "motion.py:fall_into_place")
def test_sweep_the_animator_overlays_open_in_place_spinners_are_still_marks_the_fall_is_none(sweep):
    stage = QWidget()
    stage.resize(900, 640)
    stage.show()
    _settle()
    sweep.on()
    for how in sorted(motion.HOW):                         # every kind of opening: in place, a fade within FAST
        card = Card(stage, how)
        opening = card.open()
        assert opening is None or opening.ghost is None or opening.ghost.offset == QPoint(0, 0), how
        sweep.still()
        assert card.isVisible() and motion.opening_of(card) is None, how
        card.hide()
    pop = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    pop.setGeometry(300, 300, 200, 100)
    motion.open_overlay(pop, "pop")
    assert pop.pos() == QPoint(300, 300)                   # a top-level popup: no move, only its fade
    sweep.still()
    assert pop.windowOpacity() == 1.0
    pop.close()
    for kind in ("pulse", "spin"):                         # a spinner: a still mark, painted and visible
        spin = motion.Spinner(kind, stage)
        spin.show()
        idle = _painted(spin)
        spin.set_running(True)
        busy = _painted(spin)
        assert not spin.on_clock and sweep.clock.active == []
        sweep.clock.advance(700)
        assert _painted(spin) == busy and busy != idle and _ink(busy) > 0, kind
        spin.set_running(False)
    fell = []
    motion.fall_into_place(fell.append)
    assert fell == [0.0]                                   # the fall: home at once, no frames
    sweep.still()
    stage.close()


@drives("drag.py:Parting.move_to", "drag.py:DragController._glide_home", "drag.py:DragController._glide_away",
        "frame.py:GoalDock._move", "frame.py:GoalDock.hover", "frame.py:Vein.go", "rows.py:RowsView._touch_to",
        "toast.py:ToastHost.show", "toast.py:ToastCard")
def test_sweep_the_list_rows_jump_the_ghost_never_glides_wells_never_rise_but_the_hand_still_scrolls(sweep, world):
    seed, win, writer = _reduced_window(sweep, world)
    lst = lst_of(win)
    dock = win.dock
    sweep.on()
    # a row under the hand: its lift and neighbours at rest at once, its look a fade within FAST
    seen = [n for n, e in enumerate(lst.model().entries) if e[0] == "row"
            and lst.viewport().rect().contains(lst.visualRect(lst.model().index(n, 0)).center())]
    assert len(seen) >= 4, "four whole rows on screen for the drags below"
    i = seen[0]
    key = lst.model().entries[i][1].key
    lst._hover = i
    lst._retouch()
    t = lst._touch[key]
    assert t.lift == theme.SPRINGS["lift-px"] and t.nb == theme.SPRINGS["neighbour-px"]
    sweep.still()
    lst._hover = None
    lst._retouch()
    sweep.still()
    # a drop on the list: no glide home, the row at its place at once
    lift(win, seen[2])
    target = row_point(win, seen[0])
    move_global(win, target)
    release_global(win, target)
    assert writer.calls and not win.moves.ghost.isVisible() and lst.landing is None
    sweep.still()
    assert wait_until(lambda: writer.saved, 3)
    QTest.qWait(theme.MOTION["click-swallow-after-drag"] + 30)   # (a press right after a drop is swallowed: not motion)
    seen = [n for n, e in enumerate(lst.model().entries) if e[0] == "row"
            and lst.viewport().rect().contains(lst.visualRect(lst.model().index(n, 0)).center())]
    # a drag: the wells up at once, the rows part at once, the slot at once
    lift(win, seen[1])
    assert dock.rise == 0 and dock.wells
    sweep.still()
    move_global(win, row_point(win, seen[3]))
    p = lst.parting
    assert p.springs == {} and sweep.clock.active == []
    # the ghost under the hand: it follows the pointer at once (direct manipulation, not motion)
    ghost = win.moves.ghost
    before = ghost.pos()
    move_global(win, row_point(win, seen[3]) + QPoint(0, 9))
    assert ghost.isVisible() and ghost.pos() == before + QPoint(0, 9)
    # auto-scroll: kept under Reduced motion — its timer runs and a tick at the list's bottom edge scrolls it
    assert win.moves._scroll.isActive() and win.moves._scroll.interval() == theme.MOTION["auto-scroll-tick"]
    bar = lst.verticalScrollBar()
    assert bar.maximum() > 0, "the list must scroll for this check"
    vp = lst.viewport()
    move_global(win, vp.mapToGlobal(QPoint(vp.width() // 2, vp.height() - 5)))
    first = bar.value()
    win.moves._auto_scroll()
    assert bar.value() > first
    bar.setValue(0)
    # over a well: its slot open at once; dropped there: the ghost's fade within FAST
    move_global(win, well_point(win, "soon"))
    assert dock.lit == "soon" and dock.slot_width("soon") == float(theme.FRAME["dock-cover"][0])
    sweep.still()
    release_global(win, well_point(win, "soon"))
    sweep.still()
    assert not ghost.isVisible() and dock.wells == ()       # the wells gone at once
    # a tab switch: the vein at its tab at once
    win.show_tab("finished")
    assert (win.vein.left, win.vein.right) == win.vein.span(win.tab_buttons["finished"]) and not win.vein.moving()
    win.show_tab("current")
    # a toast: in place, its fade within FAST
    win.toasts.show(JA)
    sweep.still()
    card = win.toasts.card
    assert card.isVisible() and motion.opening_of(card) is None


class _Shots:
    """search's `QTimer`, recording its single shots (the steady wash's second) instead of waiting on real time."""

    def __init__(self):
        self.shots = []

    def singleShot(self, ms, *args):
        self.shots.append((ms, args[-1]))


@drives("goal_sheet.py:GoalSheet.open", "goal_sheet.py:Wash.flash", "goal_sheet.py:GoalSheet",
        "search.py:SearchCut._sink_to", "search.py:Results", "search.py:Wash.__init__")
def test_sweep_goal_and_search_the_sheet_in_place_and_every_row_flash_a_steady_second(sweep, world, monkeypatch):
    from app.qt import goal_sheet, search as search_ui
    seed, win, writer = _reduced_window(sweep, world)
    sweep.on()
    sheet = win.goal_sheet
    sheet.open()                                           # in place at once
    assert sheet.offset == 0 and not sheet.rising() and sheet.geometry() == sheet.rest_rect()
    sweep.still()
    wash = sheet.wash
    lst = lst_of(win)
    wash.flash(lst.visualRect(lst.model().index(1, 0)))    # Goal's wash: steady, then gone after its second
    sweep.still()
    assert wash.isVisible() and wash.alpha == goal_sheet.SHEET["wash-alpha"]
    assert wash._steady.isActive() and wash._steady.interval() == theme.SETTINGS_MOTION["row-wash-steady"]
    wash._steady.timeout.emit()
    assert not wash.isVisible()
    sheet.hide()
    cut = win.search
    cut._sink_to(1.0)                                      # the field's sink: at rest at once
    assert cut.sink == 1.0
    sweep.still()
    cut.edit.blockSignals(True)
    cut.edit.setText("星")
    cut.edit.blockSignals(False)
    cut.wanted = True
    cut._answered("星", (), 1.0)                            # the results: in place, a fade within FAST
    sweep.still()
    assert cut.results.isVisible() and motion.opening_of(cut.results) is None
    cut.results.hide()
    shots = _Shots()
    monkeypatch.setattr(search_ui, "QTimer", shots)
    last = lst.model().entries[-1][1].key
    cut._scroll_to("current", last)                        # an app-made scroll: a jump, then the steady wash
    assert lst.viewport().rect().intersects(lst.visualRect(lst.model().index(len(lst.model().entries) - 1, 0)))
    washed = cut.washed
    sweep.still()
    assert washed.level == 1.0 and washed.isVisible()
    assert [ms for ms, _fn in shots.shots] == [theme.SETTINGS_MOTION["row-wash-steady"]]
    shots.shots[0][1]()
    assert sip.isdeleted(washed) or not washed.isVisible()


@drives("arrivals.py:ArrivalsInset._play_arrival", "arrivals.py:ArrivalsInset._sink", "arrivals.py:ArrivalsTray",
        "arrivals.py:ArrivalsTray.start_drag")
def test_sweep_arrivals_the_covers_rest_the_tray_opens_in_place_and_fades_within_fast(sweep, world):
    seed, win, writer = _reduced_window(sweep, world)
    inset = win.arrivals_inset
    sweep.on()
    played = inset.arrivals_played
    _arrive(seed)
    assert wait_until(lambda: inset.arrivals_played == played + 1, 5)   # (the reader's thread; no motion waited on)
    assert inset.arrive == 1.0
    sweep.still()
    mouse(inset, QEvent.Type.MouseButtonPress, QPointF(inset.rect().center()))
    assert inset.press == 1.0                                          # the sink: at once
    mouse(inset, QEvent.Type.MouseButtonRelease, QPointF(inset.rect().center()), LEFT, NONE)
    assert inset.press == 0.0
    tray = win.arrivals_tray
    if not tray.isVisible() and motion.opening_of(tray) is None:
        inset.click()
    sweep.still()                                                      # the tray: in place, a fade within FAST
    assert tray.isVisible() and motion.opening_of(tray) is None
    lift_row(win, 1)                                                   # the tray's picture: a fade within FAST
    sweep.still()
    assert not tray.fade.isVisible()
    win.moves.cancel()


@drives("add_menu.py:AddStone._rise", "add_menu.py:PasteCard.open", "add_menu.py:PasteCard", "confirm.py:Confirm.open",
        "confirm.py:Confirm", "frame.py:LevelPop", "duties.py:UpdateSheet", "finished.py:WhatIfCard")
def test_sweep_the_windows_cards_and_pops_open_in_place(sweep, world):
    from app.qt import add_menu, confirm, duties, finished, frame
    seed, win, writer = _reduced_window(sweep, world)
    central = win.centralWidget()
    sweep.on()
    stone = win.add_stone
    stone._rise(1.0)                                       # + Add's stone: up at once
    assert stone.lift == 1.0
    stone._rise(0.0)
    sweep.still()
    level = win.duties.pop if win.duties is not None else frame.LevelPop(central, frame.LevelButton(central))
    cards = [add_menu.PasteCard(win, lambda *_a: None), level, duties.UpdateSheet(central),
             finished.WhatIfCard(central)]
    for card in cards:
        card.open()
        sweep.still()
        assert card.isVisible() and motion.opening_of(card) is None, type(card).__name__
        card.hide()
    question = confirm.ask(win, "削除しますか", JA, "削除", "Remove it")
    sweep.still()
    assert question.isVisible() and motion.opening_of(question) is None
    question.close()


@drives("settings_page.py:SettingsPage._glide", "settings_page.py:SettingsPage._wash",
        "settings_controls.py:_Vein.travel", "settings_controls.py:Toggle._toggle",
        "settings_controls.py:LevelSlider._press", "settings_controls.py:LevelSlider._settle",
        "settings_controls.py:LevelSlider._key_to", "settings_live.py:FormatPop", "settings_live.py:CreditsCard")
def test_sweep_settings_the_glide_jumps_the_wash_is_steady_and_every_control_lands_at_once(sweep):
    from app.qt import settings_live
    from tests.qt.test_settings_controls import BANDS, ROAD, click, shown, spy
    from tests.qt.test_settings_controls import mouse as mouse_at
    from tests.qt.test_settings_page import ALL_ON, _at_third, make_page
    page, _store = make_page(ALL_ON, "ja")
    sweep.on()
    page.reveal("logic.names_kanji")                       # the glide to a row: a jump (an app-made scroll)
    view = page.rows["names_kanji"]
    assert _at_third(page, view)
    sweep.still()
    assert view.wash == 1.0                                # the wash: steady for its second, then gone
    assert page._wash_timer.isActive() and page._wash_timer.interval() == theme.SETTINGS_MOTION["row-wash-steady"]
    page._wash_timer.timeout.emit()
    assert view.wash == 0.0
    choice = shown(sc.Choice(ROAD))
    click(choice, choice._rects()[1].center())
    assert choice.vein() == choice._rest(1)
    sweep.still()
    toggle = shown(sc.Toggle())
    click(toggle, toggle.rect().center())
    assert toggle.position() == (1.0, 1.0)
    sweep.still()
    slider = shown(sc.LevelSlider(BANDS, value="core"), width=640)
    got = spy(slider)
    a, b = slider.chamber(4), slider.chamber(5)
    mouse_at(slider, QEvent.Type.MouseButtonPress, slider.chamber(0).x(), a.y())
    sweep.still()                                          # held: no lift glide, no follow loop
    mouse_at(slider, QEvent.Type.MouseMove, a.x() + 0.4 * (b.x() - a.x()), a.y())
    mouse_at(slider, QEvent.Type.MouseButtonRelease, a.x() + 0.4 * (b.x() - a.x()), a.y(), Qt.MouseButton.NoButton)
    assert got == ["rare"] and slider.gem() == (slider._at_t(4), 0.0)
    slider.setFocus()
    slider._key_to(5)                                      # by key: no glide
    assert slider.gem()[0] == slider._at_t(5)
    sweep.still()
    top = page.window()
    for pop in (settings_live.FormatPop(top, view, None, on_pick=lambda _f: None),
                settings_live.CreditsCard(top, JA, "CC BY-SA 4.0")):
        pop.open()
        sweep.still()
        assert pop.isVisible() and motion.opening_of(pop) is None, type(pop).__name__
        pop.close()
    for w in (choice, toggle, slider):
        w.close()


@drives("wizard.py:Switch._slide")
def test_sweep_the_wizards_switch_knob_jumps(sweep):
    from app.qt import wizard
    switch = wizard.Switch("Anki", "Turns it on")
    switch.show()
    sweep.on()
    switch.setChecked(True)
    assert switch._pos == 1.0
    sweep.still()
    switch.close()


# --- the live flip ---------------------------------------------------------------------------------------------- #
class Flip:
    """One of each running motion, started under Full on the clock's test time, for a flip to Reduced to land."""

    def __init__(self, clock, parent):
        self.clock = clock
        self.moved, self.done, self.faded, self.ended = [], [], [], []
        self.move = clock.animate(theme.MOTION["sheet"], self.moved.append, lambda: self.done.append("move"))
        self.spring_at = []
        self.spring = clock.spring(self.spring_at.append, 0.0, 10.0, **motion.preset("hover-lift"))
        self.fade = clock.animate(theme.MOTION["row-flash"], self.faded.append, lambda: self.done.append("fade"),
                                  kind="fade")
        self.loop = clock.animate(theme.MOTION["footer-pulse"], lambda _p: None, kind="loop", repeat=True,
                                  on_end=lambda: self.ended.append("loop"))
        self.spinner = motion.Spinner("pulse", parent)
        self.spinner.show()
        self.spinner.set_running(True)
        self.slider = sc.LevelSlider([(b, b) for b in ("a", "b", "c", "d")], value="a", parent=parent)
        self.slider.setGeometry(20, 400, 640, 80)
        self.slider.show()
        _settle()
        a, b = self.slider.chamber(1), self.slider.chamber(2)
        from tests.qt.test_settings_controls import mouse as mouse_at
        mouse_at(self.slider, QEvent.Type.MouseButtonPress, a.x(), a.y())
        mouse_at(self.slider, QEvent.Type.MouseMove, a.x() + 0.7 * (b.x() - a.x()), a.y())
        self.card = Card(parent, "up")                     # (after the press: a press lands an opening)
        self.opening = self.card.open()

    def check_running(self):
        assert self.move.alive and self.spring.alive and self.fade.alive and self.loop.alive
        assert self.spinner.on_clock and self.opening is not None and motion.opening_of(self.card) is not None
        assert self.slider._anims["follow"].alive and self.slider._t != self.slider._goal()

    def check_landed(self):
        now = self.clock.now()
        assert not self.move.alive and self.moved[-1] == 1.0 and "move" in self.done      # a move: at its end now
        assert self.spring.at_rest and self.spring_at[-1] == 10.0
        assert self.fade.alive and self.fade.start + self.fade.duration <= now + theme.FAST   # a fade: ends within FAST
        assert not self.loop.alive and self.ended == ["loop"]                                 # a loop: stopped
        assert not self.spinner.on_clock
        assert self.card.isVisible() and motion.opening_of(self.card) is None                 # the overlay: landed
        assert "follow" not in self.slider._anims or not self.slider._anims["follow"].alive
        assert self.slider._t == self.slider._goal()                                          # the gem at the hand
        self.clock.advance(theme.FAST)
        assert not self.fade.alive and "fade" in self.done and self.faded[-1] == 1.0

    def release(self):
        from tests.qt.test_settings_controls import mouse as mouse_at
        c = self.slider.chamber(2)
        mouse_at(self.slider, QEvent.Type.MouseButtonRelease, c.x(), c.y(), Qt.MouseButton.NoButton)
        self.spinner.set_running(False)


@pytest.fixture
def window_on_test_time(qapp):
    """The real window (its own settings service, its mode filter), then the clock on test time, unfrozen."""
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1100, 760)
    win.show()
    _settle()
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    mode = c.mode
    reader, system, setting = mode._reader, mode.system, mode.setting
    yield win, services, c
    for a in motion.clock().active:
        a.stop()
    motion.clock().use_real_time()
    mode._reader, mode.system = reader, system
    mode.set_setting(setting)
    freeze.set_frozen(None)
    win.close()
    services.shutdown(0.5)


def _windows_says(msg_wparam=motion.SPI_SETCLIENTAREAANIMATION):
    """Windows' WM_SETTINGCHANGE for its animation switch, handed to the app's own filter (never Windows' setting)."""
    from ctypes import wintypes
    state = QApplication.instance()._surasura_motion
    msg = wintypes.MSG()
    msg.message = motion.WM_SETTINGCHANGE
    msg.wParam = msg_wparam
    state["filter"].nativeEventFilter(QByteArray(b"windows_generic_MSG"), sip.voidptr(ctypes.addressof(msg)))
    _settle(3)                                             # (the filter tells the mode on the loop's next turn)


@pytest.mark.skipif(os.name != "nt", reason="Windows' message")
def test_live_flip_windows_turns_animations_off_mid_move_mid_fade_mid_loop_and_everything_lands(window_on_test_time):
    win, services, c = window_on_test_time
    windows = {"on": True}
    c.mode._reader = lambda: windows["on"]
    c.mode.system = True
    c.mode.set_setting("follow")
    assert not c.mode.reduced
    flip = Flip(c, win.centralWidget())
    c.advance(48)
    flip.check_running()
    windows["on"] = False                                  # Windows' *Show animations* turned off …
    _windows_says()                                        # … and its message to the app's own filter
    assert c.mode.reduced
    flip.check_landed()
    windows["on"] = True                                   # back on: nothing restarts (only the busy mark's pulse)
    _windows_says()
    assert not c.mode.reduced
    assert [a for a in c.active if a is not flip.spinner._anim] == [] and flip.card.isVisible()
    flip.release()


def test_live_flip_the_settings_row_mid_move_mid_fade_mid_loop_through_the_settings_service(window_on_test_time):
    win, services, c = window_on_test_time
    c.mode.set_setting("full")
    win.show_tab("settings")
    page = win.mount_settings()
    assert wait_until(lambda: page.row("app_motion") is not None, 20)
    flip = Flip(c, win.centralWidget())
    c.advance(48)
    flip.check_running()
    page.row("app_motion").controls[0].changed.emit("reduced")      # the Settings row: at once, and saved
    assert c.mode.setting == "reduced"
    assert wait_until(lambda: services.settings.get().get("app_motion") == "reduced", 5)
    flip.check_landed()
    page.row("app_motion").controls[0].changed.emit("full")
    assert c.mode.setting == "full"
    assert [a for a in c.active if a is not flip.spinner._anim] == [] and flip.card.isVisible()
    flip.release()


def test_back_to_full_a_landed_move_stays_landed(qapp):
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    was = c.mode.setting
    try:
        c.mode.set_setting("full")
        moved = []
        a = c.animate(theme.MOTION["sheet"], moved.append)
        c.advance(32)
        c.mode.set_setting("reduced")
        c.mode.set_setting("full")
        c.advance(theme.MOTION["sheet"])
        assert not a.alive and moved[-1] == 1.0 and moved.count(1.0) == 1 and c.active == []
    finally:
        c.use_real_time()
        c.mode.set_setting(was)
        freeze.set_frozen(None)


# --- the switch: the filter, the activation, the overrides ---------------------------------------------------------- #
def test_the_filter_is_installed_only_while_the_setting_follows_windows(qapp, monkeypatch):
    app = QApplication.instance()
    old = getattr(app, "_surasura_motion", None)
    if old is not None and old["installed"]:
        app.removeNativeEventFilter(old["filter"])
    monkeypatch.delattr(app, "_surasura_motion", raising=False)
    mode = motion.clock().mode
    was = mode.setting
    try:
        mode.set_setting("follow")
        motion.install_mode_filter(app)
        state = app._surasura_motion
        windows = sys.platform == "win32"
        assert state["installed"] is windows
        mode.set_setting("full")
        assert state["installed"] is False
        mode.set_setting("reduced")
        assert state["installed"] is False
        mode.set_setting("follow")
        assert state["installed"] is windows
        assert motion.install_mode_filter(app) is state["filter"]          # idempotent: one filter
        # a clock made again (a test's teardown deletes the app's children) is followed by the next window's install
        monkeypatch.setattr(motion, "_clock", None)
        fresh = motion.clock().mode
        fresh.set_setting("follow")
        assert motion.install_mode_filter(app) is state["filter"]
        fresh.set_setting("full")
        assert state["installed"] is False
        fresh.set_setting("follow")
        assert state["installed"] is windows
    finally:
        motion.clock().mode.set_setting("follow")
        mode.set_setting(was)
        state = getattr(app, "_surasura_motion", None)
        if state is not None and state["installed"]:
            app.removeNativeEventFilter(state["filter"])
        if old is not None and old["installed"]:
            app.installNativeEventFilter(old["filter"])


def test_coming_back_to_the_front_reads_windows_again(window_on_test_time):
    win, services, c = window_on_test_time
    reads, windows = [], {"on": True}
    c.mode._reader = lambda: reads.append(1) or windows["on"]
    c.mode.system = True
    c.mode.set_setting("follow")
    moved = []
    a = c.animate(theme.MOTION["sheet"], moved.append)
    c.advance(32)
    windows["on"] = False                                  # changed in Windows' Settings, the app in the back
    QApplication.instance().applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert reads and c.mode.reduced
    assert not a.alive and moved[-1] == 1.0                # and a move running then lands


def test_full_overrides_windows_off_and_reduced_overrides_windows_on(qapp):
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    mode = c.mode
    reader, system, was = mode._reader, mode.system, mode.setting
    try:
        mode._reader = lambda: False                       # Windows: animations off
        mode.system_changed()
        mode.set_setting("full")
        a = c.animate(theme.MOTION["sheet"], lambda _v: None)
        assert a.alive                                     # Full: it moves
        a.stop()
        mode._reader = lambda: True                        # Windows: animations on
        mode.system_changed()
        mode.set_setting("reduced")
        moved = []
        b = c.animate(theme.MOTION["sheet"], moved.append)
        assert not b.alive and moved == [1.0]              # Reduced: it jumps
    finally:
        mode._reader, mode.system = reader, system
        mode.set_setting(was)
        c.use_real_time()
        freeze.set_frozen(None)
