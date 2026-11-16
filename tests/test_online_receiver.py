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
    assert code == 200 and got == {"app": "surasura", "version": "3.0.0", "contract": 3, "languages": ["ja", "zh"]}
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


def test_the_token_is_made_once_and_kept_outside_settings_json():
    """A credential never goes in settings.json (it ships inside the release, and leaves with every export): the token
    is made once in the persistent user data folder, and read back the same."""
    from app import settings_manager
    assert rx.read_token() is None
    token = rx.kept_token()
    assert rx.kept_token() == token == rx.read_token() and len(token) >= 32
    assert "persistent_root" in rx.token_path()
    assert not [k for k in settings_manager.DEFAULT_SETTINGS if "token" in k]


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


# --- v2: mining after the fact (`app/connect/browser.py`, `runner._browser_clips`) ----------------------------------- #
CUES = [(700.0, 703.5, "雨の日の散歩で見つけた"), (705.29, 708.84, "小さな発見を話そう"), (709.0, 711.0, "朝ごはんを五分で作る"),
        (912.0, 915.5, "古本屋めぐりは楽しい")]
WEB = {"site": "netflix", "url": "https://www.netflix.com/watch/81234567", "video_id": "81234567"}


def _words():
    """Two words on 小さな発見を話そう (one card each, the same line), one on 古本屋めぐり expanded to the line before."""
    return [{"word": "発見", "reading": "はっけん", "line_start": 705.29, "line_expansion": [0, 0]},
            {"word": "話す", "reading": "はなす", "line_start": 705.29, "line_expansion": [0, 0]},
            {"word": "古本屋", "reading": "ふるほんや", "line_start": 912.0, "line_expansion": [1, 0]}]


def _handed(root, job=412):
    from app.connect import browser
    lines, _index = browser.lines_for(_words(), CUES)
    browser.hand_off(job, WEB, "雲の上の郵便屋さん S01E03", lines, root)
    return lines


def test_a_jobs_lines_are_its_words_lines_once_each_widened_as_their_cards_are(tmp_path):
    from app.connect import browser
    lines = _handed(str(tmp_path))
    assert [(ln["n"], ln["start"], ln["end"]) for ln in lines] == [(0, 705.29, 708.84), (1, 709.0, 915.5)]
    assert lines[1]["text"] == "朝ごはんを五分で作る 古本屋めぐりは楽しい"
    assert browser.state(412, str(tmp_path)) == "waiting"


def test_the_listener_lists_the_waiting_lines_takes_clips_whole_and_404s_what_doesnt_wait(tmp_path, monkeypatch):
    root = str(tmp_path)
    _handed(root)
    receiver = rx.Receiver(lambda: TOKEN, lambda sub: (True, 1), port=0, clips=root)
    assert receiver.start()
    try:
        assert _ask(receiver, "GET", "/v1/jobs")[0] == 401, "the token, as v1"
        token = {rx.TOKEN_HEADER: TOKEN}
        code, got, _h = _ask(receiver, "GET", "/v1/jobs", headers=token)
        assert code == 200 and [j["job"] for j in got["jobs"]] == [412]
        assert got["jobs"][0]["lines"] == [{"n": 0, "start": 705.29, "end": 708.84},
                                           {"n": 1, "start": 709.0, "end": 915.5}]
        assert got["jobs"][0]["pad_before"] == 1.0 and got["jobs"][0]["url"] == WEB["url"]
        clip = dict(token, **{"Content-Type": "video/webm", "X-Clip-Start": "704.29", "X-Clip-End": "709.84"})
        page = dict(clip, Origin="https://www.netflix.com")
        assert _ask(receiver, "POST", "/v1/jobs/412/clips/0", b"webm", page)[0] == 403, "never a web page"
        assert _ask(receiver, "POST", "/v1/jobs/412/clips/0", b"\x1aE\xdf\xa3webm", clip)[0] == 200
        assert not [p for p in os.listdir(os.path.join(root, "b412")) if p.endswith(".part")], "renamed whole"
        assert [ln["n"] for ln in _ask(receiver, "GET", "/v1/jobs", headers=token)[1]["jobs"][0]["lines"]] == [1]
        assert _ask(receiver, "POST", "/v1/jobs/412/clips/7", b"webm", clip)[0] == 404, "no such line"
        assert _ask(receiver, "POST", "/v1/jobs/999/clips/0", b"webm", clip)[0] == 404, "no such job"
        bad = dict(clip, **{"X-Clip-Start": "abc"})
        assert _ask(receiver, "POST", "/v1/jobs/412/clips/1", b"webm", bad)[0] == 400
        monkeypatch.setattr(rx, "MAX_CLIP", 8)
        assert _ask(receiver, "POST", "/v1/jobs/412/clips/1", b"x" * 64, clip)[0] == 413
        done = dict(token, **{"Content-Type": "application/json"})
        assert _ask(receiver, "POST", "/v1/jobs/412/done", {"failed": [{"n": 1, "why": "seek failed"}]}, done)[0] == 200
        assert _ask(receiver, "GET", "/v1/jobs", headers=token)[1]["jobs"] == [], "done: no longer listed"
        assert _ask(receiver, "POST", "/v1/jobs/412/clips/1", b"webm", clip)[0] == 404, "a clip after done"
        assert _ask(receiver, "POST", "/v1/jobs/412/done", {"failed": []}, done)[0] == 404
    finally:
        receiver.stop()


