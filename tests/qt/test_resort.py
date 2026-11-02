"""*Sort my library again* ends in the setup's load and sort screens (Fresh library 3.0.1, WP3; the spec §3.2, §6.1,
P11, P12): `SourceLooks.fresh` (the watches let go, the store's `start_fresh`, *Change folders…*'s changes after its
commit, every folder read again for sorting), `SourceLooks.put_back` (a Sorted-again backup, then a full look), the one
load sequence (`sort_screen.LoadRun`) over the window, and *Change folders…* (the wizard's folders page alone).

What a wrong answer would cost a learner:
  * a Sort again that lands his titles in Current in name order again (the reason it was asked for: never sorted);
  * folder changes that leak into the backup's copy — Put back then brings back folders he had removed, or loses the
    ones he had (the backup must hold the folder list as it was);
  * a Stop that throws away what was read, or a load screen that never ends;
  * a Put back that leaves the window reading a half-old library, or that never looks at the folders again;
  * *Change folders…* that reads his folders on its own before he pressed Sort again.

A real store in the test's own root with real Japanese subtitles (tests/Test Resources/ja), made-up show names; the
source folders sit beside the data folder ("elsewhere"), never inside it.
"""
import os
import sqlite3
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from app import library_store as ls
from app.qt import settings_sources, sort_screen
from app.qt import settings_strings as S
from app.qt import wizard as W
from app.qt import wizard_strings as WS
from app.services import source_looks
from tests.qt.conftest import wait_until
from tests.qt.test_drag import _stones_sheet  # noqa: F401  (the stones' sheet fixture)
from tests.qt.test_window_sources import (FakeWatch, RecordingLooks, _added, _fresh_run, _library,  # noqa: F401
                                          _read_store, _source, window)
from tests.qt.test_wizard import make  # noqa: F401  (`make`: the wizard over a stand-in window)

SHOWS = ("ぼっち・ざ・ろっく！", "葬送のフリーレン")


def _tiers(data_dir, user_files_dir):
    store = _read_store(data_dir, user_files_dir)
    try:
        return store.conn.execute("SELECT tier, rel_path FROM items ORDER BY rel_path").fetchall()
    finally:
        store.close()


def _roots(data_dir, user_files_dir):
    store = _read_store(data_dir, user_files_dir)
    try:
        return sorted((r["path"], r.get("on", True)) for r in store.sources(counts=False))
    finally:
        store.close()


def _backups(user_files_dir):
    trash = os.path.join(user_files_dir, ".trash")
    return sorted(os.path.join(trash, n) for n in os.listdir(trash) if n.startswith(ls.RESET_PREFIX)) \
        if os.path.isdir(trash) else []


def _backup_roots(folder):
    """The folder list the backup's store copy holds (what Put back brings back)."""
    db = next(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".db"))
    conn = sqlite3.connect(db)
    try:
        return sorted(p for (p,) in conn.execute("SELECT path FROM roots WHERE kind = 'source'"))
    finally:
        conn.close()


def _distinct(name, show, start, episodes=2):
    """A source folder whose subtitles differ from every other folder's (`_source` numbers each folder from 1: the
    same bytes in two folders are one item's copies)."""
    from tests.qt.test_window_sources import _subtitle
    root = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", name)
    for e in range(1, episodes + 1):
        _subtitle(os.path.join(root, show), f"{show} - {e:02d}.ja.srt", start + e)
    return root


def _looks(opener):
    return source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")


def _fresh(looks, **kw):
    """`fresh` with every answer recorded: (then's answer, scanned's, progress counts)."""
    answers, scanned, said = [], [], []
    assert looks.fresh(answers.append, progress=lambda f, s: said.append((f, s)), scanned=scanned.append, **kw)
    assert looks.idle(60)
    return answers[0], (scanned[0] if scanned else None), said


