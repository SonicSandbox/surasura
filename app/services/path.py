"""The feature guide's path (Hoshi-S, PR 2; Kantan-X's model, the 3.0 planning folder's
`tracks/window/work/experience-2026-11-12/EXPERIENCE.md` §3, §6 — every learner-visible choice PROVISIONAL, Sonic's
answers may change it). Qt-free: the Next card on Current (`app/qt/next_card.py`) and the ✦ panel's *Your path* tab
(`app/qt/guide.py`) paint what this says.

- **One table of steps** (`STEPS`): each step's chapter, `when` it is useful, `done` when the real thing happened, and
  `where` *Show me* goes (the anchors `guide.anchor_ok` knows). Two chapters: *Your first cards* (three steps: see the
  words, watch and press Done, get cards made — or *I make my own cards*) and *When you're ready* (five: 順, Backfill, an
  audiobook, hato, Piyo — each shown only once useful; a missing module is never offered, S10).
- **Done is the real thing, read from what the app already keeps** (`facts`, on a worker; each a stat, one small read
  or one read-only `LIMIT 1` query): the journey opened (a guide moment the window writes), an episode Done or a title
  Finished (the window's view), a card Connect made (its ledger's `outcomes`), 順's and Backfill's undo snapshots (each
  writes one before its first change), a finished line-up (Connect's `lineup/<key>/state.json`), a pairing hato wrote
  (the store's `pairings`), a kept Piyo round (`practice_rounds.last_round`, else a round file). Pointing at a place is
  never doing the step. A tick is kept once seen (`guide.json`'s `done`): a record gone later never un-ticks it.
- **The Next card** (`next_card`): chapter 1's first undone step (*Not now* hides it until the next start — it is the
  loop itself); then *Your first cards are made*, once; then a chapter-2 step that has become useful and was never set
  aside (*Not now* there is for good: it lives on in ✦ → *Your path*). One at a time; never during setup.
- **The glow** (`newly_useful`): a chapter-2 step useful and not yet seen in the panel lights the ✦ (with unseen news);
  never the first chapter's (the card carries those), never on a first run.
- **State** in the guide's `guide.json` (per PC, never settings.json, never sent): `done`, `not_now`, `own_cards`,
  `moments`, `first_ack`, `useful_seen` — through `guide.update_state` (one writer's lock, atomic, only on change).
"""
import os
import sqlite3
import time
from collections import namedtuple

FIRST, READY = "first", "ready"
CHAPTERS = (FIRST, READY)
BOOKS = ("book", "lightnovel")                   # a book an audiobook can line up with (never manga or text)

Facts = namedtuple("Facts", "has_library journey_opened episodes_done cards_made own_cards junban anki_synced "
                            "junban_ordered backfilled book_in_current lined_up video_waiting hato_paired piyo_round "
                            "journey_ready", defaults=(True,))
# journey_ready: a journey is on disk (the header's *Journey ↗* shows) — step 1's Show me has a place
Step = namedtuple("Step", "id chapter when done where")

# The table (EXPERIENCE.md §3). `when` / `done`: Facts -> bool. Chapter 1's steps are useful as soon as a library is.
STEPS = (
    Step("words", FIRST, lambda f: f.has_library and f.journey_ready, lambda f: f.journey_opened, "control:journey"),
    Step("watch", FIRST, lambda f: f.has_library, lambda f: f.episodes_done >= 1, "help:current"),
    Step("cards", FIRST, lambda f: f.has_library, lambda f: f.cards_made or f.own_cards, "settings:anki_miner"),
    Step("junban", READY, lambda f: f.junban and f.anki_synced and (f.cards_made or f.own_cards),
         lambda f: f.junban_ordered, "settings:junban"),
    Step("backfill", READY, lambda f: f.junban and (f.cards_made or (f.own_cards and f.anki_synced)),
         lambda f: f.backfilled, "settings:backfill_patterns"),
    Step("audiobook", READY, lambda f: f.book_in_current, lambda f: f.lined_up, "tab:current"),
    Step("hato", READY, lambda f: f.video_waiting, lambda f: f.hato_paired, "settings:hato"),
    Step("piyo", READY, lambda f: f.episodes_done >= 3, lambda f: f.piyo_round, "settings:practice_ai"),
)
BY_ID = {s.id: s for s in STEPS}
PIYO_AFTER = 3                                  # episodes Done before Piyo is offered

Status = namedtuple("Status", "step useful done")                 # one step for this learner now
Path = namedtuple("Path", "steps first_done card glow")            # what the card and the panel show
# card: None, ("step", step id, n, of) for a step, or ("made",) for *Your first cards are made*


# --- the facts (a worker's) ----------------------------------------------------------------------------------------- #
def _ro(path):
    """A read-only connection to an SQLite file that is there (never makes one), or None."""
    if not path or not os.path.isfile(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.2)
    except sqlite3.Error:
        return None