class _Ledger:
    def __init__(self):
        self.needs, self.states = [], []

    def need(self, lang, kind, say, item_id=None, job_id=None, **_kw):
        self.needs.append((kind, say))
        return True

    def set_state(self, jid, state, **kw):
        self.states.append((state, kw))


class _Steps:
    def title(self, lang, job):
        return "雲の上の郵便屋さん"


def _picked(srt):
    return {"online": "netflix", "url": WEB["url"], "video": srt, "words": _words(),
            "names": ["Processed", "雲の上の郵便屋さん S01E03 [netflix-81234567]"]}


def _srt():
    from app.connect import browser
    here = browser.place(412)
    os.makedirs(here, exist_ok=True)
    path = os.path.join(here, browser.SUBTITLE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(browser.srt_of(CUES))
    return path


def test_connect_hands_the_lines_off_and_waits_for_the_browser_with_plain_words():
    from app.connect import browser, runner
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    with pytest.raises(runner.Wait) as w:
        runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt()))
    assert w.value.reason == runner.BROWSER_WAIT and w.value.resume == "mining" and w.value.look
    handed = browser.waiting()
    assert handed[0]["job"] == 412 and handed[0]["video_id"] == "81234567"
    assert handed[0]["title"] == "雲の上の郵便屋さん S01E03"
    with pytest.raises(runner.Wait):            # looked at again: still waiting, nothing handed twice
        runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt()))
    assert not ledger.needs


def test_once_done_each_clip_is_a_video_of_its_own_and_a_lost_line_is_said_plainly():
    from app.connect import browser, runner
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    picked = _picked(_srt())
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert browser.keep_clip(412, 0, b"\x1aE\xdf\xa3", 704.29, 709.84)
    assert browser.finish(412, [{"n": 1, "why": "seek failed"}])
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert [w["word"] for w in got["words"]] == ["発見", "話す"] and {w["clip"] for w in got["words"]} == {0}
    clip = got["clips"]["0"]
    assert clip["shift"] == 704.29 and clip["video"].endswith("clip-0.webm")
    assert browser.read_srt(clip["subtitle"]) == [(1.0, 4.55, "小さな発見を話そう"), (4.71, 5.55, "朝ごはんを五分で作る")], \
        "its lines in clip time"
    (kind, say), = ledger.needs
    assert kind == runner.BROWSER_LINE
    assert say == "雲の上の郵便屋さん: the line at 11:49 (「朝ごはんを五分で作る 古本屋めぐりは楽しい」) wasn't recorded in " \
                  "the browser (seek failed). Mine it to ask again."


def test_no_clip_at_all_ends_the_job_with_words_to_ask_again():
    from app.connect import browser, runner
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    picked = _picked(_srt())
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    browser.finish(412, [{"n": 0, "why": "the tab was closed"}, {"n": 1, "why": "the tab was closed"}])
    with pytest.raises(runner._Finished):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked, record=False)
    assert ledger.states[-1][0] == "skipped" and ledger.states[-1][1]["reason"] == runner.BROWSER_NONE
    assert len(ledger.needs) == 2 and not os.path.exists(browser.place(412)), "its folder gone"


