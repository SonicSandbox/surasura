"""Ukai's caller class on the journey's door (app/door.py, `Extension`; Ukai SPEC §6 U-S0, adapting #474's listener
checks): the browser extension's own listener on 127.0.0.1:27631 (or the next few), beside the page's.

What a wrong answer would cost a learner: a web page they visit posting into their library or reading what waits to
be recorded (an Origin or token check missing); another extension, or a page with a stolen token, passing as the
paired one; a 40 MB clip held in memory, or half a clip kept after a tab closed mid-upload; one silent connection
blocking every later call; two Surasuras bound to the same port (Windows lets a second bind take it); and, until
Ukai's pairing exists (U-S1), anything listening at all.

The door is the real one on a free loopback port (EXT_PORT moved off 27631 in every test that turns the class on, so
a test never binds the real port); the bodies are real lines from `tests/Test Resources/ja|zh`.
"""
import http.client
import json
import os
import socket
import threading
import time

import pysrt
import pytest

from app import door

ORIGIN = "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb"
OTHER = "chrome-extension://aapbdbdomjkkjkaonfhkkikfgjllcleb"
TOKEN = "ukai-no-kotoba-wa-hoshi-no-yo-ni"
REAL_EXT_PORT = door.EXT_PORT                  # (27631: a test moves EXT_PORT, never binds this one)


def _cues(resources, name):
    """A subtitle's first lines as the extension sends them: [start s, end s, text]."""
    subs = pysrt.open(os.path.join(resources, name), encoding="utf-8")
    return [[s.start.ordinal / 1000, s.end.ordinal / 1000, s.text] for s in subs[:3]]


