"""The library the real window opens (W3.2 P0; W3.1a's *As built* R3-L7: `main()` opened none, so the window Sonic runs
showed no library and its drag reached only tests).

What a wrong answer would cost:
  * the window Sonic starts showing no library at all — the G3.2 test build would have nothing to test;
  * a window that builds, migrates or repairs a store as it opens (a fresh install, a 2.x library not migrated yet, a
    store mid-migration, a damaged one): user data written by a look, never by the user or the store's own helper;
  * a crash on any of those, instead of the page's own *Getting ready* / read-only bar;
  * a language switch that keeps showing the old language's rows, or — worse — writes the user's next move, or an
    Undo of the old language's move, into the other language's library;
  * a move given just before a switch or a quit, lost (the store busy: it must land, or wait in the journal for the
    next start);
  * the plan's numbers read inside the first frame (≤ 1 s): main loads them after it.

Every library here is the store tests' synthetic one (real Japanese and Chinese names from tests/Test Resources/),
under the per-test SURASURA_TEST_ROOT.
"""
import json
import os
import sqlite3
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import path_utils
from app.qt import shell
from app.services import library_reader
from app.services import moves as moves_module
from tests.qt.conftest import wait_until
from tests.test_library_store_support import library, migrated, write_manifest
from tests.test_services_moves import LockHolder, short_lock_wait  # noqa: F401  (a fixture)


