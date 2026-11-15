"""The browser extension's subtitles (Netflix, Disney+; `app/online_receiver.py`): the listener the extension posts to,
and the library item a subtitle becomes.

What a wrong answer would cost a learner: a web page they visit posting text into their library (or reading whether
Surasura runs); a second item for an episode the extension sent again after a restart; an episode filed under its own
title instead of its show, its number lost; ▶ opening nothing; or Connect trying to download a DRM'd video and saying
*No video* for ever.

The listener is the real one on a free loopback port (`port=0`); the library is a real store (per-test
SURASURA_TEST_ROOT), reached through a stand-in for the window's writer that registers at once. Real Japanese and
Chinese names from the test texts.
"""
import http.client
import json
import os
import threading

import pytest

from app import library_store as ls
from app import online_receiver as rx
from app import path_utils
from tests.test_library_store_support import LANGUAGES, migrated, names, roots

TOKEN = "kumo-no-ue-no-token"


def _sub(language, video="81234567", site="netflix", film=False, episode=3):
    w = names(language)
    body = {"schema": 1, "site": site, "video_id": video, "url": f"https://www.netflix.com/watch/{video}",
            "language": language, "title": w[2],
            "cues": [[12.34, 15.02, f"{w[3]}{w[4]}"], [15.5, 18.0, f"{w[5]}\n{w[6]}"], [20.0, 21.0, "  "]]}
    if not film:
        body["show"] = {"title": w[1], "season": 1, "episode": episode}
    return body


class _Opener:
    """The window's `StoreOpener` as `take_in` uses it: a handle of the calling thread's own (the listener's)."""

    def __init__(self, language):
        self.language, (self.data_dir, self.user_files_dir) = language, roots(language)
        self._local = threading.local()

    def handle(self):
        if getattr(self._local, "store", None) is None:
            self._local.store = ls.open_store(self.language, self.data_dir, self.user_files_dir)
        return self._local.store

    def close(self):
        store, self._local.store = getattr(self._local, "store", None), None
        if store is not None:
            store.close()


class _Writer:
    """The window's writer as `take_in` uses it: registers at once, on the caller's thread, through its own handle."""

    def __init__(self, language):
        self.opener, self.language, self.registered = _Opener(language), language, []

    def register(self, paths, pairing, rules=None, label=None, done=None):
        for p in paths:
            self.opener.handle().register(p, pairing, rules=rules)
            self.registered.append(p)
        self.opener.close()
        done(1, 0, 0)
        return 1


@pytest.fixture
def library(request):
    language = request.param if hasattr(request, "param") else "ja"
    store = migrated(language)
    writer = _Writer(language)
    yield store, writer, language
    store.close()


@pytest.fixture
def listening(library):
    store, writer, language = library
    receiver = rx.Receiver(lambda: TOKEN, lambda sub: rx.take_in(writer, sub), version="3.0.0", port=0)
    assert receiver.start()
    yield receiver, store, writer, language
    receiver.stop()


