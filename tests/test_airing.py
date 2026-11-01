"""AniList's airing status for the finish (3.0.1 item 5): `app/services/airing.py`, asked through the covers fetcher
(`covers_online.Fetcher.airing`) and handed its shows by the library reader — spec: the planning folder's
`tracks/books/work/airing/SPEC.md` (A1–A8 PROVISIONAL; AA-1: the *Download covers* switch).

What a wrong answer would cost a learner:
  * a show finishing by itself SOONER than 3.0 would — AniList's "finished" releasing a show its files' dates hold back,
    or season 1's id on a two-season folder (the spec's F1: AniList only ever holds a show back);
  * an AniList id sent while they never turned *Download covers* on, a title or file name sent at all, or ids for
    shows in Goal, Finished, New arrivals or far from their end (a privacy break: CLAUDE.md §1);
  * AniList's limit broken (covers and airing together over 30 a minute: a one-minute block);
  * offline, refused or timed out: an answer lost, a dialog, or a retry storm;
  * *Remove downloaded covers* leaving AniList's answers behind.

The network is blocked as in `test_covers_online` (its `blocked` guard, its fake AniList on 127.0.0.1: answers in the
API's shape, hand-written here). No live AniList call. Show names are the suite's own made-up Japanese titles.
"""
import json
import os
import threading
import time

import pytest

from app import __version__
from app.services import airing as A
from app.services import covers_online as O
from app.services import library_reader, view_rows
from tests.fixtures import window_seed
from tests.test_covers_online import AniList, Clock, Pen, blocked, fetcher  # noqa: F401 (blocked: autouse guard)

NOW = 1_800_000_000.0                               # a fixed wall clock (2027-01-15)
DAY = 24 * 3600


@pytest.fixture
def anilist():
    fake = AniList()
    yield fake
    fake.close()


def _media(fake, id_, status, episodes=None, next_at=None, next_ep=None):
    """A show in the fake AniList as `Q_AIRING` reads it (the API's field names)."""
    fake.media[id_] = {"id": id_, "status": status, "episodes": episodes,
                       "nextAiringEpisode": None if next_at is None else {"episode": next_ep, "airingAt": next_at},
                       "coverImage": {"extraLarge": f"{fake.base}/img/{id_}.jpg", "large": None}}


def _ep(number, watched=True, **kw):
    blank = view_rows.Episode._make([None] * len(view_rows.Episode._fields))
    return blank._replace(id=number or 0, number=number, watched=watched, **kw)


def _row(work_id, eps, group=False):
    return view_rows.Row._make([None] * len(view_rows.Row._fields))._replace(
        key=f"w{work_id}", work_id=work_id, episodes=tuple(eps), group=group)


def _airing(f, tmp_path, clock=None):
    """The fetcher's own airing asker, its cache in the test's folder and on a wall clock of the test's."""
    a = f.airing
    a.path = str(tmp_path / "airing_ja.json")
    a.clock = clock or (lambda: NOW)
    return a


def _queries(fake):
    return [b for b, _h in fake.posts if b["query"] == A.Q_AIRING]


# --- the id (A8) ---------------------------------------------------------------------------------------------------- #
def test_the_id_is_the_work_s_anilist_id_else_its_anilist_cover_s_ref_and_nothing_else():
    assert A.airing_id({"anilist_id": 154587, "cover_source": "anilist", "cover_ref": "99"}) == 154587
    assert A.airing_id({"anilist_id": None, "cover_source": "anilist", "cover_ref": "154587"}) == 154587, \
        "a cover found by search, or picked from AniList, keeps its id as the ref"
    assert A.airing_id({"anilist_id": None, "cover_source": "tmdb", "cover_ref": "154587"}) is None
    assert A.airing_id({"anilist_id": None, "cover_source": "youtube", "cover_ref": "dQw4w9WgXcQ"}) is None
    assert A.airing_id({"anilist_id": None, "cover_source": "anilist", "cover_ref": "１２３"}) is None, "full-width"
    assert A.airing_id({"anilist_id": True}) is None and A.airing_id({"anilist_id": 0}) is None
    assert A.airing_id({"anilist_id": "21"}) == 21
    assert A.airing_id(None) is None and A.airing_id({}) is None


