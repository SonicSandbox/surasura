"""Kantan-B5 (a tester's report on 3.0.6 and his outside PR #421): *Needs you* said an episode's subtitle was "Not timed
to its video (refused) … this is not the same episode". He had linked it by hand to the NEXT episode's video, and once
an episode has a video — right or wrong — nothing offered to pick again: *Link…* shows only while it has none. The
store already takes a newer link over an old one (`link.link`, `library.pairing_of`: the newest pairing wins); only the
door was missing.

Here, the window's side: *Not timed*'s card offers *Change its video…* between *Check again* and *Mine anyway*, and so
does the episode's ⋯ beside its *Check again* (`mine_actions.change_video`) — the system's picker opened at the folder
of the video it is linked to now (`own_folder.read_video`, on a worker), the pick linked through the writer's
`link_video` (one change: the toast's Undo), and only once that change is saved its timing checked again
(`check_job`: Connect's `check_again`, on a worker, Connect kicked); the bar says so and *Needs you* is read again.
Connect's own side, on a real store and ledger: `tests/connect/test_change_video.py`.

What a wrong answer would cost: a learner who picked the wrong video stuck for good with *Mine anyway* (cards cut from
another episode's video) as the only way on; or a check run before the new link landed (the wrong video checked again
and refused again); or a cancelled picker, the same video again, or a store that can't write now, still writing.

On the window's seed (Japanese titles) through a recording writer (`test_p41_actions`'s), the episode a real one of it.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.connect import feed
from app.qt import rows, strings
from app.services import needs as service
from app.services import own_folder
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, settle
from tests.qt.test_nt_check_again import _not_timed_row
from tests.qt.test_p41_actions import act, lst_of     # noqa: F401  (act: a fixture)

REFUSED = ("ダンジョン飯 S01E07.ja.srt: Not timed to its video (refused), so no cards. tsubasa: 29% of reference "
           "lines matched … this is not the same episode")


def _links(writer):
    return [c for c in writer.calls if c[0] == "link_video"]


def _card(win, ep):
    """*Needs you* reading one *Not timed* line Connect wrote for `ep` -> the card's entry."""
    ny = win.needs_you
    ny.read_connect = lambda _lang: {"jobs": [], "gaps": [], "needs": [
        {"id": 31, "kind": "not-timed", "say": REFUSED, "item": ep.id, "seen_at": None, "at": "2026-11-13T05:18:21Z"}]}
    ny.read_settings = lambda: {"connect_enabled": True, "connect_video_folders": {}}
    settle(ny)
    return next(e for e in ny.entries if (e.data or {}).get("need_id") == 31)


def _wired(win, monkeypatch, tmp_path, current="E08", pick="E07"):
    """The video the episode is linked to now (in a real folder), what the picker answers, and the check handed to the
    worker — recorded: (the pickers' starts, the checks: (language, ids, was the link saved then, on a worker))."""
    folder = tmp_path / "videos" / "Dungeon Meshi"
    folder.mkdir(parents=True)
    now = str(folder / f"Dungeon Meshi S01{current}-[1080p][BDRIP][x265.FLAC].mkv")
    picked = str(folder / f"Dungeon Meshi S01{pick}-[1080p][BDRIP][x265.FLAC].mkv") if pick else ""
    asked_of = []
    monkeypatch.setattr(own_folder, "read_video", lambda opener, data, item_id, rel=None:
                        asked_of.append((item_id, rel, threading.current_thread() is threading.main_thread())) or
                        (str(folder), now))
    started, checks = [], []
    win.mine.pick_file = lambda title, start, patterns: started.append((title, start, patterns)) or picked
    main = threading.main_thread()
    writer = win.moves.writer

    def check(language, ids, _settings):
        checks.append((language, list(ids), bool(writer.saved), threading.current_thread() is not main))
        return list(ids)
    win.mine.check_job = check
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    return SimpleRecord(now=now, picked=picked, folder=str(folder), asked_of=asked_of, started=started, checks=checks)


class SimpleRecord:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# --- the card -------------------------------------------------------------------------------------------------------- #
def test_not_timed_offers_change_its_video_between_check_again_and_mine_anyway(act):
    """The dead end, reproduced: the card offered *Check again* · *Mine anyway* · *Dismiss* — none of them lets the
    learner pick another video. Now *Change its video…* is there, with its words and its tooltip."""
    _seed, win, _writer = act()
    i, row = _not_timed_row(lst_of(win))
    entry = _card(win, row.episodes[0])
    names = [b.property("action") for b in win.needs_you.cards.buttons(entry.key)]
    assert names == ["check_again", "change_video", "mine_anyway", "dismiss"]
    b = button(win.needs_you, entry.key, "change_video")
    assert b.text() == strings.ROWS_CHANGE_VIDEO == "Change its video…" and b.toolTip()
    assert service.CONNECT_ACTIONS["not-timed"] == ("check_again", "change_video", "mine_anyway")


