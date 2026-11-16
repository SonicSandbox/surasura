"""The browser extension's subtitles, taken in (Mattias's Netflix and Disney+ wish): a small extension in the learner's
own browser sends the subtitle the player loaded to Surasura on the same computer, and it becomes a library item the
way a YouTube transcript does. The contract both sides build against is the extension's `CONTRACT.md` (v1):

- `GET /v1/hello` -> {"app", "version", "contract", "languages"}: is Surasura there (the extension sends what it kept
  once it answers).
- `POST /v1/online-subtitle` with `X-Surasura-Token` and {"schema": 1, "site", "video_id", "url", "language", "title",
  "show": {"title", "season", "episode"} (none for a film), "cues": [[start s, end s, text], …]} -> 200 {"ok", "added",
  "item"} (`added` false: that video is in already), 400 {"ok": false, "why"}, 401, 503 (busy: try again later).

**Never a video, never DRM.** Only the text the browser already shows is sent; nothing here contacts anything. The
picture and sound a card needs come later, from the extension itself (`runner.BROWSER_WAIT`: the seam).

**Safe on a shared computer** (each its own check, `Receiver`):
- loopback only: bound to 127.0.0.1, and a peer that isn't loopback is refused all the same;
- a token the learner copies once from Settings (`kept_token`: in the persistent user data folder, never settings.json; compared in constant time);
- no web page: a request naming an `Origin` that isn't a browser extension's is refused (a page's script can reach
  127.0.0.1, an extension's background can't be faked by one), and no CORS header is ever sent;
- a body over `MAX_BODY` is refused before it is read.

**The item** (`write`, `record`): a transcript as the YouTube downloader writes one — its `.txt` (the downloader's
header: `analyzer.transcript_body` reads it as one) and its cue sidecar (`<stem>.surasura.json`, each cue
[text, start, end]: the end too, which the later mining reads) — into the language's Processed folder, a loose drop
whose title is its record's show (a film: its own title). The file's name ends `[netflix-<id>]` /
`[disneyplus-<id>]` (`path_utils.SITE_ID_RE`), so its `source_type` is the site: an online item, ▶ its page.

Standard library only; no Qt (the window's glue is `app/qt/windows.py` `start_receiver`).
"""
import base64
import binascii
import hashlib
import hmac
import logging
import http.server
import ipaddress
import json
import os
import re
import secrets
import threading

log = logging.getLogger(__name__)

HOST, PORT = "127.0.0.1", 27631
CONTRACT, SCHEMA = 3, 1              # 2: mining after the fact (`connect.browser`); 3: YouTube links
LANGUAGES = ("ja", "zh")
SITES = {"netflix": "Netflix", "disneyplus": "Disney+"}     # `source_type` -> the site's name (`play.SITES` too)
PRODUCER = "browser"                    # the pairing record's producer (`placing_rules`' `browser`)
MAX_BODY = 4 * 1024 * 1024              # a two-hour film's cues are about 200 KB
DRAIN = 1024 * 1024                     # an over-large body this small is read and dropped before the 413
MAX_CLIP = 40 * 1024 * 1024             # one recorded line, a few seconds of video and sound
_CLIP_PATH = re.compile(r"/v1/jobs/(\d{1,9})/clips/(\d{1,5})")
_DONE_PATH = re.compile(r"/v1/jobs/(\d{1,9})/done")
YOUTUBE_HOSTS = ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")
MAX_LINKS = 50
MAX_CUES = 20000
MAX_COVER = 400 * 1024                  # the show's artwork as the page shows it (the contract's limit)
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://", "safari-web-extension://")
TOKEN_HEADER = "X-Surasura-Token"
_ID = re.compile(r"[A-Za-z0-9-]{1,64}")         # Netflix's digits, Disney+'s UUID-like ids
_RESERVED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Bad(ValueError):
    """A body the contract doesn't take: `why` in plain words (the 400's)."""


class Refused(Exception):
    """Surasura won't take it as things stand (the YouTube downloader off, its risk tick not given): the 409's words."""