# --- AniList only holds a show back (A5) ---------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", A.AIRING)
def test_an_airing_status_holds_the_show_whatever_its_files(status):
    eps = [_ep(n) for n in range(1, 13)]
    assert A.holds({"status": status, "episodes": 12}, eps) == "airing"
    assert A.holds({"status": status, "episodes": None}, eps) == "airing", "no count yet: still held"


@pytest.mark.parametrize("status", ["FINISHED", "CANCELLED", "unknown", "SOME_NEW_STATUS"])
def test_an_ended_or_unknown_status_with_every_episode_never_says_anything(status):
    """F1: AniList's "finished" never releases a show — None leaves the files' dates to decide, as 3.0."""
    eps = [_ep(n) for n in range(1, 13)]
    assert A.holds({"status": status, "episodes": 12}, eps) is None
    assert A.holds({"status": status, "episodes": 10}, eps) is None, "more files than AniList lists"


@pytest.mark.parametrize("status", ["FINISHED", "CANCELLED", "unknown"])
def test_fewer_files_than_anilist_lists_holds_the_show_as_more_to_come(status):
    assert A.holds({"status": status, "episodes": 28}, [_ep(n) for n in range(1, 25)]) == "more"


def test_nothing_kept_or_a_hand_edited_entry_holds_nothing():
    eps = [_ep(1), _ep(2)]
    assert A.holds(None, eps) is None and A.holds("RELEASING", eps) is None
    assert A.holds({"status": "FINISHED", "episodes": "28"}, eps) is None, "a count that isn't a number"
    assert A.holds({"status": "FINISHED", "episodes": True}, eps) is None


def test_episodes_short_reads_the_highest_numbered_file_only():
    assert view_rows.episodes_short([_ep(1), _ep(2), _ep(24)], 28)
    assert not view_rows.episodes_short([_ep(13), _ep(24)], 12), "season 2's numbers above season 1's count"
    assert not view_rows.episodes_short([_ep(34)], 34), "absolute numbering at the count"
    assert not view_rows.episodes_short([_ep(None), _ep(None)], 12), "no numbered file: never short"
    assert not view_rows.episodes_short([_ep(1)], None) and not view_rows.episodes_short([_ep(1)], 0)
    assert not view_rows.episodes_short([], 12)


# --- when an answer is asked again (A2) ----------------------------------------------------------------------------- #
def test_due_none_kept_or_no_time_is_asked():
    assert A.due(None, NOW) and A.due({"status": "RELEASING"}, NOW)
    assert A.due({"status": "FINISHED", "asked_at": NOW + 60}, NOW), "a time ahead of the clock tells nothing"


def test_due_an_airing_show_after_a_day_or_once_its_next_episode_has_aired():
    e = {"status": "RELEASING", "asked_at": NOW - 23 * 3600, "next_at": NOW + DAY}
    assert not A.due(e, NOW)
    assert A.due(dict(e, asked_at=NOW - DAY - 1), NOW)
    aired = {"status": "RELEASING", "asked_at": NOW - 5 * 3600, "next_at": NOW - 2 * 3600}
    assert A.due(aired, NOW), "its next episode aired over an hour ago: asked again"
    assert not A.due(dict(aired, next_at=NOW - 30 * 60), NOW), "aired half an hour ago: AniList may not know yet"
    assert not A.due(dict(aired, asked_at=NOW - 30 * 60), NOW), "asked after that air time: a day's wait"


def test_due_an_ended_show_after_thirty_days_and_an_unknown_one_after_seven():
    assert not A.due({"status": "FINISHED", "asked_at": NOW - 29 * DAY}, NOW)
    assert A.due({"status": "CANCELLED", "asked_at": NOW - 31 * DAY}, NOW)
    assert not A.due({"status": "unknown", "asked_at": NOW - 6 * DAY}, NOW)
    assert A.due({"status": "unknown", "asked_at": NOW - 8 * DAY}, NOW)


