# SPDX-License-Identifier: GPL-3.0-or-later
"""Spaced Anki numbers — a move rewrites tens of cards instead of most of the backlog (E1.1 03, E2.1).

Junban numbers a deck's new cards densely from `min(due)` (`plan.py`): card *i* of the planned order
gets `base + i`. That keeps the block where it was, and it means one far move renumbers every card
between the old place and the new one — measured, about 1,170 of 2,000 cards (14,338 of 30,000). With
the fast re-plan's preview on, a move re-orders Anki about once a second, so that cost is paid on every
drag. The numbers here leave room instead: the cards that are still in order keep their numbers, and
only the others are given new ones in the gaps around them.

Everything here is pure — plain lists of ints in, plain lists out, no Anki, no files, no clock — for
the reason `plan.py` is: a position write cannot be undone by Anki and it syncs to every device, so
the numbers have to be provable against data alone.

**The ceiling (E0.1, measured on a test profile).** Anki's *Check Database* folds every new position
at or above 1,000,000 to `1,000,000 + due % 1,000,000` — order lost, cards collide — and its own
Reposition box stops at 1,000,000. So no number here is ever ≥ 1,000,000 or < 1: the ladder lives in
`base … 999,999`, `base` being the lowest current position of the cards when spacing begins (as 2.5's
block keeps its bottom: `plan.py`), kept from then on so it never climbs (`number`, E2.1-1). `number`
checks every list it returns and raises rather than hand one back that breaks either bound or fails
to increase.

**The ladder (a full write).** Card *i* of *n* gets `base + floor((999,999 − base) · ((i+1)/(n+1))^0.6)`:
front-weighted — the widest gaps at the front, where moves and newly mined cards land most. With less
room than two numbers a card (`999,999 − base < 2n`) it falls back to 2.5's dense numbers from `base`.

**The delta.** In the planned order, the cards on a longest increasing run of their current numbers
keep them; each run of the others gets numbers spread evenly between its kept neighbours. When a run
finds no room, its window grows (16 cards each side, then doubling) until the window's average gap is
at least `max(2, (g/2)^(log w / log n))` — *g* the ladder's average gap, *w* the window's cards (list
labelling's graded threshold: small windows may stay denser than large ones) — and the whole window is
spread evenly; kept cards inside it are rewritten too. A window that reaches the whole ladder is the
one full rewrite. Past the ladder's ends the same rule runs against `base` and 999,999; a run past the
last kept card (or before the first) takes the even gap when it fits.

Simulated on the study's synthetic library (`tracks/engine/work/E1.1-gap-sim.md`, scheme F-LLg; 1,000
moves, 20 cards studied and 20 mined a day): a median of 19 / 29 / 66 cards written per reorder at
2,000 / 10,000 / 30,000 new cards, against dense numbering's 883 / 4,527 / 23,333, with no full rewrite
in ~1,370 reorders.

**Tomorrow's cards go first** (03 §3.6, `front_group`, `requests`): every changed card among the plan's
first N, and every card pushed out of that front, go in the first request (or the first few, when there
are more than `junban_chunk_size`) — so that the moment they land, Anki's first N new cards are exactly
the plan's first N, whatever happens to the rest of the job.

**Tomorrow's own numbers first** (E3.3, Sonic's A for E3.1-B3; `_front_first`): when a move would push more
cards out of tomorrow's than tomorrow holds — an item at the front moved to the back, its hundred cards all
needing to go back before tomorrow's are first — tomorrow's N cards are numbered instead below every other
card's current number (in the upper half of the room above the bottom), so the first request is tomorrow's
own N cards and the cards they pass follow in the next requests. With no room, today's rule.
"""

import math
from bisect import bisect_left

CEILING = 999_999           # E0.1: Check Database folds every new position >= 1,000,000
FLOOR = 1                   # Anki's own positions start at 1; nothing here goes below it
POWER = 0.6                 # the ladder's front weighting (F-LLg)
TAU = 0.5                   # a window's bar: half the ladder's average gap, graded by its size
FIRST_WINDOW = 16           # a run's window first grows by 16 cards each side, then doubles
FRONT_MIN = 20              # the next day's cards: the deck's New cards/day, never fewer than 20 (D6)

# What `number` did, for the panel and the bar: the first spaced run is a full write, announced (03 §2).
DENSE, FULL, DELTA = "dense", "full", "delta"


class SpacedError(ValueError):
    """No numbering of these cards fits between 1 and 999,999 (more than 999,999 new cards), or a list
    failed its own check. Nothing is written: the caller refuses the run with this message."""


