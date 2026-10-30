"""The phase strip's rules (Sonic, 2026-10-23, build 6's *phase strip*; the scope `work/phase-strip/scope.md`): which
of the five circles at the bar's bottom left each piece of work lights, and in what state. Qt-free;
`app/qt/phase_strip.py` paints it.

- **The circles**, left to right: 届 arrivals (looks, imports, copies, the library's upkeep) · ス Surasura (Generate,
  the indexer, the sentence dictionary, the journey) · Anki Miner (Connect making cards) · 順 Junban (its reorder,
  the re-order host, Backfill — scope Q2) · Anki (the sync, the backlog read, a known-words import).
- **What lights one:** the registry's jobs by their kind (`KINDS`: every kind the window can register names its
  circle, or None — `update`, Koe: no circle, Q7; a test fails on a kind it doesn't name, like `PLACED`), the
  window's presses by their key's first word (`PRESSES`: lit before the job exists; one that failed is the circle's
  failure — its words, red until hovered or the next run: PS-A1), *Needs you*'s entries by
  their source (`SOURCES`; none → no circle, still in Needs you: Q1), and what the window adds itself (`extra`: the
  offline folders → 届's hover (a7: a fact, no decision), a gone folder → 届 amber, moves waiting on a busy store → 届
  queued).
- **Its state** (`Circle`): `running` (the accent arc turns) · `waiting` (queued or held: a still arc) · `needs` (it
  waits on you: amber) · `failed` (red until hovered — `seen` — or the next run: Q3) · `done` (the newest ended run,
  for the 2 s tick the painter shows on the way from lit to dim) — and the hover's `lines` (one per live job, its
  `status.job_line`) and `last` (the newest ended run: done, stopped or failed, with its time).
- **Automatic work shows only after `REVEAL_S`** (Q6: no flicker for a short read): a job the user didn't ask for
  lights its circle once it has run (or waited, a recorded wait) that long; a wait on you shows at once. One never
  shown ends without a tick. A job leaves the status line only once a circle will show it (`placed`, Q5): an
  automatic one held before it starts (a gate, a queue) has no start to count from, so the line keeps it (PS-A2).
- **Amber only with a decision, and where it is** (a7, Sonic 2026-10-29: "If yellow i would expect it to let me go
  somewhere to make a decision that is highlighted. If no decision it shouldn't be yellow but something else."): a
  wait on you counts as `needs` only when it names its place (`Go`): a job's by its kind (`NEEDS_GO`), the window's own
  part with its own. A wait on you that names none is said in the hover and never painted amber; a fact the window
  adds is `info` (words only) and a fault `failed` (red). The press opens `Circle.go` with its row highlighted.
- **A run is a job that ran** (`ran`): one that ended before it started (cancelled while queued, a queued automatic
  job absorbed by yours) or while it waited (a recorded wait that went: an episode now mined) is no *Done*, no tick
  and no failure.
"""
import time
from collections import namedtuple

from app.services import jobs as jobs_module
from app.services.status import job_line

ARRIVALS, SURASURA, MINER, JUNBAN, ANKI = "arrivals", "surasura", "miner", "junban", "anki"
CIRCLES = (ARRIVALS, SURASURA, MINER, JUNBAN, ANKI)
REVEAL_S = 1.0              # an automatic job lights its circle once it has gone on this long (Q6)