# --- who is asked (A1) ---------------------------------------------------------------------------------------------- #
def test_only_current_rows_with_an_id_and_at_most_one_file_left_are_near_their_end():
    works = {1: {"anilist_id": 501}, 2: {"anilist_id": 502}, 3: {"anilist_id": None}, 4: {"anilist_id": 504},
             5: {"cover_source": "anilist", "cover_ref": "505"}, 6: {"anilist_id": 506}}
    heard = _ep(None, watched=False, waiting=True, text="audio", rel_path="星の旅人/第1巻.m4b")
    rows = [_row(1, [_ep(1), _ep(2), _ep(3, watched=False)]),                     # one left: asked
            _row(2, [_ep(1), _ep(2, watched=False), _ep(3, watched=False)]),      # two left: far from its end
            _row(3, [_ep(1, watched=False)]),                                     # no id
            _row(4, [_ep(1), _ep(2)], group=True),                                # a group
            _row(5, [_ep(1), _ep(2, watched=False), heard]),                      # its audiobook item never counts
            _row(1, [_ep(4, watched=False)]),                                     # a second part: once
            _row(6, [])]
    assert A.near_end(rows, works) == [501, 505]


def test_the_view_s_airing_map_is_built_for_current_s_rows_by_work():
    works = {1: {"anilist_id": 501}, 2: {"anilist_id": 502}, 3: {}}
    shows = {"501": {"status": "RELEASING"}, "999": {"status": "FINISHED"}, "502": "junk"}
    rows = [_row(1, [_ep(1)]), _row(2, [_ep(1)]), _row(3, [_ep(1)]), _row(None, [])]
    assert A.of_rows(rows, works, shows) == {1: {"status": "RELEASING"}}
    assert A.of_rows(rows, works, {}) == {}


# --- the cache (A4) ------------------------------------------------------------------------------------------------- #
def test_the_cache_is_written_whole_and_an_unreadable_one_reads_empty(tmp_path):
    path = str(tmp_path / "airing_ja.json")
    assert A.read(path) == {}
    assert A._write(path, {"501": {"status": "RELEASING", "episodes": 12, "next_at": None, "asked_at": NOW}})
    assert not os.path.exists(path + ".tmp")
    assert json.load(open(path, encoding="utf-8"))["v"] == 1
    assert A.read(path)["501"]["status"] == "RELEASING"
    for bad in ("{not json", json.dumps({"v": 2, "shows": {"1": {}}}), json.dumps([1, 2]),
                json.dumps({"v": 1, "shows": {"1": "x", "2": {"status": "FINISHED"}}})):
        open(path, "w", encoding="utf-8").write(bad)
        assert A.read(path) in ({}, {"2": {"status": "FINISHED"}})


def test_the_reader_s_copy_reads_the_file_again_only_when_it_moved(tmp_path):
    path = str(tmp_path / "airing_ja.json")
    kept = A.Kept("ja", path)
    assert kept.shows() == {}
    A._write(path, {"501": {"status": "RELEASING"}})
    first = kept.shows()
    assert first == {"501": {"status": "RELEASING"}} and kept.shows() is first, "unchanged: the same dict"
    A._write(path, {"501": {"status": "FINISHED", "episodes": 13}})
    os.utime(path, ns=(time.time_ns(), os.stat(path).st_mtime_ns + 10_000_000))
    assert kept.shows()["501"]["status"] == "FINISHED"
    os.remove(path)
    assert kept.shows() == {}