def _free_port():
    with socket.socket() as s:
        s.bind((door.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture
def ukai(tmp_path, monkeypatch):
    """A door with Ukai's class on: its routes record what reached them; `pair` is what `pairing()` answers."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    calls, pair, errors = [], {"now": (ORIGIN, TOKEN)}, []

    def echo(call):
        body = call.json()
        calls.append(("echo", body))
        return {"echo": body}

    def clip(call):
        job, n = call.groups
        path = str(tmp_path / f"b{job}" / f"clip-{n}.webm")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        size = call.save(path)
        calls.append(("clip", job, n, size))
        return {"size": size}

    def jobs(_call):
        calls.append(("jobs",))
        return {"jobs": [{"job": 412, "lines": [{"n": 0, "start": 705.29, "end": 708.84}]}]}

    def busy(_call):
        raise door.RouteError("Surasura is busy: try again later", "busy", status=503)

    def crashes(_call):
        raise KeyError("C:/Users/someone/private/path")

    def unread(_call):
        calls.append(("unread",))
        return {}

    def twice(call):
        call.json()
        return call.json()

    routes = {"POST /v1/echo": echo, r"POST /v1/jobs/(\d{1,9})/clips/(\d{1,5})": clip, "GET /v1/jobs": jobs,
              "POST /v1/busy": busy, "POST /v1/crashes": crashes, "POST /v1/unread": unread, "POST /v1/twice": twice}
    ext = door.Extension(routes, lambda: pair["now"])
    d = door.Door({}, str(tmp_path / "results"), on_error=lambda path, e: errors.append((path, e)),
                  extension=ext).start()
    d.calls, d.pair, d.errors, d.clips = calls, pair, errors, tmp_path
    yield d
    d.stop()


def _ask(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection(door.HOST, port, timeout=10)
    data = body if isinstance(body, bytes) or body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    sent = {"Host": host or f"{door.HOST}:{port}"}
    sent.update(headers or {})
    conn.request(method, path, body=data, headers=sent)
    r = conn.getresponse()
    got = r.read()
    conn.close()
    return r.status, (json.loads(got.decode("utf-8")) if got else None), dict(r.getheaders())


def _ukai(d, method, path, body=None, token=TOKEN, origin=ORIGIN, **headers):
    """A call as Ukai's background makes it: the token header, its Origin (a POST always has one: Chrome stamps it)."""
    if token is not None:
        headers[door.EXT_TOKEN_HEADER] = token
    if origin is not None:
        headers["Origin"] = origin
    if body is not None and not isinstance(body, bytes):
        headers.setdefault("Content-Type", "application/json")
    return _ask(d.ext_port, method, path, body, headers)


# --- off until the pairing exists ----------------------------------------------------------------------------------- #
def test_ukais_class_is_off_so_nothing_listens_for_the_extension(tmp_path, monkeypatch):
    """U-S0's gate: until U-S1's pairing exists, a door given Ukai's class binds nothing for it — no server built,
    no port, no thread — while the page's own class still answers."""
    assert door.EXTENSION_ON is False, "switched on only with Ukai's pairing (U-S1)"
    built = []
    monkeypatch.setattr(door, "_ExtServer", lambda *a, **k: built.append(a))
    d = door.Door({}, str(tmp_path / "results"), extension=door.Extension({}, lambda: (ORIGIN, TOKEN))).start()
    try:
        assert built == [] and d.ext_port is None
        assert not [t for t in threading.enumerate() if t.name == "ukai-door"]
        status, got, _h = _ask(d.port, "POST", "/v1/hello", json.dumps({"token": d.token}).encode("utf-8"),
                               {"Content-Type": "text/plain"})
        assert status == 200 and got["ok"] is True, "the page's class is untouched"
    finally:
        d.stop()


# (the window's side of the gate, off and on: tests/test_ukai_pairing.py, `test_while_off_…` / `test_once_on_…`)


# --- who may call --------------------------------------------------------------------------------------------------- #
def test_hello_answers_any_extension_and_no_web_page(ukai):
    status, got, headers = _ask(ukai.ext_port, "GET", "/v1/hello")
    assert status == 200 and got == {"ok": True, "app": "surasura", "door": door.VERSION}, "a GET carries no Origin"
    assert not [k for k in headers if k.lower().startswith("access-control")], "no CORS: a page can't read it"
    assert _ask(ukai.ext_port, "GET", "/v1/hello", headers={"Origin": OTHER})[0] == 200, "any extension, unpaired"
    for page in ("https://www.netflix.com", "null", "chrome-extension://", "http://127.0.0.1:8000"):
        assert _ask(ukai.ext_port, "GET", "/v1/hello", headers={"Origin": page})[0] == 403, page
    assert _ask(ukai.ext_port, "OPTIONS", "/v1/echo", headers={"Origin": ORIGIN})[0] == 403, "no preflight, ever"


@pytest.mark.parametrize("lang, name", [("ja", "phrases_sample.srt"), ("zh", "night_market.srt")])
def test_the_paired_extension_reaches_its_route_with_the_text_whole(ukai, test_resources_dir, lang, name):
    cues = _cues(os.path.join(test_resources_dir, lang), name)
    status, got, _h = _ukai(ukai, "POST", "/v1/echo", {"language": lang, "cues": cues})
    assert status == 200 and got == {"ok": True, "echo": {"language": lang, "cues": cues}}
    assert ukai.calls == [("echo", {"language": lang, "cues": cues})]


@pytest.mark.parametrize("token", [None, "", TOKEN[:-1], TOKEN + "x", TOKEN.upper(), "ukai-nö-kotoba"])
def test_a_wrong_or_missing_token_reaches_no_route(ukai, token):
    status, got, _h = _ukai(ukai, "POST", "/v1/echo", {"cues": []}, token=token)
    assert status == 401 and got["ok"] is False and ukai.calls == []


def test_another_extension_with_the_token_is_refused(ukai):
    """The Origin is pinned beside the token: a token another extension got hold of opens nothing."""
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []}, origin=OTHER)[0] == 403
    assert _ukai(ukai, "GET", "/v1/jobs", origin=OTHER)[0] == 403
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []}, origin=OTHER, token=None)[0] == 401, (
        "the token is checked first: a caller without it learns nothing of who is paired")
    assert ukai.calls == []


