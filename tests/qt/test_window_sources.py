"""The window reads the folders (SRC W1b; the RUNBOOK §1b S4, S10 / D5, S14 / D6 and §3 W1): the shell's looks at the
source folders (`app/services/source_looks.py`, wired in `app/qt/shell.py`), + Add's *A folder…* read where it is,
Settings' *Library folders* row, the offline line, an arrival naming its folder and a video waiting for its subtitle.

What a wrong answer would cost a learner:
  * a look on every focus, or while the window is behind, is constant disk and network use on a laptop (SRC-9); a look
    on the window's thread freezes it on a slow share;
  * a Refresh that lists only what moved misses a file whose folder time didn't move (S4);
  * a local folder whose new episode waits an hour for the cadence, when Windows already said it arrived (D5);
  * a folder added after setup flooding Current with shows he never asked for (D6: they wait in New arrivals);
  * *Stop reading* that took his episodes, words and cards with it — or a refused folder that said nothing;
  * an offline drive that marks or moves anything (SRC-3), or whose line never goes when the drive is back;
  * a video with no subtitle yet that offers ▶ or waits to be mined.

Real Japanese subtitles from tests/Test Resources/, made-up show names, a real store in the test's own root; the
source folders sit beside the data folder ("elsewhere"), never inside it.
"""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import sources
from app.qt import add_menu, rows, settings_sources, strings, windows
from app.qt import settings_strings as S
from app.services import source_looks, view_rows as vr
from tests import services_helpers as h
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, _stones_sheet, open_window  # noqa: F401  (the stones' sheet fixture)
from tests.test_library_store_support import library, write_manifest

SHOW = "月影の旅人"                    # made-up show names
OTHER = "星降る街の工房"


