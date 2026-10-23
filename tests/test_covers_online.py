"""Covers from AniList (W3.2 Q7): `app/services/covers_online.py` — a new network call (the window's spec 01 §1.3).

What a wrong answer would cost a learner:
  * their show's name, a file name or a path sent to AniList while they never said yes (`covers_download` off), or a
    release group, an episode or a hash sent with a name (01 §1.3 *What leaves the machine, and nothing else*);
  * the cover they chose, or the poster beside their files, replaced by a downloaded one;
  * another show's cover on theirs (a near-miss title, the wrong season, the wrong year auto-accepted);
  * AniList's limits broken (more than 50 ids a query, more than 30 queries a minute), or the library swept;
  * a dialog, or an error, when they're offline — or a title that never gets its cover once they're back;
  * *Remove downloaded covers* taking the covers they chose; a picked candidate that Undo can't take back.

The network is blocked (`urllib.request.urlopen` refuses every address but 127.0.0.1, and the suite's own guard refuses
any connection past loopback); a fake AniList — a `http.server` on 127.0.0.1, its base URL handed in — answers the
GraphQL queries and serves the images (real JPEGs). The store tests run on a real migrated store (Japanese and Chinese
show names from tests/Test Resources) through the window's writer; the release names are real anime releases'.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from app import __version__
from app import path_utils
from app.services import covers as C
from app.services import covers_online as O
from tests import services_helpers as h
from tests.test_services_covers import Library, jpeg, png, write

REAL_URLOPEN = urllib.request.urlopen


@pytest.fixture(autouse=True)
def blocked(monkeypatch):
    """`urlopen` refuses everything but the fake server (127.0.0.1): an address it refused fails the test."""
    refused = []

    def guard(request, *args, **kwargs):
        url = getattr(request, "full_url", request)
        if urlsplit(str(url)).hostname != "127.0.0.1":
            refused.append(str(url))
            raise urllib.error.URLError("the network is blocked in tests")
        return REAL_URLOPEN(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guard)
    real_open = O._open

    def guard_open(request, allowed):               # the fetcher's own door (its redirects checked)
        if urlsplit(request.full_url).hostname != "127.0.0.1":
            refused.append(request.full_url)
            raise urllib.error.URLError("the network is blocked in tests")
        return real_open(request, allowed)

    monkeypatch.setattr(O, "_open", guard_open)
    yield refused
    assert refused == [], f"a request tried to leave the machine: {refused}"


# --- a fake AniList (and YouTube's thumbnails) on 127.0.0.1 --------------------------------------------------------- #
class AniList:
    def __init__(self):
        self.media = {}                 # id -> AniList's media
        self.found = {}                 # a search's text -> [ids], AniList's order
        self.posts = []                 # (body, headers)
        self.gets = []                  # (path, headers)
        self.down = False
        self.after_post = None          # called as an answer goes out (a test turns the switch off there)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, kind):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                fake.posts.append((body, dict(self.headers)))
                if fake.down:
                    return self._send(503, b"{}", "application/json")
                v = body["variables"]
                ids = v.get("ids") or [i for i in fake.found.get(v.get("search"), ())]
                media = [fake.media[i] for i in ids if i in fake.media]
                if fake.after_post is not None:
                    fake.after_post()
                self._send(200, json.dumps({"data": {"Page": {"media": media}}}).encode("utf-8"), "application/json")

            def do_GET(self):
                fake.gets.append((self.path, dict(self.headers)))
                if fake.down or not self.path.endswith(".jpg"):
                    return self._send(404, b"", "text/plain")
                self._send(200, png() if self.path.startswith("/vi/") else jpeg(), "image/jpeg")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add(self, id_, romaji, native=None, english=None, synonyms=(), year=None, fmt="TV", search=None):
        self.media[id_] = {"id": id_, "format": fmt, "seasonYear": year, "startDate": {"year": year},
                           "title": {"romaji": romaji, "english": english, "native": native},
                           "synonyms": list(synonyms), "coverImage": {"extraLarge": f"{self.base}/img/{id_}.jpg",
                                                                      "large": f"{self.base}/img/{id_}-s.jpg"}}
        if search is not None:
            self.found.setdefault(search, []).append(id_)
        return id_

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def anilist():
    fake = AniList()
    yield fake
    fake.close()


class Clock:
    """A clock the throttle and the retries read; `sleep` moves it (and is counted)."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Pen:
    """A writer that records the covers it's given."""

    def __init__(self):
        self.covers = []
        self.writable = True
        self.forgot = 0

    def can_write(self):
        return self.writable

    def idle(self, timeout=None):
        return True

    def set_cover(self, work_id, source, ref=None, path=None, locked=False, label=None, auto=False):
        self.covers.append((work_id, source, ref, path, locked, auto))
        return len(self.covers)

    def forget_covers(self, label=None):
        self.forgot += 1
        return 1


def want(id_, title="", anilist_id=None, video_id=None, kind="subtitle", media_type=None, source=None, ref=None,
         path=None, locked=False):
    return O.Want(id_, title, anilist_id, video_id, kind, media_type, source, ref, path, locked)


def fetcher(writer, server=None, on=True, language="ja", **kw):
    switch = {"covers_download": on}
    kw.setdefault("clock", Clock())
    kw.setdefault("sleep", kw["clock"].sleep)
    kw.setdefault("background", False)              # the test runs each round itself
    f = O.Fetcher(language, writer, settings=lambda: switch, api=(server.base if server else O.ANILIST_API),
                  ytimg=(server.base if server else O.YTIMG), image_hosts=("127.0.0.1",) if server else O.IMAGE_HOSTS,
                  **kw)
    f.switch = switch
    return f


