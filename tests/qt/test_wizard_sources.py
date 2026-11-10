"""Setup's page 3 asks where the shows and books are (SRC W1a; the RUNBOOK's §1b S1 + D1, W1): one or more folders
picked (the store's own rule refuses Surasura's folders in plain words; one removed before going on), then on *Next*
each added and given setup's first look on a worker — its progress line, *Stop*, the rows — landing in New arrivals
under the load screen, then sorted on the sort screen (Mado-O, Sonic 2026-10-30); *Needs you*'s one line after the
sorting, *Make cards for your first 20 episodes? · Not now* (D1, Sonic ✅), when the sorting put some in the line. Tier: one write path (K1a's) — the
writes are proven on a real store in a temp library.

What a wrong answer would cost a learner:
  * the window frozen for minutes while a whole drive is listed (the look on the window's thread);
  * a Stop that throws away what already came in, or leaves half a show;
  * Surasura reading its own data folder back in as new episodes (the trash, the word lists as books);
  * cards made for 20 episodes he never asked for — or *Make cards* that turns Connect on and then makes none,
    because its watermark came after the episodes were logged; *Not now* that writes anything at all.

Real Japanese subtitles from tests/Test Resources/ in temp folders beside the test's data folder, made-up show names.
"""
import os
import socket
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from app import library_store as ls
from app import path_utils, sources
from app.qt import needs as needs_ui
from app.qt import strings
from app.qt import wizard as W
from app.qt import wizard_strings as S
from app.services import needs as service
from app.services import setup_wizard
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import FakeAdder, FakeApi, go_to, make  # noqa: F401  (`make`: the wizard, a stand-in window)
from tests.test_library_store_support import library, write_manifest
from tests.test_sources_scan import _drive, _text, _write

SHOWS = {"月影の旅人": 3, "Hoshizora Kissa": 2}            # made-up shows in the first folder, episodes each
LOOSE = {"風鈴の街": 2}                                     # … and in the second
MINER = r"C:\Programs\Anki Miner\AnkiMiner.exe"            # row 13: Anki Miner's program, as a stand-in finds it