class Busy(Exception):
    """Surasura can't take it now (no library open, the store busy, read-only): the 503."""


TOKEN_FILE = "browser_extension_token.txt"


def new_token():
    return secrets.token_urlsafe(24)


def token_path():
    """Where the token is kept: the persistent user data folder (`path_utils.get_persistent_user_data_path`), never
    settings.json — a credential there would ship inside the release and leave with every export."""
    from app.path_utils import get_persistent_user_data_path
    return os.path.join(get_persistent_user_data_path(), TOKEN_FILE)


def read_token(path=None):
    """The kept token, or None (none made yet, or unreadable)."""
    try:
        with open(path or token_path(), encoding="utf-8") as f:
            token = f.read().strip()
        return token or None
    except OSError:
        return None


OLD_SETTING = "browser_extension_token"      # where a build before 8e1d45e7 kept the token (settings.json)


def adopt_token(values, path=None):
    """The token a build before 8e1d45e7 kept in settings.json (`OLD_SETTING` in `values`) put in the token's file,
    over one made since: an extension paired then holds it, and the one made in its place reached no extension (a
    pairing needs a *Copy token*, and the old value was still there to win). -> True when there was one to take over
    (the caller then takes the key out of settings.json); False otherwise."""
    old = values.get(OLD_SETTING) if hasattr(values, "get") else None     # (the settings service's frozen view)
    if not isinstance(old, str) or not old.strip():
        return False
    path = path or token_path()
    if read_token(path) != old.strip():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as f:
            f.write(old.strip())
        os.replace(path + ".part", path)
    return True


def kept_token(path=None):
    """The kept token, made and written once (when the learner first turns the listener on) -> it."""
    path = path or token_path()
    token = read_token(path)
    if token is None:
        token = new_token()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as f:
            f.write(token)
        os.replace(path + ".part", path)
    return token


def token_ok(given, kept):
    """Is `given` the kept token? Constant time; no kept token takes nothing."""
    if not isinstance(kept, str) or not kept or not isinstance(given, str):
        return False
    return hmac.compare_digest(given.encode("utf-8"), kept.encode("utf-8"))


def origin_ok(origin):
    """A request with no `Origin` (the extension's background, curl) or an extension's own; never a web page's."""
    return not origin or origin.startswith(EXTENSION_ORIGINS)


def _loopback(host):
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < 0:
        raise Bad("a cue's times must be seconds")
    return round(float(value), 3)


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def subtitle(body):
    """The posted body (bytes) -> the subtitle as the contract names it, checked and tidied; raises Bad."""
    try:
        got = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Bad("the body isn't JSON") from None
    if not isinstance(got, dict):
        raise Bad("the body isn't a JSON object")
    if got.get("schema") != SCHEMA:
        raise Bad(f"schema {SCHEMA} only")
    site = got.get("site")
    if site not in SITES:
        raise Bad(f"site must be one of {', '.join(SITES)}")
    video = str(got.get("video_id") or "")
    if not _ID.fullmatch(video):
        raise Bad("video_id is missing or not an id")
    url = got.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise Bad("url must be the video's https page")
    language = got.get("language")
    if language not in LANGUAGES:
        raise Bad(f"language must be one of {', '.join(LANGUAGES)}")
    title = got.get("title")
    title = " ".join(title.split()) if isinstance(title, str) else ""
    show = got.get("show")
    if show is not None:
        if not isinstance(show, dict) or not isinstance(show.get("title"), str) or not show["title"].strip():
            raise Bad("show needs its title")
        show = {"title": " ".join(show["title"].split()), "season": _number(show.get("season")),
                "episode": _number(show.get("episode"))}
    if not title and not show:
        raise Bad("title is missing")
    cues = got.get("cues")
    if not isinstance(cues, list) or not cues:
        raise Bad("cues are missing")
    if len(cues) > MAX_CUES:
        raise Bad("too many cues")
    tidy = []
    for cue in cues:
        if not isinstance(cue, list) or len(cue) != 3 or not isinstance(cue[2], str):
            raise Bad("each cue is [start, end, text]")
        start, end, text = _seconds(cue[0]), _seconds(cue[1]), " ".join(cue[2].split())
        if end < start:
            raise Bad("a cue ends before it starts")
        if text:
            tidy.append([start, end, text])
    if not tidy:
        raise Bad("every cue is empty")
    return {"site": site, "video_id": video, "url": url.split("#", 1)[0], "language": language,
            "title": title or show["title"], "show": show, "cues": tidy,
            "cover": got["cover"] if isinstance(got.get("cover"), str) else None}