# --- the switch ----------------------------------------------------------------------------------------------------- #
def test_with_the_switch_off_nothing_leaves_the_machine_not_even_a_title_asked_for(anilist):
    pen = Pen()
    f = fetcher(pen, anilist, on=False)
    asked = [want(1, "星送りのリーフェン", anilist_id=900101), want(2, "嵐壁の巨兵"), want(3, "動画", video_id="dQw4w9WgXcQ")]
    assert f.want(asked) == 0 and f.run_once() == 0
    assert anilist.posts == [] and anilist.gets == [] and pen.covers == []


def test_the_switch_is_off_by_default_so_a_fresh_install_sends_nothing_to_the_real_anilist():
    f = O.Fetcher("ja", Pen())                      # settings.json's defaults, the real AniList (the guard refuses it)
    assert f.on() is False
    assert f.want([want(1, "星送りのリーフェン", anilist_id=900101)]) == 0 and f.run_once() == 0


def test_the_switch_turned_off_after_a_title_was_asked_for_stops_the_next_request(anilist):
    pen = Pen()
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン")
    f = fetcher(pen, anilist)
    assert f.want([want(1, "星送りのリーフェン", anilist_id=900101)]) == 1
    f.switch["covers_download"] = False
    assert f.run_once() == 0 and anilist.posts == [] and pen.covers == []
    candidate = O.Candidate(900101, f"{anilist.base}/img/900101.jpg", "星送りのリーフェン", 2023, "TV")
    assert f.candidates(want(1, "星送りのリーフェン")) is None and f.pick(want(1, "星送りのリーフェン"), candidate) is None
    assert f.paste(want(1, "星送りのリーフェン"), "https://anilist.co/anime/900101") == (None, "off")
    assert anilist.posts == [] and anilist.gets == []


# --- what is sent ---------------------------------------------------------------------------------------------------- #
def test_the_requests_hold_only_an_id_or_a_cleaned_title_with_surasuras_user_agent_and_no_referer(anilist):
    pen = Pen()
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン")
    anilist.add(900202, "Arashikabe no Kyohei", "嵐壁の巨兵", english="Giants of the Storm Wall", year=2013, search="嵐壁の巨兵")
    f = fetcher(pen, anilist)
    release = r"D:\Anime\嵐壁の巨兵\[SubsPlease] 嵐壁の巨兵 - 01 (1080p) [ABCD1234].mkv"
    assert f.want([want(1, "星送りのリーフェン", anilist_id=900101), want(2, release)]) == 2
    assert f.run_once() == 2
    sent = [body["variables"] for body, _headers in anilist.posts]
    assert sent == [{"ids": [900101]}, {"search": "嵐壁の巨兵"}]
    assert all(set(body) == {"query", "variables"} for body, _headers in anilist.posts)
    raw = json.dumps([body for body, _headers in anilist.posts], ensure_ascii=False)
    for leak in ("SubsPlease", "1080p", "ABCD1234", "Anime", ".mkv", " - 01", "D:"):
        assert leak not in raw, leak
    for _what, headers in anilist.posts + anilist.gets:
        assert headers["User-Agent"] == f"Surasura/{__version__}"
        assert "Referer" not in headers and "Cookie" not in headers
    assert sorted(p for p, _h in anilist.gets) == ["/img/900101.jpg", "/img/900202.jpg"]
    assert [(c[1], c[2], c[5]) for c in pen.covers] == [("anilist", "900101", True), ("anilist", "900202", True)]


@pytest.mark.parametrize("name, cleaned, year", [
    ("[SubsPlease] Hoshiokuri no Riefen - 01 (1080p) [ABCD1234].mkv", "Hoshiokuri no Riefen", None),
    (r"D:\Anime\嵐壁の巨兵\[Group] 嵐壁の巨兵 第3話 (BD 1080p HEVC).ja.srt", "嵐壁の巨兵", None),
    ("Arashikabe.no.Kyohei.S02E05.1080p.WEB-DL.mkv", "Arashikabe no Kyohei Season 2", None),
    ("星送りのリーフェン (2023)", "星送りのリーフェン", 2023),
    ("みさき様は言わせたい 第2期 EP 03", "みさき様は言わせたい 第2期", None),
    ("ひとり・で・ぽっぷ！ #01", "ひとり・で・ぽっぷ!", None),
    ("Steins;Gate 0", "Steins;Gate 0", None),
])
def test_a_cleaned_title_loses_its_group_episode_resolution_hash_and_path(name, cleaned, year):
    assert O.clean_title(name) == (cleaned, year)


# --- batches and the pace --------------------------------------------------------------------------------------------- #
def test_ids_go_fifty_to_a_query(anilist):
    pen = Pen()
    ids = [100000 + n for n in range(120)]
    for i in ids:
        anilist.add(i, f"Title {i}")
    f = fetcher(pen, anilist, images_per_minute=1000)
    assert f.want([want(n, f"作品{n}", anilist_id=i) for n, i in enumerate(ids, 1)]) == 120
    assert f.run_once() == 120
    assert [len(body["variables"]["ids"]) for body, _h in anilist.posts] == [50, 50, 20]
    assert len(anilist.gets) == 120 and all(c[5] for c in pen.covers), "each a background cover"


def test_the_throttle_lets_thirty_through_a_minute_and_waits_out_the_oldest_for_the_next():
    clock = Clock()
    gate = O.Throttle(30, clock, clock.sleep)
    for _ in range(30):
        gate.wait()
        clock.now += 1
    assert clock.slept == []
    gate.wait()
    assert clock.slept == [30.0], "the 31st waits until the first is a minute old"


