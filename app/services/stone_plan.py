"""The string of stones, planned (W3.1a package C; the RUNBOOK's §1 *The string*, §3, §4 row C): pure and Qt-free, so
every rule is tested without a window and the painter only blits what the plan says.

A Current row's string is one stone per file, along a hairline (the reference page `list-r14m.html`, `gemPlan` r9
:6800 then r11 :7442; the extract `w31a/ref-extract.md` §4):
- **the tiers** — the watched past before the twelve in play, fused into cut groups: a 120 where the whole 120 lies
  inside, else a 60, else a 12 (`r8Tiers` :2562). They always come out whole: they run to s0 = floor(next / 12) × 12;
- **the twelve in play**, s0…s0+12 (or what is left), one stone each: `cut` (watched) · `raw` (in Anki) · `rock`
  (not in Anki); the next one `big`; a stone `dim` when it isn't mined, isn't watched and lies below the top 20.
  Never cut to make room;
- **one ore** for everything after, with its mined and watched counts (a watched file past the twelve shows on the ore
  as 1–3 cut points, gem-kit's `o.cut`).
A finished piece whose last twelve is whole (all watched, a multiple of 12 files: `r10Whole` :7343) shows its tiers
only; a one-file row is a single stone. A piece counts its twelves from its **own** first file (the brief: "It should be
12 regardless"; the page's `r8Off = () => 0`, :6796), so a split part's episodes are the piece's own files.

`layout(plan, width, fz)` lays the string out on its row (`r8Place` :2544, `r11Place` / `r11Fit` :7425–7440): short
of room the watched loose stones step closer (28 → 14), then consecutive cut groups overlap (to half), then the watched
stones step closer still (14 → 8); stones never shrink, and what still doesn't fit comes back as a shortfall, which
`title_width` takes off the one title column every row shares (`r11Title` :7463).

Every user-facing word is in `WORDS` (Mado moves them to `app/qt/strings.py`); nothing here imports Qt, Tk or pandas.
"""
import math
from collections import namedtuple
from functools import lru_cache

from app.theme import KIND_GEM

BLOCK = 12                                  # the twelve in play; a 12-group
STONE_W = 28                                # a single stone's step (logical px at fz 1)
STEP_CLOSER = 14                            # short of room: watched loose stones first step to here …
STEP_LAST = 8                               # … then, after the groups overlap, to here at the least
OVERLAP_MIN = .5                            # an overlapped cut group keeps at least half of itself showing
TIER_W = {12: 40, 60: 50, 120: 54}          # a cut group's slot
ORE_W = 46
FIRST_CENTRE = 24                           # the first centre; the string ends 12 past the last slot
END_PAD = 12
TITLE_BASE = 187                            # the title column, × fz (215 at Medium, the page's `--r11-tw`)
TITLE_FLOOR = 80                            # … narrowed to round(80 × fz) at the least
VARIANTS = 8                                # a fixed set of variants per state × kind on the stone sheet

# a work's media type (`view_rows.MEDIA_WORD`'s keys) -> its kind (the page's `gemKind` :2490); None -> shows
_KIND = {"anime": "shows", "drama": "shows", "movie": "shows", None: "shows",
         "youtube": "videos", "podcast": "videos",
         "book": "reading", "lightnovel": "reading", "manga": "reading", "text": "reading", "audiobook": "reading",
         "game": "reading"}

WORDS = {
    "of_watched": "{k} of {n} watched", "in_anki": "{n} in Anki",
    "one_watched": "Watched", "one_not": "Not watched yet", "one_in_anki": "in Anki",
    "join": ", ",
}


class Tier(namedtuple("Tier", "start n variant")):
    """A watched group of `n` (12 · 60 · 120) files from the piece's file `start`."""
    __slots__ = ()
    kind = "tier"


class Stone(namedtuple("Stone", "index state big dim variant missing removed")):
    """One file of the twelve in play (or a one-file row): `state` cut · raw · rock."""
    __slots__ = ()
    kind = "stone"


class Ore(namedtuple("Ore", "start n mined watched cut_points mined_step variant")):
    """Everything after the twelve: `mined` / `watched` of its `n`; `cut_points` 0–3 (watched already, gem-kit's
    `o.cut`); `mined_step` 0 none · 1 up to half · 2 more · 3 all (the sheet's four ores)."""
    __slots__ = ()
    kind = "ore"


Plan = namedtuple("Plan", "gem items n watched in_anki next twelve single")
#   items: Tier / Stone / Ore in order · next: the next file's index, None when all are watched · twelve: (s0, s1)
Layout = namedtuple("Layout", "xs end ws cf fits shortfall")
#   xs: each item's centre (logical px) · end: where the string ends · ws: the watched loose stones' step · cf: the
#   overlapped groups' share · shortfall: px still missing at the tightest (0 when it fits)


