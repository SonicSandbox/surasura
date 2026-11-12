# SPDX-License-Identifier: GPL-3.0-or-later
"""
Core transcript extraction for the Surasura YouTube Downloader.

Drives the managed yt-dlp binary (see ytdlp_manager) via its CLI, so the tool
keeps working as YouTube changes (one-click "Update yt-dlp"). Writes clean .txt
transcripts into the active language's Processed folder.

Grouping (per the agreed rules):
  - a playlist            -> subfolder  "<Channel> - <PlaylistTitle> (playlist)"
  - >= 2 links, one channel -> subfolder "<Channel>"
  - single video / mixed singles -> straight into Processed

Caption resolution mirrors the original tool: manual -> native auto -> auto-
translation, for the chosen language.

bilibili.tv links work too, with no account (see site_of): same flow, SRT captions instead of
WebVTT, and files named "<Title> [bilibili-<id>]". bilibili.com links are refused with a pointer to
bilibili.tv, since that site only gives subtitles to signed-in users.
"""

import calendar
import contextlib
import os
import re
import glob
import json
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from app import youtube_hold

from . import ytdlp_manager

# Alpha 8 (Sonic's try: Download seemed to hang): a probe gets this long; a download that writes nothing new this long
# has stalled — its yt-dlp child is ended, what came in is kept, and the run says why.
PROBE_S = 120
STALL_S = 120
FIRST_S = 300           # … before its first file (a channel's listing comes first): this long
LIST_S = 30             # (Mado-Q) setup's read of a video's playlist, for its place: past it, the video alone

INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TAG = re.compile(r'<[^>]+>')

# Friendly name -> caption spec (native codes best-first, translation prefix).
LANGS = {
    'Japanese': {'native': ['ja', 'ja-orig'], 'prefix': 'ja'},
    'Chinese':  {'native': ['zh-Hans', 'zh-Hant', 'zh', 'zh-CN', 'zh-TW', 'zh-HK', 'zh-orig'],
                 'prefix': 'zh-Hans'},
    'English':  {'native': ['en', 'en-US', 'en-GB', 'en-orig'], 'prefix': 'en'},
}
DEFAULT_LANG = 'Japanese'

# app target_language code -> friendly LANGS key (used to default the dropdown).
LANG_BY_CODE = {'ja': 'Japanese', 'zh': 'Chinese', 'en': 'English'}

# --- Sites ---------------------------------------------------------------------------------------- #
# bilibili.tv (Bilibili's international site) needs no account: where a show is licensed for the
# viewer's region, its subtitles are plain text tracks, Chinese included. bilibili.com (the mainland
# site) only gives subtitles to signed-in users — measured: 0 of 20 popular videos without a login —
# so its links are turned away up front with a pointer to bilibili.tv, instead of failing later as
# "no captions". The bilibili.tv pattern is yt-dlp's own, so both agree on what counts.
BILIBILI_TV_RE = re.compile(r'^https?://(?:www\.)?bili(?:bili\.tv|intl\.com)/', re.I)
BILIBILI_COM_RE = re.compile(r'^https?://(?:[\w-]+\.)*(?:bilibili\.com|b23\.tv)/', re.I)


def site_of(url):
    """'bilibili' (bilibili.tv), 'bilibili.com' (the mainland site — not supported) or 'youtube'."""
    url = (url or '').strip()
    if BILIBILI_TV_RE.match(url):
        return 'bilibili'
    if BILIBILI_COM_RE.match(url):
        return 'bilibili.com'
    return 'youtube'


# Alpha 8 (setup's YouTube): a link setup takes — YouTube's or bilibili.tv's own address; yt-dlp would try any page.
YOUTUBE_RE = re.compile(r'^https?://(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/', re.I)


def is_supported(url):
    """A YouTube or bilibili.tv link (bilibili.com is turned away with its own reason)."""
    url = (url or '').strip()
    return bool(YOUTUBE_RE.match(url) or BILIBILI_TV_RE.match(url))


# What yt-dlp says, in plain words (alpha 8: the setup line and the window's last line): the first that matches.
_PLAIN = (
    (('getaddrinfo', 'Failed to resolve', 'Name or service not known', 'No route to host', 'Network is unreachable',
      'timed out', 'Connection refused', 'Connection reset', 'Unable to download webpage', 'Unable to download API'),
     "YouTube couldn't be reached: check your internet connection"),
    (('Private video', 'Video unavailable', 'This video is unavailable', 'has been removed', 'does not exist'),
     "the video is private or no longer there"),
    (('Sign in to confirm your age', 'age-restricted'), "the video is age-restricted: YouTube needs a sign-in"),
    (('Unsupported URL', 'is not a valid URL'), "that isn't a YouTube or bilibili.tv link"),
)


RATE_LIMITED = "YouTube is turning requests away for now (too many, or its bot check): try again later"


def plain_reason(message, youtube=True):
    """yt-dlp's error, in plain words where it is a known one; else its own first 200 characters. `youtube`: the call
    was YouTube's (a refusal is said as the hold it began, Yt-B); bilibili.tv's is said as it was."""
    text = str(message or '').strip()
    if _looks_rate_limited(text):
        until = youtube_hold.held() if youtube else None     # (Yt-B) the hold, with when YouTube is asked again
        return youtube_hold.words(until) if until else RATE_LIMITED
    for needles, plain in _PLAIN:
        if any(n in text for n in needles):
            return plain
    errors = _errors(text)
    return (errors[0][1] if errors else text)[:200] or 'nothing readable'


SLOW = "YouTube didn't answer in {seconds} seconds"
TIMED_OUT = "one YouTube run went past {minutes} minutes and was ended: what came in is kept"


def transient(problem):
    """(Alpha 8, a playlist's rest) Is a run's plain-words problem one a later try may not meet — no connection, YouTube
    turning requests away or slow to answer, a stalled download or one past its time? (A private or deleted video, or
    no captions, stays so.)"""
    text = str(problem or '')
    return (text.endswith(_PLAIN[0][1]) or text.endswith(RATE_LIMITED) or youtube_hold.is_words(text) or
            any(words.split('{', 1)[0] in text for words in (STALLED, SLOW, TIMED_OUT)))


# YouTube's lists no one else can read or that never end: a Mix (RD…), Watch later, Liked, a channel's uploads (UL…,
# UU…: a channel is its first video only), the music app's own: their link's other videos are never fetched
_NOT_PLAYLISTS = ('RD', 'WL', 'LL', 'LM', 'UL', 'UU')     # UU…: a channel's "Play all" (its uploads), a channel


