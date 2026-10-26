"""Settings › Content › *Library folders* › *Skipped folders* and the looks' side of K6 (`app/qt/settings_sources.py`,
`app/services/source_looks.py`): each folder Surasura never reads listed under the folders with *Read again*, the list
hidden while there is none; *Read again* runs on the looks' worker, the folder's files come back at once, the line goes.

What a wrong answer would cost a learner:
  * a skipped folder he can't find again (no list), or an empty heading cluttering the page when there is none;
  * *Read again* that brings nothing back until the next hour, or blocks the window while it reads.

A real store in the test's own root, real Japanese subtitles from tests/Test Resources/, made-up folder names; the
source folder sits beside the data folder ("elsewhere"), never inside it.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")

from app import library_store as ls
from app.qt import settings_strings as S
from app.services import source_looks
from tests.qt.conftest import wait_until
from tests.qt.test_window_sources import (SHOW, _added, _folders_window, _fresh_run, _library, _read_store,  # noqa
                                          _source, _subtitle, window)

CARD = os.path.join("Old Backups", "Console Card")


def _with_card(folder):
    """The source folder with a backup's folder of two real subtitles beside its show."""
    for n in (1, 2):
        _subtitle(os.path.join(folder, CARD, "loader", "skins"), f"skin {n}.srt", 10 + n)
    return os.path.join(folder, CARD)


def test_settings_lists_a_skipped_folder_with_read_again_and_its_files_come_back(window):
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win = window(looks)
    folder = _source()
    card = _with_card(folder)
    answer = _added(looks, folder)
    assert answer["result"]["added"] == 4
    page, summary, row = _folders_window(win)                           # `row`: the *Library folders* window
    assert wait_until(lambda: answer["root"] in row.lines, 10)
    assert row.skip_box.isHidden() and row.skipped == {}                # none: no heading at all
    assert summary.summary.text() == S.SOURCES_FOLDERS_ONE
    store = _read_store(data_dir, user_files_dir)
    try:
        store.skip_folder(card)                                          # (⋯'s pick, as its writer lands it)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    finally:
        store.close()
    looks.listing()
    assert wait_until(lambda: len(row.skipped) == 1 and not row.skip_box.isHidden(), 10)
    assert summary.summary.text() == " · ".join([S.SOURCES_FOLDERS_ONE, S.SOURCES_SKIPPED_N.format(n=1)])
    line = next(iter(row.skipped.values()))
    assert line.words.text() == ls.folder_path(card) or line.words.toolTip() == ls.folder_path(card)
    assert line.read.toolTip() and row.skip_title.text() == S.SOURCES_SKIPPED
    scans = []
    real = looks._look
    looks._look = lambda full, roots: (scans.append((threading.current_thread(), roots)), real(full, roots))[1]
    line.read.click()
    assert wait_until(lambda: not row.skipped and row.skip_box.isHidden(), 10)
    assert wait_until(lambda: summary.summary.text() == S.SOURCES_FOLDERS_ONE, 10)     # the page followed it
    assert wait_until(lambda: win.bar_line.full() == S.SOURCES_READ_AGAIN_DONE.format(path=ls.folder_path(card)), 10)
    assert looks.idle(30)
    assert scans and scans[0][0] is not threading.main_thread() and scans[0][1] == {answer["root"]}
    store = _read_store(data_dir, user_files_dir)
    try:
        assert store.skipped_folders() == []
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 4     # back, once
    finally:
        store.close()


def test_read_again_of_another_languages_folder_is_refused():
    opener, _data, _uf = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    try:
        assert looks.read_again(1, language="zh") is False
    finally:
        looks.close()
        looks.idle(5)


def test_the_looks_answer_the_folders_to_skip_for_an_item_on_their_worker():
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    try:
        folder = _source()
        _with_card(folder)
        answer = _added(looks, folder)
        store = _read_store(data_dir, user_files_dir)
        try:
            item = next(i for i in answer["result"]["ids"] if "skin 1" in store.item(i)["rel_path"])
        finally:
            store.close()
        got = []
        assert looks.skippable([item], lambda folders: got.append((threading.current_thread(), folders)))
        assert looks.idle(10) and got
        assert got[0][0] is not threading.main_thread()
        assert got[0][1] == [ls.folder_path(os.path.join(folder, CARD, "loader", "skins")),
                             ls.folder_path(os.path.join(folder, CARD, "loader")), ls.folder_path(os.path.join(
                                 folder, CARD)), ls.folder_path(os.path.join(folder, "Old Backups"))]
    finally:
        looks.close()
        looks.idle(5)


