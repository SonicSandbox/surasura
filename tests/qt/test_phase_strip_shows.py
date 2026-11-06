"""The phase strip says and shows what is spinning (try a9.1, Sonic's report #BS0A1K: "for some reason junban and anki
miner are spinning but i don't know what they are doing"; `app/qt/phase_strip.py`, `app/services/phase.py`).

What a wrong answer would cost a learner:
  * 順 turning for minutes with a hover that only says "Re-ordering Anki's new cards" — never how many, how far;
  * Anki Miner's hover still saying it makes cards after Stop was pressed;
  * a press on a spinning circle that opens a settings page instead of the work it is doing;
  * a Stop offered where nothing can stop (an Anki write finishing its batch) — or one that stops the wrong thing;
  * a right-click menu on the left icons that differs from the right icons' (two rules for one bar).
"""
import html
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtWidgets import QApplication, QWidget

from app.connect import feed
from app.qt import phase_strip, strings, tool_icons
from app.services import jobs as J
from app.services import phase as P
from app.services import status as S
from app.services.jobs import JobRegistry
from tests.qt.conftest import logos_in
from tests.qt.test_jobs_bar import world  # noqa: F401  (`world`: the window with stand-in services)
from tests.qt.test_p41_actions import act  # noqa: F401  (`act`: the window on the seed library)

TITLE = "ヤコブ書 · Part 2"
COUNTED = "Anki: tomorrow's 20 cards placed · moving 281 more…"     # 順's own line while it writes (the host's words)


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
    host.show()
    QApplication.processEvents()
    assert logos_in(s)
    yield s
    host.close()


def _snap(**kw):
    from app.services.status import Snapshot
    base = dict(lines=(), failure=None, needs_you=(), ankiweb=None, connect=None, logs=None, taken_at=0, replan=None)
    base.update(kw)
    return Snapshot(**base)


def _mining(stoppable=True, stopping=None, progress=40, doing="Filling fields"):
    return feed.Item(feed.MINING, feed.WORDS[feed.MINING], "", 7, 0, 0, progress, doing, stoppable, stopping,
                     None, TITLE + ".srt")


def _feed(item):
    return feed.Feed(on=True, mining=frozenset({11}), items={11: item}, line="Mining", state="ok", unseen=0,
                     updating=False)


# --- the rules (Qt-free) ------------------------------------------------------------------------------------------ #
def test_a_stop_cancels_only_live_cancellable_jobs_of_that_circle_never_one_past_its_stopping_point():
    """The update's *Stop it* rule, per circle: a job with a cancel, not an Anki write finishing its batch (`wait`),
    not one already stopping — and never another circle's."""
    registry = JobRegistry()
    gen = registry.submit("generate", "Generating", lambda j: None, cancel=lambda j: None)
    writing = registry.submit("junban", "Junban", lambda j: None, cancel=lambda j: None, on_quit="wait")
    backfill = registry.submit("backfill", "Backfill", lambda j: None, cancel=lambda j: None)
    replan = registry.record("replan", "Re-ordering Anki's new cards", automatic=True, on_quit="wait")
    mine = registry.record("mine", "Making cards", automatic=True, on_quit="detach")       # (no cancel of its own)
    views = registry.live()
    assert P.stoppable(views, P.SURASURA) == (gen.id,)
    assert P.stoppable(views, P.JUNBAN) == (backfill.id,)               # not the Anki write, not the host's reorder
    assert P.stoppable(views, P.MINER) == () and P.stoppable(views, P.ANKI) == ()
    gen.cancel()                                                       # stopping already: not offered again
    assert P.stoppable(registry.live(), P.SURASURA) == ()
    for j in (writing, backfill, replan, mine):
        j.finish()


def test_a_job_with_no_step_is_marked_so_the_hover_can_add_the_circles_own_counted_line():
    registry = JobRegistry()
    replan = registry.record("replan", "Re-ordering Anki's new cards", automatic=False, on_quit="wait")
    got = P.read(registry.snapshot())
    assert got[P.JUNBAN].running and not got[P.JUNBAN].stepped
    replan.progress("placing tomorrow's 20 cards")
    assert P.read(registry.snapshot())[P.JUNBAN].stepped
    assert P.IDLE.stepped is False


def test_connects_mining_line_says_stopping_once_its_stop_is_asked():
    registry = JobRegistry()
    S.mirror_connect(registry, _feed(_mining()))
    (job,) = registry.live(S.CONNECT_JOB_KIND)
    assert S.CONNECT_JOB_LABEL in S.job_line(job) and TITLE in S.job_line(job) and "Filling fields 40%" in S.job_line(job)
    S.mirror_connect(registry, _feed(_mining(stoppable=False, stopping=True)))
    (job,) = registry.live(S.CONNECT_JOB_KIND)
    assert S.job_line(job) == f"{S.CONNECT_JOB_LABEL} · {TITLE} · {S.CONNECT_STOPPING}"   # the title kept, no %
    S.mirror_connect(registry, None)
    assert registry.live(S.CONNECT_JOB_KIND) == ()