def test_anilists_queries_are_paced_under_its_limit(anilist):
    pen = Pen()
    for i in range(101):
        anilist.add(200000 + i, f"Title {i}")
    clock = Clock()
    f = fetcher(pen, anilist, clock=clock, sleep=clock.sleep, per_minute=2, images_per_minute=1000)
    f.want([want(n, f"作品{n}", anilist_id=200000 + n) for n in range(101)])
    assert f.run_once() == 101
    assert len(anilist.posts) == 3 and clock.slept == [60.0], "the third query waits a minute"


def test_a_title_asked_again_is_never_fetched_twice_in_a_session(anilist):
    pen = Pen()
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン")
    f = fetcher(pen, anilist)
    f.want([want(1, "星送りのリーフェン", anilist_id=900101)])
    f.run_once()
    assert f.want([want(1, "星送りのリーフェン", anilist_id=900101)]) == 0 and f.run_once() == 0
    assert len(anilist.posts) == 1


# --- the confidence gate ------------------------------------------------------------------------------------------- #
def _riefen(anilist):
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン", english="Riefen: Beyond the Starlit Road", year=2023,
                search="星送りのリーフェン")
    anilist.add(900104, "Hoshiokuri no Riefen: ●● no Mahou", "星送りのリーフェン ～●●の魔法～", year=2023, fmt="ONA",
                search="星送りのリーフェン")


def test_an_exact_title_with_the_right_season_and_year_is_accepted(anilist):
    _riefen(anilist)
    media = list(anilist.media.values())
    assert O.gate("星送りのリーフェン", media)["id"] == 900101
    assert O.gate("Hoshiokuri no Riefen", media, 2023)["id"] == 900101, "the romaji title"
    assert O.gate("riefen beyond the starlit road", media)["id"] == 900101, "the English one, normalised"
    pen = Pen()
    f = fetcher(pen, anilist)
    f.want([want(1, "[SubsPlease] 星送りのリーフェン (2023) - 05 (1080p).mkv")])
    assert f.run_once() == 1 and pen.covers[0][1:3] == ("anilist", "900101")


def test_a_near_miss_a_wrong_season_or_a_wrong_year_is_refused(anilist):
    anilist.add(900202, "Arashikabe no Kyohei", "嵐壁の巨兵", year=2013)
    anilist.add(900203, "Arashikabe no Kyohei Season 2", "嵐壁の巨兵 Season2", year=2017)
    anilist.add(900104, "Hoshiokuri no Riefen: ●● no Mahou", "星送りのリーフェン ～●●の魔法～", year=2023)
    media = list(anilist.media.values())
    assert O.gate("星送りのリーフェン", media) is None, "a near miss"
    assert O.gate("嵐壁の巨兵", [anilist.media[900203]]) is None, "the name says no season: the second isn't it"
    assert O.gate("嵐壁の巨兵 Season 3", media) is None, "no third season among the answers"
    assert O.gate("嵐壁の巨兵", media, 2019) is None, "the wrong year"
    assert O.gate("嵐壁の巨兵 第2期", media)["id"] == 900203 and O.gate("嵐壁の巨兵", media)["id"] == 900202
    twins = [anilist.media[900202], dict(anilist.media[900202], id=99999)]
    assert O.gate("嵐壁の巨兵", twins) is None, "two answers pass: neither is taken"


def test_a_search_with_no_sure_match_records_nothing_and_isnt_asked_again(anilist):
    anilist.add(900104, "Hoshiokuri no Riefen: ●● no Mahou", "星送りのリーフェン ～●●の魔法～", search="星送りのリーフェン")
    pen = Pen()
    f = fetcher(pen, anilist)
    f.want([want(1, "星送りのリーフェン")])
    assert f.run_once() == 0 and pen.covers == [] and anilist.gets == []
    assert f.want([want(1, "星送りのリーフェン")]) == 0, "the generated cover stays; Change cover… offers the top 5"


# --- the library: a real store through the window's writer ---------------------------------------------------------- #
@pytest.fixture(params=["ja", "zh"])
def lib(request):
    library = Library(request.param)
    yield library
    library.close()


def _wants(lib):
    feed = lib.store.read_feed()
    return {w.id: w for w in O.wants_from(feed["items"], feed["works"])}


def _landed(lib, before):
    return h.until(lambda: lib.heard.rereads > before and not lib.writer.pending())


def test_a_fetched_cover_lands_in_the_cache_as_a_background_cover_never_on_undo(lib, anilist):
    work = lib.work_of(lib.store.ids("now")[0])
    w = _wants(lib)[work]
    anilist.add(900202, "Arashikabe no Kyohei", w.title, search=w.title)
    f = fetcher(lib.writer, anilist, language=lib.language)
    before = lib.heard.rereads
    assert f.want([w]) == 1 and f.run_once() == 1 and _landed(lib, before)
    source, ref, path, locked = lib.row(work)
    assert (source, ref, locked) == ("anilist", "900202", 0) and path.startswith("cache:")
    assert os.path.isfile(C.image_path(lib.language, _wants(lib)[work]))
    assert not [n for n in os.listdir(path_utils.get_covers_cache_path()) if n.endswith(".part")]
    assert lib.heard.saved == [] and not lib.writer.can_undo()


