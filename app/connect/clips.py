"""The journey's ▶ on a line the browser can't play (an .mkv — most anime libraries; journey v3 SPEC §3.3 `clip/cut`,
§6's row; J-CLIP, PROVISIONAL): the line's audio cut on the press, kept for the next press.

- **One cutter:** `add_audio.cut` — Anki Miner's `media`, the function that cuts *Add audio*'s card clips, the line
  sent as its video's (`video_file`). No ffmpeg of Surasura's own, no new dependency, nothing off the PC.
- **The line:** the page's line id (`<item id>:<start ms>`, Swap's) found the one way Swap finds it
  (`swap.line_cue`: the item's subtitle in the library, the cue starting there now), and the item's video the one
  Connect's job would cut its cards from (`runner.Steps.video`). Its times are the subtitle's as the page shows them
  (the browser-played ▶'s own; no fit-check shift).
- **Kept, not stored:** each clip is derived data in a small cache of its own — `<Connect's folder>/clips/` in the
  local data folder (never synced, never listed, never a card's source; a card's media still comes from mining) —
  named by what it was cut from (the video's path, size and time, the line's times and text: a changed video or a
  re-timed line is cut again, never an old clip). Past CAP_BYTES the oldest clips go first (a clip played is new
  again); the folder may be deleted at any time. Nothing is cut for a line nobody pressed (the line to Torii, 3.1).
- **Two presses of one line at once:** one cut; the second waits for it and gets the same clip (or its refusal).
- **Ahead of a press** (`ahead`; measured, J-CLIP's register: a press takes 2.0–2.6 s, Anki Miner's own start 1.4–1.6 s
  of it, an 8-line call 2.7 s): the page, idle on a word, asks for the open episode's lines it shows — at most
  AHEAD_MAX, those not kept, in ONE call on a worker of its own, below normal priority; a newer ask replaces one not
  started; stopped the moment the learner presses anything on the page (`stop_ahead`, the door's every route but
  this ask). Never at Generate, never a whole library, never a line the page doesn't show.
- **Says why, never hangs:** `Refused` (its words, its `kind`) when Cards made for you is off, Anki Miner is absent or
  too old to cut a line, the line isn't one with a time in its file (or isn't there now), the video isn't on this PC,
  or Anki Miner couldn't cut it; a cut is stopped past CUT_TIMEOUT.

Runs on the door's thread (`door_routes.clip_route`); Qt-free; inert until the journey v3 page ships (J-CUT).
"""
import hashlib
import logging
import os
import shutil
import threading
import time

log = logging.getLogger("surasura-cli")

ROOT = "clips"                  # under Connect's folder (`verbs._connect_folder`): the local data folder
CAP_BYTES = 64 << 20            # the cache's size: ~400 lines of 192 kbps audio; the oldest dropped first past it
CUT_TIMEOUT = 30.0              # one cut at most (a share that stops answering never leaves ▶ waiting: the page waits 35 s)
RUN_LEFT_S = 60 * 60            # a run folder a crash left behind is removed once this old
AHEAD_MAX = 6                   # lines an ahead ask cuts, in one call (a word's shown lines: ~2.7 s for 8)
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
    kept = _kept(key)
    if kept:
        return kept
    with _lock:
        held = _cutting.get(key)
        mine = held is None
        if mine:
            held = _cutting[key] = [threading.Event(), None]
    if not mine:                                # a press of the same line is cutting it: its answer is this one's
        held[0].wait(CUT_TIMEOUT + 5)
        if held[1] is not None:
            raise held[1]
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
    if miner is None or not anki_miner.can_now({"Z-10"}):
        return
    steps = steps or runner.Steps(settings)
    can = {}
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
        if key in can or _kept(key) or key in _cutting:
            continue
        can[key] = lineup.Cue(video, subtitle, seconds(cue.start), seconds(cue.end), lineup.clean(cue.text))
    if not can or _ahead["stop"].is_set():
        return
    folder = root()
    run_dir = os.path.join(folder, f".run-ahead-{time.time_ns()}")
    os.makedirs(run_dir, exist_ok=True)
    try:
        try:
            cut = add_audio.cut(miner, language, None, can, run_dir, timeout=CUT_TIMEOUT,
                                on_poll=lambda: stopping.END if _ahead["stop"].is_set() else None, below=True)
        except (anki_miner.AnkiMinerError, stopping.Stopped):
            return
        for key, clip in cut.items():
            os.replace(clip, os.path.join(folder, key + os.path.splitext(clip)[1].lower()))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    _trim(folder)


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
    if not anki_miner.can_now({"Z-10"}):
        raise Refused(OLD_MINER, "absent")
    folder = root()
    run_dir = os.path.join(folder, f".run-{key[:12]}-{time.time_ns()}")
    os.makedirs(run_dir, exist_ok=True)
    try:
        # (the cutter matches Anki Miner's answer back by the line-up's text, `lineup.clean`, as its own cues are)
        line = lineup.Cue(video, subtitle, seconds(cue.start), seconds(cue.end), lineup.clean(cue.text))
        try:
            clips = add_audio.cut(miner, language, None, {0: line}, run_dir, timeout=CUT_TIMEOUT)
        except anki_miner.AnkiMinerError as e:
            raise Refused(FAILED.format(e.message), e.kind) from None
        clip = clips.get(0)
        if not clip:
            raise Refused(FAILED.format("no clip for that line"))
        path = os.path.join(folder, key + os.path.splitext(clip)[1].lower())
        os.replace(clip, path)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    _trim(folder, path)
    return path


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