def _settings(**values):
    with open(path_utils.get_user_file("settings.json"), "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)


def _page(win):
    return win.page_widgets["current"]


def _state(win):
    view = _page(win).view_model
    return None if view is None else view.state


def _db(language):
    return ls.library_db_path(language, path_utils.get_data_path(language))


def _stamp(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


@pytest.fixture
def opened(qapp):
    """`open_services` and the window on it, as main makes them (the reader's collector freeze left off: a test's own
    cycles are still collected). -> make(); everything closed and shut down after."""
    made = []

    def make(**kw):
        services = shell.open_services(**kw)
        win = shell.open_window(qapp, services)
        win.resize(1280, 900)
        win.show()
        made.append((win, services))
        return services, win
    yield make
    for win, services in made:
        win.close()
        services.shutdown(2.0)


# --- main()'s wiring ------------------------------------------------------------------------------------------------ #
def test_main_opens_settings_language_library_and_loads_the_numbers_only_after_the_first_frame(qapp, monkeypatch):
    # R3-L7: the real main() built Services() with no library. Now it calls open_services (the window process's
    # collector freeze on), and the numbers' plan is read once the first frame is out (never inside it: ≤ 1 s).
    store = migrated("zh")
    _settings(target_language="zh")
    from app.qt import single as single_module

    class OneInstance:
        def __init__(self):
            self.released = 0

        def claim(self, _argv):
            return True

        def release(self):
            self.released += 1

        def stop_listening(self):
            pass

        class _Signal:
            def connect(self, _slot):
                pass
        activated = _Signal()

    asked, windows, inside = [], [], {}
    real_open, real_window = shell.open_services, shell.open_window

    def spy_open(**kw):
        asked.append(kw)
        return real_open(**dict(kw, freeze_gc=False))       # (the test process's collector stays as it is)

    def spy_window(app, services, state_file=None):
        win = real_window(app, services, state_file)
        windows.append(win)
        return win

    def fake_exec(*_a):
        win = windows[0]
        win.first_frame.disconnect(win.start_duties)        # (the real duties stay unmade: only main's own hooks)
        services = win.services
        numbers = services.writer.numbers
        opener = services.library.opener
        # IK0-4 / AD0-3: the window built, and at its first frame, the store not even probed on this thread
        inside["probed"] = [opener.reason]
        win.first_frame.connect(lambda: inside["probed"].append(opener.reason))
        inside["before"] = (numbers.why(), services.library._thread)   # nothing read, no reader before the frame
        inside["language"] = (services.library.language, services.writer.language, win.language)
        inside["one_opener"] = services.writer.opener is services.library.opener is numbers.opener
        inside["journal"] = services.writer.journal_file
        inside["cache"] = services.library.cache_file
        inside["rows"] = wait_until(lambda: _state(win) == "full", 15)   # (offscreen: the first frame comes here)
        inside["after"] = numbers.idle(30) and numbers.why()
        inside["writer"] = wait_until(lambda: services.writer._thread is not None, 10)   # started after it, on a worker
        win.close()
        return 0

    monkeypatch.setattr(single_module, "SingleInstance", OneInstance)
    monkeypatch.setattr(shell, "open_services", spy_open)
    monkeypatch.setattr(shell, "open_window", spy_window)
    monkeypatch.setattr(QApplication, "exec", fake_exec)
    monkeypatch.setattr(shell, "prepare_process", lambda: None)
    assert shell.main(["surasura"]) == 0
    assert asked == [{}]                                    # IK0-3: the collector freeze stays off
    assert inside["before"] == ("not read yet", None)
    assert inside["after"] == "no plan: Generate first"     # loaded once the frame was out
    assert inside["language"] == ("zh", "zh", "zh")
    assert inside["one_opener"]
    assert inside["journal"] == moves_module.journal_path("zh")
    assert inside["cache"] == library_reader.cache_path("zh")
    assert inside["rows"]
    assert inside["probed"] == ["not checked", "not checked"]
    assert inside["writer"]
    services = windows[0].services
    assert services.library._thread is not None and not services.library._thread.is_alive()   # stopped at quit
    store.close()


def test_open_services_builds_nothing_and_reads_nothing_before_the_window_starts_it(qapp):
    # The first frame's budget: open_services makes objects only — no reader thread, no writer thread, no store
    # handle, no plan read (the window starts the reader, its drag the writer, main the numbers after the frame).
    store = migrated("ja")
    services = shell.open_services()
    try:
        reader, writer = services.library, services.writer
        assert reader._thread is None and writer._thread is None
        assert writer.numbers.why() == "not read yet" and writer.numbers.worker._thread is None
        assert reader.opener.mode == "json" and reader.opener.reason == "not checked"   # never even probed
        assert reader.freeze_gc is False
        assert callable(services.library_for)
    finally:
        services.shutdown(1.0)
        store.close()


# --- every store mode opens --------------------------------------------------------------------------------------- #
def test_a_migrated_store_shows_its_rows_and_a_move_lands_in_it(opened):
    store = migrated("ja")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    assert win.moves is not None and win.moves.writer is services.writer
    assert services.writer.can_write()
    shown = {e.id for r in _page(win).view_model.rows for e in r.episodes}
    assert shown and shown <= set(store.ids("now") + store.ids("soon") + store.ids("goal"))
    now = store.ids("now")
    assert services.writer.move([now[-1]], "now", before_id=now[0]) is not None
    assert wait_until(lambda: services.writer.pending() == 0 and store.ids("now")[0] == now[-1], 10)
    store.close()


@pytest.mark.parametrize("kind", ["fresh install", "2.x library not migrated"])
def test_no_store_yet_opens_getting_ready_and_never_makes_or_migrates_one(opened, kind):
    # A fresh install, and a 2.x JSON library: the window says *Getting ready*; the chores' helper (W3.5) builds or
    # migrates it, never the window's open. The manifest is left byte for byte.
    manifest = None
    if kind != "fresh install":
        data_dir, user_files_dir, doc = library("ja")
        manifest = write_manifest(user_files_dir, doc)
        with open(manifest, "rb") as f:
            before = f.read()
    services, win = opened()
    assert wait_until(lambda: _state(win) == "getting-ready", 10)
    time.sleep(0.3)
    QApplication.processEvents()
    assert not os.path.exists(_db("ja"))
    assert not services.writer.can_write()
    assert services.writer.move([1], "now") is None              # E4: refused before anything is painted
    if manifest is not None:
        with open(manifest, "rb") as f:
            assert f.read() == before


def test_a_store_being_migrated_says_getting_ready_then_shows_its_rows_once_it_is_done(opened):
    store = migrated("ja")
    with sqlite3.connect(store.db_path) as conn:                 # mid-migration: the build hasn't finished
        stamp = conn.execute("SELECT value FROM meta WHERE key = 'migrated_at'").fetchone()[0]
        conn.execute("DELETE FROM meta WHERE key = 'migrated_at'")
    store.close()
    services, win = opened()
    assert wait_until(lambda: _state(win) == "getting-ready", 10)
    assert _page(win).view_model.reason == "not ready"
    with sqlite3.connect(_db("ja")) as conn:                     # the helper finishes (never the window)
        conn.execute("INSERT INTO meta (key, value) VALUES ('migrated_at', ?)", (stamp,))
    assert wait_until(lambda: _state(win) == "full", 15)         # the reader's mode recheck: no restart needed
    assert wait_until(services.writer.can_write, 5)               # the writer's thread asks again (R3-L4)


@pytest.mark.parametrize("why", ["damaged", "made by a newer Surasura"])
def test_a_damaged_or_newer_store_opens_read_only_and_refuses_moves_without_writing_it(opened, why):
    store = migrated("ja")
    db = store.db_path
    store.close()
    if why == "damaged":
        ls.mark_damaged(db, "test: a torn page")
    else:
        with sqlite3.connect(db) as conn:
            conn.execute(f"PRAGMA user_version = {ls.STORE_SCHEMA + 1}")
        conn.close()
    before = _stamp(db)
    services, win = opened()
    assert wait_until(lambda: _state(win) == "read-only", 10)
    assert _page(win).view_model.reason == why
    assert not services.writer.can_write()
    assert services.writer.move([1], "now") is None
    time.sleep(0.3)
    assert _stamp(db) == before                                   # the open wrote nothing


# --- a language switch ---------------------------------------------------------------------------------------------- #
def _switch(services, language):
    services.settings.set({"target_language": language})


def test_a_language_switch_shows_the_new_library_and_writes_only_into_it(opened):
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    old_reader, old_writer, old_moves = services.library, services.writer, win.moves
    ja_order = {t: ja.ids(t) for t in ("now", "soon", "goal")}
    undone = []
    win.toasts.show("Moved 1 file to the top of Current", undo=lambda: undone.append(1))   # a ja move's Undo
    assert win.toasts.shown
    _switch(services, "zh")
    assert wait_until(lambda: win.language == "zh" and _page(win).view_model is not None
                      and _page(win).view_model.language == "zh" and _state(win) == "full", 15)
    assert services.library is not old_reader and services.library.language == "zh"
    assert services.writer.language == "zh" and services.writer.opener is services.library.opener
    assert win.moves is not old_moves and win.moves.writer is services.writer and win.moves.reader is services.library
    assert not old_reader._thread.is_alive()                     # the old reader stopped
    assert old_writer._stop                                      # ... and its writer finished
    assert all(p.language == "zh" for p in win.page_widgets.values() if hasattr(p, "language"))
    assert not win.toasts.shown and undone == []               # the ja Undo went with its toast
    undo = QKeySequence(QKeySequence.StandardKey.Undo)
    keys = [k for k in win.findChildren(QShortcut) if k.isEnabled() and k.key() == undo]
    assert keys == [win.moves.undo_key]                          # one Ctrl+Z: the new language's
    shown = [e.id for r in _page(win).view_model.rows for e in r.episodes]
    assert set(shown) <= set(zh.ids("now") + zh.ids("soon") + zh.ids("goal"))
    now = zh.ids("now")
    assert win.moves.writer.move([now[-1]], "now", before_id=now[0]) is not None
    assert wait_until(lambda: zh.ids("now")[0] == now[-1], 10)
    assert {t: ja.ids(t) for t in ("now", "soon", "goal")} == ja_order   # the language left: untouched
    assert old_writer.move([ja_order["now"][-1]], "now", before_id=ja_order["now"][0]) is None   # refused
    ja.close()
    zh.close()


def test_a_move_queued_on_a_busy_store_lands_in_its_own_language_before_the_switch(opened, short_lock_wait):
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    old_writer = services.writer
    now, zh_now = ja.ids("now"), zh.ids("now")
    holder = LockHolder(ja.db_path)
    try:
        assert old_writer.move([now[-1]], "now", before_id=now[0]) is not None
        assert wait_until(lambda: os.path.exists(moves_module.journal_path("ja")), 5)
        _switch(services, "zh")
        time.sleep(0.5)
        QApplication.processEvents()
        assert services.library is None or services.library.language == "ja"   # the switch waits for the ja move
    finally:
        holder.release()
    assert wait_until(lambda: win.language == "zh" and _state(win) == "full"
                      and _page(win).view_model.language == "zh", 15)
    assert ja.ids("now")[0] == now[-1]                           # written into ja, as given
    assert zh.ids("now") == zh_now                               # ... never into zh
    ja.close()
    zh.close()


def test_a_second_switch_overtaking_the_first_leaves_one_library_the_last_language(opened):
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    readers = [services.library]
    _switch(services, "zh")
    assert wait_until(lambda: services.library is not None and services.library.language == "zh", 15)
    readers.append(services.library)
    _switch(services, "ja")
    assert wait_until(lambda: win.language == "ja" and services.library.language == "ja"
                      and _page(win).view_model.language == "ja" and _state(win) == "full", 15)
    readers.append(services.library)
    assert wait_until(lambda: win._reader_shown is services.library, 5)
    alive = [r for r in readers if r._thread is not None and r._thread.is_alive()]
    assert alive == [services.library]
    ja.close()
    zh.close()


def test_a_view_of_the_language_left_is_dropped_never_shown(opened):
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    shown = _page(win).view_model
    stale = shown._replace(language="zh", rows=())
    win.show_library(stale)
    assert _page(win).view_model is shown
    ja.close()
    zh.close()


def test_a_test_library_given_by_hand_never_switches(qapp):
    # Services(library=…) without `library_for` (W2.2 / W3.1a's tests, the capture): a switch keeps it.
    services = shell.Services()
    assert services._switch_library("zh") is None and services.library is None


# --- quit ------------------------------------------------------------------------------------------------------------ #
def test_quit_writes_a_waiting_move_when_the_store_frees_in_time(opened, short_lock_wait):
    store = migrated("ja")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    now = store.ids("now")
    holder = LockHolder(store.db_path)
    assert services.writer.move([now[-1]], "now", before_id=now[0]) is not None
    assert wait_until(lambda: os.path.exists(moves_module.journal_path("ja")), 5)
    import threading
    threading.Timer(0.6, holder.release).start()
    win.close()                                                  # (E20: the window waits for its moves first)
    assert wait_until(lambda: not win.isVisible(), 10)
    services.shutdown(2.0)
    assert store.ids("now")[0] == now[-1]
    journal = moves_module.journal_path("ja")
    if os.path.exists(journal):                                  # (an empty journal may be removed)
        with open(journal, encoding="utf-8") as f:
            assert json.load(f)["pending"] == []
    assert not services.library._thread.is_alive()
    store.close()


def test_quit_out_of_time_keeps_the_move_in_the_journal_and_the_next_start_applies_it(opened, short_lock_wait,
                                                                                    monkeypatch):
    store = migrated("ja")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    now = store.ids("now")
    holder = LockHolder(store.db_path)
    try:
        assert services.writer.move([now[-1]], "now", before_id=now[0]) is not None
        assert wait_until(lambda: os.path.exists(moves_module.journal_path("ja")), 5)
        monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 0.3)
        win._quit = "ready"                                      # (the close's wait skipped: the quit runs out of time)
        win.close()
        services.shutdown(1.0)
    finally:
        holder.release()
    with open(moves_module.journal_path("ja"), encoding="utf-8") as f:
        assert len(json.load(f)["pending"]) == 1                 # kept for the next start
    assert store.ids("now")[0] == now[0]
    services2, win2 = opened()                                   # the next start: the journal replayed by id
    assert wait_until(lambda: store.ids("now")[0] == now[-1], 15)
    assert wait_until(lambda: services2.writer.pending() == 0, 10)
    store.close()


# --- the fix round (W3.2 P0 reviews: AD0-1…12, IK0-1…11) -------------------------------------------------------- #
@pytest.fixture
def gui_probes(monkeypatch):
    """Every store probe (`library_store._probe`: a SQLite open, reads, a close) made on the window's thread."""
    import threading
    made = []
    real = ls._probe

    def probe(*a, **k):
        if threading.current_thread() is threading.main_thread():
            made.append(a[0] if a else None)
        return real(*a, **k)
    monkeypatch.setattr(ls, "_probe", probe)
    return made


def _ask(services, win, language):
    """Settings › Language as the user moves it: the write lands, the window asks (no wait for the switch itself)."""
    _switch(services, language)
    assert wait_until(lambda: win._language_asked == language, 10)


def _switched_to(win, services, language, timeout=20):
    return wait_until(lambda: win.language == language and services.library is not None
                      and services.library.language == language and win._reader_shown is services.library
                      and _page(win).view_model is not None and _page(win).view_model.language == language
                      and _state(win) in ("full", "empty") and win.moves is not None and win.moves.blocked is None,
                      timeout)


def _ticket(text):
    from app.qt import drag
    return drag.Ticket(text)


def test_a_switch_never_probes_the_store_on_the_window_thread_and_clears_the_rows_marks(opened, gui_probes):
    # IK0-4 / AD0-3: the writer's first look and its replay ran on the window's thread, at the open and at every
    # switch (a SQLite open there, up to 50 ms waiting for the write lock). AD0-6: a ja row's *saving…* / landing mark
    # stayed on the zh row with the same key. AD0-11: zh rows drew in the ja font.
    from app.qt import style
    ja, zh = migrated("ja"), migrated("zh")
    gui_probes.clear()                                           # (the test's own store set-up probed here)
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    assert gui_probes == []                                      # the open: none
    lst = _page(win).list
    key = _page(win).view_model.rows[0].key
    lst.saving, lst.landing = frozenset({key}), key              # a ja move waiting on a busy store as the switch came
    win.moves_saving(True)                                       # (PS-A4: and 届's wait for it, on the phase strip)
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    assert wait_until(lambda: services.writer._thread is not None, 10)
    assert gui_probes == []                                      # the switch: none either
    assert lst.saving == frozenset() and lst.landing is None
    assert not win.phase.states["arrivals"].waiting              # the writer let go never says False: no wait kept
    assert style.current()[2] == "zh"
    ja.close()
    zh.close()


def test_a_reader_a_switch_let_go_is_freed(opened):
    # IK0-3 / AD0-2: the reader <-> numbers cycle, and main's collector freeze, kept every library a switch let go.
    import gc
    import weakref
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    gone = weakref.ref(services.library)
    numbers_gone = weakref.ref(services.writer.numbers)
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    assert gone() is None or (gone()._items == {} and gone()._works == {})    # its copy let go at its stop
    assert wait_until(lambda: (gc.collect(), gone() is None and numbers_gone() is None)[1], 10)
    ja.close()
    zh.close()


def test_L3_the_covers_follow_the_library_a_switch_opens_and_hold_nothing_of_the_one_it_left(opened, monkeypatch):
    # W3.2 L3: the covers kept the first library's writer, drag controller and fetcher past a switch — the ja reader
    # was never freed, a Change cover… on a zh row went to the ja writer, and zh's posters were never scanned for.
    from app.qt import covers as qcovers
    scans = []
    real_scan = qcovers.start_scan
    monkeypatch.setattr(qcovers, "start_scan", lambda opener, language, writer: (
        scans.append((language, writer)), real_scan(opener, language, writer))[1])
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and scans, 15)            # the first frame's scan, of ja
    old_writer, old_fetcher = services.writer, win.cover_fetcher()
    assert scans == [("ja", old_writer)] and old_fetcher.language == "ja"
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    assert qcovers._where["language"] == "zh"
    assert qcovers._where["data_dir"] == services.library.opener.data_dir != old_writer.opener.data_dir
    assert qcovers._library["writer"] is services.writer is not old_writer
    assert qcovers._library["moves"] is win.moves and qcovers._library["window"] is win
    f = qcovers.fetcher()
    assert f is win._fetcher and f.language == "zh" and f.writer is services.writer
    assert f.data_dir == services.library.opener.data_dir, "its disk-first look reads zh's folder, not a default one"
    assert old_fetcher._stop                                                  # the ja fetcher stopped
    assert scans[-1] == ("zh", services.writer)                               # zh's posters scanned for
    ja.close()
    zh.close()


