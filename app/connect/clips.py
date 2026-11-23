"""The journey's ▶ on a line the browser can't play (an .mkv — most anime libraries; journey v3 SPEC §3.3 `clip/cut`,
§6's row; J-CLIP, PROVISIONAL): the line's audio cut on the press, kept for the next press.

- **The direct cut, then the one cutter** (J-CLIP 3, Sonic's yes 2026-11-23): the press runs **Anki Miner's own
  ffmpeg** (`<its install folder>/_internal/bin`, its installed layout — not its API) with **Anki Miner's own
  arguments**, read once and pinned here (`command`, `pick_stream`: its 3.13 `media_extractor._extract_audio` and
  `audio_track_detector.pick_audio_stream`) and its profile's audio settings (`settings-export`, kept until Anki
  Miner's files change) — the same clip byte for byte as `media`'s, ~0.15 s instead of ~2.2 s. Whenever it can't (no
  bundled ffmpeg — a source checkout, the suite's fake —, no settings, no stream Anki Miner's rule picks without its
  title rule, ffmpeg failing for any reason) the line goes to `add_audio.cut` — Anki Miner's `media`, the cutter of
  every card's audio, the line sent as its video's (`video_file`) — and the learner only waits longer. The
  same-bytes test (`tests/connect/test_j_clip_direct.py`) holds the two together: a change in Anki Miner that moves
  either is a red test, not a drift. No ffmpeg of Surasura's own, no new dependency, nothing off the PC.
- **The line:** the page's line id (`<item id>:<start ms>`, Swap's) found the one way Swap finds it
  (`swap.line_cue`: the item's subtitle in the library, the cue starting there now), and the item's video the one
  Connect's job would cut its cards from (`runner.Steps.video`). Its times are the subtitle's as the page shows them
  (the browser-played ▶'s own; no fit-check shift).
- **Kept, not stored:** each clip is derived data in a small cache of its own — `<Connect's folder>/clips/` in the
  local data folder (never synced, never listed, never a card's source; a card's media still comes from mining) —
  named by what it was cut from (the video's path, size and time, the line's times and text: a changed video or a
  re-timed line is cut again, never an old clip). Past CAP_BYTES the oldest clips go first (a clip played is new
  again); the folder may be deleted at any time. Nothing is cut for a line nobody pressed (the line to Torii, 3.1).
- **Two presses of one line at once:** one cut; the second waits for it and gets the same clip (or its refusal). The
  cut ahead claims its lines the same way: a press on one of them waits for it, never cuts it a second time.
- **Ahead of a press** (`ahead`; measured, J-CLIP's register: through `media` a press takes 2.0–2.6 s, Anki Miner's
  own start 1.4–1.6 s of it, an 8-line call 2.7 s; the direct cut ~0.15 s a line): the page, idle on a word, asks for
  the open episode's lines it shows — at most AHEAD_MAX, those not kept, cut one at a time on a worker of its own,
  below normal priority (the lines the direct cut can't take in ONE `media` call); a newer ask replaces one not
  started; stopped the moment the learner presses anything on the page (`stop_ahead`, the door's every route but
  this ask) — between two lines, or at `media`'s next poll. Never at Generate, never a whole library, never a line
  the page doesn't show.
- **Says why, never hangs:** `Refused` (its words, its `kind`) when Cards made for you is off, Anki Miner is absent or
  too old to cut a line, the line isn't one with a time in its file (or isn't there now), the video isn't on this PC,
  or Anki Miner couldn't cut it; a cut is stopped past CUT_TIMEOUT.

Runs on the door's thread (`door_routes.clip_route`); Qt-free; inert until the journey v3 page ships (J-CUT).
"""
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time

log = logging.getLogger("surasura-cli")