def test_a_post_without_an_origin_is_refused_and_a_get_without_one_needs_the_token(ukai):
    """Chrome stamps an extension's POST with its Origin and sends its GET with none (as measured): a POST
    with none is no extension's; a GET with none still needs the paired token."""
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []}, origin=None)[0] == 403
    assert _ukai(ukai, "GET", "/v1/jobs", origin=None, token=None)[0] == 401
    status, got, _h = _ukai(ukai, "GET", "/v1/jobs", origin=None)
    assert status == 200 and got["jobs"][0]["job"] == 412
    assert ukai.calls == [("jobs",)]


def test_not_paired_or_forgotten_refuses_at_once(ukai):
    """No pairing yet, a pairing whose read fails, or *Forget Ukai* mid-session: every paired route refused at the
    next call (the pairing is read at each one); hello still answers, for the pairing to begin."""
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []})[0] == 200
    ukai.pair["now"] = None
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []})[0] == 401
    ukai.pair["now"] = ("", "")
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []}, token="")[0] == 401
    assert _ukai(ukai, "GET", "/v1/jobs", origin=None, token="")[0] == 401, "an empty pairing pins nothing"
    assert _ask(ukai.ext_port, "GET", "/v1/hello")[0] == 200
    assert len(ukai.calls) == 1


def test_a_pairing_that_cant_be_read_refuses_and_never_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())

    def unreadable():
        raise OSError("the pairing file is locked")

    d = door.Door({}, str(tmp_path), extension=door.Extension({"GET /v1/jobs": lambda c: {}}, unreadable)).start()
    try:
        assert _ask(d.ext_port, "GET", "/v1/jobs", headers={door.EXT_TOKEN_HEADER: TOKEN})[0] == 401
    finally:
        d.stop()


@pytest.mark.parametrize("origin", ["", "chrome-extension://", "null", "https://evil.example", None])
def test_a_pairing_that_pins_no_extension_opens_nothing_even_to_its_token(ukai, origin):
    """A pairing whose Origin isn't an extension's pins nothing: an Origin-less GET (the one the pinned-Origin check
    lets through on the token) is refused all the same."""
    ukai.pair["now"] = (origin, TOKEN)
    assert _ukai(ukai, "GET", "/v1/jobs", origin=None)[0] == 401
    assert ukai.calls == []


def test_an_empty_token_is_never_a_match_on_either_side():
    """Each check holds on its own: the shared compare takes no empty token, and a pairing with one is no pairing."""
    assert door._same("", "") is False and door._same(TOKEN, TOKEN) is True and door._same(TOKEN[:-1], TOKEN) is False
    assert door._same(TOKEN + "x", TOKEN) is False
    assert door.Extension({}, lambda: (ORIGIN, "")).paired() is None
    assert door.Extension({}, lambda: (ORIGIN, TOKEN)).paired() == (ORIGIN, TOKEN)


@pytest.mark.parametrize("host", ["localhost", "evil.example", "127.0.0.1", "127.0.0.1:1"])
def test_any_host_but_its_own_address_is_refused(ukai, host):
    """DNS rebinding: a page's name pointed at 127.0.0.1 still carries its own Host."""
    status, _got, _h = _ask(ukai.ext_port, "GET", "/v1/hello", host=host)
    assert status == 403


def test_an_unknown_route_or_method_is_404(ukai):
    assert _ukai(ukai, "POST", "/v1/nothing", {"cues": []})[0] == 404
    assert _ukai(ukai, "POST", "/v1/jobs", {"cues": []})[0] == 404, "GET only"
    assert _ukai(ukai, "POST", "/v1/jobs/412/clips/0/x", b"x")[0] == 404, "the whole path, never a prefix"
    assert ukai.calls == []