@pytest.fixture(autouse=True)
def _fresh_run():
    """Each test starts as a new run of the app: no look made yet, none running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    FakeWatch.made.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


# --- helpers ----------------------------------------------------------------------------------------------------- #
def _subtitle(folder, name, n):
    """A real subtitle at `folder/name`, settled (a minute old: never the half-written wait), told apart by a line."""
    with open(os.path.join(h.RESOURCES, "ja", "phrases_sample.srt"), encoding="utf-8") as f:
        text = f.read()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + f"\n{n}\n")
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


def _source(name="Anime", shows=(SHOW,), episodes=2):
    """A source folder on the second "drive" (beside the data folder): shows of real subtitles."""
    root = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", name)
    n = 0
    for show in shows:
        for e in range(1, episodes + 1):
            n += 1
            _subtitle(os.path.join(root, show), f"{show} - {e:02d}.ja.srt", n)
    return root


def _library():
    """An empty 3.0 store (setup's start) and the window's opener on it -> (opener, data_dir, user_files_dir)."""
    data_dir, user_files_dir, doc = library("ja", shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    opener = ls.StoreOpener("ja", data_dir, user_files_dir)
    assert opener.check() == "store"
    return opener, data_dir, user_files_dir


def _read_store(data_dir, user_files_dir):
    return ls.open_store("ja", data_dir, user_files_dir)


class Clock:
    def __init__(self, t=10000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeWatch:
    """`library_watch.TreeWatch` as the looks use it: started, its settled folders taken; `report()` is Windows saying
    a file arrived under it."""
    made = []

    def __init__(self, path, wake, start=True):
        self.path, self.wake, self._start = path, wake, start
        self.state = "closed"
        self.pending = False
        FakeWatch.made.append(self)

    def start(self):
        self.state = "watching" if self._start else "fallback"
        return self._start

    def close(self):
        self.state = "closed"

    def due(self):
        return 0.0 if self.pending else None

    def take(self):
        if self.pending:
            self.pending = False
            return [SHOW], False
        return [], False

    def report(self):
        self.pending = True
        self.wake.set()


@pytest.fixture
def scans(monkeypatch):
    """Every `sources.scan` the looks run: (thread, root, kwargs) — the real scan still runs."""
    calls = []
    real = sources.scan

    def spy(store, language, root, **kw):
        calls.append((threading.current_thread(), root, dict(kw)))
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", spy)
    return calls


@pytest.fixture
def looks_world():
    made = []

    def make(kind="network", watch=FakeWatch):
        opener, data_dir, user_files_dir = _library()
        clock = Clock()
        looks = source_looks.SourceLooks(opener, "ja", clock=clock, watch=watch, kind=lambda _p: kind, quiet=0.2)
        seen = []
        looks.on_result = seen.append
        made.append(looks)
        return looks, clock, seen, (data_dir, user_files_dir)
    yield make
    for looks in made:
        looks.close()
        looks.idle(5)


def _added(looks, folder):
    answers = []
    assert looks.add(folder, answers.append)
    assert looks.idle(30)
    return answers[0]


# --- the cadence (SRC-9, S4) --------------------------------------------------------------------------------------- #
def test_the_window_focused_twice_within_five_minutes_looks_once_and_the_first_look_lists_everything(looks_world,
                                                                                                      scans):
    looks, clock, _seen, _dirs = looks_world()
    _added(looks, _source())
    scans.clear()
    assert looks.asked(focused=True)
    assert looks.idle(10)
    clock.t += 60                                             # a minute later: back to the window again
    assert not looks.asked(focused=True)
    assert looks.idle(10)
    assert len(scans) == 1 and scans[0][2]["full"] is True    # the first look after start: everything listed
    clock.t += sources.FOCUS_S + 1                            # five minutes on: the next focus looks, only what moved
    assert looks.asked(focused=True)
    assert looks.idle(10)
    assert len(scans) == 2 and scans[1][2]["full"] is False


def test_nothing_is_looked_at_while_the_window_is_behind_or_minimized(looks_world, scans):
    looks, clock, _seen, _dirs = looks_world()
    _added(looks, _source())
    scans.clear()
    assert not looks.asked(focused=True, shown=False)
    clock.t += sources.HOURLY_S + 1
    assert not looks.asked(shown=False)                       # the hourly tick, behind another program
    assert looks.idle(10)
    assert scans == []
    assert looks.asked(shown=True)                            # in front again: the hour is up
    assert looks.idle(10)
    assert len(scans) == 1


def test_refresh_is_a_full_look_every_time_even_right_after_one(looks_world, scans):
    looks, clock, _seen, _dirs = looks_world()
    _added(looks, _source())
    scans.clear()
    assert looks.asked(focused=True)
    assert looks.idle(10)
    clock.t += 30
    assert looks.asked(refreshed=True)
    assert looks.idle(10)
    clock.t += 30
    assert looks.asked(refreshed=True, shown=False)           # his own press: even behind another program
    assert looks.idle(10)
    assert [c[2]["full"] for c in scans] == [True, True, True]
    clock.t += 30
    assert not looks.asked(focused=True)                      # and a focus right after still waits its five minutes


def test_a_look_asked_while_one_runs_is_one_more_after_it_and_never_two_at_once(looks_world, monkeypatch):
    looks, clock, _seen, _dirs = looks_world()
    _added(looks, _source())
    gate, running, most = threading.Event(), [0], [0]
    real = sources.scan

    def slow(store, language, root, **kw):
        running[0] += 1
        most[0] = max(most[0], running[0])
        gate.wait(10)
        try:
            return real(store, language, root, **kw)
        finally:
            running[0] -= 1
    monkeypatch.setattr(sources, "scan", slow)
    assert looks.asked(focused=True)
    assert not looks.asked(refreshed=True)                    # folded into one more after the running one
    assert not looks.asked(refreshed=True)
    gate.set()
    assert looks.idle(20)
    assert most[0] == 1 and looks.looks == 2


# --- the watch (S10 / D5) ---------------------------------------------------------------------------------------- #
def test_a_local_folders_watch_report_looks_at_that_folder_once_it_settles(looks_world, scans):
    looks, clock, _seen, _dirs = looks_world(kind="local")
    folder = _source()
    answer = _added(looks, folder)
    assert len(FakeWatch.made) == 1 and FakeWatch.made[0].path == folder
    scans.clear()
    FakeWatch.made[0].report()                                # Windows: a file arrived under it
    assert wait_until(lambda: len(scans) == 1, 5)
    assert scans[0][1] == answer["root"] and scans[0][2]["full"] is False
    assert scans[0][0] is not threading.main_thread()


def test_a_watch_turn_that_fails_never_ends_the_watches_for_the_run(looks_world, scans):
    """H10: an error in one turn of the watch thread (a dictionary changed while it was read) ended the thread: no
    watch report was ever looked at again that run. The turn is logged and the next report still looks."""
    class Flaky(FakeWatch):
        failed = []

        def take(self):
            if not Flaky.failed:
                Flaky.failed.append(True)
                self.pending = False
                raise RuntimeError("dictionary changed size during iteration")
            return super().take()
    looks, clock, _seen, _dirs = looks_world(kind="local", watch=Flaky)
    _added(looks, _source())
    scans.clear()
    FakeWatch.made[-1].report()                               # this turn fails
    assert wait_until(lambda: Flaky.failed, 5)
    time.sleep(0.2)
    FakeWatch.made[-1].report()                               # the next one is still heard
    assert wait_until(lambda: len(scans) == 1, 5)


def test_a_watch_report_while_the_window_is_behind_waits_for_its_focus(looks_world, scans):
    looks, clock, _seen, _dirs = looks_world(kind="local")
    _added(looks, _source())
    assert looks.asked(focused=True)
    assert looks.idle(10)
    scans.clear()
    looks.set_shown(False)
    FakeWatch.made[0].report()
    time.sleep(0.3)
    assert looks.idle(5) and scans == []                      # behind: nothing read
    clock.t += 10                                             # (within the five minutes: no cadence look)
    assert looks.asked(focused=True, shown=True)              # back in front: the folder it reported, looked at
    assert looks.idle(10)
    assert len(scans) == 1 and scans[0][2]["full"] is False


def test_a_network_folder_or_one_whose_watch_fails_gets_the_cadence_only(looks_world):
    looks, _clock, _seen, _dirs = looks_world(kind="network")
    _added(looks, _source("Share"))
    assert FakeWatch.made == []                               # a share: never watched
    looks2, _c, _s, _d = looks_world(kind="local", watch=lambda p, w: FakeWatch(p, w, start=False))
    _added(looks2, _source("Removable"))
    assert len(FakeWatch.made) == 1 and FakeWatch.made[0].state != "watching"
    assert looks2._watches == {}                              # the failed watch let go: the cadence looks there


# --- the window ---------------------------------------------------------------------------------------------- #
class RecordingLooks:
    """The looks as the shell calls them, recorded (`folders` answers from a dict)."""

    def __init__(self, folders=None):
        self.asks, self.shown, self.closed = [], [], False
        self.on_result = self.on_progress = None
        self._folders = folders or {}
        self.asked_folders = []

    def asked(self, focused=False, refreshed=False, shown=True):
        self.asks.append((focused, refreshed, shown))
        return True

    def set_shown(self, shown):
        self.shown.append(shown)

    def folders(self, ids, then, detail=False):
        self.asked_folders.append(list(ids))
        then({i: self._folders.get(i) for i in ids})
        return True

    def listing(self):
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def window(qapp):
    made = []

    def make(looks):
        seed = window_seed.build()
        win, services = open_window(qapp, seed, FakeWriter(seed.library, apply=False))
        services.source_looks = looks
        win._open_looks(None)
        made.append((win, services))
        return seed, win
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def test_the_shell_looks_on_focus_refresh_and_the_tick_and_holds_while_behind(window, monkeypatch):
    looks = RecordingLooks()
    seed, win = window(looks)
    looks.asks.clear()
    monkeypatch.setattr(win, "in_front", lambda: True)
    win.changeEvent(QEvent(QEvent.Type.ActivationChange))
    win.look_key.activated.emit()                             # the Refresh key
    win._look_tick.timeout.emit()                             # the tick
    assert looks.asks == [(True, False, True), (False, True, True), (False, False, True)]
    monkeypatch.setattr(win, "in_front", lambda: False)
    win.changeEvent(QEvent(QEvent.Type.WindowStateChange))    # minimized
    win._look_tick.timeout.emit()
    assert looks.shown[-1] is False and looks.asks[-1] == (False, False, False)   # `due` refuses it: behind
    assert win.look_key.key() == QKeySequence(QKeySequence.StandardKey.Refresh)


def test_no_look_ever_runs_on_the_windows_thread(window, scans, monkeypatch):
    opener, _data, _uf = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    _added(looks, _source())
    scans.clear()
    monkeypatch.setattr(win, "in_front", lambda: True)
    t0 = time.perf_counter()
    assert win.refresh_sources()
    assert time.perf_counter() - t0 < 0.5                     # asked, never waited for
    assert wait_until(lambda: scans and looks.idle(0), 10)
    assert all(thread is not threading.main_thread() for thread, _r, _kw in scans)


@pytest.mark.parametrize("held, handed", [
    ({"source": "wait"}, {"hato": "after-show", "source": "wait"}),       # the user's own Wait for folders reaches it
    ({}, {"hato": "after-show", "source": "after-show"}),                 # {}: the defaults, merged per key
    ({"hato": "top"}, {"hato": "top", "source": "after-show"}),           # partial: the folders' default kept
])
def test_a_look_hands_take_in_the_windows_frozen_rules_merged_per_key(monkeypatch, held, handed):
    """SRC W1 fix (the lead's call 3): the window hands the looks its settings service's `placing_rules`, which are
    frozen (a mapping, never a dict). The look read only a dict, so a user's own rule — folders set to *Wait here* —
    never reached `take_in` (its default placed them); now every look hands the rules merged per key."""
    from app.services.settings import freeze
    opener, _d, _u = _library()
    got = []
    real = sources.scan

    def scan(store, language, root, **kw):
        got.append(kw.get("rules"))
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", scan)
    looks = source_looks.SourceLooks(opener, "ja", rules=lambda: freeze(held), kind=lambda _p: "network")
    try:
        answers = []
        assert looks.add(_source(), answers.append)
        assert wait_until(lambda: answers, 30)
        assert got == [handed] and not answers[0].get("refused")
    finally:
        looks.close()
    bare = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    try:
        assert bare._rules_now() is None, "no rules reader: take_in's own default"
    finally:
        bare.close()


def test_add_a_folder_reads_it_where_it_is_and_its_shows_wait_in_new_arrivals(window, monkeypatch):
    # D6: a folder added after setup lands as a later look does: shows never shown wait in New arrivals
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    folder = _source(shows=(SHOW, OTHER))
    before = sorted(os.listdir(os.path.join(folder, SHOW)))
    monkeypatch.setattr(add_menu, "pick_folder", lambda _parent: folder)
    given = []
    win.adder.given.connect(given.append)
    win.adder.run("folder")
    want = strings.SOURCES_READ_ARRIVALS.format(name="Anime", added=4)
    assert wait_until(lambda: win.bar_line.full() == want, 30)
    assert given == [want]
    store = _read_store(data_dir, user_files_dir)
    try:
        assert [s["path"] for s in store.sources()] == [ls.folder_path(folder)]
        rows_ = store.conn.execute("SELECT tier, rel_path FROM items").fetchall()
        assert len(rows_) == 4 and {t for t, _r in rows_} == {"arrivals"}
        assert all(r.startswith(f"{ls.CONTENT_FOLDER}/") for _t, r in rows_)     # Surasura's own copy
    finally:
        store.close()
    assert sorted(os.listdir(os.path.join(folder, SHOW))) == before            # nothing written in his folder


def test_a_folder_that_cant_be_a_source_says_why_and_nothing_is_written(window, monkeypatch):
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    monkeypatch.setattr(add_menu, "pick_folder", lambda _parent: data_dir)    # the library's own folder
    win.adder.run("folder")
    assert wait_until(lambda: win.bar_line.full().startswith(
        strings.SOURCES_REFUSED.format(name=os.path.basename(data_dir), reason="")), 10)
    assert len(win.bar_line.full()) > len(strings.SOURCES_REFUSED.format(name=os.path.basename(data_dir), reason=""))
    store = _read_store(data_dir, user_files_dir)
    try:
        assert store.sources(all=True) == []
    finally:
        store.close()


def _sources_row(win):
    page = win.mount_settings()
    assert wait_until(lambda: page.findChildren(settings_sources.SourcesRow), 10)
    return page, page.findChildren(settings_sources.SourcesRow)[0]


def _folders_window(win):
    """Settings' row, then its *Manage folders…* door pressed -> (page, row, the *Library folders* window)."""
    page, row = _sources_row(win)
    assert wait_until(lambda: page.row(settings_sources.ROW_ID) is not None, 20)
    door = page.row(settings_sources.ROW_ID).doors[settings_sources.WINDOW]
    assert door.text() == S.DOORS["library-folders"][0] and door.toolTip()
    door.click()
    folders = windows.opened(win, settings_sources.WINDOW)
    assert isinstance(folders, settings_sources.FoldersWindow) and folders.isVisible()
    return page, row, folders


def test_settings_lists_the_folders_and_stop_reading_keeps_every_episode(window):
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    folder = _source()
    answer = _added(looks, folder)
    page, row, folders = _folders_window(win)
    assert wait_until(lambda: answer["root"] in folders.lines, 10)
    assert row.summary.text() == S.SOURCES_FOLDERS_ONE
    line = folders.lines[answer["root"]]
    assert line.count.text() == S.SOURCES_COUNT.format(n=2)
    assert "stay in your library" in line.stop.toolTip()       # the words say the items stay
    assert row.add.toolTip() and folders.add.toolTip() and folders.look.toolTip()
    line.stop.click()
    assert wait_until(lambda: not folders.lines, 10)
    assert win.bar_line.full() == S.SOURCES_STOPPED.format(path=ls.folder_path(folder), n=2)
    assert not folders.none.isHidden()                        # the empty state, its Add a folder… beside it
    assert row.summary.text() == S.SOURCES_NONE                # the page's summary followed the stop
    store = _read_store(data_dir, user_files_dir)
    try:
        assert store.sources() == [] and store.sources(all=True)[0]["on"] is False
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2   # every episode kept
    finally:
        store.close()


def test_a_folder_offline_shows_one_quiet_line_that_goes_when_it_is_back(window, monkeypatch):
    opener, data_dir, user_files_dir = _library()
    clock = Clock()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network", clock=clock)
    seed, win = window(looks)
    folder = _source()
    _added(looks, folder)
    assert wait_until(lambda: win.sources, 10)
    assert win.offline_line.isHidden()
    from tests.test_sources_gone import unplug
    back = unplug(monkeypatch, folder)                        # the drive went (T6: away, never gone — the line)
    try:
        win.refresh_sources()
        want = strings.SOURCES_OFFLINE.format(path=ls.folder_path(folder), n=2)
        assert wait_until(lambda: not win.offline_line.isHidden() and win.offline_line.text() == want, 10)
    finally:
        back()
    store = _read_store(data_dir, user_files_dir)
    try:                                                      # nothing moved or marked (SRC-3)
        assert {r[0] for r in store.conn.execute("SELECT availability FROM items")} == {"available"}
    finally:
        store.close()
    monkeypatch.setattr(win, "in_front", lambda: True)
    clock.t += sources.HOURLY_S + 1                           # back again: the hourly look finds it
    win._look_tick.timeout.emit()
    assert wait_until(lambda: win.offline_line.isHidden(), 10)
    assert win.offline_line.text() == ""


def test_an_arrival_from_a_source_names_its_folder_and_is_repainted_once(window):
    seed, win = window(RecordingLooks())
    tray = win.arrivals_tray
    assert wait_until(lambda: tray.groups, 10)
    first = tray.groups[0].rows[0]
    folder = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Anime")
    looks = RecordingLooks({first.item_ids[0]: folder})
    win.services.source_looks = looks
    win._open_looks(None)
    win._show_arrivals(win._arrivals_view)
    shown = tray.arrival(first.key)                           # (A4: what the tray holds, open or not)
    assert shown.chip == "Anime"
    assert strings.SOURCES_FROM.format(name="Anime") in shown.accessible
    groups = tray.groups
    win._show_arrivals(win._arrivals_view)                    # the same view again: nothing asked, nothing repainted
    assert tray.groups is groups and tray.arrival(first.key) is shown and len(looks.asked_folders) == 1


# --- a video waiting for its subtitle (K5's `waiting`) ------------------------------------------------------------- #
def _waiting_items():
    from tests.test_view_rows import items_of, work, WORKS
    WORKS.clear()
    work(1, SHOW)
    work(2, OTHER)
    names = [f"{SHOW} - {n:02d}.mkv" for n in (1, 2)]
    items = items_of([("now", 1, 1, names, {0: {"availability": "waiting", "rel_path": f"Library/{SHOW}/{names[0]}"},
                                             1: {"availability": "waiting", "rel_path": f"Library/{SHOW}/{names[1]}"}}),
                      ("arrivals", 2, 2, [f"{OTHER} - 01.mkv"],
                       {0: {"availability": "waiting", "rel_path": f"Library/{OTHER}/{OTHER} - 01.mkv"}})])
    return items, WORKS


def test_a_video_waiting_for_its_subtitle_says_so_and_cant_be_played_or_mined():
    items, works = _waiting_items()
    view = vr.build(items, works, {"mine_line": 20})
    row = view.rows[0]                                        # in Current, inside the top 20: still never Waiting
    assert all(not e.can_play and e.waiting for e in row.episodes)
    assert all(e.play_tip == vr.STRINGS["play_waiting"].format(word="video") for e in row.episodes)
    assert all(e.status.kind == "no_subs" for e in row.episodes)
    assert row.status.kind == "no_subs" and row.status.label == vr.STRINGS["no_subs_n"].format(n=2)
    assert not row.can_play
    assert rows.STATUS_ICON["no_subs"] == "waiting"           # its own pill, never Mine's or No video's
    arrival = view.arrivals[0]
    assert arrival.waiting == 1 and (vr.STRINGS["arr_no_subs"], "dim") in arrival.parts


def test_a_filled_gap_reads_as_any_episode_again():
    items, works = _waiting_items()
    for item in items.values():
        item["availability"] = "available"
        item["rel_path"] = item["rel_path"][:-4] + ".ja.srt"
    row = vr.build(items, works, {"mine_line": 20}).rows[0]
    assert all(e.can_play and not e.waiting for e in row.episodes) and row.status.kind == "waiting"


def test_without_the_looks_a_folder_is_copied_in_as_before(qapp):
    # no store open (a 2.x library): + Add's folder still does something — the copy it always did
    seed = window_seed.build()
    win, services = open_window(qapp, seed, FakeWriter(seed.library, apply=False))
    try:
        win.looks = None
        asked = []
        win.adder.add_folder = asked.append
        assert win.adder.read_folder(os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Anime")) is False
        assert len(asked) == 1
    finally:
        win.close()
        services.shutdown(0.5)
    QApplication.processEvents()


def test_a_closed_window_closes_its_looks(window):
    looks = RecordingLooks()
    seed, win = window(looks)
    win.close()
    assert looks.closed


def test_the_offline_words_name_each_folder_and_its_count():
    rows_ = [{"id": 1, "path": "N:\\Media", "on": True, "items": 412, "reachable": False},
             {"id": 2, "path": "D:\\Books", "on": True, "items": 0, "reachable": True},
             {"id": 3, "path": "E:\\Old", "on": False, "items": 9, "reachable": False},
             {"id": 4, "path": "F:\\New", "on": True, "items": 3, "reachable": None}]
    assert source_looks.offline(rows_) == [("N:\\Media", 412)]


# --- the review's rows (reviews/SRC-W1b-adversary.md) -------------------------------------------------------------- #
@pytest.mark.skipif(not __import__("app.library_watch", fromlist=["x"]).watchable(), reason="Windows' change reports")
def test_B1_a_just_downloaded_episode_is_taken_in_by_the_watch_without_waiting_for_the_cadence(looks_world):
    # a real watch on a real folder: the file lands fresh (younger than the scan's half-written wait), and the watch's
    # one look comes once the folder has been quiet past that wait — never at the next focus or the hourly look
    from app import library_watch
    looks, _clock, _seen, (data_dir, user_files_dir) = looks_world(
        kind="local", watch=lambda p, w: library_watch.TreeWatch(p, wake=w))
    folder = _source()
    _added(looks, folder)
    looks._quiet = sources.SETTLE_S + 0.5
    path = os.path.join(folder, SHOW, f"{SHOW} - 03.ja.srt")
    with open(os.path.join(h.RESOURCES, "ja", "phrases_sample.srt"), encoding="utf-8") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8", newline="\n") as f:      # just downloaded: its time is now
        f.write(text + "\n3\n")

    def items():
        store = _read_store(data_dir, user_files_dir)
        try:
            return store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        finally:
            store.close()
    assert wait_until(lambda: items() == 3, sources.SETTLE_S + 8)


def test_B1_S7_a_long_download_is_one_look_at_its_end_never_one_per_burst(looks_world, scans):
    looks, _clock, _seen, _dirs = looks_world(kind="local")
    _added(looks, _source())
    looks._quiet = 0.4
    scans.clear()
    for _ in range(5):                                        # five bursts, each inside the quiet spell
        FakeWatch.made[0].report()
        time.sleep(0.15)
    assert scans == []
    assert wait_until(lambda: len(scans) == 1, 5)
    time.sleep(0.6)
    assert len(scans) == 1


def test_B2_after_a_language_switch_settings_shows_that_librarys_folders_and_a_stale_stop_is_refused(window):
    old = RecordingLooks()
    seed, win = window(old)
    page, row, folders = _folders_window(win)
    win._sources_looked({"language": win.language, "sources": [{"id": 2, "path": r"D:\アニメ", "on": True,
                                                                  "items": 5, "reachable": True}]})
    assert 2 in folders.lines and row.summary.text() == S.SOURCES_FOLDERS_ONE
    new = RecordingLooks()
    listed = []
    new.listing = lambda: listed.append(True) or True
    win.services.source_looks = new
    win.language = "zh"
    win._follow_looks(None)
    assert listed == [True]                                   # the zh library's listing asked for at once
    assert folders.lines == {} and folders.none.text() == S.SOURCES_LISTING   # on its way: never "No folders yet"
    assert row.summary.text() == S.SOURCES_LISTING
    win._sources_looked({"language": "ja", "sources": [{"id": 2, "path": r"D:\アニメ", "on": True, "items": 5,
                                                        "reachable": False}]})
    assert folders.lines == {} and win.offline_line.isHidden()  # the language left's late answer: dropped
    assert row.summary.text() == S.SOURCES_LISTING
    win._sources_looked({"language": "zh", "sources": [], "skipped": []})     # the zh listing: none yet
    assert row.summary.text() == S.SOURCES_NONE and folders.none.text() == S.SOURCES_NONE
    assert not folders.none.isHidden()
    opener, _d, _u = _library()
    looks = source_looks.SourceLooks(opener, "zh", kind=lambda _p: "network")
    try:
        assert looks.stop(2, language="ja") is False           # a ja line's id never reaches the zh store
    finally:
        looks.close()


def test_row55_a_look_says_how_many_known_files_it_found_a_video_for_and_a_quiet_one_none(looks_world):
    """Row 55 IK-1 (S19): the summary's `moved` counts the known files a look recorded a video on (a video come after
    its subtitle) — the window asks ▶'s looks again only then; a look that found nothing new says 0."""
    looks, clock, seen, _dirs = looks_world()
    folder = _source()
    _added(looks, folder)
    clock.t += sources.FOCUS_S + 1
    assert looks.asked(focused=True) and looks.idle(10)
    assert seen[-1]["moved"] == 0
    _stand_in_video(os.path.join(folder, SHOW, f"{SHOW} - 01.mkv"))      # downloaded after its subtitle
    clock.t += sources.FOCUS_S + 1
    assert looks.asked(focused=True) and looks.idle(10)
    assert seen[-1]["moved"] == 1
    clock.t += sources.FOCUS_S + 1
    assert looks.asked(focused=True) and looks.idle(10)
    assert seen[-1]["moved"] == 0


def test_B2_a_closed_looks_tells_no_one_what_it_still_finds():
    opener, _d, _u = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    told = []
    looks.on_result = told.append
    looks.close()
    looks._publish(None, {})
    assert told == []


def test_S3_a_library_with_no_store_copies_the_folder_in(window, monkeypatch):
    class NoStore(RecordingLooks):
        def add(self, path, then, first=False):
            then({"path": path, "refused": "no-library"})
            return True
    seed, win = window(NoStore())
    copied = []
    monkeypatch.setattr(win.adder, "add_folder", copied.append)
    folder = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Anime")
    win.adder.read_folder(folder)
    assert wait_until(lambda: copied == [folder], 5)


@pytest.mark.parametrize("refused, want", [
    ("busy", strings.SOURCES_BUSY.format(name="Anime")),
    ("damaged", strings.SOURCES_REFUSED.format(name="Anime", reason=strings.READ_ONLY_REASONS["damaged"])),
    ("io: disk I/O error", strings.SOURCES_REFUSED.format(name="Anime", reason=strings.READ_ONLY_IO)),
], ids=["busy", "damaged", "disk-error"])
def test_P1_a_busy_or_read_only_store_is_said_in_the_bar_and_never_copies_the_folder_in(window, monkeypatch,
                                                                                        refused, want):
    # why (P-1, MV-1: never a duplicate): only a library with no store copies a folder in; a store busy past its wait
    # says to try again (nothing was added), a read-only one says why in the store's own words — and nothing is written
    class Closed(RecordingLooks):
        def add(self, path, then, first=False):
            then({"path": path, "refused": refused})
            return True
    seed, win = window(Closed())
    copied = []
    monkeypatch.setattr(win.adder, "add_folder", copied.append)
    folder = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Anime")
    win.adder.read_folder(folder)
    assert wait_until(lambda: win.bar_line.full() == want, 5), win.bar_line.full()
    assert copied == []


def test_S4_a_video_waiting_for_its_subtitle_never_takes_a_place_on_the_mine_line():
    items, works = _waiting_items()
    from tests.test_view_rows import items_of
    more = items_of([("now", 2, 3, [f"{OTHER} - {n:02d}.srt" for n in (2, 3)], {})])
    for k, row_ in more.items():
        row_["id"] = 100 + k
    items.update({r["id"]: r for r in more.values()})
    view = vr.build(items, works, {"mine_line": 1})
    other = next(r for r in view.rows if r.title == OTHER)
    assert other.episodes[0].in_top                           # the first available file is the one mined


def test_S5_a_paired_episode_still_names_its_folder(looks_world):
    looks, _clock, _seen, (data_dir, user_files_dir) = looks_world()
    folder = _source()
    _added(looks, folder)
    store = ls.open_store("ja", data_dir, user_files_dir, role="window")
    try:
        item_id = store.conn.execute("SELECT MIN(id) FROM items").fetchone()[0]
        with store._writing():                                # hato pairs it afterwards: its record comes first
            store.conn.execute("INSERT INTO pairings (item_id, content_key, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               (item_id, "v1-made-up-key", '{"producer": "hato"}', "2026-10-16T00:00:00Z"))
    finally:
        store.close()
    found = []
    looks.folders([item_id], found.append)
    assert looks.idle(10)
    assert found == [{item_id: ls.folder_path(folder)}]


def test_S6_stop_reading_lets_a_running_look_go_between_files(looks_world, monkeypatch):
    looks, _clock, _seen, _dirs = looks_world()
    answer = _added(looks, _source())
    gate, started, asked_stop = threading.Event(), threading.Event(), []
    real = sources.scan

    def slow(store, language, root, **kw):
        started.set()
        gate.wait(10)
        asked_stop.append(kw["stop"]())
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", slow)
    assert looks.asked(focused=True)
    assert started.wait(10) and looks.busy()                  # the look is reading the folder now
    assert looks.stop(answer["root"], language="ja")
    gate.set()
    assert looks.idle(20)
    assert asked_stop == [True]


def test_S15_an_equal_summary_repaints_no_line(window):
    seed, win = window(RecordingLooks())
    page, row, folders = _folders_window(win)
    summary = {"language": win.language, "sources": [{"id": 3, "path": r"D:\Shows", "on": True, "items": 9,
                                                       "reachable": True}]}
    win._sources_looked(summary)
    reads, paints = folders.reads, row.paints
    win._sources_looked(dict(summary, sources=[dict(s) for s in summary["sources"]]))
    assert folders.reads == reads and row.paints == paints
    win._sources_looked(dict(summary, sources=[dict(summary["sources"][0], items=10)]))
    assert folders.reads == reads + 1 and folders.lines[3].count.text() == S.SOURCES_COUNT.format(n=10)
    assert row.paints == paints                                # one folder still: the page's words never moved


def test_settings_waits_for_the_first_listing_before_saying_no_folders(window):
    seed, win = window(RecordingLooks())
    page, row, folders = _folders_window(win)
    assert row.summary.text() == S.SOURCES_LISTING and folders.none.text() == S.SOURCES_LISTING
    win._sources_looked({"language": win.language, "sources": []})
    assert folders.none.text() == S.SOURCES_NONE and not folders.none.isHidden()
    assert row.summary.text() == S.SOURCES_NONE


# --- ▶ on an episode a source folder holds (laptop fix "play", FEEDBACK row 5) ------------------------------------ #
def _episode_name(n, ext):
    """A release's name, as a download folder holds them: `[group] <show> - 09 (1080p) [crc].mkv` (made-up group)."""
    return f"[Hoshizora Subs] {SHOW} - {n:02d} (1080p) [8F3A2C1D]{ext}"


def _stand_in_video(path):
    """A video stand-in (Matroska's magic and a few bytes), settled like a finished download — never played."""
    with open(path, "wb") as f:
        f.write(b"\x1a\x45\xdf\xa3 stand-in matroska " + os.path.basename(path).encode("utf-8"))
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


def _part(lst, i, name, payload=None):
    entry = lst.model().entries[i]
    for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))):
        if p[0] == name and (payload is None or p[3] is payload):
            return p
    raise AssertionError((i, name))


def test_play_opens_the_video_beside_the_original_in_a_source_folder_and_says_why_when_there_is_none(qapp,
                                                                                                     monkeypatch):
    """▶ on an episode a source folder holds (FEEDBACK row 5: *the play button doesn't play the media*). The library's
    entry is the subtitle's copy in `Library/<show>/`; the video stays in the folder read in place, so looking beside
    the copy found nothing and every ▶ said "no video beside it". The row's own ▶ (its next episode) and an episode's ▶
    must ask the opener for the video's absolute path: the one the scan recorded beside the original, or one that
    arrived after its subtitle (looked for beside the original by name); with no video, a line in the bar says so."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import Qt
    from app.qt import screens, shell
    from app.services import library_reader, play
    from app.services import moves as moves_module
    opener, data_dir, user_files_dir = _library()
    opener.close()
    folder = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Downloads", SHOW)
    for n in (9, 10, 11):
        _subtitle(folder, _episode_name(n, ".ja.srt"), n)
    video_09 = _stand_in_video(os.path.join(folder, _episode_name(9, ".mkv")))      # there at the scan: recorded
    store = _read_store(data_dir, user_files_dir)
    with store:
        root = store.add_source(folder)
        assert sources.scan(store, "ja", root, first=True)["added"] == 3
    video_10 = _stand_in_video(os.path.join(folder, _episode_name(10, ".mkv")))     # downloaded after its subtitle
    opened = []
    monkeypatch.setattr(screens, "open_with_system", opened.append)                # never a real player
    monkeypatch.setattr(screens.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    reader = library_reader.LibraryReader(moves_module.store_opener("ja"), "ja", poll=0.02)
    services = shell.Services(library=reader)
    win = shell.open_window(qapp, services)
    try:
        win.resize(1280, 900)
        win.show()
        page = win.page_widgets["current"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full"
                          and not page.view_model.loading, 15)
        for _ in range(50):
            QApplication.processEvents()
        lines = []
        page.message.connect(lines.append)
        lst = page.list
        kind, hero, _lines = lst.model().entries[0]
        assert kind == rows.HERO and len(hero.episodes) == 3
        same = lambda a, b: os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))  # noqa: E731
        # the row's own ▶: its next episode (09), whose video the scan found beside the original
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=_part(lst, 0, "play")[1].center())
        assert wait_until(lambda: opened or lines, 10)
        assert lines == [] and len(opened) == 1 and same(opened[0], video_09)
        # an episode's ▶ in the opened row: 10's video came after its subtitle — found beside the original by name
        lst.toggle(lst.model().index(0, 0))
        for _ in range(20):
            QApplication.processEvents()
        ep10, ep11 = hero.episodes[1], hero.episodes[2]
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=_part(lst, 0, "play", ep10)[1].center())
        assert wait_until(lambda: len(opened) > 1 or lines, 10)
        assert lines == [] and len(opened) == 2 and same(opened[1], video_10)
        # 11 has no video anywhere: nothing opens, and the bar says which episode and why
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=_part(lst, 0, "play", ep11)[1].center())
        assert wait_until(lambda: lines, 10)
        assert len(opened) == 2
        assert lines[0] == strings.PLAY_FAILED.format(name=ep11.label, why=play.WHY["no-media"].format(word="video"))
        assert win.bar_line.full() == lines[0]
    finally:
        win.close()
        services.shutdown(2.0)
    QApplication.processEvents()


# --- the opener: COM around Windows' open, the shell's opens through it (review AD-3, AD-9) ----------------------- #
@pytest.mark.skipif(os.name != "nt", reason="Windows' opener")
def test_the_opener_sets_up_com_around_each_open_and_undoes_only_its_own(monkeypatch):
    """▶'s opener on a pool thread: COM is set up before Windows is asked and undone after, once per open — also when
    Windows refuses the file; when the thread had COM in another mode already (RPC_E_CHANGED_MODE), it's left so."""
    import threading
    from app.qt import screens
    calls = []

    class Ole32:
        def __init__(self, answer):
            self.answer = answer

        def CoInitializeEx(self, _reserved, flags):
            calls.append(("init", flags))
            return self.answer

        def CoUninitialize(self):
            calls.append(("uninit",))
    monkeypatch.setattr(os, "startfile", lambda path: calls.append(("open", path)))   # never a real player
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], _episode_name(9, ".mkv"))
    for answer, expected in ((0, [("init", 0x6), ("open", path), ("uninit",)]),           # S_OK
                             (1, [("init", 0x6), ("open", path), ("uninit",)]),           # S_FALSE: still ours to undo
                             (-2147417850, [("init", 0x6), ("open", path)])):             # RPC_E_CHANGED_MODE
        calls.clear()
        monkeypatch.setattr(screens, "_ole32", lambda answer=answer: Ole32(answer))
        t = threading.Thread(target=screens.open_with_system, args=(path,))
        t.start()
        t.join(10)
        assert calls == expected
    calls.clear()
    monkeypatch.setattr(screens, "_ole32", lambda: Ole32(0))

    def refused(p):
        calls.append(("open", p))
        raise OSError("No application is associated with the specified file")
    monkeypatch.setattr(os, "startfile", refused)
    with pytest.raises(OSError):
        screens.open_with_system(path)
    assert calls == [("init", 0x6), ("open", path), ("uninit",)]


