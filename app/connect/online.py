"""An online title's video, fetched to make its cards (Michi-YT, 3.0; Sonic 2026-11-07: "And YouTube should be taken
care of. Obviously it needs to download the video. I thought Anki miner had that in the API. … Once extracted the
video is deleted. And the play button opens it up.").

A YouTube title in the library is only its transcript (the downloader's `.txt` and its cue sidecar, `source_type`
"youtube"): there is no video on this computer to cut a card from. Connect now fetches it for the job that mines it:

- **Anki Miner's own `fetch`** (Z-8, 3.11.0 `cli/api/fetch.py`): one YouTube video and its captions into
  `<connect>/online/<run>/fetch-<n>/` — the one folder every fetched video lives in, nothing else ever there; never
  the library, never the user's folders. Its captions (`youtube_subtitle_source` "captions", not aligned) are the
  subtitle the job picks its words from and Anki Miner cuts from: they came down with that video, timed to it (the
  library's transcript keeps whole seconds only). Its quality is Anki Miner's own (`YOUTUBE_MAX_HEIGHT` 720, best
  audio); the card audio is the profile's own bitrate, never lowered here.
- **yt-dlp:** the YouTube downloader's own binary (`modules/youtube_downloader/ytdlp_manager`, kept up to date by it)
  is put on Anki Miner's PATH for the call; one Anki Miner downloaded itself comes first (its resolver's order).
- **Gone after** (`drop`): as soon as Anki Miner has made the job's clips and pictures, and whenever the job stops
  short (your *Stop*, a failure, a wait, an update, Connect's exit: `runner._language`'s `finally`), and every
  leftover at Connect's start and end (`sweep`). A re-mine fetches it again.
- **Its troubles in plain words** (`Trouble`): the language's own (`standing`: the risk tick off, no yt-dlp, no room
  on the disk, an Anki Miner without `fetch`, YouTube offline or asking to prove you're no bot) once for the language;
  a video's own (private, removed, age-restricted, members only, live, too long, no captions in the language) once
  for its episode.

bilibili.tv (`SITES`) is told plainly, never fetched: Anki Miner's `fetch` takes YouTube links only (`files.py`
`_fetch_episode`), and bilibili.tv's picture and sound come apart, which only an ffmpeg joins — Surasura ships none
(PROVISIONAL, asked of the lead). ▶ keeps opening the page online (`play.online_link`).

Standard library only; no Qt. The network call itself is Anki Miner's (CLAUDE.md §1, Module-driven: the network map's
item).
"""
import html
import json
import logging
import os
import re
import shutil
import time

from app.connect import stopping

log = logging.getLogger("surasura-cli")

SITES = ("youtube", "bilibili")         # the online items' `source_type`s (`view_rows`' ▶ reads the same two)
KIND = "online-video"                   # Connect's *Needs you* kind for all of it (the language's, or a video's)
FOLDER = "online"                       # <connect>/online: every fetched video, and nothing else
FLOOR = 3 * 1024 ** 3                   # free bytes before a fetch: a 2-hour 720p video (Anki Miner's longest) fits
FETCH_TIMEOUT = 2 * 60 * 60.0           # one video, probed and downloaded (Anki Miner's own probe and download limits)
UPDATE_EVERY = 2                        # polls (a second each) between two looks for an update staged

# The words (PROVISIONAL: lean A, asked of the lead) — the language's own trouble, once for it
NOT_TICKED = ("Its video is downloaded to make its cards once you tick “I understand the risks” in YouTube… "
              "(Add → YouTube…, or ⋯ in its window).")
NO_YTDLP = ("yt-dlp isn't on this computer, so its video can't be downloaded: open YouTube… and choose "
            "⋯ → Update yt-dlp.")
NO_ROOM = "There isn't room on the disk to download its video (about 3 GB free is needed)."
NO_FETCH = "This Anki Miner can't download videos: update it from Settings → Anki & mining."
OFFLINE = "YouTube couldn't be reached (is this computer online?): Connect tries again at its next start."
BOT = ("YouTube asked to prove this computer isn't a bot, so its video wasn't downloaded: Connect tries again at its "
       "next start.")