ROOT = "clips"                  # under Connect's folder (`verbs._connect_folder`): the local data folder
CAP_BYTES = 64 << 20            # the cache's size: ~400 lines of 192 kbps audio; the oldest dropped first past it
CUT_TIMEOUT = 30.0              # one cut at most (a share that stops answering never leaves ▶ waiting: the page waits 35 s)
RUN_LEFT_S = 60 * 60            # a run folder a crash left behind is removed once this old
AHEAD_MAX = 6                   # lines an ahead ask cuts, in one call (a word's shown lines: ~2.7 s for 8)
SETTINGS_TIMEOUT = 15.0         # Anki Miner's settings export on a press (~1.2 s; once until its files change)
SETTINGS_RETRY_S = 10 * 60      # an export that failed is asked again once this old (`media` cuts meanwhile)
STREAMS_MAX = 512               # files whose audio stream is kept (a file's first press pays the ffprobe, ~0.1 s)
# Anki Miner's own cut of a line's audio, read once from its 3.13 source and pinned (the same-bytes test holds it):
BIN = os.path.join("_internal", "bin")                  # its installed layout (a PyInstaller folder): ffmpeg + ffprobe
BIN_EXT = ".exe" if sys.platform == "win32" else ""
AUDIO_CODES = {"ja": frozenset(("jpn", "ja", "japanese", "jp")),              # `LanguageProfile.audio_track_codes`
               "zh": frozenset(("chi", "zho", "zh", "chinese", "cmn"))}
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"              # `LOUDNORM_FILTER`, only while the profile's switch is on
LOUDNORM_RATE = "48000"
FADE_S = 0.03                                           # `CLIP_FADE_SECONDS`, follows the loudness switch
OPUS_MAX_KBPS = 256                                     # `OPUS_MONO_MAX_KBPS`
KINDS = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".opus": "audio/ogg",
         ".flac": "audio/flac", ".wav": "audio/wav"}       # Anki Miner's clip formats -> the door's Content-Type

OFF = "Cards made for you is off: turn it on in Connect to play this line."
NO_MINER = "Anki Miner isn't installed: it cuts this line's audio."
OLD_MINER = "This Anki Miner can't cut a line's audio: update it to play this line."
NO_LINE = "This line has no time in its file, so there's nothing to play."
GONE = "Surasura can't find that line in its file now: the journey may be older than your library."
BUSY = "Your library is busy just now: press ▶ again in a moment."
NO_VIDEO = "This line's video isn't on this PC just now."
FAILED = "Anki Miner couldn't cut this line ({})."


class Refused(Exception):
    """A press that gets no clip: `message` (plain words for the page), `kind` (the door's error kind)."""

    def __init__(self, message, kind="refused"):
        super().__init__(message)
        self.message, self.kind = message, kind


_lock = threading.Lock()
_cutting = {}                   # key -> [threading.Event, the refusal or None]: a cut under way


def root():
    from app.cli.verbs import _connect_folder
    return os.path.join(_connect_folder(), ROOT)


def kind(path):
    """The Content-Type the door serves `path` with."""
    return KINDS.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def cut(language, line_id, settings=None, steps=None, miner=None):
    """The kept clip of the line `line_id` names -> its path (cut now when none is kept). Raises Refused."""
    from app import settings_manager
    from app.connect import runner, swap
    settings = settings if settings is not None else settings_manager.load_settings()
    if not (settings or {}).get("connect_enabled"):
        raise Refused(OFF, "off")
    if not isinstance(line_id, str) or swap._parse_line_id(line_id) is None:
        raise Refused(NO_LINE)
    steps = steps or runner.Steps(settings)
    try:
        found = swap.line_cue(steps, language, line_id)
        if found is None:
            raise Refused(GONE, "gone")
        item_id, cue, subtitle = found
        video = steps.video(language, {"id": 0, "item_id": item_id})
    except runner.Wait:
        raise Refused(BUSY, "busy") from None
    if not video or not os.path.isfile(video):
        raise Refused(NO_VIDEO, "gone")
    key = _key(language, video, cue)
    for _turn in range(2):
        kept = _kept(key)
        if kept:
            return kept
        with _lock:
            held = _cutting.get(key)
            mine = held is None
            if mine:
                held = _cutting[key] = [threading.Event(), None]
        if mine:
            break
        # a press of the same line, or the cut ahead, is cutting it: its answer is this one's
        if not held[0].wait(CUT_TIMEOUT + 5):
            raise Refused(FAILED.format("no clip"))
        if held[1] is not None:
            raise held[1]
        # (no clip and no refusal: the cut ahead let it go at a press — this press cuts it itself)
    else:
        kept = _kept(key)
        if kept:
            return kept
        raise Refused(FAILED.format("no clip"))
    try:
        path = _cut(language, key, video, subtitle, cue, settings, miner)
    except Refused as e:
        held[1] = e
        raise
    except Exception as e:                      # (never a crashed route without its words)
        log.warning("Clips: a line couldn't be cut", exc_info=True)
        held[1] = Refused(FAILED.format(type(e).__name__))
        raise held[1] from None
    finally:
        with _lock:
            _cutting.pop(key, None)
        held[0].set()
    return path


