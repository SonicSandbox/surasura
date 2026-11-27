"""The journey's door to the app (built by Michi-SW for ⇄ Swap, #385, the 3.0 plan's
`tracks/pipeline/work/swap/SWAP-PROTO.md`; split out on its own for 3.0.12 by Kotoba-K, Michi-J2's scope decision 4:
`tracks/window/work/journey-v2/SCOPE.md`).

The journey page opens from its FILE, as it always has, and calls this small server for a press while the window
runs (Sonic, 2026-10-28: one page -> app layer, never one channel per button; the page's open no slower than today).
Its routes are one table the window gives (`start(routes, ...)`): Known and Ignore first (Kotoba-K); the stone's ✓,
⇄ Swap and *mine this* are later rows of the same table.

- **Loopback only:** bound to 127.0.0.1 on a port the system picks; a request whose `Host` isn't that address and
  port is refused (a web page can't reach it through a name that points here: DNS rebinding).
- **One token a session, handed only to the page the window opens** (review 1's #4, Michi-SW2: before, a file any
  local page could read with a `<script>` tag held it): *Your journey* opens the report through a one-time page
  (`launch_page`: `results/door-secret-<random>.html`, its name unguessable) that replaces itself with the report at
  `#door=<port>.<token>`; after LAUNCH_S or at stop it is written again without the door (a browser slower than that
  still opens the report: review 2), and swept at the next start; the report takes it out of its address at once and keeps
  it for that tab (`sessionStorage`). A report opened any other way (by hand, from Junban) has no door and says so.
  Every call carries the token (`hmac.compare_digest`); a call with any `Origin` but `null` (a file page's — which a
  sandboxed frame also sends, so the token stays the gate) is refused before its token is read.
- **Simple requests only:** `POST /v1/<route>` with a `text/plain` JSON body (no custom header, so no CORS
  preflight). Bodies over 64 KB are refused.
- **The one GET** (journey v3 SPEC §3.3, #385's): an `<audio>` element can't send a body, so `GET /v1/clip/<name>`
  serves a file the app handed out this session (`serve_file`: a name of 128 random bits, the last CLIPS_KEPT kept),
  and nothing else. The Host check holds for it; the request log never takes a name.
- The route's answer is JSON; a route that raises answers `{"ok": false, "error": <its plain words>}`.
- **At quit** (`stop`), a call already in its route is answered first (STOP_WAIT_S at most), and a call that comes
  after the quit began is answered `{"ok": false, "kind": "closed"}` (503): the page keeps it in its queue.

The routes themselves are the journey's registry (`app/services/journey_door.py`). Standard library only.
`start(routes)` from the window after its first frame (an earlier window's one-time pages swept), `stop()` at quit
(this door's pages removed).

**Ukai's caller class** (鵜飼 Ukai, the browser extension: TheForge `Projects/Houseki/Ukai/SPEC.md` §6 U-S0, its
checks adapted from #474's `online_receiver`): the extension can't be handed a token through a page, and it
calls a fixed address, so it has a listener of its own on the same door (`Extension`), with its own rules:
- **127.0.0.1:EXT_PORT** (27631, its CONTRACT.md), or the next EXT_PORTS_MORE when it's taken (Ukai says hello on
  each); never a port another socket holds (Windows' SO_REUSEADDR would share it). The Host check and a loopback peer.
- **An extension's Origin only:** any Origin but `chrome-extension://<id>` is refused (a web page's, a file page's
  `null`), and a POST without one (Chrome stamps an extension's POST; its GET carries none, as measured). No CORS header
  is ever sent, no preflight answered.
- **Paired routes** need the paired token (`X-Surasura-Token`, constant time) **and** the paired Origin (`pairing()`
  -> (origin, token), read at every call: *Forget* refuses at once); `hello` and the routes `open` names (U-S1's
  pairing) need neither.
- **#474's caps and timeouts:** a JSON body ≤ EXT_MAX_JSON (`Call.json`), a streamed one ≤ EXT_MAX_STREAM to a file,
  EXT_CHUNK at a time, never whole in memory, in place only once whole (`Call.save`); no length 411, over 413 (a
  small body read and dropped first: unread, Windows resets the socket before the answer is read), cut short 400; a
  socket silent EXT_TIMEOUT ends. Answers `{"ok", "why", "kind"}` with a status the extension reads (CONTRACT.md).
- **Off until Ukai's pairing exists** (U-S1): `EXTENSION_ON`. While it's False nothing listens for the extension.
"""
import hmac
import json
import os
import re
import secrets
import socket
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
# The one-time page's name is a secret's, so Send report's scrub leaves it out (`report.SECRET_NAMES`: *secret*): it
# holds the token. Every `door-secret*` in the folder is swept at start (a killed window's; the first prototype's .js)
PREFIX = "door-secret"
LAUNCH_S = 120.0                # the one-time page's life: a cold browser start on the laptop has read it long before
VERSION = 1
MAX_BODY = 64 * 1024
CLIP_PATH = "/v1/clip/"
CLIPS_KEPT = 40                 # the clips a page may still play (`serve_file`): older names answer 404
STOP_WAIT_S = 3.0               # the quit waits this long at most for the calls already in a route