def test_a_locked_user_or_disk_cover_is_never_asked_for_nor_replaced(lib, anilist, tmp_path):
    mine, disk, plain = (lib.work_of(lib.store.ids(t)[0]) for t in ("now", "soon", "goal"))
    C.keep_user_image(lib.language, mine, write(str(tmp_path / "お気に入り.png"), png()), lib.writer)
    write(os.path.join(lib.folder_of(lib.store.ids("soon")[0]), "poster.jpg"), jpeg())
    assert h.until(lambda: len(lib.heard.saved) == 1)
    lib.scan()
    lib.writer.set_cover(plain, "generated", locked=True)           # *Use a generated cover*
    assert h.until(lambda: len(lib.heard.saved) == 2)
    wants = _wants(lib)
    for n, work in enumerate((mine, disk, plain)):
        anilist.add(300000 + n, "x", wants[work].title, search=wants[work].title)
    f = fetcher(lib.writer, anilist, language=lib.language)
    assert f.want([wants[w]._replace(anilist_id=300000 + n) for n, w in enumerate((mine, disk, plain))]) == 0
    assert f.run_once() == 0 and anilist.posts == []
    assert lib.row(mine)[0] == "user" and lib.row(disk)[0] == "file" and lib.row(plain) == ("generated", None, None, 1)


def test_a_cover_the_user_chose_while_a_fetch_was_on_its_way_stays_theirs(lib, anilist, tmp_path):
    work = lib.work_of(lib.store.ids("now")[0])
    w = _wants(lib)[work]
    anilist.add(900202, "Arashikabe no Kyohei", w.title)
    f = fetcher(lib.writer, anilist, language=lib.language)
    assert f.want([w._replace(anilist_id=900202)]) == 1
    kept = C.keep_user_image(lib.language, work, write(str(tmp_path / "選んだ.png"), png()), lib.writer)
    assert h.until(lambda: len(lib.heard.saved) == 1)
    before = lib.heard.rereads
    f.run_once()
    assert _landed(lib, before)
    assert lib.row(work) == ("user", None, kept, 1), "the store refuses a fetch over the user's lock"


def test_offline_the_generated_cover_stays_quietly_and_the_title_is_asked_again_later(lib, anilist, capsys):
    work = lib.work_of(lib.store.ids("now")[0])
    w = _wants(lib)[work]._replace(anilist_id=900202)
    anilist.add(900202, "Arashikabe no Kyohei", "嵐壁の巨兵")
    clock = Clock()
    f = fetcher(lib.writer, anilist, language=lib.language, clock=clock, sleep=clock.sleep)
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    f.api = f"http://127.0.0.1:{probe.server_address[1]}"
    probe.server_close()                                             # a port nothing listens on: offline
    assert f.want([w]) == 1 and f.run_once() == 0
    assert lib.row(work)[0] is None and lib.heard.notes == []
    assert work in f._later and f._later[work][0] == clock.now + O.RETRY_S
    assert f.want([w]) == 0 and f.run_once() == 0, "not asked again before its time"
    f.api = anilist.base                                             # back online
    clock.now += O.RETRY_S
    before = lib.heard.rereads
    assert f.run_once() == 1 and _landed(lib, before)
    assert lib.row(work)[:2] == ("anilist", "900202")
    assert "Traceback" not in capsys.readouterr().out


def test_a_failing_server_is_retried_too_and_never_raises(anilist):
    pen = Pen()
    anilist.add(900202, "Arashikabe no Kyohei", "嵐壁の巨兵", search="嵐壁の巨兵")
    anilist.down = True
    f = fetcher(pen, anilist)
    f.want([want(1, "嵐壁の巨兵", anilist_id=900202), want(2, "嵐壁の巨兵")])
    assert f.run_once() == 0 and set(f._later) == {1, 2} and pen.covers == []


def test_remove_downloaded_covers_takes_only_the_downloaded_ones_and_they_may_come_again(lib, anilist, tmp_path):
    fetched, mine, disk = (lib.work_of(lib.store.ids(t)[0]) for t in ("now", "soon", "goal"))
    kept = C.keep_user_image(lib.language, mine, write(str(tmp_path / "表紙.png"), png()), lib.writer)
    poster = write(os.path.join(lib.folder_of(lib.store.ids("goal")[0]), "poster.jpg"), jpeg())
    assert h.until(lambda: len(lib.heard.saved) == 1)
    lib.scan()
    anilist.add(900202, "Arashikabe no Kyohei", "嵐壁の巨兵")
    f = fetcher(lib.writer, anilist, language=lib.language)
    before = lib.heard.rereads
    f.want([_wants(lib)[fetched]._replace(anilist_id=900202)])
    assert f.run_once() == 1 and _landed(lib, before)
    cached = C.image_path(lib.language, _wants(lib)[fetched])
    assert os.path.isfile(cached)
    before = lib.heard.rereads
    assert f.remove_downloaded() is not None and _landed(lib, before)
    assert lib.row(fetched) == ("anilist", "900202", None, 0) and not os.path.exists(cached)
    assert lib.row(mine) == ("user", None, kept, 1)
    assert os.path.isfile(C.image_path(lib.language, _wants(lib)[mine])), "the user's image is user data"
    assert lib.row(disk)[0] == "file" and os.path.isfile(poster)
    assert len(lib.heard.saved) == 1, "nothing of the fetch or the removal reached the user's Undo"
    assert f.want([_wants(lib)[fetched]._replace(anilist_id=900202)]) == 1, "re-fetchable while the switch is on"