def test_no_window_routing_hides_change_its_video_never_a_button_that_does_nothing(act):
    _seed, win, _writer = act()
    i, row = _not_timed_row(lst_of(win))
    entry = _card(win, row.episodes[0])
    ny = win.needs_you
    hook = ny.hooks.pop("change_video")
    ny.rewire()
    assert button(ny, entry.key, "change_video") is None and button(ny, entry.key, "check_again") is not None
    ny.hooks["change_video"] = hook


def test_the_cards_change_its_video_opens_at_its_videos_folder_links_the_pick_then_checks_it_again(act, monkeypatch,
                                                                                                  tmp_path):
    """Mattias's own case: linked to E08's video, he picks E07's. The picker opens where E08's video is (looked for on a
    worker), videos only; the pick is linked to THAT episode through the writer (its toast, with Undo); then — and only
    once the link is saved — its timing is checked again on a worker, and the bar says so."""
    _seed, win, writer = act()
    i, row = _not_timed_row(lst_of(win))
    ep = row.episodes[0]
    entry = _card(win, ep)
    assert entry.data["label"] == ep.label and entry.data["rel_path"] == ep.rel_path, "the view's own episode"
    rec = _wired(win, monkeypatch, tmp_path)
    button(win.needs_you, entry.key, "change_video").click()
    assert wait_until(lambda: rec.checks, 5)
    assert rec.asked_of == [(ep.id, ep.rel_path, False)], "where it opens: read on a worker"
    assert rec.started == [(strings.LINK_TITLE.format(label=ep.label), rec.folder, rec.started[0][2])]
    assert "*.mkv" in rec.started[0][2], "videos only"
    assert _links(writer) == [("link_video", [ep.id], {"path": rec.picked})], "the writer's link: one change"
    assert rec.checks == [(win.language, [ep.id], True, True)], "checked once the link was saved, on a worker"
    assert wait_until(lambda: win.bar_line.full() == strings.NEEDS_CHECK_AGAIN, 5)
    assert [c[0] for c in writer.calls] == ["link_video"], "nothing else written: no move, no ask"


def test_a_cancelled_picker_the_same_video_or_a_store_that_cant_write_links_and_checks_nothing(act, monkeypatch,
                                                                                              tmp_path):
    _seed, win, writer = act()
    i, row = _not_timed_row(lst_of(win))
    ep = row.episodes[0]
    rec = _wired(win, monkeypatch, tmp_path, pick=None)                        # the picker cancelled
    win.mine.change_video(ep.id, ep.label, ep.rel_path)
    assert wait_until(lambda: rec.started, 5)
    for _ in range(20):
        QApplication.processEvents()
    assert _links(writer) == [] and rec.checks == []
    rec.started.clear()
    win.mine.pick_file = lambda title, start, patterns: rec.started.append(start) or rec.now   # the same one
    win.mine.change_video(ep.id, ep.label, ep.rel_path)
    assert wait_until(lambda: win.bar_line.full() == strings.CHANGE_VIDEO_SAME, 5)
    assert _links(writer) == [] and rec.checks == []
    rec.started.clear()
    writer.writable = False                                                    # the store takes no change now
    win.mine.change_video(ep.id, ep.label, ep.rel_path)
    assert wait_until(lambda: strings.store_reason(writer.why) in (win.bar_line.full() or ""), 5)
    assert rec.started == [], "no picker for a change the store can't take: said first"
    assert _links(writer) == [] and rec.checks == []


def test_a_link_that_lands_as_nothing_is_never_checked(act, monkeypatch, tmp_path):
    """The store's None (the very link there already, by another path): the ticket ends unsaved, nothing is checked."""
    _seed, win, writer = act()
    i, row = _not_timed_row(lst_of(win))
    ep = row.episodes[0]
    rec = _wired(win, monkeypatch, tmp_path)
    writer.nothing.add("link_video")
    win.mine.change_video(ep.id, ep.label, ep.rel_path)
    assert wait_until(lambda: _links(writer), 5)
    for _ in range(30):
        QApplication.processEvents()
    assert rec.checks == []


def test_connect_off_still_links_and_says_why_nothing_is_made(act, monkeypatch, tmp_path):
    """As *Link…* (it still works with Connect off): the link is the learner's to make; the check is recorded for
    Connect's next run, and the bar says Connect is off rather than "checked again"."""
    _seed, win, writer = act(connect_off=feed.OFF_CONNECT)
    i, row = _not_timed_row(lst_of(win))
    ep = row.episodes[0]
    rec = _wired(win, monkeypatch, tmp_path)
    win.mine.change_video(ep.id, ep.label, ep.rel_path)
    assert wait_until(lambda: rec.checks, 5)
    assert _links(writer) == [("link_video", [ep.id], {"path": rec.picked})]
    assert wait_until(lambda: win.bar_line.full() == feed.OFF_CONNECT, 5)