# … and a video's own, once for its episode
PRIVATE = "This video is private: its video can't be downloaded."
REMOVED = "This video isn't on YouTube any more (removed, or unavailable here)."
AGE = "YouTube asks to sign in for this video (age-restricted): its video can't be downloaded."
MEMBERS = "This video is for the channel's members only: its video can't be downloaded."
LIVE = "This is a live stream: there is no video to download yet."
NO_CAPTIONS = "This video has no captions in its language on YouTube, so its cards can't be timed."
NO_LINK = "Its video's page isn't known (the downloader kept no link), so its video can't be downloaded."
STALE = "yt-dlp needs updating to download this video: open YouTube… and choose ⋯ → Update yt-dlp."
NO_FFMPEG = "Anki Miner can't find ffmpeg, which it needs to download videos."
BILIBILI = "bilibili.tv videos can't be downloaded to make cards yet: ▶ opens its page."
FAILED = "Its video couldn't be downloaded ({why})."

# What Anki Miner (and the yt-dlp lines it passes on) says -> the words above. First match wins; `standing` the
# language's trouble (`Trouble.standing`)
_SAYS = (
    (re.compile(r"age[- ]restrict|confirm your age|inappropriate for some users", re.I), AGE, False),
    (re.compile(r"not a bot|confirm you.?re not", re.I), BOT, True),
    (re.compile(r"update yt.?dlp|downloadable format|requested format", re.I), STALE, True),
    (re.compile(r"ffmpeg", re.I), NO_FFMPEG, True),
    (re.compile(r"private video|video is private|\bprivate\b", re.I), PRIVATE, False),
    (re.compile(r"members[- ]only|join this channel|channel members", re.I), MEMBERS, False),
    (re.compile(r"live stream|is live|premieres? in|live event", re.I), LIVE, False),
    (re.compile(r"no (?:\w+ )?(?:captions|subtitles)|captions only|has no captions", re.I), NO_CAPTIONS, False),
    (re.compile(r"unavailable|removed|deleted|terminated|no longer available|does not exist|not available",
                re.I), REMOVED, False),
    (re.compile(r"getaddrinfo|network is unreachable|timed out|connection|resolve host|offline|errno 110|"
                r"unable to download webpage", re.I), OFFLINE, True),
)


class Trouble(Exception):
    """A fetch that didn't give a video: `say` (plain words), `standing` (the language's trouble, once for it; else
    the video's own)."""

    def __init__(self, say, standing=False):
        super().__init__(say)
        self.say, self.standing = say, standing


def is_online(item):
    """Is this item (a `store.item` dict) an online title's episode — its file a downloaded transcript?"""
    return bool(item) and item.get("source_type") in SITES


def of(language, item, pairing=None):
    """What a job needs of an online item -> {"site", "url" (or None: no link kept), "names": [the transcript's folder,
    its name]} — the names its cards' Source carries (`runfile.episode(names=)`), so 順's one source-name rule ties
    them to the transcript as it ties any card to its file; None for any other item. Never writes."""
    if not is_online(item):
        return None
    from app.services import play
    rel = str(item.get("rel_path") or "").replace("\\", "/")
    url, _why = play.online_link(language, rel, pairing)
    folder, name = os.path.basename(os.path.dirname(rel)), os.path.splitext(os.path.basename(rel))[0]
    return {"site": item["source_type"], "url": url, "names": [folder or name, name]}


def folder():
    """<local data>/connect/online — every video Connect fetched, while its job runs."""
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", FOLDER)


def run_id(job_id):
    return f"v{int(job_id)}"


def place(job_id):
    """The job's own folder inside `folder()`: Anki Miner's run folder for its fetch (`<run_id>/fetch-<n>/`)."""
    return os.path.join(folder(), run_id(job_id))


def _remove(path, tries=10, pause=0.2):
    """`path` (a folder, or a file: a killed fetch's own file) gone -> True; tried again a few times while a just-ended
    program still holds a file (Windows: yt-dlp's or ffmpeg's handle lets go a moment after it is ended) -> False when
    it stays (the next sweep takes it)."""
    for n in range(tries):
        if not os.path.lexists(path):
            return True
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
        if not os.path.lexists(path):
            return True
        if n + 1 < tries:
            time.sleep(pause)
    log.warning("Connect couldn't remove a downloaded video's folder yet (%s): its next start does", path)
    return False