def _one(path, sql, args=()):
    con = _ro(path)
    if con is None:
        return False
    try:
        return con.execute(sql, args).fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _cards_made(language):
    from app.connect import ledger
    return _one(ledger.path(), "SELECT 1 FROM outcomes o JOIN jobs j ON j.id = o.job_id "
                               "WHERE o.outcome = 'made' AND j.language = ? LIMIT 1", (language,))


def _hato_paired(language):
    from app import library_store, path_utils
    try:
        store = library_store.library_db_path(language, path_utils.get_data_path(language))
    except Exception:
        return False
    return _one(store, "SELECT 1 FROM pairings WHERE json_valid(pairing) AND "
                       "coalesce(trim(json_extract(pairing, '$.producer')), 'hato') = 'hato' LIMIT 1")


def _lined_up():
    from app.connect import lineup
    try:
        root = lineup.root()
        keys = os.listdir(root)
    except (OSError, ImportError):
        return False
    import json
    for key in keys[:200]:
        if key == lineup.SPEECH:                       # the speech model's setup: a "line-up" of its own, no book's
            continue
        try:
            with open(os.path.join(root, key, lineup.STATE), encoding="utf-8") as f:
                state = json.load(f) or {}
            if isinstance(state, dict) and lineup.usable(state):
                return True
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return False


def _junban(language, kind):
    """順's or Backfill's real run on this language: Junban's own answer for a reorder (`undo.has_reordered`: never a
    *Try it*, the automatic ones too), the window's Backfill snapshot, or a run of Connect's (its runs folder's names)."""
    from modules.junban import undo
    if kind == "reorder" and undo.has_reordered(language):
        return True
    if kind == "backfill" and _user_file(language, undo.FILENAMES["backfill"]):
        return True
    try:
        return any(name.startswith(kind + "-") for name in os.listdir(undo.runs_folder(language)))
    except OSError:
        return False


def _piyo_round(language):
    from app import practice_rounds
    last = getattr(practice_rounds, "last_round", None)         # Kantan-B2's read (#406), once it has landed
    if last is not None:
        try:
            return last(language) is not None
        except Exception:
            return False
    try:
        folder = practice_rounds.folder(language)
        return any(n.endswith(".json") for n in os.listdir(folder))
    except OSError:
        return False


def _user_file(language, name):
    from app import path_utils
    return os.path.isfile(os.path.join(path_utils.get_user_files_path(language), name))


def _view_facts(view):
    """(has a library, episodes Done, a book in Current, a video waiting for subtitles) from the window's frozen view."""
    rows = tuple(getattr(view, "rows", ()) or ())
    counts = getattr(view, "counts", None)
    finished = getattr(counts, "finished", 0) or 0
    episodes = sum(getattr(r, "n_watched", 0) or 0 for r in rows) + finished
    book = any(getattr(r, "media", None) in BOOKS for r in rows)
    waiting = any((getattr(a, "waiting", 0) or 0) > 0 for a in getattr(view, "arrivals", ()) or ())
    has = (bool(rows) or bool(finished) or bool(getattr(counts, "goal_titles", 0))
           or bool(getattr(view, "arrivals", ())))
    return has, episodes, book, waiting


def facts(language, settings, view, state, journey_ready=True):
    """(A worker.) This learner's `Facts` now. Each check that fails reads as not done / not useful — never a crash. A
    step ticked already is never read again (S19): its record's check is skipped."""
    from app.services import help_cards
    settings, state = settings or {}, state or {}
    has, episodes, book, waiting = _view_facts(view)
    ticked = state.get("done") or {}

    def safe(fn, *args):
        try:
            return bool(fn(*args))
        except Exception:
            return False

    def unless(step_id, fn, *args):
        return True if step_id in ticked else safe(fn, *args)

    try:
        from app import anki_sync
        synced = bool(anki_sync.load_state(language).get("last_sync"))
    except Exception:
        synced = False
    junban = safe(help_cards.module_present, "junban") and bool(settings.get("enable_junban", True))
    return Facts(
        has_library=has, journey_opened="journey" in (state.get("moments") or {}), episodes_done=episodes,
        cards_made=safe(_cards_made, language), own_cards=bool(state.get("own_cards")), junban=junban,
        anki_synced=synced, junban_ordered=junban and unless("junban", _junban, language, "reorder"),
        backfilled=junban and unless("backfill", _junban, language, "backfill"), book_in_current=book,
        lined_up=book and unless("audiobook", _lined_up), video_waiting=waiting,
        hato_paired=waiting and unless("hato", _hato_paired, language),
        piyo_round=episodes >= PIYO_AFTER and unless("piyo", _piyo_round, language), journey_ready=journey_ready)


# --- the path (pure) ------------------------------------------------------------------------------------------------- #
def statuses(f, state):
    """Every step's `Status` for `Facts` `f`: done if it happened now or was ticked before (kept)."""
    ticked = (state or {}).get("done") or {}
    return tuple(Status(s, bool(s.when(f)), s.id in ticked or bool(s.done(f))) for s in STEPS)