# --- the strip ---------------------------------------------------------------------------------------------------- #
def test_junbans_reorder_hover_names_it_plainly_then_says_its_own_counted_line(strip):
    registry = JobRegistry()
    strip.set_status(_snap(replan=COUNTED))
    replan = registry.record("replan", "Re-ordering Anki's new cards", automatic=False, on_quit="wait")
    strip.set_jobs(registry.snapshot())
    text = strip.hover_text(P.JUNBAN)
    assert html.escape("Re-ordering Anki's new cards") in text        # what it is
    assert html.escape(COUNTED) in text                               # how far: the host's own count
    assert text.index(html.escape("Re-ordering Anki's new cards")) < text.index(html.escape(COUNTED))
    replan.progress("placing tomorrow's 20 cards")                    # a job that says its step: said once, alone
    strip.set_jobs(registry.snapshot())
    assert html.escape(COUNTED) not in strip.hover_text(P.JUNBAN)
    replan.finish()


def test_a_spinning_circle_that_can_be_seen_says_a_press_shows_it_and_offers_show_stop_settings(strip):
    registry = JobRegistry()
    strip.set_opens({P.MINER, P.JUNBAN, P.SURASURA})
    asked = []
    strip.stops = lambda c: asked.append(c) or c == P.MINER
    assert not strip.showing(P.MINER)                                  # at rest: a press opens its settings
    assert [w for _p, w in strip.menu_entries(P.MINER)] == ["stop", "settings"]
    mine = registry.record("mine", "Making cards", automatic=False)
    mine.progress(f"{TITLE} · Filling fields 40%")
    strip.set_jobs(registry.snapshot())
    assert strip.showing(P.MINER) and strip.press_words(P.MINER) == strings.PHASE_PRESS_SHOW
    entries = strip.menu_entries(P.MINER)
    assert [pair for pair, _w in entries] == [strings.PHASE_SHOW, strings.PHASE_STOP, strings.PHASE_SETTINGS]
    text = strip.hover_text(P.MINER)
    assert html.escape(TITLE) in text and html.escape(strings.PHASE_PRESS_SHOW) in text
    assert html.escape(strings.PHASE_MENU_TIP.format(items="Stop · Settings")) in text    # (Show: the press's own)
    strip.can_show = lambda c: False                                  # nothing to see now (its install, a press
    assert not strip.showing(P.MINER)                                 # ... before Connect's job): no promise of it
    assert strip.press_words(P.MINER) == strings.PHASE_PRESS
    assert html.escape(strings.PHASE_MENU_TIP.format(items="Stop")) in strip.hover_text(P.MINER)
    strip.can_show = None
    gen = registry.submit("generate", "Generating", lambda j: None)
    strip.set_jobs(registry.snapshot())
    assert not strip.showing(P.SURASURA)                               # ス has no place of its own: its settings
    assert strip.press_words(P.SURASURA) == strings.PHASE_PRESS
    assert "Right-click" not in strip.hover_text(P.SURASURA)           # one item, the press's own: not said twice
    for j in (mine, gen):
        j.finish()


def test_the_right_click_is_the_bottom_bars_one_menu_and_each_item_asks_the_shell(strip, monkeypatch):
    built = []

    class Menu:
        def exec(self, at):
            built.append(("exec", at))

    def menu_of(parent, entries):
        built.append([pair for pair, _do in entries])
        built.append([do for _pair, do in entries])
        return Menu()
    monkeypatch.setattr(tool_icons, "menu_of", menu_of)
    registry = JobRegistry()
    strip.set_opens({P.JUNBAN})
    strip.stops = lambda c: bool(P.stoppable(registry.live(), c))       # (the shell's rule, for jobs)
    replan = registry.record("replan", "Re-ordering Anki's new cards", automatic=False, on_quit="wait")
    strip.set_jobs(registry.snapshot())
    said = []
    strip.asked.connect(lambda c, what: said.append((c, what)))
    at = strip.rect_of(P.JUNBAN).center().toPoint()
    QApplication.sendEvent(strip, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, at, strip.mapToGlobal(at)))
    assert built[0] == [strings.PHASE_SHOW, strings.PHASE_SETTINGS]    # no Stop: the host's Anki write can't stop
    for do in built[1]:
        do()
    assert said == [(P.JUNBAN, "show"), (P.JUNBAN, "settings")] and built[2][0] == "exec"
    built.clear()
    at = strip.rect_of(P.ANKI).center().toPoint()                      # nothing to offer: no menu at all
    QApplication.sendEvent(strip, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, at, strip.mapToGlobal(at)))
    assert built == []
    replan.finish()


def test_menu_of_makes_one_item_per_entry_with_its_tip_and_runs_it(qapp):
    host = QWidget()
    ran = []
    m = tool_icons.menu_of(host, [(strings.PHASE_SHOW, lambda: ran.append("show")),
                                  (strings.PHASE_STOP, lambda: ran.append("stop"))])
    acts = m.actions()
    assert [a.text() for a in acts] == ["Show", "Stop"] and acts[1].toolTip() == strings.PHASE_STOP[1]
    assert m.toolTipsVisible()
    acts[1].trigger()
    assert ran == ["stop"]
    host.deleteLater()