# --- the looks' half (writes: every rule a test) ---------------------------------------------------------------- #
def test_sort_again_lands_every_title_in_new_arrivals_for_the_sort_screen_and_says_its_ids():
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    try:
        _added(looks, _source(shows=SHOWS))
        before = [r for _t, r in _tiers(data_dir, user_files_dir)]
        assert len(before) == 4
        answer, scanned, said = _fresh(looks)
    finally:
        looks.close()
    assert answer["done"] and answer["known"] == "kept" and answer["folders"] is None
    after = _tiers(data_dir, user_files_dir)
    assert {t for t, _r in after} == {"arrivals"}, "read for sorting: New arrivals, never Current in name order"
    assert [r for _t, r in after] == before                                # the same episodes, once each
    assert scanned["found"] == 4 and not scanned["stopped"] and len(scanned["ids"]) == 4
    store = _read_store(data_dir, user_files_dir)
    try:
        assert sorted(scanned["ids"]) == sorted(i for (i,) in store.conn.execute("SELECT id FROM items"))
    finally:
        store.close()
    assert said and said[-1][0] == 4                                       # the load screen's count
    assert len(_backups(user_files_dir)) == 1                              # the old order, in one backup


def test_a_refused_sort_again_answers_why_reads_nothing_and_never_says_scanned(monkeypatch):
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    try:
        _added(looks, _source())
        before = _tiers(data_dir, user_files_dir)

        def refused(store, **_kw):
            raise ls.ResetRefused(ls.RESET_GENERATE)
        monkeypatch.setattr(ls, "start_fresh", refused)
        answer, scanned, _said = _fresh(looks)
    finally:
        looks.close()
    assert not answer["done"] and answer["refused"] == ls.RESET_GENERATE and scanned is None
    assert _tiers(data_dir, user_files_dir) == before


def test_change_folders_lands_after_the_commit_so_the_backup_keeps_the_folder_list_as_it_was():
    # P11: the backup's store copy is made before the changes: Put back brings back the folders he had then
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    old, new = _source("Anime", shows=SHOWS[:1]), _source("Dramas", shows=SHOWS[1:])
    try:
        old_root = _added(looks, old)["root"]
        answer, scanned, _said = _fresh(looks, folders={"add": [new], "stop": [old_root], "skip": []})
    finally:
        looks.close()
    assert answer["done"] and answer["folders"]["added"] and answer["folders"]["stopped"] == [old_root]
    live = [p for p, on in _roots(data_dir, user_files_dir) if on]
    assert [os.path.normcase(p) for p in live] == [os.path.normcase(new)]
    assert [os.path.normcase(p) for p in _backup_roots(_backups(user_files_dir)[0])] == [os.path.normcase(old)]
    rels = [r for _t, r in _tiers(data_dir, user_files_dir)]
    assert rels and all(SHOWS[1] in r for r in rels), "only the folder read now was read again"
    assert len(scanned["ids"]) == 2


def test_a_folder_change_the_store_refuses_is_named_and_the_others_still_land():
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    good = _source("Anime", shows=SHOWS[:1])
    try:
        answer, _scanned, _said = _fresh(looks, folders={"add": [data_dir, good], "stop": [], "skip": []})
    finally:
        looks.close()
    folders = answer["folders"]
    assert len(folders["added"]) == 1 and [p for p, _why in folders["refused"]] == [data_dir]
    assert [os.path.normcase(p) for p, _on in _roots(data_dir, user_files_dir)] == [os.path.normcase(good)]


def test_stop_keeps_what_came_in_and_the_scanned_answer_says_stopped(monkeypatch):
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    first, second = _source("Anime", shows=SHOWS[:1]), _source("Dramas", shows=SHOWS[1:])
    stop = threading.Event()
    try:
        _added(looks, first)
        _added(looks, second)
        real = ls.Store.take_in

        def take_in(self, *a, **kw):
            change = real(self, *a, **kw)
            stop.set()                                                    # Stop pressed after the first take-in
            return change
        monkeypatch.setattr(ls.Store, "take_in", take_in)
        answer, scanned, _said = _fresh(looks, stop=stop.is_set)
    finally:
        looks.close()
    assert answer["done"] and scanned["stopped"]
    rows = _tiers(data_dir, user_files_dir)
    assert rows and len(rows) < 4 and {t for t, _r in rows} == {"arrivals"}
    assert len(scanned["ids"]) == len(rows)