def test_anki_miner_gets_one_episode_a_clip_with_the_lines_start_in_clip_time(monkeypatch):
    """`Steps.mine`: a run a clip — its webm as the video, its own .srt, offset 0, the words' line start moved into clip
    time; the cards' Source still names the transcript (`names`). The outcomes come back by word."""
    from app.connect import runner
    sent = []

    def one(self, lang, job, picked, words, attempt):
        sent.append((picked["video"], picked["subtitle"], picked["offset"], picked["names"],
                     [(w["word"], w["line_start"]) for w in words]))
        return {"outcomes": [dict(w, outcome="made") for w in words], "app": "3.12.0", "doubt": False}
    monkeypatch.setattr(runner.Steps, "_mine_one", one)
    words = [dict(w, clip=0) for w in _words()[:2]] + [dict(_words()[2], clip=1)]
    picked = {"names": ["Processed", "雲の上の郵便屋さん S01E03 [netflix-81234567]"], "words": words,
              "clips": {"0": {"video": "c0.webm", "subtitle": "c0.srt", "shift": 704.29},
                        "1": {"video": "c1.webm", "subtitle": "c1.srt", "shift": 708.0}}}
    got = runner.Steps.mine(runner.Steps.__new__(runner.Steps), "ja", {"id": 412}, picked, words, 1)
    assert sent == [("c0.webm", "c0.srt", 0.0, picked["names"], [("発見", 1.0), ("話す", 1.0)]),
                    ("c1.webm", "c1.srt", 0.0, picked["names"], [("古本屋", 204.0)])]
    assert [o["outcome"] for o in got["outcomes"]] == ["made"] * 3


def test_a_netflix_episode_is_picked_from_its_own_cues_never_downloaded(library):
    """`Steps.download` for Netflix / Disney+: no fetch, no YouTube tick — the transcript's cues as the subtitle the
    words are picked from (its sidecar's start and end)."""
    from app.connect import browser, runner
    store, writer, language = library
    _added, item = rx.take_in(writer, rx.subtitle(json.dumps(_sub(language)).encode()))
    steps = runner.Steps.__new__(runner.Steps)
    steps._settings = lambda lang: pytest.fail("nothing is read for a browser site")
    steps._open = lambda lang: ls.open_store(lang, *roots(lang))
    srt, again = steps.download(language, {"id": 9, "item_id": item}, {"site": "netflix", "url": WEB["url"]})
    assert srt == again and browser.read_srt(srt)[0] == (12.34, 15.02, f"{names(language)[3]}{names(language)[4]}")


# --- v3: YouTube links to the transcript downloader ------------------------------------------------------------------ #
def test_youtube_links_go_to_the_downloader_only_as_its_window_would_take_them(tmp_path):
    """`POST /v1/youtube`: YouTube's own https links only (400 else), the token as v1, and the window's answer passed
    on — 409 with its words when the downloader is off or its tick not given, `queued` when it runs them."""
    got, answer = [], {"refuse": "Surasura's YouTube downloader needs your OK first"}

    def youtube(urls):
        if answer["refuse"]:
            raise rx.Refused(answer["refuse"])
        got.append(urls)
        return len(urls)
    receiver = rx.Receiver(lambda: TOKEN, lambda sub: (True, 1), port=0, youtube=youtube)
    assert receiver.start()
    try:
        headers = {rx.TOKEN_HEADER: TOKEN, "Content-Type": "application/json"}
        links = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/playlist?list=PLjfPBTv1Zr1J8"]
        body = {"schema": 1, "urls": links}
        assert _ask(receiver, "POST", "/v1/youtube", body)[0] == 401
        code, said, _h = _ask(receiver, "POST", "/v1/youtube", body, headers)
        assert code == 409 and said["why"] == answer["refuse"] and got == []
        answer["refuse"] = None
        code, said, _h = _ask(receiver, "POST", "/v1/youtube", body, headers)
        assert code == 200 and said == {"ok": True, "queued": 2} and got == [links]
        for bad in (["https://evil.example/watch?v=x"], ["http://www.youtube.com/watch?v=x"], [], ["x"] * 51):
            assert _ask(receiver, "POST", "/v1/youtube", {"schema": 1, "urls": bad}, headers)[0] == 400
    finally:
        receiver.stop()
    bare = rx.Receiver(lambda: TOKEN, lambda sub: (True, 1), port=0)       # no downloader here: 409, never a run
    assert bare.start()
    try:
        assert _ask(bare, "POST", "/v1/youtube", body, headers)[0] == 409
    finally:
        bare.stop()


