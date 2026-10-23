"""Row 55 (laptop try, Sonic: "if it doesn't find the media, there shouldn't be a play button as it would be missing"):
▶ shows only where the file it would open is found — by ▶'s own lookup (`play._find`, Connect's rules), asked of many
episodes at once (`play.look`), each episode's answer kept by `play.Looks` on a worker of its own, read by the view
(`view_rows.build(playable=)`) through the reader (`LibraryReader(play=)`). Qt-free: a real store with a source folder
read in place, real Japanese subtitles and an EPUB from tests/Test Resources, made-up show names, video stand-ins
(never played: nothing here opens a file).

What a wrong answer would cost a learner:
  * a ▶ that opens nothing (the row-55 complaint), or none on an episode whose video sits beside its original;
  * ▶ and the row's *No video* saying opposite things;
  * a share offline that makes the looks wait once per episode, or makes the window wait at all;
  * every refresh looking at the disk again (S19), every row redrawn when one answer moved, ▶ flashing out and in.
"""
import os
import threading
import time

import pytest

from app import sources
from app.connect import videos
from app.services import library_reader, play, view_rows as vr
from tests.fixtures import window_seed
from tests.test_services_play import SHOW, _copy, _elsewhere, _name, _read_in_place, _subtitle, _video
from tests.test_sources_scan import _chapters, _epub
from tests.test_view_rows import WORKS, eps, items_of, work


@pytest.fixture(autouse=True)
def _fresh():
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    WORKS.clear()
    work(1, "星降る街の小さな工房")
    work(2, "雲の上の郵便屋さん")
    work(4, "Tsubasa no Kitchen", media="youtube", channel="Tsubasa no Kitchen")
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


class _Hand:
    """A worker run by hand (`automation.Worker`'s shape): a test says when the looks run."""

    def __init__(self):
        self.calls = []

    def put(self, call, *args):
        self.calls.append((call, args))
        return True

    def run(self):
        while self.calls:
            call, args = self.calls.pop(0)
            call(*args)

    def idle(self, timeout=None):
        self.run()
        return True

    def close(self):
        pass


def _fake_look(monkeypatch, found):
    """`play.look` answering from `found` ({item_id: bool}, read at each call), every call recorded."""
    calls = []

    def look(language, asks, listings=None, find=None):
        calls.append(dict(asks))
        return {i: bool(found.get(i)) for i in asks}
    monkeypatch.setattr(play, "look", look)
    return calls


# --- the one lookup, asked of many --------------------------------------------------------------------------------- #
def test_look_answers_as_the_click_opens_for_every_way_a_file_is_found(monkeypatch):
    """Beside its original (a folder read in place), beside the copy (a 2.x file, no record), the video hato's pairing
    names, one only Connect's index knows, and none: `look` says found exactly where `to_open` opens a file — one
    rule, two callers."""
    folder = _elsewhere("Downloads", SHOW)
    subs = {n: _subtitle(os.path.join(folder, _name(n, ".ja.srt")), n) for n in (9, 10)}
    _video(os.path.join(folder, _name(9, ".mkv")))                       # beside the original only
    items = _read_in_place(folder)
    beside_origin, nothing = items[os.path.abspath(subs[9])], items[os.path.abspath(subs[10])]
    rel_copy, copies = _copy(_name(11, ".ja.srt"))
    _video(os.path.join(copies, _name(11, ".mkv")))                      # beside the copy
    rel_indexed, _ = _copy(_name(12, ".ja.srt"))
    _video(_elsewhere("Videos", SHOW, _name(12, ".mp4")))
    videos.Index("ja").refresh([], [_elsewhere("Videos")])              # Connect's own refresh, saved
    rel_paired, _ = _copy(_name(13, ".ja.srt"))
    paired = _video(_elsewhere("hato", "第13話.mkv"))
    real = play._pairings
    monkeypatch.setattr(play, "_pairings", lambda language, ids: {
        **real(language, ids), **({9013: {"producer": "hato", "video_path": paired}} if 9013 in ids else {})})
    asks = {beside_origin[0]: (beside_origin[1], "anime"), nothing[0]: (nothing[1], "anime"),
            9011: (rel_copy, "anime"), 9012: (rel_indexed, "anime"), 9013: (rel_paired, "anime")}
    found = play.look("ja", asks)
    assert found == {beside_origin[0]: True, nothing[0]: False, 9011: True, 9012: True, 9013: True}
    for item_id, (rel, media) in asks.items():
        assert found[item_id] == (play.to_open("ja", item_id, rel, media)[0] is not None)