def content_key(sub):
    """The pairing's key: one per site's video, so the same video is never a second item."""
    return f"{sub['site']}:{sub['video_id']}"


def _clean(name):
    return _RESERVED.sub("_", name).strip().rstrip(". ")[:80].rstrip(". ")


def file_name(sub):
    """`<Show> S01E03 <episode title> [netflix-<id>].txt`; a film `<title> [disneyplus-<id>].txt`."""
    show = sub["show"]
    parts = []
    if show:
        parts.append(_clean(show["title"]))
        if show["episode"]:
            parts.append(f"S{show['season'] or 1:02d}E{show['episode']:02d}")
        if sub["title"] != show["title"]:
            parts.append(_clean(sub["title"]))
    else:
        parts.append(_clean(sub["title"]))
    name = " ".join(p for p in parts if p) or sub["site"]
    return f"{name} [{sub['site']}-{sub['video_id']}].txt"


def text(sub):
    """The transcript: the downloader's header (`analyzer.transcript_body`), then a cue a line."""
    show = sub["show"]
    header = [sub["title"], f"{show['title'] if show else SITES[sub['site']]} |  | ",
              f"Captions: {sub['language']} (manual)", sub["url"], "", "-" * 60, ""]
    return "\n".join(header) + "\n".join(c[2] for c in sub["cues"]) + "\n"


def sidecar(sub):
    """The cue sidecar: what `cues._transcript` and ▶ read (`video_id`, `url`, `title`, cues [text, start, end] — the
    start first, as the downloader's [text, seconds]), the show for `record`."""
    return {"video_id": sub["video_id"], "url": sub["url"], "title": sub["title"], "site": sub["site"],
            "show": sub["show"], "cues": [[c[2], c[0], c[1]] for c in sub["cues"]]}


def write(folder, sub):
    """The transcript and its sidecar into `folder` (the language's Processed) -> the transcript's path. Written
    sidecar first, each through a temporary name, so the library never sees a transcript without its cues."""
    from app.path_utils import SIDECAR_SUFFIX
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, file_name(sub))
    for target, data in ((os.path.splitext(path)[0] + SIDECAR_SUFFIX, json.dumps(sidecar(sub), ensure_ascii=False)),
                         (path, text(sub))):
        tmp = target + ".part"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        os.replace(tmp, target)
    return path


def record(sub, language):
    """The pairing record `Store.register` takes for it: titled by its show (a film by its own title), the episode's
    season and number kept; `video_id` and `url` for ▶ (`play.online_link`)."""
    show = dict(sub["show"] or {"title": sub["title"]})
    show = {k: v for k, v in show.items() if v is not None}
    out = {"schema": 1, "producer": PRODUCER, "language": language, "content_key": content_key(sub),
           "video_id": sub["video_id"], "url": sub["url"], "title": sub["title"], "show": show}
    if not sub["show"]:
        out["media_type"] = "movie"
    return out


def youtube_links(body):
    """v3's `POST /v1/youtube` body -> its links (1 to MAX_LINKS https links on YouTube's own hosts); raises Bad."""
    try:
        got = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Bad("the body isn't JSON") from None
    urls = got.get("urls") if isinstance(got, dict) and got.get("schema") == SCHEMA else None
    if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_LINKS:
        raise Bad(f"urls must be 1 to {MAX_LINKS} links")
    from urllib.parse import urlsplit
    out = []
    for url in urls:
        parts = urlsplit(url.strip()) if isinstance(url, str) else None
        if parts is None or parts.scheme != "https" or (parts.hostname or "") not in YOUTUBE_HOSTS:
            raise Bad("each link must be a YouTube https link")
        out.append(url.strip())
    return out


