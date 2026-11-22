"""The journey's door (app/door.py; built for ⇄ Swap in #385, split out on its own by Kotoba-K): a loopback server
only the journey page's own file can call. What a wrong answer would cost: any web page in the learner's browser
writing their word lists through it (a missing token or origin check, a DNS-rebound name), a route's crash taking the
window down or leaking its text, or the token in a file
any other local page could read (review 1's #4: the token goes only to the page the window opens, through a one-time
page whose name can't be guessed and which goes within LAUNCH_S)."""
import http.client
import json
import os
import re
import time

from pathlib import Path
from urllib.parse import quote

import pytest

from app import door


@pytest.fixture
def opened(tmp_path):
    calls = []

    def echo(body):
        calls.append(body)
        return {"echo": body}

    def refuses(_body):
        raise door.RouteError("Your known words are being updated by Anki: try again in a moment.", "busy")

    def crashes(_body):
        raise KeyError("C:/Users/someone/private/path")

    errors = []
    d = door.Door({"echo": echo, "refuses": refuses, "crashes": crashes}, str(tmp_path / "results"),
                  on_error=lambda path, e: errors.append((path, e))).start()
    d.calls, d.errors = calls, errors
    yield d
    d.stop()


def _request(d, method, path, body=None, host=None, origin=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", d.port, timeout=5)
    headers = {"Host": host or f"127.0.0.1:{d.port}", "Content-Type": "text/plain"}
    if origin is not None:
        headers["Origin"] = origin
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None
                                        else None)
    conn.request(method, path, body=data, headers=headers)
    r = conn.getresponse()
    out = r.status, dict(r.getheaders()), r.read()
    conn.close()
    return out


def _post(d, route, body, **kw):
    status, headers, data = _request(d, "POST", f"/v1/{route}", body, **kw)
    return status, headers, json.loads(data.decode("utf-8"))


def _target(page):
    """The address a one-time page replaces itself with."""
    found = re.search(r"location\.replace\((\"[^\"]*\")\)", page.read_text(encoding="utf-8"))
    return json.loads(found.group(1))


def _holding(folder, token):
    return [p.name for p in folder.rglob("*") if p.is_file() and token in p.read_text(encoding="utf-8", errors="ignore")]


def test_an_open_door_leaves_no_file_holding_its_token(tmp_path):
    # review 1's #4: a file at a known name holding the token is readable by any local page with a <script> tag
    results = tmp_path / "results"
    d = door.Door({}, str(results)).start()
    try:
        assert d.port and _holding(tmp_path, d.token) == []
    finally:
        d.stop()


def test_the_one_time_page_opens_the_report_with_the_door_in_its_address_and_a_secrets_name(tmp_path):
    from app import report
    results = tmp_path / "results"
    d = door.Door({}, str(results)).start()
    try:
        page = Path(d.launch_page(str(results), "reading_list_static.html", "file=%E5%AE%B6.srt"))
        assert page.parent == results and re.fullmatch(door.PREFIX + r"-[0-9a-f]{32}\.html", page.name)
        assert _target(page) == f"reading_list_static.html#door={d.port}.{d.token}&file=%E5%AE%B6.srt"
        assert _target(Path(d.launch_page(str(results), "reading_list_static.html"))) == \
            f"reading_list_static.html#door={d.port}.{d.token}"
        assert report.is_secret(page.name), "Send report zips results/: a page holding the token is never taken"
        assert re.fullmatch(r"[A-Za-z0-9_-]+", d.token), "the page's reader takes these characters only"
    finally:
        d.stop()


def test_two_one_time_pages_never_share_a_name(tmp_path):
    d = door.Door({}, str(tmp_path)).start()
    try:
        names = {d.launch_page(str(tmp_path), "r.html") for _ in range(20)}
        assert len(names) == 20
    finally:
        d.stop()


