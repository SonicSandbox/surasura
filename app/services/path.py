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
- **Done before the guide counts** (Kantan-S2, Sonic 2026-11-13: "if they already did one…"): cards mined with Anki
  Miner before Connect kept a ledger — a mining session of this language that created cards, in Anki Miner's own
  `stats.db` (`_miner_cards`) — count as cards made; a later step's record is read whether or not the step
  applies now (a book lined up once, with none in Current today, is done — never offered as new).
- **Four stages** (Mado-EZP, SPEC-r2 EZ2-1 / §0.9, Sonic ruled 2026-11-18; every word PROVISIONAL): the same steps,
  grouped as *Your path* draws them — ① On board (setup: done once there is a library), ② First episode (`words`,
  `watch`), ③ Automate (`cards`, `junban`, `backfill`; the review loop's step goes last here, WL-9), ④ Make it yours
  (`yours`: which words get a card). `audiobook`, `hato` and `piyo` stay later steps, outside the stages. A step's
  `chapter` keeps its card rule (chapter 1's comes back at the next start; a later one's *Not now* is for good);
  `stage_states` says each stage's state for the string of four stones (`DONE` · `NOW` · `LATER`).
- **The panel's one list** (`listed`): the stage to do now (its steps, and a later step useful now), the later stages
  (and the later steps that can't apply yet: no Anki, no book, no waiting video, too few episodes), then what's done
  (kept, to try again) — never a step whose module is missing or switched off (`offered`, S10).
- **The Next card** (`next_card`): chapter 1's first undone step (*Not now* hides it until the next start — it is the
  loop itself); then *Your first cards are made*, once; then a chapter-2 step that has become useful and was never set
  aside (*Not now* there is for good: it lives on in ✦ → *Your path*). One at a time; never during setup.
- **④ only for a new path** (`yours_card`, decided once at this code's first look): a path past chapter 1 then never
  sees ④'s card — for it, *Make it yours* sits in ✦ only (round 1's #7). **For now no path sees it** (`YOURS_CARD`
  off; Sonic 2026-11-20, train 51's keeper decision 1): ④ points at *Words to make cards from*, the choice the mining
  model retires (Kantan-MO, `tracks/logic/work/mining-ordering/MODEL.md`), and its *Only i+1* is the off-list cards'
  trap. The step stays in ✦'s list and the string; `yours_card` is still decided and kept, so the switch back on
  (once ④ is re-pointed) gives each path the card its rule says.
- **The glow** (`newly_useful`): a chapter-2 step useful and not yet seen in the panel lights the ✦ (with unseen news);
  never the first chapter's (the card carries those), never on a first run.
- **State** in the guide's `guide.json` (per PC, never settings.json, never sent): `done`, `not_now`, `own_cards`,
  `moments`, `first_ack`, `useful_seen`, `yours_card` — through `guide.update_state` (one writer's lock, atomic, only on
  change).
"""
import os
import sqlite3
import time
from collections import namedtuple

FIRST, READY = "first", "ready"
CHAPTERS = (FIRST, READY)
BOARD, EPISODE, AUTOMATE, YOURS = "board", "episode", "automate", "yours"
STAGES = (BOARD, EPISODE, AUTOMATE, YOURS)       # ① On board · ② First episode · ③ Automate · ④ Make it yours
DONE, NOW, LATER = "done", "now", "later"        # a stage's state on the string
BOOKS = ("book", "lightnovel")                   # a book an audiobook can line up with (never manga or text)

Facts = namedtuple("Facts", "has_library journey_opened episodes_done cards_made own_cards junban anki_synced "
                            "junban_ordered backfilled book_in_current lined_up video_waiting hato_paired piyo_round "
                            "journey_ready yours_picked miner_found", defaults=(True, False, True))
# journey_ready: a journey is on disk (the header's *Journey ↗* shows) — step 1's press has a page to open;
# yours_picked: the learner chose which words get a card (the `yours` moment); miner_found: Anki Miner is here (the
# cards step's press is *Make … cards*, else *Set up Anki Miner*)
def _always(_f):
    return True


Step = namedtuple("Step", "id chapter when done where offered stage", defaults=(_always, None))
# offered: Facts -> bool, whether the step is this learner's at all (its module here and on); else never listed
# where: where *Show me* lights the place its press also lives (only a look: it never presses); stage: its stage, or
# None (a later step outside the four)
PIYO_AFTER = 3                                  # episodes Done before Piyo is offered
YOURS_CARD = False                              # ④'s Next card, off until the mining model re-points it (Sonic 11-20)

# The table (EXPERIENCE.md §3; the stages, SPEC-r2 §0.2 / §0.9). `when` / `done`: Facts -> bool. Chapter 1's steps are
# useful as soon as a library is. `where`: `hero:<part>` Up Next's part, `circle:<name>` a footer circle, `settings:`.
def _cards(f):
    return f.cards_made or f.own_cards


STEPS = (
    Step("words", FIRST, lambda f: f.has_library and f.journey_ready, lambda f: f.journey_opened, "hero:journey",
         stage=EPISODE),
    Step("watch", FIRST, lambda f: f.has_library, lambda f: f.episodes_done >= 1, "hero:done", stage=EPISODE),
    Step("cards", FIRST, lambda f: f.has_library, _cards, "circle:miner", stage=AUTOMATE),
    Step("junban", READY, lambda f: f.junban and f.anki_synced and _cards(f),
         lambda f: f.junban_ordered, "circle:junban", lambda f: f.junban, AUTOMATE),
    Step("backfill", READY, lambda f: f.junban and (f.cards_made or (f.own_cards and f.anki_synced)),
         lambda f: f.backfilled, "settings:backfill_patterns", lambda f: f.junban, AUTOMATE),
    # (WL-9, Mado-WL: the review loop's step joins here, the last of stage ③ after Backfill — not built yet)
    Step("yours", READY, _cards, lambda f: f.yours_picked, "settings:setup_mining", stage=YOURS),
    Step("audiobook", READY, lambda f: f.book_in_current, lambda f: f.lined_up, "tab:current@audiobook"),
    Step("hato", READY, lambda f: f.video_waiting, lambda f: f.hato_paired, "settings:hato"),
    Step("piyo", READY, lambda f: f.episodes_done >= PIYO_AFTER, lambda f: f.piyo_round, "settings:practice_ai"),
)
BY_ID = {s.id: s for s in STEPS}

Status = namedtuple("Status", "step useful done offered", defaults=(True,))   # one step for this learner now
Path = namedtuple("Path", "steps first_done card glow stages facts", defaults=((), None))   # the card's and panel's
# card: None, ("step", step id, stages) for a step — `stages` the four stages' states (`stage_states`), () for a later
# step outside them — or ("made",) for *Your first cards are made*. facts: the `Facts` it was read from (the shell
# names the cards step's press from them: Anki Miner here or not)


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


def _miner_cards(language):
    """Cards Anki Miner made itself, before Connect kept a ledger: a mining session of this language that created
    cards, in Anki Miner's own `stats.db` (`mining_sessions`, written as it mines; read only). Never "Anki Miner
    installed + cards in Anki": a premade deck synced on setup is no card mined (adversary r1 #1). A test run reads it
    only from an `ANKI_MINER_HOME` it set (never the developer's own)."""
    if os.environ.get("SURASURA_TEST_ROOT") and not os.environ.get("ANKI_MINER_HOME"):
        return False
    from app.connect import anki_miner
    db = os.path.join(anki_miner.home(), "stats.db")
    if _one(db, "SELECT 1 FROM mining_sessions WHERE cards_created > 0 AND language = ? LIMIT 1", (language,)):
        return True
    # an Anki Miner from before its `language` column mined Japanese only (its migration fills the old rows 'ja')
    return language == "ja" and _one(db, "SELECT 1 FROM mining_sessions WHERE cards_created > 0 AND NOT EXISTS "
                                         "(SELECT 1 FROM pragma_table_info('mining_sessions') WHERE name = 'language') "
                                         "LIMIT 1")


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
    # a later step's record is read whether or not it applies now (Kantan-S2: done before is done)
    return Facts(
        has_library=has, journey_opened="journey" in (state.get("moments") or {}), episodes_done=episodes,
        cards_made=safe(_cards_made, language) or safe(_miner_cards, language),
        own_cards=bool(state.get("own_cards")), junban=junban,
        anki_synced=synced, junban_ordered=junban and unless("junban", _junban, language, "reorder"),
        backfilled=junban and unless("backfill", _junban, language, "backfill"), book_in_current=book,
        lined_up=unless("audiobook", _lined_up), video_waiting=waiting,
        hato_paired=unless("hato", _hato_paired, language),
        piyo_round=unless("piyo", _piyo_round, language), journey_ready=journey_ready,
        yours_picked="yours" in (state.get("moments") or {}),
        miner_found=True if "cards" in ticked else safe(_miner_found, settings))


def _miner_found(settings):
    """Anki Miner is here (`anki_miner.find`: the path chosen, else where its installer puts it; two file looks). A test
    run looks only under an `ANKI_MINER_HOME` it set (never the developer's own), as `_miner_cards`."""
    if os.environ.get("SURASURA_TEST_ROOT") and not os.environ.get("ANKI_MINER_HOME"):
        return False
    from app.connect import anki_miner
    return bool(anki_miner.find(settings))


# --- the path (pure) ------------------------------------------------------------------------------------------------- #
def statuses(f, state):
    """Every step's `Status` for `Facts` `f`: done if it happened now or was ticked before (kept)."""
    ticked = (state or {}).get("done") or {}
    return tuple(Status(s, bool(s.when(f)), s.id in ticked or bool(s.done(f)), bool(s.offered(f))) for s in STEPS)


def stage_states(sts):
    """The four stages' states, in order (`DONE` · `NOW` · `LATER`): ① On board is done (a path needs a library); a
    stage is done once each of its offered steps is; the first stage not done is `NOW`, the rest `LATER`."""
    out, now = [], False
    for stage in STAGES:
        steps = [st for st in sts if st.step.stage == stage and st.offered]
        if all(st.done for st in steps):
            out.append(DONE)
        elif not now:
            out.append(NOW)
            now = True
        else:
            out.append(LATER)
    return tuple(out)


def listed(sts):
    """The panel's one list (EZ2-1 / EZ2-3): -> (now stage or None, now, later, done) — the steps of the stage to do
    now, and every later step useful and not done; the later stages' steps and the later steps that can't apply yet; the
    done stages' steps and the later steps done (kept, to try again). A step not offered (its module missing or off) is
    in none."""
    states = dict(zip(STAGES, stage_states(sts)))
    stage = next((s for s in STAGES if states[s] == NOW), None)
    now, later, done = [], [], []
    for st in sts:
        if not st.offered:
            continue
        if st.step.stage is not None:
            {NOW: now, LATER: later, DONE: done}[states[st.step.stage]].append(st)
        elif st.done:
            done.append(st)
        elif st.useful:
            now.append(st)
        else:
            later.append(st)
    return stage, now, later, done


def newly_done(sts, state):
    """The step ids done now and not yet kept as done (the worker records them)."""
    ticked = (state or {}).get("done") or {}
    return [st.step.id for st in sts if st.done and st.step.id not in ticked]


def newly_useful(sts, state):
    """Chapter 2's steps useful, not done, never seen in the panel: they light the ✦."""
    seen = set((state or {}).get("useful_seen") or ())
    return [st.step.id for st in sts if st.step.chapter == READY and st.useful and not st.done and st.step.id not in seen]


def next_card(sts, state, later=()):
    """The Next card: ("step", id, stages) · ("made",) · None. `later`: chapter 1's steps set aside this run. `stages`:
    the four stages' states for a step in one of them, () for a later step. ④'s step only on a path that was new
    (`yours_card`)."""
    state = state or {}
    first = [st for st in sts if st.step.chapter == FIRST]
    stages = stage_states(sts)

    def card(st):
        return ("step", st.step.id, stages if st.step.stage is not None else ())
    if not all(st.done for st in first):
        for st in first:
            if not st.done:
                return None if (st.step.id in later or not st.useful) else card(st)
        return None
    if not state.get("first_ack"):
        return ("made",)
    aside = set(state.get("not_now") or ())
    if not (YOURS_CARD and state.get("yours_card")):   # a path past chapter 1 when the stages came: ④ in ✦ only
        aside.add("yours")                             # (and every path while YOURS_CARD is off)
    if READY in later:                                 # a later step set aside this run: no other card until the next
        return None
    for st in sts:
        if st.step.chapter == READY and st.useful and not st.done and st.step.id not in aside:
            return card(st)
    return None


def path(f, state, later=()):
    """`Path` for `Facts` `f`: every step's status, whether chapter 1 is done, the Next card and the glow."""
    sts = statuses(f, state)
    first_done = all(st.done for st in sts if st.step.chapter == FIRST)
    return Path(sts, first_done, next_card(sts, state, later), bool(newly_useful(sts, state)), stage_states(sts), f)


def look(language, settings, view, fresh=False, later=(), seen=False, journey_ready=True):
    """(A worker.) The path now, with what changed recorded (newly done steps kept): -> `Path`, or None while there is
    no library (no path to walk yet). `fresh`: a first run (setup running) — nothing glows; `seen`: the panel opened —
    the useful steps' glow is over; `later`: chapter 1's steps set aside this run."""
    from app.services import guide
    state = guide.read_state()
    f = facts(language, settings, view, state, journey_ready)
    if "path_started" not in state and f.has_library:
        state = _first_look(f)
    if "yours_card" not in state and f.has_library:     # ④'s card: a path new when the stages came (once, kept)
        first_done = all(st.done for st in statuses(f, state) if st.step.chapter == FIRST)
        guide.update_state(lambda s: s if "yours_card" in s else dict(s, yours_card=not first_done))
        state = guide.read_state()
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