def test_remove_downloaded_covers_deletes_only_a_bare_name_in_the_cache_never_a_path_a_record_names():
    # Why: `drop_cached` deletes what the store's records name; a record naming a path (an old store, a hand edit)
    # must never reach a file outside the cache — the local data folder one level up, the user's own covers.
    folder = path_utils.get_covers_cache_path()
    outside = write(os.path.join(os.path.dirname(folder), "嵐壁の巨兵.jpg"), jpeg())
    mine = write(os.path.join(path_utils.get_user_files_path("ja"), "covers", "星送りのリーフェン.png"), png())
    cached = write(os.path.join(folder, "anilist-900202.jpg"), jpeg())
    named = ["cache:../嵐壁の巨兵.jpg", "cache:..\\嵐壁の巨兵.jpg", "cache:" + mine, "user:星送りのリーフェン.png",
             "cache:anilist-900202.jpg"]
    assert O.drop_cached(named) == 1
    assert os.path.isfile(outside) and os.path.isfile(mine) and not os.path.exists(cached)


def test_a_picked_candidate_is_the_users_locked_with_undo(lib, anilist):
    work = lib.work_of(lib.store.ids("now")[0])
    w = _wants(lib)[work]
    for n in range(7):
        anilist.add(400000 + n, f"Candidate {n}", f"{w.title}{n}", year=2010 + n, search=w.title)
    f = fetcher(lib.writer, anilist, language=lib.language)
    found = f.candidates(w)
    assert [c.id for c in found] == [400000 + n for n in range(5)], "the top five, AniList's order"
    assert found[2] == O.Candidate(400002, f"{anilist.base}/img/400002.jpg", f"{w.title}2", 2012, "TV")
    path = f.pick(w, found[2])
    assert h.until(lambda: len(lib.heard.saved) == 1)
    assert lib.row(work) == ("anilist", "400002", path, 1) and path.startswith("user:")
    assert os.path.isfile(C.image_path(lib.language, _wants(lib)[work]))
    lib.writer.undo()
    assert h.until(lambda: lib.heard.undone)
    assert lib.row(work) == (None, None, None, 0)


def test_paste_a_link_takes_anilist_and_youtube_links_and_nothing_else(lib, anilist):
    work = lib.work_of(lib.store.ids("now")[0])
    w = _wants(lib)[work]
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン")
    f = fetcher(lib.writer, anilist, language=lib.language)
    assert f.paste(w, "https://example.com/riefen.jpg") == (None, "not_a_link")
    assert f.paste(w, r"C:\Users\me\Pictures\riefen.jpg") == (None, "not_a_link")
    assert f.paste(w, "https://www.themoviedb.org/tv/900999-riefen") == (None, "no_key")
    assert anilist.posts == [] and anilist.gets == []
    path, why = f.paste(w, "https://anilist.co/anime/900101/Hoshiokuri-no-Riefen/")
    assert why is None and h.until(lambda: len(lib.heard.saved) == 1)
    assert lib.row(work) == ("anilist", "900101", path, 1)
    assert [b["variables"] for b, _h in anilist.posts] == [{"ids": [900101]}]
    path, why = f.paste(_wants(lib)[work], "https://youtu.be/dQw4w9WgXcQ")
    assert why is None and h.until(lambda: len(lib.heard.saved) == 2)
    assert lib.row(work) == ("youtube", "dQw4w9WgXcQ", path, 1) and anilist.gets[-1][0] == "/vi/dQw4w9WgXcQ/hqdefault.jpg"
    backups = os.listdir(os.path.join(path_utils.get_user_files_path(lib.language), "covers", ".trash"))
    assert len(backups) == 1, "the pick it replaced backed up dated"


# --- YouTube (C5) ---------------------------------------------------------------------------------------------------- #
def test_a_youtube_videos_thumbnail_is_fetched_only_with_the_switch_on(anilist):
    pen = Pen()
    video = want(5, "ゆっくり解説", video_id="dQw4w9WgXcQ", kind="youtube", media_type="youtube")
    off = fetcher(pen, anilist, on=False)
    assert off.want([video]) == 0 and off.run_once() == 0 and anilist.gets == []
    on = fetcher(pen, anilist)
    assert on.want([video]) == 1 and on.run_once() == 1
    assert [p for p, _h in anilist.gets] == ["/vi/dQw4w9WgXcQ/hqdefault.jpg"] and anilist.posts == []
    assert pen.covers[0][1:3] == ("youtube", "dQw4w9WgXcQ") and pen.covers[0][5] is True


def test_wants_from_the_feed_finds_a_videos_id_and_leaves_books_and_bilibili_alone():
    items = [
        {"id": 1, "ord": 1, "work_id": 10, "source_type": "youtube", "rel_path": "YouTube/ゆっくり解説 [dQw4w9WgXcQ].txt"},
        {"id": 2, "ord": 2, "work_id": 11, "source_type": "subtitle", "rel_path": "NOW/嵐壁の巨兵/嵐壁の巨兵_第01話.srt"},
        {"id": 3, "ord": 3, "work_id": 12, "source_type": "epub", "rel_path": "NOW/本棚好きの逆転劇/第一部.txt"},
        {"id": 4, "ord": 4, "work_id": 13, "source_type": "bilibili", "rel_path": "NOW/某视频 [BV1xx411c7mD].srt"},
    ]
    works = {i: {"id": i, "title": t} for i, t in ((10, "ゆっくり解説"), (11, "嵐壁の巨兵"), (12, "本棚好きの逆転劇"),
                                                   (13, "某视频"))}
    got = {w.id: w for w in O.wants_from(items, works)}
    assert got[10].video_id == "dQw4w9WgXcQ" and got[11].kind == "subtitle"
    assert [i for i in sorted(got) if O.fetchable(got[i])] == [10, 11]