def keep_cover(writer, sub, item_id):
    """The show's artwork the extension sent (`cover`: base64 JPEG or PNG, at most MAX_COVER) as its title's cover —
    only while the title has none of its own (none, or the generated one: never its own art, an AniList or TMDB cover,
    nor your pick). Kept as *Choose an image…* keeps one (`covers.keep_user_bytes`' folder, name and checks) and recorded
    through the window's writer as nobody's choice (`auto`: never on the Undo stack), unlocked: *Change cover…* still
    replaces it, and an online fetch never does (`Store.set_cover`'s rule). -> its record's path, or None; never
    raises (a cover is never a reason for the subtitle to fail: the why is logged)."""
    raw = sub.get("cover")
    if not raw:
        return None
    try:
        data = base64.b64decode(raw, validate=True)
        if len(data) > MAX_COVER:
            raise ValueError(f"{len(data)} bytes, over {MAX_COVER}")
        from app import path_utils
        from app.services import covers
        ext = covers.image_ext(data)
        if ext is None:
            raise ValueError("not a JPEG or PNG")
        try:
            store = writer.opener.handle()
            with store._reading():
                row = store.conn.execute("SELECT w.id, w.cover_source, w.cover_locked FROM items i JOIN works w ON "
                                         "w.id = i.work_id WHERE i.id = ?", (item_id,)).fetchone()
        finally:
            writer.opener.close()
        if row is None or row[1] not in (None, "generated") or row[2]:
            return None                         # a title with a cover of its own keeps it
        language = writer.language
        name = f"{covers._digest('work', language, row[0])[:12]}-{hashlib.sha256(data).hexdigest()[:16]}{ext}"
        target = os.path.join(path_utils.get_user_files_path(language), covers.USER_COVERS, name)
        if not os.path.isfile(target) and not covers._write_whole(target, data):
            raise OSError(f"couldn't write {target}")
        if writer.set_cover(row[0], "user", ref=f"browser:{sub['site']}", path="user:" + name, locked=False,
                            auto=True) is None:
            raise OSError("the library can't be written now")
        return "user:" + name
    except (binascii.Error, ValueError, OSError) as e:
        log.warning("The browser extension's cover wasn't kept: %s", e)
    except Exception:
        log.exception("The browser extension's cover wasn't kept")
    return None


def _cover_later(writer, sub, item_id):
    """`keep_cover` on a thread of its own: the subtitle's answer never waits for it."""
    if sub.get("cover"):
        threading.Thread(target=keep_cover, args=(writer, sub, item_id), name="browser-extension-cover",
                         daemon=True).start()


def take_in(writer, sub, rules=None, timeout=30.0, cover=_cover_later):
    """(The listener's thread.) The subtitle into the library open now -> (added, item id): one video already in
    (its pairing's `content_key`) -> (False, its item), nothing written; else its files into Processed, registered
    through the window's writer (`Writer.register`: New arrivals unless the learner's `placing_rules` place it) and
    waited for. Raises Busy (the 503: the extension keeps it and sends it again) with no library open, another
    language's open, a read-only or busy store, or a write that didn't land within `timeout`."""
    if writer is None or getattr(writer.opener, "data_dir", None) is None:
        raise Busy("No library is open in Surasura")
    if writer.language != sub["language"]:
        raise Busy(f"Surasura's open library isn't the {sub['language']} one: it is taken once that one is open")
    key = content_key(sub)

    def look(path=None):
        try:
            store = writer.opener.handle()
            if store is None:
                raise Busy("Surasura's library is busy: try again later")
            if path is None:
                return store.paired_item(key)
            from app.library_store import library_rel
            return store.paired_item(key) or store.item_id(library_rel(writer.opener.data_dir, path))
        except Busy:
            raise
        except Exception:
            raise Busy("Surasura's library is busy: try again later") from None
        finally:
            writer.opener.close()               # this thread's handle: never kept between requests
    item = look()
    if item is not None:
        cover(writer, sub, item)                # (sent again: a title still without one takes it now)
        return False, item
    path = write(os.path.join(writer.opener.data_dir, "Processed"), sub)
    landed = threading.Event()
    seq = writer.register([path], record(sub, writer.language), rules=rules,
                          done=lambda *_counts: landed.set())
    if seq is None:
        raise Busy("Surasura's library can't be written now (read-only)")
    if not landed.wait(timeout):
        raise Busy("Surasura is busy: try again later")
    item = look(path)
    if item is None:
        raise Busy("Surasura couldn't add it: try again later")
    cover(writer, sub, item)
    return True, item