def newly_done(sts, state):
    """The step ids done now and not yet kept as done (the worker records them)."""
    ticked = (state or {}).get("done") or {}
    return [st.step.id for st in sts if st.done and st.step.id not in ticked]


def newly_useful(sts, state):
    """Chapter 2's steps useful, not done, never seen in the panel: they light the ✦."""
    seen = set((state or {}).get("useful_seen") or ())
    return [st.step.id for st in sts if st.step.chapter == READY and st.useful and not st.done and st.step.id not in seen]


def next_card(sts, state, later=()):
    """The Next card: ("step", id, n, of) · ("made",) · None. `later`: chapter 1's steps set aside this run."""
    state = state or {}
    first = [st for st in sts if st.step.chapter == FIRST]
    if not all(st.done for st in first):
        for n, st in enumerate(first, 1):
            if not st.done:
                return None if (st.step.id in later or not st.useful) else ("step", st.step.id, n, len(first))
        return None
    if not state.get("first_ack"):
        return ("made",)
    aside = set(state.get("not_now") or ())
    if READY in later:                                 # a later step set aside this run: no other card until the next
        return None
    for st in sts:
        if st.step.chapter == READY and st.useful and not st.done and st.step.id not in aside:
            return ("step", st.step.id, 0, 0)
    return None


def path(f, state, later=()):
    """`Path` for `Facts` `f`: every step's status, whether chapter 1 is done, the Next card and the glow."""
    sts = statuses(f, state)
    first_done = all(st.done for st in sts if st.step.chapter == FIRST)
    return Path(sts, first_done, next_card(sts, state, later), bool(newly_useful(sts, state)))


def look(language, settings, view, fresh=False, later=(), seen=False, journey_ready=True):
    """(A worker.) The path now, with what changed recorded (newly done steps kept): -> `Path`, or None while there is
    no library (no path to walk yet). `fresh`: a first run (setup running) — nothing glows; `seen`: the panel opened —
    the useful steps' glow is over; `later`: chapter 1's steps set aside this run."""
    from app.services import guide
    state = guide.read_state()
    f = facts(language, settings, view, state, journey_ready)
    if "path_started" not in state and f.has_library:
        state = _first_look(f)
    sts = statuses(f, state)
    done = newly_done(sts, state)
    if done:
        day = time.strftime("%Y-%m-%d")
        guide.update_state(lambda s: dict(s, done=dict(s.get("done") or {}, **{i: day for i in done})))
        state = guide.read_state()
    if fresh or seen:
        useful = newly_useful(sts, state)
        if useful:
            guide.update_state(lambda s: dict(s, useful_seen=sorted(set(s.get("useful_seen") or ()) | set(useful))))
            state = guide.read_state()
    if not f.has_library:
        return None
    return path(f, state, later)


def _first_look(f):
    """The path's first look on this PC. A learner who was here before the path (an update) is no beginner: cards made
    → *Your first cards* done and acknowledged; episodes Done → its first two steps done (the journey was there all
    along). A new learner starts at step 1. -> the state."""
    from app.services import guide
    day = time.strftime("%Y-%m-%d")
    first = [s.id for s in STEPS if s.chapter == FIRST]

    def start(s):
        out = dict(s, path_started=day)
        if f.cards_made:
            out.update(done=dict(s.get("done") or {}, **{i: day for i in first}), first_ack=True)
        elif f.episodes_done >= 1:
            out.update(done=dict(s.get("done") or {}, words=day, watch=day))
        return out
    guide.update_state(start)
    return guide.read_state()


# --- the learner's answers (a worker's writes) ---------------------------------------------------------------------- #
def note_moment(name):
    """A guide moment the app keeps no record of (the journey opened): its first time only."""
    from app.services import guide
    return guide.update_state(lambda s: s if name in (s.get("moments") or {}) else
                              dict(s, moments=dict(s.get("moments") or {}, **{name: time.strftime("%Y-%m-%d")})))


def not_now(step_id):
    """*Not now* on a chapter-2 step: set aside for good (it stays in ✦ → *Your path*)."""
    from app.services import guide
    return guide.update_state(lambda s: s if step_id in (s.get("not_now") or ()) else
                              dict(s, not_now=sorted(set(s.get("not_now") or ()) | {step_id})))


def own_cards():
    """*I make my own cards*: step 3 answered for good."""
    from app.services import guide
    return guide.update_state(lambda s: s if s.get("own_cards") else dict(s, own_cards=True))


def first_ack():
    """*Your first cards are made* acknowledged: the card retires."""
    from app.services import guide
    return guide.update_state(lambda s: s if s.get("first_ack") else dict(s, first_ack=True))


def seen_useful(step_ids):
    """The panel showed these chapter-2 steps: their glow is over."""
    from app.services import guide
    ids = set(step_ids)
    return guide.update_state(lambda s: s if ids <= set(s.get("useful_seen") or ()) else
                              dict(s, useful_seen=sorted(set(s.get("useful_seen") or ()) | ids)))
