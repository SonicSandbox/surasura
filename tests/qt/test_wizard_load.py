"""Setup's load screen, as the wizard runs it (Mado-O, Sonic 2026-10-30; `SetupWizard._load_*`): after page 3's *Next*
with folders, a calm cover runs, in order, the first look (its count), the words (the window's own indexer, its count
read from its log), the covers from disk (their count) and the wait for page 2's Anki sync — each passed when there is
nothing for it — then the sort screen; *Stop* keeps what each step did and goes to the sorting; the sort screen's *Done*
goes on to page 4. The steps are the services that own them: the window's chores, its covers' scan, page 2's sync.

What a wrong answer would cost a learner:
  * a setup stuck on a cover forever — a sync that never ran, an indexer that never ends, no covers to find;
  * a Stop that throws away the shows already read, or that leaves him on the load screen;
  * a count that never moves while 20,000 episodes are read;
  * a folder with nothing in it that leaves a blank cover instead of saying so on the page.

The wizard over its stand-in window (test_wizard's `make`) with the real store in a temp library; real Japanese
subtitles from tests/Test Resources/; the window's chores and covers stand-ins that record what they were asked.
"""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from app import library_store as ls
from app.qt import sort_screen
from app.qt import wizard_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import go_to, make  # noqa: F401  (`make`: the wizard, a stand-in window)
from tests.qt.test_wizard_sources import (LOOSE, SHOWS, SourcesApi, _fresh_look_state, _folder,  # noqa: F401
                                          _items, _pick, empty_library)
from tests.test_sources_scan import _drive


class Chores:
    """The window's chores as the load screen asks them: `index(force=True)` (started: None), its log's path, and
    whether an index ask is under way (`running`: set by an ask unless `runs` is False — nothing to read, an update
    waiting, a run that couldn't start)."""

    def __init__(self, log, answer=None, runs=True):
        self.log, self.answer, self.asked, self.runs = log, answer, [], runs
        self.running = False

    def index(self, force=False):
        self.asked.append(force)
        self.running = self.runs
        return self.answer

    def index_log(self):
        return self.log

    def indexing(self):
        return self.running


def _covers(shell, counts=((1, 2), (2, 2)), hold=None):
    """The window's `scan_covers(progress, then)`: a thread that counts `counts`, then ends (after `hold`, if set)."""
    asked = []

    def scan_covers(progress=None, then=None):
        asked.append(1)

        def run():
            for done, total in counts:
                progress(done, total)
            if hold is not None:
                hold.wait(10)
            then(len(counts))
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t
    shell.scan_covers = scan_covers
    return asked


def _start(make, tmp_path, chores=True, runs=True, folders=1):
    """The wizard on page 3, `folders` folders picked; the window's chores (its log in `tmp_path`) set."""
    wiz, shell, api, settings, _m = make(api=SourcesApi())
    log = str(tmp_path / "indexer-window.log")
    if chores:
        shell.chores = Chores(log, runs=runs)
    go_to(wiz, "shows")
    _pick(wiz, _folder("anime", SHOWS), *([_folder("dramas", LOOSE, start=100)] if folders > 1 else []))
    return wiz, shell, log


def _task(wiz):
    screen = wiz.covered
    return screen.task.text() if isinstance(screen, sort_screen.LoadScreen) else None


def test_the_steps_run_in_order_each_with_its_count_then_the_sort_screen(make, empty_library, tmp_path, monkeypatch):
    """The look, then the words (the window's indexer asked once, forced; its count read from its log), then the
    covers (their count), then — no sync running — the sort screen, which *Done* leaves for page 4."""
    wiz, shell, log = _start(make, tmp_path)
    with open(log, "w", encoding="utf-8") as f:                                # an earlier run's log, finished
        f.write("Indexer: 5000 of 5000\n")
    os.utime(log, (time.time() - 120, time.time() - 120))
    hold = threading.Event()
    asked = _covers(shell, hold=hold)
    wiz.next()
    assert isinstance(wiz.covered, sort_screen.LoadScreen)
    assert wait_until(lambda: _task(wiz) == S.LOAD_INDEX_START, 30)            # the look ended: the words
    assert shell.chores.asked == [True]
    QTest.qWait(1200)
    assert _task(wiz) == S.LOAD_INDEX_START, "never the earlier run's count"
    with open(log, "w", encoding="utf-8") as f:
        f.write("Indexer: starting (ja)\nIndexer: 3 of 7\n")
    assert wait_until(lambda: _task(wiz) == S.LOAD_INDEX.format(done=3, total=7), 5)
    shell.chores.running = False                                               # the indexer's run ended
    assert wait_until(lambda: _task(wiz) == S.LOAD_COVERS.format(done=2, total=2), 5)
    assert asked == [1]
    hold.set()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 5)
    assert wiz.index == 2
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.covered is None and wiz.index == 3


def test_runs_that_keep_coming_end_the_step_after_three(make, empty_library, tmp_path):
    """The library changing all along keeps the indexer busy run after run: after three runs the step goes on
    whatever is left (the indexer finishes it behind the window) — never stuck."""
    wiz, shell, _log = _start(make, tmp_path)
    wiz.next()
    assert wait_until(lambda: _task(wiz) == S.LOAD_INDEX_START, 30)
    assert shell.chores.running
    wiz._indexed("zh")                                                         # another language's run: not this one
    wiz._indexed("ja")
    wiz._indexed("ja")
    QTest.qWait(200)
    assert isinstance(wiz.covered, sort_screen.LoadScreen) and wiz._load["step"] == "index"
    wiz._indexed("ja")
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 5)