# --- each class refuses the other's calls, and both refuse a web page ------------------------------------------------ #
def test_the_pages_call_is_refused_by_ukais_class(ukai):
    """The journey page's call (Origin null, its token in a text/plain body) on Ukai's port: refused."""
    body = json.dumps({"token": ukai.token}).encode("utf-8")
    for origin in ("null", None):
        headers = {"Content-Type": "text/plain"} if origin is None else {"Content-Type": "text/plain", "Origin": origin}
        assert _ask(ukai.ext_port, "POST", "/v1/hello", body, headers)[0] == 403, origin
    assert _ukai(ukai, "POST", "/v1/echo", {"cues": []}, token=ukai.token)[0] == 401, "the page's token isn't Ukai's"
    assert ukai.calls == []


def test_ukais_call_is_refused_by_the_pages_class(ukai):
    """Ukai's call on the page's port: its Origin isn't a file page's, and its token isn't the session's."""
    status, _got, _h = _ask(ukai.port, "POST", "/v1/hello", json.dumps({"token": ukai.token}).encode("utf-8"),
                            {"Origin": ORIGIN, door.EXT_TOKEN_HEADER: TOKEN, "Content-Type": "application/json"})
    assert status == 403
    status, _got, _h = _ask(ukai.port, "POST", "/v1/hello", json.dumps({"token": TOKEN}).encode("utf-8"),
                            {"Content-Type": "text/plain"})
    assert status == 403, "Ukai's paired token opens nothing on the page's class"
    assert _ask(ukai.port, "GET", "/v1/jobs", headers={door.EXT_TOKEN_HEADER: TOKEN})[0] == 404


@pytest.mark.parametrize("page", ["https://www.netflix.com", "https://evil.example", "http://127.0.0.1:8000"])
def test_a_web_pages_origin_is_refused_by_both_classes(ukai, page):
    status, _got, _h = _ukai(ukai, "POST", "/v1/echo", {"cues": []}, origin=page)
    assert status == 403
    status, _got, _h = _ask(ukai.port, "POST", "/v1/hello", json.dumps({"token": ukai.token}).encode("utf-8"),
                            {"Origin": page, "Content-Type": "text/plain"})
    assert status == 403
    assert ukai.calls == []


# --- #474's caps and timeouts --------------------------------------------------------------------------------------- #
def test_a_json_body_over_its_limit_is_refused_unread(ukai, monkeypatch, test_resources_dir):
    monkeypatch.setattr(door, "EXT_MAX_JSON", 256)
    cues = _cues(os.path.join(test_resources_dir, "ja"), "phrases_sample.srt") * 8
    status, got, _h = _ukai(ukai, "POST", "/v1/echo", {"cues": cues})
    assert status == 413 and "too large" in got["why"] and ukai.calls == []


def test_a_body_with_no_length_or_not_json_or_cut_short_is_told_why(ukai):
    conn = http.client.HTTPConnection(door.HOST, ukai.ext_port, timeout=10)
    conn.putrequest("POST", "/v1/echo", skip_host=True)
    for k, v in (("Host", f"{door.HOST}:{ukai.ext_port}"), ("Origin", ORIGIN), (door.EXT_TOKEN_HEADER, TOKEN)):
        conn.putheader(k, v)
    conn.endheaders()
    r = conn.getresponse()
    assert r.status == 411 and "Content-Length" in json.loads(r.read())["why"]
    conn.close()
    assert _ukai(ukai, "POST", "/v1/echo", b"{not json")[0] == 400
    assert _ukai(ukai, "POST", "/v1/echo", b'["an array"]')[0] == 400
    assert _ukai(ukai, "POST", "/v1/echo", "やっと気がついた。".encode("shift_jis"))[0] == 400
    answer = _raw(ukai, "POST /v1/echo", 1000, b'{"cues": [')
    assert answer.startswith(("HTTP/1.0 400", "HTTP/1.1 400"))
    assert ukai.calls == []