def test_a_switch_straight_back_never_puts_two_writers_on_one_journal(opened, monkeypatch):
    # AD0-1: the ja store busy past the switch's wait; the old writer's thread still inside its write. Back on ja at
    # once, a second ja writer replayed the journalled nudge while the first then landed it too: moved two places.
    import threading
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 0.3)
    old = services.writer
    gate = threading.Event()
    real_apply = old._apply

    def held_apply(store, cmd):                                  # the store's write lock, held by another program
        gate.wait(10)
        return real_apply(store, cmd)
    monkeypatch.setattr(old, "_apply", held_apply)
    now = ja.ids("now")
    before = ja.versions()["order_version"]
    assert old.nudge([now[0]], "down") is not None
    assert wait_until(lambda: os.path.exists(moves_module.journal_path("ja")), 5)
    threading.Timer(3.0, gate.set).start()                       # it frees past the switch's wait, inside the lock's
    _ask(services, win, "zh")
    _ask(services, win, "ja")                                    # straight back
    assert _switched_to(win, services, "ja", 30)
    assert wait_until(lambda: gate.is_set() and services.writer.pending() == 0 and not old._thread.is_alive(), 15)
    time.sleep(0.5)
    assert ja.versions()["order_version"] == before + 1          # the nudge landed once
    assert ja.ids("now").index(now[0]) > 0
    assert not os.path.exists(moves_module.journal_path("ja"))   # ... and left the journal
    ja.close()
    zh.close()