def test_a_one_time_page_loses_its_door_after_its_life_and_the_rest_at_stop(tmp_path, monkeypatch):
    # review 2: a browser slower than LAUNCH_S (a cold laptop) still opens the report — without the door — never a
    # missing file; the token is in no page once its life is over, nor after the window's quit
    d = door.Door({}, str(tmp_path)).start()
    monkeypatch.setattr(door, "LAUNCH_S", 0.05)
    short = Path(d.launch_page(str(tmp_path), "r.html", "file=a.srt"))
    monkeypatch.setattr(door, "LAUNCH_S", 600.0)
    long_ = Path(d.launch_page(str(tmp_path), "r.html"))
    deadline = time.monotonic() + 5
    while d.token in short.read_text(encoding="utf-8") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert _target(short) == "r.html#file=a.srt" and d.token in long_.read_text(encoding="utf-8")
    d.stop()
    assert _target(long_) == "r.html" and _holding(tmp_path, d.token) == []


def test_a_stopped_door_writes_no_page(tmp_path):
    # review 2: a press racing the quit never leaves a page holding a dead token (no timer runs after the exit)
    d = door.start({}, str(tmp_path))
    door.stop()
    with pytest.raises(OSError):
        d.launch_page(str(tmp_path), "r.html")
    assert door.launch_page(str(tmp_path), "r.html") is None and list(tmp_path.iterdir()) == []


def test_start_sweeps_an_earlier_windows_pages_and_nothing_else(tmp_path):
    # a killed window leaves its page (a dead token); the first prototype's door-secret.js too
    (tmp_path / "door-secret-0123456789abcdef0123456789abcdef.html").write_text("old", encoding="utf-8")
    (tmp_path / "door-secret.js").write_text("old", encoding="utf-8")
    (tmp_path / "reading_list_static.html").write_text("the report", encoding="utf-8")
    (tmp_path / "journey_open.html").write_text("the episode page", encoding="utf-8")
    d = door.Door({}, str(tmp_path)).start()
    try:
        assert sorted(p.name for p in tmp_path.iterdir()) == ["journey_open.html", "reading_list_static.html"]
    finally:
        d.stop()


def test_an_earlier_doors_stop_leaves_the_later_doors_page(tmp_path):
    # two doors in a restart's overlap: the first to stop removes its own pages only
    first = door.Door({}, str(tmp_path)).start()
    second = door.Door({}, str(tmp_path)).start()
    page = Path(second.launch_page(str(tmp_path), "r.html"))
    first.stop()
    assert second.token in page.read_text(encoding="utf-8")
    second.stop()
    assert page.exists() and second.token not in page.read_text(encoding="utf-8")


def test_with_no_door_open_there_is_no_one_time_page(tmp_path):
    door.stop()
    assert door.current() is None and door.launch_page(str(tmp_path), "r.html") is None
    assert list(tmp_path.iterdir()) == []


def test_the_window_opens_the_report_through_the_doors_page_and_without_one_as_before(tmp_path, monkeypatch):
    # static_html_generator.open_report (Your journey ↗, the ⋯'s See it in your journey): the door's page while a door
    # is open in this process, the report's own file= after the door; none open, today's way (the report, or
    # journey_open.html for one file)
    from app import static_html_generator as gen
    results = tmp_path / "results"
    results.mkdir()
    (results / gen.REPORT_NAME).write_text("<html></html>", encoding="utf-8")
    opened = []
    monkeypatch.setattr(gen, "get_user_file", lambda name: str(results))
    monkeypatch.setattr(gen.webbrowser, "open", opened.append)
    door.stop()
    assert gen.open_report() is True and opened[-1] == f"file://{results / gen.REPORT_NAME}"
    d = door.start({}, str(results))
    try:
        assert gen.open_report() is True
        page = Path(opened[-1][len("file://"):])
        assert page.name.startswith(door.PREFIX) and _target(page) == f"{gen.REPORT_NAME}#door={d.port}.{d.token}"
        assert gen.open_report(file="家庭教師 01.srt") is True
        page = Path(opened[-1][len("file://"):])
        assert _target(page) == f"{gen.REPORT_NAME}#door={d.port}.{d.token}&file=%E5%AE%B6%E5%BA%AD%E6%95%99%E5%B8%AB%2001.srt"
        assert not (results / gen.OPEN_ON_NAME).exists()
    finally:
        door.stop()
    assert gen.open_report(file="家庭教師 01.srt") is True and opened[-1] == f"file://{results / gen.OPEN_ON_NAME}"
    assert _holding(tmp_path, d.token) == []