_ahead_lock = threading.Lock()
_ahead = {"want": None, "worker": None, "stop": threading.Event()}     # the ask waiting, its worker, its stop


def ahead(language, line_ids, settings=None, steps=None, miner=None):
    """Cut the lines `line_ids` names (the page's shown lines of its open episode) before they are pressed: at most
    AHEAD_MAX, the ones not kept, in one call on a worker below normal priority -> how many were asked (0: none it
    could). Answers at once; a newer ask replaces one not started yet; `stop_ahead` ends the one cutting."""
    from app.connect import swap
    ids = [i for i in dict.fromkeys(line_ids if isinstance(line_ids, (list, tuple)) else ())
           if isinstance(i, str) and swap._parse_line_id(i) is not None][:AHEAD_MAX]
    if not ids:
        return 0
    with _ahead_lock:
        _ahead["want"] = (language, ids, settings, steps, miner)
        worker = _ahead["worker"]
        if worker is None or not worker.is_alive():
            _ahead["stop"].clear()
            worker = _ahead["worker"] = threading.Thread(target=_ahead_loop, name="journey-clips-ahead", daemon=True)
            worker.start()
    return len(ids)


def stop_ahead():
    """A press on the page: the ask waiting is dropped and a cut ahead under way is ended (within anki_miner.POLL_S)."""
    with _ahead_lock:
        _ahead["want"] = None
        if _ahead["worker"] is not None and _ahead["worker"].is_alive():
            _ahead["stop"].set()


def _ahead_loop():
    while True:
        with _ahead_lock:
            want, _ahead["want"] = _ahead["want"], None
            if want is None:
                _ahead["worker"] = None
                return
            _ahead["stop"].clear()
        try:
            _cut_ahead(*want)
        except Exception:                       # (ahead is a nicety: never an error the learner sees)
            log.info("Clips: lines weren't cut ahead", exc_info=True)


def _cut_ahead(language, ids, settings, steps, miner):
    from app import settings_manager
    from app.cues import seconds
    from app.connect import add_audio, anki_miner, lineup, runner, stopping, swap
    settings = settings if settings is not None else settings_manager.load_settings()
    if not (settings or {}).get("connect_enabled"):
        return
    miner = miner or anki_miner.find(settings)
    if miner is None:
        return
    steps = steps or runner.Steps(settings)
    can = {}                                    # key -> (video, subtitle, cue)
    for line_id in ids:
        if _ahead["stop"].is_set():
            return
        try:
            found = swap.line_cue(steps, language, line_id)
            if found is None:
                continue
            item_id, cue, subtitle = found
            video = steps.video(language, {"id": 0, "item_id": item_id})
        except runner.Wait:
            return                              # (the library busy: a press asks again)
        if not video or not os.path.isfile(video):
            continue
        key = _key(language, video, cue)
        if key not in can and not _kept(key):
            can[key] = (video, subtitle, cue)
    with _lock:                                 # claimed: a press of one of these lines waits for it, never cuts it
        mine = {key: _cutting.setdefault(key, [threading.Event(), None]) for key in can if key not in _cutting}
    if not mine:
        return
    folder = root()
    run_dir = os.path.join(folder, f".run-ahead-{time.time_ns()}")
    try:
        os.makedirs(run_dir, exist_ok=True)
        rest, direct = {}, True
        for key in list(mine):                  # one line at a time (~0.15 s each), a press heard between lines
            if _ahead["stop"].is_set():
                return
            video, subtitle, cue = can[key]
            clip = _direct(language, video, cue, miner, os.path.join(run_dir, key), below=True) if direct else None
            if clip is None:
                direct = False                  # (what kept this line from the direct cut keeps the rest: one `media`)
                rest[key] = lineup.Cue(video, subtitle, seconds(cue.start), seconds(cue.end), lineup.clean(cue.text))
                continue
            os.replace(clip, os.path.join(folder, key + os.path.splitext(clip)[1].lower()))
            _release(mine.pop(key), key)
        if rest and not _ahead["stop"].is_set() and anki_miner.can_now({"Z-10"}):
            try:
                cut = add_audio.cut(miner, language, None, rest, run_dir, timeout=CUT_TIMEOUT,
                                    on_poll=lambda: stopping.END if _ahead["stop"].is_set() else None, below=True)
            except (anki_miner.AnkiMinerError, stopping.Stopped):
                return
            for key, clip in cut.items():
                os.replace(clip, os.path.join(folder, key + os.path.splitext(clip)[1].lower()))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        for key, held in mine.items():          # a line not cut: a press waiting on it cuts it itself
            _release(held, key)
    _trim(folder)