# --- what is sent (the covers' own request, its switch and its throttle) ------------------------------------------- #
def test_only_the_ids_and_the_query_are_sent_with_the_covers_headers(anilist, tmp_path):
    _media(anilist, 501, "RELEASING", 12, next_at=int(NOW + 3 * DAY), next_ep=9)
    _media(anilist, 502, "FINISHED", 24)
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path)
    assert a.want([501, 502, 503]) == 3 and a.run_once() == 3
    (body, headers), = anilist.posts
    assert body == {"query": A.Q_AIRING, "variables": {"ids": [501, 502, 503]}}
    assert headers["User-Agent"] == f"Surasura/{__version__}"
    assert "Referer" not in headers and "Cookie" not in headers
    shows = A.read(a.path)
    assert shows["501"] == {"status": "RELEASING", "episodes": 12, "next_at": int(NOW + 3 * DAY), "asked_at": NOW}
    assert shows["502"]["status"] == "FINISHED" and shows["502"]["next_at"] is None
    assert shows["503"] == {"status": "unknown", "episodes": None, "next_at": None, "asked_at": NOW}, \
        "AniList has no row for it (deleted, merged): unknown, asked again in a week"


def test_with_the_switch_off_nothing_is_sent_and_nothing_queued(anilist, tmp_path):
    f = fetcher(Pen(), anilist, on=False)
    a = _airing(f, tmp_path)
    assert a.want([501]) == 0 and a.run_once() == 0
    f.switch["covers_download"] = True
    assert a.want([501]) == 1
    f.switch["covers_download"] = False             # turned off before the thread's turn: nothing leaves
    assert a.run_once() == 0
    assert anilist.posts == [] and not os.path.exists(a.path)


def test_the_switch_off_by_default_sends_nothing_to_the_real_anilist(tmp_path):
    f = O.Fetcher("ja", Pen(), background=False)
    f.airing.path = str(tmp_path / "airing_ja.json")
    assert f.airing.want([501]) == 0 and f.airing.run_once() == 0


def test_a_kept_answer_that_isn_t_due_is_never_asked_again(anilist, tmp_path):
    _media(anilist, 501, "FINISHED", 12)
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path)
    a.want([501]) and a.run_once()
    assert a.want([501]) == 0 and a.run_once() == 0 and len(anilist.posts) == 1
    a.clock = lambda: NOW + 31 * DAY
    assert a.want([501]) == 1 and a.run_once() == 1 and len(anilist.posts) == 2


def test_fifty_ids_a_query(anilist, tmp_path):
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path)
    ids = list(range(1000, 1120))
    assert a.want(ids) == 120 and a.run_once() == 120
    assert [len(b["variables"]["ids"]) for b in _queries(anilist)] == [50, 50, 20]
    assert len(A.read(a.path)) == 120


def test_only_the_ids_asked_are_touched_in_the_cache(anilist, tmp_path):
    _media(anilist, 502, "RELEASING", 12)
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path)
    old = {"status": "FINISHED", "episodes": 12, "next_at": None, "asked_at": NOW - DAY}
    A._write(a.path, {"501": old})
    a.want([502]) and a.run_once()
    shows = A.read(a.path)
    assert shows["501"] == old and shows["502"]["status"] == "RELEASING"


def test_covers_and_airing_together_stay_within_thirty_a_minute(anilist, tmp_path):
    """One AniList budget (A3): every request goes through the fetcher's own `_post`, so through its one throttle."""
    clock = Clock()
    at = []
    anilist.after_post = lambda: at.append(clock.now)
    for k in range(20):
        anilist.add(9000 + k, f"Hoshikuzu Station {k}", search=f"Hoshikuzu Station {k}")
    f = fetcher(Pen(), anilist, clock=clock, sleep=clock.sleep)
    a = _airing(f, tmp_path, clock=lambda: NOW)
    for k in range(20):                             # 20 title searches and 20 airing queries, interleaved
        f.want([O.Want(k + 1, f"Hoshikuzu Station {k}", None, None, "subtitle", None, None, None, None, False)])
        f.run_once()
        a.want([2000 + k]) and a.run_once()
    assert len(at) == 40
    for i, t in enumerate(at):
        assert sum(1 for u in at[i:] if u - t < 60) <= O.PER_MINUTE