def test_the_page_takes_the_door_out_of_its_address_before_reading_its_own_fragment():
    # the template's reader runs before `file=` / `search=` are read, and nothing reads a door file any more
    from app.path_utils import get_resource
    with open(get_resource(os.path.join("templates", "web_app.html")), encoding="utf-8") as f:
        page = f.read()
    reader = page.index("const SURASURA_DOOR = (function")
    assert reader < page.index("function fileFromHash()") and reader < page.index("async function rsFromHash()")
    assert "door-secret" not in page and "history.replaceState" in page[reader:reader + 1200]


def test_a_call_with_the_token_from_a_file_page_reaches_its_route(opened):
    status, headers, answer = _post(opened, "echo", {"token": opened.token, "word": "家庭教師"}, origin="null")
    assert status == 200 and answer == {"ok": True, "echo": {"word": "家庭教師"}}
    assert headers["Access-Control-Allow-Origin"] == "null"
    assert opened.calls == [{"word": "家庭教師"}]              # the token never reaches a route


def test_hello_answers_without_any_route_of_its_own(opened):
    assert _post(opened, "hello", {"token": opened.token})[2] == {"ok": True, "version": door.VERSION}


@pytest.mark.parametrize("token", [None, "", "wrong", 12345])
def test_a_wrong_or_missing_token_is_refused(opened, token):
    body = {"word": "x"} if token is None else {"token": token, "word": "x"}
    status, _h, answer = _post(opened, "echo", body)
    assert status == 403 and answer["ok"] is False and opened.calls == []


def test_a_web_pages_origin_is_refused_even_with_the_token(opened):
    status, _h, _a = _post(opened, "echo", {"token": opened.token}, origin="https://example.com")
    assert status == 403 and opened.calls == []


@pytest.mark.parametrize("host", ["localhost:{port}", "attacker.example:{port}", "127.0.0.1", "127.0.0.1:1"])
def test_any_host_but_its_own_address_is_refused(opened, host):
    # a name rebound to 127.0.0.1 (DNS rebinding) carries that name in Host
    status, _h, _a = _post(opened, "echo", {"token": opened.token}, host=host.format(port=opened.port))
    assert status == 403 and opened.calls == []


def test_a_body_over_64_kb_is_refused_unread(opened):
    status, _h, _data = _request(opened, "POST", "/v1/echo", raw=b"x" * (door.MAX_BODY + 1))
    assert status == 413 and opened.calls == []


def test_a_body_that_isnt_json_or_isnt_an_object_is_refused(opened):
    assert _request(opened, "POST", "/v1/echo", raw="ねこ{".encode("utf-8"))[0] == 400
    assert _request(opened, "POST", "/v1/echo", raw=b'["a list"]')[0] == 403


def test_an_unknown_route_is_404(opened):
    assert _post(opened, "words/nothing", {"token": opened.token})[0] == 404
    assert _post(opened, "../echo", {"token": opened.token})[0] == 404


def test_a_refusal_is_said_in_its_own_words(opened):
    answer = _post(opened, "refuses", {"token": opened.token})[2]
    assert answer == {"ok": False, "error": "Your known words are being updated by Anki: try again in a moment.",
                      "kind": "busy"}


def test_a_routes_crash_is_said_plainly_and_never_its_text(opened):
    status, _h, answer = _post(opened, "crashes", {"token": opened.token})
    assert status == 200 and answer["ok"] is False and answer["kind"] == "crashed"
    assert "private" not in json.dumps(answer) and opened.errors and opened.errors[0][0] == "/v1/crashes"


def test_a_get_reaches_no_route_and_needs_its_own_address(opened):
    # every route is a POST (the one GET is a clip the door handed out, below): a GET is answered 404, a stranger's 403
    assert _request(opened, "GET", f"/v1/echo?t={opened.token}")[0] == 404 and opened.calls == []
    assert _request(opened, "GET", "/v1/echo", host="attacker.example")[0] == 403


def test_a_preflight_is_refused(opened):
    # every call the page makes is a simple request: something asking a preflight isn't the page
    assert _request(opened, "OPTIONS", "/v1/echo", origin="https://example.com")[0] == 403


def test_it_listens_on_loopback_only(opened):
    assert opened._server.server_address[0] == "127.0.0.1"