def layout(n, base, ceiling=CEILING):
    """The ladder for a full write: `n` numbers from `base` up to `ceiling`, front-weighted, strictly
    increasing. With less room than two numbers a card, 2.5's dense numbers from `base` instead."""
    if n <= 0:
        return []
    span = ceiling - base
    if span < 2 * n:
        return _dense(n, base, ceiling)
    out = [base + int(span * ((i + 1) / (n + 1)) ** POWER) for i in range(n)]
    for i in range(1, n):                       # ties broken by +1 (never seen at these sizes)
        if out[i] <= out[i - 1]:
            out[i] = out[i - 1] + 1
    if out[-1] > ceiling:
        return _dense(n, base, ceiling)
    return out


def _dense(n, base, ceiling):
    """2.5's numbers, `base + i` — moved down only as far as it takes to stay at or under the ceiling."""
    base = min(base, ceiling - n + 1)
    if base < FLOOR:
        raise SpacedError(f"{n:,} new cards can't be numbered between {FLOOR} and {ceiling:,}, "
                          "Anki's highest safe position.")
    return list(range(base, base + n))


def is_spaced(olds, base, ceiling=CEILING, laid=False):
    """Do these cards already sit on a ladder? Never for 2.5's dense numbers (an average gap under 2), so
    the first spaced run is the full write (03 §2), and so is the first run after Anki renumbered the
    deck (a changed insertion order renumbers from 1) or after the preview was off a while.

    `laid`: a ladder was laid for this deck before (its bottom is recorded) — then the average gap alone
    decides: deltas, studying and mining reshape a ladder, a small deck's especially, and a guess at its
    shape would re-lay it whole on a run that changed nothing (review 2 #4). Never laid, the guess: the
    card nine tenths of the way up (of those inside the ceiling) stands a quarter of the room or more
    above `base` — so a dense deck with a few stray cards far above is still dense."""
    inside = sorted(value for value in olds if base <= value <= ceiling)
    if len(inside) < 2:
        return False
    if inside[-1] - inside[0] < 2 * (len(inside) - 1):     # from the lowest card: a recorded floor can sit far
        return False                                       # below a block 2.5 renumbered densely (review 3 #1)
    return laid or inside[(9 * len(inside)) // 10] - base >= (ceiling - base) // 4


def number(olds, floor=None, ceiling=CEILING, front=None):
    """The new numbers for cards in their planned order. `olds` are the cards' current numbers in that
    order; `floor` the ladder's bottom as last recorded (`undo.ladder_floor`), or None. Returns
    `(news, info)`:

      * `news` — strictly increasing, every one in `[1, ceiling]`, one per card;
      * `info` — `{"kind": "dense" | "full" | "delta", "base", "windows": [cards per re-spaced window],
        "full_rewrite": bool}`: "full" is the ladder written whole (the first spaced run, or a window
        that reached every card), "dense" the fallback when the room is too small. `base` is the
        bottom this numbering used — the caller records it as the next run's `floor`.

    **The bottom is kept, never climbs** (E2.1-1): `base` is the lower of `floor` and the lowest
    current number. Taken afresh from the lowest current number on every run (03 §1 as signed), it
    climbs with every card studied — each takes its number with it — and the room above it shrinks:
    measured, 3,000 → 610,000 in 150 simulated days at 2,000 cards, writes per move up 40 % and still
    rising. Recorded, the room studied cards leave at the front is used again by the next move there.

    A recorded `floor` also says a ladder was laid for this deck before (`is_spaced(laid=)`), and
    `info["laid"]` carries it: the bar says "spaced out once" the first time, "again" after.

    `front`: N, tomorrow's cards (the run's `front_size`), or None. Given, a delta that would push more
    cards out of the plan's first N than N numbers tomorrow's cards below every other card instead
    (`_front_first`, E3.3), so the first request is at most N cards; `info["front_first"]` says so.

    Raises `SpacedError` when no numbering fits. The caller writes only the cards whose number changed.
    """
    olds = [int(value) for value in olds]
    n = len(olds)
    laid = isinstance(floor, int) and not isinstance(floor, bool)
    if n == 0:
        return [], {"kind": DELTA, "base": None, "windows": [], "full_rewrite": False, "laid": laid,
                    "front_first": False}
    base = min(olds)
    if laid and floor < base:
        base = floor
    base = max(FLOOR, base)
    if ceiling - base < 2 * n:
        news, info = _dense(n, base, ceiling), {"kind": DENSE, "windows": [], "full_rewrite": False, "front_first": False}
        base = news[0]                  # moved down when the block would have passed the ceiling
    elif not is_spaced(olds, base, ceiling, laid):
        news, info = layout(n, base, ceiling), {"kind": FULL, "windows": [], "full_rewrite": True, "front_first": False}
    else:
        news, info = delta(olds, base, ceiling)
        first = _front_first(olds, news, base, front)
        if first is not None:
            news = first
        info["front_first"] = first is not None
    info["base"], info["laid"] = base, laid
    _check(news, n, ceiling)
    return news, info


def _front_first(olds, news, base, front):
    """E3.3 (Sonic's A for E3.1-B3): `news` with the plan's first `front` cards renumbered below every other card's
    current number, or None to keep `news` as it is.

    `front_group` puts in the first request every card pushed out of tomorrow's — its current number at or below the
    new number of the plan's `front`-th card. A move that sends an item at the front to the back pushes out all its
    cards (a hundred and more), and the first request waits on all of them. When more cards would be pushed out than
    tomorrow holds, tomorrow's cards take numbers below the lowest current number outside them (and below the plan's
    next card's new number): then no card is pushed out, the first request is tomorrow's own cards, and the others
    follow, each request still sending none of tomorrow's back. They take the upper half of the room above the
    bottom, evenly, so later moves find room too; with less than two numbers a card there, None (today's rule)."""
    n = len(olds)
    count = min(max(int(front or 0), 0), n)
    if not count or count >= n:
        return None
    cut = news[count - 1]
    pushed = sum(1 for i in range(count, n) if news[i] != olds[i] and olds[i] <= cut)
    if pushed <= count:
        return None                             # the first request is no bigger than tomorrow's own cards
    high = min(min(olds[count:]), news[count])  # every number tomorrow takes is below this
    half = (high - base) // 2                   # the upper half of base … high - 1
    if half < 2 * count:
        return None
    step = half // count
    return [high - step * (count - m) for m in range(count)] + list(news[count:])


def delta(olds, base, ceiling=CEILING):
    """Renumber only what is out of order (the module docstring's *delta*). `olds` in the planned order;
    `base` the ladder's bottom (no number below it). Returns `(news, info)` as `number` does, kind
    "delta" — or "full" when a window had to take in every card."""
    n = len(olds)
    keep = _longest_run(olds, base, ceiling)
    new = list(olds)
    nominal = (ceiling - base) / (n + 1)                # the even gap
    half = TAU * (ceiling - base + 2) / (n + 1)         # half the ladder's average gap
    windows, full = [], False
    i = 0
    while i < n:
        if keep[i]:
            i += 1
            continue
        j = i
        while j < n and not keep[j]:
            j += 1
        a, b = i, j
        widened = False
        while True:
            lo = new[a - 1] if a > 0 else base - 1
            hi = new[b] if b < n else ceiling + 1
            k = b - a
            whole = a == 0 and b == n
            room = whole or hi - lo - 1 >= k
            if room and widened and not whole:
                room = (hi - lo) / (k + 1) >= _bar(k, n, half)
            if room:
                if whole:
                    new = layout(n, base, ceiling)
                elif b == n and not widened:            # past the last kept card: the even gap, if it fits
                    step = min(nominal, (hi - lo) / (k + 1))
                    for m in range(a, b):
                        new[m] = math.floor(lo + step * (m - a + 1))
                elif a == 0 and not widened:            # before the first kept card
                    step = min(nominal, (hi - lo) / (k + 1))
                    for m in range(a, b):
                        new[m] = math.ceil(hi - step * (b - m))
                else:                                   # between two kept cards: spread evenly
                    step = (hi - lo) / (k + 1)
                    for m in range(a, b):
                        new[m] = math.floor(lo + step * (m - a + 1))
                break
            widened = True
            grow = max(FIRST_WINDOW, b - a)             # 16 cards each side at first, then doubling
            a, b = max(0, a - grow), min(n, b + grow)
            while b < n and not keep[b]:                # the right edge is always a kept (settled) number
                b += 1
        if widened:
            windows.append(b - a)
        full = full or (a == 0 and b == n)              # the whole ladder written: the one full rewrite
        i = max(j, b)
    return new, {"kind": FULL if full else DELTA, "windows": windows, "full_rewrite": full}


def _bar(k, n, half):
    """The average gap a re-spaced window of `k` cards must reach: `max(2, half^(log k / log n))`."""
    if k <= 1 or n <= 1:
        return 2.0
    return max(2.0, half ** (math.log(k) / math.log(n)))


def _longest_run(olds, low, high):
    """`keep[i]` for one longest strictly increasing run of `olds` among the values in `[low, high]`
    (patience sorting, O(n log n)). A number outside the bounds is never kept: it is rewritten."""
    n = len(olds)
    tails, tails_at, previous = [], [], [-1] * n
    for index, value in enumerate(olds):
        if value < low or value > high:
            continue
        place = bisect_left(tails, value)
        if place == len(tails):
            tails.append(value)
            tails_at.append(index)
        else:
            tails[place] = value
            tails_at[place] = index
        previous[index] = tails_at[place - 1] if place > 0 else -1
    keep = [False] * n
    index = tails_at[-1] if tails_at else -1
    while index >= 0:
        keep[index] = True
        index = previous[index]
    return keep


def _check(news, n, ceiling):
    """The bounds, asserted on every list `number` hands back: one per card, each in `[1, ceiling]`,
    strictly increasing. A failure is a bug — and it stops the run before a single write."""
    if len(news) != n:
        raise SpacedError(f"Junban numbered {len(news)} of {n} cards; nothing was written.")
    for index, value in enumerate(news):
        if not isinstance(value, int) or value < FLOOR or value > ceiling:
            raise SpacedError(f"Junban computed position {value!r}, outside 1–{ceiling:,}; nothing was written.")
        if index and value <= news[index - 1]:
            raise SpacedError("Junban computed positions out of order; nothing was written.")


def front_size(per_day):
    """N, the next day's cards (D6): the scoped deck's *New cards/day*, at least 20. `per_day` is what
    the deck options say (an int, or None when they couldn't be read)."""
    if isinstance(per_day, int) and not isinstance(per_day, bool) and per_day > FRONT_MIN:
        return per_day
    return FRONT_MIN


def front_group(order, news, front):
    """Tomorrow's writes (03 §3.6): every changed card among the plan's first `front`, and every card not
    among them whose current number is at or below the new number of the plan's `front`-th card — it
    has to be pushed out (at, too: two cards on one number leave their order to Anki). Once these have
    landed, Anki's first `front` new cards are exactly the plan's. `[(card_id, new)]`, front first."""
    count = min(max(int(front or 0), 0), len(order))
    if not count:
        return []
    cut = news[count - 1]
    return [(card_id, new) for index, ((card_id, old), new) in enumerate(zip(order, news))
            if new != old and (index < count or old <= cut)]


def requests(order, news, front, chunk):
    """The writes, as requests (03 §3.6). `order` is `[(card_id, current)]` in the planned order, `news`
    the new numbers. Returns `[[(card_id, new)]]`: first tomorrow's cards (`front_group`), then the
    rest, each `chunk` at a time. The front group is usually one request (a move's tens of cards); the
    first spaced run's is the whole deck, and one request of thousands would freeze Anki with no
    progress and outlast AnkiConnect's time limit — so Anki's first `front` cards are the plan's once
    the front group's LAST request has landed, the rest still going in the background.

    **Inside each group, the cards moving back go first — the furthest back first — then the cards moving
    forward, the front-most first** (`_safe_order`; review 2 #1). A job can stop between two requests
    (Anki closed, the app quit); written front first, the first spaced run's opening requests lifted
    tomorrow's cards above every card not yet written. In this order tomorrow's cards are never sent
    back, wherever a job stops; past them, a stopped job leaves a mix of the old order and the new
    (a card pushed out of tomorrow's can wait behind a block not yet moved back — review 3 #3).

    Only changed cards are written; empty when nothing changed.
    """
    order, news = list(order), list(news)
    old_of = dict(order)
    changed = [(card_id, new) for (card_id, old), new in zip(order, news) if new != old]
    if not changed:
        return []
    first = front_group(order, news, front)
    taken = {card_id for card_id, _new in first}
    rest = [pair for pair in changed if pair[0] not in taken]
    first, rest = _safe_order(first, old_of), _safe_order(rest, old_of)
    size = max(1, int(chunk or 1))
    return ([first[start:start + size] for start in range(0, len(first), size)]
            + [rest[start:start + size] for start in range(0, len(rest), size)])


def _safe_order(pairs, old_of):
    """`[(card_id, new)]` with the cards moving back first (the highest new number first), then the cards
    moving forward (the lowest first) — `requests`' order inside a group."""
    back = sorted((pair for pair in pairs if pair[1] > old_of[pair[0]]), key=lambda pair: -pair[1])
    forward = sorted((pair for pair in pairs if pair[1] < old_of[pair[0]]), key=lambda pair: pair[1])
    return back + forward


class Numbering:
    """`plan`'s `number=` for the fast re-plan's preview (03 §2): `numbering(dues)` -> `number(dues, floor)`.

    `after` is the highest card id the last spaced run placed (`undo.ladder`): a card made since is new
    to the ladder, and Anki numbered it at its next-position counter — below a spaced ladder — so among
    cards nothing else tells apart (`plan`'s ties) it goes after the others, as 2.5's counter put it,
    while every card already placed keeps its existing order (a curated deck's included; review 2 #3).
    None: no card counts as new (the first spaced run)."""

    def __init__(self, floor=None, after=None, front=None):
        self.floor = floor
        self.after = after
        self.front = front              # N, tomorrow's cards (E3.3): None numbers as before

    def __call__(self, dues):
        return number(dues, floor=self.floor, front=self.front)


class Job:
    """One Junban writer's run with the fast re-plan's preview on (03 §3) — handed to `reposition.run`,
    `dry_run` and `auto.reorder` as `job=`. `None` there is 2.5's run, byte for byte.

      * `automatic` — an automatic re-order (the dashboard's step, the Content Manager's job, Connect's
        2.x step): its way back is today's baseline (`undo.save_baseline`, 03 §5), written once a day
        and never a reason to refuse; positions only. A run from the 順 window keeps 2.5's snapshot.
      * `rows` — the fast re-plan's rows (`plan_engine.Result.rows(order_mode)`, 02 §4) to rank by,
        instead of the list's CSV.
      * `cards` — a warm `reposition.CardMap` kept between jobs (03 §3.2); None reads the deck afresh.
      * `front` — N, the next day's cards; None reads the deck's *New cards/day* (D6, at least 20).
      * `places` — RP-10 (E3.1): `{the last Generate's file number: its number in the new order}`, for the numbers
        `library_frequency.json` and the phrase places still carry (a word below the list's cut-off, a phrase card
        found in the library); None, or a number it doesn't hold, keeps the number as written.
      * `probe` — `reposition.probe_anki`'s answer, asked by the job's caller a moment before (E3.1-B2: the preview
        probes before reading the library); the run's preflight asks nothing again. None: the run probes.
      * `actions` — 3.0 (W3.5 row 7, Haya's G2b): an automatic job `auto.reorder` hands in, its settings already
        decided there (`junban_auto_actions`, Connect's preview, `positions_only`, the unattended suspend). The run
        applies them after the positions, under one restore point; with a review or a card left meanwhile, none
        this run. 2.x-dev has no such key (the fast re-plan's host moves positions only there); 3.0: the window's
        re-order host sets it too, its settings decided by `auto.decide_actions`. Without it, positions only.
      * `cards_out` — P4.1 L2 (*Take its new cards out*, D14): the caller records what the run changes for it in the
        store (`pins.record`: the window's re-order host, Connect's step) — then, with `actions`, a taken-out item's
        new cards are suspended and tagged and an item put back has exactly its recorded cards restored first. Off
        (every other run, `junban --auto` and `resort`'s positions only), they are only placed after every other card.

    The run fills in, for its caller's progress line: `front_size` (N), `front_ids` (tomorrow's writes: the card
    ids `front_group` chose) and `kind` (the numbering's: `DENSE`, `FULL` or `DELTA`); and `stopped_for_review`
    when an automatic job stopped between requests because a review began.
    """

    def __init__(self, automatic=False, rows=None, cards=None, front=None, places=None, probe=None, actions=False):
        self.automatic = bool(automatic)
        self.actions = bool(actions)
        self.rows = rows
        self.cards = cards
        # At least 1: a front of 0 would silently drop the guarantee (review 2 #12).
        self.front = None if front is None else max(1, int(front))
        self.places = places
        self.probe = probe
        self.front_size = None
        self.front_ids = frozenset()
        self.kind = None
        self.stopped_for_review = False
        self.anki_busy = False          # #370: Anki busy (its sync) stopped the writes part-way: the rest in `left`
        self.cards_out = False          # P4.1 L2: set by a caller that records (`pins.record`)
        self.put_back = []              # … and the run fills in the records its Put back restored
        self.put_back_owed = None       # … and what it left owed (TF fix 6: `reposition._put_back_owed`)