def test_a_book_read_in_place_is_found():
    """A part of an EPUB a folder holds: ▶ opens the book itself, so ▶ shows."""
    book = _epub(_elsewhere("Books", "星の歌.epub"), _chapters())
    items = _read_in_place(_elsewhere("Books"))
    item_id, rel = items[os.path.abspath(book) + "#2"]
    assert play.look("ja", {item_id: (rel, "book")}) == {item_id: True}


def test_a_share_offline_is_listed_once_a_round_never_once_an_episode(monkeypatch):
    """Three episodes whose originals sit on a share gone offline: one listing of it for the round (`runner.beside`
    remembers the folder it couldn't list), all three not found — never three waits on the network's timeout."""
    share = os.path.join(os.environ["SURASURA_TEST_ROOT"], "N", "Media", "Shows", SHOW)
    copies = {n: _copy(_name(n, ".ja.srt"))[0] for n in (1, 2, 3)}
    monkeypatch.setattr(play, "_pairings", lambda language, ids: {
        i: {"producer": "source", "origin": os.path.join(share, _name(i, ".ja.srt"))} for i in ids})
    listed, real = [], os.listdir

    def offline(folder):
        listed.append(folder)
        if folder == share:
            raise OSError(64, "The specified network name is no longer available")
        return real(folder)
    monkeypatch.setattr(os, "listdir", offline)
    found = play.look("ja", {n: (rel, "anime") for n, rel in copies.items()})
    assert found == {1: False, 2: False, 3: False}
    assert listed.count(share) == 1 and len(listed) == 2                 # the copies' folder once, the share once


def test_the_window_never_waits_on_a_look_however_long_it_takes(monkeypatch):
    """`want` hands the asks to the looks' own worker and returns: a share holding the look for seconds holds no
    caller (the reader's thread asks, the window's never does)."""
    gate = threading.Event()

    def slow(language, asks, listings=None, find=None):
        gate.wait(5)
        return dict.fromkeys(asks, False)
    monkeypatch.setattr(play, "look", slow)
    looks = play.Looks("ja")
    try:
        t0 = time.monotonic()
        looks.want({1: ("Library/月影の旅人/a.srt", "anime")})
        assert time.monotonic() - t0 < 0.2
    finally:
        gate.set()
        looks.idle(5)
        looks.close()


# --- each answer kept, looked at again only when it may have changed (S19) ---------------------------------------- #
def test_an_answer_is_looked_for_once_and_the_same_ask_never_again(monkeypatch):
    calls = _fake_look(monkeypatch, {1: True})
    handed = []
    hand = _Hand()
    looks = play.Looks("ja", on_change=handed.append, worker=hand)
    asks = {1: ("Library/星降る街/01.srt", "anime"), 2: ("Library/星降る街/02.srt", "anime")}
    looks.want(asks)
    hand.run()
    assert handed == [{1: True, 2: False}] and len(calls) == 1
    looks.want(dict(asks))                                               # a row rebuilt for another reason
    hand.run()
    assert len(calls) == 1 and len(handed) == 1, "the same ask: nothing looked at, nothing handed on"


def test_a_changed_ask_or_one_back_from_missing_is_looked_at_again(monkeypatch):
    calls = _fake_look(monkeypatch, {1: True})
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: ("Library/星降る街/01.srt", "anime")})
    hand.run()
    looks.want({1: ("Library/星降る街 2/01.srt", "anime")})              # its file moved
    hand.run()
    looks.want({1: None})                                                # gone missing: never asked
    hand.run()
    looks.want({1: ("Library/星降る街 2/01.srt", "anime")})              # back: looked at afresh
    hand.run()
    assert [list(c.values())[0][0] for c in calls] == ["Library/星降る街/01.srt", "Library/星降る街 2/01.srt",
                                                       "Library/星降る街 2/01.srt"]