# Every job kind the window registers -> its circle (None: no circle). `tests/test_services_phase.py` reads the code
# for the kinds and fails on one missing here.
KINDS = {
    "arrivals-ja": ARRIVALS, "arrivals-zh": ARRIVALS, "library-maintain": ARRIVALS, "extract": ARRIVALS,
    "finished-import": ARRIVALS, "child": ARRIVALS, "youtube": ARRIVALS,
    "library-look": ARRIVALS, "library-copy": ARRIVALS,       # the folder looks and the drop's copies (asked of Kura)
    "generate": SURASURA, "indexer": SURASURA, "sentence-corpus": SURASURA,
    "mine": MINER, "mine-wait": MINER, "anki-miner-install": MINER, "anki-miner-setup": MINER,
    "junban": JUNBAN, "backfill": JUNBAN, "replan": JUNBAN,
    "anki-sync": ANKI, "anki-backlog": ANKI, "anki-session": ANKI, "known-import": ANKI, "mine-anki": ANKI,
    "update": None,
}
# A press's key's first word (`"known:sync"`, `"mine:ja:12"`) -> its circle: lit from the press, before any job
PRESSES = {"known": ANKI, "mine": MINER, "generate": SURASURA, "sources": ARRIVALS}
# A *Needs you* entry's source (`status.Entry.source`) -> its circle: a failure there (red until seen)
SOURCES = {
    "generate": SURASURA, "cli:generate": SURASURA,
    "cli:known-sync": ANKI, "cli:known": ANKI,
    "cli:junban": JUNBAN, "cli:resort": JUNBAN, "cli:backfill": JUNBAN,
}

# a7: where a wait on you is decided — `place` "needs" (the *Needs you* page, at its first card of the kinds `at`) or
# "junban" (順's window, at its control `at`: "deck" · "restore")
Go = namedtuple("Go", "place at")
# The job kinds that wait on you -> where (Connect's mirror, `status.mirror_connect`): its episodes with no video, not
# timed or held by one of its own entries are each a card on *Needs you* — a no-video card, or any card of Connect's
# record (`CONNECT_CARDS`: its needs, whatever their kind); Anki asking for you (a prompt, another profile —
# never Anki closed: a plain wait, `status._waits`) is that page's Anki line
CONNECT_CARDS = "connect"
NEEDS_GO = {
    "mine-wait": Go("needs", ("no-video", CONNECT_CARDS)),
    "mine-anki": Go("needs", ("anki-wait",)),
}

Circle = namedtuple("Circle", "running waiting needs failed done lines last go", defaults=(None,))
IDLE = Circle(False, False, None, None, None, (), None)
Ended = namedtuple("Ended", "state words at id")       # the hover's last line: `state` "done" · "stopped" · "failed"


def circle_of(view):
    """The circle `view` (a job view) lights, or None."""
    return KINDS.get(getattr(view, "kind", None))


def press_circle(key):
    """The circle a press of `key` lights, or None."""
    word = key[0] if isinstance(key, tuple) and key else str(key).split(":", 1)[0]
    return PRESSES.get(word)


def ran(view):
    """Whether an ended job ran: one cancelled before it started (no start time) or that ended while it waited (a
    recorded wait: its reason kept) didn't."""
    return view.started_at is not None and view.reason is None


def shown(view, now):
    """Whether `view` (live) lights its circle now: the user's at once; an automatic one once it has gone on
    `REVEAL_S` (a wait on the user at once)."""
    if not view.automatic or view.needs:
        return True
    return view.started_at is not None and now - view.started_at >= REVEAL_S


def placed(view):
    """Whether a circle shows `view`, now or by the clock alone (the status line leaves it out: Q5) — not an automatic
    job that hasn't started (held by a gate or queued: `shown` counts from its start, PS-A2)."""
    return circle_of(view) is not None and (not view.automatic or bool(view.needs) or view.started_at is not None)


def reveal_at(views, now):
    """When the next automatic job not shown yet will be (the painter looks again then), or None."""
    due = [v.started_at + REVEAL_S for v in views
           if v.state in jobs_module.LIVE and circle_of(v) and v.started_at is not None and not shown(v, now)]
    return min(due) if due else None


def fold(last, views):
    """{circle: the newest ended job view that ran} — `last` (the painter's, kept across snapshots: the registry keeps
    only its newest 20 ended) updated with `views`. -> a new dict (or `last` itself when nothing newer came)."""
    out = None
    for v in views:
        circle = circle_of(v)
        if circle is None or v.state not in (jobs_module.DONE, jobs_module.FAILED) or v.ended_at is None:
            continue
        if not ran(v) and not v.needs:
            continue
        held = (out or last).get(circle)
        if held is None or (v.ended_at, v.id) > (held.ended_at, held.id):
            if out is None:
                out = dict(last)
            out[circle] = v
    return last if out is None else out


