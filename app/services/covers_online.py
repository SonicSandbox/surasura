"""Covers from AniList (W3.2 Q7; the window's spec 01 §1.3 C1–C6: *The switch*, rows 1, 2 and 4, *What leaves the
machine, and nothing else*, *How it fetches*, *A wrong match*; RUNBOOK §1's *Covers* row, §4 Q7, §5a IK-7): a new
network call, specified there and named in `CLAUDE.md` §1. Qt-free, Tk-free, standard library only (`urllib.request`).

**Nothing leaves the machine unless `covers_download` is True** (settings.json, read only — never written here; asked
again before every request). What is sent, and nothing else: an AniList id (`id_in`, up to `BATCH` a query), or — only
when no id is known — a cleaned title (`clean_title`: no release group, episode, resolution, hash or path); YouTube gets
a video id (`i.ytimg.com/vi/<id>/hqdefault.jpg`: a video already in the library, C5). Every request says
`User-Agent: Surasura/<version>` and sends no `Referer` (AniList's image server refuses some by it) and no cookie.
TMDB is skipped in 3.0's first cut (no key in source, CI or tests: the seam is `paste`'s *no_key*).

- **`Fetcher(language, writer)`**: `want(wants)` — the titles that arrived or first show (never a sweep of the
  library: the window asks for what it paints) — returns at once; its own thread (never the window's) fetches them:
  ids first, batched, then a title search behind the confidence gate (`gate`: one candidate's romaji, English, native
  or synonym title, normalised, equals the cleaned name, and the season — and the year, when the name holds one —
  agrees; else nothing: the generated cover stays and *Change cover…* offers `candidates`). AniList's API is asked at
  most `PER_MINUTE` times a minute (its degraded limit), its images `IMAGES_PER_MINUTE`. Each image is written into the
  covers cache (`.part`, then renamed) and recorded `writer.set_cover(work, "anilist" | "youtube", ref=<id>,
  path="cache:<name>", auto=True)` — a background cover: never on the user's Undo stack — and only over no cover or an
  unlocked generated one (or its own source's after *Remove downloaded covers*): never over a locked, user or disk
  cover (the S5 rules; the store refuses a lock too). Offline or failed: nothing changes, a quiet retry `RETRY_S`
  later; never an error, never a dialog.
- **`candidates(want)`** (a worker's call): the top `CANDIDATES` for *Change cover…* (`Candidate`: id, cover url,
  title, year, format); **`pick(want, candidate)`** fetches it and keeps it as the user's (`covers.keep_user_bytes`:
  `User Files/<lang>/covers/`, a dated backup of the user image it replaces, locked, on the Undo stack);
  **`paste(want, link)`** — *Paste a link*: AniList, TMDB or YouTube links only.
- **`remove_downloaded()`** — *Remove downloaded covers*: `Writer.forget_covers` (the records cleared, then the cache's
  files they named deleted: `drop_cached`); the user's covers and the art beside their files stay; a book's cover comes
  back with the next disk scan (N5).
"""
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import OrderedDict, deque, namedtuple
from urllib.parse import parse_qs, urlsplit

from app import path_utils
from app.services import covers

ANILIST_API = "https://graphql.anilist.co"
YTIMG = "https://i.ytimg.com"
IMAGE_HOSTS = ("anilist.co",)       # where an AniList cover's image may come from (s4.anilist.co), and its subdomains
BATCH = 50                          # ids a query (`id_in`)
PER_MINUTE = 30                     # AniList's API while degraded
IMAGES_PER_MINUTE = 60              # its image server (and YouTube's), gently
RETRY_S = 15 * 60                   # an offline or failed title is asked again this long after
TIMEOUT_S = 20
MAX_JSON = 2 << 20                  # bytes: an answer past this isn't AniList's
CANDIDATES = 5                      # *Change cover…*'s top candidates
SEARCH_PAGE = 10                    # a title search's answers the gate looks at
WAIT_S = 0.5
NOT_ANIME = ("drama", "youtube", "podcast", "audiobook", "book", "lightnovel", "manga", "text")
#   a title its user (or its files) say isn't anime: AniList is never asked its name (books online: not at first, C6)
_OPEN = (None, "generated")         # an unlocked cover a fetch may write over