def _release(held, key):
    """A claimed line's cut is over (cut or not): its claim goes and a press waiting on it goes on."""
    with _lock:
        if _cutting.get(key) is held:
            _cutting.pop(key, None)
    held[0].set()


def _key(language, video, cue):
    """The clip's name: what it is cut from — the video (its path, size and time) and the line (times, text)."""
    st = os.stat(video)
    text = "\x1f".join((language, os.path.normcase(os.path.abspath(video)), str(st.st_size), str(st.st_mtime_ns),
                        str(cue.start), str(cue.end), cue.text))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _kept(key):
    """The kept clip named `key` (marked played: the newest), or None."""
    folder = root()
    for ext in KINDS:
        path = os.path.join(folder, key + ext)
        try:
            os.utime(path)
            return path
        except OSError:
            continue
    return None


def _cut(language, key, video, subtitle, cue, settings, miner):
    from app.cues import seconds
    from app.connect import add_audio, anki_miner, lineup
    miner = miner or anki_miner.find(settings)
    if miner is None:
        raise Refused(NO_MINER, "absent")
    folder = root()
    run_dir = os.path.join(folder, f".run-{key[:12]}-{time.time_ns()}")
    os.makedirs(run_dir, exist_ok=True)
    try:
        clip = _direct(language, video, cue, miner, os.path.join(run_dir, "clip"))
        if clip is None:                        # Anki Miner's own `media` (an older one without it: words to update)
            if not anki_miner.can_now({"Z-10"}):
                raise Refused(OLD_MINER, "absent")
            # (the cutter matches Anki Miner's answer back by the line-up's text, `lineup.clean`, as its own cues are)
            line = lineup.Cue(video, subtitle, seconds(cue.start), seconds(cue.end), lineup.clean(cue.text))
            try:
                clip = add_audio.cut(miner, language, None, {0: line}, run_dir, timeout=CUT_TIMEOUT).get(0)
            except anki_miner.AnkiMinerError as e:
                raise Refused(FAILED.format(e.message), e.kind) from None
        if not clip:
            raise Refused(FAILED.format("no clip for that line"))
        path = os.path.join(folder, key + os.path.splitext(clip)[1].lower())
        os.replace(clip, path)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    _trim(folder, path)
    return path


# --------------------------------------------------------------------------- #
# The direct cut: Anki Miner's own ffmpeg, its own arguments
# --------------------------------------------------------------------------- #
_known = {}             # (Anki Miner's path, language) -> (its files' stamp, the audio settings or None, when read)
_streams = {}           # (the video's path, size, mtime, language) -> the audio stream Anki Miner's rule picks, or None