def test_three_switches_back_to_back_end_on_the_last_language_with_one_reader_and_a_working_drag(opened):
    # AD0-4 / IK0-7: ja → zh → ja → zh with no wait: an ask was compared against the services' language (set later
    # by the worker) and dropped, or the window read a library another switch was replacing — a stopped reader
    # started, no drag for the rest of the session.
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    readers = [services.library]
    real_for = services.library_for

    def library_for(language):
        made = real_for(language)
        readers.append(made[0])
        return made
    services.library_for = library_for
    _ask(services, win, "zh")
    _ask(services, win, "ja")
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh", 30)
    def alive():
        QApplication.processEvents()
        return [r for r in readers if r._thread is not None and r._thread.is_alive()]
    # the readers left stop on their own threads: on a loaded machine that can take longer than half a second
    assert wait_until(lambda: alive() == [services.library], 15), alive()
    assert services.library.language == "zh"
    assert win.moves.writer is services.writer and win.moves.reader is services.library
    now = zh.ids("now")
    assert win.moves.writer.move([now[-1]], "now", before_id=now[0]) is not None
    assert wait_until(lambda: zh.ids("now")[0] == now[-1], 10)
    ja.close()
    zh.close()


def test_from_the_switchs_start_a_drag_is_refused_with_a_line_and_a_refused_write_is_said(opened, short_lock_wait,
                                                                                          monkeypatch):
    # AD0-5 / IK0-6: a drop between the old writer stopping and the new library looked saved and sprang back later,
    # silently; a pending *Take its new cards out* that could no longer be written said nothing.
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 1.5)
    old_moves, old_writer = win.moves, services.writer
    now = ja.ids("now")
    holder = LockHolder(ja.db_path)
    try:
        assert old_writer.move([now[-1]], "now", before_id=now[0]) is not None      # the switch waits for it
        _ask(services, win, "zh")
        line = shell.strings.SWITCHING.format(name="中文")
        assert win.moves is old_moves and old_moves.blocked == line
        assert old_moves.begin_by_id([now[1]], "now", "ナルト", None) is False      # refused …
        assert win.bar_line.full() == line                                        # … and said
        assert wait_until(lambda: old_writer._stop, 10)
        old_moves.blocked = None                                 # (past the refusal: the writer let go itself)
        win.bar_line.set_full("")
        given = old_moves._give(_ticket("Moved"), lambda t: old_writer.set_finished([now[2]], keep_cards=False,
                                                                                   label=t))
        assert given is None and win.bar_line.full() == shell.strings.MOVE_NOT_SAVED
    finally:
        holder.release()
    assert _switched_to(win, services, "zh", 30)
    ja.close()
    zh.close()


