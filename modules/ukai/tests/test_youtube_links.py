# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜 Ukai's YouTube links through the one door (Ukai SPEC §6 U-S3; its CONTRACT.md v3, `POST /v1/youtube`; ported
from #474's `tests/test_online_receiver.py`, by mattias): a simulated loopback POST with the extension's own body
(`src/delivery.js` `postYoutube`: {"schema": 1, "urls": [...]}) on the real door's Ukai class.

What a wrong answer would cost a learner: yt-dlp runs on their PC started by an extension they never allowed, or by a
web page; runs past the downloader's switch or its risk tick (rate limits they never agreed to); a playlist pressed
twice downloaded twice; a link that isn't YouTube's handed to yt-dlp; the bar silent about what came in.
"""
import http.client
import json
import socket
import sys
from types import SimpleNamespace

import pytest

from app import door
from modules import ukai
from modules.ukai import youtube
from tests.test_library_store_support import LANGUAGES

ORIGIN = "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb"
TOKEN = "U" * 32
LINKS = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/playlist?list=PLjfPBTv1Zr1J8"]
ON = {"enable_youtube_transcripts": True, "youtube_risk_acknowledged": True}


def _free_port():
    with socket.socket() as s:
        s.bind((door.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture(params=LANGUAGES)
def run(request, tmp_path, monkeypatch):
    """The door with Ukai's class (its pairing a stand-in: `ukai_pairing`'s is tested in core) and the module's routes;
    `start` records what would go to the window's thread -> (door, held, started)."""
    held = {"writer": SimpleNamespace(language=request.param), "settings": dict(ON), "fail": None}
    started = []

    def start(urls, release):
        if held["fail"]:
            raise held["fail"]
        started.append((urls, release))
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    ext = door.Extension(ukai.routes(writer=lambda: held["writer"], settings=lambda: held["settings"],
                                     youtube=start), lambda: (ORIGIN, TOKEN))
    d = door.Door({}, str(tmp_path / "results"), extension=ext).start()
    yield d, held, started
    d.stop()