def playlist_link(url):
    """(Alpha 8, setup) The YouTube playlist a link names (`watch?v=…&list=PL…`, `playlist?list=PL…`) as its own
    page's address, or None: no list, a Mix or another list no one else can read (`_NOT_PLAYLISTS`), not YouTube."""
    url = (url or '').strip()
    if url and not re.match(r'^https?://', url, re.I):
        url = f"https://{url}"
    if not YOUTUBE_RE.match(url):
        return None
    listed = (parse_qs(urlsplit(url).query).get('list') or [''])[0].strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,}', listed) or listed.upper().startswith(_NOT_PLAYLISTS):
        return None
    return f"https://www.youtube.com/playlist?list={listed}"


# --------------------------------------------------------------------------- #
# Pure helpers (no network) — these are what the module tests exercise.
# --------------------------------------------------------------------------- #
def slug(name, limit=150):
    """Make a filesystem-safe name fragment from a title."""
    name = INVALID_FS.sub('', name or '').strip().rstrip('.')
    name = re.sub(r'\s+', ' ', name)
    return name[:limit].strip() or 'untitled'


def _fmt_date(yyyymmdd):
    if yyyymmdd and len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return yyyymmdd or ""


def _duration(info):
    s = info.get('duration_string')
    if s:
        return s
    d = info.get('duration')
    if not d:
        return ''
    d = int(d)
    h, m, sec = d // 3600, (d % 3600) // 60, d % 60
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def channel_of(info):
    return info.get('channel') or info.get('uploader') or 'Unknown'


def ts_seconds(stamp):
    """'00:12:03' / '12:03.400' -> whole seconds. None if it isn't a timestamp."""
    parts = str(stamp).strip().split('.')[0].split(':')
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0)
    h, m, s = nums[-3:]
    return h * 3600 + m * 60 + s


def clean_vtt(raw, keep_timestamps=False):
    """Strip a WebVTT (or SRT) file down to clean text lines (dedupes auto-caption roll-up)."""
    return [line for line, _sec in clean_vtt_cues(raw, keep_timestamps)]


def clean_vtt_cues(raw, keep_timestamps=False):
    """As clean_vtt, but each line is paired with its start time in seconds (None if unknown).

    The times are what the report's source badge turns into a `youtu.be/...?t=` link. They're kept
    SEPARATE from the text so the transcript can stay one flowing paragraph — the timestamped
    display format puts one cue per line, and a line break is a hard sentence boundary in Japanese,
    so writing times inline visibly degrades the example sentences.

    Reads SRT too (bilibili.tv's format): its cue numbers are dropped like any bare number, and its
    '00:01:02,500' timestamps use a comma where WebVTT uses a dot."""
    out, last, cur_ts = [], None, None
    cue_start = None
    for line in raw.splitlines():
        s = line.strip()
        if not s or s == 'WEBVTT':
            continue
        if s.startswith(('Kind:', 'Language:', 'NOTE')):
            continue
        if '-->' in s:
            cur_ts = s.split('-->')[0].strip().replace(',', '.').split('.')[0]
            cue_start = ts_seconds(cur_ts)
            continue
        s = TAG.sub('', s).replace('&nbsp;', ' ').strip()
        if not s or s.isdigit():
            continue
        if s == last:
            continue
        last = s
        if keep_timestamps and cur_ts:
            out.append((f'[{cur_ts}] {s}', cue_start))
            cur_ts = None
        else:
            out.append((s, cue_start))
    return out


def resolve_caption(info, spec):
    """Pick the best caption code + kind for the chosen language from an info dict.

    Returns (lang_code, kind) or (None, None). kind: manual / native auto / auto-translated.
    """
    subs = info.get('subtitles') or {}
    autos = info.get('automatic_captions') or {}
    # 1. manual (human) subtitles
    for c in spec['native']:
        if c in subs:
            return c, 'manual'
    # 2. native auto-generated
    for c in spec['native']:
        if c in autos:
            return c, 'native auto'
    # 3. auto-translation, preferring the video's original source language
    prefix = spec['prefix']
    orig = info.get('language')
    if orig:
        cand = f'{prefix}-{orig}'
        if cand in autos:
            return cand, 'auto-translated'
    trans = sorted(k for k in autos if k == prefix or k.startswith(prefix + '-'))
    if trans:
        return trans[0], 'auto-translated'
    return None, None


def build_text(info, body, language, kind):
    """Plain-text output: a light header followed by the transcript."""
    title = info.get('title') or 'Untitled'
    channel = channel_of(info)
    url = info.get('webpage_url') or info.get('original_url') or ''
    published = _fmt_date(info.get('upload_date', ''))
    dur = _duration(info)
    header = [
        title,
        f'{channel} | {published} | {dur}',
        f'Captions: {language} ({kind})',
        url,
        '',
        '-' * 60,
        '',
    ]
    return '\n'.join(header) + body + '\n'


# Written beside each transcript so the report can turn a sentence into a "jump to this moment"
# link. Not content (the analyzer only reads .txt/.md/.srt/.ass), so it is inert everywhere else.
# The suffix lives in the core so the report can read a sidecar without importing this module.
from app.path_utils import SIDECAR_SUFFIX


def sidecar_path(txt_path):
    """The cue sidecar that belongs to a transcript: 'foo.txt' -> 'foo.surasura.json'."""
    return os.path.splitext(txt_path)[0] + SIDECAR_SUFFIX


def build_sidecar(info, cues, place=None):
    """Cue payload for a transcript. `cues` is [(text, seconds), ...] from clean_vtt_cues. `place` (Mado-Q): a
    playlist's video's {"id": the list, "index": its place in the list's learning order} — the library reads it to
    put the list's videos in its order (`series_places`)."""
    payload = {
        'video_id': info.get('id', ''),
        # Without the '#…' fragment: yt-dlp tags an episode reached through a bilibili.tv season
        # with '#__youtubedl_smuggle=…', which is plumbing, not part of the page's address.
        'url': (info.get('webpage_url') or info.get('original_url') or '').split('#', 1)[0],
        'title': info.get('title') or '',
        # Only timed lines are useful for jumping; an untimed one can't be linked to.
        'cues': [[text, sec] for text, sec in cues if sec is not None],
    }
    if place:
        payload['playlist'] = dict(place)
    return payload