def test_the_window_never_runs_links_past_the_downloaders_switch_or_its_risk_tick():
    from app.qt import strings, windows
    assert windows.youtube_refused({}) == strings.EXT_YT_OFF
    assert windows.youtube_refused({"enable_youtube_transcripts": True}) == strings.EXT_YT_TICK
    assert windows.youtube_refused({"enable_youtube_transcripts": True, "youtube_risk_acknowledged": "yes"}) == \
        strings.EXT_YT_TICK
    assert windows.youtube_refused({"enable_youtube_transcripts": True, "youtube_risk_acknowledged": True}) is None


# --- a pick again after the hand-off (the user's jobs 461–464, 2026-11-15) ------------------------------------------- #
# 俺のこと、なんか言ってた？ S01E08: five lines out of time order, as a pick ranks them
EP8 = [(129.708, 131.458, "〈貴様の頬が裂けるまで〉"), (265.75, 268.25, "「リア王」と初日 一緒だなって"),
       (337.042, 339.917, "もともと こちらの大物俳優役は どなたが？"), (1241.792, 1246.625, "〈稲妻よ 電光石火の硫黄の火〉"),
       (2044.292, 2046.667, "ワレ コラ！ワシを誰や思っとんねん！"), (2212.917, 2215.375, "王冠をかぶれば 王になれる")]


def _ep8_word(word, start):
    return {"word": word, "reading": word, "line_start": start, "line_expansion": [0, 0]}


def _ep8_srt(job):
    from app.connect import browser
    here = browser.place(job)
    os.makedirs(here, exist_ok=True)
    path = os.path.join(here, browser.SUBTITLE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(browser.srt_of(EP8))
    return path


def _record_all(receiver, job, pad=0.7):
    """The extension's round: `GET /v1/jobs`, then a clip for each line still missing one (`pad` around it)."""
    headers = {rx.TOKEN_HEADER: TOKEN}
    jobs = _ask(receiver, "GET", "/v1/jobs", headers=headers)[1]["jobs"]
    for line in next(j for j in jobs if j["job"] == job)["lines"]:
        clip = dict(headers, **{"Content-Type": "video/webm", "X-Clip-Start": str(line["start"] - pad),
                                "X-Clip-End": str(line["end"] + pad)})
        assert _ask(receiver, "POST", f"/v1/jobs/{job}/clips/{line['n']}", b"webm", clip)[0] == 200


def test_a_pick_again_after_the_hand_off_never_gives_a_word_another_lines_clip(monkeypatch):
    """The user's jobs 461–464: lines handed off in a pick's order, clips posted in two rounds, a pick again meanwhile
    ranking other words first. Each word still gets its own line's clip (matched by the line's place, never its
    order), the new pick's extra line is asked for, and every run Anki Miner gets has its line inside its clip —
    never the −970.425 s that stopped the run file."""
    from app.connect import browser, runner
    job, ledger = {"id": 464, "item_id": 7}, _Ledger()
    srt = _ep8_srt(464)
    first = [_ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292), _ep8_word("王冠", 2212.917),
             _ep8_word("初日", 265.75), _ep8_word("稲妻", 1241.792)]
    picked = dict(_picked(srt), words=first)
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    receiver = rx.Receiver(lambda: TOKEN, lambda sub: (True, 1), port=0)
    assert receiver.start()
    try:
        headers = {rx.TOKEN_HEADER: TOKEN}
        two = [ln for ln in _ask(receiver, "GET", "/v1/jobs", headers=headers)[1]["jobs"][0]["lines"]][:2]
        for line in two:                                    # round one: two clips, then the tab is busy
            clip = dict(headers, **{"Content-Type": "video/webm", "X-Clip-Start": str(line["start"] - 0.7),
                                    "X-Clip-End": str(line["end"] + 0.7)})
            assert _ask(receiver, "POST", f"/v1/jobs/464/clips/{line['n']}", b"webm", clip)[0] == 200
        # a pick again meanwhile: other words first, one line more (貴様, 129.708), 王冠 gone
        again = [_ep8_word("稲妻", 1241.792), _ep8_word("貴様", 129.708), _ep8_word("初日", 265.75),
                 _ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292)]
        picked = dict(picked, words=again)
        with pytest.raises(runner.Wait):                    # the new line is added, never renumbering the others
            runner._browser_clips(_Steps(), ledger, "ja", job, picked)
        assert browser.handed(464)[(129.708, 131.458)] == 5
        _record_all(receiver, 464)                          # round two: the rest, after asking again
        assert _ask(receiver, "POST", "/v1/jobs/464/done", {"failed": []},
                    dict(headers, **{"Content-Type": "application/json"}))[0] == 200
    finally:
        receiver.stop()
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert not ledger.needs
    sent = []
    monkeypatch.setattr(runner.Steps, "_mine_one", lambda self, lang, j, p, ws, attempt: (
        sent.append((p["video"], [w["line_start"] for w in ws])),
        {"outcomes": [dict(w, outcome="made") for w in ws], "app": "3.12.0", "doubt": False})[1])
    runner.Steps.mine(runner.Steps.__new__(runner.Steps), "ja", job, got, got["words"], 1)
    assert len(sent) == 5
    for video, starts in sent:
        n = int(os.path.basename(video)[len("clip-"):-len(".webm")])
        length = browser.clip(464, n)[1]["end"] - browser.clip(464, n)[1]["start"]
        assert all(0 <= s <= length for s in starts), (video, starts)
    assert {w["word"]: round(w["line_start"] - got["clips"][str(w["clip"])]["shift"], 3) for w in got["words"]} == \
        {w: 0.7 for w in ("稲妻", "貴様", "初日", "大物", "ワシ")}