@pytest.mark.parametrize("trouble", ["refused", "offline"])
def test_a_failed_ask_keeps_the_old_answer_and_is_asked_again_after_retry_s(anilist, tmp_path, trouble):
    _media(anilist, 501, "RELEASING", 12)
    wall = {"t": NOW}
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path, clock=lambda: wall["t"])
    old = {"status": "RELEASING", "episodes": 12, "next_at": None, "asked_at": NOW - 2 * DAY}
    A._write(a.path, {"501": old})
    if trouble == "refused":
        anilist.down = True                         # a 503 / 429: refused (Retry-After isn't read)
    else:
        f.api = "http://127.0.0.1:9"                # nothing listens there: offline
    assert a.want([501]) == 1 and a.run_once() == 0
    assert A.read(a.path)["501"] == old, "the old answer stays"
    assert a.want([501]) == 0, "not asked again before RETRY_S"
    wall["t"] = NOW + A.RETRY_S - 1
    assert a.run_once() == 0
    anilist.down = False
    f.api = anilist.base
    wall["t"] = NOW + A.RETRY_S + 1
    assert a.run_once() == 1, "the retry comes by itself"
    assert A.read(a.path)["501"]["asked_at"] == NOW + A.RETRY_S + 1


def test_the_background_thread_asks_and_tells_the_reader(anilist, tmp_path):
    _media(anilist, 501, "RELEASING", 12)
    f = fetcher(Pen(), anilist, background=True)
    a = _airing(f, tmp_path)
    told = threading.Event()
    a.on_change = told.set
    try:
        assert a.want([501]) == 1
        assert told.wait(10)
        assert A.read(a.path)["501"]["status"] == "RELEASING"
    finally:
        f.stop()
    assert a.want([502]) == 0, "stopped with the fetcher"


def test_remove_downloaded_covers_clears_the_kept_answers(anilist, tmp_path):
    _media(anilist, 501, "RELEASING", 12)
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path)
    a.want([501]) and a.run_once()
    told = []
    a.on_change = lambda: told.append(1)
    f.remove_downloaded()
    assert not os.path.exists(a.path) and told
    assert a.want([501]) == 1, "asked again: nothing kept"


# --- the reader hands over Current's shows near their end, on its own thread (AW-2) ------------------------------- #
class _Asker:
    def __init__(self):
        self.asked = []
        self.on_change = None

    def want(self, ids):
        self.asked.append((threading.get_ident(), list(ids)))
        return len(ids)


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_the_reader_hands_over_only_current_s_shows_near_their_end_and_reads_the_answers_onto_the_view(tmp_path):
    seed = window_seed.build()
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    reader._airing_kept.path = str(tmp_path / "airing_ja.json")
    asker = _Asker()
    views = []
    reader.subscribe(views.append)
    reader.follow_airing(asker)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1].state == "full")
        assert asker.asked == [] or all(ids == [] for _t, ids in asker.asked), \
            "the hero has six episodes left; the arrivals' shows (202, 303) are never Current's"
        hero = [i for i in seed.library.items() if i["work_id"] == seed.hero_work]
        seed.library.commit(items=[dict(id=i["id"], watched=1) for i in hero[:-1]])
        assert _wait(lambda: asker.asked and asker.asked[-1][1])
        tid, ids = asker.asked[-1]
        assert ids == [101] and tid != threading.get_ident()
        A._write(reader._airing_kept.path, {"101": {"status": "RELEASING", "episodes": 12, "asked_at": NOW}})
        asker.on_change()                           # the asker's answer kept: the next view reads it
        assert _wait(lambda: views[-1].airing.get(seed.hero_work, {}).get("status") == "RELEASING")
    finally:
        reader.stop()


def test_the_asker_itself_never_calls_the_request_while_the_switch_is_off(tmp_path):
    """Its own rule, not only the fetcher's `_post`: a request handed in that would send anyway is never called."""
    sent = []
    switch = {"on": True}
    a = A.Airing("ja", lambda variables, query: sent.append(variables) or {"Page": {"media": []}},
                 lambda: switch["on"], path=str(tmp_path / "airing_ja.json"), clock=lambda: NOW, background=False)
    assert a.want([501]) == 1
    switch["on"] = False
    assert a.run_once() == 0 and sent == []
    switch["on"] = True
    assert a.want([501]) == 1 and a.run_once() == 1 and sent == [{"ids": [501]}]


