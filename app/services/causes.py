"""Why it happened (the help cards' spec §5, HG-2: *Why?* first): one cause line for what Surasura did by itself.

**The rule.** A cause is said only for what Surasura did **without a press just then** (an automatic job), or **did
more than the press said** (a show finishing after its last Done). A job you started has none: your press is the cause,
and its wait already says its reason. A cause is one line of plain words, with the time when it has one.

**One shape** — `Cause(line, at, card)`: `line` the words (*you moved Show B ep 3*), `at` when (the wall clock,
`time.time()`; None: no time), `card` the help card it opens (`app/services/help_cards.py`'s id; None: none).
**One formatter** — `when(at, now)` writes every time the window shows beside a cause or on the phase strip's
*Last:* line: today *14:02*, yesterday *yesterday 21:14*, older *Oct 30, 21:14*, none → "". `said(cause, now)` is
the hover's and the card's line: *Why: you moved Show B ep 3 · 14:02*.

Qt-free; the words come from the caller (the window's strings table holds them), so a cause is a record: it keeps the
words it had when it was made (a title renamed since stays as it was, like *Last:*).
"""
import time
from collections import namedtuple

Cause = namedtuple("Cause", "line at card", defaults=(None, None))

WHY = "Why: {line}"                 # (the formats are plain words with no translation yet; the window's strings table
WHY_AT = "Why: {line} · {time}"     # ... re-exports them so every user string has one home: `app/qt/strings.py`)
TODAY = "%H:%M"
YESTERDAY = "yesterday %H:%M"
OLDER = "%b %d, %H:%M"


def when(at, now=None):
    """`at` (seconds, the wall clock) as the window writes a time: *14:02* today, *yesterday 21:14*, *Oct 30, 21:14*
    older (a time ahead of `now` — another PC's clock — reads as today's); None → ""."""
    if at is None:
        return ""
    now = time.time() if now is None else now
    then, today = time.localtime(at), time.localtime(now)
    day = (then.tm_year, then.tm_yday)
    if day >= (today.tm_year, today.tm_yday):
        return time.strftime(TODAY, then)
    yesterday = time.localtime(time.mktime((today.tm_year, today.tm_mon, today.tm_mday - 1, 12, 0, 0, 0, 0, -1)))
    if day == (yesterday.tm_year, yesterday.tm_yday):
        return time.strftime(YESTERDAY, then)
    out = time.strftime(OLDER, then)
    return out.replace(" 0", " ", 1)                # *Oct 3, 21:14*, never *Oct 03*


def said(cause, now=None, why=WHY, why_at=WHY_AT):
    """The one line a cause is shown as (*Why: you moved Show B ep 3 · 14:02*), or "" for none."""
    if cause is None or not cause.line:
        return ""
    at = when(cause.at, now)
    return why_at.format(line=cause.line, time=at) if at else why.format(line=cause.line)


def of(line, at=None, card=None):
    """A cause, stamped now when `at` is True (the moment its job was asked for)."""
    return Cause(line, time.time() if at is True else at, card)