@pytest.mark.skipif(os.name != "nt", reason="Windows' opener")
def test_the_shells_open_folder_and_open_file_go_through_the_same_opener_on_a_worker(window, monkeypatch):
    """AD-9: the logs folder and a log file open as ▶'s file does (COM set up), off the window's thread."""
    import threading
    from app.qt import screens
    seed, win = window(RecordingLooks())
    asked = []
    monkeypatch.setattr(screens, "open_with_system", lambda p: asked.append((p, threading.current_thread())))
    monkeypatch.setattr(os, "startfile", lambda p: asked.append(("bare", p)))
    logs = os.path.join(os.environ["SURASURA_TEST_ROOT"], "local", "logs")
    log = os.path.join(logs, "generate.log")
    win.open_logs(logs)
    from app.qt import press as qpress
    qpress.open(win, log)                                   # (a log file: Generate's *Open the log*)
    assert wait_until(lambda: len(asked) == 2, 10)
    assert sorted(p for p, _t in asked) == sorted([logs, log])
    assert all(t is not threading.main_thread() for _p, t in asked)


def test_a_watch_whose_drive_went_is_removed_from_the_held_watches(looks_world):
    # why: a watch that ended (its drive went) must leave the held watches, or the watch thread keeps it and the
    # folder is never watched again when the drive comes back; a watch that is still watching stays held.
    looks, clock, _seen, _dirs = looks_world(kind="local")
    answer = _added(looks, _source())
    root = answer["root"]
    watch = FakeWatch.made[0]
    looks.set_shown(False)                                    # behind: the watch thread only notes its roots (no look
                                                              # runs, so nothing else tidies the held watches)
    assert looks._watches.get(root) is watch                  # held while its drive is there
    watch.report()                                            # a report while still watching...
    assert wait_until(lambda: root in looks._dirty, 5)        # ...is taken and noted by the watch thread
    assert looks._watches.get(root) is watch                  # and the watch that is still watching stays held
    looks._dirty.clear()
    watch.state = "closed"                                    # the drive went: the watch has ended
    watch.report()                                            # (wakes the watch thread to look at it)
    assert wait_until(lambda: root in looks._dirty, 5)        # the watch thread has looked at it...
    assert root not in looks._watches                         # ...and let the ended watch go


