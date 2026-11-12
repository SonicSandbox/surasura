"""YouTube's bot check, met once, holds every YouTube download for a day — and one YouTube call at a time, a little
apart (Yt-B, 3.0.1; Sonic 2026-11-12: "will this hit from my own network and then will I have issues in the future
with too many requests?").

Every YouTube download Surasura makes runs on the learner's own computer, from their own address: the YouTube
downloader's yt-dlp (transcripts, setup's first videos, a playlist's rest, Preview, the cue backfill) and Connect's
video for a YouTube title (Anki Miner's `fetch`). YouTube answers too many requests from one address without a sign-in
with "Sign in to confirm you're not a bot" or HTTP 429, and asking again straight away only makes that last longer. So:

- `refused(text)`: does yt-dlp's (or Anki Miner's) output say YouTube turned the computer away? An age check ("Sign in
  to confirm your age") is a video's own and never one.
- `hold()`: the first refusal holds every YouTube call for HOLD_S (a day) from then — a refusal met during a hold
  never lengthens it; `held()` -> the hold's end while it runs, else None; `words(until)`: it said, with when it tries
  again.
- `turn(should_stop)`: one YouTube call at a time on this computer (the `youtube` lock, `app/locks.py`: the window,
  Preview's child and Connect alike), at least GAP_S after the last one ended. Inside a turn the caller checks
  `held()` first and calls `hold()` on a refusal, so both writes happen under the lock.

The record: `<persistent>/youtube_hold.json` {"until", "since", "last"} (epoch seconds). One missing or unreadable is
no hold — a broken file never stops YouTube for good — and an end more than HOLD_S away (the clock was moved) is
none either. bilibili.tv is another site and never held here.

Standard library only; no Qt.
"""
import contextlib
import json
import os
import re
import time

from app import locks, path_utils

HOLD_S = 24 * 60 * 60           # a refusal holds every YouTube call this long (PROVISIONAL: "the rest of the day")
GAP_S = 2.0                     # the least time between two YouTube calls on this computer
LOCK = "youtube"
NAME = "youtube_hold.json"

# yt-dlp's words for YouTube turning the computer away (and Anki Miner's, which passes them on). "Sign in to
# confirm your age" is a video's age check: it holds nothing.
REFUSED = re.compile(r"not a bot|confirm you.?re not|HTTP Error 429|too many requests|rate[- ]?limit", re.I)

HEAD = "YouTube asked to prove this computer isn't a bot"
# PROVISIONAL (learner-visible): the one sentence every YouTube path says while a hold runs
WORDS = HEAD + ", so every YouTube download waits until {when} (asking again sooner makes it last longer)."


class Stopped(Exception):
    """A turn waited for was given up: `should_stop()` turned true."""


def refused(text):
    return bool(REFUSED.search(str(text or "")))


def _path():
    return os.path.join(path_utils.get_persistent_user_data_path(), NAME)


def _read():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data):
    path = _path()
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    for attempt in range(5):                # a reader holding it for a moment (a virus scanner) waited out
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def held(now=None):
    """The end of the hold running now (epoch seconds), or None."""
    now = time.time() if now is None else now
    until = _number(_read().get("until"))
    return until if until is not None and now < until <= now + HOLD_S else None


def hold(now=None):
    """YouTube refused: every YouTube call waits HOLD_S from now -> the hold's end. One already running stays as it
    is (a refusal met during it never lengthens it). A record that can't be written is logged by the caller's own
    except: the run stops there all the same."""
    now = time.time() if now is None else now
    running = held(now)
    if running is not None:
        return running
    data = _read()
    data.update(until=now + HOLD_S, since=now)
    _write(data)
    return now + HOLD_S


def words(until, now=None):
    """The hold said, with when it ends: "today at 09:15" / "tomorrow at 21:42" (the computer's own clock)."""
    now = time.time() if now is None else now
    end, today = time.localtime(until), time.localtime(now)
    day = "today" if end[:3] == today[:3] else "tomorrow"           # (`held` keeps an end within HOLD_S)
    return WORDS.format(when=f"{day} at {time.strftime('%H:%M', end)}")


def is_words(text):
    """Is this line (or the end of one) the hold's own sentence?"""
    return HEAD in str(text or "")


def _wait(seconds, should_stop):
    end = time.monotonic() + seconds
    while True:
        if should_stop is not None and should_stop():
            raise Stopped()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.25, left))


@contextlib.contextmanager
def turn(should_stop=None, verb="YouTube download"):
    """One YouTube call: the `youtube` lock taken (waited for, asking `should_stop()` every quarter second ->
    Stopped), then GAP_S since the last call ended waited out; the call's end recorded as it lets go."""
    while True:
        try:
            taken = locks.take(LOCK, verb)
            break
        except locks.Busy:
            _wait(locks.POLL, should_stop)
    try:
        last = _number(_read().get("last"))
        if last is not None:
            _wait(max(0.0, min(GAP_S, last + GAP_S - time.time())), should_stop)
        yield
    finally:
        try:
            data = _read()
            data["last"] = time.time()
            _write(data)
        except OSError:
            pass                            # only the gap is lost: the next call goes at once
        taken.release()
