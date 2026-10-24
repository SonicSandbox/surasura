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
    assert found == {1: None, 2: None, 3: None}                          # can't tell: never a lasting no (A-2)
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
    assert "found" in third.play_tip and second.looking and not third.looking    # R55-A: not answered is no "not found"
    assert second.play_tip == vr.STRINGS["play_looking"].format(word="video") != third.play_tip
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
    assert b.rows[0] is not a.rows[0], "R55-A: not answered (Looking…) and not found are two shown answers"
    assert b.rows[1] is not a.rows[1] and b.rows[1].can_play
    assert b.finished == a.finished
    c = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}), playable={1: False, 3: True, 4: True})
    assert c.rows[0] is b.rows[0] and c.rows[1] is not b.rows[1], "only the row whose answer moved"
    d = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}), playable={1: False, 3: True, 4: True})
    assert all(x is y for x, y in zip(d.rows, c.rows))


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


# --- fix round 1 (the row 55 reviews: reviews/row55-adversary.md, row55-intent-keeper.md) -------------------------- #
def test_a_video_come_while_a_round_runs_is_found_once_its_folder_is_synced(monkeypatch):
    """A-1: the round lists 02's folder, then 01's video lands there and the watch syncs the folder while the round
    is still running. The sync's re-look must list the folder afresh: answered from the round's old listing, 01 kept
    no ▶ though its click opens the file."""
    monkeypatch.setattr(play, "BATCH", 1)
    rel1, copies = _copy(_name(1, ".ja.srt"))
    rel2, _ = _copy(_name(2, ".ja.srt"))
    video = os.path.join(copies, _name(1, ".mkv"))
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    real = play.look

    def look(language, asks, listings=None, find=None):
        out = real(language, asks, listings, find)
        if 2 in asks and not os.path.exists(video):
            _video(video)                                           # downloaded just after the folder was listed
            looks.again({f"Library/{SHOW}"})                        # the watch's sync of it, the round still running
        return out
    monkeypatch.setattr(play, "look", look)
    looks.want({2: (rel2, "anime"), 1: (rel1, "anime")})
    hand.run()
    assert play.to_open("ja", 1, rel1, "anime")[0] == video
    assert looks.answers() == {2: False, 1: True}


def test_a_new_episode_asked_while_a_round_runs_is_looked_at_with_a_fresh_listing(monkeypatch):
    """A-1: a new item's ask (its subtitle and video just copied into a show folder the round already listed) lands
    while the round runs: its folder is listed again for it, never answered from before its video came."""
    monkeypatch.setattr(play, "BATCH", 1)
    rel1, copies = _copy(_name(1, ".ja.srt"))
    rel3, _ = _copy(_name(3, ".ja.srt"))
    video = os.path.join(copies, _name(3, ".mkv"))
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    real = play.look

    def look(language, asks, listings=None, find=None):
        out = real(language, asks, listings, find)
        if 1 in asks and not os.path.exists(video):
            _video(video)
            looks.want({3: (rel3, "anime")})                        # the build that showed the new episode asks
        return out
    monkeypatch.setattr(play, "look", look)
    looks.want({1: (rel1, "anime")})
    hand.run()
    assert looks.answers() == {1: False, 3: True}


def test_an_episode_whose_record_couldnt_be_read_is_never_kept_as_looked_at(monkeypatch):
    """A-2 / IK-7: the store busy at the look (its record unread) is "can't tell", never a lasting *not found*: it is
    tried once more that round, and its next ask looks again — once the store reads, ▶ shows (the click opens it)."""
    folder = _elsewhere("Downloads", SHOW)
    origin = _subtitle(os.path.join(folder, _name(5, ".ja.srt")), 5)
    video = _video(os.path.join(folder, _name(5, ".mkv")))           # beside the original only
    rel, _copies = _copy(_name(5, ".ja.srt"))
    readable = [False]
    monkeypatch.setattr(play, "_pairings", lambda language, ids: {
        i: ({"producer": "source", "origin": origin} if readable[0] else None) for i in ids})
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({5: (rel, "anime")})
    hand.run()
    assert looks.answers() == {5: False} and looks.looked == 2, "tried once more that round, then left"
    readable[0] = True
    looks.want({5: (rel, "anime")})                                  # the same ask: its row built again
    hand.run()
    assert looks.answers() == {5: True}
    assert play.to_open("ja", 5, rel, "anime")[0] == video