def test_a_job_saved_with_clips_matched_by_order_is_matched_again_from_its_folder():
    """A job stuck before this rule (its `clips` saved with a word on another line's clip) is worked out again at its
    next look while its folder is there: no re-recording, the clips on disk matched by their line's place."""
    from app.connect import browser, runner
    job, ledger = {"id": 461, "item_id": 7}, _Ledger()
    srt = _ep8_srt(461)
    words = [_ep8_word("王冠", 2212.917), _ep8_word("稲妻", 1241.792)]
    lines, _index = browser.lines_for(words, EP8)
    browser.hand_off(461, WEB, "俺のこと、なんか言ってた？ S01E08", lines)
    for n, (start, end) in ((0, (2212.216667, 2216.448667)), (1, (1241.083667, 1247.662333))):
        assert browser.keep_clip(461, n, b"webm", start, end)
    browser.finish(461, [])
    stuck = dict(_picked(srt), words=[dict(words[0], clip=0), dict(words[1], clip=0)],      # 稲妻 on 王冠's clip
                 clips={"0": {"video": "x", "subtitle": "y", "shift": 2212.216667}})
    got = runner._browser_clips(_Steps(), ledger, "ja", job, stuck)
    assert {w["word"]: w["clip"] for w in got["words"]} == {"王冠": 0, "稲妻": 1}
    assert got["clips"]["1"]["shift"] == 1241.083667


def test_a_clip_that_doesnt_hold_its_line_is_a_lost_line_never_sent():
    from app.connect import browser, runner
    job, ledger = {"id": 463, "item_id": 7}, _Ledger()
    srt = _ep8_srt(463)
    picked = dict(_picked(srt), words=[_ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292)])
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert browser.keep_clip(463, 0, b"webm", 336.3, 340.9)
    assert browser.keep_clip(463, 1, b"webm", 2212.2, 2216.4)          # another line's moment
    browser.finish(463, [])
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert [w["word"] for w in got["words"]] == ["大物"]
    (kind, say), = ledger.needs
    assert "34:04" in say and "its clip doesn't hold the line" in say


# --- a job made again for the same episode (Mattias, トークサバイバー Ep 3 / 6, 2026-11-16) ---------------------------- #
class _JobsLedger(_Ledger):
    """The ledger as `_earlier_jobs` reads it: the episode's jobs."""

    def __init__(self, jobs):
        import sqlite3
        super().__init__()
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE jobs (id INTEGER, language TEXT, item_id INTEGER)")
        self.conn.executemany("INSERT INTO jobs VALUES (?, 'ja', ?)", jobs)


