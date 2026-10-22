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
from app.qt import add_menu, rows, settings_sources, strings
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

    def folders(self, ids, then):
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


def test_settings_lists_the_folders_and_stop_reading_keeps_every_episode(window):
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    folder = _source()
    answer = _added(looks, folder)
    page, row = _sources_row(win)
    assert wait_until(lambda: answer["root"] in row.lines, 10)
    line = row.lines[answer["root"]]
    assert line.count.text() == S.SOURCES_COUNT.format(n=2)
    assert "stay in your library" in line.stop.toolTip()       # the words say the items stay
    assert row.add.toolTip() and row.look.toolTip()
    line.stop.click()
    assert wait_until(lambda: not row.lines, 10)
    assert win.bar_line.full() == S.SOURCES_STOPPED.format(path=ls.folder_path(folder), n=2)
    assert not row.none.isHidden()                            # the empty state, its Add a folder… beside it
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
    away = folder + " (away)"
    os.rename(folder, away)                                   # the drive went
    try:
        win.refresh_sources()
        want = strings.SOURCES_OFFLINE.format(path=ls.folder_path(folder), n=2)
        assert wait_until(lambda: not win.offline_line.isHidden() and win.offline_line.text() == want, 10)
    finally:
        os.rename(away, folder)
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
    row = tray.rows[first.key]
    assert row.arrival.chip == "Anime"
    assert strings.SOURCES_FROM.format(name="Anime") in row.arrival.accessible
    shown = row.arrival
    win._show_arrivals(win._arrivals_view)                    # the same view again: nothing asked, nothing repainted
    assert row.arrival is shown and len(looks.asked_folders) == 1


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
    rows_ = [{"id": 1, "path": "S:\\Video", "on": True, "items": 412, "reachable": False},
             {"id": 2, "path": "D:\\Books", "on": True, "items": 0, "reachable": True},
             {"id": 3, "path": "E:\\Old", "on": False, "items": 9, "reachable": False},
             {"id": 4, "path": "F:\\New", "on": True, "items": 3, "reachable": None}]
    assert source_looks.offline(rows_) == [("S:\\Video", 412)]


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
    page, row = _sources_row(win)
    win._sources_looked({"language": win.language, "sources": [{"id": 2, "path": r"D:\アニメ", "on": True,
                                                                  "items": 5, "reachable": True}]})
    assert 2 in row.lines
    new = RecordingLooks()
    win.services.source_looks = new
    win.language = "zh"
    win._follow_looks(None)
    assert row.lines == {} and not row.none.isHidden()        # the zh library's folders, none yet
    win._sources_looked({"language": "ja", "sources": [{"id": 2, "path": r"D:\アニメ", "on": True, "items": 5,
                                                        "reachable": False}]})
    assert row.lines == {} and win.offline_line.isHidden()     # the language left's late answer: dropped
    opener, _d, _u = _library()
    looks = source_looks.SourceLooks(opener, "zh", kind=lambda _p: "network")
    try:
        assert looks.stop(2, language="ja") is False           # a ja line's id never reaches the zh store
    finally:
        looks.close()


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
    page, row = _sources_row(win)
    summary = {"language": win.language, "sources": [{"id": 3, "path": r"D:\Shows", "on": True, "items": 9,
                                                       "reachable": True}]}
    win._sources_looked(summary)
    reads = row.reads
    win._sources_looked(dict(summary, sources=[dict(s) for s in summary["sources"]]))
    assert row.reads == reads
    win._sources_looked(dict(summary, sources=[dict(summary["sources"][0], items=10)]))
    assert row.reads == reads + 1 and row.lines[3].count.text() == S.SOURCES_COUNT.format(n=10)


def test_settings_waits_for_the_first_listing_before_saying_no_folders(window):
    seed, win = window(RecordingLooks())
    page, row = _sources_row(win)
    assert row.none.text() == S.SOURCES_LISTING
    win._sources_looked({"language": win.language, "sources": []})
    assert row.none.text() == S.SOURCES_NONE and not row.none.isHidden()