def _raw(d, line, length, body, headers=""):
    """A request whose body ends before its Content-Length (a tab closed mid-upload) -> the answer's text."""
    with socket.create_connection((door.HOST, d.ext_port), timeout=10) as s:
        s.sendall((f"{line} HTTP/1.1\r\nHost: {door.HOST}:{d.ext_port}\r\nOrigin: {ORIGIN}\r\n"
                   f"{door.EXT_TOKEN_HEADER}: {TOKEN}\r\n{headers}Content-Length: {length}\r\n\r\n").encode() + body)
        s.shutdown(socket.SHUT_WR)
        return s.recv(4096).decode("utf-8", "replace")


def test_a_clip_is_streamed_to_its_file_in_chunks_never_whole_in_memory(ukai, monkeypatch):
    """≤ 40 MB to a file: read EXT_CHUNK at a time, written as it comes, the file in place only once it's whole."""
    monkeypatch.setattr(door, "EXT_CHUNK", 4096)
    reads = []
    real = door.Call._read

    def counted(self, n):
        reads.append(n)
        return real(self, n)

    monkeypatch.setattr(door.Call, "_read", counted)
    clip = (b"\x1aE\xdf\xa3" + os.urandom(64)) * 3000                  # ~200 KB, a webm's magic first
    status, got, _h = _ukai(ukai, "POST", "/v1/jobs/412/clips/0", clip, **{"Content-Type": "video/webm"})
    assert status == 200 and got == {"ok": True, "size": len(clip)}
    path = ukai.clips / "b412" / "clip-0.webm"
    assert path.read_bytes() == clip and not (ukai.clips / "b412" / "clip-0.webm.part").exists()
    assert reads and max(reads) <= 4096 and sum(reads) == len(clip)


def test_a_clip_over_40_mb_is_refused_unread_and_nothing_is_written(ukai):
    assert door.EXT_MAX_STREAM == 40 * 1024 * 1024
    answer = _raw(ukai, "POST /v1/jobs/412/clips/1", door.EXT_MAX_STREAM + 1, b"\x1aE\xdf\xa3",
                  "Content-Type: video/webm\r\n")
    assert answer.startswith(("HTTP/1.0 413", "HTTP/1.1 413"))
    assert not (ukai.clips / "b412").exists() or os.listdir(ukai.clips / "b412") == []


def test_a_clip_cut_short_keeps_nothing_and_leaves_the_earlier_clip_whole(ukai):
    """#474's 3: a tab closed mid-upload — a 400, no half clip; a clip already kept at that place stays as it was."""
    first = b"\x1aE\xdf\xa3" * 50
    assert _ukai(ukai, "POST", "/v1/jobs/412/clips/2", first)[0] == 200
    answer = _raw(ukai, "POST /v1/jobs/412/clips/2", 1000, b"\x1aE\xdf\xa3" * 10, "Content-Type: video/webm\r\n")
    assert answer.startswith(("HTTP/1.0 400", "HTTP/1.1 400"))
    assert (ukai.clips / "b412" / "clip-2.webm").read_bytes() == first
    assert sorted(os.listdir(ukai.clips / "b412")) == ["clip-2.webm"]


def test_a_refused_small_body_is_read_first_so_the_answer_arrives(ukai):
    """#474's drain: a refusal before a small body is read (Windows resets an unread socket before the answer is
    read) — the extension still gets its 401, not a reset."""
    status, got, _h = _ukai(ukai, "POST", "/v1/jobs/412/clips/3", os.urandom(200 * 1024), token="wrong")
    assert status == 401 and got["ok"] is False