def test_the_fetcher_works_on_its_own_thread_and_want_returns_at_once(anilist):
    pen = Pen()
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン")
    f = O.Fetcher("ja", pen, settings=lambda: {"covers_download": True}, api=anilist.base, ytimg=anilist.base,
                  image_hosts=("127.0.0.1",))
    try:
        started = time.monotonic()
        assert f.want([want(1, "星送りのリーフェン", anilist_id=900101)]) == 1
        assert time.monotonic() - started < 0.05
        assert h.until(lambda: pen.covers) and f._thread is not threading.current_thread()
    finally:
        f.stop()


def test_an_image_from_anywhere_but_anilist_or_youtube_is_never_fetched(anilist):
    pen = Pen()
    anilist.add(900101, "Hoshiokuri no Riefen", "星送りのリーフェン")
    anilist.media[900101]["coverImage"] = {"large": "https://evil.example/cover.jpg"}
    f = fetcher(pen, anilist)
    f.want([want(1, "星送りのリーフェン", anilist_id=900101)])
    assert f.run_once() == 0 and pen.covers == [] and anilist.gets == []


# --- W3.2 L3 fix round: the switch holds mid-wait, a stop ends at once, art on disk first, gone files asked again -- #
def test_B1_the_switch_turned_off_while_the_throttle_waits_sends_nothing_after_it(anilist):
    """A full minute, the user turns *Download covers* off: the search waiting its turn never leaves (01 §1.3 C1)."""
    pen = Pen()
    clock = Clock()
    f = fetcher(pen, anilist, clock=clock, per_minute=1)

    def sleep(seconds):
        f.switch["covers_download"] = False         # turned off in Settings while the fetcher waits for its turn
        clock.sleep(seconds)
    f.api_gate.sleep = sleep
    f.want([want(1, "星送りのリーフェン"), want(2, "嵐壁の巨兵")])
    assert f.run_once() == 0
    assert len(anilist.posts) == 1 and clock.slept, "the second search waited, and the switch was off at its turn"
    assert anilist.gets == [] and pen.covers == []
    f.switch["covers_download"] = True
    assert f.want([want(2, "嵐壁の巨兵")]) == 1, "dropped while off, never parked for a retry: asked again once on"


def test_B1_the_switch_turned_off_inside_an_id_answer_fetches_no_image_of_its_batch(anilist):
    pen = Pen()
    ids = [900101 + n for n in range(5)]
    for i in ids:
        anilist.add(i, f"Title {i}")
    f = fetcher(pen, anilist, images_per_minute=1000)
    anilist.after_post = lambda: f.switch.update(covers_download=False)
    f.want([want(n, f"作品{n}", anilist_id=i) for n, i in enumerate(ids, 1)])
    assert f.run_once() == 0 and len(anilist.posts) == 1
    assert anilist.gets == [] and pen.covers == [], "no image of the batch once the switch is off"


def test_B1_a_fetcher_stopped_mid_throttle_ends_at_once_never_spins_and_sends_nothing_more(anilist):
    """A library switch or the window closing stops the fetcher: its thread ends within a second, the throttle's loop
    turns only a handful of times (it used to spin a core for up to a minute), and the waiting search never leaves."""
    pen = Pen()
    f = O.Fetcher("ja", pen, settings=lambda: {"covers_download": True}, api=anilist.base, ytimg=anilist.base,
                  image_hosts=("127.0.0.1",), per_minute=1)
    try:
        f.want([want(1, "星送りのリーフェン"), want(2, "嵐壁の巨兵")])
        assert h.until(lambda: len(anilist.posts) == 1 and f.api_gate.turns >= 2)   # the second waits its minute
        time.sleep(0.1)
        started = time.monotonic()
        f.stop(timeout=5)
        assert not f._thread.is_alive() and time.monotonic() - started < 1.0
        assert f.api_gate.turns <= 3, f"the wait loop ran {f.api_gate.turns} turns"
        time.sleep(0.2)
        assert len(anilist.posts) == 1 and pen.covers == []
    finally:
        f.stop(timeout=0)


def test_N_an_idle_fetcher_sleeps_until_asked_with_no_timer_waking_it(anilist):
    pen = Pen()
    f = O.Fetcher("ja", pen, settings=lambda: {"covers_download": True}, api=anilist.base, ytimg=anilist.base,
                  image_hosts=("127.0.0.1",))
    waits = []

    class Cond(type(f._cond)):
        def wait(self, timeout=None):
            waits.append(timeout)
            return super().wait(timeout)
    f._cond = Cond()
    try:
        f.want([want(1, "星送りのリーフェン")])          # nothing found: done, nothing to retry
        assert h.until(lambda: len(anilist.posts) == 1 and waits)
        time.sleep(0.7)
        assert waits == [None], "asleep without a timeout (S19), never waking every half second"
    finally:
        f.stop()