def test_a_write_the_writer_refuses_puts_the_stores_order_back_and_says_so(opened):
    # AD0-5: `_give` with no command number repainted nothing — the drop's order stayed on screen, unsaved.
    from app.qt import drag
    store = migrated("ja")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    moves = win.moves
    shown = _page(win).view_model
    keys = [r.key for r in shown.rows]
    moves._ahead(drag.reordered(shown, keys[1:] + keys[:1]))     # the drop painted ahead of the store
    assert [r.key for r in _page(win).view_model.rows] != keys
    assert moves._give(drag.Ticket("Moved"), lambda _t: None) is None
    assert [r.key for r in _page(win).view_model.rows] == keys
    assert win.bar_line.full() == shell.strings.MOVE_NOT_SAVED
    store.close()


def test_a_switch_with_the_duties_attached_hears_the_new_readers_moves_and_reads_the_level_again(opened):
    # AD0-7: the path Sonic runs (the duties attach after the first frame) had no switch test. AD0-12: a step of the
    # language switch that fails (here the Generate failure's forget) is logged and the library still follows.
    from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates
    from tests.qt.test_shell_replan import _Replan
    ja, zh = migrated("ja"), migrated("zh")
    log, replan = [], _Replan()
    controller = FakeController(log)

    def boom():
        raise RuntimeError("the controller is gone")
    controller.forget_failure = boom
    services, win = opened(controller=controller, updates=FakeUpdates(log), automation=FakeAutomation(log),
                           chores=FakeChores(log), replan=replan)
    assert win.duties is not None
    assert wait_until(lambda: _state(win) == "full", 15)
    levels = []
    win._read_level = lambda: levels.append(win.language)
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    assert ("language_changed", "zh") in replan.calls and levels == ["zh"]
    with open(os.path.join(path_utils.get_local_data_path(), "logs", "app_debug_log.txt"), encoding="utf-8") as f:
        assert "the Generate failure at the language switch" in f.read()
    now = zh.ids("now")
    assert win.moves.writer.move([now[-1]], "now", before_id=now[0]) is not None
    assert wait_until(lambda: ("store_moved", "zh") in replan.calls, 10)   # the zh reader's moves reach the host
    zh.close()
    ja.close()