def test_a_connection_gone_silent_never_blocks_the_next(tmp_path, monkeypatch):
    """#474's 5: a half-sent request ends at EXT_TIMEOUT; hello is answered meanwhile; a stalled clip leaves no part."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    monkeypatch.setattr(door, "EXT_TIMEOUT", 0.5)
    saved = []

    def clip(call):
        saved.append(call.save(str(tmp_path / "clip.webm")))
        return {}

    d = door.Door({}, str(tmp_path), extension=door.Extension({"POST /v1/clip": clip}, lambda: (ORIGIN, TOKEN))).start()
    try:
        hung = socket.create_connection((door.HOST, d.ext_port), timeout=5)
        hung.sendall(b"GET /v1/hel")
        stalled = socket.create_connection((door.HOST, d.ext_port), timeout=5)
        stalled.sendall((f"POST /v1/clip HTTP/1.1\r\nHost: {door.HOST}:{d.ext_port}\r\nOrigin: {ORIGIN}\r\n"
                         f"{door.EXT_TOKEN_HEADER}: {TOKEN}\r\nContent-Length: 5000\r\n\r\n").encode() + b"x" * 100)
        began = time.monotonic()
        assert _ask(d.ext_port, "GET", "/v1/hello")[0] == 200
        assert time.monotonic() - began < 5
        deadline = time.monotonic() + 10
        while os.listdir(tmp_path) and time.monotonic() < deadline:     # (the stalled clip ends at EXT_TIMEOUT)
            time.sleep(0.05)
        assert saved == [] and os.listdir(tmp_path) == [], "the stalled clip ended, its part removed"
        hung.close()
        stalled.close()
    finally:
        d.stop()


# --- answers ---------------------------------------------------------------------------------------------------------- #
def test_a_refusal_is_said_with_its_status_and_a_crash_plainly_never_its_text(ukai):
    status, got, _h = _ukai(ukai, "POST", "/v1/busy", {})
    assert status == 503 and got == {"ok": False, "why": "Surasura is busy: try again later", "kind": "busy"}
    status, got, _h = _ukai(ukai, "POST", "/v1/crashes", {})
    assert status == 503 and got["kind"] == "crashed" and "private" not in json.dumps(got)
    assert [p for p, _e in ukai.errors] == ["/v1/crashes"]


def test_a_json_body_gone_silent_is_the_callers_400_never_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    monkeypatch.setattr(door, "EXT_TIMEOUT", 0.5)
    errors = []
    ext = door.Extension({"POST /v1/echo": lambda call: call.json()}, lambda: (ORIGIN, TOKEN))
    d = door.Door({}, str(tmp_path), on_error=lambda path, e: errors.append(path), extension=ext).start()
    try:
        with socket.create_connection((door.HOST, d.ext_port), timeout=10) as s:
            s.sendall((f"POST /v1/echo HTTP/1.1\r\nHost: {door.HOST}:{d.ext_port}\r\nOrigin: {ORIGIN}\r\n"
                       f"{door.EXT_TOKEN_HEADER}: {TOKEN}\r\nContent-Length: 500\r\n\r\n").encode() + b'{"cues": [')
            answer = s.recv(4096).decode("utf-8", "replace")            # (the socket stays open: silent, not closed)
        assert answer.startswith(("HTTP/1.0 400", "HTTP/1.1 400")) and errors == []
    finally:
        d.stop()


def test_a_route_that_takes_no_body_still_answers_and_a_second_read_fails_at_once(ukai):
    """An unread body is dropped before the answer (Windows resets an unread socket); a route reading its body
    twice is a bug said at once (a crash), never a wait for bytes that won't come."""
    status, got, _h = _ukai(ukai, "POST", "/v1/unread", os.urandom(200 * 1024))
    assert status == 200 and got == {"ok": True} and ukai.calls == [("unread",)]
    began = time.monotonic()
    status, got, _h = _ukai(ukai, "POST", "/v1/twice", {"cues": []})
    assert status == 503 and got["kind"] == "crashed" and time.monotonic() - began < 5
    assert [p for p, _e in ukai.errors] == ["/v1/twice"]