def _direct(language, video, cue, miner, out, below=False):
    """The line's clip cut as Anki Miner's `media` cuts it, written at `out` + its format's extension -> its path, or
    None whenever it can't be (the caller asks `media`; nothing is said). Never raises."""
    from app.cues import seconds
    try:
        found = _binaries(miner)
        got = _settings(miner, language) if found else None
        stream = _stream(found[1], video, language, below) if got else None
        if stream is None:
            return None
        clip = f"{out}.{got['format']}"
        cmd = command(found[0], video, seconds(cue.start), seconds(cue.end), stream, got, clip)
        if _run(cmd, below) is None or not os.path.isfile(clip) or os.path.getsize(clip) == 0:
            return None
        return clip
    except Exception:                           # (the fallback is `media`: never an error the learner sees from here)
        log.info("Clips: the direct cut couldn't run; Anki Miner's media cuts it", exc_info=True)
        return None


def _binaries(miner):
    """(ffmpeg, ffprobe) bundled in Anki Miner's install folder, or None (a source checkout, the suite's fake)."""
    if not isinstance(miner, str) or miner.lower().endswith(".py"):
        return None
    folder = os.path.join(os.path.dirname(os.path.abspath(miner)), BIN)
    found = tuple(os.path.join(folder, name + BIN_EXT) for name in ("ffmpeg", "ffprobe"))
    return found if all(os.path.isfile(p) for p in found) else None


def _settings(miner, language):
    """The profile's audio settings `media` cuts with (`audio_settings` of its `settings-export`, the profile `media`
    reads when none is named) — read once, again only once Anki Miner's files change (`anki_miner.stamp`); an export
    that failed is tried again after SETTINGS_RETRY_S."""
    from app.connect import anki_miner
    now = anki_miner.stamp(miner)
    held = _known.get((miner, language))
    if held and now is not None and held[0] == now and (held[1] or time.monotonic() - held[2] < SETTINGS_RETRY_S):
        return held[1]
    if anki_miner.too_old_install(miner):
        return None                             # (it has no `--api`: run, it would open its window)
    run_dir = os.path.join(root(), f".run-settings-{time.time_ns()}")
    got = None
    try:
        os.makedirs(run_dir, exist_ok=True)
        got = audio_settings(anki_miner.settings_export(miner, language, os.path.join(run_dir, "export.json"),
                                                        timeout=SETTINGS_TIMEOUT))
    except Exception:
        log.info("Clips: Anki Miner's settings couldn't be read for the direct cut", exc_info=True)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)     # (an export may hold a key: never kept on disk)
    if now is not None:
        _known[(miner, language)] = (now, got, time.monotonic())
    return got


def audio_settings(export):
    """{padding, format, bitrate, normalize} from a settings export, or None when one is missing or not Anki Miner's
    kind. An Anki Miner without the loudness switch (3.5) never filtered: off."""
    values = (export or {}).get("settings") if isinstance(export, dict) else None
    if not isinstance(values, dict):
        return None
    padding, bitrate = values.get("audio_padding"), values.get("audio_bitrate")
    form, normalize = values.get("audio_format", "mp3"), values.get("normalize_audio_loudness", False)
    if isinstance(padding, bool) or not isinstance(padding, (int, float)) or padding < 0 or \
            isinstance(bitrate, bool) or not isinstance(bitrate, int) or bitrate <= 0 or \
            form not in ("mp3", "opus") or not isinstance(normalize, bool):
        return None
    return {"padding": float(padding), "format": form, "bitrate": bitrate, "normalize": normalize}


def _stream(ffprobe, video, language, below=False):
    """The audio stream of `video` Anki Miner's rule picks (`pick_stream`), kept per file: only a file's first press
    pays the ffprobe (~0.1 s). None: none it picks here (the line goes to `media`)."""
    import json
    st = os.stat(video)
    key = (os.path.normcase(os.path.abspath(video)), st.st_size, st.st_mtime_ns, language)
    if key in _streams:
        return _streams[key]
    out = _run([ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", "-select_streams", "a",
                str(video)], below, stdout=True)
    if out is None:
        return None                             # (ffprobe failed: asked again at the next press)
    try:
        listed = json.loads(out.decode("utf-8", "replace")).get("streams")
    except (ValueError, AttributeError):
        return None
    if len(_streams) >= STREAMS_MAX:
        _streams.clear()
    picked = _streams[key] = pick_stream(listed if isinstance(listed, list) else [], language)
    return picked