class Receiver:
    """The listener on 127.0.0.1:`PORT`, on a thread of its own while the window is open. `token()` -> the kept token
    (read at each request: a new one in Settings counts at once); `deliver(sub)` -> (added, item id), raising Busy (a
    503) — the window's (`windows.start_receiver`); `version` for `hello`. `start()` -> True when listening (False: the
    port is taken — another Surasura, or another program); `stop()` at the window's close."""

    def __init__(self, token, deliver, version="", host=HOST, port=PORT, clips=None, youtube=None):
        self.token, self.deliver, self.version = token, deliver, version
        self.youtube = youtube              # v3: `youtube(urls)` -> how many queued (raises Refused / Busy), or None
        self.clips = clips                  # Connect's `browser` folder (None: `connect.browser.folder()`)
        self.host, self.port = host, port
        self._server = self._thread = None

    @property
    def on(self):
        return self._server is not None

    def start(self):
        if self._server is not None:
            return True
        try:
            server = http.server.HTTPServer((self.host, self.port), _handler(self))
        except OSError:
            return False
        self.port = server.server_address[1]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5},
                                        name="browser-extension", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout=2.0):
        """Stops listening: at most `timeout` waited for a request under way (its library write ends by itself; the
        window's close never waits on it), then the port let go."""
        server, self._server = self._server, None
        if server is None:
            return
        ender = threading.Thread(target=server.shutdown, name="browser-extension-stop", daemon=True)
        ender.start()
        ender.join(timeout)
        server.server_close()