def test_connects_index_saved_between_two_rounds_is_still_noticed(monkeypatch):
    """A-3: Connect saves its index, then a round for another reason (a new episode's ask) runs before Connect's
    feed moves: that round must not take the new index as already seen — the ones not found are looked at again."""
    rel1, _ = _copy(_name(1, ".ja.srt"))
    rel2, _ = _copy(_name(2, ".ja.srt"))
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: (rel1, "anime")})
    hand.run()
    assert looks.answers() == {1: False}
    far = _video(_elsewhere("Videos", SHOW, _name(1, ".mp4")))
    videos.Index("ja").refresh([], [_elsewhere("Videos")])          # Connect saved its index
    looks.want({2: (rel2, "anime")})                                 # a round for another reason
    hand.run()
    looks.index_moved()                                              # Connect's feed moved after
    hand.run()
    assert looks.answers()[1] is True and play.to_open("ja", 1, rel1, "anime")[0] == far


def test_a_synced_folder_looks_at_the_episodes_in_its_subfolders_too(monkeypatch):
    """A-4 / IK-2: the watch reports the outermost folder and the sync takes everything under it: a season's folder
    inside it is looked at again too, a sibling folder that only starts with its name never."""
    calls = _fake_look(monkeypatch, {})
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: ("Library/星降る街/01.srt", "anime"), 2: ("Library/星降る街/Season 2/01.srt", "anime"),
                3: ("Library/星降る街 劇場版/01.srt", "anime")})
    hand.run()
    calls.clear()
    looks.again({"Library/星降る街"})
    hand.run()
    assert [sorted(c) for c in calls] == [[1, 2]]


def _offline(monkeypatch, share):
    """Every look at `share` fails as a share gone offline does (each would wait one network timeout), counted."""
    touched = []

    def wrap(fn, answer):
        def call(path, *a, **k):
            if os.path.normcase(os.path.abspath(os.fspath(path))).startswith(os.path.normcase(share)):
                touched.append((fn.__name__, path))
                if answer is OSError:
                    raise OSError(64, "The specified network name is no longer available")
                return answer
            return fn(path, *a, **k)
        return call
    monkeypatch.setattr(os, "stat", wrap(os.stat, OSError))
    monkeypatch.setattr(os, "listdir", wrap(os.listdir, OSError))
    monkeypatch.setattr(os.path, "isdir", wrap(os.path.isdir, False))
    monkeypatch.setattr(os.path, "exists", wrap(os.path.exists, False))
    return touched


def test_hatos_videos_on_a_share_gone_offline_are_waited_on_once_a_round(monkeypatch):
    """A-5 / IK-8: three episodes paired by hato with videos on a share that went offline, Connect's index holding
    them there too: the share is touched at most twice for the round (a stat, then its folder), never three times an
    episode — the looks' later answers never wait behind one timeout per episode."""
    share = os.path.join(os.environ["SURASURA_TEST_ROOT"], "N", "Media", "Shows", SHOW)
    for n in (1, 2, 3):
        _video(os.path.join(share, _name(n, ".mkv")))
    videos.Index("ja").refresh([], [os.path.dirname(share)])         # listed while the share was there
    copies = {n: _copy(_name(n, ".ja.srt"))[0] for n in (1, 2, 3)}
    monkeypatch.setattr(play, "_pairings", lambda language, ids: {
        i: {"producer": "hato", "video_path": os.path.join(share, _name(i, ".mkv"))} for i in ids})
    touched = _offline(monkeypatch, share)
    assert play.look("ja", {n: (rel, "anime") for n, rel in copies.items()}) == dict.fromkeys((1, 2, 3))
    assert len(touched) <= 2, touched