def test_a_journal_the_other_language_left_is_replayed_when_the_switch_reaches_it(opened, short_lock_wait,
                                                                                 monkeypatch):
    # AD0-8: zh quit out of time (its move in window_pending_zh.json); the next start opens ja; a switch to zh
    # replays it — the new writer's start (and replay) at the switch is what does it.
    ja, zh = migrated("ja"), migrated("zh")
    _settings(target_language="zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    now = zh.ids("now")
    holder = LockHolder(zh.db_path)
    try:
        assert services.writer.move([now[-1]], "now", before_id=now[0]) is not None
        assert wait_until(lambda: os.path.exists(moves_module.journal_path("zh")), 5)
        monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 0.3)
        win._quit = "ready"
        win.close()
        services.shutdown(1.0)
    finally:
        holder.release()
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 8.0)
    assert zh.ids("now")[0] == now[0]                            # not written: kept for the next open
    _settings(target_language="ja")
    services2, win2 = opened()
    assert wait_until(lambda: _state(win2) == "full", 15)
    _ask(services2, win2, "zh")
    assert _switched_to(win2, services2, "zh")
    assert wait_until(lambda: zh.ids("now")[0] == now[-1], 15)
    assert wait_until(lambda: not os.path.exists(moves_module.journal_path("zh")), 10)
    ja.close()
    zh.close()


def test_a_quit_during_a_switch_leaves_nothing_open_and_keeps_the_journal(opened, short_lock_wait, monkeypatch):
    # AD0-9: the quit waits for a switch under way and never opens a library behind it: one writer and reader at
    # most, the ja move kept in its journal, nothing alive after shutdown.
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 1.0)
    opened_for = []
    real_for = services.library_for
    services.library_for = lambda language: opened_for.append(language) or real_for(language)
    old_reader, old_writer = services.library, services.writer
    now, zh_now = ja.ids("now"), zh.ids("now")
    holder = LockHolder(ja.db_path)
    try:
        assert old_writer.move([now[-1]], "now", before_id=now[0]) is not None
        assert wait_until(lambda: os.path.exists(moves_module.journal_path("ja")), 5)
        _ask(services, win, "zh")
        time.sleep(0.2)                                          # the switch waits on the busy ja move
        win._quit = "ready"
        win.close()
        services.shutdown(1.0)
        assert opened_for == []                                  # no library opened behind the quit
        assert services.library is None and services.writer is None
        assert not old_reader._thread.is_alive() and not old_writer._thread.is_alive()
        with open(moves_module.journal_path("ja"), encoding="utf-8") as f:
            assert len(json.load(f)["pending"]) == 1             # kept for the next start
    finally:
        holder.release()
    assert zh.ids("now") == zh_now
    ja.close()
    zh.close()


def test_main_opens_the_window_without_a_library_when_open_services_fails(qapp, monkeypatch):
    # AD0-12: before P0 the window always opened; an open_services that raises must not take the window with it.
    from app.qt import single as single_module

    class OneInstance:
        def claim(self, _argv):
            return True

        def release(self):
            pass

        def stop_listening(self):
            pass

        class _Signal:
            def connect(self, _slot):
                pass
        activated = _Signal()

    seen = {}

    def broken(**_kw):
        raise sqlite3.OperationalError("disk I/O error")

    real_window = shell.open_window

    def spy_window(app, services, state_file=None):
        win = real_window(app, services, state_file)
        seen["win"] = win
        return win

    def fake_exec(*_a):
        win = seen["win"]
        win.first_frame.disconnect(win.start_duties)
        seen["library"] = win.services.library
        seen["bar"] = win.bar_line.full()
        seen["page"] = [label.text() for label in win.page_widgets["current"].findChildren(shell.QLabel)]
        win.close()
        return 0

    monkeypatch.setattr(single_module, "SingleInstance", OneInstance)
    monkeypatch.setattr(shell, "open_services", broken)
    monkeypatch.setattr(shell, "open_window", spy_window)
    monkeypatch.setattr(QApplication, "exec", fake_exec)
    monkeypatch.setattr(shell, "prepare_process", lambda: None)
    assert shell.main(["surasura"]) == 0
    assert seen["library"] is None
    assert seen["bar"] == shell.strings.LIBRARY_NOT_OPENED
    assert shell.strings.LIBRARY_NOT_OPENED in seen["page"]


