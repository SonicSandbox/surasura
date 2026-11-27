# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜 Ukai's YouTube links (Ukai SPEC §6 U-S3; its CONTRACT.md v3, `POST /v1/youtube`): Mattias's #474 v3 route (its
`online_receiver.youtube_links` and the window's `youtube_refused` / `LinkRuns` / `BarLines` / `_youtube_links`, by
mattias), moved onto the one door as a paired route of Ukai's class.

YouTube needs no recording: Ukai only hands over the links the learner's browser is on, and Surasura's own transcript
downloader runs them as if they were pasted in its window (`modules.youtube_downloader.fetch_links`: one yt-dlp run at
a time, its bot check's hold); the transcripts come into New arrivals as the downloader's own do
(`windows.youtube_arrivals`). Only while the downloader is here, on (`enable_youtube_transcripts`) and its risk tick
given (`youtube_risk_acknowledged`): never past the tick (409 with which).

- `route(writer, settings, start)` -> the route's function, on the door's thread: the links checked (`links`, 400),
  the downloader's switch and tick (`refused`, 409), a library open (503 *busy*), the same links not already running
  (`LinkRuns`, 409), then `start(urls, release)` hands them to the window's thread and the answer is
  {"queued": n}. Nothing here touches a widget.
- `qt_youtube.run(shell, urls, release)` (the window's thread) -> the downloader's run, its lines in the bar (`BarLines`);
  `release()` once it ends, so the links can be sent again.
"""
import threading
import time
from urllib.parse import urlsplit

SCHEMA = 1
HOSTS = ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")
MAX_LINKS = 50
MAX_URL = 2048
MAX_BODY = 128 * 1024                   # 50 links of 2,048 characters are about 103 KB of JSON; real ones under 4 KB

# The 409's words, said in Ukai; the bar's lines (#474's; PROVISIONAL)
ABSENT = "This Surasura has no YouTube downloader."
OFF = "Surasura's YouTube downloader is off: turn on YouTube transcripts in Settings → Content."
TICK = ("Surasura's YouTube downloader needs your OK first: open + Add → YouTube… in Surasura and tick "
        "“I understand the risks”.")
RUNNING = "These links are being downloaded already: their transcripts come into New arrivals as they're read."
NO_LIBRARY = "No library is open in Surasura: send them again once one is."
STARTED = "YouTube links from Ukai: downloading their transcripts ({n} links)…"
PROGRESS = "YouTube from Ukai: {line}"
NONE_NEW = "YouTube links from Ukai: no new transcripts (they're in your library already)."


class Bad(ValueError):
    """A body the contract doesn't take: `why` in plain words (the 400's)."""


def links(body):
    """v3's body (the door's parsed JSON object) -> its links, each once, in order: 1 to MAX_LINKS https links on
    YouTube's own hosts (the host alone: no name, password or port before the path), each one printable line of at
    most MAX_URL characters (it goes to yt-dlp as it is). Raises Bad."""
    urls = body.get("urls") if body.get("schema") == SCHEMA else None
    if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_LINKS:
        raise Bad(f"urls must be 1 to {MAX_LINKS} links")
    out = {}
    for url in urls:
        url = url.strip() if isinstance(url, str) else ""
        try:
            parts = urlsplit(url)
            host = parts.hostname or ""
        except ValueError:                      # (a broken address: "https://[")
            parts, host = None, ""
        if (parts is None or parts.scheme != "https" or host not in HOSTS or parts.netloc.lower() != host
                or len(url) > MAX_URL or not url.isprintable() or " " in url):     # (one line, no spaces)
            raise Bad("each link must be a YouTube https link")
        out[url] = None
    return list(out)


def refused(values):
    """Why the links aren't taken (the 409's words), or None: the downloader is here, on and its risk tick given —
    never past the tick."""
    import importlib.util
    try:
        here = importlib.util.find_spec("modules.youtube_downloader") is not None
    except (ImportError, ValueError):
        here = False
    if not here:
        return ABSENT
    if not values.get("enable_youtube_transcripts"):
        return OFF
    if values.get("youtube_risk_acknowledged") is not True:
        return TICK
    return None


class LinkRuns:
    """The links being downloaded now: a link sent again while its run goes on starts no second yt-dlp run (`claim`
    False: the 409's *already*). Any thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = set()

    def claim(self, urls):
        """True, and the links held till `release`, when none of them is running; else False (nothing held)."""
        urls = set(urls)
        with self._lock:
            if self._running & urls:
                return False
            self._running |= urls
            return True

    def release(self, urls):
        with self._lock:
            self._running -= set(urls)


class BarLines:
    """A run's progress lines in the window's bar, one at most every `every` seconds (yt-dlp says one a video and
    more): `bar(line)` -> whether it was said."""

    def __init__(self, say, every=2.0, clock=time.monotonic):
        self.say, self.every, self.clock, self._last = say, every, clock, None

    def __call__(self, line):
        now = self.clock()
        if not line or (self._last is not None and now - self._last < self.every):
            return False
        self._last = now
        self.say(PROGRESS.format(line=line))
        return True


def route(writer, settings, start):
    """`POST /v1/youtube`'s function for the door's Ukai class (paired: the door has checked the Origin and the
    token). `writer()` -> the open library's writer or None; `settings()` -> the settings as the window holds them
    (a dict; `routes`' `values`: {} when they can't be read);
    `start(urls, release)` (any thread) hands the links to the window's thread, or None: no window to run them."""
    from app import door
    runs = LinkRuns()

    def youtube(call):
        try:
            urls = links(call.json(limit=MAX_BODY))
        except Bad as e:
            raise door.RouteError(str(e), "body", 400) from None
        why = ABSENT if start is None else refused(settings())
        if why:
            raise door.RouteError(why, "refused", 409)
        if writer() is None:
            raise door.RouteError(NO_LIBRARY, "busy", 503)
        if not runs.claim(urls):                    # sent again while it runs: no second yt-dlp run
            raise door.RouteError(RUNNING, "refused", 409)
        try:
            start(urls, lambda: runs.release(urls))
        except BaseException:
            runs.release(urls)
            raise
        return {"queued": len(urls)}
    return youtube

