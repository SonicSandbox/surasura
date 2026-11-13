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
SLACK_S = 60 * 60               # an end this much past a day away still holds (the clock set back a little)
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


def _read(tries=5):
    """The record -> a dict ({} when there is none, or it is broken), or None when it couldn't be read (a scanner
    holding it: read again `tries` times, 0.1 s apart, first): a writer then leaves it as it is, never writing over a
    hold it didn't see."""
    for attempt in range(tries):
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}
        except OSError:
            if attempt < tries - 1:
                time.sleep(0.1)
    return None


def _write(data):
    path = _path()
    temp = f"{path}.{os.getpid()}.tmp"              # each program's own: two installs never share one
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
    until = _number((_read() or {}).get("until"))
    return until if until is not None and now < until <= now + HOLD_S + SLACK_S else None


def hold(now=None):
    """YouTube refused: every YouTube call waits HOLD_S from now -> the hold's end. One already running stays as it
    is (a refusal met during it never lengthens it). A record that can't be written is logged by the caller's own
    except: the run stops there all the same."""
    now = time.time() if now is None else now
    running = held(now)
    if running is not None:
        return running
    data = _read() or {}                    # (unreadable after its tries: the hold matters more than `last`)
    data.update(until=now + HOLD_S, since=now)
    _write(data)
    return now + HOLD_S


_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def words(until):
    """The hold said, with when it ends: "Thursday at 21:42" (the computer's own clock) — the same words all through
    the hold, so Connect's Needs you counts it once."""
    end = time.localtime(until)
    return WORDS.format(when=f"{_DAYS[end.tm_wday]} at {time.strftime('%H:%M', end)}")


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


def _gap():
    """The seconds still to wait since the last YouTube call ended (at most GAP_S: a clock set back never waits
    longer)."""
    last = _number((_read(1) or {}).get("last"))
    return 0.0 if last is None else max(0.0, min(GAP_S, last + GAP_S - time.time()))


@contextlib.contextmanager
def turn(should_stop=None, verb="YouTube download", on_wait=None):
    """One YouTube call: GAP_S since the last call ended waited out BEFORE the `youtube` lock is taken — so a
    program that just let go doesn't win it straight back from one waiting — then taken (waited for, asking
    `should_stop()` every quarter second -> Stopped; `on_wait(the holder's verb)` once, when another program holds
    it), and the gap looked at again; the call's end recorded as it lets go."""
    taken, said = None, False
    while True:
        _wait(_gap(), should_stop)
        try:
            taken = locks.take(LOCK, verb)
        except locks.Busy:
            if locks.unopenable(LOCK):          # (a folder it can't write: no one holds it — the call goes)
                break
            if on_wait is not None and not said:
                said = True
                holder = locks.read_holder(LOCK) or {}
                try:
                    on_wait(str(holder.get("verb") or "another YouTube download"))
                except Exception:
                    pass
            _wait(locks.POLL, should_stop)
            continue
        except OSError:
            break
        if _gap() <= 0:
            break
        taken.release()                         # (another call ended meanwhile: its gap first)
        taken = None
    try:
        yield
    finally:
        try:
            data = _read()
            if data is not None:            # (unreadable just now: left as it is, a hold in it kept)
                data["last"] = time.time()
                _write(data)
        except OSError:
            pass                            # only the gap is lost: the next call goes at once
        if taken is not None:
            taken.release()