def test_a_books_parts_on_a_share_gone_offline_are_waited_on_once_a_round(monkeypatch):
    """A-5: three parts of an EPUB whose book sits on a share gone offline: one stat of the book and one of its
    folder for the round, never two an episode."""
    share = os.path.join(os.environ["SURASURA_TEST_ROOT"], "N", "Books")
    book = os.path.join(share, "星の歌.epub")
    monkeypatch.setattr(play, "_pairings", lambda language, ids: {
        i: {"producer": "source", "origin": f"{book}#{i}"} for i in ids})
    touched = _offline(monkeypatch, share)
    asks = {n: (f"Library/星の歌/星の歌 {n:02d}.txt", "book") for n in (1, 2, 3)}
    assert play.look("ja", asks) == dict.fromkeys((1, 2, 3))           # can't tell (A-2)
    assert len(touched) <= 2, touched


def test_closing_stops_a_round_between_batches_and_hands_nothing_on(monkeypatch):
    """A-6 / IK-9: a language switch or the quit closes the looker while a round runs: the round leaves at its next
    batch (no store opened, no share listed for a language gone), and nothing is handed to a reader that stopped."""
    monkeypatch.setattr(play, "BATCH", 1)
    handed = []
    hand = _Hand()
    looks = play.Looks("ja", on_change=handed.append, worker=hand)
    calls = []

    def look(language, asks, listings=None, find=None):
        calls.append(dict(asks))
        looks.close()                                                # closed while this batch was looked at
        return dict.fromkeys(asks, True)
    monkeypatch.setattr(play, "look", look)
    looks.want({i: (f"Library/星降る街/{i:02d}.srt", "anime") for i in (1, 2, 3)})
    hand.run()
    assert len(calls) == 1 and handed == []


def test_a_round_that_fails_lets_the_next_asks_be_looked_at(monkeypatch):
    """IK-9: a round that raised (a fault outside one episode's look) never leaves the looker thinking a round still
    runs: the next ask is looked at."""
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    broken = [True]

    def look(language, asks, listings=None, find=None):
        if broken[0]:
            raise RuntimeError("the disk went away")
        return dict.fromkeys(asks, True)
    monkeypatch.setattr(play, "look", look)
    looks.want({1: ("Library/星降る街/01.srt", "anime")})
    try:
        hand.run()
    except RuntimeError:
        hand.calls.clear()                                           # (`automation.Worker` prints it and goes on)
    broken[0] = False
    looks.want({2: ("Library/星降る街/02.srt", "anime")})
    hand.run()
    assert looks.answers().get(2) is True


def test_a_press_that_found_nothing_looks_at_that_episode_again(monkeypatch):
    """A-7: the click's own lookup found nothing (the video just vanished): that episode is looked at again on the
    looks' worker, so ▶ goes — never offered again for a file the app knows is gone."""
    found = {1: True, 2: True}
    calls = _fake_look(monkeypatch, found)
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: ("Library/星降る街/01.srt", "anime"), 2: ("Library/星降る街/02.srt", "anime")})
    hand.run()
    calls.clear()
    found[1] = False
    looks.recheck([1])
    hand.run()
    assert calls == [{1: ("Library/星降る街/01.srt", "anime")}] and looks.answers() == {1: False, 2: True}