def ended(view):
    """The hover's last line of an ended job view."""
    if view.state == jobs_module.FAILED:
        return Ended("failed", view.message or "", view.ended_at, view.id)
    if view.needs:
        return Ended("needs", view.needs, view.ended_at, view.id)
    return Ended("stopped" if view.cancelled else "done", view.message or "", view.ended_at, view.id)


def read(views, presses=(), entries=(), extra=None, last=None, seen=frozenset(), now=None):
    """{circle: Circle} now. `views`: the registry's snapshot; `presses`: the window's live presses (each with `key`,
    `state`, `words`: the live ones and those that failed); `entries`: *Needs you*'s (`status.Entry`); `extra`:
    {circle: [(state, words[, go])]} the window adds (`state` "waiting" · "running" · "needs" — amber only with its `go`,
    a7 — · "info" · "failed"); `last`: `fold`'s; `seen`: the
    failures and ended waits on you looked at (their job ids, `("entry", text, at)` or `("press", key)`); `now`: the
    wall clock (time.time())."""
    now = time.time() if now is None else now
    last = last or {}
    got = {c: {"running": False, "waiting": False, "needs": [], "failed": None, "lines": [], "go": None}
           for c in CIRCLES}
    live = {c: False for c in CIRCLES}
    for v in views:
        circle = circle_of(v)
        if circle is None or v.state not in jobs_module.LIVE:
            continue
        g = got[circle]
        g["lines"].append(job_line(v))
        if not shown(v, now):
            continue
        live[circle] = True
        if v.needs and NEEDS_GO.get(v.kind):
            g["needs"].append(v.needs)
            g["go"] = g["go"] or NEEDS_GO[v.kind]
        elif v.needs:
            g["waiting"] = True                 # (a wait on you naming no place: a plain wait, its words in the hover)
        elif v.state in (jobs_module.RUNNING, jobs_module.CANCELLING):
            g["running"] = True
        else:
            g["waiting"] = True
    for p in presses:
        circle = press_circle(p.key)
        if circle is None:
            continue
        if p.state == jobs_module.FAILED:
            if ("press", p.key) not in seen and got[circle]["failed"] is None:
                got[circle]["failed"] = p.words or "failed"
            continue
        if not p.live():
            continue
        live[circle] = True
        if p.state in (jobs_module.RUNNING, jobs_module.CANCELLING):
            got[circle]["running"] = True
        else:
            got[circle]["waiting"] = True
    for circle, parts in (extra or {}).items():
        g = got.get(circle)
        if g is None:
            continue
        for state, words, *go in parts:
            go = go[0] if go else None
            if words and state != "failed":     # (a fault's words are its `failed`: said once)
                g["lines"].append(words)
            if state == "needs" and go is not None:
                g["needs"].append(words)
                g["go"] = g["go"] or go
            elif state == "failed":
                g["failed"] = g["failed"] or words or "failed"
            elif state == "running":
                g["running"] = live[circle] = True
            elif state == "waiting":
                g["waiting"] = live[circle] = True
    for e in entries:
        circle = SOURCES.get(getattr(e, "source", None))
        if circle is None or e.seen or ("entry", e.text, e.at) in seen:
            continue
        if got[circle]["failed"] is None:
            got[circle]["failed"] = e.text
    out = {}
    for circle in CIRCLES:
        g = got[circle]
        end = last.get(circle)
        tail = ended(end) if end is not None else None
        failed, done, needs, go = g["failed"], None, list(g["needs"]), g["go"]
        if tail is not None and not live[circle]:
            if tail.state == "failed" and end.id not in seen:
                failed = failed or tail.words or "failed"
            elif tail.state == "needs" and end.id not in seen and NEEDS_GO.get(end.kind):
                needs.append(tail.words)
                go = go or NEEDS_GO[end.kind]
            elif tail.state == "done":
                done = end.id
        if live[circle]:
            failed = None                       # the next run under way: the failure before it is over (Q3)
        out[circle] = Circle(g["running"], g["waiting"] and not g["running"], "; ".join(needs) or None, failed,
                             done, tuple(g["lines"]), tail, go if needs else None)
    return out