# Ukai's caller class (`Extension`; #474's numbers)
EXTENSION_ON = False            # off until Ukai's pairing (U-S1) exists: until then nothing listens on EXT_PORT
EXT_PORT = 27631                # where Ukai says hello first (its CONTRACT.md) ...
EXT_PORTS_MORE = 4              # ... then on the next few, when another program holds it
EXT_ORIGIN = "chrome-extension://"
EXT_TOKEN_HEADER = "X-Surasura-Token"
EXT_MAX_JSON = 4 * 1024 * 1024  # a two-hour film's cues are about 200 KB
EXT_MAX_STREAM = 40 * 1024 * 1024   # one recorded line's clip, a few seconds of video and sound
EXT_CHUNK = 64 * 1024           # a streamed body is read and written this much at a time
EXT_DRAIN = 1024 * 1024         # a refused body this small is read and dropped before the answer
EXT_TIMEOUT = 15.0              # a socket silent this long ends (a 40 MB clip on loopback takes well under a second)
NOT_UKAI = "only Surasura's browser extension, on this computer"


class RouteError(Exception):
    """A route's refusal in plain words (the page shows `message`); `kind` for the page to act on; `status` the HTTP
    status Ukai's class answers it with (the page's class always answers 200)."""

    def __init__(self, message, kind="refused", status=400):
        super().__init__(message)
        self.message, self.kind, self.status = message, kind, status


def _same(given, kept):
    """Is `given` the token `kept`? Constant time; no token kept takes nothing."""
    if not isinstance(given, str) or not isinstance(kept, str) or not kept:
        return False
    try:
        sent = given.encode("utf-8")
    except UnicodeEncodeError:                      # (a lone surrogate, "\ud800": no token of ours)
        return False
    return hmac.compare_digest(sent, kept.encode("utf-8"))