Q_IDS = ("query ($ids: [Int]) { Page(perPage: 50) { media(id_in: $ids) { id coverImage { extraLarge large } } } }")
Q_SEARCH = ("query ($search: String) { Page(perPage: 10) { media(search: $search, type: ANIME) { id format "
            "seasonYear startDate { year } title { romaji english native } synonyms coverImage { extraLarge large } "
            "} } }")

Want = namedtuple("Want", "id title anilist_id video_id kind media_type cover_source cover_ref cover_path cover_locked "
                         "rel_paths", defaults=((),))     # rel_paths: its files' (the disk is looked at first: B2)
Candidate = namedtuple("Candidate", "id cover_url title year format")



def _user_agent():
    from app import __version__
    return f"Surasura/{__version__}"


def wants_from(items, works):
    """[Want] from the feed's rows (`Store.read_feed`'s `items` / `works`, the reader's copy): each work with its
    files' commonest source type (a video waiting for its subtitles counted as one: a show's that came in video-only,
    setup's scan or a look's, is asked like any show wherever it is — New arrivals, Current, Finished) and, for a
    YouTube title, its first video's id (the downloader's file name, "<title> [<id>]": `path_utils`' own reading of
    it)."""
    kinds, videos, rels = {}, {}, {}
    for item in sorted(items, key=lambda r: (r.get("ord") or 0, r["id"])):
        w = item.get("work_id")
        if w is None:
            continue
        if item.get("rel_path"):
            rels.setdefault(w, []).append(item["rel_path"])
        kind = item.get("source_type")
        if item.get("availability") == "waiting":       # a video waiting for its subtitles (K5: no text copy, so its
            kind = "subtitle"                           # type the fallback 'text'): a show's episode, as they'll make it
        kinds.setdefault(w, {})[kind] = kinds.get(w, {}).get(kind, 0) + 1
        if kind == "youtube" and w not in videos and item.get("rel_path"):
            m = path_utils._YOUTUBE_ID_RE.search(os.path.splitext(item["rel_path"].rsplit("/", 1)[-1])[0])
            if m:
                videos[w] = m.group(1)
    out = []
    for w in (works.values() if isinstance(works, dict) else works):
        if w["id"] in kinds:
            counts = kinds[w["id"]]
            kind = max(counts, key=lambda k: (counts[k], k or ""))
            out.append(Want(w["id"], w.get("title") or "", w.get("anilist_id"), videos.get(w["id"]), kind,
                            w.get("media_type"), w.get("cover_source"), w.get("cover_ref"), w.get("cover_path"),
                            bool(w.get("cover_locked")), tuple(rels.get(w["id"], ()))))
    return out


# --- the cleaned title, and the gate ------------------------------------------------------------------------------- #
_EXT = re.compile(r"(?i)(?:\.[a-z]{2,3})?\.(?:mkv|mp4|avi|webm|srt|ass|ssa|vtt|txt|epub)$")
_YEAR = re.compile(r"[(\[]\s*((?:19|20)\d{2})\s*[)\]]")
_BRACKETS = re.compile(r"\[[^\]]*\]|【[^】]*】|\{[^}]*\}")
_TECH = re.compile(r"(?i)\b(?:\d{3,4}p|[48]k|x26[45]|h\.?26[45]|hevc|avc|aac|flac|10-?bit|bd(?:rip)?|"
                   r"blu-?ray|web-?(?:dl|rip)|dvd(?:rip)?|hdtv|dual[- ]audio|multi-?subs?|[0-9a-f]{8})\b")