def test_the_looks_answer_whether_a_folder_can_be_skipped_on_their_worker():
    # Q7: Settings' *Skip a folder…* asks the store's own rule first — a backup inside the folder may be skipped, the
    # folder itself may not (that's *Stop reading*) — on the looks' worker, never the window's thread.
    opener, _data, _uf = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    try:
        folder = _source()
        card = _with_card(folder)
        _added(looks, folder)
        got = []
        for path in (card, folder):
            assert looks.skip_refused(path, lambda why: got.append((threading.current_thread(), why)), language="ja")
        assert looks.idle(10) and len(got) == 2
        assert all(t is not threading.main_thread() for t, _why in got)
        assert [why for _t, why in got] == [None, ls.SKIP_IS_SOURCE]
        assert looks.skip_refused(card, got.append, language="zh") is False      # another language's: not asked
    finally:
        looks.close()
        looks.idle(5)
    assert looks.skip_refused(card, got.append) is False                         # closed


def test_a_sibling_folder_sharing_a_name_prefix_is_not_inside_the_source_folder():
    # why: a folder named like the source plus more letters (Source + "b") is a sibling, not inside the source, so a
    # backup in it is refused as outside the folders Surasura reads, never allowed as one of the source's own files.
    opener, _data, _uf = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    try:
        folder = _source()
        sibling = folder.rstrip("/\\") + "b"
        sibling_card = _with_card(sibling)
        _added(looks, folder)
        got = []
        assert looks.skip_refused(sibling_card, lambda why: got.append(why), language="ja")
        assert looks.idle(10) and len(got) == 1
        assert got == [ls.SKIP_OUTSIDE]                                          # the sibling is outside the folder
    finally:
        looks.close()
        looks.idle(5)


def test_skipping_a_folder_bumps_copy_dirty_so_the_connect_copy_carries_the_skip():
    # why: the Connect copy takes the skipped folders only when copy_dirty moves, so a skip change must bump it
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    try:
        folder = _source()
        card = _with_card(folder)
        _added(looks, folder)
        store = _read_store(data_dir, user_files_dir)
        try:
            before = int(store._meta().get("copy_dirty") or 0)
            store.skip_folder(card)
            assert len(store.skipped_folders()) == 1                         # the skip landed, not just the bump
            assert int(store._meta().get("copy_dirty") or 0) == before + 1
            # why: Read again moves the skip too, so it must carry the copy just as the skip does
            assert store.read_folder_again(store.skipped_folders()[0]["id"]) is True
            assert store.skipped_folders() == []
            assert int(store._meta().get("copy_dirty") or 0) == before + 2
        finally:
            store.close()
    finally:
        looks.close()
        looks.idle(5)


def test_a_folder_named_only_with_version_and_subtitle_words_is_a_versions_folder():
    # why: "synced_subtitles" is another version of the episodes above (a versions folder), not a folder of its own
    # that Surasura would list as a separate source. Glued with `_`, the subtitle word is kept (a bare "Subtitles" is
    # stripped first by _FOLDER_MARKS), so only the subtitle-word rule places it.
    from app.sources import _subtitle_folder
    assert _subtitle_folder("synced_subtitles", "Show", "ja") == "versions"


def test_a_stop_during_the_better_version_pass_ends_it_before_the_switch():
    # a Stop asked during the better-version pass (`_switch_better`) must end the pass before the store is asked
    # to switch anything — a stopped look keeps what it took in, and no switch starts after the Stop. The control
    # half runs the same pass unstopped and sees the store asked, so the stopped half can't pass by asking nothing.
    from types import SimpleNamespace
    from app.sources import _Look

    asked = []

    def fake_switch(ids, stop=None):
        asked.append(list(ids))
        raise ls.StoreError("busy: the next look tries again")

    store = SimpleNamespace(data_dir="unused", switch_versions=fake_switch)
    stopped_look = _Look(store, "ja", None, False, None, lambda: True, False, None)
    stopped_look.better = {"item-a"}
    stopped_look._switch_better()
    assert asked == [], "a Stop before the switch: the store is never asked"

    running_look = _Look(store, "ja", None, False, None, lambda: False, False, None)
    running_look.better = {"item-a"}
    running_look._switch_better()
    assert asked == [["item-a"]], "no Stop: the pass asks the store for the better version"