def _handler(receiver):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "Surasura"
        sys_version = ""

        def log_message(self, *_args):          # nothing on stderr; never the token
            pass

        def _send(self, code, payload=None):
            if code >= 400 and self.command == "POST" and not getattr(self, "_read", False):
                self._read = True                   # a refusal before the body was read: a small one read and
                try:                                # dropped first (unread, Windows resets the socket before the
                    length = int(self.headers.get("Content-Length") or 0)    # answer is read)
                except ValueError:
                    length = 0
                if 0 < length <= DRAIN:
                    self.rfile.read(length)
                self.close_connection = True
            body = json.dumps(payload if payload is not None else {"ok": code == 200}).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _refused(self):
            """Not loopback, or a web page's Origin -> 403; else None."""
            if not _loopback(self.client_address[0]) or not origin_ok(self.headers.get("Origin")):
                self._send(403, {"ok": False, "why": "only the browser extension on this computer"})
                return True
            return False

        def _token(self):
            if token_ok(self.headers.get(TOKEN_HEADER), receiver.token()):
                return True
            self._send(401, {"ok": False, "why": "wrong or missing token"})
            return False

        def _body(self, limit):
            """The body's bytes, or None (answered: no length, or over `limit` — never read)."""
            try:
                length = int(self.headers.get("Content-Length") or -1)
            except ValueError:
                length = -1
            if length < 0:
                self._send(411, {"ok": False, "why": "Content-Length is needed"})
                return None
            if length > limit:
                self._send(413, {"ok": False, "why": "the body is too large"})     # (a small one read and dropped)
                return None
            self._read = True
            return self.rfile.read(length)

        def do_GET(self):
            if self._refused():
                return
            if self.path == "/v1/hello":
                self._send(200, {"app": "surasura", "version": receiver.version, "contract": CONTRACT,
                                 "languages": list(LANGUAGES)})
            elif self.path == "/v1/jobs":
                if self._token():
                    from app.connect import browser
                    self._send(200, {"jobs": browser.waiting(receiver.clips)})
            else:
                self._send(404, {"ok": False, "why": "not found"})

        def do_POST(self):
            if self._refused():
                return
            clip, done = _CLIP_PATH.fullmatch(self.path), _DONE_PATH.fullmatch(self.path)
            if self.path == "/v1/youtube":
                if self._token():
                    self._youtube()
                return
            if self.path != "/v1/online-subtitle" and not clip and not done:
                self._send(404, {"ok": False, "why": "not found"})
                return
            if not self._token():
                return
            if clip or done:
                self._job(clip, done)
                return
            body = self._body(MAX_BODY)
            if body is None:
                return
            try:
                sub = subtitle(body)
                added, item = receiver.deliver(sub)
            except Bad as e:
                self._send(400, {"ok": False, "why": str(e)})
                return
            except Busy as e:
                self._send(503, {"ok": False, "why": str(e) or "Surasura is busy: try again later"})
                return
            except Exception as e:                  # never the listener's end: said, and the extension keeps it
                self._send(503, {"ok": False, "why": f"Surasura couldn't take it in ({type(e).__name__})"})
                return
            self._send(200, {"ok": True, "added": bool(added), "item": item})

        def _youtube(self):
            """v3: YouTube links to the transcript downloader, as if pasted in its window — only while it is on and
            its risk tick given (409 with which, never past it)."""
            body = self._body(64 * 1024)
            if body is None:
                return
            try:
                urls = youtube_links(body)
                if receiver.youtube is None:
                    raise Refused("This Surasura has no YouTube downloader")
                queued = receiver.youtube(urls)
            except Bad as e:
                self._send(400, {"ok": False, "why": str(e)})
                return
            except Refused as e:
                self._send(409, {"ok": False, "why": str(e)})
                return
            except Busy as e:
                self._send(503, {"ok": False, "why": str(e) or "Surasura is busy: try again later"})
                return
            self._send(200, {"ok": True, "queued": int(queued)})

        def _job(self, clip, done):
            """v2: a recorded line's clip (`X-Clip-Start` / `X-Clip-End`: its first and last frame's video time), or
            the job's done; a job or line that no longer waits -> 404 (the extension skips it)."""
            from app.connect import browser
            if clip:
                try:
                    start, end = (float(self.headers.get(h) or "nan") for h in ("X-Clip-Start", "X-Clip-End"))
                except ValueError:
                    start = end = float("nan")
                if not (0 <= start < end):
                    self._send(400, {"ok": False, "why": "X-Clip-Start and X-Clip-End must be the clip's seconds"})
                    return
                body = self._body(MAX_CLIP)
                if body is None:
                    return
                if not body:
                    self._send(400, {"ok": False, "why": "the clip is empty"})
                    return
                job, n = int(clip.group(1)), int(clip.group(2))
                try:
                    kept = browser.keep_clip(job, n, body, start, end, receiver.clips)
                except OSError as e:
                    self._send(503, {"ok": False, "why": f"Surasura couldn't keep the clip ({e.strerror or e})"})
                    return
            else:
                body = self._body(MAX_BODY)
                if body is None:
                    return
                try:
                    failed = json.loads(body.decode("utf-8") or "{}").get("failed") or []
                    if not isinstance(failed, list):
                        raise ValueError
                except (UnicodeDecodeError, ValueError, AttributeError):
                    self._send(400, {"ok": False, "why": "the body must be {\"failed\": [...]}"})
                    return
                kept = browser.finish(int(done.group(1)), failed, receiver.clips)
            if kept:
                self._send(200, {"ok": True})
            else:
                self._send(404, {"ok": False, "why": "that job or line doesn't wait for a clip"})

        def do_OPTIONS(self):                       # no CORS: a web page's preflight is never answered yes
            self._send(403, {"ok": False, "why": "only the browser extension on this computer"})

    return Handler
