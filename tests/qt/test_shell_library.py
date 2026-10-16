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
        inside["before"] = (numbers.why(), services.library._thread)   # nothing read, no reader before the frame
        inside["language"] = (services.library.language, services.writer.language, win.language)
        inside["one_opener"] = services.writer.opener is services.library.opener is numbers.opener
        inside["journal"] = services.writer.journal_file
        inside["cache"] = services.library.cache_file
        inside["rows"] = wait_until(lambda: _state(win) == "full", 15)   # (offscreen: the first frame comes here)
        inside["after"] = numbers.idle(30) and numbers.why()
        win.close()
        return 0

    monkeypatch.setattr(single_module, "SingleInstance", OneInstance)
    monkeypatch.setattr(shell, "open_services", spy_open)
    monkeypatch.setattr(shell, "open_window", spy_window)
    monkeypatch.setattr(QApplication, "exec", fake_exec)
    monkeypatch.setattr(shell, "prepare_process", lambda: None)
    assert shell.main(["surasura"]) == 0
    assert asked == [{"freeze_gc": True}]
    assert inside["before"] == ("not read yet", None)
    assert inside["after"] == "no plan: Generate first"     # loaded once the frame was out
    assert inside["language"] == ("zh", "zh", "zh")
    assert inside["one_opener"]
    assert inside["journal"] == moves_module.journal_path("zh")
    assert inside["cache"] == library_reader.cache_path("zh")
    assert inside["rows"]
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
    assert services.writer.can_write()


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
    assert services._switch_library("zh") is False and services.library is None


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