_PARENS = re.compile(r"\(([^)]*)\)")
_SXXEXX = re.compile(r"(?i)\bs(\d{1,2})\s?e\d{1,4}\b.*$")
_EPISODE = re.compile(r"(?i)(?:\s[-–—]\s*\d{1,4}(?:v\d)?\b|(?<!\S)(?:ep?\.?|episode|#)\s?\d{1,4}\b|第\s*\d+\s*[話回])"
                      r".*$")
_SEASONS = (re.compile(r"(?i)\b(?:season|series)\s*(\d{1,2})\b"), re.compile(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)\s+season\b"),
            re.compile(r"(?i)\bs(\d{1,2})\b"), re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*[期季]"),
            re.compile(r"シーズン\s*([0-9]+)"))
_KANJI_NUMBERS = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}


def clean_title(raw):
    """(title, year) of a work's name as AniList may be asked it: its last path part only, without the file's
    extension, release group, hash, resolution, codec or episode (`[SubsPlease] Sousou no Frieren - 01 (1080p)
    [ABCD1234].mkv` → `Sousou no Frieren`); an `S02E05` becomes `Season 2`. `year`: one the name holds in brackets
    (`(2013)`), else None (never sent: the gate's)."""
    s = unicodedata.normalize("NFKC", str(raw or ""))
    s = re.split(r"[\\/]", s)[-1]
    s = _EXT.sub("", s).strip()
    m = _YEAR.search(s)
    year = int(m.group(1)) if m else None
    s = _YEAR.sub(" ", s)
    s = _BRACKETS.sub(" ", s)
    s = _PARENS.sub(lambda p: " " if _TECH.search(p.group(1)) or not p.group(1).strip() else p.group(0), s)
    if "_" in s and " " not in s.strip("_"):
        s = s.replace("_", " ")
    if " " not in s.strip() and s.count(".") >= 2:
        s = s.replace(".", " ")
    m = _SXXEXX.search(s)
    if m:
        s = s[:m.start()] + f" Season {int(m.group(1))}"
    s = _EPISODE.sub("", s)
    s = _TECH.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -_.~·|")
    return s, year


def _season(title):
    """(the title without its season, the season's number or None): `進撃の巨人 Season 2` → (`進撃の巨人`, 2)."""
    t = unicodedata.normalize("NFKC", title or "")
    for pattern in _SEASONS:
        m = pattern.search(t)
        if m:
            n = m.group(1)
            number = _KANJI_NUMBERS.get(n) if n in _KANJI_NUMBERS else int(n) if n.isdigit() else None
            return t[:m.start()] + " " + t[m.end():], number
    return t, None


def normalise(text):
    """A title compared: NFKC, case-folded, letters and digits only (`Re:Zero` and `re zero` are one)."""
    return "".join(c for c in unicodedata.normalize("NFKC", text or "").casefold()
                   if unicodedata.category(c)[0] in "LN")


def _titles(media):
    t = media.get("title") or {}
    return [x for x in (t.get("romaji"), t.get("english"), t.get("native"), *(media.get("synonyms") or ())) if x]


def _year_of(media):
    return media.get("seasonYear") or (media.get("startDate") or {}).get("year")


def gate(name, media, year=None):
    """The one AniList answer (`media`: the search's) that is this title, or None: a candidate passes when one of its
    titles, its season taken off and normalised, equals the cleaned name's, their seasons agree (none said is the
    first), and — when the name holds a year — its year is that year. Two or more passing: none (a wrong cover is
    worse than the generated one)."""
    base, season = _season(name)
    key = normalise(base)
    if not key:
        return None
    hits = []
    for m in media or ():
        ok = any(normalise(b) == key and (s or 1) == (season or 1) for b, s in map(_season, _titles(m)))
        if ok and (year is None or _year_of(m) == year):
            hits.append(m)
    return hits[0] if len(hits) == 1 else None


def _cover_url(media):
    image = (media or {}).get("coverImage") or {}
    return image.get("extraLarge") or image.get("large")