def test_a_hand_edited_infinite_count_or_time_is_no_number():
    """`Infinity` in the cache (a hand edit): no count, so no "more" — and the offer's words never fail on it."""
    eps = [_ep(n) for n in range(1, 13)]
    assert A.holds({"status": "FINISHED", "episodes": float("inf")}, eps) is None
    assert A.holds({"status": "FINISHED", "episodes": float("nan")}, eps) is None
    assert A.due({"status": "FINISHED", "asked_at": float("-inf")}, NOW), "no time: asked"


def test_an_answer_in_flight_when_covers_are_removed_is_never_kept(anilist, tmp_path):
    """A7: *Remove downloaded covers* while a request is out — its answer lands after, and is dropped."""
    _media(anilist, 501, "RELEASING", 12)
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path)
    anilist.after_post = a.clear                    # the press comes while AniList answers
    assert a.want([501]) == 1 and a.run_once() == 0
    assert not os.path.exists(a.path) and a._known() == {}


def test_a_queued_or_retried_id_no_longer_near_its_end_is_never_sent(anilist, tmp_path):
    """Spec §4 *never: Finished*: a show finished (or moved out of Current) while its ask waited for its turn or its
    retry — the reader's next ids no longer hold it — is dropped, never sent."""
    wall = {"t": NOW}
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path, clock=lambda: wall["t"])
    anilist.down = True
    assert a.want([501, 502]) == 2 and a.run_once() == 0           # refused: both wait for their retry
    anilist.down = False
    a.want([502])                                                  # 501 left Current meanwhile
    wall["t"] = NOW + A.RETRY_S + 1
    assert a.run_once() == 1
    assert _queries(anilist)[-1]["variables"]["ids"] == [502]
    assert a.want([503]) == 1
    a.want([])                                                     # the view's last near-end show is gone
    assert a.run_once() == 0 and len(_queries(anilist)) == 2


def test_an_answer_the_same_as_before_builds_no_view(anilist, tmp_path):
    """S19: asked again a day later and AniList says the same, only its time moved: the reader isn't woken."""
    _media(anilist, 501, "RELEASING", 12, next_at=int(NOW + 3 * DAY), next_ep=9)
    wall = {"t": NOW}
    f = fetcher(Pen(), anilist)
    a = _airing(f, tmp_path, clock=lambda: wall["t"])
    told = []
    a.on_change = lambda: told.append(wall["t"])
    a.want([501]) and a.run_once()
    wall["t"] = NOW + DAY + 1
    assert a.want([501]) == 1 and a.run_once() == 1
    assert told == [NOW], "the first answer told the reader; the same answer again didn't"
    assert A.read(a.path)["501"]["asked_at"] == NOW + DAY + 1
    _media(anilist, 501, "FINISHED", 12)
    wall["t"] = NOW + 2 * DAY + 2
    a.want([501]) and a.run_once()
    assert told == [NOW, NOW + 2 * DAY + 2]


def test_the_cache_is_written_though_the_reader_holds_it_open_a_moment(tmp_path, monkeypatch):
    """Windows refuses a rename over a file another thread has open: tried again, never an answer lost."""
    path = str(tmp_path / "airing_ja.json")
    real_replace, refused = os.replace, []

    def busy_once(src, dst):
        if not refused:
            refused.append(dst)
            raise PermissionError(13, "in use")
        return real_replace(src, dst)
    monkeypatch.setattr(A.os, "replace", busy_once)
    monkeypatch.setattr(A, "REPLACE_WAIT_S", 0.0)
    assert A._write(path, {"501": {"status": "RELEASING"}}) and refused
    assert A.read(path) == {"501": {"status": "RELEASING"}}