def test_no_indexer_no_covers_and_no_sync_pass_straight_to_the_sort_screen(make, empty_library, tmp_path):
    """Anki absent (page 2 never synced), no chores (indexing off), no covers to scan: each step is passed by."""
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    assert not wiz._sync_running
    wiz.next()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)


def test_an_index_ask_that_brings_no_run_ends_the_step(make, empty_library, tmp_path):
    """The ask was taken but no run comes — nothing left to read, an update waiting to install, an indexer that
    couldn't start: no `indexed` ever arrives, and the step still ends by itself (the chores idle)."""
    wiz, shell, _log = _start(make, tmp_path, runs=False)
    wiz.next()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)
    assert shell.chores.asked == [True]


def test_the_last_step_waits_for_page_twos_sync_and_goes_on_when_it_ends(make, empty_library, tmp_path):
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    wiz._sync_running = True                                                   # page 2's first sync, still running
    wiz.next()
    assert wait_until(lambda: _task(wiz) == S.LOAD_ANKI, 30)
    QTest.qWait(200)
    assert isinstance(wiz.covered, sort_screen.LoadScreen)
    wiz._synced_now()
    assert isinstance(wiz.covered, sort_screen.SortScreen)


def test_stop_while_reading_keeps_what_came_in_and_goes_to_the_sorting(make, empty_library, tmp_path, monkeypatch):
    """*Stop* mid-look: the show already taken in stays, whole, in New arrivals, and the sort screen comes up at once
    after the look ends — no indexing or covers waited for."""
    reached, release = threading.Event(), threading.Event()
    taken = []
    real_take_in = ls.Store.take_in

    def take_in(self, root_id, found, *a, **kw):
        change = real_take_in(self, root_id, found, *a, **kw)
        taken.append(list(change.added) if change is not None else [])
        if len(taken) == 1:
            reached.set()
            release.wait(10)
        return change
    monkeypatch.setattr(ls.Store, "take_in", take_in)
    wiz, shell, _log = _start(make, tmp_path, folders=2)
    wiz.next()
    assert wait_until(reached.is_set, 30)
    load = wiz.covered
    QTest.mouseClick(load.btn_stop, Qt.MouseButton.LeftButton)
    assert not load.btn_stop.isEnabled() and wiz.reading.is_set()
    release.set()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)
    assert shell.chores.asked == []                                            # stopped: no indexing asked
    items = _items()
    assert taken[0] and sorted(i for i, *_r in items) == sorted(taken[0])
    assert {t for _i, t, _o, _r in items} == {"arrivals"}
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.covered is None and wiz.index == 2, "page 3 stays: the folder never reached is still listed"
    assert len(wiz.page.folders) == 1 and not wiz.page.reading_line.isHidden()


def test_stop_while_the_words_are_read_goes_to_the_sorting_at_once(make, empty_library, tmp_path):
    wiz, shell, _log = _start(make, tmp_path)
    wiz.next()
    assert wait_until(lambda: _task(wiz) == S.LOAD_INDEX_START, 30)
    QTest.mouseClick(wiz.covered.btn_stop, Qt.MouseButton.LeftButton)
    assert isinstance(wiz.covered, sort_screen.SortScreen)
    wiz._indexed("ja")                                                         # the run ending later changes nothing
    shell.chores.running = False
    QTest.qWait(100)
    assert isinstance(wiz.covered, sort_screen.SortScreen)


def test_a_folder_with_nothing_to_read_lifts_the_cover_and_the_page_says_so(make, empty_library):
    wiz, shell, _api, _settings, _m = make(api=SourcesApi())
    go_to(wiz, "shows")
    _pick(wiz, _drive("nothing-here"))
    wiz.next()
    assert isinstance(wiz.covered, sort_screen.LoadScreen)
    assert wait_until(lambda: wiz.reading is None, 30)
    assert wiz.covered is None and wiz.index == 2 and not wiz.page.reading_line.isHidden()
    assert _items() == []


def test_the_wizard_takes_no_press_while_it_is_covered(make, empty_library, tmp_path):
    """Next, Back, Skip and Enter do nothing under the cover: only its own Stop, and the sort screen's own keys."""
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    wiz.next()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)
    for act in (wiz.next, wiz.back, wiz.skip, wiz.enter):
        act()
        assert wiz.index == 2 and isinstance(wiz.covered, sort_screen.SortScreen)
    assert wiz.covered.geometry() == wiz.rect()
    wiz.resize(wiz.width() - 40, wiz.height() - 30)
    assert wiz.covered.geometry() == wiz.rect()                                # it follows the wizard's size


class _Writer:
    """The window's writer, as `_load_sorted` reads it: `pending()` commands not yet saved."""

    def __init__(self, n):
        self.n = n

    def pending(self):
        return self.n


def test_the_cards_line_is_checked_only_once_the_sorts_places_are_saved(make, empty_library, tmp_path):
    """*Done* straight after the last key: D1's check (`sorted_offer`) waits until the writer has saved every place
    the sorting gave — never a check of the store before they landed, which would miss the line."""
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    writer = shell.services.writer = _Writer(2)
    seen = []
    api = wiz.api
    real = api.sorted_offer
    api.sorted_offer = lambda language, ids: (seen.append(writer.n), real(language, ids))[1]
    wiz.next()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.index == 3
    QTest.qWait(300)
    assert seen == []                                                          # two places still being saved
    writer.n = 0
    assert wait_until(lambda: seen == [0], 5)