def test_a_fresh_install_builds_its_store_from_the_folders_and_takes_a_drop(opened, tmp_path, real_store_helper):
    # IK0-2: no manifest and no store (a fresh install): the chores' helper built only from a manifest, so the window
    # said *Getting ready* forever and refused every drop. Now it builds from the tiers' folders: the empty state,
    # then an Explorer drop lands.
    import shutil
    from app.services import chores as chores_module
    from app.services.jobs import JobRegistry
    services, win = opened()
    assert wait_until(lambda: _state(win) == "getting-ready", 10)
    assert "as it was" not in _page(win).state_bar.text()        # IK0-1: no promise of rows it can't show
    chores = chores_module.Chores(JobRegistry(), services.settings, "ja", update_staged=lambda: False)
    try:
        chores.worker.put(chores._maintain)
        assert wait_until(lambda: _state(win) == "empty", 60)
        assert wait_until(lambda: not chores.registry.live("library-maintain"), 30)   # the helper ended
        assert wait_until(lambda: services.writer.can_write(), 10)
        episode = tmp_path / "ぼっち・ざ・ろっく！ - 01.srt"
        shutil.copy(os.path.join(os.path.dirname(__file__), "..", "Test Resources", "ja", "placed_episode.srt"),
                    episode)
        assert services.writer.insert_at([str(episode)], "now") is not None
        assert wait_until(lambda: _state(win) == "full", 20)
        store = ls.open_store("ja", path_utils.get_data_path("ja"), path_utils.get_user_files_path("ja"))
        try:
            assert len(store.ids("now")) == 1
        finally:
            store.close()
    finally:
        chores.close(store=False)


def test_a_stale_switch_running_last_follows_the_language_asked_last(opened):
    # AD0-4 / IK0-7, made certain: ja → zh → ja, the zh worker slow to start. The second ask was compared against the
    # services' language (still ja: dropped), and a switch ran its own language even when a newer ask had come (zh
    # last: the window on zh while settings say ja).
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    first = services.library
    real = services.language_changed
    delays = iter([0.8, 0.1])
    services.language_changed = lambda language: (time.sleep(next(delays, 0.0)), real(language))[1]
    win._ask_language("zh", win._library_switched)              # (the window's own entry, as a settings write calls it)
    win._ask_language("ja", win._library_switched)
    time.sleep(1.5)
    assert wait_until(lambda: win.moves is not None and win.moves.blocked is None, 10)
    assert services.library.language == "ja" and win.language == "ja" and win._reader_shown is services.library
    assert services.library is first and first._thread.is_alive()   # nothing to switch: the same library, still live
    ja.close()
    zh.close()


# --- P4.1 L2 (W1: rows 4.1.10, 4.1.13; W-A1, W-A2, W-A5): Connect hung on the window's library ------------------- #
def test_connect_is_hung_on_the_library_one_feed_a_language_for_the_line_and_the_stones_and_a_kick_after_writes(
        opened):
    """The window as main makes it, its duties attached (the status line's providers): one Connect feed per language,
    ticked by the status line and read by the reader's stones; the writer's after-commit hook kicks Connect once for a
    move into the top 20 (row 4.1.6's rule); Connect's look then queues it and the next tick shows it *Waiting* on
    its row. What a wrong answer would cost: a placed episode that never gets cards until the next start (no kick), a
    status line and stones that disagree, or the Japanese feed's stones on the Chinese rows after a switch."""
    from app.connect import feed as connect_feed_module
    from app.connect import inbox
    from app.connect.ledger import Ledger
    from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates
    from tests.qt.test_shell_replan import _Replan
    ja, zh = migrated("ja"), migrated("zh")
    _settings(target_language="ja", connect_enabled=True)
    ja.bookkeeping({"mine_line": 2}, copy_carries=True)     # a top 2: the last NOW file is below the line
    with Ledger() as ledger:
        inbox.consume(ja, "ja", ledger)                     # Connect's first look: its reader and watermark
    log = []
    services, win = opened(controller=FakeController(log), updates=FakeUpdates(log), automation=FakeAutomation(log),
                           chores=FakeChores(log), replan=_Replan())
    assert wait_until(lambda: _state(win) == "full", 15)
    feed = shell.connect_feed("ja", services.settings)
    assert shell.connect_feed("ja", services.settings) is feed and shell.connect_feed("zh", services.settings) is not feed
    assert services.library.connect == feed.latest, "the stones read the status line's feed"
    kicks = []
    link = services.writer.after_commit.link
    link._kick, link._running = (lambda settings: kicks.append(1) or object()), (lambda: False)
    now = ja.ids("now")
    assert services.writer.move([now[-1]], "now", before_id=now[0]) is not None
    assert wait_until(lambda: services.writer.pending() == 0 and kicks == [1], 10), "one kick after the move"
    with Ledger() as ledger:
        got = inbox.consume(ja, "ja", ledger)
        assert now[-1] in got["queued"]                 # what the kicked Connect does first
    line = services.status.providers["connect"]()                       # the status line's tick (a worker's call)
    got = feed.latest()
    assert line == got.line and got.items[now[-1]].kind == connect_feed_module.WAITING

    def tip():
        view = _page(win).view_model
        return next((e.status.tip for r in view.rows for e in r.episodes if e.id == now[-1]), None)
    assert wait_until(lambda: tip() == connect_feed_module.WORDS[connect_feed_module.WAITING], 10)
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    assert services.library.connect == shell.connect_feed("zh", services.settings).latest
    ja.close()
    zh.close()