def test_a_synced_folder_looks_at_its_episodes_and_a_full_sync_at_the_ones_not_found(monkeypatch):
    found = {1: True}
    calls = _fake_look(monkeypatch, found)
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: ("Library/星降る街/01.srt", "anime"), 2: ("Library/星降る街/02.srt", "anime"),
                3: ("Library/雲の上/01.srt", "anime")})
    hand.run()
    calls.clear()
    looks.again({"library/星降る街"})                                    # the watch's folder, any case
    hand.run()
    assert [sorted(c) for c in calls] == [[1, 2]]
    calls.clear()
    looks.again()                                                        # a full sync, a source folder's look
    hand.run()
    assert [sorted(c) for c in calls] == [[2, 3]], "only the ones not found"


def test_connects_index_saved_anew_looks_again_at_the_ones_not_found_only_then(monkeypatch):
    calls = _fake_look(monkeypatch, {1: True})
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: ("Library/星降る街/01.srt", "anime"), 2: ("Library/星降る街/02.srt", "anime")})
    hand.run()
    calls.clear()
    looks.index_moved()                                                  # Connect's feed moved, its index didn't
    hand.run()
    assert calls == []
    _video(_elsewhere("Videos", SHOW, _name(2, ".mp4")))
    videos.Index("ja").refresh([], [_elsewhere("Videos")])              # Connect saved its index
    looks.index_moved()
    hand.run()
    assert [sorted(c) for c in calls] == [[2]]


def test_an_answer_stays_until_its_new_one_lands_and_a_seed_until_the_first(monkeypatch):
    """▶ never goes and comes back: the first screen's answers (the cache's) and a re-look's old answer are shown
    until the look answers."""
    found = {1: True, 2: True}
    _fake_look(monkeypatch, found)
    handed = []
    hand = _Hand()
    looks = play.Looks("ja", on_change=handed.append, worker=hand)
    looks.seed({1: True, 2: False})
    looks.want({1: ("Library/a/01.srt", "anime"), 2: ("Library/a/02.srt", "anime")})
    assert looks.answers() == {1: True, 2: False}                        # asked, not looked at yet: the seed
    hand.run()
    assert looks.answers() == {1: True, 2: True} and handed == [{1: True, 2: True}]
    found[1] = False
    looks.again({"Library/a"})
    assert looks.answers()[1] is True                                    # owed: the old answer stays
    hand.run()
    assert looks.answers()[1] is False


def test_answers_land_batch_by_batch_in_the_order_asked(monkeypatch):
    calls = _fake_look(monkeypatch, {i: True for i in range(1, 6)})
    monkeypatch.setattr(play, "BATCH", 2)
    handed = []
    hand = _Hand()
    looks = play.Looks("ja", on_change=handed.append, worker=hand)
    looks.want({i: (f"Library/a/{i:02d}.srt", "anime") for i in (5, 1, 4, 2, 3)})
    hand.run()
    assert [list(c) for c in calls] == [[5, 1], [4, 2], [3]]
    assert [sorted(h) for h in handed] == [[1, 5], [1, 2, 4, 5], [1, 2, 3, 4, 5]]


# --- the view reads the answers ------------------------------------------------------------------------------------ #
def test_the_view_shows_play_only_where_the_lookup_found_the_file():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {})])
    plain = vr.build(items, WORKS, {"mine_line": 20})
    assert [e.can_play for e in plain.rows[0].episodes] == [True, True, True], "no looker: as before"
    view = vr.build(items, WORKS, {"mine_line": 20}, playable={1: True, 3: False})
    first, second, third = view.rows[0].episodes
    assert (first.can_play, second.can_play, third.can_play) == (True, False, False)    # 2: not answered yet
    assert first.ask == ("HighPriority/星降る街の小さな工房 - 01.srt", "anime")
    assert "found" in third.play_tip and third.play_tip == second.play_tip
    assert view.rows[0].can_play is True                                # the row's ▶: its next episode's