def test_the_watches_are_let_go_before_the_reset_moves_anything_and_followed_again_after(monkeypatch):
    # R4: a watch's handle on a folder inside the data folder would turn the reset's renames into copies
    opener, data_dir, user_files_dir = _library()
    made = []

    def watch(path, wake):
        w = FakeWatch(path, wake)
        made.append(w)
        return w
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "local", watch=watch)
    seen = []
    real = ls.start_fresh

    def start_fresh(store, **kw):
        seen.append([w for w in made if w.state != "closed"])
        return real(store, **kw)
    monkeypatch.setattr(ls, "start_fresh", start_fresh)
    try:
        _added(looks, _source())
        assert any(w.state != "closed" for w in made)
        _fresh(looks)
        assert seen == [[]], "every watch closed before the reset"
        assert any(w.state != "closed" for w in made), "followed again after it"
    finally:
        looks.close()


def test_put_back_brings_the_old_order_back_in_one_write_then_looks_at_every_folder():
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    try:
        _added(looks, _source(shows=SHOWS))
        before = _tiers(data_dir, user_files_dir)
        _fresh(looks)
        assert {t for t, _r in _tiers(data_dir, user_files_dir)} == {"arrivals"}
        backup = _backups(user_files_dir)[0]
        answers = []
        assert looks.put_back(backup, answers.append)
        assert looks.idle(60)
    finally:
        looks.close()
    assert answers[0]["done"] and answers[0]["put_back"] == backup and answers[0]["backup"]
    assert _tiers(data_dir, user_files_dir) == before                      # the order from then, row for row
    assert answers[0]["backup"] in _backups(user_files_dir)               # the library it replaced, its own backup


def test_put_back_refused_answers_why_and_changes_nothing():
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    try:
        _added(looks, _source())
        before = _tiers(data_dir, user_files_dir)
        answers = []
        assert looks.put_back(os.path.join(user_files_dir, ".trash", "library-reset-20260101-000000"), answers.append)
        assert looks.idle(30)
    finally:
        looks.close()
    assert not answers[0]["done"] and answers[0]["refused"]
    assert _tiers(data_dir, user_files_dir) == before


# --- the window's half: the one load run, the sort screen's resort door ---------------------------------------- #
class ResortLooks(RecordingLooks):
    """The looks as Sort again calls them: `fresh` recorded and answered as told (its read answered by the test)."""

    def __init__(self, answer=None):
        super().__init__()
        self.answer = answer or {"done": True, "known": "kept", "backup": "C:/backups/library-reset-x"}
        self.calls = []

    def fresh(self, then=None, folders=None, progress=None, stop=None, scanned=None):
        self.calls.append({"folders": folders, "stop": stop, "progress": progress, "scanned": scanned})
        then(dict(self.answer))
        return True


def test_sort_again_covers_the_window_counts_the_read_then_sorts_with_the_resort_door(window):
    looks = ResortLooks()
    seed, win = window(looks)
    run = settings_sources.sort_again(win)
    assert isinstance(run, sort_screen.LoadRun) and run.door == "resort"
    assert isinstance(run.loading, sort_screen.LoadScreen) and run.loading.isVisible()   # pending at the press
    assert run.loading.geometry() == win.centralWidget().rect()
    assert settings_sources.running(win) == S.FRESH_RUNNING_TIP
    call = looks.calls[0]
    assert call["folders"] is None
    call["progress"](12, 3)
    assert wait_until(lambda: run.loading.task.text() == WS.LOAD_SCAN.format(episodes="12 episodes",
                                                                            shows="3 shows"), 5)
    call["scanned"]({"ids": [1, 2], "found": 2, "shows": 1, "stopped": False})
    assert wait_until(lambda: run.state["step"] == "sort", 10)             # no indexer, covers or Anki to wait for
    screen = win.__dict__.get("_sort_screen")
    assert isinstance(screen, sort_screen.SortScreen) and screen.door == "resort"
    assert screen.btn_done.toolTip() == WS.SORT_RESORT_DONE_TIP
    QTest.mouseClick(screen.btn_done, Qt.MouseButton.LeftButton)
    assert run.ended and settings_sources.running(win) is None
    assert win.current_tab() == "current"
    assert win.toasts.text == S.FRESH_SORTED