def test_N_an_image_redirected_to_another_host_is_refused_and_plain_http_never_leaves(anilist):
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{anilist.server.server_address[1]}/img/1.jpg")
            self.send_header("Content-Length", "0")
            self.end_headers()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        f = fetcher(Pen(), anilist)
        with pytest.raises(O._Failed):
            f._image(f"http://127.0.0.1:{server.server_address[1]}/img/1.jpg")
        assert anilist.gets == [], "the redirect's other host was never asked"
    finally:
        server.shutdown()
        server.server_close()
    real = O.Fetcher("ja", Pen())
    assert real._allowed("https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx900202.jpg")
    assert real._allowed("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    assert not real._allowed("http://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx900202.jpg")
    assert not real._allowed("https://evil.example/cover.jpg")


def test_S2_the_users_own_ask_goes_ahead_of_a_full_background_minute():
    clock = Clock()
    gate = O.Throttle(30, clock, clock.sleep, reserve=5)
    for _ in range(25):
        assert gate.wait()
    assert clock.slept == []
    assert gate.wait(first=True) and clock.slept == [], "Find it online… never waits behind the queue"
    gate.wait()
    assert clock.slept == [60.0], "the background's 26th waits its minute"
    assert O.Fetcher("ja", Pen()).api_gate.reserve == 5


def test_S2_a_waiter_sleeps_outside_the_throttles_lock_so_the_users_ask_never_waits_behind_it():
    over = threading.Event()
    gate = O.Throttle(6, time.monotonic, lambda s: over.wait(s), reserve=1)
    for _ in range(5):
        gate.wait()
    background = threading.Thread(target=gate.wait, args=(lambda: not over.is_set(),), daemon=True)
    background.start()
    try:
        assert h.until(lambda: gate.turns >= 6)     # the background's sixth waits its minute
        started = time.monotonic()
        user = threading.Thread(target=gate.wait, kwargs={"first": True}, daemon=True)
        user.start()
        user.join(2)
        assert not user.is_alive() and time.monotonic() - started < 0.5
    finally:
        over.set()
        background.join(2)
    assert not background.is_alive()


def test_S2_find_it_online_goes_ahead_of_the_background_queue(anilist):
    pen = Pen()
    clock = Clock()
    _riefen(anilist)
    f = fetcher(pen, anilist, clock=clock, per_minute=6)
    f.want([want(n, t) for n, t in enumerate(("嵐壁の巨兵", "本棚好きの逆転劇", "茶屋のないしょごと", "霧断の剣", "符術奇譚"), 1)])
    f.run_once()
    assert len(anilist.posts) == 5 and clock.slept == []
    assert f.candidates(want(9, "星送りのリーフェン")) and clock.slept == []


def test_B2_the_store_writes_a_fetched_cover_only_over_none_generated_or_its_own(lib):
    s = lib.store
    a, b, c = (lib.work_of(s.ids(t)[0]) for t in ("now", "soon", "goal"))
    assert s.set_cover(a, "anilist", ref="900202", path="cache:anilist-a.jpg") is not None, "over none"
    assert s.set_cover(a, "anilist", ref="900202", path="cache:anilist-a2.jpg") is not None, "its own source's"
    assert s.set_cover(a, "youtube", ref="dQw4w9WgXcQ", path="cache:youtube-a.jpg") is None, "another source's"
    poster = lib.rel(os.path.join(lib.folder_of(s.ids("soon")[0]), "poster.jpg"))
    assert s.set_cover(b, "file", ref=poster) is not None
    assert s.set_cover(b, "anilist", ref="900202", path="cache:anilist-b.jpg") is None, "never over the art on disk"
    assert lib.row(b) == ("file", poster, None, 0)
    assert s.set_cover(c, "generated") is not None
    assert s.set_cover(c, "anilist", ref="900202", path="cache:anilist-c.jpg") is not None, "over the generated one"
    # Its own source, but an image of the user's (User Files, not the re-fetchable cache): never written over.
    assert s.set_cover(c, "anilist", ref="900202", path="user:茶屋のないしょごと.png") is not None
    assert s.set_cover(c, "anilist", ref="900202", path="cache:anilist-c2.jpg") is None, "never over a user: image"
    assert lib.row(c) == ("anilist", "900202", "user:茶屋のないしょごと.png", 0)
    assert s.set_cover(a, "file", ref=poster) is not None, "art on disk is written over a downloaded cover (D-1)"


def test_B2_an_arrival_with_its_folder_art_takes_the_art_and_anilist_is_never_asked(lib, anilist):
    """Scenario A: a show arrives mid-session with folder.jpg beside it (the open's scan never saw it): the disk is
    looked at first — even with an AniList id — and nothing leaves the machine."""
    show = lib.store.ids("now")[0]
    work = lib.work_of(show)
    art = write(os.path.join(lib.folder_of(show), "folder.jpg"), jpeg())
    w = _wants(lib)[work]._replace(anilist_id=900202)
    assert w.rel_paths
    anilist.add(900202, "Arashikabe no Kyohei", w.title, search=O.clean_title(w.title)[0])
    f = fetcher(lib.writer, anilist, language=lib.language, data_dir=lib.data_dir)
    before = lib.heard.rereads
    assert f.want([w]) == 1 and f.run_once() == 0 and _landed(lib, before)
    assert lib.row(work) == ("file", lib.rel(art), None, 0)
    assert anilist.posts == [] and anilist.gets == []
    assert f.want([w]) == 0, "done for the session"


def test_B2_the_scans_disk_record_landing_before_a_fetch_is_never_overwritten(lib, anilist):
    """Scenario B: the fetch read the record before the open's scan recorded the art beside the files; the store
    refuses the fetch at write time."""
    show = lib.store.ids("now")[0]
    work = lib.work_of(show)
    w = _wants(lib)[work]._replace(anilist_id=900202)                 # the fetch's copy: no cover yet
    anilist.add(900202, "Arashikabe no Kyohei", w.title)
    f = fetcher(lib.writer, anilist, language=lib.language, data_dir=lib.data_dir)
    assert f.want([w]) == 1
    poster = lib.rel(os.path.join(lib.folder_of(show), "poster.jpg"))
    lib.writer.set_cover(work, "file", ref=poster, auto=True)        # the scan's record lands first
    assert h.until(lambda: lib.row(work)[0] == "file" and not lib.writer.pending())
    before = lib.heard.rereads
    f.run_once()
    assert _landed(lib, before)
    assert lib.row(work) == ("file", poster, None, 0), "the art beside the files stays"


def test_S3_S4_a_downloaded_cover_whose_file_went_is_asked_again_and_lands_under_a_new_name(lib, anilist):
    """Another library's *Remove downloaded covers* (or an Undo back to an old record) took the cached file: the title
    is askable again, and its new file lands under a new name so the row repaints."""
    work = lib.work_of(lib.store.ids("now")[0])
    anilist.add(900202, "Arashikabe no Kyohei", "嵐壁の巨兵")
    f = fetcher(lib.writer, anilist, language=lib.language, data_dir=lib.data_dir)
    before = lib.heard.rereads
    f.want([_wants(lib)[work]._replace(anilist_id=900202)])
    assert f.run_once() == 1 and _landed(lib, before)
    old = _wants(lib)[work]._replace(anilist_id=900202)
    os.remove(C.image_path(lib.language, old))
    assert O.fetchable(old)
    again = fetcher(lib.writer, anilist, language=lib.language, data_dir=lib.data_dir)    # the next ask
    before = lib.heard.rereads
    assert again.want([old]) == 1 and again.run_once() == 1 and _landed(lib, before)
    new = _wants(lib)[work]
    assert new.cover_source == "anilist" and new.cover_path != old.cover_path
    assert os.path.isfile(C.image_path(lib.language, new))


# --- laptop fixes, row 18: a show that came in video-only, sent to Finished, gets its cover -------------------------- #
_VIDEO_ONLY = {"ja": "ある日の物語", "zh": "夜市小记"}          # made-up show names


def _video_only_show(lib):
    """Setup's first look at a folder of the user's (`sources.scan(first=True)`, as `setup_wizard.read_folders` runs
    it) holding one show of videos with no subtitles beside them: its episodes wait in New arrivals (K5, *no subtitles
    yet*) — then the user sends it to Finished (he has watched it). -> (its work, its item ids)."""
    from app import sources
    from tests.test_sources_scan import _drive, _video
    sources._LOOKED.clear()
    show = os.path.join(_drive("anime"), _VIDEO_ONLY[lib.language])
    for e in (1, 2, 3):
        _video(os.path.join(show, f"[Kumo-Subs] Aru Hi no Monogatari - {e:02d} (1080p).mkv"),
               body=b"\x1a\x45\xdf\xa3 matroska " + bytes([e]) * 64)    # each episode its own bytes (its own video)
    got = sources.scan(lib.store, lib.language, lib.store.add_source(os.path.dirname(show)), first=True)
    sources._LOOKED.clear()
    ids = [i for i in got["ids"] if lib.store.item(i)["availability"] == "waiting"]
    assert len(ids) == 3, got
    assert {lib.store.item(i)["source_type"] for i in ids} == {"subtitle"}, "typed as the show's episodes it waits as"
    work = lib.work_of(ids[0])
    assert lib.store._work_row(work)["title"] == _VIDEO_ONLY[lib.language]
    lib.writer.set_finished(ids)
    assert h.until(lambda: not lib.writer.pending() and all(lib.store.item(i)["tier"] == "graduated" for i in ids))
    return work, ids


def test_row18_a_video_only_show_from_setup_sent_to_finished_is_asked_online_and_its_cover_lands(lib, anilist):
    """Sonic, row 18: the shows he sent to Finished at the start got no cover, while a folder added on the Finished
    page did. A show whose videos came in with no subtitles is typed `subtitle` by the store as they come in, so its
    Want's kind is a show's. Wrong, its items were typed by the fallback ('text'): its Want's kind read 'text' and
    `fetchable` refused it in every place it stood — New arrivals, Current, Finished — for good."""
    work, _ids = _video_only_show(lib)
    w = _wants(lib)[work]
    assert w.kind == "subtitle" and O.fetchable(w), "a show waiting for its subtitles is a show, asked like one"
    anilist.add(171000, "Aru Hi no Monogatari", w.title, search=O.clean_title(w.title)[0])
    f = fetcher(lib.writer, anilist, language=lib.language, data_dir=lib.data_dir)
    before = lib.heard.rereads
    assert f.want([w]) == 1 and f.run_once() == 1 and _landed(lib, before)
    source, ref, path, locked = lib.row(work)
    assert (source, ref, locked) == ("anilist", "171000", 0) and path.startswith("cache:")
    searches = [b["variables"]["search"] for b, _h in anilist.posts if "search" in b["variables"]]
    assert searches == [_VIDEO_ONLY[lib.language]], "its cleaned name only, asked once"


def test_row18_a_coverless_finished_show_is_asked_once_a_session_never_a_storm(lib, anilist):
    """S19: an existing Finished show with no cover (one AniList doesn't know) is asked at its first paint after the
    fix — once: painted again, asked again by the window, the fetcher sends nothing more."""
    work, _ids = _video_only_show(lib)
    f = fetcher(lib.writer, anilist, language=lib.language, data_dir=lib.data_dir)
    for _ in range(3):
        f.want([_wants(lib)[work]])
        f.run_once()
    assert len(anilist.posts) == 1 and anilist.gets == [] and lib.row(work)[0] is None


def test_a_candidates_search_that_didnt_answer_raises_and_one_that_found_nothing_is_empty(anilist):
    """The press rule (Sonic, 2026-10-23: the AniList lookup reacts at once — found, *No cover found on AniList*, or
    failed): a search AniList didn't answer (503 here, offline alike) is never told as "nothing found"."""
    f = fetcher(Pen(), anilist)
    assert f.candidates(want(1, "星送りのリーフェン")) == []           # AniList answered: no such title
    anilist.down = True
    with pytest.raises(O.LookupFailed):
        f.candidates(want(1, "星送りのリーフェン"))
