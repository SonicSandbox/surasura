"""Alpha 6's #5 (a tester's notes, 2026-10-29): Settings' Journey rows — the theme, the switches — changed nothing on
screen. A setting only the report reads moves no analysis (the Generate button's mark leaves it out on purpose), the
window told the journey keeper nothing, and *Journey ↗* opened the file as it was. Now:

  * the window's settings hook tells the keeper when a report setting is written (`Replan.report_changed` →
    `keeper.marked("settings")`), never for an analysis or a window-only key;
  * the keeper's quiet run then re-renders the journey and re-analyses nothing (the analyzer's reuse path);
  * *Journey ↗* (`Services.draw_journey`), when the report is stale and its analysis isn't, asks the user's own run,
    waits for it, then opens — a journey whose analysis is stale too opens as it is, never after a full Generate.

What a wrong answer would cost a learner: every Journey setting looking dead (Mattias), or — the other way — a theme
change that starts a minutes-long re-analysis, or a *Journey ↗* that waits for one.

The scenario half runs real Generates on a real library (tests/test_journey_stones_quiet's: Show A and Show B, Japanese
and Chinese), the analyzer in its own process with the argv the window's run carries.
"""
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app import analyzer, run_args
from app.qt import shell
from tests import services_helpers as h
from tests.plan_file_cases import child_env
from tests.qt.test_jobs_bar import World
from tests.qt.test_journey_stones_trigger import _Window
from tests.test_journey_stones import REPO, REUSED
from tests.test_journey_stones_quiet import (RE_RENDER, _argv, _kept_on,  # noqa: F401
                                             _the_childs_token_store)  # (an autouse fixture)
from tests.test_library_store_support import LANGUAGES
from tests.test_services_replan_host import fired, gate  # noqa: F401 (fixtures)


# --- the window's hook ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("keys, told", [
    (["theme"], 1),                                   # the theme row
    (["logic.hide_audio_button"], 1),                 # a Journey switch (a logic key)
    (["source_display", "zen_limit"], 1),             # two at once: one look
    (["open_app_mode"], 0),                           # how it opens, read at the open: nothing to draw
    (["exclude_single"], 0),                          # an analysis key: the Generate button's mark says so
])
def test_a_report_setting_written_tells_the_journey_keeper_once_and_nothing_else_does(qapp, tmp_path, monkeypatch,
                                                                                      keys, told):
    w = World(qapp, logs_folder=str(tmp_path / "logs"))           # the window with its header's duties
    try:
        heard = []
        monkeypatch.setattr(w.services, "replan", SimpleNamespace(report_changed=lambda: heard.append(1),
                                                                  level_changed=lambda: None))
        w.win._settings_written(keys)
        assert len(heard) == told
    finally:
        w.close()


# --- the scenario: real Generates ------------------------------------------------------------------------------------ #
def _themed_argv(settings, language=None, **_k):
    """The test's Generates' argv (`_argv`: six short episodes), with the theme `run_args` passes when one is set and
    an analysis setting the test can move (`min_freq`, as `--min-freq` stands for the level)."""
    settings = settings or {}
    argv = _argv(language)
    argv[argv.index("--min-freq") + 1] = str(settings.get("min_freq", 1))
    theme = settings.get("theme")
    return argv + ([f"--theme={run_args.THEME_ARGS[theme]}"] if theme else [])


def _run(root, run):
    """A run the controller launched, run as the window starts it (the analyzer in its own process, with the run's
    own argv) and ended on the controller -> what it printed, and the report's text."""
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py")] + list(run.argv[1:])
    p = subprocess.run(cmd, cwd=REPO, env=child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    run.ended(0)
    with open(os.path.join(root, "results", "reading_list_static.html"), encoding="utf-8") as f:
        return p.stdout, f.read()


@pytest.fixture
def themed(monkeypatch):
    monkeypatch.setattr(run_args, "analyzer_args", _themed_argv)
    made = []

    def make(language):
        w = _Window(language)
        made.append(w)
        return w
    yield make
    for w in made:
        w.close()


def _halves(settings, language):
    args = _themed_argv(settings, language)
    return analyzer.journey_is_current(args, language), analyzer.report_is_current(args, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_theme_change_re_renders_the_journey_by_itself_and_re_analyses_nothing(language, themed, gate, fired):
    store, _ids, _names, root, _first = _kept_on(language)
    w = themed(language)
    settings = w.replan._settings
    assert _halves(settings.get(), language) == (True, True)
    settings.values["theme"] = "Modern Light"
    assert _halves(settings.get(), language) == (True, False), "the analysis current, the report not"
    w.replan.report_changed()
    assert fired.done(w.keeper)
    assert w.keeper.asked == 1 and h.until(lambda: w.launches.count() == 1, seconds=5), "one quiet run asked"
    said, html = _run(root, w.launches.runs[0])
    assert REUSED in said and RE_RENDER in said, "a re-render only"
    assert "globalTheme = 'modern-light'" in html
    assert _halves(settings.get(), language) == (True, True)
    w.replan.report_changed()                         # the same setting again: nothing left to draw
    assert fired.done(w.keeper)
    assert w.keeper.asked == 1 and w.launches.count() == 1
    store.close()


def _press(w, settings, opened):
    """`Services.draw_journey` + the open, as *Journey ↗* runs them on a worker: the services' parts it reads."""
    def generate():
        return w.controller.request(w.language, settings=settings.get(), launcher=w.launches)
    services = SimpleNamespace(closing=threading.Event(), settings=settings, language=w.language,
                               controller=w.controller, generate=generate)
    t = threading.Thread(target=lambda: opened.append(shell.Services.draw_journey(services, wait=60)) or None)
    t.start()
    return t


@pytest.mark.parametrize("language", LANGUAGES)
def test_journey_opens_after_a_re_render_when_only_a_report_setting_changed_and_as_it_is_when_the_analysis_moved(
        language, themed, gate):
    store, _ids, _names, root, _first = _kept_on(language)
    w = themed(language)
    settings = w.replan._settings
    settings.values["logic"] = {"automation": False}  # D29 off: the keeper runs nothing, so the press is the one
    settings.values["source_display"] = "full"
    settings.values["theme"] = "Midnight (Vibrant)"
    opened = []
    t = _press(w, settings, opened)
    assert h.until(lambda: w.launches.count() == 1, seconds=20), "the press asked a run"
    assert t.is_alive(), "and waits for it before opening"
    said, html = _run(root, w.launches.runs[0])
    t.join(10)
    assert not t.is_alive() and opened == [None]
    assert REUSED in said and RE_RENDER in said and "globalTheme = 'midnight-vibrant'" in html
    assert _halves(settings.get(), language) == (True, True)
    t = _press(w, settings, opened)                   # current now: opens at once, no run
    t.join(10)
    assert not t.is_alive() and w.launches.count() == 1
    settings.values["min_freq"] = 2                   # the analysis moves too (a full Generate's to do)
    settings.values["theme"] = "Modern Light"
    assert _halves(settings.get(), language)[0] is not True
    t = _press(w, settings, opened)
    t.join(10)
    assert not t.is_alive() and w.launches.count() == 1, "opened as it is: no full Generate behind a press"
    store.close()