def test_a_watch_started_while_the_looks_are_closing_is_closed_at_once(looks_world):
    # why: a watch the window's close overtook while it was being set up is closed on the spot, never kept: a kept
    # watch would outlive the window and keep reporting into it.
    class ShutsAsItStarts(FakeWatch):
        def start(self):
            looks._closing.set()                       # the window shuts while this watch is being set up
            return super().start()

    looks, _clock, _seen, _dirs = looks_world(kind="local", watch=ShutsAsItStarts)
    assert looks.add(_source(), lambda answer: None)
    assert looks.idle(30)
    assert len(FakeWatch.made) == 1
    assert FakeWatch.made[0].state == "closed"
    assert not looks._watches                          # never kept: nothing holds the closing window's watch


def test_a_refresh_merged_into_a_held_focus_look_keeps_every_folder_and_raises_nothing(looks_world, monkeypatch):
    # why: a focus look held for a folder a watch reported while the window was behind, then a Refresh folded into
    # it: the merged look must read every folder (full), and folding the two asks together must not raise
    looks, clock, _seen, _dirs = looks_world(kind="local")
    _added(looks, _source())
    gate, kws = threading.Event(), []
    real = sources.scan

    def slow(store, language, root, **kw):
        kws.append(dict(kw))
        gate.wait(10)
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", slow)
    try:
        assert looks.asked(focused=True)                      # the first look runs and holds the worker
        looks.set_shown(False)
        FakeWatch.made[0].report()
        assert wait_until(lambda: bool(looks._dirty), 10)     # the watch's folder is recorded while the window is behind
        looks.set_shown(True)
        assert not looks.asked(focused=True)                  # its focus: that folder held for one more look
        assert not looks.asked(refreshed=True)                # Refresh folded into it: still every folder, no error
    finally:
        gate.set()                                            # the worker is released even when an assert above failed
    assert looks.idle(20)
    assert looks.looks == 2
    assert len(kws) == 2 and all(kw["full"] is True for kw in kws)