def test_an_answer_landing_after_its_ask_went_is_never_kept_as_looked_at(monkeypatch):
    """A-12: an episode went missing (its ask None) while its look ran, then came back with the same ask: it is
    looked at afresh, as `want` says, never taken as answered by the look that ran before."""
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    calls = []
    ask = ("Library/星降る街/01.srt", "anime")

    def look(language, asks, listings=None, find=None):
        calls.append(dict(asks))
        if len(calls) == 1:
            looks.want({1: None})                                    # gone missing while it was looked at
        return dict.fromkeys(asks, False)
    monkeypatch.setattr(play, "look", look)
    looks.want({1: ask})
    hand.run()
    looks.want({1: ask})                                             # back
    hand.run()
    assert len(calls) == 2


def test_episodes_that_left_current_are_forgotten(monkeypatch):
    """A-8: an item finished or removed leaves Current: its answer is forgotten, and a full sync's re-look of the
    ones not found never looks at it again (S19)."""
    calls = _fake_look(monkeypatch, {})
    hand = _Hand()
    looks = play.Looks("ja", worker=hand)
    looks.want({1: ("Library/星降る街/01.srt", "anime"), 2: ("Library/星降る街/02.srt", "anime")})
    hand.run()
    looks.forget([2])
    calls.clear()
    looks.again()
    hand.run()
    assert [sorted(c) for c in calls] == [[1]] and 2 not in looks.answers()


class _Recorder:
    """A looker that records what the reader tells it."""

    def __init__(self):
        self.on_change = None
        self.wanted, self.agains, self.forgot, self.rechecked, self.moved = [], [], [], [], 0

    def want(self, asks):
        self.wanted.append(dict(asks))

    def again(self, folders=None):
        self.agains.append(None if folders is None else sorted(folders))

    def forget(self, ids):
        self.forgot.append(sorted(ids))

    def recheck(self, ids):
        self.rechecked.append(list(ids))

    def index_moved(self):
        self.moved += 1

    def seed(self, found):
        pass

    def answers(self):
        return {}

    def close(self):
        pass