def test_never_asked_where_play_cant_be_and_connects_no_video_wins():
    from app.connect import runner
    from tests.test_view_rows import _feed, _job
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 4), {1: {"availability": "missing"},
                                                                 2: {"availability": "waiting"}}),
                      ("now", 4, 2, ["朝ごはんの作り方.srt"], {0: {"source_type": "youtube"}})])
    connect = _feed([_job(4, reason=runner.NO_VIDEO)])
    view = vr.build(items, WORKS, {"mine_line": 20}, connect=connect, playable=dict.fromkeys(range(1, 6), True))
    by_id = {e.id: e for r in view.rows for e in r.episodes}
    assert by_id[1].ask is not None and by_id[1].can_play
    for i in (2, 3, 4, 5):                                               # missing, waiting, Connect's No video, online
        assert by_id[i].ask is None and not by_id[i].can_play, i
    assert by_id[4].status.kind == "no_media"                           # the status and ▶ say the same


def test_new_answers_rebuild_only_the_rows_whose_shown_answer_moved():
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {}),
                      ("graduated", 2, 3, eps("雲の上の郵便屋さん", 3, 3), {})])
    cache = vr.RowCache()
    a = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}), playable={})
    b = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}), playable={1: False, 3: True})
    assert b.rows[0] is a.rows[0], "not found reads as not answered: the same row"
    assert b.rows[1] is not a.rows[1] and b.rows[1].can_play
    assert b.finished == a.finished
    c = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}), playable={1: False, 3: True})
    assert all(x is y for x, y in zip(c.rows, b.rows))


# --- the reader: asks once, hands back, a quiet refresh looks at nothing ------------------------------------------- #
def test_the_reader_asks_once_shows_the_answers_and_a_quiet_refresh_looks_at_nothing(monkeypatch):
    seed = window_seed.build()
    first = vr.build({r["id"]: r for r in seed.items}, {w["id"]: w for w in seed.works}, {"mine_line": 20})
    asked = [e.id for r in first.rows for e in r.episodes if e.ask is not None]
    lucky = set(asked[::3])                                              # every third episode's video is found
    calls = _fake_look(monkeypatch, {i: True for i in lucky})
    looks = play.Looks(seed.language)
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02, play=looks)
    views = []
    reader.subscribe(views.append)
    reader.start()
    try:
        def shown():
            return views and {e.id for r in views[-1].rows for e in r.episodes if e.can_play} == lucky
        end = time.monotonic() + 10
        while not shown() and time.monotonic() < end:
            time.sleep(0.02)
        assert shown()
        assert sorted(i for c in calls for i in c) == sorted(asked), "each episode looked at once"
        before = next(v for v in views if v.state == "full")
        after = views[-1]
        unmoved = [r.key for r in before.rows if not any(e.id in lucky for e in r.episodes)]
        olds, news = {r.key: r for r in before.rows}, {r.key: r for r in after.rows}
        assert unmoved and all(news[k] is olds[k] for k in unmoved), "rows with no ▶ found: the same objects"
        n = len(calls)
        for _ in range(3):
            reader.refresh()
            time.sleep(0.1)
        looks.idle(5)
        assert len(calls) == n, "a refresh with nothing changed looks at nothing"
    finally:
        reader.stop()
    assert looks._worker._closed, "the reader's stop ends the looks' worker"


def test_the_first_screens_cache_seeds_the_answers(tmp_path, monkeypatch):
    seed = window_seed.build()
    first = vr.build({r["id"]: r for r in seed.items}, {w["id"]: w for w in seed.works}, {"mine_line": 20})
    asked = [e.id for r in first.rows for e in r.episodes if e.ask is not None]
    _fake_look(monkeypatch, dict.fromkeys(asked, True))
    cache = str(tmp_path / "window_cache_ja.json")
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02, cache_file=cache, play=play.Looks("ja"))
    views = []
    reader.subscribe(views.append)
    reader.start()
    end = time.monotonic() + 10
    while not (views and any(e.can_play for r in views[-1].rows for e in r.episodes)) and time.monotonic() < end:
        time.sleep(0.02)
    reader.stop()                                                        # the last view's cache written as it stops
    assert os.path.exists(cache)
    hand = _Hand()                                                       # its looks never run: only the seed
    again = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                         mining=seed.mining, cache_file=cache, play=play.Looks("ja", worker=hand))
    again._first_screen()
    shown = {e.id for r in again.view().rows for e in r.episodes if e.can_play}
    assert shown and again._playable == {e.id: e.can_play for r in again.view().rows for e in r.episodes}