def gem_of(media, mix=False):
    """The gem by the row's media type: shows → sapphire, reading → emerald, videos → ruby; hato's mix is sapphire."""
    return KIND_GEM["shows" if mix else _KIND.get(media, "shows")]


def variant(key, *place):
    """A stable variant 0…7 for (row key, place): FNV-1a 32 over the text, mixed (MurmurHash3's finaliser: FNV-1a
    alone barely moves its top bits for keys a digit apart, so neighbouring stones would repeat) — the same in every
    run (never Python's `hash()`, which is salted per process)."""
    h = 0x811C9DC5
    for b in ":".join(str(x) for x in (key,) + place).encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    h = ((h ^ (h >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return (h ^ (h >> 16)) % VARIANTS


def tiers(a, b):
    """The cut groups over files a…b (a a multiple of 12): a 120 where the whole 120 lies inside, else a 60, else a 12
    -> [(start, n)]."""
    out, x = [], a
    while x < b:
        t = 120 if x % 120 == 0 and x + 120 <= b else 60 if x % 60 == 0 and x + 60 <= b else BLOCK
        out.append((x, t))
        x += t
    return out


def _stone(ep, i, key, big):
    state = "cut" if ep.watched else "raw" if ep.cards > 0 else "rock"
    dim = not ep.cards > 0 and not ep.watched and not ep.in_top
    return Stone(i, state, big, dim, variant(key, i), bool(ep.missing), bool(ep.removed))


def plan(episodes, next_index=None, media=None, key="", mix=False):
    """The string's plan for a row's files (`view_rows.Episode`s, the piece's own, in order) — immutable and hashable,
    so the row cache can key on it. `next_index`: the row's next file (`Row.next_index`; None → the first not
    watched); `key`: the row's key (the stones' variants); `mix`: hato's mix (sapphire)."""
    eps = tuple(episodes)
    n = len(eps)
    gem = gem_of(media, mix)
    watched = sum(1 for e in eps if e.watched)
    in_anki = sum(1 for e in eps if e.cards > 0)
    first = next((i for i, e in enumerate(eps) if not e.watched), None)
    at = first if next_index is None else max(0, min(n - 1, next_index))
    nxt = at if at is not None and n and not eps[at].watched else None
    if n == 0:
        return Plan(gem, (), 0, 0, 0, None, (0, 0), False)
    if n == 1:
        return Plan(gem, (_stone(eps[0], 0, key, nxt == 0),), 1, watched, in_anki, nxt, (0, 1), True)
    if first is None and n % BLOCK == 0:                 # finished, its last twelve whole: its tiers only
        items = tuple(Tier(s, t, variant(key, "t", s)) for s, t in tiers(0, n))
        return Plan(gem, items, n, watched, in_anki, None, (n, n), False)
    if at is None:
        at = n - 1
    s0 = at // BLOCK * BLOCK
    s1 = min(n, s0 + BLOCK)
    items = [Tier(s, t, variant(key, "t", s)) for s, t in tiers(0, s0)]
    items += [_stone(eps[i], i, key, i == nxt) for i in range(s0, s1)]
    if s1 < n:
        rest = eps[s1:]
        m = sum(1 for e in rest if e.cards > 0)
        c = sum(1 for e in rest if e.watched)
        fc = c / len(rest)
        cut_points = 0 if not c else 3 if fc > 2 / 3 else 2 if fc > 1 / 3 else 1
        step = 0 if not m else 3 if m == len(rest) else 1 if m * 2 <= len(rest) else 2
        items.append(Ore(s1, len(rest), m, c, cut_points, step, variant(key, "o", s1)))
    return Plan(gem, tuple(items), n, watched, in_anki, nxt, (s0, s1), False)


def plan_of(row):
    """`plan` for a `view_rows.Row`."""
    return plan(row.episodes, row.next_index, row.media, row.key, row.source == "hato")


# --- layout ------------------------------------------------------------------------------------------------------- #
def _slots(items):
    """Each item's slot (fz 1) and whether it is a watched loose stone (it takes the step) or a cut group followed by
    another (it overlaps)."""
    out = []
    for i, e in enumerate(items):
        if e.kind == "stone":
            out.append((STONE_W, e.state == "cut", False))
        elif e.kind == "tier":
            out.append((TIER_W[e.n], False, i + 1 < len(items) and items[i + 1].kind == "tier"))
        else:
            out.append((ORE_W, False, False))
    return out


def _width(slots, ws, cf):
    """The string's end for the step `ws` and the overlap `cf` (fz 1): linear in both."""
    cur = FIRST_CENTRE - STONE_W / 2
    for w, loose, overlaps in slots:
        w = ws if loose else w
        cur += w * cf if overlaps else w
    return cur + END_PAD


def _fit(slots, room):
    """The loosest (ws, cf) that fits `room` (fz 1), in the order: ws 28 → 14, then cf 1 → .5, then ws 14 → 8; the
    width is linear in each, so each step is solved exactly. -> (ws, cf, shortfall)."""
    nw = sum(1 for _, loose, _ in slots if loose)
    over = sum(w for w, _, o in slots if o)
    if _width(slots, STONE_W, 1) <= room:
        return STONE_W, 1.0, 0.0
    # each step runs only when the one before it didn't fit, so its solution lies inside its own range: nw > 0 where
    # the step moved the width, over > 0 where the overlap did
    if _width(slots, STEP_CLOSER, 1) <= room:
        return (room - _width(slots, 0, 1)) / nw, 1.0, 0.0
    if _width(slots, STEP_CLOSER, OVERLAP_MIN) <= room:
        return STEP_CLOSER, (room - _width(slots, STEP_CLOSER, 0)) / over, 0.0
    if _width(slots, STEP_LAST, OVERLAP_MIN) <= room:
        return (room - _width(slots, 0, OVERLAP_MIN)) / nw, OVERLAP_MIN, 0.0
    return STEP_LAST, OVERLAP_MIN, _width(slots, STEP_LAST, OVERLAP_MIN) - room


@lru_cache(maxsize=1024)
def layout(plan_, width, fz=1.0):
    """The string laid out in `width` logical px at text size `fz`: each item's centre, the string's end, the step and
    the overlap it took, and the shortfall when it still doesn't fit (stones never shrink)."""
    slots = _slots(plan_.items)
    if not slots:
        return Layout((), 0.0, STONE_W * fz, 1.0, True, 0.0)
    ws, cf, short = _fit(slots, width / fz)
    xs, cur = [], FIRST_CENTRE - STONE_W / 2
    for w, loose, overlaps in slots:
        w = ws if loose else w
        xs.append((cur + w / 2) * fz)
        cur += w * cf if overlaps else w
    return Layout(tuple(xs), (cur + END_PAD) * fz, ws * fz, cf, short <= 0, max(0.0, short) * fz)


def tightest(plan_):
    """The string's width at its tightest (fz 1)."""
    return _width(_slots(plan_.items), STEP_LAST, OVERLAP_MIN)


def ahead(plan_):
    """Where the string is going (fz 1): its width at the tightest once the twelve in play is done and fuses (the
    page's `r11Ahead`, :7445) — then the next twelve is all still to come and can't overlap, so the title column is
    decided for that too and doesn't narrow in the middle of a fuse. 0 when nothing comes after the twelve."""
    n, (_, s1) = plan_.n, plan_.twelve
    if plan_.single or s1 >= n:
        return 0.0
    one = min(BLOCK, n - s1)
    slots = [(TIER_W[t], False, False) for _, t in tiers(0, s1)]
    slots = [(w, False, i + 1 < len(slots)) for i, (w, _, _) in enumerate(slots)]
    slots += [(STONE_W, False, False)] * one + ([(ORE_W, False, False)] if n - s1 - one > 0 else [])
    return _width(slots, STEP_LAST, OVERLAP_MIN)


@lru_cache(maxsize=32)
def _title_width(plans, list_width, fz, fixed_columns, string_fz):
    base, floor = round(TITLE_BASE * fz), round(TITLE_FLOOR * fz)
    room = list_width - fixed_columns - base
    short = max((max(tightest(p), ahead(p)) * string_fz - room for p in plans), default=0.0)
    return max(floor, base - math.ceil(short)) if short > .5 else base


def title_width(plans, list_width, fz=1.0, fixed_columns=0, string_fz=None):
    """The one title width for every row: round(187 × fz), less the worst row's shortfall at its tightest (now or
    after its next fuse), never under round(80 × fz). `fixed_columns`: the row's other columns, gaps and padding (all
    but the title and the string); `string_fz`: the string's own scale when it isn't the text size's (the reference
    page keeps the string at its Medium size, 1.15, at every text size). Computed once per (width, text size, the
    rows' plans)."""
    return _title_width(tuple(plans), list_width, fz, fixed_columns, fz if string_fz is None else string_fz)


# --- words -------------------------------------------------------------------------------------------------------- #
def words(plan_):
    """What a screen reader says for the string, over the whole piece: "8 of 12 watched, 3 in Anki"."""
    if not plan_.n:
        return ""
    if plan_.single:
        parts = [WORDS["one_watched"] if plan_.watched else WORDS["one_not"]]
        if plan_.in_anki:
            parts.append(WORDS["one_in_anki"])
    else:
        parts = [WORDS["of_watched"].format(k=plan_.watched, n=plan_.n)]
        if plan_.in_anki:
            parts.append(WORDS["in_anki"].format(n=plan_.in_anki))
    return WORDS["join"].join(parts)
