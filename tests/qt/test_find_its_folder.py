"""MV-2 in the window (Sonic: yes, 2026-10-23): an episode whose video left the folder it was in shows Connect's line —
*This episode's video isn't where it was (<folder>).* — on its *No video* and ▶'s place, and offers *Find its
folder…* first on its status's menu and on its ⋯. Picked, the folder goes through Settings' own *Add a folder…*
(`settings_sources.add_folder` → `Adder.read_folder` → the store's `add_source` and its look): the one way in, so the
store's join (MV-1) is the only rule that puts the show's episodes there. A look that recorded videos for known
episodes kicks Connect (on a worker), so a job waiting on that video goes on now, not at Connect's next start.

What a wrong answer costs a learner: a moved show's episodes stuck on *No video* with nothing to click, a second copy of
his show from a second way in, or a click that adds nothing. Names are made up; the folder added is a real temp folder
beside the test's data folder holding real subtitles.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QRect  # noqa: E402

from app.connect import kick  # noqa: E402
from app.qt import press as qpress  # noqa: E402
from app.qt import rows, strings  # noqa: E402
from app.services import source_looks, view_rows  # noqa: E402
from tests.qt.conftest import wait_until  # noqa: E402
from tests.qt.test_p41_actions import act, lst_of, row_with  # noqa: E402,F401
from tests.qt.test_window_sources import _library, _read_store, _source, window  # noqa: E402,F401

OLD = os.path.join("Z:\\", "アニメ", "[Grp] 月影の旅人")         # where the video was (no such drive: the picker
#                                                                  opens at the nearest folder still there)


def _moved(ep, folder=OLD):
    """`ep` as the rows hold it once Connect's feed says its video left `folder` (`view_rows._connected`)."""
    line = f"This episode's video isn't where it was ({folder})."
    status = view_rows.Status("no_media", "No video", view_rows.STRINGS["tip_connect_moved"].format(tip=line), "warn",
                              moved=folder)
    return ep._replace(status=status)


def test_a_moved_episode_offers_find_its_folder_first_and_a_plain_one_never(act):
    # why: the learner's way on is the folder; Link… and Mine text stay. A No video that didn't move (never downloaded,
    # a drive unplugged) offers nothing about a folder
    _seed, win, _writer = act()
    lst = lst_of(win)
    row = lst.model().entries[row_with(lst, "no_media", None)][1]
    ep = row.episodes[0]
    rect = QRect(10, 10, 40, 20)
    lst._press_action("no-media", rect, row, rows.Ask(ep.id, (ep.id,), _moved(ep)), "tip")
    menu = lst.action_menu
    assert [a.text() for a in menu.actions()] == [strings.ROWS_FIND_FOLDER, strings.ROWS_LINK, strings.ROWS_MINE_TEXT]
    assert OLD in menu.actions()[0].toolTip()
    menu.close()
    lst._press_action("no-media", rect, row, rows.Ask(ep.id, (ep.id,), ep._replace(status=view_rows.Status(
        "no_media", "No video", "tip", "warn"))), "tip")
    assert [a.text() for a in lst.action_menu.actions()] == [strings.ROWS_LINK, strings.ROWS_MINE_TEXT]
    lst.action_menu.close()
    entries = win.mine.episode_entries(row, _moved(ep))
    assert [(e.name, e.label, e.writes) for e in entries] == [("ep-find-folder", strings.ROWS_FIND_FOLDER, True)]
    name, tip, _ask = rows.action_of(_moved(ep).status, (_moved(ep),), None, "video")
    assert name == "no-media" and "find its folder" in tip


def test_find_its_folder_adds_the_folder_picked_through_settings_add_a_folder(window):
    # why (MV-2: one way in): the folder is read from now on through the store's add_source and its look — never a
    # setting of Connect's, never a second path; the picker opens where the video was, or the nearest folder above
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    _seed, win = window(looks)
    folder = _source("Moved")
    old = os.path.join(os.path.dirname(folder), "Gone", "[Grp] 月影の旅人")
    asked = []
    win.mine.pick_folder = lambda title, where: (asked.append((title, where)), folder)[1]
    row = next(e[1] for e in win.page_widgets["current"].list.model().entries if e[0] == rows.ROW)
    ep = _moved(row.episodes[0], old)
    assert win.mine.find_folder(ep) is True
    assert asked == [(strings.FIND_FOLDER_TITLE.format(label=ep.label), os.path.dirname(old))]

    def read():
        store = _read_store(data_dir, user_files_dir)
        try:
            return [s["path"] for s in store.sources()]
        finally:
            store.close()
    assert wait_until(lambda: read() == [folder] or [os.path.normcase(p) for p in read()] ==
                      [os.path.normcase(folder)], 30)
    assert wait_until(lambda: not qpress.presses_of(win).any_live(), 30), "the add's press ends with its look"
    win.mine.pick_folder = lambda title, where: ""
    assert win.mine.find_folder(ep) is False, "a cancelled picker adds nothing"


@pytest.mark.parametrize("moved, waiting, kicks", [(2, True, 1), (0, True, 0), (2, False, 0)],
                         ids=["videos-found-and-one-waits", "nothing-found", "nobody-waits"])
def test_a_look_that_recorded_videos_kicks_connect_only_while_an_episode_waits_on_its_video(window, monkeypatch,
                                                                                         moved, waiting, kicks):
    # why: a job waiting on No video is parked for Connect's next start; after *Find its folder* (a look that
    # recorded videos for known episodes) the next start is now. A look that changed nothing, or found a new
    # episode's video while no episode waits on one, starts nothing (S19: a Connect run is a sync and more)
    from app.connect import feed
    from app.qt import shell
    looks = source_looks.SourceLooks(_library()[0], "ja", kind=lambda _p: "network")
    _seed, win = window(looks)
    called = []
    monkeypatch.setattr(kick, "kick", lambda settings: called.append(dict(settings)))
    item = feed.Item(kind=feed.NO_VIDEO if waiting else feed.WAITING, words="", tip="", job=1, made=0, total=0)
    latest = feed.NOT_LOOKED._replace(on=True, items={7: item})
    monkeypatch.setattr(shell, "connect_feed", lambda _l, _s: type("P", (), {"latest": lambda self: latest})())
    win._sources_looked({"sources": [], "moved": moved, "language": win.language})
    if kicks:
        assert wait_until(lambda: len(called) == kicks, 5)
    else:
        win._sources_looked({"sources": [], "language": win.language})
        wait_until(lambda: called, 0.5)
        assert called == []
