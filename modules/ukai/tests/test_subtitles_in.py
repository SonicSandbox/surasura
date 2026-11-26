# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜飼 Ukai's subtitles in, through the one door (Ukai SPEC §6 U-S2; ported from #474's
`tests/test_online_receiver.py`, by mattias): Netflix-X's run again — a simulated loopback POST with the real JSON
shape, real lines from Test Resources — on the real door's Ukai class with a real pairing and a real library store.

What a wrong answer would cost a learner: a subtitle taken in without the learner's Allow (any extension posting into
their library); an episode sent again after a restart becoming a second item; a subtitle in a language they don't
study kept (U3); an episode filed under its own title instead of its show, its number lost; ▶ opening nothing.
"""
import http.client
import json
import os
import re
import socket
import threading

import pytest

from app import door, library_store as ls, path_utils
from modules import ukai
from modules.ukai import subtitles
from tests.test_library_store_support import LANGUAGES, migrated, names, roots

ORIGIN = "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb"
TOKEN = "U" * 32
SRT = {"ja": "placed_episode.srt", "zh": "night_market.srt"}
RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))), "tests", "Test Resources")


def _cues(language):
    """The episode's cues as Ukai sends them ([start s, end s, text]), from the language's real .srt."""
    with open(os.path.join(RESOURCES, language, SRT[language]), encoding="utf-8-sig") as f:
        blocks = re.split(r"\n\s*\n", f.read().strip())
    out = []
    for block in blocks:
        lines = block.strip().splitlines()
        a, b = (sum(float(x) * m for x, m in zip(t.replace(",", ".").split(":"), (3600, 60, 1)))
                for t in lines[1].split(" --> "))
        out.append([round(a, 3), round(b, 3), " ".join(lines[2:])])
    return out


def _body(language, video="80000003", site="netflix", film=False):
    w = names(language)
    body = {"schema": 1, "site": site, "video_id": video, "url": f"https://www.netflix.com/watch/{video}",
            "language": language, "title": w[2], "cues": _cues(language)}
    if not film:
        body["show"] = {"title": w[1], "season": 1, "episode": 3}
    return body


class _Opener:
    """The window's `StoreOpener` as `take_in` uses it: a handle of the calling thread's own (the door's)."""

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
    """The window's writer as `take_in` uses it: registers at once, through the caller's own handle."""

    def __init__(self, language):
        self.opener, self.language, self.registered = _Opener(language), language, []

    def register(self, paths, pairing, rules=None, label=None, done=None):
        for p in paths:
            self.opener.handle().register(p, pairing, rules=rules)
            self.registered.append(p)
        self.opener.close()
        done(1, 0, 0)
        return 1


def _free_port():
    with socket.socket() as s:
        s.bind((door.HOST, 0))
        return s.getsockname()[1]


class _Pairing:
    def __init__(self):
        self.kept = (ORIGIN, TOKEN)

    def __call__(self):
        return self.kept


@pytest.fixture(params=LANGUAGES)
def run(request, tmp_path, monkeypatch):
    """The door with Ukai's class (its pairing a stand-in; the real one is `ukai_pairing`'s, tested in core) and the
    module's routes, on a real library of the language."""
    language = request.param
    store = migrated(language)
    writer = _Writer(language)
    settings = {"covers_download": False, "placing_rules": {}}
    pairing = _Pairing()
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    ext = door.Extension(ukai.routes(writer=lambda: writer, settings=lambda: settings), pairing)
    d = door.Door({}, str(tmp_path / "results"), extension=ext).start()
    yield d, store, writer, language, pairing, settings
    d.stop()
    store.close()


def _ask(d, method, path, body=None, token=TOKEN, origin=ORIGIN):
    conn = http.client.HTTPConnection(door.HOST, d.ext_port, timeout=30)
    headers = {"Host": f"{door.HOST}:{d.ext_port}", "Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    if token is not None:
        headers[door.EXT_TOKEN_HEADER] = token
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    conn.request(method, path, body=data, headers=headers)
    r = conn.getresponse()
    got = json.loads(r.read().decode("utf-8"))
    conn.close()
    return r.status, got


def _post(d, body, **kw):
    return _ask(d, "POST", "/v1/online-subtitle", body, **kw)


def test_an_episode_comes_in_once_titled_by_its_show_and_never_twice(run):
    """Netflix-X's run, through the door: added as one item of its show (season and episode kept), an online item of
    the site whose ▶ is its page, the transcript in the downloader's shape; the same episode again is that item."""
    d, store, writer, language, _p, _s = run
    status, got = _post(d, _body(language))
    assert status == 200 and got["ok"] and got["added"] is True
    item = store.item(got["item"])
    assert item["source_type"] == "netflix" and item["rel_path"].endswith("[netflix-80000003].txt")
    title = store.conn.execute("SELECT title FROM works WHERE id = ?", (item["work_id"],)).fetchone()[0]
    assert title == names(language)[1], "titled by its show, never by the episode's own title"
    pairing = json.loads(store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ?",
                                            (got["item"],)).fetchone()[0])
    assert pairing["show"]["episode"] == 3 and pairing["content_key"] == "netflix:80000003"
    from app.services import play
    assert play.online_link(language, item["rel_path"], pairing) == ("https://www.netflix.com/watch/80000003", None)
    again = _post(d, _body(language))
    assert again == (200, {"ok": True, "added": False, "item": got["item"]}) and len(writer.registered) == 1


def test_the_same_episode_sent_twice_at_once_is_still_one_item(run):
    d, store, writer, language, _p, _s = run
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(_post(d, _body(language)))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(a[1]["added"] for a in answers) == [False, True] and len({a[1]["item"] for a in answers}) == 1
    assert len(writer.registered) == 1


@pytest.mark.parametrize("token, origin", [(None, ORIGIN), ("W" * 32, ORIGIN), (TOKEN, "chrome-extension://" + "b" * 32),
                                           (TOKEN, "https://www.netflix.com"), (TOKEN, None)])
def test_without_the_pairing_nothing_comes_in(run, token, origin):
    d, _store, writer, language, _p, _s = run
    status, got = _post(d, _body(language), token=token, origin=origin)
    assert status in (401, 403) and got["ok"] is False and writer.registered == []


def test_forgotten_refuses_at_once(run):
    d, _store, writer, language, pairing, _s = run
    pairing.kept = None
    assert _post(d, _body(language))[0] == 401 and writer.registered == []


def test_a_language_with_no_library_is_refused_and_one_not_open_waits(run):
    """U3: Ukai sends only a library's language — a subtitle in a language the learner has no library for is
    refused for good (409: Ukai drops it); one whose library isn't the open one waits (503: Ukai sends it again)."""
    d, _store, writer, language, _p, _s = run
    other = "zh" if language == "ja" else "ja"
    assert ukai.libraries() == [language]
    status, got = _post(d, _body(other))
    assert (status, got["kind"]) == (409, "refused") and writer.registered == []
    migrated(other).close()                                 # now the learner has that library too, not open
    status, got = _post(d, _body(other))
    assert (status, got["kind"]) == (503, "busy") and writer.registered == []


def test_hello_says_the_libraries_languages_and_covers_to_any_extension(run):
    d, _store, _writer, language, _p, settings = run
    status, got = _ask(d, "GET", "/v1/hello", token=None, origin=None)
    assert status == 200 and got["app"] == "surasura" and got["languages"] == [language] and got["covers"] is False
    assert got["contract"] == ukai.CONTRACT and got["door"] == door.VERSION
    settings["covers_download"] = True
    assert _ask(d, "GET", "/v1/hello", token=None, origin=None)[1]["covers"] is True


@pytest.mark.parametrize("change, why", [
    (lambda b: b.update(schema=2), "schema"), (lambda b: b.update(site="hulu"), "site"),
    (lambda b: b.update(video_id="../../etc"), "video_id"), (lambda b: b.update(url="javascript:alert(1)"), "url"),
    (lambda b: b.update(language="ko"), "language"), (lambda b: b.update(cues=[]), "cues"),
    (lambda b: b.update(cues=[[3.0, 1.0, "逆"]]), "ends before"), (lambda b: b.update(show={"season": 1}), "show"),
])
def test_a_bad_body_is_told_why_and_adds_nothing(run, change, why):
    d, _store, writer, language, _p, _s = run
    body = _body(language)
    change(body)
    status, got = _post(d, body)
    assert (status, got["kind"]) == (400, "body") and why in got["why"] and writer.registered == []


def test_the_names_type_is_the_site_and_never_a_bare_bracket():
    assert path_utils.infer_source_type("Processed/星の旅 S01E03 [netflix-81234567].txt") == "netflix"
    assert path_utils.infer_source_type("Processed/夜市 [disneyplus-5f2c1e7a-6b9d].txt") == "disneyplus"
    assert path_utils.infer_source_type("Processed/星の旅 [81234567].txt") == "text"
    assert subtitles.content_key({"site": "netflix", "video_id": "81234567"}) == "netflix:81234567"
