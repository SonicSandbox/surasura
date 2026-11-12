"""The journey's door to the app (Michi-SW, 3.1 prototype; the 3.0 plan's `tracks/pipeline/work/swap/SWAP-PROTO.md`).

The journey page opens from its FILE, as it always has, and calls this small server for a press while the window
runs (Sonic, 2026-10-28: one page -> app layer, never one channel per button; the page's open no slower than today).
⇄ Swap is its first route; the stone's ✓, Ignore, Known and *mine this* are later rows of the same table.

- **Loopback only:** bound to 127.0.0.1 on a port the system picks; a request whose `Host` isn't that address and
  port is refused (a web page can't reach it through a name that points here: DNS rebinding).
- **One token a session, handed only to the page the window opens** (review 1's #4, Michi-SW2: before, a file any
  local page could read with a `<script>` tag held it): *Your journey* opens the report through a one-time page
  (`launch_page`: `results/door-secret-<random>.html`, its name unguessable, removed after LAUNCH_S or at stop) that
  replaces itself with the report at `#door=<port>.<token>`; the report takes it out of its address at once and keeps
  it for that tab (`sessionStorage`). A report opened any other way (by hand, from Junban) has no door and says so.
  Every call carries the token (`hmac.compare_digest`); a call from a web page (an `Origin` other than `null`, a file
  page's) is refused before its token is read.
- **Simple requests only:** `POST /v1/<route>` with a `text/plain` JSON body (no custom header, so no CORS
  preflight); `GET /v1/clip/<name>?t=<token>` for an `<audio>` / `<img>` the page shows. Bodies over 64 KB are refused.
- The route's answer is JSON; a route that raises answers `{"ok": false, "error": <its plain words>}`.

Standard library only. `start(routes)` from the window after its first frame (an earlier window's one-time pages
swept), `stop()` at quit (this door's pages removed).
"""
import hmac
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HOST = "127.0.0.1"
# The one-time page's name is a secret's, so Send report's scrub leaves it out (`report.SECRET_NAMES`: *secret*): it
# holds the token. Every `door-secret*` in the folder is swept at start (a killed window's; the first prototype's .js)
PREFIX = "door-secret"
LAUNCH_S = 120.0                # the one-time page's life: a cold browser start on the laptop has read it long before
VERSION = 1
MAX_BODY = 64 * 1024
CLIP_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\.(mp3|ogg|m4a|opus|wav|jpg|jpeg|png|webp|gif|avif)")
TYPES = {"mp3": "audio/mpeg", "ogg": "audio/ogg", "opus": "audio/ogg", "m4a": "audio/mp4", "wav": "audio/wav",
         "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif",
         "avif": "image/avif"}


class RouteError(Exception):
    """A route's refusal in plain words (the page shows `message`); `kind` for the page to act on."""

    def __init__(self, message, kind="refused"):
        super().__init__(message)
        self.message, self.kind = message, kind


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

        def do_GET(self):
            if not self._allowed():
                return self._send(403, {"ok": False, "error": "refused"})
            parts = urlsplit(self.path)
            token = (parse_qs(parts.query).get("t") or [""])[0]
            if not door.token_ok(token):
                return self._send(403, {"ok": False, "error": "refused"})
            if not parts.path.startswith("/v1/clip/"):
                return self._send(404, {"ok": False, "error": "no such route"})
            name = parts.path[len("/v1/clip/"):]
            path = door.clip(name)
            if path is None:
                return self._send(404, {"ok": False, "error": "no such clip"})
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                return self._send(404, {"ok": False, "error": "no such clip"})
            self._send(200, data, TYPES[name.rsplit(".", 1)[1].lower()])

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
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"ok": False, "error": "not JSON"})
            if not isinstance(body, dict) or not door.token_ok(body.get("token")):
                return self._send(403, {"ok": False, "error": "refused"})
            path = urlsplit(self.path).path
            route = door.routes.get(path[len("/v1/"):]) if path.startswith("/v1/") else None
            if route is None:
                return self._send(404, {"ok": False, "error": "no such route"})
            body.pop("token", None)
            try:
                answer = route(body)
            except RouteError as e:
                return self._send(200, {"ok": False, "error": e.message, "kind": e.kind})
            except Exception as e:                  # a route's bug: said, never the window's crash
                door.on_error(path, e)
                return self._send(200, {"ok": False, "error": "Something went wrong in Surasura: try again.",
                                        "kind": "crashed"})
            self._send(200, dict({"ok": True}, **(answer or {})))

    return Handler


class Door:
    """One door: `routes` {name: fn(body dict) -> dict}; `clips` the folder `GET /v1/clip/<name>` serves from;
    `folder` where its file goes (the report's folder)."""

    def __init__(self, routes, folder, clips=None, on_error=None):
        self.routes = dict(routes)
        self.routes.setdefault("hello", lambda _body: {"version": VERSION})
        self.folder, self.clips = folder, clips
        self.token = secrets.token_urlsafe(24)
        self.on_error = on_error or (lambda _path, _e: None)
        self.port = None
        self._server = self._thread = None
        self._pages = set()                         # this door's one-time pages still on disk
        self._pages_lock = threading.Lock()

    def token_ok(self, token):
        return isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))

    def clip(self, name):
        """The file `name` in the clips folder, or None (a name of the clip form only, never a path)."""
        if not self.clips or not CLIP_NAME.fullmatch(name or ""):
            return None
        path = os.path.join(self.clips, name)
        return path if os.path.isfile(path) else None

    def start(self):
        self._server = ThreadingHTTPServer((HOST, 0), _handler(self))
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="journey-door", daemon=True)
        self._thread.start()
        self._sweep()
        return self

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
        `&<rest>`, the report's own fragment: `file=<name>`) -> its path. Removed after LAUNCH_S, and at stop."""
        target = "%s#door=%d.%s%s" % (report, self.port, self.token, "&" + rest if rest else "")
        path = os.path.join(folder, "%s-%s.html" % (PREFIX, secrets.token_hex(16)))
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write('<!DOCTYPE html><meta charset="utf-8"><title>Surasura</title><body style="background:#1e1e1e">'
                    '<script>location.replace(%s);</script>\n' % json.dumps(target).replace("</", "<\\/"))
        with self._pages_lock:
            self._pages.add(path)
        timer = threading.Timer(LAUNCH_S, self._drop, (path,))
        timer.daemon = True
        timer.start()
        return path

    def _drop(self, path):
        with self._pages_lock:
            self._pages.discard(path)
        _remove(path)

    def stop(self):
        if self._server is None:
            return
        with self._pages_lock:
            pages, self._pages = self._pages, set()
        for path in pages:
            _remove(path)
        self._server.shutdown()
        self._server.server_close()
        self._server = None


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


def start(routes, folder, clips=None, on_error=None):
    """The window's door (one a process); a second start replaces the first."""
    global _door
    stop()
    _door = Door(routes, folder, clips, on_error).start()
    return _door


def stop():
    global _door
    if _door is not None:
        _door.stop()
        _door = None
