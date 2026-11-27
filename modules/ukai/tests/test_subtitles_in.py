# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜 Ukai's subtitles in, through the one door (Ukai SPEC §6 U-S2; ported from #474's
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
    # (review: an endless or huge time was a crash, 503 again at every resend; a line break in the url a forged
    # header line in the transcript)
    (lambda b: b.update(cues=[[0.0, float("inf"), "無限"]]), "seconds"),
    (lambda b: b.update(cues=[[0.0, 1e306, "大"]]), "seconds"),
    (lambda b: b.update(url=b["url"] + "\nCaptions: zh"), "url"),
    (lambda b: b.update(url="https://" + "a" * 3000), "url"),
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


def _title(store, item_id):
    return store.conn.execute("SELECT w.title FROM items i JOIN works w ON w.id = i.work_id WHERE i.id = ?",
                              (item_id,)).fetchone()[0]


def test_a_film_is_its_own_title_and_a_disney_episode_its_own_site(run):
    """(#474's, through the door.) A film (no `show`) is titled by itself, its pairing a movie; a Disney+ episode is
    Disney+'s item, its id a UUID."""
    d, store, _writer, language, _p, _s = run
    status, got = _post(d, _body(language, video="80100172", film=True))
    assert status == 200 and _title(store, got["item"]) == names(language)[2]
    pairing = json.loads(store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ?",
                                            (got["item"],)).fetchone()[0])
    assert pairing["media_type"] == "movie"
    disney = _body(language, video="5f2c1e7a-6b9d-4c1e-9a0b-3d2f1e0c9b8a", site="disneyplus")
    disney["url"] = "https://www.disneyplus.com/video/5f2c1e7a-6b9d-4c1e-9a0b-3d2f1e0c9b8a"
    status, got = _post(d, disney)
    assert status == 200 and store.item(got["item"])["source_type"] == "disneyplus"
    assert store.item(got["item"])["rel_path"].endswith("[disneyplus-5f2c1e7a-6b9d-4c1e-9a0b-3d2f1e0c9b8a].txt")


# --- the cover (v1's optional `cover`; #474's, by mattias) ---------------------------------------------------------- #
def _png(pad=0):
    """A real 1×1 PNG (`pad` bytes of a text chunk make it as big as wanted)."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + (chunk(b"tEXt", b"Comment\x00" + b"x" * pad) if pad else b"")
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _cover_of(store, item_id):
    return store.conn.execute("SELECT w.cover_source, w.cover_ref, w.cover_path, w.cover_locked FROM items i JOIN "
                              "works w ON w.id = i.work_id WHERE i.id = ?", (item_id,)).fetchone()


class _CoverWriter(_Writer):
    def set_cover(self, work_id, source, ref=None, path=None, locked=False, label=None, auto=False):
        assert auto, "nobody's choice: never on the Undo stack"
        got = self.opener.handle().set_cover(work_id, source, ref=ref, path=path, locked=locked)
        self.opener.close()
        return 1 if got is not None else None


def _with_cover(language, data, **kw):
    import base64
    body = _body(language, **kw)
    body["cover"] = base64.b64encode(data).decode("ascii") if isinstance(data, bytes) else data
    return subtitles.subtitle(body)


@pytest.fixture(params=LANGUAGES)
def covered(request):
    language = request.param
    store = migrated(language)
    yield store, _CoverWriter(language), language
    store.close()


def test_the_pages_artwork_becomes_the_cover_of_a_title_with_none(covered):
    store, writer, language = covered
    _added, item = subtitles.take_in(writer, _with_cover(language, _png()), cover=subtitles.keep_cover)
    source, ref, path, locked = _cover_of(store, item)
    assert (source, ref, locked) == ("user", "browser:netflix", 0)
    assert path.startswith("user:") and path.endswith(".png")
    assert os.path.isfile(os.path.join(path_utils.get_user_files_path(language), "covers", path[len("user:"):]))


def test_a_title_with_a_cover_of_its_own_keeps_it(covered):
    store, writer, language = covered
    _added, item = subtitles.take_in(writer, _with_cover(language, _png()), cover=subtitles.keep_cover)
    work = store.item(item)["work_id"]
    assert store.set_cover(work, "file", ref="Processed/folder.jpg") is not None      # its own art, say
    _added, again = subtitles.take_in(writer, _with_cover(language, _png(pad=40), video="81234599"),
                                      cover=subtitles.keep_cover)
    assert store.item(again)["work_id"] == work
    assert _cover_of(store, again)[:3] == ("file", "Processed/folder.jpg", None)


@pytest.mark.parametrize("bad", ["not base64 at all!", b"GIF89a this is no PNG at all, only text", "big"])
def test_a_broken_or_too_big_cover_is_left_out_and_the_subtitle_still_arrives(covered, bad):
    store, writer, language = covered
    data = _png(pad=subtitles.MAX_COVER) if bad == "big" else bad
    added, item = subtitles.take_in(writer, _with_cover(language, data), cover=subtitles.keep_cover)
    assert added is True and _cover_of(store, item)[0] in (None, "generated")


def test_with_covers_off_the_route_keeps_no_cover_and_with_them_on_it_does(run, monkeypatch):
    """U7: the show's artwork is kept only while *Download covers* is on (hello says so, so Ukai fetches it only
    then); off, a cover sent anyway is dropped before anything reads it."""
    import base64
    d, store, _writer, language, _p, settings = run
    kept, real = [], subtitles.take_in
    monkeypatch.setattr(subtitles, "take_in", lambda writer, sub, rules=None: real(
        writer, sub, rules, cover=lambda _w, s, _i: kept.append(s.get("cover"))))
    body = _body(language)
    body["cover"] = base64.b64encode(_png()).decode("ascii")
    assert _post(d, body)[0] == 200 and kept == [None]
    settings["covers_download"] = True
    assert _post(d, body)[0] == 200 and kept == [None, body["cover"]]


def test_a_disk_that_wont_take_the_file_is_busy_never_a_crash(run, monkeypatch):
    """(Review.) Processed unwritable or the file held: 503 *busy* (Ukai sends it again), nothing registered."""
    d, _store, writer, language, _p, _s = run

    def held(*_a, **_k):
        raise PermissionError(13, "held by another program")

    monkeypatch.setattr(subtitles.os, "replace", held)
    status, got = _post(d, _body(language))
    assert (status, got["kind"]) == (503, "busy") and writer.registered == []


def test_a_file_already_there_by_that_name_is_never_written_over(run):
    """(Review; CLAUDE.md §4.) A transcript of that video already in Processed with no pairing (named by hand, or
    from a try whose answer was lost): kept byte for byte, and it becomes the video's one item."""
    d, store, writer, language, _p, _s = run
    folder = os.path.join(writer.opener.data_dir, "Processed")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, subtitles.file_name(subtitles.subtitle(_body(language))))
    with open(path, "w", encoding="utf-8") as f:
        f.write("自分で書いた書き起こし")
    status, got = _post(d, _body(language))
    assert status == 200 and got["added"] is True
    with open(path, encoding="utf-8") as f:
        assert f.read() == "自分で書いた書き起こし"
    assert store.item(got["item"])["rel_path"].endswith(os.path.basename(path))
    assert _post(d, _body(language))[1]["item"] == got["item"]