def _ask(receiver, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(rx.HOST, receiver.port, timeout=10)
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode("utf-8")
    conn.request(method, path, body=data, headers=headers or {})
    reply = conn.getresponse()
    got = reply.read()
    conn.close()
    return reply.status, (json.loads(got) if got else None), dict(reply.getheaders())


def _title(store, item_id):
    return store.conn.execute("SELECT title FROM works WHERE id = ?", (store.item(item_id)["work_id"],)).fetchone()[0]


def _pairing(store, item_id):
    return json.loads(store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ?", (item_id,)).fetchone()[0])


def _post(receiver, body, token=TOKEN, **headers):
    if token is not None:
        headers[rx.TOKEN_HEADER] = token
    headers.setdefault("Content-Type", "application/json")
    return _ask(receiver, "POST", "/v1/online-subtitle", body, headers)


# --- the listener ---------------------------------------------------------------------------------------------------- #
def test_hello_says_who_answers_and_never_opens_the_door_to_a_web_page(listening):
    receiver = listening[0]
    code, got, headers = _ask(receiver, "GET", "/v1/hello")
    assert code == 200 and got == {"app": "surasura", "version": "3.0.0", "contract": 1, "languages": ["ja", "zh"]}
    assert not any(k.lower().startswith("access-control") for k in headers), "no CORS: a page can't read it"
    code, _got, _h = _ask(receiver, "GET", "/v1/hello", headers={"Origin": "https://evil.example"})
    assert code == 403, "a web page's script is refused, even for hello"
    code, _got, _h = _ask(receiver, "GET", "/v1/hello", headers={"Origin": "chrome-extension://abcdefghijklmnop"})
    assert code == 200, "the extension's own origin is welcome"
    assert _ask(receiver, "OPTIONS", "/v1/online-subtitle")[0] == 403, "a preflight is never answered yes"


def test_a_wrong_or_missing_token_adds_nothing(listening):
    receiver, store, writer, language = listening
    assert _post(receiver, _sub(language), token=None)[0] == 401
    assert _post(receiver, _sub(language), token="kumo-no-ue-no-tokem")[0] == 401
    unset = rx.Receiver(lambda: None, lambda sub: (True, 1), port=0)       # no token kept yet: nothing is taken
    assert unset.start()
    try:
        assert _post(unset, _sub(language), token="")[0] == 401
    finally:
        unset.stop()
    assert writer.registered == []


def test_a_post_from_a_web_page_is_refused_before_its_token_is_looked_at(listening):
    receiver, _store, writer, language = listening
    code, _got, _h = _post(receiver, _sub(language), Origin="https://www.netflix.com")
    assert code == 403 and writer.registered == []


@pytest.mark.parametrize("change, why", [
    (lambda b: b.update(schema=2), "schema"),
    (lambda b: b.update(site="hulu"), "site"),
    (lambda b: b.update(video_id="../../etc"), "video_id"),
    (lambda b: b.update(url="javascript:alert(1)"), "url"),
    (lambda b: b.update(language="ko"), "language"),
    (lambda b: b.update(cues=[]), "cues"),
    (lambda b: b.update(cues=[[3.0, 1.0, "逆"]]), "ends before"),
    (lambda b: b.update(cues=[["0:12", 1.0, "時"]]), "seconds"),
    (lambda b: b.update(show={"season": 1}), "show"),
])
def test_a_bad_body_is_told_why_and_adds_nothing(listening, change, why):
    receiver, _store, writer, language = listening
    body = _sub(language)
    change(body)
    code, got, _h = _post(receiver, body)
    assert code == 400 and got["ok"] is False and why in got["why"]
    assert _post(receiver, b"{not json")[0] == 400
    assert writer.registered == []


def test_a_body_over_the_limit_is_refused_unread(listening, monkeypatch):
    receiver, _store, writer, language = listening
    monkeypatch.setattr(rx, "MAX_BODY", 512)
    body = _sub(language)
    body["cues"] = [[float(n), n + 0.5, names(language)[n % 40] * 4] for n in range(200)]
    code, got, _h = _post(receiver, body)
    assert code == 413 and "too large" in got["why"] and writer.registered == []


def test_not_loopback_is_refused():
    assert rx._loopback("127.0.0.1") and rx._loopback("::1")
    assert not rx._loopback("192.168.1.20") and not rx._loopback("example.com")


def test_the_token_is_compared_whole():
    token = rx.new_token()
    assert len(token) >= 32 and rx.token_ok(token, token)
    assert not rx.token_ok(token[:-1], token) and not rx.token_ok(token, "") and not rx.token_ok(None, token)


# --- the item it makes ----------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("library", LANGUAGES, indirect=True)
def test_an_episode_arrives_titled_by_its_show_with_its_number_and_its_page(library):
    """The real listener, a real store: the posted episode is one item in its show's title, season and episode kept,
    an online item of the site (`source_type` netflix), its transcript the downloader's shape with every cue's start
    and end in its sidecar, ▶ its page."""
    store, writer, language = library
    receiver = rx.Receiver(lambda: TOKEN, lambda sub: rx.take_in(writer, sub), port=0)
    assert receiver.start()
    try:
        code, got, _h = _post(receiver, _sub(language))
    finally:
        receiver.stop()
    assert code == 200 and got["ok"] and got["added"] is True
    item = store.item(got["item"])
    w = names(language)
    assert item["source_type"] == "netflix"
    assert item["rel_path"].startswith("Processed/") and item["rel_path"].endswith("[netflix-81234567].txt")
    assert _title(store, got["item"]) == w[1], "titled by its show, never by the episode's own title"
    pairing = _pairing(store, got["item"])
    assert pairing["show"] == {"title": w[1], "season": 1, "episode": 3} and pairing["content_key"] == "netflix:81234567"
    path = os.path.join(writer.opener.data_dir, *item["rel_path"].split("/"))
    from app import analyzer
    with open(path, encoding="utf-8") as f:
        body = analyzer.transcript_body(f.read())
    assert body == f"{w[3]}{w[4]}\n{w[5]} {w[6]}\n", "the downloader's header; an empty cue left out"
    with open(os.path.splitext(path)[0] + path_utils.SIDECAR_SUFFIX, encoding="utf-8") as f:
        side = json.load(f)
    assert side["cues"][0] == [f"{w[3]}{w[4]}", 12.34, 15.02], "each cue's start and end, for the later mining"
    from app.services import play
    assert play.online_link(language, item["rel_path"], pairing) == ("https://www.netflix.com/watch/81234567", None)


def test_the_same_video_sent_again_is_never_a_second_item(library):
    store, writer, language = library
    added, item = rx.take_in(writer, rx.subtitle(json.dumps(_sub(language)).encode("utf-8")))
    again, same = rx.take_in(writer, rx.subtitle(json.dumps(_sub(language)).encode("utf-8")))
    assert (added, again) == (True, False) and same == item and len(writer.registered) == 1


def test_a_film_is_its_own_title_and_a_disney_episode_its_own_site(library):
    store, writer, language = library
    w = names(language)
    _a, film = rx.take_in(writer, rx.subtitle(json.dumps(_sub(language, video="80100172", film=True)).encode()))
    assert _title(store, film) == w[2]
    assert _pairing(store, film)["media_type"] == "movie"
    disney = _sub(language, video="5f2c1e7a-6b9d-4c1e-9a0b-3d2f1e0c9b8a", site="disneyplus", episode=4)
    _a, ep = rx.take_in(writer, rx.subtitle(json.dumps(disney).encode()))
    assert store.item(ep)["source_type"] == "disneyplus"


def test_another_languages_subtitle_waits_for_its_library(library):
    """The open library is the other language's: a 503 (the extension keeps it and sends it again), nothing written."""
    _store, writer, language = library
    other = "zh" if language == "ja" else "ja"
    body = _sub(language)
    body["language"] = other
    with pytest.raises(rx.Busy):
        rx.take_in(writer, rx.subtitle(json.dumps(body).encode()))
    assert writer.registered == []
    with pytest.raises(rx.Busy):
        rx.take_in(None, rx.subtitle(json.dumps(_sub(language)).encode()))


def test_the_names_type_is_the_site_and_never_a_bare_bracket():
    assert path_utils.infer_source_type("Processed/星の旅 S01E03 [netflix-81234567].txt") == "netflix"
    assert path_utils.infer_source_type("Processed/星の旅 [disneyplus-5f2c1e7a-6b9d].txt") == "disneyplus"
    assert path_utils.infer_source_type("Processed/星の旅 [81234567].txt") == "text"


# --- mining: never fetched, a quiet wait ----------------------------------------------------------------------------- #
def test_connect_sets_a_netflix_episode_aside_with_plain_words_never_a_download():
    from app.connect import anki_miner, library, online, runner
    item = {"source_type": "netflix", "rel_path": "Processed/星の旅 S01E03 [netflix-81234567].txt"}
    assert library.waits_for(item) == "browser" and online.is_online(item)
    assert anki_miner.mines("browser") is False and anki_miner.mines_now("browser") is False
    assert runner.WAIT_REASONS["browser"] == runner.BROWSER_WAIT
    assert "browser extension" in runner.BROWSER_WAIT and "No video" not in runner.BROWSER_WAIT


def test_a_download_of_a_browser_site_is_refused_before_anything_is_asked():
    """`Steps.download` (Anki Miner's fetch) is never reached for these: a Skip with the wait's words, before the
    YouTube tick or Anki Miner are looked at."""
    from app.connect import runner
    steps = runner.Steps.__new__(runner.Steps)
    steps._settings = lambda lang: pytest.fail("nothing is read for a browser site")
    with pytest.raises(runner.Skip) as e:
        steps.download("ja", {"id": 1}, {"site": "disneyplus", "url": "https://www.disneyplus.com/video/x"})
    assert e.value.why == runner.BROWSER_WAIT