def _handler(door):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SurasuraDoor/%d" % VERSION
        sys_version = ""
        timeout = 10                                # (a client that sends nothing more never holds a thread)

        def log_message(self, fmt, *args):          # (the window's log never takes a request line: its token)
            return

        def _send(self, code, body, kind="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "null")     # a file page's origin, and no other
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self):
            """The address and the page's origin: this door's own address, from a file page (or no page at all)."""
            if self.headers.get("Host") != "%s:%d" % (HOST, door.port):
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin == "null"

        def do_OPTIONS(self):                       # (no preflight is ever needed; anything asking one is refused)
            self._send(403, {"ok": False, "error": "refused"})

        def do_GET(self):                           # (every route is a POST; the one GET is a clip, `serve_file`)
            if not self._allowed():
                return self._send(403, {"ok": False, "error": "refused"})
            path = _path(self.path)
            clip = door.clip(path[len(CLIP_PATH):]) if path.startswith(CLIP_PATH) else None
            if clip is None:
                return self._send(404, {"ok": False, "error": "no such route"})
            try:
                with open(clip[0], "rb") as f:
                    data = f.read()
            except OSError:
                return self._send(404, {"ok": False, "error": "no such clip"})
            self._send(200, data, clip[1])

        def do_POST(self):
            if not self._allowed():
                return self._send(403, {"ok": False, "error": "refused"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._send(413, {"ok": False, "error": "too big"})
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError, RecursionError):     # (a body nested past Python's depth too)
                return self._send(400, {"ok": False, "error": "not JSON"})
            if not isinstance(body, dict) or not door.token_ok(body.get("token")):
                return self._send(403, {"ok": False, "error": "refused"})
            path = _path(self.path)
            route = door.routes.get(path[len("/v1/"):]) if path.startswith("/v1/") else None
            if route is None:
                return self._send(404, {"ok": False, "error": "no such route"})
            body.pop("token", None)
            if not door.enter():
                return self._send(503, {"ok": False, "error": "Surasura is closing.", "kind": "closed"})
            try:
                try:
                    answer = route(body)
                    data = json.dumps(dict({"ok": True}, **(answer or {})), ensure_ascii=False).encode("utf-8")
                except RouteError as e:
                    return self._send(200, {"ok": False, "error": e.message, "kind": e.kind})
                except Exception as e:              # a route's bug (or an answer JSON can't carry): said, never a crash
                    door.on_error(path, e)
                    return self._send(200, {"ok": False, "error": "Something went wrong in Surasura: try again.",
                                            "kind": "crashed"})
                self._send(200, data)
            finally:
                door.leave()

    return Handler


class BodyError(Exception):
    """A body Ukai's class won't take (no length, too large, cut short, not JSON): `status` and `why` its answer."""

    def __init__(self, status, why):
        super().__init__(why)
        self.status, self.why = status, why


class Extension:
    """Ukai's caller class: `routes` {"<METHOD> <path regex>": fn(call) -> dict} (the whole path matches; its groups
    are `call.groups`); `pairing()` -> (origin, token) of the paired extension, or None; `open` the routes reachable
    unpaired (`GET /v1/hello` always)."""

    def __init__(self, routes, pairing, open=()):
        table = dict(routes)
        table.setdefault("GET /v1/hello", lambda _call: {"app": "surasura", "door": VERSION})
        unpaired = set(open) | {"GET /v1/hello"}
        self.pairing = pairing
        self._routes = []
        for key, fn in table.items():
            method, pattern = key.split(" ", 1)
            self._routes.append((method, re.compile(pattern), fn, key in unpaired))

    def route(self, method, path):
        """-> (fn, groups, open) for the call, or None."""
        for m, pattern, fn, unpaired in self._routes:
            found = pattern.fullmatch(path) if m == method else None
            if found:
                return fn, found.groups(), unpaired
        return None

    def paired(self):
        """(origin, token) or None: a pairing that can't be read, or one that pins no extension, is none."""
        try:
            pair = self.pairing()
        except Exception:
            return None
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            return None
        origin, token = pair
        if not isinstance(origin, str) or not origin.startswith(EXT_ORIGIN) or len(origin) == len(EXT_ORIGIN):
            return None
        return (origin, token) if isinstance(token, str) and token else None


def _content_length(headers):
    """A request's Content-Length, or -1 (none, or not a number)."""
    try:
        return int(headers.get("Content-Length") or -1)
    except ValueError:
        return -1


class Call:
    """One of Ukai's calls as its route sees it: `groups` (the path's), `headers`; its body read once, by `json` or
    `save` (a route that reads neither takes no body: the door drops a small one)."""

    def __init__(self, handler, groups):
        self.groups, self.headers = groups, handler.headers
        self._handler = handler

    def _length(self, limit):
        if self._handler.body_read:                 # (a route's bug: a second read would wait out EXT_TIMEOUT)
            raise RuntimeError("a call's body is read once")
        length = _content_length(self.headers)
        if length < 0:
            raise BodyError(411, "Content-Length is needed")
        if length > limit:
            raise BodyError(413, "the body is too large")
        self._handler.body_read = True
        return length

    def _read(self, n):
        return self._handler.rfile.read(n)

    def json(self, limit=None):
        """The body as a JSON object (≤ EXT_MAX_JSON) -> dict; raises BodyError."""
        length = self._length(EXT_MAX_JSON if limit is None else limit)
        try:
            data = self._read(length)
        except OSError:                             # (gone silent past EXT_TIMEOUT, or reset)
            data = b""
        if len(data) != length:                     # cut short (a tab closed mid-upload)
            self._handler.close_connection = True
            raise BodyError(400, "the body ended before its Content-Length")
        try:
            body = json.loads(data.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise BodyError(400, "the body must be JSON") from None
        if not isinstance(body, dict):
            raise BodyError(400, "the body must be a JSON object")
        return body

    def save(self, path, limit=None):
        """The body streamed to `path` (≤ EXT_MAX_STREAM, EXT_CHUNK at a time) -> its size. Written to a `.part` beside
        it and put in place only once whole: a body cut short or gone silent leaves nothing, and a file already at `path`
        as it was. Raises BodyError (OSError from the disk: the route's to answer)."""
        length = self._length(EXT_MAX_STREAM if limit is None else limit)
        part, left = "%s.%s.part" % (path, secrets.token_hex(4)), length     # (its own: a retry beside it never mixes)
        try:
            with open(part, "wb") as f:
                while left:
                    try:
                        chunk = self._read(min(EXT_CHUNK, left))
                    except OSError:                 # (gone silent past EXT_TIMEOUT, or reset)
                        chunk = b""
                    if not chunk:
                        self._handler.close_connection = True
                        raise BodyError(400, "the body ended before its Content-Length")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(part, path)
        except BaseException:
            _remove(part)
            raise
        return length


class _ExtServer(ThreadingHTTPServer):
    """Ukai's listener: a port another socket holds is never shared (SO_REUSEADDR on Windows would let this bind
    beside it: two Surasuras on one port), and on Windows none may bind beside this one."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _loopback(host):
    """A peer of the listener on 127.0.0.1: an IPv4 loopback address (no other can reach it; said all the same)."""
    return isinstance(host, str) and host.startswith("127.")


def _ext_handler(door):
    ext = door.extension

    class Handler(BaseHTTPRequestHandler):
        server_version = "SurasuraDoor/%d" % VERSION
        sys_version = ""
        timeout = EXT_TIMEOUT                       # (a client gone silent ends; the next is served)

        def log_message(self, fmt, *args):          # (never a request line: the log takes no token)
            return

        def _send(self, code, payload):
            if not self.body_read:                  # an answer before the body was read: a small one read and
                self.body_read = True               # dropped first (unread, Windows resets the socket before the
                length = _content_length(self.headers)                          # answer is read)
                if 0 < length <= EXT_DRAIN:
                    try:
                        self.rfile.read(length)
                    except OSError:
                        pass
                self.close_connection = True
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()                      # (no Access-Control header, ever: a page reads nothing)
            self.wfile.write(data)

        def _refuse(self, code, why=NOT_UKAI):
            self._send(code, {"ok": False, "why": why, "kind": "refused"})

        def _allowed(self):
            """Its own address, a loopback peer, and an extension's Origin (a GET may have none; a POST must)."""
            port = self.server.server_address[1]    # (its own: still right while the quit drains)
            if self.headers.get("Host") != "%s:%d" % (HOST, port) or not _loopback(self.client_address[0]):
                return False
            origin = self.headers.get("Origin")
            if origin is None:
                return self.command == "GET"
            return origin.startswith(EXT_ORIGIN) and len(origin) > len(EXT_ORIGIN)

        def _serve(self):
            self.body_read = False
            if not self._allowed():
                return self._refuse(403)
            path = _path(self.path)
            found = ext.route(self.command, path)
            if found is None:
                return self._refuse(404, "no such route")
            fn, groups, unpaired = found
            if not unpaired:                        # the token first: without it nothing says a pairing exists
                pair = ext.paired()
                if pair is None or not _same(self.headers.get(EXT_TOKEN_HEADER), pair[1]):
                    return self._refuse(401, "not paired, or the wrong token")
                origin = self.headers.get("Origin")
                if origin is not None and origin != pair[0]:    # (a GET carries none: the token is its gate)
                    return self._refuse(403, "another extension is paired with Surasura")
            if not door.enter():
                return self._send(503, {"ok": False, "why": "Surasura is closing.", "kind": "closed"})
            try:
                try:
                    answer = fn(Call(self, groups))
                    data = json.dumps(dict({"ok": True}, **(answer or {})), ensure_ascii=False,
                                      allow_nan=False).encode("utf-8")      # (NaN: no JSON the extension reads)
                except BodyError as e:
                    return self._send(e.status, {"ok": False, "why": e.why, "kind": "body"})
                except RouteError as e:
                    return self._send(e.status, {"ok": False, "why": e.message, "kind": e.kind})
                except Exception as e:              # a route's bug: said plainly, never its text; Ukai keeps the call
                    door.on_error(path, e)
                    return self._send(503, {"ok": False, "why": "Something went wrong in Surasura: try again.",
                                            "kind": "crashed"})
                self._send(200, data)
            finally:
                door.leave()

        def do_GET(self):
            self._serve()

        def do_POST(self):
            self._serve()

        def do_OPTIONS(self):                       # (no preflight is ever answered yes)
            self.body_read = False
            self._refuse(403)

    return Handler


class Door:
    """One door: `routes` {name: fn(body dict) -> dict}; `folder` where its one-time pages go (the report's folder);
    `extension` Ukai's caller class (`Extension`), listening only while EXTENSION_ON."""

    def __init__(self, routes, folder, on_error=None, extension=None):
        self.routes = dict(routes)
        self.routes.setdefault("hello", lambda _body: {"version": VERSION})
        self.folder = folder
        self.token = secrets.token_urlsafe(24)
        self.on_error = on_error or (lambda _path, _e: None)
        self.port = None
        self._server = self._thread = None
        self.extension = extension
        self.ext_port = None
        self._ext_server = None
        self._pages = {}                            # this door's one-time pages still holding its token: path -> fragment
        self._pages_lock = threading.Lock()
        self._clips = OrderedDict()                 # name -> (path, content type): `serve_file`'s, the newest last
        self._calls = 0                             # calls inside a route now (`enter` / `leave`)
        self._closing = False
        self._calls_done = threading.Condition()

    def token_ok(self, token):
        return _same(token, self.token)

    def enter(self):
        """A call going into its route -> False once the quit has begun (the call is answered *closed*)."""
        with self._calls_done:
            if self._closing:
                return False
            self._calls += 1
            return True

    def leave(self):
        with self._calls_done:
            self._calls -= 1
            self._calls_done.notify_all()

    def serve_file(self, path, kind):
        """`path` playable by the page at the URL this returns (`GET /v1/clip/<name>`, `kind` its Content-Type), until
        CLIPS_KEPT newer ones are handed out or the door stops."""
        name = secrets.token_hex(16)
        with self._pages_lock:
            self._clips[name] = (path, kind)
            while len(self._clips) > CLIPS_KEPT:
                self._clips.popitem(last=False)
        return "http://%s:%d%s%s" % (HOST, self.port, CLIP_PATH, name)

    def clip(self, name):
        with self._pages_lock:
            return self._clips.get(name)

    def start(self):
        self._server = ThreadingHTTPServer((HOST, 0), _handler(self))
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="journey-door", daemon=True)
        self._thread.start()
        if EXTENSION_ON and self.extension is not None:
            self._listen_for_extension()
        self._sweep()
        return self

    def _listen_for_extension(self):
        """Ukai's listener on the first free port of EXT_PORT and the EXT_PORTS_MORE after it; none free: said once
        (`on_error("extension", …)`), and the page's class goes on alone."""
        for port in range(EXT_PORT, EXT_PORT + EXT_PORTS_MORE + 1):
            try:
                server = _ExtServer((HOST, port), _ext_handler(self))
            except OSError:
                continue
            self.ext_port, self._ext_server = port, server
            threading.Thread(target=server.serve_forever, name="ukai-door", daemon=True).start()
            return
        self.on_error("extension", OSError(f"ports {EXT_PORT}–{EXT_PORT + EXT_PORTS_MORE} are all taken"))

    def _sweep(self):
        """An earlier window's one-time pages (a killed window leaves its own): each holds a dead token."""
        try:
            names = os.listdir(self.folder)
        except OSError:
            return
        for name in names:
            if name.startswith(PREFIX):
                _remove(os.path.join(self.folder, name))

    def launch_page(self, folder, report, rest=""):
        """A one-time page in `folder` that opens `report` (a name in that folder) at `#door=<port>.<token>` (then
        `&<rest>`, the report's own fragment: `file=<name>`) -> its path. After LAUNCH_S, and at stop, written again
        without the door. OSError on a door already stopped (a press racing the quit: no page holds a dead token)."""
        fragment = "%s#door=%d.%s%s" % (report, self.port, self.token, "&" + rest if rest else "")
        path = os.path.join(folder, "%s-%s.html" % (PREFIX, secrets.token_hex(16)))
        os.makedirs(folder, exist_ok=True)
        with self._pages_lock:
            if self._server is None:
                raise OSError("the door is closed")
            _page(path, fragment)
            self._pages[path] = "%s#%s" % (report, rest) if rest else report
        timer = threading.Timer(LAUNCH_S, self._retire, (path,))
        timer.daemon = True
        timer.start()
        return path

    def _retire(self, path):
        """The page's door taken out: it still opens the report (a browser that reads it late), never the token."""
        with self._pages_lock:
            plain = self._pages.pop(path, None)
            if plain is not None:
                try:
                    _page(path, plain)
                except OSError:
                    _remove(path)

    def stop(self):
        with self._pages_lock:                      # (closed and listed at once: no page slips in between)
            server, self._server = self._server, None
            ext, self._ext_server, self.ext_port = self._ext_server, None, None
            pages = list(self._pages)
            self._clips.clear()
        if server is None:
            return
        with self._calls_done:                      # the calls already in a route answered first, a new one *closed*
            self._closing = True
            self._calls_done.notify_all()           # (anyone waiting for the quit to begin hears it)
            drained = self._calls_done.wait_for(lambda: self._calls == 0, STOP_WAIT_S)
        if not drained:                             # (said: the quit goes on with a route still running)
            self.on_error("stop", TimeoutError(f"a call still in its route after {STOP_WAIT_S:g} s"))
        for path in pages:
            self._retire(path)
        ender = None
        if ext is not None:                         # (side by side: each shutdown waits out its own poll)
            ender = threading.Thread(target=ext.shutdown, name="ukai-door-stop", daemon=True)
            ender.start()
        server.shutdown()
        server.server_close()
        if ender is not None:
            ender.join()
            ext.server_close()


def _page(path, target):
    """A page that replaces itself with `target` (a name in its folder, with its fragment)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write('<!DOCTYPE html><meta charset="utf-8"><title>Surasura</title><body style="background:#1e1e1e">'
                '<script>location.replace(%s);</script>\n' % json.dumps(target).replace("</", "<\\/"))


def _path(target):
    """A request's path: its target before any query (an absolute or malformed target: no route of ours)."""
    return target.split("?", 1)[0].split("#", 1)[0]


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


_door = None


def current():
    """The door open in this process, or None (a Junban window, a 2.x one, a test)."""
    return _door


def launch_page(folder, report, rest=""):
    """The open door's one-time page for `report` (`Door.launch_page`), or None: no door here, or it can't be
    written (the report then opens as it is, without the door)."""
    d = _door
    if d is None or d.port is None:
        return None
    try:
        return d.launch_page(folder, report, rest)
    except OSError:
        return None


def serve_file(path, kind):
    """The open door's URL for `path` (`Door.serve_file`), or None: no door here."""
    d = _door
    if d is None or d.port is None:
        return None
    return d.serve_file(path, kind)


def start(routes, folder, on_error=None, extension=None):
    """The window's door (one a process); a second start replaces the first. `extension`: Ukai's caller class
    (`Extension`), listening only while EXTENSION_ON."""
    global _door
    stop()
    _door = Door(routes, folder, on_error, extension).start()
    return _door


def stop():
    global _door
    if _door is not None:
        _door.stop()
        _door = None