# --- links (*Paste a link*) ---------------------------------------------------------------------------------------- #
def parse_link(text):
    """('anilist', id) · ('tmdb', 'tv:<id>' | 'movie:<id>') · ('youtube', <video id>), or None: any other text."""
    raw = str(text or "").strip()
    try:
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = [p for p in parts.path.split("/") if p]
    if host == "anilist.co" and len(path) >= 2 and path[0] in ("anime", "manga") and path[1].isdigit():
        return "anilist", int(path[1])
    if host == "themoviedb.org" and len(path) >= 2 and path[0] in ("tv", "movie"):
        number = path[1].split("-", 1)[0]
        return ("tmdb", f"{path[0]}:{number}") if number.isdigit() else None
    vid = None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if path[:1] == ["watch"]:
            vid = (parse_qs(parts.query).get("v") or [None])[0]
        elif len(path) >= 2 and path[0] in ("shorts", "embed", "live", "v"):
            vid = path[1]
    elif host == "youtu.be" and path:
        vid = path[0]
    return ("youtube", vid) if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else None


# --- the cache ------------------------------------------------------------------------------------------------------ #
def _cache_name(language, source, ref, ext):
    return f"{source}-{covers._digest('online', language, source, ref)[:24]}{ext}"


def drop_cached(paths):
    """(The writer's thread, after `Store.forget_downloaded_covers`.) The covers cache's files the records named
    ('cache:<name>'), and any `.part` left beside them, deleted -> how many. Nothing outside the cache."""
    folder = path_utils.get_covers_cache_path()
    n = 0
    for path in paths or ():
        target = covers._named(folder, str(path or "")[len("cache:"):]) if str(path or "").startswith("cache:") else None
        if target is None:
            continue
        for p in (target, target + ".part"):
            try:
                os.remove(p)
                n += p == target
            except OSError:
                pass
    return n


# --- the pace ------------------------------------------------------------------------------------------------------ #
class Throttle:
    """At most `per_minute` requests in any 60 s: `wait()` before each (sleeps, through `sleep`, until the oldest of
    the minute leaves it — outside the lock, so a waiter never holds the others). `reserve`: the minute's last slots,
    kept for the user's own asks (`first`: *Find it online…*, a pick, *Paste a link* go ahead of the background queue,
    never behind it for a minute). Any thread."""

    def __init__(self, per_minute, clock=time.monotonic, sleep=time.sleep, reserve=0):
        self.per_minute = per_minute
        self.clock = clock
        self.sleep = sleep
        self.reserve = reserve
        self.turns = 0                      # the wait loop's turns (tests: a stopped wait ends, never spins)
        self._at = deque()
        self._lock = threading.Lock()

    def wait(self, go=None, first=False):
        """A slot taken -> True; or False once `go()` (asked after every sleep) says no — switched off, stopped:
        nothing may be sent."""
        limit = self.per_minute if first else max(1, self.per_minute - self.reserve)
        while True:
            self.turns += 1
            with self._lock:
                now = self.clock()
                while self._at and now - self._at[0] >= 60:
                    self._at.popleft()
                if len(self._at) < limit:
                    self._at.append(now)
                    return True
                pause = 60 - (now - self._at[len(self._at) - limit])
            self.sleep(pause)
            if go is not None and not go():
                return False


class _Failed(Exception):
    """A request that didn't answer (offline, refused, a server's error, an answer that isn't one): retried later."""