def test_stop_on_the_load_screen_stops_the_read_and_a_refusal_lifts_the_cover(window):
    looks = ResortLooks()
    seed, win = window(looks)
    run = settings_sources.sort_again(win)
    stop = looks.calls[0]["stop"]
    assert not stop()
    assert wait_until(lambda: run.loading.btn_stop.isEnabled(), 5)        # once the order is aside (F5)
    QTest.mouseClick(run.loading.btn_stop, Qt.MouseButton.LeftButton)
    assert stop(), "the read stops between files"
    looks.calls[0]["scanned"]({"ids": [5], "found": 1, "shows": 1, "stopped": True})
    assert wait_until(lambda: run.state["step"] == "sort", 5)              # stopped: straight to the sorting
    run.end()
    refused = ResortLooks({"done": False, "refused": ls.RESET_CONNECT})
    seed, win = window(refused)
    run = settings_sources.sort_again(win)
    assert wait_until(lambda: run.ended, 5) and settings_sources.running(win) is None
    assert win.bar_line.full() == S.FRESH_REFUSED.format(reason=ls.RESET_CONNECT)


def test_a_read_that_found_nothing_goes_to_current_and_says_so(window):
    looks = ResortLooks()
    seed, win = window(looks)
    run = settings_sources.sort_again(win)
    looks.calls[0]["scanned"]({"ids": [], "found": 0, "shows": 0, "stopped": False})
    assert wait_until(lambda: run.ended, 5)
    assert win.current_tab() == "current" and win.toasts.text == S.FRESH_SORTED_NOTHING


def test_one_sort_again_at_a_time(window):
    looks = ResortLooks()
    seed, win = window(looks)
    assert settings_sources.sort_again(win) is not None
    assert settings_sources.sort_again(win) is None and len(looks.calls) == 1


# --- *Change folders…*: the wizard's folders page alone (never reads) ------------------------------------------- #
def test_change_folders_lists_the_folders_read_now_and_hands_back_the_changes_without_reading(make, tmp_path):
    wiz_plain, shell, api, _settings, _m = make()
    wiz_plain._close("later")
    a, b = str(tmp_path / "Anime"), str(tmp_path / "Dramas")
    os.makedirs(a)
    os.makedirs(b)
    shell.sources = ({"id": 7, "path": a, "on": True}, {"id": 8, "path": "C:/off", "on": False})
    handed = []
    wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=api, resort=handed.append)
    shell.centralWidget().layout().addWidget(wiz)
    page = wiz.page
    assert page.id == "shows" and page.folders == [a], "the folders being read, each with Remove"
    assert wiz.btn_back.isHidden() and wiz.btn_skip.isHidden() and wiz.steps.isHidden()
    assert wiz.btn_next.text() == WS.RESORT_NEXT and wiz.btn_later.text() == WS.RESORT_BACK
    page.entered()
    assert page.btn_file.isHidden() and page.btn_youtube.isHidden()      # folders only
    page.remove_folder(a)
    page.add_folder(b)
    page.add_skip(os.path.join(b, "Extras"))
    wiz.next()
    assert handed == [{"add": [b], "stop": [7], "skip": [os.path.join(b, "Extras")]}]
    assert wiz._gone and not [c for c in api.calls if c[0] == "read_folders"], "nothing read here"


