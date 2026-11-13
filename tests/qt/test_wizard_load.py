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
from app.qt import covers as qcovers
from app.qt import sort_screen
from app.qt import wizard_strings as S
from app.services import view_rows
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
        shell.services.chores = Chores(log, runs=runs)
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
    assert shell.services.chores.asked == [True]
    QTest.qWait(1200)
    assert _task(wiz) == S.LOAD_INDEX_START, "never the earlier run's count"
    with open(log, "w", encoding="utf-8") as f:
        f.write("Indexer: starting (ja)\nIndexer: 3 of 7\n")
    assert wait_until(lambda: _task(wiz) == S.LOAD_INDEX.format(done=3, total=7), 5)
    shell.services.chores.running = False                                               # the indexer's run ended
    assert wait_until(lambda: _task(wiz) == S.LOAD_COVERS.format(done=2, total=2), 5)
    assert asked == [1]
    hold.set()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 5)
    assert wiz.index == 2
    # Mado-P: the sort screen covers the wizard by geometry, outside its layout; the wizard's minimum holds its room,
    # so the window's (`first_run._Cover`) never lets it be cut off
    need, hint = wiz.covered.minimumSizeHint(), wiz.minimumSizeHint()
    assert hint.width() >= need.width() and hint.height() >= need.height()
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.covered is None and wiz.index == 3


def test_runs_that_keep_coming_end_the_step_after_three(make, empty_library, tmp_path):
    """The library changing all along keeps the indexer busy run after run: after three runs the step goes on
    whatever is left (the indexer finishes it behind the window) — never stuck."""
    wiz, shell, _log = _start(make, tmp_path)
    wiz.next()
    assert wait_until(lambda: _task(wiz) == S.LOAD_INDEX_START, 30)
    assert shell.services.chores.running
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
    assert shell.services.chores.asked == [True]


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
    assert shell.services.chores.asked == []                                            # stopped: no indexing asked
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
    shell.services.chores.running = False
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


# --- Mado-SB: *Show covers* in force before the sort pad ---------------------------------------------------------- #
class _Fetcher:
    """The window's online covers fetcher as `covers.ask` uses it: `on()` reads the switch from the settings as they
    stand (as `covers_online.Fetcher.on` does, before every request), `want` records what was handed on."""

    def __init__(self, settings):
        self.settings, self.wanted = settings, []

    def on(self):
        return self.settings.get().get("covers_download") is True

    def want(self, wants):
        self.wanted.extend(wants)
        return len(wants)


@pytest.fixture
def fetcher():
    made = []

    def install(settings):
        f = _Fetcher(settings)
        qcovers.use_fetcher(f, lambda ids: list(ids))          # (the store read stood in for: the ids handed on)
        made.append(f)
        return f
    yield install
    qcovers.use_fetcher(None)


def _shows(*titles):
    """Two titles as New arrivals hands them to the pad: generated covers (no picture yet), each its own work."""
    rows = []
    for i, title in enumerate(titles, start=1):
        fields = {f: None for f in view_rows.Arrival._fields}
        fields.update(key=f"w{i}", work_id=900 + i, item_ids=(i * 10, i * 10 + 1), rel_paths=(), title=title,
                      media="anime", media_word="video", group="new", cover_title=title, line="Ep 1–2", parts=(),
                      episodes=(), cover=(900 + i, "generated", None, None, False))
        rows.append(view_rows.Arrival(**fields))
    return (view_rows.ArrivalGroup("new", "New", tuple(rows), tuple(a.key for a in rows)),)


def _to_the_pad(wiz, shell):
    _covers(shell, counts=())
    wiz.next()
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)
    wiz.covered.set_groups(_shows("小林さんちのメイドラゴン", "ぼっち・ざ・ろっく！"))
    QTest.qWait(50)


def test_show_covers_on_is_written_before_the_read_so_the_sort_pad_asks_its_covers(make, empty_library, tmp_path,
                                                                                   fetcher):
    """Mado-SB (the release shots, F2): a first run, *Show covers* on (its default) — the page saved it only after
    the sort pad's *Done*, so the pad's titles were never asked online and showed plain tiles. *Next* with folders
    writes it before the read: the pad's titles are asked as they paint, never waiting on the pad (asked on a
    worker); *Done* writes nothing again (a second write would ask every title on screen once more)."""
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    settings = shell.services.settings
    assert "covers_download" not in settings.data                       # a first run: nothing saved yet
    f = fetcher(settings)
    wiz.next()
    assert settings.data.get("covers_download") is True, "written as Next leaves the page, before the load"
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 30)
    wiz.covered.set_groups(_shows("小林さんちのメイドラゴン", "ぼっち・ざ・ろっく！"))
    assert wait_until(lambda: {w for w in f.wanted} >= {901}, 5), "the pad's top title asked online as it painted"
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.covered is None and wiz.index == 3
    assert [c for c in settings.calls if "covers_download" in c] == [{"covers_download": True}]
    assert [s for s in wiz.saves if s[0] == "shows"] == [("shows", {"covers": True})]