# --- P4.1 WF (review B1): Connect's line and stones tick again once Connect may run again ------------------------- #
def _duties():
    from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates
    from tests.qt.test_shell_replan import _Replan
    log = []
    return dict(controller=FakeController(log), updates=FakeUpdates(log), automation=FakeAutomation(log),
                chores=FakeChores(log), replan=_Replan())


def test_automation_turned_back_on_brings_connects_line_and_feed_back_through_the_status_poll(opened, monkeypatch):
    """B1 (a): a look that found D29's automation off stops Connect's tick (`Provider.every` None); the window's own
    status poll asks nothing more of it. Automation turned back on in Settings asks the line by name, so the bar leaves
    *Automation is off…* and the stones' feed is an on Feed again, ticking. What a wrong answer would cost: Connect
    making cards while the bar says it makes none, and no row ever showing *Mining* / *Waiting*."""
    from app.connect import feed as connect_feed_module
    # Connect is never started by a test (a kick would run the CLI without the test root: harness_guards)
    from app.connect import kick as connect_kick
    monkeypatch.setattr(connect_kick, "kick", lambda settings: None)
    ja = migrated("ja")
    _settings(target_language="ja", connect_enabled=True, logic={"automation": False})
    services, win = opened(**_duties())
    feed = shell.connect_feed("ja", services.settings)
    assert wait_until(lambda: services.status.snapshot().connect == connect_feed_module.OFF_AUTOMATION, 15)
    assert feed.latest() is not None and not feed.latest().on and feed.every() is None
    services.settings.set({"logic.automation": True}, now=True)
    assert wait_until(lambda: services.status.snapshot().connect not in (None, connect_feed_module.OFF_AUTOMATION),
                      10), services.status.snapshot().connect
    assert feed.latest().on and services.status.providers["connect"].every() == 3.0   # the poll ticks it again
    ja.close()


def test_a_language_whose_feed_last_found_connect_off_looks_again_when_switched_back_to(opened, monkeypatch):
    """B1 (b), the adversary's case: Connect off in Japanese, switch to Chinese, turn *Make cards for me* on there,
    switch back. The Japanese feed (kept across switches) last found Connect off: the switch asks the line by name, so
    it looks again and is on. What a wrong answer would cost: the Japanese rows never showing Connect, the bar holding
    the Chinese library's last Connect line."""
    # Connect is never started by a test (a kick would run the CLI without the test root: harness_guards)
    from app.connect import kick as connect_kick
    monkeypatch.setattr(connect_kick, "kick", lambda settings: None)
    ja, zh = migrated("ja"), migrated("zh")
    _settings(target_language="ja", connect_enabled=False)
    services, win = opened(**_duties())
    assert wait_until(lambda: _state(win) == "full", 15)
    feed_ja = shell.connect_feed("ja", services.settings)
    assert wait_until(lambda: feed_ja.latest() is not None and not feed_ja.latest().on, 15)
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    feed_zh = shell.connect_feed("zh", services.settings)
    services.settings.set({"connect_enabled": True}, now=True)
    assert wait_until(lambda: feed_zh.latest() is not None and feed_zh.latest().on, 10)
    assert not feed_ja.latest().on                          # (not asked while Chinese is open)
    _ask(services, win, "ja")
    assert _switched_to(win, services, "ja")
    assert wait_until(lambda: feed_ja.latest().on and feed_ja.every() is not None, 10), feed_ja.latest()
    assert services.status.snapshot().connect == feed_ja.latest().line
    ja.close()
    zh.close()


def test_a_window_with_no_connect_actions_gets_them_with_a_switchs_writer(opened):
    """WF fix 9 (adversary N7): Connect's actions are made with a writer; a window that had none gets them at the
    switch that brings one (its buttons wired to someone), and one made already is kept (it follows `win.moves` and
    the language at each call: a second would ask twice)."""
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full", 15)
    first = win.mine
    assert first is not None
    win.mine = None                                         # as a window opened with no writer holds it
    _ask(services, win, "zh")
    assert _switched_to(win, services, "zh")
    made = win.mine
    assert made is not None and made is not first and made.win is win
    _ask(services, win, "ja")
    assert _switched_to(win, services, "ja")
    assert win.mine is made
    ja.close()
    zh.close()


def test_W1_a_mark_that_counts_asks_the_indexer_forced_from_the_first_writer_and_a_switchs(tmp_path):
    """W-1 (K-W4): the writer's `on_counted` (a watched mark, its undo or the option moved what counts) is the chores'
    forced index — for the writer the window starts with and for the one a language switch brings; nothing before
    the duties are made, nothing once the quit began."""
    class _Writer:
        on_counted = None

    class _Chores:
        def __init__(self):
            self.calls = []

        def index(self, force=False):
            self.calls.append(force)

    first, second = _Writer(), _Writer()
    services = shell.Services(writer=first)
    first.on_counted()                                  # no duties yet: nothing to ask
    services.chores = _Chores()
    first.on_counted()
    services._wire_writer(second)                       # (what `_switch_library` does with the new writer)
    second.on_counted()
    services.closing.set()
    second.on_counted()
    assert services.chores.calls == [True, True]