def write_sidecar(txt_path, info, cues, place=None):
    """Write the cue sidecar next to a transcript. Best-effort — a failure must never lose the
    transcript itself, which is the thing the user actually asked for."""
    try:
        payload = build_sidecar(info, cues, place)
        if not payload['cues'] and not payload['video_id']:
            return False
        with open(sidecar_path(txt_path), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def sublang_patterns(spec):
    """yt-dlp --sub-langs value covering native codes + translations for the language."""
    pats = list(spec['native'])
    pats.append(spec['prefix'] + '.*')
    return ','.join(pats)


def plan_buckets(probe_results, processed_dir):
    """Turn probe results into download buckets: list of (urls, target_dir).

    `probe_results` is a list of (url, info_dict) where info_dict is the flat JSON
    yt-dlp returned (or None to skip). Pure function — easy to unit-test.
    """
    playlists, loose, singletons = [], [], []
    for url, info in probe_results:
        if not info:
            continue
        # bilibili.tv names no uploader at all, so it has no channel to group by or prefix with: a
        # season is simply "<Show> (playlist)" and a loose episode goes straight into Processed.
        bilibili = site_of(url) == 'bilibili'
        if info.get('_type') == 'playlist' or info.get('entries') is not None:
            ptitle = info.get('title') or 'Playlist'
            if bilibili:
                folder = slug(f"{ptitle} (playlist)")
            else:
                folder = slug(f"{channel_of(info)} - {ptitle} (playlist)")
            playlists.append((url, os.path.join(processed_dir, folder)))
        elif bilibili:
            singletons.append(url)
        else:
            loose.append((url, channel_of(info)))

    buckets = [([url], target) for url, target in playlists]

    by_channel = {}
    for url, ch in loose:
        by_channel.setdefault(ch, []).append(url)

    for ch, ch_urls in by_channel.items():
        if len(ch_urls) >= 2:
            buckets.append((ch_urls, os.path.join(processed_dir, slug(ch, 80))))
        else:
            singletons.extend(ch_urls)
    if singletons:
        buckets.append((singletons, processed_dir))
    return buckets


# --------------------------------------------------------------------------- #
# yt-dlp CLI driving (network) — thin wrappers around the managed binary.
# --------------------------------------------------------------------------- #
_STOP = threading.local()


@contextlib.contextmanager
def stopping(should_stop):
    """Within it, this thread's yt-dlp children end as soon as `should_stop()` turns true (3.0: a cancelled job, a
    closed window, the app's quit) — a playlist's one call can take half an hour. Outside it (2.x, Tk) nothing asks."""
    before = getattr(_STOP, "check", None)
    _STOP.check = should_stop
    try:
        yield
    finally:
        _STOP.check = before


def _stopping_now():
    return getattr(_STOP, "check", None)


class Held(Exception):
    """(Yt-B) YouTube's bot check holds every YouTube call (`app.youtube_hold`): no call made. Its str: the words."""


_YOUTUBE_ARG = re.compile(r'(?:^|[/.])(?:youtube(?:-nocookie)?\.com|youtu\.be)(?::\d+)?/|^ytsearch\d*:', re.I)


_PATH_FLAGS = ('-o', '--output', '--download-archive', '--cookies', '--config-locations')   # (their values: paths)


def _reaches_youtube(args):
    """(Yt-B) Does this yt-dlp call ask YouTube — one of its links YouTube's (a path given to a flag never counts)?"""
    return any(not a.startswith('-') and (i == 0 or args[i - 1] not in _PATH_FLAGS) and _YOUTUBE_ARG.search(a)
               for i, a in enumerate(args))


def _run_ytdlp(args, timeout=1800, tick=None):
    """One yt-dlp call. A YouTube one (Yt-B, `_reaches_youtube`): one at a time on the computer and a little apart
    (`youtube_hold.turn`; the tick's stall clock starts once its turn came), never made while a hold runs (Held), and
    ended at its first refusal ("not a bot", HTTP 429: `--ignore-errors` would ask for every video left), which holds
    every YouTube call for a day."""
    cmd = [ytdlp_manager.get_ytdlp_path()] + args
    extra = {} if tick is None else {"tick": tick}
    if not _reaches_youtube(args):
        return ytdlp_manager.run(cmd, timeout, should_stop=_stopping_now(), **extra)
    try:
        with youtube_hold.turn(_stopping_now(), on_wait=getattr(tick, 'waiting', None)):
            until = youtube_hold.held()
            if until:
                raise Held(youtube_hold.words(until))
            getattr(tick, 'restart', lambda: None)()
            res = ytdlp_manager.run(cmd, timeout, should_stop=_stopping_now(), stop_on=youtube_hold.refused, **extra)
            if youtube_hold.refused(getattr(res, 'stderr', '')):
                try:
                    youtube_hold.hold()
                except OSError as e:                # the record unwritable: this run still stops; said in the log
                    print(f"YouTube: the hold couldn't be noted: {e!r}")
            return res
    except youtube_hold.Stopped:
        raise ytdlp_manager.Stopped() from None


# (Yt-B) yt-dlp's own pacing (its `-t sleep` preset's request and caption waits): between a YouTube call's page
# requests, and before each video's captions when one call reads several
SLEEP_REQUESTS = ['--sleep-requests', '0.75']
SLEEP_CAPTIONS = ['--sleep-subtitles', '5']


def _held(log, summary):
    """(Yt-B) Does YouTube's bot check hold every YouTube call now? Said once a run (`summary['held']`)."""
    until = youtube_hold.held()
    if until is None:
        return False
    if not summary.get('held'):
        summary['held'] = True
        log(f"  ! {youtube_hold.words(until)}")
    return True


class Stalled(Exception):
    """A download that wrote nothing new for STALL_S seconds: its yt-dlp child was ended (alpha 8)."""


STALLED = "YouTube stopped answering for {minutes} minutes, so the download was stopped: what came in is kept"


def _watch(tmp, total, log, clock=time.monotonic):
    """The tick of one download call (alpha 8: a playlist's call said nothing for many minutes and looked hung): each
    video read — its info.json written into `tmp` — said as `n of total` (when there are several); nothing new written
    for STALL_S seconds (FIRST_S before the first file) raises Stalled."""
    state = {"files": 0, "videos": 0, "since": clock()}

    def restart():                                  # (Yt-B) the call's own start: after a wait for its turn
        state["since"] = clock()

    def tick():
        try:
            names = os.listdir(tmp)
        except OSError:
            return
        now = clock()
        if len(names) != state["files"]:
            state["files"], state["since"] = len(names), now
        elif now - state["since"] >= (STALL_S if state["files"] else FIRST_S):
            raise Stalled()
        videos = min(total, sum(1 for n in names if n.endswith('.info.json')))
        if videos > state["videos"]:
            state["videos"] = videos
            if total > 1:
                log(f"  … {videos} of {total} videos read")
    tick.restart = restart
    tick.waiting = lambda verb: log(f"  … waiting for {verb} to finish first (one YouTube download at a time)")
    return tick


def _saying(log):
    """(Yt-B) A tick that only says a wait for the turn: a probe's (it has no progress of its own)."""
    def tick():
        return None
    tick.waiting = lambda verb: log(f"  … waiting for {verb} to finish first (one YouTube download at a time)")
    return tick


def _probe(url, log, single=False, timeout=PROBE_S):
    """Fast metadata probe (flat playlist) — returns parsed JSON or None. `single` (setup's first video): a link that
    names a video is read as that video, never its playlist."""
    try:
        # (Mado-Q) each playlist entry's rough date ("3 weeks ago"), which tells its order: `series_order`
        youtube = site_of(url) == 'youtube'
        res = _run_ytdlp(['-J', '--flat-playlist', '--no-warnings', '--extractor-args', 'youtubetab:approximate_date']
                         + (SLEEP_REQUESTS if youtube else []) + (['--no-playlist'] if single else []) + [url],
                         timeout=timeout, tick=_saying(log))
    except Held as e:
        log(f"  ! {e}")
        return None
    except subprocess.TimeoutExpired:
        log(f"  ! could not read {url}: {SLOW.format(seconds=timeout)}")
        return None
    except ytdlp_manager.Stopped:
        log("Stopped.")
        return None
    except Exception as e:
        log(f"  ! could not read {url}: {plain_reason(e, site_of(url) == 'youtube')}")
        return None
    if not res.stdout:
        log(f"  ! could not read {url}: {plain_reason(res.stderr, site_of(url) == 'youtube')}")
        return None
    try:
        info = json.loads(res.stdout)
    except Exception as e:
        log(f"  ! could not parse {url}: {e}")
        return None
    if not info:
        # yt-dlp prints 'null' when it couldn't read the link at all (a region-locked bilibili.tv
        # episode, a private video). Say why, instead of the run ending in "No videos found".
        errors = _errors(res.stderr)
        message = errors[0][1] if errors else ''
        plain = _refusal(message) if site_of(url) == 'bilibili' else None
        log(f"  – could not read {url}: {plain or plain_reason(message, site_of(url) == 'youtube')}")
        return None
    return info


def _subtitle_args(site, spec):
    """yt-dlp caption flags for one site.

    YouTube serves WebVTT natively. bilibili.tv serves SRT (yt-dlp builds it from Bilibili's JSON);
    converting that to VTT would need ffmpeg, which users don't have, so it is written as SRT and
    read by clean_vtt_cues, which understands both. bilibili.tv has no auto-captions to ask for."""
    langs = ['--sub-langs', sublang_patterns(spec)]
    if site == 'bilibili':
        return ['--write-subs'] + langs + ['--sub-format', 'srt/best']
    return ['--write-subs', '--write-auto-subs'] + langs + [
        '--sub-format', 'vtt/best', '--convert-subs', 'vtt']


# What yt-dlp says when bilibili.tv refuses an episode, and what the learner is told instead. The
# region lock is the everyday one: each show is licensed per country, so the same link works for one
# learner and not another.
_BILIBILI_REFUSALS = (
    ('geo restriction', 'not available in your region (bilibili.tv licenses each show per country)'),
    ('registered users', 'for bilibili.tv members only'),
    # When bilibili.tv's playback API refuses a video with a code yt-dlp doesn't know (10004002,
    # seen live on uploads, 2026-09-18), yt-dlp 2026.07.04 and 2026.08.19 both crash with exactly
    # this instead of reporting it. The site gave no reason, so none is invented here.
    ("'NoneType' object is not subscriptable", "bilibili.tv didn't return this video"),
)
# yt-dlp names the video only in SOME errors, and tags most with the extractor: a region lock
# arrives as "ERROR: [BiliIntl] This video is not available from your location due to geo
# restriction", the crash above as a bare "ERROR: 'NoneType' object is not subscriptable".
_YTDLP_ERROR_RE = re.compile(r'^ERROR: (?:\[[^\]]+\] )?(?:([^\s:]+): )?(.+)$')


def _errors(stderr):
    """[(video id or None, message)] for every ERROR line yt-dlp printed."""
    out = []
    for line in (stderr or '').splitlines():
        match = _YTDLP_ERROR_RE.match(line.strip())
        if match:
            out.append(match.groups())
    return out


def _refusal(message):
    """The plain-words reason for a bilibili.tv refusal, or None for any other error."""
    for needle, plain in _BILIBILI_REFUSALS:
        if needle in message:
            return plain
    return None


def _report_refusals(stderr, log, summary, site='bilibili'):
    """Tell the learner about every episode yt-dlp refused (bilibili.tv's in its own words). A refused one writes no
    info.json, so without this it would vanish from the run without a word. yt-dlp doesn't name the
    episode in a refusal, so those are counted per reason."""
    refused = {}
    for vid, message in _errors(stderr):
        plain = _refusal(message) if site == 'bilibili' else None
        if plain:
            refused[plain] = refused.get(plain, 0) + 1
            summary['no_transcript'] += 1
        else:
            what = 'episode' if site == 'bilibili' else 'video'
            log(f"  ! {f'{what} {vid}: ' if vid else ''}{plain_reason(message, site != 'bilibili')}")
            summary['errors'] += 1
    for plain, count in refused.items():
        log(f"  – {count} episode{'s' if count > 1 else ''}: {plain}")


def _subtitle_file(tmp, vid, code):
    """The caption file yt-dlp wrote for a video: the chosen language first, then any it wrote."""
    for ext in ('vtt', 'srt'):
        path = os.path.join(tmp, f"{vid}.{code}.{ext}")
        if os.path.isfile(path):
            return path
    cand = glob.glob(os.path.join(tmp, f"{vid}.*.vtt")) + glob.glob(os.path.join(tmp, f"{vid}.*.srt"))
    return cand[0] if cand else None


def _download_bucket(urls, target_dir, spec, lang, keep_ts, channel_first, log, summary, should_stop=None,
                     counts=None, single=False, skip=None, written=None, places=None, reverse=()):
    """Download captions for a bucket into target_dir, writing clean .txt files. `should_stop()` true (the window
    that asked closed) skips the bucket's yt-dlp calls not yet started. `counts`: the videos behind each link (a
    playlist's, from its probe), for the progress lines. `single` (setup's first videos): each link is its one video,
    never its playlist (`--no-playlist`: a `watch?v=…&list=…` link is otherwise the whole list). `skip` (a
    playlist's rest): the video ids never read — handed to yt-dlp as a download archive, which it checks before it
    reads a video (one request saved per video already in). `written(path)`: told of each transcript as it is written
    (a playlist's rest records it at once: a crash after it never leaves it out of the library). `places`: {video id:
    its playlist place} (`series_places`), written into its sidecar; `reverse`: the playlist links read newest first
    (`series_reversed`), fetched from their end (`--playlist-reverse`): a run stopped half-way keeps the series' start."""
    existed = os.path.isdir(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='surasura_yt_') as tmp, \
            tempfile.TemporaryDirectory(prefix='surasura_yt_have_') as have:
        archive = []
        if skip:                                         # beside the run's folder: its files are what the tick counts
            archive = ['--download-archive', os.path.join(have, 'have.txt')]
            with open(archive[1], 'w', encoding='utf-8') as f:
                f.write(''.join(f"youtube {vid}\n" for vid in sorted(skip)))
        # One yt-dlp call per site: their caption flags differ (see _subtitle_args).
        by_site = {}
        for url in urls:
            by_site.setdefault(site_of(url), []).append(url)
        for site, site_urls in by_site.items():
            if should_stop is not None and should_stop():
                break
            youtube = site == 'youtube'
            if youtube and _held(log, summary):
                continue
            total = sum((counts or {}).get(u, 1) for u in site_urls)
            pace = (SLEEP_REQUESTS + (SLEEP_CAPTIONS if total > 1 else [])) if youtube else []
            args = ['--skip-download'] + _subtitle_args(site, spec) + pace + [
                '--write-info-json', '--no-write-playlist-metafiles',   # (a playlist's own info.json was a video read)
                '--ignore-errors', '--no-warnings', '--quiet',
                '-o', os.path.join(tmp, '%(id)s.%(ext)s'),
            ] + (['--no-playlist'] if single else []) + archive + (
                ['--playlist-reverse'] if site_urls and set(site_urls) <= set(reverse) else []) + list(site_urls)
            limit = max(1800, 600 + 15 * total) if youtube else 1800     # (Yt-B: ~8-13 s a video with the waits)
            try:
                res = _run_ytdlp(args, timeout=limit, tick=_watch(tmp, total, log))
            except Held as e:                               # (a hold another program began a moment ago)
                if not _held(log, summary) and not summary.get('held'):
                    summary['held'] = True
                    log(f"  ! {e}")
                continue
            except Stalled:
                log(f"  ! {STALLED.format(minutes=STALL_S // 60)}")
                summary['errors'] += 1
                continue
            except subprocess.TimeoutExpired:               # (a playlist of hundreds: what came in is kept)
                log(f"  ! {TIMED_OUT.format(minutes=limit // 60)}")
                summary['errors'] += 1
                continue
            except ytdlp_manager.Stopped:                   # (A8B-11) asked to stop: said as a stop, never an error
                log("Stopped.")
                break
            except Exception as e:
                log(f"  ! download error: {e}")
                summary['errors'] += 1
                continue
            # Every site's errors are said (alpha 8: a YouTube video yt-dlp refused vanished from the run unsaid)
            _report_refusals(getattr(res, 'stderr', ''), log, summary, site)
            if youtube and youtube_hold.held():             # (Yt-B) its refusal said the hold: not again this run
                summary['held'] = True

        for info_path in sorted(glob.glob(os.path.join(tmp, '*.info.json'))):
            try:
                with open(info_path, encoding='utf-8') as f:
                    info = json.load(f)
            except Exception:
                continue
            if info.get('_type') == 'playlist':
                continue
            title = info.get('title') or info.get('id') or 'unknown'
            vid = info.get('id', '')
            bilibili = site_of(info.get('webpage_url') or info.get('original_url') or '') == 'bilibili'
            code, kind = resolve_caption(info, spec)
            if not code:
                log(f"  – no {lang} captions: {title}")
                summary['no_transcript'] += 1
                continue
            sub_path = _subtitle_file(tmp, vid, code)
            if not sub_path:
                log(f"  – captions unavailable: {title}")
                summary['no_transcript'] += 1
                continue
            try:
                with open(sub_path, encoding='utf-8', errors='replace') as f:
                    cues = clean_vtt_cues(f.read(), keep_ts)
                lines = [text for text, _sec in cues]
                if keep_ts:
                    body = '\n'.join(lines)
                elif bilibili:
                    # bilibili.tv subtitles are one sentence per cue and, in Chinese, carry no
                    # punctuation at all: joined with spaces they became one endless "sentence".
                    # Close each cue exactly as the analyzer closes a cue in an .srt file.
                    from app.analyzer import close_cue
                    body = ''.join(close_cue(line) for line in lines)
                else:
                    body = ' '.join(lines)
                if not body.strip():
                    log(f"  – empty transcript: {title}")
                    summary['no_transcript'] += 1
                    continue
                # A distinct token, not a bare number: "[20240101]" and fansub CRCs are bracketed
                # digits too. It is what tells the app this is a bilibili.tv transcript.
                token = f"[bilibili-{vid}]" if bilibili else f"[{vid}]"
                stem = f"{title} {token}".strip()
                if channel_first and not bilibili:     # bilibili.tv names no uploader to prefix
                    stem = f"{slug(channel_of(info), 60)} - {stem}"
                out_stem = slug(stem)
                if not out_stem.endswith(token):
                    # Too long, and slug() cut from the END — through the id. Shorten the title
                    # instead: the id is how the app knows this file (the "already in your library"
                    # check, cue backfill, the source badge), and without it two long titles from
                    # one channel could share a name and the second overwrite the first.
                    head = slug(stem[:-len(token)].rstrip(), 150 - len(token) - 1)
                    out_stem = f"{head} {token}"
                out_name = out_stem + '.txt'
                out_path = os.path.join(target_dir, out_name)
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(build_text(info, body, lang, kind))
                # Cue times, so the report can link a sentence to its moment in the video.
                write_sidecar(out_path, info, cues, (places or {}).get(vid))
                if written is not None:
                    written(out_path)
                summary['written'] += 1
                log(f"  [ok] ({kind}) {out_name}")
            except Exception as e:
                log(f"  ! failed on {title}: {e}")
                summary['errors'] += 1

    # A folder made for this bucket that stayed empty (every episode region-locked, a playlist with
    # no captions) would be picked up as "new" and land in the library as an empty group. rmdir only
    # ever removes an EMPTY directory, and only one this call created.
    if not existed:
        try:
            os.rmdir(target_dir)
        except OSError:
            pass


# Matches the id at the end of a stem, tolerating the `_<timestamp>` suffixes Graduate/Demote append
# on a name collision. Kept in step with app.path_utils._YOUTUBE_ID_RE.
VIDEO_ID_RE = re.compile(r'\[([A-Za-z0-9_-]{11})\][\s_()\-.\d]*$')


def ids_in(root):
    """(Alpha 8, a playlist's rest) The YouTube video ids of the transcripts anywhere under `root` (their names end
    with the id, `VIDEO_ID_RE`): the videos brought in already."""
    found = set()
    for _folder, _dirs, names in os.walk(root):
        for name in names:
            if name.lower().endswith('.txt'):
                match = VIDEO_ID_RE.search(os.path.splitext(name)[0])
                if match:
                    found.add(match.group(1))
    return found


def find_transcripts_missing_cues(root):
    """Transcripts under `root` that carry a [videoID] but have no cue sidecar yet.

    Returns [(txt_path, video_id), ...]. These are the ones a backfill can repair — anything
    downloaded before sidecars existed."""
    found = []
    for folder, _dirs, names in os.walk(root):
        for name in names:
            if not name.lower().endswith('.txt'):
                continue
            match = VIDEO_ID_RE.search(os.path.splitext(name)[0])
            if not match:
                continue
            path = os.path.join(folder, name)
            if not os.path.exists(sidecar_path(path)):
                found.append((path, match.group(1)))
    return sorted(found)


# Backfill pacing. A library can hold hundreds of transcripts, and hammering YouTube with
# back-to-back requests earns a 429 (or a "confirm you're not a bot" wall) that poisons the rest of
# the run. These are deliberately conservative: a backfill is a background chore, not something
# anyone waits on.
BATCH_SIZE = 20            # videos per batch
BATCH_PAUSE = 20.0         # seconds of rest between batches
REQUEST_PAUSE = 1.5        # seconds between individual videos
MAX_CONSECUTIVE_ERRORS = 5  # give up rather than keep hammering a wall

# yt-dlp surfaces throttling in its stderr: these mean "stop", not "try the next one" — `youtube_hold.refused`'s words
# (Yt-B: "Sign in to confirm your age" is a video's age check, never YouTube turning the computer away).
def _looks_rate_limited(text):
    return youtube_hold.refused(text)


def backfill_cues(root, lang=DEFAULT_LANG, log=print, should_stop=None, sleep=time.sleep):
    """Re-fetch cue times for transcripts downloaded before sidecars existed.

    `root` should be the LANGUAGE data folder, not just Processed: a transcript is copied into a
    tier when it's added to the library, and it's that copy the analyzer reads — so it's the copy
    that needs the sidecar sitting beside it.

    Only the CAPTIONS are fetched — the transcript on disk is never rewritten, so a backfill can
    never alter content you have already analyzed.

    Paced in batches (see BATCH_SIZE) and stopped early if YouTube starts throttling. Safe to run
    again afterwards: a transcript that already has its sidecar is skipped, so a run that stops
    part-way simply resumes where it left off."""
    targets = find_transcripts_missing_cues(root)
    summary = {'written': 0, 'no_transcript': 0, 'errors': 0, 'remaining': 0, 'stopped': False}
    if not targets:
        log("Every transcript already has its cue times — nothing to backfill.")
        return summary

    spec = LANGS.get(lang, LANGS[DEFAULT_LANG])
    total = len(targets)
    log(f"Backfilling cue times for {total} transcript(s), "
        f"{BATCH_SIZE} at a time …\n")
    consecutive_errors = 0

    for done, (txt_path, vid) in enumerate(targets):
        if should_stop is not None and should_stop():
            summary['stopped'] = True
            summary['remaining'] = total - done
            log(f"\nStopped — {summary['remaining']} left. Run it again to pick up where this left off.")
            return summary
        if _held(log, summary):                      # (Yt-B) YouTube's bot check: no video asked for until it ends
            summary['stopped'] = True
            summary['remaining'] = total - done
            return summary
        if done and done % BATCH_SIZE == 0:
            log(f"  … {done}/{total} done, pausing {BATCH_PAUSE:.0f}s to stay under YouTube's limits")
            sleep(BATCH_PAUSE)
        elif done:
            sleep(REQUEST_PAUSE)

        name = os.path.basename(txt_path)
        with tempfile.TemporaryDirectory(prefix='surasura_yt_bf_') as tmp:
            args = [
                '--skip-download', '--write-subs', '--write-auto-subs',
                '--sub-langs', sublang_patterns(spec), '--sub-format', 'vtt/best',
                '--convert-subs', 'vtt', '--write-info-json',
                '--ignore-errors', '--no-warnings', '--quiet',
                '-o', os.path.join(tmp, '%(id)s.%(ext)s'),
                f'https://www.youtube.com/watch?v={vid}',
            ]
            try:
                res = _run_ytdlp(args, timeout=300)
            except Held as e:
                if not _held(log, summary):
                    log(f"  ! {e}")
                summary['stopped'] = True
                summary['remaining'] = total - done
                return summary
            except Exception as e:
                log(f"  ! {name}: {e}")
                summary['errors'] += 1
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    summary['stopped'] = True
                    summary['remaining'] = total - done - 1
                    log(f"\nStopped after {MAX_CONSECUTIVE_ERRORS} failures in a row — something is "
                        f"wrong (offline, or YouTube is refusing). {summary['remaining']} left; "
                        f"run it again later and it will resume.")
                    return summary
                continue

            # Being throttled means every remaining request will fail too — and keep digging the
            # hole. Stop and let the user come back later; finished files are already saved.
            if _looks_rate_limited(getattr(res, 'stderr', '') or ''):
                summary['stopped'] = True
                summary['remaining'] = total - done
                until = youtube_hold.held()
                log(f"\n{youtube_hold.words(until) if until else 'YouTube is rate-limiting us.'} "
                    f"Stopped with {summary['remaining']} left; everything done so far is saved.")
                return summary
            consecutive_errors = 0

            info = {}
            info_files = glob.glob(os.path.join(tmp, '*.info.json'))
            if info_files:
                try:
                    with open(info_files[0], encoding='utf-8') as f:
                        info = json.load(f)
                except Exception:
                    info = {}
            info.setdefault('id', vid)

            vtt_files = glob.glob(os.path.join(tmp, f'{vid}.*.vtt')) or glob.glob(
                os.path.join(tmp, '*.vtt'))
            if not vtt_files:
                log(f"  – no captions available: {name}")
                summary['no_transcript'] += 1
                continue
            try:
                with open(vtt_files[0], encoding='utf-8', errors='replace') as f:
                    cues = clean_vtt_cues(f.read())
                if write_sidecar(txt_path, info, cues):
                    summary['written'] += 1
                    log(f"  [ok] {name}")
                else:
                    summary['no_transcript'] += 1
                    log(f"  – no usable cue times: {name}")
            except Exception as e:
                log(f"  ! {name}: {e}")
                summary['errors'] += 1

    log(f"\nDone — {summary['written']} updated, "
        f"{summary['no_transcript']} without usable times, {summary['errors']} error(s).")
    return summary


_GONE = ('[Private video]', '[Deleted video]')        # what a flat playlist names an entry it can't show


def _when(entry):
    """A playlist entry's date as a number (its timestamp, else its upload day), or None."""
    for key in ('timestamp', 'release_timestamp'):
        value = entry.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    day = str(entry.get('upload_date') or '')
    try:
        return calendar.timegm(time.strptime(day, '%Y%m%d'))
    except ValueError:
        return None


# An episode's number in its title: "#12", "第12話", "Ep 12", "Episode 12", "Part 12", "Vol. 12"
_EPISODE_NO = re.compile(r'(?:#|第|\b(?:ep|episode|part|vol)\.?\s*)\s*(\d{1,4})', re.I)


def _number(entry):
    found = _EPISODE_NO.search(str(entry.get('title') or ''))
    return int(found.group(1)) if found else None


def _falling(values):
    """Do `values` (Nones skipped) fall at least two neighbours to one (only neighbours that differ count)? None when
    no two differ: no evidence."""
    values = [v for v in values if v is not None]
    rising = sum(b > a for a, b in zip(values, values[1:]))
    falling = sum(b < a for a, b in zip(values, values[1:]))
    return None if not (rising or falling) else falling > 2 * rising


def series_reversed(info):
    """(Mado-Q) Is a playlist listed newest first — its entries' dates running newest → oldest at least two neighbours
    to one (yt-dlp's rough dates, `approximate_date`: only neighbours whose dates differ count)? When the dates tell
    nothing (none, or all in one rough bucket: "2 years ago"), the episode numbers in the titles (#12, 第12話, Ep 12)
    vote the same way. No evidence, or no clear majority: no (the maker's order stands). PROVISIONAL."""
    entries = [e for e in (info or {}).get('entries') or () if e]
    by_date = _falling(_when(e) for e in entries)
    return by_date if by_date is not None else bool(_falling(_number(e) for e in entries))


def series_order(info, reverse=None):
    """(Mado-Q, alpha 8 — Sonic: "i want it in the order … their first video") A playlist's entries in learning order,
    its first video first: as the list gives them, unless their dates run mostly newest to oldest — a list YouTube shows
    newest at the top (a podcast adding each episode on top, a channel's uploads) — then turned over. Dates are
    yt-dlp's rough ones (`approximate_date`: "3 weeks ago"); `series_reversed` decides. A channel's uploads read the same
    way start at its oldest. `reverse`: the direction decided already (`list_direction`), else read from the dates.
    PROVISIONAL."""
    entries = [e for e in (info or {}).get('entries') or () if e]
    return entries[::-1] if (series_reversed(info) if reverse is None else reverse) else entries


def series_places(info, reverse=None):
    """(Mado-Q) {video id: {"id": the list's id, "index": its place in `series_order`, the first 1}} of a probed
    playlist ({} for a video or a list without an id): what each transcript's sidecar keeps, and the library orders by."""
    list_id = str((info or {}).get('id') or '').strip()
    if not list_id or info.get('entries') is None:
        return {}
    return {e['id']: {'id': list_id, 'index': n} for n, e in enumerate(series_order(info, reverse), 1) if e.get('id')}


def places_in(root, list_id, ids):
    """(Mado-Q; read only) {video id: index} the transcripts under `root` keep for list `list_id` (their sidecars'
    `playlist`): the places earlier runs gave this list's videos. Only the sidecars of `ids` (the list's videos, by the
    id in their names) are opened — a sidecar carries every cue."""
    found = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            vid = VIDEO_ID_RE.search(name[:-len(SIDECAR_SUFFIX)]) if name.endswith(SIDECAR_SUFFIX) else None
            if vid is None or vid.group(1) not in ids:
                continue
            try:
                with open(os.path.join(folder, name), encoding='utf-8') as f:
                    place = json.load(f).get('playlist')
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(place, dict) and place.get('id') == list_id and type(place.get('index')) is int:
                found[vid.group(1)] = place['index']
    return found


def list_direction(info, known):
    """(Mado-Q, A8Q-4) Is this list read turned over? The way its earlier videos' places (`known`, `places_in`) were
    counted, when they tell — the rough dates of an old list age into one bucket ("2 years ago"), and a later run must
    count as the first did — else its dates (`series_reversed`)."""
    if known:
        agree = {rev: sum(1 for vid, p in series_places(info, rev).items() if known.get(vid) == p['index'])
                 for rev in (False, True)}
        if agree[False] != agree[True]:
            return agree[True] > agree[False]
    return series_reversed(info)


def video_id(url):
    """The video a YouTube link names (`watch?v=…`, `youtu.be/…`), or None."""
    parts = urlsplit((url or '').strip())
    if parts.netloc.lower().endswith('youtu.be'):
        found = parts.path.strip('/').split('/')[0]
    else:
        found = (parse_qs(parts.query).get('v') or [''])[0]
    return found if re.fullmatch(r'[A-Za-z0-9_-]{11}', found or '') else None


def _probe_first(url, log):
    """(Setup) A link naming a video in a playlist (`watch?v=X&list=…`) is read as its playlist, so X's place in it is
    known (Mado-Q) — quietly, and for LIST_S seconds at most: when the list can't be read in time or doesn't hold X, X
    alone is read as before (A8B-1)."""
    vid = video_id(url)
    if not vid or playlist_link(url) is None:
        return _probe(url, log, single=True)
    quiet = []
    info = _probe(url, quiet.append, timeout=LIST_S)
    if "Stopped." in quiet:
        log("Stopped.")
        return None
    if info and any(e and e.get('id') == vid for e in info.get('entries') or ()):
        return info
    return _probe(url, log, single=True)


def first_video(url, info, reverse=None):
    """(Alpha 8, setup) The one video a probed link brings in: a video's own link -> it; a playlist's -> the video
    the link names (`watch?v=X&list=…`: X, A8B-L1), else the list's first in learning order (`series_order`) -> (url,
    info), or None (an empty playlist)."""
    if not info or (info.get('_type') != 'playlist' and info.get('entries') is None):
        return (url, info) if info else None
    named = video_id(url)
    entries = series_order(info, reverse)
    for entry in sorted(entries, key=lambda e: e.get('id') != named) if named else entries:
        if entry.get('title') in _GONE:
            continue
        link = entry.get('url') or entry.get('webpage_url')
        if not link and entry.get('id') and site_of(url) == 'youtube':
            link = f"https://www.youtube.com/watch?v={entry['id']}"
        if link:
            return link, dict(entry, _type='url')
    return None


def extract(urls, processed_dir, lang=DEFAULT_LANG, keep_timestamps=False,
            channel_first=True, log=print, should_stop=None, first_only=False, new_only=False, written=None):
    """Download transcripts for the given URLs into processed_dir (grouped). `should_stop()` true (the window that
    asked closed, 3.0) ends the run between lookups and between downloads: what finished stays. `first_only` (alpha
    8, setup): each link brings in one video — its own, or its playlist's first in learning order (`first_video`) —
    and a link that isn't YouTube's or bilibili.tv's is turned away. A playlist's videos keep their place in it
    (`series_places`, in each sidecar: the library puts them in its order, Mado-Q). The smallest download goes first (a single video never waits behind a playlist).
    `new_only` (alpha 8, a playlist's rest after setup's first video): a video already anywhere in the language's data
    folder — `processed_dir`'s parent: the tiers, Library, Graduated, Processed and the trash (its id in a transcript's
    name, `ids_in`) — is never read again: a run stopped half-way goes on where it stopped, and a video the learner
    removed never comes back. `written(path)`: each transcript as it is written."""
    stopped = (lambda: False) if should_stop is None else should_stop
    urls = [u.strip() for u in urls if u and u.strip()]
    summary = {'written': 0, 'no_transcript': 0, 'errors': 0}
    # Turned away before anything is fetched: bilibili.com only gives subtitles to signed-in users.
    for url in [u for u in urls if site_of(u) == 'bilibili.com']:
        log(f"  ! bilibili.com needs a signed-in account for subtitles — open the show on "
            f"bilibili.tv and paste that link instead: {url}")
        summary['errors'] += 1
    urls = [u for u in urls if site_of(u) != 'bilibili.com']
    if first_only:
        urls = [u if re.match(r'^https?://', u, re.I) else f"https://{u}" for u in urls]
        for url in [u for u in urls if not is_supported(u)]:
            log(f"  ! not a YouTube or bilibili.tv link: {url}")
            summary['errors'] += 1
        urls = [u for u in urls if is_supported(u)]
    if not urls:
        if not summary['errors']:
            log("Nothing to do — paste at least one YouTube or bilibili.tv link.")
        return summary

    spec = LANGS.get(lang, LANGS[DEFAULT_LANG])
    log(f"Looking up {len(urls)} item(s) — language: {lang} …\n")

    probe_results = []
    for u in urls:
        if stopped():
            log("Stopped.")
            return summary
        if site_of(u) == 'youtube' and _held(log, summary):     # (Yt-B) said once; bilibili.tv links go on
            continue
        probe_results.append((u, _probe_first(u, log) if first_only else _probe(u, log)))
        if site_of(u) == 'youtube' and youtube_hold.held():     # (its refusal said the hold: not again this run)
            summary['held'] = True
    places, turned = {}, {}                         # (Mado-Q) each playlist video's place, kept in its sidecar
    root = os.path.dirname(os.path.abspath(processed_dir))
    for u, info in probe_results:
        if info and info.get('entries') is not None and str(info.get('id') or '').strip():
            ids = {e.get('id') for e in info['entries'] if e and e.get('id')}
            turned[u] = list_direction(info, places_in(root, str(info['id']).strip(), ids))
            for vid, place in series_places(info, turned[u]).items():
                places.setdefault(vid, place)          # (A8Q-8) a video in two lists keeps its first list's place
    reverse = {u for u, rev in turned.items() if rev}
    if first_only:
        probe_results = [found for found in (first_video(u, info, turned.get(u)) for u, info in probe_results)
                         if found]
    have = ids_in(os.path.dirname(os.path.abspath(processed_dir))) if new_only else set()
    counts = {u: len([e for e in info.get('entries') or () if not e or e.get('id') not in have]) or 1
              for u, info in probe_results if info}
    buckets = plan_buckets(probe_results, processed_dir)
    if not buckets:
        log("No videos found.")
        return summary
    if have and all(info.get('entries') is not None and info['entries']
                    and all(e and e.get('id') in have for e in info['entries'])
                    for _u, info in probe_results if info):
        log("\nDone — every video is in already.")
        return summary
    buckets.sort(key=lambda b: sum(counts.get(u, 1) for u in b[0]))

    for bucket_urls, target_dir in buckets:
        if stopped():
            log("Stopped.")
            return summary
        _download_bucket(bucket_urls, target_dir, spec, lang,
                         keep_timestamps, channel_first, log, summary, should_stop, counts=counts, single=first_only,
                         skip=have, written=written, places=places, reverse=reverse)

    log(f"\nDone — {summary['written']} written, "
        f"{summary['no_transcript']} without {lang} captions, "
        f"{summary['errors']} error(s).")
    return summary