def drop(job_id):
    """The job's fetched video and captions gone -> True (none there counts). Never raises."""
    try:
        return _remove(place(job_id))
    except Exception:
        log.exception("Connect couldn't remove job %s's downloaded video", job_id)
        return False


def sweep():
    """Every fetched video left (a Connect killed mid-job, a folder a held file kept) gone -> how many were there.
    Connect's own, at its start and its end: one Connect runs at a time (its lock), so none is in use then. Never
    raises."""
    try:
        here = folder()
        names = os.listdir(here) if os.path.isdir(here) else []
        for name in names:
            _remove(os.path.join(here, name), tries=3)
        if names:
            log.info("Connect removed %d downloaded video folder(s) left from before", len(names))
        return len(names)
    except Exception:
        log.exception("Connect couldn't look for downloaded videos left from before")
        return 0


def room(path=None, need=FLOOR):
    """Is there room for a video on the drive of `path` (default `folder()`'s nearest folder that is there)?"""
    path = path or folder()
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        return shutil.disk_usage(path).free >= need
    except OSError:
        return True                         # can't tell: the fetch itself says when the disk is full


def ytdlp_folder():
    """The folder of the YouTube downloader's own yt-dlp, when it is there (the module installed and its binary
    downloaded) -> its path, or None. The module's absence is no error (CLAUDE.md §2's modularity rule)."""
    try:
        from modules.youtube_downloader import ytdlp_manager
    except Exception:
        return None
    try:
        path = ytdlp_manager.get_ytdlp_path()
        return os.path.dirname(path) if os.path.isfile(path) else None
    except Exception:
        return None


def child_env(base=None):
    """Anki Miner's environment for a fetch: the downloader's yt-dlp folder first on PATH (Anki Miner's own yt-dlp,
    when it has one, still comes first: its resolver reads its own copy before PATH) -> a dict, or None when there is
    no yt-dlp of Surasura's to add (the call keeps Connect's own environment)."""
    found = ytdlp_folder()
    if not found:
        return None
    env = dict(os.environ if base is None else base)
    env["PATH"] = found + os.pathsep + env.get("PATH", "")
    return env


def plain(message, transient=False):
    """Anki Miner's words for a failed fetch -> (plain words, standing)."""
    text = str(message or "")
    for pattern, say, standing in _SAYS:
        if pattern.search(text):
            return say, standing
    if transient:
        return OFFLINE, True
    short = text.strip().splitlines()[-1].strip() if text.strip() else "no reason given"
    return FAILED.format(why=short[:200]), False


def fetch(exe, profile, language, job_id, url, on_progress=None, should_end=None, env=None):
    """Anki Miner's `fetch` of one YouTube video for job `job_id` -> (video, subtitle): both inside `place(job_id)`.
    Raises Trouble (plain words), `stopping.Stopped` (the job's *Stop* — the program ended within a second —, or
    `should_end()` true, asked every UPDATE_EVERY polls: an update staged, ended within a few seconds, its folder left for the caller's `drop`), and AnkiMinerError for a call
    with no verdict (absent, crashed, timeout). `on_progress(percent)`: the download's own percent, as it goes."""
    from app.connect import anki_miner
    if not room():
        raise Trouble(NO_ROOM, standing=True)
    rid = run_id(job_id)
    here = folder()
    os.makedirs(here, exist_ok=True)
    data = {"schema": 1, "run_dir": here, "language": language,
            "episodes": [{"run_id": rid, "youtube_url": url, "youtube_subtitle_source": "captions",
                          "youtube_align_captions": False}]}
    if profile:
        data["profile"] = profile
    path = os.path.join(here, f"fetch-{rid}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    polls = [0]

    def poll():
        polls[0] += 1
        if should_end is not None and polls[0] % UPDATE_EVERY == 0 and should_end():
            return stopping.END
        if on_progress is not None:
            progress = anki_miner.read_progress(here, rid)
            if progress and progress.get("stage") == 2 and progress.get("total"):
                on_progress(max(0, min(99, int(100 * progress["done"] / progress["total"]))))
        return None
    try:
        verdict = anki_miner.api(exe, ["fetch", path], timeout=FETCH_TIMEOUT, on_poll=poll, look_up=True,
                                 env=env if env is not None else child_env())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == rid), None)
    if run is None:                         # the whole call refused: no yt-dlp or ffmpeg, a link it doesn't take
        code, message = verdict.get("error"), verdict.get("message") or ""
        if code == "SETUP_ERROR" and re.search(r"yt.?dlp", message, re.I):
            raise Trouble(NO_YTDLP, standing=True)
        raise Trouble(plain(message or code)[0], standing=True)    # the whole call: the language's (review S3)
    if not run.get("ok"):
        code, message = run.get("error"), run.get("message") or ""
        if code == "CANCELLED":
            raise stopping.Stopped()
        if code == "SETUP_ERROR" and re.search(r"yt.?dlp", message, re.I):
            raise Trouble(NO_YTDLP, standing=True)
        if code == "SETUP_ERROR":
            raise Trouble(plain(message or code)[0], standing=True)
        return _refused(code, message, bool(run.get("failure_is_transient")))
    return _made(rid, run, language)