def test_a_watch_folder_merged_into_a_held_refresh_keeps_every_folder_and_raises_nothing(looks_world, monkeypatch):
    # why: the reverse order: a Refresh held first (every folder, so the held roots are None), then a watch's folder
    # folded into it on the window's focus: the merge must not raise on None | set, and the merged look reads every
    # folder (full)
    looks, clock, _seen, _dirs = looks_world(kind="local")
    _added(looks, _source())
    gate, kws = threading.Event(), []
    real = sources.scan

    def slow(store, language, root, **kw):
        kws.append(dict(kw))
        gate.wait(10)
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", slow)
    try:
        assert looks.asked(focused=True)                      # the first look runs and holds the worker
        assert not looks.asked(refreshed=True)                # Refresh held for one more look: every folder (roots None)
        looks.set_shown(False)
        FakeWatch.made[0].report()
        assert wait_until(lambda: bool(looks._dirty), 10)     # the watch's folder is recorded while the window is behind
        assert not looks.asked(focused=True)                  # its focus: that folder folded into the held Refresh
    finally:
        gate.set()                                            # the worker is released even when an assert above failed
    assert looks.idle(20)
    assert looks.looks == 2
    assert len(kws) == 2 and all(kw["full"] is True for kw in kws)


def test_a_watch_report_made_while_the_window_is_behind_waits_until_it_is_in_front(looks_world, scans):
    # why: a folder that changed while the window was behind is looked at when the window comes to the front, not
    # on the first focus event that happens to arrive while another program still has the window's place
    looks, clock, _seen, _dirs = looks_world(kind="local")    # a local folder is the one Windows reports arrivals for
    _added(looks, _source())
    assert not looks.asked(shown=False)                       # behind another program: the window is not in front
    scans.clear()
    watch = FakeWatch.made[-1]
    watch.report()                                            # Windows: a file arrived under the folder, behind the window
    assert wait_until(lambda: not watch.pending, 10)          # the watch thread has taken the report
    assert wait_until(lambda: bool(looks._dirty), 10)         # its quiet time has passed: the folder is kept for the focus
    assert looks.idle(10)
    assert not looks.asked(focused=True, shown=False)         # focus while still behind: nothing is looked at yet
    assert looks.idle(10)
    assert scans == []
    assert looks.asked(focused=True, shown=True)              # in front: the report's folder is looked at now
    assert looks.idle(10)
    assert len(scans) == 1