def test_the_reader_tells_the_looker_which_episodes_left_current():
    """A-8: through the reader — a build without a row hands its episodes to `forget`."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})])
    rec = _Recorder()
    reader = library_reader.LibraryReader(None, play=rec)
    reader._ask_play(vr.build(items, WORKS, {"mine_line": 20}))
    left = {k: v for k, v in items.items() if v["work_id"] == 1}
    reader._ask_play(vr.build(left, WORKS, {"mine_line": 20}))
    assert rec.forgot == [[3, 4]]


def test_the_readers_sync_looks_again_at_the_folders_it_synced(monkeypatch):
    """A-10: the wiring — a watch's sync re-looks its folders' episodes, a full sync the ones not found."""
    from app import library_store

    class _Opener:
        def handle(self):
            return object()
    monkeypatch.setattr(library_store, "sync_for_window", lambda store, folders=None: None)
    rec = _Recorder()
    reader = library_reader.LibraryReader(_Opener(), play=rec)
    reader._owed = ({"Library/星降る街"}, False, False)
    reader._sync()
    reader._owed = (set(), True, False)
    reader._sync()
    assert rec.agains == [["Library/星降る街"], None]


def test_a_new_connect_feed_asks_whether_its_index_moved():
    """A-10: the wiring — a build with another Connect feed than the last asks the looker to check Connect's index;
    the same feed never does."""
    from tests.test_view_rows import _feed
    seed = window_seed.build()
    feeds = [_feed([])]
    rec = _Recorder()
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02, play=rec, connect=lambda: feeds[0])
    views = []
    reader.subscribe(views.append)
    reader.start()
    try:
        end = time.monotonic() + 10
        while not (views and views[-1].state == "full") and time.monotonic() < end:
            time.sleep(0.02)
        first = rec.moved
        reader.refresh()
        time.sleep(0.2)
        assert rec.moved == first, "the same feed: nothing asked"
        feeds[0] = _feed([])
        end = time.monotonic() + 10
        while rec.moved == first and time.monotonic() < end:
            time.sleep(0.02)
        assert rec.moved == first + 1
    finally:
        reader.stop()


def test_connects_no_video_hides_play_only_where_play_would_open_a_video():
    """IK-3: Connect's lookup is a video's: its *No video* on a podcast's episode says nothing of the audio ▶ opens —
    the episode is still asked, and ▶ shows when its audio is found."""
    from app.connect import runner
    from tests.test_view_rows import _feed, _job
    work(5, "ゆるっと日本語ラジオ", media="podcast")
    items = items_of([("now", 5, 1, ["ゆるっと日本語ラジオ 第12回.srt"], {}),
                      ("now", 1, 2, eps("星降る街の小さな工房", 1, 1), {})])
    connect = _feed([_job(1, reason=runner.NO_VIDEO), _job(2, reason=runner.NO_VIDEO)])
    view = vr.build(items, WORKS, {"mine_line": 20}, connect=connect, playable={1: True, 2: True})
    by_id = {e.id: e for r in view.rows for e in r.episodes}
    assert by_id[1].ask is not None and by_id[1].can_play, "a podcast's audio: Connect's video lookup says nothing"
    assert by_id[2].ask is None and not by_id[2].can_play, "an anime's video: Connect and ▶ agree"


# --- R55-A: Up Next says *Looking…* until the check has answered ---------------------------------------------------- #
def test_an_episode_not_answered_yet_is_looking_never_not_found():
    """R55-A (Sonic): before the video check answers, Up Next reads a muted *Looking…*, never *No video*: the view
    tells an episode not answered yet (`looking`, a neutral tip — A-11) from one not found; without a looker, or once
    answered, nothing is looking."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 3), {}),
                      ("now", 4, 2, ["朝ごはんの作り方.srt"], {0: {"source_type": "youtube"}})])
    view = vr.build(items, WORKS, {"mine_line": 20}, playable={1: False, 2: True})
    by_id = {e.id: e for r in view.rows for e in r.episodes}
    assert (by_id[1].looking, by_id[1].can_play) == (False, False)              # looked: not found
    assert (by_id[2].looking, by_id[2].can_play) == (False, True)
    assert (by_id[3].looking, by_id[3].can_play) == (True, False)               # not answered yet
    assert by_id[3].play_tip == vr.STRINGS["play_looking"].format(word="video")
    assert by_id[3].play_tip != by_id[1].play_tip
    assert not by_id[4].looking, "online: nothing to look for"
    assert not any(e.looking for r in vr.build(items, WORKS, {"mine_line": 20}).rows for e in r.episodes)


def test_an_answer_landing_rebuilds_the_row_that_was_looking():
    """R55-A: *Looking…* → *No video* is a change the learner sees: the row whose episode was answered not found is
    rebuilt (the others stay the same objects)."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {}),
                      ("now", 2, 2, eps("雲の上の郵便屋さん", 1, 2), {})])
    cache = vr.RowCache()
    a = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}), playable={3: True, 4: True})
    b = vr.build(items, WORKS, {"mine_line": 20}, cache=cache, numbers=(1, {}),
                 playable={1: False, 2: False, 3: True, 4: True})
    assert a.rows[0].episodes[0].looking and not b.rows[0].episodes[0].looking
    assert b.rows[0] is not a.rows[0] and b.rows[1] is a.rows[1]


def test_the_first_screens_cache_never_seeds_an_episode_that_was_still_looking():
    """R55-A: a cache written while an episode was still being looked for seeds no answer for it — the next session
    says *Looking…* until it is looked at, never a *No video* nothing found."""
    items = items_of([("now", 1, 1, eps("星降る街の小さな工房", 1, 2), {})])
    view = vr.build(items, WORKS, {"mine_line": 20}, playable={1: True})
    looks = play.Looks("ja", worker=_Hand())
    reader = library_reader.LibraryReader(None, play=looks)
    reader._seed_play(view)
    assert looks.answers() == {1: True}