def _ask(d, body, token=TOKEN, origin=ORIGIN, raw=None):
    conn = http.client.HTTPConnection(door.HOST, d.ext_port, timeout=30)
    headers = {"Host": f"{door.HOST}:{d.ext_port}", "Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    if token is not None:
        headers[door.EXT_TOKEN_HEADER] = token
    data = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    conn.request("POST", "/v1/youtube", body=data, headers=headers)
    r = conn.getresponse()
    got = json.loads(r.read().decode("utf-8"))
    conn.close()
    return r.status, got


def _links(urls):
    return {"schema": 1, "urls": urls}


def test_links_go_to_the_downloader_only_from_the_paired_extension(run):
    """No token, a wrong one, another extension, a web page, no Origin at all: refused before anything runs. The
    paired extension's links are queued, as many as it sent, and handed on whole."""
    d, _held, started = run
    assert _ask(d, _links(LINKS), token=None)[0] == 401
    assert _ask(d, _links(LINKS), token="W" * 32)[0] == 401
    assert _ask(d, _links(LINKS), origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")[0] == 403
    assert _ask(d, _links(LINKS), origin="https://www.youtube.com")[0] == 403, "a web page's script"
    assert _ask(d, _links(LINKS), origin=None)[0] == 403, "a POST names its Origin"
    assert started == []
    assert _ask(d, _links(LINKS)) == (200, {"ok": True, "queued": 2})
    assert [urls for urls, _r in started] == [LINKS]


def test_never_past_the_downloaders_switch_or_its_risk_tick(run, monkeypatch):
    """The 409 says which (Ukai shows its words); nothing runs. A tick that isn't True is no tick."""
    d, held, started = run
    for values, words in (({}, youtube.OFF), ({"enable_youtube_transcripts": True}, youtube.TICK),
                          ({"enable_youtube_transcripts": True, "youtube_risk_acknowledged": "yes"}, youtube.TICK),
                          ({"youtube_risk_acknowledged": True}, youtube.OFF)):
        held["settings"] = values
        assert _ask(d, _links(LINKS)) == (409, {"ok": False, "why": words, "kind": "refused"})
    held["settings"] = dict(ON)
    monkeypatch.setitem(sys.modules, "modules.youtube_downloader", None)      # (the downloader's folder gone)
    assert _ask(d, _links(LINKS)) == (409, {"ok": False, "why": youtube.ABSENT, "kind": "refused"})
    held["settings"] = "not settings"                                          # (unreadable: no switch, no tick)
    monkeypatch.delitem(sys.modules, "modules.youtube_downloader")
    assert _ask(d, _links(LINKS))[1]["why"] == youtube.OFF
    assert started == []


@pytest.mark.parametrize("urls", [
    ["https://evil.example/watch?v=dQw4w9WgXcQ"], ["http://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    ["https://www.youtube.com.evil.example/watch?v=dQw4w9WgXcQ"], ["https://[www.youtube.com/watch"],
    ["https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://evil.example/"], ["https://youtu.be/dQw4w9WgXcQ x"],
    ["\x00https://www.youtube.com/watch?v=dQw4w9WgXcQ"], ["https://www.youtube.com/watch?v=" + "d" * 2048],
    [7], [], ["https://youtu.be/dQw4w9WgXcQ"] * 51, "https://youtu.be/dQw4w9WgXcQ", None])
def test_a_link_that_isnt_youtubes_own_https_one_is_a_400_and_nothing_runs(run, urls):
    d, _held, started = run
    status, got = _ask(d, _links(urls))
    assert status == 400 and got["kind"] == "body" and started == []


def test_a_body_that_isnt_the_contracts_is_a_400(run):
    d, _held, started = run
    for body in ({"urls": LINKS}, {"schema": 2, "urls": LINKS}):
        assert _ask(d, body)[0] == 400
    assert _ask(d, None, raw=b"[1, 2]")[0] == 400
    assert _ask(d, None, raw=b"{" + b" " * youtube.MAX_BODY + b"}")[0] == 413, "read no further than 64 KB"
    assert started == []


def test_links_sent_again_while_their_run_goes_on_start_no_second_run(run):
    """Mattias pressed it twice for an 8-video playlist: two yt-dlp runs. A link already running is refused (the 409's
    *already*), nothing held for it; another runs beside it; once its run ends, it can be sent again."""
    d, _held, started = run
    assert _ask(d, _links(LINKS[1:]))[0] == 200
    assert _ask(d, _links(LINKS[1:])) == (409, {"ok": False, "why": youtube.RUNNING, "kind": "refused"})
    assert _ask(d, _links(LINKS))[0] == 409, "one of them is running"
    assert _ask(d, _links(LINKS[:1]))[0] == 200, "another link runs beside it"
    started[0][1]()                                                     # the playlist's run ended
    assert _ask(d, _links(LINKS[1:]))[0] == 200
    assert [urls for urls, _r in started] == [LINKS[1:], LINKS[:1], LINKS[1:]]


def test_the_same_link_twice_in_one_send_is_one_link(run):
    d, _held, started = run
    assert _ask(d, _links([LINKS[0], " " + LINKS[0] + " ", LINKS[0]])) == (200, {"ok": True, "queued": 1})
    assert started[0][0] == LINKS[:1]


def test_no_library_open_is_busy_and_holds_nothing(run):
    """503 *busy*: Ukai keeps the links and sends them again; nothing claimed meanwhile."""
    d, held, started = run
    held["writer"] = None
    assert _ask(d, _links(LINKS)) == (503, {"ok": False, "why": youtube.NO_LIBRARY, "kind": "busy"})
    held["writer"] = SimpleNamespace(language="ja")
    assert _ask(d, _links(LINKS))[0] == 200 and len(started) == 1


def test_a_hand_off_that_fails_lets_its_links_go(run):
    """The window's hand-off raising (its bug): 503 *crashed*, Ukai keeps them, and the links aren't left claimed."""
    d, held, started = run
    held["fail"] = RuntimeError("the window's bridge is gone")
    assert _ask(d, _links(LINKS))[1]["kind"] == "crashed"
    held["fail"] = None
    assert _ask(d, _links(LINKS))[0] == 200 and len(started) == 1


def test_without_a_window_to_run_them_the_links_are_refused(tmp_path, monkeypatch):
    """`routes` without `youtube` (no window hands one): the route answers the downloader's absence, never a run."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    ext = door.Extension(ukai.routes(writer=lambda: SimpleNamespace(language="ja"), settings=lambda: dict(ON)),
                         lambda: (ORIGIN, TOKEN))
    d = door.Door({}, str(tmp_path / "results"), extension=ext).start()
    try:
        assert _ask(d, _links(LINKS)) == (409, {"ok": False, "why": youtube.ABSENT, "kind": "refused"})
    finally:
        d.stop()


def test_while_off_nothing_listens_for_the_links(tmp_path, monkeypatch):
    """`door.EXTENSION_ON = False` (until Ukai 1.0): the class is handed in, yet no port answers for it."""
    assert door.EXTENSION_ON is False
    port = _free_port()
    monkeypatch.setattr(door, "EXT_PORT", port)
    ext = door.Extension(ukai.routes(writer=lambda: None, settings=dict, youtube=lambda u, r: pytest.fail("ran")),
                         lambda: (ORIGIN, TOKEN))
    d = door.Door({}, str(tmp_path / "results"), extension=ext).start()
    try:
        assert d.ext_port is None
        with pytest.raises(OSError):
            socket.create_connection((door.HOST, port), timeout=2).close()
    finally:
        d.stop()


# --- the window's half (#474's `windows` helpers, now `modules/ukai/youtube.py`) --------------------------------- #
def test_the_window_never_runs_links_past_the_downloaders_switch_or_its_risk_tick():
    assert youtube.refused({}) == youtube.OFF
    assert youtube.refused({"enable_youtube_transcripts": True}) == youtube.TICK
    assert youtube.refused({"enable_youtube_transcripts": True, "youtube_risk_acknowledged": "yes"}) == youtube.TICK
    assert youtube.refused(ON) is None


def test_link_runs_hold_a_link_once_until_released():
    runs = youtube.LinkRuns()
    playlist = LINKS[1:]
    assert runs.claim(playlist) is True
    assert runs.claim(playlist) is False
    assert runs.claim(LINKS) is False
    assert runs.claim(LINKS[:1]) is True, "another link runs beside it"
    runs.release(playlist)
    assert runs.claim(playlist) is True


def test_a_runs_progress_shows_in_the_bar_at_most_every_two_seconds():
    said, now = [], [100.0]
    bar = youtube.BarLines(said.append, every=2.0, clock=lambda: now[0])
    assert bar("1 of 8 videos read") is True
    now[0] += 0.5
    assert bar("2 of 8 videos read") is False and bar("") is False
    now[0] += 2.0
    assert bar("3 of 8 videos read") is True
    assert said == [youtube.PROGRESS.format(line=f"{n} of 8 videos read") for n in (1, 3)]


@pytest.fixture(params=LANGUAGES)
def window_run(request, monkeypatch):
    """`youtube.run` with the window's pieces recorded: the bar, New arrivals' hand-in, the downloader's fetch."""
    import modules.youtube_downloader as downloader
    from app.qt import windows
    bar, arrived, fetched, released = [], [], [], []
    shell = SimpleNamespace(services=SimpleNamespace(writer=SimpleNamespace(language=request.param)))
    monkeypatch.setattr(windows, "say_in_bar", lambda _shell, line: bar.append(line))
    monkeypatch.setattr(windows, "youtube_arrivals", lambda _shell: arrived.append)
    monkeypatch.setattr(downloader, "fetch_links",
                        lambda _shell, urls, language, said, ended: fetched.append((urls, language, said, ended)))
    return SimpleNamespace(shell=shell, bar=bar, arrived=arrived, fetched=fetched, released=released,
                           language=request.param, release=lambda: released.append(True))


def test_a_run_downloads_in_the_libraries_language_and_brings_its_transcripts_into_new_arrivals(window_run):
    w = window_run
    youtube.run(w.shell, LINKS, w.release)
    [(urls, language, said, ended)] = w.fetched
    assert urls == LINKS and language == w.language and isinstance(said, youtube.BarLines)
    assert w.bar == [youtube.STARTED.format(n=2)] and w.released == [], "held while it runs"
    ended(["x [dQw4w9WgXcQ].txt"], [])
    assert w.arrived == [["x [dQw4w9WgXcQ].txt"]] and w.released == [True]
    assert youtube.NONE_NEW not in w.bar


def test_a_run_with_nothing_new_says_so_and_one_with_a_problem_says_that_instead(window_run):
    w = window_run
    youtube.run(w.shell, LINKS, w.release)
    youtube.run(w.shell, LINKS, w.release)
    w.fetched[0][3]([], [])
    w.fetched[1][3]([], ["YouTube couldn't be reached: check your internet connection"])
    assert w.bar[2:] == [youtube.NONE_NEW, "YouTube couldn't be reached: check your internet connection"]
    assert w.arrived == [] and w.released == [True, True]


def test_transcripts_whose_library_switched_meanwhile_say_where_they_wait(window_run, monkeypatch):
    from app.qt import strings, windows

    def arrivals(_shell):
        def complete(_paths):
            raise RuntimeError(strings.YT_OTHER_LIBRARY)
        return complete
    monkeypatch.setattr(windows, "youtube_arrivals", arrivals)
    w = window_run
    youtube.run(w.shell, LINKS, w.release)
    w.fetched[0][3](["x [dQw4w9WgXcQ].txt"], [])
    assert w.bar[-1] == strings.YT_OTHER_LIBRARY and w.released == [True]


def test_a_downloader_that_fails_to_start_lets_the_links_go_and_the_app_goes_on(window_run, monkeypatch):
    import modules.youtube_downloader as downloader

    def broken(*_a):
        raise RuntimeError("yt-dlp's folder is gone")
    monkeypatch.setattr(downloader, "fetch_links", broken)
    w = window_run
    youtube.run(w.shell, LINKS, w.release)
    assert w.released == [True]