class _Redirects(urllib.request.HTTPRedirectHandler):
    """A redirect followed only where the request itself may go (the request's `allowed`): never another host, never
    plain http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed = getattr(req, "allowed", None)
        if allowed is None or not allowed(newurl):
            return None                             # urllib raises the 3xx as an HTTPError: a failed request
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.allowed = allowed
        return new


_OPENER = urllib.request.build_opener(_Redirects())


def _open(request, allowed):
    """`request` sent (TIMEOUT_S), its redirects checked by `allowed(url)`."""
    request.allowed = allowed
    return _OPENER.open(request, timeout=TIMEOUT_S)


# --- the fetcher ---------------------------------------------------------------------------------------------------- #
class Fetcher:
    def __init__(self, language, writer, settings=None, api=ANILIST_API, ytimg=YTIMG, image_hosts=IMAGE_HOSTS,
                 per_minute=PER_MINUTE, images_per_minute=IMAGES_PER_MINUTE, retry_s=RETRY_S, clock=time.monotonic,
                 sleep=None, background=True, data_dir=None):
        self.language = language
        self.data_dir = data_dir            # the library's data folder (None: `path_utils`' for the language)
        self.writer = writer
        self.settings = settings            # a function giving settings.json's values (None: `load_settings`)
        self.api = api
        self.ytimg = ytimg
        self.image_hosts = tuple(image_hosts)
        self.retry_s = retry_s
        self.clock = clock
        self.background = background        # False (tests): no thread — the caller runs `run_once()` itself
        self._wake = threading.Event()
        nap = sleep or self._nap
        self.api_gate = Throttle(per_minute, clock, nap, reserve=per_minute // 6)
        self.image_gate = Throttle(images_per_minute, clock, nap, reserve=images_per_minute // 6)
        self._cond = threading.Condition()
        self._queue = OrderedDict()         # work id -> Want, in the order asked
        self._later = {}                    # work id -> (when, Want): failed, asked again then
        self._done = set()                  # asked this session: fetched, no match, nothing to ask
        self._stop = False
        self._thread = None

    # --- the window's side (any thread; returns at once) ----------------------------------------------------------- #
    def on(self):
        """Whether `covers_download` is True now (settings.json, read each time: the switch turned off stops the next
        request)."""
        try:
            if self.settings is not None:
                values = self.settings()
            else:
                from app import settings_manager
                values = settings_manager.load_settings()
            return (values or {}).get("covers_download") is True
        except Exception:
            return False

    def want(self, wants):
        """The titles that arrived or first show: each one this session hasn't asked, whose cover a fetch may give
        (`fetchable`), queued for the thread. -> how many queued (0 with the switch off: nothing is kept)."""
        if not self.on():
            return 0
        n = 0
        with self._cond:
            for w in wants:
                if w.id in self._done or w.id in self._queue or w.id in self._later or not fetchable(w):
                    continue
                self._queue[w.id] = w
                n += 1
            if n:
                self._start()
                self._cond.notify_all()
        return n

    def stop(self, timeout=5):
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def remove_downloaded(self):
        """*Remove downloaded covers*: the writer clears the fetched records and deletes their files (`forget_covers`);
        what this session fetched may be fetched again (the switch still on). -> the command's number, or None."""
        with self._cond:
            self._done.clear()
            self._later.clear()
        return self.writer.forget_covers()

    def _start(self):
        if self.background and self._thread is None and not self._stop:
            self._thread = threading.Thread(target=self._run, name=f"covers-online-{self.language}", daemon=True)
            self._thread.start()

    def _nap(self, seconds):
        """The throttle's sleep: ended at once by `stop()` (the throttle then asks `_go`, and stops: never a loop on the
        set event)."""
        self._wake.wait(max(0.0, seconds))

    # --- the thread -------------------------------------------------------------------------------------------------- #
    def _run(self):
        while True:
            with self._cond:
                while not self._stop and not self._queue and not self._due():
                    soonest = min((t for t, _w in self._later.values()), default=None)
                    if soonest is None:
                        self._cond.wait()               # nothing queued: asleep until `want` or `stop` (S19)
                    else:
                        self._cond.wait(max(0.01, min(WAIT_S * 20, soonest - self.clock())))
                if self._stop:
                    return
            try:
                self.run_once()
            except Exception as e:                  # the thread never dies of an error
                print(f"Covers online: a round failed: {e!r}")

    def _due(self):
        now = self.clock()
        return any(t <= now for t, _w in self._later.values())

    def run_once(self):
        """One round: the queued titles and the retries that are due — ids in batches, then videos, then title
        searches. -> how many covers were handed to the writer."""
        with self._cond:
            now = self.clock()
            for wid, (t, w) in list(self._later.items()):
                if t <= now and wid not in self._queue:
                    del self._later[wid]
                    self._queue[wid] = w
            todo = list(self._queue.values())
            self._queue.clear()
        if not todo:
            return 0
        if not self.on():
            return 0                                # switched off: nothing asked, nothing kept (a later want asks)
        if not self.writer.can_write():
            for w in todo:
                self._failed(w)
            return 0
        todo = [w for w in todo if not self._on_disk(w)]
        landed = 0
        ids = [w for w in todo if w.anilist_id]
        for at in range(0, len(ids), BATCH):
            landed += self._by_ids(ids[at:at + BATCH])
        for w in todo:
            if not w.anilist_id and w.video_id:
                landed += self._video(w)
            elif not w.anilist_id:
                landed += self._search(w)
        return landed

    def _on_disk(self, w):
        """(B2, D-1 *disk art first*) The art beside its files (`covers._scan_one`), looked at before AniList is asked:
        a title that arrived mid-session, which the open's scan never saw. True: recorded from disk, nothing asked."""
        if not w.rel_paths or not covers._my_turn(self.writer, lambda: self._stop):
            return False
        work = covers.Work(w.id, tuple(w.rel_paths), w.cover_source, w.cover_ref, w.cover_path, w.cover_locked)
        try:
            found = covers._scan_one(self.language, self.data_dir or path_utils.get_data_path(self.language), work,
                                     self.writer)
        except Exception as e:                      # one title's trouble: asked online as before
            print(f"Covers online: work {w.id}'s folder couldn't be read: {e!r}")
            return False
        if found:
            self._finished(w)
        return found

    def _go(self):
        return not self._stop and self.on()

    def _failed(self, w):
        if not self._go():
            return                                  # switched off or stopped: dropped (a later `want` asks again)
        with self._cond:
            self._later[w.id] = (self.clock() + self.retry_s, w)

    def _finished(self, w):
        with self._cond:
            self._done.add(w.id)

    def _by_ids(self, chunk):
        if not self._go():
            return 0
        try:
            data = self._post({"ids": [int(w.anilist_id) for w in chunk]}, Q_IDS)
        except _Failed:
            for w in chunk:
                self._failed(w)
            return 0
        urls = {m.get("id"): _cover_url(m) for m in (data.get("Page") or {}).get("media") or () if isinstance(m, dict)}
        landed = 0
        for w in chunk:
            url = urls.get(int(w.anilist_id))
            if not url:
                self._finished(w)                   # AniList has no cover for it: the generated one stays
                continue
            landed += self._land(w, "anilist", str(w.anilist_id), url)
        return landed

    def _search(self, w):
        name, year = clean_title(w.title)
        if not name:
            self._finished(w)
            return 0
        if not self._go():
            return 0
        try:
            media = self._find(name)
        except _Failed:
            self._failed(w)
            return 0
        match = gate(name, media, year)
        if match is None or not _cover_url(match):
            self._finished(w)                       # no sure match: *Change cover…* offers the candidates
            return 0
        return self._land(w, "anilist", str(match["id"]), _cover_url(match))

    def _video(self, w):
        if not self._go():
            return 0
        return self._land(w, "youtube", w.video_id, f"{self.ytimg}/vi/{w.video_id}/hqdefault.jpg")

    def _land(self, w, source, ref, url):
        """The image at `url` into the cache, recorded as a background cover once the writer's queue is empty."""
        if not self._go():
            return 0                                # switched off (or stopped) inside a batch: no image more
        try:
            data, ext = self._image(url)
        except _Failed:
            self._failed(w)
            return 0
        name = _cache_name(self.language, source, ref, ext)
        if "cache:" + name == w.cover_path:         # its file went (S4): a new name, so the record — and the row — moves
            name = _cache_name(self.language, source, f"{ref}@{time.time_ns()}", ext)
        if not covers._write_whole(os.path.join(path_utils.get_covers_cache_path(), name), data):
            self._failed(w)
            return 0
        if not covers._my_turn(self.writer, lambda: self._stop):
            return 0
        self._finished(w)
        return 1 if self.writer.set_cover(w.id, source, ref=ref, path="cache:" + name, auto=True) is not None else 0

    # --- requests ---------------------------------------------------------------------------------------------------- #
    def _find(self, name, first=False):
        data = self._post({"search": name}, Q_SEARCH, first)
        return [m for m in (data.get("Page") or {}).get("media") or () if isinstance(m, dict)]

    def _post(self, variables, query, first=False):
        """AniList's answer's `data` for `query` with `variables` (the only values sent: ids, or a cleaned title).
        `first`: the user's own ask (ahead of the background queue). The switch asked again after the throttle's wait."""
        if not self.api_gate.wait(self._go, first) or not self._go():
            raise _Failed()
        body = json.dumps({"query": query, "variables": variables}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.api, data=body, method="POST", headers={
            "User-Agent": _user_agent(), "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with _open(request, self._allowed) as r:
                raw = r.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError("too long")
            out = json.loads(raw.decode("utf-8"))
            data = out.get("data") if isinstance(out, dict) else None
            if not isinstance(data, dict):
                raise ValueError("no data")
            return data
        except (OSError, ValueError, urllib.error.URLError) as e:   # offline, refused, 4xx / 5xx, not an answer
            print(f"Covers online: AniList didn't answer ({type(e).__name__})")
            raise _Failed() from e

    def _allowed(self, url):
        """Whether a request (or a redirect) may go to `url`: AniList's API or image hosts, or YouTube's thumbnails —
        over https (plain http only to this machine: the tests' fake server)."""
        parts = urlsplit(url or "")
        host = (parts.hostname or "").lower()
        hosts = self.image_hosts + tuple((urlsplit(u).hostname or "").lower() for u in (self.ytimg, self.api))
        scheme_ok = parts.scheme == "https" or (parts.scheme == "http" and host == "127.0.0.1")
        return scheme_ok and any(host == h or host.endswith("." + h) for h in hosts if h)

    def _image(self, url, first=False):
        """(bytes, ext) of the image at `url` — an AniList image host's or YouTube's, nowhere else (nor redirected
        anywhere else)."""
        if not self._allowed(url):
            raise _Failed()
        if not self.image_gate.wait(self._go, first) or not self._go():
            raise _Failed()
        request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})   # no Referer, no cookie
        try:
            with _open(request, self._allowed) as r:
                data = r.read(covers.MAX_IMAGE + 1)
        except (OSError, ValueError, urllib.error.URLError) as e:
            print(f"Covers online: an image didn't come ({type(e).__name__})")
            raise _Failed() from e
        ext = covers.image_ext(data) if len(data) <= covers.MAX_IMAGE else None
        if ext is None:
            raise _Failed()
        return data, ext

    # --- *Change cover…* (a worker's calls: each waits for its answer) ------------------------------------------------ #
    def candidates(self, want, n=CANDIDATES):
        """The top `n` AniList answers for the title's cleaned name ([Candidate], AniList's order); [] with the switch
        off, offline, or nothing found."""
        name, _year = clean_title(want.title)
        if not name or not self._go():
            return []
        try:
            media = self._find(name, first=True)
        except _Failed:
            return []
        out = []
        for m in media:
            url = _cover_url(m)
            if url:
                t = m.get("title") or {}
                out.append(Candidate(m.get("id"), url, t.get("native") or t.get("romaji") or t.get("english") or "",
                                     _year_of(m), m.get("format")))
        return out[:n]

    def pick(self, want, candidate, writer=None):
        """A candidate chosen: its image fetched and kept as the user's (locked, on the Undo stack). -> the record's
        path ('user:<name>'), or None (switched off, offline, not an image, a store that can't take it)."""
        writer = writer or self.writer
        if not self._go() or not writer.can_write():
            return None
        try:
            data, _ext = self._image(candidate.cover_url, first=True)
        except _Failed:
            return None
        return covers.keep_user_bytes(self.language, want.id, data, writer, current=want.cover_path,
                                      source="anilist", ref=str(candidate.id))

    def paste(self, want, link, writer=None):
        """*Paste a link*: an AniList, TMDB or YouTube link's cover kept as the user's. -> (path, None), or (None, why):
        'not_a_link' (any other text), 'off' (`covers_download` off), 'no_key' (TMDB: no key in 3.0's first cut),
        'failed' (offline, nothing there, a store that can't take it)."""
        found = parse_link(link)
        if found is None:
            return None, "not_a_link"
        if not self._go():
            return None, "off"
        kind, ref = found
        if kind == "tmdb":
            return None, "no_key"                   # the seam: TMDB comes with its key (01 §1.3 *Duties*)
        writer = writer or self.writer
        if not writer.can_write():
            return None, "failed"
        if kind == "anilist":
            try:
                media = (self._post({"ids": [ref]}, Q_IDS, first=True).get("Page") or {}).get("media") or ()
            except _Failed:
                return None, "failed"
            url = next((_cover_url(m) for m in media if isinstance(m, dict) and m.get("id") == ref), None)
        else:
            url = f"{self.ytimg}/vi/{ref}/hqdefault.jpg"
        if not url:
            return None, "failed"
        try:
            data, _ext = self._image(url, first=True)
        except _Failed:
            return None, "failed"
        path = covers.keep_user_bytes(self.language, want.id, data, writer, current=want.cover_path,
                                      source=kind, ref=str(ref))
        return (path, None) if path else (None, "failed")