# --- the port --------------------------------------------------------------------------------------------------------- #
def _hold_a_run():
    """A run of EXT_PORTS_MORE + 1 free ports side by side, each held by a listening socket — found below every
    system's dynamic range (Windows hands out 49152+, Linux 32768+: every outgoing connection on the PC takes its own
    port from there). A run from there could lose the port a test frees to any connection made in the gap (the 3.0.20
    cut's --all: `None == 49689`); here only a program binding that very port could take it. Blocks stay aligned, so
    two runs of this side by side never take from each other, and the door's real ports are skipped."""
    n = door.EXT_PORTS_MORE + 1
    real = range(REAL_EXT_PORT, REAL_EXT_PORT + n)
    for base in range(20000, 32768 - n, n):
        if base in real or base + n - 1 in real:
            continue
        held = []
        for p in range(base, base + n):
            s = socket.socket()
            try:
                s.bind((door.HOST, p))
            except OSError:
                s.close()
                break
            s.listen()
            held.append(s)
        if len(held) == n:
            return held
        for s in held:
            s.close()
    pytest.skip("no run of free ports here")


def test_a_port_taken_between_the_pick_and_the_bind_moves_to_the_next(tmp_path, monkeypatch):
    """Another program on the learner's PC takes 27631 after nothing held it, just before the door binds it: the door
    goes on to the next (Ukai says hello on each), never gives up while one of its ports is free."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    held = _hold_a_run()
    ports = [s.getsockname()[1] for s in held]
    for s in held:
        s.close()                                                     # the whole run free ...
    monkeypatch.setattr(door, "EXT_PORT", ports[0])
    strangers = []

    class Racing(door._ExtServer):
        def server_bind(self):
            if self.server_address[1] == ports[0] and not strangers:  # ... and taken in the gap, no sleep
                s = socket.socket()
                s.bind((door.HOST, ports[0]))
                s.listen()
                strangers.append(s)
            super().server_bind()

    monkeypatch.setattr(door, "_ExtServer", Racing)
    d = door.Door({}, str(tmp_path), extension=door.Extension({}, lambda: (ORIGIN, TOKEN))).start()
    try:
        assert strangers and d.ext_port == ports[1]
        assert _ask(d.ext_port, "GET", "/v1/hello")[0] == 200
    finally:
        d.stop()
        for s in strangers:
            s.close()


def test_a_taken_port_moves_to_the_next_and_none_free_listens_nowhere(tmp_path, monkeypatch):
    """Another program on 27631: the next one (Ukai says hello on each); none free: no listener, said once, and the
    page's class unharmed. A port another socket holds is never shared (Windows' SO_REUSEADDR would let it be)."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    held = []
    try:
        held = _hold_a_run()
        ports = [s.getsockname()[1] for s in held]
        monkeypatch.setattr(door, "EXT_PORT", ports[0])
        ext = door.Extension({}, lambda: (ORIGIN, TOKEN))
        last = next(s for s in held if s.getsockname()[1] == ports[-1])
        held.remove(last)
        last.close()                                                  # the last of the run free
        d = door.Door({}, str(tmp_path), extension=ext).start()
        try:
            assert d.ext_port == ports[-1]
            assert _ask(d.ext_port, "GET", "/v1/hello")[0] == 200
        finally:
            d.stop()
        s = socket.socket()
        s.bind((door.HOST, ports[-1]))
        s.listen()
        held.append(s)
        errors = []
        d = door.Door({}, str(tmp_path), on_error=lambda path, e: errors.append(path), extension=ext).start()
        try:
            assert d.ext_port is None and errors == ["extension"] and d.port
        finally:
            d.stop()
    finally:
        for s in held:
            s.close()


def test_stop_closes_ukais_listener_too(ukai):
    port = ukai.ext_port
    assert _ask(port, "GET", "/v1/hello")[0] == 200
    ukai.stop()
    assert ukai.ext_port is None
    with pytest.raises(OSError):
        _ask(port, "GET", "/v1/hello")