def pick_stream(streams, language):
    """Anki Miner's audio stream for `language` among ffprobe's `streams` (its `pick_audio_stream`): one tagged with
    the language's code (or its regional variant, ja-JP) — of several, the default one, else the first. None tagged
    so: the only stream there is (the one Anki Miner then takes too, `0:a:0`); of several, None — Anki Miner's next
    rule reads their titles in every language it knows, not copied here: `media` cuts those."""
    codes = AUDIO_CODES.get(language)
    if not codes:
        return None
    listed = []
    for stream in streams:
        if not isinstance(stream, dict):
            return None
        try:
            index = int(stream["index"])
        except (KeyError, TypeError, ValueError):
            continue
        tag = (stream.get("tags") or {}).get("language")
        tag = tag.lower() if isinstance(tag, str) and tag else None
        listed.append((index, tag, (stream.get("disposition") or {}).get("default") == 1))
    matches = [s for s in listed if s[1] and (s[1] in codes or ("-" in s[1] and s[1].partition("-")[0] in codes))]
    if matches:
        return next((s for s in matches if s[2]), matches[0])[0]
    return listed[0][0] if len(listed) == 1 and len(streams) == 1 else None


def command(ffmpeg, video, start, end, stream, got, out):
    """Anki Miner's own ffmpeg command for the line `start`-`end` (seconds) of `video`, its audio stream `stream`, the
    profile's settings `got` (`audio_settings`), into `out` — its 3.13 `resolve_audio_window` (the line widened by the
    padding each side, never before 0) and `_extract_audio`, argument for argument. No picture."""
    end = max(start, end)
    padded = start - got["padding"]
    begin = max(0.0, padded)
    length = (end - start) + (got["padding"] * 2) - (begin - padded)
    opus = got["format"] == "opus"
    cmd = [ffmpeg, "-y", "-ss", str(begin), "-t", str(length), "-i", str(video), "-map", f"0:{stream}", "-vn",
           "-acodec", "libopus" if opus else "libmp3lame",
           "-b:a", f"{min(got['bitrate'], OPUS_MAX_KBPS) if opus else got['bitrate']}k", "-ac", "1"]
    if got["normalize"]:
        cmd += ["-af", f"{LOUDNORM},afade=t=in:d={FADE_S},afade=t=out:st={max(length - FADE_S, 0.0):.3f}:d={FADE_S}",
                "-ar", LOUDNORM_RATE]
    return cmd + [str(out)]


def _run(cmd, below=False, stdout=False):
    """Run Anki Miner's ffmpeg / ffprobe with no window, ended with this process (`anki_miner._bind`), at most
    CUT_TIMEOUT -> its stdout (b"" when not asked), or None when it failed."""
    from app.connect import anki_miner
    proc = anki_miner._popen(cmd, below=below, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE if stdout else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=anki_miner.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    anki_miner._bind(proc)
    try:
        out, _err = proc.communicate(timeout=CUT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None
    return (out or b"") if proc.returncode == 0 else None


def _trim(folder, keep=None, cap=None):
    """Past `cap` (CAP_BYTES) the oldest clips go first, never `keep`; run folders a crash left go once old."""
    cap = CAP_BYTES if cap is None else cap
    now = time.time()
    clips = []
    try:
        with os.scandir(folder) as listing:
            for entry in listing:
                try:
                    st = entry.stat()
                except OSError:
                    continue
                if entry.is_dir():
                    if entry.name.startswith(".run-") and now - st.st_mtime > RUN_LEFT_S:
                        shutil.rmtree(entry.path, ignore_errors=True)
                elif os.path.splitext(entry.name)[1].lower() in KINDS:
                    clips.append((st.st_mtime_ns, st.st_size, entry.path))
    except OSError:
        return
    total = sum(size for _t, size, _p in clips)
    for _t, size, path in sorted(clips):
        if total <= cap:
            break
        if keep and os.path.normcase(path) == os.path.normcase(keep):
            continue
        try:
            os.remove(path)
            total -= size
        except OSError:
            continue                            # (the door serving it this moment: it goes next time)