def test_a_full_look_asked_while_a_partial_one_runs_runs_full_after_it(looks_world, monkeypatch):
    # why: a Refresh asked while a cadence look is still reading must read every folder once the running look ends;
    # a partial follow-up skips the folders whose time did not move, so a learner's new episode in an unchanged folder
    # would stay unread until the next look.
    looks, clock, _seen, _dirs = looks_world()
    _added(looks, _source())
    gate, scans = threading.Event(), []
    real = sources.scan

    def slow(store, language, root, **kw):
        # why: a stop callback is a new closure each look, so only the plain options are compared
        scans.append((root, sorted((k, v) for k, v in kw.items() if not callable(v))))
        gate.wait(10)
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", slow)
    try:                                                      # the gate opens even when an assertion fails
        assert looks.asked(focused=True)                      # a cadence look starts and waits at the gate
        assert not looks.asked(refreshed=True)                # held: it runs full after the running look
    finally:
        gate.set()
    assert looks.idle(20)
    assert len(scans) == 2
    assert looks.asked(refreshed=True)                        # an idle Refresh now: the reference for a full read
    assert looks.idle(20)
    assert len(scans) == 3
    assert ("full", True) in scans[1][1]                      # the held Refresh reads full...
    assert scans[1][1] == scans[2][1]                         # ...exactly as an idle Refresh does