# --- in the window ------------------------------------------------------------------------------------------------ #
def test_in_the_window_anki_miners_press_while_mining_goes_to_its_title_and_stop_is_its_rows_stop(world, monkeypatch):
    win = world.win
    item = _mining()
    monkeypatch.setattr(win, "_mining_now", lambda: (11, item))
    shown, settings, stopped = [], [], []
    monkeypatch.setattr(win.search, "show_row", lambda group, key: shown.append((group, key)))
    win.open_setting = lambda target: settings.append(target) or True
    from types import SimpleNamespace                                  # (this window has no library: its list's look)
    monkeypatch.setitem(win.page_widgets, "current",
                        SimpleNamespace(list=SimpleNamespace(key_of=lambda fid: "row:ヤコブ書" if fid == 11 else None)))

    class Mine:
        def stop(self, ask):
            stopped.append(ask)
    win.mine = Mine()
    mine = world.registry.record(S.CONNECT_JOB_KIND, S.CONNECT_JOB_LABEL)   # (as the mirror lists it, shown at once)
    win.phase.set_jobs(world.registry.snapshot())
    assert win.phase.showing(P.MINER)
    win._circle_pressed(P.MINER)
    assert shown == [("current", "row:ヤコブ書")] and settings == []
    assert win._circle_stops(P.MINER)
    win._circle_asked(P.MINER, "stop")
    assert [(a.id, a.ids, a.job) for a in stopped] == [(11, (11,), 7)]   # the row's own Stop: its pill, its refusal
    monkeypatch.setattr(win, "_mining_now", lambda: (11, _mining(stoppable=False, stopping=True)))
    assert not win._circle_stops(P.MINER)                              # stopping already / past it: no Stop offered
    win._circle_asked(P.MINER, "settings")
    assert settings == ["connect_enabled"]
    mine.finish()


def test_in_the_window_a_circles_stop_cancels_its_own_cancellable_job(world):
    win = world.win
    cancelled = []
    job = world.registry.submit("backfill", "Backfill", lambda j: None, cancel=lambda j: cancelled.append(j.id))
    assert win._circle_stops(P.JUNBAN) and not win._circle_stops(P.SURASURA)
    win._circle_asked(P.JUNBAN, "stop")
    assert cancelled == [job.id] and job.view().state == J.CANCELLING
    job.finish(cancelled=True)


def test_in_the_window_junbans_press_while_it_reorders_opens_its_window(world, monkeypatch):
    win = world.win
    opened, settings = [], []
    monkeypatch.setattr(win, "_open_junban", lambda at=None: opened.append(at) or True)
    win.open_setting = lambda target: settings.append(target) or True
    replan = world.registry.record("replan", "Re-ordering Anki's new cards", automatic=False, on_quit="wait")
    win.phase.set_jobs(world.registry.snapshot())
    win.phase.set_opens(win.phase.opens - {P.JUNBAN})                  # Junban not here (the public checkout's look)
    win._circle_pressed(P.JUNBAN)                                       # ... nothing to open, nothing done
    assert opened == [] and settings == [] and not win.phase.showing(P.JUNBAN)
    win.phase.set_opens(win.phase.opens | {P.JUNBAN})                  # Junban found
    win._circle_pressed(P.JUNBAN)
    assert opened == [None] and settings == []
    replan.finish()
    win.phase.set_jobs(world.registry.snapshot())
    win._circle_pressed(P.JUNBAN)                                       # at rest: its settings, as before (alpha 3)
    assert opened == [None] and settings == ["junban"]


def test_on_the_seed_anki_miners_show_goes_to_its_row_washed_and_its_stop_marks_that_rows_pill(act, monkeypatch):
    """The real list: *Show* finds the mined file's row (`RowsView.key_of`) and washes it as a search hit is; *Stop*
    is the row's own (its pill reads *Stopping…* before the worker is handed the stop)."""
    from tests.qt.test_r47_stop import JOB, _item, _mining as mined_row, _watch_stop, lst_of
    from tests.qt.conftest import wait_until
    _seed, win, _writer = act()
    lst = lst_of(win)
    i, row = mined_row(lst)
    fid = row.episodes[0].id
    assert lst.key_of(fid) == row.key and lst.key_of(-1) is None
    monkeypatch.setattr(win, "_mining_now", lambda: (fid, _item()))
    washes = win.search.washes
    lst.scrollToTop()
    assert win._show_circle(P.MINER)
    assert wait_until(lambda: win.search.washes == washes + 1)
    assert win.current_tab() == "current" and lst.visualRect(lst.model().index(i, 0)).intersects(lst.viewport().rect())
    seen, calls, _n = _watch_stop(win, monkeypatch)
    win._circle_asked(P.MINER, "stop")
    assert seen and fid in seen[0][0]                                 # *Stopping…* on its row, before the worker
    assert wait_until(lambda: calls == [(win.language, JOB)])
