"""The journey's door (app/door.py; ⇄ Swap's first route, the 3.0 plan's tracks/pipeline/work/swap/SWAP-PROTO.md): a
loopback server only the journey page's own file can call. What a wrong answer would cost: any web page in the
learner's browser reaching his Anki through it (a missing token or origin check, a DNS-rebound name), a file outside
the preview folder served by name, a route's crash taking the window down or leaking its text, or a door file left
behind that names a dead port (the page would think the app is open)."""
import http.client
import json
import os

import pytest

from app import door


@pytest.fixture
def opened(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "0123abcd.mp3").write_bytes(b"ID3 a clip")
    (tmp_path / "secret.txt").write_text("not a clip", encoding="utf-8")
    calls = []

    def echo(body):
        calls.append(body)
        return {"echo": body}

    def refuses(_body):
        raise door.RouteError("Open Anki to swap this card's sentence.", "anki-closed")

    def crashes(_body):
        raise KeyError("C:/Users/someone/private/path")

    errors = []
    d = door.Door({"echo": echo, "refuses": refuses, "crashes": crashes}, str(tmp_path / "results"),
                  clips=str(clips), on_error=lambda path, e: errors.append((path, e))).start()
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


def test_door_js_names_the_port_and_token_and_goes_at_stop(tmp_path):
    d = door.Door({}, str(tmp_path / "results")).start()
    path = tmp_path / "results" / door.FILE
    text = path.read_text(encoding="utf-8")
    assert text.startswith("/*") and "window.SURASURA_DOOR = " in text
    named = json.loads(text.split("window.SURASURA_DOOR = ", 1)[1].rstrip().rstrip(";"))
    assert named == {"port": d.port, "token": d.token, "version": door.VERSION}
    d.stop()
    assert not path.exists()


def test_a_later_doors_file_is_left_by_the_earlier_ones_stop(tmp_path):
    # two windows (a restart's overlap): the first to stop must not delete the file naming the one still open
    first = door.Door({}, str(tmp_path)).start()
    second = door.Door({}, str(tmp_path)).start()
    first.stop()
    assert second.token in (tmp_path / door.FILE).read_text(encoding="utf-8")
    second.stop()


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
    assert _post(opened, "swap/nothing", {"token": opened.token})[0] == 404
    assert _post(opened, "../echo", {"token": opened.token})[0] == 404


def test_a_refusal_is_said_in_its_own_words(opened):
    answer = _post(opened, "refuses", {"token": opened.token})[2]
    assert answer == {"ok": False, "error": "Open Anki to swap this card's sentence.", "kind": "anki-closed"}


def test_a_routes_crash_is_said_plainly_and_never_its_text(opened):
    status, _h, answer = _post(opened, "crashes", {"token": opened.token})
    assert status == 200 and answer["ok"] is False and answer["kind"] == "crashed"
    assert "private" not in json.dumps(answer) and opened.errors and opened.errors[0][0] == "/v1/crashes"


def test_a_clip_is_served_by_its_name_with_the_token(opened):
    status, headers, data = _request(opened, "GET", f"/v1/clip/0123abcd.mp3?t={opened.token}")
    assert status == 200 and data == b"ID3 a clip" and headers["Content-Type"] == "audio/mpeg"


@pytest.mark.parametrize("name", ["../secret.txt", "..%2Fsecret.txt", "secret.txt", "0123abcd.mp3/..", "nothere.mp3",
                                  "C:%5Cwindows%5Cwin.ini"])
def test_nothing_but_a_clip_in_the_folder_is_served(opened, name):
    assert _request(opened, "GET", f"/v1/clip/{name}?t={opened.token}")[0] == 404


def test_a_clip_without_the_token_is_refused(opened):
    assert _request(opened, "GET", "/v1/clip/0123abcd.mp3")[0] == 403
    assert _request(opened, "GET", "/v1/clip/0123abcd.mp3?t=wrong")[0] == 403


def test_a_preflight_is_refused(opened):
    # every call the page makes is a simple request: something asking a preflight isn't the page
    assert _request(opened, "OPTIONS", "/v1/echo", origin="https://example.com")[0] == 403


def test_it_listens_on_loopback_only(opened):
    assert opened._server.server_address[0] == "127.0.0.1"
    assert os.path.basename(opened._path()) == door.FILE


def test_send_report_leaves_the_doors_file_out():
    # results/ goes into Send report's zip; the door's file holds the session's token, so it is named as a secret
    from app import report
    assert report.is_secret(door.FILE)


def test_start_replaces_the_doors_one_a_process(tmp_path):
    first = door.start({}, str(tmp_path))
    second = door.start({}, str(tmp_path))
    try:
        assert first._server is None and second.token in (tmp_path / door.FILE).read_text(encoding="utf-8")
    finally:
        door.stop()
    assert not (tmp_path / door.FILE).exists()