def test_a_held_full_look_merged_with_a_later_partial_ask_still_runs_full(looks_world, monkeypatch):
    # why: a Refresh (full) held behind a running look must not be made partial by a watch's partial ask asked after it.
    looks, clock, _seen, _dirs = looks_world(kind="local")
    folder = _source()
    _added(looks, folder)
    gate, asks = threading.Event(), []
    real = sources.scan

    def slow(store, language, root, **kw):
        asks.append(kw["full"])
        gate.wait(10)
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", slow)
    queued, real_queue = [], looks._queue

    def record(full, roots):                                  # record each look offered to the worker, in order
        queued.append(full)
        return real_queue(full, roots)
    monkeypatch.setattr(looks, "_queue", record)
    try:                                                      # the gate opens even when an assertion fails: no worker left parked
        assert looks.asked(refreshed=True)                    # a full look runs and waits at the gate
        assert not looks.asked(refreshed=True)                # a full ask held behind it (folded, one more after it)
        FakeWatch.made[0].report()                            # Windows: a file arrived: the watch's partial ask
        assert wait_until(lambda: False in queued, 5)         # the partial ask has been folded into the held look
        gate.set()
        assert wait_until(lambda: len(asks) == 2, 10)
        assert looks.idle(20)
        assert asks == [True, True]                           # the look after it is still full
    finally:
        gate.set()