def test_start_replaces_the_doors_one_a_process(tmp_path):
    first = door.start({}, str(tmp_path))
    page = Path(door.launch_page(str(tmp_path), "r.html"))
    second = door.start({}, str(tmp_path))
    try:
        assert first._server is None and door.current() is second and not page.exists()
        assert second.token in _target(Path(door.launch_page(str(tmp_path), "r.html")))
    finally:
        door.stop()
    assert door.current() is None and _holding(tmp_path, second.token) == []


# --- the one GET: a clip the app handed out (journey v3 SPEC §3.3; #385's) ---------------------------------------- #
def test_a_clip_handed_out_plays_at_its_url_and_only_through_the_doors_own_address(opened, tmp_path):
    clip = tmp_path / "家庭教師 01 00-01-02.mp3"
    clip.write_bytes(b"ID3\x03\x00 a short line's audio")
    url = opened.serve_file(str(clip), "audio/mpeg")
    path = url[len(f"http://127.0.0.1:{opened.port}"):]
    assert url.startswith(f"http://127.0.0.1:{opened.port}{door.CLIP_PATH}") and len(path.rsplit("/", 1)[1]) == 32
    status, headers, data = _request(opened, "GET", path)
    assert status == 200 and data == clip.read_bytes() and headers["Content-Type"] == "audio/mpeg"
    assert _request(opened, "GET", path, host="attacker.example")[0] == 403
    assert _request(opened, "GET", path, origin="https://example.com")[0] == 403
    assert _request(opened, "POST", path, {"token": opened.token})[0] == 404     # (a clip is no route)


def test_a_clip_name_the_door_never_handed_out_or_no_longer_keeps_is_404(opened, tmp_path):
    clip = tmp_path / "第3話.m4a"
    clip.write_bytes(b"\x00\x00\x00\x18ftypM4A ")
    first = opened.serve_file(str(clip), "audio/mp4")
    first_path = first[len(f"http://127.0.0.1:{opened.port}"):]
    assert _request(opened, "GET", door.CLIP_PATH + "0" * 32)[0] == 404
    assert _request(opened, "GET", door.CLIP_PATH + quote(str(clip)))[0] == 404          # never a path, only a name
    for _ in range(door.CLIPS_KEPT):
        opened.serve_file(str(clip), "audio/mp4")
    assert _request(opened, "GET", first_path)[0] == 404                         # the oldest let go
    last = opened.serve_file(str(clip), "audio/mp4")
    clip.unlink()
    assert _request(opened, "GET", last[len(f"http://127.0.0.1:{opened.port}"):])[0] == 404    # its file gone


def test_with_no_door_open_no_clip_is_handed_out_and_a_stop_forgets_them(tmp_path):
    door.stop()
    assert door.serve_file(str(tmp_path / "a.mp3"), "audio/mpeg") is None
    d = door.start({}, str(tmp_path))
    door.serve_file(str(tmp_path / "a.mp3"), "audio/mpeg")
    door.stop()
    assert d._clips == {}


def test_an_answer_json_cant_carry_is_said_as_a_crash_never_a_dropped_call(tmp_path):
    # a route (an owner's reader) answering a set: the page still gets its answer, and the window's log the error
    errors = []
    d = door.Door({"odd": lambda _body: {"words": {"猫", "犬"}}}, str(tmp_path),
                  on_error=lambda path, e: errors.append(path)).start()
    try:
        status, _h, answer = _post(d, "odd", {"token": d.token})
        assert status == 200 and answer["ok"] is False and answer["kind"] == "crashed" and errors == ["/v1/odd"]
    finally:
        d.stop()


def test_a_body_too_deep_a_token_no_encoding_holds_and_an_odd_target_are_each_answered(opened):
    # each was a dropped connection (no answer, a traceback) before: Python's depth, a lone surrogate, urlsplit
    assert _request(opened, "POST", "/v1/echo", raw=b"[" * 50_000)[0] == 400
    assert _request(opened, "POST", "/v1/echo", raw=b'{"token": "\\ud800"}')[0] == 403
    assert _request(opened, "GET", "//[")[0] == 404 and _request(opened, "GET", "/v1/clip/x?y#z")[0] == 404
    assert opened.calls == []
