"""Mado-PZ (2026-11-18, a tester's ask: what runs by itself taxes the PC; PROVISIONAL): one click on a circle at the
bar's bottom left pauses what it runs by itself — its ring turns the paused colour with two bars on it, on the press —
and a second click resumes it; a pause is kept across a restart and said at the start; an amber circle's click still
goes to its decision (a7). Mado-PZ2 (Sonic, 2026-11-19): no *Pause all* bubble — *Pause all* / *Resume all* under each
circle's own *Pause* / *Resume* in its right-click, and a Shift-click on any circle does it; each hover says what its
pause holds; a press held elsewhere names the circle to click.

What a wrong answer would cost a learner: a click that seems to do nothing (no change until a worker answers), a
pause that looks like a decision (amber), every circle repainted for one pause (S19), a job they pressed themselves
stopped by it, the PC busy again after a restart they thought kept the pause — or a pause they can't find a way out of.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app import settings_manager
from app.qt import mine_actions, phase_strip, strings
from app.services import jobs as J
from app.services import phase as P
from tests.qt.conftest import logos_in, wait_until
from tests.qt.test_jobs_bar import World, world  # noqa: F401  (`world`: the fixture)
from tests.qt.test_phase_strip import C, _centre, _click, _image, _near, _ring, strip  # noqa: F401


def _badge(s, circle, img):
    """The colour at the centre of `circle`'s paused badge's disc, beside its two bars."""
    r = s.rect_of(circle)
    d = r.width() * phase_strip.BADGE
    x = r.right() - d * 0.5 - d * 0.32
    y = r.bottom() - d * 0.5
    return img.pixelColor(round(x - 0.5), round(y - 0.5))


# --- the strip ----------------------------------------------------------------------------------------------------- #
def test_a_paused_circle_is_painted_at_once_in_the_paused_colour_with_its_badge_and_only_it(strip):
    strip.repaint()
    before = dict(strip.paints)
    strip.set_paused({P.MINER})
    after = dict(strip.paints)                                          # painted before set_paused returned
    assert after[P.MINER] == before[P.MINER] + 1
    assert all(after[c] == before[c] for c in P.CIRCLES if c != P.MINER), "S19: one pause, one circle repainted"
    img = _image(strip)
    assert _near(_ring(strip, P.MINER, img), C()[phase_strip.PAUSED_TOKEN])
    assert not _near(_ring(strip, P.MINER, img), C()["warn"]), "never amber: amber means a decision (a7)"
    assert _near(_badge(strip, P.MINER, img), C()[phase_strip.PAUSED_TOKEN])
    for c in (P.ARRIVALS, P.SURASURA, P.JUNBAN, P.ANKI):
        assert _near(_ring(strip, c, img), C()["line-hi"]), c
    strip.set_paused(set())
    img = _image(strip)
    assert _near(_ring(strip, P.MINER, img), C()["line-hi"]), "resumed: as at rest"
    painted = dict(strip.paints)
    strip.set_paused(set())
    assert strip.paints == painted, "the same again: nothing repainted"


def test_a_paused_circles_hover_says_so_first_and_a_click_is_what_resumes_it(strip):
    strip.set_paused({P.SURASURA})
    text = strip.hover_text(P.SURASURA)
    assert strings.PHASE_PAUSED in text and strings.PHASE_IDLE not in text
    assert strings.PHASE_PRESS_PAUSE not in text, "said once: its line says a click resumes it"
    assert strings.PHASE_PRESS_PAUSE in strip.hover_text(P.ANKI)
    assert f"{strings.PHASE_NAMES[P.SURASURA]}: {strings.PHASE_PAUSED}" in strip.summary()


def test_the_right_click_menu_offers_pause_or_resume_first(strip):
    strip.set_opens(set(phase_strip.SETTINGS))
    assert strip.menu_entries(P.JUNBAN)[0] == (strings.PHASE_PAUSE, "pause")
    strip.set_paused({P.JUNBAN})
    assert strip.menu_entries(P.JUNBAN)[0] == (strings.PHASE_RESUME, "pause")
    assert (strings.PHASE_SETTINGS, "settings") in strip.menu_entries(P.JUNBAN), "Settings kept, one right-click away"
    hover = strip.hover_text(P.JUNBAN)
    assert strings.PHASE_SETTINGS[0] in hover and strings.PHASE_RESUME[0] not in hover   # (the click's item said once)


def test_every_circle_takes_a_press_and_the_keyboard_reaches_each(strip):
    got = []
    strip.opened.connect(got.append)
    for c in P.CIRCLES:
        _click(strip, _centre(strip, c))
    assert got == list(P.CIRCLES)
    assert strip.focusPolicy() == Qt.FocusPolicy.TabFocus


# --- Mado-PZ2 (Sonic, 2026-11-19: no extra bubble — *Pause all* in each circle's right-click + Shift-click) ------- #
def test_no_pause_all_bubble_the_strip_is_its_five_circles_and_the_question_mark(strip):
    """Sonic: "I don't want too much there … we already have the ? bubble": nothing between the circles and the ?."""
    from PyQt6.QtWidgets import QAbstractButton
    from app import theme
    assert not hasattr(strip, "pause_all_button")
    marks = [w for w in strip.findChildren(QAbstractButton) if w is not strip.help]
    assert marks == [], [w.objectName() for w in marks]
    width = 5 * theme.size("phase-circle") + 4 * theme.size("phase-gap")
    if strip.help is not None:
        assert strip.help.geometry().left() == round(width + theme.size("phase-gap"))
    else:
        assert strip.width() == width


def test_every_circles_right_click_has_pause_all_right_under_its_own_pause(strip):
    """The pair reads as one: *Pause* · *Pause all*, *Resume* · *Resume all* — the item names what it does to all five
    as the item above does to this one; each with its tip (the bubble, a screen reader's description)."""
    from app.qt import tool_icons
    strip.set_opens(set(phase_strip.SETTINGS))
    for c in P.CIRCLES:
        entries = strip.menu_entries(c)
        assert entries[:2] == [(strings.PHASE_PAUSE, "pause"), (strings.PHASE_PAUSE_ALL, "pause_all")], c
    strip.set_paused({P.JUNBAN})
    assert strip.menu_entries(P.JUNBAN)[:2] == [(strings.PHASE_RESUME, "pause"), (strings.PHASE_RESUME_ALL, "pause_all")]
    assert strip.menu_entries(P.ANKI)[:2] == [(strings.PHASE_PAUSE, "pause"), (strings.PHASE_PAUSE_ALL, "pause_all")]
    menu = tool_icons.menu_of(strip, [(pair, lambda: None) for pair, _what in strip.menu_entries(P.JUNBAN)])
    try:
        acts = menu.actions()
        assert [a.text() for a in acts[:2]] == ["Resume", "Resume all"]       # (an item's text is its read-out name)
        assert all(a.toolTip() and a.toolTip() != a.text() for a in acts[:2])
    finally:
        menu.deleteLater()


def test_the_menus_pause_all_is_asked_of_the_window_with_its_circle(strip):
    asked = []
    strip.asked.connect(lambda c, what: asked.append((c, what)))
    strip.set_opens(set(phase_strip.SETTINGS))
    entries = strip.menu_entries(P.SURASURA)
    assert entries[1][1] == "pause_all"
    strip.asked.emit(P.SURASURA, entries[1][1])
    assert asked == [(P.SURASURA, "pause_all")]


def test_a_shift_click_on_any_circle_asks_for_all_five_and_opens_nothing(strip):
    from PyQt6.QtTest import QTest
    opened, every = [], []
    strip.opened.connect(opened.append)
    strip.pause_all.connect(every.append)
    for c in P.CIRCLES:
        QTest.mouseClick(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, _centre(strip, c))
    assert every == list(P.CIRCLES) and opened == []
    _click(strip, _centre(strip, P.ANKI))                               # a plain click: that circle alone, as before
    assert opened == [P.ANKI] and every == list(P.CIRCLES)


def test_shift_enter_on_the_circle_in_focus_asks_for_all_five(strip):
    from PyQt6.QtTest import QTest
    opened, every = [], []
    strip.opened.connect(opened.append)
    strip.pause_all.connect(every.append)
    strip.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    QTest.keyClick(strip, Qt.Key.Key_Right)
    QTest.keyClick(strip, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(strip, Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier)
    assert every == [P.SURASURA, P.SURASURA] and opened == []
    QTest.keyClick(strip, Qt.Key.Key_Return)
    assert opened == [P.SURASURA]


def test_each_circles_hover_lists_what_its_pause_holds_and_says_the_shift_click(strip):
    """The line *Pause all*'s hover was to carry, on the circle it belongs to; the Shift-click said where it's used."""
    assert set(strings.PHASE_HOLDS) == set(P.CIRCLES)
    for c in P.CIRCLES:
        text = strip.hover_text(c)
        assert strings.PHASE_HOLDS_LINE.format(what=strings.PHASE_HOLDS[c]) in text, c
        assert strings.PHASE_SHIFT_PAUSE_ALL in text and strings.PHASE_SHIFT_RESUME_ALL not in text, c
        assert strings.PHASE_PAUSE_ALL[0] not in text, "said once: the Shift-click line, not the right-click's again"
    strip.set_paused({P.MINER})
    text = strip.hover_text(P.MINER)
    assert strings.PHASE_HOLDS_LINE.format(what=strings.PHASE_HOLDS[P.MINER]) in text, "paused: what waits, said"
    assert strings.PHASE_SHIFT_RESUME_ALL in text and strings.PHASE_SHIFT_PAUSE_ALL not in text
    assert strings.PHASE_SHIFT_PAUSE_ALL in strip.hover_text(P.ANKI)


# --- the window ---------------------------------------------------------------------------------------------------- #
def test_a_click_pauses_at_once_and_a_second_click_resumes(world):
    win = world.win
    _click(win.phase, _centre(win.phase, P.SURASURA))
    assert win.phase.paused == {P.SURASURA}, "painted on the press, before any worker"
    assert world.services.paused == {P.SURASURA}
    assert settings_manager.paused(world.services.settings.get()) == {P.SURASURA}
    assert world.services.settings.flush(5) and settings_manager.paused(settings_manager.load_settings()) == \
        {P.SURASURA}, "written: kept across a restart (and Connect reads the file)"
    _click(win.phase, _centre(win.phase, P.SURASURA))
    assert win.phase.paused == frozenset() == world.services.paused


def test_a_pause_holds_and_stops_what_runs_by_itself_never_a_job_you_pressed(world):
    win, registry = world.win, world.registry
    cancelled = []
    auto = registry.submit("indexer", "Reading your files", lambda job: None,
                           cancel=lambda job: cancelled.append("auto"), automatic=True)
    yours = registry.submit("sentence-corpus", "Making the sentence dictionary", lambda job: None,
                            cancel=lambda job: cancelled.append("yours"))
    assert auto.state == J.RUNNING and yours.state == J.WAITING      # (one token-store job at a time)
    _click(win.phase, _centre(win.phase, P.SURASURA))
    assert cancelled == ["auto"] and auto.state == J.CANCELLING, "its next safe point: *Stopping…*"
    assert any("stopping" in line for line in win.phase.states[P.SURASURA].lines) or \
        wait_until(lambda: any("stopping" in line for line in win.phase.states[P.SURASURA].lines))
    auto.finish(cancelled=True)
    assert yours.state == J.RUNNING, "the job you pressed runs"
    yours.finish()
    again = registry.submit("indexer", "Reading your files", lambda job: None, automatic=True)
    assert again.state == J.WAITING and again.reason == strings.PAUSED_HELD
    _click(win.phase, _centre(win.phase, P.SURASURA))                  # resumed
    assert wait_until(lambda: again.state == J.RUNNING), "what waited starts on the resume"


def _shift_click(widget, pos):
    from PyQt6.QtTest import QTest
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos)


def test_a_shift_click_pauses_all_five_and_on_a_paused_circle_resumes_all(world):
    """Shift does to all five what the click does to the one: a running circle's pauses them all, a paused one's
    resumes them all — painted on the press, kept in settings.json as one click's is."""
    win = world.win
    _shift_click(win.phase, _centre(win.phase, P.SURASURA))
    assert win.phase.paused == set(P.CIRCLES) == world.services.paused
    assert world.services.settings.flush(5) and settings_manager.paused(settings_manager.load_settings()) == \
        set(P.CIRCLES)
    _click(win.phase, _centre(win.phase, P.MINER))                     # one resumed by its own click
    assert win.phase.paused == set(P.CIRCLES) - {P.MINER}
    _shift_click(win.phase, _centre(win.phase, P.MINER))               # it runs: Shift pauses all again
    assert win.phase.paused == set(P.CIRCLES)
    _shift_click(win.phase, _centre(win.phase, P.ANKI))                # paused: Shift resumes all
    assert win.phase.paused == frozenset() == world.services.paused


def test_the_menus_pause_all_and_resume_all_are_the_shift_click(world):
    win = world.win
    win.phase.asked.emit(P.JUNBAN, "pause_all")
    assert world.services.paused == set(P.CIRCLES)
    win.phase.asked.emit(P.JUNBAN, "pause")                            # its own Resume, as a click
    assert world.services.paused == set(P.CIRCLES) - {P.JUNBAN}
    win.phase.asked.emit(P.ANKI, "pause_all")                          # Anki is paused: *Resume all*
    assert world.services.paused == frozenset()


def test_a_shift_click_on_an_amber_circle_pauses_all_and_never_opens_its_decision(world, monkeypatch):
    """Amber's click goes to its decision (a7); Shift is the all-five pause, on any circle."""
    win = world.win
    monkeypatch.setattr(win.phase, "go", lambda circle: P.Go("needs", ("no-video",)))
    shown = []
    monkeypatch.setattr(win, "show_tab", lambda name: shown.append(name))
    _shift_click(win.phase, _centre(win.phase, P.MINER))
    assert world.services.paused == set(P.CIRCLES) and shown == []


def test_the_menus_pause_and_resume_are_the_click(world):
    win = world.win
    win.phase.asked.emit(P.ANKI, "pause")
    assert world.services.paused == {P.ANKI}
    win.phase.asked.emit(P.ANKI, "pause")
    assert world.services.paused == frozenset()


def test_an_amber_circles_click_goes_to_its_decision_and_pauses_nothing(world, monkeypatch):
    win = world.win
    monkeypatch.setattr(win.phase, "go", lambda circle: P.Go("needs", ("no-video",)))
    shown = []
    monkeypatch.setattr(win, "show_tab", lambda name: shown.append(name))
    from types import SimpleNamespace
    monkeypatch.setattr(win, "needs_you", SimpleNamespace(reveal_first=lambda at: shown.append(at)), raising=False)
    win._circle_pressed(P.MINER)
    assert world.services.paused == frozenset() and shown == ["needs", ("no-video",)]
    monkeypatch.setattr(win, "needs_you", None, raising=False)          # its page not there: still no pause
    win._circle_pressed(P.MINER)
    assert world.services.paused == frozenset()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_pause_is_kept_across_a_restart_and_said_at_the_start(qapp, tmp_path, language):
    settings_manager.save_settings({"target_language": language, "paused": ["miner", "junban"]})
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    try:
        assert w.services.paused == {P.MINER, P.JUNBAN} == w.win.phase.paused
        said = strings.PAUSED_AT_START.format(names=" · ".join(strings.PHASE_NAMES[c] for c in (P.MINER, P.JUNBAN)))
        assert wait_until(lambda: w.win.bar_line.full() == said)
        held = w.registry.submit("junban", "Re-ordering Anki", lambda job: None, automatic=True)
        assert held.state == J.WAITING and held.reason == strings.PAUSED_HELD, "never resumed by itself"
    finally:
        w.close()


def test_nothing_paused_says_nothing_at_the_start(world):
    QApplication.processEvents()
    assert world.services.paused == frozenset() == world.win.phase.paused
    assert "Paused:" not in world.win.bar_line.full()


# --- Mine now while Anki Miner is paused ------------------------------------------------------------------------ #
def test_mine_now_while_anki_miner_is_paused_is_asked_and_the_bar_says_it_waits(monkeypatch):
    """The ask is kept (Connect mines it once resumed: nothing lost); the bar says why nothing starts yet."""
    from types import SimpleNamespace
    said = []

    class Timer:
        @staticmethod
        def singleShot(_ms, _call):
            pass
    monkeypatch.setattr(mine_actions, "QTimer", Timer)
    waits = strings.PAUSED_WAITS.format(what=strings.MINE_WAITS, circle=strings.PAUSED_CIRCLE[P.MINER])
    assert "Anki Miner is paused" in waits, "the one shared line names the circle to click (Mado-PZ2)"
    for paused, expect in (({P.MINER}, [waits]), (frozenset(), [])):
        said.clear()
        win = SimpleNamespace(services=SimpleNamespace(paused=paused, status=None), say=said.append)
        mine_actions.MineActions._told(SimpleNamespace(win=win), "saved", [], 1)
        assert said == expect


def test_pausing_anki_miner_mid_episode_never_presses_its_rows_stop(world, monkeypatch):
    """Train 45's intent keeper #1: the row's Stop waits for a new *Mine now*; a pause must let the resume go on — so
    the window never presses it: Connect cuts the episode itself at its watch's next look, resumably. The menu's own
    *Stop* is still the row's Stop."""
    from types import SimpleNamespace
    win = world.win
    item = SimpleNamespace(stoppable=True, stopping=False, job=7, kind="mining")
    monkeypatch.setattr(win, "_mining_now", lambda: (11, item))
    stopped = []
    monkeypatch.setattr(win, "mine", SimpleNamespace(stop=lambda ask: stopped.append(ask.id)), raising=False)
    win._circle_pressed(P.MINER)
    assert world.services.paused == {P.MINER} and stopped == []
    win._circle_asked(P.MINER, "stop")
    assert stopped == [11], "your Stop from the menu: the row's, as before"



# --- Mado-PZ2: a press held by a pause names the circle to click ------------------------------------------------ #
def test_make_their_cards_while_anki_miner_is_paused_says_they_wait_and_which_circle_resumes():
    """*Make their cards* queues them (nothing lost) but nothing starts while Anki Miner is paused: never *come next*."""
    for made, one in ((1, True), (3, False)):
        said = mine_actions._made_words(made, paused=True)
        assert said == strings.PAUSED_WAITS.format(what=strings.MAKE_CARDS_WAIT[one].format(n=made),
                                                   circle=strings.PAUSED_CIRCLE[P.MINER])
        assert mine_actions._made_words(made) == strings.MAKE_CARDS_QUEUED[one].format(n=made)
    assert mine_actions._made_words(0, paused=True) == strings.MAKE_CARDS_NONE, "nothing queued: nothing waits"
    assert mine_actions._made_words(False, paused=True) == strings.MAKE_CARDS_GONE


def test_every_paused_line_names_a_circle_the_strip_shows():
    assert set(strings.PAUSED_CIRCLE) == set(P.CIRCLES)
    for c in (P.ARRIVALS, P.SURASURA, P.JUNBAN):
        assert strings.PAUSED_CIRCLE[c] == strings.PHASE_MARKS[c], "the mark on the circle itself"
    for c in (P.MINER, P.ANKI):
        assert strings.PAUSED_CIRCLE[c] == strings.PHASE_NAMES[c], "a logo: its name"