def test_stop_takes_the_folder_out_of_the_followed_set(looks_world):
    # why: a stopped folder must leave the followed set, or the watch keeps reading a folder the learner has stopped
    looks, _clock, _seen, _dirs = looks_world(kind="local")   # only a local folder gets a watch to follow
    answer = _added(looks, _source())
    assert looks.asked(focused=True)                          # a look follows the folder
    assert looks.idle(20)
    assert answer["root"] in looks._watches                   # the folder is followed before the Stop
    assert looks.stop(answer["root"], language="ja")
    assert looks.idle(20)
    assert answer["root"] not in looks._watches


def test_stop_reading_clears_its_flag_so_the_folder_reads_again_when_added_back(looks_world, monkeypatch):
    """Once *Stop reading* has answered, the folder's stop flag is gone, so a later read of it is not stopped."""
    # why: `_stopping` holds the folder only while its stop runs; if the flag outlives the stop, a folder added back
    # (its row turned on again) has its scan stopped at once, and nothing reports that it was never read.
    looks, _clock, _seen, _dirs = looks_world()
    answer = _added(looks, _source())
    flags = []
    real = sources.scan

    def watched(store, language, root, **kw):
        flags.append(kw["stop"]())
        return real(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", watched)
    assert looks.stop(answer["root"], language="ja")
    assert looks.idle(20)
    flags.clear()
    assert _added(looks, _source())
    assert flags and not any(flags)                          # the re-added folder's read is not stopped


def test_after_close_a_waiting_watch_pass_queues_nothing_for_the_window(looks_world, scans):
    # why: a watch pass that wakes after the looks are closed must return at once; a window that is closing
    # must not be queued a look (the drive went while the pass waited, so the pass would otherwise report it)
    class Signalling(FakeWatch):
        # the pass calls due() once it has taken its snapshot of the watches, then waits: that call is the sync point
        def __init__(self, path, wake, start=True):
            super().__init__(path, wake, start)
            self.snapshotted = threading.Event()

        def due(self):
            self.snapshotted.set()
            return super().due()

    looks, _clock, _seen, _dirs = looks_world(kind="local", watch=Signalling)
    folder = _source()
    _added(looks, folder)
    scans.clear()
    queued = []
    looks._queue = lambda *args, **kwargs: queued.append(args)   # a look queued for the window (its own method)
    looks._dirty = set()
    watch = FakeWatch.made[0]
    watch.state = "ended"                                 # the drive went while the pass waits
    assert watch.snapshotted.wait(5)                      # the pass has its snapshot and is waiting now
    looks.close()
    watch.report()                                        # wakes the waiting pass, now that the looks are closed
    looks._watcher.join(5)                                # the pass has returned: nothing after this can still come
    assert not looks._watcher.is_alive()
    assert queued == [] and not looks._dirty
    assert scans == []


def test_a_new_watch_is_stored_only_once_the_watches_lock_is_free(looks_world):
    # why: the closing flag is read and the watch stored under the watches lock, so a close cannot slip in between;
    # a watch that finishes starting while the lock is held waits for it and is not stored until it is free.
    entered, go = threading.Event(), threading.Event()

    class GatedWatch(FakeWatch):
        def start(self):
            entered.set()
            go.wait(5)
            return super().start()

    looks, _clock, _seen, _dirs = looks_world(kind="local", watch=GatedWatch)
    answers = []
    assert looks.add(_source(), answers.append)
    assert entered.wait(5)
    with looks._lock:
        go.set()
        assert wait_until(lambda: FakeWatch.made[-1].state == "watching", 5)   # the watch has finished starting
        # why: storing is the very next step after the start returns, so a watch stored without the lock shows within
        # this grace however loaded the machine (a wait on a condition can't stand in: the right answer is no change)
        time.sleep(0.3)
        assert looks._watches == {}
        looks._closing.set()                                  # the close lands while the watch waits for the lock
    assert wait_until(lambda: FakeWatch.made[-1].state == "closed", 5)   # closed, not stored: the flag was read under the lock
    assert looks._watches == {}
    assert looks.idle(30)