def _recorded(job, words, clips=None, done=True):
    """An earlier job's folder as the extension left it: its lines, a clip for each (or `clips`: {n: (start, end)})."""
    from app.connect import browser
    _ep8_srt(job)
    lines, _index = browser.lines_for(words, EP8)
    browser.hand_off(job, WEB, "トークサバイバー！ S01E03", lines)
    for ln in lines:
        start, end = (clips or {}).get(ln["n"], (ln["start"] - 0.7, ln["end"] + 0.7))
        if start is not None:
            assert browser.keep_clip(job, ln["n"], b"webm", start, end)
    if done:
        browser.finish(job, [])


def test_a_job_made_again_takes_the_earlier_jobs_clips_and_goes_straight_to_its_cards():
    """Jobs 470 → 476: the earlier job was dropped (the list reordered) after its clips came in; the new one, in
    another order, takes them over by their line's place and needs no recording."""
    from app.connect import browser, runner
    words = [_ep8_word("大物", 337.042), _ep8_word("稲妻", 1241.792), _ep8_word("初日", 265.75)]
    _recorded(470, words)
    ledger, job = _JobsLedger([(470, 2900), (476, 2900), (475, 2905)]), {"id": 476, "item_id": 2900}
    picked = dict(_picked(_ep8_srt(476)), words=list(reversed(words)))
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert sorted(w["word"] for w in got["words"]) == ["初日", "大物", "稲妻"] and not ledger.needs
    for w in got["words"]:
        assert 0 <= w["line_start"] - got["clips"][str(w["clip"])]["shift"] <= 1.0
    assert browser.waiting() == [], "nothing for the extension to record"


def test_only_the_lines_no_earlier_job_holds_wait_for_recording():
    """An earlier job with one clip that doesn't hold its line (another moment) and one line never recorded: only those
    two wait; the clip that holds its line is taken over. An earlier folder still waiting is closed: its job is
    gone, so the extension is never asked for it again."""
    from app.connect import browser, runner
    words = [_ep8_word("大物", 337.042), _ep8_word("稲妻", 1241.792), _ep8_word("初日", 265.75)]
    _recorded(473, words, clips={1: (2212.2, 2216.4), 2: (None, None)}, done=False)
    ledger, job = _JobsLedger([(473, 2903), (477, 2903)]), {"id": 477, "item_id": 2903}
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, dict(_picked(_ep8_srt(477)), words=words))
    (waits,) = browser.waiting()
    assert waits["job"] == 477 and [ln["start"] for ln in waits["lines"]] == [1241.792, 265.75]


def test_a_wait_for_the_browser_says_so_on_its_row():
    from app.connect import feed, runner
    from app.services import view_rows as vr
    item = feed.Item(kind=feed.WAITING, words=feed.WORDS[feed.WAITING], tip=runner.BROWSER_WAIT, job=476, made=0,
                     total=0)
    st = vr._connected(vr.Status("mine", vr.STRINGS["mine"], "", "ok"), item, "video", online="netflix")
    assert (st.kind, st.label, st.tip) == ("waiting", "Record in browser", runner.BROWSER_WAIT)


def test_a_job_already_waiting_when_the_earlier_clips_were_left_takes_them_at_its_next_look():
    """Mattias's 476 / 477: made again (and handed off, waiting) before this rule — its next look takes the earlier
    job's clips over and goes on to its cards."""
    from app.connect import browser, runner
    words = [_ep8_word("大物", 337.042), _ep8_word("稲妻", 1241.792)]
    _recorded(473, words)
    lines, _index = browser.lines_for(list(reversed(words)), EP8)
    browser.hand_off(477, WEB, "トークサバイバー！ S01E06", lines)
    ledger, job = _JobsLedger([(473, 2903), (477, 2903)]), {"id": 477, "item_id": 2903}
    got = runner._browser_clips(_Steps(), ledger, "ja", job, dict(_picked(_ep8_srt(477)), words=words))
    assert sorted(w["word"] for w in got["words"]) == ["大物", "稲妻"] and browser.waiting() == []