def test_pressed_again_while_it_looks_asks_nothing_more(act, monkeypatch, tmp_path):
    _seed, win, writer = act()
    i, row = _not_timed_row(lst_of(win))
    ep = row.episodes[0]
    rec = _wired(win, monkeypatch, tmp_path)
    gate = threading.Event()
    real = own_folder.read_video
    monkeypatch.setattr(own_folder, "read_video", lambda *a, **k: gate.wait(5) and real(*a, **k))
    first = win.mine.change_video(ep.id, ep.label, ep.rel_path)
    assert first is not None and win.mine.change_video(ep.id, ep.label, ep.rel_path) is None, "one press"
    gate.set()
    assert wait_until(lambda: rec.checks, 5)
    assert len(rec.started) == 1 and len(_links(writer)) == 1


# --- the episode's ⋯ ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", [feed.NOT_TIMED, feed.SKIPPED])
def test_the_episodes_menu_offers_change_its_video_beside_check_again_and_a_pick_links_it(act, monkeypatch, tmp_path,
                                                                                         kind):
    """Listed or dismissed (the row's *Skipped: not timed*): the ⋯ is where a dismissed card's episode is reached."""
    _seed, win, writer = act()
    i, row = _not_timed_row(lst_of(win), kind)
    ep = row.episodes[0]
    entries = win.mine.episode_entries(row, ep)
    assert [e.name for e in entries] == ["ep-" + rows.CHECK, "ep-change-video"]
    change = entries[1]
    assert (change.label, change.tip, change.ok, change.writes) == (strings.ROWS_CHANGE_VIDEO,
                                                                    strings.ROWS_CHANGE_VIDEO_TIP, True, True)
    rec = _wired(win, monkeypatch, tmp_path)
    win.items.episode_pick(row, ep, change.name, change.payload)
    assert wait_until(lambda: rec.checks, 5)
    assert _links(writer) == [("link_video", [ep.id], {"path": rec.picked})]
    assert rec.started[0][1] == rec.folder


def test_an_episode_not_waiting_on_its_timing_never_offers_it(act):
    from app.services import view_rows
    _seed, win, _writer = act()
    lst = lst_of(win)
    row = next(e[1] for e in lst.model().entries if e[0] == rows.ROW and e[1].episodes)
    plain = view_rows.Status("waiting", "Waiting", "In your top 20: it mines by itself, in turn", "dim")
    in_anki = view_rows.Status("in_anki", "In Anki", "Its cards are in Anki", "ok")
    for st in (plain, in_anki, None):
        ep = row.episodes[0]._replace(status=st, mining=False)
        assert "ep-change-video" not in [e.name for e in win.mine.episode_entries(row, ep)], st


# --- where it opens -------------------------------------------------------------------------------------------- #
def test_read_video_opens_at_the_linked_videos_folder_else_the_items_own_rule(tmp_path, monkeypatch):
    """`own_folder.read_video` on a stand-in opener: its pairing's video's folder; that folder gone, or no pairing,
    `find_how`'s rule for the item (asked with its copy); no store to read: the library's side."""
    from app.connect import library
    folder = tmp_path / "videos"
    folder.mkdir()
    video = str(folder / "Dungeon Meshi S01E08.mkv")
    closed = []

    class Opener:
        mode = "store"

        def handle(self):
            return "the store"

        def close(self):
            closed.append(1)
    pairings = {"pairing": {"video_path": video, "producer": "surasura"}}
    monkeypatch.setattr(library, "pairing_of", lambda store, item_id: pairings["pairing"])
    rules = []
    monkeypatch.setattr(own_folder, "find_how", lambda store, data, ids=(), rels=(), folders=():
                        rules.append((store, ids, rels)) or ("their own folder", None))
    assert own_folder.read_video(Opener(), str(tmp_path), 7, "Library/ダンジョン飯/S01E07.ja.srt") == (str(folder), video)
    assert rules == [] and closed == [1], "its video's folder: nothing else read, the handle closed"
    os.rmdir(folder)
    assert own_folder.read_video(Opener(), str(tmp_path), 7, "Library/ダンジョン飯/S01E07.ja.srt") == \
        ("their own folder", video), "its folder gone: the item's own rule (the video still named: the same is said)"
    pairings["pairing"] = None
    assert own_folder.read_video(Opener(), str(tmp_path), 7) == ("their own folder", None)
    assert rules[-1] == ("the store", (7,), ())
    assert own_folder.read_video(None, str(tmp_path), 7, "Library/a.srt")[1] is None, "no store: no video named"