def test_show_covers_off_asks_nothing_online_on_the_sort_pad(make, empty_library, tmp_path, fetcher):
    """The network rule (CLAUDE.md §1): *Show covers* turned off on page 3 — written off before the read, and the
    pad's titles paint their generated covers with nothing handed to the fetcher."""
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    settings = shell.services.settings
    f = fetcher(settings)
    page = wiz.page
    QTest.mouseClick(page.covers.switch, Qt.MouseButton.LeftButton)
    assert page.covers.switch.isChecked() is False
    assert "covers_download" not in settings.data, "the click alone writes nothing (Skip's contract: nothing written)"
    _to_the_pad(wiz, shell)
    assert settings.data.get("covers_download") is False
    wiz.covered.repaint()
    QTest.qWait(300)
    assert f.wanted == [] and qcovers._online["asked"] == set()
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert [c for c in settings.calls if "covers_download" in c] == [{"covers_download": False}]


def test_show_covers_changed_after_an_early_write_is_written_again_by_next(make, empty_library, tmp_path):
    """Page 3 written once (as a read's *Next* writes it), then the switch turned off on the page: the next *Next*
    writes the off — the skip of a repeat never keeps a later choice from being saved."""
    wiz, shell, _log = _start(make, tmp_path, chores=False)
    settings = shell.services.settings
    wiz._save_shows(wiz.page)
    assert settings.calls[-1] == {"covers_download": True}
    page = wiz.page
    page.folders.clear()
    QTest.mouseClick(page.covers.switch, Qt.MouseButton.LeftButton)
    wiz.next()
    assert settings.calls[-1] == {"covers_download": False} and wiz.index == 3


def test_a_next_refused_while_the_last_links_still_come_writes_no_covers(make, empty_library):
    """Review (Mado-SB R1): *Next* refused — the last YouTube links still coming — writes nothing: a Skip after it
    (Skip writes nothing) never leaves `covers_download` on that the learner may yet turn off."""
    wiz, shell, _api, settings, _m = make(api=SourcesApi())
    go_to(wiz, "shows")
    page = wiz.page
    page.links_part.setVisible(True)
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI")
    page.yt_risk.switch.set_quiet(True)
    wiz.fetching = {"links": 1}                                          # (the last fetch still running)
    try:
        wiz.next()
        assert page.refused_line.text() == S.YOUTUBE_BUSY
        assert "covers_download" not in settings.data and not [s for s in wiz.saves if s[0] == "shows"]
    finally:
        wiz.fetching = None


def test_a_covers_write_that_failed_is_tried_again_at_the_next_next(make, empty_library, tmp_path, monkeypatch):
    """Review (Mado-SB R2): the write raised (said in the bar) — the page's next *Next* writes it again, never skipped
    as a repeat of a write that never landed."""
    wiz = _start(make, tmp_path, chores=False)[0]
    settings = wiz.shell.services.settings
    real = wiz.api.save
    failed = []

    def save(service, page, answers, language):
        if page == "shows" and not failed:
            failed.append(page)
            raise OSError("settings.json is held by another program")
        return real(service, page, answers, language)
    monkeypatch.setattr(wiz.api, "save", save)
    wiz._save_shows(wiz.page)
    assert failed and "covers_download" not in settings.data
    wiz.page.folders.clear()
    wiz.next()
    assert settings.data.get("covers_download") is True and wiz.index == 3


def test_the_load_asks_the_real_windows_chores_never_an_attribute_the_window_lacks(qapp, tmp_path):
    """Kantan-B1 (its adversary's find, 2026-11-12): the load read `shell.chores`, which the real window doesn't have
    (its chores are its services'), so in the app the words step was passed by and setup never said *Reading the
    words*; the stand-in shells here had one. The load built on the real window finds the window's own chores."""
    from tests.qt.test_jobs_bar import World
    world = World(qapp, logs_folder=str(tmp_path / "logs"))
    try:
        assert not hasattr(world.win, "chores")
        run = sort_screen.LoadRun(world.win, lambda widget: None)
        assert run._chores() is world.services.chores and run._chores() is not None
    finally:
        world.close()