def fetchable(want):
    """Whether a fetch may give this title a cover: no cover yet (or the generated one, unlocked), or its own online
    record whose cached file *Remove downloaded covers* took; never a locked, user or disk cover — and something to ask
    by: an AniList id, a YouTube video's id, or a name AniList may know (not a book, not bilibili, not a title its user
    calls something other than anime)."""
    if want.cover_locked:
        return False
    if want.cover_source not in _OPEN and not (want.cover_source in ("anilist", "youtube") and _gone(want.cover_path)):
        return False
    if want.anilist_id or want.video_id:
        return True
    return (want.kind == "subtitle" and want.media_type not in NOT_ANIME and bool(clean_title(want.title)[0]))


def _gone(path):
    """No cached file: no path, or a 'cache:' one whose file went (another library's *Remove*, an Undo to an old
    record: S3 / S4)."""
    if not path:
        return True
    if not str(path).startswith("cache:"):
        return False
    target = covers._named(path_utils.get_covers_cache_path(), str(path)[len("cache:"):])
    return target is not None and not os.path.exists(target)


# --- W3.2 L3: the window's asks ------------------------------------------------------------------------------------- #
def wants_for(store, work_ids, chunk=500):
    """[Want] for these works only (the titles the window paints or that arrived — never the library), read through
    `store` (this thread's handle) in one read transaction: their rows and their files' source types."""
    from app.library_store import FEED_ITEM_FIELDS, FEED_WORK_FIELDS
    ids = sorted({int(w) for w in work_ids if w is not None})
    items, works = [], []
    item_cols, work_cols = ", ".join(FEED_ITEM_FIELDS), ", ".join(FEED_WORK_FIELDS)
    with store._reading():
        for at in range(0, len(ids), chunk):
            part = ids[at:at + chunk]
            marks = ", ".join("?" * len(part))
            works += [dict(zip(FEED_WORK_FIELDS, r)) for r in
                      store.conn.execute(f"SELECT {work_cols} FROM works WHERE id IN ({marks})", part)]
            items += [dict(zip(FEED_ITEM_FIELDS, r)) for r in
                      store.conn.execute(f"SELECT {item_cols} FROM items WHERE work_id IN ({marks})", part)]
    return wants_from(items, works)
# --- end W3.2 L3
