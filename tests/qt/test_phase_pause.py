"""Mado-PZ (2026-11-18, a tester's ask: what runs by itself taxes the PC; PROVISIONAL): one click on a circle at the
bar's bottom left pauses what it runs by itself — its ring turns the paused colour with two bars on it, on the press —
and a second click resumes it; one control after the circles pauses (or resumes) all five; a pause is kept across a
restart and said at the start; an amber circle's click still goes to its decision (a7).

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


def test_the_pause_all_control_sits_after_the_circles_and_says_which_it_does(strip):
    b = strip.pause_all_button
    last = strip.rect_of(P.CIRCLES[-1])
    assert b.geometry().left() > last.right() and b.geometry().right() < strip.width()
    if strip.help is not None:
        assert strip.help.geometry().left() > b.geometry().right()
    asked = []
    strip.pause_all.connect(lambda: asked.append(True))
    _click(b, b.rect().center())
    assert asked == [True]
    assert b.toolTip() == strings.PHASE_PAUSE_ALL
    strip.set_paused(set(P.CIRCLES))
    assert b.all_paused and b.toolTip() == strings.PHASE_RESUME_ALL == b.accessibleName()
    strip.set_paused({P.MINER})
    assert not b.all_paused and b.toolTip() == strings.PHASE_PAUSE_ALL


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


def test_the_pause_all_control_pauses_every_circle_and_then_resumes_them(world):
    win = world.win
    _click(win.phase.pause_all_button, win.phase.pause_all_button.rect().center())
    assert win.phase.paused == set(P.CIRCLES) == world.services.paused
    _click(win.phase, _centre(win.phase, P.MINER))                     # one resumed: *Pause all* pauses it again
    assert win.phase.paused == set(P.CIRCLES) - {P.MINER}
    _click(win.phase.pause_all_button, win.phase.pause_all_button.rect().center())
    assert win.phase.paused == set(P.CIRCLES)
    _click(win.phase.pause_all_button, win.phase.pause_all_button.rect().center())
    assert win.phase.paused == frozenset() == world.services.paused


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
    for paused, expect in (({P.MINER}, [strings.MINE_PAUSED]), (frozenset(), [])):
        said.clear()
        win = SimpleNamespace(services=SimpleNamespace(paused=paused, status=None), say=said.append)
        mine_actions.MineActions._told(SimpleNamespace(win=win), "saved", [], 1)
        assert said == expect