def test_change_folders_back_changes_nothing(make):
    wiz_plain, shell, api, _settings, _m = make()
    wiz_plain._close("later")
    handed = []
    wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=api, resort=handed.append)
    wiz.finish_later()
    assert handed == [] and wiz._gone


def test_put_back_lets_the_watches_go_before_it_moves_anything(monkeypatch):
    # R4, as Sort again's: the backup's folders move back by rename, never held by a watch
    opener, data_dir, user_files_dir = _library()
    made = []

    def watch(path, wake):
        w = FakeWatch(path, wake)
        made.append(w)
        return w
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "local", watch=watch)
    seen = []
    real = ls.put_back_library

    def put_back_library(store, folder, **kw):
        seen.append([w for w in made if w.state != "closed"])
        return real(store, folder, **kw)
    monkeypatch.setattr(ls, "put_back_library", put_back_library)
    try:
        _added(looks, _source())
        _fresh(looks)
        assert any(w.state != "closed" for w in made)
        answers = []
        assert looks.put_back(_backups(user_files_dir)[0], answers.append)
        assert looks.idle(60)
    finally:
        looks.close()
    assert answers[0]["done"] and seen == [[]]


# --- the review's round (F5, F6, F7) ---------------------------------------------------------------------------- #
class HeldLooks(ResortLooks):
    """`fresh` whose reset answers only when the test says so (a reset at 60k takes seconds)."""

    def fresh(self, then=None, folders=None, progress=None, stop=None, scanned=None):
        self.calls.append({"then": then, "stop": stop, "scanned": scanned, "progress": progress})
        return True


def test_stop_waits_for_the_order_to_be_aside_and_says_what_runs_meanwhile(window):
    # F5: a Stop pressed during the reset broke the read before the first folder: an empty library, "nothing to sort"
    looks = HeldLooks()
    seed, win = window(looks)
    run = settings_sources.sort_again(win)
    assert run.loading.task.text() == S.FRESH_SETTING_ASIDE and not run.loading.btn_stop.isEnabled()
    QTest.mouseClick(run.loading.btn_stop, Qt.MouseButton.LeftButton)
    assert not looks.calls[0]["stop"](), "no Stop reaches the read while the reset runs"
    looks.calls[0]["then"]({"done": True, "known": "kept", "backup": "B"})
    assert wait_until(lambda: run.loading.btn_stop.isEnabled(), 5)
    assert run.loading.task.text() == WS.LOAD_SCAN.format(episodes="0 episodes", shows="0 shows")
    run.end()


def test_a_read_stopped_before_anything_came_looks_again_and_says_the_folders_come_in(window):
    looks = ResortLooks()
    seed, win = window(looks)
    run = settings_sources.sort_again(win)
    assert wait_until(lambda: run.loading.btn_stop.isEnabled(), 5)
    QTest.mouseClick(run.loading.btn_stop, Qt.MouseButton.LeftButton)
    looks.asks.clear()
    looks.calls[0]["scanned"]({"ids": [], "found": 0, "shows": 0, "stopped": True})
    assert wait_until(lambda: run.ended, 5)
    assert win.toasts.text == S.FRESH_SORTED_STOPPED and (False, True, True) in looks.asks


def test_the_window_under_the_sort_again_cover_takes_no_focus(window):
    # F7: Tab from the load screen never reaches the window's own parts hidden under it
    looks = ResortLooks()
    seed, win = window(looks)
    area = win.centralWidget()
    parts = [area.layout().itemAt(i).widget() for i in range(area.layout().count())]
    parts = [w for w in parts if w is not None]
    run = settings_sources.sort_again(win)
    assert all(not w.isEnabled() for w in parts if w is not run.loading)
    run.end()
    assert all(w.isEnabled() for w in parts)