def _refused(code, message, transient):
    """A fetch run's refusal or failure -> raises its Trouble."""
    if code == "YOUTUBE_REFUSED" and re.search(r"captions", message, re.I) and not re.search(r"age", message, re.I):
        raise Trouble(NO_CAPTIONS)
    if code == "YOUTUBE_REFUSED" and re.search(r"max duration|exceeds", message, re.I):
        raise Trouble(FAILED.format(why=message.strip().rstrip(".")))
    raise Trouble(*plain(message or code, transient))


def _made(rid, run, language="ja"):
    """The files a run's `fetch-<n>.json` names -> (video, subtitle), each a file inside the job's folder (a caption
    file in WebVTT copied to SubRip beside it, the cue reader's)."""
    own = os.path.join(folder(), rid)
    name = os.path.basename(str(run.get("file") or ""))
    try:
        with open(os.path.join(own, name), encoding="utf-8-sig") as f:
            record = json.load(f)
    except (OSError, ValueError):
        raise Trouble(FAILED.format(why="Anki Miner's answer couldn't be read")) from None
    video, subtitle = (record.get(k) if isinstance(record, dict) else None for k in ("video_file", "subtitle_file"))
    for path in (video, subtitle):
        if not isinstance(path, str) or not _inside(path, own) or not os.path.isfile(path):
            raise Trouble(FAILED.format(why="its files aren't where Anki Miner said"))
    if subtitle.lower().endswith(".vtt"):
        subtitle = as_srt(subtitle, language)
    return video, subtitle


def _inside(path, here):
    p, f = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(here))
    return p.startswith(f + os.sep)


_VTT_TIME = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})")
_TAG = re.compile(r"<[^>]*>")


def _srt_time(stamp):
    parts = stamp.replace(",", ".").split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    h, m, s = parts
    sec, _dot, frac = s.partition(".")
    return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{(frac + '000')[:3]}"


def as_srt(vtt, language="ja"):
    """A WebVTT caption file written beside itself as SubRip (`<stem>.srt`): each cue's times and its lines, tags and
    cue settings off, numbered from 1; NOTE / STYLE blocks and the header left out -> the .srt's path."""
    from app.path_utils import read_text
    blocks, cue = [], None
    for line in read_text(vtt, language).splitlines():
        m = _VTT_TIME.match(line)
        if m:
            cue = [_srt_time(m.group(1)), _srt_time(m.group(2)), []]
            blocks.append(cue)
        elif not line.strip():
            cue = None
        elif cue is not None:
            text = html.unescape(_TAG.sub("", line)).strip()
            if text:
                cue[2].append(text)
    out = os.path.splitext(vtt)[0] + ".srt"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        n = 0
        for start, end, lines in blocks:
            if lines:
                n += 1
                f.write(f"{n}\n{start} --> {end}\n" + "\n".join(lines) + "\n\n")
    return out