@pytest.fixture(autouse=True)
def _fresh_look_state():
    """Each test starts as a new run of the app: no look made yet, none running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


@pytest.fixture
def empty_library():
    """A 3.0 library with nothing in it yet (setup's start) -> its data folder."""
    data_dir, user_files_dir, doc = library("ja", shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    return data_dir


def _folder(name, shows, start=0):
    """A source folder ("another drive") holding `shows` {show: episodes}, real text each (told apart from `start` on:
    the same bytes in two folders are one episode, SRC-7)."""
    root = _drive(name)
    n = start
    for show, episodes in shows.items():
        for e in range(1, episodes + 1):
            _write(os.path.join(root, show, f"{show} - {e:02d}.ja.srt"), _text("ja", n))
            n += 1
    return root


def _store():
    return ls.open_store("ja", path_utils.get_data_path("ja"), path_utils.get_user_files_path("ja"))


def _items():
    store = _store()
    try:
        return store.conn.execute("SELECT id, tier, ord, rel_path FROM items ORDER BY id").fetchall()
    finally:
        store.close()


def _log():
    store = _store()
    try:
        return store.conn.execute("SELECT id, item_id, kind, by, explicit FROM placement_log ORDER BY id").fetchall()
    finally:
        store.close()


class SourcesApi(FakeApi):
    """The stand-in services, with page 3's folders and rows the real ones (`setup_wizard`) on the real store."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.read_threads = []

    def folder_refused(self, language, path):
        return setup_wizard.folder_refused(language, path)

    def read_folders(self, language, paths, progress=None, stop=None, **kw):
        self.read_threads.append(threading.current_thread())
        return setup_wizard.read_folders(language, paths, progress, stop, **kw)

    def library_rows(self, settings, language):
        self.calls.append(("library_rows", language))
        return setup_wizard.library_rows(settings, language)

    def sorted_offer(self, language, ids):
        self.calls.append(("sorted_offer", language, list(ids)))
        return setup_wizard.sorted_offer(language, ids)


def _sorted(wiz):
    """The load screen's steps pass by (the stand-in window has no indexer, covers or sync to wait for) and the sort
    screen covers the wizard; its *Done* goes on."""
    from app.qt import sort_screen
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), 10)
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.covered is None


def _pick(wiz, *paths):
    """*Choose a folder…* clicked once per path, the dialog answering it; each waits for the store's check."""
    page = wiz.pages[2]
    for path in paths:
        wiz.pick_dialog = lambda _title, _start, p=path: p
        before = (list(page.folders), page.refused_line.text())
        QTest.mouseClick(page.btn_pick, Qt.MouseButton.LeftButton)
        assert wait_until(lambda: (list(page.folders), page.refused_line.text()) != before)


def _remove_button(page, path):
    return next(b for b in page.folders_part.findChildren(QPushButton)
                if b.accessibleName() == S.FOLDER_REMOVE_NAME.format(folder=path))


# --- the page ----------------------------------------------------------------------------------------------------- #
def test_page_three_lists_two_folders_refuses_the_data_folder_and_one_is_removed_before_going_on(make, empty_library):
    """Two folders listed; the data folder refused with the store's own words (its scan would bring back the trash
    and the word lists as books); *Remove* takes one off — and nothing is added to the store before *Next*."""
    first, second = _folder("anime", SHOWS), _folder("dramas", LOOSE, start=100)
    wiz, *_ = make(api=SourcesApi())
    go_to(wiz, "shows")
    page = wiz.page
    assert not page.folders_part.isHidden() and page.btn_pick.text() == S.PICK_FOLDER
    _pick(wiz, first)
    assert page.btn_pick.text() == S.PICK_ANOTHER                  # one picked: *Add another folder…*
    _pick(wiz, second, path_utils.get_data_path("ja"))
    assert page.folders == [os.path.normpath(first), os.path.normpath(second)]
    store = _store()
    reason = store._not_a_source(path_utils.get_data_path("ja"))
    assert store.sources(all=True) == []                           # picking writes nothing
    store.close()
    assert reason and page.refused_line.text() == S.FOLDER_REFUSED.format(
        folder=os.path.normpath(path_utils.get_data_path("ja")), why=reason)
    assert not page.refused_line.isHidden()
    for b in page.folders_part.findChildren(QPushButton):           # every control says what it does
        assert b.toolTip()
    QTest.mouseClick(_remove_button(page, os.path.normpath(first)), Qt.MouseButton.LeftButton)
    assert page.folders == [os.path.normpath(second)]
    wiz.pick_dialog = lambda _title, _start: second.upper()         # the same folder again, spelt otherwise: once
    QTest.mouseClick(page.btn_pick, Qt.MouseButton.LeftButton)
    wait_until(lambda: False, 0.3)
    assert page.folders == [os.path.normpath(second)]


def test_next_reads_the_folders_on_a_worker_under_the_load_screen_and_they_wait_in_new_arrivals(make, empty_library,
                                                                                                 monkeypatch):
    """*Next* adds each folder and gives it setup's first look — on a worker, never the window's thread — with the
    progress line, under the load screen; the shows land in New arrivals for the sort screen (SRC-1 as Mado-O changed
    it), the page under it shows them as rows, and no cards line is offered yet (nothing is in the line). The sort
    screen's *Done* saves page 3 (the covers) and goes on to page 4."""
    first, second = _folder("anime", SHOWS), _folder("dramas", LOOSE, start=100)
    looks = []
    real_scan = sources.scan

    def scan(store, language, root, **kw):
        looks.append((threading.current_thread(), kw.get("first")))
        return real_scan(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", scan)
    api = SourcesApi()
    wiz, _shell, _api, settings, _m = make(api=api)
    go_to(wiz, "shows")
    page = wiz.page
    _pick(wiz, first, second)
    lines = []
    show_reading = page.show_reading
    monkeypatch.setattr(page, "show_reading", lambda f, s: (lines.append((f, s)), show_reading(f, s)))
    settings.calls.clear()
    wiz.next()
    from app.qt import sort_screen
    assert isinstance(wiz.covered, sort_screen.LoadScreen) and wiz.covered.isVisible()        # the calm cover, at once
    assert wiz.reading is not None and not page.btn_stop.isHidden()
    assert not wiz.btn_next.isEnabled() and not wiz.btn_back.isEnabled() and not wiz.btn_skip.isEnabled()
    assert page.reading_line.text() == S.READING.format(episodes="0 episodes", shows="0 shows")
    assert wait_until(lambda: wiz.reading is None, 30)
    main = threading.main_thread()
    assert looks and all(t is not main and first_ for t, first_ in looks)          # a worker's, setup's first look
    assert api.read_threads and api.read_threads[0] is not main
    assert lines and lines[-1] == (7, 3)                           # every folder's count so far, the last one whole
    assert page.reading_line.text() == S.READ_DONE.format(episodes="7 episodes", shows="3 shows")
    assert page.btn_stop.isHidden() and page.folders == [] and page.refused_line.isHidden()
    items = _items()
    assert len(items) == 7 and {tier for _i, tier, _o, _r in items} == {"arrivals"}           # New arrivals, to sort
    assert all(rel.startswith(ls.CONTENT_FOLDER + "/") for *_x, rel in items)
    assert wait_until(lambda: len(page.rows_part.findChildren(W.QLabel)) >= 3 and not page.rows_part.isHidden())
    names = {w.text() for w in page.rows_part.findChildren(W.QLabel)}
    assert set(SHOWS) | set(LOOSE) <= names
    assert service.read_offers("ja") == frozenset()               # nothing in the line yet: no cards line
    assert _log() == []                                            # the first look logs nothing (S1)
    assert wiz.index == 2 and settings.calls == []                 # under the cover; nothing saved yet
    wiz.next()
    assert wiz.index == 2, "Next does nothing while the wizard is covered"
    _sorted(wiz)
    assert wiz.index == 3 and settings.calls == [{"covers_download": True}]
    assert wait_until(lambda: any(c[0] == "sorted_offer" for c in api.calls), 10)
    assert sorted(next(c for c in api.calls if c[0] == "sorted_offer")[2]) == [i for i, *_r in items]
    assert service.read_offers("ja") == frozenset()               # nothing sorted into Current: still no line


def test_stop_keeps_what_came_in_whole(make, empty_library, monkeypatch):
    """*Stop* mid-look: the show already taken in stays, whole, in New arrivals; the look ends at the next file; the line
    says it stopped and kept them. The folder it never reached stays listed (never dropped unsaid), and so does one
    picked while it ran (the store's check landing mid-look)."""
    first, second = _folder("anime", SHOWS), _folder("dramas", LOOSE, start=100)
    late = _drive("picked-meanwhile")
    reached, release = threading.Event(), threading.Event()
    taken = []
    real_take_in = ls.Store.take_in

    def take_in(self, root_id, found, *a, **kw):
        change = real_take_in(self, root_id, found, *a, **kw)
        taken.append(list(change.added) if change is not None else [])
        if len(taken) == 1:
            reached.set()
            release.wait(10)                                       # held here until the test pressed Stop
        return change
    monkeypatch.setattr(ls.Store, "take_in", take_in)
    wiz, *_ = make(api=SourcesApi())
    go_to(wiz, "shows")
    page = wiz.page
    _pick(wiz, first, second)
    wiz.next()
    assert wait_until(reached.is_set, 30)
    page.add_folder(os.path.normpath(late))                        # as `pick_folder`'s check answers mid-look
    QTest.mouseClick(page.btn_stop, Qt.MouseButton.LeftButton)
    assert wiz.reading.is_set() and page.btn_stop.text() == S.STOPPING and not page.btn_stop.isEnabled()
    release.set()
    assert wait_until(lambda: wiz.reading is None, 30)
    assert len(taken) == 1 and taken[0]                            # one show came in, then it stopped
    items = _items()
    assert sorted(i for i, *_r in items) == sorted(taken[0])       # what came in is kept, and nothing more
    shows = {rel.split("/")[1] for *_x, rel in items}
    assert len(shows) == 1 and len(items) == SHOWS[shows.pop()]    # the show whole
    assert page.reading_line.text().startswith(S.READ_STOPPED.split("{")[0])
    assert all(os.path.exists(os.path.join(path_utils.get_data_path("ja"), *rel.split("/"))) for *_x, rel in items)
    assert page.folders == [os.path.normpath(second), os.path.normpath(late)]
    store = _store()
    try:
        assert [s["path"] for s in store.sources()] == [ls.folder_path(first)]          # the second never added
    finally:
        store.close()


@pytest.mark.parametrize("where, offered", [("soon", False), ("goal", False), ("top", True)])
def test_a_look_into_a_full_current_offers_the_line_only_for_what_was_sorted_into_it(where, offered):
    """*Set up again* or a library brought over: Current already holds its top 20. Setup's look puts the new episodes
    in New arrivals (never the line); the sorting decides: sent to Soon or Goal they stay outside the mine line — no
    line offers cards for episodes it wouldn't make them for — sent to *Current* (its top) they are in it, and the line
    is offered for them."""
    data_dir, user_files_dir, doc = library("ja", shows=3, episodes=8, loose=0, tiers=("now",))
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    got = setup_wizard.read_folders("ja", [_folder("anime", SHOWS)])
    assert got["added"] == 5 and not got["offered"] and service.read_offers("ja") == frozenset()
    assert len(got["ids"]) == 5 and {t for i, t, _o, _r in _items() if i in got["ids"]} == {"arrivals"}
    store = _store()
    try:
        assert store.place(got["ids"], where) is not None
    finally:
        store.close()
    assert setup_wizard.sorted_offer("ja", got["ids"]) is offered
    assert service.read_offers("ja") == (frozenset({service.FIRST_CARDS}) if offered else frozenset())


def test_going_on_refuses_surasuras_own_folder_and_an_empty_folder_offers_no_line(empty_library):
    """A folder refused when *Next* adds it (picked before the check could answer) is reported, never read, and nothing
    is offered while nothing came in: the cards line is only for what setup's look took in."""
    empty = _drive("nothing-yet")
    got = setup_wizard.read_folders("ja", [path_utils.get_data_path("ja"), empty])
    assert [p for p, _why in got["refused"]] == [path_utils.get_data_path("ja")] and got["refused"][0][1]
    assert got["added"] == 0 and not got["offered"] and service.read_offers("ja") == frozenset()
    store = _store()
    try:
        assert [s["path"] for s in store.sources()] == [ls.folder_path(empty)]      # only the folder it could read
    finally:
        store.close()
    assert _items() == []


def test_a_library_not_ready_keeps_the_folders_to_try_again(make, monkeypatch):
    """No library yet (the store not built): nothing is read, the line says so, the folders stay listed."""
    first = _folder("anime", SHOWS)
    monkeypatch.setattr(ls, "open_store", lambda *a, **kw: None)
    wiz, *_ = make(api=SourcesApi())
    go_to(wiz, "shows")
    _pick(wiz, first)
    wiz.next()
    assert wait_until(lambda: wiz.reading is None, 10)
    assert wiz.page.reading_line.text() == S.READ_NOT_READY and wiz.page.folders == [os.path.normpath(first)]


# --- Needs you's one line (D1) -------------------------------------------------------------------------------------- #
def _view(n):
    """A reader's view holding `n` episodes of one show in Current (what the line's count reads)."""
    eps = [SimpleNamespace(id=i, missing=False, rel_path=f"Library/月影の旅人/{i:02d}.srt") for i in range(1, n + 1)]
    row = SimpleNamespace(tier="now", episodes=eps, work_id=1, key="w1", title="月影の旅人", media="anime")
    return SimpleNamespace(mode="store", rows=[row], loading=False)


def test_the_line_is_offered_once_names_the_first_twenty_and_leaves_once_answered():
    assert service.entries(None) == []
    entry = service.entries(_view(25), offers={service.FIRST_CARDS})[0]
    assert entry.kind == service.FIRST_CARDS and entry.actions == ("first_cards", "not_now") and entry.unseen
    assert entry.title == "Make cards for your first 20 episodes?"
    assert service.entries(_view(5), offers={service.FIRST_CARDS})[0].title == "Make cards for your first 5 episodes?"
    assert service.entries(_view(25), offers={service.FIRST_CARDS}, answered={service.FIRST_CARDS}) == []
    assert service.offer("ja") == 1 and service.offer("ja") == 0   # offered once
    assert service.read_offers("ja") == {service.FIRST_CARDS} and service.read_offers("zh") == frozenset()
    service.mark_seen("ja", ["gone:1:abc"])
    assert service.read_offers("ja") == {service.FIRST_CARDS}      # a seen-file write keeps the offer
    assert service.prune("ja", _view(3), offline_roots=[], connect={"gaps": []}, asks=[]) >= 0
    assert service.read_offers("ja") == {service.FIRST_CARDS}      # never pruned: it goes only with its answer


class SpySettings:
    """The window's settings service: every call recorded (`set` would be a write)."""

    def __init__(self, on):
        self.data = {"connect_enabled": on, "target_language": "ja"}
        self.calls = []

    def get(self):
        return dict(self.data)

    def fresh(self):
        self.calls.append("fresh")
        return dict(self.data)

    def reload(self):
        self.calls.append("reload")

    def set(self, changes, update=None, now=False):
        self.calls.append(("set", dict(changes)))


class Heard(QObject):
    settings_written = pyqtSignal(object)


class LineWindow(QWidget):
    """What Needs you reads of the window, for its line alone: the services, the bridge, the bar."""

    def __init__(self, settings):
        super().__init__()
        self.services = SimpleNamespace(settings=settings, library=None, writer=None)
        self.bridge = Heard(self)
        self.said = []
        self.toasts = SimpleNamespace(show=self.said.append)
        self.moves = None

    def say(self, text):
        self.said.append(text)

    def current_tab(self):
        return "current"


@pytest.fixture
def line(qapp):
    """Needs you holding only D1's line, over a window stand-in -> (needs, window, settings, written)."""
    made = []

    def build(on, cards_on=False):
        settings = SpySettings(on)
        win = LineWindow(settings)
        area, cards = needs_ui.make_area(win)
        page = SimpleNamespace(cards=cards, show_entries=cards.show_entries)
        ny = needs_ui.NeedsYou(win, page, "ja")
        ny.find_miner = lambda _settings: MINER         # row 13: Anki Miner found (a stand-in; nothing real looked at)
        written = []
        win.bridge.settings_written.connect(written.append)
        ny.entries = tuple(service.entries(None, offers={service.FIRST_CARDS}, cards_on=cards_on))
        ny._paint()
        win.show()
        made.append(win)
        return ny, win, settings, written
    yield build
    for win in made:
        win.close()


def _answer(ny, action):
    b = next(b for b in ny.cards.buttons(service.FIRST_CARDS) if b.property("action") == action)
    assert b.toolTip() and not b.isHidden()
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)


def _first_scan(n_shows=2, episodes=12):
    """Setup's first look over one folder of `n_shows` × `episodes` (New arrivals), then the sort screen's *Current*
    for all of them (the store's own `place(…, "top")`, as `Writer.place` calls it) and its end (`sorted_offer`: D1's
    line offered) -> the store's items afterwards."""
    root = _folder("anime", {f"夜空の灯 {k}": episodes for k in range(1, n_shows + 1)})
    got = setup_wizard.read_folders("ja", [root])
    assert got["added"] == n_shows * episodes and not got["offered"]
    assert {tier for _i, tier, _o, _r in _items()} == {"arrivals"}
    store = _store()
    try:
        assert store.place(got["ids"], "top") is not None
    finally:
        store.close()
    assert setup_wizard.sorted_offer("ja", got["ids"]) is True
    return _items()


def _mine_line():
    store = _store()
    try:
        return store._mine_ids(store.meta().get("mine_line", ls.MINE_LINE_DEFAULT))
    finally:
        store.close()


def test_make_cards_turns_connect_on_as_settings_does_then_logs_the_first_twenty_as_yours(line, empty_library,
                                                                                         monkeypatch):
    """*Make cards* with Connect off: Settings › Anki's switch — the watermarks first, then `connect_enabled` saved
    alone, the service reloaded, the write told — then the first 20 of Current logged as entering the mine line, the
    user's and explicit, which Connect's inbox makes jobs of. Nothing moves, nothing else is saved."""
    before = _first_scan()
    in_line = _mine_line()
    assert len(in_line) == 20
    from app import settings_manager
    from app.connect import inbox, switch
    saved, backfilled = [], []
    monkeypatch.setattr(settings_manager, "save_keys", lambda changes, **kw: (saved.append(dict(changes)),
                                                                              dict(changes))[1])
    monkeypatch.setattr(switch, "refresh_tools_entry", lambda _saved: None)
    monkeypatch.setattr(switch, "backfill", lambda langs, s, log=print: backfilled.append(tuple(langs)))
    ny, win, settings, written = line(on=False)
    _answer(ny, "first_cards")
    assert wait_until(lambda: win.said, 30)
    assert win.said == [strings.NEEDS_FIRST_CARDS_MADE]
    assert saved == [{"connect_enabled": True}]                   # the one key, once (Settings' own save)
    assert [c for c in settings.calls if c != "fresh"] == ["reload"] and backfilled
    assert written == [("connect_enabled",)]
    logged = _log()
    assert [(i, k, b, e) for _n, i, k, b, e in logged] == [(i, "entered_mine_line", "user", 1) for i in in_line]
    assert _items() == before                                      # nothing moved
    assert service.read_answered("ja") == {service.FIRST_CARDS}   # the line leaves
    store = _store()
    try:
        got = inbox.consume(store, "ja")
    finally:
        store.close()
    assert sorted(got["queued"]) == sorted(in_line)               # Connect's inbox: 20 jobs, the user's


def test_make_cards_with_connect_already_on_only_logs_them(line, empty_library, monkeypatch):
    _first_scan(n_shows=1, episodes=6)
    from app.connect import switch
    turned = []
    monkeypatch.setattr(switch, "turn_on", lambda *a, **kw: turned.append(a))
    ny, win, settings, written = line(on=True)
    _answer(ny, "first_cards")
    assert wait_until(lambda: win.said, 30)
    assert turned == [] and settings.calls == [] and written == []          # Connect left as it was: no write
    assert [(k, b, e) for _n, _i, k, b, e in _log()] == [("entered_mine_line", "user", 1)] * 6


def test_not_now_writes_nothing_but_its_answer(line, empty_library, monkeypatch):
    before = _first_scan(n_shows=1, episodes=4)
    calls = []
    ny, win, settings, written = line(on=False)
    ny.switch_on = lambda *a: calls.append("switch_on")
    ny.first_cards = lambda *a: calls.append("first_cards")
    _answer(ny, "not_now")
    assert wait_until(lambda: win.said, 30)
    assert win.said == [strings.NEEDS_FIRST_CARDS_LATER]
    assert calls == [] and settings.calls == [] and written == []
    assert _log() == [] and _items() == before
    assert service.read_answered("ja") == {service.FIRST_CARDS}


def test_automatic_actions_off_make_no_cards_and_write_nothing(line, empty_library):
    """D29's switch off: Connect would never read the 20 (and turning it on later moves its watermark past them), so
    *Make cards* writes nothing and says why; the line stays."""
    _first_scan(n_shows=1, episodes=3)
    ny, win, settings, written = line(on=False)
    settings.data["logic"] = {"automation": False}
    calls = []
    ny.switch_on = lambda *a: calls.append("switch_on")
    ny.first_cards = lambda *a: calls.append("first_cards")
    _answer(ny, "first_cards")
    assert win.said == [strings.NEEDS_FIRST_CARDS_NOT_ON.format(why=strings.NEEDS_FIRST_CARDS_AUTOMATION_OFF)]
    wait_until(lambda: False, 0.3)
    assert calls == [] and settings.calls == [] and written == [] and _log() == []
    assert service.read_answered("ja") == frozenset()


def test_a_failure_after_connect_was_switched_on_still_tells_the_window(line, empty_library):
    """Connect saved on, then the log can't be written: the shell's Connect line and Settings' switch still hear that
    Connect is on (it is), and the failure is said; the line stays."""
    _first_scan(n_shows=1, episodes=3)
    ny, win, settings, written = line(on=False)
    ny.switch_on = lambda _s, _log: (True, None)

    def broken(*a):
        raise OSError("the library is held by another program")
    ny.first_cards = broken
    _answer(ny, "first_cards")
    assert wait_until(lambda: win.said, 30)
    assert written == [("connect_enabled",)] and "held by another program" in win.said[-1]
    from app.qt import press as qpress
    assert service.read_answered("ja") == frozenset() and not qpress.presses_of(win).any_live()   # its press ended


def test_connect_not_turned_on_makes_no_cards_and_the_line_stays(line, empty_library):
    _first_scan(n_shows=1, episodes=3)
    ny, win, settings, _written = line(on=False)
    logged = []
    ny.switch_on = lambda _s, _log: (False, "the library is busy; try again in a moment")
    ny.first_cards = lambda *a: logged.append(a)
    _answer(ny, "first_cards")
    assert wait_until(lambda: win.said, 30)
    assert win.said == [strings.NEEDS_FIRST_CARDS_NOT_ON.format(why="the library is busy; try again in a moment")]
    assert logged == [] and _log() == [] and service.read_answered("ja") == frozenset()


# --- SRC W1 fix: setup asks about cards once (Decision 1) --------------------------------------------------------- #
def _tips(entry):
    return [strings.NEEDS_ACTIONS[name][1] for name in entry.actions]


def test_with_cards_already_on_the_line_asks_only_about_these_episodes_and_never_offers_the_switch():
    """Page 5's *Make cards for me as I watch* said yes (Connect's switch on): the line is the same question, *Make
    cards for your first 20 episodes? · Not now*, but neither button's words offer to turn cards on — they are on.
    Page 5 said no (or was skipped): the line offers both, as built."""
    on = service.entries(_view(25), offers={service.FIRST_CARDS}, cards_on=True)[0]
    off = service.entries(_view(25), offers={service.FIRST_CARDS})[0]
    assert on.title == off.title == "Make cards for your first 20 episodes?" and on.key == off.key
    assert [strings.NEEDS_ACTIONS[a][0] for a in on.actions] == ["Make cards", "Not now"]
    assert [strings.NEEDS_ACTIONS[a][0] for a in off.actions] == ["Make cards", "Not now"]
    assert off.actions == ("first_cards", "not_now")
    assert on.actions != off.actions
    for tip in _tips(on):
        assert "from now on" not in tip and "Turn it on" not in tip, tip       # the switch is on: no offer of it
    assert "from now on" in _tips(off)[0] and "Turn it on" in _tips(off)[1]  # off: the 20 and the switch
    assert service.entries(_view(25), offers={service.FIRST_CARDS}, answered={service.FIRST_CARDS},
                           cards_on=True) == []


def test_make_cards_with_cards_already_on_logs_the_twenty_and_says_nothing_about_turning_on(line, empty_library,
                                                                                              monkeypatch):
    _first_scan(n_shows=1, episodes=6)
    from app.connect import switch
    turned = []
    monkeypatch.setattr(switch, "turn_on", lambda *a, **kw: turned.append(a))
    ny, win, settings, written = line(on=True, cards_on=True)
    _answer(ny, "first_cards_on")
    assert wait_until(lambda: win.said, 30)
    assert win.said == [strings.NEEDS_FIRST_CARDS_MADE_ON]
    assert turned == [] and settings.calls == [] and written == []          # Connect left as it was: no write
    assert [(k, b, e) for _n, _i, k, b, e in _log()] == [("entered_mine_line", "user", 1)] * 6
    assert service.read_answered("ja") == {service.FIRST_CARDS}


def test_not_now_with_cards_already_on_writes_only_its_answer_and_never_says_turn_it_on(line, empty_library):
    before = _first_scan(n_shows=1, episodes=4)
    ny, win, settings, written = line(on=True, cards_on=True)
    calls = []
    ny.switch_on = lambda *a: calls.append("switch_on")
    ny.first_cards = lambda *a: calls.append("first_cards")
    _answer(ny, "not_now_on")
    assert wait_until(lambda: win.said, 30)
    assert win.said == [strings.NEEDS_FIRST_CARDS_LATER_ON] and "Turn it on" not in win.said[0]
    assert calls == [] and settings.calls == [] and written == []
    assert _log() == [] and _items() == before
    assert service.read_answered("ja") == {service.FIRST_CARDS}


def test_the_line_follows_connects_switch_as_page_five_writes_it(line, empty_library):
    """The line is offered by page 3's read, before page 5 is answered: once page 5's yes (or Settings › Anki) writes
    `connect_enabled`, Needs you works the line out again in the switch's words — and back when it goes off."""
    service.offer("ja")
    ny, win, settings, _written = line(on=False)
    ny.read_connect = lambda _lang: None
    ny.find_offline = lambda *a: []
    ny.read_asks = lambda: ()

    def actions():
        return next((e.actions for e in ny.entries if e.kind == service.FIRST_CARDS), None)
    ny.view_in(_view(25))
    assert wait_until(lambda: actions() == ("first_cards", "not_now"), 10)
    settings.data["connect_enabled"] = True                     # page 5's yes, landed
    win.bridge.settings_written.emit(("connect_enabled",))
    assert wait_until(lambda: actions() == ("first_cards_on", "not_now_on"), 10)
    b = next(b for b in ny.cards.buttons(service.FIRST_CARDS) if b.property("action") == "first_cards_on")
    assert b.toolTip() == strings.NEEDS_ACTIONS["first_cards_on"][1] and not b.isHidden()
    gathers = ny.gathers
    win.bridge.settings_written.emit(("words_per_day",))        # another key: nothing worked out again
    wait_until(lambda: False, 0.3)
    assert ny.gathers == gathers
    settings.data["connect_enabled"] = False
    win.bridge.settings_written.emit(("connect_enabled",))
    assert wait_until(lambda: actions() == ("first_cards", "not_now"), 10)


# --- SRC W1 fix: page 3's two folder buttons land alike (Decision 2) -------------------------------------------- #
def test_page_threes_add_row_folder_is_setups_own_and_waits_for_the_sort_screen_on_set_up_again(make, monkeypatch):
    """*Set up again* over a library already in use (New arrivals on): page 3's add row *A folder…* is setup's own
    picker, as *Choose a folder…* — listed, then read on *Next* by setup's first look — so its shows land in New
    arrivals, grouped by show, quietly (no placing rule takes them: the sort screen comes up for them), and Current is
    untouched (+ Add's later look outside setup, D6, is never asked)."""
    data_dir, user_files_dir, doc = library("ja", shows=2, episodes=3, loose=0, tiers=("now",))
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    store = _store()
    try:
        store.set_library_options(arrivals_on=True)
        assert store.meta().get("arrivals_on")
        had = [rel for _i, _t, _o, rel in store.conn.execute("SELECT id, tier, ord, rel_path FROM items")]
    finally:
        store.close()
    folder = _folder("anime", SHOWS)
    looks = []
    real_scan = sources.scan

    def scan(store, language, root, **kw):
        looks.append(kw.get("first"))
        return real_scan(store, language, root, **kw)
    monkeypatch.setattr(sources, "scan", scan)
    wiz, shell, *_ = make(api=SourcesApi())
    adder = shell.adder = FakeAdder()
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    button = page.btn_pick                                          # alpha 8: page 3's one folder button
    assert not button.isHidden() and button.toolTip()
    wiz.pick_dialog = lambda _title, _start: folder
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: page.folders == [os.path.normpath(folder)], 10)
    assert adder.ran == [], "setup's own picker, never + Add's later look"
    wiz.next()
    assert wait_until(lambda: wiz.reading is None, 30)
    assert looks == [ls.SORT]                                       # setup's first look, for the sort screen
    items = _items()
    new = [(tier, ord_, rel) for _i, tier, ord_, rel in items if rel not in had]
    assert len(new) == sum(SHOWS.values())
    assert {tier for tier, _o, _r in new} == {"arrivals"}, "New arrivals, waiting to be sorted"
    assert sorted(rel for _i, t, _o, rel in items if t in ("now", "soon")) == sorted(had), "Current untouched"
    shows = [rel.split("/")[1] for _t, _o, rel in sorted(new, key=lambda n: n[1])]
    runs = [s for i, s in enumerate(shows) if i == 0 or shows[i - 1] != s]
    assert sorted(runs) == sorted(SHOWS), "grouped by show: one run each"
    assert _log() == []                                             # quiet: no placing rule took them on (S1)
    _sorted(wiz)


def test_the_folders_and_the_cards_line_never_touch_the_network(empty_library, monkeypatch):
    """The look and *Make cards* stay on this computer: no socket is ever opened (Connect's start is a process of its
    own, and none is started under a test root)."""
    opened = []

    def refuse(*a, **kw):
        opened.append(a)
        raise OSError("no network in this test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    first = _folder("anime", SHOWS)
    assert setup_wizard.folder_refused("ja", first) is None
    got = setup_wizard.read_folders("ja", [first])
    assert got["added"] == 5
    store = _store()
    try:
        store.place(got["ids"], "top")                              # the sort screen's *Current*
    finally:
        store.close()
    assert setup_wizard.sorted_offer("ja", got["ids"]) is True
    assert len(setup_wizard.first_cards("ja", {"connect_enabled": True})) == 5     # its own watermark, then the 5
    assert opened == []


# --- row 13 (laptop fixes): setup's *Make cards* waits for Anki Miner ------------------------------------------- #
def test_the_make_cards_line_waits_while_anki_miner_isnt_found_and_stays_offered():
    """Row 13: setup offered D1's line (its shows came into the top 20), but no Anki Miner here — *Make cards* would
    turn Connect on for cards it can never make, so the line waits; the offer is kept, and it shows once Anki Miner is
    found. Found, it is the line as before."""
    service.offer("ja")
    assert service.entries(_view(25), offers=service.read_offers("ja"), miner_found=False) == []
    assert service.read_offers("ja") == {service.FIRST_CARDS}                 # still offered, nothing answered
    assert service.read_answered("ja") == frozenset()
    entry = service.entries(_view(25), offers=service.read_offers("ja"), miner_found=True)[0]
    assert entry.kind == service.FIRST_CARDS and entry.actions == ("first_cards", "not_now")


@pytest.mark.parametrize("here", [False, True], ids=["miner-absent", "miner-found"])
def test_needs_you_asks_for_anki_miner_on_its_worker_and_shows_the_line_by_it(line, empty_library, here):
    """Row 13, the window: Needs you's gather (a worker) asks for Anki Miner — a stand-in, never the real one — and the
    line shows only when it is found. Never asked on the window's thread."""
    service.offer("ja")
    ny, win, settings, _written = line(on=False)
    asked = []

    def find(_settings):
        asked.append(threading.current_thread() is threading.main_thread())
        return MINER if here else None
    ny.find_miner = find
    ny.read_connect = lambda _lang: None
    ny.find_offline = lambda *a: []
    ny.read_asks = lambda: ()
    ny.entries = ()
    ny.view_in(_view(25))
    assert wait_until(lambda: asked and not ny._running, 10)
    QApplication.processEvents()
    assert asked == [False] * len(asked), "Anki Miner was looked for on the window's thread"
    kinds = [e.kind for e in ny.entries]
    assert (service.FIRST_CARDS in kinds) is here


@pytest.mark.parametrize("automation", [False, True], ids=["automation-off", "automation-on"])
def test_needs_you_reads_connect_on_as_the_rows_do_the_switch_and_automation(line, empty_library, automation):
    """B2-8 (Michi's call): "is Connect on" is one rule — `settings_manager.connect_on`, the switch and D29's
    automation, as the rows' `Feed.on` and Connect's own gates read it. With the switch on but the automation off,
    D1's line no longer says later episodes "get their cards already": its actions are the off ones."""
    service.offer("ja")
    ny, win, settings, _written = line(on=True)
    settings.data["logic"] = {"automation": automation}
    ny.read_connect = lambda _lang: None
    ny.find_offline = lambda *a: []
    ny.read_asks = lambda: ()
    ny.entries = ()
    ny.view_in(_view(25))
    assert wait_until(lambda: ny.entries and not ny._running, 10)
    entry = next(e for e in ny.entries if e.kind == service.FIRST_CARDS)
    assert entry.actions == (("first_cards_on", "not_now_on") if automation else ("first_cards", "not_now"))