def test_change_folders_hides_setups_samples_covers_and_cores_and_esc_is_back(make):
    # F6: *Try it with samples first* copied samples in at once (nothing changes until Sort again), the switches
    # did nothing here; Esc closes it as Back (the GUI rule), nothing handed on
    wiz_plain, shell, api, _settings, _m = make()
    wiz_plain._close("later")
    handed = []
    wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=api, resort=handed.append)
    page = wiz.page
    page.entered()
    assert page.btn_samples.isHidden() and page.covers.isHidden() and page.every_core.isHidden()
    QTest.keyClick(wiz, Qt.Key.Key_Escape)
    assert wiz._gone and handed == []


# --- the mutants' round (W05, W07, W11) --------------------------------------------------------------------------- #
def test_stop_inside_one_folder_stops_between_its_shows(monkeypatch):
    # W05: the load screen's Stop reaches the read of the folder under way, not only the next folder
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    stop = threading.Event()
    try:
        _added(looks, _source("Anime", shows=SHOWS))                       # one folder, two shows
        real = ls.Store.take_in

        def take_in(self, *a, **kw):
            change = real(self, *a, **kw)
            stop.set()
            return change
        monkeypatch.setattr(ls.Store, "take_in", take_in)
        _answer, scanned, _said = _fresh(looks, stop=stop.is_set)
    finally:
        looks.close()
    rows = _tiers(data_dir, user_files_dir)
    assert scanned["stopped"] and 0 < len(rows) < 4


def test_the_ids_of_every_folder_read_reach_the_sort_screen():
    # W07: the scanned answer holds the items of every folder, not only the last one's
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    try:
        _added(looks, _source("Anime", shows=SHOWS[:1]))
        _added(looks, _distinct("Dramas", SHOWS[1], start=10))           # (never the same bytes as Anime's)
        _answer, scanned, _said = _fresh(looks)
    finally:
        looks.close()
    assert len(scanned["ids"]) == 4 and scanned["found"] == 4


def test_put_back_looks_at_every_folder_after_so_a_file_new_since_comes_in():
    # W11: the library from then, then a full look: an episode that arrived after the Sort again isn't lost
    opener, data_dir, user_files_dir = _library()
    looks = _looks(opener)
    try:
        folder = _source(shows=SHOWS[:1])
        _added(looks, folder)
        _fresh(looks)
        from tests.qt.test_window_sources import _subtitle
        _subtitle(os.path.join(folder, SHOWS[0]), f"{SHOWS[0]} - 09.ja.srt", 9)
        answers = []
        assert looks.put_back(_backups(user_files_dir)[0], answers.append)
        assert looks.idle(60)
    finally:
        looks.close()
    assert answers[0]["done"]
    assert any(r.endswith("09.ja.srt") for _t, r in _tiers(data_dir, user_files_dir)), "read by the look after"


class _IndexerChores:
    """The window's chores as the load run asks them: an index ask that is always under way (`indexing()` True) and
    a log under the test's folder; nothing else."""

    def __init__(self, log):
        self.log = log

    def index(self, force=False):
        return None

    def index_log(self):
        return self.log

    def indexing(self):
        return True


def test_the_load_screen_counts_only_its_own_languages_indexer_runs(tmp_path, qapp):
    """Another language's indexer runs don't end the words step: three runs of zh leave a ja load on the index step,
    and three of ja end it. Why: a Chinese library's indexer run must not finish a Japanese load's words early."""
    shell = type("Shell", (), {"chores": _IndexerChores(str(tmp_path / "index.log"))})()
    run = sort_screen.LoadRun(shell, lambda widget: None, door="resort", language=lambda: "ja",
                              sort=lambda: None)
    run.begin()
    try:
        run.scanned([1])
        for _ in range(3):
            run.indexed("zh")
        assert run.state["step"] == "index", "a zh run never counts toward a ja load's words step"
        for _ in range(2):
            run.indexed("ja")
        assert run.state["step"] == "index", "two ja runs do not end the words step"
        run.indexed("ja")
        assert run.state["step"] != "index", "three ja runs end the words step"
    finally:
        run.end()
